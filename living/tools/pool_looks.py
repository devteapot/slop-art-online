#!/usr/bin/env python3
"""A world's look data from the pool alone (docs/LOOK.md §5): every one of its people wears a pool
entry by `pool_pick(world_seed, id, pool_len)`, as newcomers do, and nobody is assigned one.

    python3 living/tools/pool_looks.py island                      # writes living/seeds/worlds/island/looks.json
    python3 living/tools/pool_looks.py island --into island        # and sets `looks` in living/seeds/island.json
    python3 living/tools/pool_looks.py island --into island --check  # fails when either is not what it would write

The pool comes from another world's data of the same generation, written by the generator
(`living/tools/characters/look_lines.py book`): `--from` (default Cullet's
`living/seeds/worlds/cullet/looks.json`). Its `pool`, each pool person's `people` entry (a line for
every band) and those lines' `words` are copied; the source's residents and their lines are
not. The generation stays the source's, so the client's book already holds every line (the pool's
lines are in it). `residents` is empty: the world's seed gives no one a `look`.
`author_world.py <world> --compile-only` writes `looks` into the world's seed whenever it compiles.
`--into SEED` writes only the seed's `looks` and leaves every other key as it is: for a seed whose
compile no longer reproduces it (the island's cast still says `mending` where its seed was renamed
to `wound_tending`), so no other change is undone. The seed keeps its formatting (indent 2).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def pool_only(src):
    looks = src["looks"]
    pool = looks["pool"]
    people = {lp: looks["people"][lp] for lp in pool}
    keys = sorted({lk for bands in people.values() for lk in bands.values()})
    missing = [k for k in keys if k not in looks["words"]]
    if missing:
        raise SystemExit(f"pool_looks: {len(missing)} pool lines have no words in the source (e.g. {missing[0]})")
    return {
        "about": "Look data from the pool alone (living/tools/pool_looks.py; docs/LOOK.md §5): every resident wears a pool entry by pool_pick(world seed, id, pool length), as newcomers do. Copied from the generator's world data of the same generation; never shipped to a client.",
        "looks": {"generation": looks["generation"], "people": people, "words": {k: looks["words"][k] for k in keys}, "pool": pool},
        "residents": {},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("world", help="the world directory's name under living/seeds/worlds")
    ap.add_argument("--from", dest="src", default=str(ROOT / "living/seeds/worlds/cullet/looks.json"))
    ap.add_argument("--into", default="", help="also set `looks` in living/seeds/<INTO>.json, changing nothing else")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    out = ROOT / "living/seeds/worlds" / a.world / "looks.json"
    data = pool_only(json.loads(Path(a.src).read_text()))
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    seed_path = ROOT / "living/seeds" / f"{a.into}.json" if a.into else None
    seed_text = None
    if seed_path:
        seed = json.loads(seed_path.read_text())
        seed["looks"] = data["looks"]
        seed_text = json.dumps(seed, indent=2, ensure_ascii=False) + "\n"
    if a.check:
        bad = [p for p, t in ((out, text), (seed_path, seed_text)) if p and (not p.exists() or p.read_text() != t)]
        for p in bad:
            print(f"pool_looks: {p.relative_to(ROOT)} differs from the pool of {a.src}")
        return 1 if bad else 0
    out.write_text(text)
    if seed_path:
        seed_path.write_text(seed_text)
        print(f"pool_looks: set `looks` in {seed_path.relative_to(ROOT)}")
    l = data["looks"]
    print(f"pool_looks: wrote {out.relative_to(ROOT)}: generation {l['generation']}, a pool of {len(l['pool'])} people, {len(l['words'])} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
