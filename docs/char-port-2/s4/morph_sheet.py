#!/usr/bin/env python3
"""S4 morph sheet: each body's face held at neutral, blink, eye-joy, talk and angry brow, front and
three-quarter (char-live-3 ink-batch/morph_stills.py's stills), and the composed people with their
type files' ink and without.

    python3 morph_sheet.py MORPHS_DIR COMPOSED_DIR OUT_DIR
"""
import glob
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = '/usr/share/fonts/rsms-inter-fonts/Inter-Regular.ttf'
BG = (244, 241, 236)
BODIES = ['woman', 'man', 'elder', 'girl']
KEYS = [('neutral', 'neutral'), ('Fcl_EYE_Close', 'blink'), ('Fcl_EYE_Joy', 'eye joy'), ('Fcl_MTH_A', 'talk'), ('Fcl_BRW_Angry', 'angry brow')]
CELL = (300, 200)


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def still(folder, shot):
    fs = [f for f in sorted(glob.glob(f'{folder}/**/*{shot}.png', recursive=True)) if shot != '0_8_0.18_0.86' or '--35' not in f]
    return Image.open(fs[0]).convert('RGB') if fs else None


def morphs(src, out):
    S = Image.new('RGB', (140 + len(KEYS) * (CELL[0] + 6), 50 + 2 * len(BODIES) * (CELL[1] + 6)), BG)
    d = ImageDraw.Draw(S)
    for j, (_, label) in enumerate(KEYS):
        d.text((140 + j * (CELL[0] + 6), 14), label, fill=(40, 40, 40), font=font(18))
    y = 50
    for b in BODIES:
        for shot, box, tag in (('0_8_0.18_0.86', (640, 240, 960, 453), 'front'), ('-35_8_0.18_0.86', (640, 240, 960, 453), '3/4')):
            d.text((12, y + 80), f'{b}\n{tag}', fill=(40, 40, 40), font=font(16))
            for j, (k, _) in enumerate(KEYS):
                im = still(f'{src}/{b}/{k}', shot)
                if im:
                    S.paste(im.crop(box).resize(CELL, Image.LANCZOS), (140 + j * (CELL[0] + 6), y))
            y += CELL[1] + 6
    S.save(out/'morph-sheet.png')


def composed(src, out):
    keys = sorted(Path(src).glob('lk_*'))
    S = Image.new('RGB', (140 + 4 * (CELL[0] + 6), 50 + len(keys) * (CELL[1] + 6)), BG)
    d = ImageDraw.Draw(S)
    for j, label in enumerate(['front, ink', 'front, noink', '3/4, ink', 'Near, ink (4x)']):
        d.text((140 + j * (CELL[0] + 6), 14), label, fill=(40, 40, 40), font=font(18))
    for i, k in enumerate(keys):
        y = 50 + i * (CELL[1] + 6)
        d.text((12, y + 80), k.name[:14], fill=(40, 40, 40), font=font(14))
        for j, (slop, shot, box) in enumerate((('on', '0_8_0.18_0.86', (600, 170, 1000, 437)), ('noink', '0_8_0.18_0.86', (600, 170, 1000, 437)),
                                               ('on', '-35_8_0.18_0.86', (600, 170, 1000, 437)), ('on', 'near_0', (770, 400, 830, 440)))):
            im = still(f'{k}/{slop}', shot)
            if im:
                S.paste(im.crop(box).resize(CELL, Image.NEAREST if shot == 'near_0' else Image.LANCZOS), (140 + j * (CELL[0] + 6), y))
    S.save(out/'composed-sheet.png')


if __name__ == '__main__':
    morphs(sys.argv[1], Path(sys.argv[3]))
    composed(sys.argv[2], Path(sys.argv[3]))
