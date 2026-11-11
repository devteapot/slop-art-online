"""A person made wholly by script: body, head and face, hands, hair and clothes on the J_Bip skeleton.

The game's character generator (docs/CHARACTERS.md). A person is a set of parameters
(person_params.py): sex, age, build, face, skin, eyes, hair, beard and outfit. A seed gives a
repeatable person, and a parameter file or `--set` overrides any value.

Run headless (gen_person.sh runs this and then the steps every base goes through: animate.py,
merge_primitives.py, face_normals.py):
    blender -b -P living/tools/blender/person.py -- --out living/game/assets/lookdev/own-man.glb \
        [--variant man|woman|elder|youth|boy|girl|<seed>:<kind>] [--seed N] [--params person.json]
        [--set age=70 --set face.jaw_width=0.8 ...] [--expression Fcl_MTH_Fun=1] [--body] [--no-shade] [--blend x.blend]

Beside the model it writes `<name>.params.json` (the person's full parameters, to edit and pass
back with --params, and the game recipe's height and proportions) and `<name>.atlas.png` (the
painted face).

The output follows the conventions the VRoid bases brought, so the rest of the pipeline is
unchanged (animate.py, merge_primitives.py, face_normals.py, characters.rs, lookdev.rs):
- metres, the sole on the floor, the character facing glTF -Z (Blender +Y), its left at -X;
- the `J_Bip_*` skeleton in a T-pose with identity rest rotations under a `Root` bone, so
  animate.py retargets the Kimodo library onto it unchanged;
- material names carry VRoid's group tags: `…Face_00_SKIN` (the face: face_normals.py flattens
  its normals and writes its shadow map from TEXCOORD_0), `…Body_00_SKIN`, `…_EYE`, `…_FACE`,
  `…_HAIR`, and `…Tops…`, `…Bottoms…`, `…Shoes…`, `…Coat…` `_CLOTH`, which is how the game picks
  the toon shading kind and the recipe colour slot;
- the face's expressions are morph targets under VRoid's names (`Fcl_EYE_Close`, `Fcl_MTH_A`,
  which the game drives, and thirteen more: head_mesh.EXPRESSIONS);
- an `extensions.VRM` block (VRM 0.x: meta, humanoid bones, expression groups, empty spring
  groups), which is how the game recognises a character file. It is written here as plain JSON;
  nothing of VRoid's is used.

How it is made:
- **The head** is a form set by the face parameters (head_form.py), meshed with real eye openings
  and a mouth slit, the eyes set back behind the lids, lashes and brows standing off the skin
  (head_mesh.py), and one painted atlas for the skin and the eyes (face_paint.py). A beard is
  the skin standing off the face with its hairs painted.
- **Colour** elsewhere is per face corner (COLOR_0) on white materials, as for the environment
  kits and the outfit pieces. `bake_shade` multiplies in how closed-in each vertex is in the
  rest pose, and cloth takes a slow mottle: the soft light is painted into the colours.
- **Clothes and limbs** are low cages lofted from rings (a superellipse torso, tubes for arms,
  legs and boots) with the weights written ring by ring, mirrored, then subdivided once
  (Catmull-Clark carries weights and the ring parameters). Garments are the body's form plus an
  offset, so layers share their weights and move together.
- **Hair** is a cap over the scalp and tapered clumps that follow the head's surface. Kerchiefs
  and caps are the head's own quads pushed out, their edge snapped to a smooth line.
- **Hands** are a lofted palm and five finger tubes with two rings round every joint.

Skin exists only where it shows (head, neck, hands); `--body` builds the unclothed form instead,
to show what the clothes are fitted to.
"""

import argparse
import json
import math
import os
import random
import struct
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import face_paint  # noqa: E402
import hair  # noqa: E402
import head_form  # noqa: E402
import head_mesh  # noqa: E402
import person_params  # noqa: E402

PI = math.pi


def lin(c):
    """sRGB (0..1) to linear."""
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c[:3])


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def lerp(a, b, t):
    return a + (b - a) * t


def mottle(c, co, amount=0.07, scale=1.0):
    """Cloth is never one flat colour: a slow, soft variation in value over the surface (and a
    little toward the weathered side of the hue), from the point's position."""
    x, y, z = co[0] * scale, co[1] * scale, co[2] * scale
    n = math.sin(23.0 * x + 1.3 + 2.1 * math.sin(17.0 * z)) * math.sin(19.0 * z + 0.7 + 1.7 * math.sin(13.0 * y)) * math.cos(21.0 * y + 2.9)
    n += 0.5 * math.sin(47.0 * x + 31.0 * z + 5.0 * math.sin(29.0 * y))
    k = 1.0 + amount * n / 1.5
    return tuple(min(max(v * k, 0.0), 1.0) for v in c)


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def table(rows, z):
    """Piecewise-linear lookup in rows of (key, values…), clamped at the ends."""
    if z <= rows[0][0]:
        return rows[0][1:]
    for a, b in zip(rows, rows[1:]):
        if z <= b[0]:
            t = (z - a[0]) / (b[0] - a[0])
            return tuple(lerp(x, y, t) for x, y in zip(a[1:], b[1:]))
    return rows[-1][1:]


# ---------------------------------------------------------------------------------------------
# What varies between people: configure() sets these from a person's parameters
# (person_params.py, docs/CHARACTERS.md).

PAL = person_params.PAL
SKIN = (0.86, 0.66, 0.54)
SKIN_WARM = (0.80, 0.48, 0.40)
SKIN_SHADE = (0.66, 0.45, 0.37)
HAIR = (0.115, 0.09, 0.08)
HAIR_TIP = (0.20, 0.155, 0.125)
RECEDE = 0.0  # how far the front hairline has moved back, m
BALD = 0.0  # 0 a full head of hair to 1 a bald crown from the forehead back
STRANDS_PATH = ""  # where the strands' picture is written
LIMB_K = 1.0  # girth of arms and legs
GIRTH = 1.0  # girth of the torso
BELLY = 0.0  # how far a belly stands forward (a share of the torso's depth)
CHEST = 0.0  # how much wider and deeper a strong chest is
LONG = 0.07  # how far a bob hangs below the hairline, m
HF = None  # the head's form (head_form.Head)

MAT = dict(
    face="M00_000_00_Face_00_SKIN", skin="M00_000_00_Body_00_SKIN", eye="M00_000_00_Eye_00_EYE", brow="M00_000_00_FaceBrow_00_FACE",
    line="M00_000_00_FaceEyeline_00_FACE", mouth="M00_000_00_FaceMouth_00_FACE", hair="M00_000_Hair_00_HAIR",
    jersey="M00_001_01_Tops_01_CLOTH", trousers="M00_001_01_Bottoms_01_CLOTH", boots="M00_001_01_Shoes_01_CLOTH",
    coat="M00_001_01_Coat_01_CLOTH",
)

# ---------------------------------------------------------------------------------------------
# The skeleton: an adult man, 1.78 m to the scalp. Blender axes: +Y forward, +Z up, left at -X.

ARM_Y, ARM_Z = -0.010, 1.420
SHOULDER_X = -0.199  # the shoulder joint: broad for a working man
WRIST_X = SHOULDER_X - 0.530
JOINTS = {
    "Root": (0, 0, 0),
    "J_Bip_C_Hips": (0, 0.000, 0.985),
    "J_Bip_C_Spine": (0, 0.006, 1.060),
    "J_Bip_C_Chest": (0, 0.012, 1.180),
    "J_Bip_C_UpperChest": (0, 0.004, 1.310),
    "J_Bip_C_Neck": (0, -0.020, 1.475),
    "J_Bip_C_Head": (0, -0.010, 1.560),
    "J_Bip_L_Shoulder": (-0.025, -0.012, 1.435),
    "J_Bip_L_UpperArm": (SHOULDER_X, ARM_Y, ARM_Z),
    "J_Bip_L_LowerArm": (SHOULDER_X - 0.280, ARM_Y, ARM_Z),
    "J_Bip_L_Hand": (WRIST_X, ARM_Y, ARM_Z),
    "J_Bip_L_UpperLeg": (-0.092, 0.000, 0.930),
    "J_Bip_L_LowerLeg": (-0.092, 0.006, 0.500),
    "J_Bip_L_Foot": (-0.092, -0.012, 0.085),
    "J_Bip_L_ToeBase": (-0.092, 0.125, 0.022),
}
PARENT = {
    "J_Bip_C_Hips": "Root", "J_Bip_C_Spine": "J_Bip_C_Hips", "J_Bip_C_Chest": "J_Bip_C_Spine",
    "J_Bip_C_UpperChest": "J_Bip_C_Chest", "J_Bip_C_Neck": "J_Bip_C_UpperChest", "J_Bip_C_Head": "J_Bip_C_Neck",
    "J_Bip_L_Shoulder": "J_Bip_C_UpperChest", "J_Bip_L_UpperArm": "J_Bip_L_Shoulder", "J_Bip_L_LowerArm": "J_Bip_L_UpperArm",
    "J_Bip_L_Hand": "J_Bip_L_LowerArm", "J_Bip_L_UpperLeg": "J_Bip_C_Hips", "J_Bip_L_LowerLeg": "J_Bip_L_UpperLeg",
    "J_Bip_L_Foot": "J_Bip_L_LowerLeg", "J_Bip_L_ToeBase": "J_Bip_L_Foot",
}
# Fingers of the left hand (it points along -X, palm down, thumb forward): the knuckle relative to
# the wrist (x along the arm, y forward), the three bone lengths and the radius.
FINGERS = {
    "Index": ((-0.096, 0.030), (0.041, 0.026, 0.023), 0.0100),
    "Middle": ((-0.100, 0.010), (0.045, 0.029, 0.024), 0.0102),
    "Ring": ((-0.096, -0.010), (0.041, 0.027, 0.023), 0.0096),
    "Little": ((-0.088, -0.029), (0.032, 0.020, 0.020), 0.0086),
}
HAND_K = 1.12  # large working hands
FINGERS = {n: ((kx * HAND_K, ky * HAND_K), tuple(x * HAND_K for x in lens), r * HAND_K * 1.05) for n, ((kx, ky), lens, r) in FINGERS.items()}
THUMB_ROOT = Vector((WRIST_X - 0.024 * HAND_K, ARM_Y + 0.026 * HAND_K, ARM_Z - 0.007))
THUMB_DIR = Vector((-0.62, 0.78, -0.10)).normalized()
THUMB_LEN = tuple(x * HAND_K for x in (0.040, 0.031, 0.027))
THUMB_R = 0.0118 * HAND_K * 1.05


def finger_joints():
    for name, ((kx, ky), lens, _) in FINGERS.items():
        p = Vector((WRIST_X + kx, ARM_Y + ky, ARM_Z - 0.001))
        parent = "J_Bip_L_Hand"
        for i, ln in enumerate(lens):
            b = f"J_Bip_L_{name}{i + 1}"
            JOINTS[b] = tuple(p)
            PARENT[b] = parent
            parent = b
            p = p + Vector((-ln, 0, 0))
    p = THUMB_ROOT.copy()
    parent = "J_Bip_L_Hand"
    for i, ln in enumerate(THUMB_LEN):
        b = f"J_Bip_L_Thumb{i + 1}"
        JOINTS[b] = tuple(p)
        PARENT[b] = parent
        parent = b
        p = p + THUMB_DIR * ln


def mirror_name(n):
    if n.startswith("J_Bip_L_"):
        return "J_Bip_R_" + n[8:]
    if n.startswith("J_Bip_R_"):
        return "J_Bip_L_" + n[8:]
    return n


