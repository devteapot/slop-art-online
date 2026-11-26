#!/usr/bin/env python3
"""The face and hair measures against the drawing in the measuring view (the GC's acceptance, 2026-11-21: bind,
level, orthographic, `LIVING_GAME_VIEW_ORTHO=1` with `LIVING_GAME_VIEW_CLIP=bind`; the outline and ink on, as in
play), with the cheek row by landmarks (drawing_spread.ROW_FRACTION of the eye line to the chin; the chin from a
chin-ID frame, chin_id.py), and the type file cut in 3D at the same row.

    python3 ortho_measure.py draw OUT --binary BIN --hair NOSTYLE --kind face|chin TYPE [TYPE ...]
        # one front frame per type with whatever type files are installed (the ear-ID or the chin-ID copies)
    python3 ortho_measure.py face OUT FACE_DIR CHIN_DIR EARID_DIR [TYPE ...]
        # the 2D measure on each type's two frames, and the 3D cut of its ear-ID file at the same row
    python3 ortho_measure.py hair OUT --binary BIN --style STYLE --id IDSTYLE --none NOSTYLE --kind look|id|none|chin
    python3 ortho_measure.py spread OUT     # the hair measure on OUT/{look,id,none,chin}

**The frame:** 1600x900, `LIVING_GAME_VIEW_ORTHO_M` 0.75 (1200 px/m), its middle 0.04 m under the eye line (the eye
line from the type file's eyes and the line's height over the file's standing height), measured in the box
(550, 140, 1050, 640). 11:00, soft film, springs off; the composed person as face2d.py and image_spread.py have it.

**The same row in 3D:** the frame's pixels per metre and ground row (its `.ortho.json`) give the row's height in view
metres; the view draws the file at a uniform scale about the ground, the eye spacing on the frame over the file's
(as docs/char-port-2/measure-view/face_rows.py); the file is cut there (measure3d.width, ears excluded). Reported
beside it: the 3D cut at the 3D landmark row (eye line to measure3d.chin, by ROW_FRACTION), and the 2D chin and eye
line against the file's, through the same scale.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "docs/char-port-2/s6"), str(ROOT / "docs/char-port-2/s6b"), str(ROOT / "living/tools/characters")]
import drawing_spread as D  # noqa: E402
import look_lines  # noqa: E402
import measure3d as M  # noqa: E402

FRAME_M = 0.75
BOX = (550, 140, 1050, 640)
FILE_HEIGHT = 1.797  # a type file's standing height (adult-f-b's eye line 1.6365 at the view's 0.9128 for a 1.64 line)


def line_of(t, hair):
    female = "-f-" in t or t.startswith("child")
    return dict(type=t, height=1.25 if t.startswith("child") else 1.64, colors=dict(hair="#662e1a", skin="#e8bca3", eyes="#4f7a4f"),
                styles=dict(hair=hair, outfit=["jersey-f", "trousers-f", "boots-f"] if female else ["jersey-m", "trousers-m", "boots-m"], overlays=[]))


def draw(out, binary, line, middle):
    k = look_lines.key_of(line)
    out.mkdir(parents=True, exist_ok=True)
    (out / "book.json").write_text(json.dumps(dict(generation="c4-s7ortho", generations=[], lines={k: dict(person=line, words={})}, decor=[])))
    env = {x: v for x, v in os.environ.items() if not x.startswith("LIVING_GAME_")}
    env.update(LIVING_GAME_VIEW=f"look:{k}", LIVING_GAME_LOOK_BOOK=str(out / "book.json"), LIVING_GAME_VIEW_SHOTS="front", LIVING_GAME_VIEW_OUT=str(out),
               LIVING_GAME_HOUR="11", LIVING_GAME_DAY_MINUTES="0", LIVING_GAME_FILM="soft", LIVING_GAME_SETTINGS=str(out / "settings.json"),
               LIVING_GAME_SIZE="1600x900", LIVING_GAME_VIEW_CLIP="bind", LIVING_GAME_SPRINGS="0", RUST_LOG="warn",
               LIVING_GAME_VIEW_ORTHO="1", LIVING_GAME_VIEW_ORTHO_M=str(FRAME_M), LIVING_GAME_VIEW_ORTHO_Y=f"{middle:.4f}")
    (out / "pose.txt").write_text("bind ortho\n")
    with (out / "client.log").open("w") as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
    return frame(out)


def frame(d):
    return sorted(p for p in Path(d).rglob("*.png") if ".face." not in p.name)[0]


def middle_of(t, types_dir):
    _, _, iris = M.face(str(Path(types_dir) / f"{t}.glb"))
    return M.eyes(iris)[0] * line_of(t, "x")["height"] / FILE_HEIGHT - 0.04


def face(out, face_dir, chin_dir, earid_dir, types):
    res = {}
    for t in types:
        f, c = frame(Path(face_dir) / t), frame(Path(chin_dir) / t)
        r, pic = D.face_render(f, box=BOX, chin_frame=c)
        pic.save(Path(out) / f"{t}.measured.png")
        j = json.loads(f.with_suffix(".ortho.json").read_text())
        k, ground = j["px_per_m"], j["ground_row_px"]
        P, T, iris = M.face(str(Path(earid_dir) / f"{t}.glb"))
        eye3, sp3 = M.eyes(iris)
        chin3 = M.chin(P, iris)
        skin = T[~M.ear_triangles(P, T)]
        scale = r["eye_spacing_px"] / k / sp3
        to_file = lambda row: (ground - (row + BOX[1])) / k / scale  # noqa: E731
        h2 = to_file(r["cheek_row"])
        h3 = eye3 - D.ROW_FRACTION * (eye3 - chin3)
        res[t] = dict(pose="bind", view="ortho", rule=r["row_rule"], face_over_eyes_2d=r["face_over_eyes"], cut_3d_same_row=round(M.width(P, skin, h2) / sp3, 3),
                      cut_3d_landmark_row=round(M.width(P, skin, h3) / sp3, 3), row_file_m=round(h2, 4), row_3d_landmark_file_m=round(h3, 4),
                      chin_2d_file_m=round(to_file(r["chin_row"]), 4), chin_3d_file_m=round(chin3, 4), eye_2d_file_m=round(to_file(r["eye_line_px"]), 4), eye_3d_file_m=round(eye3, 4),
                      eye_spacing_px=r["eye_spacing_px"], px_per_m=k, scale=round(scale, 4), ear_on_cheek_row=r["ear_on_cheek_row"], row_fraction=r["row_fraction"])
        x = res[t]
        print(t, "pose bind ortho", x["face_over_eyes_2d"], "3D same row", x["cut_3d_same_row"], "3D landmark row", x["cut_3d_landmark_row"],
              f"chin 2D-3D {1000 * (x['chin_2d_file_m'] - x['chin_3d_file_m']):+.1f} mm, eye {1000 * (x['eye_2d_file_m'] - x['eye_3d_file_m']):+.1f} mm", flush=True)
    Path(out, "face.json").write_text(json.dumps(res, indent=1))


def spread(out):
    out = Path(out)
    r, pic = D.render(frame(out / "look"), frame(out / "id"), box=BOX, face=frame(out / "none"), chin_frame=frame(out / "chin"))
    pic.save(out / "spread.png")
    drawn = json.loads((ROOT / "docs/char-port-2/s6/spread/spread.json").read_text())["drawing"]
    lo, hi = drawn["band"]
    res = dict(pose="bind", view="ortho", rule=r["row_rule"], **{k: r[k] for k in ("body_over_eyes", "whole_over_eyes", "body", "hair_width_px", "body_width_px", "cheek_width_px", "eye_spacing_px", "chin_row", "cheek_row", "row_fraction")},
               band=[lo, hi], within=lo <= r["body_over_eyes"] <= hi)
    (out / "spread.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res))


def main():
    a = sys.argv[1:]
    if a[0] == "draw":
        out, binary, hair, kind, types = Path(a[1]), a[a.index("--binary") + 1], a[a.index("--hair") + 1], a[a.index("--kind") + 1], a[a.index("--kind") + 2:]
        for t in types:
            f = draw(out / kind / t, binary, line_of(t, hair), middle_of(t, ROOT / "living/game/assets/lookdev/types"))
            print(t, kind, f, flush=True)
    elif a[0] == "face":
        face(a[1], a[2], a[3], a[4], a[5:])
    elif a[0] == "hair":
        out, binary, kind = Path(a[1]), a[a.index("--binary") + 1], a[a.index("--kind") + 1]
        style = dict(look=a[a.index("--style") + 1], id=a[a.index("--id") + 1], none=a[a.index("--none") + 1], chin=a[a.index("--none") + 1])[kind]
        line = dict(type="adult-f-b", height=1.64, colors=dict(hair="#662e1a", skin="#e8bca3", eyes="#4f7a4f"), styles=dict(hair=style, outfit=["jersey-f", "trousers-f", "boots-f"], overlays=[]))
        print(kind, draw(out / kind, binary, line, middle_of("adult-f-b", ROOT / "living/game/assets/lookdev/types")))
    elif a[0] == "spread":
        spread(a[1])


if __name__ == "__main__":
    main()
