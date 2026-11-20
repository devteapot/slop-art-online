#!/usr/bin/env python3
"""Front-view face measures of a character GLB at the drawing's stations (char-port-2, S0/S1).

    python3 face_measure.py FILE.glb [FILE.glb ...]

Reads the face skin primitive (`…Face_00_SKIN`), the irises (`…EyeIris_00_EYE`) and the eye whites
(`…Eye_00_EYE`) at rest, in the file's own metres (the type's mesh; identity bones are not applied).

- **Stations:** Cora's front drawing samples cheek, jaw and chin at 0.208, 0.662 and 0.874 of the
  way from the pupils' height down to the chin (y 320, 414 and 458 between pupils at 277 and chin at
  484, docs/char-live-2/stage-2.md). The same fractions are used here, from the irises' centres to
  the chin (the face skin's lowest point within 5 mm of the midline, in front).
- **Width at a station:** twice the largest |x| where the face skin's triangles cross that height,
  on surface that faces the front (its triangle's normal within 80° of forward): the face's front
  outline, without the ears or the head's sides behind it.
- **Ratios** are divided by the pupil-to-chin span, as the drawing's: cheek 1.232, jaw 0.952,
  chin 0.483; chin/cheek 0.392, jaw/cheek 0.773.
- **Iris / eye:** each iris's width across x over the eye opening's width across x (the face
  skin's boundary loop round that eye), per eye; the drawing's is 0.49-0.51 in front.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'living/tools'))
from merge_primitives import read_glb, read_accessor  # noqa: E402

STATIONS = dict(cheek=0.208, jaw=0.662, chin=0.874)
DRAWING = dict(cheek=1.232, jaw=0.952, chin=0.483, chin_over_cheek=0.392, jaw_over_cheek=0.773, iris_over_eye=0.50)


def prims(path):
    doc, buf = read_glb(path)
    out = {}
    for m in doc['meshes']:
        for p in m['primitives']:
            name = doc['materials'][p['material']]['name']
            P = np.asarray(read_accessor(doc, buf, p['attributes']['POSITION'])[0], float).reshape(-1, 3)
            I = np.asarray(read_accessor(doc, buf, p['indices'])[0]).reshape(-1, 3)
            out.setdefault(name, []).append((P, I))
    return out


def measure(path):
    pr = prims(path)
    face = next(v for k, v in pr.items() if k.endswith('Face_00_SKIN'))
    P = np.vstack([a for a, _ in face])
    tris = np.vstack([b + sum(len(a) for a, _ in face[:k]) for k, (_, b) in enumerate(face)])
    iris = np.vstack([a for a, _ in next(v for k, v in pr.items() if k.endswith('EyeIris_00_EYE'))])
    white = np.vstack([a for a, _ in next(v for k, v in pr.items() if k.endswith('Eye_00_EYE'))])
    # glTF: +Y up; the face looks along +Z or -Z.
    fwd = 1.0 if P[:, 2].mean() < iris[:, 2].mean() else -1.0
    eye_y = iris[:, 1].mean()
    front_z = iris[:, 2].mean() * fwd - 0.025
    front = P[:, 2] * fwd > front_z
    mid = front & (np.abs(P[:, 0]) < 0.005)
    chin_y = P[mid, 1].min()
    span = eye_y - chin_y
    res = dict(file=str(path), pupil_to_chin_mm=round(span * 1000, 1))
    A, B, C = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    n = np.cross(B - A, C - A)
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
    faces_front = n[:, 2] * fwd > np.cos(np.radians(80))
    for name, f in STATIONS.items():
        y = eye_y - f * span
        xs = []
        for a, b in ((A, B), (B, C), (C, A)):
            d = b[:, 1] - a[:, 1]
            t = (y - a[:, 1]) / np.where(np.abs(d) < 1e-12, np.nan, d)
            ok = (t >= 0) & (t <= 1) & faces_front
            q = a[ok] + t[ok, None] * (b[ok] - a[ok])
            xs.append(np.abs(q[:, 0]))
        xs = np.concatenate(xs)
        res[name] = round(float(2 * xs.max() / span), 3) if len(xs) else None
    res['chin_over_cheek'] = round(res['chin'] / res['cheek'], 3)
    res['jaw_over_cheek'] = round(res['jaw'] / res['cheek'], 3)
    from collections import Counter
    count = Counter()
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            ka, kb = tuple(np.round(P[a], 5)), tuple(np.round(P[b], 5))
            count[(min(ka, kb), max(ka, kb))] += 1
    rim = np.array([q for e, c in count.items() if c == 1 for q in e])
    ratios = []
    for s in (-1, 1):
        ir = iris[iris[:, 0] * s > 0]
        near = rim[(rim[:, 0] * s > 0) & (np.abs(rim[:, 1] - ir[:, 1].mean()) < 0.012) & (np.abs(rim[:, 0] - ir[:, 0].mean()) < 0.03)]
        ratios.append(round(float(np.ptp(ir[:, 0]) / np.ptp(near[:, 0])), 3) if len(near) else None)
    res['iris_over_eye'] = ratios
    return res


if __name__ == '__main__':
    print(json.dumps(dict(drawing=DRAWING, files=[measure(Path(p)) for p in sys.argv[1:]]), indent=1))
