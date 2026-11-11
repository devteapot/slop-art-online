"""The locomotion takes' library entries: turns, starts, stops, jumps, and backward and sideways gaits.

    python3 living/tools/kimodo/locomotion.py [--write]

Prints the entries this file defines; `--write` puts them in `living/tools/blender/clips.json`
(replacing entries of the same name, adding the rest at the end, one entry per line). The paths in
those entries are computed here from speed profiles, so this file is their source; the picked
seeds (`PICKS`) and the measured notes are kept here too. `batch.py` then generates the takes.

Frames and units are Kimodo's (SOMA metres, +Z ahead, +X the body's left). Fields for the game
are in the game's convention: `travel_deg` 0 forward, 180 back, -90 left, 90 right, and
`turn_deg` likewise (-90 a quarter turn to the left).

Speeds are the natural ones of the forward picks the new takes sit beside (2026-11-11):
walk#1 1.536 m/s with a 1.045 s cycle, run#1 2.83 m/s with a 0.74 s cycle. The rules' jump is
1.6 tiles at 3.6 tiles/s (`jump_dist`, `jump_speed` in `living/scripts/skills.rhai`): 1.674 SOMA
metres in 0.444 s at the 0.956 game metres per SOMA metre the dodge entry uses.
"""

import json
import os
import sys

W, R = 1.536, 2.83
K = 0.956
JD, JT = 1.6 / K, 1.6 / 3.6
JV = JD / JT

# Footfalls of the forward picks, for keyframes: the game's loops start where the right foot
# comes down (phase 0), so these are phases 0 and 0.5.
WALK_R, WALK_L = "walk#1@83", "walk#1@100"
RUN_R, RUN_L = "run#1@91", "run#1@101"


def profile(knots, total, direction=(0.0, 1.0), step=0.1):
    """A path [[s, x, z], ...] from a speed profile [[s, m/s], ...] (linear between knots), with a
    point every `step` seconds and at every knot."""
    ts = sorted({round(i * step, 3) for i in range(int(round(total / step)) + 1)} | {round(k[0], 3) for k in knots})

    def v(t):
        for (a, va), (b, vb) in zip(knots, knots[1:]):
            if a <= t <= b:
                return va + (vb - va) * (t - a) / (b - a) if b > a else vb
        return knots[-1][1]

    out, d, prev = [], 0.0, 0.0
    for t in ts:
        n = 20
        for i in range(n):
            ta, tb = prev + (t - prev) * i / n, prev + (t - prev) * (i + 1) / n
            d += (v(ta) + v(tb)) / 2 * (tb - ta)
        prev = t
        out.append([t, round(direction[0] * d, 3), round(direction[1] * d, 3)])
    return out


def line(total, speed, direction):
    return [[0, 0, 0], [total, round(direction[0] * speed * total, 3), round(direction[1] * speed * total, 3)]]


def end_of(path):
    return [path[-1][1], path[-1][2]]


# name -> (picked seed, note). Filled in from the review of the raw takes.
PICKS = {
    "turn_left_90": (4, "two steps (left, then right), no overshoot; ends facing 90 degrees left in the neutral pose, so no ease out to the forward-facing neutral"),
    "turn_right_90": (4, "two steps (right, then left); ends facing 90 degrees right in the neutral pose"),
    "turn_left_180": (4, "three steps (left, right, left); the hips' heading is pinned to a steady turn from 0.3 s to 1.7 s"),
    "turn_right_180": (3, "three steps (right, left, right); the hips' heading is pinned to a steady turn from 0.3 s to 1.7 s"),
    "walk_start": (6, "right step, left step, ends as the left heel comes down in walk#1's frame 100 (half a cycle after the loop's start) at walk#1's speed; the hips follow the path (0 to 1.536 m/s between 0.15 s and 0.95 s)"),
    "walk_stop": (3, "starts in walk#1's frame 83 (the right heel comes down: the loop's start) at walk#1's speed; a left step, the right foot closes by 1.07 s, then the neutral pose"),
    "run_start": (2, "right, left, right; ends as the right foot comes down in run#1's frame 91 (the loop's start) at run#1's speed. Seeds 0, 1, 3, 4, 5 step off with the left foot"),
    "run_stop": (1, "starts in run#1's frame 91 (the right foot comes down) at run#1's speed; three braking steps, still by 0.93 s"),
    "jump_stand": (4, "in the air 0.63-1.10 s (0.47 s); the hips rise 0.38 m and the feet clear 0.27 m, less than the 0.45 m asked"),
    "jump_forward": (2, "a leap off the left foot: in the air 0.97-1.43 s, against the path's hop window 0.95-1.394 s (1.674 m at 3.77 m/s, the rules' jump); a run-up at run#1's speed before, slowing to 1.9 m/s after. Only seeds 2, 4 and 7 leap; 4 and 7 are in the air too early or too long"),
}


