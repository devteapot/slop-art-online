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

import person_params
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

# char-port-2 S5 (`SLOP_PORT=hair`, docs/char-port-2/s5): hair laid out for the handmade-hair
# profile on the shared hair-mask page (docs/HANDMADE_COMPOSED.md v1.3, "The hair-mask page"):
# every piece (the cap, each sheet, each lock, a bun's coils, a braid's leaves) its own UV island
# by its own lengths at 1 mm a texel, a highlight on the upper hair and lock lines up from the
# notches between a sheet's points. Off unless named; with it off nothing changes.
PORT = {f.strip() for f in __import__("os").environ.get("SLOP_PORT", "").split(",") if f.strip()}
PAGE_HAIR = "hair" in PORT
TEXEL_M = 0.001  # the page's density: 1 mm a texel
PAGE_PX = 4096
INK_RANGE_PX = 6  # the lock lines' range, texels (6 mm: above px x 4.03 mm + a pixel at ink_px 1.05)
ISLAND_PAD_PX = 2 * INK_RANGE_PX + 8  # between islands and from the file's rectangle's edge (the contract's)
CREASE = dict(notch=0.55, clear=INK_RANGE_PX + 3)  # a column cut back this far is a notch; a line starts this many texels in from the hem
# The lock lines, grouped into locks (the plait's lesson: even, parallel, equal stripes read as
# melon stripes, and the fringe's as clips): up each notch, a line a share of the way to the root
# (`notch_len`), bending across by up to `drift` columns as it goes; beside a notch, inside the
# lock, 0 to 2 shorter companions (`mate_len`), started a share of the way from the notch to the
# point's tip (`mate_at`), bending with the notch's line.
LOCK_LINES = dict(notch_len=(0.30, 0.72), drift=1.3, mate_len=(0.16, 0.40), mate_at=(0.30, 0.55), mates=(0, 0, 1, 1))
# The parting (char-port-2 S5's second pass): a pale strip on the page (the highlight's R) where
# the hair parts, `width` across (metres, tapering to its ends), on what lies within `depth` of
# the scalp there. Close up the bands and lines carry the hair; in play the parting does.
PARTING = dict(width=0.010, depth=0.014, from_deg=84.0, curtain_from_deg=70.0, to_deg=122.0)
# The look the second pass gives the bands at play distance. Two were built side by side
# (docs/char-port-2/s5): `b1` turns each lock's normals across it as a low cylinder, so the bands
# break lock by lock; `b2` keeps the bands smooth and has hair_page.py lay main's strands under
# them at low contrast (the page's B, which the client multiplies into the bands). B2 is kept;
# SLOP_HAIR_LOOK=b1 builds the other again.
HAIR_LOOK = __import__("os").environ.get("SLOP_HAIR_LOOK", "b2")
LOCK_ROUND = 0.60  # b1: how far a lock's normals turn across it, at its sides

# char-port-2 S6 (`SLOP_PORT=masters`, docs/char-port-2/s6): hair masters, a cut as a named set of
# parameters in the generator's own terms, never a mesh. `swept_braid` is Cora's cut (char-live-2
# and char-live-3): her rear layers as stations, each a wide lock and on two layers a narrower
# companion, joining a three-strand plait at staggered heights, and the plait itself. Off unless
# named; with it off nothing changes.
MASTERS_ON = "masters" in PORT
# SLOP_MASTER_DROP=hooks,side groups: a master built without those parts (as tagged; the triangle
# budget's names), everything else as it was: the parts' ID control (docs/char-port-2/s6/part_id.py).
MASTER_DROP = {x.strip() for x in __import__("os").environ.get("SLOP_MASTER_DROP", "").split(",") if x.strip()}
MASTERS = dict(swept_braid=dict(
    # The head's measures Cora's were taken in: half her cheek width over her head's height (her
    # fit's cheek_radius .0589 m over head_height .2322 m). Stations are in those units: side
    # distance in half-cheeks, height above the chin in head heights, width in half-cheeks.
    cheek=0.2538,
    # docs/char-live-3/back-hair/fit.py `layers`: per layer, six stations root to join, Catmull-Rom
    # between. Layer 2 starts at the temples (the front opening stays) and joins lowest; the crown
    # layer, 6, joins high. Each runs a side, mirrored, the pair making a descending V.
    layers={
        2: [(1.40, .77, .12), (1.55, .65, .22), (1.42, .48, .26), (.94, .37, .23), (.41, .25, .13), (.06, .18, .025)],
        3: [(1.25, .91, .05), (1.52, .75, .22), (1.40, .65, .34), (.90, .52, .36), (.47, .42, .29), (.04, .32, .02)],
        4: [(.93, .92, .06), (1.25, .83, .28), (1.18, .73, .39), (.86, .64, .34), (.53, .60, .28), (.02, .48, .030)],
        5: [(.79, .92, .03), (.99, .85, .10), (1.14, .79, .16), (1.02, .72, .16), (.80, .68, .12), (.59, .64, .012)],
        6: [(.16, .96, .05), (.41, .93, .30), (.60, .87, .45), (.56, .79, .44), (.39, .72, .36), (.03, .60, .022)],
    },
    part_asymmetry=0.065, side_tuck=(0.035, -0.018),  # Cora's part offset and the sides' tuck
    over=0.011,  # how far the layers lie off the scalp: over the hair mass drawn to the plait
    mass_in=0.0,  # how far inside the plait's start the mass under it is drawn
    volume=0.95,  # the cut's volume (the sheets' swell): Cora's crown lift
    lift=(0.004, 0.0012),  # and each layer's own swell over its length (Cora's)
    companions=(3, 4),  # the layers with a narrower companion beside the wide lock (her secondary folds)
    companion=dict(width=0.45, side=0.22, start=0.14, end=0.09),  # its width, where it lies across, the share of the lock it leaves out
    rings=12,  # sections along a layer's lock
    # The front (char-live-2's swept forelocks, returning hooks, jaw strands and side groups), in
    # the generator's terms. Angles round the head from the front, + toward the far side of the
    # part; heights above the chin in head heights.
    front=dict(
        part=0.55,  # how far off centre the part is (the seed decides the side; cut 1 is Cora's, person_params.from_style; the rear layers follow it)
        flare=0.012,  # how far the sweep's points turn out from the head (the spread; held under the outline check's margin); the seed's variation moves the near section's by the same
        sweep=dict(points=7, depth=0.024, el=(58.0, 112.0), drop=0.40, lean=1.4, thick=0.004, lift=0.020, fall=0.60),  # the big section: roots up the part (elevation from the hairline to the crown), its hem from the brow at the front to `drop` head heights lower behind
        near=dict(points=4, depth=0.026, el=(60.0, 104.0), end_h=0.10, lean=1.8, thick=0.0035, lift=0.024, lift_back=0.012, flare=0.012),  # the near section: up the part too, falling to the near temple and down beside the face to the jaw in front of the ear; its stand-off at the temple (the sides' width) and behind, toward the crown (where more hides the plait's start and stands out as a ledge); its points' flare on the columns that reach the jaw# the near section: up the part too, falling to the near temple and down beside the face to the jaw
        # Returning hooks off the sweep's outer edge: each bows out `out` from the hair and curls
        # back under, its tip lying on the hair `back` degrees nearer the face, `length` lower.
        hooks=[dict(az=62.0, h=0.90, length=0.100, width=0.022, out=0.020, back=12.0), dict(az=80.0, h=0.76, length=0.090, width=0.020, out=0.018, back=10.0)],
        ear=dict(top=0.022, front=0.45),  # the ear stays open (the drawing's, and char-port-1's ear rays): no section's hem below `top` over the eye line where it passes over the ear; the near section's columns from `front` back end there
        jaw=dict(n=2, end_h=-0.03, width=0.022),  # long strands before the ears, to below the jaw
        sides=dict(n=2, width=0.016, off=0.015),  # side groups: over the ear and round behind it to the nape, `off` over the scalp
    ),
    plait=dict(
        root_h=0.56,  # the plait's start, head heights above the chin: behind the crown, where the upper layers meet
        root_lift=0.002,  # lifted over the hair mass, so the start shows to the 58° camera, seated (Cora's rear depth)
        length_h=2.3,  # root to tie, in head heights: down the back to below the shoulder blades, as the drawing
        depth=(0.55, 0.40),  # its strands' depth over their width, and their over-and-under's: Cora's flatter section (.0078 deep for .0125 wide, the orbit .0068 deep for .0185 across)
        seat=0.15,  # how far its spine stands off the hair under it, in its own radii (the styles' braid: 1.55)
        scale=1.6,  # its radius over the styles' braid (0.085 of the head's width): the drawn rear's width at Near and Middle
        turns=3.9, taper=0.63, gain=0.55, gain_span=(0.15, 0.92), full_from=0.0,  # crossings root to tie (0.59 head heights each: Near and Middle luma closest to the drawn rear), its narrowing, the upper lobes' widening
        crest=__import__("os").environ.get("SLOP_MASTER_CREST", "1") != "0",
        crest_up=(-0.28, 0.55), crest_lit=(0.70, 0.45),  # a lobe's normals: down below, up on its upper face (base, by facing); where its crest highlight starts (over, facing)
    ),
    # Seeded variation (a cut is the style from another seed, as for every style): each value
    # moves by up to its range, a draw per value from the seed, and the plait keeps its pitch.
    # Clamped by measure (master_scale): built at full range, the silhouette measured against
    # Cora's tolerances below, and the range halved until it holds (at none, the master itself).
    vary=dict(length_h=0.25, drop=0.06, lean=0.12, hook_az=4.0, hook_h=0.03, near_end=0.04, jaw_end=0.04, flare=0.002, part=0.06),
    highlight=dict(layers=(5, 6), band=(0.10, 0.42)),  # the highlight rule: the rear layers with one (Cora's upper groups), and where along the lock (root 0, tip 1)
    tolerance=dict(spread_face=(1.77, 1.97), crown_lift=(0.061, 0.131), rear_depth=(0.49, 0.57)),  # Cora's: 1.87±0.10, 0.096±0.035, 0.53±0.04
    hair_tris=10700,  # the near mesh's budget, 12,000, less the scalp cap's 1,216 on the style head, with a margin
    # SLOP_MASTER_PLAIT=0 builds the cut without its plait: the visibility control (the plait's
    # pixels are where the two differ).
    plait_on=__import__("os").environ.get("SLOP_MASTER_PLAIT", "1") != "0",
))


