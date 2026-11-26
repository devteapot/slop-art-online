# Track B2 base human: one quad cage, built from parameters, subdivided, skinned to our J_Bip skeleton.
# Run:  blender -b --python docs/char-bakeoff/B2/base.py -- OUT_DIR [--tex DIR]
# Every morph is the same cage built again with other parameters (positions(P) - positions(BASE)),
# so topology, weights and UVs are shared by every body.
import bpy, bmesh, sys, os, json, struct, math
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = os.path.abspath(ARGS[0]) if ARGS else os.path.join(HERE, 'out')
os.makedirs(OUT, exist_ok=True)
SKEL = os.path.join(HERE, '..', '..', 'char-live-2', 'final', 'own-cora-live.glb')

def nrm(v):
    v = np.asarray(v, float); return v / (np.linalg.norm(v) + 1e-12)
def lerp(a, b, t): return np.asarray(a, float) * (1 - t) + np.asarray(b, float) * t
def sstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a))); return t * t * (3 - 2 * t)
def srgb(h):
    h = h.lstrip('#'); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c] + [1.0]

# ---------------------------------------------------------------- parameters
BASE = dict(sh_w=0.0, chest=1.0, chest_d=1.0, bust=1.0, waist=1.0, hip=1.0, belly=0.0, neck=1.0, arm=1.0,
            leg=1.0, hand=1.0, foot=1.0, head=1.0, jaw=1.0, chin=0.0, cheek=0.0, brow=0.0, stoop=0.0,
            chin_n=1.5, butt=1.0)
MORPHS = {
    'Sex_Male':   dict(sh_w=0.032, chest=1.12, chest_d=1.03, bust=0.0, waist=1.19, hip=0.93, neck=1.40, arm=1.20,
                       leg=1.09, hand=1.13, foot=1.10, jaw=1.17, chin=0.008, brow=0.004, cheek=-0.002, head=1.0, butt=0.9),
    'Age_Child':  dict(head=1.30, sh_w=-0.012, chest=0.95, bust=0.0, waist=1.14, hip=0.90, belly=0.008, neck=0.92,
                       arm=1.04, leg=1.05, jaw=0.95, chin=-0.006, cheek=0.004, hand=1.05, foot=1.04, butt=0.9),
    'Age_Elder':  dict(stoop=0.030, bust=0.45, waist=1.13, belly=0.012, neck=0.95, arm=0.92, leg=0.93,
                       cheek=-0.004, chin=0.003, jaw=1.02, sh_w=-0.008, butt=0.92),
    'Build_Heavy': dict(waist=1.32, hip=1.15, chest=1.12, chest_d=1.10, belly=0.030, arm=1.22, leg=1.18, neck=1.16,
                        cheek=0.006, jaw=1.08, butt=1.1),
    'Build_Slim': dict(waist=0.92, hip=0.95, chest=0.96, arm=0.90, leg=0.92, neck=0.94, cheek=-0.003),
    'Face_Round': dict(cheek=0.006, chin=-0.005, jaw=1.07),
    'Face_Long':  dict(chin=0.008, jaw=0.95, cheek=-0.002),
    'Jaw_Square': dict(jaw=1.15, chin_n=1.95),
}
# name: armature scale (height), morph mix, colours
CHARS = {
    'woman': dict(scale=0.9265, mix={}, skin='#f2c9a8', hair='#a8482a', top='#e9dfcc', shorts='#3d4756', shoes='#6b4a36'),
    'man':   dict(scale=1.0, mix={'Sex_Male': 1.0, 'Jaw_Square': 0.5, 'Face_Long': 0.5}, skin='#e3b08c', hair='#2f2a28', top='#d8d2c2', shorts='#35404a', shoes='#4a3628'),
    'elder': dict(scale=0.955, mix={'Sex_Male': 0.75, 'Age_Elder': 1.0, 'Face_Long': 0.6}, skin='#e6bfa2', hair='#c9c9c6', top='#ddd6c6', shorts='#4a4a52', shoes='#4f3d30'),
    'child': dict(scale=0.70, mix={'Age_Child': 1.0, 'Face_Round': 0.7}, skin='#f5cfb0', hair='#c98a3a', top='#e6e0cf', shorts='#4b5a48', shoes='#70503a'),
}

