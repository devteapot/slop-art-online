#!/usr/bin/env python3
"""Face types, the identity rig and the parameter model, as data (docs/CHARACTERS.md, "Types and
rig"). No mesh is built here: this is what the cage head of each type is built to (step 3 of the
plan), and what the client reads to compose a person.

    python3 living/tools/characters/face_types.py measure REF_DIR     # the anchors, from the reference's measuring tools
    python3 living/tools/characters/face_types.py build               # compose the types into types.json
    python3 living/tools/characters/face_types.py check [--people N]  # every type, and N drawn people of each, are valid heads
    python3 living/tools/characters/face_types.py draw OUT_DIR        # diagram sheets: types front and side, people, the rig
    python3 living/tools/characters/face_types.py person --seed 12 --sex female --age 29 [--family 7]
    python3 living/tools/characters/face_types.py rig                 # the bones, their values and ranges, as a table

The data is `types.json` beside this file:

- `rig`: the bones that carry identity, each under `J_Bip_C_Head` or another identity bone, and
  each bone's values: what it does (move, scale or turn, on which axis) and its range. A
  person's value runs from -1 to 1; 0 is the type. No clip keys these bones.
- `directions`: ways in which heads vary together (broad or narrow, long or short, bony or
  soft, large or small eyes). A person is drawn along these and then value by value.
- `measured`: the anchors. The reference and its sister file, measured by
  `living/tools/characters/reference/` (proportions only; nothing of theirs is used), and the
  average head of each sex and age band of the pass-2 generator, measured the same way.
- `types`: about three designed face types for each sex and age band, each a complete set of
  skull and landmark values in units of the head's height H (chin to crown), with the body
  type tied to it.

How a type is composed (`build`): the reference's measured head, plus the difference the pass-2
generator makes between that group's average head and the adult woman's (so men, elders and
children keep their own look on the reference's structure), plus the type's own line: `a`
round, toward the reference's sister file; `b` even; `c` long. The numbers are then written
out in full and can be edited by hand; `check` says whether they still make a head.

Everything is numpy and Pillow; `measure` needs the reference tool's output
(`living/tools/characters/reference/run.sh`), the rest only `types.json`.
"""

