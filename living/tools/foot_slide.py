#!/usr/bin/env python3
"""Foot slide from a game client's toe track (`LIVING_GAME_FEET=<file>`, living/game/src/gait.rs).

    python3 living/tools/foot_slide.py FEET.jsonl [--skip 3] [--json OUT]

Per clip played: a toe counts as planted while it is within 3 cm of that clip's lowest toe height
above the ground under it (2nd percentile) and no higher than the other toe. While a toe is
planted it should not move: its horizontal speed is the slide. The report gives the body's speed,
the share of toe-frames planted, the mean and median slide speed (m/s and as a share of the
body's speed), the drift over each whole contact (median and 90th percentile, cm), and the
cadence: steps a second (both feet's contacts over the clip's time) and the stride (metres
walked per step). The first `--skip` seconds (accelerating, crossfades) are left out.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict

PLANT_M = 0.03
MOVING = 0.3
# A contact ends after its toe has been up this long (s).
GAP_S = 0.08


def cycle(pairs) -> float | None:
    """The gait cycle (s): the first strong peak of the left toe height's autocorrelation, over
    the longest run of consecutive moving frames, resampled at 120 Hz."""
    runs, cur = [], [pairs[0]]
    for p in pairs[1:]:
        if abs(p[0]["t"] - cur[-1][1]["t"]) < 1e-6:
            cur.append(p)
        else:
            runs.append(cur)
            cur = [p]
    runs.append(cur)
    run = max(runs, key=len)
    ts = [p[1]["t"] for p in run]
    hs = [p[1]["l"][1] - p[1]["l"][3] for p in run]
    if ts[-1] - ts[0] < 3.0:
        return None
    step = 1 / 120
    grid, k = [], 0
    t = ts[0]
    while t < ts[-1]:
        while ts[k + 1] < t:
            k += 1
        f = (t - ts[k]) / max(ts[k + 1] - ts[k], 1e-9)
        grid.append(hs[k] + (hs[k + 1] - hs[k]) * f)
        t += step
    m = statistics.mean(grid)
    g = [x - m for x in grid]
    n = len(g)
    def ac(lag):
        return sum(g[i] * g[i + lag] for i in range(n - lag)) / (n - lag)
    lags = range(int(0.3 / step), min(int(2.0 / step), n // 2))
    vals = [(ac(l), l) for l in lags]
    if not vals:
        return None
    top = max(v for v, _ in vals)
    # The first lag that comes within 85% of the best peak and is a local maximum.
    for i in range(1, len(vals) - 1):
        if vals[i][0] >= 0.85 * top and vals[i][0] >= vals[i - 1][0] and vals[i][0] >= vals[i + 1][0]:
            return vals[i][1] * step
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("track")
    ap.add_argument("--skip", type=float, default=3.0)
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    rows = [json.loads(line) for line in open(a.track) if line.strip()]
    if not rows:
        sys.exit("no frames")
    t0 = rows[0]["t"]
    rows = [r for r in rows if r["t"] - t0 >= a.skip and r.get("speed", 0) > 0.2]
    if len(rows) < 10:
        sys.exit("too few moving frames")
    out = {}
    by_clip = defaultdict(list)
    for r in rows:
        by_clip[r.get("clip", "")].append(r)
    for clip, rs in by_clip.items():
        # Frame pairs where the body moves (stops for photographs keep the clip for a moment).
        pairs = []
        for prev, cur in zip(rs, rs[1:]):
            dt = cur["t"] - prev["t"]
            if 0 < dt <= 0.1:
                bv = math.dist((prev["root"][0], prev["root"][2]), (cur["root"][0], cur["root"][2])) / dt
                if bv > MOVING:
                    pairs.append((prev, cur, dt, bv))
        if len(pairs) < 20:
            continue
        floor = {}
        for side in "lr":
            h = sorted(c[side][1] - c[side][3] for _, c, _, _ in pairs)
            floor[side] = h[max(0, int(len(h) * 0.02))]
        lift = lambda r, side: r[side][1] - r[side][3] - floor[side]
        slides, rel, drifts, planted = [], [], [], 0
        for side in "lr":
            other = "r" if side == "l" else "l"
            down = lambda r: lift(r, side) <= PLANT_M and lift(r, side) <= lift(r, other)
            contact, last, gap_t = None, None, 0.0
            for prev, cur, dt, bv in pairs:
                if down(prev) and down(cur):
                    planted += 1
                    v = math.dist((prev[side][0], prev[side][2]), (cur[side][0], cur[side][2])) / dt
                    slides.append(v)
                    rel.append(v / bv)
                    if contact is None:
                        contact = (prev[side][0], prev[side][2])
                    last, gap_t = (cur[side][0], cur[side][2]), 0.0
                elif contact is not None:
                    gap_t += dt
                    if gap_t > GAP_S:
                        drifts.append(math.dist(contact, last))
                        contact = None
        if not slides:
            continue
        drifts.sort()
        secs = sum(dt for _, _, dt, _ in pairs)
        body = sum(bv * dt for _, _, dt, bv in pairs) / secs
        period = cycle(pairs)
        out[clip or "?"] = {
            "seconds": round(secs, 1),
            "body_mps": round(body, 3),
            "cycle_s": round(period, 3) if period else None,
            "steps_per_s": round(2 / period, 2) if period else None,
            "step_m": round(body * period / 2, 2) if period else None,
            "planted_share": round(planted / (2 * len(pairs)), 3),
            "slide_mps_mean": round(statistics.mean(slides), 3),
            "slide_mps_median": round(statistics.median(slides), 3),
            "slide_of_body_median": round(statistics.median(rel), 3),
            "contacts": len(drifts),
            "drift_cm_median": round(100 * drifts[len(drifts) // 2], 1) if drifts else None,
            "drift_cm_p90": round(100 * drifts[int(len(drifts) * 0.9)], 1) if drifts else None,
        }
    for clip, s in out.items():
        print(f"{clip:11s} {s['seconds']} s, body {s['body_mps']} m/s; cycle {s['cycle_s']} s ({s['steps_per_s']} steps/s, {s['step_m']} m a step); planted {s['planted_share']:.0%}; slide mean {s['slide_mps_mean']} m/s, median {s['slide_mps_median']} m/s ({s['slide_of_body_median']} of body); drift per contact median {s['drift_cm_median']} cm, p90 {s['drift_cm_p90']} cm over {s['contacts']} contacts")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