# skeleton joints of the bind figure (world, metres; the armature of docs/char-live-2, scale 0.9265)
HJ = np.array([0, -0.015, 1.453])
SJ = np.array([.143, .006, 1.332]); EJ = np.array([.208, .006, 1.122]); WJ = np.array([.272, -.015, .895])
HIP = np.array([.082, .006, .908]); KJ = np.array([.099, -.006, .474]); AJ = np.array([.119, .006, .099])
FING = {  # J1, J2, J3, tip length
    'Index':  ([.292, -.031, .820], [.295, -.036, .781], [.296, -.039, .758], .022),
    'Middle': ([.282, -.015, .817], [.283, -.018, .774], [.284, -.019, .747], .024),
    'Ring':   ([.272, .001, .817], [.271, .001, .777], [.271, .000, .754], .022),
    'Little': ([.259, .013, .821], [.258, .014, .784], [.257, .015, .763], .019),
}
FN = ['Index', 'Middle', 'Ring', 'Little']
THUMB = ([.279, -.036, .891], [.284, -.056, .849], [.288, -.069, .823], .024)
NT = 16      # torso and head ring size
A0 = 7       # torso ring of the armhole's lower row
# torso rings: z, rx, front, back, cy, group, dz at the back
TORSO = [
    (0.850, .158, .088, .100, .004, 'hip', 0), (0.915, .163, .092, .106, .004, 'hip', 0),
    (0.985, .146, .086, .092, .002, 'waist', 0), (1.055, .116, .076, .074, .000, 'waist', 0),
    (1.125, .120, .084, .076, -.002, 'waist', 0), (1.180, .126, .092, .082, -.002, 'chest', 0),
    (1.232, .130, .100, .088, .000, 'chest', 0), (1.268, .130, .100, .092, .000, 'chest', 0),
    (1.298, .127, .094, .094, .002, 'sh', 0), (1.327, .123, .080, .090, .004, 'sh', 0),
    (1.352, .110, .056, .070, .006, 'sh', 0), (1.384, .045, .042, .050, .000, 'nb', .006),
    (1.404, .0305, .031, .034, -.006, 'neck', .008), (1.424, .0295, .030, .033, -.010, 'neck', .012),
]
NTOR = len(TORSO)   # 14: torso rings k0..k13, head rings follow
# head rings, head-local: z front, z back, half width, front, back, exponent, group
HEAD = [
    (-0.015, -0.002, .033, .050, .036, 2.0, 'under'), (-0.024, 0.008, .039, .083, .062, 1.5, 'chin'),
    (-0.011, 0.034, .057, .091, .084, 1.75, 'jaw'), (0.011, 0.060, .0695, .096, .095, 2.0, 'mouth'),
    (0.036, 0.086, .0765, .097, .101, 2.2, 'nose'), (0.062, 0.106, .0795, .097, .103, 2.3, 'eye'),
    (0.090, 0.126, .0800, .098, .103, 2.2, 'brow'), (0.122, 0.148, .077, .094, .099, 2.05, 'cr'),
    (0.152, 0.168, .070, .082, .088, 2.0, 'cr'), (0.178, 0.184, .054, .060, .066, 2.0, 'cr'),
    (0.194, 0.196, .030, .032, .036, 2.0, 'cr'),
]
HS = 1.06; YS = 0.010
LEGPHI = [306, 342, 18, 54, 90, 126, 162, 198, 234, 270]
ARMALPHA = [-72, -36, 0, 36, 72, 108, 144, 180, 216, 252]
LEG = [  # z, rx, ry, cy offset, group
    (.775, .080, .086, .004, 'thigh'), (.680, .071, .076, .002, 'thigh'), (.570, .060, .064, .0, 'thigh'),
    (.515, .053, .057, -.003, 'knee'), (.474, .049, .054, -.007, 'knee'), (.435, .046, .050, -.001, 'knee'),
    (.360, .053, .058, .010, 'calf'), (.250, .040, .042, .005, 'calf'), (.160, .032, .034, .0, 'ankle'),
    (.115, .030, .033, .0, 'ankle'),
]
FOOT = [  # centre s, centre z, axis (ds, dz), lateral radius
    (-.002, .047, (.046, .041), .037), (.085, .034, (.012, .030), .045), (.150, .024, (.004, .021), .043),
    (.185, .018, (.0, .012), .027),
]
NLEG = len(LEG) + len(FOOT)

def sup(theta, rx, f, b, cy, n):
    e = 2.0 / n; s, c = math.sin(theta), math.cos(theta)
    x = rx * math.copysign(abs(s) ** e, s)
    y = cy - f * abs(c) ** e if c >= 0 else cy + b * abs(c) ** e
    return x, y

