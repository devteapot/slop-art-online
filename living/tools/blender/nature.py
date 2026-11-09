"""Stylized nature generator for the game client's test environments.

Run headless:
    blender -b -P living/tools/blender/nature.py -- --kind tree --style meadow --count 12 --out DIR

Kinds: trees by species and age (tree, oak, birch, pine, spruce, coppice, young, sapling, snag,
giant), bush, rock, flower, grass, glow_mushroom, glow_plant, crystal, log, stalagmite. Styles
shift colours and shapes (meadow, forest, spirit); in the spirit style, tree, giant and sapling
are glowing spirit trees. Every asset is real-size in metres,
origin at its base, +Z up in Blender (+Y in glTF), coloured by vertex colours (linear, gradients
baked per vertex) on white materials so the game's toon material does the shading. Glowing
parts use a material whose name starts with "Glow" and that has emission.

Readability rules, judged through the game's renderer at the gameplay camera (40° down, 16 m):
- Small things come as clumps or patches (flowers, grass tufts, mushroom clusters), never as
  one 30 cm stem.
- Foliage is built as a Crown of lobes (see Crown): buried faces dropped, leafy points poked out
  at the silhouette, and normals pointing out from near the crown's centre, so a crown shades as
  one soft mass with a jagged, leafy edge (Genshin and Ghibli foliage), not as separate balls.
  Grass and flower heads point up, so they shade like the ground.
- Forest trees carry their crowns high on long trunks, so a 40°/16 m camera sees trunks and
  the floor beneath instead of a lid of canopy. Open-grown meadow trees keep broad crowns.
- A forest reads as one when its trees differ in species, age and growth form, not only in size:
  each tree kind draws crown shape, lean, curvature, limbs and leaf tint from the seed (see Trees).
- Young trees and saplings carry tall, uneven crowns that start low on the stem, never a ball
  on a stick. Conifer skirts are pads of branch arms of uneven length with turned-up tips and
  dark undersides; some pines are old Scots pines with flat, layered pads.
- Rocks are convex hulls of a few points on a stretched ellipsoid (boulder, slab, standing
  stone, block): a few big, crisp facets give a strong silhouette.
- Triangle budgets: under about 3k per large tree, under 800 per sapling or snag.
- Emission is in nits: Bevy's default camera exposure (EV100 9.7) multiplies emissive by about
  1/1000, so `glow(level)` writes level × 1000 as the glTF emissive strength; level 1 is about
  1.0 linear on screen before tonemapping and bloom.
"""

import argparse
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector, noise

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "textures"))
from surfaces import alpha as surface_alpha  # noqa: E402

NITS = 1000.0 * float(os.environ.get("NATURE_GLOW", "1"))
UP = Vector((0, 0, 1))

STYLES = {
    # leaf: deep (inside, below), mid, top (sunlit, a little warmer). All linear RGB. Each tree
    # shifts its ramp lighter or darker and often towards one of `tints` (leaf_stops).
    # tree: the broadleaf kind's height, crown base and width (× height), side lobes, chance of a
    # strong lean, and the weights of its growth forms (round, oval, fork, onesided, layered).
    "meadow": dict(
        leaf=((0.035, 0.10, 0.045), (0.12, 0.30, 0.06), (0.36, 0.58, 0.10)),
        birch=((0.05, 0.12, 0.04), (0.2, 0.4, 0.07), (0.55, 0.72, 0.15)),
        needle=((0.02, 0.07, 0.05), (0.08, 0.22, 0.11), (0.22, 0.42, 0.16)),
        tints=((0.5, 0.62, 0.1), (0.05, 0.3, 0.22), (0.3, 0.34, 0.08)),
        bark=(0.14, 0.11, 0.09), oak_bark=(0.12, 0.105, 0.09), pine_bark=(0.3, 0.14, 0.07),
        rock=(0.36, 0.35, 0.33), moss=(0.16, 0.32, 0.06),
        grass=((0.08, 0.20, 0.03), (0.34, 0.58, 0.05)),
        tree=dict(h=(7, 11), base=0.36, width=0.31, lobes=(0, 1), lean=0.1, forms=(4, 1, 2, 2, 2)),
        young_conifer=0.2,
        petals=[(0.92, 0.22, 0.38), (0.95, 0.68, 0.06), (0.42, 0.28, 0.90), (0.90, 0.90, 0.94), (0.90, 0.20, 0.06), (0.25, 0.48, 0.95)],
        glow=(0.4, 1.0, 0.9)),
    "forest": dict(
        leaf=((0.015, 0.05, 0.03), (0.05, 0.16, 0.05), (0.19, 0.38, 0.08)),
        birch=((0.03, 0.08, 0.03), (0.13, 0.3, 0.06), (0.42, 0.58, 0.12)),
        needle=((0.015, 0.05, 0.04), (0.06, 0.17, 0.09), (0.16, 0.33, 0.14)),
        spruce=((0.008, 0.03, 0.035), (0.03, 0.1, 0.09), (0.09, 0.22, 0.17)),
        tints=((0.42, 0.55, 0.08), (0.04, 0.24, 0.18), (0.26, 0.3, 0.07)),
        bark=(0.10, 0.085, 0.075), oak_bark=(0.09, 0.08, 0.07), pine_bark=(0.26, 0.11, 0.05),
        rock=(0.30, 0.30, 0.28), moss=(0.10, 0.26, 0.05),
        grass=((0.04, 0.11, 0.03), (0.18, 0.36, 0.07)),
        tree=dict(h=(10, 15), base=0.5, width=0.23, lobes=(0, 2), lean=0.14, forms=(3, 3, 3, 2, 1)),
        young_conifer=0.4,
        petals=[(0.9, 0.9, 0.95), (0.95, 0.75, 0.3)], glow=(0.4, 1.0, 0.9)),
    "spirit": dict(
        leaf=((0.01, 0.03, 0.07), (0.03, 0.12, 0.20), (0.10, 0.36, 0.45)),
        tints=((0.06, 0.3, 0.5), (0.2, 0.18, 0.5), (0.05, 0.4, 0.32)),
        bark=(0.06, 0.05, 0.08), rock=(0.16, 0.17, 0.24), moss=(0.06, 0.20, 0.24),
        grass=((0.02, 0.06, 0.08), (0.08, 0.26, 0.30)),
        tree=dict(h=(8, 12), base=0.5, width=0.38, clumps=(7, 9)),
        petals=[(0.6, 0.9, 1.0), (0.85, 0.6, 1.0)],
        glow=(0.1, 1.0, 0.72), fruit=(1.0, 0.42, 0.04), bloom=(0.55, 0.22, 1.0), crystal=(0.2, 0.32, 1.0),
        # Spirit trees mostly glow teal, some blue or violet; lanterns orange, gold or rose.
        glows=[(0.1, 1.0, 0.72), (0.2, 0.62, 1.0), (0.62, 0.32, 1.0)], glow_weights=(6, 2, 2),
        fruits=[(1.0, 0.42, 0.04), (1.0, 0.42, 0.04), (1.0, 0.72, 0.18), (1.0, 0.32, 0.5)]),
}


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name, emission=None, level=0.0, cull=False):
    """A white material (vertex colours carry the colour); `emission` makes it glow at `level`."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    if m.node_tree is None:  # Blender 5 materials always have a node tree
        m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (1, 1, 1, 1)
    bsdf.inputs["Roughness"].default_value = 0.9
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = level * NITS
    # Two-sided parts are built as back-to-back faces, so their material culls back faces
    # (glTF doubleSided false) and every visible face keeps its own upward normal.
    m.use_backface_culling = cull
    return m


def glow(name, color, level):
    return material(name, emission=color, level=level)


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def ramp(stops, t):
    """Piecewise-linear gradient through evenly spaced colour stops."""
    t = min(1.0, max(0.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return lerp(stops[i], stops[i + 1], t - i)


def jitter(c, rng, k=0.06):
    return tuple(min(1, max(0, x * (1 + rng.uniform(-k, k)))) for x in c)


def scale(c, k):
    return tuple(min(1.0, x * k) for x in c)


def srgb(c):
    """Linear to sRGB: bmesh's colour layer is stored as sRGB bytes, and the exporter writes
    it back out as linear COLOR_0, so the palettes here can stay linear."""
    return tuple(12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055 for x in c)


FLAT, SMOOTH = 0, -1

# The painted surface (living/tools/textures/surfaces.py) of each material's parts, which the
# game multiplies into their vertex colours; it travels in the colours' alpha, so materials stay
# shared. "Tree" holds bark and leaves alike: parts with a crown centre are foliage.
SURFACE_OF = {"Bark": "bark", "Stone": "boulder", "Leaves": "leaves", "Tree": "bark"}


class Builder:
    """Accumulates parts into one bmesh with a per-corner colour layer and material slots."""

    def __init__(self):
        self.bm = bmesh.new()
        self.col = self.bm.loops.layers.color.new("Color")
        # Shading per face: 0 flat, -1 smooth, k > 0 radial from self.centres[k - 1].
        self.shade_layer = self.bm.faces.layers.int.new("shade")
        self.mats = []
        self.centres = []
        self.pinned = {}  # merged vertex -> normal, overriding its shading

    def slot(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def add(self, bm_part, mat, color_fn, centre=None, flat=0.15, smooth=False, two_sided=False, per_face=False, pin=None, surface=""):
        """Merge a part: color_fn(vertex_co, face_normal) -> rgb.

        centre: foliage normals point out from it (lerped `flat` towards the face normal).
        smooth: averaged vertex normals (trunks, stems). two_sided: add back faces too.
        per_face: one colour per face, from its centre (crisp bark marks).
        pin: {part vertex: normal} for vertices whose normal is set, not derived.
        surface: the painted surface (default from the material, SURFACE_OF; None for none).
        """
        idx = self.slot(mat)
        if surface == "":
            surface = SURFACE_OF.get(mat.name)
            if mat.name == "Tree" and centre is not None:
                surface = "leaves"
        a = surface_alpha(surface)
        if centre is not None:
            self.centres.append((Vector(centre), flat))
            shade = len(self.centres)
        else:
            shade = SMOOTH if smooth else FLAT
        for reverse in ((False, True) if two_sided else (False,)):
            mapping = {v: self.bm.verts.new(v.co) for v in bm_part.verts}
            for v, n in (pin or {}).items():
                self.pinned[mapping[v]] = n
            for f in bm_part.faces:
                vs = [mapping[v] for v in f.verts]
                try:
                    nf = self.bm.faces.new(vs[::-1] if reverse else vs)
                except ValueError:
                    continue
                nf.material_index = idx
                nf[self.shade_layer] = shade
                nf.normal_update()
                if per_face:
                    c = (*srgb(color_fn(nf.calc_center_median(), nf.normal)), a)
                    for loop in nf.loops:
                        loop[self.col] = c
                    continue
                for loop in nf.loops:
                    loop[self.col] = (*srgb(color_fn(loop.vert.co, nf.normal)), a)
        bm_part.free()

    def finish(self, name):
        mesh = bpy.data.meshes.new(name)
        shade = [f[self.shade_layer] for f in self.bm.faces]
        self.bm.verts.index_update()
        pinned = {v.index: n for v, n in self.pinned.items() if v.is_valid}
        self.bm.to_mesh(mesh)
        self.bm.free()
        for m in self.mats:
            mesh.materials.append(m)
        # The exporter writes the active colour attribute as COLOR_0.
        if "Color" in mesh.color_attributes:
            mesh.color_attributes.active_color = mesh.color_attributes["Color"]
            mesh.color_attributes.render_color_index = mesh.color_attributes.active_color_index
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        mesh.shade_flat()
        vnormals = [v.normal.copy() for v in mesh.vertices]
        normals = [None] * len(mesh.loops)
        for poly in mesh.polygons:
            s = shade[poly.index]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                if s > 0 and vi in pinned:
                    normals[li] = pinned[vi]
                elif s > 0:
                    c, flat = self.centres[s - 1]
                    n = (mesh.vertices[vi].co - c).normalized()
                    normals[li] = n.lerp(poly.normal, flat).normalized()
                elif s == SMOOTH:
                    normals[li] = vnormals[vi]
                else:
                    normals[li] = poly.normal.copy()
        mesh.normals_split_custom_set(normals)
        return obj


# ---------------------------------------------------------------------------------------------
# Shapes

def blob(centre, radius, rng, subdiv=2, squash=1.0, roughness=0.18):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=radius)
    off = Vector((rng.random() * 100, rng.random() * 100, rng.random() * 100))
    for v in bm.verts:
        d = noise.noise(v.co * (1.6 / radius) + off)
        v.co *= 1 + d * roughness
        v.co.z *= squash
        v.co += centre
    return bm


def tube(points, radii, sides=6, cap=True):
    """A tube along a polyline (parallel-transported frame); radius 0 at the end makes a tip."""
    bm = bmesh.new()
    n = len(points)
    d0 = (points[1] - points[0]).normalized()
    ref = Vector((1, 0, 0)) if abs(d0.x) < 0.9 else Vector((0, 1, 0))
    u = (ref - d0 * ref.dot(d0)).normalized()
    rings = []
    for i, p in enumerate(points):
        d = (points[min(i + 1, n - 1)] - points[max(i - 1, 0)]).normalized()
        u = (u - d * u.dot(d)).normalized()
        w = d.cross(u)
        if radii[i] <= 1e-5:
            rings.append([bm.verts.new(p)])
            continue
        rings.append([bm.verts.new(p + (u * math.cos(a) + w * math.sin(a)) * radii[i]) for a in (k / sides * math.tau for k in range(sides))])
    for i in range(n - 1):
        a, b = rings[i], rings[i + 1]
        for k in range(sides):
            if len(b) == 1:
                bm.faces.new((a[k], a[(k + 1) % sides], b[0]))
            else:
                bm.faces.new((a[k], a[(k + 1) % sides], b[(k + 1) % sides], b[k]))
    if cap and len(rings[-1]) > 1:
        bm.faces.new(rings[-1])
    return bm


def curve(a, b, bend, segs):
    """Points from a to b, bowed by the vector `bend` at the middle."""
    return [a.lerp(b, t) + bend * (4 * t * (1 - t)) for t in (i / segs for i in range(segs + 1))]


def strip(points, widths, side):
    """A flat ribbon along points, `side` across it; width 0 at the end makes a pointed tip."""
    bm = bmesh.new()
    rows = []
    for p, w in zip(points, widths):
        rows.append([bm.verts.new(p)] if w <= 1e-5 else [bm.verts.new(p - side * w / 2), bm.verts.new(p + side * w / 2)])
    for a, b in zip(rows, rows[1:]):
        if len(b) == 1:
            bm.faces.new((a[0], a[1], b[0]))
        else:
            bm.faces.new((a[0], a[1], b[1], b[0]))
    return bm


def blade(base, angle, length, width, lean, droop, segs=3):
    """A grass blade or leaf: leaning out at `angle`, drooping towards the tip."""
    out = Vector((math.cos(angle), math.sin(angle), 0))
    side = Vector((-math.sin(angle), math.cos(angle), 0))
    pts = []
    for i in range(segs + 1):
        t = i / segs
        pts.append(base + out * (math.sin(lean) * length * t + droop * length * t * t) + UP * (math.cos(lean) * length * t - droop * 0.7 * length * t * t))
    widths = [width * (1 - t) ** 0.7 * (0.75 + 0.25 * math.sin(t * math.pi)) for t in (i / segs for i in range(segs + 1))]
    return strip(pts, widths, side)


def star(centre, radius, petals, tilt, rng, cup=0.25):
    """A flower head: a petal-notched disc, cupped, facing up and tilted by the (x, y) `tilt`."""
    bm = bmesh.new()
    c = bm.verts.new(Vector((0, 0, 0)))
    rim = []
    a0 = rng.uniform(0, math.tau)
    for p in range(petals):
        base = a0 + p / petals * math.tau
        step = math.tau / petals
        for da, r in ((-0.5, 0.35), (-0.22, 0.95), (0.18, 0.95)):
            a = base + da * step
            rim.append(bm.verts.new(Vector((math.cos(a) * r * radius, math.sin(a) * r * radius, r * r * cup * radius))))
    for i in range(len(rim)):
        bm.faces.new((c, rim[i], rim[(i + 1) % len(rim)]))
    m = Matrix.Translation(centre) @ Matrix.Rotation(tilt[0], 4, "X") @ Matrix.Rotation(tilt[1], 4, "Y")
    bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
    return bm


def dome(centre, radius, rng, height=0.55, subdiv=2, roughness=0.06):
    """A mushroom cap: the top of a noisy sphere, flattened, open underneath."""
    bm = blob(Vector((0, 0, 0)), radius, rng, subdiv=subdiv, roughness=roughness)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -radius * 0.12], context="VERTS")
    for v in bm.verts:
        v.co.z = (v.co.z + radius * 0.12) * height
    bmesh.ops.translate(bm, vec=centre, verts=bm.verts)
    return bm


def disc(centre, radius, sides, rise=0.0):
    """A downward-facing disc (cap underside, gills), its middle raised by `rise`."""
    bm = bmesh.new()
    c = bm.verts.new(centre + Vector((0, 0, rise)))
    ring = [bm.verts.new(centre + Vector((math.cos(a) * radius, math.sin(a) * radius, 0))) for a in (k / sides * math.tau for k in range(sides))]
    for k in range(sides):
        bm.faces.new((c, ring[(k + 1) % sides], ring[k]))
    return bm


def gem(centre, r, sides=5):
    """A small bipyramid (10 triangles): glowing dots, leaf tips."""
    bm = bmesh.new()
    top, bot = bm.verts.new(centre + UP * r), bm.verts.new(centre - UP * r)
    ring = [bm.verts.new(centre + Vector((math.cos(a) * r, math.sin(a) * r, 0))) for a in (k / sides * math.tau for k in range(sides))]
    for k in range(sides):
        bm.faces.new((ring[k], ring[(k + 1) % sides], top))
        bm.faces.new((ring[(k + 1) % sides], ring[k], bot))
    return bm


def solid(c, rng, k=0.06):
    return lambda co, n: jitter(c, rng, k)


# ---------------------------------------------------------------------------------------------
# Trees
#
# A stand reads as a forest when its trees differ in kind, age and growth form, not only in
# size. Each kind below draws its own crown shape, lean, curvature, limb count and leaf tint from
# the seed, so a dozen variants of one kind aren't clones. The game scales a model to a height
# from its slot's range, keeping proportions, so each kind is drawn at about the middle of the
# heights its slots use: saplings, young trees and giants are separate kinds, not scaled copies.
#
# Bark and foliage share one white material ("Tree"): vertex colours carry the colour, and one
# material per tree is one draw instead of two.

SINK = 0.3  # trunks start this far below the origin, so they stay planted on slopes


def leaf_stops(st, rng, key="leaf"):
    """The style's leaf ramp for one tree: lighter or darker, and often tinted towards one of the
    style's tints (yellow-green, blue-green, olive) at the same brightness."""
    stops = st.get(key, st["leaf"])
    k = rng.uniform(0.82, 1.18)
    tints = st.get("tints", ())
    tint = rng.choice(tints) if tints and rng.random() < 0.75 else None
    amt = rng.uniform(0.2, 0.45)
    out = []
    for s in stops:
        c = scale(s, k)
        if tint:
            c = lerp(c, scale(tint, sum(c) / max(sum(tint), 1e-3)), amt)
        out.append(jitter(c, rng, 0.05))
    return out


