#!/usr/bin/env python3
"""A few town people composed from shared files (LIVING_GAME_COMPOSE=1) against their whole
files, in the client's asset view: every bone at each shot (LIVING_GAME_VIEW_JOINTS) and the
shots themselves, side by side (docs/CHARACTERS.md, "The client since compose-1").

Arms, each a recipe on the same person:
- whole:    town-X, LIVING_GAME_COMPOSE=0 (their both-file, their own recipe's numbers);
- composed: town-X, LIVING_GAME_COMPOSE=1 (their person line: type, styles, the line's numbers);
- control:  town-X-same, LIVING_GAME_COMPOSE=1, the person line with the whole recipe's
            proportions (its build), to tell the line's build from the composing itself.

    python3 living/tools/characters/compose_check.py BINARY OUT [name ...]

The people's both-files and `<name>.params.json` (with its `person` line) are under
lookdev/lod/ (town.py --lod both), the types and styles under lookdev/types/ and
lookdev/styles/. Writes OUT/<arm>/ (the view's shots, joints.jsonl, view.log), OUT/fidelity.json
(per person and shot: the largest and root-mean-square distance between the arms' bones, `J_Sec*`
spring bones and `J_Fit_Belly` left out, in metres and in file units, the ratio of their height
scales, and how far the belly's bone stands from the whole file's, `belly_mm`) and
OUT/stills/<name>.jpg (whole, composed, control side by side). It rewrites recipes.json for the
runs and restores it after: never run it beside crowd.py. SHOTS overrides the shots, SIZE the
frame. The control in file units is the composing rule itself: 0.000 mm when it holds.
"""
import json, os, subprocess, sys, math

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
RECIPES = os.path.join(REPO, "living/game/assets/characters/recipes.json")
LOOK = os.path.join(REPO, "living/game/assets/lookdev")
SHOTS = os.environ.get("SHOTS", "idle@1.0/front,idle@1.0/0:6:0.32:0.92,walk@0.25/side,walk@0.5/three-quarter")

binary, out = sys.argv[1], os.path.abspath(sys.argv[2])
people = sys.argv[3:] or ["tamsin-hollin", "fenn-brandt", "joss-tarn", "ode-pontil", "vessa-pontil", "wick-marl"]
os.makedirs(out, exist_ok=True)
original = open(RECIPES).read()
book = json.loads(original)
for n in people:
    params = json.load(open(os.path.join(LOOK, "lod", f"own-{n}.params.json")))
    r = dict(name=f"town-{n}", base=f"lookdev/lod/own-{n}.glb", **params["recipe"], person=params["person"])
    same = json.loads(json.dumps(r))
    same["name"] = f"town-{n}-same"
    same["person"]["proportions"] = {k: v for k, v in params["recipe"]["proportions"].items()}
    same["person"]["height"] = params["recipe"]["height"]
    book["recipes"] = [x for x in book["recipes"] if x["name"] not in (r["name"], same["name"])] + [r, same]


def run(arm, compose, suffix):
    d = os.path.join(out, arm)
    os.makedirs(d, exist_ok=True)
    joints = os.path.join(d, "joints.jsonl")
    if os.path.exists(joints):
        os.remove(joints)
    env = dict(os.environ, LIVING_GAME_VIEW=",".join(f"recipe:town-{n}{suffix}" for n in people), LIVING_GAME_VIEW_OUT=d, LIVING_GAME_VIEW_SHOTS=SHOTS,
               LIVING_GAME_VIEW_JOINTS=joints, LIVING_GAME_COMPOSE=compose, LIVING_GAME_FAR="1000", LIVING_GAME_SIZE=os.environ.get("SIZE", "900x1200"),
               RUST_LOG="warn,living_game=info,living_game::characters::compose=debug")
    with open(os.path.join(d, "view.log"), "w") as f:
        subprocess.run([binary], cwd=os.path.join(REPO, "living/game"), env=env, stdout=f, stderr=subprocess.STDOUT, timeout=900)


