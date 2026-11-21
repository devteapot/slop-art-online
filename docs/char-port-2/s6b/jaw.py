"""S6b: the three jaw lines stay distinct. The face's width with the ears left out (measure3d.ear_triangles) where
the level plane chin + r H cuts its skin triangles, at 0.08, 0.12, 0.15, 0.18 and 0.20 H; per class, the lines a/b/c
before and after. (The first version took the vertices within 3 mm of each height and showed a swap on elder-f-b at
0.15 H that is not there.) Known-answer test: measure3d_selftest.py.
    python3 jaw.py BEFORE_DIR AFTER_DIR OUT.json"""
import glob, json, os, sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]
import measure3d as M  # noqa: E402

ROWS = (0.08, 0.12, 0.15, 0.18, 0.20)


def widths(path, H):
    """The face's width in mm at each of ROWS, in head heights H (m) over the chin."""
    P, T, iris = M.face(path)
    c = M.chin(P, iris)
    face = T[~M.ear_triangles(P, T)]
    return [round(float(M.width(P, face, c + r * H) * 1000), 1) for r in ROWS]


if __name__ == "__main__":
    TY = json.load(open(Path(__file__).resolve().parents[3] / "living/tools/characters/types.json"))["types"]
    res = {}
    for lab, d in zip(("before", "after"), sys.argv[1:3]):
        for f in sorted(glob.glob(d + "/*.glb")):
            t = os.path.basename(f)[:-4]
            res.setdefault(t, {})[lab] = widths(f, TY[t]["head"]["height_m"])
    cls = {}
    for t, v in res.items():
        cls.setdefault(t[:-2], {})[t[-1]] = v
    rep = {}
    for c, L in sorted(cls.items()):
        rep[c] = {}
        for k, r in enumerate(ROWS):
            bef = [L[x]["before"][k] for x in "abc"]
            aft = [L[x]["after"][k] for x in "abc"]
            ok = lambda v: v[0] > v[1] > v[2]  # noqa: E731
            rep[c][r] = dict(before=bef, after=aft, order_before=ok(bef), order_after=ok(aft))
            print(f"{c:8s} {r:.2f} H  before {bef}  after {aft}{'' if ok(aft) or not ok(bef) else '  <-- order lost'}")
    json.dump(dict(rows_h=ROWS, classes=rep), open(sys.argv[3], "w"), indent=1)
