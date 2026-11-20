"""Journal block: the ink batch (items 2-5), one combined attempt.

Five strokes from the drawing's measurements, drawn by the general ink profile
(docs/HANDMADE_INK.md, v1.2) on carriers that are primitives of the face mesh:

1. upper lid with wing and two lash flicks, 2. outer lower lid, 3. brows   -> eyes map
4. jaw line, 5. nostrils                                                    -> skin map

The opaque eye-line bands and lash cards, the lower-lid line and the brow strips they replace are
removed. Opaque cores, generated from the same strokes and lying inside them, keep the lid and
brow value at play distance, where the ink fades by design. The neck shade is moved up to hug the
jaw, and the nose paint's shade and glint are tightened. Iris, opening geometry, hair and cloth
are untouched.
"""
import importlib
import bmesh

INK = SESSION/'ink-batch'
sys.path.insert(0, str(INK))
import carriers as ink_carriers
import design as ink_design
importlib.reload(ink_carriers)
importlib.reload(ink_design)

ink_params = dict(ink_design.PARAMS)
# Ink colours (sRGB albedo). Each is lit as its slot lights its own albedo.
ink_colours = {
    'Cora_LidInk_EYE': [14, 5, 4],
    'Cora_BrowInk_EYE': [57, 32, 20],
    'Cora_JawInk_SKIN': [27, 11, 7],
    'Cora_NoseInk_SKIN': [30, 11, 9],
}
ink_min_px = 1.0
# Neck: the throat shade holds full strength from the jaw down to z_full, then fades out by
# z_clear (both rising with the side as before), at a strength matched to the drawing's neck.
neck_params = dict(z_full=1.422, z_clear=1.385, side_rise=.025, strength=(.601, .724, .728),
                   side_fade=.3, base=(.754, .389, .247))
nose_params = dict(flank_u=.484, flank_half_u=.043, curve_v=.738, curve_bend=.012, curve_tilt=.004,
                   below=.0035, above=.0045, pigment=[.38, .41, .42],
                   glint_uv=[.502, .711], glint_ru=.0045, glint_rv=.0025, glint_rgb=[255, 236, 211])


def to_linear(c):
    c = c/255
    return c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4


