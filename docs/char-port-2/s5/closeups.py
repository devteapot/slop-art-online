#!/usr/bin/env python3
"""S5 close-ups: the lock lines at the 1 mm hair page, measured on a composed woman drawn by the
client with the hair's ink and without it (LIVING_GAME_COMPOSED_SLOP=noink:hair).

    python3 closeups.py OUT --binary BIN

**People:** `adult-f-b` in bob (auburn and black) and long (auburn), from a book of their own.
**Shots** (1600x900, 11:00, soft film, idle at 0 s): the calibration portrait (zoom 0.36), a
close-up (0.18), a closer one (0.10), each front (yaw 0) and three-quarter (yaw -35), pitch 8.

**Measured, per shot:** the ink is the pixels the line darkens by more than 8 levels of luminance
(ink against noink), on the hair (see `measure`: the client's clock blink is dropped). Each connected run of ink (8-neighbour) is a line piece; per piece its
length (the longer side of its box), and across it the width (ink pixels per row, or per column
for a line that runs across). Reported: pieces, pieces of 6 px or more, the median width and its
90th percentile, the darkest step (levels), and **gaps**: within a piece's long extent, the rows
(columns) without ink, a break in the line. Writes OUT/closeups.json and OUT/closeups.png (each
shot's crop round the hair, ink beside noink, and the ink mask).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO/'living/tools/characters')]
import look_lines  # noqa: E402
import palette  # noqa: E402

PEOPLE = [('bob-auburn', 'bob', 'auburn'), ('bob-black', 'bob', 'black'), ('long-auburn', 'long', 'auburn')]
SHOTS = [f'{y}:8:{z}:0.9' for z in (0.36, 0.18, 0.10) for y in (0, -35)]
FONT = '/usr/share/fonts/rsms-inter-fonts/Inter-Regular.ttf'


def lum(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def render(key, book, binary, out, mode):
    if not list(out.rglob('*.png')):  # an earlier run's stills are reused
        _draw(key, book, binary, out, mode)
    return {s: next(p for p in out.rglob('*.png') if p.name.endswith(s.replace(':', '_') + '.png')) for s in SHOTS}


def _draw(key, book, binary, out, mode):
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('LIVING_GAME_')}
    env.update(LIVING_GAME_VIEW=f'look:{key}', LIVING_GAME_LOOK_BOOK=str(book), LIVING_GAME_VIEW_SHOTS=','.join(f'idle@0/{s}' for s in SHOTS),
               LIVING_GAME_VIEW_OUT=str(out), LIVING_GAME_HOUR='11', LIVING_GAME_DAY_MINUTES='0', LIVING_GAME_FILM='soft', LIVING_GAME_COMPOSED_SLOP=mode,
               LIVING_GAME_SETTINGS=str(out/'settings.json'), LIVING_GAME_SIZE='1600x900', LIVING_GAME_VIEW_CLIP='idle', RUST_LOG='warn')
    with (out/'client.log').open('w') as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)


def components(m):
    lab = np.zeros(m.shape, int)
    n = 0
    for y, x in zip(*np.nonzero(m)):
        if lab[y, x]:
            continue
        n += 1
        st = [(y, x)]
        lab[y, x] = n
        while st:
            cy, cx = st.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = cy + dy, cx + dx
                    if 0 <= yy < m.shape[0] and 0 <= xx < m.shape[1] and m[yy, xx] and not lab[yy, xx]:
                        lab[yy, xx] = n
                        st.append((yy, xx))
    return lab, n


def measure(ink, plain):
    a, b = np.asarray(Image.open(ink).convert('RGB')).astype(float), np.asarray(Image.open(plain).convert('RGB')).astype(float)
    d = lum(b) - lum(a)
    m = d > 8
    lab, n = components(m)
    # The client's blink runs on the clock, so one render can catch a blink the other doesn't:
    # a piece over skin (the plain frame light there) or the iris (green in the inked frame) is
    # the eye, not the hair's ink, and is dropped.
    Lp = lum(b)
    for k in range(1, n + 1):
        sel = lab == k
        if np.median(Lp[sel]) > 160 or (a[sel][:, 1] > a[sel][:, 0] + 25).any():
            m[sel] = False
            lab[sel] = 0
    n = len(np.unique(lab)) - 1
    d = np.where(m, d, 0)
    widths, gaps, long_ = [], 0, 0
    for k in np.unique(lab)[1:]:
        ys, xs = np.nonzero(lab == k)
        h, w = np.ptp(ys) + 1, np.ptp(xs) + 1
        if max(h, w) < 6:
            continue
        long_ += 1
        along, across = (ys, xs) if h >= w else (xs, ys)
        cnt = np.bincount(along - along.min())
        widths += cnt[cnt > 0].tolist()
        gaps += int((cnt == 0).sum())
    return dict(pieces=int(n), lines=long_, width_median=float(np.median(widths)) if widths else None,
                width_p90=float(np.percentile(widths, 90)) if widths else None, gaps=gaps, darkest=round(float(d.max()), 1), ink_px=int(m.sum())), m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', type=Path)
    ap.add_argument('--binary', required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    lines, keys = {}, {}
    for name, style, colour in PEOPLE:
        line = dict(type='adult-f-b', height=1.64, colors=dict(hair=palette.HAIR_COLOURS[colour], skin='#e8bca3', eyes='#4f7a4f'),
                    styles=dict(hair=style, outfit=['jersey-f', 'trousers-f', 'boots-f'], overlays=[]))
        keys[name] = look_lines.key_of(line)
        lines[keys[name]] = dict(person=line, words={})
    book = a.out/'book.json'
    book.write_text(json.dumps(dict(generation='c4-s5close01', generations=[], lines=lines, decor=[])))
    res, tiles = {}, []
    for name, _, _ in PEOPLE:
        ink = render(keys[name], book, a.binary, a.out/name/'ink', 'on')
        plain = render(keys[name], book, a.binary, a.out/name/'noink', 'noink:hair')
        res[name] = {}
        for s in SHOTS:
            r, m = measure(ink[s], plain[s])
            res[name][s] = r
            print(name, s, r, flush=True)
            ys, xs = np.nonzero(m)
            if len(xs):
                cx, cy = int(np.median(xs)), int(np.median(ys))
                half = max(60, int(max(np.ptp(xs), np.ptp(ys)) * 0.6))
                box = (cx - half, cy - half, cx + half, cy + half)
                tiles.append((f'{name} {s}', [Image.open(ink[s]).convert('RGB').crop(box), Image.open(plain[s]).convert('RGB').crop(box),
                                              Image.fromarray((~m * 255).astype(np.uint8)).convert('RGB').crop(box)]))
    (a.out/'closeups.json').write_text(json.dumps(res, indent=1))
    T = 260
    S = Image.new('RGB', (3 * (T + 6) + 10, len(tiles) * (T + 26) + 10), (244, 241, 236))
    d = ImageDraw.Draw(S)
    try:
        f = ImageFont.truetype(FONT, 14)
    except OSError:
        f = ImageFont.load_default()
    for i, (label, ims) in enumerate(tiles):
        y = 10 + i * (T + 26)
        d.text((10, y), label + '   (ink, noink, ink mask)', fill=(40, 40, 40), font=f)
        for j, im in enumerate(ims):
            S.paste(im.resize((T, T), Image.NEAREST), (10 + j * (T + 6), y + 20))
    S.save(a.out/'closeups.png')


if __name__ == '__main__':
    main()
