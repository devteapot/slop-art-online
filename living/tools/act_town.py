#!/usr/bin/env python3
"""Island residents at their daily work given errands as a mind gives them (docs/INPUT_LATENCY.md,
"Mind acts replace"): whether a law on deliberate acts makes residents abandon tasks. Free: no
model; a scratch `verify-minds-*` database on the server LIVING_STDB_URL / LIVING_STDB_CONTAINER
names.

    act_town.py --run minds-town-<stamp> [--minutes 10] [--residents 40] [--every 40] [--seed 1]
                [--law NAME=VALUE ...] [--arm LABEL] [--no-errands]

Seed `island`. `--residents` seeded adults (the admin's AI residents with at least two given
places and a unique name, by id) go about their seeded ways (work, the square, home). This driver
stands in for their minds: at seeded random times (exponential, mean `--every` s; the same
schedule in every arm for one `--seed`) it decides an errand for one of them with `mind_act`, as
the mind service's deliberation does: walk to one of its given places, then to another (two drawn
at random). An errand can come while the last is under way; what happens then is the law's
(`mind_act_replaces`). No mind service runs (residents' requests to think stay pending), so the
fixture's decisions are the only acts. The diagnostic law `latency_acts` is on.

Every second the residents' `activity` rows are sampled (`activities.jsonl.gz`), so each task a
resident starts (a graph's or an act's, by its start time) is seen to its end: done when its last
sample was performing and its end time had come by the next sample, else broken off while
performing or while approaching; a walk (no performing phase) is only counted as ended, its
outcome being its act's (`act_done`) or its routine's (`routine_stat`). At the end
the act markers (`act-trace.jsonl`, act_trace.py) and the residents' `routine_stat` rows before and
after. `town-result.json` summarizes both. Evidence: `.local/living/verify/<run>/`.
"""
import argparse
import gzip
import random
import urllib.request
import importlib.util
import json
import os
import signal
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

import act_trace

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("privacy", ROOT / ".agents/skills/verify-minds/scripts/privacy.py")
pv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pv)
vm = pv.vm
ACT_NODE = 65534  # act.rs `ACT`
# Skills whose activity is a movement to its end (act.rs `moving_skill`, the aside skills).
MOVES = {"goto", "wander", "flee", "follow", "step_aside", "dodge", "jump"}


def interrupted(signum, _frame):
    raise KeyboardInterrupt(f"signal {signum}")


