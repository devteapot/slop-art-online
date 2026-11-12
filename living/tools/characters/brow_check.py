#!/usr/bin/env python3
"""Check that every type's brows are there and stand before the skin, at rest and on people.

    python3 living/tools/characters/brow_check.py TYPES_DIR [--book looks.json] [--least 0.3] [--json OUT]

A type's brows are a drawn strip (`…FaceBrow_00_FACE`) a little over a millimetre off the face's
skin. A person is the type with its identity bones moved, so the strip and the skin under it
have to move alike: where they do not, the skin comes through the brow and the person has none
(the laptop's find on `child-u-a`, 2026-11-12: one line in five of the look book had some of a
brow behind the skin). For each `<type>.glb` in TYPES_DIR this poses the file the client's way
(compose.py's rule, linear blend skinning) and looks from the front: on the line of sight
through each of the brow's vertices and each of its triangles' middles, how far the brow is
before the skin's front.

- at rest;
- with every identity value alone at each of its ends (-1 and 1);
- with the values that move the forehead and the brow together at their ends;
- with `--book`, on every line of a look book that wears the type.

It fails (exit 1) if a type has no brow primitive, if the brow has no weights, or if anywhere in
those poses a point of the brow is less than `--least` millimetres before the skin (default 0.3).
Plain Python and numpy.
"""

import argparse
import copy
import glob
import itertools
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import compose  # noqa: E402
import face_types  # noqa: E402
from merge_primitives import read_accessor, read_glb  # noqa: E402


class TypeFile:
    def __init__(self, path):
        self.j, binary = read_glb(path)
        j = self.j
        self.parent = {c: i for i, n in enumerate(j["nodes"]) for c in n.get("children", [])}
        face = next((i for i, m in enumerate(j["meshes"]) if m.get("name") == "Face"), None)
        if face is None:
            raise SystemExit(f"{path}: no Face mesh")
        node = next(n for n in j["nodes"] if n.get("mesh") == face)
        skin = j["skins"][node.get("skin", 0)]
        self.joints = skin["joints"]
        self.ibm = np.array(read_accessor(j, binary, skin["inverseBindMatrices"])[0]).reshape(-1, 4, 4).transpose(0, 2, 1)
        self.prims = {}
        for p in j["meshes"][face]["primitives"]:
            name = j["materials"][p["material"]]["name"]
            kind = "brow" if "FaceBrow" in name else ("skin" if name.endswith("Face_00_SKIN") else None)
            if kind:
                get = lambda a: np.array(read_accessor(j, binary, p["attributes"][a])[0])
                self.prims[kind] = dict(pos=get("POSITION").reshape(-1, 3), joints=get("JOINTS_0").reshape(-1, 4).astype(int), weights=get("WEIGHTS_0").reshape(-1, 4),
                                        tris=np.array(read_accessor(j, binary, p["indices"])[0]).reshape(-1, 3))

    def posed(self, values):
        """(skin positions, brow positions) with the identity bones moved for `values`."""
        j = copy.deepcopy({"nodes": self.j["nodes"]})
        compose.compose(j, values)
        nodes = j["nodes"]
        world = {}

        def local(n):
            if "matrix" in n:
                return np.array(n["matrix"]).reshape(4, 4).T
            t = np.eye(4)
            t[:3, 3] = n.get("translation", [0, 0, 0])
            x, y, z, w = n.get("rotation", [0, 0, 0, 1])
            r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            m = np.eye(4)
            m[:3, :3] = r * np.array(n.get("scale", [1, 1, 1]))[None, :]
            return t @ m

        def w(i):
            if i not in world:
                world[i] = (w(self.parent[i]) if i in self.parent else np.eye(4)) @ local(nodes[i])
            return world[i]

        mats = np.array([w(jn) @ self.ibm[k] for k, jn in enumerate(self.joints)])
        out = []
        for kind in ("skin", "brow"):
            p = self.prims[kind]
            ph = np.concatenate([p["pos"], np.ones((len(p["pos"]), 1))], axis=1)
            sk = np.zeros((len(ph), 3))
            for k in range(4):
                sk += p["weights"][:, k : k + 1] * np.einsum("nij,nj->ni", mats[p["joints"][:, k]], ph)[:, :3]
            out.append(sk)
        return out

    def before(self, values):
        """How far each sample of the brow is before the skin's front (metres; the face looks toward -Z)."""
        skin, brow = self.posed(values)
        tris = self.prims["skin"]["tris"]
        a, b, c = skin[tris[:, 0]], skin[tris[:, 1]], skin[tris[:, 2]]
        lo, hi = np.minimum(np.minimum(a, b), c), np.maximum(np.maximum(a, b), c)
        den = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
        pts = np.concatenate([brow, brow[self.prims["brow"]["tris"]].mean(axis=1)])
        out = np.full(len(pts), np.inf)
        for n, q in enumerate(pts):
            m = np.where((lo[:, 0] <= q[0]) & (hi[:, 0] >= q[0]) & (lo[:, 1] <= q[1]) & (hi[:, 1] >= q[1]) & (np.abs(den) > 1e-14))[0]
            u = ((b[m, 1] - c[m, 1]) * (q[0] - c[m, 0]) + (c[m, 0] - b[m, 0]) * (q[1] - c[m, 1])) / den[m]
            v = ((c[m, 1] - a[m, 1]) * (q[0] - c[m, 0]) + (a[m, 0] - c[m, 0]) * (q[1] - c[m, 1])) / den[m]
            w = 1 - u - v
            inside = (u >= -1e-6) & (v >= -1e-6) & (w >= -1e-6)
            if inside.any():
                out[n] = (u * a[m, 2] + v * b[m, 2] + w * c[m, 2])[inside].min() - q[2]
        return out


