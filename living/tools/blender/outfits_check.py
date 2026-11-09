"""Check renders for outfit pieces: the animated base wearing them, in Workbench.

    blender -b -P living/tools/blender/outfits_check.py -- --anim living/game/assets/lookdev/anim/vroid-Vivi.glb \
        --pieces a.glb,b.glb --out DIR/name [--shots rest/front,idle@0.5/side,walk@0.3/front]

Each piece's mesh is rebound to the animated base's armature by bone name (as the client will
bind it to the character's bones), so a render shows the exported weights under the real clips.
Writes DIR/name-NN-<pose>-<view>.png. Colours: the base's materials in flat tones, each piece's
vertex colours quantised to a few flat materials (Workbench shows material colours).
"""

import argparse
import sys

import bpy
from mathutils import Vector

VIEWS = {"front": (0, 1, 0), "side": (1, 0, 0), "back": (0, -1, 0), "three": (0.7, 0.7, 0)}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--anim", required=True)
    ap.add_argument("--pieces", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--shots", default="rest/front,rest/side,rest/back,idle@0.6/front,idle@0.6/three,walk@0.2/front,walk@0.2/side,walk@0.7/side,walk@0.7/back")
    ap.add_argument("--size", default="420x640")
    a = ap.parse_args(argv)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.anim, bone_heuristic="BLENDER", guess_original_bind_pose=False, disable_bone_shape=True)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for o in bpy.data.objects:
        if o.type == "MESH":
            o["base"] = 1
    for m in bpy.data.materials:
        n = m.name
        m.diffuse_color = ((0.93, 0.78, 0.68, 1) if "SKIN" in n else (0.45, 0.32, 0.28, 1) if "HAIR" in n else
                           (0.15, 0.12, 0.12, 1) if "EYE" in n or "FACE" in n and "Face_00" not in n else (0.74, 0.74, 0.78, 1))
    for path in [p for p in a.pieces.split(",") if p]:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=path, bone_heuristic="BLENDER", guess_original_bind_pose=False, disable_bone_shape=True)
        new = set(bpy.data.objects) - before
        for o in new:
            if o.type == "MESH":
                o.parent = arm
                o.matrix_parent_inverse.identity()
                for md in o.modifiers:
                    if md.type == "ARMATURE":
                        md.object = arm
                quantise(o)
        for o in new:
            if o.type != "MESH":
                bpy.data.objects.remove(o)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light, sh.color_type = "STUDIO", "MATERIAL"
    sh.show_shadows, sh.show_cavity, sh.show_object_outline = True, True, True
    w, h = (int(x) for x in a.size.split("x"))
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.film_transparent = False
    scene.world = bpy.data.worlds.new("w")
    scene.world.color = (0.32, 0.33, 0.36)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.data.type = "ORTHO"
    top = max((o.matrix_world @ Vector(c)).z for o in bpy.data.objects if o.type == "MESH" for c in o.bound_box)
    cam.data.ortho_scale = top * 1.12
    for i, shot in enumerate(a.shots.split(",")):
        pose, view = shot.split("/")
        set_pose(arm, pose)
        d = Vector(VIEWS[view]).normalized()
        cam.location = Vector((0, 0, top * 0.5)) + d * 5.0
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        report_fit(pose)
        scene.render.filepath = f"{a.out}-{i:02d}-{pose.replace('@', '_')}-{view}.png"
        bpy.ops.render.render(write_still=True)
        print("SHOT", scene.render.filepath)


FITTED = set()


def report_fit(pose):
    """Skinning check: how far each piece's posed vertices stand from the posed body (a vertex
    left behind or pulled to the wrong bone stands far off)."""
    if pose in FITTED:
        return
    FITTED.add(pose)
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    body = [o for o in bpy.data.objects if o.type == "MESH" and o.get("base")]
    vs, tris = [], []
    for o in body:
        e = o.evaluated_get(dg)
        m = e.to_mesh()
        off = len(vs)
        vs += [o.matrix_world @ v.co for v in m.vertices]
        m.calc_loop_triangles()
        tris += [tuple(off + i for i in t.vertices) for t in m.loop_triangles]
        e.to_mesh_clear()
    tree = BVHTree.FromPolygons(vs, tris)
    for o in bpy.data.objects:
        if o.type != "MESH" or o.get("base"):
            continue
        e = o.evaluated_get(dg)
        m = e.to_mesh()
        d = sorted(tree.find_nearest(o.matrix_world @ v.co)[3] for v in m.vertices)
        far = [v.index for v in m.vertices if tree.find_nearest(o.matrix_world @ v.co)[3] > 0.25]
        print(f"FIT {o.name} {pose} p95={d[int(len(d) * 0.95)]:.3f} max={d[-1]:.3f} far>{0.25}={len(far)}")
        e.to_mesh_clear()


def quantise(o):
    """Flat materials from the piece's vertex colours (a few, by rounded colour); glow kept."""
    me = o.data
    col = me.color_attributes.get("Color") or (me.color_attributes[0] if me.color_attributes else None)
    mats = {}
    slots = list(me.materials)
    me.materials.clear()
    for p in me.polygons:
        src = slots[p.material_index] if p.material_index < len(slots) else None
        if src is not None and src.name.startswith("Glow"):
            key = src.name
            c = {"GlowCyan": (0.2, 0.95, 1.0), "GlowPink": (1.0, 0.3, 0.75), "GlowAmber": (1.0, 0.7, 0.2)}.get(src.name.split(".")[0], (1, 1, 1))
        elif col is not None:
            vals = [col.data[li].color for li in p.loop_indices] if col.domain == "CORNER" else [col.data[me.loops[li].vertex_index].color for li in p.loop_indices]
            # Average and round in sRGB (rounding linear values crushes dark colours).
            c = tuple((sum(v[k] for v in vals) / len(vals)) ** (1 / 2.2) for k in range(3))
            c = tuple((round(x * 16) / 16) ** 2.2 for x in c)
            key = c
        else:
            key, c = "plain", (0.6, 0.6, 0.6)
        if key not in mats:
            m = bpy.data.materials.new(f"q{len(mats)}")
            m.diffuse_color = (*[min(1.0, x) for x in c], 1)
            mats[key] = len(mats)
            me.materials.append(m)
        p.material_index = mats[key]


def set_pose(arm, pose):
    if pose == "rest":
        arm.data.pose_position = "REST"
        return
    arm.data.pose_position = "POSE"
    clip, _, at = pose.partition("@")
    acts = [x for x in bpy.data.actions if x.name == clip or x.name.startswith(clip + "_") or x.name.startswith(clip + "|")]
    if not acts:
        raise SystemExit(f"no action {clip}; have {[x.name for x in bpy.data.actions][:30]}")
    act = sorted(acts, key=lambda x: len(x.name))[0]
    ad = arm.animation_data or arm.animation_data_create()
    for t in ad.nla_tracks:
        t.mute = True
    ad.action = act
    if hasattr(ad, "action_slot") and getattr(act, "slots", None):
        ad.action_slot = act.slots[0]
    f0, f1 = act.frame_range
    bpy.context.scene.frame_set(int(round(f0 + (f1 - f0) * float(at or 0))))


main()
