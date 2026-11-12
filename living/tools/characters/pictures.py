#!/usr/bin/env python3
"""A character bundle's pictures as KTX2: BC7, a full mip chain, zstd (docs/CHARACTERS.md,
"Pictures as KTX2").

    python3 living/tools/characters/pictures.py bundle IN.tar.gz OUT.tar.gz --pictures ktx2|png [--png CLASS ...]
    python3 living/tools/characters/pictures.py convert DIR --pictures ktx2|png [--png CLASS ...] [--config FILE]
    python3 living/tools/characters/pictures.py check DIR|BUNDLE.tar.gz
    python3 living/tools/characters/pictures.py memory DIR|BUNDLE.tar.gz

A bundle step, run on a bundle's own copies, never on the generator's output: `convert` refuses
a directory without the bundle's MANIFEST.txt. The generator's PNGs stay its intermediates
(shade_mean.py, eye_colours.py and the boards read them); this step runs after they are checked.

- `convert`: every picture of a known class (`CLASSES`) is encoded by bc7ktx
  (living/tools/bc7ktx) beside where it was, with a `<name>.thumb.png` summary: 64×64 16-bit
  RGBA, the client's `Thumb` cells. Each GLB's `images[]` then names the `.ktx2` by `uri`, with
  no `mimeType` or `bufferView`, and its binary chunk is repacked without the PNG. The PNGs a
  GLB named by path, and the shadow maps, are removed; `pages/types.json` names the pages'
  new files. MANIFEST.txt gains `pictures: ktx2-bc7` (or `png`) and lists every file with its
  sha256. With `--pictures png` nothing but MANIFEST.txt changes. `--png CLASS` (or `"format":
  "png"` in pictures.json) keeps a class as it is: `pictures: ktx2-bc7 (png: overlay)`.
- `bundle`: unpack a bundle, convert, check, and pack it again (same member order, owners and
  times; gzip without a time), in a scratch directory beside OUT.
- `check`: fails (exit 1) when a GLB's image URI does not resolve, a `.ktx2` has no thumb, a
  KTX2's level count or format class (sRGB or linear) is wrong, a GLB still embeds a picture the
  manifest calls KTX2, a converted PNG is left behind, or a manifest line's sha256 is wrong.
- `memory`: each class's GPU bytes, KTX2 (BC7, every level) against RGBA8 without mips.

The encoder is built on first use (`cargo build --release --offline --locked`, in
$CARGO_TARGET_DIR or .local/bc7ktx-target); `BC7KTX=PATH` names a built one.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ENCODER_DIR = REPO / "living/tools/bc7ktx"
CONFIG = Path(__file__).with_name("pictures.json")
ASSETS = Path("living/game/assets/lookdev")
MANIFEST = "MANIFEST.txt"

# The classes, where they are and what they become. `colour` is how the client samples them:
# sRGB colour, or linear data (the shadow maps, loaded with `is_srgb = false`).
CLASSES = ["atlas", "face", "overlay", "far", "tint", "iris", "strands"]
URI_CLASSES = {"pages/types-far.png": "far", "pages/types-tint.png": "tint", "pages/types-iris.png": "iris", "strands.png": "strands"}
LINEAR = {"face"}


def die(msg):
    print(f"pictures: {msg}", file=sys.stderr)
    sys.exit(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- GLB ------------------------------------------------------------------------------------

def read_glb(path):
    b = Path(path).read_bytes()
    magic, version, length = struct.unpack_from("<4sII", b, 0)
    if magic != b"glTF" or version != 2 or length != len(b):
        die(f"{path}: not a glTF 2 binary")
    jlen, jtype = struct.unpack_from("<II", b, 12)
    if jtype != 0x4E4F534A:
        die(f"{path}: first chunk is not JSON")
    j = json.loads(b[20:20 + jlen])
    bin_ = b""
    o = 20 + jlen
    if o < len(b):
        blen, btype = struct.unpack_from("<II", b, o)
        if btype != 0x004E4942:
            die(f"{path}: second chunk is not BIN")
        bin_ = b[o + 8:o + 8 + blen]
    return j, bin_


def write_glb(path, j, bin_):
    text = json.dumps(j, separators=(",", ":"), ensure_ascii=False).encode()
    text += b" " * (-len(text) % 4)
    bin_ = bin_ + b"\0" * (-len(bin_) % 4)
    out = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(text) + (8 + len(bin_) if bin_ else 0))
    out += struct.pack("<II", len(text), 0x4E4F534A) + text
    if bin_:
        out += struct.pack("<II", len(bin_), 0x004E4942) + bin_
    Path(path).write_bytes(out)


def image_bytes(j, bin_, image):
    v = j["bufferViews"][image["bufferView"]]
    o = v.get("byteOffset", 0)
    return bin_[o:o + v["byteLength"]]


def remap_views(node, mapping):
    """Every `bufferView` index anywhere in the JSON (accessors, sparse accessors, images,
    extensions) through `mapping`."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "bufferView" and isinstance(v, int):
                if v not in mapping:
                    die(f"bufferView {v} is still used after its picture was moved out")
                node[k] = mapping[v]
            else:
                remap_views(v, mapping)
    elif isinstance(node, list):
        for v in node:
            remap_views(v, mapping)


