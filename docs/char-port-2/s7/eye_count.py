#!/usr/bin/env python3
"""Must-fix 1's measure (char-port-2 S7): in a frame drawn with eye_id.py's copy, the eye pixels that show (EYE's
cyan, lit or shaded: green and blue each over red by 60). A closed eye shows none. Known-answer test:
eye_count_selftest.py.

    python3 eye_count.py FRAME.png [FRAME.png ...]
"""
import json
import sys

import numpy as np
from PIL import Image


def eye_pixels(a):
    """The eye-ID pixels of an RGB array."""
    a = np.asarray(a, float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (g > r + 60) & (b > r + 60)


def count(frame):
    """(eye pixels, their rows' span): how much eye shows in the frame."""
    m = eye_pixels(Image.open(frame).convert("RGB"))
    rows = np.nonzero(m.any(axis=1))[0]
    return dict(eye_px=int(m.sum()), rows=[int(rows.min()), int(rows.max())] if len(rows) else None)


if __name__ == "__main__":
    print(json.dumps({f: count(f) for f in sys.argv[1:]}, indent=1))
