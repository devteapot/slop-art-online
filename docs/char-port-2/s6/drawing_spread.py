#!/usr/bin/env python3
"""Cora's spread, re-derived from her front drawing the generator's way (char-port-2 S6, the GC's
decision after step 3): the hair's width above the chin over the face's width at the cheekbones,
as `Hair.measures()` takes `spread_face` (the ears open, as the drawing has them).

    python3 drawing_spread.py OUT.json OUT.png [LOOK.png ID.png]   # and a front portrait render, the same way

LOOK is a game front portrait (back_views.py --front, `0:8:0.36:0.88`) and ID the same shot of
the all-hair ID (part_id.py --all): the render is measured as the drawing is, its hair from the
ID's green and its skin warm (R over G by 25 and over B by 40), inside the portrait's crop.

**Two spreads** on each: `spread_face`, the hair's whole width; and `body`, the hair's body
(every part narrower than the outline check's 15 px, scaled by head size, taken off): the width
without the curls and thin locks, as the outline check holds the hair to it.

**The acceptance (the GC's, after step 3):** `body_over_eyes`, the hair body's width over the eye
spacing (iris centre to iris centre), which no face's width enters; its band is the drawing's
value ± 0.10/1.82 of it (the cheek measure's ±0.10 about 1.82, in proportion). `body` (over the
cheek width) is reported, not held: a face wider than the drawing's for its eyes (ours, 1.86
against 1.75 at the GC's count) would charge the face's width to the hair.

**The drawing:** the front drawing in docs/char-live-2/hair/final/review.jpg (its largest copy),
checked against the copy in docs/char-live-2/stage-1-targets.jpg.

**The pixels:** each is classed by its nearest reference colour: the drawing's hair swatches
(stage-1's 9 × 9 medians: shade, mid, light, highlight), skin (cheek, base, shadow), the paper,
and ink (dark, luma under 70). Hair is hair or ink, connected to the hair mass (the face's own
ink lines are inside the hair's width either way).

**The measure:**
- **The chin:** where the face's centre run of skin is narrowest (its ink point), between the
  mouth and the neck.
- **The eyes:** the iris pieces parted into two eyes at the widest gap across (`two_eyes`); their
  centres give the eye line and the eye spacing.
- **The head's height:** the eye spacing over 0.30, stage-1's front ratio (eye spacing over head
  height).
- **The cheek row:** 0.030 m under the eye line, the generator's (`eye_z - 0.030`), in head
  heights of the generator's standard head (0.030 / 0.2322, Cora's head height in metres).
- **The cheek width:** the run of skin on that row that holds the face's centre column: the face
  across the cheekbones (the generator's, in front of the pinna): the face's outline on that row.
  On the drawing no hair covers the cheeks there; on a render it is taken from the same frame drawn
  with no hair (image_spread.py), where nothing covers it (at this head's cheek row the ears join
  the outline: the generator's head has no line between them and the face).
- **The spread:** the hair's (and its ink's) widest extent over all rows above the chin, over the
  cheek width.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parents[3]
SOURCES = [("review.jpg front drawing", REPO / "docs/char-live-2/hair/final/review.jpg", (18, 93, 396, 434)),
           ("stage-1 targets front drawing", REPO / "docs/char-live-2/stage-1-targets.jpg", (17, 90, 327, 365))]
HAIR = [(88, 42, 27), (152, 72, 43), (171, 88, 56), (187, 99, 63)]
SKIN = [(235, 164, 128), (241, 183, 148), (192, 121, 90)]
PAPER = [(226, 228, 232), (240, 240, 240)]
EYE_SPACING_H = 0.30
CHEEK_DROP_H = 0.030 / 0.23221159


def classify(a):
    refs = [(c, "hair") for c in HAIR] + [(c, "skin") for c in SKIN] + [(c, "paper") for c in PAPER]
    d = np.stack([np.linalg.norm(a - np.array(c, float), axis=2) for c, _ in refs])
    k = np.argmin(d, axis=0)
    kinds = np.array([t for _, t in refs])[k]
    luma = a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722
    kinds = np.where(luma < 70, "ink", kinds)
    green = (a[..., 1] > a[..., 0] + 8) & (a[..., 1] > a[..., 2]) & (luma > 60) & (luma < 200)
    return np.where(green, "iris", kinds)


def blobs(mask):
    seen = np.zeros_like(mask)
    out = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        st, pc = [(y0, x0)], []
        seen[y0, x0] = True
        while st:
            y, x = st.pop()
            pc.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                v, u = y + dy, x + dx
                if 0 <= v < mask.shape[0] and 0 <= u < mask.shape[1] and mask[v, u] and not seen[v, u]:
                    seen[v, u] = True
                    st.append((v, u))
        out.append(np.array(pc))
    return sorted(out, key=len, reverse=True)


def two_eyes(iris):
    """The two eyes' centres (y, x): every piece of iris (the pupil and a lid cut it into pieces;
    a blink leaves only slivers), parted into two at the widest gap across between the pieces. The
    largest twelve under 3000 px: a render's ground is far larger and is left out."""
    pcs = sorted((e for e in blobs(iris) if 3 <= len(e) < 3000), key=len, reverse=True)[:12]
    pcs.sort(key=lambda e: e[:, 1].mean())
    cut = int(np.argmax(np.diff([e[:, 1].mean() for e in pcs]))) + 1
    return np.concatenate(pcs[:cut]).mean(axis=0), np.concatenate(pcs[cut:]).mean(axis=0)


