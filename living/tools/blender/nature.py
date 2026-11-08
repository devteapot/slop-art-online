"""Stylized nature generator for the game client's test environments.

Run headless:
    blender -b -P living/tools/blender/nature.py -- --kind tree --style meadow --count 12 --out DIR

Kinds: tree, pine, bush, rock, flower, grass, glow_mushroom, glow_plant, crystal, log, stalagmite.
Styles shift colours and shapes (meadow, forest, spirit). Every asset is real-size in metres,
origin at its base, +Z up in Blender (+Y in glTF), coloured by vertex colours (linear, gradients
baked per vertex) on white materials so the game's toon material does the shading. Glowing
parts use a material whose name starts with "Glow" and that has emission.

Readability rules, judged through the game's renderer at the gameplay camera (40° down, 16 m):
- Small things come as clumps or patches (flowers, grass tufts, mushroom clusters), never as
  one 30 cm stem.
- Foliage clumps get custom normals pointing out from the clump's centre, and grass and flower
  heads point up, so they shade as soft masses (Genshin-style), not noisy facets.
- Forest trees carry their crowns high on long trunks, so a 40°/16 m camera sees trunks and
  the floor beneath instead of a lid of canopy. Open-grown meadow trees keep broad crowns.
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

NITS = 1000.0 * float(os.environ.get("NATURE_GLOW", "1"))
UP = Vector((0, 0, 1))

STYLES = {
    # leaf: deep (inside, below), mid, top (sunlit, a little warmer). All linear RGB.
    "meadow": dict(
        leaf=((0.035, 0.10, 0.045), (0.12, 0.30, 0.06), (0.36, 0.58, 0.10)),
        bark=(0.14, 0.11, 0.09), rock=(0.36, 0.35, 0.33), moss=(0.16, 0.32, 0.06),
        grass=((0.08, 0.20, 0.03), (0.34, 0.58, 0.05)),
        tree=dict(h=(7, 11), base=0.36, width=0.31, clumps=(7, 9), lobes=(0, 1)),
        petals=[(0.92, 0.22, 0.38), (0.95, 0.68, 0.06), (0.42, 0.28, 0.90), (0.90, 0.90, 0.94), (0.90, 0.20, 0.06), (0.25, 0.48, 0.95)],
        glow=(0.4, 1.0, 0.9)),
    "forest": dict(
        leaf=((0.015, 0.05, 0.03), (0.05, 0.16, 0.05), (0.19, 0.38, 0.08)),
        bark=(0.10, 0.085, 0.075), rock=(0.30, 0.30, 0.28), moss=(0.10, 0.26, 0.05),
        grass=((0.04, 0.11, 0.03), (0.18, 0.36, 0.07)),
        needle=((0.015, 0.05, 0.04), (0.06, 0.17, 0.09), (0.16, 0.33, 0.14)),
        tree=dict(h=(10, 15), base=0.5, width=0.23, clumps=(7, 9), lobes=(1, 2)),
        petals=[(0.9, 0.9, 0.95), (0.95, 0.75, 0.3)], glow=(0.4, 1.0, 0.9)),
    "spirit": dict(
        leaf=((0.01, 0.03, 0.07), (0.03, 0.12, 0.20), (0.10, 0.36, 0.45)),
        bark=(0.06, 0.05, 0.08), rock=(0.16, 0.17, 0.24), moss=(0.06, 0.20, 0.24),
        grass=((0.02, 0.06, 0.08), (0.08, 0.26, 0.30)),
        tree=dict(h=(8, 12), base=0.5, width=0.38, clumps=(7, 9)),
        petals=[(0.6, 0.9, 1.0), (0.85, 0.6, 1.0)],
        glow=(0.1, 1.0, 0.72), fruit=(1.0, 0.42, 0.04), bloom=(0.55, 0.22, 1.0), crystal=(0.2, 0.32, 1.0)),
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


class Builder:
    """Accumulates parts into one bmesh with a per-corner colour layer and material slots."""

    def __init__(self):
        self.bm = bmesh.new()
        self.col = self.bm.loops.layers.color.new("Color")
        # Shading per face: 0 flat, -1 smooth, k > 0 radial from self.centres[k - 1].
        self.shade_layer = self.bm.faces.layers.int.new("shade")
        self.mats = []
        self.centres = []

    def slot(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def add(self, bm_part, mat, color_fn, centre=None, flat=0.15, smooth=False, two_sided=False):
        """Merge a part: color_fn(vertex_co, face_normal) -> rgb.

        centre: foliage normals point out from it (lerped `flat` towards the face normal).
        smooth: averaged vertex normals (trunks, stems). two_sided: add back faces too.
        """
        idx = self.slot(mat)
        if centre is not None:
            self.centres.append((Vector(centre), flat))
            shade = len(self.centres)
        else:
            shade = SMOOTH if smooth else FLAT
        for reverse in ((False, True) if two_sided else (False,)):
            mapping = {v: self.bm.verts.new(v.co) for v in bm_part.verts}
            for f in bm_part.faces:
                vs = [mapping[v] for v in f.verts]
                try:
                    nf = self.bm.faces.new(vs[::-1] if reverse else vs)
                except ValueError:
                    continue
                nf.material_index = idx
                nf[self.shade_layer] = shade
                nf.normal_update()
                for loop in nf.loops:
                    loop[self.col] = (*srgb(color_fn(loop.vert.co, nf.normal)), 1.0)
        bm_part.free()

    def finish(self, name):
        mesh = bpy.data.meshes.new(name)
        shade = [f[self.shade_layer] for f in self.bm.faces]
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
                if s > 0:
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
# Kinds

def crown_colour(st, rng, lo, hi, centre, rx, rz, top=1.0):
    """Leaves: darker inside and below, lighter and warmer on the sunlit top (up to `top` of
    the way along the style's leaf ramp)."""
    stops = [jitter(s, rng, 0.08) for s in st["leaf"]]

    def f(co, n):
        tz = (co.z - lo) / max(hi - lo, 1e-3)
        d = co - centre
        out = math.sqrt((d.x / rx) ** 2 + (d.y / rx) ** 2 + (d.z / rz) ** 2)
        return jitter(ramp(stops, top * (0.55 * tz + 0.3 * min(out, 1.2) + 0.15 * max(0, n.z) - 0.1)), rng, 0.04)
    return f


def trunk_points(h_top, lean, wiggle, rng, segs=5):
    pts = []
    for i in range(segs + 1):
        t = i / segs
        w = Vector((noise.noise(Vector((t * 2, wiggle, 0))), noise.noise(Vector((wiggle, t * 2, 0))), 0)) * 0.25
        pts.append(Vector((0, 0, -0.3 + (h_top + 0.3) * t)) + lean * t * t + w * t)
    return pts


def roots(b, mat, col, r0, count, rng, reach=3.2):
    for k in range(count):
        a = k / count * math.tau + rng.uniform(-0.4, 0.4)
        out = Vector((math.cos(a), math.sin(a), 0))
        top = out * r0 * 0.3 + UP * r0 * rng.uniform(1.6, 2.6)
        end = out * r0 * reach * rng.uniform(0.8, 1.2) + UP * -0.08
        b.add(tube(curve(top, end, out * r0 * 0.3, 2), [r0 * 0.55, r0 * 0.35, r0 * 0.08], 5, cap=False), mat, col, smooth=True)


def broadleaf(rng, st):
    """An open-grown or forest broadleaf: trunk, a few visible limbs, and a crown of clumps."""
    p = st["tree"]
    b = Builder()
    bark, leaves = material("Bark"), material("Leaves")
    h = rng.uniform(*p["h"])
    lo = h * p["base"] * rng.uniform(0.92, 1.1)
    rz = (h - lo) / 2
    rx = h * p["width"] * rng.uniform(0.85, 1.15)
    lean = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0)) * h * 0.03
    centre = Vector((0, 0, lo + rz)) + lean
    r0 = h * 0.032
    pts = trunk_points(centre.z, lean, rng.random() * 10, rng)
    bark_col = lambda co, n: jitter(lerp(scale(st["bark"], 0.7), st["bark"], min(1, co.z / 3)), rng, 0.05)
    b.add(tube(pts, [r0 * (1.35 - 0.75 * i / (len(pts) - 1)) for i in range(len(pts))], 8), bark, bark_col, smooth=True)
    roots(b, bark, bark_col, r0, rng.randint(3, 5), rng)
    col = crown_colour(st, rng, lo, h, centre, rx, rz)
    # Clumps on the crown's shell (golden spiral, more on top), each with its own radial normals
    # blended with the crown's, so the crown reads as one mass with lumps.
    n = rng.randint(*p["clumps"])
    phase = rng.uniform(0, math.tau)
    for i in range(n):
        y = 1 - (i + 0.5) / n * 1.6
        r = math.sqrt(max(0.0, 1 - y * y))
        a = i * 2.39996 + phase
        c = centre + Vector((math.cos(a) * r * rx * 0.62, math.sin(a) * r * rx * 0.62, y * rz * 0.55))
        cr = min(rx, rz) * rng.uniform(0.5, 0.62)
        if y < 0.2:  # lower clumps hang off limbs you can see
            start = pts[-2].lerp(pts[-1], rng.uniform(0.0, 0.6))
            b.add(tube(curve(start, c, UP * 0.3, 2), [r0 * 0.45, r0 * 0.3, r0 * 0.15], 5), bark, bark_col, smooth=True)
        b.add(blob(c, cr, rng, subdiv=3 if y > -0.1 else 2, squash=0.85), leaves, col, c.lerp(centre, 0.5), flat=0.1)
    b.add(blob(centre + UP * rz * 0.1, min(rx, rz) * 0.78, rng, subdiv=2, squash=rz / max(rx, rz) * 1.05), leaves, col, centre, flat=0.1)
    # Side lobes: a limb leaves the trunk below the crown and carries its own small clump, so
    # the silhouette isn't a lollipop.
    for _ in range(rng.randint(*p.get("lobes", (0, 0)))):
        a = rng.uniform(0, math.tau)
        out = Vector((math.cos(a), math.sin(a), 0))
        z = lo - rz * rng.uniform(0.1, 0.5)
        k = (z + 0.3) / (centre.z + 0.3) * (len(pts) - 1)
        i = min(int(k), len(pts) - 2)
        start = pts[i].lerp(pts[i + 1], k - i)
        c = start + out * rx * rng.uniform(0.8, 1.05) + UP * rz * 0.35
        lr = min(rx, rz) * rng.uniform(0.38, 0.5)
        b.add(tube(curve(start, c, UP * 0.3 - out * 0.3, 2), [r0 * 0.5, r0 * 0.35, r0 * 0.2], 5), bark, bark_col, smooth=True)
        b.add(blob(c, lr, rng, subdiv=2, squash=0.8), leaves, col, c, flat=0.15)
    return b


