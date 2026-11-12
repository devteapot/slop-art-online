"""The body of a character file, measured the same way on the reference and on ours.

    python3 -I living/tools/characters/reference/body.py FILE.glb [--params NAME.params.json [--person] | --line LINE.json]
        [--all] [--top Y | --head 0.2564] [--floor 0.085] [--json OUT] [--mask OUT.png]

The figure stands in its rest pose with the arms out (glTF coordinates: Y up, the face toward
-Z). Ours is first posed as the client poses it, by the proportions of the recipe in
`--params` (a per-person file's `recipe`) or of a person's line (`--line`, or `--params` with
`--person`): the bones' scales that make a woman's shoulders, a child's legs or a heavy build
(person_check.shaped, the client's `bone_scale` repeated). Every length is then given as a
share of the figure's height and of H, the head's height from chin to top, so the figure's own
size drops out.

- by default the skin is cut (`…_SKIN`: the body under the clothes; on ours the unclothed form,
  `person.py --body`); `--all` cuts every mesh but the hair's: the silhouette one sees;
- **heights:** the crotch (the highest cut the legs are still two pieces), the hips' widest, the
  waist's narrowest, the bust's foremost, the armpit, the shoulders' top over the joint, the
  chin; the joints' heights;
- **widths and depths** of the torso's own cut at the hips, waist and bust and under the arms,
  with how far the bust stands before the waist's front and the seat behind the waist's back;
- **the shoulders:** between the joints; across the arms as they would hang (the joints' span
  and one upper arm's thickness); the slope from the neck's side down to the top over the joint;
- **limbs:** the arm from shoulder joint to wrist and to the fingertip, the leg from hip joint to
  the floor, the inseam, the thicknesses of upper arm, forearm, wrist, thigh, knee, calf and
  ankle;
- **hands:** wrist to fingertip, the palm (wrist to the middle finger's first joint), the
  middle finger, the palm's breadth and thickness;
- `--mask OUT.png` writes the front and the side silhouette as two filled shapes (the figure's
  height 1000 px), to lay one figure over another.
"""
import sys, os, json, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
from geo import section
import person_check

FLAGS = ('--params', '--line', '--top', '--head', '--json', '--mask', '--floor')
argv = sys.argv[1:]
opt = {f: argv[argv.index(f) + 1] for f in FLAGS if f in argv}
rest = [a for i, a in enumerate(argv) if not a.startswith('--') and (i == 0 or argv[i - 1] not in FLAGS)]
path = rest[0]
every = '--all' in argv
props = {}
if '--params' in opt:
    doc = json.load(open(opt['--params']))
    props = (doc['person'] if '--person' in argv else doc['recipe'])['proportions']
if '--line' in opt:
    props = json.load(open(opt['--line']))['proportions']

def take(want):
    more = {}
    P = person_check.shaped(path, want, props, more)
    return P, more['triangles'], more['joints']

near = lambda mesh: not mesh.startswith('Far')
FP, FI, J = take(lambda mesh, mat: near(mesh) and 'Face_00_SKIN' in mat)
SP, SI, _ = take(lambda mesh, mat: near(mesh) and '_SKIN' in mat and '_01_SKIN' not in mat)
AP, AI, _ = take(lambda mesh, mat: near(mesh) and '_HAIR' not in mat and '_01_SKIN' not in mat)
P, I = (AP, AI) if every else (SP, SI)

side = 1.0 if J['J_Bip_L_UpperArm'][0] > 0 else -1.0  # which way the figure's left lies
jl = lambda n: J['J_Bip_L_' + n]
chin = float(FP[np.abs(FP[:, 0]) < 0.02][:, 1].min())
top = float(opt['--top']) if '--top' in opt else float(FP[:, 1].max())
if '--head' in opt:
    # Ours with hair on has no scalp under it: the head's height is the generator's own (0.2564 m
    # in a file, types.json `head_height_m`), as the person's proportions scale it.
    top = chin + float(opt['--head']) * props.get('head', 1.0)
