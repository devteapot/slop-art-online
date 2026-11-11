"""Hair as the VRoid controls build it: a cap on the scalp and layers of broad locks combed over
it, each lock a closed lens-shaped ribbon with its own column of a strand texture. numpy only (no
Blender); person.py turns the result into the `Hair` object.

What the controls showed (docs/CHARACTERS.md, "What was learnt from VRoid"; nothing of theirs is
used, the locks here are computed and the texture is painted by `paint_strands`):

- about fifty locks, each two faces thick (a front and a back surface closed at the edges), three
  to five vertices across and many along, tapering to a point or cut blunt;
- every lock mapped root to tip onto a tall grey texture of fine streaks, darker at the root and
  the tip, tinted by the hair's colour, so each lock shows strands;
- under them the scalp itself painted with the same streaks, so no skin shows between locks;
- the long locks hang from chains of spring bones.

How a head of hair is made here:

1. **Roots and directions.** A style lays out locks in layers: where each starts on the scalp,
   which way it is combed, how long it is or how low it hangs (`STYLES`).
2. **Combing.** Every lock is walked from its root in small steps: it keeps its direction, bends
   toward the ground, and is pushed out of the head, the neck and the shoulders (`Comb`), so it
   flows over the skull and then hangs. A lock may instead be drawn toward a point (a tail's tie).
3. **Curl** bends the walked path into waves.
4. **Ribbons.** Each path becomes a lens-shaped ribbon standing a little off whatever it lies on,
   with per-vertex colour (root shade, a tone of its own, grey hairs) and strand UVs.

Positions are in the head's own frame (head_form.py): metres round the head's centre before
person.py's HEAD_SCALE, +Y forward, +Z up, the character's left at -X.
"""

import math
import random

import numpy as np

from head_form import ORIGIN, lerp, smooth

STYLES = ("crop", "short", "tousled", "swept", "shag", "bob", "bob_parted", "long", "tail", "bun", "braid", "braids", "sides", "kerchief", "balding")
# Styles whose hair hangs: `length` is how far below the hairline at the sides, in metres. For
# the others it scales the hairs' own length.
HANGING = ("shag", "bob", "bob_parted", "long", "tail", "braid", "braids", "kerchief")

TEX_W, TEX_H = 256, 512  # the strand texture
DOWN = np.array([0.0, 0.0, -1.0])


def head_dir(az, el):
    a, e = np.radians(az), np.radians(el)
    return np.stack([-np.sin(a) * np.cos(e), np.cos(a) * np.cos(e), np.sin(e)], axis=-1)


def unit(v):
    v = np.asarray(v, float)
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def paint_strands(seed=0):
    """The strand texture: grey streaks running down (root at the top), darker at the root and
    the tip, with a few dark gaps between strands. It wraps across, so a lock may take any
    column. uint8, TEX_H × TEX_W × 3, sRGB; the same for everyone (colour is per vertex)."""
    rng = np.random.default_rng(1000 + seed)
    w, h = TEX_W, TEX_H
    v = (np.arange(h) + 0.5) / h

    def streaks(cells, drift):
        """Noise that is fine across and slow along: `cells` streaks across, wandering."""
        rows = 6
        g = rng.random((rows + 1, cells))
        u = (np.arange(w) + 0.5) / w * cells
        out = np.empty((h, w))
        for r in range(h):
            t = v[r] * rows
            i = min(int(t), rows - 1)
            f = smooth(t - i)
            uu = u + drift * math.sin(6.0 * v[r] + i)
            i0 = np.floor(uu).astype(int) % cells
            fu = smooth(uu - np.floor(uu))
            a = g[i][i0] * (1 - fu) + g[i][(i0 + 1) % cells] * fu
            b = g[i + 1][i0] * (1 - fu) + g[i + 1][(i0 + 1) % cells] * fu
            out[r] = a * (1 - f) + b * f
        return out

    img = 0.80 + 0.13 * (streaks(9, 0.25) - 0.5) + 0.12 * (streaks(28, 0.15) - 0.5) + 0.10 * (streaks(75, 0.0) - 0.5)
    # Gaps between strands: thin dark lines that come and go along the length.
    for _ in range(11):
        u0 = rng.uniform(0, w)
        wid = rng.uniform(0.7, 1.6)
        a, b = sorted(rng.uniform(-0.2, 1.2, 2))
        wob = rng.uniform(0.5, 2.5)
        ph = rng.uniform(0, 6.28)
        for r in range(h):
            if not a < v[r] < b:
                continue
            c = u0 + wob * math.sin(5.0 * v[r] + ph)
            d = np.abs((np.arange(w) - c + w / 2) % w - w / 2)
            k = np.clip(1 - d / wid, 0, 1) * smooth(min(v[r] - a, b - v[r]) / 0.08)
            img[r] -= 0.20 * k
    # A few light strands.
    for _ in range(7):
        u0 = rng.uniform(0, w)
        ph = rng.uniform(0, 6.28)
        for r in range(h):
            c = u0 + 1.5 * math.sin(4.0 * v[r] + ph)
            d = np.abs((np.arange(w) - c + w / 2) % w - w / 2)
            img[r] += 0.07 * np.clip(1 - d / 1.2, 0, 1)
    # Darker at the root, a little darker toward the tip.
    shade = 1 - 0.30 * (1 - smooth(v / 0.16)) - 0.14 * smooth((v - 0.72) / 0.28)
    img = img * shade[:, None]
    out = np.clip(img, 0, 1)[..., None] * np.ones(3)
    return (out * 255 + 0.5).astype(np.uint8)


TEX_MEAN = 0.74  # the texture's mean value, about: vertex colours are divided by it


