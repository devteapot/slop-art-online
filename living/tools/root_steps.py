#!/usr/bin/env python3
"""Hitches in your own body's drawn motion, from a game client's feet log (`LIVING_GAME_FEET`).

    python3 living/tools/root_steps.py FEET.jsonl [--from S] [--to S] [--json OUT]

Takes the root's horizontal step each frame (`root`, x and z) and its speed: step over the
authority time the body is drawn at (`mine_ms`, connected play), else over the frame time.
Over the frames between `--from` and `--to` (seconds of the log's own clock; default: the
longest run of frames moving above 0.5 m/s, less its first and last second), it reports:

- the median speed;
- stalls: frames whose speed is under 10% of the median (the body stood still for a frame);
- surges: frames faster than 120% of the median (catching up);
- the seconds between consecutive stalls (median), which shows a renewal period such as the
  authority's `steer_s` (2 s);
- the speed's p1 / p5 / p95 / p99 as shares of the median.

Walking straight at a held direction, a smooth body has no stalls and no surges.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys


def load(path):
    out = []
    with open(path) as f:
        for line in f:
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "root" in j and "t" in j:
                # Connected play logs the authority time my body is drawn at (`mine_ms`): the
                # step over that time is the drawn speed, free of frame-timing noise.
                out.append((j["t"], j["root"][0], j["root"][2], j.get("mine_ms"), (j.get("seg") or [0, 0])[0]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("feet")
    ap.add_argument("--from", dest="t0", type=float)
    ap.add_argument("--to", dest="t1", type=float)
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = load(a.feet)
    steps = []
    renewals = 0
    for (t0, x0, z0, m0, s0), (t1, x1, z1, m1, s1) in zip(rows, rows[1:]):
        dt = t1 - t0
        if m0 is not None and m1 is not None:
            dt = (m1 - m0) / 1000.0
        if dt <= 0:
            continue
        d = math.hypot(x1 - x0, z1 - z0)
        steps.append((t1, d / dt, dt, s1 != s0))
    if a.t0 is None or a.t1 is None:
        # The longest run of moving frames, less a second at each end.
        # (A stall of up to 6 frames stays inside the run.)
        best, start, last = (0, 0), None, None
        for i, (_, v, _, _) in enumerate(steps):
            if v > 0.5:
                if start is None or i - last > 6:
                    start = i
                last = i
                if last - start > best[1] - best[0]:
                    best = (start, last)
        t0 = steps[best[0]][0] + 1.0
        t1 = steps[best[1]][0] - 1.0
    else:
        t0, t1 = a.t0, a.t1
    win = [s for s in steps if t0 <= s[0] <= t1]
    if len(win) < 10:
        print("too few frames in the window", file=sys.stderr)
        return 1
    vs = sorted(v for _, v, _, _ in win)
    med = statistics.median(vs)
    stalls = [t for t, v, _, _ in win if v < 0.1 * med]
    surges = [t for t, v, _, _ in win if v > 1.2 * med]
    renewals = sum(1 for *_, r in win if r)
    gaps = [b - a for a, b in zip(stalls, stalls[1:]) if b - a > 0.05]
    q = lambda p: vs[min(len(vs) - 1, int(round(p * (len(vs) - 1))))] / med
    report = {
        "window_s": [round(t0, 2), round(t1, 2)],
        "frames": len(win),
        "clock": "mine_ms" if rows[0][3] is not None else "frame",
        "segments_started": renewals,
        "median_speed": round(med, 3),
        "stalls": len(stalls),
        "surges": len(surges),
        "stall_gap_median_s": round(statistics.median(gaps), 3) if gaps else None,
        "speed_share": {k: round(q(p), 3) for k, p in [("p1", 0.01), ("p5", 0.05), ("p95", 0.95), ("p99", 0.99)]},
        "stall_times": [round(t, 3) for t in stalls[:40]],
    }
    print(json.dumps(report, indent=2))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(report, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