def drop_views(j, bin_, drop):
    """The GLB without the buffer views in `drop`: the others keep their order and are packed
    again, each on a 4-byte boundary (glTF's alignment for accessors)."""
    if not drop:
        return j, bin_
    if len(j.get("buffers", [])) != 1 or any(v.get("buffer", 0) != 0 for v in j["bufferViews"]):
        die("a GLB with more than one buffer")
    keep = [i for i in range(len(j["bufferViews"])) if i not in drop]
    order = sorted(keep, key=lambda i: (j["bufferViews"][i].get("byteOffset", 0), i))
    new_bin = bytearray()
    placed = {}
    for i in order:
        v = j["bufferViews"][i]
        o = v.get("byteOffset", 0)
        new_bin += b"\0" * (-len(new_bin) % 4)
        placed[i] = len(new_bin)
        new_bin += bin_[o:o + v["byteLength"]]
    views = []
    mapping = {}
    for i in keep:
        v = dict(j["bufferViews"][i])
        v["byteOffset"] = placed[i]
        mapping[i] = len(views)
        views.append(v)
    j["bufferViews"] = views
    for key in [k for k in j if k != "bufferViews"]:
        remap_views(j[key], mapping)
    j["buffers"][0]["byteLength"] = len(new_bin)
    return j, bytes(new_bin)


# --- the bundle's pictures --------------------------------------------------------------------

def load_config(png_classes, config=None):
    cfg = json.loads(Path(config or CONFIG).read_text())
    classes = cfg["classes"]
    if sorted(classes) != sorted(CLASSES):
        die(f"{CONFIG}: classes {sorted(classes)}, expected {sorted(CLASSES)}")
    for c in png_classes:
        if c not in classes:
            die(f"--png {c}: not a class ({', '.join(CLASSES)})")
        classes[c]["format"] = "png"
    for c, v in classes.items():
        v.setdefault("format", "ktx2")
        v["colour"] = "linear" if c in LINEAR else "srgb"
    return cfg