def crown_colour(st, rng, lo, hi, centre, rx, rz, top=1.0, stops=None):
    """Leaves: darker inside and below, lighter and warmer on the sunlit top (up to `top` of
    the way along the leaf ramp)."""
    stops = stops or [jitter(s, rng, 0.08) for s in st["leaf"]]

    def f(co, n):
        # From position only (not the facet's normal), so leafy points don't speckle the mass.
        tz = (co.z - lo) / max(hi - lo, 1e-3)
        d = co - centre
        out = math.sqrt((d.x / rx) ** 2 + (d.y / rx) ** 2 + (d.z / rz) ** 2)
        up = max(0.0, d.z / max(d.length, 1e-3))
        return jitter(ramp(stops, top * (0.55 * tz + 0.3 * min(out, 1.2) + 0.15 * up - 0.1)), rng, 0.03)
    return f


def bark_colour(c, rng, foot=0.7, rise=3.0):
    return lambda co, n: jitter(lerp(scale(c, foot), c, min(1, max(0.0, co.z) / rise)), rng, 0.05)


def direction(a):
    return Vector((math.cos(a), math.sin(a), 0))


def heading(rng):
    return direction(rng.uniform(0, math.tau))


def stem(top_z, rng, segs=6, base=None, lean=None, lean_pow=2.0, bow=0.0, wiggle=0.25):
    """A trunk's centre line from `base` up to `top_z`: a lean that grows with height (`lean_pow`
    below 1 leans from the foot and straightens; above 1 stays upright and bends near the top),
    a sideways bow and a little noise."""
    base = base if base is not None else Vector((0, 0, -SINK))
    lean = lean if lean is not None else Vector((0, 0, 0))
    bowv = heading(rng) * bow
    seed = rng.random() * 10
    pts = []
    for i in range(segs + 1):
        t = i / segs
        w = Vector((noise.noise(Vector((t * 2.2, seed, 0))), noise.noise(Vector((seed, t * 2.2, 0))), 0)) * wiggle
        pts.append(base + UP * (top_z - base.z) * t + lean * t ** lean_pow + bowv * math.sin(math.pi * t) + w * t)
    return pts


def taper(r0, n, top=0.35, flare=0.4):
    """Radii along a trunk: thinning to `top` × r0, with a flared foot."""
    out = []
    for i in range(n):
        t = i / (n - 1)
        out.append(r0 * (1 - (1 - top) * t) * (1 + flare * max(0.0, 1 - t * 4) ** 2))
    return out


def along(pts, t):
    q = min(max(t, 0.0), 1.0) * (len(pts) - 1)
    i = min(int(q), len(pts) - 2)
    return pts[i].lerp(pts[i + 1], q - i)


def along_r(radii, t):
    q = min(max(t, 0.0), 1.0) * (len(radii) - 1)
    i = min(int(q), len(radii) - 2)
    return radii[i] + (radii[i + 1] - radii[i]) * (q - i)


def at_height(pts, z):
    """The fraction along a mostly upright stem at height z."""
    lo, hi = pts[0].z, pts[-1].z
    return (z - lo) / max(hi - lo, 1e-3)


def roots(b, mat, col, r0, count, rng, reach=3.2, base=None):
    base = base if base is not None else Vector((0, 0, 0))
    for k in range(count):
        a = k / count * math.tau + rng.uniform(-0.4, 0.4)
        out = direction(a)
        top = base + out * r0 * 0.3 + UP * r0 * rng.uniform(1.6, 2.6)
        end = base + out * r0 * reach * rng.uniform(0.8, 1.2) + UP * -SINK * 0.7
        b.add(tube(curve(top, end, out * r0 * 0.3, 2), [r0 * 0.55, r0 * 0.35, r0 * 0.08], 5, cap=False), mat, col, smooth=True)


def limb(b, mat, col, a, e, r0, r1, arch=0.25, segs=2, sides=5):
    """A branch from a to e, arched up by `arch` × its length at the middle."""
    d = (e - a).length
    radii = [r0 + (r1 - r0) * i / segs for i in range(segs + 1)]
    b.add(tube(curve(a, e, UP * d * arch, segs), radii, sides), mat, col, smooth=True)


def tris(b):
    return sum(len(f.verts) - 2 for f in b.bm.faces)


class Crown:
    """A tree's leaf mass, gathered as lobes and built in one go (Genshin- and Ghibli-style
    foliage: a soft mass with leafy edges):
    - faces buried inside a neighbouring lobe are dropped, so overlapping lobes cost little;
    - a share of the exposed, outward faces is poked out into leafy points that lean out and
      droop, so the silhouette breaks into leaf clumps;
    - every lobe's normals point out from a point pulled towards the crown's centre, so the
      lobes shade together as one mass and only its big notches and gaps read as form."""

    def __init__(self, centre, col, pull=0.85, jag=0.5, tip=0.22, droop=0.6):
        self.c = Vector(centre)
        self.col, self.pull, self.jag, self.tip, self.droop = col, pull, jag, tip, droop
        self.lobes = []

    def lobe(self, c, r, squash=0.9, rough=0.16, sub=2, nc=None, jag=None):
        """One leaf lobe; `nc` overrides the point its normals point out from."""
        self.lobes.append(dict(c=Vector(c), r=r, sq=squash, rough=rough, sub=sub, nc=nc, jag=jag))

    def cluster(self, rng, c, r, sats=1, squash=0.85, sub=2, rough=0.18):
        """A branch's leaf mass: a main lobe and smaller ones on its outer, upper side."""
        self.lobe(c, r, squash, rough, sub)
        out = c - self.c
        out.z = 0
        out = out.normalized() if out.length > 1e-3 else Vector((0, 0, 0))
        for _ in range(sats):
            e = rng.uniform(-0.1, 0.9)
            d = (heading(rng) * math.cos(e) + UP * math.sin(e) + out * 0.8).normalized()
            self.lobe(c + d * r * rng.uniform(0.55, 0.75), r * rng.uniform(0.45, 0.62), squash, rough, min(sub, 2) if r > 1.2 else 1)

    def inside(self, p, skip, k=0.9):
        for j, l in enumerate(self.lobes):
            if j == skip:
                continue
            d = p - l["c"]
            r = l["r"] * k
            if (d.x / r) ** 2 + (d.y / r) ** 2 + (d.z / (r * l["sq"])) ** 2 < 1.0:
                return True
        return False

    def build(self, b, mat, rng):
        for i, l in enumerate(self.lobes):
            c, r = l["c"], l["r"]
            bm = blob(c, r, rng, subdiv=l["sub"], squash=l["sq"], roughness=l["rough"])
            bm.normal_update()
            buried = [f for f in bm.faces if all(self.inside(v.co, i) for v in f.verts)]
            if len(buried) < len(bm.faces):
                bmesh.ops.delete(bm, geom=buried, context="FACES")
            jag = self.jag if l["jag"] is None else l["jag"]
            pick = []
            for f in bm.faces:
                m = f.calc_center_median()
                # Long points on the sides and underside, where the outline is; short, flat-lying
                # ones on the sunlit top, where long ones would speckle the mass with shadow.
                if f.normal.dot(m - self.c) > 0 and not self.inside(m, i, 1.0) and rng.random() < (jag if f.normal.z < 0.55 else jag * 0.6):
                    pick.append(f)
            nc = l["nc"] if l["nc"] is not None else c.lerp(self.c, self.pull)
            pin = {}
            if pick:
                tips = bmesh.ops.poke(bm, faces=pick)["verts"]
                for v in tips:
                    # A leafy point shades as the surface it grows from: only the outline changes.
                    pin[v] = (v.co - nc).normalized()
                    out = ((v.co - c).normalized() + (v.co - self.c).normalized()).normalized()
                    top = out.z > 0.55
                    d = (out - UP * self.droop * max(0.2, 1 - out.z) - (UP * out.z * 0.8 if top else Vector())).normalized()
                    v.co += d * r * self.tip * rng.uniform(0.6, 1.25) * (0.45 if top else 1.0)
            b.add(bm, mat, self.col, nc, flat=0.0, pin=pin)


