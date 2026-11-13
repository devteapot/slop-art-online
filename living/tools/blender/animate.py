"""Animation clips for VRoid (VRM 0.x) humanoids, authored headless in Blender.

Run headless:
    blender -b -P living/tools/blender/animate.py -- \
        --in living/game/assets/lookdev/vroid-Vivi.glb \
        --out living/game/assets/lookdev/anim/vroid-Vivi.glb [--clips idle,walk,talk] \
        [--speed 1.4] [--run-speed 3.6] [--height 1.75] [--blend out.blend]

Writes the same character with named, looping clips at 30 fps: idle, walk, talk, run, attack.

`--kimodo NAME=motion.npz` (repeatable) adds a clip retargeted from an NVIDIA Kimodo SOMA-RP
output as generated (see `retarget_kimodo`); `--clips ""` writes only those.

`--library living/tools/blender/clips.json` writes the game's clip library instead (gen_anim.sh
does this; `--summary FILE` records each clip's length, loop, natural and baked speed, source).
Kimodo entries come from the NPZs `living/tools/kimodo/spark.sh` generated (`--kimodo-dir`) and
are made game-ready (`library_clip`):
- `kind: loop`: the cycle whose ends match best by pose, joint velocity and foot contacts
  (`cycle: [min_s, max_s]` after `skip` seconds, or `"whole"` for takes keyframed at both ends),
  cut and closed by spreading the end-to-start difference over the loop. Locomotion
  (`locomotion: walk|run|sneak`) is straightened, faced along its travel and put on a belt (travel
  removed at constant speed); `--speed`, `--run-speed`, `--sneak-speed` and `--target KEY=M/S` set
  the speed a clip's `speed` key (default: its locomotion) is time-scaled to, within
  `--max-scale`; unset keys keep the natural speed.
- `travel_deg` (optional, locomotion loops): the take travels this far from where it faces (the
  game's sense: 0 forward, 180 back, -90 left, 90 right), so it is faced ahead with its travel
  turned there, and its cycle and speed are measured along that direction. The summary gets
  `travel_deg`, `locomotion`, `facing_deg` (the hips' mean heading once faced, the same sense) and
  `cycle_m` (metres a cycle). Entries without it bake exactly as before.
- `kind: once`: a one-shot (`trim: [a, b]` seconds). It eases from and into the library's
  `neutral` pose at ends keyframed to it (`start`/`end: "neutral"`), so it blends with the idles.
  Travel is kept (`travel: belt` takes it out at constant speed; `travel: path` takes out the
  entry's `path` [[s, x, z], …] in SOMA metres, the track batch.py pinned the hips to and the
  game's body moves along by itself, as for the authority's dodge dash);
  `offset: [x, z]` places a clip that continues another (sitting after sit_down).
  `turn_deg` (a turn on the spot; the game's sense, -90 a quarter turn left): the turn is taken
  out of the clip after its feet are planted (`unturn`), so it ends facing ahead in the neutral
  pose, and the summary gives `turn_deg` (measured), `turn_planned_deg` and `turn_curve`
  ([[normalised time, degrees so far], …]) for the game to turn the body along. `hop: [a, b]`
  (seconds, the path's flight) goes to the summary in clip seconds. A `travel: path` one-shot that
  hops, has `travel_deg`, or starts or ends in a gait's frame (`walk#1@100`) gets `path_m`, the
  body's track per frame (game metres: to its left, ahead), and a start or end in a gait baked in
  the same run gets `start_gait`/`end_gait`: {clip, phase}, that frame's phase in the gait's loop.
- Planted feet (`plant`, default on): Kimodo's foot contacts, plus feet near the floor and still,
  pin the heel or the ball of the foot in the game's world; between plants the correction blends;
  `solve_leg` reaches the targets, lowering the hips smoothly where a leg can't.
- Floor guard (`floor_guard`, every Kimodo and overlay clip, after the planting): where a
  foot's heel, ball or toe tip is more than `FLOOR_EPS` (1 cm) under the floor, the ankle is
  lifted by a smooth curve never below that depth and the leg solved to it; the summary gets
  `floor_lift_m` and `floor_frames`. A clip that never goes under bakes exactly as without it.
- `grip: {"R": deg, "L": deg}` curls a hand that holds something (Kimodo's fingers stay relaxed).
- Foot-down markers (`foot_markers`): every clip's summary gets `contacts: {"L": [[a, b], …],
  "R": …}`, each foot's contact windows in normalised clip time, detected from the baked take
  (heel or ball within 3 cm of the floor and slower than 0.3 m/s in the game's world). A gait's
  loop is rotated to start where its right foot comes down (`sync: "R"`, `phase_shift`: the
  fraction it was turned by), so phase 0 is the same event in every gait and the game blends
  them at one shared phase (`living/game/src/anim.rs`).
- `layer: "upper"` is copied to the summary: the game plays that clip on the spine, arms and
  head only while the body moves, over its gait; otherwise (and standing) on the whole body.
Hand-keyed entries: `keyed: <CLIPS name>`, or `overlay` (eased key curves on central bones over
the neutral pose, for head gestures).

Pipeline:
1. Blender's glTF importer reads the VRoid GLB (unknown VRM extensions are ignored). With the
   BLENDER bone heuristic every J_Bip bone's rest frame is the glTF frame rotated into Blender's
   Z-up, so a pose-bone quaternion is the glTF local rotation, component for component. The
   script checks this before keying anything.
2. Each clip is evaluated in glTF space from the CLIPS table below (angles relative to the rest
   pose, which is the T-pose with identity rest rotations), with analytic two-bone IK for the
   legs so planted feet stay on the floor and roll heel to toe. The result is keyed on the pose
   bones, one action per clip, each pushed onto its own NLA track named after the clip.
3. Blender's glTF exporter writes the clips (NLA_TRACKS mode: one glTF animation per track).
4. Blender's exporter cannot round-trip a VRoid file: it drops the VRM extension, the normal and
   emissive textures and the morph-target names, and adds an "Armature" root node. So the
   exported animations (samplers and channels) are grafted, by node name, into a copy of the
   original GLB. Meshes, materials, textures, morph targets, node names and hierarchy stay
   byte-identical; only `animations` and the new buffer data are added. The graft refuses to
   run if Blender's rest translations or rotations differ from the original's.

Conventions (glTF, the character faces −Z, +X is its right, +Y is up; metres are game metres
at --height, converted to file units):
- central bones (Hips, Spine, Chest, UpperChest, Neck, Head): pitch + bends forward, yaw + turns
  to the character's left, roll + leans to its left. Hips also take x, y, z offsets.
- limbs are written for the left side and mirrored to the right (a reflection in X), with the
  right side shifted by the clip's `mirror` phase; `L.` / `R.` entries override one side.
  Shoulder: raise, fwd. UpperArm: down (+ lowers from the T-pose; 90 hangs), swing (+ forward
  about the shoulder's side axis), cross (+ across the body), twist. LowerArm: bend, twist.
  Hand: flex, side. Fingers / Thumb: curl.
- legs are solved by IK from the clip's feet: a gait (walk, run) or planted feet.

Clips loop exactly: the last frame equals the first. Face expressions (blink, mouth) stay
procedural in the game: VRoid's face mesh is a separate glTF scene root, so morph channels
would need a second AnimationPlayer.
"""

import argparse
import json
import math
import os
import shutil
import struct
import sys
import tempfile

import bpy
from mathutils import Matrix, Quaternion, Vector

FPS = 30


# ---------------------------------------------------------------------------------------------
# Curves over a clip's normalised time t in [0, 1). Numbers are constants.


class Curve:
    def __init__(self, f):
        self.f = f

    def __call__(self, t):
        return self.f(t % 1.0)

    def __add__(self, o):
        o = curve(o)
        return Curve(lambda t: self(t) + o(t))

    __radd__ = __add__

    def __sub__(self, o):
        return self + (-1.0) * curve(o)

    def __mul__(self, k):
        return Curve(lambda t: self(t) * k)

    __rmul__ = __mul__

    def __neg__(self):
        return self * -1.0

    def late(self, lag):
        """The same motion, `lag` (fraction of the clip) later: overlap and follow-through."""
        return Curve(lambda t: self(t - lag))


def curve(v):
    return v if isinstance(v, Curve) else Curve(lambda t, v=v: v)


def cos(amp, peak=0.0, n=1):
    """amp·cos, peaking at `peak`, n whole cycles per clip."""
    return Curve(lambda t: amp * math.cos(2 * math.pi * n * (t - peak)))


def monotone(ts, vs, cyclic):
    """Monotone cubic (Fritsch–Carlson) through (ts, vs): eased holds, no overshoot."""
    n = len(ts)
    if cyclic:
        ts = [ts[-1] - 1.0] + list(ts) + [ts[0] + 1.0]
        vs = [vs[-1]] + list(vs) + [vs[0]]
    d = [(vs[i + 1] - vs[i]) / max(ts[i + 1] - ts[i], 1e-9) for i in range(len(ts) - 1)]
    m = [d[0]] + [0.0 if d[i - 1] * d[i] <= 0 else 2 / (1 / d[i - 1] + 1 / d[i]) for i in range(1, len(d))] + [d[-1]]
    if not cyclic:
        m[0], m[-1] = 0.0, 0.0

    def f(t):
        if not cyclic:
            t = min(max(t, ts[0]), ts[-1])
        i = max(j for j in range(len(ts) - 1) if ts[j] <= t) if t >= ts[0] else 0
        h = ts[i + 1] - ts[i]
        s = (t - ts[i]) / h
        h00, h10, h01, h11 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s, -2 * s**3 + 3 * s**2, s**3 - s**2
        return h00 * vs[i] + h10 * h * m[i] + h01 * vs[i + 1] + h11 * h * m[i + 1]

    return f


def keys(*pairs):
    """Cyclic keys (t, value), eased, looping from the last key back to the first."""
    pairs = sorted(pairs)
    f = monotone([p[0] for p in pairs], [p[1] for p in pairs], cyclic=True)
    return Curve(f)


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


# ---------------------------------------------------------------------------------------------
# The clips. Angles in degrees, distances in game metres. See the module docstring for the
# meaning of each channel.

FINGERS = {"curl": 18}
THUMB = {"curl": 10}

# A relaxed standing pose shared by idle and talk: arms hang, elbows and fingers soften.
REST_ARM = {
    "Shoulder": {"raise": -2},
    "UpperArm": {"down": 76, "swing": 4},
    "LowerArm": {"bend": 14, "twist": -15},
    "Hand": {"flex": 6},
}

