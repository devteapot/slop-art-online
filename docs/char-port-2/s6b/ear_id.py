#!/usr/bin/env python3
"""The ears' ID control (char-port-2 S6b, the GC's 2D acceptance): a copy of a type's file whose ears draw in one
fixed colour, so the game's front frame says which pixels are ear.

    python3 ear_id.py TYPE.glb OUT.glb

The ears are the face skin's two small connected pieces (measure3d.ear_triangles; its known-answer test,
measure3d_selftest.py, covers this tool too). Their triangles move from
the skin's primitive to one of their own, drawn with the face's plain-colour material (`FaceEyeline`: no texture,
unshaded, its vertex colours; the client does not recolour it) in EAR (pure magenta). The ears keep their place,
bones and shape keys; nothing else changes.
"""
import copy
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "living/tools"), str(Path(__file__).resolve().parent)]
from merge_primitives import read_glb, read_accessor, write_glb  # noqa: E402
from measure3d import ear_triangles  # noqa: E402

EAR = (1.0, 0.0, 1.0, 1.0)
SKIN, PLAIN = "M00_000_00_Face_00_SKIN", "M00_000_00_FaceEyeline_00_FACE"


def add(j, binary, data, **acc):
    while len(binary) % 4:
        binary.append(0)
    j["bufferViews"].append(dict(buffer=0, byteOffset=len(binary), byteLength=len(data)))
    binary.extend(data)
    j["accessors"].append(dict(bufferView=len(j["bufferViews"]) - 1, **acc))
    return len(j["accessors"]) - 1


def main(src, out):
    j, binary = read_glb(src)
    binary = bytearray(binary)
    mats = {m["name"]: i for i, m in enumerate(j["materials"])}
    node = next(n for n in j["nodes"] if n.get("name") == "Face" and "mesh" in n)
    prims = j["meshes"][node["mesh"]]["primitives"]
    p = next(q for q in prims if q["material"] == mats[SKIN])
    P = np.array(read_accessor(j, binary, p["attributes"]["POSITION"])[0], float).reshape(-1, 3)
    T = np.array(read_accessor(j, binary, p["indices"])[0], np.uint32).reshape(-1, 3)
    ear = ear_triangles(P, T)
    p["indices"] = add(j, binary, T[~ear].ravel().tobytes(), componentType=5125, count=int((~ear).sum()) * 3, type="SCALAR")
    q = copy.deepcopy(p)
    q["material"] = mats[PLAIN]
    q["indices"] = add(j, binary, T[ear].ravel().tobytes(), componentType=5125, count=int(ear.sum()) * 3, type="SCALAR")
    q["attributes"]["COLOR_0"] = add(j, binary, np.tile(np.array(EAR, np.float32), (len(P), 1)).tobytes(), componentType=5126, count=len(P), type="VEC4")
    q["attributes"].pop("TEXCOORD_1", None)
    prims.append(q)
    j["buffers"][0]["byteLength"] = len(binary)
    write_glb(out, j, binary)
    print(f"ear_id: {int(ear.sum())} ear triangles in {EAR[:3]} in {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
