#!/usr/bin/env python3
"""The shared hair-mask page (char-port-2 S5, `SLOP_PORT=hair`; docs/HANDMADE_COMPOSED.md v1.3,
"The hair-mask page"): every hair style file put on one page and opted into the handmade-hair
profile with one palette relative to the hair tag.

    python3 living/tools/characters/hair_page.py STYLES/hair [--anchors ANCHORS.json] [--profile P.json] [--profile-only]

For every `<style>.glb` in the folder with a `<style>.hairpage.json` beside it (person.py writes it
with the flag: the file's hair laid out at 1 mm a texel in a rectangle, and its lock lines):

- **The cells.** The page is 4096², 8 × 8 cells of 512. A file takes whole cells, `[col, row, w, h]`,
  at most 2 × 2; files are placed in sorted path order, each at the first free position scanning
  rows top to bottom, then columns left to right. A page that is full starts a second
  (`hair-masks-1.png`, its own material), and the manifest says so.
- **The file.** Its hair primitives' TEXCOORD_0 (`Hair` and `FarHair`) move into its cells; the
  hair material loses its texture, and the strands' picture with it (`prune_orphans`: every texture,
  image and sampler no material uses goes, in both modes, so the client loads none) and takes `slop.hair` (the profile below, the same object on every
  file of the page, `highlight_map` the page); the scene opts in (`slop` `{"contract": 1}`).
- **The page.** R: the highlight, each file's `_HIGHLIGHT` rasterised from its near `Hair` mesh,
  and the parting (`parting_strip`: a pale strip where the hair parts, on what lies near the
  scalp there). G: the lock lines' distance field over `ink_range` (HANDMADE_HAIR v1.1; 255 is no
  line). B: main's strands under the bands at low contrast (`strands_bake`, `--strands`; the
  client multiplies the bands by 2 B, 128 none), for files that carry the strands' mapping
  (`_STRANDU`, `_STRANDV`, `_STRANDK`, removed once read); 0 on a page without.
- **The manifest**, `hair-masks.json`: `{"page", "size", "cell", "density_mm", "files": {name: [col,
  row, w, h]}}` (the first page) and, when there is more than one, `"pages"`: each page's `page`
  and `files`. The generator's 86 files take 190 cells: three pages (docs/char-port-2/s5).
- **`--profile-only`:** the files already on the page keep their places; only their `slop.hair` is
  written again (with `--profile`, the profile's own swatches; with `--anchors`, the anchors), as
  the calibration (docs/char-port-2/s5/calibrate_bins.py) does each round.

**The profile:** Cora's accepted swatches at their hair colour, auburn (`ref`), and thresholds,
relative to the tag (`palette: "tag"`), with an anchor for each other colour bin (`--anchors`, or
this file's ANCHORS: black, brown, blond and grey; HANDMADE_COMPOSED v1.3.1 allows 4), as
calibrated in docs/char-port-2/s5. The lock lines' `ink`, on the profile and on every anchor, is a
darker shade of its own mid swatch (INK_RULE; softer on light hair). A page with strands gives every file on it
`strands: true` (v1.3.1).
Plain Python, numpy and Pillow.
"""
import argparse
import glob
import json
import math
import os
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from merge_primitives import read_glb, write_glb  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import palette  # noqa: E402