def make_armature():
    finger_joints()
    # The eyes' bones (VRoid's names), each at the centre of the ball its iris lies on: turning
    # one slides that iris over the white.
    if HF is not None:
        for side, n in ((-1, "J_Adj_L_FaceEye"), (1, "J_Adj_R_FaceEye")):
            JOINTS[n] = tuple(hw(head_mesh.eye_ball(HF, side)))
            PARENT[n] = "J_Bip_C_Head"
    for n in [n for n in JOINTS if n.startswith("J_Bip_L_")]:
        x, y, z = JOINTS[n]
        JOINTS[mirror_name(n)] = (-x, y, z)
        PARENT[mirror_name(n)] = mirror_name(PARENT[n])
    data = bpy.data.armatures.new("Armature")
    arm = bpy.data.objects.new("Armature", data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    # Every bone's rest frame is the glTF frame turned to Z-up, so rest rotations are identity in
    # the file and a pose quaternion is the glTF local rotation (animate.py checks this).
    frame = Matrix.Rotation(math.radians(90), 4, "X")
    order = ["Root"] + [n for n in JOINTS if n != "Root"]
    for n in order:
        eb = data.edit_bones.new(n)
        eb.head = (0, 0, 0)
        eb.tail = (0, 0.04, 0)
        eb.matrix = Matrix.Translation(JOINTS[n]) @ frame
    for n in order:
        if n in PARENT:
            data.edit_bones[n].parent = data.edit_bones[PARENT[n]]
    bpy.ops.object.mode_set(mode="OBJECT")
    for b in data.bones:
        assert b.matrix_local.to_quaternion().rotation_difference(frame.to_quaternion()).angle < 1e-4, b.name
    return arm


# ---------------------------------------------------------------------------------------------
# Cages.


class Part:
    """A cage in progress: vertices with weights, faces with a tag and ring parameters (u round,
    v along). Tags pick colours after subdivision; `HIDE` faces are dropped then."""

    HIDE = 31

    def __init__(self, name):
        self.name = name
        self.co, self.w, self.faces, self.fuv, self.tags = [], [], [], [], []

    def v(self, co, w):
        self.co.append(Vector(co))
        self.w.append(dict(w))
        return len(self.co) - 1

    def f(self, idx, uv=None, tag=0):
        if len(set(idx)) < 3:
            return
        self.faces.append(tuple(idx))
        self.fuv.append(tuple(uv) if uv else tuple((0.0, 0.0) for _ in idx))
        self.tags.append(tag)

    def band(self, a, b, v0, v1, closed=True, tag=0, u0=0.0, u1=1.0):
        """Quads between two rings of the same length. `tag` may be fn(column) -> tag."""
        n = len(a)
        cols = n if closed else n - 1
        for i in range(cols):
            j = (i + 1) % n
            ua, ub = lerp(u0, u1, i / cols), lerp(u0, u1, (i + 1) / cols)
            t = tag(i) if callable(tag) else tag
            self.f((a[i], a[j], b[j], b[i]), ((ua, v0), (ub, v0), (ub, v1), (ua, v1)), t)

    def fan(self, ring, centre, v0, tag=0):
        n = len(ring)
        for i in range(n):
            j = (i + 1) % n
            self.f((ring[i], ring[j], centre), ((i / n, v0), ((i + 1) / n, v0), ((i + 0.5) / n, v0 + 1)), tag)

    def mirrored(self):
        """This cage and its reflection in X, sharing the vertices on the centre plane."""
        m = {}
        for i in range(len(self.co)):
            c = self.co[i]
            if abs(c.x) < 1e-6:
                m[i] = i
                # A centre vertex follows both sides alike.
                w = {}
                for n, x in self.w[i].items():
                    w[n] = w.get(n, 0) + x / 2
                    w[mirror_name(n)] = w.get(mirror_name(n), 0) + x / 2
                self.w[i] = w
            else:
                m[i] = self.v((-c.x, c.y, c.z), {mirror_name(n): x for n, x in self.w[i].items()})
        for k in range(len(self.faces)):
            idx, uv, tag = self.faces[k], self.fuv[k], self.tags[k]
            self.f(tuple(m[i] for i in reversed(idx)), tuple((1.0 - u, v) for u, v in reversed(uv)), tag)
        return self


def ring(part, centre, e1, e2, r1, r2, n, w, p=1.0, phase=0.0, r1b=None, r2b=None):
    """A ring of n vertices round `centre` in the plane of e1, e2: a superellipse with exponent p
    (1 is an ellipse, lower is boxier); r1b, r2b are the radii on the negative sides."""
    centre, e1, e2 = Vector(centre), Vector(e1), Vector(e2)
    out = []
    for i in range(n):
        a = 2 * PI * (i / n) + phase
        c, s = math.cos(a), math.sin(a)
        x = math.copysign(abs(c) ** p, c) * (r1 if c >= 0 or r1b is None else r1b)
        y = math.copysign(abs(s) ** p, s) * (r2 if s >= 0 or r2b is None else r2b)
        out.append(part.v(centre + e1 * x + e2 * y, w(i) if callable(w) else w))
    return out


def blend(*pairs):
    w = {}
    for n, x in pairs:
        if x > 1e-4:
            w[n] = w.get(n, 0) + x
    s = sum(w.values()) or 1.0
    return {n: x / s for n, x in w.items()}


# ---------------------------------------------------------------------------------------------
# The body's form: what every garment is an offset of.

# Torso: height, half width, half depth, centre forward.
TORSO = [
    (0.70, 0.150, 0.105, 0.000),
    (0.86, 0.152, 0.104, 0.000),
    (0.93, 0.162, 0.112, -0.004),
    (1.00, 0.155, 0.108, -0.002),
    (1.08, 0.141, 0.100, 0.004),
    (1.16, 0.145, 0.102, 0.008),
    (1.24, 0.156, 0.111, 0.010),
    (1.32, 0.168, 0.119, 0.008),
    (1.375, 0.174, 0.115, 0.000),
    (1.42, 0.180, 0.106, -0.006),
    (1.465, 0.180, 0.093, -0.008),
]
# A coat's skirt flares below the hips.
SKIRT = [(0.46, 0.078, 0.066), (0.66, 0.050, 0.040), (0.80, 0.030, 0.026), (0.93, 0.008, 0.008), (1.00, 0.0, 0.0)]
# Arm, along -X from the shoulder: x, radius forward, radius up.
ARM = [
    (-0.205, 0.055, 0.059),
    (-0.250, 0.050, 0.053),
    (-0.330, 0.046, 0.048),
    (-0.420, 0.040, 0.040),
    (-0.445, 0.039, 0.038),
    (-0.485, 0.039, 0.038),
    (-0.520, 0.040, 0.039),
    (-0.600, 0.034, 0.032),
    (-0.680, 0.028, 0.024),
    (-0.705, 0.027, 0.022),
]
ARM_OUT = SHOULDER_X + 0.185  # the table above was drawn for a shoulder at -0.185
ARM = [(x + ARM_OUT, ry, rz) for x, ry, rz in ARM]
# Left leg: height, centre x, centre y, radius across, radius forward.
LEG = [
    (0.84, -0.094, 0.000, 0.086, 0.092),
    (0.74, -0.094, 0.002, 0.078, 0.084),
    (0.62, -0.093, 0.004, 0.066, 0.070),
    (0.54, -0.092, 0.006, 0.056, 0.060),
    (0.50, -0.092, 0.008, 0.054, 0.058),
    (0.455, -0.092, 0.004, 0.050, 0.054),
    (0.38, -0.092, -0.006, 0.054, 0.058),
    (0.28, -0.092, -0.008, 0.044, 0.046),
    (0.16, -0.092, -0.010, 0.036, 0.038),
    (0.10, -0.092, -0.010, 0.034, 0.040),
]
LEG_UP = list(reversed(LEG))
NT = 20  # columns round the torso
SHOULDER = Vector((-0.170 + ARM_OUT, -0.008, 1.420))  # the armhole's centre
HOLE_R = 0.058


def torso_w(z, x, skirt=False, front=False):
    """Weights of a torso vertex at height z (and side x, for a coat's skirt)."""
    k = [(0.99, "J_Bip_C_Hips"), (1.09, "J_Bip_C_Spine"), (1.20, "J_Bip_C_Chest"), (1.31, "J_Bip_C_UpperChest")]
    if z <= k[0][0]:
        w = [(k[0][1], 1.0)]
    elif z >= k[-1][0]:
        w = [(k[-1][1], 1.0)]
    else:
        for (za, na), (zb, nb) in zip(k, k[1:]):
            if z <= zb:
                t = smooth((z - za) / (zb - za))
                w = [(na, 1 - t), (nb, t)]
                break
    if skirt and z < 0.93:
        # A skirt's panels follow the legs' stride: up to half the same side's upper leg at the hem.
        t = (0.85 if front else 0.55) * smooth((0.93 - z) / 0.25)
        side = min(abs(x) / 0.07, 1.0)
        left = t * (0.5 + 0.5 * side if x <= 0 else 0.5 - 0.5 * side)
        right = t - left
        w = [(n, v * (1 - t)) for n, v in w] + [("J_Bip_L_UpperLeg", left), ("J_Bip_R_UpperLeg", right)]
    return blend(*w)


def torso_point(z, k, d=0.0, skirt=0.0, n=NT, edge=None):
    """Column k (0 front, n/4 the left side, n/2 back) of the torso's ring at height z, offset d."""
    a, b, cy = table(TORSO, z)
    a, b = a * lerp(1.0, GIRTH, smooth((1.40 - z) / 0.08)), b * GIRTH
    # A strong chest is wider and deeper; a heavy person carries a belly in front and at the sides.
    chest = CHEST * math.exp(-(((z - 1.30) / 0.09) ** 2))
    belly = BELLY * math.exp(-(((z - 1.07) / 0.13) ** 2))
    a, b = a * (1 + chest + 0.45 * belly), b * (1 + chest)
    if skirt:
        fa, fb = table(SKIRT, z)
        a, b = a + fa * skirt, b + fb * skirt
    a, b = a + d, b + d
    phi = 2 * PI * k / n
    if edge is not None:
        # The front edge of an open coat: this column stands `edge` metres off the centre line.
        phi = math.asin(min(edge / a, 1.0) ** (1 / 0.85))
    s, c = math.sin(phi), math.cos(phi)
    p = 0.85
    front = 1 + belly if c > 0 else 1.0
    return Vector((-a * math.copysign(abs(s) ** p, s), cy + b * front * math.copysign(abs(c) ** p, c), z))


def arm_w(x):
    x = x - ARM_OUT
    lower = smooth((-0.432 - x) / 0.066)
    hand = smooth((-0.690 - x) / 0.04)
    sh = 0.25 * smooth((x + 0.25) / 0.045)
    return blend(("J_Bip_L_Shoulder", sh), ("J_Bip_L_UpperArm", (1 - sh) * (1 - lower)), ("J_Bip_L_LowerArm", lower * (1 - hand)), ("J_Bip_L_Hand", lower * hand))


def upper_garment(part, d, zs, hem, cuff, collar, front=None, skirt=0.0, tag_fn=None, cols=None):
    """The left half of a torso-and-arms garment at offset d from the body.

    zs: ring heights from the hem up to the armpit ring (exclusive of it); hem / cuff / collar
    add those rims; front(z) gives an open coat's edge distance (the garment then starts at
    column 1); tag_fn(kind, column, row) -> tag.
    """
    half = NT // 2
    k0 = 1 if front else 0
    ks = list(range(k0, half + 1))
    tag_fn = tag_fn or (lambda kind, k, r: 0)
    sk = skirt > 0
    cuff = (cuff[0] + ARM_OUT, cuff[1])  # callers give the cuff for a shoulder at -0.185

    def col_point(z, k):
        return torso_point(z, k, d, skirt, edge=front(z) if front and k == 1 else None)

    rows = []
    for z in zs:
        rows.append([part.v(col_point(z, k), torso_w(z, col_point(z, k).x, sk, k <= 4)) for k in ks])
    # The armpit ring (A), the ring through the armhole's middle (M) and the yoke line (T). The
    # armhole takes columns 4..6: its rim is the first ring of the sleeve.
    hole = {}
    rr = HOLE_R + d
    for name, ang in (("A4", 315), ("A5", 270), ("A6", 225), ("M6", 180), ("T6", 135), ("T5", 90), ("T4", 45), ("M4", 0)):
        a = math.radians(ang)
        hole[name] = SHOULDER + Vector((-d * 0.6 - 0.004 * abs(math.sin(a)), rr * 0.98 * math.cos(a), rr * math.sin(a)))
    zA, zM = 1.375, 1.42

    def shoulder_w(pos, base):
        # Near the armhole the yoke follows the shoulder and a little of the arm.
        near = smooth(1 - (pos - SHOULDER).length / 0.13)
        top = smooth((pos.z - 1.39) / 0.07)
        return blend(*[(n, x * (1 - 0.55 * near)) for n, x in base.items()], ("J_Bip_L_Shoulder", 0.33 * near * (0.5 + 0.5 * top)), ("J_Bip_L_UpperArm", 0.22 * near))

    def special(z, prefix, yoke_z=None):
        row = []
        for k in ks:
            if k in (4, 5, 6) and f"{prefix}{k}" in hole:
                pos = hole[f"{prefix}{k}"]
            elif k == 5:
                row.append(None)
                continue
            else:
                zz = z if yoke_z is None else yoke_z(k)
                pos = col_point(zz, k)
                pos.z = zz
            row.append(part.v(pos, shoulder_w(pos, torso_w(pos.z, pos.x))))
        return row

    rowA = special(zA, "A")
    rowM = special(zM, "M")
    # The yoke line dips at the front and rises over the shoulders.
    rowT = special(1.465, "T", lambda k: 1.448 + 0.022 * smooth(k / 4) - 0.004 * smooth((k - 6) / 4))
    rows += [rowA, rowM, rowT]
    nb = len(zs)
    for r in range(len(rows) - 1):
        a, b = rows[r], rows[r + 1]
        for i in range(len(ks) - 1):
            k = ks[i]
            if r >= nb and k in (4, 5):
                continue  # the armhole
            q = (a[i], a[i + 1], b[i + 1], b[i])
            if None in q:
                continue
            part.f(q, ((k / NT, r), ((k + 1) / NT, r), ((k + 1) / NT, r + 1), (k / NT, r + 1)), tag_fn("torso", k, r))
    # Yoke: from the yoke line up to the neck base.
    def neck_point(k, dz=0.0, dr=0.0):
        phi = 2 * PI * k / NT
        if front and k == 1:
            phi = math.asin(min(front(1.5) / (0.066 + d + dr), 1.0))
        s, c = math.sin(phi), math.cos(phi)
        z = 1.488 + 0.016 * smooth(k / 5.0) + dz
        return Vector((-(0.066 + d + dr) * s, -0.018 + (0.072 + d + dr) * c, z))

    prev = rowT
    for step in (1, 2, 3):
        t = step / 3
        cur = []
        for i, k in enumerate(ks):
            a = part.co[rowT[i]]
            b = neck_point(k)
            pos = a.lerp(b, t) + Vector((0, 0, -0.006 * math.sin(PI * t)))
            neck = 0.4 * smooth((t - 0.3) / 0.7)
            cur.append(part.v(pos, shoulder_w(pos, blend(("J_Bip_C_UpperChest", 1 - neck), ("J_Bip_C_Neck", neck)))))
        r = len(rows) - 2 + step
        for i in range(len(ks) - 1):
            k = ks[i]
            part.f((prev[i], prev[i + 1], cur[i + 1], cur[i]), ((k / NT, r), ((k + 1) / NT, r), ((k + 1) / NT, r + 1), (k / NT, r + 1)), tag_fn("yoke", k, r))
        prev = cur
    # Collar rings above the neck base: (height above it, radius change, weights).
    r = len(rows) + 2
    for dz, dr, w in collar:
        cur = [part.v(neck_point(k, dz, dr), w) for k in ks]
        for i in range(len(ks) - 1):
            k = ks[i]
            part.f((prev[i], prev[i + 1], cur[i + 1], cur[i]), ((k / NT, r), ((k + 1) / NT, r), ((k + 1) / NT, r + 1), (k / NT, r + 1)), tag_fn("collar", k, r))
        prev = cur
        r += 1
    # Hem rings below the first row: (height change, offset change).
    prev = rows[0]
    z0 = zs[0]
    for j, (dz, dd) in enumerate(hem):
        cur = []
        for k in ks:
            pos = torso_point(z0 + dz, k, d + dd, skirt, edge=front(z0 + dz) if front and k == 1 else None)
            cur.append(part.v(pos, torso_w(z0, pos.x, sk)))
        for i in range(len(ks) - 1):
            k = ks[i]
            part.f((cur[i], cur[i + 1], prev[i + 1], prev[i]), ((k / NT, -j - 1), ((k + 1) / NT, -j - 1), ((k + 1) / NT, -j), (k / NT, -j)), tag_fn("hem", k, -j - 1))
        prev = cur
    # The sleeve: the armhole's rim, then rings along the arm.
    i5 = ks.index(5) if 5 in ks else None
    idx = {k: ks.index(k) for k in (4, 5, 6)}
    rim = [rowM[idx[4]], rowT[idx[4]], rowT[idx[5]], rowT[idx[6]], rowM[idx[6]], rowA[idx[6]], rowA[idx[5]], rowA[idx[4]]]
    del i5
    prev = rim
    stations = [s for s in ARM if s[0] >= cuff[0] + 1e-6]
    n = 0
    for x, ry, rz in stations + [(cuff[0], *table(ARM_X, cuff[0]))]:
        cur = ring(part, (x, ARM_Y, ARM_Z), (0, 1, 0), (0, 0, 1), ry * LIMB_K + d, rz * LIMB_K + d, 8, arm_w(x))
        part.band(prev, cur, n, n + 1, tag=tag_fn("sleeve", 0, n))
        prev = cur
        n += 1
    for dx, dd in cuff[1]:
        x = cuff[0] + dx
        ry, rz = table(ARM_X, x)
        cur = ring(part, (x, ARM_Y, ARM_Z), (0, 1, 0), (0, 0, 1), ry * LIMB_K + d + dd, rz * LIMB_K + d + dd, 8, arm_w(x))
        part.band(prev, cur, n, n + 1, tag=tag_fn("cuff", 0, n))
        prev = cur
        n += 1
    return part


ARM_X = sorted(ARM)


def leg_ring(part, z, d, w, n=13, floor=None):
    cx, cy, rx, ry = table(LEG_UP, z)
    out = []
    for j in range(n):
        th = math.radians(45) + 2 * PI * j / n
        k = lerp(1.0, LIMB_K, smooth((0.86 - z) / 0.1))
        out.append(part.v((cx + (rx * k + d) * math.cos(th), cy + (ry * k + d) * math.sin(th), z), w))
    return out


def leg_w(z):
    lower = smooth((0.538 - z) / 0.076)
    foot = smooth((0.16 - z) / 0.09)
    return blend(("J_Bip_L_UpperLeg", 1 - lower), ("J_Bip_L_LowerLeg", lower * (1 - foot)), ("J_Bip_L_Foot", lower * foot))


def trousers(part, d, top=1.075, bottom=0.40, tag_fn=None):
    """The left half of a pair of trousers: waist, seat, the split at the crotch, one leg."""
    tag_fn = tag_fn or (lambda kind, k, r: 0)
    half = NT // 2
    ks = list(range(half + 1))
    rows = []
    zs = [top, 1.01, 0.94, 0.875]
    for z in zs:
        row = []
        for k in ks:
            pos = torso_point(z, k, d)
            if z < 0.9:
                # The seat narrows into the legs' tops.
                pos.x *= 0.99
            side = smooth(abs(pos.x) / 0.09)
            leg = (0.18 if z > 0.9 else 0.62) * side if z < 0.98 else 0.0
            row.append(part.v(pos, blend(*torso_w(z, pos.x).items(), ("J_Bip_L_UpperLeg", leg / max(1 - leg, 1e-3)))))
        rows.append(row)
    for r in range(len(rows) - 1):
        part.band(rows[r], rows[r + 1], r, r + 1, closed=False, tag=tag_fn("seat", 0, r), u0=0.0, u1=0.5)
    # Waistband lip.
    lip = [part.v(torso_point(top + 0.012, k, d - 0.012), torso_w(top, 0)) for k in ks]
    part.band(lip, rows[0], -1, 0, closed=False, tag=tag_fn("waist", 0, -1), u0=0.0, u1=0.5)
    # The crotch: two vertices on the centre plane join front to back between the legs.
    hips = {"J_Bip_C_Hips": 1.0}
    s1 = part.v((0, 0.040, 0.842), hips)
    s2 = part.v((0, -0.045, 0.846), hips)
    loop = rows[-1] + [s2, s1]
    n = len(loop)
    prev = loop
    r = len(rows)
    for z in [0.80, 0.72, 0.62, 0.555, 0.50, 0.455, bottom]:
        w = blend(*leg_w(z).items(), ("J_Bip_C_Hips", 0.12 if z > 0.79 else 0.0))
        cur = leg_ring(part, z, d * (1.0 if z > 0.5 else 0.7), w, n)
        part.band(prev, cur, r, r + 1, tag=tag_fn("leg", 0, r))
        prev = cur
        r += 1
    return part


def boot(part, d=0.0, tag_fn=None):
    """The left sea boot: a tube down the shin that turns forward through the heel into the foot,
    with a folded top. Rings: centre (y, z), tilt from pointing down (deg), radius across, radius
    toward the front or top, radius toward the back or sole."""
    tag_fn = tag_fn or (lambda kind, k, r: 0)
    x0 = -0.092
    rings = [
        ((-0.004, 0.470), 0, 0.068, 0.074, 0.072),
        ((-0.006, 0.360), 0, 0.061, 0.067, 0.066),
        ((-0.010, 0.240), 0, 0.054, 0.058, 0.058),
        ((-0.012, 0.150), 5, 0.051, 0.056, 0.055),
        ((-0.008, 0.095), 30, 0.052, 0.060, 0.080),
        ((0.000, 0.072), 60, 0.053, 0.066, 0.092),
        ((0.045, 0.058), 80, 0.055, 0.056, 0.072),
        ((0.095, 0.050), 90, 0.058, 0.048, 0.062),
        ((0.140, 0.048), 90, 0.060, 0.046, 0.058),
        ((0.176, 0.046), 90, 0.057, 0.043, 0.052),
        ((0.200, 0.042), 90, 0.047, 0.034, 0.046),
    ]
    n = 10

    def w_at(pos):
        toe = smooth((pos.y - 0.085) / 0.07)
        shin = max(smooth((pos.z - 0.10) / 0.10) * (1 - smooth((pos.y - 0.03) / 0.05)), smooth((pos.z - 0.13) / 0.08))
        return blend(("J_Bip_L_LowerLeg", shin), ("J_Bip_L_Foot", (1 - shin) * (1 - toe)), ("J_Bip_L_ToeBase", (1 - shin) * toe))

    made = []
    for (cy, cz), tilt, rx, rf, rb in rings:
        a = math.radians(tilt)
        e2 = Vector((0, math.cos(a), math.sin(a)))
        idx = ring(part, (x0, cy, cz), (1, 0, 0), e2, rx + d, rf + d, n, {}, p=0.9, r2b=rb + d)
        for i in idx:
            part.co[i].z = max(part.co[i].z, 0.0)
            part.w[i] = w_at(part.co[i])
        made.append(idx)
    for r in range(len(made) - 1):
        part.band(made[r], made[r + 1], r, r + 1, tag=tag_fn("boot", 0, r))
    tip = part.v((x0, 0.212, 0.036), {"J_Bip_L_ToeBase": 1.0})
    part.fan(made[-1], tip, len(made), tag=tag_fn("boot", 0, len(made)))
    # The folded top: a band of its own round the shaft (outside, over the lip, down the lining),
    # since a folded surface shows its other side.
    shin = {"J_Bip_L_LowerLeg": 1.0}
    prev = None
    for j, (cz, dr) in enumerate([(0.398, 0.003), (0.400, 0.015), (0.470, 0.019), (0.490, 0.014), (0.492, 0.004), (0.488, -0.004), (0.440, -0.007)]):
        cur = ring(part, (x0, -0.004, cz), (1, 0, 0), (0, 1, 0), 0.068 + dr + d, 0.074 + dr + d, n, shin, p=0.9, r2b=0.072 + dr + d)
        if prev:
            part.band(prev, cur, j - 1, j, tag=tag_fn("fold", 0, j))
        prev = cur
    return part


# ---------------------------------------------------------------------------------------------
# The head. Its form is head_form.py's (a loft with the face's features as bumps, set by the
# face parameters); these place it on the neck and give the rest of the script its surface.

HEAD_SCALE = 1.08  # a little larger than life, as stylised figures are (configure() sets it from the style)
HEAD = Vector((0, -0.004, 1.535 + 0.131 * HEAD_SCALE))  # configure() keeps the chin at 1.535 m
ORIGIN = Vector(head_form.ORIGIN)  # rays leave from here (relative to HEAD)


def hw(p):
    """A point of the head's own frame (metres round its centre, unscaled) in the world."""
    return HEAD + Vector(p) * HEAD_SCALE


def head_radius(dirs):
    """Distance from ORIGIN to the head's surface along each unit direction."""
    return HF.radius(np.asarray(dirs, dtype=float))


def head_normal(p):
    return HF.normal(np.asarray(p, dtype=float))


def project_front(pts):
    """Points (x, z) of the face's front view onto the head's surface: N×3 positions (relative
    to HEAD) and normals."""
    return HF.project_front(pts)


def hairline(az):
    """The lowest height (relative to HEAD) hair grows at, by the angle round the head from the
    front (degrees, 0..180)."""
    r = RECEDE
    top = HF.top_z - 0.115
    return float(np.interp(abs(az), [0, 35, 62, 80, 92, 104, 125, 180], [0.080 + top + r, 0.076 + top + 1.3 * r, 0.052 + 0.6 * r, -0.004, 0.016, 0.010, -0.050, -0.078]))


# ---------------------------------------------------------------------------------------------
# Building Blender objects from cages.

_materials = {}


def material(name):
    if name in _materials:
        return _materials[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (1, 1, 1, 1)
    bsdf.inputs["Roughness"].default_value = 0.9
    m.use_backface_culling = True
    _materials[name] = m
    return m


def outward(bm):
    """Wind every connected piece so its faces look away from its own middle. Blender's own
    recalculation guesses wrong on open tubes (a boot came out inside-out)."""
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.normal_update()
    seen = set()
    for f0 in bm.faces:
        if f0 in seen:
            continue
        island, stack = [], [f0]
        seen.add(f0)
        while stack:
            f = stack.pop()
            island.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g not in seen:
                        seen.add(g)
                        stack.append(g)
        area = sum(f.calc_area() for f in island) or 1.0
        mid = sum((f.calc_center_median() * f.calc_area() for f in island), Vector()) / area
        if sum((f.calc_center_median() - mid).dot(f.normal) * f.calc_area() for f in island) < 0:
            bmesh.ops.reverse_faces(bm, faces=island)
    bm.normal_update()


def build(part, arm, mat, colour, levels=1, solid=0.0, post=None, materials=None):
    """Make a skinned object from a cage: subdivide, drop hidden faces, thicken, colour.

    colour(tag, u, v, co, normal) -> sRGB; it is called per face corner with the face's tag and
    mean ring parameters, so a tag's edge is a crisp colour edge. `materials`: tag -> material
    name for parts with more than one."""
    me = bpy.data.meshes.new(part.name)
    bm = bmesh.new()
    vs = [bm.verts.new(c) for c in part.co]
    uvl = bm.loops.layers.uv.new("param")
    for idx, uvs, tag in zip(part.faces, part.fuv, part.tags):
        try:
            f = bm.faces.new([vs[i] for i in idx])
        except ValueError:
            continue
        f.material_index = tag
        f.smooth = True
        for l, uv in zip(f.loops, uvs):
            l[uvl].uv = uv
    outward(bm)
    bm.to_mesh(me)
    bm.free()
    for _ in range(32):
        me.materials.append(None)
    ob = bpy.data.objects.new(part.name, me)
    bpy.context.collection.objects.link(ob)
    groups = {}
    for i, w in enumerate(part.w):
        if not w:
            raise SystemExit(f"{part.name}: vertex {i} has no weights")
        for n, x in w.items():
            g = groups.get(n) or ob.vertex_groups.new(name=n)
            groups[n] = g
            g.add([i], x, "REPLACE")
    if levels:
        m = ob.modifiers.new("subdivide", "SUBSURF")
        m.levels = levels
        m.render_levels = levels
        m.uv_smooth = "NONE"
        m.boundary_smooth = "ALL"
    dg = bpy.context.evaluated_depsgraph_get()
    me2 = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    ob.modifiers.clear()
    ob.data = me2
    bpy.data.meshes.remove(me)
    me = me2
    # Drop the faces a cage marked hidden (under another garment).
    bm = bmesh.new()
    bm.from_mesh(me)
    gone = [f for f in bm.faces if f.material_index == Part.HIDE]
    if gone:
        bmesh.ops.delete(bm, geom=gone, context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    if post:
        post(bm)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    if solid:
        m = ob.modifiers.new("solid", "SOLIDIFY")
        m.thickness = solid
        m.offset = -1.0
        m.use_rim = True
        m.use_quality_normals = True
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        me2 = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        ob.modifiers.clear()
        ob.data = me2
        bpy.data.meshes.remove(me)
        me = me2
    paint(me, colour)
    # Materials: one, or one per tag.
    tags = [p.material_index for p in me.polygons]
    me.materials.clear()
    if materials:
        names = sorted(set(materials.values()), key=list(materials.values()).index)
        for n in names:
            me.materials.append(material(n))
        for p, t in zip(me.polygons, tags):
            p.material_index = names.index(materials.get(t, names[0]))
    else:
        me.materials.append(material(mat))
        for p in me.polygons:
            p.material_index = 0
    for p in me.polygons:
        p.use_smooth = True
    ob.parent = arm
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    return ob


def paint(me, colour):
    uvl = me.uv_layers.get("param")
    attr = me.color_attributes.new("Color", "FLOAT_COLOR", "CORNER")
    data = np.ones((len(me.loops), 4), dtype=np.float32)
    for p in me.polygons:
        tag = p.material_index
        us = [uvl.data[li].uv for li in p.loop_indices] if uvl else [(0, 0)]
        u = sum(x[0] for x in us) / len(us)
        v = sum(x[1] for x in us) / len(us)
        for li in p.loop_indices:
            vert = me.vertices[me.loops[li].vertex_index]
            data[li, :3] = lin(colour(tag, u, v, vert.co, p.normal))
    attr.data.foreach_set("color", data.ravel())
    me.color_attributes.active_color = attr
    me.color_attributes.render_color_index = me.color_attributes.active_color_index


def raw_object(name, verts, faces, weights, colours, mat, arm, uvs=None, smooth_shade=True, materials=None, face_mats=None, orient=False):
    """A skinned object from explicit geometry with per-vertex sRGB colours (no subdivision)."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.update()
    if orient:
        bm = bmesh.new()
        bm.from_mesh(me)
        outward(bm)
        bm.to_mesh(me)
        bm.free()
    attr = me.color_attributes.new("Color", "FLOAT_COLOR", "CORNER")
    data = np.ones((len(me.loops), 4), dtype=np.float32)
    for l in me.loops:
        data[l.index, :3] = lin(colours[l.vertex_index])
    attr.data.foreach_set("color", data.ravel())
    me.color_attributes.active_color = attr
    me.color_attributes.render_color_index = me.color_attributes.active_color_index
    if uvs is not None:
        uvl = me.uv_layers.new(name="UVMap")
        for l in me.loops:
            uvl.data[l.index].uv = uvs[l.vertex_index]
    if materials:
        for n in materials:
            me.materials.append(material(n))
        for p, m in zip(me.polygons, face_mats):
            p.material_index = m
    else:
        me.materials.append(material(mat))
    for p in me.polygons:
        p.use_smooth = smooth_shade
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    groups = {}
    for i, w in enumerate(weights):
        for n, x in w.items():
            g = groups.get(n) or ob.vertex_groups.new(name=n)
            groups[n] = g
            g.add([i], x, "REPLACE")
    ob.parent = arm
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    return ob


# ---------------------------------------------------------------------------------------------
# Head, face, neck.


def make_face(arm, spec, atlas_path):
    """The head's skin with its eye openings and mouth slit, the eyes, lashes, lid lines, brows,
    the mouth's inside and the ears (head_mesh.py), as one object `Face` with the expressions as
    shape keys under VRoid's names (the game drives `Fcl_EYE_Close` and `Fcl_MTH_A`), and the
    painted atlas (face_paint.py) on the skin and the eyes. Returns the object and the whole
    head's surface (positions relative to HEAD, quads) for hair, beards and headwear."""
    look = spec["look"]
    # The scalp is dropped where the hair's cap covers it (well inside the hairline).
    face = head_mesh.Face(HF, look, keep=lambda c: c[2] < hairline(az_of(c)) + 0.016 or bald_depth(c) > -0.012)
    m = face.mesh
    # The iris shares the eye's material (the atlas); highlights are plain colour, as the lines are.
    fm = [dict(iris="eye", glint="line").get(k, k) for k in m.fm]
    order = [k for k in ("face", "eye", "line", "brow", "mouth") if k in set(fm)]
    base = np.array(HEAD)[None, :]
    world = base + np.array(m.v) * HEAD_SCALE
    eye_bone = {-1: "J_Adj_L_FaceEye", 1: "J_Adj_R_FaceEye"}
    weights = [{"J_Bip_C_Head": 1.0} if e is None else ({eye_bone[e[0]]: e[1], "J_Bip_C_Head": 1.0 - e[1]} if e[1] < 1 else {eye_bone[e[0]]: 1.0}) for e in m.eye]
    ob = raw_object("Face", world, m.f, weights, m.col, None, arm, uvs=m.uv, materials=[MAT[k] for k in order], face_mats=[order.index(k) for k in fm])
    ob.shape_key_add(name="Basis", from_mix=False)
    for name, delta in face.morphs.items():
        key = ob.shape_key_add(name=name, from_mix=False)
        key.data.foreach_set("co", (world + delta * HEAD_SCALE).ravel())
        # A new key starts at 1, and the file would say every expression is on.
        key.value = float(spec.get("expression", {}).get(name, 0.0))
    face_paint.write_png(atlas_path, face_paint.paint(HF, look))
    img = bpy.data.images.load(atlas_path)
    img.pack()
    for k in ("face", "eye"):
        mat = material(MAT[k])
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = img
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return ob, face.base_pos, face.base_quads


def make_neck(arm):
    part = Part("Neck")
    stations = [
        (1.440, -0.024, 0.060, blend(("J_Bip_C_UpperChest", 0.7), ("J_Bip_C_Neck", 0.3))),
        (1.490, -0.022, 0.054, {"J_Bip_C_Neck": 1.0}),
        (1.540, -0.019, 0.051, blend(("J_Bip_C_Neck", 0.75), ("J_Bip_C_Head", 0.25))),
        (1.590, -0.016, 0.050, blend(("J_Bip_C_Neck", 0.2), ("J_Bip_C_Head", 0.8))),
        (1.630, -0.012, 0.046, {"J_Bip_C_Head": 1.0}),
    ]
    prev = None
    for i, (z, cy, r, w) in enumerate(stations):
        cur = ring(part, (0, cy, z), (1, 0, 0), (0, 1, 0), r, r * 1.04, 10, w)
        if prev:
            part.band(prev, cur, i - 1, i)
        prev = cur
    return build(part, arm, MAT["skin"], lambda tag, u, v, co, n: mix(SKIN, SKIN_SHADE, 0.25 * smooth((1.56 - co.z) / 0.08)))


# ---------------------------------------------------------------------------------------------
# Hair.


def head_dir(az, el):
    a, e = math.radians(az), math.radians(el)
    return np.array([-math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)])


def region_shell(pos, quads, depth_of, snap, need=2):
    """The head's quads inside a region, for a shell over it (hair, a beard, a scarf, a cap).
    depth_of(p) is how far inside the region a point lies (metres; negative outside); vertices
    outside are slid onto the edge with snap(p), so the edge is a smooth line and the shell
    follows the skin. Returns positions (relative to HEAD), normals, depths and faces."""
    depth = [depth_of(p) for p in pos]
    index, new_pos, new_depth, faces = {}, [], [], []
    for q in quads:
        if sum(depth[i] > 0 for i in q) < need:
            continue
        idx = []
        for i in q:
            if i not in index:
                index[i] = len(new_pos)
                new_pos.append(np.array(pos[i]) if depth[i] > 0 else np.array(snap(pos[i])))
                new_depth.append(max(depth[i], 0.0))
            idx.append(index[i])
        faces.append(idx)
    new_pos = np.array(new_pos)
    return new_pos, head_normal(new_pos), new_depth, faces


def face_out(ob, centre=(0, 0, -0.03)):
    """Wind a shell on the head so its faces look away from the head's middle."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    c = hw(centre)
    flip = [f for f in bm.faces if f.normal.dot(f.calc_center_median() - c) < 0]
    if flip:
        bmesh.ops.reverse_faces(bm, faces=flip)
    bm.to_mesh(me)
    bm.free()
    return ob


def az_of(p):
    return math.degrees(math.atan2(-p[0], p[1]))


def snap_plane(p, depth_of):
    """Slide a point of the head along the surface until depth_of is zero (a few Newton steps
    on the direction from ORIGIN)."""
    p = np.array(p, dtype=float)
    o = np.array(ORIGIN)
    for _ in range(5):
        d0 = depth_of(p)
        if abs(d0) < 2e-4:
            break
        e = 2e-3
        g = np.array([(depth_of(p + np.array(v) * e) - d0) / e for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))])
        gg = float(g @ g)
        if gg < 1e-9:
            break
        p = p - g * d0 / gg
        d = (p - o) / np.linalg.norm(p - o)
        p = o + d * float(head_radius(d[None, :])[0])
    return p


def bald_depth(p):
    """How far inside a bald crown a point of the head lies (metres; negative outside): an
    ellipse seen from above, reaching from the forehead to the crown when BALD is 1."""
    if BALD <= 0.01 or p[2] < 0.025:
        return -1.0
    rx, ry = 0.060 * (0.55 + 0.45 * BALD), 0.086 * (0.5 + 0.5 * BALD)
    q = math.hypot(p[0] / rx, (p[1] - 0.022 * BALD) / ry)
    return (1 - q) * rx


def hair_depth(p):
    """How far inside the region hair grows on a point of the head lies."""
    return min(p[2] - (hairline(az_of(p)) - 0.002), -bald_depth(p))


def make_hair(arm, spec, pos, quads, covered=None):
    """Hair (hair.py): a cap on the scalp and layers of locks combed over it, textured with one
    shared picture of strands. Long locks hang from spring bones, which are added to the
    armature here. Returns the objects (hair, and ties in cloth)."""
    look = spec["look"]
    seed = spec["seed"]
    verts, faces, cols, uvs, weights = [], [], [], [], []
    # The cap: the scalp's own quads, pushed out; its edge is the hairline. It carries the same
    # strands, running out from the crown, so no skin shows between locks.
    if BALD > 0.01:
        cp, cn, cd, cf = region_shell(pos, quads, hair_depth, lambda p: snap_plane(p, hair_depth))
    else:
        line = lambda p: p[2] - (hairline(az_of(p)) - 0.002)
        cp, cn, cd, cf = region_shell(pos, quads, line, lambda p: head_point(az_of(p), hairline(az_of(p)) - 0.002))
    comb = hair.Comb(HF)
    whorl = comb.surface(180.0, 64.0)[0]
    wn = np.array(head_normal(whorl[None, :])[0])
    e1 = np.array([1.0, 0.0, 0.0]) - wn * wn[0]
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(wn, e1)
    reps = 5.0
    cap_c = np.array(HAIR) * 0.80 / hair.TEX_MEAN
    cap_uv = []
    for p_, n_, d_ in zip(cp, cn, cd):
        verts.append(hw(p_ + n_ * (0.0010 + 0.0050 * smooth(d_ / 0.02))))
        r = p_ - whorl
        # The seam runs down the back of the head, under the hair.
        ang = math.atan2(-(r @ e1), r @ e2) / (2 * PI) + 0.5
        cap_uv.append((ang * reps, 1.0 - min(np.linalg.norm(r) / 0.34, 0.97)))
        cols.append(tuple(np.clip(cap_c * (0.82 + 0.18 * smooth(d_ / 0.03)), 0, 1)))
    extra = {}
    for f in cf:
        us = [cap_uv[i][0] for i in f]
        g = list(f)
        if max(us) - min(us) > reps / 2:
            for k, i in enumerate(f):
                if cap_uv[i][0] < reps / 2:
                    if i not in extra:
                        extra[i] = len(verts)
                        verts.append(verts[i])
                        cols.append(cols[i])
                        cap_uv.append((cap_uv[i][0] + reps, cap_uv[i][1]))
                    g[k] = extra[i]
        faces.append(g)
    uvs += cap_uv
    weights += [{"J_Bip_C_Head": 1.0}] * len(verts)
    # The cap's faces look away from the head.
    c0 = hw((0, 0, -0.03))
    for k, f in enumerate(faces):
        a, b, c = (Vector(verts[i]) for i in f[:3])
        if (b - a).cross(c - a).dot((a + b + c) / 3 - c0) < 0:
            faces[k] = list(reversed(f))
    # The locks.
    hs = dict(spec["hair"], colour=look["hair_natural"], tip=look["hair_natural_tip"], silver=look["hair_silver"], grey=look["hair_grey"], seed=seed)
    hd = lambda z: (z - HEAD.z) / HEAD_SCALE
    collar = dict(coat=0.090, smock=0.068).get(spec["coat"], 0.064)
    body = dict(neck_r=collar / HEAD_SCALE, neck_y=(-0.018 - HEAD.y) / HEAD_SCALE, neck_top=HF.chin_z + 0.022, shoulder_z=hd(1.468 + (0.030 if spec["coat"] else 0.014)),
                half_w=(0.182 * GIRTH + 0.035) / HEAD_SCALE, half_d=(0.108 * GIRTH + 0.035) / HEAD_SCALE, torso_y=(0.0 - HEAD.y) / HEAD_SCALE, round=0.05 / HEAD_SCALE)
    h = hair.Hair(HF, hs, hairline, covered=covered, bald=bald_depth, body=body)
    base = len(verts)
    names = add_spring_bones(arm, h.chains)
    for p_, c_, uv_, ch, al in zip(h.v, h.col, h.uv, h.chain, h.along):
        verts.append(hw(p_))
        cols.append(tuple(c_))
        uvs.append(tuple(uv_))
        weights.append(chain_weights(names[ch], h.chains[ch]["step"] * HEAD_SCALE, al * HEAD_SCALE) if ch >= 0 and names.get(ch) else {"J_Bip_C_Head": 1.0})
    lock_faces = [tuple(base + i for i in f) for f in h.f]
    ob = raw_object("Hair", verts, faces + lock_faces, weights, cols, MAT["hair"], arm, uvs=uvs)
    orient_islands(ob, skip=len(faces))
    # Shading normals: the cap's are the head's, the locks' their own (hair.py).
    normals = [tuple(head_normal(np.array(p_)[None, :])[0]) for p_ in cp] + [None] * len(extra)
    for i, k in extra.items():
        normals[k] = normals[i]
    normals += [tuple(n_) for n_ in h.nrm]
    ob.data.normals_split_custom_set_from_vertices(normals)
    # The strands' picture, the same for everyone.
    path = STRANDS_PATH
    if not os.path.exists(path):
        face_paint.write_png(path, hair.paint_strands())
    img = bpy.data.images.load(path)
    img.pack()
    mat = material(MAT["hair"])
    if not any(n.type == "TEX_IMAGE" for n in mat.node_tree.nodes):
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = img
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    obs = [ob]
    # Ties: a band of cloth round a tail or a braid's end.
    for kind, d in h.extra:
        if kind != "tie":
            continue
        tv, tf, tc = [], [], []
        axis = np.array(d["axis"], float)
        a1 = np.cross(axis, [1.0, 0.0, 0.0])
        a1 /= np.linalg.norm(a1)
        a2 = np.cross(axis, a1)
        n = 10
        for i in range(n):
            a = 2 * PI * i / n
            for k, (dr, dz) in enumerate(((0.0, -0.006), (0.004, 0.0), (0.0, 0.006))):
                tv.append(hw(np.array(d["p"]) + (a1 * math.cos(a) + a2 * math.sin(a)) * (d["r"] + dr) + axis * dz))
                tc.append(mix(spec["headwear_colour"], (0, 0, 0), 0.10 + 0.10 * (k != 1)))
        for i in range(n):
            for k in range(2):
                a, b = 3 * i + k, 3 * ((i + 1) % n) + k
                tf.append((a, b, b + 1, a + 1))
        ch = d.get("chain", -1)
        w = chain_weights(names[ch], h.chains[ch]["step"] * HEAD_SCALE, d["along"] * HEAD_SCALE) if ch >= 0 and names.get(ch) else {"J_Bip_C_Head": 1.0}
        obs.append(raw_object("HairTie", tv, tf, [w] * len(tv), tc, MAT["coat"], arm, orient=True))
    spec["springs"] = [names[i] for i in sorted(names) if names[i]]
    return obs


def orient_islands(ob, skip=0):
    """Wind each closed lock so its faces look outward (the first `skip` faces are left)."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    seen = set(f.index for f in bm.faces[:skip])
    for f0 in bm.faces[skip:]:
        if f0.index in seen:
            continue
        island, stack = [], [f0]
        seen.add(f0.index)
        while stack:
            f = stack.pop()
            island.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        bmesh.ops.recalc_face_normals(bm, faces=island)
        vol = sum(f.calc_center_median().dot(f.normal) * f.calc_area() for f in island)
        if vol < 0:
            bmesh.ops.reverse_faces(bm, faces=island)
    bm.to_mesh(me)
    bm.free()


def add_spring_bones(arm, chains):
    """Chains of bones for hanging hair, under the head: `J_Sec_Hair<chain>_<joint>`. The game
    swings them (characters.rs, VRM spring bones); they are listed in the file's VRM block."""
    names = {}
    todo = [(i, c) for i, c in enumerate(chains) if len(c.get("joints") or []) >= 2]
    if not todo:
        return names
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    frame = Matrix.Rotation(math.radians(90), 4, "X")
    for i, c in todo:
        parent = arm.data.edit_bones["J_Bip_C_Head"]
        names[i] = []
        for j, p in enumerate(c["joints"]):
            n = f"J_Sec_Hair{i + 1}_{j + 1:02d}"
            eb = arm.data.edit_bones.new(n)
            eb.head = (0, 0, 0)
            eb.tail = (0, 0.04, 0)
            eb.matrix = Matrix.Translation(hw(p)) @ frame
            eb.parent = parent
            parent = eb
            names[i].append(n)
    bpy.ops.object.mode_set(mode="OBJECT")
    return names


def chain_weights(bones, step, along):
    """Weights of a vertex `along` metres down a spring chain whose joints are `step` apart:
    each stretch follows its own bone, shared half and half at a joint. Above the first joint
    it joins the head."""
    if along <= -0.03:
        return {"J_Bip_C_Head": 1.0}
    m = len(bones) - 1  # the last bone only marks the end
    f = along / step
    i = int(min(max(math.floor(f), 0), m - 1))
    t = f - i if f > 0 else 0.0
    w = {}
    here = bones[i]
    before = bones[i - 1] if i > 0 else "J_Bip_C_Head"
    if along < 0:
        k = smooth((along + 0.03) / 0.03) * 0.5
        return {"J_Bip_C_Head": 1 - k, bones[0]: k}
    if t < 0.5:
        k = 0.5 * (1 - smooth(t / 0.5))
        w[before] = k
        w[here] = 1 - k
    elif i < m - 1:
        k = 0.5 * smooth((t - 0.5) / 0.5)
        w[bones[i + 1]] = k
        w[here] = 1 - k
    else:
        w[here] = 1.0
    return {n: x for n, x in w.items() if x > 1e-4}


# ---------------------------------------------------------------------------------------------
# Headwear.


def kerchief_depth(p):
    """How far behind a kerchief's front edge a point of the head lies: the edge crosses the top
    of the head behind the fringe and comes down behind the ears to the nape."""
    return -((p[1] - 0.060) - 0.9 * (p[2] - 0.090)) / 1.345 if p[2] > -0.070 else -1.0


def make_kerchief(arm, pos, quads, colour):
    """A headscarf tied at the nape: a shell over the top and back of the head, a knot and two
    tails."""
    def depth(p):
        return min(kerchief_depth(p), (p[2] + 0.070) * 2)

    cp, cn, cd, cf = region_shell(pos, quads, depth, lambda p: snap_plane(p, depth))
    verts = [hw(p_ + n_ * (0.0045 + 0.0110 * smooth(d_ / 0.012))) for p_, n_, d_ in zip(cp, cn, cd)]
    cols = [mix(colour, (0, 0, 0), 0.22 * (1 - smooth(d_ / 0.012))) for d_ in cd]
    obs = [face_out(raw_object("Kerchief", verts, [list(f) for f in cf], [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["coat"], arm))]
    # The knot and tails.
    verts, cols, faces = [], [], []
    knot = Vector((0, -0.112, -0.060))
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=8, v_segments=5, radius=0.017)
    for v in bm.verts:
        verts.append(hw(knot + Vector((v.co.x * 1.3, v.co.y * 0.8, v.co.z))))
        cols.append(mix(colour, (0, 0, 0), 0.18))
    faces += [[v.index for v in f.verts] for f in bm.faces]
    bm.free()
    for side in (-1, 1):
        first = len(verts)
        n = 5
        for i in range(n + 1):
            t = i / n
            c = knot + Vector((side * (0.012 + 0.030 * t), -0.006 - 0.022 * t, -0.012 - 0.085 * t))
            w = 0.020 * (1 - 0.75 * t)
            for a in (-1, 1):
                verts.append(hw(c + Vector((a * w * 0.8, a * w * 0.3 * side, 0))))
                cols.append(mix(colour, (0, 0, 0), 0.12))
        for i in range(n):
            a = first + 2 * i
            faces.append([a, a + 1, a + 3, a + 2])
            faces.append([a + 2, a + 3, a + 1, a])
    obs.append(raw_object("KerchiefKnot", verts, faces, [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["coat"], arm))
    return obs


def cap_depth(p):
    return ((p[2] - 0.060) - 0.22 * p[1]) / 1.02


def make_cap(arm, pos, quads, colour):
    """A flat cloth cap: a low crown over the top of the head and a short peak."""
    cp, cn, cd, cf = region_shell(pos, quads, cap_depth, lambda p: snap_plane(p, cap_depth))
    verts, cols = [], []
    for p_, n_, d_ in zip(cp, cn, cd):
        q = p_ + n_ * (0.0060 + 0.0130 * smooth(d_ / 0.008))
        # The crown is flat and slopes forward.
        q[2] = min(q[2], 0.132 - 0.16 * max(q[1], 0.0))
        verts.append(hw(q))
        cols.append(mix(colour, (0, 0, 0), 0.25 * (1 - smooth(d_ / 0.010))))
    obs = [face_out(raw_object("Cap", verts, [list(f) for f in cf], [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["coat"], arm))]
    # The peak: out from the front edge, two-sided.
    verts, cols, faces = [], [], []
    azs = [-62 + 124 * i / 12 for i in range(13)]
    for a in azs:
        e = snap_plane(head_point(a, 0.075), cap_depth)
        n = head_normal(e[None, :])[0]
        e = e + n * 0.0065
        reach = 0.062 * math.cos(math.radians(a * 1.35)) ** 0.8
        out = np.array([-math.sin(math.radians(a)) * 0.55, 1.0, -0.20])
        out /= np.linalg.norm(out)
        for k in (0.0, 0.55, 1.0):
            verts.append(hw(e + out * reach * k))
            cols.append(mix(colour, (0, 0, 0), 0.30))
    for i in range(len(azs) - 1):
        for r in range(2):
            a, b = 3 * i + r, 3 * (i + 1) + r
            faces.append([a, a + 1, b + 1, b])
            faces.append([b, b + 1, a + 1, a])
    obs.append(raw_object("CapPeak", verts, faces, [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["coat"], arm))
    return obs


def head_point(az, z):
    """The point of the head's surface at angle az round it (degrees from the front, + toward
    the character's left) and height z (relative to HEAD), with its normal."""
    el = math.degrees(math.asin(max(min((z - ORIGIN.z) / 0.09, 0.99), -0.99)))
    for _ in range(6):
        d = head_dir(az, el)
        r = float(head_radius(d[None, :])[0])
        el = math.degrees(math.asin(max(min((z - ORIGIN.z) / r, 0.999), -0.999)))
    p = np.array(ORIGIN) + head_dir(az, el) * r
    return p


def make_buttons(arm):
    """Horn toggles down the coat's left front edge."""
    verts, faces, cols, weights = [], [], [], []
    for z in (1.36, 1.24, 1.12, 1.00):
        edge = lerp(0.058, 0.026, smooth((z - 0.70) / 0.75))
        p = torso_point(z, 1, 0.024, 1.0, edge=edge + 0.020)
        nrm = Vector((-0.25, 1, 0)).normalized()
        e1 = Vector((1, 0.25, 0)).normalized()
        e2 = Vector((0, 0, 1))
        first = len(verts)
        w = torso_w(z, p.x)
        for k in range(8):
            a = 2 * PI * k / 8
            verts.append(p + nrm * 0.000 + (e1 * math.cos(a) + e2 * math.sin(a)) * 0.014)
            verts.append(p + nrm * 0.014 + (e1 * math.cos(a) + e2 * math.sin(a)) * 0.011)
        verts.append(p + nrm * 0.016)
        n = len(verts) - first
        cols += [mix(PAL["peat"], PAL["driftwood"], 0.35)] * n
        weights += [w] * n
        for k in range(8):
            a, b = first + 2 * k, first + 2 * ((k + 1) % 8)
            faces.append((a, b, b + 1, a + 1))
            faces.append((a + 1, b + 1, first + 16))
    return raw_object("Buttons", verts, faces, weights, cols, MAT["coat"], arm, orient=True)


# ---------------------------------------------------------------------------------------------
# Hands.


def make_hand(part):
    """The left hand's cage: palm, four fingers and thumb. Finger tubes start inside the palm."""
    hand = {"J_Bip_L_Hand": 1.0}
    y0, z0 = ARM_Y, ARM_Z
    stations = [
        (0.045, 0.000, 0.0265, 0.0215, {"J_Bip_L_LowerArm": 1.0}),
        (0.000, 0.000, 0.0280, 0.0195, blend(("J_Bip_L_LowerArm", 0.5), ("J_Bip_L_Hand", 0.5))),
        (-0.028, 0.003, 0.0370, 0.0170, hand),
        (-0.062, 0.003, 0.0440, 0.0155, hand),
        (-0.092, 0.001, 0.0440, 0.0135, hand),
        (-0.101, 0.001, 0.0400, 0.0100, hand),
    ]
    stations = stations[:2] + [(dx * HAND_K, dy * HAND_K, hy * HAND_K, hz * HAND_K * 1.08, w) for dx, dy, hy, hz, w in stations[2:]]
    prev = None
    for i, (dx, dy, hy, hz, w) in enumerate(stations):
        cur = ring(part, (WRIST_X + dx, y0 + dy, z0), (0, 1, 0), (0, 0, 1), hy, hz, 8, w, p=0.62)
        if prev:
            part.band(prev, cur, i - 1, i)
        prev = cur
    cap = part.v((WRIST_X - 0.104 * HAND_K, y0, z0), hand)
    part.fan(prev, cap, len(stations))

    def tube(root, axis, e1, e2, lens, r, names, base_w):
        total = sum(lens)
        j1, j2 = lens[0], lens[0] + lens[1]
        b1, b2, b3 = names
        st = [
            (-0.016, 1.00, blend((base_w, 0.7), (b1, 0.3))),
            (0.004, 1.02, {b1: 1.0}),
            (j1 - 0.006, 0.98, blend((b1, 0.8), (b2, 0.2))),
            (j1 + 0.006, 0.97, blend((b1, 0.2), (b2, 0.8))),
            (j2 - 0.005, 0.93, blend((b2, 0.8), (b3, 0.2))),
            (j2 + 0.005, 0.92, blend((b2, 0.2), (b3, 0.8))),
            (total - 0.010, 0.90, {b3: 1.0}),
            (total - 0.002, 0.60, {b3: 1.0}),
        ]
        prev = None
        for i, (s, k, w) in enumerate(st):
            cur = ring(part, root + axis * s, e1, e2, r * k, r * k * 0.92, 6, w)
            if prev:
                part.band(prev, cur, i - 1, i, tag=1 if i == len(st) - 1 else 0)
            prev = cur
        tip = part.v(root + axis * (total + 0.0025), {b3: 1.0})
        part.fan(prev, tip, len(st), tag=1)

    for name, ((kx, ky), lens, r) in FINGERS.items():
        root = Vector((WRIST_X + kx, y0 + ky, z0 - 0.001))
        tube(root, Vector((-1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)), lens, r, [f"J_Bip_L_{name}{i}" for i in (1, 2, 3)], "J_Bip_L_Hand")
    e1 = THUMB_DIR.cross(Vector((0, 0, 1))).normalized()
    e2 = e1.cross(THUMB_DIR).normalized()
    tube(THUMB_ROOT, THUMB_DIR, e1, e2, THUMB_LEN, THUMB_R, [f"J_Bip_L_Thumb{i}" for i in (1, 2, 3)], "J_Bip_L_Hand")
    return part


# ---------------------------------------------------------------------------------------------
# The man.


def jersey_colour(base):
    def colour(tag, u, v, co, n):
        # Knit: ribs round the torso and sleeves; tighter, darker ribbing at collar, cuffs and hem.
        rib = int(math.floor(u * (80 if tag in (2, 3) else 40) + 0.5)) % 2
        c = mix(base, (0, 0, 0), 0.16 * rib)
        if tag in (2, 3):
            c = mix(c, (0, 0, 0), 0.12)
        return mottle(c, co, 0.06)

    return colour


def coat_colour(base, patches):
    def colour(tag, u, v, co, n):
        c = base
        # Wet and tarred toward the hem; salt-faded on the shoulders.
        c = mix(c, PAL["kelp"], 0.40 * smooth((0.86 - co.z) / 0.2))
        c = mix(c, PAL["old_lime"], 0.16 * smooth((co.z - 1.40) / 0.08))
        if tag in (4, 5, 6):  # patches: other cloth, never matching
            c = patches[tag - 4]
        elif tag == 7:  # collar lining
            c = mix(PAL["kelp"], PAL["tar"], 0.3)
        elif tag == 8:  # an apron
            c = mix(PAL["old_lime"], PAL["driftwood"], 0.15 + 0.25 * smooth((0.75 - co.z) / 0.3))
        elif tag == 9:  # its band
            c = mix(PAL["old_lime"], PAL["driftwood"], 0.6)
        return mottle(c, co, 0.09)

    return colour


# A woman's torso (a man's is TORSO): a narrower waist and shoulders, fuller hips and chest.
MAN_TORSO = TORSO
WOMAN_TORSO = [
    (0.70, 0.150, 0.105, 0.000),
    (0.86, 0.156, 0.108, 0.000),
    (0.93, 0.172, 0.116, -0.006),
    (1.00, 0.160, 0.110, -0.004),
    (1.08, 0.132, 0.093, 0.002),
    (1.16, 0.130, 0.093, 0.008),
    (1.24, 0.140, 0.106, 0.014),
    (1.32, 0.150, 0.122, 0.018),
    (1.375, 0.158, 0.112, 0.004),
    (1.42, 0.162, 0.102, -0.006),
    (1.465, 0.164, 0.090, -0.008),
]


def configure(spec):
    """Set the generator's numbers for a person (person_params.resolve's result)."""
    g = globals()
    look = spec["look"]
    g.update(
        HF=head_form.Head(masc=spec["masc"], child=spec["child"], elder=spec["elder"], face=spec["face"], style=spec["style"]), HEAD_SCALE=spec["head_scale"], SKIN=look["skin"], SKIN_SHADE=look["skin_shade"], SKIN_WARM=look["skin_warm"],
        HAIR=look["hair"], HAIR_TIP=look["hair_tip"], RECEDE=spec["recede"], BALD=spec["bald"], LIMB_K=spec["limb"], GIRTH=spec["girth"], BELLY=spec["belly"], CHEST=spec["chest"], LONG=spec["hair_length"],
        TORSO=WOMAN_TORSO if spec["woman_torso"] else MAN_TORSO,
    )
    # The chin stays where the neck expects it, whatever the face's length.
    g["HEAD"] = Vector((0, -0.004, 1.535 - HF.chin_z * HEAD_SCALE))


def build_person(arm, spec, atlas_path, body=False):
    obs = []
    coat = spec["coat"]
    seed = spec["seed"]
    hem = max(spec["hem"], 0.50)
    if body:
        # The unclothed form the garments are offsets of (for inspection).
        p = upper_garment(Part("BodyTop"), 0.0, [0.94, 1.01, 1.08, 1.16, 1.24, 1.32], hem=[], cuff=(-0.705, []), collar=[(0.03, -0.006, {"J_Bip_C_Neck": 1.0})]).mirrored()
        obs.append(build(p, arm, MAT["skin"], lambda *a: SKIN))
        p = trousers(Part("BodyLegs"), 0.0, top=1.0, bottom=0.11).mirrored()
        obs.append(build(p, arm, MAT["skin"], lambda *a: SKIN))
    else:
        # Jersey: a roll neck, ribbed cuffs and hem. Under a coat only its front, collar and cuffs
        # are kept; under a smock its collar and cuffs.
        def jtag(kind, k, r):
            if kind in ("collar", "cuff"):
                return 2
            if kind == "hem":
                return Part.HIDE if coat == "smock" else 2
            if coat and kind in ("torso", "yoke") and (k >= 3 or coat == "smock"):
                return Part.HIDE
            if coat and kind == "sleeve" and r < 8:
                return Part.HIDE
            return 0

        neck = {"J_Bip_C_Neck": 1.0}
        p = upper_garment(
            Part("Jersey"), 0.008, [0.975, 1.01, 1.08, 1.16, 1.24, 1.32],
            hem=[(-0.030, 0.003), (-0.034, -0.006)], cuff=(-0.700, [(-0.012, 0.003), (-0.026, 0.003), (-0.028, -0.004)]),
            collar=[(0.022, -0.004, blend(("J_Bip_C_Neck", 0.8), ("J_Bip_C_UpperChest", 0.2))), (0.050, -0.002, neck), (0.058, -0.006, neck), (0.050, -0.012, neck)], tag_fn=jtag,
        ).mirrored()
        obs.append(build(p, arm, MAT["jersey"], jersey_colour(spec["jersey"])))
        chest = blend(("J_Bip_C_UpperChest", 0.75), ("J_Bip_C_Neck", 0.25))
        if coat == "coat":
            def ctag(kind, k, r):
                if kind == "collar":
                    return 7
                if kind == "sleeve" and r in (3, 4):
                    return 4  # elbow patches
                if kind == "torso" and k in (2, 3) and r in (1, 2):
                    return 5  # a patch on the skirt's front
                if kind == "torso" and k in (7, 8) and r in (4, 5):
                    return 6  # one on the back
                return 0

            p = upper_garment(
                Part("Coat"), 0.024, [0.70, 0.79, 0.88, 0.97, 1.06, 1.15, 1.24, 1.32],
                hem=[], cuff=(-0.640, [(-0.030, 0.006)]), collar=[(0.028, 0.012, chest), (0.060, 0.026, chest)],
                front=lambda z: lerp(0.058, 0.026, smooth((z - 0.70) / 0.75)), skirt=1.0, tag_fn=ctag,
            ).mirrored()
            obs.append(build(p, arm, MAT["coat"], coat_colour(spec["coat_colour"], spec["patches"]), solid=0.006))
            obs.append(make_buttons(arm))
        elif coat == "smock":
            # A pull-over smock to the knee, an apron tied over it.
            zs = [z for z in (0.50, 0.58, 0.66, 0.74, 0.82, 0.90, 0.98, 1.06, 1.13, 1.20, 1.26, 1.32) if z >= hem - 1e-6]
            band = zs.index(1.06)
            apron = spec["apron"]

            def stag(kind, k, r):
                if apron and kind == "torso" and r == band:
                    return 9
                if apron and kind == "torso" and k <= 2 and r < band:
                    return 8
                if kind == "sleeve" and r in (3, 4):
                    return 4
                return 0

            p = upper_garment(
                Part("Smock"), 0.018, zs, hem=[(-0.004, -0.008)], cuff=(-0.655, [(-0.022, 0.004), (-0.024, -0.004)]),
                collar=[(0.020, 0.006, chest), (0.022, -0.002, chest)], skirt=1.0, tag_fn=stag,
            ).mirrored()
            obs.append(build(p, arm, MAT["coat"], coat_colour(spec["coat_colour"], spec["patches"])))
        # Trousers, tucked into the boots.
        p = trousers(Part("Trousers"), 0.012).mirrored()
        obs.append(build(p, arm, MAT["trousers"], lambda tag, u, v, co, n: mottle(mix(PAL["iron"], PAL["slate"], 0.25 + 0.10 * (int(u * 44) % 2)), co, 0.08)))
        # Sea boots: tarred leather, a paler folded top, a dark sole.
        def boot_colour(tag, u, v, co, n):
            if co.z < 0.022:
                return (0.055, 0.05, 0.045)  # the sole
            if tag == 1:
                return mix(PAL["peat"], PAL["driftwood"], 0.22)
            return mottle(mix(PAL["tar"], PAL["peat"], 0.75 + 0.25 * smooth((co.z - 0.05) / 0.3)), co, 0.10)

        def flat_sole(bm):
            # A flat sole with a welt standing proud of the upper.
            for v in bm.verts:
                if v.co.z < 0.024 and v.co.y > -0.11:
                    side = -1 if v.co.x < 0 else 1
                    off = Vector((v.co.x - side * 0.092, v.co.y - 0.07, 0))
                    off.y *= 0.35
                    if off.length > 1e-5:
                        v.co += off.normalized() * 0.0045 * (1 if v.co.z < 0.016 else 0.4)
                if v.co.z < 0.006:
                    v.co.z = 0.0

        p = boot(Part("Boots"), tag_fn=lambda kind, k, r: 1 if kind == "fold" else 0).mirrored()
        obs.append(build(p, arm, MAT["boots"], boot_colour, post=flat_sole))
    # Hands.
    p = make_hand(Part("Hands")).mirrored()
    obs.append(build(p, arm, MAT["skin"], lambda tag, u, v, co, n: mix(SKIN, SKIN_WARM, 0.30) if tag == 1 else SKIN))
    # Head and face, neck, hair, beard, headwear.
    head, pos, quads = make_face(arm, spec, atlas_path)
    obs.append(head)
    obs.append(make_neck(arm))
    covered = dict(kerchief=lambda p: min(kerchief_depth(p), (p[2] + 0.070) * 2), cap=cap_depth).get(spec["headwear"])
    obs += make_hair(arm, spec, pos, quads, covered)
    if spec["headwear"] == "kerchief":
        obs += make_kerchief(arm, pos, quads, spec["headwear_colour"])
    elif spec["headwear"] == "cap":
        obs += make_cap(arm, pos, quads, spec["headwear_colour"])
    return obs


# ---------------------------------------------------------------------------------------------
# Painted shade: how closed-in each vertex is, multiplied into its colour.

AO_FLAT = ("Face",)  # the face shades others (the neck under the jaw) but takes none: its shade is painted
AO_SOFT = {"Neck": 0.7, "Hands": 0.6}


def bake_shade(obs, strength=0.50, reach=0.11):
    """Darken each vertex's colour by how much of the sky its neighbours hide in the rest pose
    (under the collar and the coat's skirt, inside cuffs, between the legs, under the fringe).
    The game lights with two flat bands, so this is the only soft shading the clothes get: the
    light painted into the colours, as the art direction asks."""
    from mathutils.bvhtree import BVHTree

    verts, polys = [], []
    for ob in obs:
        base = len(verts)
        verts += [v.co.copy() for v in ob.data.vertices]
        # Of the face only its skin shades others, not the lashes and brows standing off it.
        polys += [tuple(base + i for i in p.vertices) for p in ob.data.polygons if ob.name != "Face" or p.material_index == 0]
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=False)
    # A fixed fan of directions over the hemisphere, as (sideways, sideways, outward).
    fan = []
    for ring, (elev, count) in enumerate(((75, 4), (48, 7), (20, 9))):
        for k in range(count):
            a = 2 * PI * (k + 0.5 * ring) / count
            e = math.radians(elev)
            fan.append((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
    weight = sum(d[2] for d in fan)
    for ob in obs:
        if ob.name in AO_FLAT:
            continue
        me = ob.data
        k_ob = strength * AO_SOFT.get(ob.name, 1.0)
        shade = []
        for v in me.vertices:
            n = v.normal
            t = n.orthogonal().normalized()
            b = n.cross(t)
            o = v.co + n * 0.006
            hit = 0.0
            for dx, dy, dz in fan:
                d = t * dx + b * dy + n * dz
                h = tree.ray_cast(o, d, reach)
                if h[0] is not None:
                    hit += dz * (1.0 - 0.5 * h[3] / reach)
            shade.append(1.0 - k_ob * min(hit / weight, 1.0))
        attr = me.color_attributes["Color"]
        data = np.empty(len(me.loops) * 4, dtype=np.float32)
        attr.data.foreach_get("color", data)
        data = data.reshape(-1, 4)
        idx = np.empty(len(me.loops), dtype=np.int32)
        me.loops.foreach_get("vertex_index", idx)
        k = np.array(shade, dtype=np.float32)[idx]
        # Shade keeps a little warmth instead of going to grey.
        data[:, 0] *= k ** 0.90
        data[:, 1] *= k
        data[:, 2] *= k ** 1.05
        attr.data.foreach_set("color", data.ravel())


# ---------------------------------------------------------------------------------------------
# Export.

LOOK_RANGE = 6.0  # degrees an eye's bone turns for a look fully to one side

HUMAN = {
    "hips": "J_Bip_C_Hips", "spine": "J_Bip_C_Spine", "chest": "J_Bip_C_Chest", "upperChest": "J_Bip_C_UpperChest", "neck": "J_Bip_C_Neck",
    "head": "J_Bip_C_Head", "leftShoulder": "J_Bip_L_Shoulder", "leftUpperArm": "J_Bip_L_UpperArm", "leftLowerArm": "J_Bip_L_LowerArm",
    "leftHand": "J_Bip_L_Hand", "leftUpperLeg": "J_Bip_L_UpperLeg", "leftLowerLeg": "J_Bip_L_LowerLeg", "leftFoot": "J_Bip_L_Foot",
    "leftToes": "J_Bip_L_ToeBase",
}


def secondary(nodes, springs):
    """VRM 0.x spring bones for hanging hair, with spheres on the head, neck and shoulders it
    must not pass through. Offsets are in each bone's own frame (the file's axes: Y up, the
    character facing -Z), which is how the game reads them (characters.rs)."""
    if not springs:
        return {"boneGroups": [], "colliderGroups": []}

    def sphere(bone, at, r):
        j = JOINTS[bone]
        return {"offset": {"x": at[0] - j[0], "y": at[2] - j[2], "z": -(at[1] - j[1])}, "radius": r}

    # Smaller than the head, neck and shoulders themselves: the hair at rest lies on those, and
    # a sphere that reached it would push it off them.
    hc = HEAD + Vector((0, -0.010, 0.012)) * HEAD_SCALE
    colliders = [
        {"node": nodes["J_Bip_C_Head"], "colliders": [sphere("J_Bip_C_Head", hc, 0.074 * HEAD_SCALE), sphere("J_Bip_C_Head", hc + Vector((0, 0.014, -0.070)) * HEAD_SCALE, 0.046 * HEAD_SCALE)]},
        {"node": nodes["J_Bip_C_Neck"], "colliders": [sphere("J_Bip_C_Neck", (0, -0.018, 1.52), 0.040)]},
        {"node": nodes["J_Bip_C_UpperChest"], "colliders": [sphere("J_Bip_C_UpperChest", (0, -0.005, 1.32), 0.105 * GIRTH), sphere("J_Bip_C_UpperChest", (-0.12, -0.012, 1.385), 0.055),
                                                             sphere("J_Bip_C_UpperChest", (0.12, -0.012, 1.385), 0.055)]},
    ]
    # Stiff enough to settle within half a second of a jump in pose (the asset view photographs
    # 0.6 s after posing), loose enough to swing in a walk.
    groups = [{"comment": "Hair", "stiffiness": 2.0, "gravityPower": 0.10, "gravityDir": {"x": 0, "y": -1, "z": 0}, "dragForce": 0.5, "center": -1, "hitRadius": 0.010,
               "bones": [nodes[chain[0]] for chain in springs], "colliderGroups": [0, 1, 2]}]
    return {"boneGroups": groups, "colliderGroups": colliders}


def add_vrm(path, title, springs=None):
    """Mark the file as a VRM 0.x humanoid (plain JSON in the GLB's extensions), with the
    expressions' groups under VRM's preset names."""
    b = open(path, "rb").read()
    jl = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20 : 20 + jl])
    rest = b[20 + jl :]
    nodes = {n.get("name"): i for i, n in enumerate(j["nodes"])}
    bones = [{"bone": "leftEye", "node": nodes["J_Adj_L_FaceEye"], "useDefaultValues": True}, {"bone": "rightEye", "node": nodes["J_Adj_R_FaceEye"], "useDefaultValues": True}]
    for k, n in HUMAN.items():
        bones.append({"bone": k, "node": nodes[n], "useDefaultValues": True})
        if k.startswith("left"):
            bones.append({"bone": "right" + k[4:], "node": nodes[mirror_name(n)], "useDefaultValues": True})
    groups = []
    for mi, mesh in enumerate(j["meshes"]):
        names = mesh.get("extras", {}).get("targetNames", [])
        if "Fcl_EYE_Close" not in names:
            continue
        presets = dict(a="Fcl_MTH_A", i="Fcl_MTH_I", u="Fcl_MTH_U", e="Fcl_MTH_E", o="Fcl_MTH_O", blink="Fcl_EYE_Close", blink_l="Fcl_EYE_Close_L", blink_r="Fcl_EYE_Close_R",
                       joy=("Fcl_EYE_Joy", "Fcl_MTH_Fun", "Fcl_BRW_Fun"), fun=("Fcl_MTH_Fun", "Fcl_BRW_Fun"), angry=("Fcl_BRW_Angry", "Fcl_MTH_Sorrow"), sorrow=("Fcl_BRW_Sorrow", "Fcl_MTH_Sorrow"))
        groups.append({"name": "Neutral", "presetName": "neutral", "binds": [], "materialValues": []})
        for preset, targets in presets.items():
            targets = (targets,) if isinstance(targets, str) else targets
            groups.append({"name": preset.capitalize(), "presetName": preset, "binds": [{"mesh": mi, "index": names.index(t), "weight": 100} for t in targets if t in names], "materialValues": []})
    j.setdefault("extensionsUsed", []).append("VRM")
    j.setdefault("extensions", {})["VRM"] = {
        "exporterVersion": "slop-art-online person.py",
        "specVersion": "0.0",
        "meta": {"title": title, "author": "Slop Art Online (generated by living/tools/blender/person.py)", "licenseName": "Other"},
        "humanoid": {"humanBones": bones},
        # The eyes turn by their bones; a few degrees crosses the whole eye (head_mesh.EYE_R).
        "firstPerson": {"firstPersonBone": nodes["J_Bip_C_Head"], "firstPersonBoneOffset": {"x": 0, "y": 0.06, "z": 0}, "meshAnnotations": [], "lookAtTypeName": "Bone",
                        **{k: {"curve": [0, 0, 0, 1, 1, 1, 1, 0], "xRange": 90, "yRange": LOOK_RANGE} for k in ("lookAtHorizontalInner", "lookAtHorizontalOuter", "lookAtVerticalDown", "lookAtVerticalUp")}},
        "blendShapeMaster": {"blendShapeGroups": groups},
        "secondaryAnimation": secondary(nodes, springs or []),
    }
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + len(rest)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(rest)
    return j


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    person_params.add_args(ap)
    ap.add_argument("--expression", default="", help="expressions the file starts with, to look at them: `Fcl_MTH_Fun=1,Fcl_BRW_Fun=1` (the game drives Fcl_EYE_Close and Fcl_MTH_A itself)")
    ap.add_argument("--look", default="", help="turn the eyes in the file, to look at it: `yaw,pitch` in degrees of the eyes' bones (about 6 is fully aside)")
    ap.add_argument("--body", action="store_true", help="the unclothed form instead of the clothes")
    ap.add_argument("--no-shade", action="store_true", help="leave out the painted shade (bake_shade)")
    ap.add_argument("--blend")
    a = ap.parse_args(argv)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    given = person_params.given_from_args(a)
    if not given:
        given = person_params.from_variant("man")
    params = person_params.draw(given)
    spec = person_params.resolve(params)
    spec["expression"] = {k: float(v) for k, v in (x.split("=") for x in a.expression.split(",") if x)}
    unknown = set(spec["expression"]) - set(head_mesh.EXPRESSIONS)
    if unknown:
        raise SystemExit(f"--expression: {sorted(unknown)} not among {sorted(head_mesh.EXPRESSIONS)}")
    if a.look:
        spec["look"]["gaze"] = tuple(float(x) for x in a.look.split(","))
    configure(spec)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    stem = os.path.splitext(out)[0]
    # Beside the model: the person's full parameters (edit and pass back with --params) and the
    # game recipe's height and proportions.
    with open(stem + ".params.json", "w") as f:
        json.dump(dict(params=params, recipe=spec["recipe"]), f, indent=1)
    g = globals()
    g["STRANDS_PATH"] = os.path.join(os.path.dirname(out), "strands.png")
    arm = make_armature()
    obs = build_person(arm, spec, stem + ".atlas.png", body=a.body)
    if not a.no_shade:
        bake_shade(obs)
    tris = {}
    for ob in obs:
        ob.data.calc_loop_triangles()
        tris[ob.name] = len(ob.data.loop_triangles)
    if a.blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.blend))
    bpy.ops.export_scene.gltf(
        filepath=out, export_format="GLB", export_yup=True, export_skins=True, export_animations=False, export_vertex_color="ACTIVE",
        export_all_vertex_colors=False, export_normals=True, export_materials="EXPORT", export_def_bones=False, export_leaf_bone=False,
        export_rest_position_armature=True, use_selection=False, export_morph=True, export_morph_normal=False,
        export_try_sparse_sk=False,  # Bevy's loader rejects sparse morph accessors
    )
    j = add_vrm(out, f"Cullet resident {params['seed']} ({params['sex']}, {params['age']:.0f})", spec.get("springs"))
    zs = [v.co.z for ob in obs for v in ob.data.vertices]
    print(f"PERSON {out}: {params['sex']} {params['age']:.0f}y seed {params['seed']}, {sum(tris.values())} triangles, {len(arm.data.bones)} bones, {len(j['materials'])} materials, "
          f"{len(j.get('images', []))} texture, height {max(zs) - min(zs):.3f} m, floor {min(zs):+.4f}")
    print("PERSON parts: " + ", ".join(f"{k} {v}" for k, v in tris.items()))


if __name__ == "__main__":
    main()
