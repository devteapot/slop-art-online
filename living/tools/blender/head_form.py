"""The head's form: what a face's parameters mean in metres. numpy only (no Blender).

person.py builds the head's mesh on this form, and face_paint.py paints the face's texture on it,
so the two agree on where the eyes, nose and mouth are. docs/CHARACTERS.md has the parameters.

The head is a loft: at each height its cross-section is a superellipse given by the front view's
half width, the profile's front and back, and how boxy the front half is. Those four curves are
tables by height, so the face's outline from the front (jaw, cheekbones, chin) and its profile
(forehead, brow, lips, chin) are set directly, which a union of blobs does not allow. The nose,
brow ridge, eye sockets, cheeks, lips and chin are bumps that move the front surface forward or
back. The top and the chin are rounded off.

Axes are the head's own, in metres round its centre before person.py's HEAD_SCALE: +Y forward
(the face), +Z up, the character's left at -X. Everything is symmetric in X.
"""

import math

import numpy as np

ORIGIN = np.array([0.0, 0.0, -0.012])  # rays leave from here (it is inside every head)


def smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def lerp(a, b, t):
    return a + (b - a) * t


def curve(zs, vs, n=500):
    """A smooth curve through (z, v) points, sampled densely: a monotone cubic (it does not
    overshoot), as (z grid, values)."""
    zs, vs = np.asarray(zs, float), np.asarray(vs, float)
    order = np.argsort(zs)
    zs, vs = zs[order], vs[order]
    h = np.diff(zs)
    d = np.diff(vs) / h
    m = np.zeros_like(vs)
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, len(zs) - 1):
        if d[i - 1] * d[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    zg = np.linspace(zs[0], zs[-1], n)
    i = np.clip(np.searchsorted(zs, zg) - 1, 0, len(zs) - 2)
    t = (zg - zs[i]) / h[i]
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    return zg, h00 * vs[i] + h10 * h[i] * m[i] + h01 * vs[i + 1] + h11 * h[i] * m[i + 1]


class Head:
    """A head's form for a person: `masc` 0 (a woman's) to 1 (a man's), `child` 1 (a small
    child) to 0 (grown), `elder` 0 to 1 (old), and `face`, the face parameters, each about -1 to
    1 round the person's average (missing ones are 0)."""

    def __init__(self, masc=1.0, child=0.0, elder=0.0, face=None):
        g = lambda k: float((face or {}).get(k, 0.0))
        self.masc, self.child, self.elder = masc, child, elder
        c, e = child, elder
        # Children's faces differ little by sex.
        m = lerp(masc, 0.3, c)
        s = 2 * m - 1  # -1 a woman's, +1 a man's
        self.m = m
        # How long the lower face is (everything below the eyes scales by it).
        L = 1.0 + 0.09 * g("face_length") + 0.0425 * s - 0.0075 - 0.12 * c + 0.01 * e
        self.L = L
        wide = 1.0 + 0.075 * g("face_width") + 0.02 * c
        self.chin_z = -0.131 * L
        self.top_z = 0.115 + 0.006 * g("forehead") + 0.003 * c
        # ---- the eyes
        self.eye_x = 0.0335 * (1 + 0.075 * g("eye_spacing")) * (1 + 0.5 * (wide - 1))
        self.eye_z = 0.002 + 0.0035 * g("eye_height") - 0.007 * c - 0.0015 * (1 - m)
        size = 1 + 0.11 * g("eye_size")
        self.eye_w = lerp(lerp(0.0203, 0.0176, m), 0.0206, c) * size * (1 - 0.04 * e)
        openness = (1 + 0.15 * g("eye_open")) * (1 - 0.16 * e)
        self.eye_up = self.eye_w * lerp(lerp(0.68, 0.50, m), 0.72, c) * openness
        self.eye_lo = self.eye_w * lerp(lerp(0.36, 0.31, m), 0.40, c) * (1 + 0.10 * g("eye_open"))
        self.eye_tilt = 0.10 * g("eye_tilt") + 0.03 * (1 - m) - 0.05 * e  # the outer corner's rise, as a slope
        self.eye_peak = 0.10 * g("eye_shape") - 0.05 * m  # where the upper lid peaks: + outward
        self.iris_r = min(0.60 * (self.eye_up + self.eye_lo), 0.64 * self.eye_w) * (1 + 0.07 * g("iris_size"))
        # ---- brows
        self.brow_w = lerp(lerp(0.0042, 0.0072, m), 0.0042, c) * (1 + 0.30 * g("brow_thickness")) * (1 + 0.25 * e * m)
        self.brow_up = 0.0085 + 0.0030 * g("brow_height") + 0.0015 * (1 - m) + 0.002 * c
        self.brow_tilt = 0.0028 * g("brow_tilt") + 0.0006 * s
        self.brow_arch = 0.0048 * (1 + 0.5 * g("brow_arch")) * lerp(1.15, 0.8, m)
        self.brow_len = 1 + 0.10 * g("brow_length")
        # ---- nose
        self.nose_len = 1 + 0.17 * g("nose_length") + 0.06 * s - 0.20 * c + 0.07 * e
        self.nose_wid = 1 + 0.22 * g("nose_width") + 0.08 * s - 0.05 * c + 0.08 * e
        self.nose_out = (1 + 0.20 * g("nose_bridge") + 0.12 * s - 0.30 * c + 0.06 * e) * (1 + 0.5 * (self.nose_len - 1))
        self.nose_curve = 1.25 - 0.45 * g("nose_bridge") - 0.20 * s + 0.35 * c  # > 1 scooped, < 1 arched
        self.nose_turn = 0.0030 * g("nose_tip") + 0.0015 * c - 0.001 * e  # the tip's lift
        self.nasion_z = self.eye_z + 0.006
        self.nose_tip_z = self.eye_z - 0.040 * self.nose_len * (0.5 + 0.5 * L) + self.nose_turn
        self.nose_base_z = self.nose_tip_z - 0.0095 - self.nose_turn
        # ---- mouth
        self.mouth_z = self.nose_base_z - (0.0275 + 0.0030 * g("mouth_height")) * L
        self.mouth_w = lerp(lerp(0.0178, 0.0205, m), 0.0150, c) * (1 + 0.15 * g("mouth_width"))
        self.lip = lerp(lerp(1.20, 0.80, m), 1.05, c) * (1 + 0.32 * g("lip_fullness")) * (1 - 0.25 * e)
        self.mouth_curve = 0.0016 * g("mouth_curve") - 0.0006 * e  # corners up (+) or down
        # ---- ears
        self.ear_size = 1 + 0.13 * g("ear_size") + 0.07 * e + 0.04 * c
        self.ear_out = 22 + 13 * g("ear_out") + 4 * c
        # ---- the outline from the front: half width by height
        jaw = (0.0522 + 0.0042 * s) * (1 + 0.13 * g("jaw_width")) * (1 + 0.04 * c + 0.035 * e) * wide
        chin_w = (0.0190 + 0.0045 * s) * (1 + 0.36 * g("chin_width")) * (1 + 0.10 * c)
        cheekbone = 0.0712 * (1 + 0.06 * g("cheekbones") - 0.012 * c) * wide
        chin_len = 1 + 0.14 * g("chin_length") + 0.04 * s
        self.chin_z = self.mouth_z - (self.mouth_z - self.chin_z) * chin_len
        cz = self.chin_z
        zj = lerp(self.mouth_z, cz, 0.30)  # the jaw's angle
        skull = 0.0775 * (1 + 0.5 * (wide - 1))
        W = [(self.top_z, skull), (0.040, skull), (0.004, 0.0750 * wide), (-0.030 * L, cheekbone), (lerp(-0.030 * L, zj, 0.55), lerp(cheekbone, jaw, 0.45) * (1 + 0.02 * c)),
             (zj, jaw), (lerp(zj, cz, 0.55), lerp(jaw, chin_w, 0.52) * (1 + 0.04 * e)), (lerp(zj, cz, 0.86), chin_w * 1.22), (cz, chin_w)]
        # ---- the profile: the front of the midline, the back, and the section's widest line
        fh = 0.004 * g("forehead") + 0.003 * c - 0.002 * s  # a fuller forehead
        cf = 0.0045 * g("chin_forward") + 0.0015 * s - 0.003 * c
        F = [(self.top_z, 0.086 + fh), (0.040, 0.0865 + fh), (0.026, 0.0880 + 0.4 * fh), (self.nasion_z, 0.0868), (self.eye_z - 0.030, 0.0880), (self.nose_base_z, 0.0892),
             (self.mouth_z, 0.0885), (lerp(self.mouth_z, cz, 0.42), 0.0850 + 0.5 * cf), (lerp(self.mouth_z, cz, 0.76), 0.0862 + cf), (cz, 0.0790 + cf)]
        B = [(self.top_z, -0.109), (0.020, -0.109), (-0.030, -0.099), (-0.060 * L, -0.080), (zj, -0.052), (lerp(zj, cz, 0.5), -0.012), (lerp(zj, cz, 0.82), 0.026), (cz, 0.052 + cf)]
        C = [(self.top_z, -0.012), (0.0, -0.011), (-0.050 * L, -0.004), (zj, 0.006), (lerp(zj, cz, 0.6), 0.030), (cz, 0.064 + cf)]
        # How boxy the front half of each section is (2 an ellipse; more is flatter across the face).
        sq = 0.30 * g("jaw_square") + 0.16 * s
        A = [(self.top_z, 2.0), (0.045, 2.05), (0.004, 2.55), (-0.030 * L, 2.60 + 0.15 * g("cheekbones")), (zj, 2.30 + sq), (lerp(zj, cz, 0.6), 2.10 + 0.6 * sq), (cz, 2.0 + 0.3 * sq)]
        self.zg, self.Wg = curve(*zip(*W))
        resample = lambda rows: np.interp(self.zg, *curve(*zip(*rows)))
        self.Fg, self.Bg, self.Cg, self.Ag = resample(F), resample(B), resample(C), resample(A)
        self.dome = 0.076 + 0.006 * g("forehead")  # the height the skull's top rounds over
        self.dome_n = 2.0 + 0.25 * g("forehead") + 0.2 * c  # 2 an ellipse; more is a squarer forehead
        self.chin_round = 0.011
        # ---- bumps
        self.cheek = 0.15 + 0.75 * c + 0.55 * g("cheeks") - 0.35 * e - 0.10 * s
        self.brow_ridge = max(0.0, 0.0030 * (0.5 + 0.5 * s) * (1 - c) + 0.0015 * g("brow_ridge") + 0.0008 * e)
        self.chin_f = cf
        self.jowl = 0.6 * e + 0.25 * max(g("cheeks"), 0) * (1 - c)

    # ------------------------------------------------------------------------------------ form

    def bump(self, x, z):
        """How far the front surface stands forward of the plain loft at (|x|, z)."""
        L = self.L
        ex, ez = self.eye_x, self.eye_z
        zn, zt, zs = self.nasion_z, self.nose_tip_z, self.nose_base_z
        out = np.zeros_like(x)
        # Nose: a ridge from between the eyes to the tip, an undercut back to the lip, the wings.
        t = np.clip((zn - z) / (zn - zt), 0, 1)
        nh = 0.0165 * self.nose_out
        ridge = (0.0012 + (nh - 0.0012) * t**self.nose_curve) * smooth((zn + 0.010 - z) / 0.012)
        under = nh * smooth((z - zs) / (zt - zs)) ** 1.6
        h = np.where(z >= zt, ridge, under)
        sig = lerp(0.0062, 0.0098, t) * self.nose_wid
        out += h * np.exp(-((x / sig) ** 2))
        out += 0.0030 * self.nose_wid * np.exp(-(((x - 0.0112 * self.nose_wid) / 0.0052) ** 2 + ((z - (zs + 0.0048)) / 0.0052) ** 2))
        # Brow ridge, and the hollows the eyes sit in.
        out += self.brow_ridge * np.exp(-(((z - (ez + 0.024)) / 0.010) ** 2)) * smooth((0.060 - x) / 0.02)
        out -= (0.0042 + 0.002 * self.m) * np.exp(-(((x - ex) / 0.021) ** 2 + ((z - ez - 0.002) / 0.013) ** 2))
        # Cheeks: full for a child, hollow for the old.
        out += 0.0062 * self.cheek * np.exp(-(((x - 0.036) / 0.021) ** 2 + ((z - (ez - 0.047 * L)) / 0.024) ** 2))
        out += 0.0035 * self.jowl * np.exp(-(((x - 0.034) / 0.016) ** 2 + ((z - lerp(self.mouth_z, self.chin_z, 0.45)) / 0.016) ** 2))
        # Lips: two soft ridges and the line between them.
        mw = self.mouth_w
        across = smooth((mw * 1.25 - x) / (mw * 0.7))
        lz = self.mouth_z + self.mouth_curve * (x / mw) ** 2
        out += 0.0019 * self.lip * across * np.exp(-(((z - lz - 0.0048) / 0.0042) ** 2))
        out += 0.0024 * self.lip * across * np.exp(-(((z - lz + 0.0058) / 0.0048) ** 2))
        out -= 0.0011 * across * np.exp(-(((z - lz) / 0.0016) ** 2))
        return out

    def f(self, p):
        """Negative inside the head, positive outside; p is N×3."""
        x, y, z = np.abs(p[:, 0]), p[:, 1], p[:, 2]
        zc = np.clip(z, self.chin_z, self.top_z)
        W, F, B, C, A = (np.interp(zc, self.zg, t) for t in (self.Wg, self.Fg, self.Bg, self.Cg, self.Ag))
        u = np.clip((zc - (self.top_z - self.dome)) / self.dome, 0, 1)
        r = (1 - u**self.dome_n) ** (1 / self.dome_n)
        u = np.clip((self.chin_z + self.chin_round - zc) / self.chin_round, 0, 1)
        r = r * (1 - u**2.0) ** 0.5
        W, df, db = np.maximum(W * r, 1e-5), np.maximum((F - C) * r, 1e-5), np.maximum((C - B) * r, 1e-5)
        yb = y - self.bump(x, z) * smooth((y - C) / 0.035)
        front = yb > C
        yy = np.where(front, (yb - C) / df, (C - yb) / db)
        a = np.where(front, A, 2.0)
        g = ((x / W) ** a + yy**a) ** (1 / a)
        return (g - 1) * np.minimum(W, np.where(front, df, db)) + np.maximum(z - self.top_z, 0) + np.maximum(self.chin_z - z, 0)

    def radius(self, dirs):
        """Distance from ORIGIN to the surface along each unit direction (N×3)."""
        lo, hi = np.full(len(dirs), 0.0), np.full(len(dirs), 0.20)
        for _ in range(26):
            mid = (lo + hi) / 2
            inside = self.f(ORIGIN + dirs * mid[:, None]) < 0
            lo, hi = np.where(inside, mid, lo), np.where(inside, hi, mid)
        return (lo + hi) / 2

    def normal(self, p):
        e = 2e-4
        g = np.stack([self.f(p + np.array(v) * e) - self.f(p - np.array(v) * e) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))], axis=1)
        return g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-12)

    def project_front(self, pts):
        """Points (x, z) of the front view onto the face: N×3 positions and normals."""
        pts = np.asarray(pts, dtype=float).reshape(-1, 2)
        lo, hi = np.full(len(pts), -0.005), np.full(len(pts), 0.16)
        for _ in range(26):
            mid = (lo + hi) / 2
            inside = self.f(np.stack([pts[:, 0], mid, pts[:, 1]], axis=1)) < 0
            lo, hi = np.where(inside, mid, lo), np.where(inside, hi, mid)
        p = np.stack([pts[:, 0], (lo + hi) / 2, pts[:, 1]], axis=1)
        return p, self.normal(p)

    def point(self, az, z):
        """The surface point at angle az round the head (degrees from the front, + toward the
        character's left) and height z."""
        a = math.radians(az)
        d = np.array([[-math.sin(a), math.cos(a), 0.0]])
        zc = min(max(z, self.chin_z + 1e-4), self.top_z - 1e-4)
        lo, hi = 0.0, 0.2
        for _ in range(26):
            mid = (lo + hi) / 2
            if self.f(np.array([[0.0, 0.0, zc]]) + d * mid)[0] < 0:
                lo = mid
            else:
                hi = mid
        return np.array([0.0, 0.0, zc]) + d[0] * (lo + hi) / 2

    # ------------------------------------------------------------------------------- the eyes

    def lid(self, s):
        """The eye's opening at s in -1 (the inner corner) to 1 (the outer): heights of the upper
        and lower lids relative to eye_z, in the front view."""
        s = np.clip(np.asarray(s, float), -1, 1)
        k = self.eye_peak
        # The upper lid peaks a little to one side; the lower lid is flatter and sags outward.
        sk = s - k * (1 - s * s)
        up = self.eye_up * (1 - sk * sk) ** 0.60
        lo = -self.eye_lo * (1 - s * s) ** 0.78 * (1 + 0.10 * s)
        tilt = self.eye_tilt * self.eye_w * s
        return up + tilt, lo + tilt

    def eye_inside(self, x, z, grow=0.0):
        """Whether front-view points are inside an eye's opening; and s, and the lids there."""
        s = (np.abs(x) - self.eye_x) / (self.eye_w + grow)
        up, lo = self.lid(s)
        zr = z - self.eye_z
        return (np.abs(s) < 1) & (zr < up + grow) & (zr > lo - grow), s, up, lo

    def mouth_line(self, x):
        """The height of the line between the lips at x."""
        t = np.clip(np.abs(x) / self.mouth_w, 0, 1.3)
        return self.mouth_z + self.mouth_curve * t * t - 0.0007 * np.cos(np.pi * np.clip(t, 0, 1)) * (1 - np.clip(t, 0, 1))

    # ------------------------------------------------------------------------------ the beard

    BEARDS = dict(moustache=0.0018, goatee=0.0022, chinstrap=0.0022, short=0.0026, full=0.0068)  # how far each stands off the skin, m

    def beard_cover(self, style, ax, z, az, e=0.0, soft=0.0011):
        """How much of each point a beard style covers (0..1). ax is |x|, az the angle round
        the head from the front in degrees; `e` moves the edge (metres), for a broken edge."""
        if style not in self.BEARDS:
            return None
        mw, zm = self.mouth_w, self.mouth_z
        zs = self.nose_base_z
        # The moustache: from under the nose it follows the upper lip, thinning to a point a
        # little past and below the mouth's corners.
        u = ax / mw
        lz = self.mouth_line(ax)
        end = 1.32
        mous_top = lerp(zs - 0.0028, lz - 0.0012, np.clip(u / end, 0, 1) ** 2.4)
        mous_bot = lz + 0.0013 - 0.0040 * smooth((u - 0.80) / 0.5)
        mous = smooth((mous_top - z + e) / soft) * smooth((z - mous_bot + e) / soft) * smooth((mw * end - ax + e) / 0.002)
        mous = mous * (1 - 0.9 * np.exp(-((ax / 0.0020) ** 2)) * smooth((z - (zs - 0.0080)) / 0.003))  # the groove under the nose
        # The chin: below the lower lip, round the chin; and the patch under the lip.
        lip_bot = lz - 0.0062 * self.lip - 0.0018
        chin = smooth((lip_bot - z + e) / soft) * smooth((mw * 1.10 + 0.007 * smooth((zm - z) / 0.03) - ax + e) / 0.003)
        soul = smooth((lip_bot + 0.0030 - z + e) / soft) * smooth((0.0050 - ax + e) / 0.002) * smooth((z - (lip_bot - 0.009)) / 0.003)
        # The cheeks and jaw: below a line from the moustache's end up across the cheek to the
        # sideburn.
        a = np.abs(az)
        corner = math.degrees(math.atan2(mw * end, 0.088))
        line = np.interp(a, [0, corner, corner + 14, 62, 84, 100], [zs - 0.004, lerp(zs, zm, 0.55), lerp(zs, zm, 0.50), lerp(zm, self.eye_z, 0.40), self.eye_z - 0.014, self.eye_z + 0.014])
        jaw = smooth((line - z + 1.6 * e) / (1.6 * soft)) * smooth((104 - a) / 6.0)
        # The mouth stays clear, and the skin beside the moustache's ends.
        jaw = jaw * (1 - smooth((mw * 1.06 - ax) / 0.003) * smooth((z - lip_bot) / 0.003))
        jaw = jaw * (1 - smooth((mw * (end + 0.05) - ax) / 0.003) * smooth((z - (lz + 0.0005)) / 0.002))
        if style == "moustache":
            return mous
        if style == "goatee":
            return np.maximum(mous, np.maximum(chin * smooth((mw * 1.25 - ax) / 0.004), soul))
        if style == "chinstrap":
            # Along the jaw only: its upper edge runs level below the mouth.
            low = smooth((np.minimum(line, lerp(zm, self.chin_z, 0.30)) - z + 1.6 * e) / (1.6 * soft)) * smooth((104 - a) / 6.0)
            return np.maximum(low, soul)
        return np.maximum(np.maximum(mous, jaw), np.maximum(chin, soul))  # short, full
