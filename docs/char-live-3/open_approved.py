"""Open the approved scene and reuse its rig, material audit and clip exporter."""
import ast
import hashlib
import math
import shutil
import subprocess
import sys
from array import array

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

repo = SESSION.parents[1]
baseline = SESSION.parent/'char-live-1/restart/replay.py'
bpy.ops.wm.open_mainfile(filepath=str(APPROVED/'cora-final.blend'))
scene = bpy.context.scene
rig = next(o for o in scene.objects if o.type == 'ARMATURE' and not o.hide_render)
rig_items = [o for o in scene.objects if o.type == 'MESH' and not o.hide_render]
face = next(o for o in rig_items if o.data.shape_keys)
hair_ob = next(o for o in rig_items if 'swept hair' in o.name)
hair_material = hair_ob.data.materials[0]
bpy.context.preferences.filepaths.save_version = 0
sys.path[:0] = [str(repo/'living/tools'), str(repo/'living/tools/blender')]
import person as generator
import merge_primitives as glb_io

source_tree = ast.parse(baseline.read_text())
def baseline_function(name):
    return next(n for n in reversed(list(ast.walk(source_tree)))
                if isinstance(n, ast.FunctionDef) and n.name == name)

for name in ('audit', 'clear_render_buffer'):
    exec(compile(ast.Module([baseline_function(name)], []), str(baseline), 'exec'), globals())
approved_proof = json.loads((APPROVED/'replay-check.json').read_text())
allowed_generator_images = set(approved_proof['images_match_generator'].values())
assert hashlib.sha256((APPROVED/'own-cora-live.glb').read_bytes()).hexdigest() == approved_proof['artifacts']['own-cora-live.glb']['delivery']
clear_render_buffer()
audit('open-approved')
for ext in ('face.png', 'hair.png', 'calibration.json'):
    shutil.copyfile(APPROVED/('own-cora-live.'+ext), ROOT/('own-cora-live.'+ext))

cj, cb = glb_io.read_glb(repo/'living/game/assets/lookdev/anim/own-clips.glb')
motions = {a['name']:a for a in cj['animations'] if a['name'] in
           ('idle','walk','run','talk','sit_idle','sit_ground')}
# Reuse the approved export settings and the removal of the redundant
# point mask from the export copy. The editable mesh keeps its point mask.
previous_entries = {e['stage']:e for e in map(json.loads, (PREVIOUS/'session.jsonl').read_text().splitlines())}
setup = previous_entries['stage4-xhigh-uv']['code']
export_setup = setup[setup.index('node=next(n for n in ast.parse'):setup.index('export_with_face_map=')]
exec(compile(export_setup, 'char-live-2 UV export setup', 'exec'), globals())

def export_current():
    for part in rig_items:
        colors = part.data.color_attributes
        if colors.get('Color'):
            colors.active_color = colors['Color']
            colors.render_color_index = colors.active_color_index
    export_cora()
    dst = ROOT/'own-cora-live.glb'
    subprocess.run(['python3', str(repo/'living/tools/face_normals.py'), str(dst), str(dst),
                    '--flat','0','--hair','0','--png',str(ROOT/'own-cora-live.face.png')], check=True)
    subprocess.run(['python3',str(PREVIOUS/'face-shading/paint_features.py'),'shadow',
                    str(ROOT/'own-cora-live.face.png')],check=True)
    doc,buf = glb_io.read_glb(dst)
    for mesh in doc['meshes']:
        mesh['name'] = 'Cora face' if mesh.get('extras',{}).get('targetNames') else 'Cora body and hair'
        for prim in mesh['primitives']:
            if doc['materials'][prim['material']]['extras']['slop']['slot']=='hair':
                prim['attributes'].pop('TEXCOORD_1', None)
    glb_io.write_glb(dst,doc,buf)
    clear_render_buffer()
    audit('item1-export')
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'cora-final.blend'))

# Register each original UV island to the vertices of its editable lock.
layout=json.loads((PREVIOUS/'hair/final/lock-layout.json').read_text())
mesh=hair_ob.data
groups=[set() for spec in layout['islands']]
poly_tiles=[]
for p in mesh.polygons:
    uv=mesh.uv_layers.active.data[p.loop_indices[0]].uv
    tile=int(uv.x*layout['size']//340)+6*int((1-uv.y)*layout['size']//340)
    groups[tile].update(p.vertices)
    poly_tiles.append(tile)
groups=[sorted(ids) for ids in groups]
assert sum(map(len, groups))==len(mesh.vertices)
for spec,ids in zip(layout['islands'],groups):
    if spec['kind']=='braid':
        coords=np.array([tuple(mesh.vertices[i].co) for i in ids]).reshape(57,10,3).mean(1)
        print('BRAID',spec['seed'],coords[::7].round(3).tolist(),flush=True)
