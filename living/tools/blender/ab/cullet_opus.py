"""Cullet, the Opus arm of the model A/B (docs/SMALL_CITY.md, section 7): the Cone, a Low Row
terrace, a Ladder glasshouse and eight props for the Strand.

Run headless:
    blender -b -P living/tools/blender/ab/cullet_opus.py -- --out DIR --seed 1 [--only row,cone]

Writes cone.glb, row.glb, glasshouse.glb, net_rack.glb, barrels.glb, creels.glb, bollard.glb,
quay_lamp.glb, boat.glb, peat_stack.glb, floats.glb and report.json into DIR.

Conventions are buildings.py's, whose helpers this imports and never changes: metres for a
1.75 m person; origin at the floor, centred on the footprint; +Z up; fronts face -Y, which in
Cullet is south, to the sea, so west is -X and the weather (south-west) side is the front and
the -X end. Colour is per vertex on one white "Body" material with the painted surface in its
alpha. Glowing parts use "Glow" (oil lamp), "GlowAmber" (furnace) or "GlowCyan"; a glowing
pane's vertex colour is its daytime glass colour, and the material lights it at night.

Palette discipline: every colour is an entry of section 1 (PAL), jittered by at most 5%, and
nothing is shaded into the vertex colours (no painted ambient occlusion: the toon shader shades).
Wear is drawn as patches of other entries, each placed by a cause from section 1's wear table:
salt (rust streaks under iron, white bloom on stone), soot (above flues and furnace mouths), wind
(lichen, flaked lime and patched slates on south-west faces), feet, repair and abandonment.

The same --seed gives the same files: every choice draws from one stream per model.
"""

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
from contextlib import contextmanager

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import buildings as B  # noqa: E402
from buildings import X, Y, Z, Face, Kit, box, convex_hull, cyl, jitter, lbox, material, prism, sphere, tagged  # noqa: E402
from surfaces import alpha as surface_alpha  # noqa: E402  (buildings.py puts living/tools/textures on the path)

# ---------------------------------------------------------------------------------------------
# Palette (docs/SMALL_CITY.md section 1), each entry's painted surface, and the lights.

PAL = {
    "basalt": (0.24, 0.25, 0.28), "pale_basalt": (0.36, 0.37, 0.39), "limewash": (0.90, 0.89, 0.84), "old_lime": (0.78, 0.77, 0.71),
    "slate": (0.30, 0.34, 0.40), "new_slate": (0.38, 0.43, 0.50), "lichen": (0.72, 0.66, 0.30), "tar": (0.13, 0.12, 0.12),
    "driftwood": (0.52, 0.50, 0.46), "brick": (0.33, 0.20, 0.17), "new_brick": (0.58, 0.30, 0.22), "iron": (0.17, 0.17, 0.19),
    "rust": (0.50, 0.27, 0.15), "verdigris": (0.36, 0.62, 0.55),
    "green": (0.20, 0.42, 0.30), "amber": (0.78, 0.50, 0.16), "aqua": (0.62, 0.80, 0.78), "smoke": (0.55, 0.60, 0.62), "cobalt": (0.16, 0.26, 0.60),
    "oxblood": (0.45, 0.14, 0.13), "mustard": (0.78, 0.60, 0.18), "sea_green": (0.22, 0.45, 0.42), "chalk_blue": (0.50, 0.62, 0.72),
    "kelp": (0.30, 0.28, 0.12), "sand": (0.86, 0.82, 0.70), "peat": (0.20, 0.15, 0.11), "moor_grass": (0.52, 0.50, 0.28), "heather": (0.50, 0.34, 0.48),
    "furnace": (1.0, 0.45, 0.12), "oil_lamp": (1.0, 0.74, 0.40), "watchglass": (0.80, 0.95, 1.0),
}
SURF = dict(basalt="stone", pale_basalt="stone", limewash="plaster", old_lime="plaster", slate="shingles", new_slate="shingles",
            lichen="shingles", tar="planks", driftwood="wood", brick="brick", new_brick="brick", iron="metal", rust="metal",
            verdigris="copper", green="glass", amber="glass", aqua="glass", smoke="glass", cobalt="glass", oxblood="planks",
            mustard="planks", sea_green="planks", chalk_blue="planks", kelp="leaves", sand="earth", peat="earth",
            moor_grass="leaves", heather="leaves", furnace="glass", oil_lamp="glass", watchglass="glass")
# Glow material: (palette light, emission strength).
GLOWS = {"Glow": ("oil_lamp", 2.6), "GlowAmber": ("furnace", 5.0), "GlowCyan": ("watchglass", 4.0)}
GLASS = ("aqua", "smoke", "green", "amber")
MAX_PANE = 0.45


def C(name, surface=None):
    """A palette colour carrying its painted surface (salt bloom is limewash-white on stone...)."""
    return tagged(PAL[name], surface or SURF[name])


class M(Kit):
    """One model: buildings.py's Kit with Cullet's palette. Colours are never shaded (no painted
    AO, jitter at most 5%); `poly` paints a single polygon its own colour; `at` places parts."""

    def __init__(self, seed, name):
        super().__init__(random.Random(f"cullet-{seed}-{name}"), dict(glow=PAL["oil_lamp"], glass=C("smoke")), ao=1.0)
        self.name, self.style, self.xf, self.glows, self.facts = name, "cullet", None, {}, {}

    def add(self, bm, color, glow=False, soft=None, closed=True, vary=0.04, ao=True, tint=None):
        if self.xf is not None:
            bmesh.ops.transform(bm, matrix=self.xf, verts=bm.verts)
            soft = self.xf @ soft if soft is not None else None
        super().add(bm, color, glow, soft, closed, min(vary, 0.05), False, None)

    def put(self, bm, col, surface=None, vary=0.04, closed=True, soft=None):
        self.add(bm, C(col, surface) if isinstance(col, str) else col, vary=vary, closed=closed, soft=soft)

    def glow(self, name):
        if name not in self.glows:
            light, strength = GLOWS[name]
            self.glows[name] = material(name, (1, 1, 1), emission=PAL[light], strength=strength)
        return self.glows[name]

    def poly(self, pts, col, out=None, mat=None, vary=0.03):
        """One polygon in one colour (a palette name or colour), wound to face `out`."""
        if isinstance(col, str):
            col = C(col)
        if vary:
            col = jitter(col, self.rng, min(vary, 0.05))
        pts = [Vector(p) for p in pts]
        if self.xf is not None:
            pts = [self.xf @ p for p in pts]
            out = self.xf.to_3x3() @ Vector(out) if out is not None else None
        b = self.b
        mat = mat or self.body
        if mat not in b.mats:
            b.mats.append(mat)
        f = b.bm.faces.new([b.bm.verts.new(p) for p in pts])
        f.normal_update()
        if out is not None and f.normal.dot(Vector(out)) < 0:
            f.normal_flip()
        f.material_index = b.mats.index(mat)
        f[b.soft_layer] = 0
        a = surface_alpha(col.surface)
        for loop in f.loops:
            loop[b.col] = (*col, a)

    def pane(self, pts, glass, out, lit=False, mat="Glow"):
        self.facts.setdefault("glass_used", set()).add(glass)
        self.poly(pts, C(glass, "glass"), out, mat=self.glow(mat) if lit else None, vary=0.0 if lit else 0.02)

    @contextmanager
    def at(self, matrix):
        prev = self.xf
        self.xf = matrix if prev is None else prev @ matrix
        try:
            yield
        finally:
            self.xf = prev

    def chance(self, p):
        return self.rng.random() < p


def place(x=0.0, y=0.0, z=0.0, rz=0.0, rx=0.0, ry=0.0):
    return Matrix.Translation((x, y, z)) @ Matrix.Rotation(rz, 4, "Z") @ Matrix.Rotation(ry, 4, "Y") @ Matrix.Rotation(rx, 4, "X")


# ---------------------------------------------------------------------------------------------
# Shared shapes


def polar(a, r, z):
    return Vector((r * math.cos(a), r * math.sin(a), z))


def sector(a0, a1, r0, r1, z0, z1):
    """A box bent round the Z axis: angles a0..a1, radii r0..r1."""
    return lbox(Vector((a0, r0, z0)), Vector((a1, r1, z1)), fn=lambda q: polar(q.x, q.y, q.z))


class Wrapped(Face):
    """A wall face wrapped round the Z axis at radius rad(z): a runs round it, z up, w out. Boxes
    and outlines on it (Face.box, Face.poly) follow a round or tapering wall."""

    def __init__(self, ang, rad):
        self.ang, self.rad = ang, rad
        self.n, self.u = polar(ang, 1.0, 0.0), polar(ang + math.pi / 2, 1.0, 0.0)

    def p(self, a, z, w):
        r = self.rad(z)
        return polar(self.ang + a / r, r + w, z)


def lathe(m, rings, sides, paint, c=(0.0, 0.0), sy=1.0, phase=0.5, mat=None, vary=0.03):
    """A surface of revolution through rings [(r, z)]; paint(i, s, angle, z) colours each quad
    (ring band i, side s) or returns None to leave it out (an opening)."""
    for i in range(len(rings) - 1):
        (r0, z0), (r1, z1) = rings[i], rings[i + 1]
        for s in range(sides):
            a0, a1 = (s + phase) * math.tau / sides, (s + 1 + phase) * math.tau / sides
            am = (a0 + a1) / 2
            col = paint(i, s, am, (z0 + z1) / 2)
            if col is None:
                continue
            pts = [(c[0] + r * math.cos(a), c[1] + r * sy * math.sin(a), z) for r, a, z in ((r0, a0, z0), (r0, a1, z0), (r1, a1, z1), (r1, a0, z1))]
            if r0 < 1e-6:
                pts = pts[1:]
            elif r1 < 1e-6:
                pts = pts[:3]
            m.poly(pts, col, (math.cos(am) * (z1 - z0), math.sin(am) * (z1 - z0), r0 - r1), mat=mat, vary=vary)


def plain(col):
    c = C(col) if isinstance(col, str) else col
    return lambda i, s, a, z: c


def tube(m, pts, r, col, sides=4, vary=0.03):
    """A rope, pipe or rail along a polyline."""
    pts = [Vector(p) for p in pts]
    bm = bmesh.new()
    rings = []
    for i, p in enumerate(pts):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        u = t.cross(Z if abs(t.z) < 0.9 else X).normalized()
        v = t.cross(u)
        rings.append([bm.verts.new(p + (u * math.cos(k * math.tau / sides) + v * math.sin(k * math.tau / sides)) * r) for k in range(sides)])
    for a, b in zip(rings, rings[1:]):
        for k in range(sides):
            bm.faces.new([a[k], a[(k + 1) % sides], b[(k + 1) % sides], b[k]])
    m.put(bm, col, vary=vary, closed=False)


def blob(m, f, a, z, rx, rz, col, w=0.012, n=7):
    """An irregular patch on a face: flaked lime, lichen, salt bloom, soot."""
    pts = []
    for i in range(n):
        t, k = i / n * math.tau, m.rng.uniform(0.62, 1.0)
        pts.append(f.p(a + math.cos(t) * rx * k, z + math.sin(t) * rz * k, w))
    m.poly(pts, col, f.n)


def flake(m, f, a, z, size, col, w=0.012):
    """Weathered render: a cluster of overlapping patches, wider than tall, ragged at its edge."""
    for _ in range(m.rng.randint(3, 5)):
        blob(m, f, a + m.rng.uniform(-size, size), z + m.rng.uniform(-0.4, 0.4) * size, size * m.rng.uniform(0.45, 0.8),
             size * m.rng.uniform(0.25, 0.45), col, w, 6)


def bloom(m, f, a0, a1, z, h, col, w=0.012):
    """Salt efflorescence: a ragged pale band rising a little from the foot of a wall."""
    n = max(3, round((a1 - a0) / 0.25))
    top = [f.p(a0 + (a1 - a0) * i / n, z + h * m.rng.uniform(0.3, 1.0) * math.sin(math.pi * i / n) ** 0.5, w) for i in range(n, -1, -1)]
    m.poly([f.p(a0, z, w), f.p(a1, z, w)] + top[1:-1], col, f.n)


def lichens(m, P, N, spots, h=0.075):
    """Lichen on slates or stone: small clusters of rosettes on a surface P(a, t, h)."""
    for a, t, r in spots:
        for _ in range(m.rng.randint(1, 3)):
            ca, ct, rr = a + m.rng.uniform(-r, r), t + m.rng.uniform(-r, r) * 0.6, r * m.rng.uniform(0.4, 0.8)
            m.poly([P(ca + math.cos(k * math.tau / 6) * rr * m.rng.uniform(0.7, 1.0), ct + math.sin(k * math.tau / 6) * rr * 0.7, h) for k in range(6)],
                   C("lichen"), N)


def streak(m, f, a, z, length, col, width=0.08, w=0.01):
    """A stain running down a face from (a, z): rust under iron."""
    d = m.rng.uniform(-0.03, 0.03)
    m.poly([f.p(a - width / 2, z, w), f.p(a + width / 2, z, w), f.p(a + d + width * 0.15, z - length, w), f.p(a + d - width * 0.15, z - length, w)], col, f.n)


def clear(holes, a, z, rx, rz, pad=0.12):
    return all(a + rx < a0 - pad or a - rx > a1 + pad or z + rz < z0 - pad or z - rz > z1 + pad for a0, a1, z0, z1 in holes)


def tufts(m, pts, r=0.09, cols=("moor_grass",)):
    """Weeds, greens and kelp: small soft clumps."""
    for i, p in enumerate(pts):
        rr = r * m.rng.uniform(0.75, 1.25)
        c = Vector(p) + Z * rr * 0.4
        m.put(sphere(c, rr, 0, squash=0.7), cols[i % len(cols)], soft=c)


