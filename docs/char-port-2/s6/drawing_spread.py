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
- **The cheek row** (by landmarks since S7's ortho re-measure, the GC's 2026-11-21: the same on the drawing and a
  render, never by millimetres): `ROW_FRACTION` of the way from the eye line to the chin. The fraction is the
  row the drawing's 1.751 was measured at (review.jpg: row 206, eye line 169.7, chin 292: 0.2967). That row was
  first set as 0.030 m under the eye line in head heights of Cora's standard head (0.030 / 0.2322), the head's
  height taken from the eye spacing by stage-1's ratio (0.30); on a generated head, whose spacing is 0.38 of its
  height, that rule put the row 41-44 mm under the eyes instead of 30 (`rule="spacing"` keeps it, for S6b's
  numbers).
- **The chin on a render** (`chin_px`): a render has no ink at the chin's midline, so its chin is the lowest
  pixel of the face's front on the eyes' middle column, from a frame drawn with the chin-ID copy
  (docs/char-port-2/s7/chin_id.py: the skin in front of the irises in pure yellow). It is the tip of the chin, as
  the drawing's ink point is.
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


ROW_FRACTION = 0.2967  # the drawing's row, from its eye line to its chin (the module's docstring)
CHIN_ID = "the chin-ID copy's yellow (docs/char-port-2/s7/chin_id.py): red and green each over blue by 80 (the client draws it (227, 217, 113))"


def chin_of(a):
    """The pixels of a frame drawn with the chin-ID copy that are the face's front (CHIN_ID)."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (r > b + 80) & (g > b + 80)


def chin_px(a, cx, below):
    """The chin's row on a chin-ID frame (an array, cropped as the frame it goes with): the lowest front pixel within
    2 px of the column cx, under the row `below` (the eye line). None if the column has no front."""
    m = chin_of(a)[:, max(0, cx - 2):cx + 3].any(axis=1)
    m[:int(below) + 1] = False
    ys = np.nonzero(m)[0]
    return int(ys.max()) if len(ys) else None


def chin_from(chin_frame, box, cx, eye_y):
    """A render's chin from its chin-ID frame; it stops, rather than fall back to the drawing's search, when the frame
    shows no chin (a chin found by the drawing's search on a render lies in the neck)."""
    c = chin_px(np.asarray(Image.open(chin_frame).convert("RGB").crop(box)).astype(float), cx, eye_y)
    if c is None:
        raise SystemExit(f"drawing_spread: no chin-ID front ({CHIN_ID}) under the eye line in {chin_frame}")
    return c


def cheek_at(skin, eye_y, spacing, cx, w, chin=None, rule="landmark"):
    """The chin row, the cheek row, and the run of skin on the cheek row that holds the face's centre column (the
    module's docstring): (chin, cheek_row, (x0, x1), head_px). `chin`: a render's chin (chin_px); without it, the
    drawing's (the centre run's narrowest row, its ink point). `rule`: "landmark" (ROW_FRACTION of eye line to chin,
    the acceptance's) or "spacing" (S6b's: CHEEK_DROP_H head heights, the head from the eye spacing)."""
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

    if chin is None:
        rows = range(int(eye_y + 0.33 * head_px), min(h, int(eye_y + 0.62 * head_px)))
        width = [(0 if run(r) is None else run(r)[1] - run(r)[0]) for r in rows]
        chin = list(rows)[int(np.argmin(width))]
    if rule == "landmark":
        cheek_row = int(round(eye_y + ROW_FRACTION * (chin - eye_y)))
    else:
        cheek_row = int(round(eye_y + CHEEK_DROP_H * head_px))
    return chin, cheek_row, run(cheek_row), head_px


def finish(im, hair, skin, eye_y, spacing, cx, w, chin=None, rule="landmark"):
    """The chin, the cheek row and width, and the hair's two spreads (the module's docstring)."""
    chin, cheek_row, cheek_px, head_px = cheek_at(skin, eye_y, spacing, cx, w, chin, rule)
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
                cheek_row=cheek_row, cheek_px=cheek, cheek_width_px=cw, face_over_eyes=round(float(cw / spacing), 3), hair_px=hx, hair_width_px=hx[1] - hx[0], spread_face=round(float(spread), 3),
                row_rule=rule, row_fraction=round(float((cheek_row - eye_y) / (chin - eye_y)), 4)), pic


def render(look, idp, box=(600, 160, 1000, 620), face=None, chin_frame=None, rule=None):
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
    eye_y, cx = (ya + yb) / 2, int(round((xa + xb) / 2))
    # The landmark row needs the render's chin (a chin-ID frame); without one, S6b's spacing rule.
    chin = chin_from(chin_frame, box, cx, eye_y) if chin_frame else None
    return finish(im, hair, skin, eye_y, abs(xa - xb), cx, a.shape[1], chin, rule or ("landmark" if chin_frame else "spacing"))


EAR_ID = "the ear-ID copy's magenta (ear_id.py): red and blue each over green by 40"


def ears_of(a):
    """The pixels of a frame drawn with the ear-ID copy that are ear (EAR_ID)."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (r > g + 40) & (b > g + 40)


def face_render(frame, box=(600, 160, 1000, 620), chin_frame=None, rule=None):
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
    # The landmark row needs the render's chin (a chin-ID frame of the same view); without one, S6b's spacing rule.
    chin = chin_from(chin_frame, box, cx, eye_y) if chin_frame else None
    rule = rule or ("landmark" if chin_frame else "spacing")
    chin, cheek_row, run, head_px = cheek_at(skin, eye_y, spacing, cx, a.shape[1], chin, rule)
    cw = run[1] - run[0]
    pic = im.copy()
    d = ImageDraw.Draw(pic)
    d.line((run[0], cheek_row, run[1], cheek_row), fill=(0, 90, 255), width=2)
    row_ear = np.nonzero(ear[cheek_row])[0]
    return dict(face_over_eyes=round(float(cw / spacing), 3), cheek_width_px=int(cw), eye_spacing_px=round(float(spacing), 1), cheek_row=cheek_row, cheek_px=[int(run[0]), int(run[1])],
                eye_line_px=round(float(eye_y), 1), ear_on_cheek_row=bool(len(row_ear)), ear_px=int(ear.sum()), chin_row=int(chin), row_rule=rule,
                row_fraction=round(float((cheek_row - eye_y) / (chin - eye_y)), 4)), pic


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
