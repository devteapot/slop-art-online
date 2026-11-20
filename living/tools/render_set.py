#!/usr/bin/env python3
"""The pinned render asset set: the game client's generated assets, fixed and read-only, for the
scene gate's verify-ui `render` group (docs/TOOLING.md, "Render asset set").

    python3 living/tools/render_set.py build --bundle KTX2.tar.gz [--repo PATH] [--root ~/slop-assets] [--pin]
    python3 living/tools/render_set.py check [SET] [--repo PATH]       # SET: a set's folder, default ROOT/current
    python3 living/tools/render_set.py link [SET] --repo PATH          # the set's files into a checkout's assets
    python3 living/tools/render_set.py pin SET [--root ~/slop-assets]

The game reads its assets from its own checkout's `living/game/assets` (lookdev::asset_root, the
crate's path compiled in), and the generated part of that folder is git-ignored. A set is that
generated part, built once from a main commit on dev-box, at `ROOT/<id>/`:

  assets/                 laid out as living/game/assets: lookdev/ (the VRoid and KayKit bases, the
                          animated bases with their clips, the wolf and the deer, and the composed
                          characters from the bundle: types, pages, styles, strands, own-clips.glb),
                          view/, textures/, envs/<name>/, characters/looks.json
  bundle/                 the composed bundle (KTX2) as built, its MANIFEST.txt and cullet-people.json,
                          and the world look data it was checked against (seeds/...)
  SET-MANIFEST.txt        every file under assets/ with its sha256
  set.json                what the set is (below)

`<id>` is the first 12 hex digits of the bundle file's sha256. `ROOT/current` is a symlink to the
pinned set (`--pin`, or `pin`), replaced atomically.

set.json:
  schema              1
  id                  the set's folder name
  bundle              {file, sha256, commit, port, pictures}: the composed bundle (bundle.py)
  main_commit         the commit the set was built from (provenance only)
  generator_trees     {blender, characters, textures}: `git rev-parse <commit>:living/tools/<dir>`
  generator_tree      one hash of the three (sha256 of "blender=…\\ncharacters=…\\ntextures=…\\n")
  looks               {book, generations: [...], worlds: {name: generation}}
  clips               {own_clips: the shared bake's clip count, bases: {file: clip count}}
  files, bytes        under assets/
  built, build_seconds

`check` reads a set against a checkout (default: this one): `corrupt` (exit 1) when a file's
sha256 is not SET-MANIFEST.txt's or a file is missing or extra; `stale` (exit 2) when the
checkout's generator tree differs from the set's, or a world's look generation (its tracked
`living/seeds/worlds/<w>/looks.json`) is not in the set's book; `ok` (exit 0) otherwise. It
prints one JSON object with the verdict and its reasons.

`build` takes the generated files from `--repo` (default this checkout), which must be clean
(tracked files as HEAD) and built from main as docs/TOOLING.md says, and the composed files from
the KTX2 bundle, never from the checkout's own lookdev/types, pages or styles. The set is made
read-only (files 0444, folders 0555).
"""

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = Path.home() / "slop-assets"
GEN_DIRS = ("blender", "characters", "textures")
ASSETS = "living/game/assets"
# The checkout's generated files a set takes (relative to living/game/assets). The composed
# characters (lookdev/types, pages, styles, strands, anim/own-clips.glb) and the book come from
# the bundle; residents' own files, far and lod copies and outfits are the generator's
# intermediates and stay out.
FROM_REPO_LOOKDEV = ("vroid-*.glb", "kaykit-*.glb", "KAYKIT-LICENSE.txt", "anim/vroid-*", "anim/wolf.*", "anim/deer.*")
FROM_REPO_DIRS = ("view", "textures")