def tier(axis, r, th, rng, sides=10, droop=0.28, notch=0.72, wobble=0.0, shift=None, arms=0.22, curl=0.08, bulge=0.18):
    """One conifer skirt of branch arms: a convex pad that swells out from the apex, then droops
    to jagged arm tips of uneven length (`arms`), whose ends turn up a little (`curl`); deep
    notches between arms; open underneath."""
    bm = bmesh.new()
    shift = shift if shift is not None else Vector((0, 0, 0))
    apex = bm.verts.new(axis + UP * th)
    inner = bm.verts.new(axis + UP * th * 0.3 + shift * 0.5)
    mid, rim = [], []
    a0 = rng.uniform(0, math.tau)
    off = rng.random() * 50
    n = sides * 2
    for k in range(n):
        a = a0 + (k + rng.uniform(-0.18, 0.18)) / n * math.tau
        tip = k % 2 == 0
        reach = (1.0 + rng.uniform(-arms, arms)) if tip else notch
        rr = r * reach * (1 + wobble * noise.noise(Vector((math.cos(a) * 1.5 + off, math.sin(a) * 1.5, 0))))
        dr = r * (droop if tip else droop * 0.4)
        d = Vector((math.cos(a), math.sin(a), 0))
        end = axis + shift + d * rr + UP * (-dr + (r * curl if tip else 0.0))
        # The pad bulges above the straight line from apex to rim, so each tier reads as a shelf.
        m = axis + UP * th + (end - axis - UP * th) * 0.55 + UP * (th * bulge + (0.0 if tip else -th * 0.12))
        mid.append(bm.verts.new(m))
        rim.append(bm.verts.new(end))
    for k in range(n):
        j = (k + 1) % n
        bm.faces.new((apex, mid[k], mid[j]))
        bm.faces.new((mid[k], rim[k], rim[j], mid[j]))
        bm.faces.new((inner, rim[j], rim[k]))
    return bm


def needle_col(stops, rng, lo_z, hi_z, t):
    def col(co, n):
        tz = (co.z - lo_z) / max(hi_z - lo_z, 1e-3)
        return jitter(ramp(stops, 0.35 * tz + 0.35 * t + 0.3 * max(0, n.z)), rng, 0.04)
    return col


def conifer_crown(b, mat, rng, stops, h, lo, top, rmax, tiers, sides=10, droop=0.28, notch=0.72, lean=None,
                  profile=1.0, skip=0.0, wobble=0.12, sway=0.0, flat_top=False, at=None, arms=0.22, curl=0.08, overlap=1.6):
    """Stacked skirts from `lo` to `top`, widest at the bottom (`profile` shapes the taper), each
    nudged sideways by up to `sway` × its radius so the cone isn't a lathe. `overlap` is each
    skirt's height in tier spacings: below about 1.7 the dark underside of each shelf shows."""
    lean = lean if lean is not None else Vector((0, 0, 0))
    foot = Vector((at.x, at.y, 0)) if at is not None else Vector((0, 0, 0))
    th = (top - lo) / tiers * overlap
    for i in range(tiers):
        t = i / max(tiers - 1, 1)
        if 0 < i < tiers - 2 and rng.random() < skip:
            continue
        z = lo + (top - lo) * t
        axis = foot + Vector((0, 0, z)) + lean * (z / h) ** 2
        r = rmax * ((1 - t * 0.82) ** profile if not flat_top else 1 - 0.5 * t ** 2.5) * rng.uniform(0.88, 1.12)
        shift = heading(rng) * r * rng.uniform(0, sway)
        b.add(tier(axis, r, th, rng, sides, droop, notch, wobble, shift, arms, curl), mat, needle_col(stops, rng, z - r * 0.3, z + th, t), axis + UP * th * 0.2, flat=0.2)
    if not flat_top:
        tip = foot + Vector((0, 0, top)) + lean * (top / h) ** 2
        b.add(tube([tip, foot + Vector((0, 0, h)) + lean], [rmax * 0.12, 0], 6, cap=False), mat, lambda co, n: jitter(stops[2], rng, 0.04), tip - UP * h * 0.05, flat=0.3)


def broadleaf(rng, st):
    """A broadleaf in one of several growth forms (round, tall oval, forked, one-sided, two-layered),
    sometimes leaning. Forest trees carry their crowns high on long trunks; open-grown meadow trees
    keep broad crowns."""
    p = st["tree"]
    b = Builder()
    wood = material("Tree")
    stops = leaf_stops(st, rng)
    h = rng.uniform(*p["h"])
    form = rng.choices(["round", "oval", "fork", "onesided", "layered"], weights=p["forms"])[0]
    lo = h * p["base"] * rng.uniform(0.88, 1.12)
    rx = h * p["width"] * rng.uniform(0.85, 1.15) * dict(oval=0.75, layered=1.1, fork=1.05).get(form, 1.0)
    rz = (h - lo) / 2
    way = heading(rng)
    leaning = rng.random() < p.get("lean", 0.12)
    shift = way * (h * rng.uniform(0.12, 0.2) if leaning else h * rng.uniform(0, 0.04))
    if form == "onesided":
        shift += way * rx * rng.uniform(0.25, 0.4)
    centre = Vector((0, 0, lo + rz)) + shift
    r0 = h * p.get("girth", 0.03) * rng.uniform(0.85, 1.2)
    bark_col = bark_colour(jitter(st["bark"], rng, 0.1), rng)
    col = crown_colour(st, rng, lo, h, centre, rx, rz, stops=stops)
    crown = Crown(centre, col)

    if form == "fork":
        # The trunk splits below the crown into two or three leaders, each with its own sub-crown.
        fz = lo - h * rng.uniform(0.04, 0.14)
        pts = stem(fz, rng, 4, lean=shift * (fz / centre.z), lean_pow=0.8 if leaning else 2.0)
        radii = taper(r0, len(pts), top=0.75, flare=0.45)
        b.add(tube(pts, radii, 8), wood, bark_col, smooth=True)
        roots(b, wood, bark_col, r0, rng.randint(3, 5), rng)
        n = rng.choice([2, 2, 3])
        a0 = rng.uniform(0, math.tau)
        for k in range(n):
            out = direction(a0 + k / n * math.tau + rng.uniform(-0.3, 0.3))
            top_z = h - rz * rng.uniform(0.55, 0.95)
            c = Vector((shift.x, shift.y, top_z)) + out * rx * rng.uniform(0.35, 0.55)
            lead = curve(pts[-1], c, UP * 0.4 - out * rx * 0.15, 3)
            b.add(tube(lead, [radii[-1] * 0.8, r0 * 0.5, r0 * 0.38, r0 * 0.25], 6), wood, bark_col, smooth=True)
            cr = rx * rng.uniform(0.55, 0.66)
            crown.cluster(rng, c, cr, sats=1, squash=0.85)
            low = lead[1].lerp(lead[2], 0.5)
            side = (out + heading(rng) * 0.6).normalized()
            e = low + side * rx * rng.uniform(0.4, 0.6) + UP * rz * 0.15
            limb(b, wood, bark_col, low, e, r0 * 0.3, r0 * 0.12)
            crown.cluster(rng, e, cr * 0.62, sats=0, squash=0.8)
    else:
        top_z = centre.z + rz * (0.1 if form != "oval" else 0.4)
        pts = stem(top_z, rng, 6, lean=Vector((shift.x, shift.y, 0)), lean_pow=0.75 if leaning else 2.0,
                   bow=h * rng.uniform(0.0, 0.03))
        radii = taper(r0, len(pts), top=0.4, flare=0.45)
        b.add(tube(pts, radii, 8), wood, bark_col, smooth=True)
        roots(b, wood, bark_col, r0, rng.randint(3, 5), rng)
        spots = []  # (centre, radius, squash)
        if form in ("round", "onesided"):
            # A few big lobes round a small core: one mass whose rim has deep notches.
            n = rng.randint(4, 5)
            phase = rng.uniform(0, math.tau)
            for i in range(n):
                y = 0.85 - (i + 0.5) / n * 1.3
                r = math.sqrt(max(0.0, 1 - y * y))
                a = i * 2.39996 + phase
                d = direction(a)
                if form == "onesided" and d.dot(way) < -0.3:
                    d = (d + way * 1.2).normalized()  # crowded on one side: limbs reach to the light
                c = centre + d * r * rx * 0.55 + UP * y * rz * 0.5
                spots.append((c, min(rx, rz) * rng.uniform(0.62, 0.74), 0.85))
            core = (centre + UP * rz * 0.05, min(rx, rz) * 0.72, rz / max(rx, rz) * 1.0)
        elif form == "oval":
            n = rng.randint(4, 5)
            phase = rng.uniform(0, math.tau)
            for i in range(n):
                u = (i + 0.5) / n
                z = lo + rz * 0.35 + (h - lo - rz * 0.6) * u
                c = Vector((shift.x, shift.y, z)) + direction(phase + i * 2.39996) * rx * 0.42 * math.sin(math.pi * (0.15 + 0.85 * u))
                spots.append((c, rx * rng.uniform(0.66, 0.78), 0.95))
            core = (centre + UP * rz * 0.15, rx * 0.72, rz / rx * 0.9)
        else:  # layered: a wide low tier and a small top, with a gap you can see through
            n = rng.randint(4, 5)
            phase = rng.uniform(0, math.tau)
            for i in range(n):
                c = Vector((shift.x, shift.y, lo + rz * 0.45)) + direction(phase + i / n * math.tau + rng.uniform(-0.3, 0.3)) * rx * rng.uniform(0.6, 0.8)
                spots.append((c, rx * rng.uniform(0.42, 0.5), 0.6))
            for i in range(2):
                c = Vector((pts[-1].x, pts[-1].y, h - rz * 0.5)) + direction(phase + 1 + i * math.pi) * rx * 0.25
                spots.append((c, rx * rng.uniform(0.4, 0.48), 0.8))
            core = None
        for j, (c, cr, sq) in enumerate(spots):
            t = at_height(pts, min(c.z - cr * 0.6, pts[-1].z))
            start = along(pts, max(0.55, t))
            if (c - start).length > cr * 0.6:
                limb(b, wood, bark_col, start, c, along_r(radii, t) * 0.55, r0 * 0.15)
            crown.cluster(rng, c, cr, sats=1 if j % 2 == 0 else 0, squash=sq)
        if core:
            crown.lobe(core[0], core[1], core[2], sub=2)
    # Side lobes: a limb leaves the trunk below the crown and carries its own small clump.
    for _ in range(rng.randint(*p.get("lobes", (0, 0)))):
        out = heading(rng)
        z = lo - rz * rng.uniform(0.1, 0.45)
        t = at_height(pts, z)
        start = along(pts, t)
        c = start + out * rx * rng.uniform(0.6, 0.75) + UP * rz * 0.7
        lr = min(rx, rz) * rng.uniform(0.5, 0.6)
        limb(b, wood, bark_col, start, c, along_r(radii, t) * 0.5, r0 * 0.18)
        crown.cluster(rng, c, lr, sats=1, squash=0.8)
    crown.build(b, wood, rng)
    return b


