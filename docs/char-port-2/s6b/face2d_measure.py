#!/usr/bin/env python3
"""S6b's acceptance numbers (the GC's: the 2D front-render measure): every frame face2d.py drew (its pose kept with each number: pose.txt beside the frame; frames from before the
pose was recorded are S6b's idle), measured by
drawing_spread.face_render (its known-answer test: docs/char-port-2/s6/drawing_spread_selftest.py).

    python3 face2d_measure.py FRAMES_DIR OUT.json      # FRAMES_DIR/<type>/.../*.png
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "s6")]
import drawing_spread as D  # noqa: E402

res = {}
root = Path(sys.argv[1])
for d in sorted(p for p in root.iterdir() if p.is_dir()):
    frame = sorted(d.rglob("*.png"))[0]
    r, pic = D.face_render(frame)
    pf = d / "pose.txt"
    r = dict(pose=pf.read_text().strip() if pf.exists() else "idle", **r)
    pic.save(root / f"{d.name}.measured.png")
    res[d.name] = r
    print(d.name, f"pose {r['pose']}", r["face_over_eyes"], r["cheek_width_px"], r["eye_spacing_px"], "ear on row" if r["ear_on_cheek_row"] else "", flush=True)
Path(sys.argv[2]).write_text(json.dumps(res, indent=1))
