#!/usr/bin/env python3
"""Write a character file's outline normals: one smoothed direction a point, as `_OUTLINE_NORMAL`.

    python3 living/tools/characters/outline_normals.py IN.glb [OUT.glb] [--check]

The game draws a person's outline as a shell: each vertex pushed out along a direction. A
vertex's shading normal will not do, because a mesh is split wherever its shading, UVs or
materials break, and the split's two sides would be pushed apart and the line would crack. The
client makes up a direction when it loads a mesh (`generate_outline_normals` in
`lookdev.rs`), mesh by mesh. This writes it into the file instead, once, when the file is
made:

- every vertex at the same place takes the same direction, across the file's meshes and
  materials too (the face's skin against the skin under the jaw and the neck's, an eye's rim
  against the lid): the mean of the face normals round it, each weighted by its corner's angle,
  which is what the client's own makes within one mesh;
- where the faces round a point cancel (a card seen from both sides, a strand's tip) the
  vertex keeps its shading normal;
- it is the bind pose's. Skinning turns it with the vertex, as it turns the normal; an
  expression's morph does not move it.

`--check` reads a file and says how many of its vertices carry the attribute and how far the
directions are from the shading normals. Plain Python and numpy.

The client needs two lines to use it (docs/CHARACTERS.md, "What the client needs"): name the
attribute to the glTF loader, and skip its own generation for a mesh that has it. Until then
the loader ignores the attribute and the game draws the file as before.
"""

import argparse
import os
import sys
from array import array

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from merge_primitives import append_accessor, read_accessor, read_glb, write_glb  # noqa: E402

NAME = "_OUTLINE_NORMAL"
WELD = 2e-5  # metres: vertices nearer than this are one point


def primitives(j):
    for mesh in j["meshes"]:
        for p in mesh["primitives"]:
            if p.get("mode", 4) == 4 and "POSITION" in p["attributes"] and "NORMAL" in p["attributes"]:
                yield mesh, p


def outline(j, binary):
    """The direction for every vertex of every triangle primitive: {id(primitive): (n, 3) array}."""
    parts = []
    for mesh, p in primitives(j):
        pos = np.array(read_accessor(j, binary, p["attributes"]["POSITION"])[0], dtype=np.float64).reshape(-1, 3)
        nrm = np.array(read_accessor(j, binary, p["attributes"]["NORMAL"])[0], dtype=np.float64).reshape(-1, 3)
        idx = np.array(read_accessor(j, binary, p["indices"])[0], dtype=np.int64).reshape(-1, 3) if "indices" in p else np.arange(len(pos)).reshape(-1, 3)
        parts.append((p, pos, nrm, idx))
    if not parts:
        return {}
    allpos = np.concatenate([q[1] for q in parts])
    _, point = np.unique(np.round(allpos / WELD).astype(np.int64), axis=0, return_inverse=True)
    point = point.reshape(-1)
    acc = np.zeros((point.max() + 1, 3))
    base = 0
    for p, pos, nrm, idx in parts:
        a, b, c = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
        fn = np.cross(b - a, c - a)
        ln = np.linalg.norm(fn, axis=1, keepdims=True)
        fn = np.where(ln > 1e-14, fn / np.maximum(ln, 1e-14), 0.0)
        for k, (u, v, w) in enumerate(((a, b, c), (b, c, a), (c, a, b))):
            e1, e2 = v - u, w - u
            e1 /= np.maximum(np.linalg.norm(e1, axis=1, keepdims=True), 1e-14)
            e2 /= np.maximum(np.linalg.norm(e2, axis=1, keepdims=True), 1e-14)
            ang = np.arccos(np.clip((e1 * e2).sum(axis=1), -1.0, 1.0))
            np.add.at(acc, point[base + idx[:, k]], fn * ang[:, None])
        base += len(pos)
    out, base = {}, 0
    for p, pos, nrm, idx in parts:
        d = acc[point[base : base + len(pos)]]
        ln = np.linalg.norm(d, axis=1, keepdims=True)
        # Faces that cancel, or a vertex no triangle uses: the shading normal.
        weak = (ln[:, 0] < 0.25) | ((d * nrm).sum(axis=1) < 0.0)
        d = np.where(weak[:, None], nrm, d / np.maximum(ln, 1e-14))
        out[id(p)] = d
        base += len(pos)
    return out


def write(j, binary):
    """Add the attribute to every triangle primitive. Returns (primitives, vertices)."""
    dirs = outline(j, binary)
    n = 0
    for _, p in primitives(j):
        d = dirs[id(p)]
        p["attributes"][NAME] = append_accessor(j, binary, array("f", d.astype(np.float32).ravel().tolist()), 5126, "VEC3", False, 34962)
        n += len(d)
    return len(dirs), n


def check(path):
    j, binary = read_glb(path)
    have = total = 0
    turn = []
    for _, p in primitives(j):
        nrm = np.array(read_accessor(j, binary, p["attributes"]["NORMAL"])[0]).reshape(-1, 3)
        total += len(nrm)
        if NAME in p["attributes"]:
            o = np.array(read_accessor(j, binary, p["attributes"][NAME])[0]).reshape(-1, 3)
            assert len(o) == len(nrm) and np.allclose(np.linalg.norm(o, axis=1), 1.0, atol=1e-3), "outline normals must be unit vectors, one a vertex"
            have += len(o)
            turn.append(np.degrees(np.arccos(np.clip((o * nrm).sum(axis=1), -1, 1))))
    t = np.concatenate(turn) if turn else np.zeros(1)
    print(f"outline_normals: {path}: {have} of {total} vertices carry {NAME}; from the shading normal {np.median(t):.1f} degrees at the median, {np.percentile(t, 95):.1f} at the 95th percentile")
    return have == total


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inp")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        sys.exit(0 if check(a.inp) else 1)
    j, binary = read_glb(a.inp)
    for _, p in primitives(j):
        p["attributes"].pop(NAME, None)
    prims, verts = write(j, binary)
    write_glb(a.out or a.inp, j, binary)
    print(f"outline_normals: {a.out or a.inp}: {verts} vertices in {prims} primitives")


if __name__ == "__main__":
    main()
