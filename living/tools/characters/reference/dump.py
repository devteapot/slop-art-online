import json, sys, numpy as np
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import G
CT = {5120:np.int8,5121:np.uint8,5122:np.int16,5123:np.uint16,5125:np.uint32,5126:np.float32}
NC = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}
_g = G(sys.argv[1]); j, B = _g.j, _g.B
def acc(i):
    a = j['accessors'][i]; bv = j['bufferViews'][a['bufferView']]
    n = NC[a['type']]; dt = np.dtype(CT[a['componentType']])
    off = bv.get('byteOffset',0)+a.get('byteOffset',0); stride = bv.get('byteStride', dt.itemsize*n)
    raw = np.frombuffer(B, dtype=np.uint8, count=stride*(a['count']-1)+dt.itemsize*n, offset=off)
    out = np.lib.stride_tricks.as_strided(raw, shape=(a['count'], dt.itemsize*n), strides=(stride,1)).copy().view(dt).reshape(a['count'], n)
    return out
nodes = j['nodes']
print('== meshes')
for mi, m in enumerate(j['meshes']):
    users = [n['name'] for n in nodes if n.get('mesh')==mi]
    print(f"mesh {mi} {m['name']} nodes={users} prims={len(m['primitives'])} targetNames={len(m.get('extras',{}).get('targetNames',[]))}")
    for pi, p in enumerate(m['primitives']):
        mat = j['materials'][p['material']]['name']
        nv = j['accessors'][p['attributes']['POSITION']]['count']; nt = j['accessors'][p['indices']]['count']//3
        print(f"  prim {pi} mat={mat} verts={nv} tris={nt} attrs={sorted(p['attributes'])} targets={len(p.get('targets',[]))}")
print('== materials')
for i,m in enumerate(j['materials']):
    print(i, m['name'], m.get('alphaMode'), m.get('doubleSided'), list(m.get('extensions',{})))
print('== images')
for i,im in enumerate(j['images']):
    bv = j['bufferViews'][im['bufferView']]
    print(i, im.get('name'), im.get('mimeType'), bv['byteLength'])
vrm = j['extensions']['VRM']
print('== VRM keys', list(vrm))
print('== materialProperties')
for mp in vrm['materialProperties']:
    print(json.dumps({'name':mp['name'],'shader':mp['shader'],'renderQueue':mp['renderQueue'],'float':mp['floatProperties'],'vector':mp['vectorProperties'],'tex':mp['textureProperties'],'keywords':mp['keywordMap'],'tags':mp['tagMap']}))
print('== humanoid')
h = vrm['humanoid']
print(json.dumps({k:v for k,v in h.items() if k!='humanBones'}))
print(len(h['humanBones']), [ (b['bone'], nodes[b['node']]['name']) for b in h['humanBones']])
print('== firstPerson'); print(json.dumps(vrm['firstPerson'])[:3000])
print('== blendShapeMaster')
for g in vrm['blendShapeMaster']['blendShapeGroups']:
    print(json.dumps(g))
print('== secondaryAnimation')
sa = vrm['secondaryAnimation']
for b in sa['boneGroups']:
    print(json.dumps({k:(v if k!='bones' else [nodes[x]['name'] for x in v]) for k,v in b.items()}))
for c in sa['colliderGroups']:
    print(nodes[c['node']]['name'], json.dumps(c['colliders']))
