#!/usr/bin/env python3
"""One composed-character bundle from this worktree's built files at its HEAD: the char-4 practice,
one bundle per commit, published twice (PNG and KTX2), with the checks it must fail on
(docs/CHARACTERS.md, "Pictures as KTX2"; docs/HANDMADE_COMPOSED.md, "Bundles"; docs/TOOLING.md,
"Render asset set").

    python3 living/tools/characters/bundle.py OUT_DIR [--book LOOKS.json] [--name char-composed]
        [--port hair,ink] [--with-clips] [--note TEXT] [--skip-checks] [--keep-raw]

What it packs, at the files' repository paths:
- `living/game/assets/lookdev/types/<type>.glb` and `<type>.face.png` (the 21 types);
- `living/game/assets/lookdev/pages/*` (the far, tint and iris pages and `types.json`);
- `living/game/assets/lookdev/styles/{hair,outfit,overlay}/...` (every style file);
- `living/game/assets/lookdev/strands.png` (the hair styles' shared picture), when the build has it;
- `living/game/assets/characters/looks.json`, the client's look book;
- `living/seeds/worlds/<world>/looks.json` for every world with look data (Cullet and the island),
  and Cullet's `look-cases.json`;
- with `--with-clips`, `lookdev/anim/own-clips.glb`, the shared clip bake (the gate's render set
  carries it; the laptop bakes its own, so its bundles leave it out and say so);
- at the root, `cullet-people.json` (each resident's line as built, and every file's use count)
  and `MANIFEST.txt` (a header, then every file's sha256).

The book. It is git-ignored and append-only (look_lines.py `book`), and a bundle ships the one the
last bundle shipped. It is never written again in place. `--book FILE` copies a given book to its
path first (the previous bundle's, unpacked); without it the one already there is used.
`book_drift.py` then makes the book again from the built residents into a scratch file. Each worn
line may differ from the shipped one by one level of 255 in an outfit colour; anything more fails.

The port's pages (`--port`, docs/char-port-2/PLAN.md): `SLOP_PORT` names what the generator was
run with (`hair`, `ink`). With `ink` the ink page and its manifest are packed
(`types/types.*.ink.png`, `types/types.ink.json`); with `hair`, the hair-mask pages and the styles'
`*.hairpage.json`. Without `--port`, any such file in the build fails the bundle: a mixed build.
The manifest records the port either way (`port: none` for main's defaults).

The checks, each of which fails the bundle (`--skip-checks` is for a dry run only, and is written
into the manifest):
- eye_colours.py --check, shade_mean.py --check, look_lines.py wear --check, skeleton_check.py,
  brow_check.py --book, fringe_check.py;
- cloth_check.py on every tenth resident (nothing comes through anything);
- book_drift.py;
- one generation: every world's `looks.generation` is one of the book's `generations` (or its
  own), and every key a world's people and pool name is a line of the book;
- the clip bake, when packed, shares the types' skeleton (skeleton_check.py reads it).

Writes OUT_DIR/<name>-<sha8>.tar.gz (pictures: png) and OUT_DIR/<name>-<sha8>-ktx2.tar.gz (BC7
KTX2), each through `pictures.py bundle` and passing `pictures.py check`, and prints their paths,
file counts and sizes. Build on dev-box only: KTX2 bytes depend on the encoder's CPU kernel.
"""

import argparse
import collections
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LOOKDEV = "living/game/assets/lookdev"
BOOK = "living/game/assets/characters/looks.json"
WORLDS = REPO / "living/seeds/worlds"
TOOLS = "living/tools/characters"


def run(cmd, what, env=None):
    """Run a check; its last line is printed; a non-zero exit fails the bundle."""
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
    out = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode:
        sys.exit(f"bundle: {what} failed (exit {r.returncode}):\n{r.stdout[-2000:]}{r.stderr[-2000:]}")
    print(f"{what}: {out}")
    return r.stdout


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def port_files(rel):
    """Is this lookdev file one of the port's (ink page, hair masks, hair-page records)?"""
    n = os.path.basename(rel)
    return ("ink" if (n.startswith("types.") and (n.endswith(".ink.png") or n == "types.ink.json")) else
            "hair" if (n.startswith("hair-masks") or n.endswith(".hairpage.json")) else None)


def world_books():
    """Every world with look data: {name: (path, data)}."""
    out = {}
    for p in sorted(WORLDS.glob("*/looks.json")):
        out[p.parent.name] = (p, json.load(open(p)))
    return out