def sh(*a, cwd=None):
    return subprocess.run([*map(str, a)], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def trees(repo, commit="HEAD"):
    t = {d: sh("git", "rev-parse", f"{commit}:living/tools/{d}", cwd=repo) for d in GEN_DIRS}
    one = hashlib.sha256("".join(f"{d}={t[d]}\n" for d in GEN_DIRS).encode()).hexdigest()
    return t, one


def clip_count(path):
    with open(path, "rb") as f:
        f.read(12)
        n = struct.unpack("<I", f.read(4))[0]
        f.read(4)
        return len(json.loads(f.read(n)).get("animations", []))


def world_generations(repo):
    out = {}
    for p in sorted((Path(repo) / "living/seeds/worlds").glob("*/looks.json")):
        out[p.parent.name] = json.load(open(p))["looks"]["generation"]
    return out


def manifest(assets):
    lines = []
    for p in sorted(assets.rglob("*")):
        if p.is_file():
            lines.append(f"{sha256(p)}  {p.relative_to(assets).as_posix()}")
    return lines


def build(a):
    t0 = time.time()
    repo = Path(a.repo).resolve()
    if sh("git", "status", "--porcelain", "--untracked-files=no", cwd=repo):
        sys.exit("render_set: tracked files differ from HEAD in --repo (a set is of a commit)")
    commit = sh("git", "rev-parse", "HEAD", cwd=repo)
    gtrees, gtree = trees(repo)
    bsha = sha256(a.bundle)
    sid = bsha[:12]
    root = Path(a.root)
    dest = root / sid
    if dest.exists():
        sys.exit(f"render_set: {dest} exists (a set is never rebuilt in place; remove it first if it must go)")
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{sid}-", dir=root))
    try:
        assets, bdir = work / "assets", work / "bundle"
        assets.mkdir()
        bdir.mkdir()
        # The composed bundle: living/game/assets/... into assets/, the rest into bundle/.
        with tarfile.open(a.bundle) as t:
            for m in t.getmembers():
                if not m.isfile():
                    continue
                if m.name.startswith(ASSETS + "/"):
                    out = assets / m.name[len(ASSETS) + 1:]
                elif m.name.startswith("living/seeds/"):
                    out = bdir / "seeds" / m.name[len("living/seeds/"):]
                else:
                    out = bdir / m.name
                out.parent.mkdir(parents=True, exist_ok=True)
                with t.extractfile(m) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        shutil.copyfile(a.bundle, bdir / Path(a.bundle).name)
        head = (bdir / "MANIFEST.txt").read_text().split("\n\n", 1)[0]
        hv = lambda k: next((ln.split(":", 1)[1].strip() for ln in head.splitlines() if ln.startswith(k + ":")), None)
        bcommit = next((ln.split()[1] for ln in head.splitlines() if ln.startswith("commit ")), None)
        if bcommit != commit:
            sys.exit(f"render_set: the bundle is of {bcommit}, --repo is at {commit}: build both from one commit")
        if "generator trees: " + " ".join(f"{d}={gtrees[d]}" for d in GEN_DIRS) not in head:
            sys.exit("render_set: the bundle's generator trees are not --repo's")
        # The checkout's generated files.
        src = repo / ASSETS
        n = 0
        for pat in FROM_REPO_LOOKDEV:
            for p in sorted((src / "lookdev").glob(pat)):
                if p.is_file():
                    out = assets / "lookdev" / p.relative_to(src / "lookdev")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(p, out)
                    n += 1
        for d in FROM_REPO_DIRS:
            if not (src / d).is_dir():
                sys.exit(f"render_set: {ASSETS}/{d} is not built (docs/TOOLING.md, 'Render asset set')")
            shutil.copytree(src / d, assets / d)
        for e in sorted((src / "envs").iterdir()):
            if e.is_dir():
                shutil.copytree(e, assets / "envs" / e.name)
        bases = sorted((assets / "lookdev/anim").glob("vroid-*.glb"))
        if not bases or not (assets / "lookdev/anim/own-clips.glb").exists():
            sys.exit("render_set: the animated bases or own-clips.glb are missing (gen_anim.sh; bundle.py --with-clips)")
        if not (src / "textures").is_dir() or not any((src / "textures").iterdir()):
            sys.exit("render_set: no terrain textures (just living-game-textures --set all)")
        # The looks: the bundle's book against the checkout's worlds.
        book = json.load(open(assets / "characters/looks.json"))
        held = set(book.get("generations") or []) | {book["generation"]}
        worlds = world_generations(repo)
        bad = {w: g for w, g in worlds.items() if g not in held}
        if bad:
            sys.exit(f"render_set: worlds at generations the book does not hold: {bad}")
        lines = manifest(assets)
        (work / "SET-MANIFEST.txt").write_text("\n".join(lines) + "\n")
        size = sum(p.stat().st_size for p in assets.rglob("*") if p.is_file())
        meta = {
            "schema": 1, "id": sid,
            "bundle": {"file": Path(a.bundle).name, "sha256": bsha, "commit": bcommit, "port": hv("port"), "pictures": hv("pictures")},
            "main_commit": commit, "generator_trees": gtrees, "generator_tree": gtree,
            "looks": {"book": book["generation"], "generations": book.get("generations") or [book["generation"]], "worlds": worlds},
            "clips": {"own_clips": clip_count(assets / "lookdev/anim/own-clips.glb"),
                      "bases": {p.name: clip_count(p) for p in bases}},
            "files": len(lines), "bytes": size,
            "built": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "build_seconds": None,
        }
        meta["build_seconds"] = round(time.time() - t0)
        (work / "set.json").write_text(json.dumps(meta, indent=1) + "\n")
        for p in sorted(work.rglob("*"), reverse=True):
            os.chmod(p, 0o555 if p.is_dir() else 0o444)
        os.chmod(work, 0o555)
        work.rename(dest)
    except BaseException:
        for p in work.rglob("*"):
            if p.is_dir():
                os.chmod(p, 0o755)
        os.chmod(work, 0o755)
        shutil.rmtree(work, ignore_errors=True)
        raise
    print(json.dumps({"set": str(dest), **{k: meta[k] for k in ("id", "files", "bytes", "build_seconds", "looks", "clips")}}, indent=1))
    if a.pin:
        pin(dest, root)


def pin(dest, root):
    root = Path(root)
    tmp = root / f".current-{os.getpid()}"
    if tmp.is_symlink():
        tmp.unlink()
    tmp.symlink_to(Path(dest).name)
    os.replace(tmp, root / "current")
    print(f"render_set: {root / 'current'} -> {Path(dest).name}")


def resolve(s, root):
    p = Path(s) if s else Path(root) / "current"
    return p.resolve()


def check(a):
    s = resolve(a.set, a.root)
    meta = json.load(open(s / "set.json"))
    reasons = []
    want = {}
    for ln in (s / "SET-MANIFEST.txt").read_text().splitlines():
        h, f = ln.split("  ", 1)
        want[f] = h
    have = {p.relative_to(s / "assets").as_posix() for p in (s / "assets").rglob("*") if p.is_file()}
    for f in sorted(set(want) - have):
        reasons.append(f"missing {f}")
    for f in sorted(have - set(want)):
        reasons.append(f"extra {f}")
    for f in sorted(set(want) & have):
        if sha256(s / "assets" / f) != want[f]:
            reasons.append(f"sha256 {f}")
    verdict = "corrupt" if reasons else "ok"
    if not reasons:
        repo = Path(a.repo).resolve()
        _, gtree = trees(repo)
        if gtree != meta["generator_tree"]:
            reasons.append(f"generator tree {gtree[:12]} at {sh('git', 'rev-parse', '--short', 'HEAD', cwd=repo)}, set's {meta['generator_tree'][:12]} (built at {meta['main_commit'][:9]})")
        held = set(meta["looks"]["generations"]) | {meta["looks"]["book"]}
        for w, g in world_generations(repo).items():
            if g not in held:
                reasons.append(f"world {w} at look generation {g}, not in the set's book ({meta['looks']['book']})")
        if reasons:
            verdict = "stale"
    print(json.dumps({"set": str(s), "id": meta["id"], "verdict": verdict, "reasons": reasons[:50]}, indent=1))
    sys.exit({"ok": 0, "corrupt": 1, "stale": 2}[verdict])


def link(a):
    """Symlink a set's generated files into a checkout's living/game/assets (refusing to replace
    anything that is not already a link): lookdev, view, textures, each envs/<name>/, characters/looks.json."""
    s = resolve(a.set, a.root)
    dst = Path(a.repo).resolve() / ASSETS
    pairs = [(s / "assets" / n, dst / n) for n in ("lookdev", "view", "textures", "characters/looks.json")]
    pairs += [(e, dst / "envs" / e.name) for e in sorted((s / "assets/envs").iterdir()) if e.is_dir()]
    for src, d in pairs:
        if d.is_symlink():
            d.unlink()
        elif d.exists():
            sys.exit(f"render_set: {d} exists and is not a link (move it aside first)")
        d.parent.mkdir(parents=True, exist_ok=True)
        d.symlink_to(src)
    print(f"render_set: {len(pairs)} links into {dst} -> {s}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--bundle", required=True, type=Path)
    b.add_argument("--repo", default=str(REPO))
    b.add_argument("--root", default=str(ROOT))
    b.add_argument("--pin", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("set", nargs="?")
    c.add_argument("--repo", default=str(REPO))
    c.add_argument("--root", default=str(ROOT))
    l = sub.add_parser("link")
    l.add_argument("set", nargs="?")
    l.add_argument("--repo", required=True)
    l.add_argument("--root", default=str(ROOT))
    p = sub.add_parser("pin")
    p.add_argument("set")
    p.add_argument("--root", default=str(ROOT))
    a = ap.parse_args()
    if a.cmd == "build":
        build(a)
    elif a.cmd == "check":
        check(a)
    elif a.cmd == "link":
        link(a)
    else:
        pin(Path(a.set).resolve(), a.root)


if __name__ == "__main__":
    main()
