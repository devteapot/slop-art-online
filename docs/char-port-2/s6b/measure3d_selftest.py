#!/usr/bin/env python3
"""Known-answer test for S6b's 3D measures (face_width.py, jaw.py, ears.py; the rule in docs/char-port-2/PLAN.md:
a measuring tool passes a known-answer test before its numbers are used).

Synthetic face files, written to a scratch folder and measured by the tools' own functions:
- **the head:** level rings, 64 points round, from the chin up; each ring an ellipse whose half-width runs linearly
  between known heights (WIDTH), so any level cut has a known width;
- **the irises:** two small discs a known spacing apart, at the eye line, 12 mm behind the face's front (as an eye sits in its socket: measure3d.chin needs it);
- **the ears:** two boxes of known size and height, their own pieces of the skin, standing out past the face and
  sunk 2 mm into it, as the generator's ears are. One case puts an ear across the cheek row (where the first
  face_width.py counted it as face); one has the ears above it. Each ear's vertices touch none of the head's.
- **features:** a nose (a wedge on the midline, part of the head's piece), which must not enter the width.

Each tool must return the known answer to 0.001 (ratios) or 0.1 mm. Exit status 1 on any failure.
    python3 measure3d_selftest.py
"""
import json
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import measure3d as M  # noqa: E402
import face_width  # noqa: E402
import ears  # noqa: E402
import jaw  # noqa: E402
import ear_id  # noqa: E402
from merge_primitives import read_glb, read_accessor  # noqa: E402

CHIN, H = 1.535, 0.24
EYE = CHIN + 0.40 * H                         # the eye line
SPACING = 0.096                               # iris centre to iris centre
# (height over the chin in H, half-width in m): linear between, the head's outline from the front
WIDTH = [(0.0, 0.010), (0.04, 0.030), (0.10, 0.045), (0.20, 0.060), (0.30, 0.075), (0.45, 0.080), (0.75, 0.078), (1.0, 0.030)]
DEPTH = 0.100                                 # every ring's half-depth: the front's midline lies at z = -DEPTH


def half(y):
    return float(np.interp((y - CHIN) / H, [a for a, _ in WIDTH], [b for _, b in WIDTH]))


def box(x0, x1, y0, y1, z0, z1):
    v = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    q = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return np.array(v, float), [t for a, b, c, d in q for t in ((a, b, c), (a, c, d))]


def head_file(path, ear_top, ear_bottom, ear_out):
    """A face file: head rings, a nose, two ears (top/bottom over/under the eye line, m; standing ear_out past the
    face's half-width at the eye line), irises. Returns the known answers."""
    ys = sorted({CHIN + k * 0.005 for k in range(int(H / 0.005) + 1)} | {CHIN + a * H for a, _ in WIDTH})
    th = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    V, T = [], []
    for y in ys:
        V += [(half(y) * np.cos(t), y, DEPTH * np.sin(t)) for t in th]
    n = len(th)
    for r in range(len(ys) - 1):
        for i in range(n):
            a, b, c, d = r * n + i, r * n + (i + 1) % n, (r + 1) * n + (i + 1) % n, (r + 1) * n + i
            T += [(a, b, c), (a, c, d)]
    # The nose: a wedge on the midline's front, joined to the ring points it stands on.
    k = int(np.argmin([abs(y - (EYE - 0.03)) for y in ys]))
    front = int(np.argmin([abs(t - 1.5 * np.pi) for t in th]))
    V.append((0.0, ys[k], -DEPTH - 0.02))
    tip = len(V) - 1
    T += [(k * n + front - 1, k * n + front, tip), (k * n + front, k * n + front + 1, tip), ((k + 1) * n + front, k * n + front, tip)]
    V = np.array(V, float)
    T = np.array(T, int)
    hw = half(EYE)
    parts_v, parts_t = [V], [T]
    for s in (-1, 1):
        ev, et = box(s * (hw - 0.002), s * (hw + ear_out), EYE - ear_bottom, EYE + ear_top, -0.01, 0.02)
        parts_t.append(np.array(et) + sum(len(p) for p in parts_v))
        parts_v.append(ev)
    P = np.vstack(parts_v)
    Tall = np.vstack(parts_t)
    iris = []
    for s in (-1, 1):
        iris += [(s * SPACING / 2 + 0.006 * np.cos(t), EYE + 0.006 * np.sin(t), -DEPTH + 0.012) for t in np.linspace(0, 2 * np.pi, 16, endpoint=False)]
    write(path, P, Tall, np.array(iris, float))
    cheek = EYE - 0.030
    covers = EYE - ear_bottom <= cheek <= EYE + ear_top
    E = EYE - CHIN
    return dict(ears_excluded=round(2 * half(cheek) / SPACING, 3),
                with_ears=round(2 * (hw + ear_out if covers else half(cheek)) / SPACING, 3),
                jaw=[round(2 * half(CHIN + r * H) * 1000, 1) for r in jaw.ROWS],
                ear=dict(top=round(ear_top / E, 3), bottom=round(ear_bottom / E, 3), height=round((ear_top + ear_bottom) / E, 3)))


