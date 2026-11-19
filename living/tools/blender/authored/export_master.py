"""Open a rigged Blender master and bake the chosen age profile into the client type.
Run with the Blender shim, -b --python-exit-code 1 -P export_master.py -- MASTER OUT [MATURITY].
"""
import json
from pathlib import Path
import sys

import bpy
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import person
sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[2])]
from merge_primitives import read_glb, write_glb
from rig_data import rebind

master, out, *profile = sys.argv[sys.argv.index("--")+1:]
bpy.ops.wm.open_mainfile(filepath=str(Path(master).resolve()))
face = bpy.data.objects.get("Face")
if face and profile:
    # Reconstruct an editable shape key from the master, then bake the chosen
    # fraction through all the expression targets before writing the type.
    age = float(profile[0])
    if not 0 <= age <= 1:
        raise ValueError("maturity is in [0,1]")
    diff = age - face["atelier_maturity"]
    changes = [a.vector.copy() for a in face.data.attributes["atelier_profile"].data]
    age_key = face.shape_key_add(name="Atelier maturity", from_mix=False)
    for vertex, delta in zip(age_key.data, changes):
        vertex.co += delta * diff
    deltas = [p.co-b.co for p,b in zip(age_key.data,face.data.shape_keys.key_blocks[0].data)]
    face.shape_key_remove(age_key)
    for key in face.data.shape_keys.key_blocks:
        for vertex, delta in zip(key.data, deltas):
            vertex.co += delta
for ob in list(bpy.data.objects):
    if ob.get("atelier_fitting_surface"):
        bpy.data.objects.remove(ob, do_unlink=True)
person.export_glb(str(Path(out).resolve()))
person.add_vrm(out,"Atelier master")
j,b=read_glb(out)
secondary=json.loads(Path(__file__).with_name("springs.json").read_text())[Path(master).stem]
j["extensions"]["VRM"]["secondaryAnimation"]=rebind(secondary,{n.get("name"):i for i,n in enumerate(j["nodes"])})
write_glb(out,j,b)
