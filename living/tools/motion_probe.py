#!/usr/bin/env python3
"""How bodies move, from the `body` rows an observer receives.

Subscribes to `body` for a window and reports, over bodies that moved:
- row updates per moving body per second (what steering costs in writes),
- stop-and-go: a body that stood still for less than 1.5 s between two movements
  (per moving body per minute),
- abrupt turns: an update whose direction of travel differs from the previous segment's
  (at the moment of the update) by more than 60 degrees while moving on both sides,
- the share of segments that are arcs (a turning body),
- position jumps: how far a new row puts a body from where the previous row, extrapolated
  as an observer does, had it (0 = continuous motion).

Usage: living/tools/motion_probe.py --db DB [--seconds 30]
LIVING_STDB overrides the CLI wrapper (e.g. the main checkout's, from a worktree).
"""
import argparse
import collections
import json
import math
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = os.environ.get("LIVING_STDB", str(ROOT / "living/tools/stdb"))


def velocity_at(r, t):
    """Direction of travel (radians) and speed of a body row at time t (ms)."""
    vx, vy = r["vx"], r["vy"]
    speed = math.hypot(vx, vy)
    if speed == 0:
        return None, 0.0
    turn = r.get("turn", 0.0) or 0.0
    h0 = r.get("heading", math.atan2(vy, vx)) if turn else math.atan2(vy, vx)
    dt = max(0.0, (min(t, r["next_ms"]) - r["t_ms"]) / 1000)
    return h0 + turn * min(dt, r.get("turn_s", 0.0) or 0.0), speed


def position_at(r, t):
    """Where an observer extrapolates body row `r` at time t (ms): a turn for `turn_s`, then
    straight (rows without turn fields are straight lines)."""
    vx, vy = r["vx"], r["vy"]
    v = math.hypot(vx, vy)
    dt = max(0.0, (min(t, r["next_ms"]) - r["t_ms"]) / 1000)
    turn, ts = r.get("turn", 0.0) or 0.0, r.get("turn_s", 0.0) or 0.0
    if v == 0 or not turn or ts <= 0:
        return r["x"] + vx * dt, r["y"] + vy * dt
    h = r.get("heading", math.atan2(vy, vx))
    a = min(dt, ts)
    h1 = h + turn * a
    x = r["x"] + v / turn * (math.sin(h1) - math.sin(h))
    y = r["y"] - v / turn * (math.cos(h1) - math.cos(h))
    return x + v * math.cos(h1) * (dt - a), y + v * math.sin(h1) * (dt - a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--seconds", type=int, default=30)
    a = ap.parse_args()
    p = subprocess.run([STDB, "subscribe", "-s", "local", a.db, "SELECT * FROM body", "-t", str(a.seconds)], capture_output=True, text=True)
    updates = collections.defaultdict(list)
    for line in p.stdout.splitlines():
        if not line.startswith("{"):
            continue
        try:
            u = json.loads(line).get("body", {})
        except ValueError:
            continue
        for r in u.get("inserts", []):
            updates[r["id"]].append(r)
    moving = 0
    writes = 0
    stop_go = 0
    abrupt = 0
    arcs = 0
    segs = 0
    jumps = []
    for rows in updates.values():
        rows.sort(key=lambda r: r["t_ms"])
        if not any(r["vx"] or r["vy"] for r in rows):
            continue
        moving += 1
        writes += len(rows)
        stand_from = None
        prev = None
        for r in rows:
            segs += 1
            is_moving = bool(r["vx"] or r["vy"])
            if r.get("turn"):
                arcs += 1
            if prev is not None:
                px, py = position_at(prev, r["t_ms"])
                jumps.append(math.hypot(px - r["x"], py - r["y"]))
                h_prev, s_prev = velocity_at(prev, r["t_ms"])
                h_new, s_new = velocity_at(r, r["t_ms"])
                if s_prev > 0.3 and s_new > 0.3:
                    d = abs((h_new - h_prev + math.pi) % (2 * math.pi) - math.pi)
                    if d > math.radians(60):
                        abrupt += 1
                if not is_moving and (prev["vx"] or prev["vy"]):
                    stand_from = r["t_ms"]
                elif is_moving and stand_from is not None:
                    if r["t_ms"] - stand_from < 1500:
                        stop_go += 1
                    stand_from = None
            prev = r
    minutes = a.seconds / 60
    report = {
        "db": a.db,
        "seconds": a.seconds,
        "bodies_updated": len(updates),
        "bodies_moving": moving,
        "row_updates_per_moving_body_per_s": round(writes / max(moving, 1) / a.seconds, 2),
        "stop_and_go_per_moving_body_per_min": round(stop_go / max(moving, 1) / minutes, 2),
        "abrupt_turns_per_moving_body_per_min": round(abrupt / max(moving, 1) / minutes, 2),
        "arc_share_of_segments": round(arcs / max(segs, 1), 3),
        # Where the previous row put the body at the new row's time vs where the new row says
        # it is: an observer sees this as a jump (0 = continuous motion).
        "position_jump_tiles": {
            "p99": round(sorted(jumps)[int(0.99 * (len(jumps) - 1))], 3) if jumps else 0.0,
            "max": round(max(jumps, default=0.0), 3),
        },
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
