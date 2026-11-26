"""Run in Blender with the MPFB extension enabled. See README.md."""

import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
import addon_utils
import bpy
from mathutils import Matrix, Vector, Quaternion
from mathutils.bvhtree import BVHTree

addon_utils.enable("bl_ext.user_default.mpfb", default_set=True)
from bl_ext.user_default.mpfb.services.humanservice import HumanService
from bl_ext.user_default.mpfb.services.targetservice import TargetService
from bl_ext.user_default.mpfb.services.locationservice import LocationService

output, clip_file = map(Path, sys.argv[sys.argv.index("--") + 1 :])
output.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()
# Keep exactly the two animation takes needed to drive the inspection.
raw = clip_file.read_bytes()
size = struct.unpack_from("<I", raw, 12)[0]
doc = json.loads(raw[20 : 20 + size])
doc["animations"] = [a for a in doc["animations"] if a["name"] in ("idle", "walk")]
# The shared clip file carries a node hierarchy without a skin. Supply inverse
# bind matrices from its authored rest transforms so Blender imports real bones.
payload = bytearray(raw[28 + size :])


def accessor(data, kind, component, count):
    payload.extend(bytes(-len(payload) % 4))
    offset = len(payload)
    payload.extend(data)
    doc["bufferViews"].append(dict(buffer=0, byteOffset=offset, byteLength=len(data)))
    doc["accessors"].append(
        dict(bufferView=len(doc["bufferViews"]) - 1, componentType=component, count=count, type=kind)
    )
    return len(doc["accessors"]) - 1


joints = []
inverses = []


def walk_joint(i, parent):
    n = doc["nodes"][i]
    x, y, z, w = n.get("rotation", (0, 0, 0, 1))
    world = parent @ Matrix.LocRotScale(
        Vector(n.get("translation", (0, 0, 0))), Quaternion((w, x, y, z)), Vector(n.get("scale", (1, 1, 1)))
    )
    joints.append(i)
    inverses.extend(k for row in world.inverted().transposed() for k in row)
    for c in n.get("children", []):
        walk_joint(c, world)


root = next(i for i, n in enumerate(doc["nodes"]) if n["name"] == "Root")
walk_joint(root, Matrix.Identity(4))
ibm = accessor(struct.pack("<" + "f" * len(inverses), *inverses), "MAT4", 5126, len(joints))
doc["skins"] = [dict(joints=joints, inverseBindMatrices=ibm)]
figure = next(n for n in doc["nodes"] if n.get("mesh") == 0)
figure["skin"] = 0
attrs = doc["meshes"][0]["primitives"][0]["attributes"]
count = doc["accessors"][attrs["POSITION"]]["count"]
attrs["JOINTS_0"] = accessor(bytes(4 * count), "VEC4", 5121, count)
attrs["WEIGHTS_0"] = accessor(struct.pack("<4f", 1, 0, 0, 0) * count, "VEC4", 5126, count)
doc["buffers"][0]["byteLength"] = len(payload)
header = json.dumps(doc).encode()
header += b" " * (-len(header) % 4)
binary = struct.pack("<I4s", len(payload), b"BIN\0") + payload
inspection = output / "inspection-rig.glb"
inspection.write_bytes(
    struct.pack("<4sIIII", b"glTF", 2, 20 + len(header) + len(binary), len(header), 0x4E4F534A) + header + binary
)
bpy.ops.import_scene.gltf(filepath=str(inspection))
game = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
for obj in list(bpy.context.scene.objects):
    if obj != game:
        bpy.data.objects.remove(obj, do_unlink=True)
game.animation_data.action = None
for track in game.animation_data.nla_tracks:
    track.mute = True
for bone in game.pose.bones:
    bone.matrix_basis.identity()
bpy.context.view_layer.update()

