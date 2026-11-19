#!/usr/bin/env python3
"""Who is in a player's near tier: those engaged with it first, then the nearest (frame-views;
docs/PERCEPTION.md, "Cues and tiers").

    near_tier.py --run client-...      (a run launched with verify.py launch, any seed, by day)

Two players join with fresh identities: A, and B. Thirteen held strangers stand within 4 m of A
on a quiet open line; B stands 10 m from A (beyond the near tier's 8 m, within day sight). The
near tier holds at most `frame::NEAR_MAX` (32). Read through A's own SQL (`seen_bodies_near`,
`seen_bodies_far`):

- before: the 12 nearest strangers are near, the farthest one and B are far;
- B waves at A (`human_act`, a visible act aimed at A: B is engaged with A): within 1.5 s B is in
  A's near tier, past the cap at once, and A's next sweep ranks it first: B and the 11 nearest
  strangers, 12 in all;
- after the wave has ended and two sweeps have passed, B is far again.

Admin calls (`spawn_crowd`, `set_behavior`, `place_at`) set the scene. Writes `RUN/near_tier.json`.
Python standard library only.
"""

import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HARNESS = ROOT / ".agents/skills/verify/scripts/verify.py"
SPEC = importlib.util.spec_from_file_location("verify_harness", HARNESS)
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from earshot import call, open_line, sql  # noqa: E402

import re
# The cap, as the authority has it (frame::NEAR_MAX).
NEAR_MAX = int(re.search(r"pub const NEAR_MAX: usize = (\d+);", (ROOT / "living/authority/src/frame.rs").read_text())[1])


def player_sql(db, token, query):
    """`SELECT id FROM <view>` as the player (its own identity's view rows)."""
    code, body = V.http(f"/v1/database/{db}/sql", query, token, raw=True)
    if code != 200:
        raise RuntimeError(f"{query}: {code} {body[:200]}")
    return [{"id": r[0]} for r in json.loads(body)[0]["rows"]]


def tiers(db, token):
    near = {r["id"] for r in player_sql(db, token, "SELECT id FROM seen_bodies_near")}
    far = {r["id"] for r in player_sql(db, token, "SELECT id FROM seen_bodies_far")}
    return near, far


def hcall(db, token, reducer, args):
    code, body = V.http(f"/v1/database/{db}/call/{reducer}", args, token)
    if code != 200:
        raise RuntimeError(f"{reducer}: {code} {body[:200]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    db = V.load(rid)["db"]
    out = ROOT / ".local/living/verify" / rid
    tok = {}
    for who in ("a", "b"):
        tok[who] = json.loads(V.http("/v1/identity", {})[1])["token"]
        hcall(db, tok[who], "join", [f"Tier {who.upper()}"])
    chars = {c["name"]: c["id"] for c in sql(rid, "SELECT id, name FROM character")}
    a, b = chars["Tier A"], chars["Tier B"]
    before = {x["id"] for x in sql(rid, "SELECT id FROM character")}
    call(rid, "spawn_crowd", [NEAR_MAX + 1, True])
    strangers = sorted(x["id"] for x in sql(rid, "SELECT id FROM character") if x["id"] not in before)
    for s in strangers:
        call(rid, "set_behavior", [s, json.dumps({"wait": 600})])
    line = open_line(rid, 30)
    ax, ay = line[10]
    call(rid, "place_at", [a, ax, ay])
    # NEAR_MAX + 1 spots round A on the line's open tiles (5 wide), nearest first, within 7 m.
    grid = sorted(((dx, dy) for dx in range(-7, 8) for dy in (-2, -1, 0, 1, 2) if (dx, dy) != (0, 0)),
                  key=lambda d: (math.hypot(*d), d))
    spots = [(ax + dx, ay + dy) for dx, dy in grid[:NEAR_MAX + 1]]
    for s, (x, y) in zip(strangers, spots):
        call(rid, "place_at", [s, x, y])
    call(rid, "place_at", [b, *line[20]])
    time.sleep(2.0)
    pos = {x["id"]: (x["x"], x["y"]) for x in sql(rid, "SELECT id, x, y FROM body")}
    dist = {s: math.dist(pos[a], pos[s]) for s in strangers + [b]}
    by_dist = sorted(strangers, key=lambda s: (dist[s], s))
    near0, far0 = tiers(db, tok["a"])
    hcall(db, tok["b"], "human_act", [json.dumps({"do": {"skill": "wave", "target": {"id": a}}})])
    engaged = None
    t0 = time.time()
    while time.time() - t0 < 1.5:
        near, far = tiers(db, tok["a"])
        if b in near:
            engaged = (near, far, round(time.time() - t0, 2))
            break
        time.sleep(0.1)
    # B joins at once, past the cap; A's next sweep (within 200 ms) ranks the tier: B first, then
    # the 11 nearest strangers.
    ranked = None
    t1 = time.time()
    while engaged is not None and time.time() - t1 < 0.6:
        near, far = tiers(db, tok["a"])
        if near == {b} | set(by_dist[:NEAR_MAX - 1]):
            ranked = (near, round(time.time() - t0, 2))
            break
        time.sleep(0.05)
    doing = [d for d in sql(rid, f"SELECT id, until_ms FROM doing WHERE id = {b}")]
    time.sleep(3.0)
    near2, far2 = tiers(db, tok["a"])
    checks = {
        f"placed as planned ({NEAR_MAX + 1} strangers within 7.5 m of A, B 9-11 m)": all(dist[s] <= 7.5 for s in strangers) and 9 <= dist[b] <= 11,
        f"before: the {NEAR_MAX} nearest strangers are near; the farthest stranger and B are far": near0 == set(by_dist[:NEAR_MAX]) and {by_dist[-1], b} <= far0,
        "B waving at A (engaged) joins A's near tier within 1.5 s, beyond 8 m and past the cap": engaged is not None,
        f"while engaged, A's next sweep ranks the tier: B first and the {NEAR_MAX - 1} nearest strangers, {NEAR_MAX} in all": ranked is not None,
        f"after the wave and two sweeps, B is far again and the {NEAR_MAX} nearest are near": b in far2 and near2 == set(by_dist[:NEAR_MAX]),
    }
    result = {"a": a, "b": b, "dist": {str(k): round(v, 2) for k, v in dist.items()}, "before": sorted(near0),
              "engaged": None if engaged is None else {"near": sorted(engaged[0]), "after_s": engaged[2]},
              "ranked": None if ranked is None else {"near": sorted(ranked[0]), "after_s": ranked[1]}, "after": sorted(near2),
              "doing": doing, "checks": checks}
    (out / "near_tier.json").write_text(json.dumps(result, indent=1) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
