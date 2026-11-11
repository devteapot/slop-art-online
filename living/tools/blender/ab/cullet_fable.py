"""Cullet asset A/B, the Fable arm: the Cone, a Low Row terrace, a Ladder glasshouse and the
eight Strand props (docs/SMALL_CITY.md, sections 1 and 7).

Run headless:
    blender -b -P living/tools/blender/ab/cullet_fable.py -- --out DIR --seed 1 [--only cone,row]

Writes eleven GLB files and `report.json` (footprint, height, triangles and the checks of each
model) to DIR. The same seed gives the same files.

Conventions, as buildings.py: metres, +Z up, fronts face -Y, the origin at the floor and centred
on the footprint. Colour is per vertex ("Color") on one white "Body" material with the surface
tag in alpha; glowing parts are on "Glow" (oil lamp) or "GlowAmber" (the furnace) and carry
their daytime glass colour. Buildings stand on a stepped basalt foundation 1.8 m deep, props on
0.4 m. No textures, no external files.

Colour: every part takes a palette colour of section 1 (P), jittered by at most 0.05. Wear is a
second palette colour laid over the first by a named cause (the `wear` of each model: salt,
soot, wind, repair, empty), never a random tint: soot is tar, bloom is pale basalt, repairs are
new slate, new brick or driftwood boards.

Compass: the front (-Y) is south, towards the harbour. West is -X. The wind is south-westerly,
so the weather side is -X and -Y, and soot drifts to +X and +Y.

Footprints are everything above the floor, as the settlement table measures them: the row's
pavement, stoops, eaves and lean-to lie inside 22.0 x 7.5 m, and the glasshouse's rain butt,
kelp heap and cold frame inside 12.0 x 4.5 m.
"""

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
from types import SimpleNamespace as NS

import bmesh
import bpy
from mathutils import Matrix, Vector, noise

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import buildings as B  # noqa: E402
from buildings import X, Y, Z, Face, Kit, box, lbox, prism, sphere, surface_alpha, tagged, wall_skin  # noqa: E402

TAU, PI = math.tau, math.pi
rad, sin, cos = math.radians, math.sin, math.cos

# The palette of section 1 (sRGB), each colour with its painted surface.
P = NS(**{name: tagged(c, s) for name, (c, s) in dict(
    basalt=((0.24, 0.25, 0.28), "stone"), pale=((0.36, 0.37, 0.39), "stone"),
    lime=((0.90, 0.89, 0.84), "plaster"), oldlime=((0.78, 0.77, 0.71), "plaster"),
    slate=((0.30, 0.34, 0.40), "shingles"), newslate=((0.38, 0.43, 0.50), "shingles"),
    lichen=((0.72, 0.66, 0.30), "stone"), tar=((0.13, 0.12, 0.12), "planks"), drift=((0.52, 0.50, 0.46), "wood"),
    brick=((0.33, 0.20, 0.17), "brick"), newbrick=((0.58, 0.30, 0.22), "brick"),
    iron=((0.17, 0.17, 0.19), "metal"), rust=((0.50, 0.27, 0.15), "metal"), verdigris=((0.36, 0.62, 0.55), "copper"),
    green=((0.20, 0.42, 0.30), "glass"), amber=((0.78, 0.50, 0.16), "glass"), aqua=((0.62, 0.80, 0.78), "glass"),
    smoke=((0.55, 0.60, 0.62), "glass"), cobalt=((0.16, 0.26, 0.60), "glass"),
    oxblood=((0.45, 0.14, 0.13), "planks"), mustard=((0.78, 0.60, 0.18), "planks"),
    seagreen=((0.22, 0.45, 0.42), "planks"), chalkblue=((0.50, 0.62, 0.72), "planks"),
    kelp=((0.30, 0.28, 0.12), "leaves"), sand=((0.86, 0.82, 0.70), "earth"), peat=((0.20, 0.15, 0.11), "earth"),
    grass=((0.52, 0.50, 0.28), "leaves"), heather=((0.50, 0.34, 0.48), "leaves")).items()})
# Light (the emission of the glow materials): oil lamps and the furnace.
LIGHT = {"Glow": ((1.0, 0.74, 0.40), 2.6), "GlowAmber": ((1.0, 0.45, 0.12), 4.5)}
BUDGET = dict(cone=12000, row=16000, glasshouse=9000, boat=2500)  # triangles; the other props 1,500


# ---------------------------------------------------------------------------------------------
# Colour


def on(c, surface):
    """The colour on another surface (limewash paint on wood)."""
    return tagged(tuple(c), surface)


def mix(a, b, t):
    """a with b laid over it by t: wear keeps the surface of what it lies on."""
    t = min(1.0, max(0.0, t))
    return tagged(tuple(x + (y - x) * t for x, y in zip(a, b)), getattr(a, "surface", None))


def jit(c, rng, k=0.035):
    """One part's own shade: at most 0.05 from the palette."""
    d = rng.uniform(-k, k)
    return tagged(tuple(min(1.0, max(0.0, x + d + rng.uniform(-0.012, 0.012))) for x in c), getattr(c, "surface", None))


def nz(x, y, z=0.0):
    """Smooth noise in -1..1: where blotches of wear lie (the same for every seed's geometry)."""
    return noise.noise(Vector((x, y, z)))


LEAF = mix(P.grass, on(P.green, "leaves"), 0.5)  # greens under glass: moor grass and bottle green


# ---------------------------------------------------------------------------------------------
# Mesh building, on buildings.py's Builder


def glow_mat(k, name):
    colour, strength = LIGHT[name]
    return k.glow_mat if name == "Glow" else B.material(name, (1, 1, 1), emission=colour, strength=strength)


def put(k, bm, col, glow=None, soft=None, closed=True):
    """Add a part: `col` is its colour, or a function of (position, normal)."""
    k.b.add(bm, glow_mat(k, glow) if glow else k.body, col if callable(col) else (lambda co, n: col), soft, closed)


def raw(k, polys, glow=None, two=False):
    """Add flat faces [(points, colour)], each wound as given (`two`: seen from both sides)."""
    b = k.b
    mat = glow_mat(k, glow) if glow else k.body
    if mat not in b.mats:
        b.mats.append(mat)
    idx = b.mats.index(mat)
    for pts, c in polys:
        for ring in ((pts, pts[::-1]) if two else (pts,)):
            try:
                f = b.bm.faces.new([b.bm.verts.new(q) for q in ring])
            except ValueError:
                continue
            f.material_index = idx
            a = surface_alpha(getattr(c, "surface", None))
            for loop in f.loops:
                loop[b.col] = (*c, a)


def oriented(pts, n):
    """The points wound to face n."""
    pts = [Vector(q) for q in pts]
    nn = Vector((0, 0, 0))
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        nn += Vector(((a.y - b.y) * (a.z + b.z), (a.z - b.z) * (a.x + b.x), (a.x - b.x) * (a.y + b.y)))
    return pts if nn.dot(n) >= 0 else pts[::-1]


def moved(bm, M):
    bmesh.ops.transform(bm, matrix=M, verts=bm.verts)
    return bm


def lathe(prof, sides=10, M=None, caps=(True, True)):
    """Rings of a profile [(r, z)] round +Z, then placed by M."""
    bm = bmesh.new()
    rings = [[bm.verts.new((cos(i / sides * TAU) * r, sin(i / sides * TAU) * r, z)) for i in range(sides)] for r, z in prof]
    for lo, hi in zip(rings, rings[1:]):
        for i in range(sides):
            j = (i + 1) % sides
            bm.faces.new([lo[i], lo[j], hi[j], hi[i]])
    if caps[0]:
        bm.faces.new(rings[0][::-1])
    if caps[1]:
        bm.faces.new(rings[-1])
    return moved(bm, M) if M else bm


def tube(pts, r, sides=4, caps=True):
    """A tube along a line of points (rope, pipe, pole); r may be one radius per point."""
    pts = [Vector(q) for q in pts]
    rs = r if isinstance(r, (list, tuple)) else [r] * len(pts)
    bm = bmesh.new()
    rings, u = [], None
    for i, q in enumerate(pts):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        if u is None:
            u = t.cross(Z if abs(t.z) < 0.9 else X).normalized()
        u = (u - t * u.dot(t)).normalized()
        v = t.cross(u)
        rings.append([bm.verts.new(q + (u * cos(j / sides * TAU) + v * sin(j / sides * TAU)) * rs[i]) for j in range(sides)])
    for lo, hi in zip(rings, rings[1:]):
        for i in range(sides):
            j = (i + 1) % sides
            bm.faces.new([lo[i], lo[j], hi[j], hi[i]])
    if caps:
        bm.faces.new(rings[0][::-1])
        bm.faces.new(rings[-1])
    return bm


def beam(p0, p1, w, h, up=Z):
    """A sawn timber from p0 to p1, w wide and h deep."""
    p0, p1 = Vector(p0), Vector(p1)
    t = (p1 - p0).normalized()
    side = Vector(up).cross(t)
    side = (side if side.length > 1e-4 else X.cross(t)).normalized()
    u = t.cross(side)
    return lbox(Vector((0, -w / 2, -h / 2)), Vector(((p1 - p0).length, w / 2, h / 2)), fn=lambda q: p0 + t * q.x + side * q.y + u * q.z)


def ribbon(pts, w, side):
    """Flat strip quads along a line of points, w wide across `side`."""
    out = []
    for a, b in zip(pts, pts[1:]):
        s = Vector(side) * (w / 2)
        out.append([a - s, a + s, b + s, b - s])
    return out


def fit(k, w=None, d=None, h=None):
    """Scale the model by a hair so that it measures exactly w x d x h, centred, on the floor."""
    vs = k.b.bm.verts
    lo = Vector([min(v.co[i] for v in vs) for i in range(3)])
    hi = Vector([max(v.co[i] for v in vs) for i in range(3)])
    s = [(want / (hi[i] - lo[i]) if want else 1.0) for i, want in enumerate((w, d, None))] + [1.0]
    s[2] = h / hi.z if h else 1.0
    assert all(0.9 < x < 1.1 for x in s), f"fit would distort: {s}"
    M = Matrix.Diagonal(s) @ Matrix.Translation((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, 0))
    bmesh.ops.transform(k.b.bm, matrix=M, verts=vs)
    k.b.centres = [M @ c for c in k.b.centres]


def found(k, depth):
    """The stepped basalt foundation under the ground outline, `depth` below the floor."""
    hull = B.convex_hull([(v.co.x, v.co.y) for v in k.b.bm.verts if v.co.z <= 0.05])
    if len(hull) < 3:
        return
    cx, cy = sum(q[0] for q in hull) / len(hull), sum(q[1] for q in hull) / len(hull)
    n = max(2, round(depth / 0.6))
    polys = []
    for i in range(n):
        ring = []
        for x, y in hull:
            l = max(math.hypot(x - cx, y - cy), 1e-6)
            ring.append((x + (x - cx) / l * 0.02 * i, y + (y - cy) / l * 0.02 * i))
        z1, z0 = -0.01 - (depth - 0.01) * i / n, -0.01 - (depth - 0.01) * (i + 1) / n
        c = jit(P.pale if i % 2 else P.basalt, k.pr, 0.02)
        polys.append(([Vector((x, y, z1)) for x, y in ring], c))
        for a, b in zip(ring, ring[1:] + ring[:1]):
            polys.append(([Vector((*a, z0)), Vector((*b, z0)), Vector((*b, z1)), Vector((*a, z1))], c))
    polys.append(([Vector((x, y, z0)) for x, y in ring][::-1], c))
    raw(k, polys)


# ---------------------------------------------------------------------------------------------
# Parts shared between the models


def blocks(k, rng, f, a0, a1, z0, z1, th, col, alt=None, p_alt=0.0, course=0.35, cut=(0.7, 1.2), back=True):
    """Coursed stone on wall face f, th thick behind the face, each block its own shade (`alt`
    with chance `p_alt`: bloom, lichen, a repair)."""
    n = max(1, round((z1 - z0) / course))
    for i in range(n):
        za, zb = z0 + (z1 - z0) * i / n, z0 + (z1 - z0) * (i + 1) / n
        a = a0
        while a < a1 - 1e-6:
            b = a + rng.uniform(*cut) * (0.5 if i % 2 and a == a0 else 1.0)
            b = a1 if a1 - b < 0.35 else b
            c = alt if alt is not None and rng.random() < p_alt else col
            put(k, f.box(a + 0.008, b - 0.008, za, zb - 0.012, -th, 0.0, back=back), jit(c, rng))
            a = b


def slates(k, rng, fn, a0, a1, S, state, course=0.44, cut=(0.55, 1.0), th=0.05):
    """A slope of slates on a tarred deck. fn(a, t, h): a along the ridge, t down the slope, h
    above the deck. state(a, t) is a slate's colour, or None where it is missing."""
    N = (fn(a0, 0, 1) - fn(a0, 0, 0)).normalized()
    D = (fn(a0, 1, 0) - fn(a0, 0, 0)).normalized()
    nd = max(1, round((a1 - a0) / 0.9))
    for i in range(nd):  # the deck in short lengths, so that it follows a sagging ridge
        put(k, lbox(Vector((a0 + (a1 - a0) * i / nd, -0.04, -0.12)), Vector((a0 + (a1 - a0) * (i + 1) / nd, S - 0.03, 0.0)), fn=lambda q: fn(q.x, q.y, q.z)), P.tar)
    n = max(2, round(S / course))
    polys = []
    for i in range(n):
        t0, t1 = S * i / n, S * (i + 1) / n
        a = a0
        while a < a1 - 1e-6:
            b = a + rng.uniform(*cut)
            b = a1 if a1 - b < 0.3 else b
            c = state((a + b) / 2, (t0 + t1) / 2)
            e = t1 - rng.uniform(0.0, 0.03)
            if c is not None:
                top = [fn(a + 0.008, max(0.0, t0 - 0.04), 0.012), fn(b - 0.008, max(0.0, t0 - 0.04), 0.012), fn(b - 0.008, e, th), fn(a + 0.008, e, th)]
                polys.append((oriented(top, N), c))
                polys.append((oriented([top[3], top[2], fn(b - 0.008, e, 0.0), fn(a + 0.008, e, 0.0)], D), mix(c, P.tar, 0.3)))
            a = b
    raw(k, polys)


def pane_grid(k, rng, pt, nu, nv, cu, cv, pick, bar=0.05, back=None, glow=None, two=False, lift=0.015):
    """Small panes, nu x nv in cells of cu x cv. pt(u, v, w) is a point of the window (w out);
    pick(i, j) is a pane's colour or None for a hole. `back` is the colour of the glazing bars,
    drawn as one sheet behind the panes."""
    if back is not None:
        raw(k, [([pt(0, 0, 0), pt(nu * cu, 0, 0), pt(nu * cu, nv * cv, 0), pt(0, nv * cv, 0)], back)])
    lit, unlit = [], []
    for i in range(nu):
        for j in range(nv):
            c = pick(i, j)
            if c is None:
                continue
            q = [pt(i * cu + bar / 2, j * cv + bar / 2, lift), pt((i + 1) * cu - bar / 2, j * cv + bar / 2, lift),
                 pt((i + 1) * cu - bar / 2, (j + 1) * cv - bar / 2, lift), pt(i * cu + bar / 2, (j + 1) * cv - bar / 2, lift)]
            (lit if glow and c.surface == "glass" else unlit).append((q, c))
    raw(k, unlit, two=two)
    raw(k, lit, glow=glow, two=two)


def glazing(rng, main, odd=None, n_odd=0, cells=(), boards=(), gone=()):
    """A window's panes: `main` glass with n_odd panes of `odd` (at most two glass colours in a
    window), boards over `boards` and holes at `gone`."""
    cells = list(cells)
    odd_at = set(rng.sample(cells, min(n_odd, len(cells)))) if odd is not None else set()
    shade = {c: jit(odd if c in odd_at else main, rng, 0.03) for c in cells}
    hole = on(P.tar, "glass")
    return lambda i, j: hole if (i, j) in gone else jit(P.drift, rng) if (i, j) in boards else shade[(i, j)]


def window(k, rng, f, a, z0, grid, pick, lit=False, recess=0.2, bars=None, sill=P.pale):
    """A small-paned window in a hole of wall face f (centre a, sill z0); returns the hole."""
    nu, nv, cu, cv = grid
    w, h = nu * cu, nv * cv
    bars = bars if bars is not None else on(P.oldlime, "wood")
    pane_grid(k, rng, lambda u, v, o: f.p(a - w / 2 + u, z0 + v, o - recess), nu, nv, cu, cv, pick, back=jit(bars, rng, 0.02), glow="Glow" if lit else None)
    if sill is not None:
        put(k, f.box(a - w / 2 - 0.1, a + w / 2 + 0.1, z0 - 0.13, z0, -recess, 0.08), jit(sill, rng))
        put(k, f.box(a - w / 2 - 0.16, a + w / 2 + 0.16, z0 + h, z0 + h + 0.24, 0.0, 0.035, back=False), jit(sill, rng))
    return (a - w / 2, a + w / 2, z0, z0 + h)


def wall(k, rng, f, z0, z1, col, holes=(), reveal=None, depth=0.2):
    """A wall face with its openings cut through and their reveals."""
    skin, rev = wall_skin(f, z0, z1, list(holes), depth)
    put(k, skin, col, closed=False)
    put(k, rev, reveal if reveal is not None else mix(col, P.basalt, 0.25), closed=False)