def measure(path, box):
    im = Image.open(path).convert("RGB").crop(box)
    a = np.asarray(im).astype(float)
    kind = classify(a)
    w = kind.shape[1]
    skin = kind == "skin"
    (ya, xa), (yb, xb) = two_eyes(kind == "iris")
    eye_y, spacing = (ya + yb) / 2, abs(xa - xb)
    cx = int(round((xa + xb) / 2))
    hair = (kind == "hair") | (kind == "ink")
    return finish(im, hair, skin, eye_y, spacing, cx, w)


def cheek_at(skin, eye_y, spacing, cx, w):
    """The chin row, the cheek row, and the run of skin on the cheek row that holds the face's centre column (the
    module's docstring): (chin, cheek_row, (x0, x1), head_px)."""
    head_px = spacing / EYE_SPACING_H
    h = skin.shape[0]

    def run(row):
        if not skin[row, cx]:
            return None
        x0 = x1 = cx
        while x0 > 0 and skin[row, x0 - 1]:
            x0 -= 1
        while x1 < w - 1 and skin[row, x1 + 1]:
            x1 += 1
        return x0, x1

    rows = range(int(eye_y + 0.33 * head_px), min(h, int(eye_y + 0.62 * head_px)))
    width = [(0 if run(r) is None else run(r)[1] - run(r)[0]) for r in rows]
    chin = list(rows)[int(np.argmin(width))]
    cheek_row = int(round(eye_y + CHEEK_DROP_H * head_px))
    return chin, cheek_row, run(cheek_row), head_px


