#!/usr/bin/env python3
"""living/tools/blender/stable.py's primitives are the same in every Blender process
(docs/TOOLING.md, "Reproducible generators").

    python3 living/tools/stable_selftest.py [--runs 3]

Builds, in --runs separate Blender processes: stable.uvsphere at 8x5 and 16x8 (the kerchief's
knot, the mushroom caps), and the primitives found stable on 2026-11-21 (icospheres 1-3, cones with
and without caps, a cube, a convex hull of 40 seeded points). Each process prints a hash of every
result's vertices and faces in order; every run must print the same. It also prints whether the
bare bmesh.ops.create_uvsphere varied across the runs (it does, most times: that is why
stable.uvsphere exists; not a failure either way). Exits 1 when a stable result differs.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
INNER = r'''
import bmesh, hashlib, random, sys
from mathutils import Vector
sys.path.insert(0, sys.argv[sys.argv.index("--") + 1])
import stable
def h(bm):
    bm.verts.index_update(); bm.faces.index_update()
    return hashlib.sha256(repr(([tuple(round(x, 6) for x in v.co) for v in bm.verts],
                                [tuple(v.index for v in f.verts) for f in bm.faces])).encode()).hexdigest()[:12]
def t(name, fn):
    bm = bmesh.new(); fn(bm); print(f"RESULT {name} {h(bm)}"); bm.free()
t("stable.uvsphere 8x5", lambda bm: stable.uvsphere(bm, u_segments=8, v_segments=5, radius=0.017))
t("stable.uvsphere 16x8", lambda bm: stable.uvsphere(bm, u_segments=16, v_segments=8, radius=1.0))
t("raw uvsphere 16x8", lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=1.0))
for s in (1, 2, 3):
    t(f"icosphere {s}", lambda bm, s=s: bmesh.ops.create_icosphere(bm, subdivisions=s, radius=1.0))
t("cone with caps", lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=1, radius2=0.5, depth=1))
t("cone tip", lambda bm: bmesh.ops.create_cone(bm, cap_ends=False, segments=6, radius1=1, radius2=0, depth=1))
t("cube", lambda bm: bmesh.ops.create_cube(bm, size=1.0))
def hull(bm):
    r = random.Random(7)
    for _ in range(40): bm.verts.new(Vector((r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(-1, 1))))
    bmesh.ops.convex_hull(bm, input=list(bm.verts))
t("convex hull", hull)
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    runs = []
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "inner.py"
        script.write_text(INNER)
        for _ in range(a.runs):
            r = subprocess.run(["blender", "-b", "--python-exit-code", "1", "-P", str(script), "--", str(HERE / "blender")],
                               capture_output=True, text=True, timeout=300)
            res = dict(ln.split(" ", 1)[1].rsplit(" ", 1) for ln in r.stdout.splitlines() if ln.startswith("RESULT "))
            if r.returncode or not res:
                sys.exit(f"stable_selftest: blender failed: {r.stderr[-400:]}")
            runs.append(res)
    fails = 0
    for name in runs[0]:
        seen = {run[name] for run in runs}
        if name.startswith("raw "):
            print(f"note {name}: {len(seen)} distinct in {a.runs} runs (the bare op; why stable.uvsphere exists)")
            continue
        ok = len(seen) == 1
        fails += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {'the same' if ok else f'{len(seen)} distinct'} in {a.runs} runs")
    print(f"stable_selftest: {'all passed' if not fails else f'{fails} failed'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