def master_params(name, seed, scale):
    """A master's parameters for a seed: each `vary` value moved by up to its range times `scale`
    (a draw per value from the seed, the same at every scale), the plait's turns with its length."""
    import copy
    m = copy.deepcopy(MASTERS[name])
    r = random.Random(f"master/{name}/{seed}")
    d = {k: r.uniform(-1.0, 1.0) * v * scale for k, v in sorted(m["vary"].items())}
    p, f = m["plait"], m["front"]
    p["turns"] *= (p["length_h"] + d["length_h"]) / p["length_h"]
    p["length_h"] += d["length_h"]
    f["sweep"]["drop"] += d["drop"]
    f["sweep"]["lean"] += d["lean"]
    f["hooks"] = [dict(hk, az=hk["az"] + d["hook_az"], h=hk["h"] + d["hook_h"]) for hk in f["hooks"]]
    f["near"]["end_h"] += d["near_end"]
    f["jaw"]["end_h"] += d["jaw_end"]
    f["flare"] += d["flare"]
    f["part"] += d["part"]
    return m, dict(scale=scale, moved={k: round(v, 4) for k, v in d.items()})


def master_scale(hf, spec, hairline, covered, bald, body):
    """The variation a master's cut keeps (master_params): the full range if its silhouette, built
    at full detail, is within the tolerances; else half, a quarter, none. A cut that is out of
    them even unvaried (its seed's own parting and lock draws) stops the build."""
    for scale in (1.0, 0.5, 0.25, 0.0):
        h = Hair(hf, dict(spec, _vary_scale=scale), hairline, covered=covered, bald=bald, body=body, detail=1.0)
        if h.within():
            return scale
    raise SystemExit(f"hair master {spec['style']} seed {spec.get('seed', 0)}: out of its tolerances even unvaried: {h.measures()}, {sum(h.part_tris.values())} triangles")


FRINGE_OVER = 0.003  # a full fringe ends this far above the top of the head's own brows
FRINGE_BONE = "J_Hair_Fringe"  # the bone a fringe hangs from on a face type's head; a type's file says where it stands (hair_fit.py)
RING_END = 0.030  # a lock carries the head's light ring to this far from its tip, metres (`_RING`)


def brow_top(hf):
    """The top of a head's brows (relative to the head's origin, metres), drawn stroke included."""
    from head_mesh import BROW_STROKE

    return float(hf.eye_z + hf.eye_up + hf.brow_up + getattr(hf, "brow_lift", 0.0) + hf.brow_arch + abs(hf.brow_tilt) + 0.55 * hf.brow_w * BROW_STROKE)


def fringe_line(hf):
    """The height a full fringe ends at on a head (relative to the head's origin, metres):
    `FRINGE_OVER` above the top of that head's own brows.

    The types' brows sit at different heights: the highest brow's top is 1.2 cm above the
    lowest's. A shared style is one mesh for every type, built on the standard head to that
    head's line, and until 2026-11-13 the line was one for all, above the highest brow any type
    has: after a type's fit the fringe ended 3 to 16 mm above that type's brows, a bare
    forehead on most. Now the fringe hangs from a bone (`FRINGE_BONE`), and each type's file
    stands that bone where its own line is (hair_fit.py), so a style's fringe ends at this
    line on every type. A person's own hair is built to their own head's line directly."""
    return brow_top(hf) + FRINGE_OVER


def fringe_point(hf):
    """The middle of the forehead's front at the fringe's line, in the head's frame: where the
    fringe's bone stands, and the point a type's fit of the fringe is worked out from."""
    z = fringe_line(hf)
    lo, hi = -30.0, 80.0
    for _ in range(40):  # the elevation whose point on the head's front is at that height
        el = math.radians((lo + hi) / 2)
        d = np.array([0.0, math.cos(el), math.sin(el)])
        p = ORIGIN + d * hf.radius(d[None, :])[0]
        lo, hi = ((lo + hi) / 2, hi) if p[2] < z else (lo, (lo + hi) / 2)
    return p


def fringe_share(hf, hairline, pts, front_z=None):
    """How much of the fringe's bone each point of the hair follows: nothing at the hairline and
    above it, all of it at the fringe's line and below, over the forehead only (in full to 48
    degrees round from the front, none past 78; behind the head's middle, none). Hair between
    stretches or closes up evenly when a type's file moves the bone."""
    pts = np.asarray(pts, float).reshape(-1, 3)
    line = fringe_line(hf)
    az = np.degrees(np.arctan2(-pts[:, 0], pts[:, 1]))
    front = np.abs(az) < 78.0
    out = np.zeros(len(pts))
    for i in np.nonzero(front & (pts[:, 1] > 0.0))[0]:
        z0 = hairline(float(az[i])) - 0.002
        down = float(np.clip((z0 - pts[i, 2]) / max(z0 - line, 0.004), 0.0, 1.0))
        out[i] = down * smooth((78.0 - abs(az[i])) / 30.0) * smooth(pts[i, 1] / 0.03)
    return out


