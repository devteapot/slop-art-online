#!/usr/bin/env python3
"""Review sheet for attempt 2: the drawing, the approved asset, the batch fit and the new fit,
front and three-quarter, registered as ../ink-batch/sheet.py does (face height and pupils'
midpoint), with the lid and the nose enlarged.

    python3 sheet2.py APPROVED_STILLS BATCH_STILLS NEW_STILLS OUT.jpg
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'ink-batch'))
import sheet  # noqa: E402

WINDOWS = {
    'front': [('portrait', (-250, -205, 250, 255), .9), ('eyes and lids', (-120, -32, 120, 30), 1.85),
              ('lid, the traced eye', (25, -32, 135, 22), 3.4), ('nose', (-48, 55, 48, 100), 3.4)],
    'three-quarter': [('portrait', (-250, -205, 250, 255), .9), ('eyes and lids', (-120, -32, 120, 30), 1.85),
                      ('lid, the traced eye', (-110, -32, 0, 22), 3.4), ('nose', (-10, 40, 106, 98), 2.8)],
}


def main(approved, batch, new, out):
    drawing = Image.open(sheet.DRAWING).convert('RGB')
    cols = [('Drawing', None), ('Approved asset', Path(approved)), ('Batch fit (attempt 1)', Path(batch)), ('Attempt 2', Path(new))]
    rows = []
    for view, v in sheet.VIEWS.items():
        ref = sheet.frame(v['drawing'])[0]
        for name, window, mag in WINDOWS[view]:
            cells = []
            for title, src in cols:
                img = drawing if src is None else Image.open(src/v['shot']).convert('RGB')
                cells.append(sheet.crop(img, v['drawing'] if src is None else v['render'], window, mag, ref))
            rows.append((f'{view}: {name}', cells))
    pad, head = 10, 32
    width = max(sum(c.width for c in cells) + pad * (len(cells) + 1) for _, cells in rows)
    height = 60 + sum(c[0].height + head for _, c in rows) + pad
    out_img = Image.new('RGB', (width, height), (244, 241, 236))
    d = ImageDraw.Draw(out_img)
    d.text((pad, 12), 'Cora / ink batch, attempt 2: ' + '   |   '.join(t for t, _ in cols), fill=(30, 30, 30), font=sheet.font(24))
    y = 60
    for name, cells in rows:
        d.text((pad, y + 4), name, fill=(60, 60, 60), font=sheet.font(19))
        y += head
        x = pad
        for c in cells:
            out_img.paste(c, (x, y))
            x += c.width + pad
        y += cells[0].height
    out_img.save(out, quality=88)


if __name__ == '__main__':
    main(*sys.argv[1:5])
