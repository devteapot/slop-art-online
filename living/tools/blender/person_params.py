#!/usr/bin/env python3
"""A person's parameters: what the character generator (person.py) is told. Plain Python.

    python3 living/tools/blender/person_params.py --seed 12                 # a seed's person, as JSON
    python3 living/tools/blender/person_params.py --seed 12 --set age=70 --set face.jaw_width=0.8
    python3 living/tools/blender/person_params.py --params halvard.json     # a file, filled in
    python3 living/tools/blender/person_params.py --doc                     # the reference tables (docs/CHARACTERS.md)

A person is a small JSON object. Every value is optional: `draw()` fills what is missing from
the seed, each value from its own random stream, so setting one value never changes another and
the same seed always gives the same person. `sex` and `age` are settled first, since most other
values are drawn round them. `family` is a second seed that relatives share: faces, skin and
hair colour are drawn partly from it, so a household looks related.

`resolve()` turns the filled-in parameters into the generator's numbers: the head's form
(head_form.py), the face's colours and line weights (head_mesh.py, face_paint.py), the body's
girth, the hair and the clothes, and the game recipe's height and proportions.
"""

import argparse
import copy
import json
import os
import random
import sys

sys.path.insert(1, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "characters"))
import face_types  # noqa: E402  (the face types and the identity rig: living/tools/characters/types.json)

# Cullet's palette (docs/SMALL_CITY.md §1, sRGB).
PAL = dict(
    basalt=(0.24, 0.25, 0.28), old_lime=(0.78, 0.77, 0.71), slate=(0.30, 0.34, 0.40), tar=(0.13, 0.12, 0.12),
    driftwood=(0.52, 0.50, 0.46), iron=(0.17, 0.17, 0.19), rust=(0.50, 0.27, 0.15), mustard=(0.78, 0.60, 0.18),
    sea_green=(0.22, 0.45, 0.42), oxblood=(0.45, 0.14, 0.13), kelp=(0.30, 0.28, 0.12), peat=(0.20, 0.15, 0.11),
    chalk_blue=(0.50, 0.62, 0.72), heather=(0.50, 0.34, 0.48),
)
# Cloth: a name, the two palette colours it lies between, and how far it may lie toward the second.
CLOTH = dict(
    oilskin=("mustard", "driftwood", 0.15, 0.45), tarred=("tar", "slate", 0.25, 0.50), olive=("kelp", "driftwood", 0.20, 0.50),
    canvas=("driftwood", "old_lime", 0.10, 0.40), blue=("slate", "chalk_blue", 0.20, 0.50), red=("oxblood", "peat", 0.20, 0.50),
    green=("sea_green", "slate", 0.20, 0.50), cream=("old_lime", "driftwood", 0.10, 0.35), navy=("iron", "slate", 0.30, 0.60),
    heather=("heather", "slate", 0.40, 0.70),
)
SKIN_TONES = [(0.96, 0.84, 0.77), (0.93, 0.78, 0.69), (0.88, 0.71, 0.61), (0.80, 0.61, 0.50), (0.66, 0.48, 0.37), (0.48, 0.34, 0.26), (0.34, 0.23, 0.18)]
HAIR_COLOURS = dict(
    black=(0.075, 0.065, 0.065), dark_brown=(0.125, 0.095, 0.08), brown=(0.20, 0.135, 0.09), chestnut=(0.29, 0.17, 0.10), auburn=(0.40, 0.18, 0.10),
    sandy=(0.48, 0.34, 0.19), blond=(0.62, 0.49, 0.28), grey=(0.52, 0.52, 0.52), white=(0.78, 0.78, 0.76),
)
EYE_COLOURS = dict(
    blue=(0.30, 0.47, 0.62), grey=(0.42, 0.50, 0.54), green=(0.33, 0.48, 0.33), hazel=(0.47, 0.40, 0.20), amber=(0.60, 0.40, 0.14),
    brown=(0.36, 0.23, 0.13), dark_brown=(0.21, 0.14, 0.10),
)
# How drawn the whole town's faces are (docs/CHARACTERS.md, "Style"): 0 keeps the proportions of
# life that pass 1 had, 1 is the VRoid control's drawing (eyes low on the head and tall, a short
# fine lower face, a small nose and mouth, a larger head). Grown men and the old take less of it.
# One number for everyone; `stylise` in a person's parameters overrides it for that person.
STYLE = dict(
    toward=0.70,      # how far every face leans toward the control's proportions
    men=0.66,         # the share of it a grown man's face takes
    elders=0.85,      # and an old face
    head=0.085,       # how much larger the head is at 1 (on top of 1.08)
    lash=0.55,        # how much heavier the lash line is at 1
    lash_colour=(0.24, 0.10, 0.09),  # the lashes' warm dark brown, as the control's
)

HAIR_STYLES = ("crop", "short", "tousled", "swept", "shag", "bob", "bob_parted", "long", "tail", "bun", "braid", "braids", "sides", "kerchief", "balding")  # hair.py STYLES
# How far each style's hair hangs below the hairline at the sides, in metres, as drawn from a
# seed (`hair.length`); for the short styles it scales the hairs' own length round 0.07.
HAIR_LENGTHS = dict(shag=(0.025, 0.06), bob=(0.05, 0.11), bob_parted=(0.06, 0.12), long=(0.20, 0.36), tail=(0.10, 0.28), braid=(0.08, 0.22), braids=(0.06, 0.16), bun=(0.05, 0.11))
BEARD_STYLES = ("none", "stubble", "moustache", "goatee", "chinstrap", "short", "full")
COATS = ("coat", "smock", "none")
HEADWEAR = ("none", "cap", "kerchief")