def positions(P):
    """key -> world position, for the left side and the middle; the right side is mirrored after."""
    V = {}
    # ---- torso
    for k, (z, rx, f, b, cy, g, dzb) in enumerate(TORSO):
        if g == 'hip': rx *= P['hip']; f *= 0.5 + 0.5 * P['hip']; b *= P['butt'] * (0.5 + 0.5 * P['hip'])
        if g == 'waist':
            m = P['waist'] if k in (3, 4) else 0.5 + 0.5 * P['waist']
            rx *= m; f = f * (0.4 + 0.6 * m) + P['belly'] * (1.0 if k in (2, 3) else 0.6); b *= 0.5 + 0.5 * m
        if g == 'chest': rx *= P['chest']; f *= P['chest_d']; b *= P['chest_d']; f += P['belly'] * 0.25
        if g == 'sh': rx = rx * P['chest'] + P['sh_w']; f *= P['chest_d']; b *= P['chest_d']
        if g in ('nb', 'neck'): rx *= P['neck']; f *= P['neck']; b *= P['neck']
        st = 0.0
        if g in ('chest', 'sh'): st = -P['stoop'] * (0.35 if g == 'chest' else 0.6); b += P['stoop'] * (0.5 if g == 'chest' else 0.9); f -= P['stoop'] * 0.3
        if g == 'nb': st = -P['stoop'] * 0.3
        for j in range(NT):
            th = j * 2 * math.pi / NT
            x, y = sup(th, rx, f, b, cy, 2.5)
            zz = z + dzb * (1 - math.cos(th)) / 2
            if k in (5, 6, 7) and j in (1, 2, 3, 13, 14, 15):   # the bust
                jj = j if j < 8 else NT - j
                y -= P['bust'] * {1: .018, 2: .025, 3: .006}[jj] * {5: .35, 6: 1.0, 7: .5}[k]
                if k == 5: zz -= 0.006 * P['bust']
            V[('T', k, j)] = np.array([x, y + st, zz])
    V[('C',)] = np.array([0, .008, .803])
    # ---- head (rings NTOR .. NTOR+len(HEAD)-1, then the pole)
    hs = HS * P['head']
    st = 0.0
    for i, (zf, zb, w, f, b, n, g) in enumerate(HEAD):
        if g in ('chin', 'jaw'): w *= P['jaw']
        if g == 'chin': zf -= P['chin']; n = P['chin_n']
        if g == 'under': zf -= P['chin'] * 0.7
        if g in ('jaw', 'mouth'): w += P['cheek'] * (1.0 if g == 'jaw' else 0.8)
        if g == 'mouth': w *= 0.6 + 0.4 * P['jaw']
        if g == 'brow': f += P['brow']
        for j in range(NT):
            th = j * 2 * math.pi / NT
            x, y = sup(th, w, f, b, 0.0, n)
            z = zf * (1 + math.cos(th)) / 2 + zb * (1 - math.cos(th)) / 2
            V[('T', NTOR + i, j)] = HJ + hs * np.array([x, y + YS, z]) + np.array([0, st, 0])
    V[('HP',)] = HJ + hs * np.array([0, YS + .002, .202]) + np.array([0, st, 0])
    # ---- left arm: rings 1..11 (ring 0 is the armhole in the torso)
    au = nrm(EJ - SJ); al = nrm(WJ - EJ)
    idx1 = np.array(FING['Index'][0]); lit1 = np.array(FING['Little'][0]); mid1 = np.array(FING['Middle'][0])
    hd = nrm(mid1 - WJ)
    hu = lit1 - idx1; hu = nrm(hu - hu.dot(hd) * hd)
    hn = nrm(np.cross(hd, hu))
    if hn[0] < 0: hn = -hn
    X = np.array([1.0, 0, 0])
    arm_spec = [  # centre, tangent, radius n, radius u, twist toward the hand's frame
        (np.array([.165 + P['sh_w'], .006, 1.291]), nrm([.915, 0, -.404]), .051, .050, 0.0, nrm([.404, 0, .915])),
        (SJ + au * .11 + [P['sh_w'] * .4, 0, 0], au, .041, .041, 0.0, None), (SJ + au * .165, au, .037, .037, .1, None),
        (EJ - au * .032, au, .032, .032, .2, None), (EJ, nrm(au + al), .031, .031, .3, None),
        (EJ + al * .032, al, .033, .032, .45, None), (EJ + al * .09, al, .031, .033, .65, None),
        (EJ + al * .175, al, .021, .026, .9, None),
    ]
    for r, (c, t, rn, ru, tw, nfix) in enumerate(arm_spec, start=1):
        n = nfix if nfix is not None else lerp(X, hn, tw)
        n = nrm(n - n.dot(t) * t); u = nrm(np.cross(n, t))
        for i, a in enumerate(ARMALPHA):
            a = math.radians(a)
            V[('A', r, i)] = c + (rn * P['arm'] / .936) * math.cos(a) * n + (ru * P['arm'] / .936) * math.sin(a) * u
    # the hand: wrist ring 9, mid palm 10, web ring 11, in the hand's frame (hd down, hu index->little, hn back)
    hsz = P['hand']
    def hp(d, s, n): return WJ + hsz * (hd * d + hu * s + hn * n)
    ks = [(np.array(FING[f][0]) - WJ).dot(hu) for f in FN]; kd = [(np.array(FING[f][0]) - WJ).dot(hd) for f in FN]
    for r, d, s0, s1, h in ((9, 0.0, -.023, .023, .0165), (10, .040, -.037, .033, .0150)):
        for i in range(5):
            s = s0 + (s1 - s0) * i / 4
            hh = h * (0.8 if i in (0, 4) else 1.0)
            V[('A', r, i)] = hp(d, s, hh); V[('A', r, 9 - i)] = hp(d, s, -hh)
    ws = [ks[0] - .0090, (ks[0] + ks[1]) / 2, (ks[1] + ks[2]) / 2, (ks[2] + ks[3]) / 2, ks[3] + .0078]
    wd = [kd[0] + .006, (kd[0] + kd[1]) / 2 + .011, (kd[1] + kd[2]) / 2 + .012, (kd[2] + kd[3]) / 2 + .011, kd[3] + .005]
    for i in range(5):
        V[('A', 11, i)] = hp(wd[i], ws[i], .0090); V[('A', 11, 9 - i)] = hp(wd[i], ws[i], -.0090)
    def tube(tag, joints, tip, radii, first):
        j1, j2, j3 = [WJ + hsz * (np.array(j) - WJ) for j in joints]
        tipp = j3 + nrm(j3 - j2) * tip * hsz
        cs = [first(j1, j2), j2, j3, tipp]; ts = [nrm(j2 - j1), nrm(j3 - j1), nrm(tipp - j2), nrm(tipp - j3)]
        for fr, (c, t, rr) in enumerate(zip(cs, ts, radii), start=1):
            if tag[0] == 'F':
                uu = nrm(hu - hu.dot(t) * t); nn = nrm(np.cross(t, uu));
                if nn.dot(hn) < 0: nn = -nn
                cor = [(-1, 1), (1, 1), (1, -1), (-1, -1)]
            else:
                uu = nrm(hd - hd.dot(t) * t); nn = hn - hn.dot(t) * t; nn = nrm(nn - nn.dot(uu) * uu)
                cor = [(-1, 1), (1, 1), (1, -1), (-1, -1)]
            h = rr * hsz / 0.89
            for q, (su, sn) in enumerate(cor):
                V[tag + (fr, q)] = c + uu * su * h + nn * sn * h
        V[tag + (5, 0)] = tipp + ts[3] * radii[3] * hsz * 0.9      # the tip's pole
    for fi, f in enumerate(FN):
        j1, j2, j3, tip = FING[f]
        rad = {'Index': .0073, 'Middle': .0076, 'Ring': .0072, 'Little': .0064}[f]
        tube(('F', fi), (j1, j2, j3), tip, [rad, rad * .95, rad * .88, rad * .70], lambda a, b: a + nrm(b - a) * .024 * hsz)
    tube(('TH',), THUMB[:3], THUMB[3], [.0118, .0100, .0090, .0072], lambda a, b: a + (b - a) * .80)
    # ---- left leg: rings 1..NLEG, then the toe pole
    def bone_c(z):
        if z >= KJ[2]: t = (HIP[2] - z) / (HIP[2] - KJ[2]); return lerp(HIP, KJ, t)
        t = (KJ[2] - z) / (KJ[2] - AJ[2]); return lerp(KJ, AJ, t)
    for r, (z, rx, ry, cyo, g) in enumerate(LEG, start=1):
        c = bone_c(z)
        m = P['leg'] * (0.5 + 0.5 * P['hip'] if r == 1 else 1.0) / .936
        cx = .090 if r == 1 else c[0]
        if g == 'ankle': m = (0.5 + 0.5 * P['leg']) / .936
        for i, ph in enumerate(LEGPHI):
            ph = math.radians(ph)
            x = cx + rx * m * math.sin(ph)
            if r <= 2: x = max(x, .010 if r == 1 else .014)
            V[('L', r, i)] = np.array([x, c[1] + cyo - ry * m * math.cos(ph), z])
    ff = nrm([.141, -.99, 0]); fp = np.array([.99, .141, 0]); fs = P['foot']
    for q, (s, zc, (ads, adz), rl) in enumerate(FOOT):
        r = len(LEG) + 1 + q
        for i, ph in enumerate(LEGPHI):
            ph = math.radians(ph)
            ss = (s + ads * math.cos(ph)) * fs; lat = rl * fs * math.sin(ph) / .936
            V[('L', r, i)] = np.array([AJ[0], AJ[1], 0]) + ff * ss + fp * lat + [0, 0, max(0.0, zc + adz * math.cos(ph))]
    V[('LP',)] = np.array([AJ[0], AJ[1], 0]) + ff * .203 * fs + [0, 0, .016]
    # ---- ear (left): a small closed lobe, four rings of four and a tip
    ec = HJ + hs * np.array([.0775, YS + .014, .052]) + [0, st, 0]
    for r, (out, back, hh, ww) in enumerate([(-.006, 0, .013, .007), (.003, .003, .017, .009), (.007, .007, .015, .008)]):
        for q, (sy, sz) in enumerate([(-1, 1), (1, 1), (1, -1), (-1, -1)]):
            V[('E', r, q)] = ec + hs * np.array([out, back + sy * ww, sz * hh + (0.004 if sz > 0 else 0)])
    return V