macro = TargetService.get_default_macro_info_dict()
macro.update(age=0.39, gender=0.12, proportions=0.39, muscle=0.52, weight=0.46)
human = HumanService.create_human(mask_helpers=False, macro_detail_dict=macro)
targets = Path(LocationService.get_mpfb_data("targets"))
details = {
    "nose/nose-scale-depth-decr": 0.74,
    "nose/nose-volume-decr": 0.5,
    "mouth/mouth-scale-horiz-decr": 0.43,
    "mouth/mouth-upperlip-volume-decr": 0.38,
    "chin/chin-height-decr": 0.65,
    "chin/chin-width-decr": 0.38,
    "chin/chin-jaw-drop-decr": 0.22,
    "mouth/mouth-lowerlip-volume-decr": 0.66,
    "mouth/mouth-lowerlip-height-decr": 0.54,
    "mouth/mouth-upperlip-height-decr": 0.55,
    "breast/nipple-point-decr": 0.9,
    "breast/nipple-size-decr": 0.8,
    "head/head-invertedtriangular": 0.26,
    "head/head-scale-horiz-incr": 0.32,
}
for side in ("l", "r"):
    for target, weight in (
        ("scale-incr", 1.1),
        ("height1-incr", 0.62),
        ("height2-incr", 0.55),
        ("height3-incr", 0.40),
    ):
        details[f"eyes/{side}-eye-{target}"] = weight
for target, weight in details.items():
    TargetService.load_target(human, str(targets / (target + ".target.gz")), weight=weight)
human.update_tag()
rig = HumanService.add_builtin_rig(human, "mixamo")
bpy.context.view_layer.update()
# Preserve the native A-pose, targets and rig separately for future edits.
bpy.ops.wm.save_as_mainfile(filepath=str(output / "mpfb-source.blend"), compress=True, copy=True)
mesh = human.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
points = [v.co.copy() for v in mesh.vertices]
groups = {g.name: g.index for g in human.vertex_groups}


def members(group):
    index = groups[group]
    return {v.index for v in mesh.vertices if any(g.group == index for g in v.groups)}


# Expand the socket and its helper landmarks together. The displacement fades
# to zero before the nose bridge and outer temple to preserve the facial loops.
eye_centers = [
    sum((points[i] for i in members("joint-" + side + "-eye")), Vector()) / len(members("joint-" + side + "-eye"))
    for side in ("l", "r")
]
for v in points:
    c = min(eye_centers, key=lambda p: abs(p.x - v.x))
    d = v - c
    influence = math.exp(-((d.x / 0.028) ** 4 + (d.z / 0.020) ** 4 + (d.y / 0.037) ** 4))
    v.x += d.x * 0.31 * influence
    v.z += d.z * 0.36 * influence
body = members("body")
lips = members("lips")
native_faces = [p for p in mesh.polygons if all(i in body for i in p.vertices)]
faces = [tuple(p.vertices) for p in native_faces]
surface = BVHTree.FromPolygons(points, faces)


def bone_map():
    mapping = {
        s: "J_Bip_C_" + t
        for s, t in zip(
            ("Hips", "Spine", "Spine1", "Spine2", "Neck", "Head"),
            ("Hips", "Spine", "Chest", "UpperChest", "Neck", "Head"),
        )
    }
    for word, side in (("Left", "L"), ("Right", "R")):
        prefix = "J_Bip_" + side + "_"
        for s, t in zip(
            ("Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase"),
            ("Shoulder", "UpperArm", "LowerArm", "Hand", "UpperLeg", "LowerLeg", "Foot", "ToeBase"),
        ):
            mapping[word + s] = prefix + t
        for f in ("Index", "Middle", "Ring", "Pinky", "Thumb"):
            for i in (1, 2, 3):
                mapping[f"{word}Hand{f}{i}"] = f"{prefix}{'Little' if f=='Pinky' else f}{i}"
    return mapping


