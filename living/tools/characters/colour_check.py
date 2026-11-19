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

3. **The eyes against the eye colour:** an eye close-up (`EYE_SHOT`) in every arm, and a fifth
   run, `eyes`, composed with every person's `colors.eyes` pure green: the pixels that change are
   the iris, exactly. Over them, the iris body (L* 20 to 85: the pupil and the highlights left
   out) in `composed` and in `whole`, each as CIE76 ΔE against the line's eye colour
   (`colors.eyes_natural`, else `colors.eyes`), and the composed iris against the whole file's
   (`composed_vs_whole`: what composing changes; the first two also carry the lighting and,
   since char-4's iris lights, the glow drawn over the iris). A person whose eyes are shut in the
   shot (the blink) is left out.

It rewrites recipes.json for the runs and restores it after: never run it beside crowd.py or
compose_check.py. SHOTS overrides the shots, SIZE the frame. PERSON_LINES=<file> takes each person's line
from a file of person lines (`{"people": {name: line}}`, as char-4 hands them over) in place of
their `<name>.params.json`'s; ARMS=whole,composed runs only those arms (the sharing check then
reports nothing). REUSE=1 measures an OUT already run, without running the client. Needs numpy and
pillow.
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
EYE_SHOT = "idle@1.0/0:0:0.1:0.925"
SHOTS = os.environ.get("SHOTS", "idle@1.0/front,idle@1.0/back,idle@1.0/0:6:0.32:0.92," + EYE_SHOT)
ARMS = [("whole", "0", ""), ("composed", "1", ""), ("perfile", "1", "filestyles"), ("again", "1", ""), ("eyes", "1", "")]
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
    shots = EYE_SHOT if arm == "eyes" else SHOTS
    env = dict(os.environ, LIVING_GAME_VIEW=",".join(f"recipe:town-{n}{'-green' if arm == 'eyes' else ''}" for n in people), LIVING_GAME_VIEW_OUT=d, LIVING_GAME_VIEW_SHOTS=shots, LIVING_GAME_VIEW_PLATE="1",
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
    green = json.loads(json.dumps(r))
    green["name"] += "-green"
    green["person"]["colors"]["eyes"] = "#00ff00"
    book["recipes"] = [x for x in book["recipes"] if x["name"] not in (r["name"], green["name"])] + [r, green]
if not os.environ.get("REUSE"):
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
        if s.endswith("0_0_0.1_0.925.png"):
            continue
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

def align(ref, img, mask, reach=60):
    """The shift (dy, dx) that lays `img` onto `ref` around `mask`'s box (the eye close-up is
    framed by each arm's own figure, so a whole file's eyes may sit a few pixels off a composed
    person's): the least mean absolute difference in luminance, searched in steps of 2 and then 1."""
    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = max(ys.min() - 20, reach), min(ys.max() + 20, ref.shape[0] - reach), max(xs.min() - 20, reach), min(xs.max() + 20, ref.shape[1] - reach)
    if y1 <= y0 or x1 <= x0:
        return 0, 0
    a, b = ref.mean(axis=2), img.mean(axis=2)
    win = a[y0:y1, x0:x1]
    cost = lambda dy, dx: float(np.abs(win - b[y0 + dy:y1 + dy, x0 + dx:x1 + dx]).mean())
    best = min(((cost(dy, dx), dy, dx) for dy in range(-reach, reach + 1, 2) for dx in range(-reach, reach + 1, 2)))
    best = min(((cost(dy, dx), dy, dx) for dy in range(best[1] - 1, best[1] + 2) for dx in range(best[2] - 1, best[2] + 2) if abs(dy) <= reach and abs(dx) <= reach))
    return best[1], best[2]


# The eyes: the iris where the green-eyed run differs, its body against the line's eye colour.
eye_rows = []
for p in people:
    line = LINES.get(p) or json.load(open(os.path.join(LOOK, "lod", f"own-{p}.params.json")))["person"]
    want = line["colors"].get("eyes_natural") or line["colors"].get("eyes")
    d = os.path.join(out, "composed", f"recipe:town-{p}")
    eye = [f for f in (os.listdir(d) if os.path.isdir(d) else []) if f.endswith("0_0_0.1_0.925.png")]
    g = os.path.join(out, "eyes", f"recipe:town-{p}-green")
    geye = [f for f in (os.listdir(g) if os.path.isdir(g) else []) if f.endswith("0_0_0.1_0.925.png") and not f.endswith(".plate.png")]
    if not (want and eye and geye):
        continue
    c = np.asarray(Image.open(os.path.join(d, eye[0])).convert("RGB")).astype(np.float64)
    gr = np.asarray(Image.open(os.path.join(g, geye[0])).convert("RGB")).astype(np.float64)
    w = np.asarray(Image.open(os.path.join(out, "whole", f"recipe:town-{p}", eye[0])).convert("RGB")).astype(np.float64)
    mask = np.abs(c - gr).sum(axis=2) > 60
    lc = np.array([lab(px)[0] for px in c[mask]]) if mask.sum() else np.array([])
    body = mask.copy()
    if mask.sum():
        body[mask] = (lc > 20) & (lc < 85)
    if body.sum() < 30:
        eye_rows.append(dict(person=p, iris_pixels=int(body.sum()), note="eyes shut or out of frame"))
        continue
    dy, dx = align(c, w, mask)
    w = np.roll(w, (-dy, -dx), axis=(0, 1))
    tgt = np.array([int(want[k:k + 2], 16) for k in (1, 3, 5)], dtype=np.float64)
    de_c = float(np.linalg.norm(lab(c[body].mean(axis=0)) - lab(tgt)))
    de_w = float(np.linalg.norm(lab(w[body].mean(axis=0)) - lab(tgt)))
    de_cw = float(np.linalg.norm(lab(c[body].mean(axis=0)) - lab(w[body].mean(axis=0))))
    eye_rows.append(dict(person=p, iris_pixels=int(body.sum()), eye_colour=want, composed="#%02x%02x%02x" % tuple(int(round(x)) for x in c[body].mean(axis=0)), whole="#%02x%02x%02x" % tuple(int(round(x)) for x in w[body].mean(axis=0)), composed_delta_e=round(de_c, 2), whole_delta_e=round(de_w, 2), composed_vs_whole_delta_e=round(de_cw, 2), whole_shift_px=[dy, dx]))

summary = {}
measured = [r for r in eye_rows if "composed_delta_e" in r]
if measured:
    summary["eyes"] = dict(people=len(measured), left_out=len(eye_rows) - len(measured),
                           composed=dict(median=round(float(np.median([r["composed_delta_e"] for r in measured])), 2), most=max(r["composed_delta_e"] for r in measured)),
                           whole=dict(median=round(float(np.median([r["whole_delta_e"] for r in measured])), 2), most=max(r["whole_delta_e"] for r in measured)),
                           composed_vs_whole=dict(median=round(float(np.median([r["composed_vs_whole_delta_e"] for r in measured])), 2), most=max(r["composed_vs_whole_delta_e"] for r in measured)))
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
json.dump(dict(people=len(people), shots=SHOTS, summary=summary, rows=report, eyes=eye_rows), open(os.path.join(out, "colour.json"), "w"), indent=1)
print(json.dumps(summary, indent=1))
