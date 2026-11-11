"""A person made wholly by script: body form, face, hands, hair and clothes on the J_Bip skeleton.

Spike (branch char-spike, 2026-11-11): can the game's characters come from our own Blender
scripts, with no VRoid Studio base? This builds one adult man of Cullet (docs/SMALL_CITY.md): a
knitted jersey, a patched oilskin coat, wool trousers and sea boots.

Run headless:
    blender -b -P living/tools/blender/person.py -- --out living/game/assets/lookdev/own-man.glb \
        [--blend man.blend] [--seed 3] [--no-coat] [--body]

The output follows the conventions the VRoid bases brought, so the rest of the pipeline is
unchanged (animate.py, merge_primitives.py, face_normals.py, characters.rs, lookdev.rs):
- metres, the sole on the floor, the character facing glTF -Z (Blender +Y), its left at -X;
- the `J_Bip_*` skeleton in a T-pose with identity rest rotations under a `Root` bone, so
  animate.py retargets the Kimodo library onto it unchanged;
- material names carry VRoid's group tags: `…Face_00_SKIN` (the face: face_normals.py flattens
  its normals and writes its shadow map from TEXCOORD_0), `…Body_00_SKIN`, `…_EYE`, `…_FACE`,
  `…_HAIR`, and `…Tops…`, `…Bottoms…`, `…Shoes…`, `…Coat…` `_CLOTH`, which is how the game picks
  the toon shading kind and the recipe colour slot;
- an `extensions.VRM` block (VRM 0.x: meta, humanoid bones, empty spring groups), which is how
  the game recognises a character file. It is written here as plain JSON; nothing of VRoid's is
  used.

How it is made:
- **Colour** is per face corner (COLOR_0) on white materials, as for the environment kits and the
  outfit pieces. There are no textures.
- **Clothes and limbs** are low cages lofted from rings (a superellipse torso, tubes for arms,
  legs and boots) with the weights written ring by ring, mirrored, then subdivided once
  (Catmull-Clark carries weights and the ring parameters). Garments are the body's form plus an
  offset, so layers share their weights and move together.
- **The head** is a cube-sphere projected radially onto a signed distance field (cranium, face,
  jaw, chin, cheekbones, brow, nose, lips), denser toward the face. Eyes, lashes, brows and the
  mouth are thin shells laid on that surface, as VRoid's are.
- **Hair** is a cap over the scalp and tapered locks that follow the head's surface.
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

PI = math.pi


def lin(c):
    """sRGB (0..1) to linear."""
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c[:3])


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def lerp(a, b, t):
    return a + (b - a) * t


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
# Cullet's palette (docs/SMALL_CITY.md, sRGB) and this man's colours.

PAL = dict(
    basalt=(0.24, 0.25, 0.28), old_lime=(0.78, 0.77, 0.71), slate=(0.30, 0.34, 0.40), tar=(0.13, 0.12, 0.12),
    driftwood=(0.52, 0.50, 0.46), iron=(0.17, 0.17, 0.19), rust=(0.50, 0.27, 0.15), mustard=(0.78, 0.60, 0.18),
    sea_green=(0.22, 0.45, 0.42), oxblood=(0.45, 0.14, 0.13), kelp=(0.30, 0.28, 0.12), peat=(0.20, 0.15, 0.11),
    chalk_blue=(0.50, 0.62, 0.72),
)
SKIN = (0.86, 0.66, 0.54)
SKIN_WARM = (0.80, 0.48, 0.40)
SKIN_SHADE = (0.66, 0.45, 0.37)
STUBBLE = (0.50, 0.42, 0.38)
HAIR = (0.115, 0.09, 0.08)
HAIR_TIP = (0.20, 0.155, 0.125)
IRIS = (0.34, 0.47, 0.56)

MAT = dict(
    face="M00_000_00_Face_00_SKIN", skin="M00_000_00_Body_00_SKIN", eye_white="M00_000_00_EyeWhite_00_EYE",
    iris="M00_000_00_EyeIris_00_EYE", highlight="M00_000_00_EyeHighlight_00_EYE", brow="M00_000_00_FaceBrow_00_FACE",
    line="M00_000_00_FaceEyeline_00_FACE", mouth="M00_000_00_FaceMouth_00_FACE", hair="M00_000_Hair_00_HAIR",
    jersey="M00_001_01_Tops_01_CLOTH", trousers="M00_001_01_Bottoms_01_CLOTH", boots="M00_001_01_Shoes_01_CLOTH",
    coat="M00_001_01_Coat_01_CLOTH",
)

# ---------------------------------------------------------------------------------------------
# The skeleton: an adult man, 1.78 m to the scalp. Blender axes: +Y forward, +Z up, left at -X.

ARM_Y, ARM_Z = -0.010, 1.420
WRIST_X = -0.715
JOINTS = {
    "Root": (0, 0, 0),
    "J_Bip_C_Hips": (0, 0.000, 0.985),
    "J_Bip_C_Spine": (0, 0.006, 1.060),
    "J_Bip_C_Chest": (0, 0.012, 1.180),
    "J_Bip_C_UpperChest": (0, 0.004, 1.310),
    "J_Bip_C_Neck": (0, -0.020, 1.475),
    "J_Bip_C_Head": (0, -0.010, 1.560),
    "J_Bip_L_Shoulder": (-0.025, -0.012, 1.435),
    "J_Bip_L_UpperArm": (-0.185, ARM_Y, ARM_Z),
    "J_Bip_L_LowerArm": (-0.465, ARM_Y, ARM_Z),
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
    (0.93, 0.166, 0.112, -0.004),
    (1.00, 0.158, 0.108, -0.002),
    (1.08, 0.144, 0.100, 0.004),
    (1.16, 0.147, 0.102, 0.008),
    (1.24, 0.155, 0.110, 0.010),
    (1.32, 0.163, 0.117, 0.008),
    (1.375, 0.166, 0.113, 0.000),
    (1.42, 0.168, 0.104, -0.006),
    (1.465, 0.168, 0.092, -0.008),
]
# A coat's skirt flares below the hips.
SKIRT = [(0.66, 0.050, 0.040), (0.80, 0.030, 0.026), (0.93, 0.008, 0.008), (1.00, 0.0, 0.0)]
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
SHOULDER = Vector((-0.170, -0.008, 1.420))  # the armhole's centre
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
    return Vector((-a * math.copysign(abs(s) ** p, s), cy + b * math.copysign(abs(c) ** p, c), z))


def arm_w(x):
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
        cur = ring(part, (x, ARM_Y, ARM_Z), (0, 1, 0), (0, 0, 1), ry + d, rz + d, 8, arm_w(x))
        part.band(prev, cur, n, n + 1, tag=tag_fn("sleeve", 0, n))
        prev = cur
        n += 1
    for dx, dd in cuff[1]:
        x = cuff[0] + dx
        ry, rz = table(ARM_X, x)
        cur = ring(part, (x, ARM_Y, ARM_Z), (0, 1, 0), (0, 0, 1), ry + d + dd, rz + d + dd, 8, arm_w(x))
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
        out.append(part.v((cx + (rx + d) * math.cos(th), cy + (ry + d) * math.sin(th), z), w))
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
# The head: a signed distance field, in metres round the head's centre.

HEAD_SCALE = 1.08  # a little larger than life, as stylised figures are
HEAD = Vector((0, -0.004, 1.535 + 0.131 * HEAD_SCALE))  # the chin stays at 1.535 m
ORIGIN = Vector((0, 0.0, -0.012))  # rays leave from here (relative to HEAD)


def hw(p):
    """A point of the head's own frame (metres round its centre, unscaled) in the world."""
    return HEAD + Vector(p) * HEAD_SCALE


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