H = top - chin
# The floor: the lowest point of everything drawn; a figure with no feet drawn (ours unclothed)
# gives its own (`--floor`, metres under the foot's joint as posed).
floor = float(jl('Foot')[1] - float(opt['--floor']) * props.get('feet', 1.0)) if '--floor' in opt else float(AP[:, 1].min())
height = top - floor
hips_z = float(J['J_Bip_C_Hips'][2])
xj = abs(float(jl('UpperArm')[0]))  # the shoulder joint, off the midline
xe = abs(float(jl('LowerArm')[0]))  # the elbow
head_w = 0.0
for f in np.linspace(0.25, 0.95, 40):
    s = section(FP, FI, 1, chin + f * H).reshape(-1, 3)
    if len(s):
        head_w = max(head_w, float(np.ptp(s[:, 0])))


def pieces(P, I, axis, value):
    """A cut's segments joined into pieces: a list of point arrays."""
    s = section(P, I, axis, value)
    if not len(s):
        return []
    pts = s.reshape(-1, 3)
    key = np.round(np.delete(pts, axis, 1) * 2000).astype(np.int64)
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
    return [s[roots == r].reshape(-1, 3) for r in np.unique(roots)]


def torso(y, P=P, I=I):
    """The torso's own part of a horizontal cut: the piece across the midline, kept between the
    shoulder joints where it runs out into the arms. (width, front z, back z, the piece's full
    width), or None."""
    best = None
    for q in pieces(P, I, 1, y):
        if q[:, 0].min() < -0.005 and q[:, 0].max() > 0.005:
            size = np.ptp(q[:, 0]) * np.ptp(q[:, 2])
            if best is None or size > best[0]:
                best = (size, q)
    if best is None:
        return None
    q = best[1]
    full = float(np.ptp(q[:, 0]))
    arms = float(np.abs(q[:, 0]).max()) > xj + 0.4 * (xe - xj)  # the cut runs out along an arm: the torso is then what lies between the joints
    inner = q[np.abs(q[:, 0]) <= xj] if arms else q
    if not len(inner):
        return None
    return (2 * xj if arms else full), float(inner[:, 2].min()), float(inner[:, 2].max()), full


# The torso from the knee up to the chin, a cut every 0.4% of the height.
ys = np.arange(floor + 0.30 * height, chin, 0.004 * height)
cuts = [(y, torso(y, SP, SI)) for y in ys]   # the skin: where the body's own landmarks are
have = [(y, c) for y, c in cuts if c]
knee = float(jl('LowerLeg')[1])
crotch = min(y for y, c in have if y > knee)
armpit = None
for y, c in have:
    if y > crotch + 0.15 * height and c[3] > 2 * (xj + 0.4 * (xe - xj)):
        break
    armpit = y
body = [(y, c) for y, c in have if crotch <= y <= armpit]
arr = np.array([(y, c[0], c[1], c[2]) for y, c in body])
sel = (arr[:, 0] > crotch + 0.07 * height) & (arr[:, 0] < armpit - 0.04 * height)
waist = arr[sel][np.argmin(arr[sel][:, 1])]
low = arr[arr[:, 0] <= waist[0]]
hip = low[np.argmax(low[:, 1])]
seat = low[np.argmax(low[:, 3])]
# The bust: the foremost point between the waist and the shoulders (the cuts above the armpit
# still give the front between the joints).
up = np.array([(y, c[0], c[1], c[2]) for y, c in have if waist[0] < y < armpit + 0.05 * height])
bust = up[np.argmin(up[:, 2])]
under = arr[np.argmin(np.abs(arr[:, 0] - (armpit - 0.012 * height)))]

# The shoulder's top: over planes x = const from the neck's side to the joint, the highest skin
# below the chin.
def top_at(x):
    s = section(SP, SI, 0, side * x).reshape(-1, 3)
    s = s[(s[:, 1] < chin - 0.03 * H) & (s[:, 1] > armpit)]
    return float(s[:, 1].max()) if len(s) else None

