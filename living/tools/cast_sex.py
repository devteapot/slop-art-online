#!/usr/bin/env python3
"""Each authored resident's body sex, from its world's cast into the compiled seeds (docs/LIVING_CORE.md,
"Body sex"). Every cast member carries `"sex": "f"|"m"`; the authority reads it from the seed's
residents (`SeedResident.sex`) and refuses an authored cast whose residents lack it.

    python3 living/tools/cast_sex.py            # writes `sex` into every compiled seed of a cast
    python3 living/tools/cast_sex.py --check    # fails when a seed's residents differ from their cast

Only `sex` is written, next to each resident's `age`, and the rest of each file's text is left as
it is: some compiled seeds no longer recompile to themselves (docs/LOOK.md §9), so this does not
recompile them. `author_world.py` writes `sex` too when a world is compiled.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEEDS = os.path.join(ROOT, "living", "seeds")
# world -> (its cast files, the compiled seeds made from it)
WORLDS = {
    "island": (["worlds/island/cast/*.json"], ["island.json"]),
    "cullet": (["worlds/cullet/cast.json"], ["cullet.json"]),
    "aske-coast": (["worlds/aske-coast/cast.json"], ["aske-coast.json", "aske-coast-dynamic.json", "aske-coast-crypercept.json", "aske-coast-yieldnorm.json"]),
}


def cast_sexes(patterns):
    """Name -> "f" or "m" for every cast member (any object with a name and a sex)."""
    out = {}

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("name"), str) and x.get("sex") in ("f", "m"):
                out[x["name"]] = x["sex"]
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for p in patterns:
        for f in sorted(glob.glob(os.path.join(SEEDS, p))):
            with open(f, encoding="utf-8") as fh:
                walk(json.load(fh))
    return out


def residents(seed):
    return [r for t in seed.get("towns", []) + seed.get("villages", []) for r in t.get("residents", [])]


def with_sex(text, sexes):
    """The seed text with each resident's `sex` set from `sexes`, by editing the text only."""
    seed = json.loads(text)
    rs = residents(seed)
    missing = [r["name"] for r in rs if r["name"] not in sexes]
    if missing:
        raise SystemExit(f"no sex in the cast for {', '.join(missing[:5])}")
    if all(r.get("sex") == sexes[r["name"]] for r in rs):
        return text
    if any("sex" in r for r in rs):
        # Already carries some: rewrite the values in place.
        out, pos = [], 0
        for r in rs:
            i = text.index(json.dumps(r["name"], ensure_ascii=False), pos)
            j = text.index('"sex"', i)
            m = re.compile(r'"sex"\s*:\s*"[^"]*"').match(text, j)
            out.append(text[pos:m.start()])
            out.append(f'"sex": "{sexes[r["name"]]}"')
            pos = m.end()
        return "".join(out) + text[pos:]
    start = text.index('"residents"')
    out, pos = [text[:start]], start
    age_re = re.compile(r'"age"\s*:\s*[-0-9.eE+]+')
    for r in rs:
        name = '"name": ' + json.dumps(r["name"], ensure_ascii=False)
        # The resident's own object: the first occurrence of its name whose object gives an age
        # before the next name (a sheet's relations name people too, with no age).
        at, i = None, pos
        while True:
            i = text.index(name, i)
            nxt = text.find('"name": ', i + len(name))
            m = age_re.search(text, i)
            if "age" not in r:
                at = i + len(name)
                break
            if m is not None and (nxt == -1 or m.start() < nxt):
                at = m.end()
                break
            i += len(name)
        out.append(text[pos:at])
        # On its own line in a file written one key a line, else inline.
        nl = re.compile(r",\n([ \t]*)").match(text, at)
        sep = f",\n{nl.group(1)}" if nl else ", "
        out.append(f'{sep}"sex": "{sexes[r["name"]]}"')
        pos = at
    out.append(text[pos:])
    new = "".join(out)
    after = json.loads(new)
    assert all(r["sex"] == sexes[r["name"]] for r in residents(after))
    return new


def main():
    check = "--check" in sys.argv[1:]
    bad = 0
    for world, (casts, seeds) in WORLDS.items():
        sexes = cast_sexes(casts)
        for s in seeds:
            path = os.path.join(SEEDS, s)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            new = with_sex(text, sexes)
            if new == text:
                print(f"{s}: {len(residents(json.loads(text)))} residents carry their cast's sex")
                continue
            if check:
                print(f"{s}: residents' sex differs from {world}'s cast (run living/tools/cast_sex.py)")
                bad += 1
                continue
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
            print(f"{s}: wrote sex for {len(residents(json.loads(new)))} residents from {world}'s cast")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
