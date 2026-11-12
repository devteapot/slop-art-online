#!/usr/bin/env python3
"""What the `force_outcomes` law costs in a battle of minds (docs/COMBAT_MIND.md, R2).

    living/tools/outcome_cost.py --run core-RUN [--fighters 20] [--seconds 30]

On a launched verify-core run (`verify.py launch --run core-RUN`), for each arm (the law on,
then off) a fresh battle: `--fighters` minded people (`spawn_crowd(n, true)`: held by the admin
like a mind's, so their outcomes are told), each given a spear and a graph that strikes the
nearest person in reach and else walks to them, packed 1.5 m apart away from the town. Then
`bench.py` times the module's tick spans over `--seconds` (profiled windows, no subscribers) and
this counts what the window wrote: the fighters' outcome lines in `experience` ("You finished: /
You failed to strike…", the told lines) and their `act_outcome` rows, against the blows from the
`stats` counters. The survivors are killed between arms. Writes `RUN/outcome_cost.json`.

Minded fighters have no person playing them, so `act_outcome` rows (written only for a played
character, `outcomes::write`) stay 0 here; a played character's row is one per told line, under
its newest 64 lines (`frame::LINES_SHOWN`). Admin reducers set the scene only.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verify", ROOT / ".agents/skills/verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)
STDB = str(ROOT / "living/tools/stdb")


def sql(db, q):
    out = subprocess.run([STDB, "sql", "--format", "json", "-s", "local", db, q], capture_output=True, text=True, check=True).stdout
    t = json.loads(next(l for l in out.splitlines() if l.startswith("[")))[-1]
    names = [e["name"]["some"] for e in t["schema"]["elements"]]
    return [dict(zip(names, r)) for r in t["rows"]]


def call(db, reducer, *args):
    subprocess.run([STDB, "call", "-s", "local", db, reducer, *[json.dumps(a) for a in args]], capture_output=True, text=True, check=True)


def battle(db, n, spot):
    """`n` minded fighters, placed and armed first; their graphs are set last, all at once."""
    before = {c["id"] for c in sql(db, "SELECT id FROM character")}
    call(db, "spawn_crowd", n, True)
    ids = [c["id"] for c in sql(db, "SELECT id FROM character") if c["id"] not in before]
    for i in ids:
        call(db, "set_behavior", i, json.dumps({"wait": 120}))
    for k, i in enumerate(ids):
        call(db, "place_at", i, spot[0] + (k % 5) * 1.5, spot[1] + (k // 5) * 1.5)
        call(db, "grant_items", i, "spear", 1)
    near = {"nearest": {"kind": "person"}}
    graph = json.dumps({"first": [{"if": {"cond": {"near": {"target": near, "within": 2.2}}, "then": {"do": {"skill": "strike", "target": near}}}},
                                  {"do": {"skill": "goto", "target": near}}]})
    for i in ids:
        call(db, "set_behavior", i, graph)
    return ids


def lines_since(db, cursor, ids, into):
    """New experience rows since `cursor` (by id; read while the window runs, so the lines of
    fighters who die, whose rows go with them, are counted): the fighters' own strike lines."""
    rows = sql(db, f"SELECT id, observer, kind, text FROM experience WHERE id > {cursor}")
    for r in rows:
        into["all"] += 1
        if r["observer"] in ids and r["kind"] == "own":
            if r["text"].startswith("You finished: strike"):
                into["done"] += 1
            elif r["text"].startswith("You failed to strike"):
                into["failed"] += 1
                into["failed_words"][r["text"].split(": ", 1)[-1][:60]] = into["failed_words"].get(r["text"].split(": ", 1)[-1][:60], 0) + 1
            else:
                into["other_own"] += 1
    return max([cursor] + [r["id"] for r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--fighters", type=int, default=20)
    ap.add_argument("--seconds", type=int, default=30)
    a = ap.parse_args()
    st = V.load(a.run)
    db = st["db"]
    land = sql(db, "SELECT arrive_x, arrive_y FROM land")
    spot = (land[0]["arrive_x"] - 60, land[0]["arrive_y"]) if land else (40.0, 40.0)
    out = {"db": db, "fighters": a.fighters, "seconds": a.seconds, "arms": {}}
    for arm, law in (("on", "true"), ("off", "false")):
        call(db, "set_world_law", "force_outcomes", law)
        cursor = max([0] + [r["id"] for r in sql(db, "SELECT id FROM experience")])
        ids = set(battle(db, a.fighters, spot))
        rows0 = len([r for r in sql(db, "SELECT observer FROM act_outcome") if r["observer"] in ids])
        bench_out = V.run_dir(a.run) / f"bench-{arm}.json"
        bench = subprocess.Popen([sys.executable, str(ROOT / "living/tools/bench.py"), "--db", db, "--seconds", str(a.seconds), "--settle", "0", "--out", str(bench_out)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        count = {"all": 0, "done": 0, "failed": 0, "other_own": 0, "failed_words": {}}
        t0 = time.time()
        while bench.poll() is None:
            cursor = lines_since(db, cursor, ids, count)
            time.sleep(0.5)
        span = time.time() - t0
        cursor = lines_since(db, cursor, ids, count)
        b = json.loads(bench_out.read_text())
        rows1 = len([r for r in sql(db, "SELECT observer FROM act_outcome") if r["observer"] in ids])
        alive = sum(1 for c in sql(db, "SELECT id, alive FROM character") if c["id"] in ids and c["alive"])
        out["arms"][arm] = {"law": law, "window_s": round(span, 1), "told_strike_lines": count["done"] + count["failed"], "told_done": count["done"], "told_failed": count["failed"],
                            "told_lines_per_s": round((count["done"] + count["failed"]) / span, 2), "failed_words": count["failed_words"], "other_own_lines": count["other_own"],
                            "experience_rows_per_s": round(count["all"] / span, 1),
                            "act_outcome_rows": rows1 - rows0, "alive_at_end": alive, "bench": b}
        for i in ids:
            subprocess.run([STDB, "call", "-s", "local", db, "kill", str(i), json.dumps("outcome_cost: between arms")], capture_output=True, text=True)
        time.sleep(3)
    call(db, "set_world_law", "force_outcomes", "true")
    path = V.run_dir(a.run) / "outcome_cost.json"
    for arm in out["arms"].values():
        c = arm["bench"].get("combat", {})
        arm["blows_per_s"] = round((c.get("hits", 0) + c.get("dodged", 0) + c.get("blocked", 0)) / a.seconds, 1)
        sp = arm["bench"].get("spans_ms", {})
        arm["summary"] = {"tick": arm["bench"].get("tick_ms"), "combat_span": sp.get("tick.combat"), "activity_span": sp.get("tick.activity"),
                          "experiences_per_s": arm["bench"].get("experiences_per_s"), "people": arm["bench"].get("people")}
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: {x: v for x, v in arm.items() if x != "bench"} for k, arm in out["arms"].items()}, indent=1))
    print(f"evidence: {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
