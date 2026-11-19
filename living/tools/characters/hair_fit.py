#!/usr/bin/env python3
"""Fit the shared hair styles' head onto a face type's, and write the fit into the type's file.

    python3 living/tools/characters/hair_fit.py TYPE FILE.glb
    python3 living/tools/characters/hair_fit.py --table

A shared hair style (lookdev/styles/hair/<style>.glb, gen_styles.sh) is built once, on one head:
the standard, `person_params.STYLE_HEAD`. The types' skulls differ from it, by up to 5 mm (root
mean square over the hair's region) for the men's. So each type's file says how the standard
skull is laid onto its own: one matrix, `hair_fit`, in the scene's extras, which scales the
standard about its cranium's pivot (three numbers) and shifts it (three), fitted by least squares
to the two skulls over the region hair grows on. About 2 mm is left.

The client uses it when it attaches a style to a person of that type (docs/CHARACTERS.md, "Hair
styles"): a hair vertex's place at rest is `hair_fit` times its place in the style's file, and
compose.py does exactly that to a file, to show it and to check it.

The types' brows sit at different heights, so a style's fringe hangs from a bone of the head's,
`J_Hair_Fringe` (hair.py, `fringe_line`), and this also stands that bone in the type's file where
the type's own fringe ends: the node is moved from its bind (its inverse bind matrix stays), by
`hair_fit.fringe.move` in the extras. A client that attaches a style by bone name, binding it to
the type's bind matrices, draws the fringe at the type's line with nothing more to do.

The matrix is in the file's space (metres, X the character's right, Y up, -Z forward), sixteen
numbers, column by column. Every generated head sits at the same place in its file, so it needs
no other frame. Plain Python and numpy.
"""

import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "blender"))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import cage_head  # noqa: E402
import face_types  # noqa: E402
import hair  # noqa: E402
import head_mesh  # noqa: E402
from merge_primitives import read_accessor, read_glb, write_glb  # noqa: E402

STANDARD = "adult-f-b"  # person_params.STYLE_HEAD
FILE_FROM_FORM = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])  # the file's X, Y, Z from the generator's x, y (forward), z (up)


def head(tid):
    t = face_types.load()["types"][tid]
    return cage_head.CageHead(face_types.apply(t, {}), masc=1.0 if t["sex"] == "male" else 0.0, child=1.0 if t["band"] == "child" else 0.0, elder=1.0 if t["band"] == "elder" else 0.0)


def placed(hf, p):
    """Points of a head (the generator's frame) where they stand in a file: the chin at 1.535 m (person.py, configure)."""
    return (p + np.array([0.0, -0.004, 1.535 - hf.chin_z])) @ FILE_FROM_FORM.T


def fit(tid):
    """The matrix that lays the standard head's skull onto type `tid`'s, and what it leaves:
    (4x4 in the file's space, root mean square before in mm, after in mm, the most after in mm)."""
    dirs, _, _ = head_mesh.cube_sphere(16, head_mesh.WARP)
    grows = (dirs[:, 2] > 0.15) | ((dirs[:, 1] < -0.2) & (dirs[:, 2] > -0.45))  # above the brow, and the back down to the nape
    std, typ = head(STANDARD), head(tid)
    a = placed(std, head_mesh.ORIGIN + dirs[grows] * std.radius(dirs[grows])[:, None])
    b = placed(typ, head_mesh.ORIGIN + dirs[grows] * typ.radius(dirs[grows])[:, None])
    c = placed(std, cage_head.rig_pivots(std)["J_Id_Cranium"][None, :])[0]
    A = np.zeros((len(a) * 3, 6))
    y = np.zeros(len(a) * 3)
    for k in range(3):
        A[k::3, k] = a[:, k] - c[k]
        A[k::3, 3 + k] = 1.0
        y[k::3] = b[:, k] - c[k]
    x = np.linalg.lstsq(A, y, rcond=None)[0]
    m = np.eye(4)
    m[:3, :3] = np.diag(x[:3])
    m[:3, 3] = c + x[3:] - x[:3] * c
    before = np.linalg.norm(a - b, axis=1) * 1000
    # What is left, along the skull's own direction from the cranium's pivot (sliding along the surface is no misfit).
    fitted = a @ m[:3, :3].T + m[:3, 3]
    after = np.abs(np.linalg.norm(fitted - c, axis=1) - np.linalg.norm(b - c, axis=1)) * 1000
    return m, float(np.sqrt((before ** 2).mean())), float(np.sqrt((after ** 2).mean())), float(after.max())