def spirit_tree(rng, st):
    """A dark spirit tree that reads at night: gnarled trunk and wide umbrella crown in silhouette,
    with glowing vines hanging from the crown, lantern fruit on their ends, glowing leaf tips and
    bioluminescent lines up the bark."""
    p = st["tree"]
    b = Builder()
    bark, leaves = material("Bark"), material("Leaves")
    vine = glow("Glow", st["glow"], 3.0)
    fruit = glow("GlowFruit", st["fruit"], 5.0)
    tips = glow("GlowLeaf", st["glow"], 2.0)
    lines = glow("GlowLine", st["glow"], 2.5)
    h = rng.uniform(*p["h"])
    rx = h * p["width"] * rng.uniform(0.9, 1.15)
    rz = h * 0.22
    lean = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0)) * h * 0.06
    centre = Vector((0, 0, h - rz * 1.1)) + lean
    r0 = h * 0.045
    pts = []
    sway = rng.uniform(0.5, 1.0) * h * 0.06
    ph = rng.uniform(0, math.tau)
    for i in range(8):
        t = i / 7
        pts.append(Vector((math.sin(t * 3.4 + ph) * sway * t, math.cos(t * 2.7 + ph) * sway * t, -0.3 + (centre.z - rz * 0.3 + 0.3) * t)) + lean * t * t)
    radii = [r0 * (1.5 - 0.8 * t) for t in (i / 7 for i in range(8))]
    bark_col = lambda co, n: jitter(lerp(scale(st["bark"], 0.6), st["bark"], min(1, co.z / 4)), rng, 0.06)
    b.add(tube(pts, radii, 8), bark, bark_col, smooth=True)
    roots(b, bark, bark_col, r0, rng.randint(4, 6), rng, reach=4.0)
    # Glowing lines spiralling up the bark, just proud of its surface.
    for s in range(2):
        a0 = rng.uniform(0, math.tau) + s * math.pi
        line = []
        for i in range(14):
            t = i / 13
            q = (len(pts) - 1) * t * 0.92
            k = min(int(q), len(pts) - 2)
            c = pts[k].lerp(pts[k + 1], q - k)
            rr = (radii[k] + (radii[k + 1] - radii[k]) * (q - k)) * 1.06
            a = a0 + t * rng.uniform(2.0, 3.5)
            line.append(c + Vector((math.cos(a), math.sin(a), 0)) * rr)
        b.add(tube(line, [0.035] * len(line), 3), lines, solid(scale(st["glow"], 0.8), rng, 0.0))
    # Limbs out to a wide, flat crown of dark clumps.
    col = crown_colour(st, rng, centre.z - rz, centre.z + rz, centre, rx, rz)
    n = rng.randint(*p["clumps"])
    phase = rng.uniform(0, math.tau)
    clumps = []
    for i in range(n):
        a = phase + i / n * math.tau + rng.uniform(-0.25, 0.25)
        r = rx * rng.uniform(0.55, 0.75)
        c = centre + Vector((math.cos(a) * r, math.sin(a) * r, rng.uniform(-0.3, 0.2) * rz))
        cr = rx * rng.uniform(0.32, 0.42)
        b.add(tube(curve(pts[-2], c, UP * rz * 0.5, 3), [r0 * 0.6, r0 * 0.45, r0 * 0.3, r0 * 0.15], 5), bark, bark_col, smooth=True)
        b.add(blob(c, cr, rng, subdiv=2, squash=0.6), leaves, col, c.lerp(centre, 0.4), flat=0.1)
        clumps.append((c, cr))
    b.add(blob(centre + UP * rz * 0.3, rx * 0.62, rng, subdiv=3, squash=0.45), leaves, col, centre, flat=0.1)
    # Glowing leaf tips: small bright tufts on the crown's rim and top.
    for c, cr in clumps:
        for _ in range(rng.randint(3, 5)):
            a = rng.uniform(0, math.tau)
            e = rng.uniform(-0.2, 0.5)
            q = c + Vector((math.cos(a) * cr * 0.92 * math.cos(e), math.sin(a) * cr * 0.92 * math.cos(e), math.sin(e) * cr * 0.55))
            b.add(gem(q, cr * rng.uniform(0.1, 0.16)), tips, solid(scale(st["glow"], 0.7), rng), q, flat=0.2)
    # Vines from the crown's underside, some ending in lantern fruit.
    for c, cr in clumps:
        for _ in range(rng.randint(2, 3)):
            a, d = rng.uniform(0, math.tau), rng.uniform(0.2, 0.85) * cr
            top = c + Vector((math.cos(a) * d, math.sin(a) * d, -cr * 0.35))
            # Vines stay above head height (and above the game camera's line to the player).
            length = rng.uniform(0.08, 0.2) * h
            end = top + Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), -length))
            end.z = max(end.z, h * 0.55)
            line = curve(top, end, Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), 0)), 4)
            b.add(tube(line, [0.05, 0.045, 0.04, 0.035, 0.03], 3, cap=False), vine, solid(scale(st["glow"], 0.8), rng, 0.0))
            if rng.random() < 0.55:
                b.add(blob(end + UP * -0.08, rng.uniform(0.09, 0.15), rng, subdiv=1, roughness=0.05, squash=1.3), fruit, solid(st["fruit"], rng, 0.0))
    return b


