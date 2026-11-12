#!/usr/bin/env python3
"""Write the client's identity test cases: compose.py's `transforms` for three sets of values.

    python3 living/tools/characters/identity_cases.py [PERSON.params.json]

The game's `characters::identity` is a port of `transforms`; its test reads
living/game/src/characters/identity_cases.json and must give the same moves, turns and scales.
Run this again when the rig (types.json) or the rule changes. The cases: every value at 1, every
value at -1, and a person's values (a generated person's `identity`, or a fixed mixed set).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import compose  # noqa: E402
import face_types  # noqa: E402

OUT = os.path.normpath(os.path.join(HERE, "..", "..", "game", "src", "characters", "identity_cases.json"))


def main():
    ids = [v[0] for v in face_types.rig_values()]
    person = json.load(open(sys.argv[1]))["identity"] if len(sys.argv) > 1 else {k: round(((i * 37) % 19) / 9.0 - 1.0, 3) for i, k in enumerate(ids)}
    head_m = face_types.load()["file"]["head_height_m"]
    cases = []
    for name, values in (("every value at 1", {k: 1.0 for k in ids}), ("every value at -1", {k: -1.0 for k in ids}), ("a person", person)):
        bones = {b: [move, rot, scale] for b, (move, rot, scale) in compose.transforms(values, head_m).items()}
        cases.append(dict(name=name, values=values, bones=bones))
    with open(OUT, "w") as f:
        json.dump(cases, f, indent=1)
    print(f"identity_cases: {OUT}: {len(cases)} cases, {len(cases[0]['bones'])} bones each")


if __name__ == "__main__":
    main()
