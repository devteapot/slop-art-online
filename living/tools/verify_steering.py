#!/usr/bin/env python3
"""End-to-end checks of steering locomotion on a scratch database (no LLM).

1. Momentum: two walks in a row flow into each other (no standing row in between).
2. Arrival slows: the last moving segment before standing is slower than the walk.
3. Following keeps a distance and keeps up with a walking target.
4. A player's direction input moves, turns and stops the body; changes are rate-limited.

Usage: living/tools/verify_steering.py [--db steer-verify] [--wasm living_authority.wasm]
Publishes the database fresh (deletes its data). LIVING_STDB overrides the CLI wrapper.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = os.environ.get("LIVING_STDB", str(ROOT / "living/tools/stdb"))


def stdb(*args, check=True):
    r = subprocess.run([STDB, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()[-300:]}")
    return r


def rows(db, q):
    out = stdb("sql", "-s", "local", db, q).stdout
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("WARNING") and set(l.strip()) - set("-+")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    return [{h: v.strip().strip('"') for h, v in zip(head, [v.strip() for v in l.split("|")])} for l in lines[1:]]


def call(db, reducer, *args, check=True):
    enc = [str(a) if isinstance(a, (int, float, bool)) and not isinstance(a, bool) else (("true" if a else "false") if isinstance(a, bool) else json.dumps(a)) for a in args]
    return stdb("call", "-s", "local", db, reducer, *enc, check=check)


class Recorder:
    """Body rows of some ids, as an observer receives them."""

    def __init__(self, db, ids, seconds):
        q = f"SELECT * FROM body WHERE id = {ids[0]}" if len(ids) == 1 else "SELECT * FROM body"
        self.ids = set(ids)
        self.rows = {i: [] for i in ids}
        self.p = subprocess.Popen([STDB, "subscribe", "-s", "local", db, q, "-t", str(seconds), "--print-initial-update"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.t = threading.Thread(target=self.drain, daemon=True)
        self.t.start()

    def drain(self):
        for line in self.p.stdout:
            if not line.startswith("{"):
                continue
            try:
                u = json.loads(line).get("body", {})
            except ValueError:
                continue
            for r in u.get("inserts", []):
                if r["id"] in self.ids:
                    self.rows[r["id"]].append(r)

    def wait(self):
        self.p.wait()
        self.t.join(timeout=5)
        return self.rows


def pose(r, t):
    """Position of body row `r` at time `t` (ms), as living_rules::steer::pose."""
    v = math.hypot(r["vx"], r["vy"])
    dt = max(0.0, (min(t, r["next_ms"]) - r["t_ms"]) / 1000)
    h, turn, ts = r.get("heading", 0.0), r.get("turn", 0.0), r.get("turn_s", 0.0)
    x, y = r["x"], r["y"]
    if v == 0:
        return x, y
    if not turn or ts <= 0:
        return x + r["vx"] * dt, y + r["vy"] * dt
    a = min(dt, ts)
    h1 = h + turn * a
    x += v / turn * (math.sin(h1) - math.sin(h))
    y -= v / turn * (math.cos(h1) - math.cos(h))
    rest = dt - a
    return x + v * math.cos(h1) * rest, y + v * math.sin(h1) * rest


def walkable(db):
    """Terrain lookup for choosing open ground (water, rock and walls block)."""
    cache = {}

    def ok(x, y):
        cx, cy = int(x) // 16, int(y) // 16
        cid = (cy << 16) | cx
        if cid not in cache:
            out = stdb("sql", "-s", "local", db, f"SELECT tiles FROM terrain_chunk WHERE id = {cid}").stdout
            hexes = [w for w in out.split() if w.startswith("0x")]
            cache[cid] = bytes.fromhex(hexes[0][2:]) if hexes else b""
        t = cache[cid]
        i = (int(y) % 16) * 16 + int(x) % 16
        return i < len(t) and t[i] not in (2, 4, 7)

    return ok


def open_l(ok, x, y, n=5):
    """A right-angle walk of two legs of n tiles over open ground from (x, y), if any."""
    for dx, dy in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
        legs = [(x + dx * s / 2, y) for s in range(0, 2 * n + 1)] + [(x + dx * n, y + dy * s / 2) for s in range(0, 2 * n + 1)]
        if all(ok(px + ox, py + oy) for px, py in legs for ox, oy in [(0, 0), (0.4, 0.4), (-0.4, -0.4), (0.4, -0.4), (-0.4, 0.4)]):
            return (x + dx * n, y), (x + dx * n, y + dy * n)
    return None


def at(rows_, t):
    cur = None
    for r in rows_:
        if r["t_ms"] <= t:
            cur = r
    return pose(cur, t) if cur else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="steer-verify")
    ap.add_argument("--wasm", default="living_authority.wasm")
    a = ap.parse_args()
    db = a.db
    stdb("publish", "-s", "local", "-b", f"/wasm/{a.wasm}", db, "--delete-data", "-y")
    time.sleep(3)
    call(db, "spawn_crowd", 2, True)
    time.sleep(1.5)
    walkers = sorted(int(r["id"]) for r in rows(db, "SELECT id, name FROM character") if r["name"].startswith("Walker"))
    A, B = walkers[:2]
    idle = {"wait": 120}
    call(db, "set_behavior", A, json.dumps(idle))
    call(db, "set_behavior", B, json.dumps(idle))
    results = {}

    # 1-2. Two walks in a row: one flowing movement, slowing only at the end.
    ok = walkable(db)
    legs = None
    for walker in [A, B]:
        b = rows(db, f"SELECT x, y FROM body WHERE id = {walker}")[0]
        x, y = int(float(b["x"])) + 0.5, int(float(b["y"])) + 0.5
        legs = open_l(ok, x, y)
        if legs:
            break
    if not legs:
        sys.exit("no open ground around the walkers; publish again")
    if walker != A:
        A, B = B, A
    call(db, "set_behavior", A, json.dumps({"seq": [{"do": {"skill": "goto", "target": {"at": [x, y]}}}, {"wait": 120}]}))
    time.sleep(2)
    rec = Recorder(db, [A], 12)
    time.sleep(1)
    (p1, p2) = legs
    plan = {"seq": [{"do": {"skill": "goto", "target": {"at": list(p1)}}}, {"do": {"skill": "goto", "target": {"at": list(p2)}}}, {"wait": 120}]}
    call(db, "set_behavior", A, json.dumps(plan))
    got = rec.wait()[A]
    moving = [i for i, r in enumerate(got) if r["vx"] or r["vy"]]
    first, last = (moving[0], moving[-1]) if moving else (0, -1)
    between = got[first:last + 1]
    stood = [r for r in between if not (r["vx"] or r["vy"])]
    done = rows(db, f"SELECT label FROM activity WHERE id = {A}")
    end = got[-1] if got else None
    far = end is not None and math.hypot(end["x"] - p2[0], end["y"] - p2[1]) < 1.5
    results["two walks flow into each other (no stop between)"] = bool(moving) and not stood and far and bool(done) and done[0]["label"] == "wait"
    speeds = [math.hypot(r["vx"], r["vy"]) for r in between]
    print(f"  walks: {len(got)} rows, speeds {[round(s, 2) for s in speeds]}, standing between {len(stood)}, ended {'near' if far else 'away from'} the second spot, now {done[0]['label'] if done else '-'}")
    results["arrival slows down before standing"] = len(speeds) >= 2 and speeds[-1] < 0.8 * max(speeds) and end is not None and not (end["vx"] or end["vy"])

    # 3. Following: B walks away, A follows at a distance.
    call(db, "place_near", A, B)
    time.sleep(0.5)
    b = rows(db, f"SELECT x, y FROM body WHERE id = {B}")[0]
    bx, by = float(b["x"]), float(b["y"])
    rec = Recorder(db, [A, B], 10)
    time.sleep(1)
    call(db, "set_behavior", A, json.dumps({"seq": [{"do": {"skill": "follow", "target": {"id": B}}}, {"wait": 120}]}))
    call(db, "set_behavior", B, json.dumps({"seq": [{"do": {"skill": "goto", "target": {"at": [bx - 8, by + 3]}}}, {"wait": 120}]}))
    got = rec.wait()
    ra, rb = got[A], got[B]
    t0 = max(ra[0]["t_ms"], rb[0]["t_ms"]) if ra and rb else 0
    t1 = min(ra[-1]["t_ms"], rb[-1]["t_ms"]) + 3000 if ra and rb else 0
    ds = []
    for t in range(t0 + 500, t1, 250):
        pa, pb = at(ra, t), at(rb, t)
        if pa and pb:
            ds.append(math.hypot(pa[0] - pb[0], pa[1] - pb[1]))
    moved = at(ra, t1) and at(ra, t0) and math.hypot(at(ra, t1)[0] - at(ra, t0)[0], at(ra, t1)[1] - at(ra, t0)[1])
    results["follower keeps a distance and keeps up"] = bool(ds) and min(ds) >= 0.9 and ds[-1] <= 3.5 and (moved or 0) > 3.0
    print(f"  follow: distance min {min(ds, default=0):.2f} end {ds[-1] if ds else 0:.2f}, follower moved {moved or 0:.1f}")

    # 4. A player's direction input.
    call(db, "join", "Tester")
    me = [int(r["id"]) for r in rows(db, "SELECT id, name FROM character") if r["name"] == "Tester"][0]
    call(db, "place_near", me, A)
    time.sleep(1)
    call(db, "human_move", 1.0, 0.0, False)
    time.sleep(1.2)
    r1 = rows(db, f"SELECT vx, vy, heading FROM body WHERE id = {me}")[0]
    call(db, "human_move", 0.0, 1.0, True)
    time.sleep(1.2)
    r2 = rows(db, f"SELECT vx, vy, speed FROM body WHERE id = {me}")[0]
    call(db, "human_move", 0.0, 0.0, False)
    time.sleep(1.2)
    r3 = rows(db, f"SELECT vx, vy FROM body WHERE id = {me}")[0]
    east = float(r1["vx"]) > 1.0 and abs(float(r1["vy"])) < 0.3
    # Moving south, running (or stopped against something after sliding along it).
    south = float(r2["vy"]) > 1.0 or float(r2["speed"]) > 3.0
    stopped = float(r3["vx"]) == 0 and float(r3["vy"]) == 0
    results["player direction input moves, turns and stops"] = east and south and stopped
    print(f"  player: east v=({r1['vx']},{r1['vy']}), south v=({r2['vx']},{r2['vy']}) speed {r2['speed']}, stop v=({r3['vx']},{r3['vy']})")
    src = (ROOT / "living/scripts/skills.rhai").read_text().replace("input_hz: 30.0, input_burst: 15.0", "input_hz: 0.2, input_burst: 2.0")
    call(db, "install_script", src)
    outcomes = [call(db, "human_move", dx, dy, False, check=False).returncode == 0 for dx, dy in [(1, 0), (0, 1), (-1, 0), (0, -1)]]
    results["movement input is rate-limited"] = outcomes[:2] == [True, True] and not all(outcomes[2:])
    print(f"  rate limit: accepted {outcomes}")

    ok = all(results.values())
    for k, v in results.items():
        print(("PASS " if v else "FAIL ") + k)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
