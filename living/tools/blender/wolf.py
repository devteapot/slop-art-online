"""A stylised wolf with a procedural quadruped rig and keyed clips, for the game client.

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

import argparse
import json
import math
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

FPS = 30


def P(f, s, u):
    """The wolf's frame (forward, left, up) in Blender's: it faces -Y, so glTF +Z."""
    return Vector((s, -f, u))


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def bump(t, a, b):
    """0 outside a..b, rising and falling smoothly inside."""
    if t <= a or t >= b:
        return 0.0
    return math.sin(math.pi * (t - a) / (b - a))


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


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


LEN = {
    "upper": dist2(REST["shoulder"], REST["elbow"]), "fore": dist2(REST["elbow"], REST["wrist"]),
    "thigh": dist2(REST["hip"], REST["stifle"]), "shin": dist2(REST["stifle"], REST["hock"]),
}
# Paw offsets from the wrist / hock at rest (pastern and metatarsus).
PASTERN = (REST["fpaw"][0] - REST["wrist"][0], REST["fpaw"][1] - REST["wrist"][1])
META = (REST["hpaw"][0] - REST["hock"][0], REST["hpaw"][1] - REST["hock"][1])

LEGS = {  # name: (front, side sign)
    "fl": (True, 1.0), "fr": (True, -1.0), "hl": (False, 1.0), "hr": (False, -1.0),
}

# Bones: name -> (head joint, tail joint, parent). Joint names with a leg prefix are per leg.
BONES = [
    ("root", None, None, None),
    ("hips", "pelvis", "mid", "root"),
    ("spine", "mid", "chest", "hips"),
    ("chest", "chest", "neck", "spine"),
    ("neck", "neck", "skull", "chest"),
    ("head", "skull", "nose", "neck"),
    ("jaw", "jaw0", "jaw1", "head"),
    ("tail1", "tail0", "tail1", "hips"),
    ("tail2", "tail1", "tail2", "tail1"),
    ("tail3", "tail2", "tail3", "tail2"),
]
for leg, (front, _) in LEGS.items():
    if front:
        BONES += [(f"upper.{leg}", f"{leg}.shoulder", f"{leg}.elbow", "chest"),
                  (f"fore.{leg}", f"{leg}.elbow", f"{leg}.wrist", f"upper.{leg}"),
                  (f"paw.{leg}", f"{leg}.wrist", f"{leg}.fpaw", f"fore.{leg}")]
    else:
        BONES += [(f"thigh.{leg}", f"{leg}.hip", f"{leg}.stifle", "hips"),
                  (f"shin.{leg}", f"{leg}.stifle", f"{leg}.hock", f"thigh.{leg}"),
                  (f"paw.{leg}", f"{leg}.hock", f"{leg}.hpaw", f"shin.{leg}")]


def rot2(v, a):
    c, s = math.cos(a), math.sin(a)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def ik2(root, target, a, b, forward_knee):
    """Two-bone IK in a leg's (forward, up) plane: the middle joint, bent forward or back."""
    dx, du = target[0] - root[0], target[1] - root[1]
    d = math.hypot(dx, du)
    d = min(max(d, abs(a - b) + 1e-3), a + b - 1e-4)
    ex, eu = dx / max(math.hypot(dx, du), 1e-6), du / max(math.hypot(dx, du), 1e-6)
    x = (a * a - b * b + d * d) / (2 * d)
    y = math.sqrt(max(a * a - x * x, 0.0))
    px, pu = -eu, ex  # perpendicular toward forward for a downward leg
    if not forward_knee:
        px, pu = -px, -pu
    return (root[0] + ex * x + px * y, root[1] + eu * x + pu * y)


class Pose:
    """Joint points of one frame, in the wolf's frame (f, s, u)."""

    def __init__(self):
        self.pt = {}

    def set(self, name, f, u, s=0.0):
        self.pt[name] = (f, s, u)