def ell(p, c, r):
    q = (p - np.array(c)) / np.array(r)
    k0 = np.linalg.norm(q, axis=1)
    k1 = np.linalg.norm(q / np.array(r), axis=1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def sph(p, c, r):
    return np.linalg.norm(p - np.array(c), axis=1) - r


def capsule(p, a, b, ra, rb):
    a, b = np.array(a), np.array(b)
    ab = b - a
    t = np.clip(((p - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1) - (ra + (rb - ra) * t)


def head_sdf(p):
    """The man's head. p: N×3, relative to HEAD. Paired features are evaluated on |x|."""
    q = p.copy()
    q[:, 0] = np.abs(q[:, 0])
    d = ell(p, (0, -0.012, 0.022), (0.077, 0.097, 0.093))  # cranium
    d = smin(d, ell(p, (0, 0.018, -0.040), (0.067, 0.070, 0.080)), 0.022)  # face
    d = smin(d, ell(p, (0, 0.022, -0.090), (0.052, 0.058, 0.040)), 0.022)  # jaw
    d = smin(d, sph(q, (0.047, -0.004, -0.078), 0.024), 0.022)  # the jaw's corners
    d = smin(d, ell(p, (0, 0.064, -0.110), (0.027, 0.022, 0.021)), 0.016)  # chin
    d = smin(d, sph(q, (0.046, 0.050, -0.026), 0.024), 0.022)  # cheekbones
    d = smin(d, ell(p, (0, 0.074, 0.024), (0.060, 0.018, 0.013)), 0.014)  # brow
    d = -smin(-d, sph(q, (0.034, 0.108, 0.002), 0.020), 0.012)  # shallow eye sockets
    nose = capsule(p, (0, 0.082, 0.006), (0, 0.105, -0.040), 0.0075, 0.0115)
    nose = smin(nose, sph(q, (0.0115, 0.092, -0.0455), 0.0085), 0.006)
    d = smin(d, nose, 0.008)
    d = smin(d, ell(p, (0, 0.081, -0.0760), (0.022, 0.0065, 0.0085)), 0.010)  # lips
    return d


def head_radius(dirs):
    """Distance from ORIGIN to the head's surface along each unit direction."""
    o = np.array(ORIGIN)
    lo = np.full(len(dirs), 0.03)
    hi = np.full(len(dirs), 0.17)
    for _ in range(30):
        mid = (lo + hi) / 2
        inside = head_sdf(o + dirs * mid[:, None]) < 0
        lo = np.where(inside, mid, lo)
        hi = np.where(inside, hi, mid)
    return (lo + hi) / 2


def head_normal(p):
    e = 1e-4
    g = np.stack([head_sdf(p + np.array(v) * e) - head_sdf(p - np.array(v) * e) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))], axis=1)
    return g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-12)


