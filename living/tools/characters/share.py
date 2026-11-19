#!/usr/bin/env python3
"""Put generated people's textures on files they share, so a crowd of them is a handful of
materials and not three a person (docs/CHARACTERS.md, "Crowd cost").

    python3 living/tools/characters/share.py strands GLB [GLB ...]
    python3 living/tools/characters/share.py pages --name cullet [--tile 1024] [--page 4096] [--dir DIR] [--which near|far] GLB [GLB ...]
    python3 living/tools/characters/share.py types [--dir DIR] TYPE.glb [TYPE.glb ...]
    python3 living/tools/characters/share.py clips GLB [GLB ...]
    python3 living/tools/characters/share.py list GLB [GLB ...]

The game makes one toon material for every distinct material content (lookdev.rs `convert`), and
a texture is part of that content. A character file that carries its own copy of a picture
therefore brings its own material, even when the picture is the same for everyone. A picture
that a file names by path is loaded once and shared by every file that names it (Bevy loads an
image's `uri` through the asset server), so those files' materials become one.

- `strands`: the hair's strand texture is the same for everyone (hair.paint_strands). Each
  file's embedded copy is replaced by the path of the one `strands.png` beside the models.
  gen_person.sh does this for every person.
- `pages`: the faces' atlases (the face's skin and the eyes; for a far model its one picture) of
  a set of people are laid out as tiles on shared pages, `<dir>/<name>-<n>.png`. Each file's UVs
  are moved into its tile and its embedded atlas is replaced by the page's path. The faces'
  shadow maps (face_normals.py's `<model>.face.png`) are laid out the same way as
  `<name>-<n>.face.png`; the per-person files are removed, and each face material's `extras`
  name the page's map (`face_map`, a path under the asset folder). `<name>.json` records who is
  on which tile. town.py does this for a town. A file with the full and the far model
  (`--lod both`) has two atlases: `--which near` pages the full model's, `--which far` the far
  model's picture (its image is named `<person>.far`).
- `types`: the face types' own small pictures (lookdev/types/<type>.glb) are laid out on two
  pages every type shares: `<dir>/types-far.png` (the far head's picture) and `types-tint.png`
  (lips and blush, with its alpha; only the band of the picture its mesh uses). A type's place
  on a page is fixed by its place in types.json, so one type built again goes back into its own
  tile. `<dir>/types.json` records the tiles. The types' far heads and lip layers are then one
  material each for every type, where each type brought its own.
  - The far head's picture is recoloured by the client, which learns a material's mean colour
    once, from the first mesh that wears it. So each tile's colours are moved as the client
    moves them (one turn of hue, one ratio of saturation and of value, in linear light) until
    its mean over the texels its mesh's vertices use is `FAR_MEAN`, and the page's empty tiles
    are that colour. The types' own means are within 1% of it, so nothing shows.
  - The iris stays each type's own picture. The types' irises are painted in different
    colours (brown, blue, grey: mean value 0.06 to 0.12, saturation 0.15 to 0.80), and the
    client's move from a mean to a person's colour is not one that can be made in two steps:
    it multiplies below the mean and lightens above it. Moved to one mean and shared, the same
    eye colour came out as another on some types (simulated with the client's formula: up to
    40 of 255 a texel). One picture for every type's iris would share; that is a change to
    how every composed person's eyes are coloured, to be judged on the board first.
  - The full head's atlas and its shadow map stay the type's own.
- `clips`: every generated person has the same skeleton, so the game takes their clips from one
  shared clip file (`lookdev/anim/own-clips.glb`, anim.rs `clip_file`). Each file's own clips
  (its `animations` and their data) and its `.clips.json` are removed.
- `list`: each file's meshes, materials and pictures, to check.

The atlas wraps round the back of the head (head_mesh.py): faces across that seam have
vertices a full turn on in u. A tile cannot wrap, so those are held at the tile's edge; the
skin there is plain and under the hair.

The client reads `face_map` from a face material's extras (lookdev.rs `convert`); a client from
before crowd-1 shades paged faces as skin.
"""

import argparse
import io
import json
import math
import os
import struct
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from merge_primitives import read_glb, write_glb  # noqa: E402

ASSETS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "game", "assets"))


