"""Blender probe. Arguments after -- are a body GLB and an output JSON path."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np

source, output = sys.argv[sys.argv.index("--") + 1 :]
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = 30
bpy.ops.import_scene.gltf(filepath=source, disable_bone_shape=True, guess_original_bind_pose=False)
arm = next(o for o in scene.objects if o.type == "ARMATURE")
body = next(o for o in scene.objects if o.type == "MESH")
ad = arm.animation_data
for tr in ad.nla_tracks:
    tr.mute = True
ad.action = None
for bone in arm.pose.bones:
    bone.matrix_basis.identity()
bpy.context.view_layer.update()
edges = np.asarray([tuple(e.vertices) for e in body.data.edges])


def coords():
    evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = evaluated.to_mesh()
    p = np.empty(3 * len(me.vertices), dtype=np.float32)
    me.vertices.foreach_get("co", p)
    evaluated.to_mesh_clear()
    transform = np.array(evaluated.matrix_world)
    return p.reshape(-1, 3) @ transform[:3, :3].T + transform[:3, 3]


p = coords()
mid = p[edges].mean(axis=1)


def lengths(p):
    return np.linalg.norm(p[edges[:, 0]] - p[edges[:, 1]], axis=1)


rest = lengths(p)
regions = {}
for label, bone, radius in [
    ("shoulders", "UpperArm", 0.092),
    ("hips", "UpperLeg", 0.14),
    ("knees", "LowerLeg", 0.078),
    ("hands", "Hand", 0.19),
]:
    centers = [arm.matrix_world @ arm.pose.bones["J_Bip_" + s + "_" + bone].head for s in "LR"]
    regions[label] = (rest > 0.0001) & (np.linalg.norm(mid[:, None] - centers, axis=2).min(axis=1) < radius)
    assert regions[label].any(), label
hips = np.mean([arm.matrix_world @ arm.pose.bones["J_Bip_" + s + "_UpperLeg"].head for s in "LR"], axis=0)
offset = mid - hips
regions["saddle"] = (
    (rest > 0.0001)
    & (np.abs(offset[:, 0]) < 0.055)
    & (np.abs(offset[:, 1]) < 0.082)
    & (offset[:, 2] > -0.15)
    & (offset[:, 2] < -0.035)
)
assert regions["saddle"].any()
report = {}
for clip in ["walk", "run", "sit_ground", "sword_slash"]:
    track = next(t for t in ad.nla_tracks if t.name == clip)
    strip = track.strips[0]
    ad.action = strip.action
    ad.action_slot = strip.action_slot
    start, end = map(round, ad.action.frame_range)
    samples = {k: [] for k in regions}
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        posed = lengths(coords())
        for k, mask in regions.items():
            samples[k].append(posed[mask] / rest[mask])
    report[clip] = {
        k: {
            "edges": int(regions[k].sum()),
            "frames": len(v),
            "min_p05_p95_max": np.percentile(v, [0, 5, 95, 100]).round(4).tolist(),
        }
        for k, v in samples.items()
    }
Path(output).write_text(json.dumps(report, indent=2) + "\n")
