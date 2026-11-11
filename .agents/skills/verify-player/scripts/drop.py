#!/usr/bin/env python3
"""A player on an upper level and one below, across a drop (docs/PERCEPTION.md, "Drops").

A drop between two ground levels is a `drop` tile (8): no one walks across it, but it is open
air, so sight and missiles pass over it. On a plan-test world (`seeds/plan-test.json`: a quay at
2.5 m and a row at 6.5 m, the drop along the quay's edge) two player identities stand either side
of the drop, a few metres apart:

1. each perceives the other (`seen_bodies`, `seen_characters`, the players' own views);
2. the one above walks straight at the drop (`human_move`) and stops at its edge: no sample of
   its body is on a drop tile, and it is still on the row;
3. it is told to go to the one below (`human_act` goto): its body never stands on a drop tile,
   and between samples it never jumps across one (it goes round by a stair, or is refused);
4. it shoots the one below with its bow (`use_skill bowshot`): the arrow flies over the drop and
   strikes.

    drop.py --run RUN

Needs `verify.py launch --run RUN --seed plan-test` (best with LIVING_PERCEPTION=scoped, so the
views are the only way in); joins both players if needed. Admin `place_at` sets the scene (not
something a player can do) and admin SQL reads bodies and tiles. Writes `RUN/drop.json`.
Python standard library only.
"""

import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location("verify", HERE.parent.parent / "verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)

RESULTS = []
WALKABLE = {0, 1, 3, 5, 6}  # living_rules::map::Terrain: grass, forest, sand, dirt, road
DROP = 8


class P:
    def __init__(self, run):
        self.st = V.load(run)
        self.db = self.st["db"]
        self.admin = V.admin_token()
        for key in ("token", "token2"):
            if not self.st.get(key):
                code, body = V.http("/v1/identity", {})
                j = json.loads(body)
                self.st[key] = j["token"]
                self.st["identity" if key == "token" else "identity2"] = j["identity"]
                V.save(self.st)

    def token(self, who):
        return {"admin": self.admin, "above": self.st["token"], "below": self.st["token2"]}[who]

    def sql(self, q, who="admin"):
        code, body = V.http(f"/v1/database/{self.db}/sql", q, self.token(who), raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q}: {code} {body}")
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(self, reducer, args, who="above"):
        code, body = V.http(f"/v1/database/{self.db}/call/{reducer}", args, self.token(who))
        V.log(self.st, f"call {reducer}{json.dumps(args)} as {who} -> {code} {body.strip()}", sys.stderr)
        return code, body

    def me(self, who, name):
        mine = [c for c in self.sql("SELECT id, alive FROM my_characters", who) if c["alive"]]
        if not mine:
            self.call("join", [name], who)
            mine = [c for c in self.sql("SELECT id, alive FROM my_characters", who) if c["alive"]]
        return mine[0]["id"]

    def at(self, cid):
        """Where a body is now, from its segment (straight-line)."""
        b = self.sql(f"SELECT x, y, t_ms, vx, vy, next_ms FROM body WHERE id = {cid}")[0]
        now = self.sql("SELECT last_ms FROM clock")[0]["last_ms"]
        dt = max(0, min(now, b["next_ms"]) - b["t_ms"]) / 1000
        return (b["x"] + b["vx"] * dt, b["y"] + b["vy"] * dt)


def check(p, name, ok, detail):
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail})
    V.log(p.st, f"{'PASS' if ok else 'FAIL'} {name}: {detail}")


