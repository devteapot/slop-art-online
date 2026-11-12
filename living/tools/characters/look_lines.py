#!/usr/bin/env python3
"""The look book: a person line and its words for every look band a person can reach, under
opaque keys (docs/LOOK.md §2, §4, §5; docs/CHARACTERS.md, "The look book").

    python3 living/tools/characters/look_lines.py book --town living/seeds/cullet.json
    python3 living/tools/characters/look_lines.py cases --town living/seeds/cullet.json   # test cases: the key hash, bands from the cast
    python3 living/tools/characters/look_lines.py wear STYLES_DIR                          # slot and layer into each outfit file

`book` writes two files (docs/LOOK.md §5):

  living/game/assets/characters/looks.json    the book, a client asset (git-ignored): lines only
      generation   "c4-" and 8 hex digits of a hash of every line key
      lines        {"lk_…": {person: the line as the composer reads it, words: LookWords}}
      decor        ["lk_…"]: lines for the island's background people, none of which a
                   character can wear
      files        every shared file the lines name, with how many lines use it; an outfit
                   piece's slot and layer
    It does not say whose a line is: no people, no pool, no names. A client cannot tell a
    resident's line from a newcomer's, or link one person's lines across ages.
  living/seeds/worlds/<run>/looks.json        the world's data (tracked; never shipped to a client)
      looks        {generation, people: {lp: {band: lk}}, words: {lk: LookWords}, pool: [lp]}
      residents    {the seed's name of each resident: "lp_…"}

**Keys.** A line's key is `lk_` and the first 16 hex digits of the SHA-256 of the line's
canonical JSON: only the fields the client draws (`type`, `height`, `proportions`, `identity`,
`colors`, `styles`, `belly`, `grey`, those the line has), keys sorted at every depth, separators
`,` and `:` with no spaces, numbers in their shortest form that reads back the same, UTF-8.
A person's key is `lp_` and the first 16 hex digits of the SHA-256 of their bands and line keys
(`0:lk_…|1:lk_…`, in band order). No key comes from a name or from the cast's order.

**Bands** (docs/LOOK.md §4): 0 infant (stage 0), 1 child (stage 1 and under 12), 2 youth (12 to
under 18), 3 adult (stage 2 and 18 or over), 4 elder (stage 3). `look_band` is the rules'
(living_rules::look); `band_of` here is the same rule, for writing the book.

**Who is in it.**
- A town's residents: a line for the band each is in now and for every later one. The band they
  are in now is their line as the town's build made it (town.py: its outfit colours are measured
  from the built file). A later band is the same person drawn at that band's age: the same seed,
  sex, family and skin tone, so the same identity values, eye and hair colour; the type follows
  sex and band; grey, lines and build come as the generator ages people.
- The pool and the decor: people drawn from seeds of their own, half women and half men, each
  with all five bands.
- An infant is a child type at an infant's size (0.70 to 0.85 m, with the larger head the
  generator gives that height), hair cropped, in a plain smock: there is no baby type yet.

**Words** (`words_of`): what a glance can say of a line, from the person's parameters, by one
naming function. `colour` is one of about ten words, the main upper garment's.

An unbuilt line's outfit colours are its cloths' colours taken to what they would be painted:
the value and saturation ratio and the turn of hue that the built residents' pieces of that
kind have (`paint_rule`). Against the built colours that is within 3.7 CIE76, 0.5 at the median.
"""
import argparse
import collections
import colorsys
import hashlib
import json
import os
import random
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "blender"))
sys.path.insert(0, os.path.join(HERE, ".."))
import person_params  # noqa: E402

LOOKDEV = os.path.join(ROOT, "living", "game", "assets", "lookdev")
BOOK = os.path.join(ROOT, "living", "game", "assets", "characters", "looks.json")
BANDS = ("infant", "child", "youth", "adult", "elder")
YOUTH_FROM, ADULT_FROM = 12.0, 18.0  # the world law `look_bands()`'s defaults (docs/LOOK.md §4)
# The age a resident is drawn at in a band they have not reached yet.
BAND_AGE = (1.0, 8.0, 15.0, 30.0, 68.0)
# The ages a pool person is drawn at, each by their own draw within the band.
POOL_AGES = ((1.0, 1.0), (4.0, 11.5), (12.0, 17.5), (19.0, 56.0), (61.0, 80.0))
POOL, DECOR = 128, 96
# A cloth's name (person_params.CLOTH) as the one colour word a glance gives it: ten cloths, nine words.
CLOTH_WORDS = dict(oilskin="yellow", tarred="black", olive="green", canvas="tan", blue="blue", red="red", green="green", cream="cream", navy="navy", heather="purple")
# The fields of a line the client draws: what a line's key is the hash of, and all the book keeps.
DRAWN = ("type", "height", "proportions", "identity", "colors", "styles", "belly", "grey")
# Of the decor's people, how many are drawn at each band: the island's background, as a town's ages run.
DECOR_BANDS = (1, 2, 3, 3, 3, 3, 3, 4)