def slope(m, top, A, D, L, S, paint, course=0.36, th=0.05, deck="tar", gap=0.006):
    """One slate roof slope: its top edge runs from `top` along unit A for L and it falls along
    unit D for S. Courses of slates lie on a dark deck; each course is a few pieces of uneven
    width, whose butts stand proud of the course below. paint(a, t) gives a piece's colour, or
    None for missing slates (the deck and battens show). Returns (point(a, t, h), normal)."""
    top, A, D = Vector(top), Vector(A).normalized(), Vector(D).normalized()
    N = A.cross(D)
    if N.z < 0:
        N = -N

    def P(a, t, h):
        return top + A * a + D * t + N * h
    m.put(lbox(Vector((0.0, -0.02, -0.14)), Vector((L, S, 0.0)), fn=lambda q: P(q.x, q.y, q.z)), deck, vary=0.02)
    n = max(2, round(S / course))
    missing = []
    for i in range(n):
        t0, t1 = S * i / n - 0.04, S * (i + 1) / n
        a = 0.0
        while a < L - 1e-3:
            a1 = a + m.rng.uniform(0.45, 1.05)
            a1 = L if L - a1 < 0.3 else a1
            col = paint(a + (a1 - a) / 2, (t0 + t1) / 2)
            if col is None:
                missing.append((a, a1, t0, t1))
            else:
                jt, h1 = m.rng.uniform(-0.025, 0.02), th * m.rng.uniform(0.8, 1.25)
                q = [P(a + gap, t0, 0.008), P(a1 - gap, t0, 0.008), P(a1 - gap, t1 + jt, h1), P(a + gap, t1 + jt, h1)]
                m.poly(q, col, N)
                m.poly([q[3], q[2], P(a1 - gap, t1 + jt, 0.0), P(a + gap, t1 + jt, 0.0)], col, D)
            a = a1
    for a0, a1, t0, t1 in missing:
        # Battens across the gap a missing slate leaves.
        for tb in (t0 + 0.08, t1 - 0.1):
            m.put(lbox(Vector((a0, tb, 0.0)), Vector((a1, tb + 0.05, 0.03)), fn=lambda q: P(q.x, q.y, q.z)), "driftwood")
    m.facts["missing_slates"] = m.facts.get("missing_slates", 0) + len(missing)
    return P, N


def grid(w, h, bar=0.04, frame=0.06):
    """Columns and rows of panes no larger than MAX_PANE in a w x h opening: (cols, rows, pw, ph)."""
    gw, gh = w - 2 * frame, h - 2 * frame
    cols, rows = max(1, math.ceil((gw + bar) / (MAX_PANE + bar))), max(1, math.ceil((gh + bar) / (MAX_PANE + bar)))
    return cols, rows, (gw - (cols - 1) * bar) / cols, (gh - (rows - 1) * bar) / rows


def window(m, f, a, z0, w, h, glass, patch=None, lit=False, frame="driftwood", R=0.2, missing=(), sill=True, lintel=True):
    """A small-paned window in a hole cut by wall_skin: panes at most 0.45 m in `glass`, one or
    two of them replaced in `patch` (never more than two colours); missing panes show the dark
    room behind. Returns the hole."""
    bar, fw = 0.04, 0.06
    cols, rows, pw, ph = grid(w, h, bar, fw)
    m.facts["max_pane"] = max(m.facts.get("max_pane", 0.0), pw, ph)
    n = cols * rows
    patched = set(m.rng.sample(range(n), min(n, 1 + (n > 4)))) if patch else set()
    wp = -R + 0.04
    for i in range(cols):
        for j in range(rows):
            k = j * cols + i
            if k in missing:
                continue
            pa, pz = a - w / 2 + fw + i * (pw + bar), z0 + fw + j * (ph + bar)
            m.pane([f.p(pa, pz, wp), f.p(pa + pw, pz, wp), f.p(pa + pw, pz + ph, wp), f.p(pa, pz + ph, wp)], patch if k in patched else glass, f.n, lit)
    m.facts.setdefault("window_glass", []).append(sorted({glass} | ({patch} if patched else set())))
    for b0, b1, c0, c1 in ((a - w / 2, a + w / 2, z0, z0 + fw), (a - w / 2, a + w / 2, z0 + h - fw, z0 + h),
                           (a - w / 2, a - w / 2 + fw, z0, z0 + h), (a + w / 2 - fw, a + w / 2, z0, z0 + h)):
        m.put(f.box(b0, b1, c0, c1, -R, -R + 0.09), frame)
    for i in range(1, cols):
        ba = a - w / 2 + fw + i * (pw + bar) - bar
        m.put(f.box(ba, ba + bar, z0 + fw, z0 + h - fw, wp - 0.01, wp + 0.03, back=False), frame)
    for j in range(1, rows):
        bz = z0 + fw + j * (ph + bar) - bar
        m.put(f.box(a - w / 2 + fw, a + w / 2 - fw, bz, bz + bar, wp - 0.01, wp + 0.03, back=False), frame)
    if missing:
        m.poly([f.p(a - w / 2, z0, -R - 0.3), f.p(a + w / 2, z0, -R - 0.3), f.p(a + w / 2, z0 + h, -R - 0.3), f.p(a - w / 2, z0 + h, -R - 0.3)], "tar", f.n)
    if sill:
        m.put(f.box(a - w / 2 - 0.08, a + w / 2 + 0.08, z0 - 0.1, z0 + 0.01, -R, 0.07), "pale_basalt")
    if lintel:
        m.put(f.box(a - w / 2 - 0.12, a + w / 2 + 0.12, z0 + h, z0 + h + 0.2, -0.01, 0.025), "pale_basalt")
    return (a - w / 2, a + w / 2, z0, z0 + h)


def plank_door(m, f, a, z0, col, frame, R=0.2, light=None, lit=False):
    """A ledged plank door, exactly 0.9 x 2.0 m, in a reveal, with strap hinges and a latch; a
    two-pane light over it if `light` names its glass. Returns the hole."""
    for i in range(3):
        a0 = a - 0.45 + i * 0.3
        m.put(f.box(a0, a0 + 0.3, z0, z0 + 2.0, -R, -R + 0.05 + m.rng.uniform(0, 0.012)), col, vary=0.05)
    for zh in (z0 + 0.32, z0 + 1.62):
        m.put(f.box(a - 0.44, a + 0.12, zh, zh + 0.05, -R + 0.06, -R + 0.075, back=False), "iron")
    m.put(f.box(a + 0.3, a + 0.36, z0 + 0.98, z0 + 1.04, -R + 0.06, -R + 0.1), "iron")
    m.facts.setdefault("doors", []).append([0.9, 2.0])
    top = z0 + 2.06
    m.put(f.box(a - 0.51, a - 0.45, z0, top, -R, -R + 0.1), frame)
    m.put(f.box(a + 0.45, a + 0.51, z0, top, -R, -R + 0.1), frame)
    m.put(f.box(a - 0.51, a + 0.51, z0 + 2.0, top, -R, -R + 0.1), frame)
    if light:
        for e in (-1, 1):
            pa = a + (0.02 if e > 0 else -0.43)
            m.pane([f.p(pa, top + 0.04, -R + 0.04), f.p(pa + 0.41, top + 0.04, -R + 0.04), f.p(pa + 0.41, top + 0.3, -R + 0.04), f.p(pa, top + 0.3, -R + 0.04)], light, f.n, lit)
        m.put(f.box(a - 0.02, a + 0.02, top, top + 0.34, -R + 0.03, -R + 0.08, back=False), frame)
        m.put(f.box(a - 0.51, a + 0.51, top + 0.3, top + 0.36, -R, -R + 0.1), frame)
        top += 0.36
    m.put(f.box(a - 0.62, a + 0.62, top, top + 0.22, -0.01, 0.03), "pale_basalt")
    return (a - 0.51, a + 0.51, z0, top)


def footing(m, depth):
    """buildings.py's stepped foundation, in palette stone: courses under the ground outline,
    the top one flush and pale, each lower one 2 cm wider (so the lot's footprint stays within
    0.1 m of the model's)."""
    hull = convex_hull([(v.co.x, v.co.y) for v in m.b.bm.verts if v.co.z <= 0.05])
    if len(hull) < 3 or depth <= 0:
        return
    cx, cy = sum(p[0] for p in hull) / len(hull), sum(p[1] for p in hull) / len(hull)
    courses = max(2, round(depth / 0.6))
    for i in range(courses):
        z1, z0 = -0.01 - i * depth / courses, -0.01 - (i + 1) * depth / courses
        ring = []
        for x, y in hull:
            dx, dy = x - cx, y - cy
            ln = max(math.hypot(dx, dy), 1e-6)
            ring.append((x + dx / ln * 0.02 * i, y + dy / ln * 0.02 * i))
        bm = bmesh.new()
        bot, top = [bm.verts.new((x, y, z0)) for x, y in ring], [bm.verts.new((x, y, z1)) for x, y in ring]
        bm.faces.new(bot[::-1])
        bm.faces.new(top)
        for a in range(len(ring)):
            b = (a + 1) % len(ring)
            bm.faces.new([bot[a], bot[b], top[b], top[a]])
        m.put(bm, "pale_basalt" if i % 2 == 0 else "basalt", vary=0.02)


# ---------------------------------------------------------------------------------------------
# 1. The Cone