neck_cut = torso(chin - 0.10 * H, SP, SI)
neck_w = neck_cut[3] if neck_cut else 0.0
x0 = neck_w / 2 + 0.25 * (xj - neck_w / 2)
profile = [(x, top_at(x)) for x in np.linspace(neck_w / 2 * 1.05, xj, 14)]
profile = [(float(x), y) for x, y in profile if y is not None]
y0, y1 = top_at(x0), top_at(xj)
slope = float(np.degrees(np.arctan2(y0 - y1, xj - x0)))


def arm_cut(x):
    """The arm's thickness on a plane x = const: (up, forward)."""
    s = section(SP, SI, 0, x).reshape(-1, 3)
    c = jl('UpperArm')
    s = s[(np.abs(s[:, 1] - c[1]) < 0.12 * height / 1.6) & (np.abs(s[:, 2] - c[2]) < 0.12 * height / 1.6)]
    return (float(np.ptp(s[:, 1])), float(np.ptp(s[:, 2]))) if len(s) else (0.0, 0.0)


def leg_cut(y):
    """One leg's (width, depth) on a horizontal cut."""
    best = (0.0, 0.0)
    for q in pieces(SP, SI, 1, y):
        if (q[:, 0] * side).min() > -0.004 and np.ptp(q[:, 0]) * np.ptp(q[:, 2]) > best[0] * best[1]:
            best = (float(np.ptp(q[:, 0])), float(np.ptp(q[:, 2])))
    return best


sh, el, wr = jl('UpperArm'), jl('LowerArm'), jl('Hand')
left = SP[SP[:, 0] * side > abs(wr[0])]
tip = float(np.abs(left[:, 0]).max())
hand_len = tip - abs(float(wr[0]))
palm_x = side * (abs(float(wr[0])) + 0.38 * hand_len)
ps = section(SP, SI, 0, palm_x).reshape(-1, 3)
mid1 = J.get('J_Bip_L_Middle1')
ankle_y = float(jl('Foot')[1])
calf = max((leg_cut(y) for y in np.linspace(ankle_y + 0.25 * (knee - ankle_y), knee - 0.1 * (knee - ankle_y), 12)), key=lambda c: c[0])
ank = min((leg_cut(y) for y in np.linspace(ankle_y + 0.02 * height, ankle_y + 0.3 * (knee - ankle_y), 8)), key=lambda c: c[0] if c[0] else 9)
m = dict(
    file=os.path.basename(path), what='every mesh but hair' if every else 'skin', height=height, H=H, heads=height / H, chin=chin - floor, head_width=head_w,
    heights=dict(crotch=crotch - floor, hip=hip[0] - floor, seat=seat[0] - floor, waist=waist[0] - floor, bust=bust[0] - floor, armpit=armpit - floor, shoulder_top=y1 - floor, chin=chin - floor,
                 hip_joint=float(jl('UpperLeg')[1]) - floor, knee_joint=knee - floor, ankle_joint=ankle_y - floor, shoulder_joint=float(sh[1]) - floor, neck_joint=float(J['J_Bip_C_Neck'][1]) - floor),
    widths=dict(hip=hip[1], waist=waist[1], under_arms=under[1], bust=bust[1], shoulder_joints=2 * xj, shoulders_hanging=2 * xj + arm_cut(side * (xj + 0.25 * (abs(el[0]) - xj)))[0], hip_joints=2 * abs(float(jl('UpperLeg')[0])), neck=neck_w),
    depths=dict(hip=hip[3] - hip[2], waist=waist[3] - waist[2], bust=bust[3] - bust[2], under_arms=under[3] - under[2], bust_before_waist=waist[2] - bust[2], seat_behind_waist=seat[3] - waist[3],
                waist_middle_behind_hips_joint=0.5 * (waist[2] + waist[3]) - hips_z, bust_front_before_hips_joint=hips_z - bust[2], seat_back_behind_hips_joint=seat[3] - hips_z),
    shoulders=dict(slope_degrees=slope, top_below_chin=chin - y1, neck_side_top_below_chin=chin - y0, profile=[(x, chin - y) for x, y in profile]),
    limbs=dict(arm=abs(float(wr[0])) - xj, upper_arm=abs(float(el[0])) - xj, forearm=abs(float(wr[0] - el[0])), arm_to_tip=tip - xj, leg=float(jl('UpperLeg')[1]) - floor, inseam=crotch - floor,
               thigh_bone=float(jl('UpperLeg')[1]) - knee, shin_bone=knee - ankle_y, torso=float(J['J_Bip_C_Neck'][1]) - crotch,
               upper_arm_thick=arm_cut(side * (xj + 0.5 * (abs(el[0]) - xj))), forearm_thick=arm_cut(side * (abs(el[0]) + 0.3 * abs(wr[0] - el[0]))), wrist_thick=arm_cut(side * (abs(wr[0]) - 0.02 * hand_len)),
               thigh=leg_cut(crotch - 0.03 * height), knee=leg_cut(knee), calf=calf, ankle=ank),
    hands=dict(length=hand_len, palm=(abs(float(mid1[0])) - abs(float(wr[0]))) if mid1 is not None else None, middle_finger=(tip - abs(float(mid1[0]))) if mid1 is not None else None,
               breadth=float(np.ptp(ps[:, 2])) if len(ps) else None, thickness=float(np.ptp(ps[:, 1])) if len(ps) else None),
    levels=[dict(at=(y - floor) / height, width=c[0] / height, front=(hips_z - c[1]) / height, back=(c[2] - hips_z) / height) for y, c in ((y, torso(y)) for y in ys) if c and y <= armpit + 0.06 * height],
)
if '--json' in opt:
    json.dump(m, open(opt['--json'], 'w'), indent=1)

