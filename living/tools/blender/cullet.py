"""Cullet's asset kit (docs/SMALL_CITY.md, phase 3): every model of the glassmakers' harbour,
built for its place from the hand-authored plan.

Run headless (living/tools/blender/gen_cullet.sh does):
    blender -b -P living/tools/blender/cullet.py -- --out living/game/assets/envs/cullet [--only cone,low_4,wall]

Reads `living/seeds/worlds/cullet/plan.json` (written by living/tools/cullet_plan.py) and writes
- `<out>/<folder>/<id>.glb` for every lot and fixture it has a generator for: the path the plan
  names (`model`), so the game finds it. A lot without a generator writes nothing, and the game
  draws it as a grey box;
- `<out>/fixtures.json`: where each fixture's model stands, in land metres, for the game client;
- `<out>/report.json`: each model's footprint, height, triangles, doors and checks
  (living/tools/cullet_kit_check.py re-measures the GLB files themselves).

A model is built for its lot: its footprint, height and level come from the plan, and so does its
wear (`salt`, `soot`, `wind`, `age`, `repair`, `empty`, each with a cause the plan names). The
only random numbers come from the seed the plan records for the lot (which stone is a shade
darker, where a flake of lime lies); the same plan gives the same files.

Conventions, as buildings.py: metres, +Z up, fronts face -Y, the origin at the floor in the
middle of the lot's rectangle (never re-centred: a terrace's houses must meet at their party
walls). Colour is per vertex ("Color") on one white "Body" material with the surface tag in
alpha; glowing parts are on "Glow" (oil lamp), "GlowAmber" (the furnace) or "GlowCyan" (the
Watchglass) and carry their daytime glass colour. Buildings stand on a stepped basalt foundation
1.8 m deep, props on 0.4 m. No textures, no external files.

Colour: every part takes a palette colour of SMALL_CITY section 1 (P), jittered by at most 0.05.
Wear is a second palette colour laid over the first by a named cause, never a random tint: soot
is tar, bloom is pale basalt, repairs are new slate, new brick or driftwood boards.

Compass: a model's front (-Y) looks along its lot's `facing`. For the many lots that face south
(the harbour), west is -X, the south-westerly wind strikes -X and -Y, and soot drifts to +X and
+Y. `Env` turns compass bearings into each lot's own frame.

Footprints are everything above the floor, as the settlement table measures them. Sea walls and
the Fish Steps go down into the water below their floor, outside their rectangle.
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


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildings as B  # noqa: E402
from buildings import X, Y, Z, Face, Kit, box, lbox, prism, sphere, surface_alpha, tagged, wall_skin  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
PLAN = os.path.join(ROOT, "living/seeds/worlds/cullet/plan.json")

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
# Light (the emission of the glow materials): oil lamps, the furnace and the Watchglass.
# Strengths are judged in the game at 21:30 and at 13:00 (its emission is material x exposure x
# the hour's glow, three times stronger at night): these read as lit windows at night and leave
# a pane its own glass colour by day. buildings.py's 2.6 does not show at all on daytime glass.
LIGHT = {"Glow": ((1.0, 0.74, 0.40), 220.0), "GlowDim": ((1.0, 0.74, 0.40), 80.0), "GlowAmber": ((1.0, 0.45, 0.12), 300.0), "GlowCyan": ((0.80, 0.95, 1.0), 240.0)}
# How far a glasshouse's one lantern lights its panes (`--lantern-core`, `--lantern-reach`, metres
# from the lantern strip on the warm wall): within the core every pane is lit; from there to the
# reach fewer and fewer catch a dimmer light; beyond it a pane keeps its glass colour. Glow is
# sparse and true to what is lit (SMALL_CITY §1): a lamp lights the panes near it, not the house.
LANTERN = dict(core_m=1.0, reach_m=2.4)
DOORS = []  # every door made for the current model: (centre, width, height), for the report


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
    return B.material(name, (1, 1, 1), emission=colour, strength=strength)


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
    DOORS.append(dict(at=[round(x, 3) for x in f.p(a, z0 + h / 2, -recess)], along=[round(x, 3) for x in f.u], width_m=w, height_m=h))
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


def gen_cone(k, rng, lot):
    """The glass furnace: a sooted brick cone, 14 m across and 24 m to the rim, on a basalt
    plinth, with three arched mouths (the front one lit by the furnace), five iron bands, a
    pot room tucked into the south-west corner of its 14 m lot, and a timber stair that starts
    in the south-east corner and winds up the east flank to the gallery and charging door at 7 m
    (everything stays inside the lot's square: the stair hugs the cone as it narrows). Wear: soot (rim, mouths), salt (rust, bloom), wind (lichen on the
    south-west), repair (the newer brick between 9 and 12 m, tied with iron plates)."""
    wear = lot["wear"]
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
        front = m >= 0.0  # two mouths are worked; the third's door stands half open on the glow

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
            raw(k, [(oriented([bp(-0.95, 0.5, 0.03), bp(-0.05, 0.5, 0.03), bp(-0.05, 2.3, 0.03), bp(-0.95, 1.9, 0.03)], nrm), P.amber)], glow="GlowAmber")
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

    # The stair: tarred ship's timber from the south-east corner up the east flank, 35 treads to
    # 7 m, on raking struts that lean on the cone; then the gallery, the charging door, the hoist.
    def rp(az, r, z):
        return Vector((r * sin(az), -r * cos(az), z))
    A0, A1, NT, GZ, SW_ = rad(45), rad(110), 35, 7.0, 0.85  # SW_: the stair is 0.85 m wide
    da = (A1 - A0) / NT
    for i in range(NT):
        z, az = GZ * (i + 1) / NT, A0 + da * i
        r = radius(z)
        put(k, lbox(Vector((az, r + 0.04, z - 0.06)), Vector((az + da * 1.12, r + SW_, z)), fn=lambda q: rp(q.x, q.y, q.z)), jit(P.drift, rng, 0.04))  # treads worn bare
    stations = list(range(0, NT + 1, 5))
    outer = [rp(A0 + da * i, radius(GZ * i / NT) + SW_ - 0.02, GZ * i / NT) for i in stations]
    tarred = jit(P.tar, rng, 0.02)
    for i, (a, b) in zip(stations, zip(outer, outer[1:])):
        put(k, beam(a - Z * 0.18, b - Z * 0.18, 0.07, 0.28), tarred)
        put(k, beam(a + Z * 1.05, b + Z * 1.05, 0.07, 0.09), tarred)
    for i, q in zip(stations, outer):
        put(k, beam(q - Z * 0.3, q + Z * 1.08, 0.09, 0.09, up=X), tarred)
        z = GZ * i / NT
        foot = rp(A0 + da * i, radius(max(0.0, z - 1.9)) - 0.05, z - 1.9) if z > 2.0 else Vector((q.x, q.y, 0.0))
        put(k, beam(q - Z * 0.25, foot, 0.1, 0.1, up=X), tarred)
    G0, G1, GR = A1, rad(144), radius(GZ)
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
    DA = rad(127)
    door = [(x, 1.25 + math.sqrt(max(0.0, 0.3025 - x * x))) for x in [-0.55 + 0.11 * i for i in range(11)]]
    raw(k, [([cp(DA - da_door, GZ, 0.05), cp(DA + da_door, GZ, 0.05)] + [cp(DA + x / GR, GZ + z, 0.05) for x, z in reversed(door)], mix(P.iron, P.rust, 0.45))])
    for i in range(7):
        t0, t1 = PI * i / 7, PI * (i + 1) / 7
        put(k, lbox(Vector((t0, 0.55, 0.0)), Vector((t1, 0.8, 0.1)), fn=lambda q: cp(DA + q.y * cos(q.x) / GR, GZ + 1.25 + q.y * sin(q.x), q.z), open_bottom=True), jit(P.pale, rng, 0.025))
    for e in (-1, 1):
        put(k, lbox(Vector((min(e * 0.55, e * 0.8), 0.0, 0.0)), Vector((max(e * 0.55, e * 0.8), 1.25, 0.1)), fn=lambda q: cp(DA + q.x / GR, GZ + q.y, q.z), open_bottom=True), jit(P.pale, rng, 0.025))
    put(k, lbox(Vector((-0.5, 0.75, 0.05)), Vector((0.5, 0.85, 0.09)), fn=lambda q: cp(DA + q.x / GR, GZ + q.y, q.z), open_bottom=True), P.rust)
    HZ, HA = 9.6, rad(137)  # the hoist: a cathead over the gallery's end, its rope down to a batch bucket
    tip = rp(HA, radius(HZ) + 2.45, HZ)
    put(k, beam(rp(HA, radius(HZ) - 0.1, HZ), tip, 0.16, 0.2), tarred)
    put(k, beam(rp(HA, radius(HZ - 1.5) - 0.05, HZ - 1.5), rp(HA, radius(HZ) + 1.5, HZ - 0.1), 0.11, 0.11, up=X), tarred)
    hook = tip - Vector((sin(HA), -cos(HA), 0)) * 0.2
    put(k, tube([hook - Z * 0.1, Vector((hook.x, hook.y, 2.25))], 0.02, 4, caps=False), on(P.sand, "cloth"), closed=False)
    M = Matrix.Translation((hook.x, hook.y, 1.75))
    put(k, lathe([(0.2, 0.0), (0.27, 0.5)], 8, M, caps=(True, False)), mix(P.iron, P.rust, 0.5), closed=False)
    put(k, lathe([(0.25, 0.42), (0.19, 0.02)], 8, M, caps=(False, False)), P.tar, closed=False)
    put(k, lathe([(0.24, 0.4), (0.03, 0.47)], 8, M, caps=(True, True)), jit(P.sand, rng), closed=False)  # the batch: sand and ash

    # The pot room: a lean-to in the south-west corner of the lot, 4 x 4 m with its inner half
    # swallowed by the cone, basalt under slate, its front open to the yard so the drying pots
    # can be seen. Its roof falls to the west, the weather side.
    PX0, PXI, PY0, PY1 = -6.85, -3.0, -6.85, -3.0

    def ptop(x):
        return 2.35 + (x - PX0) * 0.3
    put(k, prism([(PX0, 0), (PX0 + 0.42, 0), (PX0 + 0.42, ptop(PX0 + 0.42) - 0.1), (PX0, ptop(PX0) - 0.1)], PY0, PY1, lambda a, s, z: Vector((s, a, z))), jit(P.basalt, rng))
    put(k, prism([(PX0, 0), (PXI, 0), (PXI, ptop(PXI) - 0.1), (PX0, ptop(PX0) - 0.1)], PY1 - 0.42, PY1, lambda a, s, z: Vector((s, a, z))), jit(P.basalt, rng))
    put(k, prism([(PXI - 0.42, 0), (PXI, 0), (PXI, ptop(PXI) - 0.1), (PXI - 0.42, ptop(PXI - 0.42) - 0.1)], PY0, PY0 + 1.1, lambda a, s, z: Vector((s, a, z))), jit(P.basalt, rng))
    put(k, box((PX0, PY0, 0.0), (PXI, PY1, 0.06)), jit(P.pale, rng))
    fw = Face((PX0, (PY0 + PY1) / 2, 0), -Y, PY1 - PY0)
    for _ in range(6):  # lichen and bloom on the weather wall
        a, z, c = rng.uniform(-1.6, 1.6), rng.uniform(0.3, 2.0), rng.choice([P.lichen, P.pale, P.pale])
        raw(k, [(blotch(fw, a, z, rng.uniform(0.18, 0.4), rng), mix(P.basalt, c, 0.55))])
    window(k, rng, fw, 0.3, 1.0, (2, 3, 0.36, 0.34), glazing(rng, P.smoke, P.green, 1, [(i, j) for i in range(2) for j in range(3)]), recess=-0.02, sill=None)
    for x in (PX0 + 0.1, -5.0):
        put(k, beam((x, PY0 + 0.1, 0.06), (x, PY0 + 0.1, ptop(x) - 0.22), 0.16, 0.16, up=X), tarred)
    put(k, beam((PX0, PY0 + 0.1, ptop(PX0) - 0.16), (PXI, PY0 + 0.1, ptop(PXI) - 0.16), 0.14, 0.2, up=Y), jit(P.drift, rng))
    q = math.atan(0.3)

    def proof(a, t, h):
        return Vector((PXI - t * cos(q) + h * sin(q) * -1, a, ptop(PXI) + 0.06 - t * sin(q) + h * cos(q)))

    def pstate(a, t):
        r = rng.random()
        return jit(P.newslate, rng) if r < 0.1 else mix(jit(P.slate, rng), P.lichen, 0.3) if r < 0.1 + 0.22 * wear["wind"] and t > 2.2 else jit(P.slate, rng)
    slates(k, rng, proof, PY0 - 0.1, PY1 + 0.1, (PXI - PX0 + 0.1) / cos(q), pstate)
    put(k, box((-6.3, PY1 - 0.95, 0.06), (-5.0, PY1 - 0.42, 0.8)), jit(P.drift, rng))  # the pot bench
    for x, y, z, s in ((-6.0, PY1 - 0.7, 0.8, 1.0), (-5.45, PY1 - 0.68, 0.8, 0.9), (-6.3, -6.3, 0.06, 1.25), (-6.3, -5.3, 0.06, 1.1),
                       (-5.4, -6.3, 0.06, 1.2), (-4.5, -6.35, 0.06, 1.0), (-5.6, -5.5, 0.06, 1.15)):
        M = Matrix.Translation((x, y, z)) @ Matrix.Scale(s, 4)
        put(k, lathe([(0.2, 0.0), (0.3, 0.38), (0.28, 0.6), (0.23, 0.62), (0.21, 0.5)], 8, M), jit(mix(P.sand, P.oldlime, 0.4), rng), soft=M @ Vector((0, 0, 0.3)))
    found(k, 1.8)
    return dict(body_m=[2 * R0, 2 * R0], ridge_m=H, opening_m=3.2)




# ---------------------------------------------------------------------------------------------
# 3. The Ladder glasshouse


def gen_glasshouse(k, rng, lot):
    """A lean-to glasshouse against a whitewashed terrace wall: basalt dwarf walls, a timber
    frame in flaking pale paint, 1.0 m bays of small aqua panes, a roof falling from 3.2 to
    1.9 m. A fifth of the panes are not original (boards, odd glass, holes), more of them at the
    west end where the storm came in. Two vents stand open, and the door at the sheltered east
    end. Along the front: a kelp heap and fork, a cold frame, a rain butt under the downpipe."""
    wear = lot["wear"]
    state = "sound" if wear["repair"] >= 0.85 else "patched" if wear["repair"] >= 0.3 else "broken"
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
    sh = lot["seed"] % 9  # where the storm's holes fell along this house: its own, from its seed
    holes = [[roof[((p_.i + sh) % 24, p_.j)] for p_ in hole if p_.where == "roof" and ((p_.i + sh) % 24, p_.j) in roof] or [front[((p_.i + sh) % 24, p_.j)] for p_ in hole] for hole in holes]
    if state == "sound":  # kept whole: one pane out, waiting for glass
        holes = [[roof[((3 + sh) % 24, 5)]]]
    elif state == "broken":  # last autumn's storm came in from the south-west and took the west half
        holes = [[roof[(i, j)] for i in range(0, 9) for j in range(2, 8) if nz(i * 0.9, j * 0.9, lot["seed"] * 0.01) > -0.25 and (i, j) in roof],
                 [roof[(i, j)] for i in range(10, 15) for j in range(3, 7) if nz(i * 1.1, j * 1.1, lot["seed"] * 0.01 + 5) > 0.1 and (i, j) in roof],
                 [front[(i, j)] for i in range(1, 8) for j in (1, 2) if nz(i * 1.3, j, lot["seed"] * 0.01 + 9) > -0.1], [roof[(19, 5)], roof[(20, 5)]]]
        holes = [h for h in holes if h]
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
    # The share that is boarded or odd glass follows the plan's `repair`: sound, patched, broken.
    n_board, n_odd = {"sound": (round(0.02 * T), int(0.04 * T)), "patched": (round(0.105 * T), int(0.075 * T)), "broken": (round(0.13 * T), int(0.05 * T))}[state]
    for p_ in order[:n_board]:
        p_.state = "board"
    for p_ in rng.sample(order[n_board:], n_odd):
        p_.state = "odd"
    lit, dim, plain = [], [], []
    for p_ in panes:
        if p_.state == "gone":
            continue
        c = jit(P.aqua, rng, 0.025)
        if p_.state == "board":
            c = jit(P.tar if rng.random() < 0.25 else P.drift, rng)  # hull planks, some still tarred
        elif p_.state == "odd":
            c = jit(rng.choice([P.green, P.amber, P.smoke]), rng, 0.03)
        # A worked house's one lantern (the strip on the warm wall, below) lights the panes near it:
        # all of them within LANTERN's core, fewer and dimmer out to its reach, none beyond. A
        # broken house is not worked and has no light.
        pc = sum((Vector(v) for v in p_.q), Vector()) / 4
        d = (pc - Vector((min(3.1, max(1.9, pc.x)), YW, 2.6))).length
        core, reach = LANTERN["core_m"], LANTERN["reach_m"]
        catch = 0.0 if state == "broken" or p_.state not in ("glass", "odd") or d >= reach else 1.0 if d <= core else (reach - d) / max(reach - core, 1e-6)
        took = catch >= 1.0 or (catch > 0.0 and 0.5 + 0.5 * nz(pc.x * 2.3, pc.y * 2.3 + pc.z * 2.3, lot["seed"] * 0.01) < catch)
        (lit if took and d <= core else dim if took else plain).append((p_.q if p_.where != "roof" else oriented(p_.q, N), c))
    raw(k, plain, two=True)
    raw(k, lit, glow="Glow", two=True)
    raw(k, dim, glow="GlowDim", two=True)

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
    # A broken house is not worked, so nobody lights it.
    lx0, lx1, lz = 1.9, 3.1, 2.6
    raw(k, [([Vector((lx0, YW - 0.07, lz)), Vector((lx1, YW - 0.07, lz)), Vector((lx1, YW - 0.07, lz + 0.11)), Vector((lx0, YW - 0.07, lz + 0.11))], P.amber),
            ([Vector((lx0, YW, lz)), Vector((lx1, YW, lz)), Vector((lx1, YW - 0.07, lz)), Vector((lx0, YW - 0.07, lz))], P.amber)], glow=None if state == "broken" else "Glow")
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
    return dict(state=state, lantern_core_m=LANTERN["core_m"], lantern_reach_m=LANTERN["reach_m"], lit_panes=len(lit), dim_panes=len(dim), ridge_m=3.2, body_m=[12.0, round(2.25 - YFR, 2)], strip_m=round(YFR - YS, 2), bays=12, panes=T, boarded=count["board"], odd_glass=count["odd"], missing=count["gone"], holes=len(holes),
                not_original_share=round((count["board"] + count["odd"] + count["gone"]) / T, 3), odd_share=round(count["odd"] / T, 3))




# ---------------------------------------------------------------------------------------------
# 4. The Strand set


def gen_net_rack(k, rng, lot=None):
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


def gen_barrels(k, rng, lot=None):
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


def gen_creels(k, rng, lot=None):
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


def gen_bollard(k, rng, lot=None):
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


def gen_quay_lamp(k, rng, lot=None):
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


def gen_boat(k, rng, lot=None):
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


def gen_peat_stack(k, rng, lot=None):
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
    NUc, NVc = 8, 6
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
            put(k, sphere(q - Z * 0.07, 0.085, 0, squash=0.85), jit(P.pale, rng), soft=q - Z * 0.07)
    for x, y, a in ((0.82, -0.36, 0.3), (0.8, 0.26, 1.2)):  # loose turves at the working end
        put(k, moved(box((-0.18, -0.07, 0.0), (0.18, 0.07, 0.11)), Matrix.Translation((x, y, 0)) @ Matrix.Rotation(a, 4, "Z")), jit(P.peat, rng, 0.04))
    fit(k, 2.0, 1.2, 1.4)
    found(k, 0.4)


def gen_floats(k, rng, lot=None):
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
# The plan's frame

FACING = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}
WIND_FROM = 225.0  # the south-westerly


class Env:
    """A lot's own compass: its front (-Y) looks along the plan's `facing`, so a compass bearing
    (0 north, 90 east) lies at an azimuth of facing - bearing from the front towards +X."""

    def __init__(self, lot):
        f = lot["facing"]
        self.F = FACING[f] if isinstance(f, str) else float(f)
        self.sw = self.vec(WIND_FROM)
        self.ne = -self.sw

    def vec(self, bearing):
        a = rad(self.F - bearing)
        return Vector((sin(a), -cos(a), 0.0))

    def weather(self, n):
        """How squarely a face with outward normal n meets the south-westerly: 0 to 1."""
        return max(0.0, Vector(n).normalized().dot(self.sw))


def masonry(k, rng, pt, n, a0, a1, z0, z1, col, shade=None, course=0.36, cut=(0.7, 1.3)):
    """Coursed stone drawn one quad a stone, in broken bond. pt(a, z) is a point of the face
    and n its outward normal; shade(a, z, colour) lays the wear of that place over a stone."""
    rows = max(1, round((z1 - z0) / course))
    polys = []
    for i in range(rows):
        za, zb = z0 + (z1 - z0) * i / rows, z0 + (z1 - z0) * (i + 1) / rows
        a = a0 - (rng.uniform(0.25, 0.6) if i % 2 else 0.0)
        while a < a1 - 1e-6:
            b = a + rng.uniform(*cut)
            b = a1 if a1 - b < 0.3 else b
            lo, hi = max(a, a0), min(b, a1)
            c = jit(col, rng, 0.03)
            if shade is not None:
                c = shade((lo + hi) / 2, (za + zb) / 2, c)
            polys.append((oriented([pt(lo, za), pt(hi, za), pt(hi, zb), pt(lo, zb)], n), c))
            a = b
    raw(k, polys)


def coping(k, rng, p0, p1, w, h, col=None, stone=1.1, across=None, skip=()):
    """A course of capping stones from p0 to p1 (the middle of its bed), w wide and h high."""
    p0, p1 = Vector(p0), Vector(p1)
    L = (p1 - p0).length
    t = (p1 - p0) / L
    s = Vector(across) if across is not None else Z.cross(t)
    n = max(1, round(L / stone))
    for i in range(n):
        if i in skip:
            continue
        a, b = L * i / n + 0.012, L * (i + 1) / n - 0.012
        put(k, lbox(Vector((a, -w / 2, 0.0)), Vector((b, w / 2, h * rng.uniform(0.94, 1.0))), fn=lambda q: p0 + t * q.x + s * q.y + Z * q.z, bevel=0.02, open_bottom=True), jit(col if col is not None else P.pale, rng, 0.025))


def tide(c, z, water, band, salt, x=0.0):
    """The tide line on a wall that stands in the sea: dark below the water, a green band up to
    `band` above it, then a pale line of salt."""
    d = z - water
    if d < 0.0:
        return mix(c, P.tar, 0.45)
    edge = band * (0.85 + 0.15 * nz(x * 0.6, 1.7))
    if d < edge:
        return mix(c, P.kelp, 0.62 * salt * (1 - 0.35 * d / edge))
    if d < edge + 0.28:
        return mix(c, P.lime, 0.4 * salt)
    return c


def bollard_at(k, rng, at, h=1.1, salt=1.0):
    """A cast-iron ship's bollard, 1.1 m high: far too big for a fishing boat."""
    M = Matrix.Translation(Vector(at))
    prof = [(0.3, 0.0), (0.3, 0.07), (0.2, 0.12), (0.17, 0.62 * h), (0.21, 0.72 * h), (0.29, 0.8 * h), (0.3, 0.9 * h), (0.24, h), (0.1, h + 0.02)]
    base = Vector(at)

    def col(co, n):
        z = co.z - base.z
        r = 0.25 + 0.45 * salt * max(0.0, nz(co.x * 6, co.y * 6, z * 3)) + 0.4 * max(0.0, 1 - z / 0.3)
        return mix(mix(P.iron, P.rust, min(0.85, r)), P.pale, 0.35 * max(0.0, 1 - abs(z - 0.5 * h) / 0.12))  # the rope's polish
    put(k, lathe(prof, 10, M), col, soft=M @ Vector((0, 0, h / 2)))


# ---------------------------------------------------------------------------------------------
# Ground and structure: retaining walls, the wynds' flights, the quay, the mole, plot walls


def gen_wall(k, rng, lot):
    """A length of retaining wall under a drop: battered basalt in broken courses, a coping that
    stands 0.4 m above the upper level (a wall to sit on), a pier where it meets a flight. Wear
    by its place: salt bloom low on the Strand's walls, lichen where it faces the wind, soot
    near the Cone, damp green under its weep holes."""
    L, D = lot["size"]
    fall, cop, w, env = lot["fall_m"], lot["coping_m"], lot["wear"], Env(lot)
    exposed = env.weather(-Y) * (0.5 + w["wind"])
    batter = 0.04

    def pt(a, z):
        return Vector((a, -D / 2 + batter * z, z))
    weeps = [(-L / 2 + L * (i + 0.5) / max(1, round(L / 4)), 0.5 + 0.25 * (i % 2)) for i in range(max(1, round(L / 4)))]

    def shade(a, z, c):
        if w["soot"] > 0.05:
            c = mix(c, P.tar, 0.45 * w["soot"])
        if z < 1.1 and w["salt"] > 0.05 and nz(a * 0.9, z * 2.2, 4.0) > 0.25 - 0.3 * w["salt"]:
            c = mix(c, P.pale, 0.55 * w["salt"])
        if z > fall * 0.45 and nz(a * 0.55, z * 0.8, 9.0 + lot["seed"] * 0.01) > 0.62 - 0.5 * exposed:
            c = mix(c, P.lichen, 0.14)
        for wa, wz in weeps:
            if abs(a - wa) < 0.3 and z < wz:
                c = mix(c, P.kelp, 0.22)
        return c
    masonry(k, rng, pt, -Y, -L / 2, L / 2, -0.25, fall, P.basalt, shade)
    raw(k, [([pt(a - 0.07, z), pt(a + 0.07, z), pt(a + 0.07, z + 0.1), pt(a - 0.07, z + 0.1)], P.tar) for a, z in weeps])
    raw(k, [([Vector((-L / 2, -D / 2 + batter * fall, fall)), Vector((L / 2, -D / 2 + batter * fall, fall)), Vector((L / 2, D / 2, fall)), Vector((-L / 2, D / 2, fall))], jit(P.basalt, rng))])
    yc = (-D / 2 + batter * fall + D / 2) / 2
    coping(k, rng, (-L / 2, yc, fall), (L / 2, yc, fall), D - batter * fall + 0.03, cop, stone=1.15)
    for e, pier in zip((-1, 1), lot["ends"]):
        x = e * (L / 2 - 0.3)
        if pier:  # the pier at a flight's side: pale quoins
            put(k, box((x - 0.3, -D / 2 - 0.0, -0.25), (x + 0.3, D / 2, fall + cop + 0.06), bevel=0.02), lambda co, n, c=jit(P.pale, rng, 0.02), d=jit(P.basalt, rng): c if int(co.z / 0.45) % 2 == 0 else d)
        raw(k, [(oriented([Vector((e * L / 2, -D / 2, -0.25)), Vector((e * L / 2, D / 2, -0.25)), Vector((e * L / 2, D / 2, fall)), Vector((e * L / 2, -D / 2 + batter * fall, fall))], X * e), jit(P.basalt, rng))])
    return dict(ridge_m=fall + cop, fall_m=fall)


def gen_stairs(k, rng, lot):
    """A flight of a wynd: basalt treads of 0.18 m between two cheek walls, the treads the game
    walks on (round(rise / 0.18) of them over the flight's run), worn pale down the middle."""
    W, run = lot["size"]
    rise, N, w, env = lot["rise_m"], lot["treads"], lot["wear"], Env(lot)
    g, r = run / N, rise / N
    CH = 0.28  # a cheek wall's width, inside the flight's 3 m
    polys = []
    for i in range(N):
        y0, y1, z = -run / 2 + i * g, -run / 2 + (i + 1) * g, (i + 1) * r
        stone = jit(P.basalt, rng, 0.03)
        worn = mix(stone, P.pale, 0.75)
        if z < 1.2 and w["salt"] > 0.3:
            stone = mix(stone, P.pale, 0.3 * w["salt"])
        polys.append(([Vector((-W / 2 + CH, y0, z - r)), Vector((W / 2 - CH, y0, z - r)), Vector((W / 2 - CH, y0, z)), Vector((-W / 2 + CH, y0, z))], mix(stone, P.tar, 0.25)))
        for x0, x1, c in ((-W / 2 + CH, -0.55, stone), (-0.55, 0.55, worn), (0.55, W / 2 - CH, stone)):  # feet keep to the middle
            dip = 0.012 if c is worn else 0.0
            polys.append(([Vector((x0, y0, z - dip)), Vector((x1, y0, z - dip)), Vector((x1, y1 + 0.02, z - dip)), Vector((x0, y1 + 0.02, z - dip))], jit(c, rng, 0.015)))
    raw(k, polys)
    for e in (-1, 1):
        x0, x1 = (W / 2 - CH, W / 2) if e > 0 else (-W / 2, -W / 2 + CH)
        top = [(-run / 2, 0.0), (-run / 2, r + 0.22), (run / 2, rise + 0.22), (run / 2, -0.2), (-run / 2, -0.2)]
        lich = env.weather(X * e) * (0.4 + w["wind"])
        put(k, prism(top, x0, x1, lambda a, s, z: Vector((a, s, z))),
            lambda co, n, c=jit(P.basalt, rng, 0.02), lich=lich: mix(c, P.lichen, 0.35) if lich > 0.2 and nz(co.y * 0.9, co.z * 0.9, 2.0 + e) > 0.7 - 0.5 * lich else mix(c, P.pale, 0.5) if n.z > 0.5 else c)
        for j in range(max(2, round(run / 1.2))):  # the cheek's capping, stepping up with the flight
            n_ = max(2, round(run / 1.2))
            ya, yb = -run / 2 + run * j / n_, -run / 2 + run * (j + 1) / n_
            za = r + 0.22 + (rise - r) * (j + 1) / n_
            put(k, box((x0 - 0.0, ya + 0.01, za - 0.14), (x1 + 0.0, yb - 0.01, za + 0.03), bevel=0.015), jit(P.pale, rng, 0.025))
    return dict(ridge_m=rise + 0.25, treads=N, tread_rise_m=round(r, 4), tread_going_m=round(g, 4))


def sea_face(k, rng, lot, p0, p1, n, depth=3.2):
    """A sea wall's face from p0 to p1 (at the quay's level), looking along n: big basalt blocks
    with the tide line on them."""
    p0, p1 = Vector(p0), Vector(p1)
    L = (p1 - p0).length
    t = (p1 - p0) / L
    water, band, salt = -lot["water_m"], lot["tide_m"], lot["wear"]["salt"]
    masonry(k, rng, lambda a, z: p0 + t * a + Z * z, n, 0.0, L, -depth, 0.0, P.basalt, lambda a, z, c: tide(c, z, water, band, salt, a + p0.x + p0.y), course=0.45, cut=(0.9, 1.6))


def iron_ladder(k, rng, at, n, down=2.5):
    """Iron rungs let into a sea wall, rusting, with the stain they leave."""
    at, n = Vector(at), Vector(n)
    s = Z.cross(n)
    rust = mix(P.iron, P.rust, 0.7)
    for e in (-1, 1):
        put(k, beam(at + s * e * 0.22 + n * 0.06 + Z * 0.25, at + s * e * 0.22 + n * 0.06 - Z * down, 0.04, 0.04, up=n), rust)
    for i in range(int(down / 0.3)):
        put(k, beam(at - s * 0.22 + n * 0.06 - Z * (0.15 + 0.3 * i), at + s * 0.22 + n * 0.06 - Z * (0.15 + 0.3 * i), 0.03, 0.03), rust)
    raw(k, [(oriented([at + s * (e * 0.22 - 0.05) + n * 0.012 - Z * 0.1, at + s * (e * 0.22 + 0.05) + n * 0.012 - Z * 0.1, at + s * (e * 0.22 + 0.09) + n * 0.012 - Z * 1.7,
                       at + s * (e * 0.22 - 0.09) + n * 0.012 - Z * 1.7], n), mix(P.basalt, P.rust, 0.45)) for e in (-1, 1)])


def mooring_ring(k, rng, at, n):
    at, n = Vector(at), Vector(n)
    s = Z.cross(n)
    put(k, tube([at + n * 0.05 + (s * cos(i / 8 * TAU) + Z * sin(i / 8 * TAU)) * 0.16 - Z * 0.16 for i in range(9)], 0.022, 4, caps=False), mix(P.iron, P.rust, 0.65), closed=False)
    raw(k, [(oriented([at + s * -0.1 + n * 0.012 - Z * 0.3, at + s * 0.1 + n * 0.012 - Z * 0.3, at + s * 0.14 + n * 0.012 - Z * 1.3, at + s * -0.14 + n * 0.012 - Z * 1.3], n), mix(P.basalt, P.rust, 0.4))])


def gen_quay(k, rng, lot):
    """A length of the ship-day quay's edge: coping stones a metre wide, raised a hand above the
    flags, over a sea wall that stands 0.5 m out over the water with the tide line on it. Every
    third length has an iron ladder, the ones between a mooring ring."""
    L, D = lot["size"]
    sea_face(k, rng, lot, (-L / 2, -D / 2, 0.0), (L / 2, -D / 2, 0.0), -Y)
    for e in (-1, 1):
        raw(k, [(oriented([Vector((e * L / 2, -D / 2, -3.2)), Vector((e * L / 2, -D / 2 + 0.6, -3.2)), Vector((e * L / 2, -D / 2 + 0.6, 0.0)), Vector((e * L / 2, -D / 2, 0.0))], X * e), jit(P.basalt, rng))])
    # The edge stones, a hand above the flags, and a second course of flags behind them.
    coping(k, rng, (-L / 2, -D / 2 + 0.5, 0.0), (L / 2, -D / 2 + 0.5, 0.0), 1.0, 0.12, stone=1.33, across=Y)
    coping(k, rng, (-L / 2, D / 2 - 0.5, 0.0), (L / 2, D / 2 - 0.5, 0.0), 1.0, 0.07, col=mix(P.basalt, P.pale, 0.55), stone=0.9, across=Y)
    if lot.get("ladder"):
        iron_ladder(k, rng, (0.0, -D / 2, 0.0), -Y)
    if lot.get("ring"):
        mooring_ring(k, rng, (L * 0.2, -D / 2, -0.25), -Y)
    return dict(ridge_m=0.12)