def oak(rng, st):
    """A broad old oak: a short, thick, flared trunk forking into heavy sinuous limbs under a wide,
    low, flat-topped crown wider than it is tall."""
    b = Builder()
    wood = material("Tree")
    stops = leaf_stops(st, rng, "oak")
    h = rng.uniform(15, 18)
    rx = h * rng.uniform(0.5, 0.62)
    lo = h * rng.uniform(0.24, 0.32)
    fork = lo + h * rng.uniform(0.0, 0.07)
    r0 = h * rng.uniform(0.05, 0.06)
    lean = heading(rng) * h * rng.uniform(0, 0.04)
    pts = stem(fork, rng, 4, lean=lean, wiggle=0.35)
    radii = taper(r0, len(pts), top=0.78, flare=0.6)
    bark_col = bark_colour(jitter(st.get("oak_bark", st["bark"]), rng, 0.1), rng, foot=0.65)
    b.add(tube(pts, radii, 9), wood, bark_col, smooth=True)
    roots(b, wood, bark_col, r0, rng.randint(5, 7), rng, reach=2.6)
    rz = (h - lo) / 2
    cz = lo + rz
    centre = Vector((lean.x, lean.y, cz))
    col = crown_colour(st, rng, lo, h, centre, rx, rz, stops=stops)
    crown = Crown(centre, col, pull=0.7)
    top = pts[-1]
    n = rng.randint(4, 5)
    a0 = rng.uniform(0, math.tau)
    for i in range(n):
        out = direction(a0 + i / n * math.tau + rng.uniform(-0.35, 0.35))
        reach = rx * rng.uniform(0.5, 0.78)
        ez = cz + rz * rng.uniform(-0.15, 0.35)
        e = top + out * reach
        e.z = ez
        # Heavy limbs rise steeply, then spread: the middle bows up and in.
        side = Vector((-out.y, out.x, 0)) * rng.uniform(-0.2, 0.2) * reach
        b.add(tube(curve(top, e, UP * reach * 0.15 - out * reach * 0.12 + side, 3),
                   [r0 * 0.5, r0 * 0.38, r0 * 0.27, r0 * 0.16], 6), wood, bark_col, smooth=True)
        cr = rx * rng.uniform(0.4, 0.48)
        crown.cluster(rng, e, cr, sats=1, squash=0.78)
        # A lower, outer branch droops towards the rim.
        if rng.random() < 0.75:
            s = top.lerp(e, rng.uniform(0.4, 0.6))
            o2 = (out + Vector((-out.y, out.x, 0)) * rng.choice([-0.7, 0.7])).normalized()
            e2 = s + o2 * reach * rng.uniform(0.6, 0.85)
            e2.z = cz - rz * rng.uniform(0.3, 0.6)
            limb(b, wood, bark_col, s, e2, r0 * 0.2, r0 * 0.09, arch=0.12)
            crown.cluster(rng, e2, cr * rng.uniform(0.62, 0.75), sats=0, squash=0.8)
    crown.lobe(Vector((lean.x, lean.y, h - rz * 0.6)), rx * 0.5, 0.65)
    crown.lobe(centre + UP * rz * 0.05, rx * 0.62, rz / rx * 1.15)
    crown.build(b, wood, rng)
    return b


def birch_bark(st, rng, h):
    """Pale bark with dark marks, dark and fissured at the foot; coloured per face so the marks stay
    crisp under the toon bands."""
    pale = jitter(st.get("birch_bark", (0.78, 0.76, 0.7)), rng, 0.06)
    dark, foot = (0.05, 0.045, 0.04), (0.12, 0.11, 0.1)
    off = Vector((rng.random() * 40, rng.random() * 40, rng.random() * 40))
    foot_h = h * rng.uniform(0.04, 0.09)

    def f(co, n):
        if co.z < foot_h * (1 + 0.5 * noise.noise(co * 2 + off)):
            return jitter(foot, rng, 0.1)
        m = noise.noise(Vector((co.x * 4, co.y * 4, co.z * 2.2)) + off)
        return jitter(dark if m > 0.22 else pale, rng, 0.05)
    return f


def birch(rng, st):
    """A tall, slender birch: pale marked bark, a light, loose and narrow crown of small hanging
    clusters you can see the trunk through; sometimes twin-stemmed, sometimes leaning."""
    b = Builder()
    wood = material("Tree")
    stops = leaf_stops(st, rng, "birch")
    h = rng.uniform(10, 13)
    rx = h * rng.uniform(0.15, 0.2)
    stems = 2 if rng.random() < 0.3 else 1
    way = heading(rng)
    leaning = rng.random() < 0.2
    for s in range(stems):
        hs = h if s == 0 else h * rng.uniform(0.75, 0.9)
        d = way if s == 0 else (-way + heading(rng) * 0.5).normalized()
        lean = d * hs * (rng.uniform(0.1, 0.17) if leaning and s == 0 else rng.uniform(0.02, 0.07 if s else 0.04))
        base = Vector((0, 0, -SINK)) + (d * 0.18 if stems > 1 else Vector((0, 0, 0)))
        r0 = h * rng.uniform(0.014, 0.018) * (1 if s == 0 else 0.8)
        pts = stem(hs, rng, 12, base=base, lean=lean, lean_pow=0.8 if leaning and s == 0 else 1.6,
                   bow=hs * rng.uniform(0.01, 0.035), wiggle=0.18)
        radii = taper(r0, len(pts), top=0.22, flare=0.35)
        b.add(tube(pts, radii, 6), wood, birch_bark(st, rng, h), smooth=True, per_face=True)
        lo = hs * rng.uniform(0.4, 0.52)
        centre = along(pts, 0.5 + 0.5 * at_height(pts, lo))
        rz = (hs - lo) / 2
        col = crown_colour(st, rng, lo, hs, centre, rx, rz, stops=stops)
        crown = Crown(centre, col, pull=0.65, jag=0.45, tip=0.28, droop=0.8)
        n = rng.randint(6, 8) if stems == 1 else rng.randint(4, 5)
        phase = rng.uniform(0, math.tau)
        for i in range(n):
            u = (i + 0.5) / n
            t = at_height(pts, lo + (hs - lo) * u * 0.92)
            start = along(pts, t)
            out = direction(phase + i * 2.39996)
            reach = rx * (0.22 + 0.35 * math.sin(math.pi * (0.2 + 0.7 * u))) * rng.uniform(0.8, 1.1)
            e = start + out * reach + UP * rng.uniform(-0.2, 0.5)
            limb(b, wood, birch_bark(st, rng, h), start, e, along_r(radii, t) * 0.5, 0.02, arch=0.3, sides=4)
            cr = rx * rng.uniform(0.5, 0.62) * (1.15 - 0.4 * u)
            # Hanging twigs: clusters a little taller than wide, just below their limb's tip.
            crown.cluster(rng, e - UP * cr * 0.3, cr, sats=1 if i % 2 else 0, squash=1.15, sub=2 if cr > 0.9 else 1, rough=0.24)
        crown.cluster(rng, pts[-1] - UP * rx * 0.15, rx * 0.32, sats=1, squash=1.2, sub=1, rough=0.24)
        crown.lobe(centre, rx * 0.55, rz / rx * 0.55, sub=2)
        crown.build(b, wood, rng)
    return b


def pine(rng, st):
    """A pine on a warm upper trunk: either a cone of jagged, drooping skirts (forest pines lose
    their lower tiers, as in a stand; some have a flat old top or a missing tier), or an old
    Scots pine whose crooked upper limbs carry flat, layered pads of needles."""
    b = Builder()
    wood = material("Tree")
    stops = leaf_stops(st, rng, "needle")
    h = rng.uniform(12, 16)
    lean = heading(rng) * h * rng.uniform(0, 0.035)
    r0 = h * rng.uniform(0.02, 0.027)
    warm = st.get("pine_bark", st["bark"])
    bark_col = lambda co, n: jitter(lerp(scale(st["bark"], 0.7), warm, min(1, max(0.0, co.z - 2) / (h * 0.5))), rng, 0.05)
    if rng.random() < 0.45:
        return scots_pine(b, wood, rng, st, stops, h, lean, r0, bark_col)
    pts = stem(h * 0.9, rng, 5, lean=lean, bow=h * rng.uniform(0, 0.02))
    b.add(tube(pts, taper(r0, len(pts), top=0.3, flare=0.3), 7), wood, bark_col, smooth=True)
    roots(b, wood, bark_col, r0, 3, rng, reach=2.6)
    old = rng.random() < 0.2
    conifer_crown(b, wood, rng, stops, h, h * rng.uniform(0.28, 0.48), h * 0.86, h * rng.uniform(0.15, 0.21), rng.randint(5, 7),
                  lean=lean, skip=0.08, sway=0.18, wobble=0.15, flat_top=old, profile=rng.uniform(0.8, 1.2),
                  notch=0.55, arms=0.28, curl=0.1, overlap=1.5)
    return b


def scots_pine(b, wood, rng, st, stops, h, lean, r0, bark_col):
    """An old Scots pine: a tall bare trunk that kinks near the top into a few crooked limbs, each
    holding a flat cloud of needles; pads overlap in layers, lit on top and dark beneath."""
    top = h * rng.uniform(0.78, 0.86)
    r0 *= 1.25
    pts = stem(top, rng, 6, lean=lean * 1.5, lean_pow=2.5, bow=h * rng.uniform(0.02, 0.05), wiggle=0.35)
    radii = taper(r0, len(pts), top=0.4, flare=0.3)
    b.add(tube(pts, radii, 7), wood, bark_col, smooth=True)
    roots(b, wood, bark_col, r0, 3, rng, reach=2.4)
    lo = h * rng.uniform(0.58, 0.66)
    span = h * rng.uniform(0.2, 0.26)

    def col(co, n):
        tz = (co.z - lo) / max(h - lo, 1e-3)
        return jitter(ramp(stops, 0.25 + 0.45 * tz + 0.3 * max(0.0, n.z)), rng, 0.04)
    crown = Crown(Vector((pts[-1].x, pts[-1].y, (lo + h) / 2)), col, jag=0.4, tip=0.22, droop=0.25)
    n = rng.randint(5, 7)
    a0 = rng.uniform(0, math.tau)
    for i in range(n):
        u = i / max(n - 1, 1)
        z = lo + (h - lo) * (0.1 + 0.62 * u) + rng.uniform(-0.3, 0.3)
        t = at_height(pts, min(z - 1.0, top))
        s = along(pts, t)
        out = direction(a0 + i * 2.39996 + rng.uniform(-0.3, 0.3))
        reach = span * (0.8 - 0.4 * u) * rng.uniform(0.75, 1.15)
        c = Vector((s.x, s.y, z)) + out * reach
        # A crooked limb: up, then out.
        limb(b, wood, bark_col, s, c - UP * 0.3, along_r(radii, t) * 0.6, r0 * 0.18, arch=0.35, sides=5)
        r = span * rng.uniform(0.5, 0.65) * (1.05 - 0.35 * u)
        crown.lobe(c, r, rng.uniform(0.45, 0.55), rough=0.22, nc=c - UP * r * 0.7)
        if rng.random() < 0.7:
            c2 = c + heading(rng) * r * 0.55 - UP * r * 0.12
            crown.lobe(c2, r * 0.65, 0.5, rough=0.22, sub=1, nc=c2 - UP * r * 0.5)
    tp = Vector((pts[-1].x, pts[-1].y, h - span * 0.2))
    crown.lobe(tp, span * 0.4, 0.55, rough=0.2, nc=tp - UP * span * 0.3)
    crown.build(b, wood, rng)
    return b


def spruce(rng, st):
    """A tall, narrow spruce: a dark blue-green spire of many small drooping tiers almost to the
    ground, with a few dead twigs below them."""
    b = Builder()
    wood = material("Tree")
    stops = leaf_stops(st, rng, "spruce")
    h = rng.uniform(16, 20)
    lean = heading(rng) * h * rng.uniform(0, 0.02)
    r0 = h * rng.uniform(0.017, 0.021)
    pts = stem(h * 0.92, rng, 5, lean=lean, wiggle=0.1)
    bark_col = bark_colour(jitter(st["bark"], rng, 0.1), rng)
    b.add(tube(pts, taper(r0, len(pts), top=0.25, flare=0.3), 6), wood, bark_col, smooth=True)
    lo = h * rng.uniform(0.04, 0.17)
    for _ in range(rng.randint(2, 5)):
        z = rng.uniform(0.6, max(0.8, lo))
        s = along(pts, at_height(pts, z))
        e = s + heading(rng) * rng.uniform(0.4, 1.0) + UP * rng.uniform(-0.2, 0.1)
        b.add(tube([s, e], [r0 * 0.15, 0.0], 3, cap=False), wood, solid(scale(st["bark"], 1.4), rng))
    conifer_crown(b, wood, rng, stops, h, lo, h * 0.9, h * rng.uniform(0.14, 0.17), rng.randint(10, 13), sides=8,
                  droop=0.5, notch=0.5, lean=lean, skip=0.08, sway=0.14, wobble=0.18, profile=rng.uniform(0.85, 1.15),
                  arms=0.3, curl=0.14, overlap=1.55)
    return b