def cone(m):
    """The glass furnace: a sooted brick cone on a basalt plinth, three arched mouths (the
    front one working and glowing, the others shut with rusting iron doors), five iron bands, a
    lean-to pot room on the west, a timber stair hugging the cone up to a gallery and the
    charging door at 7 m. Soot fans above the mouths and down from the rim; the crack between
    two bands on the south-west side was rebuilt in newer, redder brick."""
    H, R0, RB, RT, RI = 24.0, 7.0, 6.85, 2.4, 1.6

    def r(z):
        if z < 1.2:
            return R0
        return RT + (RB - RT) * (1 - min(1.0, (z - 1.2) / (H - 1.2))) ** 1.2
    SIDES = 48
    mouths = [(-90.0, True), (30.0, False), (150.0, False)]

    def off(a, deg):
        return (math.degrees(a) - deg + 180.0) % 360.0 - 180.0
    ragged = [m.rng.uniform(-1.0, 1.0) for _ in range(SIDES)]
    zs = [1.2, 1.9, 2.65, 3.4] + [3.4 + (H - 0.6 - 3.4) * k / 28 for k in range(1, 29)]
    rings = [(R0, 0.0), (R0, 1.2)] + [(r(z), z) for z in zs] + [(RT + 0.22, H - 0.45), (RT + 0.22, H), (RI, H), (RI, H - 2.2)]

    def paint(i, s, a, z):
        if z < 3.4 and any(abs(off(a, d)) < 15 for d, _ in mouths):
            return None
        if i == 0:
            return C("basalt")
        if i == 1:
            return C("pale_basalt")
        if z > H - 4.0 + 0.9 * ragged[s]:
            return C("tar", "brick")  # soot from the rim
        for d, lit in mouths:
            # Soot fan above a mouth: narrow at the arch, spreading as it rises, ragged and
            # thinning towards its top.
            reach = (5.6 if lit else 3.2) + 0.8 * ragged[s]
            u = (z - 3.4) / reach
            wdt = (7.0 + (z - 3.4) * (4.5 if lit else 3.0)) * (1.0 - 0.35 * u)
            if 0 <= u < 1 and abs(off(a, d)) < wdt and m.chance(1.0 - 0.8 * u ** 2 if abs(off(a, d)) < 0.6 * wdt else 0.55 - 0.5 * u):
                return C("tar", "brick")
        dz = 0.5 * ragged[(s + 11) % SIDES]
        o = abs(off(a, 225.0))
        if 9.0 + dz <= z <= 12.0 - dz and (o < 16.0 or (o < 30.0 and m.chance(0.55 - (o - 16.0) / 30.0))):
            return C("new_brick")  # the rebuilt crack, south-west
        return C("brick")
    lathe(m, rings, SIDES, paint)
    for zb in (5.0, 8.4, 12.4, 16.2, 20.0):
        # Ship iron, rusting worst on the weather side.
        z1 = zb + 0.22
        lathe(m, [(r(zb) + 0.07, zb), (r(z1) + 0.07, z1), (r(z1) - 0.05, z1)], SIDES,
              lambda i, s, a, z: C("rust") if (abs(off(a, 225.0)) < 28.0 + 14.0 * ragged[s] and m.chance(0.7)) or m.chance(0.04) else C("iron"))
    m.facts.update(base_m=2 * R0, rim_m=H, rim_opening_m=2 * RI, mouth_m=[2.4, 3.0], bands=5, charging_door_z=7.0)

    # The mouths: jambs, spandrels and a pale voussoir arch on a wall bent to the cone, a tunnel
    # into the furnace, its back glowing at the working mouth and dark behind iron doors.
    for d, lit in mouths:
        lo, hi = Wrapped(math.radians(d), lambda z: R0), Wrapped(math.radians(d), lambda z: r(max(z, 1.2)))
        for e in (-1, 1):
            a0, a1 = sorted((e * 1.2, e * 2.0))
            m.put(lo.box(a0, a1, 0.0, 1.2, -0.9, 0.06), "basalt")
            m.put(hi.box(a0, a1, 1.2, 3.4, -0.9, 0.06), "brick")
            arc = [(e * 1.2 * math.cos(math.radians(t)), 1.8 + 1.2 * math.sin(math.radians(t))) for t in range(0, 91, 15)]
            pts = [(e * 1.2, 1.8)] + arc[1:] + [(0.0, 3.4), (e * 1.2, 3.4)]
            m.put(hi.poly(pts if e > 0 else pts[::-1], -0.9, 0.06), "tar" if lit else "brick", surface="brick")
        for k in range(9):
            t0, t1 = math.pi * k / 9, math.pi * (k + 1) / 9
            pts = [(1.2 * math.cos(t0), 1.8 + 1.2 * math.sin(t0)), (1.62 * math.cos(t0), 1.8 + 1.62 * math.sin(t0)),
                   (1.62 * math.cos(t1), 1.8 + 1.62 * math.sin(t1)), (1.2 * math.cos(t1), 1.8 + 1.2 * math.sin(t1))]
            m.put(hi.poly(pts, -0.05, 0.16), "tar" if lit and 3 <= k <= 5 else "pale_basalt", surface="stone")
        outline = [(-1.18, 0.0), (-1.18, 1.8)] + [(1.18 * math.cos(math.radians(t)), 1.8 + 1.18 * math.sin(math.radians(t))) for t in range(165, 0, -15)] + [(1.18, 1.8), (1.18, 0.0)]
        for (pa, pz), (qa, qz) in zip(outline, outline[1:]):
            mid = Vector(((pa + qa) / 2, (pz + qz) / 2))
            inward = Vector((0.0, 1.4)) - mid
            m.poly([hi.p(pa, pz, -0.9), hi.p(qa, qz, -0.9), hi.p(qa, qz, -2.3), hi.p(pa, pz, -2.3)], C("tar", "brick"),
                   hi.u * inward.x + Z * inward.y)
        back = [hi.p(a, z, -2.3) for a, z in outline]
        m.poly(back, C("tar", "brick"), hi.n)
        if lit:
            # The furnace's own mouth deep in the dark arch, and its glow on the floor.
            inner = [(-0.7, 0.0), (0.7, 0.0)] + [(0.7 * math.cos(math.radians(t)), 1.1 + 0.7 * math.sin(math.radians(t))) for t in range(0, 181, 20)]
            m.poly([hi.p(pa, pz, -2.28) for pa, pz in inner], C("furnace", "glass"), hi.n, mat=m.glow("GlowAmber"), vary=0)
            m.poly([hi.p(-0.9, 0.03, -2.3), hi.p(0.9, 0.03, -2.3), hi.p(0.9, 0.03, -1.7), hi.p(-0.9, 0.03, -1.7)], C("furnace", "glass"), Z, mat=m.glow("GlowAmber"), vary=0)
        else:
            # Shut: one rusting iron leaf closed, one folded back against the jamb.
            m.put(hi.box(-1.16, 0.0, 0.0, 2.25, -0.5, -0.44), "rust")
            m.put(hi.box(1.08, 1.15, 0.0, 2.25, -0.44, 0.72), "rust")
            for zz in (0.4, 1.7):
                m.put(hi.box(-1.16, -0.05, zz, zz + 0.09, -0.44, -0.42, back=False), "iron")
        m.poly([hi.p(-1.18, 0.02, 0.06), hi.p(1.18, 0.02, 0.06), hi.p(1.18, 0.02, -2.3), hi.p(-1.18, 0.02, -2.3)], "pale_basalt" if lit else "basalt", Z)
    # Salt bloom on the plinth (the Cone stands on the quay, below +6 m).
    for k in range(9):
        a = math.radians(m.rng.uniform(-180, 180))
        if any(abs(off(a, d)) < 22 for d, _ in mouths):
            continue
        bloom(m, Wrapped(a, lambda z: R0), -m.rng.uniform(0.4, 0.9), m.rng.uniform(0.4, 0.9), 0.0, m.rng.uniform(0.15, 0.4), C("limewash", "stone"))

    # The charging door at 7 m, its gallery and the stair up to it.
    zg = 7.0
    ga0, ga1 = math.radians(-8.0), math.radians(22.0)
    rin, rout = r(zg) - 0.3, r(zg) + 1.5
    for k in range(6):
        a0 = ga0 + (ga1 - ga0) * k / 6
        m.put(sector(a0, a0 + (ga1 - ga0) / 6 - 0.002, rin, rout, zg - 0.1, zg), "driftwood")
    rail = [polar(ga0 + (ga1 - ga0) * k / 6, rout - 0.06, zg + 1.0) for k in range(7)]
    for k, p in enumerate(rail):
        m.put(cyl(p - Z * 1.0, p, 0.045, 0.045, 4), "driftwood")
        if k % 2 == 0:
            m.put(cyl(polar(ga0 + (ga1 - ga0) * k / 6, r(5.5), 5.5), polar(ga0 + (ga1 - ga0) * k / 6, rout - 0.2, zg - 0.1), 0.06, 0.06, 4), "driftwood")
    tube(m, rail, 0.04, "driftwood")
    tube(m, [polar(ga1, rout - 0.06, zg + 1.0), polar(ga1, rin + 0.3, zg + 1.0)], 0.04, "driftwood")
    m.put(cyl(polar(ga1, rin + 0.35, zg), polar(ga1, rin + 0.35, zg + 1.0), 0.045, 0.045, 4), "driftwood")
    door = Wrapped(math.radians(7.0), r)
    arch = [(-0.55, zg), (0.55, zg)] + [(0.55 * math.cos(math.radians(t)), zg + 1.5 + 0.55 * math.sin(math.radians(t))) for t in range(0, 181, 30)]
    m.put(door.poly(arch, -0.1, 0.03), "tar", surface="brick")
    for k in range(7):
        t0, t1 = math.pi * k / 7, math.pi * (k + 1) / 7
        m.put(door.poly([(0.55 * math.cos(t0), zg + 1.5 + 0.55 * math.sin(t0)), (0.85 * math.cos(t0), zg + 1.5 + 0.85 * math.sin(t0)),
                         (0.85 * math.cos(t1), zg + 1.5 + 0.85 * math.sin(t1)), (0.55 * math.cos(t1), zg + 1.5 + 0.55 * math.sin(t1))], -0.05, 0.12), "new_brick")
    m.put(door.box(-0.85, -0.55, zg, zg + 1.5, -0.05, 0.1), "new_brick")
    m.put(door.box(0.55, 0.85, zg, zg + 1.5, -0.05, 0.1), "new_brick")
    m.put(door.box(0.95, 1.95, zg + 0.05, zg + 1.75, 0.08, 0.13), "rust")  # the iron door, folded back
    for zz in (zg + 0.3, zg + 1.4):
        m.put(door.box(0.6, 1.9, zz, zz + 0.08, 0.13, 0.15, back=False), "iron")
    n = 38
    rise, s0 = zg / n, math.radians(-70.0)
    edge, posts = [], []
    for i in range(n):
        z1 = rise * (i + 1)
        a0, a1 = s0 + (ga0 - s0) * i / n, s0 + (ga0 - s0) * (i + 1) / n
        ri = r(z1) + 0.12
        m.put(sector(a0, a1 + 0.004, ri, ri + 1.0, z1 - 0.07, z1), "driftwood")
        edge.append(polar(a0, ri + 1.03, z1 - 0.16))
        if i % 5 == 2:
            posts.append((polar(a0, ri + 0.95, 0.0), polar(a0, ri + 0.95, z1 - 0.07), polar(a0, ri + 0.95, z1 + 0.95)))
    edge.append(polar(ga0, r(zg) + 1.15, zg - 0.16))
    tube(m, edge, 0.06, "driftwood")
    for foot, tread, hand in posts:
        m.put(cyl(foot, tread, 0.06, 0.06, 4), "driftwood")
        m.put(cyl(tread, hand, 0.04, 0.04, 4), "driftwood")
    tube(m, [p[2] for p in posts] + [rail[0]], 0.035, "driftwood")

    # The pot room: a basalt lean-to on the west, its slates on the weather side, a lit window.
    xo, xi, y0, y1, zo, zi = -11.0, -5.2, -2.5, 2.5, 2.55, 4.8
    m.put(box((xo, y0, 0), (xo + 0.45, y1, zo)), "basalt")
    for ya, yb in ((y0, y0 + 0.45), (y1 - 0.45, y1)):
        m.put(prism([(xo, 0.0), (xi, 0.0), (xi, zi), (xo, zo)], ya, yb, lambda a, s, z: Vector((s, a, z))), "basalt")
    pitch = math.atan2(zi - zo, xi - xo)
    Dp = Vector((-math.cos(pitch), 0, -math.sin(pitch)))
    Np = Vector((-math.sin(pitch), 0, math.cos(pitch)))
    Sp = (xi - xo + 0.22) / math.cos(pitch)
    P, N = slope(m, Vector((xi, y0 - 0.12, zi)) + Np * 0.14, Y, Dp, (y1 - y0) + 0.24, Sp, lambda a, t: C("new_slate") if m.chance(0.14) else C("slate"))
    # The pot room's slope faces the weather (west): lichen towards its eave.
    lichens(m, P, N, [(m.rng.uniform(0.6, 4.6), Sp * m.rng.uniform(0.45, 0.85), m.rng.uniform(0.15, 0.28)) for _ in range(9)])
    front = Face((-8.4, y0, 0), X, 5.6)
    a = -9.3 + 8.4
    for i in range(3):
        m.put(front.box(a - 0.45 + i * 0.3, a - 0.15 + i * 0.3, 0.0, 2.0, 0.0, 0.05), "tar", vary=0.05)
    m.put(front.box(a - 0.55, a + 0.55, 2.0, 2.12, 0.0, 0.08), "driftwood")
    for e in (-1, 1):
        m.put(front.box(a + e * 0.5 - 0.05, a + e * 0.5 + 0.05, 0.0, 2.0, 0.0, 0.08), "driftwood")
    side = Face((xo, 0.0, 0), -Y, 5.0)
    cols, rows, pw, ph = grid(0.9, 0.86)
    for i in range(cols):
        for j in range(rows):
            pa, pz = -0.45 + 0.06 + i * (pw + 0.04), 1.15 + 0.06 + j * (ph + 0.04)
            m.pane([side.p(pa, pz, 0.03), side.p(pa + pw, pz, 0.03), side.p(pa + pw, pz + ph, 0.03), side.p(pa, pz + ph, 0.03)], "smoke", side.n, True, "GlowAmber")
    for b0, b1, c0, c1 in ((-0.51, 0.51, 1.09, 1.15), (-0.51, 0.51, 2.01, 2.07), (-0.51, -0.45, 1.09, 2.07), (0.45, 0.51, 1.09, 2.07), (-0.02, 0.02, 1.15, 2.01)):
        m.put(side.box(b0, b1, c0, c1, 0.0, 0.07), "driftwood")
    m.put(side.box(-0.6, 0.6, 2.07, 2.22, 0.0, 0.04), "pale_basalt")


# ---------------------------------------------------------------------------------------------
# 2. A Low Row terrace


ROW_WEAR = dict(salt=0.6, soot=0.1, wind=0.7)
# West (uphill) to east. g: street at the house above the lowest street; eave and ridge are
# measured from the house's own street; door and window positions from its west party wall.
HOUSES = [
    dict(name="tidy", w=5.0, g=1.5, eave=5.75, pitch=47, door="chalk_blue", frame="limewash", wall="limewash", glass="aqua", patch=None,
         door_a=3.75, win_a=1.45, up_a=(1.45, 3.75), lit={"ground", "light"}, flakes=1, repair=0.10),
    dict(name="fisher", w=6.0, g=1.0, eave=5.95, pitch=45, door="oxblood", frame="driftwood", wall="old_lime", glass="smoke", patch="green",
         door_a=1.85, win_a=4.3, up_a=(1.85, 4.3), lit={"ground"}, flakes=3, repair=0.06),
    dict(name="empty", w=4.5, g=0.5, eave=5.6, pitch=48, door="driftwood", frame="driftwood", wall="old_lime", glass="smoke", patch=None,
         door_a=3.4, win_a=1.6, up_a=(1.6, 3.4), lit=set(), flakes=7, repair=0.0),
    dict(name="crowded", w=6.5, body=4.7, g=0.0, eave=5.85, pitch=46, door="mustard", frame="driftwood", wall="limewash", glass="aqua", patch="amber",
         door_a=1.65, win_a=3.6, up_a=(1.65, 3.6), lit={"ground", "up1", "dormer", "back", "lean"}, flakes=3, repair=0.08),
]


