#!/usr/bin/env python3
"""Print a seed as `create_floor` takes it: its JSON with a `laws_file` (a Rhai laws overlay kept
beside the seed, relative to living/seeds) read into `laws`, as `living/authority/build.rs` does
for a compiled seed.

    python3 living/tools/seed_text.py living/seeds/cullet-laws.json        # the seed's text
    python3 living/tools/seed_text.py living/seeds/cullet-laws.json --arg  # as one JSON string argument
"""
import json
import pathlib
import sys

SEEDS = pathlib.Path(__file__).resolve().parent.parent / "seeds"


def resolved(path):
    seed = json.loads(pathlib.Path(path).read_text())
    if seed.get("laws_file") and not str(seed.get("laws") or "").strip():
        seed["laws"] = (SEEDS / seed["laws_file"]).read_text()
    return seed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    text = json.dumps(resolved(sys.argv[1]))
    print(json.dumps(text) if "--arg" in sys.argv[2:] else text)
