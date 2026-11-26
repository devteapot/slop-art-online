#!/usr/bin/env python3
"""Known-answer test for the 2D measures (drawing_spread.py: the drawing's measure, `render` (image_spread.py's,
which shares its face definition) and `face_render`, S6b's acceptance; the rule in docs/char-port-2/PLAN.md: a
measuring tool passes a known-answer test before its numbers are used).

Synthetic pictures of known sizes, 400 x 460 px, the eyes 60 px apart at row 200 (so the head is 200 px, the
cheek row 226 and the chin searched for in rows 266-323):
- **the face:** 101 px of skin across (x 150-250) from row 120 to 270, narrowing to a 7 px chin at row 300, a
  41 px neck under it;
- **the irises:** two discs (r 6) at x 170 and 230;
- **the ears:** 15 px of skin past each side of the face, rows 190-240, across the cheek row;
- **the hair:** a 161 px block (x 120-280) over rows 60-140.

The cases:
- **a drawing** (drawing_spread.measure): its colours, an ink line between each ear and the face (as Cora draws
  it). Known: the face 100 px (x1 - x0) over 60, the hair's whole and body 160 px.
- **a render** (render(), image_spread.py's): the frame with no hair has the ears joined to the face, as the
  generator's head has no line there, and the all-hair ID's green. Known: its cheek takes in the ears (130 px), the
  hair body 160 px.
- **the acceptance** (face_render): the same no-hair frame drawn with the ear-ID copy, the ears magenta. Known: the
  face alone, 100 px over 60; and with no ear on the row, the same.
- **render() with the ear-ID frame** (image_spread.py run with the ear-ID type installed): its cheek stops at the
  ears too. Known: the cheek 100 px, the hair body over it 1.6.

- **the landmark row** (`landmark_cases`): a face that narrows under the eyes, so the row's height matters; the
  drawing's chin and a render's chin-ID chin (drawing_spread.chin_px), each with its row and width known.

Each must return the known answer exactly (whole pixels) or to 0.001 (ratios). Exit status 1 on any failure.
    python3 drawing_spread_selftest.py
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path[:0] = [str(Path(__file__).resolve().parent)]
import drawing_spread as D  # noqa: E402

W, Hh = 400, 460
CX, EYE_Y, SPACING = 200, 200, 60


def canvas(bg):
    return np.tile(np.array(bg, np.uint8), (Hh, W, 1))


def face(a, skin, ears=None, ink=None, iris=(70, 160, 70)):
    for y in range(120, 331):
        if y <= 270:
            hw = 50
        elif y <= 300:
            hw = round(50 - (50 - 3) * (y - 270) / 30)
        else:
            hw = 20
        a[y, CX - hw:CX + hw + 1] = skin
    if ears is not None:
        a[190:241, CX + 51:CX + 66] = ears
        a[190:241, CX - 65:CX - 50] = ears
    if ink is not None:
        a[190:241, CX + 51] = ink
        a[190:241, CX - 51] = ink
    yy, xx = np.mgrid[0:Hh, 0:W]
    for ex in (CX - SPACING // 2, CX + SPACING // 2):
        a[(yy - EYE_Y) ** 2 + (xx - ex) ** 2 <= 36] = iris
    return a


def save(a, d, name):
    p = Path(d) / name
    Image.fromarray(a).save(p)
    return p


def tapered(a, skin):
    """A face whose width changes under the eyes, so the row matters: half-width 50 to row 220, then 50 - (y - 220) // 2
    to row 270 (25), then to a 3 px chin at row 300; a 41 px neck under it."""
    for y in range(120, 331):
        hw = 50 if y <= 220 else 50 - (y - 220) // 2 if y <= 270 else round(25 - 22 * (y - 270) / 30) if y <= 300 else 20
        a[y, CX - hw:CX + hw + 1] = skin
    yy, xx = np.mgrid[0:Hh, 0:W]
    return a, yy, xx


def landmark_cases():
    """The landmark row (ROW_FRACTION of the eye line to the chin), the drawing's and a render's.
    - **a drawing** (its chin the centre run's narrowest row, 300): row round(200 + 0.2967 x 100) = 230, the face
      2 x 45 = 90 px; S6b's spacing rule's row 226 would give 94;
    - **a render with a chin-ID frame** (the face's front yellow down to row 290, the neck's skin under it unbroken,
      as a render has it): chin 290, row round(200 + 0.2967 x 90) = 227, the face 2 x 47 = 94 px; and the same with the
      yellow shaded (200, 190, 40) and as the client draws it (227, 217, 113); a chin-ID frame with no front stops;
    - **a render without a chin-ID frame:** S6b's spacing rule (row 226), as before."""
    out = []
    box = (0, 0, W, Hh)
    with tempfile.TemporaryDirectory() as d:
        a, yy, xx = tapered(canvas((240, 240, 240)), (241, 183, 148))
        for ex in (CX - SPACING // 2, CX + SPACING // 2):
            a[(yy - EYE_Y) ** 2 + (xx - ex) ** 2 <= 36] = (60, 150, 60)
        a[60:141, 120:281] = (152, 72, 43)  # hair, as the drawing case
        r, _ = D.measure(save(a, d, "tapered.png"), box)
        out += [("landmark, drawing: chin row", r["chin_row"], 300, 0), ("landmark, drawing: cheek row", r["cheek_row"], 230, 0),
                ("landmark, drawing: cheek width px", r["cheek_width_px"], 90, 0), ("landmark, drawing: face over eyes", r["face_over_eyes"], round(90 / 60, 3), 0.001)]
        grey, rskin = (120, 138, 160), (232, 182, 152)
        f = np.tile(np.array(grey, np.uint8), (Hh, W, 1))
        for y in range(120, 400):  # the render: the face's skin runs on into the neck at the midline
            hw = 50 if y <= 220 else 50 - (y - 220) // 2 if y <= 270 else 25 if y <= 290 else 20
            f[y, CX - hw:CX + hw + 1] = rskin
        for ex in (CX - SPACING // 2, CX + SPACING // 2):
            f[(yy - EYE_Y) ** 2 + (xx - ex) ** 2 <= 36] = (70, 160, 70)
        frame = save(f, d, "render.png")
        for label, yellow in (("", (255, 255, 0)), (", shaded yellow", (200, 190, 40)), (", the client's yellow", (227, 217, 113))):
            c = f.copy()
            front = np.zeros(f.shape[:2], bool)
            front[120:291] = (f[120:291] == rskin).all(axis=2)
            c[front] = yellow
            r, _ = D.face_render(frame, box=box, chin_frame=save(c, d, "chin.png"))
            out += [(f"landmark, render{label}: chin row", r["chin_row"], 290, 0), (f"landmark, render{label}: cheek row", r["cheek_row"], 227, 0),
                    (f"landmark, render{label}: cheek width px", r["cheek_width_px"], 94, 0)]
        r, _ = D.face_render(frame, box=box)
        out += [("render without a chin-ID frame: S6b's spacing row", (r["row_rule"], r["cheek_row"]), ("spacing", 226), None)]
        try:
            D.face_render(frame, box=box, chin_frame=frame)
            stopped = False
        except SystemExit:
            stopped = True
        out += [("a chin-ID frame with no chin stops the measure (no fallback to the drawing's search)", stopped, True, None)]
    return out


def main():
    checks = []
    box = (0, 0, W, Hh)
    with tempfile.TemporaryDirectory() as d:
        # A drawing: Cora's colours, an ink line before each ear.
        skin, hair, paper, ink = (241, 183, 148), (152, 72, 43), (240, 240, 240), (20, 20, 20)
        a = face(canvas(paper), skin, ears=skin, ink=ink, iris=(60, 150, 60))
        a[60:141, 120:281] = hair
        r, _ = D.measure(save(a, d, "drawing.png"), box)
        checks += [("drawing: cheek width px", r["cheek_width_px"], 100, 0), ("drawing: eye spacing px", r["eye_spacing_px"], 60, 0),
                   ("drawing: face over eyes", r["face_over_eyes"], round(100 / 60, 3), 0.001), ("drawing: cheek row (landmark: 0.2967 of eye 200 to chin 300)", r["cheek_row"], 230, 0),
                   ("drawing: chin row", r["chin_row"], 300, 0), ("drawing: hair body over eyes", r["body_over_eyes"], round(160 / 60, 3), 0.001)]
        # A render (image_spread.py): the no-hair frame, ears joined to the face; the all-hair ID.
        grey, rskin = (120, 138, 160), (232, 182, 152)
        nohair = face(canvas(grey), rskin, ears=rskin)
        look = nohair.copy()
        look[60:141, 120:281] = (110, 60, 40)
        idp = nohair.copy()
        idp[60:141, 120:281] = (0, 255, 0)
        r, _ = D.render(save(look, d, "look.png"), save(idp, d, "id.png"), box=box, face=save(nohair, d, "none.png"))
        checks += [("render: cheek width px (ears joined, taken in)", r["cheek_width_px"], 130, 0), ("render: eye spacing px", r["eye_spacing_px"], 60, 0),
                   ("render: hair body over eyes", r["body_over_eyes"], round(160 / 60, 3), 0.001)]
        # The acceptance (face_render): the no-hair frame with the ear-ID copy.
        eid = face(canvas(grey), rskin, ears=(225, 30, 225))
        # render() (image_spread.py) given that ear-ID frame as its face: its cheek path stops at the ears too, so
        # the hair body over the cheek compares like with like (the drawing's cheek has no ears in it).
        look_e, id_e = eid.copy(), eid.copy()
        look_e[60:141, 120:281] = (110, 60, 40)
        id_e[60:141, 120:281] = (0, 255, 0)
        r, _ = D.render(save(look_e, d, "look_e.png"), save(id_e, d, "id_e.png"), box=box, face=save(eid, d, "none_e.png"))
        checks += [("render with the ear-ID frame: cheek width px (ears masked)", r["cheek_width_px"], 100, 0), ("render with the ear-ID frame: hair body over cheek", r["body"], round(160 / 100, 3), 0.001),
                   ("render with the ear-ID frame: hair body over eyes", r["body_over_eyes"], round(160 / 60, 3), 0.001)]
        r, _ = D.face_render(save(eid, d, "earid.png"), box=box)
        checks += [("face_render: cheek width px (ears masked)", r["cheek_width_px"], 100, 0), ("face_render: face over eyes", r["face_over_eyes"], round(100 / 60, 3), 0.001),
                   ("face_render: ear on the cheek row", r["ear_on_cheek_row"], True, 0)]
        # Shaded ears (the ID's magenta under light and shade) still stop the run.
        eid2 = face(canvas(grey), rskin, ears=(150, 40, 170))
        r, _ = D.face_render(save(eid2, d, "earid2.png"), box=box)
        checks += [("face_render: shaded ears masked", r["cheek_width_px"], 100, 0)]
        # No ears on the cheek row: the same face.
        noear = face(canvas(grey), rskin)
        r, _ = D.face_render(save(noear, d, "noear.png"), box=box)
        checks += [("face_render: no ears", r["cheek_width_px"], 100, 0), ("face_render: no ear on the row", r["ear_on_cheek_row"], False, 0)]
    checks += landmark_cases()
    bad = 0
    for label, got, want, tol in checks:
        ok = got == want if isinstance(want, (bool, tuple)) else abs(got - want) <= tol + 1e-9
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {got} (known {want})")
    print("drawing_spread_selftest:", "PASS" if not bad else f"{bad} FAILED")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
