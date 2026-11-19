#!/usr/bin/env python3
"""Shimmer of a hand-made hair's lock ink lines in camera pans and zooms (docs/HANDMADE_HAIR.md,
"The calibration frame", "Ink shimmer").

    python3 living/tools/characters/hair_shimmer.py view/<file>.glb [--out DIR] [--binary PATH]
                                                    [--plain-stills DIR] [--ink-stills DIR]

The file is used as it is, with its own `extras.slop.hair` (its `ink_range`, `ink_px`,
`ink_fade_px`, `ink`) and sidecars. The reference is the same file with the ink fields taken
out of every profile (a temporary copy `view/<stem>-noink.glb`, its `.face`/`.hair` sidecars
copied, removed afterwards): the hair-only profile, highlight and all.

**Shots** (the asset view, headless, 1600x900, 11:00, the idle clip paused at 0 s or the first
clip, springs off): at each game camera stop, Near (8 m up, FOV 42°), Middle (12 m, 44°) and
Far (19 m, 46°), 58° down at the chest, a pan of 16 stills (yaw 0 to 1.5°, 0.1° a frame) and a
zoom of 16 (the height up 0.3% a frame).

**Metric.** Per frame i and pixel p, with luminance L:

- ink signal  s_i(p) = max(0, Lplain_i(p) - Link_i(p)): how much the line darkens the pixel;
- edge signal e_i(p) = |dL/dx| + |dL/dy| of the plain frame: the profile's own band and
  highlight edges.

Over the hair pixels (the hue of the plain frame where ink falls, within ±0.06, saturation above
0.2, in the box round every pixel the ink changes at that stop, 8 px wider), the flicker ratio
F = sum |x_{i+1} - 2 x_i + x_{i-1}| / sum x: a smooth camera path changes a well-drawn signal
nearly linearly over a frame, so the second temporal difference isolates what flickers or crawls
(0 is smooth, up to 4 for signal that comes and goes at random). **A sequence passes when
F_ink <= 1.5 F_edge:** the line flickers no more, per unit of what it draws, than the
antialiased band edges the profile already shows in motion, with half again for a line having two
edges to an edge's one. A sequence whose ink darkens fewer than 1 pixel a frame by more than 8
levels is not scored (the ink has faded out there): it is listed as `faded`.

Writes OUT (default `.local/living/hair-shimmer/<stem>/<time>/`): `plain/`, `ink/` (the
stills), `shimmer.json` and the table it prints. `--plain-stills`/`--ink-stills` reuse an earlier
run's still folders (each `<dir>/<stem>/NN-*.png`) instead of rendering. Plain Python.
"""

import argparse
import glob
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from calibrate import ASSETS, REPO, clips_of, read_glb  # noqa: E402
from merge_primitives import write_glb  # noqa: E402  (living/tools)

INK_KEYS = ("ink", "ink_px", "ink_range", "ink_fade_px")
STOPS = (("near", 8.0, 42.0), ("middle", 12.0, 44.0), ("far", 19.0, 46.0))
FRAMES = 16


def shots(clip):
    out = []
    for _, h, f in STOPS:
        out += [f"play:{h}:{f}@{0.1 * k:.1f}" for k in range(FRAMES)]
        out += [f"play:{h * (1 + 0.003 * k):.3f}:{f}@0" for k in range(FRAMES)]
    return ",".join(f"{clip}@0/{s}" if clip else s for s in out)


def render(glb, out, binary):
    clips = clips_of(glb)
    clip = "idle" if "idle" in clips else (clips[0] if clips else None)
    env = {k: v for k, v in os.environ.items() if not k.startswith("LIVING_GAME_")}
    env.update(LIVING_GAME_VIEW=glb, LIVING_GAME_VIEW_SHOTS=shots(clip), LIVING_GAME_VIEW_OUT=str(out), LIVING_GAME_HOUR="11", LIVING_GAME_DAY_MINUTES="0",
               LIVING_GAME_FILM="soft", LIVING_GAME_SETTINGS=str(out) + ".settings.json", LIVING_GAME_SIZE="1600x900", LIVING_GAME_SPRINGS="0", RUST_LOG="warn")
    if clip:
        env["LIVING_GAME_VIEW_CLIP"] = clip
    with open(str(out) + ".log", "w") as log:
        subprocess.run([str(binary)], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)