def survey(root):
    """Every picture under the bundle's lookdev/: (class, source, users). `source` is a file
    (by URI, or a shadow map) or (glb, image index) for an embedded picture; `users` are the
    (glb, image index) pairs that name a file."""
    lookdev = root / ASSETS
    found = {}  # key -> {"class", "source", "out", "users"}
    errors = []
    for glb in sorted(lookdev.rglob("*.glb")):
        rel = glb.relative_to(lookdev)
        j, _ = read_glb(glb)
        for i, im in enumerate(j.get("images", [])):
            if "bufferView" in im:
                if rel.parts[0] == "types" and len(rel.parts) == 2:
                    cls, out = "atlas", glb.with_name(glb.stem + ".atlas.ktx2")
                elif rel.parts[:2] == ("styles", "overlay") and len(rel.parts) == 4:
                    cls, out = "overlay", glb.with_suffix(".ktx2")
                else:
                    errors.append(f"{rel}: image {i} is embedded and of no known class")
                    continue
                if im.get("mimeType") != "image/png":
                    errors.append(f"{rel}: image {i} is {im.get('mimeType')}, not PNG")
                key = (str(glb), i)
                if any(k[0] == str(glb) for k in found if isinstance(k, tuple)):
                    errors.append(f"{rel}: more than one embedded picture")
                found[key] = {"class": cls, "source": (glb, i), "out": out, "users": [(glb, i)]}
            elif "uri" in im:
                target = (glb.parent / im["uri"]).resolve()
                try:
                    trel = target.relative_to(lookdev.resolve()).as_posix()
                except ValueError:
                    errors.append(f"{rel}: image {i} names {im['uri']}, outside lookdev/")
                    continue
                cls = URI_CLASSES.get(trel)
                if cls is None:
                    errors.append(f"{rel}: image {i} names {im['uri']}, of no known class")
                    continue
                if not target.exists():
                    errors.append(f"{rel}: image {i} names {im['uri']}, which is not in the bundle")
                    continue
                f = found.setdefault(trel, {"class": cls, "source": target, "out": target.with_suffix(".ktx2"), "users": []})
                f["users"].append((glb, i))
    for face in sorted((lookdev / "types").glob("*.face.png")):
        found[face.relative_to(lookdev).as_posix()] = {"class": "face", "source": face, "out": face.with_suffix(".ktx2"), "users": []}
    known = {Path(v["source"]).resolve() for v in found.values() if not isinstance(v["source"], tuple)}
    for png in sorted(lookdev.rglob("*.png")):
        if png.resolve() not in known and not png.name.endswith(".thumb.png"):
            errors.append(f"{png.relative_to(lookdev)}: a picture of no known class")
    if errors:
        die("pictures of no known class (add them to CLASSES):\n  " + "\n  ".join(errors))
    return found


def manifest_parts(root):
    text = (root / MANIFEST).read_text()
    head, lines = [], []
    for ln in text.splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  (.+)", ln)
        if m:
            lines.append((m.group(1), m.group(2)))
        elif ln.strip():
            head.append(ln)
    return head, lines


def bundle_files(root):
    files = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.name != MANIFEST]
    # The builder's order: paths in folders sorted, then the top-level files.
    return sorted(f for f in files if "/" in f) + sorted(f for f in files if "/" not in f)


def pictures_line(cfg, mode):
    if mode == "png":
        return "pictures: png"
    kept = [c for c in CLASSES if cfg["classes"][c]["format"] == "png"]
    return "pictures: ktx2-bc7" + (f" (png: {', '.join(kept)})" if kept else "")


def anchors(f):
    """The files a new file is listed after: what it was made from."""
    if f.endswith(".thumb.png"):
        return [f[: -len(".thumb.png")] + ".ktx2"]
    if f.endswith(".atlas.ktx2"):
        return [f[: -len(".atlas.ktx2")] + ".glb"]
    if f.endswith(".ktx2"):
        return [f[: -len(".ktx2")] + ".png", f[: -len(".ktx2")] + ".glb"]
    return []


def write_manifest(root, line):
    """MANIFEST.txt with the `pictures:` line after the builder's header, and every file with
    its sha256: in the builder's order, each new file after the one it was made from."""
    head, old = manifest_parts(root)
    head = [h for h in head if not h.startswith("pictures:")]
    files = bundle_files(root)
    present = set(files)
    order = [p for _, p in old]
    new = [f for f in files if f not in set(order)]
    after = {}
    for f in new:
        a = next((x for x in anchors(f) if x in order or x in new), None)
        after.setdefault(a, []).append(f)
    listed = []

    def put(f):
        if f in present:
            listed.append(f)
        for g in after.pop(f, []):
            put(g)

    for p in order:
        put(p)
    for a in list(after):
        for g in after.pop(a, []):
            put(g)
    out = head + [line, ""] + [f"{sha256(root / f)}  {f}" for f in listed]
    (root / MANIFEST).write_text("\n".join(out) + "\n")