def ink_batch():
    data = face.data
    keys = data.shape_keys.key_blocks
    W = face.matrix_world
    Winv = W.inverted()
    R3 = W.to_3x3()
    nV = len(data.vertices)
    V = np.array([tuple(W @ v.co) for v in keys[0].data])
    KV = {k.name: np.array([tuple(W @ v.co) for v in k.data]) for k in keys}
    VN = np.array([tuple((R3 @ v.normal).normalized()) for v in data.vertices])
    mats = [m.name for m in data.materials]
    mi = {name: i for i, name in enumerate(mats)}
    data.calc_loop_triangles()

    def tris(material):
        return np.array([tuple(t.vertices) for t in data.loop_triangles if t.material_index == mi[material]])
    T_skin = tris(generator.MAT['face'])
    T_brow = tris(generator.MAT['brow'])
    # The +X eye's opening: the skin's boundary loop round it.
    from collections import Counter
    count = Counter()
    for poly in data.polygons:
        if poly.material_index == mi[generator.MAT['face']]:
            vs = list(poly.vertices)
            for a, b in zip(vs, vs[1:] + vs[:1]):
                count[(min(a, b), max(a, b))] += 1
    adj = defaultdict(list)
    for (a, b), c in sorted(count.items()):
        if c == 1:
            adj[a].append(b)
            adj[b].append(a)
    loops, seen = [], set()
    for s in sorted(adj):
        if s in seen:
            continue
        loop, prev, cur = [s], None, s
        seen.add(s)
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            loop.append(cur)
            seen.add(cur)
        loops.append(loop)
    eye_loop = next(L for L in loops if V[L, 0].mean() > .02 and abs(V[L, 2].mean()-1.52) < .01)
    irises = [V[g].mean(0) for g in surface_islands(data, generator.MAT['iris'])]
    drawing = json.loads((SESSION/'eye-frame/drawing-strokes.json').read_text())

    R = ink_design.build(V, VN, T_skin, eye_loop, irises, drawing, ink_params)
    maps = ink_design.finish(R, ink_params)
    skin = ink_carriers.Surface(V, T_skin, VN)
    brow = ink_carriers.Surface(V, T_brow, VN)

    # Old opaque strokes: upper bands, lower line and lash cards round the eyes; the brows.
    line_islands = [g for g in surface_islands(data, generator.MAT['line']) if V[g, 2].mean() > 1.502]
    removed = set()
    for g in line_islands:
        if len(g) != 24:                       # keep the lid crease
            removed.update(g)
    for g in surface_islands(data, generator.MAT['brow']):
        removed.update(g)
    drop_faces = {p.index for p in data.polygons if set(p.vertices) <= removed}

    # Groups, weights and normals of the carriers from the triangles they ride.
    groups = [g.name for g in face.vertex_groups]
    Wm = np.zeros((nV, len(groups)))
    for v in data.vertices:
        for g in v.groups:
            Wm[v.index, g.group] = g.weight
    material_of = lambda name: ('Cora_BrowInk_EYE' if name.startswith('brow') and 'core' not in name else
                                generator.MAT['brow'] if name.startswith('brow core') else
                                generator.MAT['line'] if name.startswith('lid core') else
                                'Cora_JawInk_SKIN' if name == 'jaw' else
                                'Cora_NoseInk_SKIN' if name.startswith('nostril') else 'Cora_LidInk_EYE')
    for name, colour in ink_colours.items():
        if name not in mi:
            m = bpy.data.materials.new(name)
            m.use_nodes = True
            bsdf = m.node_tree.nodes['Principled BSDF']
            bsdf.inputs['Base Color'].default_value = (1, 1, 1, 1)
            bsdf.inputs['Alpha'].default_value = 0.
            m.blend_method = 'BLEND'
            data.materials.append(m)
            mi[name] = len(data.materials)-1
    ranges = {'eyes': maps['eyes']['range_uv'], 'skin': maps['skin']['range_uv']}
    for name, colour in ink_colours.items():
        slot = 'eyes' if name.endswith('_EYE') else 'skin'
        bpy.data.materials[name]['slop'] = {'slot': slot, 'ink': {
            'color': colour, 'width': 'uv', 'min_px': ink_min_px, 'range': round(ranges[slot], 6)}}

    built = []
    for rb in R['eyes'] + R['skins'] + R['cores']:
        nc, nr = rb.shape
        P = rb.P.reshape(-1, 3)
        drv = brow if rb.name.startswith('brow') else skin
        bind = ink_carriers.Binding(P, drv)
        rest = bind.at(V)
        moved = {}
        for k in keys:
            D = ink_carriers.smooth_field((bind.at(KV[k.name]) - rest).reshape(nc, nr, 3))
            if k.name == keys[0].name or np.abs(D).max() < 1e-7:
                moved[k.name] = P
            else:
                # Keep the clearance over the skin as it is in this key.
                moved[k.name] = ink_carriers.clearance(rb.P + D, rb.N, skin, KV[k.name], rb.clear).reshape(-1, 3)
        normals = drv.normal(bind.tri, bind.bary) if material_of(rb.name).endswith('_SKIN') else rb.N.reshape(-1, 3)
        uv = rb.uv.reshape(-1, 2) if hasattr(rb, 'uv') else np.zeros((nc*nr, 2))
        built.append((rb, moved, bind.weights(Wm), normals, uv, material_of(rb.name)))

    # The faces that stay keep their encoded custom normals untouched; the carriers take their
    # own smooth normals (they lie on the surface they draw on).
    bm = bmesh.new()
    bm.from_mesh(data)
    orig = bm.faces.layers.int.new('ink_orig')
    for f in bm.faces:
        f[orig] = f.index
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index in drop_faces], context='FACES')
    shape = {k.name: bm.verts.layers.shape[k.name] for k in keys}
    deform = bm.verts.layers.deform.verify()
    uvl = bm.loops.layers.uv['UVMap']
    uvf = bm.loops.layers.uv['RestForward']
    col = bm.loops.layers.float_color['Color']
    counts = {}
    for rb, moved, weights, normals, uv, material in built:
        nc, nr = rb.shape
        vs = []
        for i in range(nc*nr):
            v = bm.verts.new(Winv @ Vector(moved[keys[0].name][i]))
            for k in keys:
                v[shape[k.name]] = Winv @ Vector(moved[k.name][i])
            for g in np.flatnonzero(weights[i] > 1e-6):
                v[deform][int(g)] = float(weights[i, g])
            vs.append(v)
        colour = ([to_linear(c) for c in ink_colours['Cora_LidInk_EYE']] if rb.name.startswith('lid core') else
                  [to_linear(c) for c in ink_colours['Cora_BrowInk_EYE']] if rb.name.startswith('brow core') else [1, 1, 1])
        P = moved[keys[0].name]
        n_faces = 0
        # One winding for the whole ribbon (consistent fans keep its vertices whole on export),
        # facing the way its normals do.
        quads = [[c*nr+r, (c+1)*nr+r, (c+1)*nr+r+1, c*nr+r+1] for c in range(nc-1) for r in range(nr-1)]
        facing = sum(np.dot(np.cross(P[q[1]]-P[q[0]], P[q[3]]-P[q[0]]), normals[q].sum(0)) for q in quads)
        for q in quads:
            if True:
                a, b, d = P[q[0]], P[q[1]], P[q[3]]
                if np.linalg.norm(np.cross(b-a, d-a)) < 1e-12:
                    continue
                if facing < 0:
                    q = q[::-1]
                f = bm.faces.new([vs[i] for i in q])
                f.material_index = mi[material]
                f.smooth = True
                for e in f.edges:
                    e.smooth = True
                f[orig] = -1
                for loop, i in zip(f.loops, q):
                    loop[uvl].uv = (float(uv[i, 0]), 1-float(uv[i, 1]))
                    loop[uvf].uv = (0., 0.)
                    loop[col] = (*colour, 1.)
                n_faces += 1
        counts[rb.name] = dict(vertices=nc*nr, quads=n_faces)
    bm.to_mesh(data)
    bm.free()
    data.update()
    for name in ('ink_orig',):
        data.attributes.remove(data.attributes[name])
    data.update()

    # Ink maps, made by the contract's tool from the registered strokes.
    out = ROOT/'ink-batch'
    out.mkdir(exist_ok=True)
    for slot, m in maps.items():
        src = out/f'{slot}.strokes.json'
        src.write_text(json.dumps(dict(size=m['size'], strokes=[dict(points=s['points']) for s in m['strokes']])) + '\n')
        subprocess.run(['python3', str(repo/'living/tools/characters/ink_field.py'), str(src),
                        str(ROOT/f'own-cora-live.{slot}.ink.png'), '--range', str(round(m['range_uv'], 6))],
                       check=True, stdout=subprocess.DEVNULL)
    return dict(params=ink_params, colours=ink_colours, info=R['info'],
                maps={k: {a: b for a, b in m.items() if a != 'strokes'} for k, m in maps.items()},
                removed_vertices=len(removed), removed_faces=len(drop_faces), carriers=counts)


