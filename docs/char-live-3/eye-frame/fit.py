"""Fit the two iris disks and the generated upper bands, wings and lash cards."""
from collections import defaultdict

# Use the approved cage in its world-space metres. Keep the lower border
# fixed at the pupil. Each expression supplies its own band and lash roots.
iris_width_scale = 1.27
outer_lift_m = .0013
wing_extension_m = .0040
wing_lift_m = .0048
outer_band_thickness_scale = 1.24
lash_length_scale = 1.40
ink_gain = .18

def surface_islands(data, material):
    adj = defaultdict(set)
    for poly in data.polygons:
        if data.materials[poly.material_index].name != material:
            continue
        verts = list(poly.vertices)
        for a, b in zip(verts, verts[1:] + verts[:1]):
            adj[a].add(b)
            adj[b].add(a)
    left = set(adj)
    while left:
        stack = [left.pop()]
        group = []
        while stack:
            v = stack.pop()
            group.append(v)
            neighbours = adj[v] & left
            left.difference_update(neighbours)
            stack.extend(neighbours)
        yield sorted(group)


def ramp(a, b, value):
    t = np.clip((value-a)/(b-a), 0, 1)
    return t*t*(3-2*t)


def fit_eye_frame():
    data = face.data
    keys = data.shape_keys.key_blocks
    world = face.matrix_world
    inverse = world.to_3x3().inverted()
    basis = np.array([tuple(world @ v.co) for v in keys[0].data])
    assert len(keys) == 16
    irises = list(surface_islands(data, generator.MAT['iris']))
    lines = [g for g in surface_islands(data, generator.MAT['line'])
             if basis[g,2].mean() > 1.502]
    bands = [g for g in lines if len(g) in (52,44)]
    upper_cards = [g for g in lines if len(g)==5 and basis[g[-1],2] >= basis[g[:2],2].mean()-.0005]
    assert len(irises)==2 and sorted(map(len,bands))==[44,44,52,52]
    assert len(upper_cards)>=8
    eye_ink = set(i for g in bands + upper_cards for i in g)
    # Use the cage ring's local outer canthus and attenuate through the
    # neighbouring skin. Apply the same lift to coincident seam copies.
    x, y, z = basis.T
    outer = ramp(.035, .050, abs(x)) * (1-ramp(.053,.062,abs(x)))
    outer *= (1-ramp(.005,.014,abs(z-1.519))) * ramp(.049,.060,-y)
    brow = list(surface_islands(data, generator.MAT['brow']))
    outer[[i for g in brow for i in g]] = 0
    changed = set(np.flatnonzero(outer)) | eye_ink | {i for g in irises for i in g}
    for key in keys:
        pos = np.array([tuple(world @ v.co) for v in key.data])
        shift = np.zeros_like(pos)
        shift[:,2] = outer * outer_lift_m
        for g in irises:
            # Grow the disk along its own horizontal tangent, carrying depth
            # with width so the turned iris continues to sit on the white.
            disk = pos[g]
            dx = disk[:,0] - disk[:,0].mean()
            slope = np.linalg.lstsq(np.column_stack((dx,disk[:,2]-disk[:,2].mean())),
                                    disk[:,1]-disk[:,1].mean(),rcond=None)[0][0]
            shift[g,0] += (iris_width_scale-1)*dx
            shift[g,1] += (iris_width_scale-1)*dx*slope
        for g in bands:
            n = len(g)//2
            t = np.minimum(np.arange(n)/21,1.)
            thickness = pos[g[:n]]-pos[g[n:]]
            shift[g[:n]] += ((outer_band_thickness_scale-1)*ramp(.20,.80,t))[:,None]*thickness
            if n == 26:
                # Last four longitudinal stations belong to the existing wing.
                w = np.maximum(0,(np.arange(n)-21)/4)
                w = np.tile(w,2)
                side = np.sign(pos[g,0].mean())
                shift[g,0] += side*wing_extension_m*w
                shift[g,2] += wing_lift_m*w
                shift[g,1] -= .0008*w
        for g in upper_cards:
            anchor = pos[g[:2]].mean(axis=0)
            extension = pos[g]-anchor
            shift[g] += (lash_length_scale-1)*extension
            shift[g,2] += np.array([0,0,.45,.45,1])*.0018
            shift[g,1] -= .00075
        for i in changed:
            key.data[int(i)].co += inverse @ Vector(shift[i])
    for i in changed:
        data.vertices[int(i)].co = keys[0].data[int(i)].co
    colors = data.color_attributes['Color'].data
    for poly in data.polygons:
        if data.materials[poly.material_index].name != generator.MAT['line']:
            continue
        for loop_id in poly.loop_indices:
            if data.loops[loop_id].vertex_index in eye_ink:
                c = colors[loop_id]
                c.color = (*[v*ink_gain for v in c.color[:3]], c.color[3])
    data.update()
    return dict(iris_width_scale=iris_width_scale, outer_lift_m=outer_lift_m,
                wing_extension_m=wing_extension_m, wing_lift_m=wing_lift_m,
                outer_band_thickness_scale=outer_band_thickness_scale,
                lash_length_scale=lash_length_scale, ink_gain=ink_gain,
                changed_face_vertices=len(changed), upper_lash_cards=len(upper_cards))

(ROOT/'eye-fit.json').write_text(json.dumps(fit_eye_frame(), indent=2)+'\n')
export_current()
audit('item2-eye-frame')
