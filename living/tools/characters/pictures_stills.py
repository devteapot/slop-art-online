#!/usr/bin/env python3
"""Composed people drawn by the client from two bundles, side by side: a PNG bundle against its
KTX2 conversion (docs/CHARACTERS.md, "Pictures as KTX2").

    python3 living/tools/characters/pictures_stills.py BINARY OUT png=A.tar.gz ktx2=B.tar.gz [ref=A.tar.gz@4] [--people lk_…,lk_…]

For each arm the bundle's `living/game/assets/lookdev/` and `characters/looks.json` are installed
into this worktree's game assets (git-ignored; an existing `lookdev/` is refused unless an
earlier run of this tool put it there), the people's look lines become recipes `tex-<line>` in
`characters/recipes.json` for the run (restored after), their type files' eyes are held open
(hold_eyes.py), and the client's asset view photographs them composed (`LIVING_GAME_COMPOSE=1`),
each shot with its plate (the person hidden):

- `far`:   the game camera (22 m, 28° down, 50° field), the far model as the game draws it there;
- `full`:  the same camera with the full model (`LIVING_GAME_FAR=1000`): the overlays and the
           atlas at the distance where their small mips are sampled; and the person at about the
           size the game's close camera (7.5 m) gives (`0:24:4.5:0.5`);
- `close`: the face filling the frame from the front and at 35°, and head and shoulders.

OUT/<arm>/<run>/ holds the view's frames; OUT/sheets/<run>-<shot>.png puts the arms side by side,
a row a person: the client's frame cropped round the person's head (found from the plate), and
enlarged by nearest neighbour (8× at the game camera, 4× at the close camera), so each screen pixel can be
seen. OUT/stills.json lists the people and, per shot, how far the arms' head crops differ
(mean and largest of 255, and the share of pixels more than 8 apart).

An arm `NAME=BUNDLE@N` is a supersampled reference: its `far` and `full` runs are drawn N times
larger and averaged down N×N in linear light to the others' size, which is what the screen would
show with ideal filtering (no aliasing, no mip blur). `stills.json`'s `vs_ref` then gives each
arm's head crops against it (mean of 255 and the share of pixels more than 8 apart): the arm
nearer the reference is the better drawing at that distance.

The binary must be built from this worktree (it reads its own worktree's assets). One run at a
time: never beside crowd.py, compose_check.py or colour_check.py, which also rewrite recipes.json.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
ASSETS = REPO / "living/game/assets"
RECIPES = ASSETS / "characters/recipes.json"
MARK = ".pictures-stills"
HOLD = REPO / "living/tools/characters/hold_eyes.py"

# Light and dark skin, blue and brown eyes, freckles, lines and brows (every type has brows).
PEOPLE = [
    "lk_b23bcf72f485a061",  # adult-f-a, light skin, blue eyes, lines
    "lk_97e70f4184cd645d",  # adult-f-a, light skin, brown eyes, lines and freckles
    "lk_3a24378c7d67ec75",  # elder-f-c, dark skin, brown eyes, lines
    "lk_c10f255e70477c0c",  # adult-m-b, darker skin, grey-blue eyes, short beard, lines, freckles
    "lk_785d5fa2c550b36c",  # child-u-b, light skin, green eyes, freckles
]

RUNS = {
    "far": ({"LIVING_GAME_SIZE": "1920x1080"}, "game"),
    "full": ({"LIVING_GAME_SIZE": "1920x1080", "LIVING_GAME_FAR": "1000"}, "game,0:24:4.5:0.5"),
    "close": ({"LIVING_GAME_SIZE": "900x1200", "LIVING_GAME_FAR": "1000"}, "0:4:0.14:0.93,35:4:0.14:0.93,0:6:0.32:0.92"),
}


def install(bundle, dest_tmp):
    look = ASSETS / "lookdev"
    if look.exists() and not (look / MARK).exists():
        sys.exit(f"pictures_stills: {look} exists and is not this tool's install; move it aside first")
    if look.exists():
        shutil.rmtree(look)
    with tarfile.open(bundle) as t:
        t.extractall(dest_tmp, filter="data")
    src = Path(dest_tmp) / "living/game/assets"
    shutil.copytree(src / "lookdev", look)
    (look / MARK).write_text(str(bundle) + "\n")
    shutil.copy2(src / "characters/looks.json", ASSETS / "characters/looks.json")
    return json.loads((src / "characters/looks.json").read_text())


def recipes_for(book, people):
    out = []
    for lk in people:
        p = book["lines"][lk]["person"]
        out.append({"name": f"tex-{lk}", "base": f"lookdev/types/{p['type']}.glb", "height": p["height"], "person": p})
    return out


def shrink(path, k):
    """A frame averaged down k×k in linear light (sRGB in and out)."""
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    h, w = lin.shape[0] // k, lin.shape[1] // k
    m = lin[: h * k, : w * k].reshape(h, k, w, k, 3).mean(axis=(1, 3))
    e = np.where(m <= 0.0031308, m * 12.92, 1.055 * m ** (1 / 2.4) - 0.055)
    Image.fromarray(np.clip(np.round(e * 255), 0, 255).astype(np.uint8)).save(path)


def head_box(shot, plate, frac, pad=0.25):
    """The square round the top `frac` of the figure: where the shot differs from its plate (the
    person hidden), rows with at least 3 such pixels, the head's width from the 5th to the 95th
    percentile of its columns."""
    a = np.asarray(Image.open(shot).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(plate).convert("RGB"), dtype=np.int16)
    m = np.abs(a - b).sum(axis=2) > 40
    rows = np.nonzero(m.sum(axis=1) >= 3)[0]
    if len(rows) == 0:
        return None
    y0, y1 = rows.min(), rows.max()
    hy1 = y0 + max(int((y1 - y0 + 1) * frac), 8)
    ys, xs = np.nonzero(m[y0:hy1])
    hx0, hx1 = np.percentile(xs, 5), np.percentile(xs, 95)
    s = int(max(hy1 - y0, hx1 - hx0 + 1) * (1 + pad))
    cx, cy = int(hx0 + hx1) // 2, (y0 + hy1) // 2
    x0, top = max(cx - s // 2, 0), max(cy - s // 2, 0)
    return (x0, top, x0 + s, top + s)


def frames(run_dir, person):
    d = run_dir / f"recipe:tex-{person}"
    shots = sorted(p for p in d.glob("[0-9][0-9]-*.png") if not p.name.endswith(".plate.png"))
    return {p.stem.split("-", 1)[1]: (p, p.with_name(p.stem + ".plate.png")) for p in shots}


def sheets(out, arms, people, ref=None):
    report = {}
    vs_ref = {}
    (out / "sheets").mkdir(exist_ok=True)
    for run in RUNS:
        here = [x for x in arms if run != "close" or x != ref]
        names = sorted(set().union(*[frames(out / here[0] / run, p).keys() for p in people]))
        for shot in names:
            rows = []
            for person in people:
                per_arm = [frames(out / x / run, person).get(shot) for x in here]
                if any(f is None or not f[0].exists() for f in per_arm):
                    continue
                # At the game camera the top 30% of the figure, 8×; at the close camera the head, 4×.
                frac, k = (0.3, 8) if shot == "game" else (0.2, 4)
                box = head_box(*per_arm[0], frac) if run != "close" else None
                crops = []
                for (img, _plate) in per_arm:
                    im = Image.open(img).convert("RGB")
                    crops.append(im.crop(box) if box else im)
                if ref in here:
                    r = np.asarray(crops[here.index(ref)], dtype=np.int16)
                    for arm, c in zip(here, crops):
                        if arm != ref:
                            d = np.abs(np.asarray(c, dtype=np.int16) - r)
                            vs_ref[f"{run}/{shot}/{person}/{arm}"] = {"mean": round(float(d.mean()), 3), "over8": round(float((d.max(axis=2) > 8).mean()), 4)}
                a, b = (np.asarray(c, dtype=np.int16) for c in crops[:2])
                if a.shape == b.shape:
                    d = np.abs(a - b)
                    report[f"{run}/{shot}/{person}"] = {"mean": round(float(d.mean()), 3), "max": int(d.max()), "over8": round(float((d.max(axis=2) > 8).mean()), 4)}
                if box:
                    rows.append([c.resize((c.width * k, c.height * k), Image.NEAREST) for c in crops])
                else:
                    rows.append([c.resize((c.width // 2, c.height // 2), Image.LANCZOS) for c in crops])
            if not rows:
                continue
            w = max(sum(c.width for c in r) + 8 * (len(r) - 1) for r in rows)
            h = sum(r[0].height for r in rows) + 8 * (len(rows) - 1)
            sheet = Image.new("RGB", (w, h), (32, 32, 32))
            y = 0
            for r in rows:
                x = 0
                for c in r:
                    sheet.paste(c, (x, y))
                    x += c.width + 8
                y += r[0].height + 8
            sheet.save(out / "sheets" / f"{run}-{shot}.png")
    return report, vs_ref


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("binary")
    ap.add_argument("out")
    ap.add_argument("arms", nargs="+", help="NAME=BUNDLE.tar.gz")
    ap.add_argument("--people", default=",".join(PEOPLE))
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    people = a.people.split(",")
    arms = [x.split("=", 1) for x in a.arms]
    scale = {n: int(b.rsplit("@", 1)[1]) if "@" in b else 1 for n, b in arms}
    arms = [[n, b.rsplit("@", 1)[0] if "@" in b else b] for n, b in arms]
    original = RECIPES.read_text()
    try:
        for name, bundle in arms:
            tmp = out / f".unpack-{name}"
            shutil.rmtree(tmp, ignore_errors=True)
            book = install(bundle, tmp)
            shutil.rmtree(tmp)
            r = json.loads(original)
            mine = recipes_for(book, people)
            r["recipes"] = [x for x in r["recipes"] if x["name"] not in {m["name"] for m in mine}] + mine
            RECIPES.write_text(json.dumps(r, indent=1))
            tokens = ",".join(f"recipe:tex-{p}" for p in people)
            held = subprocess.run([sys.executable, str(HOLD), "hold", tokens], check=True, capture_output=True, text=True).stdout.split()
            try:
                for run, (env, shots) in RUNS.items():
                    k = scale[name]
                    if k > 1 and run == "close":
                        continue
                    if k > 1:
                        w, h = map(int, env["LIVING_GAME_SIZE"].split("x"))
                        env = dict(env, LIVING_GAME_SIZE=f"{w * k}x{h * k}")
                    d = out / name / run
                    shutil.rmtree(d, ignore_errors=True)
                    d.mkdir(parents=True)
                    e = dict(os.environ, LIVING_GAME_VIEW=tokens, LIVING_GAME_VIEW_OUT=str(d), LIVING_GAME_VIEW_SHOTS=shots, LIVING_GAME_VIEW_PLATE="1",
                             LIVING_GAME_COMPOSE="1", RUST_LOG="warn,living_game=info", **env)
                    with open(d / "view.log", "w") as f:
                        subprocess.run([a.binary], cwd=REPO / "living/game", env=e, stdout=f, stderr=subprocess.STDOUT, timeout=900, check=False)
                    if k > 1:
                        for f in d.rglob("[0-9][0-9]-*.png"):
                            shrink(f, k)
                    print(f"{name}/{run}: {len(list(d.rglob('[0-9][0-9]-*.png')))} frames")
            finally:
                if held:
                    subprocess.run([sys.executable, str(HOLD), "release", *held], check=True)
    finally:
        RECIPES.write_text(original)
    ref = next((n for n, _ in arms if scale[n] > 1), None)
    diff, vs_ref = sheets(out, [n for n, _ in arms], people, ref)
    report = {"people": people, "arms": dict(arms), "scale": scale, "diff": diff, "vs_ref": vs_ref}
    (out / "stills.json").write_text(json.dumps(report, indent=1) + "\n")
    print(f"sheets in {out / 'sheets'}")


if __name__ == "__main__":
    main()
