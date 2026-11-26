#!/usr/bin/env python3
"""The chin's ID control (char-port-2 S7, step 2 of the ortho re-measure): a copy of a type's file whose face front
draws in one fixed colour, so a level front frame shows where the chin's tip is.

    python3 chin_id.py TYPE.glb OUT.glb      # TYPE.glb may be the ear-ID copy (ear_id.py); its ears stay magenta

**The landmark:** the chin is the tip of the chin on the face's midline, where the face ends over the neck. The
drawing marks it with its ink point (drawing_spread.cheek_at: the centre run of skin at its narrowest, between the
mouth and the neck). A render has no ink there: the lit face runs into the shaded neck as unbroken skin. So the copy
colours the face's front, the skin triangles whose middle lies in front of the irises' mean depth (the face looks down
-z), and the chin on a level front frame is that region's lowest pixel on the eyes' middle column
(`drawing_spread.chin_px`; its known-answer cases are in drawing_spread_selftest.py). It is
the 3D chin's own definition (measure3d.chin: the lowest skin by the midline in front of the irises), seen in the
picture.

The front's triangles move from the skin's primitive to one of their own, drawn with the face's plain-colour material
(`FaceEyeline`: unshaded, its vertex colours) in CHIN (pure yellow); everything else is unchanged.
"""
import copy
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "living/tools"), str(Path(__file__).resolve().parents[1] / "s6b")]
from merge_primitives import read_glb, read_accessor, write_glb  # noqa: E402
from ear_id import PLAIN, SKIN, add  # noqa: E402
from measure3d import IRIS  # noqa: E402

CHIN = (1.0, 1.0, 0.0, 1.0)  # found in a frame by drawing_spread.chin_of / chin_px


def main(src, out):
    j, binary = read_glb(src)
    binary = bytearray(binary)
    mats = {m["name"]: i for i, m in enumerate(j["materials"])}
    node = next(n for n in j["nodes"] if n.get("name") == "Face" and "mesh" in n)
    prims = j["meshes"][node["mesh"]]["primitives"]
    p = next(q for q in prims if q["material"] == mats[SKIN])
    iris = next(q for q in prims if q["material"] == mats[IRIS])
    P = np.array(read_accessor(j, binary, p["attributes"]["POSITION"])[0], float).reshape(-1, 3)
    T = np.array(read_accessor(j, binary, p["indices"])[0], np.uint32).reshape(-1, 3)
    iz = np.array(read_accessor(j, binary, iris["attributes"]["POSITION"])[0], float).reshape(-1, 3)[:, 2].mean()
    front = P[T].mean(axis=1)[:, 2] < iz
    p["indices"] = add(j, binary, T[~front].ravel().tobytes(), componentType=5125, count=int((~front).sum()) * 3, type="SCALAR")
    q = copy.deepcopy(p)
    q["material"] = mats[PLAIN]
    q["indices"] = add(j, binary, T[front].ravel().tobytes(), componentType=5125, count=int(front.sum()) * 3, type="SCALAR")
    q["attributes"]["COLOR_0"] = add(j, binary, np.tile(np.array(CHIN, np.float32), (len(P), 1)).tobytes(), componentType=5126, count=len(P), type="VEC4")
    q["attributes"].pop("TEXCOORD_1", None)
    prims.append(q)
    j["buffers"][0]["byteLength"] = len(binary)
    write_glb(out, j, binary)
    print(f"chin_id: {int(front.sum())} front triangles (in front of the irises at z {iz:.4f}) in {CHIN[:3]} in {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
