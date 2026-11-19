#!/usr/bin/env python3
"""Write a copy of a GLB with the hand-made contract's extras (docs/HANDMADE_HAIR.md).

    python3 living/tools/characters/handmade_extras.py IN.glb OUT.glb SPEC.json [--test-highlight]

SPEC.json:

    {"scene": {"contract": 1, "character": "handmade", "forward": "+Z"},
     "materials": {"<material name>": {"slot": "hair", "hair": {...}}, ...}}

`scene` becomes the default scene's `extras.slop`; each named material's object its
`extras.slop` (other extras are kept). Materials the spec does not name are left alone, and a
name the file does not have is an error. OUT must differ from IN: the source file is never
rewritten.

`--test-highlight` adds a **stand-in** `_HIGHLIGHT` (SCALAR FLOAT) to the profile hair's
primitives, for trying the client before an author paints one: a band round the crown (about
5-11 cm below the hair's top, so long hanging hair does not move it), its edges waved lock by
lock round the head, off surfaces facing down or forward (the fringe). It is not an authored
mask.
Plain Python; uses merge_primitives' GLB helpers.
"""

import argparse
import json
import math
import os
import sys
from array import array

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from merge_primitives import append_accessor, read_accessor, read_glb, write_glb  # noqa: E402

FLOAT, ARRAY_BUFFER = 5126, 34962


def smooth(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def test_highlight(j, binary, hair_mats, plus_z):
    """A stand-in mask on the hair primitives (one accessor per POSITION accessor they use)."""
    groups = {}
    for m in j["meshes"]:
        for p in m["primitives"]:
            if p.get("material") in hair_mats:
                groups.setdefault((p["attributes"]["POSITION"], p["attributes"]["NORMAL"]), []).append(p)
    done = 0
    for (pacc, nacc), prims in groups.items():
        pos, _ = read_accessor(j, binary, pacc)
        nor, _ = read_accessor(j, binary, nacc)
        used = set()
        for p in prims:
            idx, _ = read_accessor(j, binary, p["indices"])
            used.update(idx)
        ys = [pos[3 * v + 1] for v in used]
        lo, hi = min(ys), max(ys)
        cx = sum(pos[3 * v] for v in used) / len(used)
        cz = sum(pos[3 * v + 2] for v in used) / len(used)
        fz = 1.0 if plus_z else -1.0
        out = array("f", [0.0]) * (len(pos) // 3)
        for v in used:
            x, y, z = pos[3 * v : 3 * v + 3]
            nx, ny, nz = nor[3 * v : 3 * v + 3]
            depth = hi - y
            theta = math.atan2(x - cx, (z - cz) * fz)
            centre = 0.08 + 0.012 * math.sin(5.0 * theta) + 0.007 * math.sin(11.0 * theta + 1.3)
            band = 0.5 + (0.03 - abs(depth - centre)) / 0.02
            rx, rz = x - cx, z - cz
            rl = math.hypot(rx, rz) or 1.0
            outward = (nx * rx + nz * rz) / rl + max(ny, 0.0)
            keep = smooth(0.15, 0.45, outward) * smooth(-0.2, 0.1, ny) * (1.0 - smooth(0.55, 0.8, nz * fz))
            out[v] = min(max(band, 0.0), 1.0) * keep
        acc = append_accessor(j, binary, out, FLOAT, "SCALAR", False, ARRAY_BUFFER)
        for p in prims:
            p["attributes"]["_HIGHLIGHT"] = acc
        done += sum(1 for v in used if out[v] > 0.5)
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("spec")
    ap.add_argument("--test-highlight", action="store_true")
    a = ap.parse_args()
    if os.path.abspath(a.inp) == os.path.abspath(a.out):
        sys.exit("handmade_extras: OUT must not be IN (write a copy)")
    spec = json.load(open(a.spec))
    j, binary = read_glb(a.inp)
    scene = j["scenes"][j.get("scene", 0)]
    scene.setdefault("extras", {})["slop"] = spec["scene"]
    names = {m.get("name"): i for i, m in enumerate(j.get("materials", []))}
    hair = set()
    for name, slop in spec.get("materials", {}).items():
        if name not in names:
            sys.exit(f"handmade_extras: {a.inp} has no material {name!r}")
        j["materials"][names[name]].setdefault("extras", {})["slop"] = slop
        if slop.get("slot") == "hair" and "hair" in slop:
            hair.add(names[name])
    unnamed = sorted(n for n in names if n not in spec.get("materials", {}))
    if unnamed:
        print(f"handmade_extras: no slot given for {unnamed}")
    if a.test_highlight:
        n = test_highlight(j, binary, hair, spec["scene"].get("forward") == "+Z")
        print(f"handmade_extras: stand-in _HIGHLIGHT, {n} hair vertices above 0.5")
    write_glb(a.out, j, binary)
    print(f"handmade_extras: {a.out}: scene and {len(spec.get('materials', {}))} material(s) marked")


if __name__ == "__main__":
    main()
