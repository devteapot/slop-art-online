"""Stylized building generator for the game client's test-environment cities.

Run headless:
    blender -b -P living/tools/blender/buildings.py -- --style fantasy --kind house --count 8 --out DIR

Styles and kinds (see HEIGHTS):
- fantasy: house (cottage), townhouse, tower, wall, market_stall, lamp: timber frame and
  plaster on stone, steep stepped-shingle roofs, chimneys, dormers, warm lit windows;
- steampunk: house, factory, chimney, pipe, crate, lamp: brick, riveted metal bands, copper
  roofs and domes, pipes, gears, smokestacks;
- giant: house, tower, lamp: the fantasy grammar built for 5 m giants (doors ~6 m, steps ~0.5 m);
- small: house, tower: burrows, mushroom and stump dwellings for 0.6 m small folk.

Conventions (as nature.py): metres, origin at the base centre, +Z up in Blender (+Y in glTF),
fronts face -Y in Blender (+Z in glTF, the asset view's "front"). Colour is per-vertex
("Color", exported as COLOR_0) on a white "Body" material so the game's toon material does
the shading; lit windows and lamps use a "Glow" material with emission.

Every model of a kind is scaled to exactly that kind's height (HEIGHTS) above its floor, and the
environment slots use the same height, so the harness never rescales a building: doors stay
door-sized.

Foundations: the origin is the floor (where the building meets level ground). Below it every
model has a stepped stone foundation under its whole ground outline, about 1.8 m deep for a
person's house (FOUNDATION, scaled with the inhabitants: about 5 m for giants, 0.6 m for small
folk), so on a slope it reaches down into the ground instead of floating; on flat ground it is
hidden. The settlement planner (`living/rules/src/settle.rs`) levels each lot to the floor.

Footprints: every model of a kind fits inside ENVELOPES (width along the front, depth front to
back, roof overhangs and steps included); a model that does not prints WARN. `--table PATH`
writes HEIGHTS, ENVELOPES and foundation depths as the JSON the planner reads
(`living/rules/data/buildings.json`); `gen_buildings.sh` refreshes it.
"""

import argparse
import json
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector, noise

PROFILE = None  # --profile: triangles per generator function

X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))

# Inhabitant heights: everything is designed around the door its folk need.
FOLK = {"human": 1.75, "giant": 5.0, "small": 0.6}

# Exact model height (m) per (style, kind); the env JSON slots use the same numbers.
HEIGHTS = {
    ("fantasy", "house"): 8.0,
    ("fantasy", "townhouse"): 12.0,
    ("fantasy", "tower"): 24.0,
    ("fantasy", "wall"): 5.5,
    ("fantasy", "market_stall"): 2.6,
    ("fantasy", "lamp"): 3.6,
    ("steampunk", "house"): 12.0,
    ("steampunk", "factory"): 15.0,
    ("steampunk", "chimney"): 20.0,
    ("steampunk", "pipe"): 2.0,
    ("steampunk", "crate"): 1.0,
    ("steampunk", "lamp"): 4.0,
    ("giant", "house"): 8.0 * 5.0 / 1.75,
    ("giant", "tower"): 13.3 * 5.0 / 1.75,
    ("giant", "lamp"): 3.6 * 5.0 / 1.75,
    ("small", "house"): 1.6,
    ("small", "tower"): 3.5,
    ("fantasy", "well"): 3.4,
    ("giant", "well"): 3.4 * 5.0 / 1.75,
    ("small", "well"): 3.4 * 0.6 / 1.75,
}

# Foundation depth below the floor, in a person's metres (scaled with the inhabitants).
FOUNDATION = {"lamp": 0.6, "market_stall": 0.5, "crate": 0.4, "pipe": 0.5}
FOUNDATION_DEFAULT = 1.8

# Footprint envelope (width along the front, depth front to back; metres, as built) of every model
# of a kind: the maximum over 32 seeds, foundations included, plus a little. The planner sizes
# lots by these, so changing a generator's proportions means re-measuring them.
ENVELOPES = {
    ("fantasy", "house"): (10.1, 9.5),
    ("fantasy", "lamp"): (2.0, 0.7),
    ("fantasy", "market_stall"): (4.2, 2.0),
    ("fantasy", "tower"): (8.7, 8.7),
    ("fantasy", "townhouse"): (10.4, 8.8),
    ("fantasy", "wall"): (5.0, 3.8),
    ("fantasy", "well"): (3.0, 2.4),
    ("giant", "house"): (29.3, 27.1),
    ("giant", "lamp"): (5.7, 1.8),
    ("giant", "tower"): (21.2, 21.2),
    ("giant", "well"): (8.4, 6.7),
    ("small", "house"): (3.1, 3.5),
    ("small", "tower"): (2.5, 2.5),
    ("small", "well"): (1.0, 0.9),
    ("steampunk", "chimney"): (7.1, 7.1),
    ("steampunk", "crate"): (1.9, 1.4),
    ("steampunk", "factory"): (17.0, 17.4),
    ("steampunk", "house"): (9.1, 9.1),
    ("steampunk", "lamp"): (1.7, 0.9),
    ("steampunk", "pipe"): (7.2, 0.9),
}

PALETTES = {
    "fantasy": dict(
        plaster=[(0.95, 0.90, 0.79), (0.97, 0.86, 0.68), (0.94, 0.82, 0.76), (0.88, 0.89, 0.82), (0.96, 0.93, 0.87)],
        timber=(0.34, 0.22, 0.15), stone=(0.70, 0.66, 0.59), stone_dark=(0.55, 0.52, 0.48),
        roof=[(0.28, 0.40, 0.62), (0.74, 0.33, 0.22), (0.22, 0.50, 0.52), (0.52, 0.36, 0.25), (0.46, 0.43, 0.42), (0.34, 0.46, 0.30)],
        paint=[(0.58, 0.24, 0.18), (0.24, 0.44, 0.33), (0.26, 0.35, 0.56), (0.66, 0.50, 0.22), (0.46, 0.30, 0.18)],
        glass=(0.17, 0.21, 0.30), under=(0.30, 0.21, 0.15), iron=(0.20, 0.20, 0.23),
        glow=(1.0, 0.68, 0.34)),
    "steampunk": dict(
        brick=[(0.62, 0.30, 0.22), (0.56, 0.27, 0.21), (0.66, 0.36, 0.26), (0.50, 0.30, 0.25)],
        stone=(0.74, 0.67, 0.56), stone_dark=(0.50, 0.45, 0.40),
        copper=[(0.30, 0.62, 0.55), (0.76, 0.44, 0.26), (0.36, 0.56, 0.50)], brass=(0.80, 0.62, 0.30),
        iron=(0.22, 0.22, 0.25), steel=(0.42, 0.42, 0.45), timber=(0.36, 0.24, 0.16),
        paint=[(0.20, 0.32, 0.30), (0.42, 0.18, 0.16), (0.18, 0.22, 0.32)],
        glass=(0.18, 0.18, 0.22), under=(0.25, 0.20, 0.17), glow=(1.0, 0.62, 0.28)),
    "small": dict(
        earth=(0.46, 0.34, 0.22), grass=[(0.42, 0.62, 0.26), (0.36, 0.56, 0.24)], stone=(0.68, 0.64, 0.57),
        cream=(0.94, 0.88, 0.74), bark=(0.46, 0.39, 0.31), heart=(0.86, 0.72, 0.50), timber=(0.36, 0.24, 0.16),
        cap=[(0.80, 0.20, 0.17), (0.86, 0.50, 0.20), (0.60, 0.36, 0.62), (0.46, 0.30, 0.20)],
        roof=[(0.28, 0.40, 0.62), (0.74, 0.33, 0.22), (0.22, 0.50, 0.52)],
        paint=[(0.24, 0.48, 0.30), (0.86, 0.66, 0.20), (0.62, 0.22, 0.20), (0.26, 0.38, 0.62)],
        glass=(0.17, 0.21, 0.30), iron=(0.22, 0.22, 0.25), glow=(1.0, 0.70, 0.36),
        plaster=[(0.97, 0.92, 0.80), (0.96, 0.88, 0.74)], stone_dark=(0.55, 0.52, 0.48), under=(0.32, 0.23, 0.16)),
}
PALETTES["giant"] = PALETTES["fantasy"]


# ---------------------------------------------------------------------------------------------
# Mesh building


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name, color=(1, 1, 1), emission=None, strength=3.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if m.node_tree is None:  # Blender 5 materials always have a node tree
        m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = 0.9
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = strength
    return m


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def mul(c, k):
    return tuple(min(1.0, max(0.0, x * k)) for x in c)


def jitter(c, rng, k=0.05):
    return mul(c, 1 + rng.uniform(-k, k))