def finish(im, hair, skin, eye_y, spacing, cx, w):
    """The chin, the cheek row and width, and the hair's two spreads (the module's docstring)."""
    chin, cheek_row, cheek_px, head_px = cheek_at(skin, eye_y, spacing, cx, w)
    cheek = cheek_px
    # The face's own outline on that row: the drawing's, where no hair covers the cheeks at that
    # height; a render's from its copy with no hair (part_id.py --none), so no lock can cut it short.
    cw = cheek[1] - cheek[0]
    hair = hair.copy()
    hair[chin:] = False
    big = blobs(hair)[0]  # the hair mass with its outline ink
    hx = (int(big[:, 1].min()), int(big[:, 1].max()))
    spread = (hx[1] - hx[0]) / cw
    n = int(round(15 * head_px / 230)) | 1
    body = np.asarray(Image.fromarray((hair * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(n)).filter(ImageFilter.MaxFilter(n))) > 0
    bx = np.nonzero(body.any(axis=0))[0]
    pic = im.copy()
    d = ImageDraw.Draw(pic)
    d.line((cheek[0], cheek_row, cheek[1], cheek_row), fill=(0, 90, 255), width=2)
    d.line((hx[0], chin, hx[0], 0), fill=(255, 0, 0))
    d.line((hx[1], chin, hx[1], 0), fill=(255, 0, 0))
    d.line((0, chin, w, chin), fill=(0, 160, 0))
    d.line((bx.min(), chin, bx.min(), 0), fill=(255, 150, 0))
    d.line((bx.max(), chin, bx.max(), 0), fill=(255, 150, 0))
    return dict(body_over_eyes=round(float((bx.max() - bx.min()) / spacing), 3), whole_over_eyes=round(float((hx[1] - hx[0]) / spacing), 3),
                body_width_px=int(bx.max() - bx.min()), body=round(float((bx.max() - bx.min()) / cw), 3), opening_px=n, eye_line_px=round(float(eye_y), 1), eye_spacing_px=round(float(spacing), 1), head_px=round(float(head_px), 1), chin_row=chin,
                cheek_row=cheek_row, cheek_px=cheek, cheek_width_px=cw, face_over_eyes=round(float(cw / spacing), 3), hair_px=hx, hair_width_px=hx[1] - hx[0], spread_face=round(float(spread), 3)), pic


def render(look, idp, box=(600, 160, 1000, 620), face=None):
    """A game front portrait, measured as the drawing is (the module's docstring). `face`: the
    same frame with no hair drawn (part_id.py --none), whose skin and eyes give the face, so no lock
    over a cheek or an eye can move it (image_spread.py)."""
    im = Image.open(look).convert("RGB").crop(box)
    i = np.asarray(Image.open(idp).convert("RGB").crop(box)).astype(int)
    hair = (i[..., 1] - i[..., 0] > 28) & (i[..., 1] - i[..., 2] > 28) & (i[..., 1] >= 60)
    a = np.asarray(Image.open(face).convert("RGB").crop(box) if face else im).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    skin = (r > g + 12) & (r > b + 25) if face else (r > g + 25) & (r > b + 40) & (r > 170) & ~hair  # the hairless frame: nothing over the face
    # The eyes: every piece of iris (the pupil and a lid cut it into pieces; a blink leaves only
    # slivers), parted into the two eyes at the widest gap across between the pieces; the
    # ground's green is far larger and is left out.
    (ya, xa), (yb, xb) = two_eyes((g > r + 8) & (g > b) & (True if face else ~hair))
    return finish(im, hair, skin, (ya + yb) / 2, abs(xa - xb), int(round((xa + xb) / 2)), a.shape[1])


EAR_ID = "the ear-ID copy's magenta (ear_id.py): red and blue each over green by 40"


def ears_of(a):
    """The pixels of a frame drawn with the ear-ID copy that are ear (EAR_ID)."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (r > g + 40) & (b > g + 40)


def face_render(frame, box=(600, 160, 1000, 620)):
    """S6b's acceptance (the GC's): the face's width at the cheek row over the eye spacing, measured as the drawing's
    is, on a front frame with no hair whose type file is the ear-ID copy (docs/char-port-2/s6b/ear_id.py,
    face2d.py). The skin is the hairless frame's (render()'s rule) less the ears, so the run on the cheek row stops at
    the ear's front edge, as the drawing's stops at the line before her ear. Returns (dict, picture)."""
    im = Image.open(frame).convert("RGB").crop(box)
    a = np.asarray(im).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    ear = ears_of(a)
    skin = (r > g + 12) & (r > b + 25) & ~ear
    (ya, xa), (yb, xb) = two_eyes((g > r + 8) & (g > b))
    eye_y, spacing, cx = (ya + yb) / 2, abs(xa - xb), int(round((xa + xb) / 2))
    chin, cheek_row, run, head_px = cheek_at(skin, eye_y, spacing, cx, a.shape[1])
    cw = run[1] - run[0]
    pic = im.copy()
    d = ImageDraw.Draw(pic)
    d.line((run[0], cheek_row, run[1], cheek_row), fill=(0, 90, 255), width=2)
    row_ear = np.nonzero(ear[cheek_row])[0]
    return dict(face_over_eyes=round(float(cw / spacing), 3), cheek_width_px=int(cw), eye_spacing_px=round(float(spacing), 1), cheek_row=cheek_row, cheek_px=[int(run[0]), int(run[1])],
                eye_line_px=round(float(eye_y), 1), ear_on_cheek_row=bool(len(row_ear)), ear_px=int(ear.sum())), pic


def main(out_json, out_png, look=None, idp=None):
    res, pics = {}, []
    todo = [(name, lambda p=path, b=box: measure(p, b)) for name, path, box in SOURCES]
    if look:
        todo.append(("game front portrait", lambda: render(look, idp)))
    for name, fn in todo:
        r, pic = fn()
        res[name] = r
        pics.append(pic.resize((int(pic.width * 380 / pic.height), 380)))
        print(name, r)
    S = Image.new("RGB", (sum(p.width for p in pics) + 10 * len(pics), 390), (244, 241, 236))
    x = 0
    for p in pics:
        S.paste(p, (x, 5))
        x += p.width + 10
    S.save(out_png)
    drawn = [r for n, r in res.items() if n != "game front portrait"]
    boe = float(np.mean([r["body_over_eyes"] for r in drawn]))
    Path(out_json).write_text(json.dumps(dict(sources=res, drawing=dict(spread_face=round(float(np.mean([r["spread_face"] for r in drawn])), 3), body=round(float(np.mean([r["body"] for r in drawn])), 3),
                                                                        body_over_eyes=round(boe, 3), band=[round(boe * (1 - 0.10 / 1.82), 3), round(boe * (1 + 0.10 / 1.82), 3)]),
                                              method=__doc__.split("**The measure:**")[1].strip()), indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:5])