def files_list(port, with_clips):
    """The bundle's files, repository paths, sorted; and the port files found in the build."""
    L = REPO / LOOKDEV
    files, found = [], collections.defaultdict(list)
    for p in sorted((L / "types").glob("*")):
        if p.is_file() and (p.suffix == ".glb" or p.name.endswith(".face.png") or port_files(p.name)):
            rel = str(p.relative_to(REPO))
            k = port_files(p.name)
            if k:
                found[k].append(rel)
                if k not in port:
                    continue
            files.append(rel)
    for d in ("pages", "styles"):
        for p in sorted((L / d).rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(REPO))
                k = port_files(p.name)
                if k:
                    found[k].append(rel)
                    if k not in port:
                        continue
                files.append(rel)
    # The hair styles' shared picture, as the build left it; pictures.py refuses it unnamed (an orphan).
    if (L / "strands.png").exists():
        files.append(f"{LOOKDEV}/strands.png")
    if with_clips:
        files.append(f"{LOOKDEV}/anim/own-clips.glb")
    files.append(BOOK)
    for name, (p, _) in world_books().items():
        files.append(str(p.relative_to(REPO)))
        cases = p.parent / "look-cases.json"
        if cases.exists():
            files.append(str(cases.relative_to(REPO)))
    for f in files:
        if not (REPO / f).is_file():
            sys.exit(f"bundle: {f} is missing (build it first: docs/TOOLING.md, 'Render asset set')")
    return sorted(set(files)), found


def residents():
    """Cullet's residents as built: {slug: line}, from lookdev/own-<slug>.params.json."""
    import re
    w = json.load(open(WORLDS / "cullet/looks.json"))
    people = {}
    for name in w["residents"]:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        p = REPO / LOOKDEV / f"own-{slug}.params.json"
        if not p.exists():
            sys.exit(f"bundle: resident {name} is not built ({p.relative_to(REPO)}): run town.py --town living/seeds/cullet.json --models-only")
        people[slug] = json.load(open(p))["person"]
    return dict(sorted(people.items()))


def use_counts(lines):
    """Every type and style file the lines wear, with how many wear it (cullet-people.json's `files`)."""
    c = collections.Counter()
    for line in lines:
        c["types/" + line["type"]] += 1
        c["hair/" + line["styles"]["hair"]] += 1
        for p in line["styles"]["outfit"]:
            c["outfit/" + p] += 1
        for o in line["styles"].get("overlays", []):
            c[f"overlay/{line['type']}/{o}"] += 1
    return dict(sorted(c.items()))


def clip_count(path):
    import struct
    with open(path, "rb") as f:
        f.read(12)
        n = struct.unpack("<I", f.read(4))[0]
        f.read(4)
        return len(json.loads(f.read(n)).get("animations", []))