names = bone_map()
source = {n: rig.data.bones["mixamorig:" + n].head_local.copy() for n in names}
dest = {n: game.matrix_world @ game.data.bones[g].head_local for n, g in names.items()}
flip = Matrix.Rotation(math.pi, 3, "Z")


# Choose roll from the palm's transverse axis so all five digits keep their spread.
def frame(axis, transverse):
    x = axis.normalized()
    z = x.cross(transverse).normalized()
    return Matrix((x, z.cross(x), z)).transposed()


transforms = {}
for name in names:
    side = "Left" if name.startswith("Left") else "Right"
    child = None
    for chain in (
        ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head"],
        [side + x for x in ("Shoulder", "Arm", "ForeArm", "Hand", "HandMiddle1")],
        [side + x for x in ("UpLeg", "Leg", "Foot", "ToeBase")],
    ):
        if name in chain[:-1]:
            child = chain[chain.index(name) + 1]
    hand = name.startswith(side + "Hand")
    if hand and name[-1:].isdigit():
        child = name[:-1] + str(int(name[-1]) + 1) if name[-1] != "3" else None
    parent = rig.data.bones["mixamorig:" + name].parent
    previous = parent.name.split(":")[-1] if parent else None
    a = source[child] - source[name] if child else source[name] - source[previous]
    b = dest[child] - dest[name] if child else dest[name] - dest[previous]
    rotation = (flip @ a).rotation_difference(b).to_matrix() @ flip
    if hand:
        across = side + "HandIndex1", side + "HandPinky1"
        rotation = (
            frame(b, dest[across[0]] - dest[across[1]])
            @ frame(a, source[across[0]] - source[across[1]]).transposed()
        )
    scale = max(0.83, min(1.45, b.length / a.length))
    if name == "Head":
        rotation = flip
        scale = 0.228 / (max(points[i].z for i in body) - source[name].z)
    transforms[name] = rotation * scale


def transformed(p, n):
    return dest[n] + transforms[n] @ (p - source[n])


def material(name, rgb):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*rgb, 1)
    m.use_nodes = True
    bs = m.node_tree.nodes.get("Principled BSDF")
    bs.inputs["Base Color"].default_value = (*rgb, 1)
    bs.inputs["Roughness"].default_value = 0.86
    return m


skin = material("Porcelain warm_SKIN", (0.69, 0.39, 0.275))
ink = material("Upper lid umber_FACE", (0.035, 0.017, 0.019))
white = material("Warm sclera_EYE", (0.86, 0.78, 0.68))
iris = material("Iris teal_EYE", (0.068, 0.30, 0.28))
light = material("Eye glint_EYE", (0.98, 0.93, 0.78))


def bind(o):
    o.parent = game
    mod = o.modifiers.new("Shared character skeleton", "ARMATURE")
    mod.object = game
    return o


def surface_object(name, verts, polys, mats):
    m = bpy.data.meshes.new(name)
    m.from_pydata(verts, [], polys)
    m.update()
    o = bpy.data.objects.new(name, m)
    bpy.context.collection.objects.link(o)
    for mat in mats:
        m.materials.append(mat)
    for p in m.polygons:
        p.use_smooth = True
    return bind(o)


ids = sorted(body)
index = {v: i for i, v in enumerate(ids)}
verts = []
weights = []
for i in ids:
    ws = [
        (human.vertex_groups[w.group].name.split(":")[-1], w.weight)
        for w in mesh.vertices[i].groups
        if human.vertex_groups[w.group].name.startswith("mixamorig:") and w.weight > 0
    ]
    ws = sorted(ws, key=lambda pair: -pair[1])[:4]
    if not ws:
        raise RuntimeError(f"Missing body weight {i}")
    total = sum(w for n, w in ws)
    ws = [(n, w / total) for n, w in ws]
    verts.append(sum((transformed(points[i], n) * w for n, w in ws), Vector()))
    weights.append(ws)
