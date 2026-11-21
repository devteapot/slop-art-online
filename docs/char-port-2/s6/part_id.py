#!/usr/bin/env python3
"""The master's parts' ID control (char-port-2 S6 step 3): a copy of a master's style file whose
parts each draw in a fixed colour of their own, so the game camera's frame says which part made
which pixels (plait_id.py, for any part).

    python3 part_id.py WITH.glb OUT.glb --part hooks=WITHOUT_HOOKS.glb [--part ...]
    python3 part_id.py WITH.glb OUT.glb --all                      # all its hair one colour

WITH is the cut; each WITHOUT the same cut built without that part (SLOP_MASTER_DROP=<part>).
Every triangle of WITH's hair whose vertices WITHOUT does not have (by position, to 0.01 mm) is
the part's, and moves to a primitive whose material is a fixed hand-made hair profile in that
part's colour (COLOURS, in the order given). With `--all`, the whole hair material is the first
colour instead: the outline check's mask (back_views.py outline).
"""
import argparse
import copy
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "living/tools"))
from merge_primitives import read_glb, write_glb  # noqa: E402
from plait_id import accessor, keys  # noqa: E402

COLOURS = [[0, 255, 0], [255, 0, 255], [0, 110, 255], [255, 220, 0], [0, 255, 255], [255, 60, 0]]
DROP = ("anchors", "ref", "ink", "ink_px", "ink_range", "ink_fade_px", "ink_m_uv", "highlight_map", "strands")


def fixed(mat, name, colour):
    m = copy.deepcopy(mat)
    m["name"] = name
    h = m.setdefault("extras", {}).setdefault("slop", {}).setdefault("hair", {})
    for k in DROP:
        h.pop(k, None)
    h.update(palette="fixed", shade=colour, mid=colour, light=colour, highlight=colour)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("with_path")
    ap.add_argument("out")
    ap.add_argument("--part", action="append", default=[], help="NAME=WITHOUT.glb")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    j, binary = read_glb(a.with_path)
    binary = bytearray(binary)
    hair = next(i for i, m in enumerate(j["materials"]) if "_HAIR" in m.get("name", ""))
    if a.all:
        j["materials"][hair] = fixed(j["materials"][hair], j["materials"][hair]["name"], COLOURS[0])
        write_glb(a.out, j, binary)
        print(f"part_id: all hair {COLOURS[0]} in {a.out}")
        return
    legend = {}
    for n, spec in enumerate(a.part):
        name, without = spec.split("=", 1)
        j0, b0 = read_glb(without)
        others = set()
        for m in j0["meshes"]:
            for p in m["primitives"]:
                others |= keys(accessor(j0, b0, p["attributes"]["POSITION"]).astype(np.float64))
        j["materials"].append(fixed(j["materials"][hair], f"ZZ_Part{n}_HAIR", COLOURS[n]))
        gid = len(j["materials"]) - 1
        moved = 0
        for m in j["meshes"]:
            add = []
            for p in m["primitives"]:
                if p.get("material") != hair:
                    continue
                pos = accessor(j, binary, p["attributes"]["POSITION"]).astype(np.float64)
                mine_v = np.array([tuple(q) not in others for q in np.round(pos * 1e5).astype(np.int64)])
                idx = accessor(j, binary, p["indices"]).reshape(-1, 3).astype(np.uint32)
                mine = mine_v[idx].all(axis=1)
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
        legend[name] = dict(colour=COLOURS[n], triangles=moved)
    j["buffers"][0]["byteLength"] = len(binary)
    write_glb(a.out, j, binary)
    print("part_id:", legend)


if __name__ == "__main__":
    main()