def tree(rng, st):
    return spirit_tree(rng, st) if st is STYLES["spirit"] else broadleaf(rng, st)


def pine(rng, st):
    """A conifer of jagged, drooping skirts. Forest pines lose their lower tiers, as in a stand."""
    b = Builder()
    bark, needles = material("Bark"), material("Needles")
    stops = st.get("needle", st["leaf"])
    h = rng.uniform(11, 16)
    lean = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0)) * h * 0.015
    r0 = h * 0.024
    pts = trunk_points(h * 0.9, lean, rng.random() * 10, rng, 4)
    bark_col = lambda co, n: jitter(lerp(scale(st["bark"], 0.7), st["bark"], min(1, co.z / 3)), rng, 0.05)
    b.add(tube(pts, [r0 * (1.3 - 0.9 * i / (len(pts) - 1)) for i in range(len(pts))], 7), bark, bark_col, smooth=True)
    roots(b, bark, bark_col, r0, 3, rng, reach=2.6)
    lo = h * rng.uniform(0.3, 0.4)
    tiers = rng.randint(6, 8)
    rmax = h * rng.uniform(0.15, 0.19)
    sides = 10
    for i in range(tiers):
        t = i / (tiers - 1)
        z = lo + (h * 0.86 - lo) * t
        axis = Vector((0, 0, z)) + lean * (z / h) ** 2
        r = rmax * (1 - t * 0.82) * rng.uniform(0.9, 1.1)
        th = (h - lo) / tiers * 1.9
        bm = bmesh.new()
        apex = bm.verts.new(axis + UP * th)
        inner = bm.verts.new(axis + UP * th * 0.3)
        rim = []
        a0 = rng.uniform(0, math.tau)
        for k in range(sides * 2):
            a = a0 + k / (sides * 2) * math.tau
            rr = r * (1.0 if k % 2 == 0 else 0.72)
            droop = r * (0.28 if k % 2 == 0 else 0.12)
            rim.append(bm.verts.new(axis + Vector((math.cos(a) * rr, math.sin(a) * rr, -droop))))
        for k in range(sides * 2):
            bm.faces.new((apex, rim[k], rim[(k + 1) % (sides * 2)]))
            bm.faces.new((inner, rim[(k + 1) % (sides * 2)], rim[k]))
        lo_z, hi_z = z - r * 0.3, z + th

        def col(co, n, lo_z=lo_z, hi_z=hi_z, t=t):
            tz = (co.z - lo_z) / (hi_z - lo_z)
            return jitter(ramp(stops, 0.35 * tz + 0.35 * t + 0.3 * max(0, n.z)), rng, 0.04)
        b.add(bm, needles, col, axis + UP * th * 0.2, flat=0.2)
    b.add(tube([Vector((0, 0, h * 0.86)) + lean * 0.74 ** 2, Vector((0, 0, h)) + lean], [rmax * 0.12, 0], 6, cap=False), needles, lambda co, n: jitter(stops[2], rng, 0.04), Vector((0, 0, h * 0.8)), flat=0.3)
    return b