def mkey(k):
    """the mirrored vertex's key"""
    if k[0] == 'T': return ('T', k[1], (NT - k[2]) % NT)
    if k[0] in ('C', 'HP'): return k
    return ('R' + k[0],) + k[1:]

def arm_key(r, i):
    if r == 0:
        a = A0
        return [('T', a + 2, 3), ('T', a + 3, 3), ('T', a + 3, 4), ('T', a + 3, 5), ('T', a + 2, 5), ('T', a + 1, 5),
                ('T', a, 5), ('T', a, 4), ('T', a, 3), ('T', a + 1, 3)][i]
    return ('A', r, i)
def leg_key(r, i):
    if r == 0: return ('T', 0, i) if i < 9 else ('C',)
    return ('L', r, i)

def topology():
    """faces as key tuples with a material tag; the right side by mirroring."""
    F = []
    nk = NTOR + len(HEAD)
    hole = {(k, j) for k in range(A0, A0 + 3) for j in (3, 4)}
    hole |= {(k, NT - 1 - j) for (k, j) in hole}
    for k in range(nk - 1):
        for j in range(NT):
            if (k, j) in hole: continue
            if k < 3: m = 'shorts'
            elif k < 11: m = 'top'
            else: m = 'skin'
            hk = k - NTOR
            if 1 <= hk <= 6 and (j in (13, 14, 15, 0, 1, 2)): m = 'face'
            F.append(([('T', k, j), ('T', k, (j + 1) % NT), ('T', k + 1, (j + 1) % NT), ('T', k + 1, j)], m))
    for j in range(NT):
        F.append(([('T', nk - 1, j), ('T', nk - 1, (j + 1) % NT), ('HP',)], 'skin'))
    L = []
    for r in range(11):                                  # arm and palm
        for i in range(10):
            if r == 9 and i == 9: continue               # the thumb's opening
            L.append(([arm_key(r, i), arm_key(r, (i + 1) % 10), arm_key(r + 1, (i + 1) % 10), arm_key(r + 1, i)], 'skin'))
    def tube_faces(tag, base):
        ring = lambda fr: base if fr == 0 else [tag + (fr, q) for q in range(4)]
        for fr in range(4):
            a, b = ring(fr), ring(fr + 1)
            for q in range(4):
                L.append(([a[q], a[(q + 1) % 4], b[(q + 1) % 4], b[q]], 'skin'))
        b = ring(4)
        for q in range(4): L.append(([b[q], b[(q + 1) % 4], tag + (5, 0)], 'skin'))
    for f in range(4):
        tube_faces(('F', f), [('A', 11, f), ('A', 11, f + 1), ('A', 11, 8 - f), ('A', 11, 9 - f)])
    tube_faces(('TH',), [('A', 9, 0), ('A', 10, 0), ('A', 10, 9), ('A', 9, 9)])
    for r in range(NLEG):
        m = 'shorts' if r < 2 else ('shoes' if r >= len(LEG) - 1 else 'skin')
        for i in range(10):
            L.append(([leg_key(r, i), leg_key(r, (i + 1) % 10), leg_key(r + 1, (i + 1) % 10), leg_key(r + 1, i)], m))
    for i in range(10): L.append(([('L', NLEG, i), ('L', NLEG, (i + 1) % 10), ('LP',)], 'shoes'))
    for r in range(2):                                   # the ear
        for q in range(4): L.append(([('E', r, q), ('E', r, (q + 1) % 4), ('E', r + 1, (q + 1) % 4), ('E', r + 1, q)], 'skin'))
    L.append(([('E', 2, q) for q in range(4)], 'skin')); L.append(([('E', 0, q) for q in range(4)][::-1], 'skin'))
    F += L
    F += [([mkey(k) for k in ks][::-1], m) for ks, m in L]
    return F

