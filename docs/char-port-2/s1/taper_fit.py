#!/usr/bin/env python3
"""The lower face's front widths of a type's cage head for given jaw and chin tapers, without
Blender (char-port-2 S1). Measured as docs/char-port-2/s0/face_measure.py measures a GLB: widths
of front-facing skin at 0.662 (jaw) and 0.874 (chin) of the way from the eyes' height to the chin,
over that span; the drawing's are 0.952 and 0.483 (chin / jaw 0.507).

    python3 taper_fit.py TYPE [JAW_TAPER CHIN_TAPER ...]     # widths for each pair (0 0 first)
    python3 taper_fit.py --grid TYPE [TYPE ...]                # the pair that meets the drawing best
"""
import copy
import itertools
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO/'living/tools/blender'))
sys.path.insert(0, str(REPO/'living/tools/characters'))
import cage_head  # noqa: E402
import face_types  # noqa: E402
import person_params  # noqa: E402

STATIONS = dict(jaw=0.662, chin=0.874)
DRAWING = dict(jaw=0.952, chin=0.483)
LOOK = person_params.resolve(person_params.draw(dict(seed=1, sex='female', age=30)))['look']


def widths(t, jaw_taper, chin_taper):
    t = copy.deepcopy(t)
    t['jaw'].update(jaw_taper=jaw_taper, chin_taper=chin_taper)
    face = cage_head.CageFace(cage_head.CageHead(face_types.apply(t, {})), LOOK)
    m = face.mesh
    V = np.array(m.v)
    skin = [f for f, k in zip(m.f, m.fm) if k == 'face'][: len(face.skin_faces)]
    tris = np.array([[f[0], f[1], f[2]] for f in skin] + [[f[0], f[2], f[3]] for f in skin if len(f) == 4])
    eye_z = np.mean([V[r['first']: r['first'] + len(r['ring'])][:, 2].mean() for r in face.rings.values()])
    mid = (np.abs(V[:, 0]) < 0.005) & (V[:, 1] > np.median(V[:, 1]))
    chin_z = V[mid, 2].min()
    span = eye_z - chin_z
    A, B, C = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
    n = np.cross(B - A, C - A)
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
    front = n[:, 1] > np.cos(np.radians(80))
    out = {}
    for name, f in STATIONS.items():
        z = eye_z - f * span
        xs = []
        for a, b in ((A, B), (B, C), (C, A)):
            d = b[:, 2] - a[:, 2]
            s = (z - a[:, 2]) / np.where(np.abs(d) < 1e-12, np.nan, d)
            ok = (s >= 0) & (s <= 1) & front
            xs.append(np.abs((a[ok] + s[ok, None] * (b[ok] - a[ok]))[:, 0]))
        out[name] = float(2 * np.concatenate(xs).max() / span)
    out['chin_over_jaw'] = out['chin'] / out['jaw']
    return out


def miss(w):
    """How far from the drawing, in the drawing's own shape: chin over jaw, and the jaw's width."""
    return abs(w['chin_over_jaw'] - DRAWING['chin'] / DRAWING['jaw']) + 0.5 * abs(w['jaw'] - DRAWING['jaw'])


if __name__ == '__main__':
    types = face_types.load(raw=True)['types']
    if sys.argv[1] == '--grid':
        for tid in sys.argv[2:]:
            base = widths(types[tid], 0, 0)
            best = min(((miss(widths(types[tid], j, c)), j, c) for j, c in itertools.product(np.arange(-0.20, 0.051, 0.05), np.arange(-0.35, 0.01, 0.05))))
            w = widths(types[tid], best[1], best[2])
            print(json.dumps(dict(type=tid, untapered={k: round(v, 3) for k, v in base.items()}, best=dict(jaw_taper=round(best[1], 2), chin_taper=round(best[2], 2)), widths={k: round(v, 3) for k, v in w.items()})))
    else:
        tid, vals = sys.argv[1], [float(x) for x in sys.argv[2:]]
        for j, c in [(0.0, 0.0)] + list(zip(vals[::2], vals[1::2])):
            print(tid, j, c, {k: round(v, 3) for k, v in widths(types[tid], j, c).items()})
