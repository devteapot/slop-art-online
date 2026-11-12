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
from array import array  # noqa: E402

from merge_primitives import COMPONENT, append_accessor, read_accessor, read_glb, write_glb  # noqa: E402


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


def bind_world(j, binary, skin):
    """Each joint's world matrix at bind, by node index: the inverse of its inverse bind matrix."""
    ibm = np.array(read_accessor(j, binary, skin["inverseBindMatrices"])[0]).reshape(-1, 4, 4).transpose(0, 2, 1)
    return {n: np.linalg.inv(ibm[k]) for k, n in enumerate(skin["joints"])}


def attach_hair(j, binary, style_path, out_path, colour=None, far=False):
    """Put a shared hair style on a type's (or a person's) file, as the client attaches one.

    - The style's hair mesh comes in as it is, in the standard head's space, with its weights.
    - Its joints are the target's own bones, found by name. The bones only the style has (its
      spring chains, which hang under `J_Id_Cranium`) are added under the target's.
    - Where a hair vertex stands at rest is `hair_fit` (the target scene's extras; nothing for
      the standard head) times where it stands in the style's file. So the hair's inverse bind
      matrix for a joint is the inverse of that joint's rest in the target, times `hair_fit`;
      and a spring bone's rest in the target is `hair_fit` times its rest in the style's file.
    - `colour` (linear r, g, b) tints the hair's neutral shades, standing in for the mesh tag.
    Returns the names of the bones added."""
    h, hbin = read_glb(style_path)
    names = {n.get("name"): i for i, n in enumerate(j["nodes"])}
    fit = np.array((j["scenes"][j.get("scene", 0)].get("extras") or {}).get("hair_fit", {}).get("matrix", np.eye(4).T.ravel().tolist())).reshape(4, 4).T
    tskin = j["skins"][0]
    tworld = bind_world(j, binary, tskin)
    hnode = next(n for n in h["nodes"] if n.get("name") == ("FarHair" if far else "Hair") and "mesh" in n)
    hskin = h["skins"][hnode["skin"]]
    hworld = bind_world(h, hbin, hskin)
    hparent = {c: i for i, n in enumerate(h["nodes"]) for c in n.get("children", [])}
    # Joints: by name, adding the style's own bones under the target's.
    joint, added = {}, []

    def place(hn):
        name = h["nodes"][hn].get("name")
        if hn in joint:
            return joint[hn]
        if name in names:
            joint[hn] = names[name]
            return joint[hn]
        parent = place(hparent[hn])
        world = fit @ hworld[hn]
        tworld[len(j["nodes"])] = world
        local = np.linalg.inv(tworld[parent]) @ world
        j["nodes"].append(dict(name=name, matrix=[float(v) for v in local.T.ravel()]))
        j["nodes"][parent].setdefault("children", []).append(len(j["nodes"]) - 1)
        names[name] = joint[hn] = len(j["nodes"]) - 1
        added.append(name)
        return joint[hn]

    order = [place(hn) for hn in hskin["joints"]]
    ibm = np.array([np.linalg.inv(tworld[n]) @ fit for n in order])
    skin = dict(joints=order, inverseBindMatrices=append_accessor(j, binary, array("f", ibm.transpose(0, 2, 1).astype(np.float32).ravel().tolist()), 5126, "MAT4", False))
    j["skins"].append(skin)
    # The mesh: every accessor copied across; the material and its picture with it.
    def copy(acc, scale=None):
        values, (ct, typ, norm) = read_accessor(h, hbin, acc)
        if scale is not None:
            v = np.array(values, dtype=np.float64).reshape(-1, 4)
            v[:, :3] *= np.array(scale)
            values = array(COMPONENT[ct], v.ravel().tolist() if ct == 5126 else [int(round(x)) for x in v.ravel()])
        return append_accessor(j, binary, values, ct, typ, norm, None)

    mats = {}
    prims = []
    for p in h["meshes"][hnode["mesh"]]["primitives"]:
        q = dict(attributes={k: copy(a, scale=colour if k == "COLOR_0" and colour is not None else None) for k, a in p["attributes"].items()}, mode=p.get("mode", 4))
        if "indices" in p:
            q["indices"] = copy(p["indices"])
        mi = p.get("material")
        if mi is not None:
            if mi not in mats:
                m = json.loads(json.dumps(h["materials"][mi]))
                tex = (m.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
                if tex is not None:
                    t = json.loads(json.dumps(h["textures"][tex["index"]]))
                    img = json.loads(json.dumps(h["images"][t["source"]]))
                    if "bufferView" in img:
                        bv = h["bufferViews"][img["bufferView"]]
                        data = bytes(hbin[bv.get("byteOffset", 0) : bv.get("byteOffset", 0) + bv["byteLength"]])
                        while len(binary) % 4:
                            binary.append(0)
                        j["bufferViews"].append(dict(buffer=0, byteOffset=len(binary), byteLength=len(data)))
                        binary.extend(data)
                        img["bufferView"] = len(j["bufferViews"]) - 1
                    else:
                        there = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(style_path)), img["uri"]))
                        img["uri"] = os.path.relpath(there, os.path.dirname(os.path.abspath(out_path))).replace(os.sep, "/")
                    j.setdefault("images", []).append(img)
                    t["source"] = len(j["images"]) - 1
                    if "sampler" in t:
                        j.setdefault("samplers", []).append(json.loads(json.dumps(h["samplers"][t["sampler"]])))
                        t["sampler"] = len(j["samplers"]) - 1
                    j.setdefault("textures", []).append(t)
                    tex["index"] = len(j["textures"]) - 1
                j["materials"].append(m)
                mats[mi] = len(j["materials"]) - 1
            q["material"] = mats[mi]
        prims.append(q)
    j["meshes"].append(dict(name=hnode["name"], primitives=prims))
    j["nodes"].append(dict(name=hnode["name"], mesh=len(j["meshes"]) - 1, skin=len(j["skins"]) - 1))
    root = next((n for n in j["nodes"] if "children" in n and any("mesh" in j["nodes"][c] for c in n["children"])), None)
    if root is not None:
        root["children"].append(len(j["nodes"]) - 1)
    else:
        j["scenes"][j.get("scene", 0)]["nodes"].append(len(j["nodes"]) - 1)
    # The spring chains, in the file's VRM block, as the generator lists them (the game swings them).
    hv = ((h.get("extensions") or {}).get("VRM") or {}).get("secondaryAnimation") or {}
    tv = ((j.get("extensions") or {}).get("VRM") or {}).setdefault("secondaryAnimation", {})
    hname = [n.get("name") for n in h["nodes"]]
    if hv.get("boneGroups") and not far:
        if not tv.get("colliderGroups"):
            tv["colliderGroups"] = [dict(g, node=names[hname[g["node"]]]) for g in hv.get("colliderGroups", []) if hname[g["node"]] in names]
        tv.setdefault("boneGroups", []).extend(dict(g, bones=[names[hname[b]] for b in g["bones"]], colliderGroups=[c for c in g.get("colliderGroups", []) if c < len(tv["colliderGroups"])]) for g in hv["boneGroups"])
    return added


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

    def local_matrix(n):
        return np.array(n["matrix"]).reshape(4, 4).T if "matrix" in n else local(n)

    def w(i):  # noqa: F811
        if i not in world:
            world[i] = (w(parent[i]) if i in parent else np.eye(4)) @ local_matrix(nodes[i])
        return world[i]

    skin_of = {n["mesh"]: n.get("skin", 0) for n in nodes if "mesh" in n}
    pose = {}
    out = []
    for mi, mesh in enumerate(j["meshes"]):
        si = skin_of.get(mi, 0)
        if si not in pose:
            skin = j["skins"][si]
            ibm = np.array(read_accessor(j, binary, skin["inverseBindMatrices"])[0]).reshape(-1, 4, 4).transpose(0, 2, 1)
            pose[si] = np.array([w(jn) @ ibm[k] for k, jn in enumerate(skin["joints"])])
        mats = pose[si]
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
    ap.add_argument("--hair", help="a shared hair style's file (lookdev/styles/hair/<style>.glb) to attach, the client's way")
    ap.add_argument("--hair-colour", help="the hair's colour, `#rrggbb`, standing in for the client's mesh tag")
    ap.add_argument("--far-hair", action="store_true", help="attach the style's far mesh too (FarHair)")
    ap.add_argument("--drop", default="", help="mesh nodes to leave out, by the start of their names, comma-separated (`Far`: today's client draws a file's far meshes over its near ones)")
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
    if a.hair:
        colour = None
        if a.hair_colour:
            c = [int(a.hair_colour.lstrip("#")[k : k + 2], 16) / 255 for k in (0, 2, 4)]
            colour = [((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c]
        added = attach_hair(j, binary, a.hair, a.out, colour)
        if a.far_hair:
            attach_hair(j, binary, a.hair, a.out, colour, far=True)
        print(f"compose: {a.out}: hair from {a.hair}: {len(added)} bones added under the cranium")
    for start in [x for x in a.drop.split(",") if x]:
        gone = {i for i, n in enumerate(j["nodes"]) if "mesh" in n and (n.get("name") or "").startswith(start)}
        for n in j["nodes"]:
            if "children" in n:
                n["children"] = [c for c in n["children"] if c not in gone]
        for sc in j["scenes"]:
            sc["nodes"] = [c for c in sc["nodes"] if c not in gone]
    moved = compose(j, values)
    write_glb(a.out, j, binary)
    print(f"compose: {a.out}: {len(values)} values, {len(moved)} bones moved from rest")


if __name__ == "__main__":
    main()
