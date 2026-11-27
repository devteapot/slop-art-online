"""Build a body-only foundation GLB from the shared clip library."""

import argparse
import sys
from array import array
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1])]
from cage import BASE, FN, MORPHS, NTOR, full, srgb, topology
from merge_primitives import append_accessor, read_glb, write_glb

PRESETS = {
    "base": (1.80, {}),
    "woman": (1.67, {"Build_Slim": 0.23, "Face_Round": 0.16}),
    "man": (1.86, {"Sex_Male": 1.0, "Jaw_Square": 0.65, "Build_Heavy": 0.20}),
    "elder": (1.70, {"Sex_Male": 0.7, "Age_Elder": 1.0, "Face_Long": 0.5}),
    "child": (1.20, {"Age_Child": 1.0, "Face_Round": 0.65}),
}
MATERIALS = {
    "skin": "#e8bda5",
    "face": "#e8bda5",
    "top": "#74869a",
    "shorts": "#3e4b5a",
    "shoes": "#5a4951",
    "band": "#495a68",
}


def rest(doc):
    matrices = {}

    def visit(i, parent):
        node = doc["nodes"][i]
        x, y, z, w = node.get("rotation", [0, 0, 0, 1])
        local = Matrix.LocRotScale(
            Vector(node.get("translation", [0, 0, 0])),
            Quaternion((w, x, y, z)),
            Vector(node.get("scale", [1, 1, 1])),
        )
        matrices[i] = parent @ local
        for child in node.get("children", []):
            visit(child, matrices[i])

    visit(next(i for i, n in enumerate(doc["nodes"]) if n["name"] == "Armature"), Matrix.Identity(4))
    return matrices


def axes(points):
    return np.asarray(points)[..., [0, 2, 1]] * [-1, 1, 1]


def weights(key, point):
    tag, *idx = key
    side = "R" if tag.startswith("R") else "L"
    tag = tag.removeprefix("R")
    limb = "J_Bip_" + side + "_"
    center = "J_Bip_C_"

    def along(names, anchors, x):
        i = np.clip(np.searchsorted(anchors, x) - 1, 0, len(names) - 2)
        t = np.clip((x - anchors[i]) / (anchors[i + 1] - anchors[i]), 0, 1)
        t = t * t * (3 - 2 * t)
        return {names[i]: 1 - t, names[i + 1]: t}

    if tag in ("F", "TH"):
        finger, r = (FN[idx[0]], idx[1]) if tag == "F" else ("Thumb", idx[0])
        return along([limb + finger + str(i) for i in (1, 2, 3)], [1, 2.8, 4], r)
    if tag == "A":
        r = idx[0]
        if r <= 3:
            return along([limb + "Shoulder", limb + "UpperArm"], [-0.8, 2], r)
        if r <= 7:
            return along([limb + "UpperArm", limb + "LowerArm"], [3.7, 6.3], r)
        return along([limb + "LowerArm", limb + "Hand"], [8, 10], r)
    if tag in ("L", "LP"):
        r = idx[0] if idx else 15
        if r < 3:
            side_mix = np.clip(0.5 + point[0] / (0.20 if r == 1 else 0.09), 0.0, 1.0)
            leg_share = 0.78 if r == 1 else 0.97
            return {
                center + "Hips": 1 - leg_share,
                "J_Bip_L_UpperLeg": leg_share * side_mix,
                "J_Bip_R_UpperLeg": leg_share * (1 - side_mix),
            }
        if r < 9:
            return along([limb + "UpperLeg", limb + "LowerLeg"], [3.65, 6.35], r)
        return along([limb + "LowerLeg", limb + "Foot", limb + "ToeBase"], [9, 11.4, 14], r)
    # Blend the saddle across both femurs so the medial thigh does not pull
    # against a rigid perineal pole when the legs rotate out in a ground sit.
    if tag == "C" or tag == "T" and idx[0] <= 1:
        leg_share = 0.68 if tag == "C" else (0.54 if idx[0] == 0 else 0.14)
        side_mix = np.clip(0.5 + point[0] / 0.13, 0.0, 1.0)
        return {
            center + "Hips": 1 - leg_share,
            "J_Bip_L_UpperLeg": leg_share * side_mix,
            "J_Bip_R_UpperLeg": leg_share * (1 - side_mix),
        }
    if tag in ("HP", "E") or idx[0] >= NTOR:
        return {center + "Head": 1}
    r = idx[0]
    if 7 <= r <= 10:
        cuff = np.clip((abs(point[0]) - 0.063) / 0.074, 0, 1)
        side = "L" if point[0] >= 0 else "R"
        upper = cuff * (0.27 if r <= 8 else 0.14)
        return {
            center + "UpperChest": 1 - cuff,
            f"J_Bip_{side}_Shoulder": cuff - upper,
            f"J_Bip_{side}_UpperArm": upper,
        }
    return along(
        [center + n for n in ["Hips", "Spine", "Chest", "UpperChest", "Neck", "Head"]],
        [1, 3, 6, 10, 12.5, 14],
        r,
    )


