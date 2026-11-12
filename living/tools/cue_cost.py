#!/usr/bin/env python3
"""What attention cues and the shared answers cost on the authority's own tick (docs/ATTENTION.md,
"Cost"). Free: the fake model or no mind service; scratch `verify-minds-*` databases only.

  cue_cost.py cullet   --run minds-cost-<stamp> [--seconds 120] [--reps 2]
  cue_cost.py crowd216 --run minds-c216-<stamp> [--seconds 180] [--reps 2] [--battle 100] [--walkers 116]

Arms, by world law in one world (`set_world_law`), each a `bench.py` window: cues off and on
(`cues_on`) times the shared answers off and on (`regard_cache`). With `regard_cache` off every
asker computes its answer afresh, which is the code path before the cache. The order is
A B C D, then D C B A, so drift shows as a difference between the two passes.

- `cullet`: seed `cullet`, all its minds on the fake model (think 5 s, compile and consolidation
  4 s, talk 2 s) with Neo4j; each mind's think reply writes the same 8 cues (NOTICE).
- `crowd216`: seed `island`; 216 minded people (`spawn_crowd`): `--battle` of them packed within
  7 m of the battle site (where `spawn_battle` stages one) fighting the nearest person (strike;
  dodge or block when threatened; heal below half, knowing wound_tending), the rest walking as
  foragers; each with the same 8 cues written as its mind would (`mind_update`). No mind service:
  their requests to think stay pending, refreshed with their scene, as under a slow mind. A
  fighter who dies is replaced by a new one at the site (a load-generator respawn, counted per
  window), so the battle keeps its population.

Environment as the verify harness (LIVING_STDB_CONTAINER, LIVING_STDB_URL), and for `cullet`
LIVING_PRIVACY_NEO4J / LIVING_PRIVACY_NEO4J_ENV as verify-minds' privacy.py. Evidence:
`.local/living/verify/<run>/cost.json` and `bench-*.json`.
"""
import argparse
import importlib.util
import json
import os
import random
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("privacy", ROOT / ".agents/skills/verify-minds/scripts/privacy.py")
pv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pv)
vm = pv.vm

WHY = "cost fixture {}"
NOTICE = [
    {"for": "verify_cost", "who": "unknown"},
    {"for": "verify_cost", "who": "unknown", "near_me": 10},
    {"for": "verify_cost", "who": "wolf"},
    {"for": "verify_cost", "who": "deer"},
    {"for": "verify_cost", "thing": "storage", "near_me": 5},
    {"for": "verify_cost", "thing": "fishing_spot"},
    {"for": "verify_cost", "who": "person", "doing": "strike"},
    {"for": "verify_cost", "who": "person", "near_me": 1},
]
ARMS = [("off", False, False), ("off+cache", False, True), ("on", True, False), ("on+cache", True, True)]


def notice():
    return [dict(n, why=WHY.format(i + 1)) for i, n in enumerate(NOTICE)]


def cue_in(n):
    """A `NOTICE` entry as `mind_update` takes it (`CueIn`)."""
    who = n.get("who", "")
    return {"for_key": "stance:" + n["for"], "why": n["why"], "who_id": 0, "who": who, "doing": n.get("doing", ""), "phase": "",
            "thing": n.get("thing", ""), "at": "", "within": 0.0, "near_me": float(n.get("near_me", 0)), "source": "cue_cost"}


def bench(run, label, seconds):
    out = run.directory / f"bench-{label}.json"
    env = dict(os.environ, LIVING_STDB=str(ROOT / "living/tools/stdb"))
    r = subprocess.run([sys.executable, str(ROOT / "living/tools/bench.py"), "--db", run.db, "--seconds", str(seconds), "--settle", "3",
                        "--log-lines", str(seconds * 20000 + 20000), "--out", str(out)], cwd=ROOT, env=env, capture_output=True, text=True)
    (run.directory / f"bench-{label}.log").write_text(r.stdout + r.stderr)
    if r.returncode:
        raise RuntimeError(f"bench {label} failed; see bench-{label}.log")
    return json.loads(out.read_text())


def law(run, name, value):
    run.admin("set_world_law", name, json.dumps(value))


