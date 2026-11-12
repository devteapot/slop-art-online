#!/usr/bin/env python3
"""How far a person composed from shared outfit pieces is from their own file, inside each piece.

    python3 living/tools/characters/piece_tones.py PERSON.json [...] [--styles DIR] [--work DIR] [--jobs N] [--root DIR]

A shared piece is grey shading that the client tints to the wearer's colour, so the mean of a
composed piece is right by construction (the person's line carries the painted colour). What
can still differ is the spread inside the piece: a darker hem, stripes, patches. This builds,
for each person (a parameter file, as town.py writes them):

- their own file, and each piece they wear alone, to know which of the file's vertices are
  that piece's (matched by position);
- the same piece's shared file (`<styles>/outfit/<piece>.glb`), whose vertices are in the same
  order, tinted as the client tints it: a grey material takes the line's hue and saturation,
  and its value is multiplied down to the line's when that is below the material's mean, or
  lightened toward white when it is above (`living/game/src/toon.wesl` `recolor`, `remap`).

It prints, for each piece and over all, the CIE76 difference between the two colours of each
vertex, weighted by area (mean and 95th percentile), and the same for lightness alone, which
is the part a tone can carry. `--root` runs another checkout's generator (to measure before a
change). Needs Blender; plain Python, numpy.
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from merge_primitives import read_accessor, read_glb  # noqa: E402


def linear(c):
    c = np.asarray(c, float)
    return np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)


def lab(rgb):
    """Linear RGB (n, 3) to CIE L*a*b* (D65)."""
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = np.clip(rgb, 0, None) @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def hsv(c):
    v = float(max(c)); lo = float(min(c)); d = v - lo
    if d < 1e-9:
        return 0.0, 0.0, v
    r, g, b = c
    h = ((g - b) / d) % 6 if v == r else ((b - r) / d + 2 if v == g else (r - g) / d + 4)
    return h / 6.0, d / v, v


def rgb_of(h, s, v):
    k = (np.array([5.0, 3.0, 1.0]) + h * 6.0) % 6.0
    return v[:, None] * (1.0 - s * np.clip(np.minimum(k, 4.0 - k), 0.0, 1.0))[None, :]


def tinted(grey, mean, target):
    """A grey piece's vertices as the client draws them tinted to `target` (linear RGB)."""
    th, ts, tv = hsv(target)
    mv = float(max(mean))
    if tv <= mv:
        v = grey * (tv / mv if mv > 1e-4 else 1.0)
    else:
        v = 1.0 - (1.0 - grey) * max((1.0 - tv) / max(1.0 - mv, 1e-4), 1e-4)
    return rgb_of(th, ts, np.clip(v, 0.0, 1.0))