def compact(j, binary):
    """Drop the buffer views nothing refers to any more (a removed picture's bytes)."""
    used = set()
    for a in j.get("accessors", []):
        if "bufferView" in a:
            used.add(a["bufferView"])
        for part in ("indices", "values"):
            if "sparse" in a and "bufferView" in a["sparse"].get(part, {}):
                used.add(a["sparse"][part]["bufferView"])
    for im in j.get("images", []):
        if "bufferView" in im:
            used.add(im["bufferView"])
    views = j.get("bufferViews", [])
    if len(used) == len(views):
        return binary
    out, remap, kept = bytearray(), {}, []
    for i, v in enumerate(views):
        if i not in used:
            continue
        while len(out) % 4:
            out.append(0)
        o = v.get("byteOffset", 0)
        nv = dict(v, byteOffset=len(out))
        out += binary[o : o + v["byteLength"]]
        remap[i] = len(kept)
        kept.append(nv)
    j["bufferViews"] = kept
    for a in j.get("accessors", []):
        if "bufferView" in a:
            a["bufferView"] = remap[a["bufferView"]]
        for part in ("indices", "values"):
            if "sparse" in a and "bufferView" in a["sparse"].get(part, {}):
                a["sparse"][part]["bufferView"] = remap[a["sparse"][part]["bufferView"]]
    for im in j.get("images", []):
        if "bufferView" in im:
            im["bufferView"] = remap[im["bufferView"]]
    return out


def material_image(j, mi):
    """The index of a material's base colour picture, or None."""
    tex = j["materials"][mi].get("pbrMetallicRoughness", {}).get("baseColorTexture")
    if tex is None:
        return None
    return j["textures"][tex["index"]].get("source")


def image_bytes(j, binary, ii):
    v = j["bufferViews"][j["images"][ii]["bufferView"]]
    o = v.get("byteOffset", 0)
    return bytes(binary[o : o + v["byteLength"]])


def point_at(j, ii, path, glb):
    """Make a file's picture a path, relative to the file."""
    j["images"][ii] = dict(uri=os.path.relpath(path, os.path.dirname(os.path.abspath(glb))).replace(os.sep, "/"), name=os.path.splitext(os.path.basename(path))[0])


def strands(files, shared=None):
    """Replace each file's embedded strand texture by the shared one's path."""
    done = 0
    for f in files:
        j, binary = read_glb(f)
        path = shared or os.path.join(ASSETS, "lookdev", "strands.png")
        if not os.path.exists(path):
            raise SystemExit(f"share: {path} is missing (person.py writes it beside the models)")
        images = {material_image(j, mi) for mi, m in enumerate(j.get("materials", [])) if "_HAIR" in m.get("name", "")}
        images = [ii for ii in images if ii is not None and "bufferView" in j["images"][ii]]
        if not images:
            continue
        for ii in images:
            point_at(j, ii, path, f)
        write_glb(f, j, compact(j, binary))
        done += 1
    return done


def atlas_users(j, which=None):
    """The materials whose picture is an atlas of this person (embedded, and not the hair's, the
    iris's, which keeps a small picture of its own for the client's tag, nor the lips' and
    blush's fixed-colour layer, `.tint`, which keeps its own), by picture; `which`
    keeps only the full model's (`near`) or the far model's (`far`)."""
    by_image = {}
    for mi, m in enumerate(j.get("materials", [])):
        ii = material_image(j, mi)
        if ii is None or "_HAIR" in m.get("name", "") or "bufferView" not in j["images"][ii] or j["images"][ii].get("name", "").endswith((".iris", ".tint")):
            continue
        if which is not None and j["images"][ii].get("name", "").endswith(".far") != (which == "far"):
            continue
        by_image.setdefault(ii, []).append(mi)
    return by_image