def write(path, P, T, iris):
    """A minimal glTF: one node `Face`, two primitives (skin, irises) with the files' material names."""
    blob = bytearray()
    views, accs, prims = [], [], []
    for mat, pos, idx in ((0, P, T), (1, iris, np.array([(0, i, i + 1) for i in range(1, len(iris) - 1)], int))):
        for data, kind, ctype, count in ((pos.astype(np.float32).tobytes(), "VEC3", 5126, len(pos)), (idx.astype(np.uint32).ravel().tobytes(), "SCALAR", 5125, idx.size)):
            views.append(dict(buffer=0, byteOffset=len(blob), byteLength=len(data)))
            blob += data
            acc = dict(bufferView=len(views) - 1, componentType=ctype, count=count, type=kind)
            if kind == "VEC3":
                acc.update(min=pos.min(0).tolist(), max=pos.max(0).tolist())
            accs.append(acc)
        prims.append(dict(attributes=dict(POSITION=len(accs) - 2), indices=len(accs) - 1, material=mat))
    j = dict(asset=dict(version="2.0"), scene=0, scenes=[dict(nodes=[0])], nodes=[dict(name="Face", mesh=0)], meshes=[dict(primitives=prims)],
             materials=[dict(name=M.SKIN), dict(name=M.IRIS), dict(name=ear_id.PLAIN)], accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(blob))])
    js = json.dumps(j).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


def main():
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        for name, top, bottom, out in (("ears across the cheek row", 0.020, 0.045, 0.012), ("ears above the cheek row", 0.030, 0.020, 0.012)):
            f = Path(d) / "case.glb"
            want = head_file(f, top, bottom, out)
            got = dict(face_width.measure(f), jaw=jaw.widths(f, H), ear=ears.measure(f))
            checks = [("face_width ears excluded", got["ears_excluded"], want["ears_excluded"], 0.001), ("face_width with ears", got["with_ears"], want["with_ears"], 0.001)]
            checks += [(f"jaw at {r} H (mm)", g, w, 0.1) for r, g, w in zip(jaw.ROWS, got["jaw"], want["jaw"])]
            for side in "LR":
                checks += [(f"ear {side} {k}", got["ear"][side][k], want["ear"][k], 0.001) for k in ("top", "bottom", "height")]
            # ear_id.py: exactly the two ears' 24 triangles move to the plain-colour primitive, and all of them.
            out = Path(d) / "case.id.glb"
            ear_id.main(f, out)
            j, b = read_glb(out)
            pr = j["meshes"][0]["primitives"]
            moved = np.array(read_accessor(j, b, pr[-1]["indices"])[0]).reshape(-1, 3)
            pos = np.array(read_accessor(j, b, pr[-1]["attributes"]["POSITION"])[0]).reshape(-1, 3)
            checks += [("ear_id: ear triangles moved", len(moved), 24, 0), ("ear_id: all outside the face's side less 2 mm", int((np.abs(pos[moved.ravel(), 0]) >= half(EYE) - 0.002 - 1e-6).all()), 1, 0),
                       ("ear_id: material", j["materials"][pr[-1]["material"]]["name"] == ear_id.PLAIN, True, 0)]
            for label, g, w, tol in checks:
                ok = abs(g - w) <= tol + 1e-9
                bad += not ok
                print(f"{'ok  ' if ok else 'FAIL'} {name}: {label}: {g} (known {w})")
    print("measure3d_selftest:", "PASS" if not bad else f"{bad} FAILED")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