class Builder:
    """One bmesh with a per-corner colour layer and material slots (as nature.py's Builder)."""

    def __init__(self):
        self.bm = bmesh.new()
        self.col = self.bm.loops.layers.color.new("Color")
        # Faces with soft (rounded) shading carry the index (+1) of the centre normals point from.
        self.soft_layer = self.bm.faces.layers.int.new("soft")
        self.mats = []
        self.centres = []

    def add(self, part, mat, color_fn, soft_centre=None, closed=True):
        if closed:
            bmesh.ops.recalc_face_normals(part, faces=part.faces)
        if mat not in self.mats:
            self.mats.append(mat)
        idx = self.mats.index(mat)
        if soft_centre is not None:
            self.centres.append(soft_centre.copy())
        soft_id = len(self.centres) if soft_centre is not None else 0
        mapping = {v: self.bm.verts.new(v.co) for v in part.verts}
        for f in part.faces:
            try:
                nf = self.bm.faces.new([mapping[v] for v in f.verts])
            except ValueError:
                continue
            nf.material_index = idx
            nf[self.soft_layer] = soft_id
            nf.normal_update()
            for loop in nf.loops:
                loop[self.col] = (*color_fn(loop.vert.co, nf.normal), 1.0)
        part.free()

    def finish(self, name, height):
        """Scale uniformly so the top is exactly `height` above the floor (z=0, kept as the
        origin; the foundation reaches below it), centre the footprint on the origin, then make
        the object."""
        hi = max(v.co.z for v in self.bm.verts)
        k = height / max(hi, 1e-6)
        # Centred on its footprint, so a lot centred on the origin fits it snugly.
        xs = [v.co.x for v in self.bm.verts]
        ys = [v.co.y for v in self.bm.verts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        m = Matrix.Scale(k, 4) @ Matrix.Translation((-cx, -cy, 0))
        bmesh.ops.transform(self.bm, matrix=m, verts=self.bm.verts)
        self.centres = [m @ c for c in self.centres]
        mesh = bpy.data.meshes.new(name)
        soft = [f[self.soft_layer] for f in self.bm.faces]
        self.bm.to_mesh(mesh)
        self.bm.free()
        for mt in self.mats:
            mesh.materials.append(mt)
        # The exporter writes the active colour attribute as COLOR_0.
        if "Color" in mesh.color_attributes:
            mesh.color_attributes.active_color = mesh.color_attributes["Color"]
            mesh.color_attributes.render_color_index = mesh.color_attributes.active_color_index
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        mesh.shade_flat()
        normals = [None] * len(mesh.loops)
        for poly in mesh.polygons:
            s = soft[poly.index]
            for li in poly.loop_indices:
                if s > 0:
                    v = mesh.vertices[mesh.loops[li].vertex_index].co
                    normals[li] = (v - self.centres[s - 1]).normalized().lerp(poly.normal, 0.25).normalized()
                else:
                    normals[li] = poly.normal.copy()
        mesh.normals_split_custom_set(normals)
        return obj, k


def lbox(lo, hi, fn=None, bevel=0.0, warp=None):
    """A box from lo to hi in local coordinates, optionally warped (local) and mapped (fn)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    size = hi - lo
    for v in bm.verts:
        v.co = Vector((lo.x + (v.co.x + 0.5) * size.x, lo.y + (v.co.y + 0.5) * size.y, lo.z + (v.co.z + 0.5) * size.z))
    if bevel > 0:
        b = min(bevel, min(size) * 0.4)
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=b, segments=1, affect="EDGES", clamp_overlap=True)
    if warp or fn:
        for v in bm.verts:
            p = warp(v.co.copy()) if warp else v.co.copy()
            v.co = fn(p) if fn else p
    return bm


def box(lo, hi, bevel=0.0):
    return lbox(Vector(lo), Vector(hi), bevel=bevel)


def cyl(a, b, r0, r1, sides=10, bevel=0.0):
    a, b = Vector(a), Vector(b)
    bm = bmesh.new()
    axis = b - a
    bmesh.ops.create_cone(bm, cap_ends=True, segments=sides, radius1=r0, radius2=r1, depth=axis.length)
    if bevel > 0:
        rim = [e for e in bm.edges if len(e.link_faces) == 2 and any(len(f.verts) > 4 for f in e.link_faces)]
        bmesh.ops.bevel(bm, geom=rim, offset=bevel, segments=1, affect="EDGES", clamp_overlap=True)
    rot = axis.to_track_quat("Z", "Y").to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=Matrix.Translation((a + b) / 2) @ rot, verts=bm.verts)
    return bm


def sphere(c, r, sub=1, squash=1.0):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r)
    for v in bm.verts:
        v.co.z *= squash
        v.co += Vector(c)
    return bm


def prism(pts, a0, a1, fn):
    """Extrude a 2D polygon pts[(s, z)] between a0 and a1 along the local x axis; fn maps (a, s, z)."""
    bm = bmesh.new()
    f0 = [bm.verts.new(fn(a0, s, z)) for s, z in pts]
    f1 = [bm.verts.new(fn(a1, s, z)) for s, z in pts]
    bm.faces.new(f0)
    bm.faces.new(list(reversed(f1)))
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([f0[i], f0[j], f1[j], f1[i]])
    return bm


def ring_polys(r_out, r_in, n):
    return [(math.cos(i / n * math.tau) * r_out, math.sin(i / n * math.tau) * r_out) for i in range(n)]


class Face:
    """A wall face: `o` is the wall's centre at the foot of its outer surface, `u` runs along it
    (u x Z = n), `n` points out. Local coordinates: a along u, z up, w out."""

    def __init__(self, o, u, length):
        self.o, self.u, self.length = Vector(o), Vector(u), length
        self.n = self.u.cross(Z)

    def p(self, a, z, w):
        return self.o + self.u * a + Z * z + self.n * w

    def box(self, a0, a1, z0, z1, w0, w1, bevel=0.0):
        return lbox(Vector((a0, z0, w0)), Vector((a1, z1, w1)), fn=lambda q: self.p(q.x, q.y, q.z), bevel=bevel)

    def obox(self, a, z, la, lz, w0, w1, angle):
        """A beam centred at (a, z), la long, lz thick, rotated in the wall plane."""
        c, s = math.cos(angle), math.sin(angle)

        def fn(q):
            return self.p(a + q.x * c - q.y * s, z + q.x * s + q.y * c, q.z)
        return lbox(Vector((-la / 2, -lz / 2, w0)), Vector((la / 2, lz / 2, w1)), fn=fn)

    def quad(self, a0, a1, z0, z1, w):
        bm = bmesh.new()
        vs = [bm.verts.new(self.p(a, z, w)) for a, z in ((a0, z0), (a1, z0), (a1, z1), (a0, z1))]
        bm.faces.new(vs)
        return bm

    def poly(self, pts, w0, w1):
        """A slab whose outline pts[(a, z)] lies in the wall plane, from w0 to w1 out."""
        return prism(pts, w0, w1, lambda w, a, z: self.p(a, z, w))


def box_faces(cx, cy, hx, hy):
    """The four outer faces of an axis-aligned box: front (-Y), right (+X), back (+Y), left (-X)."""
    return {
        "front": Face((cx, cy - hy, 0), X, 2 * hx),
        "right": Face((cx + hx, cy, 0), Y, 2 * hy),
        "back": Face((cx, cy + hy, 0), -X, 2 * hx),
        "left": Face((cx - hx, cy, 0), -Y, 2 * hy),
    }


class Kit:
    """A Builder with a palette, an RNG and shading helpers."""

    def __init__(self, rng, pal, ao=1.2):
        self.b = Builder()
        self.rng, self.pal = rng, pal
        self.body = material("Body")
        self.glow_mat = material("Glow", (1, 1, 1), emission=pal["glow"], strength=2.6)
        self.ao = ao

    def add(self, bm, color, glow=False, soft=None, closed=True, vary=0.04, ao=True):
        if PROFILE is not None:
            import inspect
            who = inspect.stack()[1].function
            PROFILE[who] = PROFILE.get(who, 0) + sum(len(f.verts) - 2 for f in bm.faces)
        if color is None and not glow:
            # An unlit window pane.
            color, ao, vary = self.pal["glass"], False, 0.0
        if glow:
            warm = self.pal.get("glow_tint", (1.0, 0.78, 0.45))
            self.b.add(bm, self.glow_mat, lambda co, n: warm, soft, closed)
            return
        if callable(color):
            self.b.add(bm, self.body, color, soft, closed)
            return
        c = jitter(color, self.rng, vary)
        aoh = self.ao

        def fn(co, n):
            # Ground contact darkens a little (painted ambient occlusion).
            k = 0.8 + 0.2 * min(1.0, max(0.0, co.z / aoh)) if ao else 1.0
            return mul(c, k)
        self.b.add(bm, self.body, fn, soft, closed)

    def choice(self, xs):
        return self.rng.choice(xs)

    def u(self, a, b):
        return self.rng.uniform(a, b)


# ---------------------------------------------------------------------------------------------
# Roofs


def gable_roof(k, centre, axis, half_len, half_span, zw, oh_e, oh_g, color, sides=(-1, 1), course=0.48,
               th=0.1, sag=0.06, barge=None, cap=True):
    """A gable (or, with one side, lean-to) roof of stepped, slightly uneven shingle courses.

    `centre` is the middle of the ridge (z = ridge height); the slopes run down across `axis` to
    the wall lines at `half_span`, where they are at `zw`, then on past them by `oh_e`."""
    rng = k.rng
    centre, A = Vector(centre), Vector(axis).normalized()
    C = Vector((-A.y, A.x, 0))
    rise = centre.z - zw
    p = math.atan2(rise, half_span)
    S = (half_span + oh_e) / math.cos(p)
    L = half_len + oh_g
    barge = barge or k.pal.get("timber", (0.3, 0.2, 0.15))
    under = k.pal.get("under", (0.3, 0.2, 0.15))

    def droop(a, t):
        return sag * (1 - min(1.0, (a / L) ** 2)) * (1 - 0.6 * t / S)

    for sgn in sides:
        D = C * (sgn * math.cos(p)) - Z * math.sin(p)
        N = C * (sgn * math.sin(p)) + Z * math.cos(p)

        def fn(q, D=D, N=N):
            return centre + A * q.x + D * q.y + N * q.z - Z * droop(q.x, q.y)
        k.add(lbox(Vector((-L, -0.05, -0.18)), Vector((L, S, 0.0)), fn), under, ao=False)
        n = max(3, round(S / course))
        for i in range(n):
            t0, t1 = S * i / n - (0.14 if i else 0.06), S * (i + 1) / n
            # Each course is a few pieces of uneven length, butt and thickness: hand-laid.
            cuts = [-L - rng.uniform(0.0, 0.08)]
            while cuts[-1] < L - 0.6:
                cuts.append(cuts[-1] + rng.uniform(1.1, 2.8))
            cuts[-1] = L + rng.uniform(0.0, 0.08)
            for a0, a1 in zip(cuts, cuts[1:]):
                jl, jr = rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05)
                thick = th * rng.uniform(0.8, 1.2)

                def warp(q, t0=t0, t1=t1, jl=jl, jr=jr, a0=a0, a1=a1, thick=thick):
                    f = (q.x - a0) / max(a1 - a0, 1e-3)
                    if q.y > t1 - 1e-4:
                        q.y += jl + (jr - jl) * f
                    if q.z > 1e-4:
                        # Wedge: thicker at the butt end, so each course reads as a step.
                        q.z = thick * (0.4 + 1.6 * (q.y - t0) / max(t1 - t0, 1e-3))
                    return q
                r = rng.random()
                c = jitter(color, rng, 0.06) if r > 0.2 else mul(color, rng.uniform(0.8, 0.88)) if r > 0.08 else mul(color, 1.12)
                k.add(lbox(Vector((a0 + 0.015, t0, 0.0)), Vector((a1 - 0.015, t1, 1.0)), fn, warp=warp), c, ao=False, vary=0)
        if barge:
            for e in (-1, 1):
                a0 = e * L
                k.add(lbox(Vector((min(a0, a0 + e * 0.16), -0.08, -0.22)), Vector((max(a0, a0 + e * 0.16), S + 0.04, th * 2.0)), fn), barge, ao=False)
    if cap and len(sides) == 2:
        def fc(q):
            return centre + A * q.x + C * q.y + Z * q.z - Z * droop(q.x, 0)
        k.add(lbox(Vector((-L - 0.12, -0.2, -0.05)), Vector((L + 0.12, 0.2, th * 2.6)), fc, bevel=0.05), mul(color, 0.7), ao=False)
    return p


def hip_roof(k, cx, cy, hx, hy, zw, zr, oh, color, course=0.55, lip=0.07, swap=False):
    """A hipped roof of stacked, stepped frustum courses (long axis X, or Y with swap)."""
    rng = k.rng
    if hx < hy:
        hx, hy, swap = hy, hx, not swap
    p = math.atan2(zr - zw, hy)
    ze = zw - oh * math.tan(p)
    ridge = hx - hy
    n = max(3, round((hy + oh) / math.cos(p) / course))

    def rect(f, grow, dz):
        ex = (hx + oh) + (ridge - hx - oh) * f + grow
        ey = max(0.03, (hy + oh) * (1 - f)) + grow
        z = ze + (zr - ze) * f + dz
        pts = [(-ex, -ey), (ex, -ey), (ex, ey), (-ex, ey)]
        return [Vector((cx + (y if swap else x), cy + (x if swap else y), z)) for x, y in pts]

    def frustum(b, t):
        bm = bmesh.new()
        vb = [bm.verts.new(v) for v in b]
        vt = [bm.verts.new(v) for v in t]
        bm.faces.new(vb)
        bm.faces.new(list(reversed(vt)))
        for i in range(4):
            j = (i + 1) % 4
            bm.faces.new([vb[i], vb[j], vt[j], vt[i]])
        return bm
    under = k.pal.get("under", (0.3, 0.2, 0.15))
    k.add(frustum(rect(0, -0.02, -0.16), rect(1, -0.02, -0.16)), under, ao=False)
    for i in range(n):
        f0, f1 = i / n, (i + 1) / n
        c = jitter(color, rng, 0.07) if rng.random() > 0.15 else mul(color, rng.uniform(0.82, 0.9))
        k.add(frustum(rect(f0, lip + rng.uniform(-0.02, 0.02), -0.04), rect(min(1, f1 + 0.02), 0, 0.02)), c, ao=False, vary=0)
    a, b = (Vector((cx - (0 if swap else ridge), cy - (ridge if swap else 0), zr)), Vector((cx + (0 if swap else ridge), cy + (ridge if swap else 0), zr)))
    if ridge > 0.1:
        k.add(cyl(a - (b - a).normalized() * 0.2, b + (b - a).normalized() * 0.2, 0.17, 0.17, 6), mul(color, 0.7), ao=False)
    return p


def cone_roof(k, c, r, zb, zt, color, oh=0.4, course=0.6, sides=14, lip=0.08, flare=0.0):
    """A conical roof of stepped courses from radius r(+oh) at zb to a point at zt."""
    rng = k.rng
    c = Vector(c)
    ze = zb
    S = math.hypot(r + oh, zt - ze)
    n = max(4, round(S / course))
    under = k.pal.get("under", (0.3, 0.2, 0.15))
    k.add(cyl(c + Z * (ze - 0.15), c + Z * (zt - 0.15), r + oh - 0.03, 0.02, sides), under, ao=False)
    for i in range(n):
        f0, f1 = i / n, min(1.0, (i + 1) / n + 0.03)
        # A slight bell curve: the lower courses flatten out.
        g = lambda f: f ** (1 - flare) if flare else f
        r0 = (r + oh) * (1 - g(f0)) + lip
        r1 = max(0.02, (r + oh) * (1 - g(f1)))
        z0, z1 = ze + (zt - ze) * f0 - 0.03, ze + (zt - ze) * f1
        cc = jitter(color, rng, 0.07) if rng.random() > 0.15 else mul(color, rng.uniform(0.82, 0.9))
        k.add(cyl(c + Z * z0, c + Z * z1, r0, r1, sides), cc, ao=False, vary=0)


# ---------------------------------------------------------------------------------------------
# Openings and wall details (human metres; giants and small folk scale whole models)


def window(k, f, a, z0, w, h, frame, lit=None, shutters=None, mullion=True, box_color=None, sill=True):
    rng = k.rng
    lit = rng.random() < 0.6 if lit is None else lit
    if lit:
        k.add(f.box(a - w / 2, a + w / 2, z0, z0 + h, -0.05, 0.03), None, glow=True)
    else:
        k.add(f.quad(a - w / 2, a + w / 2, z0, z0 + h, 0.03), k.pal["glass"], closed=False, ao=False)
    fw = 0.12
    k.add(f.box(a - w / 2 - fw, a + w / 2 + fw, z0 + h, z0 + h + fw * 1.2, 0.0, 0.12), frame)
    k.add(f.box(a - w / 2 - fw, a - w / 2, z0, z0 + h, 0.0, 0.1), frame)
    k.add(f.box(a + w / 2, a + w / 2 + fw, z0, z0 + h, 0.0, 0.1), frame)
    if sill:
        k.add(f.box(a - w / 2 - fw * 1.6, a + w / 2 + fw * 1.6, z0 - 0.1, z0 + 0.02, 0.0, 0.18), frame)
    if mullion:
        k.add(f.box(a - 0.035, a + 0.035, z0, z0 + h, 0.02, 0.07), frame)
        k.add(f.box(a - w / 2, a + w / 2, z0 + h * 0.58, z0 + h * 0.58 + 0.07, 0.02, 0.07), frame)
    if shutters:
        for e in (-1, 1):
            a0 = a + e * (w / 2 + fw + 0.02)
            a1 = a0 + e * w * 0.5
            k.add(f.box(min(a0, a1), max(a0, a1), z0 - 0.02, z0 + h + 0.02, 0.02, 0.08), shutters)
            k.add(f.box(min(a0, a1) + 0.04, max(a0, a1) - 0.04, z0 + h * 0.48, z0 + h * 0.52, 0.08, 0.1), mul(shutters, 0.75))
    if box_color and lit is not None:
        k.add(f.box(a - w / 2 - 0.05, a + w / 2 + 0.05, z0 - 0.32, z0 - 0.1, 0.05, 0.32), k.pal["timber"])
        for i in range(4):
            aa = a - w / 2 + (i + 0.5) * w / 4
            k.add(sphere(f.p(aa, z0 - 0.05, 0.2), 0.11, 0), jitter(box_color, rng, 0.1), ao=False)


def door(k, f, a, z0, w, h, color, frame, hood=None, arch=False):
    """A plank door with a frame and, from the floor level z0 down to the ground, steps."""
    rng = k.rng
    planks = 3 if w < 1.2 else 4
    for i in range(planks):
        a0 = a - w / 2 + i * w / planks
        k.add(f.box(a0 + 0.01, a0 + w / planks - 0.01, z0, z0 + h - (0.0 if not arch else 0.0), -0.04, 0.04 + rng.uniform(0, 0.015)), jitter(color, rng, 0.06), vary=0)
    if arch:
        n = 6
        pts = [(a + math.cos(math.pi * i / n) * w / 2, z0 + h + math.sin(math.pi * i / n) * w * 0.35) for i in range(n + 1)]
        k.add(f.poly(pts, -0.04, 0.05), color)
    fw = 0.16
    top = z0 + h + (w * 0.35 if arch else 0)
    k.add(f.box(a - w / 2 - fw, a - w / 2, z0, z0 + h, 0.0, 0.14), frame)
    k.add(f.box(a + w / 2, a + w / 2 + fw, z0, z0 + h, 0.0, 0.14), frame)
    k.add(f.box(a - w / 2 - fw * 1.4, a + w / 2 + fw * 1.4, top, top + 0.2, 0.0, 0.16), frame)
    k.add(f.box(a + w / 2 - 0.2, a + w / 2 - 0.12, z0 + h * 0.45, z0 + h * 0.5, 0.04, 0.1), k.pal["iron"], ao=False)
    k.add(f.box(a - w / 2 + 0.05, a + w / 2 - 0.05, z0 + h * 0.8, z0 + h * 0.83, 0.04, 0.07), k.pal["iron"], ao=False)
    steps = max(0, round(z0 / 0.18))
    for i in range(steps):
        zt = z0 - i * z0 / max(steps, 1)
        k.add(f.box(a - w / 2 - 0.25 - i * 0.08, a + w / 2 + 0.25 + i * 0.08, 0.0, zt, 0.0, 0.35 + i * 0.32, bevel=0.03), k.pal["stone"])
    if hood:
        c = f.p(a, top + 0.75, 0.25)
        gable_roof(k, c, f.n, 0.45, w / 2 + 0.25, top + 0.2, 0.18, 0.12, hood, course=0.35, th=0.07, sag=0.0)
        for e in (-1, 1):
            k.add(f.obox(a + e * (w / 2 + 0.2), top - 0.05, 0.6, 0.1, 0.05, 0.6, e * -0.7), frame)
    return top


def lantern(k, c, s=1.0):
    c = Vector(c)
    iron = k.pal["iron"]
    k.add(box(c + Vector((-0.12, -0.12, -0.18)) * s, c + Vector((0.12, 0.12, 0.18)) * s), None, glow=True)
    for dx in (-1, 1):
        for dy in (-1, 1):
            k.add(box(c + Vector((dx * 0.14 - 0.025, dy * 0.14 - 0.025, -0.2)) * s, c + Vector((dx * 0.14 + 0.025, dy * 0.14 + 0.025, 0.2)) * s), iron, ao=False)
    k.add(cyl(c + Vector((0, 0, 0.19)) * s, c + Vector((0, 0, 0.36)) * s, 0.22 * s, 0.03 * s, 4), iron, ao=False)
    k.add(box(c + Vector((-0.16, -0.16, -0.24)) * s, c + Vector((0.16, 0.16, -0.18)) * s), iron, ao=False)


# ---------------------------------------------------------------------------------------------
# Fantasy grammar (also giants)


def timber_storey(k, f, z0, z1, bays, openings, timber, braces=True):
    """Posts, rails and braces over a plaster storey. openings: per bay, None or (a, z0, w, h)."""
    rng = k.rng
    L = f.length
    tw, out = 0.17, 0.06
    k.add(f.box(-L / 2, L / 2, z0, z0 + 0.2, 0.0, out + 0.02), timber)
    k.add(f.box(-L / 2, L / 2, z1 - 0.22, z1, 0.0, out + 0.02), timber)
    edges = [-L / 2 + i * L / bays for i in range(bays + 1)]
    for i, e in enumerate(edges):
        a0 = e if i < bays else e - tw
        a0 = max(-L / 2, min(L / 2 - tw, a0 - (0 if i in (0, bays) else tw / 2)))
        k.add(f.box(a0, a0 + tw, z0, z1, 0.0, out), timber)
    if not braces:
        return
    for i in range(bays):
        a0, a1 = edges[i] + tw / 2, edges[i + 1] - tw / 2
        op = openings[i]
        if op is None:
            # A diagonal (or chevron) brace across a closed panel.
            h = z1 - z0 - 0.42
            if rng.random() < 0.5:
                ln = math.hypot(a1 - a0, h)
                ang = math.atan2(h, a1 - a0) * (1 if rng.random() < 0.5 else -1)
                k.add(f.obox((a0 + a1) / 2, (z0 + z1) / 2, ln, tw * 0.9, 0.0, out * 0.8, ang), timber)
            else:
                mid = (a0 + a1) / 2
                for e in (-1, 1):
                    ln = math.hypot((a1 - a0) / 2, h)
                    ang = math.atan2(h, (a1 - a0) / 2) * e
                    k.add(f.obox((mid + (a0 if e > 0 else a1)) / 2, (z0 + z1) / 2, ln, tw * 0.9, 0.0, out * 0.8, ang), timber)
        else:
            a, oz, w, h = op
            if oz - z0 > 0.6 and (a1 - a0) > w + 0.5:
                # Little braces under the window.
                for e in (-1, 1):
                    x0 = a + e * (w / 2 + 0.1)
                    xe = a1 if e > 0 else a0
                    ln = math.hypot(xe - x0, oz - z0 - 0.3)
                    ang = math.atan2(oz - z0 - 0.3, abs(xe - x0)) * (-e)
                    k.add(f.obox((x0 + xe) / 2, (z0 + 0.2 + oz - 0.1) / 2, ln, tw * 0.8, 0.0, out * 0.8, ang * -1), timber)


def stone_quoins(k, f, z0, z1, stone, size=0.36):
    rng = k.rng
    L = f.length
    z = z0
    i = 0
    while z < z1 - 0.1:
        h = min(size * rng.uniform(0.9, 1.1), z1 - z)
        ln = size * (1.6 if i % 2 else 1.0)
        for e in (-1, 1):
            a = e * L / 2
            k.add(f.box(min(a, a - e * ln), max(a, a - e * ln), z + 0.02, z + h - 0.02, -0.02, 0.05), jitter(stone, rng, 0.07), vary=0)
        z += h
        i += 1


def fantasy_house(k, H, town=False):
    rng, pal = k.rng, k.pal
    plaster = k.choice(pal["plaster"])
    timber = jitter(pal["timber"], rng, 0.08)
    stone = pal["stone"]
    roofc = k.choice(pal["roof"])
    paint = k.choice(pal["paint"])
    shut = k.choice(pal["paint"]) if rng.random() < 0.6 else None
    storeys = rng.choice([2, 2, 3]) if town else 1
    knee = 0.0 if town else rng.choice([0.0, 0.0, 0.8])
    plinth = rng.uniform(0.38, 0.5)
    hs = 2.75 if town else 3.0
    jetty = 0.4 if storeys >= 2 and rng.random() < 0.75 else 0.0
    stone_ground = rng.random() < (0.55 if town else 0.35)
    hip = town and rng.random() < 0.3
    ridge_x = hip or rng.random() < (0.55 if not town else 0.45)
    ridge = H - rng.uniform(0.45, 0.85)
    zw = plinth + storeys * hs + knee
    rise = ridge - zw
    pitch = math.radians(rng.uniform(52, 60))
    span = min(3.6 if not town else 3.5, max(2.2, rise / math.tan(pitch)))
    along = rng.uniform(5.4, 7.6) if not town else rng.uniform(5.0, 6.6)
    if ridge_x:
        W, D = along, 2 * (span - jetty)
    else:
        W, D = 2 * span, along - 2 * jetty
    hx, hy = W / 2, D / 2
    hyu = hy + jetty
    # Footprint parts: main box, maybe a front cross-wing or a side lean-to.
    wing = None
    if not town and ridge_x and not hip and rng.random() < 0.5:
        ww = rng.uniform(2.6, 3.2)
        wx = rng.choice([-1, 1]) * (hx - ww / 2 - rng.uniform(0.3, 0.8))
        wing = (wx, ww, rng.uniform(1.6, 2.2))
    lean = None
    if rng.random() < 0.45:
        lean = (rng.choice([-1, 1]), rng.uniform(1.6, 2.1), rng.uniform(0.55, 0.8) * D)
    # Plinth and storeys.
    k.add(box((-hx - 0.08, -hy - 0.08, 0), (hx + 0.08, hy + 0.08, plinth), 0.05), pal["stone_dark"])
    door_side = "front"
    for s in range(storeys):
        z0 = plinth + s * hs
        z1 = z0 + hs + (knee if s == storeys - 1 else 0)
        yy = hy if s == 0 else hyu
        mat = stone if (s == 0 and stone_ground) else plaster
        k.add(box((-hx, -yy, z0 - 0.02), (hx, yy, z1), 0.07), mat, vary=0.02)
        if s == 1 and jetty > 0:
            # Jetty: joist ends and a bressumer beam under the overhang.
            for e in (-1, 1):
                k.add(box((-hx, e * hyu - (0.2 if e > 0 else 0), z0 - 0.24), (hx, e * hyu + (0 if e > 0 else 0.2), z0)), timber)
                n = int(W / 0.65)
                for i in range(n):
                    x = -hx + (i + 0.5) * W / n
                    k.add(box((x - 0.08, min(e * hy, e * hyu), z0 - 0.4), (x + 0.08, max(e * hy, e * hyu), z0 - 0.24)), timber)
        faces = box_faces(0, 0, hx, yy)
        for name, f in faces.items():
            L = f.length
            if wing and name == "front" and s == 0:
                continue
            bays = max(1, round(L / 2.3))
            bw = L / bays
            door_bay = None
            if s == 0 and name == door_side:
                door_bay = rng.randrange(bays) if bays < 3 else bays // 2 + rng.choice([0, 0, -1, 1]) * (bays > 3)
            openings = []
            for i in range(bays):
                a = -L / 2 + (i + 0.5) * bw
                if i == door_bay:
                    openings.append("door")
                elif rng.random() < (0.8 if name in ("front", "back") else 0.55) and bw > 1.5:
                    w = min(0.9, bw - 0.7)
                    openings.append((a, z0 + 0.95, w, 1.15))
                else:
                    openings.append(None)
            if mat is stone:
                stone_quoins(k, f, z0, z1, mul(stone, 0.92))
            else:
                timber_storey(k, f, z0, z1, bays, [o if o != "door" else None for o in openings] if True else openings, timber, braces=True)
            for i, op in enumerate(openings):
                a = -L / 2 + (i + 0.5) * bw
                if op == "door":
                    door(k, f, a, plinth, 1.1, 2.15, paint, timber if mat is plaster else mul(stone, 0.85), hood=roofc if (not ridge_x and rng.random() < 0.6) else None, arch=mat is stone and rng.random() < 0.5)
                    if rng.random() < 0.5:
                        lantern(k, f.p(a + 0.95, plinth + 2.0, 0.28))
                elif op:
                    window(k, f, *op, frame=timber if mat is plaster else mul(stone, 0.88), shutters=shut,
                           box_color=k.choice([(0.9, 0.3, 0.35), (0.95, 0.75, 0.3), (0.85, 0.45, 0.8)]) if rng.random() < 0.25 else None)
    # Roof over the top storey.
    if hip:
        hip_roof(k, 0, 0, hx, hyu, zw, ridge, 0.5, roofc)
    elif ridge_x:
        gable_roof(k, (0, 0, ridge), X, hx, hyu, zw, 0.5, 0.35, roofc, barge=timber)
        gables = [Face((hx, 0, 0), Y, 2 * hyu), Face((-hx, 0, 0), -Y, 2 * hyu)]
    else:
        gable_roof(k, (0, 0, ridge), Y, hyu, hx, zw, 0.5, 0.35, roofc, barge=timber)
        gables = [Face((0, -hyu, 0), X, 2 * hx), Face((0, hyu, 0), -X, 2 * hx)]
    if not hip:
        for f in gables:
            half = f.length / 2
            pts = [(-half, zw - 0.02), (half, zw - 0.02), (0, ridge - 0.05)]
            k.add(f.poly(pts, -0.3, 0.0), plaster, vary=0.02)
            # King post, collar and a small attic window.
            k.add(f.box(-0.09, 0.09, zw, ridge - 0.25, 0.0, 0.06), timber)
            cz = zw + (ridge - zw) * 0.38
            cw = half * (1 - 0.38) - 0.1
            k.add(f.box(-cw, cw, cz, cz + 0.17, 0.0, 0.07), timber)
            for e in (-1, 1):
                ln = math.hypot(half - 0.1, ridge - zw) - 0.2
                ang = math.atan2(ridge - zw, half) * e
                k.add(f.obox(e * -half / 2, zw + (ridge - zw) / 2 - 0.08, ln, 0.17, 0.0, 0.06, ang), timber)
            if ridge - cz > 1.6 and rng.random() < 0.75:
                ww = min(0.7, cw * 0.5)
                for e in ((-1, 1) if cw > 1.6 and rng.random() < 0.5 else (0,)):
                    window(k, f, e * cw * 0.5, cz + 0.4, ww, 0.85, timber, mullion=False, sill=True)
    # Dormers on the front slope (cottages with a knee wall or a tall roof).
    if ridge_x and not hip and (knee > 0 or rise > 3.6):
        tanp = rise / hyu
        n = 1 if W < 6.4 else rng.choice([1, 2])
        xs = [rng.uniform(-0.6, 0.6)] if n == 1 else [-W / 4, W / 4]
        if wing:
            xs = [x for x in xs if abs(x - wing[0]) > wing[1] / 2 + 0.9] or []
        for xd in xs:
            yf = -hyu + 0.3
            zd0, zd1 = zw - 0.1, zw + 1.35
            zdr = zd1 + 0.75
            yb = -(ridge - zdr - 0.25) / tanp
            if yb <= yf + 0.4:
                continue
            k.add(box((xd - 0.75, yf, zd0), (xd + 0.75, yb, zd1)), plaster, vary=0.02)
            fd = Face((xd, yf, 0), X, 1.5)
            k.add(fd.poly([(-0.75, zd1 - 0.02), (0.75, zd1 - 0.02), (0, zdr - 0.03)], -0.25, 0.0), plaster)
            window(k, fd, 0, zd0 + 0.3, 0.75, 0.85, timber, shutters=None, sill=False)
            k.add(fd.box(-0.75, -0.6, zd0, zd1, 0.0, 0.06), timber)
            k.add(fd.box(0.6, 0.75, zd0, zd1, 0.0, 0.06), timber)
            gable_roof(k, (xd, (yf - 0.3 + yb) / 2, zdr), Y, (yb - yf + 0.3) / 2, 0.75, zd1, 0.22, 0.0, roofc, course=0.45, th=0.08, sag=0.0, barge=timber)
    # Front cross-wing: a one-storey gabled bay with its own lower ridge.
    if wing:
        wx, ww, wd = wing
        y0, y1 = -hy - wd, -hy + 0.05
        wz = plinth + hs
        mat = stone if stone_ground else plaster
        k.add(box((wx - ww / 2, y0, plinth - 0.02), (wx + ww / 2, y1, wz)), mat, vary=0.02)
        k.add(box((wx - ww / 2 - 0.08, y0 - 0.08, 0), (wx + ww / 2 + 0.08, y1, plinth), bevel=0.04), pal["stone_dark"])
        wr = wz + math.tan(pitch) * ww / 2
        wr = min(wr, ridge - 0.6)
        tanp = rise / hyu
        ym = -(ridge - wr) / tanp
        fw = Face((wx, y0, 0), X, ww)
        if mat is plaster:
            timber_storey(k, fw, plinth, wz, 1, [(0, plinth + 0.95, 0.9, 1.15)], timber)
        else:
            stone_quoins(k, fw, plinth, wz, mul(stone, 0.92))
        window(k, fw, 0, plinth + 0.95, 1.0, 1.2, timber if mat is plaster else mul(stone, 0.88), shutters=shut)
        k.add(fw.poly([(-ww / 2, wz - 0.02), (ww / 2, wz - 0.02), (0, wr - 0.05)], -0.3, 0.0), plaster)
        k.add(fw.box(-0.09, 0.09, wz, wr - 0.2, 0.0, 0.06), timber)
        gable_roof(k, (wx, (y0 + ym) / 2, wr), Y, (ym - y0) / 2, ww / 2, wz, 0.4, 0.3, roofc, barge=timber)
        # The main front still needs its door, beside the wing.
        f = Face((0, -hy, 0), X, W)
        free0, free1 = (-hx, wx - ww / 2) if wx > 0 else (wx + ww / 2, hx)
        if free1 - free0 > 3.0:
            # Door and a window side by side in the free stretch of front wall.
            da = free0 + (free1 - free0) * 0.32
            window(k, f, free0 + (free1 - free0) * 0.74, plinth + 0.95, 0.9, 1.15, timber, shutters=shut)
        else:
            da = (free0 + free1) / 2
        door(k, f, da, plinth, 1.1, 2.15, paint, timber, hood=None)
        if stone_ground:
            k.add(f.box(-hx, hx, plinth, plinth + hs, -0.01, 0.0), stone)
        else:
            timber_storey(k, f, plinth, plinth + hs, 1, [None], timber, braces=False)
    # Side lean-to shed.
    if lean:
        e, lw, ld = lean
        xw = e * hx
        y0 = rng.uniform(-hy, hy - ld)
        top_in = min(plinth + hs + 0.2, zw - 0.55 * math.tan(pitch) - 0.25) if not ridge_x else plinth + hs + 0.3
        top_out = top_in - lw * 0.55
        shed = jitter((0.52, 0.43, 0.33), rng, 0.06)
        k.add(box((min(xw, xw + e * lw), y0, 0), (max(xw, xw + e * lw), y0 + ld, top_out)), shed, vary=0)
        side = Face((xw + e * lw, y0 + ld / 2, 0), Y * e, ld)
        nb = max(2, int(ld / 0.35))
        for i in range(nb):
            a = -ld / 2 + (i + 0.5) * ld / nb
            k.add(side.box(a - ld / nb / 2 + 0.02, a + ld / nb / 2 - 0.02, 0.0, top_out - 0.05, 0.0, 0.05), jitter(shed, rng, 0.08), vary=0)
        gable_roof(k, (xw, y0 + ld / 2, top_in), Y, ld / 2, lw, top_out, 0.3, 0.25, roofc, sides=(-e,), course=0.5, sag=0.0, barge=timber)
        # A woodpile under the eave.
        if rng.random() < 0.6:
            fr = Face((xw + e * lw / 2, y0, 0), -X * e, lw)
            for r in range(3):
                for i in range(4 - r):
                    a = -0.6 + (i + 0.5 * r) * 0.32
                    k.add(cyl(fr.p(a, 0.15 + r * 0.26, 0.05), fr.p(a, 0.15 + r * 0.26, 0.75), 0.14, 0.14, 6), (0.55, 0.40, 0.26), ao=False)
    # Chimney: through the back slope or up the outside of a gable.
    cz_top = H
    if ridge_x and not hip and rng.random() < 0.45:
        e = rng.choice([-1, 1])
        if lean and lean[0] == e:
            e = -e
        cx = e * (hx + 0.5)
        cy = rng.uniform(-0.4, 0.4)
        k.add(box((cx - 0.55, cy - 0.6, 0), (cx + 0.55, cy + 0.6, zw + 0.3), bevel=0.06), stone)
        k.add(box((cx - 0.4, cy - 0.42, zw + 0.25), (cx + 0.4, cy + 0.42, cz_top - 0.3), bevel=0.05), stone)
        stack_c = Vector((cx, cy, 0))
        sw = 0.4
    else:
        ca = rng.uniform(-0.6, 0.6) * hx if not ridge_x else rng.choice([-1, 1]) * (hx - 1.0)
        cb = rng.uniform(0.5, 1.1) if ridge_x else rng.uniform(-0.6, 0.6) * hyu
        cx, cy = (ca, cb) if ridge_x else (rng.choice([-1, 1]) * rng.uniform(0.6, 1.1), ca * 0 + cb)
        k.add(box((cx - 0.4, cy - 0.4, zw - 0.6), (cx + 0.4, cy + 0.4, cz_top - 0.3), bevel=0.05), stone)
        stack_c = Vector((cx, cy, 0))
        sw = 0.4
    k.add(box(stack_c + Vector((-sw - 0.12, -sw - 0.12, cz_top - 0.42)), stack_c + Vector((sw + 0.12, sw + 0.12, cz_top - 0.2)), 0.04), mul(stone, 0.85))
    k.add(box(stack_c + Vector((-0.17, -0.17, cz_top - 0.25)), stack_c + Vector((0.17, 0.17, cz_top))), (0.62, 0.36, 0.25))
    # Hand-made lean: shear the whole building a little.
    lx, ly = rng.uniform(-0.012, 0.012), rng.uniform(-0.008, 0.008)
    for v in k.b.bm.verts:
        v.co.x += lx * v.co.z
        v.co.y += ly * v.co.z


def cyl_face(r, ang):
    """A Face tangent to a vertical cylinder of radius r at angle ang (0 = front, -Y)."""
    n = Vector((math.sin(ang), -math.cos(ang), 0))
    u = Vector((math.cos(ang), math.sin(ang), 0))
    return Face(n * r, u, 1.0)


def fantasy_tower(k, H):
    """A round or square stone watchtower with a jettied timber-frame room and a steep roof."""
    rng, pal = k.rng, k.pal
    stone, roofc, timber = pal["stone"], k.choice(pal["roof"]), pal["timber"]
    plaster = k.choice(pal["plaster"])
    round_ = rng.random() < 0.65
    r = (2.6 if H > 16 else 2.0) * rng.uniform(0.88, 1.15)
    room_h = 3.2
    roof_h = rng.uniform(0.28, 0.38) * H
    flare = rng.uniform(0.0, 0.45)
    zs = H - roof_h - room_h
    if round_:
        k.add(cyl((0, 0, 0), (0, 0, 1.1), r * 1.22, r * 1.12, 16, bevel=0.06), pal["stone_dark"])
        k.add(cyl((0, 0, 1.0), (0, 0, zs), r * 1.1, r, 16), stone, vary=0.02)
        z = 1.0 + rng.uniform(2.5, 3.5)
        while z < zs - 1.5:
            rr = r * 1.1 + (r - r * 1.1) * (z / zs)
            k.add(cyl((0, 0, z), (0, 0, z + 0.3), rr + 0.08, rr + 0.08, 16), mul(stone, 0.88))
            z += rng.uniform(3.0, 4.5)
        # Windows climb the shaft like a stair.
        ang = rng.uniform(-0.6, 0.6)
        z = 4.0
        while z < zs - 2.0:
            rr = r * 1.1 + (r - r * 1.1) * (z / zs)
            f = cyl_face(rr - 0.05, ang)
            window(k, f, 0, z, 0.45, 1.2, mul(stone, 0.85), lit=rng.random() < 0.5, mullion=False, sill=True)
            ang += rng.uniform(1.6, 2.4)
            z += rng.uniform(2.6, 3.4)
        fd = cyl_face(r * 1.1 - 0.15, 0)
        k.add(fd.box(-1.1, 1.1, 0.0, 3.4, 0.0, 0.35, bevel=0.05), mul(stone, 0.92))
        door(k, Face(fd.p(0, 0, 0.35), X, 2), 0, 0.36, 1.25, 2.3, k.choice(pal["paint"]), mul(stone, 0.8), arch=True)
        # Corbels under the jettied room.
        n = 16
        for i in range(n):
            a = i / n * math.tau
            f = cyl_face(r - 0.2, a)
            k.add(f.box(-0.22, 0.22, zs - 0.9, zs, 0.0, 0.75, bevel=0.04), mul(stone, 0.9), vary=0.05)
        R = r + rng.uniform(0.45, 0.85)
        k.add(cyl((0, 0, zs), (0, 0, zs + 0.25), R + 0.1, R + 0.1, 16), timber)
        k.add(cyl((0, 0, zs + 0.2), (0, 0, zs + room_h), R, R, 16), plaster, vary=0.02)
        k.add(cyl((0, 0, zs + room_h - 0.25), (0, 0, zs + room_h), R + 0.08, R + 0.08, 16), timber)
        nw = 8
        for i in range(nw):
            a = (i + 0.5) / nw * math.tau
            f = cyl_face(R - 0.04, a)
            k.add(f.box(-0.1, 0.1, zs + 0.2, zs + room_h, 0.0, 0.08), timber)
            f2 = cyl_face(R - 0.08, a + math.pi / nw)
            if i % 2 == 0:
                window(k, f2, 0, zs + 0.9, 0.7, 1.3, timber, mullion=True, sill=False)
            else:
                for e in (-1, 1):
                    k.add(f2.obox(0, zs + 1.6, 2.2, 0.15, 0.0, 0.1, 0.95 * e), timber)
        cone_roof(k, (0, 0, 0), R, zs + room_h, H - 1.0, roofc, oh=0.55, course=0.5, sides=16, flare=flare)
        if rng.random() < 0.55:
            # A stair turret against the shaft, with its own little cone.
            ta = rng.choice([-1, 1]) * rng.uniform(1.2, 2.0)
            d = Vector((math.sin(ta), -math.cos(ta), 0))
            rt_ = r * 0.45
            c = d * (r * 1.02)
            zt = zs * rng.uniform(0.55, 0.8)
            k.add(cyl(c, c + Z * zt, rt_ * 1.08, rt_, 10), mul(stone, 0.95), vary=0.02)
            for zz in (zt * 0.35, zt * 0.7):
                f = Face(c + d * rt_ * 0.98, Vector((math.cos(ta), math.sin(ta), 0)), 1)
                window(k, f, 0, zz, 0.32, 0.8, mul(stone, 0.85), lit=rng.random() < 0.5, mullion=False, sill=False)
            k.add(cyl(c + Z * (zt - 0.05), c + Z * (zt + 0.25), rt_ + 0.12, rt_ + 0.12, 10), mul(stone, 0.85))
            cone_roof(k, c, rt_, zt + 0.2, zt + 0.2 + rt_ * 2.6, roofc, oh=0.3, course=0.45, sides=10, flare=flare)
        if rng.random() < 0.6:
            # A hanging banner below the corbels.
            f = cyl_face(r + 0.02, rng.uniform(-0.4, 0.4))
            bc = k.choice(pal["paint"])
            bz = zs - 1.0
            k.add(f.poly([(-0.6, bz), (0.6, bz), (0.6, bz - 3.2), (0.0, bz - 2.7), (-0.6, bz - 3.2)], 0.0, 0.06), bc)
            k.add(f.box(-0.75, 0.75, bz - 0.08, bz + 0.05, 0.0, 0.12), pal["timber"])
            k.add(f.box(-0.5, 0.5, bz - 1.2, bz - 1.05, 0.06, 0.08), mul(bc, 1.6) if max(bc) < 0.6 else (0.95, 0.85, 0.5), ao=False)
    else:
        h = r * 1.05
        k.add(box((-h - 0.2, -h - 0.2, 0), (h + 0.2, h + 0.2, 1.1), 0.06), pal["stone_dark"])
        k.add(box((-h, -h, 1.0), (h, h, zs), 0.08), stone, vary=0.02)
        for f in box_faces(0, 0, h, h).values():
            stone_quoins(k, f, 1.0, zs, mul(stone, 0.9), size=0.5)
        faces = box_faces(0, 0, h, h)
        door(k, faces["front"], 0, 0.4, 1.25, 2.3, k.choice(pal["paint"]), mul(stone, 0.8), arch=True)
        z, side = 4.2, 0
        names = ["front", "right", "back", "left"]
        while z < zs - 2.0:
            window(k, faces[names[side % 4]], rng.uniform(-0.5, 0.5), z, 0.45, 1.2, mul(stone, 0.85), lit=rng.random() < 0.5, mullion=False)
            side += 1
            z += rng.uniform(2.4, 3.2)
        hr = h + 0.5
        for f in faces.values():
            for i in range(5):
                a = -h + (i + 0.5) * 2 * h / 5
                k.add(f.box(a - 0.14, a + 0.14, zs - 0.5, zs, 0.0, 0.5), timber)
        k.add(box((-hr, -hr, zs), (hr, hr, zs + room_h), 0.06), plaster, vary=0.02)
        for f in box_faces(0, 0, hr, hr).values():
            ops = [(0, zs + 0.9, 0.8, 1.2) if i == 1 else None for i in range(3)]
            timber_storey(k, f, zs, zs + room_h, 3, ops, timber)
            window(k, f, 0, zs + 0.9, 0.8, 1.2, timber, shutters=k.choice(pal["paint"]) if rng.random() < 0.5 else None)
        hip_roof(k, 0, 0, hr, hr, zs + room_h, H - 1.0, 0.55, roofc, course=0.5)
    # Finial and pennant.
    k.add(cyl((0, 0, H - 1.3), (0, 0, H), 0.06, 0.04, 6), pal["iron"], ao=False)
    k.add(sphere((0, 0, H - 1.05), 0.13, 1), pal.get("brass", (0.85, 0.65, 0.3)), ao=False)
    k.add(box((0.05, -0.02, H - 0.55), (0.75, 0.02, H - 0.15)), k.choice(pal["paint"]), ao=False)


def fantasy_wall(k, H):
    """One town-wall segment (4.7 m along X, outer face -Y): battered base, walk, merlons."""
    rng, pal = k.rng, k.pal
    stone, dark = (0.68, 0.66, 0.61), (0.52, 0.50, 0.47)
    moss = (0.40, 0.50, 0.28)
    L, T = 2.35, 1.0
    walk = H - 1.25

    def topped(c):
        def fn(co, n):
            m = 0.45 * max(0.0, 1 - co.z / 1.6)
            return mul(lerp(c, moss, m), (1.1 if n.z > 0.7 else 1.0) * (0.84 + 0.16 * min(1.0, co.z / 1.5)))
        return fn
    k.add(box((-L, -T - 0.3, 0), (L, T + 0.15, 0.9), 0.08), topped(dark))
    k.add(box((-L, -T, 0.8), (L, T, walk), 0.05), topped(stone))
    for f, density in ((Face((0, -T, 0), X, 2 * L), 3.2), (Face((0, T, 0), -X, 2 * L), 1.6)):
        z = 1.1
        while z < walk - 0.4:
            hh = rng.uniform(0.45, 0.6)
            for _ in range(int(density + rng.random())):
                ln = rng.uniform(0.6, 1.2)
                a = rng.uniform(-L + ln / 2, L - ln / 2)
                k.add(f.box(a - ln / 2, a + ln / 2, z, z + hh - 0.05, -0.02, rng.uniform(0.04, 0.1), bevel=0.05), topped(mul(stone, rng.choice([0.8, 0.86, 0.92, 1.06]))))
            z += hh
    # Outer parapet and merlons.
    k.add(box((-L, -T, walk - 0.05), (L, -T + 0.5, walk + 0.65), 0.04), topped(stone))
    for i, x in enumerate((-1.6, 0.0, 1.6)):
        k.add(box((x - 0.48, -T - 0.04, walk + 0.6), (x + 0.48, -T + 0.5, H - 0.12), 0.05), topped(jitter(stone, rng, 0.05)))
        k.add(box((x - 0.55, -T - 0.08, H - 0.15), (x + 0.55, -T + 0.56, H), 0.04), topped(mul(stone, 1.05)))
        if i == 1:
            k.add(Face((x, -T - 0.05, 0), X, 1).quad(-0.07, 0.07, walk + 0.8, H - 0.4, 0.0), (0.12, 0.12, 0.14), closed=False, ao=False)
    k.add(box((-L, T - 0.35, walk - 0.05), (L, T, walk + 0.45), 0.04), topped(stone))
    # Walkway paving.
    for i in range(5):
        x0 = -L + i * 2 * L / 5
        k.add(box((x0 + 0.02, -T + 0.5, walk - 0.08), (x0 + 2 * L / 5 - 0.02, T - 0.35, walk + 0.02 + rng.uniform(0, 0.03))), jitter(mul(stone, 1.05), rng, 0.06), vary=0, ao=False)
    v = rng.random()
    if v < 0.3:
        # A buttress on the town side.
        k.add(box((-0.6, T, 0), (0.6, T + 1.2, walk - 1.2), 0.06), topped(mul(stone, 0.95)))
        k.add(prism([(T + 1.2, walk - 1.2), (T, walk - 0.2), (T, walk - 1.2)], -0.6, 0.6, lambda a, s, z: Vector((a, s, z))), mul(stone, 0.95))
    elif v < 0.5:
        f = Face((0, T + 0.15, 0), -X, 1)
        k.add(f.box(-0.06, 0.06, 2.2, 2.9, 0.0, 0.4), pal["iron"])
        lantern(k, f.p(0, 2.55, 0.55), 1.1)


def market_stall(k, H):
    rng, pal = k.rng, k.pal
    wood = jitter(pal["timber"], rng, 0.1)
    cloth = k.choice([(0.82, 0.26, 0.22), (0.25, 0.46, 0.72), (0.28, 0.56, 0.36), (0.88, 0.66, 0.24), (0.56, 0.32, 0.62)])
    cream = (0.96, 0.93, 0.84)
    w, d = rng.uniform(1.1, 1.5), 0.55
    k.add(box((-w, -d, 0), (w, d, 0.95), 0.04), mul(wood, 1.25))
    for i in range(int(w * 2 / 0.3)):
        x = -w + (i + 0.5) * 0.3
        k.add(box((x - 0.13, -d - 0.04, 0.05), (x + 0.13, -d, 0.9)), jitter(mul(wood, 1.3), rng, 0.08), vary=0)
    k.add(box((-w - 0.08, -d - 0.12, 0.92), (w + 0.08, d + 0.05, 1.02), 0.02), mul(wood, 1.1))
    front, back = H - 0.5, H - 0.06
    for x in (-w, w):
        k.add(box((x - 0.06, -d - 0.06, 0), (x + 0.06, -d + 0.06, front)), wood)
        k.add(box((x - 0.06, d - 0.06, 0), (x + 0.06, d + 0.06, back)), wood)
    # Striped awning, sloping to the front, with a scalloped valance.
    y0, y1 = d + 0.15, -d - 0.6
    zb, zf = back, front - 0.05
    n = 6 if w < 1.3 else 8
    for i in range(n):
        x0 = -w - 0.2 + i * (2 * w + 0.4) / n
        x1 = x0 + (2 * w + 0.4) / n
        c = cloth if i % 2 == 0 else cream
        k.add(prism([(y0, zb), (y1, zf), (y1, zf + 0.06), (y0, zb + 0.06)], x0, x1, lambda a, s, z: Vector((a, s, z))), c, ao=False)
        for j in range(2):
            xa = x0 + j * (x1 - x0) / 2
            xb = xa + (x1 - x0) / 2
            k.add(prism([(xa, zf + 0.04), (xb, zf + 0.04), ((xa + xb) / 2, zf - 0.32)], y1 - 0.01, y1 + 0.02, lambda a, s, z: Vector((s, a, z))), c, ao=False)
    # Goods: crates of fruit, pots and bolts of cloth.
    x = -w + 0.15
    while x < w - 0.35:
        kind = rng.random()
        if kind < 0.5:
            cw = rng.uniform(0.4, 0.55)
            k.add(box((x, -d + 0.05, 1.02), (x + cw, -d + 0.5, 1.22)), mul(wood, 1.4))
            fc = k.choice([(0.85, 0.2, 0.18), (0.95, 0.6, 0.15), (0.55, 0.75, 0.25), (0.55, 0.25, 0.55)])
            for fx in range(3):
                for fy in range(2):
                    k.add(sphere((x + (fx + 0.5) * cw / 3, -d + 0.15 + fy * 0.22, 1.24), 0.085, 0), jitter(fc, rng, 0.08), ao=False)
            x += cw + 0.08
        elif kind < 0.8:
            for _ in range(2):
                pr = rng.uniform(0.09, 0.14)
                k.add(cyl((x + pr, -d + 0.3, 1.02), (x + pr, -d + 0.3, 1.02 + pr * 2.4), pr, pr * 0.7, 8), k.choice([(0.72, 0.42, 0.28), (0.42, 0.52, 0.62), (0.8, 0.75, 0.62)]))
                x += pr * 2 + 0.05
        else:
            cc = k.choice([(0.3, 0.4, 0.7), (0.8, 0.3, 0.3), (0.9, 0.8, 0.4)])
            k.add(cyl((x, -d + 0.25, 1.12), (x + 0.5, -d + 0.25, 1.12), 0.1, 0.1, 8), cc)
            x += 0.58
    # A barrel and a sack beside it.
    bx = w + 0.45
    barrel(k, (bx, 0.1, 0), 0.32, 0.8, wood)
    k.add(sphere((bx + 0.05, -0.5, 0.25), 0.3, 1, squash=0.85), (0.78, 0.68, 0.5), soft=Vector((bx + 0.05, -0.5, 0.25)))


def barrel(k, c, r, h, wood):
    c = Vector(c)
    k.add(cyl(c, c + Z * h * 0.25, r * 0.88, r, 10), mul(wood, 1.35))
    k.add(cyl(c + Z * h * 0.25, c + Z * h * 0.75, r, r, 10), mul(wood, 1.35))
    k.add(cyl(c + Z * h * 0.75, c + Z * h, r, r * 0.88, 10), mul(wood, 1.35))
    for z in (0.12, 0.88):
        rr = r * (0.95 if z < 0.5 else 0.95)
        k.add(cyl(c + Z * (h * z - 0.03), c + Z * (h * z + 0.03), rr + 0.015, rr + 0.015, 10), k.pal["iron"], ao=False)


def fantasy_lamp(k, H):
    rng, pal = k.rng, k.pal
    iron = pal["iron"]
    k.add(box((-0.28, -0.28, 0), (0.28, 0.28, 0.35), 0.05), pal["stone"])
    v = rng.random()
    wooden = rng.random() < 0.4
    top = H - 0.55 if v < 0.45 else H - 0.1
    if wooden:
        k.add(box((-0.09, -0.09, 0.3), (0.09, 0.09, top), 0.02), pal["timber"])
    else:
        k.add(cyl((0, 0, 0.3), (0, 0, 0.7), 0.14, 0.08, 8), iron)
        k.add(cyl((0, 0, 0.7), (0, 0, top), 0.07, 0.05, 8), iron)
    if v < 0.45:
        # Post-top lantern.
        lantern(k, (0, 0, H - 0.4 - 0.05), 1.3)
        return
    arms = [1] if v < 0.8 else [-1, 1]
    for e in arms:
        k.add(box((min(0, e * 0.75), -0.04, top - 0.35), (max(0, e * 0.75), 0.04, top - 0.25)), iron)
        k.add(Face((0, 0, 0), X, 1).obox(e * 0.25, top - 0.55, 0.55, 0.05, -0.03, 0.03, -e * 0.75), iron)
        k.add(box((e * 0.7 - 0.02, -0.02, top - 0.6), (e * 0.7 + 0.02, 0.02, top - 0.3)), iron)
        lantern(k, (e * 0.7, 0, top - 0.88), 1.2)
    k.add(sphere((0, 0, top), 0.1, 1), iron)


# ---------------------------------------------------------------------------------------------
# Steampunk


def gear(k, c, U, V, r, teeth, thick, color):
    N = U.cross(V)
    pts = []
    for i in range(teeth):
        a0 = i / teeth * math.tau
        for da, rr in ((-0.25, r * 0.8), (-0.13, r), (0.13, r), (0.25, r * 0.8)):
            a = a0 + da * math.tau / teeth
            pts.append((math.cos(a) * rr, math.sin(a) * rr))
    k.add(prism(pts, 0.0, thick, lambda w, s, z: c + U * s + V * z + N * w), color)
    k.add(cyl(c, c + N * (thick + 0.08), r * 0.3, r * 0.3, 8), mul(color, 0.8))
    # Spokes as a darker cross.
    for ang in (0, math.pi / 2):
        d = U * math.cos(ang) + V * math.sin(ang)
        e = U * -math.sin(ang) + V * math.cos(ang)
        k.add(lbox(Vector((-r * 0.72, -r * 0.08, thick)), Vector((r * 0.72, r * 0.08, thick + 0.04)), fn=lambda q, d=d, e=e: c + d * q.x + e * q.y + N * q.z), mul(color, 0.85))


def rivets(k, f, a0, a1, z, w, step=0.35, color=(0.3, 0.3, 0.32)):
    n = max(1, int((a1 - a0) / step))
    for i in range(n + 1):
        a = a0 + i * (a1 - a0) / n
        k.add(f.box(a - 0.04, a + 0.04, z - 0.04, z + 0.04, w, w + 0.05), color, ao=False, vary=0)


def arch_window(k, f, a, z0, w, h, frame, lit=None, bars=True):
    """A tall window with a round head, a brick arch of voussoirs and a stone sill."""
    rng = k.rng
    lit = rng.random() < 0.65 if lit is None else lit
    r = w / 2
    n = 8
    pts = [(a - r, z0), (a + r, z0)] + [(a + math.cos(math.pi * i / n) * r, z0 + h + math.sin(math.pi * i / n) * r) for i in range(n + 1)]
    pane = f.poly(pts, -0.05, 0.02)
    if lit:
        k.add(pane, None, glow=True)
    else:
        k.add(pane, k.pal["glass"], ao=False)
    if bars:
        for e in (-1, 1):
            k.add(f.box(a + e * r / 3 - 0.03, a + e * r / 3 + 0.03, z0, z0 + h + r * 0.9, 0.0, 0.06), k.pal["iron"], ao=False)
        for zz in (z0 + h * 0.35, z0 + h * 0.7, z0 + h):
            k.add(f.box(a - r, a + r, zz - 0.03, zz + 0.03, 0.0, 0.06), k.pal["iron"], ao=False)
    m = 7
    for i in range(m):
        a0, a1 = math.pi * i / m, math.pi * (i + 1) / m
        ro = r + (0.32 if i == m // 2 else 0.24)
        q = [(a + math.cos(a0) * (r + 0.02), z0 + h + math.sin(a0) * (r + 0.02)), (a + math.cos(a0) * ro, z0 + h + math.sin(a0) * ro),
             (a + math.cos(a1) * ro, z0 + h + math.sin(a1) * ro), (a + math.cos(a1) * (r + 0.02), z0 + h + math.sin(a1) * (r + 0.02))]
        k.add(f.poly(q, 0.0, 0.1 if i == m // 2 else 0.07), mul(frame, 1.08 if i == m // 2 else rng.uniform(0.92, 1.0)), vary=0)
    k.add(f.box(a - r - 0.15, a + r + 0.15, z0 - 0.16, z0, 0.0, 0.16), frame)


def pipe_run(k, pts, r, color, flange_every=1.6):
    pts = [Vector(p) for p in pts]
    for a, b in zip(pts, pts[1:]):
        k.add(cyl(a, b, r, r, 8), color, ao=False)
        L = (b - a).length
        n = int(L / flange_every)
        for i in range(1, n + 1):
            t = i / (n + 1)
            p = a + (b - a) * t
            d = (b - a).normalized() * 0.06
            k.add(cyl(p - d, p + d, r * 1.35, r * 1.35, 8), mul(color, 0.85), ao=False)
    for p in pts[1:-1]:
        k.add(sphere(p, r * 1.15, 1), mul(color, 0.92), ao=False)


def brick_fn(c, rng, band=None):
    """Brick colour with a soot gradient at the base and slight per-course variation."""
    def fn(co, n):
        course = math.floor(co.z / 0.3)
        k = 0.93 + 0.07 * ((course * 7919) % 5) / 4
        g = 0.78 + 0.22 * min(1.0, co.z / 1.4)
        return mul(c, k * g)
    return fn


def steampunk_house(k, H):
    rng, pal = k.rng, k.pal
    brick = k.choice(pal["brick"])
    stone, copper, iron, brass = pal["stone"], k.choice(pal["copper"]), pal["iron"], pal["brass"]
    paint = k.choice(pal["paint"])
    W, D = rng.uniform(6.2, 8.0), rng.uniform(6.0, 7.5)
    hx, hy = W / 2, D / 2
    plinth, g, s = 0.55, 3.4, 2.9
    ups = 2
    zw = plinth + g + ups * s
    k.add(box((-hx - 0.1, -hy - 0.1, 0), (hx + 0.1, hy + 0.1, plinth), 0.05), pal["stone_dark"])
    k.add(box((-hx, -hy, plinth - 0.02), (hx, hy, plinth + g), 0.05), stone, vary=0.02)
    k.add(box((-hx, -hy, plinth + g - 0.02), (hx, hy, zw), 0.05), brick_fn(brick, rng))
    faces = box_faces(0, 0, hx, hy)
    # Rusticated ground floor: horizontal grooves as slightly proud stone courses.
    for f in faces.values():
        z = plinth + 0.05
        while z < plinth + g - 0.2:
            k.add(f.box(-f.length / 2 + 0.02, f.length / 2 - 0.02, z, z + 0.5, 0.0, 0.04), jitter(stone, rng, 0.05), vary=0)
            z += 0.58
    for f in faces.values():
        # Stone string courses, an iron band with rivets, and a cornice.
        k.add(f.box(-f.length / 2 - 0.05, f.length / 2 + 0.05, plinth + g - 0.05, plinth + g + 0.25, 0.0, 0.18), stone)
        k.add(f.box(-f.length / 2 - 0.02, f.length / 2 + 0.02, plinth + g + s - 0.08, plinth + g + s + 0.18, 0.0, 0.08), iron)
        rivets(k, f, -f.length / 2 + 0.2, f.length / 2 - 0.2, plinth + g + s + 0.05, 0.08, 0.4, mul(iron, 1.4))
        k.add(f.box(-f.length / 2 - 0.2, f.length / 2 + 0.2, zw - 0.1, zw + 0.35, 0.0, 0.3, bevel=0.04), stone)
    front = faces["front"]
    door_a = rng.choice([-1, 1]) * (hx - 1.4)
    door(k, front, door_a, plinth, 1.2, 2.3, paint, mul(stone, 0.85))
    k.add(front.poly([(door_a + math.cos(math.pi * i / 6) * 0.6, plinth + 2.5 + math.sin(math.pi * i / 6) * 0.6) for i in range(7)], -0.04, 0.03), None, glow=True)
    # Shop window or two tall windows on the ground floor.
    span0, span1 = (-hx + 0.4, door_a - 1.0) if door_a > 0 else (door_a + 1.0, hx - 0.4)
    sw = span1 - span0
    sa = (span0 + span1) / 2
    k.add(front.box(sa - sw / 2, sa + sw / 2, plinth + 0.6, plinth + 2.8, -0.05, 0.04), None, glow=True)
    for i in range(4):
        a = sa - sw / 2 + i * sw / 3
        k.add(front.box(a - 0.06, a + 0.06, plinth + 0.6, plinth + 2.8, 0.0, 0.1), brass)
    k.add(front.box(sa - sw / 2 - 0.1, sa + sw / 2 + 0.1, plinth + 2.1, plinth + 2.18, 0.0, 0.1), brass)
    k.add(front.box(sa - sw / 2 - 0.15, sa + sw / 2 + 0.15, plinth + 2.8, plinth + 3.15, 0.0, 0.2), paint)
    k.add(front.box(sa - sw / 2 - 0.15, sa + sw / 2 + 0.15, plinth + 0.4, plinth + 0.6, 0.0, 0.25), mul(stone, 0.9))
    # Upper floors: tall windows with stone heads, maybe an oriel bay on the front.
    oriel = rng.random() < 0.55
    for name, f in faces.items():
        L = f.length
        bays = max(2, round(L / 2.1))
        for st in range(ups):
            z0 = plinth + g + st * s + 0.75
            for i in range(bays):
                a = -L / 2 + (i + 0.5) * L / bays
                if oriel and name == "front" and abs(a) < 1.3:
                    continue
                if name == "front" or rng.random() < 0.7:
                    arch_window(k, f, a, z0, 0.9, 1.35, stone, bars=False)
                    k.add(f.box(a - 0.06, a + 0.06, z0, z0 + 1.7, 0.0, 0.05), iron, ao=False)
        if name == "front" and not oriel:
            k.add(f.box(-L / 2 + 0.3, -L / 2 + 0.3, 0, 0, 0, 0), stone)
    if oriel:
        oz0, oz1 = plinth + g + 0.3, zw - 0.25
        k.add(box((-1.3, -hy - 0.8, oz0), (1.3, -hy, oz1), 0.05), copper)
        for zz in (oz0, oz1 - 0.1):
            k.add(box((-1.38, -hy - 0.88, zz - 0.1), (1.38, -hy, zz + 0.1)), brass)
        k.add(prism([(-hy - 0.8, oz0), (-hy, oz0), (-hy, oz0 - 0.9)], -1.3, 1.3, lambda a, s_, z: Vector((a, s_, z))), copper)
        fo = Face((0, -hy - 0.8, 0), X, 2.6)
        for st in range(ups):
            z0 = plinth + g + st * s + 0.75
            k.add(fo.box(-1.05, 1.05, z0, z0 + 1.5, -0.05, 0.03), None, glow=True)
            for a in (-1.05, -0.35, 0.35, 1.05):
                k.add(fo.box(a - 0.05, a + 0.05, z0, z0 + 1.5, 0.0, 0.08), brass)
        rivets(k, fo, -1.2, 1.2, oz0 + 0.3, 0.02, 0.3, brass)
    # Copper mansard with dormers, or a corner turret with a dome.
    zm0 = zw + 0.35
    top = H - 0.7
    inset = 1.0
    mans = [Vector((-hx - 0.05, -hy - 0.05, zm0)), Vector((hx + 0.05, -hy - 0.05, zm0)), Vector((hx + 0.05, hy + 0.05, zm0)), Vector((-hx - 0.05, hy + 0.05, zm0))]
    upper = [Vector((-hx + inset, -hy + inset, top)), Vector((hx - inset, -hy + inset, top)), Vector((hx - inset, hy - inset, top)), Vector((-hx + inset, hy - inset, top))]
    bm = bmesh.new()
    vb = [bm.verts.new(v) for v in mans]
    vt = [bm.verts.new(v) for v in upper]
    bm.faces.new(vb)
    bm.faces.new(list(reversed(vt)))
    for i in range(4):
        j = (i + 1) % 4
        bm.faces.new([vb[i], vb[j], vt[j], vt[i]])

    def copper_fn(co, n):
        # Vertical standing seams as stripes, verdigris lighter on top.
        stripe = 0.92 if int((co.x + co.y) / 0.45) % 2 else 1.0
        return mul(copper, stripe * (1.08 if n.z > 0.8 else 1.0))
    k.add(bm, copper_fn)
    k.add(box((-hx + inset - 0.1, -hy + inset - 0.1, top - 0.05), (hx - inset + 0.1, hy - inset + 0.1, top + 0.12)), brass)
    # Mansard dormers.
    slope_y = lambda z: -hy - 0.05 + (z - zm0) / (top - zm0) * (inset + 0.05)
    for xd in ([-W / 4, W / 4] if W > 6.8 else [0.0]):
        z0, z1 = zm0 + 0.25, zm0 + 1.65
        yf = slope_y(z0) - 0.15
        z1 = zm0 + 1.35
        k.add(box((xd - 0.55, yf, z0), (xd + 0.55, slope_y(z1) + 0.4, z1), 0.04), copper)
        fd = Face((xd, yf, 0), X, 1.1)
        arch_window(k, fd, 0, z0 + 0.15, 0.6, 0.6, brass, bars=False)
        hood = [(math.cos(math.pi * i / 8) * 0.68, z1 + math.sin(math.pi * i / 8) * 0.5) for i in range(9)]
        k.add(prism(hood, yf - 0.12, slope_y(z1 + 0.5) + 0.3, lambda a, s_, z, xd=xd: Vector((xd + s_, a, z))), mul(copper, 0.9))
    # Chimneys with copper pots, and a steam pipe down the side.
    for e in (-1, 1):
        if rng.random() < 0.75:
            cx = e * (hx - 0.8)
            k.add(box((cx - 0.45, -0.5, zw), (cx + 0.45, 0.5, H - 0.4), 0.04), brick_fn(mul(brick, 0.9), rng))
            k.add(box((cx - 0.55, -0.6, H - 0.5), (cx + 0.55, 0.6, H - 0.35)), stone)
            for dy in (-0.25, 0.25):
                k.add(cyl((cx, dy, H - 0.4), (cx, dy, H), 0.14, 0.17, 8), copper, ao=False)
    side = faces["right" if rng.random() < 0.5 else "left"]
    pa = rng.uniform(-0.6, 0.6) * side.length / 2
    pipe_run(k, [side.p(pa, 0.0, 0.25), side.p(pa, zw - 0.6, 0.25), side.p(pa, zw - 0.6, -0.1)], 0.12, copper)
    if rng.random() < 0.6:
        gear(k, front.p(door_a, plinth + 3.25, 0.02), X, Z, 0.55, 10, 0.12, brass)
    lx = door_a + (0.95 if door_a < 0 else -0.95)
    k.add(front.box(lx - 0.04, lx + 0.04, plinth + 2.1, plinth + 2.5, 0.0, 0.35), iron)
    lantern(k, front.p(lx, plinth + 2.0, 0.35))


def steampunk_factory(k, H):
    rng, pal = k.rng, k.pal
    brick = k.choice(pal["brick"])
    stone, copper, iron, brass, steel = pal["stone"], k.choice(pal["copper"]), pal["iron"], pal["brass"], pal["steel"]
    W, D = rng.uniform(14.0, 16.0), rng.uniform(9.5, 11.5)
    hx, hy = W / 2, D / 2
    zw = rng.uniform(7.2, 8.4)
    k.add(box((-hx - 0.15, -hy - 0.15, 0), (hx + 0.15, hy + 0.15, 0.6), 0.06), pal["stone_dark"])
    k.add(box((-hx, -hy, 0.55), (hx, hy, zw), 0.06), brick_fn(brick, rng))
    faces = box_faces(0, 0, hx, hy)
    for name, f in faces.items():
        L = f.length
        bays = max(2, round(L / 3.4))
        for i in range(bays + 1):
            a = -L / 2 + i * L / bays
            a = min(L / 2 - 0.3, max(-L / 2 + 0.3, a))
            k.add(f.box(a - 0.35, a + 0.35, 0.55, zw, 0.0, 0.25), brick_fn(mul(brick, 0.9), rng))
            k.add(f.box(a - 0.42, a + 0.42, zw - 0.5, zw - 0.2, 0.0, 0.32), stone)
        k.add(f.box(-L / 2 - 0.15, L / 2 + 0.15, zw - 0.2, zw + 0.3, 0.0, 0.35, bevel=0.04), stone)
        k.add(f.box(-L / 2, L / 2, 3.0, 3.3, 0.0, 0.1), iron)
        rivets(k, f, -L / 2 + 0.3, L / 2 - 0.3, 3.15, 0.1, 0.5, mul(iron, 1.5))
        big_door = None
        if name == "front":
            gear_at = None
            big_door = rng.randrange(bays)
        for i in range(bays):
            a = -L / 2 + (i + 0.5) * L / bays
            if i == big_door:
                # Sliding cargo door, braced, with a person-sized door beside it: the scale cue.
                dw, dh = min(3.6, L / bays - 1.0), 4.4
                k.add(f.box(a - dw / 2, a + dw / 2, 0.6, 0.6 + dh, -0.02, 0.08), k.choice(pal["paint"]))
                for e in (-1, 1):
                    ln = math.hypot(dw, dh / 2)
                    k.add(f.obox(a, 0.6 + dh * (0.25 if e > 0 else 0.75), ln, 0.16, 0.08, 0.14, math.atan2(dh / 2, dw) * e), iron)
                k.add(f.box(a - dw / 2 - 0.15, a + dw / 2 + 0.15, 0.6 + dh, 0.6 + dh + 0.25, 0.0, 0.2), iron)
                k.add(f.box(a - dw / 2 - 0.3, a + dw / 2 + 0.3, 0.6 + dh + 0.25, 0.6 + dh + 0.4, 0.0, 0.35), iron)
                for e in (-1, 1):
                    k.add(f.box(a + e * dw / 2 - 0.12, a + e * dw / 2 + 0.12, 0.6, 0.6 + dh, 0.0, 0.14), iron)
                k.add(f.box(a - dw / 2 - 0.2, a + dw / 2 + 0.2, 0.0, 0.6, 0.0, 1.4), mul(stone, 0.9))
                gear_at = (a, 0.6 + dh + 0.4 + 1.2)
                continue
            arch_window(k, f, a, 3.6, 1.6, 2.4, stone)
            if name == "front" and i == (big_door + 1) % bays:
                door(k, f, a, 0.6, 1.0, 2.15, k.choice(pal["paint"]), iron)
                lantern(k, f.p(a + 0.85, 2.6, 0.25))
            elif name in ("front", "back"):
                arch_window(k, f, a, 1.1, 1.2, 1.0, stone, bars=True)
    # Roof: a copper barrel vault or north-light sawtooth.
    if rng.random() < 0.5:
        rr = hy + 0.4
        n = 12
        prof = [(math.cos(math.pi * i / n) * rr, math.sin(math.pi * i / n) * rr * 0.55) for i in range(n + 1)]
        inner = [(x * 0.97, y * 0.97) for x, y in reversed(prof)]
        k.add(prism(prof + inner, -hx - 0.4, hx + 0.4, lambda a, s_, z: Vector((a, s_, zw + 0.25 + z))),
              lambda co, nn: mul(copper, 0.92 if int((co.x + 50) / 0.6) % 2 else 1.0))
        for i in range(6):
            x = -hx + (i + 0.5) * W / 6
            ring = [(math.cos(math.pi * j / n) * (rr + 0.08), math.sin(math.pi * j / n) * (rr * 0.55 + 0.08)) for j in range(n + 1)]
            k.add(prism(ring + [(x2 * 0.96, y2 * 0.96) for x2, y2 in reversed(ring)], x - 0.08, x + 0.08, lambda a, s_, z: Vector((a, s_, zw + 0.25 + z))), iron, ao=False)
        for e in (-1, 1):
            k.add(prism([(-rr, 0), (rr, 0)] + [(math.cos(math.pi * i / n) * rr, math.sin(math.pi * i / n) * rr * 0.55) for i in range(n, -1, -1)][1:-1], e * hx - 0.05, e * hx + 0.05, lambda a, s_, z: Vector((a, s_, zw + 0.25 + z))), brick_fn(brick, rng))
        gf = Face((0, -hy - 0.02, 0), X, W)
    else:
        teeth = 4
        tw = W / teeth
        for i in range(teeth):
            x0 = -hx + i * tw
            zt = zw + 2.4
            prof = [(x0, zw + 0.25), (x0 + tw, zw + 0.25), (x0 + tw, zt), (x0 + tw - 0.2, zt)]
            k.add(prism(prof, -hy - 0.3, hy + 0.3, lambda a, s_, z: Vector((s_, a, z))), lambda co, nn: mul(copper, 0.92 if int((co.y + 50) / 0.6) % 2 else 1.0))
            glaze = Face((x0 + tw + 0.01, 0, 0), Y, D)
            k.add(glaze.box(-hy, hy, zw + 0.5, zt - 0.2, -0.03, 0.02), None, glow=rng.random() < 0.7)
            for j in range(int(D / 1.2)):
                a = -hy + (j + 0.5) * D / int(D / 1.2)
                k.add(glaze.box(a - 0.05, a + 0.05, zw + 0.4, zt, 0.0, 0.06), iron, ao=False)
    # Smokestack at a back corner, with iron bands and a ladder.
    sx, sy = rng.choice([-1, 1]) * (hx - 1.8), hy + 1.2
    rb, rt = 1.15, 0.85
    k.add(box((sx - 1.5, sy - 1.5, 0), (sx + 1.5, sy + 1.5, 2.2), 0.06), pal["stone_dark"])
    k.add(cyl((sx, sy, 2.1), (sx, sy, H - 0.7), rb, rt, 12), brick_fn(brick, rng))
    z = 3.5
    while z < H - 1.5:
        rr = rb + (rt - rb) * (z - 2.1) / (H - 2.8)
        k.add(cyl((sx, sy, z), (sx, sy, z + 0.22), rr + 0.07, rr + 0.07, 12), iron, ao=False)
        z += 2.4
    k.add(cyl((sx, sy, H - 0.9), (sx, sy, H - 0.4), rt + 0.08, rt + 0.25, 12), stone)
    k.add(cyl((sx, sy, H - 0.4), (sx, sy, H), rt + 0.25, rt + 0.18, 12), (0.18, 0.16, 0.16), ao=False)
    # Pipes from the hall to the stack, a tank and a gear on the front.
    pipe_run(k, [(sx + 1.6, hy - 0.2, 1.0), (sx + 1.6, hy + 0.4, 1.0), (sx + 1.6, hy + 0.4, zw - 1.0), (sx + 0.4, sy, zw - 1.0)], 0.22, copper)
    if rng.random() < 0.6:
        tx = -sx * 0.9
        tz = 0.6
        k.add(box((tx - 1.6, -hy - 3.0, 0), (tx + 1.6, -hy - 0.2, tz), 0.04), pal["stone_dark"])
        k.add(cyl((tx, -hy - 0.4, tz + 1.2), (tx, -hy - 2.8, tz + 1.2), 1.2, 1.2, 12), lambda co, nn: mul(copper, 1.0))
        for yy in (-hy - 0.6, -hy - 1.6, -hy - 2.6):
            k.add(cyl((tx, yy - 0.06, tz + 1.2), (tx, yy + 0.06, tz + 1.2), 1.27, 1.27, 12), iron, ao=False)
        pipe_run(k, [(tx, -hy - 1.6, tz + 2.3), (tx, -hy - 1.6, tz + 3.2), (tx, -hy - 0.1, tz + 3.2)], 0.16, brass)
    gf = Face((0, -hy - 0.02, 0), X, W)
    ga, gz = gear_at
    gear(k, gf.p(ga, gz, 0.3), X, Z, 1.1, 12, 0.18, brass)
    gear(k, gf.p(ga + 1.45 * rng.choice([-1, 1]), gz + 0.55, 0.3), X, Z, 0.55, 8, 0.16, mul(copper, 1.1))


def steampunk_chimney(k, H):
    """A freestanding smokestack on a boiler-house base: a door, iron bands, a gallery and a
    ladder with rungs a person's step apart are the scale cues."""
    rng, pal = k.rng, k.pal
    brick, stone, iron = k.choice(pal["brick"]), pal["stone"], pal["iron"]
    sides = rng.choice([4, 8, 12, 12])
    rot = math.pi / 2 - math.pi / sides
    ap = math.cos(math.pi / sides)
    rb = rng.uniform(1.7, 2.1)
    rt = rb * rng.uniform(0.58, 0.7)
    base = rng.uniform(2.8, 3.4)
    bw = rb + 1.1
    k.add(box((-bw, -bw, 0), (bw, bw, base), 0.08), brick_fn(mul(brick, 0.9), rng))
    k.add(box((-bw - 0.15, -bw - 0.15, 0), (bw + 0.15, bw + 0.15, 0.5), 0.05), pal["stone_dark"])
    k.add(box((-bw - 0.2, -bw - 0.2, base - 0.1), (bw + 0.2, bw + 0.2, base + 0.25), 0.05), stone)
    f = Face((0, -bw, 0), X, 2 * bw)
    door(k, f, -0.6, 0.0, 1.0, 2.05, k.choice(pal["paint"]), iron, arch=True)
    arch_window(k, f, 1.1, 0.9, 0.8, 1.0, stone)
    top = H - 1.1

    def rad(z):
        return rb + (rt - rb) * (z - base) / (top - base)

    def soot(co, n):
        t = max(0.0, (co.z - (H - 4.5)) / 4.5)
        c = lerp(brick, (0.16, 0.14, 0.14), min(1.0, t * 0.95))
        course = math.floor(co.z / 0.3)
        return mul(c, 0.94 + 0.06 * ((course * 7919) % 5) / 4)

    def ring(z0, z1, r0, r1, color, **kw):
        bm = cyl((0, 0, z0), (0, 0, z1), r0, r1, sides)
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(rot, 3, "Z"))
        k.add(bm, color, **kw)
    ring(base, top, rb, rt, soot)
    z = base + rng.uniform(1.8, 2.4)
    while z < top - 1.0:
        rr = rad(z)
        ring(z, z + 0.25, rr + 0.08, rr + 0.08, iron, ao=False)
        z += rng.uniform(2.4, 3.2)
    # A gallery with railings part-way up.
    gz = rng.uniform(0.5, 0.65) * H
    gr = rad(gz) + 0.9
    k.add(cyl((0, 0, gz - 0.2), (0, 0, gz), gr, gr, 12), iron, ao=False)
    k.add(cyl((0, 0, gz - 0.6), (0, 0, gz - 0.2), rad(gz) + 0.1, gr - 0.1, 12), mul(iron, 1.2), ao=False)
    for i in range(16):
        a = i / 16 * math.tau
        k.add(cyl((math.cos(a) * (gr - 0.06), math.sin(a) * (gr - 0.06), gz), (math.cos(a) * (gr - 0.06), math.sin(a) * (gr - 0.06), gz + 1.0), 0.04, 0.04, 4), iron, ao=False)
    k.add(cyl((0, 0, gz + 0.95), (0, 0, gz + 1.05), gr, gr, 12), iron, ao=False)
    k.add(cyl((0, 0, gz + 0.95), (0, 0, gz + 1.06), gr - 0.12, gr - 0.12, 12), iron, ao=False)
    # Ladder up the front, rungs 0.35 m apart.
    z = base + 0.3
    while z < top - 0.6:
        y = -rad(z) * ap - 0.28
        k.add(box((-0.28, y - 0.03, z - 0.025), (0.28, y + 0.03, z + 0.025)), mul(iron, 1.5), ao=False)
        z += 0.35
    y0, y1 = -rad(base) * ap - 0.28, -rad(top) * ap - 0.28
    for e in (-1, 1):
        k.add(lbox(Vector((e * 0.28 - 0.035, -0.035, base)), Vector((e * 0.28 + 0.035, 0.035, top - 0.3)),
                   fn=lambda q: Vector((q.x, q.y + y0 + (y1 - y0) * (q.z - base) / (top - base), q.z))), mul(iron, 1.5), ao=False)
    # Corbelled crown.
    ring(top - 0.1, top + 0.35, rt + 0.05, rt + 0.35, stone)
    ring(top + 0.35, H - 0.25, rt + 0.35, rt + 0.3, soot)
    ring(H - 0.25, H, rt + 0.42, rt + 0.36, iron, ao=False)


