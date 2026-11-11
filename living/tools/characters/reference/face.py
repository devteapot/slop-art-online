import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import G
g = G(sys.argv[1]); out = sys.argv[2]
W, par = g.world()
mi, m = g.mesh('Face')
fn = [i for i,n in enumerate(g.nodes) if n.get('mesh')==mi][0]
print('face node world', np.round(W[fn],4).tolist())
p0 = m['primitives'][0]
P = g.acc(p0['attributes']['POSITION']); N = g.acc(p0['attributes']['NORMAL']); UV = g.acc(p0['attributes']['TEXCOORD_0'])
J = g.acc(p0['attributes']['JOINTS_0']); Wt = g.acc(p0['attributes']['WEIGHTS_0'])
print('verts', len(P), 'bbox', P.min(0).round(4), P.max(0).round(4))
skin = g.j['skins'][g.nodes[fn]['skin']]; jn = [g.nodes[k]['name'] for k in skin['joints']]
names = p0.get('extras',{}).get('targetNames') or m.get('extras',{}).get('targetNames')
print('targetNames from extras:', names is not None)
prims = []
for pi,p in enumerate(m['primitives']):
    I = g.acc(p['indices']).reshape(-1,3); mat = g.j['materials'][p['material']]['name']
    prims.append((pi, mat, I))
np.savez(out, P=P, N=N, UV=UV, J=J, W=Wt, **{f'I{pi}':I for pi,_,I in prims})
json.dump({'mats':[mat for _,mat,_ in prims], 'joints':jn, 'targets':names}, open(out+'.json','w'))
# targets
T = []
for ti,t in enumerate(p0.get('targets',[])):
    d = g.acc(t['POSITION']); T.append(d)
    # check same accessor across prims
np.save(out+'_targets.npy', np.array(T))
same = all(m['primitives'][k]['targets'][0]['POSITION']==p0['targets'][0]['POSITION'] for k in range(len(m['primitives'])))
print('targets shared across prims:', same, 'normals in targets:', 'NORMAL' in p0['targets'][0])
