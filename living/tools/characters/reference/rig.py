import sys, os, json, numpy as np
from collections import defaultdict, Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import G
g = G(sys.argv[1]); W, par = g.world(); nodes = g.nodes
name = lambda i: nodes[i].get('name')
# head subtree
hi = [i for i,n in enumerate(nodes) if n.get('name')=='J_Bip_C_Head'][0]
def tree(i, d=0, maxd=3):
    kids = nodes[i].get('children', [])
    hair = [k for k in kids if name(k).startswith('HairJoint') or name(k).startswith('J_Sec_Hair')]
    print('  '*d + f"{name(i)} @ {np.round(W[i][:3,3],4).tolist()}" + (f"  (+{len(hair)} hair chains)" if hair else ''))
    if d < maxd:
        for k in kids:
            if k not in hair: tree(k, d+1, maxd)
tree(hi)
ni = [i for i,n in enumerate(nodes) if n.get('name')=='J_Bip_C_Neck'][0]; print('neck', np.round(W[ni][:3,3],4).tolist(), 'parent', name(par[ni]))
# hair chains: length in joints
def chain_len(i):
    n=1
    while nodes[i].get('children'): i = nodes[i]['children'][0]; n+=1
    return n
hairroots = [k for k in nodes[hi].get('children',[]) if name(k).startswith('Hair') or name(k).startswith('J_Sec_Hair')]
print('hair chains', len(hairroots), 'joints per chain', Counter(chain_len(k) for k in hairroots))
# weights of the body mesh around the neck and shoulders
for mn in ('Body', 'Face'):
    for mi, m in enumerate(g.j['meshes']):
        if not m['name'].startswith(mn): continue
        node = [i for i,n in enumerate(nodes) if n.get('mesh')==mi][0]
        skin = g.j['skins'][nodes[node]['skin']]; jn = [name(k) for k in skin['joints']]
        p = m['primitives'][0]
        P = g.acc(p['attributes']['POSITION']); J = g.acc(p['attributes']['JOINTS_0']); Wt = g.acc(p['attributes']['WEIGHTS_0'])
        used = np.unique(np.concatenate([g.acc(q['indices']).ravel() for q in m['primitives'] if 'SKIN' in g.j['materials'][q['material']]['name']]))
        sel = used[(P[used,1] > 1.22) & (P[used,1] < 1.47) & (np.abs(P[used,0]) < 0.17)] if mn=="Body" else used
        print(f'== {m["name"]} skin verts in band: {len(sel)}  (y {P[sel,1].min():.3f}..{P[sel,1].max():.3f})')
        inf = defaultdict(list)
        for v in sel:
            for k in range(4):
                if Wt[v,k] > 0.001: inf[jn[J[v,k]]].append(Wt[v,k])
        for k, ws in sorted(inf.items(), key=lambda x: -sum(x[1])):
            ws = np.array(ws); print(f'   {k:24s} verts={len(ws):5d}  full(>0.99)={int((ws>0.99).sum()):5d}  partial={int((ws<=0.99).sum()):5d}  mean={ws.mean():.2f}')
        nz = (Wt[sel] > 0.001).sum(1); print('   influences per vertex', sorted(Counter(nz.tolist()).items()))
        # vertical weight profile of the neck: head weight vs height at the midline front
        if mn == 'Body':
            hj = jn.index('J_Bip_C_Head') if 'J_Bip_C_Head' in jn else None; nj = jn.index('J_Bip_C_Neck')
            rows = []
            for y0 in np.arange(1.22, 1.47, 0.02):
                m_ = sel[(P[sel,1] >= y0) & (P[sel,1] < y0+0.02)]
                if not len(m_): continue
                def w_of(j): return np.mean([sum(Wt[v,k] for k in range(4) if J[v,k]==j) for v in m_])
                rows.append(f'{y0:.2f}: neck {w_of(nj):.2f} head {w_of(hj) if hj is not None else 0:.2f} upperchest {w_of(jn.index("J_Bip_C_UpperChest")):.2f} shoulderL {w_of(jn.index("J_Bip_L_Shoulder")):.2f} upperarmL {w_of(jn.index("J_Bip_L_UpperArm")):.2f}  n={len(m_)}')
            print('   by height (mean weight):'); [print('     '+r) for r in rows]
