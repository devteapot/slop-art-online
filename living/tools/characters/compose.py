#!/usr/bin/env python3
"""Compose a person the client's way: a type's file and a set of identity values, by bones.

    python3 living/tools/characters/compose.py IN.glb OUT.glb [--identity jaw_width=0.4,eye_size=-0.3 | --params NAME.params.json]
    python3 living/tools/characters/compose.py --compare COMPOSED.glb BAKED.glb

A person of a face type is the type's mesh with its identity bones moved (docs/CHARACTERS.md, "The
client format"). The client will do that once when it spawns the person. This does the same to a
file, so a person can be photographed before the client can compose one, and it is the reference
for what the client must compute:

- each value v in -1..1 becomes an amount from the rig's table (`types.json`, `rig.bones`): at -1
  the value's `least`, at 0 nothing, at 1 its `most`;
- a `move` adds amount ‰ of the head's height in the file (`file.head_height_m`) along the
  value's axis to the bone's rest translation; a `scale` multiplies the axis; a `turn` rotates
  about the axis;
- the rig's x, y, z are the file's X, -Z, Y; `o` is 0.55 x + 0.83 y. On a paired bone x points
  away from the midline on both sides and a turn has the same sense on both, so the right bone
  (`…_R`, at +X) takes the left's values mirrored;
- a bone's node gets translation, rotation and scale; its children ride it, which is how a layer
  is set in the units of the one it sits on.

No clip keys these bones, so the file's clips play on the composed person as they are.

`--compare` skins both files at rest and measures how far the first's surfaces lie from the
second's, mesh by mesh: a person composed by bones against the same person baked (`person.py
--bake`, which applies the same rule to the vertices and leaves the bones at rest). Plain Python
and numpy.
"""

import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import face_types  # noqa: E402
from merge_primitives import read_accessor, read_glb, write_glb  # noqa: E402


def quat(axis, deg):
    """A rotation about a unit axis, as glTF's (x, y, z, w)."""
    a = math.radians(deg) / 2
    s = math.sin(a)
    return [axis[0] * s, axis[1] * s, axis[2] * s, math.cos(a)]


def transforms(values, head_m):
    """Each identity bone's change from rest for a set of values: {bone: (move in file metres as
    X, Y, Z; rotation as a quaternion or None; scale as X, Y, Z)}. This is what the client computes."""
    out = {}
    for bone, _, _, _, vals in face_types.RIG:
        for name in ([bone, bone.replace("_L", "_R")] if bone in face_types.PAIRED else [bone]):
            side = -1.0 if name.endswith("_L") or "_L_" in name else (1.0 if name.endswith("_R") or "_R_" in name else 0.0)
            move, rot, scale = [0.0, 0.0, 0.0], None, [1.0, 1.0, 1.0]
            for v, what, axis, lo, hi, unit, _ in vals:
                amount = face_types.decode(v, values.get(v, 0.0))
                if what == "move":
                    m = amount * head_m
                    x, y, z = dict(x=(1, 0, 0), y=(0, 1, 0), z=(0, 0, 1), o=(0.55, 0.83, 0))[axis]
                    # The rig's x is away from the midline; the file's X is the character's right... and its left is -X.
                    move[0] += m * x * (side if side else 1.0)
                    move[1] += m * z
                    move[2] += -m * y
                elif what == "scale":
                    for k in axis:
                        scale[dict(x=0, y=2, z=1)[k]] *= amount
                elif abs(amount) > 1e-9:
                    if axis == "y":  # about the forward axis: the outer end up, on both sides
                        rot = quat((0, 0, 1), amount * (side if side else 1.0))
                    elif axis == "z":  # about the upright axis: outward, on both sides
                        rot = quat((0, 1, 0), amount * (side if side else 1.0))
                    else:  # about the axis across: the chin down
                        rot = quat((1, 0, 0), -amount)
            out[name] = (move, rot, scale)
    return out


def compose(j, values, head_m=None):
    """Write the identity bones' transforms for `values` into a file's nodes. Returns the bones moved."""
    head_m = head_m or face_types.load()["file"]["head_height_m"]
    nodes = {n.get("name"): n for n in j["nodes"]}
    moved = []
    for bone, (move, rot, scale) in transforms(values, head_m).items():
        n = nodes.get(bone)
        if n is None:
            continue
        rest = n.setdefault("extras", {}).setdefault("rest_translation", n.get("translation", [0.0, 0.0, 0.0]))
        n["translation"] = [r + m for r, m in zip(rest, move)]
        n.pop("rotation", None)
        n.pop("scale", None)
        if rot is not None:
            n["rotation"] = rot
        if any(abs(s - 1) > 1e-9 for s in scale):
            n["scale"] = scale
        if any(abs(m) > 1e-9 for m in move) or rot is not None or "scale" in n:
            moved.append(bone)
    return moved