def blotch(f, a, z, r, rng, w=0.012, n=7, tall=1.0):
    """An irregular patch on a wall face: flaked lime, lichen, bloom, a soot stain."""
    return [f.p(a + cos(i / n * TAU) * r * rng.uniform(0.5, 1.0), z + sin(i / n * TAU) * r * tall * rng.uniform(0.5, 1.0), w) for i in range(n)]


def plank_door(k, rng, f, a, z0, col, recess=0.2, w=0.9, h=2.0, planks=4, straps=P.iron):
    """A 0.9 x 2.0 m plank door in its hole, with strap hinges and a latch; returns the hole."""
    for i in range(planks):
        a0 = a - w / 2 + i * w / planks
        put(k, f.box(a0 + 0.006, a0 + w / planks - 0.006, z0, z0 + h, -recess - 0.05, -recess + 0.03 + rng.uniform(0, 0.012), back=False), jit(col, rng))
    for zz in (0.32, 1.62):
        put(k, f.box(a - w / 2 + 0.03, a + w / 2 - 0.2, z0 + zz, z0 + zz + 0.06, -recess + 0.03, -recess + 0.06, back=False), straps)
    put(k, f.box(a + w / 2 - 0.16, a + w / 2 - 0.08, z0 + 0.98, z0 + 1.1, -recess + 0.03, -recess + 0.1, back=False), straps)
    put(k, f.box(a - w / 2 - 0.3, a + w / 2 + 0.3, z0 + h, z0 + h + 0.32, 0.0, 0.05, back=False), jit(P.pale, rng))
    return (a - w / 2, a + w / 2, z0, z0 + h)


def barrel(k, rng, at, r, h, wood=P.drift, M=None, salt=0.0, head=True, sides=12, hoops=(0.1, 0.3, 0.7, 0.9)):
    """A coopered barrel standing at `at` (or placed by M): staves, rusting hoops, a recessed head
    and a salt crust that thickens towards the top."""
    M = M if M is not None else Matrix.Translation(at)
    inv = M.inverted()
    stave = [jit(wood, rng, 0.04) for _ in range(sides)]

    def col(co, n):
        q = inv @ co
        c = stave[int((math.atan2(q.y, q.x) % TAU) / TAU * sides) % sides]
        crust = salt * max(0.0, (q.z / h - 0.72) * 2.2 + 0.55 * nz(q.x * 7, q.y * 7, q.z * 4))
        return mix(c, P.lime, min(0.6, crust))
    prof = [(r * 0.84, 0.0), (r * 0.96, h * 0.22), (r, h * 0.5), (r * 0.96, h * 0.78), (r * 0.84, h)]
    if head:
        prof += [(r * 0.78, h), (r * 0.78, h - 0.04)]
    put(k, lathe(prof, sides, M, caps=(True, head)), col, soft=M @ Vector((0, 0, h / 2)))
    for t in hoops:
        rr = r * (0.84 + 0.16 * math.sin(PI * t) ** 0.8) + 0.012
        put(k, lathe([(rr, h * t - 0.025), (rr, h * t + 0.025)], sides, M, caps=(False, False)), mix(P.iron, P.rust, 0.35 + 0.6 * salt * rng.random()), closed=False)
    return M


def glass_float(k, rng, c, col, r=0.125, cord=None):
    """A blown-glass net float in its net bag, hung by a cord from `cord`."""
    c = Vector(c)
    prof = [(r * sin(PI * i / 6), -r * cos(PI * i / 6)) for i in range(1, 6)]
    put(k, lathe(prof, 8, Matrix.Translation(c)), jit(col, rng, 0.03), soft=c)
    net = on(P.tar, "cloth")
    polys = []
    for m in range(4):
        a = m / 4 * TAU + 0.4
        line = [c + Vector((cos(a) * sin(PI * i / 5), sin(a) * sin(PI * i / 5), -cos(PI * i / 5))) * (r + 0.008) for i in range(6)]
        polys += [(oriented(q, Vector((cos(a), sin(a), 0)) + (q[0] - c) * 6), net) for q in ribbon(line, 0.02, Vector((-sin(a), cos(a), 0)))]
    raw(k, polys)
    put(k, lathe([(r * 0.9 + 0.01, -0.012), (r * 0.9 + 0.01, 0.012)], 8, Matrix.Translation(c - Z * r * 0.42), caps=(False, False)), net, closed=False)
    if cord is not None:
        put(k, tube([c + Z * r, Vector(cord)], 0.012, 3, caps=False), on(P.sand, "cloth"), closed=False)


def kelp(k, rng, at, n, reach, dirn=None, spread=PI):
    """Wrack: n dark fronds lying out from `at`, towards `dirn` within `spread`."""
    at = Vector(at)
    base = math.atan2(dirn[1], dirn[0]) if dirn is not None else 0.0
    polys = []
    for _ in range(n):
        a = base + rng.uniform(-spread, spread)
        d, s = Vector((cos(a), sin(a), 0)), Vector((-sin(a), cos(a), 0))
        L, w = reach * rng.uniform(0.6, 1.0), rng.uniform(0.07, 0.12)
        line = [at + d * (L * i / 4) + s * (0.06 * sin(i * 1.9 + a * 5)) + Z * (0.012 + 0.05 * (1 - i / 4) + 0.004 * i) for i in range(5)]
        c = jit(P.kelp, rng)
        polys += [(oriented(q, Z), c) for q in ribbon(line, w, s)]
    raw(k, polys, two=True)


def kelp_heap(k, rng, at, rx, ry, h, fronds=10):
    """A heap of wrack, with fronds trailing off it."""
    at = Vector(at)
    bm = sphere((0, 0, 0), 1.0, 2)
    for v in bm.verts:
        b = 1 + 0.22 * nz(v.co.x * 2.1 + at.x, v.co.y * 2.1, v.co.z * 2.1)
        v.co = Vector((at.x + v.co.x * rx * b, at.y + v.co.y * ry * b, at.z + max(-0.02, v.co.z) * h * b))
    put(k, bm, lambda co, n: mix(P.kelp, P.tar, 0.25 + 0.25 * nz(co.x * 6, co.y * 6, co.z * 6)), soft=at)
    kelp(k, rng, at + Z * 0.0, fronds, max(rx, ry) * 1.25)


def creel(k, rng, M, r=0.27, h=0.6, fill=None, sides=10, rows=6):
    """A wicker creel placed by M: a tapered basket of two-tone weave with a rope rim and a
    shoulder strap; `fill` heaps it with kelp."""
    a_col, b_col = on(mix(P.grass, P.drift, 0.3), "thatch"), on(mix(P.grass, P.drift, 0.75), "thatch")

    def pt(i, j, inset=0.0):
        rr = r * (0.72 + 0.28 * (j / rows) ** 0.7) - inset
        a = i / sides * TAU
        return M @ Vector((cos(a) * rr, sin(a) * rr, h * j / rows))
    polys = []
    for j in range(rows):
        for i in range(sides):
            c = jit(a_col if (i + j) % 2 else b_col, rng, 0.025)
            polys.append(([pt(i, j), pt(i + 1, j), pt(i + 1, j + 1), pt(i, j + 1)], c))
    polys.append(([pt(i, 0) for i in range(sides)][::-1], b_col))
    dark = mix(b_col, P.tar, 0.55)
    top = rows - 1 if fill else 1
    for i in range(sides):  # the inside, down to what it holds
        polys.append(([pt(i, rows, 0.02), pt(i + 1, rows, 0.02), pt(i + 1, top, 0.02), pt(i, top, 0.02)], dark))
    polys.append(([pt(i, top, 0.02) for i in range(sides)], mix(P.kelp, P.tar, 0.3) if fill else dark))
    raw(k, polys)
    rim = [M @ Vector((cos(i / sides * TAU) * (r + 0.005), sin(i / sides * TAU) * (r + 0.005), h)) for i in range(sides + 1)]
    rope = on(mix(P.sand, P.drift, 0.55), "cloth")
    put(k, tube(rim, 0.02, 4, caps=False), rope, closed=False)
    strap = [M @ Vector((cos(t) * (r + 0.02), sin(t) * (r + 0.02), h * (0.95 - 0.45 * sin(PI * i / 6)))) for i, t in enumerate([PI * 1.5 + (i / 6 - 0.5) * 1.7 for i in range(7)])]
    put(k, tube(strap, 0.014, 3, caps=False), rope, closed=False)
    if fill:
        c = M @ Vector((0, 0, h * (rows - 1) / rows))
        bm = sphere((0, 0, 0), 1.0, 2)
        for v in bm.verts:
            b = 1 + 0.18 * nz(v.co.x * 2.3, v.co.y * 2.3, v.co.z * 2.3)
            v.co = M @ Vector((v.co.x * r * 0.92, v.co.y * r * 0.92, h * (rows - 1) / rows + max(0.0, v.co.z) * fill * b))
        put(k, bm, lambda co, n: mix(P.kelp, P.tar, 0.2 + 0.2 * nz(co.x * 8, co.y * 8, co.z * 8)), soft=c)


def turves(k, rng, x0, x1, y0, y1, z0, courses, ch=0.13, step=None):
    """Stacked peat: courses of cut turves round a dark core, each course a little inside the one
    below; `step(i)` shortens course i at its +X end (where turves have been taken)."""
    for i in range(courses):
        ins = 0.012 * i
        xa, xb, ya, yb = x0 + ins, (x1 - ins) - (step(i) if step else 0.0), y0 + ins, y1 - ins
        za = z0 + i * ch
        put(k, box((xa + 0.05, ya + 0.05, za), (xb - 0.05, yb - 0.05, za + ch)), mix(P.peat, P.tar, 0.3))
        runs = [(Face(((xa + xb) / 2, ya, 0), X, xb - xa), xb - xa), (Face(((xa + xb) / 2, yb, 0), -X, xb - xa), xb - xa),
                (Face((xb, (ya + yb) / 2, 0), Y, yb - ya), yb - ya), (Face((xa, (ya + yb) / 2, 0), -Y, yb - ya), yb - ya)]
        for f, L in runs:
            a = -L / 2 + (0.0 if i % 2 else -0.3)
            while a < L / 2 - 1e-6:
                b = min(L / 2, a + rng.uniform(0.5, 0.7))
                a = max(a, -L / 2)
                # Most turves show their cut face; some lie grass side out.
                c = mix(jit(P.peat, rng, 0.04), P.grass, 0.22) if rng.random() < 0.07 else jit(P.peat, rng, 0.045)
                put(k, f.box(a + 0.012, b - 0.012, za + 0.008, za + ch - 0.008, -0.12, rng.uniform(0.0, 0.025), back=False), c)
                a = b


def tuft(k, rng, at, r, h, col, blades=5):
    """A tuft of leaves: weeds on a stoop, greens in a bed."""
    at = Vector(at)
    polys = []
    for i in range(blades):
        a = i / blades * TAU + rng.uniform(-0.3, 0.3)
        d, s = Vector((cos(a), sin(a), 0)), Vector((-sin(a), cos(a), 0))
        tip = at + d * r * rng.uniform(0.7, 1.1) + Z * h * rng.uniform(0.6, 1.0)
        polys.append(([at - s * r * 0.35, at + s * r * 0.35, tip], jit(col, rng, 0.04)))
    raw(k, polys, two=True)


# ---------------------------------------------------------------------------------------------
# 1. The Cone


