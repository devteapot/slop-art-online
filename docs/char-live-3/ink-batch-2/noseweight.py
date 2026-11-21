#!/usr/bin/env python3
"""The nostrils against the drawing at the 440 px registration (front portrait).

    python3 noseweight.py [NAME=STILLS_DIR ...]

Each image is registered as the review sheets are (face height and the pupils' midpoint), the
nose window resampled to the 440 px scale, and split into its two halves (one nostril each).
Darkness D = (L_skin - L) / (L_skin - L_ink), from the window's skin (90th percentile of
luminance) to full ink (the drawing's darkest pixel there; in a render, what black renders as).
Per nostril:

- `area_px`: pixels with D > 0.5, and the bounding box of that shape (`w`, `h`);
- `centre`: its centroid from the pupils' midpoint, in 440 px (x right, y down);
- `core_rgb`: the median colour where D > 0.6 (or of its darkest tenth);
- `softness`: the area with D > 0.15 over the area with D > 0.5 (1 is a hard edge);
- `below_tip`, `from_tip`: its centroid against its own nose's tip glint (the window's brightest
  point in its upper half), where the window is split. Cora's 3D nose sits higher under the
  eyes than the drawing's, so the tip-relative place is the one to compare.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent/'ink-batch'))
import sheet  # noqa: E402

WINDOW = (-60, 30, 60, 110)       # drawing pixels from the pupils' midpoint (front)
TO440 = 244 / 356
FLOOR_L = 49.6


def lum(a):
    return a @ np.array([.2126, .7152, .0722])


def measure(img, land, ink_l=None):
    v = sheet.VIEWS['front']
    ref = sheet.frame(v['drawing'])[0]
    c = np.asarray(sheet.crop(img, land, WINDOW, TO440, ref), float)
    L = lum(c)
    skin = np.percentile(L, 90)
    ink = np.percentile(L, .2) if ink_l is None else ink_l
    D = np.clip((skin - L) / max(skin - ink, 1), 0, 1)
    h, w = D.shape
    tip = np.unravel_index(np.argmax(L[:h // 2]), L[:h // 2].shape)
    out = []
    mid = int(tip[1])                     # split at the nose's own tip
    for half in (slice(0, mid), slice(mid, w)):
        d = D[:, half]
        m = d > .5
        if not m.any():
            out.append(None)
            continue
        ys, xs = np.nonzero(m)
        x0 = half.start
        cx, cy = xs.mean() + x0, ys.mean()
        core = c[:, half][d > .6] if (d > .6).sum() >= 3 else c[:, half][d >= np.percentile(d, 90)]
        out.append(dict(area_px=int(m.sum()), w=int(np.ptp(xs) + 1), h=int(np.ptp(ys) + 1),
                        centre=[round(cx - (-WINDOW[0]) * TO440, 1), round(cy - (-WINDOW[1]) * TO440, 1)],
                        below_tip=round(float(cy - tip[0]), 1), from_tip=round(float(cx - tip[1]), 1),
                        core_rgb=[int(x) for x in np.median(core, 0)],
                        softness=round(float((d > .15).sum() / max(m.sum(), 1)), 2)))
    return out


def main(args):
    v = sheet.VIEWS['front']
    res = {'drawing': measure(Image.open(sheet.DRAWING).convert('RGB'), v['drawing'])}
    for name, d in (a.split('=', 1) for a in args):
        res[name] = measure(Image.open(Path(d)/v['shot']).convert('RGB'), v['render'], FLOOR_L)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main(sys.argv[1:])