def body_pose(bob=0.0, pitch=0.0, lean=0.0, flex=0.0, shift=0.0, head=(0.0, 0.0), head_turn=0.0, jaw=0.0, tail=(0.0, 0.0), crouch=0.0):
    """The torso, head and tail: `bob` lifts it, `pitch` tips it nose-down (+, radians) about
    its middle, `flex` arches the back (+) or stretches it (-), `shift` slides it forward,
    `head` (lower, reach) moves the head down and out, `head_turn` turns it left (radians),
    `jaw` opens the mouth (radians), `tail` (raise, sway) in radians, `crouch` lowers the hind
    and front ends (m). Returns a Pose without legs and a function placing body-fixed points."""
    p = Pose()
    cf, cu = -0.09, 0.66

    def place(f, u, lift=0.0):
        rf, ru = rot2((f - cf, u - cu), -pitch)
        return (cf + rf + shift, cu + ru + bob + lift - crouch)

    for k in ("pelvis", "mid", "chest", "neck", "tail0"):
        f, u = REST[k]
        lift = {"mid": flex * 0.06, "pelvis": -flex * 0.02, "chest": -flex * 0.02}.get(k, 0.0)
        if k in ("pelvis", "tail0"):
            f += flex * 0.05
        if k == "chest":
            f -= flex * 0.05
        p.set(k, *place(f, u, lift))
    # Neck and head: lowered (`head[0]`) and reaching out (`head[1]`), turned by head_turn.
    nf, _, nu = p.pt["neck"]
    sf, su = REST["skull"][0] - REST["neck"][0], REST["skull"][1] - REST["neck"][1]
    neck_a = -head[0] * 0.9 - pitch
    sf, su = rot2((sf * (1 + head[1]), su), neck_a)
    ts = math.sin(head_turn) * math.hypot(sf, su)
    sf *= math.cos(head_turn) ** 0.5
    p.set("skull", nf + sf, nu + su, ts)
    kf, ks, ku = p.pt["skull"]
    head_a = -head[0] * 0.6 - pitch
    for k in ("nose", "jaw0", "jaw1"):
        df, du = REST[k][0] - REST["skull"][0], REST[k][1] - REST["skull"][1]
        if k == "jaw1":
            # The jaw swings down about its hinge (jaw0).
            jf, ju = REST["jaw0"][0] - REST["skull"][0], REST["jaw0"][1] - REST["skull"][1]
            rf, ru = rot2((df - jf, du - ju), -jaw)
            df, du = jf + rf, ju + ru
        df, du = rot2((df, du), head_a)
        p.set(k, kf + df * math.cos(head_turn), ku + du, ks + df * math.sin(head_turn))
    # Tail: hanging in a curve, raised and swayed.
    tf, _, tu = p.pt["tail0"]
    prev = (tf, 0.0, tu)
    for i, k in enumerate(("tail1", "tail2", "tail3")):
        a, b = REST[("tail0", "tail1", "tail2")[i]], REST[k]
        df, du = rot2((b[0] - a[0], b[1] - a[1]), tail[0] * (0.6 + 0.4 * i) - pitch)
        ds = math.sin(tail[1] * (0.5 + 0.5 * i)) * abs(df)
        prev = (prev[0] + df, prev[1] + ds, prev[2] + du)
        p.pt[k] = prev
    return p, place


def leg_points(p, place, leg, paw, lift_paw=0.0, fold=0.0):
    """Solve one leg to put its paw (f, u) at `paw`; `fold` bends the wrist or hock (radians,
    swing phase), `lift_paw` raises the toe. Writes the leg's joints into the pose."""
    front, sgn = LEGS[leg]
    s = SIDE * sgn
    if front:
        root = place(*REST["shoulder"])
        off = rot2(PASTERN, fold)
        wrist = (paw[0] - off[0], paw[1] - off[1])
        elbow = ik2(root, wrist, LEN["upper"], LEN["fore"], forward_knee=False)
        names = ("shoulder", "elbow", "wrist", "fpaw")
        pts = (root, elbow, wrist, paw)
    else:
        root = place(*REST["hip"])
        off = rot2(META, -fold)
        hock = (paw[0] - off[0], paw[1] - off[1])
        stifle = ik2(root, hock, LEN["thigh"], LEN["shin"], forward_knee=True)
        names = ("hip", "stifle", "hock", "hpaw")
        pts = (root, stifle, hock, paw)
    for n, q in zip(names, pts):
        p.set(f"{leg}.{n}", q[0], q[1], s)


def neutral_paw(leg):
    return REST["fpaw"] if LEGS[leg][0] else REST["hpaw"]


# ---------------------------------------------------------------------------------------------
# Clips: name -> (seconds, loop, natural speed m/s or None, function(t in 0..1) -> Pose)


