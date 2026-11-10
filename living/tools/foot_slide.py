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

`--floors` prints the toe's and ankle's height over the ground on flat ground (a flat run);
`--gap TOE:ANKLE` then reports, for another run (slopes, stairs), the supporting foot's gap to
the ground under it: the lower of toe and ankle over the ground under each, less those heights
(median signed and absolute, p90 absolute, cm; shares more than 2 cm into the ground or above
it). `--stairs X,Z,DOWNX,DOWNZ,FLOOR` measures against a flight's treads instead of its ramp.

`--bins 0.5` reports by the body's speed instead of by clip (for speed ramps, `LIVING_GAME_RAMP`,
where clips change or blend), in bands of that width. It needs no planted-foot guess: in each
frame the supporting foot is the slower of the feet within 5 cm of the floor (none: flight), and
its horizontal speed is the slide (median, mean, p90, m/s, and as a share of the body's speed).
A contact is a run of frames with the same supporting foot; its drift is how far that foot moved
(cm). Steps a second count toe touchdowns (a toe coming within 3 cm of the floor after rising
above 5 cm); step jitter is the median change between one step's duration and the next (s): a
crossfade between unaligned cycles shows as stutter. Contacts and touchdowns belong to the band
of the body's speed when they start. `--json` writes the table.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict

PLANT_M = 0.03
LIFT_M = 0.05
# A foot within this of the floor can be the supporting one (`--bins`).
SUPPORT_M = 0.05
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
    ap.add_argument("--bins", type=float, default=0.0)
    ap.add_argument("--gap", default="", help="TOE:ANKLE floors (m above the ground, from a flat-ground run's --floors)")
    ap.add_argument("--floors", action="store_true")
    ap.add_argument("--stairs", default="", help="X,Z,DOWNX,DOWNZ,FLOOR: measure against that flight's treads (17 rising 3 m over 5 m, buildings.py prop_stairs)")
    ap.add_argument("--paws", action="store_true", help="an animal's paw track (with --bins)")
    ap.add_argument("--paw-floor", type=float, default=0.015)
    a = ap.parse_args()
    if a.paws:
        return paws(a)
    if a.floors or a.gap:
        return gaps(a)
    if a.bins > 0:
        return by_speed(a)
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


def gaps(a) -> None:
    """Foot-to-ground gap of the supporting foot (the slower one) while moving: the lower of its
    toe's and its ankle's height over the ground under each, less that joint's height on flat
    ground (`--floors` prints them from a flat run; `--gap TOE:ANKLE` uses them)."""
    rows = [json.loads(line) for line in open(a.track) if line.strip()]
    t0 = rows[0]["t"]
    rows = [r for r in rows if r["t"] - t0 >= a.skip and "la" in r]
    if a.stairs:
        cx, cz, dx, dz, floor = (float(v) for v in a.stairs.split(","))
        n = math.hypot(dx, dz)
        dx, dz = dx / n, dz / n
        for r in rows:
            for k in ("l", "r", "la", "ra"):
                x, z = r[k][0] - cx, r[k][2] - cz
                u = 2.5 - (x * dx + z * dz)
                if abs(-x * dz + z * dx) <= 1.2 and 0 <= u < 5.0:
                    r[k][3] = floor + (math.floor(u * 17 / 5) + 1) * 3 / 17
    pairs = []
    for prev, cur in zip(rows, rows[1:]):
        dt = cur["t"] - prev["t"]
        if 0 < dt <= 0.1:
            bv = math.dist((prev["root"][0], prev["root"][2]), (cur["root"][0], cur["root"][2])) / dt
            if bv > MOVING:
                pairs.append((prev, cur, dt, bv))
    up = lambda r, k: r[k][1] - r[k][3]
    if a.floors:
        h = sorted(up(c, k) for _, c, _, _ in pairs for k in "lr")
        g = sorted(up(c, k) for _, c, _, _ in pairs for k in ("la", "ra"))
        print(f"{h[int(len(h) * 0.02)]:.4f}:{g[int(len(g) * 0.02)]:.4f}")
        return
    toe_f, ankle_f = (float(x) for x in a.gap.split(":"))
    gap = []
    for prev, cur, dt, bv in pairs:
        speed = {s: math.dist((prev[s][0], prev[s][2]), (cur[s][0], cur[s][2])) / dt for s in "lr"}
        s = min("lr", key=lambda x: speed[x])
        gap.append(min(up(cur, s) - toe_f, up(cur, s + "a") - ankle_f))
    ab = sorted(abs(x) for x in gap)
    out = {
        "frames": len(gap),
        "gap_cm_median": round(100 * statistics.median(gap), 1),
        "abs_gap_cm_median": round(100 * ab[len(ab) // 2], 1),
        "abs_gap_cm_p90": round(100 * ab[int(len(ab) * 0.9)], 1),
        "into_ground_over_2cm": round(sum(x < -0.02 for x in gap) / len(gap), 3),
        "floating_over_2cm": round(sum(x > 0.02 for x in gap) / len(gap), 3),
    }
    print(json.dumps(out))
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)


def by_speed(a) -> None:
    """The ramp report: per band of body speed, the supporting foot's slide and the cadence."""
    rows = [json.loads(line) for line in open(a.track) if line.strip()]
    t0 = rows[0]["t"]
    rows = [r for r in rows if r["t"] - t0 >= a.skip]
    pairs = []
    for prev, cur in zip(rows, rows[1:]):
        dt = cur["t"] - prev["t"]
        if 0 < dt <= 0.1:
            bv = math.dist((prev["root"][0], prev["root"][2]), (cur["root"][0], cur["root"][2])) / dt
            pairs.append((prev, cur, dt, bv))
    moving = [p for p in pairs if p[3] > MOVING]
    if len(moving) < 20:
        sys.exit("too few moving frames")
    # One floor for both toes (2nd percentile of toe height over the ground while moving).
    h = sorted(c[k][1] - c[k][3] for _, c, _, _ in moving for k in "lr")
    floor = h[max(0, int(len(h) * 0.02))]
    lift = lambda r, side: r[side][1] - r[side][3] - floor
    band = lambda v: int(v / a.bins)
    stats = defaultdict(lambda: {"secs": 0.0, "support": 0.0, "slides": [], "rel": [], "drifts": [], "touch": []})
    seg = None  # (side, start position, band, start time)
    for prev, cur, dt, bv in pairs:
        if bv <= MOVING:
            seg = None
            continue
        st = stats[band(bv)]
        st["secs"] += dt
        low = [side for side in "lr" if lift(prev, side) <= SUPPORT_M and lift(cur, side) <= SUPPORT_M]
        if not low:
            seg = None  # flight
            continue
        speed = {side: math.dist((prev[side][0], prev[side][2]), (cur[side][0], cur[side][2])) / dt for side in low}
        side = min(low, key=lambda x: speed[x])
        st["support"] += dt
        st["slides"].append(speed[side])
        st["rel"].append(speed[side] / bv)
        if seg is None or seg[0] != side:
            if seg is not None and cur["t"] - seg[3] >= 0.1:
                stats[seg[2]]["drifts"].append(math.dist(seg[1], seg[4]))
            seg = [side, (prev[side][0], prev[side][2]), band(bv), prev["t"], None]
        seg[4] = (cur[side][0], cur[side][2])
    # Steps: a touchdown is a toe coming within PLANT_M of the floor after it rose above LIFT_M
    # (hysteresis, so a toe skimming the floor is one step).
    for side in "lr":
        up = False
        for prev, cur, dt, bv in pairs:
            hh = lift(cur, side)
            if hh > LIFT_M:
                up = True
            elif up and hh <= PLANT_M:
                up = False
                if bv > MOVING:
                    stats[band(bv)]["touch"].append(cur["t"])
    touches = sorted(t for st in stats.values() for t in st["touch"])
    out = {}
    for b in sorted(stats):
        st = stats[b]
        if st["secs"] < 0.5 or not st["slides"]:
            continue
        sl, rel, dr = sorted(st["slides"]), sorted(st["rel"]), sorted(st["drifts"])
        mine = set(st["touch"])
        idx = [i for i, t in enumerate(touches) if t in mine]
        steps = [touches[i] - touches[i - 1] for i in idx if i > 0 and touches[i] - touches[i - 1] < 1.2]
        jit = [abs(steps[i] - steps[i - 1]) for i in range(1, len(steps))]
        out[f"{b * a.bins:.1f}-{(b + 1) * a.bins:.1f}"] = {
            "seconds": round(st["secs"], 1),
            "support_share": round(st["support"] / st["secs"], 3),
            "slide_mps_median": round(statistics.median(sl), 3),
            "slide_mps_mean": round(statistics.mean(sl), 3),
            "slide_mps_p90": round(sl[int(len(sl) * 0.9)], 3),
            "slide_of_body_median": round(statistics.median(rel), 3),
            "contacts": len(dr),
            "drift_cm_median": round(100 * dr[len(dr) // 2], 1) if dr else None,
            "drift_cm_p90": round(100 * dr[int(len(dr) * 0.9)], 1) if dr else None,
            "steps_per_s": round(len(st["touch"]) / st["secs"], 2),
            "step_jitter_s": round(statistics.median(jit), 3) if jit else None,
        }
    print(f"{'m/s':9s} {'secs':>5s} {'supp':>5s} {'slide med':>9s} {'mean':>6s} {'p90':>6s} {'/body':>6s} {'drift med':>9s} {'p90':>6s} {'n':>4s} {'steps/s':>7s} {'jitter':>6s}")
    for k, v in out.items():
        print(f"{k:9s} {v['seconds']:5.1f} {v['support_share']:5.0%} {v['slide_mps_median']:9.3f} {v['slide_mps_mean']:6.3f} {v['slide_mps_p90']:6.3f} {v['slide_of_body_median']:6.3f} {v['drift_cm_median'] or 0:9.1f} {v['drift_cm_p90'] or 0:6.1f} {v['contacts']:4d} {v['steps_per_s']:7.2f} {v['step_jitter_s'] or 0:6.3f}")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)


PAWS = ("fl", "fr", "hl", "hr")


def paws(a) -> None:
    """The ramp report for an animal: per band of body speed, planted paws' slide, drift and gap."""
    rows = [json.loads(line) for line in open(a.track) if line.strip()]
    rows = [r for r in rows if "paws" in r]
    t0 = rows[0]["t"]
    rows = [r for r in rows if r["t"] - t0 >= a.skip]
    pairs = []
    for prev, cur in zip(rows, rows[1:]):
        dt = cur["t"] - prev["t"]
        if 0 < dt <= 0.1:
            bv = math.dist((prev["root"][0], prev["root"][2]), (cur["root"][0], cur["root"][2])) / dt
            pairs.append((prev, cur, dt, bv))
    moving = [p for p in pairs if p[3] > MOVING]
    if len(moving) < 20:
        sys.exit("too few moving frames")
    up = lambda r, k: r["paws"][k][1] - r["paws"][k][3]
    floor = {}
    for k in PAWS:
        h = sorted(up(c, k) for _, c, _, _ in moving)
        floor[k] = h[max(0, int(len(h) * 0.02))]
    lift = lambda r, k: up(r, k) - floor[k]
    bins = a.bins or 1.0
    band = lambda v: int(v / bins)
    stats = defaultdict(lambda: {"secs": 0.0, "slide": [], "all": [], "drift": [], "gap": [], "support": 0.0})
    run = {k: None for k in PAWS}  # (start xz, band, start t, last xz)
    for prev, cur, dt, bv in pairs:
        if bv <= MOVING:
            for k in PAWS:
                run[k] = None
            continue
        st = stats[band(bv)]
        st["secs"] += dt
        speeds = []
        for k in PAWS:
            planted = lift(prev, k) <= PLANT_M and lift(cur, k) <= PLANT_M
            p0, p1 = (prev["paws"][k][0], prev["paws"][k][2]), (cur["paws"][k][0], cur["paws"][k][2])
            if planted:
                v = math.dist(p0, p1) / dt
                speeds.append(v)
                st["all"].append(v)
                st["gap"].append(up(cur, k) - a.paw_floor)
                if run[k] is None:
                    run[k] = [p0, band(bv), prev["t"], p1]
                run[k][3] = p1
            elif run[k] is not None:
                if cur["t"] - run[k][2] >= 0.1:
                    stats[run[k][1]]["drift"].append(math.dist(run[k][0], run[k][3]))
                run[k] = None
        if speeds:
            st["support"] += dt
            st["slide"].append(min(speeds))
    out = {}
    for b in sorted(stats):
        st = stats[b]
        if st["secs"] < 0.5 or not st["slide"]:
            continue
        sl, al, dr, gp = sorted(st["slide"]), sorted(st["all"]), sorted(st["drift"]), st["gap"]
        ag = sorted(abs(x) for x in gp)
        out[f"{b * bins:.1f}-{(b + 1) * bins:.1f}"] = {
            "seconds": round(st["secs"], 1),
            "support_share": round(st["support"] / st["secs"], 3),
            "slide_mps_median": round(statistics.median(sl), 3),
            "slide_mps_mean": round(statistics.mean(sl), 3),
            "slide_mps_p90": round(sl[int(len(sl) * 0.9)], 3),
            "all_mps_median": round(statistics.median(al), 3),
            "contacts": len(dr),
            "drift_cm_median": round(100 * dr[len(dr) // 2], 1) if dr else None,
            "drift_cm_p90": round(100 * dr[int(len(dr) * 0.9)], 1) if dr else None,
            "gap_cm_median": round(100 * statistics.median(gp), 1),
            "abs_gap_cm_p90": round(100 * ag[int(len(ag) * 0.9)], 1),
            "into_ground_over_3cm": round(sum(x < -0.03 for x in gp) / len(gp), 3),
            "floating_over_3cm": round(sum(x > 0.03 for x in gp) / len(gp), 3),
        }
    print(f"{'m/s':9s} {'secs':>5s} {'supp':>5s} {'slide med':>9s} {'mean':>6s} {'p90':>6s} {'all':>6s} {'drift med':>9s} {'p90':>6s} {'n':>4s} {'gap med':>7s} {'|p90|':>6s} {'in>3':>5s} {'up>3':>5s}")
    for k, v in out.items():
        print(f"{k:9s} {v['seconds']:5.1f} {v['support_share']:5.0%} {v['slide_mps_median']:9.3f} {v['slide_mps_mean']:6.3f} {v['slide_mps_p90']:6.3f} {v['all_mps_median']:6.3f} {v['drift_cm_median'] or 0:9.1f} {v['drift_cm_p90'] or 0:6.1f} {v['contacts']:4d} {v['gap_cm_median']:7.1f} {v['abs_gap_cm_p90']:6.1f} {v['into_ground_over_3cm']:5.0%} {v['floating_over_3cm']:5.0%}")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
