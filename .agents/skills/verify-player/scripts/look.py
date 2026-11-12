#!/usr/bin/env python3
"""A player's own look (look-1, docs/LOOK.md §4): written at `join` from the world's pool, the same
across reconnects, and set by no player reducer.

    look.py --run player-...      (a run launched with verify.py launch --seed plan-test, or any
                                   seed whose `looks` are in force)

The run's player joins (its own identity). Then:
- its `look` row (admin SQL; the table is private) wears the pool entry
  `pool[splitmix64(world.seed ^ id * 0xD1B54A32D192ED03) % len(pool)]` of the run's seed, computed
  here independently of the authority (living_rules::look::pool_pick), and its line is that
  entry's line for the player's band;
- its own `seen_characters` row (`own`), read as the player, carries that line's key, and a
  second read (a new connection with the same identity) gets the same key;
- after every player reducer (`human_move`, `human_act`, `human_say`, `human_speak`,
  `human_face`, `use_skill`, `release_skill`) the `look` row is unchanged, and a second `join` is
  refused;
- in the authority's source, `look` rows are written only in `look.rs` (genesis, spawn, bands,
  relook) and deleted in `perception::gone` (death): no player reducer writes one.
Writes `RUN/player_look.json`. Python standard library only.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
V = ROOT / ".agents/skills/verify/scripts/verify.py"
M = (1 << 64) - 1
BANDS = ["infant", "child", "youth", "adult", "elder"]


def splitmix64(x):
    z = (x + 0x9E3779B97F4A7C15) & M
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M
    return z ^ (z >> 31)


def pool_pick(seed, cid, n):
    return splitmix64(seed ^ ((cid * 0xD1B54A32D192ED03) & M)) % n


def run(*args, check=True):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=ROOT, timeout=300)
    if check and r.returncode:
        raise RuntimeError(f"{args[:3]}: {r.stderr[-400:] or r.stdout[-400:]}")
    return r


def sql(rid, query, *flags):
    out = run(V, "sql", "--run", rid, query, *flags).stdout
    start = out.find("[")
    return json.loads(out[start:]) if start >= 0 else []


def own_row(rid):
    """The player's own `seen_characters` row, read as the player (a request of its own, with the
    player's token: a fresh connection each time). The SDK stream of the same rows across a
    reconnect is verify-client's `look_rows.py`."""
    rows = [r for r in sql(rid, "SELECT * FROM seen_characters", "--as-player") if r.get("own")]
    return rows[0] if rows else {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    rid, out, checks = a.run, ROOT / ".local/living/verify" / a.run, {}
    state = json.loads((out / "state.json").read_text())
    seed = json.loads((ROOT / "living/seeds" / f"{state.get('seed', 'world')}.json").read_text())
    looks = seed.get("looks")
    if not looks:
        print(f"FAIL the run's seed ({state.get('seed')}) has no looks: launch with --seed plan-test")
        return 1
    run(V, "player", "--run", rid, "join", "LookPlayer", check=False)
    me = sql(rid, "SELECT * FROM my_characters", "--as-player")[0]["id"]
    world = sql(rid, "SELECT seed, look_book FROM world")[0]
    row = sql(rid, f"SELECT id, person, line, band, next_ms FROM look WHERE id = {me}")
    row = row[0] if row else {}
    pick = looks["pool"][pool_pick(int(world["seed"]), me, len(looks["pool"]))]
    band = BANDS[row.get("band", 0)] if row else "?"
    checks["the world wears the seed's look generation"] = world["look_book"] == looks["generation"]
    checks["the player's look is the pool entry pool_pick(world seed, id, pool length) names"] = row.get("person") == pick
    # A seed names a band by its name or its code ("adult" or "3").
    entry = looks["people"][pick]
    checks["its line is that entry's line for its band"] = bool(row) and (entry.get(band) or entry.get(str(row.get("band")))) == row.get("line")
    first = own_row(rid)
    time.sleep(1)
    again = own_row(rid)
    checks["its own seen_characters row carries that key"] = first.get("look") == row.get("line")
    checks["a reconnect gets the same key"] = again.get("look") == first.get("look") and bool(first.get("look"))
    # Every player reducer, then the row again.
    calls = [("human_move", [1, 0, False]), ("human_move", [0, 0, False]), ("human_act", ['{"wait":5}']),
             ("human_say", ["look probe", 0]), ("human_speak", ["look probe", 0, "say"]), ("human_face", [1.0, 0.0]),
             ("use_skill", ["strike", 0, 0.0, 0.0]), ("release_skill", ["block"])]
    statuses = []
    for reducer, args in calls:
        r = run(V, "call", "--run", rid, reducer, json.dumps(args), "--as-player", check=False)
        statuses.append({"reducer": reducer, "exit": r.returncode, "out": (r.stdout + r.stderr)[-160:]})
        time.sleep(0.3)
    refused = run(V, "call", "--run", rid, "join", json.dumps(["Again"]), "--as-player", "--expect-refusal", "you already have a living character", check=False)
    checks["a second join is refused"] = refused.returncode == 0
    after = sql(rid, f"SELECT id, person, line, band, next_ms FROM look WHERE id = {me}")
    checks["no player reducer changed the look row"] = bool(after) and after[0] == row
    # The source: who writes `look` rows.
    writers = {}
    for path in (ROOT / "living/authority/src").glob("*.rs"):
        for m in re.finditer(r"ctx\.db\.look\(\)\.(?:id\(\)\.)?(insert|update|delete)\b", path.read_text()):
            writers.setdefault(path.name, set()).add(m[1])
    checks["look rows are written only in look.rs, and deleted at death in perception.rs"] = set(writers) <= {"look.rs", "perception.rs"} and writers.get("perception.rs", {"delete"}) == {"delete"}
    result = {"player": me, "world": world, "look": row, "pool_pick": pick, "own_first": first, "own_again": again, "calls": statuses, "after": after, "writers": {k: sorted(v) for k, v in writers.items()}, "checks": checks}
    (out / "player_look.json").write_text(json.dumps(result, indent=1) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
