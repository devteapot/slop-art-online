#!/usr/bin/env python3
"""Repeat verify_mechanics' "blows land on the yielded, and striking them is news" step on many
pairs at once and trace each: J's yield time (its chronicle row), every blow J felt (its
experiences, with their ms), and whether the "though … had yielded" story entry was written.

    living/tools/yield_race.py --db verify-yield-<stamp> --wasm FILE --pairs 12 --rounds 5 --out DIR

Publishes the world fresh on LIVING_STDB_CONTAINER (default seed), stages `--pairs` pairs a
round with walkers from spawn_crowd, as the mechanics scene does, and writes DIR/rounds.jsonl
and DIR/summary.json. The world is paused and deleted at the end (world_delete.py).
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "living/tools"))
import verify_mechanics as vm  # noqa: E402

idle = json.dumps({"wait": 120})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--wasm", required=True)
    ap.add_argument("--pairs", type=int, default=12)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--fight-s", type=float, default=8.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db = a.db
    vm.stdb("publish", "-s", "local", "-b", f"/wasm/{a.wasm}", db, "--delete-data", "-y")
    import genesis_wait
    genesis_wait.wait_ready_cli(vm.stdb, db)
    time.sleep(3)
    used = set()
    total = {"pairs": 0, "yielded": 0, "news": 0, "missing": 0, "missing_same_ms": 0, "missing_other": 0}
    with (out / "rounds.jsonl").open("a") as f:
        for rnd in range(a.rounds):
            vm.stdb("call", "-s", "local", db, "spawn_crowd", str(2 * a.pairs), "true")
            time.sleep(1.5)
            walkers = sorted(int(r["id"]) for r in vm.rows(db, "SELECT id, name, alive FROM character") if r["name"].startswith("Walker") and r["alive"] == "true" and int(r["id"]) not in used)
            walkers = walkers[: 2 * a.pairs]
            used |= set(walkers)
            pairs = [(walkers[2 * k], walkers[2 * k + 1]) for k in range(len(walkers) // 2)]
            for i, j in pairs:
                vm.call(db, "set_behavior", str(i), idle)
                vm.call(db, "set_behavior", str(j), idle)
            for i, j in pairs:
                vm.call(db, "place_near", str(i), str(j))
                vm.call(db, "set_behavior", str(j), json.dumps({"first": [{"if": {"hurt_within": 10}, "then": {"do": "yield", "target": "attacker"}}, {"wait": 1}]}))
                vm.call(db, "set_behavior", str(i), json.dumps({"first": [{"do": {"skill": "attack", "target": {"id": j}}}, {"wait": 1}]}))
            time.sleep(a.fight_s)
            for i, j in pairs:
                vm.call(db, "set_behavior", str(i), idle)
            time.sleep(1)
            chron = vm.rows(db, "SELECT at_ms, kind, a, b, text FROM chronicle")
            for i, j in pairs:
                ys = sorted(int(r["at_ms"]) for r in chron if r["kind"] == "yield" and int(r["a"]) == j)
                news = [int(r["at_ms"]) for r in chron if r["kind"] == "attack" and int(r["a"]) == i and int(r["b"]) == j and "had yielded" in r["text"]]
                felt = sorted((int(r["at_ms"]), r["text"][:90]) for r in vm.rows(db, f"SELECT at_ms, kind, text FROM experience WHERE observer = {j}") if r["kind"] == "attacked")
                yt = ys[0] if ys else None
                after = [t for t, x in felt if yt is not None and "though you had yielded" in x]
                same = [t for t, x in felt if yt is not None and t == yt and "though you had yielded" not in x]
                row = {"round": rnd, "I": i, "J": j, "yield_ms": yt, "news_ms": news, "blows": felt, "blows_after_yield": len(after), "plain_blow_at_yield_ms": bool(same)}
                if yt is not None and after:
                    total["pairs"] += 1
                    total["yielded"] += 1
                    if news:
                        total["news"] += 1
                    else:
                        total["missing"] += 1
                        total["missing_same_ms" if same else "missing_other"] += 1
                row["verdict"] = "no-yield-or-no-later-blow" if yt is None or not after else ("news" if news else ("MISSING (blow at the yield's ms)" if same else "MISSING (other)"))
                f.write(json.dumps(row) + "\n")
                if row["verdict"].startswith("MISSING"):
                    print(f"round {rnd} I={i} J={j}: {row['verdict']} yield {yt} blows {felt[:6]}", flush=True)
            print(f"round {rnd}: {json.dumps(total)}", flush=True)
    (out / "summary.json").write_text(json.dumps(total, indent=1) + "\n")
    if not a.keep:
        import world_delete
        deleted, why = world_delete.cli_pause_and_delete(lambda *x: subprocess.run([vm.STDB, *x], capture_output=True, text=True), db)
        print(f"{db}: {why}", flush=True)
    print(json.dumps(total))


if __name__ == "__main__":
    main()