def stage_ages(seed):
    """Where a person's stages end in this world, in years: (infant, child, elder). Infancy's
    end and old age's start are the species' (living/seeds/species.json `person.life`); childhood's
    end is the world's `life_years` law where it has one (15 in Cullet), else the species'."""
    life = json.load(open(os.path.join(ROOT, "living", "seeds", "species.json")))["person"]["life"]
    years = float(life["years"])
    infant, child, elder = life["infant"] * years, life["child"] * years, life["elder"] * years
    if seed.get("laws_file"):
        text = open(os.path.join(ROOT, "living", "seeds", seed["laws_file"])).read()
        m = re.search(r"fn person_years\(\)\s*\{\s*#\{([^}]*)\}", text)
        if m:
            child = float(dict(re.findall(r"(\w+):\s*([0-9.]+)", m.group(1))).get("child", child))
    return infant, child, elder


def stage_of(age, ages):
    return 0 if age < ages[0] else (1 if age < ages[1] else (2 if age < ages[2] else 3))


def band_of(stage, age):
    """A character's look band from its stage (0 infant, 1 child, 2 adult, 3 elder) and its age
    in years."""
    return 0 if stage == 0 else (4 if stage == 3 else (1 if age < YOUTH_FROM else (2 if age < ADULT_FROM else 3)))


def given_for(person, band, age):
    """A person's parameters as given to the generator for a band: who they are, at that age."""
    g = {k: person[k] for k in ("seed", "sex", "family", "skin") if k in person}
    g["age"] = age
    if band == 0:
        g["hair"] = dict(style="crop")
        g["outfit"] = dict(coat="smock", apron=False, headwear="none")
    return g


def drawn(given, band):
    """(the filled-in parameters, the person line) for a set of given values."""
    p = person_params.draw(given)
    line = json.loads(json.dumps(person_params.resolve(p)["person"]))
    if band == 0:
        line["height"] = round(min(max(line["height"], 0.70), 0.85), 2)
    return p, line