def gen_cone(k, rng):
    """The glass furnace: a sooted brick cone, 14 m across and 24 m to the rim, on a basalt
    plinth, with three arched mouths (the front one lit by the furnace), five iron bands, a
    lean-to pot room on the left, and a timber stair climbing the right flank to the gallery
    and charging door at 7 m. Wear: soot (rim, mouths), salt (rust, bloom), wind (lichen on the
    south-west), repair (the newer brick between 9 and 12 m, tied with iron plates)."""
    wear = dict(salt=0.5, soot=1.0, wind=0.6)
    R0, RT, H, SEG = 7.0, 1.95, 24.0, 48
    MOUTHS, HW = (0.0, rad(120), rad(-120)), 1.2
    SW, NE = rad(-45), rad(135)
    BANDS = (4.3, 8.3, 12.3, 16.3, 20.3)

    def radius(z):
        return RT + (R0 - RT) * (1 - min(1.0, max(0.0, z / H))) ** 1.12

    def cp(az, z, out=0.0):
        """A point of the cone: azimuth az from the front towards +X, height z, `out` proud."""
        r = radius(z) + out
        return Vector((r * sin(az), -r * cos(az), z))

    def wrap(a):
        return (a + PI) % TAU - PI

    def brick(co, n):
        az, z = math.atan2(co.x, -co.y), co.z
        c = tagged(tuple(x + 0.03 * nz(co.x * 0.4, co.y * 0.4, z * 0.55) for x in P.brick), "brick")
        if 1.2 < z < 9.5:  # lichen on the weather side, where the air is clean
            lich = max(0.0, nz(co.x * 1.6, co.y * 1.6, z * 1.6 + 7.0) - 0.3) * max(0.0, cos(az - SW)) ** 2 * wear["wind"] * min(1.0, (9.5 - z) / 4)
            c = mix(c, P.lichen, min(0.3, lich * 1.4))
        if z < 3.2:  # salt bloom near the quay
            c = mix(c, P.pale, wear["salt"] * max(0.0, nz(co.x * 0.7, co.y * 0.7, z + 3.0)) * 0.8)
        for zb in BANDS:  # rust runs down from the iron
            dz = zb - 0.15 - z
            if 0.0 <= dz < 1.5:
                c = mix(c, P.rust, max(0.0, nz(az * 11, zb)) * (1 - dz / 1.5) * (0.45 + 0.4 * wear["salt"] * (zb < 7)))
        for m in MOUTHS:  # a soot fan above each mouth
            d = abs(wrap(az - m)) * radius(z)
            hw = 1.0 + 0.3 * max(0.0, z - 3.0)
            if 2.0 < z < 10.0 and d < hw:
                c = mix(c, P.tar, (1 - (d / hw) ** 2) * max(0.0, 1 - (z - 3.0) / 7.0) * (0.9 if m == 0.0 else 0.6) * wear["soot"])
        lee = 0.5 + 0.5 * cos(az - NE)  # soot from the rim, 4 m down, a little longer downwind
        edge = H - 4.0 - 1.3 * lee + 0.45 * nz(az * 2.3, 0.0)
        return mix(c, P.tar, 0.92 * min(1.0, max(0.0, (z - edge) / 3.0)) ** 0.7 * wear["soot"])

    # The shell above the first band: rings of 48.
    zs = [4.3 + (23.3 - 4.3) * i / 27 for i in range(28)]
    bm = bmesh.new()
    rings = [[bm.verts.new(cp(i / SEG * TAU, z)) for i in range(SEG)] for z in zs]
    for lo, hi in zip(rings, rings[1:]):
        for i in range(SEG):
            bm.faces.new([lo[i], lo[(i + 1) % SEG], hi[(i + 1) % SEG], hi[i]])
    put(k, bm, brick, closed=False)

    # The shell below it hangs like a curtain over the three arched mouths: each column of the
    # mesh starts at the plinth, or at the arch where it crosses a mouth.
    cols = [(i / SEG * TAU - PI, None, None, 1.14) for i in range(SEG)]
    cols = [c for c in cols if all(abs(wrap(c[0] - m)) * R0 > HW + 0.3 for m in MOUTHS)]
    xs = [-HW + 2 * HW * i / 10 for i in range(11)]
    for m in MOUTHS:
        cols.append((m - HW / R0 - 1e-4, m, -HW, 1.14))
        cols += [(m + x / R0, m, x, 1.8 + math.sqrt(max(0.0, HW * HW - x * x))) for x in xs]
        cols.append((m + HW / R0 + 1e-4, m, HW, 1.14))
    cols.sort(key=lambda c: wrap(c[0]))

    def col_pt(c, s):
        z = c[3] + (4.3 - c[3]) * s
        return cp(c[0], z) if c[1] is None else cp(c[1] + math.asin(c[2] / radius(z)), z)
    bm = bmesh.new()
    grid = [[bm.verts.new(col_pt(c, s)) for s in (0.0, 0.2, 0.45, 0.7, 1.0)] for c in cols]
    for j, c in enumerate(cols):
        d = cols[(j + 1) % len(cols)]
        if c[1] is not None and c[1] == d[1] and c[2] == d[2]:
            continue  # the two columns of a jamb
        lo, hi = grid[j], grid[(j + 1) % len(cols)]
        for i in range(4):
            bm.faces.new([lo[i], hi[i], hi[i + 1], lo[i + 1]])
    put(k, bm, brick, closed=False)

    # The rim: two corbelled rings, the lip and the black throat. The opening is 3.2 m across.
    polys = []
    soot = mix(P.brick, P.tar, 0.9)
    for i in range(SEG):
        a0, a1 = i / SEG * TAU, (i + 1) / SEG * TAU
        for z0, z1, o0, o1 in ((23.3, 23.3, 0.0, 0.09), (23.3, 23.65, 0.09, 0.09), (23.65, 23.65, 0.09, 0.17), (23.65, 24.0, 0.17, 0.17)):
            polys.append(([cp(a0, z0, o0), cp(a1, z0, o0), cp(a1, z1, o1), cp(a0, z1, o1)], soot))

        def inner(a, z):
            return Vector((1.6 * sin(a), -1.6 * cos(a), z))
        polys.append(([cp(a0, 24.0, 0.17), cp(a1, 24.0, 0.17), inner(a1, 24.0), inner(a0, 24.0)], soot))
        polys.append(([inner(a0, 24.0), inner(a1, 24.0), inner(a1, 21.8), inner(a0, 21.8)], P.tar))
    polys.append(([Vector((1.6 * sin(i / 12 * TAU), -1.6 * cos(i / 12 * TAU), 21.8)) for i in range(12)], P.tar))
    raw(k, polys)

    # Five iron bands, each with its tightening lug; the lowest rust most.
    polys = []
    for bi, zb in enumerate(BANDS):
        for i in range(SEG):
            a0, a1 = i / SEG * TAU, (i + 1) / SEG * TAU
            c = mix(P.iron, P.rust, min(0.85, max(0.0, 0.3 + 0.6 * nz(a0 * 2.5, zb) + (0.3 * wear["salt"] if zb < 7 else 0.0))))
            polys.append(([cp(a0, zb - 0.15, 0.08), cp(a1, zb - 0.15, 0.08), cp(a1, zb + 0.15, 0.08), cp(a0, zb + 0.15, 0.08)], c))
            polys.append(([cp(a0, zb + 0.15, 0.08), cp(a1, zb + 0.15, 0.08), cp(a1, zb + 0.15, 0.0), cp(a0, zb + 0.15, 0.0)], c))
            polys.append(([cp(a0, zb - 0.15, 0.0), cp(a1, zb - 0.15, 0.0), cp(a1, zb - 0.15, 0.08), cp(a0, zb - 0.15, 0.08)], c))
        la = rad(-150 + 67 * bi)
        put(k, lbox(Vector((la - 0.03, zb - 0.2, 0.0)), Vector((la + 0.03, zb + 0.2, 0.2)), fn=lambda q: cp(q.x, q.y, q.z), open_bottom=True), P.iron)
    raw(k, polys)

    # The basalt plinth, 1.2 m, in two courses and a pale capping, between the mouths.
    delta = math.asin(HW / R0)
    for m in sorted(MOUTHS):
        s0, s1 = m + delta, m + rad(120) - delta
        for c in range(2):
            n = 12
            edges = [s0] + [s0 + (s1 - s0) * (i + (0.5 if c else 0.0)) / n for i in range(1, n if not c else n)] + [s1]
            for a0, a1 in zip(edges, edges[1:]):
                bloom = rng.random() < 0.22 * wear["salt"] * 2
                put(k, lbox(Vector((a0 + 0.003, 0.6 * c, 0.0)), Vector((a1 - 0.003, 0.6 * c + (0.585 if not c else 0.49), 0.14)), fn=lambda q: cp(q.x, q.y, q.z), open_bottom=True),
                    jit(P.pale if bloom else P.basalt, rng))
        for i in range(8):
            a0, a1 = s0 + (s1 - s0) * i / 8, s0 + (s1 - s0) * (i + 1) / 8
            put(k, lbox(Vector((a0, 1.08, 0.0)), Vector((a1, 1.2, 0.2)), fn=lambda q: cp(q.x, q.y, q.z), open_bottom=True), jit(P.pale, rng, 0.02))

    # The mouths: an arch of pale voussoirs with a basalt keystone, a reveal through the wall
    # and what stands inside.
    DB = 5.35  # the back of each mouth, from the axis
    for m in MOUTHS:
        nrm, tan = Vector((sin(m), -cos(m), 0)), Vector((cos(m), sin(m), 0))
        front = m == 0.0

        def mp(x, z, out=0.0, m=m):
            return cp(m + math.asin(x / radius(z)), z, out)

        def bp(x, z, out=0.0, nrm=nrm, tan=tan):
            return tan * x + nrm * (DB + out) + Z * z
        arch = [(x, 1.8 + math.sqrt(max(0.0, HW * HW - x * x))) for x in xs]
        mid = bp(0, 1.5, 1.0)
        lining = mix(P.brick, P.newbrick, 0.55) if front else mix(P.brick, P.tar, 0.5)  # fire-lit, or sooted
        polys = [(oriented([mp(x0, z0), mp(x1, z1), bp(x1, z1), bp(x0, z0)], mid - bp((x0 + x1) / 2, z0)), jit(lining, rng, 0.02)) for (x0, z0), (x1, z1) in zip(arch, arch[1:])]
        for e in (-1, 1):
            polys.append((oriented([mp(e * HW, 0), mp(e * HW, 1.8), bp(e * HW, 1.8), bp(e * HW, 0)], -tan * e), lining))
        polys.append((oriented([mp(-HW, 0.02), mp(HW, 0.02), bp(HW, 0.02), bp(-HW, 0.02)], Z), jit(P.pale, rng)))  # a threshold worn pale
        polys.append((oriented([bp(-HW, 0), bp(HW, 0)] + [bp(x, z) for x, z in reversed(arch)], nrm), mix(P.brick, P.tar, 0.7)))
        raw(k, polys)
        for i in range(9):
            t0, t1, key = PI * i / 9, PI * (i + 1) / 9, i == 4
            c = jit(P.basalt if key else P.pale, rng, 0.025)
            c = mix(c, P.tar, (0.45 if front else 0.25) * wear["soot"] * sin(PI * (i + 0.5) / 9) ** 2)
            put(k, lbox(Vector((t0 + 0.01, HW, 0.0)), Vector((t1 - 0.01, HW + (0.5 if key else 0.4), 0.16 if key else 0.11)),
                        fn=lambda q, mp=mp: mp(q.y * cos(q.x), 1.8 + q.y * sin(q.x), q.z), open_bottom=True), c)
        for e in (-1, 1):
            put(k, lbox(Vector((min(e * HW, e * (HW + 0.4)), 1.2, 0.0)), Vector((max(e * HW, e * (HW + 0.4)), 1.8, 0.11)), fn=lambda q, mp=mp: mp(q.x, q.y, q.z), open_bottom=True), jit(P.pale, rng, 0.025))
        if front:
            # The furnace's eye: a lit arch behind two pots on the siege.
            eye = [(x, 1.3 + math.sqrt(max(0.0, 0.7225 - x * x))) for x in [-0.85 + 0.17 * i for i in range(11)]]
            raw(k, [(oriented([bp(-0.85, 0.55, 0.03), bp(0.85, 0.55, 0.03)] + [bp(x, z, 0.03) for x, z in reversed(eye)], nrm), P.amber)], glow="GlowAmber")
            for i in range(7):
                t0, t1 = PI * i / 7, PI * (i + 1) / 7
                put(k, lbox(Vector((t0, 0.85, 0.0)), Vector((t1, 1.09, 0.16)), fn=lambda q, bp=bp: bp(q.y * cos(q.x), 1.3 + q.y * sin(q.x), q.z), open_bottom=True), jit(mix(P.brick, P.newbrick, 0.7), rng, 0.02))
            for e in (-1, 1):
                put(k, lbox(Vector((min(e * 0.85, e * 1.09), 0.0, 0.0)), Vector((max(e * 0.85, e * 1.09), 1.3, 0.16)), fn=lambda q, bp=bp: bp(q.x, q.y, q.z), open_bottom=True), jit(mix(P.brick, P.newbrick, 0.7), rng, 0.02))
            put(k, lbox(Vector((-0.85, 0.0, 0.0)), Vector((0.85, 0.55, 0.42)), fn=lambda q, bp=bp: bp(q.x, q.y, q.z), open_bottom=True), mix(P.brick, P.tar, 0.35))
            for x in (-0.42, 0.36):
                M = Matrix.Translation(bp(x, 0.55, 0.22))
                put(k, lathe([(0.15, 0.0), (0.21, 0.28), (0.19, 0.46), (0.16, 0.48)], 8, M), mix(P.sand, P.tar, 0.8), soft=M @ Vector((0, 0, 0.25)))
        else:
            # Tarred doors with rusting straps; the left-hand mouth stands half open.
            half = m < 0
            planks = [(oriented([bp(x0, 0, 0.06), bp(x1, 0, 0.06), bp(x1, z1, 0.06), bp(x0, z0, 0.06)], nrm), jit(P.tar, rng, 0.03))
                      for (x0, z0), (x1, z1) in list(zip(arch, arch[1:]))[5 if half else 0:]]
            raw(k, planks)
            for zz in (0.5, 1.5):
                put(k, lbox(Vector((0.0 if half else -HW + 0.08, zz, 0.06)), Vector((HW - 0.08, zz + 0.1, 0.1)), fn=lambda q, bp=bp: bp(q.x, q.y, q.z), open_bottom=True), mix(P.iron, P.rust, 0.6))

    # The newer brick, 9 to 12 m on the south-west: toothed into the old work, proud of it by a
    # finger, tied through with four iron plates that have begun to run.
    polys = []
    step = rad(3.75)
    for j in range(6):
        z0 = 9.0 + 0.5 * j
        a = SW - rad(40) - (step / 2 if j % 2 else 0.0)
        while a < SW + rad(40):
            c = jit(mix(P.newbrick, P.brick, 0.75) if rng.random() < 0.07 else P.newbrick, rng, 0.03)
            polys.append(([cp(a, z0, 0.035), cp(a + step, z0, 0.035), cp(a + step, z0 + 0.5, 0.035), cp(a, z0 + 0.5, 0.035)], c))
            a += step
    for i in range(4):
        az = SW + rad(-30 + 20 * i)
        put(k, B.cyl(cp(az, 10.5, 0.03), cp(az, 10.5, 0.1), 0.26, 0.26, 8), P.iron)
        polys.append(([cp(az - 0.012, 9.1, 0.045), cp(az + 0.012, 9.1, 0.045), cp(az + 0.02, 10.3, 0.045), cp(az - 0.02, 10.3, 0.045)], mix(P.newbrick, P.rust, 0.7)))
    # The crack that the repair answers still shows above it, stitched with two iron cramps.
    crack = [(SW + rad(8), 12.0), (SW + rad(9.5), 12.5), (SW + rad(8.5), 13.0), (SW + rad(10.5), 13.6), (SW + rad(10), 14.1)]
    for (a0, z0), (a1, z1) in zip(crack, crack[1:]):
        polys.append(([cp(a0 - 0.008, z0, 0.02), cp(a0 + 0.008, z0, 0.02), cp(a1 + 0.008, z1, 0.02), cp(a1 - 0.008, z1, 0.02)], P.tar))
    for a0, z0 in crack[1:4:2]:
        put(k, lbox(Vector((a0 - 0.07, z0 - 0.04, 0.0)), Vector((a0 + 0.07, z0 + 0.04, 0.06)), fn=lambda q: cp(q.x, q.y, q.z), open_bottom=True), P.rust)
    raw(k, polys)

    # The stair: tarred ship's timber climbing the right flank, 35 treads to 7 m, on raking
    # struts that lean on the cone; then the gallery, the charging door and the hoist.
    def rp(az, r, z):
        return Vector((r * sin(az), -r * cos(az), z))
    A0, A1, NT, GZ = rad(20), rad(84), 35, 7.0
    da = (A1 - A0) / NT
    for i in range(NT):
        z, az = GZ * (i + 1) / NT, A0 + da * i
        r = radius(z)
        put(k, lbox(Vector((az, r + 0.04, z - 0.06)), Vector((az + da * 1.12, r + 1.0, z)), fn=lambda q: rp(q.x, q.y, q.z)), jit(P.drift, rng, 0.04))  # treads worn bare
    stations = list(range(0, NT + 1, 5))
    outer = [rp(A0 + da * i, radius(GZ * i / NT) + 0.98, GZ * i / NT) for i in stations]
    tarred = jit(P.tar, rng, 0.02)
    for i, (a, b) in zip(stations, zip(outer, outer[1:])):
        put(k, beam(a - Z * 0.18, b - Z * 0.18, 0.07, 0.28), tarred)
        put(k, beam(a + Z * 1.05, b + Z * 1.05, 0.07, 0.09), tarred)
    for i, q in zip(stations, outer):
        put(k, beam(q - Z * 0.3, q + Z * 1.08, 0.09, 0.09, up=X), tarred)
        z = GZ * i / NT
        foot = rp(A0 + da * i, radius(max(0.0, z - 1.9)) - 0.05, z - 1.9) if z > 2.0 else Vector((q.x, q.y, 0.0))
        put(k, beam(q - Z * 0.25, foot, 0.1, 0.1, up=X), tarred)
    G0, G1, GR = A1, rad(118), radius(GZ)
    nb = 9
    for i in range(nb):
        a0, a1 = G0 + (G1 - G0) * i / nb, G0 + (G1 - G0) * (i + 1) / nb
        put(k, lbox(Vector((a0 + 0.002, GR - 0.25, GZ - 0.07)), Vector((a1 - 0.002, GR + 1.3, GZ)), fn=lambda q: rp(q.x, q.y, q.z)), jit(P.drift, rng, 0.04))
    rail = [rp(G0 + (G1 - G0) * i / 3, GR + 1.26, GZ) for i in range(4)] + [rp(G1, GR - 0.1, GZ)]
    for a, b in zip(rail, rail[1:]):
        put(k, beam(a + Z * 1.05, b + Z * 1.05, 0.07, 0.09), tarred)
        put(k, beam(a + Z * 0.55, b + Z * 0.55, 0.05, 0.07), tarred)
        put(k, beam(a - Z * 0.14, b - Z * 0.14, 0.08, 0.16), tarred)
    for i, q in enumerate(rail[:4]):
        put(k, beam(q - Z * 0.2, q + Z * 1.08, 0.09, 0.09, up=X), tarred)
        az = G0 + (G1 - G0) * i / 3
        put(k, beam(q - Z * 0.2, rp(az, radius(GZ - 2.0) - 0.05, GZ - 2.0), 0.11, 0.11, up=X), tarred)
    da_door = 0.55 / GR
    DA = rad(101)
    door = [(x, 1.25 + math.sqrt(max(0.0, 0.3025 - x * x))) for x in [-0.55 + 0.11 * i for i in range(11)]]
    raw(k, [([cp(DA - da_door, GZ, 0.05), cp(DA + da_door, GZ, 0.05)] + [cp(DA + x / GR, GZ + z, 0.05) for x, z in reversed(door)], mix(P.iron, P.rust, 0.45))])
    for i in range(7):
        t0, t1 = PI * i / 7, PI * (i + 1) / 7
        put(k, lbox(Vector((t0, 0.55, 0.0)), Vector((t1, 0.8, 0.1)), fn=lambda q: cp(DA + q.y * cos(q.x) / GR, GZ + 1.25 + q.y * sin(q.x), q.z), open_bottom=True), jit(P.pale, rng, 0.025))
    for e in (-1, 1):
        put(k, lbox(Vector((min(e * 0.55, e * 0.8), 0.0, 0.0)), Vector((max(e * 0.55, e * 0.8), 1.25, 0.1)), fn=lambda q: cp(DA + q.x / GR, GZ + q.y, q.z), open_bottom=True), jit(P.pale, rng, 0.025))
    put(k, lbox(Vector((-0.5, 0.75, 0.05)), Vector((0.5, 0.85, 0.09)), fn=lambda q: cp(DA + q.x / GR, GZ + q.y, q.z), open_bottom=True), P.rust)
    HZ, HA = 9.6, rad(110)  # the hoist: a cathead over the gallery's end, its rope down to a batch bucket
    tip = rp(HA, radius(HZ) + 2.45, HZ)
    put(k, beam(rp(HA, radius(HZ) - 0.1, HZ), tip, 0.16, 0.2), tarred)
    put(k, beam(rp(HA, radius(HZ - 1.5) - 0.05, HZ - 1.5), rp(HA, radius(HZ) + 1.5, HZ - 0.1), 0.11, 0.11, up=X), tarred)
    hook = tip - Vector((sin(HA), -cos(HA), 0)) * 0.2
    put(k, tube([hook - Z * 0.1, Vector((hook.x, hook.y, 2.25))], 0.02, 4, caps=False), on(P.sand, "cloth"), closed=False)
    M = Matrix.Translation((hook.x, hook.y, 1.75))
    put(k, lathe([(0.2, 0.0), (0.27, 0.5)], 8, M, caps=(True, False)), mix(P.iron, P.rust, 0.5), closed=False)
    put(k, lathe([(0.25, 0.42), (0.19, 0.02)], 8, M, caps=(False, False)), P.tar, closed=False)
    put(k, lathe([(0.24, 0.4), (0.03, 0.47)], 8, M, caps=(True, True)), jit(P.sand, rng), closed=False)  # the batch: sand and ash

    # The pot room: a lean-to on the left, 5 x 4 m, basalt under slate, its front open to the
    # yard so the drying pots can be seen. Its roof falls to the west, the weather side.
    PX0, PXI, PY0, PY1 = -10.3, -4.9, -3.2, 1.8

    def ptop(x):
        return 2.35 + (x - PX0) * 0.3
    put(k, prism([(PX0, 0), (PX0 + 0.42, 0), (PX0 + 0.42, ptop(PX0 + 0.42) - 0.1), (PX0, ptop(PX0) - 0.1)], PY0, PY1, lambda a, s, z: Vector((s, a, z))), jit(P.basalt, rng))
    put(k, prism([(PX0, 0), (PXI, 0), (PXI, ptop(PXI) - 0.1), (PX0, ptop(PX0) - 0.1)], PY1 - 0.42, PY1, lambda a, s, z: Vector((s, a, z))), jit(P.basalt, rng))
    put(k, box((PX0, PY0, 0.0), (PXI, PY1, 0.06)), jit(P.pale, rng))
    fw = Face((PX0, (PY0 + PY1) / 2, 0), -Y, PY1 - PY0)
    for _ in range(7):  # lichen and bloom on the weather wall
        a, z, c = rng.uniform(-2.2, 2.2), rng.uniform(0.3, 2.0), rng.choice([P.lichen, P.pale, P.pale])
        raw(k, [(blotch(fw, a, z, rng.uniform(0.18, 0.4), rng), mix(P.basalt, c, 0.55))])
    window(k, rng, fw, 0.4, 1.0, (2, 3, 0.36, 0.34), glazing(rng, P.smoke, P.green, 1, [(i, j) for i in range(2) for j in range(3)]), recess=-0.02, sill=None)
    for x in (PX0 + 0.1, -8.3, -6.5):
        put(k, beam((x, PY0 + 0.1, 0.06), (x, PY0 + 0.1, ptop(x) - 0.22), 0.16, 0.16, up=X), tarred)
    put(k, beam((PX0, PY0 + 0.1, ptop(PX0) - 0.16), (PXI, PY0 + 0.1, ptop(PXI) - 0.16), 0.14, 0.2, up=Y), jit(P.drift, rng))
    q = math.atan(0.3)

    def proof(a, t, h):
        return Vector((PXI - t * cos(q) + h * sin(q) * -1, a, ptop(PXI) + 0.06 - t * sin(q) + h * cos(q)))

    def pstate(a, t):
        r = rng.random()
        return jit(P.newslate, rng) if r < 0.1 else mix(jit(P.slate, rng), P.lichen, 0.3) if r < 0.1 + 0.22 * wear["wind"] and t > 2.2 else jit(P.slate, rng)
    slates(k, rng, proof, PY0 - 0.15, PY1 + 0.15, (PXI - PX0 + 0.25) / cos(q), pstate)
    put(k, box((-7.95, PY1 - 1.0, 0.06), (-6.2, PY1 - 0.42, 0.8)), jit(P.drift, rng))  # the pot bench
    for x, y, z, s in ((-7.6, PY1 - 0.72, 0.8, 1.0), (-7.05, PY1 - 0.7, 0.8, 0.9), (-9.3, PY1 - 0.9, 0.06, 1.25), (-8.5, PY1 - 0.85, 0.06, 1.1),
                       (-9.4, -0.1, 0.06, 1.2), (-9.35, -1.0, 0.06, 1.0), (-8.6, -2.3, 0.06, 1.15), (-7.3, -2.6, 0.06, 1.0)):
        M = Matrix.Translation((x, y, z)) @ Matrix.Scale(s, 4)
        put(k, lathe([(0.2, 0.0), (0.3, 0.38), (0.28, 0.6), (0.23, 0.62), (0.21, 0.5)], 8, M), jit(mix(P.sand, P.oldlime, 0.4), rng), soft=M @ Vector((0, 0, 0.3)))
    found(k, 1.8)
    return dict(body_m=[2 * R0, 2 * R0], rim_m=H, opening_m=3.2, wear=wear)