import argparse
import copy
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "types.json")
Z = [0.04, 0.12, 0.20, 0.28, 0.40, 0.52, 0.64, 0.76, 0.88]  # the heights sections are kept at, in H above the chin
BANDS = [("child", 0, 12), ("youth", 12, 18), ("adult", 18, 60), ("elder", 60, 200)]
LINES = dict(a="round", b="even", c="long")


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def lerp(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------------------------------------------
# The rig: which bones carry identity.

# (bone, parent, part, where its pivot sits, [(value, what it does, axis, least, most, unit, note)])
# Axes are the bone's own at rest, which are the head's unless a note says the bone is turned:
# x across (for a paired bone, away from the midline on both sides), y forward, z up. In a
# character file that is X, -Z and Y. `move` is in thousandths of the head's height H, so a
# value keeps its meaning on any head; `scale` is a factor; `turn` is degrees (for a paired
# bone the same sense on both sides: outer ends up, or outward). Least and most need not mirror
# each other: each direction has its own designed reach. A value named as one of pass 2's 34
# keeps that name.
RIG = [
    ("J_Id_Cranium", "J_Bip_C_Head", "skull", "the head's middle at the brow line", [
        ("cranium_width", "scale", "x", 0.94, 1.07, "×", "new"),
        ("cranium_depth", "scale", "y", 0.95, 1.06, "×", "new"),
        ("cranium_height", "scale", "z", 0.95, 1.07, "×", "new")]),
    ("J_Id_Forehead", "J_Id_Cranium", "skull", "the forehead's middle", [
        ("forehead", "move", "y", -12, 16, "‰H", "pass 2's `forehead`: low and sloping to high and full")]),
    ("J_Id_Glabella", "J_Id_Cranium", "brows", "between the brows", [
        ("brow_ridge", "move", "y", -4, 12, "‰H", "pass 2's `brow_ridge`")]),
    ("J_Id_Face", "J_Bip_C_Head", "outline", "the bridge of the nose", [
        ("face_length", "scale", "z", 0.92, 1.10, "×", "pass 2's `face_length`: everything below the eyes"),
        ("face_width", "scale", "x", 0.94, 1.07, "×", "pass 2's `face_width`")]),
    ("J_Id_Corner_L", "J_Id_Face", "outline", "the cheek corner beside the eye", [
        ("front_breadth", "move", "x", -16, 16, "‰H", "new: how broad the front planes are")]),
    ("J_Id_Zygoma_L", "J_Id_Face", "outline", "the cheekbone's point", [
        ("cheekbones", "move", "x", -12, 16, "‰H", "pass 2's `cheekbones`"),
        ("cheekbone_height", "move", "z", -12, 12, "‰H", "new")]),
    ("J_Id_Cheek_L", "J_Id_Face", "outline", "the cheek's fullest point", [
        ("cheeks", "move", "y", -12, 20, "‰H", "pass 2's `cheeks`: hollow to full; this bone is turned at rest to face out of the cheek, so its forward is the surface's normal")]),
    ("J_Id_Jaw", "J_Id_Face", "outline", "the jaw's hinge, under the ear", [
        ("jaw_width", "scale", "x", 0.88, 1.14, "×", "pass 2's `jaw_width`"),
        ("jaw_angle", "turn", "x", -4.0, 5.0, "°", "new: a steeper or flatter jaw line")]),
    ("J_Id_Gonion_L", "J_Id_Jaw", "outline", "the angle of the jaw", [
        ("jaw_square", "move", "x", -10, 14, "‰H", "pass 2's `jaw_square`: tapered to square")]),
    ("J_Id_Chin", "J_Id_Jaw", "outline", "the chin's point", [
        ("chin_length", "move", "z", -28, 20, "‰H", "pass 2's `chin_length` (down is longer)"),
        ("chin_width", "scale", "x", 0.70, 1.40, "×", "pass 2's `chin_width`: pointed to broad"),
        ("chin_forward", "move", "y", -16, 20, "‰H", "pass 2's `chin_forward`")]),
    ("J_Id_Orbit_L", "J_Id_Face", "eyes", "the eye's middle, on the skin", [
        ("eye_spacing", "move", "x", -12, 14, "‰H", "pass 2's `eye_spacing`"),
        ("eye_height", "move", "z", -14, 14, "‰H", "pass 2's `eye_height`"),
        ("socket_depth", "move", "y", -10, 8, "‰H", "new: the eye set deeper or shallower"),
        ("eye_size", "scale", "xyz", 0.88, 1.13, "×", "pass 2's `eye_size`"),
        ("eye_open", "scale", "z", 0.82, 1.18, "×", "pass 2's `eye_open`"),
        ("eye_tilt", "turn", "y", -6.0, 7.0, "°", "pass 2's `eye_tilt`: outer corners down to up")]),
    ("J_Adj_L_FaceEye", "J_Id_Orbit_L", "eyes", "behind the eye (the bone the look turns; it exists today)", [
        ("iris_size", "scale", "xyz", 0.90, 1.10, "×", "pass 2's `iris_size`")]),
    ("J_Id_Brow_L", "J_Id_Face", "brows", "the brow's middle", [
        ("brow_height", "move", "z", -12, 16, "‰H", "pass 2's `brow_height`"),
        ("brow_tilt", "turn", "y", -8.0, 8.0, "°", "pass 2's `brow_tilt`"),
        ("brow_thickness", "scale", "z", 0.70, 1.40, "×", "pass 2's `brow_thickness`"),
        ("brow_length", "scale", "x", 0.90, 1.12, "×", "pass 2's `brow_length`")]),
    ("J_Id_Nose", "J_Id_Face", "nose", "the bridge, between the eyes", [
        ("nose_length", "scale", "z", 0.85, 1.20, "×", "pass 2's `nose_length`"),
        ("nose_width", "scale", "x", 0.80, 1.25, "×", "pass 2's `nose_width`"),
        ("nose_bridge", "scale", "y", 0.80, 1.25, "×", "pass 2's `nose_bridge`: how far the nose stands out")]),
    ("J_Id_NoseTip", "J_Id_Nose", "nose", "the nose's tip", [
        ("nose_tip", "move", "z", -10, 12, "‰H", "pass 2's `nose_tip`: turned down to turned up")]),
    ("J_Id_Mouth", "J_Id_Face", "mouth", "the mouth's middle", [
        ("mouth_height", "move", "z", -12, 12, "‰H", "pass 2's `mouth_height` (down is lower)"),
        ("mouth_width", "scale", "x", 0.85, 1.18, "×", "pass 2's `mouth_width`"),
        ("lip_fullness", "scale", "z", 0.70, 1.35, "×", "pass 2's `lip_fullness`")]),
    ("J_Id_MouthCorner_L", "J_Id_Mouth", "mouth", "the mouth's corner", [
        ("mouth_curve", "move", "z", -6, 6, "‰H", "pass 2's `mouth_curve`: corners down to up")]),
    ("J_Id_Ear_L", "J_Bip_C_Head", "ears", "the ear's root", [
        ("ear_size", "scale", "xyz", 0.87, 1.20, "×", "pass 2's `ear_size`"),
        ("ear_out", "turn", "z", -8.0, 18.0, "°", "pass 2's `ear_out`")]),
]
# Bones with a mirrored twin on the character's right (the same values, mirrored).
PAIRED = ("J_Id_Corner_L", "J_Id_Zygoma_L", "J_Id_Cheek_L", "J_Id_Gonion_L", "J_Id_Orbit_L", "J_Adj_L_FaceEye", "J_Id_Brow_L", "J_Id_MouthCorner_L", "J_Id_Ear_L")
# Pass 2's values that are a shape and not a placement: a type fixes them.
FIXED_BY_TYPE = dict(eye_shape="where the upper lid peaks", eye_fold="the lid fold's depth", brow_arch="how arched the brow is")
# Blue Protocol's five face parts, and the skull above them.
PARTS = ("skull", "outline", "eyes", "brows", "nose", "mouth", "ears")
# Ways heads vary together: a person is drawn along these first (value -> share of the direction).
DIRECTIONS = dict(
    broad=dict(face_width=0.8, cranium_width=0.6, jaw_width=0.6, cheekbones=0.5, front_breadth=0.6, eye_spacing=0.4, nose_width=0.3, mouth_width=0.3),
    long=dict(face_length=0.8, chin_length=0.5, nose_length=0.6, mouth_height=0.3, cranium_height=0.3, forehead=0.2),
    bony=dict(cheekbones=0.5, cheeks=-0.7, brow_ridge=0.6, jaw_square=0.6, socket_depth=-0.5, chin_forward=0.3, nose_bridge=0.4),
    eyes=dict(eye_size=0.8, eye_open=0.6, iris_size=0.4, brow_height=0.3),
)
DRAW = dict(direction_sd=0.42, value_sd=0.22, reach=0.42, family_share=0.7)  # reach: the most a person's values may be from the type, as a root mean square


def rig_values():
    """Every value a person may vary, in order: (value, bone, what, axis, least, most, unit, note)."""
    return [(v, bone, what, axis, lo, hi, unit, note) for bone, _, _, _, values in RIG for v, what, axis, lo, hi, unit, note in values]


def rig_json():
    bones = []
    for bone, parent, part, at, values in RIG:
        bones.append(dict(name=bone, parent=parent, part=part, at=at, mirrored=bone.replace("_L", "_R") if bone in PAIRED else None,
                          values=[dict(id=v, does=what, axis=axis, least=lo, most=hi, unit=unit, note=note) for v, what, axis, lo, hi, unit, note in values]))
    return dict(
        about="Identity bones. A person's value v in -1..1 gives the bone's change from its rest: least at -1, none at 0, most at 1 (a scale's rest is 1, a move's and a turn's 0). `move` is in thousandths of the head's height.",
        axes=dict(x="across: file X; for a paired bone, away from the midline on both sides", y="forward: file -Z", z="up: file Y", note="a bone's own axes at rest; a bone turned at rest (the cheeks) moves along its turned axes"),
        bones=bones, fixed_by_type=FIXED_BY_TYPE, directions=DIRECTIONS, draw=DRAW)


def decode(value_id, v):
    """A value's physical amount for v in -1..1: a scale factor, a move in H, or degrees."""
    _, _, what, _, lo, hi, _, _ = next(r for r in rig_values() if r[0] == value_id)
    rest = 1.0 if what == "scale" else 0.0
    v = min(max(v, -1.0), 1.0)
    amount = lerp(rest, hi, v) if v >= 0 else lerp(rest, lo, -v)
    return amount / 1000.0 if what == "move" else amount


# ---------------------------------------------------------------------------------------------
# Measuring the anchors.


def measure_one(path, mouth=None):
    """A head's landmark set from the reference tool's `<name>_m.json` (measure.py): sections at
    the heights Z and the features' places, in units of the head's height H."""
    import numpy as np

    d = json.load(open(path))
    H, chin, R = d["H"], d["chin"], d["R"]
    secs = {round(float(k), 2): np.array(v).reshape(-1, 3) for k, v in d["secs"].items() if len(v)}
    eye_y = d["eye"][1]
    at_eye = secs[min(secs, key=lambda f: abs(chin + f * H - eye_y))]
    bridge = at_eye[np.abs(at_eye[:, 0]) < 0.004][:, 2].max()  # the front of the midline at eye height: depths are behind it
    out = dict(H_m=round(H, 4), w15=[], w30=[], wide=[], p00=[], p08=[], p30=[])
    for f in Z:
        s = secs.get(f)
        if s is None or len(s) < 6:
            for k in ("w15", "w30", "wide", "p00", "p08", "p30"):
                out[k].append(None)
            continue
        within = lambda dep: round(2 * float(np.abs(s[s[:, 2] > bridge - dep * H][:, 0]).max()) / H, 3) if (s[:, 2] > bridge - dep * H).any() else None
        out["w15"].append(within(0.15))
        out["w30"].append(within(0.30))
        out["wide"].append(within(0.42))  # the skull's side, before the ears stand out of it
        mid = s[np.abs(s[:, 0]) < 0.005]
        out["p00"].append(round(float(mid[:, 2].max() - bridge) / H, 3) if len(mid) else None)
        for key, x in (("p08", 0.08), ("p30", 0.30)):  # beside the nose (the front plane without it), and at the cheek
            off = s[np.abs(np.abs(s[:, 0]) - x * H) < 0.006]
            out[key].append(round(float(off[:, 2].max() - bridge) / H, 3) if len(off) else None)
    out.update(eye_z=round(R["eye_centre_share"], 3), eye_apart=round(R["eye_sep_H"], 3), eye_w=round(R["eye_w_H"], 3), eye_h=round(R["eye_w_H"] * R["eye_h_over_w"], 3),
               socket_brow=round(R["eye_rim_behind_brow_H"], 3), socket_cheek=round(R["eye_rim_behind_cheek_H"], 3), nose_tip_z=round(R["nose_tip_share"], 3), nose_out=round(R["nose_out_H"], 3), nose_tip_y=round(float(d["tip"][2] - bridge) / H, 3))
    if "mouth_share" in R:
        out.update(mouth_z=round(R["mouth_share"], 3), mouth_w=round(R["mouth_w_H"], 3))
    elif mouth:
        out.update(mouth_z=round(mouth[0], 3), mouth_w=round(mouth[1], 3))
    return out


def measure(ref):
    """The anchors: the reference and its sister file, and the pass-2 generator's average head
    for each sex and age band (ref/avg/<band>_<f|m>.params.json, made as run.sh makes its two)."""
    sys.path.insert(0, os.path.join(HERE, "..", "blender"))
    import head_form
    import person_params

    out = {}
    for name, key in (("shino", "reference"), ("vivi", "sister")):
        out[key] = measure_one(os.path.join(ref, "npz", f"{name}_m.json"))
    for band in ("adult", "elder", "youth", "child"):
        for sex in "fm":
            k = f"{band}_{sex}"
            s = person_params.resolve(json.load(open(os.path.join(ref, "avg", f"{k}.params.json")))["params"])
            hf = head_form.Head(masc=s["masc"], child=s["child"], elder=s["elder"], face=s["face"], style=s["style"])
            h = hf.top_z - hf.chin_z
            m = measure_one(os.path.join(ref, "npz", f"avg_{k}_m.json"), mouth=((hf.mouth_z - hf.chin_z) / h, 2 * hf.mouth_w / h))
            # Pass 2's skin stops at the hairline, so its top section is the edge of the skin, not the skull.
            for key in SECTION_KEYS:
                m[key][-1] = None
            out["pass2_" + k] = m
    return out


# ---------------------------------------------------------------------------------------------
# Composing the types.

SECTION_KEYS = ("w15", "w30", "wide", "p00", "p08", "p30")
SCALAR_KEYS = ("eye_z", "eye_apart", "eye_w", "eye_h", "socket_brow", "socket_cheek", "nose_tip_z", "nose_out", "nose_tip_y", "mouth_z", "mouth_w")
SIZE_KEYS = ("eye_w", "eye_h", "mouth_w")  # sizes follow a group by its ratio to the adult woman's; places by its difference
# Body types, tied to the face's line: (height in metres as least, usual, most; weight; muscle), by band and sex.
BODY = dict(
    child=dict(u=((0.87, 1.22, 1.45), 0.0, 0.0)),
    youth=dict(f=((1.50, 1.60, 1.70), -0.05, -0.1), m=((1.50, 1.66, 1.80), -0.1, 0.0)),
    adult=dict(f=((1.50, 1.64, 1.78), 0.0, -0.1), m=((1.60, 1.77, 1.94), 0.0, 0.15)),
    elder=dict(f=((1.48, 1.61, 1.74), 0.1, -0.2), m=((1.58, 1.74, 1.90), 0.1, 0.0)),
)
BODY_LINE = dict(a=(-0.02, 0.35, 0.0), b=(0.0, 0.0, 0.0), c=(0.03, -0.30, 0.05))  # the line's change: usual height, weight, muscle


def add(a, b, k=1.0):
    """a + k·b for two landmark sets (b's missing entries change nothing)."""
    out = copy.deepcopy(a)
    for key in SECTION_KEYS:
        out[key] = [None if x is None else (x if y is None else x + k * y) for x, y in zip(a[key], b[key])]
    for key in SCALAR_KEYS:
        if a.get(key) is not None and b.get(key) is not None:
            out[key] = a[key] + k * b[key]
    return out


def sub(a, b):
    out = copy.deepcopy(a)
    for key in SECTION_KEYS:
        out[key] = [None if (x is None or y is None) else x - y for x, y in zip(a[key], b[key])]
    for key in SCALAR_KEYS:
        out[key] = (a[key] - b[key]) if (a.get(key) is not None and b.get(key) is not None) else None
    return out


def mean(a, b):
    return add(a, sub(b, a), 0.5)


def compose(measured):
    """The types, from the anchors (see the module's text). Returns {id: type}."""
    ref, sister = measured["reference"], measured["sister"]
    toward_sister = sub(sister, ref)
    home = measured["pass2_adult_f"]
    types = {}
    for band, lo, hi in BANDS:
        for sex in ("u",) if band == "child" else ("f", "m"):
            if sex == "u":
                group = mean(measured["pass2_child_f"], measured["pass2_child_m"])
            else:
                group = measured[f"pass2_{band}_{sex}"]
            base = add(ref, sub(group, home))
            for key in SIZE_KEYS:
                base[key] = ref[key] * group[key] / home[key]
            for line, name in LINES.items():
                t = copy.deepcopy(base)
                masc = dict(f=0.0, m=1.0, u=0.3)[sex]
                if line == "a":
                    # Round: the lower face wider and blunter and the eyes taller and further
                    # apart, as the sister file is; its eyes' and nose's heights only in part.
                    t = add(t, toward_sister, 0.8)
                    for key, share in (("eye_h", 0.5), ("eye_z", 0.4), ("nose_tip_z", 0.3), ("mouth_w", 0.5), ("mouth_z", 0.0)):
                        t[key] = base[key] + share * toward_sister[key]
                elif line == "c":
                    # Long: a longer, narrower lower face, the eyes a little higher and narrower,
                    # a chin that comes to a point (a woman's) or is cut square (a man's).
                    t = add(t, toward_sister, -0.5)
                    t["eye_h"] = base["eye_h"] * 0.90
                    for key, dz in (("eye_z", 0.014), ("nose_tip_z", 0.012), ("mouth_z", 0.006)):
                        t[key] += dz
                    t["w15"][0] += lerp(-0.02, 0.035, masc)
                    t["w30"][0] += lerp(-0.02, 0.035, masc)
                    t["wide"][0] = t["w30"][0]
                    for i in (1, 2):
                        t["w15"][i] -= 0.012
                        t["w30"][i] -= 0.012
                # A width within a shallower depth never passes one within a deeper.
                for i in range(len(Z)):
                    if t["w15"][i] is not None and t["w30"][i] is not None:
                        t["w30"][i] = max(t["w30"][i], t["w15"][i])
                    if t["w30"][i] is not None and t["wide"][i] is not None:
                        t["wide"][i] = max(t["wide"][i], t["w30"][i])
                # The skull above the reference's mask, the brows, ears and creases are designed.
                child, elder = band == "child", band == "elder"
                sharp = dict(a=0.60, b=0.72, c=0.86)[line] + 0.08 * masc - (0.22 if child else 0.0) + (0.05 if elder else 0.0)
                bh, bw, bm = BODY[band][sex]
                dh, dw, dm = BODY_LINE[line]
                tid = f"{band}-{sex}-{line}"
                types[tid] = dict(
                    id=tid, band=band, ages=[lo, min(hi, 99)], sex=dict(f="female", m="male", u="either")[sex], line=line, name=name,
                    head=dict(height_m=round(lerp(0.233, 0.245, masc) * (0.97 if child else 1.0), 3), figure_heads=7.0 if not child else 5.6),
                    sections=dict(z=Z, **{k: [None if x is None else round(x, 3) for x in t[k]] for k in SECTION_KEYS}),
                    skull=dict(crown=1.0, depth=round(lerp(0.86, 0.84, masc) + (0.02 if child else 0.0), 3), back_z=0.58),
                    eye=dict(z=round(t["eye_z"], 3), apart=round(t["eye_apart"], 3), w=round(t["eye_w"], 3), h=round(t["eye_h"], 3), tilt_deg=round(lerp(2.5, 0.5, masc) - (2.0 if elder else 0.0), 1),
                             behind_brow=round(t["socket_brow"], 3), behind_cheek=round(t["socket_cheek"], 3), iris=0.62, shape=round(lerp(0.05, -0.05, masc), 2), fold=round(0.65 + (0.3 if elder else 0.0), 2),
                             iris_behind_lid=0.017, white_depth=0.064),
                    brow=dict(above_eye=round(lerp(0.105, 0.085, masc) + (0.01 if child else 0.0), 3), thick=round(lerp(0.010, 0.017, masc) * (1.15 if elder and masc else 1.0), 4), tilt_deg=round(lerp(-1.0, 2.0, masc), 1),
                              arch=round(lerp(0.35, 0.15, masc), 2), ridge=round(lerp(0.0, 0.008, masc) * (0.0 if child else 1.0), 4)),
                    nose=dict(tip_z=round(t["nose_tip_z"], 3), out=round(t["nose_out"], 3), tip_y=round(t["nose_tip_y"], 3), base_z=round(t["nose_tip_z"] - 0.035, 3), bridge_z=round(t["eye_z"] + 0.025, 3), width=round(lerp(0.085, 0.105, masc) * (0.9 if child else 1.0), 3)),
                    mouth=dict(z=round(t["mouth_z"], 3), w=round(t["mouth_w"], 3), lips=round(lerp(0.030, 0.022, masc) * (0.85 if elder else 1.0), 4)),
                    jaw=dict(angle_z=round(lerp(0.20, 0.17, masc) + (0.02 if child else 0.0), 3), angle_back=round(lerp(0.40, 0.43, masc), 3), under=round(lerp(0.06, 0.07, masc), 3)),
                    ear=dict(z=round(t["eye_z"] - 0.045, 3), size=round(0.235 * (1.08 if elder else 1.0), 3), out_deg=22, back=0.50),
                    planes=dict(cheek_corner=round(min(max(sharp, 0.2), 1.0), 2), brow_line=round(0.35 + 0.35 * masc, 2), jaw_line=round(min(sharp + 0.05, 1.0), 2), under_jaw=0.8),
                    body=dict(height_m=[round(bh[0] + dh, 2), round(bh[1] + dh, 2), round(bh[2] + dh, 2)], weight=round(bw + dw, 2), muscle=round(bm + dm, 2), head_power=0.6),
                    made_from=f"reference + (pass 2's {band} {dict(f='woman', m='man', u='child')[sex]} − pass 2's adult woman)" + dict(a=" + 0.8 × (sister − reference)", b="", c=" − 0.5 × (sister − reference), lengthened")[line],
                )
    return types


# ---------------------------------------------------------------------------------------------
# A person: a type and bounded values.


def band_of(age):
    return next(b for b, lo, hi in BANDS if lo <= age < hi)


def type_for(seed, sex, age, family=None):
    """The type a person is: their band's and sex's, on their family's line when they have one."""
    band = band_of(age)
    s = "u" if band == "child" else ("m" if sex == "male" else "f")
    own = random.Random(f"{seed}/type").choice("abc")
    line = own
    if family is not None and random.Random(f"{seed}/type.family").random() < 0.8:
        line = random.Random(f"family{family}/type").choice("abc")
    return f"{band}-{s}-{line}"


def draw_values(seed, family=None):
    """A person's values, -1..1 each, 0 the type: drawn along the directions heads vary in, then
    value by value, and pulled back when the whole set lies further from the type than
    DRAW['reach']. Relatives share part of the draw. Each value has its own random stream."""
    ids = [r[0] for r in rig_values()]

    def one(src):
        v = dict.fromkeys(ids, 0.0)
        for name, shares in DIRECTIONS.items():
            g = random.Random(f"{src}/direction.{name}").gauss(0, DRAW["direction_sd"])
            for k, share in shares.items():
                v[k] += g * share
        for k in ids:
            v[k] += random.Random(f"{src}/value.{k}").gauss(0, DRAW["value_sd"])
        return v

    v = one(seed)
    if family is not None:
        f = one(f"family{family}")
        a = DRAW["family_share"]
        v = {k: a * f[k] + math.sqrt(1 - a * a) * v[k] for k in ids}
    rms = math.sqrt(sum(x * x for x in v.values()) / len(v))
    k = min(1.0, DRAW["reach"] / max(rms, 1e-9))
    return {key: round(min(max(x * k, -1.0), 1.0), 3) for key, x in v.items()}


def draw_valid(t, seed, family=None):
    """A person's values for a type, pulled back toward the type until they make a valid head
    (`faults`). Nearly every draw is valid as drawn."""
    v = draw_values(seed, family)
    for _ in range(12):
        if not faults(apply(t, v)):
            break
        v = {k: round(x * 0.85, 3) for k, x in v.items()}
    return v


def distance(values):
    return math.sqrt(sum(x * x for x in values.values()) / max(len(values), 1))


def head_scale(body, height):
    """The recipe's head multiplier for a height: a taller person's head grows less than they do
    (Blue Protocol changes the head's proportion with height, not only the scale)."""
    usual = body["height_m"][1]
    return round((usual / height) ** body["head_power"], 3)


def person(seed, sex, age, family=None, height=None):
    """What a person becomes: a type id, values, and the body's numbers (colours and styles are
    drawn as today, by person_params)."""
    tid = type_for(seed, sex, age, family)
    t = load()["types"][tid]
    lo, usual, hi = t["body"]["height_m"]
    if height is None:
        height = min(max(random.Random(f"{seed}/build.height").gauss(usual, (hi - lo) / 6), lo), hi)
    return dict(type=tid, height=round(height, 2), head=head_scale(t["body"], height), identity=draw_valid(t, seed, family))


def apply(t, values):
    """A type's landmark set with a person's values applied: what the bones do to the type's
    head, for diagrams and checks. Heights stay in the type's own H, so a longer chin makes a
    taller head."""
    p = copy.deepcopy(t)
    g = lambda k: decode(k, values.get(k, 0.0))
    s = p["sections"]
    brow = p["eye"]["z"] + p["brow"]["above_eye"]
    nasion = p["eye"]["z"]
    above = lambda z: smooth((z - (brow - 0.04)) / 0.14)
    n = len(s["z"])
    for i in range(n):
        z = s["z"][i]
        up, low = above(z), 1 - above(z)
        jaw = 1 - smooth((z - 0.10) / 0.16)
        wx = (1 + (g("cranium_width") - 1) * up) * (1 + (g("face_width") - 1) * low) * (1 + (g("jaw_width") - 1) * jaw * low)
        for k in ("w15", "w30", "wide"):
            if s[k][i] is not None:
                s[k][i] *= wx
        cheek = math.exp(-(((z - 0.28 - g("cheekbone_height")) / 0.08) ** 2))
        full = math.exp(-(((z - 0.18) / 0.07) ** 2))
        square = math.exp(-(((z - p["jaw"]["angle_z"] + 0.06) / 0.06) ** 2))
        mid = smooth((z - 0.14) / 0.08) * (1 - smooth((z - 0.70) / 0.10))
        if s["w15"][i] is not None:
            s["w15"][i] += 2 * (g("front_breadth") * mid + 0.6 * g("cheekbones") * cheek + 0.5 * g("jaw_square") * square)
        for k in ("w30", "wide"):
            if s[k][i] is not None:
                s[k][i] += 2 * (g("cheekbones") * cheek + g("cheeks") * 0.6 * full + g("jaw_square") * square)
        if s["p00"][i] is not None:
            s["p00"][i] += g("forehead") * smooth((z - 0.58) / 0.10) + g("brow_ridge") * math.exp(-(((z - brow) / 0.05) ** 2)) + g("chin_forward") * (1 - smooth((z - 0.02) / 0.10))
        if s["p08"][i] is not None:
            s["p08"][i] += g("forehead") * smooth((z - 0.58) / 0.10) + g("brow_ridge") * math.exp(-(((z - brow) / 0.05) ** 2))
        if s["p30"][i] is not None:
            s["p30"][i] += g("cheeks") * full
    for i in (0,):
        for k in ("w15", "w30", "wide"):
            if s[k][i] is not None:
                s[k][i] *= g("chin_width")
    # Heights: the face below the bridge stretches with face_length, the chin drops with
    # chin_length, the cranium above the brows with cranium_height. The chin stays at 0.
    fl, ch, cl = g("face_length"), g("cranium_height"), -g("chin_length")

    def zmap(z):
        if z < nasion:
            z = nasion - (nasion - z) * fl
        elif z > brow:
            z = brow + (z - brow) * ch
        return z

    drop = (nasion - nasion * fl) - cl  # where the chin went
    shift = lambda z: zmap(z) - drop if z > 0.02 else 0.0
    s["z"] = [round(shift(z), 4) for z in s["z"]]
    p["skull"]["crown"] = round(shift(1.0), 4)
    e, b, no, m = p["eye"], p["brow"], p["nose"], p["mouth"]
    fw = g("face_width")
    e["z"] = shift(e["z"]) + g("eye_height")
    e["apart"] = e["apart"] * fw + 2 * g("eye_spacing")
    e["w"] *= g("eye_size")
    e["h"] *= g("eye_size") * g("eye_open")
    e["tilt_deg"] += g("eye_tilt")
    e["behind_brow"] -= g("socket_depth")
    e["behind_cheek"] -= g("socket_depth")
    e["iris"] *= g("iris_size")
    b["above_eye"] += g("brow_height") + g("eye_height") * 0  # the brow rides the face, not the eye
    b["brow_z"] = shift(brow) + g("brow_height")
    b["thick"] *= g("brow_thickness")
    b["tilt_deg"] += g("brow_tilt")
    b["length"] = g("brow_length")
    b["ridge"] += g("brow_ridge")
    span = no["bridge_z"] - no["tip_z"]
    no["bridge_z"] = shift(no["bridge_z"])
    no["tip_z"] = no["bridge_z"] - span * fl * g("nose_length") + g("nose_tip")
    no["base_z"] = no["tip_z"] - 0.035 * fl - g("nose_tip")
    no["tip_y"] *= g("nose_bridge")
    no["out"] *= g("nose_bridge")
    no["width"] *= g("nose_width") * fw
    m["z"] = shift(m["z"]) + g("mouth_height")
    m["w"] *= g("mouth_width") * fw
    m["lips"] *= g("lip_fullness")
    m["curve"] = g("mouth_curve")
    p["jaw"]["angle_z"] = shift(p["jaw"]["angle_z"])
    p["ear"]["z"] = shift(p["ear"]["z"])
    p["ear"]["size"] *= g("ear_size")
    p["ear"]["out_deg"] += g("ear_out")
    p["head"]["height_m"] = round(p["head"]["height_m"] * p["skull"]["crown"], 4)
    return p


def at(s, key, z):
    """A section value at height z (linear between the kept heights; None entries skipped)."""
    pts = [(zz, v) for zz, v in zip(s["z"], s[key]) if v is not None]
    if z <= pts[0][0]:
        return pts[0][1]
    for (za, a), (zb, b) in zip(pts, pts[1:]):
        if z <= zb:
            return lerp(a, b, (z - za) / (zb - za))
    return pts[-1][1]


def faults(t):
    """What is wrong with a head, as a list of sentences (empty: it is a valid head)."""
    out = []
    s, e, no, m = t["sections"], t["eye"], t["nose"], t["mouth"]
    crown = t["skull"]["crown"]
    brow = t["brow"].get("brow_z", e["z"] + t["brow"]["above_eye"])
    order = [("chin", 0.0), ("mouth", m["z"]), ("nose base", no["base_z"]), ("nose tip", no["tip_z"]), ("eye", e["z"]), ("brow", brow), ("crown", crown)]
    for (na, a), (nb, b) in zip(order, order[1:]):
        if not a < b - 0.012:
            out.append(f"{nb} ({b:.3f}) is not above {na} ({a:.3f})")
    for i, z in enumerate(s["z"]):
        w15, w30, wide = s["w15"][i], s["w30"][i], s["wide"][i]
        if None not in (w15, w30) and w15 > w30 + 0.004:
            out.append(f"at {z:.2f} the front ({w15:.3f}) is wider than the head within 0.30 H ({w30:.3f})")
        if None not in (w30, wide) and w30 > wide + 0.004:
            out.append(f"at {z:.2f} the width within 0.30 H ({w30:.3f}) passes the skull's side ({wide:.3f})")
    inner, outer = e["apart"] / 2 - e["w"] / 2, e["apart"] / 2 + e["w"] / 2
    if inner < 0.045:
        out.append(f"the eyes' inner corners are {inner:.3f} H from the midline (0.045 at least)")
    front = at(s, "w15", e["z"]) / 2
    if outer > front + 0.012:
        out.append(f"the eye's outer corner ({outer:.3f}) is off the front plane ({front:.3f})")
    if e["z"] - e["h"] * 0.38 < no["tip_z"] + 0.012:
        out.append("the eye's lower lid reaches the nose's tip")
    if e["z"] + e["h"] * 0.6 > brow - 0.004:
        out.append("the eye's upper lid reaches the brow")
    if m["w"] / 2 > at(s, "w15", m["z"]) / 2 - 0.02:
        out.append(f"the mouth ({m['w']:.3f}) is as wide as the front at its height ({at(s, 'w15', m['z']):.3f})")
    if no["width"] / 2 > inner + e["w"] * 0.35:
        out.append("the nose is wider than the gap between the eyes allows")
    if min(e["behind_brow"], e["behind_cheek"]) < 0.012:
        out.append("the eye stands out of its socket")
    return out


def load():
    return json.load(open(DATA))


# ---------------------------------------------------------------------------------------------
# Diagrams.

INK, GUIDE, FRONT, SIDE, FAR, SKIN_LINE, BONE = (40, 36, 34), (150, 160, 170), (246, 226, 208), (226, 196, 176), (198, 164, 146), (150, 96, 84), (30, 110, 200)
SS = 3  # diagrams are drawn at three times their size and reduced


def _font(size):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def outline_front(t, key):
    """A closed polygon of the head from the front at the width `key` (half widths by height),
    with a rounded top and the chin's point; in H units, x across and z up."""
    s = t["sections"]
    crown = t["skull"]["crown"]
    pts = [(zz, w / 2) for zz, w in zip(s["z"], s[key]) if w is not None]
    top_z, top_w = pts[-1]
    right = [(0.0, 0.0)] + [(w, z) for z, w in pts]
    # The dome: an ellipse from the last kept section to the crown.
    for k in range(1, 9):
        a = (k / 8) * math.pi / 2
        right.append((top_w * math.cos(a), top_z + (crown - top_z) * math.sin(a)))
    return right + [(-x, z) for x, z in reversed(right[1:-1])]


def draw_front(d, box, t, ghost=None, labels=True, bones=False):
    """A type or a person from the front, as planes and landmarks."""
    x0, y0, x1, y1 = box
    crown = max(t["skull"]["crown"], 1.0)
    k = min((x1 - x0) / 1.08, (y1 - y0) / (1.16 * 1.0))
    cx, base = (x0 + x1) / 2, y1 - 0.07 * k
    P = lambda x, z: (cx + x * k, base - z * k)
    poly = lambda pts: [P(x, z) for x, z in pts]
    if ghost is not None:
        d.line(poly(outline_front(ghost, "wide")) + [P(0, 0)], fill=(170, 170, 170), width=SS)
    e, b, no, m, ear = t["eye"], t["brow"], t["nose"], t["mouth"], t["ear"]
    # Ears behind the head.
    for sx in (-1, 1):
        ex = at(t["sections"], "wide", ear["z"]) / 2
        out = 0.03 + 0.05 * math.sin(math.radians(max(ear["out_deg"], 0)))
        d.ellipse([P(sx * (ex + out) - 0.035, ear["z"] + ear["size"] / 2)[0], P(0, ear["z"] + ear["size"] / 2)[1], P(sx * (ex + out) + 0.035, 0)[0], P(0, ear["z"] - ear["size"] / 2)[1]], fill=SIDE, outline=INK, width=SS)
    d.polygon(poly(outline_front(t, "wide")), fill=FAR, outline=INK)
    d.polygon(poly(outline_front(t, "w30")), fill=SIDE)
    d.polygon(poly(outline_front(t, "w15")), fill=FRONT)
    d.line(poly(outline_front(t, "wide")) + [P(0, 0)], fill=INK, width=2 * SS)
    # The cheek corner: where the front planes turn into the cheek and temple.
    corner = [(w / 2, z) for z, w in zip(t["sections"]["z"], t["sections"]["w15"]) if w is not None]
    wt = max(1, round(SS * (0.6 + 2.2 * t["planes"]["cheek_corner"])))
    for sx in (-1, 1):
        d.line([P(sx * x, z) for x, z in corner], fill=SKIN_LINE, width=wt)
    # The midline, where the two front planes meet.
    d.line([P(0, 0.02), P(0, t["skull"]["crown"] - 0.02)], fill=(214, 186, 168), width=SS)
    brow_z = b.get("brow_z", e["z"] + b["above_eye"])
    if labels:
        for z, name in ((brow_z, "brow"), (e["z"], "eyes"), (no["base_z"], "nose base"), (m["z"], "mouth")):
            for a in range(0, 46, 2):
                d.line([P(-0.52 + a * 0.0226, z), P(-0.52 + (a + 1) * 0.0226, z)], fill=GUIDE, width=SS)
    for sx in (-1, 1):
        ex = sx * e["apart"] / 2
        hw, tilt = e["w"] / 2, math.radians(e["tilt_deg"]) * sx
        up, lo = e["h"] * 0.62, e["h"] * 0.38
        lens = []
        for i in range(17):
            u = -1 + 2 * i / 16
            lens.append((ex + u * hw, e["z"] + up * (1 - u * u) ** 0.6 + math.tan(tilt) * u * hw * sx * sx))
        for i in range(16, -1, -1):
            u = -1 + 2 * i / 16
            lens.append((ex + u * hw, e["z"] - lo * (1 - u * u) ** 0.8 + math.tan(tilt) * u * hw))
        # The socket: a recess round the opening.
        d.ellipse([P(ex - hw * 1.45, 0)[0], P(0, e["z"] + e["h"] * 1.05)[1], P(ex + hw * 1.45, 0)[0], P(0, e["z"] - e["h"] * 0.85)[1]], fill=(236, 208, 190))
        d.polygon(poly(lens), fill=(250, 250, 248), outline=INK)
        r = min(e["iris"] * hw, (up + lo) * 0.52)
        d.ellipse([P(ex - r * 0.9, e["z"] + up * 0.2 + r)[0], P(0, e["z"] + (up - lo) * 0.25 + r)[1], P(ex + r * 0.9, 0)[0], P(0, e["z"] + (up - lo) * 0.25 - r)[1]], fill=(86, 110, 96), outline=INK)
        d.line(poly(lens[:17]), fill=INK, width=2 * SS)
        bl = hw * 1.25 * b.get("length", 1.0)
        bt = math.radians(b["tilt_deg"])
        brow = [(ex + sx * u * bl, brow_z + b["arch"] * 0.03 * (1 - u * u) - math.tan(bt) * u * bl) for u in (-1, -0.5, 0, 0.5, 1)]
        d.line(poly(brow), fill=(70, 50, 44), width=max(SS, round(b["thick"] * k)))
    # The nose as a wedge, the mouth as a line.
    d.polygon(poly([(0, no["bridge_z"] - 0.02), (no["width"] / 2 * 0.85, no["base_z"] + 0.004), (0, no["base_z"] - 0.006), (-no["width"] / 2 * 0.85, no["base_z"] + 0.004)]), fill=(238, 214, 198), outline=SKIN_LINE)
    d.line([P(-0.012, no["base_z"]), P(0.012, no["base_z"])], fill=SKIN_LINE, width=2 * SS)
    curve = m.get("curve", 0.0)
    d.line(poly([(-m["w"] / 2, m["z"] + curve), (-m["w"] / 4, m["z"] - 0.002), (m["w"] / 4, m["z"] - 0.002), (m["w"] / 2, m["z"] + curve)]), fill=(150, 70, 66), width=2 * SS)
    if bones:
        for name, x, z in bone_places(t):
            px, py = P(x, z)
            d.ellipse([px - 3 * SS, py - 3 * SS, px + 3 * SS, py + 3 * SS], fill=BONE)
    return P


def bone_places(t):
    """Where each identity bone's pivot sits on a type, front view: (name, x, z) in H."""
    e, b, no, m, s = t["eye"], t["brow"], t["nose"], t["mouth"], t["sections"]
    brow_z = e["z"] + b["above_eye"]
    out = [("Cranium", 0, brow_z + 0.02), ("Forehead", 0, 0.70), ("Glabella", 0, brow_z), ("Face", 0, e["z"]), ("Nose", 0, no["bridge_z"] - 0.01), ("NoseTip", 0, no["tip_z"]), ("Mouth", 0, m["z"]),
           ("Chin", 0, 0.012), ("Jaw", 0, 0.075)]
    for sx, side in ((-1, "R"), (1, "L")):
        out += [(f"Orbit_{side}", sx * e["apart"] / 2, e["z"]), (f"Brow_{side}", sx * e["apart"] / 2, brow_z), (f"Corner_{side}", sx * at(s, "w15", e["z"]) / 2, e["z"]),
                (f"Zygoma_{side}", sx * at(s, "w30", 0.28) / 2 * 0.92, 0.28), (f"Cheek_{side}", sx * at(s, "w15", 0.18) / 2 * 0.8, 0.18), (f"Gonion_{side}", sx * at(s, "wide", t["jaw"]["angle_z"]) / 2, t["jaw"]["angle_z"]),
                (f"MouthCorner_{side}", sx * (m["w"] / 2 + 0.035), m["z"] - 0.022), (f"Ear_{side}", sx * (at(s, "wide", t["ear"]["z"]) / 2 + 0.02), t["ear"]["z"])]
    return out


def draw_side(d, box, t, labels=True):
    """A type from the side, facing right: the midline's profile, the cheek plane 0.30 H off
    it, the jaw line, the eye in its socket, the ear and the skull's back. Depths are from the
    bridge of the nose at eye height, forward to the right."""
    x0, y0, x1, y1 = box
    k = min((x1 - x0) / 1.16, (y1 - y0) / 1.16)
    s, e, no, m, ear, jaw, sk = t["sections"], t["eye"], t["nose"], t["mouth"], t["ear"], t["jaw"], t["skull"]
    crown = sk["crown"]
    cx, base = x1 - 0.20 * k, y1 - 0.07 * k
    P = lambda y, z: (cx + y * k, base - z * k)
    # The front of the midline from the chin up: the kept sections, with the nose's tip.
    # Chin and lips are the midline's; from the lip up it is the front plane beside the nose,
    # brought forward to the midline, with the nose standing on it as a wedge.
    lift = at(s, "p00", 0.52) - at(s, "p08", 0.52)
    plane = lambda z: at(s, "p08", z) + lift
    lip = m["z"] + 0.035
    front = [(at(s, "p00", 0.04) - 0.012, 0.0)] + [(v, zz) for zz, v in zip(s["z"], s["p00"]) if v is not None and zz < lip - 0.02]
    front += [(plane(lip), lip), (plane(no["base_z"]) + 0.004, no["base_z"] - 0.006), (no["tip_y"] - 0.03, no["base_z"]), (no["tip_y"], no["tip_z"]), (plane(no["bridge_z"]), no["bridge_z"])]
    front += [(v + lift, zz) for zz, v in zip(s["z"], s["p08"]) if v is not None and zz > no["bridge_z"] + 0.03]
    front.sort(key=lambda q: q[1])
    top_y, top_z = front[-1]
    # Over the crown and down the back of the skull, the nape and the neck.
    depth = sk["depth"]
    fore = max(v for v, zz in front if zz > 0.5)
    back_y = fore - depth
    yc, zc = (fore + back_y) / 2, sk["back_z"]
    a0 = math.atan2((top_z - zc) / (crown - zc), (top_y - yc) / (depth / 2))
    arc = [(yc + depth / 2 * math.cos(a0 + (math.pi - a0) * i / 14), zc + (crown - zc) * math.sin(a0 + (math.pi - a0) * i / 14)) for i in range(1, 15)]
    nape = [(back_y + 0.02, zc - 0.14), (back_y + 0.11, 0.28), (-jaw["angle_back"] - 0.10, 0.14), (-jaw["angle_back"] - 0.10, -0.08)]
    throat = [(-0.26, -0.08), (-0.24, jaw["under"] - 0.01), (front[0][0] - 0.05, 0.0)]
    head = front + arc + nape + throat
    d.polygon([P(y, z) for y, z in head], fill=SIDE)
    # The front planes as the side shows them: between the midline and the surface 0.30 H off it.
    off = [(v, zz) for zz, v in zip(s["z"], s["p30"]) if v is not None]
    if len(off) >= 2:
        lo_z, hi_z = off[0][1], off[-1][1]
        d.polygon([P(y, z) for y, z in [q for q in front if lo_z - 0.10 <= q[1] <= hi_z + 0.001] + [(off[-1][0], hi_z)] + list(reversed(off))], fill=FRONT)
        d.line([P(y, z) for y, z in off], fill=SKIN_LINE, width=max(1, round(SS * (0.6 + 2.2 * t["planes"]["cheek_corner"]))))
    d.line([P(y, z) for y, z in head] + [P(*head[0])], fill=INK, width=2 * SS)
    # The jaw line: down the ramus to the angle of the jaw, then forward to the chin; and the plane under it.
    gon = (-jaw["angle_back"], jaw["angle_z"])
    d.line([P(gon[0] + 0.02, ear["z"] - ear["size"] * 0.45), P(*gon), P(front[0][0] - 0.03, 0.02)], fill=SKIN_LINE, width=max(1, round(SS * (0.6 + 2.2 * t["planes"]["jaw_line"]))))
    # The eye, seen from the side in its socket: the white's bowl, the iris just behind the lid, the lid's visor.
    lid = -(e["behind_brow"] + 0.045)
    d.polygon([P(lid, e["z"] + e["h"] * 0.62), P(lid - e["white_depth"], e["z"] + e["h"] * 0.25), P(lid - e["white_depth"], e["z"] - e["h"] * 0.2), P(lid, e["z"] - e["h"] * 0.38)], fill=(250, 250, 248), outline=INK)
    d.line([P(lid - e["iris_behind_lid"], e["z"] + e["h"] * 0.45), P(lid - e["iris_behind_lid"], e["z"] - e["h"] * 0.30)], fill=(60, 90, 76), width=3 * SS)
    d.line([P(lid - 0.006, e["z"] + e["h"] * 0.60), P(lid + 0.038, e["z"] + e["h"] * 0.74)], fill=INK, width=2 * SS)
    # The brow, the mouth and the ear.
    bz = t["brow"].get("brow_z", e["z"] + t["brow"]["above_eye"])
    d.line([P(at(s, "p00", bz) - 0.045, bz), P(at(s, "p00", bz) - 0.12, bz - 0.008)], fill=(70, 50, 44), width=max(SS, round(t["brow"]["thick"] * k)))
    d.line([P(at(s, "p00", m["z"]) + 0.004, m["z"]), P(at(s, "p00", m["z"]) - 0.04, m["z"] - 0.004)], fill=(150, 70, 66), width=2 * SS)
    d.ellipse([P(-ear["back"] - 0.045, 0)[0], P(0, ear["z"] + ear["size"] / 2)[1], P(-ear["back"] + 0.055, 0)[0], P(0, ear["z"] - ear["size"] / 2)[1]], fill=(238, 214, 198), outline=INK, width=SS)
    if labels:
        for z in (bz, e["z"], no["base_z"], m["z"]):
            for a in range(0, 30, 2):
                d.line([P(0.14 - a * 0.012, z), P(0.14 - (a + 1) * 0.012, z)], fill=GUIDE, width=SS)


def type_text(t):
    s, e = t["sections"], t["eye"]
    if t["name"] == "measured":
        return [t["id"], f"eyes at {e['z']:.2f} H, {e['apart']:.2f} apart, {e['w']:.2f} by {e['h']:.2f}", f"front at the eyes {at(s, 'w15', 0.40):.2f} / {at(s, 'w30', 0.40):.2f} H",
                f"jaw {at(s, 'w30', 0.12):.2f}, chin {at(s, 'w15', 0.04):.2f} H", f"nose tip {t['nose']['tip_z']:.2f}"]
    return [f"{t['id']}  ·  {t['name']}", f"eyes at {e['z']:.2f} H, {e['apart']:.2f} apart, {e['w']:.2f} by {e['h']:.2f}", f"front at the eyes {at(s, 'w15', 0.40):.2f} / {at(s, 'w30', 0.40):.2f} H",
            f"jaw {at(s, 'w30', 0.12):.2f}, chin {at(s, 'w15', 0.04):.2f} H", f"cheek corner {t['planes']['cheek_corner']:.2f}, nose tip {t['nose']['tip_z']:.2f}"]


def sheet(rows, path, people=5, title=None, cell=300):
    """One row a type: front, side, and `people` drawn people of it (their outline over the
    type's in grey)."""
    from PIL import Image, ImageDraw

    c = cell * SS
    pc = int(cell * 0.62) * SS
    W = max(2 * c + people * pc + 20 * SS, 1100 * SS)
    titles = [title] if isinstance(title, str) else list(title or [])
    head = (14 + 20 * len(titles) if titles else 0) * SS
    img = Image.new("RGB", (W, head + len(rows) * (c + 26 * SS)), (252, 251, 248))
    d = ImageDraw.Draw(img)
    f, small = _font(13 * SS), _font(11 * SS)
    for i, line in enumerate(titles):
        d.text((10 * SS, (8 + 20 * i) * SS), line, fill=INK if i == 0 else (90, 90, 90), font=_font((16 if i == 0 else 13) * SS))
    for r, (t, folk) in enumerate(rows):
        y = head + r * (c + 26 * SS)
        draw_front(d, (0, y, c, y + c), t)
        draw_side(d, (c, y, 2 * c, y + c), t)
        d.text((8 * SS, y + c + 2 * SS), "   ·   ".join(type_text(t)[:3]), fill=INK, font=small)
        d.text((8 * SS, y + c + 13 * SS), "   ·   ".join(type_text(t)[3:]), fill=(90, 90, 90), font=small)
        for i, (label, p) in enumerate(folk[:people]):
            x = 2 * c + 10 * SS + i * pc
            draw_front(d, (x, y + (c - pc) // 2, x + pc, y + (c - pc) // 2 + pc), p, ghost=t, labels=False)
            d.text((x + 6 * SS, y + (c - pc) // 2 - 12 * SS), label, fill=(90, 90, 90), font=small)
    img = img.resize((img.size[0] // SS, img.size[1] // SS), Image.LANCZOS)
    img.save(path, quality=92)
    return img.size


def sample_people(t, n, src="page"):
    """n drawn people of a type: (label, landmark set). The first two share a family."""
    out = []
    for i in range(n):
        v = draw_valid(t, f"{src}/{t['id']}/{i}", family=f"{t['id']}/fam" if i < 2 else None)
        out.append((f"{'kin ' if i < 2 else ''}d {distance(v):.2f}", apply(t, v)))
    return out


def draw(out):
    from PIL import Image, ImageDraw

    os.makedirs(out, exist_ok=True)
    data = load()
    types = data["types"]
    made = []
    titles = dict(child="Children (2 to 11), boys and girls", youth="Youths (12 to 17)", adult="Adults (18 to 59)", elder="Elders (60 and over)")
    for band, _, _ in BANDS:
        for sex, word in (("u", ""), ("f", ": women and girls"), ("m", ": men and boys")):
            rows = [(t, sample_people(t, 5)) for t in types.values() if t["band"] == band and t["id"].split("-")[1] == sex]
            if not rows:
                continue
            name = f"types-{band}" + ("" if sex == "u" else f"-{sex}")
            size = sheet(rows, os.path.join(out, name + ".jpg"), title=[titles[band] + word, "Front planes pale, cheek and temple planes darker; the red line is the cheek corner, heavier where it is sharper. Dashes: brow, eyes, nose base, mouth.",
                                                                        "Right: five people drawn from each type, over its outline in grey. `kin` are two of one family; d is how far the person's values lie from the type (0.42 at most)."])
            made.append((name, size))
    # The anchors in the same drawing: the reference, its sister, and where pass 2's averages are.
    blank = types["adult-f-b"]

    def as_type(m, name):
        t = copy.deepcopy(blank)
        t["id"], t["name"] = name, "measured"
        for k in SECTION_KEYS:
            t["sections"][k] = m[k]
        if all(v is None for v in t["sections"]["p30"]):
            t["sections"]["p30"] = blank["sections"]["p30"]
        t["eye"].update(z=m["eye_z"], apart=m["eye_apart"], w=m["eye_w"], h=m["eye_h"], behind_brow=m["socket_brow"], behind_cheek=m["socket_cheek"])
        t["nose"].update(tip_z=m["nose_tip_z"], out=m["nose_out"], tip_y=m["nose_tip_y"], base_z=m["nose_tip_z"] - 0.035, bridge_z=m["eye_z"] + 0.025)
        t["mouth"].update(z=m["mouth_z"], w=m["mouth_w"])
        t["ear"]["z"] = m["eye_z"] - 0.045
        return t

    ms = data["measured"]
    rows = [(as_type(ms["reference"], "the reference (Shino), measured"), []), (as_type(ms["sister"], "its sister file (Vivi), measured"), []),
            (as_type(ms["pass2_adult_f"], "pass 2's average woman, measured"), []), (as_type(ms["pass2_adult_m"], "pass 2's average man, measured"), [])]
    size = sheet(rows, os.path.join(out, "measured.jpg"), people=0, title=["Measured heads, drawn the same way", "The two VRoid files, and pass 2's average woman and man (every face value at 0).",
                                                                            "Sections and features are measured; the skull's back, the ears and the jaw's angle are drawn in the same for all four."])
    made.append(("measured", size))
    # The rig on one type.
    c = 760 * SS
    img = Image.new("RGB", (int(c * 1.75), c), (252, 251, 248))
    d = ImageDraw.Draw(img)
    t = types["adult-f-b"]
    P = draw_front(d, (0, 0, c, c), t, bones=True)
    f = _font(12 * SS)
    for name, x, z in bone_places(t):
        px, py = P(x, z)
        d.text((px + 5 * SS, py - 7 * SS), name, fill=BONE, font=f)
    y = 20 * SS
    d.text((c + 10 * SS, y), "Identity bones (J_Id_…), by part", fill=INK, font=_font(15 * SS))
    y += 26 * SS
    for part in PARTS:
        d.text((c + 10 * SS, y), part, fill=BONE, font=_font(13 * SS))
        y += 17 * SS
        for bone, parent, bp, _, values in RIG:
            if bp != part:
                continue
            d.text((c + 22 * SS, y), bone.replace("J_Id_", "") + (" (and _R)" if bone in PAIRED else "") + ":  " + ", ".join(v for v, *_ in values), fill=INK, font=_font(11 * SS))
            y += 15 * SS
        y += 5 * SS
    img = img.resize((img.size[0] // SS, img.size[1] // SS), Image.LANCZOS)
    img.save(os.path.join(out, "rig.jpg"), quality=92)
    made.append(("rig", img.size))
    for name, size in made:
        print(f"{name}.jpg {size[0]}x{size[1]}")
    return made


# ---------------------------------------------------------------------------------------------


def rig_table():
    rows = ["| Bone | Under | Part | Value | Does | Least to most | Was |", "|---|---|---|---|---|---|---|"]
    for bone, parent, part, at_, values in RIG:
        for i, (v, what, axis, lo, hi, unit, note) in enumerate(values):
            name = (f"`{bone}`" + (f", `{bone.replace('_L', '_R')}`" if bone in PAIRED else "")) if i == 0 else ""
            rng = f"{lo:g} to {hi:g} {unit}" if what != "scale" else f"×{lo:g} to ×{hi:g}"
            rows.append(f"| {name} | {('`' + parent + '`') if i == 0 else ''} | {part if i == 0 else ''} | `{v}` | {what} {axis} | {rng} | {note} |")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub_ = ap.add_subparsers(dest="cmd", required=True)
    m = sub_.add_parser("measure")
    m.add_argument("ref")
    sub_.add_parser("build")
    c = sub_.add_parser("check")
    c.add_argument("--people", type=int, default=200)
    d = sub_.add_parser("draw")
    d.add_argument("out")
    p = sub_.add_parser("person")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--sex", default="female")
    p.add_argument("--age", type=float, default=29)
    p.add_argument("--family")
    p.add_argument("--height", type=float)
    sub_.add_parser("rig")
    a = ap.parse_args()
    if a.cmd == "measure":
        data = load() if os.path.exists(DATA) else {}
        data["measured"] = measure(a.ref)
        json.dump(data, open(DATA, "w"), indent=1)
        print(f"measured {len(data['measured'])} anchors into {DATA}")
    elif a.cmd == "build":
        data = load()
        data = dict(about="Face types, the identity rig and the anchors they were set from (living/tools/characters/face_types.py; docs/CHARACTERS.md). Lengths are in units of the head's height H, chin to crown, unless a name says otherwise.",
                    version=1, bands=[dict(band=b, ages=[lo, min(hi, 99)]) for b, lo, hi in BANDS], lines=LINES, rig=rig_json(), measured=data["measured"], types=compose(data["measured"]))
        json.dump(data, open(DATA, "w"), indent=1)
        values = rig_values()
        print(f"built {len(data['types'])} types; the rig has {len(RIG)} bones ({len(RIG) + len(PAIRED)} with the mirrored ones), {len(values)} values a person")
    elif a.cmd == "check":
        types = load()["types"]
        bad = 0
        for tid, t in types.items():
            f = faults(apply(t, {}))
            wrong = 0
            worst = 0.0
            for i in range(a.people):
                v = draw_values(f"check/{tid}/{i}", family=f"check/{tid}/{i // 4}" if i % 2 else None)
                worst = max(worst, distance(v))
                wrong += bool(faults(apply(t, v)))
                assert not faults(apply(t, draw_valid(t, f"check/{tid}/{i}", family=f"check/{tid}/{i // 4}" if i % 2 else None))), "a pulled-back person is a valid head"
            bad += bool(f)
            print(f"{tid:12s} {'ok' if not f else 'FAULTS: ' + '; '.join(f)}; {a.people - wrong} of {a.people} people valid as drawn (furthest {worst:.2f}); all valid once pulled back")
        # Every value at its ends, alone and in pairs, on every type.
        ids = [r[0] for r in rig_values()]
        ends = 0
        cases = 0
        seen = {}
        for tid, t in types.items():
            for i, x in enumerate(ids):
                for sx in (-1, 1):
                    for y in ids[i:]:
                        for sy in (-1, 1):
                            if x == y and sx != sy:
                                continue
                            cases += 1
                            f = faults(apply(t, {x: sx, y: sy}))
                            if f:
                                ends += 1
                                seen[f[0].split("(")[0].strip()] = seen.get(f[0].split("(")[0].strip(), 0) + 1
        print(f"value ends alone and in pairs: {cases - ends} of {cases} valid" + ("; faults: " + "; ".join(f"{k} ×{v}" for k, v in sorted(seen.items(), key=lambda kv: -kv[1])[:6]) if seen else ""))
        sys.exit(1 if bad else 0)
    elif a.cmd == "draw":
        draw(a.out)
    elif a.cmd == "person":
        print(json.dumps(person(a.seed, a.sex, a.age, a.family, a.height), indent=1))
    else:
        print(rig_table())


if __name__ == "__main__":
    main()
