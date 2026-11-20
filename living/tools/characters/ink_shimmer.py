#!/usr/bin/env python3
"""Shimmer of a hand-made character's ink lines in camera pans and zooms (docs/HANDMADE_INK.md,
"Shimmer, per slot"; the hair's v1.1 lock lines, docs/HANDMADE_HAIR.md, "Ink shimmer").

    python3 living/tools/characters/ink_shimmer.py view/<file>.glb [--slot S] [--material NAME]
                         [--fade A,B,...] [--stills] [--also SHOT] [--out DIR] [--binary PATH]
                         [--plain-stills DIR] [--ink-stills DIR]

The file is used as it is, with its own ink (each material's `extras.slop.ink`, and the hair
profile's v1.1 `ink`, `ink_range`, `ink_px`, `ink_fade_px`) and sidecars. The reference is the
same file with the targeted ink taken out (a temporary copy `view/<stem>-noink.glb`, its sidecars
copied, removed afterwards): every ink without `--slot`; with `--slot S` only the materials of
slot S (the hair: their `slop.ink` and their profile's v1.1 fields); with `--material` only that
one.

**Shots** (the asset view, headless, 1600x900, 11:00, the idle clip paused at 0 s or the first
clip, springs off): at each game camera stop, Near (8 m up, FOV 42°), Middle (12 m, 44°) and
Far (19 m, 46°), 58° down at the chest, a pan of 16 stills (yaw 0 to 1.5°, 0.1° a frame) and a
zoom of 16 (the height up 0.3% a frame). `--also SHOT` adds a pan and a zoom at a view shot:
`portrait` (yaw 0, pitch 8, zoom 0.36, aim 0.88, the calibration frame's) or `YAW:PITCH:ZOOM:AIM`
(the pan turns the yaw 0.1° a frame, the zoom moves in 0.3% a frame).

**Metric.** Per frame i and pixel p, with luminance L:

- ink signal  s_i(p) = max(0, Lplain_i(p) - Link_i(p)): how much the line darkens the pixel;
- edge signal e_i(p) = |dL/dx| + |dL/dy| of the plain frame: the surface's own band and
  highlight edges.

The flicker ratio F = sum |x_{i+1} - 2 x_i + x_{i-1}| / sum x over the region scored: a smooth
camera path changes a well-drawn signal nearly linearly over a frame, so the second temporal
difference isolates what flickers or crawls (0 is smooth, up to 4 for signal that comes and goes
at random). **The region:** for `--slot hair` (`hair_shimmer.py`), the hair pixels (the hue of
the plain frame where ink falls, within ±0.06, saturation above 0.2) in the box round every pixel
the ink changes at that stop, 8 px wider; for other slots (eye whites and skin fail the hair's
saturation test), the union over the sequence's frames of the pixels the ink darkens by more than
2 levels, dilated by 3 px. **A sequence passes when F_ink <= 1.5 F_edge:** the line flickers no
more, per unit of what it draws, than the antialiased edges the surface already shows in motion,
with half again for a line having two edges to an edge's one. A sequence whose ink darkens fewer
than 1 pixel a frame by more than 8 levels is not scored (the ink has faded out there): it is
listed as `faded`.

**Deciding a fade:** `--fade A,B,...` scores the file once for each `fade_px` (an ink copy per
value, the value set on every targeted ink; the reference is rendered once). `--stills` writes,
per value, a crop round the ink at the Near and Middle stops (the pan's first frame), the reference
beside the ink, 4x nearest-neighbour: `stills/<stop>-fade<v>.png` (`-file` without `--fade`).

Writes OUT (default `.local/living/ink-shimmer/<stem>/<time>/`, `hair-shimmer` for
`hair_shimmer.py`): `plain/`, `ink/` (or `ink-fade<v>/`), `shimmer.json` and the table it
prints. `--perf FLAGS` passes `LIVING_GAME_PERF` to both renders (the
client's A/B switches, such as `inkfw`; no other `LIVING_GAME_` variable reaches them).
`--plain-stills`/`--ink-stills` reuse an earlier run's still folders (each
`<dir>/<stem>/NN-*.png`) instead of rendering. Plain Python.
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
VIEWS = {"portrait": "0:8:0.36:0.88"}


def sequences(also):
    """(name, the 2 x FRAMES shots of its pan and zoom) per stop and `--also` view."""
    out = []
    for name, h, f in STOPS:
        out.append((name, [f"play:{h}:{f}@{0.1 * k:.1f}" for k in range(FRAMES)] + [f"play:{h * (1 + 0.003 * k):.3f}:{f}@0" for k in range(FRAMES)]))
    for v in also:
        y, p, z, a = (float(x) for x in VIEWS.get(v, v).split(":"))
        out.append((v.replace(":", "_"), [f"{y + 0.1 * k:.2f}:{p}:{z}:{a}" for k in range(FRAMES)] + [f"{y}:{p}:{z * (1 - 0.003 * k):.5f}:{a}" for k in range(FRAMES)]))
    return out


def shots(clip, also=()):
    out = [s for _, seq in sequences(also) for s in seq]
    return ",".join(f"{clip}@0/{s}" if clip else s for s in out)


PERF = []
# Variables passed to the client as well (a composed person's book, contract v1.3).
EXTRA = {}


def render(glb, out, binary, also=(), extra=None):
    if glb.startswith("look:"):
        clip = "idle"
    else:
        clips = clips_of(glb)
        clip = "idle" if "idle" in clips else (clips[0] if clips else None)
    env = {k: v for k, v in os.environ.items() if not k.startswith("LIVING_GAME_")}
    env.update(LIVING_GAME_VIEW=glb, LIVING_GAME_VIEW_SHOTS=shots(clip, also), LIVING_GAME_VIEW_OUT=str(out), LIVING_GAME_HOUR="11", LIVING_GAME_DAY_MINUTES="0",
               LIVING_GAME_FILM="soft", LIVING_GAME_SETTINGS=str(out) + ".settings.json", LIVING_GAME_SIZE="1600x900", LIVING_GAME_SPRINGS="0", RUST_LOG="warn")
    if clip:
        env["LIVING_GAME_VIEW_CLIP"] = clip
    if PERF:
        env["LIVING_GAME_PERF"] = ",".join(PERF)
    env.update(EXTRA)
    env.update(extra or {})
    with open(str(out) + ".log", "w") as log:
        subprocess.run([str(binary)], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)


def targeted(m, slot, material):
    ms = m.get("extras", {}).get("slop") or {}
    return (slot is None or ms.get("slot") == slot) and (material is None or m.get("name") == material)


def inks_of(j, slot, material):
    """The targeted inks, by material: its slop.ink, or its hair profile's v1.1 fields."""
    out = {}
    for m in j.get("materials", []):
        ms = m.get("extras", {}).get("slop") or {}
        if not targeted(m, slot, material):
            continue
        if isinstance(ms.get("ink"), dict):
            out[m.get("name")] = dict(ms["ink"])
        elif isinstance(ms.get("hair"), dict) and any(k in ms["hair"] for k in INK_KEYS):
            out[m.get("name")] = {k: v for k, v in ms["hair"].items() if k in INK_KEYS}
    return out


