#!/usr/bin/env python3
"""Opt a generated file's ink carriers in (char-port-2 S4; docs/HANDMADE_COMPOSED.md v1.3):

    python3 living/tools/characters/type_ink.py FILE.glb [FILE.glb ...]     # rewrites each in place
    python3 living/tools/characters/type_ink.py --page LOOKDEV_TYPES_DIR      # the ink page and its manifest

**A file** (a type file, or a person's own file, built with `SLOP_PORT=ink`) that has carriers
(`ink_carriers.LID_MAT`, `BROW_MAT`) gets:
- its scene's `extras.slop = {"contract": 1}` (merged; no `character`), so the client reads its
  materials' `slop`;
- on each carrier material: `alphaMode` BLEND, `baseColorFactor` [1, 1, 1, 0], no texture, and
  `extras.slop` = `{"slot": "eyes", "ink": …}` with the page as its `map` and the declared
  `m_uv` (ink_carriers.INK).

A file without carriers is left as it is.

**The page** (`--page DIR`): every class's strokes on one 4096² page, `DIR/types.eyes.ink.png`
(by ink_field.py from the strokes, G the distance and R the half-width over the range), and
`DIR/types.ink.json`, its manifest (HANDMADE_COMPOSED "The ink page"), with the strokes beside it
(`DIR/types.eyes.strokes.json`). The classes' layouts are the generator's (ink_carriers.layout,
from each class's line b), so the page is made without Blender.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "blender"))
sys.path.insert(0, HERE)
from merge_primitives import read_glb, write_glb  # noqa: E402


def opt_in(path):
    import ink_carriers

    j, binary = read_glb(path)
    mats = {m.get("name"): m for m in j.get("materials", [])}
    carriers = [n for n in (ink_carriers.LID_MAT, ink_carriers.BROW_MAT) if n in mats]
    if not carriers:
        return False
    for n in carriers:
        m = mats[n]
        m["alphaMode"] = "BLEND"
        pbr = m.setdefault("pbrMetallicRoughness", {})
        pbr.pop("baseColorTexture", None)
        pbr["baseColorFactor"] = [1.0, 1.0, 1.0, 0.0]
        m.setdefault("extras", {})["slop"] = ink_carriers.slop(n)
    scene = j["scenes"][j.get("scene", 0)]
    slop = scene.setdefault("extras", {}).setdefault("slop", {})
    slop.pop("character", None)
    slop["contract"] = 1
    write_glb(path, j, binary)
    return True


def page(out):
    import cage_head
    import face_types
    import head_mesh
    import ink_carriers

    strokes, manifest = ink_carriers.page_strokes(face_types.load()["types"], cage_head, face_types, head_mesh)
    os.makedirs(out, exist_ok=True)
    spath = os.path.join(out, "types.eyes.strokes.json")
    with open(spath, "w") as f:
        json.dump(strokes, f, separators=(",", ":"))
    png = os.path.join(out, "types.eyes.ink.png")
    subprocess.run([sys.executable, os.path.join(HERE, "ink_field.py"), spath, png, "--range", str(ink_carriers.RANGE_UV)], check=True)
    with open(os.path.join(out, "types.ink.json"), "w") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    print(f"type_ink: {png}: {len(strokes['strokes'])} strokes for {len(manifest['classes'])} classes; manifest types.ink.json")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--page", metavar="DIR")
    a = ap.parse_args()
    if a.page:
        page(a.page)
    for f in a.files:
        print(f"type_ink: {f}: {'carriers opted in' if opt_in(f) else 'no carriers'}")


if __name__ == "__main__":
    main()