def cloth(path):
    """A file's near cloth: positions, vertex colours (linear RGB) and each vertex's share of the area."""
    j, b = read_glb(path)
    P, C, A = [], [], []
    for mesh in j["meshes"]:
        if mesh["name"] != "Cloth":
            continue
        for p in mesh["primitives"]:
            pos = np.array(read_accessor(j, b, p["attributes"]["POSITION"])[0], float).reshape(-1, 3)
            acc = j["accessors"][p["attributes"]["COLOR_0"]]
            col = np.array(read_accessor(j, b, p["attributes"]["COLOR_0"])[0], float).reshape(len(pos), -1)[:, :3] / {5126: 1.0, 5123: 65535.0, 5121: 255.0}[acc["componentType"]]
            idx = np.array(read_accessor(j, b, p["indices"])[0], np.int64).reshape(-1, 3)
            area = np.linalg.norm(np.cross(pos[idx[:, 1]] - pos[idx[:, 0]], pos[idx[:, 2]] - pos[idx[:, 0]]), axis=1)
            a = np.zeros(len(pos))
            for k in range(3):
                np.add.at(a, idx[:, k], area / 3)
            P.append(pos); C.append(col); A.append(a)
    return np.vstack(P), np.vstack(C), np.concatenate(A)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("people", nargs="+")
    ap.add_argument("--styles", default="living/game/assets/lookdev/styles")
    ap.add_argument("--work", default=".local/work/piece-tones")
    ap.add_argument("--root", default=".", help="the checkout whose generator builds the people (default: this one)")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--reuse", action="store_true", help="read what an earlier run built in --work")
    ap.add_argument("--json")
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    os.makedirs(work, exist_ok=True)
    sys.path.insert(0, os.path.join(os.path.abspath(a.root), "living", "tools", "blender"))
    sys.path.insert(0, os.path.join(os.path.abspath(a.root), "living", "tools", "characters"))
    import person_params

    def blender(args, out):
        if a.reuse and os.path.exists(out):
            return
        log = out + ".log"
        r = subprocess.run([os.environ.get("BLENDER", "blender"), "-b", "--python-exit-code", "1", "-P", "living/tools/blender/person.py", "--", *args, "--lod", "near", "--morphs", "client", "--out", out],
                           cwd=a.root, stdout=open(log, "w"), stderr=subprocess.STDOUT)
        if r.returncode:
            raise SystemExit(f"piece_tones: building {out} failed; see {log}")

    people = {os.path.splitext(os.path.basename(p))[0]: os.path.abspath(p) for p in a.people}
    with ThreadPoolExecutor(a.jobs) as pool:
        list(pool.map(lambda n: blender(["--params", people[n]], os.path.join(work, f"{n}.glb")), people))
    lines = {n: json.load(open(os.path.join(work, f"{n}.params.json")))["person"] for n in people}
    jobs = [(n, piece) for n in people for piece in lines[n]["styles"]["outfit"]]
    with ThreadPoolExecutor(a.jobs) as pool:
        list(pool.map(lambda j: blender(["--params", people[j[0]], "--parts", "keep", "--keep", ",".join(person_params.piece_parts(j[1]))], os.path.join(work, f"{j[0]}.{j[1]}.glb")), jobs))
    rows = []
    for n in people:
        wp, wc, _ = cloth(os.path.join(work, f"{n}.glb"))
        where = {}
        for i, k in enumerate(map(tuple, np.round(wp * 1e5).astype(np.int64))):
            where.setdefault(k, []).append(i)
        for piece in lines[n]["styles"]["outfit"]:
            op, _, area = cloth(os.path.join(work, f"{n}.{piece}.glb"))
            hit = [where.get(k) for k in map(tuple, np.round(op * 1e5).astype(np.int64))]
            # A piece built alone has a man's or a woman's neck hole; on a child's own file the
            # hole is the child's, a few millimetres in. Those vertices take the nearest.
            for i in [i for i, h in enumerate(hit) if h is None]:
                d = np.linalg.norm(wp - op[i], axis=1)
                if d.min() > 0.02:
                    raise SystemExit(f"piece_tones: {n}: {piece}: a vertex is {d.min() * 100:.1f} cm from anything in the person's own file")
                hit[i] = [int(d.argmin())]
            own = np.array([wc[h].mean(axis=0) for h in hit])
            sp, sc, sarea = cloth(os.path.join(a.styles, "outfit", piece + ".glb"))
            if len(sp) != len(op):
                # Its vertices are split another way in the two files (a head piece's seams): left out.
                print(f"piece_tones: {n}: {piece} left out: the shared file has {len(sp)} vertices, the person's own piece {len(op)}")
                continue
            grey = sc.mean(axis=1)
            mean = (sc * sarea[:, None]).sum(axis=0) / sarea.sum()
            target = linear([int(lines[n]["colors"]["outfit"][piece].lstrip("#")[k : k + 2], 16) / 255 for k in (0, 2, 4)])
            comp = tinted(grey, mean, target)
            la, lb = lab(own), lab(comp)
            de = np.linalg.norm(la - lb, axis=1)
            dl = np.abs(la[:, 0] - lb[:, 0])
            order = np.argsort(de); cw = np.cumsum(area[order]) / area.sum()
            rows.append(dict(person=n, piece=piece, de=float((de * area).sum() / area.sum()), de95=float(de[order][np.searchsorted(cw, 0.95)]), dl=float((dl * area).sum() / area.sum()),
                             lightens=bool(max(target) > max(mean)), mean=float(max(mean)), value=float(max(target))))
    kinds = {}
    for r in rows:
        kinds.setdefault(r["piece"].split("-")[0].split("_")[0], []).append(r)
    print(f"piece_tones: {len(people)} people, {len(rows)} pieces; CIE76 between each vertex of a person's own piece and the shared piece tinted as the client tints it")
    print(f"  {'piece':10s} {'n':>3s}  {'mean dE':>8s} {'p95 dE':>8s} {'mean dL':>8s}  tinted lighter than the mean")
    for k, v in sorted(kinds.items()):
        print(f"  {k:10s} {len(v):3d}  {np.median([r['de'] for r in v]):8.1f} {np.median([r['de95'] for r in v]):8.1f} {np.median([r['dl'] for r in v]):8.1f}  {sum(r['lightens'] for r in v)}")
    print(f"  {'all':10s} {len(rows):3d}  {np.median([r['de'] for r in rows]):8.1f} {np.median([r['de95'] for r in rows]):8.1f} {np.median([r['dl'] for r in rows]):8.1f}  {sum(r['lightens'] for r in rows)}   (medians over pieces)")
    worst = sorted(rows, key=lambda r: -r["de"])[:6]
    print("  worst: " + "; ".join(f"{r['person']} {r['piece']} {r['de']:.1f}" for r in worst))
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
