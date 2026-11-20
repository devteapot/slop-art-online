#!/usr/bin/env python3
"""A stand-in for S4's and S5's generator output, so the client's composed `slop` (contract
v1.3, docs/HANDMADE_COMPOSED.md) can be drawn, measured and audited before the generator writes
it. It copies an asset tree's `lookdev/` and opts every type file and hair style in:

    uv run --with numpy --with pillow --with scipy python living/tools/characters/composed_fixture.py \\
        SRC/lookdev OUT/lookdev [--hair-density-mm 2.0] [--profile PROFILE.json]

- **Every type file** gains two ink carriers on its face mesh, built from its own eyeline and
  brow primitives: the same skin, normals, indices and morph targets, positions lifted 0.3 mm
  along the normal, and a new TEXCOORD_0 in its class's cell of the ink page (a front-plane
  projection at 0.5 mm a texel: the contract's 0.25 mm is for S4's stroke strips, and today's
  whole eyeline with its lash cards is about 210 mm across). Materials `M00_000_00_LidInk_00_FACE` (absolute colour) and
  `M00_000_00_FaceBrowInk_00_FACE` (`ref`: it follows the hair tag), both BLEND with base alpha 0,
  `slot` eyes, `width` px, `map` the page. Today's types don't share topology across a class's
  lines, so each type takes a quadrant of its class's cell (`fixture_type_quadrants` in the
  manifest), which the audit's class check reports as a difference from the contract. The originals stay, so a person draws two more
  primitives than S4's would (S4 removes the old lines): an upper bound for cost.
- **The ink page** `types/types.eyes.ink.png` (4096², cells 1024² by class) holds the
  carriers' UV island borders as lines (G the distance over `range`, R 255), and
  `types/types.ink.json` its manifest.
- **Every hair style's hair** (Hair and FarHair) gets a new TEXCOORD_0: a cylindrical
  projection about the head's vertical axis, into the file's 512² cell of the hair-mask page.
  Files with identical hair share a cell. Its texture is dropped (a profile ignores the base RGB),
  and it carries the profile (`--profile`, default Cora's palette relative to auburn with a dark
  anchor) with `highlight_map` the page and `ink_m_uv` the density.
- **The hair-mask page** `styles/hair/hair-masks.png` (4096², 8 × 8 cells of 512²): R a broad
  highlight over the upper front of each cut, G lock lines along the hair every 24 mm, and
  `styles/hair/hair-masks.json`.
- **Scenes** declare `{"slop": {"contract": 1}}`; everything else in OUT is a link to SRC.

The density differs from the contract's 1.0 mm a texel for hair (`--hair-density-mm`, default 2):
a cylindrical projection is not S5's packed lock islands, and at 1 mm a cut would take 2 × 1
cells, which the 64 cells don't hold. The client takes the declared `ink_m_uv` either way.
"""

import argparse
import copy
import hashlib
import json
import os
import struct
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