def wait_for(fn, secs=8.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        r = fn()
        if r:
            return r
        time.sleep(0.4)
    return fn()


def inside(poly, q):
    x, y = q
    n, hit = len(poly), False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def plan_levels():
    """The plan's levels as (id, height, polygon) in world coordinates. The plan's frame
    (`settle::plan::Frame`): east-north metres from `origin`, turned clockwise by `rotation_deg`,
    north up the map (world y grows south)."""
    plan = json.loads((ROOT / "living/seeds/plan-test.json").read_text())["map"]["params"]["plans"][0]
    (ox, oy), th = plan["origin"], math.radians(plan.get("rotation_deg", 0.0))
    pt = lambda e, n: (ox + e * math.cos(th) + n * math.sin(th), oy + e * math.sin(th) - n * math.cos(th))
    return [(l["id"], l["height_m"], [pt(*q) for q in l["area"]]) for l in plan["levels"]], (ox, oy)


def geometry(p):
    """An upper tile on the higher level and a lower one on the lower, on one axis, with only
    drop tiles (1 to 3) between and walkable ground behind each for 3 tiles."""
    w = p.sql("SELECT width, height FROM world")[0]
    W, H = w["width"], w["height"]
    tiles = bytearray([4]) * (W * H)
    for row in p.sql("SELECT * FROM terrain_chunk"):
        data = row["tiles"]
        data = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)
        cx, cy = row["id"] & 0xFFFF, row["id"] >> 16
        for k, t in enumerate(data):
            x, y = cx * 16 + k % 16, cy * 16 + k // 16
            if x < W and y < H:
                tiles[y * W + x] = t
    at = lambda x, y: tiles[y * W + x] if 0 <= x < W and 0 <= y < H else 4
    levels, (ox, oy) = plan_levels()
    hi = max(levels, key=lambda l: l[1])
    lo = min(levels, key=lambda l: l[1])
    walk = lambda x, y: at(x, y) in WALKABLE
    for y in range(int(oy) - 90, int(oy) + 90):
        for x in range(int(ox) - 90, int(ox) + 90):
            if not walk(x, y) or not inside(hi[2], (x + .5, y + .5)):
                continue
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                for gap in (1, 2, 3):
                    bx, by = x + (gap + 1) * dx, y + (gap + 1) * dy
                    if walk(bx, by) and inside(lo[2], (bx + .5, by + .5)) \
                            and all(at(x + i * dx, y + i * dy) == DROP for i in range(1, gap + 1)) \
                            and all(walk(x - i * dx, y - i * dy) and walk(bx + i * dx, by + i * dy) for i in range(1, 4)) \
                            and all(walk(x + j * dy, y + j * dx) for j in (-1, 1)):
                        return {"above": (x + .5, y + .5), "below": (bx + .5, by + .5), "dir": (dx, dy), "gap": gap,
                                "levels": {hi[0]: hi[1], lo[0]: lo[1]}}, at, (hi, lo)
    raise RuntimeError("no drop between the plan's levels on this map")


def finish(p):
    out = V.run_dir(ARGS.run) / "drop.json"
    out.write_text(json.dumps(RESULTS, indent=1))
    bad = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(bad)} of {len(RESULTS)} checks pass; {out}")
    sys.exit(1 if bad else 0)


def trail(p, cid, secs, every=0.2):
    pts = []
    end = time.monotonic() + secs
    while time.monotonic() < end:
        pts.append(p.at(cid))
        time.sleep(every)
    return pts