def linear(h):
    c = [int(h[k : k + 2], 16) / 255 for k in (1, 3, 5)]
    return [((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c]


def stored(c):
    return "#" + "".join(f"{round(min(max(1.055 * x ** (1 / 2.4) - 0.055 if x > 0.0031308 else 12.92 * x, 0.0), 1.0) * 255):02x}" for x in c)


def stem(piece):
    return piece[:-2] if piece[-2:] in ("-m", "-f") else piece


def paint_rule(built):
    """From built residents, each kind of piece's step from its cloth's colour to its painted
    colour: {stem: (value ratio, saturation ratio, turn of hue)}, the medians. `built` is a list
    of (line as built, the same line as drawn)."""
    seen = collections.defaultdict(list)
    for made, plain in built:
        for piece, h in made["colors"].get("outfit", {}).items():
            if piece in plain["colors"].get("outfit", {}):
                a, b = colorsys.rgb_to_hsv(*linear(h)), colorsys.rgb_to_hsv(*linear(plain["colors"]["outfit"][piece]))
                seen[stem(piece)].append((a[2] / max(b[2], 1e-6), a[1] / max(b[1], 1e-6), (a[0] - b[0] + 0.5) % 1.0 - 0.5))
    return {k: tuple(statistics.median(x[i] for x in v) for i in range(3)) for k, v in seen.items()}


def painted(line, rule):
    """A drawn line with its outfit colours as they would be painted."""
    for piece, h in line["colors"].get("outfit", {}).items():
        if stem(piece) in rule:
            kv, ks, dh = rule[stem(piece)]
            hh, s, v = colorsys.rgb_to_hsv(*linear(h))
            line["colors"]["outfit"][piece] = stored(colorsys.hsv_to_rgb((hh + dh) % 1.0, min(s * ks, 1.0), min(v * kv, 1.0)))
    return line


def words_of(p, line, band):
    """LookWords for a line (docs/LOOK.md §2): what a glance can say, from the person's
    parameters `p` and the line. One function names everyone."""
    male = p["sex"] == "male"
    age = p["age"]
    form = ("baby", "boy" if male else "girl", "young man" if male else "young woman", "man" if male else "woman", "old man" if male else "old woman")[band]
    # Girth: the build's weight draw, and a belly.
    weight = p["build"]["weight"]
    girth = 2 if weight > 0.45 or line.get("belly", 0.0) > 0.12 else (0 if weight < -0.35 else 1)
    # Height for the band: against what the generator expects at that age and sex.
    expected = person_params.child_height(age, male) - 0.03 * person_params.smooth((age - 55) / 20)
    sd = 0.055 if age >= 18 else 0.03
    off = (p["build"]["height"] - expected) / sd
    height = 0 if off < -0.6 else (2 if off > 0.6 else 1)
    outfit = p["outfit"]
    head = {"cap": "a cap", "kerchief": "a kerchief"}.get(outfit.get("headwear"), "")
    hair_p = p["hair"]
    grey = hair_p.get("grey", 0.0)
    tone = "white" if grey > 0.85 else ("grey" if grey > 0.5 else dict(black="dark", dark_brown="dark", brown="brown", chestnut="brown", auburn="red", sandy="fair", blond="fair").get(hair_p["colour"], "dark"))
    if line["styles"]["hair"].startswith("kerchief"):
        hair = ""
    elif line["styles"]["hair"].startswith("balding"):
        hair = "bald"
    else:
        hair = f"{tone}-haired"
    over = line["styles"].get("overlays", [])
    beard = next((dict(moustache=f"a {tone} moustache", goatee=f"a {tone} goatee").get(o[6:], f"a {tone} beard") for o in over if o.startswith("beard_")), "stubble" if "stubble" in over else "")
    coat = outfit["coat"]
    cloth = outfit["coat_colour"] if coat in ("coat", "smock") else outfit["jersey_colour"]
    colour = CLOTH_WORDS.get(cloth, "grey") if isinstance(cloth, str) else "grey"
    garment = coat if coat in ("coat", "smock") else "jersey"
    top = f"a {colour} {garment}" + (" with an apron" if coat == "smock" and outfit.get("apron") else "")
    return dict(form=form, girth=girth, height=height, hair=hair, top=top, bottom="dark trousers", head=head, beard=beard)


def canonical(line):
    """A line's canonical JSON: its drawn fields, keys sorted, no spaces."""
    return json.dumps({k: line[k] for k in DRAWN if k in line}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def key_of(line):
    return "lk_" + hashlib.sha256(canonical(line).encode("utf-8")).hexdigest()[:16]


def person_key(bands):
    return "lp_" + hashlib.sha256("|".join(f"{b}:{k}" for b, k in sorted(bands.items())).encode("utf-8")).hexdigest()[:16]


def files_of(lines):
    """Every shared file the lines name: {path under lookdev/: {uses, and an outfit's slot and layer}}."""
    out = collections.Counter()
    for line in lines:
        out["types/" + line["type"]] += 1
        out["styles/hair/" + line["styles"]["hair"]] += 1
        for p in line["styles"]["outfit"]:
            out["styles/outfit/" + p] += 1
        for o in line["styles"].get("overlays", []):
            out[f"styles/overlay/{line['type']}/{o}"] += 1
    files = {}
    for k, n in sorted(out.items()):
        files[k] = dict(uses=n)
        if k.startswith("styles/outfit/"):
            files[k].update(person_params.piece_wear(k.rsplit("/", 1)[1]))
    return files


def residents(a):
    """The town's people with each one's stage and band now."""
    import town

    seed = json.load(open(a.town))
    ages = stage_ages(seed)
    people = town.from_seed(seed, a.town)["people"]
    for p in people:
        p["stage"] = stage_of(p["age"], ages)
        p["band"] = band_of(p["stage"], p["age"])
    return seed, ages, people


def book(a):
    seed, ages, people = residents(a)
    run = seed.get("run") or "town"
    entries, built = [], []  # (who, band, parameters, line, as built?)
    for p in people:
        for b in range(p["band"], len(BANDS)):
            params, line = drawn(given_for(p, b, p["age"] if b == p["band"] else BAND_AGE[b]), b)
            made_path = os.path.join(a.built, f"own-{p['name']}.params.json")
            made = b == p["band"] and b != 0 and os.path.exists(made_path)
            if made:
                own = json.load(open(made_path))["person"]
                if own["type"] != line["type"] or own["identity"] != line["identity"]:
                    raise SystemExit(f"look_lines: {made_path} is not this person as drawn now; build the town again")
                built.append((own, line))
                line = own
            entries.append((("resident", p["full_name"]), b, params, line, made))
    if not built:
        raise SystemExit(f"look_lines: no built residents under {a.built}; run town.py first (the outfit colours are measured from them)")
    for i in range(a.pool):
        p = dict(seed=20000 + i, sex="female" if i % 2 == 0 else "male")
        r = random.Random(f"pool/{i}")
        for b in range(len(BANDS)):
            params, line = drawn(given_for(p, b, round(r.uniform(*POOL_AGES[b]), 1)), b)
            entries.append((("pool", i), b, params, line, False))
    for i in range(a.decor):
        # A background figure is one line: someone at one age.
        p = dict(seed=40000 + i, sex="female" if i % 2 == 0 else "male")
        r = random.Random(f"decor/{i}")
        b = DECOR_BANDS[(i // 2) % len(DECOR_BANDS)]
        params, line = drawn(given_for(p, b, round(r.uniform(*POOL_AGES[b]), 1)), b)
        entries.append((("decor", i), b, params, line, False))
    rule = paint_rule(built)
    lines, by_who = {}, collections.defaultdict(dict)
    for who, b, params, line, made in entries:
        if not made:
            painted(line, rule)
        line = {k: line[k] for k in DRAWN if k in line}
        k = key_of(line)
        lines[k] = dict(person=line, words=words_of(params, line, b))
        by_who[who][b] = k
    decor = sorted({k for who, bands in by_who.items() if who[0] == "decor" for k in bands.values()})
    worn = {k for who, bands in by_who.items() if who[0] != "decor" for k in bands.values()}
    if worn & set(decor):
        raise SystemExit("look_lines: a decor line is also a line a character can wear")
    people_of = {who: bands for who, bands in by_who.items() if who[0] != "decor"}
    who_key = {who: person_key(bands) for who, bands in people_of.items()}
    if len(set(who_key.values())) != len(who_key):
        raise SystemExit("look_lines: two people came out with the same lines at every band")
    generation = "c4-" + hashlib.sha256("".join(sorted(lines)).encode()).hexdigest()[:8]
    out = dict(generation=generation, lines=dict(sorted(lines.items())), decor=decor, files=files_of(v["person"] for v in lines.values()))
    os.makedirs(os.path.dirname(a.book), exist_ok=True)
    json.dump(out, open(a.book, "w"), indent=1, ensure_ascii=False)
    # The world's data: whose each line is. Never shipped to a client.
    people_keys = {who_key[who]: {str(b): k for b, k in sorted(bands.items())} for who, bands in people_of.items()}
    world = dict(
        about="Cullet's looks: keys and words for the authority (docs/LOOK.md §5). Written by living/tools/characters/look_lines.py with the client's book of the same generation; not edited by hand, and never shipped to a client.",
        looks=dict(generation=generation, people=dict(sorted(people_keys.items())), words={k: lines[k]["words"] for k in sorted(worn)}, pool=[who_key[("pool", i)] for i in range(a.pool)]),
        residents={who[1]: who_key[who] for who in people_of if who[0] == "resident"},
    )
    world_path = a.world or os.path.join(ROOT, "living", "seeds", "worlds", run, "looks.json")
    json.dump(world, open(world_path, "w"), indent=1, ensure_ascii=False)
    n = collections.Counter(b for who, b, *_ in entries if who[0] == "resident")
    print(f"look_lines: generation {generation}: {len(lines)} lines: {len(people)} residents in {sum(n.values())} "
          f"({', '.join(f'{n[b]} {BANDS[b]}' for b in range(5) if n[b])}; {len(built)} as built), {a.pool} pool people with five bands each, {len(decor)} decor lines; "
          f"{len(out['files'])} files named")
    print(f"  {os.path.relpath(a.book, ROOT)} ({os.path.getsize(a.book) // 1024} kB), {os.path.relpath(world_path, ROOT)} ({os.path.getsize(world_path) // 1024} kB)")


def cases(a):
    """Test cases for the authority: the key hash against lines' canonical JSON, and band cases
    from the cast (a resident's age, stage, band and the line their look row holds). Printed,
    and written beside the world's data as `look-cases.json`."""
    seed, ages, people = residents(a)
    world_path = a.world or os.path.join(ROOT, "living", "seeds", "worlds", seed.get("run") or "town", "looks.json")
    world = json.load(open(world_path))
    lines = json.load(open(a.book))["lines"]
    tiny = dict(type="adult-f-a", height=1.6, name="left out: not drawn", seed=7)
    hashes = [dict(line=tiny, canonical=canonical(tiny), key=key_of(tiny))]
    for k in (min(lines), max(lines)):
        hashes.append(dict(line=lines[k]["person"], canonical=canonical(lines[k]["person"]), key=k))
    print("key hash: lk_ + the first 16 hex digits of SHA-256 over the canonical JSON of the drawn fields")
    for h in hashes:
        print(f"  {h['key']}: {len(h['canonical'].encode())} bytes: {h['canonical'][:110]}{'…' if len(h['canonical']) > 110 else ''}")
    print(f"stages end at {ages[0]:.1f} (infant), {ages[1]:.1f} (child) and old age starts at {ages[2]:.1f}; youth from {YOUTH_FROM:g}, adult from {ADULT_FROM:g}")
    pick = {}
    for p in sorted(people, key=lambda p: p["age"]):
        pick.setdefault((p["stage"], p["band"]), []).append(p)
    rows = []
    for p in sorted({q["full_name"]: q for v in pick.values() for q in (v[0], v[-1])}.values(), key=lambda p: p["age"]):
        lp = world["residents"][p["full_name"]]
        bands = world["looks"]["people"][lp]
        rows.append(dict(resident=p["full_name"], age=p["age"], stage=p["stage"], band=p["band"], look=lp, line=bands[str(p["band"])], bands=sorted(int(b) for b in bands)))
        print(f"  {p['full_name']}: age {p['age']:g} -> stage {p['stage']} -> band {p['band']} ({BANDS[p['band']]}) -> {lp} -> {bands[str(p['band'])]}; bands in the data: {', '.join(sorted(bands))}")
    out = dict(
        about="Test cases for the look data (living/tools/characters/look_lines.py cases; docs/CHARACTERS.md, 'The look book'). Written with looks.json of the same generation.",
        generation=world["looks"]["generation"],
        key_hash=dict(rule="lk_ + the first 16 hex digits of SHA-256 over the UTF-8 canonical JSON of the line's drawn fields: " + ", ".join(DRAWN) + "; keys sorted at every depth, separators ',' and ':', no spaces", cases=hashes),
        bands=dict(stages=dict(infant_until=round(ages[0], 2), child_until=round(ages[1], 2), elder_from=round(ages[2], 2)), youth=YOUTH_FROM, adult=ADULT_FROM, cases=rows),
    )
    path = os.path.join(os.path.dirname(world_path), "look-cases.json")
    json.dump(out, open(path, "w"), indent=1, ensure_ascii=False)
    print(f"  {os.path.relpath(path, ROOT)}")


def wear(a):
    """Write each outfit piece's slot and layer into its file's scene extras (`outfit`)."""
    from merge_primitives import read_glb, write_glb

    done = 0
    for f in sorted(os.listdir(os.path.join(a.styles, "outfit"))):
        if not f.endswith(".glb"):
            continue
        path = os.path.join(a.styles, "outfit", f)
        j, binary = read_glb(path)
        scene = j["scenes"][j.get("scene", 0)]
        want = dict(piece=f[:-4], **person_params.piece_wear(f[:-4]))
        if scene.get("extras", {}).get("outfit") != want:
            scene.setdefault("extras", {})["outfit"] = want
            write_glb(path, j, binary)
        done += 1
    print(f"look_lines: {done} outfit files carry their slot and layer")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("book")
    b.add_argument("--town", required=True, help="the world's seed (living/seeds/cullet.json)")
    b.add_argument("--built", default=LOOKDEV, help="where the town's built people are (own-<name>.params.json)")
    b.add_argument("--book", default=BOOK, help="where the client's book goes")
    b.add_argument("--world", default="", help="where the world's data goes (default: living/seeds/worlds/<run>/looks.json)")
    b.add_argument("--pool", type=int, default=POOL, help="people in the pool")
    b.add_argument("--decor", type=int, default=DECOR, help="people in the decor pool")
    c = sub.add_parser("cases")
    c.add_argument("--town", required=True)
    c.add_argument("--world", default="")
    c.add_argument("--book", default=BOOK)
    w = sub.add_parser("wear")
    w.add_argument("styles")
    a = ap.parse_args()
    dict(book=book, cases=cases, wear=wear)[a.cmd](a)


if __name__ == "__main__":
    main()
