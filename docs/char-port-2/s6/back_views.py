#!/usr/bin/env python3
"""S6 back views: a composed woman in auburn, from behind at the game camera's Near and Middle stops
(58°) and in a back and a back three-quarter portrait, in a hair style; the plait measured on its
ID control (plait_id.py).

    python3 back_views.py render OUT --binary BIN --style STYLE --tag TAG
    python3 back_views.py measure OUT --tag TAG --id IDTAG          # the plait's first row, width and luma
    python3 back_views.py sheet OUT SHEET.png --tags a,b,c
    python3 back_views.py outline OUT OUTLINE.png --id ALLTAG           # flyaways: tips outside the hair's outline (step 3)

**Measures** (char-live-3's, docs/char-live-3/back-hair/plait/README.md): the plait is where the ID
render is green (G over R and B by more than 28, at least 60). Its first row is the topmost such
row: the braid's start as the camera sees it. From there, at Near 17 rows and at Middle 10 rows
(Cora's windows below the nape): the width, green pixels over rows (the drawn rear: 7.4 px at
Near, 4.6 at Middle), and the mean luma of those pixels in TAG's own render (the drawn rear 69.1).

**The outline check** (step 3, the GC's: no lock points out from the head): on the front set of an
all-hair ID render (part_id.py --all), the hair is the green. Its body is the hair with every
part narrower than BODY px taken off (an opening by a BODY-px square), its outline the body's
convex hull. A piece of hair outside the outline hangs if it runs down from where it leaves it,
within HANG degrees of straight down (the jaw strands, below the jaw): a lock may hang. Any other
piece points out, and its reach is the furthest of its pixels from the outline; each over MARGIN
px fails. Pieces under SPECK pixels are not counted, and only the portrait's crop is (the head:
the plait below it hangs, and a piece that runs on past the crop's foot is counted as hanging).
The portraits' scale is about 1.0 px per mm
at the head (the head's 0.232 m is about 230 px), so MARGIN is about 4 mm.
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
BODY, MARGIN, HANG, SPECK = 15, 4, 35.0, 4
GATED = ("front portrait", "three-quarter", "back portrait")  # the GC's three; the profile is reported, not held (its fringe ends stand over the brow side-on)


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


def green(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (g - r > 28) & (g - b > 28) & (g >= 60)


def hull(points):
    """The convex hull of integer (x, y) points, counter-clockwise (Andrew's monotone chain)."""
    P = sorted(set(map(tuple, points)))
    if len(P) < 3:
        return P
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in P:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(P):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def components(mask):
    """Connected pieces (8-neighbour) of a boolean mask, as lists of (y, x)."""
    seen = np.zeros_like(mask)
    out = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack, piece = [(y0, x0)], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            piece.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    v, u = y + dy, x + dx
                    if 0 <= v < mask.shape[0] and 0 <= u < mask.shape[1] and mask[v, u] and not seen[v, u]:
                        seen[v, u] = True
                        stack.append((v, u))
        out.append(piece)
    return out


def outline(out, path, idtag, shots=None):
    """Each shot's tips outside the hair's outline (the module's docstring), drawn and listed."""
    from PIL import ImageFilter
    shots = shots or FRONT
    res, cells = {}, []
    for name, shot, box in shots:
        a = np.asarray(Image.open(frame(out, idtag, shot)).convert("RGB")).astype(int)
        m = green(a)
        x0, y0, x1, y1 = box
        m[:y0], m[y1:], m[:, :x0], m[:, x1:] = False, False, False, False  # the portrait's crop: the head, not the plait down the back
        im = Image.fromarray((m * 255).astype(np.uint8))
        body = np.asarray(im.filter(ImageFilter.MinFilter(BODY)).filter(ImageFilter.MaxFilter(BODY))) > 0
        ys, xs = np.nonzero(body)
        H = hull(np.stack([xs, ys], axis=1)) if len(xs) else []
        fill = Image.new("L", im.size, 0)
        if len(H) >= 3:
            ImageDraw.Draw(fill).polygon([tuple(map(int, p)) for p in H], fill=255)
        inside = np.asarray(fill) > 0
        edge = inside & ~(np.roll(inside, 1, 0) & np.roll(inside, -1, 0) & np.roll(inside, 1, 1) & np.roll(inside, -1, 1))
        ey, ex = np.nonzero(edge)
        tips, hanging, hang_px = [], [], np.zeros_like(m)
        for piece in components(m & ~inside):
            if len(piece) < SPECK:
                continue  # a speck: a thin tip broken by the pixels
            P = np.array(piece)
            d = np.sqrt(((P[:, None, 0] - ey[None]) ** 2 + (P[:, None, 1] - ex[None]) ** 2).min(axis=1)) if len(ey) else np.zeros(len(P))
            k = int(np.argmax(d))
            root = P[d <= max(1.5, d.min() + 0.5)].mean(axis=0)
            dy, dx = P[k] - root
            angle = float(np.degrees(np.arctan2(abs(dx), dy))) if d[k] > 0 else 0.0  # from straight down
            t = dict(reach_px=round(float(d[k]), 1), at=[int(P[k, 1]), int(P[k, 0])], pixels=len(P), from_down_deg=round(angle, 1))
            if (dy > 0 and angle <= HANG) or P[:, 0].max() >= y1 - 1:  # hangs, or runs on past the crop's foot (the plait)
                hanging.append(t)
                hang_px[P[:, 0], P[:, 1]] = True
            else:
                tips.append(t)
        tips.sort(key=lambda t: -t["reach_px"])
        over = [t for t in tips if t["reach_px"] > MARGIN]
        res[name] = dict(gated=name in GATED, ok=not over, over_margin=len(over), max_reach_px=tips[0]["reach_px"] if tips else 0.0, tips=tips[:12],
                         hanging=sorted(hanging, key=lambda t: -t["reach_px"])[:6])
        # The picture: the ID render, the outline (blue), what hangs below it (yellow), what points out (red), each over the margin numbered.
        px = np.asarray(Image.open(frame(out, idtag, shot)).convert("RGB")).copy()
        px[m & ~inside] = (255, 0, 0)
        px[hang_px] = (255, 200, 0)
        px[edge] = (0, 60, 255)
        pic = Image.fromarray(px)
        d = ImageDraw.Draw(pic)
        for i, t in enumerate(over, 1):
            x, y = t["at"]
            d.ellipse((x - 9, y - 9, x + 9, y + 9), outline=(255, 0, 0), width=2)
            d.text((x + 10, y - 10), str(i), fill=(255, 0, 0))
        cells.append((name, pic.crop(box), res[name]))
    (out / f"outline-{idtag}.json").write_text(json.dumps(dict(body_px=BODY, margin_px=MARGIN, shots=res), indent=1))
    try:
        f = ImageFont.truetype(FONT, 13)
    except OSError:
        f = ImageFont.load_default()
    w, h = cells[0][1].size
    S = Image.new("RGB", (len(cells) * (w + 8), h + 40), (244, 241, 236))
    d = ImageDraw.Draw(S)
    for i, (name, pic, r) in enumerate(cells):
        d.text((i * (w + 8) + 4, 6), f"{name}{'' if r['gated'] else ' (not held)'}: {'ok' if r['ok'] else str(r['over_margin']) + ' over'}, furthest {r['max_reach_px']} px", fill=(40, 40, 40), font=f)
        S.paste(pic, (i * (w + 8), 34))
    S.save(path)
    print(json.dumps(dict(passed=all(v["ok"] for v in res.values() if v["gated"]), shots={k: (v["ok"], v["over_margin"], v["max_reach_px"]) for k, v in res.items()})))
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
    elif a.cmd == "outline":
        outline(a.out, a.dest, a.id)
    else:
        sheet(a.out, a.dest, a.tags.split(","), FRONT if a.front else None)
