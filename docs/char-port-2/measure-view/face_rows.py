#!/usr/bin/env python3
"""S7's face/eye gap, taken apart with the measuring view (README.md): one type drawn in the bind pose at the old
perspective portrait (level and 8° up) and in the orthographic measuring view, measured by S6b's 2D rule
(drawing_spread.face_render: the cheek row's skin run, ears masked by the ear-ID copy, over the eye spacing), and the
type file cut in 3D (S6b's measure3d: the whole skin cut, ears excluded) at the same heights.

    python3 face_rows.py OUT --binary BIN --type adult-f-b --ear-glb EAR.glb [--hair bob_none] [--frame-m 0.6 --y 1.45]

The type's ear-ID copy (s6b/ear_id.py) must be installed as `lookdev/types/<type>.glb` and the no-hair style
(s6/part_id.py --none) as `lookdev/styles/hair/<hair>.glb` in the binary's asset tree; EAR.glb is that same ear-ID
file (the 3D cut reads it). Needs numpy and Pillow. Writes OUT/face_rows.json.

Two rows:
- **the 2D rule's row:** CHEEK_DROP_H x eye spacing / EYE_SPACING_H under the eyes (drawing_spread.cheek_at), a drop
  set by the drawing's proportions;
- **the 3D rule's row:** 30 mm under the irises in the type file's own metres (s6b/face_width.py).
The view draws the type at the line's height, so a file metre is `scale` view metres: the eye spacing on the
orthographic frame (m, from its recorded pixels per metre) over the file's. The eye line's height on the frame against
the file's eye height checks that scale independently.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "docs/char-port-2/s6"), str(ROOT / "docs/char-port-2/s6b"), str(ROOT / "living/tools"), str(ROOT / "living/tools/characters")]
import drawing_spread as D  # noqa: E402
import face_width  # noqa: E402
import look_lines  # noqa: E402
import measure3d as M  # noqa: E402

PORTRAITS = "0:0:0.36:0.88,0:8:0.36:0.88"


def render(out, binary, line, shots, ortho=None):
    k = look_lines.key_of(line)
    out.mkdir(parents=True, exist_ok=True)
    (out / "book.json").write_text(json.dumps(dict(generation="c4-measure-view", generations=[], lines={k: dict(person=line, words={})}, decor=[])))
    env = {x: v for x, v in os.environ.items() if not x.startswith("LIVING_GAME_")}
    env.update(LIVING_GAME_VIEW=f"look:{k}", LIVING_GAME_LOOK_BOOK=str(out / "book.json"), LIVING_GAME_VIEW_SHOTS=shots, LIVING_GAME_VIEW_OUT=str(out),
               LIVING_GAME_HOUR="11", LIVING_GAME_DAY_MINUTES="0", LIVING_GAME_FILM="soft", LIVING_GAME_SETTINGS=str(out / "settings.json"),
               LIVING_GAME_SIZE="1600x900", LIVING_GAME_VIEW_CLIP="bind", LIVING_GAME_SPRINGS="0", RUST_LOG="warn")
    if ortho:
        env.update(LIVING_GAME_VIEW_ORTHO="1", LIVING_GAME_VIEW_ORTHO_M=str(ortho[0]), LIVING_GAME_VIEW_ORTHO_Y=str(ortho[1]))
    with (out / "client.log").open("w") as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
    return sorted(p for p in out.rglob("*.png") if ".face." not in p.name and ".rows." not in p.name)


def skin_run(png, box, row):
    """drawing_spread's skin and eyes on the frame, and the run's width (px) on a fractional row, linear between the
    two rows round it."""
    a = np.asarray(Image.open(png).convert("RGB").crop(box)).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    skin = (r > g + 12) & (r > b + 25) & ~D.ears_of(a)
    (ya, xa), (yb, xb) = D.two_eyes((g > r + 8) & (g > b))
    eye_y, spacing, cx = (ya + yb) / 2, abs(xa - xb), int(round((xa + xb) / 2))

    def run(rr):
        x0 = x1 = cx
        while x0 > 0 and skin[rr, x0 - 1]:
            x0 -= 1
        while x1 < a.shape[1] - 1 and skin[rr, x1 + 1]:
            x1 += 1
        return x1 - x0

    if row is None:
        return eye_y, spacing, None
    r0 = int(np.floor(row))
    f = row - r0
    return eye_y, spacing, (1 - f) * run(r0) + f * run(r0 + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--type", default="adult-f-b")
    ap.add_argument("--ear-glb", type=Path, required=True)
    ap.add_argument("--hair", default="bob_none")
    ap.add_argument("--frame-m", type=float, default=0.60)
    ap.add_argument("--y", type=float, default=1.45)
    a = ap.parse_args()
    t = a.type
    female = "-f-" in t or t.startswith("child")
    line = dict(type=t, height=1.25 if t.startswith("child") else 1.64, colors=dict(hair="#662e1a", skin="#e8bca3", eyes="#4f7a4f"),
                styles=dict(hair=a.hair, outfit=["jersey-f", "trousers-f", "boots-f"] if female else ["jersey-m", "trousers-m", "boots-m"], overlays=[]))
    res = dict(type=t, line=line, frame_m=a.frame_m, frame_middle_y_m=a.y)
    # The 2D rule as S7 ran it, on both portraits and the orthographic frame.
    for p in render(a.out / "portrait", a.binary, line, PORTRAITS):
        r, pic = D.face_render(p)
        pic.save(p.with_name(p.stem + ".face.png"))
        res[f"portrait {p.stem}"] = r
    o = render(a.out / "ortho", a.binary, line, "front", ortho=(a.frame_m, a.y))[0]
    j = json.loads(o.with_suffix(".ortho.json").read_text())
    k, ground = j["px_per_m"], j["ground_row_px"]
    # A box like face_render's, round the face: 400 px wide, the eyes 250 px from its top.
    eye_y_abs = None
    box = (600, 140, 1000, 620)
    r, pic = D.face_render(o, box=box)
    pic.save(o.with_name(o.stem + ".face.png"))
    eye_y_abs = r["eye_line_px"] + box[1]
    res["ortho rule"] = dict(r, projection=j)
    # The file in 3D (its own metres) and the view's scale.
    P, T, iris = M.face(str(a.ear_glb))
    eye3, sp3 = M.eyes(iris)
    face = T[~M.ear_triangles(P, T)]
    _, sp2, _ = skin_run(o, box, None)
    scale = sp2 / k / sp3
    eye_h_view = (ground - eye_y_abs) / k
    res["scale"] = dict(view_m_per_file_m=scale, by_eye_height=eye_h_view / eye3, eye_spacing_view_m=sp2 / k, eye_spacing_file_m=sp3,
                        eye_height_view_m=eye_h_view, eye_height_file_m=eye3)
    rows = {"3D rule (30 mm under the irises, file)": face_width.CHEEK_DROP,
            "2D rule (drawing's ratio)": D.CHEEK_DROP_H * (sp2 / D.EYE_SPACING_H) / k / scale}
    res["rows"] = {}
    im = Image.open(o).convert("RGB")
    d = ImageDraw.Draw(im)
    for (name, drop), colour in zip(rows.items(), [(0, 200, 0), (0, 90, 255)]):
        row_abs = eye_y_abs + drop * scale * k
        _, _, w2 = skin_run(o, box, row_abs - box[1])
        w3 = M.width(P, face, eye3 - drop)
        res["rows"][name] = dict(drop_file_mm=round(drop * 1000, 2), drop_view_mm=round(drop * scale * 1000, 2), row_px=round(row_abs, 1),
                                 height_view_m=round((ground - row_abs) / k, 5),
                                 ortho_2d=round(w2 / sp2, 3), ortho_2d_width_file_mm=round(w2 / k / scale * 1000, 1),
                                 cut_3d=round(w3 / sp3, 3), cut_3d_width_mm=round(w3 * 1000, 1), ortho_over_3d=round(w2 / sp2 / (w3 / sp3) - 1, 4))
        d.line((600, row_abs, 1000, row_abs), fill=colour, width=1)
    im.crop((560, 220, 1040, 520)).save(a.out / "rows.png")
    (a.out / "face_rows.json").write_text(json.dumps(res, indent=1, default=float))
    for n in [x for x in res if x.startswith("portrait") or x == "ortho rule"]:
        print(n, res[n]["face_over_eyes"])
    print("scale", res["scale"])
    for n, v in res["rows"].items():
        print(n, v)


if __name__ == "__main__":
    main()