def row(m):
    """Four houses sharing walls on a street that drops 0.5 m at each party wall, so floors,
    eaves and ridges step down to the east. Skew gables with coping stones (no verges in the
    wind), a brick chimney on each party wall, basalt ground floors, limewashed upper floors,
    slate roofs; told apart by their doors, keepsakes, care and wear."""
    W = ROW_WEAR
    YF, YB, YP, YR, HALF, R = -2.75, 3.45, -3.75, 0.35, 3.1, 0.2
    x = -11.0
    for h in HOUSES:
        h["x0"], h["x1"] = x, x + h["w"]
        h["xb"] = x + h.get("body", h["w"])
        x += h["w"]
        h["f"] = h["g"] + 0.36
        h["s1"] = h["f"] + 2.75
        h["ze"] = h["g"] + h["eave"]
        h["p"] = math.radians(h["pitch"])
        h["zr"] = h["ze"] + HALF * math.tan(h["p"])  # the deck's underside at the ridge
        h["top"] = h["zr"] + 0.27  # the slates' and gable's top at the ridge
    m.facts["houses"] = []

    for k, h in enumerate(HOUSES):
        x0, x1, xb, g, f, s1, ze, p = h["x0"], h["x1"], h["xb"], h["g"], h["f"], h["s1"], h["ze"], h["p"]
        L, cx = xb - x0, (x0 + xb) / 2
        name = h["name"]
        # The street: a basalt plinth up to this house's level, worn flags and a kerb, and steps
        # down from the house above at the party wall.
        if g > 0:
            m.put(box((x0, YP, 0), (x1, YB, g)), "basalt")
        m.put(box((x0, YP, g), (x1, YF, g + 0.04)), "pale_basalt")
        m.put(box((x0, YP, g), (x1, YP + 0.2, g + 0.08)), "pale_basalt")
        if k > 0:
            dz = HOUSES[k - 1]["g"] - g
            for j, wdt in ((1, 0.6), (2, 0.3)):
                m.put(box((x0, YP, g), (x0 + wdt, YF, g + dz * j / 3)), "pale_basalt")
        F = Face((cx, YF, 0), X, L)
        Bk = Face((cx, YB, 0), -X, L)

        def at(xx):
            return xx - cx
        lit = h["lit"]
        hg, hu = [], []
        # Stoop, door and ground window.
        da = at(x0 + h["door_a"])
        m.put(F.box(da - 0.75, da + 0.75, g, g + 0.18, 0.0, 0.6), "pale_basalt")
        m.put(F.box(da - 0.65, da + 0.65, g + 0.18, f, 0.0, 0.3), "pale_basalt")
        hg.append(plank_door(m, F, da, f, h["door"], h["frame"], R, light=None if name == "empty" else h["glass"], lit="light" in lit))
        wa = at(x0 + h["win_a"])
        ww = 1.25 if name == "fisher" else 0.95
        if name == "empty":
            hole = (wa - ww / 2, wa + ww / 2, f + 0.85, f + 2.1)
            hg.append(hole)
            m.poly([F.p(hole[0], hole[2], -R), F.p(hole[1], hole[2], -R), F.p(hole[1], hole[3], -R), F.p(hole[0], hole[3], -R)], "tar", F.n)
            for j in range(4):
                zz = f + 0.8 + j * 0.34
                m.put(F.obox(wa + m.rng.uniform(-0.04, 0.04), zz + 0.15, ww + 0.22, 0.3, 0.0, 0.035, m.rng.uniform(-0.05, 0.05)), "driftwood", vary=0.05)
            m.put(F.obox(wa, f + 1.45, 1.45, 0.12, 0.035, 0.06, 0.75), "driftwood")
            m.put(F.box(wa - ww / 2 - 0.08, wa + ww / 2 + 0.08, f + 0.75, f + 0.86, -R, 0.07), "pale_basalt")
            m.put(F.box(wa - ww / 2 - 0.12, wa + ww / 2 + 0.12, f + 2.1, f + 2.3, -0.01, 0.025), "pale_basalt")
            # The door boarded across, weeds on the stoop and along the wall foot.
            m.put(F.obox(da, f + 1.1, 1.25, 0.16, -R + 0.06, -R + 0.1, -0.9), "driftwood")
            tufts(m, [F.p(da + e * m.rng.uniform(0.3, 0.7), zz, ws) for e in (-1, 1) for zz, ws in ((g + 0.18, 0.48), (f, 0.16))]
                  + [F.p(m.rng.uniform(-L / 2 + 0.2, L / 2 - 0.2), g + 0.04, 0.08) for _ in range(4)], 0.1)
        else:
            hg.append(window(m, F, wa, f + 0.85, ww, 1.25, h["glass"], h["patch"], "ground" in lit, h["frame"], R))
        # Upper windows (the empty house has lost panes).
        for j, ua in enumerate(h["up_a"]):
            miss = (1, 4) if name == "empty" and j == 0 else ()
            hu.append(window(m, F, at(x0 + ua), s1 + 0.75, 0.9, 1.15, h["glass"], h["patch"], f"up{j}" in lit, h["frame"], R, missing=miss))
        for zz0, zz1, holes, col in ((g, s1, hg, "basalt"), (s1, ze, hu, h["wall"])):
            skin, rev = B.wall_skin(F, zz0, zz1, holes, R)
            m.put(skin, col, closed=False, vary=0.02)
            m.put(rev, col, closed=False, vary=0.02)
        m.put(F.box(-L / 2, L / 2, s1 - 0.08, s1 + 0.08, 0.0, 0.05), "pale_basalt")
        # Back: sheltered (north), so the lime is renewed there.
        bh = [window(m, Bk, 0.0, f + 0.85, 0.9, 1.15, h["glass"], None, False, h["frame"], R),
              window(m, Bk, 0.0, s1 + 0.75, 0.9, 1.15, h["glass"], None, "back" in lit, h["frame"], R)]
        for zz0, zz1, holes, col in ((g, s1, bh[:1], "basalt"), (s1, ze, bh[1:], "old_lime" if name == "empty" else "limewash")):
            skin, rev = B.wall_skin(Bk, zz0, zz1, holes, R)
            m.put(skin, col, closed=False, vary=0.02)
            m.put(rev, col, closed=False, vary=0.02)

        # Wear on the front, by cause: wind flakes the lime (most where nobody renews it), salt
        # blooms white on the basalt below +6 m.
        # Lime goes first at the wall's edges: the corners against the party walls, the foot
        # of the upper wall over the string course and under the eave.
        tries = 0
        placed = 0
        while placed < round(h["flakes"] * W["wind"] * 1.5) and tries < 40:
            tries += 1
            e = m.rng.choice((-1, 1))
            a = e * (L / 2 - m.rng.uniform(0.25, 0.7)) if m.chance(0.6) else m.rng.uniform(-L / 2 + 0.4, L / 2 - 0.4)
            z = m.rng.choice((s1 + m.rng.uniform(0.2, 0.45), ze - m.rng.uniform(0.25, 0.45), m.rng.uniform(s1 + 0.3, ze - 0.3)))
            size = m.rng.uniform(0.18, 0.32) * (1.4 if name == "empty" else 1.0)
            if clear(hu, a, z, size * 1.6, size, 0.05):
                flake(m, F, a, z, size, C("old_lime") if name in ("tidy", "crowded") else C("basalt"))
                placed += 1
        a = m.rng.uniform(-L / 2, 0.0)
        bloom(m, F, a, min(L / 2, a + m.rng.uniform(1.2, 2.4) * W["salt"] / 0.6), g + 0.04, m.rng.uniform(0.12, 0.3), C("limewash", "stone"))

        # Gutter and downpipe (the empty house's gutter lost a length in the storm), each
        # bracket weeping rust onto the wall.
        ye, zg = YF - 0.15, ze - 0.15 * math.tan(p) - 0.04
        spans = [(x0, x0 + 0.8), (x0 + 2.5, xb)] if name == "empty" else [(x0, xb)]
        for a0, a1 in spans:
            m.put(box((a0, ye - 0.15, zg - 0.12), (a1, ye, zg)), "iron")
        if name != "empty":
            px = xb - 0.22
            m.put(cyl((px, YF - 0.09, zg - 0.05), (px, YF - 0.09, g + 0.15), 0.05, 0.05, 6), "iron")
            m.put(cyl((px, YF - 0.09, g + 0.15), (px, YF - 0.3, g + 0.06), 0.05, 0.05, 6), "iron")
            for zb in (s1 + 1.2, f + 1.0):
                m.put(box((px - 0.07, YF - 0.16, zb), (px + 0.07, YF, zb + 0.05)), "iron")
                streak(m, F, at(px) + 0.09, zb, m.rng.uniform(0.4, 0.8) * (0.6 + W["salt"]), "rust")
        h["eave_edge"] = (ye, zg)

        # Roof: each piece's colour by cause. Wind patches and lichens the front (south) more than
        # the back, and the west more than the east; repairs are new slate; the empty house has
        # lost slates near its west ridge in the storm.
        for sgn in (-1, 1):
            D = Vector((0, sgn * math.cos(p), -math.sin(p)))
            Nn = Vector((0, sgn * math.sin(p), math.cos(p)))

            def paint(a, t, sgn=sgn, h=h, x0=x0):
                xx = x0 + a
                if name == "empty" and sgn < 0 and ((0.5 < a < 2.3 and 0.4 < t < 2.0 and m.chance(0.8)) or m.chance(0.02)):
                    return None
                weather = (1.0 if sgn < 0 else 0.35) * (1.0 + (-xx) / 22.0)
                if name == "crowded" and sgn < 0 and abs(xx - 7.05) < 1.3 and 0.6 < t < 2.6 and m.chance(0.55):
                    return C("new_slate")  # round the dormer, added later
                if m.chance(h["repair"] * (1.4 if sgn < 0 else 0.6) + W["wind"] * 0.02 * weather):
                    return C("new_slate")
                return C("slate")
            S = (HALF + 0.15) / math.cos(p)
            P, N = slope(m, Vector((x0, YR, h["zr"])) + Nn * 0.14, X, D, xb - x0, S, paint)
            h["P%d" % sgn] = P
            # Lichen where the wind and wet sit: the south slope, the west end, the lower courses;
            # thickest where nobody clears it.
            weather = (1.0 if sgn < 0 else 0.3) * (1.0 + (-cx) / 22.0) * (1.8 if name == "empty" else 0.5 if name == "tidy" else 1.0)
            lichens(m, P, N, [(min(L - 0.5, 0.5 + (L - 1.0) * m.rng.random() ** 1.6), (S - 0.4) * (1 - m.rng.random() ** 2 * 0.7), m.rng.uniform(0.12, 0.24))
                              for _ in range(round(W["wind"] * 7 * weather))])
        for a in range(math.ceil(L / 0.7)):
            m.put(box((x0 + a * 0.7 + 0.01, YR - 0.21, h["zr"] + 0.06), (min(xb, x0 + (a + 1) * 0.7) - 0.01, YR + 0.21, h["top"])), "pale_basalt")

        # Household marks.
        if name == "tidy":
            # A chalk-blue flower box of heather and moor grass, and a doorstep bench.
            wz = f + 0.66
            m.put(F.box(wa - 0.5, wa + 0.5, wz, wz + 0.2, 0.07, 0.3), "chalk_blue")
            tufts(m, [F.p(wa - 0.38 + i * 0.19, wz + 0.2, 0.18) for i in range(5)], 0.08, ("heather", "moor_grass"))
            bx = at(x0 + 1.45)
            m.put(F.box(bx - 0.65, bx + 0.65, g + 0.4, g + 0.46, 0.06, 0.42), "driftwood")
            for e in (-1, 1):
                m.put(F.box(bx + e * 0.5 - 0.12, bx + e * 0.5 + 0.12, g + 0.04, g + 0.4, 0.1, 0.38), "basalt")
        elif name == "fisher":
            # Glass floats strung under the upper sill, a creel at the step, oilskins on a peg.
            a0, a1, zh = at(x0 + 2.6), at(x0 + 5.6), s1 - 0.2
            line = [F.p(a0 + (a1 - a0) * i / 10, zh - 0.32 * (1 - (2 * i / 10 - 1) ** 2), 0.12) for i in range(11)]
            tube(m, line, 0.012, "driftwood", sides=3)
            for e in (a0, a1):
                m.put(F.box(e - 0.03, e + 0.03, zh - 0.03, zh + 0.03, 0.0, 0.14), "iron")
                streak(m, F, e, zh - 0.03, 0.5, "rust", 0.06)
            for i in range(1, 10):
                c = line[i] - Z * 0.13
                m.put(sphere(c, 0.1, 1), ("green", "amber", "aqua")[i % 3], soft=c)
                tube(m, [c + X * 0.1 + Z * 0.02, c + Z * 0.1, c - X * 0.1 + Z * 0.02], 0.008, "tar", sides=3)
            ca = at(x0 + 2.8)
            c0 = F.p(ca, g + 0.04, 0.38)
            lathe(m, [(0.17, 0.0), (0.24, 0.55), (0.21, 0.55), (0.14, 0.06), (0.0, 0.06)], 8,
                  lambda i, s, a, z: C("driftwood") if i % 2 == 0 else C("tar"), c=(c0.x, c0.y), sy=0.8)
            m.put(F.box(ca - 0.24, ca + 0.24, g + 0.5, g + 0.6, 0.18, 0.24), "driftwood")
            oa, top = at(x0 + 0.95), f + 2.1
            m.put(F.box(oa - 0.03, oa + 0.03, top, top + 0.06, 0.0, 0.16), "iron")
            coat = [(-0.2, top), (0.2, top), (0.33, top - 0.28), (0.27, top - 0.33), (0.27, top - 1.05), (-0.27, top - 1.05), (-0.27, top - 0.33), (-0.33, top - 0.28)]
            m.put(F.poly(coat, 0.02, 0.13), "mustard", surface="cloth")
            hat = F.p(oa, top + 0.2, 0.12)
            m.put(cyl(hat - Z * 0.05, hat + Z * 0.05, 0.19, 0.12, 8), "mustard", surface="cloth")
            m.put(F.box(oa - 0.03, oa + 0.03, top + 0.18, top + 0.24, 0.0, 0.06), "iron")
        elif name == "crowded":
            # The washing-line pulley bracket, its line down to a cleat by the window.
            ba, bz = at(xb - 0.25), s1 + 2.0
            m.put(F.box(ba - 0.03, ba + 0.03, bz - 0.04, bz + 0.04, 0.0, 0.62), "iron")
            m.put(cyl(F.p(ba, bz - 0.5, 0.0), F.p(ba, bz - 0.03, 0.55), 0.02, 0.02, 4), "iron")
            wheel = F.p(ba, bz - 0.12, 0.58)
            m.put(cyl(wheel - X * 0.03, wheel + X * 0.03, 0.09, 0.09, 8), "iron")
            cleat = F.p(ba - 0.1, f + 1.55, 0.06)
            m.put(F.box(ba - 0.2, ba, f + 1.52, f + 1.58, 0.0, 0.07), "iron")
            for dx in (-0.025, 0.025):
                tube(m, [wheel + X * dx - Z * 0.08, cleat + X * dx], 0.01, "driftwood", sides=3)
            streak(m, F, ba, bz - 0.06, 0.9, "rust", 0.07)
        m.facts["houses"].append(dict(name=name, front_m=h["w"], street_m=g, floor_m=round(f, 2), eave_above_street_m=h["eave"],
                                      pitch_deg=h["pitch"], ridge_above_street_m=round(h["top"] - g, 2), door=h["door"]))

    # Gables: the west end, each party wall (only the higher house's shows) and the crowded
    # house's east end above its lean-to, each with coping stones and skewputs. The weather end
    # (west) is flaked and lichened.
    gables = [(-11.0, -10.7, HOUSES[0], -1, True)] + [(h["x1"] - 0.3, h["x1"], h, 0, False) for h in HOUSES[:3]] + [(HOUSES[3]["xb"] - 0.3, HOUSES[3]["xb"], HOUSES[3], 1, False)]
    for xa, xb_, h, end, weather in gables:
        s1, ze, zr, top = h["s1"], h["ze"], h["zr"], h["top"]

        def fn(a, s, z):
            return Vector((a, s, z))
        m.put(prism([(YF + 0.01, 0.0), (YB - 0.01, 0.0), (YB - 0.01, s1), (YF + 0.01, s1)], xa, xb_, fn), "basalt", vary=0.02)
        m.put(prism([(YF + 0.01, s1), (YB - 0.01, s1), (YB - 0.01, ze + 0.27), (YR, top), (YF + 0.01, ze + 0.27)], xa, xb_, fn),
              "old_lime", vary=0.02)
        cx0, cx1 = (xa, xa + 0.38) if end < 0 else (xb_ - 0.38, xb_ + 0.06) if end > 0 else (xb_ - 0.22, xb_ + 0.22)
        for ye in (YF, YB):
            for j in range(4):
                t0, t1 = j / 4, (j + 1) / 4

                def cp(q, ye=ye):
                    return Vector((q.x, YR + (ye - YR) * q.y, top + (ze + 0.27 - top) * q.y + q.z))
                m.put(lbox(Vector((cx0, t0 - 0.02, -0.02)), Vector((cx1, t1, 0.13)), fn=cp), "pale_basalt")
                if m.chance(0.8 if weather else 0.15 * ROW_WEAR["wind"] * (2 if ye == YF else 1)):
                    lichens(m, lambda a, t, hh, cp=cp: cp(Vector((a, t, hh))), Z, [((cx0 + cx1) / 2, (t0 + t1) / 2, 0.07)], 0.135)
            yy0, yy1 = sorted((ye - 0.1 * (1 if ye == YB else -1), ye + 0.25 * (-1 if ye == YB else 1)))
            m.put(box((cx0, yy0, ze + 0.02), (cx1, yy1, ze + 0.45)), "pale_basalt")
        if weather:
            gf = Face((-11.0, (YF + YB) / 2, 0), -Y, YB - YF)
            # The weather end: lime stripped along the windward (front) corner and under the
            # skew, lichen creeping down from the coping, salt at the foot.
            for a, z, size in ((-2.35, h["s1"] + 0.6, 0.4), (-2.3, h["s1"] + 1.7, 0.36), (-2.1, h["ze"] - 0.2, 0.32), (-1.2, h["ze"] + 0.5, 0.3),
                               (1.0, h["ze"] + 0.6, 0.3), (2.3, h["s1"] + 0.4, 0.32), (0.2, h["s1"] + 0.25, 0.3)):
                flake(m, gf, a + m.rng.uniform(-0.2, 0.2), z + m.rng.uniform(-0.2, 0.2), size, C("basalt"))
            for a in (-1.6, -0.6, 0.5, 1.5):
                z = h["ze"] + 0.27 + (h["top"] - h["ze"] - 0.27) * (1 - abs(a) / 3.1) - 0.25
                flake(m, gf, a, z, 0.16, C("lichen", "plaster"), 0.016)
            bloom(m, gf, -3.0, 0.6, 0.02, 0.35, C("limewash", "stone"))

    # Chimneys on the party walls; a cold pot capped with a slate on the empty house's side, an
    # extra pot on the crowded house's. Soot is light this far from the Cone: only the pots'
    # mouths.
    for hw, he, pots in ((HOUSES[0], HOUSES[1], [("tidy", -0.22), ("fisher", 0.22)]),
                         (HOUSES[1], HOUSES[2], [("fisher", -0.22), ("empty", 0.22)]),
                         (HOUSES[2], HOUSES[3], [("empty", -0.3), ("crowded", 0.0), ("extra", 0.3)])):
        xc = hw["x1"]
        zt = hw["top"] + 0.95
        m.put(box((xc - 0.32, YR - 0.5, he["zr"] - 0.3), (xc + 0.32, YR + 0.5, zt)), "brick")
        m.put(box((xc - 0.37, YR - 0.55, zt), (xc + 0.37, YR + 0.55, zt + 0.09)), "pale_basalt")
        for who, dy in pots:
            base = Vector((xc, YR + dy, zt + 0.09))
            hp = 0.62 if who == "extra" else 0.42
            m.put(cyl(base, base + Z * hp, 0.12, 0.1 if who != "extra" else 0.08, 8), "new_brick")
            if who == "empty":
                m.put(box(base + Vector((-0.15, -0.13, hp)), base + Vector((0.15, 0.13, hp + 0.03))), "new_slate")
            else:
                m.put(cyl(base + Z * (hp - 0.08 * (0.5 + ROW_WEAR["soot"] * 5)), base + Z * (hp + 0.01), 0.105, 0.105, 8), "tar", surface="brick")

    # Roof lights for the tidy and fisher attics; a dormer for the crowded one.
    for h, xa in ((HOUSES[0], -8.6), (HOUSES[1], -2.4)):
        P = h["P-1"]
        p0 = (xa - h["x0"])
        m.put(lbox(Vector((p0, 0.9, 0.0)), Vector((p0 + 0.62, 1.75, 0.12)), fn=lambda q, P=P: P(q.x, q.y, q.z)), "iron")
        for i in range(2):
            for j in range(2):
                aa, tt = p0 + 0.06 + i * 0.27, 0.96 + j * 0.37
                h0 = 0.125
                m.pane([P(aa, tt, h0), P(aa + 0.23, tt, h0), P(aa + 0.23, tt + 0.33, h0), P(aa, tt + 0.33, h0)], h["glass"], P(0, 0, 1) - P(0, 0, 0))
    h = HOUSES[3]
    p, P = h["p"], h["P-1"]
    yd = YF + 0.55
    zb = h["ze"] + 0.55 * math.tan(p) + 0.12
    zde = zb + 1.05
    dx0, dx1 = 6.4, 7.8
    depth = (zde - zb) / math.tan(p) + 0.15
    m.put(box((dx0, yd, zb - 0.2), (dx1, yd + 0.12, zde)), "limewash")
    for xx in (dx0, dx1 - 0.08):
        m.put(prism([(yd, zb - 0.2), (yd + depth, zde), (yd, zde)], xx, xx + 0.08, lambda a, s, z: Vector((a, s, z))), "new_slate")
    Fd = Face(((dx0 + dx1) / 2, yd, 0), X, dx1 - dx0)
    window(m, Fd, 0.0, zb + 0.2, 0.8, 0.74, h["glass"], h["patch"], True, h["frame"], R=0.02, sill=False, lintel=False)
    for sgn in (-1, 1):
        q = math.radians(45)
        Dd = Vector((sgn * math.cos(q), 0, -math.sin(q)))
        Nd = Vector((sgn * math.sin(q), 0, math.cos(q)))
        slope(m, Vector(((dx0 + dx1) / 2, yd - 0.12, zde + 0.7)) + Nd * 0.14, Y, Dd, depth + 0.3, 0.85 / math.cos(q),
              lambda a, t: C("new_slate") if m.chance(0.5) else C("slate"), course=0.3)
    m.put(prism([(dx0, zde), (dx1, zde), ((dx0 + dx1) / 2, zde + 0.72)], yd, yd + 0.12, lambda a, s, z: Vector((s, a, z))), "limewash")
    m.put(box(((dx0 + dx1) / 2 - 0.12, yd - 0.12, zde + 0.78), ((dx0 + dx1) / 2 + 0.12, yd + depth + 0.2, zde + 0.92)), "pale_basalt")

    # The crowded house's lean-to: tarred boards on a basalt sill, a slate roof falling east, a
    # lit scullery window.
    lx0, lx1, ly0, ly1, zh, zl = 9.2, 11.0, YF + 0.35, 1.9, 3.05, 2.3
    m.put(box((lx0, ly0, 0), (lx1, ly1, 0.45)), "basalt")
    m.put(prism([(lx0, 0.45), (lx1, 0.45), (lx1 - 0.0, zl), (lx0, zh)], ly0, ly1, lambda a, s, z: Vector((s, a, z))), "tar", vary=0.02)
    Fl = Face(((lx0 + lx1) / 2, ly0, 0), X, lx1 - lx0)
    for i in range(6):
        aa = -0.9 + 0.3 * i + 0.13
        m.put(Fl.box(aa - 0.035, aa + 0.035, 0.45, zl - 0.05 + (zh - zl) * (0.5 - aa / 1.8) * 0.9, 0.0, 0.03, back=False), "tar")
    window(m, Fl, 0.15, 1.2, 0.62, 0.62, h["glass"], None, "lean" in h["lit"], "driftwood", R=0.0, lintel=False)
    q = math.atan2(zh - zl, lx1 - lx0)
    Dl, Nl = Vector((math.cos(q), 0, -math.sin(q))), Vector((math.sin(q), 0, math.cos(q)))
    slope(m, Vector((lx0, ly0 - 0.12, zh + 0.02)) + Nl * 0.14, Y, Dl, ly1 - ly0 + 0.24, (lx1 - lx0 - 0.08) / math.cos(q),
          lambda a, t: C("new_slate") if m.chance(0.15) else C("slate"), course=0.32)
    m.facts.update(wear=W, footprint_brief_m=[22.0, 7.5])


