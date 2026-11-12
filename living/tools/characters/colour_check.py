#!/usr/bin/env python3
"""Composed people's colours against their whole files, person by person, in pixels
(docs/CHARACTERS.md, "The client since compose-1"; verify-ui crowd.md `compose`).

    python3 living/tools/characters/colour_check.py BINARY OUT [name ...]      (default: the whole town)

Four runs of the client's asset view over the same people, each shot followed by its plate (the
same view with the person hidden, LIVING_GAME_VIEW_PLATE=1), the full model always
(LIVING_GAME_FAR=1000):

- whole:    each person's recipe on their whole both-file (LIVING_GAME_COMPOSE=0);
- composed: the same recipe composed from type and style files, style materials shared by what
            they draw (LIVING_GAME_COMPOSE=1);
- perfile:  composed with one material a style file (LIVING_GAME_PERF=filestyles), as before the
            sharing;
- again:    `composed` once more: what two runs of the same thing differ by (the clips' and the
            blink's timing, foot IK settling).

What it reports (OUT/colour.json, and a summary on stdout):

1. **Sharing changes nothing:** composed against perfile, every pixel of every shot: the share of
   pixels that differ by more than 2 of 255 in any channel, and the largest difference, beside
   composed against again. Sharing holds when the first is within the second.
2. **Colours against the whole files:** the person's pixels (where a shot differs from its plate
   by more than 30 of 255 summed over the channels) in bands of the person's height on screen:
   for the full-body shots, head (top 17%), torso (to 52%) and legs; for a close-up, the whole
   face. Each band's mean colour in both, and their difference as CIE76 ΔE (about 2 is the least
   most people notice side by side; the bands mix skin, hair and cloth, so it tells where a
   person's colours moved, not which surface).

It rewrites recipes.json for the runs and restores it after: never run it beside crowd.py or
compose_check.py. SHOTS overrides the shots, SIZE the frame. PERSON_LINES=<file> takes each person's line
from a file of person lines (`{"people": {name: line}}`, as char-4 hands them over) in place of
their `<name>.params.json`'s; ARMS=whole,composed runs only those arms (the sharing check then
reports nothing). Needs numpy and pillow.
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
RECIPES = os.path.join(REPO, "living/game/assets/characters/recipes.json")
LOOK = os.path.join(REPO, "living/game/assets/lookdev")
SHOTS = os.environ.get("SHOTS", "idle@1.0/front,idle@1.0/back,idle@1.0/0:6:0.32:0.92")
ARMS = [("whole", "0", ""), ("composed", "1", ""), ("perfile", "1", "filestyles"), ("again", "1", "")]
if os.environ.get("ARMS"):
    ARMS = [a for a in ARMS if a[0] in os.environ["ARMS"].split(",")]
LINES = json.load(open(os.environ["PERSON_LINES"]))["people"] if os.environ.get("PERSON_LINES") else {}
BANDS = [("head", 0.0, 0.17), ("torso", 0.17, 0.52), ("legs", 0.52, 1.0)]

binary, out = sys.argv[1], os.path.abspath(sys.argv[2])
people = sys.argv[3:] or sorted(f[4:-12] for f in os.listdir(os.path.join(LOOK, "lod")) if f.startswith("own-") and f.endswith(".params.json"))
os.makedirs(out, exist_ok=True)


def run(arm, compose, perf):
    d = os.path.join(out, arm)
    os.makedirs(d, exist_ok=True)
    env = dict(os.environ, LIVING_GAME_VIEW=",".join(f"recipe:town-{n}" for n in people), LIVING_GAME_VIEW_OUT=d, LIVING_GAME_VIEW_SHOTS=SHOTS, LIVING_GAME_VIEW_PLATE="1",
               LIVING_GAME_COMPOSE=compose, LIVING_GAME_FAR="1000", LIVING_GAME_SIZE=os.environ.get("SIZE", "600x800"), RUST_LOG="warn,living_game=info")
    if perf:
        env["LIVING_GAME_PERF"] = perf
    with open(os.path.join(d, "view.log"), "w") as f:
        subprocess.run([binary], cwd=os.path.join(REPO, "living/game"), env=env, stdout=f, stderr=subprocess.STDOUT, timeout=3600)


original = open(RECIPES).read()
book = json.loads(original)
for n in people:
    params = json.load(open(os.path.join(LOOK, "lod", f"own-{n}.params.json")))
    r = dict(name=f"town-{n}", base=f"lookdev/lod/own-{n}.glb", **params["recipe"], person=LINES.get(n, params["person"]))
    book["recipes"] = [x for x in book["recipes"] if x["name"] != r["name"]] + [r]
try:
    with open(RECIPES, "w") as f:
        json.dump(book, f)
    for arm, compose, perf in ARMS:
        run(arm, compose, perf)
finally:
    with open(RECIPES, "w") as f:
        f.write(original)


def load(arm, person, shot):
    d = os.path.join(out, arm, f"recipe:town-{person}")
    a, p = os.path.join(d, shot), os.path.join(d, shot[:-4] + ".plate.png")
    if not (os.path.exists(a) and os.path.exists(p)):
        return None, None
    return np.asarray(Image.open(a).convert("RGB")).astype(np.float64), np.asarray(Image.open(p).convert("RGB")).astype(np.float64)


def lab(rgb):
    """sRGB 0–255 → CIE Lab (D65)."""
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = c @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def bands(img, plate, close):
    mask = np.abs(img - plate).sum(axis=2) > 30
    rows = np.where(mask.any(axis=1))[0]
    if len(rows) == 0:
        return {}
    top, h = rows[0], rows[-1] - rows[0] + 1
    out_ = {}
    for name, a, b in [("face", 0.0, 1.0)] if close else BANDS:
        m = mask.copy()
        m[: top + int(a * h)] = False
        m[top + int(b * h) :] = False
        if m.sum() > 50:
            out_[name] = img[m].mean(axis=0)
    return out_


def changed(a, b):
    d = np.abs(a - b).max(axis=2)
    return float((d > 2).mean()), float(d.max())


report, same, noise, deltas = [], [], [], []
for p in people:
    d = os.path.join(out, "whole", f"recipe:town-{p}")
    shots = sorted(f for f in os.listdir(d) if f.endswith(".png") and not f.endswith(".plate.png")) if os.path.isdir(d) else []
    for s in shots:
        w, wp = load("whole", p, s)
        c, cp = load("composed", p, s)
        f, _ = load("perfile", p, s)
        g, _ = load("again", p, s)
        if w is None or c is None:
            continue
        row = dict(person=p, shot=s)
        if f is not None and g is not None:
            row["composed_vs_perfile"] = changed(c, f)
            row["composed_vs_again"] = changed(c, g)
            same.append(row["composed_vs_perfile"])
            noise.append(row["composed_vs_again"])
        close = "0_6_0.32" in s or ":0.32" in s
        bw, bc = bands(w, wp, close), bands(c, cp, close)
        row["bands"] = {}
        for k in bw.keys() & bc.keys():
            de = float(np.linalg.norm(lab(bw[k]) - lab(bc[k])))
            row["bands"][k] = dict(whole="#%02x%02x%02x" % tuple(int(round(x)) for x in bw[k]), composed="#%02x%02x%02x" % tuple(int(round(x)) for x in bc[k]), delta_e=round(de, 2))
            deltas.append((de, p, s, k))
        report.append(row)

summary = {}
if same:
    summary["sharing"] = dict(
        composed_vs_perfile=dict(pixels_changed_median=float(np.median([x[0] for x in same])), pixels_changed_most=max(x[0] for x in same), largest=max(x[1] for x in same)),
        composed_vs_again=dict(pixels_changed_median=float(np.median([x[0] for x in noise])), pixels_changed_most=max(x[0] for x in noise), largest=max(x[1] for x in noise)),
    )
by_band = {}
for de, p, s, k in deltas:
    by_band.setdefault(k, []).append(de)
summary["delta_e"] = {k: dict(median=round(float(np.median(v)), 2), p90=round(float(np.percentile(v, 90)), 2), most=round(max(v), 2), bands=len(v)) for k, v in sorted(by_band.items())}
summary["worst"] = [dict(delta_e=round(de, 2), person=p, shot=s, band=k) for de, p, s, k in sorted(deltas, reverse=True)[:12]]
json.dump(dict(people=len(people), shots=SHOTS, summary=summary, rows=report), open(os.path.join(out, "colour.json"), "w"), indent=1)
print(json.dumps(summary, indent=1))