try:
    with open(RECIPES, "w") as f:
        json.dump(book, f)
    for arm, compose, suffix in (("whole", "0", ""), ("composed", "1", ""), ("control", "1", "-same")):
        run(arm, compose, suffix)
finally:
    with open(RECIPES, "w") as f:
        f.write(original)


def load(arm):
    rows = {}
    for line in open(os.path.join(out, arm, "joints.jsonl")):
        j = json.loads(line)
        who = j["file"].removeprefix("recipe:town-").removesuffix("-same")
        rows[(who, j["shot"])] = j
    return rows


def diff(a, b, units=False):
    common = sorted(set(a["joints"]) & set(b["joints"]))
    # Spring bones swing; the belly's bone stands forward on a composed person by design (its
    # whole file carries the belly in its meshes): both are reported apart.
    common = [c for c in common if not c.startswith("J_Sec") and c != "J_Fit_Belly"]
    ds = []
    for c in common:
        pa, pb = a["joints"][c], b["joints"][c]
        if units:
            pa, pb = [x / a["scale"] for x in pa], [x / b["scale"] for x in pb]
        ds.append((math.dist(pa, pb) * 1000, c))
    ds.sort()
    rms = math.sqrt(sum(d * d for d, _ in ds) / max(len(ds), 1))
    belly = None
    if "J_Fit_Belly" in a["joints"] and "J_Fit_Belly" in b["joints"]:
        pa, pb = a["joints"]["J_Fit_Belly"], b["joints"]["J_Fit_Belly"]
        if units:
            pa, pb = [x / a["scale"] for x in pa], [x / b["scale"] for x in pb]
        belly = round(math.dist(pa, pb) * 1000, 2)
    return dict(joints=len(ds), rms_mm=round(rms, 3), most_mm=round(ds[-1][0], 3) if ds else None, worst=ds[-1][1] if ds else None, scale_ratio=round(b["scale"] / a["scale"], 5), belly_mm=belly)


whole, composed, control = load("whole"), load("composed"), load("control")
report = []
for key in sorted(whole):
    if key not in composed:
        continue
    r = dict(person=key[0], shot=key[1], composed=diff(whole[key], composed[key]), composed_file_units=diff(whole[key], composed[key], True))
    if key in control:
        r["control"] = diff(whole[key], control[key])
        r["control_file_units"] = diff(whole[key], control[key], True)
    r["sec_bones"] = dict(whole=sum(1 for c in whole[key]["joints"] if c.startswith("J_Sec")), composed=sum(1 for c in composed[key]["joints"] if c.startswith("J_Sec")))
    report.append(r)
    print(json.dumps(r))
json.dump(report, open(os.path.join(out, "fidelity.json"), "w"), indent=1)


# The shots side by side: whole, composed, control.
try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("compose_check: no pillow; stills not put side by side")
arms = ["whole", "composed", "control"]
os.makedirs(os.path.join(out, "stills"), exist_ok=True)
for p in people:
    shots = sorted(f for f in os.listdir(os.path.join(out, "whole", "recipe:town-" + p)) if f.endswith(".png"))
    w, h = 450, 600
    sheet = Image.new("RGB", (w * 3, h * len(shots) + 30), (24, 24, 24))
    dr = ImageDraw.Draw(sheet)
    for i, a in enumerate(arms):
        dr.text((i * w + 10, 8), f"{p}: {a}", fill=(255, 255, 255))
    for r, s in enumerate(shots):
        for i, a in enumerate(arms):
            f = os.path.join(out, a, "recipe:town-" + p + ("-same" if a == "control" else ""), s)
            if os.path.exists(f):
                sheet.paste(Image.open(f).convert("RGB").resize((w, h)), (i * w, 30 + r * h))
    sheet.save(os.path.join(out, "stills", f"{p}.jpg"), quality=88)
    print(os.path.join(out, "stills", f"{p}.jpg"))
