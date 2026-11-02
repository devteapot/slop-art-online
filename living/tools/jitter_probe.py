#!/usr/bin/env python3
"""Where bodies jump, as an observer receives `body` updates.

Subscribes to `body` and `activity` for a window, stamps every transaction with the local
wall clock when it arrives, and reports for each body update (old row -> new row):

- `server_jump`: the old row evaluated at the new row's `t_ms` against the new row's pose
  (a discontinuity in the authority's own motion; 0 = continuous),
- `heading_jump`: the change of direction of travel at that instant (moving on both sides),
- `stall_ms`: how long the body stood held at the old row's `next_ms` before the update
  (`t_ms - next_ms` when positive: the tick came after the segment ended),
- `delivery_ms`: local arrival time minus the row's `t_ms` (latency plus clock offset),
- `observer_jump`: what a viewer using its own wall clock (holding a row at `next_ms`, as
  `body_pos` does) sees snap when the row arrives: the old row at arrival against the new
  row at arrival,

as p50/p95/p99/max, broken down by the body's activity (`skill`) and by what the update
did (start, stop, moving -> moving). Also the update interval per moving body.

Usage: living/tools/jitter_probe.py --db DB [--seconds 60] [--json out.json]
"""
import argparse
import collections
import json
import math
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = os.environ.get("LIVING_STDB", str(ROOT / "living/tools/stdb"))
IDLE = 18446744073709551615


def pose(r, t):
    """(x, y, heading, speed) of body row `r` at time t (ms), held at `next_ms`; mirrors
    `living_rules::steer::pose`."""
    vx, vy = r["vx"], r["vy"]
    v = math.hypot(vx, vy)
    dt = max(0.0, (min(t, r["next_ms"]) - r["t_ms"]) / 1000)
    turn, ts = r.get("turn", 0.0) or 0.0, r.get("turn_s", 0.0) or 0.0
    h = r.get("heading", 0.0)
    if v == 0:
        a = min(dt, ts) if turn and ts > 0 else 0.0
        return r["x"], r["y"], h + turn * a, 0.0
    if not turn or ts <= 0:
        return r["x"] + vx * dt, r["y"] + vy * dt, math.atan2(vy, vx), v
    a = min(dt, ts)
    h1 = h + turn * a
    x = r["x"] + v / turn * (math.sin(h1) - math.sin(h))
    y = r["y"] - v / turn * (math.cos(h1) - math.cos(h))
    return x + v * math.cos(h1) * (dt - a), y + v * math.sin(h1) * (dt - a), h1, v


def stats(xs):
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    q = lambda f: s[min(len(s) - 1, int(f * (len(s) - 1)))]
    return {"n": len(s), "p50": round(q(0.5), 4), "p95": round(q(0.95), 4), "p99": round(q(0.99), 4), "max": round(s[-1], 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--server", default="local")
    ap.add_argument("--json", help="also write the report here")
    ap.add_argument("--record", help="save arrivals (local ms, body deletes/inserts) as JSON lines for viewer_sim.py")
    a = ap.parse_args()
    cmd = [STDB, "subscribe", "-s", a.server, a.db, "SELECT * FROM body", "SELECT * FROM activity", "-t", str(a.seconds + 5), "--print-initial-update"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    lines = []

    def drain():
        for line in p.stdout:
            lines.append((time.time() * 1000.0, line))

    th = threading.Thread(target=drain, daemon=True)
    th.start()
    th.join(a.seconds + 30)
    p.kill()

    if a.record:
        with open(a.record, "w") as f:
            for recv, line in lines:
                if line.startswith("{"):
                    try:
                        b = json.loads(line).get("body")
                    except ValueError:
                        continue
                    if b:
                        f.write(json.dumps({"recv": recv, "body": b}) + "\n")
    skill = {}
    jumps = collections.defaultdict(list)  # by class -> server jumps
    hjumps = collections.defaultdict(list)
    obs = collections.defaultdict(list)
    stalls = []
    delivery = []
    last_t = {}
    intervals = []
    per_tx = collections.Counter()
    worst = []
    first = True
    for recv, line in lines:
        if not line.startswith("{"):
            continue
        try:
            u = json.loads(line)
        except ValueError:
            continue
        act = u.get("activity", {})
        for r in act.get("deletes", []):
            skill.pop(r["id"], None)
        for r in act.get("inserts", []):
            skill[r["id"]] = r["skill"]
        if first:
            first = False
            continue
        body = u.get("body", {})
        old = {}
        for r in body.get("deletes", []):
            old[r["id"]] = r
        ins = collections.Counter(r["id"] for r in body.get("inserts", []))
        for i, n in ins.items():
            per_tx[n] += 1
        for new in body.get("inserts", []):
            o = old.get(new["id"])
            if o is None:
                continue
            t = new["t_ms"]
            delivery.append(recv - t)
            ox, oy, oh, ov = pose(o, t)
            nx, ny, nh, nv = pose(new, t)
            j = math.hypot(ox - nx, oy - ny)
            was, now_moving = bool(o["vx"] or o["vy"]), bool(new["vx"] or new["vy"])
            kind = "move->move" if was and now_moving else "start" if now_moving else "stop" if was else "still"
            sk = skill.get(new["id"], "none")
            for key in ("all", f"skill:{sk}", f"update:{kind}", f"kind:{new['kind']}"):
                jumps[key].append(j)
            if was and now_moving:
                hjumps[f"skill:{sk}"].append(abs((nh - oh + math.pi) % (2 * math.pi) - math.pi))
                hjumps["all"].append(abs((nh - oh + math.pi) % (2 * math.pi) - math.pi))
            if (o["vx"] or o["vy"]) and o["next_ms"] < t:
                stalls.append(t - o["next_ms"])
            # What a viewer on this host's clock sees snap when the row arrives.
            ax, ay, _, _ = pose(o, recv)
            bx, by, _, _ = pose(new, recv)
            oj = math.hypot(ax - bx, ay - by)
            obs["all"].append(oj)
            obs[f"skill:{sk}"].append(oj)
            if j > 0.05:
                worst.append((round(j, 3), sk, kind, new["kind"], new["id"], o, new))
            if now_moving or was:
                if new["id"] in last_t:
                    intervals.append(t - last_t[new["id"]])
                last_t[new["id"]] = t
    worst.sort(key=lambda w: -w[0])
    rep = {
        "db": a.db,
        "seconds": a.seconds,
        "updates": len(jumps["all"]),
        "rows_per_body_per_tx": dict(per_tx),
        "server_jump_tiles": {k: stats(v) for k, v in sorted(jumps.items(), key=lambda kv: -len(kv[1]))},
        "server_jumps_over_0.05": sum(1 for x in jumps["all"] if x > 0.05),
        "heading_jump_rad_moving": {k: stats(v) for k, v in sorted(hjumps.items(), key=lambda kv: -len(kv[1]))[:12]},
        "stall_ms": stats(stalls),
        "stalled_share": round(len(stalls) / max(1, len(jumps["all"])), 3),
        "delivery_ms": stats(delivery),
        "update_interval_ms_moving": stats(intervals),
        "observer_jump_tiles": {k: stats(v) for k, v in sorted(obs.items(), key=lambda kv: -len(kv[1]))[:14]},
        "worst": [w[:5] for w in worst[:15]],
    }
    out = json.dumps(rep, indent=1)
    print(out)
    if a.json:
        Path(a.json).write_text(json.dumps({**rep, "worst_rows": [[w[5], w[6]] for w in worst[:15]]}, indent=1))


if __name__ == "__main__":
    main()
