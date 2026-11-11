"""blender -b -P render.py -- IN.glb OUTDIR KIND(vroid|ours)
Renders the face skin as form, geometry-only form, quad wireframe, normals, toon steps and plane clusters."""
import bpy, bmesh, sys, os, math
import numpy as np
from mathutils import Vector, Matrix
argv = sys.argv[sys.argv.index('--')+1:]
src, out, kind = argv[0], argv[1], argv[2]
os.makedirs(out, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
scene = bpy.context.scene
# Face the model to -Y (Blender front).
arm = [o for o in scene.objects if o.type == 'ARMATURE']
roots = [o for o in scene.objects if o.parent is None]
FLIP = Matrix.Rotation(math.pi, 4, 'Z')  # both files face glTF -Z (VRM 0.x)
bpy.context.view_layer.update()
def mats(o): return [s.material.name if s.material else '' for s in o.material_slots]
def extract(pred, name):
    """A new evaluated mesh object holding only faces whose material matches pred, in world space (rest pose)."""
    bm = bmesh.new()
    for o in scene.objects:
        if o.type != 'MESH': continue
        ms = mats(o)
        if not any(pred(m) for m in ms): continue
        me = o.data.copy()
        # drop shape keys influence: rest
        tmp = bpy.data.objects.new('tmp', me); scene.collection.objects.link(tmp)
        tmp.matrix_world = o.matrix_world
        b2 = bmesh.new(); b2.from_mesh(me)
        kill = [f for f in b2.faces if not pred(ms[f.material_index] if f.material_index < len(ms) else '')]
        bmesh.ops.delete(b2, geom=kill, context='FACES')
        b2.transform(FLIP @ o.matrix_world)
        # carry custom normals: compute per-loop normals from the source mesh
        me2 = bpy.data.meshes.new(name+'_part'); b2.to_mesh(me2)
        bpy.data.objects.remove(tmp)
        yield me2, o, ms
def part_object(pred, name):
    parts = list(extract(pred, name))
    objs = []
    for me, o, ms in parts:
        ob = bpy.data.objects.new(name, me); scene.collection.objects.link(ob); objs.append(ob)
    if not objs: return None
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objs: ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1: bpy.ops.object.join()
    return bpy.context.view_layer.objects.active
# Hide all originals.
for o in list(scene.objects):
    o.hide_render = True
is_skin = (lambda m: m.endswith('Face_00_SKIN'))
skin = part_object(is_skin, 'skin')
skin.hide_render = False
print('skin', len(skin.data.polygons), 'faces', len(skin.data.vertices), 'verts')
# file normals (custom, carried by to_mesh? bmesh drops custom normals) -> recompute from the source object separately
# Approach: transfer normals from original via Data Transfer would blur; instead read loop normals of the original faces.
src_objs = [o for o in scene.objects if o.type=='MESH' and any(is_skin(m) for m in mats(o)) and o is not skin]
file_normals = []
for o in src_objs:
    ms = mats(o); me = o.data
    R = (FLIP @ o.matrix_world).to_3x3()
    cn = me.corner_normals
    for p in me.polygons:
        if is_skin(ms[p.material_index]):
            file_normals.extend([(R @ Vector(cn[li].vector)).normalized() for li in p.loop_indices])
print('file normals', len(file_normals), 'loops', len(skin.data.loops))
fileN = np.array([tuple(v) for v in file_normals]) if len(file_normals)==len(skin.data.loops) else None
# geometry normals: weld, smooth
me = skin.data
bm = bmesh.new(); bm.from_mesh(me)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
bm.to_mesh(me); bm.free()
for p in me.polygons: p.use_smooth = True
me.update()
geoN = np.array([tuple(c.vector) for c in me.corner_normals])
if fileN is not None and len(fileN) != len(geoN): fileN = None
if fileN is not None:
    ang = np.degrees(np.arccos(np.clip((fileN*geoN).sum(1), -1, 1)))
    print('file vs geometry normal angle deg: mean %.1f median %.1f p90 %.1f max %.1f' % (ang.mean(), np.median(ang), np.percentile(ang,90), ang.max()))
    np.save(os.path.join(out, 'normal_angle.npy'), ang)
# bounds
co = np.array([tuple(skin.matrix_world @ v.co) for v in me.vertices])
lo, hi = co.min(0), co.max(0); ctr = (lo+hi)/2; H = hi[2]-lo[2]
print('bounds', lo.round(4), hi.round(4))
def set_colors(rgb, name='c'):
    if name in me.color_attributes: me.color_attributes.remove(me.color_attributes[name])
    a = me.color_attributes.new(name, 'FLOAT_COLOR', 'CORNER')
    flat = np.concatenate([np.clip(rgb,0,1), np.ones((len(rgb),1))], 1).astype(np.float32).ravel()
    a.data.foreach_set('color', flat); me.color_attributes.active_color = a
    me.attributes.active_color = a
# camera
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); scene.collection.objects.link(cam); scene.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = max(H, hi[0]-lo[0]) * 1.12
scene.render.engine = 'BLENDER_WORKBENCH'; scene.render.resolution_x = 700; scene.render.resolution_y = 700
sh = scene.display.shading; sh.light = 'FLAT'; sh.color_type = 'VERTEX'; sh.show_backface_culling = False
scene.display.render_aa = '8'
scene.view_settings.view_transform = 'Standard'
world = bpy.data.worlds.new('w'); scene.world = world
sh.background_type = 'VIEWPORT'; sh.background_color = (1,1,1)
VIEWS = {'front':0, 'three-quarter':35, 'side':90}
def place(az):
    a = math.radians(az); d = 0.6
    target = Vector((ctr[0], ctr[1], ctr[2]))
    cam.location = target + Vector((math.sin(a)*d, -math.cos(a)*d, 0))
    cam.rotation_euler = (math.pi/2, 0, a)