def full(P):
    V = positions(P)
    for k, p in list(V.items()):
        mk = mkey(k)
        if mk not in V: V[mk] = p * np.array([-1, 1, 1])
    return V

MATS = ['skin', 'top', 'shorts', 'shoes', 'face']
MATNAME = {'skin': 'M00_000_00_Body_00_SKIN', 'top': 'B2_UnderTop_CLOTH', 'shorts': 'B2_UnderShorts_CLOTH',
           'shoes': 'B2_Shoes_CLOTH', 'face': 'B2_tmp_face', 'hair': 'M00_000_Hair_00_HAIR',
           'decal': 'M00_000_00_FaceTint_00_FACE'}

def material(name, col, image=None):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes['Principled BSDF']
    b.inputs['Roughness'].default_value = 1.0
    if 'Specular IOR Level' in b.inputs: b.inputs['Specular IOR Level'].default_value = 0.0
    if image is not None:
        t = nt.nodes.new('ShaderNodeTexImage'); t.image = image
        nt.links.new(t.outputs['Color'], b.inputs['Base Color']); nt.links.new(t.outputs['Alpha'], b.inputs['Alpha'])
        try: m.surface_render_method = 'BLENDED'
        except Exception: m.blend_method = 'BLEND'
    else:
        mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'; mix.blend_type = 'MULTIPLY'
        mix.inputs[0].default_value = 1.0; mix.inputs[6].default_value = col
        ca = nt.nodes.new('ShaderNodeVertexColor'); ca.layer_name = 'Color'
        nt.links.new(ca.outputs['Color'], mix.inputs[7]); nt.links.new(mix.outputs[2], b.inputs['Base Color'])
    m['b2_col'] = list(col)
    return m

def build_cage(arm):
    V0 = full(BASE); keys = list(V0.keys()); index = {k: i for i, k in enumerate(keys)}
    F = topology()
    used = {k for ks, m in F for k in ks}
    keys = [k for k in keys if k in used]; index = {k: i for i, k in enumerate(keys)}
    me = bpy.data.meshes.new('BaseCage')
    me.from_pydata([V0[k].tolist() for k in keys], [], [[index[k] for k in ks] for ks, m in F])
    for i, (ks, m) in enumerate(F): me.polygons[i].material_index = MATS.index(m)
    me.update()
    bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.recalc_face_normals(bm, faces=bm.faces); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new('BaseCage', me); bpy.context.scene.collection.objects.link(ob)
    for p in me.polygons: p.use_smooth = True
    return ob, keys, index

