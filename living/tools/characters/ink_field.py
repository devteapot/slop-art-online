#!/usr/bin/env python3
"""Ink distance fields for hand-made characters: the hair's lock lines (docs/HANDMADE_HAIR.md,
"Lock ink lines", v1.1) and any material's ink map (docs/HANDMADE_INK.md, v1.2).

    python3 living/tools/characters/ink_field.py LINES.png STEM.hair.png [--range 0.004]
                                                 [--seams-as-lines --glb FILE.glb [--material NAME]]
                                                 [--size WxH]
    python3 living/tools/characters/ink_field.py LINES.png|STROKES.json STEM.SLOT.ink.png [--range R]
                                                 [--width W.png] [--size WxH]
                                                 [--seams-as-lines --glb FILE.glb --material NAME]

**The layout** follows the output's name (`--layout hair|ink` overrides): `*.ink.png` gets the
ink layout (v1.2), anything else the hair's (v1.1, below).

**The ink layout (v1.2):** G as below, the distance to the nearest stroke centreline over
`range`; **R** the width of the stroke whose centreline is nearest (a nearest-point fill: every
texel carries it, so bilinear filtering across a line reads that stroke's own width), 255 without
a width source; B 0. What R means is the material's: in `"px"` mode with `taper` the width
fraction, in `"uv"` mode the half-width over `range` (docs/HANDMADE_INK.md, "The map"). Sources:

- `LINES.png` as below, with `--width W.png` (greyscale, the same size): the value under each
  centreline texel is that point's R.
- `STROKES.json`, exact centrelines: `{"size": [W, H], "strokes": [{"points": [[u, v, f], ...]},
  ...]}`, polylines in glTF UV (top-left origin), `f` (0-1) the R at each point, interpolated
  along each segment. d is the exact distance from each texel's centre to the nearest segment,
  and R the interpolated `f` at that nearest point; a tapered tip is a point with `f` 0.
  `--size` overrides `"size"`.

**The hair layout (v1.1):**

LINES.png holds the painted lock lines, dark on light, at the hair texture's resolution, in the
hair's TEXCOORD_0 (glTF's top-left origin, as Blender exports the image): a pixel is on a line
where its luminance is below half (or its alpha, if it has one, is above half and it is dark).
Paint lines one or two texels wide: the field measures from line texels, and the client draws the
line's width in screen pixels around them, so a wide painted line draws wide when close.

STEM.hair.png gets, in **G**, the exact Euclidean distance from each texel's centre to the
nearest line texel's centre, in UV units (a texel is 1/width across and 1/height down), encoded as
G = round(255 × min(1, d / range)): 0 on a line, 255 at `range` or further (no ink). **R** is kept
from the existing file (the highlight mask), or 0 for a new file; **B** is 0. `range` must be the
material's `slop.hair.ink_range`; the tool prints the line to put in the extras.

`--seams-as-lines` adds the borders of the hair's UV islands (edges used by one triangle only)
as lines, rasterized from `--glb` (the hair primitives: the materials whose `slop.slot` is
"hair", else those named `…_HAIR`, else `--material`). LINES.png may then be `-`, with the size
from `--size`, an existing STEM.hair.png, or the GLB's hair texture.

Plain Python, no dependencies: the transform is Felzenszwalb and Huttenlocher's exact squared
distance transform, by columns then rows (a few seconds for 1024x1024).
"""

import argparse
import json
import math
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calibrate import accessor, read_glb, read_png  # noqa: E402

INF = float("inf")


def write_png(path, w, h, rows):
    """An 8-bit RGB PNG; `rows` are h bytearrays of w*3 bytes."""
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def dt1(f, pos):
    """The 1D squared distance transform of samples f at positions pos (increasing):
    d[p] = min_q f[q] + (pos[p] - pos[q])^2 (Felzenszwalb & Huttenlocher, 2012)."""
    n = len(f)
    d = [INF] * n
    v = [0] * n
    z = [0.0] * (n + 1)
    k = -1
    for q in range(n):
        if f[q] == INF:
            continue
        if k < 0:
            k = 0
            v[0] = q
            z[0], z[1] = -INF, INF
            continue
        while True:
            r = v[k]
            s = ((f[q] + pos[q] * pos[q]) - (f[r] + pos[r] * pos[r])) / (2 * (pos[q] - pos[r]))
            if s <= z[k]:
                k -= 1
                if k < 0:
                    break
            else:
                break
        k += 1
        v[k] = q
        z[k] = s if k > 0 else -INF
        z[k + 1] = INF
    if k < 0:
        return d
    j = 0
    for p in range(n):
        while z[j + 1] < pos[p]:
            j += 1
        r = v[j]
        d[p] = f[r] + (pos[p] - pos[r]) ** 2
    return d