def shoot(tag, views=VIEWS):
    for vn, az in views.items():
        place(az); scene.render.filepath = os.path.join(out, f'{tag}-{vn}.png'); bpy.ops.render.render(write_still=True)
# light direction for toon: from the character's right? use camera-left-up-front: world
def toon(N, L, edge=0.0):
    d = N @ L
    return np.where(d[:,None] > edge, np.array([[0.97,0.93,0.90]]), np.array([[0.62,0.52,0.55]]))
def lit(N, L):
    d = np.clip(N @ L, 0, 1)
    v = 0.25 + 0.75*d; return np.stack([v,v,v],1)
Ls = {'key': Vector((-0.55, -0.6, 0.58)).normalized(), 'side': Vector((-0.95, -0.15, 0.27)).normalized(), 'top': Vector((0.0, -0.35, 0.94)).normalized()}
# 1. form with geometry normals, lambert from key light
for which, NN in (('geo', geoN), ('file', fileN)):
    if NN is None: continue
    set_colors(lit(NN, np.array(Ls['key']))); shoot(f'lambert-{which}')
    for ln in ('key', 'side'):
        set_colors(toon(NN, np.array(Ls[ln]))); shoot(f'toon-{ln}-{which}', {'front':0, 'three-quarter':35})
    set_colors(NN*0.5+0.5); shoot(f'normals-{which}', {'front':0, 'side':90})
# plane clusters on face normals (area weighted k-means), geometry normals
fn = np.array([tuple(p.normal) for p in me.polygons]); fa = np.array([p.area for p in me.polygons])
rng = np.random.default_rng(1)
K = 10
C = fn[rng.choice(len(fn), K, replace=False, p=fa/fa.sum())]
for _ in range(40):
    lab = np.argmax(fn @ C.T, 1)
    for k in range(K):
        m_ = lab == k
        if m_.any():
            v = (fn[m_]*fa[m_,None]).sum(0); C[k] = v/np.linalg.norm(v)
pal = np.array([[0.90,0.36,0.33],[0.95,0.70,0.30],[0.95,0.92,0.45],[0.55,0.82,0.45],[0.35,0.75,0.75],[0.40,0.55,0.90],[0.62,0.45,0.85],[0.90,0.55,0.80],[0.65,0.60,0.55],[0.30,0.30,0.35]])
loopcol = np.zeros((len(me.loops),3))
for p in me.polygons:
    for li in p.loop_indices: loopcol[li] = pal[lab[p.index]]*(0.75+0.25*max(0,p.normal.dot(Ls['key'])))
set_colors(loopcol); shoot('planes', {'front':0, 'three-quarter':35, 'side':90})
# 2. quad wireframe
bpy.context.view_layer.objects.active = skin; skin.select_set(True)
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.tris_convert_to_quads(face_threshold=math.radians(60), shape_threshold=math.radians(60))
bpy.ops.object.mode_set(mode='OBJECT')
nq = sum(1 for p in me.polygons if len(p.vertices)==4); nt = sum(1 for p in me.polygons if len(p.vertices)==3); nn = len(me.polygons)-nq-nt
bm = bmesh.new(); bm.from_mesh(me)
inner = [v for v in bm.verts if not v.is_boundary]
from collections import Counter
val = Counter(len(v.link_edges) for v in inner)
print('quads', nq, 'tris', nt, 'ngons', nn, 'interior valence', sorted(val.items()))
poles = np.array([tuple(skin.matrix_world @ v.co) for v in inner if len(v.link_edges) != 4])
pole_val = [len(v.link_edges) for v in inner if len(v.link_edges) != 4]
np.save(os.path.join(out, 'poles.npy'), np.concatenate([poles, np.array(pole_val)[:,None]], 1) if len(poles) else np.zeros((0,4)))
bm.free()
set_colors(np.tile([[0.93,0.90,0.88]], (len(me.loops),1)))
sh.light = 'STUDIO'
wire = skin.copy(); wire.data = me.copy(); scene.collection.objects.link(wire)
mod = wire.modifiers.new('w', 'WIREFRAME'); mod.thickness = 0.00045 if kind=='vroid' else 0.00035; mod.use_replace = True; mod.use_even_offset = False
wme = wire.data
ca = wme.color_attributes.active_color
ca.data.foreach_set('color', np.tile([0.08,0.08,0.10,1.0], len(ca.data)).astype(np.float32))
shoot('wire', {'front':0, 'three-quarter':35, 'side':90})
import json
json.dump({'quads':nq,'tris':nt,'ngons':nn,'valence':sorted(val.items()),'H':float(H),'bounds':[lo.tolist(),hi.tolist()]}, open(os.path.join(out,'topo.json'),'w'))