def generations(book, worlds):
    """One generation: each world's is in the book, and every key it names is a book line."""
    held = set(book.get("generations") or [book["generation"]]) | {book["generation"]}
    out = {}
    for name, (_, w) in worlds.items():
        g = w["looks"]["generation"]
        if g not in held:
            sys.exit(f"bundle: world {name} is at look generation {g}, which the book ({book['generation']}) does not hold")
        keys = [k for person in w["looks"]["people"].values() for k in person.values()]
        missing = [k for k in keys if k not in book["lines"]]
        missing += [p for p in w["looks"].get("pool", []) if p not in w["looks"]["people"]]
        missing += [p for p in w.get("residents", {}).values() if p not in w["looks"]["people"]]
        if missing:
            sys.exit(f"bundle: world {name}'s keys missing from the book: {missing[:5]} ({len(missing)})")
        out[name] = g
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--book", type=Path, help="the shipped book to bundle (copied to its path first)")
    ap.add_argument("--name", default="char-composed")
    ap.add_argument("--port", default=os.environ.get("SLOP_PORT", ""), help="what SLOP_PORT the build used: '', 'hair', 'ink' or 'hair,ink'")
    ap.add_argument("--with-clips", action="store_true", help="pack lookdev/anim/own-clips.glb (the gate's render set)")
    ap.add_argument("--note", default="", help="a line for the manifest's header")
    ap.add_argument("--skip-checks", action="store_true", help="a dry run: no checks (written into the manifest)")
    ap.add_argument("--keep-raw", action="store_true", help="keep the raw tarball beside the two bundles")
    a = ap.parse_args()
    port = sorted(x for x in a.port.split(",") if x)
    if set(port) - {"hair", "ink"}:
        sys.exit(f"bundle: --port takes hair and ink, not {a.port}")
    t0 = time.time()
    if git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("bundle: tracked files differ from HEAD (a bundle is of a commit)")
    head = git("rev-parse", "HEAD")
    sha8 = head[:8]
    if a.book:
        dest = REPO / BOOK
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(a.book, dest)
    book = json.load(open(REPO / BOOK))
    files, found = files_list(port, a.with_clips)
    stray = {k: v for k, v in found.items() if k not in port}
    if stray:
        sys.exit(f"bundle: the build holds the port's {', '.join(stray)} files but --port is '{','.join(port)}' "
                 f"(a mixed build: {next(iter(stray.values()))[:3]}); build again with the same SLOP_PORT")
    missing_port = [k for k in port if not found.get(k)]
    if missing_port:
        sys.exit(f"bundle: --port {','.join(port)} but the build has no {', '.join(missing_port)} files")
    worlds = world_books()
    gens = generations(book, worlds)
    print(f"looks: book {book['generation']} ({len(book['lines'])} lines, holds {book.get('generations')}); worlds {gens}")
    L = LOOKDEV
    if not a.skip_checks:
        run(["python3", f"{TOOLS}/eye_colours.py", f"{L}/types", "--check"], "eye_colours")
        run(["python3", f"{TOOLS}/shade_mean.py", "--check", f"{L}/styles"], "shade_mean")
        run(["python3", f"{TOOLS}/look_lines.py", "wear", "--check", f"{L}/styles"], "look_lines wear")
        run(["python3", f"{TOOLS}/skeleton_check.py", L], "skeleton_check")
        run(["python3", f"{TOOLS}/book_drift.py"], "book_drift")
        run(["python3", f"{TOOLS}/brow_check.py", f"{L}/types", "--book", BOOK], "brow_check")
        run(["python3", f"{TOOLS}/fringe_check.py", L], "fringe_check")
    people = residents()
    if not a.skip_checks:
        sample = [s for i, s in enumerate(people) if i % 10 == 0]
        for s in sample:
            out = run(["python3", f"{TOOLS}/cloth_check.py", f"{L}/own-{s}.params.json", "--quiet"], f"cloth_check {s}")
            if "none comes through" not in out.strip().splitlines()[-1]:
                sys.exit(f"bundle: cloth_check on {s}: {out.strip().splitlines()[-1]}")
    nclips = clip_count(REPO / L / "anim/own-clips.glb") if (REPO / L / "anim/own-clips.glb").exists() else None
    a.out.mkdir(parents=True, exist_ok=True)
    w = Path(tempfile.mkdtemp(dir=a.out))
    try:
        (w / "cullet-people.json").write_text(json.dumps({"people": people, "files": use_counts(people.values())}, indent=1) + "\n")
        clips = (f"clips: lookdev/anim/own-clips.glb is in this bundle ({nclips} clips)." if a.with_clips else
                 "clips: lookdev/anim/own-clips.glb is not in this bundle. The laptop bakes its own from its clip library on this "
                 "bundle's skeleton (ONLY=present LOD=near living/tools/blender/gen_person.sh clips=man; then skeleton_check.py "
                 f"must print 0). The dev-box's bake at this commit has {nclips} clips.")
        tree = {d: git("rev-parse", f"HEAD:living/tools/{d}") for d in ("blender", "characters", "textures")}
        head_lines = [
            "Slop Art Online — composed characters (living/tools/characters/bundle.py)",
            f"commit {head}",
            f"built {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
            "generator trees: " + " ".join(f"{d}={t}" for d, t in tree.items()),
            f"looks: book {book['generation']}, holds {' '.join(book.get('generations') or [book['generation']])}; "
            + "; ".join(f"{n} {g}" for n, g in gens.items()),
            f"port: {','.join(port) or 'none'}",
            clips,
        ]
        if a.skip_checks:
            head_lines.append("checks: SKIPPED (a dry run; not for delivery)")
        if a.note:
            head_lines.append(a.note)
        with open(w / "MANIFEST.txt", "w") as m:
            m.write("\n".join(head_lines) + "\n\n")
            for f in files:
                m.write(f"{sha256(REPO / f)}  {f}\n")
            m.write(f"{sha256(w / 'cullet-people.json')}  cullet-people.json\n")
        raw = w / "raw.tar.gz"
        (w / "files.txt").write_text("\n".join(files) + "\n")
        subprocess.run(["tar", "-czf", str(raw), "-C", str(REPO), "-T", str(w / "files.txt"),
                        "-C", str(w), "cullet-people.json", "MANIFEST.txt"], check=True)
        outs = []
        for kind, suffix in (("png", ""), ("ktx2", "-ktx2")):
            out = a.out / f"{a.name}-{sha8}{suffix}.tar.gz"
            run(["python3", f"{TOOLS}/pictures.py", "bundle", str(raw), str(out), "--pictures", kind], f"pictures {kind}")
            run(["python3", f"{TOOLS}/pictures.py", "check", str(out)], f"pictures check {kind}")
            outs.append(out)
        if a.keep_raw:
            shutil.move(str(raw), a.out / f"{a.name}-{sha8}-raw.tar.gz")
    finally:
        shutil.rmtree(w, ignore_errors=True)
    for out in outs:
        n = int(subprocess.run(["sh", "-c", f"tar -tzf '{out}' | wc -l"], capture_output=True, text=True).stdout)
        print(f"{out}: {n} files, {out.stat().st_size / 1e6:.1f} MB")
    print(f"bundle: {len(files) + 2} files, port {','.join(port) or 'none'}, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
