"""A character file's left hand, measured the same way on the reference and on ours.

    python3 living/tools/characters/reference/hand.py FILE.glb [--params NAME.params.json [--person]] [--head 0.2564] [--json OUT] [--mask OUT.png]

The hand at rest (the arm out along X, the palm down), ours posed by its recipe's proportions as
the client poses it. Lengths are given in millimetres, as a share of the hand's own length (wrist
joint to the middle finger's tip) and of H, the head's height, so hands of two figures compare.

- **the hand:** its length; the palm (wrist to the middle finger's first joint); its breadth
  across the knuckles (the index's to the little finger's first joint, with their own
  thickness) and its thickness there; the wrist's breadth and thickness;
- **each finger:** its three bones' lengths (first joint to second, second to third, third to the
  tip, the tip being the furthest of the last bone's own vertices along it), its thickness at
  each bone (twice the middle distance of that bone's own vertices from its line), and how far
  it splays from the middle finger at rest (degrees, in the palm's plane);
- **the thumb:** where its first joint sits (along the hand from the wrist, and across it from
  the middle finger's line), its length, its thickness, how far it splays from the hand's line
  and how far it drops below the palm's plane;
- `--mask OUT.png` writes the hand from above and from the front edge as filled shapes, the
  hand's length 600 px, to lay one over another.

`--head` gives the head's height for a file whose scalp is under hair (ours: 0.2564).
"""
import sys, os, json, math, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cloth_check
from merge_primitives import read_accessor, read_glb

FLAGS = ('--params', '--head', '--json', '--mask')
argv = sys.argv[1:]
opt = {f: argv[argv.index(f) + 1] for f in FLAGS if f in argv}
path = [a for i, a in enumerate(argv) if not a.startswith('--') and (i == 0 or argv[i - 1] not in FLAGS)][0]
props = {}
if '--params' in opt:
    doc = json.load(open(opt['--params']))
    props = (doc['person'] if '--person' in argv else doc['recipe'])['proportions']

sk = cloth_check.Skeleton(path, props)
mats, J = sk.pose({})
j, binary = read_glb(path)
P, W, T = [], [], []
count = 0
for n in j['nodes']:
    if 'mesh' not in n or n.get('name', '').startswith('Far'):
        continue
    skin = j['skins'][n.get('skin', 0)]
    names = [j['nodes'][k].get('name') for k in skin['joints']]
    ibm = np.array(read_accessor(j, binary, skin['inverseBindMatrices'])[0]).reshape(-1, 4, 4).transpose(0, 2, 1)
    m = np.array([mats.get(nm, np.eye(4)) @ ibm[k] for k, nm in enumerate(names)])
    for p in j['meshes'][n['mesh']]['primitives']:
        mat = j['materials'][p['material']]['name']
        if '_SKIN' not in mat or 'Face' in mat:
            continue
        get = lambda a: np.array(read_accessor(j, binary, p['attributes'][a])[0])
        pos, jt, wt = get('POSITION').reshape(-1, 3), get('JOINTS_0').reshape(-1, 4).astype(int), get('WEIGHTS_0').reshape(-1, 4)
        ph = np.concatenate([pos, np.ones((len(pos), 1))], axis=1)
        out = np.zeros((len(pos), 3))
        for k in range(4):
            out += wt[:, k:k + 1] * np.einsum('nij,nj->ni', m[jt[:, k]], ph)[:, :3]
        P.append(out)
        W.append([names[a] for a in jt[np.arange(len(jt)), wt.argmax(axis=1)]])
        T.append(np.array(read_accessor(j, binary, p['indices'])[0]).reshape(-1, 3) + count)
        count += len(out)
P = np.concatenate(P)
main = np.array([w for ws in W for w in ws])
T = np.concatenate(T)
side = 1.0 if J['J_Bip_L_Hand'][0] > 0 else -1.0
wrist = J['J_Bip_L_Hand']
bone = lambda f, k: J[f'J_Bip_L_{f}{k}']
FING = ('Index', 'Middle', 'Ring', 'Little')
# The hand's own frame: along (wrist to the middle finger's first joint), across (toward the
# thumb's side: the character's forward, -Z in the file), up.
along = bone('Middle', 1) - wrist
along = along / np.linalg.norm(along)
up = np.array([0.0, 1.0, 0.0])
across = np.cross(up, along) * side
across = across / np.linalg.norm(across)
if np.dot(across, bone('Index', 1) - bone('Little', 1)) < 0:
    across = -across
up = np.cross(along, across)
up = up if up[1] > 0 else -up


def chain(f):
    pts = [bone(f, 1), bone(f, 2), bone(f, 3)]
    own = P[main == f'J_Bip_L_{f}3']
    d = pts[2] - pts[1]
    d = d / np.linalg.norm(d)
    tip = pts[2] + d * float(((own - pts[2]) @ d).max()) if len(own) else pts[2]
    return pts + [tip]


