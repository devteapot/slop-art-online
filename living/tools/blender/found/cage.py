"""Body rings and topology derived from our bake-off B2 cage."""

import math

import numpy as np


def nrm(v):
    v = np.asarray(v, float)
    return v / (np.linalg.norm(v) + 1e-12)


def lerp(a, b, t):
    return np.asarray(a, float) * (1 - t) + np.asarray(b, float) * t


def srgb(h):
    h = h.lstrip("#")
    c = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    return [((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c] + [1.0]


# ---------------------------------------------------------------- parameters
BASE = {
    "sh_w": 0.0,
    "chest": 1.0,
    "chest_d": 1.0,
    "bust": 1.0,
    "waist": 1.0,
    "hip": 1.0,
    "belly": 0.0,
    "neck": 1.0,
    "arm": 1.0,
    "leg": 1.0,
    "hand": 1.0,
    "foot": 1.0,
    "head": 1.0,
    "jaw": 1.0,
    "chin": 0.0,
    "cheek": 0.0,
    "brow": 0.0,
    "stoop": 0.0,
    "chin_n": 1.5,
    "butt": 1.0,
}
MORPHS = {
    "Sex_Male": {
        "sh_w": 0.042,
        "chest": 1.27,
        "chest_d": 1.18,
        "bust": 0.0,
        "waist": 1.19,
        "hip": 0.93,
        "neck": 1.40,
        "arm": 1.29,
        "leg": 1.09,
        "hand": 1.13,
        "foot": 1.10,
        "jaw": 1.17,
        "chin": 0.008,
        "brow": 0.004,
        "cheek": -0.002,
        "head": 1.0,
        "butt": 0.9,
    },
    "Age_Child": {
        "child": True,
        "head": 1.21,
        "sh_w": -0.012,
        "chest": 0.95,
        "bust": 0.0,
        "waist": 1.14,
        "hip": 0.90,
        "belly": 0.008,
        "neck": 0.92,
        "arm": 1.04,
        "leg": 1.05,
        "jaw": 0.95,
        "chin": -0.006,
        "cheek": 0.004,
        "hand": 1.05,
        "foot": 1.04,
        "butt": 0.9,
    },
    "Age_Elder": {
        "stoop": 0.030,
        "bust": 0.45,
        "waist": 1.13,
        "belly": 0.012,
        "neck": 0.95,
        "arm": 0.92,
        "leg": 0.93,
        "cheek": -0.004,
        "chin": 0.003,
        "jaw": 1.02,
        "sh_w": -0.008,
        "butt": 0.92,
    },
    "Build_Heavy": {
        "waist": 1.32,
        "hip": 1.15,
        "chest": 1.12,
        "chest_d": 1.10,
        "belly": 0.030,
        "arm": 1.14,
        "leg": 1.16,
        "neck": 1.16,
        "cheek": 0.006,
        "jaw": 1.08,
        "butt": 1.1,
    },
    "Build_Slim": {
        "waist": 0.92,
        "hip": 0.95,
        "chest": 0.96,
        "arm": 0.90,
        "leg": 0.92,
        "neck": 0.94,
        "cheek": -0.003,
    },
    "Face_Round": {"cheek": 0.006, "chin": -0.005, "jaw": 1.07},
    "Face_Long": {"chin": 0.008, "jaw": 0.95, "cheek": -0.002},
    "Jaw_Square": {"jaw": 1.15, "chin_n": 1.95},
}
FN = ["Index", "Middle", "Ring", "Little"]
NT = 16  # torso and head ring size
A0 = 7  # torso ring of the armhole's lower row
# torso rings: z, rx, front, back, cy, group, dz at the back
TORSO = [
    (0.850, 0.158, 0.088, 0.110, 0.006, "hip", 0),
    (0.915, 0.163, 0.092, 0.116, 0.008, "hip", 0),
    (0.985, 0.146, 0.086, 0.092, 0.004, "waist", 0),
    (1.055, 0.116, 0.078, 0.066, -0.002, "waist", 0),
    (1.125, 0.120, 0.085, 0.073, -0.004, "waist", 0),
    (1.180, 0.126, 0.092, 0.082, -0.004, "chest", 0),
    (1.232, 0.144, 0.100, 0.092, -0.002, "chest", 0),
    (1.268, 0.146, 0.100, 0.096, 0.000, "chest", 0),
    (1.298, 0.144, 0.094, 0.097, 0.002, "sh", 0),
    (1.327, 0.149, 0.080, 0.092, 0.004, "sh", 0),
    (1.352, 0.135, 0.056, 0.070, 0.006, "sh", 0),
    (1.384, 0.045, 0.042, 0.050, 0.000, "nb", 0.006),
    (1.404, 0.0305, 0.031, 0.034, -0.006, "neck", 0.008),
    (1.424, 0.0295, 0.030, 0.033, -0.010, "neck", 0.012),
]
NTOR = len(TORSO)  # 14: torso rings k0..k13, head rings follow
# head rings, head-local: z front, z back, half width, front, back, exponent, group
HEAD = [
    (-0.015, -0.002, 0.033, 0.050, 0.036, 2.0, "under"),
    (-0.024, 0.008, 0.039, 0.083, 0.062, 1.5, "chin"),
    (-0.011, 0.034, 0.057, 0.091, 0.084, 1.75, "jaw"),
    (0.011, 0.060, 0.0695, 0.096, 0.095, 2.0, "mouth"),
    (0.036, 0.086, 0.0765, 0.097, 0.101, 2.2, "nose"),
    (0.062, 0.106, 0.0795, 0.097, 0.103, 2.3, "eye"),
    (0.090, 0.126, 0.0800, 0.098, 0.103, 2.2, "brow"),
    (0.122, 0.148, 0.077, 0.094, 0.099, 2.05, "cr"),
    (0.152, 0.168, 0.070, 0.082, 0.088, 2.0, "cr"),
    (0.178, 0.184, 0.054, 0.060, 0.066, 2.0, "cr"),
    (0.194, 0.196, 0.030, 0.032, 0.036, 2.0, "cr"),
]
HS = 1.06
YS = 0.010
LEGPHI = [306, 342, 18, 54, 90, 126, 162, 198, 234, 270]
ARMALPHA = [-72, -36, 0, 36, 72, 108, 144, 180, 216, 252]
LEG = [  # z, rx, ry, cy offset, group
    (0.775, 0.080, 0.088, 0.004, "thigh"),
    (0.680, 0.071, 0.080, -0.003, "thigh"),
    (0.570, 0.060, 0.066, -0.003, "thigh"),
    (0.515, 0.053, 0.058, -0.004, "knee"),
    (0.474, 0.049, 0.054, -0.008, "knee"),
    (0.435, 0.046, 0.050, 0.001, "knee"),
    (0.360, 0.059, 0.063, 0.013, "calf"),
    (0.250, 0.040, 0.043, 0.008, "calf"),
    (0.160, 0.032, 0.034, 0.002, "ankle"),
    (0.115, 0.030, 0.033, 0.0, "ankle"),
]
FOOT = [  # centre s, centre z, axis (ds, dz), lateral radius
    (-0.002, 0.047, (0.046, 0.041), 0.037),
    (0.085, 0.034, (0.012, 0.030), 0.045),
    (0.150, 0.024, (0.004, 0.021), 0.043),
    (0.185, 0.018, (0.0, 0.012), 0.027),
]
NLEG = len(LEG) + len(FOOT)


def sup(theta, rx, f, b, cy, n):
    e = 2.0 / n
    s, c = math.sin(theta), math.cos(theta)
    x = rx * math.copysign(abs(s) ** e, s)
    y = cy - f * abs(c) ** e if c >= 0 else cy + b * abs(c) ** e
    return x, y


def positions(P, joints):
    """key -> world position, for the left side and the middle; the right side is mirrored after."""
    SJ, EJ, WJ, HIP, KJ, AJ = [
        joints["J_Bip_L_" + n] for n in ("UpperArm", "LowerArm", "Hand", "UpperLeg", "LowerLeg", "Foot")
    ]
    HJ = joints["J_Bip_C_Head"]

    def finger(name, tip):
        return [joints[f"J_Bip_L_{name}{i}"] for i in (1, 2, 3)] + [tip]

    FING = {name: finger(name, tip) for name, tip in zip(FN, (0.022, 0.024, 0.022, 0.019))}
    THUMB = finger("Thumb", 0.024)
    V = {}
    # ---- torso
    for k, (z, rx, f, b, cy, g, dzb) in enumerate(TORSO):
        if g == "hip":
            rx *= P["hip"]
            f *= 0.5 + 0.5 * P["hip"]
            b *= P["butt"] * (0.5 + 0.5 * P["hip"])
        if g == "waist":
            m = P["waist"] if k in (3, 4) else 0.5 + 0.5 * P["waist"]
            rx *= m
            f = f * (0.4 + 0.6 * m) + P["belly"] * (1.0 if k in (2, 3) else 0.6)
            b *= 0.5 + 0.5 * m
        if g == "chest":
            rx *= P["chest"]
            f *= P["chest_d"]
            b *= P["chest_d"]
            f += P["belly"] * 0.25
        if g == "sh":
            rx = rx * P["chest"] + P["sh_w"]
            f *= P["chest_d"]
            b *= P["chest_d"]
        if g in ("nb", "neck"):
            rx *= P["neck"]
            f *= P["neck"]
            b *= P["neck"]
        st = 0.0
        if g in ("chest", "sh"):
            st = -P["stoop"] * (0.35 if g == "chest" else 0.6)
            b += P["stoop"] * (0.5 if g == "chest" else 0.9)
            f -= P["stoop"] * 0.3
        if g == "nb":
            st = -P["stoop"] * 0.3
        for j in range(NT):
            th = j * 2 * math.pi / NT
            x, y = sup(th, rx, f, b, cy, 2.5)
            zz = z + dzb * (1 - math.cos(th)) / 2
            # Taper the deltoid into the acromion and raise the outer clavicle.
            if k in (9, 10) and math.cos(th) > 0:
                y -= 0.009 * math.sin(abs(th) * 2) ** 2
                zz += 0.008 * abs(math.sin(th))
            zz = np.interp(
                zz, [0.850, 0.915, 1.327, 1.424], [HIP[2] - 0.065, HIP[2] + 0.005, SJ[2], HJ[2] - 0.030]
            )
            if k in (5, 6, 7) and j in (1, 2, 3, 13, 14, 15):  # the bust
                jj = j if j < 8 else NT - j
                y -= P["bust"] * {1: 0.022, 2: 0.030, 3: 0.007}[jj] * {5: 0.35, 6: 1.0, 7: 0.5}[k]
                if k == 5:
                    zz -= 0.006 * P["bust"]
            V[("T", k, j)] = np.array([x, y + st, zz])
    V[("C",)] = np.array([0.020, 0.008, HIP[2] - 0.111])
    # ---- head (rings NTOR .. NTOR+len(HEAD)-1, then the pole)
    hs = HS * P["head"]
    st = 0.0
    for i, (zf, zb, w, f, b, n, g) in enumerate(HEAD):
        if g in ("chin", "jaw"):
            w *= P["jaw"]
        if g == "chin":
            zf -= P["chin"]
            n = P["chin_n"]
        if g == "under":
            zf -= P["chin"] * 0.7
        if g in ("jaw", "mouth"):
            w += P["cheek"] * (1.0 if g == "jaw" else 0.8)
        if g == "mouth":
            w *= 0.6 + 0.4 * P["jaw"]
        if g == "brow":
            f += P["brow"]
        for j in range(NT):
            th = j * 2 * math.pi / NT
            x, y = sup(th, w, f, b, 0.0, n)
            z = zf * (1 + math.cos(th)) / 2 + zb * (1 - math.cos(th)) / 2
            V[("T", NTOR + i, j)] = HJ + hs * np.array([x, y + YS, z]) + np.array([0, st, 0])
    V[("HP",)] = HJ + hs * np.array([0, YS + 0.002, 0.202]) + np.array([0, st, 0])
    # ---- left arm: rings 1..11 (ring 0 is the armhole in the torso)
    au = nrm(EJ - SJ)
    al = nrm(WJ - EJ)
    idx1 = np.array(FING["Index"][0])
    lit1 = np.array(FING["Little"][0])
    mid1 = np.array(FING["Middle"][0])
    hd = nrm(mid1 - WJ)
    hu = lit1 - idx1
    hu = nrm(hu - hu.dot(hd) * hd)
    hn = nrm(np.cross(hd, hu))
    if hn[2] < 0:
        hn = -hn
    X = np.array([0.0, 0.0, 1.0])
    arm_spec = [  # centre, tangent, radius n, radius u, twist toward the hand's frame
        (SJ + au * 0.028 + [P["sh_w"] * 0.35, 0, -0.003], au, 0.058, 0.054, 0.0, X),
        (lerp(SJ, EJ, 0.31), au, 0.053, 0.047, 0.0, None),
        (lerp(SJ, EJ, 0.61), au, 0.044, 0.044, 0.1, None),
        (lerp(SJ, EJ, 0.89), au, 0.033, 0.034, 0.2, None),
        (EJ, nrm(au + al), 0.031, 0.033, 0.3, None),
        (lerp(EJ, WJ, 0.13), al, 0.035, 0.034, 0.45, None),
        (lerp(EJ, WJ, 0.38), al, 0.036, 0.036, 0.65, None),
        (lerp(EJ, WJ, 0.78), al, 0.024, 0.028, 0.9, None),
    ]
    for r, (c, t, rn, ru, tw, nfix) in enumerate(arm_spec, start=1):
        n = nfix if nfix is not None else lerp(X, hn, tw)
        n = nrm(n - n.dot(t) * t)
        u = nrm(np.cross(n, t))
        for i, a in enumerate(ARMALPHA):
            a = math.radians(a)
            V[("A", r, i)] = (
                c + (rn * P["arm"] / 0.936) * math.cos(a) * n + (ru * P["arm"] / 0.936) * math.sin(a) * u
            )
    # the hand: wrist ring 9, mid palm 10, web ring 11, in the hand's frame (hd down, hu index->little, hn back)
    hsz = P["hand"]

    def hp(d, s, n):
        return WJ + hsz * (hd * d + hu * s + hn * n)

    ks = [(np.array(FING[f][0]) - WJ).dot(hu) for f in FN]
    kd = [(np.array(FING[f][0]) - WJ).dot(hd) for f in FN]
    for r, d, s0, s1, h in ((9, 0.0, -0.023, 0.023, 0.0165), (10, 0.040, -0.037, 0.033, 0.0150)):
        for i in range(5):
            s = s0 + (s1 - s0) * i / 4
            hh = h * (0.8 if i in (0, 4) else 1.0)
            V[("A", r, i)] = hp(d, s, hh)
            V[("A", r, 9 - i)] = hp(d, s, -hh)
    ws = [ks[0] - 0.0090, (ks[0] + ks[1]) / 2, (ks[1] + ks[2]) / 2, (ks[2] + ks[3]) / 2, ks[3] + 0.0078]
    wd = [
        kd[0] + 0.006,
        (kd[0] + kd[1]) / 2 + 0.011,
        (kd[1] + kd[2]) / 2 + 0.012,
        (kd[2] + kd[3]) / 2 + 0.011,
        kd[3] + 0.005,
    ]
    for i in range(5):
        V[("A", 11, i)] = hp(wd[i], ws[i], 0.0090)
        V[("A", 11, 9 - i)] = hp(wd[i], ws[i], -0.0090)

    def tube(tag, joints, tip, radii, first):
        j1, j2, j3 = [WJ + hsz * (np.array(j) - WJ) for j in joints]
        tipp = j3 + nrm(j3 - j2) * tip * hsz
        cs = [first(j1, j2), j2, j3, tipp]
        ts = [nrm(j2 - j1), nrm(j3 - j1), nrm(tipp - j2), nrm(tipp - j3)]
        for fr, (c, t, rr) in enumerate(zip(cs, ts, radii), start=1):
            if tag[0] == "F":
                uu = nrm(hu - hu.dot(t) * t)
                nn = nrm(np.cross(t, uu))
                if nn.dot(hn) < 0:
                    nn = -nn
                cor = [(-1, 1), (1, 1), (1, -1), (-1, -1)]
            else:
                uu = nrm(hd - hd.dot(t) * t)
                nn = hn - hn.dot(t) * t
                nn = nrm(nn - nn.dot(uu) * uu)
                cor = [(-1, 1), (1, 1), (1, -1), (-1, -1)]
            h = rr * hsz / 0.89
            for q, (su, sn) in enumerate(cor):
                V[tag + (fr, q)] = c + uu * su * h + nn * sn * h
        V[tag + (5, 0)] = tipp + ts[3] * radii[3] * hsz * 0.9  # the tip's pole

    for fi, f in enumerate(FN):
        j1, j2, j3, tip = FING[f]
        rad = {"Index": 0.0073, "Middle": 0.0076, "Ring": 0.0072, "Little": 0.0064}[f]
        tube(
            ("F", fi),
            (j1, j2, j3),
            tip,
            [rad, rad * 0.95, rad * 0.88, rad * 0.70],
            lambda a, b: a + nrm(b - a) * 0.024 * hsz,
        )
    tube(("TH",), THUMB[:3], THUMB[3], [0.0118, 0.0100, 0.0090, 0.0072], lambda a, b: a + (b - a) * 0.80)

    # ---- left leg: rings 1..NLEG, then the toe pole
    def bone_c(z):
        if z >= KJ[2]:
            t = (HIP[2] - z) / (HIP[2] - KJ[2])
            return lerp(HIP, KJ, t)
        t = (KJ[2] - z) / (KJ[2] - AJ[2])
        return lerp(KJ, AJ, t)

    for r, (z, rx, ry, cyo, g) in enumerate(LEG, start=1):
        z = np.interp(z, [0.099, 0.474, 0.908], [AJ[2], KJ[2], HIP[2]])
        c = bone_c(z)
        m = P["leg"] * (0.5 + 0.5 * P["hip"] if r == 1 else 1.0) / 0.936
        cx = c[0]
        if g == "ankle":
            m = (0.5 + 0.5 * P["leg"]) / 0.936
        for i, ph in enumerate(LEGPHI):
            ph = math.radians(ph)
            x = cx + rx * m * math.sin(ph)
            if r <= 2:
                x = max(x, 0.016)
            V[("L", r, i)] = np.array(
                [
                    x,
                    c[1]
                    + cyo
                    - ry * m * math.cos(ph)
                    - (0.009 * max(0.0, math.cos(ph)) ** 3 if r == 5 else 0.0),
                    z + (0.012 * math.sin(ph) if g in ("calf", "ankle") else 0.0),
                ]
            )
    toe = joints["J_Bip_L_ToeBase"] - AJ
    ff = nrm([toe[0], toe[1], 0])
    fp = np.array([-ff[1], ff[0], 0])
    fs = P["foot"]
    for q, (s, zc, (ads, adz), rl) in enumerate(FOOT):
        r = len(LEG) + 1 + q
        for i, ph in enumerate(LEGPHI):
            ph = math.radians(ph)
            ss = (s + ads * math.cos(ph)) * fs
            lat = rl * fs * math.sin(ph) / 0.936
            V[("L", r, i)] = (
                np.array([AJ[0], AJ[1], 0]) + ff * ss + fp * lat + [0, 0, max(0.0, zc + adz * math.cos(ph))]
            )
    V[("LP",)] = np.array([AJ[0], AJ[1], 0]) + ff * 0.203 * fs + [0, 0, 0.016]
    # ---- ear (left): a small closed lobe, four rings of four and a tip
    ec = HJ + hs * np.array([0.0775, YS + 0.014, 0.052]) + [0, st, 0]
    for r, (out, back, hh, ww) in enumerate(
        [(-0.006, 0, 0.013, 0.007), (0.003, 0.003, 0.017, 0.009), (0.007, 0.007, 0.015, 0.008)]
    ):
        for q, (sy, sz) in enumerate([(-1, 1), (1, 1), (1, -1), (-1, -1)]):
            V[("E", r, q)] = ec + hs * np.array([out, back + sy * ww, sz * hh + (0.004 if sz > 0 else 0)])
    # Child silhouette: shorter long bones relative to the ribcage, rounder abdomen.
    if P.get("child"):
        for v in V.values():
            v[0] -= 0.18 * max(v[0] - SJ[0], 0.0)
            v[2] -= 0.17 * min(v[2], HIP[2])
    return V


def mkey(k):
    """the mirrored vertex's key"""
    if k[0] == "T":
        return ("T", k[1], (NT - k[2]) % NT)
    if k[0] == "HP":
        return k
    return ("R" + k[0],) + k[1:]


def arm_key(r, i):
    if r == 0:
        a = A0
        return [
            ("T", a + 2, 3),
            ("T", a + 3, 3),
            ("T", a + 3, 4),
            ("T", a + 3, 5),
            ("T", a + 2, 5),
            ("T", a + 1, 5),
            ("T", a, 5),
            ("T", a, 4),
            ("T", a, 3),
            ("T", a + 1, 3),
        ][i]
    return ("A", r, i)


def leg_key(r, i):
    if r == 0:
        return ("T", 0, i) if i < 9 else ("C",)
    return ("L", r, i)


def topology():
    """faces as key tuples with a material tag; the right side by mirroring."""
    F = []
    nk = NTOR + len(HEAD)
    hole = {(k, j) for k in range(A0, A0 + 3) for j in (3, 4)}
    hole |= {(k, NT - 1 - j) for (k, j) in hole}
    for k in range(nk - 1):
        for j in range(NT):
            if (k, j) in hole:
                continue
            if k < 3:
                m = "shorts"
            elif k < 11:
                m = "top"
            else:
                m = "skin"
            hk = k - NTOR
            if 1 <= hk <= 6 and (j in (13, 14, 15, 0, 1, 2)):
                m = "face"
            F.append(([("T", k, j), ("T", k, (j + 1) % NT), ("T", k + 1, (j + 1) % NT), ("T", k + 1, j)], m))
    for j in range(NT):
        F.append(([("T", nk - 1, j), ("T", nk - 1, (j + 1) % NT), ("HP",)], "skin"))
    L = []
    for r in range(11):  # arm and palm
        for i in range(10):
            if r == 9 and i == 9:
                continue  # the thumb's opening
            L.append(
                (
                    [
                        arm_key(r, i),
                        arm_key(r, (i + 1) % 10),
                        arm_key(r + 1, (i + 1) % 10),
                        arm_key(r + 1, i),
                    ],
                    "top" if r == 0 else "skin",
                )
            )  # a cap sleeve: the top ends on the arm's first ring

    def tube_faces(tag, base):
        ring = lambda fr: base if fr == 0 else [tag + (fr, q) for q in range(4)]
        for fr in range(4):
            a, b = ring(fr), ring(fr + 1)
            for q in range(4):
                L.append(([a[q], a[(q + 1) % 4], b[(q + 1) % 4], b[q]], "skin"))
        b = ring(4)
        for q in range(4):
            L.append(([b[q], b[(q + 1) % 4], tag + (5, 0)], "skin"))

    for f in range(4):
        tube_faces(("F", f), [("A", 11, f), ("A", 11, f + 1), ("A", 11, 8 - f), ("A", 11, 9 - f)])
    tube_faces(("TH",), [("A", 9, 0), ("A", 10, 0), ("A", 10, 9), ("A", 9, 9)])
    for r in range(NLEG):
        m = "shorts" if r < 2 else ("shoes" if r >= len(LEG) - 1 else "skin")
        for i in range(10):
            L.append(
                (
                    [
                        leg_key(r, i),
                        leg_key(r, (i + 1) % 10),
                        leg_key(r + 1, (i + 1) % 10),
                        leg_key(r + 1, i),
                    ],
                    m,
                )
            )
    for i in range(10):
        L.append(([("L", NLEG, i), ("L", NLEG, (i + 1) % 10), ("LP",)], "shoes"))
    for r in range(2):  # the ear
        for q in range(4):
            L.append(
                ([("E", r, q), ("E", r, (q + 1) % 4), ("E", r + 1, (q + 1) % 4), ("E", r + 1, q)], "skin")
            )
    L.append(([("E", 2, q) for q in range(4)], "skin"))
    L.append(([("E", 0, q) for q in range(4)][::-1], "skin"))
    # A small four-corner perineal panel separates the medial thigh poles.
    F.append(([("T", 0, 0), ("C",), ("T", 0, 8), ("RC",)], "shorts"))
    F += L
    F += [([mkey(k) for k in ks][::-1], m) for ks, m in L]
    return F


def full(P, joints):
    V = positions(P, joints)
    for k, p in list(V.items()):
        mk = mkey(k)
        if mk not in V:
            V[mk] = p * np.array([-1, 1, 1])
    return V
