#!/usr/bin/env python3
"""Build a shared style file round one shading mean, so one material can serve every file of its class.

    python3 living/tools/characters/shade_mean.py outfit|hair|overlay FILE.glb [...]
    python3 living/tools/characters/shade_mean.py --check DIR

The client tints a person's pieces through each mesh's tag: a material holds the mean colour of
what it draws, and the shader moves that mean to the person's colour, keeping the detail round
it. A material can then be shared by everyone wearing a file, and no further: every file's mean
differed, so every hair cut, outfit piece and overlay was a material of its own (96 on Cullet's 64
at the play camera, where whole-person files made 20). Here each class is given one mean:

- **outfit** (`…Cloth_01_CLOTH`, vertex colours, no picture): the colours become grey shading
  (each vertex's lightness) scaled so the mesh's mean, weighted by area and in linear light as the
  client measures it, is `CLOTH` for every piece and its far mesh. A piece's own colour is then
  only the person's (`colors.outfit` in their line names every piece worn), and what was another
  hue inside a piece (a coat's patches, its lining) is a lighter or darker tone of it.
- **hair** (`…Hair_00_HAIR`, the shared picture of strands times vertex colours): the vertex
  colours, already neutral, are scaled so the mean of a mesh's outer surfaces (its lighter half
  by area; the inner surfaces are dark) is `HAIR` in every cut and its far mesh. The
  picture is one file for all, so its mean is one already. A style's tie is left as it is: it has
  no tag and keeps its own colour.
- **overlay** (a grey picture with an alpha, a file): the picture's mean over what it covers is
  scaled to `OVERLAY` (a light grey, so that tinting it to a person's colour only darkens it). An overlay still has a picture of its own (and lines and freckles their
  type's shadow map), so it stays a material a file; equal means only make one tint come out the
  same on every type.

`--check` prints each file's means by class and fails if one is off. Plain Python, numpy and Pillow.
"""

import glob
import io
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from merge_primitives import read_accessor, read_glb, write_glb  # noqa: E402

CLOTH = 0.48    # an outfit piece's mean lightness, linear: above every cloth colour worn, so the client's tint only darkens (it lightens another way, which flattens a piece's darker tones)
HAIR = 0.78     # the mean vertex colour of a hair mesh's outer surfaces (its lighter half), as stored
OVERLAY = 0.90  # an overlay picture's mean grey over what it covers, as stored (sRGB): high, so a tint is a darkening
LUM = np.array([0.2126, 0.7152, 0.0722])
TOL = 0.004


def _colours(j, binary, p):
    """A primitive's vertex colours as floats (n×3 or n×4), with what is needed to write them back."""
    acc = j["accessors"][p["attributes"]["COLOR_0"]]
    n = 4 if acc["type"] == "VEC4" else 3
    scale = {5126: 1.0, 5123: 65535.0, 5121: 255.0}[acc["componentType"]]
    col = np.array(read_accessor(j, binary, p["attributes"]["COLOR_0"])[0], float).reshape(-1, n) / scale
    return col, acc, n, scale


def _write(j, binary, acc, col, n, scale):
    bv = j["bufferViews"][acc["bufferView"]]
    fmt = {5126: "f", 5123: "H", 5121: "B"}[acc["componentType"]]
    size = struct.calcsize(fmt) * n
    stride = bv.get("byteStride") or size
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    vals = col if scale == 1.0 else np.clip(np.rint(col * scale), 0, scale).astype(np.int64)
    for i, row in enumerate(vals):
        struct.pack_into("<" + fmt * n, binary, start + i * stride, *(row.tolist()))
    if "min" in acc:
        acc["min"] = [float(x) for x in (vals.min(axis=0) if scale == 1.0 else vals.min(axis=0))]
        acc["max"] = [float(x) for x in (vals.max(axis=0) if scale == 1.0 else vals.max(axis=0))]


