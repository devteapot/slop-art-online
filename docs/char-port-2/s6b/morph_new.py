"""S6b: the self-crossings an expression adds. In Blender (mathutils' BVH): for each person file, the face skin's
triangle pairs that cut through each other at full weight of each expression but not at rest (pairs sharing a
vertex's place left out), and where they are: near the ear root (within 45 mm of the segment from J_Id_Ear to
J_Id_Gonion) or elsewhere. Writes OUT.json: per file, per expression, the count, the count elsewhere, and
the rest count.
    blender -b --python-exit-code 1 -P morph_new.py -- OUT.json FILE.glb [FILE.glb ...]"""
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


def pairs(V, T, at):
    """Crossing pairs, neighbours by position: along a seam two vertices share a place, and triangles meeting
    there touch whatever the motion."""
    tree = BVHTree.FromPolygons(V.tolist(), T.tolist(), all_triangles=True)
    return {(a, c) for a, c in tree.overlap(tree) if a < c and not (set(at[T[a]]) & set(at[T[c]]))}


res = {}
for f in files:
    j, b = read_glb(f)
    node = next(n for n in j["nodes"] if n.get("name") == "Face" and "mesh" in n)
    mesh = j["meshes"][node["mesh"]]
    names = mesh["extras"]["targetNames"]
    sk = j["skins"][node["skin"]]
    M = arr(j, b, sk["inverseBindMatrices"]).reshape(-1, 4, 4)
    pos = {j["nodes"][k]["name"]: np.linalg.inv(M[i].T)[:3, 3] for i, k in enumerate(sk["joints"])}
    p = next(p for p in mesh["primitives"] if j["materials"][p["material"]]["name"].endswith("Face_00_SKIN"))
    P = arr(j, b, p["attributes"]["POSITION"]).reshape(-1, 3)
    T = arr(j, b, p["indices"]).reshape(-1, 3).astype(int)
    C = P[T].mean(1)
    at = np.unique(np.round(P * 1e6).astype(np.int64), axis=0, return_inverse=True)[1].ravel()

    def seg(q, a, c):
        t = np.clip(((q - a) @ (c - a)) / ((c - a) @ (c - a)), 0, 1)
        return np.linalg.norm(q - (a + t[:, None] * (c - a)[None]), axis=1)

    near = np.minimum(seg(C, pos["J_Id_Ear_R"], pos["J_Id_Gonion_R"]), seg(C, pos["J_Id_Ear_L"], pos["J_Id_Gonion_L"])) < 0.045
    rest = pairs(P, T, at)
    row = {"rest": len(rest)}
    for k, t in enumerate(p.get("targets", [])):
        new = pairs(P + arr(j, b, t["POSITION"]).reshape(-1, 3), T, at) - rest
        row[names[k]] = [len(new), sum(1 for a, c in new if not (near[a] or near[c]))]
    res[f.split("/")[-1]] = row
    print(f, {k: v for k, v in row.items() if k == "rest" or v[0]}, flush=True)
json.dump(res, open(out, "w"), indent=1)
