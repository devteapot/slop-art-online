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
    # Group B. Cycles are animate.py's best loop cut on the raw take; the forward picks cut the same way are
    # walk#1 1.067 s and 1.70 m a cycle, run#1 0.70 s and 2.30 m a cycle.
    "walk_back": (1, "cycle 1.10 s (x1.03 of walk#1) at 1.1 m/s: 1.22 m a cycle against walk#1's 1.70 m; hips ahead within 3 degrees; toe ends 1.8 cm under the floor at push-off (11 frames). Seeds 2 and 5 are cleaner on the floor at a 1.0 s and 0.97 s cycle"),
    "run_back": (2, "a backward jog: cycle 0.73 s (x1.05 of run#1) at 2.0 m/s, 1.47 m a cycle against run#1's 2.30 m; almost no flight"),
    "strafe_walk_left": (3, "a step touch: the only seed of 8 whose feet never cross (heels 9.5 to 77 cm apart). Slower than the walk: cycle 1.40 s (x1.31 of walk#1) at 0.46 m/s, 0.64 m a cycle. The relaxed-arm side-step prompts all crossed the trailing foot behind"),
    "strafe_walk_right": (3, "a step touch, feet never cross (heels 4 to 76 cm apart); cycle 1.53 s (x1.44 of walk#1) at 0.44 m/s, 0.69 m a cycle. Seed 0 has the walk's cadence (1.13 s) and no crossing, but its chest turns up to 16 degrees and the arms lift"),
    "strafe_run_left": (3, "crossover steps: cycle 0.70 s (x1.00 of run#1) at 2.0 m/s, 1.40 m a cycle against run#1's 2.30 m; chest within -9..5 degrees of ahead"),
    "strafe_run_right": (6, "crossover steps: cycle 0.67 s (x0.95 of run#1) at 2.0 m/s, 1.33 m a cycle; chest within -7..1 degrees of ahead; toe ends 1.4 cm under the floor for 7 frames"),
    "strafe_walk_cross_left": (1, "not asked for: a sideways walk with the feet crossing, close to the forward walk: cycle 1.00 s (x0.94 of walk#1) at 1.3 m/s, 1.31 m a cycle; arms down"),
    "strafe_walk_cross_right": (3, "not asked for: a sideways walk with the feet crossing: cycle 0.90 s (x0.84 of walk#1) at 1.3 m/s, 1.18 m a cycle; arms down. Seeds 0 and 5 match the walk's cadence but hold the hands at chest height"),
    # Group C. The asked-for hop from a walk did not come out: with a walking run-up the takes kept stepping.
    "jump_back": (3, "from and to the neutral pose, not from a walk; in the air 0.70-1.03 s against the path's hop 0.6-1.044 s. Fails the floor on every seed: toe ends up to 3.7 cm under it for 20 frames here, the least of 8"),
    "jump_left": (3, "from and to the neutral pose, not from a walk; in the air 0.67-1.00 s against the path's hop 0.6-1.044 s; feet clear 0.33 m; toe end 1.8 cm under the floor for 6 frames"),
    "jump_right": (1, "from and to the neutral pose, not from a walk; in the air 0.70-1.03 s against the path's hop 0.6-1.044 s; toe ends 2.2 cm under the floor for 15 frames; the hips turn up to 7 degrees"),
    # Group B, optional diagonals.
    "walk_diag_fl": (5, "cycle 1.00 s (x0.94 of walk#1) at 1.4 m/s, 1.44 m a cycle; the feet cross; chest 3 to 10 degrees to the right of ahead"),
    "walk_diag_fr": (1, "cycle 1.00 s (x0.94 of walk#1) at 1.4 m/s, 1.39 m a cycle; the feet cross; chest within -7..8 degrees. Seed 0 has the walk's cycle but holds the hands at chest height"),
    "walk_diag_bl": (1, "cycle 1.07 s (x1.00 of walk#1) at 1.1 m/s, 1.16 m a cycle; the feet cross; chest within -7..3 degrees"),
    "walk_diag_br": (0, "cycle 1.07 s (x1.00 of walk#1) at 1.1 m/s, 1.16 m a cycle; the feet cross; chest within -6..4 degrees"),
    "run_diag_fl": (3, "cycle 0.73 s (x1.05 of run#1) at 2.6 m/s, 1.91 m a cycle; chest within -7..7 degrees. Seeds 1, 2 and 4 turn the chest 17 to 18 degrees"),
    "run_diag_fr": (5, "cycle 0.70 s (x1.00 of run#1) at 2.6 m/s, 1.84 m a cycle; chest up to 13 degrees to the left of ahead"),
    "run_diag_bl": (5, "a backward jog: cycle 0.77 s (x1.10 of run#1) at 2.0 m/s, 1.54 m a cycle; chest within -6..7 degrees"),
    "run_diag_br": (3, "a backward jog: cycle 0.73 s (x1.05 of run#1) at 2.0 m/s, 1.47 m a cycle; chest within -9..4 degrees"),
}