# The face: each value runs about -1 to 1 round the average for the person's sex and age.
FACE = [
    ("face_length", "short lower face", "long lower face"),
    ("face_width", "narrow", "wide"),
    ("forehead", "low, sloping", "high, full"),
    ("cheekbones", "narrow, soft", "wide, set"),
    ("cheeks", "hollow", "full"),
    ("jaw_width", "narrow jaw", "wide jaw"),
    ("jaw_square", "tapered jaw", "square jaw"),
    ("chin_length", "short chin", "long chin"),
    ("chin_width", "pointed chin", "broad chin"),
    ("chin_forward", "receding chin", "jutting chin"),
    ("brow_ridge", "smooth brow bone", "heavy brow bone"),
    ("eye_size", "small eyes", "large eyes"),
    ("eye_spacing", "close-set", "wide-set"),
    ("eye_height", "eyes low on the face", "eyes high"),
    ("eye_open", "narrow", "round, open"),
    ("eye_tilt", "outer corners down", "outer corners up"),
    ("eye_shape", "lid peaks toward the nose", "lid peaks outward"),
    ("iris_size", "small iris", "large iris"),
    ("eye_fold", "no lid fold", "deep lid fold"),
    ("brow_thickness", "thin brows", "heavy brows"),
    ("brow_height", "low brows", "high brows"),
    ("brow_tilt", "inner ends high (mild)", "inner ends low (stern)"),
    ("brow_arch", "straight brows", "arched brows"),
    ("brow_length", "short brows", "long brows"),
    ("nose_length", "short nose", "long nose"),
    ("nose_width", "narrow nose", "broad nose"),
    ("nose_bridge", "low, scooped bridge", "high, arched bridge"),
    ("nose_tip", "tip turned down", "tip turned up"),
    ("mouth_width", "small mouth", "wide mouth"),
    ("mouth_height", "mouth close under the nose", "mouth low"),
    ("lip_fullness", "thin lips", "full lips"),
    ("mouth_curve", "corners down", "corners up"),
    ("ear_size", "small ears", "large ears"),
    ("ear_out", "ears flat to the head", "ears standing out"),
]
FACE_KEYS = [k for k, _, _ in FACE]

# Presets: named people (person.py --variant).
PRESETS = {
    "man": dict(type="adult-m-b", identity=dict(), seed=3, sex="male", age=36, build=dict(height=1.80, weight=0.1, muscle=0.4), beard=dict(style="full"), hair=dict(style="tousled", colour="dark_brown"),
                eyes=dict(colour="blue"), skin=dict(tone=0.30), outfit=dict(coat="coat", coat_colour="oilskin", jersey_colour="green", headwear="none")),
    "woman": dict(type="adult-f-b", identity=dict(), seed=8, sex="female", age=29, build=dict(height=1.66), hair=dict(style="long", colour="chestnut", length=0.30, parting=0.0, fringe=0.95, fringe_style="straight", volume=0.55, curl=0.1), eyes=dict(colour="green"), skin=dict(tone=0.22),
                  outfit=dict(coat="smock", coat_colour="blue", jersey_colour="cream", headwear="none", apron=True)),
    "elder": dict(type="elder-m-b", identity=dict(), seed=5, sex="male", age=70, build=dict(height=1.72), beard=dict(style="short"), hair=dict(style="sides"), eyes=dict(colour="grey"), skin=dict(tone=0.30),
                  outfit=dict(coat="coat", coat_colour="tarred", jersey_colour="red", headwear="cap")),
    "youth": dict(type="youth-m-b", identity=dict(), seed=11, sex="male", age=15, hair=dict(style="tousled", colour="sandy"), outfit=dict(coat="none", jersey_colour="cream", headwear="none")),
    "heavy": dict(type="adult-m-a", identity=dict(), seed=31, sex="male", age=44, build=dict(height=1.88, weight=0.9, muscle=0.6), beard=dict(style="short"), hair=dict(style="short", colour="auburn"), skin=dict(tone=0.45),
                  outfit=dict(coat="smock", coat_colour="canvas", jersey_colour="navy", headwear="none")),
    "boy": dict(type="child-u-b", identity=dict(), seed=21, sex="male", age=8, hair=dict(style="tousled", colour="chestnut"), outfit=dict(coat="none", jersey_colour="blue")),
    "girl": dict(type="child-u-a", identity=dict(), seed=22, sex="female", age=6, hair=dict(style="bob", colour="brown"), outfit=dict(coat="smock", coat_colour="red", apron=False)),
}
KINDS = dict(man=("male", 19, 58), woman=("female", 19, 58), elder_man=("male", 62, 76), elder_woman=("female", 62, 76), boy=("male", 4, 15), girl=("female", 4, 15))


def rnd(seed, name):
    return random.Random(f"{seed}/{name}")