def plain_copy(glb):
    """The file without ink fields, beside it, with its sidecars; returns its path under assets."""
    j, binary = read_glb(ASSETS / glb)
    removed = 0
    for m in j.get("materials", []):
        h = m.get("extras", {}).get("slop", {}).get("hair")
        if isinstance(h, dict):
            for k in INK_KEYS:
                removed += h.pop(k, None) is not None
    if not removed:
        sys.exit(f"hair_shimmer: {glb} sets no ink field: nothing to compare")
    stem = glb[: -len(".glb")]
    out = stem + "-noink.glb"
    write_glb(ASSETS / out, j, bytearray(binary))
    for side in (".face.png", ".face.ktx2", ".hair.png", ".hair.ktx2"):
        if (ASSETS / (stem + side)).exists():
            shutil.copyfile(ASSETS / (stem + side), ASSETS / (stem + "-noink" + side))
    return out


def read_rgb(path, x1=None, y1=None):
    """An 8-bit RGB(A) PNG's rows 0..y1 and columns 0..x1 (all without), as (w, h, ch, rows)."""
    b = open(path, "rb").read()
    pos, idat = 8, []
    while pos < len(b):
        n = struct.unpack(">I", b[pos:pos + 4])[0]
        tag, data = b[pos + 4:pos + 8], b[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h, _, ctype = struct.unpack(">IIBB", data[:10])
        elif tag == b"IDAT":
            idat.append(data)
        pos += 12 + n
    ch = 4 if ctype == 6 else 3
    raw = zlib.decompress(b"".join(idat))
    full = w * ch
    stride = full if x1 is None else min((x1 + 1) * ch, full)
    prev, rows = bytearray(stride), []
    for y in range(h if y1 is None else min(y1 + 1, h)):
        o = y * (full + 1)
        f, line = raw[o], bytearray(raw[o + 1:o + 1 + stride])
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                line[i] = (line[i] + (((line[i - ch] if i >= ch else 0) + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                c = prev[i - ch] if i >= ch else 0
                bb = prev[i]
                p = a + bb - c
                pa, pb, pc = abs(p - a), abs(p - bb), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else (bb if pb <= pc else c))) & 255
        rows.append(line)
        prev = line
    return w, h, ch, rows


def lum_of(img, x0, x1, y0, y1):
    w, h, ch, rows = img
    return [[0.2126 * r[x * ch] + 0.7152 * r[x * ch + 1] + 0.0722 * r[x * ch + 2] for x in range(x0, x1)] for r in rows[y0:y1]]


def hsv(r, g, b):
    hi, lo = max(r, g, b), min(r, g, b)
    s = 0.0 if hi == 0 else (hi - lo) / hi
    if hi == lo:
        return 0.0, s
    if hi == r:
        hue = ((g - b) / (hi - lo)) % 6
    elif hi == g:
        hue = (b - r) / (hi - lo) + 2
    else:
        hue = (r - g) / (hi - lo) + 4
    return hue / 6, s


def flicker(X, M):
    num = den = 0.0
    for i in range(1, len(X) - 1):
        for y, row in enumerate(M):
            for x, m in enumerate(row):
                if m:
                    num += abs(X[i + 1][y][x] - 2 * X[i][y][x] + X[i - 1][y][x])
                    den += X[i][y][x]
    return num / den if den else 0.0


def score(plain_files, ink_files):
    rows = []
    for si, (stop, _, _) in enumerate(STOPS):
        for mi, move in enumerate(("pan", "zoom")):
            start = (2 * si + mi) * FRAMES
            name = f"{stop} {move}"
            # Where the ink falls: the pixels it darkens in the sequence's first and last frames.
            diff = []
            for k in (start, start + FRAMES - 1):
                p, i = read_rgb(plain_files[k]), read_rgb(ink_files[k])
                w, h = p[0], p[1]
                lp, li = lum_of(p, 0, w, 0, h), lum_of(i, 0, w, 0, h)
                diff += [(x, y) for y in range(h) for x in range(w) if lp[y][x] - li[y][x] > 2]
            if not diff:
                rows.append(dict(sequence=name, ink_px=0.0, result="faded"))
                continue
            x0, x1 = max(min(q[0] for q in diff) - 12, 1), min(max(q[0] for q in diff) + 13, w)
            y0, y1 = max(min(q[1] for q in diff) - 12, 1), min(max(q[1] for q in diff) + 13, h)
            P = [read_rgb(f, x1, y1) for f in plain_files[start:start + FRAMES]]
            I = [read_rgb(f, x1, y1) for f in ink_files[start:start + FRAMES]]
            Lp, Li = [lum_of(p, x0 - 1, x1, y0 - 1, y1) for p in P], [lum_of(i, x0 - 1, x1, y0 - 1, y1) for i in I]
            ink_px = sum(1 for k in range(FRAMES) for r_p, r_i in zip(Lp[k], Li[k]) for a, b in zip(r_p, r_i) if a - b > 8) / FRAMES
            if ink_px < 1:
                rows.append(dict(sequence=name, ink_px=round(ink_px, 1), result="faded"))
                continue
            # The hair's hue: the plain frame's median hue where the ink falls.
            c0 = P[0]
            hues = sorted(hsv(*c0[3][y][x * c0[2]:x * c0[2] + 3])[0] for x, y in diff[:4000] if y <= y1 and x <= x1)
            hue = hues[len(hues) // 2]
            M = []
            for y in range(y0 - 1, y1):
                row = []
                for x in range(x0 - 1, x1):
                    ok = y >= y0 and x >= x0
                    for p in P:
                        if not ok:
                            break
                        hh, sat = hsv(*p[3][y][x * p[2]:x * p[2] + 3])
                        d = abs(hh - hue)
                        ok = sat > 0.2 and min(d, 1 - d) < 0.06
                    row.append(ok)
                M.append(row)
            S = [[[max(0.0, a - b) for a, b in zip(rp, ri)] for rp, ri in zip(Lp[k], Li[k])] for k in range(FRAMES)]
            Ed = [[[0.0 if x == 0 or y == 0 else abs(L[y][x] - L[y][x - 1]) + abs(L[y][x] - L[y - 1][x]) for x in range(len(L[0]))] for y in range(len(L))] for L in Lp]
            fi, fe = flicker(S, M), flicker(Ed, M)
            ratio = fi / fe if fe else 0.0
            rows.append(dict(sequence=name, f_ink=round(fi, 3), f_edge=round(fe, 3), ratio=round(ratio, 2), ink_px=round(ink_px, 1), result="pass" if ratio <= 1.5 else "FAIL"))
    return rows


def stills(d):
    fs = [f for f in glob.glob(os.path.join(d, "*", "*.png")) if not f.endswith(".plate.png")]
    return sorted(fs, key=lambda f: int(os.path.basename(f).split("-")[0]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb", help="the inked file, as a path under living/game/assets (view/<file>.glb)")
    ap.add_argument("--out")
    ap.add_argument("--binary", help="the game client (default $CARGO_TARGET_DIR or living/target, release)")
    ap.add_argument("--plain-stills", help="reuse a plain run's stills folder")
    ap.add_argument("--ink-stills", help="reuse an ink run's stills folder")
    a = ap.parse_args()
    glb = os.path.relpath(a.glb, ASSETS) if os.path.isabs(a.glb) else a.glb
    stem = Path(glb).stem
    j, _ = read_glb(ASSETS / glb)
    inks = {m.get("name"): {k: v for k, v in m.get("extras", {}).get("slop", {}).get("hair", {}).items() if k in INK_KEYS} for m in j.get("materials", []) if isinstance(m.get("extras", {}).get("slop", {}).get("hair"), dict)}
    out = Path(a.out) if a.out else REPO / ".local" / "living" / "hair-shimmer" / stem / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    binary = Path(a.binary) if a.binary else Path(os.environ.get("CARGO_TARGET_DIR", REPO / "living" / "target")) / "release" / "living-game"
    print(f"hair_shimmer: {glb}: ink fields {inks}")
    if not a.ink_stills:
        render(glb, out / "ink", binary)
    if not a.plain_stills:
        plain = plain_copy(glb)
        try:
            render(plain, out / "plain", binary)
        finally:
            for f in glob.glob(str(ASSETS / (plain[: -len(".glb")] + "*"))):
                os.remove(f)
    P = stills(a.plain_stills or str(out / "plain"))
    I = stills(a.ink_stills or str(out / "ink"))
    if len(P) < 6 * FRAMES or len(I) < 6 * FRAMES:
        sys.exit(f"hair_shimmer: {len(P)} plain and {len(I)} ink stills; {6 * FRAMES} each expected")
    rows = score(P, I)
    print(f"  {'sequence':<12} {'F_ink':>7} {'F_edge':>7} {'ratio':>6} {'ink px/frame':>13}  result (pass: ratio <= 1.5)")
    for r in rows:
        if r["result"] == "faded":
            print(f"  {r['sequence']:<12} {'':>7} {'':>7} {'':>6} {r['ink_px']:13.1f}  faded (not scored)")
        else:
            print(f"  {r['sequence']:<12} {r['f_ink']:7.3f} {r['f_edge']:7.3f} {r['ratio']:6.2f} {r['ink_px']:13.1f}  {r['result']}")
    ok = all(r["result"] != "FAIL" for r in rows)
    (out / "shimmer.json").write_text(json.dumps(dict(file=glb, ink=inks, sequences=rows, passed=ok), indent=2))
    print(f"  shimmer: {'PASS' if ok else 'FAIL'} ({out / 'shimmer.json'})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
