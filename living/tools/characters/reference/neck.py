"""The neck of a character file, measured the same way on the reference and on ours.

    python3 -I living/tools/characters/reference/neck.py FILE.glb [--top Y] [--json OUT] [--all]

In the file's bind pose, glTF coordinates (Y up, the face toward -Z). Heights are given from
the chin in H, the head's height from chin to top (the face skin's own top, or `--top`, as
measure.py takes it); widths and depths as a share of the head's greatest width.

- the neck's width (across) and depth (front to back) on horizontal cuts from the jaw down:
  the part of each cut round the neck's axis, as far out as it runs unbroken before the
  shoulders;
- by default the skin's cuts (`…_SKIN`: what the body is under the clothes); `--all` cuts
  every mesh but the hair's, so a collar that covers the neck counts as the neck one sees;
- the pivots: `J_Bip_C_Head` and `J_Bip_C_Neck`, their heights from the chin and how far behind
  the face's front they lie;
- the seam: the height where the head's own skin (the face material) ends and the body's begins,
  at the front, the side and the back.
"""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import load, soup, section

args = [a for a in sys.argv[1:] if not a.startswith('--')]
path = args[0]
top = float(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else None
every = '--all' in sys.argv
face_tris, bones, g = load(path, lambda m: 'Face_00_SKIN' in m)
FP, _, FI = soup(face_tris)
want = (lambda m: '_HAIR' not in m and 'Far' not in m and '_01_SKIN' not in m) if every else (lambda m: '_SKIN' in m and '_01_SKIN' not in m)
tris, _, _ = load(path, want)
# The far model's meshes are left out by their nodes' names where the file has both.
P, _, I = soup(tris)
chin = float(FP[np.abs(FP[:, 0]) < 0.02][:, 1].min())
top = float(FP[:, 1].max()) if top is None else top
H = top - chin
front = float(FP[:, 2].min())  # the face's foremost point (the nose)
head_w = 0.0
for f in np.linspace(0.25, 0.95, 40):
    s = section(FP, FI, 1, chin + f * H).reshape(-1, 3)
    if len(s):
        head_w = max(head_w, float(np.ptp(s[:, 0])))

def cut(y):
    """The neck's own part of a horizontal cut: (width, depth, its middle's z), or None."""
    s = section(P, I, 1, y)
    if not len(s):
        return None
    # Segments joined into pieces; the piece round the midline.
    pts = s.reshape(-1, 3)
    key = np.round(pts[:, [0, 2]] * 2000).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.ravel().reshape(-1, 2)
    parent = list(range(inv.max() + 1))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for a, b in inv:
        parent[find(a)] = find(b)
    roots = np.array([find(a) for a in inv[:, 0]])
    best = None
    for r in np.unique(roots):
        q = s[roots == r].reshape(-1, 3)
        if q[:, 0].min() < -0.005 and q[:, 0].max() > 0.005:  # it crosses the midline
            size = np.ptp(q[:, 0]) * np.ptp(q[:, 2])
            if best is None or size > best[0]:
                best = (size, q)
    if best is None:
        return None
    q = best[1]
    return float(np.ptp(q[:, 0])), float(np.ptp(q[:, 2])), float(0.5 * (q[:, 2].min() + q[:, 2].max()))

rows = []
for f in (0.02, -0.02, -0.06, -0.10, -0.14, -0.18, -0.22, -0.26, -0.30, -0.34):
    c = cut(chin + f * H)
    if c:
        rows.append(dict(at=f, y=round(chin + f * H, 4), width=c[0], depth=c[1], width_share=c[0] / head_w, depth_share=c[1] / head_w, middle_behind_front_H=(c[2] - front) / H))
# The seam: where the face material's skin stops, at the front, the side and the back.
def lowest(sel):
    return float(FP[sel][:, 1].min()) if sel.any() else None
zc = float(np.median(FP[:, 2]))
seam = dict(front=lowest((np.abs(FP[:, 0]) < 0.015) & (FP[:, 2] < zc)), side=lowest(np.abs(FP[:, 0]) > 0.6 * head_w / 2), back=lowest((np.abs(FP[:, 0]) < 0.02) & (FP[:, 2] > zc)))
out = dict(file=os.path.basename(path), chin=chin, top=top, H=H, head_width=head_w, head_width_H=head_w / H, cuts=rows,
           pivots={k: dict(y=float(bones[k][1]), z=float(bones[k][2]), above_chin_H=float((bones[k][1] - chin) / H), behind_front_H=float((bones[k][2] - front) / H)) for k in ('J_Bip_C_Head', 'J_Bip_C_Neck') if k in bones},
           seam={k: (None if v is None else dict(y=v, above_chin_H=(v - chin) / H)) for k, v in seam.items()}, what='every mesh but hair' if every else 'skin')
if '--json' in sys.argv:
    json.dump(out, open(sys.argv[sys.argv.index('--json') + 1], 'w'), indent=1)
print(f"{out['file']}: chin {chin:.3f} m, H {H:.3f} m, head width {head_w:.3f} m ({head_w / H:.2f} H); cuts of {out['what']}")
for r in rows:
    print(f"  {r['at']:+.2f} H ({r['y']:.3f} m): width {r['width'] * 100:5.1f} cm = {r['width_share']:.2f} of the head's, depth {r['depth'] * 100:5.1f} cm = {r['depth_share']:.2f}, its middle {r['middle_behind_front_H']:.3f} H behind the face's front")
for k, v in out['pivots'].items():
    print(f"  {k}: {v['above_chin_H']:+.3f} H from the chin ({v['y']:.3f} m), {v['behind_front_H']:.3f} H behind the face's front")
print('  seam (the face skin ends): ' + ', '.join(f"{k} {v['above_chin_H']:+.3f} H" for k, v in out['seam'].items() if v))
