#!/usr/bin/env python3
"""The S6 spread acceptance (the GC's choice after step 3): a hair style's image spread, measured
as drawing_spread.py measures Cora's drawing, on the game's front portrait, in a still pose.

    python3 image_spread.py OUT --binary BIN --style STYLE --id IDSTYLE --none NOSTYLE

STYLE is the style to look at, IDSTYLE its all-hair ID copy (part_id.py --all) and NOSTYLE a copy
that draws no hair (part_id.py --none), all installed in the asset tree. Each is drawn on a
composed woman in auburn (back_views.py's) at the front portrait (`0:8:0.36:0.88`, 1600x900,
11:00, soft film, springs off), 2.0 s into the idle clip: a moment the head is square to the
camera. The clip turns and sways the head: at its start the face stands 10 px off the skull's
middle and an ear shows, and from 0.9 s on it is within half a pixel (measured on a face with no
hair, every 0.1 s to 3.4 s); 1.8 to 3.1 s is its steadiest. One moment, named, so every run takes
the same pose: the view's pose without a clip is whatever moment its photograph lands on.

**The measure** (drawing_spread.render): the face (the eyes, the chin, the cheek row and its
width) from the frame with no hair, so a lock over a cheek or an eye cannot move it; the hair from
the ID's green; the hair's whole width and its body width above the chin, as on the drawing.
Writes OUT/spread.json (the acceptance: body 1.82 ± 0.10, the drawing's).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "living/tools/characters")]
import drawing_spread  # noqa: E402
import look_lines  # noqa: E402

SHOT = "idle@2.0/0:8:0.36:0.88"


def render(out, binary, style):
    line = dict(type="adult-f-b", height=1.64, colors=dict(hair="#662e1a", skin="#e8bca3", eyes="#4f7a4f"), styles=dict(hair=style, outfit=["jersey-f", "trousers-f", "boots-f"], overlays=[]))
    k = look_lines.key_of(line)
    out.mkdir(parents=True, exist_ok=True)
    (out / "book.json").write_text(json.dumps(dict(generation="c4-s6back01", generations=[], lines={k: dict(person=line, words={})}, decor=[])))
    env = {x: v for x, v in os.environ.items() if not x.startswith("LIVING_GAME_")}
    env.update(LIVING_GAME_VIEW=f"look:{k}", LIVING_GAME_LOOK_BOOK=str(out / "book.json"), LIVING_GAME_VIEW_SHOTS=SHOT,
               LIVING_GAME_VIEW_OUT=str(out), LIVING_GAME_HOUR="11", LIVING_GAME_DAY_MINUTES="0", LIVING_GAME_FILM="soft", LIVING_GAME_SETTINGS=str(out / "settings.json"),
               LIVING_GAME_SIZE="1600x900", LIVING_GAME_VIEW_CLIP="idle", LIVING_GAME_SPRINGS="0", RUST_LOG="warn")
    with (out / "client.log").open("w") as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
    return sorted(p for p in out.rglob("*.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--style", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--none", required=True)
    a = ap.parse_args()
    look = render(a.out / "look", a.binary, a.style)[0]
    idp = render(a.out / "id", a.binary, a.id)[0]
    face = render(a.out / "none", a.binary, a.none)[0]
    r, pic = drawing_spread.render(look, idp, face=face)
    pic.save(a.out / "spread.png")
    res = dict(style=a.style, **{k: r[k] for k in ("spread_face", "body", "hair_width_px", "body_width_px", "cheek_width_px", "cheek_px", "eye_spacing_px", "chin_row", "cheek_row")},
               target=dict(body=1.82, tolerance=0.10), within=abs(r["body"] - 1.82) <= 0.10)
    (a.out / "spread.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("style", "spread_face", "body", "within", "hair_width_px", "body_width_px", "cheek_width_px")}))


if __name__ == "__main__":
    main()