def summary(b, seconds):
    t, sp = b["tick_ms"], b["spans_ms"]
    g = lambda k, f: sp.get(k, {}).get(f)
    return {"ticks_per_s": b["ticks_per_s"], "skipped": max(0, round(60 * b["seconds"] - b["ticks_per_s"] * b["seconds"])),
            "tick_p50": t["p50"], "tick_p95": t["p95"], "tick_p99": t["p99"], "tick_max": t["max"], "over_16_7": t["over_16_7ms"],
            "tick_samples": t["samples"], "max_gap_ms": b.get("max_tick_gap_ms_last_s"), "tick_ms_s": g("tick", "ms_per_s"),
            "slots_ms_s": g("tick.slots", "ms_per_s"), "wakes_ms_s": g("tick.wakes", "ms_per_s"), "combat_ms_s": g("tick.combat", "ms_per_s"),
            "activity_ms_s": g("tick.activity", "ms_per_s"), "cues_per_s": round((sp.get("brain.cues", {}).get("n") or 0) / b["seconds"], 1),
            "cues_ms_s": g("brain.cues", "ms_per_s"), "cues_p99": g("brain.cues", "p99"), "evals_per_s": b["evals_per_s"],
            "experiences_per_s": b["experiences_per_s"], "deliberation_requests_per_s": b["deliberation_requests_per_s"],
            "seen_mean": (b.get("graph_scenes") or {}).get("seen_mean"), "seen_max": (b.get("graph_scenes") or {}).get("seen_max")}


def answers(run, since_ms):
    """The shared answers' hits and computations over a window (the module's per-second line)."""
    logs = subprocess.run([str(ROOT / "living/tools/stdb"), "logs", "-s", "local", run.db, "-n", "200000"], capture_output=True, text=True).stdout
    import re
    from datetime import datetime, timezone
    h = c = 0
    for m in re.finditer(r"^(\S+Z)\s.*regard answers: hits=(\d+) computed=(\d+)", logs, re.M):
        stamp = m.group(1)[:26].rstrip("Z")
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%f" if "." in stamp else "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        if at * 1000 >= since_ms:
            h += int(m.group(2))
            c += int(m.group(3))
    return {"hits": h, "computed": c}


def windows(run, a, extra=None):
    res = {}
    order = ARMS + list(reversed(ARMS)) if a.reps >= 2 else ARMS
    for k, (label, cues, cache) in enumerate(order):
        law(run, "cues_on", cues)
        law(run, "regard_cache", cache)
        time.sleep(5)
        fires0 = sum(c["fires"] for c in run.private("SELECT fires FROM cue", "fires"))
        stats0 = (extra or {}).get("before", lambda: {})()
        t0 = time.time() * 1000
        load0 = os.getloadavg()
        b = bench(run, f"{k + 1}-{label}", a.seconds)
        load1 = os.getloadavg()
        s = summary(b, a.seconds)
        s["cue_fires"] = sum(c["fires"] for c in run.private("SELECT fires FROM cue", "fires")) - fires0
        s["load_1m"] = [round(load0[0], 1), round(load1[0], 1)]
        s.update(answers(run, t0) if cache else {})
        s.update((extra or {}).get("after", lambda x: {})(stats0))
        res[f"{k + 1}-{label}"] = s
        print(label, json.dumps(s), flush=True)
    return res


def cullet(run, a):
    container, uri, pw = pv.neo4j_cfg()
    run.harness("launch", "--seed", "cullet")
    run.harness("doctor")
    law(run, "cues_on", True)
    people = run.sql("SELECT * FROM character WHERE kind = 'person'", "people")
    minds = [p["id"] for p in people if p["ai"] and p["alive"] and p["stage"] >= 1]
    think = {"thought": "cost fixture: I keep to my day.", "intend": [], "say": None,
             "judgments": [{"key": "verify_cost", "value": 0.9, "why": "cost fixture"}], "notice": notice()}
    replies = {"think": think, "deliberate": {"graph": "keep", "plan": "cost fixture"}, "talk": {"thought": "cost fixture", "say": None, "end": True},
               "consolidate": {"summary": "cost fixture", "remember": [], "nodes": [], "edges": [], "retract": [], "merge": [], "identity": None,
                               "relations": [], "judgments": [], "places": []}}
    script = {"replies": replies, "rules": [{"purpose": p, "delay_s": d, "times": -1, "reply": replies[p]} for p, d in (("think", 5.0), ("deliberate", 4.0), ("consolidate", 4.0), ("talk", 2.0))]}
    models = vm.model(run, script)
    run.start(models, minds, seed="cullet", extra_env={"LIVING_NEO4J": "on", "LIVING_NEO4J_URI": uri, "LIVING_NEO4J_PASSWORD": pw, "LIVING_CONCURRENCY": "64"})
    t0 = time.monotonic()
    while time.monotonic() - t0 < a.setup_s and len(run.private("SELECT id FROM cue", "cue-count")) < int(len(minds) * 8 * 0.9):
        time.sleep(10)
    cues = run.private("SELECT * FROM cue", "cues-before")
    head = {"workload": "cullet", "minds": len(minds), "cue_rows": len(cues), "refused": sum(1 for c in cues if c["refused"]), "setup_s": round(time.monotonic() - t0)}
    print(json.dumps(head), flush=True)
    return {**head, "windows": windows(run, a)}