def _areas(j, binary, p):
    pos = np.array(read_accessor(j, binary, p["attributes"]["POSITION"])[0], float).reshape(-1, 3)
    idx = np.array(read_accessor(j, binary, p["indices"])[0], np.int64).reshape(-1, 3)
    return idx, np.linalg.norm(np.cross(pos[idx[:, 1]] - pos[idx[:, 0]], pos[idx[:, 2]] - pos[idx[:, 0]]), axis=1)


def _prims(j, want):
    """(mesh, primitives) for the meshes whose materials' names contain `want` and have no picture."""
    for mesh in j["meshes"]:
        ps = []
        for p in mesh["primitives"]:
            m = j["materials"][p["material"]]
            if want in m.get("name", "") and "COLOR_0" in p["attributes"]:
                ps.append(p)
        if ps:
            yield mesh, ps


def mesh_mean(j, binary, ps, grey, outer=False):
    """A mesh's mean vertex colour weighted by area (its lightness when `grey`). `outer`: over
    its lighter half only. A sheet of hair has a dark inner surface as large as its outer one;
    the mean of both would be set by what is not seen."""
    vs, areas = [], []
    for p in ps:
        col, _, _, _ = _colours(j, binary, p)
        idx, a = _areas(j, binary, p)
        v = col[:, :3] @ LUM if grey else col[:, :3].mean(axis=1)
        vs.append(v[idx].mean(axis=1))
        areas.append(a)
    v, a = np.concatenate(vs), np.concatenate(areas)
    if outer:
        order = np.argsort(v)
        half = np.searchsorted(np.cumsum(a[order]), 0.5 * a.sum())
        keep = order[half:]
        v, a = v[keep], a[keep]
    return float((v * a).sum() / max(a.sum(), 1e-12))


def outfit(j, binary):
    """Grey shading round CLOTH for every cloth mesh without a picture."""
    out = []
    for mesh, ps in _prims(j, "_CLOTH"):
        ps = [p for p in ps if "baseColorTexture" not in (j["materials"][p["material"]].get("pbrMetallicRoughness") or {})]
        if not ps:
            continue
        k = CLOTH / max(mesh_mean(j, binary, ps, True), 1e-9)
        for _ in range(3):  # a clipped vertex pulls the mean down a hair: scale again
            for p in ps:
                col, acc, n, scale = _colours(j, binary, p)
                g = np.clip((col[:, :3] @ LUM) * k, 0.0, 1.0)
                col[:, :3] = g[:, None]
                _write(j, binary, acc, col, n, scale)
            k = CLOTH / max(mesh_mean(j, binary, ps, True), 1e-9)
            if abs(k - 1) < 1e-4:
                break
        out.append((mesh["name"], mesh_mean(j, binary, ps, True)))
    return out


def hair(j, binary):
    """The same mean vertex colour for every hair mesh; a tie (cloth) is left alone."""
    out = []
    for mesh, ps in _prims(j, "_HAIR"):
        k = HAIR / max(mesh_mean(j, binary, ps, False, outer=True), 1e-9)
        for _ in range(8):  # a highlight that clips pulls the mean down: scale again
            for p in ps:
                col, acc, n, scale = _colours(j, binary, p)
                col[:, :3] = np.clip(col[:, :3] * k, 0.0, 1.0)
                _write(j, binary, acc, col, n, scale)
            k = HAIR / max(mesh_mean(j, binary, ps, False, outer=True), 1e-9)
            if abs(k - 1) < 5e-4:
                break
        out.append((mesh["name"], mesh_mean(j, binary, ps, False, outer=True)))
    return out