def move_uvs(j, binary, materials, col, row, n, tile, window=(0.0, 0.0, 1.0, 1.0), also=None):
    """Move the UVs of every primitive that wears one of `materials` into tile (col, row) of an
    n×n page, half a texel inside its edges. `window`: the part of the picture the tile holds
    (u0, v0, u1, v1), when it is not the whole of it. `also`: a second block of the picture and
    where the page has it, for UVs that lie in it: ((u0, v0, u1, v1), (page u0, v0, u1, v1),
    its side in texels)."""
    u0, v0, u1, v1 = window
    e = 0.5 / tile
    seen = set()
    for mesh in j["meshes"]:
        for p in mesh["primitives"]:
            if p.get("material") not in materials:
                continue
            ai = p["attributes"].get("TEXCOORD_0")
            if ai is None or ai in seen:
                continue
            seen.add(ai)
            a = j["accessors"][ai]
            assert a["componentType"] == 5126 and a["type"] == "VEC2", "UVs are float pairs"
            v = j["bufferViews"][a["bufferView"]]
            base = v.get("byteOffset", 0) + a.get("byteOffset", 0)
            stride = v.get("byteStride") or 8
            for k in range(a["count"]):
                o = base + k * stride
                u, t = struct.unpack_from("<2f", binary, o)
                if also is not None and also[0][0] - 1e-4 <= u <= also[0][2] + 1e-4 and also[0][1] - 1e-4 <= t <= also[0][3] + 1e-4:
                    (a0, b0, a1, b1), (p0, q0, p1, q1), px = also
                    e2 = 0.5 / px
                    u, t = min(max((u - a0) / (a1 - a0), e2), 1 - e2), min(max((t - b0) / (b1 - b0), e2), 1 - e2)
                    struct.pack_into("<2f", binary, o, p0 + u * (p1 - p0), q0 + t * (q1 - q0))
                    continue
                u, t = (u - u0) / (u1 - u0), (t - v0) / (v1 - v0)
                struct.pack_into("<2f", binary, o, (col + min(max(u, e), 1 - e)) / n, (row + min(max(t, e), 1 - e)) / n)
            a.pop("min", None)
            a.pop("max", None)


