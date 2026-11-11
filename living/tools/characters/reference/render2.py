"""blender -b -P render2.py -- IN.glb OUTDIR : face weights (eye-set bones) and blend-shape heat maps, front view."""
import bpy, sys, os, math, numpy as np
from mathutils import Vector, Matrix
argv = sys.argv[sys.argv.index('--')+1:]; src, out = argv[0], argv[1]; os.makedirs(out, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
scene = bpy.context.scene
face = [o for o in scene.objects if o.type=='MESH' and o.data.shape_keys and len(o.data.shape_keys.key_blocks) > 5][0]
for o in scene.objects: o.hide_render = (o is not face)
face.modifiers.clear()  # rest pose, no armature
FLIP = Matrix.Rotation(math.pi, 4, 'Z')
face.matrix_world = FLIP @ face.matrix_world
me = face.data; kb = me.shape_keys.key_blocks
print('shape keys', len(kb))
co = np.array([tuple(face.matrix_world @ v.co) for v in me.vertices]); lo, hi = co.min(0), co.max(0); ctr = (lo+hi)/2; H = hi[2]-lo[2]
# hide non-skin materials? keep skin + eye region only: delete faces of hair? face mesh only holds face prims.
def set_vcol(vals_rgb):
    if 'c' in me.color_attributes: me.color_attributes.remove(me.color_attributes['c'])
    a = me.color_attributes.new('c', 'FLOAT_COLOR', 'POINT')
    a.data.foreach_set('color', np.concatenate([vals_rgb, np.ones((len(vals_rgb),1))],1).astype(np.float32).ravel())
    me.color_attributes.active_color = a; me.attributes.active_color = a
def heat(t):
    t = np.clip(t, 0, 1)[:,None]
    a = np.array([[0.92,0.92,0.92]]); b = np.array([[0.98,0.80,0.25]]); c = np.array([[0.85,0.15,0.10]])
    return np.where(t < 0.5, a + (b-a)*(t*2), b + (c-b)*((t-0.5)*2))
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); scene.collection.objects.link(cam); scene.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = H*1.05
cam.location = Vector((ctr[0], ctr[1]-0.6, ctr[2]-0.03*H)); cam.rotation_euler = (math.pi/2, 0, 0)
scene.render.engine = 'BLENDER_WORKBENCH'; scene.render.resolution_x = 520; scene.render.resolution_y = 520
sh = scene.display.shading; sh.light = 'STUDIO'; sh.color_type = 'VERTEX'; sh.show_backface_culling = False
sh.background_type = 'VIEWPORT'; sh.background_color = (1,1,1); scene.view_settings.view_transform = 'Standard'
def shoot(tag):
    scene.render.filepath = os.path.join(out, tag + '.png'); bpy.ops.render.render(write_still=True)
# weights
for gname in ('J_Adj_L_FaceEyeSet', 'J_Adj_L_FaceEye', 'J_Bip_C_Head'):
    vg = face.vertex_groups.get(gname)
    if not vg: continue
    w = np.zeros(len(me.vertices))
    for v in me.vertices:
        for ge in v.groups:
            if ge.group == vg.index: w[v.index] = ge.weight
    set_vcol(heat(w)); shoot('weight-' + gname)
base = np.array([tuple(v.co) for v in kb[0].data])
for k in kb[1:]:
    d = np.array([tuple(v.co) for v in k.data]) - base
    m = np.linalg.norm(d, axis=1)
    if m.max() < 1e-5: continue
    # show the shape applied, coloured by displacement (scale: 10 mm = full red)
    k.value = 1.0
    set_vcol(heat(m/0.010)); shoot('bs-' + k.name.split('Fcl_')[-1].replace('.', '_'))
    k.value = 0.0
