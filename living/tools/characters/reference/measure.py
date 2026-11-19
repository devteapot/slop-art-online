"""Landmarks and proportions of a face skin (glTF coords, faces -Z), and sections normalised for plotting."""
import sys, os, json, numpy as np
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import load, soup, section
path, out = sys.argv[1], sys.argv[2]
tris, bones, g = load(path, lambda m: m.endswith('Face_00_SKIN'))
P, N, I = soup(tris)
P = P * np.array([1, 1, -1.0])  # now the face looks +Z
key = np.round(P*1e5).astype(np.int64)
_, wid, inv = np.unique(key, axis=0, return_index=True, return_inverse=True); inv = inv.ravel()
Pw = P[wid]; T = inv[I]
E = defaultdict(int)
for a,b,c in T:
    for e in ((a,b),(b,c),(c,a)): E[tuple(sorted(e))] += 1
adj = defaultdict(list)
for (a,b),c in E.items():
    if c == 1: adj[a].append(b); adj[b].append(a)
seen=set(); loops=[]
for s in adj:
    if s in seen: continue
    loop=[s]; seen.add(s); cur=s; prev=None
    while True:
        nx=[n for n in adj[cur] if n not in seen]
        if not nx: break
        cur=nx[0]; seen.add(cur); loop.append(cur)
    loops.append(np.array(loop))
chin, top = P[:,1].min(), P[:,1].max()
if len(sys.argv) > 3: top = float(sys.argv[3])
H = top-chin
eyes=[]; mouth=None
for l in loops:
    q = Pw[l]; c = q.mean(0); w = np.ptp(q[:,0]); h = np.ptp(q[:,1])
    if 0.01 < abs(c[0]) < 0.07 and 0.3 < (c[1]-chin)/H < 0.7 and w < 0.06: eyes.append((c, w, h, q))
    elif abs(c[0]) < 0.004 and (c[1]-chin)/H < 0.35 and w < 0.06 and len(l) > 6: mouth = (c, w, h, q)
eyes.sort(key=lambda e: e[0][0])
R = {}
if eyes:
    eL = eyes[-1]; ec = eL[0]
    R['eye_centre_share'] = (ec[1]-chin)/H
    R['eye_w_H'] = eL[1]/H; R['eye_h_over_w'] = eL[2]/eL[1]; R['eye_sep_H'] = 2*ec[0]/H
    R['eye_rim_inner_x'] = eL[3][:,0].min()
if mouth: R['mouth_w_H'] = mouth[1]/H; R['mouth_share'] = (mouth[0][1]-chin)/H
# midline profile: front z along y near x=0
mid = np.concatenate([section(P, I, 0, dx).reshape(-1,3) for dx in (1e-4, -1e-4, 0.002)])
mid = mid[mid[:,2] > np.median(mid[:,2])-0.05]
def front_at(y, xs=None):
    s = section(P, I, 1, y).reshape(-1,3)
    return s
# Face width at heights
def width(y):
    s = section(P, I, 1, y).reshape(-1,3)
    return 2*np.abs(s[:,0]).max() if len(s) else 0
ey = eyes[-1][0][1] if eyes else chin+0.5*H
R['width_eye_H'] = width(ey)/H
R['width_cheek_H'] = width(chin + 0.30*H)/H
R['width_mouth_H'] = width(mouth[0][1] if mouth else chin+0.2*H)/H
R['width_jawmid_H'] = width(chin + 0.12*H)/H
R['width_max_H'] = max(width(chin+f*H) for f in np.linspace(0.05,0.95,60))/H
# nose: front-most midline point between eye and mouth
m2 = mid[(mid[:,1] < ey) & (mid[:,1] > (mouth[0][1] if mouth else chin+0.2*H))]
tip = m2[np.argmax(m2[:,2])]
R['nose_tip_share'] = (tip[1]-chin)/H
def mid_z(y):
    q = mid[np.abs(mid[:,1]-y) < 0.004]
    return q[:,2].max() if len(q) else np.nan
