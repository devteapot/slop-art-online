#!/usr/bin/env python3
"""The strands across a cell border (contract v1.3.1): a strand cut beside a strand-less cut on one
page, drawn at Far and Middle, shows no dark fringe.

    python3 border_proof.py OUT --binary BIN --styles DIR      # DIR: bob (strands) and short (none), paged together

DIR is a hair folder built for the proof: `bob` with the strands' mapping (SLOP_HAIR_LOOK=b2, the
default) and `short` without it (any other SLOP_HAIR_LOOK), put on one page by hair_page.py, so
bob's cells carry strands and short's are all 128, both cuts with `strands` on (page-wide).

**Variants**, each installed in turn (the cuts and the page; the assets' own put back after):
- `on`: as made;
- `off`: `strands` false on both (B ignored);
- `control`: `strands` on, with every texel of B without strands set to 0, as a page would be
  without the generator's 128 fill: the fringe the fill prevents.

**Measured** at Far and Middle (the game camera's stops, 1600x900, 11:00, soft film), a composed
woman in auburn wearing each cut: the hair's mean luma, and its rim's (the hair pixels next to
anything else, where a cut's islands meet their padding on screen). The hair is where the auburn
render and a white-haired one differ by more than 40 levels. Writes OUT/border.json and
OUT/border.png (each variant's crops, 4x nearest).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO/'living/tools/characters'), str(REPO/'living/tools')]
import look_lines  # noqa: E402
import palette  # noqa: E402
from merge_primitives import read_glb, write_glb  # noqa: E402

HAIR = REPO/'living/game/assets/lookdev/styles/hair'
CUTS = ('bob', 'short')
SHOTS = (('far', 'far@0', 14), ('middle', 'middle@0', 22))  # (name, shot, the crop's half-size round the head)
Y = lambda a: a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def book(path):
    lines, keys = {}, {}
    for cut in CUTS:
        for colour in ('auburn', 'white'):
            line = dict(type='adult-f-b', height=1.64, colors=dict(hair=palette.HAIR_COLOURS[colour], skin='#e8bca3', eyes='#4f7a4f'),
                        styles=dict(hair=cut, outfit=['jersey-f', 'trousers-f', 'boots-f'], overlays=[]))
            keys[cut, colour] = look_lines.key_of(line)
            lines[keys[cut, colour]] = dict(person=line, words={})
    path.write_text(json.dumps(dict(generation='c4-s5border', generations=[], lines=lines, decor=[])))
    return keys


def render(key, book_path, binary, out):
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('LIVING_GAME_')}
    env.update(LIVING_GAME_VIEW=f'look:{key}', LIVING_GAME_LOOK_BOOK=str(book_path), LIVING_GAME_VIEW_SHOTS=','.join(f'idle@0/{s}' for _, s, _ in SHOTS),
               LIVING_GAME_VIEW_OUT=str(out), LIVING_GAME_HOUR='11', LIVING_GAME_DAY_MINUTES='0', LIVING_GAME_FILM='soft', LIVING_GAME_SETTINGS=str(out/'settings.json'),
               LIVING_GAME_SIZE='1600x900', LIVING_GAME_VIEW_CLIP='idle', RUST_LOG='warn')
    with (out/'client.log').open('w') as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)
    return {n: np.asarray(Image.open(next(p for p in out.rglob('*.png') if p.name.endswith(s.replace('@', '_') + '.png'))).convert('RGB')).astype(float) for n, s, _ in SHOTS}


def set_strands(path, on):
    j, b = read_glb(path)
    for m in j['materials']:
        h = m.get('extras', {}).get('slop', {}).get('hair')
        if h is not None:
            h['strands'] = on
    write_glb(path, j, b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', type=Path)
    ap.add_argument('--binary', required=True)
    ap.add_argument('--styles', type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    keys = book(a.out/'book.json')
    keep = a.out/'assets-own'
    keep.mkdir(exist_ok=True)
    for f in [f'{c}.glb' for c in CUTS] + ['hair-masks.png']:
        shutil.copyfile(HAIR/f, keep/f)
    man = json.load(open(a.styles/'hair-masks.json'))
    page = np.asarray(Image.open(a.styles/'hair-masks.png').convert('RGB')).copy()
    res, crops = {}, {}
    try:
        for variant in ('off', 'on', 'control'):
            for c in CUTS:
                shutil.copyfile(a.styles/f'{c}.glb', HAIR/f'{c}.glb')
                set_strands(HAIR/f'{c}.glb', variant != 'off')
            img = page.copy()
            if variant == 'control':
                img[..., 2] = np.where(img[..., 2] == 128, 0, img[..., 2])
            Image.fromarray(img).save(HAIR/'hair-masks.png')
            for c in CUTS:
                got = render(keys[c, 'auburn'], a.out/'book.json', a.binary, a.out/variant/c)
                if variant == 'off':
                    white = render(keys[c, 'white'], a.out/'book.json', a.binary, a.out/'white'/c)
                    res.setdefault('mask', {})[c] = {n: (np.abs(Y(white[n]) - Y(got[n])) > 40) for n, _, _ in SHOTS}
                for n, _, box in SHOTS:
                    m = res['mask'][c][n]
                    rim = m & ~(np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1))
                    L = Y(got[n])
                    res.setdefault(variant, {}).setdefault(c, {})[n] = dict(hair=round(float(L[m].mean()), 2), rim=round(float(L[rim].mean()), 2), pixels=int(m.sum()), rim_pixels=int(rim.sum()))
                    ys, xs = np.nonzero(res['mask']['bob'][n])
                    cx, cy = int(np.median(xs)), int(np.median(ys))
                    crops[variant, c, n] = Image.fromarray(got[n].astype(np.uint8)).crop((cx - box, cy - box, cx + box, cy + box))
                print(variant, c, res[variant][c], flush=True)
    finally:
        for f in keep.iterdir():
            shutil.copyfile(f, HAIR/f.name)
    out = {k: v for k, v in res.items() if k != 'mask'}
    for c in CUTS:
        for n, _, _ in SHOTS:
            for v in ('on', 'control'):
                out.setdefault('difference_from_off', {}).setdefault(v, {}).setdefault(c, {})[n] = {k: round(out[v][c][n][k] - out['off'][c][n][k], 2) for k in ('hair', 'rim')}
    (a.out/'border.json').write_text(json.dumps(out, indent=1))
    S = Image.new('RGB', (4 * 200 + 20, 3 * 230 + 10), (244, 241, 236))
    d = ImageDraw.Draw(S)
    for vi, v in enumerate(('off', 'on', 'control')):
        for ci, c in enumerate(CUTS):
            for ni, (n, _, _) in enumerate(SHOTS):
                x, y = (ci * 2 + ni) * 200 + 10, vi * 230
                d.text((x, y + 4), f'{v} · {c} · {n}', fill=(40, 40, 40))
                S.paste(crops[v, c, n].resize((192, 192), Image.NEAREST), (x, y + 22))
    S.save(a.out/'border.png')


if __name__ == '__main__':
    main()