PAGE, CELL = 4096, 512
GRID = PAGE // CELL
DENSITY_MM = 1.0
PAGE_PATH = "lookdev/styles/hair/hair-masks.png"
STRANDS = 0.9  # main's strands under the bands, at this share of their own contrast (B; char-port-2 S5's B2)
STRANDS_RANGE = (0.35, 0.65)  # B's range: the contract's low-contrast range (the bands x 0.7 to 1.3)
# The strands' mean over a style's texels is held at neutral (0.5, 128): the bake's own mean runs
# from 125 to 164 by style (main's shading factor, and the larger of a sheet's front and back), and
# the palette, calibrated on one style, was off on the others by up to 15% (char-port-2 S6 step 4).
# STRANDS_MEAN_TOL: how far a page's file may stand from 128 before the audit fails it.
STRANDS_MEAN_TOL = 2.0
AUBURN = [102, 46, 26]
# At auburn: Cora's accepted hair (docs/char-live-3/ink-batch-2/own-cora-live.glb) as calibrated on a
# composed person against the drawing's hair patches, with the strands under the bands
# (docs/char-port-2/s5/calibrate_bins.py; again in S6 step 4, over the held strands).
PROFILE = dict(palette="tag", ref=AUBURN, shade=[36, 1, 0], mid=[98, 33, 5], light=[114, 43, 4], highlight=[138, 53, 3],
               t1=-0.2, t2=0.4, edge=0.02, highlight_feather=0.08, ink_px=1.05, ink_fade_px=2.0)
# One anchor a colour bin besides auburn (HANDMADE_COMPOSED "Several anchors"): black, brown, blond
# and grey, calibrated in docs/char-port-2/s5 (calibrate_bins.py) and again, over the strands held at
# a neutral mean, in S6 step 4 (docs/char-port-2/s6/step4: bob, then checked on six styles).
ANCHORS = [{"ref": [19, 17, 17], "shade": [0, 0, 0], "mid": [6, 5, 5], "light": [21, 19, 18], "highlight": [51, 46, 46]}, {"ref": [51, 34, 23], "shade": [6, 2, 1], "mid": [42, 27, 15], "light": [55, 36, 25], "highlight": [67, 49, 36]}, {"ref": [158, 125, 71], "shade": [84, 61, 29], "mid": [158, 121, 49], "light": [187, 156, 100], "highlight": [237, 197, 121]}, {"ref": [133, 133, 133], "shade": [65, 65, 65], "mid": [123, 123, 123], "light": [156, 156, 156], "highlight": [193, 193, 193]}]


# The lock lines' colour (the third pass, 2026-11-20): a darker shade of the hair's own mid swatch,
# never near-black on hair that is not: OKLab lightness `lightness` x the mid's, and at least
# `contrast` below it (which keeps a line on black hair, whose mid is near black, at black), the
# mid's own a and b. Light hair (the GC, 2026-11-20: its mid drawn above OKLab L 0.7 at 11:00,
# which is its mid swatch above `light_from`: blond and grey, drawn at 0.72) takes `light`, a
# softer line: dark strokes on pale hair read as scratches at portrait. Set on the profile (its
# `ink`) and on every anchor, so the palette moves it with the hair like a swatch (white's lines
# come from grey's and blond's).
INK_RULE = dict(lightness=0.65, contrast=0.12, light_from=0.5, light=dict(lightness=0.8, contrast=0.08))


def line_ink(mid):
    L, a, b = palette.oklab(tuple(mid))
    r = INK_RULE["light"] if L > INK_RULE["light_from"] else INK_RULE
    Li = max(0.0, min(r["lightness"] * L, L - r["contrast"]))
    return [palette.enc(x) for x in palette.from_oklab(Li, a, b)]


def with_inks(profile, anchors):
    """The profile's and each anchor's `ink` by INK_RULE."""
    profile = dict(profile, ink=line_ink(profile["mid"]))
    return profile, [dict(x, ink=line_ink(x["mid"])) for x in anchors]


def accessor(j, binary, i):
    a = j["accessors"][i]
    bv = j["bufferViews"][a["bufferView"]]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    dt = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}[a["componentType"]]
    stride = bv.get("byteStride", 0)
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    if stride and stride != n * np.dtype(dt).itemsize:
        raise SystemExit(f"hair_page: accessor {i} is interleaved")
    arr = np.frombuffer(bytes(binary[off: off + a["count"] * n * np.dtype(dt).itemsize]), dt).reshape(a["count"], n)
    return arr, off