CLIPS = {
    "idle": dict(
        seconds=4.0,
        mirror=0.0,
        feet=dict(stand=dict(width=1.05, L=dict(dz=0.02, yaw=6), R=dict(dz=-0.03, yaw=4))),
        bones={
            # One breath per loop and one slow weight shift: onto the left foot and back.
            "Hips": dict(x=cos(-0.022, 0.3), y=-0.02 + cos(-0.006, 0.3, 2), roll=cos(-2.0, 0.32), yaw=cos(1.5, 0.35)),
            "Spine": dict(pitch=1.0, roll=cos(1.2, 0.36), yaw=cos(-0.8, 0.4)),
            "Chest": dict(pitch=cos(-1.2, 0.05), roll=cos(0.6, 0.4)),
            "UpperChest": dict(pitch=cos(-1.0, 0.1)),
            "Neck": dict(pitch=-1.0, roll=cos(0.5, 0.45), yaw=keys((0.0, 0), (0.48, 0), (0.6, 4), (0.8, 4), (0.92, 0))),
            # An occasional small head turn, eased in and out, with a slight lag on the neck.
            "Head": dict(pitch=cos(1.2, 0.08) - 1.0, roll=cos(1.0, 0.45),
                         yaw=keys((0.0, 0), (0.5, 0), (0.62, 9), (0.82, 8), (0.95, 0))),
            "Shoulder": dict(raise_=cos(1.5, 0.1) - 2),
            "UpperArm": dict(down=cos(1.2, 0.6) + 76, swing=cos(1.5, 0.15) + 4),
            "LowerArm": dict(bend=cos(2.0, 0.22) + 14, twist=-15),
            "Hand": dict(flex=cos(2.0, 0.3) + 6),
            "Fingers": FINGERS,
            "Thumb": THUMB,
        },
    ),
    "walk": dict(
        seconds=32 / FPS,
        mirror=0.5,
        # t = 0: left heel strike. Stance is 62% of the cycle.
        feet=dict(gait=dict(speed="walk", stance=0.62, heel_pitch=18, toe_pitch=-34, load_end=0.1, heel_off=0.34,
                            lift=0.05, lift_peak=0.4, width=0.9, yaw=5, centre=0.0,
                            swing_pitch=((0.0, -34), (0.3, -12), (0.62, 2), (1.0, 18)), tangent=0.6)),
        bones={
            # Lowest at heel strike, highest passing mid-stance; sway over the stance leg; the
            # swing side's hip drops; the pelvis turns with the swinging leg.
            "Hips": dict(y=-0.05 + cos(-0.016, 0.02, 2), x=cos(-0.022, 0.28), pitch=4 + cos(1.0, 0.1, 2),
                         yaw=cos(-6, 0.0), roll=cos(-3.5, 0.3)),
            # The chest counter-rotates with growing lag up the spine; the head stays level.
            "Spine": dict(pitch=2, yaw=cos(3, 0.02), roll=cos(1.6, 0.32)),
            "Chest": dict(pitch=1, yaw=cos(3, 0.04), roll=cos(1.0, 0.34)),
            "UpperChest": dict(yaw=cos(2.5, 0.06)),
            "Neck": dict(pitch=-3, yaw=cos(-2, 0.08), roll=cos(-1.0, 0.36)),
            "Head": dict(pitch=-3 + cos(1.2, 0.12, 2), yaw=cos(-2, 0.1), roll=cos(-1.2, 0.38)),
            # Arms swing opposite to the legs, the forearm and hand lagging behind.
            "Shoulder": dict(fwd=cos(3, 0.54), raise_=-2),
            "UpperArm": dict(down=76 + cos(2, 0.0, 2), swing=cos(18, 0.54) + 3),
            "LowerArm": dict(bend=cos(9, 0.6) + 22, twist=-15),
            "Hand": dict(flex=cos(5, 0.66) + 8),
            "Fingers": FINGERS,
            "Thumb": THUMB,
        },
    ),
    "run": dict(
        seconds=21 / FPS,
        mirror=0.5,
        # Stance 36%, then flight; land on the mid-foot.
        feet=dict(gait=dict(speed="run", stance=0.36, heel_pitch=6, toe_pitch=-30, load_end=0.06, heel_off=0.16,
                            lift=0.2, lift_peak=0.38, width=0.85, yaw=4, centre=0.04,
                            swing_pitch=((0.0, -30), (0.3, -40), (0.65, -8), (1.0, 6)), tangent=0.5)),
        bones={
            # Lowest at mid-stance (the knee takes the load), highest in flight.
            "Hips": dict(y=-0.1 + cos(-0.03, 0.2, 2), x=cos(-0.012, 0.2), pitch=10, yaw=cos(-9, 0.02), roll=cos(-3, 0.22)),
            "Spine": dict(pitch=5, yaw=cos(5, 0.05), roll=cos(1.5, 0.25)),
            "Chest": dict(pitch=2, yaw=cos(5, 0.08)),
            "UpperChest": dict(yaw=cos(3, 0.1)),
            "Neck": dict(pitch=-8, yaw=cos(-4, 0.12)),
            "Head": dict(pitch=-6 + cos(1.5, 0.25, 2), yaw=cos(-3, 0.14)),
            "Shoulder": dict(fwd=cos(5, 0.53), raise_=1),
            "UpperArm": dict(down=72 + cos(3, 0.0, 2), swing=cos(34, 0.53) + 6),
            "LowerArm": dict(bend=cos(14, 0.6) + 82),
            "Hand": dict(flex=cos(6, 0.66) + 4),
            "Fingers": {"curl": 55},
            "Thumb": {"curl": 25},
        },
    ),
    "talk": dict(
        seconds=3.6,
        mirror=0.0,
        feet=dict(stand=dict(width=1.05, L=dict(dz=0.01, yaw=6), R=dict(dz=-0.03, yaw=4))),
        bones={
            "Hips": dict(y=-0.02, x=keys((0.0, -0.01), (0.5, 0.012)), roll=keys((0.0, -1.0), (0.5, 1.0)), yaw=keys((0.0, 2), (0.55, -2))),
            "Spine": dict(pitch=keys((0.0, 1), (0.2, 3), (0.5, 2), (0.75, 3.5)), roll=keys((0.0, 0.8), (0.5, -0.8)), yaw=keys((0.0, -2), (0.55, 3))),
            "Chest": dict(pitch=cos(-0.8, 0.1, 2), yaw=keys((0.0, -1), (0.58, 2))),
            "UpperChest": dict(pitch=cos(-0.6, 0.12, 2)),
            # Nods land on the gesture beats; a tilt carries the phrase.
            "Neck": dict(pitch=keys((0.0, -1), (0.16, 2), (0.3, -1), (0.46, 2.5), (0.6, -1), (0.76, 2), (0.9, -1)),
                         yaw=keys((0.0, 3), (0.35, -2), (0.7, 4))),
            "Head": dict(pitch=keys((0.0, -2), (0.18, 4), (0.32, -2), (0.48, 5), (0.62, -2), (0.78, 4), (0.92, -2)),
                         roll=keys((0.0, -2), (0.4, 3), (0.8, -1)), yaw=keys((0.0, 4), (0.36, -4), (0.72, 6))),
            "Shoulder": REST_ARM["Shoulder"],
            "UpperArm": dict(down=76 + cos(1.0, 0.6), swing=4),
            "LowerArm": dict(bend=14, twist=-15),
            "Hand": dict(flex=6),
            # Right hand: forearm up, palm opening on three beats, a small retreat between.
            "R.UpperArm": dict(down=keys((0.0, 78), (0.14, 72), (0.3, 76), (0.44, 70), (0.6, 76), (0.74, 72), (0.9, 78)),
                               swing=keys((0.0, 8), (0.14, 18), (0.3, 10), (0.44, 22), (0.6, 10), (0.74, 18), (0.9, 8)),
                               cross=keys((0.0, -4), (0.14, -12), (0.3, -6), (0.44, -16), (0.6, -6), (0.74, -12), (0.9, -4))),
            "R.LowerArm": dict(bend=keys((0.0, 62), (0.15, 50), (0.31, 64), (0.45, 46), (0.61, 64), (0.75, 50), (0.9, 62)),
                               twist=keys((0.0, 40), (0.15, 75), (0.31, 50), (0.45, 80), (0.61, 50), (0.75, 75), (0.9, 40))),
            "R.Hand": dict(flex=keys((0.0, 4), (0.16, -16), (0.32, 2), (0.46, -18), (0.62, 2), (0.76, -14), (0.9, 4))),
            "R.Fingers": dict(curl=keys((0.0, 22), (0.16, 6), (0.32, 20), (0.46, 4), (0.62, 20), (0.76, 8), (0.9, 22))),
            # Left hand: one smaller gesture late in the phrase.
            "L.UpperArm": dict(down=keys((0.0, 76), (0.55, 76), (0.68, 70), (0.85, 74)),
                               swing=keys((0.0, 5), (0.55, 5), (0.68, 22), (0.85, 8))),
            "L.LowerArm": dict(bend=keys((0.0, 14), (0.55, 16), (0.68, 50), (0.85, 24)),
                               twist=keys((0.0, -15), (0.55, -15), (0.68, 55), (0.85, 0))),
            "L.Hand": dict(flex=keys((0.0, 6), (0.55, 6), (0.68, -12), (0.85, 4))),
            "Fingers": FINGERS,
            "Thumb": THUMB,
        },
    ),
    "attack": dict(
        seconds=1.2,
        mirror=0.0,
        # A staggered stance, left foot forward; a right-handed diagonal slash.
        # 0 guard, 0.28 wind-up, 0.44 strike, 0.56 follow-through, 0.85 recover.
        feet=dict(stand=dict(width=1.5, L=dict(dz=-0.16, yaw=-8), R=dict(dz=0.16, yaw=22))),
        bones={
            "Hips": dict(y=keys((0.0, -0.06), (0.28, -0.05), (0.46, -0.1), (0.62, -0.09), (0.85, -0.06)),
                         z=keys((0.0, 0.0), (0.28, 0.04), (0.46, -0.05), (0.62, -0.04), (0.85, 0.0)),
                         yaw=keys((0.0, -8), (0.28, -20), (0.44, 10), (0.58, 14), (0.85, -8)),
                         pitch=keys((0.0, 4), (0.28, 0), (0.46, 10), (0.62, 8), (0.85, 4))),
            "Spine": dict(yaw=keys((0.0, -4), (0.3, -14), (0.45, 12), (0.6, 16), (0.88, -4)),
                          pitch=keys((0.0, 3), (0.3, -2), (0.46, 8), (0.62, 6), (0.88, 3)),
                          roll=keys((0.0, 0), (0.3, -5), (0.46, 6), (0.62, 4), (0.88, 0))),
            "Chest": dict(yaw=keys((0.0, -3), (0.31, -12), (0.46, 12), (0.61, 14), (0.89, -3)),
                          roll=keys((0.0, 0), (0.31, -4), (0.47, 4), (0.89, 0))),
            "UpperChest": dict(yaw=keys((0.0, -2), (0.32, -8), (0.47, 8), (0.62, 10), (0.9, -2))),
            # The head keeps facing the target: it counter-turns the trunk.
            "Neck": dict(yaw=keys((0.0, 8), (0.3, 24), (0.46, -16), (0.62, -22), (0.88, 8)), pitch=keys((0.0, -2), (0.46, -6), (0.88, -2))),
            "Head": dict(yaw=keys((0.0, 8), (0.31, 26), (0.47, -18), (0.63, -24), (0.89, 8)), pitch=keys((0.0, -2), (0.47, -4), (0.89, -2))),
            "Shoulder": dict(raise_=-2),
            "R.Shoulder": dict(raise_=keys((0.0, 0), (0.28, 12), (0.45, -4), (0.6, -6), (0.85, 0)),
                               fwd=keys((0.0, 4), (0.28, -6), (0.45, 12), (0.6, 14), (0.85, 4))),
            # Weapon arm: guard → raised high to the side, elbow up → sweep down and across →
            # follow through past the left hip → back to guard.
            "R.UpperArm": dict(down=keys((0.0, 70), (0.28, -22), (0.44, 70), (0.56, 85), (0.85, 70)),
                               swing=keys((0.0, 30), (0.28, 10), (0.44, 70), (0.56, 45), (0.85, 30)),
                               cross=keys((0.0, 10), (0.28, -20), (0.44, 20), (0.56, 45), (0.85, 10)),
                               twist=keys((0.0, 0), (0.28, 80), (0.44, 0), (0.56, -10), (0.85, 0))),
            "R.LowerArm": dict(bend=keys((0.0, 75), (0.28, 115), (0.42, 15), (0.58, 30), (0.85, 75)),
                               twist=keys((0.0, -30), (0.28, -10), (0.44, -60), (0.85, -30))),
            "R.Hand": dict(flex=keys((0.0, 0), (0.28, -25), (0.43, 25), (0.58, 10), (0.85, 0))),
            "R.Fingers": {"curl": 75},
            "R.Thumb": {"curl": 35},
            # Free arm: guards, then pulls back to counter the strike.
            "L.UpperArm": dict(down=keys((0.0, 72), (0.28, 66), (0.46, 74), (0.85, 72)),
                               swing=keys((0.0, 24), (0.28, 36), (0.46, -12), (0.62, -8), (0.85, 24))),
            "L.LowerArm": dict(bend=keys((0.0, 60), (0.28, 70), (0.46, 35), (0.85, 60))),
            "L.Hand": dict(flex=10),
            "L.Fingers": {"curl": 35},
            "L.Thumb": THUMB,
        },
    ),
}

ORDER = ["idle", "walk", "talk", "run", "attack"]

# ---------------------------------------------------------------------------------------------
# Rotations, in glTF axes.


def rot(axis, deg):
    return Quaternion(axis, math.radians(deg))


def Rx(d):
    return rot((1, 0, 0), d)


def Ry(d):
    return rot((0, 1, 0), d)


def Rz(d):
    return rot((0, 0, 1), d)


def mirror(q):
    """Reflect a left-side rotation through the YZ plane to the right side."""
    return Quaternion((q.w, q.x, -q.y, -q.z))


CENTRAL = ["Hips", "Spine", "Chest", "UpperChest", "Neck", "Head"]
LIMB = ["Shoulder", "UpperArm", "LowerArm", "Hand"]
FINGER_NAMES = ["Thumb", "Index", "Middle", "Ring", "Little"]
# Curl spread: fingers curl more toward the little finger, the middle joint most.
FINGER_GAIN = {"Thumb": 1.0, "Index": 0.85, "Middle": 1.0, "Ring": 1.1, "Little": 1.25}
JOINT_GAIN = [1.0, 1.25, 0.85]
LEG = ["UpperLeg", "LowerLeg", "Foot", "ToeBase"]


def bone(side, name):
    return f"J_Bip_{side}_{name}"


def central_q(c):
    return Ry(c("yaw")) @ Rx(-c("pitch")) @ Rz(c("roll"))


def limb_q(name, c):
    """A left-side limb rotation from its named channels."""
    if name == "Shoulder":
        return Rz(-c("raise_")) @ Ry(-c("fwd"))
    if name == "UpperArm":
        return Ry(-c("cross")) @ Rx(c("swing")) @ Rz(c("down")) @ Rx(c("twist"))
    if name == "LowerArm":
        return Ry(-c("bend")) @ Rx(c("twist"))
    if name == "Hand":
        return Rz(c("flex")) @ Ry(c("side"))
    raise KeyError(name)


# ---------------------------------------------------------------------------------------------
# The skeleton, measured from the imported armature, in glTF coordinates and file units.

C = Matrix.Rotation(math.radians(90), 4, "X")  # glTF (Y up) → Blender (Z up)
CQ = C.to_quaternion()


def to_gltf(v):
    return Vector((v.x, v.z, -v.y))


