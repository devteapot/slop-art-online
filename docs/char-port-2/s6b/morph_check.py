"""S6b: expressions intact. In Blender (mathutils' BVH): for each person file, the face's skin at rest and in each
expression at full weight, and the pairs of its triangles that cut through each other (pairs sharing a vertex
left out). Writes OUT.json: per file, per state, the count.
    blender -b --python-exit-code 1 -P morph_check.py -- OUT.json FILE.glb [FILE.glb ...]"""
import json
import sys

import numpy as np
from mathutils.bvhtree import BVHTree

sys.path[:0] = ["living/tools"]
from merge_primitives import read_glb, read_accessor  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
out, files = argv[0], argv[1:]


def arr(j, b, i):
    return np.array(read_accessor(j, b, i)[0], float)


def crossings(V, T):
    tree = BVHTree.FromPolygons(V.tolist(), T.tolist(), all_triangles=True)
    n = 0
    for a, c in tree.overlap(tree):
        if a < c and not (set(T[a]) & set(T[c])):
            n += 1
    return n


res = {}
for f in files:
    j, b = read_glb(f)
    node = next(n for n in j["nodes"] if n.get("name") == "Face" and "mesh" in n)
    mesh = j["meshes"][node["mesh"]]
    names = (mesh.get("extras") or {}).get("targetNames", [])
    for p in mesh["primitives"]:
        if not j["materials"][p["material"]]["name"].endswith("Face_00_SKIN"):
            continue
        P = arr(j, b, p["attributes"]["POSITION"]).reshape(-1, 3)
        T = arr(j, b, p["indices"]).reshape(-1, 3).astype(int)
        row = {"rest": crossings(P, T)}
        for k, t in enumerate(p.get("targets", [])):
            name = names[k] if k < len(names) else f"target{k}"
            row[name] = crossings(P + arr(j, b, t["POSITION"]).reshape(-1, 3), T)
        res[f.split("/")[-1]] = row
        print(f, {k: v for k, v in row.items() if v}, flush=True)
json.dump(res, open(out, "w"), indent=1)