def clip(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def smooth(x):
    x = clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def table(rows, x):
    if x <= rows[0][0]:
        return rows[0][1]
    for (xa, a), (xb, b) in zip(rows, rows[1:]):
        if x <= xb:
            return a + (b - a) * (x - xa) / (xb - xa)
    return rows[-1][1]


def deep_update(base, extra):
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def child_height(age, male):
    rows = [(1, 0.76), (2, 0.87), (4, 1.03), (6, 1.16), (8, 1.28), (10, 1.39), (12, 1.50), (14, 1.62 if male else 1.59), (16, 1.72 if male else 1.63), (18, 1.77 if male else 1.64)]
    return table(rows, age)


def draw(given=None):
    """Fill in a person's parameters. `given` holds any values already decided (at least a seed,
    or nothing for seed 0); the result has every value."""
    given = copy.deepcopy(given or {})
    seed = given.get("seed", 0)
    fam = given.get("family")
    u = lambda name, lo, hi: rnd(seed, name).uniform(lo, hi)
    n = lambda name, sd=0.5: clip(rnd(seed, name).gauss(0, sd))
    pick = lambda name, options, weights=None: rnd(seed, name).choices(list(options), weights=weights)[0]
    p = dict(seed=seed)
    if fam is not None:
        p["family"] = fam
    p["sex"] = given.get("sex") or pick("sex", ("male", "female"))
    male = p["sex"] == "male"
    # Cullet: 14 children, 44 adults and 6 elders in 64 (docs/SMALL_CITY.md §3).
    age = given.get("age")
    if age is None:
        band = pick("age.band", ("child", "adult", "elder"), (14, 44, 6))
        age = dict(child=u("age", 2, 16), adult=u("age", 18, 59), elder=u("age", 62, 78))[band]
    p["age"] = round(float(age), 1)
    age = p["age"]
    child, old = age < 16, age >= 60
    grown = smooth((age - 10) / 8)
    # Build.
    h = child_height(age, male) + rnd(seed, "build.height").gauss(0, 0.055 if age >= 18 else 0.03) - 0.03 * smooth((age - 55) / 20)
    lo_h, hi_h = (0.70, 1.95) if age < 18 else ((1.60, 1.94) if male else (1.50, 1.78))
    p["build"] = dict(height=round(clip(h, lo_h, hi_h), 2), weight=round(n("build.weight", 0.45), 2), muscle=round(clip(n("build.muscle", 0.4) + (0.15 if male else -0.1) * grown), 2))
    # The face: partly the family's, mostly the person's own.
    face = {}
    for k in FACE_KEYS:
        own = rnd(seed, f"face.{k}").gauss(0, 0.52)
        if fam is not None:
            own = 0.62 * own + 0.62 * rnd(f"family{fam}", f"face.{k}").gauss(0, 0.52)
        face[k] = round(clip(own), 2)
    p["face"] = face
    src = f"family{fam}" if fam is not None else seed
    tone = clip(rnd(src, "skin.tone").betavariate(1.6, 4.2) + (rnd(seed, "skin.tone.own").gauss(0, 0.04) if fam is not None else 0), 0.0, 1.0)
    fr = rnd(seed, "skin.freckles").random()
    p["skin"] = dict(tone=round(tone, 2), freckles=round(clip((fr - 0.72) / 0.28, 0, 1) * (1 - tone) * (1.2 if child else 1.0), 2), weathered=round(clip(u("skin.weathered", 0.0, 0.7) * grown + 0.3 * smooth((age - 40) / 30), 0, 1), 2))
    dark = tone > 0.55
    p["eyes"] = dict(colour=rnd(src if rnd(seed, "eyes.own").random() < 0.6 else seed, "eyes.colour").choices(list(EYE_COLOURS), weights=(1, 1, 1, 1, 0.5, 5, 6) if dark else (5, 3, 3, 3, 1, 4, 2))[0])
    # Hair.
    # The weights do not depend on age: a seed keeps its hair colour as it grows up. (Until pass
    # 3 a child's draw gave blond twice the weight, which moved every colour's share, so the same
    # seed could change hair colour on turning 16.)
    natural = rnd(src if rnd(seed, "hair.own").random() < 0.7 else seed, "hair.colour").choices(
        ("black", "dark_brown", "brown", "chestnut", "auburn", "sandy", "blond"), weights=(6, 5, 2, 1, 0.3, 0.1, 0.05) if dark else (2, 5, 5, 3, 2, 3, 2))[0]
    grey = clip(smooth((age - 36) / 34) + rnd(seed, "hair.grey").gauss(0, 0.16) * smooth((age - 30) / 15), 0, 1)
    recede = clip(u("hair.recede", 0.0, 1.0) ** 1.5 * smooth((age - 24) / 40) * 1.3 if male else 0.0, 0, 1)
    if child:
        style = pick("hair.style", ("tousled", "short", "crop", "shag", "bob") if male else ("bob", "bob_parted", "braids", "tail", "long", "tousled"), (4, 3, 2, 1.5, 1) if male else (4, 2, 4, 3, 2, 1))
    elif male:
        style = pick("hair.style", ("tousled", "short", "crop", "swept", "shag", "tail"), (2, 3, 3, 3, 1, 0.3) if old else (4, 4, 3, 3, 2, 0.5))
        if recede > 0.72:
            style = "balding"
    else:
        style = pick("hair.style", ("kerchief", "bob", "bob_parted", "long", "tail", "bun", "braid"), (4, 1, 0.5, 0.5, 0.5, 4, 1.5) if old else (2, 2, 2, 3, 3, 3, 3))
    # A style that is given takes its own lengths (a shared style's file names its style and
    # draws the rest; until the sheets step its length came from the style its seed would have
    # picked, so `long` came out at the jaw and `bob` at the shoulders).
    style = (given.get("hair") or {}).get("style", style)
    lo_l, hi_l = HAIR_LENGTHS.get(style, (0.05, 0.09))
    p["hair"] = dict(style=style, colour=natural, grey=round(grey, 2), length=round(u("hair.length", lo_l, hi_l), 3), parting=round(clip(rnd(seed, "hair.parting").gauss(0, 0.5)), 2),
                     fringe=round(u("hair.fringe", 0.3, 0.9) if male and not child else u("hair.fringe", 0.5, 1.05), 2), volume=round(u("hair.volume", 0.25, 0.85), 2),
                     curl=round(clip(rnd(seed, "hair.curl").betavariate(1.2, 4.5), 0, 1), 2), recede=round(recede, 2))
    # Beard (men).
    if male and age >= 17:
        bs = pick("beard.style", BEARD_STYLES, (30, 22, 7, 7, 3, 14, 17) if not old else (14, 14, 8, 6, 4, 22, 32))
        if age < 23 and bs in ("short", "full"):
            bs = "stubble"
    else:
        bs = "none"
    p["beard"] = dict(style=bs, stubble=round(u("beard.stubble", 0.25, 1.0) if bs == "stubble" else (u("beard.stubble", 0.0, 0.45) if male and age >= 17 else 0.0), 2))
    # Clothes, in Cullet's cloth.
    if child:
        coat = pick("outfit.coat", COATS, (0, 3, 6) if male else (0, 9, 1))
        head = "none"
    elif male:
        coat = pick("outfit.coat", COATS, (5, 3, 2))
        head = "cap" if rnd(seed, "outfit.headwear").random() < (0.45 if old else 0.15) else "none"
    else:
        coat = pick("outfit.coat", COATS, (2, 8, 0))
        head = "kerchief" if style == "kerchief" else "none"
    p["outfit"] = dict(
        coat=coat, coat_colour=pick("outfit.coat_colour", ("oilskin", "oilskin", "tarred", "olive", "canvas", "navy") if male else ("blue", "red", "heather", "green", "canvas", "tarred")),
        jersey_colour=pick("outfit.jersey_colour", ("green", "cream", "blue", "red", "navy", "olive")), headwear=head,
        headwear_colour=pick("outfit.headwear_colour", ("tarred", "olive", "navy", "canvas") if male else ("red", "blue", "cream", "heather", "green")),
        apron=bool(not male and rnd(seed, "outfit.apron").random() < (0.5 if child else 0.7)),
        hem=0.74 if male else (0.58 if child else pick("outfit.hem", (0.50, 0.50, 0.58))),
    )
    # The face: a type for the person's sex and age band on their family's line, and values
    # bounded by their distance from it (face_types; docs/CHARACTERS.md, "Types and rig"). The
    # 34 values above are pass 2's and make the head only with `head: "loft"`.
    p["head"] = given.get("head", "cage")
    p["type"] = given.get("type") or face_types.type_for(seed, p["sex"], age, fam)
    if given.get("identity") is None:
        p["identity"] = face_types.draw_valid(face_types.load()["types"][p["type"]], seed, fam)
    deep_update(p, {k: v for k, v in given.items() if k not in ("seed", "family")})
    # A style that needs its headwear, and the other way round.
    if p["hair"]["style"] == "kerchief":
        p["outfit"]["headwear"] = "kerchief"
    if p["outfit"]["headwear"] == "cap" and p["hair"]["style"] not in ("sides", "crop", "short", "balding", "tail"):
        p["hair"]["style"] = "sides"
    if p["outfit"]["headwear"] == "kerchief":
        p["hair"]["style"] = "kerchief"
    return p


def colour(value, table_, what):
    if isinstance(value, (list, tuple)):
        return tuple(float(c) for c in value)
    if value not in table_:
        raise SystemExit(f"{what}: {value!r} is not one of {sorted(table_)} or an [r, g, b] list")
    return table_[value]


def cloth(seed, name, value):
    """A cloth colour: a CLOTH name (its exact shade drawn from the seed) or an [r, g, b] list."""
    if isinstance(value, (list, tuple)):
        return tuple(float(c) for c in value)
    if value not in CLOTH:
        raise SystemExit(f"{name}: {value!r} is not one of {sorted(CLOTH)} or an [r, g, b] list")
    a, b, lo, hi = CLOTH[value]
    return mix(PAL[a], PAL[b], rnd(seed, f"cloth.{name}").uniform(lo, hi))


def resolve(p):
    """The generator's numbers for a filled-in person (see `draw`)."""
    seed, age, male = p["seed"], p["age"], p["sex"] == "male"
    b, face, skin_p, hair_p, beard_p, outfit = p["build"], dict(p["face"]), p["skin"], p["hair"], p["beard"], p["outfit"]
    child = smooth((16.5 - age) / 12.5)
    elder = smooth((age - 46) / 26)
    teen = smooth((age - 11) / 7)  # 0 a child, 1 grown
    masc = 1.0 if male else 0.0
    drawn = clip(float(p.get("stylise", STYLE["toward"])), 0.0, 1.2) * (1 - (1 - STYLE["men"]) * masc * teen) * (1 - (1 - STYLE["elders"]) * elder)
    w, mus = b["weight"], b["muscle"]
    # A heavier person has a fuller face; a lean one a harder one.
    face["cheeks"] = clip(face.get("cheeks", 0) + 0.55 * w, -1.4, 1.4)
    face["jaw_width"] = clip(face.get("jaw_width", 0) + 0.30 * w + 0.15 * mus, -1.3, 1.3)
    face["face_width"] = clip(face.get("face_width", 0) + 0.25 * w, -1.3, 1.3)
    # Skin.
    tone = clip(skin_p["tone"], 0, 1) * (len(SKIN_TONES) - 1)
    i = min(int(tone), len(SKIN_TONES) - 2)
    skin = mix(SKIN_TONES[i], SKIN_TONES[i + 1], tone - i)
    weather = skin_p.get("weathered", 0.0)
    skin = mix(skin, (skin[0] * 0.95, skin[1] * 0.84, skin[2] * 0.78), 0.4 * weather)  # ruddier and deeper
    shade = (skin[0] * 0.82, skin[1] * 0.69, skin[2] * 0.67)
    warm = mix(skin, (0.84, 0.36, 0.32), 0.50)
    line = (shade[0] * 0.74, shade[1] * 0.64, shade[2] * 0.64)
    lip = mix(skin, (0.74, 0.30, 0.30) if skin_p["tone"] < 0.6 else (0.50, 0.22, 0.22), 0.62)
    # Hair.
    natural = colour(hair_p["colour"], HAIR_COLOURS, "hair.colour")
    grey = clip(hair_p.get("grey", 0.0), 0, 1)
    silver = mix(HAIR_COLOURS["grey"], HAIR_COLOURS["white"], smooth((grey - 0.5) / 0.5))
    hair = mix(natural, silver, smooth(grey / 0.85))
    hair_tip = mix(hair, (0.94, 0.88, 0.76), 0.16)
    natural_tip = mix(natural, (0.94, 0.88, 0.76), 0.14)
    beard_c = mix(natural, silver, smooth(min(grey * 1.25, 1.0) / 0.85))
    brow = mix(mix(natural, silver, 0.6 * smooth(grey / 0.9)), (0.05, 0.04, 0.04), 0.25 if sum(natural) > 0.6 else 0.0)
    # Lines and lashes.
    fem = (1 - masc) * teen
    lash = mix(mix((0.10, 0.075, 0.07), STYLE["lash_colour"], min(drawn, 1.0)), natural, 0.25 if sum(natural) > 0.7 else 0.0)
    style = beard_p.get("style", "none")
    if style not in BEARD_STYLES:
        raise SystemExit(f"beard.style: {style!r} is not one of {BEARD_STYLES}")
    stubble = clip(beard_p.get("stubble", 0.0), 0, 1) * masc * teen
    look = dict(
        seed=seed, skin=skin, skin_shade=shade, skin_warm=warm, skin_line=line, skin_rim=(0.86, 0.78, 0.78), lip=lip,
        lip_tint=clip(0.40 + 0.40 * fem + 0.08 * child - 0.10 * elder, 0, 1), mouth_line=(0.36, 0.16, 0.15) if skin_p["tone"] < 0.6 else (0.20, 0.09, 0.09),
        blush=clip(0.20 + 0.14 * fem + 0.22 * child + 0.16 * weather, 0, 0.6), lines=clip(((age - 30) / 40), 0, 1.25) ** 1.25 * 1.15 + 0.20 * weather * (1 - child),
        freckles=skin_p.get("freckles", 0.0), nostril=clip(0.35 + 0.35 * masc * teen + 0.3 * elder - 0.3 * child, 0, 1), nose_line=clip(0.55 + 0.45 * masc * teen + 0.3 * elder - 0.3 * child, 0, 1.3),
        stubble=stubble, stubble_colour=mix(mix(skin, beard_c, 0.55), (0.35, 0.38, 0.42), 0.25), beard=style if masc else "none", beard_colour=beard_c, beard_density=1.0,
        hair=hair, hair_tip=hair_tip, hair_natural=natural, hair_natural_tip=natural_tip, hair_silver=silver, hair_grey=grey, brow=brow, lash=lash, lash_tip=mix(lash, (0.42, 0.20, 0.14), 0.6),
        lash_k=(0.66 + 0.74 * fem + 0.34 * child * (1 - masc) + 0.12 * child) * (1 + STYLE["lash"] * drawn), lash_wing=0.14 + 0.22 * fem + 0.06 * child, wing_lift=0.10 + 0.22 * fem,
        lashes=int(round(9 * fem + 5 * child * (1 - masc) + 2 * child * masc)), lashes_low=int(round(4 * fem + 2 * child * (1 - masc))),
        brow_hairs=int(round(22 + 8 * masc * teen + 4 * elder)), fold=clip(0.65 + 0.5 * face.get("eye_fold", 0) + 0.35 * elder, 0, 1.6),
        lower=clip(0.35 + 0.45 * fem + 0.2 * child, 0, 1), iris=colour(p["eyes"]["colour"], EYE_COLOURS, "eyes.colour"),
        white_shade=mix((0.62, 0.60, 0.68), shade, 0.25),
    )
    # Body: girth from weight and muscle; the recipe carries height and a child's proportions.
    girth = 1.02 + 0.12 * w + 0.03 * mus - 0.03 * child
    limb = (1.0 if male else 0.86) * (1 + 0.09 * w + 0.08 * mus) * (1 - 0.06 * child)
    belly = 0.30 * max(w, 0.0) ** 1.3 + 0.05 * elder * (1 + w) + 0.04 * child
    chest = 0.06 * max(mus, 0.0) * teen
    t = age
    prop = dict(
        legs=table([(1, 0.66), (4, 0.78), (15, 0.98), (18, 1.0)], t), arms=table([(1, 0.76), (4, 0.84), (15, 0.98), (18, 1.0)], t), torso=table([(1, 0.86), (4, 0.90), (15, 1.0)], t),
        neck=table([(1, 0.60), (4, 0.70), (15, 0.95), (18, 1.0)], t), head=table([(1, 1.60), (4, 1.42), (15, 1.08), (18, 1.0)], t), shoulders=table([(1, 0.78), (4, 0.82), (15, 0.94), (18, 1.0)], t),
        build=table([(1, 1.02), (4, 0.96), (15, 0.92), (18, 1.0)], t),
    )
    prop["shoulders"] *= (1.0 if male else 1.0 - 0.10 * teen) * (1 + 0.035 * mus + 0.015 * w) * (1 - 0.04 * elder)
    prop["build"] *= 1 + 0.07 * w + 0.04 * mus
    prop["neck"] *= 1 - 0.05 * elder
    if not male and age >= 12:
        prop.update(hands=0.88, feet=0.90)
    recipe = dict(height=b["height"], proportions={k: round(v, 3) for k, v in prop.items() if abs(v - 1) > 0.004})
    for name, options in (("hair.style", HAIR_STYLES), ("outfit.coat", COATS), ("outfit.headwear", HEADWEAR)):
        a, k = name.split(".")
        if p[a][k] not in options:
            raise SystemExit(f"{name}: {p[a][k]!r} is not one of {options}")
    typed = p.get("head", "cage") == "cage" and p.get("type")
    if typed:
        # Height changes the head's proportion and not only the scale (face_types.head_scale).
        body = face_types.load()["types"][p["type"]]["body"]
        recipe["proportions"]["head"] = round(recipe["proportions"].get("head", 1.0) * face_types.head_scale(body, b["height"]) / face_types.head_scale(body, child_height(age, male) if age < 18 else body["height_m"][1]), 3)
    spec = dict(
        type=p["type"] if typed else None, identity=dict(p.get("identity") or {}),
        seed=seed, masc=masc, child=child, elder=elder, face=face, look=look, style=drawn, head_scale=1.08 * (1 + STYLE["head"] * drawn), girth=girth, limb=limb, belly=belly, chest=chest, woman_torso=bool(not male and age >= 13),
        hair_style=hair_p["style"], hair_length=hair_p.get("length", 0.07), recede=0.024 * clip(hair_p.get("recede", 0.0), 0, 1),
        hair=dict(style=hair_p["style"], length=float(hair_p.get("length", 0.07)), parting=float(hair_p.get("parting", 0.0)), fringe=float(hair_p.get("fringe", 0.7)), volume=float(hair_p.get("volume", 0.5)),
                  curl=float(hair_p.get("curl", 0.0)), fringe_style=hair_p.get("fringe_style", "auto")),
        bald=smooth((clip(hair_p.get("recede", 0.0), 0, 1) - 0.55) / 0.40) if hair_p["style"] == "balding" else 0.0,
        beard=style if male else "none", coat=None if outfit["coat"] == "none" else outfit["coat"], headwear=None if outfit["headwear"] == "none" else outfit["headwear"],
        coat_colour=cloth(seed, "coat", outfit["coat_colour"]), jersey=cloth(seed, "jersey", outfit["jersey_colour"]), headwear_colour=cloth(seed, "headwear", outfit["headwear_colour"]),
        patches=(cloth(seed, "patch1", "canvas"), cloth(seed, "patch2", "olive"), cloth(seed, "patch3", "red")), apron=bool(outfit.get("apron", False)), hem=float(outfit.get("hem", 0.74)),
        recipe=recipe,
    )
    if typed:
        spec["person"] = person_line(spec, recipe, male)
    return spec


def hexed(c):
    return "#" + "".join(f"{round(min(max(x, 0.0), 1.0) * 255):02x}" for x in c[:3])


def person_line(spec, recipe, male):
    """A person as the client composes one from shared files (docs/CHARACTERS.md, "The client
    format"): a type, identity values, the style files worn, colours, and proportions. The
    proportions differ from the per-person file's recipe in one number: `build` also carries the
    girth the per-person file builds into its own meshes, because a shared piece is built at the
    standard build and the bones give it this person's (the mean of the torso's and the limbs'
    girth, each against the standard for the person's form), and `shoulders` is divided by the
    same, so the girth does not also move the arms out."""
    hair, pieces, head = worn(spec)
    g = ((spec["girth"] / 1.02) * (spec["limb"] / (1.0 if male else 0.86))) ** 0.5
    props = dict(recipe["proportions"])
    props["build"] = round(props.get("build", 1.0) * g, 3)
    # The client widens the upper chest by build x shoulders and hangs the arms from it. A person's
    # own file put its girth on below the shoulders only, so the shoulders give the girth back.
    props["shoulders"] = round(props.get("shoulders", 1.0) / g, 3)
    look = spec["look"]
    # One colour for the hair: the natural colour gone as grey as this person's is (a per-person
    # file greys lock by lock; a shared style takes one tint). The beard has its own.
    grey = min(max(float(look.get("hair_grey", 0.0)), 0.0), 1.0)
    colours = dict(skin=hexed(look["skin"]), hair=hexed(mix(look["hair_natural"], look["hair_silver"], grey)), beard=hexed(look["beard_colour"]))
    cloth_ = {}
    for name in pieces + head:
        base = name[:-2] if name[-2:] in ("-m", "-f") else name
        if base.split("_")[0] in PIECE_COLOURS:
            cloth_[name] = PIECE_COLOURS[base.split("_")[0]]
            continue
        tone = spec["patches"][0] if base == "smock_bands" else (spec["jersey"] if base.startswith("jersey") else (spec["headwear_colour"] if base in HEAD_PIECES else (spec["coat_colour"] if base.startswith(("coat", "smock")) else None)))
        if isinstance(tone, (tuple, list)) and len(tone) >= 3 and all(isinstance(x, (int, float)) for x in tone[:3]):
            cloth_[name] = hexed(tone)
    colours["outfit"] = cloth_
    if isinstance(look.get("iris"), (tuple, list)):
        colours["eyes"] = hexed(look["iris"])
    # The details worn as overlay styles, by the same thresholds a glance would use.
    over = []
    if spec["beard"] in BEARD_FORMS:
        over.append(f"beard_{spec['beard']}")
    if spec["beard"] == "stubble" or look.get("stubble", 0.0) > 0.2:
        over.append("stubble")
    if look.get("lines", 0.0) > 0.2:
        over.append("lines")
    if look.get("freckles", 0.0) > 0.1:
        over.append("freckles")
    types = face_types.load()["types"]
    over = [o for o in over if spec["type"] in overlay_types(o, types)]
    line = dict(type=spec["type"], height=recipe["height"], proportions={k: v for k, v in props.items() if abs(v - 1) > 0.004}, identity={k: v for k, v in spec["identity"].items() if abs(v) > 1e-6}, colors=colours,
                styles=dict(hair=hair, outfit=pieces + head, overlays=over))
    if spec["belly"] > 0.02:
        line["belly"] = round(spec["belly"], 3)
    return line


def from_type(tid):
    """The figure a face type's own file is built on (`type:<id>`): the type with every identity
    value at 0, at the usual age, height and build of its band, with nothing a person adds (no
    freckles, stubble or weathering). A type for either sex takes line b's as male, a and c's as
    female; children's builds do not differ."""
    types = face_types.load()["types"]
    if tid not in types:
        raise SystemExit(f"type {tid!r}: not one of {sorted(types)}")
    t = types[tid]
    sex = t["sex"] if t["sex"] in ("male", "female") else ("male" if t["line"] == "b" else "female")
    body = t["body"]
    return dict(type=tid, identity=dict(), seed=1000 + sorted(types).index(tid), sex=sex, age=dict(child=8, youth=15, adult=32, elder=68)[t["band"]],
                build=dict(height=body["height_m"][1], weight=0.0, muscle=0.0), skin=dict(tone=0.25, freckles=0.0, weathered=0.0), beard=dict(style="none", stubble=0.0))


STYLES = ("tousled", "short", "crop", "shag", "swept", "sides", "balding", "bob", "bob_parted", "braids", "tail", "long", "bun", "braid", "kerchief")
CAPPED = ("tousled", "short", "crop", "shag", "swept", "sides", "balding")  # the styles also written as worn under a cap (`<style>.cap`)
CUTS = 3  # how many cuts of each style are written: `<style>`, `<style>.2`, `<style>.3`, each with its own length, parting, fringe and volume
STYLE_HEAD = "adult-f-b"  # the head every shared hair style is built on; a type's file carries its fit onto that type (hair_fit.py)


def from_style(style):
    """The figure a shared hair style's file is built on (`style:<name>`): the standard head with
    every identity value at 0, and the style at the lengths and parting its own seed draws."""
    parts = style.split(".")
    style, under, cut = parts[0], ("cap" if parts[-1] == "cap" else ""), next((int(x) for x in parts[1:] if x.isdigit()), 1)
    if style not in STYLES or (under and style not in CAPPED) or not 1 <= cut <= CUTS or len(parts) > 1 + bool(under) + (cut > 1):
        raise SystemExit(f"style {'.'.join(parts)!r}: one of {STYLES}, with `.2` to `.{CUTS}` for another cut and `.cap` for {CAPPED} under a cap")
    male = style in ("short", "crop", "swept", "sides", "shag", "tousled", "balding")
    # Another cut is the same style from another seed: the generator draws its length, parting,
    # fringe, volume and curl from it, as it did for each person.
    hair = dict(style=style)
    if style == "balding":
        # The crown is bald by how far the hairline has receded, and at the standard figure's age
        # a seed draws almost none: until the sheets step this style's file had a full head of hair.
        hair["recede"] = (0.85, 1.0, 0.74)[cut - 1]
    return dict(type=STYLE_HEAD, identity=dict(), seed=2000 + STYLES.index(style) + 100 * (cut - 1), sex="male" if male else "female", age=30, hair=hair, beard=dict(style="none", stubble=0.0),
                build=dict(weight=0.0, muscle=0.0), outfit=dict(headwear="kerchief" if style == "kerchief" else (under or "none")))


# Outfit pieces as shared style files (gen_styles.sh): the outfit that makes each, and the parts of
# it the file keeps. A piece worn on the body comes in two forms, `-m` and `-f` (a woman's torso
# and limbs are built differently); a piece worn on the head is fitted like hair.
PIECES = dict(
    jersey=(dict(coat="none"), ("Jersey",)), jersey_coat=(dict(coat="coat"), ("Jersey",)), jersey_smock=(dict(coat="smock", hem=0.58), ("Jersey",)),
    coat=(dict(coat="coat"), ("Coat", "Buttons")), trousers=(dict(coat="none"), ("Trousers",)), boots=(dict(coat="none"), ("Boots",)),
    **{f"smock_{round(h * 100)}": (dict(coat="smock", hem=h, apron=False), ("Smock",)) for h in (0.50, 0.58, 0.74)},
    **{f"apron_{round(h * 100)}": (dict(coat="smock", hem=h, apron=True), ("Apron",)) for h in (0.50, 0.58, 0.74)},
    smock_bands=(dict(coat="smock", hem=0.58, apron=False), ("SmockBands",)),  # the bands round a smock's sleeves, the same on every length
)
# The colour of a piece that a person does not choose: every resident's trousers, boots and apron
# are the same cloth. A shared piece is grey shading round one mean (shade_mean.py), so a person's
# line names a colour for every piece worn; these are what the pieces were built in.
PIECE_COLOURS = dict(trousers="#353840", boots="#332820", apron="#b4b1a3")
# Details a person has and a type does not, as overlay styles (gen_styles.sh): each is built on a
# type's own face, for the types that can wear it.
BEARD_FORMS = ("moustache", "goatee", "chinstrap", "short", "full")
OVERLAYS = tuple(f"beard_{b}" for b in BEARD_FORMS) + ("stubble", "lines", "freckles")


def overlay_types(name, types):
    """The face types an overlay style is written for: beards and stubble for men past boyhood,
    age lines for adults and elders, freckles for everyone."""
    if name.startswith("beard") or name == "stubble":
        return [t for t, v in types.items() if v["sex"] == "male" and v["band"] in ("adult", "elder")] + ([t for t, v in types.items() if v["sex"] == "male" and v["band"] == "youth"] if name == "stubble" else [])
    if name == "lines":
        return [t for t, v in types.items() if v["band"] in ("adult", "elder")]
    return list(types)


def from_overlay(spec):
    """The figure an overlay style's file is built on (`overlay:<type>:<name>`): the type's own
    figure with that one detail, at a set strength."""
    tid, name = spec.split(":")
    if name not in OVERLAYS:
        raise SystemExit(f"overlay {name!r}: not one of {OVERLAYS}")
    given = from_type(tid)
    if name.startswith("beard"):
        given["beard"] = dict(style=name[6:], stubble=0.0)
    elif name == "stubble":
        given["beard"] = dict(style="stubble", stubble=0.8)
    elif name == "freckles":
        given["skin"] = dict(given["skin"], freckles=0.7)
    else:
        given.update(age=max(given["age"], 66), skin=dict(given["skin"], weathered=0.6))
    return given
HEAD_PIECES = dict(cap=(dict(headwear="cap"), ("Cap", "CapPeak")), kerchief=(dict(headwear="kerchief"), ("Kerchief", "KerchiefKnot")))


def piece_parts(name):
    base = name[:-2] if name[-2:] in ("-m", "-f") else name
    return (PIECES.get(base) or HEAD_PIECES[base])[1]


def from_piece(name):
    """The figure an outfit piece's file is built on (`piece:<name>`): the standard head and the
    standard build (weight and muscle 0), a man's body for `-m` and a woman's for `-f`."""
    base, form = (name[:-2], name[-1]) if name[-2:] in ("-m", "-f") else (name, "m")
    if (base in PIECES) == (base in HEAD_PIECES) or (base in HEAD_PIECES and name != base):
        raise SystemExit(f"piece {name!r}: not one of {sorted(PIECES)} with -m or -f, or {sorted(HEAD_PIECES)}")
    outfit = dict(coat_colour="oilskin" if form == "m" else "blue", jersey_colour="cream", headwear="none", apron=False)
    outfit.update((PIECES.get(base) or HEAD_PIECES[base])[0])
    return dict(type=STYLE_HEAD, identity=dict(), seed=2500, sex="male" if form == "m" else "female", age=30, build=dict(weight=0.0, muscle=0.0), hair=dict(style="kerchief" if base == "kerchief" else "short"),
                beard=dict(style="none", stubble=0.0), outfit=outfit)


def worn(spec):
    """The shared style files a resolved person wears: (hair style, outfit pieces, head pieces)."""
    form = "f" if spec["woman_torso"] else "m"
    coat, head = spec["coat"], spec["headwear"]
    if coat == "coat":
        top = [f"coat-{form}", f"jersey_coat-{form}"]
    elif coat == "smock":
        hem = int(round(max(spec["hem"], 0.50) * 100))
        top = [f"smock_{hem}-{form}", f"smock_bands-{form}", f"jersey_smock-{form}"] + ([f"apron_{hem}-{form}"] if spec["apron"] else [])
    else:
        top = [f"jersey-{form}"]
    style = spec["hair"]["style"]
    cut = spec["seed"] % CUTS + 1  # which cut of the style this person wears
    hair = "kerchief" if head == "kerchief" else (f"{style}.cap" if head == "cap" and style in CAPPED else (style if cut == 1 or style == "kerchief" else f"{style}.{cut}"))
    return hair, top + [f"trousers-{form}", f"boots-{form}"], [head] if head else []



def from_variant(name):
    """A preset's name, `type:<face type>` (the type's own figure) or `<seed>:<kind>` (man, woman, elder_man, elder_woman, boy, girl)."""
    if name.startswith("type:"):
        return from_type(name[5:])
    if name.startswith("style:"):
        return from_style(name[6:])
    if name.startswith("piece:"):
        return from_piece(name[6:])
    if name.startswith("overlay:"):
        return from_overlay(name[8:])
    if ":" in name:
        seed, kind = name.split(":")
        sex, lo, hi = KINDS[kind]
        return dict(seed=int(seed), sex=sex, age=round(rnd(int(seed), "kind.age").uniform(lo, hi), 1))
    if name not in PRESETS:
        raise SystemExit(f"variant {name!r}: not one of {sorted(PRESETS)} or <seed>:<kind> with kind in {sorted(KINDS)}")
    return copy.deepcopy(PRESETS[name])


def set_path(p, text):
    """Apply `a.b=value` to a parameter object (value as JSON, else a string)."""
    key, value = text.split("=", 1)
    try:
        value = json.loads(value)
    except ValueError:
        pass
    node = p
    parts = key.split(".")
    for k in parts[:-1]:
        node = node.setdefault(k, {})
    node[parts[-1]] = value


def given_from_args(a):
    given = {}
    if getattr(a, "variant", None):
        given = from_variant(a.variant)
    if getattr(a, "params", None):
        deep_update(given, json.load(open(a.params)))
    if getattr(a, "seed", None) is not None:
        given["seed"] = a.seed
    for s in getattr(a, "set", None) or []:
        set_path(given, s)
    return given


def add_args(ap):
    ap.add_argument("--variant", help=f"a preset ({', '.join(sorted(PRESETS))}) or `<seed>:<kind>` with kind in {', '.join(sorted(KINDS))}")
    ap.add_argument("--params", help="a JSON file of parameters (any subset; see docs/CHARACTERS.md)")
    ap.add_argument("--seed", type=int, help="the seed everything not given is drawn from")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", help="override one value, e.g. --set age=70 --set face.jaw_width=0.8 (repeatable)")


def doc():
    """The parameter reference, as Markdown (pasted into docs/CHARACTERS.md)."""
    out = ["| Parameter | Values | Drawn from the seed as |", "|---|---|---|"]
    rows = [
        ("`seed`", "integer", "given (0 if missing)"),
        ("`family`", "integer or text", "none; relatives who share it share part of their face, skin, eyes and hair colour"),
        ("`sex`", "`male`, `female`", "even"),
        ("`age`", "years, 1 to about 80", "Cullet's mix: 14 children (2 to 16), 44 adults (18 to 59), 6 elders (62 to 78) in 64"),
        ("`build.height`", "metres", "by age and sex (adults about 1.77 ± 0.055 m for men, 1.64 for women; a growth table under 18)"),
        ("`build.weight`", "-1 lean to 1 heavy", "normal round 0"),
        ("`build.muscle`", "-1 slight to 1 strong", "normal round 0, a little higher for men"),
        ("`skin.tone`", "0 fairest to 1 darkest", "mostly fair to medium; from the family when one is given"),
        ("`skin.freckles`", "0 to 1", "about a quarter of people, more on fair skin and on children"),
        ("`skin.weathered`", "0 to 1 (ruddier, deeper, lined)", "rises with age"),
        ("`eyes.colour`", ", ".join(f"`{k}`" for k in EYE_COLOURS) + ", or `[r, g, b]`", "by skin tone; often the family's"),
        ("`stylise`", "0 to 1: how far the face leans toward the reference's drawing", "not drawn; the town's one number, `STYLE[\"toward\"]`"),
        ("`hair.style`", ", ".join(f"`{k}`" for k in HAIR_STYLES), "by sex and age; `balding` for men whose hairline has gone far back, `sides` under a cap, `kerchief` under a headscarf"),
        ("`hair.colour`", ", ".join(f"`{k}`" for k in HAIR_COLOURS) + ", or `[r, g, b]`", "by skin tone; often the family's"),
        ("`hair.grey`", "0 to 1; hair greys lock by lock before it greys all over", "rises from about 36"),
        ("`hair.length`", "metres the hair hangs below the hairline over the ear, or a bun's size; for the short styles it scales the hairs' own length round 0.07", "by style (`HAIR_LENGTHS`)"),
        ("`hair.parting`", "-1 to 1: where the hair parts, from the character's right to the left, 0 the middle", "normal round 0"),
        ("`hair.fringe`", "0 none to 1 at the brows (up to 1.3, over the eyes)", "0.5 to 1.05; grown men 0.3 to 0.9"),
        ("`hair.fringe_style`", "`auto` (the style's own), `straight`, `swept`, `curtain`", "`auto`"),
        ("`hair.volume`", "0 flat to 1 full", "0.25 to 0.85"),
        ("`hair.curl`", "0 straight to 1 curly", "mostly straight"),
        ("`hair.recede`", "0 to 1: men's front hairline; with `balding`, how far the bald crown reaches", "rises with age"),
        ("`beard.style`", ", ".join(f"`{k}`" for k in BEARD_STYLES), "men from 17; fuller with age"),
        ("`beard.stubble`", "0 to 1 (shade on the jaw and lip)", "light for most men"),
        ("`outfit.coat`", ", ".join(f"`{k}`" for k in COATS), "by sex and age"),
        ("`outfit.coat_colour`, `outfit.jersey_colour`, `outfit.headwear_colour`", ", ".join(f"`{k}`" for k in CLOTH) + ", or `[r, g, b]`", "Cullet's cloth; the exact shade is drawn within the name's range"),
        ("`outfit.headwear`", ", ".join(f"`{k}`" for k in HEADWEAR), "caps on some men, kerchiefs on some women"),
        ("`outfit.apron`", "true, false (on a smock)", "most women"),
        ("`outfit.hem`", "metres above the ground a smock ends", "0.50 to 0.74"),
    ]
    out += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    out += ["", "| `face.` | at -1 | at 1 |", "|---|---|---|"]
    out += [f"| `{k}` | {lo} | {hi} |" for k, lo, hi in FACE]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_args(ap)
    ap.add_argument("--doc", action="store_true", help="print the parameter reference tables")
    ap.add_argument("--resolved", action="store_true", help="print the generator's numbers instead of the parameters")
    ap.add_argument("--recipe", metavar="NAME", help="print the game recipe (recipes.json) for the person's model lookdev/own-NAME.glb")
    a = ap.parse_args()
    if a.doc:
        print(doc())
        return
    p = draw(given_from_args(a))
    if a.recipe:
        print(json.dumps(dict(name=f"cullet-{a.recipe}", base=f"lookdev/own-{a.recipe}.glb", **resolve(p)["recipe"])))
        return
    json.dump(resolve(p) if a.resolved else p, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
