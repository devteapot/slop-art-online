#!/usr/bin/env python3
"""S0 jaw sheet: does the generator's inside-out jaw and chin line (`cage_head._shell_lines`) draw
the drawing's jaw outline on generated people?

    python3 jaw_sheet.py SHOTS_DIR OUT_DIR

SHOTS_DIR holds shots.py's output for cp2-<body> (lines on) and cp2-<body>-nl (`--no-lines`).
Writes OUT_DIR/jaw-sheet.png and OUT_DIR/lines.json:

- rows 1-2: the drawing's face (front, three-quarter) beside the four bodies' portraits with lines;
- rows 3-4: the closer front and three-quarter shots, grey, with every pixel the lines change by
  more than 8 levels (of 255, any channel) in red;
- lines.json: the changed-pixel counts per body and shot, including Near and Middle.
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
SHOTS = {
    'front': '00-clip-idle@0-0_8_0.36_0.88.png', 'three_quarter': '01-clip-idle@0--35_8_0.36_0.88.png',
    'profile': '02-clip-idle@0-90_8_0.36_0.88.png', 'front_close': '03-clip-idle@0-0_8_0.18_0.86.png',
    'three_quarter_close': '04-clip-idle@0--35_8_0.18_0.86.png', 'near': '05-clip-idle@0-near_0.png',
    'middle': '06-clip-idle@0-middle_0.png',
}
THRESHOLD = 8
CELL = 300


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def still(shots, body, shot, lines=True):
    name = f'cp2-{body}' + ('' if lines else '-nl')
    return np.asarray(Image.open(shots/name/f'own-{name}'/SHOTS[shot]).convert('RGB')).astype(int)


def changed(shots, body, shot):
    return np.abs(still(shots, body, shot) - still(shots, body, shot, False)).max(2) > THRESHOLD


def marked(shots, body, shot):
    base, d = still(shots, body, shot, False), changed(shots, body, shot)
    g = (base.mean(2) * 0.6 + 90).astype(np.uint8)
    im = np.stack([g, g, g], 2)
    wide = d.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            wide |= np.roll(np.roll(d, dy, 0), dx, 1)
    im[wide] = (220, 0, 0)
    return Image.fromarray(im)


def main(shots, out):
    shots, out = Path(shots), Path(out)
    counts = {b: {s: int(changed(shots, b, s).sum()) for s in SHOTS} for b in BODIES}
    (out/'lines.json').write_text(json.dumps(dict(threshold=THRESHOLD, changed_pixels=counts), indent=1) + '\n')
    x0, y0 = 170, 70
    S = Image.new('RGB', (x0 + 5 * (CELL + 10), y0 + 4 * (CELL + 40) + 30), BG)
    d = ImageDraw.Draw(S)
    d.text((20, 18), 'Shell lines on generated people (cage_head._shell_lines), 11:00, idle at 0 s', fill=(30, 30, 30), font=font(24))
    for k, name in enumerate(['Drawing'] + BODIES):
        d.text((x0 + k * (CELL + 10), y0 - 4), name, fill=(40, 40, 40), font=font(18))
    face = Image.open(FACE).convert('RGB')
    rows = [('Front\nportrait', face.crop((230, 0, 830, 600)), 'front', (610, 190, 990, 570), None),
            ('Three-\nquarter\nportrait', face.crop((990, 0, 1590, 600)), 'three_quarter', (630, 190, 1010, 570), None),
            ('Front,\ncloser:\nred = pixels\nthe lines\nchange', None, 'front_close', (550, 200, 1050, 600), marked),
            ('Three-\nquarter,\ncloser:\nred = pixels\nthe lines\nchange', None, 'three_quarter_close', (550, 200, 1050, 600), marked)]
    for r, (label, drawing, shot, box, fn) in enumerate(rows):
        y = y0 + 24 + r * (CELL + 40)
        d.multiline_text((20, y + 10), label, fill=(40, 40, 40), font=font(17))
        if drawing is not None:
            S.paste(drawing.resize((CELL, CELL), Image.LANCZOS), (x0, y))
        for k, b in enumerate(BODIES):
            im = fn(shots, b, shot) if fn else Image.fromarray(still(shots, b, shot).astype(np.uint8))
            S.paste(im.crop(box).resize((CELL, CELL), Image.LANCZOS), (x0 + (k + 1) * (CELL + 10), y))
            d.text((x0 + (k + 1) * (CELL + 10), y + CELL + 4), f'{counts[b][shot]} px changed', fill=(70, 70, 70), font=font(14))
    S.save(out/'jaw-sheet.png')


if __name__ == '__main__':
    main(*sys.argv[1:3])
