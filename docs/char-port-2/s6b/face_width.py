"""S6b's first measure (no builds): on each type file, seen from the front (orthographic), the head's width at
the cheek row (0.030 m under the irises' centres), with and without the ears (vertices skinned to J_Id_Ear_*),
over the eye spacing (iris centre to iris centre)."""
import sys, json, glob, os, numpy as np
sys.path[:0]=['living/tools']
from merge_primitives import read_glb, read_accessor
def arr(j,b,i): return np.array(read_accessor(j,b,i)[0], float)
rows={}
for f in sorted(glob.glob(os.path.join(sys.argv[2] if len(sys.argv) > 2 else 'living/game/assets/lookdev/types', '*.glb'))):
    j,b=read_glb(f); node=next(n for n in j['nodes'] if n.get('name')=='Face' and 'mesh' in n)
    names=[j['nodes'][k]['name'] for k in j['skins'][node['skin']]['joints']]
    ears=[i for i,n in enumerate(names) if n.startswith('J_Id_Ear')]
    skin=iris=None
    for p in j['meshes'][node['mesh']]['primitives']:
        mn=j['materials'][p['material']]['name']; a=p['attributes']
        if mn.endswith('Face_00_SKIN'):
            P=arr(j,b,a['POSITION']).reshape(-1,3); J=arr(j,b,a['JOINTS_0']).reshape(-1,4).astype(int); W=arr(j,b,a['WEIGHTS_0']).reshape(-1,4)
            earw=sum(np.where(J==e, W, 0).sum(1) for e in ears); skin=(P, earw)
        if 'EyeIris' in mn: iris=arr(j,b,a['POSITION']).reshape(-1,3)
    P,earw=skin
    L,R=iris[iris[:,0]>0], iris[iris[:,0]<0]
    spacing=abs(L[:,0].mean()-R[:,0].mean()); eye_y=iris[:,1].mean(); yc=eye_y-0.030
    band=np.abs(P[:,1]-yc)<0.003
    w_all=P[band,0].max()-P[band,0].min()
    ne=band&(earw<0.5)
    w_face=P[ne,0].max()-P[ne,0].min()
    # where the ears-excluded outline is: its vertices' depth against the irises' (z forward)
    xm=np.argmax(np.where(ne, np.abs(P[:,0]), -1)); depth=P[xm,2]-iris[:,2].mean()
    ear=P[earw>=0.5]
    t=os.path.basename(f)[:-4]
    rows[t]=dict(spacing_mm=round(spacing*1000,1), cheek_row_mm_under_eyes=30, with_ears=round(w_all/spacing,3), ears_excluded=round(w_face/spacing,3),
                 outline_depth_behind_irises_mm=round(-depth*1000,1), ear_height_mm=round((ear[:,1].max()-ear[:,1].min())*1000,1) if len(ear) else None,
                 ear_top_over_eyes_mm=round((ear[:,1].max()-eye_y)*1000,1) if len(ear) else None, ear_bottom_under_eyes_mm=round((eye_y-ear[:,1].min())*1000,1) if len(ear) else None,
                 ear_reach_over_face_mm=round((np.abs(ear[:,0]).max()-np.abs(P[ne,0]).max())*1000,1) if len(ear) else None)
json.dump(rows, open(sys.argv[1],'w'), indent=1)
for t,r in rows.items(): print(t, r)