def wave_wall(k, rng, env, lot, p0, p1, out, h=1.1, th=0.5):
    """The mole's wave wall on its open side: basalt 0.5 m thick with a pale capping, lichen and
    bloom on the face the sea strikes."""
    p0, p1, out = Vector(p0), Vector(p1), Vector(out)
    L = (p1 - p0).length
    t = (p1 - p0) / L
    w = lot["wear"]
    for side in (1, -1):
        o = p0 + out * (side * th / 2)
        n = out * side
        ex = env.weather(n)
        masonry(k, rng, lambda a, z, o=o: o + t * a + Z * z, n, 0.0, L, 0.1, h, P.basalt,
                lambda a, z, c, ex=ex, side=side: mix(c, P.lichen, 0.38) if nz(a * 0.7, z * 2.0, 3.0 + side) > 0.55 - 0.4 * ex else mix(c, P.pale, 0.5 * w["salt"]) if nz(a * 0.5, z * 1.5, 8.0) > 0.35 else c, course=0.34)
    coping(k, rng, p0 + Z * h, p1 + Z * h, th + 0.08, 0.12, across=out)
    for q in (p0, p1):
        raw(k, [(oriented([q - out * th / 2 + Z * 0.1, q + out * th / 2 + Z * 0.1, q + out * th / 2 + Z * h, q - out * th / 2 + Z * h], t if q is p1 else -t), jit(P.basalt, rng))])


def iron_rail(k, rng, pts, h=1.0, gone=()):
    """An iron rail on posts along pts; spans in `gone` went in the storm: bent stubs are left."""
    pts = [Vector(q) for q in pts]
    rust = lambda: mix(P.iron, P.rust, rng.uniform(0.45, 0.8))  # noqa: E731
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        if i in gone:
            put(k, beam(a, a + Z * 0.5 + (b - a).normalized() * 0.25, 0.05, 0.05), rust())
            continue
        put(k, beam(a, a + Z * h, 0.05, 0.05), rust())
        put(k, beam(a + Z * h, b + Z * h, 0.045, 0.045), rust())
        put(k, beam(a + Z * h * 0.5, b + Z * h * 0.5, 0.03, 0.03), rust())
    if len(pts) - 2 not in gone:
        put(k, beam(pts[-1], pts[-1] + Z * h, 0.05, 0.05), rust())


def gen_mole(k, rng, lot):
    """A piece of the ship-day mole: sea walls on both sides with the tide line, a wave wall on
    the open (east) side, oversized bollards on the harbour (west) side. The root carries the
    lamp house; the tip has an iron rail round it whose south end went in last autumn's storm."""
    W, D = lot["size"]
    hw, hd, env, part = W / 2, D / 2, Env(lot), lot["part"]
    edge = 0.5  # the face stands 0.5 m out from the mole's ground
    if part == "arm":
        sea_face(k, rng, lot, (-hw, -hd, 0), (-hw, hd, 0), -X)
        sea_face(k, rng, lot, (hw, -hd, 0), (hw, hd, 0), X)
        for e in (-1, 1):
            coping(k, rng, (e * (hw - 0.5), -hd, 0), (e * (hw - 0.5), hd, 0), 1.0, 0.12, stone=1.33, across=X)
            coping(k, rng, (e * (hw - 1.5), -hd, 0), (e * (hw - 1.5), hd, 0), 1.0, 0.07, col=mix(P.basalt, P.pale, 0.55), stone=0.9, across=X)
        wave_wall(k, rng, env, lot, (hw - 0.32, -hd, 0.1), (hw - 0.32, hd, 0.1), X)
        bollard_at(k, rng, (-hw + 0.55, 0.0, 0.12))
        mooring_ring(k, rng, (-hw, hd * 0.5, -0.25), -X)
        if lot["wear"]["repair"] < 0.35:
            iron_ladder(k, rng, (-hw, -hd * 0.5, 0.0), -X)
        return dict(ridge_m=1.2)
    ax0, ax1 = lot["arm_x"][0] - lot["at"][0] - edge, lot["arm_x"][1] - lot["at"][0] + edge  # where the arm joins, in this frame
    if part == "root":
        # West, the two south shoulders, east. The north side is the quay.
        runs = [((-hw, hd - edge, 0), (-hw, -hd, 0), -X), ((-hw, -hd, 0), (ax0, -hd, 0), -Y), ((ax1, -hd, 0), (hw, -hd, 0), -Y), ((hw, -hd, 0), (hw, hd - edge, 0), X)]
        cops = [((-hw + 0.5, hd - edge, 0), (-hw + 0.5, -hd + 1.0, 0), X), ((-hw, -hd + 0.5, 0), (ax0, -hd + 0.5, 0), Y), ((ax1, -hd + 0.5, 0), (hw, -hd + 0.5, 0), Y), ((hw - 0.5, -hd + 1.0, 0), (hw - 0.5, hd - edge, 0), X)]
        wave_wall(k, rng, env, lot, (hw - 0.32, -hd + 0.07, 0.1), (hw - 0.32, hd - edge, 0.1), X)
        wave_wall(k, rng, env, lot, (ax1 + 0.2, -hd + 0.32, 0.1), (hw - 0.57, -hd + 0.32, 0.1), -Y)
        bollard_at(k, rng, (-hw + 0.55, -hd + 1.6, 0.12))
        bollard_at(k, rng, (-hw + 0.55, hd - 4.0, 0.12))
        iron_ladder(k, rng, (-hw, 1.0, 0.0), -X)
    else:
        # The tip: north shoulders (towards the harbour), west, south, east.
        runs = [((-hw, hd, 0), (ax0, hd, 0), Y), ((ax1, hd, 0), (hw, hd, 0), Y), ((-hw, hd, 0), (-hw, -hd, 0), -X), ((-hw, -hd, 0), (hw, -hd, 0), -Y), ((hw, -hd, 0), (hw, hd, 0), X)]
        cops = [((-hw, hd - 0.5, 0), (ax0, hd - 0.5, 0), Y), ((ax1, hd - 0.5, 0), (hw, hd - 0.5, 0), Y), ((-hw + 0.5, hd - 1.0, 0), (-hw + 0.5, -hd + 1.0, 0), X),
                ((-hw, -hd + 0.5, 0), (hw, -hd + 0.5, 0), Y), ((hw - 0.5, -hd + 1.0, 0), (hw - 0.5, hd - 1.0, 0), X)]
        wave_wall(k, rng, env, lot, (hw - 0.32, -hd + 0.07, 0.1), (hw - 0.32, hd - 0.07, 0.1), X)
        # The rail: west side and south end; the south spans are gone since the storm.
        rail = [Vector((-hw + 0.25, hd - 0.3, 0.12)), Vector((-hw + 0.25, hd - 4.6, 0.12)), Vector((-hw + 0.25, -hd + 4.4, 0.12)), Vector((-hw + 0.25, -hd + 0.25, 0.12)),
                Vector((-hw + 4.4, -hd + 0.25, 0.12)), Vector((hw - 4.6, -hd + 0.25, 0.12)), Vector((hw - 0.7, -hd + 0.25, 0.12))]
        iron_rail(k, rng, rail, gone=(3, 4) if lot.get("rail_gone") == "south" else ())
        bollard_at(k, rng, (-hw + 0.8, hd - 2.4, 0.12))
        bollard_at(k, rng, (-hw + 0.8, -hd + 2.6, 0.12))
        iron_ladder(k, rng, (-hw, 0.5, 0.0), -X)
    for p0, p1, n in runs:
        sea_face(k, rng, lot, p0, p1, n)
    for p0, p1, across in cops:
        coping(k, rng, p0, p1, 1.0, 0.12, stone=1.33, across=across)
        # A second course of flags inside the edge stones, over the ground's own bank.
        p0, p1 = Vector(p0), Vector(p1)
        mid = (p0 + p1) / 2
        inn = Vector(across) * (1.0 if Vector(across).dot(-mid) > 0 else -1.0)
        t = (p1 - p0).normalized()
        coping(k, rng, p0 + inn + t * 0.5, p1 + inn - t * 0.5, 1.0, 0.07, col=mix(P.basalt, P.pale, 0.55), stone=0.9, across=across)
    return dict(ridge_m=1.2)


def gen_plot_wall(k, rng, lot):
    """Dry stone round a root plot: basalt as it came off the ground, 0.45 m thick and about a
    metre high, an uneven top, a gap with a driftwood hurdle on the side of the path."""
    W, D = lot["size"]
    hw, hd, env, w, TH = W / 2, D / 2, Env(lot), lot["wear"], 0.45
    ga = lot["gate_at"]
    sides = [((-hw, -hd), (ga - 0.55, -hd), -Y), ((ga + 0.55, -hd), (hw, -hd), -Y), ((hw, -hd), (hw, hd), X), ((hw, hd), (-hw, hd), Y), ((-hw, hd), (-hw, -hd), -X)]
    for (x0, y0), (x1, y1), n in sides:
        p0, p1 = Vector((x0, y0, 0)), Vector((x1, y1, 0))
        L = (p1 - p0).length
        t = (p1 - p0) / L
        inn = -Vector(n)
        ex = env.weather(n) * (0.4 + w["wind"])
        m = max(1, round(L / 1.15))
        for i in range(m):
            a, b = L * i / m, L * (i + 1) / m
            h = rng.uniform(0.86, 1.0)
            c, lichen = jit(rng.choice([P.basalt, P.basalt, P.pale]), rng, 0.03), rng.random() < ex
            put(k, lbox(Vector((a + 0.01, 0.0, 0.0)), Vector((b - 0.01, TH, h)), fn=lambda q, p0=p0, t=t, inn=inn: p0 + t * q.x + inn * q.y + Z * q.z, bevel=0.03, open_bottom=True),
                lambda co, nn, c=c, lichen=lichen, n=n: mix(c, P.lichen, 0.4) if lichen and nn.dot(Vector(n)) > 0.5 else mix(c, P.pale, 0.35) if nn.z > 0.5 else c)
    for i, z in enumerate((0.25, 0.55, 0.85)):  # the hurdle
        put(k, beam((ga - 0.5, -hd + 0.2, z), (ga + 0.5, -hd + 0.2, z + 0.03 * (i - 1)), 0.03, 0.09), jit(P.drift, rng))
    for e in (-1, 1):
        put(k, beam((ga + e * 0.5, -hd + 0.2, 0.0), (ga + e * 0.5, -hd + 0.2, 1.0), 0.07, 0.07), jit(P.drift, rng))
    put(k, beam((ga - 0.48, -hd + 0.17, 0.2), (ga + 0.48, -hd + 0.17, 0.9), 0.03, 0.07), jit(P.drift, rng))
    return dict(ridge_m=1.0)


def gen_fish_steps(k, rng, lot):
    """The Fish Steps: broad basalt steps going down into the harbour from the quay's edge, where
    the catch is divided each morning. The landing (the lot) is flagged in big worn slabs; the
    flight goes down south of it into the water, green below the tide line."""
    W, D = lot["size"]
    hw, hd, w = W / 2, D / 2, lot["wear"]
    water, band = -2.0, 1.2
    rng2 = random.Random(lot["seed"])
    # The landing: worn flags, a pale path down its middle where the fish are carried up.
    nx, ny = 6, 2
    put(k, box((-hw, -hd, 0.0), (hw, hd, 0.03)), mix(P.basalt, P.tar, 0.3))
    for i in range(nx):
        for j in range(ny):
            x0, x1, y0, y1 = -hw + W * i / nx, -hw + W * (i + 1) / nx, -hd + D * j / ny, -hd + D * (j + 1) / ny
            worn = abs((x0 + x1) / 2) < 1.6
            put(k, box((x0 + 0.015, y0 + 0.015, 0.0), (x1 - 0.015, y1 - 0.015, 0.05 + 0.01 * rng2.random()), bevel=0.012), jit(mix(P.basalt, P.pale, 0.8 if worn else 0.35), rng, 0.025))
    # The flight: 14 treads of 0.18 m and 0.3 m, the lowest under water.
    polys, N, g, r = [], 14, 0.3, 0.18
    for i in range(N):
        y0, z = -hd - i * g, -(i + 1) * r
        for x0, x1, mid in ((-hw, -1.4, False), (-1.4, 1.4, True), (1.4, hw, False)):
            c = jit(mix(P.basalt, P.pale, 0.6 if mid else 0.15), rng, 0.02)
            c = tide(c, z + 0.01, water, band, w["salt"], x0 + i)
            polys.append(([Vector((x0, y0 - g, z)), Vector((x1, y0 - g, z)), Vector((x1, y0, z)), Vector((x0, y0, z))], c))
            polys.append(([Vector((x0, y0, z)), Vector((x1, y0, z)), Vector((x1, y0, z + r)), Vector((x0, y0, z + r))], mix(c, P.tar, 0.3)))
    raw(k, polys)
    # Its sides, closed with stone down to the bed.
    for e in (-1, 1):
        side = [(-hd, 0.0)] + [q for i in range(N) for q in ((-hd - i * g, -(i + 1) * r), (-hd - (i + 1) * g, -(i + 1) * r))] + [(-hd - N * g, -3.2), (-hd, -3.2)]
        raw(k, [(oriented([Vector((e * hw, y, z)) for y, z in side], X * e), tide(jit(P.basalt, rng), -1.0, water, band, w["salt"]))])
    raw(k, [([Vector((-hw, -hd - N * g, -3.2)), Vector((hw, -hd - N * g, -3.2)), Vector((hw, -hd - N * g, -N * r)), Vector((-hw, -hd - N * g, -N * r))], mix(P.basalt, P.tar, 0.45))])
    # Two iron rings at the head of the steps and a mooring post worn by ropes.
    for e in (-1, 1):
        put(k, tube([(e * (hw - 0.35), -hd + 0.25, 0.0), (e * (hw - 0.35), -hd + 0.25, 0.85)], [0.11, 0.09], 8), lambda co, n, c=jit(P.drift, rng): mix(c, P.pale, 0.5) if 0.45 < co.z < 0.6 else mix(c, P.kelp, 0.3) if co.z < 0.2 else c)
    kelp(k, rng, (-hw + 0.9, hd - 0.5, 0.06), 5, 0.5)
    return dict(ridge_m=0.85)


# ---------------------------------------------------------------------------------------------
# The Rows: terraces built as rows. Each house is its own model on its own lot, but it is laid
# out with its neighbours: they share a party wall (each model carries its half), the stack on
# it (half each, as high as the taller roof needs) and the eaves' line, so the row is one roof
# that steps where a household's storeys differ. The Rows follow the slope's contours, so a
# row's floors are level; the street's steps are the wynds between the rows.

CELLS = lambda nu, nv: [(i, j) for i in range(nu) for j in range(nv)]  # noqa: E731
FINE, WIDE, BROAD = (3, 4, 0.32, 0.33), (2, 3, 0.45, 0.45), (3, 3, 0.45, 0.45)
DOOR = dict(oxblood=P.oxblood, mustard=P.mustard, sea_green=P.seagreen, chalk_blue=P.chalkblue, faded=mix(P.seagreen, P.drift, 0.55))
STOREY = dict(kiln=2.9, strand=2.6, ladder=2.7)
PITCH = rad(47)
STOOP = 0.95  # the strip before a house's wall, inside its lot: step, bench, what it keeps outside


def row_frame(lot):
    """A row building's section, from its lot: the wall lines, the floors and the roof."""
    w, d = lot["size"]
    f = NS(w=w, hw=w / 2, YP=-d / 2, YF=-d / 2 + STOOP, YB=d / 2 - 0.05, H=lot["height_m"], F=0.36)
    f.YR, f.half = (f.YF + f.YB) / 2, (f.YB - f.YF) / 2
    f.rise = f.half * math.tan(PITCH)
    f.shell = lot.get("state") == "roofless shell"
    f.zr = f.H - 0.13  # the ridge stones' bed: their top is the plan's height
    f.E = f.H if f.shell else f.zr - f.rise
    f.z1 = f.F + STOREY.get(lot.get("family"), 2.75 if lot["kind"] == "house" else 2.8)
    return f


def ridge_of(nb):
    """A neighbour's ridge bed (None: no roof there to rise above)."""
    if nb is None or nb.get("state") == "roofless shell":
        return None
    return nb["height_m"] - 0.13


def roof_top(f, y, extra=0.0):
    return f.zr + extra - abs(y - f.YR) * math.tan(PITCH)