def tasks(samples_path, residents):
    """Each task (resident, skill, node kind, start ms) from the 1 s samples, and how it ended."""
    seen = {}
    order = []
    prev_t = None
    with gzip.open(samples_path, "rt") as f:
        for line in f:
            s = json.loads(line)
            t = s["at_ms"]
            if "error" in s:
                continue
            now = set()
            for a in s["activities"]:
                if a["id"] not in residents:
                    continue
                key = (a["id"], a["skill"], a["started_ms"])
                now.add(key)
                if key not in seen:
                    seen[key] = {"first_ms": t, "node": "act" if a["node"] == ACT_NODE else "graph", "phase": a["phase"], "ends_ms": a["ends_ms"], "gone_ms": None}
                    order.append(key)
                else:
                    seen[key].update(phase=a["phase"], ends_ms=a["ends_ms"])
            for key in order:
                v = seen[key]
                if v["gone_ms"] is None and key not in now and v["first_ms"] < t:
                    v["gone_ms"] = t
            prev_t = t
    out = Counter()
    by_skill = {}
    for key, v in seen.items():
        if v["gone_ms"] is None:
            state = "running_at_end"
        elif key[1] in MOVES:
            # A walk has no performing phase: how it ended is its act's outcome or the routine's.
            state = "ended"
        elif v["phase"] == 1 and v["ends_ms"] <= v["gone_ms"]:
            state = "done"
        elif v["phase"] == 1:
            state = "broken_off_performing"
        else:
            state = "broken_off_approaching"
        out[f"{v['node']}:{state}"] += 1
        by_skill.setdefault(f"{v['node']}:{key[1]}", Counter())[state] += 1
    return {"tasks": dict(out), "by_skill": {k: dict(c) for k, c in sorted(by_skill.items(), key=lambda kv: -sum(kv[1].values()))},
            "last_sample_ms": prev_t}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--residents", type=int, default=40)
    ap.add_argument("--law", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--arm", default="")
    ap.add_argument("--no-errands", action="store_true")
    ap.add_argument("--every", type=float, default=40.0, help="mean seconds between one resident's errands")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    run = vm.Run(a.run)
    signal.signal(signal.SIGTERM, interrupted)
    head = {"arm": a.arm, "laws": a.law, "minutes": a.minutes, "errands": not a.no_errands, "every_s": a.every, "seed": a.seed}
    container = os.environ.get("LIVING_STDB_CONTAINER", "sao-living_spacetimedb_1")
    trace_start = time.time_ns() // 1_000_000
    try:
        target = os.environ.get("CARGO_TARGET_DIR")
        run.harness("launch", "--seed", "island", "--archive-commitlog", "--driver-pid", str(os.getpid()),
                    *(["--target-dir", target] if target else []))
        run.harness("doctor")
        run.admin("set_paused", True)
        run.admin("set_world_law", "latency_acts", "true")
        for law in a.law:
            name, value = law.split("=", 1)
            run.admin("set_world_law", name, value)
        world = run.sql("SELECT * FROM world", "world")[0]
        people = [c for c in run.sql("SELECT * FROM character WHERE kind = 'person'", "people")
                  if c["alive"] and c["stage"] == 2 and c["ai"] and c["controller"] == world["admin"]]
        places = {}
        for p in run.sql("SELECT * FROM place", "places"):
            if p["given"]:
                places.setdefault(p["actor"], set()).add(p["name"])
        names = Counter(c["name"] for c in people)
        chosen = [c for c in sorted(people, key=lambda c: c["id"]) if len(places.get(c["id"], ())) >= 2 and names[c["name"]] == 1][:a.residents]
        if len(chosen) < a.residents:
            raise RuntimeError(f"only {len(chosen)} residents with two given places and a unique name")
        ids = [c["id"] for c in chosen]
        residents = set(ids)
        rng = random.Random(a.seed)
        # The schedule: (seconds after the start, resident, the errand), drawn before the run.
        plan = []
        for c in chosen:
            t = rng.expovariate(1 / a.every)
            while t < a.minutes * 60:
                p1, p2 = rng.sample(sorted(places[c["id"]]), 2)
                plan.append((round(t, 3), c["id"], [{"do": "goto", "target": {"place": p1}}, {"do": "goto", "target": {"place": p2}}]))
                t += rng.expovariate(1 / a.every)
        plan.sort()
        if a.no_errands:
            plan = []
        (run.directory / "residents.json").write_text(json.dumps(ids))
        (run.directory / "errands.json").write_text(json.dumps(plan))
        routines0 = run.private("SELECT * FROM routine_stat", "routine-stat-0")
        import battle_diag
        token = battle_diag.authority_token()
        url = battle_diag.URL
        head.update(residents=len(ids), db=run.db, errands_planned=len(plan))
        calls = Counter()

        def decide(actor, acts):
            body = json.dumps([actor, [json.dumps(x) for x in acts], "town"]).encode()
            req = urllib.request.Request(f"{url}/v1/database/{run.db}/call/mind_act", data=body, method="POST",
                                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    calls[r.status] += 1
            except OSError as e:
                calls[str(e)[:60]] += 1

        run.admin("set_paused", False)
        t0 = time.time()
        head["started_ms"] = int(t0 * 1000)
        nxt = 0
        with gzip.open(run.directory / "activities.jsonl.gz", "wt", compresslevel=3) as out:
            last_sample = 0.0
            while time.time() < t0 + a.minutes * 60:
                while nxt < len(plan) and time.time() - t0 >= plan[nxt][0]:
                    decide(plan[nxt][1], plan[nxt][2])
                    nxt += 1
                if time.time() - last_sample >= 1.0:
                    last_sample = time.time()
                    at = time.time_ns() // 1_000_000
                    try:
                        acts = battle_diag.authority_sql(run, token, "SELECT id, skill, phase, node, started_ms, ends_ms FROM activity")
                        out.write(json.dumps({"at_ms": at, "activities": [x for x in acts if x["id"] in residents]}, separators=(",", ":")) + "\n")
                    except (OSError, ValueError) as e:
                        out.write(json.dumps({"at_ms": at, "error": str(e)}) + "\n")
                time.sleep(0.05)
        head["errand_calls"] = dict(calls)
        head["ended_ms"] = time.time_ns() // 1_000_000
        run.admin("set_paused", True)
        routines1 = run.private("SELECT * FROM routine_stat", "routine-stat-1")
        mine = {r["id"] for r in run.private("SELECT id, actor FROM routine", "routines") if r["actor"] in residents}
        before = {r["id"]: r for r in routines0}
        delta = Counter()
        for r in routines1:
            if r["id"] in mine:
                b = before.get(r["id"], {"ok": 0, "failed": 0})
                delta["ok"] += r["ok"] - b["ok"]
                delta["failed"] += r["failed"] - b["failed"]
        head["routine_outcomes"] = dict(delta)
        head["act_trace_markers"] = act_trace.capture(container, act_trace.newest_replica(container), run.directory / "act-trace.jsonl", trace_start)
        seconds = (head["ended_ms"] - head["started_ms"]) / 1000
        head["acts"] = act_trace.report(run.directory / "act-trace.jsonl", residents, seconds, head["started_ms"], head["ended_ms"])
        head["activity"] = tasks(run.directory / "activities.jsonl.gz", residents)
        hours = seconds / 3600
        gather = head["activity"]["by_skill"].get("graph:gather", {})
        head["gathers_done_per_resident_hour"] = round(gather.get("done", 0) / (len(ids) * hours), 2) if hours else None
        head["status"] = "done"
    except KeyboardInterrupt:
        head["status"] = "interrupted"
    except Exception as error:
        (run.directory / "failure.txt").write_text(traceback.format_exc())
        head["status"] = f"fail: {type(error).__name__}: {error}"
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            run.admin("set_paused", True)
        except Exception:
            pass
        (run.directory / "town-result.json").write_text(json.dumps(head, indent=1))
        run.finish_cleanup()
        print(json.dumps({k: head.get(k) for k in ("status", "arm", "residents", "routine_outcomes", "gathers_done_per_resident_hour")}), flush=True)
    return 0 if head.get("status") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