def steampunk_pipe(k, H):
    rng, pal = k.rng, k.pal
    copper, brass, iron = k.choice(pal["copper"]), pal["brass"], pal["iron"]
    L = rng.uniform(2.2, 3.2)
    z = 1.15
    r = rng.uniform(0.2, 0.28)
    pipe_run(k, [(-L, 0, 0.0), (-L, 0, z), (L, 0, z), (L, 0, 0.0)] if rng.random() < 0.5 else [(-L, 0, z), (L, 0, z), (L, 0, 0.0)], r, copper, 1.3)
    for x in (-L * 0.45, L * 0.45):
        k.add(box((x - 0.25, -0.35, 0), (x + 0.25, 0.35, 0.2), 0.03), pal["stone_dark"])
        k.add(box((x - 0.07, -0.07, 0.2), (x + 0.07, 0.07, z - r)), iron)
        k.add(box((x - 0.12, -r - 0.04, z - r - 0.06), (x + 0.12, r + 0.04, z - r + 0.02)), iron)
    # A valve with a hand wheel on top, and a pressure gauge.
    vx = rng.uniform(-0.4, 0.4)
    k.add(cyl((vx, 0, z), (vx, 0, z + r + 0.35), 0.06, 0.06, 6), brass, ao=False)
    wz = z + r + 0.38
    rw = 0.3
    n = 8
    for i in range(n):
        a0, a1 = i / n * math.tau, (i + 1) / n * math.tau
        k.add(cyl((vx + math.cos(a0) * rw, math.sin(a0) * rw, wz), (vx + math.cos(a1) * rw, math.sin(a1) * rw, wz), 0.035, 0.035, 5), (0.7, 0.18, 0.15), ao=False)
    for i in range(3):
        a = i / 3 * math.tau
        k.add(cyl((vx, 0, wz), (vx + math.cos(a) * rw, math.sin(a) * rw, wz), 0.025, 0.025, 4), (0.7, 0.18, 0.15), ao=False)
    gx = vx + rng.choice([-1, 1]) * 0.9
    k.add(cyl((gx, 0, z + r), (gx, 0, z + r + 0.2), 0.04, 0.04, 6), brass, ao=False)
    k.add(cyl((gx, 0.06, z + r + 0.35), (gx, -0.06, z + r + 0.35), 0.17, 0.17, 10), brass, ao=False)
    k.add(cyl((gx, -0.06, z + r + 0.35), (gx, -0.075, z + r + 0.35), 0.13, 0.13, 10), (0.95, 0.92, 0.82), ao=False)
    # A steam vent plume stub up to the kind's height.
    k.add(cyl((L * 0.7, 0, z + r * 0.5), (L * 0.7, 0, H - 0.15), 0.08, 0.08, 6), copper, ao=False)
    k.add(cyl((L * 0.7, 0, H - 0.15), (L * 0.7, 0, H), 0.13, 0.16, 8), brass, ao=False)