def subdivide(points, faces, skin, level):
    me = bpy.data.meshes.new("Body cage")
    me.from_pydata(points.tolist(), [], [f for f, m in faces])
    for name in MATERIALS:
        me.materials.append(bpy.data.materials.new(name))
    for poly, (_, mat) in zip(me.polygons, faces):
        poly.material_index = list(MATERIALS).index(mat)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Body cage", me)
    bpy.context.collection.objects.link(ob)
    for i, ws in enumerate(skin):
        for name, w in ws.items():
            group = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
            group.add([i], w, "REPLACE")
    sub = ob.modifiers.new("Catmull-Clark", "SUBSURF")
    sub.levels = level

    def evaluate(coords):
        me.vertices.foreach_set("co", coords.ravel())
        me.update()
        bpy.context.view_layer.update()
        return ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).data

    return ob, evaluate


def generate(args):
    doc, buf = read_glb(args.rig)
    mats = rest(doc)
    indices = [i for i in mats if doc["nodes"][i]["name"] != "Armature"]
    assert len(indices) == 82
    names = [doc["nodes"][i]["name"] for i in indices]
    joints = {name: axes(mats[i].translation) for i, name in zip(indices, names)}
    faces = topology()
    keys = list(dict.fromkeys(k for face, _ in faces for k in face))
    ids = {k: i for i, k in enumerate(keys)}
    faces = [([ids[k] for k in face], "band" if face[0][:2] == ("T", 2) else m) for face, m in faces]

    def coords(params):
        verts = full(params, joints)
        return np.array([verts[k] for k in keys])

    points = coords(BASE)
    skin = [weights(k, p) for k, p in zip(keys, points)]
    ob, evaluate = subdivide(points, faces, skin, args.level)

    def surface(coords):
        me = evaluate(coords)
        return tuple(axes([tuple(getattr(v, field)) for v in me.vertices]) for field in ("co", "normal"))

    base, normals = surface(points)
    me = evaluate(points)
    me.calc_loop_triangles()
    triangles = [(list(t.vertices), t.material_index) for t in me.loop_triangles]
    influences = np.zeros((len(me.vertices), len(names)))
    for v in me.vertices:
        for g in v.groups:
            influences[v.index, names.index(ob.vertex_groups[g.group].name)] = g.weight
    js = np.argsort(-influences, axis=1)[:, :4]
    ws = np.take_along_axis(influences, js, axis=1)
    assert np.all(ws.sum(axis=1) > 0)
    ws /= ws.sum(axis=1)[:, None]

    def acc(values, typ, ct=5126):
        code = {5126: "f", 5123: "H"}[ct]
        return append_accessor(doc, buf, array(code, np.asarray(values).ravel()), ct, typ, False)

    height, mix = PRESETS[args.preset]
    mix = dict(mix)
    for expression in args.weight:
        name, val = expression.split("=")
        if name not in MORPHS or not 0 <= float(val) <= 1:
            raise ValueError(expression)
        mix[name] = float(val)
    if args.build is not None:
        mix["Build_Heavy"] = max(args.build, 0)
        mix["Build_Slim"] = max(-args.build, 0)
    shaped = base.copy()
    targets = []
    for name, over in MORPHS.items():
        v, n = surface(coords(BASE | over))
        delta = v - base
        targets.append((delta, n - normals))
        shaped += mix.get(name, 0) * delta
    primitives = []
    for m in range(len(MATERIALS)):
        tri = [t for t, material in triangles if material == m]
        used, local = np.unique(np.asarray(tri).ravel(), return_inverse=True)
        attrs = {
            "POSITION": acc(base[used], "VEC3"),
            "NORMAL": acc(normals[used], "VEC3"),
            "JOINTS_0": acc(js[used], "VEC4", 5123),
            "WEIGHTS_0": acc(ws[used], "VEC4"),
        }
        shapes = [
            {"POSITION": acc(delta[used], "VEC3"), "NORMAL": acc(dn[used], "VEC3")} for delta, dn in targets
        ]
        primitives.append(
            {"attributes": attrs, "indices": acc(local, "SCALAR", 5123), "material": m, "targets": shapes}
        )
    doc["materials"] = [
        {
            "name": ("Foundation_" + n + ("_SKIN" if n in ("skin", "face") else "_CLOTH")),
            "pbrMetallicRoughness": {
                "baseColorFactor": srgb(c),
                "metallicFactor": 0,
                "roughnessFactor": 0.91,
            },
        }
        for n, c in MATERIALS.items()
    ]
    doc["meshes"] = [
        {
            "name": "Foundation",
            "primitives": primitives,
            "weights": [mix.get(n, 0) for n in MORPHS],
            "extras": {"targetNames": list(MORPHS)},
        }
    ]
    # The child's rest offsets follow its shorter limbs. Hips motion is shared;
    # a constant armature offset keeps the soles at ground level.
    child = mix.get("Age_Child", 0)
    root = next(i for i, n in enumerate(doc["nodes"]) if n["name"] == "Armature")
    doc["nodes"][root]["translation"] = [0, -0.17 * joints["J_Bip_L_UpperLeg"][2] * child, 0]
    if child:
        # Scale animated hips translations by the leg-length ratio. The inverse
        # scale on Hips preserves torso size and the authored joint-local rotations.
        stride = 1 - 0.17 * child
        doc["nodes"][root]["scale"] = [stride] * 3
        doc["nodes"][root]["translation"][1] += (1 - stride) * joints["J_Bip_C_Hips"][2]
        doc["nodes"][indices[names.index("J_Bip_C_Hips")]]["scale"] = [1 / stride] * 3
    for i in indices:
        node = doc["nodes"][i]
        n = node["name"].split("_")[-1]
        if child and n in ("UpperArm", "UpperLeg"):
            factor = 1 - (0.18 if n == "UpperArm" else 0.17) * child
            node["scale"] = [factor] * 3
    mats = rest(doc)
    doc["skins"] = [
        {
            "joints": indices,
            "inverseBindMatrices": acc([np.array(mats[i].inverted()).T for i in indices], "MAT4"),
        }
    ]
    fig = next(i for i, n in enumerate(doc["nodes"]) if n["name"] == "Figure")
    doc["nodes"][fig] = {"name": "Foundation", "mesh": 0, "skin": 0}
    scale = (args.height or height) / np.ptp(shaped[:, 1])
    scene = doc["scenes"][0]
    doc["nodes"].append(
        {
            "name": "Foundation height",
            "children": scene["nodes"],
            "scale": [scale] * 3,
            "rotation": [0, 1, 0, 0],
        }
    )
    scene["nodes"] = [len(doc["nodes"]) - 1]
    args.out.parent.mkdir(exist_ok=True, parents=True)
    write_glb(args.out, doc, buf)
    print(args.out, len(triangles), "triangles", scale * np.ptp(shaped[:, 1]), "m")


parser = argparse.ArgumentParser()
parser.add_argument("out", type=Path)
parser.add_argument(
    "--rig", type=Path, default=Path("~/slop-assets/current/assets/lookdev/anim/own-clips.glb").expanduser()
)
parser.add_argument("--level", type=int, choices=[1, 2], default=1)
parser.add_argument("--preset", choices=list(PRESETS), default="base")
parser.add_argument("--weight", action="append", default=[])
parser.add_argument("--height", type=float)
parser.add_argument("--build", type=float)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
if (args.build is not None and not -1 <= args.build <= 1) or (
    args.height is not None and not 0 < args.height < float("inf")
):
    parser.error("invalid height or build")
generate(args)
