"""Model the outer eyelash fans directly on the master and carry each lid expression
and the contact vertex's skin weights into them. The existing eyeline slot draws them.
"""
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import person

path=Path(sys.argv[-1]).resolve()
bpy.ops.wm.open_mainfile(filepath=str(path))
face=bpy.data.objects['Face']
mesh=face.data
arm=face.parent
slots=[m.name for m in mesh.materials]
line=next(i for i,s in enumerate(slots) if 'Eyeline' in s)
corners={v for f in mesh.polygons if f.material_index==line for v in f.vertices}
keys=mesh.shape_keys.key_blocks
basis=keys[0]
coords=[v.co.copy() for v in basis.data]
# Ray of three differently sized lashes at each outside lid corner. Pick actual
# mesh vertices so profile variation and blink carry each line with the eyelid.
pos=[]; tris=[]; weights=[]; colours=[]; anchors=[]
for side in (-1,1):
    for k,x in enumerate((.054,.061,.067)):
        candidates=[i for i in corners if side*coords[i].x>0 and 1.627<coords[i].z<1.659]
        a=min(candidates,key=lambda i:abs(side*coords[i].x-x)+.40*(1.659-coords[i].z))
        pt=coords[a]+Vector((0,.0012,0)); s=side
        offsets=[(-s*.002,0,-.001),(s*.002,0,.001),(s*(.0035+.0017*k),.0008,.0062-.0005*k)]
        start=len(pos)
        for off in offsets:
            pos.append(pt+Vector(off)); anchors.append(a)
            weights.append({face.vertex_groups[g.group].name:g.weight for g in mesh.vertices[a].groups if g.weight>0})
            colours.append((.17,.096,.105))
        tris.append((start,start+2,start+1) if side==1 else (start,start+1,start+2))
lash=person.raw_object("Lash fans",pos,tris,weights,colours,slots[line],arm)
# raw_object caches freshly built materials; the master already has this exact slot.
lash.data.materials[0]=mesh.materials[line]
lash.shape_key_add(name="Basis",from_mix=False)
for key in list(keys)[1:]:
    nk=lash.shape_key_add(name=key.name,from_mix=False)
    for v,idx in zip(nk.data,anchors):
        v.co+=key.data[idx].co-basis.data[idx].co
# Preserve the modelling profile through the same skin and expression deltas.
attr=lash.data.attributes.new("atelier_profile","FLOAT_VECTOR","POINT")
for v,i in zip(attr.data,anchors):
    v.vector=mesh.attributes["atelier_profile"].data[i].vector
with bpy.context.temp_override(active_object=face,object=face,selected_objects=[face,lash],selected_editable_objects=[face,lash]):
    bpy.ops.object.join()
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(path),compress=True)
