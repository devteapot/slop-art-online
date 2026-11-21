#!/usr/bin/env python3
"""The upper lid's visual weight against the drawing, at the 440 px registration.

    python3 lidweight.py [NAME=STILLS_DIR ...]

For the eye each drawing trace follows (screen-right in front, screen-left at three-quarter),
every image is resampled so the eye spans the reference width (48 px front, 50 px three-
quarter), then measured column by column over the outer two thirds of the eye (canthus-to-
canthus fraction t from 1/3 to 1):

- darkness D = (L_skin - L) / (L_skin - L_ink), from the column's skin (its 85th percentile of
  luminance on the lid, above the band) to full ink (the drawing's own darkest lid ink; in a
  render the black-ink floor, `--floor`, what black ink renders as there);
- band width: D summed over the dark run that meets the opening, in 440 px;
- mean darkness: D averaged over a fixed box from the opening's top up 0.16 eye widths, the
  lid band and its lashes, over the same columns.

Landmarks are eye-frame/landmarks.json's; renders use the calibration portraits.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LAND = json.loads((HERE.parent/'eye-frame/landmarks.json').read_text())
VIEWS = {'front': ('drawing_front', 'fit_front', 1, '00-clip-idle@0-0_8_0.36_0.88.png', 48.),
         'three-quarter': ('drawing_three_quarter', 'fit_three_quarter', 0, '10-clip-idle@0--35_8_0.36_0.88.png', 50.)}
FLOOR_L = 49.6      # luminance of black lid ink at the portrait (batch floor control, (67, 46, 35))


def lum(a):
    return a @ np.array([.2126, .7152, .0722])


def measure(img, eye, ref_w, ink_l):
    inner, outer = eye['inner_outer_x']
    top = eye['aperture_y'][0]
    W = abs(outer - inner)
    k = ref_w / W
    big = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    L = lum(np.asarray(big.convert('RGB'), float))
    sgn = 1 if outer > inner else -1
    xs = [round((inner + sgn * t * W) * k) for t in np.linspace(1 / 3, 1, 24)]
    y_top = round(top * k)
    widths, boxes = [], []
    for x in xs:
        col = L[y_top - round(.55 * ref_w):y_top + round(.08 * ref_w), x]
        skin = np.percentile(col, 85)
        D = np.clip((skin - col) / max(skin - ink_l, 1), 0, 1)
        # The dark run meeting the opening: from the darkest point near the opening, upward and
        # downward while D > 0.15.
        n = len(col)
        near = np.arange(n) >= n - round(.30 * ref_w)
        i = int(np.argmax(np.where(near, D, -1)))
        a = b = i
        while a > 0 and D[a - 1] > .15:
            a -= 1
        while b < n - 1 and D[b + 1] > .15:
            b += 1
        widths.append(float(D[a:b + 1].sum()))
        box = D[n - round(.08 * ref_w) - round(.16 * ref_w):n - round(.08 * ref_w) + 1]
        boxes.append(float(box.mean()))
    return dict(band_width_px440=dict(mean=round(float(np.mean(widths)), 2), at_5_6=round(widths[int(round((5 / 6 - 1 / 3) / (2 / 3) * 23))], 2),
                                      max=round(float(np.max(widths)), 2)),
                mean_darkness=round(float(np.mean(boxes)), 3))


def main(args):
    drawing = Image.open(REPO/'docs/char-live-1/face.png')
    arr = lum(np.asarray(drawing.convert('RGB'), float))
    out = {}
    for view, (dk, rk, ei, shot, ref_w) in VIEWS.items():
        de = LAND[dk]['eyes'][ei]
        inner, outer = de['inner_outer_x']
        # The drawing's own full ink: its darkest lid pixels over the measured columns.
        x0, x1 = sorted((inner, outer))
        ink = np.percentile(arr[de['aperture_y'][0] - 20:de['aperture_y'][0] + 4, x0:x1 + 1], 1)
        out.setdefault('drawing', {})[view] = measure(drawing, de, ref_w, ink)
        for name, d in (a.split('=', 1) for a in args):
            img = Image.open(Path(d)/shot)
            out.setdefault(name, {})[view] = measure(img, LAND[rk]['eyes'][ei], ref_w, FLOOR_L)
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main(sys.argv[1:])