def thick(f, k, a, b):
    own = P[main == f'J_Bip_L_{f}{k}']
    if len(own) < 4:
        return None
    d = (b - a) / np.linalg.norm(b - a)
    t = (own - a) @ d
    sel = own[(t > 0.25 * np.linalg.norm(b - a)) & (t < 0.75 * np.linalg.norm(b - a))]
    sel = sel if len(sel) >= 3 else own
    r = np.linalg.norm((sel - a) - np.outer((sel - a) @ d, d), axis=1)
    return 2 * float(np.median(r))


mid = chain('Middle')
L = float(np.linalg.norm(mid[3] - wrist @ np.ones(1) * 1 if False else mid[3] - wrist))
L = float((mid[3] - wrist) @ along)
out = dict(file=os.path.basename(path), length=L, palm=float((mid[0] - wrist) @ along), fingers={})
for f in FING + ('Thumb',):
    c = chain(f)
    seg = [float(np.linalg.norm(c[i + 1] - c[i])) for i in range(3)]
    d = c[1] - c[0]
    splay = math.degrees(math.atan2(float(d @ across), float(d @ along)))
    drop = math.degrees(math.atan2(-float(d @ up), float(np.hypot(d @ along, d @ across))))
    out['fingers'][f] = dict(bones=seg, length=sum(seg), thick=[thick(f, k + 1, c[k], c[k + 1]) for k in range(3)], splay=splay, drop=drop,
                             root_along=float((c[0] - wrist) @ along), root_across=float((c[0] - wrist) @ across), root_up=float((c[0] - wrist) @ up))
hand = P[np.isin(main, ['J_Bip_L_Hand'])]
rel = hand - wrist
t = rel @ along
kn = rel[(t > 0.80 * out['palm']) & (t < 1.0 * out['palm'])]
wr = rel[(t > -0.01) & (t < 0.12 * out['palm'])]
ft = out['fingers']
out['breadth'] = float(np.ptp(kn @ across)) if len(kn) else None
out['knuckle_span'] = float(abs(ft['Index']['root_across'] - ft['Little']['root_across'])) + 0.5 * ((ft['Index']['thick'][0] or 0) + (ft['Little']['thick'][0] or 0))
out['thickness'] = float(np.ptp(kn @ up)) if len(kn) else None
out['wrist'] = (float(np.ptp(wr @ across)), float(np.ptp(wr @ up))) if len(wr) else None
chin = None
H = float(opt['--head']) * props.get('head', 1.0) if '--head' in opt else None
if H is None:
    fp = []
    for n in j['nodes']:
        if 'mesh' in n and not n.get('name', '').startswith('Far'):
            for p in j['meshes'][n['mesh']]['primitives']:
                if 'Face_00_SKIN' in j['materials'][p['material']]['name']:
                    fp.append(np.array(read_accessor(j, binary, p['attributes']['POSITION'])[0]).reshape(-1, 3))
    fp = np.concatenate(fp)
    H = float(fp[:, 1].max() - fp[np.abs(fp[:, 0]) < 0.02][:, 1].min())
out['H'] = H
if '--json' in opt:
    json.dump(out, open(opt['--json'], 'w'), indent=1)
mm = lambda v: f"{v * 1000:5.1f} mm = {v / L:.2f} of the hand, {v / H:.2f} H"
print(f"{out['file']}: hand {L * 1000:.1f} mm = {L / H:.2f} H; palm {mm(out['palm'])}")
print(f"  across the knuckles {mm(out['breadth'])} (joints and their fingers: {out['knuckle_span'] * 1000:.1f} mm); thick there {mm(out['thickness'])}; wrist {out['wrist'][0] * 1000:.1f} by {out['wrist'][1] * 1000:.1f} mm")
for f, v in ft.items():
    th = ', '.join('-' if x is None else f"{x * 1000:.1f}" for x in v['thick'])
    print(f"  {f:6s} {v['length'] * 1000:5.1f} mm = {v['length'] / L:.2f} of the hand; bones {', '.join(f'{x * 1000:.1f}' for x in v['bones'])}; thick {th}; splay {v['splay']:+5.1f} deg, drop {v['drop']:+5.1f}; root {v['root_along'] / L:.2f} along, {v['root_across'] / L:+.2f} across, {v['root_up'] * 1000:+.1f} mm up")

if '--mask' in opt:
    from PIL import Image, ImageDraw
    S = 600.0 / L
    sel = np.isin(main, ['J_Bip_L_Hand'] + [f'J_Bip_L_{f}{k}' for f in FING + ('Thumb',) for k in (1, 2, 3)])
    tri = T[sel[T].all(axis=1)]
    R = P - wrist
    for name, a2 in (('top', across), ('edge', up)):
        im = Image.new('L', (760, 520 if name == 'top' else 300), 0)
        d = ImageDraw.Draw(im)
        u = 60 + (R @ along) * S
        v = im.height / 2 - (R @ a2) * S
        for t3 in tri:
            d.polygon([(u[t3[0]], v[t3[0]]), (u[t3[1]], v[t3[1]]), (u[t3[2]], v[t3[2]])], fill=255)
        im.save(opt['--mask'].replace('.png', f'-{name}.png'))