def bush(rng, st):
    b = Builder()
    leaves = material("Leaves")
    r = rng.uniform(0.5, 0.9)
    centre = Vector((0, 0, r * 0.55))
    lo, hi = 0, r * 1.5
    col = crown_colour(st, rng, lo, hi, centre, r * 1.2, r * 0.8, top=0.62)
    clumps = []
    for i in range(rng.randint(4, 5)):
        a = rng.uniform(0, math.tau)
        c = centre + Vector((math.cos(a) * r * 0.6, math.sin(a) * r * 0.6, rng.uniform(-0.1, 0.35) * r))
        cr = r * rng.uniform(0.5, 0.7)
        bm = blob(c, cr, rng, squash=0.8, roughness=0.12)
        for v in bm.verts:
            v.co.z = max(v.co.z, 0.0)
        b.add(bm, leaves, col, c.lerp(centre, 0.6), flat=0.15)
        clumps.append((c, cr))

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


def one_rock(b, stone, st, rng, at, r):
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
        # Moss on top faces, stone below, darker at the foot.
        c = lerp(rock_c, moss, max(0, n.z - 0.6) / 0.4)
        return jitter(scale(c, 0.75 + 0.25 * min(1, (co.z - at.z) / (r * 0.6))), rng, 0.06)
    b.add(bm, stone, col)


