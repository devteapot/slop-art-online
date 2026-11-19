#!/usr/bin/env python3
"""Where every hair style's fringe ends on every face type, against that type's brows.

    python3 living/tools/characters/fringe_check.py LOOKDEV_DIR [--table] [--json OUT] [--least 1.0] [--most 6.0]

A shared hair style is one mesh for every type, and the types' brows sit at different heights.
A style's fringe hangs from a bone, `J_Hair_Fringe`, and each type's file stands that bone where
the type's own fringe line is (hair_fit.py; hair.py `fringe_line`: 3 mm above the brows' top).
This puts each style on each type the client's way, at rest: a hair vertex stands at the type's
`hair_fit` times its place in the style's file, moved by the bone's move in the type's file
times the vertex's weight on the bone. Then, over the middle of the forehead (the vertices that
stand within 2.5 cm of the middle on the standard head, the same ones on every type):

- the fringe's end: the lowest hair vertex there, and how far it is above the type's brows' top
  (styles whose hair does not come within 4.5 cm of the brows have no fringe to speak of and
  are left out);
- how far each style's end above the brows is from the same style's on the standard head (the
  head the styles are built on): a style should sit on every type's brows as it was drawn;
- how far the fringe's hair is in front of the type's face skin, looking from the front: it must
  not be behind it.

For each type it prints the lowest fringe (the fullest style's) and the spread over styles. It
fails (exit 1) if a type's lowest fringe ends less than `--least` mm above its brows' top or
more than `--most` above, if any style's end above the brows is more than `--off` mm from the
same style's on the standard head, if a fringe's vertex is behind the skin, or if a type's file
or a style's lacks the bone. On files from before the bone it reports the same measures (`--table`
with no failing, for a before and after). Plain Python and numpy.
"""

import argparse
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "blender"))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import face_types  # noqa: E402
import hair  # noqa: E402
import hair_fit  # noqa: E402
from merge_primitives import read_accessor, read_glb  # noqa: E402

BONE = hair.FRINGE_BONE
HALF = 0.025  # the middle of the forehead: this far each side of the middle
REACH = 0.045  # hair over the forehead that comes this near the brows' top is a fringe


def style(path):
    """A style file's `Hair` mesh: positions, and each vertex's weight on the fringe's bone (None without the bone)."""
    j, binary = read_glb(path)
    node = next((n for n in j["nodes"] if n.get("name") == "Hair" and "mesh" in n), None)
    if node is None:
        return None
    joints = [j["nodes"][i].get("name") for i in j["skins"][node["skin"]]["joints"]]
    pos, share = [], []
    for p in j["meshes"][node["mesh"]]["primitives"]:
        v = np.array(read_accessor(j, binary, p["attributes"]["POSITION"])[0]).reshape(-1, 3)
        pos.append(v)
        if BONE in joints:
            jn = np.array(read_accessor(j, binary, p["attributes"]["JOINTS_0"])[0]).reshape(-1, 4).astype(int)
            w = np.array(read_accessor(j, binary, p["attributes"]["WEIGHTS_0"])[0]).reshape(-1, 4)
            share.append((w * (jn == joints.index(BONE))).sum(axis=1))
    return np.concatenate(pos), (np.concatenate(share) if share else None)


