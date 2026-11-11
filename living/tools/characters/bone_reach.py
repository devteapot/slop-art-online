#!/usr/bin/env python3
"""How far identity bones reach: can bones with soft weights turn one head into another?

    python3 living/tools/characters/bone_reach.py [--sex female|male] [--people 40] [--json OUT]

The plan after pass 3's first step puts a person's identity on bones over a shared mesh for each
face type (docs/CHARACTERS.md, "Types and rig"). Before any mesh is built for that, this asks
whether bones can do what pass 2's 34 face values do. For each value at -1 and at +1 (and for
people drawn from seeds), it takes pass 2's head with every value at 0 (head_form.Head) as the
shared mesh and the head with that value set as the target, and fits the rig's bones to carry
the one onto the other:

- what must match: about 1,800 points of the face's and skull's surface, which only have to
  land on the target's surface, and 42 landmarks (eye corners and lids, brows, the nose's
  bridge, tip, base and wings, the mouth's corners and lips, the chin, the jaw's angle, the
  cheekbones, the ears, the crown), which have to land on the target's landmarks and count
  three times as much, so a feature that slides along the surface has to be followed;
- the bones: 25 of the rig's (face_types.RIG with the mirrored ones; the eyes' own bones carry
  no skin), each with a soft weight
  field round its pivot, each free to move, scale along its axes and turn a little. That is more
  freedom than the rig's named values give a bone, so the result is the most these bones could
  do, not what the 38 values do;
- the fit is linear least squares (linear blend skinning is linear in each bone's move, scale
  and small turn).

It prints, for each value, how far the surface and the landmarks moved (root mean square and
the most, in mm on the finished head) and what is left after the bones. A value whose change
is mostly left over is a shape bones do not reach: a type must fix it, or a morph carry it.
Values that move neither (the iris, the brows' thickness and length, the lid fold, the ears)
change parts that have a bone of their own. numpy only.
"""

import argparse
import json
import math
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "blender"))
sys.path.insert(0, HERE)
import head_form  # noqa: E402
import person_params  # noqa: E402

ORIGIN = head_form.ORIGIN
MM = 1000.0 * 1.14  # the form's own metres to mm on the finished head (person.py's head scale at the style in use)


def head(sex, face):
    p = person_params.draw(dict(seed=1, sex=sex, age=29 if sex == "female" else 36, build=dict(weight=0.0, muscle=0.0), face=dict({k: 0.0 for k in person_params.FACE_KEYS}, **face)))
    s = person_params.resolve(p)
    return head_form.Head(masc=s["masc"], child=s["child"], elder=s["elder"], face=s["face"], style=s["style"])


def directions():
    """Directions out of the head's middle: the face densely, the skull's top and sides."""
    out = []
    for el in np.arange(-62, 84, 4.0):
        step = 4.0 / max(math.cos(math.radians(el)), 0.25)
        for az in np.arange(-128, 128.1, step):
            a, e = math.radians(az), math.radians(el)
            out.append((-math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))
    return np.array(out)


def landmarks(hf):
    """Named points of a head, from its own numbers: where its features are."""
    ex, ez, ew = hf.eye_x, hf.eye_z, hf.eye_w
    up0, lo0 = (float(v) for v in hf.lid(np.array(0.0)))
    up_i, lo_i = (float(v) for v in hf.lid(np.array(-1.0)))
    up_o, lo_o = (float(v) for v in hf.lid(np.array(1.0)))
    brow = ez + hf.eye_up + hf.brow_up
    front, names = [], []
    for sx, side in ((-1, "L"), (1, "R")):
        for name, x, z in (("eye.in", ex - ew, ez + up_i), ("eye.out", ex + ew, ez + up_o), ("eye.top", ex, ez + up0), ("eye.low", ex, ez + lo0), ("eye.mid", ex, ez + (up0 + lo0) / 2),
                           ("brow.in", ex - ew, brow - hf.brow_tilt), ("brow.mid", ex + 0.2 * ew, brow + hf.brow_arch), ("brow.out", ex + 1.1 * ew, brow + hf.brow_tilt),
                           ("nose.wing", 0.0112 * hf.nose_wid, hf.nose_base_z + 0.0048), ("mouth.corner", hf.mouth_w, float(hf.mouth_line(np.array([hf.mouth_w]))[0])),
                           ("cheek", 0.036, ez - 0.047 * hf.L), ("corner", ex + 1.5 * ew, ez)):
            front.append((sx * x, z))
            names.append(f"{name}.{side}")
    for name, x, z in (("nasion", 0.0, hf.nasion_z), ("nose.tip", 0.0, hf.nose_tip_z), ("nose.base", 0.0, hf.nose_base_z), ("lip.up", 0.0, hf.mouth_z + 0.0048), ("lip.low", 0.0, hf.mouth_z - 0.0058),
                       ("mouth", 0.0, hf.mouth_z), ("chin", 0.0, hf.chin_z + 0.006), ("glabella", 0.0, brow), ("forehead", 0.0, 0.055)):
        front.append((x, z))
        names.append(name)
    pts = list(hf.project_front(front)[0])
    zj = head_form.lerp(hf.mouth_z, hf.chin_z, 0.30)
    for sx, side in ((-1, "L"), (1, "R")):
        for name, az, z in (("gonion", 78.0, zj), ("zygoma", 62.0, -0.030 * hf.L), ("ear", 92.0, head_form.lerp(ez + 0.020, hf.nose_base_z, 0.5)), ("temple", 70.0, 0.05)):
            pts.append(hf.point(-sx * az, z))
            names.append(f"{name}.{side}")
    pts.append(np.array([0.0, -0.01, hf.top_z]))
    names.append("crown")
    return np.array(pts), names