def coppice(rng, st):
    """A multi-stemmed coppice (hazel, alder): several stems fan out of one old stool, each
    with its own leafy top, so the whole reads as a vase."""
    b = Builder()
    wood = material("Tree")
    stops = leaf_stops(st, rng)
    h = rng.uniform(6.5, 8)
    n = rng.randint(3, 6)
    bark_col = bark_colour(jitter(st["bark"], rng, 0.1), rng, foot=0.6)
    stool = blob(Vector((0, 0, -0.05)), 0.4, rng, subdiv=2, squash=0.5, roughness=0.3)
    b.add(stool, wood, bark_col, smooth=True)
    centre = Vector((0, 0, h * 0.7))
    rx = h * 0.4
    col = crown_colour(st, rng, h * 0.3, h, centre, rx, h * 0.35, stops=stops)
    crown = Crown(centre, col, pull=0.55)
    a0 = rng.uniform(0, math.tau)
    for i in range(n):
        out = direction(a0 + i / n * math.tau + rng.uniform(-0.4, 0.4))
        hs = h * (0.95 if i == 0 else rng.uniform(0.65, 0.92))
        cr = h * rng.uniform(0.15, 0.19)
        base = out * rng.uniform(0.08, 0.25) + UP * -SINK
        reach = hs * rng.uniform(0.08, 0.2)
        top = base + out * reach + UP * (hs - cr * 0.6 + SINK)
        pts = curve(base, top, out * reach * 0.35 + UP * 0.2, 5)
        r = h * rng.uniform(0.011, 0.015)
        radii = [r * (1.2 - 0.85 * k / 5) for k in range(6)]
        b.add(tube(pts, radii, 5), wood, bark_col, smooth=True)
        # Leaves along the upper part of each stem, not only at its tip.
        crown.cluster(rng, top, cr * 1.1, sats=1 if i % 2 == 0 else 0, squash=0.95, sub=2 if i < 3 else 1)
        s = along(pts, rng.uniform(0.6, 0.72))
        crown.lobe(s + out * cr * 0.5, cr * rng.uniform(0.7, 0.85), 1.0, sub=1)
    crown.lobe(centre - UP * h * 0.05, h * 0.2, 1.1, sub=1)
    crown.build(b, wood, rng)
    return b


def young_conifer(b, wood, rng, st, h, at=None, bark=None, sides=8):
    at = at if at is not None else Vector((0, 0, 0))
    stops = leaf_stops(st, rng, "needle")
    lean = heading(rng) * h * rng.uniform(0, 0.04)
    pts = stem(h * 0.85, rng, 3, base=at + UP * -SINK * min(1.0, h / 5), lean=lean, wiggle=0.05)
    b.add(tube(pts, taper(h * 0.022, len(pts), top=0.3, flare=0.2), 5), wood, bark or bark_colour(st["bark"], rng), smooth=True)
    conifer_crown(b, wood, rng, stops, h, h * rng.uniform(0.04, 0.12), h * 0.86, h * rng.uniform(0.18, 0.24),
                  rng.randint(4, 6), sides=sides, droop=0.36, notch=0.55, lean=lean, sway=0.14, wobble=0.12, at=at,
                  arms=0.3, curl=0.12, overlap=1.5)


def young(rng, st):
    """A young tree (pole stage): a slender stem and a small, loose crown starting low, or a narrow
    young conifer; sometimes leaning."""
    b = Builder()
    wood = material("Tree")
    h = rng.uniform(4.5, 6)
    if rng.random() < st.get("young_conifer", 0.35):
        young_conifer(b, wood, rng, st, h)
        return b
    stops = leaf_stops(st, rng, rng.choice(["leaf", "leaf", "birch"]))
    leaning = rng.random() < 0.18
    lean = heading(rng) * h * (rng.uniform(0.1, 0.18) if leaning else rng.uniform(0, 0.05))
    pts = stem(h * 0.92, rng, 5, lean=lean, lean_pow=0.8 if leaning else 1.6, bow=h * rng.uniform(0.01, 0.04), wiggle=0.12)
    r0 = h * rng.uniform(0.016, 0.02)
    radii = taper(r0, len(pts), top=0.25, flare=0.25)
    bark_col = bark_colour(jitter(st["bark"], rng, 0.1), rng)
    b.add(tube(pts, radii, 5), wood, bark_col, smooth=True)
    lo = h * rng.uniform(0.2, 0.28)
    rx = h * rng.uniform(0.18, 0.23)
    rz = (h - lo) / 2
    centre = along(pts, 0.5 + 0.5 * at_height(pts, lo))
    col = crown_colour(st, rng, lo, h, centre, rx, rz, stops=stops)
    crown = Crown(centre, col, pull=0.75, jag=0.45, tip=0.28)
    # Not a ball on a stick: a tall, uneven crown that starts low on the stem, built from lobes
    # that sit on alternate sides up the stem round a slim core, with a leader at the top and a
    # low branch or two standing out, so the outline is long and lumpy and the stem shows below.
    side = heading(rng)
    crown.lobe(centre + side * rx * 0.15, rx * 0.62, rz / rx * 0.62, sub=2)
    n = rng.randint(4, 5)
    phase = rng.uniform(0, math.tau)
    for i in range(n):
        u = (i + 0.5) / n
        t = at_height(pts, lo + (h - lo) * (0.08 + 0.78 * u))
        s = along(pts, t)
        out = direction(phase + i * 2.39996 + rng.uniform(-0.3, 0.3))
        reach = rx * (0.7 - 0.35 * u) * rng.uniform(0.85, 1.15)
        e = s + out * reach + UP * reach * rng.uniform(0.2, 0.5)
        if reach > rx * 0.45:
            limb(b, wood, bark_col, s - UP * reach * 0.3, e, along_r(radii, t) * 0.6, r0 * 0.15, arch=0.2, sides=4)
        crown.lobe(e, rx * rng.uniform(0.5, 0.62) * (1.1 - 0.3 * u), rng.uniform(0.95, 1.2), sub=2 if i < 2 else 1)
    crown.lobe(pts[-1] - UP * rx * 0.3, rx * rng.uniform(0.38, 0.46), 1.4, sub=1)
    if rng.random() < 0.7:
        # A low branch with its own tuft, below the crown.
        t = at_height(pts, lo * rng.uniform(0.75, 0.95))
        s = along(pts, t)
        out = (-side + heading(rng) * 0.5).normalized()
        e = s + out * rx * rng.uniform(0.8, 1.0) + UP * rx * 0.4
        limb(b, wood, bark_col, s, e, along_r(radii, t) * 0.5, r0 * 0.12, arch=0.25, sides=4)
        crown.lobe(e, rx * rng.uniform(0.32, 0.4), 0.85, sub=1)
    crown.build(b, wood, rng)
    return b


def sapling(rng, st):
    """Saplings, 1–1.6 m: one to three stems of a regenerating patch, broadleaf or conifer."""
    if st is STYLES["spirit"]:
        return spirit_sapling(rng, st)
    b = Builder()
    wood = material("Tree")
    conifer = rng.random() < st.get("young_conifer", 0.35)
    stops = leaf_stops(st, rng, rng.choice(["leaf", "birch"]))
    bark_col = bark_colour(st["bark"], rng, rise=0.8)
    stems = rng.choice([1, 1, 2, 3])
    for s in range(stems):
        h = rng.uniform(1.3, 1.6) if s == 0 else rng.uniform(0.5, 1.0)
        at = Vector((0, 0, 0)) if s == 0 else heading(rng) * rng.uniform(0.35, 0.7)
        if conifer:
            young_conifer(b, wood, rng, st, h, at, bark_col, sides=5)
            continue
        lean = heading(rng) * h * rng.uniform(0.02, 0.12)
        pts = stem(h * 0.9, rng, 3, base=at + UP * -SINK * 0.3, lean=lean, bow=h * 0.05, wiggle=0.04)
        b.add(tube(pts, [0.022 * h, 0.016 * h, 0.011 * h, 0.006 * h], 4, cap=False), wood, bark_col, smooth=True)
        centre = along(pts, 0.7)
        col = crown_colour(st, rng, h * 0.3, h, centre, h * 0.25, h * 0.3, stops=stops)
        crown = Crown(centre, col, pull=0.4, jag=0.55, tip=0.38, droop=0.6)
        # Leafy sprigs up the stem on alternate sides and a tuft at the top: a small, uneven spire
        # with the stem showing between its leaves, not a ball.
        k = rng.randint(3, 4) if s == 0 else 2
        a0 = rng.uniform(0, math.tau)
        for i in range(k):
            u = (i + 0.5) / k
            q = along(pts, 0.35 + 0.5 * u)
            out = direction(a0 + i * math.pi * rng.uniform(0.8, 1.2))
            r = h * rng.uniform(0.12, 0.16) * (1.15 - 0.4 * u)
            crown.lobe(q + out * r * 0.9 + UP * r * 0.3, r, rng.uniform(0.8, 1.1), rough=0.25, sub=1)
        crown.lobe(pts[-1] - UP * h * 0.05, h * 0.09, 1.4, rough=0.25, sub=1)
        crown.build(b, wood, rng)
    return b


def snag(rng, st):
    """A dead standing tree: broken, splintered top, a few bare stubs, bark falling away to pale
    wood, a bracket fungus or two; often leaning."""
    b = Builder()
    wood = material("Tree")
    h = rng.uniform(5, 8)
    r0 = h * rng.uniform(0.04, 0.06)
    leaning = rng.random() < 0.35
    lean = heading(rng) * h * (rng.uniform(0.08, 0.16) if leaning else rng.uniform(0, 0.04))
    pts = stem(h * 0.93, rng, 6, lean=lean, lean_pow=0.9 if leaning else 1.6, bow=h * rng.uniform(0, 0.03), wiggle=0.3)
    radii = taper(r0, len(pts), top=rng.uniform(0.45, 0.65), flare=0.45)
    bark = jitter(st.get("snag_bark", (0.07, 0.062, 0.055)), rng, 0.08)
    bare = jitter((0.3, 0.27, 0.22), rng, 0.06)
    off = Vector((rng.random() * 40, rng.random() * 40, 0))
    loss = rng.uniform(0.0, 0.3)
    moss = st["moss"]

    def col(co, n):
        if co.z > h * 0.85 and n.z > 0.5:
            return jitter((0.55, 0.43, 0.28), rng, 0.05)  # broken fresh-ish wood on top
        c = bare if noise.noise(Vector((co.x * 2.5, co.y * 2.5, co.z * 0.9)) + off) > 0.42 - loss else bark
        if co.z < 0.7:
            c = lerp(c, moss, 0.5 * (1 - co.z / 0.7))
        return jitter(c, rng, 0.06)
    b.add(tube(pts, radii, 7), wood, col, per_face=True)
    roots(b, wood, lambda co, n: jitter(lerp(bark, moss, 0.4), rng, 0.06), r0, rng.randint(3, 4), rng, reach=2.4)
    # Splinters up from the broken top.
    top, rt = pts[-1], radii[-1]
    a0 = rng.uniform(0, math.tau)
    for k in range(rng.randint(2, 4)):
        a = a0 + k * 2.1
        s = top + direction(a) * rt * 0.55 - UP * rt * 0.2
        e = s + direction(a) * rt * 0.3 + UP * rng.uniform(0.25, 1.1) + lean.normalized() * 0.1
        b.add(tube([s, e], [rt * 0.38, 0.0], 3, cap=False), wood, solid(bare, rng))
    # Bare branch stubs, a few still forked.
    for _ in range(rng.randint(2, 5)):
        t = rng.uniform(0.35, 0.88)
        s = along(pts, t)
        out = heading(rng)
        length = rng.uniform(0.3, 1.9)
        e = s + out * length + UP * length * rng.uniform(0.2, 0.8)
        b.add(tube([s, e], [along_r(radii, t) * 0.32, 0.015], 4, cap=False), wood, solid(bare if rng.random() < 0.5 else bark, rng))
        if length > 1.2 and rng.random() < 0.6:
            m = s.lerp(e, 0.6)
            b.add(tube([m, m + (out + heading(rng)).normalized() * length * 0.4 + UP * 0.3], [along_r(radii, t) * 0.12, 0.0], 3, cap=False), wood, solid(bare, rng))
    # Bracket fungi on the trunk.
    shelf = rng.choice([(0.85, 0.72, 0.5), (0.8, 0.45, 0.12), (0.7, 0.66, 0.6)])
    for _ in range(rng.randint(0, 3)):
        t = rng.uniform(0.15, 0.6)
        out = heading(rng)
        c = along(pts, t) + out * along_r(radii, t) * 0.95
        f = blob(c, along_r(radii, t) * rng.uniform(0.6, 0.9), rng, subdiv=1, squash=0.28, roughness=0.1)
        b.add(f, wood, lambda co, n: jitter(lerp(scale(shelf, 0.6), shelf, max(0, n.z)), rng, 0.05), c - UP * 0.3, flat=0.2)
    return b