# ---------------------------------------------------------------------------------------------
# 3. A Ladder glasshouse


def glasshouse(m):
    """A lean-to glasshouse against a whitewashed stone wall: ten 1 m bays of small aqua panes
    in a frame whose pale paint is flaking, the storm's damage on the weather (west) end and
    front boarded, some panes replaced in whatever glass there was, a few lost; two vents
    propped open and the end door open on the beds; the end yard of the 12 m plot holds the rain
    butt, the kelp heap with its fork and a cold frame."""
    X0, X1, GX, Y0, YW, YB = -6.0, 6.0, 4.0, -2.25, 1.75, 2.25
    YG, ZE, ZT = -2.08, 1.95, 3.2  # the glazing line, its eave and the roof's top at the wall
    rng = m.rng
    run, rise = YW - YG, ZT - ZE
    q = math.atan2(rise, run)
    Ls = math.hypot(run, rise)
    U, Nr = Vector((0, math.cos(q), math.sin(q))), Vector((0, -math.sin(q), math.cos(q)))

    def RP(x, t, h=0.0):
        return Vector((x, YG, ZE)) + U * t + Nr * h

    def roof_z(y):
        return ZE + (y - YG) * rise / run

    # The back wall, whitewashed (lime) on a basalt course, with a pale coping.
    m.put(box((X0, YW, 0), (X1, YB, 0.3)), "basalt")
    m.put(box((X0, YW, 0.3), (X1, YB, ZT)), "limewash", vary=0.02)
    for i in range(12):
        m.put(box((X0 + i, YW - 0.02, ZT), (X0 + i + 1 - 0.01, YB, ZT + 0.12)), "pale_basalt")
    bw = Face((0.0, YB, 0), -X, X1 - X0)
    for _ in range(9):
        flake(m, bw, rng.uniform(2.0, 5.2), rng.uniform(0.8, 2.6), rng.uniform(0.15, 0.3), C("basalt"))
    ew = Face((X0, (YW + YB) / 2, 0), -Y, YB - YW)
    blob(m, ew, 0.0, 1.8, 0.18, 0.5, C("basalt"))
    # Dwarf walls with a pale cap.
    m.put(box((X0, Y0, 0), (GX, Y0 + 0.33, 0.62)), "basalt")
    m.put(box((X0, Y0, 0.62), (GX, Y0 + 0.36, 0.7)), "pale_basalt")
    m.put(box((X0, Y0, 0), (X0 + 0.3, YW, 0.62)), "basalt")
    m.put(box((X0, Y0, 0.62), (X0 + 0.33, YW, 0.7)), "pale_basalt")
    for ya, yb in ((Y0, -0.5), (0.5, YW)):
        m.put(box((GX - 0.3, ya, 0), (GX, yb, 0.62)), "basalt")
        m.put(box((GX - 0.33, ya, 0.62), (GX, yb, 0.7)), "pale_basalt")

    # Every pane slot: (part, bay, column, row, corners, outward, weather weight).
    slots = []
    bays = [X0 + i for i in range(int(GX - X0))]
    rows_r = math.ceil((Ls - 0.06 + 0.03) / (MAX_PANE + 0.03))
    pr = (Ls - 0.06 - (rows_r - 1) * 0.03) / rows_r
    pw = (1.0 - 0.07 - 2 * 0.03) / 3
    vents = {2, 6}
    for b, xb in enumerate(bays):
        for c in range(3):
            xa = xb + 0.035 + c * (pw + 0.03)
            for j in range(rows_r):
                t = 0.03 + j * (pr + 0.03)
                if b in vents and j >= rows_r - 2:
                    continue
                slots.append(("roof", b, c, j, [RP(xa, t), RP(xa + pw, t), RP(xa + pw, t + pr), RP(xa, t + pr)], Nr, 0.15 + (b < 2) * 2.0))
    fh = (1.92 - 0.72 - 2 * 0.04) / 3
    front = Face(((X0 + GX) / 2, YG, 0), X, GX - X0)
    for b, xb in enumerate(bays):
        for c in range(3):
            a = xb - (X0 + GX) / 2 + 0.035 + c * (pw + 0.03)
            for j in range(3):
                z = 0.72 + j * (fh + 0.04)
                slots.append(("front", b, c, j, [front.p(a, z, 0), front.p(a + pw, z, 0), front.p(a + pw, z + fh, 0), front.p(a, z + fh, 0)], -Y, 0.3 + (j == 0) * 1.0 + (b < 3) * 3.0))

    def end_panes(part, x, cols, out, weight):
        for c, (ya, yb) in enumerate(cols):
            ztop = roof_z(min(ya, yb)) - 0.06
            zb = 2.14 if part == "door" else 0.72
            n = math.ceil((ztop - zb + 0.03) / (MAX_PANE + 0.03))
            ph = (ztop - zb - (n - 1) * 0.03) / n
            for j in range(n):
                z0 = zb + j * (ph + 0.03)
                z1 = z0 + ph
                za, zbb = (z1, z1) if j < n - 1 else (roof_z(ya) - 0.06, roof_z(yb) - 0.06)
                slots.append((part if part != "door" else "east", 0, c, j, [Vector((x, ya, z0)), Vector((x, yb, z0)), Vector((x, yb, zbb)), Vector((x, ya, za))], out, weight))

    def spans(a, b, n):
        return [(a + (b - a) * i / n + 0.02, a + (b - a) * (i + 1) / n - 0.02) for i in range(n)]
    end_panes("west", X0 + 0.15, spans(YG, YW, 9), -X, 4.0)
    end_panes("east", GX - 0.15, spans(YG, -0.5, 4) + spans(0.5, YW, 3), X, 0.8)
    end_panes("door", GX - 0.15, spans(-0.5, 0.5, 3), X, 0.8)
    m.facts["max_pane"] = max(max((p[4][1] - p[4][0]).length, (p[4][3] - p[4][0]).length) for p in slots)

    # Which panes are not original, chosen by cause: holes (3 to 5) and boards where the storm
    # struck (weighted to the west end and the front), mismatched glass anywhere.
    n = len(slots)
    idx = list(range(n))
    fate = {}
    for part in ("roof", "roof", "front", "west"):
        cands = [i for i in idx if slots[i][0] == part and i not in fate and (part != "roof" or 0 < slots[i][3] < rows_r - 3)]
        i = rng.choice(cands)
        fate[i] = "missing"
        if part == "roof" and rng.random() < 0.6:
            nb = [k for k in cands if slots[k][1] == slots[i][1] and slots[k][3] == slots[i][3] and abs(slots[k][2] - slots[i][2]) == 1]
            if nb:
                fate[nb[0]] = "missing"
    holes = 4
    want_boards = round(n * rng.uniform(0.09, 0.11))
    weights = [slots[i][6] for i in idx]
    while sum(1 for v in fate.values() if v == "boarded") < want_boards:
        i = rng.choices(idx, weights)[0]
        if i not in fate:
            fate[i] = "boarded"
            # Boards go up in runs along a row.
            for k in idx:
                s, t = slots[k], slots[i]
                if k not in fate and s[0] == t[0] and s[1] == t[1] and s[3] == t[3] and abs(s[2] - t[2]) == 1 and rng.random() < 0.5:
                    fate[k] = "boarded"
    want_odd = round(n * rng.uniform(0.05, 0.065))
    while sum(1 for v in fate.values() if v in GLASS) < want_odd:
        i = rng.randrange(n)
        if i not in fate:
            fate[i] = rng.choice(["green", "amber", "green", "smoke"])
    for i, (part, b, c, j, pts, out, wt) in enumerate(slots):
        f = fate.get(i)
        if f == "missing":
            continue
        if f == "boarded":
            nrm = Vector(out)
            ctr = sum(pts, Vector()) / 4
            grown = [ctr + (p - ctr) * 1.12 + nrm * 0.015 for p in pts]
            m.put(prism([(0, 0), (1, 0), (1, 1), (0, 1)], 0.0, 0.025, lambda w, a, z, g=grown, nrm=nrm:
                        g[0].lerp(g[1], a).lerp(g[3].lerp(g[2], a), z) + nrm * w), "driftwood", vary=0.05)
            continue
        m.pane(pts, f if f else "aqua", out)
    counts = {"panes": n, "missing": sum(1 for v in fate.values() if v == "missing"), "holes": holes,
              "boarded": sum(1 for v in fate.values() if v == "boarded"), "mismatched": sum(1 for v in fate.values() if v in GLASS)}
    counts["not_original_pct"] = round(100.0 * len(fate) / n, 1)
    counts["mismatched_pct"] = round(100.0 * counts["mismatched"] / n, 1)
    m.facts["panes"] = counts

    # The frame: posts, rafters, plates and glazing bars, painted pale and flaking; bare
    # driftwood shows most on the weather side.
    def paint_col(weather):
        r = rng.random()
        return "driftwood" if r < 0.12 + 0.18 * weather else "limewash" if r < 0.4 else "old_lime"
    for i, xb in enumerate(bays + [GX]):
        wthr = 1.0 if i < 3 else 0.3
        for t0, t1 in ((-0.05, Ls / 2), (Ls / 2, Ls)):
            m.put(lbox(Vector((xb - 0.035, t0, -0.1)), Vector((xb + 0.035, t1, 0.035)), fn=lambda q: RP(q.x, q.y, q.z)), paint_col(wthr), surface="wood")
        m.put(box((xb - 0.04, YG - 0.04, 0.7), (xb + 0.04, YG + 0.04, ZE)), paint_col(wthr), surface="wood")
        if i < len(bays):
            for c in (1, 2):
                xg = xb + 0.035 + c * (pw + 0.03) - 0.03
                m.put(lbox(Vector((xg, 0.0, 0.0)), Vector((xg + 0.03, Ls, 0.025)), fn=lambda q: RP(q.x, q.y, q.z)), paint_col(wthr * 0.8), surface="wood")
                m.put(box((xg, YG - 0.02, 0.7), (xg + 0.03, YG + 0.01, ZE)), paint_col(wthr), surface="wood")
            for j in range(1, rows_r):
                t = 0.03 + j * (pr + 0.03) - 0.03
                m.put(lbox(Vector((xb + 0.035, t, 0.0)), Vector((xb + 0.965, t + 0.03, 0.02)), fn=lambda q: RP(q.x, q.y, q.z)), paint_col(wthr * 0.6), surface="wood")
            for j in (1, 2):
                z = 0.72 + j * (fh + 0.04) - 0.04
                m.put(box((xb, YG - 0.02, z), (xb + 1.0, YG + 0.01, z + 0.04)), paint_col(wthr), surface="wood")
    m.put(box((X0, YG - 0.05, 0.68), (GX, YG + 0.06, 0.74)), paint_col(1.0), surface="wood")
    m.put(box((X0, YG - 0.06, ZE - 0.1), (GX, YG + 0.06, ZE + 0.03)), paint_col(1.0), surface="wood")
    m.put(box((X0, Y0, ZE - 0.12), (GX + 0.1, Y0 + 0.12, ZE - 0.02)), "iron")  # gutter
    for x, out in ((X0 + 0.15, -1), (GX - 0.15, 1)):
        for y in [YG + (YW - YG) * i / 9 for i in range(10)]:
            if out > 0 and -0.55 < y < 0.55:
                continue
            m.put(box((x - 0.035, y - 0.03, 0.7), (x + 0.035, y + 0.03, roof_z(y))), paint_col(1.0 if out < 0 else 0.3), surface="wood")
        for z in (1.12, 1.55, 1.98, 2.41):
            ys = [(YG, YW)] if out < 0 else [(YG, -0.5), (0.5, YW)] + ([(-0.5, 0.5)] if z > 2.1 else [])
            for ya, yb in ys:
                top = roof_z(ya)
                if z < top - 0.05:
                    m.put(box((x - 0.03, ya, z - 0.02), (x + 0.03, yb, z + 0.02)), paint_col(1.0 if out < 0 else 0.3), surface="wood")
    m.put(box((GX - 0.2, -0.56, 0.0), (GX - 0.1, -0.48, 2.12)), paint_col(0.3), surface="wood")
    m.put(box((GX - 0.2, 0.48, 0.0), (GX - 0.1, 0.56, 2.12)), paint_col(0.3), surface="wood")
    m.put(box((GX - 0.2, -0.56, 2.06), (GX - 0.1, 0.56, 2.14)), paint_col(0.3), surface="wood")

    # The vents, propped open on iron stays.
    t1 = 0.03 + rows_r * (pr + 0.03)
    t0 = 0.03 + (rows_r - 2) * (pr + 0.03)
    for b in vents:
        xb = bays[b]
        hinge = RP(0, t1, 0.03)
        with m.at(Matrix.Translation(hinge) @ Matrix.Rotation(math.radians(-28), 4, "X") @ Matrix.Translation(-hinge)):
            for a0, a1, s0, s1 in ((xb + 0.04, xb + 0.96, t0, t0 + 0.05), (xb + 0.04, xb + 0.96, t1 - 0.05, t1),
                                    (xb + 0.04, xb + 0.09, t0, t1), (xb + 0.91, xb + 0.96, t0, t1)):
                m.put(lbox(Vector((a0, s0, 0.03)), Vector((a1, s1, 0.08)), fn=lambda q: RP(q.x, q.y, q.z)), paint_col(0.5), surface="wood")
            for c in range(3):
                for j in range(2):
                    xa, ta = xb + 0.1 + c * 0.27, t0 + 0.06 + j * (t1 - t0 - 0.12) / 2
                    m.pane([RP(xa, ta, 0.06), RP(xa + 0.25, ta, 0.06), RP(xa + 0.25, ta + (t1 - t0 - 0.14) / 2, 0.06), RP(xa, ta + (t1 - t0 - 0.14) / 2, 0.06)], "aqua", Nr)
        lower = Matrix.Translation(hinge) @ Matrix.Rotation(math.radians(-28), 4, "X") @ Matrix.Translation(-hinge) @ RP(xb + 0.5, t0, 0.05)
        m.put(cyl(RP(xb + 0.5, t0 - 0.25, 0.03), lower, 0.012, 0.012, 4), "iron")

    # The door, open outward into the yard: lower panel boarded, upper panes.
    with m.at(place(GX - 0.12, -0.48, 0.0, math.radians(-78))):
        for a0, a1, z0, z1 in ((0, 0.06, 0, 2.0), (0.84, 0.9, 0, 2.0), (0, 0.9, 0, 0.1), (0, 0.9, 0.95, 1.05), (0, 0.9, 1.9, 2.0), (0.42, 0.48, 1.05, 1.9)):
            m.put(box((0.0, a0, z0), (0.05, a1, z1)), paint_col(0.4), surface="wood")
        m.put(box((0.005, 0.06, 0.1), (0.045, 0.84, 0.95)), "driftwood")
        for c in range(2):
            for j in range(2):
                ya, za = 0.08 + c * 0.42, 1.08 + j * 0.42
                m.pane([Vector((0.05, ya, za)), Vector((0.05, ya + 0.32, za)), Vector((0.05, ya + 0.32, za + 0.38)), Vector((0.05, ya, za + 0.38))], "aqua", X)
                m.pane([Vector((0.0, ya, za)), Vector((0.0, ya, za + 0.38)), Vector((0.0, ya + 0.32, za + 0.38)), Vector((0.0, ya + 0.32, za))], "aqua", -X)

    # Inside: a peat floor, two raised beds of greens, vines trained up the white wall, and a
    # lantern hung under the first vent (the one faint glow).
    m.poly([(X0 + 0.3, Y0 + 0.33, 0.01), (GX - 0.3, Y0 + 0.33, 0.01), (GX - 0.3, YW, 0.01), (X0 + 0.3, YW, 0.01)], "peat", Z)
    for ya, yb, zt in ((Y0 + 0.4, -0.75, 0.35), (0.25, YW - 0.05, 0.45)):
        m.put(box((X0 + 0.35, ya, 0), (GX - 0.35, yb, zt)), "driftwood")
        m.poly([(X0 + 0.4, ya + 0.05, zt + 0.01), (GX - 0.4, ya + 0.05, zt + 0.01), (GX - 0.4, yb - 0.05, zt + 0.01), (X0 + 0.4, yb - 0.05, zt + 0.01)], "peat", Z)
    greens = [(x, y, 0.36) for x in [X0 + 0.6 + 0.48 * i for i in range(20)] for y in (-1.55, -1.05)]
    tufts(m, greens, 0.17, ("moor_grass", "kelp", "moor_grass"))
    for i in range(10):
        x = X0 + 0.55 + i
        m.put(box((x - 0.012, YW - 0.12, 0.45), (x + 0.012, YW - 0.1, 2.7)), "driftwood")
        tufts(m, [(x + rng.uniform(-0.12, 0.12), YW - 0.3, z) for z in (0.5, 1.2, 1.9)], 0.22, ("moor_grass", "kelp"))
    strip = [(-3.95, YW - 0.03, 2.66), (-3.05, YW - 0.03, 2.66), (-3.05, YW - 0.03, 2.78), (-3.95, YW - 0.03, 2.78)]
    m.poly(strip, C("smoke", "glass"), -Y, mat=m.glow("Glow"), vary=0)
    material("Glow", (1, 1, 1), emission=PAL["oil_lamp"], strength=1.4)  # faint
    m.put(box((-4.0, YW - 0.08, 2.62), (-3.0, YW - 0.0, 2.66)), "iron")
    m.put(box((-4.0, YW - 0.08, 2.78), (-3.0, YW - 0.0, 2.82)), "iron")

    # The yard: rain butt fed by the gutter, the cold frame, the kelp heap with its fork.
    bc = Vector((4.38, -1.82, 0.0))
    lathe(m, [(0.27, 0.0), (0.3, 0.42), (0.27, 0.84), (0.25, 0.84), (0.25, 0.78), (0.0, 0.78)], 10,
          lambda i, s, a, z: C("driftwood") if i < 2 else C("tar"), c=(bc.x, bc.y))
    for z in (0.12, 0.7):
        lathe(m, [(0.29 if z < 0.4 else 0.285, z), (0.3, z + 0.05)], 10, lambda i, s, a, zz: C("rust") if m.chance(0.5) else C("iron"), c=(bc.x, bc.y))
    tube(m, [(GX + 0.08, Y0 + 0.06, ZE - 0.07), (GX + 0.2, -1.95, ZE - 0.3), (bc.x - 0.02, bc.y + 0.02, 1.1), (bc.x, bc.y, 0.86)], 0.045, "iron", sides=6)
    cx0, cx1, cy0, cy1 = 4.78, 5.95, -2.2, -1.1
    m.put(box((cx0, cy0, 0), (cx1, cy0 + 0.06, 0.28)), "driftwood")
    m.put(box((cx0, cy1 - 0.06, 0), (cx1, cy1, 0.45)), "driftwood")
    for xx in (cx0, cx1 - 0.06):
        m.put(prism([(cy0, 0.0), (cy1, 0.0), (cy1, 0.45), (cy0, 0.28)], xx, xx + 0.06, lambda a, s, z: Vector((a, s, z))), "driftwood")
    tufts(m, [(cx0 + 0.25 + 0.26 * i, cy0 + 0.3 + 0.35 * (i % 2), 0.05) for i in range(4)], 0.13, ("moor_grass",))
    lid_q = math.atan2(0.17, cy1 - cy0) - math.radians(12)
    with m.at(place(0, cy1, 0.45) @ Matrix.Rotation(lid_q, 4, "X") @ place(0, -cy1, -0.45)):
        ln = cy1 - cy0 + 0.02
        for a0, a1, b0, b1 in ((cx0, cx1, cy1 - ln, cy1 - ln + 0.05), (cx0, cx1, cy1 - 0.05, cy1), (cx0, cx0 + 0.05, cy1 - ln, cy1), (cx1 - 0.05, cx1, cy1 - ln, cy1)):
            m.put(box((a0, b0, 0.45), (a1, b1, 0.5)), paint_col(0.5), surface="wood")
        for c in range(3):
            for j in range(3):
                xa, ya = cx0 + 0.07 + c * 0.35, cy1 - ln + 0.07 + j * 0.34
                m.pane([(xa, ya, 0.49), (xa + 0.33, ya, 0.49), (xa + 0.33, ya + 0.32, 0.49), (xa, ya + 0.32, 0.49)], "smoke" if (c, j) == (2, 0) else "aqua", Z)
    heap = [(4.95 + rng.uniform(0, 0.62), 0.8 + rng.uniform(0, 0.62), rng.uniform(0.0, 0.25)) for _ in range(14)]
    for i, c in enumerate(heap):
        rr = rng.uniform(0.22, 0.34)
        cc = Vector(c) + Z * rr * 0.4
        m.put(sphere(cc, rr, 1, squash=0.55), "kelp", soft=cc)
    fork = [Vector((5.3, 1.25, 0.45)), Vector((5.05, 0.75, 1.65))]
    m.put(cyl(fork[0], fork[1], 0.025, 0.025, 4), "driftwood")
    for dx in (-0.06, 0.0, 0.06):
        m.put(cyl(fork[0] + Vector((dx, 0, 0)), fork[0] + Vector((dx, 0.07, -0.3)), 0.01, 0.01, 3), "iron")
    m.put(box((5.21, 1.22, 0.42), (5.39, 1.27, 0.47)), "iron")
    m.facts.update(lot_m=[X1 - X0, YB - Y0], glazed_m=[GX - X0, YB - Y0], bays=len(bays))