def copy_with(glb, suffix, slot, material, fade=None):
    """A copy of the file beside it, with its sidecars: the targeted ink removed (`fade` None), or
    its fade set to `fade`; returns its path under assets."""
    j, binary = read_glb(ASSETS / glb)
    for m in j.get("materials", []):
        ms = m.get("extras", {}).get("slop") or {}
        if not targeted(m, slot, material):
            continue
        h = ms.get("hair") if isinstance(ms.get("hair"), dict) else {}
        if fade is None:
            ms.pop("ink", None)
            for k in INK_KEYS:
                h.pop(k, None)
        elif isinstance(ms.get("ink"), dict):
            ms["ink"]["fade_px"] = fade
        elif any(k in h for k in INK_KEYS):
            h["ink_fade_px"] = fade
    stem = glb[: -len(".glb")]
    out = stem + suffix + ".glb"
    write_glb(ASSETS / out, j, bytearray(binary))
    base = Path(ASSETS / stem)
    for f in base.parent.glob(base.name + ".*"):
        side = f.name[len(base.name):]
        if side.endswith((".png", ".ktx2")):
            shutil.copyfile(f, ASSETS / (stem + suffix + side))
    return out


def remove_copy(glb):
    base = Path(ASSETS / glb[: -len(".glb")])
    for f in base.parent.glob(base.name + ".*"):
        f.unlink()


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