def bones(hf):
    """The rig's bones on a head: (name, pivot, weight field)."""
    L, names = landmarks(hf)
    at = dict(zip(names, L))
    brow_z = hf.eye_z + hf.eye_up + hf.brow_up
    sm = lambda x: np.clip(x, 0, 1) ** 2 * (3 - 2 * np.clip(x, 0, 1))
    ball = lambda c, r: (lambda p: np.exp(-((np.linalg.norm(p - c, axis=1) / r) ** 2)))
    out = [("Cranium", np.array([0.0, -0.01, brow_z]), lambda p: sm((p[:, 2] - brow_z + 0.012) / 0.03)),
           ("Face", at["nasion"], lambda p: (1 - sm((p[:, 2] - brow_z + 0.012) / 0.03)) * sm((p[:, 1] + 0.03) / 0.05)),
           ("Jaw", np.array([0.0, -0.01, hf.mouth_z + 0.02]), lambda p: sm((hf.mouth_z + 0.014 - p[:, 2]) / 0.03) * sm((p[:, 1] + 0.05) / 0.05)),
           ("Forehead", at["forehead"], ball(at["forehead"], 0.045)), ("Glabella", at["glabella"], ball(at["glabella"], 0.022)), ("Chin", at["chin"], ball(at["chin"], 0.028)),
           ("Nose", (at["nasion"] + at["nose.tip"]) / 2, ball((at["nasion"] + at["nose.tip"]) / 2, 0.020)), ("NoseTip", at["nose.tip"], ball(at["nose.tip"], 0.012)), ("Mouth", at["mouth"], ball(at["mouth"], 0.020))]
    for side in "LR":
        for name, key, r in (("Corner", "corner", 0.028), ("Zygoma", "zygoma", 0.032), ("Cheek", "cheek", 0.028), ("Gonion", "gonion", 0.032), ("Orbit", "eye.mid", 0.022), ("Brow", "brow.mid", 0.017),
                             ("MouthCorner", "mouth.corner", 0.010), ("Ear", "ear", 0.030)):
            out.append((f"{name}_{side}", at[f"{key}.{side}"], ball(at[f"{key}.{side}"], r)))
    return out


