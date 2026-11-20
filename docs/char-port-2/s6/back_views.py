#!/usr/bin/env python3
"""S6 back views: a composed woman in auburn, from behind at the game camera's Near and Middle stops
(58°) and in a back and a back three-quarter portrait, in a hair style; the plait measured on its
ID control (plait_id.py).

    python3 back_views.py render OUT --binary BIN --style STYLE --tag TAG
    python3 back_views.py measure OUT --tag TAG --id IDTAG          # the plait's first row, width and luma
    python3 back_views.py sheet OUT SHEET.png --tags a,b,c

**Measures** (char-live-3's, docs/char-live-3/back-hair/plait/README.md): the plait is where the ID
render is green (G over R and B by more than 28, at least 60). Its first row is the topmost such
row: the braid's start as the camera sees it. From there, at Near 17 rows and at Middle 10 rows
(Cora's windows below the nape): the width, green pixels over rows (the drawn rear: 7.4 px at
Near, 4.6 at Middle), and the mean luma of those pixels in TAG's own render (the drawn rear 69.1).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "living/tools/characters")]
import look_lines  # noqa: E402

SHOTS = [("Near, back", "near@180", (730, 360, 870, 500)), ("Middle, back", "middle@180", (755, 385, 845, 475)),
         ("back portrait", "180:8:0.36:0.88", (560, 60, 1040, 860)), ("back three-quarter", "145:8:0.36:0.88", (560, 60, 1040, 860))]
# The front set (step 2): the silhouette and the tips, as char-live-2 counted them.
FRONT = [("front portrait", "0:8:0.36:0.88", (600, 160, 1000, 620)), ("three-quarter", "-35:8:0.36:0.88", (600, 160, 1000, 620)),
         ("profile", "90:8:0.36:0.88", (600, 160, 1000, 620)), ("back portrait", "180:8:0.36:0.88", (600, 160, 1000, 620))]
WINDOW = {"near@180": 17, "middle@180": 10}
DRAWN = {"near@180": 7.4, "middle@180": 4.6}
FONT = "/usr/share/fonts/rsms-inter-fonts/Inter-Regular.ttf"


def frame(out, tag, shot):
    return next(p for p in sorted((out / tag).rglob("*.png")) if p.name.endswith(shot.replace(":", "_").replace("@", "_") + ".png"))


def render(out, binary, style, tag, shots=None):
    shots = shots or SHOTS
    line = dict(type="adult-f-b", height=1.64, colors=dict(hair="#662e1a", skin="#e8bca3", eyes="#4f7a4f"),
                styles=dict(hair=style, outfit=["jersey-f", "trousers-f", "boots-f"], overlays=[]))
    k = look_lines.key_of(line)
    d = out / tag
    d.mkdir(parents=True, exist_ok=True)
    (d / "book.json").write_text(json.dumps(dict(generation="c4-s6back01", generations=[], lines={k: dict(person=line, words={})}, decor=[])))
    env = {x: v for x, v in os.environ.items() if not x.startswith("LIVING_GAME_")}
    env.update(LIVING_GAME_VIEW=f"look:{k}", LIVING_GAME_LOOK_BOOK=str(d / "book.json"), LIVING_GAME_VIEW_SHOTS=",".join(f"idle@0/{s}" for _, s, _ in shots),
               LIVING_GAME_VIEW_OUT=str(d), LIVING_GAME_HOUR="11", LIVING_GAME_DAY_MINUTES="0", LIVING_GAME_FILM="soft",
               LIVING_GAME_SETTINGS=str(d / "settings.json"), LIVING_GAME_SIZE="1600x900", LIVING_GAME_VIEW_CLIP="idle", LIVING_GAME_SPRINGS="0", RUST_LOG="warn")
    with (d / "client.log").open("w") as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)
    print(tag, style, flush=True)


def measure(out, tag, idtag):
    res = {}
    for name, shot, _ in SHOTS:
        a = np.asarray(Image.open(frame(out, idtag, shot)).convert("RGB")).astype(int)
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        m = (g - r > 28) & (g - b > 28) & (g >= 60)
        ys = np.nonzero(m.any(axis=1))[0]
        if not len(ys):
            res[name] = dict(visible=False)
            continue
        first = int(ys.min())
        row = dict(visible=True, first_row=first, pixels=int(m.sum()))
        if shot in WINDOW:
            n = WINDOW[shot]
            win = m[first:first + n]
            own = np.asarray(Image.open(frame(out, tag, shot)).convert("RGB")).astype(float)
            luma = own[..., 0] * 0.2126 + own[..., 1] * 0.7152 + own[..., 2] * 0.0722
            row.update(rows=n, width_px=round(float(win.sum()) / n, 2), drawn_px=DRAWN[shot], width_off_px=round(float(win.sum()) / n - DRAWN[shot], 2),
                       luma=round(float(luma[first:first + n][win].mean()), 1) if win.any() else None, drawn_luma=69.1)
        res[name] = row
    (out / f"measure-{tag}.json").write_text(json.dumps(res, indent=1))
    print(tag, json.dumps(res))
    return res


def sheet(out, path, tags, shots=None):
    SHOTS_ = shots or SHOTS
    try:
        f = ImageFont.truetype(FONT, 14)
    except OSError:
        f = ImageFont.load_default()
    cell = 260
    S = Image.new("RGB", (150 + len(SHOTS_) * (cell + 6), 40 + len(tags) * (cell + 6)), (244, 241, 236))
    d = ImageDraw.Draw(S)
    for i, (name, _, _) in enumerate(SHOTS_):
        d.text((150 + i * (cell + 6), 12), name, fill=(40, 40, 40), font=f)
    for r, tag in enumerate(tags):
        d.text((10, 40 + r * (cell + 6) + cell // 2), tag, fill=(40, 40, 40), font=f)
        for i, (name, shot, box) in enumerate(SHOTS_):
            im = Image.open(frame(out, tag, shot)).convert("RGB").crop(box)
            w, h = im.size
            k = min(cell / w, cell / h)
            im = im.resize((int(w * k), int(h * k)), Image.NEAREST if shot in WINDOW else Image.LANCZOS)
            S.paste(im, (150 + i * (cell + 6), 40 + r * (cell + 6)))
    S.save(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("out", type=Path)
    ap.add_argument("dest", nargs="?")
    ap.add_argument("--binary")
    ap.add_argument("--style")
    ap.add_argument("--tag")
    ap.add_argument("--id")
    ap.add_argument("--tags")
    ap.add_argument("--front", action="store_true", help="the front set (portrait, three-quarter, profile, back portrait)")
    a = ap.parse_args()
    if a.cmd == "render":
        render(a.out, a.binary, a.style, a.tag, FRONT if a.front else None)
    elif a.cmd == "measure":
        measure(a.out, a.tag, a.id)
    else:
        sheet(a.out, a.dest, a.tags.split(","), FRONT if a.front else None)