def gait(t, speed, period, offsets, duty, lift, body):
    """A cyclic gait at `speed` m/s: each leg's paw is planted for `duty` of the cycle and
    moves back under the body at exactly `speed`, then swings forward."""
    p, place = body
    reach = speed * period * duty  # ground covered while a paw is down
    for leg, off in offsets.items():
        ph = (t + off) % 1.0
        f0, u0 = neutral_paw(leg)
        if ph < duty:
            x = ph / duty
            f = f0 + reach * (0.5 - x)
            paw, fold = (f, u0), 0.0
        else:
            x = (ph - duty) / (1 - duty)
            e = smooth(x)
            f = f0 + reach * (e - 0.5)
            h = lift * math.sin(math.pi * x) ** 0.8
            paw, fold = (f, u0 + h), 1.1 * math.sin(math.pi * min(1.0, x * 1.3))
        leg_points(p, place, leg, paw, fold=fold)
    return p


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


def stand(body):
    p, place = body
    for leg in LEGS:
        leg_points(p, place, leg, neutral_paw(leg))
    return p


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
    ang = roll * math.pi / 2 * 0.97
    pivot = 0.0
    out = Pose()
    for k, (f, sd, u) in p.pt.items():
        uu = u - pivot
        s2 = sd * math.cos(ang) - uu * math.sin(ang)
        u2 = sd * math.sin(ang) + uu * math.cos(ang) + pivot
        out.pt[k] = (f, s2, u2)
    # Keep the lowest point on the ground and the body centred where it stood.
    low = min(q[2] for q in out.pt.values())
    cs = out.pt["mid"][1]
    for k, (f, sd, u) in out.pt.items():
        out.pt[k] = (f, sd - cs * roll, u - low * roll)
    return out


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


def rest_pose():
    return stand(body_pose())


# ---------------------------------------------------------------------------------------------
# Armature


def bone_matrix(head, tail):
    """Armature-space matrix of a bone from its head and tail (Blender coords): Y along it, X
    toward the wolf's left where it can be."""
    y = (tail - head).normalized()
    side = Vector((1, 0, 0))
    x = side - y * side.dot(y)
    if x.length < 1e-4:
        x = Vector((0, 0, 1)) - y * y.z
    x.normalize()
    z = x.cross(y)
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = head
    return m


def joint(pose, name):
    f, s, u = pose.pt[name]
    return P(f, s, u)


def bone_ends(pose, b):
    _, h, t, _ = b
    if h is None:
        return P(0, 0, 0), P(0.2, 0, 0)
    return joint(pose, h), joint(pose, t)


def make_armature(rest):
    arm_data = bpy.data.armatures.new("WolfRig")
    arm = bpy.data.objects.new("Wolf", arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = {}
    for b in BONES:
        name, _, _, parent = b
        head, tail = bone_ends(rest, b)
        eb = arm_data.edit_bones.new(name)
        eb.head, eb.tail = head, tail
        eb.matrix = bone_matrix(head, tail)
        eb.length = (tail - head).length
        eb.use_deform = name != "root"
        if parent:
            eb.parent = ebs[parent]
            eb.use_connect = False
        ebs[name] = eb
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


# ---------------------------------------------------------------------------------------------
# Mesh

# Display (sRGB) colours: bmesh's colour layer holds sRGB bytes, and the exporter writes them out
# as linear COLOR_0, so these show as written.
COAT = (0.50, 0.49, 0.47)
SADDLE = (0.27, 0.26, 0.25)
PALE = (0.84, 0.80, 0.72)
DARK = (0.08, 0.07, 0.07)
EYE = (0.85, 0.62, 0.20)


def loft(bm, stations, sides=8, cap0=True, cap1=True, phase=0.0):
    """Rings at `stations` [(centre Vector, along Vector, half width, half height)], joined
    into a tube. Rings lie across `along`; width runs along the wolf's side (X)."""
    rings = []
    for c, along, w, h in stations:
        a = along.normalized()
        x = Vector((1, 0, 0)) - a * a.x
        if x.length < 1e-3:
            x = Vector((0, 1, 0)) - a * a.y
        x.normalize()
        y = a.cross(x).normalized()
        ring = []
        for i in range(sides):
            t = 2 * math.pi * (i + phase) / sides
            ct, st = math.cos(t), math.sin(t)
            # A soft superellipse: fuller than an ellipse, so the low-poly body reads as mass.
            r = (abs(ct) ** 2.6 + abs(st) ** 2.6) ** (-1 / 2.6)
            ring.append(bm.verts.new(c + x * (ct * w * r) + y * (st * h * r)))
        rings.append(ring)
    faces = []
    for r0, r1 in zip(rings, rings[1:]):
        for i in range(sides):
            j = (i + 1) % sides
            faces.append(bm.faces.new((r0[i], r0[j], r1[j], r1[i])))
    if cap0:
        faces.append(bm.faces.new(list(reversed(rings[0]))))
    if cap1:
        faces.append(bm.faces.new(rings[-1]))
    return [v for r in rings for v in r], faces


def path_stations(points, sizes):
    """Stations along a polyline of Vectors with (w, h) per point."""
    out = []
    for i, (c, (w, h)) in enumerate(zip(points, sizes)):
        a = points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]
        out.append((c, a, w, h))
    return out