# ---------------------------------------------------------------------------------------------
# 2. The Low Row terrace


def gen_row(k, rng):
    """Four houses sharing walls on a street that drops 0.5 m at each party wall: basalt below,
    limewash above, slate roofs that step with the floors, a brick stack on each party wall,
    raised stone skews. The model carries its own stepped pavement, so the drop reads on flat
    ground. Each house is one household: tidy, a fisher's, empty, crowded."""
    wear = dict(salt=0.6, soot=0.1, wind=0.7)
    YF, YB, YR, YP = -2.55, 3.45, 0.45, -3.75
    p = rad(47)
    rise, c_p, s_p = 3.0 * math.tan(p), cos(p), sin(p)
    cells = lambda nu, nv: [(i, j) for i in range(nu) for j in range(nv)]  # noqa: E731
    fine, wide, broad = (3, 4, 0.32, 0.33), (2, 3, 0.45, 0.45), (3, 3, 0.45, 0.45)
    HS = [
        NS(n=1, x0=-11.0, x1=-6.0, S=1.5, eave=6.0, lime=P.lime, flake=0.25, door=P.chalkblue, dx=3.6, gx=1.45, ux=(1.35, 3.6), grid=fine, ggrid=fine,
           glass=(P.aqua, P.amber), odd=dict(g=0, u0=1, u1=0), lit=("u0",), sag=0.03, patch=0.05),
        NS(n=2, x0=-6.0, x1=0.0, S=1.0, eave=5.9, lime=P.oldlime, flake=0.9, door=P.oxblood, dx=1.35, gx=4.0, ux=(1.5, 4.3), grid=wide, ggrid=broad,
           glass=(P.smoke, P.green), odd=dict(g=2, u0=1, u1=1), lit=("g",), sag=0.07, patch=0.12),
        NS(n=3, x0=0.0, x1=4.5, S=0.5, eave=5.6, lime=P.oldlime, flake=2.2, door=mix(P.seagreen, P.drift, 0.5), dx=3.3, gx=1.3, ux=(1.25, 3.3), grid=wide, ggrid=wide,
           glass=(P.smoke, None), odd=dict(g=0, u0=0, u1=0), lit=(), sag=0.16, patch=0.0),
        NS(n=4, x0=4.5, x1=9.1, S=0.0, eave=5.75, lime=P.oldlime, flake=0.5, door=P.mustard, dx=1.45, gx=3.3, ux=(1.2, 3.4), grid=fine, ggrid=fine,
           glass=(P.aqua, P.smoke), odd=dict(g=2, u0=1, u1=3), lit=("g", "u1", "attic"), sag=0.05, patch=0.3),
    ]
    for h in HS:
        h.F, h.E, h.w, h.cx = h.S + 0.36, h.S + h.eave, h.x1 - h.x0, (h.x0 + h.x1) / 2
        h.z1, h.zr = h.F + 2.7, h.E + rise
        h.west = max(0.0, 1 - (h.x0 + 11.0) / 12.0)  # how open to the south-west wind

    def top(h, y):
        return h.zr - abs(y - YR) * math.tan(p)

    def flakes(h, f, a0, a1, z0, z1, n, holes=(), core=True):
        """Limewash flaked off by the wind: old lime shows, then the stone."""
        polys = []
        for _ in range(n):
            a, z, r = rng.uniform(a0 + 0.35, a1 - 0.35), z0 + 0.3 + (z1 - z0 - 0.6) * rng.random() ** 1.8, rng.uniform(0.2, 0.55)
            if any(h0 - r < a < h1 + r and zb - r < z < zt + r for h0, h1, zb, zt in holes):
                continue
            tall = rng.uniform(0.45, 0.8)  # lime comes off in low, wide sheets
            polys.append((blotch(f, a, z, r, rng, n=10, tall=tall), jit(P.oldlime if h.lime is P.lime else mix(P.oldlime, P.basalt, 0.22), rng, 0.02)))
            if core and r > 0.38:
                polys.append((blotch(f, a + rng.uniform(-0.1, 0.1), z - 0.04, r * 0.45, rng, w=0.02, n=7, tall=tall), jit(mix(P.basalt, P.pale, 0.5), rng)))
        raw(k, polys)

    for h in HS:
        A = lambda x, h=h: x - h.w / 2  # noqa: E731  (metres from the house's left wall to the face's own axis)
        ff, fb = Face((h.cx, YF, 0), X, h.w), Face((h.cx, YB, 0), -X, h.w)
        stone = jit(P.basalt, rng, 0.02)
        lime = jit(h.lime, rng, 0.02)
        main, odd = h.glass
        empty, tidy, fisher, crowded = h.n == 3, h.n == 1, h.n == 2, h.n == 4

        # The front: door, stoop, a ground window, two above.
        nu, nv, cu, cv = h.ggrid
        ghole = (A(h.gx) - nu * cu / 2, A(h.gx) + nu * cu / 2, h.F + 0.95, h.F + 0.95 + nv * cv)
        dhole = (A(h.dx) - 0.45, A(h.dx) + 0.45, h.F, h.F + 2.0)
        wall(k, rng, ff, 0.0, h.z1, stone, [dhole, ghole])
        plank_door(k, rng, ff, A(h.dx), h.F, h.door)
        if empty:  # boards nailed over the ground window and across the door
            raw(k, [([ff.p(ghole[0], ghole[2], -0.18), ff.p(ghole[1], ghole[2], -0.18), ff.p(ghole[1], ghole[3], -0.18), ff.p(ghole[0], ghole[3], -0.18)], P.tar)])
            for i in range(4):
                zz = ghole[2] + 0.12 + i * 0.36
                put(k, ff.obox(A(h.gx), zz + 0.1, nu * cu + 0.3, 0.26, 0.0, 0.04, rng.uniform(-0.07, 0.07)), jit(P.drift, rng, 0.045))
            put(k, ff.obox(A(h.dx), h.F + 1.1, 1.25, 0.16, -0.16, -0.12, 0.5), jit(P.drift, rng))
        else:
            window(k, rng, ff, A(h.gx), h.F + 0.95, h.ggrid, glazing(rng, main, odd, h.odd["g"], cells(nu, nv)), lit="g" in h.lit)
        nu, nv, cu, cv = h.grid
        uholes = [(A(x) - nu * cu / 2, A(x) + nu * cu / 2, h.z1 + 0.85, h.z1 + 0.85 + nv * cv) for x in h.ux]
        wall(k, rng, ff, h.z1, h.E, lime, uholes)
        for wi, x in enumerate(h.ux):
            if empty:  # broken panes, one boarded
                pick = glazing(rng, main, None, 0, cells(nu, nv), boards={(wi, 1)}, gone={(1 - wi, 2), (0, 0)})
                window(k, rng, ff, A(x), h.z1 + 0.85, h.grid, pick, bars=P.drift)
            else:
                # The row's one cobalt pane is in the fisher's upper window.
                o, n_odd = (P.cobalt, 1) if fisher and wi == 1 else (P.amber, 1) if crowded and wi == 0 else (odd, h.odd[f"u{wi}"])
                window(k, rng, ff, A(x), h.z1 + 0.85, h.grid, glazing(rng, main, o, n_odd, cells(nu, nv)), lit=f"u{wi}" in h.lit)
        put(k, ff.box(-h.w / 2, h.w / 2, h.z1 - 0.09, h.z1 + 0.05, 0.0, 0.05, back=False), jit(P.pale, rng, 0.02))
        flakes(h, ff, -h.w / 2, h.w / 2, h.z1, h.E, round(h.flake * wear["wind"] * 7), uholes)
        if crowded:  # patched in fresh lime that does not match
            raw(k, [(blotch(ff, A(0.42), h.z1 + 1.2, 0.36, rng, n=11, tall=1.5), jit(P.lime, rng, 0.02)), (blotch(ff, A(4.2), h.z1 + 0.5, 0.34, rng, n=11, tall=1.0), jit(P.lime, rng, 0.02))])
        bloom = [(blotch(ff, rng.uniform(-h.w / 2 + 0.4, h.w / 2 - 0.4), h.S + rng.uniform(0.15, 0.7), rng.uniform(0.2, 0.4), rng, tall=0.6), mix(P.basalt, P.pale, 0.7))
                 for _ in range(round(wear["salt"] * 5))]
        raw(k, [b for b in bloom if not (dhole[0] - 0.5 < (b[0][0] - ff.o).dot(X) < dhole[1] + 0.5)])  # salt bloom low on the stone
        # The stoop: two steps of 0.18 m, the upper tread worn pale (whitened, at the tidy house).
        tread = P.lime if tidy else P.pale
        put(k, ff.box(A(h.dx) - 0.8, A(h.dx) + 0.8, h.S, h.S + 0.18, 0.0, 0.62), lambda co, n, c=jit(P.basalt, rng): mix(c, P.pale, 0.6) if n.z > 0.5 else c)
        put(k, ff.box(A(h.dx) - 0.62, A(h.dx) + 0.62, h.S + 0.18, h.S + 0.36, 0.0, 0.32), lambda co, n, c=jit(P.basalt, rng), t=jit(tread, rng, 0.02): t if n.z > 0.5 else c)

        # The back: plain, two windows; only the crowded house shows a light.
        bx = (h.w * 0.3, h.w * 0.72)
        bg = (A(bx[0]) - 0.45, A(bx[0]) + 0.45, h.F + 1.0, h.F + 2.35)
        bu = (A(bx[1]) - 0.45, A(bx[1]) + 0.45, h.z1 + 0.85, h.z1 + 2.2)
        wall(k, rng, fb, 0.0, h.z1, stone, [bg])
        wall(k, rng, fb, h.z1, h.E, lime, [bu])
        for hole, lit_ in ((bg, False), (bu, crowded)):
            gone = {(0, 1), (1, 0)} if empty else set()
            window(k, rng, fb, (hole[0] + hole[1]) / 2, hole[2], wide, glazing(rng, main, odd, 0 if empty else 1, cells(2, 3), gone=gone), lit=lit_, bars=P.drift if empty else None)
        put(k, fb.box(-h.w / 2, h.w / 2, h.z1 - 0.09, h.z1 + 0.05, 0.0, 0.05, back=False), jit(P.pale, rng, 0.02))

        # The roof: slates in the house's own state of repair, a sagging stone ridge, a gutter.
        a0, a1 = h.x0 + (0.3 if h.n == 1 else 0.18), h.x1 - (0.3 if h.n == 4 else 0.18)
        S = 3.26 / c_p

        def sag(a, h=h, a0=a0, a1=a1):
            return h.sag * (1 - ((2 * a - a0 - a1) / (a1 - a0)) ** 2)
        gone_at = [(h.x0 + 1.2, 3.9), (h.x0 + 1.75, 3.9), (h.x0 + 1.5, 3.45), (h.x0 + 3.2, 1.6), (h.x0 + 3.5, 2.6), (h.x0 + 0.9, 1.2)] if empty else []
        for sgn in (-1, 1):
            D, N = Vector((0, sgn * c_p, -s_p)), Vector((0, sgn * s_p, c_p))

            def fn(a, t, hh, D=D, N=N):
                return Vector((a, YR, h.zr - sag(a))) + D * t + N * hh

            def state(a, t, sgn=sgn, h=h):
                if sgn < 0 and any(abs(a - ga) < 0.45 and abs(t - gt) < 0.24 for ga, gt in gone_at):
                    return None  # slates the storm took, never put back
                c = jit(P.slate, rng, 0.04)
                lee = max(0.0, 1 - math.hypot(a - (h.x0 + 0.5), (t - 0.8) * 0.8) / 1.6) if sgn > 0 else 0.0
                if lee > 0:  # soot settles downwind of the stack
                    c = mix(c, P.tar, 0.55 * lee)
                exposed = wear["wind"] * (0.55 + 0.45 * h.west) * (1.0 if sgn < 0 else 0.35)
                if nz(a * 0.7, t * 0.9, 3.0 + sgn) + rng.uniform(-0.25, 0.25) > 0.62 - 0.38 * exposed and t > 1.2:
                    c = mix(c, P.lichen, rng.uniform(0.2, 0.42))  # lichen on the weather slope, low down
                if rng.random() < h.patch * exposed + 0.02:
                    c = jit(P.newslate, rng, 0.04)  # a repair in whatever slate there was
                return c
            slates(k, rng, fn, a0, a1, S, state)
            if sgn < 0:  # iron gutter and downpipe; rust runs under them (salt)
                ze = h.zr - S * s_p
                ga1 = a1 - 2.3 if empty else a1
                put(k, box((a0, YF - 0.36, ze - 0.13), (ga1, YF - 0.25, ze - 0.02)), mix(P.iron, P.rust, 0.3 + 0.4 * wear["salt"] * rng.random()))
                px = h.x1 - 0.42
                if empty:  # the gutter's end has dropped, and the pipe is gone: its stain is left
                    put(k, beam((ga1, YF - 0.3, ze - 0.08), (ga1 + 1.1, YF - 0.3, ze - 0.75), 0.11, 0.11), mix(P.iron, P.rust, 0.8))
                    raw(k, [(blotch(ff, A(px - h.x0), h.z1 + rng.uniform(0.4, 2.2), 0.06, rng, n=8, tall=5.0), mix(P.oldlime, P.rust, 0.4)) for _ in range(3)])
                else:
                    put(k, beam((px, YF - 0.3, ze - 0.1), (px, YF - 0.07, ze - 0.55), 0.08, 0.08), P.iron)
                    put(k, box((px - 0.045, YF - 0.11, h.S + 0.25), (px + 0.045, YF - 0.02, ze - 0.5)), mix(P.iron, P.rust, 0.25 + 0.5 * wear["salt"] * rng.random()))
                    raw(k, [(blotch(ff, A(px - h.x0) + 0.09, h.S + 0.9 + i * 2.1, 0.05, rng, n=8, tall=7.0), mix(lime if i else stone, P.rust, 0.35)) for i in range(2)])
        a = a0
        while a < a1 - 0.2:  # ridge stones; one is gone from the empty house
            b = min(a1, a + rng.uniform(0.6, 0.85))
            if not (empty and abs(a - (h.x0 + 2.6)) < 0.4):
                put(k, box((a + 0.015, YR - 0.2, h.zr - sag((a + b) / 2) - 0.03), (b - 0.015, YR + 0.2, h.zr - sag((a + b) / 2) + 0.13), bevel=0.04), jit(P.basalt, rng, 0.03))
            a = b
        # Attic lights: cast-iron rooflights, more of them where more people sleep.
        for li, lx in enumerate({1: (2.4,), 2: (3.2,), 3: (), 4: (1.5, 3.3)}[h.n]):
            D, N = Vector((0, -c_p, -s_p)), Vector((0, -s_p, c_p))
            o = Vector((h.x0 + lx - 0.36, YR, h.zr - sag(h.x0 + lx))) + D * 2.45
            pt = lambda u, v, w, o=o, D=D, N=N: o + X * u - D * v + N * (0.09 + w)  # noqa: E731
            put(k, lbox(Vector((-0.06, -0.06, 0.0)), Vector((0.78, 0.78, 0.085)), fn=lambda q, o=o, D=D, N=N: o + X * q.x - D * q.y + N * q.z), P.iron)
            pane_grid(k, rng, pt, 2, 2, 0.36, 0.36, glazing(rng, P.smoke, P.aqua, 1, cells(2, 2)), back=P.iron, glow="Glow" if crowded and li == 0 else None)

        # A strip of pavement at the house's own street level, with a kerb, and steps down to
        # the next house's.
        pw = h.x1 - h.x0 if h.n < 4 else 11.0 - h.x0
        put(k, box((h.x0, YP + 0.04, 0.0), (h.x0 + pw, YF, h.S + 0.04)), lambda co, n, c=jit(P.basalt, rng, 0.02), t=jit(P.pale, rng, 0.02): t if n.z > 0.5 else c)
        blocks(k, rng, Face((h.x0 + pw / 2, YP, 0), X, pw), -pw / 2, pw / 2, max(0.0, h.S - 0.16), h.S + 0.06, 0.24, P.pale, P.basalt, 0.3, course=0.3, cut=(0.6, 1.0))
        if h.S > 0.3:  # the pavement's wall, where the street has dropped away from it
            blocks(k, rng, Face((h.x0 + pw / 2, YP + 0.035, 0), X, pw), -pw / 2, pw / 2, 0.0, h.S - 0.17, 0.2, P.basalt, P.pale, 0.3 * wear["salt"], cut=(0.6, 1.1), back=False)
        if h.n < 4:
            for j in (1, 2):
                put(k, box((h.x1 + 0.3 * (j - 1), YP, h.S - 0.5), (h.x1 + 0.3 * j, YF, h.S - 0.5 + 0.5 * (3 - j) / 3), bevel=0.015),
                    lambda co, n, c=jit(P.basalt, rng), t=jit(P.pale, rng): t if n.z > 0.5 else c)

    # Party walls rise through the roofs as raised skews; a brick stack stands on each.
    def skew(h, x, w):
        for sgn in (-1, 1):
            a = Vector((x, YR, h.zr + 0.2))
            b = Vector((x, YR + sgn * 3.24, h.zr + 0.2 - 3.24 * math.tan(p)))
            put(k, beam(a, b, w, 0.13), lambda co, n, c=jit(P.pale, rng, 0.02): mix(c, P.lichen, 0.5 * wear["wind"] * max(0.0, nz(co.y * 1.4, co.z * 1.4, x)) * (2.0 if co.y < YR else 0.6)))
            put(k, box((x - w / 2, b.y - 0.2 if sgn > 0 else b.y - 0.16, b.z - 0.42), (x + w / 2, b.y + 0.05 if sgn > 0 else b.y + 0.1, b.z + 0.02)), jit(P.pale, rng, 0.02))

    for hl, hr in zip(HS, HS[1:]):
        b = hl.x1
        pts = [(YF + 0.02, 0.0), (YB - 0.02, 0.0), (YB - 0.02, top(hl, YB) + 0.14), (YR, hl.zr + 0.14), (YF + 0.02, top(hl, YF) + 0.14)]
        put(k, prism(pts, b - 0.18, b + 0.18, lambda a, s, z: Vector((a, s, z))), jit(P.lime, rng, 0.02))
        skew(hl, b, 0.4)
        # The stack: sooted brick, rebuilt at the top in newer brick on the first; pots for the
        # hearths that burn. The empty house's flues are capped with a slate.
        zc = hl.zr + 1.35
        newer = hl.n == 1
        put(k, box((b - 0.47, YR - 0.3, hl.zr - 0.6), (b + 0.47, YR + 0.3, zc - (0.5 if newer else 0.0))),
            lambda co, n, c=jit(P.brick, rng, 0.02), zc=zc: mix(c, P.tar, 0.5 * max(0.0, (co.z - zc + 0.9) / 0.9)))
        if newer:
            put(k, box((b - 0.47, YR - 0.3, zc - 0.5), (b + 0.47, YR + 0.3, zc)), jit(P.newbrick, rng, 0.02))
        put(k, box((b - 0.53, YR - 0.36, zc), (b + 0.53, YR + 0.36, zc + 0.09)), jit(P.pale, rng, 0.02))
        pots = [(-0.26, 0.45, P.newbrick)] * (hl.n != 3) + [(0.26, 0.45, P.newbrick)] * (hr.n != 3)
        if hr.n == 4:  # the crowded house has added a pot: taller, a different clay, with an iron cowl
            pots = [(0.12, 0.45, P.newbrick), (0.36, 0.72, mix(P.sand, P.oldlime, 0.5))]
        for dx, ph, pc in pots:
            M = Matrix.Translation((b + dx, YR, zc + 0.09))
            put(k, lathe([(0.13, 0.0), (0.15, 0.08), (0.11, ph - 0.04), (0.13, ph), (0.09, ph), (0.09, ph - 0.1)], 6, M), lambda co, n, c=jit(pc, rng, 0.03), z=zc + ph: mix(c, P.tar, 0.8 * max(0.0, (co.z - z + 0.1) / 0.2)))
            if ph > 0.6:
                put(k, lathe([(0.16, ph + 0.06), (0.03, ph + 0.2)], 6, M), P.iron)
                put(k, lathe([(0.02, ph - 0.02), (0.02, ph + 0.08)], 4, M), P.iron)
        for side, hh in ((-1, hl), (1, hr)):
            if hh.n == 3:
                put(k, box((b + side * 0.26 - 0.2, YR - 0.2, zc + 0.09), (b + side * 0.26 + 0.2, YR + 0.2, zc + 0.12)), jit(P.newslate, rng))

    # The end gables. The west one takes the weather: flaked lime, lichen, bloom.
    for h, xg, u in ((HS[0], -11.0, -Y), (HS[3], 9.1, Y)):
        sx = -1 if xg < 0 else 1
        xa, xb = (xg, xg + 0.3) if sx < 0 else (xg - 0.3, xg)
        put(k, prism([(YF + 0.01, 0.0), (YB - 0.01, 0.0), (YB - 0.01, h.z1), (YF + 0.01, h.z1)], xa, xb, lambda a, s, z: Vector((a, s, z))), jit(P.basalt, rng, 0.02))
        lime = jit(h.lime, rng, 0.02)
        put(k, prism([(YF + 0.01, h.z1), (YB - 0.01, h.z1), (YB - 0.01, top(h, YB) + 0.14), (YR, h.zr + 0.14), (YF + 0.01, top(h, YF) + 0.14)], xa, xb, lambda a, s, z: Vector((a, s, z))), lime)
        skew(h, (xa + xb) / 2, 0.3)
        fg = Face((xg, YR, 0), u, YB - YF)
        put(k, fg.box(-3.0, 3.0, h.z1 - 0.09, h.z1 + 0.05, 0.0, 0.05, back=False), jit(P.pale, rng, 0.02))
        lit = "attic" in h.lit
        window(k, rng, fg, 0.0, h.E + 0.75, (2, 2, 0.36, 0.36), glazing(rng, h.glass[0], h.glass[1], 1, cells(2, 2)), lit=lit, recess=-0.02, sill=None)
        put(k, fg.box(-0.46, 0.46, h.E + 0.63, h.E + 0.75, 0.0, 0.1), jit(P.pale, rng))
        if sx < 0:
            flakes(h, fg, -3.0, 3.0, h.z1, h.E + 0.5, round(14 * wear["wind"]), [(-0.5, 0.5, h.E + 0.6, h.E + 1.6)])
            for ca, cz in ((-2.2, h.E - 0.6), (1.9, h.z1 + 0.5), (-1.4, h.S + 1.6), (2.3, h.S + 2.4)):  # lichen, in colonies
                raw(k, [(blotch(fg, ca + rng.uniform(-0.45, 0.45), cz + rng.uniform(-0.5, 0.5), rng.uniform(0.07, 0.2), rng, n=8, tall=rng.uniform(0.6, 1.5)), mix(P.basalt if cz < h.z1 else lime, P.lichen, 0.5))
                        for _ in range(4)])
            raw(k, [(blotch(fg, rng.uniform(-2.6, 2.6), h.S + rng.uniform(0.2, 1.0), rng.uniform(0.25, 0.45), rng, tall=0.6), mix(P.basalt, P.pale, 0.7)) for i in range(4)])

    # --- What each household keeps outside ---------------------------------------------------
    h1, h2, h3, h4 = HS
    # 1, tidy: a flower box under the window, a bench by the door.
    fx, fz = h1.x0 + h1.gx, h1.F + 0.95 - 0.16
    put(k, box((fx - 0.56, YF - 0.3, fz - 0.24), (fx + 0.56, YF - 0.04, fz)), jit(P.drift, rng))
    for i in range(6):
        c = Vector((fx - 0.45 + i * 0.18, YF - 0.17, fz))
        tuft(k, rng, c, 0.13, 0.26, LEAF, 4)
        put(k, sphere(c + Vector((rng.uniform(-0.04, 0.04), -0.03, rng.uniform(0.12, 0.22))), 0.06, 0), jit(P.heather, rng), soft=c)
    bx0 = h1.x0 + 0.85
    for dx in (0.12, 1.0):
        put(k, box((bx0 + dx - 0.1, YF - 0.42, h1.S + 0.04), (bx0 + dx + 0.1, YF - 0.06, h1.S + 0.44)), jit(P.basalt, rng))
    put(k, box((bx0 - 0.08, YF - 0.46, h1.S + 0.44), (bx0 + 1.2, YF - 0.04, h1.S + 0.5)), jit(P.drift, rng))
    # 2, the fisher's: a string of glass floats under the upper windows, a creel by the door,
    # oilskins on a peg.
    fz = h2.S + 2.75
    span = [Vector((h2.x0 + 2.3 + 1.0 * i / 5, YF - 0.16, fz - 0.0 * i)) for i in range(6)]
    line = [Vector((q.x, q.y, fz + 0.32 - 0.3 * sin(PI * i / 5))) for i, q in enumerate(span)]
    put(k, tube(line, 0.012, 3, caps=False), on(P.sand, "cloth"), closed=False)
    for i, q in enumerate(line[1:5]):
        glass_float(k, rng, q - Z * 0.21, (P.green, P.amber, P.aqua, P.green)[i], r=0.11, cord=q)
    for q in (line[0], line[-1]):
        put(k, beam(q + Y * 0.16, q - Y * 0.03, 0.03, 0.03), P.iron)
    creel(k, rng, Matrix.Translation((h2.x0 + 2.6, YF - 0.36, h2.S + 0.04)), 0.25, 0.55)
    ox, oz = h2.x0 + 0.42, h2.S + 1.95
    put(k, beam((ox, YF, oz), (ox, YF - 0.12, oz + 0.02), 0.03, 0.03), P.iron)
    oil = on(P.kelp, "cloth")
    put(k, moved(lbox(Vector((-0.24, -0.07, -1.05)), Vector((0.24, 0.07, 0.0)), warp=lambda q: Vector((q.x * (1.0 + 0.35 * (-q.z)), q.y * (1 + 0.5 * (-q.z)), q.z))), Matrix.Translation((ox, YF - 0.11, oz))), jit(oil, rng))
    for e in (-1, 1):
        put(k, beam((ox + e * 0.22, YF - 0.11, oz - 0.06), (ox + e * 0.38, YF - 0.1, oz - 0.7), 0.13, 0.11), jit(oil, rng))
    put(k, moved(sphere((0, 0, 0), 0.14, 1, squash=0.7), Matrix.Translation((ox, YF - 0.12, oz + 0.07))), jit(oil, rng), soft=Vector((ox, YF - 0.12, oz)))
    # 3, empty: weeds on the stoop and along the wall foot.
    for _ in range(11):
        x = h3.x0 + rng.choice([rng.uniform(0.2, 4.3), h3.dx + rng.uniform(-0.75, 0.75)])
        near_door = abs(x - h3.x0 - h3.dx) < 0.8
        y = YF - (rng.uniform(0.1, 0.6) if near_door else rng.uniform(0.02, 0.14))
        z = h3.S + (0.04 if not near_door else 0.18 if y < YF - 0.32 else 0.36)
        tuft(k, rng, (x, y, z), rng.uniform(0.1, 0.2), rng.uniform(0.2, 0.5), P.grass, 5)
    # 4, crowded: a tarred lean-to on the end wall with its own flue, a washing-line bracket
    # with the line tied off to a cleat, peat by the lean-to door.
    LX0, LX1, LY0, LY1 = 9.1, 10.9, -2.2, 1.6

    def ltop(x):
        return 3.1 - (x - LX0) * 0.5
    put(k, box((LX0, LY0, 0.0), (LX1, LY1, 0.3)), jit(P.basalt, rng))
    tarc = jit(P.tar, rng, 0.02)
    put(k, prism([(LX0, 0.3), (LX1, 0.3), (LX1, ltop(LX1)), (LX0, ltop(LX0))], LY0 + 0.02, LY1 - 0.02, lambda a, s, z: Vector((s, a, z))), tarc)
    lf, le = Face(((LX0 + LX1) / 2, LY0, 0), X, LX1 - LX0), Face((LX1, (LY0 + LY1) / 2, 0), Y, LY1 - LY0)
    for a in (-0.75, 0.75):
        put(k, lf.box(a - 0.04, a + 0.04, 0.3, ltop((LX0 + LX1) / 2 + a) - 0.05, 0.0, 0.05, back=False), jit(P.tar, rng))
    for i in range(3):
        put(k, lf.box(-0.72 + i * 0.25, -0.49 + i * 0.25, 0.32, 1.95, 0.0, 0.04, back=False), jit(P.drift, rng, 0.045))
    put(k, lf.box(-0.16, -0.06, 1.1, 1.2, 0.04, 0.09, back=False), P.iron)
    for i in range(10):
        a = -1.8 + i * 0.4
        put(k, le.box(a - 0.035, a + 0.035, 0.3, ltop(LX1) - 0.04, 0.0, 0.04, back=False), jit(P.tar, rng))
    window(k, rng, le, 0.4, 1.15, (2, 2, 0.32, 0.32), glazing(rng, P.smoke, P.green, 1, cells(2, 2)), recess=-0.045, sill=None, bars=P.drift)
    ql = math.atan(0.5)
    lstate = lambda a, t: jit(P.newslate if rng.random() < 0.3 else P.slate, rng)  # noqa: E731
    slates(k, rng, lambda a, t, hh: Vector((LX0 + 0.02 + t * cos(ql) + hh * sin(ql), a, ltop(LX0) + 0.08 - t * sin(ql) + hh * cos(ql))), LY0 - 0.08, LY1 + 0.08, (11.0 - 0.045 - LX0) / cos(ql), lstate, course=0.4)
    put(k, tube([(10.25, 0.7, 2.3), (10.25, 0.7, 3.95)], 0.08, 6), mix(P.iron, P.rust, 0.55))
    put(k, lathe([(0.17, 3.93), (0.04, 4.1)], 6, Matrix.Translation((10.25, 0.7, 0))), P.iron)
    fe = Face((9.1, YR, 0), Y, 6.0)
    raw(k, [(blotch(fe, 0.55, 5.0, 0.5, rng, n=11, tall=1.9), mix(P.oldlime, P.tar, 0.3)), (blotch(fe, 0.7, 5.4, 0.26, rng, w=0.02, n=9, tall=2.0), mix(P.oldlime, P.tar, 0.5))])  # the flue's soot, blown north-east
    f4 = Face((h4.cx, YF, 0), X, h4.w)
    wx, wz = h4.x0 + 2.3 - h4.cx, h4.z1 + 1.75
    put(k, beam(f4.p(wx, wz, 0.0), f4.p(wx, wz, 0.62), 0.05, 0.05), P.iron)
    put(k, beam(f4.p(wx, wz - 0.42, 0.0), f4.p(wx, wz - 0.02, 0.55), 0.04, 0.04), P.iron)
    put(k, B.cyl(f4.p(wx - 0.03, wz - 0.12, 0.58), f4.p(wx + 0.03, wz - 0.12, 0.58), 0.09, 0.09, 8), mix(P.iron, P.rust, 0.5))
    cleat = f4.p(wx + 0.25, h4.S + 1.55, 0.05)
    put(k, tube([f4.p(wx, wz - 0.2, 0.58), f4.p(wx + 0.08, wz - 1.5, 0.3), cleat], 0.012, 3, caps=False), on(P.sand, "cloth"), closed=False)
    put(k, beam(cleat - X * 0.09, cleat + X * 0.09, 0.03, 0.03), P.iron)
    raw(k, [(blotch(f4, wx, wz - 0.9, 0.05, rng, n=8, tall=7.0), mix(P.oldlime, P.rust, 0.4))])  # rust under the bracket
    turves(k, rng, 10.05, 10.85, LY0 - 0.44, LY0 - 0.02, 0.04, 5, step=lambda i: 0.25 * max(0, i - 2))
    fit(k, 22.0, 7.5)
    found(k, 1.8)
    return dict(wear=wear, houses=[dict(house=h.n, front_m=round(h.w + (1.9 if h.n == 4 else 0.0), 2), street_m=h.S, eave_above_street_m=h.eave, ridge_above_street_m=round(h.eave + rise, 2)) for h in HS],
                note="house 4's 6.5 m front is its 4.6 m house and the 1.9 m lean-to; heights are above each house's own street level")