def ring_mask(hf, hairline, pts, nrm, share, along):
    """`_RING` for each point of the hair, 0 to 1: how much of the head's light ring it takes
    (the client multiplies its ring by it). 1 over the top and round the crown; 0 on a fringe
    (a ring drawn straight across its sheets reads as a seam), on the last `RING_END` of a lock
    before its tip, and on the sides of a lock or a sheet that face the head. `share` is each
    point's share of its lock's length from the root and `along` that in metres."""
    pts, nrm = np.asarray(pts, float).reshape(-1, 3), np.asarray(nrm, float).reshape(-1, 3)
    share, along = np.clip(np.asarray(share, float), 0.0, 1.0), np.asarray(along, float)
    fringe = fringe_share(hf, hairline, pts)
    # A fringe is off the ring from where it leaves the hairline, sooner than the bone takes it.
    off_fringe = 1.0 - np.array([smooth(min(f / 0.25, 1.0)) for f in fringe])
    to_tip = np.where(share > 1e-3, along * (1.0 - share) / np.maximum(share, 1e-3), 1.0)
    end = np.array([smooth(d / RING_END) for d in to_tip])
    outward = np.einsum("ij,ij->i", nrm, unit(pts - ORIGIN))
    inner = np.array([smooth((o + 0.05) / 0.25) for o in outward])
    return np.clip(off_fringe * end * inner, 0.0, 1.0)


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
        self.marks = []  # (first vertex, `_GREY`): the grey mask of the vertices from there on
        self.hang_chains = set()  # the chains of sheets that lie on the back (their joints are on the hair, not inside its arc)
        self.rope_chains = {}  # the chains of a tail and of braids: {chain: the rope's radius}. They hang down the back as a rope, whose joints are its axis
        self.chains = []
        self.locks = []
        self.sheets = []  # sheets' own records; their columns are walked with the locks
        self.extra = []  # (kind, data) for person.py: ties and bands in cloth
        self.creases = []  # (SLOP_PORT=hair) lock lines: points, hem first, each [(vertex, weight), ...] on a sheet's front
        self.partings = []  # where the hair parts: dict(pts, nrm, deg) on the scalp, head frame
        self.paths = []  # (S6 masters) locks laid on explicit paths: dict(pts, widths, ...)
        self.hl_marks = {}  # vertex -> highlight (0..1) a master asks for (the plait's crests)
        self.part_tris = {}  # triangles by part, for the budget
        self.part_verts = []  # (part, first vertex, end) as built
        style = spec["style"]
        if style not in STYLES and not (MASTERS_ON and style in MASTERS):
            raise SystemExit(f"hair.style: {style!r} is not one of {STYLES}")
        self.length = float(spec.get("length", 0.07))
        self.parting = float(np.clip(spec.get("parting", 0.0), -1, 1))
        self.fringe = float(np.clip(spec.get("fringe", 0.7), 0, 1.3))
        self.volume = float(np.clip(spec.get("volume", 0.5), 0, 1))
        self.curl = float(np.clip(spec.get("curl", 0.0), 0, 1))
        self.fringe_style = spec.get("fringe_style") or "auto"
        self.brow_z = hf.eye_z + hf.eye_up + hf.brow_up
        self.front_z = float(hairline(0.0))
        # Where a full fringe ends: just above this head's own brows.
        self.fringe_z = fringe_line(hf)
        self.hairline_soft = lambda az: float(np.mean([hairline(az + d) for d in np.linspace(-18.0, 18.0, 9)]))
        self.vary_scale = spec.get("_vary_scale")
        if MASTERS_ON and style in MASTERS:
            if self.vary_scale is None:
                self.vary_scale = master_scale(hf, spec, hairline, covered, bald, body)
            self.master, self.master_vary = master_params(style, spec.get("seed", 0), self.vary_scale)
        getattr(self, "_" + style)()
        self._build()

    def within(self):
        """A master's silhouette within its tolerances (MASTERS[...]["tolerance"])."""
        ms, m = self.measures(), MASTERS[self.spec["style"]]
        return all(lo <= ms.get(k, lo - 1) <= hi for k, (lo, hi) in m["tolerance"].items()) and sum(self.part_tris.values()) <= m["hair_tris"]

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
                self.locks.append(dict(p=pt, d=unit(d), length=max(ln, 0.008), z_end=-9.0 if ze is None else ze, width=0.05, lift=lift(uu) if callable(lift) else lift, g=g, blunt=0.0, tip_out=tip_out(uu) if callable(tip_out) else tip_out,
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
        mid = 1.0 if back_th > 80 else 0.0  # the two sides meet down the middle of the back
        back = lambda u: smooth((u - 0.55) / 0.45)
        short = (lambda u: 0.0) if front_end is None else (lambda u: (front_end - z_end) * smooth((0.34 - u) / 0.16))
        sides = {}
        for side in (-1, 1):  # -1: toward the character's left (-X)
            roots, dirs = [], []
            for t in np.linspace(0, 1, 13):
                phi = math.radians(lerp(front, 128, t))  # from the front over the top to the crown
                d = unit(np.array([px / 0.11 * (1 - mid * smooth((t - 0.55) / 0.45)) + side * 0.035 * (1 - 0.9 * mid * smooth((t - 0.6) / 0.4)), math.cos(phi), math.sin(phi)]))
                roots.append(ORIGIN + d * self.hf.radius(d[None, :])[0])
                # Sideways at the front, fanning to straight back behind the crown. The front edge
                # starts far enough back that it comes down at the ear's front: rooted further
                # forward, where the skull slopes to the forehead, it slides down over the eye.
                th = math.radians(lerp(4, back_th, smooth((t - 0.45) / 0.55)))
                dirs.append([side * math.cos(th), -0.16 - math.sin(th), 0.0])
            sides[side] = (roots, dirs)
        # The parting: between the two sides' roots, on the scalp, from the front over the top.
        mids, deg = [], []
        for t, a, b in zip(np.linspace(0, 1, 13), sides[-1][0], sides[1][0]):
            d = unit((a + b) / 2 - ORIGIN)
            mids.append(ORIGIN + d * self.hf.radius(d[None, :])[0])
            deg.append(lerp(front, 128, t))
        self.partings.append(dict(pts=np.array(mids), deg=np.array(deg)))
        # The wider side of an off-centre parting takes more points.
        count = {side: max(2, round(points * (0.75 + 0.5 * (0.5 + 0.5 * side * (px / 0.05) * -1)))) for side in (-1, 1)}
        if mid:
            # One sheet for both sides: down one side of the parting to the crown, round behind
            # it and back up the other. As two sheets their back edges met down the middle of
            # the back, and the two edges read as a seam from behind.
            roots = sides[-1][0] + sides[1][0][::-1]
            dirs = sides[-1][1] + sides[1][1][::-1]
            half = lambda u: 2 * u if u < 0.5 else 2 * (1 - u)  # how far along its own side a place across the sheet is
            side_of = lambda u: -1 if u < 0.5 else 1
            self.sheet(roots, np.array(dirs), z_end=z_end, points=count[-1] + count[1], depth=depth, hem=lambda u: -back_drop * back(half(u)) + short(half(u)), lift=lift, g=g,
                       chain=None if chain is None else (lambda u: chain(-side_of(u) * (90 + 45 * back(half(u))))), shade=0.03, edges=(0.15, 0.15), tip_out=tip_out, splay=splay, off=0.005, gather=gather)
        else:
            for side in (-1, 1):
                roots, dirs = sides[side]
                self.sheet(roots, np.array(dirs), z_end=z_end, points=count[side], depth=depth, hem=lambda u: -back_drop * back(u) + short(u), lift=lift, g=g,
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

    def fringe_reach(self, least):
        """How far down the forehead a fringe comes: 0 the hairline, 1 the fringe's line, just
        above the brows. A person's `fringe` takes it from `least` to the line. Until 2026-11-13
        it was the fringe's share of the way itself, so most people's fringes, and every short
        style's, ended in the middle of the forehead, 3 to 6 cm above the brows: only the bobs'
        came within 13 mm. The reference's fringe ends at the brows; a style now has a fringe
        that comes down to them or none to speak of."""
        return float(lerp(least, 1.0, min(self.fringe, 1.0)))

    def bangs(self, mode="straight", points=6, reach=1.0, depth=0.009, span=60.0, g=38.0, splay=0.0, tip_out=0.0):
        """The fringe, one sheet from the top of the head forward and down over the forehead:
        `straight` to a level line with longer flanks, `swept` to one side, `curtain` parted to
        the temples (a sheet a side)."""
        if self.fringe * reach <= 0.03:
            return
        f = self.fringe_reach(0.86) * (0.6 + 0.4 * reach)
        if self.fringe_style in ("straight", "swept", "curtain"):
            mode = self.fringe_style
        px = self.part_x()
        z_end = lerp(self.front_z - 0.004, self.fringe_z, f)
        sweep = 0.0
        if mode == "swept":
            sweep = 1.0 if px <= 0 else -1.0  # away from the parting
            if abs(px) < 0.004:
                sweep = 1.0 if self.rng.random() < 0.5 else -1.0
        for pt in self.partings:  # a fringe that is not parted covers the parting's front
            pt["from"] = PARTING["curtain_from_deg"] if mode == "curtain" else PARTING["from_deg"]
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
            # Longest in the middle and a little shorter toward the temples: a level line with
            # square ends reads as a helmet's edge.
            hem = lambda u: 0.012 * abs(tt(u)) ** 1.6
        else:
            hem = lambda u: 0.010 * sweep * tt(u) + 0.006 * abs(tt(u)) ** 2  # longest where it ends
        dirs = np.stack([sweep * 0.75 - 0.80 * np.sign(ts) * np.abs(ts) ** 2, np.ones(len(ts)), np.zeros(len(ts))], axis=1)  # the flanks fan out to the temples
        # A few thick locks, as the reference's fringe is: fewer and deeper points than the
        # hem of the sides and back, and uneven.
        locks = max(3, round(points * 0.6))
        self.sheet(roots, dirs, z_end=z_end, points=locks, depth=max(depth, 0.022) * (0.5 + 0.5 * f), hem=hem, lift=0.011, g=g, shade=0.05, edges=(0.5, 0.5), splay=splay,
                   tip_out=tip_out, thick=0.0035, check=True, uneven=0.45, sharp=0.55)

    def strands(self, n, z=None, chain=None):
        """Single strands that lift off the hair, as the reference's has: thin locks a little off
        the sheets. With `z` (where hanging hair ends) they hang beside the sheets at the sides
        and back and flick out at the end; without, they rise from the top of short hair and
        stand up at the tip."""
        for _ in range(n):
            if z is None:
                az, el = self.u(-170, 170), self.u(46, 70)
                self.lock(az, el, "away", length=self.u(0.045, 0.075), width=self.u(0.010, 0.016), lift=self.u(0.012, 0.020), g=9.0, tip_out=self.u(0.014, 0.028), taper=3.2, shade=0.03)
            else:
                # Hair on spring chains keeps its strands to the back, where the chains that hang
                # that long are: one at the ear's front would ride a chain that stops at the jaw.
                az = self.u(78, 282) if chain is None else self.u(108, 252)
                az = az if az <= 180 else az - 360
                self.lock(az, self.u(30, 42), DOWN + np.array([0, 0.05, 0]), z_end=z + self.u(-0.012, 0.022), length=0.9, width=self.u(0.010, 0.016), lift=self.u(0.009, 0.014), g=36.0,
                          tip_out=self.u(0.012, 0.026), chain=-1 if chain is None else chain(az), taper=3.0, shade=0.03)

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
        f = min(self.fringe if fringe is None else fringe, 1.0)
        brow = lerp(self.front_z - 0.004, self.fringe_z, f)
        # The hem follows the hairline with its corner at the temple rounded: a level front with
        # square corners reads as a helmet's edge.
        ends = np.array([self.hairline_soft(a) - drop for a in az_end])
        # Over the forehead the hem is the fringe's line: lowest in the middle and rising in a
        # curve to the temples, uneven by a few millimetres from side to side.
        front = np.array([max(0.0, 1.0 - (abs(a) / 62.0) ** 2) for a in az_end])
        p1, p2 = self.u(0, 6.28), self.u(0, 6.28)
        wave = np.array([0.5 * math.sin(math.radians(a) * 2.6 + p1) + 0.5 * math.sin(math.radians(a) * 4.3 + p2) for a in az_end])
        ends = ends * (1 - front) + np.minimum(brow + 0.006 * f * wave, ends) * front + raise_hem
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
        self.cap(drop=0.010 * k, points=15, depth=0.016, fringe=0.92 * self.fringe_reach(0.80), lift=0.006, tip_out=0.002 + 0.004 * self.volume, g=20.0, splay=0.06, swirl=lean)
        # A shorter layer over the top, for the cut's volume.
        self.cap(raise_hem=0.045, points=9, depth=0.022, fringe=0.2 * self.fringe, lift=0.011, tip_out=0.003 + 0.005 * self.volume, g=18.0, splay=0.08, swirl=lean, shade=0.03)
        self.strands(1 + int(self.volume > 0.5))
        self.sideburns(0.026)

    def _tousled(self):
        k = self.length / 0.07
        lean = 30.0 if self.part_x() <= 0 else -30.0
        # Longer and looser: deep points turned out, and a second layer whose points stand up.
        self.cap(drop=0.016 * k, points=13, depth=0.034, fringe=self.fringe_reach(0.86), lift=0.007, tip_out=0.006 + 0.010 * self.volume, g=16.0, splay=0.16, swirl=lean, uneven=0.45)
        self.cap(raise_hem=0.040, points=8, depth=0.040, fringe=0.3 * self.fringe, lift=0.013, tip_out=0.008 + 0.014 * self.volume, g=14.0, splay=0.13, swirl=lean, shade=0.03, uneven=0.45)
        self.strands(3)
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
        self.strands(3, z=z)
        self.temples(z + 0.02, n=1)

    def _bob(self):
        # Cut to one line, the ends turned under.
        z = self.side_line()
        self.curtain(z, points=6, depth=0.010, back_drop=-0.010, tip_out=-0.010)
        self.over(z, points=4, depth=0.010, back_drop=-0.010, tip_out=-0.010, back_th=88.0)
        self.bangs("swept" if abs(self.parting) > 0.45 else "straight", points=6)
        self.strands(1, z=z)

    def _bob_parted(self):
        z = self.side_line()
        self.curtain(z, points=6, depth=0.014, tip_out=-0.006)
        self.over(z, points=4, depth=0.014, tip_out=-0.006, back_th=88.0)
        self.bangs("curtain", points=5)
        self.temples(z + 0.03, n=1)
        self.strands(2, z=z)

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
        self.curtain(z, points=5, depth=0.060, back_drop=drop, chain=chain, gather=15.0, tip_out=-0.005, front_end=-0.100)
        self.over(z + 0.02, points=4, depth=0.060, back_drop=drop, chain=chain, gather=15.0, tip_out=-0.005, front_end=-0.105, back_th=88.0)
        mode = "curtain" if abs(self.parting) < 0.3 else "swept"
        self.bangs(mode, points=6)
        self.strands(4, z=z - drop, chain=chain)
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
        self.rope_chains[chain(0)] = 0.014
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
        # Anchor just inside the nape hairline on this head's surface.
        g = self.point(180, self.hairline(180) + .012)
        self.gather(g, n_mid=16)
        width = np.linalg.norm(self.comb.surface(90, 0) - self.comb.surface(-90, 0))
        back_length = g[2] - self.comb.b.get("belt_z", -0.55)
        self.braid = [dict(p=g, d=np.array([0.0, -0.5, -1.0]),
                           length=back_length * (0.58 + 0.30 * self.length),
                           radius=0.085 * width)]
        self.bangs("curtain" if abs(self.parting) < 0.3 else "swept", points=5, reach=0.9)
        self.temples(-0.085, n=1, width=0.024)

    def _swept_braid(self):
        """The `swept_braid` master (MASTERS): Cora's cut. Under it the hair drawn back to the
        plait's start (`gather`, as `braid`); over it the rear layers (`rear_layers`), wide locks
        and companions meeting the plait at staggered heights; the plait from behind the crown,
        lifted so its start shows to the game camera."""
        m = self.master
        H = self.hf.top_z - self.hf.chin_z
        self.volume = max(self.volume, m["volume"])  # Cora's crown stands up off the scalp
        z0 = self.hf.chin_z + m["plait"]["root_h"] * H
        g = self.point(180, z0)
        # The mass is drawn a little inside the plait's start, so it thins there and the plait's
        # first lobes lie on it rather than in it.
        self._tag("mass", lambda: self.gather(g - unit(np.array([0.0, g[1], 0.0])) * m["mass_in"], n_mid=16))
        self._tag("rear layers", lambda: self.rear_layers(m))
        width = np.linalg.norm(self.comb.surface(90, 0) - self.comb.surface(-90, 0))
        back_length = g[2] - self.comb.b.get("belt_z", -0.55)
        self.braid = [dict(p=g, d=np.array([0.0, -0.5, -1.0]), length=m["plait"]["length_h"] * H, radius=0.085 * width * m["plait"]["scale"], master=m["plait"])] if m["plait_on"] else []
        self._tag("front", lambda: self.front_master(m))
        f = m["front"]
        self._tag("jaw strands", lambda: self.temples(self.hf.chin_z + f["jaw"]["end_h"] * H, n=f["jaw"]["n"], width=f["jaw"]["width"]))
        self.side_groups(m)

    def measures(self):
        """The silhouette's measures as Cora's fit was held to (docs/char-live-2/hair/README.md),
        in this head's own frame: the hair's outer spread in cheek widths, its lift over the skull's
        top in head heights, and its depth behind the pinna, over the pinna's base, in head heights.
        The cheek is Cora's, 0.5076 head heights (her fit's units, the stations' too): this head's
        own face, across its cheekbones, is wider for its height, and its ratio is given beside
        (`spread_face`)."""
        V = np.asarray(self.v, float).reshape(-1, 3)
        if not len(V):
            return {}
        H = self.hf.top_z - self.hf.chin_z
        ear = self.point(90.0, self.hf.eye_z - 0.010)
        base = self.hf.eye_z - 0.035  # the pinna's base, about
        part = np.array([""] * len(V), dtype=object)
        for name, a, b in self.part_verts:
            part[a:b] = name
        above = np.nonzero(V[:, 2] > base)[0]
        head = np.nonzero(V[:, 2] > self.hf.chin_z)[0]  # the head's hair, not the plait down the back
        hx = V[head, 0]
        # This face's own cheek width: across the head's surface at the cheekbones, in front of the ears.
        z = self.hf.eye_z - 0.030
        xs = np.linspace(0.0, 0.12, 241)
        cheek = 2.0 * max((x for x in xs if self.comb.head(np.array([[x, 0.035, z]]))[0] < 0), default=0.5076 * H / 2)
        out = dict(spread=round(float((hx.max() - hx.min()) / (0.5076 * H)), 3), spread_face=round(float((hx.max() - hx.min()) / cheek), 3), crown_lift=round(float((V[:, 2].max() - self.hf.top_z) / H), 3),
                   rear_depth=round(float((ear[1] - V[above, 1].min()) / H), 3) if len(above) else None)
        # Which part sets each (for tuning): the widest on each side, the highest, the furthest back.
        out["by"] = dict(left=str(part[head[np.argmin(hx)]]), right=str(part[head[np.argmax(hx)]]), top=str(part[int(np.argmax(V[:, 2]))]),
                         back=str(part[above[np.argmin(V[above, 1])]]) if len(above) else None)
        return out

    def _tag(self, part, make):
        """Run `make` and tag the locks and sheets it adds with `part` (the triangle budget)."""
        n0, s0 = len(self.locks), len(self.sheets)
        make()
        for k in self.locks[n0:]:
            k.setdefault("part", part)
        for sp in self.sheets[s0:]:
            sp.setdefault("part", part)

    def rear_layers(self, m):
        """The rear layers of a master: each layer's stations (side distance and width in
        half-cheeks, height above the chin in head heights) as a path a side, Catmull-Rom between,
        laid over the back of the head `over` off the scalp with the layer's own swell; the pair
        offset by the part's asymmetry and tucked a little at the sides (Cora's fit, generator
        units). A companion, narrower, lies beside the wide lock over the middle of its length."""
        ps = -1.0 if self.parting < 0 else 1.0  # the part's side in the head's x (front_master's `s`: the sweep goes the other way round the head)
        H = self.hf.top_z - self.hf.chin_z
        cr = m["cheek"] * H
        n = m["rings"]
        ts = np.linspace(0.0, 1.0, n + 1)

        def station(rows, t):
            q = t * (len(rows) - 1)
            j = min(int(q), len(rows) - 2)
            u = q - j
            a, b, c, d = (np.array(rows[int(np.clip(k, 0, len(rows) - 1))], float) for k in (j - 1, j, j + 1, j + 2))
            return 0.5 * (2 * b + (-a + c) * u + (2 * a - 5 * b + 4 * c - d) * u * u + (-a + 3 * b - 3 * c + d) * u ** 3)

        for g, rows in sorted(m["layers"].items()):
            for side in (-1, 1):
                pts, widths = [], []
                for t in ts:
                    x, h, w = station(rows, t)
                    # Cora's offset leans toward her part and her tuck's second value is the part's
                    # side (her fit: +X, her left, in Blender's frame). Here they follow this cut's
                    # part: on the side of the head's x that is `ps` (the head frame's -X is the left).
                    x = side * x * cr + ps * m["part_asymmetry"] * cr * math.sin(t * math.pi + g * 0.8)
                    z = self.hf.chin_z + H * (h + m["side_tuck"][1 if side * ps > 0 else 0] * 0.23 * math.sin(math.pi * t + g * 0.47))
                    off = m["over"] + (m["lift"][0] + m["lift"][1] * (g % 3)) * math.sin(math.pi * t)
                    pts.append(self._back_point(x, z, off))
                    widths.append(max(0.00035, w * cr))
                self.paths.append(dict(pts=np.array(pts), widths=np.array(widths), layer=g, side=side, part="rear layers", tone=self.u(-1, 1), grey=self.rng.random()))
                if g in m["companions"]:
                    c = m["companion"]
                    keep = (ts >= c["start"]) & (ts <= 1.0 - c["end"])
                    P = np.array(pts)
                    tan = unit(np.gradient(P, axis=0))
                    nrm = self.comb.normal(P)
                    across = unit(np.cross(tan, nrm))
                    W = np.array(widths)
                    Q = P + across * (side * c["side"] * W * 2)[:, None] + nrm * 0.0015
                    self.paths.append(dict(pts=Q[keep], widths=W[keep] * c["width"], layer=g, side=side, part="rear layers", companion=True, tone=self.u(-1, 1), grey=self.rng.random()))

    def front_master(self, m):
        """A master's front (Cora's): a side part; from it the big swept section across the
        forehead to the far temple, short at the part (above the brow) and long at the far side
        (to the cheek), ending in points; the near side's section from the part to the near
        temple, down beside the face to the jaw; returning hooks off the sweep's outer edge.
        Angles round the head: + toward the far side, the side the sweep goes to."""
        f = m["front"]
        H = self.hf.top_z - self.hf.chin_z
        s = -1.0 if self.parting < 0 else 1.0  # the far side: + the character's left (az +, -X)
        self.parting = -s * max(abs(self.parting), f["part"])  # the part on the near side
        part_az = -s * 22.0 * f["part"]
        ts = np.linspace(0, 1, 13)
        # Both sections root along the part, from the hairline over the top toward the crown, and
        # fall away from it: the sweep forward and across the forehead to the far side, the near
        # section down to the near temple.
        sw = f["sweep"]
        el = lerp(sw["el"][0], sw["el"][1], ts)
        roots = self.comb.surface(np.full(len(ts), part_az + s * 3.0), el)
        dirs = np.stack([-s * sw["lean"] * (0.75 + 0.25 * ts), 0.55 - 0.75 * ts, -sw["fall"] - (0.55 - sw["fall"]) * ts], axis=1)
        brow = self.hf.eye_z + self.hf.eye_up + self.hf.brow_up + 0.006
        ear_top = self.hf.eye_z + f["ear"]["top"]
        hem = lambda u: max(-sw["drop"] * H * smooth((u - 0.10) / 0.90), ear_top - brow)
        self.sheet(roots, dirs, z_end=brow, points=sw["points"], depth=sw["depth"], hem=hem, lift=sw["lift"], g=30.0, shade=0.04, tip_out=f["flare"],
                   edges=(0.3, 0.3), thick=sw["thick"], check=True, uneven=0.30, sharp=0.55)
        nr = f["near"]
        l0, s0 = len(self.locks), len(self.sheets)
        el = lerp(nr["el"][0], nr["el"][1], ts)
        roots = self.comb.surface(np.full(len(ts), part_az - s * 3.0), el)
        dirs = np.stack([s * nr["lean"] * np.ones(len(ts)), 0.25 - 0.45 * ts, -0.55 - 0.15 * ts], axis=1)
        z_near = self.hf.chin_z + nr["end_h"] * H
        near_hem = lambda u: 0.03 * u + (ear_top - z_near) * smooth((u - f["ear"]["front"]) / 0.25)
        self.sheet(roots, dirs, z_end=z_near, points=nr["points"], depth=nr["depth"], hem=near_hem, lift=lambda u: lerp(nr["lift"], nr["lift_back"], smooth((u - f["ear"]["front"]) / 0.25)), g=40.0, shade=0.03,
                   tip_out=lambda u: (nr["flare"] + f["flare"] - MASTERS["swept_braid"]["front"]["flare"]) * (1 - smooth((u - f["ear"]["front"]) / 0.25)),  # the columns ending above the ear turn no points out
                   edges=(0.3, 0.5), thick=nr["thick"], check=True, uneven=0.4, sharp=0.55)
        for x in self.locks[l0:] + self.sheets[s0:]:
            x["part"] = "near section"
        for hk in f["hooks"]:
            az = part_az + s * hk["az"]
            z = self.hf.chin_z + hk["h"] * H
            radial = lambda p: unit(np.array([p[0], p[1] + 0.01, 0.0]))
            p0 = self.point(az, z)
            p0 = p0 + radial(p0) * 0.012
            tip = self.point(az - s * hk["back"], z - hk["length"])
            tip = tip + radial(tip) * 0.016  # on the sweep, not under it
            down = np.array([0.0, 0.0, -hk["length"]])
            ctrl = [p0, p0 + radial(p0) * hk["out"] * 0.8 + down * 0.35, lerp(p0, tip, 0.75) + radial(p0) * hk["out"] * 0.7 + down * 0.05, tip]
            self.explicit_lock(ctrl, hk["width"], part="hooks")

    def side_groups(self, m):
        """A master's side groups: from over the ear, round behind it and down to the nape,
        toward the plait (Cora's combed side locks, which follow the skull round the pinna)."""
        sg = m["front"]["sides"]
        H = self.hf.top_z - self.hf.chin_z
        for side in (-1, 1):
            for k in range(sg["n"]):
                z0 = self.hf.chin_z + (0.62 - 0.08 * k) * H
                a0 = side * (92 + 6 * k)
                p0 = self.point(a0, z0)
                ctrl = [p0, self.point(side * (118 + 4 * k), self.hf.chin_z + (0.46 - 0.06 * k) * H), self.point(side * (150 + 3 * k), self.hf.chin_z + (0.30 - 0.05 * k) * H),
                        self.point(side * 168, self.hf.chin_z + (0.20 - 0.04 * k) * H)]
                ctrl = [c + unit(np.array([c[0], c[1] + 0.012, 0.0])) * sg["off"] for c in ctrl]
                self.explicit_lock(ctrl, sg["width"] * (1 - 0.15 * k), part="side groups")

    def explicit_lock(self, ctrl, width, part, n=12):
        """A lock through control points (Catmull-Rom), tapering from `width` at the root to a
        point, laid as a path lock (`_path_ribbon`)."""
        C = np.array(ctrl, float)
        pts = []
        for t in np.linspace(0, 1, n + 1):
            q = t * (len(C) - 1)
            j = min(int(q), len(C) - 2)
            u = q - j
            a, b, c, d = (C[int(np.clip(i, 0, len(C) - 1))] for i in (j - 1, j, j + 1, j + 2))
            pts.append(0.5 * (2 * b + (-a + c) * u + (2 * a - 5 * b + 4 * c - d) * u * u + (-a + 3 * b - 3 * c + d) * u ** 3))
        t = np.linspace(0, 1, n + 1)
        widths = width * (0.55 + 0.45 * smooth(t / 0.2)) * np.maximum(1 - t ** 2.2, 0.04)
        self.paths.append(dict(pts=np.array(pts), widths=widths, layer=0, side=0, part=part, tone=self.u(-1, 1), grey=self.rng.random()))

    def _back_point(self, x, z, off):
        """The point behind the head (or neck) at side x and height z, `off` out from what the hair
        lies on: the first, coming from behind, that close. A station wider than this head (Cora's
        were measured on hers) has none: it takes the point of the line nearest the head, at the
        side."""
        ys = np.linspace(-0.30, 0.10, 81)
        d = self.comb.dist(np.stack([np.full(len(ys), x), ys, np.full(len(ys), z)], axis=1))
        hit = np.nonzero(d <= off)[0]
        if not len(hit):
            return np.array([x, ys[int(np.argmin(d))], z])
        lo, hi = ys[max(hit[0] - 1, 0)], ys[hit[0]]
        for _ in range(20):
            mid = 0.5 * (lo + hi)
            if self.comb.dist(np.array([[x, mid, z]]))[0] > off:
                lo = mid
            else:
                hi = mid
        return np.array([x, lo, z])

    def _path_ribbon(self, k, base, tipc, silver, grey):
        """A lock on an explicit path (a master's rear layer): the ribbon's five across and one
        behind, its width the path's own, shaded as Cora's leaves were: the broad face one band,
        only the rolled margins turning into shadow."""
        pts, widths = k["pts"], k["widths"]
        n = len(pts)
        if n < 2:
            return
        tan = unit(np.gradient(pts, axis=0))
        out = self.comb.normal(pts)
        side = unit(np.cross(tan, out))
        out = np.cross(side, tan)
        col = self._lock_colour(dict(tone=k["tone"], shade=0.0, grey=k["grey"]), base, tipc, silver, grey)
        across = (-1.0, -0.5, 0.0, 0.5, 1.0)
        profile = (0.0, 0.78, 1.0, 0.78, 0.0)
        back = self.detail >= 1
        if not back:
            across, profile = (-1.0, 0.0, 1.0), (0.0, 1.0, 0.0)
        s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        t = s / max(s[-1], 1e-9)
        th = 0.0015 + 0.25 * widths
        first = len(self.v)
        self.marks.append((first, person_params.grey_mask(k["grey"])))
        u0 = self.u(0, 1)
        for i in range(n):
            cc = lerp(col[0], col[1], smooth((t[i] - 0.35) / 0.65)) / TEX_MEAN
            for a, h in zip(across, profile):
                self.v.append(pts[i] + side[i] * (widths[i] * a) + out[i] * (th[i] * h))
                self.col.append(cc * (1 - 0.22 * abs(a) ** 3))
                self.uv.append((u0 + 0.2 * (a + 1) / 2, 1 - t[i]))
                # The broad face carries one band (out, leaning up); the margins roll to the sides.
                up = np.array([0.0, 0.0, 0.31 + 0.36 * (k["layer"] in (4, 6))])
                c_ = math.cos(a * math.pi / 2)
                self.nrm.append(unit(unit(out[i] + up) * c_ + side[i] * (math.sin(a * math.pi / 2) * (0.74 if k["layer"] in (4, 6) else 0.94))))
            if back:
                self.v.append(pts[i] - out[i] * th[i] * 0.35)
                self.col.append(cc * 0.55)
                self.uv.append((u0 + 0.1, 1 - t[i]))
                self.nrm.append(-out[i])
            self.chain += [-1] * (len(across) + back)
            self.along += [s[i]] * (len(across) + back)
        nr = len(across) + back
        for i in range(n - 1):
            a0, b0 = first + nr * i, first + nr * (i + 1)
            for j in range(nr):
                self.f.append((a0 + j, a0 + (j + 1) % nr, b0 + (j + 1) % nr, b0 + j))
        for end in (0, n - 1):  # each end closed, so the lock is one solid shape for outlines
            r0 = first + nr * end
            ring = [r0 + j for j in range(nr)]
            self.f.append(tuple(ring if end else ring[::-1]))
        if back:
            hl = self.master["highlight"]
            if k["layer"] in hl["layers"]:  # the highlight rule: the master's marked groups, a band along the lock
                b0, b1 = hl["band"]
                for i in range(n):
                    w = smooth((t[i] - b0) / 0.06) * smooth((b1 - t[i]) / 0.06)
                    for j, a in enumerate(across):
                        if w * (1 - abs(a)) > 0.01:
                            v = first + nr * i + j
                            self.hl_marks[v] = max(self.hl_marks.get(v, 0.0), float(w * min(1.0, 2 * (1 - abs(a)))))
            if PAGE_HAIR:
                self._path_lines(k, first, n, nr)

    def _path_lines(self, k, first, n, nr):
        """A path lock's lock lines (SLOP_PORT=hair), as a sheet's (`_lock_lines`): from the tip
        toward the root, one down the lock of its own length and, on a wide lock, a shorter
        companion beside it, each bending a little across. Their own random numbers."""
        cr = random.Random(f"lines/{self.spec.get('seed', 0)}/path/{len(self.creases)}/{k['layer']}")
        lines = [(cr.uniform(-0.25, 0.25), cr.uniform(*LOCK_LINES["notch_len"]) + 0.15)]
        if float(np.max(k["widths"])) > 0.018 and cr.random() < 0.7:
            lines.append((cr.choice((-1, 1)) * cr.uniform(0.45, 0.6), cr.uniform(*LOCK_LINES["mate_len"]) + 0.1))
        for x, share in lines:
            bend = cr.uniform(-0.3, 0.3)
            m = max(4, int(math.ceil(share * n * 2)))
            pts = []
            for tt in np.linspace(0.0, 1.0, m):
                jj = float(np.clip(2.0 + 2.0 * (x + bend * tt ** 2.2), 0.5, 3.5))
                ii = (n - 1) * (1.0 - tt * min(share, 0.95))
                a, b = min(int(jj), 3), min(int(ii), n - 2)
                fa, fb = jj - a, ii - b
                at = lambda j, i: first + nr * i + j
                pts.append([(at(a, b), (1 - fa) * (1 - fb)), (at(a + 1, b), fa * (1 - fb)), (at(a, b + 1), (1 - fa) * fb), (at(a + 1, b + 1), fa * fb)])
            self.creases.append(pts)

    def _braids(self):
        # Two braids from behind the ears, the hair parted down the middle and drawn to each.
        self.braid = []
        deg = np.linspace(62.0, 150.0, 23)
        dirs = np.stack([np.zeros(len(deg)), np.cos(np.radians(deg)), np.sin(np.radians(deg))], axis=1)
        self.partings.append(dict(pts=ORIGIN + dirs * self.hf.radius(dirs)[:, None], deg=deg))
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
        def tris(f0):
            return sum(len(f) - 2 for f in self.f[f0:])

        for k, path, touch in zip(self.locks, paths, touches):
            if k.get("part") in MASTER_DROP:
                continue
            if "sheet" in k:
                sheets.setdefault(k["sheet"][0], []).append((k, path, touch))
                continue
            f0 = len(self.f)
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
            self.part_tris[k.get("part", "locks")] = self.part_tris.get(k.get("part", "locks"), 0) + tris(f0)
            self.part_verts.append((k.get("part", "locks"), first, len(self.v)))
            if k["chain"] >= 0:
                # Free from where it last touches the head.
                head_on = on & (pts[:, 2] > -0.11)
                free_from = s[np.nonzero(head_on)[0].max()] if head_on.any() else 0.0
                chain_pts.setdefault(k["chain"], []).append((pts, s, free_from, first, len(self.v)))
        for sid in sorted(sheets):
            if self.sheets[sid].get("part") in MASTER_DROP:
                continue
            f0, v0 = len(self.f), len(self.v)
            self._sheet_mesh(self.sheets[sid], sheets[sid], base, tipc, silver, grey, chain_pts)
            part = self.sheets[sid].get("part", "sheets")
            self.part_tris[part] = self.part_tris.get(part, 0) + tris(f0)
            self.part_verts.append((part, v0, len(self.v)))
        for k in self.paths:
            if k["part"] in MASTER_DROP:
                continue
            f0, v0 = len(self.f), len(self.v)
            self._path_ribbon(k, base, tipc, silver, grey)
            self.part_tris[k["part"]] = self.part_tris.get(k["part"], 0) + tris(f0)
            self.part_verts.append((k["part"], v0, len(self.v)))
        self._springs(chain_pts)
        if hasattr(self, "bun"):
            f0 = len(self.f)
            self._bun_mesh(base, tipc, silver, grey)
            self.part_tris["bun"] = tris(f0)
        for b in getattr(self, "braid", []):
            f0, v0 = len(self.f), len(self.v)
            self._braid_mesh(b, base, tipc, silver, grey)
            self.part_tris["plait"] = self.part_tris.get("plait", 0) + tris(f0)
            self.part_verts.append(("plait", v0, len(self.v)))
        # The grey mask of every vertex, from the marks set as locks and columns were written.
        self.grey = np.full(len(self.v), person_params.grey_mask(0.5))
        for (a, m), (b, _) in zip(self.marks, self.marks[1:] + [(len(self.v), 0.0)]):
            self.grey[a:b] = m
        self.v = np.array(self.v).reshape(-1, 3)
        self.col = np.clip(np.array(self.col).reshape(-1, 3), 0, 1)
        self.uv = np.array(self.uv).reshape(-1, 2)
        self.nrm = np.array(self.nrm).reshape(-1, 3)
        self.chain = np.array(self.chain, int)
        self.along = np.array(self.along, float)

    def _lock_colour(self, k, base, tipc, silver, grey):
        """A lock's own colour: a tone of the hair's, gone as grey as its place among the head's
        locks makes it. Greying goes lock by lock before it goes all over: the mix is the one
        the client makes from the file's `_GREY` and the person's `grey` (person_params), so a
        person's own file and the same person composed from a shared style grey alike. The
        vertices that follow carry the lock's mask."""
        c = base * (1 + 0.04 * k["tone"] + k["shade"])
        t = tipc * (1 + 0.04 * k["tone"] + k["shade"])
        mask = person_params.grey_mask(k["grey"])
        if not k.get("column"):
            self.marks.append((len(self.v), mask))
        if grey > 0.02:
            mixk = float(np.clip(person_params.grey_amount(grey) * mask, 0, 1))
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
        # Each column has its own place in the greying, so a sheet greys in streaks a column wide
        # and not a whole point at a time.
        places = [self.rng.random() for _ in range(M)]
        for j in range(M):
            tone, _ = sp["tone"][sp["q"][j]]
            cb[j], ct[j] = self._lock_colour(dict(tone=0.6 * tone, shade=sp["shade"], grey=places[j], column=True), base, tipc, silver, grey)
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
        if PAGE_HAIR and HAIR_LOOK == "b1" and not tube:
            N = self._lock_round(sp, C, SIDE, N, T)
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
            self.marks.append((first, person_params.grey_mask(places[jj])))
            for i in range(R + 1):
                self.v += [F[jj, i], B[jj, i]]
                self.col += [col[jj, i], col[jj, i] * 0.55]
                self.uv += [(U[j], 1 - T[i]), (U[j], 1 - T[i])]
                self.nrm += [N[jj, i], -OUT[jj, i]]
                self.along += [S[jj, i], S[jj, i]]
            ch = cols[jj][0]["chain"]
            self.chain += [ch] * nr
            if ch >= 0:
                if sp.get("hang"):
                    self.hang_chains.add(ch)
                # Free from where it last touches the head.
                head_on = ON[jj] & (C[jj][:, 2] > -0.11)
                free_from = S[jj][np.nonzero(head_on)[0].max()] if head_on.any() else 0.0
                chain_pts.setdefault(ch, []).append((C[jj], S[jj], free_from, first, first + nr))
        at = lambda j, i, back: v0 + j * nr + 2 * i + back
        if PAGE_HAIR and self.detail >= 1:
            self._lock_lines(sp, kk, M, R, at)
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

    def _lock_lines(self, sp, kk, M, R, at):
        """A sheet's lock lines (SLOP_PORT=hair), grouped into locks (LOCK_LINES): from the hem
        toward the root, up each notch and beside it inside the lock, of uneven lengths, bending
        across. Never on the sheet's own edge columns, so a line keeps its distance from the
        island's border. Their own random numbers, so the hair's shape does not change."""
        if M < 3 or R < 2:
            return
        cr = random.Random(f"lines/{self.spec.get('seed', 0)}/{sp['u0']:.9f}/{len(self.creases)}")
        q = list(sp["q"])
        lines = []  # (start column, its bend, length share)
        tips = {}
        for j in range(M):
            if q[j] not in tips or kk[j] < kk[tips[q[j]]]:
                tips[q[j]] = j
        for j in range(1, M - 1):
            if kk[j] < CREASE["notch"]:
                continue
            bend = cr.uniform(-1, 1) * LOCK_LINES["drift"]
            lines.append((float(j), bend, cr.uniform(*LOCK_LINES["notch_len"])))
            # Inside the locks either side of this notch: companions, toward each lock's tip.
            for side in (-1, 1):
                jt = tips.get(q[j] if side > 0 else q[j - 1] if j > 0 else q[j])
                if jt is None or jt == j:
                    continue
                for _ in range(cr.choice(LOCK_LINES["mates"])):
                    j0 = j + (jt - j) * cr.uniform(*LOCK_LINES["mate_at"])
                    lines.append((j0, 0.6 * bend + cr.uniform(-0.15, 0.15), cr.uniform(*LOCK_LINES["mate_len"])))
        for j0, bend, share in lines:
            n = max(4, int(math.ceil(share * R * 3)))
            pts = []
            for t in np.linspace(0.0, 1.0, n):
                jj = float(np.clip(j0 + bend * t ** 2.2, 1.0, M - 2.0))
                ii = R - t * share * R
                a, b = min(int(jj), M - 2), min(int(ii), R - 1)
                fa, fb = jj - a, ii - b
                pts.append([(at(a, b, 0), (1 - fa) * (1 - fb)), (at(a + 1, b, 0), fa * (1 - fb)), (at(a, b + 1, 0), (1 - fa) * fb), (at(a + 1, b + 1, 0), fa * fb)])
            self.creases.append(pts)

    def _lock_round(self, sp, C, SIDE, N, T):
        """b1: each lock (a point of the sheet's hem, notch to notch) shaded as a low cylinder:
        its normals turned across it, out toward its sides, more toward the hem than at the root,
        each lock by its own amount, so the bands' edges break lock by lock."""
        u, q = np.array(sp["u"]), list(sp["q"])
        M = len(u)
        if len(set(q)) < 2:  # a sheet without points (drawn to a tie): one smooth surface
            return N
        starts = {}
        for j in range(M):
            starts.setdefault(q[j], u[j])
        a = np.zeros(M)
        for j in range(M):
            lo = starts[q[j]]
            hi = starts.get(q[j] + 1, starts[q[0]] + 1.0 if sp["loop"] else u[-1])  # a closed sheet's last lock runs round to its first
            a[j] = 2.0 * (u[j] - lo) / max(hi - lo, 1e-9) - 1.0
        gain = [0.7 + 0.6 * ((i * 0.618034 + sp["u0"]) % 1.0) for i in range(max(q) + 1)]
        # Which way across is out of the lock: SIDE's sign against the way u runs.
        across = np.gradient(C[:, :, :], axis=0)
        sgn = np.sign(np.einsum("jik,jik->ji", across, SIDE))
        amp = LOCK_ROUND * smooth(T / 0.30)[None, :] * np.array([gain[k] for k in q])[:, None] * a[:, None] * sgn
        return unit(N + SIDE * amp[..., None])

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
            rows = []
            for j in range(m + 1):
                at = reach * j / m
                ps = []
                for pts, s, f, _, _ in locks:
                    q = min(f + at, s[-1])
                    ps.append([np.interp(q, s, pts[:, k]) for k in range(3)])
                rows.append(np.array(ps))
            joints = [r.mean(axis=0) for r in rows]
            if ci in self.hang_chains:
                # Hair that lies on the back: the joints are one of its own columns, the one
                # nearest the mean. The mean of an arc of columns lies inside the arc, in the
                # body, and the game holds the joints, not the surface, out of the body's spheres.
                mid = int(np.argmin(sum(np.linalg.norm(r - c, axis=1) for r, c in zip(rows, joints))))
                joints = [r[mid] for r in rows]
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
        mp = b.get("master")  # a master's plait (MASTERS[...]["plait"]); None for the styles' own
        lift = b.get("radius", 0) * mp["seat"] + mp["root_lift"] if mp else max(.016, b.get("radius", 0) * 1.55)
        self.lock(0, 0, b["d"], root=b["p"], length=b["length"], width=0.03, lift=lift, g=30.0)
        (path,), (touch,) = self._walk()
        self.locks = keep
        if "radius" in b:
            # The type rig scales a hair chain about the skull while the chest
            # scales about the spine. Ease the fitted plait over the upper back.
            path[:, 1] -= self.comb.b.get("braid_ease", 0) * np.clip((path[0, 2] - path[:, 2]) / .080, 0, 1)
        n = max(4, int(b["length"] / 0.012))
        pts, on, s = self._resample(path, touch, n)
        tan, out, side = self._frame(pts, on)
        ci = len(self.chains)
        m = int(np.clip(round(s[-1] / 0.09), 1, 4))
        self.chains.append(dict(name=f"Braid{ci}", joints=[np.array([np.interp(s[-1] * j / m, s, pts[:, q]) for q in range(3)]) for j in range(m + 1)], step=s[-1] / m))
        if "radius" in b:
            radius = b["radius"]
            self.rope_chains[ci] = radius
            turns = mp["turns"] if mp else max(1, round(s[-1] / (7 * radius)))
            points, contact, along = self._resample(path, touch, int(round(turns * (14 if self.detail >= 1 else 8))))
            _, outward, across = self._frame(points, contact)
            u = along / along[-1]
            if mp:
                # Cora's plait (plait/fit.py): narrowing to the tie, fuller over its first few
                # centimetres, the upper lobes widened by `gain`, falling to none before the tie.
                r = radius * (1 - mp["taper"] * u) * (0.60 + 0.40 * smooth(u / 0.14) if mp.get("full_from", 0.14) > 0 else 1.0)
                wide = 1 + mp["gain"] * (1 - smooth((u - mp["gain_span"][0]) / (mp["gain_span"][1] - mp["gain_span"][0])))
            else:
                r = radius * (1 - 0.59 * u)
                wide = None
            # Cora's alternating over/under path, measured along the combed spine.
            for strand in range(3):
                phase = math.tau * (turns * u + strand / 3)
                centres = (points + across * (r * (wide if wide is not None else 1) * np.sin(phase))[:, None]
                           + outward * ((mp["depth"][1] if mp else 0.68) * r * np.sin(2 * phase))[:, None])
                colours = self._lock_colour(dict(tone=strand-1, shade=0, grey=self.rng.random()),
                                            base, tipc, silver, grey)
                self._plait_tube(centres, across, outward, r, along, ci, colours, wide=wide, crest=np.sin(2 * phase) if (mp and mp.get("crest")) else None, deep=mp["depth"][0] if mp else 0.72,
                                 crest_shape=(mp["crest_up"], mp["crest_lit"]) if mp else ((0.52, 0.32), (0.35, 0.35)))
            # The binding and brush share the plait's material and last joint.
            offsets = radius * np.array([0, .25, .50, .65, 1.30, 1.85, 2.55])
            radii = radius * np.array([.54, .56, .54, .40, .63, .49, .035])
            tip = points[-1] + offsets[:, None] * tan[-1]
            for rows, colour in ((slice(0, 3), base * .48), (slice(2, None), tipc)):
                count = len(tip[rows])
                self._plait_tube(tip[rows], np.tile(across[-1], (count, 1)),
                                 np.tile(outward[-1], (count, 1)), radii[rows],
                                 np.full(count, along[-1]), ci, (colour, colour))
            return
        self.rope_chains[ci] = 0.013
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

    def _plait_tube(self, centres, across, outward, radii, along, chain, colours, wide=None, crest=None, crest_shape=((0.52, 0.32), (0.35, 0.35)), deep=0.72):
        """A plait's strand as a tube. `wide` widens it across (a master's upper lobes); `crest`
        (how far the strand is over its neighbours, per ring: sin 2 phase) lights the top of each
        crossing: normals up the lobe as Cora's (plait/fit.py), and a highlight on its crest
        (`hl_marks`), in place of her second, lighter material."""
        sides = 6
        start = len(self.v)
        up = np.array([0.0, 0.0, 1.0])
        for i, centre in enumerate(centres):
            w = 1.0 if wide is None else float(wide[i])
            for j in range(sides):
                angle = math.tau * j / sides
                a, b = math.cos(angle), math.sin(angle)
                self.v.append(centre + radii[i] * (.81 * a * w * across[i] + deep * b * outward[i]))
                if crest is None:
                    self.nrm.append(unit(a * across[i] + b * outward[i]))
                else:
                    cu, cl = crest_shape
                    self.nrm.append(unit(b * outward[i] + 0.79 * a * across[i] + up * (cu[0] + cu[1] * b)))
                    lit = smooth((float(crest[i]) - cl[0]) / 0.30) * smooth((b - cl[1]) / 0.30)
                    if lit > 0:
                        self.hl_marks[len(self.v) - 1] = max(self.hl_marks.get(len(self.v) - 1, 0.0), lit)
                self.col.append(lerp(*colours, i / (len(centres)-1)))
                self.uv.append((j / sides, 1 - i / (len(centres)-1)))
                self.chain.append(chain)
                self.along.append(along[i])
                if i:
                    k = start + i * sides
                    nxt = (j + 1) % sides
                    self.f.append((k-sides+j, k+j, k+nxt, k-sides+nxt))
        self.f.append(tuple(start + j for j in range(sides)))
        last = start + (len(centres) - 1) * sides
        self.f.append(tuple(last + j for j in reversed(range(sides))))


# --- the hair-mask page (SLOP_PORT=hair) ---------------------------------------------------------
def highlight(hf, pts, nrm):
    """The highlight mask a hair vertex takes (0..1): a band round the upper hair, from about 4 to
    7.5 cm under the top of the head, its lower edge scalloped, on the front and sides, on surfaces
    that face out (a lock's underside and a sheet's back take none). Head frame, as `Hair.v`."""
    p = np.asarray(pts, float).reshape(-1, 3)
    n = np.asarray(nrm, float).reshape(-1, 3)
    if not len(p):
        return np.zeros(0)
    az = np.degrees(np.arctan2(-p[:, 0], p[:, 1]))
    radial = unit(p - np.array([0.0, -0.012, 0.0]))
    facing = np.einsum("ij,ij->i", n, radial)
    top = hf.top_z
    hi = top - 0.040
    lo = top - 0.075 + 0.007 * np.cos(np.radians(az) * 9.0)
    soft = 0.004
    band = smooth((p[:, 2] - lo) / soft) * smooth((hi - p[:, 2]) / soft)
    return band * smooth((facing - 0.15) / 0.2) * smooth((140.0 - np.abs(az)) / 25.0)


def _pack(boxes, W, H):
    """Pack boxes (w, h) into W x H with the padding: a skyline, each box (largest first) at the
    lowest place it fits, either way round. [(x, y, turned)] or None."""
    pad = ISLAND_PAD_PX
    sky = [(pad, pad, W - pad)]  # segments (x0, y, x1) of the skyline
    out = [None] * len(boxes)
    for k in sorted(range(len(boxes)), key=lambda k: -(boxes[k][0] * boxes[k][1])):
        best = None
        for turned in (False, True):
            w, h = (boxes[k][1], boxes[k][0]) if turned else boxes[k]
            w, h = int(math.ceil(w)), int(math.ceil(h))
            for i, (x0, _, _) in enumerate(sky):
                if x0 + w + pad > W:
                    break
                # The box rests on the highest segment under its width.
                y, x, j = 0, x0, i
                while j < len(sky) and sky[j][0] < x0 + w + pad:
                    y = max(y, sky[j][1])
                    j += 1
                if y + h + pad > H:
                    continue
                if best is None or (y + h, x0) < (best[0] + best[3], best[1]):
                    best = (y, x0, turned, h, w)
        if best is None:
            return None
        y, x0, turned, h, w = best
        out[k] = (x0, y, turned)
        top = y + h + pad
        x1 = x0 + w + pad
        new = []
        for a, yy, b in sky:
            if b <= x0 or a >= x1:
                new.append((a, yy, b))
                continue
            if a < x0:
                new.append((a, yy, x0))
            if b > x1:
                new.append((x1, yy, b))
        new.append((x0, top, x1))
        sky = sorted(new)
    return out


def page_layout(verts, faces, uvs, near=None, planar_first=True):
    """Lay a hair object out on the page at 1 mm a texel: each piece (a connected run of faces) by
    its own lengths, its present UVs scaled along and across to metres (the strands' mapping runs
    across a piece and root to tip); the first piece, the scalp's cap, seen from above. The pieces
    are packed into the smallest of 1 x 1, 2 x 1, 1 x 2 and 2 x 2 page cells (512 texels) that holds
    them with the contract's padding, a piece turned a quarter where that is the only way it fits;
    a file that needs more is laid out larger and the page tool refuses it. Returns (uvs in texels
    from the rectangle's top-left, x right and y down; the rectangle's size in texels; the layout,
    which `near` passes to the far mesh's call so its pieces land where the near mesh's do)."""
    V = np.asarray(verts, float)
    U = np.asarray(uvs, float)
    parent = list(range(len(V)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for f in faces:
        r = find(f[0])
        for v in f[1:]:
            q = find(v)
            if q != r:
                parent[q] = r
    roots = {}
    piece = np.array([roots.setdefault(find(i), len(roots)) for i in range(len(V))])
    # Pieces in the order of their first face, so the near and far meshes number them alike.
    order = []
    for f in faces:
        k = piece[f[0]]
        if k not in order:
            order.append(k)
    rank = {k: i for i, k in enumerate(order)}
    piece = np.array([rank.get(k, len(order)) for k in piece])
    # The far mesh's pieces are not the near mesh's one for one (its locks are fewer and thinner):
    # each takes the near piece most of its vertices lie nearest to, and that piece's scale, gain,
    # origin and place.
    match = list(range(len(order)))
    if near is not None:
        NV, NP = np.asarray(near["verts"], float), np.asarray(near["piece"])
        for k in range(len(order)):
            ids = np.nonzero(piece == k)[0]
            if (k == 0 and planar_first) or not (NP > 0).any():
                match[k] = 0
                continue
            d = ((V[ids, None, :] - NV[None, NP > 0, :]) ** 2).sum(-1)
            match[k] = int(np.bincount(NP[NP > 0][d.argmin(1)]).argmax())
    local = {}
    scales, gains, origins = [], [], []
    for k in range(len(order)):
        ids = np.nonzero(piece == k)[0]
        if k == 0 and planar_first:
            m = np.stack([V[ids, 0], -V[ids, 1]], 1) / TEXEL_M  # the cap from above
            su = sv = None
        else:
            fs = [f for f in faces if piece[f[0]] == k]
            e = np.array([(f[i], f[(i + 1) % len(f)]) for f in fs for i in range(len(f))])
            d3 = np.linalg.norm(V[e[:, 1]] - V[e[:, 0]], axis=1)
            du, dv = np.abs(U[e[:, 1], 0] - U[e[:, 0], 0]), np.abs(U[e[:, 1], 1] - U[e[:, 0], 1])
            across, along = (du > 3 * dv) & (du > 1e-9), (dv > 3 * du) & (dv > 1e-9)
            su = float(np.median(d3[across] / du[across])) if across.any() else 0.05
            sv = float(np.median(d3[along] / dv[along])) if along.any() else 0.05
            if near is not None and near["scale"][match[k]][0] is not None:
                su, sv = near["scale"][match[k]]  # the far mesh: the near piece's own scale
            m = np.stack([U[ids, 0] * su, -U[ids, 1] * sv], 1) / TEXEL_M  # v up in the strands' mapping; texels down
        # Each piece at the page's density where most of it lies: its triangles' median
        # density made exactly 1 mm a texel (the cap seen from above is coarse at its sides; a
        # piece whose columns spread as they hang is finer at its root).
        if near is None:
            fs = [f for f in faces if piece[f[0]] == k]
            pos = {v: i for i, v in enumerate(ids)}
            tri = np.array([(f[0], f[i], f[i + 1]) for f in fs for i in range(1, len(f) - 1)])
            a3 = np.linalg.norm(np.cross(V[tri[:, 1]] - V[tri[:, 0]], V[tri[:, 2]] - V[tri[:, 0]]), axis=1)
            t2 = np.array([[pos[v] for v in t] for t in tri])
            e1, e2 = m[t2[:, 1]] - m[t2[:, 0]], m[t2[:, 2]] - m[t2[:, 0]]
            a2 = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
            ok = (a2 > 1e-9) & (a3 > 1e-12)
            gain = float(np.median(np.sqrt(a3[ok] / a2[ok]))) / TEXEL_M if ok.any() else 1.0
        else:
            gain = near["gain"][match[k]]
        m = m * gain
        # The far mesh takes the near piece's origin, so a point both meshes share lands on the
        # same texel; what of a far piece runs past its near piece's box is held at the box.
        o = m.min(0) if near is None else np.asarray(near["origin"][match[k]], float)
        local[k] = (ids, m - o)
        scales.append((su, sv))
        gains.append(gain)
        origins.append(m.min(0).tolist())
    if near is None:
        boxes = [tuple(np.ptp(local[k][1], axis=0) + 1.0) for k in range(len(order))]
        cell = PAGE_PX // 8
        for cw, ch in ((1, 1), (2, 1), (1, 2), (2, 2)):
            place = _pack(boxes, cw * cell, ch * cell)
            if place:
                size = (cw * cell, ch * cell)
                break
        else:
            side = int(math.ceil(math.sqrt(sum((w + ISLAND_PAD_PX) * (h + ISLAND_PAD_PX) for w, h in boxes)) * 1.3))
            W = max(side, int(max(min(w, h) for w, h in boxes)) + 2 * ISLAND_PAD_PX)
            H = W
            while not (place := _pack(boxes, W, H)):
                H += cell // 4
            size = (W, H)
        near = dict(scale=scales, gain=gains, origin=origins, place=place, size=size, boxes=boxes, verts=V, piece=piece)
    out = np.zeros((len(V), 2))
    for k, (ids, m) in local.items():
        x, y, turned = near["place"][match[k]]
        m = np.clip(m, 0.0, np.asarray(near["boxes"][match[k]], float) - 1.0)
        if turned:
            w = near["boxes"][match[k]][0]
            m = np.stack([m[:, 1], w - 1.0 - m[:, 0]], 1)
        out[ids] = m + np.array([x, y], float)
    return out, near["size"], near
