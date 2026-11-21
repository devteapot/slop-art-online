"""Journal block. Change only the packed procedural skin atlas."""
image = bpy.data.images['cora.atlas.png']
source = bytes(image.packed_file.data)
source_hash = hashlib.sha256(source).hexdigest()
assert source_hash in allowed_generator_images
paint_path = ROOT/'nose-paint'/'cora.atlas.png'
paint_path.parent.mkdir(exist_ok=True)
paint_path.write_bytes(source)
subprocess.run(['python3',str(SESSION/'nose/paint.py'),str(paint_path)],check=True)
paint_hash = hashlib.sha256(paint_path.read_bytes()).hexdigest()
assert paint_hash != source_hash
allowed_generator_images.add(paint_hash)
image.unpack(method='REMOVE')
image.filepath = str(paint_path)
image.reload()
image.pack()
assert hashlib.sha256(bytes(image.packed_file.data)).hexdigest()==paint_hash
export_current()
audit('item4-nose')
(ROOT/'nose-atlas.json').write_text(json.dumps(dict(source=source_hash,painted=paint_hash),indent=2)+'\n')