def steampunk_crate(k, H):
    rng, pal = k.rng, k.pal
    wood = jitter(k.choice([(0.62, 0.46, 0.30), (0.54, 0.43, 0.32), (0.70, 0.56, 0.38)]), rng, 0.06)
    v = rng.random()
    if v < 0.5:
        s = 0.5
        w = rng.uniform(0.5, 0.75)
        k.add(box((-w, -s, 0), (w, s, 2 * s), 0.03), wood)
        for f in box_faces(0, 0, w, s).values():
            hl = f.length / 2
            for e in (-1, 1):
                k.add(f.box(e * hl - (0.12 if e > 0 else 0), e * hl + (0.12 if e < 0 else 0), 0.0, 2 * s, 0.0, 0.04), mul(wood, 0.8))
            for zz in (0.0, 2 * s - 0.12):
                k.add(f.box(-hl, hl, zz, zz + 0.12, 0.0, 0.03), mul(wood, 0.85))
            k.add(f.obox(0, s, math.hypot(2 * hl, 2 * s) - 0.3, 0.12, 0.0, 0.03, math.atan2(2 * s, 2 * hl) * rng.choice([-1, 1])), mul(wood, 0.85))
        for x in (-w, w):
            for y in (-s, s):
                for zz in (0.0, 2 * s - 0.14):
                    k.add(box((x - 0.07, y - 0.07, zz), (x + 0.07, y + 0.07, zz + 0.14)), pal["iron"], ao=False)
    elif v < 0.8:
        barrel(k, (0, 0, 0), 0.38, 1.0, mul(wood, 0.75))
        k.add(cyl((0, 0, 0.995), (0, 0, 1.0), 0.33, 0.33, 10), mul(wood, 0.9), ao=False)
    else:
        k.add(box((-0.55, -0.45, 0), (0.55, 0.45, 0.62), 0.03), wood)
        k.add(box((-0.3, -0.3, 0.62), (0.3, 0.3, 1.0), 0.03), mul(wood, 1.08))
        for zz in (0.25, 0.8):
            k.add(box((-0.56 if zz < 0.5 else -0.31, -0.46 if zz < 0.5 else -0.31, zz), (0.56 if zz < 0.5 else 0.31, 0.46 if zz < 0.5 else 0.31, zz + 0.06)), pal["iron"], ao=False)