def project_front(pts):
    """Points (x, z) of the face's front view onto the head's surface: N×3 positions (relative
    to HEAD) and normals."""
    pts = np.asarray(pts, dtype=float)
    lo = np.full(len(pts), -0.01)  # inside
    hi = np.full(len(pts), 0.15)  # in front of the face
    for _ in range(30):
        mid = (lo + hi) / 2
        p = np.stack([pts[:, 0], mid, pts[:, 1]], axis=1)
        inside = head_sdf(p) < 0
        lo = np.where(inside, mid, lo)
        hi = np.where(inside, hi, mid)
    p = np.stack([pts[:, 0], (lo + hi) / 2, pts[:, 1]], axis=1)
    return p, head_normal(p)


def hairline(az):
    """The lowest height (relative to HEAD) hair grows at, by the angle round the head from the
    front (degrees, 0..180)."""
    return float(np.interp(abs(az), [0, 35, 62, 80, 92, 104, 125, 180], [0.080, 0.076, 0.052, -0.004, 0.016, 0.010, -0.050, -0.078]))


def head_mesh(seed):
    """The head's skin: (verts relative to HEAD, quads, is-face flags)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=17, use_grid_fill=True)
    d = np.array([v.co[:] for v in bm.verts])
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    # More of the vertices go to the face.
    d = d + np.array([0.0, 0.52, -0.10])
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    r = head_radius(d)
    pos = np.array(ORIGIN) + d * r[:, None]
    quads = [[v.index for v in f.verts] for f in bm.faces]
    bm.free()
    return pos, quads


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
# Head, face parts, ears, neck.


def face_colour(p):
    """Skin colour at a point of the head (relative to HEAD): a little wind-burn on cheeks, nose
    and ears, a soft stubble shade on the jaw and lip, shade under the brow and jaw."""
    x, y, z = abs(p[0]), p[1], p[2]
    c = SKIN
    front = smooth((y - 0.01) / 0.04)
    cheek = math.exp(-(((x - 0.040) / 0.024) ** 2 + ((z + 0.032) / 0.022) ** 2)) * front
    nose = math.exp(-((x / 0.014) ** 2 + ((z + 0.036) / 0.018) ** 2)) * smooth((y - 0.05) / 0.03)
    c = mix(c, SKIN_WARM, 0.20 * cheek + 0.22 * nose)
    socket = math.exp(-(((x - 0.032) / 0.024) ** 2 + ((z - 0.012) / 0.010) ** 2)) * front
    c = mix(c, SKIN_SHADE, 0.30 * socket)
    # Stubble: the jaw, chin and upper lip, fading upward.
    jaw = smooth((-0.046 - z) / 0.045) * smooth((y + 0.02) / 0.04) * (0.55 + 0.45 * smooth((x - 0.012) / 0.03))
    lip = math.exp(-((x / 0.028) ** 2 + ((z + 0.062) / 0.009) ** 2)) * front
    c = mix(c, STUBBLE, min(0.34 * max(jaw, 0.9 * lip), 0.34))
    under = smooth((-0.118 - z) / 0.012) * smooth((0.06 - y) / 0.03)
    c = mix(c, SKIN_SHADE, 0.5 * under)
    return c


def face_uv(p):
    return (0.5 + p[0] / 0.20, 0.5 + p[2] / 0.30)


def make_head(arm, seed):
    pos, quads = head_mesh(seed)
    head_w = {"J_Bip_C_Head": 1.0}
    verts = [hw(p) for p in pos]
    centre = pos[np.array(quads)].mean(axis=1)
    # The face's skin is what looks forward, below the hair; the rest of the head is plain skin.
    is_face = (centre[:, 1] > 0.004)
    # Drop the scalp where the hair's cap covers it (well inside the hairline).
    keep = []
    for i, c in enumerate(centre):
        az = math.degrees(math.atan2(abs(c[0]), c[1]))
        keep.append(c[2] < hairline(az) + 0.016)
    faces = [q for q, k in zip(quads, keep) if k]
    fm = [0 if f else 1 for f, k in zip(is_face, keep) if k]
    colours = [face_colour(p) for p in pos]
    uvs = [face_uv(p) for p in pos]
    used = sorted({i for f in faces for i in f})
    remap = {i: n for n, i in enumerate(used)}
    ob = raw_object("Face", [verts[i] for i in used], [[remap[i] for i in f] for f in faces], [head_w] * len(used), [colours[i] for i in used], None, arm,
                    uvs=[uvs[i] for i in used], materials=[MAT["face"], MAT["skin"]], face_mats=fm)
    return ob, pos, quads


class Shells:
    """Thin shells laid on the face: each layer stands a little further off the skin."""

    def __init__(self):
        self.groups = {}
        self.extra = 0.0

    def add(self, mat, pts, faces, colours, layer, name=None):
        """pts: (x, z) in the face's front view; they are projected onto the head. `self.extra`
        is added to the shell's distance from the skin (a mouth over a beard)."""
        g = self.groups.setdefault(name or mat, dict(mat=mat, pts=[], faces=[], colours=[], layers=[]))
        layer = layer + self.extra / 0.0006
        base = len(g["pts"])
        g["pts"] += [tuple(p) for p in pts]
        g["faces"] += [tuple(base + i for i in f) for f in faces]
        g["colours"] += list(colours)
        g["layers"] += [layer] * len(pts)

    def strip(self, mat, top, bottom, colour, layer, colour_bottom=None, name=None):
        n = len(top)
        pts = list(top) + list(bottom)
        faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
        cols = [colour] * n + [colour_bottom or colour] * n
        self.add(mat, pts, faces, cols, layer, name)

    def objects(self, arm):
        out = []
        for key, g in self.groups.items():
            mat = g["mat"]
            p, nrm = project_front(g["pts"])
            off = np.array([0.0011 + 0.0006 * l for l in g["layers"]])
            p = p + nrm * off[:, None]
            verts = [hw(q) for q in p]
            name = key.split("_")[3] if key == mat else key
            ob = raw_object(name, verts, g["faces"], [{"J_Bip_C_Head": 1.0}] * len(verts), g["colours"], mat, arm, uvs=[face_uv(q) for q in p])
            # Faces must look outward (forward).
            me = ob.data
            flip = [poly.index for poly in me.polygons if poly.normal.y < 0]
            if flip:
                bm = bmesh.new()
                bm.from_mesh(me)
                bm.faces.ensure_lookup_table()
                bmesh.ops.reverse_faces(bm, faces=[bm.faces[i] for i in flip])
                bm.to_mesh(me)
                bm.free()
            out.append(ob)
        return out


