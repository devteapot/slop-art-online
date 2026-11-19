"""Refit the existing cloth pigments, stored in Blender's linear corner RGB."""
cloth_dyes = json.loads((SESSION / 'final' / 'cloth-dyes.json').read_text())
cloth_lookup = {tuple(dye['old']): name for name, dye in cloth_dyes.items()}
cloth_hits = dict.fromkeys(cloth_dyes, 0)
for part in rig_items:
    cloth_slots = {n for n, material in enumerate(part.data.materials)
                   if material and material.name == generator.MAT['cloth']}
    if not cloth_slots:
        continue
    colors = part.data.color_attributes['Color']
    assert colors.domain == 'CORNER'
    for poly in part.data.polygons:
        if poly.material_index not in cloth_slots:
            continue
        for li in poly.loop_indices:
            pigment = colors.data[li]
            key = tuple(round(value * 65535) for value in pigment.color[:3])
            name = cloth_lookup.get(key)
            if name:
                pigment.color = (*[c / 65535 for c in cloth_dyes[name]['new']], pigment.color[3])
                cloth_hits[name] += 1
assert all(cloth_hits.values()), cloth_hits
(ROOT / 'cloth-corners.json').write_text(json.dumps(cloth_hits, indent=2) + '\n')
export_handmade()
# The export creates the directional mask; restore the approved painted shadow.
subprocess.run(['python3', str(SESSION/'face-shading/paint_features.py'), 'shadow',
                str(ROOT/'own-cora-live.face.png')], check=True)
reset_views()
review_pass('cloth-final')
clear_render_buffer()
audit('stage5-cloth-final')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'cora-final.blend'))
