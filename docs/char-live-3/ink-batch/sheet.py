#!/usr/bin/env python3
"""Review sheets for the ink batch: the drawing, the approved asset and the ink fit, front and
three-quarter, registered by face height and the pupils' midpoint (as the eye-frame and nose
sheets), with close crops per stroke; plus the morph and play sheets.

    python3 sheet.py review APPROVED_STILLS FIT_STILLS OUT.png
    python3 sheet.py morphs MORPH_DIR OUT.png
    python3 sheet.py play APPROVED_STILLS FIT_STILLS OUT.png
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DRAWING = REPO/'docs/char-live-1/face.png'
LAND = json.loads((HERE.parent/'eye-frame/landmarks.json').read_text())
FONT = '/usr/share/fonts/google-noto/NotoSans-Regular.ttf'


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def frame(view):
    """(face height, pupil midpoint) of a landmark set."""
    l, r = (e['pupil'] for e in view['eyes'])
    return view['chin'] - view['hairline'], ((l[0] + r[0]) / 2, (l[1] + r[1]) / 2)


VIEWS = {
    'front': dict(drawing=LAND['drawing_front'], render=LAND['fit_front'], shot='00-clip-idle@0-0_8_0.36_0.88.png'),
    'three-quarter': dict(drawing=LAND['drawing_three_quarter'], render=LAND['fit_three_quarter'], shot='10-clip-idle@0--35_8_0.36_0.88.png'),
}
# Windows in drawing pixels relative to the pupils' midpoint, and their magnification.
WINDOWS = {
    'portrait': ((-250, -205, 250, 255), 1.0),
    'eyes and lids': ((-120, -32, 120, 30), 2.0),
    'brows': ((-130, -62, 130, -12), 1.85),
    'nose': ((-48, 55, 48, 100), 3.0),
    'jaw': ((-145, 95, 145, 215), 1.0),
}


def crop(img, land, window, mag, ref_h):
    h, (cx, cy) = frame(land)
    s = h / ref_h
    x0, y0, x1, y1 = window
    box = (cx + x0 * s, cy + y0 * s, cx + x1 * s, cy + y1 * s)
    size = (round((x1 - x0) * mag), round((y1 - y0) * mag))
    return img.crop(tuple(round(v) for v in box)).resize(size, Image.LANCZOS)


def review(approved, fit, out, label_fit='Ink fit'):
    drawing = Image.open(DRAWING).convert('RGB')
    cols = [('Drawing', None), ('Approved asset', Path(approved)), (label_fit, Path(fit))]
    rows = []
    for view, v in VIEWS.items():
        ref_h = frame(v['drawing'])[0]
        for wname, (window, mag) in WINDOWS.items():
            if view == 'three-quarter' and wname == 'jaw':
                window = (-200, 60, 140, 210)
            if view == 'three-quarter' and wname == 'nose':
                window, mag = (-10, 40, 106, 98), 2.5
            cells = []
            for title, src in cols:
                if src is None:
                    cells.append(crop(drawing, v['drawing'], window, mag, ref_h))
                else:
                    img = Image.open(src/v['shot']).convert('RGB')
                    cells.append(crop(img, v['render'], window, mag, ref_h))
            rows.append((f'{view}: {wname}', cells))
    pad, head = 10, 34
    width = max(sum(c.width for c in cells) + pad * (len(cells) + 1) for _, cells in rows)
    height = 60 + sum(c[0].height + head for _, c in rows) + pad
    sheet = Image.new('RGB', (width, height), (244, 241, 236))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 12), 'Cora / ink batch: ' + '   |   '.join(t for t, _ in cols), fill=(30, 30, 30), font=font(26))
    y = 60
    for name, cells in rows:
        d.text((pad, y + 4), name, fill=(60, 60, 60), font=font(20))
        y += head
        x = pad
        for c in cells:
            sheet.paste(c, (x, y))
            x += c.width + pad
        y += cells[0].height
    sheet.save(out)


def morphs(root, out):
    root = Path(root)
    idx = json.loads((root/'index.json').read_text())
    shots = list(next(iter(idx.values())).keys())
    tiles = []
    for k, v in idx.items():
        row = []
        for s in shots:
            img = Image.open(root/v[s]).convert('RGB')
            box = (540, 290, 1060, 570) if s.endswith('0.91') else (560, 330, 1040, 720)
            if s.startswith('-35'):
                box = (520, 290, 1040, 570) if s.endswith('0.91') else (540, 330, 1020, 720)
            im = img.crop(box)
            row.append(im.resize((round(im.width * 240 / im.height), 240)))
        tiles.append((k, row))
    pad = 8
    W = max(sum(t.width for t in r) + pad * (len(r) + 1) for _, r in tiles) + 170
    H = sum(240 + pad for _ in tiles) + 50
    sheet = Image.new('RGB', (W, H), (244, 241, 236))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 10), 'Cora / ink batch: every face key at 1, Bevy, ' + ', '.join(shots), fill=(30, 30, 30), font=font(22))
    y = 46
    for k, row in tiles:
        d.text((pad, y + 100), k.replace('Fcl_', ''), fill=(40, 40, 40), font=font(18))
        x = 170
        for t in row:
            sheet.paste(t, (x, y))
            x += t.width + pad
        y += 240 + pad
    sheet.save(out)


def play(approved, fit, out):
    approved, fit = Path(approved), Path(fit)
    shots = [('Near, 58°', '01-clip-idle@0-near_0.png', (745, 375, 865, 475)),
             ('Middle, 58°', '07-clip-idle@0-middle_0.png', (765, 400, 845, 466))]
    pad = 10
    tiles = []
    for name, f, box in shots:
        for title, src in (('approved', approved), ('ink fit', fit)):
            im = Image.open(src/f).convert('RGB').crop(box)
            s = 6 if 'Near' in name else 9
            tiles.append((f'{name}: {title} ({s}x nearest)', im.resize((im.width * s, im.height * s), Image.NEAREST)))
    W = max(t.width for _, t in tiles) * 2 + pad * 3
    H = 50 + (tiles[0][1].height + 34) + (tiles[2][1].height + 34) + pad
    sheet = Image.new('RGB', (W, H), (244, 241, 236))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 10), 'Cora / ink batch: play cameras, native pixels enlarged', fill=(30, 30, 30), font=font(22))
    y = 46
    for r in range(2):
        x = pad
        for c in range(2):
            name, t = tiles[r * 2 + c]
            d.text((x, y), name, fill=(40, 40, 40), font=font(18))
            sheet.paste(t, (x, y + 28))
            x += t.width + pad
        y += tiles[r * 2][1].height + 34
    sheet.save(out)


if __name__ == '__main__':
    {'review': review, 'morphs': morphs, 'play': play}[sys.argv[1]](*sys.argv[2:])
