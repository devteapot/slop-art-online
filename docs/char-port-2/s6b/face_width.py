"""S6b's 3D face measure (reported; the acceptance is the 2D render's, face2d_measure.py): on each type file, seen
from the front (orthographic), the face's width at the cheek row (0.030 m under the irises' centres) over the eye
spacing (iris centre to iris centre), with the ears and without them.
- The width is where the level plane cuts the skin's triangles (not the vertices near it).
- The ears are left out as whole shells (measure3d.ear_triangles). The first version took vertices within 3 mm of the
  row and left out those weighing 0.5 or more on the ear bones; the ear's lower vertices weigh less, and counted as
  face.
- Known-answer test: measure3d_selftest.py.
    python3 face_width.py OUT.json DIR"""
import glob, json, os, sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent)]
import measure3d as M  # noqa: E402

CHEEK_DROP = 0.030


def measure(path):
    P, T, iris = M.face(path)
    eye, spacing = M.eyes(iris)
    h = eye - CHEEK_DROP
    face = T[~M.ear_triangles(P, T)]
    return dict(spacing_mm=round(spacing * 1000, 1), with_ears=round(M.width(P, T, h) / spacing, 3), ears_excluded=round(M.width(P, face, h) / spacing, 3))


if __name__ == "__main__":
    rows = {os.path.basename(f)[:-4]: measure(f) for f in sorted(glob.glob(os.path.join(sys.argv[2], "*.glb")))}
    json.dump(rows, open(sys.argv[1], "w"), indent=1)
    for t, r in rows.items():
        print(t, r)