def encoder(jobs):
    exe = os.environ.get("BC7KTX")
    if not exe:
        target = Path(os.environ.get("CARGO_TARGET_DIR") or REPO / ".local/bc7ktx-target")
        cmd = ["cargo", "build", "--release", "--offline", "--locked", "-j", str(jobs), "--manifest-path", str(ENCODER_DIR / "Cargo.toml")]
        subprocess.run(cmd, check=True, env={**os.environ, "CARGO_TARGET_DIR": str(target)})
        exe = target / "release/bc7ktx"
    return str(exe)


def convert(root, mode, png_classes=(), jobs=12, config=None):
    root = Path(root)
    if not (root / MANIFEST).exists():
        die(f"{root}: no {MANIFEST}; this step runs on a bundle's copies only")
    head, _ = manifest_parts(root)
    if any(h.startswith("pictures:") for h in head):
        die(f"{root}: already converted ({[h for h in head if h.startswith('pictures:')][0]})")
    cfg = load_config(png_classes, config)
    found = survey(root)
    if mode == "png":
        write_manifest(root, pictures_line(cfg, "png"))
        return
    todo = {k: v for k, v in found.items() if cfg["classes"][v["class"]]["format"] == "ktx2"}
    exe = encoder(jobs)
    with tempfile.TemporaryDirectory(prefix="pictures-") as tmp:
        tmp = Path(tmp)
        joblist = []
        for n, (key, v) in enumerate(sorted(todo.items(), key=lambda kv: str(kv[1]["out"]))):
            src = v["source"]
            if isinstance(src, tuple):
                j, bin_ = read_glb(src[0])
                src_png = tmp / f"{n}.png"
                src_png.write_bytes(image_bytes(j, bin_, j["images"][src[1]]))
            else:
                src_png = src
            c = dict(cfg["classes"][v["class"]])
            c.update(c.get("by_name", {}).get(Path(v["out"]).stem, {}))
            job = {"in": str(src_png), "out": str(v["out"]), "thumb": str(v["out"].with_suffix(".thumb.png")), "colour": c["colour"], "mips": c["mips"], "zstd": cfg["zstd"]}
            if c["mips"] == "coverage":
                job["threshold"] = c["threshold"]
            joblist.append(job)
        (tmp / "jobs.json").write_text(json.dumps(joblist))
        subprocess.run([exe, "encode", str(tmp / "jobs.json"), "--threads", str(jobs)], check=True)
    # The GLBs name the new files.
    by_glb = {}
    for v in todo.values():
        for glb, i in v["users"]:
            by_glb.setdefault(glb, []).append((i, v))
    for glb, images in sorted(by_glb.items()):
        j, bin_ = read_glb(glb)
        drop = set()
        for i, v in images:
            im = j["images"][i]
            if "bufferView" in im:
                drop.add(im["bufferView"])
            new = {k: x for k, x in im.items() if k not in ("bufferView", "mimeType", "uri")}
            new = {"uri": os.path.relpath(v["out"], glb.parent).replace(os.sep, "/"), **new}
            j["images"][i] = new
        j, bin_ = drop_views(j, bin_, drop)
        write_glb(glb, j, bin_)
    # The pages' record names the new files.
    tj = root / ASSETS / "pages/types.json"
    if tj.exists():
        t = json.loads(tj.read_text())
        changed = False
        for page in t.get("pages", {}).values():
            f = page.get("file")
            if f and f"pages/{f}" in todo:
                page["file"] = Path(f).with_suffix(".ktx2").name
                changed = True
        if changed:
            tj.write_text(json.dumps(t, indent=1) + "\n")
    for v in todo.values():
        if not isinstance(v["source"], tuple):
            v["source"].unlink()
    write_manifest(root, pictures_line(cfg, "ktx2"))


# --- the check --------------------------------------------------------------------------------

