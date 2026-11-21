#!/usr/bin/env python3
"""The hair mirror check (hair-mirror, README.md): draw a cut's two partings, built as mirrors,
in main's client and measure how far the drawings are mirrors.

    python3 mirror_pair.py OUT --binary BIN --left DIR --right DIR [--style NAME] [--pose bind|idle]

Each DIR holds one build: `<NAME>.glb` (default `swept_braid`) and the page it names
(`hair-masks.png`). For each, this makes the ID copies (s6/part_id.py `--all` and `--none`;
rope_id.py, the plait magenta), installs the build, its page and its copies in this checkout's
asset tree as `lookdev/styles/hair/<NAME>{,_all,_none,_rope}.glb` (**overwriting** what is there:
use a worktree whose asset tree is a copy, not a link to a shared one), measures it with
s6/image_spread.py in the pose (default `bind`, the head square) into OUT/L and OUT/R, and draws the
rope copy into OUT/<side>/rope. Then mirror_metric.py compares them: OUT/mirror.json and
OUT/mirror.png (grey both, red the left build mirrored only, blue the right only). Exit 1 when the
pair fails the acceptance.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
S6 = HERE.parent / "s6"
sys.path[:0] = [str(S6), str(HERE)]
import image_spread  # noqa: E402
import mirror_metric  # noqa: E402

PY = sys.executable


def install(src, style, work):
    hair = ROOT / "living/game/assets/lookdev/styles/hair"
    glb = src / f"{style}.glb"
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([PY, str(S6 / "part_id.py"), str(glb), str(work / f"{style}_all.glb"), "--all"], check=True)
    subprocess.run([PY, str(S6 / "part_id.py"), str(glb), str(work / f"{style}_none.glb"), "--none"], check=True)
    subprocess.run([PY, str(HERE / "rope_id.py"), str(glb), str(work / f"{style}_rope.glb")], check=True)
    for f in [glb, work / f"{style}_all.glb", work / f"{style}_none.glb", work / f"{style}_rope.glb"]:
        shutil.copyfile(f, hair / f.name)
    page = json.loads(subprocess.run([PY, "-c", "import json,struct,sys;b=open(sys.argv[1],'rb').read();n=struct.unpack('<I',b[12:16])[0];print(json.dumps([i.get('uri') for i in json.loads(b[20:20+n]).get('images',[])]))", str(glb)], capture_output=True, text=True, check=True).stdout)
    for uri in filter(None, page):
        shutil.copyfile(src / Path(uri).name, ROOT / "living/game/assets" / uri)


def measure(out, binary, style, pose):
    look = image_spread.render(out / "look", binary, style, pose)[0]
    idp = image_spread.render(out / "id", binary, f"{style}_all", pose)[0]
    face = image_spread.render(out / "none", binary, f"{style}_none", pose)[0]
    image_spread.render(out / "rope", binary, f"{style}_rope", pose)
    r, pic = image_spread.drawing_spread.render(look, idp, face=face)
    pic.save(out / "spread.png")
    (out / "spread.json").write_text(json.dumps(dict(style=style, pose=pose, **r), indent=1, default=int))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--left", type=Path, required=True)
    ap.add_argument("--right", type=Path, required=True)
    ap.add_argument("--style", default="swept_braid")
    ap.add_argument("--pose", choices=sorted(image_spread.SHOTS), default="bind")
    a = ap.parse_args()
    for side, src in (("L", a.left), ("R", a.right)):
        install(src, a.style, a.out / "copies" / side)
        shutil.rmtree(a.out / side, ignore_errors=True)
        measure(a.out / side, a.binary, a.style, a.pose)
    sys.argv = ["mirror_metric.py", str(a.out / "L"), str(a.out / "R"), str(a.out / "mirror.json")]
    mirror_metric.main()
    sys.exit(0 if json.loads((a.out / "mirror.json").read_text())["accepted"] else 1)


if __name__ == "__main__":
    os.environ.setdefault("RUST_LOG", "warn")
    main()