class Skeleton:
    def __init__(self, arm, meshes, height_m):
        self.arm = arm
        self.rest = {b.name: to_gltf(b.head_local) for b in arm.data.bones}
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
        # Character height (file units) from every mesh's rest vertices, and the foot's sole.
        ys = []
        for m in meshes:
            mw = m.matrix_world
            ys += [to_gltf(mw @ v.co).y for v in m.data.vertices]
        self.height = max(ys) - min(ys)
        self.floor = min(ys)
        self.unit = self.height / height_m  # file units per game metre
        self.feet = {}
        for side in "LR":
            self.feet[side] = self.measure_foot(meshes, side)
        self.body = self.measure_body(meshes)
        L = self.rest
        s = "L"
        self.l1 = (L[bone(s, "LowerLeg")] - L[bone(s, "UpperLeg")]).length
        self.l2 = (L[bone(s, "Foot")] - L[bone(s, "LowerLeg")]).length

    def measure_body(self, meshes):
        """For the limb guard's torso check: per torso bone (BODY_BONES), points on the mesh weighted
        mostly to it and within BODY_REACH_M of it: the vertices furthest out along the cube's 26
        face, edge and corner directions and an even sample of about BODY_POINTS, as offsets from
        the bone in the rest frame (the glTF frame: rest rotations are identity)."""
        dirs = [Vector((x, y, z)).normalized() for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1) if (x, y, z) != (0, 0, 0)]
        pts = {b: [] for b in BODY_BONES if b in self.rest}
        for m in meshes:
            groups = {g.index: g.name for g in m.vertex_groups}
            mw = m.matrix_world
            for v in m.data.vertices:
                if not v.groups:
                    continue
                g = max(v.groups, key=lambda x: x.weight)
                name = groups.get(g.group)
                if g.weight > 0.5 and name in pts:
                    pts[name].append(to_gltf(mw @ v.co))
        out = {}
        reach = BODY_REACH_M * self.unit
        for b, ps in pts.items():
            o = self.rest[b]
            # The body itself, not what hangs from it (a coat's hem weighted to the hips).
            ps = [p for p in ps if (p - o).length <= reach]
            if not ps:
                continue
            keep = {id(p): p for p in (max(ps, key=lambda q: (q - o).dot(d)) for d in dirs)}
            step = max(1, len(ps) // BODY_POINTS)
            keep.update({id(p): p for p in ps[::step]})
            out[b] = [p - o for p in keep.values()]
        return out

    def measure_foot(self, meshes, side):
        ankle, toe = self.rest[bone(side, "Foot")], self.rest[bone(side, "ToeBase")]
        pts = []
        for m in meshes:
            groups = {g.index: g.name for g in m.vertex_groups}
            mw = m.matrix_world
            for v in m.data.vertices:
                w = sum(g.weight for g in v.groups if groups.get(g.group) in (bone(side, "Foot"), bone(side, "ToeBase")))
                if w > 0.5:
                    pts.append(to_gltf(mw @ v.co))
        if not pts:
            raise SystemExit(f"no vertices weighted to {bone(side, 'Foot')}")
        sole = min(p.y for p in pts)
        heel_z = max(p.z for p in pts)
        tip_z = min(p.z for p in pts)
        return dict(
            ankle=ankle.copy(),
            toe=toe.copy(),
            heel=Vector((ankle.x, sole, heel_z)),
            tip=Vector((toe.x, sole, tip_z)),
            sole=sole,
            # How far the foot reaches out sideways from the ankle (a foot lying on its side).
            half_width=max(abs(p.x - ankle.x) for p in pts),
        )


# ---------------------------------------------------------------------------------------------
# Evaluating a clip at time t: local rotations (glTF) per bone, and the hips' offset.


class Channels:
    def __init__(self, spec, t):
        self.spec, self.t = spec, t

    def __call__(self, name):
        v = self.spec.get(name, 0.0)
        return curve(v)(self.t)


def merged(bones, side, name):
    spec = dict(bones.get(name, {}))
    spec.update(bones.get(f"{side}.{name}", {}))
    return spec


def foot_pose(sk, side, dx, dz, pitch, yaw, toe_local):
    """Foot pose from a flat-foot displacement and a pitch about the heel (toes up) or the ball
    joint (heel up). Returns the ankle position and the foot and toe world rotations."""
    f = sk.feet[side]
    d = Vector((dx, 0, dz))
    yawq = Ry(yaw if side == "L" else -yaw)
    R = yawq @ Rx(pitch)
    pivot = (f["heel"] if pitch > 0 else f["toe"])
    pivot_w = f["ankle"] + yawq @ (pivot - f["ankle"]) + d
    ankle = pivot_w + R @ (f["ankle"] - pivot)
    if toe_local is None:  # heel up in stance: the toes stay flat on the floor
        toe = yawq
    else:
        toe = R @ Rx(toe_local)
    return ankle, R, toe


def gait_foot(sk, g, side, u, v):
    """One foot of a gait at its own phase u (0 = its heel strike). v: belt speed, file units per
    clip. Returns (ankle, foot rotation, toe rotation, in stance)."""
    st = g["stance"]
    width = sk.feet[side]["ankle"].x * (g["width"] - 1.0)
    centre = g["centre"] * sk.unit

    def stance_pose(u):
        dz = v * (u - st * 0.5) + centre
        if u < g["load_end"]:
            pitch = g["heel_pitch"] * (1 - smooth(u / g["load_end"]))
        elif u < g["heel_off"]:
            pitch = 0.0
        else:
            s = (u - g["heel_off"]) / (st - g["heel_off"])
            pitch = g["toe_pitch"] * s * s
        return foot_pose(sk, side, width, dz, pitch, g["yaw"], 0.0 if pitch >= 0 else None)

    if u < st:
        a, R, toe = stance_pose(u)
        return a, R, toe, True
    s = (u - st) / (1 - st)
    a0, _, _ = stance_pose(st - 1e-6)
    a1, _, _ = stance_pose(0.0)
    # Hermite between toe-off and the next heel strike, both moving with the belt.
    m = Vector((0, 0, v * (1 - st))) * g["tangent"]
    h00, h10, h01, h11 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s, -2 * s**3 + 3 * s**2, s**3 - s**2
    a = h00 * a0 + h10 * m + h01 * a1 + h11 * m
    peak = g["lift_peak"]
    k = math.log(0.5) / math.log(peak)
    a.y += g["lift"] * sk.unit * math.sin(math.pi * s**k)
    pitch = monotone([p[0] for p in g["swing_pitch"]], [p[1] for p in g["swing_pitch"]], cyclic=False)(s)
    toe_local = -g["toe_pitch"] * (1 - smooth(s / 0.35))
    yaw = g["yaw"]
    yawq = Ry(yaw if side == "L" else -yaw)
    R = yawq @ Rx(pitch)
    return a, R, R @ Rx(toe_local), False


def frame_q(direction, lateral):
    """Rotation whose columns are (direction, lateral ⟂ direction, their cross)."""
    d = direction.normalized()
    l = (lateral - lateral.dot(d) * d).normalized()
    return Matrix((d, l, d.cross(l))).transposed()


def solve_leg(sk, side, hip_pos, hips_rot, ankle, foot_rot, toe_rot, stats, pole=None):
    """Two-bone IK: thigh and shin rotations that put the ankle at `ankle`, the knee bending
    toward `pole` (default: where the foot points, horizontally)."""
    L = sk.rest
    ul, ll, ft = (L[bone(side, n)] for n in ("UpperLeg", "LowerLeg", "Foot"))
    thigh0, shin0 = ll - ul, ft - ll
    l1, l2 = thigh0.length, shin0.length
    d = ankle - hip_pos
    dist = d.length
    reach = (l1 + l2) * 0.9995
    if dist > reach:
        stats["overreach"] = max(stats.get("overreach", 0.0), dist - reach)
        dist = reach
    dist = max(dist, abs(l1 - l2) + 1e-4)
    dh = d.normalized()
    if pole is None:
        # The knee points where the foot points (horizontally).
        pole = foot_rot @ Vector((0, 0, -1))
        pole.y = 0
    pole = pole.normalized()
    perp = pole - pole.dot(dh) * dh
    if perp.length < 1e-6:
        perp = Vector((0, 0, -1))
    perp.normalize()
    a = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    knee = hip_pos + dh * a + perp * h
    end = hip_pos + dh * dist
    hinge = (end - hip_pos).cross(perp).normalized()
    X = Vector((1, 0, 0))
    r_thigh = frame_q(knee - hip_pos, hinge) @ frame_q(thigh0, X).inverted()
    r_shin = frame_q(end - knee, hinge) @ frame_q(shin0, X).inverted()
    q_thigh, q_shin = r_thigh.to_quaternion(), r_shin.to_quaternion()
    fq, tq = foot_rot, toe_rot
    return {
        bone(side, "UpperLeg"): hips_rot.inverted() @ q_thigh,
        bone(side, "LowerLeg"): q_thigh.inverted() @ q_shin,
        bone(side, "Foot"): q_shin.inverted() @ fq,
        bone(side, "ToeBase"): fq.inverted() @ tq,
    }


def finger_curl(sk, side, fn, curl):
    """Local rotations of one finger's three joints curled by `curl` degrees (spread by
    FINGER_GAIN and JOINT_GAIN)."""
    out = {}
    curl *= FINGER_GAIN[fn]
    for j in range(3):
        b = bone(side, f"{fn}{j + 1}")
        child = bone(side, f"{fn}{j + 2}") if j < 2 else None
        tip = sk.rest[child] if child in sk.rest else None
        if tip is None:
            # The last joint bends like the one before it.
            prev = sk.rest[bone(side, f"{fn}{j}")]
            direction = (sk.rest[b] - prev).normalized()
        else:
            direction = (tip - sk.rest[b]).normalized()
        axis = direction.cross(Vector((0, -1, 0))).normalized()
        if fn == "Thumb":  # the thumb folds toward the palm's centre, under the hand
            axis = direction.cross(Vector((1.0 if side == "L" else -1.0, -1.0, 0.0))).normalized()
        out[b] = Quaternion(axis, math.radians(curl * JOINT_GAIN[j]))
    return out


def evaluate(sk, name, clip, t, speeds, stats, drop=0.0):
    """Local rotations (glTF frame) for every animated bone, and the hips' translation offset."""
    bones = clip["bones"]
    out = {}
    hc = Channels(bones.get("Hips", {}), t)
    for nm in CENTRAL:
        out[bone("C", nm)] = central_q(Channels(bones.get(nm, {}), t))
    hips_off = Vector((hc("x"), hc("y"), hc("z"))) * sk.unit
    hips_off.y -= drop
    shift = clip["mirror"]
    for side in "LR":
        ts = t + (shift if side == "R" and shift else 0.0)
        for nm in LIMB:
            # Shared channels run at the side's phase; one-sided overrides at the clip's.
            spec, side_spec = bones.get(nm, {}), bones.get(f"{side}.{nm}", {})
            q = limb_q(nm, lambda ch: curve(side_spec[ch])(t) if ch in side_spec else curve(spec.get(ch, 0.0))(ts))
            out[bone(side, nm)] = q if side == "L" else mirror(q)
        for fn in FINGER_NAMES:
            spec = merged(bones, side, "Thumb" if fn == "Thumb" else "Fingers")
            tt = ts if (side == "R" and shift and f"R.{'Thumb' if fn == 'Thumb' else 'Fingers'}" not in bones) else t
            out.update(finger_curl(sk, side, fn, curve(spec.get("curl", 0.0))(tt)))
    # Legs.
    hips_rot = out[bone("C", "Hips")]
    feet = clip["feet"]
    targets = {}
    if "gait" in feet:
        g = feet["gait"]
        v = speeds[g["speed"]] * sk.unit * clip["seconds"]  # file units per cycle
        for side in "LR":
            u = (t + (0.5 if side == "R" else 0.0)) % 1.0
            targets[side] = gait_foot(sk, g, side, u, v)
    else:
        s = feet["stand"]
        for side in "LR":
            fs = s.get(side, {})
            c = Channels(fs, t)
            dx = sk.feet[side]["ankle"].x * (s.get("width", 1.0) - 1.0) + c("dx") * sk.unit
            pitch = c("pitch")
            a, R, toe = foot_pose(sk, side, dx, c("dz") * sk.unit, pitch, c("yaw"), 0.0 if pitch >= 0 else None)
            targets[side] = (a, R, toe, True)
    # Lower the hips if a leg can't reach its foot (the knee would lock and the foot float).
    hips_rest = sk.rest[bone("C", "Hips")]
    dropped = 0.0
    for _ in range(6):
        worst = 0.0
        for side in "LR":
            hip = hips_rest + hips_off + hips_rot @ (sk.rest[bone(side, "UpperLeg")] - hips_rest)
            d = (targets[side][0] - hip)
            over = d.length - (sk.l1 + sk.l2) * 0.999
            if over > 0:
                worst = max(worst, over * d.length / max(abs(d.y), 1e-3))
        if worst <= 0:
            break
        hips_off.y -= worst
        dropped += worst
    if dropped:
        stats["hip_drop"] = max(stats.get("hip_drop", 0.0), dropped)
        stats["dropped_frames"] = stats.get("dropped_frames", 0) + 1
    for side in "LR":
        hip = hips_rest + hips_off + hips_rot @ (sk.rest[bone(side, "UpperLeg")] - hips_rest)
        a, R, toe, planted = targets[side]
        out.update(solve_leg(sk, side, hip, hips_rot, a, R, toe, stats))
        # Floor check: the lowest of heel, ball and tip.
        f = sk.feet[side]
        heel = a + R @ (f["heel"] - f["ankle"])
        ball = a + R @ (f["toe"] - f["ankle"])
        tip = ball + toe @ (f["tip"] - f["toe"])
        low = min(heel.y, tip.y, ball.y - (f["toe"].y - f["sole"]))
        key = "stance_low" if planted else "swing_low"
        lo, hi = stats.get(key, (1e9, -1e9))
        stats[key] = (min(lo, low - f["sole"]), max(hi, low - f["sole"]))
    return out, hips_off, dropped


def smooth_drop(drops, r=3, cyclic=True):
    """Dilate-then-blur (cyclic for a loop): a smooth curve never below the drops it covers."""
    n = len(drops)
    at = (lambda i: drops[i % n]) if cyclic else (lambda i: drops[min(max(i, 0), n - 1)])
    dil = [max(at(i + k) for k in range(-r, r + 1)) for i in range(n)]
    dat = (lambda i: dil[i % n]) if cyclic else (lambda i: dil[min(max(i, 0), n - 1)])
    w = [math.cos(k / (r + 1) * math.pi / 2) ** 2 for k in range(-r, r + 1)]
    return [sum(dat(i + k) * w[k + r] for k in range(-r, r + 1)) / sum(w) for i in range(n)]


# ---------------------------------------------------------------------------------------------
# Blender: import, key, export.


def import_model(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path, bone_heuristic="BLENDER", guess_original_bind_pose=False, disable_bone_shape=True)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise SystemExit(f"expected one armature, found {len(arms)}")
    arm = arms[0]
    if (arm.matrix_world - Matrix.Identity(4)).to_scale().length > 1e-6 or any(abs(x) > 1e-6 for r in (arm.matrix_world - Matrix.Identity(4)) for x in r):
        raise SystemExit("armature object is not at identity; the rest-frame shortcut does not hold")
    # Every bone's rest frame must be the glTF frame turned to Z-up: then a pose quaternion is
    # the glTF local rotation.
    bad = [b.name for b in arm.data.bones if b.name.startswith("J_Bip") and b.matrix_local.to_quaternion().rotation_difference(CQ).angle > 1e-4]
    if bad:
        raise SystemExit(f"rest rotations are not identity in glTF for {bad[:5]}… (not a VRoid T-pose?)")
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(md.type == "ARMATURE" for md in o.modifiers)]
    return arm, meshes


def key_clip(arm, sk, name, clip, speeds):
    """Evaluate a CLIPS entry over one loop and key it."""
    n = round(clip["seconds"] * FPS)
    # Pass 1 finds where the legs can't reach and the hips must come down; pass 2 lowers them
    # along a smooth curve instead, so the clamp leaves no corners.
    drops = [evaluate(sk, name, clip, f / n, speeds, {})[2] for f in range(n)]
    extra = smooth_drop(drops) if any(drops) else [0.0] * n
    stats = {}
    if any(drops):
        stats["hip_lowered"] = max(extra)
    frames = []
    for f in range(n + 1):
        t = (f % n) / n
        out, off, _ = evaluate(sk, name, clip, t, speeds, stats, extra[f % n])
        frames.append((out, off))
    return key_frames(arm, name, frames, stats)