def weights(ob, arm, keys, index):
    main = [b for b in arm.data.bones if b.name.startswith('J_Bip_') and not any(f in b.name for f in FN + ['Thumb'])]
    # The imported bones' tails point anywhere (glTF has joints, not segments), and bone heat reads segments.
    # So the heat is solved on a stand-in rig whose bones run joint to joint, and the groups go to the real one.
    child = {'J_Bip_C_Hips': 'J_Bip_C_Spine', 'J_Bip_C_Spine': 'J_Bip_C_Chest', 'J_Bip_C_Chest': 'J_Bip_C_UpperChest',
             'J_Bip_C_UpperChest': 'J_Bip_C_Neck', 'J_Bip_C_Neck': 'J_Bip_C_Head'}
    for S in 'LR':
        for a, b in (('Shoulder', 'UpperArm'), ('UpperArm', 'LowerArm'), ('LowerArm', 'Hand'), ('Hand', 'Middle1'),
                     ('UpperLeg', 'LowerLeg'), ('LowerLeg', 'Foot'), ('Foot', 'ToeBase')):
            child['J_Bip_%s_%s' % (S, a)] = 'J_Bip_%s_%s' % (S, b)
    W = arm.matrix_world
    ad = bpy.data.armatures.new('HeatRig'); rig = bpy.data.objects.new('HeatRig', ad)
    bpy.context.scene.collection.objects.link(rig)
    bpy.ops.object.select_all(action='DESELECT'); bpy.context.view_layer.objects.active = rig; rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for b in main:
        eb = ad.edit_bones.new(b.name); eb.head = W @ b.head_local
        if b.name in child: eb.tail = W @ arm.data.bones[child[b.name]].head_local
        elif 'Head' in b.name: eb.tail = eb.head + Vector((0, 0, .13))
        else: eb.tail = eb.head + Vector((0, -.07, 0))
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT'); ob.select_set(True); rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    ob.parent = arm; ob.matrix_parent_inverse = arm.matrix_world.inverted()
    for m in ob.modifiers:
        if m.type == 'ARMATURE': m.object = arm
    bpy.data.objects.remove(rig, do_unlink=True)
    got = sum(1 for v in ob.data.vertices if v.groups)
    print('B2 heat weights on', got, 'of', len(ob.data.vertices))
    def setw(k, w):
        i = index[k]
        for g in ob.vertex_groups: g.remove([i])
        for bn, x in w.items():
            g = ob.vertex_groups.get(bn) or ob.vertex_groups.new(name=bn)
            g.add([i], x, 'REPLACE')
    for side, pre, S in (('L', '', 'L'), ('R', 'R', 'R')):
        K = lambda *k: ((pre + k[0],) + tuple(k[1:]))
        B = lambda n: 'J_Bip_%s_%s' % (S, n)
        for i in range(10):
            setw(K('A', 9, i), {B('Hand'): .5, B('LowerArm'): .5}); setw(K('A', 10, i), {B('Hand'): 1.0})
        for i in range(5):
            w = {B('Hand'): .6}
            for f in (i - 1, i):
                if 0 <= f < 4: w[B(FN[f] + '1')] = .4 if i in (0, 4) else .2
            setw(K('A', 11, i), w); setw(K('A', 11, 9 - i), w)
        for fi, f in enumerate(FN):
            for q in range(4):
                setw(K('F', fi, 1, q), {B(f + '1'): 1.0}); setw(K('F', fi, 2, q), {B(f + '1'): .5, B(f + '2'): .5})
                setw(K('F', fi, 3, q), {B(f + '2'): .5, B(f + '3'): .5}); setw(K('F', fi, 4, q), {B(f + '3'): 1.0})
            setw(K('F', fi, 5, 0), {B(f + '3'): 1.0})
        for q in range(4):
            setw(K('TH', 1, q), {B('Thumb1'): .65, B('Thumb2'): .35}); setw(K('TH', 2, q), {B('Thumb2'): .5, B('Thumb3'): .5})
            setw(K('TH', 3, q), {B('Thumb3'): 1.0}); setw(K('TH', 4, q), {B('Thumb3'): 1.0})
        setw(K('TH', 5, 0), {B('Thumb3'): 1.0})
        for r in range(3):
            for q in range(4): setw(K('E', r, q), {'J_Bip_C_Head': 1.0})
    for k in keys:
        if k[0] == 'T' and k[1] >= NTOR: setw(k, {'J_Bip_C_Head': 1.0})
        if k[0] == 'T' and k[1] == NTOR - 1: setw(k, {'J_Bip_C_Head': .5, 'J_Bip_C_Neck': .5})
        if k[0] == 'T' and k[1] == NTOR - 2: setw(k, {'J_Bip_C_Neck': 1.0})
        if k[0] == 'T' and k[1] == NTOR - 3: setw(k, {'J_Bip_C_Neck': .5, 'J_Bip_C_UpperChest': .5})
    setw(('HP',), {'J_Bip_C_Head': 1.0})

def detail(co, P=None):
    """small forms added after subdivision, on the basis' coordinates (head-local): the nose, the lips' line"""
    d = np.zeros_like(co)
    l = (co - HJ) / HS
    x, y, z = l[:, 0], l[:, 1] - YS, l[:, 2]
    front = y < -0.06
    up = np.clip((z - 0.026) / 0.040, 0, 1); dn = np.clip((0.036 - z) / 0.012, 0, 1)
    g = np.where(z > 0.034, np.exp(-((z - 0.034) / 0.022) ** 2), np.exp(-((z - 0.034) / 0.0065) ** 2))
    nose = 0.0125 * np.exp(-(x / 0.0085) ** 2) * g
    lip = 0.0022 * np.exp(-(x / 0.016) ** 2) * (np.exp(-((z - 0.006) / 0.005) ** 2) + 0.8 * np.exp(-((z + 0.004) / 0.005) ** 2))
    sock = -0.0030 * np.exp(-(((np.abs(x) - 0.034) / 0.020) ** 2)) * np.exp(-((z - 0.060) / 0.016) ** 2)
    chin = 0.0030 * np.exp(-(x / 0.016) ** 2) * np.exp(-((z + 0.018) / 0.010) ** 2)
    d[:, 1] = np.where(front, -(nose + lip + sock + chin) * HS, 0)
    return d

