#!/usr/bin/env python3
"""How close is the landmark sketch of a value to what its bone does? Each value, alone at -1 and at +1.

    python3 living/tools/characters/rig_check.py [TYPE] [--values a,b,...] [--people N]

A value is defined by its bone (compose.transforms and cage_head.identity_weights): that is what
the client does to a type's mesh, and what `person.py --bake` does itself. face_types.apply is a
simpler account of the same value on a type's sections and features. It draws the diagrams and
runs the validity checks, where a whole head would be slow to build. This says how far that
account is from the bones, so its checks are read with that in mind:

- **on the landmarks** (face_types.apply): the type's record changed, and a head built on it;
- **on the bones**: the type's own mesh, skinned.

For each value this builds the type's skin both ways, without Blender: the cage of the changed
landmarks, and the type's own cage skinned by the bones (linear blend skinning, as the game does
it). Both have the same vertices, so the distance is exact, vertex by vertex. It prints how far
the baked head moved from the type, and how far the composed one is from the baked: root mean
square and the most, in mm on a head as it is in a character file. Surfaces are compared along
the baked surface's normals, since a feature may slide along a plane without the plane changing;
the feature points (the eyes' edges, the nose's tip, the mouth's corners, the chin, the jaw's
angles, the brows) are compared in full.
"""

import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "blender"))
import cage_head  # noqa: E402
import compose  # noqa: E402
import face_types  # noqa: E402
import person_params  # noqa: E402

LOOK = None


def skin_of(t):
    """A head's skin from its cage (every vertex, nothing cut away), in head_form's frame, and the head."""
    global LOOK
    LOOK = LOOK or person_params.resolve(person_params.draw(dict(seed=1, sex="female", age=30)))["look"]
    hf = cage_head.CageHead(t)
    cage = cage_head.Cage(t, state=dict(lids=lambda side, s, upper: hf.lid(np.array(s, float))[0 if upper else 1]))
    S, quads = cage.subdivided()[:2]
    R, vid = cage.R, cage.vid
    marks = {"eye": [v for loop in cage.eye.values() for v in loop], "nose tip": [vid(R["tip"], 0)], "mouth corner": [vid(R["mouth"], 2), vid(R["mouth"], cage_head.COLS - 2)], "chin": [vid(R["jaw"], 0)],
             "jaw angle": [vid(R["jaw"], cage_head.C_WIDE), vid(R["jaw"], cage_head.COLS - cage_head.C_WIDE)]}
    hf.marks, hf.quads = marks, quads
    return S @ cage.v, hf


def composed(base, hf, values):
    mats = cage_head.bone_matrices(hf, values)
    weights = cage_head.identity_weights(hf, base, brows=True)  # the face's own skin: the skin round a brow follows the brow's bone
    ph = np.concatenate([base, np.ones((len(base), 1))], axis=1)
    out = np.zeros_like(base)
    for i, ws in enumerate(weights):
        for name, x in ws.items():
            out[i] += x * (mats[name] @ ph[i])[:3]
    return out


def where(hf, p):
    H = hf.H
    return f"{'left ' if p[0] < -0.01 else 'right ' if p[0] > 0.01 else 'mid '}{p[2] / H + cage_head.ZC:.2f} H up, {p[1] / H - cage_head.YB:+.2f} H deep"


def one(t, base, hf, values):
    """A set of values both ways. The surfaces are compared along the baked one's normals (a
    feature may slide along a plane without the plane changing); the feature points in full."""
    tp = face_types.apply(t, values)
    baked, hb = skin_of(tp)
    baked = baked + np.array([0.0, 0.0, tp["head"].get("chin_drop", 0.0) * hf.H])
    comp = composed(base, hf, values)
    normals = cage_head.CageFace._normals(baked, hb.quads)

    def surface(a):
        d = np.empty(len(a))
        for i in range(0, len(a), 512):
            near = ((a[i : i + 512, None, :] - baked[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
            d[i : i + 512] = np.abs(((a[i : i + 512] - baked[near]) * normals[near]).sum(axis=1))
        return d

    moved, off = surface(base), surface(comp)
    ids = [v for vs in hf.marks.values() for v in vs]
    mark_moved = np.linalg.norm(baked[ids] - base[ids], axis=1)
    mark_off = np.linalg.norm(comp[ids] - baked[ids], axis=1)
    names = [n for n, vs in hf.marks.items() for _ in vs]
    rms = lambda d: float(np.sqrt((d ** 2).mean()) * 1000)
    return dict(moved_rms=rms(moved), moved_max=float(moved.max() * 1000), off_rms=rms(off), off_max=float(off.max() * 1000), worst=where(hf, base[int(np.argmax(off))]),
                mark_moved=float(mark_moved.max() * 1000), mark_off=float(mark_off.max() * 1000), mark=names[int(np.argmax(mark_off))])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("type", nargs="?", default="adult-f-b")
    ap.add_argument("--values", default="")
    ap.add_argument("--people", type=int, default=0)
    a = ap.parse_args()
    t = face_types.load()["types"][a.type]
    base, hf = skin_of(face_types.apply(t, {}))
    ids = [v for v in a.values.split(",") if v] or [r[0] for r in face_types.rig_values()]
    print(f"{a.type}: {len(base)} vertices; mm on a head of {hf.H * 100:.1f} cm")
    print(f"{'value':18s} {'at':>3s}  {'surface: baked moved':>20s} {'most':>5s}  {'composed off':>12s} {'most':>5s}   {'features: baked moved':>21s} {'composed off':>12s}  worst feature")
    for v in ids:
        for x in (-1.0, 1.0):
            r = one(t, base, hf, {v: x})
            print(f"{v:18s} {x:+3.0f}  {r['moved_rms']:20.2f} {r['moved_max']:5.1f}  {r['off_rms']:12.2f} {r['off_max']:5.1f}   {r['mark_moved']:21.1f} {r['mark_off']:12.1f}  {r['mark'] if r['mark_off'] > 0.5 else ''}")
    rows = []
    for i in range(a.people):
        vals = face_types.draw_valid(t, f"rig_check/{i}")
        rows.append(one(t, base, hf, vals))
    if rows:
        med = lambda k: float(np.median([r[k] for r in rows]))
        top = lambda k: float(np.max([r[k] for r in rows]))
        print(f"{len(rows)} drawn people: the baked surface moved {med('moved_rms'):.2f} mm rms from the type's (most {top('moved_max'):.1f}) and its features up to {med('mark_moved'):.1f} mm; "
              f"the composed surface is {med('off_rms'):.2f} mm rms from the baked at the median, {top('off_rms'):.2f} at worst (worst point {top('off_max'):.1f} mm); features up to {med('mark_off'):.1f} mm at the median, {top('mark_off'):.1f} at worst")


if __name__ == "__main__":
    main()