# ---------------------------------------------------------------------------------------------
# 3. The Ladder glasshouse


def gen_glasshouse(k, rng):
    """A lean-to glasshouse against a whitewashed terrace wall: basalt dwarf walls, a timber
    frame in flaking pale paint, 1.0 m bays of small aqua panes, a roof falling from 3.2 to
    1.9 m. A fifth of the panes are not original (boards, odd glass, holes), more of them at the
    west end where the storm came in. Two vents stand open, and the door at the sheltered east
    end. Along the front: a kelp heap and fork, a cold frame, a rain butt under the downpipe."""
    wear = dict(salt=0.1, soot=0.0, wind=0.8, repair=0.6)
    XL, XR, YW, YFR, YS = -6.0, 6.0, 1.75, -1.6, -2.25  # the wall's face, the dwarf wall's face, the edge of the strip
    ZT, ZE, YE = 3.14, 1.84, -1.66
    run = YW - YE
    S = math.hypot(run, ZT - ZE)
    D, N = Vector((0, -run / S, -(ZT - ZE) / S)), Vector((0, -(ZT - ZE) / S, run / S))
    paint, paint2 = on(P.lime, "wood"), on(P.oldlime, "wood")

    def R(a, t, h=0.0):
        return Vector((a, YW, ZT)) + D * t + N * h

    def roof_z(y):
        return ZE + (y - YE) / run * (ZT - ZE)

    def timber(p0, p1, w, h, n=1, up=Z):
        """A painted frame member in n lengths; where the wind has stripped it, bare driftwood."""
        p0, p1 = Vector(p0), Vector(p1)
        for i in range(n):
            a, b = p0.lerp(p1, i / n), p0.lerp(p1, (i + 1) / n)
            bare = rng.random() < 0.12 + 0.5 * wear["wind"] * (XR - (a.x + b.x) / 2) / 12.0
            put(k, beam(a, b, w, h, up), jit(P.drift if bare else rng.choice([paint, paint, paint2]), rng, 0.025))

    # The back wall: whitewashed towards the house, bare basalt behind, a slate coping.
    put(k, box((XL, YW, 0.0), (XR, 2.25, 3.1)), lambda co, n, c=jit(on(P.lime, "stone"), rng, 0.015), s=jit(P.basalt, rng, 0.02): s if n.y > 0.5 else c)
    blocks(k, rng, Face((0, 2.25, 0), -X, 12.0), -6.0, 6.0, 3.1, 3.2, 0.5, P.slate, P.newslate, 0.25, course=0.1, cut=(0.6, 1.1))
    fwall = Face((0, YW, 0), X, 12.0)
    raw(k, [(blotch(fwall, rng.uniform(-5.8, 5.8), rng.uniform(0.2, 1.0), rng.uniform(0.2, 0.45), rng, tall=0.7), mix(on(P.lime, "stone"), P.kelp, 0.3)) for _ in range(8)])  # damp green at the foot
    fend = Face((XL, 2.0, 0), -Y, 0.5)
    raw(k, [(blotch(fend, 0.0, 0.6 + 0.8 * i, 0.2, rng), jit(P.oldlime if i % 2 else P.basalt, rng)) for i in range(3)])  # the weather end flakes

    # Dwarf walls of basalt, 0.7 m: the front and both ends, less the doorway.
    DY0, DY1 = 0.5, 1.4
    blocks(k, rng, Face((0, YFR, 0), X, 12.0), -6.0, 6.0, 0.0, 0.7, 0.3, P.basalt, P.pale, 0.12)
    blocks(k, rng, Face((XL, (YFR + YW) / 2, 0), -Y, YW - YFR), -(YW - YFR) / 2 + 0.0, (YW - YFR) / 2 - 0.3, 0.0, 0.7, 0.3, P.basalt, mix(P.basalt, P.lichen, 0.4), 0.3)
    fe = Face((XR, (YFR + YW) / 2, 0), Y, YW - YFR)
    ea = lambda y: y - (YFR + YW) / 2  # noqa: E731
    blocks(k, rng, fe, ea(YFR) + 0.3, ea(DY0), 0.0, 0.7, 0.3, P.basalt, P.pale, 0.12)
    blocks(k, rng, fe, ea(DY1), ea(YW), 0.0, 0.7, 0.3, P.basalt, P.pale, 0.12)

    # Every pane is listed first, so that the share that is not original can be counted.
    VENTS = {6: 0, 7: 0, 16: 1, 17: 1}  # roof columns under the two vents (their top two rows)
    NR, cvr = 9, S / 9
    panes = []  # dict(where, quad, west, state)

    def cell(pt, u0, u1, v0, v1, bar=0.06, v1b=None):
        return [pt(u0 + bar / 2, v0 + bar / 2), pt(u1 - bar / 2, v0 + bar / 2), pt(u1 - bar / 2, (v1b if v1b is not None else v1) - bar / 2), pt(u0 + bar / 2, v1 - bar / 2)]
    for i in range(24):
        for j in range(NR):
            if i in VENTS and j < 2:
                continue
            q = cell(lambda u, v: R(XL + u, v), i * 0.5, (i + 1) * 0.5, j * cvr, (j + 1) * cvr)
            panes.append(NS(where="roof", q=q, i=i, j=j, n=N, west=1 - i / 23))
    for i in range(24):
        for j in range(3):
            q = cell(lambda u, v: Vector((XL + u, YFR + 0.04, 0.7 + v)), i * 0.5, (i + 1) * 0.5, j * 0.38, (j + 1) * 0.38)
            panes.append(NS(where="front", q=q, i=i, j=j, n=-Y, west=1 - i / 23))
    cy = (YW - (YFR + 0.06)) / 8
    for sx, x in ((-1, XL + 0.04), (1, XR - 0.04)):
        for i in range(8):
            y0, y1 = YFR + 0.06 + i * cy, YFR + 0.06 + (i + 1) * cy
            j = 0
            while 0.7 + j * 0.4 < roof_z(y0) - 0.2:
                z0, z1 = 0.7 + j * 0.4, 0.7 + (j + 1) * 0.4
                j += 1
                if sx > 0 and y1 > DY0 and y0 < DY1 and z0 < 2.0:
                    continue  # the doorway
                za, zb = min(z1, roof_z(y0) - 0.04), min(z1, roof_z(y1) - 0.04)
                q = [Vector((x, y0 + 0.03, z0 + 0.03)), Vector((x, y1 - 0.03, z0 + 0.03)), Vector((x, y1 - 0.03, zb - 0.03)), Vector((x, y0 + 0.03, za - 0.03))]
                panes.append(NS(where="end", q=oriented(q, X * sx), i=i, j=j, n=X * sx, west=1.0 if sx < 0 else 0.0))
    for p_ in panes:
        p_.state = "glass"
    # Holes: where the storm broke through. Four, of one to three panes, three of them in the
    # roof's west half and one in the front.
    roof = {(p_.i, p_.j): p_ for p_ in panes if p_.where == "roof"}
    front = {(p_.i, p_.j): p_ for p_ in panes if p_.where == "front"}
    holes = [[roof[(2, 4)], roof[(3, 4)], roof[(3, 5)]], [roof[(9, 6)], roof[(10, 6)]], [roof[(13, 2)]], [front[(4, 2)], front[(5, 2)]]]
    for hole in holes:
        for p_ in hole:
            p_.state = "gone"
    # Boards go where panes were lost and not replaced: mostly round the holes and to the west.
    # Odd glass (bottle green, amber, smoke) is what the Cone had that week.
    rest = [p_ for p_ in panes if p_.state == "glass"]
    T = len(panes) + 8
    centres = [sum((Vector(v) for v in p_.q), Vector()) / 4 for hole in holes for p_ in hole]

    def weight(p_):
        c = sum((Vector(v) for v in p_.q), Vector()) / 4
        near = min((c - h).length for h in centres)
        return (0.25 + p_.west * wear["wind"]) * (4.0 if near < 0.9 else 1.0) * (1.4 if p_.where == "roof" else 1.0)
    order = sorted(rest, key=lambda p_: rng.random() ** (1.0 / weight(p_)), reverse=True)
    n_board, n_odd = round(0.105 * T), int(0.075 * T)
    for p_ in order[:n_board]:
        p_.state = "board"
    for p_ in rng.sample(order[n_board:], n_odd):
        p_.state = "odd"
    lit, plain = [], []
    for p_ in panes:
        if p_.state == "gone":
            continue
        c = jit(P.aqua, rng, 0.025)
        if p_.state == "board":
            c = jit(P.tar if rng.random() < 0.25 else P.drift, rng)  # hull planks, some still tarred
        elif p_.state == "odd":
            c = jit(rng.choice([P.green, P.amber, P.smoke]), rng, 0.03)
        plain.append((p_.q if p_.where != "roof" else oriented(p_.q, N), c))
    raw(k, plain, two=True)

    # The frame. Roof: a rafter on each bay line, a lighter bar between, purlin bars across.
    for i in range(25):
        full = i % 2 == 0
        a = XL + 0.035 + (12.0 - 0.07) * i / 24
        t0 = 2 * cvr if i in (7, 17) else 0.0
        w, h = (0.07, 0.12) if full else (0.045, 0.08)
        timber(R(a, t0, 0.0), R(a, S, 0.0), w, h, 3 if full else 2, up=N)
    for j in range(1, NR):
        runs = [(XL, XR)] if j != 1 else [(XL, XL + 3.0), (XL + 4.0, XL + 8.0), (XL + 9.0, XR)]
        for x0, x1 in runs:
            timber(R(x0, j * cvr, 0.0), R(x1, j * cvr, 0.0), 0.04, 0.06, max(1, round((x1 - x0) / 3)), up=N)
    timber(R(XL, 0.03, 0.0), R(XR, 0.03, 0.0), 0.09, 0.12, 4, up=N)
    timber((XL, YFR + 0.05, ZE - 0.02), (XR, YFR + 0.05, ZE - 0.02), 0.1, 0.1, 4)
    # Front: a post on each bay line and a mullion between, two rails, a sill on the wall.
    for i in range(25):
        full = i % 2 == 0
        a = XL + 0.04 + (12.0 - 0.08) * i / 24
        timber((a, YFR + 0.05, 0.7), (a, YFR + 0.05, ZE - 0.06), 0.08 if full else 0.045, 0.1 if full else 0.07, 1, up=Y)
    for z in (0.74, 1.08, 1.46):
        timber((XL, YFR + 0.05, z), (XR, YFR + 0.05, z), 0.05 if z > 0.8 else 0.1, 0.07 if z > 0.8 else 0.12, 4, up=Y)
    # Ends: posts, rails and the end rafter; the door frame at the east end.
    for sx, x in ((-1, XL + 0.05), (1, XR - 0.05)):
        for i in range(9):
            y = YFR + 0.06 + i * cy
            if sx > 0 and DY0 < y < DY1:
                timber((x, y, 2.0), (x, y, roof_z(y) - 0.08), 0.045, 0.07, 1, up=X)
                continue
            timber((x, y, 0.7), (x, y, roof_z(y) - 0.08), 0.045 if 0 < i < 8 else 0.09, 0.08, 1, up=X)
        for z in (1.1, 1.5, 1.9, 2.3, 2.7):
            y0 = max(YFR + 0.06, YE + (z + 0.12 - ZE) / (ZT - ZE) * run)
            if sx > 0 and z < 2.0:
                for ya, yb in ((y0, DY0), (DY1, YW)):
                    if yb - ya > 0.1:
                        timber((x, ya, z), (x, yb, z), 0.04, 0.06, 1, up=X)
            elif YW - y0 > 0.1:
                timber((x, y0, z), (x, YW, z), 0.04, 0.06, 1, up=X)
        timber((x, YFR + 0.05, 0.74), (x, YW, 0.74), 0.1, 0.1, 1, up=X) if sx < 0 else None
        timber(R(x, 0.0, -0.02), R(x, S, -0.02), 0.1, 0.13, 3, up=N)
    for y in (DY0, DY1):
        timber((XR - 0.05, y, 0.0), (XR - 0.05, y, 2.06), 0.09, 0.1, 1, up=X)
    timber((XR - 0.05, DY0, 2.03), (XR - 0.05, DY1, 2.03), 0.09, 0.09, 1, up=X)
    # The door, swung in against the back bed: boards below, six panes above.
    hinge = Vector((XR - 0.1, DY1 - 0.05, 0.0))
    du = Vector((-cos(rad(12)), -sin(rad(12)), 0))
    dn = Vector((du.y, -du.x, 0))
    put(k, lbox(Vector((0.0, 0.05, -0.025)), Vector((0.84, 0.95, 0.025)), fn=lambda q: hinge + du * q.x + Z * q.y + dn * q.z), jit(P.drift, rng))
    for a, b in (((0, 0.05), (0, 1.98)), ((0.84, 0.05), (0.84, 1.98)), ((0, 1.96), (0.84, 1.96)), ((0, 0.97), (0.84, 0.97))):
        timber(hinge + du * a[0] + Z * a[1], hinge + du * b[0] + Z * b[1], 0.07, 0.06, 1, up=dn)
    pane_grid(k, rng, lambda u, v, w: hinge + du * (0.06 + u) + Z * (1.0 + v) + dn * w, 2, 3, 0.36, 0.31, glazing(rng, P.aqua, P.smoke, 1, [(i, j) for i in range(2) for j in range(3)]), back=paint2, two=True, lift=0.0)

    # Two roof vents propped open: each two panes square, hinged at the wall.
    for i0 in (6, 16):
        x0 = XL + i0 * 0.5
        lift = rad(24)
        Dv = (D * cos(lift) + N * sin(lift)).normalized()
        Nv = (N * cos(lift) - D * sin(lift)).normalized()
        V = lambda a, t, h=0.0, Dv=Dv, Nv=Nv: Vector((a, YW, ZT)) + N * 0.06 + Dv * t + Nv * h  # noqa: E731
        for a0, a1, t0, t1 in ((x0, x0 + 1.0, 0.0, 0.0), (x0, x0 + 1.0, 2 * cvr, 2 * cvr), (x0, x0, 0.0, 2 * cvr), (x0 + 1.0, x0 + 1.0, 0.0, 2 * cvr), (x0 + 0.5, x0 + 0.5, 0.0, 2 * cvr)):
            timber(V(a0, t0), V(a1, t1), 0.06, 0.07, 1, up=Nv)
        raw(k, [(oriented(cell(lambda u, v: V(x0 + u, v), i * 0.5, (i + 1) * 0.5, j * cvr, (j + 1) * cvr), Nv), jit(P.aqua, rng, 0.025)) for i in range(2) for j in range(2)], two=True)
        put(k, beam(R(x0 + 0.5, 2 * cvr, 0.03), V(x0 + 0.5, 2 * cvr - 0.05), 0.03, 0.03), jit(P.drift, rng))

    # Inside: a flagged path between two beds; vines on the warm wall, rows of greens in front.
    put(k, box((XL + 0.3, -0.45, 0.0), (XR - 0.3, 0.75, 0.03)), jit(P.pale, rng))
    for y0, y1 in ((YFR + 0.3, -0.45), (0.75, YW)):
        put(k, box((XL + 0.3, y0, 0.0), (XR - 0.3, y1, 0.26)), lambda co, n, c=jit(P.peat, rng), e=jit(P.drift, rng): c if n.z > 0.5 else e)
    for i in range(23):
        for y in (-1.02, -0.66):
            if rng.random() < 0.2:
                continue  # cut and eaten
            tuft(k, rng, (XL + 0.6 + i * 0.48 + rng.uniform(-0.05, 0.05), y, 0.26), rng.uniform(0.14, 0.2), rng.uniform(0.16, 0.3), LEAF if rng.random() < 0.8 else mix(LEAF, P.heather, 0.5), 5)
    for i in range(11):
        x = XL + 0.8 + i * 1.04
        if rng.random() < 0.12:
            continue
        put(k, beam((x, 1.2, 0.26), (x + 0.05, 1.68, 2.5), 0.03, 0.03), jit(P.drift, rng))
        for j in range(4):
            c = Vector((x + rng.uniform(-0.12, 0.12), 1.25 + 0.1 * j + rng.uniform(-0.05, 0.05), 0.6 + j * 0.5))
            put(k, sphere(c, rng.uniform(0.2, 0.3), 1, squash=0.8), jit(LEAF, rng, 0.04), soft=c)
            if rng.random() < 0.5:
                put(k, sphere(c + Vector((rng.uniform(-0.15, 0.15), -0.2, -0.05)), 0.055, 0), jit(on(P.amber, "leaves"), rng), soft=c)
    # The lantern: one faint strip of light on the warm wall under an iron hood, below the east
    # vent, so that it shows through the vent, the door and the nearest hole.
    lx0, lx1, lz = 1.9, 3.1, 2.6
    raw(k, [([Vector((lx0, YW - 0.07, lz)), Vector((lx1, YW - 0.07, lz)), Vector((lx1, YW - 0.07, lz + 0.11)), Vector((lx0, YW - 0.07, lz + 0.11))], P.amber),
            ([Vector((lx0, YW, lz)), Vector((lx1, YW, lz)), Vector((lx1, YW - 0.07, lz)), Vector((lx0, YW - 0.07, lz))], P.amber)], glow="Glow")
    put(k, box((lx0 - 0.05, YW - 0.12, lz + 0.11), (lx1 + 0.05, YW, lz + 0.15)), P.iron)

    # Along the front, in the 0.65 m strip: gutter, downpipe and rain butt at the east end; the
    # kelp heap with its fork at the west end, and the cold frame beside it.
    put(k, box((XL, YE - 0.08, ZE - 0.1), (XR, YE + 0.03, ZE - 0.01)), mix(P.iron, P.rust, 0.5))
    bx, by = 5.6, -1.95
    barrel(k, rng, (bx, by, 0.0), 0.29, 0.95, wood=P.tar, salt=0.0, head=False, sides=10)
    put(k, lathe([(0.26, 0.86), (0.02, 0.86)], 10, Matrix.Translation((bx, by, 0)), caps=(False, False)), on(P.smoke, "glass"), closed=False)
    put(k, tube([(bx, YE - 0.03, ZE - 0.1), (bx, YE - 0.03, 1.45), (bx, by + 0.1, 1.15), (bx, by + 0.1, 0.95)], 0.045, 4), mix(P.iron, P.rust, 0.6))
    kelp_heap(k, rng, (-4.9, -1.92, 0.0), 0.8, 0.27, 0.5, fronds=0)
    for e in (-1, 1):
        kelp(k, rng, (-4.9 + e * 0.6, -1.93, 0.0), 3, 0.45, dirn=(e, 0), spread=0.3)
    put(k, tube([(-4.55, -1.98, 0.3), (-4.2, -2.1, 1.35)], 0.022, 4), jit(P.drift, rng))
    for e in (-1, 0, 1):
        put(k, tube([(-4.56 + e * 0.05, -1.97 - e * 0.02, 0.36), (-4.67 + e * 0.06, -1.94 - e * 0.02, 0.05)], 0.011, 3), P.iron)
    put(k, beam((-4.61, -1.99, 0.36), (-4.51, -1.95, 0.36), 0.03, 0.03), P.iron)
    cx0, cx1 = -3.6, -2.2
    put(k, box((cx0, YS + 0.02, 0.0), (cx1, YFR - 0.02, 0.24)), lambda co, n, c=jit(P.drift, rng), s=jit(P.peat, rng): s if n.z > 0.5 else c)
    put(k, prism([(YFR - 0.02, 0.24), (YFR - 0.02, 0.42), (YS + 0.02, 0.24)], cx0, cx0 + 0.04, lambda a, s, z: Vector((a, s, z))), jit(P.drift, rng))
    put(k, prism([(YFR - 0.02, 0.24), (YFR - 0.02, 0.42), (YS + 0.02, 0.24)], cx1 - 0.04, cx1, lambda a, s, z: Vector((a, s, z))), jit(P.drift, rng))
    for i in range(5):
        tuft(k, rng, (cx0 + 0.2 + i * 0.25, -1.9, 0.24), 0.08, 0.12, LEAF, 4)
    ld = Vector((0, 0.58, 0.18)).normalized()
    for half, up_ in ((0, 0.0), (1, 0.22)):  # two lights; the second propped for air
        o = Vector((cx0 + 0.02 + half * 0.69, YS + 0.03, 0.26))
        d2 = (ld * cos(up_) + Vector((0, -ld.z, ld.y)) * sin(up_)) if up_ else ld
        n2 = Vector((0, -d2.z, d2.y))
        o = o + (ld * 0.61 - d2 * 0.61 if up_ else Vector())
        pane_grid(k, rng, lambda u, v, w, o=o, d2=d2, n2=n2: o + X * u + d2 * v + n2 * w, 2, 2, 0.335, 0.305, glazing(rng, P.aqua, P.smoke, 1, [(i, j) for i in range(2) for j in range(2)]), back=jit(paint2, rng), two=True)
        if up_:
            put(k, beam(o + X * 0.33 + Z * -0.02, Vector((o.x + 0.33, YS + 0.05, 0.25)), 0.025, 0.025), jit(P.drift, rng))
    fit(k, 12.0, 4.5)
    found(k, 1.8)
    count = {s: sum(1 for p_ in panes if p_.state == s) for s in ("glass", "board", "odd", "gone")}
    count["glass"] += 8  # the vents' panes
    return dict(wear=wear, body_m=[12.0, round(2.25 - YFR, 2)], strip_m=round(YFR - YS, 2), bays=12, panes=T, boarded=count["board"], odd_glass=count["odd"], missing=count["gone"], holes=len(holes),
                not_original_share=round((count["board"] + count["odd"] + count["gone"]) / T, 3), odd_share=round(count["odd"] / T, 3))