def skinned(path, want=lambda mesh, material: material.endswith("Face_00_SKIN")):
    """A file's vertices as its nodes pose them (linear blend skinning in numpy), in the file's space."""
    j, binary = read_glb(path)
    nodes = j["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}

    def local(n):
        t = np.eye(4)
        t[:3, 3] = n.get("translation", [0, 0, 0])
        x, y, z, w = n.get("rotation", [0, 0, 0, 1])
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m = np.eye(4)
        m[:3, :3] = r * np.array(n.get("scale", [1, 1, 1]))[None, :]
        return t @ m

    world = {}

    def w(i):
        if i not in world:
            world[i] = (w(parent[i]) if i in parent else np.eye(4)) @ local(nodes[i])
        return world[i]

    skin = j["skins"][0]
    ibm = np.array(read_accessor(j, binary, skin["inverseBindMatrices"])[0]).reshape(-1, 4, 4).transpose(0, 2, 1)
    mats = np.array([w(jn) @ ibm[k] for k, jn in enumerate(skin["joints"])])
    out = []
    for mesh in j["meshes"]:
        for p in mesh["primitives"]:
            if not want(mesh.get("name", ""), j["materials"][p["material"]]["name"]):
                continue
            pos = np.array(read_accessor(j, binary, p["attributes"]["POSITION"])[0]).reshape(-1, 3)
            jt = np.array(read_accessor(j, binary, p["attributes"]["JOINTS_0"])[0]).reshape(-1, 4)
            wt = np.array(read_accessor(j, binary, p["attributes"]["WEIGHTS_0"])[0]).reshape(-1, 4)
            ph = np.concatenate([pos, np.ones((len(pos), 1))], axis=1)
            sk = np.zeros((len(pos), 3))
            for k in range(4):
                sk += wt[:, k : k + 1] * np.einsum("nij,nj->ni", mats[jt[:, k]], ph)[:, :3]
            out.append(sk)
    return np.concatenate(out)


KINDS = (("face skin", lambda mesh, material: material.endswith("Face_00_SKIN")), ("eyes", lambda mesh, material: material.endswith("_EYE")),
         ("lashes, brows and lines", lambda mesh, material: material.endswith("_FACE")), ("skin under the jaw", lambda mesh, material: mesh == "Face" and material.endswith("Body_00_SKIN")),
         ("hair", lambda mesh, material: material.endswith("_HAIR")), ("everything else", lambda mesh, material: mesh != "Face" and not material.endswith("_HAIR")))


def compare(a, b, want=KINDS[0][1]):
    """How far the first file's surface lies from the second's: each vertex to the nearest of the
    other's (both are dense, so this is close to the distance between the surfaces). Nearest and
    not vertex for vertex, because an exporter splits vertices by their normals."""
    pa, pb = skinned(a, want), skinned(b, want)
    d = np.empty(len(pa))
    for i in range(0, len(pa), 256):
        d[i : i + 256] = np.sqrt(((pa[i : i + 256, None, :] - pb[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
    return dict(vertices=len(pa), rms_mm=float(np.sqrt((d ** 2).mean()) * 1000), p95_mm=float(np.percentile(d, 95) * 1000), most_mm=float(d.max() * 1000))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--identity", default="", help="values as `k=v,k=v` or a JSON object")
    ap.add_argument("--params", help="a person's NAME.params.json (person.py writes it): its `identity`")
    ap.add_argument("--compare", action="store_true", help="measure the first file's skin against the second's")
    a = ap.parse_args()
    if a.compare:
        for kind, want in KINDS:
            r = compare(a.inp, a.out, want)
            print(f"compose: {kind}: {r['vertices']} vertices; first against second: {r['rms_mm']:.2f} mm rms, {r['p95_mm']:.2f} mm at the 95th percentile, {r['most_mm']:.2f} mm at most")
        return
    values = {}
    if a.params:
        values.update(json.load(open(a.params)).get("identity") or {})
    if a.identity:
        values.update(json.loads(a.identity) if a.identity.strip().startswith("{") else {k: float(v) for k, v in (x.split("=") for x in a.identity.split(",") if x)})
    j, binary = read_glb(a.inp)
    moved = compose(j, values)
    write_glb(a.out, j, binary)
    print(f"compose: {a.out}: {len(values)} values, {len(moved)} bones moved from rest")


if __name__ == "__main__":
    main()
