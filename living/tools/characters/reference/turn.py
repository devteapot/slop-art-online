import sys, json, numpy as np
def front_curve(segs, H):
    pts = np.array(segs).reshape(-1,3); pts = pts[pts[:,0] >= 0]
    if len(pts) < 5: return None
    xs = np.linspace(0, pts[:,0].max()*0.995, 160)
    zf = []
    for x in xs:
        m = np.abs(pts[:,0]-x) < 0.0025
        zf.append(pts[m][:,2].max() if m.any() else np.nan)
    zf = np.array(zf); ok = ~np.isnan(zf)
    return xs[ok]/H, zf[ok]/H
names = sys.argv[1:]
for f in ['0.64','0.52','0.28','0.20','0.12']:
    print(f'height {f}H:')
    for n in names:
        d = json.load(open(f'npz/{n}_m.json')); H = d['H']
        k = min(d['secs'], key=lambda s: abs(float(s)-float(f)))
        c = front_curve(d['secs'][k], H)
        if c is None: print('  ', n, '-'); continue
        x, z = c
        # smooth z a bit
        zs = np.convolve(z, np.ones(5)/5, mode='same')
        ang = np.degrees(np.arctan(-np.gradient(zs, x)))
        def at(deg):
            i = np.where((ang > deg) & (x > 0.06))[0]
            return x[i[0]] if len(i) else np.nan
        half = x.max()
        x30, x60, x75 = at(30), at(60), at(75)
        print(f'   {n:8s} half-width {half:.3f}  turns 30deg at x={x30:.3f}  60deg at {x60:.3f}  75deg at {x75:.3f}  depth lost by x=0.3H: {(z[0]-np.interp(0.3, x, z)):.3f}H')