def row_sides(k, rng, f, lot, env, lime):
    """The two side walls: half a party wall and half its stack where a neighbour stands, an end
    gable where the terrace ends. Returns the roof's span."""
    w, near = lot["wear"], lot["near"]
    span = []
    for sx, side in ((-1, "west"), (1, "east")):
        nb = near.get(side)
        xg = sx * f.hw
        th = 0.18 if nb is not None else 0.3
        xa, xb = (xg, xg + th) if sx < 0 else (xg - th, xg)
        span.append(xg - sx * th)
        if f.shell:
            top = [(f.YF + 0.01, 0.0), (f.YB - 0.01, 0.0), (f.YB - 0.01, f.H - 0.5), (f.YR + 1.0, f.H), (f.YR - 0.6, f.H - 0.2), (f.YF + 0.01, f.H - 0.7)]
            put(k, prism(top, xa, xb, lambda a, s, z: Vector((a, s, z))), lambda co, n, c=jit(P.basalt, rng, 0.02), l=jit(P.oldlime, rng, 0.02): l if co.z > f.z1 + 0.3 and nz(co.y * 0.8, co.z * 0.8, xg) > -0.1 else c)
        else:
            put(k, prism([(f.YF + 0.01, 0.0), (f.YB - 0.01, 0.0), (f.YB - 0.01, f.z1), (f.YF + 0.01, f.z1)], xa, xb, lambda a, s, z: Vector((a, s, z))), jit(P.basalt, rng, 0.02))
            put(k, prism([(f.YF + 0.01, f.z1), (f.YB - 0.01, f.z1), (f.YB - 0.01, roof_top(f, f.YB, 0.14)), (f.YR, f.zr + 0.14), (f.YF + 0.01, roof_top(f, f.YF, 0.14))], xa, xb, lambda a, s, z: Vector((a, s, z))), lime)
            # The raised skew: flat stones up each slope, lichened on the weather side.
            xm, sw = (xa + xb) / 2, th + 0.04
            for sgn in (-1, 1):
                a = Vector((xm, f.YR, f.zr + 0.2))
                b = Vector((xm, f.YR + sgn * (f.half - 0.01), f.zr + 0.2 - (f.half - 0.01) * math.tan(PITCH)))
                put(k, beam(a, b, sw, 0.13), lambda co, n, c=jit(P.pale, rng, 0.02), xg=xg: mix(c, P.lichen, 0.45 * w["wind"] * max(0.0, nz(co.y * 1.4, co.z * 1.4, xg)) * (2.0 if co.y < f.YR else 0.6)))
        if nb is not None:
            # Half the stack on the party wall: sooted brick, as high as the taller roof needs.
            tops = [z for z in (None if f.shell else f.zr, ridge_of(nb)) if z is not None]
            if not tops:
                continue
            zc, z0 = max(tops) + 1.35, min(tops) - 0.6
            x0, x1 = (xg, xg + 0.47) if sx < 0 else (xg - 0.47, xg)
            put(k, box((x0, f.YR - 0.3, z0), (x1, f.YR + 0.3, zc)), lambda co, n, c=jit(P.brick, rng, 0.02), zc=zc: mix(c, P.tar, 0.5 * max(0.0, (co.z - zc + 0.9) / 0.9)))
            put(k, box((x0, f.YR - 0.36, zc), (x1, f.YR + 0.36, zc + 0.09)), jit(P.pale, rng, 0.02))
            px = xg - sx * 0.26
            if w["empty"] >= 1.0:  # no hearth burns: the flue is capped with a slate
                put(k, box((px - 0.2, f.YR - 0.2, zc + 0.09), (px + 0.2, f.YR + 0.2, zc + 0.12)), jit(P.newslate, rng))
            else:
                M = Matrix.Translation((px, f.YR, zc + 0.09))
                ph = 0.45 + 0.09 * min(3, lot.get("people", 1) // 3)  # a fuller house, a taller pot
                put(k, lathe([(0.13, 0.0), (0.15, 0.08), (0.11, ph - 0.04), (0.13, ph), (0.09, ph), (0.09, ph - 0.1)], 6, M), lambda co, n, c=jit(P.newbrick, rng, 0.03), z=zc + ph: mix(c, P.tar, 0.8 * max(0.0, (co.z - z + 0.1) / 0.2)))
        elif not f.shell:
            # An end gable: a string course, an attic light; the west one takes the weather.
            u = -Y if sx < 0 else Y
            fg = Face((xg, f.YR, 0), u, f.YB - f.YF)
            put(k, fg.box(-f.half, f.half, f.z1 - 0.09, f.z1 + 0.05, 0.0, 0.05, back=False), jit(P.pale, rng, 0.02))
            lit = lot.get("people", 0) >= 5
            window(k, rng, fg, 0.0, f.E + 0.75, (2, 2, 0.36, 0.36), glazing(rng, P.smoke, P.aqua, 1, CELLS(2, 2)), lit=lit, recess=-0.02, sill=None)
            put(k, fg.box(-0.46, 0.46, f.E + 0.63, f.E + 0.75, 0.0, 0.07), jit(P.pale, rng))
            ex = env.weather(X * sx) * (0.5 + w["wind"])
            polys = []
            for _ in range(round(16 * ex)):  # flaked lime, then lichen in colonies
                a, z, r = rng.uniform(-f.half + 0.4, f.half - 0.4), f.z1 + 0.3 + (f.E - f.z1) * rng.random() ** 1.6, rng.uniform(0.2, 0.5)
                if abs(a) < 0.9 and z > f.E:
                    continue
                polys.append((blotch(fg, a, z, r, rng, n=10, tall=rng.uniform(0.45, 0.8)), jit(mix(P.oldlime, P.basalt, 0.2), rng, 0.02)))
            for _ in range(round(14 * ex)):
                a, z = rng.uniform(-f.half + 0.3, f.half - 0.3), rng.uniform(0.6, f.E)
                polys.append((blotch(fg, a, z, rng.uniform(0.07, 0.2), rng, n=8, tall=rng.uniform(0.6, 1.5)), mix(P.basalt if z < f.z1 else lime, P.lichen, 0.5)))
            for _ in range(round(5 * w["salt"])):
                polys.append((blotch(fg, rng.uniform(-f.half + 0.4, f.half - 0.4), rng.uniform(0.2, 1.0), rng.uniform(0.25, 0.45), rng, tall=0.6), mix(P.basalt, P.pale, 0.7)))
            raw(k, polys)
    return span[0], span[1]


def row_roof(k, rng, f, lot, a0, a1, sag_m, patch, gone_at=(), lights=0, lit_light=False):
    """Both slopes in the house's own state of repair, the ridge stones, the gutter and pipe."""
    w = lot["wear"]
    c_p, s_p = cos(PITCH), sin(PITCH)
    S = (f.half + 0.01) / c_p
    empty = w["empty"] >= 1.0
    west = lot["near"].get("west") is None  # open to the wind at the terrace's west end

    def sag(a):
        return sag_m * (1 - ((2 * a - a0 - a1) / (a1 - a0)) ** 2)
    for sgn in (-1, 1):
        D, N = Vector((0, sgn * c_p, -s_p)), Vector((0, sgn * s_p, c_p))

        def fn(a, t, hh, D=D, N=N):
            return Vector((a, f.YR, f.zr - sag(a))) + D * t + N * hh

        def state(a, t, sgn=sgn):
            if sgn < 0 and any(abs(a - ga) < 0.45 and abs(t - gt) < 0.24 for ga, gt in gone_at):
                return None  # slates the storm took, never put back
            c = jit(P.slate, rng, 0.04)
            for xs in (a0, a1):  # soot settles downwind (north-east) of a stack
                lee = max(0.0, 1 - math.hypot(a - xs - 0.4, (t - 0.8) * 0.8) / 1.6) if sgn > 0 and not empty else 0.0
                c = mix(c, P.tar, 0.55 * lee)
            if w["soot"] > 0.05:
                c = mix(c, P.tar, 0.6 * w["soot"])
            exposed = w["wind"] * (1.0 if west else 0.6) * (1.0 if sgn < 0 else 0.35)
            if nz(a * 0.7 + lot["at"][0] * 0.7, t * 0.9, 3.0 + sgn) + rng.uniform(-0.25, 0.25) > 0.62 - 0.5 * exposed and t > 1.2:
                c = mix(c, P.lichen, rng.uniform(0.1, 0.24))
            if rng.random() < patch:
                c = jit(P.newslate, rng, 0.04)  # a repair in whatever slate there was
            return c
        slates(k, rng, fn, a0, a1, S, state)
        if sgn < 0:  # iron gutter and downpipe; rust runs under them where the air is salt
            ze = f.zr - S * s_p
            ga1 = a1 - 2.0 if empty else a1
            put(k, box((a0, f.YF - 0.36, ze - 0.13), (ga1, f.YF - 0.25, ze - 0.02)), mix(P.iron, P.rust, 0.3 + 0.4 * w["salt"] * rng.random()))
            px = a1 - 0.24
            if empty:  # the gutter's end has dropped and the pipe is gone
                put(k, beam((ga1, f.YF - 0.3, ze - 0.08), (ga1 + 1.0, f.YF - 0.3, ze - 0.7), 0.11, 0.11), mix(P.iron, P.rust, 0.8))
            else:
                put(k, beam((px, f.YF - 0.3, ze - 0.1), (px, f.YF - 0.07, ze - 0.55), 0.08, 0.08), P.iron)
                put(k, box((px - 0.045, f.YF - 0.11, 0.25), (px + 0.045, f.YF - 0.02, ze - 0.5)), mix(P.iron, P.rust, 0.25 + 0.5 * w["salt"] * rng.random()))
    a = a0
    gap = a0 + (a1 - a0) * 0.55 if empty else None
    while a < a1 - 0.2:  # ridge stones; one is gone from an empty house
        b = min(a1, a + rng.uniform(0.6, 0.85))
        if gap is None or not (a <= gap < b):
            put(k, box((a + 0.015, f.YR - 0.2, f.zr - sag((a + b) / 2) - 0.03), (b - 0.015, f.YR + 0.2, f.zr - sag((a + b) / 2) + 0.13), bevel=0.04), jit(P.basalt, rng, 0.03))
        a = b
    for li in range(lights):  # cast-iron rooflights: more of them where more people sleep
        lx = a0 + (a1 - a0) * (li + 1) / (lights + 1)
        D, N = Vector((0, -c_p, -s_p)), Vector((0, -s_p, c_p))
        o = Vector((lx - 0.36, f.YR, f.zr - sag(lx))) + D * 2.45
        pt = lambda u, v, ww, o=o, D=D, N=N: o + X * u - D * v + N * (0.09 + ww)  # noqa: E731
        put(k, lbox(Vector((-0.06, -0.06, 0.0)), Vector((0.78, 0.78, 0.085)), fn=lambda q, o=o, D=D, N=N: o + X * q.x - D * q.y + N * q.z), P.iron)
        pane_grid(k, rng, pt, 2, 2, 0.36, 0.36, glazing(rng, P.smoke, P.aqua, 1, CELLS(2, 2)), back=P.iron, glow="Glow" if lit_light and li == 0 else None)


def flakes(k, rng, f, lime, face, a0, a1, z0, z1, n, holes=()):
    """Limewash flaked off by the wind: old lime shows, then the stone."""
    polys = []
    for _ in range(n):
        a, z, r = rng.uniform(a0 + 0.35, a1 - 0.35), z0 + 0.3 + (z1 - z0 - 0.6) * rng.random() ** 1.8, rng.uniform(0.2, 0.55)
        if any(h0 - r < a < h1 + r and zb - r < z < zt + r for h0, h1, zb, zt in holes):
            continue
        tall = rng.uniform(0.45, 0.8)
        polys.append((blotch(face, a, z, r, rng, n=10, tall=tall), jit(P.oldlime if lime is P.lime else mix(P.oldlime, P.basalt, 0.22), rng, 0.02)))
        if r > 0.38:
            polys.append((blotch(face, a + rng.uniform(-0.1, 0.1), z - 0.04, r * 0.45, rng, w=0.02, n=7, tall=tall), jit(mix(P.oldlime, P.basalt, 0.4), rng, 0.02)))
    raw(k, polys)


def pavement(k, rng, f, w):
    """The strip before the wall: flags at the street's level and a kerb."""
    n = max(2, round(f.w / 1.1))
    for i in range(n):
        x0, x1 = -f.hw + f.w * i / n, -f.hw + f.w * (i + 1) / n
        put(k, box((x0 + 0.01, f.YP + 0.22, 0.0), (x1 - 0.01, f.YF, 0.04), bevel=0.008), jit(mix(P.basalt, P.pale, 0.55), rng, 0.03))
    blocks(k, rng, Face((0, f.YP, 0), X, f.w), -f.hw, f.hw, 0.0, 0.07, 0.22, P.pale, P.basalt, 0.3, course=0.07, cut=(0.6, 1.0))


def keepsake(k, rng, f, lot, dx, gx, gz):
    """What the household keeps outside (the plan's `keepsake`, from the cast): the street tells
    you who lives here. dx: the door's middle, gx: the ground window's, gz: its sill."""
    h = lot.get("household")
    y0 = f.YF  # the wall's face
    side = 1 if gx > dx else -1  # things stand on the window's side of the door
    bx = dx + side * 1.0
    if h == "pontil":  # a sill of cullet: one piece of every colour Ode has kept, the Rows' one cobalt among them
        for i, c in enumerate((P.green, P.amber, P.aqua, P.cobalt, P.smoke, P.amber, P.green, P.aqua)):
            x = gx - 0.42 + i * 0.12
            put(k, box((x - 0.04, y0 - 0.1, gz), (x + 0.04, y0 - 0.02, gz + 0.06 + 0.05 * ((i * 7) % 3))), jit(c, rng, 0.02))
    elif h == "hollin":  # a bucket of off-cuts the children play with
        M = Matrix.Translation((bx, y0 - 0.4, 0.04))
        put(k, lathe([(0.15, 0.0), (0.19, 0.3)], 8, M, caps=(True, False)), mix(P.iron, P.rust, 0.4), closed=False)
        for i, c in enumerate((P.aqua, P.green, P.amber, P.aqua, P.smoke)):
            q = Vector((bx + 0.08 * cos(i * 1.3), y0 - 0.4 + 0.08 * sin(i * 1.3), 0.3))
            put(k, sphere(q, 0.06, 0), jit(c, rng, 0.02), soft=q)
        for i, c in enumerate((P.amber, P.aqua, P.green)):
            put(k, box((bx + 0.3 + 0.13 * i, y0 - 0.55 + 0.1 * i, 0.04), (bx + 0.38 + 0.13 * i, y0 - 0.47 + 0.1 * i, 0.09)), jit(c, rng, 0.02))
    elif h == "sarro":  # a pontil rod hung over the door
        put(k, tube([(dx - 0.75, y0 - 0.1, 2.72), (dx + 0.75, y0 - 0.1, 2.76)], 0.02, 5), mix(P.iron, P.rust, 0.3))
        put(k, sphere((dx + 0.75, y0 - 0.1, 2.76), 0.05, 0), jit(P.amber, rng, 0.02))
        for e in (-0.6, 0.6):
            put(k, beam((dx + e, y0, 2.7), (dx + e, y0 - 0.13, 2.7), 0.03, 0.03), P.iron)
    elif h == "quill":  # a slate tally board by the door
        put(k, box((bx - 0.3, y0 - 0.06, 1.0), (bx + 0.3, y0 - 0.02, 1.8)), jit(P.slate, rng, 0.02))
        put(k, box((bx - 0.34, y0 - 0.07, 0.96), (bx + 0.34, y0 - 0.015, 1.0)), jit(P.drift, rng))
        raw(k, [([Vector((bx - 0.24 + 0.06 * i, y0 - 0.065, 1.55 - 0.2 * r)), Vector((bx - 0.225 + 0.06 * i, y0 - 0.065, 1.55 - 0.2 * r)), Vector((bx - 0.225 + 0.06 * i, y0 - 0.065, 1.69 - 0.2 * r)),
                  Vector((bx - 0.24 + 0.06 * i, y0 - 0.065, 1.69 - 0.2 * r))], on(P.lime, "shingles")) for r in range(3) for i in range(4 + 2 * r)])
    elif h == "brandt":  # a hen coop against the front
        put(k, box((bx - 0.5, y0 - 0.62, 0.04), (bx + 0.5, y0 - 0.02, 0.5)), jit(P.drift, rng))
        put(k, prism([(-0.66, 0.5), (0.0, 0.5), (0.0, 0.78), (-0.66, 0.56)], bx - 0.55, bx + 0.55, lambda a, s, z: Vector((a, y0 + s, z))), jit(P.tar, rng, 0.02))
        raw(k, [([Vector((bx - 0.15, y0 - 0.625, 0.06)), Vector((bx + 0.15, y0 - 0.625, 0.06)), Vector((bx + 0.15, y0 - 0.625, 0.36)), Vector((bx - 0.15, y0 - 0.625, 0.36))], P.tar)])
        for q in ((bx + 0.75, y0 - 0.35), (bx + 0.95, y0 - 0.6)):  # two hens, named after people
            c = Vector((q[0], q[1], 0.18))
            put(k, sphere(c, 0.12, 1, squash=0.8), jit(on(P.oldlime, "cloth"), rng, 0.03), soft=c)
            put(k, sphere(c + Vector((0.1, 0, 0.1)), 0.055, 0), jit(on(P.oxblood, "cloth"), rng), soft=c)
    elif h == "marl":  # wind chimes of cullet
        put(k, beam((bx, y0, 2.45), (bx, y0 - 0.45, 2.5), 0.03, 0.03), P.iron)
        for i, c in enumerate((P.aqua, P.green, P.amber, P.aqua, P.smoke)):
            q = Vector((bx - 0.14 + 0.07 * i, y0 - 0.42, 2.45))
            L = 0.25 + 0.07 * ((i * 3) % 4)
            put(k, tube([q, q - Z * L], 0.006, 3, caps=False), on(P.sand, "cloth"), closed=False)
            put(k, box((q.x - 0.02, q.y - 0.006, q.z - L - 0.16), (q.x + 0.02, q.y + 0.006, q.z - L)), jit(c, rng, 0.02))
    elif h == "dunmore":  # a bench made from a boat's thwart
        for e in (-0.5, 0.5):
            put(k, box((bx + e - 0.07, y0 - 0.42, 0.04), (bx + e + 0.07, y0 - 0.08, 0.42)), jit(P.tar, rng))
        put(k, box((bx - 0.72, y0 - 0.48, 0.42), (bx + 0.72, y0 - 0.04, 0.49), bevel=0.015), lambda co, n, c=jit(P.drift, rng): mix(c, P.pale, 0.35) if n.z > 0.5 and abs(co.x - bx) < 0.3 else c)
        put(k, beam((bx - 0.7, y0 - 0.05, 0.5), (bx - 0.45, y0 - 0.05, 0.9), 0.05, 0.12), jit(P.tar, rng))  # the thwart's knee, kept on
    elif h == "calloway":  # a ship's knee of timber propped by the door
        put(k, beam((bx, y0 - 0.12, 0.04), (bx + 0.1, y0 - 0.06, 1.5), 0.14, 0.2), jit(P.drift, rng))
        put(k, beam((bx + 0.02, y0 - 0.14, 0.14), (bx + 0.85, y0 - 0.2, 0.2), 0.14, 0.18), jit(P.drift, rng))
        put(k, beam((bx + 0.07, y0 - 0.1, 0.9), (bx + 0.55, y0 - 0.17, 0.25), 0.1, 0.12), jit(mix(P.drift, P.tar, 0.3), rng))
    elif h == "tarn":  # a row of glass floats; the Tarns have always painted their door oxblood
        zf = 2.75
        line = [Vector((gx - 0.8 + 1.6 * i / 6, y0 - 0.16, zf + 0.3 - 0.28 * sin(PI * i / 6))) for i in range(7)]
        put(k, tube(line, 0.012, 3, caps=False), on(P.sand, "cloth"), closed=False)
        for i, q in enumerate(line[1:6]):
            glass_float(k, rng, q - Z * 0.21, (P.green, P.amber, P.aqua, P.green, P.amber)[i], r=0.11, cord=q)
        for q in (line[0], line[-1]):
            put(k, beam(q + Y * 0.16, q - Y * 0.03, 0.03, 0.03), P.iron)
    elif h == "okoro":  # a string of sea-glass, each colour from a known wreck
        line = [Vector((gx - 0.7 + 1.4 * i / 9, y0 - 0.1, gz + 1.75 - 0.12 * sin(PI * i / 9))) for i in range(10)]
        put(k, tube(line, 0.008, 3, caps=False), on(P.sand, "cloth"), closed=False)
        for i, q in enumerate(line[1:9]):
            put(k, box((q.x - 0.035, q.y - 0.012, q.z - 0.11), (q.x + 0.035, q.y + 0.012, q.z - 0.02)), jit((P.aqua, P.green, P.smoke, P.amber, P.aqua, P.green, P.smoke, P.aqua)[i], rng, 0.025))
    elif h == "vane":  # a counters board chalked on the step
        raw(k, [([Vector((dx - 0.5 + 0.2 * i, y0 - 0.56, 0.185)), Vector((dx - 0.32 + 0.2 * i, y0 - 0.56, 0.185)), Vector((dx - 0.32 + 0.2 * i, y0 - 0.38, 0.185)), Vector((dx - 0.5 + 0.2 * i, y0 - 0.38, 0.185))],
                 on(P.lime, "stone") if i % 2 == 0 else mix(P.basalt, P.pale, 0.5)) for i in range(5)])
        for i, c in enumerate((P.amber, P.green, P.aqua)):
            put(k, B.cyl((dx - 0.4 + 0.3 * i, y0 - 0.47, 0.185), (dx - 0.4 + 0.3 * i, y0 - 0.47, 0.21), 0.035, 0.035, 6), jit(c, rng, 0.02))
    elif h == "morrow":  # a caged gull
        put(k, beam((bx, y0, 2.2), (bx, y0 - 0.5, 2.25), 0.03, 0.03), P.iron)
        c = Vector((bx, y0 - 0.45, 1.85))
        for i in range(8):
            a = i / 8 * TAU
            put(k, tube([c + Vector((0.17 * cos(a), 0.17 * sin(a), -0.22)), c + Vector((0.17 * cos(a), 0.17 * sin(a), 0.16)), c + Z * 0.3], 0.007, 3, caps=False), P.iron, closed=False)
        put(k, lathe([(0.18, -0.24), (0.18, -0.21)], 8, Matrix.Translation(c)), jit(P.drift, rng))
        put(k, sphere(c - Z * 0.1, 0.09, 1, squash=0.8), on(P.lime, "cloth"), soft=c)
        put(k, sphere(c + Vector((0.07, 0, 0.0)), 0.045, 0), on(P.lime, "cloth"), soft=c)
    elif h == "sato":  # a sack of kelp ash and a smoke-grey line of washing
        c = Vector((bx, y0 - 0.35, 0.04))
        put(k, moved(sphere((0, 0, 0), 0.3, 1, squash=1.2), Matrix.Translation(c + Z * 0.28)), jit(on(mix(P.sand, P.drift, 0.5), "cloth"), rng), soft=c)
        raw(k, [(oriented([c + Vector((-0.4, -0.15, 0.01)), c + Vector((0.45, -0.2, 0.01)), c + Vector((0.5, 0.3, 0.01)), c + Vector((-0.35, 0.3, 0.01))], Z), mix(P.pale, P.smoke, 0.5))])  # spilt ash
        a, b = Vector((-f.hw + 0.5, y0 - 0.12, 2.5)), Vector((f.hw - 0.5, y0 - 0.12, 2.45))
        put(k, tube([a, (a + b) / 2 - Z * 0.12, b], 0.008, 3, caps=False), on(P.sand, "cloth"), closed=False)
        for i in range(4):
            q = a.lerp(b, 0.2 + 0.2 * i) - Z * 0.1
            raw(k, [([q + X * -0.2, q + X * 0.2, q + X * 0.2 - Z * (0.5 + 0.1 * (i % 2)), q + X * -0.2 - Z * (0.45 + 0.1 * (i % 2))], jit(on(mix(P.oldlime, P.smoke, 0.6), "cloth"), rng, 0.03))], two=True)
    elif h == "dunlin":  # a lamp hook and a creel: he fishes the mole by lamplight
        put(k, beam((bx, y0, 2.0), (bx, y0 - 0.3, 2.05), 0.03, 0.03), P.iron)
        q = Vector((bx, y0 - 0.28, 1.72))
        put(k, lathe([(0.05, 0.0), (0.09, 0.05), (0.09, 0.22), (0.04, 0.28)], 6, Matrix.Translation(q)), mix(P.iron, P.rust, 0.4))
        raw(k, [([q + Vector((-0.06, -0.093, 0.07)), q + Vector((0.06, -0.093, 0.07)), q + Vector((0.06, -0.093, 0.2)), q + Vector((-0.06, -0.093, 0.2))], P.amber)], glow="Glow")
        creel(k, rng, Matrix.Translation((bx + 0.35, y0 - 0.36, 0.04)), 0.25, 0.55)
    elif h == "greave":  # seedling trays on the sill
        for i in range(2):
            x = gx - 0.33 + 0.66 * i
            put(k, box((x - 0.28, y0 - 0.26, gz - 0.02), (x + 0.28, y0 - 0.02, gz + 0.07)), jit(P.drift, rng))
            for j in range(4):
                tuft(k, rng, (x - 0.2 + 0.135 * j, y0 - 0.14, gz + 0.07), 0.07, 0.12 + 0.04 * (j % 2), LEAF, 3)
    elif h == "fenwick":  # a rain gauge on a post
        put(k, tube([(bx, y0 - 0.55, 0.04), (bx, y0 - 0.55, 1.2)], 0.035, 5), jit(P.drift, rng))
        put(k, lathe([(0.07, 1.2), (0.07, 1.42)], 8, Matrix.Identity(4) @ Matrix.Translation((bx, y0 - 0.55, 0)), caps=(True, False)), jit(P.aqua, rng, 0.02), closed=False)
        put(k, lathe([(0.1, 1.42), (0.075, 1.36)], 8, Matrix.Translation((bx, y0 - 0.55, 0)), caps=(False, False)), mix(P.iron, P.rust, 0.3), closed=False)
    elif h == "stannard":  # a stack of odd slates: every roof leaks and he is one man
        for i in range(9):
            c = P.newslate if i % 3 == 0 else P.slate
            put(k, box((bx - 0.3 + 0.01 * (i % 3), y0 - 0.5, 0.04 + 0.035 * i), (bx + 0.3 - 0.015 * (i % 2), y0 - 0.1, 0.07 + 0.035 * i)), jit(c, rng, 0.04))
        for i in range(3):
            put(k, beam((bx + 0.5 + 0.06 * i, y0 - 0.35, 0.04), (bx + 0.5 + 0.06 * i, y0 - 0.04, 0.7), 0.025, 0.45), jit(P.slate, rng, 0.04))


def gen_house(k, rng, lot):
    """A row house on its lot, one of a terrace: basalt below, limewash above, slate over; a
    0.9 x 2.0 m door in the household's colour with a two-step stoop, small-paned windows. Its
    width is its household's size, its storeys its family's (the plan), its state its history:
    lived in, empty and sound (boarded, a dropped gutter, slates gone), or a roofless shell."""
    f, env, w, near = row_frame(lot), Env(lot), lot["wear"], lot["near"]
    fam, people = lot.get("family"), lot.get("people", 0)
    n = int(lot["id"].rsplit("_", 1)[1])
    empty, lived = w["empty"] >= 1.0, "household" in lot
    A = lambda x: x - f.hw  # noqa: E731  (metres from the west wall -> the face's own axis)
    ff, fb = Face((0, f.YF, 0), X, f.w), Face((0, f.YB, 0), -X, f.w)
    stone = jit(P.basalt, rng, 0.02)
    base = P.lime if w["repair"] >= 0.7 else P.oldlime
    lime = jit(base, rng, 0.02)
    if w["soot"] > 0.05:  # grey limewash downwind of the Cone
        lime = mix(lime, P.smoke, min(0.6, w["soot"]))
    main, odd = {"kiln": (P.aqua, P.amber), "strand": (P.smoke, P.green), "ladder": (P.aqua, P.green)}.get(fam, (P.smoke, None))
    grid = {"kiln": FINE, "strand": WIDE, "ladder": BROAD}.get(fam, WIDE)
    n_odd = 0 if odd is None else 1 + round(2 * (1 - w["repair"]))
    lit = set() if not lived else {"g"} if people <= 2 else {"g", "u1"} if people <= 4 else {"g", "u0", "u1"}
    # Doors pair at the party walls, as terraces are built: odd numbers hang theirs to the east.
    dx = f.w - 1.15 if n % 2 else 1.15
    gx = 1.6 if n % 2 else f.w - 1.6
    ux = (1.3, f.w - 1.3)
    door = DOOR.get(lot.get("door_colour"), P.drift)
    pavement(k, rng, f, w)

    if f.shell:
        # A roofless shell: its roof went for fuel in the lean years. Walls only, their heads
        # ragged, the openings empty; weeds, fallen stone, and in one a tree.
        nu, nv, cu, cv = WIDE
        dhole = (A(dx) - 0.45, A(dx) + 0.45, f.F, f.F + 2.0)
        ghole = (A(gx) - 0.45, A(gx) + 0.45, f.F + 0.95, f.F + 2.3)
        uholes = [(A(x) - 0.45, A(x) + 0.45, f.z1 + 0.85, f.z1 + 2.2) for x in ux]
        wall(k, rng, ff, 0.0, f.z1, stone, [dhole, ghole])
        wall(k, rng, ff, f.z1, f.H - 0.6, mix(lime, P.basalt, 0.35), uholes)
        wall(k, rng, fb, 0.0, f.H - 1.2, stone, [(A(f.w * 0.5) - 0.45, A(f.w * 0.5) + 0.45, f.F + 1.0, f.F + 2.3)])
        a = -f.hw
        while a < f.hw - 0.05:  # the wall heads, stone by stone
            b = min(f.hw, a + rng.uniform(0.5, 0.9))
            put(k, ff.box(a, b, f.H - 0.6, f.H - rng.uniform(0.0, 0.55), -0.2, 0.0), jit(mix(P.basalt, P.pale, 0.4), rng, 0.03))
            put(k, fb.box(a, b, f.H - 1.2, f.H - 0.6 - rng.uniform(0.0, 0.5), -0.2, 0.0), jit(P.basalt, rng, 0.03))
            a = b
        flakes(k, rng, f, P.oldlime, ff, -f.hw, f.hw, f.z1, f.H - 0.7, 9, uholes)
        put(k, ff.box(A(dx) - 0.8, A(dx) + 0.8, 0.0, 0.18, 0.0, 0.62), jit(P.basalt, rng))
        put(k, ff.box(A(dx) - 0.62, A(dx) + 0.62, 0.18, 0.36, 0.0, 0.32), jit(P.basalt, rng))
        row_sides(k, rng, f, lot, env, lime)
        for _ in range(16):  # weeds on the stoop and inside
            x, y = rng.uniform(-f.hw + 0.3, f.hw - 0.3), rng.choice([f.YF - rng.uniform(0.05, 0.5), rng.uniform(f.YF + 0.4, f.YB - 0.4)])
            tuft(k, rng, (x, y, 0.04), rng.uniform(0.12, 0.24), rng.uniform(0.25, 0.6), P.grass, 5)
        for _ in range(7):  # fallen stone
            c = Vector((rng.uniform(-f.hw + 0.5, f.hw - 0.5), rng.uniform(f.YF + 0.5, f.YB - 0.5), 0.1))
            put(k, moved(box((-0.25, -0.18, -0.1), (0.25, 0.18, 0.12), bevel=0.03), Matrix.Translation(c) @ Matrix.Rotation(rng.uniform(0, PI), 4, "Z")), jit(P.basalt, rng, 0.04))
        if "tree" in lot.get("note", ""):
            # A thorn grown up inside the walls, leaning north-east as every tree here does.
            lean = env.ne
            trunk = [Vector((-0.5, -0.9, 0.0)) + lean * (0.05 * i * i) + Z * (1.05 * i) for i in range(6)]
            put(k, tube(trunk, [0.16, 0.14, 0.12, 0.1, 0.08, 0.06], 6), jit(on(mix(P.peat, P.drift, 0.4), "bark"), rng))
            for i, (dq, r) in enumerate(((0.0, 0.95), (0.55, 0.8), (1.0, 0.6), (-0.4, 0.65))):
                c = trunk[-1] + lean * dq + Z * (0.5 - 0.18 * i)
                put(k, sphere(c, r, 1, squash=0.6), jit(mix(P.grass, on(P.green, "leaves"), 0.45), rng, 0.04), soft=c)
        found(k, 1.8)
        return dict(ridge_m=f.H, state="roofless shell", door_colour="none")

    # The front: door, stoop, a ground window, two above.
    nu, nv, cu, cv = grid
    gz = f.F + 0.95
    ghole = (A(gx) - nu * cu / 2, A(gx) + nu * cu / 2, gz, gz + nv * cv)
    dhole = (A(dx) - 0.45, A(dx) + 0.45, f.F, f.F + 2.0)
    wall(k, rng, ff, 0.0, f.z1, stone, [dhole, ghole])
    plank_door(k, rng, ff, A(dx), f.F, door)
    if empty:  # boards nailed over the ground window and across the door
        raw(k, [([ff.p(ghole[0], ghole[2], -0.18), ff.p(ghole[1], ghole[2], -0.18), ff.p(ghole[1], ghole[3], -0.18), ff.p(ghole[0], ghole[3], -0.18)], P.tar)])
        for i in range(4):
            put(k, ff.obox(A(gx), gz + 0.22 + i * 0.36, nu * cu + 0.3, 0.26, 0.0, 0.04, rng.uniform(-0.07, 0.07)), jit(P.drift, rng, 0.045))
        put(k, ff.obox(A(dx), f.F + 1.1, 1.25, 0.16, -0.16, -0.12, 0.5), jit(P.drift, rng))
    else:
        window(k, rng, ff, A(gx), gz, grid, glazing(rng, main, odd, n_odd, CELLS(nu, nv)), lit="g" in lit)
    uz = f.z1 + 0.85
    uholes = [(A(x) - nu * cu / 2, A(x) + nu * cu / 2, uz, uz + nv * cv) for x in ux]
    wall(k, rng, ff, f.z1, f.E, lime, uholes)
    for wi, x in enumerate(ux):
        if empty:  # broken panes, one boarded
            window(k, rng, ff, A(x), uz, grid, glazing(rng, main, None, 0, CELLS(nu, nv), boards={(wi, 1)}, gone={(1 - wi, 2), (0, 0)}), bars=P.drift)
        else:
            window(k, rng, ff, A(x), uz, grid, glazing(rng, main, odd, max(0, n_odd - wi), CELLS(nu, nv)), lit=f"u{wi}" in lit)
    put(k, ff.box(-f.hw, f.hw, f.z1 - 0.09, f.z1 + 0.05, 0.0, 0.05, back=False), jit(P.pale, rng, 0.02))
    flakes(k, rng, f, base, ff, -f.hw, f.hw, f.z1, f.E, round((1.4 - w["repair"]) * (0.4 + w["wind"]) * f.w * 1.6 + (6 if empty else 0)), uholes)
    if lived and w["repair"] < 0.6:  # patched in fresh lime that does not match
        raw(k, [(blotch(ff, A(rng.uniform(0.5, f.w - 0.5)), f.z1 + rng.uniform(0.5, 1.6), 0.36, rng, n=11, tall=1.3), jit(P.lime, rng, 0.02)) for _ in range(2)])
    bloom = [(blotch(ff, rng.uniform(-f.hw + 0.4, f.hw - 0.4), rng.uniform(0.15, 0.7), rng.uniform(0.2, 0.4), rng, tall=0.6), mix(P.basalt, P.pale, 0.7)) for _ in range(round(w["salt"] * 6))]
    raw(k, [b for b in bloom if not (dhole[0] - 0.5 < (b[0][0] - ff.o).dot(X) < dhole[1] + 0.5)])
    # The stoop: two steps of 0.18 m, the upper tread worn pale (whitened where the house is kept).
    tread = P.lime if lived and w["repair"] >= 0.7 else P.pale
    put(k, ff.box(A(dx) - 0.8, A(dx) + 0.8, 0.0, 0.18, 0.0, 0.62), lambda co, nn, c=jit(P.basalt, rng): mix(c, P.pale, 0.6) if nn.z > 0.5 else c)
    put(k, ff.box(A(dx) - 0.62, A(dx) + 0.62, 0.18, 0.36, 0.0, 0.32), lambda co, nn, c=jit(P.basalt, rng), t=jit(tread, rng, 0.02): t if nn.z > 0.5 else c)
    if empty:  # weeds on the stoop and along the wall foot
        for _ in range(10):
            x = rng.choice([rng.uniform(0.2, f.w - 0.2), dx + rng.uniform(-0.75, 0.75)])
            nd = abs(x - dx) < 0.8
            y = f.YF - (rng.uniform(0.1, 0.6) if nd else rng.uniform(0.02, 0.14))
            tuft(k, rng, (A(x), y, 0.04 if not nd else 0.18 if y < f.YF - 0.32 else 0.36), rng.uniform(0.1, 0.2), rng.uniform(0.2, 0.5), P.grass, 5)

    # The back: plain, two windows; a full house shows a light there too.
    bx = (f.w * 0.3, f.w * 0.72)
    bg = (A(bx[0]) - 0.45, A(bx[0]) + 0.45, f.F + 1.0, f.F + 2.35)
    bu = (A(bx[1]) - 0.45, A(bx[1]) + 0.45, f.z1 + 0.85, f.z1 + 2.2)
    wall(k, rng, fb, 0.0, f.z1, stone, [bg])
    wall(k, rng, fb, f.z1, f.E, lime, [bu])
    for hole, lit_ in ((bg, False), (bu, people >= 4)):
        gone = {(0, 1), (1, 0)} if empty else set()
        window(k, rng, fb, (hole[0] + hole[1]) / 2, hole[2], WIDE, glazing(rng, main, odd, 0 if empty or odd is None else 1, CELLS(2, 3), gone=gone), lit=lit_, bars=P.drift if empty else None)
    put(k, fb.box(-f.hw, f.hw, f.z1 - 0.09, f.z1 + 0.05, 0.0, 0.05, back=False), jit(P.pale, rng, 0.02))

    a0, a1 = row_sides(k, rng, f, lot, env, lime)
    gone_at = [(a0 + 1.0, 3.9), (a0 + 1.55, 3.9), (a0 + 1.3, 3.45), (a0 + 3.0, 1.6), (a0 + 3.3, 2.6), (a0 + 0.7, 1.2)] if empty else []
    row_roof(k, rng, f, lot, a0, a1, sag_m=0.03 + 0.1 * w["age"] * (1 - w["repair"]) + (0.08 if empty else 0.0), patch=0.02 + 0.22 * (1 - w["repair"]) * (0.0 if empty else 1.0),
             gone_at=gone_at, lights=0 if empty else people // 3, lit_light=people >= 5)
    keepsake(k, rng, f, lot, A(dx), A(gx), gz - 0.13)
    found(k, 1.8)
    return dict(ridge_m=f.H, state=lot.get("state", "lived in"), door_colour=lot.get("door_colour"), household=lot.get("household"), front_m=f.w, eave_m=round(f.E, 2),
                storey_m=round(f.z1 - f.F, 2), lit=sorted(lit), keepsake=lot.get("keepsake"))


# ---------------------------------------------------------------------------------------------
# The Strand's working buildings: the rank of net lofts, the Marver and its terrace


def gen_net_loft(k, rng, lot):
    """A net loft, one of the rank of six: a tall thin shed of tarred ship's planks, gable to the
    sea, 3.5 m wide and 8.5 m to the ridge, under slate. Double doors of 0.9 x 2.0 m leaves (one
    stands open on the nets inside), a loading hatch above them and a cathead with its rope at
    the peak. It shares its side walls with its neighbours; only the rank's ends show theirs.
    The plan's `repair` says how many planks are bare driftwood."""
    W, D = lot["size"]
    hw, hd, H, w, env, near = W / 2, D / 2, lot["height_m"], lot["wear"], Env(lot), lot["near"]
    p = rad(50)
    YF, YB, zr = -hd + 0.45, hd - 0.05, H - 0.1
    E = zr - hw * math.tan(p)

    def top(x):
        return E + (hw - abs(x)) * math.tan(p)
    put(k, box((-hw, YF - 0.04, 0.0), (hw, YB + 0.04, 0.16)), jit(P.basalt, rng))
    n_bare = round((1 - w["repair"]) * 5)
    NP = 14
    bare = set(rng.sample(range(NP), n_bare))
    DW, DH, HZ0, HZ1 = 0.9, 2.0, 3.5, 5.0  # the door leaves; the loading hatch

    def planks(y, n, front):
        polys = []
        for i in range(NP):
            x0, x1 = -hw + W * i / NP + 0.008, -hw + W * (i + 1) / NP - 0.008
            xm = (x0 + x1) / 2
            c = jit(P.drift if i in bare and front else P.tar, rng, 0.03)
            if i not in bare:
                c = mix(c, P.drift, 0.3 * w["wind"] * env.weather(n) + 0.12 * rng.random())  # tar weathered grey
            z0 = 0.16
            spans = [(z0, top(xm))]
            if front and abs(xm) < DW:
                spans = [(z0 + DH + 0.04, HZ0 - 0.04), (HZ1 + 0.04, top(xm))] if abs(xm) < 0.5 else [(z0 + DH + 0.04, top(xm))]
            for za, zb in spans:
                foot = mix(c, P.pale, 0.35 * w["salt"]) if za < 0.5 else c  # salt low on the boards
                pts = [Vector((x0, y, za)), Vector((x1, y, za)), Vector((x1, y, min(zb, top(x1)) if zb >= top(xm) - 1e-6 else zb)), Vector((x0, y, min(zb, top(x0)) if zb >= top(xm) - 1e-6 else zb))]
                polys.append((oriented(pts, n), foot if za < 0.5 and zb < 1.2 else c))
        raw(k, polys)
    planks(YF, -Y, True)
    planks(YB, Y, False)
    # The west leaf, shut; the east leaf stands open on the dark of the loft: nets and floats.
    ff = Face((0, YF, 0), X, W)
    for i in range(3):
        a0 = -DW + i * DW / 3
        put(k, ff.box(a0 + 0.006, a0 + DW / 3 - 0.006, 0.16, 0.16 + DH, -0.04, 0.02 + rng.uniform(0, 0.01), back=False), jit(mix(P.tar, P.drift, 0.2), rng))
    for zz in (0.5, 1.75):
        put(k, ff.box(-DW + 0.04, -0.12, zz, zz + 0.06, 0.02, 0.05, back=False), mix(P.iron, P.rust, 0.5 + 0.4 * w["salt"]))
    DOORS.append(dict(at=[-DW / 2, YF, 0.16 + DH / 2], along=[1, 0, 0], width_m=DW, height_m=DH))
    DOORS.append(dict(at=[DW / 2, YF, 0.16 + DH / 2], along=[1, 0, 0], width_m=DW, height_m=DH, open=True))
    dark = mix(P.tar, P.basalt, 0.25)
    raw(k, [([ff.p(0.0, 0.16, -0.5), ff.p(DW, 0.16, -0.5), ff.p(DW, 0.16 + DH, -0.5), ff.p(0.0, 0.16 + DH, -0.5)], dark),
            ([ff.p(0.0, 0.16, 0.0), ff.p(0.0, 0.16, -0.5), ff.p(0.0, 0.16 + DH, -0.5), ff.p(0.0, 0.16 + DH, 0.0)], dark),
            ([ff.p(DW, 0.16, -0.5), ff.p(DW, 0.16, 0.0), ff.p(DW, 0.16 + DH, 0.0), ff.p(DW, 0.16 + DH, -0.5)], dark),
            ([ff.p(0.0, 0.16 + DH, -0.5), ff.p(DW, 0.16 + DH, -0.5), ff.p(DW, 0.16 + DH, 0.0), ff.p(0.0, 0.16 + DH, 0.0)], dark),
            ([ff.p(0.0, 0.16, 0.0), ff.p(DW, 0.16, 0.0), ff.p(DW, 0.16, -0.5), ff.p(0.0, 0.16, -0.5)], mix(P.basalt, P.pale, 0.5))])
    net = on(mix(P.kelp, P.drift, 0.5), "cloth")
    raw(k, [([ff.p(0.08 + 0.2 * i, 1.95, -0.3), ff.p(0.24 + 0.2 * i, 1.95, -0.3), ff.p(0.3 + 0.2 * i, 0.5 + 0.2 * (i % 2), -0.22), ff.p(0.05 + 0.2 * i, 0.45 + 0.2 * (i % 2), -0.22)], jit(net, rng, 0.03)) for i in range(4)])
    for i, c in enumerate((P.green, P.amber)):
        glass_float(k, rng, ff.p(0.25 + 0.4 * i, 1.55 - 0.3 * i, -0.12), c, r=0.1)
    # The loading hatch and its sill; the cathead and rope.
    put(k, ff.box(-0.5, 0.5, HZ0, HZ1, -0.03, 0.02, back=False), jit(mix(P.tar, P.drift, 0.35), rng))
    for zz in (HZ0 + 0.25, HZ1 - 0.3):
        put(k, ff.box(-0.46, 0.3, zz, zz + 0.06, 0.02, 0.045, back=False), mix(P.iron, P.rust, 0.5 + 0.4 * w["salt"]))
    put(k, ff.box(-0.6, 0.6, HZ0 - 0.08, HZ0, 0.0, 0.1), jit(P.drift, rng))
    put(k, beam((0, YF + 0.5, zr - 0.75), (0, YF - 0.38, zr - 0.72), 0.14, 0.16), jit(P.tar, rng))
    put(k, tube([(0, YF - 0.3, zr - 0.8), (0, YF - 0.3, HZ1 + 0.35)], 0.015, 3, caps=False), on(P.sand, "cloth"), closed=False)
    put(k, box((-0.05, YF - 0.34, HZ1 + 0.2), (0.05, YF - 0.26, HZ1 + 0.36)), mix(P.iron, P.rust, 0.6))
    window(k, rng, ff, 0.0, HZ1 + 0.55, (2, 2, 0.3, 0.3), glazing(rng, P.smoke, P.green, 1, CELLS(2, 2)), recess=-0.01, sill=None, bars=P.drift)
    # Barge boards, corner posts.
    for e in (-1, 1):
        for y in (YF - 0.03, YB + 0.03):
            put(k, beam((e * hw, y, E - 0.02), (0, y, zr + 0.02), 0.05, 0.16, up=Y), jit(P.tar, rng, 0.02))
        put(k, box((e * hw - (0.07 if e > 0 else 0.0), YF - 0.03, 0.16), (e * hw + (0.07 if e < 0 else 0.0), YF + 0.04, E)), jit(P.tar, rng, 0.02))
        if near.get("west" if e < 0 else "east") is None:  # the rank's end: its long side shows
            n = X * e
            m = 16
            raw(k, [(oriented([Vector((e * hw, YF + (YB - YF) * i / m + 0.008, 0.16)), Vector((e * hw, YF + (YB - YF) * (i + 1) / m - 0.008, 0.16)), Vector((e * hw, YF + (YB - YF) * (i + 1) / m - 0.008, E)),
                               Vector((e * hw, YF + (YB - YF) * i / m + 0.008, E))], n), mix(jit(P.tar, rng, 0.03), P.drift, 0.35 * env.weather(n) * (0.5 + w["wind"]) + 0.1 * rng.random())) for i in range(m)])
    S = hw / cos(p)
    for sgn in (-1, 1):
        Dv, Nv = Vector((sgn * cos(p), 0, -sin(p))), Vector((sgn * sin(p), 0, cos(p)))

        def state(a, t, sgn=sgn):
            c = jit(P.slate, rng, 0.04)
            ex = env.weather(X * sgn) * (0.4 + w["wind"])
            if nz(a * 0.8 + lot["at"][0], t, 5.0 + sgn) + rng.uniform(-0.2, 0.2) > 0.7 - 0.5 * ex and t > 0.8:
                c = mix(c, P.lichen, rng.uniform(0.1, 0.24))
            return jit(P.newslate, rng, 0.04) if rng.random() < 0.3 * (1 - w["repair"]) else c
        slates(k, rng, lambda a, t, hh, Dv=Dv, Nv=Nv: Vector((0, a, zr)) + Dv * t + Nv * hh, YF - 0.08, YB + 0.08, S, state)
    put(k, box((-0.07, YF - 0.1, zr - 0.02), (0.07, YB + 0.1, H)), jit(P.tar, rng, 0.02))
    found(k, 1.8)
    return dict(ridge_m=H, bare_planks=n_bare)


def gen_marver(k, rng, lot):
    """The Marver, the cookshop on Mid Row: a wide row house whose ground floor is open to the
    street through three serving hatches over a basalt counter, their shutters propped up, the
    hearth alight behind the middle one. A mustard door under the figurehead of a ship that never
    left; the Achterbergs live over it."""
    f, env, w = row_frame(lot), Env(lot), lot["wear"]
    A = lambda x: x - f.hw  # noqa: E731
    ff, fb = Face((0, f.YF, 0), X, f.w), Face((0, f.YB, 0), -X, f.w)
    stone, lime = jit(P.basalt, rng, 0.02), jit(P.lime if w["repair"] >= 0.7 else P.oldlime, rng, 0.02)
    pavement(k, rng, f, w)
    dx = 1.3
    dhole = (A(dx) - 0.45, A(dx) + 0.45, f.F, f.F + 2.0)
    hatches = [(A(x0), A(x0 + 2.6), f.F + 0.6, f.F + 2.35) for x0 in (2.5, 5.55, 8.6)]
    wall(k, rng, ff, 0.0, f.z1, stone, [dhole] + hatches, depth=0.3)
    plank_door(k, rng, ff, A(dx), f.F, DOOR[lot.get("door_colour", "mustard")])
    put(k, ff.box(A(dx) - 0.8, A(dx) + 0.8, 0.0, 0.18, 0.0, 0.62), lambda co, n, c=jit(P.basalt, rng): mix(c, P.pale, 0.6) if n.z > 0.5 else c)
    put(k, ff.box(A(dx) - 0.62, A(dx) + 0.62, 0.18, 0.36, 0.0, 0.32), lambda co, n, c=jit(P.basalt, rng), t=jit(P.pale, rng, 0.02): t if n.z > 0.5 else c)
    warm = mix(P.brick, P.tar, 0.45)
    for hi, (a0, a1, z0, z1) in enumerate(hatches):
        # The room behind, the counter's worn top, the shutter propped open on two sticks.
        raw(k, [([ff.p(a0, z0, -1.3), ff.p(a1, z0, -1.3), ff.p(a1, z1, -1.3), ff.p(a0, z1, -1.3)], jit(warm, rng, 0.02)),
                ([ff.p(a0, z0, -0.3), ff.p(a1, z0, -0.3), ff.p(a1, z0, -1.3), ff.p(a0, z0, -1.3)], mix(P.drift, P.tar, 0.4)),
                ([ff.p(a0, z1, -1.3), ff.p(a1, z1, -1.3), ff.p(a1, z1, -0.3), ff.p(a0, z1, -0.3)], warm),
                ([ff.p(a0, z0, -0.3), ff.p(a0, z0, -1.3), ff.p(a0, z1, -1.3), ff.p(a0, z1, -0.3)], warm), ([ff.p(a1, z0, -1.3), ff.p(a1, z0, -0.3), ff.p(a1, z1, -0.3), ff.p(a1, z1, -1.3)], warm)])
        put(k, ff.box(a0 - 0.08, a1 + 0.08, z0 - 0.09, z0, -0.3, 0.22, bevel=0.015), lambda co, n, c=jit(P.pale, rng, 0.02): mix(c, P.lime, 0.3) if n.z > 0.5 else c)
        sh = [ff.p(a0, z1 + 0.02, 0.03), ff.p(a1, z1 + 0.02, 0.03), ff.p(a1, z1 - 0.3, 0.72), ff.p(a0, z1 - 0.3, 0.72)]
        m = 6
        raw(k, [([sh[0].lerp(sh[1], i / m + 0.004), sh[0].lerp(sh[1], (i + 1) / m - 0.004), sh[3].lerp(sh[2], (i + 1) / m - 0.004), sh[3].lerp(sh[2], i / m + 0.004)], jit(mix(P.tar, P.drift, 0.25), rng, 0.03)) for i in range(m)], two=True)
        for a in (a0 + 0.15, a1 - 0.15):
            put(k, beam(ff.p(a, z0, 0.18), ff.p(a, z1 - 0.3, 0.68), 0.03, 0.03), jit(P.drift, rng))
        if hi == 1:  # the hearth: the one warm light on the row at any hour
            eye = [(x, 0.75 + math.sqrt(max(0.0, 0.36 - x * x))) for x in [-0.6 + 0.12 * i for i in range(11)]]
            am = (a0 + a1) / 2
            raw(k, [([ff.p(am - 0.6, z0 + 0.12, -1.28), ff.p(am + 0.6, z0 + 0.12, -1.28)] + [ff.p(am + x, z0 + z, -1.28) for x, z in reversed(eye)], P.amber)], glow="GlowAmber")
            put(k, ff.box(am - 0.85, am + 0.85, z0, z0 + 0.12, -1.3, -1.0, back=False), mix(P.brick, P.tar, 0.3))
            put(k, lathe([(0.2, 0.0), (0.27, 0.22), (0.2, 0.3)], 8, Matrix.Translation(ff.p(am + 0.1, z0 + 0.12, -1.12))), P.iron)
        else:  # shelves of bottles and bowls
            put(k, ff.box(a0 + 0.2, a1 - 0.2, z0 + 0.95, z0 + 1.0, -1.3, -1.05, back=False), jit(P.drift, rng))
            for i in range(7):
                c = (P.green, P.amber, P.aqua, P.smoke, P.green, P.aqua, P.amber)[(i + hi) % 7]
                x = a0 + 0.4 + (a1 - a0 - 0.8) * i / 6
                put(k, lathe([(0.05, 0.0), (0.06, 0.14), (0.025, 0.2), (0.025, 0.27)], 6, Matrix.Translation(ff.p(x, z0 + 1.0, -1.17))), jit(c, rng, 0.03))
            for i in range(3):
                put(k, lathe([(0.06, 0.0), (0.13, 0.08)], 8, Matrix.Translation(ff.p(a0 + 0.5 + 0.7 * i, z0, -0.02)), caps=(True, False)), jit(mix(P.sand, P.oldlime, 0.4), rng), closed=False)
    # The figurehead over the door: a woman leaning out from the wall, her paint gone to chalk.
    fx, fz = A(dx), f.F + 2.45
    put(k, beam(ff.p(fx, fz, 0.0), ff.p(fx, fz + 1.0, 0.42), 0.34, 0.3, up=X), jit(mix(P.chalkblue, P.drift, 0.45), rng))
    put(k, beam(ff.p(fx, fz + 0.2, 0.0), ff.p(fx, fz - 0.25, 0.1), 0.42, 0.2, up=X), jit(mix(P.chalkblue, P.drift, 0.6), rng))
    hc = ff.p(fx, fz + 1.2, 0.5)
    put(k, sphere(hc, 0.16, 1), jit(on(P.oldlime, "wood"), rng), soft=hc)
    put(k, moved(sphere((0, 0, 0), 0.19, 1, squash=0.9), Matrix.Translation(hc + Vector((0, 0.06, 0.03)))), jit(mix(P.oxblood, P.tar, 0.4), rng), soft=hc)
    for e in (-1, 1):
        put(k, beam(ff.p(fx + e * 0.2, fz + 0.85, 0.36), ff.p(fx + e * 0.26, fz + 0.3, 0.12), 0.09, 0.09), jit(on(P.oldlime, "wood"), rng))
    # Above: four windows of the Achterbergs' rooms, two of them lit.
    nu, nv, cu, cv = FINE
    uz = f.z1 + 0.85
    ux = (1.6, 4.5, 7.5, 10.4)
    uholes = [(A(x) - nu * cu / 2, A(x) + nu * cu / 2, uz, uz + nv * cv) for x in ux]
    wall(k, rng, ff, f.z1, f.E, lime, uholes)
    for wi, x in enumerate(ux):
        window(k, rng, ff, A(x), uz, FINE, glazing(rng, P.aqua, P.amber, 1 + wi % 2, CELLS(nu, nv)), lit=wi in (1, 2))
    put(k, ff.box(-f.hw, f.hw, f.z1 - 0.09, f.z1 + 0.05, 0.0, 0.05, back=False), jit(P.pale, rng, 0.02))
    flakes(k, rng, f, P.lime, ff, -f.hw, f.hw, f.z1, f.E, round((1.4 - w["repair"]) * (0.4 + w["wind"]) * f.w * 1.2), uholes)
    raw(k, [(blotch(ff, A(5.55 + 1.3) + rng.uniform(-0.6, 0.6), f.z1 + 0.25 + 0.3 * i, 0.5 - 0.1 * i, rng, n=10, tall=0.9), mix(lime, P.tar, 0.22 - 0.05 * i)) for i in range(3)])  # the hearth's smoke on the lime
    bholes = [(A(x) - 0.45, A(x) + 0.45, f.z1 + 0.85, f.z1 + 2.2) for x in (2.5, 9.0)]
    wall(k, rng, fb, 0.0, f.z1, stone, [(A(f.w - 6.0) - 0.45, A(f.w - 6.0) + 0.45, f.F + 1.0, f.F + 2.35)])
    wall(k, rng, fb, f.z1, f.E, lime, [(-h1, -h0, zb, zt) for h0, h1, zb, zt in bholes])
    window(k, rng, fb, -A(f.w - 6.0), f.F + 1.0, WIDE, glazing(rng, P.aqua, P.amber, 1, CELLS(2, 3)))
    for h0, h1, zb, zt in bholes:
        window(k, rng, fb, -(h0 + h1) / 2, zb, WIDE, glazing(rng, P.aqua, P.amber, 1, CELLS(2, 3)), lit=h0 < 0)
    a0, a1 = row_sides(k, rng, f, lot, env, lime)
    row_roof(k, rng, f, lot, a0, a1, sag_m=0.05, patch=0.02 + 0.22 * (1 - w["repair"]), lights=2, lit_light=True)
    # The hearth's stack at the east gable: broad, sooted, two pots.
    xs, zc = f.hw - 1.0, f.zr + 1.5
    put(k, box((xs - 0.6, f.YR - 0.38, f.zr - 0.7), (xs + 0.6, f.YR + 0.38, zc)), lambda co, n, c=jit(P.brick, rng, 0.02): mix(c, P.tar, 0.6 * max(0.0, (co.z - zc + 1.1) / 1.1)))
    put(k, box((xs - 0.66, f.YR - 0.44, zc), (xs + 0.66, f.YR + 0.44, zc + 0.09)), jit(P.pale, rng, 0.02))
    for e in (-0.3, 0.3):
        put(k, lathe([(0.13, 0.0), (0.15, 0.08), (0.11, 0.5), (0.13, 0.54), (0.09, 0.54), (0.09, 0.44)], 6, Matrix.Translation((xs + e, f.YR, zc + 0.09))), mix(jit(P.newbrick, rng, 0.03), P.tar, 0.4))
    found(k, 1.8)
    return dict(ridge_m=f.H, hatches=3, household=lot.get("household"), keepsake=lot.get("keepsake"))


def gen_marver_terrace(k, rng, lot):
    """The Marver's terrace over the harbour: flags, three trestle tables with their benches (the
    plan's six seats), an iron rail above the drop, a lamp on a spar. Ship parts reused: the
    benches are thwarts, an anchor is a bench end."""
    W, D = lot["size"]
    hw, hd = W / 2, D / 2
    nx, ny = 6, 3
    put(k, box((-hw, -hd, 0.0), (hw, hd, 0.025)), mix(P.basalt, P.tar, 0.3))
    for i in range(nx):
        for j in range(ny):
            x0, x1, y0, y1 = -hw + W * i / nx, -hw + W * (i + 1) / nx, -hd + D * j / ny, -hd + D * (j + 1) / ny
            put(k, box((x0 + 0.015, y0 + 0.015, 0.0), (x1 - 0.015, y1 - 0.015, 0.04), bevel=0.01), jit(mix(P.basalt, P.pale, 0.5), rng, 0.03))
    iron_rail(k, rng, [Vector((-hw + 0.1, hd - 2.0, 0.04)), Vector((-hw + 0.1, -hd + 0.12, 0.04))] + [Vector((-hw + 0.1 + (W - 0.2) * i / 4, -hd + 0.12, 0.04)) for i in range(1, 5)] + [Vector((hw - 0.1, hd - 2.0, 0.04))], h=1.0)
    for (x0, x1, yt, yb) in ((0.6, 5.4, -2.15, -1.45), (-5.4, -0.6, -2.15, -1.45), (0.6, 5.4, 1.75, 1.05)):
        put(k, box((x0, yt - 0.36, 0.72), (x1, yt + 0.36, 0.78), bevel=0.012), lambda co, n, c=jit(P.drift, rng): mix(c, P.pale, 0.3) if n.z > 0.5 else c)
        for x in (x0 + 0.5, x1 - 0.5):
            for e in (-1, 1):
                put(k, beam((x, yt + e * 0.34, 0.04), (x, yt - e * 0.1, 0.72), 0.06, 0.08, up=X), jit(P.drift, rng))
        put(k, box((x0, yb - 0.17, 0.42), (x1, yb + 0.17, 0.48), bevel=0.012), jit(mix(P.drift, P.tar, 0.3), rng))
        for x in (x0 + 0.3, (x0 + x1) / 2, x1 - 0.3):
            put(k, box((x - 0.06, yb - 0.14, 0.04), (x + 0.06, yb + 0.14, 0.42)), jit(P.tar, rng))
        for i in range(2):  # a bowl and a bottle left out
            put(k, lathe([(0.05, 0.0), (0.12, 0.07)], 8, Matrix.Translation((x0 + 1.0 + 2.4 * i, yt + 0.05, 0.78)), caps=(True, False)), jit(mix(P.sand, P.oldlime, 0.4), rng), closed=False)
        put(k, lathe([(0.045, 0.0), (0.055, 0.14), (0.022, 0.2), (0.022, 0.27)], 6, Matrix.Translation((x0 + 2.2, yt - 0.1, 0.78))), jit(rng.choice([P.green, P.amber]), rng, 0.03))
    # The anchor at the west bench's end: stock, shank and one fluke showing.
    ax = -5.7
    rust = mix(P.iron, P.rust, 0.7)
    put(k, beam((ax, -1.45, 0.04), (ax, -1.3, 1.25), 0.09, 0.09), rust)
    put(k, beam((ax, -1.75, 1.12), (ax, -0.95, 1.2), 0.07, 0.07), rust)
    put(k, beam((ax, -1.9, 0.3), (ax, -1.45, 0.06), 0.08, 0.14), rust)
    put(k, beam((ax, -1.0, 0.3), (ax, -1.45, 0.06), 0.08, 0.14), rust)
    # The lamp on a spar: mismatched panes, lit at dusk.
    lx, ly = -0.0, -0.3
    put(k, tube([(lx, ly, 0.04), (lx, ly, 2.5)], [0.07, 0.05], 6), jit(P.drift, rng))
    put(k, beam((lx, ly, 2.45), (lx + 0.5, ly, 2.55), 0.04, 0.04), P.iron)
    c = Vector((lx + 0.5, ly, 2.22))
    put(k, box((c.x - 0.11, c.y - 0.11, c.z + 0.2), (c.x + 0.11, c.y + 0.11, c.z + 0.24)), P.iron)
    put(k, box((c.x - 0.1, c.y - 0.1, c.z - 0.03), (c.x + 0.1, c.y + 0.1, c.z)), P.iron)
    for i, (n, col) in enumerate(((X, P.amber), (-X, P.aqua), (Y, P.aqua), (-Y, P.green))):
        s = Z.cross(n)
        raw(k, [(oriented([c + n * 0.09 - s * 0.08, c + n * 0.09 + s * 0.08, c + n * 0.09 + s * 0.08 + Z * 0.2, c + n * 0.09 - s * 0.08 + Z * 0.2], n), jit(col, rng, 0.02))], glow="Glow")
    return dict(ridge_m=2.6, seats=6)


# ---------------------------------------------------------------------------------------------
# Landmarks of the ship days: the Counting House and the Watchglass


def slate_field(k, rng, fn, bounds, S, state, course=0.5, cut=(0.6, 1.1), th=0.05):
    """A slope of slates whose width changes down the slope (a hip, a trapezoid): bounds(t) is
    the slope's (a0, a1) at t below its head. As `slates` otherwise."""
    N = (fn(0, 0, 1) - fn(0, 0, 0)).normalized()
    D = (fn(0, 1, 0) - fn(0, 0, 0)).normalized()
    (lo0, hi0), (lo1, hi1) = bounds(0.0), bounds(S)
    deck = [fn(lo0, 0, 0)] + ([fn(hi0, 0, 0)] if hi0 - lo0 > 1e-3 else []) + [fn(hi1, S, 0), fn(lo1, S, 0)]
    raw(k, [(oriented(deck, N), P.tar)])
    n = max(2, round(S / course))
    polys = []
    for i in range(n):
        t0, t1 = S * i / n, S * (i + 1) / n
        lo, hi = bounds((t0 + t1) / 2)
        a = lo - rng.uniform(0.0, 0.4)
        while a < hi - 1e-6:
            b = a + rng.uniform(*cut)
            l, h = max(a, lo), min(b, hi)
            a = b
            if h - l < 0.08:
                continue
            c = state((l + h) / 2, (t0 + t1) / 2)
            if c is None:
                continue
            e = t1 - rng.uniform(0.0, 0.03)
            top = [fn(l + 0.008, max(0.0, t0 - 0.04), 0.012), fn(h - 0.008, max(0.0, t0 - 0.04), 0.012), fn(h - 0.008, e, th), fn(l + 0.008, e, th)]
            polys.append((oriented(top, N), c))
            polys.append((oriented([top[3], top[2], fn(h - 0.008, e, 0.0), fn(l + 0.008, e, 0.0)], D), mix(c, P.tar, 0.3)))
    raw(k, polys)


def arch_bay(k, rng, o, u, n, x0, x1, zs, ztop, th, stone, soot=0.0):
    """One arch of an arcade in a wall th thick: the opening runs x0..x1 along u from o, springs
    at zs and is a half circle; the wall above it rises to ztop. Pale voussoirs, a dark keystone."""
    o, u, n = Vector(o), Vector(u), Vector(n)
    R, cx = (x1 - x0) / 2, (x0 + x1) / 2
    Q = lambda x, z, w=0.0: o + u * x + Z * z + n * w  # noqa: E731
    segs = 12
    arch = [(cx - R * cos(PI * j / segs), zs + R * sin(PI * j / segs)) for j in range(segs + 1)]
    polys = []
    mid = Q(cx, zs, -th / 2)
    for (xa, za), (xb, zb) in zip(arch, arch[1:]):
        c = jit(stone, rng, 0.02)
        polys.append((oriented([Q(xa, za), Q(xb, zb), Q(xb, ztop), Q(xa, ztop)], n), c))
        polys.append((oriented([Q(xa, za, -th), Q(xb, zb, -th), Q(xb, ztop, -th), Q(xa, ztop, -th)], -n), mix(c, P.tar, 0.25)))
        polys.append((oriented([Q(xa, za, -th), Q(xb, zb, -th), Q(xb, zb), Q(xa, za)], mid - Q((xa + xb) / 2, (za + zb) / 2, -th / 2)), mix(jit(P.pale, rng, 0.02), P.tar, 0.2 + soot)))
    raw(k, polys)
    for i in range(9):
        t0, t1, key = PI * i / 9, PI * (i + 1) / 9, i == 4
        put(k, lbox(Vector((t0 + 0.012, R, 0.0)), Vector((t1 - 0.012, R + (0.46 if key else 0.36), 0.09 if key else 0.05)),
                    fn=lambda q: Q(cx - q.y * cos(q.x), zs + q.y * sin(q.x), q.z), open_bottom=True), jit(P.basalt if key else P.pale, rng, 0.025))


def gen_counting_house(k, rng, lot):
    """The Counting House: the ship days' hall, 30 x 12 m on an open arcade of seven arches, a
    limewashed tally room above under a hipped slate roof, and a cupola whose clock stopped at
    ten past four. Built for a trade that no longer exists: its lime is flaking, its slates are
    patched, the arcade is the market and the shelter from rain."""
    W, D = lot["size"]
    hw, hd, w, env = W / 2 - 0.1, D / 2 - 0.1, lot["wear"], Env(lot)
    YF, YB, YI = -hd, hd, -hd + 3.6
    ZS, ZH, ZE, ZR = 2.5, 4.7, 8.2, 12.0
    stone = jit(P.basalt, rng, 0.02)
    lime = jit(P.oldlime, rng, 0.02)
    PW = 0.86
    pitch = (2 * hw - PW) / 7
    piers = [-hw + PW / 2 + pitch * i for i in range(8)]
    TH = 0.8
    # The arcade's front: eight basalt piers, seven arches, a carved band over them.
    for i, xc in enumerate(piers):
        bloom = w["salt"]
        put(k, lbox(Vector((xc - PW / 2, 0.0, -TH)), Vector((xc + PW / 2, ZS, 0.0)), fn=lambda q: Vector((q.x, YF - q.z, q.y)), bevel=0.02),
            lambda co, n, c=jit(stone, rng, 0.02), i=i: mix(c, P.pale, 0.55 * bloom) if co.z < 0.9 and nz(co.x * 1.3, co.z * 2.0, i) > 0.0 else c)
        put(k, lbox(Vector((xc - PW / 2 - 0.05, ZS - 0.14, -TH - 0.05)), Vector((xc + PW / 2 + 0.05, ZS + 0.04, 0.05)), fn=lambda q: Vector((q.x, YF - q.z, q.y))), jit(P.pale, rng, 0.02))
        put(k, lbox(Vector((xc - PW / 2 - 0.04, 0.0, -TH - 0.04)), Vector((xc + PW / 2 + 0.04, 0.3, 0.04)), fn=lambda q: Vector((q.x, YF - q.z, q.y))), jit(P.pale, rng, 0.02))
        if i < 7:
            arch_bay(k, rng, (0, YF, 0), X, -Y, xc + PW / 2, piers[i + 1] - PW / 2, ZS, ZH, TH, stone)
        # The wall over each pier, between the arches.
        raw(k, [([Vector((xc - PW / 2, YF, ZS)), Vector((xc + PW / 2, YF, ZS)), Vector((xc + PW / 2, YF, ZH)), Vector((xc - PW / 2, YF, ZH))], jit(stone, rng, 0.02)),
                ([Vector((xc + PW / 2, YF + TH, ZS)), Vector((xc - PW / 2, YF + TH, ZS)), Vector((xc - PW / 2, YF + TH, ZH)), Vector((xc + PW / 2, YF + TH, ZH))], mix(stone, P.tar, 0.25))])
    ff = Face((0, YF, 0), X, 2 * hw)
    put(k, ff.box(-hw, hw, ZH - 0.3, ZH + 0.06, 0.0, 0.06, back=False), jit(P.pale, rng, 0.02))
    script = mix(P.pale, P.basalt, 0.75)  # the ship days' formal script, cut into the band
    raw(k, [([ff.p(a, ZH - 0.2, 0.065), ff.p(a + 0.1 + 0.08 * ((j * 7) % 3), ZH - 0.2, 0.065), ff.p(a + 0.1 + 0.08 * ((j * 7) % 3), ZH - 0.04, 0.065), ff.p(a, ZH - 0.04, 0.065)], script)
            for j, a in enumerate([-hw + 0.9 + 0.42 * j for j in range(int((2 * hw - 1.8) / 0.42))]) if j % 6 != 5])
    # The arcade's floor, its back wall with the tally room's doors, its ceiling.
    for i in range(7):
        for j in range(2):
            x0, x1 = -hw + 2 * hw * i / 7, -hw + 2 * hw * (i + 1) / 7
            put(k, box((x0 + 0.015, YF + 0.01 + (YI - YF) * j / 2, 0.0), (x1 - 0.015, YF + (YI - YF) * (j + 1) / 2 - 0.015, 0.05), bevel=0.01), jit(mix(P.basalt, P.pale, 0.6 if j == 0 else 0.4), rng, 0.03))
    fi = Face((0, YI, 0), X, 2 * hw)
    door_at = (piers[2] + pitch / 2, piers[4] + pitch / 2)
    win_at = [piers[i] + pitch / 2 for i in (0, 1, 3, 5, 6)]
    iholes = [(a - 0.45, a + 0.45, 0.18, 2.18) for a in door_at] + [(a - 0.48, a + 0.48, 1.2, 2.52) for a in win_at]
    wall(k, rng, fi, 0.0, ZH, mix(stone, P.pale, 0.25), iholes)
    for a in door_at:
        plank_door(k, rng, fi, a, 0.18, mix(P.seagreen, P.drift, 0.3))
        put(k, fi.box(a - 0.7, a + 0.7, 0.0, 0.18, 0.0, 0.4), lambda co, n, c=jit(P.basalt, rng): mix(c, P.pale, 0.6) if n.z > 0.5 else c)
    for a in win_at:
        window(k, rng, fi, a, 1.2, FINE, glazing(rng, P.smoke, P.green, 2, CELLS(3, 4)))
    raw(k, [([Vector((-hw, YF + TH, ZH - 0.01)), Vector((-hw, YI, ZH - 0.01)), Vector((hw, YI, ZH - 0.01)), Vector((hw, YF + TH, ZH - 0.01))], mix(P.tar, P.drift, 0.2))])
    for i in (1, 5):  # the arcade's two lamps: the counters game is played under them
        c = Vector((piers[i] + pitch / 2, YF + 1.9, 3.3))
        put(k, tube([c + Z * 0.3, Vector((c.x, c.y, ZH))], 0.012, 3, caps=False), P.iron, closed=False)
        put(k, box((c.x - 0.13, c.y - 0.13, c.z + 0.26), (c.x + 0.13, c.y + 0.13, c.z + 0.3)), P.iron)
        for n_, col in ((X, P.amber), (-X, P.aqua), (Y, P.aqua), (-Y, P.amber)):
            s_ = Z.cross(n_)
            raw(k, [(oriented([c + n_ * 0.1 - s_ * 0.1, c + n_ * 0.1 + s_ * 0.1, c + n_ * 0.1 + s_ * 0.1 + Z * 0.26, c + n_ * 0.1 - s_ * 0.1 + Z * 0.26], n_), jit(col, rng, 0.02))], glow="Glow")
    # The ends and the back, basalt to the hall's floor; each end has the arcade's side arch.
    for sx, u in ((-1, -Y), (1, Y)):
        n = X * sx
        fs = Face((sx * hw, 0, 0), u, 2 * hd)
        a_arc = (-hd + 0.7, -hd + 3.1) if sx > 0 else (hd - 3.1, hd - 0.7)  # along u: the arcade's part of this side
        arch_bay(k, rng, (sx * hw, 0, 0), u, n, a_arc[0], a_arc[1], ZS, ZH, TH, stone)
        lo, hi = (-hd, a_arc[0]), (a_arc[1], hd)
        for a0, a1 in (lo, hi):
            raw(k, [(oriented([fs.p(a0, 0, 0), fs.p(a1, 0, 0), fs.p(a1, ZH, 0), fs.p(a0, ZH, 0)], n), jit(stone, rng, 0.02))])
        raw(k, [(oriented([fs.p(a_arc[0], ZS, -TH), fs.p(a_arc[0], 0, -TH), fs.p(a_arc[0], 0, 0), fs.p(a_arc[0], ZS, 0)], u), mix(stone, P.tar, 0.2)),
                (oriented([fs.p(a_arc[1], ZS, -TH), fs.p(a_arc[1], 0, -TH), fs.p(a_arc[1], 0, 0), fs.p(a_arc[1], ZS, 0)], -u), mix(stone, P.tar, 0.2))])
        put(k, fs.box(-hd, hd, ZH - 0.3, ZH + 0.06, 0.0, 0.06, back=False), jit(P.pale, rng, 0.02))
        sholes = [(a - 0.54, a + 0.54, ZH + 0.9, ZH + 2.7) for a in (-2.6, 2.6)]
        wall(k, rng, fs, ZH, ZE, lime, sholes)
        for h0, h1, zb, zt in sholes:
            window(k, rng, fs, (h0 + h1) / 2, zb, (3, 5, 0.36, 0.36), glazing(rng, P.aqua, P.smoke, 2, CELLS(3, 5)))
        ex = env.weather(n) * (0.5 + w["wind"])
        flakes(k, rng, NS(), P.oldlime, fs, -hd, hd, ZH, ZE, round(4 + 22 * ex), sholes)
        raw(k, [(blotch(fs, rng.uniform(-hd + 0.4, hd - 0.4), rng.uniform(0.6, ZE - 0.5), rng.uniform(0.08, 0.22), rng, n=8, tall=rng.uniform(0.6, 1.5)), mix(stone, P.lichen, 0.5)) for _ in range(round(16 * ex))])
    fb = Face((0, YB, 0), -X, 2 * hw)
    bholes = [(a - 0.48, a + 0.48, 1.4, 2.72) for a in (-10.0, -5.0, 5.0, 10.0)]
    wall(k, rng, fb, 0.0, ZH, stone, bholes)
    for h0, h1, zb, zt in bholes:
        window(k, rng, fb, (h0 + h1) / 2, zb, FINE, glazing(rng, P.smoke, P.green, 2, CELLS(3, 4)))
    put(k, fb.box(-hw, hw, ZH - 0.3, ZH + 0.06, 0.0, 0.06, back=False), jit(P.pale, rng, 0.02))
    # The tally room: seven tall windows over the arches; Aldous Quill's lamp burns in one.
    uh = [(piers[i] + pitch / 2 - 0.54, piers[i] + pitch / 2 + 0.54, ZH + 0.9, ZH + 2.7) for i in range(7)]
    wall(k, rng, ff, ZH, ZE, lime, uh)
    wall(k, rng, fb, ZH, ZE, lime, [(-h1, -h0, zb, zt) for h0, h1, zb, zt in uh[1::2]])
    for i, (h0, h1, zb, zt) in enumerate(uh):
        window(k, rng, ff, (h0 + h1) / 2, zb, (3, 5, 0.36, 0.36), glazing(rng, P.aqua, P.smoke if i % 2 else P.amber, 2 + i % 2, CELLS(3, 5)), lit=i == 4)
        if i % 2:
            window(k, rng, fb, -(h0 + h1) / 2, zb, (3, 5, 0.36, 0.36), glazing(rng, P.aqua, P.smoke, 2, CELLS(3, 5)))
    flakes(k, rng, NS(), P.oldlime, ff, -hw, hw, ZH, ZE, round(10 + 40 * (0.3 + w["wind"]) * (1.3 - w["repair"])), uh)
    for e in (-1, 1):  # pale quoins at the corners
        for j in range(int(ZE / 0.5)):
            lw = 0.5 if j % 2 else 0.3
            put(k, ff.box(e * hw - (lw if e > 0 else 0.0), e * hw + (lw if e < 0 else 0.0), j * 0.5 + 0.01, j * 0.5 + 0.49, 0.0, 0.04, back=False), jit(P.pale, rng, 0.025))
    # The cornice and the hipped roof.
    put(k, box((-hw - 0.08, YF - 0.08, ZE), (hw + 0.08, YB + 0.08, ZE + 0.22), bevel=0.03), jit(P.pale, rng, 0.02))
    z0 = ZE + 0.22
    HR = hd + 0.08  # the roof's half span
    S = math.hypot(HR, ZR - z0)
    c_p, s_p = HR / S, (ZR - z0) / S
    RL = hw + 0.08 - HR  # half the ridge's length
    gone = [(-11.5 + 0.9 * i, 4.9 + 0.5 * (i % 2)) for i in range(4)] + [(-6.2, 6.3), (3.4, 5.6)]  # slates the storm took from the south-west

    def state_of(n, front):
        ex = env.weather(n) * (0.5 + w["wind"])

        def state(a, t):
            if front and any(abs(a - ga) < 0.5 and abs(t - gt) < 0.27 for ga, gt in gone):
                return None
            c = jit(P.slate, rng, 0.04)
            if nz(a * 0.45, t * 0.8, 2.0 + n.x + 2 * n.y) + rng.uniform(-0.25, 0.25) > 0.7 - 0.55 * ex and t > 1.5:
                c = mix(c, P.lichen, rng.uniform(0.1, 0.24))
            return jit(P.newslate, rng, 0.04) if rng.random() < 0.05 + 0.2 * (1 - w["repair"]) else c
        return state
    for sgn in (-1, 1):
        Dv, Nv = Vector((0, sgn * c_p, -s_p)), Vector((0, sgn * s_p, c_p))
        slate_field(k, rng, lambda a, t, h, Dv=Dv, Nv=Nv: Vector((a, 0, ZR)) + Dv * t + Nv * h, lambda t: (-RL - HR * t / S, RL + HR * t / S), S, state_of(Y * sgn, sgn < 0))
        Dh, Nh = Vector((sgn * c_p, 0, -s_p)), Vector((sgn * s_p, 0, c_p))
        slate_field(k, rng, lambda a, t, h, Dh=Dh, Nh=Nh, sgn=sgn: Vector((sgn * RL, a, ZR)) + Dh * t + Nh * h, lambda t: (-HR * t / S, HR * t / S), S, state_of(X * sgn, False))
        for ey in (-1, 1):  # the hips, in lead-grey stone
            coping(k, rng, (sgn * RL, 0, ZR + 0.02), (sgn * (RL + HR), ey * HR, z0 + 0.04), 0.3, 0.1, col=P.basalt, stone=0.9)
    coping(k, rng, (-RL, 0, ZR), (RL, 0, ZR), 0.36, 0.14, col=P.basalt, stone=0.8)
    # The cupola: a square of tarred boards with a clock on each face, a verdigris cap, a vane.
    CB, CZ0, CZ1 = 1.3, ZR - 0.5, ZR + 1.35
    put(k, box((-CB, -CB, CZ0), (CB, CB, CZ1)), lambda co, n, c=jit(on(P.oldlime, "wood"), rng, 0.02): mix(c, P.drift, 0.5) if nz(co.x * 2 + co.y * 2, co.z * 3) > 0.25 else c)
    put(k, box((-CB - 0.12, -CB - 0.12, CZ1), (CB + 0.12, CB + 0.12, CZ1 + 0.14)), jit(P.pale, rng, 0.02))
    for n_ in (-Y, Y, X, -X):
        u_ = Z.cross(n_) * -1.0
        c = n_ * (CB + 0.02) + Z * (ZR + 0.7)
        ring = [c + (u_ * sin(i / 14 * TAU) + Z * cos(i / 14 * TAU)) * 0.56 for i in range(14)]
        raw(k, [(oriented(ring, n_), jit(on(P.lime, "plaster"), rng, 0.015))])
        ring2 = [c + n_ * -0.005 + (u_ * sin(i / 14 * TAU) + Z * cos(i / 14 * TAU)) * 0.64 for i in range(14)]
        raw(k, [(oriented(ring2, n_), P.iron)])
        for ang, L, wd in ((rad(125), 0.3, 0.035), (rad(60), 0.46, 0.025)):  # ten past four
            d = u_ * sin(ang) + Z * cos(ang)
            put(k, beam(c + n_ * 0.02 - d * 0.06, c + n_ * 0.02 + d * L, wd, 0.02, up=n_), P.iron)
        raw(k, [(oriented([c + n_ * 0.012 + (u_ * sin(i / 12 * TAU) + Z * cos(i / 12 * TAU)) * 0.47 + s_ for s_ in (u_ * -0.015 + Z * -0.03, u_ * 0.015 + Z * -0.03, u_ * 0.015 + Z * 0.03, u_ * -0.015 + Z * 0.03)], n_), P.iron) for i in range(12)])
    M = Matrix.Rotation(rad(45), 4, "Z")
    cap = [(CB * 1.5, CZ1 + 0.14), (CB * 1.32, CZ1 + 0.42), (CB * 0.8, CZ1 + 0.8), (0.3, CZ1 + 1.15), (0.12, CZ1 + 1.25)]
    put(k, lathe(cap, 4, M), lambda co, n, c=jit(P.verdigris, rng, 0.02): mix(c, P.tar, 0.3 * max(0.0, nz(co.x * 1.5, co.y * 1.5, co.z))))
    top = lot["height_m"]
    put(k, tube([(0, 0, CZ1 + 1.2), (0, 0, top)], 0.035, 5), P.iron)
    put(k, sphere((0, 0, CZ1 + 1.36), 0.12, 1), jit(P.verdigris, rng, 0.02))
    vane = env.ne  # the vane points down the wind
    raw(k, [([Vector((0, 0, top - 0.2)) - vane * 0.4, Vector((0, 0, top - 0.2)) + vane * 0.5, Vector((0, 0, top - 0.08)) + vane * 0.2, Vector((0, 0, top - 0.08)) - vane * 0.4], mix(P.iron, P.verdigris, 0.4))], two=True)
    found(k, 1.8)
    return dict(ridge_m=top, arches=7, bay_m=round(pitch, 3), arch_crown_m=round(ZS + (pitch - PW) / 2, 2), clock="ten past four")


def gen_watchglass(k, rng, lot):
    """The Watchglass: the harbour light at the tip of the mole. A squat eight-sided tower, basalt
    below and limewash above, with a lantern room too big for it: 5 m across on a 4 m shaft,
    glazed in small panes set in facets, one band of them cobalt, under a verdigris cap. Lit every
    night. It stands in the sea's spray on every side: bloom, rust under its ironwork, lime gone
    from the faces the south-westerly strikes."""
    w, env, H = lot["wear"], Env(lot), lot["height_m"]
    K = 1 / cos(PI / 8)  # an octagon's corner radius over its flat radius
    ZB, ZG, ZL0, ZL1, ZC = 2.6, 9.6, 10.6, 14.0, 16.0
    spray = max(w["wind"], 0.6 * w["salt"])  # open to the sea all round

    def rflat(z):
        return 2.25 if z <= ZB else 2.25 - 0.25 * (z - ZB) / (ZG - ZB)

    def op(az, r, z):
        """A point on an octagon of flat radius r: azimuth az from the front (-Y) towards +X."""
        i = math.floor(az / (PI / 4) + 0.5)
        d = az - i * PI / 4
        rr = r / cos(d)
        return Vector((rr * sin(az), -rr * cos(az), z))

    def shaft(co, n):
        z = co.z
        ex = env.weather(n) * (0.4 + spray)
        if z < ZB:
            c = jit(P.basalt, rng, 0.02)
            if z < 0.9:
                return mix(c, P.kelp, 0.35 * w["salt"] * max(0.0, 1 - z / 0.9))
            return mix(c, P.pale, 0.6 * w["salt"]) if nz(co.x * 0.9, co.y * 0.9, z * 1.4) > 0.15 else c
        c = jit(P.oldlime, rng, 0.012)
        f = nz(co.x * 0.8, co.y * 0.8, z * 0.55 + 3.0)
        if f > 0.5 - 0.75 * ex:
            c = mix(c, P.basalt, 0.55) if f > 0.72 - 0.75 * ex else mix(c, P.pale, 0.5)  # the lime gone, the stone showing
        if z > ZG - 2.2:  # rust runs down from the gallery's brackets
            c = mix(c, P.rust, 0.5 * max(0.0, nz(math.atan2(co.x, -co.y) * 9.0, 1.0)) * (z - (ZG - 2.2)) / 2.2 * w["salt"])
        return c
    SEG, zs = 32, [0.0, 0.45, 0.9, 1.5, 2.1, ZB] + [ZB + (ZG - ZB) * i / 14 for i in range(1, 15)]
    bm = bmesh.new()
    rings = [[bm.verts.new(op((i + 0.0) / SEG * TAU - PI / 8, rflat(z), z)) for i in range(SEG)] for z in zs]
    for lo, hi in zip(rings, rings[1:]):
        for i in range(SEG):
            bm.faces.new([lo[i], lo[(i + 1) % SEG], hi[(i + 1) % SEG], hi[i]])
    put(k, bm, shaft, closed=False)
    for z, c in ((ZB, P.pale), (0.0, P.pale)):
        put(k, lathe([(2.3 * K, z), (2.3 * K, z + 0.16)], 8, Matrix.Rotation(PI / 8, 4, "Z"), caps=(False, True)), jit(c, rng, 0.02), closed=False)
    # The door, to landward, and three slit lights climbing with the stair.
    ff = Face((0, -2.26, 0), X, 1.86)
    put(k, ff.box(-0.62, 0.62, 0.0, 2.5, -0.1, 0.03), jit(P.pale, rng, 0.02))
    plank_door(k, rng, ff, 0.0, 0.18, DOOR.get(lot.get("door_colour"), mix(P.seagreen, P.drift, 0.25)), recess=-0.03)
    put(k, ff.box(-0.7, 0.7, 0.0, 0.18, 0.0, 0.42), lambda co, n, c=jit(P.basalt, rng): mix(c, P.pale, 0.6) if n.z > 0.5 else c)
    for i, z in ((1, 4.3), (7, 6.2), (2, 7.9)):
        a = i * PI / 4
        r = rflat(z)
        nrm = Vector((sin(a), -cos(a), 0))
        fw = Face(nrm * (r + 0.005), Vector((cos(a), sin(a), 0)), 1.6)
        window(k, rng, fw, 0.0, z, (1, 3, 0.3, 0.32), glazing(rng, P.smoke, P.green, 1, CELLS(1, 3)), recess=-0.02, bars=P.iron)
    # The gallery: corbelled out on iron brackets, its deck and rail.
    RG = 2.9
    put(k, lathe([(rflat(ZG) * K, ZG - 0.5), (RG * K * 0.86, ZG - 0.12), (RG * K, ZG - 0.1), (RG * K, ZG + 0.06), (2.5 * K, ZG + 0.06)], 8, Matrix.Rotation(PI / 8, 4, "Z"), caps=(False, False)),
        lambda co, n, c=jit(P.pale, rng, 0.02): mix(c, P.rust, 0.35 * w["salt"]) if n.z < -0.2 else c, closed=False)
    for i in range(8):
        a = i * PI / 4 + PI / 8
        put(k, beam(op(a, rflat(ZG - 1.3), ZG - 1.3), op(a, RG - 0.1, ZG - 0.14), 0.07, 0.07), mix(P.iron, P.rust, 0.6 * w["salt"]))
    rail = [op(i * PI / 4 + PI / 8, RG - 0.12, ZG + 0.06) for i in range(9)]
    iron_rail(k, rng, rail, h=1.0)
    # The lantern room: a low wall, then eight faces of panes, each set in two facets.
    RL_ = 2.5
    put(k, lathe([(RL_ * K, ZG + 0.06), (RL_ * K, ZL0)], 8, Matrix.Rotation(PI / 8, 4, "Z"), caps=(False, False)), lambda co, n, c=jit(on(P.oldlime, "metal"), rng, 0.02): mix(c, P.rust, 0.5 * max(0.0, nz(co.x * 3, co.y * 3, co.z * 2))), closed=False)
    fw_ = 2 * RL_ * math.tan(PI / 8)
    NU, NV = 5, 8
    cu, cv = fw_ / NU, (ZL1 - ZL0) / NV
    band = 5  # the one band of cobalt
    for i in range(8):
        a = i * PI / 4
        nrm, tan = Vector((sin(a), -cos(a), 0)), Vector((cos(a), sin(a), 0))
        o = nrm * RL_ - tan * (fw_ / 2) + Z * ZL0

        def pt(u, v, ww, o=o, nrm=nrm, tan=tan):
            return o + tan * u + Z * v + nrm * (ww + 0.14 * (1 - abs(2 * u / fw_ - 1)))
        raw(k, [([pt(0, 0, -0.012), pt(fw_ / 2, 0, -0.012), pt(fw_ / 2, ZL1 - ZL0, -0.012), pt(0, ZL1 - ZL0, -0.012)], P.iron), ([pt(fw_ / 2, 0, -0.012), pt(fw_, 0, -0.012), pt(fw_, ZL1 - ZL0, -0.012), pt(fw_ / 2, ZL1 - ZL0, -0.012)], P.iron)])
        odd_at = set(rng.sample([c for c in CELLS(NU, NV) if c[1] != band], 1 + round(3 * (1 - w["repair"]))))
        shade = {c: jit(P.smoke if c in odd_at else P.aqua, rng, 0.025) for c in CELLS(NU, NV)}
        pane_grid(k, rng, pt, NU, NV, cu, cv, lambda ci, cj: None if cj == band else shade[(ci, cj)], bar=0.05, glow="GlowCyan", lift=0.004)
        pane_grid(k, rng, pt, NU, NV, cu, cv, lambda ci, cj: jit(P.cobalt, rng, 0.02) if cj == band else None, bar=0.05, lift=0.004)
        put(k, beam(o - nrm * 0.0, o + Z * (ZL1 - ZL0), 0.09, 0.09, up=nrm), P.iron)
    # The cap: verdigris copper over the lamp, sooted downwind of its vent; a ball and a rod.
    cap = [(RL_ * K + 0.3, ZL1 - 0.05), (RL_ * K + 0.3, ZL1 + 0.1), (RL_ * K * 0.82, ZL1 + 0.55), (RL_ * K * 0.5, ZL1 + 1.2), (0.5, ZC - 0.25), (0.34, ZC)]
    put(k, lathe(cap, 8, Matrix.Rotation(PI / 8, 4, "Z")), lambda co, n, c=jit(P.verdigris, rng, 0.02): mix(mix(c, P.tar, 0.55 * max(0.0, Vector((co.x, co.y, 0)).normalized().dot(env.ne)) * max(0.0, (co.z - ZL1 - 0.4) / 1.6)), P.pale, 0.25 * max(0.0, nz(co.x, co.y, co.z * 2))))
    put(k, lathe([(RL_ * K + 0.3, ZL1 - 0.05), (RL_ * K - 0.1, ZL1 - 0.05)], 8, Matrix.Rotation(PI / 8, 4, "Z"), caps=(False, False)), P.iron, closed=False)
    put(k, lathe([(0.3, ZC), (0.42, ZC + 0.12), (0.42, ZC + 0.3), (0.2, ZC + 0.42)], 8), mix(P.iron, P.tar, 0.5))
    put(k, tube([(0, 0, ZC + 0.4), (0, 0, H)], 0.03, 5), P.iron)
    put(k, sphere((0, 0, ZC + 0.62), 0.13, 1), jit(P.verdigris, rng, 0.02))
    found(k, 1.8)
    return dict(ridge_m=H, shaft_across_m=4.0, lantern_across_m=2 * RL_, panes=8 * NU * NV, cobalt_panes=8 * NU)


# ---------------------------------------------------------------------------------------------
# Export and report

# folder -> (generator, triangle budget). SMALL_CITY §6's budgets; ground pieces and dressing
# take the prop budgets of §7.
GEN = dict(
    cone=(gen_cone, 12000), glasshouse=(gen_glasshouse, 9000), counting_house=(gen_counting_house, 14000), watchglass=(gen_watchglass, 9000), row_house=(gen_house, 4000), net_loft=(gen_net_loft, 2500), marver=(gen_marver, 9000), marver_terrace=(gen_marver_terrace, 2500),
    retaining_wall=(gen_wall, 1500), stairs=(gen_stairs, 1500), quay=(gen_quay, 1500), mole=(gen_mole, 6000), plot_wall=(gen_plot_wall, 1500), fish_steps=(gen_fish_steps, 2500),
    net_rack=(gen_net_rack, 1500), barrels=(gen_barrels, 1500), creels=(gen_creels, 1500), bollard=(gen_bollard, 1500), quay_lamp=(gen_quay_lamp, 1500), boat=(gen_boat, 2500),
    peat_stack=(gen_peat_stack, 1500), floats=(gen_floats, 1500),
)
PALETTE = [tuple(v) for v in vars(P).values()]


def measure(obj):
    """What the checks need, measured from the finished mesh."""
    me = obj.data
    col = me.color_attributes["Color"].data
    tris = tagged_t = lit_t = on_pal = blend = 0
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
    above = [v.co for v in me.vertices if v.co.z >= 0.02]
    lo = [min(v[i] for v in above) for i in range(3)]
    hi = [max(v[i] for v in above) for i in range(3)]
    return dict(above_floor_m=[[round(lo[0], 3), round(lo[1], 3)], [round(hi[0], 3), round(hi[1], 3)]], height_m=round(hi[2], 3),
                foundation_m=round(-min(v.co.z for v in me.vertices), 3), tris=tris, materials=by_mat,
                surface_tagged_share=round(tagged_t / max(lit_t, 1), 4), palette_share=round(on_pal / tris, 4), palette_wear_blend_share=round(blend / tris, 4))


def _near_segment(c, a, b):
    c, a, b = Vector(c), Vector(a), Vector(b)
    t = min(1.0, max(0.0, (c - a).dot(b - a) / max((b - a).length_squared, 1e-9)))
    return max(abs(x) for x in (a.lerp(b, t) - c)) <= 0.056


def scale_figure(k, it, folder):
    """A 1.75 m figure beside a model, for the contact sheet: before its front, or on top of a
    piece of ground (a quay's coping, the mole, a landing)."""
    hw, hd = it["size"][0] / 2, it["size"][1] / 2
    at = {"quay": (0.9, hd - 0.4), "mole": (0.0, 0.0), "fish_steps": (1.5, 0.0), "marver_terrace": (2.0, 0.6)}.get(folder, (min(hw - 0.3, 1.6), -hd - 0.8))
    M = Matrix.Translation((at[0], at[1], 0.12 if folder in ("quay", "mole") else 0.05 if folder in ("fish_steps", "marver_terrace") else 0.0))
    c = on(P.drift, "cloth")
    for e in (-1, 1):
        put(k, lathe([(0.07, 0.0), (0.085, 0.5), (0.1, 0.9)], 8, M @ Matrix.Translation((e * 0.1, 0, 0))), c)
        put(k, lathe([(0.045, 0.82), (0.055, 1.2), (0.065, 1.42)], 6, M @ Matrix.Translation((e * 0.25, 0, 0))), c)
    put(k, lathe([(0.2, 0.86), (0.17, 1.1), (0.21, 1.4), (0.13, 1.47), (0.06, 1.5)], 10, M), c)
    put(k, moved(sphere((0, 0, 0), 0.115, 1), M @ Matrix.Translation((0, 0, 1.635))), on(P.oldlime, "cloth"))


# ---------------------------------------------------------------------------------------------
# Layout pass 1 (docs/CULLET_LAYOUT.md): enclosures. What stands between the Rows, in the old
# house plots, behind the quay's buildings and in the Ladder's corners. The plan writes each one
# out (cullet_plan.py `enclosure`): its walls (where, how high, of what make, with which gaps)
# and its contents (what, where), every one with its cause. This builds exactly that, and rolls
# only for which stone is a shade darker or which way a hen looks.
# An enclosure faces south, so its own frame is the plan's: +X east, +Y north.


def e_M(at, turn=0.0, z=0.0):
    return Matrix.Translation((at[0], at[1], z)) @ Matrix.Rotation(rad(turn), 4, "Z")


def e_box(k, M, lo, hi, col, bevel=0.0, open_bottom=False):
    put(k, lbox(Vector(lo), Vector(hi), fn=lambda q: M @ q, bevel=bevel, open_bottom=open_bottom), col)


def e_soil(rng, t=0.25):
    return jit(mix(P.peat, P.kelp, t), rng, 0.02)


def e_wall(k, rng, env, wear, w, inward):
    """A free-standing wall along a line. `dry`: rough basalt, each stone its own height; `coped`:
    coursed, with a coping; `stub`: a pulled-down house's wall, falling from h to `low` along its
    length in broken steps, old limewash still on its inner face."""
    p0, p1 = Vector((*w["from"], 0.0)), Vector((*w["to"], 0.0))
    L = (p1 - p0).length
    t = (p1 - p0) / L
    n = Vector((-t.y, t.x, 0.0))
    if n.dot(inward) > 0:  # n looks out of the enclosure
        n = -n
    h, style, th = w["h"], w["style"], w.get("th", 0.4)
    if style == "paling":  # layout pass 2: a fence of hull planks
        return e_paling(k, rng, env, wear, w, n)
    low = w.get("low", h)
    gaps = sorted(w.get("gaps", []))
    runs, a = [], 0.0
    for g0, g1 in gaps:
        if g0 - a > 0.25:
            runs.append((a, g0))
        a = g1
    if L - a > 0.25:
        runs.append((a, L))
    lich_out = env.weather(n) * (0.3 + wear["wind"])
    soot = wear["soot"]
    course = 0.42 if style == "dry" else 0.36
    polys = []
    for r0, r1 in runs:
        m = max(1, round((r1 - r0) / (1.05 if style != "coped" else 1.2)))
        hs = []
        for i in range(m):
            f = (r0 + (r1 - r0) * (i + 0.5) / m) / L
            if style == "stub":
                hh = low + (h - low) * (1 - f) ** 1.5 + rng.uniform(-0.18, 0.18)
            elif style == "dry":
                hh = h * rng.uniform(0.9, 1.0) * (1.0 - 0.25 * wear.get("empty_top", 0.0) * rng.random())
            else:
                hh = h - 0.12
            hs.append(max(0.3, hh))
        for i in range(m):  # layout pass 2: where the plan says a wall has slumped, it stands half its height
            mid = r0 + (r1 - r0) * (i + 0.5) / m
            if any(u <= mid <= v for u, v in w.get("slumps", ())):
                hs[i] = max(0.3, hs[i] * rng.uniform(0.35, 0.55))
        for i in range(m):
            a0, a1, hh = r0 + (r1 - r0) * i / m, r0 + (r1 - r0) * (i + 1) / m, hs[i]
            rows = max(1, round(hh / course))
            for side, nn in ((1, n), (-1, -n)):
                o = p0 + nn * (th / 2)
                for j in range(rows):
                    za, zb = hh * j / rows, hh * (j + 1) / rows
                    b0 = a0 + (0.0 if j % 2 == 0 or i == 0 else -0.3 * (a1 - a0))
                    b1 = a1 + (0.0 if j % 2 == 0 or i == m - 1 else -0.3 * (a1 - a0))
                    c = jit(P.basalt if rng.random() < 0.72 else P.pale, rng, 0.03)
                    if soot > 0.05:
                        c = mix(c, P.tar, 0.4 * soot)
                    elif side > 0 and lich_out > 0.25 and rng.random() < lich_out * 0.5 and zb > 0.5:
                        c = mix(c, P.lichen, 0.35)
                    elif style == "stub" and side < 0 and za > 0.8 and nz((a0 + a1) * 0.4, za * 0.9, 3.0 + w["h"]) > -0.15:
                        c = jit(mix(P.oldlime, P.basalt, 0.25), rng, 0.02)  # the lost room's limewash
                    polys.append((oriented([o + t * b0 + Z * za, o + t * b1 + Z * za, o + t * b1 + Z * zb, o + t * b0 + Z * zb], nn), c))
            top = jit(mix(P.basalt, P.pale, 0.5), rng, 0.02)
            q = [p0 + t * a0 + n * (th / 2), p0 + t * a1 + n * (th / 2), p0 + t * a1 - n * (th / 2), p0 + t * a0 - n * (th / 2)]
            polys.append((oriented([v + Z * hh for v in q], Z), top))
            for e, an in ((a0, -t), (a1, t)):  # its ends, where they show: a run's end or a step
                nb = hs[i - 1] if an is not t and i > 0 else hs[i + 1] if an is t and i < m - 1 else 0.0
                if nb < hh - 0.03:
                    polys.append((oriented([p0 + t * e + n * (th / 2) + Z * nb, p0 + t * e - n * (th / 2) + Z * nb, p0 + t * e - n * (th / 2) + Z * hh, p0 + t * e + n * (th / 2) + Z * hh], an), jit(P.basalt, rng, 0.03)))
        if style == "coped":
            mc = max(1, round((r1 - r0) / 1.15))
            for i in range(mc):
                a0, a1 = r0 + (r1 - r0) * i / mc + 0.01, r0 + (r1 - r0) * (i + 1) / mc - 0.01
                put(k, lbox(Vector((a0, -th / 2 - 0.04, h - 0.12)), Vector((a1, th / 2 + 0.04, h * rng.uniform(0.995, 1.0))), fn=lambda q: p0 + t * q.x + n * q.y + Z * q.z, open_bottom=True), jit(P.pale, rng, 0.025))
    raw(k, polys)
    for u, v in w.get("slumps", ()):  # and its stones lie where they fell, on the lee side
        for i in range(max(3, round((v - u) * 1.6))):
            lee = Vector((*w["fall"], 0.0)) if w.get("fall") else -n
            q = p0 + t * rng.uniform(u, v) + lee * rng.uniform(th / 2 + 0.25, th / 2 + 1.0)
            sz = rng.uniform(0.13, 0.26)
            S = Matrix.Translation(q) @ Matrix.Rotation(rng.uniform(0, PI), 4, "Z")
            put(k, lbox(Vector((-sz, -sz * 0.7, 0)), Vector((sz, sz * 0.7, sz * 0.9)), fn=lambda q_, S=S: S @ q_, bevel=0.02, open_bottom=True), jit(P.basalt if i % 3 else P.pale, rng, 0.03))
    for g0, g1 in gaps:
        mid, gw = p0 + t * (g0 + g1) / 2, g1 - g0
        if w.get("gate"):  # a driftwood gate, a hand ajar
            gh = min(1.5, max(0.9, h * 0.8))
            hinge = p0 + t * (g0 + 0.06)
            d = (t * cos(rad(14)) - n * sin(rad(14))).normalized()
            for j in range(4):
                u0, u1 = (gw - 0.12) * j / 4 + 0.01, (gw - 0.12) * (j + 1) / 4 - 0.01
                put(k, lbox(Vector((u0, -0.02, 0.08)), Vector((u1, 0.02, gh + 0.05 * (j % 2))), fn=lambda q: hinge + d * q.x + Vector((-d.y, d.x, 0)) * q.y + Z * q.z), jit(P.drift, rng, 0.03))
            put(k, beam(hinge + Z * 0.3, hinge + d * (gw - 0.14) + Z * (gh - 0.2), 0.035, 0.08, up=Vector((-d.y, d.x, 0))), jit(mix(P.drift, P.tar, 0.3), rng, 0.02))
        elif w.get("boarded"):
            for j in range(3):
                put(k, beam(mid - t * (gw / 2 + 0.15) + Z * (0.4 + 0.5 * j), mid + t * (gw / 2 + 0.15) + Z * (0.45 + 0.5 * j + 0.06 * (j % 2)), 0.03, 0.16, up=n), jit(P.tar, rng, 0.02))


def c_privy(k, rng, M, o, f):
    """A privy against the wall: tarred boards, a slate lid falling to the back, a plank door."""
    for (x0, x1, y0, y1) in ((-0.55, -0.5, -0.6, 0.6), (0.5, 0.55, -0.6, 0.6), (-0.55, 0.55, 0.55, 0.6)):
        e_box(k, M, (x0, y0, 0), (x1, y1, 1.95), jit(P.tar, rng, 0.025))
    e_box(k, M, (-0.5, -0.6, 0), (-0.3, -0.56, 1.95), jit(P.tar, rng, 0.025))
    e_box(k, M, (0.3, -0.6, 0), (0.5, -0.56, 1.95), jit(P.tar, rng, 0.025))
    e_box(k, M, (-0.3, -0.62, 0.06), (0.3, -0.58, 1.85), jit(P.drift, rng, 0.03))
    roof = [M @ Vector(q) for q in ((-0.68, -0.75, 2.22), (0.68, -0.75, 2.22), (0.68, 0.66, 1.94), (-0.68, 0.66, 1.94))]
    raw(k, [(oriented(roof, Z), jit(P.slate, rng)), (oriented([v - Z * 0.05 for v in roof], -Z), jit(P.tar, rng, 0.02)),
            (oriented([roof[0], roof[1], roof[1] - Z * 0.3, roof[0] - Z * 0.3], M.to_3x3() @ -Y), jit(P.tar, rng, 0.02))])


def c_lean_to(k, rng, M, o, f, boat=False):
    """A lean-to against the house's back wall: tarred boards under a slate lid; or, for a
    fisher, a low shed roofed with an upturned boat."""
    w = o.get("w", 2.4)
    hw = w / 2
    if boat:
        for x0, x1, y0, y1 in ((-hw, hw, 0.5, 0.56), (-hw, -hw + 0.06, -0.6, 0.56), (hw - 0.06, hw, -0.6, 0.56)):
            e_box(k, M, (x0, y0, 0), (x1, y1, 1.0), jit(P.tar, rng, 0.025))
        e_box(k, M, (-0.35, 0.56, 0.05), (0.35, 0.6, 0.95), jit(P.drift, rng, 0.03))
        bm = sphere((0, 0, 0), 1.0, 2)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.01], context="VERTS")
        for v in bm.verts:
            v.co = M @ Vector((v.co.x * (hw + 0.25) * (1 - 0.25 * abs(v.co.y)), v.co.y * 0.78, 0.98 + v.co.z * 0.85))
        put(k, bm, lambda co, n, c=jit(P.tar, rng, 0.02): mix(c, P.drift, 0.3) if n.z > 0.75 else c, closed=False)
        put(k, beam(M @ Vector((-hw - 0.2, 0, 1.86)), M @ Vector((hw + 0.2, 0, 1.86)), 0.07, 0.08), jit(mix(P.tar, P.drift, 0.6), rng, 0.02))
        return
    for x0, x1, y0, y1 in ((-hw, hw, 0.62, 0.68), (-hw, -hw + 0.06, -0.7, 0.68), (hw - 0.06, hw, -0.7, 0.68)):
        e_box(k, M, (x0, y0, 0), (x1, y1, 1.7), jit(P.tar, rng, 0.025))
    e_box(k, M, (-0.4, 0.68, 0.05), (0.4, 0.71, 1.6), jit(P.drift, rng, 0.03))
    roof = [M @ Vector(q) for q in ((-hw - 0.1, -0.72, 2.2), (hw + 0.1, -0.72, 2.2), (hw + 0.1, 0.82, 1.68), (-hw - 0.1, 0.82, 1.68))]
    raw(k, [(oriented(roof, Z), jit(P.slate if f.get("family") == "kiln" else P.tar, rng)), (oriented([v - Z * 0.05 for v in roof], -Z), jit(P.tar, rng, 0.02))])
    for e in (-1, 1):
        raw(k, [(oriented([M @ Vector((e * hw, -0.7, 1.7)), M @ Vector((e * hw, 0.68, 1.7)), M @ Vector((e * hw, -0.7, 2.14))], M.to_3x3() @ (X * e)), jit(P.tar, rng, 0.02))], two=True)


