#!/usr/bin/env python3
"""Check a person composed from shared files against the rule, and against their own per-person file.

    python3 living/tools/characters/person_check.py COMPOSED.glb NAME.params.json [--own OWN.glb] [--styles DIR]

COMPOSED is a type's file with a hair style, outfit pieces and identity values put on it by
compose.py --person (the client's way). Two questions:

1. **Is the file what the rule says?** Each attached mesh, as a glTF reader evaluates it, against
   the generator's rule applied to the style file's own vertices: for hair and head pieces the
   type's `hair_fit` and then the identity bones' matrices (cage_head.bone_matrices), for body
   pieces nothing (they are bound to the J_Bip_* bones every file shares). This should be 0.
2. **How far is it from the person's own file?** (`--own`: the per-person file gen_person.sh
   makes, with this person's girth, belly and hair built into its meshes.) Both are posed by the
   client's proportions (characters.rs `bone_scale`, repeated here): the composed one by its
   person line's, the own file by its recipe's. This is not 0: a shared piece has the standard
   build and the bones give it the person's, and a shared hair style is not the person's own hair.

Plain Python and numpy.
"""

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "blender"))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import cage_head  # noqa: E402
import compose  # noqa: E402
import hair_fit  # noqa: E402
from merge_primitives import read_accessor, read_glb  # noqa: E402


def bone_scale(name, p):
    """The client's proportions on a bone (characters.rs `bone_scale`): ("own", (x, y, z)) scales the
    bone's own vertices and its children's offsets; ("all", k) scales it and everything below."""
    g = p.get("build", 1.0)
    get = lambda k: p.get(k, 1.0)
    lerp = lambda a, b, t: a + (b - a) * t
    chest = g * get("shoulders")
    side = name[8:] if name.startswith(("J_Bip_L_", "J_Bip_R_")) else None
    table = {"J_Bip_C_Hips": ("own", (g * get("hips"), 1.0, g * get("hips") ** 0.5)), "J_Bip_C_Spine": ("own", (g * lerp(1.0, get("hips"), 0.5), get("torso"), g)),
             "J_Bip_C_Chest": ("own", (lerp(g, chest, 0.5), get("torso"), g)), "J_Bip_C_UpperChest": ("own", (chest, get("torso"), g)), "J_Bip_C_Neck": ("own", (g ** 0.8, get("neck"), g ** 0.8)),
             "J_Bip_C_Head": ("all", get("head"))}
    sides = {"Shoulder": ("own", (chest, g, g)), "UpperArm": ("own", (get("arms"), g, g)), "LowerArm": ("own", (get("arms"), g ** 0.85, g ** 0.85)), "Hand": ("all", get("hands")),
             "UpperLeg": ("own", (g, get("legs"), g)), "LowerLeg": ("own", (g ** 0.85, get("legs"), g ** 0.85)), "Foot": ("all", get("feet"))}
    return table.get(name) or (sides.get(side) if side else None)