o = surface_object("Cullet base", verts, [[index[i] for i in f] for f in faces], [skin])
native_uv = mesh.uv_layers.active
if native_uv:
    uv = o.data.uv_layers.new(name="HM08")
    for poly, original in zip(o.data.polygons, native_faces):
        for new, old in zip(poly.loop_indices, original.loop_indices):
            uv.data[new].uv = native_uv.data[old].uv
# Relax the transferred weight field along surface edges at major joints.
# Short edges get more weight so dense crease loops share the bend.
bone_order = list(names)
channels = np.zeros((len(verts), len(names)))
for i, ws in enumerate(weights):
    for n, w in ws:
        channels[i, bone_order.index(n)] = w
edges = np.array([tuple(e.vertices) for e in o.data.edges])
a, b = np.concatenate((edges, edges[:, ::-1])).T
coords = np.array(verts)
conductance = 1 / np.maximum(0.001, np.linalg.norm(coords[a] - coords[b], axis=1))
degree = np.bincount(a, weights=conductance, minlength=len(verts))
major = [
    i
    for i, n in enumerate(bone_order)
    if n in {"Hips", "Spine2"} or n.endswith(("UpLeg", "Foot", "ToeBase", "Shoulder", "Arm"))
]
active = channels[:, major].sum(axis=1) > 0.015
for _ in range(5):
    nearby = np.zeros_like(channels)
    np.add.at(nearby, a, channels[b] * conductance[:, None])
    channels[active] = 0.45 * channels[active] + 0.55 * nearby[active] / degree[active, None]
vg = [o.vertex_groups.new(name=names[n]) for n in bone_order]
for i, row in enumerate(channels):
    keep = np.argsort(row)[-4:]
    for k in keep:
        if row[k] > 0:
            vg[k].add([i], float(row[k] / row[keep].sum()), "REPLACE")

# Use a separate paint UV for each side of the fitted underlayer. Its edges
# are continuous in metres across all triangles, including the armholes.
sys.path.insert(0, str(Path("living/tools/blender").resolve()))
from face_paint import shared_iris, lit_iris, write_png
from head_mesh import IRIS_FILL, IRIS_WIDE

paint_uv = o.data.uv_layers.new(name="Foundation paint")
o.data.uv_layers.active = paint_uv
paint_uv.active_render = True
for poly in o.data.polygons:
    front_side = poly.normal.y >= 0
    for li in poly.loop_indices:
        x, y, z = verts[o.data.loops[li].vertex_index]
        paint_uv.data[li].uv = ((x + 1) / 4 + (0 if front_side else 0.5), (z + 0.05) / 1.90)
