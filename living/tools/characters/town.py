#!/usr/bin/env python3
"""A town's people from the character generator, and the page to check them by.

    python3 living/tools/characters/town.py OUT_DIR [--town FILE.json] [--only NAME,...] [--household ID]
                                            [--jobs 6] [--skip-build] [--skip-shots] [--write-town FILE.json]

One command generates a household or the whole town: every person's model (gen_person.sh:
person.py, then the clips, merged primitives and the face's shading data), a photograph of each
through the game's renderer, and OUT_DIR/index.html with the sheets:

- `lineup.jpg`: everyone at one scale, from the front at the game camera's angle (28° down);
- `game.jpg`: everyone through the game camera itself (22 m away), the pixels enlarged;
- `faces.jpg`: every face close up; `faces-24.jpg`: 24 of them larger;
- `town.json`: each person's full parameters and game recipe (height, proportions).

A town file is `{"people": [{"name": …, "household": …, <person parameters>}, …]}`; anything a
person leaves out is drawn from their seed (docs/CHARACTERS.md). Without --town this draws a
stand-in for Cullet (docs/SMALL_CITY.md §3: 64 residents in 22 households, 44 adults, 6 elders,
14 children, Kiln and Strand families); the residents' sheets replace it when they exist.
--write-town saves that stand-in as a file to edit.

The models are lookdev/own-<name>.glb and lookdev/anim/own-<name>.glb (git-ignored). Recipes
`town-<name>` are added to recipes.json only while the photographs are taken.
"""

import argparse
import html
import json
import math
import os
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from faces import TAKES, eyes_open  # noqa: E402

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
LOOKDEV = os.path.join(REPO, "living", "game", "assets", "lookdev")
RECIPES = os.path.join(REPO, "living", "game", "assets", "characters", "recipes.json")
SIZE, PITCH, FOV, H_REF = 900, 28.0, 35.0, 1.95
FACE_SIZE, FACE = 1200, 300  # the face shot's side, and a face tile's side on the sheet of all
PER_ROW = 16


def cullet():
    """A stand-in cast for Cullet: 22 households, 6 with an elder, a couple and a child, 4 of a
    couple and two children, 8 couples, 4 pairs of grown siblings. Blood relatives share a
    family seed and a skin tone; those who married in bring their own."""
    r = random.Random(64)
    kinds = ["elder"] * 6 + ["family"] * 4 + ["couple"] * 8 + ["siblings"] * 4
    r.shuffle(kinds)
    people = []
    for h, kind in enumerate(kinds):
        line = "kiln" if h % 2 == 0 else "strand"
        hid = f"{line}-{h // 2 + 1:02d}"
        fam = 1000 + h
        # Kiln families have been here for generations; Strand families came from everywhere.
        tone = r.uniform(0.05, 0.30) if line == "kiln" else r.choice([r.uniform(0.05, 0.40), r.uniform(0.35, 0.95)])

        def add(role, sex, age, blood=True):
            i = len(people)
            p = dict(name=f"{hid}-{role}", household=hid, seed=100 + i, sex=sex, age=round(age, 1))
            if blood:
                p.update(family=fam, skin=dict(tone=round(min(max(tone + r.uniform(-0.04, 0.04), 0), 1), 2)))
            people.append(p)

        s1 = r.choice(("male", "female"))
        s2 = "female" if s1 == "male" else "male"
        if kind == "elder":
            a1 = r.uniform(27, 46)
            add("elder", r.choice(("male", "female")), a1 + r.uniform(24, 32))
            add("a", s1, a1)
            add("b", s2, a1 + r.uniform(-5, 5), blood=False)
            add("child", r.choice(("male", "female")), r.uniform(1, min(15.5, a1 - 19)))
        elif kind == "family":
            a1 = r.uniform(27, 44)
            add("a", s1, a1)
            add("b", s2, a1 + r.uniform(-5, 5), blood=False)
            first = r.uniform(4, min(15.5, a1 - 19))
            add("child1", r.choice(("male", "female")), first)
            add("child2", r.choice(("male", "female")), max(1.0, first - r.uniform(2, 5)))
        elif kind == "couple":
            a1 = r.uniform(20, 59)
            add("a", s1, a1)
            add("b", s2, min(max(a1 + r.uniform(-6, 6), 19), 59), blood=False)
        else:
            a1 = r.uniform(19, 55)
            add("a", s1, a1)
            add("b", r.choice(("male", "female")), min(max(a1 + r.uniform(-8, 8), 18), 59))
    return dict(name="cullet (stand-in)", people=people)


