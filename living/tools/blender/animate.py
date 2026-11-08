"""Animation clips for VRoid (VRM 0.x) humanoids, authored headless in Blender.

Run headless:
    blender -b -P living/tools/blender/animate.py -- \
        --in living/game/assets/lookdev/vroid-Vivi.glb \
        --out living/game/assets/lookdev/anim/vroid-Vivi.glb [--clips idle,walk,talk] \
        [--speed 1.4] [--run-speed 3.6] [--height 1.75] [--blend out.blend]

Writes the same character with named, looping clips at 30 fps: idle, walk, talk, run, attack.

`--kimodo NAME=motion.npz` (repeatable) adds a clip retargeted from an NVIDIA Kimodo SOMA-RP
output (see `retarget_kimodo`); `--clips ""` writes only those.

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
        L = self.rest
        s = "L"
        self.l1 = (L[bone(s, "LowerLeg")] - L[bone(s, "UpperLeg")]).length
        self.l2 = (L[bone(s, "Foot")] - L[bone(s, "LowerLeg")]).length

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


def solve_leg(sk, side, hip_pos, hips_rot, ankle, foot_rot, toe_rot, stats):
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
    # The knee points where the foot points (horizontally).
    pole = foot_rot @ Vector((0, 0, -1))
    pole.y = 0
    pole.normalize()
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
            curl = curve(spec.get("curl", 0.0))(tt) * FINGER_GAIN[fn]
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


def smooth_drop(drops, r=3):
    """Cyclic dilate-then-blur: a smooth curve that is never below the drops it covers."""
    n = len(drops)
    dil = [max(drops[(i + k) % n] for k in range(-r, r + 1)) for i in range(n)]
    w = [math.cos(k / (r + 1) * math.pi / 2) ** 2 for k in range(-r, r + 1)]
    return [sum(dil[(i + k) % n] * w[k + r] for k in range(-r, r + 1)) / sum(w) for i in range(n)]


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


def retarget_kimodo(sk, path):
    """Frames from a Kimodo SOMA-RP NPZ. Both skeletons rest in a T-pose with identity rest
    rotations (arms along ±X, Y up); SOMA faces +Z and VRoid −Z, so each joint's global rotation
    is turned half round Y, and each J_Bip bone's local rotation is its mapped joint's global
    rotation relative to its nearest mapped ancestor's (SOMA joints J_Bip lacks, like Neck2,
    fold into the next bone). The hips keep their sway and bob but not their travel (the game
    moves the character), scaled by the ratio of hips heights."""
    import numpy as np

    sk_json = json.load(open(os.path.join(os.path.dirname(path), "somaskel77_skeleton.json")))
    index = {j["name"]: j["index"] for j in sk_json["joints"]}
    d = np.load(path)
    G, root, smooth = d["global_rot_mats"], d["root_positions"], d["smooth_root_pos"]
    turn = Matrix.Diagonal((-1.0, 1.0, -1.0))
    pairs = {bone("C", b): s for b, s in SOMA_CENTRAL.items()}
    for side, prefix in (("L", "Left"), ("R", "Right")):
        pairs.update({bone(side, b): prefix + s for b, s in SOMA_LIMB.items()})
    pairs = {b: index[s] for b, s in pairs.items() if b in sk.parent and s in index}

    def mapped_parent(b):
        p = sk.parent.get(b)
        while p is not None and p not in pairs:
            p = sk.parent.get(p)
        return p

    parents = {b: mapped_parent(b) for b in pairs}
    hips_h = sk.rest[bone("C", "Hips")].y - sk.floor
    k = hips_h / SOMA_HIPS_REST
    frames = []
    for t in range(G.shape[0]):
        glob = {b: turn @ Matrix(G[t, j].tolist()) @ turn for b, j in pairs.items()}
        out = {}
        for b in pairs:
            p = parents[b]
            local = glob[b] if p is None else glob[p].transposed() @ glob[b]
            out[b] = local.to_quaternion().normalized()
        dx, dz = float(root[t, 0] - smooth[t, 0]), float(root[t, 2] - smooth[t, 2])
        off = Vector((-dx * k, (float(root[t, 1]) - SOMA_HIPS_REST) * k, -dz * k))
        frames.append((out, off))
    print(f"KIMODO {os.path.basename(path)}: {len(frames)} frames, {len(pairs)} bones mapped")
    return frames


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
                    worst = max(worst, q.rotation_difference(g).angle)
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


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="src", required=True, help="VRoid GLB (VRM 0.x)")
    ap.add_argument("--out", required=True, help="output GLB")
    ap.add_argument("--clips", default=",".join(ORDER), help=f"comma-separated subset of {ORDER}")
    ap.add_argument("--speed", type=float, default=1.4, help="walk speed, game m/s")
    ap.add_argument("--run-speed", type=float, default=3.6, help="run speed, game m/s")
    ap.add_argument("--height", type=float, default=1.75, help="height the game fits the character to, m")
    ap.add_argument("--kimodo", action="append", default=[], metavar="NAME=NPZ", help="add a clip retargeted from a Kimodo SOMA-RP NPZ (repeatable)")
    ap.add_argument("--blend", help="also save the .blend with the NLA tracks")
    ap.add_argument("--keep-export", help="also keep Blender's own GLB export at this path")
    a = ap.parse_args(argv)
    clips = [c.strip() for c in a.clips.split(",") if c.strip()]
    unknown = [c for c in clips if c not in CLIPS]
    if unknown:
        raise SystemExit(f"unknown clips {unknown}")
    arm, meshes = import_model(os.path.abspath(a.src))
    bpy.context.scene.render.fps = FPS
    sk = Skeleton(arm, meshes, a.height)
    print(f"SKELETON height {sk.height:.3f} units ({sk.unit:.3f}/m), legs {sk.l1:.3f}+{sk.l2:.3f}, "
          f"foot heel {sk.feet['L']['heel'].z - sk.feet['L']['ankle'].z:+.3f} tip {sk.feet['L']['tip'].z - sk.feet['L']['ankle'].z:+.3f} sole {sk.feet['L']['sole']:+.4f}")
    check_pose_basis(arm)
    speeds = {"walk": a.speed, "run": a.run_speed}
    expected = {}
    animated, translated = set(), {bone("C", "Hips")}
    for c in clips:
        values = key_clip(arm, sk, c, CLIPS[c], speeds)
        expected[c] = {k: v for k, v in values.items() if not k.startswith("__")}
        animated |= set(expected[c])
    for spec in a.kimodo:
        name, path = spec.split("=", 1)
        values = key_frames(arm, name, retarget_kimodo(sk, os.path.abspath(path)), {})
        expected[name] = {k: v for k, v in values.items() if not k.startswith("__")}
        animated |= set(expected[name])
    if a.blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.blend))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.keep_export or os.path.join(tempfile.mkdtemp(prefix="animate-"), "blender.glb")
    export(os.path.abspath(tmp))
    worst = graft(os.path.abspath(a.src), os.path.abspath(tmp), os.path.abspath(a.out), animated, translated, expected)
    if math.degrees(worst) > 0.05:
        raise SystemExit(f"exported rotations differ from the evaluated pose by {math.degrees(worst):.3f}°")


if __name__ == "__main__":
    main()
