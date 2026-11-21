"""S6b's measure: on each type file, seen from the front (orthographic), the face's width at the cheek row (0.030 m
under the irises' centres) over the eye spacing (iris centre to iris centre), with the ears and without them.
- The width is where the level plane cuts the skin's triangles (not the vertices near it).
- The ears are left out as whole shells: the face skin's two small connected pieces, welded by position. (The first
  version took vertices within 3 mm of the row and left out those weighing 0.5 or more on the ear bones; once the
  ears reached the cheek row, their lower vertices, weighing less, counted as face.)
    python3 face_width.py OUT.json DIR"""
import glob, json, os, sys
import numpy as np
sys.path[:0] = ["living/tools"]
from merge_primitives import read_glb, read_accessor  # noqa: E402


def arr(j, b, i):
    return np.array(read_accessor(j, b, i)[0], float)


def shells(P, T):
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
    return comp, set(ids[np.argsort(-counts)[1:3]])


def width(P, T, h):
    xs = []
    for e0, e1 in ((0, 1), (1, 2), (2, 0)):
        A, B = P[T[:, e0]], P[T[:, e1]]
        s = (A[:, 1] - h) * (B[:, 1] - h) <= 0
        d = B[s, 1] - A[s, 1]
        t = (h - A[s, 1]) / np.where(np.abs(d) < 1e-12, 1e-12, d)
        xs.append(A[s, 0] + t * (B[s, 0] - A[s, 0]))
    xs = np.concatenate(xs)
    return xs.max() - xs.min()


rows = {}
for f in sorted(glob.glob(os.path.join(sys.argv[2], "*.glb"))):
    j, b = read_glb(f)
    node = next(n for n in j["nodes"] if n.get("name") == "Face" and "mesh" in n)
    pr = {j["materials"][p["material"]]["name"]: p for p in j["meshes"][node["mesh"]]["primitives"]}
    p = pr["M00_000_00_Face_00_SKIN"]
    P = arr(j, b, p["attributes"]["POSITION"]).reshape(-1, 3)
    T = arr(j, b, p["indices"]).reshape(-1, 3).astype(int)
    iris = arr(j, b, pr["M00_000_00_EyeIris_00_EYE"]["attributes"]["POSITION"]).reshape(-1, 3)
    comp, ears = shells(P, T)
    face = T[~np.isin(comp[T[:, 0]], list(ears))]
    spacing = abs(iris[iris[:, 0] > 0, 0].mean() - iris[iris[:, 0] < 0, 0].mean())
    h = iris[:, 1].mean() - 0.030
    rows[os.path.basename(f)[:-4]] = dict(spacing_mm=round(spacing * 1000, 1), with_ears=round(width(P, T, h) / spacing, 3), ears_excluded=round(width(P, face, h) / spacing, 3))
json.dump(rows, open(sys.argv[1], "w"), indent=1)
for t, r in rows.items():
    print(t, r)