def sh_(v):
    return f"{v * 100:5.1f} cm = {v / height * 100:4.1f}% of the height, {v / H:.2f} H"

print(f"{m['file']}: {m['what']}; height {height:.3f} m = {height / H:.2f} heads (H {H:.3f} m), the head {head_w / H:.2f} H wide")
for group in ('heights', 'widths', 'depths', 'limbs', 'hands'):
    print(f"  {group}:")
    for k, v in m[group].items():
        if v is None:
            continue
        if isinstance(v, tuple):
            print(f"    {k:28s} {v[0] / height * 100:4.1f}% by {v[1] / height * 100:4.1f}% of the height ({v[0] * 100:.1f} by {v[1] * 100:.1f} cm)")
        else:
            print(f"    {k:28s} {sh_(v)}")
print(f"  shoulders: the top slopes {slope:.1f} degrees from the neck's side to over the joint; over the joint it is {(chin - y1) / H:.2f} H below the chin, by the neck {(chin - y0) / H:.2f} H")
print(f"  ratios: shoulder joints / hips {2 * xj / hip[1]:.2f}; waist / hips {waist[1] / hip[1]:.2f}; waist / under the arms {waist[1] / under[1]:.2f}; shoulders hanging / the head's width {m['widths']['shoulders_hanging'] / head_w:.2f}; "
      f"leg / height {m['limbs']['leg'] / height:.3f}; inseam / height {(crotch - floor) / height:.3f}; arm / height {m['limbs']['arm'] / height:.3f}; hand / H {hand_len / H:.2f}")

if '--mask' in opt:
    from PIL import Image, ImageDraw
    S = 1000.0 / height
    W_, H_ = 1100, 1080
    for name, ax, sgn in (('front', 0, 1.0), ('side', 2, 1.0)):
        im = Image.new('L', (W_, H_), 0)
        d = ImageDraw.Draw(im)
        for label, (QP, QI) in (('all', (AP, AI)),) if every else (('skin', (SP, SI)),):
            c0 = 0.0 if ax == 0 else hips_z
            u = W_ / 2 + (QP[:, ax] - c0) * S * sgn
            v = H_ - 40 - (QP[:, 1] - floor) * S
            for t in QI:
                d.polygon([(u[t[0]], v[t[0]]), (u[t[1]], v[t[1]]), (u[t[2]], v[t[2]])], fill=255)
        im.save(opt['--mask'].replace('.png', f'-{name}.png'))
