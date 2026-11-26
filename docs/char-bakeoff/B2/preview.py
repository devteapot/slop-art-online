# Track B2: quick Blender stills of a saved master (form check; the judged photographs come from the game).
# blender -b FILE.blend --python preview.py -- OUT_PREFIX [views] [clip:frame] [wire]
import bpy, sys, math
from mathutils import Vector
a = sys.argv[sys.argv.index('--') + 1:]
out = a[0]; views = (a[1] if len(a) > 1 else 'front,side,back,tq,face').split(',')
clip = a[2] if len(a) > 2 and ':' in a[2] and not a[2].startswith('key:') else None
wire = 'wire' in a
sc = bpy.context.scene
for k in [x[4:] for x in a if x.startswith('key:')]:        # key:Fcl_EYE_Close=1 sets an expression on the face layer
    n, v = k.split('='); bpy.data.objects['FaceLayer'].data.shape_keys.key_blocks[n].value = float(v)
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
if clip:
    n, f = clip.split(':'); act = bpy.data.actions[n]
    arm.animation_data_create(); arm.animation_data.action = act
    try: arm.animation_data.action_slot = act.slots[0]
    except Exception: pass
    for t in arm.animation_data.nla_tracks: t.mute = True
    sc.frame_set(int(f))
else:
    arm.animation_data_clear()
    for pb in arm.pose.bones: pb.matrix_basis.identity()
S = arm.scale[0] / 0.9265
sc.render.engine = 'BLENDER_WORKBENCH' if wire else 'BLENDER_EEVEE'
cage = 'cage' in a
if cage:
    for o in bpy.data.objects:
        if o.type == 'MESH': o.hide_render = o.name != 'BaseCage'
    c = bpy.data.objects['BaseCage']
    for m in c.modifiers:
        if m.type == 'SUBSURF': m.show_render = False
    w_ = c.modifiers.new('w', 'WIREFRAME'); w_.thickness = 0.0022; w_.use_replace = False
    for pl in c.data.polygons: pl.use_smooth = False
if wire:
    sh = sc.display.shading; sh.light = 'STUDIO'; sh.color_type = 'MATERIAL'; sh.show_object_outline = True
    sc.display.render_aa = '8'
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.name == 'Body':
            m = o.modifiers.new('w', 'WIREFRAME'); m.thickness = 0.0012; m.use_replace = False; m.material_offset = 0
sc.render.film_transparent = False
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs[0].default_value = (.62, .66, .70, 1); w.node_tree.nodes['Background'].inputs[1].default_value = 0.55
sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN')); sc.collection.objects.link(sun)
sun.data.energy = 3.2; sun.rotation_euler = (math.radians(55), 0, math.radians(-35))
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = 'ORTHO'
sc.view_settings.view_transform = 'Standard'
V = dict(front=(0, 0), side=(90, 0), back=(180, 0), tq=(35, 8), tqb=(145, 8), face=(0, 0), face_tq=(35, 4), face_side=(90, 0), hand=(60, 0), top=(0, 60), up=(0, 0), up_tq=(40, 10), up_back=(180, 0), lo=(0, 0), lo_tq=(40, 10), lo_side=(90, 0), hand2=(100, 0), hand3=(-20, 0))
for v in views:
    yaw, pitch = V[v]
    if v.startswith('face'): tgt = Vector((0, 0, 1.54 * S)); cam.data.ortho_scale = 0.42 * S; sc.render.resolution_x = 900; sc.render.resolution_y = 900
    elif v.startswith('hand'): tgt = Vector((0.27 * S, 0, 0.84 * S)); cam.data.ortho_scale = 0.30 * S; sc.render.resolution_x = 900; sc.render.resolution_y = 900
    elif v.startswith('up'): tgt = Vector((0, 0, 1.25 * S)); cam.data.ortho_scale = 0.95 * S; sc.render.resolution_x = 900; sc.render.resolution_y = 900
    elif v.startswith('lo'): tgt = Vector((0, 0, 0.50 * S)); cam.data.ortho_scale = 1.1 * S; sc.render.resolution_x = 900; sc.render.resolution_y = 900
    else: tgt = Vector((0, 0, 0.86 * S)); cam.data.ortho_scale = 1.9 * S; sc.render.resolution_x = 700; sc.render.resolution_y = 1100
    y, p = math.radians(yaw), math.radians(pitch)
    d = Vector((math.sin(y) * math.cos(p), -math.cos(y) * math.cos(p), math.sin(p)))
    cam.location = tgt + d * 5; cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler()
    sc.render.filepath = '%s-%s.png' % (out, v); bpy.ops.render.render(write_still=True)