def c_peat(k, rng, M, o, f):
    """Peat for the hearth: stacks of cut turves, a tarred cloth weighted with stones."""
    n = o.get("n", 1)
    for i in range(n):
        x = (i - (n - 1) / 2) * 1.25
        hgt = 0.75 + 0.3 * ((i * 7 + f["seed"]) % 3) / 2
        rows = max(3, round(hgt / 0.16))
        for j in range(rows):
            ins = 0.015 * j
            e_box(k, M, (x - 0.55 + ins, -0.42 + ins, hgt * j / rows), (x + 0.55 - ins, 0.42 - ins, hgt * (j + 1) / rows - 0.012), jit(P.peat if j % 2 else mix(P.peat, P.grass, 0.12), rng, 0.03), open_bottom=True)
        e_box(k, M, (x - 0.6, -0.47, hgt - 0.01), (x + 0.6, 0.47, hgt + 0.04), on(jit(P.tar, rng, 0.02), "cloth"))
        e_box(k, M, (x - 0.5, -0.4, hgt + 0.04), (x - 0.3, -0.22, hgt + 0.13), jit(P.pale, rng, 0.03))


def c_butt(k, rng, M, o, f):
    """A rain butt under the eave: a coopered cask, dark water to its brim."""
    barrel(k, rng, None, 0.36, 0.95, wood=P.drift, M=M, salt=0.0, head=False, sides=8, hoops=(0.2, 0.8))
    raw(k, [([M @ Vector((cos(i / 8 * TAU) * 0.3, sin(i / 8 * TAU) * 0.3, 0.86)) for i in range(8)], mix(P.smoke, P.tar, 0.6))])