def fit(a, b, dirs):
    """Fit the bones on head a to carry it onto head b. A surface point only has to land on b's
    surface (its distance along b's normal counts; sliding along the surface is free); a
    landmark has to land on b's landmark. Returns what moved and what is left, in metres of
    the form."""
    ra, rb = a.radius(dirs), b.radius(dirs)
    pa, pb = ORIGIN + dirs * ra[:, None], ORIGIN + dirs * rb[:, None]
    nb = b.normal(pb)
    la, names = landmarks(a)
    lb, _ = landmarks(b)
    P = np.concatenate([pa, la])
    n = len(pa)
    rig = bones(a)
    W = np.stack([f(P) for _, _, f in rig], axis=1)
    W = W / np.maximum(W.sum(axis=1, keepdims=True), 1.0)
    cols = []
    for k, (_, c, _) in enumerate(rig):
        q = P - c
        w = W[:, k]
        z = np.zeros(len(P))
        for axis in range(3):  # a move along each axis
            m = np.zeros((len(P), 3))
            m[:, axis] = w
            cols.append(m)
        for axis in range(3):  # a scale along each axis, about the pivot
            m = np.zeros((len(P), 3))
            m[:, axis] = w * q[:, axis]
            cols.append(m)
        for m in (np.stack([z, -w * q[:, 2], w * q[:, 1]], axis=1), np.stack([w * q[:, 2], z, -w * q[:, 0]], axis=1), np.stack([-w * q[:, 1], w * q[:, 0], z], axis=1)):  # a small turn about each axis
            cols.append(m)
    # Rows: each surface point's move along the target's normal; each landmark's move in full, three times the weight.
    A = np.concatenate([np.stack([(m[:n] * nb).sum(axis=1) for m in cols], axis=1), 3.0 * np.stack([m[n:].reshape(-1) for m in cols], axis=1)])
    surf, land = ((pb - pa) * nb).sum(axis=1), lb - la
    y = np.concatenate([surf, 3.0 * land.reshape(-1)])
    # A little ridge keeps bones that have nothing to do at rest.
    x = np.linalg.solve(A.T @ A + 1e-7 * np.eye(A.shape[1]), A.T @ y)
    left = y - A @ x
    left_s, left_l = left[:n], left[n:].reshape(-1, 3) / 3.0
    rms = lambda v: float(np.sqrt((v ** 2).mean()))
    dist = lambda v: np.linalg.norm(v, axis=1)
    return dict(surface_moved=rms(surf), surface_left=rms(left_s), surface_left_max=float(np.abs(left_s).max()), land_moved=rms(dist(land)), land_moved_max=float(dist(land).max()),
                land_left=rms(dist(left_l)), land_left_max=float(dist(left_l).max()), worst=names[int(np.argmax(dist(left_l)))], bones=len(rig))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sex", default="female")
    ap.add_argument("--people", type=int, default=40)
    ap.add_argument("--json")
    a = ap.parse_args()
    dirs = directions()
    base = head(a.sex, {})
    rows = []
    for key in person_params.FACE_KEYS:
        for v in (-1.0, 1.0):
            r = fit(base, head(a.sex, {key: v}), dirs)
            rows.append(dict(value=key, at=v, **r))
    print(f"{len(dirs)} surface points, {len(landmarks(base)[1])} landmarks, {rows[0]['bones']} bones; a {a.sex} head; mm on the finished head")
    print(f"{'value':16s} {'at':>3s}  {'surface: moved':>14s} {'left':>5s} {'most':>5s}   {'landmarks: moved':>16s} {'most':>5s} {'left':>5s} {'most':>5s}  worst landmark")
    for r in rows:
        print(f"{r['value']:16s} {r['at']:+3.0f}  {r['surface_moved'] * MM:14.2f} {r['surface_left'] * MM:5.2f} {r['surface_left_max'] * MM:5.1f}   {r['land_moved'] * MM:16.2f} {r['land_moved_max'] * MM:5.1f} "
              f"{r['land_left'] * MM:5.2f} {r['land_left_max'] * MM:5.1f}  {r['worst'] if r['land_left_max'] * MM > 0.3 else ''}")
    people = []
    for i in range(a.people):
        rnd = random.Random(f"reach/{i}")
        face = {k: max(-1.0, min(1.0, rnd.gauss(0, 0.52))) for k in person_params.FACE_KEYS}
        people.append(fit(base, head(a.sex, face), dirs))
    if people:
        med = lambda k: float(np.median([p[k] for p in people])) * MM
        top = lambda k: float(np.max([p[k] for p in people])) * MM
        print(f"{len(people)} people drawn as pass 2 draws them (every value at once): the surface moved {med('surface_moved'):.2f} mm rms and the landmarks {med('land_moved'):.2f} mm (most {top('land_moved_max'):.1f}); "
              f"left after the bones: surface {med('surface_left'):.2f} mm rms at the median and {top('surface_left'):.2f} at worst (worst point {top('surface_left_max'):.1f} mm), "
              f"landmarks {med('land_left'):.2f} mm rms at the median and {top('land_left'):.2f} at worst (worst landmark {top('land_left_max'):.1f} mm)")
    if a.json:
        json.dump(dict(sex=a.sex, mm=MM, values=rows, people=people), open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
