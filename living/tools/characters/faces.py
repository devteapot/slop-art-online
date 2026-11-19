#!/usr/bin/env python3
"""A sheet of faces, close up, through the game's renderer: the quick way to judge the character
generator's faces (living/tools/blender/person.py) while changing it.

    python3 living/tools/characters/faces.py OUT.jpg PERSON [PERSON ...] [--views 0:4,40:6] [--jobs 8] [--tile 360]

A PERSON is a preset or `<seed>:<kind>` (person.py --variant), a parameter file (`*.json`), or
`<seed>` alone, each optionally followed by `+key=value` overrides (`12+age=70+face.jaw_width=1`)
and `+!<expressions>` (`woman+!Fcl_MTH_Fun=1,Fcl_BRW_Fun=1`: person.py --expression).
Every person is generated (no clips: the rest pose), given the face's shading data
(face_normals.py), and photographed from each view (`YAW:PITCH`, degrees); one row per view.
Files go to living/game/assets/lookdev/faces-*.glb (git-ignored) and are removed afterwards
unless --keep.
"""

import argparse
import glob
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
LOOKDEV = os.path.join(REPO, "living", "game", "assets", "lookdev")


def person_args(text):
    head, *sets = text.split("+")
    if head.endswith(".json"):
        args = ["--params", os.path.abspath(head)]
    elif head.lstrip("-").isdigit():
        args = ["--seed", head]
    else:
        args = ["--variant", head]
    for s in sets:
        args += ["--expression", s[1:]] if s.startswith("!") else ["--set", s]
    return args


def run(cmd, env=None):
    r = subprocess.run(cmd, cwd=REPO, env={**os.environ, **(env or {})}, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{' '.join(cmd[:8])}\n{r.stdout[-2500:]}\n{r.stderr[-1500:]}")
    return r.stdout


def build(i, text, blender):
    f = os.path.join(LOOKDEV, f"faces-{i:03d}.glb")
    run([blender, "-b", "--python-exit-code", "1", "-P", "living/tools/blender/person.py", "--", "--out", f] + person_args(text))
    run([sys.executable, "living/tools/face_normals.py", f, f + ".tmp", "--png", f[:-4] + ".face.png"])
    os.replace(f + ".tmp", f)
    return f


TAKES = 3  # photographs of each view: the game blinks by itself, and a blink is shorter than two frames' wait


def eyes_open(paths):
    """Of several photographs of one face from one view, the one with the eyes most open: the
    most near-white pixels in the middle of the frame (the eyes' whites and highlights)."""
    def white(path):
        im = Image.open(path).convert("RGB")
        w, h = im.size
        px = im.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4)).resize((160, 160)).tobytes()
        return sum(1 for i in range(0, len(px), 3) if px[i] > 185 and px[i + 1] > 185 and px[i + 2] > 180 and abs(px[i] - px[i + 2]) < 25)

    return max(paths, key=white)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("people", nargs="+")
    ap.add_argument("--views", default="0:4,40:6")
    ap.add_argument("--zoom", type=float, default=0.115)
    ap.add_argument("--aim", type=float, default=0.918)
    ap.add_argument("--tile", type=int, default=360)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--columns", type=int, default=0, help="people per row (default: all in one row per view)")
    ap.add_argument("--labels", action="store_true")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    blender = os.environ.get("BLENDER", "blender")
    os.makedirs(LOOKDEV, exist_ok=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        files = list(ex.map(lambda t: build(t[0], t[1], blender), enumerate(a.people)))
    views = a.views.split(",")
    shots = ",".join(f"{v}:{a.zoom}:{a.aim}" for v in views for _ in range(TAKES))
    tmp = os.path.abspath(a.out) + ".shots"
    run(["rm", "-rf", tmp])
    run(["living/tools/view_assets.sh", tmp, ",".join("lookdev/" + os.path.basename(f) for f in files)], {"LIVING_GAME_SIZE": f"{a.tile * 2}x{a.tile * 2}", "LIVING_GAME_VIEW_SHOTS": shots})
    cols = a.columns or len(files)
    rows = -(-len(files) // cols)
    t = a.tile
    sheet = Image.new("RGB", (cols * t, rows * len(views) * t), (150, 160, 130))
    draw = ImageDraw.Draw(sheet)
    for i, f in enumerate(files):
        d = os.path.join(tmp, os.path.basename(f)[:-4])
        pics = sorted(glob.glob(os.path.join(d, "[0-9]*-*.png")))
        if len(pics) < len(views) * TAKES:
            sys.exit(f"{d}: {len(pics)} pictures for {len(views)} views")
        for k in range(len(views)):
            im = Image.open(eyes_open(pics[k * TAKES : (k + 1) * TAKES])).convert("RGB").resize((t, t), Image.LANCZOS)
            sheet.paste(im, ((i % cols) * t, ((i // cols) * len(views) + k) * t))
        if a.labels:
            draw.text(((i % cols) * t + 6, (i // cols) * len(views) * t + 4), a.people[i][:48], fill=(20, 20, 20))
    sheet.save(a.out, quality=90)
    run(["rm", "-rf", tmp])
    if not a.keep:
        for f in files:
            for x in glob.glob(f[:-4] + ".*"):
                os.remove(x)
    print(f"wrote {a.out} ({sheet.size[0]}x{sheet.size[1]}), {len(files)} people")


if __name__ == "__main__":
    main()