def run(cmd, env=None):
    r = subprocess.run(cmd, cwd=REPO, env={**os.environ, **(env or {})}, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{' '.join(str(c) for c in cmd[:6])}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r.stdout


def kind_of(p):
    age, male = p["age"], p["sex"] == "male"
    return ("boy" if male else "girl") if age < 16 else (("old man" if male else "old woman") if age >= 60 else ("man" if male else "woman"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--town", help="a town file (default: the stand-in for Cullet)")
    ap.add_argument("--write-town", help="save the town's people to this file and stop")
    ap.add_argument("--only", help="comma-separated names")
    ap.add_argument("--household", help="one household's id")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--clips", default="idle,walk", help="library clips each person gets (gen_person.sh ONLY)")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-shots", action="store_true", help="only put the sheets and the page together again")
    a = ap.parse_args()
    town = json.load(open(a.town)) if a.town else cullet()
    if a.write_town:
        with open(a.write_town, "w") as f:
            json.dump(town, f, indent=1)
        print(f"wrote {a.write_town}: {len(town['people'])} people")
        return
    people = town["people"]
    if a.only:
        people = [p for p in people if p["name"] in a.only.split(",")]
    if a.household:
        people = [p for p in people if p.get("household") == a.household]
    if not people:
        sys.exit("no people to make")
    out = os.path.abspath(a.out)
    os.makedirs(os.path.join(out, "people"), exist_ok=True)
    for p in people:
        p["file"] = os.path.join(out, "people", p["name"] + ".json")
        with open(p["file"], "w") as f:
            json.dump({k: v for k, v in p.items() if k not in ("name", "household", "file")}, f, indent=1)
    if not a.skip_build:
        def build(p):
            run(["living/tools/blender/gen_person.sh", f"{p['name']}={p['file']}"], {"ONLY": a.clips})

        with ThreadPoolExecutor(a.jobs) as ex:
            list(ex.map(build, people))
        print(f"built {len(people)} people")
    # What the generator made of each: full parameters and the recipe.
    for p in people:
        made = json.load(open(os.path.join(LOOKDEV, f"own-{p['name']}.params.json")))
        p["params"], p["recipe"] = made["params"], made["recipe"]
        p["recipe_name"] = "town-" + p["name"]
    original = open(RECIPES).read()
    radius = lambda h, arms: math.sqrt(2 * (h * arms) ** 2 + h * h) / 2
    dist = radius(H_REF, 1.0) / math.tan(math.radians(FOV / 2)) * 1.05
    book = json.loads(original)
    book["recipes"] += [dict(name=p["recipe_name"], base=f"lookdev/own-{p['name']}.glb", **p["recipe"]) for p in people]
    shots = os.path.join(out, "shots")
    if not a.skip_shots:
        try:
            with open(RECIPES, "w") as f:
                json.dump(book, f)

            def shoot(p):
                prop = p["recipe"]["proportions"]
                head = prop.get("head", 1.0)
                # One scale for all: the view frames each model by its own size, so the zoom undoes that.
                zoom = dist / (radius(p["recipe"]["height"], prop.get("arms", 1.0)) / math.tan(math.radians(FOV / 2)) * 1.05)
                d = os.path.join(shots, p["name"])
                run(["rm", "-rf", d])
                run(["living/tools/view_assets.sh", os.path.join(d, "a"), f"recipe:{p['recipe_name']}"], {"LIVING_GAME_SIZE": f"{SIZE}x{SIZE}", "LIVING_GAME_VIEW_SHOTS": f"idle@1.0/0:{PITCH}:{zoom:.4f}"})
                run(["living/tools/view_assets.sh", os.path.join(d, "b"), f"recipe:{p['recipe_name']}"],
                    {"LIVING_GAME_SIZE": f"{FACE_SIZE}x{FACE_SIZE}", "LIVING_GAME_VIEW_SHOTS": ",".join([f"idle@1.0/0:4:{0.24 * head * (1 + 0.55 * (head - 1)):.3f}:{0.925 - 0.085 * (head - 1):.3f}"] * TAKES)})
                run(["living/tools/view_assets.sh", os.path.join(d, "c"), f"recipe:{p['recipe_name']}"], {"LIVING_GAME_SIZE": "1600x900", "LIVING_GAME_VIEW_SHOTS": "idle@1.0/game"})

            with ThreadPoolExecutor(a.jobs) as ex:
                list(ex.map(shoot, people))
        finally:
            with open(RECIPES, "w") as f:
                f.write(original)
    # Sheets. Line-up tiles: a window round each figure, feet on one line.
    n = len(people)
    cols = min(PER_ROW, n)
    rows = -(-n // cols)
    ppm = (SIZE / 2) / (dist * math.tan(math.radians(FOV / 2)))
    tw, th = int(0.80 * ppm), int(2.10 * ppm)
    lineup = Image.new("RGB", (tw * cols, th * rows), (150, 160, 130))
    faces = Image.new("RGB", (FACE * cols, FACE * rows), (150, 160, 130))
    gw, gh, gk = 44, 76, 3  # the game camera's frame round a figure, and how much it is enlarged
    game = Image.new("RGB", (gw * gk * cols, gh * gk * rows), (150, 160, 130))
    crops = []

    def shot(p, part):
        d = os.path.join(shots, p["name"], part)
        found = sorted(os.path.join(dp, x) for dp, _, fs in os.walk(d) for x in fs if x[:2].isdigit() and x.endswith(".png"))
        if not found:
            sys.exit(f"no picture in {d}")
        # The game blinks by itself: of the face's photographs, the one with the eyes open.
        return Image.open(eyes_open(found) if part == "b" else found[0]).convert("RGB")

    for i, p in enumerate(people):
        im, face, far = shot(p, "a"), shot(p, "b"), shot(p, "c")
        k = int(FACE_SIZE * 0.180)
        crop = face.crop((FACE_SIZE // 2 - k, FACE_SIZE // 2 - int(0.90 * k), FACE_SIZE // 2 + k, FACE_SIZE // 2 + int(1.10 * k)))
        crops.append(crop)
        faces.paste(crop.resize((FACE, FACE), Image.LANCZOS), ((i % cols) * FACE, (i // cols) * FACE))
        feet = SIZE / 2 + p["recipe"]["height"] / 2 * ppm * math.cos(math.radians(PITCH))
        top = int(feet + 0.10 * ppm) - th
        tile = Image.new("RGB", (tw, th), im.getpixel((5, SIZE - 5)))
        tile.paste(im.crop((SIZE // 2 - tw // 2, max(top, 0), SIZE // 2 + tw // 2, min(top + th, SIZE))), (0, max(-top, 0)))
        lineup.paste(tile, ((i % cols) * tw, (i // cols) * th))
        # The game camera looks at the figure's middle: the frame's centre.
        w, h = far.size
        g = far.crop((w // 2 - gw // 2, h // 2 - gh // 2 - 4, w // 2 + gw // 2, h // 2 + gh // 2 - 4)).resize((gw * gk, gh * gk), Image.NEAREST)
        game.paste(g, ((i % cols) * gw * gk, (i // cols) * gh * gk))
    lineup.save(os.path.join(out, "lineup.jpg"), quality=90)
    faces.save(os.path.join(out, "faces.jpg"), quality=88)
    game.save(os.path.join(out, "game.png"))
    # 24 faces larger: spread through the town.
    pick = [round(i * (n - 1) / 23) for i in range(24)] if n >= 24 else list(range(n))
    side = crops[0].size[0]
    big = Image.new("RGB", (side * 6, side * -(-len(pick) // 6)), (150, 160, 130))
    for j, i in enumerate(pick):
        big.paste(crops[i], ((j % 6) * side, (j // 6) * side))
    big.save(os.path.join(out, "faces-24.jpg"), quality=90)
    with open(os.path.join(out, "town.json"), "w") as f:
        json.dump(dict(name=town.get("name", ""), people=[{k: v for k, v in p.items() if k != "file"} for p in people]), f, indent=1)
    # The page.
    esc = html.escape
    trs = []
    for i, p in enumerate(people):
        q = p["params"]
        strong = sorted(q["face"].items(), key=lambda kv: -abs(kv[1]))[:4]
        trs.append(
            f"<tr><td class=n>{i + 1}</td><td>{esc(p['name'])}</td><td>{kind_of(q)}</td><td class=n>{q['age']:.0f}</td><td class=n>{p['recipe']['height']:.2f}</td>"
            f"<td>{q['skin']['tone']:.2f}</td><td>{esc(str(q['hair']['colour']))}, {esc(q['hair']['style'])}{', grey ' + format(q['hair']['grey'], '.1f') if q['hair']['grey'] > 0.15 else ''}</td>"
            f"<td>{esc(q['beard']['style']) if q['beard']['style'] != 'none' else ''}</td><td>{esc(str(q['eyes']['colour']))}</td><td>{', '.join(f'{k} {v:+.1f}' for k, v in strong)}</td><td class=n>{q['seed']}</td></tr>")
    page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width, initial-scale=1"><title>Town check: {esc(town.get('name', ''))}</title>
<style>body{{margin:0;background:#16181b;color:#e6e3da;font:15px/1.5 system-ui,sans-serif}}main{{max-width:1500px;margin:0 auto;padding:20px 14px 60px}}h1{{font-size:26px}}h2{{font-size:19px;margin-top:34px}}
.sheet{{overflow-x:auto;border:1px solid #34383e;border-radius:6px}}.sheet img{{display:block;max-width:none}}p{{max-width:80ch;color:#a0a6ad}}
table{{border-collapse:collapse;font-size:13.5px;display:block;overflow-x:auto}}th,td{{border:1px solid #34383e;padding:3px 8px;text-align:left}}td.n{{text-align:right;font-variant-numeric:tabular-nums}}</style>
<main><h1>Town check: {esc(town.get('name', ''))}</h1>
<p>{n} people from <code>living/tools/characters/town.py</code>, each photographed alone through the game's renderer. People stand in the table's order, {cols} to a row; a household stands together.</p>
<h2>Line-up, one scale, from the front at the game camera's angle ({PITCH:.0f}° down)</h2><div class=sheet><img src="lineup.jpg" alt="line-up"></div>
<h2>Through the game camera (22 m away), pixels enlarged {gk} times</h2><div class=sheet><img src="game.png" alt="game camera"></div>
<h2>Every face</h2><div class=sheet><img src="faces.jpg" alt="faces"></div>
<h2>24 faces, larger</h2><div class=sheet><img src="faces-24.jpg" alt="24 faces"></div>
<h2>The people</h2><table><tr><th>#</th><th>Name</th><th>Kind</th><th>Age</th><th>Height, m</th><th>Skin tone</th><th>Hair</th><th>Beard</th><th>Eyes</th><th>Strongest face values</th><th>Seed</th></tr>{''.join(trs)}</table>
<p>Full parameters and recipes: <code>town.json</code>; each person's parameter file: <code>people/&lt;name&gt;.json</code>.</p></main>"""
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(page)
    print(f"wrote {os.path.join(out, 'index.html')}: {n} people, line-up {lineup.size[0]}x{lineup.size[1]}")


if __name__ == "__main__":
    main()