def shaped(path, want, proportions):
    """A file's vertices as the client poses them at rest with a recipe's proportions (before the
    whole figure is scaled to its height): {mesh node order: positions}, concatenated."""
    j, binary = read_glb(path)
    nodes = j["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}

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

    frame, skinm = {}, {}

    def world(i):  # (the frame its children hang in, the matrix its own vertices take)
        if i in frame:
            return frame[i], skinm[i]
        n = nodes[i]
        up = world(parent[i])[0] if i in parent else np.eye(4)
        loc = local(n)
        own_parent = bone_scale(nodes[parent[i]].get("name", ""), proportions) if i in parent else None
        if own_parent and own_parent[0] == "own":
            loc = loc.copy()
            loc[:3, 3] = loc[:3, 3] * np.array(own_parent[1])
        w = up @ loc
        s = bone_scale(n.get("name", ""), proportions)
        if s and s[0] == "all":
            w = w @ np.diag([s[1], s[1], s[1], 1.0])
            frame[i], skinm[i] = w, w
        elif s:
            frame[i], skinm[i] = w, w @ np.diag(list(s[1]) + [1.0])
        else:
            frame[i], skinm[i] = w, w
        return frame[i], skinm[i]

    skin_of = {n["mesh"]: n.get("skin", 0) for n in nodes if "mesh" in n}
    drawn = {n["mesh"] for sc in j["scenes"] for r in sc["nodes"] for n in walk(nodes, r) if "mesh" in n}
    out = []
    for mi, mesh in enumerate(j["meshes"]):
        if mi not in drawn:
            continue
        skin = j["skins"][skin_of.get(mi, 0)]
        ibm = np.array(read_accessor(j, binary, skin["inverseBindMatrices"])[0]).reshape(-1, 4, 4).transpose(0, 2, 1)
        mats = np.array([world(jn)[1] @ ibm[k] for k, jn in enumerate(skin["joints"])])
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
    return np.concatenate(out) if out else np.zeros((0, 3))


def walk(nodes, i):
    yield nodes[i]
    for c in nodes[i].get("children", []):
        yield from walk(nodes, c)


def near(a, b):
    d = np.empty(len(a))
    for i in range(0, len(a), 256):
        d[i : i + 256] = np.sqrt(((a[i : i + 256, None, :] - b[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
    return d * 1000


def rule(style_path, node, tid, values, fitted):
    """A style file's mesh as the rule places it on a person of type `tid` with `values`."""
    h, hb = read_glb(style_path)
    n = next(x for x in h["nodes"] if x.get("name") == node and "mesh" in x)
    names = [h["nodes"][i]["name"] for i in h["skins"][n["skin"]]["joints"]]
    out = []
    if fitted:
        hf = hair_fit.head(tid)
        mats = cage_head.bone_matrices(hf, values)
        F = hair_fit.fit(tid)[0]
        off = np.array([0.0, -0.004, 1.535 - hf.chin_z])
        P = hair_fit.FILE_FROM_FORM
    for p in h["meshes"][n["mesh"]]["primitives"]:
        pos = np.array(read_accessor(h, hb, p["attributes"]["POSITION"])[0]).reshape(-1, 3)
        if not fitted:
            out.append(pos)
            continue
        jt = np.array(read_accessor(h, hb, p["attributes"]["JOINTS_0"])[0]).reshape(-1, 4)
        wt = np.array(read_accessor(h, hb, p["attributes"]["WEIGHTS_0"])[0]).reshape(-1, 4)
        form = (pos @ F[:3, :3].T + F[:3, 3]) @ P - off
        ph = np.concatenate([form, np.ones((len(form), 1))], axis=1)
        acc = np.zeros((len(pos), 3))
        for k in range(4):
            M = np.array([mats["J_Id_Cranium"] if names[i].startswith("J_Sec") else mats.get(names[i], np.eye(4)) for i in jt[:, k]])
            acc += wt[:, k : k + 1] * np.einsum("nij,nj->ni", M, ph)[:, :3]
        out.append((acc + off) @ P.T)
    return np.concatenate(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("composed")
    ap.add_argument("params")
    ap.add_argument("--own", help="the person's own per-person file, to measure against")
    ap.add_argument("--styles", default="living/game/assets/lookdev/styles")
    a = ap.parse_args()
    doc = json.load(open(a.params))
    line = doc["person"]
    tid, values = line["type"], line.get("identity") or {}
    # 1. Against the rule.
    hair = os.path.join(a.styles, "hair", line["styles"]["hair"] + ".glb")
    hj, _ = read_glb(hair)
    expect = {"Hair": [rule(hair, "Hair", tid, values, True)], "Cloth": []}
    if any(n.get("name") == "Cloth" and "mesh" in n for n in hj["nodes"]):
        expect["Cloth"].append(rule(hair, "Cloth", tid, values, True))
    for name in line["styles"]["outfit"]:
        expect["Cloth"].append(rule(os.path.join(a.styles, "outfit", name + ".glb"), "Cloth", tid, values, name in ("cap", "kerchief")))
    for mesh, parts in expect.items():
        if not parts:
            continue
        want = np.concatenate(parts)
        got = compose.skinned(a.composed, lambda m, material, mesh=mesh: m == mesh)
        d = np.linalg.norm(got - want, axis=1) * 1000 if len(got) == len(want) else np.array([float("nan")])
        print(f"person_check: {mesh}: {len(got)} vertices from {len(parts)} file(s); as read against the rule: {np.sqrt((d ** 2).mean()):.3f} mm rms, {d.max():.3f} mm at most")
    # 2. Against the person's own file, both posed by the client's proportions.
    if a.own:
        kinds = (("face skin", lambda m, mat: mat.endswith("Face_00_SKIN")), ("hair", lambda m, mat: mat.endswith("_HAIR")), ("clothes", lambda m, mat: mat.endswith("_CLOTH")), ("neck and hands", lambda m, mat: m == "Skin"))
        for kind, want in kinds:
            ca, ob = shaped(a.composed, want, line["proportions"]), shaped(a.own, want, doc["recipe"]["proportions"])
            if not len(ca) or not len(ob):
                continue
            # The type's file keeps the whole scalp and the person's own file cuts it under the hair,
            # so the face is measured from the own file's side; the rest from the composed side.
            d = near(ob, ca) if kind == "face skin" else near(ca, ob)
            print(f"person_check: {kind}: composed ({len(ca)} vertices) against the person's own file ({len(ob)}): {np.sqrt((d ** 2).mean()):.1f} mm rms, {np.percentile(d, 95):.1f} at the 95th percentile, {d.max():.1f} at most")


if __name__ == "__main__":
    main()
