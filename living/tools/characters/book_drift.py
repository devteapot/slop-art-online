#!/usr/bin/env python3
"""book_drift.py: the look book made again from the built residents, into a scratch book, against
the committed one. A rebuild may measure an outfit colour a level off (the colour is the built
person's painted cloth, shading included); anything more, or any other field, fails.
    python3 living/tools/characters/book_drift.py [LEVELS]   (default 1)"""
import json, os, subprocess, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
allow = int(sys.argv[1]) if len(sys.argv) > 1 else 1
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
pairs = [(ow["looks"]["people"][ow["residents"][w]], nw["looks"]["people"][nw["residents"][w]]) for w in ow["residents"]]
pairs += [(ow["looks"]["people"][a], nw["looks"]["people"][b]) for a, b in zip(ow["looks"]["pool"], nw["looks"]["pool"])]
same = off = 0; worst = 0; bad = []
for a, c in pairs:
    assert set(a) == set(c)
    for b in a:
        if a[b] == c[b]:
            same += 1; continue
        off += 1
        fa, fc = flat(ob["lines"][a[b]]["person"]), flat(nb["lines"][c[b]]["person"])
        for x in set(fa) | set(fc):
            if fa.get(x) == fc.get(x): continue
            if x.startswith("colors.outfit.") and x in fa and x in fc:
                n = max(abs(p - q) for p, q in zip(rgb(fa[x]), rgb(fc[x]))); worst = max(worst, n)
                if n > allow: bad.append(f"{a[b]} {x}: {fa[x]} now {fc[x]}")
            else: bad.append(f"{a[b]} {x}: {fa.get(x)} now {fc.get(x)}")
        if ob["lines"][a[b]]["words"] != nb["lines"][c[b]]["words"]: bad.append(f"{a[b]}: words differ")
# Decor lines have no owner to pair them by: the same lines but for their outfit colours.
bare = lambda book: sorted(json.dumps({k: v for k, v in flat(book["lines"][key]["person"]).items() if not k.startswith("colors.outfit.")}, sort_keys=True) for key in book["decor"])
if bare(ob) != bare(nb): bad.append("decor lines differ in more than an outfit colour")
print(f"book_drift: committed {ob['generation']}; built again {nb['generation']}: {same} lines the same, {off} with an outfit colour off by at most {worst} of 255" + (f"; FAILED:\n  " + "\n  ".join(bad[:20]) if bad else ""))
for f in ("book.json", "world.json"): os.remove(f"{d}/{f}")
os.rmdir(d)
sys.exit(1 if bad else 0)
