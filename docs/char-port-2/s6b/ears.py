"""S6b: the ears against Cora's drawing. On each type file (front, orthographic), each ear's shell
(measure3d.ear_triangles) and its top, bottom and height, relative to eye-to-chin: the eye line is the irises' centre
height, the chin measure3d.chin. The drawing: height 0.62, bottom 0.47 under the eye line, top 0.15 over it.
Known-answer test: measure3d_selftest.py.
    python3 ears.py OUT.json DIR [DIR ...]"""
import glob, json, os, sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent)]
import measure3d as M  # noqa: E402


def measure(path):
    P, T, iris = M.face(path)
    eye, _ = M.eyes(iris)
    E = eye - M.chin(P, iris)
    out = {}
    ear = T[M.ear_triangles(P, T)]
    for side, sel in (("L", P[ear[:, 0], 0] > 0), ("R", P[ear[:, 0], 0] < 0)):
        Q = P[np.unique(ear[sel])]
        out[side] = dict(top=round((Q[:, 1].max() - eye) / E, 3), bottom=round((eye - Q[:, 1].min()) / E, 3), height=round((Q[:, 1].max() - Q[:, 1].min()) / E, 3))
    return dict(eye_to_chin_mm=round(E * 1000, 1), **out)


if __name__ == "__main__":
    res = {}
    for d in sys.argv[2:]:
        for f in sorted(glob.glob(os.path.join(d, "*.glb"))):
            res.setdefault(d, {})[os.path.basename(f)[:-4]] = r = measure(f)
            print(os.path.basename(f)[:-4], r, flush=True)
    json.dump(res, open(sys.argv[1], "w"), indent=1)
