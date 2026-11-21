"""S6b: the ears against Cora's drawing. On each type file (front, orthographic), each ear's shell (the face skin's
small connected pieces, welded by position) and its top, bottom and height, relative to eye-to-chin: the eye line is
the irises' centre height, the chin the lowest front vertex. The drawing: height 0.62, bottom 0.47 under the eye line,
top 0.15 over it.
    python3 ears.py OUT.json DIR [DIR ...]"""
import glob, json, os, sys
import numpy as np
sys.path[:0] = ["living/tools"]
from merge_primitives import read_glb, read_accessor  # noqa: E402


def arr(j, b, i):
    return np.array(read_accessor(j, b, i)[0], float)


def ears(path):
    j, b = read_glb(path)
    node = next(n for n in j["nodes"] if n.get("name") == "Face" and "mesh" in n)
    prims = {j["materials"][p["material"]]["name"]: p for p in j["meshes"][node["mesh"]]["primitives"]}
    p = prims["M00_000_00_Face_00_SKIN"]
    P = arr(j, b, p["attributes"]["POSITION"]).reshape(-1, 3)
    T = arr(j, b, p["indices"]).reshape(-1, 3).astype(int)
    I = arr(j, b, prims["M00_000_00_EyeIris_00_EYE"]["attributes"]["POSITION"]).reshape(-1, 3)
    at = np.unique(np.round(P * 1e6).astype(np.int64), axis=0, return_inverse=True)[1].ravel()
    par = list(range(at.max() + 1))

    def root(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for t in at[T]:
        a = root(t[0])
        for v in t[1:]:
            par[root(v)] = a
    comp = np.array([root(a) for a in at])
    ids, counts = np.unique(comp, return_counts=True)
    shells = [ids[k] for k in np.argsort(-counts)[1:3]]
    eye = I[:, 1].mean()
    front = P[(np.abs(P[:, 0]) < 0.006) & (P[:, 2] < I[:, 2].mean())]
    E = eye - front[:, 1].min()
    out = {}
    for s in shells:
        Q = P[comp == s]
        side = "L" if Q[:, 0].mean() > 0 else "R"
        out[side] = dict(top=round((Q[:, 1].max() - eye) / E, 3), bottom=round((eye - Q[:, 1].min()) / E, 3), height=round((Q[:, 1].max() - Q[:, 1].min()) / E, 3))
    return dict(eye_to_chin_mm=round(E * 1000, 1), **out)


res = {}
for d in sys.argv[2:]:
    for f in sorted(glob.glob(os.path.join(d, "*.glb"))):
        res.setdefault(d, {})[os.path.basename(f)[:-4]] = r = ears(f)
        print(d.split("/")[-2], os.path.basename(f)[:-4], r, flush=True)
json.dump(res, open(sys.argv[1], "w"), indent=1)
