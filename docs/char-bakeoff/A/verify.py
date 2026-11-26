"""Run inside Blender with -- final.glb own-clips.glb."""

import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path("living/tools/board").resolve()))
import glb

character_path, clip_path = sys.argv[sys.argv.index("--") + 1 :]
character, data, _ = glb.read(character_path)
source, source_data, _ = glb.read(clip_path)
joint_names = {character["nodes"][i]["name"] for i in character["skins"][0]["joints"]}
assert len(joint_names) == 82


def hierarchy(doc):
    return {
        doc["nodes"][child]["name"]: node["name"] for node in doc["nodes"] for child in node.get("children", [])
    }


parents = hierarchy(source)
export_parents = hierarchy(character)
models = {node["name"]: node for node in character["nodes"]}
for src in source["nodes"]:
    name = src["name"]
    if name not in joint_names:
        continue
    assert parents[name] == export_parents[name], name
    target = models[name]
    for key, default in (("translation", (0, 0, 0)), ("scale", (1, 1, 1))):
        np.testing.assert_allclose(target.get(key, default), src.get(key, default), atol=1e-6)
    q = np.asarray(src.get("rotation", (0, 0, 0, 1)))
    r = np.asarray(target.get("rotation", (0, 0, 0, 1)))
    assert min(np.linalg.norm(q - r), np.linalg.norm(q + r)) < 1e-6, name

for animation in character["animations"]:
    original = next(a for a in source["animations"] if a["name"] == animation["name"])
    for c, s in zip(animation["channels"], original["channels"], strict=True):
        assert character["nodes"][c["target"]["node"]]["name"] == source["nodes"][s["target"]["node"]]["name"]
        assert c["target"]["path"] == s["target"]["path"]
    for c, s in zip(animation["samplers"], original["samplers"], strict=True):
        for k in ("input", "output"):
            np.testing.assert_array_equal(
                glb.accessor(character, data, c[k]), glb.accessor(source, source_data, s[k])
            )
    print(animation["name"], len(original["channels"]), "channels match the shared library")

bpy.ops.import_scene.gltf(filepath=character_path)
rig = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
body = next(o for o in bpy.context.scene.objects if o.name.startswith("Cullet base"))
animation = rig.animation_data
animation.action = None
for track in animation.nla_tracks:
    track.mute = True
edges = np.array([tuple(edge.vertices) for edge in body.data.edges])


def lengths(coords):
    return np.linalg.norm(coords[edges[:, 0]] - coords[edges[:, 1]], axis=1)


rest = lengths(np.array([tuple(vertex.co) for vertex in body.data.vertices]))
valid = rest > 0.0001
for track in animation.nla_tracks:
    animation.action = track.strips[0].action
    animation.action_slot = track.strips[0].action_slot
    ratios = []
    for frame in (1, 6, 12, 18, 24):
        bpy.context.scene.frame_set(frame)
        evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
        lengths_now = lengths(np.array([tuple(vertex.co) for vertex in evaluated.data.vertices]))
        ratios.extend(lengths_now[valid] / rest[valid])
    print(
        track.name,
        "posed/rest edge ratio [min,p01,median,p99,max]",
        np.round(np.percentile(ratios, [0, 1, 50, 99, 100]), 3),
    )
