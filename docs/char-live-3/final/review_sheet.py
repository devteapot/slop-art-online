#!/usr/bin/env python3
"""char-live-3's closing review sheet, in char-live-2's layout (docs/char-live-2/final/review-sheet.png):
drawing and Bevy pairs (front, three-quarter, profile, back; face and full body), the 58° Near
and Middle crops beside the overhead drawing, four walk samples and the calibration frame.

    python3 review_sheet.py STILLS_DIR WALK_SEQ_DIR CALIBRATION_REPORT OUT.png
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[3]
FACE = REPO/'docs/char-live-1/face.png'
TURN = REPO/'docs/char-live-1/turnaround.png'
FONT = '/usr/share/fonts/rsms-inter-fonts/Inter-Regular.ttf'
BG = (244, 241, 236)

# Drawing boxes (face sheet and turnaround) and Bevy boxes (native 1600 x 900 stills).
VIEWS = [
    ('Front', (FACE, (230, 0, 830, 600)), ('00-clip-idle@0-0_8_0.36_0.88.png', (610, 190, 990, 570)),
     (TURN, (55, 20, 315, 790)), ('04-clip-idle@0-0_5_1.14_0.50.png', (660, 100, 936, 810))),
    ('Three-quarter', (FACE, (990, 0, 1590, 600)), ('08-clip-idle@0--35_8_0.36_0.88.png', (630, 190, 1010, 570)),
     (TURN, (1020, 20, 1270, 790)), ('05-clip-idle@0--35_5_1.14_0.50.png', (664, 100, 940, 810))),
    ('Profile', (TURN, (330, 15, 520, 205)), ('09-clip-idle@0-90_8_0.36_0.88.png', (610, 190, 990, 570)),
     (TURN, (325, 20, 505, 790)), ('06-clip-idle@0-90_5_1.14_0.50.png', (671, 100, 947, 810))),
    ('Back', (TURN, (560, 15, 750, 205)), ('10-clip-idle@0-180_8_0.36_0.88.png', (630, 190, 1010, 570)),
     (TURN, (515, 20, 795, 790)), ('07-clip-idle@0-180_5_1.14_0.50.png', (665, 100, 941, 810))),
]
OVERHEAD = (TURN, (1560, 590, 1735, 740))


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def fit(img, w, h):
    """Scale into a w x h cell, keeping aspect, on the sheet background."""
    s = min(w / img.width, h / img.height)
    im = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    cell = Image.new('RGB', (w, h), BG)
    cell.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
    return cell


def main(stills, walk, report, out):
    stills, walk = Path(stills), Path(walk)
    rep = json.loads(Path(report).read_text())
    S = Image.new('RGB', (1840, 1740), BG)
    d = ImageDraw.Draw(S)
    d.text((24, 18), 'Cora Stannard', fill=(30, 30, 30), font=font(40))
    d.text((330, 30), 'Drawing and Bevy   /   char-live-3   /   dev-box AMD, 11:00 daylight', fill=(40, 40, 40), font=font(22))
    for i, (name, dface, bface, dbody, bbody) in enumerate(VIEWS):
        x = 24 + i * 455
        d.text((x, 90), name, fill=(30, 30, 30), font=font(26))
        d.text((x, 138), 'Drawing', fill=(50, 50, 50), font=font(17))
        d.text((x + 220, 138), 'Bevy', fill=(50, 50, 50), font=font(17))
        S.paste(fit(Image.open(dface[0]).convert('RGB').crop(dface[1]), 212, 210), (x, 165))
        S.paste(fit(Image.open(stills/bface[0]).convert('RGB').crop(bface[1]), 212, 210), (x + 220, 165))
        S.paste(fit(Image.open(dbody[0]).convert('RGB').crop(dbody[1]), 212, 546), (x, 395))
        S.paste(fit(Image.open(stills/bbody[0]).convert('RGB').crop(bbody[1]), 212, 546), (x + 220, 395))
    d.text((24, 990), '58° play camera', fill=(30, 30, 30), font=font(26))
    over = Image.open(OVERHEAD[0]).convert('RGB').crop(OVERHEAD[1])
    for k, (name, shot, box, cell) in enumerate((('Near · 8 m', '01-clip-idle@0-near_0.png', (729, 388, 869, 528), 128),
                                                 ('Middle · 12 m', '03-clip-idle@0-middle_0.png', (754, 409, 844, 499), 86))):
        x = 24 + k * 505
        d.text((x, 1040), name, fill=(40, 40, 40), font=font(20))
        S.paste(fit(over, cell, cell), (x + (130 - cell) // 2 + 20, 1115 + (130 - cell) // 2))
        native = Image.open(stills/shot).convert('RGB').crop(box)
        S.paste(native.resize((180, 180), Image.NEAREST), (x + 200, 1095))
        d.text((x, 1282), 'Overhead drawing', fill=(50, 50, 50), font=font(15))
        d.text((x + 200, 1282), 'Native Bevy crop (nearest)', fill=(50, 50, 50), font=font(15))
    d.text((24, 1355), 'Embedded walk   /   Middle, 12 m', fill=(30, 30, 30), font=font(26))
    seq = sorted(walk.glob('*.png'))
    for k, f in enumerate((0, 7, 15, 22)):
        im = Image.open(seq[f]).convert('RGB').crop((720, 360, 880, 520)).resize((187, 187), Image.LANCZOS)
        S.paste(im, (24 + k * 252, 1400))
        d.text((24 + k * 252, 1600), f'{f / 30:.2f} s', fill=(50, 50, 50), font=font(17))
    d.text((1090, 990), 'Calibration frame', fill=(30, 30, 30), font=font(26))
    cal = Image.open(stills/'00-clip-idle@0-0_8_0.36_0.88.png').convert('RGB').crop((230, 160, 1370, 800))
    S.paste(cal.resize((694, 390), Image.LANCZOS), (1090, 1035))
    pt = {p['patch']: p for p in rep['patches'] if p['shot'] == 'portrait'}
    for k, (label, key) in enumerate((('Coat', 'coat'), ('Jersey', 'jersey'), ('Neck shade', 'skin shadow'))):
        p = pt[key]
        d.text((1090, 1470 + k * 46), f"{label:<11}drawing {','.join(map(str, p['target']))}      Bevy {','.join(map(str, p['measured']))}",
               fill=(40, 40, 40), font=font(20))
    d.text((24, 1690), 'Turnaround and face references · calibrated release client from merged main (f53d46700) · idle at 0 s · walk at 30 fps',
           fill=(60, 60, 60), font=font(16))
    S.save(out)


if __name__ == '__main__':
    main(*sys.argv[1:5])
