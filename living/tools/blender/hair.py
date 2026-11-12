"""Hair as sheets: a cap on the scalp and, over it, a few broad smooth sheets that end in points,
with a lock here and there. numpy only (no Blender); person.py turns the result into the `Hair`
object.

The reference draws hair as broad smooth shapes that end in a few points. Until pass 3's sheets
step this file made a head of hair from about fifty separate locks, each a ribbon with a tone and
a wave of its own; that read as many waved ribbons, hid the face from the side and left skin
between them. Now:

- **A sheet** (`sheet`) is one surface from a line of roots on the scalp: every root is combed
  as a lock used to be (walked in small steps, bending to the ground, pushed out of the head,
  the neck and the shoulders), and the walked paths are the sheet's columns. Its hem is cut into
  a few points: columns run long at a point's tip and are cut back at the notch between two.
  It is closed by a back surface a few millimetres behind, so it is one solid shape for outlines.
- **A head of hair is a few sheets.** Hanging styles: one curtain round the sides and back, a
  sheet a side from the parting over it, one from the crown, the fringe, a small one at each
  temple. Short styles: rings of short sheets, one over the next as tiles lie, each cut into
  points. Gathered styles: the scalp's hair as sheets drawn to the tie, and the tail a sheet
  rolled into a tube.
- **It is shaded and coloured as one thing:** normals half the sheet's own and half the way out
  from the head; one colour, darker at the root, in the notches and at a sheet's own edges,
  with a lighter band round the head; curl waves the whole head together, by height.
- **Locks remain** where a single one is the drawing: the locks at the ears' front, sideburns,
  a bun's coils, a braid's leaves.
- Every sheet and lock is mapped root to tip onto one tall grey picture of fine streaks
  (`paint_strands`), tinted by the hair's colour; long hair hangs from chains of spring bones.

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
RING_TILT, RING_FROM = 1.25, 0.115  # the shape the hair is shaded as: its normals lean up from RING_FROM below the top of the head
HEM_DARK = 0.22  # how much darker a sheet's ends are drawn


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

    def back_y(self, z):
        """Where the back's surface is at a height: y behind the body's axis."""
        b = self.b
        if "back" in b:
            return b["torso_y"] - np.interp(z, b["back"][0], b["back"][1])
        return b["torso_y"] - b["half_d"] + 0 * np.asarray(z, float)

    def dist(self, p):
        b = self.b
        x, y, z = p[:, 0], p[:, 1], p[:, 2]
        d = self.head(p)
        # Below the jaw the head's own function is a flat cap: the neck takes over, or the
        # garment's collar round it (`collar`: heights and radii, a cone that stands up to its top).
        if "collar" in b:
            cz, cr = b["collar"]
            neck = np.hypot(x, y - b["neck_y"]) - np.interp(z, cz, cr)
            neck = np.maximum(neck, z - cz[-1])
        else:
            neck = np.hypot(x, y - b["neck_y"]) - b["neck_r"]
            neck = np.maximum(neck, z - b["neck_top"])
        # The shoulders and back: rounded over from front to back all along, so hair that lands
        # on a shoulder slides forward or back off it and never out along it.
        r = b["half_d"]
        qy, qz = np.abs(y - b["torso_y"]), z - (b["shoulder_z"] - r)
        top = np.hypot(qy, np.maximum(qz, 0)) - r
        if "back" in b:
            # Below the shoulders the back is the garment's own: as deep as it is at each height
            # and round from side to side, not a flat slab as deep as its deepest.
            sy = y - b["torso_y"]
            deep = np.where(sy < 0, np.interp(z, b["back"][0], b["back"][1]), r)
            body = (np.hypot(x / b["half_w"], sy / deep) - 1.0) * np.minimum(b["half_w"], deep)
            torso = np.where(qz > 0, np.maximum(top, np.abs(x) - b["half_w"]), body)
        else:
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
    the neck's and shoulders' proxy (Comb). `detail` below 1 makes the far model's hair.

    Result: v (N×3), f (faces), col (N×3 sRGB), uv (N×2, Blender's v up), nrm (N×3 shading
    normals), and per vertex
    `chain` (-1 for the head, else a spring chain's index) with `along` (metres down that
    chain). `chains` lists each chain's joint positions."""

    def __init__(self, hf, spec, hairline, covered=None, bald=None, body=None, detail=1.0):
        self.hf, self.spec, self.hairline = hf, spec, hairline
        # 1 the full model; less for the far model: the same locks on the same paths, with
        # longer steps along them and three vertices across in place of six.
        self.detail = float(detail)
        self.covered = covered or (lambda p: -1.0)
        self.bald = bald or (lambda p: -1.0)
        self.comb = Comb(hf, body)
        self.rng = random.Random(f"hair/{spec.get('seed', 0)}")
        self.v, self.f, self.col, self.uv, self.nrm, self.chain, self.along = [], [], [], [], [], [], []
        self.chains = []
        self.locks = []
        self.sheets = []  # sheets' own records; their columns are walked with the locks
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

    # Sheets. --------------------------------------------------------------------------------

    def _teeth(self, points, uneven, closed, cols, edges, sharp=0.36):
        """Where a sheet's columns lie across it (0..1), how far each is cut back at the hem (0 a
        point's tip, 1 the notch between two points) and which point it belongs to. The far
        model keeps each point's notch and tip and drops the columns between."""
        if points <= 0:
            n = max(int(round(cols * (1.0 if self.detail >= 1 else 0.6))), 4)
            return [(i / (n if closed else n - 1), 0.0, 0) for i in range(n)]
        w = [1 + self.u(-uneven, uneven) for _ in range(points)]
        tot = sum(w)
        notch = [self.u(0.65, 1.0) for _ in range(points + 1)]
        if closed:
            notch[-1] = notch[0]
        else:
            notch[0], notch[-1] = edges
        nodes, a = [], 0.0
        for q, wi in enumerate(w):
            b = a + wi / tot
            c = a + (b - a) * self.u(0.36, 0.64)
            tip = self.u(0.0, 0.28)
            nodes.append((a, notch[q], q))
            if self.detail >= 1:
                nodes.append(((a + c) / 2, lerp(tip, notch[q], sharp), q))
            nodes.append((c, tip, q))
            if self.detail >= 1:
                nodes.append(((c + b) / 2, lerp(tip, notch[q + 1], sharp), q))
            a = b
        if not closed:
            nodes.append((1.0, notch[-1], points - 1))
        return nodes

    def sheet(self, roots, dirs="down", z_end=None, length=0.9, points=3, depth=0.03, cols=9, hem=None, lift=0.006, g=30.0, chain=None, shade=0.0, bulge=None, tip_out=0.0,
              target=None, thick=0.0045, closed=False, uneven=0.25, edges=(1.0, 1.0), hug=1.0, check=False, groove=1.0, tube=False, splay=0.0, even=0.0, off=0.0, gather=0.0, over_top=False, sharp=0.36):
        """A sheet of hair: one smooth surface from a line of roots on the scalp (`roots`, a
        polyline; `closed` when it runs all the way round), combed along `dirs` (one vector, one
        a root, `down` or `away`), ending in `points` points `depth` deep. It hangs to `z_end`
        (plus `hem(u)`, u 0..1 across the sheet) or is `length` long (a number or a function of
        u). `off` stands it that far out from where it was combed, for a sheet that lies over
        another. `gather` draws it in behind the shoulders as it hangs (long hair). `check` leaves
        out the stretches whose roots are bare, bald or covered."""
        roots = np.asarray(roots, float).reshape(-1, 3)
        ring = np.vstack([roots, roots[:1]]) if closed else roots
        cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(ring, axis=0), axis=1))])
        W = float(cum[-1])
        at = lambda arr, u: np.array([np.interp((u % 1.0 if closed else u) * W, cum, arr[:, q]) for q in range(3)])
        dv = None
        if not isinstance(dirs, str):
            dv = np.asarray(dirs, float)
            dv = np.repeat(dv[None, :], len(ring), axis=0) if dv.ndim == 1 else (np.vstack([dv, dv[:1]]) if closed else dv)
        nodes = self._teeth(points, uneven, closed, cols, edges, sharp)
        jit = [np.array([self.u(-1, 1), self.u(-1, 1), self.u(-1, 1)]) for _ in range(max(points, 1))]
        tone = [(self.u(-1, 1), self.rng.random()) for _ in range(max(points, 1))]
        u0, phase = self.u(0, 1), self.u(0, 6.28)
        made = []
        for u, k, q in nodes:
            pt = at(ring, u)
            ok = not check or not (self.covered(pt) > 0 or self.bald(pt) > 0 or pt[2] < self.hairline(math.degrees(math.atan2(-pt[0], pt[1]))) - 0.004)
            made.append((u, k, q, pt, ok))
        runs, cur = [], []
        for c in made:
            if c[4]:
                cur.append(c)
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        whole = len(runs) == 1 and len(runs[0]) == len(made)
        if closed and not whole and len(runs) > 1 and made[0][4] and made[-1][4]:
            runs[0] = [(c[0] - 1.0,) + c[1:] for c in runs.pop()] + runs[0]  # the stretch across the seam
        for run in runs:
            if len(run) < 3:
                continue
            sid = len(self.sheets)
            loop = closed and whole
            self.sheets.append(dict(u=[c[0] for c in run], k=[c[1] for c in run], q=[c[2] for c in run], W=W * (1.0 if loop else run[-1][0] - run[0][0]), loop=loop, thick=thick, shade=shade,
                                    groove=groove, tube=tube, u0=u0, phase=phase, tone=tone, even=even, off=off, hang=gather > 0, top=over_top and closed))
            for j, (u, k, q, pt, _) in enumerate(run):
                if dv is None:
                    d = DOWN.copy() if dirs == "down" else pt - self.whorl
                else:
                    d = at(dv, u)
                if splay:
                    d = unit(d) + jit[q] * splay
                uu = u % 1.0 if closed else u
                ze = None if z_end is None else z_end + depth * k + (hem(uu) if hem else 0.0)
                ln = (length(uu) if callable(length) else length) - (depth * k if z_end is None else 0.0)
                if ze is not None and target is None and not over_top:  # hanging: no longer than its drop needs
                    ln = min(ln, (pt[2] - ze) * 1.25 + 0.05)
                self.locks.append(dict(p=pt, d=unit(d), length=max(ln, 0.008), z_end=-9.0 if ze is None else ze, width=0.05, lift=lift, g=g, blunt=0.0, tip_out=tip_out,
                                       bulge=(0.35 + 0.9 * self.volume) * 0.006 if bulge is None else bulge, target=target, layer=1, chain=-1 if chain is None else chain(uu), taper=2.6,
                                       tone=0.0, shade=shade, thick=1.0, hug=hug, u0=u0, du=0.2, grey=0.5, even=even, gather=gather, sheet=(sid, j)))

    # The layers styles are made of. ---------------------------------------------------------

    def curtain(self, z_end, points=7, depth=0.028, back_drop=0.0, g=42.0, chain=None, front=72.0, el=34.0, tip_out=0.0, groove=1.0, splay=0.0, gather=0.0, front_end=None):
        """The sides and back as one sheet hanging from mid-height, from in front of one ear
        round the back to the other. Its front edges hang at the ear's front, so from the side
        the face stays clear."""
        az = np.linspace(front, 360.0 - front, 33)
        a = np.where(az <= 180, az, az - 360)
        roots = self.comb.surface(a, np.full(len(a), float(el)))

        def ang(u):
            x = front + (360.0 - 2 * front) * u
            return x if x <= 180 else x - 360

        # `front_end`: the hair in front of the ears stops there (the jaw) and is not as long as
        # the back's. On long hair it could not go behind the shoulder with the rest: it hung in
        # front of it as a thin tail.
        short = (lambda u: 0.0) if front_end is None else (lambda u: (front_end - z_end) * smooth((108 - abs(ang(u))) / 16))
        self.sheet(roots, "down", z_end=z_end, points=points, depth=depth, hem=lambda u: -back_drop * smooth((abs(ang(u)) - 95) / 60) + short(u), lift=0.004, g=g,
                   chain=None if chain is None else (lambda u: chain(ang(u))), shade=-0.05, edges=(0.25, 0.25), tip_out=tip_out, groove=groove, splay=splay, gather=gather)

    def over(self, z_end, points=3, depth=0.03, back_drop=0.0, g=30.0, chain=None, front=70.0, lift=0.009, tip_out=0.0, splay=0.0, gather=0.0, front_end=None, back_th=50.0):
        """From the parting across the top and down over the curtain, one sheet a side, fanning
        round the crown at the back. Its front edge comes down over the temple to the ear's front.
        `back_th`: how far toward straight back its back edge is combed (degrees). At 88 the two
        sides' back edges meet down the middle of the back, as parted hair does: fanned apart,
        the sheet under them shows between as a strip, or a third sheet has to cover it."""
        px = self.part_x()
        for side in (-1, 1):  # -1: toward the character's left (-X)
            # The wider side of an off-centre parting takes more points.
            share = 0.5 + 0.5 * side * (px / 0.05) * -1
            roots, dirs = [], []
            mid = 1.0 if back_th > 80 else 0.0  # the two sides meet down the middle of the back
            for t in np.linspace(0, 1, 13):
                phi = math.radians(lerp(front, 128, t))  # from the front over the top to the crown
                d = unit(np.array([px / 0.11 * (1 - mid * smooth((t - 0.55) / 0.45)) + side * 0.035 * (1 - 0.9 * mid * smooth((t - 0.6) / 0.4)), math.cos(phi), math.sin(phi)]))
                roots.append(ORIGIN + d * self.hf.radius(d[None, :])[0])
                # Sideways at the front, fanning to straight back behind the crown. The front edge
                # starts far enough back that it comes down at the ear's front: rooted further
                # forward, where the skull slopes to the forehead, it slides down over the eye.
                th = math.radians(lerp(4, back_th, smooth((t - 0.45) / 0.55)))
                dirs.append([side * math.cos(th), -0.16 - math.sin(th), 0.0])
            back = lambda u: smooth((u - 0.55) / 0.45)
            short = (lambda u: 0.0) if front_end is None else (lambda u: (front_end - z_end) * smooth((0.34 - u) / 0.16))
            self.sheet(roots, np.array(dirs), z_end=z_end, points=max(2, round(points * (0.75 + 0.5 * share))), depth=depth, hem=lambda u, short=short: -back_drop * back(u) + short(u), lift=lift, g=g,
                       chain=None if chain is None else (lambda u, side=side: chain(-side * (90 + 45 * back(u)))), shade=0.03, edges=(0.15, 0.6), tip_out=tip_out, splay=splay, off=0.005, gather=gather)
        self.temple()

    def temple(self):
        """The temple, between the fringe's edge and the side hair: a small sheet a side from
        the hairline, combed down and back and lying close. It ends at the brow in front and a
        little lower toward the ear, so it closes the skin beside the fringe and stays above
        and behind the eye."""
        for side in (-1, 1):
            az = side * np.linspace(34.0, 74.0, 9)
            roots = np.array([self.point(a, self.hairline(a) + 0.006) for a in az])
            self.sheet(roots, np.array([0.0, -0.55, -1.0]), length=lambda u: lerp(0.040, 0.028, u), points=2, depth=0.008, lift=0.004, g=30.0, shade=-0.03, edges=(0.6, 0.3), thick=0.003,
                       bulge=0.001, check=True)

    def bangs(self, mode="straight", points=6, reach=1.0, depth=0.009, span=60.0, g=38.0, splay=0.0, tip_out=0.0):
        """The fringe, one sheet from the top of the head forward and down over the forehead:
        `straight` to a level line with longer flanks, `swept` to one side, `curtain` parted to
        the temples (a sheet a side)."""
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
        if mode == "curtain":
            for s in (-1, 1):
                ts = np.linspace(0.10, 1.0, 9)
                roots = self.comb.surface(s * (ts * span * 0.8 + 4), 68 - 4 * ts)
                dirs = np.array([[-s * (0.55 + 1.3 * t * t), 1.0 - 0.5 * t, 0.0] for t in ts])  # the outer part goes to the side of the head, behind the eye
                self.sheet(roots, dirs, z_end=z_end - 0.012, points=max(2, points // 2), depth=depth * 1.6, hem=lambda u: -0.020 * (0.10 + 0.90 * u), lift=0.011, g=g, shade=0.05,
                           edges=(0.9, 0.1), splay=splay, tip_out=tip_out, thick=0.0035, check=True)
            return
        ts = np.linspace(-1, 1, 15)
        roots = self.comb.surface(ts * span - sweep * 14, 68 - 4 * np.abs(ts))
        tt = lambda u: 2 * u - 1
        if mode == "straight":
            # A level line. The flanks stay at the brow: lower, they would hide the eye from the side.
            hem = lambda u: 0.003 * abs(tt(u)) - 0.005 * smooth((abs(tt(u)) - 0.74) / 0.26)
        else:
            hem = lambda u: 0.010 * sweep * tt(u)  # longest where it ends
        dirs = np.stack([sweep * 0.75 - 0.80 * np.sign(ts) * np.abs(ts) ** 2, np.ones(len(ts)), np.zeros(len(ts))], axis=1)  # the flanks fan out to the temples
        self.sheet(roots, dirs, z_end=z_end, points=points, depth=depth, hem=hem, lift=0.011, g=g, shade=0.05, edges=(0.2, 0.2), splay=splay,
                   tip_out=tip_out, thick=0.0035, check=True)

    def sideburns(self, drop):
        """In front of and above the ear, close to the head, `drop` metres long: one small sheet
        a side, where a short style's own points leave skin showing, most on a narrow skull."""
        for side in (-1, 1):
            az = side * np.linspace(54.0, 86.0, 9)
            roots = self.comb.surface(az, np.full(9, 38.0))
            self.sheet(roots, DOWN + np.array([0, 0.12, 0]), length=lambda u: 0.030 + drop * (1.2 - 0.4 * u), points=3, depth=0.010, lift=0.003, g=40.0, shade=-0.03, edges=(0.7, 0.4), thick=0.003,
                       bulge=0.001, check=True)

    def temples(self, z_end, n=2, width=0.030, chain=None):
        """Locks at the ears' front, to the jaw: far enough back that the eye shows from the side."""
        for side in (-1, 1):
            for k in range(n):
                az = side * (72 + 8 * k)
                self.lock(az + self.u(-2, 2), 30 + self.u(-3, 3), DOWN + np.array([0, 0.08, 0]), z_end=z_end + 0.02 * (n - 1 - k) + self.u(-0.008, 0.008), length=0.6, width=width, lift=0.006, g=45.0,
                          layer=1, chain=-1 if chain is None else chain(az), taper=2.0)

    def cap(self, drop=0.006, points=15, depth=0.012, fringe=None, lift=0.006, tip_out=0.0, splay=0.0, g=22.0, raise_hem=0.0, swirl=18.0, shade=0.0, uneven=0.35):
        """Short hair as one sheet: from a small ring round the whorl out over the whole scalp
        to the hairline all round (`drop` past it; at the front, the fringe), its hem cut into
        points. Rings of short sheets laid like tiles read as tiles from behind, each with its own
        edge and outline; one sheet has one hem. `raise_hem` ends it that far above the hairline
        (an upper layer over the first)."""
        n = 20
        ang = np.radians(np.arange(n) * 360.0 / n)
        roots = self.comb.surface(180.0 + 16.0 * np.sin(ang), 64.0 + 7.0 * np.cos(ang))
        away = roots - self.whorl
        # A turn about the crown, as hair grows from a whorl.
        c, s_ = math.cos(math.radians(swirl)), math.sin(math.radians(swirl))
        dirs = np.stack([away[:, 0] * c - away[:, 1] * s_, away[:, 0] * s_ + away[:, 1] * c, away[:, 2]], axis=1)
        az_end = np.degrees(np.arctan2(-dirs[:, 0], dirs[:, 1]))  # where round the head each column comes down
        f = self.fringe if fringe is None else fringe
        brow = lerp(self.front_z - 0.004, self.brow_z + 0.004, f)
        ends = np.array([self.hairline(a) - drop for a in az_end])
        # Over the forehead the hem is the fringe's line.
        front = np.array([smooth((52.0 - abs(a)) / 18.0) for a in az_end])
        ends = ends * (1 - front) + brow * front + raise_hem
        closed = np.append(ends, ends[0])
        cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(np.vstack([roots, roots[:1]]), axis=0), axis=1))])
        hem = lambda u: float(np.interp((u % 1.0) * cum[-1], cum, closed))
        self.sheet(roots, dirs, z_end=0.0, hem=hem, length=0.30, points=points, depth=depth, lift=lift, g=g, closed=True, tip_out=tip_out, splay=splay, thick=0.0040, even=1.0,
                   bulge=0.002 + 0.004 * self.volume, uneven=uneven, shade=shade, over_top=True, sharp=0.5)

    def skirt(self, el=34.0, drop=0.006, points=12, depth=0.012, lift=0.005, tip_out=0.0, splay=0.0, g=26.0):
        """Hair below a line round the head (a bald crown's edge, a cap's): one sheet from a ring
        at that height down to the hairline all round, its hem cut into points. The stretches
        whose roots are bald, covered or below the hairline are left out."""
        az = np.arange(-180.0, 180.0, 10.0)
        roots = self.comb.surface(az, np.full(len(az), float(el)))
        ends = np.array([self.hairline(a) - drop for a in az])
        closed = np.append(ends, ends[0])
        cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(np.vstack([roots, roots[:1]]), axis=0), axis=1))])
        hem = lambda u: float(np.interp((u % 1.0) * cum[-1], cum, closed))
        self.sheet(roots, roots - self.whorl, z_end=0.0, hem=hem, length=0.30, points=points, depth=depth, lift=lift, g=g, closed=True, check=True, tip_out=tip_out, splay=splay, thick=0.0040,
                   even=1.0, bulge=0.002 + 0.004 * self.volume, uneven=0.35, over_top=True)

    def gather(self, target, n_edge=24, n_mid=14):
        """Hair drawn back over the scalp to a point (a tail's or a bun's tie): a sheet from the
        hairline all round, and one over it from the top."""
        az = -180 + 360 * (np.arange(n_edge) + 0.5) / n_edge
        roots = np.array([self.point(a, self.hairline(a) + 0.010) for a in az])
        self.sheet(roots, target - roots, length=0.5, points=0, cols=n_edge, lift=0.004, g=0.0, target=target, closed=True, bulge=0.002 + 0.004 * self.volume, thick=0.0035, groove=0.0)
        az = -150 + 300 * (np.arange(n_mid) + 0.5) / n_mid
        roots = self.comb.surface(az, 62.0 + 0 * az)
        self.sheet(roots, target - roots, length=0.5, points=0, cols=n_mid, lift=0.007, g=0.0, target=target, bulge=0.002 + 0.004 * self.volume, thick=0.0035, groove=0.0)

    def point(self, az, z):
        """The head's surface at angle az and height z."""
        return np.asarray(self.hf.point(az, z), float)

    # The styles. ----------------------------------------------------------------------------

    def _crop(self):
        # Close to the head all over, the hem barely past the hairline.
        self.cap(drop=0.003, points=17, depth=0.007, fringe=0.12 * self.fringe, lift=0.004, tip_out=0.001 + 0.002 * self.volume, g=14.0, splay=0.04)
        self.sideburns(0.018)

    def _short(self):
        k = self.length / 0.07
        lean = 26.0 if self.part_x() <= 0 else -26.0
        self.cap(drop=0.010 * k, points=15, depth=0.016, fringe=0.55 * self.fringe, lift=0.006, tip_out=0.002 + 0.004 * self.volume, g=20.0, splay=0.06, swirl=lean)
        # A shorter layer over the top, for the cut's volume.
        self.cap(raise_hem=0.045, points=9, depth=0.022, fringe=0.2 * self.fringe, lift=0.011, tip_out=0.003 + 0.005 * self.volume, g=18.0, splay=0.08, swirl=lean, shade=0.03)
        self.sideburns(0.026)

    def _tousled(self):
        k = self.length / 0.07
        lean = 30.0 if self.part_x() <= 0 else -30.0
        # Longer and looser: deep points turned out, and a second layer whose points stand up.
        self.cap(drop=0.016 * k, points=13, depth=0.034, fringe=0.8 * self.fringe, lift=0.007, tip_out=0.006 + 0.010 * self.volume, g=16.0, splay=0.16, swirl=lean, uneven=0.45)
        self.cap(raise_hem=0.040, points=8, depth=0.040, fringe=0.3 * self.fringe, lift=0.013, tip_out=0.008 + 0.014 * self.volume, g=14.0, splay=0.13, swirl=lean, shade=0.03, uneven=0.45)
        self.sideburns(0.030)

    def _swept(self):
        # Combed back from the forehead: a cap all over, its hem at the hairline in front, and
        # one sheet from the front hairline back over the top, lying down behind the crown.
        k = self.length / 0.07
        lean = -1 if self.part_x() > 0 else 1
        self.cap(drop=0.014 * k, points=13, depth=0.014, fringe=0.0, lift=0.005, tip_out=0.002 + 0.003 * self.volume, g=22.0, splay=0.05, swirl=-24.0 * lean)
        ts = np.linspace(-1, 1, 11)
        roots = self.comb.surface(ts * 48, 54.0 - 6 * np.abs(ts))
        dirs = np.stack([0.30 * ts + 0.22 * lean, -np.ones(11), np.zeros(11)], axis=1)
        self.sheet(roots, dirs, length=0.115 * (0.8 + 0.3 * k), points=5, depth=0.030, lift=0.006 + 0.005 * self.volume, g=24.0, bulge=0.003 + 0.006 * self.volume, check=True, edges=(0.5, 0.5), off=0.004)

    def _shag(self):
        z = self.side_line()
        self.curtain(z, points=9, depth=0.045, tip_out=0.006, splay=0.05)
        self.over(z + 0.012, points=5, depth=0.045, tip_out=0.006, splay=0.05, back_th=88.0)
        self.bangs("swept" if abs(self.parting) > 0.25 else "straight", points=6, depth=0.016)
        self.temples(z + 0.02, n=1)

    def _bob(self):
        # Cut to one line, the ends turned under.
        z = self.side_line()
        self.curtain(z, points=6, depth=0.010, back_drop=-0.010, tip_out=-0.010)
        self.over(z, points=4, depth=0.010, back_drop=-0.010, tip_out=-0.010, back_th=88.0)
        self.bangs("swept" if abs(self.parting) > 0.45 else "straight", points=6)

    def _bob_parted(self):
        z = self.side_line()
        self.curtain(z, points=6, depth=0.014, tip_out=-0.006)
        self.over(z, points=4, depth=0.014, tip_out=-0.006, back_th=88.0)
        self.bangs("curtain", points=5)
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
        # Broad sheets down the back that end in a few long points.
        # Gathered behind the shoulders, lying close down the back, the ends turned a little in.
        self.curtain(z, points=5, depth=0.060, back_drop=drop, chain=chain, gather=15.0, tip_out=-0.014, front_end=-0.100)
        self.over(z + 0.02, points=4, depth=0.060, back_drop=drop, chain=chain, gather=15.0, tip_out=-0.014, front_end=-0.105, back_th=88.0)
        mode = "curtain" if abs(self.parting) < 0.3 else "swept"
        self.bangs(mode, points=6)
        # The locks at the ears' front stop at the jaw: hanging on to the chest they lay in front of
        # the shoulders as two dark tails.
        self.temples(-0.105, n=2)

    def _tail(self):
        g = self.comb.surface(180.0, 30.0 + 22 * self.volume)[0]
        self.gather(g)
        chain = self._chains([("Tail", -400, 400)])
        out = unit(g - np.array([0.0, 0.0, g[2]]))
        tie = g + out * 0.012
        offs = [np.array([math.cos(2 * math.pi * i / 8) * 0.014, 0.0, math.sin(2 * math.pi * i / 8) * 0.011]) for i in range(8)]
        # The tail: one sheet rolled into a tube, ending in three points.
        self.sheet([tie + o for o in offs], [out * 0.8 + DOWN * 0.6 + o * 6 for o in offs], z_end=g[2] - self.length - 0.10, points=3, depth=0.045, lift=0.006, g=26.0,
                   chain=lambda u: chain(0), closed=True, tube=True, bulge=0.004, thick=0.0040)
        self.extra.append(("tie", dict(p=tie, axis=unit(out * 0.8 + DOWN * 0.6), r=0.017)))
        self.bangs("curtain" if abs(self.parting) < 0.3 else "swept", points=5, reach=0.9)
        self.temples(-0.085, n=1, width=0.024)

    def _bun(self):
        g = self.comb.surface(180.0, 36.0 + 26 * self.volume)[0]
        self.gather(g)
        out = unit(g - np.array([0.0, 0.0, g[2] - 0.03]))
        r = 0.034 + 0.016 * min(self.length / 0.11, 1.5) / 1.5
        c = g + out * (r * 0.72)
        self.bun = dict(c=c, out=out, r=r)
        self.bangs("curtain" if abs(self.parting) < 0.3 else "swept", points=5, reach=0.8)
        self.temples(-0.075, n=1, width=0.022)

    def _braid(self):
        g = self.comb.surface(180.0, 2.0)[0]
        self.gather(g, n_mid=16)
        self.braid = [dict(p=g, d=np.array([0.0, -0.5, -1.0]), length=0.16 + self.length * 1.6)]
        self.bangs("curtain" if abs(self.parting) < 0.3 else "swept", points=5, reach=0.9)
        self.temples(-0.085, n=1, width=0.024)

    def _braids(self):
        # Two braids from behind the ears, the hair parted down the middle and drawn to each.
        self.braid = []
        for side in (-1, 1):
            g = self.comb.surface(side * 118.0, -8.0)[0]
            az = side * (8 + 172 * (np.arange(12) + 0.5) / 12)
            roots = np.array([self.point(a, self.hairline(a) + 0.010) for a in az])
            self.sheet(roots, g - roots, length=0.5, points=0, cols=12, lift=0.004, g=0.0, target=g, bulge=0.003, thick=0.0035, groove=0.0)
            az = side * (10 + 160 * (np.arange(9) + 0.5) / 9)
            roots = self.comb.surface(az, 64.0 + 0 * az)
            self.sheet(roots, g - roots, length=0.5, points=0, cols=9, lift=0.007, g=0.0, target=g, bulge=0.003, thick=0.0035, groove=0.0)
            self.braid.append(dict(p=g, d=np.array([side * 0.05, 0.45, -1.0]), length=0.10 + self.length * 1.3))
        self.bangs("straight", points=6, reach=0.9)

    def _sides(self):
        # What shows under a cap: the sides and the back, short.
        k = self.length / 0.07
        self.skirt(el=38.0, drop=0.008 * k, points=12, depth=0.012, tip_out=0.002, splay=0.05)

    def _kerchief(self):
        # Under a headscarf: a parted fringe and the temples.
        self.bangs("curtain", points=5, reach=1.0)
        self.temples(-0.080, n=2)

    def _balding(self):
        k = self.length / 0.07
        self.skirt(el=52.0, drop=0.008 * k, points=13, depth=0.012, tip_out=0.002 + 0.003 * self.volume, splay=0.06)

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
        gather = np.array([k.get("gather", 0.0) for k in L])
        free_z = self.comb.b["collar"][0][-1] if "collar" in self.comb.b else self.comb.b["neck_top"]
        steps = int(min(max(max_len.max(), 0.02), 0.95) / ds) + 2
        # The root itself sits in the scalp; the lock rises to its lift over the first steps.
        pts = [P.copy()]
        touch = [np.ones(n, bool)]
        done = np.zeros(n, bool)
        end = np.full(n, steps)
        for s in range(1, steps + 1):
            want = lift * smooth(s * ds / 0.02)
            D = D + DOWN * (g * ds)[:, None]
            if gather.any():
                # Long hair is gathered behind the shoulders as it comes down: toward the back's
                # middle, and back to the back's surface if it started in front of it. Left to
                # fall, the side hair landed on the shoulders and spread along them as a cape,
                # and what landed in front of a shoulder kicked forward at the collar.
                low = smooth((free_z + 0.02 - P[:, 2]) / 0.04)
                pull = np.stack([-P[:, 0], np.minimum(self.comb.back_y(P[:, 2]) - P[:, 1], 0.0), np.zeros(n)], axis=1)
                D = D + pull * (gather * low * ds)[:, None]
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
        sheets = {}
        for k, path, touch in zip(self.locks, paths, touches):
            if "sheet" in k:
                sheets.setdefault(k["sheet"][0], []).append((k, path, touch))
                continue
            total = float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
            if total < 0.012:
                continue
            seg = (0.022 - 0.008 * self.curl) / self.detail
            n = int(np.clip(round(total / seg), 3 if self.detail >= 1 else 2, 22))
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
        for sid in sorted(sheets):
            self._sheet_mesh(self.sheets[sid], sheets[sid], base, tipc, silver, grey, chain_pts)
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
        c = base * (1 + 0.04 * k["tone"] + k["shade"])
        t = tipc * (1 + 0.04 * k["tone"] + k["shade"])
        if grey > 0.02:
            # Greying goes lock by lock before it goes all over.
            share = smooth((grey - 0.15) / 0.75)
            if k.get("blend"):  # a sheet's point: every point greys, some a little more
                mixk = np.clip(0.75 * grey + 0.9 * share + 0.16 * (k["grey"] - 0.5) * (1 - share), 0, 1) if grey < 0.95 else 1.0
            else:
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
        ph = 0.6 * k["u0"]  # near enough one phase for the whole head: locks wave together
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
        back = True
        if self.detail < 1:
            # The far model: two edges and a ridge, closed by a flat back.
            across, profile, back = (-1.0, 0.0, 1.0), (0.0, 1.0, 0.0), False
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
            if back:
                self.v.append(c - out[i] * th[i] * 0.35)
                self.col.append(cc * 0.55)
                self.uv.append((u0 + du * 0.5, 1 - t[i]))
                self.nrm.append(-out[i])
            self.chain += [chain_id] * (len(across) + back)
            self.along += [s[i]] * (len(across) + back)
        nr = len(across) + back
        v0 = len(self.v) - rings * nr
        # A broad lock on the head bends across to follow it, as combed hair lies: each vertex
        # is moved to its own height over whatever the lock's middle lies on.
        if self._frame.__func__ is Hair._frame if hasattr(self._frame, "__func__") else False:
            mid_d = self.comb.dist(pts[:rings] + out[:rings] * rise[:rings, None])
            near = smooth((0.030 - mid_d) / 0.020)
            if near.max() > 0.01:
                V = np.array(self.v[v0 : v0 + rings * nr])
                want = np.repeat(mid_d, nr) + np.repeat(th[:rings], nr) * np.tile(np.array(profile + ((-0.35,) if back else ())), rings)
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

    def _sheet_mesh(self, sp, cols, base, tipc, silver, grey, chain_pts):
        """A sheet's mesh from its walked columns: a front surface and a back one a few
        millimetres behind it, closed all round, so it is one solid shape for outlines. Rows run
        across at the same share of each column's length, so the hem is the line through the
        columns' ends: points where columns run long, notches where they are cut back."""
        M = len(cols)
        loop, tube = sp["loop"], sp["tube"]
        Ls = np.array([float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum()) for _, path, _ in cols])
        seg = (0.020 - 0.006 * self.curl) / self.detail
        R = int(np.clip(round(float(np.median(Ls)) / seg), 3 if self.detail >= 1 else 2, 26))
        C, S, ON = np.zeros((M, R + 1, 3)), np.zeros((M, R + 1)), np.zeros((M, R + 1), bool)
        for j, (_, path, touch) in enumerate(cols):
            C[j], ON[j], S[j] = self._resample(path, touch, R)
        T = np.linspace(0.0, 1.0, R + 1)
        OUT, SIDE = np.zeros_like(C), np.zeros_like(C)
        mid = C.mean(axis=0)
        for j in range(M):
            if tube:
                tan = unit(np.gradient(C[j], axis=0))
                side = unit(np.cross(tan, unit(C[j] - mid)))
                OUT[j], SIDE[j] = np.cross(side, tan), side
            else:
                _, OUT[j], SIDE[j] = self._frame(C[j], ON[j])
        u = np.array(sp["u"])
        kk = np.array(sp["k"])
        L = Ls[:, None]
        c = self.curl
        if c >= 0.04 and R >= 3:
            # Curl: the whole sheet waves together, the wave drifting slowly across it.
            amp = (0.002 + 0.009 * c) * np.minimum(L / 0.08, 1.0)
            freq = 2 * math.pi / lerp(0.13, 0.06, c)
            # One wave for the whole head, by height and the way round it, so sheets that lie
            # over one another wave as one and do not cut through each other.
            ph = 1.3 * np.sin(np.arctan2(-C[..., 0], C[..., 1]))
            wave = amp * smooth(S / np.maximum(0.35 * L, 1e-6)) * np.where(ON, 0.4, 1.0)
            C = C + OUT * (wave * np.sin(-freq * C[..., 2] + ph))[..., None] + SIDE * (0.5 * wave * np.cos(-freq * C[..., 2] + ph))[..., None]
        if loop:
            E = np.ones(M)
        else:
            w = (u - u[0]) / max(u[-1] - u[0], 1e-9)
            E = 0.12 + 0.88 * np.clip(np.minimum(w, 1 - w) * sp["W"] / 0.012, 0.0, 1.0) ** 0.6
        k0 = cols[0][0]
        th = sp["thick"] * E[:, None] * (smooth(T / 0.10 + 0.15) * (1 - 0.82 * T ** 3))[None, :]
        # A sheet's volume is over its length; on one that hangs down the back it is over the
        # head only, so the hair lies close below.
        swell = np.sin(np.pi * np.minimum(T / 0.40, 1.0)) if sp.get("hang") else np.sin(np.pi * np.minimum(T * 1.15, 1.0))
        stand = sp["off"] * (smooth(T / 0.25) * (1 - 0.6 * smooth((T - 0.35) / 0.3)) if sp.get("hang") else smooth(T / 0.25))
        rise = np.array([q[0]["bulge"] for q in cols])[:, None] * swell[None, :] + k0["tip_out"] * (T ** 2)[None, :] + stand[None, :]
        F = C + OUT * (rise + th)[..., None]
        B = C + OUT * (rise - 0.35 * th)[..., None]
        # Colour: each point a shade of its own, slight; darker at the root, in the notches
        # between points and at the sheet's own edges; a lighter band round the head.
        cb, ct = np.zeros((M, 3)), np.zeros((M, 3))
        for j in range(M):
            tone, gr = sp["tone"][sp["q"][j]]
            cb[j], ct[j] = self._lock_colour(dict(tone=0.6 * tone, shade=sp["shade"], grey=gr, blend=True), base, tipc, silver, grey)
        even = sp["even"]
        rootshade = lerp(lerp(0.76, 0.92, even), 1.0, smooth(T / 0.22))
        grad = smooth((T - 0.35) / 0.65) * (1 - 0.8 * even)
        groove = 1 - 0.26 * sp["groove"] * (kk ** 1.5)[:, None] * smooth((T - 0.25) / 0.45)[None, :]
        edge = (1 - 0.16 * (1 - (E - 0.12) / 0.88))[:, None]
        # The ends are drawn darker, a line along the hem.
        hemline = (1 - HEM_DARK * smooth((T - 0.80) / 0.14))[None, :]
        col = (cb[:, None, :] * (1 - grad)[None, :, None] + ct[:, None, :] * grad[None, :, None]) * (rootshade[None, :] * groove * edge * hemline)[..., None] / TEX_MEAN
        # Shaded as one head of hair. The normals are those of one smooth shape round the head,
        # the same for every sheet, with a share of the sheet's own facing: a fifth over the
        # head, half where the hair hangs. The client's highlight is a ring where the normal
        # leans up by a given angle, and its shadow's edge is where the normal turns from the
        # sun: on one smooth shape each is one clean line round the head, where sheets' own
        # facings broke them into patches. RING_TILT and RING_FROM set how fast the shape's
        # normals lean up with height, which places the ring.
        P = np.stack([F[..., 0], F[..., 1] + 0.010, RING_TILT * np.maximum(F[..., 2] - (self.hf.top_z - RING_FROM), 0.0)], axis=-1)
        own = (0.2 + 0.3 * smooth((0.02 - F[..., 2]) / 0.06))[..., None]
        N = OUT if tube else unit(own * OUT + (1 - own) * unit(P))
        # Across the picture of strands: a whole number of times round a closed sheet.
        if loop:
            U = sp["u0"] + np.append(u, 1.0) * max(1, round(sp["W"] / 0.22))
        else:
            U = sp["u0"] + (u - u[0]) * sp["W"] / max(u[-1] - u[0], 1e-9) / 0.22
        Mx = M + 1 if loop else M  # a closed sheet's first column again, for the seam in the picture
        nr = 2 * (R + 1)
        v0 = len(self.v)
        for j in range(Mx):
            jj = j % M
            first = len(self.v)
            for i in range(R + 1):
                self.v += [F[jj, i], B[jj, i]]
                self.col += [col[jj, i], col[jj, i] * 0.55]
                self.uv += [(U[j], 1 - T[i]), (U[j], 1 - T[i])]
                self.nrm += [N[jj, i], -OUT[jj, i]]
                self.along += [S[jj, i], S[jj, i]]
            ch = cols[jj][0]["chain"]
            self.chain += [ch] * nr
            if ch >= 0:
                # Free from where it last touches the head.
                head_on = ON[jj] & (C[jj][:, 2] > -0.11)
                free_from = S[jj][np.nonzero(head_on)[0].max()] if head_on.any() else 0.0
                chain_pts.setdefault(ch, []).append((C[jj], S[jj], free_from, first, first + nr))
        at = lambda j, i, back: v0 + j * nr + 2 * i + back
        for j in range(Mx - 1):
            for i in range(R):
                self.f.append((at(j, i, 0), at(j + 1, i, 0), at(j + 1, i + 1, 0), at(j, i + 1, 0)))
                self.f.append((at(j, i, 1), at(j, i + 1, 1), at(j + 1, i + 1, 1), at(j + 1, i, 1)))
            self.f.append((at(j, 0, 0), at(j, 0, 1), at(j + 1, 0, 1), at(j + 1, 0, 0)))
            self.f.append((at(j, R, 0), at(j + 1, R, 0), at(j + 1, R, 1), at(j, R, 1)))
        if loop and sp.get("top"):
            # A sheet that starts as a ring round the whorl is closed over it: a low cone from its
            # second row, which has risen clear of the scalp (the roots lie in it), to a point
            # over the whorl, as high as the skull's own rise inside that row and a little more.
            mid = len(self.v)
            c1 = F[:, 1].mean(axis=0)
            r1 = float(np.linalg.norm(F[:, 1] - c1, axis=1).mean())
            self.v.append(c1 + unit(OUT[:, 0].mean(axis=0)) * (r1 * r1 / 0.19 + 0.005))
            self.col.append(col[:, 1].mean(axis=0))
            self.uv.append((float(np.mean(U)), 1.0))
            self.nrm.append(unit(N[:, 0].mean(axis=0)))
            self.along.append(0.0)
            self.chain.append(-1)
            for j in range(Mx - 1):
                self.f.append((mid, at(j, 1, 0), at(j + 1, 1, 0)))
        if not loop:
            for i in range(R):
                self.f.append((at(0, i, 0), at(0, i + 1, 0), at(0, i + 1, 1), at(0, i, 1)))
                self.f.append((at(Mx - 1, i + 1, 0), at(Mx - 1, i, 0), at(Mx - 1, i, 1), at(Mx - 1, i + 1, 1)))

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
