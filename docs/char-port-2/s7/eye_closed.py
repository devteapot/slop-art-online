#!/usr/bin/env python3
"""Must-fix 1's run (char-port-2 S7): for each person file (lookdev/own-NAME.glb) and each key that closes an eye, an
eye-ID copy with the key held (eye_id.py) drawn by the asset view at the close front and three-quarter, and its eye
pixels counted (eye_count.py). The open eye too, as the control: its count must not be 0. Copies are removed after.

    python3 eye_closed.py OUT --binary BIN NAME [NAME ...]

Writes OUT/eyes.json: {name: {key: {shot: {eye_px, rows}}}}. Known-answer test: eye_count_selftest.py.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "living/tools/characters"), str(HERE.parents[2] / "living/tools")]
import calibrate as C  # noqa: E402
import eye_count  # noqa: E402
import eye_id  # noqa: E402

KEYS = (None, "Fcl_EYE_Close", "Fcl_EYE_Close_L", "Fcl_EYE_Close_R", "Fcl_EYE_Joy")
SHOTS = ("0:8:0.18:0.86", "-35:8:0.18:0.86")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--binary", required=True)
    ap.add_argument("names", nargs="+")
    a = ap.parse_args()
    res = {}
    for name in a.names:
        stem = f"lookdev/own-{name}"
        for key in KEYS:
            tag = "-eye" + ("open" if key is None else key.replace("Fcl_EYE_", "").lower())
            copy = C.ASSETS / f"{stem}{tag}.glb"
            eye_id.main(C.ASSETS / f"{stem}.glb", copy, key)
            sides = []
            for f in sorted((C.ASSETS / stem).parent.glob(Path(stem).name + ".*")):
                side = f.name[len(Path(stem).name):]
                if side.endswith((".png", ".ktx2")):
                    shutil.copyfile(f, C.ASSETS / (stem + tag + side))
                    sides.append(C.ASSETS / (stem + tag + side))
            try:
                got = C.run_frame(f"{stem}{tag}.glb", a.binary, a.out / f"{name}{tag}", list(SHOTS))
                res.setdefault(name, {})[key or "open"] = {s: dict(eye_count.count(got[s]), still=str(got[s])) for s in SHOTS if s in got}
            finally:
                copy.unlink()
                for f in sides:
                    f.unlink()
            print(name, key or "open", {s: v["eye_px"] for s, v in res[name][key or "open"].items()}, flush=True)
    (a.out / "eyes.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