# ---------------------------------------------------------------------------------------------
# 4. The Strand props


def net_rack(m):
    """A driftwood rack, three posts on splayed feet, with a tarred net drying over its rail;
    a line of cork floats along the net's head."""
    for x in (-1.42, 0.0, 1.42):
        m.put(box((x - 0.055, -0.055, 0), (x + 0.055, 0.055, 2.08)), "driftwood")
        for s in (-1, 1):
            m.put(cyl((x, s * 0.25, 0.0), (x, s * 0.04, 0.8), 0.04, 0.04, 4), "driftwood")
    m.put(cyl((-1.5, 0, 2.1), (1.5, 0, 2.1), 0.055, 0.055, 6), "driftwood")
    m.put(cyl((-1.42, 0, 0.9), (1.42, 0, 0.9), 0.04, 0.04, 4), "driftwood")
    nx, nv = 22, 7
    drop = [1.0 + 0.28 * math.sin(i * 0.9 + 1.3) + m.rng.uniform(-0.1, 0.1) for i in range(nx + 1)]
    for s in (-1, 1):
        pts = []
        for i in range(nx + 1):
            x = -1.38 + 2.76 * i / nx
            col = []
            for j in range(nv + 1):
                v = j / nv
                y = s * (0.07 + 0.13 * v ** 0.8 + 0.035 * math.sin(x * 6.0 + v * 2.5 + s))
                col.append(Vector((x, y, 2.19 - 0.04 * v - drop[i] * v ** 1.1)))
            pts.append(col)
        for i in range(nx):
            for j in range(nv):
                if j == nv - 1 and m.chance(0.3):
                    continue
                q = [pts[i][j], pts[i + 1][j], pts[i + 1][j + 1], pts[i][j + 1]]
                m.poly(q, C("tar", "cloth"), Vector((0, s, 0.2)), vary=0.03)
        if s < 0:
            for i in range(1, nx, 3):
                c = pts[i][2] + Vector((0, -0.04, 0))
                m.put(cyl(c - X * 0.06, c + X * 0.06, 0.05, 0.05, 6), "driftwood")
    for i in range(nx):
        x0, x1 = -1.38 + 2.76 * i / nx, -1.38 + 2.76 * (i + 1) / nx
        m.poly([(x0, -0.07, 2.19), (x1, -0.07, 2.19), (x1, 0.07, 2.19), (x0, 0.07, 2.19)], C("tar", "cloth"), Z)


