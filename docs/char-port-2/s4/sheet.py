#!/usr/bin/env python3
"""S4 sheet: the four bodies with S1-S2 (`SLOP_PORT=jaw,jaw_shell,paint,neck`) and with S4's ink added (`…,ink`), beside the drawing.

    python3 sheet.py SHOTS_DIR OUT_DIR

SHOTS_DIR holds docs/char-port-2/s0/shots.py's output for cp2q-<body> (S1-S2) and cp2i-<body>
(with ink), from the same client. Writes OUT_DIR/sheet.png and OUT_DIR/play.json (pixels changed at Near and Middle).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[3]
FACE = REPO/'docs/char-live-1/face.png'
FONT = '/usr/share/fonts/rsms-inter-fonts/Inter-Regular.ttf'
BG = (244, 241, 236)
BODIES = ['woman', 'man', 'elder', 'girl']
CELL = 260
ROWS = [('Front, closer', '03-clip-idle@0-0_8_0.18_0.86.png', (560, 230, 1040, 710), (380, 200, 680, 500)),
        ('Three-quarter, closer', '04-clip-idle@0--35_8_0.18_0.86.png', (560, 230, 1040, 710), (1140, 200, 1440, 500)),
        ('Front portrait', '00-clip-idle@0-0_8_0.36_0.88.png', (640, 230, 960, 550), None),
        ('Near (58°), native', '05-clip-idle@0-near_0.png', (774, 388, 824, 438), None),
        ('Middle (58°), native', '06-clip-idle@0-middle_0.png', (784, 410, 816, 442), None)]
NEAREST = ('Near (58°), native', 'Middle (58°), native')
PLAY = {'near': '05-clip-idle@0-near_0.png', 'middle': '06-clip-idle@0-middle_0.png'}


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def img(shots, pre, body, shot):
    return Image.open(shots/f'{pre}-{body}'/f'own-{pre}-{body}'/shot).convert('RGB')


def main(shots, out):
    shots, out = Path(shots), Path(out)
    play = {}
    for b in BODIES:
        play[b] = {}
        for k, s in PLAY.items():
            d = np.abs(np.asarray(img(shots, 'cp2q', b, s)).astype(int) - np.asarray(img(shots, 'cp2i', b, s)).astype(int)).max(2)
            play[b][k] = dict(changed_over_8=int((d > 8).sum()), max_levels=int(d.max()))
    (out/'play.json').write_text(json.dumps(play, indent=1) + '\n')
    x0, y0 = 190, 80
    S = Image.new('RGB', (x0 + 9 * (CELL + 6), y0 + len(ROWS) * (CELL + 14) + 20), BG)
    d = ImageDraw.Draw(S)
    d.text((20, 16), 'S4: S1-S2 (left of each pair) and with ink, SLOP_PORT=…,ink (right), 11:00, idle at 0 s, main\'s client', fill=(30, 30, 30), font=font(24))
    d.text((x0, y0 - 26), 'Drawing', fill=(40, 40, 40), font=font(17))
    for k, b in enumerate(BODIES):
        d.text((x0 + (1 + 2 * k) * (CELL + 6), y0 - 26), f'{b}: S2 | S4', fill=(40, 40, 40), font=font(17))
    face = Image.open(FACE).convert('RGB')
    for r, (label, shot, box, dbox) in enumerate(ROWS):
        y = y0 + r * (CELL + 14)
        d.multiline_text((20, y + 10), label.replace(', ', ',\n'), fill=(40, 40, 40), font=font(17))
        if dbox:
            S.paste(face.crop(dbox).resize((CELL, CELL), Image.LANCZOS), (x0, y))
        for k, b in enumerate(BODIES):
            for j, pre in enumerate(('cp2q', 'cp2i')):
                S.paste(img(shots, pre, b, shot).crop(box).resize((CELL, CELL), Image.NEAREST if label in NEAREST else Image.LANCZOS), (x0 + (1 + 2 * k + j) * (CELL + 6), y))
    S.save(out/'sheet.png')


if __name__ == '__main__':
    main(*sys.argv[1:3])
