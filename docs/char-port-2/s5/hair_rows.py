#!/usr/bin/env python3
"""S5 rows: a composed woman in one hair style and each hair colour, drawn by the client at the
portrait, three-quarter, Near and Middle (58°), and a sheet of them beside main's.

    python3 hair_rows.py render OUT --binary BIN [--style bob] [--tag NAME]     # renders OUT/<tag>/<colour>/
    python3 hair_rows.py sheet OUT SHEET.png [--tags port,main]

The colours are the generator's hair colours (person_params.HAIR_COLOURS through palette.py): the
four calibration bins' (black, auburn, blond, grey) and brown, chestnut and white between them.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO/'living/tools/characters')]
import look_lines  # noqa: E402
import palette  # noqa: E402

COLOURS = ['black', 'brown', 'auburn', 'chestnut', 'blond', 'grey', 'white']
# (name, shot, crop): the Near and Middle crops are native pixels drawn 3x and 4x.
SHOTS = [('portrait', '0:8:0.36:0.88', (666, 240, 986, 560)), ('three-quarter', '-35:8:0.36:0.88', (666, 240, 986, 560)),
         ('Near, native', 'near@0', (771, 372, 835, 436)), ('Middle (12 m, 58°), native', 'middle@0', (778, 395, 826, 443))]
FONT = '/usr/share/fonts/rsms-inter-fonts/Inter-Regular.ttf'
BG = (244, 241, 236)


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def render(out, binary, style, tag):
    lines, keys = {}, {}
    for c in COLOURS:
        line = dict(type='adult-f-b', height=1.64, colors=dict(hair=palette.HAIR_COLOURS[c], skin='#e8bca3', eyes='#4f7a4f'),
                    styles=dict(hair=style, outfit=['jersey-f', 'trousers-f', 'boots-f'], overlays=[]))
        k = look_lines.key_of(line)
        lines[k] = dict(person=line, words={})
        keys[c] = k
    book = out/tag/'book.json'
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(json.dumps(dict(generation='c4-s5rows01', generations=[], lines=lines, decor=[])))
    for c, k in keys.items():
        o = out/tag/c
        o.mkdir(parents=True, exist_ok=True)
        env = {x: v for x, v in os.environ.items() if not x.startswith('LIVING_GAME_')}
        env.update(LIVING_GAME_VIEW=f'look:{k}', LIVING_GAME_LOOK_BOOK=str(book), LIVING_GAME_VIEW_SHOTS=','.join(f'idle@0/{s}' for _, s, _ in SHOTS),
                   LIVING_GAME_VIEW_OUT=str(o), LIVING_GAME_HOUR='11', LIVING_GAME_DAY_MINUTES='0', LIVING_GAME_FILM='soft',
                   LIVING_GAME_SETTINGS=str(o/'settings.json'), LIVING_GAME_SIZE='1600x900', LIVING_GAME_VIEW_CLIP='idle', RUST_LOG='warn,living_game=info')
        with (o/'client.log').open('w') as log:
            subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)
        print(tag, c, flush=True)


def sheet(out, path, tags):
    cell = 192
    cols = len(SHOTS) * len(tags)
    S = Image.new('RGB', (130 + cols * (cell + 4), 70 + len(COLOURS) * (cell + 4)), BG)
    d = ImageDraw.Draw(S)
    for i, (name, _, _) in enumerate(SHOTS):
        for t, tag in enumerate(tags):
            d.text((130 + (i * len(tags) + t) * (cell + 4), 20), f'{name}\n{tag}', fill=(40, 40, 40), font=font(13))
    for r, c in enumerate(COLOURS):
        y = 70 + r * (cell + 4)
        d.text((10, y + 70), c, fill=(40, 40, 40), font=font(15))
        for i, (_, shot, box) in enumerate(SHOTS):
            for t, tag in enumerate(tags):
                f = next((p for p in sorted((out/tag/c).rglob('*.png')) if p.name.endswith(shot.replace(':', '_').replace('@', '_') + '.png')), None)
                if f:
                    im = Image.open(f).convert('RGB').crop(box)
                    S.paste(im.resize((cell, cell), Image.NEAREST if 'native' in SHOTS[i][0] else Image.LANCZOS), (130 + (i * len(tags) + t) * (cell + 4), y))
    S.save(path)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd')
    ap.add_argument('out', type=Path)
    ap.add_argument('dest', nargs='?')
    ap.add_argument('--binary')
    ap.add_argument('--style', default='bob')
    ap.add_argument('--tag', default='port')
    ap.add_argument('--tags', default='port,main')
    a = ap.parse_args()
    if a.cmd == 'render':
        render(a.out, a.binary, a.style, a.tag)
    else:
        sheet(a.out, a.dest, a.tags.split(','))