def steampunk_lamp(k, H):
    rng, pal = k.rng, k.pal
    iron, brass = pal["iron"], pal["brass"]
    k.add(cyl((0, 0, 0), (0, 0, 0.35), 0.3, 0.24, 8), iron)
    k.add(cyl((0, 0, 0.35), (0, 0, 0.6), 0.16, 0.1, 8), iron)
    top = H - 0.75
    k.add(cyl((0, 0, 0.6), (0, 0, top), 0.08, 0.06, 8), iron)
    for z in (1.0, 2.2):
        k.add(cyl((0, 0, z), (0, 0, z + 0.1), 0.11, 0.11, 8), brass, ao=False)
    gear(k, Vector((0, -0.08, 1.6)), X, Z, 0.24, 8, 0.05, brass)
    arms = [0] if rng.random() < 0.5 else [-1, 1]
    for e in arms:
        cx = e * 0.55
        if e:
            k.add(box((min(0, cx), -0.04, top - 0.08), (max(0, cx), 0.04, top)), iron)
        gz = top + 0.05
        k.add(cyl((cx, 0, gz), (cx, 0, gz + 0.1), 0.18, 0.18, 8), brass, ao=False)
        k.add(sphere((cx, 0, gz + 0.32), 0.22, 1), None, glow=True)
        for i in range(4):
            a = i / 4 * math.tau + math.pi / 4
            k.add(cyl((cx + math.cos(a) * 0.2, math.sin(a) * 0.2, gz + 0.1), (cx + math.cos(a) * 0.2, math.sin(a) * 0.2, gz + 0.55), 0.02, 0.02, 4), brass, ao=False)
        k.add(cyl((cx, 0, gz + 0.52), (cx, 0, H - (0.0 if e == arms[-1] else 0.02)), 0.26, 0.03, 8), mul(k.choice(pal["copper"]), 1.0), ao=False)


