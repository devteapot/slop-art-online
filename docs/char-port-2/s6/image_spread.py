#!/usr/bin/env python3
"""The S6 spread acceptance (the GC's choice after step 3): a hair style's image spread, measured
as drawing_spread.py measures Cora's drawing, on the game's front portrait, in a still pose.

    python3 image_spread.py OUT --binary BIN --style STYLE --id IDSTYLE --none NOSTYLE [--pose bind|idle]

STYLE is the style to look at, IDSTYLE its all-hair ID copy (part_id.py --all) and NOSTYLE a copy
that draws no hair (part_id.py --none), all installed in the asset tree. Each is drawn on a
composed woman in auburn (back_views.py's) at the front portrait (`0:8:0.36:0.88`, 1600x900,
11:00, soft film, springs off), in one named pose, so every run takes the same pose:

- `--pose bind` (the default since hair-mirror, 2026-11-21): the view's bind pose
  (`LIVING_GAME_VIEW_CLIP=bind`: no clip, no procedural motion), the head square to the camera
  (its eyes' joints at 0.00° of yaw and roll). The arms stand out in the file's T-pose.
- `--pose idle`: 2.0 s into the idle clip, as S6 measured until hair-mirror. That moment is not
  square: the clip itself turns the head 11.4° (yaw, roll 3.7°, from the eyes' joints as drawn;
  the clip's keys give 12.3° of yaw over the spine) from about 1 s to its end, so a mirrored
  cut's two partings measure 208 and 192 px wide there, and 201 and 201 in the bind pose
  (docs/char-port-2/hair-mirror/README.md). Until hair-mirror this docstring said the face was
  within half a pixel of the skull's middle from 0.9 s; on a face with no hair the eyes' middle
  stands 12-13 px off the forehead's from 1.0 to 3.0 s.

**The measure** (drawing_spread.render): the face (the eyes, the chin, the cheek row and its
width) from the frame with no hair, so a lock over a cheek or an eye cannot move it; the hair from
the ID's green; the hair's whole width and its body width above the chin, as on the drawing.
Writes OUT/spread.json. **The acceptance** (the GC's): `body_over_eyes`, the hair body's width
over the eye spacing, within the drawing's band (docs/char-port-2/s6/spread/spread.json,
`drawing.band`: its value ± 0.10/1.82 of it). The cheek measure (`body`, over the face's width at
the cheekbones) is reported, not held.
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

# The front portrait in each pose (`--pose`): the clip's shot names its moment; the bind pose has
# no clip.
SHOTS = dict(bind=("0:8:0.36:0.88", "bind"), idle=("idle@2.0/0:8:0.36:0.88", "idle"))


def render(out, binary, style, pose="bind"):
    line = dict(type="adult-f-b", height=1.64, colors=dict(hair="#662e1a", skin="#e8bca3", eyes="#4f7a4f"), styles=dict(hair=style, outfit=["jersey-f", "trousers-f", "boots-f"], overlays=[]))
    k = look_lines.key_of(line)
    out.mkdir(parents=True, exist_ok=True)
    (out / "book.json").write_text(json.dumps(dict(generation="c4-s6back01", generations=[], lines={k: dict(person=line, words={})}, decor=[])))
    env = {x: v for x, v in os.environ.items() if not x.startswith("LIVING_GAME_")}
    shot, clip = SHOTS[pose]
    env.update(LIVING_GAME_VIEW=f"look:{k}", LIVING_GAME_LOOK_BOOK=str(out / "book.json"), LIVING_GAME_VIEW_SHOTS=shot,
               LIVING_GAME_VIEW_OUT=str(out), LIVING_GAME_HOUR="11", LIVING_GAME_DAY_MINUTES="0", LIVING_GAME_FILM="soft", LIVING_GAME_SETTINGS=str(out / "settings.json"),
               LIVING_GAME_SIZE="1600x900", LIVING_GAME_VIEW_CLIP=clip, LIVING_GAME_SPRINGS="0", RUST_LOG="warn")
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
    ap.add_argument("--pose", choices=sorted(SHOTS), default="bind")
    a = ap.parse_args()
    look = render(a.out / "look", a.binary, a.style, a.pose)[0]
    idp = render(a.out / "id", a.binary, a.id, a.pose)[0]
    face = render(a.out / "none", a.binary, a.none, a.pose)[0]
    r, pic = drawing_spread.render(look, idp, face=face)
    pic.save(a.out / "spread.png")
    drawn = json.loads((HERE / "spread/spread.json").read_text())["drawing"]
    lo, hi = drawn["band"]
    res = dict(style=a.style, pose=a.pose, **{k: r[k] for k in ("body_over_eyes", "whole_over_eyes", "spread_face", "body", "hair_width_px", "body_width_px", "cheek_width_px", "cheek_px", "eye_spacing_px", "chin_row", "cheek_row")},
               target=dict(body_over_eyes=drawn["body_over_eyes"], band=[lo, hi]), within=lo <= r["body_over_eyes"] <= hi,
               report_only=dict(body_over_cheek=r["body"], cheek_over_eyes=round(r["cheek_width_px"] / r["eye_spacing_px"], 3), drawing_body_over_cheek=drawn["body"]))
    (a.out / "spread.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("style", "body_over_eyes", "within", "body", "body_width_px", "eye_spacing_px", "cheek_width_px")}))


if __name__ == "__main__":
    main()
