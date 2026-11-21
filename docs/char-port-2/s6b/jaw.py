"""S6b: the three jaw lines stay distinct. The face's width with the ears excluded (triangles whose corners are all under 0.5
on the ear bones) where the plane chin + r H cuts its skin triangles, at 0.08, 0.12, 0.15, 0.18 and 0.20 H; per class,
the lines a/b/c before and after. It slices the surface: the first version took the vertices within 3 mm of the
height, and where no vertex row of the jaw's back fell in that band (elder-f-b at 0.15 H) it read the jaw 11.8 mm
narrow and showed a swap that is not there.
    python3 jaw.py BEFORE_DIR AFTER_DIR OUT.json"""
import sys, json, glob, os, numpy as np
sys.path[:0]=['living/tools']
from merge_primitives import read_glb, read_accessor
arr=lambda j,b,i: np.array(read_accessor(j,b,i)[0], float)
ROWS=(0.08,0.12,0.15,0.18,0.20)
TY=json.load(open('living/tools/characters/types.json'))['types']
def widths(path,H):
    j,b=read_glb(path); node=next(n for n in j['nodes'] if n.get('name')=='Face' and 'mesh' in n)
    names=[j['nodes'][k]['name'] for k in j['skins'][node['skin']]['joints']]; ears=[i for i,n in enumerate(names) if n.startswith('J_Id_Ear')]
    for p in j['meshes'][node['mesh']]['primitives']:
        mn=j['materials'][p['material']]['name']; a=p['attributes']
        if mn.endswith('Face_00_SKIN'):
            P=arr(j,b,a['POSITION']).reshape(-1,3); Tr=arr(j,b,p['indices']).reshape(-1,3).astype(int)
            J=arr(j,b,a['JOINTS_0']).reshape(-1,4).astype(int); W=arr(j,b,a['WEIGHTS_0']).reshape(-1,4)
            earw=sum(np.where(J==e,W,0).sum(1) for e in ears)
        if 'EyeIris' in mn: I=arr(j,b,a['POSITION']).reshape(-1,3)
    front=P[(np.abs(P[:,0])<0.006)&(P[:,2]<I[:,2].mean())]; chin=front[:,1].min()
    Tr=Tr[(earw[Tr]<0.5).all(1)]
    out=[]
    for r in ROWS:
        h=chin+r*H; xs=[]
        for e0,e1 in ((0,1),(1,2),(2,0)):
            A=P[Tr[:,e0]]; B=P[Tr[:,e1]]; s=(A[:,1]-h)*(B[:,1]-h)<=0
            t=(h-A[s,1])/np.where(np.abs(B[s,1]-A[s,1])<1e-12,1e-12,B[s,1]-A[s,1]); xs.append(A[s,0]+t*(B[s,0]-A[s,0]))
        xs=np.concatenate(xs); out.append(round(float((xs.max()-xs.min())*1000),1))
    return out
res={}
for lab,d in zip(('before','after'),sys.argv[1:3]):
    for f in sorted(glob.glob(d+'/*.glb')):
        t=os.path.basename(f)[:-4]; res.setdefault(t,{})[lab]=widths(f,TY[t]['head']['height_m'])
cls={}
for t,v in res.items(): cls.setdefault(t[:-2],{})[t[-1]]=v
rep={}
for c,L in sorted(cls.items()):
    rep[c]={}
    for k,r in enumerate(ROWS):
        bef=[L[x]['before'][k] for x in 'abc']; aft=[L[x]['after'][k] for x in 'abc']
        ok=lambda v: v[0]>v[1]>v[2]
        rep[c][r]=dict(before=bef,after=aft,order_before=ok(bef),order_after=ok(aft))
        flag='' if ok(aft) or not ok(bef) else '  <-- order lost'
        print(f"{c:8s} {r:.2f} H  before {bef}  after {aft}{flag}")
json.dump(dict(rows_h=ROWS,classes=rep),open(sys.argv[3],'w'),indent=1)