# ---------------------------------------------------------------------------------------------
# Small folk (designed in human-equivalent metres, then scaled down to their height)


def burrow(k, H):
    rng, pal = k.rng, k.pal
    R = rng.uniform(3.4, 4.2)
    mh = H - rng.uniform(0.9, 1.3)
    grass = k.choice(pal["grass"])
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
    off = Vector((rng.random() * 50, rng.random() * 50, 0))
    front = -R * 0.62
    for v in bm.verts:
        d = noise.noise(v.co * 1.5 + off) * 0.06
        v.co = Vector((v.co.x * R * (1 + d), v.co.y * R * 0.9 * (1 + d), v.co.z * mh * (1 + d) - 0.15))
        if v.co.y < front:
            v.co.y = front + (v.co.y - front) * 0.08
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.6], context="VERTS")

    def turf(co, n):
        t = min(1.0, max(0.0, (n.z - 0.15) / 0.5))
        if co.y < front + 0.15:
            t *= 0.3
        return jitter(lerp(pal["earth"], grass, t), rng, 0.04)
    k.add(bm, turf, soft=Vector((0, R * 0.25, -mh * 0.4)), closed=False)
    # A stone-faced front with a round painted door and round windows.
    fy = front - 0.02
    f = Face((0, fy, 0), X, 2 * R)
    n = 14
    arch = [(math.cos(math.pi * i / n) * R * 0.78, 0.1 + math.sin(math.pi * i / n) * mh * 0.78) for i in range(n + 1)]
    k.add(f.poly([(R * 0.78, -0.05), (R * 0.78, 0.1)] + arch[1:-1] + [(-R * 0.78, 0.1), (-R * 0.78, -0.05)], -0.1, 0.12), pal["stone"], vary=0.03)
    dr = 1.05
    ring = [(math.cos(i / 16 * math.tau) * (dr + 0.25), dr + 0.15 + math.sin(i / 16 * math.tau) * (dr + 0.25)) for i in range(16)]
    k.add(f.poly(ring, 0.1, 0.3), pal["timber"])
    disc = [(math.cos(i / 16 * math.tau) * dr, dr + 0.15 + math.sin(i / 16 * math.tau) * dr) for i in range(16)]
    k.add(f.poly(disc, 0.12, 0.38), k.choice(pal["paint"]))
    k.add(sphere(f.p(0, dr + 0.15, 0.45), 0.13, 1), (0.9, 0.72, 0.3), ao=False)
    for e in (-1, 1):
        wa = e * R * 0.48
        wz = mh * 0.38
        k.add(f.poly([(wa + math.cos(i / 12 * math.tau) * 0.62, wz + math.sin(i / 12 * math.tau) * 0.62) for i in range(12)], 0.1, 0.24), pal["timber"])
        k.add(f.poly([(wa + math.cos(i / 12 * math.tau) * 0.45, wz + math.sin(i / 12 * math.tau) * 0.45) for i in range(12)], 0.12, 0.27), None, glow=rng.random() < 0.7)
        k.add(f.box(wa - 0.07, wa + 0.07, wz - 0.45, wz + 0.45, 0.24, 0.32), pal["timber"])
    # Doorstep path, a chimney poking out of the turf, and flowers.
    for i in range(3):
        sx = rng.uniform(-0.2, 0.2)
        k.add(cyl(f.p(sx, 0.0, -0.6 - i * 1.0), f.p(sx, 0.12, -0.6 - i * 1.0), 0.55, 0.5, 7), jitter(pal["stone"], rng, 0.08), ao=False)
    cx, cy = rng.uniform(-0.4, 0.4) * R, R * 0.2
    k.add(box((cx - 0.4, cy - 0.4, mh * 0.6), (cx + 0.4, cy + 0.4, H - 0.25), 0.06), pal["stone"])
    k.add(box((cx - 0.5, cy - 0.5, H - 0.3), (cx + 0.5, cy + 0.5, H), 0.04), mul(pal["stone"], 0.85))
    for _ in range(rng.randint(5, 9)):
        a = rng.uniform(0.3, math.pi - 0.3)
        x, y = math.cos(a) * R * 0.95, front - 0.2
        k.add(sphere((x, y - rng.uniform(0, 0.4), 0.25), 0.28, 0), k.choice([(0.95, 0.5, 0.6), (0.98, 0.85, 0.35), (0.7, 0.55, 0.95)]), ao=False)
    fx = rng.choice([-1, 1]) * R * 0.9
    for i in range(4):
        k.add(box((fx - 0.08, front - 0.6 - i * 0.9, 0), (fx + 0.08, front - 0.44 - i * 0.9, 1.0)), pal["timber"])
    k.add(box((fx - 0.05, front - 3.3, 0.7), (fx + 0.05, front - 0.4, 0.82)), pal["timber"])