def fringe(tid, m=None):
    """How far a type's file stands the fringe's bone from its place at bind, in the file's space
    (metres): the move that takes the standard head's fringe point, laid on by the fit, to the
    type's own (hair.fringe_point: the forehead's front, `FRINGE_OVER` above the type's brows)."""
    m = fit(tid)[0] if m is None else m
    std, typ = head(STANDARD), head(tid)
    q = placed(std, hair.fringe_point(std)[None, :])[0] @ m[:3, :3].T + m[:3, 3]
    return placed(typ, hair.fringe_point(typ)[None, :])[0] - q


def stand_fringe(j, binary, move):
    """Move the fringe's bone in a type's file by `move` (the file's space) from where it is
    bound, leaving its inverse bind matrix alone: the node is no longer at its bind, so what
    hangs from it is drawn moved. Returns False where the file has no such bone."""
    node = next((i for i, n in enumerate(j["nodes"]) if n.get("name") == hair.FRINGE_BONE), None)
    skin = next((s for s in j.get("skins", []) if node in s["joints"]), None) if node is not None else None
    if skin is None:
        return False
    ibm = np.array(read_accessor(j, binary, skin["inverseBindMatrices"])[0]).reshape(-1, 4, 4).transpose(0, 2, 1)
    bind = {n: np.linalg.inv(ibm[k]) for k, n in enumerate(skin["joints"])}
    parent = next(i for i, n in enumerate(j["nodes"]) if node in n.get("children", []))
    local = np.linalg.inv(bind[parent]) @ (np.array([[1, 0, 0, move[0]], [0, 1, 0, move[1]], [0, 0, 1, move[2]], [0, 0, 0, 1.0]]) @ bind[node])
    n = j["nodes"][node]
    n.pop("matrix", None)
    n["translation"] = [float(v) for v in local[:3, 3]]
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("type", nargs="?")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--table", action="store_true", help="every type's fit and what it leaves")
    a = ap.parse_args()
    if a.table:
        print("| Type | Skull from the standard's, as built | After the fit | Most | Scale (across, up, depth) | Brows' top | The fringe's bone: up, forward |\n|---|---|---|---|---|---|---|")
        for tid in face_types.load()["types"]:
            m, before, after, most = fit(tid)
            f = fringe(tid, m)
            print(f"| `{tid}` | {before:.1f} mm | {after:.1f} mm | {most:.1f} mm | {m[0, 0]:.3f}, {m[1, 1]:.3f}, {m[2, 2]:.3f} | {hair.brow_top(head(tid)) * 1000:.1f} mm | {f[1] * 1000:+.1f}, {-f[2] * 1000:+.1f} mm |")
        return
    m, before, after, most = fit(a.type)
    j, binary = read_glb(a.file)
    f = fringe(a.type, m)
    if not stand_fringe(j, binary, f):
        raise SystemExit(f"hair_fit: {a.file} has no {hair.FRINGE_BONE} bone in a skin; build the type again")
    # `fringe`: where the fringe's bone stands from its bind (already done to the node above; a
    # tool that poses the file from its bind matrices applies it itself).
    j["scenes"][j.get("scene", 0)].setdefault("extras", {})["hair_fit"] = dict(standard=STANDARD, matrix=[float(v) for v in m.T.ravel()], left_mm=round(after, 2), fringe=dict(bone=hair.FRINGE_BONE, move=[float(v) for v in f]))
    write_glb(a.file, j, binary)
    print(f"hair_fit: {a.file}: {a.type} from {STANDARD}: {before:.1f} mm as built, {after:.1f} mm after the fit (most {most:.1f}); the fringe's bone {f[1] * 1000:+.1f} mm up, {-f[2] * 1000:+.1f} mm forward")


if __name__ == "__main__":
    main()