def glow_choice(st, rng):
    """A spirit tree's glow and lantern colours: mostly the style's teal, sometimes blue or violet."""
    g = rng.choices(st.get("glows", [st["glow"]]), weights=st.get("glow_weights", None))[0]
    return g, rng.choice(st.get("fruits", [st["fruit"]]))


def spirit_tree(rng, st):
    """A dark spirit tree that reads at night: gnarled trunk and a crown in silhouette (a wide
    umbrella, a weeping dome, two tiers or twin twisted stems), with glowing vines hanging from the
    crown, lantern fruit on their ends, glowing leaf tips and bioluminescent lines up the bark."""
    p = st["tree"]
    b = Builder()
    wood = material("Tree")
    hue, fruit_c = glow_choice(st, rng)
    vine = glow("Glow", hue, 3.0)
    fruit = glow("GlowFruit", fruit_c, 5.0)
    tips = glow("GlowLeaf", hue, 2.0)
    form = rng.choices(["umbrella", "weeping", "tiered", "twisted"], weights=(3, 2, 2, 2))[0]
    h = rng.uniform(*p["h"])
    rx = h * p["width"] * rng.uniform(0.9, 1.15) * dict(weeping=0.85, tiered=0.9).get(form, 1.0)
    rz = h * 0.22
    lean = heading(rng) * h * rng.uniform(0, 0.08)
    cz = h - rz * 1.1 if form != "tiered" else h * 0.6
    centre = Vector((0, 0, cz)) + lean
    r0 = h * 0.045 * rng.uniform(0.85, 1.15)
    stops = leaf_stops(st, rng)
    bark_col = lambda co, n: jitter(lerp(scale(st["bark"], 0.6), st["bark"], min(1, co.z / 4)), rng, 0.06)
    sway = rng.uniform(0.5, 1.0) * h * 0.06
    stems = 2 if form == "twisted" else 1
    trunks = []
    for s in range(stems):
        ph = rng.uniform(0, math.tau) if s == 0 else trunks[0][2] + math.pi
        top = (cz - rz * 0.3) if form != "tiered" else h - rz * 0.9
        pts = []
        for i in range(8):
            t = i / 7
            if form == "twisted":
                twist = Vector((math.cos(t * 5 + ph), math.sin(t * 5 + ph), 0)) * r0 * 0.9 * (1 - t * 0.6)
            else:
                twist = Vector((math.sin(t * 3.4 + ph) * sway * t, math.cos(t * 2.7 + ph) * sway * t, 0))
            pts.append(twist + Vector((0, 0, -SINK + (top + SINK) * t)) + lean * t * t)
        k = 0.7 if form == "twisted" else 1.0
        radii = [r0 * k * (1.5 - 0.8 * t) for t in (i / 7 for i in range(8))]
        b.add(tube(pts, radii, 8 if stems == 1 else 6), wood, bark_col, smooth=True)
        trunks.append((pts, radii, ph))
    pts, radii, _ = trunks[0]
    roots(b, wood, bark_col, r0, rng.randint(4, 6), rng, reach=4.0)
    lines = glow("GlowLine", hue, 2.5)
    for s in range(2):
        tp, tr, _ = trunks[s % stems]
        a0 = rng.uniform(0, math.tau) + s * math.pi
        line = []
        for i in range(14):
            t = i / 13
            c = along(tp, t * 0.92)
            rr = along_r(tr, t * 0.92) * 1.06
            a = a0 + t * rng.uniform(2.0, 3.5)
            line.append(c + direction(a) * rr)
        b.add(tube(line, [0.035] * len(line), 3), lines, solid(scale(hue, 0.8), rng, 0.0))

    def crown(c0, rx, rz, n, droop, from_pt):
        col = crown_colour(st, rng, c0.z - rz * (1 + droop), c0.z + rz, c0, rx, rz, stops=stops)
        mass = Crown(c0, col, pull=0.6, jag=0.35, tip=0.24, droop=0.7 if droop else 0.45)
        phase = rng.uniform(0, math.tau)
        out = []
        for i in range(n):
            a = phase + i / n * math.tau + rng.uniform(-0.25, 0.25)
            r = rx * rng.uniform(0.55, 0.75)
            c = c0 + direction(a) * r + UP * (rng.uniform(-0.3, 0.2) - droop * r / rx) * rz
            cr = rx * rng.uniform(0.32, 0.42)
            b.add(tube(curve(from_pt, c, UP * rz * 0.5, 3), [r0 * 0.6, r0 * 0.45, r0 * 0.3, r0 * 0.15], 5), wood, bark_col, smooth=True)
            mass.lobe(c, cr * 1.08, 0.6 if not droop else 0.8, sub=2 if i % 2 == 0 else 1)
            out.append((c, cr))
        mass.lobe(c0 + UP * rz * 0.3, rx * 0.62, 0.45 if not droop else 0.6, sub=2)
        mass.build(b, wood, rng)
        return out

    droop = 0.9 if form == "weeping" else 0.0
    n = rng.randint(*p["clumps"])
    if form == "tiered":
        clumps = crown(centre, rx, rz, n - 2, 0.0, along(pts, 0.75))
        c2 = Vector((pts[-1].x, pts[-1].y, h - rz * 0.8))
        clumps += crown(c2, rx * 0.55, rz * 0.7, 4, 0.0, pts[-2])
    else:
        clumps = crown(centre, rx, rz, n, droop, pts[-2])
    for c, cr in clumps:
        for _ in range(rng.randint(2, 4)):
            a = rng.uniform(0, math.tau)
            e = rng.uniform(-0.3 - droop * 0.4, 0.5)
            q = c + Vector((math.cos(a) * cr * 0.92 * math.cos(e), math.sin(a) * cr * 0.92 * math.cos(e), math.sin(e) * cr * 0.55))
            b.add(gem(q, cr * rng.uniform(0.1, 0.16)), tips, solid(scale(hue, 0.7), rng), q, flat=0.2)
    # Vines from the crown's underside, some ending in lantern fruit. Weeping trees hang longer
    # curtains, but every vine stays above head height (and the game camera's line to the player).
    floor = h * (0.42 if form == "weeping" else 0.55)
    for c, cr in clumps:
        for _ in range(rng.randint(2, 3) + (1 if form == "weeping" else 0)):
            a, d = rng.uniform(0, math.tau), rng.uniform(0.2, 0.85) * cr
            top = c + Vector((math.cos(a) * d, math.sin(a) * d, -cr * 0.35))
            length = rng.uniform(0.08, 0.2) * h * (1.6 if form == "weeping" else 1.0)
            end = top + Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), -length))
            end.z = max(end.z, floor)
            if top.z - end.z < 0.3:
                continue
            line = curve(top, end, Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), 0)), 4)
            b.add(tube(line, [0.05, 0.045, 0.04, 0.035, 0.03], 3, cap=False), vine, solid(scale(hue, 0.8), rng, 0.0))
            if rng.random() < 0.5:
                b.add(blob(end + UP * -0.08, rng.uniform(0.09, 0.15), rng, subdiv=1, roughness=0.05, squash=1.3), fruit, solid(fruit_c, rng, 0.0))
    return b


def spirit_giant(rng, st):
    """An ancient spirit tree, 20–30 m: a massive buttressed trunk wrapped by twisting stems, a
    glowing hollow at its foot, two wide umbrella tiers, and many vines and lanterns."""
    b = Builder()
    wood = material("Tree")
    hue, fruit_c = glow_choice(st, rng)
    vine = glow("Glow", hue, 3.0)
    fruit = glow("GlowFruit", fruit_c, 5.0)
    tips = glow("GlowLeaf", hue, 2.0)
    lines = glow("GlowLine", hue, 2.5)
    h = rng.uniform(22, 26)
    r0 = h * rng.uniform(0.05, 0.06)
    lean = heading(rng) * h * rng.uniform(0, 0.03)
    stops = leaf_stops(st, rng)
    bark_col = lambda co, n: jitter(lerp(scale(st["bark"], 0.55), scale(st["bark"], 1.15), min(1, co.z / 8)), rng, 0.06)
    top = h * 0.6
    pts = stem(top, rng, 8, lean=lean, bow=h * 0.03, wiggle=0.6)
    radii = taper(r0, len(pts), top=0.55, flare=0.7)
    b.add(tube(pts, radii, 10), wood, bark_col, smooth=True)
    # Buttress roots: tall where they meet the trunk, running far out.
    for k in range(rng.randint(6, 8)):
        out = direction(k / 7 * math.tau + rng.uniform(-0.25, 0.25))
        s = out * r0 * 0.4 + UP * r0 * rng.uniform(2.5, 4.0)
        e = out * r0 * rng.uniform(3.5, 5.0) + UP * -SINK * 0.7
        b.add(tube(curve(s, e, out * r0 * 0.8 - UP * r0 * 0.4, 3), [r0 * 0.5, r0 * 0.4, r0 * 0.22, r0 * 0.06], 5, cap=False), wood, bark_col, smooth=True)
    # Stems twisting round the trunk.
    for s in range(2):
        ph = rng.uniform(0, math.tau)
        line = []
        for i in range(9):
            t = i / 8
            q = along(pts, t)
            line.append(q + direction(ph + t * 4.5 * (1 if s else -1)) * along_r(radii, t) * 0.92)
        b.add(tube(line, [r0 * 0.4 * (1 - 0.5 * i / 8) for i in range(9)], 5), wood, bark_col, smooth=True)
    # A glowing hollow at the foot, between two buttresses.
    a = rng.uniform(0, math.tau)
    hollow = Vector((0, 0, r0 * 1.3)) + direction(a) * radii[0] * 1.0
    hb = blob(Vector((0, 0, 0)), r0 * 0.55, rng, subdiv=2, squash=1.7, roughness=0.08)
    bmesh.ops.scale(hb, vec=Vector((0.35, 1.0, 1.0)), verts=hb.verts)
    bmesh.ops.rotate(hb, cent=Vector((0, 0, 0)), matrix=Matrix.Rotation(a, 3, "Z"), verts=hb.verts)
    bmesh.ops.translate(hb, vec=hollow, verts=hb.verts)
    b.add(hb, fruit, solid(lerp(fruit_c, (1, 1, 1), 0.2), rng, 0.0))
    for s in range(2):
        a0 = rng.uniform(0, math.tau)
        line = [along(pts, t) + direction(a0 + t * 3.0) * along_r(radii, t) * 1.04 for t in (i / 15 * 0.95 for i in range(16))]
        b.add(tube(line, [0.06] * len(line), 3), lines, solid(scale(hue, 0.8), rng, 0.0))
    clumps = []
    tiers = [(h * rng.uniform(0.58, 0.66), h * rng.uniform(0.36, 0.48), rng.randint(6, 8))]
    if rng.random() < 0.35:
        tiers += [(h * 0.76, h * rng.uniform(0.24, 0.3), 3), (h * 0.9, h * rng.uniform(0.14, 0.18), 3)]
    else:
        tiers += [(h * rng.uniform(0.82, 0.88), h * rng.uniform(0.2, 0.3), 4)]
    for j, (cz, rx, n) in enumerate(tiers):
        c0 = Vector((pts[-1].x, pts[-1].y, cz)) + (heading(rng) * h * rng.uniform(0.02, 0.07) if j else Vector((0, 0, 0)))
        rz = h * 0.1
        col = crown_colour(st, rng, cz - rz, cz + rz * 2, c0, rx, rz, stops=stops)
        mass = Crown(c0, col, pull=0.6, jag=0.3, tip=0.22)
        phase = rng.uniform(0, math.tau)
        src = pts[-2] if j == 0 else pts[-1]
        if j:
            b.add(tube(curve(pts[-1], c0, Vector((0, 0, 0)), 2), [radii[-1] * 0.8 / j, radii[-1] * 0.6 / j, radii[-1] * 0.45 / j], 7), wood, bark_col, smooth=True)
            src = c0 - UP * rz
        for i in range(n):
            a = phase + i / n * math.tau + rng.uniform(-0.2, 0.2)
            r = rx * rng.uniform(0.6, 0.8)
            c = c0 + direction(a) * r + UP * rng.uniform(-0.2, 0.3) * rz
            cr = rx * rng.uniform(0.3, 0.38)
            b.add(tube(curve(src, c, UP * rz * 0.8, 3), [r0 * 0.42, r0 * 0.3, r0 * 0.2, r0 * 0.1], 5), wood, bark_col, smooth=True)
            mass.lobe(c, cr * 1.05, 0.55, sub=2 if i % 2 == 0 else 1)
            clumps.append((c, cr))
        mass.lobe(c0 + UP * rz * 0.4, rx * 0.66, 0.4, sub=2)
        mass.build(b, wood, rng)
    # Glow tips and vines go on in turn round the crown until the triangle budget is spent.
    rng.shuffle(clumps)
    for c, cr in clumps:
        if tris(b) > 2850:
            break
        for _ in range(rng.randint(1, 2)):
            a = rng.uniform(0, math.tau)
            e = rng.uniform(-0.2, 0.5)
            q = c + Vector((math.cos(a) * cr * 0.92 * math.cos(e), math.sin(a) * cr * 0.92 * math.cos(e), math.sin(e) * cr * 0.5))
            b.add(gem(q, cr * rng.uniform(0.08, 0.12)), tips, solid(scale(hue, 0.7), rng), q, flat=0.2)
        for _ in range(rng.randint(1, 2)):
            a, d = rng.uniform(0, math.tau), rng.uniform(0.2, 0.85) * cr
            top = c + Vector((math.cos(a) * d, math.sin(a) * d, -cr * 0.3))
            end = top + Vector((rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), -rng.uniform(0.1, 0.25) * h))
            end.z = max(end.z, h * 0.4)
            line = curve(top, end, Vector((rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), 0)), 4)
            b.add(tube(line, [0.07, 0.06, 0.055, 0.05, 0.04], 3, cap=False), vine, solid(scale(hue, 0.8), rng, 0.0))
            if rng.random() < 0.55:
                b.add(blob(end + UP * -0.12, rng.uniform(0.14, 0.22), rng, subdiv=1, roughness=0.05, squash=1.3), fruit, solid(fruit_c, rng, 0.0))
    return b


