"""Replace the procedural atlas's red nose accent with one turned shade and a glint."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def smooth(a, b, values):
    t = np.clip((values-a)/(b-a), 0, 1)
    return t*t*(3-2*t)


def paint(path):
    original = np.asarray(Image.open(path).convert('RGB'))
    y, x = np.indices(original.shape[:2], dtype=float)
    u = (x+.5)/original.shape[1]
    v = (y+.5)/original.shape[0]
    # The cage tip projects at (.500, .713). Feather out the old central
    # bulb and its side dab into the adjacent unpainted generator skin.
    radius = ((u-.502)/.070)**2 + ((v-.722)/.055)**2
    coverage = 1-smooth(.59,1.,radius)
    skin = np.median(original[767:778,540:551], axis=(0,1))
    # The visible wing turns under the tip. A broad soft fill follows this
    # bend, with a thinner, softened lower edge and a tapered far end.
    s = (u-.484)/.043
    curve = .738 - .012*np.minimum(s*s, 2.0) + .004*s
    half_height = np.where(v>curve,.006,.010)
    shade = np.exp(-((v-curve)/half_height)**2) * np.exp(-s**4)
    dye = skin*(1-shade[...,None]*np.array([.38,.41,.42]))
    # One compact warm highlight, set above and to the lit side of the turn.
    glint = np.exp(-(((u-.502)/.011)**2 + ((v-.711+.08*(u-.502))/.0055)**2))
    dye += glint[...,None]*(np.array([255,236,211])-dye)
    result = original + coverage[...,None]*(dye-original)
    Image.fromarray(np.uint8(np.clip(result,0,255).round())).save(path)


if __name__=='__main__':
    paint(Path(sys.argv[1]))