def pages(files, name, out_dir, tile=1024, page=4096, which=None):
    """Lay the files' atlases out on shared pages and point the files at them (`which`: the full
    model's or the far model's, for files that hold both)."""
    per = (page // tile) ** 2
    os.makedirs(out_dir, exist_ok=True)
    todo = []
    for f in files:
        j, binary = read_glb(f)
        users = atlas_users(j, which)
        if not users:
            print(f"share: {f} has no atlas of its own (already on a page?); left as it is")
            continue
        if len(users) > 1:
            raise SystemExit(f"share: {f} has {len(users)} atlases; one a file is expected (page a `--lod both` file with --which near, then --which far)")
        todo.append(f)
    record = dict(name=name, tile=tile, pages=[], people={})
    for pi in range(math.ceil(len(todo) / per)):
        batch = todo[pi * per : (pi + 1) * per]
        n = 1
        while n * n < len(batch):
            n *= 2
        sheet = Image.new("RGB", (n * tile, n * tile), (128, 128, 128))
        maps = None
        page_path = os.path.join(out_dir, f"{name}-{pi}.png")
        map_path = os.path.join(out_dir, f"{name}-{pi}.face.png")
        for k, f in enumerate(batch):
            col, row = k % n, k // n
            j, binary = read_glb(f)
            (ii, mats), = atlas_users(j, which).items()
            im = Image.open(io.BytesIO(image_bytes(j, binary, ii))).convert("RGB")
            if im.size != (tile, tile):
                im = im.resize((tile, tile), Image.LANCZOS)
            sheet.paste(im, (col * tile, row * tile))
            move_uvs(j, binary, set(mats), col, row, n, tile)
            point_at(j, ii, page_path, f)
            # The face's shadow map goes onto the page's, in the same tile.
            own = os.path.splitext(f)[0] + ".face.png"
            if which != "far" and os.path.exists(own):
                fm = Image.open(own).convert("RGB")
                if maps is None:
                    maps = Image.new("RGB", (n * fm.size[0], n * fm.size[1]), (255, 255, 0))
                maps.paste(fm.resize((maps.size[0] // n, maps.size[1] // n)), (col * (maps.size[0] // n), row * (maps.size[1] // n)))
                os.remove(own)
                for mi in mats:
                    if "Face" in j["materials"][mi].get("name", "") and j["materials"][mi]["name"].endswith("_SKIN"):
                        j["materials"][mi].setdefault("extras", {})["face_map"] = os.path.relpath(map_path, ASSETS).replace(os.sep, "/")
            write_glb(f, j, compact(j, binary))
            record["people"][os.path.basename(f)] = dict(page=pi, col=col, row=row, of=n)
        sheet.save(page_path)
        if maps is not None:
            maps.save(map_path)
        record["pages"].append(dict(file=os.path.basename(page_path), size=n * tile, people=len(batch), face_map=os.path.basename(map_path) if maps is not None else None))
    with open(os.path.join(out_dir, f"{name}.json"), "w") as f:
        json.dump(record, f, indent=1)
    return record


# The mean colour (linear) of a type's far picture over the texels its mesh uses: what each tile
# is moved to, so a material shared by every type has one mean. The types' own means are within
# 1% of it. The irises are not paged: their means differ too much (see the module's note).
FAR_MEAN = (0.777, 0.4985, 0.369)
# kind: (the picture's side, the class's mean or None for a layer with an alpha, the window of the
# picture a tile holds). The lip layer's mesh uses a band across the middle of its picture
# (u 0.203 to 0.797, v 0.604 to 0.859 on every type): only that is kept, at the picture's own
# scale, so the page is 1600 x 720 where whole tiles would make it 2560 x 2560.
TYPE_PAGES = dict(far=(256, FAR_MEAN, (0.0, 0.0, 1.0, 1.0)), tint=(512, None, (0.1875, 0.59375, 0.8125, 0.875)))
# The iris's lights (face_paint.iris_lights) lie in the lip layer's picture where the atlas has
# the iris, outside the window: this block of the picture (u0, v0, u1, v1). They are the same in
# every type, so the page holds them once, in the corner of its last tile, which no type has.
TYPE_LIGHTS = (0.625, 0.0, 0.8125, 0.1875)


def _linear(a):
    import numpy as np

    return np.where(a > 0.04045, ((a + 0.055) / 1.055) ** 2.4, a / 12.92)


def _stored(a):
    import numpy as np

    a = np.clip(a, 0.0, 1.0)
    return np.where(a > 0.0031308, 1.055 * a ** (1 / 2.4) - 0.055, 12.92 * a)


def _hsv(a):
    """Linear RGB (..., 3) to hue, saturation, value, each 0..1."""
    import numpy as np

    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    v = a.max(axis=-1)
    c = v - a.min(axis=-1)
    safe = np.maximum(c, 1e-12)
    h = np.where(v == r, ((g - b) / safe) % 6.0, np.where(v == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0)) / 6.0
    return np.stack([np.where(c > 1e-9, h % 1.0, 0.0), np.where(v > 1e-9, c / np.maximum(v, 1e-12), 0.0), v], axis=-1)


def _rgb(h):
    import numpy as np

    k = (np.array([5.0, 3.0, 1.0]) + h[..., 0:1] * 6.0) % 6.0
    return h[..., 2:3] * (1.0 - h[..., 1:2] * np.clip(np.minimum(k, 4.0 - k), 0.0, 1.0))


def types(files, out_dir):
    """Lay the face types' far pictures, irises and lip layers (with the iris's lights) out on
    the three shared pages."""
    import numpy as np

    from merge_primitives import read_accessor

    order = list(json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "types.json")))["types"])
    n = 1
    while n * n < len(order):
        n += 1
    os.makedirs(out_dir, exist_ok=True)
    record_path = os.path.join(out_dir, "types.json")
    record = json.load(open(record_path)) if os.path.exists(record_path) else {}
    cell = {}
    for kind, (side, mean, (u0, v0, u1, v1)) in TYPE_PAGES.items():
        cell[kind] = (int(round(side * u0)), int(round(side * v0)), int(round(side * u1)), int(round(side * v1)))
    size = {k: (c[2] - c[0], c[3] - c[1]) for k, c in cell.items()}
    record = dict(grid=n, pages={k: dict(file=f"types-{k}.png", tile=list(size[k]), window=list(TYPE_PAGES[k][2]), mean=TYPE_PAGES[k][1]) for k in TYPE_PAGES},
                  types=record.get("types", {}) if record.get("grid") == n else {})
    sheets = {}
    for kind, (side, mean, _) in TYPE_PAGES.items():
        path = os.path.join(out_dir, f"types-{kind}.png")
        whole = (n * size[kind][0], n * size[kind][1])
        if os.path.exists(path) and Image.open(path).size == whole and record["types"]:
            sheets[kind] = Image.open(path).convert("RGBA" if mean is None else "RGB")
        elif mean is None:
            sheets[kind] = Image.new("RGBA", whole, (0, 0, 0, 0))
        else:
            sheets[kind] = Image.new("RGB", whole, tuple(int(round(float(x) * 255)) for x in _stored(np.array(mean))))
    done = 0
    iris = None
    lights = None
    for f in files:
        t = os.path.splitext(os.path.basename(f))[0]
        if t not in order:
            raise SystemExit(f"share: {f} is not a face type's file (types.json has no {t!r})")
        col, row = order.index(t) % n, order.index(t) // n
        j, binary = read_glb(f)
        binary = bytearray(binary)
        moved = []
        for kind, (side, mean, window) in TYPE_PAGES.items():
            mats = [mi for mi in range(len(j.get("materials", []))) if material_image(j, mi) is not None and j["images"][material_image(j, mi)].get("name", "").endswith("." + kind)
                    and "bufferView" in j["images"][material_image(j, mi)]]
            if not mats:
                continue
            ii = material_image(j, mats[0])
            im = Image.open(io.BytesIO(image_bytes(j, binary, ii))).convert("RGBA" if mean is None else "RGB")
            if im.size != (side, side):
                im = im.resize((side, side), Image.LANCZOS)
            uv = np.vstack([np.array(read_accessor(j, binary, p["attributes"]["TEXCOORD_0"])[0], float).reshape(-1, 2) for mesh in j["meshes"] for p in mesh["primitives"] if p.get("material") in mats])
            also = None
            if kind == "tint":
                # The iris's lights: their block goes to the last tile's corner, once for all.
                a0, b0, a1, b1 = TYPE_LIGHTS
                lit = (uv[:, 0] > a0 - 1e-4) & (uv[:, 0] < a1 + 1e-4) & (uv[:, 1] > b0 - 1e-4) & (uv[:, 1] < b1 + 1e-4)
                if lit.any():
                    if len(order) >= n * n:
                        raise SystemExit("share: the pages have no spare tile for the iris's lights")
                    box = (int(round(side * a0)), int(round(side * b0)), int(round(side * a1)), int(round(side * b1)))
                    block = np.asarray(im.crop(box)).astype(int)
                    at = ((n - 1) * size[kind][0], (n - 1) * size[kind][1])
                    if lights is None and set(record["types"]) - {os.path.splitext(os.path.basename(x))[0] for x in files}:
                        lights = np.asarray(sheets[kind].crop((at[0], at[1], at[0] + box[2] - box[0], at[1] + box[3] - box[1]))).astype(int)
                    if lights is None:
                        lights = block
                        sheets[kind].paste(im.crop(box), at)
                    elif lights.shape != block.shape or np.abs(lights - block).max() > 1:
                        raise SystemExit(f"share: {f}: the lights in its iris are not the ones the other types share")
                    w_, h_ = sheets[kind].size
                    also = (TYPE_LIGHTS, (at[0] / w_, at[1] / h_, (at[0] + block.shape[1]) / w_, (at[1] + block.shape[0]) / h_), block.shape[0])
                    uv = uv[~lit]
            if uv[:, 0].min() < window[0] - 1e-4 or uv[:, 0].max() > window[2] + 1e-4 or uv[:, 1].min() < window[1] - 1e-4 or uv[:, 1].max() > window[3] + 1e-4:
                if window != (0.0, 0.0, 1.0, 1.0):
                    raise SystemExit(f"share: {f}: its {kind} mesh uses the picture outside the window the page keeps ({uv.min(axis=0).round(3)} to {uv.max(axis=0).round(3)}, window {window})")
            if mean is not None:
                # The mean over the texels the mesh's vertices use, as the client takes it.
                a = _linear(np.asarray(im, float) / 255.0)
                x = np.clip((uv[:, 0] % 1.0 * side).astype(int), 0, side - 1)
                y = np.clip((uv[:, 1] % 1.0 * side).astype(int), 0, side - 1)
                # Moved as the client moves colours (toon.wesl `recolor`): every texel's hue by the
                # same turn, its saturation and its value by the same ratios, until the tile's mean
                # is the class's. Hues keep their distance from the mean's, so the client's own
                # move from the class's mean to a person's colour lands where it did from the
                # type's own mean.
                goal = _hsv(np.array(mean, float)[None, None, :])[0, 0]
                for _ in range(3):
                    own = _hsv(a[y, x].mean(axis=0)[None, None, :])[0, 0]
                    h = _hsv(a)
                    h[..., 0] = (h[..., 0] + goal[0] - own[0]) % 1.0
                    h[..., 1] = np.clip(h[..., 1] * goal[1] / max(own[1], 1e-4), 0.0, 1.0)
                    h[..., 2] = np.clip(h[..., 2] * goal[2] / max(own[2], 1e-4), 0.0, 1.0)
                    a = _rgb(h)
                im = Image.fromarray((_stored(a) * 255 + 0.5).astype(np.uint8), "RGB")
            sheets[kind].paste(im.crop(cell[kind]), (col * size[kind][0], row * size[kind][1]))
            move_uvs(j, binary, set(mats), col, row, n, min(size[kind]), window, also)
            point_at(j, ii, os.path.join(out_dir, f"types-{kind}.png"), f)
            moved.append(kind)
        # The iris: one picture for every type (person_params.SHARED_IRIS), named by path. No tile
        # and no move of the UVs: every type's is the same picture.
        mats = [mi for mi in range(len(j.get("materials", []))) if material_image(j, mi) is not None and j["images"][material_image(j, mi)].get("name", "").endswith(".iris")
                and "bufferView" in j["images"][material_image(j, mi)]]
        if mats:
            ii = material_image(j, mats[0])
            pic = np.asarray(Image.open(io.BytesIO(image_bytes(j, binary, ii))).convert("RGB"))
            path = os.path.join(out_dir, "types-iris.png")
            # Types paged before and not in this call keep the picture they point at; when every
            # one of them is paged again here, the picture is this call's.
            if iris is None and os.path.exists(path) and set(record["types"]) - {os.path.splitext(os.path.basename(x))[0] for x in files}:
                iris = np.asarray(Image.open(path).convert("RGB"))
            if iris is None:
                iris = pic
                Image.fromarray(pic, "RGB").save(path)
            elif iris.shape != pic.shape or np.abs(iris.astype(int) - pic.astype(int)).max() > 1:
                raise SystemExit(f"share: {f}: its iris is not the picture the other types share ({path}); build the types with the shared iris")
            point_at(j, ii, path, f)
            moved.append("iris")
        if moved:
            write_glb(f, j, compact(j, binary))
            record["types"][t] = dict(col=col, row=row, pages=sorted(set(record["types"].get(t, {}).get("pages", [])) | set(moved)))
            done += 1
    for kind, sheet in sheets.items():
        sheet.save(os.path.join(out_dir, f"types-{kind}.png"))
    with open(record_path, "w") as f:
        json.dump(record, f, indent=1)
    return record, done


def drop_clips(files):
    """Remove each file's own clips and their sidecar (the shared clip file serves them)."""
    done = 0
    for f in files:
        j, binary = read_glb(f)
        anims = j.pop("animations", None)
        if anims:
            used = {s["input"] for a in anims for s in a["samplers"]} | {s["output"] for a in anims for s in a["samplers"]}
            # Accessors only the clips used go; the others are renumbered.
            keep = [i for i in range(len(j["accessors"])) if i not in used or accessor_used_elsewhere(j, i)]
            remap = {old: new for new, old in enumerate(keep)}
            j["accessors"] = [j["accessors"][i] for i in keep]
            renumber_accessors(j, remap)
            write_glb(f, j, compact(j, binary))
            done += 1
        side = os.path.splitext(f)[0] + ".clips.json"
        if os.path.exists(side):
            os.remove(side)
    return done


def clip_file(files):
    """Make each file a clip file: its skeleton and its clips, and nothing a clip file is not read
    for. The meshes, skins, materials, pictures and the VRM block go (a clip file that is a whole
    person makes the client decode and hold that person's pictures and morph targets for
    nothing). One thing stays in their place: a mesh `Figure` of four points and no material,
    whose bounds are the figure's the clips were baked on. The client measures a person's
    stride against the clip file's figure from its meshes' bounds (`lookdev::figure_height`),
    so the file must still say how tall that figure stood. Returns [(file, bytes before,
    after)]."""
    from array import array

    from merge_primitives import append_accessor, read_accessor

    out = []
    for f in files:
        j, binary = read_glb(f)
        before = os.path.getsize(f)
        nodes = j["nodes"]
        # The figure's bounds: every near mesh's, as the client takes them (bind pose; our mesh
        # nodes have no transform of their own).
        lo, hi = [1e9] * 3, [-1e9] * 3
        for n in nodes:
            if "mesh" not in n or n.get("name", "").startswith("Far"):
                continue
            for pr in j["meshes"][n["mesh"]]["primitives"]:
                acc = j["accessors"][pr["attributes"]["POSITION"]]
                lo = [min(a, b) for a, b in zip(lo, acc["min"])]
                hi = [max(a, b) for a, b in zip(hi, acc["max"])]
        if hi[1] <= lo[1]:
            raise SystemExit(f"share: {f} has no meshes to take the figure's bounds from (already a clip file?)")
        keep = [i for i, n in enumerate(nodes) if "mesh" not in n]
        remap = {old: new for new, old in enumerate(keep)}
        new_nodes = []
        for i in keep:
            n = {k: v for k, v in nodes[i].items() if k not in ("skin", "extensions")}
            if "children" in n:
                n["children"] = [remap[c] for c in n["children"] if c in remap]
                if not n["children"]:
                    del n["children"]
            new_nodes.append(n)
        nj = {"asset": j["asset"], "buffers": [{"byteLength": 0}], "bufferViews": [], "accessors": [], "nodes": new_nodes}
        nb = bytearray()
        moved = {}

        def carry(a):
            if a not in moved:
                values, (ct, typ, norm) = read_accessor(j, binary, a)
                moved[a] = append_accessor(nj, nb, values, ct, typ, norm)
                for k in ("min", "max"):
                    if k in j["accessors"][a]:
                        nj["accessors"][moved[a]][k] = j["accessors"][a][k]
            return moved[a]

        anims = []
        for an in j.get("animations", []):
            samplers = [dict(s, input=carry(s["input"]), output=carry(s["output"])) for s in an["samplers"]]
            channels = [dict(c, target=dict(c["target"], node=remap[c["target"]["node"]])) for c in an["channels"] if c["target"].get("node") in remap]
            anims.append(dict(an, samplers=samplers, channels=channels))
        if not anims:
            raise SystemExit(f"share: {f} has no clips")
        nj["animations"] = anims
        corners = array("f", [lo[0], lo[1], lo[2], hi[0], lo[1], hi[2], hi[0], hi[1], hi[2], lo[0], hi[1], lo[2]])
        pos = append_accessor(nj, nb, corners, 5126, "VEC3", False, target=34962)
        idx = append_accessor(nj, nb, array("H", [0, 1, 2, 0, 2, 3]), 5123, "SCALAR", False, target=34963)
        nj["meshes"] = [{"name": "Figure", "primitives": [{"attributes": {"POSITION": pos}, "indices": idx}]}]
        new_nodes.append({"name": "Figure", "mesh": 0})
        roots = [remap[r] for sc in j.get("scenes", []) for r in sc["nodes"] if r in remap]
        nj["scenes"] = [{"nodes": roots + [len(new_nodes) - 1], "extras": {"clip_file": {"figure_height": hi[1] - lo[1]}}}]
        nj["scene"] = 0
        write_glb(f, nj, nb)
        for side in (".face.png", ".atlas.png", ".far.png"):
            if os.path.exists(os.path.splitext(f)[0] + side):
                os.remove(os.path.splitext(f)[0] + side)
        out.append((f, before, os.path.getsize(f)))
    return out


def accessor_refs(j):
    """Every place outside animations that names an accessor: (container, key)."""
    for m in j.get("meshes", []):
        for p in m["primitives"]:
            for k in p["attributes"]:
                yield p["attributes"], k
            if "indices" in p:
                yield p, "indices"
            for t in p.get("targets", []):
                for k in t:
                    yield t, k
    for s in j.get("skins", []):
        if "inverseBindMatrices" in s:
            yield s, "inverseBindMatrices"


def accessor_used_elsewhere(j, i):
    return any(c[k] == i for c, k in accessor_refs(j))


def renumber_accessors(j, remap):
    for c, k in list(accessor_refs(j)):
        c[k] = remap[c[k]]


def listing(files):
    for f in files:
        j, binary = read_glb(f)
        prims = [(m.get("name", "?"), j["materials"][p["material"]]["name"] if "material" in p else "-", j["accessors"][p["indices"]]["count"] // 3, len(p.get("targets", []))) for m in j["meshes"] for p in m["primitives"]]
        print(f"{f}: {len(prims)} meshes, {sum(t for _, _, t, _ in prims)} triangles, {len(j.get('materials', []))} materials, {len(j.get('animations', []))} clips, {os.path.getsize(f) / 1e6:.2f} MB")
        for name, mat, tris, targets in prims:
            print(f"  {name:12s} {mat:36s} {tris:6d} triangles{f', {targets} morph targets' if targets else ''}")
        for im in j.get("images", []):
            print("  picture: " + (im["uri"] if "uri" in im else f"embedded, {j['bufferViews'][im['bufferView']]['byteLength'] / 1e3:.0f} kB"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("strands", help="share the hair's strand texture")
    s.add_argument("files", nargs="+")
    s.add_argument("--shared", help="the one strands.png (default: lookdev/strands.png under the asset folder)")
    p = sub.add_parser("pages", help="lay a set of people's atlases out on shared pages")
    p.add_argument("files", nargs="+")
    p.add_argument("--name", required=True, help="the set's name: pages are <dir>/<name>-<n>.png")
    p.add_argument("--dir", default=os.path.join(ASSETS, "lookdev", "pages"))
    p.add_argument("--tile", type=int, default=1024, help="a person's tile, in texels (1024 the full atlas, 256 a far model's picture)")
    p.add_argument("--page", type=int, default=4096, help="a page's side, in texels")
    p.add_argument("--which", choices=("near", "far"), help="for files with both models: the full model's atlas or the far model's picture")
    t = sub.add_parser("types", help="lay the face types' far pictures, irises and lip layers out on the pages every type shares")
    t.add_argument("files", nargs="+")
    t.add_argument("--dir", default=os.path.join(ASSETS, "lookdev", "pages"))
    c = sub.add_parser("clips", help="remove each file's own clips (the game takes them from the shared clip file)")
    c.add_argument("files", nargs="+")
    cf = sub.add_parser("clipfile", help="make a baked person a clip file: the skeleton, the clips and the figure's bounds, no meshes or pictures")
    cf.add_argument("files", nargs="+")
    l = sub.add_parser("list", help="each file's meshes, materials and pictures")
    l.add_argument("files", nargs="+")
    a = ap.parse_args()
    if a.cmd == "strands":
        print(f"share: {strands(a.files, a.shared)} of {len(a.files)} files now name the shared strand texture")
    elif a.cmd == "pages":
        r = pages(a.files, a.name, os.path.abspath(a.dir), a.tile, a.page, a.which)
        print(f"share: {len(r['people'])} people on {len(r['pages'])} page(s) " + ", ".join(f"{p['file']} ({p['size']}², {p['people']} people)" for p in r["pages"]))
    elif a.cmd == "types":
        r, done = types(a.files, os.path.abspath(a.dir))
        print(f"share: {done} of {len(a.files)} type files put on the shared pages ({r['grid']}x{r['grid']} tiles): " + ", ".join(f"{v['file']} ({r['grid'] * v['tile'][0]} x {r['grid'] * v['tile'][1]})" for v in r["pages"].values()))
    elif a.cmd == "clips":
        print(f"share: {drop_clips(a.files)} of {len(a.files)} files had their own clips removed")
    elif a.cmd == "clipfile":
        for f, before, after in clip_file(a.files):
            print(f"share: {f} is a clip file: {before / 1e6:.2f} MB to {after / 1e6:.2f} MB")
    else:
        listing(a.files)


if __name__ == "__main__":
    main()