def rock(rng, st):
    b = Builder()
    stone = material("Stone")
    r = rng.uniform(0.5, 1.4)
    one_rock(b, stone, st, rng, Vector((0, 0, 0)), r)
    for _ in range(rng.choice([0, 1, 1, 2])):
        a = rng.uniform(0, math.tau)
        one_rock(b, stone, st, rng, Vector((math.cos(a), math.sin(a), 0)) * r * rng.uniform(0.9, 1.3), r * rng.uniform(0.25, 0.45))
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
    one_rock(b, stone, dict(rock=(0.06, 0.06, 0.08), moss=(0.08, 0.08, 0.12)), rng, Vector((0, 0, -0.15)), 0.55)
    return b


def log(rng, st):
    """A fallen log, mossy on top, with a broken stub."""
    b = Builder()
    bark = material("Bark")
    length = rng.uniform(2.5, 4.5)
    r = rng.uniform(0.25, 0.4)
    a = Vector((-length / 2, 0, r * 0.85))
    e = Vector((length / 2, 0, r * 0.8))
    pts = curve(a, e, Vector((0, rng.uniform(-0.2, 0.2), 0.05)), 4)
    col = lambda co, n: jitter(lerp(st["bark"], st["moss"], max(0, n.z - 0.45) / 0.55), rng, 0.06)
    b.add(tube(pts, [r * (1.05 - 0.15 * i / 4) for i in range(5)], 8), bark, col, smooth=True)
    # Pale broken wood at both ends.
    for p, d in ((pts[0], pts[0] - pts[1]), (pts[-1], pts[-1] - pts[-2])):
        b.add(tube([p, p + d.normalized() * 0.04], [r * 0.95, r * 0.6], 8), bark, solid((0.45, 0.33, 0.2), rng))
    s = pts[2] + Vector((0, 0, r * 0.7))
    b.add(tube([s, s + Vector((0.25, rng.uniform(-0.2, 0.2), 0.5))], [r * 0.3, r * 0.15], 5), bark, col, smooth=True)
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


KINDS = dict(tree=tree, pine=pine, bush=bush, rock=rock, flower=flower, grass=grass, glow_mushroom=glow_mushroom,
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