def key_frames(arm, name, frames, stats):
    """Key per-frame local rotations (glTF frame) and hips offsets as one action on its own NLA
    track; returns the keyed values for the graft's check."""
    n = len(frames) - 1
    act = bpy.data.actions.new(name)
    arm.animation_data_create()
    arm.animation_data.action = act
    pbones = arm.pose.bones
    values = {}
    for b in frames[0][0]:
        if b not in pbones:
            continue
        pb = pbones[b]
        pb.rotation_mode = "QUATERNION"
        prev = None
        seq = []
        for q, _ in frames:
            qq = q[b].copy()
            if prev is not None and prev.dot(qq) < 0:
                qq.negate()
            prev = qq
            seq.append(qq)
        values[b] = seq
        path = pb.path_from_id("rotation_quaternion")
        comps = [[q.w for q in seq], [q.x for q in seq], [q.y for q in seq], [q.z for q in seq]]
        for i, comp in enumerate(comps):
            fc = act.fcurve_ensure_for_datablock(arm, path, index=i, group_name=b)
            fc.keyframe_points.add(len(comp))
            fc.keyframe_points.foreach_set("co", [x for f, v in enumerate(comp) for x in (f, v)])
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
            fc.update()
    hips = bone("C", "Hips")
    path = pbones[hips].path_from_id("location")
    for i in range(3):
        fc = act.fcurve_ensure_for_datablock(arm, path, index=i, group_name=hips)
        comp = [off[i] for _, off in frames]
        fc.keyframe_points.add(len(comp))
        fc.keyframe_points.foreach_set("co", [x for f, v in enumerate(comp) for x in (f, v)])
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
        fc.update()
    values["__hips_loc"] = [off.copy() for _, off in frames]
    arm.animation_data.action = None
    track = arm.animation_data.nla_tracks.new()
    track.name = name
    strip = track.strips.new(name, 0, act)
    strip.name = name
    act.use_fake_user = True
    print(f"ANIM {name}: {n} frames, {n / FPS:.3f} s, {len(values) - 1} bones, "
          + ", ".join(f"{k}={v[0]:+.4f}..{v[1]:+.4f}" if isinstance(v, tuple) else f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}" for k, v in stats.items()))
    return values


# NVIDIA Kimodo's SOMA skeleton → VRoid J_Bip (side letter → SOMA prefix). SOMA's `Leg` is the
# thigh and `Shin` the knee; its fingers have a metacarpal joint (`…1`) that J_Bip lacks.
SOMA_CENTRAL = {"Hips": "Hips", "Spine": "Spine1", "Chest": "Spine2", "UpperChest": "Chest", "Neck": "Neck1", "Head": "Head"}
SOMA_LIMB = {
    "Shoulder": "Shoulder", "UpperArm": "Arm", "LowerArm": "ForeArm", "Hand": "Hand",
    "UpperLeg": "Leg", "LowerLeg": "Shin", "Foot": "Foot", "ToeBase": "ToeBase",
    "Thumb1": "HandThumb1", "Thumb2": "HandThumb2", "Thumb3": "HandThumb3",
    **{f"{v}{i}": f"Hand{s}{i + 1}" for v, s in [("Index", "Index"), ("Middle", "Middle"), ("Ring", "Ring"), ("Little", "Pinky")] for i in (1, 2, 3)},
}
SOMA_HIPS_REST = 1.005  # SOMA's rest hips height above the soles, m


# The SOMA skeleton (joint names, parents, rest pose): fixed data, kept in the repo so any machine
# with the Kimodo NPZ cache can build the clips.
SOMA_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kimodo", "somaskel77_skeleton.json")
TURN = Matrix.Diagonal((-1.0, 1.0, -1.0))  # SOMA faces +Z, VRoid −Z: half a turn round Y
HIPS = bone("C", "Hips")


class Soma:
    """The SOMA → J_Bip mapping for one character: which joint drives which bone, each bone's
    nearest mapped ancestor, and the hips-height ratio that scales SOMA metres to file units."""

    def __init__(self, sk, skeleton_json):
        js = json.load(open(skeleton_json))
        self.index = {j["name"]: j["index"] for j in js["joints"]}
        pairs = {bone("C", b): s for b, s in SOMA_CENTRAL.items()}
        for side, prefix in (("L", "Left"), ("R", "Right")):
            pairs.update({bone(side, b): prefix + s for b, s in SOMA_LIMB.items()})
        self.pairs = {b: self.index[s] for b, s in pairs.items() if b in sk.parent and s in self.index}

        def mapped_parent(b):
            p = sk.parent.get(b)
            while p is not None and p not in self.pairs:
                p = sk.parent.get(p)
            return p

        self.parents = {b: mapped_parent(b) for b in self.pairs}
        self.k = (sk.rest[HIPS].y - sk.floor) / SOMA_HIPS_REST  # file units per SOMA metre
        self.k_game = self.k / sk.unit  # game metres per SOMA metre

    def frame(self, G, root):
        """One frame: J_Bip local rotations (glTF frame) from SOMA global rotations [77, 3, 3],
        and the hips offset from SOMA hips position `root` (metres, travel already removed)."""
        glob = {b: TURN @ Matrix(G[j].tolist()) @ TURN for b, j in self.pairs.items()}
        out = {}
        for b in self.pairs:
            p = self.parents[b]
            local = glob[b] if p is None else glob[p].transposed() @ glob[b]
            out[b] = local.to_quaternion().normalized()
        off = TURN @ Vector((float(root[0]), float(root[1]) - SOMA_HIPS_REST, float(root[2]))) * self.k
        return out, off


def retarget_kimodo(sk, path):
    """Frames from a Kimodo SOMA-RP NPZ, as generated. Both skeletons rest in a T-pose with
    identity rest rotations (arms along ±X, Y up); SOMA faces +Z and VRoid −Z, so each joint's
    global rotation is turned half round Y, and each J_Bip bone's local rotation is its mapped
    joint's global rotation relative to its nearest mapped ancestor's (SOMA joints J_Bip lacks,
    like Neck2, fold into the next bone). The hips keep their sway and bob but not their travel
    (the game moves the character), scaled by the ratio of hips heights."""
    import numpy as np

    soma = Soma(sk, SOMA_JSON)
    d = np.load(path)
    root = d["root_positions"].copy()
    root[:, [0, 2]] -= d["smooth_root_pos"][:, [0, 2]]
    frames = [soma.frame(d["global_rot_mats"][t], root[t]) for t in range(root.shape[0])]
    print(f"KIMODO {os.path.basename(path)}: {len(frames)} frames, {len(soma.pairs)} bones mapped")
    return frames


# ---------------------------------------------------------------------------------------------
# Kimodo clips made game-ready (`--library`). Work in SOMA space (numpy) first: pick the frames,
# face the clip forward, take the travel out; then retarget, close the loop or ease into the
# neutral pose, time-scale, and finally plant the feet with the leg IK.

SOMA_HIP_JOINTS = ("LeftLeg", "RightLeg")
CONTACT = {"L": (0, 1, 2), "R": (3, 4, 5)}  # Kimodo foot_contacts: heel, toe, toe end per side


def np_yaw(phi):
    import numpy as np

    c, s = math.cos(phi), math.sin(phi)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def soma_heading(soma, P):
    """Kimodo's heading per frame from the hip joints: 0 faces +Z. P: [T, 77, 3]."""
    import numpy as np

    d = P[:, soma.index["RightLeg"]] - P[:, soma.index["LeftLeg"]]
    return np.unwrap(np.arctan2(d[:, 2], -d[:, 0]))


def find_cycle(soma, m, lo, hi, skip, loco):
    """The loop [i, j) whose ends match best: pose (joint positions about the hips, facing
    forward), joint velocities and foot contacts, with j − i in [lo, hi] frames."""
    import numpy as np

    P, root, C = m["P"], m["root"], m["contacts"]
    T = P.shape[0]
    h = soma_heading(soma, P)
    joints = sorted(set(soma.pairs.values()))
    F = np.stack([(P[t, joints] - root[t]) @ np_yaw(-h[t]).T for t in range(T)])  # [T, J, 3]
    F = np.concatenate([F.reshape(T, -1), root[:, 1:2]], axis=1)
    V = np.zeros_like(F)
    V[1:-1] = (F[2:] - F[:-2]) * (FPS / 2)
    best = None
    for i in range(skip, T - lo - 1):
        for j in range(i + lo, min(i + hi, T - 2) + 1):
            cost = np.mean((F[i] - F[j]) ** 2) + 0.01 * np.mean((V[i] - V[j]) ** 2)
            cost += 2e-4 * np.sum(C[i] != C[j])
            if not loco:
                cost += 1e-3 * (h[j] - h[i]) ** 2
            if best is None or cost < best[0]:
                best = (cost, i, j)
    if best is None:
        raise SystemExit(f"no cycle of {lo}..{hi} frames after frame {skip} in a {T}-frame clip")
    return best[1], best[2], math.sqrt(best[0])


# A foot joint counts as planted when Kimodo says so, or when it is this close to its flat-foot
# height (m) and moving slower than SOMA_STILL m/s in the motion's own world. Kimodo's labels
# are short for running feet.
SOMA_FLAT = {"Foot": 0.071, "ToeBase": 0.020}
SOMA_NEAR, SOMA_STILL = 0.015, 0.35


def soma_contacts(soma, P, C):
    import numpy as np

    C = C.copy()
    for side, prefix in (("L", "Left"), ("R", "Right")):
        for col, joint in zip(CONTACT[side][:2], ("Foot", "ToeBase")):
            p = P[:, soma.index[prefix + joint]]
            v = np.zeros(len(p))
            v[1:-1] = np.hypot(p[2:, 0] - p[:-2, 0], p[2:, 2] - p[:-2, 2]) * (FPS / 2)
            v[0], v[-1] = v[1], v[-2]
            C[:, col] |= (p[:, 1] < SOMA_FLAT[joint] + SOMA_NEAR) & (v < SOMA_STILL)
    return C


def soma_window(soma, m, spec, cyc):
    """Cut [i, j] (inclusive) out of a Kimodo motion, face it forward and remove its travel.
    Returns the SOMA arrays for the window and the belt travel over it (metres, SOMA frame)."""
    import numpy as np

    i, j = cyc
    G, P, root, C = (m[k][i : j + 1].copy() for k in ("G", "P", "root", "contacts"))
    n = j - i
    h = soma_heading(soma, P)
    loco = spec.get("locomotion")
    if loco:
        # Straighten a curving path: undo the heading drift over the loop, a little each frame,
        # turning each frame's travel with it.
        drift = h[-1] - h[0]
        steps = root[1:] - root[:-1]
        P = P - root[:, None, :]
        newroot = [root[0].copy()]
        for f in range(1, n + 1):
            R = np_yaw(-drift * f / n)
            G[f] = R @ G[f]
            P[f] = P[f] @ R.T
            newroot.append(newroot[-1] + R @ steps[f - 1])
        root = np.stack(newroot)
        P = P + root[:, None, :]
        d = root[-1] - root[0]
        face = math.atan2(d[0], d[2])  # travel direction → +Z
        if "travel_deg" in spec:
            # A take that travels to the side or backward faces ahead: its travel is turned to
            # `travel_deg` from the facing (the game's sense: -90 left, 90 right, 180 back), so
            # the cycle and its speed are measured along the take's own direction.
            face += math.radians(spec["travel_deg"])
    else:
        face = float(h[0])
    R = np_yaw(-face)
    for f in range(n + 1):
        G[f] = R @ G[f]
    P = P @ R.T
    root = root @ R.T
    if not loco and abs(soma_heading(soma, P[:1])[0]) > 1e-3:
        raise SystemExit("facing the clip forward went the wrong way")
    C = soma_contacts(soma, P, C)
    travel = spec.get("travel") or ("belt" if loco or spec["kind"] == "loop" else "keep")
    start = root[0].copy()
    belt = np.zeros(3)
    if travel == "belt":
        belt = root[-1] - start
        belt[1] = 0.0
    shift = np.stack([start + belt * f / n for f in range(n + 1)])
    if travel == "path":
        # The travel the game's body performs itself (the entry's `path`, as batch.py pinned
        # it): taken out exactly, so what remains is the clip's own motion about the body.
        pts = spec["path"]
        ts = [p[0] for p in pts]
        at = lambda k: np.array([np.interp((i + f) / FPS, ts, [p[k] for p in pts]) for f in range(n + 1)])
        shift = np.stack([start[0] + at(1), np.zeros(n + 1), start[2] + at(2)], axis=1)
        belt = shift[-1] - shift[0]
    shift[:, 1] = 0.0
    # Clips that continue another one's end (sitting after sit_down) sit where it ended.
    ox, oz = spec.get("offset", (0.0, 0.0))
    shift[:, 0] -= ox
    shift[:, 2] -= oz
    root = root - shift
    P = P - shift[:, None, :]
    residual = float(np.hypot(root[:, 0], root[:, 2]).max()) if travel == "path" else 0.0
    track = (shift - shift[0]) if travel == "path" else None
    return dict(G=G, P=P, root=root, contacts=C, belt=belt, n=n, residual=residual, track=track, heading=soma_heading(soma, P))


def neutral_frame(sk, soma, ref, kdir):
    """The library's neutral pose (`name#seed@frame`), facing forward with its hips over the
    origin, as J_Bip local rotations and a hips offset."""
    import numpy as np

    name_seed, frame = ref.split("@")
    name, seed = name_seed.split("#")
    m = load_soma(os.path.join(kdir, f"{name}_s{int(seed)}.npz"))
    f = int(frame) % m["P"].shape[0]
    R = np_yaw(-float(soma_heading(soma, m["P"][f : f + 1])[0]))
    root = m["root"][f].copy()
    root[[0, 2]] = 0.0
    return soma.frame(R @ m["G"][f], root)


def load_soma(path):
    import numpy as np

    d = np.load(path)
    return {"G": d["global_rot_mats"].astype(np.float64), "P": d["posed_joints"].astype(np.float64),
            "root": d["root_positions"].astype(np.float64), "contacts": d["foot_contacts"].astype(bool)}


def spread_seam(frames):
    """Close a loop whose last frame should equal its first: spread the difference over the
    loop, so frame f moves f/n of the way. Returns n + 1 frames, the last equal to the first."""
    n = len(frames) - 1
    q0, off0 = frames[0]
    qn, offn = frames[n]
    err = {b: q0[b] @ qn[b].inverted() for b in q0}
    doff = off0 - offn
    out = []
    for f, (q, off) in enumerate(frames):
        s = f / n
        out.append(({b: Quaternion().slerp(err[b], s) @ q[b] for b in q}, off + doff * s))
    out[-1] = ({b: v.copy() for b, v in q0.items()}, off0.copy())
    return out, max(math.degrees(e.angle) for e in err.values()), doff.length


def ease_to(frames, pose, n_in, n_out, cyclic=False):
    """Blend the first n_in and last n_out frames toward `pose` (smoothstep), so a one-shot
    starts and ends where the idles do. A loop eased both ways starts and ends at the pose."""
    pq, poff = pose
    n = len(frames) - 1
    out = []
    for f, (q, off) in enumerate(frames):
        w = 0.0
        if n_in and f < n_in:
            w = max(w, 1 - smooth(f / n_in))
        if n_out and f > n - n_out:
            w = max(w, 1 - smooth((n - f) / n_out))
        if w <= 0:
            out.append((q, off))
            continue
        out.append(({b: q[b].slerp(pq.get(b, Quaternion()), w) for b in q}, off.lerp(poff, w)))
    return out


def resample(frames, contacts, m, cyclic):
    """Frames re-timed to m intervals (m + 1 frames), interpolating rotations and offsets."""
    n = len(frames) - 1
    out, cs = [], []
    for u in range(m + 1):
        x = u * n / m
        a = min(int(math.floor(x)), n)
        b = min(a + 1, n)
        s = x - a
        qa, oa = frames[a]
        qb, ob = frames[b]
        out.append(({k: qa[k].slerp(qb[k], s) for k in qa}, oa.lerp(ob, s)))
        cs.append(contacts[min(int(round(x)), n)])
    return out, cs


def fk_pose(sk, local, off, names):
    """World rotations and positions (glTF, file units) of `names` and their ancestors."""
    rot, pos = {}, {}

    def visit(b):
        if b in rot:
            return
        p = sk.parent.get(b)
        q = local.get(b, Quaternion())
        if p is None:
            rot[b], pos[b] = q, sk.rest[b].copy()
            return
        visit(p)
        rot[b] = rot[p] @ q
        pos[b] = pos[p] + rot[p] @ (sk.rest[b] - sk.rest[p])
        if b == HIPS:
            pos[b] = pos[b] + off

    for b in names:
        visit(b)
    return rot, pos


def clean_contacts(c, cyclic, gap=2, short=1):
    """Fill contact gaps of up to `gap` frames and drop contacts shorter than `short`."""
    n = len(c)
    c = list(c)
    for val, run in ((True, gap), (False, short)):
        # A run of `not val` no longer than `run`, bounded by `val` on both sides, flips.
        i = 0
        while i < n:
            if c[i] != val:
                j = i
                while j < n and c[j] != val:
                    j += 1
                bounded = (i > 0 or cyclic) and (j < n or cyclic)
                if j - i <= run and bounded and j - i < n:
                    for k in range(i, j):
                        c[k] = val
                i = j
            else:
                i += 1
    return c


# leg-pole-1: the knee's pole for `plant_feet`'s leg solve. The thigh's forward axis (rest −Z) is a
# stable pole while the leg is nearly straight, but a folded knee (kneeling, squatting, a tuck) brings
# it into line with the hip-to-ankle line, where the side the knee bends to is a sign that flips (a
# 79° thigh snap in stand_up_ground on the VRoid bases). A bent knee has its own answer: where the
# take's knee is. So the pole turns, about the hip-to-ankle line, from the thigh's axis toward the
# take's knee by how bent the take's knee is: not at all while its knee is within LEG_POLE_STRAIGHT of
# the line (of the thigh's length), fully from LEG_POLE_BENT.
LEG_POLE_STRAIGHT = 0.05
LEG_POLE_BENT = 0.25
# A knee opposite the thigh's axis (180°) counts from this far along the way from straight to bent.
LEG_POLE_FAR = 0.6


def knee_turn(sk, pole, reach, pos0, side):
    """How much (0–1, by how bent the take's knee is) and how far (radians, about the hip-to-ankle
    line `reach`) `pole` (the thigh's axis) turns to reach the take's own knee (`pos0`: the
    retargeted pose's positions)."""
    hip0, knee0, ankle0 = (pos0[bone(side, n)] for n in ("UpperLeg", "LowerLeg", "Foot"))
    line = (ankle0 - hip0).normalized()
    knee = (knee0 - hip0) - (knee0 - hip0).dot(line) * line
    x = (knee.length / sk.l1 - LEG_POLE_STRAIGHT) / (LEG_POLE_BENT - LEG_POLE_STRAIGHT)
    if x <= 0.0:
        return 0.0, 0.0
    dh = reach.normalized()
    # The take's knee itself, square to the line being solved (the planted foot's correction can
    # swing a folded leg's short hip-to-ankle line far from the take's own).
    kv = knee0 - hip0
    k = kv - kv.dot(dh) * dh
    across = pole - pole.dot(dh) * dh
    if k.length < 1e-6 or across.length < 1e-6:
        return 0.0, 0.0
    a, k = across.normalized(), k.normalized()
    theta = math.atan2(dh.dot(a.cross(k)), a.dot(k))
    # A knee on the far side of the line from the thigh's axis turns the pole only when clearly bent:
    # a nearly straight leg's knee a hair behind the line (a slight overextension) says nothing.
    far = max(0.0, (abs(theta) - math.pi / 2) / (math.pi / 2)) * LEG_POLE_FAR
    return smooth(min(1.0, max(0.0, (x - far) / (1.0 - far)))), theta


def turned_pole(pole, reach, angle):
    """`pole` turned by `angle` (radians) about the line `reach`, square to it."""
    if angle == 0.0:
        return pole
    dh = reach.normalized()
    across = pole - pole.dot(dh) * dh
    if across.length < 1e-6:
        return pole
    return Quaternion(dh, angle) @ across.normalized()


def knee_pole(sk, pole, reach, pos0, side, stats):
    """The pole for `solve_leg` in one frame (the guards, on poses already solved): `pole` turned
    toward the take's knee (`knee_turn`)."""
    w, theta = knee_turn(sk, pole, reach, pos0, side)
    angle = w * theta
    if angle:
        stats["leg_pole_frames"] = stats.get("leg_pole_frames", 0) + 1
        stats["leg_pole_turn_deg"] = max(stats.get("leg_pole_turn_deg", 0.0), round(abs(math.degrees(angle)), 1))
    return turned_pole(pole, reach, angle)


def smooth_weights(v, r=3, cyclic=True):
    """A cos²-weighted moving average, so a weight that ramps in one or two frames ramps over a
    few. (The weight, not the angle: the angle flips by half a turn exactly where the thigh's axis
    crosses the line, which the turned pole absorbs.)"""
    n = len(v)
    if n == 0:
        return v
    u = v
    at = (lambda i: u[i % n]) if cyclic else (lambda i: u[min(max(i, 0), n - 1)])
    w = [math.cos(k / (r + 1) * math.pi / 2) ** 2 for k in range(-r, r + 1)]
    return [sum(at(i + k) * w[k + r] for k in range(-r, r + 1)) / sum(w) for i in range(n)]


def plant_feet(sk, frames, contacts, belt_v, cyclic, stats, track=None, planted_out=None):
    """Lock planted feet to the floor in the game's world (the clip moves at `belt_v` file units
    per clip, or along `track`: the body's offset at each frame, file units), then solve the legs
    to reach them. A heel contact pins the heel, a toe-only contact
    the ball of the foot; between contacts the correction blends from one plant to the next.
    Returns the frames with new hips heights and leg rotations."""
    n = len(frames) - 1
    count = n if cyclic else n + 1  # a loop's last frame is its first
    legs = {s: [bone(s, x) for x in LEG] for s in "LR"}
    fk = [fk_pose(sk, q, off, legs["L"] + legs["R"]) for q, off in frames[:count]]
    world = (lambda p, k: p + track[k % count]) if track is not None else (lambda p, k: p + belt_v * (k / n))
    shift, planted = {}, {}
    for side in "LR":
        f_ = sk.feet[side]
        ft, toe = bone(side, "Foot"), bone(side, "ToeBase")
        floor = f_["sole"]
        ball_rest = Vector((f_["toe"].x, f_["sole"], f_["toe"].z))

        def pivot(k, kind):
            rot, pos = fk[k % count]
            ref = f_["heel"] if kind == "heel" else ball_rest
            return world(pos[ft] + rot[ft] @ (ref - f_["ankle"]), k)

        heel = clean_contacts([c[CONTACT[side][0]] for c in contacts[:count]], cyclic)
        toes = clean_contacts([c[CONTACT[side][1]] or c[CONTACT[side][2]] for c in contacts[:count]], cyclic)
        down = [h or t for h, t in zip(heel, toes)]
        O = [None] * count
        if any(down):
            # Walk the frames from a lifted one (a loop is unrolled: index k is frame k % count,
            # k / n clips of belt travel along).
            start = next((k for k in range(count) if not down[k]), 0) if cyclic else 0
            lock, kind = None, None
            for k in range(start, start + count):
                f = k % count
                if not down[f]:
                    lock = None
                    continue
                want = "heel" if heel[f] else "ball"
                p = pivot(k, want)
                if lock is None:
                    lock, kind = p.copy(), want
                    lock.y = floor
                elif want != kind:
                    prev = O[(k - 1) % count]
                    lock, kind = p + prev, want
                    lock.y = floor
                O[f] = lock - p
            # Between plants, blend the correction from one to the next.
            idx = [k for k in range(count) if O[k] is not None]
            for k in range(count):
                if O[k] is not None:
                    continue
                if cyclic:
                    a = max((x for x in idx if x < k), default=idx[-1])
                    b = min((x for x in idx if x > k), default=idx[0])
                    span = (b - a) % count
                    s = ((k - a) % count) / span if span else 0.0
                else:
                    a = max((x for x in idx if x < k), default=None)
                    b = min((x for x in idx if x > k), default=None)
                    if a is None or b is None:
                        O[k] = O[b if a is None else a].copy()
                        continue
                    s = (k - a) / (b - a)
                O[k] = O[a].lerp(O[b], smooth(s))
        else:
            O = [Vector() for _ in range(count)]
        shift[side] = O
        planted[side] = [(down[k], "heel" if heel[k] else "ball") for k in range(count)]
        if planted_out is not None:
            planted_out[side] = [("heel" if heel[k] else "ball") if down[k] else None for k in range(count)]
        stats[f"{side}_fix_m"] = max(o.length for o in O) / sk.unit
    # Lower the hips (smoothly) where a leg can't reach its target: the hips move, the target
    # doesn't, so repeat until both legs reach.
    extra = [0.0] * count
    for _ in range(4):
        drops = []
        for k in range(count):
            q, off = frames[k]
            rot, pos = fk_pose(sk, q, off - Vector((0, extra[k], 0)), legs["L"] + legs["R"])
            target_rot, target_pos = fk[k]
            worst = 0.0
            for side in "LR":
                hip = pos[bone(side, "UpperLeg")]
                d = target_pos[bone(side, "Foot")] + shift[side][k] - hip
                over = d.length - (sk.l1 + sk.l2) * 0.998
                if over > 0:
                    worst = max(worst, over * d.length / max(abs(d.y), 1e-3))
            drops.append(worst)
        if not any(drops):
            break
        more = smooth_drop(drops, cyclic=cyclic)
        extra = [e + x for e, x in zip(extra, more)]
    if any(extra):
        stats["hip_lowered"] = max(extra) / sk.unit
    out = []
    # The knee bends the way the retargeted thigh faces (its rest forward, −Z): stable even when
    # the leg is nearly straight and the knee's own offset says nothing; a bent knee turns it
    # toward the take's knee (`knee_turn`), by a weight smoothed over a few frames.
    poses, turn = [], {s: [] for s in "LR"}
    for k in range(count):
        q, off = frames[k]
        off = off - Vector((0, extra[k], 0))
        rot, pos = fk_pose(sk, q, off, legs["L"] + legs["R"])
        poses.append((dict(q), off, rot, pos))
        for side in "LR":
            target = fk[k][1][bone(side, "Foot")] + shift[side][k]
            turn[side].append(knee_turn(sk, rot[bone(side, "UpperLeg")] @ Vector((0, 0, -1)), target - pos[bone(side, "UpperLeg")], fk[k][1], side))
    for side in "LR":
        if any(w for w, _ in turn[side]):
            ws = smooth_weights([w for w, _ in turn[side]], cyclic=cyclic)
            turn[side] = [w * t for w, (_, t) in zip(ws, turn[side])]
            stats["leg_pole_turn_deg"] = max(stats.get("leg_pole_turn_deg", 0.0), round(max(abs(math.degrees(x)) for x in turn[side]), 1))
        else:
            turn[side] = [0.0] * count
    for k in range(count):
        q, off, rot, pos = poses[k]
        hips_rot = rot[HIPS]
        for side in "LR":
            ft = bone(side, "Foot")
            hip = pos[bone(side, "UpperLeg")]
            target = fk[k][1][ft] + shift[side][k]  # where the foot was before the hips came down
            pole = turned_pole(rot[bone(side, "UpperLeg")] @ Vector((0, 0, -1)), target - hip, turn[side][k])
            q.update(solve_leg(sk, side, hip, hips_rot, target, rot[ft], rot[bone(side, "ToeBase")], stats, pole=pole))
        out.append((q, off))
    # What a viewer sees: how far a planted pivot still slides (game world) and how far it is
    # off the floor.
    slide, height = 0.0, 0.0
    after = [fk_pose(sk, q, off, legs["L"] + legs["R"]) for q, off in out]
    for side in "LR":
        f_ = sk.feet[side]
        ft = bone(side, "Foot")
        ball_rest = Vector((f_["toe"].x, f_["sole"], f_["toe"].z))
        for k in range(count):
            down, kind = planted[side][k]
            if not down:
                continue
            ref = f_["heel"] if kind == "heel" else ball_rest
            rot, pos = after[k]
            p = world(pos[ft] + rot[ft] @ (ref - f_["ankle"]), k)
            height = max(height, abs(p.y - f_["sole"]))
            k2 = k + 1
            if k2 < count and planted[side][k2] == (True, kind):
                rot2, pos2 = after[k2]
                p2 = world(pos2[ft] + rot2[ft] @ (ref - f_["ankle"]), k2)
                slide = max(slide, (p2 - p).length * FPS)
    stats["slide_mps"] = slide / sk.unit
    stats["plant_off_floor_m"] = height / sk.unit
    if cyclic:
        out.append(({b: v.copy() for b, v in out[0][0].items()}, out[0][1].copy()))
    return out


# The floor guard leaves a foot alone unless its heel, ball or toe tip is more than this (game m)
# under the floor. The toe tip is taken at the sole's height at rest, a little low for most feet,
# so at 3 mm nearly every Kimodo take (the idle by 4 mm) was lifted; 1 cm is where a toe shows
# through the ground.
FLOOR_EPS = 0.01
# At a planted frame the ankle is lifted at most this (game m), well under foot_markers'
# MARK_FLOOR, so a planted foot keeps its contact; the cap grows by FLOOR_CAP_STEP a frame away
# from planted frames, so the lift never changes faster than that.
FLOOR_PLANT_LIFT = 0.025
FLOOR_CAP_STEP = 0.015
# The guard may raise a clip's largest frame-to-frame jerk by at most this (degrees; marker_check's
# JERK_MARGIN), else it leaves the clip alone.
FLOOR_JERK_MARGIN = 6.0


def floor_guard(sk, frames, cyclic, stats, planted=None):
    """Keep the feet out of the floor: in each frame, how far each foot's heel, ball or toe tip
    (the sole's corners, from the mesh) is under the floor. Where any is, beyond `FLOOR_EPS`, the
    ankle is lifted by a smooth curve never below that depth (`smooth_drop`) and the leg solved to
    it, the foot keeping its rotation. At a frame where the foot is planted (`planted`: per side and
    frame, from `plant_feet`) the lift is at most `FLOOR_PLANT_LIFT`, so the foot keeps its contact
    (lifted further, a planted heel with the toes bent down lost its whole stance); the cap grows by
    `FLOOR_CAP_STEP` a frame away from planted frames, so the lift never changes faster than that.
    (Bending the toes or pitching the foot about its planted pivot instead jerked the toe bones by
    up to 100 degrees a frame.) A clip that never goes under comes back unchanged (the same
    frames): the guard is a no-op there. Records `floor_lift_m` (the most an ankle was lifted, game
    m), `floor_frames` (frames under the floor) and `floor_left_m` (what is still under)."""
    n = len(frames) - 1
    count = n if cyclic else n + 1
    names = [bone(s, x) for s in "LR" for x in LEG]
    eps = FLOOR_EPS * sk.unit

    def points(rot, pos, s):
        f_ = sk.feet[s]
        ft, toe = bone(s, "Foot"), bone(s, "ToeBase")
        ball = Vector((f_["toe"].x, f_["sole"], f_["toe"].z))
        return [pos[ft] + rot[ft] @ (f_["heel"] - f_["ankle"]), pos[ft] + rot[ft] @ (ball - f_["ankle"]), pos[toe] + rot[toe] @ (f_["tip"] - f_["toe"])]

    def under(fk):
        return {s: [sk.feet[s]["sole"] - min(p.y for p in points(rot, pos, s)) for rot, pos in fk] for s in "LR"}

    fk = [fk_pose(sk, q, off, names) for q, off in frames[:count]]
    depth = {s: [d if d > eps else 0.0 for d in v] for s, v in under(fk).items()}
    if not any(any(v) for v in depth.values()):
        return frames
    down = {s: [k is not None for k in list((planted or {}).get(s) or [None] * count)] for s in "LR"}
    out = [(dict(q), off.copy()) for q, off in frames[:count]]
    lifted = 0.0
    for s in "LR":
        if not any(depth[s]):
            continue
        lift = smooth_drop(depth[s], cyclic=cyclic)
        planted_at = [k for k in range(count) if down[s][k]]
        for k in range(count):
            if planted_at:
                gap = min((abs(k - j) if not cyclic else min(abs(k - j), count - abs(k - j))) for j in planted_at)
                lift[k] = min(lift[k], (FLOOR_PLANT_LIFT + gap * FLOOR_CAP_STEP) * sk.unit)
            if lift[k] <= 0.0:
                continue
            rot, pos = fk[k]
            ft = bone(s, "Foot")
            target = pos[ft] + Vector((0.0, lift[k], 0.0))
            pole = knee_pole(sk, rot[bone(s, "UpperLeg")] @ Vector((0, 0, -1)), target - pos[bone(s, "UpperLeg")], pos, s, stats)
            out[k][0].update(solve_leg(sk, s, pos[bone(s, "UpperLeg")], rot[HIPS], target, rot[ft], rot[bone(s, "ToeBase")], stats, pole=pole))
        lifted = max(lifted, max(lift))
    stats["floor_lift_m"] = lifted / sk.unit
    stats["floor_frames"] = sum(1 for k in range(count) if depth["L"][k] or depth["R"][k])
    left = under([fk_pose(sk, q, off, names) for q, off in out])
    stats["floor_left_m"] = max(0.0, max(max(v) for v in left.values())) / sk.unit
    if cyclic:
        out.append(({b: v.copy() for b, v in out[0][0].items()}, out[0][1].copy()))
    return out


# A foot is down while its heel or ball is within this of the floor (game m) and moves slower than
# MARK_STILL (game m/s, in the game's world: belt or path travel included).
MARK_FLOOR = 0.03
MARK_STILL = 0.3


def foot_markers(sk, frames, belt_v, cyclic, track=None):
    """Each foot's contact windows, detected from the baked take: per frame, whether the heel or
    the ball of the foot is on the floor and still in the game's world (the clip on its belt, or
    along its path). Returns {"L": [[a, b], …], "R": …} in normalised clip time (0–1; a loop's
    windows that cross its seam are split at 1), the touchdown frame of each foot's longest
    contact, and the per-frame flags."""
    n = len(frames) - 1
    count = n if cyclic else n + 1
    legs = [bone(s, x) for s in "LR" for x in LEG]
    fk = [fk_pose(sk, q, off, legs) for q, off in frames[:count]]
    world = (lambda p, k: p + track[min(k, count - 1) if not cyclic else k % count]) if track is not None else (lambda p, k: p + belt_v * (k / n))
    out, touch, flags = {}, {}, {}
    for side in "LR":
        f_ = sk.feet[side]
        ft = bone(side, "Foot")
        refs = (f_["heel"], Vector((f_["toe"].x, f_["sole"], f_["toe"].z)))

        def pts(k):
            rot, pos = fk[k % count]
            return [world(pos[ft] + rot[ft] @ (r - f_["ankle"]), k) for r in refs]

        down = []
        for k in range(count):
            a = pts(k)
            # A one-shot's last frame has no next one: measure against the frame before.
            b, dt = (pts(k + 1), 1) if (cyclic or k + 1 < count) else (pts(k - 1), -1)
            on = False
            for p, q in zip(a, b):
                low = (p.y - f_["sole"]) / sk.unit <= MARK_FLOOR
                still = math.hypot(q.x - p.x, q.z - p.z) / sk.unit * FPS <= MARK_STILL
                on = on or (low and still)
            down.append(on)
        down = clean_contacts(down, cyclic, gap=2, short=2)
        flags[side] = down
        runs = []
        if all(down):
            runs = [(0, count)]
        elif any(down):
            start = next(k for k in range(count) if not down[k]) if cyclic else 0
            k = start
            while k < start + count:
                if down[k % count]:
                    j = k
                    while j < start + count and down[j % count]:
                        j += 1
                    runs.append((k, j))
                    k = j
                else:
                    k += 1
        touch[side] = max(runs, key=lambda r: r[1] - r[0])[0] % count if runs else None
        wins = []
        for a, b in runs:
            if cyclic and b > count and a < count:
                wins += [(a / n, 1.0), (0.0, (b - count) / n)]
            elif cyclic and a >= count:
                wins.append(((a - count) / n, (b - count) / n))
            else:
                wins.append((a / n, min(b / n, 1.0)))
        out[side] = sorted([round(a, 4), round(b, 4)] for a, b in wins)
    return out, touch, flags


def rotate_loop(frames, k):
    """A loop (last frame equal to the first) started at frame k instead."""
    n = len(frames) - 1
    body = frames[:n]
    body = body[k:] + body[:k]
    copy = lambda fr: ({b: v.copy() for b, v in fr[0].items()}, fr[1].copy())
    return [copy(f) for f in body] + [copy(body[0])]


def loop_jerk(frames):
    """How much a loop pops at its seam: per bone, the change in angular step (degrees per
    frame) across the seam, against the largest such change anywhere else in the loop (and the
    bone it is on: a foot landing from a hop stops short by nature, a hand snapping does not)."""
    n = len(frames) - 1
    worst_seam, worst_inside, worst_bone = 0.0, 0.0, ""
    for b in frames[0][0]:
        q = [frames[f][0][b] for f in range(n)]
        step = [math.degrees(q[f].rotation_difference(q[(f + 1) % n]).angle) for f in range(n)]
        for f in range(n):
            j = abs(step[f] - step[f - 1])
            if f in (0, n - 1):
                worst_seam = max(worst_seam, j)
            elif j > worst_inside:
                worst_inside, worst_bone = j, b
    return worst_seam, worst_inside, worst_bone


def max_jerk(frames, cyclic):
    """The largest change in angular step (degrees per frame, frame to frame) on any bone, over the
    whole clip (a loop's seam included), and the bone: what `loop_jerk` measures, seam and inside
    together, for one-shots too."""
    n = len(frames) - 1
    count = n if cyclic else n + 1
    worst, at = 0.0, ""
    for b in frames[0][0]:
        q = [frames[f][0][b] for f in range(count)]
        # Folded to 0-180: a quaternion and its negative are the same rotation.
        steps = [math.degrees(min(a, 2 * math.pi - a)) for a in (q[f].rotation_difference(q[(f + 1) % count]).angle for f in range(count if cyclic else count - 1))]
        for f in range(1 if not cyclic else 0, len(steps)):
            j = abs(steps[f] - steps[f - 1])
            if j > worst:
                worst, at = j, b
    return worst, at


def guarded(sk, frames, cyclic, stats, planted=None):
    """`floor_guard`, and where it changed the clip, its largest jerk before and after
    (`floor_jerk_deg`: [before, after, bone after]) for marker_check's standing check. Where the
    guard would raise that by more than `FLOOR_JERK_MARGIN` (a leg solved to a lifted ankle can
    flip its knee), the clip is left as it was: `floor_guard_skipped` records the jerk it would
    have had, and its floor stats are dropped."""
    guard_stats = {}
    out = floor_guard(sk, frames, cyclic, guard_stats, planted)
    if out is frames:
        return frames
    before, _ = max_jerk(frames, cyclic)
    after, at = max_jerk(out, cyclic)
    if after > before + FLOOR_JERK_MARGIN:
        stats["floor_guard_skipped"] = [round(before, 2), round(after, 2), at]
        return frames
    stats.update(guard_stats)
    stats["floor_jerk_deg"] = [round(before, 2), round(after, 2), at]
    return out


# The limb guard (`limb_guard`): wrists at least this far above the floor (game m), ankles at least
# LIMB_ANKLE_FACTOR of the lower of the ankle's standing height and the foot's half width (a foot
# lying on its side), so each body's own feet set it; a limb more than LIMB_EPS short is lifted.
LIMB_WRIST_CLEAR = 0.03
LIMB_ANKLE_FACTOR = 0.9
LIMB_EPS = 0.002
# A foot low on the floor (the ankle under this share of its standing height: sitting, kneeling,
# lying) whose sole still goes under after the ankle's lift turns about the ankle, toes up, by the
# least angle that brings its heel, ball and toe tip to the floor, at most LIMB_PITCH_MAX degrees;
# what is still under after that lifts the ankle again.
LIMB_LOW_ANKLE = 0.6
# The torso (BODY_BONES' mesh points, `Skeleton.measure_body`) stays out of the floor on low frames,
# where the hips are under LIMB_LOW_HIPS of their standing height (lying, sitting, kneeling): the
# hips rise by how far it is under, the legs solved so the feet stay where they were.
BODY_BONES = [bone("C", b) for b in CENTRAL] + [bone(s, "Shoulder") for s in "LR"]
LIMB_LOW_HIPS = 0.6
# Torso points within this of their bone (game m): the body, not a coat's hem or a long sleeve.
BODY_REACH_M = 0.2
# Mesh points kept per torso bone (an even sample, besides the 26 furthest out).
BODY_POINTS = 150
# The torso's lift is smoothed over this many frames either side (a falling body meets the floor
# within a frame or two; the hips rise over about half a second instead).
BODY_SMOOTH = 8
LIMB_PITCH_MAX = 70.0


def solve_arm(sk, side, rot, pos, target, stats):
    """Two-bone IK for an arm, as world-space corrections to its pose: the elbow stays in the plane
    shoulder, elbow, wrist make now and on the side it is on, and the hand keeps its world
    rotation. Returns the local rotations of the upper arm, forearm and hand, and how far short
    of the target the wrist stays (file units, upward: a target out of reach)."""
    up, lo, hd = bone(side, "UpperArm"), bone(side, "LowerArm"), bone(side, "Hand")
    S, E, W = pos[up], pos[lo], pos[hd]
    l1, l2 = (E - S).length, (W - E).length
    v = target - S
    d = v.length
    reach = (l1 + l2) * 0.999
    short = 0.0
    if d > reach:
        stats["overreach"] = max(stats.get("overreach", 0.0), d - reach)
        short = d - reach
        d = reach
    d = max(d, abs(l1 - l2) + 1e-4)
    u = v.normalized()
    normal = (E - S).cross(W - S)
    if normal.length < 1e-6:
        normal = Vector((0.0, 1.0, 0.0)).cross(u)
    side_dir = normal.normalized().cross(u).normalized()
    if side_dir.dot(E - S) < 0:
        side_dir = -side_dir
    a = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    E2 = S + u * a + side_dir * h
    W2 = S + u * d
    q1 = (E - S).rotation_difference(E2 - S)
    q2 = (q1 @ (W - E)).rotation_difference(W2 - E2)
    up_rot = q1 @ rot[up]
    lo_rot = q2 @ q1 @ rot[lo]
    parent = sk.parent.get(up)
    parent_rot = rot[parent] if parent in rot else Quaternion()
    out = {up: (parent_rot.inverted() @ up_rot).normalized(), lo: (up_rot.inverted() @ lo_rot).normalized(), hd: (lo_rot.inverted() @ rot[hd]).normalized()}
    return out, short * (v.y / max(v.length, 1e-9)) if short else 0.0


def limb_guard(sk, frames, cyclic, stats):
    """Keep wrists and ankles off the floor, every clip and every body: a wrist under
    `LIMB_WRIST_CLEAR`, or an ankle under its foot's clearance (see LIMB_ANKLE_FACTOR), is raised
    by a smooth curve never below how far short it is (`smooth_drop`), the arm (`solve_arm`) or the
    leg (`solve_leg`) solved to it with the hand or foot keeping its rotation; where an arm can't
    reach, the hips rise by what is left. A low foot (see LIMB_LOW_ANKLE) whose sole is still under
    then turns toes up about its ankle, and what is left after that lifts it again. On low frames
    (LIMB_LOW_HIPS) a torso under the floor lifts the hips by its depth as well. A clip where no
    wrist, ankle, low sole or low torso goes under comes back unchanged (the same frames). Records
    `limb_wrist_lift_m`, `limb_ankle_lift_m`, `limb_hip_lift_m` (game m), `limb_frames`, `limb_left_m` (the most still short), and for turned feet
    `limb_toe_pitch_deg` and `limb_sole_left_m`; `limb_floor_left_m` is any sole point still
    under, low or not; for a lifted torso `limb_body_lift_m` and `limb_body_left_m`."""
    n = len(frames) - 1
    count = n if cyclic else n + 1
    names = [bone(s, x) for s in "LR" for x in LEG] + [bone(s, x) for s in "LR" for x in ("UpperArm", "LowerArm", "Hand")] + list(sk.body)
    names = [b for b in names if b in sk.parent]
    hands = [bone(s, "Hand") for s in "LR" if bone(s, "Hand") in sk.parent]
    hips_low = sk.floor + LIMB_LOW_HIPS * (sk.rest[HIPS].y - sk.floor)

    def body_short(fk):
        """How far the torso is under the floor on low frames (0 elsewhere)."""
        return [max(0.0, sk.floor - min(pos[b].y + (rot[b] @ o).y for b, os in sk.body.items() for o in os)) if sk.body and pos[HIPS].y < hips_low else 0.0 for rot, pos in fk]
    eps = LIMB_EPS * sk.unit
    wclear = sk.floor + LIMB_WRIST_CLEAR * sk.unit
    aclear = {s: sk.floor + LIMB_ANKLE_FACTOR * min(sk.feet[s]["ankle"].y - sk.feet[s]["sole"], sk.feet[s]["half_width"]) for s in "LR"}

    low = {s: sk.feet[s]["sole"] + LIMB_LOW_ANKLE * (sk.feet[s]["ankle"].y - sk.feet[s]["sole"]) for s in "LR"}

    def short(fk):
        w = {h: [max(0.0, wclear - pos[h].y) for _, pos in fk] for h in hands}
        a = {s: [max(0.0, aclear[s] - pos[bone(s, "Foot")].y) for _, pos in fk] for s in "LR"}
        return w, a

    def sole_pts(rot, pos, s):
        f_ = sk.feet[s]
        ft, toe = bone(s, "Foot"), bone(s, "ToeBase")
        ball = Vector((f_["toe"].x, f_["sole"], f_["toe"].z))
        return [pos[ft] + rot[ft] @ (f_["heel"] - f_["ankle"]), pos[ft] + rot[ft] @ (ball - f_["ankle"]), pos[toe] + rot[toe] @ (f_["tip"] - f_["toe"])]

    def sole_short(fk):
        """How far each low foot's sole is under the floor, per frame (0 where the ankle is not low)."""
        return {s: [max(0.0, sk.feet[s]["sole"] - min(p.y for p in sole_pts(rot, pos, s))) if pos[bone(s, "Foot")].y < low[s] else 0.0 for rot, pos in fk] for s in "LR"}

    fk = [fk_pose(sk, q, off, names) for q, off in frames[:count]]
    w, a = short(fk)
    w = {h: [x if x > eps else 0.0 for x in v] for h, v in w.items()}
    a = {s: [x if x > eps else 0.0 for x in v] for s, v in a.items()}
    t = {s: [x if x > eps else 0.0 for x in v] for s, v in sole_short(fk).items()}
    body = [x if x > eps else 0.0 for x in body_short(fk)]
    if not any(any(v) for d in (w, a, t) for v in d.values()) and not any(body):
        return frames
    W = {h: smooth_drop(v, cyclic=cyclic) if any(v) else [0.0] * count for h, v in w.items()}
    A = {s: smooth_drop(v, cyclic=cyclic) if any(v) else [0.0] * count for s, v in a.items()}
    out = [(dict(q), off.copy()) for q, off in frames[:count]]
    # The arms first; what they can't reach lifts the hips.
    hip = [0.0] * count
    for k in range(count):
        rot, pos = fk[k]
        for side, h in zip("LR", [bone(s, "Hand") for s in "LR"]):
            if h not in W or W[h][k] <= 0.0:
                continue
            q, left = solve_arm(sk, side, rot, pos, pos[h] + Vector((0.0, W[h][k], 0.0)), stats)
            out[k][0].update(q)
            hip[k] = max(hip[k], left)
    # The torso out of the floor: the hips rise by the depth too.
    hip = smooth_drop([x if x > eps else 0.0 for x in hip], cyclic=cyclic) if any(x > eps for x in hip) else [0.0] * count
    # The torso's lift raises the whole body, legs and all: the arms' hips keep the feet where they
    # were (below), the torso's carries them up with it (a body lying or sitting on the floor).
    rise = [0.0] * count
    if any(body):
        rise = smooth_drop(body, r=BODY_SMOOTH, cyclic=cyclic)
        rise = [max(0.0, r - h) for r, h in zip(rise, hip)]
        stats["limb_body_lift_m"] = round(max(r + h for r, h in zip(rise, hip)) / sk.unit, 4)
    # The legs: each foot where it was, raised by its own lift, from hips that may have risen.
    for k in range(count):
        if rise[k] > 0.0:
            out[k] = (out[k][0], out[k][1] + Vector((0.0, rise[k], 0.0)))
        if hip[k] <= 0.0 and A["L"][k] <= 0.0 and A["R"][k] <= 0.0:
            continue
        q, off = out[k]
        if hip[k] > 0.0:
            off = off + Vector((0.0, hip[k], 0.0))
        rot0, pos0 = fk[k]
        pos0 = {b: p + Vector((0.0, rise[k], 0.0)) for b, p in pos0.items()}
        rot, pos = fk_pose(sk, q, off, names)
        for s in "LR":
            if hip[k] <= 0.0 and A[s][k] <= 0.0:
                continue
            ft = bone(s, "Foot")
            pole = knee_pole(sk, rot[bone(s, "UpperLeg")] @ Vector((0, 0, -1)), pos0[ft] + Vector((0.0, A[s][k], 0.0)) - pos[bone(s, "UpperLeg")], pos, s, stats)
            q.update(solve_leg(sk, s, pos[bone(s, "UpperLeg")], rot[HIPS], pos0[ft] + Vector((0.0, A[s][k], 0.0)), rot0[ft], rot0[bone(s, "ToeBase")], stats, pole=pole))
        out[k] = (q, off)
    # Low feet whose soles are still under: toes up about the ankle, then what is left lifts them.
    fk2 = [fk_pose(sk, q, off, names) for q, off in out]
    need = sole_short(fk2)
    pitch = {}
    for s in "LR":
        ft, shin = bone(s, "Foot"), bone(s, "LowerLeg")
        ang = [0.0] * count
        for k in range(count):
            if need[s][k] <= eps:
                continue
            rot, pos = fk2[k]
            fwd = rot[ft] @ (sk.feet[s]["toe"] - sk.feet[s]["ankle"])
            axis = Vector((0.0, 1.0, 0.0)).cross(fwd)
            if axis.length < 1e-6:
                continue
            axis.normalize()
            # The sign that raises the toe tip.
            if (Quaternion(axis, math.radians(10)) @ fwd).y < fwd.y:
                axis = -axis
            best = (-math.inf, 0.0)
            for deg in range(1, int(LIMB_PITCH_MAX) + 1):
                r = Quaternion(axis, math.radians(deg))
                rr = {ft: r @ rot[ft], bone(s, "ToeBase"): r @ rot[bone(s, "ToeBase")]}
                pp = {ft: pos[ft], bone(s, "ToeBase"): pos[ft] + r @ (pos[bone(s, "ToeBase")] - pos[ft])}
                lowest = min(p.y for p in sole_pts(rr, pp, s))
                if lowest > best[0] + 1e-9:
                    best = (lowest, deg)
                if lowest >= sk.feet[s]["sole"]:
                    break
            ang[k] = float(best[1])
        if any(ang):
            pitch[s] = smooth_drop(ang, cyclic=cyclic)
    for k in range(count):
        q, off = out[k]
        rot, pos = fk2[k]
        for s, ang in pitch.items():
            if ang[k] <= 0.0:
                continue
            ft, shin = bone(s, "Foot"), bone(s, "LowerLeg")
            fwd = rot[ft] @ (sk.feet[s]["toe"] - sk.feet[s]["ankle"])
            axis = Vector((0.0, 1.0, 0.0)).cross(fwd).normalized()
            if (Quaternion(axis, math.radians(10)) @ fwd).y < fwd.y:
                axis = -axis
            q[ft] = (rot[shin].inverted() @ Quaternion(axis, math.radians(ang[k])) @ rot[ft]).normalized()
    if pitch:
        stats["limb_toe_pitch_deg"] = round(max(max(v) for v in pitch.values()), 1)
        fk3 = [fk_pose(sk, q, off, names) for q, off in out]
        rest = sole_short(fk3)
        for s in "LR":
            if not any(x > eps for x in rest[s]):
                continue
            lift = smooth_drop([x if x > eps else 0.0 for x in rest[s]], cyclic=cyclic)
            for k in range(count):
                if lift[k] <= 0.0:
                    continue
                q, off = out[k]
                rot, pos = fk3[k]
                ft = bone(s, "Foot")
                pole = knee_pole(sk, rot[bone(s, "UpperLeg")] @ Vector((0, 0, -1)), pos[ft] + Vector((0.0, lift[k], 0.0)) - pos[bone(s, "UpperLeg")], pos, s, stats)
                q.update(solve_leg(sk, s, pos[bone(s, "UpperLeg")], rot[HIPS], pos[ft] + Vector((0.0, lift[k], 0.0)), rot[ft], rot[bone(s, "ToeBase")], stats, pole=pole))
                A[s][k] += lift[k]
        stats["limb_sole_left_m"] = round(max(max(v) for v in sole_short([fk_pose(sk, q, off, names) for q, off in out]).values()) / sk.unit, 4)
    stats["limb_wrist_lift_m"] = max((max(v) for v in W.values()), default=0.0) / sk.unit
    stats["limb_ankle_lift_m"] = max(max(v) for v in A.values()) / sk.unit
    if any(hip):
        stats["limb_hip_lift_m"] = max(hip) / sk.unit
    stats["limb_frames"] = sum(1 for k in range(count) if any(v[k] for d in (w, a, t) for v in d.values()) or body[k])
    fk_out = [fk_pose(sk, q, off, names) for q, off in out]
    w2, a2 = short(fk_out)
    # Every sole point still under the floor, low foot or not (the floor guard's own measure).
    stats["limb_floor_left_m"] = round(max(0.0, max(sk.feet[s]["sole"] - min(p.y for p in sole_pts(rot, pos, s)) for rot, pos in fk_out for s in "LR")) / sk.unit, 4)
    stats["limb_left_m"] = max([max(v) for v in w2.values()] + [max(v) for v in a2.values()]) / sk.unit
    if any(body):
        stats["limb_body_left_m"] = round(max(body_short(fk_out)) / sk.unit, 4)
    if cyclic:
        out.append(({b: v.copy() for b, v in out[0][0].items()}, out[0][1].copy()))
    return out


def limbs_guarded(sk, frames, cyclic, stats):
    """`limb_guard` with the floor guard's protection: where it would raise the clip's largest
    frame-to-frame jerk by more than FLOOR_JERK_MARGIN, the clip is left as it was
    (`limb_guard_skipped`); else its sidecar gets `limb_jerk_deg` [before, after, bone]."""
    limb_stats = {}
    out = limb_guard(sk, frames, cyclic, limb_stats)
    if out is frames:
        return frames
    before, _ = max_jerk(frames, cyclic)
    after, at = max_jerk(out, cyclic)
    if after > before + FLOOR_JERK_MARGIN:
        stats["limb_guard_skipped"] = [round(before, 2), round(after, 2), at]
        return frames
    stats.update(limb_stats)
    stats["limb_jerk_deg"] = [round(before, 2), round(after, 2), at]
    return out


def overlay_clip(sk, spec, neutral):
    """A hand-keyed gesture on the neutral pose: central bones (Neck, Head, …) turn by eased key
    curves over the clip, from rest and back to it (degrees: pitch + nods forward, yaw + turns to
    the character's left, roll + tilts to its left), feet planted."""
    o = spec["overlay"]
    n = round(o["seconds"] * FPS)
    curves = {}
    for b, chans in o.items():
        if b == "seconds":
            continue
        for ch, pts in chans.items():
            curves[(b, ch)] = monotone([p[0] for p in pts], [p[1] for p in pts], cyclic=False)
    pq, poff = neutral
    frames = []
    for f in range(n + 1):
        t = f / n
        q = {b: v.copy() for b, v in pq.items()}
        for b in {b for b, _ in curves}:
            c = lambda ch, b=b: curves[(b, ch)](t) if (b, ch) in curves else 0.0
            q[bone("C", b)] = q[bone("C", b)] @ central_q(c)
        frames.append((q, poff.copy()))
    contacts = [(True,) * 6] * (n + 1)
    stats = {}
    planted = {}
    frames = plant_feet(sk, frames, contacts, Vector(), False, stats, planted_out=planted)
    frames = guarded(sk, frames, False, stats, planted)
    frames = limbs_guarded(sk, frames, False, stats)
    info = {"source": "hand-keyed overlay on the neutral pose", "kind": "once", "loop": False, "frames": n,
            "seconds": round(n / FPS, 3), "speed": 0.0, "contacts": foot_markers(sk, frames, Vector(), False)[0]}
    return frames, info


def unturn(frames, heading):
    """A turn on the spot with its turn taken out: each frame's hips (and everything under them)
    turned back about the vertical by how far the hips' heading has turned since the first frame
    (radians, SOMA's sense: + turns to the body's left), so the clip ends facing ahead in the
    neutral pose and the game turns the body itself along the curve. Feet are planted before."""
    out = []
    for f, (q, off) in enumerate(frames):
        back = Quaternion((0.0, 1.0, 0.0), -float(heading[min(f, len(heading) - 1)] - heading[0]))
        q = dict(q)
        q[HIPS] = back @ q[HIPS]
        out.append((q, back @ off))
    return out


def joins_a_gait(spec):
    """A one-shot that travels its own path into or out of a gait, or hops (the game draws the
    body along its path, `path_m`): a start, a stop, a jump. The dodge's dash is the authority's."""
    ends = str(spec.get("start", "")) + str(spec.get("end", ""))
    return spec.get("travel") == "path" and ("hop" in spec or "travel_deg" in spec or "#" in ends)


def library_clip(sk, soma, spec, path, neutral, speeds, max_scale):
    """A Kimodo NPZ made game-ready by its library entry. Returns frames and a summary."""
    m = load_soma(path)
    T = m["P"].shape[0]
    kind = spec["kind"]
    loco = spec.get("locomotion")
    info = {"source": f"kimodo {os.path.basename(path)}", "kind": kind}
    if kind == "loop" and spec.get("cycle") == "whole":
        # Keyframed at both ends to the same pose: the whole take is the loop.
        i, j = 0, T - 1
        info.update(cut=[i, j])
    elif kind == "loop":
        lo, hi = (round(x * FPS) for x in spec.get("cycle", (1.0, 3.0)))
        skip = round(spec.get("skip", 0.0) * FPS)
        i, j, err = find_cycle(soma, m, lo, min(hi, T - 2 - skip), skip, loco)
        info.update(cut=[i, j], match=round(err, 4))
    else:
        a, b = spec.get("trim", (0.0, (T - 1) / FPS))
        i, j = round(a * FPS), min(round(b * FPS), T - 1)
        info.update(cut=[i, j])
    w = soma_window(soma, m, spec, (i, j))
    n = w["n"]
    frames = [soma.frame(w["G"][f], w["root"][f]) for f in range(n + 1)]
    # Kimodo's fingers hold one relaxed pose; a clip that holds something (a sword, a bow) closes
    # that hand: "grip": {"R": degrees of curl, "L": …}.
    for side, curl in spec.get("grip", {}).items():
        fixed = {}
        for fn in FINGER_NAMES:
            fixed.update(finger_curl(sk, side, fn, curl * (0.5 if fn == "Thumb" else 1.0)))
        for q, _ in frames:
            q.update(fixed)
    contacts = [tuple(c) for c in w["contacts"]]
    moving = bool(loco) or spec.get("travel") in ("belt", "path")
    belt_soma = float(math.hypot(w["belt"][0], w["belt"][2])) if moving else 0.0
    natural = belt_soma * soma.k_game / (n / FPS)
    if kind == "loop":
        frames, rot_err, off_err = spread_seam(frames)
        info.update(seam_deg=round(rot_err, 2), seam_m=round(off_err / sk.unit, 4))
    # Ease into and out of the neutral pose only at ends keyframed to it (a death or a sit-down
    # ends elsewhere; a stand-up starts elsewhere).
    default = (0.25 if spec.get("start") == "neutral" else 0.0, 0.3 if spec.get("end") == "neutral" else 0.0)
    ein, eout = (round(x * FPS) for x in spec.get("ease", default if kind == "once" else (0.0, 0.0)))
    if neutral is not None and (ein or eout):
        frames = ease_to(frames, neutral, ein, eout)
    scale = 1.0
    target = speeds.get(spec.get("speed", loco)) if loco else None
    if target and natural > 0:
        scale = min(max(target / natural, 1 / max_scale), max_scale)
        m2 = max(2, round(n / scale))
        frames, contacts = resample(frames, contacts, m2, kind == "loop")
        scale = n / m2
        n = m2
    # Standing loops had their drift removed; their feet stay put, so they plant in place.
    belt_v = TURN @ Vector((float(w["belt"][0]), 0.0, float(w["belt"][2]))) * soma.k if moving else Vector()
    stats = {}
    # A path's travel (the dodge's dash) is the body's own: planted feet stay put along it.
    track = [TURN @ Vector((float(t[0]), 0.0, float(t[2]))) * soma.k for t in w["track"]] if w["track"] is not None and n == w["n"] else None
    planted = {}
    if spec.get("plant", True):
        frames = plant_feet(sk, frames, contacts, belt_v, kind == "loop", stats, track, planted_out=planted)
    frames = guarded(sk, frames, kind == "loop", stats, planted)
    frames = limbs_guarded(sk, frames, kind == "loop", stats)
    # Foot-down markers. A gait's loop starts where its right foot comes down (the start of the
    # right foot's longest contact), so phase 0 is the same event in every gait and the game can
    # play them all at one shared phase.
    marks, touch, _ = foot_markers(sk, frames, belt_v, kind == "loop", track)
    if kind == "loop" and loco and touch["R"]:
        frames = rotate_loop(frames, touch["R"])
        info["phase_shift"] = round(touch["R"] / n, 4)
        marks, touch, _ = foot_markers(sk, frames, belt_v, True, track)
    info["contacts"] = marks
    if "turn_deg" in spec:
        # Measured on the take, in the game's sense (-90 is a quarter turn left): the curve is
        # what the game turns the body by, the clip itself no longer turns.
        h = w["heading"]
        info["turn_deg"] = round(-math.degrees(float(h[-1] - h[0])), 1)
        info["turn_planned_deg"] = spec["turn_deg"]
        info["turn_curve"] = [[round(f / n, 4), round(-math.degrees(float(h[f] - h[0])), 2)] for f in range(n + 1)]
        frames = unturn(frames, h)
    if kind == "loop" and loco:
        info["sync"] = "R"
    if kind == "loop":
        seam, inside, bone_ = loop_jerk(frames)
        info.update(seam_jerk_deg=round(seam, 2), max_jerk_inside_deg=round(inside, 2), max_jerk_bone=bone_)
    speed = belt_soma * soma.k_game / (n / FPS)
    info.update(frames=n, seconds=round(n / FPS, 3), natural_speed=round(natural, 3), speed=round(speed, 3),
                time_scale=round(scale, 3), loop=kind == "loop")
    if target and abs(speed - target) > 0.05 * target:
        info["speed_short_of_target"] = target
    if kind == "once" and belt_soma > 0:
        info["travel_m"] = round(belt_soma * soma.k_game, 3)
    if spec.get("travel") == "path":
        # How far the hips stray from the body's own track (game metres): the slide left.
        info["path_residual_m"] = round(w["residual"] * soma.k_game, 3)
    if joins_a_gait(spec) and w["track"] is not None:
        # The body's own track (game metres per frame: to its left, ahead), which the game draws
        # it along while the clip plays.
        info["path_m"] = [[round(float(t[0]) * soma.k_game, 4), round(float(t[2]) * soma.k_game, 4)] for t in w["track"]]
    if "hop" in spec:
        # The path's flight window, in clip seconds (the rules' jump).
        info["hop"] = [round(spec["hop"][0] - i / FPS, 3), round(spec["hop"][1] - i / FPS, 3)]
    if loco and kind == "loop":
        # The gait family (walk, run, sneak): the game picks its forward gaits by it and their
        # natural speeds, not by name.
        info["locomotion"] = loco
    if "travel_deg" in spec:
        # Where the take travels from its facing (the game's sense), and where its hips faced on
        # average once its travel was turned there (degrees, the same sense).
        info["travel_deg"] = spec["travel_deg"]
        info["facing_deg"] = round(-math.degrees(sum(map(float, w["heading"])) / len(w["heading"])), 1)
        if kind == "loop":
            info["cycle_m"] = round(speed * n / FPS, 3)
    if kind == "once" and not moving:
        d = w["root"][-1] - w["root"][0]
        info["end_offset_m"] = round(float(math.hypot(d[0], d[2])) * soma.k_game, 3)
        info["end_offset_soma_xz"] = [round(float(w["root"][-1][0]), 3), round(float(w["root"][-1][2]), 3)]
    info.update({k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items() if not isinstance(v, tuple)})
    return frames, info


def check_pose_basis(arm):
    """Pose quaternions equal glTF local rotations when every rest frame equals C."""
    for b in arm.data.bones:
        if b.name.startswith("J_Bip"):
            rb = b.matrix_local.to_quaternion()
            assert rb.rotation_difference(CQ).angle < 1e-4, b.name


def export(path):
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        export_yup=True,
        export_animations=True,
        export_animation_mode="NLA_TRACKS",
        export_force_sampling=True,
        export_frame_step=1,
        export_optimize_animation_size=False,
        export_optimize_animation_keep_anim_armature=True,
        export_def_bones=False,
        export_leaf_bone=False,
        export_reset_pose_bones=True,
        export_rest_position_armature=True,
        export_morph_animation=False,
        export_materials="EXPORT",
        export_image_format="AUTO",
    )