# Two 1024 x 1024 panels. Colour is authored in sRGB and packed into the GLB.
N = 1024
x = np.broadcast_to((np.arange(N)[None, :] + 0.5) * 2 / N - 1, (N, N))
z = np.broadcast_to((1 - (np.arange(N)[:, None] + 0.5) / N) * 1.90 - 0.05, (N, N))
absx = np.abs(x)
lip_positions = np.array([tuple(verts[index[i]]) for i in lips])
mouth_z = (lip_positions[:, 2].min() + lip_positions[:, 2].max()) / 2
panels = []
for front_side in (True, False):
    rgb = np.zeros((N, N, 3), dtype=np.float32) + [217, 168, 143]

    def tint(colour, amount):
        global rgb
        a = np.clip(amount, 0, 1)[..., None]
        rgb = rgb * (1 - a) + np.array(colour) * a

    hip = dest["Hips"].z
    shoulder = dest["LeftArm"].z
    # The neck and arm openings form one bound fabric silhouette.
    neck = shoulder + 0.076 - (0.102 if front_side else 0.052) * np.exp(-((x / 0.089) ** 2))
    arm = 0.228 - 0.061 * np.clip((z - shoulder + 0.108) / 0.13, 0, 1)
    margin = np.minimum.reduce([neck - z, arm - absx, z - (hip - 0.025)])
    cloth = np.clip(margin / 0.002 + 0.5, 0, 1)
    tint((54, 94, 103), cloth)
    tint((110, 161, 153), cloth * np.clip((0.008 - margin) / 0.002, 0, 1))
    # A flatlock seam follows the side of the jersey.
    seam = 0.148 + 0.022 * np.clip((z - hip) / 0.38, 0, 1)
    tint((73, 119, 125), cloth * np.clip(1 - np.abs(absx - seam) / 0.002, 0, 1))
    hem = hip - 0.292 + 0.025 * (absx / 0.2) ** 2
    leg = np.minimum.reduce([z - hem, hip + 0.012 - z, 0.252 - absx])
    trouser = np.clip(leg / 0.002 + 0.5, 0, 1)
    tint((57, 68, 87), trouser)
    tint(
        (89, 115, 122),
        trouser * (np.clip((0.006 - (z - hem)) / 0.002, 0, 1) + np.clip((z - hip + 0.001) / 0.002, 0, 1)),
    )
    if front_side:
        mouth = (z - mouth_z) / 0.011
        taper = np.maximum(0, 1 - (x / 0.023) ** 2)
        tint((181, 114, 104), 0.56 * np.exp(-((mouth / 0.56) ** 2)) * taper)
        tint((136, 85, 77), 0.68 * np.exp(-(((mouth + 0.07 - 0.15 * (x / 0.023) ** 2) / 0.14) ** 2)) * taper)
        for sign in (-1, 1):
            ex = members("joint-" + ("l" if sign == 1 else "r") + "-eye")
            eye_pos = transformed(sum((points[i] for i in ex), Vector()) / len(ex), "Head")
            tint(
                (227, 145, 130),
                0.32 * np.exp(-(((x - 1.28 * eye_pos.x) / 0.027) ** 2) - ((z - eye_pos.z + 0.025) / 0.013) ** 2),
            )
    panels.append(np.uint8(np.clip(rgb, 0, 255)))
body_file = output / "foundation.png"
write_png(str(body_file), np.concatenate(panels, axis=1))
o.data.materials.clear()
o.data.materials.append(skin)
for polygon in o.data.polygons:
    polygon.material_index = 0
tex = skin.node_tree.nodes.new("ShaderNodeTexImage")
tex.image = bpy.data.images.load(str(body_file))
tex.image.pack()
uv_node = skin.node_tree.nodes.new("ShaderNodeUVMap")
uv_node.uv_map = paint_uv.name
skin.node_tree.links.new(uv_node.outputs["UV"], tex.inputs["Vector"])
skin.node_tree.links.new(tex.outputs["Color"], skin.node_tree.nodes["Principled BSDF"].inputs["Base Color"])


def head_object(name, verts, faces, mat):
    ob = surface_object(name, [transformed(p, "Head") for p in verts], faces, [mat])
    ob.vertex_groups.new(name=names["Head"]).add(list(range(len(verts))), 1, "REPLACE")
    return ob


def front(x, z, y):
    hit = surface.ray_cast(Vector((x, -0.8, z)), Vector((0, 1, 0)))[0]
    return hit.y if hit else y


def oval(name, c, r, mat):
    rings, steps = (5, 12) if mat == light else (12, 32)
    vs = [c + Vector((0, 0, r.z))]
    fs = []
    for j in range(1, rings):
        phi = math.pi * j / rings
        for i in range(steps):
            a = math.tau * i / steps
            vs.append(
                c
                + Vector(
                    (r.x * math.sin(phi) * math.cos(a), r.y * math.sin(phi) * math.sin(a), r.z * math.cos(phi))
                )
            )
    south = len(vs)
    vs.append(c - Vector((0, 0, r.z)))
    for i in range(steps):
        nxt = (i + 1) % steps
        fs.append((0, 1 + i, 1 + nxt))
        for j in range(rings - 2):
            k = 1 + j * steps
            fs.append((k + i, k + steps + i, k + steps + nxt, k + nxt))
        k = 1 + (rings - 2) * steps
        fs.append((k + i, south, k + nxt))
    return head_object(name, vs, fs, mat)