def spirit_sapling(rng, st):
    """A young spirit tree, 1–2.5 m: a thin dark stem that curls over at the top like a fern frond,
    a few dark leaf clumps tipped with glow, and a lantern bud hanging from the curl."""
    b = Builder()
    wood = material("Tree")
    hue, fruit_c = glow_choice(st, rng)
    tips = glow("GlowLeaf", hue, 2.5)
    fruit = glow("GlowFruit", fruit_c, 5.0)
    stops = leaf_stops(st, rng)
    bark_col = lambda co, n: jitter(st["bark"], rng, 0.08)
    for s in range(rng.choice([1, 1, 2])):
        h = rng.uniform(1.6, 2.2) if s == 0 else rng.uniform(0.8, 1.3)
        at = Vector((0, 0, 0)) if s == 0 else heading(rng) * rng.uniform(0.4, 0.7)
        way = heading(rng)
        pts = stem(h * 0.9, rng, 4, base=at + UP * -SINK * 0.3, lean=way * h * 0.12, bow=h * 0.06, wiggle=0.05)
        # The tip arches over, so the lantern bud hangs.
        tip = pts[-1]
        pts.append(tip + way * h * 0.07 + UP * h * 0.03)
        pts.append(tip + way * h * 0.12 - UP * h * 0.03)
        b.add(tube(pts, [h * 0.022 * (1 - 0.7 * i / (len(pts) - 1)) + 0.006 for i in range(len(pts))], 4, cap=False), wood, bark_col, smooth=True)
        centre = along(pts, 0.65)
        col = crown_colour(st, rng, 0, h, centre, h * 0.3, h * 0.4, stops=stops)
        n = rng.randint(3, 4) if s == 0 else 2
        for k in range(n):
            c = along(pts, 0.25 + 0.6 * (k + rng.random()) / n) + heading(rng) * h * 0.1
            cr = h * rng.uniform(0.14, 0.18) * (1.2 - 0.4 * k / n)
            b.add(blob(c, cr, rng, subdiv=2 if s == 0 else 1, squash=0.7, roughness=0.2), wood, col, c, flat=0.1)
            for _ in range(rng.randint(2, 3)):
                q = c + heading(rng) * cr * 0.9 + UP * cr * rng.uniform(-0.2, 0.4)
                b.add(gem(q, cr * 0.28), tips, solid(scale(hue, 0.7), rng), q, flat=0.2)
        end = pts[-1]
        b.add(blob(end - UP * 0.06, h * rng.uniform(0.035, 0.05), rng, subdiv=1, roughness=0.05, squash=1.3), fruit, solid(fruit_c, rng, 0.0))
    return b


def tree(rng, st):
    return spirit_tree(rng, st) if st is STYLES["spirit"] else broadleaf(rng, st)


def giant(rng, st):
    return spirit_giant(rng, st) if st is STYLES["spirit"] else oak(rng, st)


# ---------------------------------------------------------------------------------------------
# Undergrowth, rocks and glowing things

def bush(rng, st):
    """A bush: a few jagged lobes shading as one soft mound, sometimes flowering or berried."""
    b = Builder()
    leaves = material("Leaves")
    r = rng.uniform(0.5, 0.9)
    centre = Vector((0, 0, r * 0.55))
    lo, hi = 0, r * 1.5
    col = crown_colour(st, rng, lo, hi, centre, r * 1.2, r * 0.8, top=0.62)
    crown = Crown(centre - UP * r * 0.2, col, pull=0.7, jag=0.45, tip=0.3, droop=0.5)
    clumps = []
    for i in range(rng.randint(3, 5)):
        a = rng.uniform(0, math.tau)
        c = centre + Vector((math.cos(a) * r * 0.6, math.sin(a) * r * 0.6, rng.uniform(-0.1, 0.35) * r))
        cr = r * rng.uniform(0.55, 0.75)
        crown.lobe(c, cr, 0.8, rough=0.14, sub=2 if i < 2 else 1)
        clumps.append((c, cr))
    crown.build(b, leaves, rng)
    for v in b.bm.verts:
        v.co.z = max(v.co.z, 0.0)

    def on_surface():
        # A point on a clump's upper outside, not hidden inside a neighbour.
        while True:
            c, cr = rng.choice(clumps)
            a, e = rng.uniform(0, math.tau), rng.uniform(0.1, 1.0)
            d = Vector((math.cos(a) * math.cos(e), math.sin(a) * math.cos(e), math.sin(e) * 0.8))
            q = c + d * cr * 0.97
            if all((q - c2).length > cr2 * 0.9 for c2, cr2 in clumps if c2 is not c) and q.z > 0.15:
                return q
    if rng.random() < 0.5:
        if st is STYLES["meadow"]:
            # A flowering bush: pale blossoms dotted on its upper half.
            bloom = material("Blossom")
            pc = rng.choice([(0.95, 0.9, 0.92), (0.95, 0.55, 0.7), (0.98, 0.85, 0.3)])
            for _ in range(14):
                c = on_surface()
                b.add(gem(c, 0.07), bloom, solid(pc, rng), c - UP * 0.2)
        else:
            berry = material("Berry")
            for _ in range(10):
                b.add(gem(on_surface(), 0.05), berry, solid((0.6, 0.04, 0.1), rng))
    return b


def one_rock(b, stone, st, rng, at, r, shape=None):
    """A rock with a strong silhouette: the convex hull of points on a stretched ellipsoid, so it
    breaks into a few big flat facets (crisp under the toon bands), with chamfered edges that
    catch the light. Shapes: a boulder, a leaning slab, a standing stone or a squat block. Moss
    on facets facing up, darker at the foot."""
    shape = shape or rng.choice(["boulder", "boulder", "slab", "standing", "block"])
    sx, sy, sz, n, tilt = dict(boulder=(1.0, 0.85, 0.72, 16, 0.12), slab=(1.35, 0.7, 0.45, 12, 0.35),
                               standing=(0.6, 0.5, 1.35, 12, 0.18), block=(1.0, 0.9, 0.8, 9, 0.1))[shape]
    rot = Matrix.Rotation(rng.uniform(0, math.tau), 3, "Z") @ Matrix.Rotation(rng.uniform(-tilt, tilt), 3, "X") @ Matrix.Rotation(rng.uniform(-tilt, tilt), 3, "Y")
    bm = bmesh.new()
    for i in range(n):
        # Even-ish points on a sphere, pushed in and out a little.
        z = 1 - 2 * (i + 0.5) / n
        a = i * 2.39996 + rng.uniform(-0.3, 0.3)
        q = Vector((math.cos(a) * math.sqrt(1 - z * z), math.sin(a) * math.sqrt(1 - z * z), z)) * rng.uniform(0.78, 1.08)
        bm.verts.new(rot @ Vector((q.x * sx, q.y * sy, q.z * sz)) * r)
    bmesh.ops.convex_hull(bm, input=list(bm.verts))
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bmesh.ops.bevel(bm, geom=list(bm.edges), offset=r * 0.06, segments=1, affect="EDGES", clamp_overlap=True)
    lo = min(v.co.z for v in bm.verts)
    for v in bm.verts:
        # Planted: the lowest third is cut flat into the ground.
        v.co.z = max(v.co.z - lo - (r * sz * 0.3), -0.05)
    bmesh.ops.translate(bm, vec=at, verts=bm.verts)
    rock_c, moss = jitter(st["rock"], rng, 0.1), st["moss"]
    top = max(v.co.z for v in bm.verts) - at.z

    def col(co, n):
        # Moss on top facets, stone below, darker at the foot and on steep facets (painted
        # light, so the facets read even in flat light); each facet its own shade.
        c = lerp(rock_c, lerp(rock_c, moss, 0.6), min(1.0, max(0, n.z - 0.6) / 0.3))
        k = (0.7 + 0.3 * min(1, (co.z - at.z) / max(top * 0.8, 1e-3))) * (0.62 + 0.45 * max(0.0, n.z))
        return jitter(scale(c, k), rng, 0.14)
    b.add(bm, stone, col, per_face=True)


def lump(b, stone, st, rng, at, r):
    """A rounded, noisy lump of rock sitting on `at`: a crystal cluster's foot (the faceted rocks
    above hid it; the blind A/B kept this one)."""
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r)
    off = Vector((rng.random() * 50, rng.random() * 50, 0))
    sq = rng.uniform(0.5, 0.8)
    for v in bm.verts:
        v.co *= 1 + noise.noise(v.co * (1.2 / r) + off) * 0.35
        v.co.z = max(v.co.z * sq + r * 0.3, 0.0)
    bmesh.ops.translate(bm, vec=at, verts=bm.verts)
    rock_c, moss = jitter(st["rock"], rng, 0.1), st["moss"]

    def col(co, n):
        c = lerp(rock_c, moss, max(0, n.z - 0.6) / 0.4)
        return jitter(scale(c, 0.75 + 0.25 * min(1, (co.z - at.z) / (r * 0.6))), rng, 0.06)
    b.add(bm, stone, col)


def rock(rng, st):
    b = Builder()
    stone = material("Stone")
    r = rng.uniform(0.6, 1.4)
    shape = rng.choice(["boulder", "boulder", "slab", "standing", "block"])
    one_rock(b, stone, st, rng, Vector((0, 0, 0)), r, shape)
    for _ in range(rng.choice([0, 1, 1, 2])):
        a = rng.uniform(0, math.tau)
        one_rock(b, stone, st, rng, Vector((math.cos(a), math.sin(a), 0)) * r * rng.uniform(0.9, 1.3), r * rng.uniform(0.28, 0.45),
                 rng.choice(["boulder", "block", "slab"]))
    return b


def grass(rng, st):
    """A grass tuft, about 0.5 m: blades lean out of a tight base, normals point up so the tuft
    shades like the ground it grows from."""
    b = Builder()
    mat = material("Grass", cull=True)
    lo, hi = st["grass"]
    hi = jitter(lerp(hi, (0.5, 0.45, 0.12), rng.uniform(0, 0.35)), rng, 0.05)  # some drier
    h = rng.uniform(0.4, 0.65)
    spread = rng.uniform(0.12, 0.22)
    col = lambda co, n: jitter(ramp((scale(lo, 0.85), lo, hi), co.z / (h * 0.8)), rng, 0.05)
    # Few broad blades rather than many thin ones: thin blades break up into outline noise at
    # the game camera's distance.
    for _ in range(rng.randint(15, 20)):
        a = rng.uniform(0, math.tau)
        d = spread * math.sqrt(rng.random())
        base = Vector((math.cos(a) * d, math.sin(a) * d, -0.02))
        length = h * rng.uniform(0.6, 1.0) * (1.1 - 0.35 * d / spread)
        b.add(blade(base, a + rng.uniform(-0.4, 0.4), length, rng.uniform(0.08, 0.13), rng.uniform(0.12, 0.5), rng.uniform(0.0, 0.2)), mat, col, Vector((0, 0, -3)), flat=0.0, two_sided=True)
    return b