class Face:
    """A type's face skin at rest, to look at from the front."""

    def __init__(self, path):
        j, binary = read_glb(path)
        self.extras = (j["scenes"][j.get("scene", 0)].get("extras") or {}).get("hair_fit") or {}
        mesh = next(m for m in j["meshes"] if m.get("name") == "Face")
        prim = next(p for p in mesh["primitives"] if j["materials"][p["material"]]["name"].endswith("Face_00_SKIN"))
        v = np.array(read_accessor(j, binary, prim["attributes"]["POSITION"])[0]).reshape(-1, 3)
        t = np.array(read_accessor(j, binary, prim["indices"])[0]).reshape(-1, 3)
        self.a, self.b, self.c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
        self.lo, self.hi = np.minimum(np.minimum(self.a, self.b), self.c), np.maximum(np.maximum(self.a, self.b), self.c)
        self.has_bone = any(n.get("name") == BONE for n in j["nodes"])

    def before(self, pts):
        """How far each point is in front of the skin's front on its line of sight (metres; the
        face looks toward -Z); inf where no skin is behind it."""
        a, b, c = self.a, self.b, self.c
        den = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
        out = np.full(len(pts), np.inf)
        for n, q in enumerate(pts):
            m = np.where((self.lo[:, 0] <= q[0]) & (self.hi[:, 0] >= q[0]) & (self.lo[:, 1] <= q[1]) & (self.hi[:, 1] >= q[1]) & (np.abs(den) > 1e-14))[0]
            u = ((b[m, 1] - c[m, 1]) * (q[0] - c[m, 0]) + (c[m, 0] - b[m, 0]) * (q[1] - c[m, 1])) / den[m]
            v = ((c[m, 1] - a[m, 1]) * (q[0] - c[m, 0]) + (a[m, 0] - c[m, 0]) * (q[1] - c[m, 1])) / den[m]
            w = 1 - u - v
            inside = (u >= -1e-6) & (v >= -1e-6) & (w >= -1e-6)
            if inside.any():
                out[n] = (u * a[m, 2] + v * b[m, 2] + w * c[m, 2])[inside].min() - q[2]
        return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("lookdev")
    ap.add_argument("--table", action="store_true", help="print the measures as a table and fail on nothing (for files from before the bone)")
    ap.add_argument("--least", type=float, default=0.0, help="mm a type's lowest fringe must end above its brows' top (default 0)")
    ap.add_argument("--off", type=float, default=3.0, help="mm a style's end above the brows may differ from the same style's on the standard head (default 3.0: a fringe that stops short of the line follows the bone by its share)")
    ap.add_argument("--most", type=float, default=6.0, help="mm a type's fullest fringe may end above its brows' top (default 6.0)")
    ap.add_argument("--json")
    a = ap.parse_args()
    styles = {}
    for f in sorted(glob.glob(os.path.join(a.lookdev, "styles", "hair", "*.glb"))):
        s = style(f)
        if s is not None:
            styles[os.path.basename(f)[:-4]] = s
    if not styles:
        raise SystemExit(f"fringe_check: no hair styles under {a.lookdev}/styles/hair")
    bad, report = [], {}
    no_bone = sorted(n for n, (_, w) in styles.items() if w is None)
    if no_bone and not a.table:
        bad.append(f"{len(no_bone)} style file(s) have no {BONE} joint: {', '.join(no_bone[:5])}{'…' if len(no_bone) > 5 else ''}")
    if a.table:
        print("| Type | Brows' top | Fullest fringe ends above it | Middle style | A style from the same on the standard head, at most | Least before the skin |\n|---|---|---|---|---|---|")
    ends = {}
    faces = {}
    std_head = hair_fit.head(hair_fit.STANDARD)
    brow_std = hair_fit.placed(std_head, np.array([[0.0, 0.0, hair.brow_top(std_head)]]))[0][1]
    for tid in face_types.load()["types"]:
        path = os.path.join(a.lookdev, "types", tid + ".glb")
        if not os.path.exists(path):
            bad.append(f"{tid}: no file {path}")
            continue
        face = faces[tid] = Face(path)
        if not face.has_bone and not a.table:
            bad.append(f"{tid}: its file has no {BONE} bone")
        fit = np.array(face.extras.get("matrix", np.eye(4).T.ravel().tolist())).reshape(4, 4).T
        move = np.array((face.extras.get("fringe") or {}).get("move", [0.0, 0.0, 0.0]))
        hd = hair_fit.head(tid)
        brow = hair_fit.placed(hd, np.array([[0.0, 0.0, hair.brow_top(hd)]]))[0][1]
        gaps, least = {}, (np.inf, "")
        for name, (pos, share) in styles.items():
            p = pos @ fit[:3, :3].T + fit[:3, 3]
            if share is not None:
                p = p + share[:, None] * move[None, :]
            # Over the middle of the forehead: in front of the head's middle, between the brows and
            # the crown. The same vertices on every type: chosen where they stand in the style's
            # own file, on the standard head.
            zone = (np.abs(pos[:, 0]) < HALF) & (pos[:, 2] < -0.045) & (pos[:, 1] > brow_std - 0.03)
            if not zone.any():
                continue
            end = p[zone, 1].min() - brow
            if end > REACH:
                continue
            gaps[name] = float(end * 1000)
            low = zone & (p[:, 1] < brow + 0.03)
            d = face.before(p[low]) * 1000
            d = d[np.isfinite(d)]
            if len(d) and d.min() < least[0]:
                least = (float(d.min()), name)
        ends[tid] = (gaps, least, move, hd)
    std = ends.get(hair_fit.STANDARD, ({},))[0]
    for tid, (gaps, least, move, hd) in ends.items():
        if not gaps:
            bad.append(f"{tid}: no style's hair comes near its brows")
            continue
        g = np.array(sorted(gaps.values()))
        fullest = min(gaps, key=gaps.get)
        off = max(((abs(v - std[n]), n) for n, v in gaps.items() if n in std), default=(0.0, ""))
        report[tid] = dict(brow_top_mm=float(hair.brow_top(hd) * 1000), fullest_mm=float(g[0]), fullest=fullest, median_mm=float(np.median(g)), styles=len(g), off_standard_mm=off[0], off_standard_in=off[1],
                           before_skin_mm=least[0], before_skin_in=least[1], move_mm=[float(v * 1000) for v in move])
        if a.table:
            print(f"| `{tid}` | {hair.brow_top(hd) * 1000:.1f} mm | {g[0]:.1f} mm (`{fullest}`) | {np.median(g):.1f} mm | {off[0]:.1f} mm (`{off[1]}`) | {least[0]:.1f} mm (`{least[1]}`) |")
        else:
            print(f"{tid:10s} fullest fringe ends {g[0]:5.1f} mm above the brows' top ({fullest}); middle style {np.median(g):5.1f}; {len(g)} styles; from the standard's at most {off[0]:4.1f} ({off[1]}); least before the skin {least[0]:5.1f} mm ({least[1]})")
            if g[0] < a.least:
                bad.append(f"{tid}: `{fullest}` ends {g[0]:.1f} mm above the brows' top; at least {a.least} wanted")
            if g[0] > a.most:
                bad.append(f"{tid}: its fullest fringe (`{fullest}`) ends {g[0]:.1f} mm above the brows' top; at most {a.most} wanted")
            if off[0] > a.off:
                bad.append(f"{tid}: `{off[1]}` ends {off[0]:.1f} mm from where it ends on the standard head, against the brows; at most {a.off} wanted")
            if least[0] < 0.0:
                bad.append(f"{tid}: `{least[1]}` has a fringe vertex {-least[0]:.1f} mm behind the face's skin")
    if a.json:
        json.dump(report, open(a.json, "w"), indent=1)
    full = [r["fullest_mm"] for r in report.values()]
    if full:
        print(f"fringe_check: the fullest fringe ends {min(full):.1f} to {max(full):.1f} mm above the brows' top over {len(report)} types ({len(styles)} styles); a style is at most {max(r['off_standard_mm'] for r in report.values()):.1f} mm from where it ends on the standard head")
    if bad:
        print("fringe_check: FAILED\n  " + "\n  ".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
