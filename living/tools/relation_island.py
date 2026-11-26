#!/usr/bin/env python3
"""Select the paired island cast and run one guarded relation-fight arm."""
import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import act_trial
import genesis_wait
import island_fight
import trials

HERE = Path(__file__).resolve().parent
TRIAL = trials.TRIALS / "relation-island.json"
CPUS = "0-4,10-14"


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


@contextmanager
def activity_lock():
    with (Path.home() / "slop-mq/trial-activity.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield


def private_stack():
    if trials.CONTAINER != "relation-island-stdb" or trials.NEO4J != "relation-island-neo4j":
        raise SystemExit("select the private relation-island trial containers")
    if trials.wasm_mount().resolve() != (trials.OUT / "wasm").resolve():
        raise SystemExit("the trial container must mount this checkout's wasm directory")
    for container in (trials.CONTAINER, trials.NEO4J):
        cpus = trials.sh("docker", "inspect", container, "--format", "{{.HostConfig.CpusetCpus}}").stdout.strip()
        if cpus != CPUS:
            raise SystemExit(f"{container} must be pinned to {CPUS}")
    for container, guest, host in ((trials.CONTAINER, 3000, trials.PORT), (trials.NEO4J, 7687, trials.NEO4J_PORT)):
        published = trials.sh("docker", "port", container, f"{guest}/tcp").stdout.strip()
        if published != f"127.0.0.1:{host}":
            raise SystemExit(f"{container} must publish {guest}/tcp at 127.0.0.1:{host}")
    island_fight.URL = trials.URL


def wasm_path():
    name, _, _ = trials.world_seed(trials.load_trial(str(TRIAL))["world"])
    return trials.OUT / "wasm" / f"{name}.wasm"


def pick(out):
    private_stack()
    db = f"{trials.PREFIX}relationpick-{time.time_ns()}"
    token = trials.admin_token()
    with activity_lock():
        trials.sh("docker", "exec", trials.CONTAINER, "spacetime", "publish", "-s", "local",
                  "-b", f"/wasm/{wasm_path().name}", db, "-y")
        try:
            genesis_wait.wait_ready(trials.URL, db, token)
            sql = lambda q: island_fight.sql(db, token, q)
            _, _, member, regard, _, _, _, pairs, exposure = island_fight.exposure_at(db, token)
            neutral = sorted(pair for pair, classification in pairs.items() if classification == "neutral")
            if len(neutral) != 25:
                raise RuntimeError(f"expected 25 neutral pairs, got {len(neutral)}")
            admin = sql("SELECT admin FROM world")[0]["admin"]
            chars = {c["id"]: c for c in sql("SELECT id, name, controller, ai, stage, home_x, home_y FROM character WHERE alive = true AND kind = 'person'")}
            eligible = {i for i, c in chars.items() if c["stage"] and c["ai"] and c["controller"] == admin}
            actors = {a for a, _ in neutral}
            if actors - eligible:
                raise RuntimeError(f"neutral-pair actors are ineligible: {sorted(actors - eligible)}")
            targets = {b for _, b in neutral} & eligible
            chosen = actors | targets
            if len(chosen) > 40:
                raise RuntimeError(f"{len(chosen)} required subjects exceed the 40-mind design")

            def home(i):
                return chars[i]["home_x"], chars[i]["home_y"]

            outlaw_communities = {target for (_, target), (label, _) in regard.items() if label.lower() == "outlaws"}
            ordinary = {i for i in eligible if member.get(i) is not None and member[i] not in outlaw_communities}
            nearest = sorted(ordinary - chosen, key=lambda i: (min(trials.dist(home(i), home(a)) for a in actors), i))
            ids = sorted(chosen | set(nearest[:40 - len(chosen)]))
            if len(ids) != 40:
                raise RuntimeError("fewer than 40 eligible subjects")
            dump(out, {"ids": ids, "neutral_pairs": neutral, "exposure": exposure, "fillers": sorted(set(ids) - chosen),
                       "subjects": {i: chars[i]["name"] for i in ids}})
        finally:
            if not trials.delete_db(db):
                raise RuntimeError(f"could not remove {db}")


def frozen_inputs(subjects):
    return (TRIAL, trials.TRIALS / "variants.json", subjects.resolve(), trials.ROOT / "living/configs/models.json",
            trials.TARGET / "release/living-mind", wasm_path(), trials.ROOT / "living/scripts/skills.rhai")


def manifest(path, subjects):
    entries = {}
    for source in frozen_inputs(subjects):
        with source.open("rb") as stream:
            entries[str(source)] = hashlib.file_digest(stream, "sha256").hexdigest()
    dump(path, entries)


def wait_file(path, process, seconds):
    deadline = time.monotonic() + seconds
    while not path.exists():
        if process.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError(f"{path.name} never appeared (process exit {process.poll()})")
        time.sleep(0.2)


def graph_enemy(value):
    if isinstance(value, dict):
        return value.get("relation") == "enemy" or any(graph_enemy(x) for x in value.values())
    return isinstance(value, list) and any(graph_enemy(x) for x in value)


def side(a):
    private_stack()
    state_path = a.instance / "state.json"
    token = trials.admin_token()
    deadline = time.monotonic() + 1800

    def read_state():
        return json.loads(state_path.read_text())

    while not state_path.exists() or not (a.instance / "world_laws.json").exists():
        if time.monotonic() >= deadline or not act_trial.alive(a.pid):
            raise RuntimeError("trial never reported a configured database")
        time.sleep(0.2)
    db = read_state()["db"]
    ids = json.loads(a.subjects.read_text())["ids"]
    where = " OR ".join(f"actor = {int(actor)}" for actor in ids)
    id_where = " OR ".join(f"id = {int(actor)}" for actor in ids)
    last_fight, last_context, last_chronicle = 0, 0, 0

    def sample(stream, final):
        nonlocal last_fight, last_context, last_chronicle
        now = act_trial.now_ms()
        query = ("SELECT id, kind, a, b, at_ms FROM chronicle "
                 f"WHERE id > {last_chronicle} AND (kind = 'killing' OR kind = 'death')")
        for row in island_fight.sql(db, token, query):
            if row["kind"] == "killing":
                event = {"e": "killing", "a": row["a"], "b": row["b"], "ms": row["at_ms"]}
            else:
                event = {"e": "person_death", "victim": row["a"], "killer": row["b"], "ms": row["at_ms"]}
            stream.write(json.dumps(event) + "\n")
            last_chronicle = max(last_chronicle, row["id"])
        if final or now - last_fight >= 10_000:
            rows = island_fight.sql(db, token, "SELECT actor, other, fight, by, updated_ms FROM relation_fight")
            stream.write(json.dumps({"e": "fight_snapshot", "ms": now, "rows": rows}) + "\n")
            last_fight = now
        if final or now - last_context >= 30_000:
            relations = island_fight.sql(db, token, f"SELECT actor, other, trust, label, updated_ms FROM relation WHERE {where}")
            routines = island_fight.sql(db, token, f"SELECT actor, name, source, graph, updated_ms FROM routine WHERE {where}")
            brains = island_fight.sql(db, token, f"SELECT id, source, graph, installed_ms FROM brain WHERE {id_where}")
            for row in brains:
                row["relation_enemy"] = graph_enemy(json.loads(row["graph"]))
            for row in routines:
                row["relation_enemy"] = graph_enemy(json.loads(row["graph"]))
            stream.write(json.dumps({"e": "context", "ms": now, "relations": relations, "routines": routines, "brains": brains}) + "\n")
            last_context = now
            if not a.ready.exists():
                stream.flush()
                a.ready.touch(exist_ok=False)

    def finished():
        return not act_trial.alive(a.pid)

    island_fight.observe(db, a.arm, token, a.out, 2, finished, deadline, sample)


def report_arm(out):
    switches = json.loads((out / "switches.json").read_text())
    batch, instance = switches["db"][len(trials.PREFIX):].split("-", 1)
    location = trials.OUT / batch / instance
    state = json.loads((location / "state.json").read_text())
    summary = json.loads((location / "summary.json").read_text())
    guard = next((e["final"] for e in reversed(trials.jsonl(out / "guard.jsonl")) if "final" in e), {})
    events = trials.jsonl(out / "events.jsonl")
    begin = int((state.get("t0") or 0) * 1000)
    finish = begin + int(summary["minutes_planned"] * 60_000)
    use = sorted((e for e in events if e["e"] == "use" and e["skill"] in island_fight.ATTACKS
                  and 0 < e["ms"] < finish), key=lambda e: e["ms"])
    attacks = [e for e in use if e["ms"] >= begin and e["skill"] != "threaten"]
    threats = [e for e in use if e["ms"] >= begin and e["skill"] == "threaten"]
    windows = defaultdict(list)
    started = []
    contexts = [e for e in events if e["e"] == "context"]
    fights = [e for e in events if e["e"] == "fight_snapshot"]
    for e in use:
        pair = (e["a"], e["b"])
        reverse = (e["b"], e["a"])
        if (e["ms"] >= begin and e["hostile_people"] and e["skill"] != "threaten"
                and not any(e["ms"] - 60_000 <= t < e["ms"] for t in windows[reverse])):
            context = next((c for c in reversed(contexts) if c["ms"] <= e["ms"]), {})
            fight = next((c for c in reversed(fights) if c["ms"] <= e["ms"]), {})
            relation = next((r for r in context.get("relations", []) if (r["actor"], r["other"]) == pair), None)
            order = next((r for r in fight.get("rows", []) if (r["actor"], r["other"]) == pair), None)
            routines = [r for r in context.get("routines", []) if r["actor"] == e["a"] and r["relation_enemy"]]
            brain = next((r for r in context.get("brains", []) if r["id"] == e["a"]), None)
            started.append(e | {"relation": relation, "fight": order, "enemy_routines": routines,
                                "brain": brain,
                                "relation_band": island_fight.band(relation["trust"], relation["label"]) if relation else None})
        windows[pair].append(e["ms"])
    outcomes = [e for e in events if e["e"] in ("wound", "death", "killing", "person_death") and begin <= e["ms"] < finish]
    deaths = [e for e in outcomes if e["e"] == "death" and e["resident"]]
    kills = [e for e in outcomes if e["e"] == "killing"]
    resident_ids = {death["a"] for death in deaths}
    resident_killings = [kill for kill in kills if kill["b"] in resident_ids]
    by_killer = defaultdict(list)
    for event in outcomes:
        if event["e"] == "person_death" and event["killer"]:
            by_killer[event["killer"]].append(event["ms"])
    spree = sorted(actor for actor, times in by_killer.items() if len(times) >= 3
                   or (len(times) == 2 and abs(times[1] - times[0]) <= 120_000))
    replies = []
    for file in sorted((location / "journal").glob("*.jsonl")):
        for e in trials.jsonl(file):
            if e.get("purpose") != "consolidate":
                continue
            reply = trials.parse_reply(e.get("reply"))
            relations = reply.get("relations") if isinstance(reply, dict) else None
            if not isinstance(relations, list):
                continue
            for row in relations:
                if isinstance(row, dict) and "fight" in row:
                    replies.append({"journal": file.name, "ms": e.get("at_ms"), "relation": row})
    orders = {(r["actor"], r["other"], r["fight"], r["by"], r["updated_ms"])
              for e in fights for r in e["rows"] if begin <= r["updated_ms"] < finish}
    fight_notes = []
    for thought in trials.jsonl(location / "thoughts_all.jsonl"):
        if thought["kind"] != "consolidate" or not begin <= thought["at_ms"] < finish:
            continue
        detail = json.loads(thought["detail"])
        notes = [note for note in detail.get("notes", []) if note.startswith(("fight:", "fight refused:", "relation fight left out:"))]
        if notes:
            fight_notes.append({"actor": thought["actor"], "ms": thought["at_ms"], "notes": notes})
    exit_codes = json.loads((out / "exit.json").read_text())
    poll_errors = sum(e["e"] == "poll_error" for e in events)
    attacks_by_regard = Counter(e.get("regard") for e in attacks if e["hostile_people"])
    threats_by_regard = Counter(e.get("regard") for e in threats if e["hostile_people"])
    return {"batch": batch, "usd": guard.get("usd"), "guard": guard, "stopped_by": summary["stopped_by"],
            "minutes_planned": summary["minutes_planned"], "minutes_sampled": summary.get("minutes_run"),
            "calls": summary.get("calls"), "ids": state.get("roles", {}).get("subject", []),
            "law": summary.get("world_laws", {}).get("relation_fight_on"),
            "manifest_sha256": switches.get("manifest_sha256"), "commit": switches.get("commit"),
            "complete": state["status"] == "done" and summary["stopped_by"] == "duration"
            and summary["minutes_planned"] == 20 and guard.get("status") == "ended"
            and not guard.get("unknown_models") and not any(exit_codes.values()) and not poll_errors and not summary["fake"],
            "poll_errors": poll_errors, "attacks": len(attacks), "threats": len(threats),
            "attacks_on_hostile_people": sum(e["hostile_people"] for e in attacks),
            "threats_on_hostile_people": sum(e["hostile_people"] for e in threats),
            "hostile_attacks_by_regard": attacks_by_regard, "hostile_threats_by_regard": threats_by_regard,
            "wounds_observed": sum(e["e"] == "wound" for e in outcomes),
            "deaths": sum(e["e"] == "death" for e in outcomes),
            "resident_deaths": deaths, "killings": kills, "resident_killings": resident_killings, "sprees": spree,
            "hostile_starts": started, "hostile_starts_by_source": Counter(e["source"] for e in started),
            "hostile_graph_starts_with_enemy_selector": sum(
                e["source"] == "graph" and ((e["brain"] or {}).get("relation_enemy", False) or bool(e["enemy_routines"]))
                for e in started),
            "hostile_starts_with_fight_order": Counter(e["fight"]["fight"] for e in started if e["fight"]),
            "fight_rows": sorted(orders), "fight_rows_by_word": Counter(row[2] for row in orders if row[3] == "mind"),
            "fight_replies": replies, "fight_notes": fight_notes}


def report(a):
    off, on = report_arm(a.off), report_arm(a.on)
    margin = lambda n: n + max(2, math.ceil(n / 4))
    checks = {
        "both_arms_complete": off["complete"] and on["complete"],
        "matching_cast_and_inputs": off["law"] is False and on["law"] is True and len(off["ids"]) == 40
        and off["ids"] == on["ids"] and bool(off["manifest_sha256"]) and off["manifest_sha256"] == on["manifest_sha256"]
        and bool(off["commit"]) and off["commit"] == on["commit"],
        "within_spend_caps": all(arm["usd"] is not None and arm["usd"] <= 2 for arm in (off, on)),
        "no_law_on_sprees": not on["sprees"],
        "no_additional_resident_deaths": {e["a"] for e in on["resident_deaths"]} <= {e["a"] for e in off["resident_deaths"]},
        "no_increase_in_resident_killings": len(on["resident_killings"]) <= len(off["resident_killings"]),
        "hostile_attacks_within_margin": on["attacks_on_hostile_people"] <= margin(off["attacks_on_hostile_people"]),
        "hostile_starts_within_margin": len(on["hostile_starts"]) <= margin(len(off["hostile_starts"])),
        "hostile_threats_within_margin": on["threats_on_hostile_people"] <= margin(off["threats_on_hostile_people"]),
    }
    dump(a.out, {"off": off, "on": on, "checks": checks,
                 "verdict": "eligible to flip default on" if all(checks.values()) else "leave default off"})


def launch(a):
    private_stack()
    snapshot = a.frozen.read_bytes()
    manifest_hash = hashlib.sha256(snapshot).hexdigest()
    entries = json.loads(snapshot)
    if not isinstance(entries, dict) or set(entries) != {str(p) for p in frozen_inputs(a.subjects)}:
        raise SystemExit("the manifest must name every required frozen input")
    if problem := act_trial.frozen_problem(a.frozen, snapshot):
        raise SystemExit(problem)
    ids = json.loads(a.subjects.read_text())["ids"]
    if len(ids) != 40 or ids != trials.load_trial(str(TRIAL))["subject"]["pick"]["ids"]:
        raise SystemExit("trial and frozen subject IDs differ")
    if os.environ.get("TRIALS_VARIANTS"):
        raise SystemExit("unset TRIALS_VARIANTS before launching the frozen trial")
    if not a.fake:
        if not a.allow_live:
            raise SystemExit("a paid arm requires --allow-live")
        if a.minutes is not None or a.guard_extra:
            raise SystemExit("guard overrides and shorter runs require --fake")
        if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], text=True):
            raise SystemExit("commit the frozen plan and tracked inputs before a paid launch")
        plan = subprocess.check_output(["git", "show", "HEAD:docs/RELATION_ISLAND_PAID.md"], text=True)
        if f"manifest_sha256={manifest_hash}" not in plan:
            raise SystemExit("the committed plan does not name this frozen manifest")
    if not a.batch.isascii() or not a.batch.isalnum() or not a.batch.islower() or len(a.batch) > 9:
        raise SystemExit("use a short lowercase ASCII batch name")
    variant = f"relation-fight-{a.arm}"
    inst = f"relation-island-{variant}-r1"
    db = f"{trials.PREFIX}{a.batch}-{inst}"
    batch_dir = trials.OUT / a.batch
    journal = trials.ROOT / ".local/living/journal" / db
    with activity_lock():
        if not a.fake:
            prior = json.loads(a.ledger.read_text())["arms"] if a.ledger.exists() else []
            groups = [entry["group"] for entry in prior]
            if groups != ([] if a.arm == "off" else ["off"]):
                raise SystemExit("the paid ledger permits one off arm followed by one on arm")
        if batch_dir.exists() or journal.exists():
            raise SystemExit("batch or journal already exists")
        a.out.mkdir(parents=True, exist_ok=False)
        journal.mkdir(parents=True)
        ready, pid_file, baseline = a.out / "ready", a.out / "runner.pid", a.out / "baseline.ready"
        pinned = ["taskset", "-c", CPUS, sys.executable]
        guard_cmd = pinned + [str(HERE / "act_trial.py"), "watch", "--arm", a.batch, "--group", a.arm,
                              "--log", str(a.out / "guard.jsonl"), "--ledger", str(a.ledger),
                              "--ready", str(ready), "--pid-file", str(pid_file),
                              "--journal", str(journal / "*.jsonl"), "--frozen", str(a.frozen),
                              "--group-cap", "2", "--total-cap", "4", "--margin", "0.2",
                              "--interval", "1", "--fail-last", "50", "--fail-share", "0.10",
                              "--max-calls-per-min", "240"]
        runner_cmd = pinned + [str(HERE / "trials.py"), "run", "--batch", a.batch, "relation-island",
                               "--variants", variant, "--replicates", "1", "--parallel", "1", "--observer-ready", str(baseline),
                               "--no-commitlog-archive"]
        if a.fake:
            runner_cmd += ["--fake"]
        if a.fake_script:
            runner_cmd += ["--fake-script", str(a.fake_script)]
        if a.minutes is not None:
            runner_cmd += ["--minutes", str(a.minutes)]
        guard_cmd += a.guard_extra
        # Store the exact switches alongside the run without recording its environment.
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dump(a.out / "switches.json", {"runner": runner_cmd, "guard": guard_cmd, "db": db,
                                      "manifest_sha256": manifest_hash, "commit": commit})
        runner = observer = None
        with (a.out / "guard.log").open("w") as log:
            guard = subprocess.Popen(guard_cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            wait_file(ready, guard, 120)
            if problem := act_trial.frozen_problem(a.frozen, snapshot):
                raise RuntimeError(problem)
            with (a.out / "runner.log").open("w") as log:
                runner = subprocess.Popen(runner_cmd, stdout=log, stderr=subprocess.STDOUT)
            pid_file.write_text(str(runner.pid))
            with (a.out / "side.log").open("w") as log:
                observer = subprocess.Popen(pinned + [__file__, "side", a.arm, "--out", str(a.out), "--pid",
                                                     str(runner.pid), "--instance", str(batch_dir / inst),
                                                     "--subjects", str(a.subjects), "--ready", str(baseline)],
                                            stdout=log, stderr=subprocess.STDOUT)
            while runner.poll() is None:
                if guard.poll() is not None:
                    raise RuntimeError(f"guard exited early with status {guard.returncode}")
                if observer.poll() is not None:
                    raise RuntimeError(f"observer exited early with status {observer.returncode}")
                time.sleep(0.2)
            observer.wait(timeout=120)
            guard.wait(timeout=120)
            dump(a.out / "exit.json", {"runner": runner.returncode, "observer": observer.returncode, "guard": guard.returncode})
        finally:
            if runner and runner.poll() is None:
                runner.send_signal(signal.SIGINT)
                runner.wait(timeout=180)
            if observer and observer.poll() is None:
                observer.wait(timeout=120)
            if guard.poll() is None:
                guard.send_signal(signal.SIGINT)
                guard.wait(timeout=30)
            if (batch_dir / inst / "state.json").exists() and not trials.delete_db(db):
                raise RuntimeError(f"could not remove {db}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("pick")
    select.add_argument("out", type=Path)
    freeze = commands.add_parser("manifest")
    freeze.add_argument("path", type=Path)
    freeze.add_argument("--subjects", type=Path, required=True)
    score = commands.add_parser("report")
    score.add_argument("--off", type=Path, required=True)
    score.add_argument("--on", type=Path, required=True)
    score.add_argument("--out", type=Path, required=True)
    for command in ("launch", "side"):
        sub = commands.add_parser(command)
        sub.add_argument("arm", choices=("off", "on"))
        sub.add_argument("--subjects", type=Path, required=True)
        sub.add_argument("--out", type=Path, required=True)
        if command == "side":
            sub.add_argument("--pid", type=int, required=True)
            sub.add_argument("--instance", type=Path, required=True)
            sub.add_argument("--ready", type=Path, required=True)
        else:
            sub.add_argument("--batch", required=True)
            sub.add_argument("--ledger", type=Path, required=True)
            sub.add_argument("--frozen", type=Path, required=True)
            sub.add_argument("--fake", action="store_true")
            sub.add_argument("--allow-live", action="store_true")
            sub.add_argument("--fake-script", type=Path)
            sub.add_argument("--minutes", type=float)
    a, extra = parser.parse_known_args()
    if extra and (a.command != "launch" or not a.fake or extra[0] != "--"):
        parser.error("extra guard arguments require a fake launch and a -- separator")
    if a.command == "launch" and a.fake_script and not a.fake:
        parser.error("--fake-script requires --fake")
    a.guard_extra = extra[1:]
    if a.command == "pick":
        pick(a.out)
    elif a.command == "manifest":
        manifest(a.path, a.subjects)
    elif a.command == "launch":
        launch(a)
    elif a.command == "report":
        report(a)
    else:
        side(a)


if __name__ == "__main__":
    main()
