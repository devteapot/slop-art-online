#!/usr/bin/env python3
"""Is a front face square to the viewer? The same check on Cora's drawing and on the game's front frames, so the
band's source and the measured frames are known to share a pose (the GC, 2026-11-21: bind is the acceptance pose;
the laptop's known answer for it is hair-mirror's mirror pair, 201/201 px in bind).

**What it measures** on a front face, its skin and its two eyes (drawing_spread.py's: `classify` on the drawing,
`face_render`'s skin less the ear-ID's ears on a frame with no hair):
- **the face's axis:** the middle of the face's run of skin (the run holding the eyes' middle column) on every row
  from the cheek row (drawing_spread's, 0.030 m under the eye line) to 3 rows above the chin; the axis is the median
  of those middles. The lower face: on the drawing no hair covers it there, and on a frame no ear joins it;
- **`eyes_off`:** the eyes' middle (iris centre to iris centre) less the axis, in pixels and over the eye spacing.
  A head turned about its neck (yaw) carries the eyes across the face's outline: hair-mirror's +12.8 px at idle 2.0 s,
  +0.5 in bind, at an eye spacing of about 60 px;
- **`eyes_tilt_deg`:** the eye line's tilt (the second eye's height less the first's, over their spacing): a head
  leaning to one side (roll);
- **`midline_tilt_deg`** (reported, not held): the slope of the row middles against the rows. It is not the lean: a
  leaned oval's chord middles follow its conjugate diameter (the selftest's 5 degrees read 2.3);
- **`outline_mismatch`:** the lower face's mask (the same rows) mirrored about the axis against itself: the pixels in
  exactly one over the pixels in either. A face whose two cheeks bulge alike is 0.

**Square** (proposed, the numbers are reported either way): |eyes_off| at most 0.03 of the eye spacing, the eye line
within 1.5 degrees, outline_mismatch at most 0.05.

    python3 square.py drawing                        # both drawing sources (drawing_spread.SOURCES)
    python3 square.py frame FRAME.png [FRAME ...]    # game front frames with no hair, ear-ID types (face2d.py)
Prints one JSON line each; `pose` is read from pose.txt beside a frame's folder when there is one, else from an
idle shot's file name (S6b's frames, `…clip-idle@2-0…`).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "s6"))
import drawing_spread as D  # noqa: E402

EYES_OFF = 0.03
TILT_DEG = 1.5
MISMATCH = 0.05


def runs(skin, cx, rows):
    """Each row's run of skin through column cx: {row: (x0, x1)}; rows where cx is not skin are left out."""
    w = skin.shape[1]
    out = {}
    for y in rows:
        if not skin[y, cx]:
            continue
        x0 = x1 = cx
        while x0 > 0 and skin[y, x0 - 1]:
            x0 -= 1
        while x1 < w - 1 and skin[y, x1 + 1]:
            x1 += 1
        out[y] = (x0, x1)
    return out


def square(skin, eyes):
    """The module's measures for a skin mask and the two eyes' centres ((y, x), (y, x))."""
    (ya, xa), (yb, xb) = sorted(eyes, key=lambda e: e[1])
    eye_y, spacing, ex = (ya + yb) / 2, abs(xb - xa), (xa + xb) / 2
    cx = int(round(ex))
    chin, cheek_row, _, head_px = D.cheek_at(skin, eye_y, spacing, cx, skin.shape[1], rule="spacing")  # its rows as first defined
    rr = runs(skin, cx, range(cheek_row, chin - 3))
    ys = np.array(sorted(rr), float)
    mids = np.array([(rr[y][0] + rr[y][1]) / 2 for y in sorted(rr)])
    axis = float(np.median(mids))
    slope = np.polyfit(ys, mids, 1)[0] if len(ys) > 2 else 0.0
    m = np.zeros_like(skin)
    for y, (x0, x1) in rr.items():
        m[y, x0:x1 + 1] = True
    yy, xx = np.nonzero(m)
    xm = np.round(2 * axis - xx).astype(int)
    ok = (xm >= 0) & (xm < m.shape[1])
    mm = np.zeros_like(m)
    mm[yy[ok], xm[ok]] = True
    off = ex - axis
    res = dict(eye_spacing_px=round(float(spacing), 1), axis_px=round(axis, 1), eyes_mid_px=round(float(ex), 1), eyes_off_px=round(float(off), 1),
               eyes_off=round(float(off / spacing), 4), midline_tilt_deg=round(float(np.degrees(np.arctan(slope))), 2),
               eyes_tilt_deg=round(float(np.degrees(np.arctan2(yb - ya, xb - xa))), 2), outline_mismatch=round(float((m ^ mm).sum() / (m | mm).sum()), 4),
               rows=[cheek_row, chin - 3], chin_row=int(chin))
    res["square"] = bool(abs(res["eyes_off"]) <= EYES_OFF and abs(res["eyes_tilt_deg"]) <= TILT_DEG and res["outline_mismatch"] <= MISMATCH)
    return res


def of_drawing(path, box):
    a = np.asarray(Image.open(path).convert("RGB").crop(box)).astype(float)
    kind = D.classify(a)
    return square(kind == "skin", D.two_eyes(kind == "iris"))


def of_frame(frame, box=(600, 160, 1000, 620)):
    """A game front frame with no hair, its type the ear-ID copy (as face_render)."""
    a = np.asarray(Image.open(frame).convert("RGB").crop(box)).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    skin = (r > g + 12) & (r > b + 25) & ~D.ears_of(a)
    return square(skin, D.two_eyes((g > r + 8) & (g > b)))


def pose_of(frame):
    for d in Path(frame).resolve().parents:
        if (d / "pose.txt").exists():
            return (d / "pose.txt").read_text().strip()
    return "idle" if "clip-idle@2-0" in Path(frame).name else "unrecorded"  # S6b's frames: the shot's name holds the clip


def main():
    if sys.argv[1] == "drawing":
        for name, path, box in D.SOURCES:
            print(json.dumps(dict(source=name, pose="the drawing", **of_drawing(path, box))))
    else:
        for f in sys.argv[2:]:
            print(json.dumps(dict(source=f, pose=pose_of(f), **of_frame(f))))


if __name__ == "__main__":
    main()