def stroke(name, coords, width, mat):
    vs = []
    fs = []
    for i, (x, y, z) in enumerate(coords):
        w = width * (0.16 + 0.84 * math.sin(math.pi * i / (len(coords) - 1)) ** 0.6)
        vs.extend((Vector((x, y - 0.001, z - w)), Vector((x, y - 0.001, z + w))))
        if i:
            fs.append((2 * i - 2, 2 * i, 2 * i + 1, 2 * i - 1))
    ob = head_object(name, vs, fs, mat)
    ob.data.materials[0].use_backface_culling = False


# The shared iris painter works independently of the old head UV layout.
paint = lit_iris(shared_iris((0.24, 0.54, 0.48)))
iris_file = output / "iris.png"
write_png(str(iris_file), np.uint8(np.clip(paint, 0, 1) * 255))
tex = iris.node_tree.nodes.new("ShaderNodeTexImage")
tex.image = bpy.data.images.load(str(iris_file))
tex.image.pack()
iris.node_tree.links.new(tex.outputs["Color"], iris.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
for side, sign in (("l", 1), ("r", -1)):
    eye = [points[i] for i in members("helper-" + side + "-eye")]
    lo = Vector([min(p[k] for p in eye) for k in range(3)])
    hi = Vector([max(p[k] for p in eye) for k in range(3)])
    c = (lo + hi) / 2
    r = (hi - lo) / 2
    oval("Sclera " + side, c, r, white)
    eye_front = c.y - r.y
    center = Vector((c.x, eye_front + 0.0017, c.z))
    radius = Vector((r.x * 0.54, 0.003, r.z * 0.65))
    disc = oval("Painted iris " + side, center, radius, iris)
    uv = disc.data.uv_layers.new(name="Iris")
    for loop in disc.data.loops:
        pos = disc.data.vertices[loop.vertex_index].co
        local = transforms["Head"].inverted() @ (pos - dest["Head"]) + source["Head"] - center
        uv.data[loop.index].uv = (
            0.5 + local.x / radius.x * IRIS_FILL * IRIS_WIDE,
            0.5 + local.z / radius.z * IRIS_FILL,
        )
    oval(
        "Glint " + side,
        Vector((c.x - 0.002, eye_front - 0.0018, c.z + 0.0035)),
        Vector((0.0018, 0.001, 0.0018)),
        light,
    )
    brow = []
    lash = []
    for j in range(19):
        t = j / 18
        x = c.x + sign * (2 * t - 1) * r.x * 1.12
        z = c.z + r.z * (0.94 + 0.25 * math.sin(math.pi * t) - 0.08 * t)
        brow.append((x, front(x, z, c.y) - 0.001, z))
        z = c.z + r.z * (0.02 + 0.43 * math.sin(math.pi * t) + 0.14 * t)
        lash.append((x, min(front(x, z, c.y), c.y - r.y * 0.68) - 0.0008, z))
    stroke("Tapered brow " + side, brow, 0.0027, ink)
    stroke("Upper lash " + side, lash, 0.0016, ink)

# The removable haircut uses the near mesh from the game's authored style.
# Fit its standard scalp to this macro head; keep the strand UV and tonal drawing.
sys.path.insert(0, str(Path("living/tools/board").resolve()))
import glb
from hair import paint_strands

hj, hbuf, _ = glb.read(clip_file.parent.parent / "styles/hair/swept.glb")
primitive = next(m for m in hj["meshes"] if m["name"] == "Hair")["primitives"][0]


def hair_data(attr):
    return glb.accessor(hj, hbuf, primitive["attributes"][attr])


hp = hair_data("POSITION")
hair_verts = [(x * 0.94, -depth + 0.040, z + 0.014) for x, z, depth in hp]
hair_faces = glb.accessor(hj, hbuf, primitive["indices"]).reshape((-1, 3)).tolist()
hair_mat = material("Chestnut sweep_HAIR", (0.29, 0.105, 0.065))
hair = surface_object("Swept crop", hair_verts, hair_faces, [hair_mat])
hair.vertex_groups.new(name=names["Head"]).add(list(range(len(hair_verts))), 1, "REPLACE")
# Preserve the authored root, tip and ring variation in vertex colour.
tones = hair_data("COLOR_0")
colours = hair.data.color_attributes.new(name="Hair tone", type="FLOAT_COLOR", domain="POINT")
for item, rgba in zip(colours.data, tones):
    item.color = tuple(rgba)
huv = hair.data.uv_layers.new(name="Strands")
source_uv = hair_data("TEXCOORD_0")
for loop in hair.data.loops:
    u, v = source_uv[loop.vertex_index]
    huv.data[loop.index].uv = (u, 1 - v)
strand_file = output / "strands.png"
pigment = paint_strands().astype(float) * np.array((0.71, 0.44, 0.34))
write_png(str(strand_file), np.uint8(pigment))
strand = hair_mat.node_tree.nodes.new("ShaderNodeTexImage")
strand.image = bpy.data.images.load(str(strand_file))
strand.image.pack()
tones_node = hair_mat.node_tree.nodes.new("ShaderNodeVertexColor")
tones_node.layer_name = colours.name
mix = hair_mat.node_tree.nodes.new("ShaderNodeMixRGB")
mix.blend_type = "MULTIPLY"
mix.inputs[0].default_value = 1
hair_mat.node_tree.links.new(strand.outputs["Color"], mix.inputs[1])
hair_mat.node_tree.links.new(tones_node.outputs["Color"], mix.inputs[2])
hair_mat.node_tree.links.new(mix.outputs[0], hair_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])