def dt1_arg(f, pos):
    """dt1 that also returns, for each sample, the index of the sample its minimum came from."""
    n = len(f)
    d = [INF] * n
    arg = [-1] * n
    v = [0] * n
    z = [0.0] * (n + 1)
    k = -1
    for q in range(n):
        if f[q] == INF:
            continue
        if k < 0:
            k = 0
            v[0] = q
            z[0], z[1] = -INF, INF
            continue
        while True:
            r = v[k]
            s = ((f[q] + pos[q] * pos[q]) - (f[r] + pos[r] * pos[r])) / (2 * (pos[q] - pos[r]))
            if s <= z[k]:
                k -= 1
                if k < 0:
                    break
            else:
                break
        k += 1
        v[k] = q
        z[k] = s if k > 0 else -INF
        z[k + 1] = INF
    if k < 0:
        return d, arg
    j = 0
    for p in range(n):
        while z[j + 1] < pos[p]:
            j += 1
        r = v[j]
        d[p] = f[r] + (pos[p] - pos[r]) ** 2
        arg[p] = r
    return d, arg


def nearest_uv(line, w, h):
    """The exact distance (UV units) from each texel to the nearest line texel, and that texel's
    index (y * w + x): the distance transform with its nearest feature kept."""
    xs = [i / w for i in range(w)]
    ys = [j / h for j in range(h)]
    cols = []
    for x in range(w):
        cd, ca = dt1_arg([0.0 if line[y * w + x] else INF for y in range(h)], ys)
        cols.append((cd, ca))
    dist = [INF] * (w * h)
    near = [-1] * (w * h)
    for y in range(h):
        rd, ra = dt1_arg([cols[x][0][y] for x in range(w)], xs)
        for x in range(w):
            q = ra[x]
            if q >= 0:
                dist[y * w + x] = math.sqrt(rd[x])
                near[y * w + x] = cols[q][1][y] * w + q
    return dist, near


def stroke_field(strokes, w, h, rng):
    """The exact distance (UV) from each texel centre to the nearest stroke segment within `rng`,
    and the stroke's `f` interpolated at that nearest point (INF and 1 beyond)."""
    dist = [INF] * (w * h)
    width = [1.0] * (w * h)
    segs = 0
    for st in strokes:
        pts = st["points"]
        for (u0, v0, f0), (u1, v1, f1) in zip(pts, pts[1:]):
            segs += 1
            du, dv = u1 - u0, v1 - v0
            ll = du * du + dv * dv
            x0 = max(int((min(u0, u1) - rng) * w) - 1, 0)
            x1 = min(int((max(u0, u1) + rng) * w) + 2, w)
            y0 = max(int((min(v0, v1) - rng) * h) - 1, 0)
            y1 = min(int((max(v0, v1) + rng) * h) + 2, h)
            for y in range(y0, y1):
                pv = (y + 0.5) / h
                for x in range(x0, x1):
                    pu = (x + 0.5) / w
                    t = 0.0 if ll == 0 else max(0.0, min(1.0, ((pu - u0) * du + (pv - v0) * dv) / ll))
                    eu, ev = pu - (u0 + du * t), pv - (v0 + dv * t)
                    d = math.sqrt(eu * eu + ev * ev)
                    i = y * w + x
                    if d < dist[i]:
                        dist[i] = d
                        width[i] = f0 + (f1 - f0) * t
    return dist, width, segs