class Comb:
    """What hair lies on: the head's form and, below it, the neck (or a collar) and the
    shoulders. `dist(p)` is roughly the distance from the nearest of them, negative inside."""

    def __init__(self, hf, body=None):
        self.hf = hf
        b = dict(neck_r=0.050, neck_y=-0.012, neck_top=-0.070, shoulder_z=-0.200, half_w=0.165, half_d=0.085, torso_y=0.0, round=0.045)
        b.update(body or {})
        self.b = b
        # The head's surface sampled by direction from its middle: its distance out, and how
        # squarely it faces outward there. head_form's own function is not a distance (near the
        # top of the skull it is many times too small), and hair must lie a set height off.
        self.az = np.arange(-180, 180, 5.0)
        self.el = np.arange(-90, 90.1, 5.0)
        aa, ee = np.meshgrid(self.az, self.el, indexing="ij")
        d = head_dir(aa.ravel(), ee.ravel())
        r = hf.radius(d)
        n = hf.normal(ORIGIN + d * r[:, None])
        self.R = r.reshape(aa.shape)
        self.C = np.clip(np.sum(n * d, axis=1), 0.35, 1.0).reshape(aa.shape)

    def head(self, p):
        """Roughly the distance of points from the head's surface (negative inside)."""
        q = p - ORIGIN
        rad = np.maximum(np.linalg.norm(q, axis=1), 1e-9)
        az = np.degrees(np.arctan2(-q[:, 0], q[:, 1]))
        el = np.degrees(np.arcsin(np.clip(q[:, 2] / rad, -1, 1)))
        fa = (az + 180) / 5.0
        fe = np.clip((el + 90) / 5.0, 0, len(self.el) - 1 - 1e-6)
        ia, ie = np.floor(fa).astype(int), np.floor(fe).astype(int)
        ta, te = fa - ia, fe - ie
        i0, i1 = ia % len(self.az), (ia + 1) % len(self.az)

        def at(g):
            return (g[i0, ie] * (1 - ta) + g[i1, ie] * ta) * (1 - te) + (g[i0, ie + 1] * (1 - ta) + g[i1, ie + 1] * ta) * te

        return (rad - at(self.R)) * at(self.C)

    def dist(self, p):
        b = self.b
        x, y, z = p[:, 0], p[:, 1], p[:, 2]
        d = self.head(p)
        # Below the jaw the head's own function is a flat cap: the neck takes over.
        neck = np.hypot(x, y - b["neck_y"]) - b["neck_r"]
        neck = np.maximum(neck, z - b["neck_top"])
        # The shoulders and back: rounded over from front to back all along, so hair that lands
        # on a shoulder slides forward or back off it and never out along it.
        r = b["half_d"]
        qy, qz = np.abs(y - b["torso_y"]), z - (b["shoulder_z"] - r)
        top = np.hypot(qy, np.maximum(qz, 0)) - r
        torso = np.where(qz > 0, top, qy - r)
        torso = np.maximum(torso, np.abs(x) - b["half_w"])
        return np.minimum(d, np.minimum(neck, torso))

    def normal(self, p):
        e = 1.5e-3
        g = np.stack([self.dist(p + np.array(v) * e) - self.dist(p - np.array(v) * e) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))], axis=1)
        return unit(g)

    def surface(self, az, el):
        """Points of the head's surface along directions (degrees), N×3."""
        d = head_dir(np.asarray(az, float), np.asarray(el, float)).reshape(-1, 3)
        return ORIGIN + d * self.hf.radius(d)[:, None]


