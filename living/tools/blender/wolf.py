"""A stylised wolf with a procedural quadruped rig and keyed clips, for the game client
(`quadruped.py` is the rig, keying and export machinery it shares with the deer).

    blender -b -P living/tools/blender/wolf.py -- --out living/game/assets/lookdev/anim/wolf.glb
        [--summary wolf.clips.json] [--seed 1]

Kimodo's SOMA skeleton is a person's, so the wolf's motion is computed here, frame by frame:
each clip is a function from time to the skeleton's joint points (in the wolf's own frame:
forward, left, up, metres, the ground at up = 0). Legs are solved with two-bone IK in their
own vertical plane: a planted paw stays where it touched down while the body passes over it, so
a clip's natural speed is exact and feet don't slide. Bones are then set from their joints'
points and keyed (rotation and location, linear, 30 fps), one action per clip in its own NLA
track, the way `animate.py` exports the characters' library.

The body is a few lofted, low-poly parts (torso and neck, head, jaw, ears, legs, tail) in one
mesh, vertex-coloured on a white `Body` material (coat, darker saddle, pale belly, throat and
muzzle, dark nose and eyes), skinned by distance to each part's own bones. It is about 0.75 m
at the shoulder and 1.2 m from nose to rump, faces +Z in glTF (like the characters), and stands
with its origin on the ground below its middle.

Clips (natural speed in m/s where it moves): idle (loop), walk (loop, 1.3), trot (loop, 3.4:
the rules' wolf `move_speed`), run (loop, gallop, 7.0), bite (a lunge and snap, 0.85 s: windup
to 0.55 s, the rules' `attack_duration` for a wolf, then recovery), leap (a dodge, 0.5 s), hit
(a flinch, 0.45 s, the client's HIT_MS) and death (1.6 s, ends lying on its side). The client
notes are in docs (see the branch report): clip names, speeds and when each plays.

The summary gives every clip's paw contact windows (`contacts`: per paw, normalised clip time,
detected from paw height and world speed, `paw_markers`); the gaits all bring the left hind paw
down at phase 0 (`sync: "hl"`), so the game blends them at one shared phase.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bmesh  # noqa: E402
from quadruped import LEGS, P, Part, Skeleton, args, build, bump, joint, lerp, lerp_c, loft, path_stations, smooth  # noqa: E402


# ---------------------------------------------------------------------------------------------
# The skeleton at rest (forward, up per side; s is the leg's side offset).

SIDE = 0.085  # legs' lateral offset
REST = {
    "pelvis": (-0.40, 0.64), "mid": (-0.08, 0.67), "chest": (0.22, 0.66), "neck": (0.38, 0.73),
    "skull": (0.52, 0.86), "nose": (0.80, 0.80), "jaw0": (0.55, 0.80), "jaw1": (0.77, 0.765),
    "tail0": (-0.50, 0.66), "tail1": (-0.64, 0.60), "tail2": (-0.77, 0.49), "tail3": (-0.86, 0.37),
    # Front leg: shoulder, elbow, wrist, paw (toe). Hind: hip, stifle, hock, paw.
    "shoulder": (0.26, 0.55), "elbow": (0.17, 0.37), "wrist": (0.21, 0.12), "fpaw": (0.26, 0.015),
    "hip": (-0.40, 0.57), "stifle": (-0.29, 0.37), "hock": (-0.45, 0.16), "hpaw": (-0.41, 0.015),
}
SK = Skeleton(REST, SIDE, centre=(-0.09, 0.66))
body_pose, leg_points, neutral_paw, stand = SK.body_pose, SK.leg_points, SK.neutral_paw, SK.stand


def gait(t, speed, period, offsets, duty, lift, body):
    return SK.gait(t, speed, period, offsets, duty, lift, body)


# ---------------------------------------------------------------------------------------------
# Clips: name -> (seconds, loop, natural speed m/s or None, function(t in 0..1) -> Pose)


def clip_idle(t):
    a = 2 * math.pi * t
    body = body_pose(bob=0.006 * math.sin(2 * a), flex=0.05 * math.sin(2 * a), head=(0.08 + 0.04 * math.sin(a), 0.0),
                     head_turn=0.25 * math.sin(a) * smooth(abs(math.sin(a))), tail=(0.05, 0.25 * math.sin(a)))
    p, place = body
    for leg in LEGS:
        leg_points(p, place, leg, neutral_paw(leg))
    return p


def clip_walk(t):
    a = 2 * math.pi * t
    body = body_pose(bob=0.012 * math.cos(2 * a), pitch=0.015 * math.sin(2 * a), head=(0.15 + 0.04 * math.cos(2 * a), 0.05),
                     head_turn=0.06 * math.sin(a), tail=(0.0, 0.18 * math.sin(a)))
    # Lateral sequence: left hind, left fore, right hind, right fore.
    return gait(t, WALK, PERIOD["walk"], {"hl": 0.0, "fl": -0.25, "hr": -0.5, "fr": -0.75}, 0.62, 0.08, body)


def clip_trot(t):
    a = 2 * math.pi * t
    body = body_pose(bob=0.022 * math.cos(2 * a), pitch=0.01 * math.sin(2 * a), head=(0.22, 0.1),
                     tail=(0.1, 0.12 * math.sin(a)))
    # Diagonal pairs together, a short float between.
    return gait(t, TROT, PERIOD["trot"], {"hl": 0.0, "fr": 0.0, "hr": -0.5, "fl": -0.5}, 0.42, 0.11, body)


def clip_run(t):
    a = 2 * math.pi * t
    # Rotary gallop: the back flexes as the hind legs reach under, stretches as the fore reach out.
    flex = 0.7 * math.cos(a)
    body = body_pose(bob=0.05 * math.sin(a + 0.6) + 0.01, pitch=-0.07 * math.sin(a), flex=flex, head=(0.25 - 0.08 * math.sin(a), 0.15),
                     tail=(0.35, 0.05 * math.sin(a)))
    return gait(t, RUN, PERIOD["run"], {"hl": 0.0, "hr": -0.09, "fr": -0.42, "fl": -0.52}, 0.3, 0.16, body)


BITE_S, BITE_SNAP = 0.85, 0.55


def clip_bite(t):
    s = t * BITE_S
    wind = smooth(s / 0.42) * (1 - smooth((s - 0.5) / 0.06))
    lunge = smooth((s - 0.46) / 0.09) * (1 - smooth((s - 0.6) / 0.25))
    jaw = 0.45 * smooth((s - 0.25) / 0.2) * (1 - smooth((s - BITE_SNAP + 0.02) / 0.04)) + 0.1 * bump(s, 0.62, 0.85)
    body = body_pose(shift=-0.08 * wind + 0.3 * lunge, crouch=0.07 * wind - 0.02 * lunge, pitch=0.08 * wind - 0.06 * lunge,
                     head=(0.3 * wind - 0.15 * lunge, 0.25 * lunge), jaw=jaw, tail=(0.25 * wind, 0.0))
    p, place = body
    # Paws stay put; the fore paws step out with the lunge.
    for leg in LEGS:
        f, u = neutral_paw(leg)
        if LEGS[leg][0]:
            step = 0.22 * smooth((s - 0.5) / 0.1) * (1 - smooth((s - 0.62) / 0.2))
            lift = 0.06 * bump(s, 0.48, 0.6)
            leg_points(p, place, leg, (f + step, u + lift), fold=0.6 * bump(s, 0.48, 0.6))
        else:
            leg_points(p, place, leg, (f, u))
    return p


def clip_leap(t):
    s = t * 0.5
    down = smooth(s / 0.1) * (1 - smooth((s - 0.1) / 0.06)) + 0.6 * bump(s, 0.36, 0.5)
    air = bump(s, 0.12, 0.38)
    body = body_pose(bob=0.22 * air, crouch=0.09 * down, flex=-0.3 * air + 0.3 * down, head=(0.1, 0.0), tail=(0.3 * air, 0.4 * air))
    p, place = body
    for leg in LEGS:
        f, u = neutral_paw(leg)
        tuck = 0.13 * air
        leg_points(p, place, leg, (f + (-0.06 if LEGS[leg][0] else 0.08) * air, u + 0.22 * air + tuck), fold=1.0 * air)
    return p


HIT_S = 0.45


def clip_hit(t):
    s = t * HIT_S
    k = smooth(s / 0.07) * (1 - smooth((s - 0.12) / 0.3))
    body = body_pose(shift=-0.07 * k, crouch=0.04 * k, pitch=-0.05 * k, head=(0.15 * k, -0.1 * k), head_turn=0.35 * k, jaw=0.2 * k, tail=(-0.3 * k, 0.0))
    return stand(body)


DEATH_S = 1.6


def clip_death(t):
    s = t * DEATH_S
    buckle = smooth(s / 0.5)
    roll = smooth((s - 0.25) / 0.75)
    limp = smooth((s - 0.6) / 0.8)
    body = body_pose(crouch=0.2 * buckle, pitch=0.12 * buckle * (1 - roll), head=(0.5 * buckle, -0.1), jaw=0.15 * limp, tail=(-0.4 * buckle, 0.0))
    p, place = body
    for leg in LEGS:
        f, u = neutral_paw(leg)
        # The legs fold as it sinks, then lie loose and a little straighter.
        leg_points(p, place, leg, (f + (0.06 if LEGS[leg][0] else -0.05) * limp, u + 0.12 * buckle * (1 - limp) + 0.05 * limp), fold=0.5 * buckle * (1 - limp))
    # Roll onto the right side about the forward axis, settling the body on the ground.
    return SK.lie_down(p, roll)


WALK, TROT, RUN = 1.3, 3.4, 7.0
PERIOD = {"walk": 0.8, "trot": 0.44, "run": 0.32}
CLIPS = {
    "idle": (3.0, True, None, clip_idle),
    "walk": (PERIOD["walk"], True, WALK, clip_walk),
    "trot": (PERIOD["trot"], True, TROT, clip_trot),
    "run": (PERIOD["run"], True, RUN, clip_run),
    "bite": (BITE_S, False, None, clip_bite),
    "leap": (0.5, False, None, clip_leap),
    "hit": (HIT_S, False, None, clip_hit),
    "death": (DEATH_S, False, None, clip_death),
}


# ---------------------------------------------------------------------------------------------
# Mesh

# Display (sRGB) colours: bmesh's colour layer holds sRGB bytes, and the exporter writes them out
# as linear COLOR_0, so these show as written.
COAT = (0.50, 0.49, 0.47)
SADDLE = (0.27, 0.26, 0.25)
PALE = (0.84, 0.80, 0.72)
DARK = (0.08, 0.07, 0.07)
EYE = (0.85, 0.62, 0.20)


def build_mesh(rest):
    bm = bmesh.new()
    parts = []
    J = lambda n: joint(rest, n)  # noqa: E731

    def torso_color(co, n):
        f, s, u = -co.y, co.x, co.z
        pale = smooth((-n.z - 0.2) / 0.5) + smooth((f - 0.25) / 0.12) * smooth((0.70 - u) / 0.08)
        dark = smooth((n.z - 0.45) / 0.4) * smooth((0.30 - f) / 0.3)
        c = tuple(lerp(lerp(a, b, min(1.0, pale)), d, dark * 0.8) for a, b, d in zip(COAT, PALE, SADDLE))
        return c

    # Torso and neck: rump to the base of the skull.
    pts = [P(-0.56, 0, 0.63), J("pelvis"), P(-0.24, 0, 0.665), J("mid"), P(0.08, 0, 0.665), J("chest"), J("neck") + P(0, 0, -0.02),
           P(0.46, 0, 0.80), J("skull") + P(-0.02, 0, 0)]
    # Deep chest, a thick ruff at the neck, narrow waist.
    sizes = [(0.08, 0.08), (0.13, 0.135), (0.125, 0.125), (0.115, 0.12), (0.135, 0.165), (0.15, 0.2), (0.15, 0.175), (0.11, 0.12), (0.08, 0.085)]
    st = path_stations(pts, sizes)
    # The belly tucks up behind the ribs: lift the waist rings' centres.
    st = [(c + (P(0, 0, 0.025) if i in (2, 3) else P(0, 0, -0.035) if i == 5 else P(0, 0, 0)), a, w, h) for i, (c, a, w, h) in enumerate(st)]
    v, f = loft(bm, st, sides=10)
    parts.append(Part(bm, v, f, ["hips", "spine", "chest", "neck", "tail1"], torso_color))

    # Head: skull to nose (upper jaw), and the lower jaw.
    def head_color(co, n):
        f, u = -co.y, co.z
        pale = smooth((-n.z + 0.1) / 0.4) * 0.8 + smooth((f - 0.66) / 0.06) * 0.5
        return tuple(lerp(a, b, min(1.0, pale)) for a, b in zip(COAT, PALE))
    hp = [J("skull") + P(-0.05, 0, 0.0), J("skull") + P(0.04, 0, 0.0), P(0.63, 0, 0.865), P(0.71, 0, 0.83), J("nose") + P(-0.015, 0, 0.0)]
    hs = [(0.068, 0.078), (0.085, 0.08), (0.066, 0.064), (0.044, 0.041), (0.028, 0.027)]
    v, f = loft(bm, path_stations(hp, hs), sides=8)
    parts.append(Part(bm, v, f, ["head"], head_color))
    jp = [J("jaw0"), lerp(J("jaw0"), J("jaw1"), 0.5), J("jaw1")]
    v, f = loft(bm, path_stations(jp, [(0.045, 0.02), (0.035, 0.018), (0.02, 0.012)]), sides=6)
    parts.append(Part(bm, v, f, ["jaw"], lambda co, n: PALE))
    # Nose, eyes and ears.
    for c, r, col in [(J("nose") + P(0.005, 0, 0.012), 0.022, DARK)] + [(P(0.635, s * 0.05, 0.885), 0.014, EYE) for s in (-1, 1)]:
        g = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r)
        bmesh.ops.translate(bm, vec=c, verts=g["verts"])
        parts.append(Part(bm, g["verts"], list({fc for vv in g["verts"] for fc in vv.link_faces}), ["head"], lambda co, n, col=col: col))
    for s in (-1, 1):
        base = [P(0.51, s * 0.075, 0.915), P(0.555, s * 0.045, 0.925), P(0.50, s * 0.03, 0.92)]
        tip = P(0.51, s * 0.075, 1.0)
        vs = [bm.verts.new(q) for q in base] + [bm.verts.new(tip)]
        fs = [bm.faces.new((vs[0], vs[1], vs[3])), bm.faces.new((vs[1], vs[2], vs[3])), bm.faces.new((vs[2], vs[0], vs[3])), bm.faces.new((vs[2], vs[1], vs[0]))]
        parts.append(Part(bm, vs, fs, ["head"], lambda co, n: lerp_c(COAT, SADDLE, 0.6)))

    # Legs.
    for leg, (front, sgn) in LEGS.items():
        names = ("shoulder", "elbow", "wrist", "fpaw") if front else ("hip", "stifle", "hock", "hpaw")
        q = [J(f"{leg}.{n}") for n in names]
        top = q[0] + P(0, 0, 0.06)
        if front:
            pts = [top, q[0], q[1], lerp(q[1], q[2], 0.5), q[2], q[3] + P(-0.03, 0, 0.02), q[3] + P(0.0, 0, 0.01)]
            sz = [(0.06, 0.09), (0.06, 0.08), (0.046, 0.05), (0.034, 0.036), (0.03, 0.03), (0.038, 0.034), (0.035, 0.02)]
            bones = ["chest", f"upper.{leg}", f"fore.{leg}", f"paw.{leg}"]
        else:
            pts = [top, q[0], q[1], lerp(q[1], q[2], 0.5), q[2], q[3] + P(-0.03, 0, 0.02), q[3] + P(0.0, 0, 0.01)]
            sz = [(0.07, 0.11), (0.075, 0.11), (0.05, 0.065), (0.034, 0.04), (0.03, 0.03), (0.038, 0.034), (0.035, 0.02)]
            bones = ["hips", f"thigh.{leg}", f"shin.{leg}", f"paw.{leg}"]

        def leg_color(co, n):
            u = co.z
            inner = smooth((-(n.x * sgn) - 0.1) / 0.5)
            c = lerp_c(COAT, PALE, 0.6 * inner + 0.3 * smooth((0.3 - u) / 0.2))
            return lerp_c(c, SADDLE, smooth((0.03 - u) / 0.02) * 0.5)
        v, f = loft(bm, path_stations(pts, sz), sides=7)
        parts.append(Part(bm, v, f, bones, leg_color))

    # Tail: thick and bushy, a dark tip.
    tp = [J("tail0") + P(0.03, 0, 0.0), J("tail1"), lerp(J("tail1"), J("tail2"), 0.5), J("tail2"), J("tail3"), J("tail3") + (J("tail3") - J("tail2")) * 0.35]
    ts = [(0.035, 0.04), (0.055, 0.06), (0.065, 0.07), (0.06, 0.062), (0.04, 0.04), (0.012, 0.012)]
    v, f = loft(bm, path_stations(tp, ts), sides=7)
    # (Blender +Y is the wolf's back: the tip is past 0.80 m behind its middle.)
    parts.append(Part(bm, v, f, ["hips", "tail1", "tail2", "tail3"],
                      lambda co, n: lerp_c(lerp_c(COAT, SADDLE, smooth((n.z - 0.3) / 0.5) * 0.6), DARK, smooth((co.y - 0.80) / 0.06) * 0.7)))
    return bm, parts


def main():
    a = args()

    def extra(name, rec):
        if name == "bite":
            rec["snap_s"] = BITE_SNAP

    build(SK, "wolf", CLIPS, build_mesh, a.out, a.summary, (0.1, 0.3), extra=extra)


main()
