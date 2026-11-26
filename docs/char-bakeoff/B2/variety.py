# Track B2: sixteen people from the one base, in Blender (the morphs mixed, the height on the armature, colours and
# hair swapped). blender -b OUT/b2-base.blend --python variety.py -- OUT_DIR TEX_DIR
import bpy, sys, os, random, math
from mathutils import Vector
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
a = sys.argv[sys.argv.index('--') + 1:]; out, tex = a[0], a[1]
sys.argv = sys.argv[:sys.argv.index('--') + 1] + [out]
import base as B, hair as H
os.makedirs(out, exist_ok=True)
random.seed(5)
sc = bpy.context.scene
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
body = bpy.data.objects['Body']; decal = bpy.data.objects['FaceLayer']
arm.animation_data_clear()
for pb in arm.pose.bones: pb.matrix_basis.identity()
sc.render.engine = 'BLENDER_EEVEE'
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs[0].default_value = (.62, .66, .70, 1); w.node_tree.nodes['Background'].inputs[1].default_value = 0.55
sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN')); sc.collection.objects.link(sun)
sun.data.energy = 3.2; sun.rotation_euler = (math.radians(55), 0, math.radians(-35))
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = 2.05; sc.view_settings.view_transform = 'Standard'
sc.render.resolution_x = 500; sc.render.resolution_y = 1000
tgt = Vector((0, 0, 0.98)); cam.location = tgt + Vector((0.9, -5, 0.5)); cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler()
SKIN = ['#f2c9a8', '#e9b996', '#dca882', '#c98f6a', '#f5d3b8']
HAIRC = ['#a8482a', '#2f2a28', '#5a3a22', '#c98a3a', '#7a5230', '#1e1c20', '#8a3a1e']
GREY = ['#c9c9c6', '#a9a9a8', '#dcdcd8']
TOP = ['#e9dfcc', '#d8d2c2', '#cfd6d2', '#e2d2b8', '#c9cfc0']
BOT = ['#3d4756', '#35404a', '#4b5a48', '#5a4a3c', '#4a4a52', '#6a3a34']
SHOE = ['#6b4a36', '#4a3628', '#3a3230']
kinds = ['woman', 'man', 'child', 'elder_m', 'woman', 'man', 'elder_w', 'child', 'man', 'woman', 'woman', 'elder_m', 'child', 'man', 'woman', 'man']
for i, kind in enumerate(kinds):
    r = random.random
    mix = dict.fromkeys(B.MORPHS, 0.0)
    male = kind in ('man', 'elder_m') or (kind == 'child' and r() < .5)
    if kind == 'child': mix['Age_Child'] = 1.0; mix['Sex_Male'] = 0.25 if male else 0.0; scale = random.uniform(.62, .76)
    else:
        mix['Sex_Male'] = random.uniform(.8, 1.1) if male else random.uniform(0, .12)
        scale = random.uniform(.96, 1.04) if male else random.uniform(.89, .96)
    if kind.startswith('elder'): mix['Age_Elder'] = random.uniform(.8, 1.1); scale -= .03
    b = r()
    if b < .35: mix['Build_Heavy'] = random.uniform(.25, .95)
    elif b < .65: mix['Build_Slim'] = random.uniform(.3, 1.0)
    mix[random.choice(['Face_Round', 'Face_Long', 'Jaw_Square'])] = random.uniform(.3, 1.0)
    for ob in (body, decal):
        for k in ob.data.shape_keys.key_blocks[1:]: k.value = mix.get(k.name, 0.0)
    cols = dict(skin=random.choice(SKIN), top=random.choice(TOP), shorts=random.choice(BOT), shoes=random.choice(SHOE))
    for t in B.MATS[:4]:
        bpy.data.materials[B.MATNAME[t]].node_tree.nodes['Mix'].inputs[6].default_value = B.srgb(cols[t])
    face = {'woman': 'woman', 'man': 'man', 'child': 'child', 'elder_m': 'elder', 'elder_w': 'woman'}[kind]
    img = bpy.data.images.load(os.path.join(tex, 'face-%s.png' % face), check_existing=True)
    for n in decal.data.materials[0].node_tree.nodes:
        if n.type == 'TEX_IMAGE': n.image = img
    style = {'woman': random.choice(['woman', 'woman', 'child']), 'man': random.choice(['man', 'man', 'elder']),
             'child': random.choice(['child', 'man']), 'elder_m': 'elder', 'elder_w': 'woman'}[kind]
    hc = random.choice(GREY if kind.startswith('elder') else HAIRC)
    for o in [o for o in bpy.data.objects if o.name.startswith('Hair')]: bpy.data.objects.remove(o, do_unlink=True)
    arm.scale = (B.CHARS['woman']['scale'],) * 3; bpy.context.view_layer.update()
    hs = B.HS * (1 + mix['Age_Child'] * (B.MORPHS['Age_Child']['head'] - 1))
    hob = H.build(style, B.HJ, hs, B.YS, B.material, B.srgb(hc), B.MATNAME['hair']); B.skin_to(hob, arm)
    arm.scale = (scale,) * 3; bpy.context.view_layer.update()
    sc.render.filepath = os.path.join(out, 'v%02d.png' % i); bpy.ops.render.render(write_still=True)
    print('B2 variety', i, kind, style, round(scale, 3), {k: round(v, 2) for k, v in mix.items() if v})