# ---------------------------------------------------------------------------------------------
# 4. The Strand set


def gen_net_rack(k, rng):
    """A drying rack: two crossed pairs of driftwood poles, an old oar for the top rail, a tarred
    net hung over it with a mended patch, a tear, a lead line and three glass floats."""
    for sx in (-1, 1):
        for sy in (-1, 1):
            put(k, tube([(sx * 1.42, sy * 0.25, 0.0), (sx * 1.3, -sy * 0.05, 2.17)], [0.045, 0.032], 6), jit(P.drift, rng))
        put(k, tube([(sx * 1.4, -0.2, 0.42), (sx * 1.4, 0.2, 0.42)], 0.025, 4), jit(P.drift, rng))
    put(k, tube([(-1.5, 0, 1.98), (1.05, 0, 1.98)], 0.035, 6), jit(P.drift, rng))  # the oar: loom, then blade
    put(k, box((1.0, -0.015, 1.9), (1.5, 0.015, 2.06), bevel=0.01), jit(P.chalkblue, rng))
    put(k, tube([(-1.38, 0.0, 0.42), (1.38, 0.0, 0.42)], 0.022, 4), jit(P.drift, rng))
    NU, NV = 12, 8

    def node(i, j, back=False):
        v = j / NV
        x = (-1.2 + 2.4 * i / NU) * (1 - 0.05 * v)
        if back:
            return Vector((x, 0.05 + 0.1 * v, 2.02 - 0.75 * v))
        y = -0.05 - 0.2 * v ** 0.7 + 0.025 * sin(i * 1.3 + j)
        return Vector((x, y, 2.02 - 1.62 * v - 0.05 * sin(PI * i / NU * 6) ** 2 * (1 - v)))
    net, mend = on(P.tar, "cloth"), on(P.drift, "cloth")
    polys = []
    for back, rows in ((False, NV), (True, 4)):
        for i in range(NU):
            for j in range(rows):
                if not back and 7 <= i <= 8 and 4 <= j <= 5:
                    continue  # a tear
                a, b = (node(i, j, back), node(i + 1, j + 1, back)) if (i + j) % 2 == 0 else (node(i + 1, j, back), node(i, j + 1, back))
                side = (b - a).cross(Y).normalized()
                c = mend if not back and 2 <= i <= 4 and 2 <= j <= 4 else net
                polys += [(q, jit(c, rng, 0.02)) for q in ribbon([a, b], 0.024, side)]
    raw(k, polys, two=True)
    put(k, tube([node(i, NV) for i in range(NU + 1)], 0.02, 3), P.iron)  # the lead line
    for i, c in ((1, P.green), (6, P.amber), (11, P.aqua)):
        glass_float(k, rng, node(i, 0) + Vector((0, -0.13, -0.02)), c, r=0.11)
    fit(k, 3.0, 0.6, 2.2)
    found(k, 0.4)