def unpack(src, dest):
    with tarfile.open(src) as t:
        members = t.getmembers()
        t.extractall(dest, filter="data")
    return members


def full_chain(w, h):
    return max(w, h).bit_length()


def check(root, exe=None):
    root = Path(root)
    lookdev = root / ASSETS
    fails = []
    head, lines = manifest_parts(root)
    pl = [h for h in head if h.startswith("pictures:")]
    if len(pl) != 1:
        fails.append(f"{MANIFEST}: {len(pl)} pictures lines")
        mode, kept = "png", set()
    else:
        m = re.fullmatch(r"pictures: (ktx2-bc7|png)(?: \(png: (.+)\))?", pl[0])
        if not m:
            fails.append(f"{MANIFEST}: {pl[0]!r}")
            mode, kept = "png", set()
        else:
            mode, kept = m.group(1), set((m.group(2) or "").split(", ")) - {""}
    ktx2_classes = set() if mode == "png" else set(CLASSES) - kept
    listed = dict((p, s) for s, p in lines)
    for f in bundle_files(root):
        if f not in listed:
            fails.append(f"{f}: not in {MANIFEST}")
        elif sha256(root / f) != listed[f]:
            fails.append(f"{f}: sha256 differs from {MANIFEST}")
    for f in listed:
        if not (root / f).exists():
            fails.append(f"{f}: in {MANIFEST}, not in the bundle")
    # The GLBs' pictures.
    ktx2s = {}
    for glb in sorted(lookdev.rglob("*.glb")):
        rel = glb.relative_to(lookdev)
        j, _ = read_glb(glb)
        for i, im in enumerate(j.get("images", [])):
            if "bufferView" in im:
                cls = "atlas" if rel.parts[0] == "types" else "overlay"
                if cls in ktx2_classes:
                    fails.append(f"{rel}: image {i} is embedded; {MANIFEST} calls {cls} KTX2")
                continue
            target = (glb.parent / im.get("uri", "")).resolve()
            if not im.get("uri") or not target.is_file():
                fails.append(f"{rel}: image {i} names {im.get('uri')!r}, which does not resolve")
                continue
            if "mimeType" in im and target.suffix == ".ktx2":
                fails.append(f"{rel}: image {i} has a mimeType for a KTX2")
            if target.suffix == ".ktx2":
                if rel.parts[0] == "types" and target.name.endswith(".atlas.ktx2"):
                    cls = "atlas"
                elif rel.parts[:2] == ("styles", "overlay"):
                    cls = "overlay"
                else:
                    cls = URI_CLASSES.get(target.relative_to(lookdev.resolve()).with_suffix(".png").as_posix(), "?")
                ktx2s[target] = cls
            else:
                cls = URI_CLASSES.get(target.relative_to(lookdev.resolve()).as_posix(), "?")
                if cls in ktx2_classes:
                    fails.append(f"{rel}: image {i} names {im['uri']}; {MANIFEST} calls {cls} KTX2")
    # The shadow maps.
    for t in sorted((lookdev / "types").glob("*.glb")):
        face = t.with_name(t.stem + (".face.ktx2" if "face" in ktx2_classes else ".face.png"))
        if not face.exists():
            fails.append(f"{t.relative_to(lookdev)}: no {face.name}")
        elif face.suffix == ".ktx2":
            ktx2s[face.resolve()] = "face"
        if "face" in ktx2_classes and t.with_name(t.stem + ".face.png").exists():
            fails.append(f"{t.stem}.face.png left beside {face.name}")
    for k in sorted(lookdev.rglob("*.ktx2")):
        if k.resolve() not in ktx2s:
            fails.append(f"{k.relative_to(lookdev)}: a KTX2 nothing names")
    for page, cls in URI_CLASSES.items():
        if cls in ktx2_classes and (lookdev / page).exists():
            fails.append(f"{page} left beside its KTX2")
    # Each KTX2: thumb, levels, format class.
    if ktx2s:
        exe = exe or encoder(12)
        out = subprocess.run([exe, "info", *map(str, sorted(ktx2s))], check=True, capture_output=True, text=True).stdout
        for line in out.splitlines():
            info = json.loads(line)
            k = Path(info["file"])
            rel = k.relative_to(lookdev.resolve()) if k.is_absolute() else k
            cls = ktx2s[k]
            if not info["ok"]:
                fails.append(f"{rel}: {info['error']}")
                continue
            if info["levels"] != info["full_chain"]:
                fails.append(f"{rel}: {info['levels']} levels, a full chain is {info['full_chain']}")
            want = ("BC7_UNORM_BLOCK", "linear") if cls in LINEAR else ("BC7_SRGB_BLOCK", "srgb")
            if (info["format"], info["transfer"]) != want:
                fails.append(f"{rel} ({cls}): {info['format']} {info['transfer']}, expected {want[0]} {want[1]}")
            if info["supercompression"] != "zstd":
                fails.append(f"{rel}: supercompression {info['supercompression']}")
            thumb = k.with_suffix(".thumb.png")
            if not thumb.exists():
                fails.append(f"{rel}: no {thumb.name}")
            else:
                b = thumb.read_bytes()
                w, h, depth, ctype = struct.unpack(">IIBB", b[16:26])
                if b[:8] != b"\x89PNG\r\n\x1a\n" or (w, h, depth, ctype) != (64, 64, 16, 6):
                    fails.append(f"{thumb.name}: {w}×{h} {depth}-bit type {ctype}, expected 64×64 16-bit RGBA")
    for thumb in sorted(lookdev.rglob("*.thumb.png")):
        if not thumb.with_name(thumb.name[: -len(".thumb.png")] + ".ktx2").exists():
            fails.append(f"{thumb.relative_to(lookdev)}: a thumb without its KTX2")
    tj = lookdev / "pages/types.json"
    if tj.exists():
        for name, page in json.loads(tj.read_text()).get("pages", {}).items():
            if page.get("file") and not (lookdev / "pages" / page["file"]).exists():
                fails.append(f"pages/types.json: page {name} names {page['file']}, not in the bundle")
    return mode, sorted(ktx2s), fails


