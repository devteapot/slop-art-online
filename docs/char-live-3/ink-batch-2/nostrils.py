#!/usr/bin/env python3
"""Paint the two nostrils into the skin atlas as soft filled crescents.

    python3 nostrils.py ATLAS.png NOSTRILS.json NOSE_TEXELS.npz

NOSTRILS.json holds each drawn nostril's centreline and half-widths in the front-view design
plane (metres; the drawing's nostril traces through the pupil similarity, half-widths x `gain`),
`soft_m` (the soft edge, each side of the drawn edge), `ratio` (the multiply that takes the atlas
skin to the nostril's value at full cover, per channel, linear 0-1 of the 8-bit values), and
`cap` (an optional lighter fill of the crescent's inside, 0 for none). NOSE_TEXELS.npz maps atlas
texels (iy, ix) to the design point (x, z) they show (the journal block rasterises it from the
face mesh), so the shapes are measured on the face, not in the atlas's own stretched layout.
Reads only the atlas it paints. Generalises: the shapes, softness and value are parameters.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def polyline_distance(Q, pts, hw):
    """Distance of each point to a polyline and the interpolated half-width there."""
    A, B = pts[:-1], pts[1:]
    d = B - A
    ll = np.maximum((d * d).sum(1), 1e-18)
    t = np.clip(((Q[:, None, :] - A[None]) * d[None]).sum(-1) / ll[None], 0, 1)
    X = A[None] + t[..., None] * d[None]
    dist = np.linalg.norm(Q[:, None, :] - X, axis=-1)
    i = dist.argmin(1)
    r = np.arange(len(Q))
    w = hw[i] + t[r, i] * (hw[i + 1] - hw[i])
    return dist[r, i], w


def inside(Q, poly):
    """Even-odd test of points against a closed polygon."""
    x, y = Q[:, 0], Q[:, 1]
    res = np.zeros(len(Q), bool)
    n = len(poly)
    for k in range(n):
        (x1, y1), (x2, y2) = poly[k], poly[(k + 1) % n]
        cross = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / np.where(y2 == y1, 1e-18, y2 - y1) + x1)
        res ^= cross
    return res


def main(atlas_path, params_path, texels_path):
    p = json.loads(Path(params_path).read_text())
    T = np.load(texels_path)
    img = np.asarray(Image.open(atlas_path).convert('RGB'), float)
    Q = np.stack([T['x'], T['z']], 1)
    cover = np.zeros(len(Q))
    for st in p['strokes']:
        pts, hw = np.array(st['pts']), np.array(st['hw'])
        d, w = polyline_distance(Q, pts, hw)
        line = np.clip((w + p['soft_m'] - d) / (2 * p['soft_m']), 0, 1) * (w > 0)
        cover = np.maximum(cover, line)
        if p['cap'] > 0:
            cover = np.maximum(cover, p['cap'] * inside(Q, pts))
    cover = cover * cover * (3 - 2 * cover)
    iy, ix = T['iy'], T['ix']
    ratio = np.array(p['ratio'])
    px = img[iy, ix]
    img[iy, ix] = px * (1 - cover[:, None] * (1 - ratio))
    Image.fromarray(np.uint8(np.clip(img, 0, 255).round())).save(atlas_path)
    print(f'nostrils: {int((cover > 0).sum())} texels painted, {int((cover > .99).sum())} fully')


if __name__ == '__main__':
    main(*sys.argv[1:4])