def mushroom_cap(k, c, CR, ch, color, spots=(7, 11), droop=0.18):
    """A dome cap whose rim droops below its base, cream gills under it and white spots."""
    rng = k.rng
    c = Vector(c)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=1.0)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.05], context="VERTS")
    for v in bm.verts:
        z = max(0.0, v.co.z)
        v.co = c + Vector((v.co.x * CR, v.co.y * CR, z * ch - droop * (1 - z) * ch))
    k.add(bm, lambda co, n: mul(color, 0.9 + 0.14 * max(0, n.z)), soft=c - Z * ch * 0.3, closed=False)
    k.add(cyl(c - Z * (droop * ch + 0.15), c - Z * (droop * ch - 0.02), CR * 0.97, CR * 0.6, 16), mul(k.pal["cream"], 0.82), ao=False)
    for _ in range(rng.randint(*spots)):
        a = rng.uniform(0, math.tau)
        el = rng.uniform(0.2, 1.2)
        x, y = math.cos(a) * math.cos(el) * CR, math.sin(a) * math.cos(el) * CR
        z = math.sin(el) * ch - droop * (1 - math.sin(el)) * ch
        k.add(sphere(c + Vector((x, y, z)), rng.uniform(0.22, 0.4) * CR / 2.4, 1, squash=0.45), (0.97, 0.95, 0.9), ao=False)