def bake(cage, arm, name):
    """the cage subdivided twice, with every key evaluated: -> a plain mesh object with the same keys"""
    vl = bpy.context.view_layer
    kb = cage.data.shape_keys.key_blocks
    def ev():
        vl.update(); dg = bpy.context.evaluated_depsgraph_get()
        e = cage.evaluated_get(dg); me = e.to_mesh(); a = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get('co', a); e.to_mesh_clear(); return a.reshape(-1, 3).copy()
    for k in kb: k.value = 0
    base = ev(); cols = {}
    for k in kb[1:]:
        k.value = 1.0; cols[k.name] = ev(); k.value = 0.0
    vl.update(); dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(cage.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    me.name = name
    ob = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(ob)
    for g in cage.vertex_groups: ob.vertex_groups.new(name=g.name)
    d = detail(base)
    base2 = base + d; base2[:, 2] = np.maximum(base2[:, 2], 0.0)
    me.vertices.foreach_set('co', base2.ravel())
    if me.shape_keys:
        ob.shape_key_clear()
    return ob, base2, {n: c + d for n, c in cols.items()}

def add_keys(ob, base, cols):
    ob.shape_key_add(name='Basis', from_mix=False)
    for n, c in cols.items():
        k = ob.shape_key_add(name=n, from_mix=False); k.data.foreach_set('co', np.asarray(c, float).ravel())

def skin_to(ob, arm):
    ob.parent = arm; ob.matrix_parent_inverse = arm.matrix_world.inverted()
    m = ob.modifiers.new('Armature', 'ARMATURE'); m.object = arm

def body_tint(co):
    """painted shade in the vertex colours: warm joints and fingertips, soft dark under the jaw, in the armpits
    and the crotch, a waistband line, the shoes' soles. The material's colour stays the parameter."""
    t = np.ones((len(co), 3))
    def blob(c, r, col, k=1.0, mirror=True):
        nonlocal t
        for sg in ((1, -1) if mirror else (1,)):
            d = np.linalg.norm(co - np.array(c) * [sg, 1, 1], axis=1)
            g = (np.exp(-(d / r) ** 2) * k)[:, None]
            t = t * (1 - g * (1 - np.array(col)))
    warm = (1.0, .84, .80); dark = (.86, .74, .70)
    blob((KJ[0], KJ[1] - .05, KJ[2]), .040, warm, .8); blob((EJ[0], EJ[1] + .032, EJ[2]), .030, warm, .8)
    blob((.186, .006, 1.335), .040, warm, .35)
    for f in FN:
        j1, j2, j3, tip = FING[f]
        blob(j1, .011, warm, .7); blob(np.array(j3) + [0, 0, -tip], .010, warm, .8)
    blob(np.array(THUMB[2]) + [0, -.008, -.02], .011, warm, .8)
    blob((0, -.035, 1.428), .034, dark, .9, False); blob((.132, .006, 1.262), .038, dark, .7)
    blob((0, .0, .805), .05, (.72, .72, .74), .9, False)
    band = np.exp(-((co[:, 2] - 1.055) / .006) ** 2)[:, None]; t = t * (1 - band * .16)
    hem = np.exp(-((co[:, 2] - .680) / .005) ** 2)[:, None]; t = t * (1 - hem * .14)
    sole = (co[:, 2] < .013)[:, None]; t = np.where(sole, t * .55, t)
    return np.clip(t, 0, 1)

def white(me, shade=None):
    ca = me.color_attributes.get('Color') or me.color_attributes.new('Color', 'BYTE_COLOR', 'CORNER')
    n = len(me.loops)
    if shade is None: a = np.ones((n, 4))
    else:
        li = np.empty(n, int); me.loops.foreach_get('vertex_index', li)
        s = np.asarray(shade)[li]
        a = np.concatenate([s, np.ones((n, 1))], 1) if s.ndim == 2 else np.stack([s, s, s, np.ones(n)], 1)
    ca.data.foreach_set('color', a.ravel()); me.color_attributes.active_color = ca
    try: me.color_attributes.render_color_index = list(me.color_attributes).index(ca)
    except Exception: pass

def decal_from(body, base, cols, arm):
    """the face's front as its own thin layer, for the painted eyes, brows and mouth (unshaded in the game)"""
    me = body.data
    fi = MATS.index('face')
    polys = [p for p in me.polygons if p.material_index == fi]
    vs = sorted({v for p in polys for v in p.vertices}); re = {v: i for i, v in enumerate(vs)}
    nrmls = np.array([me.vertices[v].normal[:] for v in vs])
    off = nrmls * 0.0007
    co = base[vs] + off
    dm = bpy.data.meshes.new('FaceLayer')
    dm.from_pydata(co.tolist(), [], [[re[v] for v in p.vertices] for p in polys]); dm.update()
    for p in dm.polygons: p.use_smooth = True
    uv = dm.uv_layers.new(name='UVMap')
    l = (base[vs] - HJ) / HS
    for lp in dm.loops:
        x, z = l[lp.vertex_index][0], l[lp.vertex_index][2]
        uv.data[lp.index].uv = ((x + 0.09) / 0.18, (z + 0.05) / 0.18)
    ob = bpy.data.objects.new('FaceLayer', dm); bpy.context.scene.collection.objects.link(ob)
    g = ob.vertex_groups.new(name='J_Bip_C_Head'); g.add(list(range(len(vs))), 1.0, 'REPLACE')
    white(dm)
    for p in polys: p.material_index = 0
    return ob, co, {n: c[vs] + off for n, c in cols.items()}

def glb_patch(path, colours):
    """write each material's own colour as its base colour factor; unlit-safe roughness"""
    d = open(path, 'rb').read()
    jl = struct.unpack_from('<I', d, 12)[0]; js = json.loads(d[20:20 + jl]); rest = d[20 + jl:]
    for m in js.get('materials', []):
        p = m.setdefault('pbrMetallicRoughness', {})
        p['metallicFactor'] = 0.0; p['roughnessFactor'] = 1.0
        if m['name'] in colours and 'baseColorTexture' not in p: p['baseColorFactor'] = [round(c, 5) for c in colours[m['name']]]
    out = json.dumps(js, separators=(',', ':')).encode(); out += b' ' * ((4 - len(out) % 4) % 4)
    body = struct.pack('<II', len(out), 0x4E4F534A) + out + rest
    open(path, 'wb').write(b'glTF' + struct.pack('<II', 2, 12 + len(body)) + body)
    tris = 0
    return js

def main():
    import hair as hairlib
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SKEL)
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    for o in list(bpy.data.objects):
        if o.type != 'ARMATURE': bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.materials): bpy.data.materials.remove(m)
    for m in list(bpy.data.meshes):
        if m.users == 0: bpy.data.meshes.remove(m)
    arm.name = 'Armature'
    cage, keys, index = build_cage(arm)
    weights(cage, arm, keys, index)
    cage.shape_key_add(name='Basis', from_mix=False)
    V0 = full(BASE)
    for name, over in MORPHS.items():
        P = dict(BASE); P.update(over); V = full(P)
        k = cage.shape_key_add(name=name, from_mix=False)
        k.data.foreach_set('co', np.array([V[key] for key in keys]).ravel())
    sub = cage.modifiers.new('Subdivision', 'SUBSURF'); sub.levels = 2; sub.render_levels = 2
    # modifier order: the armature first would deform the cage; for the bake, switch it off
    for m in cage.modifiers:
        if m.type == 'ARMATURE': m.show_viewport = False
    body, base, cols = bake(cage, arm, 'Body')
    tex_dir = ARGS[ARGS.index('--tex') + 1] if '--tex' in ARGS else OUT
    decal, dbase, dcols = decal_from(body, base, cols, arm)
    white(body.data, body_tint(base))
    mats = {}
    c0 = CHARS['woman']
    for t in MATS[:4]:
        mats[t] = material(MATNAME[t], srgb(c0['skin' if t == 'skin' else t]))
        body.data.materials.append(mats[t])
    while len(body.data.materials) < len(MATS): body.data.materials.append(mats['skin'])
    body.data.update()
    skin_to(body, arm)
    hair_objs = {}
    report = {}
    cage.hide_render = True
    for m in cage.modifiers:
        if m.type == 'ARMATURE': m.show_viewport = True
    cage_coll = bpy.data.collections.new('Master cage'); bpy.context.scene.collection.children.link(cage_coll)
    bpy.context.scene.collection.objects.unlink(cage); cage_coll.objects.link(cage)
    # ---- one file per character: the base with its mix baked in; plus the base with every morph
    for name, ch in list(CHARS.items()) + [('base', dict(CHARS['woman'], morphs=True))]:
        mix = ch['mix']
        def mixed(b, cs):
            p = b.copy()
            for n, w in mix.items(): p += w * (cs[n] - b)
            return p
        bco = mixed(base, cols); dco = mixed(dbase, dcols)
        body.shape_key_clear() if body.data.shape_keys else None
        decal.shape_key_clear() if decal.data.shape_keys else None
        body.data.vertices.foreach_set('co', bco.ravel()); body.data.update()
        decal.data.vertices.foreach_set('co', dco.ravel()); decal.data.update()
        if ch.get('morphs'):
            add_keys(body, base, cols); add_keys(decal, dbase, dcols)
        for t in MATS[:4]:
            col = srgb(ch['skin' if t == 'skin' else t]); mats[t]['b2_col'] = col
            mats[t].node_tree.nodes['Mix'].inputs[6].default_value = col
        tex = os.path.join(tex_dir, 'face-%s.png' % (name if name != 'base' else 'woman'))
        for o in [decal]:
            o.data.materials.clear()
            img = bpy.data.images.load(tex, check_existing=True)
            dm = bpy.data.materials.get('FACE_' + os.path.basename(tex)) or material('FACE_' + os.path.basename(tex), (1, 1, 1, 1), img)
            o.data.materials.append(dm)
        skin_to(decal, arm) if decal.parent is None else None
        # head scale of this mix, for the hair
        hscale = 1.0 + sum(w * (MORPHS[n].get('head', 1.0) - 1.0) for n, w in mix.items())
        for o in [o for o in bpy.data.objects if o.name.startswith('Hair')]: bpy.data.objects.remove(o, do_unlink=True)
        hob = hairlib.build(name if name != 'base' else 'woman', HJ, HS * hscale, YS, material, srgb(ch['hair']), MATNAME['hair'])
        skin_to(hob, arm)
        arm.scale = (ch['scale'],) * 3
        dname = decal.data.materials[0].name
        decal.data.materials[0].name = MATNAME['decal']
        bpy.context.view_layer.update()
        path = os.path.join(OUT, 'b2-%s.glb' % name)
        bpy.ops.object.select_all(action='DESELECT')
        for o in (arm, body, decal, hob): o.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.export_scene.gltf(filepath=path, use_selection=True, export_format='GLB', export_animations=True,
                                  export_animation_mode='ACTIONS', export_vertex_color='ACTIVE', export_all_vertex_colors=False,
                                  export_morph=bool(ch.get('morphs')), export_morph_normal=False, export_skins=True,
                                  export_yup=True, export_apply=False, export_optimize_animation_size=True,
                                  export_image_format='AUTO')
        cols_out = {MATNAME[t]: mats[t]['b2_col'] for t in MATS[:4]}; cols_out[MATNAME['hair']] = srgb(ch['hair'])
        js = glb_patch(path, cols_out)
        tri = lambda o: sum(len(p.vertices) - 2 for p in o.data.polygons)
        report[name] = dict(file=os.path.basename(path), triangles={o.name: tri(o) for o in (body, decal, hob)},
                            total_triangles=sum(tri(o) for o in (body, decal, hob)),
                            materials=[m['name'] for m in js['materials']], bones=len(js['skins'][0]['joints']),
                            clips=[a['name'] for a in js.get('animations', [])], scale=ch['scale'], mix=mix,
                            morph_targets=list(cols) if ch.get('morphs') else [],
                            textures=[os.path.basename(tex) + ' 1024x1024 RGBA'], bytes=os.path.getsize(path))
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'b2-%s.blend' % name), copy=True, compress=True)
        decal.data.materials[0].name = dname
        arm.scale = (CHARS['woman']['scale'],) * 3
        bpy.context.view_layer.update()
    json.dump(report, open(os.path.join(OUT, 'report.json'), 'w'), indent=1)
    print('B2 done', json.dumps({k: v['total_triangles'] for k, v in report.items()}))

if __name__ == '__main__':
    main()