def poses(ids):
    """The poses every type is tried in: (name, values)."""
    out = [("at rest", {})]
    for i in ids:
        out += [(f"{i} -1", {i: -1.0}), (f"{i} +1", {i: 1.0})]
    # What moves the forehead's skin and what moves the brow, together at their ends.
    skin = ("forehead", "brow_ridge", "cranium_depth")
    for s, h, d in itertools.product((-1.0, 1.0), (-1.0, 1.0), (-1.0, 1.0)):
        out.append((f"forehead, brow_ridge and cranium_depth {s:+.0f}, brow_height {h:+.0f}, socket_depth {d:+.0f}", dict({k: s for k in skin}, brow_height=h, socket_depth=d)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("types")
    ap.add_argument("--book", help="a look book (looks.json): every line is tried on its type")
    ap.add_argument("--least", type=float, default=0.3, help="millimetres the brow must stand before the skin everywhere (default 0.3)")
    ap.add_argument("--json")
    a = ap.parse_args()
    rig = face_types.load()
    ids = [v["id"] for b in rig["rig"]["bones"] for v in b["values"]]
    want = sorted(rig["types"])
    lines = {}
    if a.book:
        for key, line in json.load(open(a.book))["lines"].items():
            lines.setdefault(line["person"]["type"], []).append((key, line["person"].get("identity") or {}))
    bad, report = [], {}
    for t in want:
        path = os.path.join(a.types, t + ".glb")
        if not os.path.exists(path):
            bad.append(f"{t}: no file {path}")
            continue
        f = TypeFile(path)
        if "brow" not in f.prims or not len(f.prims["brow"]["tris"]):
            bad.append(f"{t}: no brow primitive (…FaceBrow_00_FACE) in its Face mesh")
            continue
        if "skin" not in f.prims:
            bad.append(f"{t}: no face skin primitive")
            continue
        if (f.prims["brow"]["weights"].sum(axis=1) < 0.99).any():
            bad.append(f"{t}: a brow vertex without weights")
            continue
        worst = (np.inf, "")
        behind = 0
        tried = poses(ids) + [(f"line {k}", v) for k, v in lines.get(t, [])]
        for name, values in tried:
            d = f.before(values) * 1000
            if not np.isfinite(d).all():
                bad.append(f"{t}, {name}: a point of the brow has no skin behind it")
                break
            if d.min() < worst[0]:
                worst = (float(d.min()), name)
            if d.min() < a.least:
                behind += 1
        rest = f.before({}) * 1000
        report[t] = dict(rest_least_mm=float(rest.min()), rest_median_mm=float(np.median(rest)), least_mm=worst[0], least_in=worst[1], poses=len(tried), failing=behind)
        print(f"{t:10s} at rest {rest.min():5.2f} mm at least (median {np.median(rest):.2f}); over {len(tried)} poses {worst[0]:5.2f} mm at least ({worst[1]}); {behind} below {a.least} mm")
        if behind:
            bad.append(f"{t}: the brow is less than {a.least} mm before the skin in {behind} of {len(tried)} poses; least {worst[0]:.2f} mm ({worst[1]})")
    if a.json:
        json.dump(report, open(a.json, "w"), indent=1)
    if bad:
        print("brow_check: FAILED\n  " + "\n  ".join(bad))
        return 1
    print(f"brow_check: {len(want)} types, every brow there and at least {a.least} mm before the skin in every pose")
    return 0


if __name__ == "__main__":
    sys.exit(main())