def crowd216(run, a):
    run.harness("launch", "--seed", "island")
    run.harness("doctor")
    law(run, "cues_on", False)
    before = {c["id"] for c in run.sql("SELECT id FROM character", "chars-0")}
    ambient = len(before)
    # The battle site: where spawn_battle stages its fight (the arrival, 20 m north); one probe
    # fighter shows it, then is removed.
    run.admin("spawn_battle", 1)
    probe = [c for c in run.sql("SELECT id FROM character", "chars-probe") if c["id"] not in before]
    site = next(b for b in run.private("SELECT id, x, y FROM body", "bodies-probe") if b["id"] == probe[0]["id"])
    run.admin("kill", probe[0]["id"], "cost probe")
    site = (site["x"], site["y"])
    graph = lambda id: {"first": [
        {"if": {"cond": {"health": {"below": 50}}, "then": {"do": {"skill": "heal", "target": "self"}}}},
        {"if": {"cond": {"threatened": True}, "then": {"do": {"skill": "dodge" if id % 2 == 0 else "block"}}}},
        {"do": {"skill": "strike", "target": {"nearest": "person"}}}]}
    cues = [cue_in(n) for n in notice()]

    def spawn(n):
        have = {c["id"] for c in run.sql("SELECT id FROM character", "chars")}
        run.admin("spawn_crowd", n, True)
        return sorted(c["id"] for c in run.sql("SELECT id FROM character", "chars") if c["id"] not in have)

    def update(id):
        run.admin("mind_update", id, {"persona": None, "relations": [], "beliefs": None, "judgments": [], "places": [], "thought": None, "replace": False, "cues": {"some": cues}})

    def fighter(id):
        run.admin("place_at", id, site[0] + random.uniform(-7, 7), site[1] + random.uniform(-7, 7))
        run.admin("grant_items", id, "spear", 1)
        run.admin("grant_know_how", id, "wound_tending")
        run.admin("set_behavior", id, json.dumps(graph(id)))
        update(id)

    made = spawn(a.battle + a.walkers)
    fighters, walkers = made[: a.battle], made[a.battle:]
    for id in fighters:
        fighter(id)
    for id in walkers:
        update(id)
    refused = sum(1 for c in run.private("SELECT refused FROM cue", "cues-refused") if c["refused"])
    state = {"respawns": 0, "stop": False, "fighters": list(fighters)}

    def keep_battle():
        while not state["stop"]:
            alive = {c["id"] for c in run.sql("SELECT id, alive FROM character", "alive") if c["alive"]}
            dead = [f for f in state["fighters"] if f not in alive]
            for f in dead:
                state["fighters"].remove(f)
            if dead:
                for id in spawn(len(dead)):
                    fighter(id)
                    state["fighters"].append(id)
                    state["respawns"] += 1
            time.sleep(3)

    keeper = threading.Thread(target=keep_battle, daemon=True)
    keeper.start()
    time.sleep(a.warmup)

    def count():
        rows = run.sql("SELECT id, alive, kind FROM character", "census")
        return {"alive": sum(1 for r in rows if r["alive"]), "respawns": state["respawns"]}

    head = {"workload": "crowd216", "ambient_at_publish": ambient, "battle": a.battle, "walkers": a.walkers, "site": site,
            "cue_rows": len(run.private("SELECT id FROM cue", "cue-count")), "refused": refused}
    print(json.dumps(head), flush=True)
    try:
        res = windows(run, a, {"before": count, "after": lambda b: {"alive_end": count()["alive"], "respawned": count()["respawns"] - b["respawns"]}})
    finally:
        state["stop"] = True
        keeper.join(timeout=30)
    return {**head, "windows": res}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workload", choices=["cullet", "crowd216"])
    ap.add_argument("--run", required=True, help="a new run name starting with minds-")
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--setup-s", type=int, default=480)
    ap.add_argument("--warmup", type=int, default=60)
    ap.add_argument("--battle", type=int, default=100)
    ap.add_argument("--walkers", type=int, default=116)
    a = ap.parse_args()
    run = vm.Run(a.run)
    result = {}
    try:
        result = (cullet if a.workload == "cullet" else crowd216)(run, a)
        result["status"] = "done"
    except Exception as error:
        (run.directory / "failure.txt").write_text(traceback.format_exc())
        result = {**result, "status": "fail", "error": f"{type(error).__name__}: {error}"}
    finally:
        result["host"] = {"nproc": os.cpu_count(), "load_end": [round(x, 1) for x in os.getloadavg()]}
        if a.workload == "cullet":
            try:
                container, _, _ = pv.neo4j_cfg()
                pv.cypher(run, container, f"MATCH (n) WHERE n.run = '{run.db}' DETACH DELETE n;", "neo4j-cleanup")
            except Exception as error:
                result["neo4j_cleanup"] = f"failed: {error}"
        run.finish_cleanup()
    (run.directory / "cost.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "windows"}, indent=2))
    return 0 if result.get("status") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