EYE_X, EYE_Z = 0.0335, 0.002
EYE_W, EYE_UP, EYE_LO = 0.0180, 0.0100, 0.0062


def lid_up(s):
    """The upper lid's height above the eye's centre line at s in -1 (inner) .. 1 (outer)."""
    return EYE_UP * (1 - s * s) ** 0.62 * (1.0 + 0.10 * s) + 0.0012 * s


def lid_lo(s):
    return -EYE_LO * (1 - s * s) ** 0.80 + 0.0012 * s


def face_parts(sh, beard=False):
    dark = (0.10, 0.08, 0.08)
    brow_c = HAIR
    n = 15
    for side in (-1, 1):  # -1: the character's left eye (at -X)
        def at(s, dz):
            return (side * (EYE_X + EYE_W * s), EYE_Z + dz)

        ss = [-1 + 2 * i / (n - 1) for i in range(n)]
        # The white, shaded under the upper lid.
        top = [at(s, lid_up(s)) for s in ss]
        mid = [at(s, lerp(lid_lo(s), lid_up(s), 0.55)) for s in ss]
        bot = [at(s, lid_lo(s)) for s in ss]
        sh.strip(MAT["eye_white"], top, mid, (0.72, 0.70, 0.70), 0, (0.93, 0.92, 0.90))
        sh.strip(MAT["eye_white"], mid, bot, (0.93, 0.92, 0.90), 0, (0.90, 0.88, 0.86))
        # The iris: a disc cut by the lids, darker at the top; pupil above it.
        r = 0.0096
        cx, cz = side * (EYE_X - 0.0008), EYE_Z + 0.0008

        def cut(x, z, margin=0.0002):
            s = max(min((abs(x) - EYE_X) / EYE_W, 0.999), -0.999)
            return (x, min(max(z, EYE_Z + lid_lo(s) + margin), EYE_Z + lid_up(s) - margin))

        m = 20
        dark_i, light_i = mix(IRIS, (0.02, 0.03, 0.05), 0.72), mix(IRIS, (0.75, 0.90, 0.95), 0.30)
        pts, cols = [cut(cx, cz)], [mix(dark_i, IRIS, 0.6)]
        for k in range(m):
            a = 2 * PI * k / m
            for rr in (0.62, 1.0):
                z = cz + r * rr * math.sin(a)
                pts.append(cut(cx + r * rr * math.cos(a), z))
                t = smooth((cz + r * 0.55 - z) / (r * 1.5))
                c = mix(dark_i, light_i, t)
                cols.append(mix(c, dark_i, 0.55) if rr == 1.0 else c)
        faces = []
        for k in range(m):
            a, b = 1 + 2 * k, 1 + 2 * ((k + 1) % m)
            faces += [(0, a, b), (a, a + 1, b + 1, b)]
        sh.add(MAT["iris"], pts, faces, cols, 1)
        pr = r * 0.40
        pts = [cut(cx, cz)] + [cut(cx + pr * math.cos(2 * PI * k / 12), cz + pr * math.sin(2 * PI * k / 12)) for k in range(12)]
        sh.add(MAT["iris"], pts, [(0, 1 + k, 1 + (k + 1) % 12) for k in range(12)], [(0.03, 0.03, 0.04)] * 13, 2)
        # A highlight, up and toward the light (the same side in both eyes).
        hx, hz, hr = cx - 0.0034, cz + 0.0036, 0.0023
        pts = [cut(hx, hz)] + [cut(hx + hr * math.cos(2 * PI * k / 8), hz + hr * 0.85 * math.sin(2 * PI * k / 8)) for k in range(8)]
        sh.add(MAT["highlight"], pts, [(0, 1 + k, 1 + (k + 1) % 8) for k in range(8)], [(1.0, 1.0, 0.98)] * 9, 3)
        # The upper lash line, thickest toward the outer corner, with a short wing.
        s2 = [-1.02 + 2.2 * i / (n - 1) for i in range(n)]

        def lash(s):
            sc = min(max(s, -1), 1)
            z = lid_up(sc) + (0.0 if s <= 1 else -(s - 1) * 0.006)
            return at(s, z)

        th = [0.0010 + 0.0026 * smooth((s + 1.1) / 1.6) * (1.0 if s < 0.9 else max(0.25, 1 - (s - 0.9) / 0.35)) for s in s2]
        sh.strip(MAT["line"], [(lash(s)[0], lash(s)[1] + t) for s, t in zip(s2, th)], [(lash(s)[0], lash(s)[1] - 0.0005) for s in s2], dark, 4)
        # The lower lid: a thin line under the outer half.
        s3 = [0.0 + 0.95 * i / 7 for i in range(8)]
        sh.strip(MAT["line"], [at(s, lid_lo(s) + 0.0002) for s in s3], [at(s, lid_lo(s) - 0.0007) for s in s3], (0.36, 0.24, 0.20), 4)
        # The fold above the eye.
        s4 = [-0.75 + 1.6 * i / 9 for i in range(10)]
        sh.strip(MAT["line"], [at(s, lid_up(min(s, 0.99)) + 0.0050) for s in s4], [at(s, lid_up(min(s, 0.99)) + 0.0040) for s in s4], (0.45, 0.30, 0.25), 4)
        # The brow: heavy, low and nearly straight, tapering outward.
        bn = 12
        top, bot = [], []
        for i in range(bn):
            t = i / (bn - 1)
            x = lerp(0.0100, 0.0590, t)
            z = EYE_Z + 0.0190 + 0.0050 * math.sin(PI * min(t * 1.25, 1.0) * 0.72) - 0.0040 * max(t - 0.7, 0) / 0.3
            w = 0.0074 * (1 - 0.70 * t ** 1.6) * (0.75 + 0.25 * smooth(t / 0.12))
            top.append((side * x, z + w * 0.55))
            bot.append((side * x, z - w * 0.45))
        sh.strip(MAT["brow"], top, bot, brow_c, 2, mix(brow_c, (0, 0, 0), 0.15))
    # The mouth: a firm line, the lower lip as a soft tint, and its shadow on a bare chin.
    mn = 13
    top, bot = [], []
    for i in range(mn):
        t = -1 + 2 * i / (mn - 1)
        x = 0.0175 * t
        w = 0.0050 * (1 - abs(t) ** 2.2)
        top.append((x, -0.0755 - 0.0006 * t * t))
        bot.append((x, -0.0755 - 0.0006 * t * t - w))
    sh.strip(MAT["face"], top, bot, mix(SKIN, SKIN_WARM, 0.50), 0, mix(SKIN, SKIN_WARM, 0.22), name="Lip")
    top, bot = [], []
    for i in range(mn):
        t = -1 + 2 * i / (mn - 1)
        x = 0.0215 * t
        z = -0.0750 - 0.0009 * t * t + 0.0006 * math.cos(PI * t)
        w = 0.0015 * (1 - 0.7 * abs(t) ** 2)
        top.append((x, z + w))
        bot.append((x, z - w))
    sh.strip(MAT["mouth"], top, bot, (0.30, 0.15, 0.14), 1)
    if not beard:
        top, bot = [], []
        for i in range(7):
            t = -1 + 2 * i / 6
            x = 0.010 * t
            z = -0.0868 + 0.0010 * t * t
            w = 0.0010 * (1 - 0.8 * t * t)
            top.append((x, z + w))
            bot.append((x, z - w))
        sh.strip(MAT["face"], top, bot, SKIN_SHADE, 0)
    # Shade under the nose's tip and along one side of its bridge (anime noses are a shadow).
    sh.add(MAT["face"], [(-0.0085, -0.0500), (0.0085, -0.0500), (0.0055, -0.0535), (-0.0055, -0.0535)], [(0, 1, 2, 3)], [SKIN_SHADE] * 4, 0)
    top, bot = [], []
    for i in range(8):
        t = i / 7
        x = lerp(0.0068, 0.0105, t ** 1.5)
        z = lerp(-0.006, -0.043, t)
        w = 0.0011 * math.sin(PI * (0.15 + 0.85 * t)) + 0.0002
        top.append((x - w, z))
        bot.append((x + w, z))
    sh.strip(MAT["face"], top, bot, SKIN_SHADE, 0)


