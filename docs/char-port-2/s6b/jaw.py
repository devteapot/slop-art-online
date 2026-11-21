"""S6b: the three jaw lines stay distinct. On each type file (front, orthographic), the face's width with the
ears left out at 0.08, 0.15 and 0.20 H over the chin (the jaw and the chin's sides), for two type folders;
per class, the lines a/b/c in order and their gaps, before and after.
    python3 jaw.py BEFORE_DIR AFTER_DIR OUT.json"""
import sys, json, glob, os, numpy as np
sys.path[:0]=['living/tools']
from merge_primitives import read_glb, read_accessor
ROWS=(0.08, 0.15, 0.20)
def arr(j,b,i): return np.array(read_accessor(j,b,i)[0], float)
def widths(path, H):
    j,b=read_glb(path); node=next(n for n in j['nodes'] if n.get('name')=='Face' and 'mesh' in n)
    names=[j['nodes'][k]['name'] for k in j['skins'][node['skin']]['joints']]; ears=[i for i,n in enumerate(names) if n.startswith('J_Id_Ear')]
    for p in j['meshes'][node['mesh']]['primitives']:
        mn=j['materials'][p['material']]['name']; a=p['attributes']
        if mn.endswith('Face_00_SKIN'):
            P=arr(j,b,a['POSITION']).reshape(-1,3); J=arr(j,b,a['JOINTS_0']).reshape(-1,4).astype(int); W=arr(j,b,a['WEIGHTS_0']).reshape(-1,4)
            earw=sum(np.where(J==e, W, 0).sum(1) for e in ears)
        if 'EyeIris' in mn: I=arr(j,b,a['POSITION']).reshape(-1,3)
    front=P[(np.abs(P[:,0])<0.006)&(P[:,2]<I[:,2].mean())]; chin=front[:,1].min()
    out=[]
    for r in ROWS:
        band=(np.abs(P[:,1]-(chin+r*H))<0.003)&(earw<0.5)
        out.append(round(float((P[band,0].max()-P[band,0].min())*1000),1))
    return out
T=json.load(open('living/tools/characters/types.json'))['types']
res={}
for side,d in (('before',sys.argv[1]),('after',sys.argv[2])):
    for f in sorted(glob.glob(os.path.join(d,'*.glb'))):
        t=os.path.basename(f)[:-4]; res.setdefault(t,{})[side]=widths(f, T[t]['head']['height_m'])
cls={}
for t,v in res.items(): cls.setdefault(t[:-2],{})[t[-1]]=v
report={}
for c,L in cls.items():
    rows=[]
    for k,r in enumerate(ROWS):
        bef=[L[x]['before'][k] for x in 'abc']; aft=[L[x]['after'][k] for x in 'abc']
        order_kept=list(np.argsort(bef))==list(np.argsort(aft))
        gaps_b=[bef[1]-bef[0], bef[2]-bef[1]]; gaps_a=[aft[1]-aft[0], aft[2]-aft[1]]
        change=[round((ga-gb)/gb,3) if abs(gb)>0.5 else None for ga,gb in zip(gaps_a,gaps_b)]
        rows.append(dict(z_over_chin=r, before_mm=bef, after_mm=aft, order_kept=order_kept, gap_change=change))
    report[c]=rows
json.dump(dict(rows_h=ROWS, classes=report), open(sys.argv[3],'w'), indent=1)
for c,rows in report.items():
    print(c, ' | '.join(f"{r['z_over_chin']}: {r['before_mm']} -> {r['after_mm']} order {r['order_kept']} gaps {r['gap_change']}" for r in rows))
