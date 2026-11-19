"""Blender block called by the session journal after the approved hair export."""
from collections import defaultdict

attempt = globals().get('face_shading_pass', 1)
second = attempt >= 2
final_fit = attempt == 3
paint_dir = ROOT/'stage3-generator-paint'
paint_dir.mkdir(exist_ok=True)
paint_script = SESSION/'face-shading/paint_features.py'
for suffix in ('atlas','tint'):
    image = bpy.data.images['cora.'+suffix+'.png']
    (paint_dir/image.name).write_bytes(bytes(image.packed_file.data))
subprocess.run(['python3',str(paint_script),str(paint_dir)]+(['--second'] if second else [])+(['--final'] if final_fit else []),check=True)
for suffix in ('atlas','tint'):
    image = bpy.data.images['cora.'+suffix+'.png']
    source = paint_dir/image.name
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if isinstance(allowed_generator_images,dict):
        allowed_generator_images[digest] = image.name
    else:
        allowed_generator_images.add(digest)
    image.unpack(method='REMOVE')
    image.filepath=str(source)
    image.reload()
    image.pack()

me=face.data
basis=me.shape_keys.key_blocks[0]
world=face.matrix_world
inverse=world.to_3x3().inverted()
locations=np.array([tuple(world@v.co) for v in basis.data])
displacement=np.zeros_like(locations)
slots={slot.name:i for i,slot in enumerate(me.materials)}
ink_vertices=set()
def components_at(slot):
    links=defaultdict(set)
    for poly in me.polygons:
        if poly.material_index==slot:
            ids=list(poly.vertices)
            for i,j in zip(ids,ids[1:]+ids[:1]):
                links[i].add(j);links[j].add(i)
    remaining=set(links)
    while remaining:
        stack=[remaining.pop()];group=[]
        while stack:
            i=stack.pop();group.append(i)
            for j in links[i]&remaining:
                remaining.remove(j);stack.append(j)
        yield sorted(group)

fitted_groups={'line':[], 'brow':[]}
for role in ('line','brow'):
    for group in components_at(slots[generator.MAT[role]]):
        pts=locations[group]
        if pts[:,2].mean()<1.502:
            continue
        if role=='brow' or (len(group)>=38 and len(group)%2==0):
            fitted_groups[role].append(len(group))
            n=len(group)//2
            thickness=pts[:n]-pts[n:]
            ratio=.18 if role=='brow' else .54
            displacement[group[:n]] += thickness*ratio
            if role=='line':
                displacement[group,1] -= .0007
            ink_vertices.update(group)
        elif len(group)==5:
            # Existing tapered lash card. Extend it out of its band and keep
            # its base attached for blinks, smiles and eye closure.
            root=pts[:2].mean(0)
            displacement[group] += (pts-root)*.86
            displacement[group,2] += .0012
            displacement[group,1] -= .0012
            ink_vertices.update(group)

assert len(fitted_groups['line'])>=4 and len(fitted_groups['brow'])==2, fitted_groups
# The low central pad has a sharp ridge on its last rings. Round the lowest
# two millimetres continuously, carrying the same correction into each key.
for i,(x,y,z) in enumerate(locations):
    if z<1.438 and -y>.062:
        floor=1.429+.003*(x/.023)**2
        displacement[i,2] += .65*max(0,floor-z)*np.exp(-(x/.026)**4)
if second:
    # Relax coincident seam copies together so the chin contour is round in
    # three-quarter, without opening the skin on a morph.
    corners, groups = np.unique(locations.round(6),axis=0,return_inverse=True)
    adj = defaultdict(set)
    for edge in me.edges:
        a,b = (groups[i] for i in edge.vertices)
        if a!=b:
            adj[a].add(b); adj[b].add(a)
    smoothed = corners.copy()
    for _ in range(4):
        prev = smoothed.copy()
        for i,(x,y,z) in enumerate(corners):
            if z<1.448 and -y>.057 and adj[i]:
                w=np.clip((1.448-z)/.014,0,1)*np.clip((-y-.057)/.015,0,1)
                smoothed[i] += .58*w*(prev[sorted(adj[i])].mean(0)-prev[i])
    displacement += (smoothed-corners)[groups]
for i in np.flatnonzero(np.any(displacement!=0,axis=1)):
    shift=inverse@Vector(displacement[i])
    for key in me.shape_keys.key_blocks:
        key.data[i].co += shift
    me.vertices[i].co=basis.data[i].co
me.update()

face_skin=slots[generator.MAT['face']]
under=slots[generator.MAT['skin']]
colors=me.color_attributes['Color'].data

def throat_color(x,z):
    # Both sides of the neck attachment use one dye field in model space.
    # Pigment is deepest beneath the front of the chin and rises towards the ear.
    side = min(abs(x)/.050,1.)
    depth = np.exp(-((z-(1.420+.025*side**2))/.034)**2)
    depth *= 1-.74*side**2
    strength = (.694,.821,.801) if final_fit else (.61,.70,.68)
    return np.array((.754,.389,.247))*(1-depth*np.array(strength))

for poly in me.polygons:
    for li in poly.loop_indices:
        i=me.loops[li].vertex_index
        x,y,z=locations[i]
        c=np.array(colors[li].color[:3])
        if i in ink_vertices:
            c*=.53 if poly.material_index==slots[generator.MAT['line']] else .8
        elif poly.material_index==face_skin:
            edge=1.430+.027*min(abs(x)/.063,1.25)**1.55
            roll=np.exp(-((z-edge)/.013)**2)
            if second:
                lower=np.clip((edge+.014-z)/.020,0,1)
                roll=max(roll*.68,lower)
            c*=1-roll*np.array((.14,.28,.33))
        elif poly.material_index==under:
            c=throat_color(x,z) if second else c*np.array((.77,.54,.48))
        colors[li].color=(*c,1.)
neck=next(o for o in rig_items if 'fitted neck and collarbones' in o.name.lower())
for poly in neck.data.polygons:
    for li in poly.loop_indices:
        index=neck.data.loops[li].vertex_index
        x,y,z=neck.matrix_world@neck.data.vertices[index].co
        a=np.exp(-((z-1.432)/.033)**2)
        c=neck.data.color_attributes['Color'].data[li]
        neck_value=throat_color(x,z) if second else np.array(c.color[:3])*(1-a*np.array((.32,.48,.54)))
        c.color=(*neck_value,1.)
if final_fit:
    jaw_block=SESSION/'face-shading/under_jaw.py'
    exec(compile(jaw_block.read_text(),str(jaw_block),'exec'),globals())
export_handmade()
subprocess.run(['python3',str(paint_script),'shadow',str(ROOT/'own-cora-live.face.png')],check=True)
reset_views();review_pass('face3')
clear_render_buffer();audit(('stage3-high-1','stage3-high-2','stage3-xhigh')[attempt-1])
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'cora-final.blend'))
