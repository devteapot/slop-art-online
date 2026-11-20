#!/usr/bin/env python3
"""Measure each ink stroke's drawn width in the Bevy portraits, against the drawing.

    python3 widths.py view/own-cora-live.glb OUT --binary BIN

Renders the file and one copy per inked material with that ink pure blue, at the
front and three-quarter portraits (the calibration frame's camera, 1600 x 900, the frames the
eye-frame landmarks were measured on). A stroke's coverage per pixel is the luminance its own
ink takes away, over what a fully covered pixel takes away (the median of its darkest tenth);
its width at a station is the coverage summed down the image column through the stroke's
strongest run (lid, lower lid, brow, nostrils, the jaw at the chin) or along the row (the jaw's
sides). Widths are reported in native pixels, as a fraction of the eye's canthus-to-canthus
width, and at the 440 px registration (48 px eye front, 50 px three-quarter), as the drawing's
measurements are (eye-frame/README.md).
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(REPO/'living/tools/characters'), str(REPO/'living/tools'), str(HERE)]
import calibrate as C  # noqa: E402
from ink_calibrate import copy_with, remove  # noqa: E402

SHOTS = {'front': '0:8:0.36:0.88', 'three-quarter': '-35:8:0.36:0.88'}
REF_EYE = {'front': 48., 'three-quarter': 50.}
# Native landmarks of the measured eye in each portrait (eye-frame/landmarks.json, fit_*),
# the eye the drawing's strokes were traced on: screen-right in front, screen-left at -35.
LAND = json.loads((HERE.parent/'eye-frame/landmarks.json').read_text())
EYES = {'front': LAND['fit_front']['eyes'][1], 'three-quarter': LAND['fit_three_quarter']['eyes'][0]}
DRAWN = {'front': dict(lid_outer_third=5.3, lid_max=5.7, wing_mid=2.6, brow_max=7.7, lower_max=1.9, jaw_max=1.7, nostril_max=1.6),
         'three-quarter': dict(lid_outer_third=5.8, lid_max=7.1, wing_mid=3.6, brow_max=8.0, lower_max=2.1, jaw_max=1.7, nostril_max=1.3)}


def lum(a):
    return a @ np.array([.2126, .7152, .0722])


def render(glb, binary, out):
    got = C.run_frame(glb, binary, out, list(SHOTS.values()))
    return {k: np.asarray(Image.open(got[v]).convert('RGB'), float) for k, v in SHOTS.items()}


def coverage(with_ink, blue):
    d = np.linalg.norm(blue - with_ink, axis=-1)
    m = d > 6
    if not m.any():
        return np.zeros(d.shape)
    full = np.median(np.sort(d[m])[-max(1, m.sum() // 10):])
    return np.clip(d / full, 0, 1) * m


def across(c, x, y, r=7):
    """Coverage summed across the stroke through (x, y), along its local normal."""
    ys, xs = np.nonzero(c[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1] > .5)
    if len(xs) < 3:
        return 0.
    P = np.stack([xs, ys], 1).astype(float)
    P -= P.mean(0)
    w, v = np.linalg.eigh(P.T @ P)
    n = v[:, 0]
    t = np.arange(-18, 18.001, .25)
    qx, qy = x + t * n[0], y + t * n[1]
    x0, y0 = np.floor(qx).astype(int), np.floor(qy).astype(int)
    fx, fy = qx - x0, qy - y0
    ok = (x0 >= 0) & (y0 >= 0) & (x0 < c.shape[1] - 1) & (y0 < c.shape[0] - 1)
    x0, y0, fx, fy = x0[ok], y0[ok], fx[ok], fy[ok]
    val = (c[y0, x0] * (1 - fx) * (1 - fy) + c[y0, x0 + 1] * fx * (1 - fy)
           + c[y0 + 1, x0] * (1 - fx) * fy + c[y0 + 1, x0 + 1] * fx * fy)
    # Only the run through the centre.
    mid = np.argmin(np.abs(t[ok]))
    a = b = mid
    while a > 0 and val[a - 1] > .03:
        a -= 1
    while b < len(val) - 1 and val[b + 1] > .03:
        b += 1
    return float(val[a:b + 1].sum() * .25)


def run_sum(col):
    """Coverage summed over the contiguous run (coverage > 0.05) holding the column's peak."""
    if col.max() <= .05:
        return 0., None
    i = int(np.argmax(col))
    a = b = i
    while a > 0 and col[a - 1] > .05:
        a -= 1
    while b < len(col) - 1 and col[b + 1] > .05:
        b += 1
    return float(col[a:b + 1].sum()), (a, b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glb')
    ap.add_argument('out')
    ap.add_argument('--binary', required=True)
    a = ap.parse_args()
    out = Path(a.out)
    j, _ = C.read_glb(C.ASSETS/a.glb)
    inks = [m['name'] for m in j['materials'] if isinstance((m.get('extras', {}).get('slop') or {}).get('ink'), dict)]
    base = render(a.glb, a.binary, out/'base')
    cov = {}
    for name in inks:
        cp = copy_with(a.glb, '-w' + name.lower(), lambda m, ms, n=name: ms['ink'].__setitem__('color', [0, 0, 255]) if m['name'] == n else None)
        try:
            img = render(cp, a.binary, out/('no-' + name))
        finally:
            remove(cp)
        cov[name] = {k: coverage(base[k], img[k]) for k in SHOTS}
    report = {}
    for view in SHOTS:
        eye = EYES[view]
        inner, outer = eye['inner_outer_x']
        px, py = eye['pupil']
        W = abs(outer - inner)
        sgn = 1 if outer > inner else -1
        k440 = REF_EYE[view] / W
        lid = cov['Cora_LidInk_EYE'][view]
        above = lid.copy()
        above[py:] = 0
        below = lid.copy()
        below[:py] = 0
        r = {}

        def station(t, mask=above):
            x = int(round(inner + sgn * t * W))
            s, run = run_sum(mask[:, x])
            if run is None:
                return dict(t=t, x=x, px=0., eye=0., px440=0.)
            y = int(round((run[0] + run[1]) / 2))
            s = across(mask, x, y)
            return dict(t=t, x=x, y=y, px=round(s, 2), eye=round(s / W, 4), px440=round(s * k440, 2))
        r['lid'] = {f't{t:g}': station(t) for t in (.05, 1 / 6, .5, 5 / 6, 1.0, 1.1, 1.2)}
        ts = np.linspace(0, 1.15, 47)
        prof = [station(t) for t in ts]
        best = max(prof, key=lambda e: e['px'])
        r['lid']['max'] = best
        lows = [station(t, below) for t in ts if .35 <= t <= .95]
        r['lower lid max'] = max(lows, key=lambda e: e['px'])
        for name, key, region in (('Cora_BrowInk_EYE', 'brow', (py - 3 * W // 2, py)),
                                  ('Cora_NoseInk_SKIN', 'nostrils', (py, py + 2 * W)),
                                  ('Cora_JawInk_SKIN', 'jaw', (py, py + 4 * W))):
            c = cov[name][view].copy()
            c[:max(0, region[0])] = 0
            c[region[1]:] = 0
            if key == 'brow':
                # The brow over the traced eye only.
                lo, hi = min(inner, outer) - int(.35 * W), max(inner, outer) + int(.35 * W)
                c[:, :max(0, lo)] = 0
                c[:, hi:] = 0
            xs = np.flatnonzero(c.max(0) > .3)
            if not len(xs):
                r[key] = None
                continue
            sums = {}
            for x in range(xs.min(), xs.max() + 1):
                _, run = run_sum(c[:, x])
                sums[x] = across(c, x, int(round((run[0] + run[1]) / 2))) if run else 0.
            xm = max(sums, key=sums.get)
            ent = dict(max=dict(x=xm, px=round(sums[xm], 2), eye=round(sums[xm] / W, 4), px440=round(sums[xm] * k440, 2)))
            if key == 'brow':
                for f in (.06, .94):
                    x = int(round(xs.min() + f * (xs.max() - xs.min())))
                    ent[f'at {f:g} of its span'] = dict(x=x, px=round(sums[x], 2), eye=round(sums[x] / W, 4), px440=round(sums[x] * k440, 2))
            if key == 'jaw':
                # Its ends run steeply: measure across the row there.
                xc = int(round((xs.min() + xs.max()) / 2))
                ent['chin'] = dict(x=xc, px=round(sums[xc], 2), eye=round(sums[xc] / W, 4), px440=round(sums[xc] * k440, 2))
                for f in (.04, .96):
                    x = int(round(xs.min() + f * (xs.max() - xs.min())))
                    ent[f'end at {f:g}'] = dict(x=x, px=round(sums[x], 2), eye=round(sums[x] / W, 4), px440=round(sums[x] * k440, 2))
            r[key] = ent
        r['drawn_440'] = DRAWN[view]
        report[view] = r
        for name in inks:
            Image.fromarray(np.uint8(255 - 255 * cov[name][view])).save(out/f'coverage-{view}-{name}.png')
    (out/'widths.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({v: {k: (x.get('max', x) if isinstance(x, dict) and 'max' in x else x) for k, x in r.items()} for v, r in report.items()}, indent=1))


if __name__ == '__main__':
    main()