def _pictures(j):
    """Each embedded RGBA picture a material with an alpha uses: (image index, material name)."""
    seen = {}
    for m in j["materials"]:
        tex = (m.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
        if tex is None or m.get("alphaMode") != "BLEND" or m.get("name", "").endswith("_FACE"):  # a fixed colour is no shading mean
            continue
        ii = j["textures"][tex["index"]]["source"]
        if "bufferView" in j["images"][ii]:
            seen.setdefault(ii, m.get("name", ""))
    return seen.items()


def _load(j, binary, ii):
    from PIL import Image

    bv = j["bufferViews"][j["images"][ii]["bufferView"]]
    return np.asarray(Image.open(io.BytesIO(bytes(binary[bv.get("byteOffset", 0) : bv.get("byteOffset", 0) + bv["byteLength"]]))).convert("RGBA"), float) / 255.0


def picture_mean(pic):
    a = pic[..., 3]
    return float(((pic[..., :3].mean(axis=2)) * a).sum() / max(a.sum(), 1e-9))


def overlay(j, binary):
    """Scale each overlay picture's grey so its mean over what it covers is OVERLAY."""
    from PIL import Image

    out = []
    for ii, name in _pictures(j):
        pic = _load(j, binary, ii)
        k = OVERLAY / max(picture_mean(pic), 1e-9)
        for _ in range(4):
            pic[..., :3] = np.clip(pic[..., :3] * k, 0.0, 1.0)
            k = OVERLAY / max(picture_mean(pic), 1e-9)
            if abs(k - 1) < 1e-3:
                break
        data = io.BytesIO()
        Image.fromarray((pic * 255 + 0.5).astype(np.uint8), "RGBA").save(data, format="PNG")
        while len(binary) % 4:
            binary.append(0)
        j["bufferViews"].append(dict(buffer=0, byteOffset=len(binary), byteLength=len(data.getvalue())))
        binary.extend(data.getvalue())
        j["images"][ii]["bufferView"] = len(j["bufferViews"]) - 1
        j["images"][ii]["mimeType"] = "image/png"
        out.append((name, picture_mean(pic)))
    return out


def measure(path):
    """A file's means by class: [(class, name, mean, target)]."""
    j, binary = read_glb(path)
    rows = []
    kind = os.path.relpath(path).replace(os.sep, "/").split("/styles/")[-1].split("/")[0]
    if kind == "outfit":
        for mesh, ps in _prims(j, "_CLOTH"):
            rows.append(("cloth", mesh["name"], mesh_mean(j, binary, ps, True), CLOTH))
    for mesh, ps in _prims(j, "_HAIR"):
        if any("baseColorTexture" in (j["materials"][p["material"]].get("pbrMetallicRoughness") or {}) for p in ps) and kind == "hair":
            rows.append(("hair", mesh["name"], mesh_mean(j, binary, ps, False, outer=True), HAIR))
    for ii, name in _pictures(j):
        if kind == "overlay":
            rows.append(("overlay", name, picture_mean(_load(j, binary, ii)), OVERLAY))
    return rows


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        bad, n = 0, 0
        files = sorted(glob.glob(os.path.join(sys.argv[2], "**", "*.glb"), recursive=True))
        for f in files:
            for cls, name, mean, target in measure(f):
                n += 1
                if abs(mean - target) > TOL + (0.01 if cls == "overlay" else 0.0):
                    bad += 1
                    print(f"shade_mean: {f}: {cls} {name}: mean {mean:.3f}, wants {target:.2f}")
        print(f"shade_mean: {len(files)} files, {n} meshes and pictures checked, {bad} off their class's mean")
        sys.exit(1 if bad else 0)
    if len(sys.argv) < 3 or sys.argv[1] not in ("outfit", "hair", "overlay"):
        sys.exit(__doc__)
    do = dict(outfit=outfit, hair=hair, overlay=overlay)[sys.argv[1]]
    for path in sys.argv[2:]:
        j, binary = read_glb(path)
        binary = bytearray(binary)
        done = do(j, binary)
        import share

        binary = share.compact(j, binary)  # an overlay's old picture
        write_glb(path, j, binary)
        print(f"shade_mean: {path}: " + (", ".join(f"{n} {m:.3f}" for n, m in done) or "nothing of this class"))


if __name__ == "__main__":
    main()
