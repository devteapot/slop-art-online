#!/usr/bin/env python3
"""The plait's ID control (char-port-2 S6): a copy of a master's style file whose plait draws pure
green, so the game camera's frame says which pixels are the plait (char-live-3's material-ID
control, in the generator's terms).

    python3 plait_id.py WITH.glb WITHOUT.glb OUT.glb

WITH is the cut, WITHOUT the same cut built without its plait (SLOP_MASTER_PLAIT=0): every vertex
of WITH's hair meshes that WITHOUT does not have (by position, to 0.01 mm) is the plait's. Its
triangles move to a primitive of their own whose material is a fixed hand-made hair profile, green
in all four bands; everything else is left as it is.
"""
import copy
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "living/tools"))
from merge_primitives import read_glb, write_glb  # noqa: E402

GREEN = [0, 255, 0]


def accessor(j, binary, i):
    a = j["accessors"][i]
    bv = j["bufferViews"][a["bufferView"]]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    dt = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}[a["componentType"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    return np.frombuffer(bytes(binary[off: off + a["count"] * n * np.dtype(dt).itemsize]), dt).reshape(a["count"], n)


def keys(pos):
    return {tuple(p) for p in np.round(pos * 1e5).astype(np.int64)}


def main(with_path, without_path, out_path):
    j, binary = read_glb(with_path)
    j0, b0 = read_glb(without_path)
    binary = bytearray(binary)
    others = set()
    for m in j0["meshes"]:
        for p in m["primitives"]:
            others |= keys(accessor(j0, b0, p["attributes"]["POSITION"]).astype(np.float64))
    hair = next(i for i, m in enumerate(j["materials"]) if "_HAIR" in m.get("name", ""))
    green = copy.deepcopy(j["materials"][hair])
    green["name"] = "ZZ_PlaitId_HAIR"
    h = green.setdefault("extras", {}).setdefault("slop", {}).setdefault("hair", {})
    for k in ("anchors", "ref", "ink", "ink_px", "ink_range", "ink_fade_px", "ink_m_uv", "highlight_map", "strands"):
        h.pop(k, None)
    h.update(palette="fixed", shade=GREEN, mid=GREEN, light=GREEN, highlight=GREEN)
    j["materials"].append(green)
    gid = len(j["materials"]) - 1
    moved = 0
    for m in j["meshes"]:
        add = []
        for p in m["primitives"]:
            if p.get("material") != hair:
                continue
            pos = accessor(j, binary, p["attributes"]["POSITION"]).astype(np.float64)
            plait = np.array([tuple(q) not in others for q in np.round(pos * 1e5).astype(np.int64)])
            idx = accessor(j, binary, p["indices"]).reshape(-1, 3).astype(np.uint32)
            mine = plait[idx].all(axis=1)
            if not mine.any():
                continue
            moved += int(mine.sum())
            for sel, target in ((~mine, p), (mine, None)):
                data = idx[sel].astype(np.uint32).ravel().tobytes()
                while len(binary) % 4:
                    binary.append(0)
                j["bufferViews"].append(dict(buffer=0, byteOffset=len(binary), byteLength=len(data), target=34963))
                binary.extend(data)
                j["accessors"].append(dict(bufferView=len(j["bufferViews"]) - 1, componentType=5125, count=int(sel.sum()) * 3, type="SCALAR"))
                if target is not None:
                    target["indices"] = len(j["accessors"]) - 1
                else:
                    q = copy.deepcopy(p)
                    q["indices"] = len(j["accessors"]) - 1
                    q["material"] = gid
                    add.append(q)
        m["primitives"] += add
    j["buffers"][0]["byteLength"] = len(binary)
    write_glb(out_path, j, binary)
    print(f"plait_id: {moved} plait triangles green in {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
