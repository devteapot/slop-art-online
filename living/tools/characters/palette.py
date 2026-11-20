#!/usr/bin/env python3
"""The hair palette relative to a person's hair tag (contract v1.3, docs/HANDMADE_COMPOSED.md,
"The palette relative to the hair tag"): the same maths as the client's
`living/game/src/characters/palette.rs`, for the audit (`calibrate.py`) and for authors.

    python3 living/tools/characters/palette.py --self-test
    python3 living/tools/characters/palette.py PROFILE.json [#rrggbb ...]   # a profile's entries

PROFILE.json is a `slop.hair` object (or a material's `slop`, or a file's material extras). Each
swatch is moved from `ref` to a tag colour in OKLCh: lightness and chroma by their ratios to the
reference's (clamped to 0..4; chroma against at least 0.02), hue by its offset (0 when either is
grey), then into the sRGB gamut by lowering chroma alone (24 bisection steps), rounded
floor(255x + 0.5). Several anchors mix their ratios by 1 / (ΔE² + 1e-4); at an anchor's reference
(ΔE < 0.001) its own swatches. Plain Python.
"""

import json
import math
import sys

GREY_C = 0.02
MAX_RATIO = 4.0
HAIR_COLOURS = dict(black="#131111", dark_brown="#201814", brown="#332217", chestnut="#4a2b1a", auburn="#662e1a", sandy="#7a5730", blond="#9e7d47", grey="#858585", white="#c7c7c2")
ROWS = ("shade", "mid", "light", "highlight", "ink")


def lin(c):
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def enc(x):
    x = min(max(x, 0.0), 1.0)
    s = 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
    return min(255, max(0, math.floor(255 * s + 0.5)))


def oklab(c):
    r, g, b = (lin(v) for v in c)
    l_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m_ = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l_, m_, s_))
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_, 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_, 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def from_oklab(L, a, b):
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_, -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_, -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)


def oklch(c):
    L, a, b = oklab(c)
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def ratios(r, s):
    lr, cr, hr = oklch(r)
    ls, cs, hs = oklch(s)
    kl = min(max(ls / lr, 0.0), MAX_RATIO) if lr > 0 else 1.0
    kc = min(max(cs / max(cr, GREY_C), 0.0), MAX_RATIO)
    dh = ((hs - hr + 180) % 360) - 180 if cr >= GREY_C and cs >= GREY_C else 0.0
    return kl, kc, dh


def clamped(r, s):
    lr, cr, _ = oklch(r)
    ls, cs, _ = oklch(s)
    return (lr > 0 and ls / lr > MAX_RATIO) or cs / max(cr, GREY_C) > MAX_RATIO


def apply(tag, rt):
    lt, ct, ht = oklch(tag)
    kl, kc, dh = rt
    L, C, h = min(lt * kl, 1.0), kc * ct, math.radians(ht + dh)

    def rgb(c):
        return from_oklab(L, c * math.cos(h), c * math.sin(h))

    def ok(c):
        return all(-1e-6 <= x <= 1 + 1e-6 for x in c)

    out, reduced = rgb(C), False
    if not ok(out):
        reduced, lo, hi = True, 0.0, C
        for _ in range(24):
            mid = (lo + hi) / 2
            if ok(rgb(mid)):
                lo = mid
            else:
                hi = mid
        out = rgb(lo)
    return tuple(enc(x) for x in out), reduced


def shade_ink(shade):
    return tuple(enc(lin(v) * 0.6) for v in shade)


def anchors_of(h):
    """The profile's anchors (its own first) as (ref, [shade, mid, light, highlight], ink or None)."""
    own = (tuple(h["ref"]), [tuple(h[k]) for k in ROWS[:4]], tuple(h["ink"]) if isinstance(h.get("ink"), list) else None)
    return [own] + [(tuple(a["ref"]), [tuple(a[k]) for k in ROWS[:4]], tuple(a["ink"]) if isinstance(a.get("ink"), list) else None) for a in h.get("anchors", [])[:4]]


def entry(anchors, tag):
    """(the five rows, which rows were brought into gamut)."""
    t = oklab(tag)

    def dist(a):
        r = oklab(a[0])
        return math.dist(t, r)

    for a in anchors:
        if dist(a) < 1e-3:
            return list(a[1]) + [a[2] or shade_ink(a[1][0])], []
    ws = [(1 / (dist(a) ** 2 + 1e-4), a) for a in anchors]
    total = sum(w for w, _ in ws)
    rows, reduced = [], []
    for row in range(5):
        kl = kc = dh = 0.0
        for w, a in ws:
            s = a[1][row] if row < 4 else (a[2] or shade_ink(a[1][0]))
            r = ratios(a[0], s)
            kl, kc, dh = kl + w * r[0], kc + w * r[1], dh + w * r[2]
        c, red = apply(tag, (kl / total, kc / total, dh / total))
        rows.append(c)
        if red:
            reduced.append(ROWS[row])
    return rows, reduced


def hexed(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def self_test():
    cora = {"ref": [102, 46, 26], "shade": [44, 8, 2], "mid": [104, 37, 8], "light": [119, 43, 6], "highlight": [135, 47, 3], "ink": [4, 0, 0]}
    a = anchors_of(cora)
    want = {
        "#662e1a": [(44, 8, 2), (104, 37, 8), (119, 43, 6), (135, 47, 3), (4, 0, 0)],
        "#131111": [(3, 3, 3), (18, 16, 16), (22, 19, 19), (26, 23, 23), (0, 0, 0)],
        "#9e7d47": [(70, 47, 12), (156, 117, 48), (176, 134, 53), (199, 149, 55), (9, 3, 0)],
        "#858585": [(53, 53, 53), (127, 127, 127), (144, 144, 144), (161, 161, 161), (4, 4, 4)],
    }
    ok = True
    for tag, rows in want.items():
        got, _ = entry(a, hexed(tag))
        print(f"  {tag}: {got}{'' if got == rows else '  WANT ' + str(rows)}")
        ok &= got == rows
    print("palette self-test:", "PASS" if ok else "FAIL")
    return ok


def main():
    if "--self-test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    h = json.load(open(sys.argv[1]))
    h = h.get("slop", h).get("hair", h.get("slop", h))
    tags = sys.argv[2:] or list(HAIR_COLOURS.values())
    for t in tags:
        rows, red = entry(anchors_of(h), hexed(t))
        print(f"{t}: " + ", ".join(f"{n} {c}" for n, c in zip(ROWS, rows)) + (f"  (gamut: {', '.join(red)})" if red else ""))


if __name__ == "__main__":
    main()