def texture_infos(node):
    """Every texture-info a material holds (any key ending in `Texture`, extensions included:
    a dict with an integer `index`)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k.endswith(("Texture", "texture")) and isinstance(v, dict) and isinstance(v.get("index"), int):
                yield v
            yield from texture_infos(v)
    elif isinstance(node, list):
        for v in node:
            yield from texture_infos(v)


def prune_orphans(j):
    """Drop the textures no material names, then the images and samplers no texture uses, and
    renumber what is left. Profile hair loses its base texture (the strands' picture), and a
    picture left in the file is still loaded by the client, though nothing draws it; its path,
    written where the file was built, can even lie outside the asset folder (an error at every
    load). Returns how many textures and images went."""
    textures, images, samplers = j.get("textures", []), j.get("images", []), j.get("samplers", [])
    used_t = sorted({t["index"] for t in texture_infos(j.get("materials", []))})
    tmap = {old: new for new, old in enumerate(used_t)}
    kept_t = [textures[i] for i in used_t if i < len(textures)]

    def image_refs(t):
        out = [t["source"]] if isinstance(t.get("source"), int) else []
        for ext in (t.get("extensions") or {}).values():
            if isinstance(ext, dict) and isinstance(ext.get("source"), int):
                out.append(ext["source"])
        return out

    used_i = sorted({i for t in kept_t for i in image_refs(t)})
    imap = {old: new for new, old in enumerate(used_i)}
    used_s = sorted({t["sampler"] for t in kept_t if isinstance(t.get("sampler"), int)})
    smap = {old: new for new, old in enumerate(used_s)}
    for t in kept_t:
        if isinstance(t.get("source"), int):
            t["source"] = imap[t["source"]]
        for ext in (t.get("extensions") or {}).values():
            if isinstance(ext, dict) and isinstance(ext.get("source"), int):
                ext["source"] = imap[ext["source"]]
        if isinstance(t.get("sampler"), int):
            t["sampler"] = smap[t["sampler"]]

    for info in list(texture_infos(j.get("materials", []))):
        info["index"] = tmap[info["index"]]
    gone = (len(textures) - len(kept_t), len(images) - len(used_i))
    for key, kept in (("textures", kept_t), ("images", [images[i] for i in used_i]), ("samplers", [samplers[i] for i in used_s])):
        if kept:
            j[key] = kept
        else:
            j.pop(key, None)
    return gone


def hair_prims(j):
    for m in j["meshes"]:
        for p in m["primitives"]:
            name = j["materials"][p["material"]]["name"] if "material" in p else ""
            if "_HAIR" in name and "Overlay" not in name:
                yield m["name"], p


def place(files):
    """Each file's cells: [page, col, row, w, h]."""
    pages, out = [], {}
    for name, (w, h) in files:
        if w > 2 or h > 2:
            raise SystemExit(f"hair_page: {name} needs {w} x {h} cells at {DENSITY_MM} mm a texel: over the hair budget (2 x 2)")
        for k in range(len(pages) + 1):
            if k == len(pages):
                pages.append(np.zeros((GRID, GRID), bool))
            g = pages[k]
            spot = next(((c, r) for r in range(GRID - h + 1) for c in range(GRID - w + 1) if not g[r:r + h, c:c + w].any()), None)
            if spot:
                c, r = spot
                g[r:r + h, c:c + w] = True
                out[name] = [k, c, r, w, h]
                break
    return out, len(pages)


def raster_highlight(R, uv_px, tris, hl):
    """The largest highlight over each texel the triangles cover (barycentric)."""
    for a, b, c in tris:
        P = uv_px[[a, b, c]]
        lo = np.floor(P.min(0)).astype(int)
        hi = np.ceil(P.max(0)).astype(int)
        if hl[[a, b, c]].max() <= 0.0:
            continue
        xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1) + 0.5, np.arange(lo[1], hi[1] + 1) + 0.5)
        d = (P[1, 1] - P[2, 1]) * (P[0, 0] - P[2, 0]) + (P[2, 0] - P[1, 0]) * (P[0, 1] - P[2, 1])
        if abs(d) < 1e-12:
            continue
        w0 = ((P[1, 1] - P[2, 1]) * (xs - P[2, 0]) + (P[2, 0] - P[1, 0]) * (ys - P[2, 1])) / d
        w1 = ((P[2, 1] - P[0, 1]) * (xs - P[2, 0]) + (P[0, 0] - P[2, 0]) * (ys - P[2, 1])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        v = (w0 * hl[a] + w1 * hl[b] + w2 * hl[c])[inside]
        X, Y = (xs[inside] - 0.5).astype(int), (ys[inside] - 0.5).astype(int)
        ok = (X >= 0) & (X < PAGE) & (Y >= 0) & (Y < PAGE)
        R[Y[ok], X[ok]] = np.maximum(R[Y[ok], X[ok]], v[ok])


def raster(uv_px, tris, attrs):
    """Per triangle, the texels it covers (their centres inside it) and each attribute there,
    interpolated (barycentric): yields (X, Y, {name: values})."""
    for a, b, c in tris:
        P = uv_px[[a, b, c]]
        lo = np.floor(P.min(0)).astype(int)
        hi = np.ceil(P.max(0)).astype(int)
        xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1) + 0.5, np.arange(lo[1], hi[1] + 1) + 0.5)
        d = (P[1, 1] - P[2, 1]) * (P[0, 0] - P[2, 0]) + (P[2, 0] - P[1, 0]) * (P[0, 1] - P[2, 1])
        if abs(d) < 1e-12:
            continue
        w0 = ((P[1, 1] - P[2, 1]) * (xs - P[2, 0]) + (P[2, 0] - P[1, 0]) * (ys - P[2, 1])) / d
        w1 = ((P[2, 1] - P[0, 1]) * (xs - P[2, 0]) + (P[0, 0] - P[2, 0]) * (ys - P[2, 1])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        X, Y = (xs[inside] - 0.5).astype(int), (ys[inside] - 0.5).astype(int)
        ok = (X >= 0) & (X < PAGE) & (Y >= 0) & (Y < PAGE)
        if not ok.any():
            continue
        vals = {}
        for k, v in attrs.items():
            q = w0[inside][:, None] * v[a] + w1[inside][:, None] * v[b] + w2[inside][:, None] * v[c]
            vals[k] = q[ok]
        yield X[ok], Y[ok], vals


def parting_strip(R, uv_px, tris, pos, partings, width, depth):
    """The parting (person.py's partings, in Blender's frame): R raised to 1 on what lies within
    `depth` of the scalp and within half `width` across of the parting's line, the width tapering
    to nothing over the line's first and last fifths."""
    if not partings:
        return 0
    segs = []
    for pt in partings:
        P = np.array([[x, z, -y] for x, y, z in pt["pts"]], float)  # glTF: y up, z forward
        O = np.array([[x, z, -y] for x, y, z in pt["out"]], float)
        run = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
        for i in range(len(P) - 1):
            segs.append((P[i], P[i + 1], O[i], O[i + 1], run[i] / run[-1], run[i + 1] / run[-1]))
    lo = np.min([np.minimum(s[0], s[1]) for s in segs], axis=0) - depth - width
    hi = np.max([np.maximum(s[0], s[1]) for s in segs], axis=0) + depth + width
    n = 0
    for X, Y, v in raster(uv_px, tris, dict(p=pos)):
        x = v["p"]
        near = np.all((x >= lo) & (x <= hi), axis=1)
        if not near.any():
            continue
        x, Xn, Yn = x[near], X[near], Y[near]
        best = np.full(len(x), np.inf)
        for a, b, oa, ob, ta, tb in segs:
            ab = b - a
            t = np.clip(((x - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
            c = a + t[:, None] * ab
            o = oa + t[:, None] * (ob - oa)
            o /= np.linalg.norm(o, axis=1, keepdims=True)
            r = x - c
            up = np.einsum("ij,ij->i", r, o)
            across = np.linalg.norm(r - up[:, None] * o, axis=1)
            share = ta + t * (tb - ta)
            half = 0.5 * width * np.clip(np.minimum(share, 1 - share) / 0.2, 0, 1) ** 0.5
            ok = (up > -0.004) & (up < depth) & (across < half)
            best = np.where(ok, np.minimum(best, across / np.maximum(half, 1e-9)), best)
        hit = np.isfinite(best)
        R[Yn[hit], Xn[hit]] = 1.0
        n += int(hit.sum())
    return n


def strands_bake(B, uv_px, tris, su, sv, sk, picture, contrast):
    """b2: main's strands under the bands, at low contrast: B = (1 + contrast x (m - 1)) / 2,
    m the strands' picture (over its mean) at the vertex's own mapping times main's shading of
    the vertex (its colour over the median), the larger where a sheet's front and back share a
    texel."""
    H, W = picture.shape
    mean = float(picture.mean())
    for X, Y, v in raster(uv_px, tris, dict(u=su[:, None], v=sv[:, None], k=sk[:, None])):
        px = (v["u"][:, 0] % 1.0) * W
        py = (1.0 - v["v"][:, 0]) % 1.0 * H  # Blender's v up; the picture's root at the top
        x0, y0 = np.floor(px - 0.5).astype(int), np.floor(py - 0.5).astype(int)
        fx, fy = px - 0.5 - x0, py - 0.5 - y0
        g = lambda yy, xx: picture[yy % H, xx % W]
        val = (g(y0, x0) * (1 - fx) * (1 - fy) + g(y0, x0 + 1) * fx * (1 - fy) + g(y0 + 1, x0) * (1 - fx) * fy + g(y0 + 1, x0 + 1) * fx * fy) / mean
        m = np.clip(val * v["k"][:, 0], 0.4, 1.6)
        b = np.clip(0.5 * (1 + contrast * (m - 1)), *STRANDS_RANGE)
        B[Y, X] = np.maximum(B[Y, X], b)


def lines_field(D, lines, rng):
    """The distance (texels) to the nearest line segment, within `rng` (D starts at rng)."""
    for pts in lines:
        P = np.asarray(pts, float)
        for a, b in zip(P[:-1], P[1:]):
            lo = np.floor(np.minimum(a, b) - rng - 1).astype(int)
            hi = np.ceil(np.maximum(a, b) + rng + 1).astype(int)
            lo, hi = np.maximum(lo, 0), np.minimum(hi, PAGE - 1)
            xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1) + 0.5, np.arange(lo[1], hi[1] + 1) + 0.5)
            ab = b - a
            t = np.clip(((xs - a[0]) * ab[0] + (ys - a[1]) * ab[1]) / max(ab @ ab, 1e-12), 0, 1)
            d = np.hypot(xs - (a[0] + t * ab[0]), ys - (a[1] + t * ab[1]))
            sub = D[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1]
            np.minimum(sub, d, out=sub)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--anchors", help="the calibrated anchors (a JSON list, HANDMADE_COMPOSED's `anchors`)")
    ap.add_argument("--profile", help="the profile's own swatches at its `ref` (JSON: shade, mid, light, highlight, ink), over PROFILE's")
    ap.add_argument("--profile-only", action="store_true", help="rewrite only the files' slop.hair (files already on the page; for calibration)")
    ap.add_argument("--strands", type=float, default=STRANDS, help=f"lay main's strands under the bands at this contrast (the page's B), for files that carry their mapping (_STRANDU/V/K; default {STRANDS}; 0 none)")
    a = ap.parse_args()
    anchors = json.load(open(a.anchors)) if a.anchors else ANCHORS
    if a.profile:
        PROFILE.update(json.load(open(a.profile)))
    if a.profile_only:
        n = 0
        seen = {}

        def strands_on(page):
            """Whether a page carries strands (its B not 0): a file on it takes `strands`."""
            if page not in seen:
                f = os.path.join(a.folder, os.path.basename(page)) if page else ""
                seen[page] = bool(f and os.path.exists(f) and np.asarray(Image.open(f).convert("RGB"))[..., 2].max() > 0)
            return seen[page]

        for g in sorted(glob.glob(os.path.join(a.folder, "*.glb"))):
            j, binary = read_glb(g)
            done = False
            for _, p in hair_prims(j):
                h = j["materials"][p["material"]].get("extras", {}).get("slop", {}).get("hair")
                if h is None:
                    continue
                for k in list(h):
                    if k in PROFILE or k in ("anchors", "ink"):
                        h.pop(k)
                prof, anc = with_inks(PROFILE, anchors)
                h.update(prof)
                if anc:
                    h["anchors"] = anc
                if strands_on(h.get("highlight_map")):
                    h["strands"] = True
                done = True
            if done:
                prune_orphans(j)
                write_glb(g, j, binary)
                n += 1
        print(f"hair_page: the profile rewritten on {n} files")
        return
    files = []
    for g in sorted(glob.glob(os.path.join(a.folder, "*.glb"))):
        side = g[:-4] + ".hairpage.json"
        if not os.path.exists(side):
            continue
        sp = json.load(open(side))
        files.append((os.path.basename(g), sp, (int(math.ceil(sp["size"][0] / CELL)), int(math.ceil(sp["size"][1] / CELL)))))
    if not files:
        raise SystemExit(f"hair_page: no file in {a.folder} has a .hairpage.json (build with SLOP_PORT=hair)")
    cells, n_pages = place([(n, wh) for n, _, wh in files])
    rng = files[0][1]["range_px"]
    R = [np.zeros((PAGE, PAGE), np.float32) for _ in range(n_pages)]
    # The strands (B) when any file carries their mapping; a page without them keeps B 0.
    carries = a.strands > 0 and any("_STRANDU" in p["attributes"] for n, _, _ in files for _, p in hair_prims(read_glb(os.path.join(a.folder, n))[0]))
    B = [np.zeros((PAGE, PAGE), np.float32) for _ in range(n_pages)] if carries else None
    picture = None
    if B is not None:
        picture = np.asarray(Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../game/assets/lookdev/strands.png")).convert("L"), np.float64) / 255.0
        for b in B:
            b[:] = -1.0  # unwritten: 0.5 (neutral) once every file is baked
    parted = 0
    D = [np.full((PAGE, PAGE), float(rng), np.float32) for _ in range(n_pages)]
    page_path = lambda k: PAGE_PATH if k == 0 else PAGE_PATH.replace(".png", f"-{k}.png")
    means = {}
    for name, sp, _ in files:
        k, c, r, w, h = cells[name]
        off = np.array([c * CELL, r * CELL], float)
        path = os.path.join(a.folder, name)
        j, binary = read_glb(path)
        prof, anc = with_inks(PROFILE, anchors)
        profile = dict(prof, ink_range=rng / PAGE, ink_m_uv=PAGE * DENSITY_MM / 1000, highlight_map=page_path(k))
        if anc:
            profile["anchors"] = anc
        if B is not None:
            profile["strands"] = True  # v1.3.1: the page's B is the strands
        moved = set()
        for mesh_name, p in hair_prims(j):
            ai = p["attributes"]["TEXCOORD_0"]
            uv, boff = accessor(j, binary, ai)
            px = uv.astype(np.float64) * PAGE
            if ai not in moved:
                new = ((px + off) / PAGE).astype(np.float32)
                binary[boff: boff + new.nbytes] = new.tobytes()
                j["accessors"][ai]["min"] = new.min(0).tolist()
                j["accessors"][ai]["max"] = new.max(0).tolist()
                moved.add(ai)
            p["attributes"].pop("_RING", None)  # a profile has no ring (HANDMADE_COMPOSED)
            strand = {k: p["attributes"].pop(k) for k in ("_STRANDU", "_STRANDV", "_STRANDK") if k in p["attributes"]}  # b2's, used below
            mat = j["materials"][p["material"]]
            mat.get("pbrMetallicRoughness", {}).pop("baseColorTexture", None)
            mat.setdefault("extras", {})["slop"] = {"slot": "hair", "hair": profile}
            if mesh_name == "Hair" and "_HIGHLIGHT" in p["attributes"]:
                hl, _ = accessor(j, binary, p["attributes"]["_HIGHLIGHT"])
                idx, _ = accessor(j, binary, p["indices"])
                raster_highlight(R[k], px + off, idx.reshape(-1, 3), hl[:, 0].astype(np.float64))
                pos, _ = accessor(j, binary, p["attributes"]["POSITION"])
                parted += parting_strip(R[k], px + off, idx.reshape(-1, 3), pos.astype(np.float64), sp.get("partings", []), **sp.get("parting", dict(width=0.008, depth=0.014)))
                if B is not None and len(strand) == 3:
                    su, sv, sk = (accessor(j, binary, strand[n])[0][:, 0].astype(np.float64) for n in ("_STRANDU", "_STRANDV", "_STRANDK"))
                    strands_bake(B[k], px + off, idx.reshape(-1, 3), su, sv, sk, picture, a.strands)
        if B is not None:
            # This style's strands, held at a neutral mean (STRANDS_MEAN_TOL): shifted, so their
            # contrast stays; the shift is recorded beside its measures.
            cell = B[k][r * CELL:(r + h) * CELL, c * CELL:(c + w) * CELL]
            wr = cell >= 0
            if wr.any():
                before = float(cell[wr].mean())
                cell[wr] = np.clip(cell[wr] - before + 0.5, *STRANDS_RANGE)
                means[name] = dict(before=round(before * 255, 1), after=round(float(cell[wr].mean()) * 255, 1))
        scene = j["scenes"][j.get("scene", 0)]
        slop = scene.setdefault("extras", {}).setdefault("slop", {})
        slop.pop("character", None)
        slop["contract"] = 1
        prune_orphans(j)  # the strands' picture, now that no material names it
        write_glb(path, j, binary)
        lines_field(D[k], [np.asarray(l, float) + off for l in sp["creases"]], rng)
    for k in range(n_pages):
        img = np.zeros((PAGE, PAGE, 3), np.uint8)
        img[..., 0] = np.round(np.clip(R[k], 0, 1) * 255)
        img[..., 1] = np.round(np.clip(D[k] / rng, 0, 1) * 255)
        if B is not None:
            # Neutral (0.5, 128) in every texel without strands, cell padding included, so the
            # filter and the mips never read an island's edge as dark (v1.3.1).
            img[..., 2] = np.round(np.clip(np.where(B[k] < 0, 0.5, B[k]), 0, 1) * 255)
        Image.fromarray(img, "RGB").save(os.path.join(a.folder, os.path.basename(page_path(k))))
    manifest = dict(page=PAGE_PATH, size=PAGE, cell=CELL, density_mm=DENSITY_MM, files={n: v[1:] for n, v in cells.items() if v[0] == 0})
    if n_pages > 1:
        manifest["pages"] = [dict(page=page_path(k), files={n: v[1:] for n, v in cells.items() if v[0] == k}) for k in range(n_pages)]
    if means:
        manifest["strands"] = dict(mean=128, tolerance=STRANDS_MEAN_TOL, files=dict(sorted(means.items())))  # each style's strands' mean (of 255) as baked and as held
    json.dump(manifest, open(os.path.join(a.folder, "hair-masks.json"), "w"), indent=1)
    used = sum(v[3] * v[4] for v in cells.values())
    print(f"hair_page: {len(files)} files on {n_pages} page(s), {used} cells of {n_pages * GRID * GRID}; lines from {sum(len(sp['creases']) for _, sp, _ in files)} creases;"
          f" partings over {parted} texels; strands {'at ' + str(a.strands) if B is not None else 'none'}")


if __name__ == "__main__":
    main()
