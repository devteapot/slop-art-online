"""The face's texture, painted by script. numpy only (no Blender, no Pillow).

One square atlas per person (head_mesh.py lays it out): the skin of the whole head, and above it
the two eyes and a swatch of plain skin for the ears. Everything is painted from the head's form
(head_form.py), texel by texel: each texel knows where on the head it lies, so the blush sits on
the cheek and the lips on the mouth's slit whatever the face's shape.

What is painted, as the VRoid controls paint it (their pictures were studied, none is used):
the skin's tone with a blush, soft shade round the eyes and under the nose and lip, the lips,
the lids' edge; and each eye as layers: the white with the upper lid's shadow, the iris with a
dark rim, a gradient from a shaded top to a lit lower crescent, fine rays, the pupil, and two
highlights on the same side in both eyes. Beyond theirs: stubble and beards, age lines, freckles.

    paint(hf, look) -> uint8 array, ATLAS × ATLAS × 3, sRGB, row 0 at the top
    write_png(path, array)
"""

import math
import struct
import zlib

import numpy as np

from head_form import ORIGIN, lerp, smooth
from head_mesh import ATLAS, EYE_COLS, EYE_ROWS, eye_frame, skin_dirs


def write_png(path, a):
    a = np.asarray(a, dtype=np.uint8)
    h, w = a.shape[:2]
    raw = b"".join(b"\x00" + a[r].tobytes() for r in range(h))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def upsample(a, f):
    h, w = a.shape[:2]

    def axis(n):
        c = (np.arange(n * f) + 0.5) / f - 0.5
        i0 = np.clip(np.floor(c).astype(int), 0, n - 2)
        return i0, np.clip(c - i0, 0, 1)

    r0, rt = axis(h)
    c0, ct = axis(w)
    a = a[r0] * (1 - rt)[:, None, None] + a[r0 + 1] * rt[:, None, None]
    return a[:, c0] * (1 - ct)[None, :, None] + a[:, c0 + 1] * ct[None, :, None]


def value_noise(shape, cell, rng):
    """Smooth noise in 0..1 over a picture, with features about `cell` texels across."""
    h, w = shape
    gh, gw = h // cell + 3, w // cell + 3
    g = rng.random((gh, gw))
    y = np.arange(h) / cell
    x = np.arange(w) / cell
    y0, x0 = y.astype(int), x.astype(int)
    ty, tx = smooth(y - y0)[:, None], smooth(x - x0)[None, :]
    a = g[y0][:, x0] * (1 - tx) + g[y0][:, x0 + 1] * tx
    b = g[y0 + 1][:, x0] * (1 - tx) + g[y0 + 1][:, x0 + 1] * tx
    return a * (1 - ty) + b * ty


class Canvas:
    """A picture with, for every texel, the front-view position it shows (x across, z up, in
    metres) and a mask of where painting may land."""

    def __init__(self, x, z, mask, colour):
        self.x, self.z, self.mask = x, z, mask
        self.img = np.empty(x.shape + (3,))
        self.img[:] = colour

    def blend(self, colour, alpha, where=None):
        a = np.clip(alpha, 0, 1) * (self.mask if where is None else where)
        self.img += (np.array(colour) - self.img) * a[..., None]

    def blob(self, cx, cz, rx, rz, colour, alpha, mirror=True, power=2.0):
        x = np.abs(self.x) if mirror else self.x
        d = ((x - cx) / rx) ** 2 + ((self.z - cz) / rz) ** 2
        self.blend(colour, alpha * np.exp(-(d ** (power / 2))))

    def stroke(self, pts, width, colour, alpha, soft=0.00035, mirror=True, taper=(0.0, 0.0)):
        """A line through pts (x, z). `width` is its half width, or a function of how far along
        it (0..1); `taper` thins that share of each end to a point."""
        pts = np.asarray(pts, float)
        x = np.abs(self.x) if mirror else self.x
        z = self.z
        m = 0.004
        box = (x > pts[:, 0].min() - m) & (x < pts[:, 0].max() + m) & (z > pts[:, 1].min() - m) & (z < pts[:, 1].max() + m) & (self.mask > 0)
        if not box.any():
            return
        px, pz = x[box], z[box]
        seg = np.hypot(*np.diff(pts, axis=0).T)
        total = seg.sum()
        best = np.full(px.shape, 1e9)
        along = np.zeros(px.shape)
        run = 0.0
        for (a, b), ln in zip(zip(pts, pts[1:]), seg):
            ab = b - a
            t = np.clip(((px - a[0]) * ab[0] + (pz - a[1]) * ab[1]) / max(ln * ln, 1e-12), 0, 1)
            d = np.hypot(px - (a[0] + t * ab[0]), pz - (a[1] + t * ab[1]))
            closer = d < best
            best = np.where(closer, d, best)
            along = np.where(closer, (run + t * ln) / total, along)
            run += ln
        w = width(along) if callable(width) else np.full(px.shape, width)
        if taper[0]:
            w = w * smooth(along / taper[0]) ** 0.7
        if taper[1]:
            w = w * smooth((1 - along) / taper[1]) ** 0.7
        a = alpha * smooth((w - best) / soft + 0.5)
        self.img[box] += (np.array(colour) - self.img[box]) * (a * self.mask[box])[:, None]


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