def mushroom_house(k, H):
    rng, pal = k.rng, k.pal
    cap = k.choice(pal["cap"])
    sr = rng.uniform(1.25, 1.5)
    sh = 2.75
    k.add(cyl((0, 0, 0), (0, 0, sh), sr * 1.18, sr * 0.95, 14), lambda co, n: mul(pal["cream"], 0.8 + 0.2 * min(1.0, co.z / 1.5)))
    f = cyl_face(sr * 1.18 - 0.1, 0)
    door(k, Face(f.p(0, 0, 0.0), X, 2), 0, 0.2, 1.0, 1.75, k.choice(pal["paint"]), pal["timber"], arch=True)
    for a in (1.4, -1.5):
        wf = cyl_face(sr * 1.05, a)
        k.add(wf.poly([(math.cos(i / 10 * math.tau) * 0.42, 1.55 + math.sin(i / 10 * math.tau) * 0.42) for i in range(10)], 0.0, 0.14), pal["timber"])
        k.add(wf.poly([(math.cos(i / 10 * math.tau) * 0.3, 1.55 + math.sin(i / 10 * math.tau) * 0.3) for i in range(10)], 0.02, 0.17), None, glow=rng.random() < 0.75)
    top = H - 0.45
    ch = top - sh + 0.4
    mushroom_cap(k, (0, 0, sh - 0.4), rng.uniform(2.3, 2.7), ch, cap)
    cx = 1.0
    k.add(cyl((cx, 0.3, sh), (cx, 0.3, H - 0.25), 0.2, 0.2, 8), pal["iron"], ao=False)
    k.add(cyl((cx, 0.3, H - 0.25), (cx, 0.3, H), 0.32, 0.28, 8), pal["iron"], ao=False)
    lantern(k, (sr * 0.9, -sr * 0.85, 1.9), 1.1)
    for i in range(3):
        sx = rng.uniform(-0.15, 0.15)
        k.add(cyl((sx, -sr * 1.3 - 0.4 - i * 0.9, 0), (sx, -sr * 1.3 - 0.4 - i * 0.9, 0.1), 0.42, 0.38, 7), jitter(pal["stone"], rng, 0.08), ao=False)


def stump_house(k, H):
    rng, pal = k.rng, k.pal
    r = rng.uniform(1.9, 2.2)
    sh = rng.uniform(2.6, 2.9)

    def bark(co, n):
        # Vertical grooves (per face) and a darker foot.
        groove = 0.86 if int((math.atan2(n.y, n.x) + math.pi) / math.tau * 14) % 2 else 1.0
        return mul(pal["bark"], groove * (0.8 + 0.2 * min(1.0, co.z / 1.5)))
    k.add(cyl((0, 0, 0), (0, 0, 0.8), r * 1.3, r * 1.08, 14), bark)
    k.add(cyl((0, 0, 0.8), (0, 0, sh), r * 1.08, r, 14), bark)
    k.add(cyl((0, 0, sh - 0.02), (0, 0, sh + 0.12), r + 0.02, r - 0.05, 14), pal["heart"], ao=False)
    for i in range(6):
        a = i / 6 * math.tau + rng.uniform(-0.25, 0.25)
        if math.sin(a) < -0.6:
            continue
        d = Vector((math.cos(a), math.sin(a), 0))
        k.add(cyl(d * r * 0.95 + Z * 1.3, d * (r + 1.2) + Z * -0.15, 0.7, 0.2, 6), bark)
    f = cyl_face(r * 1.3 - 0.25, 0)
    door(k, Face(f.p(0, 0, 0), X, 2), 0, 0.2, 1.0, 1.75, k.choice(pal["paint"]), pal["timber"], arch=True)
    for a in (1.3, -1.3):
        wf = cyl_face(r * 1.08, a)
        window(k, wf, 0, 1.0, 0.55, 0.65, pal["timber"], mullion=True, sill=True, shutters=k.choice(pal["paint"]))
    # A small shingle cone on the cut top, leaving the growth rings showing, and a chimney.
    cone_roof(k, (0, 0, 0), r * 0.72, sh + 0.1, H - 0.3, k.choice(pal["roof"]), oh=0.3, course=0.4, sides=12, flare=0.2)
    cx = r * 0.45
    k.add(box((cx - 0.25, -0.25, sh), (cx + 0.25, 0.25, H), 0.04), pal["stone"])
    k.add(cyl((0, 0, H - 0.5), (0, 0, H), 0.05, 0.03, 5), pal["iron"], ao=False)


def small_house(k, H):
    v = k.rng.random()
    (burrow if v < 0.4 else mushroom_house if v < 0.75 else stump_house)(k, H)


def mushroom_tower(k, H):
    rng, pal = k.rng, k.pal
    caps = [k.choice(pal["cap"]) for _ in range(3)]
    sh = H * 0.72
    sr = 1.3
    k.add(cyl((0, 0, 0), (0, 0, sh), sr * 1.35, sr, 14), lambda co, n: mul(pal["cream"], 0.82 + 0.18 * min(1.0, co.z / 2.0)))
    f = cyl_face(sr * 1.35 - 0.1, 0)
    door(k, Face(f.p(0, 0, 0), X, 2), 0, 0.2, 1.05, 1.85, k.choice(pal["paint"]), pal["timber"], arch=True)
    z, ang = 3.0, 0.8
    while z < sh - 1.5:
        rr = sr * 1.35 + (sr - sr * 1.35) * z / sh
        wf = cyl_face(rr - 0.05, ang)
        k.add(wf.poly([(math.cos(i / 10 * math.tau) * 0.42, z + math.sin(i / 10 * math.tau) * 0.42) for i in range(10)], 0.0, 0.12), pal["timber"])
        k.add(wf.poly([(math.cos(i / 10 * math.tau) * 0.3, z + math.sin(i / 10 * math.tau) * 0.3) for i in range(10)], 0.02, 0.15), None, glow=rng.random() < 0.7)
        ang += 2.1
        z += 1.6
    # Shelf caps up the side, a big top cap.
    for i, (z, cr) in enumerate(((sh * 0.42, 1.6), (sh * 0.68, 1.3))):
        a = rng.uniform(0, math.tau)
        c = Vector((math.cos(a) * sr * 0.95, math.sin(a) * sr * 0.95, z))
        k.add(sphere(c, cr, 2, squash=0.28), caps[i + 1], soft=c - Z * 0.5)
    CR = sr * 2.6
    ch = H - sh + 0.4
    mushroom_cap(k, (0, 0, sh - 0.4), CR, ch, caps[0], spots=(8, 12), droop=0.2)
    # A balcony ring under the cap.
    bz = sh - 1.6 - 0.2 * ch
    k.add(cyl((0, 0, bz - 0.2), (0, 0, bz), sr * 2.0, sr * 2.0, 14), pal["timber"])
    for i in range(14):
        a = i / 14 * math.tau
        k.add(cyl((math.cos(a) * sr * 1.9, math.sin(a) * sr * 1.9, bz), (math.cos(a) * sr * 1.9, math.sin(a) * sr * 1.9, bz + 0.9), 0.06, 0.06, 4), pal["timber"], ao=False)
    k.add(cyl((0, 0, bz + 0.85), (0, 0, bz + 1.0), sr * 1.95, sr * 1.95, 14), pal["timber"])
    k.add(cyl((0, 0, bz + 0.83), (0, 0, bz + 1.02), sr * 1.85, sr * 1.85, 14), pal["timber"])


def small_tower(k, H):
    if k.rng.random() < 0.5:
        mushroom_tower(k, H)
    else:
        fantasy_tower(k, H)


def convex_hull(pts):
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in pts))
    if len(pts) < 3:
        return pts

    def half(ps):
        out = []
        for p in ps:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out
    lo, hi = half(pts), half(reversed(pts))
    return lo[:-1] + hi[:-1]


def foundation(k, depth):
    """A stepped stone foundation under the model's ground outline (the convex hull of
    everything touching the ground), from the floor down `depth`: courses widen a little
    downward, like a footing, so a slope shows stonework rather than a gap."""
    pts = [(v.co.x, v.co.y) for v in k.b.bm.verts if v.co.z <= 0.05]
    hull = convex_hull(pts)
    if len(hull) < 3:
        return
    cx = sum(p[0] for p in hull) / len(hull)
    cy = sum(p[1] for p in hull) / len(hull)

    def grown(d):
        out = []
        for x, y in hull:
            dx, dy = x - cx, y - cy
            l = max(math.hypot(dx, dy), 1e-6)
            out.append((x + dx / l * d, y + dy / l * d))
        return out
    stone = k.pal.get("stone_dark", k.pal.get("stone", (0.55, 0.52, 0.48)))
    courses = max(2, round(depth / 0.6))
    for i in range(courses):
        z1 = -0.01 - i * depth / courses
        z0 = -0.01 - (i + 1) * depth / courses
        ring = grown(0.05 + 0.06 * i)
        bm = bmesh.new()
        bot = [bm.verts.new((x, y, z0)) for x, y in ring]
        top = [bm.verts.new((x, y, z1)) for x, y in ring]
        bm.faces.new(bot[::-1])
        bm.faces.new(top)
        n = len(ring)
        for a in range(n):
            b = (a + 1) % n
            bm.faces.new([bot[a], bot[b], top[b], top[a]])
        shade = 0.92 - 0.06 * i + (0.04 if i % 2 else 0.0)
        k.add(bm, mul(stone, shade), ao=False, vary=0.03)


def well(k, H):
    """A stone draw-well with a little gabled roof on two posts, a windlass and a bucket."""
    rng, pal = k.rng, k.pal
    stone, timber = pal["stone"], pal["timber"]
    roofc = k.choice(pal["roof"])
    r = rng.uniform(0.85, 1.0)
    k.add(cyl((0, 0, 0), (0, 0, 0.85), r, r * 0.96, 14, bevel=0.04), stone, vary=0.03)
    k.add(cyl((0, 0, 0.82), (0, 0, 0.95), r + 0.1, r + 0.08, 14), mul(stone, 0.88))
    k.add(cyl((0, 0, 0.55), (0, 0, 0.62), r - 0.12, r - 0.12, 14), (0.10, 0.15, 0.20), ao=False)
    top = H - 0.9
    for e in (-1, 1):
        x = e * (r + 0.02)
        k.add(box((x - 0.09, -0.09, 0.0), (x + 0.09, 0.09, top)), timber)
        k.add(box((x - 0.14, -0.14, 0.0), (x + 0.14, 0.14, 0.3)), mul(stone, 0.85))
    wz = top - 0.75
    k.add(cyl((-r - 0.1, 0, wz), (r + 0.1, 0, wz), 0.09, 0.09, 8), mul(timber, 1.2))
    k.add(box((r + 0.1, -0.03, wz - 0.03), (r + 0.16, 0.03, wz + 0.35)), pal["iron"], ao=False)
    k.add(box((r + 0.1, -0.03, wz + 0.3), (r + 0.4, 0.03, wz + 0.36)), pal["iron"], ao=False)
    bz = wz - rng.uniform(0.7, 1.1)
    k.add(cyl((0, 0, bz + 0.3), (0, 0, wz), 0.015, 0.015, 4), (0.75, 0.66, 0.48), ao=False)
    barrel(k, (0, 0, bz), 0.16, 0.3, timber)
    gable_roof(k, (0, 0, H), X, r + 0.15, 0.75, top, 0.3, 0.2, roofc, course=0.35, th=0.07, sag=0.02, barge=timber)


KINDS = {
    ("fantasy", "house"): lambda k, H: fantasy_house(k, H),
    ("fantasy", "townhouse"): lambda k, H: fantasy_house(k, H, town=True),
    ("fantasy", "tower"): fantasy_tower,
    ("fantasy", "wall"): fantasy_wall,
    ("fantasy", "market_stall"): market_stall,
    ("fantasy", "lamp"): fantasy_lamp,
    ("steampunk", "house"): steampunk_house,
    ("steampunk", "factory"): steampunk_factory,
    ("steampunk", "chimney"): steampunk_chimney,
    ("steampunk", "pipe"): steampunk_pipe,
    ("steampunk", "crate"): steampunk_crate,
    ("steampunk", "lamp"): steampunk_lamp,
    ("giant", "house"): lambda k, H: fantasy_house(k, H),
    ("giant", "tower"): fantasy_tower,
    ("giant", "lamp"): fantasy_lamp,
    ("small", "house"): small_house,
    ("small", "tower"): small_tower,
    ("fantasy", "well"): well,
    ("giant", "well"): well,
    ("small", "well"): well,
}

# Who lives there: generators work in metres for a 1.75 m person, and the result is scaled to
# the kind's height, so a giant's door is 5/1.75 times a person's and a small folk's 0.6/1.75.
STYLE_FOLK = {"fantasy": "human", "steampunk": "human", "giant": "giant", "small": "small"}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", choices=sorted(PALETTES))
    ap.add_argument("--kind")
    ap.add_argument("--table", help="write the footprint table (JSON) the settlement planner reads, and exit")
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out")
    ap.add_argument("--profile", action="store_true", help="print triangles per generator function")
    a = ap.parse_args(argv)
    global PROFILE
    if a.table:
        kinds = []
        for (style, kind), H in sorted(HEIGHTS.items()):
            scale = FOLK[STYLE_FOLK[style]] / FOLK["human"]
            w, d = ENVELOPES[(style, kind)]
            kinds.append({"style": style, "kind": kind, "width_m": w, "depth_m": d, "height_m": round(H, 3),
                          "foundation_m": round(FOUNDATION.get(kind, FOUNDATION_DEFAULT) * scale, 3)})
        with open(a.table, "w") as f:
            json.dump({"note": "Written by living/tools/blender/buildings.py --table (gen_buildings.sh). Envelope of every "
                       "model of a kind: width along the front, depth front to back, height above the floor; "
                       "foundation depth below the floor.", "kinds": kinds}, f, indent=1)
            f.write("\n")
        print(f"TABLE {a.table} {len(kinds)} kinds")
        return
    if not (a.style and a.kind and a.out):
        sys.exit("--style, --kind and --out are required unless --table is given")
    if (a.style, a.kind) not in KINDS:
        sys.exit(f"unknown kind {a.kind} for style {a.style}; known: {sorted(KINDS)}")
    os.makedirs(a.out, exist_ok=True)
    H = HEIGHTS[(a.style, a.kind)]
    # Design height, in metres for a 1.75 m person.
    Hd = H * FOLK["human"] / FOLK[STYLE_FOLK[a.style]]
    for i in range(a.count):
        reset()
        rng = random.Random(a.seed * 1000 + i)
        PROFILE = {} if a.profile else None
        k = Kit(rng, PALETTES[a.style], ao=1.2)
        KINDS[(a.style, a.kind)](k, Hd)
        foundation(k, FOUNDATION.get(a.kind, FOUNDATION_DEFAULT))
        obj, s = k.b.finish(f"{a.kind}_{a.style}_{i:02d}", H)
        tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
        dims = obj.dimensions
        path = os.path.join(a.out, f"gen-{a.kind}-{a.style}-{i:02d}.glb")
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_vertex_color="ACTIVE", export_normals=True, export_yup=True, use_selection=False)
        print(f"GEN {path} tris={tris} size={dims.x:.2f}x{dims.y:.2f}x{dims.z:.2f} fit=x{s * Hd / H:.3f}")
        # Lots are centred on the origin: the footprint is twice the farthest reach from it.
        fw = 2 * max(abs(v.co.x) for v in obj.data.vertices)
        fd = 2 * max(abs(v.co.y) for v in obj.data.vertices)
        print(f"FOOT {a.style} {a.kind} {fw:.3f} {fd:.3f} below={-min(v.co.z for v in obj.data.vertices):.2f}")
        env = ENVELOPES.get((a.style, a.kind))
        if env and (fw > env[0] + 1e-3 or fd > env[1] + 1e-3):
            print(f"WARN {path} footprint {fw:.2f}x{fd:.2f} exceeds the envelope {env[0]}x{env[1]}")
        if PROFILE:
            print("  " + " ".join(f"{n}={t}" for n, t in sorted(PROFILE.items(), key=lambda x: -x[1])))


main()
