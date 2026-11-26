#!/usr/bin/env python3
"""Known-answer test for square.py (PLAN.md §7): synthetic front faces of known pose, through both of its paths (the
drawing's colours and `classify`; a frame's colours with an ear-ID ear), must come back with the offset and tilts they
were drawn with.

The face: an ellipse of skin (half-width 70 px, half-height 95 px) on a plain ground, two green eyes 60 px apart.
- **square:** eyes_off 0, the eye line level, mismatch near 0 -> square;
- **eyes moved 6 px** (a turned head carries the eyes across the outline): eyes_off 6 px (0.1 of the spacing) -> not
  square;
- **leaned 5 degrees** (the whole drawing turned about the face's middle): the eye line at 5 degrees -> not square
  (the row middles' slope reads 2.3 here: a leaned oval's chord middles follow its conjugate diameter, not its axis,
  so square.py reports that slope but does not hold it);
- **one cheek fuller** (the right half 10% wider below the eyes): mismatch over 0.05 -> not square;
- **a frame with a magenta ear** joined to the cheek: the same as square (the ear is masked).
Exit status 1 on any failure.
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import square  # noqa: E402

W, H = 400, 460
CX, CY = 200, 230


def face(skin, ground, eye, dx=0, lean=0.0, fuller=1.0, ear=None):
    im = Image.new("RGB", (W, H), ground)
    d = ImageDraw.Draw(im)
    a = np.asarray(im).copy()
    yy, xx = np.mgrid[0:H, 0:W]
    rx = np.where((xx > CX) & (yy > CY - 30), 70 * fuller, 70)
    a[((xx - CX) / rx) ** 2 + ((yy - CY) / 95) ** 2 <= 1] = skin
    im = Image.fromarray(a)
    d = ImageDraw.Draw(im)
    for ex in (CX - 30 + dx, CX + 30 + dx):
        d.ellipse((ex - 7, CY - 40 - 6, ex + 7, CY - 40 + 6), fill=eye)
    if ear:
        d.rectangle((CX - 90, CY - 40, CX - 71, CY + 10), fill=ear)  # touching the cheek's outline at its widest
    if lean:
        im = im.rotate(lean, center=(CX, CY), resample=Image.BICUBIC, fillcolor=ground)
    return im


def main():
    checks = []
    draw = dict(skin=(241, 183, 148), ground=(240, 240, 240), eye=(90, 140, 90))
    frame = dict(skin=(225, 170, 140), ground=(120, 120, 130), eye=(60, 130, 60))
    with tempfile.TemporaryDirectory() as tmp:
        for path_name, kw in (("drawing", draw), ("frame", frame)):
            for label, opts, want in (("square", {}, dict(eyes_off_px=(0, 1), eyes_tilt_deg=(0, 0.5), outline_mismatch=(0, 0.02), square=True)),
                                      ("eyes moved 6 px", dict(dx=6), dict(eyes_off_px=(6, 1), eyes_off=(0.1, 0.02), square=False)),
                                      ("leaned 5 degrees", dict(lean=5.0), dict(eyes_tilt_deg=(5, 0.8), square=False)),
                                      ("one cheek fuller", dict(fuller=1.10), dict(square=False)),
                                      ) + ((("a joined ear, masked", dict(ear=(220, 40, 220)), dict(eyes_off_px=(0, 1), square=True)),) if path_name == "frame" else ()):
                im = face(**kw, **opts)
                p = Path(tmp) / f"{path_name}-{label}.png"
                im.save(p)
                if path_name == "drawing":
                    r = square.of_drawing(p, (0, 0, W, H))
                else:
                    big = Image.new("RGB", (1600, 900), kw["ground"])
                    big.paste(im, (600, 160))
                    big.save(p)
                    r = square.of_frame(p)
                for k, w in want.items():
                    if isinstance(w, bool):
                        checks.append((f"{path_name}, {label}: {k}", r[k], w, None))
                    else:
                        got = r[k]
                        if opts.get("lean") and "tilt" in k:
                            got = abs(got)  # image y runs down: the sign depends on the image's frame
                        checks.append((f"{path_name}, {label}: {k}", got, w[0], w[1]))
                if label == "one cheek fuller":
                    checks.append((f"{path_name}, {label}: outline_mismatch over 0.05", r["outline_mismatch"] > 0.05, True, None))
    bad = 0
    for label, got, want, tol in checks:
        ok = got == want if tol is None else abs(got - want) <= tol
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {got} (known {want}{'' if tol is None else f' ± {tol}'})")
    print("square_selftest:", "PASS" if not bad else f"{bad} FAILED", f"({len(checks)} checks)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
