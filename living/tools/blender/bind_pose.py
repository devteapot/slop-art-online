"""Read Blender pose-basis transforms for a GLB's unanimated skin."""

import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from merge_primitives import read_glb, write_glb


def read_bind_basis(source, **import_options):
    """Run before importing the animated scene. Blender can store bind scale in the pose basis."""
    doc, data = read_glb(source)
    doc.pop("animations", None)
    with tempfile.TemporaryDirectory() as directory:
        static = Path(directory) / "bind.glb"
        write_glb(static, doc, data)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(static), **import_options)
        rig = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
        return {bone.name: bone.matrix_basis.copy() for bone in rig.pose.bones}
