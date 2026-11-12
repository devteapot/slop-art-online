"""The brows' place on a character file, measured the same way on the reference and on ours.

    python3 -I living/tools/characters/reference/brow.py FILE.glb [--top Y] [--json OUT]

In the file's bind pose, glTF coordinates (Y up, the face toward -Z), in the front view. H is
the head's height from chin to top (the face skin's own top, or `--top`, as measure.py takes
it).

- The eye's opening is the open loop in the face's skin round one eye (as measure.py finds it):
  its top and bottom, its corners, its height.
- The brow is the brow material (`FaceBrow`) where it shows: on a card with a picture, the
  texels whose alpha is over a half, placed on the card by its UVs; on plain geometry, the
  geometry. Both sides are folded onto one.

Printed, in H and in heights of the opening:
  gap      the brow's lower edge above the opening's top, over the middle third of the opening
  centre   the brow's middle line above the opening's top, at the opening's inner corner, its
           middle and its outer corner (the arch and the tilt are in these three)
  thick    the brow's greatest thickness; long: its length across; in, out: how far its ends
           lie beyond the opening's corners, toward the nose and toward the ear
"""
import sys, os, io, json, numpy as np
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import load, soup

args = [a for a in sys.argv[1:] if not a.startswith('--')]
path = args[0]
top = float(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else None
tris, bones, g = load(path, lambda m: m.endswith('Face_00_SKIN'))
P, _, I = soup(tris)
chin = float(P[np.abs(P[:, 0]) < 0.02][:, 1].min())
top = float(P[:, 1].max()) if top is None else top
H = top - chin
# The openings: loops of edges that belong to one triangle.
key = np.round(P * 1e5).astype(np.int64)
_, wid, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
inv = inv.ravel(); Pw = P[wid]; T = inv[I]
E = defaultdict(int)
for a, b, c in T:
    for e in ((a, b), (b, c), (c, a)):
        E[tuple(sorted(e))] += 1
adj = defaultdict(list)
for (a, b), c in E.items():
    if c == 1:
        adj[a].append(b); adj[b].append(a)
seen = set(); eyes = []
for s in adj:
    if s in seen:
        continue
    loop = [s]; seen.add(s); cur = s
    while True:
        nx = [n for n in adj[cur] if n not in seen]
        if not nx:
            break
        cur = nx[0]; seen.add(cur); loop.append(cur)
    q = Pw[np.array(loop)]; c = q.mean(0); w = np.ptp(q[:, 0])
    if 0.01 < abs(c[0]) < 0.07 and 0.3 < (c[1] - chin) / H < 0.7 and w < 0.06 and len(loop) > 6:
        eyes.append(q)
if not eyes:
    raise SystemExit(f'brow: {path}: no eye opening in the face skin')
eye = max(eyes, key=lambda q: q[:, 0].mean())  # the one at +x
ex0, ex1 = float(eye[:, 0].min()), float(eye[:, 0].max())
etop, ebot = float(eye[:, 1].max()), float(eye[:, 1].min())
eh = etop - ebot

# The brow, as points in the front view.
btris, _, _ = load(path, lambda m: 'FaceBrow' in m)
if not btris:
    raise SystemExit(f'brow: {path}: no brow material (FaceBrow)')
pts = []
for Pb, _, Ib, mat, uv in btris:
    alpha = None
    m = next(x for x in g.j['materials'] if x['name'] == mat)
    tex = (m.get('pbrMetallicRoughness') or {}).get('baseColorTexture')
    if tex is not None:
        from PIL import Image
        im = Image.open(io.BytesIO(g.image(g.j['textures'][tex['index']]['source'])))
        if im.mode in ('RGBA', 'LA'):
            alpha = np.asarray(im.convert('RGBA'))[..., 3] / 255.0
    k = 40
    a, b = np.meshgrid(np.linspace(0, 1, k), np.linspace(0, 1, k))
    keep = a + b <= 1
    w0, w1, w2 = (1 - a - b)[keep], a[keep], b[keep]
    for t in Ib:
        q = w0[:, None] * Pb[t[0]] + w1[:, None] * Pb[t[1]] + w2[:, None] * Pb[t[2]]
        if alpha is not None:
            u = w0[:, None] * uv[t[0]] + w1[:, None] * uv[t[1]] + w2[:, None] * uv[t[2]]
            px = np.clip((u[:, 0] % 1.0 * alpha.shape[1]).astype(int), 0, alpha.shape[1] - 1)
            py = np.clip((u[:, 1] % 1.0 * alpha.shape[0]).astype(int), 0, alpha.shape[0] - 1)
            q = q[alpha[py, px] > 0.5]
        pts.append(q)
B = np.concatenate(pts)
B = np.column_stack([np.abs(B[:, 0]), B[:, 1]])
# Its lower and upper edge in columns 0.5 mm wide.
step = 0.0005
col = np.floor(B[:, 0] / step).astype(int)
cols = np.unique(col)
xs = (cols + 0.5) * step
lo = np.array([B[col == c, 1].min() for c in cols]); hi = np.array([B[col == c, 1].max() for c in cols])
mid = 0.5 * (lo + hi); th = hi - lo
at = lambda x, v: float(np.interp(x, xs, v))
third = (xs > ex0 + (ex1 - ex0) / 3) & (xs < ex1 - (ex1 - ex0) / 3)
R = dict(
    file=os.path.basename(path), H=H,
    opening_height_H=eh / H, opening_width_H=(ex1 - ex0) / H, opening_top_share=(etop - chin) / H,
    gap_H=float(lo[third].mean() - etop) / H, gap_openings=float(lo[third].mean() - etop) / eh,
    centre_inner_H=(at(ex0, mid) - etop) / H, centre_middle_H=(at(0.5 * (ex0 + ex1), mid) - etop) / H, centre_outer_H=(at(ex1, mid) - etop) / H,
    thick_H=float(th.max()) / H, long_H=float(xs.max() - xs.min()) / H,
    inner_beyond_H=(ex0 - float(xs.min())) / H, outer_beyond_H=(float(xs.max()) - ex1) / H,
)
R['centre_middle_openings'] = R['centre_middle_H'] * H / eh
print(f"{R['file']}: H {H * 100:.1f} cm; the eye's opening {R['opening_height_H']:.3f} H high, {R['opening_width_H']:.3f} H wide, its top {R['opening_top_share']:.3f} of the way up")
print(f"  gap {R['gap_H']:.4f} H = {R['gap_openings']:.2f} openings; centre above the opening's top: inner {R['centre_inner_H']:.4f}, middle {R['centre_middle_H']:.4f} ({R['centre_middle_openings']:.2f} openings), outer {R['centre_outer_H']:.4f} H")
print(f"  thick {R['thick_H']:.4f} H ({th.max() * 1000:.1f} mm), long {R['long_H']:.3f} H; beyond the opening: in {R['inner_beyond_H']:+.3f}, out {R['outer_beyond_H']:+.3f} H")
if '--json' in sys.argv:
    json.dump(R, open(sys.argv[sys.argv.index('--json') + 1], 'w'), indent=1)
