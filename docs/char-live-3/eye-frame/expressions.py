"""Exercise every approved shape key at the registered stage-2 camera."""
for fn in ('studio_preview','set_expression','detail_view','wp','view'):
    exec(compile(ast.Module([baseline_function(fn)], []), str(baseline), 'exec'), globals())
camera = scene.camera
unit = 1.65/763
saved_matrix = camera.matrix_world.copy()
saved_span = camera.data.ortho_scale
old_size = (scene.render.resolution_x, scene.render.resolution_y)
old_path = scene.render.filepath
keys = face.data.shape_keys.key_blocks
names = [key.name for key in list(keys)[1:]]
assert len(names)==15 and {'Fcl_EYE_Close','Fcl_EYE_Joy'} <= set(names)
swaps = studio_preview()
try:
    for name in ['neutral'] + names + ['returned']:
        set_expression({name:1.} if name in names else {})
        detail_view('eye',name,wp(0,0,77),0,134*unit)
    detail_view('eye','three-quarter',wp(0,0,77),-35,134*unit)
finally:
    set_expression({})
    for tree,sock,old,nodes in swaps:
        tree.links.new(old,sock)
        for node in nodes:
            tree.nodes.remove(node)
    camera.matrix_world = saved_matrix
    camera.data.ortho_scale = saved_span
    scene.render.resolution_x,scene.render.resolution_y = old_size
    scene.render.filepath = old_path
    clear_render_buffer()
audit(f"item{record['item']}-expression-sweep")
