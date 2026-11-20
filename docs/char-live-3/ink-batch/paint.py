"""Nose paint for the ink batch: the accepted first fit's procedure (../nose/paint.py) with the
shade tightened into a band hugging the underside and the highlight cut to a tip glint.

    python3 paint.py ATLAS.png PARAMS.json

Reads only the generator's skin atlas. The parameters generalise: the tip landmark, the flank
curve, its half-heights above and below, the pigment and the glint's place and radii.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def smooth(a, b, values):
    t = np.clip((values - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def paint(path, p):
    original = np.asarray(Image.open(path).convert('RGB'))
    y, x = np.indices(original.shape[:2], dtype=float)
    u = (x + .5) / original.shape[1]
    v = (y + .5) / original.shape[0]
    # As the first fit: feather out the old central bulb into the adjacent generator skin.
    radius = ((u - .502) / .070) ** 2 + ((v - .722) / .055) ** 2
    coverage = 1 - smooth(.59, 1., radius)
    skin = np.median(original[767:778, 540:551], axis=(0, 1))
    s = (u - p['flank_u']) / p['flank_half_u']
    curve = p['curve_v'] - p['curve_bend'] * np.minimum(s * s, 2.0) + p['curve_tilt'] * s
    half_height = np.where(v > curve, p['below'], p['above'])
    shade = np.exp(-((v - curve) / half_height) ** 2) * np.exp(-s ** 4)
    dye = skin * (1 - shade[..., None] * np.array(p['pigment']))
    gu, gv = p['glint_uv']
    glint = np.exp(-(((u - gu) / p['glint_ru']) ** 2 + ((v - gv + .08 * (u - gu)) / p['glint_rv']) ** 2))
    dye += glint[..., None] * (np.array(p['glint_rgb']) - dye)
    result = original + coverage[..., None] * (dye - original)
    Image.fromarray(np.uint8(np.clip(result, 0, 255).round())).save(path)


if __name__ == '__main__':
    paint(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()))