# -------------------------------------------------------------------------------------- skin


def strands(shape, rng):
    """Hair as a picture's worth of fine vertical strokes, 0..1: long thin streaks at two scales."""
    h, w = shape
    fine = value_noise((h // 6 + 2, w), 2, rng)
    coarse = value_noise((h // 14 + 2, w), 5, rng)
    rows = np.arange(h)
    return 0.6 * upsample(fine[..., None], 1)[np.clip(rows // 6, 0, fine.shape[0] - 1)][..., 0] + 0.4 * coarse[np.clip(rows // 14, 0, coarse.shape[0] - 1)]


def paint_skin(hf, look, rng):
    rows, cols = ATLAS - EYE_ROWS, ATLAS
    f = 4
    d = skin_dirs(cols // f, rows // f)
    r = hf.radius(d.reshape(-1, 3)).reshape(d.shape[:2])
    pos = upsample(ORIGIN + d * r[..., None], f)
    x, y, z = pos[..., 0], pos[..., 1], pos[..., 2]
    az = np.degrees(np.arctan2(-x, y))
    front = smooth((y - 0.012) / 0.03)
    skin, shade, warm, line = look["skin"], look["skin_shade"], look["skin_warm"], look["skin_line"]
    c = Canvas(x, z, front, skin)
    ax = np.abs(x)
    L, ex, ez, ew = hf.L, hf.eye_x, hf.eye_z, hf.eye_w
    zn, zt, zs, zm, mw = hf.nasion_z, hf.nose_tip_z, hf.nose_base_z, hf.mouth_z, hf.mouth_w
    old = look["lines"]
    # Tone: a blush on the cheeks, warmth on the nose, the temples and jaw a little deeper.
    c.blob(0.041, ez - 0.036 * L, 0.021, 0.014, warm, look["blush"])
    c.blob(0.0, zt + 0.001, 0.009, 0.007, warm, 0.5 * look["blush"] + 0.10 * old, mirror=False)
    c.blend(shade, 0.16 * smooth((ax - 0.050) / 0.022) * smooth((ez - 0.01 - z) / 0.05))
    c.blend(shade, 0.14 * smooth((z - (ez + hf.eye_up + 0.034)) / 0.03))  # under the hair
    # The eyes' hollows: shade on the upper lid and at the inner corner, a little under the eye.
    c.blob(ex, ez + hf.eye_up + 0.0035, ew * 0.95, 0.0048, shade, 0.30 + 0.10 * old)
    c.blob(ex - ew * 0.95, ez + 0.001, 0.0065, 0.0085, shade, 0.22 + 0.10 * old)
    c.blob(ex + 0.001, ez - hf.eye_lo - 0.0035, ew * 0.80, 0.0030, shade, 0.10 + 0.30 * old)
    # The lids' edge: a fine darker line round each opening.
    inside, _, _, _ = hf.eye_inside(x, z, grow=0.0009)
    inner, _, _, _ = hf.eye_inside(x, z, grow=-0.0002)
    c.blend(line, 0.38 * (inside & ~inner & (y > 0)))
    # The nose: shade under the tip and round the wings, a soft flank up the bridge, the
    # nostrils; stronger on a grown man's or an old face.
    wid = hf.nose_wid
    nl = look["nose_line"]
    c.blob(0.0, zs + 0.0010, 0.0078 * wid, 0.0022, shade, 0.80, mirror=False)
    c.blob(0.0, zs - 0.0012, 0.0042 * wid, 0.0015, line, 0.40, mirror=False)
    c.blob(0.0088 * wid, zs + 0.0030, 0.0019, 0.0026, line, 0.60 * look["nostril"])
    c.stroke([(0.0048 * wid, zs + 0.0010), (0.0080 * wid, zs + 0.0016), (0.0112 * wid, zs + 0.0034), (0.0122 * wid, zs + 0.0062)], 0.00042, line, 0.85 * look["nostril"], taper=(0.25, 0.45))
    t = np.clip((zn - z) / (zn - zt), 0, 1)
    flank = np.exp(-(((ax - lerp(0.0060, 0.0100, t) * wid * 1.05) / 0.0026) ** 2)) * smooth((zn - 0.006 - z) / 0.012) * smooth((z - zt - 0.002) / 0.008)
    c.blend(shade, 0.30 * nl * flank)
    c.blob(0.0, zt + 0.0035, 0.0028 * wid, 0.0030, mix(skin, (1.0, 0.97, 0.93), 0.5), 0.30 * nl, mirror=False)
    # The lips: a tint, fuller below; the line between them; shade beneath.
    tint = look["lip_tint"]
    lz = hf.mouth_line(x)
    u = np.clip(ax / mw, 0, 1.2)
    up_h = 0.0040 * hf.lip * np.clip(1 - u**2.2, 0, None) ** 0.75 * (1 - 0.26 * np.exp(-((ax / 0.0036) ** 2)))
    lo_h = 0.0060 * hf.lip * (1 - (u / 0.92) ** 2.0).clip(0) ** 0.62
    lip_soft = 0.0009
    upper = smooth((lz + up_h - z) / lip_soft + 0.5) * smooth((z - lz) / lip_soft + 0.5) * (u < 1.0)
    lower = smooth((z - (lz - lo_h)) / lip_soft + 0.5) * smooth((lz - z) / lip_soft + 0.5) * (u < 0.92)
    lip = look["lip"]
    c.blend(mix(lip, shade, 0.25), 0.90 * tint * upper)
    c.blend(lip, 0.80 * tint * lower)
    c.blob(0.0, zm - 0.45 * 0.0060 * hf.lip, 0.0050, 0.0013, mix(lip, (1.0, 0.96, 0.92), 0.6), 0.45 * tint * lower, mirror=False)
    c.blob(0.0, zm - 0.0060 * hf.lip - 0.0028, 0.0095, 0.0022, shade, 0.42, mirror=False)
    pts = [(mw * t_, float(hf.mouth_line(np.array([mw * t_]))[0])) for t_ in np.linspace(0, 1.0, 12)]
    mouth_c = mix(look["mouth_line"], line, 0.2)
    c.stroke(pts, lambda a: 0.00052 - 0.00022 * a, mouth_c, 0.95, soft=0.0003)
    c.blob(mw, pts[-1][1], 0.0013, 0.0011, mouth_c, 0.7)
    # Stubble: a cool shade over the jaw and lip, grained.
    stub = look["stubble"]
    beard = look.get("beard")
    grain = value_noise((rows, cols), 3, rng)
    hairs = strands((rows, cols), rng)
    if stub > 0:
        low = smooth((zm + 0.012 - z) / 0.030) * smooth((y + 0.02) / 0.04) * (0.60 + 0.40 * smooth((ax - 0.010) / 0.03))
        low = np.maximum(low, 0.9 * np.exp(-((ax / (mw * 1.15)) ** 2 + ((z - (zs - 0.0085)) / 0.0055) ** 2)))
        low *= smooth((104 - np.abs(az)) / 12)
        low *= 1 - upper - lower
        c.blend(look["stubble_colour"], stub * low * (0.20 + 0.45 * grain**1.5), where=np.ones_like(front))
    # A beard: the hair's colour in fine strokes, its edge broken into hairs.
    cover = hf.beard_cover(beard, ax, z, az, e=0.0030 * (hairs - 0.5), soft=0.0007)
    if cover is not None:
        cover = cover * smooth((y + 0.03) / 0.03)
        bc = np.array(look["beard_colour"])
        tone = 0.62 + 0.76 * hairs
        hair = bc[None, None, :] * tone[..., None] + (0.10 * np.clip(tone - 1.0, 0, 1))[..., None]
        a = np.clip(cover * look.get("beard_density", 1.0), 0, 1)
        c.img += (np.clip(hair, 0, 1) - c.img) * a[..., None]
    # Age: folds from the nose past the mouth, lines on the forehead and between the brows,
    # crow's feet, bags, lines down from the mouth's corners.
    if old > 0.02:
        k = min(old, 1.3)
        c.stroke([(0.0118 * wid, zs + 0.0065), (0.0160 * wid, zs + 0.0010), (0.0205, lerp(zs, zm, 0.55)), (mw + 0.0050, zm + 0.0010), (mw + 0.0062, zm - 0.0050)],
                 0.00055 * k, line, 0.60 * min(k, 1), taper=(0.25, 0.35))
        c.stroke([(ex - ew * 0.75, ez - hf.eye_lo - 0.0042), (ex, ez - hf.eye_lo - 0.0064), (ex + ew * 0.80, ez - hf.eye_lo - 0.0040)], 0.00042 * k, line, 0.50 * min(k, 1), taper=(0.4, 0.4))
        if k > 0.35:
            for dz_, reach in ((0.0030, 0.0085), (-0.0012, 0.0100), (-0.0052, 0.0080)):
                x0 = ex + ew + 0.0028
                c.stroke([(x0, ez + dz_ * 0.6), (x0 + reach * 0.5, ez + dz_ * 1.15), (x0 + reach, ez + dz_ * 2.0)], 0.00030 * k, line, 0.50 * min(k, 1), taper=(0.2, 0.6))
            brow_z = ez + hf.eye_up + hf.brow_up
            for i_, (dz_, half) in enumerate(((0.0150, 0.036), (0.0235, 0.033), (0.0320, 0.026))):
                wob = 0.0012 * math.sin(1.7 * i_ + look["seed"])
                pts_ = [(half * t_, brow_z + dz_ + 0.0016 * math.cos(math.pi * t_) + wob * math.sin(3.1 * t_ + i_)) for t_ in np.linspace(-1, 1, 15)]
                c.stroke(pts_, 0.00034 * k, line, 0.42 * min(k, 1), mirror=False, taper=(0.25, 0.25))
            c.stroke([(0.0042, brow_z + 0.0005), (0.0050, brow_z + 0.0060), (0.0044, brow_z + 0.0105)], 0.00032 * k, line, 0.40 * min(k, 1), taper=(0.3, 0.4))
            c.stroke([(mw + 0.0030, zm - 0.0030), (mw + 0.0048, zm - 0.0095), (mw + 0.0040, zm - 0.0160)], 0.00040 * k, line, 0.45 * min(k, 1), taper=(0.2, 0.5))
            c.blob(0.036, lerp(zm, ez, 0.42), 0.012, 0.022, shade, 0.16 * min(k, 1))
    # Freckles over the nose and cheeks.
    fr = look["freckles"]
    if fr > 0.02:
        n = int(70 * fr)
        fx = rng.normal(0, 0.030, n)
        fz = ez - 0.022 * L + rng.normal(0, 0.011, n) - 0.006 * np.abs(fx) / 0.03
        fr_c = mix(skin, (0.52, 0.30, 0.18), 0.75)
        for a_, b_, s_ in zip(fx, fz, rng.uniform(0.00045, 0.0010, n)):
            c.blob(a_, b_, s_, s_, fr_c, 0.42, mirror=False, power=4.0)
    # Behind the face the skin is plain; hair or a beard covers most of it.
    return c.img, dict(x=x, y=y, z=z)


# -------------------------------------------------------------------------------------- eyes


def paint_eye(hf, look, side, rng):
    mid, scale = eye_frame(hf)
    cols, rows = EYE_COLS, EYE_ROWS
    x = side * hf.eye_x + (np.arange(cols) + 0.5 - cols / 2)[None, :] / scale + np.zeros((rows, 1))
    z = hf.eye_z + mid - (np.arange(rows) + 0.5 - rows / 2)[:, None] / scale + np.zeros((1, cols))
    c = Canvas(x, z, np.ones((rows, cols)), (0.945, 0.940, 0.930))
    s = (side * x - hf.eye_x) / hf.eye_w
    up, lo = hf.lid(s)
    zr = z - hf.eye_z
    # The white greys toward the corners and under the upper lid.
    c.blend((0.78, 0.77, 0.80), 0.55 * np.clip(np.abs(s), 0, 1) ** 2.5)
    span = np.maximum(up - lo, 1e-4)
    c.blend(look["white_shade"], 0.80 * smooth(1 - (up - zr) / (0.34 * span)))
    # The iris.
    iris = look["iris"]
    r = hf.iris_r
    cx = side * (hf.eye_x - 0.035 * hf.eye_w)
    up0, lo0 = hf.lid(np.array(0.0))
    cz = hf.eye_z + min(float(up0) - 0.74 * r, float(lo0) + 0.97 * r)
    dx, dz = (x - cx) / (0.95 * r), (z - cz) / r
    rr = np.hypot(dx, dz)
    ang = np.arctan2(dz, dx)
    edge = 0.9 / (r * scale)  # one texel, in iris radii
    disc = smooth((1 - rr) / (2 * edge) + 0.5)
    dark = mix(iris, (0.02, 0.02, 0.05), 0.80)
    # The lit crescent leans warm, whatever the iris's colour: it is what makes an eye look lit.
    light = mix(mix(iris, (1.0, 0.86, 0.55), 0.38), (1.0, 0.98, 0.92), 0.30)
    # Shaded above, lit in a crescent below.
    t = smooth((0.50 - dz) / 1.4)
    base = np.array(dark)[None, None, :] * (1 - t[..., None]) + np.array(mix(iris, (1, 1, 1), 0.06))[None, None, :] * t[..., None]
    cres = smooth((-dz - 0.12) / 0.55) * smooth((0.97 - rr) / 0.22) * smooth((rr - 0.34) / 0.25)
    base += (np.array(light) - base) * (0.88 * cres)[..., None]
    # Fine rays from the pupil.
    rays = value_noise((1, 512), 4, rng)[0]
    ray = rays[((ang / (2 * math.pi) + 0.5) * 511).astype(int) % 512]
    base *= (1 + 0.26 * (ray - 0.5) * smooth((rr - 0.40) / 0.2))[..., None]
    # A dark rim, a paler ring just inside it, and the upper lid's shadow across the top.
    base += (np.array(mix(iris, (1, 1, 1), 0.25)) - base) * (0.30 * np.exp(-(((rr - 0.76) / 0.07) ** 2)) * smooth((0.2 - dz) / 0.6))[..., None]
    base += (np.array(dark) - base) * (0.95 * smooth((rr - 0.82) / 0.15))[..., None]
    base += (np.array(mix(dark, (0, 0, 0), 0.5)) - base) * (0.78 * smooth((dz - 0.22) / 0.55))[..., None]
    # The pupil.
    pup = smooth((0.40 - np.hypot(dx / 0.92, dz)) / (2.5 * edge) + 0.5)
    base += (np.array((0.035, 0.030, 0.045)) - base) * pup[..., None]
    c.img += (np.clip(base, 0, 1) - c.img) * disc[..., None]
    # Highlights: both eyes are lit from the same side.
    hs = look.get("light_side", 1.0)
    for hx, hz, hrx, hrz, a in ((0.36 * hs, 0.34, 0.250, 0.200, 0.97), (-0.34 * hs, -0.44, 0.105, 0.090, 0.85)):
        d = np.hypot((x - (cx + hx * r)) / (hrx * r), (z - (cz + hz * r)) / (hrz * r))
        c.blend((1.0, 1.0, 0.985), a * smooth((1 - d) / (3 * edge / hrx) + 0.5))
    return c.img


def paint(hf, look):
    rng = np.random.default_rng(int(look.get("seed", 0)) + 77)
    out = np.empty((ATLAS, ATLAS, 3))
    out[:] = look["skin"]
    skin, where = paint_skin(hf, look, rng)
    out[EYE_ROWS:] = skin
    for side in (-1, 1):
        c0 = 0 if side < 0 else EYE_COLS
        out[:EYE_ROWS, c0 : c0 + EYE_COLS] = paint_eye(hf, look, side, rng)
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)