def flower(rng, st):
    """A patch of 6–11 flowers of one kind (sometimes with a second colour) in a leafy tuft,
    about 1 m across: big enough to read as a colour patch from the game camera."""
    b = Builder()
    stem, petal, leaf = material("Stem"), material("Petal", cull=True), material("Grass", cull=True)
    pc = rng.choice(st["petals"])
    other = rng.choice(st["petals"]) if rng.random() < 0.3 else pc
    eye = rng.choice([(0.95, 0.62, 0.04), (0.95, 0.62, 0.04), (0.12, 0.06, 0.02)])
    spread = rng.uniform(0.35, 0.55)
    lo, hi = st["grass"]
    # A low leafy cushion the flowers rise from.
    cushion = blob(Vector((0, 0, 0)), spread * 0.95, rng, subdiv=2, roughness=0.3)
    ch = spread * 0.28
    for v in cushion.verts:
        v.co.z = max(v.co.z * 0.3, -0.02)
    b.add(cushion, leaf, lambda co, n: jitter(lerp(scale(lo, 0.7), lerp(lo, hi, 0.4), co.z / ch), rng, 0.05), Vector((0, 0, -1.5)), flat=0.1)
    petals = rng.choice([5, 5, 6])
    for i in range(rng.randint(8, 11)):
        a = rng.uniform(0, math.tau)
        d = spread * math.sqrt(rng.random())
        base = Vector((math.cos(a) * d, math.sin(a) * d, 0))
        h = rng.uniform(0.2, 0.36) * (1.15 - 0.4 * d / spread)
        top = base + Vector((rng.uniform(-0.06, 0.06), rng.uniform(-0.06, 0.06), h))
        b.add(tube([base, top], [0.012, 0.008], 3, cap=False), stem, solid(st["grass"][1], rng))
        c = jitter(pc if rng.random() < 0.8 else other, rng, 0.08)
        r = rng.uniform(0.09, 0.13)
        b.add(star(top, r, petals, (rng.uniform(-0.35, 0.35), rng.uniform(-0.35, 0.35)), rng), petal,
              lambda co, n, c=c, top=top, r=r: lerp(scale(c, 0.8), c, min(1, (co - top).length / r)), top - UP * 2, flat=0.0, two_sided=True)
        b.add(tube([top + UP * r * 0.15, top + UP * r * 0.4], [r * 0.32, 0], 5, cap=False), petal, solid(eye, rng), top - UP * 0.5, flat=0.2)
    return b


def mushroom(b, st, rng, base, h, cap_mat, gill_mat, stem_mat, spot_mat, spots=(3, 5)):
    lean = Vector((rng.uniform(-0.15, 0.15), rng.uniform(-0.15, 0.15), 0)) * h
    top = base + UP * h + lean
    b.add(tube(curve(base, top, lean * -0.3, 2), [h * 0.09, h * 0.065, h * 0.06], 5, cap=False), stem_mat,
          lambda co, n: jitter(lerp((0.35, 0.42, 0.45), (0.75, 0.85, 0.85), (co.z - base.z) / h), rng, 0.04), smooth=True)
    r = h * rng.uniform(0.38, 0.5)
    glow_c = st["glow"]
    height = rng.uniform(0.45, 0.65)
    b.add(dome(top - UP * r * 0.05, r, rng, height=height), cap_mat,
          lambda co, n: lerp(scale(glow_c, 0.55), lerp(glow_c, (1, 1, 1), 0.25), max(0, n.z)), top - UP * r * 0.6, flat=0.15)
    b.add(disc(top - UP * r * 0.05, r * 0.97, 10, rise=r * 0.25), gill_mat, solid(scale(glow_c, 0.5), rng, 0.0))
    # Hot spots: small, much brighter than the cap, so bloom haloes them and the cap keeps its hue.
    base = top - UP * r * 0.05
    for _ in range(rng.randint(*spots)):
        th, ph = rng.uniform(0.2, 0.95), rng.uniform(0, math.tau)
        n = Vector((math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th)))
        # On the dome: the sphere point, lifted and flattened as dome() does, pushed out a little.
        q = base + Vector((n.x * r * 1.04, n.y * r * 1.04, (n.z * 1.1 + 0.12) * r * height))
        sn = Vector((n.x * height, n.y * height, n.z)).normalized()
        rs = r * rng.uniform(0.12, 0.18)
        b.add(tube([q - sn * r * 0.06, q + sn * r * 0.015], [rs, rs * 0.75], 5), spot_mat, solid((1, 1, 1), rng, 0.0))


def glow_mushroom(rng, st):
    """A cluster of glowing mushrooms: one or two big ones and a few small at their feet."""
    b = Builder()
    stem = material("Stem")
    cap = glow("Glow", st["glow"], 3.0)
    gills = glow("GlowGills", st["glow"], 7.0)
    spots = glow("GlowSpot", lerp(st["glow"], (1, 1, 1), 0.4), 18.0)
    h = rng.uniform(0.6, 1.2)
    mushroom(b, st, rng, Vector((0, 0, 0)), h, cap, gills, stem, spots)
    for _ in range(rng.randint(2, 4)):
        a = rng.uniform(0, math.tau)
        d = h * rng.uniform(0.35, 0.7)
        mushroom(b, st, rng, Vector((math.cos(a) * d, math.sin(a) * d, 0)), h * rng.uniform(0.3, 0.6), cap, gills, stem, spots, (0, 2))
    return b


def glow_plant(rng, st):
    """A spirit-forest plant: a rosette of dark broad leaves with stalks that end in glowing bulbs."""
    b = Builder()
    leaf = material("Leaves", cull=True)
    stem = material("Stem")
    bulb = glow("Glow", st["bloom"], 4.5)
    lo, hi = st["grass"]
    for _ in range(rng.randint(6, 9)):
        a = rng.uniform(0, math.tau)
        length = rng.uniform(0.45, 0.75)
        b.add(blade(Vector((0, 0, 0.02)), a, length, rng.uniform(0.14, 0.2), rng.uniform(0.5, 1.0), 0.35, 3), leaf,
              lambda co, n: jitter(lerp(lo, hi, co.z / 0.5), rng, 0.06), Vector((0, 0, -2)), flat=0.0, two_sided=True)
    for _ in range(rng.randint(3, 6)):
        a = rng.uniform(0, math.tau)
        h = rng.uniform(0.45, 1.0)
        top = Vector((math.cos(a) * h * 0.2, math.sin(a) * h * 0.2, h))
        b.add(tube(curve(Vector((0, 0, 0)), top, Vector((math.cos(a), math.sin(a), 0)) * -0.08, 3), [0.02, 0.016, 0.012, 0.01], 4, cap=False), stem, solid(hi, rng))
        b.add(blob(top + UP * 0.03, rng.uniform(0.06, 0.09), rng, subdiv=1, roughness=0.05, squash=1.3), bulb, solid(lerp(st["bloom"], (1, 1, 1), 0.1), rng, 0.0))
    return b


def crystal(rng, st):
    """A crystal cluster growing from a dark stone foot. Faces facing up are lighter."""
    b = Builder()
    hue = st.get("crystal", st["glow"])
    shard = glow("Glow", hue, 1.7)
    hot = glow("GlowTip", lerp(hue, (1, 1, 1), 0.3), 10.0)
    stone = material("Stone")
    for i in range(rng.randint(4, 7)):
        h = rng.uniform(0.5, 2.0) if i else 2.0
        r = h * rng.uniform(0.12, 0.17)
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=False, segments=6, radius1=r * 0.85, radius2=r, depth=h * 0.75)
        bmesh.ops.translate(bm, vec=Vector((0, 0, h * 0.375)), verts=bm.verts)
        tip = bmesh.new()
        bmesh.ops.create_cone(tip, cap_ends=False, segments=6, radius1=r, radius2=0, depth=h * 0.25)
        bmesh.ops.translate(tip, vec=Vector((0, 0, h * 0.875)), verts=tip.verts)
        tilt = Matrix.Rotation(rng.uniform(-0.55, 0.55), 4, "X") @ Matrix.Rotation(rng.uniform(-0.55, 0.55), 4, "Y")
        off = Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), -0.1))
        for part, mat in ((bm, shard), (tip, hot)):
            bmesh.ops.transform(part, matrix=Matrix.Translation(off) @ tilt, verts=part.verts)
            b.add(part, mat, lambda co, n: lerp(scale(hue, 0.25), lerp(hue, (1, 1, 1), 0.3), max(0, n.z) * 0.6 + 0.4 * min(1, co.z / 2)))
    lump(b, stone, dict(rock=(0.06, 0.06, 0.08), moss=(0.08, 0.08, 0.12)), rng, Vector((0, 0, -0.15)), 0.55)
    return b


def log(rng, st):
    """A fallen log, mossy on top: a torn root plate at one end, a jagged broken end at the other,
    and a stub branch, so it reads as a fallen tree, not a tube."""
    b = Builder()
    bark = material("Bark")
    length = rng.uniform(2.5, 4.5)
    r = rng.uniform(0.25, 0.4)
    a = Vector((-length / 2, 0, r * 0.85))
    e = Vector((length / 2, 0, r * 0.8))
    pts = curve(a, e, Vector((0, rng.uniform(-0.2, 0.2), 0.05)), 4)
    col = lambda co, n: jitter(lerp(st["bark"], st["moss"], max(0, n.z - 0.45) / 0.55), rng, 0.06)
    b.add(tube(pts, [r * (1.05 - 0.15 * i / 4) for i in range(5)], 8), bark, col, smooth=True)
    pale = (0.45, 0.33, 0.2)
    # The broken end: pale splinters standing out of the break.
    p, d = pts[-1], (pts[-1] - pts[-2]).normalized()
    b.add(tube([p, p + d * 0.04], [r * 0.95, r * 0.6], 8), bark, solid(pale, rng))
    side = Vector((-d.y, d.x, 0))
    for k in range(rng.randint(3, 5)):
        ang = k / 4 * math.tau + rng.uniform(-0.4, 0.4)
        o = (side * math.cos(ang) + UP * math.sin(ang)) * r * rng.uniform(0.3, 0.75)
        b.add(tube([p + o - d * 0.05, p + o * 1.1 + d * rng.uniform(0.25, 0.6)], [r * rng.uniform(0.18, 0.3), 0.0], 3, cap=False), bark, solid(pale, rng))
    # The root plate: roots fanned out round the foot, earth still caught between them.
    p, d = pts[0], (pts[0] - pts[1]).normalized()
    side = Vector((-d.y, d.x, 0))
    earth = (0.16, 0.12, 0.08)
    disc_ = blob(p + d * 0.08, r * 1.5, rng, subdiv=1, roughness=0.3)
    bmesh.ops.scale(disc_, vec=Vector((0.35, 1.0, 1.0)) if abs(d.x) > abs(d.y) else Vector((1.0, 0.35, 1.0)), space=Matrix.Translation(-(p + d * 0.08)), verts=disc_.verts)
    for v in disc_.verts:
        v.co.z = max(v.co.z, -0.05)
    b.add(disc_, bark, solid(earth, rng, 0.1))
    for k in range(rng.randint(5, 7)):
        ang = k / 6 * math.tau + rng.uniform(-0.3, 0.3)
        o = side * math.cos(ang) + UP * math.sin(ang)
        end = p + o * r * rng.uniform(2.0, 2.8) + d * rng.uniform(0.0, 0.3)
        end.z = max(end.z, 0.02)
        b.add(tube(curve(p + o * r * 0.6, end, d * 0.2, 2), [r * 0.32, r * 0.2, r * 0.05], 4, cap=False), bark, col, smooth=True)
    s_ = pts[2] + Vector((0, 0, r * 0.7))
    b.add(tube([s_, s_ + Vector((0.25, rng.uniform(-0.2, 0.2), 0.5))], [r * 0.3, r * 0.15], 5), bark, col, smooth=True)
    return b


def stalagmite(rng, st):
    """A cave stalagmite: a lumpy cone with a wet, paler tip."""
    b = Builder()
    stone = material("Stone")
    h = rng.uniform(2, 5)
    r = h * rng.uniform(0.16, 0.22)
    pts = curve(Vector((0, 0, -0.2)), Vector((rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2), h)), Vector((rng.uniform(-0.15, 0.15), 0, 0)) * h, 6)
    radii = [r * (1 - t) ** 1.3 * (1 + 0.12 * math.sin(t * 17)) for t in (i / 6 for i in range(7))]
    radii[-1] = 0
    rock_c = st["rock"]
    b.add(tube(pts, radii, 7), stone, lambda co, n: jitter(lerp(scale(rock_c, 0.7), lerp(rock_c, (0.7, 0.7, 0.75), 0.4), co.z / h), rng, 0.06), smooth=True)
    return b


KINDS = dict(tree=tree, oak=oak, birch=birch, pine=pine, spruce=spruce, coppice=coppice, young=young, sapling=sapling,
             snag=snag, giant=giant, bush=bush, rock=rock, flower=flower, grass=grass, glow_mushroom=glow_mushroom,
             glow_plant=glow_plant, crystal=crystal, log=log, stalagmite=stalagmite)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True, choices=sorted(KINDS))
    ap.add_argument("--style", default="meadow", choices=sorted(STYLES))
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    for i in range(a.count):
        reset()
        rng = random.Random(a.seed * 1000 + i)
        obj = KINDS[a.kind](rng, STYLES[a.style]).finish(f"{a.kind}_{a.style}_{i:02d}")
        tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
        dims = obj.dimensions
        path = os.path.join(a.out, f"gen-{a.kind}-{a.style}-{i:02d}.glb")
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_vertex_color="ACTIVE", export_normals=True, export_yup=True, use_selection=False)
        print(f"GEN {path} tris={tris} size={dims.x:.2f}x{dims.y:.2f}x{dims.z:.2f}")


main()
