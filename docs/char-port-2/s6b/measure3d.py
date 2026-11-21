"""S6b's 3D measures' shared parts (face_width.py, jaw.py, ears.py): a type file's face skin and irises, the ears as
the skin's two small connected pieces, the chin, and a level plane's cut through the skin. Each tool's known-answer
test is measure3d_selftest.py.

The file's frame: y up, the face toward -z; lengths in metres."""
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "living/tools")]
from merge_primitives import read_glb, read_accessor  # noqa: E402

SKIN, IRIS = "M00_000_00_Face_00_SKIN", "M00_000_00_EyeIris_00_EYE"


def arr(j, b, i):
    return np.array(read_accessor(j, b, i)[0], float)


def face(path):
    """(P, T, iris): the face skin's positions and triangles, and the irises' positions."""
    j, b = read_glb(path)
    node = next(n for n in j["nodes"] if n.get("name") == "Face" and "mesh" in n)
    pr = {j["materials"][p["material"]]["name"]: p for p in j["meshes"][node["mesh"]]["primitives"]}
    p = pr[SKIN]
    P = arr(j, b, p["attributes"]["POSITION"]).reshape(-1, 3)
    T = arr(j, b, p["indices"]).reshape(-1, 3).astype(int)
    return P, T, arr(j, b, pr[IRIS]["attributes"]["POSITION"]).reshape(-1, 3)


def ear_triangles(P, T):
    """Which triangles are the ears': the skin's second and third largest pieces, joined by shared places (to 1 µm)."""
    at = np.unique(np.round(P * 1e6).astype(np.int64), axis=0, return_inverse=True)[1].ravel()
    par = list(range(at.max() + 1))

    def root(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for t in at[T]:
        r = root(t[0])
        for v in t[1:]:
            par[root(v)] = r
    comp = np.array([root(a) for a in at[T[:, 0]]])
    ids, counts = np.unique(comp, return_counts=True)
    return np.isin(comp, ids[np.argsort(-counts)[1:3]])


def eyes(iris):
    """(eye line height, eye spacing): the irises' mean height, and their centres apart across."""
    return iris[:, 1].mean(), abs(iris[iris[:, 0] > 0, 0].mean() - iris[iris[:, 0] < 0, 0].mean())


def chin(P, iris):
    """The chin: the lowest skin within 6 mm of the midline, in front of the irises. It needs the irises behind the
    face's front, as the generator's are (in their sockets); a face whose irises stood in front would find its chin
    at the nose."""
    return P[(np.abs(P[:, 0]) < 0.006) & (P[:, 2] < iris[:, 2].mean()), 1].min()


def width(P, T, h):
    """The skin's width across (x) where the level plane y = h cuts its triangles."""
    xs = []
    for e0, e1 in ((0, 1), (1, 2), (2, 0)):
        A, B = P[T[:, e0]], P[T[:, e1]]
        s = (A[:, 1] - h) * (B[:, 1] - h) <= 0
        d = B[s, 1] - A[s, 1]
        t = (h - A[s, 1]) / np.where(np.abs(d) < 1e-12, 1e-12, d)
        xs.append(A[s, 0] + t * (B[s, 0] - A[s, 0]))
    xs = np.concatenate(xs)
    return xs.max() - xs.min()
