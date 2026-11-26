#!/usr/bin/env python3
"""S6b's acceptance render (the GC's: the 2D front-render measure, ears masked by the ID render): each type drawn as
a composed person with no hair (a `--none` copy of a hair style, part_id.py) at image_spread.py's front portrait
(`0:8:0.36:0.88`, 1600x900, 11:00, soft film, springs off), its type file the ear-ID copy (ear_id.py) installed in
its place by the caller. Prints each frame's path.

**The pose** (`--pose`, written beside each frame as pose.txt and kept by face2d_measure.py): `bind` (the default and
the acceptance's, the GC's after hair-mirror: `LIVING_GAME_VIEW_CLIP=bind`, the head square to the camera, as the
drawing is; it needs a client with the bind pose) or `idle` (S6b's first moment, 2.0 s into the idle clip, when the
clip turns the head 11-12 degrees and foreshortens the eye spacing).

    python3 face2d.py OUT --binary BIN --hair NOSTYLE [--pose bind|idle] TYPE [TYPE ...]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "living/tools/characters")]
import look_lines  # noqa: E402

SHOTS = dict(bind="0:8:0.36:0.88", idle="idle@2.0/0:8:0.36:0.88")


def render(out, binary, t, hair, pose="bind"):
    female = "-f-" in t or t.startswith("child")
    line = dict(type=t, height=1.25 if t.startswith("child") else 1.64, colors=dict(hair="#662e1a", skin="#e8bca3", eyes="#4f7a4f"),
                styles=dict(hair=hair, outfit=["jersey-f", "trousers-f", "boots-f"] if female else ["jersey-m", "trousers-m", "boots-m"], overlays=[]))
    k = look_lines.key_of(line)
    out.mkdir(parents=True, exist_ok=True)
    (out / "book.json").write_text(json.dumps(dict(generation="c4-s6bface", generations=[], lines={k: dict(person=line, words={})}, decor=[])))
    env = {x: v for x, v in os.environ.items() if not x.startswith("LIVING_GAME_")}
    env.update(LIVING_GAME_VIEW=f"look:{k}", LIVING_GAME_LOOK_BOOK=str(out / "book.json"), LIVING_GAME_VIEW_SHOTS=SHOTS[pose], LIVING_GAME_VIEW_OUT=str(out),
               LIVING_GAME_HOUR="11", LIVING_GAME_DAY_MINUTES="0", LIVING_GAME_FILM="soft", LIVING_GAME_SETTINGS=str(out / "settings.json"),
               LIVING_GAME_SIZE="1600x900", LIVING_GAME_VIEW_CLIP="bind" if pose == "bind" else "idle", LIVING_GAME_SPRINGS="0", RUST_LOG="warn")
    (out / "pose.txt").write_text(pose + "\n")
    with (out / "client.log").open("w") as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
    return sorted(p for p in out.rglob("*.png"))[0]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--hair", required=True)
    ap.add_argument("--pose", choices=("bind", "idle"), default="bind")
    ap.add_argument("types", nargs="+")
    a = ap.parse_args()
    for t in a.types:
        print(t, a.pose, render(a.out / t, a.binary, t, a.hair, a.pose), flush=True)