# Clip lab retakes (`living/tools/kimodo/cliplab.py --write`): the fields of an entry the lab
# changed (prompt, seeds, pick, note, ...), applied over what entries() builds, so --write here
# keeps them. Each retake's scores are in its checks.json in the handoff tarball.
RETAKES = {
    "turn_left_180": {"prompt": "a person turns around to the left on the spot, stepping left, right, left", "seeds": [20, 21, 22, 23, 24, 25, 26, 27], "pick": 25, "note": "three steps (left, right, left); the hips' heading is pinned to a steady turn from 0.3 s to 1.7 s. Clip lab 2026-11-11: the old s4 slid (planted feet 6.3 cm/s p90) and s3 took four steps; s25 (the prompt names the steps) passes every check: LRL, toes 0.4 cm under the floor at most, slide 4.7 cm/s"},
    "jump_stand": {"prompt": "a person jumps high straight up on the spot and lands", "seeds": [20, 21, 22, 23, 24, 25, 26, 27], "pick": 25, "note": "Clip lab 2026-11-11: the hips rise 46 cm and both feet are off the ground 0.57 s (asked: 0.45 m, about 0.6 s); the old s4: 38 cm, 0.47 s. A tuck jump (knees pulled up, feet clear 91 cm) with the arms up, not a small hop. Fails slide only: planted feet 8.0 cm/s p90 at the landing (limit 6)"},
    "run_back": {"pick": 3, "note": "a backward jog: cycle 0.73 s (x1.05 of run#1) at 2.0 m/s, 1.47 m a cycle against run#1's 2.30 m; almost no flight Clip lab 2026-11-11: re-picked s2 -> s3: s2's planted feet slide 10.1 cm/s p90 (gait limit 10), s3's 9.2; s3's chest drifts 6.0 degrees (s2: 2.9)"},
    "jump_back": {"prompt": "a person hops backward with both feet together and lands softly on the balls of the feet", "seeds": [40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55], "pick": 49, "note": "from and to the neutral pose, not from a walk. Clip lab 2026-11-11: in the air 0.40 s (hop window overlap 0.81; the old s3: 0.33 s); still fails the floor: toe tips up to 5.9 cm under it for 16 frames at the landing, as every one of 40 takes does (least: s42, 2.4 cm, 0.33 s in the air)"},
    "jump_right": {"seeds": [20, 21, 22, 23, 24, 25, 26, 27], "pick": 25, "note": "from and to the neutral pose. Clip lab 2026-11-11: in the air 0.43 s, matching the rules' hop window (overlap 0.98; the old s1: 0.33 s); still fails the floor: toe tips up to 3.9 cm under it at the landing (the old s1: 2.2 cm)"},
    "run_diag_fr": {"pick": 4, "note": "cycle 0.70 s (x1.00 of run#1) at 2.6 m/s, 1.84 m a cycle; chest up to 13 degrees to the left of ahead Clip lab 2026-11-11: re-picked s5 -> s4: s5's planted feet slide 10.4 cm/s p90 (gait limit 10), s4's 8.2"},
}


