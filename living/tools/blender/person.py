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
sys.path.insert(1, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "characters"))  # face_types: the types' data
import cage_head  # noqa: E402
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
WHOLE_HEAD = False  # keep the scalp the hair's cap would cover (--parts head)
RECEDE = 0.0  # how far the front hairline has moved back, m
BALD = 0.0  # 0 a full head of hair to 1 a bald crown from the forehead back
STRANDS_PATH = ""  # where the strands' picture is written
LIMB_K = 1.0  # girth of arms and legs
GIRTH = 1.0  # girth of the torso
BELLY = 0.0  # how far a belly stands forward (a share of the torso's depth)
CHEST = 0.0  # how much wider and deeper a strong chest is
LONG = 0.07  # how far a bob hangs below the hairline, m
HF = None  # the head's form (head_form.Head, or cage_head.CageHead for a person of a face type)
TYPED = False  # the head is a face type's cage, with the identity bones in it

# Materials, by shading kind (the game picks the toon kind from VRoid's name tags): a person is
# six meshes, one each. Cloth, skin and the face's lines are white with colour per vertex, so
# every person's are the same material; the face, the eyes and the hair carry textures, which
# living/tools/characters/share.py puts on files that people share. `far` is the far model's
# skin (head, neck and hands), textured with the far picture.
MAT = dict(
    face="M00_000_00_Face_00_SKIN", skin="M00_000_00_Body_00_SKIN", eye="M00_000_00_Eye_00_EYE", iris="M00_000_00_EyeIris_00_EYE", overlay_hair="M00_000_00_Overlay_00_HAIR", far_overlay="M00_000_00_FarOverlay_00_HAIR", overlay_skin="M00_000_00_FaceOverlay_00_SKIN", overlay_face="M00_000_00_FaceOverlay_00_FACE", line="M00_000_00_FaceEyeline_00_FACE", brow="M00_000_00_FaceBrow_00_FACE", tint="M00_000_00_FaceTint_00_FACE",
    hair="M00_000_Hair_00_HAIR", cloth="M00_001_01_Cloth_01_CLOTH", far="M00_000_00_Body_01_SKIN",
)
FAR = False  # building the far model (--lod): coarse cages, a head without openings, thin locks

# ---------------------------------------------------------------------------------------------
# The skeleton: an adult man, 1.78 m to the scalp. Blender axes: +Y forward, +Z up, left at -X.

