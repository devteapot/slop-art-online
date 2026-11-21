"""bmesh primitives whose result is the same in every run (docs/TOOLING.md, "Reproducible generators").

`bmesh.ops.create_uvsphere` gives the same vertices every time, but the order of its faces
changes from one Blender process to the next (2026-11-21, Blender 5.2.2: two to three orders in
five runs, both for 8x5 and 16x8). The faces round the poles come out in another order, so a
file built from a UV sphere differed in its index order between two runs of the same code: the
kerchief's knot (person.py) and the mushroom caps (buildings.py). Icospheres, cones, cubes and
convex hulls were the same in every run (living/tools/stable_selftest.py checks these too).

`uvsphere` sorts the new faces by their sorted vertex indices (stable: the vertices are), which
keeps each face's own winding. Use it wherever a UV sphere goes into a file.
"""

import bmesh


def uvsphere(bm, **kw):
    """bmesh.ops.create_uvsphere, with the new faces in a fixed order. Returns the op's result.
    Faces already in bm keep their places, before the new ones."""
    before = len(bm.faces)
    res = bmesh.ops.create_uvsphere(bm, **kw)
    bm.verts.index_update()
    bm.faces.ensure_lookup_table()
    old, new = list(bm.faces[:before]), list(bm.faces[before:])
    new.sort(key=lambda f: tuple(sorted(v.index for v in f.verts)))
    rank = {f: i for i, f in enumerate(old + new)}  # BMFaceSeq.sort takes a number
    bm.faces.sort(key=lambda f: rank[f])
    bm.faces.index_update()
    bm.faces.ensure_lookup_table()
    return res