def barrel(m, c, r, h, lid=True):
    """A fish barrel: bulged staves in two tones, iron hoops rusting, salt crusted white on its
    head and upper staves."""
    rings = [(0.86 * r, 0.0), (0.93 * r, 0.12 * h), (r, 0.5 * h), (0.93 * r, 0.88 * h), (0.86 * r, h), (0.8 * r, h)]
    rings += [(0.8 * r, h - 0.04), (0.0, h - 0.04)] if lid else [(0.8 * r, h - 0.22), (0.0, h - 0.22)]

    def paint(i, s, a, z):
        if i >= 5:
            return C("limewash", "plaster") if not lid or m.chance(0.45) else C("driftwood")
        if z > 0.7 * h and m.chance(0.3):
            return C("limewash", "plaster")
        return C("driftwood") if s % 2 else jitter(C("driftwood"), m.rng, 0.05)
    lathe(m, rings, 10, paint, c=(c[0], c[1]))
    for zz in (0.1 * h, 0.82 * h):
        rr = 0.93 * r + (r - 0.93 * r) * min(zz, h - zz) / (0.38 * h)
        lathe(m, [(rr + 0.012, zz), (rr + 0.012, zz + 0.06), (rr - 0.01, zz + 0.06)], 10,
              lambda i, s, a, z: C("rust") if m.chance(0.55) else C("iron"), c=(c[0], c[1]))


def barrels(m):
    """Three fish barrels standing (one open on its salt) and one on its side."""
    barrel(m, (-0.5, 0.33), 0.3, 1.1)
    barrel(m, (0.14, 0.38), 0.29, 0.98, lid=False)
    barrel(m, (-0.28, -0.3), 0.3, 1.04)
    with m.at(place(0.12, -0.36, 0.29, math.radians(12), ry=math.radians(90))):
        barrel(m, (0.0, 0.0), 0.29, 0.84)


def creel(m, c, w, h, kelp=True):
    """A wicker creel: woven bands, a tarred rim and a rope strap; full of kelp."""
    r0, r1 = 0.37 * w, w / 2
    rings = [(r0 * 0.95, 0.0)] + [(r0 + (r1 - r0) * k / 6, h * k / 6) for k in range(7)] + [(r1 + 0.02, h + 0.02), (r1 - 0.04, h + 0.02), (r0 - 0.03, 0.06), (0.0, 0.06)]
    lathe(m, rings, 8, lambda i, s, a, z: C("tar") if i in (7, 8) else C("peat", "thatch") if i in (1, 4) else C("driftwood", "thatch"), c=c, sy=0.75)
    tube(m, [(c[0] - 0.12, c[1] + 0.75 * r1, h - 0.05), (c[0] - 0.12, c[1] + 0.75 * r1 + 0.1, h * 0.5), (c[0] - 0.12, c[1] + 0.75 * r0, 0.12)], 0.018, "tar", sides=3)
    tube(m, [(c[0] + 0.12, c[1] + 0.75 * r1, h - 0.05), (c[0] + 0.12, c[1] + 0.75 * r1 + 0.1, h * 0.5), (c[0] + 0.12, c[1] + 0.75 * r0, 0.12)], 0.018, "tar", sides=3)
    if kelp:
        tufts(m, [(c[0] + dx, c[1] + dy, h - 0.06) for dx, dy in ((-0.1, 0.0), (0.1, 0.04), (0.0, -0.08))], 0.13, ("kelp",))


def creels(m):
    """Three creels: two standing full of kelp, one tipped over and spilling it."""
    creel(m, (-0.44, 0.2), 0.5, 0.78)
    creel(m, (0.12, 0.24), 0.46, 0.72)
    with m.at(place(-0.2, -0.22, 0.19, math.radians(90), rx=math.radians(90))):
        creel(m, (0.0, 0.0), 0.5, 0.62, kelp=False)
    spill = [(0.4 + 0.05 * k + m.rng.uniform(-0.04, 0.04), -0.22 + m.rng.uniform(-0.18, 0.18), 0.0) for k in range(6)]
    tufts(m, spill, 0.11, ("kelp",))
    for k in range(4):
        p0 = Vector((0.42, -0.34 + 0.08 * k, 0.03))
        tube(m, [p0, p0 + Vector((0.12, -0.04 + 0.03 * k, 0.0)), p0 + Vector((0.24, -0.08 + 0.05 * k, 0.0))], 0.02, "kelp", sides=3)


def bollard(m):
    """A cast-iron ship's bollard, far too big for any boat left, rusting by salt: its mooring
    line's eye round the neck and the tail flaked down in a flat coil beside it."""
    prof = [(0.3, 0.0), (0.3, 0.07), (0.22, 0.13), (0.17, 0.3), (0.165, 0.55), (0.19, 0.78), (0.27, 0.9), (0.3, 0.97), (0.25, 1.04), (0.14, 1.09), (0.0, 1.1)]

    drip = [m.rng.uniform(0.3, 0.75) for _ in range(16)]

    def paint(i, s, a, z):
        sw = math.cos(a - math.radians(225))
        if z < 0.16 + 0.12 * drip[s]:
            return C("rust")  # salt splash at the foot
        if 0.3 < z < 0.86 and sw > 0.6 and z > drip[s]:
            return C("rust")  # weeping from under the head, weather side
        return C("iron")
    lathe(m, prof, 16, paint)
    loop = [(0.205 * math.cos(t), 0.205 * math.sin(t), 0.6 + 0.04 * math.sin(t)) for t in (k * math.tau / 14 for k in range(15))]
    tube(m, loop, 0.035, "driftwood", sides=5)
    cx, cy = 0.62, -0.02
    tail = [Vector((0.2, -0.04, 0.6)), Vector((0.3, -0.12, 0.35)), Vector((0.38, -0.2, 0.08)), Vector((cx + 0.3 * math.cos(-1.9), cy + 0.3 * math.sin(-1.9), 0.035))]
    spiral = [Vector((cx + (0.3 - 0.065 * t / math.tau) * math.cos(-1.9 - t), cy + (0.3 - 0.065 * t / math.tau) * math.sin(-1.9 - t), 0.035)) for t in (k * math.tau / 16 for k in range(48))]
    tube(m, tail + spiral[1:], 0.035, "driftwood", sides=5)


def quay_lamp(m):
    """An iron post with a ladder bar and a lantern glazed in whatever glass was to hand."""
    lathe(m, [(0.2, 0.0), (0.2, 0.08), (0.16, 0.12), (0.15, 0.45), (0.1, 0.5), (0.075, 0.55), (0.06, 2.3), (0.09, 2.33), (0.09, 2.4), (0.06, 2.42), (0.06, 2.5)], 8,
          lambda i, s, a, z: C("rust") if m.chance(0.45 if z < 0.6 else 0.12) else C("iron"))
    m.put(box((-0.33, -0.025, 2.2), (0.33, 0.025, 2.26)), "iron")
    for e in (-1, 1):
        m.put(cyl((e * 0.3, 0, 2.23), (e * 0.3, 0, 2.31), 0.025, 0.025, 4), "iron")
    s, z0, z1 = 0.19, 2.56, 2.98
    m.put(box((-s - 0.03, -s - 0.03, 2.5), (s + 0.03, s + 0.03, z0)), "iron")
    glass = ["aqua", "smoke", "green", "aqua", "amber", "smoke", "aqua", "green"]
    m.rng.shuffle(glass)
    k = 0
    for ang in range(4):
        rot = Matrix.Rotation(ang * math.pi / 2, 4, "Z")
        f = Face(rot @ Vector((0, -s, 0)), rot @ X, 2 * s)
        for j in range(2):
            za = z0 + 0.01 + j * 0.21
            m.pane([f.p(-s + 0.02, za, 0), f.p(s - 0.02, za, 0), f.p(s - 0.02, za + 0.19, 0), f.p(-s + 0.02, za + 0.19, 0)], glass[k], f.n, True)
            k += 1
        m.put(f.box(-s, s, z0 + 0.2, z0 + 0.225, -0.01, 0.015), "iron")
    for dx in (-s, s):
        for dy in (-s, s):
            m.put(box((dx - 0.02, dy - 0.02, z0), (dx + 0.02, dy + 0.02, z1)), "iron")
    m.put(cyl((0, 0, z1), (0, 0, z1 + 0.14), 0.29, 0.06, 4), "iron")
    m.put(cyl((0, 0, z1 + 0.12), (0, 0, 3.12), 0.06, 0.06, 6), "iron")
    m.put(cyl((0, 0, 3.12), (0, 0, 3.2), 0.07, 0.0, 6), "iron")
    for ang in (0.6, 2.4, 4.1):
        f = Wrapped(ang + math.radians(225) - 1.5, lambda z: 0.06 if z > 0.6 else 0.15)
        streak(m, f, 0.0, 2.29, m.rng.uniform(0.4, 0.8), "rust", 0.04, 0.008)


