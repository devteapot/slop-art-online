#!/usr/bin/env python3
"""Hold a character's eyes open while it is photographed.

    python3 living/tools/characters/hold_eyes.py hold TOKENS      prints the files it held
    python3 living/tools/characters/hold_eyes.py release [FILE ...]   (no files: every file still held)

The asset view shows people alive: they blink every few seconds, and a still that catches a
blink reads as a fault of the model. The view finds a face by its two morph targets,
`…Fcl_EYE_Close` and `…Fcl_MTH_A`; with the first renamed it finds no face and nothing blinks.
`hold` renames it in each file's glTF JSON to a name of the same length (`Fcl_EYE_Held_`), so
no byte moves, and `release` puts it back. The photo tools do both round every still
(`view_assets.sh`, the board's `capture.py`); `LIVING_VIEW_BLINK=1` leaves the eyes alone.

TOKENS is what the asset view takes (`LIVING_GAME_VIEW`): files and folders under the game's
assets, comma separated, and `recipe:<name>`, whose base file is looked up in
`characters/recipes.json`. A file's animated copy (`anim/<name>.glb` beside it), which is what the
game draws when there is one, is held with it. A `recipe:<folk>:<seed>` person is not held (its base is drawn in the
game). Files held are listed in `.local/held-eyes.txt` until released, so a run that was killed
is undone by the next one. Two runs photographing the same file at once can release it under
each other; the second may then catch a blink.
"""

import contextlib
import json
import os
import struct
import sys

OPEN, HELD = b"Fcl_EYE_Close", b"Fcl_EYE_Held_"
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
ASSETS = os.path.join(ROOT, "living", "game", "assets")
STATE = os.path.join(ROOT, ".local", "held-eyes.txt")


def files_of(tokens, assets=ASSETS):
    """The character files a view's tokens name."""
    out = []
    book = None
    for t in [x.strip() for x in tokens.split(",") if x.strip()] if isinstance(tokens, str) else tokens:
        if t.startswith("recipe:"):
            name = t[len("recipe:"):]
            if book is None:
                p = os.path.join(assets, "characters", "recipes.json")
                book = {r["name"]: r for r in json.load(open(p)).get("recipes", [])} if os.path.exists(p) else {}
            base = book.get(name, {}).get("base")
            if base:
                out.append(os.path.join(assets, base))
            continue
        p = t if os.path.isabs(t) else os.path.join(assets, t)
        if os.path.isdir(p):
            out += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith((".glb", ".vrm"))]
        elif os.path.exists(p):
            out.append(p)
    # The game draws a character's animated copy when there is one (`anim/<name>.glb` beside it):
    # that is the file whose eyes blink, so it is held with the file named.
    both = []
    for f in out:
        both.append(f)
        anim = os.path.join(os.path.dirname(f), "anim", os.path.basename(f))
        if os.path.exists(anim):
            both.append(anim)
    return [f for f in dict.fromkeys(both) if f.endswith((".glb", ".vrm"))]


def _swap(path, old, new):
    """Replace `old` by `new` (the same length) in a binary glTF's JSON chunk. True if it changed."""
    with open(path, "r+b") as f:
        head = f.read(20)
        if len(head) < 20 or head[:4] != b"glTF" or head[16:20] != b"JSON":
            return False
        n = struct.unpack("<I", head[12:16])[0]
        text = f.read(n)
        if old not in text:
            return False
        f.seek(20)
        f.write(text.replace(old, new))
    return True


def _state(add=(), drop=()):
    have = [l.strip() for l in open(STATE)] if os.path.exists(STATE) else []
    have = [p for p in dict.fromkeys(have + list(add)) if p and p not in set(drop)]
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    if have:
        open(STATE, "w").write("\n".join(have) + "\n")
    elif os.path.exists(STATE):
        os.remove(STATE)
    return have


def hold(tokens, assets=ASSETS):
    """Hold the eyes of every file the tokens name. Returns the files changed."""
    done = []
    for p in files_of(tokens, assets):
        if _swap(p, OPEN, HELD):
            done.append(os.path.abspath(p))
            _state(add=[done[-1]])
    return done


def release(files=None):
    """Give the files their blink back (every file still listed, when none are named)."""
    files = _state() if files is None else list(files)
    for p in files:
        if os.path.exists(p):
            _swap(p, HELD, OPEN)
    _state(drop=files)
    return files


@contextlib.contextmanager
def held(tokens, assets=ASSETS):
    """Eyes held open for the length of a `with` block, unless LIVING_VIEW_BLINK=1."""
    if os.environ.get("LIVING_VIEW_BLINK") == "1":
        yield []
        return
    release()  # whatever a killed run left
    files = hold(tokens, assets)
    try:
        yield files
    finally:
        release(files)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("hold", "release"):
        sys.exit(__doc__)
    if sys.argv[1] == "hold":
        release()
        print("\n".join(hold(",".join(sys.argv[2:]))))
    else:
        release(sys.argv[2:] or None)


if __name__ == "__main__":
    main()
