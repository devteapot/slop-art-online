"""Continue the cage's face paint over the rolled underside to its neck seam."""
from mathutils.kdtree import KDTree

def nearest_points(points):
    tree = KDTree(len(points))
    for index, point in enumerate(points):
        tree.insert(Vector(point),index)
    tree.balance()
    return tree

# The generator duplicates vertices on both seams for separate pigment and
# normals. The duplicates stay coincident, including when the keys deform.
polys = list(me.polygons)
underside = [p for p in polys if p.material_index == under]
surface = [p for p in polys if p.material_index == face_skin]
under_ids = sorted({i for p in underside for i in p.vertices})
surface_loop = {me.loops[l].vertex_index:l for p in surface for l in p.loop_indices}
face_ids = list(surface_loop)
surf_tree = nearest_points(locations[face_ids])
neck_pos = np.array([tuple(neck.matrix_world@v.co) for v in neck.data.vertices])
neck_tree = nearest_points(neck_pos)
outside = [i for i in under_ids if surf_tree.find(Vector(locations[i]))[2] < .0004]
inside = [i for i in under_ids if neck_tree.find(Vector(locations[i]))[2] < .0004]
assert len(outside)>25 and len(inside)>25
outer_tree = nearest_points(locations[outside])
inner_tree = nearest_points(locations[inside])
uv_data = me.uv_layers.active.data
normals = [n.vector.copy() for n in me.corner_normals]
stitch = {}
for i in under_ids:
    x,y,z = locations[i]
    _,out_i,d_out = outer_tree.find(Vector(locations[i]))
    _,in_i,d_in = inner_tree.find(Vector(locations[i]))
    share = d_out/max(d_out+d_in,1.e-8)
    share = share*share*(3-2*share)
    _,src,_ = surf_tree.find(Vector(locations[outside[out_i]]))
    loop = surface_loop[face_ids[src]]
    uv = uv_data[loop].uv.copy()
    uv.y = max(.005,uv.y-.022*share)
    front = np.array(colors[loop].color[:3])
    # The neck dye is linear. The face shader multiplies that dye by its
    # atlas, so express the neck endpoint relative to the atlas skin base.
    inner_dye = throat_color(x,z)/np.array((1.,.44,.27))
    pigment = np.clip(front + share*(inner_dye-front),0,1)
    inside_point = neck_pos[neck_tree.find(Vector(locations[inside[in_i]]))[1]]
    a = math.atan2(inside_point[0]/.031,(-inside_point[1]+.001)/.0435)
    end_normal = (inverse@Vector((1.15*math.sin(a),-math.cos(a),.035*(1-math.cos(a))))).normalized()
    normal = normals[loop].lerp(end_normal,share).normalized()
    stitch[i] = (uv,pigment,normal)
for p in underside:
    p.material_index = face_skin
    for li in p.loop_indices:
        uv,pigment,normal = stitch[me.loops[li].vertex_index]
        uv_data[li].uv = uv
        colors[li].color = (*pigment,1.)
        normals[li] = normal
me.normals_split_custom_set([tuple(n) for n in normals])
me.update()