# The game scene contains only T-pose geometry and its shared rig.
for ob in (human, rig):
    bpy.data.objects.remove(ob, do_unlink=True)
# Plain GLBs face the asset viewer from +Z. Keep joint-local clip axes intact.
game.rotation_mode = "XYZ"
game.rotation_euler.z += math.pi
# The source opens in bind pose. Its two NLA tracks can be enabled for editing.
bpy.ops.wm.save_as_mainfile(filepath=str(output / "cullet-base.blend"), compress=True)
static = output / "static.glb"
bpy.ops.export_scene.gltf(filepath=str(static), export_animations=False, export_morph=False)

# Attach original shared samples directly, avoiding frame resampling by Blender.
sys.path.insert(0, str(Path("living/tools").resolve()))
from merge_primitives import read_glb, write_glb, read_accessor, append_accessor

model, buffer = read_glb(static)
source, source_buffer = read_glb(clip_file)
by_name = {n["name"]: i for i, n in enumerate(model["nodes"])}
copied = {}


def copy_samples(i):
    if i not in copied:
        values, fmt = read_accessor(source, source_buffer, i)
        index = append_accessor(model, buffer, values, *fmt)
        for key in ("min", "max"):
            if key in source["accessors"][i]:
                model["accessors"][index][key] = source["accessors"][i][key]
        copied[i] = index
    return copied[i]


model["animations"] = []
for anim in source["animations"]:
    if anim["name"] not in {"idle", "walk"}:
        continue
    channels = []
    for channel in anim["channels"]:
        target = channel["target"]
        name = source["nodes"][target["node"]]["name"]
        channels.append(dict(channel, target=dict(target, node=by_name[name])))
    samplers = [
        dict(s, input=copy_samples(s["input"]), output=copy_samples(s["output"])) for s in anim["samplers"]
    ]
    model["animations"].append(dict(anim, channels=channels, samplers=samplers))
write_glb(output / "cullet-base.glb", model, buffer)
