#!/usr/bin/env python3
"""book_drift.py: the look book made again from the built residents, into a scratch book, against
the committed one. A rebuild may measure an outfit colour a level off (the colour is the built
person's painted cloth, shading included); anything more, or any other field, fails.

    python3 living/tools/characters/book_drift.py [LEVELS] [--json OUT] [--allow FILE]

LEVELS (default 1): how far an outfit colour may be off, in levels of 255.
--json OUT: every difference beyond LEVELS, one entry each, the form --allow reads.
--allow FILE: a reviewed list of known differences (a JSON written by --json and checked by
    hand; living/tools/characters/book-drift-<generation>.json). The check then passes only if
    the differences beyond LEVELS are exactly the listed ones: no difference outside the list, and
    none whose colours differ from the listed shipped and rebuilt colours. A listed difference
    that no longer occurs is reported, not failed (the list can only shrink). Words, decor and any
    field but an outfit colour still fail whatever the list says. The file names the generation it
    is for; against another book it fails. A new generation (which rebuilds the book whole) deletes it.

An entry: {"person": "lp_…", "resident": "Name" or null, "band": "4", "line": "lk_…",
"field": "colors.outfit.<piece>", "shipped": "#rrggbb", "rebuilt": "#rrggbb", "levels": n}."""
import argparse, json, os, subprocess, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("levels", nargs="?", type=int, default=1)
ap.add_argument("--json")
ap.add_argument("--allow")
a = ap.parse_args()
allow = a.levels
d = tempfile.mkdtemp()
subprocess.check_output(["python3", "living/tools/characters/look_lines.py", "book", "--town", "living/seeds/cullet.json", "--book", f"{d}/book.json", "--world", f"{d}/world.json", "--fresh"], cwd=ROOT)
nb, nw = json.load(open(f"{d}/book.json")), json.load(open(f"{d}/world.json"))
ob, ow = json.load(open(f"{ROOT}/living/game/assets/characters/looks.json")), json.load(open(f"{ROOT}/living/seeds/worlds/cullet/looks.json"))
def flat(x, p=""):
    o = {}
    for k, v in x.items():
        o.update(flat(v, p + k + ".") if isinstance(v, dict) else {p + k: v})
    return o
rgb = lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)]
who = {p: name for name, p in ow["residents"].items()}
pairs = [(ow["residents"][w], nw["residents"][w]) for w in ow["residents"]]
pairs += list(zip(ow["looks"]["pool"], nw["looks"]["pool"]))
same = off = 0; worst = 0; bad = []; drift = []
for pa, pc in pairs:
    a_, c = ow["looks"]["people"][pa], nw["looks"]["people"][pc]
    assert set(a_) == set(c)
    for b in a_:
        if a_[b] == c[b]:
            same += 1; continue
        off += 1
        fa, fc = flat(ob["lines"][a_[b]]["person"]), flat(nb["lines"][c[b]]["person"])
        for x in set(fa) | set(fc):
            if fa.get(x) == fc.get(x): continue
            if x.startswith("colors.outfit.") and x in fa and x in fc:
                n = max(abs(p - q) for p, q in zip(rgb(fa[x]), rgb(fc[x]))); worst = max(worst, n)
                if n > allow:
                    drift.append({"person": pa, "resident": who.get(pa), "band": b, "line": a_[b], "field": x, "shipped": fa[x], "rebuilt": fc[x], "levels": n})
            else: bad.append(f"{a_[b]} {x}: {fa.get(x)} now {fc.get(x)}")
        if ob["lines"][a_[b]]["words"] != nb["lines"][c[b]]["words"]: bad.append(f"{a_[b]}: words differ")
# Decor lines have no owner to pair them by: the same lines but for their outfit colours.
bare = lambda book: sorted(json.dumps({k: v for k, v in flat(book["lines"][key]["person"]).items() if not k.startswith("colors.outfit.")}, sort_keys=True) for key in book["decor"])
if bare(ob) != bare(nb): bad.append("decor lines differ in more than an outfit colour")
drift.sort(key=lambda e: (e["line"], e["field"], e["person"], e["band"]))
if a.json:
    with open(a.json, "w") as f:
        json.dump({"generation": ob["generation"], "levels": allow, "differences": drift}, f, indent=1)
        f.write("\n")
note = ""
if a.allow:
    known = json.load(open(a.allow))
    if known.get("generation") != ob["generation"]:
        bad.append(f"{a.allow} is for generation {known.get('generation')}, the book is {ob['generation']}")
    keyf = lambda e: (e["person"], e["band"], e["line"], e["field"])
    listed = {keyf(e): e for e in known.get("differences", [])}
    found = {keyf(e): e for e in drift}
    for k, e in found.items():
        l = listed.get(k)
        if l is None:
            bad.append(f"{e['line']} {e['field']}: {e['shipped']} now {e['rebuilt']} (not in {os.path.basename(a.allow)})")
        elif (l["shipped"], l["rebuilt"]) != (e["shipped"], e["rebuilt"]):
            bad.append(f"{e['line']} {e['field']}: {e['shipped']} now {e['rebuilt']}, listed {l['shipped']} now {l['rebuilt']}")
    gone = [k for k in listed if k not in found]
    note = f"; {len(found) - sum(1 for k in found if k not in listed)} of {len(listed)} listed differences found" + (f", {len(gone)} no longer occur" if gone else "")
else:
    bad += [f"{e['line']} {e['field']}: {e['shipped']} now {e['rebuilt']}" for e in drift]
print(f"book_drift: committed {ob['generation']}; built again {nb['generation']}: {same} lines the same, {off} with an outfit colour off by at most {worst} of 255{note}" + (f"; FAILED:\n  " + "\n  ".join(bad[:20]) + (f"\n  … {len(bad) - 20} more" if len(bad) > 20 else "") if bad else ""))
for f in ("book.json", "world.json"): os.remove(f"{d}/{f}")
os.rmdir(d)
sys.exit(1 if bad else 0)