# ---------------------------------------------------------------------------------------------
# GLB graft: copy the exported animations into the original file by node name.

COMPONENTS = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}


def read_glb(path):
    b = open(path, "rb").read()
    assert b[:4] == b"glTF", path
    jl = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20 : 20 + jl])
    rest = b[20 + jl :]
    binary = bytearray()
    if len(rest) >= 8:
        bl, kind = struct.unpack("<II", rest[:8])
        assert kind == 0x004E4942
        binary = bytearray(rest[8 : 8 + bl])
    return j, binary


def write_glb(path, j, binary):
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(binary), 0x004E4942) + binary)


def accessor_floats(j, binary, i):
    a = j["accessors"][i]
    assert a["componentType"] == 5126, "expected float accessors"
    bv = j["bufferViews"][a["bufferView"]]
    nc = COMPONENTS[a["type"]]
    stride = bv.get("byteStride", nc * 4)
    assert stride == nc * 4, "interleaved animation data"
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    return bytes(binary[off : off + a["count"] * nc * 4]), a


def graft(src, exported, out, animated, translated, expected):
    oj, obin = read_glb(src)
    ej, ebin = read_glb(exported)
    onodes = {n.get("name"): i for i, n in enumerate(oj["nodes"])}
    # The exported rest pose must match the original exactly for the clips to be valid there.
    for n in ej["nodes"]:
        nm = n.get("name")
        if nm in animated:
            o = oj["nodes"][onodes[nm]]
            for key, default in (("translation", [0, 0, 0]), ("rotation", [0, 0, 0, 1])):
                a, b = o.get(key, default), n.get(key, default)
                if max(abs(x - y) for x, y in zip(a, b)) > 1e-5:
                    raise SystemExit(f"rest {key} of {nm} differs after Blender: {a} vs {b}")
    names_out = []
    anims = [a for a in oj.get("animations", []) if a.get("name") not in {x.get("name") for x in ej.get("animations", [])}]
    copied = {}

    def copy(i):
        if i in copied:
            return copied[i]
        data, a = accessor_floats(ej, ebin, i)
        obin.extend(b"\0" * (-len(obin) % 4))
        oj.setdefault("bufferViews", []).append({"buffer": 0, "byteOffset": len(obin), "byteLength": len(data)})
        obin.extend(data)
        na = {k: v for k, v in a.items() if k not in ("bufferView", "byteOffset", "name")}
        na["bufferView"] = len(oj["bufferViews"]) - 1
        oj["accessors"].append(na)
        copied[i] = len(oj["accessors"]) - 1
        return copied[i]

    worst = 0.0
    for anim in ej.get("animations", []):
        name = anim.get("name")
        samplers, channels = [], []
        have = set()
        for ch in anim["channels"]:
            node = ej["nodes"][ch["target"]["node"]].get("name")
            path = ch["target"]["path"]
            if node not in animated or not (path == "rotation" or (path == "translation" and node in translated)):
                continue
            s = anim["samplers"][ch["sampler"]]
            if path == "rotation" and name in expected and node in expected[name]:
                data, a = accessor_floats(ej, ebin, s["output"])
                got = struct.unpack(f"<{a['count'] * 4}f", data)
                for f, q in enumerate(expected[name][node][: a["count"]]):
                    g = Quaternion((got[4 * f + 3], got[4 * f], got[4 * f + 1], got[4 * f + 2]))
                    ang = q.rotation_difference(g).angle
                    worst = max(worst, min(ang, 2 * math.pi - ang))  # q and −q are one rotation
            samplers.append({"input": copy(s["input"]), "output": copy(s["output"]), "interpolation": s.get("interpolation", "LINEAR")})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": onodes[node], "path": path}})
            have.add((node, path))
        missing = [(n, "rotation") for n in animated if (n, "rotation") not in have] + [(n, "translation") for n in translated if (n, "translation") not in have]
        if missing:
            raise SystemExit(f"clip {name} lacks channels {missing[:5]}")
        anims.append({"name": name, "samplers": samplers, "channels": channels})
        names_out.append(name)
    oj["animations"] = anims
    oj["buffers"][0]["byteLength"] = len(obin) + (-len(obin) % 4)
    write_glb(out, oj, obin)
    print(f"GRAFT {out}: clips {names_out}, max rotation error vs evaluated {math.degrees(worst):.4f}°")
    return worst


