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
import random
import sys

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
    "man": dict(seed=3, sex="male", age=36, build=dict(height=1.80, weight=0.1, muscle=0.4), beard=dict(style="full"), hair=dict(style="tousled", colour="dark_brown"),
                eyes=dict(colour="blue"), skin=dict(tone=0.30), outfit=dict(coat="coat", coat_colour="oilskin", jersey_colour="green", headwear="none")),
    "woman": dict(seed=8, sex="female", age=29, build=dict(height=1.66), hair=dict(style="long", colour="chestnut", length=0.30, parting=0.0, fringe=0.95, fringe_style="straight", volume=0.55, curl=0.1), eyes=dict(colour="green"), skin=dict(tone=0.22),
                  outfit=dict(coat="smock", coat_colour="blue", jersey_colour="cream", headwear="none", apron=True)),
    "elder": dict(seed=5, sex="male", age=70, build=dict(height=1.72), beard=dict(style="short"), hair=dict(style="sides"), eyes=dict(colour="grey"), skin=dict(tone=0.30),
                  outfit=dict(coat="coat", coat_colour="tarred", jersey_colour="red", headwear="cap")),
    "youth": dict(seed=11, sex="male", age=15, hair=dict(style="tousled", colour="sandy"), outfit=dict(coat="none", jersey_colour="cream", headwear="none")),
    "heavy": dict(seed=31, sex="male", age=44, build=dict(height=1.88, weight=0.9, muscle=0.6), beard=dict(style="short"), hair=dict(style="short", colour="auburn"), skin=dict(tone=0.45),
                  outfit=dict(coat="smock", coat_colour="canvas", jersey_colour="navy", headwear="none")),
    "boy": dict(seed=21, sex="male", age=8, hair=dict(style="tousled", colour="chestnut"), outfit=dict(coat="none", jersey_colour="blue")),
    "girl": dict(seed=22, sex="female", age=6, hair=dict(style="bob", colour="brown"), outfit=dict(coat="smock", coat_colour="red", apron=False)),
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
    natural = rnd(src if rnd(seed, "hair.own").random() < 0.7 else seed, "hair.colour").choices(
        ("black", "dark_brown", "brown", "chestnut", "auburn", "sandy", "blond"), weights=(6, 5, 2, 1, 0.3, 0.1, 0.05) if dark else (2, 5, 5, 3, 2, 3, 2 if not child else 4))[0]
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
    lash = mix((0.10, 0.075, 0.07), natural, 0.25 if sum(natural) > 0.7 else 0.0)
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
        lash_k=0.66 + 0.74 * fem + 0.34 * child * (1 - masc) + 0.12 * child, lash_wing=0.14 + 0.22 * fem + 0.06 * child, wing_lift=0.10 + 0.22 * fem,
        lashes=int(round(3 * fem + (1 if child > 0.5 and not male else 0))), fold=clip(0.65 + 0.5 * face.get("eye_fold", 0) + 0.35 * elder, 0, 1.6),
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
    return dict(
        seed=seed, masc=masc, child=child, elder=elder, face=face, look=look, girth=girth, limb=limb, belly=belly, chest=chest, woman_torso=bool(not male and age >= 13),
        hair_style=hair_p["style"], hair_length=hair_p.get("length", 0.07), recede=0.024 * clip(hair_p.get("recede", 0.0), 0, 1),
        hair=dict(style=hair_p["style"], length=float(hair_p.get("length", 0.07)), parting=float(hair_p.get("parting", 0.0)), fringe=float(hair_p.get("fringe", 0.7)), volume=float(hair_p.get("volume", 0.5)),
                  curl=float(hair_p.get("curl", 0.0)), fringe_style=hair_p.get("fringe_style", "auto")),
        bald=smooth((clip(hair_p.get("recede", 0.0), 0, 1) - 0.55) / 0.40) if hair_p["style"] == "balding" else 0.0,
        beard=style if male else "none", coat=None if outfit["coat"] == "none" else outfit["coat"], headwear=None if outfit["headwear"] == "none" else outfit["headwear"],
        coat_colour=cloth(seed, "coat", outfit["coat_colour"]), jersey=cloth(seed, "jersey", outfit["jersey_colour"]), headwear_colour=cloth(seed, "headwear", outfit["headwear_colour"]),
        patches=(cloth(seed, "patch1", "canvas"), cloth(seed, "patch2", "olive"), cloth(seed, "patch3", "red")), apron=bool(outfit.get("apron", False)), hem=float(outfit.get("hem", 0.74)),
        recipe=recipe,
    )


def from_variant(name):
    """A preset's name, or `<seed>:<kind>` (man, woman, elder_man, elder_woman, boy, girl)."""
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
        ("`hair.style`", ", ".join(f"`{k}`" for k in HAIR_STYLES), "by sex and age"),
        ("`hair.colour`", ", ".join(f"`{k}`" for k in HAIR_COLOURS) + ", or `[r, g, b]`", "by skin tone; often the family's"),
        ("`hair.grey`", "0 to 1", "rises from about 36"),
        ("`hair.length`", "metres a bob hangs below the hairline", "0.05 to 0.11"),
        ("`hair.recede`", "0 to 1 (men's front hairline)", "rises with age"),
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
