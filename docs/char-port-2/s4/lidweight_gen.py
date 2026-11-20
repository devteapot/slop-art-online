#!/usr/bin/env python3
"""The upper lid's weight on a generated face, as char-live-3's lidweight.py measures Cora's,
with the landmarks found in the still instead of placed by hand.

    python3 lidweight_gen.py STILL.png:PX,PY [...]     # a front close-up, and one pupil's rough place

**The eye:** in a window round the pupil, the eye's inside is every pixel that is neither skin
(warm, R - B over 30, luminance over 150, saturation under 0.46: an orange iris is over 0.5) nor
ink (warm and darker, or near black and not blue or green): the white and the iris (the pupil, as
dark as ink, is a hole, which changes neither the canthi nor the opening's top). The canthi are the inside's
leftmost and rightmost columns, and the opening's top in a column is its topmost inside pixel.

**The measure** is lidweight.py's, at its scale: the image is resampled so the eye spans 48 px,
the drawing's eye at the 440 px registration (char-live-3 eye-frame), and each of 24 columns over
the outer two thirds (canthus-to-canthus 1/3 to 1) is read upward from the opening's top:
- darkness D = (L_skin - L) / (L_skin - L_ink), from the column's skin (its 85th percentile above
  the band) to the black-ink floor (luminance 49.6, lidweight.py's);
- **band width:** D summed over the dark run that meets the opening, in 440 px;
- **mean darkness:** D averaged over a box from the opening's top up 0.16 eye widths.

The drawing's lid (Cora's eye, front): band 7.3 px mean, 6.7 px at five-sixths, 9.2 widest;
darkness 0.59 (char-live-3 ink-batch-2/lidweight.json).
"""
import json
import sys

import numpy as np
from PIL import Image

REF_EYE = 48.0
FLOOR_L = 49.6
DRAWING = dict(band_mean=7.3, band_56=6.7, band_max=9.2, darkness=0.59)


def lum(a):
    return a @ np.array([0.2126, 0.7152, 0.0722])


def eye_box(a, px, py, half=(70, 45)):
    x0, y0 = px - half[0], py - half[1]
    win = a[y0:py + half[1], x0:px + half[0]]
    L = lum(win)
    r, g, b = win[..., 0], win[..., 1], win[..., 2]
    warm = (r > g + 4) & (g > b)
    sat = (win.max(-1) - win.min(-1)) / np.maximum(win.max(-1), 1)
    skin = warm & (r - b > 30) & (L > 150) & (sat < 0.46)
    tinted = (b > r + 10) | (g > r + 6)  # a blue or green iris's darks
    ink = (warm & (L < 150) & (sat < 0.45)) | ((L < 70) & ~tinted)
    inside = ~skin & ~ink
    # Keep the region connected to the pupil.
    cy, cx = py - y0, px - x0
    keep = np.zeros_like(inside)
    iy, ix = np.nonzero(inside)
    if not len(iy):
        return keep, x0, y0
    k = int(np.argmin((iy - cy) ** 2 + (ix - cx) ** 2))
    stack = [(int(iy[k]), int(ix[k]))]
    while stack:
        y, x = stack.pop()
        if 0 <= y < keep.shape[0] and 0 <= x < keep.shape[1] and inside[y, x] and not keep[y, x]:
            keep[y, x] = True
            stack += [(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)]
    return keep, x0, y0


def measure(path, px, py):
    img = Image.open(path).convert('RGB')
    a = np.asarray(img).astype(float)
    keep, x0, y0 = eye_box(a, px, py)
    cols = np.nonzero(keep.any(0))[0]
    if len(cols) < 10:
        raise SystemExit(f'lidweight_gen: no eye found round ({px}, {py}) in {path}')
    inner_x, outer_x = (cols[-1], cols[0]) if px < a.shape[1] / 2 else (cols[0], cols[-1])  # the outer canthus is the side away from the midline
    W = abs(outer_x - inner_x)
    k = REF_EYE / W
    big = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    L = lum(np.asarray(big.convert('RGB'), float))
    sgn = 1 if outer_x > inner_x else -1
    widths, boxes = [], []
    for t in np.linspace(1 / 3, 1, 24):
        xs = inner_x + sgn * t * W
        xi = int(round(xs))
        col = keep[:, min(max(xi, 0), keep.shape[1] - 1)]
        if not col.any():
            continue
        top = (np.nonzero(col)[0][0] + y0) * k
        X = int(round((xs + x0) * k))
        c = L[:int(top) + 1, X][::-1]  # upward from the opening's top
        if len(c) < 30:
            continue
        span = int(0.16 * REF_EYE)
        skin = np.percentile(c[span:span + 25], 85)
        D = np.clip((skin - c) / max(skin - FLOOR_L, 1e-6), 0, 1)
        run, started = 0.0, False
        for d in D[: span * 2]:
            if d > 0.5:
                started = True
                run += d
            elif started:
                break
            else:
                run += d * 0  # the opening's antialiased edge before the band
        widths.append(run)
        boxes.append(float(D[:span].mean()))
    w = np.array(widths)
    return dict(file=str(path), eye_px=int(W), canthi_x=[int(inner_x + x0), int(outer_x + x0)],
                band_mean=round(float(w.mean()), 2), band_56=round(float(np.interp(5 / 6, np.linspace(1 / 3, 1, len(w)), w)), 2),
                band_max=round(float(w.max()), 2), darkness=round(float(np.mean(boxes)), 3))


if __name__ == '__main__':
    out = []
    for arg in sys.argv[1:]:
        f, g = arg.rsplit(':', 1)
        x, y = map(int, g.split(','))
        out.append(measure(f, x, y))
    print(json.dumps(dict(drawing=DRAWING, stills=out), indent=1))