# ---------------------------------------------------------------------------------------------


REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def library_entries(lib, only, seeds):
    """(clip name, entry, seed or None) for each clip the library run writes."""
    for e in lib["clips"]:
        if e.get("kind") == "pose" or (only and e["name"] not in only):
            continue
        if "keyed" in e or "overlay" in e:
            yield e["name"], e, None
        elif seeds == "all":
            for s in e["seeds"]:
                yield f"{e['name']}_s{s}", e, s
        else:
            yield e["name"], e, e["pick"]


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="src", required=True, help="VRoid GLB (VRM 0.x)")
    ap.add_argument("--out", required=True, help="output GLB")
    ap.add_argument("--clips", default=None, help=f"comma-separated subset of {ORDER} (default: all of them, or none with --library)")
    ap.add_argument("--speed", type=float, default=1.4, help="walk speed, game m/s")
    ap.add_argument("--run-speed", type=float, default=3.6, help="run speed, game m/s")
    ap.add_argument("--sneak-speed", type=float, default=None, help="sneak speed, game m/s (default: as generated)")
    ap.add_argument("--target", action="append", default=[], metavar="KEY=M/S", help="target speed for library clips whose speed key is KEY (e.g. walk_brisk=2.6); unset keys keep the generated speed")
    ap.add_argument("--max-scale", type=float, default=1.4, help="most a locomotion clip is sped up or slowed down to reach its speed")
    ap.add_argument("--height", type=float, default=1.75, help="height the game fits the character to, m")
    ap.add_argument("--kimodo", action="append", default=[], metavar="NAME=NPZ", help="add a clip retargeted from a Kimodo SOMA-RP NPZ as generated (repeatable)")
    ap.add_argument("--library", help="clip library (clips.json): write its clips, made game-ready")
    # The library's home, and only where there is none the older copy under `outputs/` (gen_person.sh has the same rule).
    home = os.path.join(REPO, ".local", "kimodo", "library")
    ap.add_argument("--kimodo-dir", default=home if os.path.isdir(home) else os.path.join(REPO, ".local", "kimodo", "outputs", "library"), help="the library's generated NPZs (default: .local/kimodo/library, else .local/kimodo/outputs/library)")
    ap.add_argument("--only", default="", help="comma-separated library entries")
    ap.add_argument("--seeds", choices=["pick", "all"], default="pick", help="all: write every seed as <name>_s<seed>, for review")
    ap.add_argument("--summary", help="write each clip's length, speed and source as JSON")
    ap.add_argument("--blend", help="also save the .blend with the NLA tracks")
    ap.add_argument("--keep-export", help="also keep Blender's own GLB export at this path")
    a = ap.parse_args(argv)
    clips = [c.strip() for c in (a.clips if a.clips is not None else ("" if a.library else ",".join(ORDER))).split(",") if c.strip()]
    unknown = [c for c in clips if c not in CLIPS]
    if unknown:
        raise SystemExit(f"unknown clips {unknown}")
    arm, meshes = import_model(os.path.abspath(a.src))
    bpy.context.scene.render.fps = FPS
    sk = Skeleton(arm, meshes, a.height)
    print(f"SKELETON height {sk.height:.3f} units ({sk.unit:.3f}/m), legs {sk.l1:.3f}+{sk.l2:.3f}, "
          f"foot heel {sk.feet['L']['heel'].z - sk.feet['L']['ankle'].z:+.3f} tip {sk.feet['L']['tip'].z - sk.feet['L']['ankle'].z:+.3f} sole {sk.feet['L']['sole']:+.4f}")
    check_pose_basis(arm)
    speeds = {"walk": a.speed, "run": a.run_speed, "sneak": a.sneak_speed}
    speeds.update({k: float(v) for k, v in (t.split("=", 1) for t in a.target)})
    expected, summary = {}, {}
    animated, translated = set(), {bone("C", "Hips")}

    def add(name, values):
        expected[name] = {k: v for k, v in values.items() if not k.startswith("__")}
        animated.update(expected[name])

    def keyed(name, c):
        add(name, key_clip(arm, sk, name, CLIPS[c], speeds))
        spec = CLIPS[c]
        gait = spec["feet"].get("gait")
        summary[name] = {"source": f"hand-keyed {c}", "kind": "loop", "loop": True, "seconds": round(round(spec["seconds"] * FPS) / FPS, 3),
                         "speed": speeds[gait["speed"]] if gait else 0.0}

    for c in clips:
        keyed(c, c)
    for spec in a.kimodo:
        name, path = spec.split("=", 1)
        add(name, key_frames(arm, name, retarget_kimodo(sk, os.path.abspath(path)), {}))
    if a.library:
        lib = json.load(open(a.library))
        soma = Soma(sk, SOMA_JSON)
        neutral = neutral_frame(sk, soma, lib["neutral"], a.kimodo_dir) if lib.get("neutral") else None
        only = {x for x in a.only.split(",") if x}
        for name, e, seed in library_entries(lib, only, a.seeds):
            if "keyed" in e:
                keyed(name, e["keyed"])
            elif "overlay" in e:
                frames, info = overlay_clip(sk, e, neutral)
                add(name, key_frames(arm, name, frames, {}))
                summary[name] = info
            else:
                path = os.path.join(a.kimodo_dir, f"{e['name']}_s{seed}.npz")
                frames, info = library_clip(sk, soma, e, path, neutral, speeds, a.max_scale)
                stats = {k: v for k, v in info.items() if k not in ("source", "kind", "loop", "contacts")}
                add(name, key_frames(arm, name, frames, stats))
                summary[name] = info
            # Upper-body clips play over the gait while the body moves (the game's anim.rs).
            if "layer" in e:
                summary[name]["layer"] = e["layer"]
            # A one-shot that starts or ends in a frame of a gait baked here (a walk's start or
            # stop): that frame's phase in the gait's loop, where the game hands over.
            for key in ("start", "end"):
                ref = str(e.get(key, ""))
                if "#" not in ref or "@" not in ref or name not in summary:
                    continue
                g, rest = ref.split("#", 1)
                seed, frame = rest.split("@", 1)
                ge = next((x for x in lib["clips"] if x["name"] == g), None)
                sg = summary.get(g)
                if ge is None or sg is None or not sg.get("sync") or a.seeds != "pick" or ge.get("pick") != int(seed):
                    continue
                i, j = sg["cut"]
                phase = ((int(frame) - i) / (j - i) - sg.get("phase_shift", 0.0)) % 1.0
                summary[name][f"{key}_gait"] = {"clip": g, "phase": round(phase, 4)}
    if a.blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.blend))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    # Blender's own export is only read here: without --keep-export it goes to a folder of its
    # own, removed when it has been read (or the bake failed). They once stayed, a few MB a bake,
    # and on a machine whose /tmp is memory that was 8.6 GB of RAM.
    own = None if a.keep_export else tempfile.mkdtemp(prefix="animate-")
    tmp = a.keep_export or os.path.join(own, "blender.glb")
    try:
        export(os.path.abspath(tmp))
        worst = graft(os.path.abspath(a.src), os.path.abspath(tmp), os.path.abspath(a.out), animated, translated, expected)
    finally:
        if own:
            shutil.rmtree(own, ignore_errors=True)
    if math.degrees(worst) > 0.05:
        raise SystemExit(f"exported rotations differ from the evaluated pose by {math.degrees(worst):.3f}°")
    if a.summary:
        with open(a.summary, "w") as f:
            json.dump(summary, f, indent=1)
        print(f"SUMMARY {a.summary}: {len(summary)} clips")


if __name__ == "__main__":
    main()