def check_cmd(target):
    with tempfile.TemporaryDirectory(prefix="pictures-check-", dir=scratch_parent(target)) as tmp:
        root = Path(target)
        if root.is_file():
            unpack(root, tmp)
            root = Path(tmp)
        mode, ktx2s, fails = check(root)
    for f in fails:
        print(f"FAIL {f}")
    print(f"pictures: {mode}, {len(ktx2s)} KTX2, {len(fails)} failures")
    return 1 if fails else 0


# --- GPU memory ---------------------------------------------------------------------------------

def memory(root):
    """Per class: pictures, RGBA8 without mips (what the client has on the GPU from a PNG), and
    the KTX2's levels (what it has from BC7)."""
    root = Path(root)
    lookdev = root / ASSETS
    exe = encoder(12)
    rows = {}
    for k in sorted(lookdev.rglob("*.ktx2")):
        rel = k.relative_to(lookdev).as_posix()
        cls = ("face" if rel.endswith(".face.ktx2") else "atlas" if rel.endswith(".atlas.ktx2") else "overlay" if rel.startswith("styles/overlay/")
               else URI_CLASSES.get(str(Path(rel).with_suffix(".png")), "?"))
        info = json.loads(subprocess.run([exe, "info", str(k)], check=True, capture_output=True, text=True).stdout)
        r = rows.setdefault(cls, {"pictures": 0, "size": f"{info['width']}x{info['height']}", "rgba8": 0, "ktx2_gpu": 0, "ktx2_file": 0, "thumb_file": 0})
        r["pictures"] += 1
        r["rgba8"] += info["width"] * info["height"] * 4
        r["ktx2_gpu"] += info["gpu_bytes"]
        r["ktx2_file"] += info["bytes"]
        r["thumb_file"] += k.with_suffix(".thumb.png").stat().st_size
    return rows