def make_ears(arm):
    obs = []
    for side in (-1, 1):
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=10, v_segments=6, radius=1.0)
        verts, cols = [], []
        tilt = Matrix.Rotation(math.radians(side * 24), 3, "Z") @ Matrix.Rotation(math.radians(-8), 3, "X")
        for v in bm.verts:
            p = Vector((v.co.x * 0.0075, v.co.y * 0.017, v.co.z * 0.031))
            # Wider at the top, a lobe at the bottom.
            p.y *= 1.0 + 0.25 * v.co.z
            inner = math.exp(-((v.co.y / 0.6) ** 2 + (v.co.z / 0.7) ** 2)) * (1.0 if v.co.x * side < 0 else 0.0)
            p = tilt @ p
            verts.append(hw(Vector((side * 0.0745, -0.010, -0.010)) + p))
            cols.append(mix(mix(SKIN, SKIN_WARM, 0.35), SKIN_SHADE, 0.6 * inner))
        faces = [[v.index for v in f.verts] for f in bm.faces]
        bm.free()
        ob = raw_object(f"Ear{'L' if side < 0 else 'R'}", verts, faces, [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["skin"], arm, orient=True)
        obs.append(ob)
    return obs


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


def make_hair(arm, seed, pos, quads):
    rng = random.Random(seed)
    verts, faces, cols = [], [], []
    # The cap: the scalp's own quads, pushed out.
    nrm = head_normal(pos)
    centre = pos[np.array(quads)].mean(axis=1)
    cap = {}
    for q, c in zip(quads, centre):
        az = math.degrees(math.atan2(abs(c[0]), c[1]))
        if c[2] < hairline(az) - 0.002:
            continue
        idx = []
        for i in q:
            if i not in cap:
                cap[i] = len(verts)
                p = pos[i] + nrm[i] * (0.0065 + 0.004 * smooth((pos[i][2] - 0.02) / 0.08))
                verts.append(hw(p))
                cols.append(mix(HAIR, (0, 0, 0), 0.25))
            idx.append(cap[i])
        faces.append(idx)

    def lock(az0, el0, az1, el1, w0, lift, tip_out=0.0, sweep=0.0, segs=7, shade=0.0, base=0.008):
        """A clump: a flat, tapering leaf that follows the head from one direction to another
        (degrees round the head from the front, + toward the character's left; degrees up),
        `lift` off the scalp along its middle and `tip_out` at its point."""
        ts = [i / segs for i in range(segs + 1)]
        dirs = np.array([head_dir(lerp(az0, az1, t) + sweep * math.sin(PI * t), lerp(el0, el1, t)) for t in ts])
        dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
        rad = head_radius(dirs)
        pts = [Vector(ORIGIN) + Vector(d) * (r + base + lift * math.sin(PI * min(t * 1.15, 1.0)) + tip_out * t * t) for t, d, r in zip(ts, dirs, rad)]
        first = len(verts)
        tone = rng.uniform(-0.10, 0.10) + shade
        across = (-1.0, -0.5, 0.0, 0.5, 1.0)
        for i, t in enumerate(ts[:-1]):
            tan = (pts[i + 1] - pts[max(i - 1, 0)]).normalized()
            out = Vector(dirs[i])
            side = tan.cross(out).normalized()
            out = side.cross(tan).normalized()
            w = w0 * (1 - t ** 2.4) * (0.72 + 0.28 * smooth(t / 0.3))
            th = 0.15 * w + 0.0015
            c = pts[i]
            col = mix(HAIR, HAIR_TIP, smooth(t * 1.1))
            col = mix(col, (0, 0, 0), -tone * 2) if tone < 0 else mix(col, HAIR_TIP, tone * 2)
            for a in across:
                verts.append(hw(c + side * (w / 2 * a) + out * (th * (1 - a * a) - (w / 2 * a) ** 2 / 0.17)))
                cols.append(mix(col, (0, 0, 0), 0.22 * abs(a)))
            verts.append(hw(c - out * th * 0.5))
            cols.append(mix(col, (0, 0, 0), 0.4))
        tip = len(verts)
        verts.append(hw(pts[-1]))
        cols.append(HAIR_TIP)
        nr = len(across) + 1
        for i in range(segs - 1):
            a, b = first + nr * i, first + nr * (i + 1)
            for k in range(nr):
                faces.append((a + k, a + (k + 1) % nr, b + (k + 1) % nr, b + k))
        a = first + nr * (segs - 1)
        for k in range(nr):
            faces.append((a + k, a + (k + 1) % nr, tip))

    u = rng.uniform
    # Under layer: the sides and back, hanging from mid-height to the hairline.
    for i in range(15):
        az = 52 + 256 * i / 14
        a = az if az <= 180 else az - 360
        low = math.degrees(math.asin(max(min(hairline(a) / 0.10, 1), -1)))
        lock(a + u(-4, 4), 42 + u(-5, 5), a + u(-3, 3) + (8 if a > 0 else -8) * (1 if abs(a) < 120 else 0), low - 6 + u(-4, 3), 0.058 + u(-0.005, 0.006), 0.006 + u(0, 0.003), 0.003, base=0.007)
    # Over layer: from the crown down over the under layer's roots, all round.
    for i in range(13):
        az = -180 + 360 * (i + 0.5) / 13
        if abs(az) < 40:
            continue
        lock(az * 0.9 + u(-8, 8), 82 + u(-4, 4), az + u(-6, 6), 22 + u(-8, 8), 0.060 + u(-0.006, 0.006), 0.007 + u(0, 0.004), 0.004 + u(0, 0.004), base=0.011, shade=0.03)
    # The fringe: from the crown forward, swept to the character's right, ending above the brows
    # at uneven lengths.
    for i in range(8):
        az = -60 + 120 * i / 7
        end = 37 + 7 * abs(az) / 60 + u(-3, 6)
        lock(az * 0.45 + 10 + u(-5, 5), 76 + u(-5, 5), az - 12 + u(-4, 4), end, 0.044 + u(-0.004, 0.008), 0.012 + u(0, 0.004), 0.005 + u(0, 0.003), sweep=-9, base=0.012)
    # A few tufts that break the outline.
    for az, el in ((150, 62), (-120, 66), (40, 70), (-30, 78)):
        lock(az + u(-10, 10), 84, az + u(-10, 10), el + u(-5, 5), 0.036, 0.012, 0.014 + u(0, 0.006), base=0.013, shade=0.06, segs=5)
    ob = raw_object("Hair", verts, faces, [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["hair"], arm, orient=True)
    return ob


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


BEARD = 0.0050  # how far a beard stands off the skin


def beard_top(a):
    """A beard's upper edge (height relative to HEAD) by the angle round the head: under the
    nose, out past the mouth's corners, then up the cheek to the sideburn."""
    a = abs(a)
    if a < 24:
        return -0.0555 - 0.0045 * smooth(a / 24)
    return lerp(-0.0600, -0.0060, ((a - 24) / 64) ** 1.3)


MOUTH = (0.0245, 0.0100, -0.0765)  # the gap a beard leaves round the mouth: half width, half height, height


def make_beard(arm, pos, quads):
    """A short full beard: the face's own quads below the cheek line, pushed out, with the
    vertices just outside its edge slid onto the edge (so the edge is a smooth line and the shell
    follows the skin exactly). It leaves the mouth clear."""
    mw, mh, mz = MOUTH

    def measure(p):
        az = math.degrees(math.atan2(-p[0], p[1]))
        top = beard_top(az) - p[2]
        e = math.sqrt((p[0] / mw) ** 2 + ((p[2] - mz) / mh) ** 2) - 1.0
        return az, top, e

    info = [measure(p) for p in pos]
    inside = [abs(az) <= 90 and top > 0 and e > 0 for az, top, e in info]
    verts, cols, faces, index = [], [], [], {}
    new_pos, depth = [], []
    for q in quads:
        if sum(inside[i] for i in q) < 2:
            continue
        idx = []
        for i in q:
            if i not in index:
                az, top, e = info[i]
                p = np.array(pos[i])
                d = 0.0
                if inside[i]:
                    d = min(top, e * mh * 1.5, (90 - abs(az)) / 90 * 0.14)
                elif abs(az) > 90:
                    p = head_point(math.copysign(90, az), min(p[2], beard_top(90) - 1e-4))
                elif e <= 0:
                    k = 1.0 / max(e + 1.0, 1e-3)
                    p = project_front([(p[0] * k, mz + (p[2] - mz) * k)])[0][0]
                else:
                    p = head_point(az, beard_top(az))
                index[i] = len(new_pos)
                new_pos.append(p)
                depth.append(d)
            idx.append(index[i])
        faces.append(idx)
    new_pos = np.array(new_pos)
    nrm = head_normal(new_pos)
    rng = random.Random(7)
    for p, n, d in zip(new_pos, nrm, depth):
        t = smooth(d / 0.011)
        verts.append(hw(p + n * (0.0009 + (BEARD - 0.0009) * t)))
        cols.append(mix(mix(HAIR, HAIR_TIP, 0.55 + 0.3 * (1 - t)), PAL["driftwood"], 0.06 + 0.10 * rng.random()))
    return raw_object("Beard", verts, faces, [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["hair"], arm)


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


def jersey_colour(tag, u, v, co, n):
    base = PAL["sea_green"]
    base = mix(base, PAL["slate"], 0.25)
    # Knit: ribs round the torso and sleeves; tighter, darker ribbing at collar, cuffs and hem.
    rib = int(math.floor(u * (80 if tag in (2, 3) else 40) + 0.5)) % 2
    c = mix(base, (0, 0, 0), 0.16 * rib)
    if tag in (2, 3):
        c = mix(c, (0, 0, 0), 0.12)
    return c


def coat_colour(tag, u, v, co, n):
    c = mix(PAL["mustard"], PAL["driftwood"], 0.22)
    # Wet and tarred toward the hem; salt-faded on the shoulders.
    c = mix(c, PAL["kelp"], 0.40 * smooth((0.86 - co.z) / 0.2))
    c = mix(c, PAL["old_lime"], 0.16 * smooth((co.z - 1.40) / 0.08))
    if tag == 4:  # patches: other cloth, never matching
        c = PAL["driftwood"]
    elif tag == 5:
        c = mix(PAL["kelp"], PAL["driftwood"], 0.3)
    elif tag == 6:
        c = PAL["oxblood"]
    elif tag == 7:  # collar lining and cuffs' inside
        c = mix(PAL["kelp"], PAL["tar"], 0.3)
    return c


def build_man(arm, seed, coat=True, body=False, beard=True):
    obs = []
    if body:
        # The unclothed form the garments are offsets of (for inspection).
        p = upper_garment(Part("BodyTop"), 0.0, [0.94, 1.01, 1.08, 1.16, 1.24, 1.32], hem=[], cuff=(-0.705, []), collar=[(0.03, -0.006, {"J_Bip_C_Neck": 1.0})]).mirrored()
        obs.append(build(p, arm, MAT["skin"], lambda *a: SKIN))
        p = trousers(Part("BodyLegs"), 0.0, top=1.0, bottom=0.11).mirrored()
        obs.append(build(p, arm, MAT["skin"], lambda *a: SKIN))
    else:
        # Jersey: a roll neck, ribbed cuffs and hem. Under a coat only its front, collar and cuffs
        # are kept.
        def jtag(kind, k, r):
            if kind in ("collar", "cuff", "hem"):
                return 2
            if coat and kind == "torso" and k >= 3:
                return Part.HIDE
            if coat and kind == "yoke" and k >= 3:
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
        obs.append(build(p, arm, MAT["jersey"], jersey_colour))
        if coat:
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

            chest = blend(("J_Bip_C_UpperChest", 0.75), ("J_Bip_C_Neck", 0.25))
            p = upper_garment(
                Part("Coat"), 0.024, [0.70, 0.79, 0.88, 0.97, 1.06, 1.15, 1.24, 1.32],
                hem=[], cuff=(-0.640, [(-0.030, 0.006)]), collar=[(0.028, 0.012, chest), (0.060, 0.026, chest)],
                front=lambda z: lerp(0.058, 0.026, smooth((z - 0.70) / 0.75)), skirt=1.0, tag_fn=ctag,
            ).mirrored()
            obs.append(build(p, arm, MAT["coat"], coat_colour, solid=0.006))
        # Trousers, tucked into the boots.
        p = trousers(Part("Trousers"), 0.012).mirrored()
        obs.append(build(p, arm, MAT["trousers"], lambda tag, u, v, co, n: mix(PAL["iron"], PAL["slate"], 0.25 + 0.10 * (int(u * 44) % 2))))
        # Sea boots: tarred leather, a paler folded top, a dark sole.
        def boot_colour(tag, u, v, co, n):
            if co.z < 0.022:
                return (0.055, 0.05, 0.045)  # the sole
            if tag == 1:
                return mix(PAL["peat"], PAL["driftwood"], 0.22)
            return mix(PAL["tar"], PAL["peat"], 0.75 + 0.25 * smooth((co.z - 0.05) / 0.3))

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
    # Head, neck, ears, face, hair.
    head, pos, quads = make_head(arm, seed)
    obs.append(head)
    obs.append(make_neck(arm))
    obs += make_ears(arm)
    sh = Shells()
    face_parts(sh, beard)
    obs += sh.objects(arm)
    obs.append(make_hair(arm, seed, pos, quads))
    if beard:
        obs.append(make_beard(arm, pos, quads))
    if coat and not body:
        obs.append(make_buttons(arm))
    return obs


# ---------------------------------------------------------------------------------------------
# Export.

HUMAN = {
    "hips": "J_Bip_C_Hips", "spine": "J_Bip_C_Spine", "chest": "J_Bip_C_Chest", "upperChest": "J_Bip_C_UpperChest", "neck": "J_Bip_C_Neck",
    "head": "J_Bip_C_Head", "leftShoulder": "J_Bip_L_Shoulder", "leftUpperArm": "J_Bip_L_UpperArm", "leftLowerArm": "J_Bip_L_LowerArm",
    "leftHand": "J_Bip_L_Hand", "leftUpperLeg": "J_Bip_L_UpperLeg", "leftLowerLeg": "J_Bip_L_LowerLeg", "leftFoot": "J_Bip_L_Foot",
    "leftToes": "J_Bip_L_ToeBase",
}


def add_vrm(path, title):
    """Mark the file as a VRM 0.x humanoid (plain JSON in the GLB's extensions)."""
    b = open(path, "rb").read()
    jl = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20 : 20 + jl])
    rest = b[20 + jl :]
    nodes = {n.get("name"): i for i, n in enumerate(j["nodes"])}
    bones = []
    for k, n in HUMAN.items():
        bones.append({"bone": k, "node": nodes[n], "useDefaultValues": True})
        if k.startswith("left"):
            bones.append({"bone": "right" + k[4:], "node": nodes[mirror_name(n)], "useDefaultValues": True})
    j.setdefault("extensionsUsed", []).append("VRM")
    j.setdefault("extensions", {})["VRM"] = {
        "exporterVersion": "slop-art-online person.py",
        "specVersion": "0.0",
        "meta": {"title": title, "author": "Slop Art Online (generated by living/tools/blender/person.py)", "licenseName": "Other"},
        "humanoid": {"humanBones": bones},
        "blendShapeMaster": {"blendShapeGroups": []},
        "secondaryAnimation": {"boneGroups": [], "colliderGroups": []},
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
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--no-coat", action="store_true")
    ap.add_argument("--no-beard", action="store_true")
    ap.add_argument("--body", action="store_true", help="the unclothed form instead of the clothes")
    ap.add_argument("--blend")
    a = ap.parse_args(argv)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    arm = make_armature()
    obs = build_man(arm, a.seed, coat=not a.no_coat, body=a.body, beard=not a.no_beard)
    tris = {}
    for ob in obs:
        ob.data.calc_loop_triangles()
        tris[ob.name] = len(ob.data.loop_triangles)
    if a.blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.blend))
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=out, export_format="GLB", export_yup=True, export_skins=True, export_animations=False, export_vertex_color="ACTIVE",
        export_all_vertex_colors=False, export_normals=True, export_materials="EXPORT", export_def_bones=False, export_leaf_bone=False,
        export_rest_position_armature=True, use_selection=False,
    )
    j = add_vrm(out, "Cullet man")
    zs = [v.co.z for ob in obs for v in ob.data.vertices]
    print(f"PERSON {out}: {sum(tris.values())} triangles, {len(arm.data.bones)} bones, {len(j['materials'])} materials, height {max(zs) - min(zs):.3f} m, floor {min(zs):+.4f}")
    print("PERSON parts: " + ", ".join(f"{k} {v}" for k, v in tris.items()))


if __name__ == "__main__":
    main()
