#!/usr/bin/env python3
"""Known-answer test for must-fix 1's measure (eye_id.py, eye_count.py; docs/char-port-2/PLAN.md §7).
- **eye_count:** synthetic frames of skin (and the ground's green, which must not count): an open eye of known area in
  cyan, lit and shaded; a closed eye (none); a sliver above a lid (a known 3 x 40 px band).
- **eye_id:** a synthetic file with `Face`'s eye white and iris primitives and a `Fcl_EYE_Joy` key: both primitives
  moved to the plain material in cyan, the key held, the rest of the file as it was.
Exit status 1 on any failure.
    python3 eye_count_selftest.py
"""
import json
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "living/tools")]
import eye_count  # noqa: E402
import eye_id  # noqa: E402
from merge_primitives import read_glb  # noqa: E402


def frame(d, name, paint):
    a = np.tile(np.array((232, 182, 152), np.uint8), (200, 300, 1))
    a[150:, :] = (110, 150, 90)  # the ground's green
    paint(a)
    p = Path(d) / name
    Image.fromarray(a).save(p)
    return p


def glb(path):
    """A minimal file: node Face with three primitives (skin, eye white, iris), each a triangle with one target."""
    blob, views, accs, prims = bytearray(), [], [], []
    for mat in range(3):
        for data, kind, ctype, cnt in ((np.zeros((3, 3), np.float32).tobytes(), "VEC3", 5126, 3), (np.array([0, 1, 2], np.uint32).tobytes(), "SCALAR", 5125, 3), (np.zeros((3, 3), np.float32).tobytes(), "VEC3", 5126, 3)):
            views.append(dict(buffer=0, byteOffset=len(blob), byteLength=len(data)))
            blob += data
            acc = dict(bufferView=len(views) - 1, componentType=ctype, count=cnt, type=kind)
            if kind == "VEC3":
                acc.update(min=[0, 0, 0], max=[0, 0, 0])
            accs.append(acc)
        prims.append(dict(attributes=dict(POSITION=len(accs) - 3), indices=len(accs) - 2, material=mat, targets=[dict(POSITION=len(accs) - 1)]))
    mats = [dict(name="M00_000_00_Face_00_SKIN"), dict(name=eye_id.PARTS[0]), dict(name=eye_id.PARTS[1]), dict(name=eye_id.PLAIN)]
    j = dict(asset=dict(version="2.0"), scene=0, scenes=[dict(nodes=[0])], nodes=[dict(name="Face", mesh=0)], meshes=[dict(primitives=prims, extras=dict(targetNames=["Fcl_EYE_Joy"]))],
             materials=mats, accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(blob))])
    js = json.dumps(j).encode()
    js += b" " * (-len(js) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


def main():
    checks = []
    with tempfile.TemporaryDirectory() as d:
        def open_eye(a):
            a[60:80, 100:140] = (0, 255, 255)
            a[80:90, 100:140] = (0, 150, 150)  # shaded
        def sliver(a):
            a[60:63, 100:140] = (20, 200, 210)
        checks += [("open eye, lit and shaded", eye_count.count(frame(d, "open.png", open_eye))["eye_px"], 30 * 40),
                   ("closed eye", eye_count.count(frame(d, "closed.png", lambda a: None))["eye_px"], 0),
                   ("a sliver above the lid", eye_count.count(frame(d, "sliver.png", sliver))["eye_px"], 3 * 40),
                   ("the sliver's rows", tuple(eye_count.count(frame(d, "sliver2.png", sliver))["rows"]), (60, 62))]
        src, out = Path(d) / "in.glb", Path(d) / "out.glb"
        glb(src)
        eye_id.main(src, out, "Fcl_EYE_Joy")
        j, _ = read_glb(out)
        pr = j["meshes"][0]["primitives"]
        checks += [("eye_id: eye white and iris on the plain material", [j["materials"][p["material"]]["name"] for p in pr[1:]], [eye_id.PLAIN] * 2),
                   ("eye_id: the skin left as it was", j["materials"][pr[0]["material"]]["name"], "M00_000_00_Face_00_SKIN"),
                   ("eye_id: the key held", j["meshes"][0]["weights"], [1.0]),
                   ("eye_id: cyan on the eye", "COLOR_0" in pr[1]["attributes"] and "COLOR_0" in pr[2]["attributes"] and "COLOR_0" not in pr[0]["attributes"], True)]
    bad = 0
    for label, got, want in checks:
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {got} (known {want})")
    print("eye_count_selftest:", "PASS" if not bad else f"{bad} FAILED")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