def neck_shade():
    neck = next(o for o in rig_items if 'fitted neck and collarbones' in o.name.lower())
    me = neck.data
    colors = me.color_attributes['Color'].data
    q = neck_params
    for poly in me.polygons:
        for li in poly.loop_indices:
            x, y, z = neck.matrix_world @ me.vertices[me.loops[li].vertex_index].co
            side = min(abs(x)/.050, 1.)
            rise = q['side_rise']*side**2
            t = np.clip((z-(q['z_clear']+rise))/(q['z_full']-q['z_clear']), 0, 1)
            depth = t*t*(3-2*t)*(1-q['side_fade']*side**2)
            colors[li].color = (*(np.array(q['base'])*(1-depth*np.array(q['strength']))), 1.)
    me.update()


def nose_paint():
    image = bpy.data.images['cora.atlas.png']
    doc, blob = glb_io.read_glb(SESSION/'eye-frame/own-cora-live.glb')
    view = doc['bufferViews'][next(im['bufferView'] for im in doc['images'] if im['name'] == 'cora.atlas')]
    source = bytes(blob[view.get('byteOffset', 0):view.get('byteOffset', 0)+view['byteLength']])
    assert hashlib.sha256(source).hexdigest() == json.loads((SESSION/'nose/nose-atlas.json').read_text())['source']
    path = ROOT/'ink-batch'/'cora.atlas.png'
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(source)
    (ROOT/'ink-batch'/'nose-paint.json').write_text(json.dumps(nose_params, indent=2)+'\n')
    subprocess.run(['python3', str(INK/'paint.py'), str(path), str(ROOT/'ink-batch'/'nose-paint.json')], check=True)
    painted = hashlib.sha256(path.read_bytes()).hexdigest()
    allowed_generator_images.add(painted)
    image.unpack(method='REMOVE')
    image.filepath = str(path)
    image.reload()
    image.pack()
    assert hashlib.sha256(bytes(image.packed_file.data)).hexdigest() == painted
    return dict(source=hashlib.sha256(source).hexdigest(), painted=painted)


def ink_export():
    """The carriers' materials as the contract asks: BLEND, alpha 0, no texture."""
    path = ROOT/'own-cora-live.glb'
    doc, buf = glb_io.read_glb(path)
    for m in doc['materials']:
        if m['name'] in ink_colours:
            pbr = m.setdefault('pbrMetallicRoughness', {})
            pbr['baseColorFactor'] = [1, 1, 1, 0]
            pbr.pop('baseColorTexture', None)
            m['alphaMode'] = 'BLEND'
            m.pop('alphaCutoff', None)
    glb_io.write_glb(path, doc, buf)


ink_report = ink_batch()
neck_shade()
ink_report['nose'] = nose_paint()
ink_report['neck'] = neck_params
export_current()
ink_export()
audit('ink-batch')
(ROOT/'ink-batch'/'fit.json').write_text(json.dumps(ink_report, indent=2, default=float)+'\n')