ARM_Y, ARM_Z = -0.010, 1.420
SHOULDER_X = -0.199  # the shoulder joint: broad for a working man
WRIST_X = SHOULDER_X - 0.530
JOINTS = {
    "Root": (0, 0, 0),
    "J_Bip_C_Hips": (0, 0.000, 0.985),
    "J_Bip_C_Spine": (0, 0.006, 1.060),
    "J_Fit_Belly": (0, 0.110, 1.070),  # a helper no clip keys: moved forward, it carries a belly on the clothes in front of it
    "J_Bip_C_Chest": (0, 0.012, 1.180),
    "J_Bip_C_UpperChest": (0, 0.004, 1.310),
    # The neck's and the head's joints are where the reference has them, measured from the chin
    # (reference/neck.py; the chin is at 1.535 and a head is 0.2564 high): the neck's 0.168 of a
    # head below it, the head's 0.135 above, each a little ahead of where they were. Until the
    # joints step the neck's was 0.234 below (1.475, y -0.020) and the head's 0.098 above (1.560,
    # y -0.010).
    "J_Bip_C_Neck": (0, -0.012, 1.492),
    "J_Bip_C_Head": (0, -0.003, 1.570),
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
    "J_Bip_C_Hips": "Root", "J_Bip_C_Spine": "J_Bip_C_Hips", "J_Fit_Belly": "J_Bip_C_Spine", "J_Bip_C_Chest": "J_Bip_C_Spine",
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
            JOINTS[n] = tuple(hw(HF.eye_pivot(side) if TYPED else head_mesh.eye_ball(HF, side)))
            PARENT[n] = f"J_Id_Orbit_{'L' if side < 0 else 'R'}" if TYPED else "J_Bip_C_Head"
    if TYPED:
        # The identity bones (docs/CHARACTERS.md, "The rig"): under the head, keyed by no clip.
        for n, pos in cage_head.rig_pivots(HF).items():
            JOINTS[n] = tuple(hw(pos))
            PARENT[n] = cage_head.RIG_PARENT[n]
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
    # A bone comes after its parent (the eyes' bones hang under the orbits on a typed head).
    order.sort(key=lambda n: (0 if n == "Root" else 1 if n.startswith("J_Bip") else 2 if n.startswith("J_Id") else 3))
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
    if skirt and z < 0.95:
        # A skirt's panels follow the legs' stride: up to half the same side's upper leg at the hem.
        # They start to at the hip joint and have most of it a hand below: a thigh that lifts
        # carries its trouser leg whole, and a skirt that waited until mid-thigh to follow let the
        # thigh's top come through its front at every step (cloth_check.py: by 2 to 5 mm in the
        # walk, and by 13 on a woman's form, whose skirt lies closer).
        t = (0.85 if front else 0.55) * smooth((0.95 - z) / 0.20)
        side = min(abs(x) / 0.07, 1.0)
        left = t * (0.5 + 0.5 * side if x <= 0 else 0.5 - 0.5 * side)
        right = t - left
        w = [(n, v * (1 - t)) for n, v in w] + [("J_Bip_L_UpperLeg", left), ("J_Bip_R_UpperLeg", right)]
    return blend(*w)


def torso_point(z, k, d=0.0, skirt=0.0, n=NT, edge=None):
    """Column k (0 front, n/4 the left side, n/2 back) of the torso's ring at height z, offset d."""
    sx = sz = 1.0
    girth = GIRTH
    if STANCE:
        # A woman's form is given as she stands: looked up at the height this ring will stand
        # at, and written wider by what the bones will take off it.
        w = torso_w(z, 0.0)
        sx, sz = STANCE.across(w), STANCE.deep(w)
        a, b, cy = (v * STANCE.height / 100.0 for v in table(WOMAN_FORM, 100.0 * STANCE.up(z, w) / STANCE.height))
        girth = GIRTH / WOMAN_GIRTH
    else:
        a, b, cy = table(TORSO, z)
    a, b = a * lerp(1.0, girth, smooth((1.40 - z) / 0.08)), b * girth
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
    return Vector((-a * math.copysign(abs(s) ** p, s) / sx, (cy + b * front * math.copysign(abs(c) ** p, c)) / sz, z))


def arm_w(x):
    x = x - ARM_OUT
    lower = smooth((-0.432 - x) / 0.066)
    hand = smooth((-0.690 - x) / 0.04)
    sh = 0.25 * smooth((x + 0.25) / 0.045)
    return blend(("J_Bip_L_Shoulder", sh), ("J_Bip_L_UpperArm", (1 - sh) * (1 - lower)), ("J_Bip_L_LowerArm", lower * (1 - hand)), ("J_Bip_L_Hand", lower * hand))


def upper_garment(part, d, zs, hem, cuff, collar, front=None, skirt=0.0, tag_fn=None, cols=None, neck_d=None):
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
        # The neck hole lies NECK_EASE off the neck itself (it was 6.6 cm from the axis whatever
        # the neck: round a neck 3.2 cm in radius that is a collar twice the neck's width).
        # `neck_d`: the garment's distance off the body at its neck hole, where a thick coat or
        # a loose smock closes in on the neck.
        base = NECK_R + NECK_EASE + (d if neck_d is None else neck_d)
        phi = 2 * PI * k / NT
        if front and k == 1:
            phi = math.asin(min(front(1.5) / (base + dr), 1.0))
        s, c = math.sin(phi), math.cos(phi)
        z = 1.488 + 0.016 * smooth(k / 5.0) + dz
        return Vector((-(base + dr) * s, cage_head.NECK_Y - 0.002 + (base * 1.08 + dr) * c, z))

    prev = rowT
    neck_x = across(blend(("J_Bip_C_UpperChest", 0.6), ("J_Bip_C_Neck", 0.4)))  # the weights of the last step below
    for step in (1, 2, 3):
        t = step / 3
        cur = []
        for i, k in enumerate(ks):
            a = part.co[rowT[i]]
            b = neck_point(k)
            b.x /= neck_x  # the neck hole stays round where the shoulders' bones are scaled across
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
        cur = []
        for k in ks:
            pos = neck_point(k, dz, dr)
            pos.x /= across(w)
            cur.append(part.v(pos, w))
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


# A woman's leg against a man's at the same girth (across, front to back), by rest height: a
# fuller thigh and calf, a narrower knee and ankle, and deeper than wide all the way down, as
# the reference's are (reference/body.py: thigh 8.9% by 9.6% of the height, knee 4.6 by 6.0,
# calf 5.3 by 6.4, ankle 2.8 by 4.0).
WOMAN_LEG = [(0.10, 0.90, 1.10), (0.16, 0.90, 1.10), (0.28, 1.08, 1.18), (0.38, 1.10, 1.20), (0.455, 0.96, 1.12), (0.50, 0.90, 1.10), (0.54, 0.92, 1.10), (0.62, 1.02, 1.10), (0.74, 1.05, 1.07), (0.84, 1.05, 1.05)]
CROTCH_UP = 0.035  # how far a woman's crotch stands above a man's at rest: the reference's is 52.4% of the height up


def leg_ring(part, z, d, w, n=13, floor=None):
    cx, cy, rx, ry = table(LEG_UP, z)
    if STANCE:
        kx, ky = table(WOMAN_LEG, z)
        rx, ry = rx * kx, ry * ky
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
    up = CROTCH_UP if STANCE else 0.0
    zs = [top, 1.01, 0.94 + 0.3 * up, 0.875 + up]
    for z in zs:
        row = []
        for k in ks:
            pos = torso_point(z, k, d)
            if z < 0.9 + up:
                # The seat narrows into the legs' tops.
                pos.x *= 0.99
            side = smooth(abs(pos.x) / 0.09)
            leg = (0.18 if z > 0.9 + up else 0.62) * side if z < 0.98 else 0.0
            row.append(part.v(pos, blend(*torso_w(z, pos.x).items(), ("J_Bip_L_UpperLeg", leg / max(1 - leg, 1e-3)))))
        rows.append(row)
    for r in range(len(rows) - 1):
        part.band(rows[r], rows[r + 1], r, r + 1, closed=False, tag=tag_fn("seat", 0, r), u0=0.0, u1=0.5)
    # Waistband lip.
    lip = [part.v(torso_point(top + 0.012, k, d - 0.012), torso_w(top, 0)) for k in ks]
    part.band(lip, rows[0], -1, 0, closed=False, tag=tag_fn("waist", 0, -1), u0=0.0, u1=0.5)
    # The crotch: two vertices on the centre plane join front to back between the legs.
    hips = {"J_Bip_C_Hips": 1.0}
    s1 = part.v((0, 0.040, 0.842 + up), hips)
    s2 = part.v((0, -0.045, 0.846 + up), hips)
    loop = rows[-1] + [s2, s1]
    n = len(loop)
    prev = loop
    r = len(rows)
    for z in [0.80 + 0.8 * up, 0.72, 0.62, 0.555, 0.50, 0.455, bottom]:
        w = blend(*leg_w(z).items(), ("J_Bip_C_Hips", 0.25 if z > 0.79 else 0.0))  # the leg's top turns less than the thigh: the crease is the hip's
        cur = leg_ring(part, z, d * (1.0 if z > 0.5 else 0.7), w, n)
        part.band(prev, cur, r, r + 1, tag=tag_fn("leg", 0, r))
        prev = cur
        r += 1
    return part


WOMAN_BOOT = 0.90  # a woman's boot against a man's, across the shaft and the foot


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

    slim = WOMAN_BOOT if STANCE else 1.0
    made = []
    for (cy, cz), tilt, rx, rf, rb in rings:
        rx, rf, rb = rx * slim, rf * (slim if cz > 0.1 else 1.0), rb * (slim if cz > 0.1 else 1.0)
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
        cur = ring(part, (x0, -0.004, cz), (1, 0, 0), (0, 1, 0), 0.068 * slim + dr + d, 0.074 * slim + dr + d, n, shin, p=0.9, r2b=0.072 * slim + dr + d)
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
    if TYPED:
        # On a face type's head the line comes lower at the temple and in front of the ear (a
        # sideburn to the middle of the ear) and sits close over the ear's top: the line tuned on
        # pass 2's head left a bare temple and skin above the ear from the side.
        return float(np.interp(abs(az), [0, 35, 60, 72, 82, 92, 104, 125, 180], [0.080 + top + r, 0.076 + top + 1.3 * r, 0.034 + 0.6 * r, 0.006, -0.014, 0.012, 0.004, -0.050, -0.078]))
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
    if FAR:
        # The far model: the cage itself, one skin thick.
        levels, solid = 0, 0.0
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
    # A face type's own file keeps the whole skull: every hair style shares it.
    keep = lambda c: WHOLE_HEAD or c[2] < hairline(az_of(c)) + 0.016 or bald_depth(c) > -0.012
    face = cage_head.CageFace(HF, look, keep=keep) if TYPED else head_mesh.Face(HF, look, keep=keep)
    m = face.mesh
    # Lips and blush are a layer of their own over the skin they lie on, in a material the client
    # does not recolour (`…_FACE`: drawn as the lash lines are, unshaded and in its own colours):
    # painted into the skin, the skin's recolouring washed them out. The layer is the skin's own
    # faces under the paint, a hair's width out, with the skin's weights and expressions.
    layer = None if OVERLAY else {}
    atlas = face_paint.paint(HF, look, layer)
    tint_src = []
    if layer is not None:
        rows_ = head_mesh.ATLAS - head_mesh.EYE_ROWS
        uv0 = np.array(m.uv)
        nsk = face.skin_n + len(face._extra)
        px = np.clip((uv0[:nsk, 0] % 1.0) * head_mesh.ATLAS, 0, head_mesh.ATLAS - 1).astype(int)
        py = np.clip((1.0 - uv0[:nsk, 1]) * head_mesh.ATLAS - head_mesh.EYE_ROWS, 0, rows_ - 1).astype(int)
        touched = layer["alpha"][py, px] > 0.02
        near = {v for f in face.skin_faces if any(touched[v] for v in f) for v in f}  # and the faces round them
        tint_faces = [f for f in face.skin_faces if any(v in near for v in f)]
        tint_src = sorted({v for f in tint_faces for v in f})
        index = {v: len(m.v) + i for i, v in enumerate(tint_src)}
        nrm_ = np.array(face.skin_normals)
        for v in tint_src:
            m.v.append(tuple(np.array(m.v[v]) + nrm_[v] * OVERLAY_OUT))
            m.col.append((1.0, 1.0, 1.0))
            m.uv.append(m.uv[v])
            m.eye.append(m.eye[v])
        for f in tint_faces:
            m.f.append(tuple(index[v] for v in f))
            m.fm.append("tint")
    # The iris shares the eye's material (the atlas); highlights are plain colour, as the lines are.
    # The lash lines, highlights and the mouth's inside are one material (plain colour).
    # The iris is a material of its own (VRoid's name for it, `EyeIris`), with its own small
    # picture: the client recolours a material by moving its picture's mean colour to the person's,
    # and the tag for the eyes' colour goes to materials named so.
    # The brows are a material of their own too (VRoid's `FaceBrow`): plain colour as the lines
    # are, and the one the client gives the person's hair colour.
    # The iris's lights ride in the lips' and blush's layer: a fixed colour the client leaves be.
    fm = [dict(iris="iris", face="face", eye="eye", under="skin", tint="tint", lights="tint", brow="brow").get(k, "line") for k in m.fm]
    order = [k for k in ("face", "eye", "iris", "line", "brow", "skin", "tint") if k in set(fm)]
    A, C0, PXI = head_mesh.ATLAS, head_mesh.IRIS_COL0, head_mesh.IRIS_PX
    iris_verts = {v for f, k in zip(m.f, m.fm) if k == "iris" for v in f}
    m.uv = [((u * A - C0) / PXI, 1.0 - (1.0 - v) * A / PXI) if i in iris_verts else (u, v) for i, (u, v) in enumerate(m.uv)]
    base = np.array(HEAD)[None, :]
    world = base + np.array(m.v) * HEAD_SCALE
    eye_bone = {-1: "J_Adj_L_FaceEye", 1: "J_Adj_R_FaceEye"}
    weights = [{"J_Bip_C_Head": 1.0} if e is None else ({eye_bone[e[0]]: e[1], "J_Bip_C_Head": 1.0 - e[1]} if e[1] < 1 else {eye_bone[e[0]]: 1.0}) for e in m.eye]
    v_kind = [None] * len(m.v)
    for f, k in zip(m.f, m.fm):
        for v in f:
            v_kind[v] = k
    if TYPED:
        # Each vertex's share of the identity bones, by where it lies; an eye's own parts ride its orbit.
        shares = cage_head.identity_weights(HF, np.array(m.v), brows=True)
        for i, e in enumerate(m.eye):
            if e is None:
                weights[i] = shares[i]
            else:
                orbit = f"J_Id_Orbit_{'L' if e[0] < 0 else 'R'}"
                weights[i] = {eye_bone[e[0]]: e[1], orbit: 1.0 - e[1]} if e[1] < 1 else {eye_bone[e[0]]: 1.0}
        # A brow lies on the skin: each of its vertices takes the weights of the skin under it
        # (the skin's triangle there, its corners' weights by how near each is), so whatever a
        # person's values do to the forehead they do to the brow, and it stays its own distance
        # off. The skin round a brow follows the brow's bone (identity_weights), which is how
        # the brow's own values still move it.
        skin = [f for f, k in zip(m.f, m.fm) if k == "face"]
        tris = np.array([(f[0], f[j], f[j + 1]) for f in skin for j in range(1, len(f) - 1)])
        V = np.array(m.v)
        A, B, C = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
        lo, hi = np.minimum(np.minimum(A, B), C), np.maximum(np.maximum(A, B), C)
        den = (B[:, 2] - C[:, 2]) * (A[:, 0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (A[:, 2] - C[:, 2])
        for i, k in enumerate(v_kind):
            if k != "brow":
                continue
            q = V[i]
            near = np.where((lo[:, 0] <= q[0]) & (hi[:, 0] >= q[0]) & (lo[:, 2] <= q[2]) & (hi[:, 2] >= q[2]) & (np.abs(den) > 1e-14) & (hi[:, 1] > 0))[0]
            u = ((B[near, 2] - C[near, 2]) * (q[0] - C[near, 0]) + (C[near, 0] - B[near, 0]) * (q[2] - C[near, 2])) / den[near]
            v = ((C[near, 2] - A[near, 2]) * (q[0] - C[near, 0]) + (A[near, 0] - C[near, 0]) * (q[2] - C[near, 2])) / den[near]
            w = 1 - u - v
            inside = (u >= -1e-6) & (v >= -1e-6) & (w >= -1e-6)
            if not inside.any():
                raise SystemExit(f"person: no skin under a brow's vertex at {tuple(round(float(x), 4) for x in q)}")
            fwd = u * A[near, 1] + v * B[near, 1] + w * C[near, 1]
            best = np.where(inside)[0][np.argmax(fwd[inside])]  # the skin's front, where the brow lies
            mixed = {}
            for corner, share in zip(tris[near[best]], (u[best], v[best], w[best])):
                for name, x in shares[corner].items():
                    mixed[name] = mixed.get(name, 0.0) + float(share) * x
            top = sorted(mixed.items(), key=lambda kv: -kv[1])[:4]
            total = sum(x for _, x in top)
            weights[i] = {name: x / total for name, x in top}
        for i in face.under_neck:  # the neck's ring turns with the neck
            weights[i] = {"J_Bip_C_Neck": 0.75, "J_Bip_C_Head": 0.25}
    for i, v in enumerate(tint_src):  # the layer moves exactly as the skin under it
        weights[len(m.v) - len(tint_src) + i] = weights[v]
    ob = raw_object("Face", world, m.f, weights, m.col, None, arm, uvs=m.uv, materials=[MAT[k] for k in order], face_mats=[order.index(k) for k in fm])
    ob.shape_key_add(name="Basis", from_mix=False)
    for name, delta in face.morphs.items():
        key = ob.shape_key_add(name=name, from_mix=False)
        if tint_src:
            delta = np.vstack([delta, delta[tint_src]])
        key.data.foreach_set("co", (world + delta * HEAD_SCALE).ravel())
        # A new key starts at 1, and the file would say every expression is on.
        key.value = float(spec.get("expression", {}).get(name, 0.0))
    face_paint.write_png(atlas_path, atlas)
    iris_path = atlas_path.replace(".atlas.png", ".iris.png")
    face_paint.write_png(iris_path, np.ascontiguousarray(atlas[:PXI, C0 : C0 + PXI]))
    for keys, path in ((("face", "eye"), atlas_path), (("iris",), iris_path)):
        img = bpy.data.images.load(path)
        img.pack()
        for k in keys:
            mat = material(MAT[k])
            tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tex.image = img
            bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if layer is not None:
        # The layer's picture: the atlas's layout at half its size, pigment with an alpha. Lips
        # and blush where the skin is, the iris's lights where the iris is.
        A2 = head_mesh.ATLAS
        pic = np.zeros((A2, A2, 4))
        pic[..., :3] = face_paint.BLUSH_PIGMENT
        pic[head_mesh.EYE_ROWS :, :, :3] = layer["rgb"]
        pic[head_mesh.EYE_ROWS :, :, 3] = layer["alpha"]
        pic[:PXI, C0 : C0 + PXI] = layer["lights"]
        # Averaged with the alpha as weight, so a half-covered texel keeps the pigment's colour.
        blocks = pic.reshape(A2 // 2, 2, A2 // 2, 2, 4)
        a_ = blocks[..., 3:4]
        rgb_ = (blocks[..., :3] * a_).sum(axis=(1, 3)) / np.maximum(a_.sum(axis=(1, 3)), 1e-6)
        rgb_ = np.where(a_.sum(axis=(1, 3)) > 1e-6, rgb_, np.array(face_paint.BLUSH_PIGMENT))
        small = np.concatenate([rgb_, a_.mean(axis=(1, 3))], axis=2)
        small = (np.clip(small, 0, 1) * 255 + 0.5).astype(np.uint8)
        path = atlas_path.replace(".atlas.png", ".tint.png")
        timg = bpy.data.images.new("tint", small.shape[1], small.shape[0], alpha=True)
        timg.pixels.foreach_set((small[::-1].astype(np.float32) / 255.0).ravel())
        timg.filepath_raw = path
        timg.file_format = "PNG"
        timg.save()
        timg = bpy.data.images.load(path)
        timg.colorspace_settings.name = "sRGB"
        timg.pack()
        mat = material(MAT["tint"])
        mat.blend_method = "BLEND"
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = timg
        bsdf = next(x for x in mat.node_tree.nodes if x.type == "BSDF_PRINCIPLED")
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        mat.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    if OVERLAY:
        layer = make_overlay(arm, spec, face, m, world, weights, atlas_path)
        bpy.data.objects.remove(ob, do_unlink=True)  # the file holds the layer alone
        return layer, face.base_pos, face.base_quads
    return ob, face.base_pos, face.base_quads


OVERLAY = None  # the overlay style being built (--overlay): beard_<style>, stubble, lines, freckles
OVERLAY_OUT = 0.0003  # how far an overlay lies off the skin, metres


def make_overlay(arm, spec, face, m, world, weights, atlas_path):
    """A detail a person has and a type does not, as a thin layer over the type's own face skin:
    a beard (the skin under it already stands out by the beard's thickness), stubble, age lines
    or freckles. Its picture is what the face's paint adds for that detail, with an alpha.

    - A beard and stubble are grey: the client tints a grey picture by the tag, moving its mean
      to the person's beard colour.
    - Age lines and freckles are one fixed colour, in a material the client neither shades nor
      tints (`…FaceOverlay_00_FACE`, as lips and blush are). Tinted by the skin's tag they came
      out at the skin's own colour: the client moves a picture's mean to the tag's colour, and
      the mean of a picture of lines is the lines.

    It has the face's weights and expressions, so it rides the identity bones and the morphs."""
    look = spec["look"]
    rng = lambda: np.random.default_rng(int(look.get("seed", 0)) + 77)
    plain = dict(look, lines=0.0, stubble=0.0, freckles=0.0, beard=None)
    # The one detail, on plain skin. An old type's own figure has age lines whatever is asked for:
    # painted from its whole look, its freckles and its beard carried the lines as well, and a
    # person wearing both wore the lines twice.
    key = "beard" if OVERLAY.startswith("beard") else OVERLAY
    strong = dict(lines=face_paint.LINE_OVERLAY, freckles=face_paint.FRECKLE_OVERLAY).get(OVERLAY, (1.0, 1.0, 1.0))
    with_, _ = face_paint.paint_skin(HF, dict(plain, detail_size=strong[2], **{key: look[key]}), rng())
    without, _ = face_paint.paint_skin(HF, plain, rng())
    hairy = OVERLAY.startswith("beard") or OVERLAY == "stubble"
    diff = np.abs(with_ - without).max(axis=2)
    alpha = np.clip(diff / (0.10 if OVERLAY.startswith("beard") else 0.16), 0.0, 1.0)
    tint = np.array(look["beard_colour"] if OVERLAY.startswith("beard") else (look["stubble_colour"] if OVERLAY == "stubble" else look["skin"]))
    grey = np.clip((with_ @ np.array([0.3, 0.59, 0.11])) / max(float(tint @ np.array([0.3, 0.59, 0.11])), 1e-3), 0.0, 1.0)
    fixed = OVERLAY in ("lines", "freckles")
    rows = head_mesh.ATLAS - head_mesh.EYE_ROWS
    pic = np.zeros((head_mesh.ATLAS, head_mesh.ATLAS, 4))
    if fixed:
        # How much of the pigment, as the client draws it, takes the type's skin to what was painted.
        pigment = np.array(face_paint.LINE_PIGMENT if OVERLAY == "lines" else face_paint.FRECKLE_PIGMENT)
        toward = without - np.clip(pigment * face_paint.PART_GAIN, 0.0, 1.0)
        alpha = np.clip(((without - with_) * toward).sum(axis=2) / np.maximum((toward * toward).sum(axis=2), 1e-6), 0.0, 1.0) * (diff > 0.004)
        # Drawn for the screen (face_paint.FRECKLE_OVERLAY, LINE_OVERLAY): stronger than the
        # paint's own strength, up to nearly the whole pigment at a core.
        alpha = np.clip(alpha * strong[0], 0.0, strong[1])
        pic[..., :3] = pigment
    else:
        pic[head_mesh.EYE_ROWS :, :, :3] = grey[..., None]
    pic[head_mesh.EYE_ROWS :, :, 3] = alpha
    small = (np.clip(pic.reshape(head_mesh.ATLAS // 2, 2, head_mesh.ATLAS // 2, 2, 4).mean(axis=(1, 3)), 0, 1) * 255 + 0.5).astype(np.uint8)
    path = atlas_path.replace(".atlas.png", ".overlay.png")
    img = bpy.data.images.new("overlay", small.shape[1], small.shape[0], alpha=True)
    img.pixels.foreach_set((small[::-1].astype(np.float32) / 255.0).ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    img = bpy.data.images.load(path)
    img.colorspace_settings.name = "sRGB"
    img.pack()
    # The faces of the skin the detail touches, a hair's width off it.
    uv = np.array(m.uv)
    n = face.skin_n + len(face._extra)
    px = np.clip((uv[:n, 0] % 1.0) * head_mesh.ATLAS, 0, head_mesh.ATLAS - 1).astype(int)
    py = np.clip((1.0 - uv[:n, 1]) * head_mesh.ATLAS - head_mesh.EYE_ROWS, 0, rows - 1).astype(int)
    # A freckle or a line is finer than the mesh: the paint is spread a few millimetres before it
    # is sampled at the vertices, so every face that has any of it is taken. Sampled as painted,
    # a freckle between two vertices was left out, and a type could come out with none.
    near = alpha.copy()
    for axis in (0, 1):
        grown = near.copy()
        for shift in range(1, 15):
            for sgn in (1, -1):
                moved = np.roll(near, sgn * shift, axis=axis)
                if axis == 0:
                    moved[(slice(0, shift) if sgn > 0 else slice(-shift, None)), :] = 0
                else:
                    moved[:, (slice(0, shift) if sgn > 0 else slice(-shift, None))] = 0
                grown = np.maximum(grown, moved)
        near = grown
    touched = near[py, px] > 0.02
    faces = [f for f in face.skin_faces if any(touched[v] for v in f)]
    used = sorted({v for f in faces for v in f})
    index = {v: i for i, v in enumerate(used)}
    out = np.array(face.skin_normals)[used] * OVERLAY_OUT * HEAD_SCALE
    name = MAT["overlay_hair" if hairy else "overlay_face"]
    ob = raw_object("Overlay", world[used] + out, [tuple(index[v] for v in f) for f in faces], [weights[v] for v in used], [(1.0, 1.0, 1.0)] * len(used), name, arm, uvs=[tuple(uv[v]) for v in used])
    ob.shape_key_add(name="Basis", from_mix=False)
    for key_name, delta in face.morphs.items():
        key = ob.shape_key_add(name=key_name, from_mix=False)
        key.data.foreach_set("co", (world[used] + out + delta[used] * HEAD_SCALE).ravel())
        key.value = 0.0
    mat = material(name)
    mat.blend_method = "BLEND"
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    bsdf = next(x for x in mat.node_tree.nodes if x.type == "BSDF_PRINCIPLED")
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    mat.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    return ob


def make_far_head(arm, spec, picture_path):
    """The far model's head (head_mesh.FarFace): the same form on a coarse grid with no
    openings; the eyes, lash lines and brows are painted on its skin (face_paint.paint_far).
    Returns the object and the head's surface for hair and headwear."""
    look = spec["look"]
    face = head_mesh.FarFace(HF, look, keep=lambda c: WHOLE_HEAD or c[2] < hairline(az_of(c)) + 0.030 or bald_depth(c) > -0.012)
    m = face.mesh
    if OVERLAY:
        return far_beard(arm, m, look), face.base_pos, face.base_quads
    if TYPED and cage_head.CageFace.LINES:
        cage_head.far_jaw_line(m, HF, look)
    world = np.array(HEAD)[None, :] + np.array(m.v) * HEAD_SCALE
    ob = raw_object("FarHead", world, m.f, [{"J_Bip_C_Head": 1.0}] * len(m.v), m.col, MAT["far"], arm, uvs=m.uv)
    face_paint.write_png(picture_path, face_paint.paint_far(HF, look))
    img = bpy.data.images.load(picture_path)
    img.pack()
    mat = material(MAT["far"])
    if not any(n.type == "TEX_IMAGE" for n in mat.node_tree.nodes):
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = img
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return ob, face.base_pos, face.base_quads


def far_beard(arm, m, look):
    """A beard for the far head: the far head's own faces under the beard, a few millimetres
    out, in a plain material the hair's tag tints. No picture and no expressions: beyond the far
    switch a beard is a patch of the hair's colour."""
    v = np.array(m.v, float)
    az = np.degrees(np.arctan2(-v[:, 0], v[:, 1]))
    cover = HF.beard_cover(look.get("beard"), np.abs(v[:, 0]), v[:, 2], az) if look.get("beard") else None
    cover = np.zeros(len(v)) if cover is None else np.asarray(cover) * (v[:, 1] > -0.03)
    faces = [f for f, k in zip(m.f, m.fm) if k == "face" and np.mean([cover[i] for i in f]) > 0.5]
    used = sorted({i for f in faces for i in f})
    index = {i: k for k, i in enumerate(used)}
    out = v[used] - np.array(head_mesh.ORIGIN)
    out = out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9) * 0.004
    world = np.array(HEAD)[None, :] + (v[used] + out) * HEAD_SCALE
    return raw_object("Overlay", world, [tuple(index[i] for i in f) for f in faces], [{"J_Bip_C_Head": 1.0}] * len(used), [(0.86, 0.86, 0.86)] * len(used), MAT["far_overlay"], arm)


NECK_R = 0.0316  # the neck's radius (head_form.neck_radius), set for the person in configure
NECK_EASE = 0.004  # how far off the neck a garment's neck hole lies, before the garment's own distance off the body


def make_neck(arm):
    part = Part("Neck")
    # A column of the neck's own radius (head_form.neck_radius), a little wider at its foot.
    n, y = NECK_R, cage_head.NECK_Y
    stations = [
        (1.440, y - 0.006, n * 1.14, blend(("J_Bip_C_UpperChest", 0.7), ("J_Bip_C_Neck", 0.3))),
        (1.490, y - 0.003, n * 1.02, {"J_Bip_C_Neck": 1.0}),
        (cage_head.NECK_RING_Z, y, n, blend(("J_Bip_C_Neck", 0.85), ("J_Bip_C_Head", 0.15))),
        (1.540, y + 0.001, n * 0.95, blend(("J_Bip_C_Neck", 0.75), ("J_Bip_C_Head", 0.25))),
        (1.590, y + 0.004, n * 0.93, blend(("J_Bip_C_Neck", 0.2), ("J_Bip_C_Head", 0.8))),
        (1.630, y + 0.008, n * 0.86, {"J_Bip_C_Head": 1.0}),
    ]
    if TYPED:
        # A typed head brings the neck's top with it: the tube ends where the head's ring begins.
        stations = stations[:3]
    prev = None
    for i, (z, cy, r, w) in enumerate(stations):
        cur = ring(part, (0, cy, z), (1, 0, 0), (0, 1, 0), r / across(w), r * 1.04, 10, w)
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


def make_hair(arm, spec, pos, quads, covered=None, bones=None):
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
    # What long hair lies on below the head: the garment's collar and back, measured on the
    # pieces themselves at the standard build (their radius about the neck's axis and their depth
    # behind the body's, by height, plus 4 mm). A person's own hair is combed over what they wear;
    # a shared style's figure wears a smock, or a coat for the style's `.collar` file.
    wears = spec["coat"]  # a shared style's figure wears a smock, or a coat for its `.collar` file
    # Measured again after the neck was made the reference's width (2026-11-12): the collars
    # stand 5 to 8 cm from the neck's axis where they stood 8 to 12, and end below the chin.
    collar = dict(coat=0.076, smock=0.064).get(wears, 0.056)
    cone = dict(coat=((1.47, 1.50, 1.53, 1.550), (0.082, 0.076, 0.077, 0.079)), smock=((1.47, 1.50, 1.528), (0.076, 0.066, 0.064))).get(wears, ((1.47, 1.50, 1.530), (0.068, 0.060, 0.056)))
    back = back_table()
    thick = dict(coat=0.015, smock=0.014).get(wears, 0.0)
    half_w, half_d = shoulder_half()
    body = dict(neck_r=collar / HEAD_SCALE, neck_y=(cage_head.NECK_Y - HEAD.y) / HEAD_SCALE, neck_top=HF.chin_z + 0.022, shoulder_z=hd(1.468 + (0.030 if wears else 0.014)),
                half_w=(half_w + 0.035) / HEAD_SCALE, half_d=(half_d + 0.035) / HEAD_SCALE, torso_y=(0.0 - HEAD.y) / HEAD_SCALE, round=0.05 / HEAD_SCALE,
                collar=(np.array([hd(z) for z in cone[0]]), np.array(cone[1]) / HEAD_SCALE), back=(np.array([hd(z) for z in back[0]]), (np.array(back[1]) + thick * GIRTH) / HEAD_SCALE))
    h = hair.Hair(HF, hs, hairline, covered=covered, bald=bald_depth, body=body, detail=0.4 if FAR else 1.0)
    base = len(verts)
    # The far model's hair follows the bones the full model's hair added, when both are built.
    names = add_spring_bones(arm, h.chains) if bones is None else {i: bones.get(i) for i, c in enumerate(h.chains) if bones.get(i)}
    if bones is None:
        back_spheres(h, back, thick, names)
    for p_, c_, uv_, ch, al in zip(h.v, h.col, h.uv, h.chain, h.along):
        verts.append(hw(p_))
        cols.append(tuple(c_))
        uvs.append(tuple(uv_))
        weights.append(chain_weights(names[ch], h.chains[ch]["step"] * HEAD_SCALE, al * HEAD_SCALE) if ch >= 0 and names.get(ch) else {"J_Bip_C_Head": 1.0})
    lock_faces = [tuple(base + i for i in f) for f in h.f]
    ob = raw_object("Hair", verts, faces + lock_faces, weights, cols, MAT["hair"], arm, uvs=uvs)
    orient_islands(ob, skip=len(faces))
    # How soon each vertex's lock goes grey (`_GREY`, person_params.grey_mask): the client mixes a
    # shared style's tint toward the person's silver by it. The scalp's cap is a middling lock.
    mask = ob.data.attributes.new("_GREY", "FLOAT", "POINT")
    mask.data.foreach_set("value", np.concatenate([np.full(base, person_params.grey_mask(0.5)), np.asarray(h.grey, float)]).astype(np.float32))
    # Shading normals: the cap's are the head's, the locks' their own (hair.py).
    normals = [tuple(head_normal(np.array(p_)[None, :])[0]) for p_ in cp] + [None] * len(extra)
    for i, k in extra.items():
        normals[k] = normals[i]
    normals += [tuple(n_) for n_ in h.nrm]
    ob.data.normals_split_custom_set_from_vertices(normals)
    # The strands' picture, the same for everyone.
    path = STRANDS_PATH
    if not os.path.exists(path):
        # Written whole or not at all: several people are generated at once.
        face_paint.write_png(path + f".{os.getpid()}.tmp", hair.paint_strands())
        os.replace(path + f".{os.getpid()}.tmp", path)
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
        obs.append(raw_object("HairTie", tv, tf, [w] * len(tv), tc, MAT["cloth"], arm, orient=True))
    if bones is None:
        spec["springs"] = [names[i] for i in sorted(names) if names[i]]
        spec["spring_bones"] = names
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


BACK_SPHERES = []  # (bone, centre, radius): the back that hair lying on it must not sink into, for the file's spring block
HIT = 0.002  # a hair joint's own radius against the spheres: less than the hair's own distance off the cloth it was combed over


BACK_ROOTS = set()  # the first bones of the chains that lie on the back
ROPE_ROOTS = set()  # the first bones of a tail's or a braid's chain, where it hangs down the back
ROPE_HIT = 0.012  # a rope's joints are its axis: the game holds them this far off the back's spheres, the rope's own radius less a little
OFF_CLOTH = 0.007  # how far behind the cloth the spheres' backs stand: a joint is the hair's core, and held at the cloth itself the sheet round it is half in the cloth


def back_spheres(h, back, thick, names):
    """Spheres on the chest's bones whose backs are the garment's back, for hair that lies on
    it (`Hair.hang_chains`). Combed close to the back, such hair is a few millimetres off the
    cloth at rest; it hangs from the head, so when the head tips or the chest leans the hair
    would pass into the back. The game holds each hair joint out of these spheres. Each is
    made no larger than leaves every joint clear of it at rest, so they do not move the hair
    as it was combed."""
    BACK_SPHERES.clear()
    BACK_ROOTS.clear()
    ROPE_ROOTS.clear()
    pts, hits = [], []
    for ci in sorted(set(h.hang_chains) | set(h.rope_chains)):
        js = [np.array(hw(p)) for p in (h.chains[ci].get("joints") or [])]
        # Only the chains behind the body: one beside the neck hangs in front of the back's
        # plane, inside any sphere large enough to be the back, and keeps the spheres it had.
        if len(js) >= 2 and names.get(ci) and float(np.mean([p[1] for p in js])) < -0.06:
            rope = ci in h.rope_chains
            (ROPE_ROOTS if rope else BACK_ROOTS).add(names[ci][0])
            new = js + [js[-1] + (js[-1] - js[-2]) / max(np.linalg.norm(js[-1] - js[-2]), 1e-9) * 0.07]  # a leaf's tail, as the game places it
            pts += new
            hits += [ROPE_HIT if rope else HIT] * len(new)
    if not pts:
        return
    hits = np.array(hits)
    pts = np.array(pts)
    half_w, R = shoulder_half()[0] + 0.035, 0.25
    for z in (1.50, 1.44, 1.37, 1.29, 1.21, 1.13):
        # The bone that carries the back at this height; on a woman's form the heights here are
        # where the hair hangs (beside the head), and the back there is lower in the file.
        zr = STANCE.rest(STANCE.beside_head(z)) if STANCE else z
        bone = "J_Bip_C_UpperChest" if zr >= 1.31 else ("J_Bip_C_Chest" if zr >= 1.18 else "J_Bip_C_Spine")
        deep = float(np.interp(z, back[0], back[1])) + thick * GIRTH
        for x in ((-0.6 * half_w, -0.22 * half_w, 0.22 * half_w, 0.6 * half_w) if STANCE else (-0.11, -0.04, 0.04, 0.11)):
            # The sphere's back point is OFF_CLOTH behind the cloth. Its radius is the largest that leaves every
            # joint clear at rest: a smaller sphere through the same point clears a joint above
            # or beside it (at the nape, the hair is nearer than the back below is).
            b = np.array([x, -deep * math.sqrt(1 - (x / half_w) ** 2) - OFF_CLOTH, z])
            clear = lambda r: float((np.linalg.norm(pts - (b + np.array([0.0, r, 0.0])), axis=1) - hits).min()) - r - 0.0005
            lo, hi = 0.0, R
            if clear(hi) < 0:
                for _ in range(24):
                    mid = 0.5 * (lo + hi)
                    lo, hi = (mid, hi) if clear(mid) >= 0 else (lo, mid)
                hi = lo
            if hi > 0.03:
                centre = b + np.array([0.0, hi, 0.0])
                if STANCE:
                    # Written so that the client's scales on the bone put it there: the offset
                    # from the bone and the radius are scaled with the bone's own vertices.
                    sc = STANCE.scale[bone]
                    centre = np.array(STANCE.to_rest(bone, (centre[0], centre[1], STANCE.beside_head(centre[2]))))
                    hi = hi / (0.5 * (sc[0] + sc[2]))
                BACK_SPHERES.append((bone, tuple(centre), hi))
    if not BACK_SPHERES:
        return
    print(f"PERSON hair: {len(BACK_SPHERES)} spheres on the back for {len(BACK_ROOTS)} chains and {len(ROPE_ROOTS)} ropes, radius {min(s[2] for s in BACK_SPHERES):.3f} to {max(s[2] for s in BACK_SPHERES):.3f} of {R}: " + " ".join(f"{s[2]:.3f}" for s in BACK_SPHERES) if BACK_SPHERES else "PERSON hair: no back spheres")


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
        # On a face type's head the chains hang under the cranium's bone, so a wider or taller
        # skull moves their roots with the hair.
        parent = arm.data.edit_bones["J_Id_Cranium" if TYPED and "J_Id_Cranium" in arm.data.edit_bones else "J_Bip_C_Head"]
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
    obs = [face_out(raw_object("Kerchief", verts, [list(f) for f in cf], [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["cloth"], arm))]
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
    obs.append(raw_object("KerchiefKnot", verts, faces, [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["cloth"], arm))
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
    obs = [face_out(raw_object("Cap", verts, [list(f) for f in cf], [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["cloth"], arm))]
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
    obs.append(raw_object("CapPeak", verts, faces, [{"J_Bip_C_Head": 1.0}] * len(verts), cols, MAT["cloth"], arm))
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
    return raw_object("Buttons", verts, faces, weights, cols, MAT["cloth"], arm, orient=True)


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


def make_mitt(part):
    """The far model's left hand: the palm and the fingers as one flat block that curls with the
    middle finger's bones, and a stub of a thumb."""
    hand = {"J_Bip_L_Hand": 1.0}
    y0, z0 = ARM_Y, ARM_Z
    k = HAND_K
    mid = "J_Bip_L_Middle"
    stations = [
        (0.045, 0.000, 0.0265, 0.0215, {"J_Bip_L_LowerArm": 1.0}),
        (0.000, 0.000, 0.0280, 0.0195, blend(("J_Bip_L_LowerArm", 0.5), ("J_Bip_L_Hand", 0.5))),
        (-0.045 * k, 0.003 * k, 0.0420 * k, 0.0170 * k, hand),
        (-0.098 * k, 0.001 * k, 0.0440 * k, 0.0140 * k, blend(("J_Bip_L_Hand", 0.6), (mid + "1", 0.4))),
        (-0.142 * k, 0.001 * k, 0.0400 * k, 0.0115 * k, blend((mid + "1", 0.5), (mid + "2", 0.5))),
        (-0.185 * k, 0.001 * k, 0.0330 * k, 0.0095 * k, {mid + "3": 1.0}),
    ]
    prev = None
    for i, (dx, dy, hy, hz, w) in enumerate(stations):
        cur = ring(part, (WRIST_X + dx, y0 + dy, z0), (0, 1, 0), (0, 0, 1), hy, hz, 6, w, p=0.62)
        if prev:
            part.band(prev, cur, i - 1, i, tag=1 if i == len(stations) - 1 else 0)
        prev = cur
    part.fan(prev, part.v((WRIST_X - 0.196 * k, y0, z0), {mid + "3": 1.0}), len(stations), tag=1)
    e1 = THUMB_DIR.cross(Vector((0, 0, 1))).normalized()
    e2 = e1.cross(THUMB_DIR).normalized()
    prev = None
    for i, (s_, r, w) in enumerate(((-0.014, 1.0, hand), (sum(THUMB_LEN) * 0.55, 0.95, {"J_Bip_L_Thumb2": 1.0}))):
        cur = ring(part, THUMB_ROOT + THUMB_DIR * s_, e1, e2, THUMB_R * r, THUMB_R * r * 0.92, 4, w)
        if prev:
            part.band(prev, cur, i - 1, i)
        prev = cur
    part.fan(prev, part.v(THUMB_ROOT + THUMB_DIR * sum(THUMB_LEN), {"J_Bip_L_Thumb3": 1.0}), 2, tag=1)
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


# The tones inside a coat or a smock, as lightness against its own cloth (linear light): the hem,
# the shoulders, the three patches (elbows, the skirt's front, the back) and the collar's lining.
# A shared piece is grey shading that the client tints to the wearer's colour, so it can carry a
# darker hem only as a tone, the same for every wearer. A person's own file is painted with the
# same tones, so the two agree: mixed toward a fixed colour, as they were, a hem came out 0.58
# to 1.37 times its cloth's lightness by the cloth (lighter on dark cloth), the shoulders 1.09
# to 2.17, and a patch anything from 0.12 to 7.4.
HEM_TONE, SHOULDER_TONE = 0.66, 1.15
PATCH_TONES = (1.45, 0.78, 0.60)
LINING_TONE = 0.45


def lightness(c):
    r, g, b = lin(c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def relit(c, level):
    """The colour c at a given lightness (linear light): its hue kept, its channels scaled."""
    k = level / max(lightness(c), 1e-5)
    return tuple(min(max(1.055 * (x * k) ** (1 / 2.4) - 0.055 if x * k > 0.0031308 else 12.92 * x * k, 0.0), 1.0) for x in lin(c))


def coat_colour(base, patches, bands=False):
    """A coat's or a smock's paint. `bands`: a smock's sleeve bands alone, which are a piece of
    their own in their own cloth (the first patch's), not a tone of the smock's."""
    level = lightness(base)

    def colour(tag, u, v, co, n):
        # Wet and tarred toward the hem; salt-faded on the shoulders: the hue leans as it did,
        # the lightness is the cloth's own times a tone.
        low, high = smooth((0.86 - co.z) / 0.2), smooth((co.z - 1.40) / 0.08)
        c = mix(mix(base, PAL["kelp"], 0.40 * low), PAL["old_lime"], 0.16 * high)
        c = relit(c, level * lerp(1.0, HEM_TONE, low) * lerp(1.0, SHOULDER_TONE, high))
        if tag in (4, 5, 6):  # patches: other cloth, never matching, at a set tone of this one
            c = patches[tag - 4] if bands else relit(patches[tag - 4], level * PATCH_TONES[tag - 4])
        elif tag == 7:  # collar lining
            c = relit(mix(PAL["kelp"], PAL["tar"], 0.3), level * LINING_TONE)
        elif tag == 8:  # an apron
            c = mix(PAL["old_lime"], PAL["driftwood"], 0.15 + 0.25 * smooth((0.75 - co.z) / 0.3))
        elif tag == 9:  # its band
            c = mix(PAL["old_lime"], PAL["driftwood"], 0.6)
        return mottle(c, co, 0.09)

    return colour


# A woman's form, as she stands in the game: at a height (percent of her height), the torso's
# half width, half depth and how far its middle stands before the hips' joint, each a percent of
# her height. Measured on the reference with reference/body.py (docs/CHARACTERS.md, "The body");
# only these proportions are taken from it. Below the crotch (52%) it is what a skirt hangs from:
# as deep as the seat behind and the thighs in front, so a stride does not come through it.
WOMAN_FORM = [
    (40.0, 9.60, 6.00, 0.00),
    (49.0, 9.60, 6.00, 0.00),
    (51.5, 9.50, 5.60, -0.20),
    (53.2, 9.44, 5.10, -0.33),
    (55.6, 9.13, 5.25, -0.43),
    (57.2, 8.64, 5.47, -0.35),
    (58.8, 8.13, 5.61, 0.00),
    (60.4, 7.71, 5.51, 0.68),
    (62.0, 7.00, 4.95, 1.43),
    (63.6, 6.45, 4.54, 1.85),
    (65.2, 5.80, 4.38, 2.33),
    (66.8, 5.43, 4.16, 2.56),
    (68.4, 5.55, 4.17, 2.44),
    (70.0, 5.81, 4.49, 2.19),
    (71.6, 6.06, 4.75, 2.02),
    (73.2, 6.30, 5.50, 2.25),
    (74.4, 6.55, 5.80, 2.10),
    (75.6, 6.90, 5.60, 1.65),
    (76.4, 7.10, 5.20, 1.10),
    (77.2, 7.00, 4.79, 0.56),
    (78.0, 6.60, 4.57, 0.32),
    (79.6, 6.50, 4.15, -0.13),
    (81.2, 6.40, 3.38, -0.32),
    (82.4, 6.30, 2.60, -1.00),
]
WOMAN_GIRTH = 1.02  # the girth the form above is drawn at: a woman of weight and muscle 0


class Stance:
    """How a figure with a recipe's proportions stands in the game: the client's scale on each of
    the torso's bones (characters.rs `bone_scale`, at build 1) and each joint's height above
    the floor. Every file has the one rest skeleton, so a woman's narrow shoulders, short torso
    and long legs are these scales, and her pieces are written so that they come out as
    WOMAN_FORM once the client has applied them: a width is divided by the scale across of the
    bones that carry it, and looked up at the height the point will stand at."""

    def __init__(self, p):
        get = lambda k: p.get(k, 1.0)
        sh, hips, torso = get("shoulders"), get("hips"), get("torso")
        # (across, up, deep)
        self.scale = {
            "J_Bip_C_Hips": (hips, 1.0, hips ** 0.5), "J_Bip_C_Spine": (lerp(1.0, hips, 0.5), torso, 1.0), "J_Bip_C_Chest": (lerp(1.0, sh, 0.5), torso, 1.0),
            "J_Bip_C_UpperChest": (sh, torso, 1.0), "J_Bip_C_Neck": (1.0, get("neck"), 1.0), "J_Bip_L_Shoulder": (sh, 1.0, 1.0), "J_Bip_R_Shoulder": (sh, 1.0, 1.0),
        }
        z = lambda n: JOINTS[n][2]
        ankle = z("J_Bip_L_Foot") * get("feet")
        hip = ankle + (z("J_Bip_L_UpperLeg") - z("J_Bip_L_Foot")) * get("legs")
        at = {"J_Bip_C_Hips": hip + z("J_Bip_C_Hips") - z("J_Bip_L_UpperLeg")}
        for parent, child in (("J_Bip_C_Hips", "J_Bip_C_Spine"), ("J_Bip_C_Spine", "J_Bip_C_Chest"), ("J_Bip_C_Chest", "J_Bip_C_UpperChest"), ("J_Bip_C_UpperChest", "J_Bip_C_Neck"), ("J_Bip_C_Neck", "J_Bip_C_Head")):
            at[child] = at[parent] + (z(child) - z(parent)) * self.scale[parent][1]
        self.at = at
        self.hip_joint = hip
        self.legs = get("legs")
        size = person_params.face_types.load()["file"]  # the chin's height and the head's, in every file
        self.height = at["J_Bip_C_Head"] + (size["chin_m"] + size["head_height_m"] - z("J_Bip_C_Head")) * get("head")

    def _of(self, w, i):
        total = sum(w.values())
        return sum(v * self.scale.get(n, (1.0, 1.0, 1.0))[i] for n, v in w.items()) / total

    def across(self, w):
        return self._of(w, 0)

    def deep(self, w):
        return self._of(w, 2)

    def up(self, z, w):
        """The height above the floor a point at rest height z stands at, carried by weights w."""
        total = sum(w.values())
        hips = "J_Bip_C_Hips"
        return sum(v * (self.at.get(n, self.at[hips]) + self.scale.get(n, (1.0, 1.0, 1.0))[1] * (z - JOINTS[n if n in self.at else hips][2])) for n, v in w.items()) / total

    def maps(self):
        """Each bone's place and scale as the client poses it, for the bones that carry the clothes
        over the belly and the hips: {bone: (scale, where it stands, where it is at rest)}, each
        (across, forward, up). `J_Fit_Belly` has no scale of its own in the client (it hangs from
        the spine, whose scale moves it), so its vertices keep their size where the spine's are
        scaled."""
        if getattr(self, "_maps", None):
            return self._maps
        out = {}
        fwd = {"J_Bip_C_Hips": JOINTS["J_Bip_C_Hips"][1]}
        chain = ("J_Bip_C_Hips", "J_Bip_C_Spine", "J_Bip_C_Chest", "J_Bip_C_UpperChest")
        for parent, child in zip(chain, chain[1:]):
            fwd[child] = fwd[parent] + (JOINTS[child][1] - JOINTS[parent][1]) * self.scale[parent][2]
        for b in chain:
            sc = self.scale[b]
            out[b] = ((sc[0], sc[2], sc[1]), (0.0, fwd[b], self.at[b]), JOINTS[b])
        sp, r = self.scale["J_Bip_C_Spine"], JOINTS["J_Fit_Belly"]
        out["J_Fit_Belly"] = ((1.0, 1.0, 1.0), (0.0, fwd["J_Bip_C_Spine"] + (r[1] - JOINTS["J_Bip_C_Spine"][1]) * sp[2], self.at["J_Bip_C_Spine"] + (r[2] - JOINTS["J_Bip_C_Spine"][2]) * sp[1]), r)
        hips, leg = self.scale["J_Bip_C_Hips"], JOINTS["J_Bip_L_UpperLeg"]
        for side, name in ((1.0, "J_Bip_L_UpperLeg"), (-1.0, "J_Bip_R_UpperLeg")):
            out[name] = ((1.0, 1.0, self.legs), (side * leg[0] * hips[0], leg[1] * hips[2], self.hip_joint), (side * leg[0], leg[1], leg[2]))
        self._maps = out
        return out

    def stands(self, weights, point):
        """Where a point at rest stands, carried by `weights`; None if a bone of them is not in `maps`."""
        m = self.maps()
        if any(n not in m for n in weights):
            return None
        total = sum(weights.values())
        return tuple(sum(w * (m[n][1][k] + m[n][0][k] * (point[k] - m[n][2][k])) for n, w in weights.items()) / total for k in range(3))

    def written(self, weights, stand):
        """The rest place of a point that is to stand at `stand`, carried by `weights` (the inverse of `stands`)."""
        m = self.maps()
        total = sum(weights.values())
        return tuple((stand[k] - sum(w * (m[n][1][k] - m[n][0][k] * m[n][2][k]) for n, w in weights.items()) / total) / (sum(w * m[n][0][k] for n, w in weights.items()) / total) for k in range(3))

    def beside_head(self, z):
        """The height above the floor of what hangs from the head at rest height z: hair is not
        scaled with the torso, so a lock that ends at z in the file ends this high on her."""
        return z - JOINTS["J_Bip_C_Head"][2] + self.at["J_Bip_C_Head"]

    def form(self, height):
        """The form at a height above the floor, in metres: (half width, half depth, middle forward)."""
        return tuple(v * self.height / 100.0 for v in table(WOMAN_FORM, 100.0 * height / self.height))

    def to_rest(self, bone, point):
        """Where to write a point (x, forward, height above the floor) that is to stand there,
        carried by one bone: the client scales its offset from the bone."""
        s, r = self.scale[bone], JOINTS[bone]
        return (point[0] / s[0], r[1] + (point[1] - r[1]) / s[2], r[2] + (point[2] - self.at[bone]) / s[1])

    def rest(self, height):
        """The rest height of the torso's point that stands at a height above the floor."""
        lo, hi = 0.5, 1.6
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if self.up(mid, torso_w(mid, 0.0)) < height else (lo, mid)
        return 0.5 * (lo + hi)


STANCE = None  # a woman's form: the standard woman's stance (configure)


def shoulder_half():
    """The proxy hair is combed over: the shoulders' half width and half depth, without ease."""
    if STANCE:
        return abs(SHOULDER.x) * STANCE.scale["J_Bip_C_UpperChest"][0] * GIRTH / WOMAN_GIRTH, STANCE.form(STANCE.beside_head(1.44))[1] * GIRTH / WOMAN_GIRTH
    return 0.182 * GIRTH, 0.108 * GIRTH


def back_table():
    """How far behind the body's axis the back of a jersey lies, by height, plus 4 mm: (heights,
    depths), for the hair that hangs down it. Measured on the pieces at the standard build for a
    man. A woman's is her form's own back at the height each point of the hair hangs beside (her
    torso is shorter under the same head), with the jersey's 8 mm; from the collar up it is the
    neck's, which no bone scales."""
    if not STANCE:
        return ((0.95, 1.10, 1.20, 1.30, 1.35, 1.40, 1.44, 1.47, 1.50, 1.53), tuple(v * GIRTH for v in (0.123, 0.110, 0.110, 0.120, 0.125, 0.126, 0.119, 0.115, 0.062, 0.052)))
    zs = (0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.40, 1.44, 1.47)
    deep = []
    for z in zs:
        _, b, c = STANCE.form(STANCE.beside_head(z))
        deep.append((b - c) * GIRTH / WOMAN_GIRTH + 0.012)
    return (zs + (1.50, 1.53), tuple(deep) + (0.062, 0.052))


def across(w):
    """The scale across that the standard figure's bones give a point with weights w (1 for a man)."""
    return STANCE.across(w) if STANCE else 1.0


def configure(spec):
    """Set the generator's numbers for a person (person_params.resolve's result)."""
    g = globals()
    look = spec["look"]
    typed = spec.get("type") is not None
    if typed:
        # A person of a face type: the type's cage head, in a character file's own size. Their
        # values are left to the identity bones, or with `baked` built into the head itself.
        import face_types

        t = face_types.load()["types"][spec["type"]]
        head = cage_head.CageHead(face_types.apply(t, {}), masc=spec["masc"], child=spec["child"], elder=spec["elder"])
    else:
        head = head_form.Head(masc=spec["masc"], child=spec["child"], elder=spec["elder"], face=spec["face"], style=spec["style"])
    g.update(
        HF=head, TYPED=typed, HEAD_SCALE=1.0 if typed else spec["head_scale"], SKIN=look["skin"], SKIN_SHADE=look["skin_shade"], SKIN_WARM=look["skin_warm"],
        HAIR=look["hair"], HAIR_TIP=look["hair_tip"], RECEDE=spec["recede"], BALD=spec["bald"], LIMB_K=spec["limb"], GIRTH=spec["girth"], BELLY=spec["belly"], CHEST=spec["chest"], LONG=spec["hair_length"],
        STANCE=Stance(person_params.WOMAN) if spec["woman_torso"] else None,
    )
    # The neck's radius: the type's own, so the head's ring and the neck's tube meet. An outfit
    # piece is built for a man's or a woman's neck, whatever head its figure stands under.
    if spec.get("piece"):
        g["NECK_R"] = head_form.neck_radius(0.0 if spec["woman_torso"] else 1.0)
    elif typed:
        g["NECK_R"] = cage_head.neck_radius_of(face_types.load()["types"][spec["type"]])
    else:
        g["NECK_R"] = head_form.neck_radius(spec["masc"], spec["child"])
    # The chin stays where the neck expects it, whatever the face's length.
    g["HEAD"] = Vector((0, -0.004, 1.535 - HF.chin_z * HEAD_SCALE))



def build_person(arm, spec, atlas_path, body=False, bones=None):
    """Every part of a person, as separate objects (join_kinds joins them by shading kind). With
    FAR set these are the far model's parts; `bones` then names the full model's hair bones,
    when it was built first."""
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
            collar=[(0.011, -0.002, blend(("J_Bip_C_Neck", 0.8), ("J_Bip_C_UpperChest", 0.2))), (0.022, -0.002, neck), (0.026, -0.005, neck), (0.020, -0.009, neck)], tag_fn=jtag,
        ).mirrored()
        obs.append(build(p, arm, MAT["cloth"], jersey_colour(spec["jersey"])))
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
                hem=[], cuff=(-0.640, [(-0.030, 0.006)]), collar=[(0.020, 0.004, chest), (0.042, 0.009, chest)],
                front=lambda z: lerp(0.058, 0.026, smooth((z - 0.70) / 0.75)), skirt=1.0, tag_fn=ctag, neck_d=0.019,
            ).mirrored()
            obs.append(build(p, arm, MAT["cloth"], coat_colour(spec["coat_colour"], spec["patches"]), solid=0.006))
            if not FAR:
                obs.append(make_buttons(arm))
        elif coat == "smock":
            # A pull-over smock to the knee, an apron tied over it.
            zs = [z for z in (0.50, 0.58, 0.66, 0.74, 0.82, 0.90, 0.98, 1.06, 1.13, 1.20, 1.26, 1.32) if z >= hem - 1e-6]
            band = zs.index(1.13 if STANCE else 1.06)  # the apron's tie: at the waist, which a woman's form has higher
            apron = spec["apron"]

            def btag(kind, k, r):  # the sleeve bands alone: a part of their own, so they take a colour of their own
                if kind == "sleeve" and r in (3, 4):
                    return 4
                return Part.HIDE

            def atag(kind, k, r):  # the apron alone: a part of its own, so it takes a colour of its own
                if kind == "torso" and r == band:
                    return 9
                if kind == "torso" and k <= 2 and r < band:
                    return 8
                return Part.HIDE

            p = upper_garment(
                Part("Smock"), 0.018, zs, hem=[(-0.004, -0.008)], cuff=(-0.655, [(-0.022, 0.004), (-0.024, -0.004)]),
                collar=[(0.020, 0.006, chest), (0.022, -0.002, chest)], skirt=1.0, neck_d=0.014,
            ).mirrored()
            obs.append(build(p, arm, MAT["cloth"], coat_colour(spec["coat_colour"], spec["patches"])))
            # The bands round the sleeves, in another cloth: over the smock's own sleeve, a hair's
            # width out. Its own part, so a shared smock's bands are a piece with its own colour.
            p = upper_garment(Part("SmockBands"), 0.0188, zs, hem=[], cuff=(-0.655, []), collar=[], skirt=1.0, tag_fn=btag, neck_d=0.0148).mirrored()
            obs.append(build(p, arm, MAT["cloth"], coat_colour(spec["coat_colour"], spec["patches"], bands=True)))
            if apron:
                p = upper_garment(Part("Apron"), 0.0198, zs, hem=[], cuff=(-0.655, []), collar=[], skirt=1.0, tag_fn=atag, neck_d=0.0158).mirrored()
                obs.append(build(p, arm, MAT["cloth"], coat_colour(spec["coat_colour"], spec["patches"])))
        # Trousers, tucked into the boots.
        p = trousers(Part("Trousers"), 0.012).mirrored()
        obs.append(build(p, arm, MAT["cloth"], lambda tag, u, v, co, n: mottle(mix(PAL["iron"], PAL["slate"], 0.25 + 0.10 * (int(u * 44) % 2)), co, 0.08)))
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
        obs.append(build(p, arm, MAT["cloth"], boot_colour, post=flat_sole))
    # Hands.
    p = (make_mitt if FAR else make_hand)(Part("Hands")).mirrored()
    obs.append(build(p, arm, MAT["skin"], lambda tag, u, v, co, n: mix(SKIN, SKIN_WARM, 0.30) if tag == 1 else SKIN))
    # Head and face, neck, hair, beard, headwear.
    head, pos, quads = make_far_head(arm, spec, atlas_path) if FAR else make_face(arm, spec, atlas_path)
    obs.append(head)
    obs.append(make_neck(arm))
    covered = dict(kerchief=lambda p: min(kerchief_depth(p), (p[2] + 0.070) * 2), cap=cap_depth).get(spec["headwear"])
    if not WHOLE_HEAD:  # a face type's own file has no hair: a style brings its own, with its spring bones
        obs += make_hair(arm, spec, pos, quads, covered, bones)
    if spec["headwear"] == "kerchief":
        obs += make_kerchief(arm, pos, quads, spec["headwear_colour"])
    elif spec["headwear"] == "cap":
        obs += make_cap(arm, pos, quads, spec["headwear_colour"])
    return obs


# ---------------------------------------------------------------------------------------------
# Painted shade: how closed-in each vertex is, multiplied into its colour.

AO_FLAT = ("Face", "FarHead")  # the face shades others (the neck under the jaw) but takes none: its shade is painted
AO_SOFT = {"Neck": 0.7, "Hands": 0.6}


def painted_pieces(parts, line):
    """Give each outfit piece in a person's line the colour it is painted in this file: the mean
    of the piece's vertex colours as built and shaded, by area, in linear light. The client
    moves a shared piece's mean to the line's colour, so the line must carry the colour as it
    appears. The cloth a piece is cut from is more saturated than its paint (the weave, the
    wear and the painted shade pale and darken it), and tinted with that, a composed person's
    clothes came out stronger than their own file's."""
    by = {}
    for ob in parts:
        me = ob.data
        attr = me.color_attributes.get("Color")
        if attr is None or not len(me.polygons):
            continue
        data = np.empty(len(me.loops) * 4, np.float32)
        attr.data.foreach_get("color", data)
        data = data.reshape(-1, 4)[:, :3].astype(float)
        tot, area = np.zeros(3), 0.0
        for p in me.polygons:
            tot += data[list(p.loop_indices)].mean(axis=0) * p.area
            area += p.area
        by.setdefault(ob.name.split(".")[0], []).append((tot, area))
    outfit = line["colors"].get("outfit", {})
    for piece in list(outfit):
        tot, area = np.zeros(3), 0.0
        for part in person_params.piece_parts(piece):
            for t, a_ in by.get(part, []):
                tot, area = tot + t, area + a_
        if area > 0:
            outfit[piece] = person_params.hexed([1.055 * x ** (1 / 2.4) - 0.055 if x > 0.0031308 else 12.92 * x for x in tot / area])


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


BELLY_PARTS = ("Jersey", "Coat", "Buttons", "Smock", "Apron")
BELLY_REACH = 0.108  # metres the belly's bone moves forward for a belly of 1 (the torso's half depth)


def belly_weights(obs):
    """Give the clothes in front of the belly a share of `J_Fit_Belly`: the same bell by height the
    generator's own belly has (torso_point), on the front half. With the bone at rest nothing
    changes; moved forward by belly x BELLY_REACH it stands a belly out on any piece."""
    for ob in obs:
        if ob.name.split(".")[0] not in BELLY_PARTS:
            continue
        g = ob.vertex_groups.get("J_Fit_Belly") or ob.vertex_groups.new(name="J_Fit_Belly")
        names = {vg.index: vg.name for vg in ob.vertex_groups}
        for v in ob.data.vertices:
            w = math.exp(-(((v.co.z - 1.07) / 0.13) ** 2)) * smooth((v.co.y - 0.01) / 0.07) * smooth((0.24 - abs(v.co.x)) / 0.06)
            if w < 0.01:
                continue
            # On a woman's form the piece was written for the scales of the bones that carried
            # it. The belly's bone has none, so a vertex it now shares is written again for the
            # weights it ends with: it stands where it was meant to (a jersey's front otherwise
            # came through the trousers it is tucked into, by 3 to 5 mm).
            before = {names[x.group]: x.weight for x in v.groups if x.weight > 0} if STANCE else None
            stand = STANCE.stands(before, tuple(v.co)) if before else None
            for x in v.groups:
                x.weight *= 1.0 - w
            g.add([v.index], w, "REPLACE")
            if stand is not None:
                after = {n: x * (1.0 - w) for n, x in before.items() if n != "J_Fit_Belly"}
                after["J_Fit_Belly"] = w
                v.co = STANCE.written(after, stand)


def spread_head_weights(obs):
    """On a typed head, what hangs on the head (hair, headwear, the neck's top, the far head)
    follows the identity bones as the face does: each vertex's weight to `J_Bip_C_Head` is
    shared out by where the vertex lies."""
    for ob in obs:
        g = ob.vertex_groups.get("J_Bip_C_Head")
        if g is None or ob.name.split(".")[0] == "Face":
            continue
        me = ob.data
        idx, share = [], []
        for v in me.vertices:
            w = next((x.weight for x in v.groups if x.group == g.index), 0.0)
            if w > 1e-4:
                idx.append(v.index)
                share.append(w)
        if not idx:
            continue
        pts = np.array([(np.array(me.vertices[i].co) - np.array(HEAD)) / HEAD_SCALE for i in idx])
        groups = {}
        # The far head has its brows painted on its skin, which follows the brows' bones as the
        # face's own skin does; what hangs on the head does not.
        for i, w, parts in zip(idx, share, cage_head.identity_weights(HF, pts, brows=ob.name.split(".")[0] == "FarHead")):
            g.remove([i])
            for n, x in parts.items():
                vg = groups.get(n) or ob.vertex_groups.get(n) or ob.vertex_groups.new(name=n)
                groups[n] = vg
                vg.add([i], w * x, "ADD")


def bake_identity(obs, values):
    """Build a person's identity values into the meshes themselves: every vertex (and every
    expression's) is moved as the identity bones would move it, by the same rule the client
    uses (compose.transforms) and the weights the file carries. The bones stay at rest. The
    result is the same person as the type's file composed by bones, as plain geometry."""
    mats = cage_head.bone_matrices(HF, values)
    origin = np.array(HEAD)
    for ob in obs:
        me = ob.data
        names = {g.index: g.name for g in ob.vertex_groups}
        n = len(me.vertices)
        # Each vertex's matrix: the bones' own, by weight; what is not an identity bone's stays put.
        M = np.zeros((n, 4, 4))
        left = np.ones(n)
        total = np.zeros(n)
        for v in me.vertices:
            for g in v.groups:
                total[v.index] += g.weight
        for v in me.vertices:
            for g in v.groups:
                name = names[g.group]
                if name in mats and name != "J_Bip_C_Head" and total[v.index] > 0:
                    w = g.weight / total[v.index]
                    M[v.index] += w * mats[name]
                    left[v.index] -= w
        M += left[:, None, None] * np.eye(4)[None, :, :]

        def moved(co):
            p = np.concatenate([co - origin, np.ones((n, 1))], axis=1)
            return np.einsum("nij,nj->ni", M, p)[:, :3] + origin

        if me.shape_keys:
            for key in me.shape_keys.key_blocks:
                co = np.empty(n * 3)
                key.data.foreach_get("co", co)
                key.data.foreach_set("co", moved(co.reshape(-1, 3)).ravel())
        co = np.empty(n * 3)
        me.vertices.foreach_get("co", co)
        me.vertices.foreach_set("co", moved(co.reshape(-1, 3)).ravel())
        me.update()


# ---------------------------------------------------------------------------------------------
# One mesh per shading kind.


def join_kinds(obs, far=False):
    """Join a person's parts into one object per shading kind, so the game draws six meshes a
    person and not a dozen: `Cloth` (every garment, buttons, ties and headwear), `Skin` (hands
    and neck), `Face` (its skin, eyes and lines are three materials, so three meshes) and
    `Hair`. The far model is three: `FarCloth`, `FarSkin` (head, neck and hands, on the far
    picture) and `FarHair`. Returns the joined objects."""
    skin_parts = ("Hands", "Neck", "FarHead") if far else ("Hands", "Neck")
    groups = {}
    for ob in obs:
        name = ob.name.split(".")[0]  # Blender numbers a name that is taken (the full model's `Hair`)
        kind = "Skin" if name in skin_parts else ("Face" if name == "Face" else ("Hair" if name == "Hair" else ("Overlay" if name == "Overlay" else "Cloth")))
        groups.setdefault(kind, []).append(ob)
    if far and "Skin" in groups:
        # Hands and neck take the far picture's swatch of plain skin: their colours become
        # shades of it, as the ears' are.
        base = np.array(lin(SKIN), dtype=np.float32)
        for ob in groups["Skin"]:
            me = ob.data
            if ob.name.split(".")[0] == "FarHead":
                continue
            attr = me.color_attributes["Color"]
            data = np.empty(len(me.loops) * 4, dtype=np.float32)
            attr.data.foreach_get("color", data)
            data = data.reshape(-1, 4)
            data[:, :3] = np.clip(data[:, :3] / base[None, :], 0, 1)
            attr.data.foreach_set("color", data.ravel())
            for layer in list(me.uv_layers):
                me.uv_layers.remove(layer)
            uvl = me.uv_layers.new(name="UVMap")
            uvl.data.foreach_set("uv", np.tile(np.array(head_mesh.SWATCH_UV, dtype=np.float32), len(me.loops)))
            me.materials.clear()
            me.materials.append(material(MAT["far"]))
    out = []
    for kind in ("Cloth", "Skin", "Face", "Hair", "Overlay"):
        parts = groups.get(kind)
        if not parts:
            continue
        # The object whose custom normals or shape keys must survive leads the join.
        lead = next((o for o in parts if o.name.split(".")[0] in ("FarHead", "Face", "Hair")), parts[0])
        if len(parts) > 1:
            with bpy.context.temp_override(active_object=lead, object=lead, selected_objects=parts, selected_editable_objects=parts):
                bpy.ops.object.join()
        lead.name = ("Far" if far else "") + kind
        lead.data.name = lead.name
        out.append(lead)
    return out


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
    k = 0.010 - HIT  # these were sized for a joint radius of 10 mm, and reach as far with the smaller one
    colliders = [
        {"node": nodes["J_Bip_C_Head"], "colliders": [sphere("J_Bip_C_Head", hc, 0.074 * HEAD_SCALE + k), sphere("J_Bip_C_Head", hc + Vector((0, 0.014, -0.070)) * HEAD_SCALE, 0.046 * HEAD_SCALE + k)]},
        {"node": nodes["J_Bip_C_Neck"], "colliders": [sphere("J_Bip_C_Neck", (0, cage_head.NECK_Y, 1.50), NECK_R + 0.004 + k)]},
        {"node": nodes["J_Bip_C_UpperChest"], "colliders": [sphere("J_Bip_C_UpperChest", (0, -0.005, 1.32), 0.105 * GIRTH + k), sphere("J_Bip_C_UpperChest", (-0.12, -0.012, 1.385), 0.055 + k),
                                                             sphere("J_Bip_C_UpperChest", (0.12, -0.012, 1.385), 0.055 + k)]},
    ]
    # Stiff enough to settle within half a second of a jump in pose (the asset view photographs
    # 0.6 s after posing), loose enough to swing in a walk.
    by_bone = {}
    for bone, at, r in BACK_SPHERES:
        by_bone.setdefault(bone, []).append(sphere(bone, at, r))
    colliders += [{"node": nodes[bone], "colliders": spheres} for bone, spheres in by_bone.items() if bone in nodes]
    group = lambda comment, chains, which, hit=HIT: {"comment": comment, "stiffiness": 2.0, "gravityPower": 0.10, "gravityDir": {"x": 0, "y": -1, "z": 0}, "dragForce": 0.5, "center": -1,
                                                     "hitRadius": hit, "bones": [nodes[chain[0]] for chain in chains], "colliderGroups": list(which)}
    on_back = [c for c in springs if c[0] in BACK_ROOTS]
    ropes = [c for c in springs if c[0] in ROPE_ROOTS]
    # A tail or a braid down the back is a rope with its joints on its axis: held off the neck,
    # the chest and the back by its own radius, and not off the head it is tied on.
    groups = [group("Hair", [c for c in springs if c[0] not in BACK_ROOTS and c[0] not in ROPE_ROOTS], range(3))] + ([group("HairBack", on_back, range(len(colliders)))] if on_back else []) \
        + ([group("HairRope", ropes, range(1, len(colliders)), ROPE_HIT)] if ropes else [])
    groups = [g for g in groups if g["bones"]]
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


CLIENT_MORPHS = ("Fcl_EYE_Close", "Fcl_MTH_A")  # what the game drives (living/game/src/lookdev.rs): the blink and the open mouth
TYPE_BROW = (0.94, 0.94, 0.94)  # a type's brows in its own file, before the client colours them
TYPE_PARTS = ("Face", "Hands", "Neck", "FarHead")  # a face type's file: its head and skin, near and far


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    person_params.add_args(ap)
    ap.add_argument("--expression", default="", help="expressions the file starts with, to look at them: `Fcl_MTH_Fun=1,Fcl_BRW_Fun=1` (the game drives Fcl_EYE_Close and Fcl_MTH_A itself)")
    ap.add_argument("--look", default="", help="turn the eyes in the file, to look at it: `yaw,pitch` in degrees of the eyes' bones (about 6 is fully aside)")
    ap.add_argument("--body", action="store_true", help="the unclothed form instead of the clothes")
    ap.add_argument("--no-shade", action="store_true", help="leave out the painted shade (bake_shade)")
    ap.add_argument("--type", dest="face_type", help="a face type (living/tools/characters/types.json): the head is that type's cage, with the identity bones in it")
    ap.add_argument("--identity", default="", help="the person's identity values, `jaw_width=0.4,eye_size=-0.3` or a JSON object; with --type")
    ap.add_argument("--loft", action="store_true", help="pass 2's head (head_form's loft with the 34 face values), in place of the person's face type")
    ap.add_argument("--bake", action="store_true", help="build the identity values into the head itself (the bones stay at rest), to compare with the same person composed by bones")
    ap.add_argument("--lod", default="near", choices=("near", "far", "both"), help="`near` the full model (the default); `far` the far model alone (about 6,000 triangles, for beyond 10 m); "
                    "`both` one file with the two on one skeleton, the far model's meshes named Far*")
    ap.add_argument("--parts", default="all", choices=("all", "head", "face", "hair", "keep", "overlay"), help="`overlay`: one detail as a layer over the type's face (--overlay); "
                    "`keep`: only the parts --keep names (an outfit piece's file); "
                    "`hair`: only the hair, near and (with --lod both) far, in neutral shades to be coloured by the client's tag: a shared hair style's file; "
                    "`head`: only what a face type's file holds (the whole head, the neck and hands, and the far head with --lod both): no hair, no clothes; "
                    "`face`: the whole head and neck alone, to photograph a type")
    ap.add_argument("--morphs", default="all", choices=("all", "client"), help=f"`client`: keep only the expressions the game drives ({', '.join(CLIENT_MORPHS)}); every expression costs each vertex of the face again")
    ap.add_argument("--own-iris", action="store_true", help="with --parts head: the iris painted in this figure's own eye colour, as a whole person's is, in place of the one every type shares (to compare the two: eye_colours.py)")
    ap.add_argument("--overlay", default="", help="with --parts overlay: beard_<style>, stubble, lines or freckles")
    ap.add_argument("--keep", default="", help="with --parts keep: the parts to keep, by name, comma-separated (Jersey, Coat, Buttons, Smock, Trousers, Boots, Cap, CapPeak, Kerchief, KerchiefKnot)")
    ap.add_argument("--no-lines", action="store_true", help="leave out the shell lines at the jaw, ears and mouth (cage_head.CageFace._shell_lines), to compare")
    ap.add_argument("--blend")
    a = ap.parse_args(argv)
    if a.no_lines:
        cage_head.CageFace.LINES = False
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
    if a.loft:
        spec["type"] = None
    elif a.face_type or spec.get("type"):
        ident = {} if a.face_type and not a.identity and a.face_type != params.get("type") else dict(spec.get("identity") or {})
        if a.identity:
            ident = json.loads(a.identity) if a.identity.strip().startswith("{") else {k: float(v) for k, v in (x.split("=") for x in a.identity.split(",") if x)}
        spec.update(type=a.face_type or spec["type"], identity=ident, baked=bool(a.bake))
    if a.parts in ("head", "face"):
        # A type's own face has nothing a person adds: age lines are an overlay style, like stubble.
        spec["look"].update(lines=0.0, stubble=0.0, freckles=0.0)
    if a.parts == "head" and not a.own_iris:
        # A type's file: its iris is the one every type shares.
        spec["look"]["iris_shared"] = person_params.SHARED_IRIS
    if a.parts == "head":
        # A type's brows are coloured by the client, with the person's hair colour through the
        # mesh tag: their own tone is neutral, and lighter than any hair, so the client only
        # ever darkens it.
        spec["look"]["brow"] = TYPE_BROW
    if a.parts == "hair":
        # A shared style is coloured by the client, through the mesh tag: its own shades are
        # neutral, a little darker at the root than the tip, with no grey of its own.
        spec["look"].update(hair=(0.86, 0.86, 0.86), hair_tip=(1.0, 1.0, 1.0), hair_natural=(0.86, 0.86, 0.86), hair_natural_tip=(1.0, 1.0, 1.0), hair_grey=0.0)
    spec["piece"] = a.parts == "keep"  # an outfit piece's file: its neck hole is a man's or a woman's
    configure(spec)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    stem = os.path.splitext(out)[0]
    # Beside the model: the person's full parameters (edit and pass back with --params) and the
    # game recipe's height and proportions.
    def write_params():
        with open(stem + ".params.json", "w") as f:
            json.dump(dict(params=params, recipe=spec["recipe"], **({"type": spec["type"], "identity": spec["identity"], "baked": spec["baked"], "person": spec.get("person")} if spec.get("type") else {})), f, indent=1)

    write_params()
    g = globals()
    g["STRANDS_PATH"] = os.path.join(os.path.dirname(out), "strands.png")
    g["WHOLE_HEAD"] = a.parts in ("head", "face", "overlay")
    g["OVERLAY"] = a.overlay if a.parts == "overlay" else None
    arm = make_armature()
    obs, tris = [], {}
    for far in (False, True):
        if a.lod == ("far" if not far else "near"):
            continue
        g["FAR"] = far
        parts = build_person(arm, spec, stem + (".far.png" if far else ".atlas.png"), body=a.body, bones=spec.get("spring_bones") if far else None)
        shaded = False
        if a.parts == "keep" and not a.no_shade:
            # An outfit piece is shaded as it is worn, with the rest of the outfit and the body
            # round it (a jersey's collar under a smock's, a smock under its apron), and then
            # the rest is taken away. Shaded alone, the tones inside it were not its wearer's.
            bake_shade(parts)
            shaded = True
        if a.parts != "all":
            wanted = dict(head=TYPE_PARTS, hair=("Hair", "HairTie"), face=("Face", "Neck"), keep=tuple(x for x in a.keep.split(",") if x), overlay=("Overlay",))[a.parts]
            keep = [ob for ob in parts if ob.name.split(".")[0] in wanted]
            for ob in parts:
                if ob not in keep:
                    bpy.data.objects.remove(ob, do_unlink=True)
            parts = keep
        if a.morphs == "client":
            for ob in parts:
                if ob.data.shape_keys:
                    for key in [k for k in ob.data.shape_keys.key_blocks if k.name != "Basis" and k.name not in CLIENT_MORPHS]:
                        ob.shape_key_remove(key)
        belly_weights(parts)
        if TYPED:
            spread_head_weights(parts)
            if spec.get("baked") and spec.get("identity"):
                bake_identity(parts, spec["identity"])
        if not a.no_shade and not shaded:
            bake_shade(parts)
        if not far and a.parts == "all" and spec.get("person"):
            painted_pieces(parts, spec["person"])
        for ob in parts:
            ob.data.calc_loop_triangles()
            tris[("Far" if far and not ob.name.startswith("Far") else "") + ob.name] = len(ob.data.loop_triangles)
        obs += join_kinds(parts, far)
    g["FAR"] = False
    if a.blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.blend))
    write_params()  # again: the line's piece colours are now the painted ones
    bpy.ops.export_scene.gltf(
        filepath=out, export_format="GLB", export_yup=True, export_skins=True, export_animations=False, export_vertex_color="ACTIVE",
        export_all_vertex_colors=False, export_normals=True, export_materials="EXPORT", export_def_bones=False, export_leaf_bone=False,
        export_rest_position_armature=True, use_selection=False, export_morph=True, export_morph_normal=False,
        export_try_sparse_sk=False,  # Bevy's loader rejects sparse morph accessors
        export_attributes=True,  # the hair's `_GREY`
    )
    # The far model alone hangs rigid: it lists no spring bones, so the game simulates none.
    j = add_vrm(out, f"Cullet resident {params['seed']} ({params['sex']}, {params['age']:.0f})", spec.get("springs") if a.lod != "far" else None)
    zs = [v.co.z for ob in obs for v in ob.data.vertices]
    print(f"PERSON {out}: {params['sex']} {params['age']:.0f}y seed {params['seed']}, lod {a.lod}, {sum(tris.values())} triangles, {sum(len(m['primitives']) for m in j['meshes'])} meshes, {len(arm.data.bones)} bones, "
          f"{len(j['materials'])} materials, {len(j.get('images', []))} texture, height {max(zs) - min(zs):.3f} m, floor {min(zs):+.4f}")
    print("PERSON parts: " + ", ".join(f"{k} {v}" for k, v in tris.items()))


if __name__ == "__main__":
    main()
