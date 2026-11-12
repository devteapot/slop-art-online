#!/usr/bin/env python3
"""Put generated people's textures on files they share, so a crowd of them is a handful of
materials and not three a person (docs/CHARACTERS.md, "Crowd cost").

    python3 living/tools/characters/share.py strands GLB [GLB ...]
    python3 living/tools/characters/share.py pages --name cullet [--tile 1024] [--page 4096] [--dir DIR] [--which near|far] GLB [GLB ...]
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


def move_uvs(j, binary, materials, col, row, n, tile):
    """Move the UVs of every primitive that wears one of `materials` into tile (col, row) of an
    n×n page, half a texel inside its edges."""
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
    c = sub.add_parser("clips", help="remove each file's own clips (the game takes them from the shared clip file)")
    c.add_argument("files", nargs="+")
    l = sub.add_parser("list", help="each file's meshes, materials and pictures")
    l.add_argument("files", nargs="+")
    a = ap.parse_args()
    if a.cmd == "strands":
        print(f"share: {strands(a.files, a.shared)} of {len(a.files)} files now name the shared strand texture")
    elif a.cmd == "pages":
        r = pages(a.files, a.name, os.path.abspath(a.dir), a.tile, a.page, a.which)
        print(f"share: {len(r['people'])} people on {len(r['pages'])} page(s) " + ", ".join(f"{p['file']} ({p['size']}², {p['people']} people)" for p in r["pages"]))
    elif a.cmd == "clips":
        print(f"share: {drop_clips(a.files)} of {len(a.files)} files had their own clips removed")
    else:
        listing(a.files)


if __name__ == "__main__":
    main()