CLOTH = dict(linen=("lime", "oldlime", "lime", "oldlime", "sand"), colours=("chalkblue", "oldlime", "oxblood", "lime", "mustard", "seagreen", "oldlime"), smoke=("smoke", "oldlime", "smoke"))


def c_washing(k, rng, M, o, f, env=None):
    """A line of washing between two poles (or two walls, across a wynd), blown north-east."""
    a, b = Vector((0, 0, 0)), Vector((o["to"][0] - o["_at"][0], o["to"][1] - o["_at"][1], 0.0))
    L = b.length
    t = b / L
    top = 3.5 if o.get("high") else 2.6 if o.get("tall") else 2.2
    if not o.get("high"):
        for q in (a, b):
            put(k, tube([M @ q, M @ (q + Z * (top + 0.1))], [0.05, 0.035], 5), jit(P.drift, rng))
    blow = env.ne * 0.16 if env else Vector((0.11, 0.11, 0))
    def line(s):
        return a + t * (L * s) + Z * (top - 0.14 * sin(PI * s))
    put(k, tube([M @ line(i / 6) for i in range(7)], 0.012, 3, caps=False), on(P.sand, "cloth"), closed=False)
    names = CLOTH[o.get("cloth", "linen")]
    polys, s, i = [], 0.35 / L, 0
    while s < 1 - 0.75 / L:
        wd = rng.uniform(0.45, 0.85) if o.get("cloth") != "linen" else rng.uniform(0.7, 1.25)
        hg = rng.uniform(0.5, 0.95) if o.get("cloth") != "linen" else rng.uniform(0.9, 1.3)
        s1 = min(1 - 0.3 / L, s + wd / L)
        c = on(jit(mix(getattr(P, names[i % len(names)]), P.tar, 0.3) if o.get("cloth") == "smoke" and names[i % len(names)] == "oldlime" else getattr(P, names[i % len(names)]), rng, 0.02), "cloth")
        p0, p1 = line(s), line(s1)
        m0, m1 = p0 - Z * hg * 0.5 + blow * 0.5, p1 - Z * hg * 0.5 + blow * 0.5
        e0, e1 = p0 - Z * hg + blow * 1.6, p1 - Z * hg + blow * 1.6
        polys += [([M @ p0, M @ p1, M @ m1, M @ m0], c), ([M @ m0, M @ m1, M @ e1, M @ e0], mix(c, P.tar, 0.06))]
        s, i = s1 + rng.uniform(0.12, 0.3) / L, i + 1
    raw(k, polys, two=True)


def c_hens(k, rng, M, o, f):
    """A hen run: a tarred coop on legs with a ramp, stakes and rails round the run, the hens."""
    w, d, n = o.get("w", 4.0), o.get("d", 4.0), o.get("n", 5)
    hw, hd = w / 2, d / 2
    cx, cy = -hw + 0.8, hd - 0.7
    for ex in (-1, 1):
        for ey in (-1, 1):
            e_box(k, M, (cx + ex * 0.5 - 0.04, cy + ey * 0.4 - 0.04, 0), (cx + ex * 0.5 + 0.04, cy + ey * 0.4 + 0.04, 0.4), jit(P.drift, rng))
    e_box(k, M, (cx - 0.6, cy - 0.5, 0.4), (cx + 0.6, cy + 0.5, 1.0), jit(P.tar, rng, 0.025))
    roof = [M @ Vector(q) for q in ((cx - 0.72, cy - 0.62, 1.0), (cx + 0.72, cy - 0.62, 1.0), (cx + 0.72, cy + 0.6, 1.28), (cx - 0.72, cy + 0.6, 1.28))]
    raw(k, [(oriented(roof, Z), jit(P.slate, rng)), (oriented([v - Z * 0.04 for v in roof], -Z), jit(P.tar, rng, 0.02))])
    raw(k, [([M @ Vector((cx + 0.1, cy - 0.5, 0.42)), M @ Vector((cx + 0.4, cy - 0.5, 0.42)), M @ Vector((cx + 0.4, cy - 1.25, 0.02)), M @ Vector((cx + 0.1, cy - 1.25, 0.02))], jit(P.drift, rng))], two=True)
    ring = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        m = max(2, round(math.hypot(x1 - x0, y1 - y0) / 1.3))
        for i in range(m):
            x, y = x0 + (x1 - x0) * i / m, y0 + (y1 - y0) * i / m
            put(k, tube([M @ Vector((x, y, 0)), M @ Vector((x + rng.uniform(-0.04, 0.04), y, 1.15 + rng.uniform(-0.08, 0.08)))], 0.03, 4), jit(P.drift, rng))
        for z in (0.45, 1.0):
            put(k, tube([M @ Vector((x0, y0, z)), M @ Vector((x1, y1, z))], 0.016, 3), jit(mix(P.drift, P.tar, 0.4), rng, 0.02))
    for i in range(n):
        x, y = rng.uniform(-hw + 0.4, hw - 0.4), rng.uniform(-hd + 0.3, hd - 1.5)
        H_ = M @ Matrix.Translation((x, y, 0)) @ Matrix.Rotation(rng.uniform(0, TAU), 4, "Z")
        c = jit((P.oldlime, P.newbrick, P.tar, P.oldlime, P.drift)[(i + f["seed"]) % 5], rng, 0.03)
        put(k, lathe([(0.02, 0.12), (0.11, 0.16), (0.13, 0.24), (0.09, 0.33), (0.02, 0.36)], 6, H_ @ Matrix.Scale(1.5, 4, X)), on(c, "cloth"))
        put(k, lathe([(0.02, 0.3), (0.06, 0.36), (0.05, 0.43), (0.01, 0.46)], 5, H_ @ Matrix.Translation((0.17, 0, 0))), on(c, "cloth"))
        raw(k, [([H_ @ Vector((0.19, -0.01, 0.46)), H_ @ Vector((0.19, 0.01, 0.46)), H_ @ Vector((0.17, 0, 0.51))], P.oxblood)], two=True)


