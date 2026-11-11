"""blender -b -P render3.py -- IN.glb VALUES.npy GLTF_POS.npz OUT.png MAXMM : face coloured by a per-glTF-vertex scalar (mm), front + three-quarter"""
import bpy, sys, os, math, numpy as np
from mathutils import Vector, Matrix
argv = sys.argv[sys.argv.index('--')+1:]; src, vals, posf, out, mx = argv[0], argv[1], argv[2], argv[3], float(argv[4])
bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=src); scene = bpy.context.scene
face = [o for o in scene.objects if o.type=='MESH' and o.data.shape_keys and len(o.data.shape_keys.key_blocks) > 5][0]
for o in scene.objects: o.hide_render = (o is not face)
face.modifiers.clear(); face.matrix_world = Matrix.Rotation(math.pi, 4, 'Z') @ face.matrix_world
me = face.data
d = np.load(vals); v = np.linalg.norm(d, axis=1) if d.ndim == 2 else d
G = np.load(posf)['P'].astype(float); Gb = np.stack([-G[:,0], G[:,2], G[:,1]], 1)
co = np.array([tuple(face.matrix_world @ x.co) for x in me.vertices])
idx = np.array([np.argmin(((Gb - c)**2).sum(1)) for c in co])
t = np.clip(v[idx]*1000/mx, 0, 1)[:,None]
a = np.array([[0.92,0.92,0.92]]); b = np.array([[0.98,0.80,0.25]]); c = np.array([[0.85,0.15,0.10]])
rgb = np.where(t < 0.5, a + (b-a)*(t*2), b + (c-b)*((t-0.5)*2))
ca = me.color_attributes.new('c', 'FLOAT_COLOR', 'POINT'); ca.data.foreach_set('color', np.concatenate([rgb, np.ones((len(rgb),1))],1).astype(np.float32).ravel())
me.color_attributes.active_color = ca; me.attributes.active_color = ca
lo, hi = co.min(0), co.max(0); ctr = (lo+hi)/2; H = hi[2]-lo[2]
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); scene.collection.objects.link(cam); scene.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = H*1.05
scene.render.engine = 'BLENDER_WORKBENCH'; scene.render.resolution_x = 520; scene.render.resolution_y = 520
sh = scene.display.shading; sh.light = 'STUDIO'; sh.color_type = 'VERTEX'; sh.show_backface_culling = False
sh.background_type = 'VIEWPORT'; sh.background_color = (1,1,1); scene.view_settings.view_transform = 'Standard'
for tag, az in (('front', 0), ('three-quarter', 35)):
    r = math.radians(az); cam.location = Vector((ctr[0] + math.sin(r)*0.6, ctr[1] - math.cos(r)*0.6, ctr[2])); cam.rotation_euler = (math.pi/2, 0, r)
    scene.render.filepath = out.replace('.png', f'-{tag}.png'); bpy.ops.render.render(write_still=True)