PAGE = 4096
INK_CELL = 1024
HAIR_CELL = 512
INK_MM = 0.5  # the contract's 0.25 mm holds S4's stroke strips; today's whole eyeline needs 0.5 mm to fit a quadrant
CLASSES = ["child-u", "youth-f", "youth-m", "adult-f", "adult-m", "elder-f", "elder-m"]
CLASS_CELLS = {c: [i % 4, i // 4] for i, c in enumerate(CLASSES)}
AUBURN = [102, 46, 26]
PROFILE = {
    "palette": "tag", "ref": AUBURN,
    "shade": [44, 8, 2], "mid": [104, 37, 8], "light": [119, 43, 6], "highlight": [135, 47, 3],
    "t1": -0.2, "t2": 0.4, "edge": 0.02, "highlight_feather": 0.08,
    "ink": [4, 0, 0], "ink_px": 1.05, "ink_fade_px": 2.0,
    "anchors": [{"ref": [19, 17, 17], "shade": [12, 10, 11], "mid": [30, 26, 27], "light": [38, 33, 34], "highlight": [52, 46, 47], "ink": [2, 1, 1]}],
}
LID = {"color": [20, 10, 10], "width": "px", "px": 1.25}
BROW = {"color": [57, 32, 20], "ref": AUBURN, "width": "px", "px": 1.25}
INK_RANGE_TEXELS = 24


class Glb:
    def __init__(self, path):
        f = open(path, "rb").read()
        n = struct.unpack("<I", f[12:16])[0]
        self.j = json.loads(f[20:20 + n])
        rest = f[20 + n:]
        self.bin = bytearray(rest[8:8 + struct.unpack("<I", rest[0:4])[0]]) if rest else bytearray()

    def read(self, i):
        a = self.j["accessors"][i]
        bv = self.j["bufferViews"][a["bufferView"]]
        comps = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        dt = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}[a["componentType"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride", 0)
        item = np.dtype(dt).itemsize * comps
        if stride and stride != item:
            raw = np.frombuffer(bytes(self.bin), dtype=np.uint8)
            rows = [np.frombuffer(raw[off + k * stride: off + k * stride + item].tobytes(), dtype=dt) for k in range(a["count"])]
            return np.array(rows).reshape(a["count"], comps) if comps > 1 else np.array(rows).reshape(-1)
        arr = np.frombuffer(bytes(self.bin[off:off + item * a["count"]]), dtype=dt)
        return arr.reshape(a["count"], comps) if comps > 1 else arr

    def add(self, arr, kind, target=34962):
        arr = np.ascontiguousarray(arr, dtype=np.float32)
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin += arr.tobytes()
        self.j["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes, "target": target})
        acc = {"bufferView": len(self.j["bufferViews"]) - 1, "componentType": 5126, "count": int(arr.shape[0]), "type": kind}
        if kind == "VEC3":
            acc["min"] = arr.min(axis=0).tolist()
            acc["max"] = arr.max(axis=0).tolist()
        self.j["accessors"].append(acc)
        return len(self.j["accessors"]) - 1

    def write(self, path):
        while len(self.bin) % 4:
            self.bin.append(0)
        self.j["buffers"][0]["byteLength"] = len(self.bin)
        js = json.dumps(self.j, separators=(",", ":")).encode()
        js += b" " * ((4 - len(js) % 4) % 4)
        out = struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(self.bin)) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(self.bin), 0x004E4942) + bytes(self.bin)
        tmp = path + ".tmp"
        open(tmp, "wb").write(out)
        os.replace(tmp, path)

    def opt_in(self):
        sc = self.j["scenes"][self.j.get("scene", 0)]
        sc.setdefault("extras", {})["slop"] = {"contract": 1}


def link_tree(src, out, real):
    """OUT mirrors SRC with links, except the directories in `real` (relative), which are made
    real with their entries linked, so files in them can be replaced."""
    os.makedirs(out, exist_ok=True)
    for name in sorted(os.listdir(src)):
        s, o = os.path.join(src, name), os.path.join(out, name)
        rel = os.path.relpath(o, out_root)
        if any(r == rel or r.startswith(rel + "/") for r in real):
            link_tree(s, o, real)
        elif not os.path.lexists(o):
            os.symlink(os.path.abspath(s), o)


def class_of(t):
    return t.rsplit("-", 1)[0]


def carriers(src_types, out_types, page_rel):
    """Carriers on every type, their UVs in the class's cell, and the page's line segments."""
    types = sorted(f[:-4] for f in os.listdir(src_types) if f.endswith(".glb"))
    layout = {}  # class -> (prim index -> uv)
    segs = []
    report = {}
    m_uv = INK_MM * PAGE / 1000.0
    for t in types:
        g = Glb(os.path.join(src_types, t + ".glb"))
        mats = [m["name"] for m in g.j["materials"]]
        face = next(n for n in g.j["nodes"] if n.get("name") == "Face")
        mesh = g.j["meshes"][face["mesh"]]
        picks = [(i, p) for i, p in enumerate(mesh["primitives"]) if mats[p["material"]].endswith(("FaceEyeline_00_FACE", "FaceBrow_00_FACE"))]
        cls = class_of(t)
        # The class's cell, a quadrant a line: today's types don't share their eyeline's topology
        # across a class's lines (S4's carriers will), so each type is laid out on its own, in its
        # line's quadrant (a, b, c), and the audit's class check reports it.
        line = "abc".index(t.rsplit("-", 1)[1]) if t.rsplit("-", 1)[1] in "abc" else 3
        pos = {i: g.read(p["attributes"]["POSITION"]) for i, p in picks}
        allp = np.concatenate(list(pos.values()))
        x0, y1 = allp[:, 0].min(), allp[:, 1].max()
        col, row = CLASS_CELLS[cls]
        q = INK_CELL // 2
        corner = np.array([col * INK_CELL + (line % 2) * q, row * INK_CELL + (line // 2) * q], float)
        origin = (corner + 24) / PAGE
        ref = {}
        for i, _ in picks:
            p = pos[i]
            uv = origin + np.stack([(p[:, 0] - x0), (y1 - p[:, 1])], axis=1) / m_uv
            assert (uv.max(axis=0) * PAGE < corner + q).all(), f"{t}: carriers do not fit the quadrant ({uv.max(axis=0) * PAGE - corner})"
            ref[i] = (len(p), uv)
        layout[t] = [int(corner[0]), int(corner[1]), q]
        for i, p in picks:
            idx = g.read(p["indices"]).reshape(-1, 3)
            uv = ref[i][1]
            edges = {}
            for tri in idx:
                for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                    k = (min(a, b), max(a, b))
                    edges[k] = edges.get(k, 0) + 1
            segs += [(uv[a], uv[b]) for (a, b), n in edges.items() if n == 1]
        new_mats = {}
        for name, ink in (("M00_000_00_LidInk_00_FACE", LID), ("M00_000_00_FaceBrowInk_00_FACE", BROW)):
            g.j["materials"].append({"name": name, "alphaMode": "BLEND", "doubleSided": False,
                                     "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 0], "metallicFactor": 0, "roughnessFactor": 1},
                                     "extras": {"slop": {"slot": "eyes", "ink": dict(ink, map=page_rel, range=INK_RANGE_TEXELS / PAGE, m_uv=m_uv)}}})
            new_mats[name] = len(g.j["materials"]) - 1
        for i, p in picks:
            count, uv = ref[i]
            pos = g.read(p["attributes"]["POSITION"])
            nrm = g.read(p["attributes"]["NORMAL"])
            attrs = {k: v for k, v in p["attributes"].items() if k in ("NORMAL", "JOINTS_0", "WEIGHTS_0")}
            attrs["POSITION"] = g.add(pos + nrm * 0.0003, "VEC3")
            attrs["TEXCOORD_0"] = g.add(uv, "VEC2")
            name = "M00_000_00_FaceBrowInk_00_FACE" if mats[p["material"]].endswith("FaceBrow_00_FACE") else "M00_000_00_LidInk_00_FACE"
            prim = {"attributes": attrs, "indices": p["indices"], "material": new_mats[name], "mode": p.get("mode", 4)}
            if "targets" in p:
                prim["targets"] = copy.deepcopy(p["targets"])
            mesh["primitives"].append(prim)
        g.opt_in()
        g.write(os.path.join(out_types, t + ".glb"))
        report[t] = {"class": cls, "cell": CLASS_CELLS[cls], "carriers": len(picks)}
    return segs, report, m_uv, layout


def ink_page(segs, path, range_texels):
    """G: the distance to the nearest segment (texels, over range), R 255, B 0."""
    lines = np.zeros((PAGE, PAGE), bool)
    for a, b in segs:
        a, b = np.asarray(a) * PAGE, np.asarray(b) * PAGE
        n = max(2, int(np.ceil(np.linalg.norm(b - a) * 4)))
        for t in np.linspace(0, 1, n):
            x, y = a + (b - a) * t
            lines[min(PAGE - 1, int(y)), min(PAGE - 1, int(x))] = True
    d = ndimage.distance_transform_edt(~lines)
    g = np.clip(np.round(255 * np.minimum(1, d / range_texels)), 0, 255).astype(np.uint8)
    img = np.stack([np.full_like(g, 255), g, np.zeros_like(g)], axis=2)
    Image.fromarray(img, "RGB").save(path)
    return int((g == 0).sum())


def hair(src_hair, out_hair, page_rel, density_mm, profile):
    """Every cut's hair into its cell, the profile on it; the page's highlight and lock lines."""
    files = sorted(f for f in os.listdir(src_hair) if f.endswith(".glb"))
    cells, by_hash, report = {}, {}, {}
    m_uv = density_mm * PAGE / 1000.0
    hl = np.zeros((PAGE, PAGE), np.uint8)
    lines = np.zeros((PAGE, PAGE), bool)
    spacing = 0.024 / m_uv  # lock lines every 24 mm, in UV
    for f in files:
        g = Glb(os.path.join(src_hair, f))
        mats = [m["name"] for m in g.j["materials"]]
        prims = [(n["name"], p) for n in g.j["nodes"] if "mesh" in n for p in g.j["meshes"][n["mesh"]]["primitives"] if mats[p["material"]].endswith("_HAIR")]
        h = hashlib.sha256()
        for _, p in prims:
            h.update(g.read(p["attributes"]["POSITION"]).tobytes())
        key = h.hexdigest()
        if key not in by_hash:
            by_hash[key] = len(by_hash)
        k = by_hash[key]
        if k >= 64:
            sys.exit("more than 64 distinct cuts: a second page is needed")
        col, row = k % 8, k // 8
        cells[f] = [col, row, 1, 1]
        near = np.concatenate([g.read(p["attributes"]["POSITION"]) for n, p in prims if n == "Hair"])
        cx, cz = (near[:, 0].min() + near[:, 0].max()) / 2, (near[:, 2].min() + near[:, 2].max()) / 2
        top = near[:, 1].max()
        r = np.median(np.hypot(near[:, 0] - cx, near[:, 2] - cz))
        origin = np.array([col * HAIR_CELL + 8, row * HAIR_CELL + 8], float) / PAGE
        span = (HAIR_CELL - 16) / PAGE
        for n, p in prims:
            pos = g.read(p["attributes"]["POSITION"])
            ang = np.arctan2(pos[:, 0] - cx, -(pos[:, 2] - cz))  # 0 at the front (-Z)
            u = (ang + np.pi) * r / m_uv
            v = (top - pos[:, 1]) / m_uv
            uv = origin + np.stack([np.clip(u, 0, span), np.clip(v, 0, span)], axis=1)
            p["attributes"]["TEXCOORD_0"] = g.add(uv, "VEC2")
        # The page's cell: a broad highlight over the upper front, lock lines down the hair.
        x0, y0 = col * HAIR_CELL + 8, row * HAIR_CELL + 8
        w = HAIR_CELL - 16
        front_u = np.pi * r / m_uv * PAGE
        band_u = 0.9 * r / m_uv * PAGE
        vv = np.arange(w)[:, None] / PAGE * m_uv
        uu = (np.arange(w)[None, :] - front_u) / PAGE * m_uv / max(r, 1e-3)
        mask = (np.abs(uu) < 1.2) & (vv > 0.03 + 0.01 * np.cos(uu * 9)) & (vv < 0.10 + 0.015 * np.cos(uu * 7))
        hl[y0:y0 + w, x0:x0 + w] = np.where(mask, 255, 0)
        step = max(2, int(round(spacing * PAGE)))
        lines[y0:y0 + w, x0:x0 + w:step] = True
        mat = g.j["materials"][next(i for i, m in enumerate(mats) if m.endswith("_HAIR"))]
        mat.get("pbrMetallicRoughness", {}).pop("baseColorTexture", None)
        mat.setdefault("extras", {})["slop"] = {"slot": "hair", "hair": dict(profile, highlight_map=page_rel, ink_range=round(spacing / 2, 6), ink_m_uv=m_uv)}
        g.opt_in()
        g.write(os.path.join(out_hair, f))
        report[f] = cells[f]
    rng = spacing / 2 * PAGE
    d = ndimage.distance_transform_edt(~lines)
    gch = np.clip(np.round(255 * np.minimum(1, d / rng)), 0, 255).astype(np.uint8)
    img = np.stack([hl, gch, np.zeros_like(hl)], axis=2)
    Image.fromarray(img, "RGB").save(os.path.join(out_hair, "hair-masks.png"))
    return cells, m_uv, len(by_hash)


def main():
    global out_root
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="the lookdev folder to copy (its files are only read)")
    ap.add_argument("out", help="a new lookdev folder: links to SRC plus the opted-in files")
    ap.add_argument("--hair-density-mm", type=float, default=2.0)
    ap.add_argument("--profile", help="a JSON hair profile instead of the default (Cora's, relative to auburn, with a dark anchor)")
    a = ap.parse_args()
    out_root = os.path.abspath(a.out)
    src = os.path.abspath(a.src)
    if os.path.realpath(out_root).startswith(os.path.realpath(src)):
        sys.exit("OUT must not be inside SRC")
    link_tree(src, out_root, ["types", "styles", "styles/hair"])
    for d in ("types", "styles/hair"):
        for f in os.listdir(os.path.join(out_root, d)):
            if f.endswith(".glb") and os.path.islink(os.path.join(out_root, d, f)):
                os.unlink(os.path.join(out_root, d, f))
    profile = json.load(open(a.profile)) if a.profile else PROFILE
    page = "lookdev/types/types.eyes.ink.png"
    segs, types, m_uv, quads = carriers(os.path.join(src, "types"), os.path.join(out_root, "types"), page)
    lines = ink_page(segs, os.path.join(out_root, "types", "types.eyes.ink.png"), INK_RANGE_TEXELS)
    json.dump({"pages": {"eyes": page}, "size": PAGE, "cell": INK_CELL, "density_mm": INK_MM, "classes": CLASS_CELLS, "types": {}, "fixture_type_quadrants": quads}, open(os.path.join(out_root, "types", "types.ink.json"), "w"), indent=1)
    hpage = "lookdev/styles/hair/hair-masks.png"
    cells, hm_uv, cuts = hair(os.path.join(src, "styles/hair"), os.path.join(out_root, "styles/hair"), hpage, a.hair_density_mm, profile)
    json.dump({"page": hpage, "size": PAGE, "cell": HAIR_CELL, "density_mm": a.hair_density_mm, "files": cells}, open(os.path.join(out_root, "styles/hair", "hair-masks.json"), "w"), indent=1)
    print(f"types: {len(types)} with carriers (m_uv {m_uv}), ink page {lines} line texels, {len(segs)} segments")
    print(f"hair: {len(cells)} files, {cuts} cells (m_uv {hm_uv})")


if __name__ == "__main__":
    main()