def entries():
    out = []

    def add(name, **e):
        pick, note = PICKS.get(name, (None, None))
        if pick is not None:
            e["pick"] = pick
        if note:
            e["note"] = note
        e.update(RETAKES.get(name, {}))
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
    # Group B: loops for the "face the cursor" scheme. The hips are pinned to a straight line at a
    # steady speed and to face ahead (heading 0). Each has its own speed key, so animate.py keeps
    # its natural speed unless a target is given for that key.
    def loop(name, prompt, seconds, speed, direction, gait, cycle, travel_deg, key, seeds=s8):
        add(name, prompt=prompt, seconds=seconds, seeds=seeds, path=line(seconds, speed, direction), heading=0, kind="loop",
            locomotion=gait, cycle=cycle, skip=1.5, speed=key, travel_deg=travel_deg)

    loop("walk_back", "a person walks backward, looking straight ahead, arms swinging lightly", 6, 1.1, (0, -1), "walk", [0.8, 1.4], 180, "walk_back")
    loop("run_back", "a person jogs backward, backpedaling, looking straight ahead", 5, 2.0, (0, -1), "run", [0.5, 0.9], 180, "run_back")
    for side, x, deg in (("left", 1, -90), ("right", -1, 90)):
        loop(f"strafe_walk_{side}", f"a person does a step touch to the {side}, over and over, arms relaxed at the sides", 6, 0.45, (x, 0),
             "walk", [1.0, 1.8], deg, "strafe_walk")
    for side, x, deg in (("left", 1, -90), ("right", -1, 90)):
        loop(f"strafe_run_{side}", f"a person runs sideways to the {side} with crossover steps, chest facing forward", 5, 2.0, (x, 0),
             "run", [0.5, 0.9], deg, "strafe_run")
    # Not asked for: a sideways walk whose feet cross, at the forward walk's cadence and nearly its
    # cycle length. The step touch above does not cross but is slower and covers 0.64 m a cycle.
    for side, x, deg in (("left", 1, -90), ("right", -1, 90)):
        loop(f"strafe_walk_cross_{side}", f"a person steps sideways to the {side}", 6, 1.3, (x, 0), "walk", [0.8, 1.4], deg, "strafe_walk_cross", s6)

    # Group C: hops for the cursor scheme, from and to the neutral pose, facing ahead. The path
    # holds the rules' hop (1.674 m in 0.444 s) from 0.6 s, with 0.15 s to speed up and to stop.
    t0, total = 0.6, 1.7
    knots = [[0, 0], [t0 - 0.15, 0], [t0, JV], [t0 + JT, JV], [t0 + JT + 0.15, 0], [total, 0]]
    for name, word, d, deg in (("jump_back", "backward", (0, -1), 180), ("jump_left", "sideways to the left", (1, 0), -90),
                               ("jump_right", "sideways to the right", (-1, 0), 90)):
        p = profile(knots, total, d)
        add(name, prompt=f"a person takes a big leap {word} and lands", seconds=total, seeds=s8, start="neutral", end="neutral",
            end_offset=end_of(p), path=p, heading=0, kind="once", travel="path", hop=[t0, round(t0 + JT, 3)], travel_deg=deg)

    # Group B, optional: diagonal travel facing ahead.
    c = 0.7071
    for tag, d, deg in (("fl", (c, c), -45), ("fr", (-c, c), 45), ("bl", (c, -c), -135), ("br", (-c, -c), 135)):
        side = "left" if d[0] > 0 else "right"
        if d[1] > 0:
            loop(f"walk_diag_{tag}", f"a person walks diagonally forward to the {side}, chest facing forward", 6, 1.4, d, "walk", [0.8, 1.4], deg, "walk_diag", s6)
        else:
            loop(f"walk_diag_{tag}", f"a person walks backward diagonally to the {side}, looking straight ahead", 6, 1.1, d, "walk", [0.8, 1.4], deg, "walk_diag_back", s6)
    for tag, d, deg in (("fl", (c, c), -45), ("fr", (-c, c), 45), ("bl", (c, -c), -135), ("br", (-c, -c), 135)):
        side = "left" if d[0] > 0 else "right"
        if d[1] > 0:
            loop(f"run_diag_{tag}", f"a person runs diagonally forward to the {side}, chest facing forward", 5, 2.6, d, "run", [0.5, 0.9], deg, "run_diag", s6)
        else:
            loop(f"run_diag_{tag}", f"a person jogs backward diagonally to the {side}, looking straight ahead", 5, 2.0, d, "run", [0.5, 0.9], deg, "run_diag_back", s6)
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