def gen_barrels(k, rng):
    """Three fish barrels and one on its side: driftwood staves, rusting hoops, salt crusted
    towards the heads. One stands open, packed with fish in salt; its lid leans beside it."""
    oiled = mix(P.drift, P.tar, 0.3)  # staves dark with brine and fish oil
    barrel(k, rng, (-0.57, 0.36, 0.0), 0.31, 1.1, oiled, salt=0.75)
    barrel(k, rng, (0.08, 0.4, 0.0), 0.3, 0.98, oiled, salt=0.6)
    M = barrel(k, rng, (0.62, 0.3, 0.0), 0.3, 0.95, oiled, salt=0.8, head=False)
    put(k, lathe([(0.25, 0.88), (0.02, 0.9)], 12, M, caps=(False, False)), jit(P.lime, rng, 0.02), closed=False)  # salt
    silver = on(P.smoke, "metal")
    polys = []
    for i in range(7):
        a = i / 7 * TAU
        d, s = Vector((cos(a), sin(a), 0)), Vector((-sin(a), cos(a), 0))
        c = Vector((0.62, 0.3, 0.905)) + d * 0.12
        polys.append(([c - d * 0.1, c + s * 0.035, c + d * 0.1 + Z * 0.01, c - s * 0.035], jit(silver, rng)))
        polys.append(([c + d * 0.1, c + d * 0.15 + s * 0.035, c + d * 0.15 - s * 0.035], jit(silver, rng)))
    raw(k, polys, two=True)
    Ml = Matrix.Translation((0.64, -0.06, 0.25)) @ Matrix.Rotation(rad(76), 4, "X")
    put(k, lathe([(0.25, -0.02), (0.25, 0.02)], 12, Ml), jit(P.drift, rng), closed=True)
    Ms = Matrix.Translation((-0.86, -0.39, 0.3)) @ Matrix.Rotation(rad(8), 4, "Z") @ Matrix.Rotation(rad(90), 4, "Y")
    barrel(k, rng, None, 0.3, 0.95, oiled, M=Ms, salt=0.35)
    for e in (-1, 1):  # chocks
        put(k, prism([(0.0, 0.0), (0.2, 0.0), (0.0, 0.13)], -0.07, 0.07, lambda a, s, z, e=e: Vector((-0.38 + a, -0.39 + e * (0.3 - s), z))), jit(P.drift, rng))
    fit(k, 1.8, 1.4, 1.1)
    found(k, 0.4)


def gen_creels(k, rng):
    """Three kelp creels of woven moor grass: one heaped with wrack, one empty, one tipped over
    with its kelp spilling across the quay."""
    creel(k, rng, Matrix.Translation((-0.42, 0.18, 0.0)), 0.27, 0.66, fill=0.34)
    creel(k, rng, Matrix.Translation((0.38, 0.2, 0.0)) @ Matrix.Rotation(rad(140), 4, "Z"), 0.24, 0.56)
    Mt = Matrix.Translation((-0.5, -0.24, 0.24)) @ Matrix.Rotation(rad(-6), 4, "Z") @ Matrix.Rotation(rad(97), 4, "Y")
    creel(k, rng, Mt, 0.25, 0.58, fill=0.05)
    mouth = Mt @ Vector((0, 0, 0.58))
    kelp_heap(k, rng, (mouth.x + 0.16, mouth.y - 0.02, 0.0), 0.2, 0.15, 0.14, fronds=0)
    kelp(k, rng, (mouth.x + 0.02, mouth.y, 0.0), 9, 0.36, dirn=(1, -0.1), spread=0.55)
    fit(k, 1.4, 1.0, 0.9)
    found(k, 0.4)


def gen_bollard(k, rng):
    """A ship's bollard from the ship days, 1.1 m of cast iron on a bolted flange: far too big for
    any boat the harbour has now. Rust below (salt), worn smooth where ropes ran; a fishing
    boat's thin line is wound round its waist."""
    def col(co, n):
        rust = 0.75 * max(0.0, 1 - co.z / 0.5) + 0.45 * max(0.0, nz(co.x * 7, co.y * 7, co.z * 4)) + (0.3 if 0.8 < co.z < 0.9 else 0.0)
        worn = 0.5 if 0.3 < co.z < 0.62 else 0.0
        return mix(mix(P.iron, P.rust, min(0.85, rust)), P.pale, worn * (0.4 + 0.3 * nz(co.x * 5, co.y * 5, co.z * 9)))
    prof = [(0.3, 0.0), (0.3, 0.05), (0.25, 0.08), (0.21, 0.16), (0.185, 0.3), (0.17, 0.62), (0.18, 0.74), (0.24, 0.8), (0.285, 0.88), (0.29, 0.96), (0.25, 1.05), (0.14, 1.1)]
    put(k, lathe(prof, 14), col)
    put(k, lathe([(0.215, 0.2), (0.225, 0.23), (0.205, 0.26)], 14, caps=(False, False)), col, closed=False)
    for i in range(6):
        a = (i + 0.5) / 6 * TAU
        put(k, lathe([(0.03, 0.05), (0.03, 0.085)], 6, Matrix.Translation((cos(a) * 0.265, sin(a) * 0.265, 0))), P.rust)
    put(k, tube([(-0.29, 0, 0.72), (0.29, 0, 0.72)], 0.04, 8), col)
    rope = on(mix(P.sand, P.drift, 0.4), "cloth")
    turns = [Vector((cos(t) * (0.205 + 0.01 * sin(t * 0.37)), sin(t) * (0.205 + 0.01 * sin(t * 0.37)), 0.33 + 0.058 * t / TAU)) for t in [i / 9 * TAU for i in range(9 * 4 + 1)]]
    tail = [turns[-1], Vector((0.19, 0.1, 0.62)), Vector((0.12, 0.2, 0.75)), Vector((0.02, 0.26, 0.6)), Vector((0.0, 0.265, 0.3)), Vector((0.03, 0.27, 0.12))]
    put(k, tube(turns + tail[1:], 0.03, 5), lambda co, n: mix(rope, P.drift, 0.3 + 0.3 * nz(co.x * 30, co.y * 30, co.z * 30)))
    fit(k, 0.6, 0.6, 1.1)
    found(k, 0.4)


def gen_quay_lamp(k, rng):
    """A quay lamp: an iron post leaded into a basalt block, a ladder bar, and a lantern glazed
    in whatever panes there were: smoke, aqua, amber, bottle green, and one of tin."""
    put(k, box((-0.2, -0.2, 0.0), (0.2, 0.2, 0.3), bevel=0.03), jit(P.basalt, rng))

    def col(co, n):
        streak = max(0.0, nz(co.x * 25, co.y * 25, 1.0)) * (max(0.0, 1 - (2.2 - co.z) / 1.3) if co.z < 2.2 else 0.3)
        return mix(P.iron, P.rust, min(0.8, 0.2 + streak + 0.6 * max(0.0, 1 - (co.z - 0.3) / 0.35)))
    put(k, lathe([(0.1, 0.3), (0.1, 0.48), (0.07, 0.6), (0.052, 2.14), (0.075, 2.2), (0.045, 2.26), (0.045, 2.52), (0.1, 2.6)], 8), col)
    put(k, tube([(-0.25, 0, 2.2), (0.25, 0, 2.2)], 0.022, 6), col)
    for e in (-1, 1):
        put(k, sphere((e * 0.25, 0, 2.2), 0.04, 0), P.iron)
    Z0, Z1, W0, W1 = 2.6, 3.0, 0.15, 0.21  # the lantern's glazing: a box of 2 x 2 panes a side, wider at the top
    put(k, lathe([(W0 * 1.5, Z0 - 0.03), (W0 * 1.5, Z0)], 4, Matrix.Rotation(rad(45), 4, "Z")), P.iron)
    glassy = [P.smoke, P.aqua, P.amber, P.green, P.smoke, P.aqua, P.amber, P.smoke]
    for s in range(4):
        u = Vector((cos(s * PI / 2), sin(s * PI / 2), 0))
        n = Vector((u.y, -u.x, 0))

        def pt(a, v, w, u=u, n=n):
            half = W0 + (W1 - W0) * v / (Z1 - Z0)
            return u * ((a / 0.4 - 0.5) * 2 * half) + n * (half + w) + Z * (Z0 + v)
        tin = (1, 0) if s == 2 else None
        cols = {(i, j): jit(glassy[(s * 3 + i * 2 + j) % len(glassy)], rng, 0.03) for i in range(2) for j in range(2)}
        pane_grid(k, rng, pt, 2, 2, 0.2, 0.2, lambda i, j: mix(P.iron, P.rust, 0.5) if (i, j) == tin else cols[(i, j)], bar=0.03, back=P.iron, glow="Glow", lift=0.006)
        put(k, beam(pt(0, 0, 0.0) , pt(0, Z1 - Z0, 0.0), 0.035, 0.035, up=n), P.iron)
    put(k, lathe([(W1 * 1.62, Z1 - 0.01), (W1 * 1.62, Z1 + 0.02), (0.07, Z1 + 0.13), (0.07, Z1 + 0.17), (0.02, Z1 + 0.2)], 4, Matrix.Rotation(rad(45), 4, "Z")), mix(P.iron, P.rust, 0.35))
    fit(k, None, None, 3.2)
    found(k, 0.4)


