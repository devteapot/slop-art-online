import sys, json, numpy as np
from collections import Counter, defaultdict
base = sys.argv[1]
z = np.load(base+'.npz'); meta = json.load(open(base+'.json')); T = np.load(base+'_targets.npy')
P, N, UV, J, Wt = z['P'], z['N'], z['UV'], z['J'], z['W']
prims = [z[f'I{i}'] for i in range(len(meta['mats']))]
mats = meta['mats']
print('## primitives (shared buffer of %d verts)' % len(P))
vsets = []
for i,(mat,I) in enumerate(zip(mats, prims)):
    v = np.unique(I); vsets.append(v)
    q = P[v]
    print(f"{i} {mat:34s} tris={len(I):5d} verts={len(v):5d} x[{q[:,0].min()*100:6.2f},{q[:,0].max()*100:6.2f}] y[{q[:,1].min()*100:6.2f},{q[:,1].max()*100:6.2f}] z[{q[:,2].min()*100:6.2f},{q[:,2].max()*100:6.2f}] cm  uv u[{UV[v,0].min():.3f},{UV[v,0].max():.3f}] v[{UV[v,1].min():.3f},{UV[v,1].max():.3f}]")
# skin topology (prims with _SKIN)
sk = np.concatenate([I for mat,I in zip(mats,prims) if mat.endswith('_SKIN')])
# weld by position for topology (UV seams split verts)
key = np.round(P*1e5).astype(np.int64)
_, wid, winv = np.unique(key, axis=0, return_index=True, return_inverse=True)
winv = winv.ravel()
S = winv[sk]
print('## skin: tris', len(sk), 'unique verts', len(np.unique(sk)), 'welded', len(np.unique(S)))
# are tris paired into quads? count edges
E = defaultdict(int)
for a,b,c in S:
    for e in ((a,b),(b,c),(c,a)): E[tuple(sorted(e))] += 1
bnd = [e for e,c in E.items() if c==1]; nonman = [e for e,c in E.items() if c>2]
print('edges', len(E), 'boundary', len(bnd), 'non-manifold', len(nonman))
# boundary loops
adj = defaultdict(list)
for a,b in bnd: adj[a].append(b); adj[b].append(a)
seen=set(); loops=[]
for s in adj:
    if s in seen: continue
    loop=[s]; seen.add(s); cur=s; prev=None
    while True:
        nx=[n for n in adj[cur] if n!=prev and n not in seen]
        if not nx: break
        prev,cur=cur,nx[0]; seen.add(cur); loop.append(cur)
    loops.append(loop)
Pw = P[wid]
for l in sorted(loops, key=len, reverse=True)[:12]:
    q = Pw[l]; print(f"  boundary loop {len(l):4d} verts centre {np.round(q.mean(0)*100,2)} cm  x[{q[:,0].min()*100:.1f},{q[:,0].max()*100:.1f}] y[{q[:,1].min()*100:.1f},{q[:,1].max()*100:.1f}]")
# valence
val = Counter()
for (a,b) in E: val[a]+=1; val[b]+=1
vc = Counter(val.values()); print('valence histogram (welded skin):', sorted(vc.items()))
# triangle-only? Estimate quad pairing: two tris sharing an edge forming planar quad -> unknown; report
json.dump({'loops':[[int(x) for x in l] for l in loops], 'wid':wid.tolist()}, open(base+'_topo.json','w'))
print('## blend shapes')
names = [n.split('Fcl_')[-1] if 'Fcl_' in n else n.split('.')[-1] for n in meta['targets']]
rows=[]
for ti,(n,d) in enumerate(zip(names,T)):
    mag = np.linalg.norm(d,axis=1)
    moved = mag > 1e-4
    per = []
    for i,v in enumerate(vsets):
        c = int(moved[v].sum())
        if c: per.append(f"{mats[i].split('_00_')[1] if '_00_' in mats[i] else mats[i]}{'' if i!=8 else '(b)'}:{c}")
    mv = np.where(moved)[0]
    if len(mv):
        q=P[mv]; mx = mag.max()*1000; mean = mag[mv].mean()*1000
        dom = d[mv].mean(0)*1000
        print(f"{ti:2d} {n:18s} moved={len(mv):4d} max={mx:6.2f}mm mean={mean:5.2f}mm meanvec(mm)={np.round(dom,2)} y[{q[:,1].min()*100:.1f},{q[:,1].max()*100:.1f}]cm | {' '.join(per)}")
    else:
        print(f"{ti:2d} {n:18s} moved=0")
    rows.append(dict(i=ti,name=n,moved=int(len(mv)),max_mm=float(mag.max()*1000)))
json.dump(rows, open(base+'_bs.json','w'))
print('## weights: joints influencing the face')
inf = defaultdict(float); cnt=Counter()
for v in range(len(P)):
    for k in range(4):
        if Wt[v,k]>0.001: inf[meta['joints'][J[v,k]]]+=Wt[v,k]; cnt[meta['joints'][J[v,k]]]+=1
for k,vv in sorted(inf.items(), key=lambda x:-x[1]): print(f"  {k:30s} verts={cnt[k]:5d} weight-sum={vv:8.1f}")
nz = (Wt>0.001).sum(1); print('  influences per vertex:', sorted(Counter(nz.tolist()).items()))
