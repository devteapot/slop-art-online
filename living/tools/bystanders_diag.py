#!/usr/bin/env python3
"""Witnessed-fight comparison. Run under flock ~/slop-mq/battle.lock and build-slot."""
import argparse
from contextlib import nullcontext
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".agents/skills/verify-minds/scripts"))
import verify_minds as vm
from bystanders_spend import PAID_END, watch

V = vm.shared
sys.path.insert(0, str(ROOT / ".agents/skills/verify/scripts"))
import verify as harness


def arm(label, first_sight, candidate, target, source, proxy):
    run = vm.Run(f"minds-bystanders-1-{label}")
    try:
        run.harness("launch", "--seed", "island", "--target-dir", target)
        run.harness("doctor")
        owner = harness.admin_token()
        status, body = harness.http(f"/v1/database/{run.db}/call/install_script", [source], owner)
        run.note(f"install archived play8 script plus trial flag -> {status}")
        if status != 200:
            raise RuntimeError(f"install_script: {status} {body}")
        run.admin("set_world_law", "first_sight_thinks", str(first_sight).lower())
        run.admin("set_world_law", "cues_on", "false")
        run.admin("set_world_law", "profile_detail", "true")
        if first_sight:
            run.admin("set_world_law", "first_sight_gap_s", "0")

        def player(token, reducer, *args):
            status, body = harness.http(f"/v1/database/{run.db}/call/{reducer}", args, token)
            run.note(f"player {reducer} {args} -> {status} {body}")
            if status != 200:
                raise RuntimeError(f"{reducer}: {status} {body}")

        def join(name):
            status, body = harness.http("/v1/identity", {})
            if status != 200:
                raise RuntimeError(f"identity: {status}")
            token = json.loads(body)["token"]
            player(token, "join", name)
            actor = run.sql(f"SELECT id FROM character WHERE name = '{name}'", name)[0]["id"]
            return token, actor

        attacker_token, attacker = join("TrialStriker")
        victim = run.sql("SELECT id FROM character WHERE name = 'Aldric Marrow'", "victim")[0]["id"]
        # Stage on the play8 road near Aldric’s spouse and daughter and two Fenners.
        run.admin("set_behavior", victim, json.dumps({"wait": 120}))
        run.admin("place_at", attacker, 398.5, 253.5)
        origin = run.private(f"SELECT x, y FROM body WHERE id = {attacker}", "arrival")[0]
        x, y = origin["x"], origin["y"]
        names = ["Cuth Marrow", "Maud Marrow", "Agnes Fenner", "Bram Fenner"]
        residents = [run.sql(f"SELECT id, name FROM character WHERE name = '{name}'", f"resident-{i}")[0]
                     for i, name in enumerate(names)]
        ids = [r["id"] for r in residents]
        (run.directory / "cast.json").write_text(json.dumps({
            "attacker": attacker, "victim": victim, "residents": residents,
            "first_sight": first_sight, "cues": False, "candidate": candidate,
        }, indent=2))
        offsets = [(-4, 0), (5, 0), (0, -10), (0, 12)]
        # Start the model before staging the strangers so a first-sight request can be consumed.
        if proxy:
            models = json.loads((ROOT / "living/configs/models.json").read_text())
            # The verify helper's startup check needs a concrete default profile. Keep
            # the play8 per-purpose routing explicitly assigned to each study resident.
            models["default"] = "glm-flash"
            models["assign"].update({name: "people" for name in names})
            models["profiles"] = {k: v for k, v in models["profiles"].items() if k in ("glm-flash", "deepseek-flash")}
            for profile in models["profiles"].values():
                profile.update(base_url=proxy, key_env="LIVING_VERIFY_FAKE_KEY")
        else:
            models = vm.model(run, {"rules": [{
                "purpose": "deliberate", "contains": "diagnostic prompt probe", "times": -1,
                "reply": {"graph": "keep", "plan": "Fixture shows refusal",
                          "acts": [{"do": "go", "target": {"place": "home"}}]},
            }], "replies": {
                "think": {"thought": "Fixture response. I wait.", "intend": ["wait"], "say": None},
                "deliberate": {"graph": "keep", "plan": "Fixture waits"},
                "consolidate": {"summary": "Fixture remembers.", "nodes": [], "edges": []},
                "talk": {"thought": "Fixture listens.", "say": None, "end": True},
            }})
        run.start(models, ids, seed="island", extra_env={"LIVING_RETHINK": "off", "LIVING_CONCURRENCY": "8"})
        for ident in ids:
            run.admin("set_behavior", ident, json.dumps({"desires": [
                {"want": "stay here", "weight": {"base": 10}, "do": {"wait": 120}}
            ]}))
        # Stay past the 20 s species throttle of any opening thought before introducing the
        # players. Both arms wait the same time.
        time.sleep(25)
        for dx, dy in [(1, 0), (0, 1), (-1, 0), (0, -1)]:
            run.admin("place_at", victim, x + dx, y + dy)
            body = run.private(f"SELECT * FROM body WHERE id = {victim}", "target-body")[0]
            if 0.5 <= math.dist((x, y), (body["x"], body["y"])) <= 1.6:
                break
        else:
            raise RuntimeError("no standing position in strike reach")
        for ident, (dx, dy) in zip(ids, offsets):
            run.admin("place_at", ident, x + dx, y + dy)
        run.admin("grant_items", attacker, "spear", 1)
        run.private("SELECT * FROM body", "before-body")
        run.private("SELECT * FROM slumber", "before-slumber")
        run.private(f"SELECT * FROM vitals WHERE id = {victim}", "before-vitals")
        run.private("SELECT * FROM deliberation", "before-deliberation")
        run.private("SELECT * FROM thought", "before-thought")
        run.admin("set_world_law", "trial_salient_events_think", str(candidate).lower())
        run.private("SELECT * FROM world_law", "law-overrides")
        run.admin("set_profile", True)
        run.private("SELECT last_ms FROM clock", "fight-start-clock")
        player(attacker_token, "human_face", body["x"] - x, body["y"] - y)
        player(attacker_token, "use_skill", "strike", victim, body["x"], body["y"])

        def sample(event, count):
            for i in range(count):
                run.private("SELECT * FROM fight_seen", f"{event}-fight-seen-{i}")
                run.private("SELECT * FROM deliberation", f"{event}-deliberation-{i}")
                time.sleep(0.15)

        sample("first", 8)
        run.admin("set_behavior", victim, json.dumps({"seq": [
            {"do": {"skill": "yield", "target": {"id": attacker}}}, {"wait": 120},
        ]}))
        time.sleep(2)
        run.private(f"SELECT * FROM vitals WHERE id = {victim}", "yield-vitals")
        run.admin("admin_set_vitals", victim, 1.0)
        player(attacker_token, "use_skill", "strike", victim, body["x"], body["y"])
        sample("last", 8)
        time.sleep(25)
        run.private("SELECT * FROM chronicle", "chronicle")
        run.private(f"SELECT id, alive FROM character WHERE id = {victim}", "victim-alive")
        run.private("SELECT last_ms FROM clock", "fight-end-clock")
        run.private(f"SELECT * FROM skill_use WHERE actor = {attacker}", "skill-use")
        run.private(f"SELECT * FROM vitals WHERE id = {victim}", "after-vitals")
        run.admin("set_profile", False)
        run.private("SELECT * FROM thought", "after-thought")
        run.private("SELECT * FROM deliberation", "after-deliberation")
        run.private("SELECT * FROM act_outcome", "after-act-outcome")
        run.private("SELECT * FROM body", "after-body")
        run.command([ROOT / "living/tools/stdb", "logs", "-s", "local", run.db, "-n", "500"],
                    filename="authority.log")
        for ident in ids:
            run.private(f"SELECT * FROM experience WHERE observer = {ident}", f"experience-{ident}")
            run.private(f"SELECT * FROM activity WHERE id = {ident}", f"activity-{ident}")
            run.private(f"SELECT * FROM skill_use WHERE actor = {ident}", f"skill-use-{ident}")
        landed = json.loads((run.directory / "skill-use.json").read_text())
        if not any(row["accepted_ms"] and "hit for" in row["outcome"] for row in landed):
            raise RuntimeError(f"{label}: missing first hit; see skill-use.json")
        chronicle = json.loads((run.directory / "chronicle.json").read_text())
        if not any(row["kind"] == "killing" and row["b"] == victim and "had yielded" in row["text"]
                   for row in chronicle):
            raise RuntimeError(f"{label}: missing killing after yield; see chronicle.json and skill-use.json")
        # Separately force an unrelated thought after the snapshot. This probes whether a
        # percept survives into an ordinary prompt, without counting it as a fight wake.
        if not proxy and not first_sight and not candidate:
            for ident in ids:
                run.admin("set_behavior", ident, json.dumps({"think": "diagnostic prompt probe"}))
            time.sleep(55)
            run.private("SELECT * FROM thought", "probe-thought")
            run.private("SELECT * FROM act_outcome", "probe-act-outcome")
            for ident in ids:
                run.private(f"SELECT * FROM experience WHERE observer = {ident}", f"probe-experience-{ident}")
    finally:
        for process in reversed(run.processes):
            V.stop(process)
        if not run.launch_blocked:
            run.harness("cleanup")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--play8-script", type=Path, default=ROOT / ".local/bystanders-1/play8/installed_source.rhai")
    parser.add_argument("--paid", action="store_true")
    args = parser.parse_args()
    if (V.STDB_CONTAINER, V.STDB_URL) != ("slop-trials-stdb", "http://127.0.0.1:3320"):
        parser.error("requires slop-trials-stdb on loopback port 3320")
    first_sight_default = "first_sight_thinks: false, first_sight_gap_s: 300.0,"
    source = args.play8_script.read_text()
    if source.count(first_sight_default) != 1:
        parser.error("unexpected play8 script defaults")
    source = source.replace(first_sight_default, first_sight_default + "\n        trial_salient_events_think: false,")
    law_about = next(line for line in (ROOT / "living/scripts/skills.rhai").read_text().splitlines()
                     if '"trial_salient_events_think" =>' in line)
    source = source.replace('        "earshot" =>', law_about + '\n        "earshot" =>', 1)
    # Absolute deadline is the explicit trial-server handover, even after waiting for the lock.
    cutoff = PAID_END if args.paid else 1795072500  # 2026-11-19 08:15 CET
    audit = ROOT / ".local/bystanders-1" / f"spend-{args.tag}.jsonl"
    watcher = watch(Path.home() / "dev/slop-trials/.env", audit) if args.paid else nullcontext()
    arms = [("base", False, False), ("event", False, True)]
    if not args.paid:
        arms.insert(1, ("first", True, False))
    failures = []
    with watcher as proxy:
        for label, first_sight, candidate in arms:
            if time.time() + 600 >= cutoff:
                raise SystemExit("insufficient time before the trial-server quiet window")
            try:
                arm(f"{args.tag}-{label}", first_sight, candidate, args.target_dir, source, proxy)
            except (RuntimeError, LookupError, OSError) as exc:
                print(f"{label}: {exc}", file=sys.stderr, flush=True)
                failures.append(label)
    if failures:
        raise SystemExit("incomplete arms: " + ", ".join(failures))


if __name__ == "__main__":
    main()