def gen_boat(k, rng):
    """A clinker boat turned keel up on two trestles for the winter: tarred, greying along the
    keel, with a new plank let into one side and a tin patch on the other; her oars lie under
    her."""
    L, BEAM, ZK, NS_, NSTR = 2.1, 0.66, 1.235, 14, 5

    def section(s, u, e, out=0.0):
        """Station s in -1..1, round the hull by u from the gunwale (0) to the keel (1), side e."""
        b = BEAM * (1 - abs(s) ** 2.6) ** 0.62 + 0.02
        zg = 0.62 - 0.1 * s * s
        w = (b + out) * cos(u * PI / 2) ** 0.75
        return Vector((L * s * (1 - 0.035 * (1 - u)), e * w, zg + (ZK - zg + out) * sin(u * PI / 2) ** 0.85))
    polys = []
    lap = 0.03
    shade = {}
    for e in (-1, 1):
        for j in range(NSTR):
            u0, u1 = j / NSTR, (j + 1) / NSTR
            for i in range(NS_):
                s0, s1 = -1 + 2 * i / NS_, -1 + 2 * (i + 1) / NS_
                key = (e, j, (i + j) // 3)
                if key not in shade:  # planks run about three stations; they grey towards the keel
                    shade[key] = mix(jit(P.tar, rng, 0.03), P.drift, 0.1 + 0.35 * (j / (NSTR - 1)) ** 1.5 * rng.uniform(0.6, 1.0))
                c = shade[key]
                q = [section(s0, u0, e), section(s1, u0, e), section(s1, u1, e, lap), section(s0, u1, e, lap)]
                n = Vector((0, e, 0.5))
                polys.append((oriented(q, n), c))
                if j < NSTR - 1:
                    polys.append((oriented([q[3], q[2], section(s1, u1, e), section(s0, u1, e)], Z), mix(c, P.tar, 0.5)))
    for i in range(NS_):  # dark inside
        s0, s1 = -1 + 2 * i / NS_, -1 + 2 * (i + 1) / NS_
        polys.append((oriented([section(s0, 0.02, -1), section(s1, 0.02, -1), section(s1, 0.02, 1), section(s0, 0.02, 1)], -Z), P.tar))
    # A new plank on the port side, a tin patch on the starboard bow.
    plank = [section(-0.15, 0.4, -1, 0.034), section(0.3, 0.4, -1, 0.034), section(0.3, 0.6, -1, 0.05), section(-0.15, 0.6, -1, 0.05)]
    polys.append((oriented(plank, Vector((0, -1, 0.5))), jit(P.drift, rng)))
    tin = [section(0.5, 0.25, 1, 0.04), section(0.68, 0.25, 1, 0.04), section(0.68, 0.48, 1, 0.05), section(0.5, 0.48, 1, 0.05)]
    polys.append((oriented(tin, Vector((0, 1, 0.5))), mix(P.iron, P.rust, 0.7)))
    raw(k, polys)
    keel = [section(-1 + 2 * i / NS_, 1.0, 1) * Vector((1, 0, 1)) + Z * 0.025 for i in range(NS_ + 1)]
    for a, b in zip(keel, keel[1:]):
        put(k, beam(a, b, 0.07, 0.09), jit(mix(P.tar, P.drift, 0.6), rng, 0.02))
    for e in (-1, 1):  # stem and stern posts, and the rubbing strakes worn bare
        post = [section(e, u, 1) * Vector((1, 0, 1)) + X * e * 0.03 for u in (0.0, 0.35, 0.7, 1.0)]
        put(k, tube(post, 0.045, 4), jit(mix(P.tar, P.drift, 0.4), rng, 0.02))
        rub = [section(-1 + 2 * i / NS_, 0.03, e, 0.02) for i in range(NS_ + 1)]
        put(k, tube(rub, 0.03, 4), jit(P.drift, rng))
    for x in (-1.05, 1.05):  # trestles
        put(k, beam((x, -0.75, 0.53), (x, 0.75, 0.53), 0.11, 0.1), jit(P.drift, rng))
        for ey in (-1, 1):
            for ex in (-1, 1):
                put(k, beam((x, ey * 0.6, 0.5), (x + ex * 0.26, ey * 0.7, 0.0), 0.07, 0.07, up=Y), jit(P.drift, rng))
            put(k, beam((x - 0.15, ey * 0.66, 0.22), (x + 0.15, ey * 0.66, 0.22), 0.05, 0.05, up=Y), jit(P.drift, rng))
    for y, tilt in ((-0.2, 0.0), (0.12, 0.04)):  # the oars, on the trestles
        put(k, tube([(-1.75, y, 0.615), (1.0, y + tilt, 0.615)], 0.03, 5), jit(P.drift, rng))
        put(k, box((1.0, y + tilt - 0.08, 0.6), (1.7, y + tilt + 0.08, 0.63), bevel=0.01), jit(P.chalkblue if y < 0 else P.drift, rng))
    painter = [section(1, 0.1, 1) * Vector((1, 0, 1)), Vector((2.02, 0.05, 0.4)), Vector((1.8, 0.1, 0.05)), Vector((1.6, 0.25, 0.03)), Vector((1.7, 0.4, 0.03))]
    put(k, tube(painter, 0.018, 4), on(P.sand, "cloth"))
    fit(k, 4.2, 1.5, 1.3)
    found(k, 0.4)


def gen_peat_stack(k, rng):
    """A winter's peat, stacked in courses under a tarred cloth weighted with stones on ropes.
    The east end is being used: the cloth is folded back and the courses step down."""
    C, CH = 7, 0.16
    turves(k, rng, -0.97, 0.97, -0.45, 0.45, 0.0, C, ch=CH, step=lambda i: 0.34 * max(0, i - 3))
    top = C * CH
    XE = 0.97 - 0.34 * 3 - 0.1  # the cloth ends where the stack is whole

    def cloth(u, v):
        """u along the stack, v across: over the crown and down the sides."""
        x = -1.0 + (XE + 1.0) * u
        yy = -0.48 + 0.96 * v
        edge = min(1.0, abs(yy) / 0.48) ** 3
        fold = 0.03 * sin(u * 23) * edge
        z = top + 0.02 + 0.2 * (1 - (yy / 0.48) ** 2) * (0.4 + 0.6 * sin(PI * min(1.0, u * 1.15)) ** 0.5)
        return Vector((x, yy + fold * (1 if yy > 0 else -1), z))
    NUc, NVc = 10, 6
    tarp = on(P.tar, "cloth")
    polys, top_polys = [], []
    for i in range(NUc):
        for j in range(NVc):
            patch = 3 <= i <= 4 and j >= 4
            c = jit(on(P.kelp, "cloth") if patch else mix(tarp, P.drift, 0.12 * (1 + nz(i * 0.7, j * 0.7))), rng, 0.015)
            top_polys.append((oriented([cloth(i / NUc, j / NVc), cloth((i + 1) / NUc, j / NVc), cloth((i + 1) / NUc, (j + 1) / NVc), cloth(i / NUc, (j + 1) / NVc)], Z), c))
        for e in (0, 1):  # the skirts, scalloped between the ropes
            a, b = cloth(i / NUc, e), cloth((i + 1) / NUc, e)
            drop = lambda u: 0.34 + 0.12 * abs(sin(PI * u * 2.5))  # noqa: E731
            o = Vector((0, (0.03 if e else -0.03), 0))
            polys.append((oriented([a, b, b + o - Z * drop((i + 1) / NUc), a + o - Z * drop(i / NUc)], Y if e else -Y), jit(tarp, rng, 0.015)))
    a, b = cloth(0, 0), cloth(0, 1)
    polys.append((oriented([a, b, b - X * 0.03 - Z * 0.4, a - X * 0.03 - Z * 0.4], -X), jit(tarp, rng, 0.015)))
    raw(k, top_polys)
    raw(k, polys, two=True)
    put(k, tube([cloth(1.0, j / NVc) + X * 0.05 + Z * 0.03 for j in range(NVc + 1)], 0.055, 5), jit(tarp, rng, 0.02))  # the cloth rolled back
    for u in (0.2, 0.6, 0.98):  # ropes over the top, a basalt stone on each end
        line = [cloth(u, j / NVc) + Z * 0.02 for j in range(NVc + 1)]
        line = [line[0] + Vector((0, -0.02, -0.62))] + line + [line[-1] + Vector((0, 0.02, -0.62))]
        put(k, tube(line, 0.014, 3, caps=False), on(P.sand, "cloth"), closed=False)
        for q in (line[0], line[-1]):
            put(k, sphere(q - Z * 0.07, 0.085, 1, squash=0.85), jit(P.pale, rng), soft=q - Z * 0.07)
    for x, y, a in ((0.82, -0.36, 0.3), (0.8, 0.26, 1.2)):  # loose turves at the working end
        put(k, moved(box((-0.18, -0.07, 0.0), (0.18, 0.07, 0.11)), Matrix.Translation((x, y, 0)) @ Matrix.Rotation(a, 4, "Z")), jit(P.peat, rng, 0.04))
    fit(k, 2.0, 1.2, 1.4)
    found(k, 0.4)


def gen_floats(k, rng):
    """A 2 m spar with a crossed oar loom, hung with seven glass floats in net bags (bottle green,
    amber, aqua), and beside it a crate of cullet for the Cone, with the Strand's one piece of
    cobalt on top."""
    put(k, tube([(0, 0, 0), (0.0, 0.0, 2.0)], [0.065, 0.045], 6), jit(P.drift, rng))
    put(k, tube([(-0.48, 0, 1.82), (0.48, 0, 1.86)], 0.03, 5), jit(P.drift, rng))
    put(k, tube([(0, -0.25, 1.4), (0, 0.22, 1.43)], 0.022, 4), jit(P.drift, rng))
    hang = [((-0.44, 0, 1.82), 0.3, P.green), ((-0.22, 0, 1.83), 0.62, P.amber), ((0.22, 0, 1.85), 0.42, P.aqua), ((0.44, 0, 1.86), 0.74, P.green),
            ((0, -0.22, 1.4), 0.34, P.aqua), ((0, 0.2, 1.43), 0.5, P.amber), ((0.03, -0.07, 1.98), 0.28, P.green)]
    for at, drop, c in hang:
        at = Vector(at)
        glass_float(k, rng, at + Vector((rng.uniform(-0.03, 0.03), rng.uniform(-0.04, 0.04) - (0.1 if at.x == 0.03 else 0.0), -drop)), c, cord=at)
    cx, cy, cw, cd = 0.78, -0.05, 0.4, 0.26  # the crate: 0.8 m long
    for z in (0.04, 0.24):
        for f, L in ((Face((cx, cy - cd, 0), X, 2 * cw), cw), (Face((cx, cy + cd, 0), -X, 2 * cw), cw), (Face((cx + cw, cy, 0), Y, 2 * cd), cd), (Face((cx - cw, cy, 0), -Y, 2 * cd), cd)):
            put(k, f.box(-L, L, z, z + 0.16, -0.025, 0.0), jit(P.drift, rng, 0.045))
    for ex in (-1, 1):
        for ey in (-1, 1):
            put(k, box((cx + ex * cw - 0.03, cy + ey * cd - 0.03, 0.0), (cx + ex * cw + 0.03, cy + ey * cd + 0.03, 0.43)), jit(P.drift, rng))
    put(k, box((cx - cw + 0.02, cy - cd + 0.02, 0.05), (cx + cw - 0.02, cy + cd - 0.02, 0.3)), mix(P.green, P.tar, 0.6))
    shards = [P.green, P.aqua, P.amber, P.smoke, P.green, P.aqua]
    polys = []
    spots = [(cx + rng.uniform(-0.34, 0.34), cy + rng.uniform(-0.2, 0.2), None) for _ in range(34)] + [(cx - 0.62, cy - 0.3, 0.0), (cx - 0.5, cy + 0.36, 0.0), (cx + 0.1, cy - 0.44, 0.0)]
    for n, (x, y, z) in enumerate(spots):
        heap = 0.3 + 0.12 * (1 - ((x - cx) / 0.4) ** 2) * (1 - ((y - cy) / 0.26) ** 2)
        base = Vector((x, y, heap if z is None else z))
        c = jit(P.cobalt if n in (3, 4) else shards[n % len(shards)], rng, 0.03)
        if n in (3, 4):
            base = Vector((cx + 0.05 + 0.1 * (n - 3), cy - 0.02, 0.42))
        r = rng.uniform(0.07, 0.12)
        a0 = rng.uniform(0, TAU)
        tri = [base + Vector((cos(a0 + i * TAU / 3) * r, sin(a0 + i * TAU / 3) * r, 0)) for i in range(3)]
        tip = base + Vector((rng.uniform(-0.04, 0.04), rng.uniform(-0.04, 0.04), r * rng.uniform(0.5, 1.0)))
        polys += [([tri[i], tri[(i + 1) % 3], tip], c) for i in range(3)]
    raw(k, polys)
    found(k, 0.4)


# ---------------------------------------------------------------------------------------------
# Export and report

MODELS = dict(cone=(gen_cone, 1.8), row=(gen_row, 1.8), glasshouse=(gen_glasshouse, 1.8), net_rack=(gen_net_rack, 0.4), barrels=(gen_barrels, 0.4),
              creels=(gen_creels, 0.4), bollard=(gen_bollard, 0.4), quay_lamp=(gen_quay_lamp, 0.4), boat=(gen_boat, 0.4), peat_stack=(gen_peat_stack, 0.4),
              floats=(gen_floats, 0.4))
PALETTE = [tuple(v) for v in vars(P).values()]


def measure(obj):
    """What the coordinator checks, measured from the finished mesh."""
    me = obj.data
    col = me.color_attributes["Color"].data
    tris = by_mat = tagged_t = lit_t = on_pal = blend = 0
    by_mat, seen = {}, {}
    for poly in me.polygons:
        t = len(poly.vertices) - 2
        tris += t
        name = me.materials[poly.material_index].name
        by_mat[name] = by_mat.get(name, 0) + t
        c = col[poly.loop_indices[0]].color_srgb
        if not name.startswith("Glow"):
            lit_t += t
            tagged_t += t if c[3] < 0.99 else 0
        key = (round(c[0], 2), round(c[1], 2), round(c[2], 2))
        if key not in seen:
            exact = any(max(abs(a - b) for a, b in zip(key, q)) <= 0.056 for q in PALETTE)
            seen[key] = 2 if exact else 1 if any(_near_segment(key, a, b) for i, a in enumerate(PALETTE) for b in PALETTE[i + 1:]) else 0
        on_pal += t if seen[key] == 2 else 0
        blend += t if seen[key] == 1 else 0
    above = [v.co for v in me.vertices if v.co.z >= -0.005]
    lo = [min(v[i] for v in above) for i in range(3)]
    hi = [max(v[i] for v in above) for i in range(3)]
    return dict(footprint_m=[round(hi[0] - lo[0], 3), round(hi[1] - lo[1], 3)], height_m=round(hi[2], 3),
                foundation_m=round(-min(v.co.z for v in me.vertices), 3), tris=tris, materials=by_mat,
                surface_tagged_share=round(tagged_t / max(lit_t, 1), 4), palette_share=round(on_pal / tris, 4), palette_wear_blend_share=round(blend / tris, 4))


def _near_segment(c, a, b):
    c, a, b = Vector(c), Vector(a), Vector(b)
    t = min(1.0, max(0.0, (c - a).dot(b - a) / max((b - a).length_squared, 1e-9)))
    return max(abs(x) for x in (a.lerp(b, t) - c)) <= 0.056


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--only", help="comma-separated models (default: all eleven)")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    names = a.only.split(",") if a.only else list(MODELS)
    report, t_all = {}, time.time()
    for name in names:
        t0 = time.time()
        gen, depth = MODELS[name]
        B.reset()
        rng = random.Random(f"cullet-{a.seed}-{name}")
        k = Kit(rng, dict(glow=LIGHT["Glow"][0]), pr=random.Random(f"cullet-detail-{a.seed}-{name}"))
        extra = gen(k, rng) or {}
        obj, _ = k.b.finish(name)
        path = os.path.join(a.out, f"{name}.glb")
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_vertex_color="ACTIVE", export_normals=True, export_yup=True, use_selection=False)
        rec = dict(file=f"{name}.glb", **measure(obj))
        rec["budget_tris"] = BUDGET.get(name, 1500)
        rec["within_budget"] = rec["tris"] <= rec["budget_tris"]
        rec["sha256"] = hashlib.sha256(open(path, "rb").read()).hexdigest()
        rec.update(extra)
        report[name] = rec
        print(f"GEN {name}: tris={rec['tris']}/{rec['budget_tris']} foot={rec['footprint_m']} h={rec['height_m']} tagged={rec['surface_tagged_share']} "
              f"palette={rec['palette_share']}+{rec['palette_wear_blend_share']} {time.time() - t0:.2f}s")
    print(f"GEN total {time.time() - t_all:.2f}s")
    if not a.only:
        with open(os.path.join(a.out, "report.json"), "w") as f:
            json.dump(dict(seed=a.seed, script="living/tools/blender/ab/cullet_fable.py", blender=bpy.app.version_string, models=report), f, indent=1)


if __name__ == "__main__":
    main()