def entries():
    out = []

    def add(name, **e):
        pick, note = PICKS.get(name, (None, None))
        if pick is not None:
            e["pick"] = pick
        if note:
            e["note"] = note
        out.append({"name": name, **e})

    s6, s8 = list(range(6)), list(range(8))
    still = lambda t: [[0, 0, 0], [t, 0, 0]]

    # Group A: one-shots for both control schemes.
    for side, sign in (("left", 1), ("right", -1)):
        add(f"turn_{side}_90", prompt=f"a person turns 90 degrees to the {side} on the spot in two steps", seconds=1.5, seeds=s6,
            start="neutral", end="neutral", end_yaw=90 * sign, path=still(1.5), kind="once", ease=[0.25, 0.0], turn_deg=-90 * sign)
    for side, sign in (("left", 1), ("right", -1)):
        add(f"turn_{side}_180", prompt=f"a person turns around to the {side} on the spot in three steps", seconds=2.0, seeds=s6,
            start="neutral", end="neutral", end_yaw=180 * sign, path=still(2.0),
            heading=[[0, 0], [0.3, 0], [1.7, 180 * sign], [2.0, 180 * sign]], kind="once", ease=[0.25, 0.0], turn_deg=-180 * sign)
    p = profile([[0, 0], [0.15, 0], [0.95, W], [1.5, W]], 1.5)
    add("walk_start", prompt="a person standing still starts walking forward, stepping off with the right foot", seconds=1.5, seeds=s8,
        start="neutral", end=WALK_L, end_offset=end_of(p), path=p, kind="once", travel="path")
    p = profile([[0, W], [0.15, W], [1.0, 0], [1.5, 0]], 1.5)
    add("walk_stop", prompt="a person walking forward slows down and stops, standing still", seconds=1.5, seeds=s6,
        start=WALK_R, end="neutral", end_offset=end_of(p), path=p, kind="once", travel="path")
    p = profile([[0, 0], [0.1, 0], [1.1, R], [1.4, R]], 1.4)
    add("run_start", prompt="a person standing still starts running forward, pushing off with the right foot first", seconds=1.4, seeds=s8,
        start="neutral", end=RUN_R, end_offset=end_of(p), path=p, kind="once", travel="path")
    p = profile([[0, R], [0.1, R], [1.1, 0], [1.6, 0]], 1.6)
    add("run_stop", prompt="a person running forward slows down quickly and stops, standing still", seconds=1.6, seeds=s6,
        start=RUN_R, end="neutral", end_offset=end_of(p), path=p, kind="once", travel="path")
    add("jump_stand", prompt="a person jumps straight up on the spot and lands", seconds=1.7, seeds=s8,
        start="neutral", end="neutral", path=still(1.7), kind="once")
    t0, total = 0.95, 2.2
    p = profile([[0, R], [t0 - 0.25, R], [t0, JV], [t0 + JT, JV], [t0 + JT + 0.35, 1.9], [total, 1.9]], total)
    add("jump_forward", prompt="a person running forward leaps forward over a gap, lands and keeps walking", seconds=total, seeds=s8,
        path=p, kind="once", travel="path", hop=[t0, round(t0 + JT, 3)])
    return out


def main():
    es = entries()
    lines = ["    " + json.dumps(e) for e in es]
    if "--write" not in sys.argv:
        print(",\n".join(lines))
        return
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender", "clips.json")
    src = open(path).read().rstrip("\n").split("\n")
    assert src[-2].strip() == "]" and src[-1].strip() == "}", "clips.json does not end with the clips list"
    body, names = src[:-2], {e["name"] for e in es}
    is_ours = lambda l: any(l.lstrip().startswith(json.dumps({"name": n})[:-1] + ",") for n in names)
    body = [l for l in body if not is_ours(l)]
    while body and not body[-1].strip():
        body.pop()
    body[-1] = body[-1].rstrip(",") + ","
    body += [""] + [l + "," for l in lines[:-1]] + [lines[-1]]
    open(path, "w").write("\n".join(body + src[-2:]) + "\n")
    json.load(open(path))
    print(f"wrote {len(es)} entries to {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
