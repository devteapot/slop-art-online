#!/usr/bin/env python3
"""Tile images into a contact sheet (a fallback for ImageMagick's montage; needs Pillow).

    python3 living/tools/contact_sheet.py OUT.png IMG... [--cols 6] [--cell 640x360]
"""

import argparse

from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--cell", default="640x360")
    a = ap.parse_args()
    w, h = (int(v) for v in a.cell.split("x"))
    pad = 2
    cols = min(a.cols, len(a.images))
    rows = (len(a.images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (w + 2 * pad), rows * (h + 2 * pad)), (32, 32, 32))
    for i, path in enumerate(a.images):
        im = Image.open(path).convert("RGB")
        im.thumbnail((w, h))
        x = (i % cols) * (w + 2 * pad) + pad + (w - im.width) // 2
        y = (i // cols) * (h + 2 * pad) + pad + (h - im.height) // 2
        sheet.paste(im, (x, y))
    sheet.save(a.out)


if __name__ == "__main__":
    main()
