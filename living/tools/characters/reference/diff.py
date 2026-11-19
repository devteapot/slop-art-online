import sys, json, numpy as np
a=np.load('npz/shino_face.npz'); b=np.load('npz/vivi_face.npz')
mats=json.load(open('npz/shino_face.json'))['mats']
Ta=np.load('npz/shino_face_targets.npy'); Tb=np.load('npz/vivi_face_targets.npy'); names=[n.split('Fcl_')[-1] for n in json.load(open('npz/shino_face.json'))['targets']]
PA, PB = a['P'].astype(float), b['P'].astype(float)
skin = np.unique(np.concatenate([a['I7'], a['I8']]))
def sim(X, Y):
    mx, my = X.mean(0), Y.mean(0); X0, Y0 = X-mx, Y-my
    U,S,Vt = np.linalg.svd(X0.T@Y0); R = (U@Vt).T
    if np.linalg.det(R) < 0: Vt[-1]*=-1; R=(U@Vt).T
    s = S.sum()/ (X0**2).sum()
    return s, R, mx, my
s,R,mx,my = sim(PB[skin], PA[skin])   # map vivi onto shino
PBa = (PB-PB[skin].mean(0))@R.T*s + PA[skin].mean(0)
print('scale vivi->shino %.3f' % s, 'rotation deg %.2f' % np.degrees(np.arccos((np.trace(R)-1)/2)))
d = PBa-PA; m = np.linalg.norm(d,axis=1)
H = PA[skin,1].max()-PA[skin,1].min()
print('after similarity: skin residual mm  mean %.2f median %.2f p90 %.2f max %.2f  (H=%.1f cm)' % (m[skin].mean()*1e3, np.median(m[skin])*1e3, np.percentile(m[skin],90)*1e3, m[skin].max()*1e3, H*100))
for i,mt in enumerate(mats):
    v=np.unique(a[f'I{i}']); print(f'  {i} {mt:34s} residual mean {m[v].mean()*1e3:5.2f} max {m[v].max()*1e3:5.2f} mm')
# region breakdown on skin by height bands
y=PA[:,1]; ymin=PA[skin,1].min()
for lo_,hi_,lab in ((0,0.12,'chin/jaw'),(0.12,0.25,'mouth'),(0.25,0.33,'nose base/cheek'),(0.33,0.45,'eyes'),(0.45,0.6,'brow/forehead'),(0.6,1.01,'cranium')):
    v=skin[((y[skin]-ymin)/H>=lo_)&((y[skin]-ymin)/H<hi_)]
    print(f'  band {lab:16s} n={len(v):4d} mean {m[v].mean()*1e3:5.2f} mm  p90 {np.percentile(m[v],90)*1e3:5.2f}  mean vector (x|abs, y, z) mm = {np.abs(d[v,0]).mean()*1e3:5.2f} {d[v,1].mean()*1e3:5.2f} {d[v,2].mean()*1e3:5.2f}')
np.save('npz/vivi_minus_shino.npy', d)
# expressions: are morph deltas the same?
print('expression deltas vivi (scaled into shino frame) vs shino:')
for ti in (2,4,12,15,22,29,33,5):
    da=Ta[ti]; db=Tb[ti]@R.T*s
    mv = np.linalg.norm(da,axis=1)>1e-4
    rel = np.linalg.norm(db[mv]-da[mv],axis=1).mean()/np.linalg.norm(da[mv],axis=1).mean()
    cos = (da[mv]*db[mv]).sum()/np.sqrt((da[mv]**2).sum()*(db[mv]**2).sum())
    print(f'  {names[ti]:14s} moved {mv.sum():4d} same vertex set {np.array_equal(mv, np.linalg.norm(Tb[ti],axis=1)>1e-4)}  relative diff {rel:.2f}  cosine {cos:.3f}')