def boat(m):
    """A clinker-built boat turned over on two trestles for the winter: tarred strakes stepped
    where each laps the one below, a pale rubbing strake, the stove-in plank patched with bare
    wood and a tin patch on the garboard."""
    Lh, Bh, T = 2.04, 0.69, 0.69
    NS, NU = 15, 6

    def G(s):
        return 0.55 + 0.2 * s * s

    def half(s, u):
        return Bh * max(0.0, 1 - abs(s) ** 2.4) ** 0.65 * math.sin(u * math.pi / 2) ** 0.75

    def pt(s, u, side, lap=0.0):
        z = 0.04 * s ** 4 + (G(s) - 0.04 * s ** 4) * u ** 1.15
        return Vector((s * Lh, side * (half(s, u) + lap * (half(s, 1) > 0.01)), T + G(0) - z))
    ss = [-1 + 2 * i / NS for i in range(NS + 1)]
    patches = {(-1, 3, i) for i in (9, 10, 11)}
    for side in (-1, 1):
        for k in range(NU):
            u0, u1 = k / NU, (k + 1) / NU
            lap = 0.035 if k else 0.0
            for i in range(NS):
                s0, s1 = ss[i], ss[i + 1]
                inside = Vector(((s0 + s1) / 2 * Lh, 0, T + 0.1))
                col = C("driftwood") if (side, k, i) in patches else C("iron") if (side, k, i) == (-1, 0, 5) else jitter(C("tar"), m.rng, 0.05) if k % 2 else C("tar")
                q = [pt(s0, u0, side, lap), pt(s1, u0, side, lap), pt(s1, u1, side), pt(s0, u1, side)]
                m.poly(q, col, sum(q, Vector()) / 4 - inside, vary=0.04)
                if k == NU - 1:
                    m.poly([pt(s0, u1, side), pt(s1, u1, side), pt(s1, u1, side, -0.03), pt(s0, u1, side, -0.03)], "tar", -Z)
                if lap:
                    m.poly([pt(s0, u0, side), pt(s1, u0, side), pt(s1, u0, side, lap), pt(s0, u0, side, lap)], "tar", Z)
                inner = [pt(s0, u0, side, -0.03), pt(s1, u0, side, -0.03), pt(s1, u1, side, -0.03), pt(s0, u1, side, -0.03)]
                m.poly(inner, "tar", inside - sum(inner, Vector()) / 4)
        tube(m, [pt(s, 1.0, side, 0.03) for s in ss], 0.032, "driftwood", sides=4)
    for i in (9, 10, 11):
        for u in (0.52, 0.64):
            m.put(box(pt(ss[i] + 0.04, u, -1, 0.025) - Vector((0.01, 0.012, 0.01)), pt(ss[i] + 0.04, u, -1, 0.025) + Vector((0.01, 0.0, 0.01))), "iron")
    tube(m, [pt(s, 0.0, 1) + Z * 0.04 for s in ss], 0.045, "tar")
    for e in (-1, 1):
        tube(m, [pt(e, u, 1) + Vector((e * 0.03, 0, 0)) for u in (0.0, 0.33, 0.66, 1.0)], 0.04, "tar")
    for e in (-1, 1):
        x = e * 1.15
        zt = pt(x / Lh, 1.0, 1).z - 0.035
        m.put(box((x - 0.06, -0.73, zt - 0.1), (x + 0.06, 0.73, zt)), "driftwood")
        for dy in (-0.6, 0.6):
            for dx in (-0.22, 0.22):
                m.put(cyl((x + dx, dy * 1.12, 0.0), (x, dy, zt - 0.05), 0.035, 0.035, 4), "driftwood")


def peat_stack(m):
    """Peats stacked in courses, the top under a tarred sheet held down by stones on ropes; a
    peat spade leaning on it."""
    # The stack steps in course by course; its ridge is under the sheet.
    core = bmesh.new()
    for x, y, z in [(sx * 0.86, sy * 0.34, 0.0) for sx in (-1, 1) for sy in (-1, 1)] + [(sx * 0.66, sy * 0.16, 0.9) for sx in (-1, 1) for sy in (-1, 1)]:
        core.verts.new((x, y, z))
    bmesh.ops.convex_hull(core, input=core.verts)
    m.put(core, "peat")
    m.put(prism([(-0.2, 0.88), (0.2, 0.88), (0.0, 1.28)], -0.68, 0.68, lambda a, s, z: Vector((a, s, z))), "peat")
    faces = B.box_faces(0.0, 0.0, 0.9, 0.38)
    for j in range(5):
        z0, inset = 0.02 + j * 0.17, -0.045 * j
        for f in faces.values():
            half = f.length / 2 + inset
            a = -half + (0.21 if j % 2 else 0.0)
            while a < half - 0.05:
                a1 = min(half, a + 0.42)
                m.put(f.box(a + 0.015, a1 - 0.015, z0, z0 + 0.15, inset - 0.06, inset + 0.0 + m.rng.uniform(0, 0.03), back=False), "peat", vary=0.05)
                a = a1
    nx, ny = 12, 8
    grid_pts = []
    for i in range(nx + 1):
        x = -1.0 + 2.0 * i / nx
        colm = []
        for j in range(ny + 1):
            v = -1 + 2 * j / ny
            y = v * 0.47
            z = 1.375 - 0.4 * abs(v) - (0.0 if abs(v) < 0.85 else 0.45 * (abs(v) - 0.85) / 0.15) + 0.02 * math.sin(x * 5 + v * 3)
            yy = y
            colm.append(Vector((x * (1.0 - 0.04 * (abs(v) > 0.85)), yy, max(z, 0.62 + 0.08 * math.sin(x * 7)))))
        grid_pts.append(colm)
    for i in range(nx):
        for j in range(ny):
            q = [grid_pts[i][j], grid_pts[i + 1][j], grid_pts[i + 1][j + 1], grid_pts[i][j + 1]]
            ctr = sum(q, Vector()) / 4
            m.poly(q, C("tar", "cloth"), ctr - Vector((ctr.x * 0.5, 0, 0.7)), vary=0.03)
    for x in (-0.95, 0.95):
        for j in range(ny):
            q = [grid_pts[0 if x < 0 else nx][j], grid_pts[0 if x < 0 else nx][j + 1]]
            m.poly([q[0], q[1], Vector((x, q[1].y, max(q[1].z - 0.35, 0.7))), Vector((x, q[0].y, max(q[0].z - 0.35, 0.7)))], C("tar", "cloth"), Vector((x, 0, 0)))
    for x in (-0.6, 0.6):
        for s in (-1, 1):
            top = Vector((x, 0.0, 1.38))
            hem = Vector((x, s * 0.49, 0.66))
            stone = Vector((x, s * 0.5, 0.36))
            tube(m, [top, Vector((x, s * 0.36, 1.22)), hem, stone + Z * 0.1], 0.015, "driftwood", sides=3)
            m.put(sphere(stone, 0.1, 0, squash=0.8), "pale_basalt", soft=stone)
    m.put(cyl((0.3, -0.55, 0.3), (0.26, -0.47, 1.25), 0.025, 0.025, 4), "driftwood")
    m.put(box((0.22, -0.6, 0.02), (0.38, -0.57, 0.32)), "iron")


def floats(m):
    """A ship's spar for a post, a cross-arm, glass floats hanging in net bags in three
    colours, and a crate of cullet beside it, a few shards spilled."""
    m.put(cyl((0, 0, 0), (0, 0, 2.0), 0.07, 0.06, 6), "driftwood")
    m.put(box((-0.42, -0.04, 1.72), (0.42, 0.04, 1.8)), "driftwood")
    m.put(cyl((0.0, 0.0, 1.35), (0.3, 0.0, 1.74), 0.025, 0.025, 4), "driftwood")
    hang = [(-0.36, 1.72, 0.45, "green"), (0.36, 1.72, 0.32, "amber"), (-0.2, 1.72, 0.7, "aqua"), (0.18, 1.72, 0.85, "green"), (0.07, 1.25, 0.3, "aqua"), (-0.07, 0.9, 0.25, "amber")]
    for x, zt, ln, col in hang:
        y = -0.08 if abs(x) < 0.1 else 0.0
        c = Vector((x, y, zt - ln - 0.125))
        m.put(sphere(c, 0.125, 1), col, soft=c)
        tube(m, [Vector((x, y, zt)), c + Z * 0.125], 0.008, "tar", sides=3)
        for ang in (0.0, math.pi / 2):
            ring = [c + Vector((math.cos(ang) * 0.128 * math.sin(t), math.sin(ang) * 0.128 * math.sin(t), 0.128 * math.cos(t))) for t in (k * math.tau / 8 for k in range(9))]
            tube(m, ring, 0.008, "tar", sides=3)
    cx, cy = 0.62, -0.2
    for a0, a1, b0, b1 in ((-0.4, 0.4, -0.28, -0.25), (-0.4, 0.4, 0.25, 0.28), (-0.4, -0.37, -0.28, 0.28), (0.37, 0.4, -0.28, 0.28)):
        for z0 in (0.02, 0.17, 0.32):
            m.put(box((cx + a0, cy + b0, z0), (cx + a1, cy + b1, z0 + 0.13)), "driftwood", vary=0.05)
    m.put(box((cx - 0.37, cy - 0.25, 0.0), (cx + 0.37, cy + 0.25, 0.32)), "driftwood")
    shards = [(cx + m.rng.uniform(-0.33, 0.33), cy + m.rng.uniform(-0.22, 0.22), 0.36 + m.rng.uniform(0, 0.08)) for _ in range(26)]
    shards += [(cx + m.rng.uniform(-0.6, 0.6), cy - 0.38 + m.rng.uniform(-0.1, 0.06), 0.02) for _ in range(6)]
    for i, p in enumerate(shards):
        r = m.rng.uniform(0.04, 0.08)
        bm = bmesh.new()
        vs = [bm.verts.new(Vector(p) + Vector((m.rng.uniform(-r, r), m.rng.uniform(-r, r), m.rng.uniform(0, r * 0.8)))) for _ in range(3)]
        vs.append(bm.verts.new(Vector(p) + Vector((0, 0, -0.01))))
        for f in ((0, 1, 2), (0, 1, 3), (1, 2, 3), (0, 2, 3)):
            try:
                bm.faces.new([vs[k] for k in f])
            except ValueError:
                pass
        m.put(bm, ("aqua", "green", "amber", "smoke")[i % 4])


# ---------------------------------------------------------------------------------------------
# Running, checks and the report

PIECES = [("cone", cone, 1.8, 12000), ("row", row, 1.8, 16000), ("glasshouse", glasshouse, 1.8, 9000),
          ("net_rack", net_rack, 0.4, 1500), ("barrels", barrels, 0.4, 1500), ("creels", creels, 0.4, 1500),
          ("bollard", bollard, 0.4, 1500), ("quay_lamp", quay_lamp, 0.4, 1500), ("boat", boat, 0.4, 2500),
          ("peat_stack", peat_stack, 0.4, 1500), ("floats", floats, 0.4, 1500)]
BRIEF = dict(cone="base 14.0 across, 24.0 to the rim", row=[22.0, 7.5], glasshouse=[12.0, 4.5], net_rack=[3.0, 0.6, 2.2], barrels=[1.8, 1.4, 1.1],
             creels=[1.4, 1.0, 0.9], bollard=[0.6, 0.6, 1.1], quay_lamp="3.2 high", boat=[4.2, 1.5, 1.3], peat_stack=[2.0, 1.2, 1.4],
             floats="2 m post, 0.25 m floats, 0.8 m crate")


def audit(m):
    """Before export: every vertex colour's distance from the palette, and the triangles on Body
    with no painted surface."""
    pal = list(PAL.values())
    worst, off, untagged, lit = 0.0, 0, 0, 0
    names = [mt.name for mt in m.b.mats]
    for f in m.b.bm.faces:
        tris = len(f.verts) - 2
        body = names[f.material_index] == "Body"
        for loop in f.loops:
            c = loop[m.b.col]
            d = min(max(abs(c[0] - p[0]), abs(c[1] - p[1]), abs(c[2] - p[2])) for p in pal)
            worst = max(worst, d)
            off += d > 0.05 + 1.5 / 255
        if body:
            lit += tris
            untagged += tris if f.loops[0][m.b.col][3] > 0.99 else 0
    return dict(palette_max_dev=round(worst, 4), off_palette_corners=off, tagged_pct=round(100.0 * (lit - untagged) / max(lit, 1), 2))


def build(name, fn, depth, budget, seed, out):
    B.reset()
    t0 = time.perf_counter()
    m = M(seed, name)
    fn(m)
    footing(m, depth)
    check = audit(m)
    obj, _ = m.b.finish(name)
    path = os.path.join(out, f"{name}.glb")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_vertex_color="ACTIVE", export_normals=True, export_yup=True, use_selection=False)
    secs = time.perf_counter() - t0
    vs = obj.data.vertices
    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    above = [v.co for v in vs if v.co.z >= -0.005]

    def ext(pts, i):
        return round(max(p[i] for p in pts) - min(p[i] for p in pts), 3)
    facts = {k: (sorted(v) if isinstance(v, set) else v) for k, v in m.facts.items()}
    if "max_pane" in facts:
        facts["max_pane"] = round(facts["max_pane"], 3)
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    rec = dict(file=f"{name}.glb", footprint_m=[ext(above, 0), ext(above, 1)], footprint_with_foundation_m=[ext([v.co for v in vs], 0), ext([v.co for v in vs], 1)],
               height_m=round(max(v.co.z for v in vs), 3), foundation_m=round(-min(v.co.z for v in vs), 3), tris=tris, budget=budget,
               within_budget=tris <= budget, materials=[mt.name for mt in obj.data.materials], brief=BRIEF[name], seconds=round(secs, 2),
               sha256=digest, **check, facts=facts)
    print(f"CULLET {name}: tris={tris}/{budget} foot={rec['footprint_m']} h={rec['height_m']} {check} {secs:.1f}s")
    return rec


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--only", help="comma-separated pieces")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    t0 = time.perf_counter()
    models = [build(n, fn, d, bud, a.seed, a.out) for n, fn, d, bud in PIECES if only is None or n in only]
    report = dict(arm="opus", script="living/tools/blender/ab/cullet_opus.py", seed=a.seed, blender=bpy.app.version_string,
                  seconds=round(time.perf_counter() - t0, 2), palette=PAL, models=models)
    if only is None:
        with open(os.path.join(a.out, "report.json"), "w") as f:
            json.dump(report, f, indent=1)
    print(f"CULLET done in {report['seconds']}s")


if __name__ == "__main__":
    main()
