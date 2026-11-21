#!/usr/bin/env python3
"""S2 nostrils against the drawing, as char-live-3's noseweight.py measured Cora's, on any face.

    python3 nostrils.py STILL.png:PX0,PY0,PX1,PY1,CHIN [...]    # front close-ups: pupils and chin rows

The still is scaled so its pupil-to-chin span is the drawing's at the 440 px registration (207 px,
docs/char-live-3/eye-frame/landmarks.json). In a window under the nose (from 0.32 to 0.58 of the
span below the pupils, 0.22 of the span either side of the midline) each pixel's darkness runs
from 0 at the window's skin (its 85th percentile of luminance) to 1 at the renderer's black-ink
floor (luminance 49.6, char-live-3 lidweight.py). A nostril is the connected dark region (D > 0.5)
on each side of the midline; its area, box and centre are reported in 440 px against the
drawing's: area 16 / 15, box 8 x 5, 8.3 / 7.3 across from the midline.
"""
import json
import sys

import numpy as np
from PIL import Image

DRAWING_SPAN = 207.0
DRAWING = dict(area=[16, 15], box=[[8, 5], [8, 5]], across=[8.3, 7.3])
FLOOR_L = 49.6


def lum(a):
    return a @ np.array([0.2126, 0.7152, 0.0722])


def regions(mask):
    """Connected regions of a boolean mask (4-neighbour), largest first."""
    seen = np.zeros_like(mask, bool)
    out = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        stack, pix = [(y, x)], []
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            pix.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        out.append(np.array(pix))
    return sorted(out, key=len, reverse=True)


def measure(path, pupils, chin):
    img = Image.open(path).convert('RGB')
    my = (pupils[1] + pupils[3]) / 2
    mx = (pupils[0] + pupils[2]) / 2
    k = DRAWING_SPAN / (chin - my)
    img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    L = lum(np.asarray(img).astype(float))
    cx, top = mx * k, my * k
    y0, y1 = round(top + 0.32 * DRAWING_SPAN), round(top + 0.58 * DRAWING_SPAN)
    x0, x1 = round(cx - 0.22 * DRAWING_SPAN), round(cx + 0.22 * DRAWING_SPAN)
    win = L[y0:y1, x0:x1]
    skin = np.percentile(win, 85)
    D = np.clip((skin - win) / (skin - FLOOR_L), 0, 1)
    mid = cx - x0
    out = []
    for side in (-1, 1):
        half = (np.arange(win.shape[1])[None, :] - mid) * side > 1
        reg = regions((D > 0.5) & half)
        if not reg:
            out.append(None)
            continue
        r = reg[0]
        out.append(dict(area=int(len(r)), box=[int(np.ptp(r[:, 1]) + 1), int(np.ptp(r[:, 0]) + 1)],
                        across=round(float(abs(r[:, 1].mean() - mid)), 1), below_pupils=round(float(r[:, 0].mean() + y0 - top), 1),
                        core_D=round(float(np.median(D[r[:, 0], r[:, 1]])), 2)))
    return dict(file=str(path), scale=round(k, 3), nostrils=out)


if __name__ == '__main__':
    rows = []
    for arg in sys.argv[1:]:
        f, g = arg.rsplit(':', 1)
        v = list(map(int, g.split(',')))
        rows.append(measure(f, v[:4], v[4]))
    print(json.dumps(dict(drawing=DRAWING, stills=rows), indent=1))
