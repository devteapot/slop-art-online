#!/usr/bin/env python3
"""S2 skin patches against the drawing, relative to each body's own skin (char-port-2).

    python3 patches.py STILL.png:X0,Y0,X1,Y1,CHIN [...]   # front close-ups: the pupils' rough places, the chin's row

Three patches, placed the same way on the drawing (docs/char-live-1/face.png, its pupils and chin
from docs/char-live-3/eye-frame/landmarks.json) and on each still, in units of the pupils' spacing
(across) and the pupil-to-chin span (down), from the pupils' midpoint:

- **base:** between the eyes at the pupils' height (lit skin, nothing painted);
- **cheek:** under the right pupil, 0.30 of the span down (the blush);
- **shade:** on the midline, 0.07 of the span under the chin (the neck under the jaw).

A generated body has its own skin, so a drawing patch becomes a target relative to the body's
base: target = base x (drawing patch / drawing base), per channel in linear light. In a still the
pupils are the darkest 5x5 mean within 40 px of the rough places; the chin's row is given (the
last skin row above the jaw line, read off the midline's luminance).
"""
import json
import sys
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
PLACES = {'base': (0.0, 0.0), 'cheek': (0.5, 0.30), 'shade': (0.0, None)}
SHADE_BELOW_CHIN = 0.07
HALF = 3  # 7 x 7 median


def lum(a):
    return a @ np.array([0.2126, 0.7152, 0.0722])


def lin(c):
    c = np.asarray(c, float) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb(c):
    c = np.clip(c, 0, 1)
    return np.round(255 * np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)).astype(int)


def sample(a, pupils, chin):
    (x0, y0), (x1, y1) = pupils
    mx, my, dist = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0
    span = chin - my
    out = {}
    for name, (fx, fy) in PLACES.items():
        X = round(mx + fx * dist)
        Y = round(chin + SHADE_BELOW_CHIN * span) if fy is None else round(my + fy * span)
        out[name] = dict(at=[X, Y], rgb=np.median(a[Y - HALF:Y + HALF + 1, X - HALF:X + HALF + 1].reshape(-1, 3), axis=0).round().astype(int).tolist())
    return out


def drawing():
    land = json.loads((REPO/'docs/char-live-3/eye-frame/landmarks.json').read_text())['drawing_front']
    a = np.asarray(Image.open(REPO/'docs/char-live-1/face.png').convert('RGB')).astype(float)
    return sample(a, [e['pupil'] for e in land['eyes']], land['chin'])


def find(a, guesses):
    L = lum(a)
    pupils = []
    for x, y in guesses:
        win = L[y - 40:y + 41, x - 40:x + 41]
        sm = sliding_window_view(win, (5, 5)).mean((2, 3))
        dy, dx = np.unravel_index(np.argmin(sm), sm.shape)
        pupils.append((x - 40 + dx + 2, y - 40 + dy + 2))
    return pupils


def measure(path, guesses, chin, draw):
    a = np.asarray(Image.open(path).convert('RGB')).astype(float)
    pupils = find(a, guesses)
    got = sample(a, pupils, chin)
    base = lin(got['base']['rgb'])
    for name, g in got.items():
        target = srgb(base * lin(draw[name]['rgb']) / lin(draw['base']['rgb']))
        g['target'] = target.tolist()
        g['delta'] = (np.array(g['rgb']) - target).tolist()
    return dict(file=str(path), pupils=[list(map(int, p)) for p in pupils], chin=int(chin), patches=got)


if __name__ == '__main__':
    draw = drawing()
    rows = []
    for arg in sys.argv[1:]:
        f, g = arg.rsplit(':', 1)
        x0, y0, x1, y1, chin = map(int, g.split(','))
        rows.append(measure(f, ((x0, y0), (x1, y1)), chin, draw))
    print(json.dumps(dict(drawing=draw, stills=rows), indent=1))