def ink_layout(a):
    """Write a v1.2 ink map (G the distance, R the width; docs/HANDMADE_INK.md)."""
    strokes = None
    if a.lines.endswith(".json"):
        spec = json.loads(open(a.lines).read())
        strokes = spec.get("strokes") or sys.exit(f"ink_field: {a.lines} has no strokes")
        for k, st in enumerate(strokes):
            pts = st.get("points", [])
            if len(pts) < 2 or any(len(q) != 3 or not all(isinstance(c, (int, float)) for c in q) for q in pts):
                sys.exit(f"ink_field: stroke {k} of {a.lines}: points must be two or more [u, v, f]")
            if any(not 0 <= q[2] <= 1 for q in pts):
                sys.exit(f"ink_field: stroke {k} of {a.lines}: f must be 0-1")
        size = a.size or ("x".join(str(int(v)) for v in spec["size"]) if "size" in spec else None)
        if not size:
            sys.exit("ink_field: give the map's size (\"size\" in the strokes, or --size)")
        w, h = (int(v) for v in size.lower().split("x"))
        dist, width, segs = stroke_field(strokes, w, h, a.range)
        if a.seams_as_lines:
            sys.exit("ink_field: --seams-as-lines takes LINES.png or -, not strokes")
        src = f"{len(strokes)} strokes, {segs} segments"
    else:
        if a.lines != "-":
            lw, lh, lch, lrows = read_png(a.lines)
            w, h = lw, lh
        elif a.size:
            w, h = (int(v) for v in a.size.lower().split("x"))
        else:
            sys.exit("ink_field: give LINES.png or --size")
        line = [False] * (w * h)
        if a.lines != "-":
            for y in range(h):
                r = lrows[y]
                for x in range(w):
                    px = r[x * lch : x * lch + lch]
                    lum = px[0] if lch < 3 else (0.299 * px[0] + 0.587 * px[1] + 0.114 * px[2])
                    alpha = px[-1] if lch in (2, 4) else 255
                    line[y * w + x] = lum < 128 and alpha >= 128
        edges = seams(a.glb, a.material, w, h, line) if a.seams_as_lines else 0
        if a.seams_as_lines and not a.glb:
            sys.exit("ink_field: --seams-as-lines needs --glb")
        if not any(line):
            sys.exit("ink_field: no line texels (lines are dark on light)")
        dist, near = nearest_uv(line, w, h)
        width = [1.0] * (w * h)
        if a.width:
            ww, wh, wch, wrows = read_png(a.width)
            if (ww, wh) != (w, h):
                sys.exit(f"ink_field: --width is {ww}x{wh}, the lines are {w}x{h}")
            for i, q in enumerate(near):
                if q >= 0:
                    width[i] = wrows[q // w][(q % w) * wch] / 255
        src = f"{sum(line)} line texels" + (f", {edges} UV seam edges" if a.seams_as_lines else "") + (f", widths from {a.width}" if a.width else "")
    rows = []
    widths = False
    for y in range(h):
        row = bytearray(w * 3)
        for x in range(w):
            i = y * w + x
            row[3 * x] = min(255, max(0, round(255 * width[i])))
            row[3 * x + 1] = min(255, round(255 * min(1.0, dist[i] / a.range)))
            widths |= row[3 * x] != 255
        rows.append(row)
    write_png(a.out, w, h, rows)
    near_pct = 100 * sum(1 for v in dist if v < a.range) / (w * h)
    on = sum(1 for r in rows for x in range(w) if r[3 * x + 1] == 0)
    print(f"ink_field: {a.out}: {w}x{h} ink layout from {src}; {on} texels on a centreline, {near_pct:.1f}% within range {a.range}; R {'the widths' if widths else '255 (no width source)'}")
    print(f'ink_field: put "range": {a.range} in the material\'s extras.slop.ink (it must match --range)')


def distance_uv(line, w, h):
    """Exact Euclidean distance (UV units) from each texel to the nearest line texel."""
    xs = [i / w for i in range(w)]
    ys = [j / h for j in range(h)]
    cols = [[0.0 if line[y * w + x] else INF for y in range(h)] for x in range(w)]
    cols = [dt1(c, ys) for c in cols]
    out = [0.0] * (w * h)
    for y in range(h):
        row = dt1([cols[x][y] for x in range(w)], xs)
        for x in range(w):
            out[y * w + x] = math.sqrt(row[x])
    return out


def hair_primitives(j, material):
    mats = j.get("materials", [])

    def pick(test):
        return [p for m in j.get("meshes", []) for p in m["primitives"] if "material" in p and test(mats[p["material"]])]

    if material:
        return pick(lambda m: m.get("name") == material)
    return pick(lambda m: m.get("extras", {}).get("slop", {}).get("slot") == "hair") or pick(lambda m: "_HAIR" in m.get("name", ""))


def seams(glb, material, w, h, line):
    """Rasterize the hair's UV island borders into `line`; returns how many edges."""
    j, binary = read_glb(glb)
    prims = hair_primitives(j, material)
    if not prims:
        sys.exit(f"ink_field: no hair primitives in {glb} (give --material)")
    n = 0
    for p in prims:
        uv, _ = accessor(j, binary, p["attributes"]["TEXCOORD_0"])
        if uv is None:
            sys.exit("ink_field: the hair's TEXCOORD_0 is not FLOAT")
        ia = j["accessors"][p["indices"]]
        idx = read_indices(j, binary, ia)
        us = [uv[i][0] for i in set(idx)]
        vs = [uv[i][1] for i in set(idx)]
        if (max(us) - min(us)) * (max(vs) - min(vs)) < 1e-6:
            sys.exit(f"ink_field: the hair's TEXCOORD_0 in {glb} spans no area (u {min(us):.3f}-{max(us):.3f}, v {min(vs):.3f}-{max(vs):.3f}): unwrap the hair's UVs first")
        count = {}
        for t in range(0, len(idx) - 2, 3):
            a, b, c = idx[t : t + 3]
            for e in ((a, b), (b, c), (c, a)):
                k = (min(e), max(e))
                count[k] = count.get(k, 0) + 1
        for (a, b), c in count.items():
            if c != 1:
                continue
            n += 1
            (u0, v0), (u1, v1) = uv[a], uv[b]
            x0, y0, x1, y1 = u0 * w - 0.5, v0 * h - 0.5, u1 * w - 0.5, v1 * h - 0.5
            steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
            for s in range(steps + 1):
                t = s / steps
                x, y = min(max(round(x0 + (x1 - x0) * t), 0), w - 1), min(max(round(y0 + (y1 - y0) * t), 0), h - 1)
                if 0 <= x < w and 0 <= y < h:
                    line[y * w + x] = True
    return n


def read_indices(j, binary, a):
    bv = j["bufferViews"][a["bufferView"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    fmt, size = {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4)}[a["componentType"]]
    return list(struct.unpack_from(f"<{a['count']}{fmt}", binary, start))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lines", help="painted lines (dark on light), or - with --seams-as-lines")
    ap.add_argument("out", help="STEM.hair.png (G written, R kept) or STEM.SLOT.ink.png (G and R written)")
    ap.add_argument("--layout", choices=("hair", "ink"), help="default: ink for *.ink.png, else hair")
    ap.add_argument("--width", help="ink layout: a greyscale image whose value at each line texel is its R")
    ap.add_argument("--range", type=float, default=0.004, help="the UV distance G = 255 stands for (slop.hair.ink_range)")
    ap.add_argument("--seams-as-lines", action="store_true")
    ap.add_argument("--glb")
    ap.add_argument("--material")
    ap.add_argument("--size", help="WxH when LINES is - and there is no existing output")
    a = ap.parse_args()
    if a.range <= 0:
        sys.exit("ink_field: --range must be above 0")
    if (a.layout or ("ink" if a.out.endswith(".ink.png") else "hair")) == "ink":
        return ink_layout(a)
    if a.width or a.lines.endswith(".json"):
        sys.exit("ink_field: --width and STROKES.json are for the ink layout (an output named *.ink.png, or --layout ink)")
    old = read_png(a.out) if os.path.exists(a.out) else None
    if a.lines != "-":
        lw, lh, lch, lrows = read_png(a.lines)
        w, h = lw, lh
    elif a.size:
        w, h = (int(v) for v in a.size.lower().split("x"))
    elif old:
        w, h = old[0], old[1]
    else:
        sys.exit("ink_field: give LINES.png, --size, or an existing output for the size")
    if old and (old[0], old[1]) != (w, h):
        sys.exit(f"ink_field: {a.out} is {old[0]}x{old[1]}, the lines are {w}x{h}")
    line = [False] * (w * h)
    if a.lines != "-":
        for y in range(h):
            r = lrows[y]
            for x in range(w):
                px = r[x * lch : x * lch + lch]
                lum = px[0] if lch < 3 else (0.299 * px[0] + 0.587 * px[1] + 0.114 * px[2])
                alpha = px[-1] if lch in (2, 4) else 255
                line[y * w + x] = lum < 128 and alpha >= 128
    painted = sum(line)
    edges = 0
    if a.seams_as_lines:
        if not a.glb:
            sys.exit("ink_field: --seams-as-lines needs --glb")
        edges = seams(a.glb, a.material, w, h, line)
    if not any(line):
        sys.exit("ink_field: no line texels (lines are dark on light)")
    d = distance_uv(line, w, h)
    rows = []
    for y in range(h):
        row = bytearray(w * 3)
        for x in range(w):
            r = 0
            if old:
                ow, oh, och, orows = old
                r = orows[y][x * och]
            row[3 * x] = r
            row[3 * x + 1] = min(255, round(255 * min(1.0, d[y * w + x] / a.range)))
        rows.append(row)
    write_png(a.out, w, h, rows)
    near = sum(1 for v in d if v < a.range)
    print(f"ink_field: {a.out}: {w}x{h}, {painted} painted line texels" + (f", {edges} UV seam edges" if a.seams_as_lines else "") + f"; {100 * near / (w * h):.1f}% of texels within range {a.range}; R {'kept' if old else '0 (new file)'}")
    print(f'ink_field: put "ink_range": {a.range} in the hair material\'s extras.slop.hair (it must match --range)')


if __name__ == "__main__":
    main()