def score(plain_files, ink_files, hair=True, also=()):
    rows = []
    for si, (stop, _) in enumerate(sequences(also)):
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
            if hair:
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
            else:
                # The ink's own footprint: where it darkens any frame by more than 2 levels,
                # dilated by 3 px.
                ny, nx = y1 - y0 + 1, x1 - x0 + 1
                seen = [[False] * nx for _ in range(ny)]
                for k in range(FRAMES):
                    for yy in range(ny):
                        rp, ri = Lp[k][yy], Li[k][yy]
                        row = seen[yy]
                        for xx in range(nx):
                            if rp[xx] - ri[xx] > 2:
                                row[xx] = True
                M = [[False] * nx for _ in range(ny)]
                for yy in range(ny):
                    for xx in range(nx):
                        if seen[yy][xx]:
                            for dy in range(max(0, yy - 3), min(ny, yy + 4)):
                                for dx in range(max(0, xx - 3), min(nx, xx + 4)):
                                    M[dy][dx] = True
                for yy in range(ny):
                    M[yy][0] = False
                M[0] = [False] * nx
            S = [[[max(0.0, a - b) for a, b in zip(rp, ri)] for rp, ri in zip(Lp[k], Li[k])] for k in range(FRAMES)]
            Ed = [[[0.0 if x == 0 or y == 0 else abs(L[y][x] - L[y][x - 1]) + abs(L[y][x] - L[y - 1][x]) for x in range(len(L[0]))] for y in range(len(L))] for L in Lp]
            fi, fe = flicker(S, M), flicker(Ed, M)
            ratio = fi / fe if fe else 0.0
            rows.append(dict(sequence=name, f_ink=round(fi, 3), f_edge=round(fe, 3), ratio=round(ratio, 2), ink_px=round(ink_px, 1), result="pass" if ratio <= 1.5 else "FAIL"))
    return rows


def stills(d):
    fs = [f for f in glob.glob(os.path.join(d, "*", "*.png")) if not f.endswith(".plate.png")]
    return sorted(fs, key=lambda f: int(os.path.basename(f).split("-")[0]))


