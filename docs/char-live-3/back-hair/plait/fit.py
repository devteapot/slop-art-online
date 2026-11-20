"""Widen the plait towards the nape and give the top of each crossing a lit dye."""
# The overhanging crown casts a real shadow on the exposed plait. Reuse the
# existing auburn mid as the darkest band on the upper face of each lobe.
crest_material = hair_material.copy()
crest_material.name = 'Cora_PlaitCrest_HAIR'
profile = crest_material['slop']['hair']
original = hair_material['slop']['hair'].to_dict()
for dest, src in [('shade','mid'),('mid','light'),('light','highlight')]:
    profile[dest] = original[src]
mesh.materials.append(crest_material)
crest_slot = len(mesh.materials)-1
braid_tiles = [idx for idx,tile in enumerate(layout['islands']) if tile['kind']=='braid']
crease_coordinate = {}
ridge_selection = {}
for strand, tile in enumerate(braid_tiles):
    ids = groups[tile]
    assert len(ids)==57*10
    centres = [sum((mesh.vertices[i].co.copy() for i in ids[j*10:j*10+10]), Vector())/10 for j in range(57)]
    for j in range(57):
        t = j/56
        gain = 1 + .44*(1-ease(.15,.92,t))
        centre = centres[j]
        tangent = (centres[min(56,j+1)]-centres[max(0,j-1)]).normalized()
        for k in range(10):
            i = ids[j*10+k]
            v = mesh.vertices[i]
            offset = v.co-centre
            # Elevation on the sloping section locates its top. A small bias
            # towards its back rounds the bright area over the exposed ridge.
            direction = offset.normalized()
            crest = direction.z + .40 * direction.y
            crease_coordinate[i] = crest
            v.co.x *= gain
    ridge_selection[tile]=0
for poly,tile in zip(mesh.polygons,poly_tiles):
    if tile in ridge_selection:
        height=sum(crease_coordinate[i] for i in poly.vertices)/len(poly.vertices)
        if height > .02:
            poly.material_index=crest_slot
            ridge_selection[tile]+=1
assert all(n>100 for n in ridge_selection.values())
mesh.update()
subprocess.run(['python3',str(SESSION/'back-hair/plait/highlights.py'),
                str(PREVIOUS/'hair/final/lock-layout.json'),str(ROOT/'own-cora-live.hair.png')],check=True)
export_current()