def main():
    p = P(ARGS.run)
    up = p.me("above", "Above")
    down = p.me("below", "Below")
    g, at, (hi, lo) = geometry(p)
    (V.run_dir(ARGS.run) / "drop-geometry.json").write_text(json.dumps(g, indent=1))
    tile = lambda q: at(math.floor(q[0]), math.floor(q[1]))
    p.call("place_at", [up, *g["above"]], "admin")
    p.call("place_at", [down, *g["below"]], "admin")
    p.call("human_move", [0.0, 0.0, False], "above")
    p.call("human_move", [0.0, 0.0, False], "below")
    time.sleep(1.0)
    a0, b0 = p.at(up), p.at(down)
    check(p, "the two players stand either side of the drop", inside(hi[2], a0) and inside(lo[2], b0) and tile(a0) in WALKABLE and tile(b0) in WALKABLE,
          {"above": a0, "below": b0, "levels": g["levels"], "drop_tiles_between": g["gap"], "apart_m": round(math.dist(a0, b0), 2)})

    # 1. Each sees the other.
    sees = lambda who, cid: any(r["id"] == cid for r in p.sql("SELECT id FROM seen_bodies", who))
    knows = lambda who, cid: any(r["id"] == cid for r in p.sql("SELECT id FROM seen_characters", who))
    s_up = wait_for(lambda: sees("above", down) and knows("above", down), 8)
    s_down = wait_for(lambda: sees("below", up) and knows("below", up), 8)
    check(p, "the player above sees the one below (seen_bodies, seen_characters)", s_up, {"seen_bodies": sorted(r["id"] for r in p.sql("SELECT id FROM seen_bodies", "above"))})
    check(p, "the player below sees the one above", s_down, {"seen_bodies": sorted(r["id"] for r in p.sql("SELECT id FROM seen_bodies", "below"))})

    # 2. Walking straight at the drop stops at its edge.
    dx, dy = g["dir"]
    p.call("human_move", [float(dx), float(dy), False], "above")
    pts = trail(p, up, 4.0)
    p.call("human_move", [0.0, 0.0, False], "above")
    time.sleep(0.5)
    end = p.at(up)
    on_drop = [q for q in pts + [end] if tile(q) not in WALKABLE]
    check(p, "walking straight at the drop, the player stops at its edge", not on_drop and inside(hi[2], end),
          {"start": pts[0] if pts else None, "end": end, "on_blocked_tiles": on_drop[:5], "moved_m": round(math.dist(pts[0], end), 2) if pts else None})

    # 3. Told to go below: never over the drop.
    p.call("place_at", [up, *g["above"]], "admin")
    time.sleep(0.5)
    p.call("human_act", [json.dumps({"do": "goto", "target": {"at": list(b0)}})], "above")
    pts = trail(p, up, 10.0)
    jumps = [(a, b) for a, b in zip(pts, pts[1:]) if math.dist(a, b) > 1.5]
    on_drop = [q for q in pts if tile(q) not in WALKABLE]
    goto = [u for u in p.sql("SELECT * FROM my_skill_uses", "above") if u["skill"] == "goto"]
    check(p, "a walk to the one below never crosses the drop", not on_drop and not jumps,
          {"outcome": goto[-1]["outcome"] if goto else None, "end": pts[-1] if pts else None, "on_level": next((l[0] for l in (hi, lo) if pts and inside(l[2], pts[-1])), None), "walked_m": round(sum(math.dist(a, b) for a, b in zip(pts, pts[1:])), 1), "on_blocked_tiles": on_drop[:5], "jumps": jumps[:3]})
    p.call("human_move", [0.0, 0.0, False], "above")

    # 4. A bow shot over the drop strikes.
    p.call("place_at", [up, *g["above"]], "admin")
    p.call("place_at", [down, *g["below"]], "admin")
    time.sleep(1.5)
    a1, b1 = p.at(up), p.at(down)
    h0 = p.sql(f"SELECT hp FROM vitals WHERE id = {down}")[0]["hp"]
    p.call("use_skill", ["bowshot", 0, b1[0], b1[1]], "above")
    shot = wait_for(lambda: [u for u in p.sql("SELECT * FROM my_skill_uses", "above") if u["skill"] == "bowshot" and u["outcome"] and u["outcome"] != "in flight"], 5)
    h1 = p.sql(f"SELECT hp FROM vitals WHERE id = {down}")[0]["hp"]
    check(p, "an arrow shot over the drop strikes the one below", shot and shot[-1]["outcome"].startswith("struck") and h1 < h0,
          {"outcome": shot[-1]["outcome"] if shot else None, "from": a1, "at": b1, "hp": [h0, h1]})
    finish(p)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ARGS = ap.parse_args()
    main()