def crop_sheet(plain, ink, out):
    """The reference beside the ink, cropped round where the ink falls, 4x nearest."""
    p, i = read_rgb(plain), read_rgb(ink)
    w, h = p[0], p[1]
    lp, li = lum_of(p, 0, w, 0, h), lum_of(i, 0, w, 0, h)
    pts = [(x, y) for y in range(h) for x in range(w) if lp[y][x] - li[y][x] > 2]
    if not pts:
        pts = [(w // 2, h // 2)]
    x0, x1 = max(min(q[0] for q in pts) - 16, 0), min(max(q[0] for q in pts) + 17, w)
    y0, y1 = max(min(q[1] for q in pts) - 16, 0), min(max(q[1] for q in pts) + 17, h)
    cw, chh, sc = x1 - x0, y1 - y0, 4
    rows = []
    for y in range(y0, y1):
        line = bytearray()
        for img in (p, i):
            r = img[3][y]
            for x in range(x0, x1):
                line += bytes(r[x * img[2]:x * img[2] + 3]) * sc
            line += b"\xff\xff\xff" * 4 * sc
        rows += [line] * sc
    width = (2 * cw + 8) * sc
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(out, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, len(rows), 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def stills(d):
    fs = [f for f in glob.glob(os.path.join(d, "*", "*.png")) if not f.endswith(".plate.png")]
    return sorted(fs, key=lambda f: int(os.path.basename(f).split("-")[0]))


def main(argv=None, tool="ink_shimmer"):
    ap = argparse.ArgumentParser(prog=tool, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb", help="the inked file, as a path under living/game/assets (view/<file>.glb); or look:<key>, a composed person (contract v1.3) from the book (LIVING_GAME_LOOK_BOOK, passed on)")
    ap.add_argument("--slot", help="score only the ink of this slot's materials")
    ap.add_argument("--material", help="score only this material's ink")
    ap.add_argument("--fade", help="comma-separated fade_px values to score, one ink copy each")
    ap.add_argument("--stills", action="store_true", help="Near and Middle crops per fade value")
    ap.add_argument("--also", action="append", default=[], help="another view shot for a pan and a zoom: portrait or YAW:PITCH:ZOOM:AIM")
    ap.add_argument("--perf", help="LIVING_GAME_PERF flags for both renders (the client's A/B switches; other LIVING_GAME_ variables are not passed)")
    ap.add_argument("--out")
    ap.add_argument("--binary", help="the game client (default $CARGO_TARGET_DIR or living/target, release)")
    ap.add_argument("--plain-stills", help="reuse a plain run's stills folder")
    ap.add_argument("--ink-stills", help="reuse an ink run's stills folder (without --fade)")
    a = ap.parse_args(argv)
    PERF[:] = [f for f in (a.perf or "").split(",") if f]
    composed = a.glb.startswith("look:")
    glb = a.glb if composed or not os.path.isabs(a.glb) else os.path.relpath(a.glb, ASSETS)
    if composed:
        # A composed person: their files are shared, so the reference is the same person with
        # the targeted ink switched off in the client (docs/HANDMADE_COMPOSED.md, "The audit and
        # tools"), not a copy.
        if a.fade or a.material:
            sys.exit(f"{tool}: --fade and --material need a file; a composed person is scored by slot")
        if os.environ.get("LIVING_GAME_LOOK_BOOK"):
            EXTRA["LIVING_GAME_LOOK_BOOK"] = os.environ["LIVING_GAME_LOOK_BOOK"]
        stem = glb.replace(":", "_")
        inks = {"composed": f"slot {a.slot or 'all'}"}
    else:
        stem = Path(glb).stem
        j, _ = read_glb(ASSETS / glb)
        inks = inks_of(j, a.slot, a.material)
    if not inks:
        sys.exit(f"{tool}: {glb} has no ink" + (f" on slot {a.slot!r}" if a.slot else "") + (f" on material {a.material!r}" if a.material else "") + ": nothing to compare")
    out = Path(a.out) if a.out else REPO / ".local" / "living" / ("hair-shimmer" if tool == "hair_shimmer" else "ink-shimmer") / stem / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    binary = Path(a.binary) if a.binary else Path(os.environ.get("CARGO_TARGET_DIR", REPO / "living" / "target")) / "release" / "living-game"
    print(f"{tool}: {glb}: ink {inks}")
    hair = a.slot == "hair"
    fades = [float(v) for v in a.fade.split(",")] if a.fade else [None]
    if not a.plain_stills and composed:
        render(glb, out / "plain", binary, a.also, {"LIVING_GAME_COMPOSED_SLOP": f"noink:{a.slot}" if a.slot else "noink"})
    elif not a.plain_stills:
        plain = copy_with(glb, "-noink", a.slot, a.material)
        try:
            render(plain, out / "plain", binary, a.also)
        finally:
            remove_copy(plain)
    P = stills(a.plain_stills or str(out / "plain"))
    need = 2 * FRAMES * len(sequences(a.also))
    results, ok = {}, True
    for fade in fades:
        label = "file" if fade is None else f"fade{fade:g}"
        if fade is None:
            idir = a.ink_stills or str(out / "ink")
            if not a.ink_stills:
                render(glb, out / "ink", binary, a.also)
        else:
            idir = str(out / f"ink-{label}")
            cp = copy_with(glb, f"-{label}", a.slot, a.material, fade)
            try:
                render(cp, Path(idir), binary, a.also)
            finally:
                remove_copy(cp)
        I = stills(idir)
        if len(P) < need or len(I) < need:
            sys.exit(f"{tool}: {len(P)} plain and {len(I)} ink stills; {need} each expected")
        rows = score(P, I, hair, a.also)
        results[label] = rows
        print(f"  {label}:")
        print(f"  {'sequence':<14} {'F_ink':>7} {'F_edge':>7} {'ratio':>6} {'ink px/frame':>13}  result (pass: ratio <= 1.5)")
        for r in rows:
            if r["result"] == "faded":
                print(f"  {r['sequence']:<14} {'':>7} {'':>7} {'':>6} {r['ink_px']:13.1f}  faded (not scored)")
            else:
                print(f"  {r['sequence']:<14} {r['f_ink']:7.3f} {r['f_edge']:7.3f} {r['ratio']:6.2f} {r['ink_px']:13.1f}  {r['result']}")
        ok &= all(r["result"] != "FAIL" for r in rows)
        if a.stills:
            (out / "stills").mkdir(exist_ok=True)
            for si, (name, _) in enumerate(sequences(a.also)[:2]):
                k = 2 * si * FRAMES
                crop_sheet(P[k], I[k], out / "stills" / f"{name}-{label}.png")
    report = dict(file=glb, slot=a.slot, material=a.material, ink=inks, also=a.also, passed=ok)
    if fades == [None]:
        report["sequences"] = results["file"]
    else:
        report["fades"] = results
    (out / "shimmer.json").write_text(json.dumps(report, indent=2))
    print(f"  shimmer: {'PASS' if ok else 'FAIL'} ({out / 'shimmer.json'})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