class Hair:
    """One person's hair.

    hf: head_form.Head. spec: style, length, parting, fringe, volume, curl, colour, tip, grey,
    silver (the grey hairs' colour), seed. hairline(az) gives the lowest height hair grows at;
    covered(p) > 0 where headwear hides the head; bald(p) > 0 inside a bald crown. `body` moves
    the neck's and shoulders' proxy (Comb).

    Result: v (N×3), f (faces), col (N×3 sRGB), uv (N×2, Blender's v up), nrm (N×3 shading
    normals), and per vertex
    `chain` (-1 for the head, else a spring chain's index) with `along` (metres down that
    chain). `chains` lists each chain's joint positions."""

    def __init__(self, hf, spec, hairline, covered=None, bald=None, body=None):
        self.hf, self.spec, self.hairline = hf, spec, hairline
        self.covered = covered or (lambda p: -1.0)
        self.bald = bald or (lambda p: -1.0)
        self.comb = Comb(hf, body)
        self.rng = random.Random(f"hair/{spec.get('seed', 0)}")
        self.v, self.f, self.col, self.uv, self.nrm, self.chain, self.along = [], [], [], [], [], [], []
        self.chains = []
        self.locks = []
        self.extra = []  # (kind, data) for person.py: ties and bands in cloth
        style = spec["style"]
        if style not in STYLES:
            raise SystemExit(f"hair.style: {style!r} is not one of {STYLES}")
        self.length = float(spec.get("length", 0.07))
        self.parting = float(np.clip(spec.get("parting", 0.0), -1, 1))
        self.fringe = float(np.clip(spec.get("fringe", 0.7), 0, 1.3))
        self.volume = float(np.clip(spec.get("volume", 0.5), 0, 1))
        self.curl = float(np.clip(spec.get("curl", 0.0), 0, 1))
        self.fringe_style = spec.get("fringe_style") or "auto"
        self.brow_z = hf.eye_z + hf.eye_up + hf.brow_up
        self.front_z = float(hairline(0.0))
        getattr(self, "_" + style)()
        self._build()

    # ----------------------------------------------------------------------------- laying out

    def u(self, a, b):
        return self.rng.uniform(a, b)

    def lock(self, az, el, d, length=0.05, z_end=None, width=0.045, lift=0.006, g=30.0, blunt=0.0, tip_out=0.0, bulge=None, target=None, layer=1, chain=-1, taper=2.6,
             shade=0.0, jitter=0.0, thick=1.0, hug=1.0, root=None, even=0.0):
        """One lock: from the scalp at (az, el) (degrees round from the front, + to the
        character's left; degrees up), or from `root`, combed along `d` (a vector, or one of
        `down`, `away`)."""
        p = np.asarray(root, float) if root is not None else self.comb.surface(az, el)[0]
        if root is None and (self.covered(p) > 0 or self.bald(p) > 0):
            return
        if root is None and p[2] < self.hairline(math.degrees(math.atan2(-p[0], p[1]))) - 0.004:
            return
        if isinstance(d, str):
            if d == "down":
                d = DOWN.copy()
            elif d == "away":
                d = p - self.whorl
            else:
                raise ValueError(d)
        d = np.asarray(d, float)
        if jitter:
            d = unit(d) + np.array([self.u(-1, 1), self.u(-1, 1), self.u(-1, 1)]) * jitter
        if z_end is not None and target is None:
            length = min(length, (p[2] - z_end) * 1.25 + 0.05)
        self.locks.append(dict(p=p, d=unit(d), length=length, z_end=-9.0 if z_end is None else z_end, width=width, lift=lift, g=g, blunt=blunt, tip_out=tip_out,
                               bulge=(0.35 + 0.9 * self.volume) * 0.006 if bulge is None else bulge, target=target, layer=layer, chain=chain, taper=taper,
                               tone=self.u(-1, 1), shade=shade, thick=thick, hug=hug, u0=self.u(0, 1), du=self.u(0.16, 0.30), grey=self.rng.random(), even=even))

    @property
    def whorl(self):
        return self.comb.surface(180.0, 64.0)[0]

    def side_line(self):
        """The height hair hangs to at the sides: `length` below the hairline over the ear."""
        return float(self.hairline(100.0)) - self.length

    def part_x(self):
        """Where the parting lies across the head (the character's left at -X)."""
        return -0.040 * self.parting

    # The layers styles are made of. ---------------------------------------------------------

    def under(self, z_end, n=13, width=0.078, back_drop=0.0, g=42.0, blunt=0.3, chain=None, span=(56, 304), el=34.0, taper=2.6, ragged=0.0):
        """The sides and back, hanging from mid-height: az from the temple round the back."""
        for i in range(n):
            az = span[0] + (span[1] - span[0]) * i / (n - 1)
            a = az if az <= 180 else az - 360
            back = smooth((abs(a) - 95) / 60)
            ch = -1 if chain is None else chain(a)
            self.lock(a + self.u(-3, 3), el + self.u(-4, 4), "down", z_end=z_end - back_drop * back + self.u(-0.008, 0.008) + self.u(-0.3, 1.0) * ragged, length=0.9, width=width + self.u(-0.005, 0.006), lift=0.004, g=g,
                      blunt=blunt, layer=0, chain=ch, shade=-0.05, taper=taper)

    def over(self, z_end, n=7, width=0.074, back_drop=0.0, g=30.0, blunt=0.3, chain=None, front=80.0, taper=2.6, lift=0.009, ragged=0.0):
        """From the parting across the top and down over the under layer, on each side, then
        fanning round the crown."""
        px = self.part_x()
        for side in (-1, 1):  # -1: toward the character's left (-X)
            # The wider side of an off-centre parting takes more locks.
            share = 0.5 + 0.5 * side * (px / 0.05) * -1
            m = max(3, round(n * (0.75 + 0.5 * share)))
            for j in range(m):
                t = j / (m - 1)
                phi = math.radians(lerp(front, 128, t))  # from the front over the top to the crown
                d = unit(np.array([px / 0.11 + side * 0.035, math.cos(phi), math.sin(phi)]))
                p = ORIGIN + d * self.hf.radius(d[None, :])[0]
                az, el = math.degrees(math.atan2(-p[0] + ORIGIN[0], p[1] - ORIGIN[1])), math.degrees(math.asin(np.clip((p[2] - ORIGIN[2]) / np.linalg.norm(p - ORIGIN), -1, 1)))
                # Sideways at the front, fanning to straight back behind the crown.
                th = math.radians(lerp(6, 50, smooth((t - 0.45) / 0.55)))
                comb = np.array([side * math.cos(th), -0.22 - math.sin(th), 0.0])
                back = smooth((t - 0.55) / 0.45)
                a_end = 90 + 45 * back
                ch = -1 if chain is None else chain(-side * a_end)
                self.lock(az, el, comb, z_end=z_end - back_drop * back + self.u(-0.010, 0.006) + self.u(-0.3, 1.0) * ragged, length=0.9, width=width + self.u(-0.006, 0.006), lift=lift, g=g, blunt=blunt, layer=1, chain=ch,
                          shade=0.03, taper=taper)

    def crown(self, z_end, n=7, width=0.070, back_drop=0.0, chain=None, blunt=0.3, taper=2.6, g=30.0, ragged=0.0):
        """Round the crown: locks from the whorl fanning down the back, over the others."""
        w = self.whorl
        for i in range(n):
            a = math.radians(-78 + 156 * i / (n - 1))  # 0 straight back
            comb = np.array([-math.sin(a), -math.cos(a), 0.0])
            root = self.comb.surface(180.0 + math.degrees(a) * 0.45, 62.0 - 6 * abs(math.sin(a)))[0]
            az_end = 180 - math.degrees(a) * 0.9
            az_end = az_end if az_end <= 180 else az_end - 360
            self.lock(0, 0, comb, root=root, z_end=z_end - back_drop + self.u(-0.010, 0.006) + self.u(-0.3, 1.0) * ragged, length=0.9, width=width + self.u(-0.006, 0.006), lift=0.009, g=g, blunt=blunt, layer=2,
                      chain=-1 if chain is None else chain(az_end), shade=0.04, taper=taper, bulge=0.003)

    def bangs(self, mode="straight", n=7, reach=1.0, width=0.048, blunt=0.55, span=50.0, g=38.0):
        """The fringe: from the top of the head forward and down over the forehead. `straight`
        to a level line, `swept` to one side, `curtain` parted to the temples."""
        f = self.fringe * reach
        if f <= 0.03:
            return
        if self.fringe_style in ("straight", "swept", "curtain"):
            mode = self.fringe_style
        px = self.part_x()
        z_end = lerp(self.front_z - 0.004, self.brow_z + 0.004, f)
        sweep = 0.0
        if mode == "swept":
            sweep = 1.0 if px <= 0 else -1.0  # away from the parting
            if abs(px) < 0.004:
                sweep = 1.0 if self.rng.random() < 0.5 else -1.0
        for i in range(n):
            t = i / (n - 1) * 2 - 1  # -1 the character's right … 1 the left
            az = t * span
            el = 68 + self.u(-3, 3) - 4 * abs(t)
            if mode == "curtain":
                s = 1.0 if t > 0 else -1.0
                if abs(t) < 0.12:
                    continue
                comb = np.array([-s * (0.55 + 0.5 * abs(t)), 1.0, 0.0])
                ze = z_end - 0.020 * abs(t) - 0.012
                az = t * span * 0.8 + s * 4
            else:
                comb = np.array([sweep * 0.75 + 0.25 * -t * 0.0, 1.0, 0.0])
                # A swept fringe is longest where it ends.
                ze = z_end + (0.010 * abs(t) if mode == "straight" else -0.010 * sweep * -t)
                az = az - sweep * 14
            self.lock(az + self.u(-3, 3), el, comb, z_end=ze + self.u(-0.004, 0.004), length=0.20, width=width + self.u(-0.004, 0.006), lift=0.011, g=g, blunt=blunt, layer=2, shade=0.05, taper=3.2)

    def temples(self, z_end, n=2, width=0.030, chain=None):
        """Locks in front of the ears, to the jaw."""
        for side in (-1, 1):
            for k in range(n):
                az = side * (64 + 9 * k)
                self.lock(az + self.u(-2, 2), 30 + self.u(-3, 3), DOWN + np.array([0, 0.25, 0]), z_end=z_end + 0.02 * (n - 1 - k) + self.u(-0.008, 0.008), length=0.6, width=width, lift=0.006, g=45.0,
                          layer=1, chain=-1 if chain is None else chain(az), taper=2.0)

    def field(self, n, length, width=0.040, jitter=0.25, tip_out=0.0, el_min=-40.0, el_max=88.0, g=22.0, front=None, lift=0.006, blunt=0.0):
        """Short hair all over: roots spread evenly over the scalp, combed away from the crown
        (and across the top from the parting)."""
        px = self.part_x()
        lo, hi = math.sin(math.radians(el_min)), math.sin(math.radians(el_max))
        for i in range(n):
            az = (i * 137.508 + 20) % 360 - 180
            el = math.degrees(math.asin(lerp(hi, lo, (i + 0.5) / n)))
            p = self.comb.surface(az, el)[0]
            d = p - self.whorl
            top = smooth((p[2] - 0.045) / 0.05)
            if front is not None and p[1] > -0.02:
                # On top, combed as the style says (forward, across, or back).
                d = lerp(d, np.asarray(front, float) * 0.1 + np.array([0.06 * (1 if p[0] > px else -1) * (abs(px) > 0.004), 0, 0]), top)
            ln = 1.45 * length * self.u(0.8, 1.25) * (1 - 0.35 * smooth((0.0 - p[2]) / 0.06))
            low = smooth((0.0 - p[2]) / 0.05)  # toward the nape and round the ears it lies flat
            self.lock(az, el, d, length=ln, width=width * self.u(0.85, 1.2), lift=lift, g=g, tip_out=tip_out * self.u(0.4, 1.3) * (1 - 0.85 * low), jitter=jitter * (1 - 0.5 * low), layer=1, blunt=blunt, taper=1.5, thick=0.6, even=1.0,
                      bulge=0.002 + 0.004 * self.volume)

    def gather(self, target, n_edge=16, n_mid=9, width=0.052):
        """Hair drawn back over the scalp to a point (a tail's or a bun's tie)."""
        for i in range(n_edge):
            az = -180 + 360 * (i + 0.5) / n_edge
            z = self.hairline(az) + 0.010
            p = self.point(az, z)
            self.lock(0, 0, target - p, root=p, length=0.5, width=width * self.u(0.9, 1.15), lift=0.004, g=0.0, target=target, layer=0, taper=7.0, bulge=0.002 + 0.004 * self.volume)
        for i in range(n_mid):
            az = -150 + 300 * (i + 0.5) / n_mid
            el = 62 + self.u(-6, 6)
            p = self.comb.surface(az, el)[0]
            self.lock(0, 0, target - p, root=p, length=0.5, width=width * self.u(0.9, 1.2), lift=0.007, g=0.0, target=target, layer=1, taper=7.0, bulge=0.002 + 0.004 * self.volume)

    def point(self, az, z):
        """The head's surface at angle az and height z."""
        return np.asarray(self.hf.point(az, z), float)

    # The styles. ----------------------------------------------------------------------------

    def _crop(self):
        k = self.length / 0.07
        self.field(84, 0.022 * (0.7 + 0.5 * k), width=0.036, jitter=0.18, tip_out=0.002 + 0.004 * self.volume, front=(0, 1, 0), lift=0.004, g=12.0)

    def _short(self):
        k = self.length / 0.07
        self.field(78, 0.040 * (0.7 + 0.4 * k), width=0.044, jitter=0.16, tip_out=0.003 + 0.006 * self.volume, front=(0.9 if self.part_x() <= 0 else -0.9, 0.55, 0), lift=0.006, g=20.0)
        self.bangs("swept", n=6, reach=0.55, width=0.036, blunt=0.2)

    def _tousled(self):
        k = self.length / 0.07
        self.field(78, 0.052 * (0.7 + 0.4 * k), width=0.044, jitter=0.36, tip_out=0.008 + 0.016 * self.volume, front=(0.4 if self.part_x() <= 0 else -0.4, 1, 0), lift=0.007, g=16.0)
        self.bangs("swept", n=7, reach=0.8, width=0.036, blunt=0.15)

    def _swept(self):
        # Combed back from the forehead; the sides back and down; the nape to the collar.
        k = self.length / 0.07
        lean = -1 if self.part_x() > 0 else 1
        for i in range(9):
            t = i / 8 * 2 - 1
            for row, el in enumerate((56, 70)):
                self.lock(t * 56 + self.u(-4, 4), el + self.u(-3, 3) - 6 * abs(t), np.array([0.30 * t + 0.22 * lean, -1.0, 0.0]), length=0.085 * self.u(0.9, 1.15) * (0.8 + 0.3 * k),
                          width=0.050, lift=0.007 + 0.006 * self.volume, g=10.0, layer=2 - row, tip_out=0.002, taper=2.4, bulge=0.003 + 0.006 * self.volume)
        self.field(40, 0.050 * (0.7 + 0.4 * k), width=0.046, jitter=0.15, el_max=58, tip_out=0.003 + 0.004 * self.volume, g=24.0)

    def _shag(self):
        z = self.side_line()
        self.under(z, n=13, blunt=0.0, taper=2.0)
        self.over(z + 0.012, n=7, blunt=0.0, taper=2.0)
        self.crown(z + 0.012, blunt=0.0, taper=2.0)
        self.bangs("swept" if abs(self.parting) > 0.25 else "straight", n=8, blunt=0.15)
        self.temples(z + 0.02, n=1)

    def _bob(self):
        z = self.side_line()
        self.under(z, n=13, blunt=0.5, back_drop=-0.010)
        self.over(z, n=7, blunt=0.5, back_drop=-0.010)
        self.crown(z, blunt=0.5, back_drop=-0.010)
        self.bangs("swept" if abs(self.parting) > 0.45 else "straight", n=7)

    def _bob_parted(self):
        z = self.side_line()
        self.under(z, n=13, blunt=0.4)
        self.over(z, n=7, blunt=0.4, front=74.0)
        self.crown(z, blunt=0.4)
        self.bangs("curtain", n=8)
        self.temples(z + 0.03, n=1)

    def _chains(self, names):
        """Spring chains for hanging hair, by the angle a lock ends at."""
        ids = {}

        def chain(a):
            for name, lo, hi in names:
                if lo <= a < hi:
                    if name not in ids:
                        ids[name] = len(self.chains)
                        self.chains.append(dict(name=name, joints=None))
                    return ids[name]
            return -1

        return chain

    def _long(self):
        z = self.side_line()
        chain = self._chains([("BackL", 95, 150), ("Back", 150, 181), ("Back", -181, -150), ("BackR", -150, -95), ("SideL", 40, 95), ("SideR", -95, -40)])
        drop = 0.03
        # Ends at uneven lengths that thin over their last third, as long hair's do.
        self.under(z, n=13, blunt=0.0, back_drop=drop, chain=chain, taper=1.9, ragged=0.035)
        self.over(z + 0.02, n=8, blunt=0.0, back_drop=drop, chain=chain, taper=1.9, ragged=0.035)
        self.crown(z + 0.01, blunt=0.0, back_drop=drop, chain=chain, taper=1.9, ragged=0.035)
        mode = "curtain" if abs(self.parting) < 0.3 else "swept"
        self.bangs(mode, n=8)
        self.temples(min(z + 0.10, -0.10), n=2)

    def _tail(self):
        g = self.comb.surface(180.0, 30.0 + 22 * self.volume)[0]
        self.gather(g)
        chain = self._chains([("Tail", -400, 400)])
        out = unit(g - np.array([0.0, 0.0, g[2]]))
        tie = g + out * 0.012
        for i in range(6):
            a = 2 * math.pi * i / 6
            off = np.array([math.cos(a) * 0.010, 0.0, math.sin(a) * 0.008])
            self.lock(0, 0, out * 0.8 + DOWN * 0.6 + off * 8, root=tie + off, length=0.9, z_end=g[2] - self.length - 0.10 + self.u(-0.02, 0.02), width=0.040, lift=0.006, g=26.0, layer=3,
                      chain=chain(0), taper=3.0, bulge=0.004)
        self.extra.append(("tie", dict(p=tie, axis=unit(out * 0.8 + DOWN * 0.6), r=0.017)))
        self.bangs("curtain" if abs(self.parting) < 0.3 else "swept", n=7, reach=0.9)
        self.temples(-0.085, n=1, width=0.024)

    def _bun(self):
        g = self.comb.surface(180.0, 36.0 + 26 * self.volume)[0]
        self.gather(g)
        out = unit(g - np.array([0.0, 0.0, g[2] - 0.03]))
        r = 0.034 + 0.016 * min(self.length / 0.11, 1.5) / 1.5
        c = g + out * (r * 0.72)
        self.bun = dict(c=c, out=out, r=r)
        self.bangs("curtain" if abs(self.parting) < 0.3 else "swept", n=7, reach=0.8)
        self.temples(-0.075, n=1, width=0.022)

    def _braid(self):
        g = self.comb.surface(180.0, 2.0)[0]
        self.gather(g, n_mid=11)
        self.braid = [dict(p=g, d=np.array([0.0, -0.5, -1.0]), length=0.16 + self.length * 1.6)]
        self.bangs("curtain" if abs(self.parting) < 0.3 else "swept", n=7, reach=0.9)
        self.temples(-0.085, n=1, width=0.024)

    def _braids(self):
        # Two braids from behind the ears, the hair parted down the middle and drawn to each.
        self.braid = []
        for side in (-1, 1):
            g = self.comb.surface(side * 118.0, -8.0)[0]
            for i in range(9):
                az = side * (8 + 172 * (i + 0.5) / 9)
                z = self.hairline(az) + 0.010
                p = self.point(az, z)
                self.lock(0, 0, g - p, root=p, length=0.5, width=0.052, lift=0.004, g=0.0, target=g, layer=0, taper=7.0, bulge=0.003)
            for i in range(6):
                az = side * (10 + 160 * (i + 0.5) / 6)
                p = self.comb.surface(az, 64 + self.u(-5, 5))[0]
                self.lock(0, 0, g - p, root=p, length=0.5, width=0.056, lift=0.007, g=0.0, target=g, layer=1, taper=7.0, bulge=0.003)
            self.braid.append(dict(p=g, d=np.array([side * 0.05, 0.45, -1.0]), length=0.10 + self.length * 1.3))
        self.bangs("straight", n=7, reach=0.9)

    def _sides(self):
        # What shows under a cap: the sides and the back, short.
        k = self.length / 0.07
        self.field(64, 0.040 * (0.7 + 0.4 * k), width=0.042, jitter=0.15, el_max=40, tip_out=0.003, g=26.0)

    def _kerchief(self):
        # Under a headscarf: a parted fringe and the temples.
        self.bangs("curtain", n=8, reach=1.0)
        self.temples(-0.080, n=2)

    def _balding(self):
        k = self.length / 0.07
        self.field(74, 0.036 * (0.7 + 0.4 * k), width=0.042, jitter=0.2, el_max=60, tip_out=0.003 + 0.004 * self.volume, g=26.0)

    # ------------------------------------------------------------------------------- combing

    def _walk(self):
        """Walk every lock from its root. Returns each lock's path (K×3) and, per point, whether
        it lies on something."""
        L = self.locks
        n = len(L)
        if n == 0:
            return [], []
        ds = 0.006
        P = np.array([k["p"] for k in L])
        nrm = self.comb.normal(P)
        D = np.array([k["d"] for k in L])
        D = unit(D - nrm * np.sum(D * nrm, axis=1, keepdims=True))  # along the scalp to start with
        lift = np.array([k["lift"] for k in L])
        g = np.array([k["g"] for k in L])
        hug = np.array([k["hug"] for k in L])
        has_t = np.array([k["target"] is not None for k in L])
        T = np.array([k["target"] if k["target"] is not None else (0, 0, 0) for k in L], float)
        max_len = np.array([k["length"] for k in L])
        z_end = np.array([k["z_end"] for k in L])
        steps = int(min(max(max_len.max(), 0.02), 0.95) / ds) + 2
        # The root itself sits in the scalp; the lock rises to its lift over the first steps.
        pts = [P.copy()]
        touch = [np.ones(n, bool)]
        done = np.zeros(n, bool)
        end = np.full(n, steps)
        for s in range(1, steps + 1):
            want = lift * smooth(s * ds / 0.02)
            D = D + DOWN * (g * ds)[:, None]
            if has_t.any():
                to = unit(T - P)
                D = np.where(has_t[:, None], unit(D) * 0.45 + to * 0.55, D)
            D = unit(D)
            Q = P + D * ds
            for _ in range(2):
                d = self.comb.dist(Q)
                nq = self.comb.normal(Q)
                Q = Q + nq * np.maximum(want - d, 0)[:, None]
            d = self.comb.dist(Q)
            on = d < want + 0.004
            # Hair lying on the head follows it: no direction into the surface is kept.
            into = np.minimum(np.sum(D * nq, axis=1), 0) * on * hug
            D = unit(D - nq * into[:, None])
            Q = np.where(done[:, None], P, Q)
            P = Q
            pts.append(P.copy())
            touch.append(on)
            reached = (s * ds >= max_len) | (P[:, 2] <= z_end) | (has_t & (np.linalg.norm(T - P, axis=1) < 0.012))
            end = np.where(reached & ~done, s, end)
            done |= reached
            if done.all():
                break
        pts = np.stack(pts, axis=1)
        touch = np.stack(touch, axis=1)
        return [pts[i, : end[i] + 1] for i in range(n)], [touch[i, : end[i] + 1] for i in range(n)]

    @staticmethod
    def _resample(path, flags, n):
        seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)])
        if s[-1] < 1e-6:
            return np.repeat(path[:1], n + 1, axis=0), np.ones(n + 1, bool), np.zeros(n + 1)
        t = np.linspace(0, s[-1], n + 1)
        out = np.stack([np.interp(t, s, path[:, k]) for k in range(3)], axis=1)
        fl = np.interp(t, s, flags.astype(float)) > 0.5
        return out, fl, t

    # ------------------------------------------------------------------------------- ribbons

    def _build(self):
        paths, touches = self._walk()
        spec = self.spec
        base, tipc, silver = np.array(spec["colour"]), np.array(spec["tip"]), np.array(spec["silver"])
        grey = float(spec.get("grey", 0.0))
        chain_pts = {}
        for k, path, touch in zip(self.locks, paths, touches):
            total = float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
            if total < 0.012:
                continue
            seg = 0.022 - 0.008 * self.curl
            n = int(np.clip(round(total / seg), 3, 22))
            pts, on, s = self._resample(path, touch, n)
            pts = self._wave(pts, on, s, k)
            col = self._lock_colour(k, base, tipc, silver, grey)
            first = len(self.v)
            self._ribbon(pts, on, s, k, col)
            if k["chain"] >= 0:
                # Free from where it last touches the head.
                head_on = on & (pts[:, 2] > -0.11)
                free_from = s[np.nonzero(head_on)[0].max()] if head_on.any() else 0.0
                chain_pts.setdefault(k["chain"], []).append((pts, s, free_from, first, len(self.v)))
        self._springs(chain_pts)
        if hasattr(self, "bun"):
            self._bun_mesh(base, tipc, silver, grey)
        for b in getattr(self, "braid", []):
            self._braid_mesh(b, base, tipc, silver, grey)
        self.v = np.array(self.v).reshape(-1, 3)
        self.col = np.clip(np.array(self.col).reshape(-1, 3), 0, 1)
        self.uv = np.array(self.uv).reshape(-1, 2)
        self.nrm = np.array(self.nrm).reshape(-1, 3)
        self.chain = np.array(self.chain, int)
        self.along = np.array(self.along, float)

    def _lock_colour(self, k, base, tipc, silver, grey):
        """A lock's own colour: a tone of the hair's, or one of the grey hairs."""
        c = base * (1 + 0.10 * k["tone"] + k["shade"])
        t = tipc * (1 + 0.10 * k["tone"] + k["shade"])
        if grey > 0.02:
            # Greying goes lock by lock before it goes all over.
            share = smooth((grey - 0.15) / 0.75)
            mixk = np.clip(0.75 * grey + (0.9 if k["grey"] < share else 0.0), 0, 1) if grey < 0.95 else 1.0
            c, t = lerp(c, silver * (1 + 0.06 * k["tone"]), mixk), lerp(t, silver * 1.05, mixk)
        return c, t

    def _wave(self, pts, on, s, k):
        """Curl: waves across the lock's path, growing from the root, tighter with more curl."""
        c = self.curl
        if c < 0.04 or len(pts) < 4:
            return pts
        total = s[-1]
        amp = (0.004 + 0.012 * c) * min(total / 0.08, 1.0)
        freq = 2 * math.pi / lerp(0.11, 0.045, c)
        ph = k["u0"] * 6.28
        tan = unit(np.gradient(pts, axis=0))
        ref = unit(pts - np.array([0.0, -0.01, 0.0]) * np.array([1, 1, 0]))
        ref[:, 2] = 0
        side = unit(np.cross(tan, unit(ref + 1e-6)))
        out = np.cross(side, tan)
        ramp = smooth(s / max(0.35 * total, 1e-6))[:, None] * np.where(on, 0.45, 1.0)[:, None]
        return pts + (side * np.sin(freq * s + ph)[:, None] + out * (0.5 * np.cos(freq * s + ph) + 0.5)[:, None] * 0.6) * amp * ramp

    def _frame(self, pts, on):
        """Along a path: tangent, the direction off what it lies on, and across."""
        tan = unit(np.gradient(pts, axis=0))
        d = self.comb.dist(pts)
        nrm = self.comb.normal(pts)
        axis = pts - np.array([0.0, self.comb.b["neck_y"], 0.0])
        axis[:, 2] = 0
        radial = unit(axis + 1e-9)
        # Off the head's own surface while on or over it; below the jaw, where hair hangs clear
        # of everything, straight out from the neck's axis (steadier than the nearest surface).
        w = (smooth((d - 0.012) / 0.03) * smooth((self.comb.b["neck_top"] + 0.03 - pts[:, 2]) / 0.03))[:, None]
        out = unit(nrm * (1 - w) + radial * w)
        side = unit(np.cross(tan, out))
        out = np.cross(side, tan)
        return tan, out, side

    def _ribbon(self, pts, on, s, k, col, chain=None):
        """A lens-shaped ribbon along a path: five vertices across the front, one behind."""
        n = len(pts) - 1
        total = max(s[-1], 1e-6)
        t = s / total
        tan, out, side = self._frame(pts, on)
        w0 = k["width"]
        blunt = k["blunt"]
        # Narrow at the root, full by a fifth of the way, then tapering to the tip (or to a cut).
        w = w0 * (0.55 + 0.45 * smooth(t / 0.22)) * np.maximum(1 - (1 - blunt) * t ** k["taper"], 0.0)
        th = ((0.085 + 0.07 * self.volume) * w * k["thick"] + 0.0008) * smooth(t / 0.10 + 0.15)
        rise = k["bulge"] * np.sin(np.pi * np.minimum(t * 1.15, 1.0)) + k["tip_out"] * t * t
        base, tipc = col
        across = (-1.0, -0.5, 0.0, 0.5, 1.0)
        profile = (0.0, 0.78, 1.0, 0.78, 0.0)  # a flat front with turned edges, as a comb leaves a lock
        u0, du = k["u0"], k["du"]
        chain_id = k["chain"] if chain is None else chain
        rings = n if blunt <= 0 else n + 1
        for i in range(rings):
            c = pts[i] + out[i] * rise[i]
            even = k.get("even", 0.0)
            shade = lerp(lerp(0.74, 0.92, even), 1.0, smooth(t[i] / 0.25))
            cc = lerp(base, tipc, smooth((t[i] - 0.35) / 0.65) * (1 - 0.8 * even)) * shade / TEX_MEAN
            for a, h in zip(across, profile):
                self.v.append(c + side[i] * (w[i] / 2 * a) + out[i] * (th[i] * h))
                self.col.append(cc * (1 - 0.22 * abs(a) ** 3))
                self.uv.append((u0 + du * (a + 1) / 2, 1 - t[i]))
                # Shaded as part of the whole head of hair, turning only a little across the lock.
                self.nrm.append(unit(out[i] + side[i] * (0.42 * a)))
            self.v.append(c - out[i] * th[i] * 0.35)
            self.col.append(cc * 0.55)
            self.uv.append((u0 + du * 0.5, 1 - t[i]))
            self.nrm.append(-out[i])
            self.chain += [chain_id] * 6
            self.along += [s[i]] * 6
        nr = 6
        v0 = len(self.v) - rings * nr
        # A broad lock on the head bends across to follow it, as combed hair lies: each vertex
        # is moved to its own height over whatever the lock's middle lies on.
        if self._frame.__func__ is Hair._frame if hasattr(self._frame, "__func__") else False:
            mid_d = self.comb.dist(pts[:rings] + out[:rings] * rise[:rings, None])
            near = smooth((0.030 - mid_d) / 0.020)
            if near.max() > 0.01:
                V = np.array(self.v[v0 : v0 + rings * nr])
                want = np.repeat(mid_d, nr) + np.repeat(th[:rings], nr) * np.tile(np.array(profile + (-0.35,)), rings)
                wgt = np.repeat(near, nr)
                for _ in range(2):
                    V = V - self.comb.normal(V) * ((self.comb.dist(V) - want) * wgt)[:, None]
                for q in range(len(V)):
                    self.v[v0 + q] = V[q]
        for i in range(rings - 1):
            a, b = v0 + nr * i, v0 + nr * (i + 1)
            for j in range(nr):
                self.f.append((a + j, a + (j + 1) % nr, b + (j + 1) % nr, b + j))
        # The tip: a point, or a cut end closed with a fan.
        last = v0 + nr * (rings - 1)
        tip = len(self.v)
        end = pts[n] + out[n] * rise[n] + (tan[n] * 0.004 if blunt > 0 else 0)
        self.v.append(end)
        self.col.append(lerp(tipc, base, 0.8 * k.get("even", 0.0)) / TEX_MEAN * (0.9 if blunt > 0 else 1.0))
        self.uv.append((u0 + du * 0.5, 0.0))
        self.nrm.append(unit(out[n] + tan[n] * 0.3))
        self.chain.append(chain_id)
        self.along.append(s[n])
        for j in range(nr):
            self.f.append((last + j, last + (j + 1) % nr, tip))
        # The root is closed too, so the lock is one solid shape for outlines.
        root = len(self.v)
        self.v.append(pts[0] - out[0] * 0.002)
        self.col.append(lerp(base, tipc, 0.0) * 0.6 / TEX_MEAN)
        self.uv.append((u0 + du * 0.5, 1.0))
        self.nrm.append(out[0])
        self.chain.append(chain_id)
        self.along.append(0.0)
        for j in range(nr):
            self.f.append((v0 + (j + 1) % nr, v0 + j, root))

    # --------------------------------------------------------------------- springs, bun, braid

    def _springs(self, chain_pts):
        """Each chain's joints: where its locks leave the head, then every 9 cm down their mean
        path. Vertices record how far down the chain they are (`along`, from the first joint)."""
        for ci, locks in chain_pts.items():
            free = [f for _, _, f, _, _ in locks]
            lengths = [s[-1] - f for (_, s, f, _, _) in locks]
            reach = float(np.median(lengths))
            if reach < 0.06:
                for _, _, _, a, b in locks:
                    for i in range(a, b):
                        self.chain[i] = -1
                continue
            m = int(np.clip(round(reach / 0.09), 1, 4))
            joints = []
            for j in range(m + 1):
                at = reach * j / m
                ps = []
                for pts, s, f, _, _ in locks:
                    q = min(f + at, s[-1])
                    ps.append([np.interp(q, s, pts[:, k]) for k in range(3)])
                joints.append(np.mean(ps, axis=0))
            self.chains[ci]["joints"] = joints
            self.chains[ci]["step"] = reach / m
            for (pts, s, f, a, b) in locks:
                for i in range(a, b):
                    self.along[i] = self.along[i] - f
        for c in self.chains:
            if c["joints"] is None:
                c["joints"] = []

    def _bun_mesh(self, base, tipc, silver, grey):
        """A bun: locks wound round a ball on the back of the head."""
        b = self.bun
        c, out, r = b["c"], b["out"], b["r"]
        e1 = unit(np.cross(out, [0.0, 0.0, 1.0]))
        e2 = np.cross(out, e1)
        n = 8
        for i in range(n):
            a0 = 2 * math.pi * i / n + self.u(-0.1, 0.1)
            k = dict(width=r * 1.05, blunt=0.0, taper=3.0, thick=0.8, bulge=0.0, tip_out=0.0, tone=self.u(-1, 1), shade=0.02, u0=self.u(0, 1), du=self.u(0.16, 0.3), grey=self.rng.random(), chain=-1)
            m = 9
            pts = []
            for j in range(m + 1):
                t = j / m
                # A spiral from near the head, round the ball, toward its outer pole.
                a = a0 + 2.3 * t
                lat = lerp(-0.55, 1.25, t)
                pts.append(c + (e1 * math.cos(a) + e2 * math.sin(a)) * (r * math.cos(lat)) + out * (r * math.sin(lat) * 0.85))
            pts = np.array(pts)
            s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
            self._ribbon_about(pts, s, k, self._lock_colour(k, base, tipc, silver, grey), c)

    def _ribbon_about(self, pts, s, k, col, centre):
        """A ribbon whose outward side looks away from a centre (a bun, a braid's knuckles)."""
        keep = self._frame

        def frame(p, on):
            tan = unit(np.gradient(p, axis=0))
            out = unit(p - centre)
            side = unit(np.cross(tan, out))
            return tan, np.cross(side, tan), side

        self._frame = frame
        try:
            self._ribbon(pts, np.zeros(len(pts), bool), s, k, col)
        finally:
            self._frame = keep

    def _braid_mesh(self, b, base, tipc, silver, grey):
        """A braid: the path hangs like any lock, and along it short fat leaves cross from side
        to side. It gets a spring chain of its own."""
        keep = self.locks
        self.locks = []
        self.lock(0, 0, b["d"], root=b["p"], length=b["length"], width=0.03, lift=0.016, g=30.0)
        (path,), (touch,) = self._walk()
        self.locks = keep
        n = max(4, int(b["length"] / 0.012))
        pts, on, s = self._resample(path, touch, n)
        tan, out, side = self._frame(pts, on)
        ci = len(self.chains)
        m = int(np.clip(round(s[-1] / 0.09), 1, 4))
        self.chains.append(dict(name=f"Braid{ci}", joints=[np.array([np.interp(s[-1] * j / m, s, pts[:, q]) for q in range(3)]) for j in range(m + 1)], step=s[-1] / m))
        pitch = 0.022
        count = int(s[-1] / pitch)
        for i in range(count):
            at = i * pitch
            t = at / s[-1]
            thick = 0.030 * (1 - 0.40 * t)
            sgn = 1 if i % 2 == 0 else -1
            c0 = np.array([np.interp(at, s, pts[:, q]) for q in range(3)])
            j = min(int(t * n), n - 1)
            T, O, S = tan[j], out[j], side[j]
            leaf = []
            for q in range(6):
                f = q / 5
                # From the far side, over the front, down to the near side further along.
                leaf.append(c0 + S * (sgn * thick * 0.62 * math.cos(math.pi * f)) + T * (pitch * 2.1 * f) + O * (thick * 0.50 * math.sin(math.pi * f)))
            leaf = np.array(leaf)
            ls = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(leaf, axis=0), axis=1))])
            k = dict(width=thick * 1.9, blunt=0.0, taper=2.4, thick=1.5, bulge=0.0, tip_out=0.0, tone=self.u(-1, 1), shade=0.0, u0=self.u(0, 1), du=self.u(0.16, 0.3), grey=self.rng.random(), chain=ci)
            a = len(self.v)
            self._ribbon_about(leaf, ls, k, self._lock_colour(k, base, tipc, silver, grey), c0 - O * thick * 0.4 + T * pitch)
            for q in range(a, len(self.v)):
                self.along[q] = at + pitch
        # The end: a tie and a tuft.
        end = pts[-1]
        self.extra.append(("tie", dict(p=np.array([np.interp(s[-1] - 0.012, s, pts[:, q]) for q in range(3)]), axis=tan[-1], r=0.011, chain=ci, along=s[-1])))
        for q in range(3):
            k = dict(width=0.020, blunt=0.0, taper=1.6, thick=1.0, bulge=0.0, tip_out=0.0, tone=self.u(-1, 1), shade=0.0, u0=self.u(0, 1), du=0.2, grey=self.rng.random(), chain=ci)
            d = unit(tan[-1] + side[-1] * (q - 1) * 0.35 + out[-1] * 0.1)
            tuft = np.array([end + d * 0.011 * z for z in range(5)])
            a = len(self.v)
            self._ribbon_about(tuft, np.arange(5) * 0.011, k, self._lock_colour(k, base, tipc, silver, grey), end - out[-1] * 0.03)
            for z in range(a, len(self.v)):
                self.along[z] = s[-1]
