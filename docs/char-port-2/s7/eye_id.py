#!/usr/bin/env python3
"""The eyes' ID control (char-port-2 S7, must-fix 1: no eye white or iris above a closed lid): a copy of a person's
file whose eye white and iris draw in one fixed colour, held at a key's full weight, so the game's frame says which
pixels are eye.

    python3 eye_id.py PERSON.glb OUT.glb [--key Fcl_EYE_Joy]

The `Eye` and `EyeIris` primitives of the `Face` mesh are drawn with the face's plain-colour material (`FaceEyeline`:
no texture, unshaded, its vertex colours; the client does not recolour it) in EYE (pure cyan). With `--key`, the
face's default weights hold that key at 1 (Bevy takes them as the initial MorphWeights), every other key at 0.
Nothing else changes. Known-answer test: eye_count_selftest.py.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "living/tools")]
from merge_primitives import read_glb, write_glb  # noqa: E402

EYE = (0.0, 1.0, 1.0, 1.0)
PARTS = ("M00_000_00_Eye_00_EYE", "M00_000_00_EyeIris_00_EYE")
PLAIN = "M00_000_00_FaceEyeline_00_FACE"


def add(j, binary, data, **acc):
    while len(binary) % 4:
        binary.append(0)
    j["bufferViews"].append(dict(buffer=0, byteOffset=len(binary), byteLength=len(data)))
    binary.extend(data)
    j["accessors"].append(dict(bufferView=len(j["bufferViews"]) - 1, **acc))
    return len(j["accessors"]) - 1


def main(src, out, key=None):
    j, binary = read_glb(src)
    binary = bytearray(binary)
    mats = {m["name"]: i for i, m in enumerate(j["materials"])}
    moved = 0
    for n in j["nodes"]:
        if n.get("name") != "Face" or "mesh" not in n:
            continue
        mesh = j["meshes"][n["mesh"]]
        for p in mesh["primitives"]:
            if j["materials"][p["material"]]["name"] in PARTS:
                count = j["accessors"][p["attributes"]["POSITION"]]["count"]
                p["material"] = mats[PLAIN]
                p["attributes"]["COLOR_0"] = add(j, binary, np.tile(np.array(EYE, np.float32), (count, 1)).tobytes(), componentType=5126, count=count, type="VEC4")
                moved += 1
        if key:
            names = mesh.get("extras", {}).get("targetNames", [])
            if key not in names:
                raise SystemExit(f"eye_id: {key} not among {names}")
            mesh["weights"] = [1.0 if k == key else 0.0 for k in names]
    if moved != 2:
        raise SystemExit(f"eye_id: found {moved} of the eye's two primitives")
    j["buffers"][0]["byteLength"] = len(binary)
    write_glb(out, j, binary)
    print(f"eye_id: eye white and iris in {EYE[:3]}{', ' + key + ' held' if key else ''} in {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--key")
    a = ap.parse_args()
    main(a.src, a.out, a.key)
