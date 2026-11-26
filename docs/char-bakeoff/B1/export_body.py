"""Export body edits from the current fitting master beside the calibrated head and hair."""
import os
import shutil
import sys
from array import array
from pathlib import Path

import bpy
from mathutils import Matrix

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2] / 'docs/char-live-3/ink-batch-2'
OUT = Path(os.environ['B1_OUT']).resolve()
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(HERE.parents[2] / 'living/tools'))
import merge_primitives as glb

body=bpy.data.objects['Base | jersey, shorts and socks']
rig=body.find_armature()
mesh=body.data
bpy.ops.object.select_all(action='DESELECT')
body.select_set(True)
rig.select_set(True)
bpy.context.view_layer.objects.active=body
bpy.ops.object.modifier_apply(modifier='Rounded fitting surface')
mesh.transform(rig.matrix_world.inverted() @ body.matrix_world)
body.matrix_parent_inverse=Matrix.Identity(4)
body.matrix_basis=Matrix.Identity(4)
# Graft only the new body primitives onto the calibrated game file. Keep the UVs,
# painted eye geometry, custom normals and clips of the authored head and hands.
intermediate=OUT/'fitting-body.glb'
bpy.ops.export_scene.gltf(filepath=str(intermediate),use_selection=True,
                          export_animations=False,export_leaf_bone=False)
j,b=glb.read_glb(SOURCE/'own-cora-live.glb')
src,raw=glb.read_glb(intermediate)
original=j['meshes'][0]['primitives']
def slot(p):return j['materials'][p['material']]['extras']['slop']['slot']
j['meshes'][0]={'name':'Swept fringe and plait','primitives':[p for p in original if slot(p)=='hair']}
old_node=next(i for i,n in enumerate(j['nodes']) if n.get('mesh')==0)
j['nodes'][old_node]['name']='Swept fringe and plait'
parent=next(n for n in j['nodes'] if old_node in n.get('children',[]))
for name,prims in [('Fitted neck',[p for p in original if slot(p)=='skin']),
                   ('Fitting body',[])]:
    parent['children'].append(len(j['nodes']))
    j['nodes'].append({'name':name,'mesh':len(j['meshes']),'skin':j['nodes'][old_node]['skin']})
    j['meshes'].append({'name':name,'primitives':prims})
# The previous skin primitive joined the old hands and neck. Only the neck
# belongs to this base. Its vertices are separated from the hands by the torso.
neck=j['meshes'][-2]['primitives'][0]
positions,_=glb.read_accessor(j,b,neck['attributes']['POSITION'])
indices,fmt=glb.read_accessor(j,b,neck['indices'])
kept=array(indices.typecode,(i for i in indices if positions[3*i+1]>1.20))
assert len(kept)%3==0
neck['indices']=glb.append_accessor(j,b,kept,*fmt)
node=next(n for n in src['nodes'] if 'mesh' in n)
skin_names=lambda doc,skin:[doc['nodes'][i]['name'] for i in doc['skins'][skin]['joints']]
dest_skin=next(n['skin'] for n in j['nodes'] if n.get('mesh')==0)
names=skin_names(j,dest_skin)
mapping=[names.index(n) for n in skin_names(src,node['skin'])]
def copy_acc(i,joints=False):
    values,fmt=glb.read_accessor(src,raw,i)
    if joints:
        values=array(values.typecode,(mapping[v] for v in values))
    return glb.append_accessor(j,b,values,*fmt)
first_material=len(j['materials'])
for mat in src['materials']:
    mat['extras']={'slop':{'slot':'skin' if mat['name'] in ('Exposed skin','Nail bed') else 'cloth'}}
    j['materials'].append(mat)
for prim in src['meshes'][node['mesh']]['primitives']:
    attrs={k:copy_acc(v,k=='JOINTS_0') for k,v in prim['attributes'].items()}
    j['meshes'][-1]['primitives'].append(dict(attributes=attrs,indices=copy_acc(prim['indices']),
                                             material=prim['material']+first_material))
# Reuse only referenced palette records. The imported outer coat is gone.
primitives=[p for m in j['meshes'] for p in m['primitives']]
active=sorted({p['material'] for p in primitives})
j['materials']=[j['materials'][i] for i in active]
for p in primitives:
    p['material']=active.index(p['material'])
glb.write_glb(OUT/'own-b1-base.glb',j,b)

for ext in ('eyes.ink.png','hair.png','face.png'):
    shutil.copyfile(SOURCE/('own-cora-live.'+ext),OUT/('own-b1-base.'+ext))