class Part:
    def __init__(self, bm, verts, faces, bones, color):
        self.verts, self.faces, self.bones, self.color = verts, faces, bones, color


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


def lerp_c(a, b, t):
    t = min(1.0, max(0.0, t))
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.dot(ab), 1e-9)))
    return (p - (a + ab * t)).length


def make_mesh(rest, arm):
    bm, parts = build_mesh(rest)
    col = bm.loops.layers.color.new("Color")
    for part in parts:
        for fc in part.faces:
            fc.smooth = True
            for loop in fc.loops:
                loop[col] = (*part.color(loop.vert.co, fc.normal), 1.0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new("WolfBody")
    # Weights from each part's own bones, by distance to their segments.
    ends = {b[0]: bone_ends(rest, b) for b in BONES}
    weights = {}
    for part in parts:
        for v in part.verts:
            ds = [(seg_dist(v.co, *ends[b]), b) for b in part.bones]
            ds.sort()
            ws = [(1.0 / (d + 0.015) ** 4, b) for d, b in ds[:3]]
            tot = sum(w for w, _ in ws)
            weights[v] = [(w / tot, b) for w, b in ws if w / tot > 0.02]
    bm.verts.index_update()
    vw = {v.index: w for v, w in weights.items()}
    bm.to_mesh(me)
    bm.free()
    # The exporter writes the active colour attribute (export_vertex_color="ACTIVE").
    me.color_attributes.active_color = me.color_attributes["Color"]
    me.color_attributes.render_color_index = me.color_attributes.active_color_index
    obj = bpy.data.objects.new("WolfBody", me)
    bpy.context.collection.objects.link(obj)
    mat = bpy.data.materials.new("Body")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (1, 1, 1, 1)
    bsdf.inputs["Roughness"].default_value = 0.9
    me.materials.append(mat)
    groups = {b[0]: obj.vertex_groups.new(name=b[0]) for b in BONES if b[0] != "root"}
    for i, ws in vw.items():
        tot = sum(w for w, _ in ws)
        for w, b in ws:
            groups[b].add([i], w / tot, "REPLACE")
    obj.parent = arm
    mod = obj.modifiers.new("Rig", "ARMATURE")
    mod.object = arm
    return obj


# ---------------------------------------------------------------------------------------------
# Keying


def key_clip(arm, name, seconds, fn, loop):
    n = max(2, round(seconds * FPS))
    frames = n if loop else n + 1
    rest = {b.name: b.matrix_local.copy() for b in arm.data.bones}
    parent = {b[0]: b[3] for b in BONES}
    act = bpy.data.actions.new(name)
    arm.animation_data_create()
    arm.animation_data.action = act
    seq = {b[0]: [] for b in BONES}
    for i in range(frames + (1 if loop else 0)):
        t = (i % n) / n if loop else i / n
        pose = fn(t)
        M = {}
        for b in BONES:
            head, tail = bone_ends(pose, b)
            M[b[0]] = bone_matrix(head, tail)
        for b in BONES:
            bn = b[0]
            par = parent[bn]
            if par:
                local = (M[par] @ rest[par].inverted() @ rest[bn]).inverted() @ M[bn]
            else:
                local = rest[bn].inverted() @ M[bn]
            seq[bn].append(local)
    for bn, mats in seq.items():
        pb = arm.pose.bones[bn]
        pb.rotation_mode = "QUATERNION"
        qs, ls = [], []
        prev = None
        for m in mats:
            q = m.to_quaternion()
            if prev is not None and prev.dot(q) < 0:
                q = -q
            prev = q
            qs.append(q)
            ls.append(m.to_translation())
        for path, comps in ((pb.path_from_id("rotation_quaternion"), [[q.w for q in qs], [q.x for q in qs], [q.y for q in qs], [q.z for q in qs]]),
                            (pb.path_from_id("location"), [[v.x for v in ls], [v.y for v in ls], [v.z for v in ls]])):
            for k, comp in enumerate(comps):
                fc = act.fcurve_ensure_for_datablock(arm, path, index=k, group_name=bn)
                fc.keyframe_points.add(len(comp))
                fc.keyframe_points.foreach_set("co", [x for f, v in enumerate(comp) for x in (f, v)])
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
                fc.update()
    arm.animation_data.action = None
    track = arm.animation_data.nla_tracks.new()
    track.name = name
    strip = track.strips.new(name, 0, act)
    strip.name = name
    act.use_fake_user = True
    return len(seq["root"])


def paw_slide(fn, speed, period):
    """How far a planted paw drifts (m) between samples, at worst: its world-space travel while it
    is on the ground (within 2 mm of its rest height), against the body moving at `speed`."""
    worst = 0.0
    n = 240
    for leg in LEGS:
        name = f"{leg}.{'fpaw' if LEGS[leg][0] else 'hpaw'}"
        prev = None
        for i in range(n + 1):
            t = i / n
            f, _, u = fn(t).pt[name]
            world = f + speed * period * t
            ground = REST["fpaw" if LEGS[leg][0] else "hpaw"][1] + 0.002
            if u < ground and prev is not None and prev[1] < ground:
                worst = max(worst, abs(world - prev[0]))
            prev = (world, u)
    return worst


def paw_markers(fn, seconds, speed, loop):
    """Each paw's contact windows (normalised clip time), detected from the clip as baked: the paw
    within 1 cm of its rest height and slower than 0.3 m/s in the world (the body moving at
    `speed`). Loops' windows that cross the seam are split at 1. The gaits all bring the left hind
    paw down at 0 (`gait`'s offsets), the phase the game syncs them on (`sync: "hl"`)."""
    n = max(2, round(seconds * FPS))
    frames = n if loop else n + 1
    out = {}
    for leg in LEGS:
        name = f"{leg}.{'fpaw' if LEGS[leg][0] else 'hpaw'}"
        rest_u = REST["fpaw" if LEGS[leg][0] else "hpaw"][1]
        pts = []
        for i in range(frames + 1):
            f, _, u = fn((i % n) / n if loop else min(i, n) / n).pt[name]
            pts.append((f + (speed or 0.0) * seconds * i / n, u))
        down = []
        for i in range(frames):
            (f0, u0), (f1, _) = pts[i], pts[i + 1] if (loop or i + 1 < frames) else pts[i]
            down.append(u0 - rest_u <= 0.01 and abs(f1 - f0) * FPS <= 0.3)
        wins, i = [], 0
        while i < frames:
            if down[i]:
                j = i
                while j < frames and down[j]:
                    j += 1
                wins.append([i / n, min(j / n, 1.0)])
                i = j
            else:
                i += 1
        # A loop's window that runs to its end continues at 0: one contact, split at the seam.
        out[leg] = [[round(a, 4), round(b, 4)] for a, b in wins]
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary")
    a = ap.parse_args(argv)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rest = rest_pose()
    arm = make_armature(rest)
    body = make_mesh(rest, arm)
    withers = max(v.co.z for v in body.data.vertices if 0.1 < -v.co.y < 0.3)
    summary = {"model": "wolf", "fps": FPS, "faces": "+Z", "shoulder_m": round(withers, 3), "clips": []}
    for name, (seconds, loop, speed, fn) in CLIPS.items():
        frames = key_clip(arm, name, seconds, fn, loop)
        rec = {"name": name, "seconds": round(seconds, 3), "loop": loop, "frames": frames}
        rec["contacts"] = paw_markers(fn, seconds, speed, loop)
        if speed:
            rec["sync"] = "hl"
        if speed:
            rec["speed"] = speed
            rec["paw_slide_m"] = round(paw_slide(fn, speed, seconds), 4)
        if name == "bite":
            rec["snap_s"] = BITE_SNAP
        summary["clips"].append(rec)
        print(f"CLIP {name}: {seconds:.2f} s, {frames} keys" + (f", {speed} m/s, paw slide {rec['paw_slide_m'] * 100:.1f} cm" if speed else ""))
    tris = sum(len(p.vertices) - 2 for p in body.data.polygons)
    summary["triangles"] = tris
    summary["bones"] = len(BONES) - 1
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=a.out, export_format="GLB", export_yup=True, export_vertex_color="ACTIVE", export_normals=True,
        export_animations=True, export_animation_mode="NLA_TRACKS", export_force_sampling=True, export_frame_step=1,
        export_optimize_animation_size=False, export_def_bones=False, export_leaf_bone=False, export_reset_pose_bones=True,
        export_rest_position_armature=True, export_morph_animation=False, export_materials="EXPORT")
    print(f"WOLF {a.out}: {tris} triangles, {len(BONES) - 1} bones, {len(CLIPS)} clips")
    if a.summary:
        with open(a.summary, "w") as f:
            json.dump(summary, f, indent=1)


main()