def c_beds(k, rng, M, o, f, what="beds"):
    """Dug beds: ridges of dark soil fed with kelp, a row of greens on each. `herbs`: slate-edged
    squares of many greens; `flowers`: the same in bloom; `poor`: half of it weeds."""
    w, d = o.get("w", 4.0), o.get("d", 4.0)
    hw, hd = w / 2, d / 2
    if what == "beds":
        rows = max(2, round(d / 0.95))
        for i in range(rows):
            y = -hd + d * (i + 0.5) / rows
            put(k, prism([(-0.3, 0.0), (0.3, 0.0), (0.1, 0.17), (-0.1, 0.17)], -hw, hw, lambda a, s, z, y=y: M @ Vector((a, y + s, z))), e_soil(rng))
            m = max(3, round(w / 0.55))
            for j in range(m):
                if o.get("poor") and (i + j) % 2:
                    continue
                tuft(k, rng, M @ Vector((-hw + w * (j + 0.5) / m, y, 0.15)), 0.2, 0.26, P.kelp if o.get("poor") and j % 3 == 0 else LEAF, 4)
        return
    nx, ny = max(1, round(w / 2.2)), max(2, round(d / 2.0))
    herbs = (LEAF, P.grass, mix(P.grass, P.lime, 0.3), mix(P.green, P.smoke, 0.5), P.kelp)
    blooms = (P.heather, P.mustard, P.chalkblue, P.lime, P.oxblood)
    for i in range(nx):
        for j in range(ny):
            x0, x1 = -hw + w * i / nx + 0.25, -hw + w * (i + 1) / nx - 0.25
            y0, y1 = -hd + d * j / ny + 0.25, -hd + d * (j + 1) / ny - 0.25
            e_box(k, M, (x0, y0, 0), (x1, y1, 0.14), e_soil(rng, 0.15), open_bottom=True)
            for a0, a1, b0, b1 in ((x0 - 0.06, x1 + 0.06, y0 - 0.06, y0), (x0 - 0.06, x1 + 0.06, y1, y1 + 0.06), (x0 - 0.06, x0, y0, y1), (x1, x1 + 0.06, y0, y1)):
                e_box(k, M, (a0, b0, 0), (a1, b1, 0.2), jit(P.slate, rng, 0.03), open_bottom=True)
            kind = (i * 3 + j * 2 + f["seed"]) % 5
            m = max(3, round((x1 - x0) * (y1 - y0) / 0.42))
            for q in range(m):
                at = M @ Vector((rng.uniform(x0 + 0.15, x1 - 0.15), rng.uniform(y0 + 0.15, y1 - 0.15), 0.13))
                tuft(k, rng, at, 0.17, 0.3 + 0.12 * (kind % 3), herbs[kind], 4)
                if what == "flowers" and q % 2 == 0:
                    tuft(k, rng, at + Z * 0.22, 0.09, 0.14, blooms[(kind + q // 2) % 5], 3)


def c_boat(k, rng, M, o, f):
    """A boat keel up on two trestles: tarred, grey along the keel."""
    bm = sphere((0, 0, 0), 1.0, 2)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.01], context="VERTS")
    for v in bm.verts:
        s = v.co.x
        v.co = M @ Vector((s * 1.95, v.co.y * 0.68 * (1 - abs(s) ** 2.4) ** 0.5 + 0.0, 0.62 + v.co.z * 0.62 * (1 - 0.15 * s * s)))
    put(k, bm, lambda co, n, c=jit(P.tar, rng, 0.02), g=jit(mix(P.tar, P.drift, 0.4), rng, 0.02): g if n.z > 0.8 else c, closed=False)
    put(k, beam(M @ Vector((-1.9, 0, 1.24)), M @ Vector((1.9, 0, 1.24)), 0.06, 0.08), jit(mix(P.tar, P.drift, 0.6), rng, 0.02))
    for x in (-1.0, 1.0):
        put(k, beam(M @ Vector((x, -0.75, 0.56)), M @ Vector((x, 0.75, 0.56)), 0.1, 0.1), jit(P.drift, rng))
        for ey in (-1, 1):
            for ex in (-1, 1):
                put(k, beam(M @ Vector((x, ey * 0.6, 0.52)), M @ Vector((x + ex * 0.25, ey * 0.68, 0.0)), 0.07, 0.07, up=M.to_3x3() @ Y), jit(P.drift, rng))
    put(k, tube([M @ Vector((-1.6, 0.2, 0.64)), M @ Vector((1.5, 0.26, 0.64))], 0.03, 4), jit(P.drift, rng))


def c_nets(k, rng, M, o, f):
    """Nets drying: three poles and a rail, a tarred net hung over it, glass floats on its head."""
    L = o.get("len", 4.0)
    for x in (-L / 2, 0.0, L / 2):
        put(k, tube([M @ Vector((x, 0, 0)), M @ Vector((x, 0, 2.3))], [0.055, 0.04], 5), jit(P.drift, rng))
    put(k, tube([M @ Vector((-L / 2 - 0.2, 0, 2.2)), M @ Vector((L / 2 + 0.2, 0, 2.2))], 0.035, 4), jit(P.drift, rng))
    net = on(P.tar, "cloth")
    nu, nv = max(4, round(L / 0.42)), 4
    def node(i, j, e):
        v = j / nv
        return M @ Vector((-L / 2 + 0.15 + (L - 0.3) * i / nu, e * (0.05 + 0.32 * v ** 0.8), 2.2 - 1.75 * v * (1 if e < 0 else 0.6) - 0.05 * sin(i * 1.7)))
    polys = []
    for e in (-1, 1):
        for i in range(nu):
            for j in range(nv):
                if (i * 5 + j * 3 + f["seed"]) % 17 == 0:
                    continue  # a tear
                a, b = (node(i, j, e), node(i + 1, j + 1, e)) if (i + j) % 2 == 0 else (node(i + 1, j, e), node(i, j + 1, e))
                side = (b - a).cross(M.to_3x3() @ Y).normalized()
                polys += [(q, jit(net, rng, 0.02)) for q in ribbon([a, b], 0.03, side)]
                a2, b2 = (node(i + 1, j, e), node(i, j + 1, e)) if (i + j) % 2 == 0 else (node(i, j, e), node(i + 1, j + 1, e))
                polys += [(q, jit(net, rng, 0.02)) for q in ribbon([a2, b2], 0.03, (b2 - a2).cross(M.to_3x3() @ Y).normalized())]
    raw(k, polys, two=True)
    for i, c in ((1, P.green), (nu // 2, P.amber), (nu - 1, P.aqua)):
        put(k, sphere(node(i, 0, -1) + Vector((0, 0, 0.1)), 0.11, 1), jit(c, rng, 0.03))


def c_kelp(k, rng, M, o, f):
    """Wrack: a heap for the beds, or hung over a driftwood rack to dry for the kilns."""
    L = o.get("len", 1.6)
    at = M @ Vector((0, 0, 0))
    if o.get("rack"):
        for x in (-L / 2, L / 2):
            for e in (-1, 1):
                put(k, tube([M @ Vector((x, e * 0.3, 0)), M @ Vector((x, 0, 1.05))], 0.035, 4), jit(P.drift, rng))
        put(k, tube([M @ Vector((-L / 2 - 0.15, 0, 1.03)), M @ Vector((L / 2 + 0.15, 0, 1.03))], 0.03, 4), jit(P.drift, rng))
        polys = []
        m = max(4, round(L / 0.22))
        for i in range(m):
            x = -L / 2 + L * (i + 0.5) / m
            for e in (-1, 1):
                ln = rng.uniform(0.45, 0.85)
                pts = [M @ Vector((x + 0.03 * sin(j * 2.0 + i), e * (0.03 + 0.1 * j / 3), 1.05 - ln * j / 3)) for j in range(4)]
                polys += [(q, jit(P.kelp if (i + e) % 3 else mix(P.kelp, P.tar, 0.35), rng, 0.03)) for q in ribbon(pts, rng.uniform(0.1, 0.17), M.to_3x3() @ X)]
        raw(k, polys, two=True)
        return
    bm = sphere((0, 0, 0), 1.0, 1)
    for v in bm.verts:
        b = 1 + 0.25 * nz(v.co.x * 2.1 + at.x, v.co.y * 2.1 + at.y, v.co.z * 2.1)
        v.co = M @ Vector((v.co.x * L * 0.32 * b, v.co.y * L * 0.26 * b, max(-0.02, v.co.z) * min(0.6, 0.3 * L) * b))
    put(k, bm, lambda co, n: mix(P.kelp, P.tar, 0.25 + 0.25 * nz(co.x * 6, co.y * 6, co.z * 6)), soft=at)
    kelp(k, rng, at, 7, L * 0.45)
    if o.get("fork"):
        tip = M @ Vector((L * 0.2, -L * 0.3, 0.25))
        put(k, tube([tip, tip + Vector((0.18, -0.25, 1.15))], 0.022, 4), jit(P.drift, rng))
        for e in (-1, 0, 1):
            put(k, tube([tip + Vector((e * 0.07, 0, 0.0)), tip + Vector((e * 0.07 - 0.04, 0.06, -0.26))], 0.01, 3), P.iron)


def c_frames(k, rng, M, o, f):
    """Cold frames: a driftwood box each, a sloping lid of small panes. Mended with boards and odd
    panes unless `whole` (the glazier's own)."""
    n = o.get("n", 2)
    for i in range(n):
        F = M @ Matrix.Translation(((i - (n - 1) / 2) * 1.6, 0, 0))
        wood = jit(P.drift, rng, 0.03)
        for x0, x1, y0, y1, z in ((-0.7, 0.7, -0.5, -0.45, 0.24), (-0.7, 0.7, 0.45, 0.5, 0.48), (-0.7, -0.65, -0.5, 0.5, 0.24), (0.65, 0.7, -0.5, 0.5, 0.24)):
            e_box(k, F, (x0, y0, 0), (x1, y1, z), wood, open_bottom=True)
        for e in (-1, 1):
            raw(k, [(oriented([F @ Vector((e * 0.675, -0.5, 0.24)), F @ Vector((e * 0.675, 0.5, 0.24)), F @ Vector((e * 0.675, 0.5, 0.48))], F.to_3x3() @ (X * e)), wood)], two=True)
        raw(k, [([F @ Vector((-0.65, -0.45, 0.05)), F @ Vector((0.65, -0.45, 0.05)), F @ Vector((0.65, 0.45, 0.05)), F @ Vector((-0.65, 0.45, 0.05))], e_soil(rng))])
        up = 0.32 if (i + f["seed"]) % 3 == 0 else 0.0  # one lid propped open
        polys = []
        for a in range(4):
            for b in range(3):
                x0, x1 = -0.68 + 1.36 * a / 4 + 0.02, -0.68 + 1.36 * (a + 1) / 4 - 0.02
                y0, y1 = -0.5 + 1.0 * b / 3 + 0.02, -0.5 + 1.0 * (b + 1) / 3 - 0.02
                z0, z1 = 0.26 + 0.24 * (y0 + 0.5) + up * (0.5 - y0), 0.26 + 0.24 * (y1 + 0.5) + up * (0.5 - y1)
                r = (a * 7 + b * 5 + i * 3 + f["seed"]) % 11
                c = jit(P.aqua, rng, 0.03) if o.get("whole") and r != 0 else jit((P.aqua, P.aqua, P.aqua, P.green, P.aqua, P.drift, P.aqua, P.amber, P.aqua, P.smoke, P.drift)[r], rng, 0.03)
                polys.append(([F @ Vector((x0, y0, z0)), F @ Vector((x1, y0, z0)), F @ Vector((x1, y1, z1)), F @ Vector((x0, y1, z1))], c))
        raw(k, polys, two=True)
        tuft(k, rng, F @ Vector((0.2, 0.0, 0.05)), 0.2, 0.2, LEAF, 4)


def c_slates(k, rng, M, o, f):
    """Slates stripped from the empty houses, stacked on edge by size, no two stacks one shade."""
    for i, (x, n, hgt) in enumerate(((-0.7, 7, 0.55), (0.1, 9, 0.42), (0.8, 5, 0.7))):
        for j in range(n):
            y = -0.35 + 0.1 * j
            S = M @ Matrix.Translation((x, y, 0)) @ Matrix.Rotation(rad(-12 + 2 * (j % 3)), 4, "X")
            e_box(k, S, (-0.3, -0.02, 0), (0.3, 0.02, hgt), jit((P.slate, P.newslate, P.slate, mix(P.slate, P.lichen, 0.25))[(i + j) % 4], rng, 0.03))


def c_blocks(k, rng, M, o, f):
    """Cut basalt never carried down: squared blocks, one on another, pale on the sawn faces."""
    for x, y, z, sx, sy, sz, tw in ((0.0, 0.0, 0.0, 1.2, 0.6, 0.5, 4), (0.75, 0.75, 0.0, 0.9, 0.55, 0.45, -18), (0.15, 0.05, 0.5, 0.9, 0.5, 0.4, 12), (-0.9, 0.6, 0.0, 0.6, 0.5, 0.35, 40)):
        S = M @ Matrix.Translation((x, y, z)) @ Matrix.Rotation(rad(tw), 4, "Z")
        put(k, lbox(Vector((-sx / 2, -sy / 2, 0)), Vector((sx / 2, sy / 2, sz)), fn=lambda q, S=S: S @ q, bevel=0.02, open_bottom=z == 0.0),
            lambda co, n, c=jit(P.basalt, rng, 0.03): mix(c, P.pale, 0.45) if n.z > 0.5 else c)


def c_pots(k, rng, M, o, f):
    """Otto Brandt's crucibles drying on a plank: island clay, paler as they dry."""
    for x in (-0.8, 0.8):
        e_box(k, M, (x - 0.12, -0.2, 0), (x + 0.12, 0.2, 0.4), jit(P.basalt, rng, 0.03), open_bottom=True)
    e_box(k, M, (-1.1, -0.22, 0.4), (1.1, 0.22, 0.45), jit(P.drift, rng, 0.03))
    for i in range(5):
        c = jit(mix(P.sand, P.newbrick, 0.25 + 0.1 * (i % 3)), rng, 0.02)
        put(k, lathe([(0.1, 0.45), (0.16, 0.6), (0.17, 0.78), (0.14, 0.86), (0.11, 0.86), (0.12, 0.6)], 8, M @ Matrix.Translation((-0.84 + 0.42 * i, 0, 0)), caps=(True, False)), c, closed=False)


def c_cullet(k, rng, M, o, f):
    """Ode Pontil's cullet: a crate a colour. As a `bed`: a border of lumps round dug ground, one
    of every glass the Cone has made, and the Rows' one piece of cobalt."""
    cols = (P.green, P.amber, P.aqua, P.smoke, P.green, P.aqua)
    if o.get("bed"):
        w, d = o.get("w", 3.6), o.get("d", 6.0)
        hw, hd = w / 2, d / 2
        e_box(k, M, (-hw + 0.3, -hd + 0.3, 0), (hw - 0.3, hd - 0.3, 0.1), e_soil(rng, 0.1), open_bottom=True)
        ring = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
        i = 0
        for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
            m = max(3, round(math.hypot(x1 - x0, y1 - y0) / 0.55))
            for j in range(m):
                c = P.cobalt if i == 5 else cols[(i * 5 + i // 3) % 6]
                put(k, sphere(M @ Vector((x0 + (x1 - x0) * j / m, y0 + (y1 - y0) * j / m, 0.1)), rng.uniform(0.12, 0.2), 1, squash=0.8), jit(c, rng, 0.03))
                i += 1
        for j in range(5):
            tuft(k, rng, M @ Vector((rng.uniform(-hw + 0.6, hw - 0.6), rng.uniform(-hd + 0.6, hd - 0.6), 0.1)), 0.2, 0.3, LEAF, 4)
        return
    for i in range(4):
        C = M @ Matrix.Translation((-0.95 + 0.63 * i, 0.0, 0.0))
        wood = jit(P.drift, rng, 0.03)
        for x0, x1, y0, y1 in ((-0.28, 0.28, -0.25, -0.22), (-0.28, 0.28, 0.22, 0.25), (-0.28, -0.25, -0.25, 0.25), (0.25, 0.28, -0.25, 0.25)):
            e_box(k, C, (x0, y0, 0), (x1, y1, 0.36), wood, open_bottom=True)
        bm = sphere((0, 0, 0), 1.0, 1)
        for v in bm.verts:
            v.co = C @ Vector((v.co.x * 0.24, v.co.y * 0.21, 0.3 + max(0.0, v.co.z) * 0.22))
        put(k, bm, jit(cols[(i + f["seed"]) % 4], rng, 0.03))


def c_timber(k, rng, M, o, f):
    """Timber seasoning for the Second Thought: planks on bearers, stickered; or ship's knees."""
    L = o.get("len", 3.6)
    if o.get("knees"):
        for i in range(3):
            K = M @ Matrix.Translation((-L / 2 + 0.6 + i * (L - 1.2) / 2, 0, 0)) @ Matrix.Rotation(rad(-20 + 25 * i), 4, "Z")
            c = jit(P.drift, rng, 0.04)
            put(k, beam(K @ Vector((0, 0, 0.08)), K @ Vector((0.9, 0, 0.08)), 0.16, 0.16), c)
            put(k, beam(K @ Vector((0.05, 0, 0.08)), K @ Vector((0.05, 0, 0.85)), 0.16, 0.16, up=K.to_3x3() @ Y), c)
        return
    for x in (-L / 2 + 0.4, 0.0, L / 2 - 0.4):
        e_box(k, M, (x - 0.07, -0.5, 0), (x + 0.07, 0.5, 0.12), jit(P.tar, rng, 0.02), open_bottom=True)
    for j in range(4):
        for i in range(3):
            e_box(k, M, (-L / 2 + 0.1 * (j % 2), -0.48 + 0.33 * i, 0.12 + 0.11 * j), (L / 2 - 0.15 * ((i + j) % 2), -0.48 + 0.33 * i + 0.29, 0.12 + 0.11 * j + 0.07), jit(P.drift if (i + j) % 3 else mix(P.drift, P.sand, 0.4), rng, 0.03))


def e_wheel(k, rng, c, axis, r):
    a = Vector(axis).normalized()
    put(k, B.cyl(Vector(c) - a * 0.03, Vector(c) + a * 0.03, r, r, 10), jit(mix(P.drift, P.tar, 0.35), rng, 0.02))


def c_handcart(k, rng, M, o, f):
    """Davin Vane's handcart: a flat bed on two wheels, its shafts on the ground."""
    T = M @ Matrix.Rotation(rad(-7), 4, "Y")
    e_box(k, T, (-0.8, -0.45, 0.5), (0.8, 0.45, 0.56), jit(P.drift, rng, 0.03))
    for y in (-0.45, 0.42):
        e_box(k, T, (-0.8, y, 0.56), (0.8, y + 0.03, 0.8), jit(P.drift, rng, 0.03))
    for e in (-1, 1):
        e_wheel(k, rng, M @ Vector((0.0, e * 0.52, 0.42)), M.to_3x3() @ Y, 0.42)
        put(k, beam(T @ Vector((0.75, e * 0.4, 0.5)), T @ Vector((1.8, e * 0.4, 0.5)), 0.05, 0.05), jit(P.drift, rng))


def c_barrow(k, rng, M, o, f):
    """A wheelbarrow: driftwood tray, one wheel."""
    c = jit(P.drift, rng, 0.03)
    e_box(k, M, (-0.35, -0.3, 0.3), (0.45, 0.3, 0.34), c)
    for y in (-0.3, 0.27):
        e_box(k, M, (-0.35, y, 0.34), (0.45, y + 0.03, 0.58), c)
    e_box(k, M, (0.42, -0.3, 0.34), (0.45, 0.3, 0.6), c)
    e_wheel(k, rng, M @ Vector((0.62, 0, 0.2)), M.to_3x3() @ Y, 0.2)
    for e in (-1, 1):
        put(k, beam(M @ Vector((0.62, e * 0.08, 0.2)), M @ Vector((-1.0, e * 0.3, 0.5)), 0.04, 0.05), c)
        put(k, beam(M @ Vector((-0.3, e * 0.26, 0.3)), M @ Vector((-0.36, e * 0.26, 0.0)), 0.04, 0.04, up=M.to_3x3() @ Y), c)


def c_barrels(k, rng, M, o, f):
    """Fish barrels, salt-crusted."""
    for x, y, hgt in ((-0.4, 0.0, 0.9), (0.38, 0.12, 0.95), (0.0, -0.62, 0.85)):
        barrel(k, rng, None, 0.3, hgt, M=M @ Matrix.Translation((x, y, 0)), salt=0.6, sides=8, hoops=(0.15, 0.85))


def c_creels(k, rng, M, o, f):
    for i, (x, y) in enumerate(((-0.3, 0.0), (0.35, 0.15))):
        creel(k, rng, M @ Matrix.Translation((x, y, 0)), fill=0.2 if i else None, sides=8, rows=4)


def c_bench(k, rng, M, o, f):
    """A bench: a plank (a boat's thwart) on two stones; on a sill, a back rail too."""
    L = o.get("len", 1.8)
    for x in (-L / 2 + 0.25, L / 2 - 0.25):
        e_box(k, M, (x - 0.14, -0.17, 0), (x + 0.14, 0.17, 0.4), jit(P.basalt, rng, 0.03), open_bottom=True)
    e_box(k, M, (-L / 2, -0.2, 0.4), (L / 2, 0.2, 0.46), jit(P.drift, rng, 0.03))
    if o.get("back"):
        e_ = -1 if o["back"] == "s" else 1
        for x in (-L / 2 + 0.2, L / 2 - 0.2):
            e_box(k, M, (x - 0.03, e_ * 0.2 - 0.03, 0.4), (x + 0.03, e_ * 0.2 + 0.03, 0.88), jit(P.drift, rng, 0.03))
        e_box(k, M, (-L / 2, e_ * 0.2 - 0.025, 0.7), (L / 2, e_ * 0.2 + 0.025, 0.88), jit(P.drift, rng, 0.03))


def c_weeds(k, rng, M, o, f):
    """Gone to weed: docks, nettles and moor grass, thick at the walls."""
    r = o.get("r", 1.5)
    for i in range(max(6, round(r * r * 5))):
        a, d = rng.uniform(0, TAU), r * rng.uniform(0.05, 1.0) ** 0.6
        big = i % 4 == 0
        tuft(k, rng, M @ Vector((cos(a) * d, sin(a) * d, 0)), 0.3 if big else 0.18, 0.62 if big else 0.3, (P.grass, mix(P.grass, P.kelp, 0.5), P.kelp, mix(P.grass, P.heather, 0.3))[i % 4], 5 if big else 4)


def c_rubble(k, rng, M, o, f):
    """What fell: a heap of wall stone, a rafter or two, broken slates."""
    r = o.get("r", 1.4)
    bm = sphere((0, 0, 0), 1.0, 2)
    at = M @ Vector((0, 0, 0))
    for v in bm.verts:
        b = 1 + 0.35 * nz(v.co.x * 2.6 + at.x, v.co.y * 2.6 + at.y, v.co.z * 2.6)
        v.co = M @ Vector((v.co.x * r * b, v.co.y * r * 0.8 * b, max(-0.02, v.co.z) * 0.6 * b))
    put(k, bm, lambda co, n, a=jit(P.basalt, rng, 0.02), b_=jit(P.pale, rng, 0.02): b_ if nz(co.x * 3.1, co.y * 3.1, co.z * 3.1) > 0.15 else a)
    for i in range(2):
        a = rng.uniform(0, PI)
        put(k, beam(M @ Vector((cos(a) * -r * 0.9, sin(a) * -r * 0.7, 0.15)), M @ Vector((cos(a) * r * 0.9, sin(a) * r * 0.7, 0.55 + 0.2 * i)), 0.12, 0.12), jit(mix(P.drift, P.tar, 0.4), rng, 0.03))
    raw(k, [([M @ Vector((x, y, 0.03)), M @ Vector((x + 0.3, y + 0.05, 0.03)), M @ Vector((x + 0.2, y + 0.26, 0.05))], jit(P.slate, rng, 0.03)) for x, y in ((r * 0.9, 0.3), (-r, -0.5), (0.2, r * 0.8), (r * 0.5, -r * 0.7))], two=True)


def c_hearth(k, rng, M, o, f):
    """A lost house's hearth, left standing when its walls came down: the breast and a stump of
    flue, sooted above the opening."""
    def col(co, n, c=jit(P.basalt, rng, 0.03)):
        q = M.inverted() @ co
        return mix(c, P.tar, 0.5) if q.z > 1.0 and abs(q.x) < 0.5 and q.y < 0 else mix(c, P.pale, 0.3) if n.z > 0.5 else c
    put(k, lbox(Vector((-0.85, -0.3, 0)), Vector((0.85, 0.3, 1.9)), fn=lambda q: M @ q, open_bottom=True), col)
    put(k, lbox(Vector((-0.5, -0.26, 1.9)), Vector((0.5, 0.3, 2.7)), fn=lambda q: M @ q, open_bottom=True), col)
    put(k, lbox(Vector((-0.34, -0.2, 2.7)), Vector((0.3, 0.3, 3.3)), fn=lambda q: M @ q, open_bottom=True), lambda co, n, c=jit(P.brick, rng, 0.03): c)
    raw(k, [([M @ Vector((-0.45, -0.31, 0.0)), M @ Vector((0.45, -0.31, 0.0)), M @ Vector((0.45, -0.31, 0.95)), M @ Vector((-0.45, -0.31, 0.95))], P.tar)])
    e_box(k, M, (-0.6, -0.36, 0.95), (0.6, -0.28, 1.12), jit(P.pale, rng, 0.02))


def c_paving(k, rng, M, o, f):
    """A court cleared to the setts: big worn flags, paler where feet cross to the oven."""
    w, d = o.get("w", 10.0), o.get("d", 8.0)
    nx, ny = max(2, round(w / 2.2)), max(2, round(d / 2.0))
    for i in range(nx):
        for j in range(ny):
            x0, x1, y0, y1 = -w / 2 + w * i / nx, -w / 2 + w * (i + 1) / nx, -d / 2 + d * j / ny, -d / 2 + d * (j + 1) / ny
            worn = j == 0 or abs((x0 + x1) / 2 - w * 0.28) < 1.6
            e_box(k, M, (x0 + 0.02, y0 + 0.02, 0.0), (x1 - 0.02, y1 - 0.02, 0.035 + 0.008 * rng.random()), jit(mix(P.basalt, P.pale, 0.75 if worn else 0.35), rng, 0.025), open_bottom=True)


def c_table(k, rng, M, o, f):
    """The bread board: a long plank table where loaves cool and roots wait their turn."""
    L = o.get("len", 3.0)
    for x in (-L / 2 + 0.3, L / 2 - 0.3):
        for e in (-1, 1):
            put(k, beam(M @ Vector((x, e * 0.3, 0)), M @ Vector((x, e * 0.08, 0.76)), 0.07, 0.07, up=M.to_3x3() @ X), jit(P.drift, rng))
    e_box(k, M, (-L / 2, -0.4, 0.76), (L / 2, 0.4, 0.82), jit(P.drift, rng, 0.03))
    for i in range(5):
        x = -L / 2 + 0.4 + i * (L - 0.8) / 4
        put(k, sphere(M @ Vector((x, 0.1 * (i % 2), 0.9)), 0.13, 1, squash=0.6), jit(mix(P.sand, P.amber, 0.45), rng, 0.02))


def c_sundial(k, rng, M, o, f):
    e_box(k, M, (-0.25, -0.25, 0), (0.25, 0.25, 0.12), jit(P.pale, rng, 0.02), open_bottom=True)
    put(k, lathe([(0.14, 0.12), (0.1, 0.5), (0.12, 0.9), (0.24, 0.96), (0.24, 1.0)], 8, M), jit(P.pale, rng, 0.02))
    raw(k, [([M @ Vector((0, -0.16, 1.0)), M @ Vector((0, 0.16, 1.0)), M @ Vector((0, 0.16, 1.16))], P.iron)], two=True)


def c_trough(k, rng, M, o, f):
    """A stone trough for rinsing roots, filled from the butts."""
    c = jit(P.basalt, rng, 0.03)
    for x0, x1, y0, y1 in ((-0.9, 0.9, -0.35, -0.25), (-0.9, 0.9, 0.25, 0.35), (-0.9, -0.8, -0.35, 0.35), (0.8, 0.9, -0.35, 0.35)):
        e_box(k, M, (x0, y0, 0), (x1, y1, 0.55), c, open_bottom=True)
    raw(k, [([M @ Vector((-0.8, -0.25, 0.45)), M @ Vector((0.8, -0.25, 0.45)), M @ Vector((0.8, 0.25, 0.45)), M @ Vector((-0.8, 0.25, 0.45))], mix(P.smoke, P.tar, 0.55))])


def c_ropewalk(k, rng, M, o, f):
    """A ropewalk: the jack and its wheel at one end, T-posts down the run to carry the strands,
    the traveller at the far end; three strands laid up between them."""
    L = math.hypot(o["to"][0] - o["_at"][0], o["to"][1] - o["_at"][1])
    wood = lambda: jit(P.drift, rng, 0.03)  # noqa: E731
    e_box(k, M, (-0.1, -0.45, 0), (0.1, 0.45, 1.25), wood())
    e_wheel(k, rng, M @ Vector((-0.16, 0, 0.95)), M.to_3x3() @ X, 0.42)
    put(k, tube([M @ Vector((-0.2, 0, 0.95)), M @ Vector((-0.34, 0, 0.95)), M @ Vector((-0.34, 0, 0.7))], 0.02, 4), P.iron)
    m = max(2, round(L / 4.6))
    for i in range(1, m):
        x = L * i / m
        put(k, tube([M @ Vector((x, 0, 0)), M @ Vector((x, 0, 1.3))], 0.05, 5), wood())
        put(k, beam(M @ Vector((x, -0.5, 1.3)), M @ Vector((x, 0.5, 1.3)), 0.06, 0.08), wood())
        for y in (-0.3, 0.0, 0.3):
            put(k, tube([M @ Vector((x, y, 1.33)), M @ Vector((x, y, 1.45))], 0.012, 3), wood())
    e_box(k, M, (L - 0.3, -0.4, 0), (L, 0.4, 0.12), wood())
    e_box(k, M, (L - 0.2, -0.05, 0.12), (L - 0.1, 0.05, 1.2), wood())
    rope = on(mix(P.sand, P.drift, 0.5), "cloth")
    for y in (-0.3, 0.0, 0.3):
        pts = [M @ Vector((0.1 + (L - 0.25) * i / (2 * m), y * (1 - 0.7 * (i / (2 * m)) ** 3), (1.15 if i % 2 else 1.34) if 0 < i < 2 * m else 1.1)) for i in range(2 * m + 1)]
        put(k, tube(pts, 0.014, 3, caps=False), jit(rope, rng, 0.02), closed=False)
    for i in range(3):
        put(k, lathe([(0.2, 0.0), (0.22, 0.08), (0.2, 0.16)], 8, M @ Matrix.Translation((1.2 + 0.5 * i, 0.9, 0.0)) ), jit(rope, rng, 0.02))


def c_wigwam(k, rng, M, o, f):
    """Canes tied at the top, a climber on them."""
    for i in range(5):
        a = i / 5 * TAU
        put(k, tube([M @ Vector((cos(a) * 0.45, sin(a) * 0.45, 0)), M @ Vector((cos(a) * 0.03, sin(a) * 0.03, 1.85))], 0.014, 3), jit(P.drift, rng))
        for z in (0.35, 0.8, 1.2):
            t = z / 1.85
            tuft(k, rng, M @ Vector((cos(a) * 0.45 * (1 - t), sin(a) * 0.45 * (1 - t), z)), 0.13, 0.16, LEAF, 3)


def c_stoop(k, rng, M, o, f):
    """A door step with no door: two worn stones."""
    w = o.get("w", 1.2)
    e_box(k, M, (-w / 2, -0.3, 0), (w / 2, 0.3, 0.16), jit(mix(P.basalt, P.pale, 0.6), rng, 0.02), open_bottom=True)
    e_box(k, M, (-w / 2 + 0.1, -0.05, 0.16), (w / 2 - 0.1, 0.3, 0.32), jit(mix(P.basalt, P.pale, 0.75), rng, 0.02), open_bottom=True)


def c_ash_sacks(k, rng, M, o, f):
    """Kelp ash in sacks, kept off the ground on a board."""
    e_box(k, M, (-0.8, -0.3, 0), (0.8, 0.3, 0.06), jit(P.drift, rng, 0.03), open_bottom=True)
    for i, (x, z) in enumerate(((-0.5, 0.06), (0.05, 0.06), (0.55, 0.06), (-0.2, 0.42))):
        bm = sphere((0, 0, 0), 1.0, 1)
        for v in bm.verts:
            v.co = M @ Vector((x + v.co.x * 0.27, v.co.y * 0.24, z + 0.2 + v.co.z * 0.2))
        put(k, bm, on(jit(mix(P.sand, P.smoke, 0.45), rng, 0.025), "cloth"))


CONTENT = dict(
    privy=c_privy, lean_to=c_lean_to, boat_shed=lambda k, rng, M, o, f: c_lean_to(k, rng, M, o, f, boat=True), peat=c_peat, butt=c_butt, hens=c_hens,
    beds=c_beds, herbs=lambda k, rng, M, o, f: c_beds(k, rng, M, o, f, "herbs"), flowers=lambda k, rng, M, o, f: c_beds(k, rng, M, o, f, "flowers"),
    boat=c_boat, nets=c_nets, kelp=c_kelp, frames=c_frames, slates=c_slates, blocks=c_blocks, pots=c_pots, cullet=c_cullet, timber=c_timber, handcart=c_handcart,
    barrels=c_barrels, creels=c_creels, bench=c_bench, weeds=c_weeds, rubble=c_rubble, hearth=c_hearth, paving=c_paving, table=c_table, sundial=c_sundial,
    trough=c_trough, ropewalk=c_ropewalk, barrow=c_barrow, wigwam=c_wigwam, stoop=c_stoop, ash_sacks=c_ash_sacks,
)


def gen_enclosure(k, rng, lot):
    """An enclosure of the plan: its walls and what stands in it, as written there."""
    env, wear_ = Env(lot), dict(lot["wear"])
    wear_["empty_top"] = 1.0 if lot.get("state") in ("empty, sound", "roofless shell") else 0.0
    for w in lot.get("walls", []):
        mid = (Vector((*w["from"], 0)) + Vector((*w["to"], 0))) / 2
        e_wall(k, rng, env, wear_, w, -mid if mid.length > 0.05 else Y)
    top = 0.3
    for c in lot.get("contents", []):
        o = dict(c, _at=c["at"])
        turn = o.get("turn", 0.0)
        if c["what"] == "ropewalk":
            turn = math.degrees(math.atan2(o["to"][1] - c["at"][1], o["to"][0] - c["at"][0]))
        M = e_M(c["at"], turn)
        if c["what"] == "washing":
            c_washing(k, rng, Matrix.Translation((c["at"][0], c["at"][1], 0)), o, lot, env)
        else:
            CONTENT[c["what"]](k, rng, M, o, lot)
    if not k.b.bm.verts:  # nothing written: a marker stone, so the model is never empty
        e_box(k, Matrix.Identity(4), (-0.1, -0.1, 0), (0.1, 0.1, 0.1), P.basalt)
    top = max(v.co.z for v in k.b.bm.verts)
    return dict(ridge_m=round(top, 3))


# The plan's enclosure kinds (one folder each, so the client and the checks tell them apart).
ENCLOSURES = dict(yard=3000, back_plot=3000, toft=3500, walled_garden=3500, oven_court=3500, drying_green=4000, wind_wall=1500, ladder_corner=1500,
                  ropewalk=1500, quarry_bench=1500, graveyard_wall=3000, sill=600, wynd_washing=600)
GEN.update({kind: (gen_enclosure, budget) for kind, budget in ENCLOSURES.items()})


# ---------------------------------------------------------------------------------------------
# Layout pass 2 (docs/CULLET_LAYOUT.md, "Pass 2"): the Crown's ground, the quarry and the
# Strand's working backs. As in pass 1 the plan writes every thing and its cause; this builds it.
# Parts that touch are set a few millimetres apart or run into each other, never face to face in
# one plane (the kit check's coplanar rule).

GLASS = dict(green=P.green, amber=P.amber, aqua=P.aqua, smoke=P.smoke, cobalt=P.cobalt)
GOOD_CLAY = on(mix(P.smoke, P.basalt, 0.32), "earth")  # the clay a crucible is made of, grey-blue while wet
ROCK, ROCK_PALE = on(P.basalt, "boulder"), on(P.pale, "boulder")  # living rock, not laid stone
ROPE = on(mix(P.sand, P.drift, 0.55), "cloth")
ASH = mix(P.pale, P.oldlime, 0.5)


def e_poly(k, M, pts, z0, z1, col, top=None):
    """A flat stone of any outline [(x, y)] from z0 to z1 (no bottom): its top and its sides."""
    n = len(pts)
    up = [M @ Vector((x, y, z1)) for x, y in pts]
    dn = [M @ Vector((x, y, z0)) for x, y in pts]
    polys = [(oriented(up, Z), top if top is not None else col)]
    cx, cy = sum(q[0] for q in pts) / n, sum(q[1] for q in pts) / n
    c = M @ Vector((cx, cy, (z0 + z1) / 2))
    for i in range(n):
        j = (i + 1) % n
        q = [dn[i], dn[j], up[j], up[i]]
        polys.append((oriented(q, (q[0] + q[1]) / 2 - c), col))
    raw(k, polys)


def e_paling(k, rng, env, wear, w, n):
    """A paling of hull planks (SMALL_CITY §1: hull planks are fences): tarred strakes set on
    end between two rails, their tops as the boat's sheer left them; a grey board where one was
    replaced. Gaps in it are gates of the same planks."""
    p0, p1 = Vector((*w["from"], 0.0)), Vector((*w["to"], 0.0))
    L = (p1 - p0).length
    t = (p1 - p0) / L
    h = w["h"]
    runs, a = [], 0.0
    for g0, g1 in sorted(w.get("gaps", [])):
        if g0 - a > 0.25:
            runs.append((a, g0))
        a = g1
    if L - a > 0.25:
        runs.append((a, L))
    for r0, r1 in runs:
        x = r0 + 0.02
        while x < r1 - 0.1:
            pw = min(rng.uniform(0.15, 0.23), r1 - 0.02 - x)
            ph = h * rng.uniform(0.9, 1.0) + 0.1 * sin(x * 0.9)
            c = jit(P.drift, rng, 0.03) if rng.random() < 0.12 else jit(P.tar, rng, 0.025)
            put(k, lbox(Vector((x, -0.015, 0.04)), Vector((x + pw, 0.015, ph)), fn=lambda q: p0 + t * q.x + n * q.y + Z * q.z), c)
            x += pw + rng.uniform(0.012, 0.035)
        for z in (0.38, h - 0.3):
            put(k, beam(p0 + t * r0 - n * 0.045 + Z * z, p0 + t * r1 - n * 0.045 + Z * z, 0.05, 0.08), jit(mix(P.drift, P.tar, 0.4), rng, 0.02))
        m = max(1, round((r1 - r0) / 2.2))
        for i in range(m + 1):
            q = p0 + t * (r0 + 0.06 + (r1 - r0 - 0.12) * i / m) - n * 0.12
            put(k, tube([q, q + Z * (h - 0.12)], 0.05, 5), jit(P.drift, rng, 0.03))
    for g0, g1 in w.get("gaps", []):
        if w.get("gate"):  # a gate of the same planks, a hand ajar
            hinge, gw = p0 + t * (g0 + 0.05), g1 - g0 - 0.1
            d = (t * cos(rad(16)) - n * sin(rad(16))).normalized()
            s = Vector((-d.y, d.x, 0))
            x = 0.0
            while x < gw - 0.08:
                pw = min(0.2, gw - x)
                put(k, lbox(Vector((x, -0.015, 0.08)), Vector((x + pw - 0.015, 0.015, h * 0.94)), fn=lambda q: hinge + d * q.x + s * q.y + Z * q.z), jit(P.tar, rng, 0.025))
                x += pw
            put(k, beam(hinge + s * 0.04 + Z * 0.3, hinge + d * gw + s * 0.04 + Z * (h - 0.35), 0.035, 0.08, up=s), jit(mix(P.drift, P.tar, 0.3), rng, 0.02))


def c_grave_row(k, rng, M, o, f):
    """A row of graves, each marked with a slab of the Cone's glass in a basalt socket (the bible,
    "Customs"). The plan gives every grave its glass and its state: `new` (six years: unweathered,
    the mound still humped), `kept`, `old` (lichen on the socket), `leaning`, `poor` (the lean
    years: small, dark, some broken off short)."""
    graves, L = o["graves"], o["len"]
    n = len(graves)
    small = o.get("small")
    for i, g in enumerate(graves):
        x = -L / 2 + L * (i + 0.5) / n
        st = g.get("state", "kept")
        glass = GLASS[g["glass"]]
        w, h, th = (0.28, 0.4, 0.06) if small else (0.4, 0.66 if st == "new" else 0.6, 0.075)
        if st == "poor":
            glass = mix(glass, P.tar, 0.32)
            if (i * 5 + f["seed"]) % 4 == 0:
                h *= 0.5  # broken off
        elif st in ("old", "leaning"):
            glass = mix(glass, P.pale, 0.18)  # weathered dull
        sock = jit(P.basalt if st != "new" else P.pale, rng, 0.03)
        if st in ("old", "leaning", "poor") and (i + f["seed"]) % 2:
            sock = mix(sock, P.lichen, 0.3)
        e_box(k, M, (x - w / 2 - 0.09, -0.15, 0.0), (x + w / 2 + 0.09, 0.15, 0.15), sock, open_bottom=True)
        lean_ = rad((9 + 4 * (i % 3)) * (1 if i % 2 else -1)) if st == "leaning" else rad(rng.uniform(-1.5, 1.5))
        S = M @ Matrix.Translation((x, 0, 0.1)) @ Matrix.Rotation(lean_, 4, "X")
        put(k, lbox(Vector((-w / 2, -th / 2, 0)), Vector((w / 2, th / 2, h)), fn=lambda q, S=S: S @ q, bevel=0.018), jit(glass, rng, 0.02))
        if o.get("mound"):  # the earth has not sunk yet: a hump before the marker, grassed over
            bm = sphere((0, 0, 0), 1.0, 2)
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.01], context="VERTS")
            for v in bm.verts:
                v.co = M @ Vector((x + v.co.x * 0.44, -1.2 + v.co.y * 0.95, v.co.z * 0.24))
            put(k, bm, lambda co, nn, c=jit(mix(P.peat, P.grass, 0.55), rng, 0.03): c, closed=False)


def c_ship_stones(k, rng, M, o, f):
    """The ship days' graves: round-headed basalt stones cut in the formal script of the carved
    lintels, a ledger slab before each. Lichened; one has fallen."""
    n, L = o.get("n", 6), o["len"]
    for i in range(n):
        x = -L / 2 + L * (i + 0.5) / n
        fallen = i == n - 2
        S = M @ Matrix.Translation((x, 0, 0)) @ (Matrix.Translation((0, -0.5, 0.1)) @ Matrix.Rotation(rad(-84), 4, "X") if fallen else Matrix.Rotation(rad(rng.uniform(-3, 3)), 4, "X"))
        w, h = 0.66, 1.02 + 0.08 * (i % 2)
        prof = [(-w / 2, 0.0), (w / 2, 0.0), (w / 2, h - 0.24), (w * 0.3, h - 0.07), (0.0, h), (-w * 0.3, h - 0.07), (-w / 2, h - 0.24)]
        c = jit(P.basalt, rng, 0.03)
        put(k, prism([(s, z) for s, z in prof], -0.07, 0.07, lambda a, s, z, S=S: S @ Vector((s, a, z))),
            lambda co, nn, c=c: mix(c, P.lichen, 0.3) if nz(co.x * 2.3, co.z * 2.3, 5.0 + co.y) > 0.2 else c)
        # The cut script: rows of short pale strokes on the face that looks south.
        strokes = []
        for r in range(4):
            z, xx = h - 0.36 - 0.12 * r, -w / 2 + 0.1
            while xx < w / 2 - 0.12:
                ww = rng.uniform(0.04, 0.1)
                strokes.append((oriented([S @ Vector((xx, -0.074, z)), S @ Vector((xx + ww, -0.074, z)), S @ Vector((xx + ww, -0.074, z + 0.05)), S @ Vector((xx, -0.074, z + 0.05))], S.to_3x3() @ -Y), jit(P.pale, rng, 0.02)))
                xx += ww + rng.uniform(0.02, 0.05)
        raw(k, strokes)
        if not fallen:
            e_box(k, M, (x - 0.4, -1.95, 0.0), (x + 0.4, -0.2, 0.09 + 0.02 * (i % 3)), jit(mix(P.basalt, P.pale, 0.3), rng, 0.03), open_bottom=True)


def c_steps(k, rng, M, o, f):
    """Three stone steps up a bank between two terraces, worn in the middle."""
    w, rise = o.get("w", 1.6), o.get("rise", 0.5)
    for i in range(3):
        y0 = -0.5 + 0.34 * i
        e_box(k, M, (-w / 2 + 0.03, y0, 0.0), (w / 2 - 0.03, y0 + 0.36 + (0.25 if i == 2 else 0.0), rise * (i + 1) / 3 + 0.02), jit(mix(P.basalt, P.pale, 0.55), rng, 0.025), open_bottom=True)


def c_apron(k, rng, M, o, f):
    """The cistern's apron: a ring of flags round the tank, worn hollow and pale on the side the
    town comes from (south)."""
    r0, r1, n = o["r0"], o["r1"], 26
    for i in range(n):
        a0, a1 = i / n * TAU + 0.012, (i + 1) / n * TAU - 0.012
        mid = (a0 + a1) / 2
        south = max(0.0, -sin(mid))  # 1 due south
        rm = r0 + (r1 - r0) * (0.45 + 0.1 * (i % 2))
        for ra, rb in ((r0, rm - 0.012), (rm + 0.012, r1 - 0.25 * (i % 3 == 0))):
            pts = [(cos(a0) * ra, sin(a0) * ra), (cos(a1) * ra, sin(a1) * ra), (cos(a1) * rb, sin(a1) * rb), (cos(a0) * rb, sin(a0) * rb)]
            e_poly(k, M, pts, 0.0, 0.05 - 0.02 * south * (ra == r0) + 0.006 * rng.random(), jit(mix(P.basalt, P.pale, 0.3 + 0.55 * south), rng, 0.025))


def c_dip_step(k, rng, M, o, f):
    """The dipping step: two worn stones against the tank's wall, where buckets are filled."""
    w = o.get("w", 2.2)
    e_box(k, M, (-w / 2, -0.5, 0.0), (w / 2, 0.42, 0.2), jit(mix(P.basalt, P.pale, 0.7), rng, 0.02), bevel=0.02, open_bottom=True)
    e_box(k, M, (-w / 2 + 0.35, 0.0, 0.0), (w / 2 - 0.35, 0.44, 0.42), jit(mix(P.basalt, P.pale, 0.6), rng, 0.02), bevel=0.02, open_bottom=True)


def c_buckets(k, rng, M, o, f):
    """Buckets and a yoke left on the apron: coopered, iron-hooped."""
    for i in range(o.get("n", 2)):
        Bm = M @ Matrix.Translation((0.55 * i - 0.3, 0.12 * (i % 2), 0.0))
        barrel(k, rng, None, 0.17, 0.3, wood=P.drift, M=Bm, head=False, sides=8, hoops=(0.2, 0.85))
        raw(k, [([Bm @ Vector((cos(j / 8 * TAU) * 0.13, sin(j / 8 * TAU) * 0.13, 0.24 if i else 0.05)) for j in range(8)], mix(P.smoke, P.tar, 0.55))])
    put(k, beam(M @ Vector((-0.7, -0.5, 0.05)), M @ Vector((0.7, -0.42, 0.05)), 0.07, 0.05), jit(P.drift, rng, 0.03))


def c_runnel(k, rng, M, o, f):
    """The overflow's runnel: a channel cut in the rock, two rows of edging stones, dark water
    and green growth between them."""
    b = Vector((o["to"][0] - o["_at"][0], o["to"][1] - o["_at"][1], 0.0))
    L = b.length
    t, s = b / L, Vector((-b.y, b.x, 0)) / L
    m = max(2, round(L / 1.3))
    wet = mix(P.smoke, P.tar, 0.6)
    for i in range(m):
        a0, a1 = L * i / m + 0.015, L * (i + 1) / m - 0.015
        for e in (-1, 1):
            q = [t * a0 + s * (e * 0.16), t * a1 + s * (e * 0.16), t * a1 + s * (e * 0.3), t * a0 + s * (e * 0.3)]
            e_poly(k, M, [(v.x, v.y) for v in q], 0.0, 0.06 + 0.02 * rng.random(), jit(mix(P.basalt, P.kelp, 0.3 + 0.25 * rng.random()), rng, 0.02))
        raw(k, [(oriented([M @ (t * (a0 - 0.015) - s * 0.16 + Z * 0.012), M @ (t * (a1 + 0.015) - s * 0.16 + Z * 0.012), M @ (t * (a1 + 0.015) + s * 0.16 + Z * 0.012), M @ (t * (a0 - 0.015) + s * 0.16 + Z * 0.012)], Z),
                 wet if i % 3 else mix(wet, P.kelp, 0.4))])


def c_slab(k, rng, M, o, f):
    """A basalt slab laid over the runnel where a path crosses it."""
    e_box(k, M, (-1.1, -0.55, 0.075), (1.1, 0.55, 0.16), jit(mix(P.basalt, P.pale, 0.6), rng, 0.02), bevel=0.02)


def c_tablet_bench(k, rng, M, o, f):
    """The tablets' bench: a long basalt slab on three stones against the Readers' House, the
    ship-day tablets laid out on it to be read in daylight: slate and fired clay, two leaning."""
    L, n = o.get("len", 4.2), o.get("tablets", 8)
    for x in (-L / 2 + 0.35, 0.0, L / 2 - 0.35):
        e_box(k, M, (x - 0.16, -0.2, 0.0), (x + 0.16, 0.2, 0.46), jit(P.basalt, rng, 0.03), open_bottom=True)
    e_box(k, M, (-L / 2, -0.26, 0.464), (L / 2, 0.26, 0.56), jit(mix(P.basalt, P.pale, 0.55), rng, 0.02), bevel=0.015)
    for i in range(n):
        x = -L / 2 + 0.3 + (L - 0.6) * i / (n - 1)
        c = jit((P.slate, mix(P.newbrick, P.sand, 0.25), P.slate, P.brick)[i % 4], rng, 0.03)
        if i in (2, n - 2):  # leaning on the wall behind
            S = M @ Matrix.Translation((x, 0.16, 0.565)) @ Matrix.Rotation(rad(-74), 4, "X")
        else:
            S = M @ Matrix.Translation((x, -0.02 + 0.03 * (i % 3), 0.565)) @ Matrix.Rotation(rad(rng.uniform(-9, 9)), 4, "Z")
        put(k, lbox(Vector((-0.15, -0.11, 0.0)), Vector((0.15, 0.11, 0.028)), fn=lambda q, S=S: S @ q), c)
        raw(k, [([S @ Vector((-0.11, -0.07 + 0.045 * r, 0.0312)), S @ Vector((0.1 - 0.03 * (r % 2), -0.07 + 0.045 * r, 0.0312)), S @ Vector((0.1 - 0.03 * (r % 2), -0.055 + 0.045 * r, 0.0312)), S @ Vector((-0.11, -0.055 + 0.045 * r, 0.0312))],
                 mix(c, P.lime, 0.5)) for r in range(4)])


def c_stools(k, rng, M, o, f):
    """Low stones in a half ring: the children's seats at lessons."""
    for i, (x, y) in enumerate(o["at_each"]):
        s = 0.19 + 0.02 * (i % 3)
        S = M @ Matrix.Translation((x, y, 0)) @ Matrix.Rotation(rad(17 * i), 4, "Z")
        put(k, lbox(Vector((-s, -s, 0.0)), Vector((s, s, 0.3 + 0.03 * (i % 2))), fn=lambda q, S=S: S @ q, bevel=0.03, open_bottom=True),
            lambda co, nn, c=jit(P.basalt, rng, 0.03): mix(c, P.pale, 0.5) if nn.z > 0.5 else c)


def c_sand_tray(k, rng, M, o, f):
    """A tray of white sand from the Sand Spit, to write in and smooth again: there is nothing to
    write on that is not kept."""
    for x in (-0.4, 0.4):
        e_box(k, M, (x - 0.1, -0.3, 0.0), (x + 0.1, 0.3, 0.36), jit(P.basalt, rng, 0.03), open_bottom=True)
    wood = jit(P.drift, rng, 0.03)
    e_box(k, M, (-0.6, -0.4, 0.364), (0.6, 0.4, 0.39), wood)
    for x0, x1, y0, y1 in ((-0.6, 0.6, -0.4, -0.36), (-0.6, 0.6, 0.36, 0.4), (-0.6, -0.56, -0.356, 0.356), (0.56, 0.6, -0.356, 0.356)):
        e_box(k, M, (x0, y0, 0.394), (x1, y1, 0.46), wood)
    raw(k, [([M @ Vector((-0.556, -0.356, 0.43)), M @ Vector((0.556, -0.356, 0.43)), M @ Vector((0.556, 0.356, 0.43)), M @ Vector((-0.556, 0.356, 0.43))], jit(P.sand, rng, 0.02))])
    raw(k, [([M @ Vector((-0.4 + 0.2 * i, -0.2, 0.4325)), M @ Vector((-0.34 + 0.2 * i, -0.2, 0.4325)), M @ Vector((-0.3 + 0.2 * i, 0.2, 0.4325)), M @ Vector((-0.36 + 0.2 * i, 0.2, 0.4325))], mix(P.sand, P.drift, 0.5)) for i in range(4)])


def c_spoil(k, rng, M, o, f):
    """A spoil heap: quarry waste tipped where the barrow run ended, a low cone of broken stone,
    angular and pale; an old one has gone to grass on top."""
    r, h = o.get("r", 2.4), o.get("h", 1.6)
    at = M @ Vector((0, 0, 0))
    grown = o.get("grown")
    a_, b_, g_ = jit(ROCK, rng, 0.02), jit(ROCK_PALE, rng, 0.02), jit(mix(P.grass, P.basalt, 0.35), rng, 0.02)
    n = 11
    rim = [M @ Vector((cos(i / n * TAU) * r * (1 + 0.16 * nz(i * 1.3, at.x, at.y)), sin(i / n * TAU) * r * 0.85 * (1 + 0.16 * nz(i * 1.9, at.y, at.x)), 0.0)) for i in range(n)]
    mid = [M @ Vector((cos((i + 0.5) / n * TAU) * r * 0.5, sin((i + 0.5) / n * TAU) * r * 0.42, h * (0.62 + 0.16 * nz(i * 2.1, at.x * 0.7, 2.0)))) for i in range(n)]
    top = M @ Vector((0.1 * r, -0.05 * r, h))
    polys = []
    for i in range(n):
        j_ = (i + 1) % n
        c1, c2 = (b_ if (i * 7) % 3 else a_), (a_ if (i * 5) % 3 else b_)
        polys += [([rim[i], rim[j_], mid[i]], c1), ([rim[j_], mid[j_], mid[i]], c2), ([mid[i], mid[j_], top], g_ if grown else (b_ if i % 2 else a_))]
    raw(k, polys)
    for i in range(16 if not grown else 5):  # broken stone on its flanks and round its foot
        a, t_ = rng.uniform(0, TAU), rng.uniform(0.35, 1.12)
        sz = rng.uniform(0.12, 0.3)
        S = M @ Matrix.Translation((cos(a) * r * t_, sin(a) * r * 0.85 * t_, max(0.0, h * 0.7 * (1 - t_) / 0.65 - 0.05) if t_ < 1 else 0.0)) @ Matrix.Rotation(rng.uniform(0, PI), 4, "Z") @ Matrix.Rotation(rng.uniform(-0.4, 0.4), 4, "X")
        put(k, lbox(Vector((-sz, -sz * 0.7, -0.05)), Vector((sz, sz * 0.7, sz * 0.8)), fn=lambda q, S=S: S @ q, bevel=0.02), jit(ROCK if i % 2 else ROCK_PALE, rng, 0.03))
    if grown:
        for i in range(8):
            a, d = rng.uniform(0, TAU), r * rng.uniform(0.2, 0.9)
            tuft(k, rng, M @ Vector((cos(a) * d, sin(a) * d * 0.85, h * max(0.0, 1 - d / r) * 0.75)), 0.24, 0.4, (P.grass, mix(P.grass, P.heather, 0.3))[i % 2], 4)


def c_crane_foot(k, rng, M, o, f):
    """The crane's standing: a bed of flags under its mast and winch (the crane is its own model)."""
    for i, (x, y, sx, sy) in enumerate(((-0.75, -0.55, 0.7, 0.5), (0.7, -0.6, 0.72, 0.52), (-0.72, 0.56, 0.7, 0.5), (0.74, 0.5, 0.68, 0.54), (0.0, 0.0, 0.3, 0.3))):
        e_box(k, M, (x - sx, y - sy, 0.0), (x + sx - 0.02, y + sy - 0.02, 0.045 + 0.008 * i), jit(mix(P.basalt, P.pale, 0.5), rng, 0.025), open_bottom=True)


def c_stone_stack(k, rng, M, o, f):
    """Squared stones waiting: dressed basalt on two bearers, three to a course, sawn faces pale."""
    n = o.get("n", 9)
    for y in (-0.48, 0.48):
        e_box(k, M, (-1.5, y - 0.07, 0.0), (1.5, y + 0.07, 0.11), jit(mix(P.drift, P.tar, 0.4), rng, 0.02), open_bottom=True)
    z, i = 0.114, 0
    while i < n:
        row = min(3, n - i)
        zh = 0.38 + 0.03 * ((i // 3) % 2)
        for j in range(row):
            x0 = -1.46 + 0.98 * j + 0.06 * ((i // 3) % 2)
            e_ = 0.84 + 0.06 * ((i + j) % 2)
            put(k, lbox(Vector((x0, -0.42 + 0.03 * (j % 2), z)), Vector((x0 + e_, 0.4, z + zh)), fn=lambda q: M @ q, bevel=0.015),
                lambda co, nn, c=jit(P.basalt, rng, 0.03): mix(c, P.pale, 0.5) if nn.z > 0.5 else mix(c, P.pale, 0.2))
        z += zh + 0.004
        i += row


def c_sledge(k, rng, M, o, f):
    """A stone sledge: two runners shod with iron and a bed of planks, one stone still on it,
    the drag rope laid out before it."""
    for y in (-0.42, 0.42):
        put(k, beam(M @ Vector((-1.0, y, 0.09)), M @ Vector((1.0, y, 0.09)), 0.1, 0.18), jit(P.drift, rng, 0.03))
        put(k, beam(M @ Vector((1.0, y, 0.09)), M @ Vector((1.28, y, 0.24)), 0.1, 0.16), jit(P.drift, rng, 0.03))
    for i in range(4):
        e_box(k, M, (-0.9 + 0.46 * i, -0.52, 0.184), (-0.9 + 0.46 * i + 0.4, 0.52, 0.23), jit(mix(P.drift, P.tar, 0.25), rng, 0.03))
    if o.get("stone"):
        put(k, lbox(Vector((-0.5, -0.32, 0.234)), Vector((0.42, 0.3, 0.66)), fn=lambda q: M @ q, bevel=0.02), lambda co, nn, c=jit(P.basalt, rng, 0.03): mix(c, P.pale, 0.5) if nn.z > 0.5 else c)
    put(k, tube([M @ Vector(q) for q in ((1.26, -0.42, 0.22), (1.9, -0.1, 0.03), (2.5, 0.0, 0.03), (1.9, 0.12, 0.03), (1.26, 0.42, 0.22))], 0.022, 4, caps=False), ROPE, closed=False)


def c_split_block(k, rng, M, o, f):
    """A block lying half split: a row of iron wedges still in the line of drilled holes, the
    two halves a hand apart, the half-holes showing pale on the open faces."""
    c = jit(P.basalt, rng, 0.03)
    for e in (-1, 1):
        S = M @ Matrix.Translation((e * 0.02, 0, 0)) @ Matrix.Rotation(rad(e * 2.5), 4, "Y")
        x0, x1 = (-0.95, -0.03) if e < 0 else (0.03, 0.8)
        put(k, lbox(Vector((x0, -0.5, 0.0)), Vector((x1, 0.5, 0.78)), fn=lambda q, S=S: S @ q, bevel=0.02, open_bottom=True),
            lambda co, nn, c=c, e=e: mix(c, P.pale, 0.55) if nn.dot(M.to_3x3() @ X) * -e > 0.6 or nn.z > 0.6 else c)
    for i in range(5):
        y = -0.36 + 0.18 * i
        put(k, lbox(Vector((-0.035, y - 0.03, 0.74)), Vector((0.035, y + 0.03, 0.9)), fn=lambda q: M @ q), jit(mix(P.iron, P.rust, 0.5), rng, 0.02))
    e_box(k, M, (0.3, -0.75, 0.0), (0.5, -0.56, 0.1), jit(mix(P.iron, P.rust, 0.4), rng, 0.02), open_bottom=True)  # the sledge hammer's head
    put(k, beam(M @ Vector((0.4, -0.66, 0.06)), M @ Vector((1.2, -0.9, 0.04)), 0.035, 0.035), jit(P.drift, rng, 0.03))


def c_clay_floor(k, rng, M, o, f):
    """The pit's floor: stony till dug to the level a spade stops at, lumpy, wet in the middle."""
    w, d = o["w"], o["d"]
    nx, ny = max(3, round(w / 1.3)), max(3, round(d / 1.3))
    at = M @ Vector((0, 0, 0))
    px, py = o.get("puddle", [0.0, 0.0])

    def zz(i, j):
        edge = min(i, nx - i, j, ny - j) == 0
        x, y = -w / 2 + w * i / nx, -d / 2 + d * j / ny
        dip = max(0.0, 1 - math.hypot((x - px) / 2.6, (y - py) / 1.7))
        return 0.012 if edge else 0.05 + 0.09 * (0.5 + 0.5 * nz(x * 0.9 + at.x, y * 0.9 + at.y, 3.3)) * (1 - dip)
    polys = []
    for i in range(nx):
        for j in range(ny):
            q = [M @ Vector((-w / 2 + w * a / nx, -d / 2 + d * b / ny, zz(a, b))) for a, b in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))]
            t_ = 0.5 + 0.5 * nz(i * 1.7, j * 1.3, 8.0)
            c = jit(mix(ROCK, P.pale, 0.2 + 0.5 * t_) if o.get("rock") else on(mix(P.sand, P.basalt, 0.5 + 0.22 * t_), "earth"), rng, 0.02)
            polys += [([q[0], q[1], q[2]], c), ([q[0], q[2], q[3]], c)]
    raw(k, polys)
    if "puddle" in o:
        ring = [M @ Vector((px + cos(a / 10 * TAU) * 2.1 * (1 + 0.12 * sin(a * 2.3)), py + sin(a / 10 * TAU) * 1.3 * (1 + 0.1 * cos(a * 1.7)), 0.062)) for a in range(10)]
        raw(k, [(ring, on(mix(P.smoke, P.basalt, 0.6), "earth"))])
    for i in range(6):
        a, dd = rng.uniform(0, TAU), rng.uniform(0.3, 0.45)
        S = M @ Matrix.Translation((rng.uniform(-w / 2 + 0.6, w / 2 - 0.6), rng.uniform(-d / 2 + 0.6, d / 2 - 0.6), 0.0)) @ Matrix.Rotation(a, 4, "Z")
        put(k, lbox(Vector((-dd, -dd * 0.7, 0.0)), Vector((dd, dd * 0.7, 0.14 + dd * 0.4)), fn=lambda q, S=S: S @ q, bevel=0.03, open_bottom=True), jit(P.basalt, rng, 0.03))


def c_clay_bank(k, rng, M, o, f):
    """The last bank of good clay, under the face: grey-blue, cut in clean spade lifts, Otto
    Brandt's spade standing in it."""
    w, d = o.get("w", 5.0), o.get("d", 2.0)
    lifts = ((-d / 2, 0.0, 0.42), (-d / 2 + 0.55, 0.424, 0.84), (-d / 2 + 1.1, 0.844, 1.26))
    for j, (y0, z0, z1) in enumerate(lifts):
        m = max(2, round(w / 0.5))
        for i in range(m):
            x0, x1 = -w / 2 + w * i / m + 0.004, -w / 2 + w * (i + 1) / m - 0.004
            yy = y0 + 0.05 * ((i * 3 + j) % 3) + (0.5 if (i >= m - 3 and j == 0) else 0.0)  # where he is digging now
            if yy >= d / 2 - 0.1:
                continue
            put(k, lbox(Vector((x0, yy, z0)), Vector((x1, d / 2, z1)), fn=lambda q: M @ q, open_bottom=j == 0), on(jit(mix(P.smoke, P.basalt, 0.26 + 0.12 * ((i + j) % 2)), rng, 0.02), "earth"))
    S = M @ Matrix.Translation((w / 2 - 0.9, -d / 2 + 0.25, 0.0)) @ Matrix.Rotation(rad(12), 4, "X")
    put(k, tube([S @ Vector((0, 0, 0.2)), S @ Vector((0, 0, 1.15))], 0.022, 5), jit(P.drift, rng, 0.03))
    put(k, lbox(Vector((-0.09, -0.008, -0.05)), Vector((0.09, 0.008, 0.24)), fn=lambda q: S @ q), jit(mix(P.iron, P.rust, 0.45), rng, 0.02))
    put(k, beam(S @ Vector((-0.1, 0, 1.15)), S @ Vector((0.1, 0, 1.15)), 0.03, 0.03), jit(P.drift, rng, 0.03))


def c_clay_boards(k, rng, M, o, f):
    """Dug clay on boards, kept damp under sacking till it goes down to the pot house."""
    for i in range(o.get("n", 3)):
        Bm = M @ Matrix.Translation((0.0, -0.75 + 0.75 * i, 0.0)) @ Matrix.Rotation(rad((-4, 3, -2)[i % 3]), 4, "Z")
        for x in (-0.5, 0.5):
            e_box(k, Bm, (x - 0.05, -0.26, 0.0), (x + 0.05, 0.26, 0.07), jit(mix(P.drift, P.tar, 0.4), rng, 0.02), open_bottom=True)
        e_box(k, Bm, (-0.72, -0.28, 0.074), (0.72, 0.28, 0.11), jit(P.drift, rng, 0.03))
        for j in range(3):
            covered = (i + j) % 3 == 0
            bm = sphere((0, 0, 0), 1.0, 1)
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.01], context="VERTS")
            for v in bm.verts:
                v.co = Bm @ Vector((-0.46 + 0.46 * j + v.co.x * 0.2, v.co.y * 0.2, 0.112 + v.co.z * 0.24))
            put(k, bm, on(jit(mix(P.sand, P.drift, 0.5), rng, 0.02), "cloth") if covered else jit(GOOD_CLAY, rng, 0.02), closed=False)


def c_plank_run(k, rng, M, o, f):
    """A barrow run: planks laid end to end up the pit's bank."""
    b = Vector((o["to"][0] - o["_at"][0], o["to"][1] - o["_at"][1], 0.0))
    L = b.length
    t, s = b / L, Vector((-b.y, b.x, 0)) / L
    m = max(2, round(L / 2.1))
    for i in range(m):
        a0, a1 = L * i / m - (0.12 if i else 0.0), L * (i + 1) / m
        z = 0.03 + 0.036 * (i % 2)
        off = s * (0.04 * (i % 2))
        put(k, lbox(Vector((a0, -0.16, z)), Vector((a1, 0.16, z + 0.032)), fn=lambda q: M @ (t * q.x + s * q.y + off + Z * q.z)), jit(mix(P.drift, P.sand, 0.25), rng, 0.03))


def c_steam_box(k, rng, M, o, f):
    """The steaming box: a long tarred trunk on trestles where a plank is steamed till it will
    bend to the hull; a kettle on a brick firebox at one end and a pipe into it, rags stuffed
    round the door, a plank's end sticking out."""
    L = o.get("len", 5.4)
    hl = L / 2
    for x in (-hl + 0.5, 0.0, hl - 0.5):
        for e in (-1, 1):
            put(k, beam(M @ Vector((x, e * 0.42, 0.0)), M @ Vector((x, e * 0.16, 0.74)), 0.07, 0.07, up=M.to_3x3() @ X), jit(P.drift, rng, 0.03))
        put(k, beam(M @ Vector((x, -0.3, 0.74)), M @ Vector((x, 0.3, 0.74)), 0.08, 0.08, up=M.to_3x3() @ X), jit(P.drift, rng, 0.03))
    for j, (y0, y1, z0, z1) in enumerate(((-0.24, 0.24, 0.784, 0.82), (-0.24, 0.24, 1.2, 1.236), (-0.276, -0.244, 0.784, 1.236), (0.244, 0.276, 0.784, 1.236))):
        for i in range(3):  # three lengths of board, butted with a batten over each joint
            x0, x1 = -hl + L * i / 3 + 0.006, -hl + L * (i + 1) / 3 - 0.006
            e_box(k, M, (x0, y0, z0), (x1, y1, z1), jit(P.tar, rng, 0.025))
    for i in (1, 2):
        x = -hl + L * i / 3
        e_box(k, M, (x - 0.05, -0.3, 0.77), (x + 0.05, 0.3, 1.25), jit(mix(P.tar, P.drift, 0.3), rng, 0.02))
    e_box(k, M, (hl - 0.03, -0.24, 0.824), (hl, 0.24, 1.196), jit(mix(P.tar, P.drift, 0.5), rng, 0.02))  # the door board
    put(k, lbox(Vector((hl - 0.6, -0.11, 0.95)), Vector((hl + 0.75, 0.11, 0.985)), fn=lambda q: M @ q), jit(mix(P.drift, P.sand, 0.3), rng, 0.03))  # a plank coming out
    raw(k, [([M @ Vector((hl + 0.004, -0.2, 0.9)), M @ Vector((hl + 0.004, 0.2, 0.9)), M @ Vector((hl + 0.004, 0.22, 1.08)), M @ Vector((hl + 0.004, -0.18, 1.1))], on(jit(P.oldlime, rng, 0.03), "cloth"))], two=True)
    # The boiler at the other end: a brick firebox, an iron kettle, the pipe.
    Bx = M @ Matrix.Translation((-hl - 0.75, 0, 0))
    put(k, lbox(Vector((-0.42, -0.42, 0.0)), Vector((0.42, 0.42, 0.5)), fn=lambda q: Bx @ q, open_bottom=True), lambda co, nn, c=jit(P.brick, rng, 0.03): mix(c, P.tar, 0.4) if nn.z > 0.5 else c)
    raw(k, [([Bx @ Vector((-0.2, -0.424, 0.06)), Bx @ Vector((0.2, -0.424, 0.06)), Bx @ Vector((0.2, -0.424, 0.34)), Bx @ Vector((-0.2, -0.424, 0.34))], P.tar)])
    put(k, lathe([(0.2, 0.504), (0.34, 0.6), (0.36, 0.8), (0.28, 0.95), (0.12, 1.0), (0.12, 1.06)], 10, Bx), jit(mix(P.iron, P.rust, 0.35), rng, 0.02))
    put(k, tube([Bx @ Vector((0.0, 0.0, 1.05)), Bx @ Vector((0.3, 0.0, 1.14)), Bx @ Vector((0.78, 0.0, 1.05))], 0.045, 6), jit(mix(P.iron, P.rust, 0.5), rng, 0.02))
    for i in range(3):
        e_box(k, Bx, (-0.5 + 0.02 * i, 0.5 + 0.2 * i, 0.0), (0.3, 0.66 + 0.2 * i, 0.12 + 0.02 * i), jit(P.peat, rng, 0.03), open_bottom=True)  # peat for the fire


def c_sawhorses(k, rng, M, o, f):
    """Two saw trestles with a plank across them and the saw left in the cut."""
    for x in (-0.95, 0.95):
        put(k, beam(M @ Vector((x, -0.4, 0.7)), M @ Vector((x, 0.4, 0.7)), 0.09, 0.09, up=M.to_3x3() @ X), jit(P.drift, rng, 0.03))
        for ey in (-1, 1):
            for ex in (-1, 1):
                put(k, beam(M @ Vector((x + ex * 0.04, ey * 0.34, 0.66)), M @ Vector((x + ex * 0.3, ey * 0.46, 0.0)), 0.06, 0.06, up=M.to_3x3() @ Y), jit(P.drift, rng, 0.03))
    put(k, lbox(Vector((-1.9, -0.14, 0.75)), Vector((1.7, 0.14, 0.79)), fn=lambda q: M @ q), jit(mix(P.drift, P.sand, 0.35), rng, 0.03))
    raw(k, [([M @ Vector((0.3, -0.3, 0.6)), M @ Vector((0.3, 0.42, 0.72)), M @ Vector((0.3, 0.42, 0.86)), M @ Vector((0.3, -0.3, 0.98))], jit(mix(P.iron, P.rust, 0.3), rng, 0.02))], two=True)
    bm = sphere((0, 0, 0), 1.0, 1)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.01], context="VERTS")
    for v in bm.verts:
        v.co = M @ Vector((0.3 + v.co.x * 0.4, v.co.y * 0.5, v.co.z * 0.1))
    put(k, bm, jit(mix(P.sand, P.drift, 0.3), rng, 0.02), closed=False)  # sawdust


def c_pitch_pot(k, rng, M, o, f):
    """The pitch pot: an iron cauldron on three stones over a ring of ash, a ladle in it."""
    for i in range(7):
        a = i / 7 * TAU
        S = M @ Matrix.Translation((cos(a) * 0.62, sin(a) * 0.62, 0)) @ Matrix.Rotation(a, 4, "Z")
        put(k, lbox(Vector((-0.12, -0.16, 0.0)), Vector((0.12, 0.16, 0.17 + 0.04 * (i % 2))), fn=lambda q, S=S: S @ q, bevel=0.02, open_bottom=True), jit(mix(P.basalt, P.tar, 0.4), rng, 0.02))
    raw(k, [([M @ Vector((cos(i / 8 * TAU) * 0.48, sin(i / 8 * TAU) * 0.48, 0.02)) for i in range(8)], jit(ASH, rng, 0.02))])
    put(k, lathe([(0.16, 0.2), (0.33, 0.3), (0.36, 0.5), (0.31, 0.62), (0.26, 0.62), (0.3, 0.5)], 10, M, caps=(True, False)), jit(mix(P.iron, P.tar, 0.4), rng, 0.02), closed=False)
    raw(k, [([M @ Vector((cos(i / 8 * TAU) * 0.28, sin(i / 8 * TAU) * 0.28, 0.56)) for i in range(8)], P.tar)])
    put(k, tube([M @ Vector((0.1, 0.0, 0.56)), M @ Vector((0.5, 0.2, 0.86))], 0.018, 4), jit(P.drift, rng, 0.03))


def c_peat_rick(k, rng, M, o, f):
    """A stance of the town's peat: two bearers, and on them a rick under tarred cloth roped
    down with stones (`full`), what is left of one (`half`), or nothing but the folded cloth
    (`bare`): the stack is lower each week."""
    st = o.get("state", "full")
    for y in (-0.42, 0.42):
        put(k, beam(M @ Vector((-1.5, y, 0.07)), M @ Vector((1.5, y, 0.07)), 0.12, 0.13), jit(mix(P.drift, P.tar, 0.35), rng, 0.02))
    if st == "bare":
        for i in range(3):
            e_box(k, M, (-0.9 + 0.04 * i, -0.3 + 0.03 * i, 0.14 + 0.05 * i), (-0.1 - 0.03 * i, 0.3 - 0.02 * i, 0.185 + 0.05 * i), on(jit(P.tar, rng, 0.02), "cloth"))
        for i in range(6):
            x, y = rng.uniform(-1.3, 1.3), rng.uniform(-0.6, 0.6)
            e_box(k, M, (x - 0.09, y - 0.06, 0.0), (x + 0.09, y + 0.06, 0.05), jit(P.peat, rng, 0.03), open_bottom=True)
        return
    x1, hgt = (1.45, 1.36) if st == "full" else (-0.1, 0.84)
    rows = max(3, round(hgt / 0.16))
    for j in range(rows):
        ins = 0.014 * j
        e_box(k, M, (-1.45 + ins, -0.6 + ins, 0.14 + hgt * j / rows), (x1 - ins - (0.12 * (j % 3) if st == "half" else 0.0), 0.6 - ins, 0.14 + hgt * (j + 1) / rows - 0.012),
              jit(P.peat if j % 2 else mix(P.peat, P.grass, 0.12), rng, 0.03), open_bottom=True)
    top = 0.14 + hgt
    cloth = on(jit(P.tar, rng, 0.02), "cloth")
    cx1 = x1 + 0.04 if st == "full" else x1 - 0.5  # half: the cloth is folded back from the open end
    e_box(k, M, (-1.5, -0.66, top - 0.006), (cx1, 0.66, top + 0.04), cloth)
    for e in (-1, 1):  # the cloth's skirts down the long sides, and the stones that hold it
        raw(k, [([M @ Vector((-1.5, e * 0.664, top + 0.02)), M @ Vector((cx1, e * 0.664, top + 0.02)), M @ Vector((cx1, e * 0.7, top - 0.55)), M @ Vector((-1.5, e * 0.7, top - 0.5))], cloth)], two=True)
        for x in (-1.2, -0.4, 0.5, 1.2):
            if x > cx1 - 0.2:
                continue
            put(k, tube([M @ Vector((x, e * 0.69, top - 0.5)), M @ Vector((x, e * 0.74, 0.3))], 0.012, 3, caps=False), ROPE, closed=False)
            e_box(k, M, (x - 0.1, e * 0.74 - 0.08, 0.14), (x + 0.1, e * 0.74 + 0.08, 0.32), jit(P.pale, rng, 0.03))


def c_tally_post(k, rng, M, o, f):
    """The tally keeper's slate on a post: the loads counted in and out, in strokes of chalk."""
    put(k, tube([M @ Vector((0, 0, 0)), M @ Vector((0, 0, 1.55))], [0.06, 0.05], 5), jit(P.drift, rng, 0.03))
    e_box(k, M, (-0.3, -0.075, 0.82), (0.3, -0.055, 1.5), jit(P.slate, rng, 0.02))
    marks = []
    for r in range(4):
        for i in range(5 if r < 3 else 2):
            x, z = -0.22 + 0.09 * i, 1.36 - 0.14 * r
            marks.append(([M @ Vector((x, -0.0775, z)), M @ Vector((x + 0.02, -0.0775, z)), M @ Vector((x + 0.02, -0.0775, z + 0.09)), M @ Vector((x, -0.0775, z + 0.09))], P.lime))
    raw(k, [(oriented(q, M.to_3x3() @ -Y), c) for q, c in marks])


def c_peat_creels(k, rng, M, o, f):
    """Back creels of peat set down: the wynds are stairs, so peat comes down on backs."""
    n = o.get("n", 4)
    for i in range(n):
        C = M @ Matrix.Translation(((i % 3) * 0.62 - 0.6, (i // 3) * 0.6, 0.0)) @ Matrix.Rotation(rad(40 * i), 4, "Z")
        creel(k, rng, C, r=0.25, h=0.58, sides=8, rows=4)
        if i % 4 != 3:  # one is empty
            for j in range(3):
                Bm = C @ Matrix.Translation((-0.08 + 0.08 * j, 0.03 * (j % 2), 0.4 + 0.07 * j)) @ Matrix.Rotation(rad(25 * j), 4, "Z")
                put(k, lbox(Vector((-0.16, -0.08, 0.0)), Vector((0.16, 0.08, 0.1)), fn=lambda q, Bm=Bm: Bm @ q), jit(P.peat, rng, 0.03))


def c_bank(k, rng, M, o, f):
    """A loading bank: dry basalt at the height of a cart's bed, its top worn; creels are tipped
    over it into the handcart."""
    L = o.get("len", 4.4)
    m = max(3, round(L / 0.95))
    for j, (z0, z1, ins) in enumerate(((0.0, 0.4, 0.0), (0.404, 0.78, 0.03))):
        for i in range(m):
            x0, x1 = -L / 2 + L * i / m + 0.006 + (0.0 if j == 0 or i == 0 else -0.3 * L / m), -L / 2 + L * (i + 1) / m - 0.006 - (0.0 if j == 0 or i == m - 1 else 0.3 * L / m)
            put(k, lbox(Vector((x0, -0.55 + ins, z0)), Vector((x1, 0.55 - ins, z1)), fn=lambda q: M @ q, bevel=0.02, open_bottom=j == 0),
                lambda co, nn, c=jit(P.basalt if (i + j) % 3 else P.pale, rng, 0.03), j=j: mix(c, P.pale, 0.5) if nn.z > 0.5 and j == 1 else c)
    for i in range(5):
        x = rng.uniform(-L / 2 + 0.3, L / 2 - 0.3)
        e_box(k, M, (x - 0.08, -0.2 + 0.1 * (i % 3), 0.784), (x + 0.08, -0.08 + 0.1 * (i % 3), 0.83), jit(P.peat, rng, 0.03))  # crumbs of peat


def c_gutting_table(k, rng, M, o, f):
    """A gutting table at the quay's edge: a slate slab on two trestles, a runnel cut toward the
    harbour, the morning's last fish, a knife, the gut bucket under it."""
    for x in (-0.72, 0.72):
        for e in (-1, 1):
            put(k, beam(M @ Vector((x, e * 0.38, 0.0)), M @ Vector((x, e * 0.14, 0.8)), 0.07, 0.07, up=M.to_3x3() @ X), jit(P.drift, rng, 0.03))
        put(k, beam(M @ Vector((x, -0.3, 0.8)), M @ Vector((x, 0.3, 0.8)), 0.08, 0.07, up=M.to_3x3() @ X), jit(P.drift, rng, 0.03))
    top = jit(mix(P.slate, P.pale, 0.3), rng, 0.02)
    e_box(k, M, (-1.0, -0.45, 0.838), (1.0, 0.45, 0.9), top, bevel=0.012)
    raw(k, [([M @ Vector((-0.8, -0.449, 0.9035)), M @ Vector((-0.7, -0.449, 0.9035)), M @ Vector((-0.7, 0.3, 0.9035)), M @ Vector((-0.8, 0.3, 0.9035))], mix(top, P.tar, 0.5)),
            ([M @ Vector((-0.5, -0.2, 0.9035)), M @ Vector((0.1, -0.3, 0.9035)), M @ Vector((0.2, 0.05, 0.9035)), M @ Vector((-0.45, 0.15, 0.9035))], mix(top, P.oxblood, 0.3))])
    for i in range(3):
        Fm = M @ Matrix.Translation((0.35 + 0.2 * i, -0.1 + 0.12 * i, 0.93)) @ Matrix.Rotation(rad(70 + 12 * i), 4, "Z")
        bm = sphere((0, 0, 0), 1.0, 1)
        for v in bm.verts:
            v.co = Fm @ Vector((v.co.x * 0.2 * (1 - 0.35 * v.co.x), v.co.y * 0.055, v.co.z * 0.03))
        put(k, bm, jit(mix(P.smoke, P.aqua, 0.3), rng, 0.02))
    raw(k, [([M @ Vector((-0.3, 0.22, 0.906)), M @ Vector((-0.02, 0.26, 0.906)), M @ Vector((-0.02, 0.29, 0.906))], P.iron)], two=True)
    Bm = M @ Matrix.Translation((-0.25, 0.75, 0.0))
    barrel(k, rng, None, 0.19, 0.33, wood=P.drift, M=Bm, head=False, sides=8, hoops=(0.2, 0.85))
    raw(k, [([Bm @ Vector((cos(j / 8 * TAU) * 0.15, sin(j / 8 * TAU) * 0.15, 0.22)) for j in range(8)], mix(P.oxblood, P.tar, 0.5))])


def c_bait_tubs(k, rng, M, o, f):
    """Bait tubs: half barrels of brine, limpets and mussels, one with its lid on."""
    n = o.get("n", 3)
    for i in range(n):
        Bm = M @ Matrix.Translation((-0.75 + 0.75 * i, 0.12 * (i % 2), 0.0))
        barrel(k, rng, None, 0.3, 0.46, wood=P.drift, M=Bm, salt=0.7, head=False, sides=10, hoops=(0.2, 0.8))
        if i == n - 1:
            put(k, B.cyl(Bm @ Vector((0, 0, 0.462)), Bm @ Vector((0, 0, 0.5)), 0.31, 0.31, 10), jit(P.drift, rng, 0.03))
        else:
            raw(k, [([Bm @ Vector((cos(j / 10 * TAU) * 0.24, sin(j / 10 * TAU) * 0.24, 0.36)) for j in range(10)], mix(P.smoke, P.tar, 0.5))])
            for j in range(4):
                put(k, sphere(Bm @ Vector((cos(j * 1.7) * 0.12, sin(j * 1.7) * 0.12, 0.362)), 0.045, 1, squash=0.5), jit(mix(P.tar, P.cobalt, 0.25), rng, 0.02))


def c_mending_bench(k, rng, M, o, f):
    """A net-mender's bench: a thwart on two stones, and beside it a net stretched on its frame
    to be worked from the bench, a float still on its head rope; twine and a needle in a creel."""
    for x in (-0.6, 0.6):
        e_box(k, M, (x - 0.14, -0.17, 0.0), (x + 0.14, 0.17, 0.4), jit(P.basalt, rng, 0.03), open_bottom=True)
    e_box(k, M, (-0.9, -0.2, 0.404), (0.9, 0.2, 0.46), jit(P.drift, rng, 0.03))
    fy = 0.75
    for x in (-0.95, 0.95):
        put(k, tube([M @ Vector((x, fy, 0.0)), M @ Vector((x, fy, 1.62))], [0.045, 0.035], 5), jit(P.drift, rng, 0.03))
        put(k, beam(M @ Vector((x, fy - 0.3, 0.0)), M @ Vector((x, fy, 0.5)), 0.04, 0.04, up=M.to_3x3() @ X), jit(P.drift, rng, 0.03))
    put(k, tube([M @ Vector((-1.05, fy, 1.56)), M @ Vector((1.05, fy, 1.56))], 0.028, 4), jit(P.drift, rng, 0.03))
    net = on(P.tar, "cloth")
    nu, nv = 9, 5

    def node(i, j):
        return M @ Vector((-0.9 + 1.8 * i / nu, fy + 0.02 * sin(i * 1.3 + j), 1.54 - 1.2 * j / nv))
    polys = []
    for i in range(nu):
        for j in range(nv):
            if (i * 3 + j * 5 + f["seed"]) % 13 == 0:
                continue  # the hole she is mending
            for a, b in ((node(i, j), node(i + 1, j + 1)), (node(i + 1, j), node(i, j + 1))):
                polys += [(q, jit(net, rng, 0.02)) for q in ribbon([a, b], 0.022, (b - a).cross(M.to_3x3() @ Y).normalized())]
    raw(k, polys, two=True)
    put(k, sphere(node(2, 0) + Vector((0, 0, 0.1)), 0.1, 1), jit(P.green, rng, 0.03))
    creel(k, rng, M @ Matrix.Translation((1.25, -0.1, 0.0)), r=0.2, h=0.4, sides=8, rows=4)


CONTENT.update(
    grave_row=c_grave_row, ship_stones=c_ship_stones, steps=c_steps, apron=c_apron, dip_step=c_dip_step, buckets=c_buckets, runnel=c_runnel, slab=c_slab, tablet_bench=c_tablet_bench,
    stools=c_stools, sand_tray=c_sand_tray, spoil=c_spoil, crane=c_crane_foot, stone_stack=c_stone_stack, sledge=c_sledge, split_block=c_split_block, clay_floor=c_clay_floor,
    clay_bank=c_clay_bank, clay_boards=c_clay_boards, plank_run=c_plank_run, steam_box=c_steam_box, sawhorses=c_sawhorses, pitch_pot=c_pitch_pot, peat_rick=c_peat_rick,
    tally_post=c_tally_post, peat_creels=c_peat_creels, bank=c_bank, gutting_table=c_gutting_table, bait_tubs=c_bait_tubs, mending_bench=c_mending_bench,
)


def gen_quarry_face(k, rng, lot):
    """A length of the quarry's face: the raw rock a drop was cut into (the plan: `fall_m`,
    `rock`, `drill`, `stain_at`). Basalt stands in columns and was worked in lifts a man can
    reach. So the face is narrow columns, each broken off at its own heights, its faces turned
    a little from its neighbours' and set back as it rises, its top where it happened to break:
    no course and no level line runs along it, as they do along a built wall. Where it was split
    along drilled holes (`drill`) the half-holes show: dark grooves down the pale, newest rock.
    `clay`: the pit's face, cut in even spade lifts under a cap of thin rock and turf. Built of
    its seen faces, each column a hair narrower than its place: no two parts meet in one plane."""
    L, D = lot["size"]
    fall, clay, drill = lot["fall_m"], lot.get("rock") == "clay", lot.get("drill")
    env, w = Env(lot), lot["wear"]
    lich = env.weather(-Y) * (0.3 + w["wind"])
    stain = lot.get("stain_at")
    a, n_col, polys, marks = -L / 2, 0, [], []
    back = D / 2
    while a < L / 2 - 1e-6:
        b = a + (rng.uniform(0.7, 1.3) if clay else rng.uniform(0.4, 1.0))
        b = L / 2 if L / 2 - b < 0.35 else b
        n_col += 1
        a0, a1 = a + 0.004, b - 0.004
        am = (a + b) / 2
        lifts = max(2, round(fall / (0.9 if clay else 1.0)))
        top = fall if clay else fall - rng.choice((0.0, 0.0, 0.0, 0.15, 0.35, 0.6))
        # Where this column was broken off, at its left and its right edge, and how far back.
        zl, zr = [-0.25], [-0.25]
        for j_ in range(1, lifts):
            z = top * j_ / lifts + (rng.uniform(-0.1, 0.1) if clay else rng.uniform(-0.35, 0.35))
            tilt = rng.uniform(-0.05, 0.05) if clay else rng.uniform(-0.18, 0.18)
            zl.append(min(top - 0.3, max(zl[-1] + 0.35, z - tilt)))
            zr.append(min(top - 0.3, max(zr[-1] + 0.35, z + tilt)))
        zl.append(top + (0.0 if clay else rng.uniform(-0.1, 0.0)))
        zr.append(top + (0.0 if clay else rng.uniform(-0.1, 0.0)))
        y, yl, yr = -D / 2 + rng.uniform(0.0, 0.1 if clay else 0.28), [], []
        for j_ in range(lifts):
            skew = rng.uniform(-0.06, 0.06) if clay else rng.uniform(-0.13, 0.13)
            yl.append(min(back - 0.12, y - skew))
            yr.append(min(back - 0.12, y + skew))
            y += (D - 0.35) / max(1, lifts - 1) * rng.uniform(0.3, 1.25)
        shade = rng.choice((0.0, 0.0, 0.12, 0.22))
        base = mix(jit(ROCK, rng, 0.04), P.tar, shade)
        fresh = bool(drill) and rng.random() < 0.8
        for j_ in range(lifts):
            if clay:
                c = on(jit(mix(P.sand, P.basalt, 0.6), rng, 0.02), "earth") if j_ == 0 else jit(mix(ROCK, P.peat, 0.45), rng, 0.02) if j_ == lifts - 1 else on(jit(mix(P.smoke, P.basalt, 0.45 + 0.15 * ((j_ + n_col) % 2)), rng, 0.03), "earth")
            else:
                c = mix(base, P.pale, 0.5) if fresh and j_ >= lifts - 2 else base
                if stain is not None and abs(am + L / 2 - stain) < 0.8:
                    c = mix(ROCK, P.kelp, 0.5)  # where the cistern's overflow runs down
                elif not fresh and lich > 0.2 and nz(am * 0.7, j_ * 1.3, lot["seed"] * 0.01) > 0.3 - 0.4 * lich:
                    c = mix(c, P.lichen, 0.25)
                elif nz(am * 0.9, j_ * 1.7, 4.0 + lot["seed"] * 0.01) > 0.45:
                    c = mix(c, P.rust, 0.22)  # iron in the rock, weeping
            fl, fr = Vector((a0, yl[j_], zl[j_])), Vector((a1, yr[j_], zr[j_]))
            tl, tr = Vector((a0, yl[j_], zl[j_ + 1])), Vector((a1, yr[j_], zr[j_ + 1]))
            bl, br = Vector((a0, back, zl[j_ + 1])), Vector((a1, back, zr[j_ + 1]))
            polys.append((oriented([fl, fr, tr], -Y), c))
            polys.append((oriented([fl, tr, tl], -Y), c))
            ledge = jit(mix(P.grass, P.peat, 0.3), rng, 0.02) if j_ == lifts - 1 and (clay or top > fall - 0.05) else mix(c, P.pale, 0.3)
            polys.append((oriented([tl, tr, br], Z), ledge))
            polys.append((oriented([tl, br, bl], Z), ledge))
            side = mix(c, P.tar, 0.2)
            polys.append((oriented([Vector((a0, back, zl[j_])), fl, tl, bl], -X), side))
            polys.append((oriented([Vector((a1, back, zr[j_])), fr, tr, br], X), side))
            if fresh and j_ >= lifts - 2 and b - a > 0.3:  # the half-holes of the split
                u = rng.uniform(0.3, 0.7)
                yy = yl[j_] + (yr[j_] - yl[j_]) * u - 0.006
                x = a0 + (a1 - a0) * u
                z0, z1 = max(0.0, zl[j_], zr[j_]) + 0.08, min(zl[j_ + 1], zr[j_ + 1]) - 0.12
                if z1 - z0 > 0.3:
                    marks.append((oriented([Vector((x - 0.022, yy, z0)), Vector((x + 0.022, yy, z0)), Vector((x + 0.022, yy, z1)), Vector((x - 0.022, yy, z1))], -Y), mix(P.basalt, P.tar, 0.6)))
        a = b
    raw(k, polys)
    raw(k, marks)
    # What has fallen to its foot.
    for i in range(max(2, round(L / 1.4))):
        x, sz = rng.uniform(-L / 2 + 0.3, L / 2 - 0.3), rng.uniform(0.09, 0.22)
        S = Matrix.Translation((x, -D / 2 + rng.uniform(0.08, 0.2) + sz * 0.7, 0.0)) @ Matrix.Rotation(rng.uniform(0, PI), 4, "Z")
        put(k, lbox(Vector((-sz, -sz * 0.7, 0)), Vector((sz, sz * 0.7, sz)), fn=lambda q, S=S: S @ q, bevel=0.02, open_bottom=True), jit(GOOD_CLAY if clay else (ROCK if i % 2 else ROCK_PALE), rng, 0.03))
    return dict(ridge_m=round(fall, 3), fall_m=fall, columns=n_col)


def gen_quarry_crane(k, rng, lot):
    """The quarry's crane: a ship's spar for a mast, stepped in a stone and stayed by two raking
    legs; a jib on a hook at its foot, held by a topping rope; a hand winch on the mast; the fall
    rope down to a squared stone in its sling, a hand above the ground: waiting."""
    wood, dark = jit(P.drift, rng, 0.03), jit(mix(P.drift, P.tar, 0.4), rng, 0.02)
    put(k, lbox(Vector((-0.5, -0.5, 0.0)), Vector((0.5, 0.5, 0.32)), bevel=0.03, open_bottom=True), jit(P.basalt, rng, 0.03))
    mast_top = Vector((0, 0, 6.0))
    put(k, tube([Vector((0, 0, 0.3)), mast_top], [0.13, 0.085], 7), wood)
    for e in (-1, 1):  # the legs behind
        put(k, tube([Vector((e * 1.5, 1.9, 0.0)), Vector((e * 0.06, 0.1, 4.6))], 0.065, 5), dark)
        put(k, lbox(Vector((e * 1.5 - 0.3, 1.6, 0.0)), Vector((e * 1.5 + 0.3, 2.2, 0.2)), bevel=0.02, open_bottom=True), jit(P.basalt, rng, 0.03))
    jib_foot, jib_end = Vector((0, -0.16, 0.9)), Vector((0, -2.9, 4.5))
    put(k, tube([jib_foot, jib_end], [0.095, 0.07], 6), wood)
    put(k, tube([mast_top - Z * 0.15, jib_end + Z * 0.05], 0.02, 4, caps=False), ROPE, closed=False)  # the topping rope
    put(k, lathe([(0.11, 5.7), (0.11, 5.86)], 7, None, caps=(False, False)), jit(mix(P.iron, P.rust, 0.5), rng, 0.02), closed=False)
    # The winch: a drum between two cheeks on the mast, a crank each side.
    for e in (-1, 1):
        put(k, lbox(Vector((e * 0.3 - 0.03, -0.14, 0.75)), Vector((e * 0.3 + 0.03, 0.2, 1.25)), bevel=0.0), dark)
        put(k, tube([Vector((e * 0.33, 0.24, 1.02)), Vector((e * 0.52, 0.24, 1.02)), Vector((e * 0.52, 0.24, 1.26)), Vector((e * 0.7, 0.24, 1.26))], 0.018, 4), jit(mix(P.iron, P.rust, 0.5), rng, 0.02))
    put(k, B.cyl(Vector((-0.27, 0.24, 1.02)), Vector((0.27, 0.24, 1.02)), 0.11, 0.11, 8), wood)
    # The fall: from the drum up the mast, out along the jib and down to the stone.
    hook = jib_end - Z * 3.35
    put(k, tube([Vector((0.0, 0.28, 1.1)), Vector((0.0, 0.12, 5.6)), jib_end + Z * 0.02, hook], 0.016, 4, caps=False), ROPE, closed=False)
    if lot.get("load", True):
        s0 = Vector((0.0, hook.y, 0.42))
        put(k, lbox(Vector((-0.45, hook.y - 0.3, 0.42)), Vector((0.45, hook.y + 0.3, 0.86)), bevel=0.02), lambda co, nn, c=jit(P.basalt, rng, 0.03): mix(c, P.pale, 0.5) if nn.z > 0.5 else mix(c, P.pale, 0.2))
        for e in (-1, 1):
            put(k, tube([hook, Vector((e * 0.47, hook.y, 0.88)), Vector((e * 0.47, hook.y, 0.4)), s0 - Z * 0.02 + X * e * 0.1], 0.016, 4, caps=False), ROPE, closed=False)
        for x in (-0.3, 0.3):  # chocks it will be set down on
            put(k, lbox(Vector((x - 0.06, hook.y - 0.36, 0.0)), Vector((x + 0.06, hook.y + 0.36, 0.1)), open_bottom=True), dark)
    return dict(ridge_m=6.0)


def gen_kelp_kiln(k, rng, lot):
    """A kelp kiln on the Wrack Strand: a round pit ringed with beach stone, burnt red and black
    inside, a bed of grey ash, the rake left across it. Round, as everything that holds fire is."""
    r, n = lot["size"][0] / 2 - 0.45, 14
    for i in range(n):
        a = i / n * TAU
        S = Matrix.Translation((cos(a) * r, sin(a) * r, 0)) @ Matrix.Rotation(a, 4, "Z")
        hh = rng.uniform(0.5, 0.72)
        put(k, lbox(Vector((-0.24, -0.33, -0.3)), Vector((0.24, 0.33, hh)), fn=lambda q, S=S: S @ q, bevel=0.04),
            lambda co, nn, c=jit(P.basalt, rng, 0.03), b=jit(mix(P.brick, P.tar, 0.4), rng, 0.02): b if math.hypot(co.x, co.y) < r - 0.05 else (mix(c, P.pale, 0.4) if nn.z > 0.5 else c))
    ring = [Vector((cos(i / 12 * TAU) * (r - 0.2), sin(i / 12 * TAU) * (r - 0.2), 0.18)) for i in range(12)]
    raw(k, [(ring, jit(ASH, rng, 0.02))])
    if lot.get("load"):  # dried kelp heaped in for the next burn
        kelp_heap(k, rng, (0.2, -0.1, 0.18), r * 0.55, r * 0.5, 0.45, fronds=6)
    put(k, tube([Vector((-r + 0.1, 0.3, 0.8)), Vector((r * 0.4, -0.2, 0.3))], 0.02, 4), jit(P.drift, rng, 0.03))
    return dict(ridge_m=0.72)


# Pass 2's enclosure kinds and their own models.
ENCLOSURES_2 = dict(kiln_road=2500, graveyard=4500, crown_ground=2500, readers_yard=3000, dyke=2500, clay_pit=3000, boatyard=5000, kelp_stance=5000, peat_stance=3000, creel_stand=3000, fish_quay=3000)
GEN.update({kind: (gen_enclosure, budget) for kind, budget in ENCLOSURES_2.items()})
GEN.update(quarry_face=(gen_quarry_face, 1500), quarry_crane=(gen_quarry_crane, 1500), kelp_kiln=(gen_kelp_kiln, 1500), quarry_bench=(gen_enclosure, 3500))


def neighbours(plan):
    """Who stands against whom: a terrace's houses east to west (the plan's `terraces`), and the
    rank of net lofts. Each lot learns the lot on its west (-X) and east (+X) party wall."""
    by = {l["id"]: l for l in plan["lots"]}
    out = {}
    rows = list(plan["terraces"].values()) + [[f"net_loft_{i}" for i in range(1, 7)]]
    for members in rows:
        for i, lid in enumerate(members):
            out[lid] = dict(east=by.get(members[i - 1]) if i > 0 else None, west=by.get(members[i + 1]) if i + 1 < len(members) else None, row=[by[m] for m in members])
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--plan", default=PLAN)
    ap.add_argument("--only", help="comma-separated ids or folders (default: everything the kit can build)")
    ap.add_argument("--lantern-core", type=float, default=LANTERN["core_m"], help="metres from a glasshouse's lantern within which every pane is lit")
    ap.add_argument("--lantern-reach", type=float, default=LANTERN["reach_m"], help="metres from the lantern beyond which no pane catches its light")
    ap.add_argument("--join", action="append", default=[], help="also write a terrace of the plan (`terraces`: \"Low Row east\") as one model, <out>/terrace/<name>.glb, "
                    "for the asset board; the game uses the houses' own models, never this one")
    ap.add_argument("--figure", action="store_true", help="stand a 1.75 m figure by each model: for contact sheets only, never for the kit's own folder")
    a = ap.parse_args(argv)
    plan = json.load(open(a.plan))
    LANTERN.update(core_m=a.lantern_core, reach_m=a.lantern_reach)
    os.makedirs(a.out, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    near = neighbours(plan)
    items = [dict(l, what="lot") for l in plan["lots"] if l.get("model")] + [dict(f, what="fixture") for f in plan["fixtures"]]
    report, skipped, t_all = {}, [], time.time()
    ox, oy = plan["origin"]
    placed = []
    for it in items:
        folder = it["model"].split("/")[1]
        if folder not in GEN:
            skipped.append(it["id"])
            continue
        if it["what"] == "fixture":
            f = it["facing"]
            b = rad(FACING[f] if isinstance(f, str) else float(f))
            fx = dict(file=f"envs/{it['model']}", kind=folder, at=[round(ox + it["at"][0], 3), round(oy - it["at"][1], 3)], front=[round(sin(b), 5), round(-cos(b), 5)], floor=it["floor_m"], height=it["height_m"], size=it["size"])
            if folder == "quay_lamp":
                fx.update(light="lamp", glow=list(LIGHT["Glow"][0]))
            placed.append(fx)
        if only and it["id"] not in only and folder not in only:
            continue
        t0 = time.time()
        gen, budget = GEN[folder]
        B.reset()
        rng = random.Random(f"cullet-{it['seed']}-{it['id']}")
        k = Kit(rng, dict(glow=LIGHT["Glow"][0]), pr=random.Random(f"cullet-detail-{it['seed']}-{it['id']}"))
        DOORS.clear()
        it["near"] = near.get(it["id"], {})
        extra = gen(k, rng, it) or {}
        if a.figure:
            scale_figure(k, it, folder)
        # buildings.py centres a model on its bounds; a lot's model keeps the lot's own centre.
        xs, ys = [v.co.x for v in k.b.bm.verts], [v.co.y for v in k.b.bm.verts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        obj, _ = k.b.finish(it["id"])
        if not it.get("dressing"):  # street dressing is centred on its own rectangle, as props are
            obj.data.transform(Matrix.Translation((cx, cy, 0.0)))
        path = os.path.join(a.out, folder, f"{it['id']}.glb")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_vertex_color="ACTIVE", export_normals=True, export_yup=True, use_selection=False)
        rec = dict(file=f"{folder}/{it['id']}.glb", what=it["what"], kind=folder, size_m=it["size"], plan_height_m=it["height_m"], seed=it["seed"], **measure(obj))
        rec["budget_tris"] = budget
        rec["doors"] = [dict(d) for d in DOORS]
        rec["sha256"] = hashlib.sha256(open(path, "rb").read()).hexdigest()
        rec.update(extra)
        report[it["id"]] = rec
        print(f"GEN {it['id']}: tris={rec['tris']}/{budget} above={rec['above_floor_m']} h={rec['height_m']} tagged={rec['surface_tagged_share']} "
              f"palette={rec['palette_share']}+{rec['palette_wear_blend_share']} doors={len(DOORS)} {time.time() - t0:.2f}s")
    joined = {}
    for tname in a.join:
        # The same houses as above (the same seeds), stood side by side as the plan places them.
        members = [dict(l, what="lot") for l in plan["lots"] if l["id"] in plan["terraces"][tname] and l.get("model", "//").split("/")[1] in GEN]
        cx = (min(l["at"][0] - l["size"][0] / 2 for l in members) + max(l["at"][0] + l["size"][0] / 2 for l in members)) / 2
        cy = members[0]["at"][1]
        B.reset()
        objs = []
        for it in members:
            rng = random.Random(f"cullet-{it['seed']}-{it['id']}")
            k = Kit(rng, dict(glow=LIGHT["Glow"][0]), pr=random.Random(f"cullet-detail-{it['seed']}-{it['id']}"))
            it["near"] = near.get(it["id"], {})
            GEN[it["model"].split("/")[1]][0](k, rng, it)
            xs, ys = [v.co.x for v in k.b.bm.verts], [v.co.y for v in k.b.bm.verts]
            obj, _ = k.b.finish(it["id"])
            obj.data.transform(Matrix.Translation(((min(xs) + max(xs)) / 2 + it["at"][0] - cx, (min(ys) + max(ys)) / 2 + it["at"][1] - cy, 0.0)))
            objs.append(obj)
        for o in objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = objs[0]
        bpy.ops.object.join()
        slug = tname.lower().replace(" ", "_")
        path = os.path.join(a.out, "terrace", f"{slug}.glb")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_vertex_color="ACTIVE", export_normals=True, export_yup=True, use_selection=False)
        joined[slug] = dict(file=f"terrace/{slug}.glb", what="terrace", terrace=tname, houses=[it["id"] for it in members], households=[it.get("household_name", it.get("state", "")) for it in members],
                            fronts_m=[it["size"][0] for it in members], ridges_m=[it["height_m"] for it in members], **measure(objs[0]))
        joined[slug]["sha256"] = hashlib.sha256(open(path, "rb").read()).hexdigest()
        print(f"GEN {slug}: {len(members)} houses joined, tris={joined[slug]['tris']} above={joined[slug]['above_floor_m']}")
    print(f"GEN total {len(report)} models, {sum(r['tris'] for r in report.values())} triangles, {time.time() - t_all:.1f}s; not built (grey boxes): {len(skipped)}")
    if not only:
        with open(os.path.join(a.out, "fixtures.json"), "w") as f:
            json.dump(placed, f, indent=1)
        with open(os.path.join(a.out, "report.json"), "w") as f:
            json.dump(dict(script="living/tools/blender/cullet.py", plan="living/seeds/worlds/cullet/plan.json", blender=bpy.app.version_string, models=report, not_built=skipped, **joined), f, indent=1)


if __name__ == "__main__":
    main()
