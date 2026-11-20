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
  hair material loses its texture and takes `slop.hair` (the profile below, the same object on every
  file of the page, `highlight_map` the page); the scene opts in (`slop` `{"contract": 1}`).
- **The page.** R: the highlight, each file's `_HIGHLIGHT` rasterised from its near `Hair` mesh.
  G: the lock lines' distance field over `ink_range` (HANDMADE_HAIR v1.1; 255 is no line). B 0.
- **The manifest**, `hair-masks.json`: `{"page", "size", "cell", "density_mm", "files": {name: [col,
  row, w, h]}}` (the first page) and, when there is more than one, `"pages"`: each page's `page`
  and `files`. The generator's 86 files take 190 cells: three pages (docs/char-port-2/s5).
- **`--profile-only`:** the files already on the page keep their places; only their `slop.hair` is
  written again (with `--profile`, the profile's own swatches; with `--anchors`, the anchors), as
  the calibration (docs/char-port-2/s5/calibrate_bins.py) does each round.

**The profile:** Cora's accepted swatches at their hair colour, auburn (`ref`), thresholds and lock
ink, relative to the tag (`palette: "tag"`), with an anchor for each other colour bin (`--anchors`,
or this file's ANCHORS: dark, light and grey), as calibrated in docs/char-port-2/s5.
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

PAGE, CELL = 4096, 512
GRID = PAGE // CELL
DENSITY_MM = 1.0
PAGE_PATH = "lookdev/styles/hair/hair-masks.png"
AUBURN = [102, 46, 26]
# At auburn: Cora's accepted hair (docs/char-live-3/ink-batch-2/own-cora-live.glb) as calibrated on a
# composed person against the drawing's hair patches (docs/char-port-2/s5/calibrate_bins.py).
PROFILE = dict(palette="tag", ref=AUBURN, shade=[38, 1, 0], mid=[101, 34, 6], light=[119, 44, 5], highlight=[139, 53, 3],
               t1=-0.2, t2=0.4, edge=0.02, highlight_feather=0.08, ink=[4, 0, 0], ink_px=1.05, ink_fade_px=2.0)
# One anchor a colour bin besides auburn (HANDMADE_COMPOSED "Several anchors"); calibrated in
# docs/char-port-2/s5 (anchors.json there, passed with --anchors).
ANCHORS = [{"ref": [19, 17, 17], "shade": [0, 0, 10], "mid": [38, 39, 48], "light": [48, 49, 57], "highlight": [69, 69, 79]}, {"ref": [158, 125, 71], "shade": [83, 64, 28], "mid": [162, 125, 56], "light": [198, 163, 105], "highlight": [227, 222, 213]}, {"ref": [133, 133, 133], "shade": [61, 67, 79], "mid": [121, 128, 142], "light": [155, 162, 178], "highlight": [211, 219, 239]}]


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
    a = ap.parse_args()
    anchors = json.load(open(a.anchors)) if a.anchors else ANCHORS
    if a.profile:
        PROFILE.update(json.load(open(a.profile)))
    if a.profile_only:
        n = 0
        for g in sorted(glob.glob(os.path.join(a.folder, "*.glb"))):
            j, binary = read_glb(g)
            done = False
            for _, p in hair_prims(j):
                h = j["materials"][p["material"]].get("extras", {}).get("slop", {}).get("hair")
                if h is None:
                    continue
                for k in list(h):
                    if k in PROFILE or k == "anchors":
                        h.pop(k)
                h.update(PROFILE)
                if anchors:
                    h["anchors"] = anchors
                done = True
            if done:
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
    D = [np.full((PAGE, PAGE), float(rng), np.float32) for _ in range(n_pages)]
    page_path = lambda k: PAGE_PATH if k == 0 else PAGE_PATH.replace(".png", f"-{k}.png")
    for name, sp, _ in files:
        k, c, r, w, h = cells[name]
        off = np.array([c * CELL, r * CELL], float)
        path = os.path.join(a.folder, name)
        j, binary = read_glb(path)
        profile = dict(PROFILE, ink_range=rng / PAGE, ink_m_uv=PAGE * DENSITY_MM / 1000, highlight_map=page_path(k))
        if anchors:
            profile["anchors"] = anchors
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
            mat = j["materials"][p["material"]]
            mat.get("pbrMetallicRoughness", {}).pop("baseColorTexture", None)
            mat.setdefault("extras", {})["slop"] = {"slot": "hair", "hair": profile}
            if mesh_name == "Hair" and "_HIGHLIGHT" in p["attributes"]:
                hl, _ = accessor(j, binary, p["attributes"]["_HIGHLIGHT"])
                idx, _ = accessor(j, binary, p["indices"])
                raster_highlight(R[k], px + off, idx.reshape(-1, 3), hl[:, 0].astype(np.float64))
        scene = j["scenes"][j.get("scene", 0)]
        slop = scene.setdefault("extras", {}).setdefault("slop", {})
        slop.pop("character", None)
        slop["contract"] = 1
        write_glb(path, j, binary)
        lines_field(D[k], [np.asarray(l, float) + off for l in sp["creases"]], rng)
    for k in range(n_pages):
        img = np.zeros((PAGE, PAGE, 3), np.uint8)
        img[..., 0] = np.round(np.clip(R[k], 0, 1) * 255)
        img[..., 1] = np.round(np.clip(D[k] / rng, 0, 1) * 255)
        Image.fromarray(img, "RGB").save(os.path.join(a.folder, os.path.basename(page_path(k))))
    manifest = dict(page=PAGE_PATH, size=PAGE, cell=CELL, density_mm=DENSITY_MM, files={n: v[1:] for n, v in cells.items() if v[0] == 0})
    if n_pages > 1:
        manifest["pages"] = [dict(page=page_path(k), files={n: v[1:] for n, v in cells.items() if v[0] == k}) for k in range(n_pages)]
    json.dump(manifest, open(os.path.join(a.folder, "hair-masks.json"), "w"), indent=1)
    used = sum(v[3] * v[4] for v in cells.values())
    print(f"hair_page: {len(files)} files on {n_pages} page(s), {used} cells of {n_pages * GRID * GRID}; lines from {sum(len(sp['creases']) for _, sp, _ in files)} creases")


if __name__ == "__main__":
    main()