def memory_cmd(target):
    with tempfile.TemporaryDirectory(prefix="pictures-mem-", dir=scratch_parent(target)) as tmp:
        root = Path(target)
        if root.is_file():
            unpack(root, tmp)
            root = Path(tmp)
        rows = memory(root)
    mib = 1 << 20
    print(f"{'class':8} {'n':>3} {'size':>9} {'RGBA8 MiB':>10} {'BC7+mips MiB':>13} {'ratio':>6} {'file KiB':>9}")
    tot = [0, 0]
    for cls in CLASSES:
        r = rows.get(cls)
        if not r:
            continue
        tot[0] += r["rgba8"]
        tot[1] += r["ktx2_gpu"]
        print(f"{cls:8} {r['pictures']:3} {r['size']:>9} {r['rgba8'] / mib:10.2f} {r['ktx2_gpu'] / mib:13.2f} {r['rgba8'] / r['ktx2_gpu']:6.2f} {r['ktx2_file'] / 1024:9.0f}")
    print(f"{'total':8} {'':3} {'':>9} {tot[0] / mib:10.2f} {tot[1] / mib:13.2f} {tot[0] / max(tot[1], 1):6.2f}")
    print(json.dumps(rows))
    return 0


# --- bundles ----------------------------------------------------------------------------------

def scratch_parent(target):
    p = Path(target).resolve()
    d = p.parent if p.is_file() else p.parent
    return str(d)


def pack(root, members, out):
    """`root` as a tar.gz: the input's members in their order, with their owners and times;
    new files after, sorted, owned and timed as the input's MANIFEST.txt."""
    root = Path(root)
    by_name = {m.name.removeprefix("./"): m for m in members}
    ref = by_name.get(MANIFEST) or members[0]
    names = [n for n in (m.name.removeprefix("./") for m in members if m.isfile()) if (root / n).is_file()]
    names += sorted(set(bundle_files(root) + [MANIFEST]) - set(names))
    tmp = Path(str(out) + ".tmp")
    import gzip
    with open(tmp, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz, tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as t:
        for n in names:
            src = by_name.get(n, ref)
            info = copy.copy(src)
            info.name = n
            info.size = (root / n).stat().st_size
            info.type = tarfile.REGTYPE
            with open(root / n, "rb") as f:
                t.addfile(info, f)
    tmp.rename(out)


def bundle(src, out, mode, png_classes=(), jobs=12, config=None):
    out = Path(out).resolve()
    with tempfile.TemporaryDirectory(prefix="pictures-bundle-", dir=str(out.parent)) as tmp:
        members = unpack(src, tmp)
        convert(tmp, mode, png_classes, jobs, config)
        mode_, ktx2s, fails = check(tmp)
        for f in fails:
            print(f"FAIL {f}")
        if fails:
            die(f"{len(fails)} failures; no bundle written")
        pack(tmp, members, out)
    print(f"pictures: {out} ({mode_}, {len(ktx2s)} KTX2, {out.stat().st_size} bytes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bundle")
    b.add_argument("src")
    b.add_argument("out")
    c = sub.add_parser("convert")
    c.add_argument("dir")
    for p in (b, c):
        p.add_argument("--pictures", choices=["ktx2", "png"], required=True)
        p.add_argument("--png", action="append", default=[], metavar="CLASS", help="keep a class as PNG")
        p.add_argument("--jobs", type=int, default=12)
        p.add_argument("--config", help=f"classes other than {CONFIG.name}'s")
    sub.add_parser("check").add_argument("target")
    sub.add_parser("memory").add_argument("target")
    a = ap.parse_args()
    if a.cmd == "bundle":
        bundle(a.src, a.out, a.pictures, a.png, a.jobs, a.config)
    elif a.cmd == "convert":
        convert(a.dir, a.pictures, a.png, a.jobs, a.config)
    elif a.cmd == "check":
        sys.exit(check_cmd(a.target))
    elif a.cmd == "memory":
        sys.exit(memory_cmd(a.target))


if __name__ == "__main__":
    main()