yl = (mouth[0][1] + 0.025*H) if mouth else tip[1] - 0.06*H
zn, zl = mid_z(ey), mid_z(yl)
line = zn + (zl - zn) * (tip[1] - ey) / (yl - ey)
R['nose_off_profile_H'] = (tip[2] - line)/H
R['profile_slope_deg'] = float(np.degrees(np.arctan2(zl - zn, ey - yl)))  # + the lip ahead of the nasion

# nose protrusion: tip z minus front of the cheek at x = eye centre x, at the tip's height
s = section(P, I, 1, tip[1]).reshape(-1,3)
ex = eyes[-1][0][0] if eyes else 0.03
near = s[np.abs(np.abs(s[:,0])-ex) < 0.004]
R['nose_out_H'] = (tip[2] - near[:,2].max())/H if len(near) else None
# eye recess: eye rim mean z vs the front surface at brow (above) and the nasion
if eyes:
    rim_z = eyes[-1][3][:,2].mean()
    s_b = section(P, I, 1, ey + 0.12*H).reshape(-1,3); bz = s_b[np.abs(s_b[:,0]-eyes[-1][0][0])<0.005][:,2].max()
    s_c = section(P, I, 1, ey - 0.10*H).reshape(-1,3); cz = s_c[np.abs(s_c[:,0]-eyes[-1][0][0])<0.005][:,2].max()
    R['eye_rim_behind_brow_H'] = (bz - rim_z)/H; R['eye_rim_behind_cheek_H'] = (cz - rim_z)/H
    mz = mid[np.abs(mid[:,1]-ey)<0.006][:,2].max() if (np.abs(mid[:,1]-ey)<0.006).any() else np.nan
    R['eye_rim_behind_nasion_H'] = (mz - rim_z)/H
# chin: profile — z of chin front vs mouth front
R['H_m'] = H
# front plane width: in each section, where the surface normal (in xz) turns > 30/45/60 deg from +z
def turn_x(y, deg):
    s = section(P, I, 1, y)
    if len(s)==0: return None
    best=None
    for a,b in s:
        if a[2] < np.median(s[:,:,2]) - 0.02: continue
        d = b-a; n = np.array([d[2], -d[0]]); n /= (np.linalg.norm(n)+1e-12)
        ang = np.degrees(np.arccos(abs(n[1]))) if False else None
    # do it on a resampled curve instead
    pts = s.reshape(-1,3); pts = pts[pts[:,0] > 0]; pts = pts[np.argsort(pts[:,0])]
    if len(pts) < 4: return None
    xs = np.linspace(0, pts[:,0].max(), 200)
    # front-most z at each x
    zf = np.array([pts[np.abs(pts[:,0]-x) < 0.002][:,2].max() if (np.abs(pts[:,0]-x) < 0.002).any() else np.nan for x in xs])
    ok = ~np.isnan(zf); xs, zf = xs[ok], zf[ok]
    slope = np.degrees(np.arctan(-np.gradient(zf, xs)))
    over = np.where((slope > deg) & (xs > 0.11*H))[0]
    return xs[over[0]] if len(over) else xs[-1]
R['frontplane_brow_45_H'] = 2*turn_x(ey+0.10*H, 45)/H
R['frontplane_brow_30_H'] = 2*turn_x(ey+0.10*H, 30)/H
R['frontplane_cheek_45_H'] = 2*turn_x(ey-0.09*H, 45)/H
R['frontplane_cheek_30_H'] = 2*turn_x(ey-0.09*H, 30)/H
R['frontplane_mouth_45_H'] = 2*turn_x(chin+0.17*H, 45)/H
for k,v in R.items(): print(f'{k:28s} {v:.3f}' if isinstance(v,float) else f'{k:28s} {v}')
secs = {f'{f:.2f}': (section(P, I, 1, chin+f*H).reshape(-1,2,3)).tolist() for f in np.round(np.arange(0.04, 0.99, 0.04),2)}
prof = {f'{fx:.2f}': (section(P, I, 0, 1e-5+fx*H).reshape(-1,2,3)).tolist() for fx in (0.0, 0.08, 0.15, 0.22, 0.30)}
json.dump({'R':R, 'chin':float(chin), 'top':float(top), 'H':float(H), 'eye': (eyes[-1][0].tolist() if eyes else None), 'secs':secs, 'prof':prof, 'tip':tip.tolist()}, open(out,'w'))
