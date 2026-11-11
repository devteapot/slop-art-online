#!/usr/bin/env python3
"""Spike (branch char-spike): a seeded cast of 64 residents and a line-up of them.

    python3 living/tools/char_spike/cast.py OUT_DIR [--jobs 6] [--skip-build]

Cullet has 50 adults (6 of them elders) and 14 children (docs/SMALL_CITY.md §3). The residents'
sheets do not exist yet, so this draws 64 people from seeds: 22 men, 22 women, 3 old men, 3 old
women, 7 boys and 7 girls. Each is its own file from `person.py --variant <seed>:<kind>`
(gen_person.sh: generate, animate, face data) and its own recipe (height, and a child's
proportions by age). The recipes are added to recipes.json only while the photographs are taken.

Every figure is photographed alone through the asset view from the front, 24° down, at one scale
for all, and close on the face; the tiles are put side by side: OUT_DIR/lineup.jpg,
OUT_DIR/faces.jpg and OUT_DIR/cast.json.
"""

import argparse
import json
import math
import os
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
RECIPES = os.path.join(REPO, "living", "game", "assets", "characters", "recipes.json")
ROWS = [["man"] * 16, ["man"] * 6 + ["elder_man"] * 3 + ["boy"] * 7, ["woman"] * 16, ["woman"] * 6 + ["elder_woman"] * 3 + ["girl"] * 7]
SIZE, PITCH, FOV, H_REF = 900, 24.0, 35.0, 1.95
FACE = 220  # a face tile's side, pixels


def cast():
    r = random.Random(64)
    people = []
    for row in ROWS:
        for kind in row:
            i = len(people)
            p = dict(name=f"cast-{i:02d}", kind=kind, seed=100 + i, proportions={})
            if kind in ("boy", "girl"):
                age = r.uniform(4, 15)
                t = (age - 4) / 11
                p["age"] = round(age)
                p["height"] = round(1.02 + 0.56 * t + r.uniform(-0.03, 0.03), 2)
                lerp = lambda a, b: round(a + (b - a) * t, 3)
                p["proportions"] = dict(legs=lerp(0.78, 0.98), arms=lerp(0.84, 0.98), torso=lerp(0.90, 1.0), neck=lerp(0.70, 0.95), head=lerp(1.42, 1.08),
                                        shoulders=lerp(0.82, 0.94), build=lerp(0.96, 0.92), hands=1.0, feet=lerp(1.0, 1.0))
            else:
                male, old = "man" in kind and "woman" not in kind, kind.startswith("elder")
                h = r.gauss(1.77 if male else 1.64, 0.055) - (0.03 if old else 0)
                p["height"] = round(min(max(h, 1.62 if male else 1.50), 1.93 if male else 1.76), 2)
                p["proportions"] = dict(build=round(r.uniform(0.92, 1.18) if male else r.uniform(0.90, 1.10), 3), shoulders=round(r.uniform(0.96, 1.06) if male else r.uniform(0.86, 0.93), 3),
                                        legs=round(r.uniform(0.97, 1.04), 3), neck=round(r.uniform(0.9, 1.02), 3))
                if not male:
                    p["proportions"].update(hands=0.88, feet=0.9)
            p["base"] = f"lookdev/own-{p['seed']}-{kind}.glb"
            people.append(p)
    return people


def run(cmd, env=None):
    r = subprocess.run(cmd, cwd=REPO, env={**os.environ, **(env or {})}, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{cmd}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-shots", action="store_true", help="only put the sheets together again")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    people = cast()
    if not a.skip_build:
        def build(p):
            run(["living/tools/blender/gen_person.sh", f"{p['seed']}:{p['kind']}"], {"ONLY": "idle,walk"})

        with ThreadPoolExecutor(a.jobs) as ex:
            list(ex.map(build, people))
        print(f"built {len(people)} files")
    original = open(RECIPES).read()
    radius = lambda h, arms: math.sqrt(2 * (h * arms) ** 2 + h * h) / 2
    dist = radius(H_REF, 1.0) / math.tan(math.radians(FOV / 2)) * 1.05
    book = json.loads(original)
    book["recipes"] += [dict(name=p["name"], base=p["base"], height=p["height"], proportions=p["proportions"]) for p in people]
    try:
        if a.skip_shots:
            raise StopIteration
        with open(RECIPES, "w") as f:
            json.dump(book, f)
        # One scale for all: the view frames each model by its own size, so the zoom undoes that.

        def shoot(p):
            zoom = dist / (radius(p["height"], p["proportions"].get("arms", 1.0)) / math.tan(math.radians(FOV / 2)) * 1.05)
            d = os.path.join(out, "shots", p["name"])
            run(["living/tools/view_assets.sh", d, f"recipe:{p['name']}"], {"LIVING_GAME_SIZE": f"{SIZE}x{SIZE}", "LIVING_GAME_VIEW_SHOTS": f"idle@1.0/0:{PITCH}:{zoom:.4f},idle@1.0/0:4:{0.24 * p['proportions'].get('head', 1.0):.3f}:{0.925 - 0.035 * (p['proportions'].get('head', 1.0) - 1):.3f}"})

        with ThreadPoolExecutor(a.jobs) as ex:
            list(ex.map(shoot, people))
    except StopIteration:
        pass
    finally:
        with open(RECIPES, "w") as f:
            f.write(original)
    # Tiles: a window round each figure, feet on one line.
    ppm = (SIZE / 2) / (dist * math.tan(math.radians(FOV / 2)))
    tw, th = int(0.80 * ppm), int(2.10 * ppm)
    sheet = Image.new("RGB", (tw * 16, th * len(ROWS)), (150, 160, 130))
    faces = Image.new("RGB", (FACE * 16, FACE * len(ROWS)), (150, 160, 130))
    for i, p in enumerate(people):
        d = os.path.join(out, "shots", p["name"])
        shots = sorted(os.path.join(dp, x) for dp, _, fs in os.walk(d) for x in fs if x[:2].isdigit() and x.endswith(".png"))
        im = Image.open(shots[0]).convert("RGB")
        face = Image.open(shots[1]).convert("RGB")
        k = int(SIZE * 0.155)
        faces.paste(face.crop((SIZE // 2 - k, SIZE // 2 - int(0.8 * k), SIZE // 2 + k, SIZE // 2 + int(1.2 * k))).resize((FACE, FACE)), ((i % 16) * FACE, (i // 16) * FACE))
        feet = SIZE / 2 + p["height"] / 2 * ppm * math.cos(math.radians(PITCH))
        top = int(feet + 0.10 * ppm) - th
        tile = Image.new("RGB", (tw, th), im.getpixel((5, SIZE - 5)))
        tile.paste(im.crop((SIZE // 2 - tw // 2, max(top, 0), SIZE // 2 + tw // 2, min(top + th, SIZE))), (0, max(-top, 0)))
        sheet.paste(tile, ((i % 16) * tw, (i // 16) * th))
    sheet.save(os.path.join(out, "lineup.jpg"), quality=90)
    faces.save(os.path.join(out, "faces.jpg"), quality=90)
    with open(os.path.join(out, "cast.json"), "w") as f:
        json.dump(people, f, indent=1)
    print(f"wrote {os.path.join(out, 'lineup.jpg')} ({sheet.size[0]}x{sheet.size[1]}), {len(people)} people")


if __name__ == "__main__":
    main()
