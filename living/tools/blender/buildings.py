"""Stylized building generator for the game client's test-environment cities.

Run headless:
    blender -b -P living/tools/blender/buildings.py -- --style fantasy --kind house --count 8 --out DIR

Styles and kinds (KINDS and FORM_KINDS):
- fantasy: houses (cottage, house, longhouse, L-house, corner house), townhouses (narrow, wide,
  corner), inn, guildhall, chapel, workshop (smithy, workshop), barn (barn, shed), tower, wall,
  market_stall, lamp, well: timber frame and plaster on stone, steep stepped-shingle roofs
  (gable, hip, half-hip, cross gables), jetties, dormers, lean-tos, chimneys, lit windows;
- steampunk: house (narrow, wide, corner with a domed turret), inn (pub), hall (exchange: portico,
  pediment clock, copper dome), clocktower (the landmark), mast (an airship mooring mast, often
  with a small airship moored), works (foundry, gearworks), arcade (iron and glass market
  arcade), factory, chimney, pipe, crate, lamp (gas lamps and brass globes): brick, riveted metal
  bands, copper mansards and domes, pipes, gears, smokestacks;
- cyberpunk: block (narrow, wide, corner: stacked mid-rise storeys with setbacks), tower
  (slender), landmark (a megatower with a halo crown and spire), market (food court), workshop
  (garage, fab), neon_sign, billboard (holo screens on legs), cable (a bundle strung between two
  buildings, along Y, hanging from brackets at its height), kiosk (vending machines or a booth),
  food_stall, walkway (a raised walkway with stairs and a canopy), lamp, crate: grimy concrete
  storeys with slab bands and glazed bays, rolled shutters and lit shopfronts, neon blade signs
  and boards of glowing characters, holo-billboards, rooftop tanks, antennas and dishes, AC
  boxes, fire escapes and hanging cables; chunky, read from the game camera;
- giant: houses and a longhall in the fantasy grammar for 5 m giants (doors ~6 m), tower, lamp,
  well;
- small: burrows, big mounds, mushroom and stump houses, a mushroom hall, tower, well for 0.6 m
  small folk.
- street props (PROPS, PROP_STYLES), placed by the settlement planner's ornaments
  (`living/rules/src/settle/ornament.rs`): barrel, crate, cart, bench, fountain, market_cross
  (a clock pillar in steampunk, an info pylon in cyberpunk), fence (2, 3 and 4 m sections),
  gate, planter, flower_box, sign (shop sign, signpost), banner, washing_line (between posts, or
  spans of 3, 4.5 and 6 m to string between houses), tree (street, garden), kerb (4 m), stairs
  (a flight rising 3 m over 5 m between terraces) and retaining_wall (4 m holding 1.5 or 3 m);
  fantasy, steampunk and cyberpunk looks, and the fantasy look scaled for giants and small folk.

Conventions (as nature.py): metres, origin at the floor centred on the footprint, +Z up in
Blender (+Y in glTF), fronts face -Y in Blender (+Z in glTF, the asset view's "front"). Colour is
per-vertex ("Color", exported as COLOR_0) on a white "Body" material so the game's toon material
does the shading; lit windows and lamps use a "Glow" material with emission, and neon a
material per colour ("GlowPink", "GlowCyan", "GlowAmber", "GlowRed", "GlowWhite"), because the
game takes a glowing part's emission from its material. Generators work in
metres for a 1.75 m person, and the result is scaled by the inhabitants' height (FOLK), so doors
stay door-sized.

Reading at game distance: windows, doors and shopfronts in storeyed blocks sit RECESS back in
holes cut through the wall (wall_skin), with lit or shadowed reveals; roofs have thick decks,
heavy eave and barge boards, a big ridge cap and courses that darken towards their butts; ridges
sag and wave and chimneys lean and kink a little; plinths carry a paler capping course. That
hand-made detail draws from a separate detail stream (Kit.pr, Kit.extra), so it never changes a
model's design, and with it its footprint in the settlement table.

Heights: a kind in KINDS is scaled to exactly its HEIGHTS entry (the environment slots use the
same number). A kind in FORM_KINDS comes in forms (size classes and shapes) whose storeys, plan
and roof vary per model; it keeps its designed size and its height is measured.

Foundations: below the floor every model has a stepped stone foundation under its whole ground
outline, about 1.8 m deep for a person's house (FOUNDATION, scaled with the inhabitants: about
5 m for giants, 0.6 m for small folk), so on a slope it reaches down into the ground instead of
floating; on flat ground it is hidden. The settlement planner (`living/rules/src/settle.rs`)
levels each lot to the floor.

Footprints: each run writes `gen-<kind>-<style>.json` beside its models with every model's form,
footprint (width along the front, depth front to back, roof overhangs, steps and yards included),
height, foundation depth and triangles. `--table PATH --envs ROOT` gathers them into the JSON the
planner reads (`living/rules/data/buildings.json`): every model with its file under `envs/`,
plus each kind's envelope; `gen_buildings.sh` refreshes it.
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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "textures"))
from surfaces import alpha as surface_alpha  # noqa: E402

PROFILE = None  # --profile: triangles per generator function
UNTAGGED = None  # --profile: untagged lit triangles (no painted surface) per generator function

X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))

# Inhabitant heights: everything is designed around the door its folk need.
FOLK = {"human": 1.75, "giant": 5.0, "small": 0.6}

# Exact model height (m) per fixed (style, kind); the env JSON slots use the same numbers. Kinds
# with forms (FORM_KINDS) have no fixed height.
HEIGHTS = {
    ("fantasy", "tower"): 24.0,
    ("fantasy", "wall"): 5.5,
    ("cyberpunk", "wall"): 14.0,
    ("fantasy", "market_stall"): 2.6,
    ("fantasy", "lamp"): 3.6,
    ("steampunk", "factory"): 15.0,
    ("steampunk", "chimney"): 20.0,
    ("steampunk", "pipe"): 2.0,
    ("steampunk", "crate"): 1.0,
    ("steampunk", "lamp"): 4.0,
    ("giant", "tower"): 13.3 * 5.0 / 1.75,
    ("giant", "lamp"): 3.6 * 5.0 / 1.75,
    ("small", "tower"): 3.5,
    ("fantasy", "well"): 3.4,
    ("giant", "well"): 3.4 * 5.0 / 1.75,
    ("small", "well"): 3.4 * 0.6 / 1.75,
    ("cyberpunk", "neon_sign"): 4.0,
    ("cyberpunk", "billboard"): 10.0,
    ("cyberpunk", "cable"): 9.0,
    ("cyberpunk", "kiosk"): 2.8,
    ("cyberpunk", "food_stall"): 3.2,
    ("cyberpunk", "walkway"): 7.0,
    ("cyberpunk", "lamp"): 6.5,
    ("cyberpunk", "crate"): 1.2,
}

# Foundation depth below the floor, in a person's metres (scaled with the inhabitants).
FOUNDATION = {"lamp": 0.6, "market_stall": 0.5, "crate": 0.4, "pipe": 0.5, "neon_sign": 0.5, "billboard": 0.8, "kiosk": 0.4,
              "food_stall": 0.4, "walkway": 0.6, "cable": 0.0,
              # Street props (settle/ornament.rs): shallow, except what holds ground.
              "barrel": 0.15, "cart": 0.0, "bench": 0.3, "fountain": 0.6, "market_cross": 0.6, "fence": 0.0, "gate": 0.0,
              "planter": 0.2, "flower_box": 0.1, "sign": 0.4, "banner": 0.4, "washing_line": 0.3, "tree": 0.3, "kerb": 0.0,
              "stairs": 1.0, "retaining_wall": 1.2}
FOUNDATION_DEFAULT = 1.8

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
        glass=(0.18, 0.18, 0.22), under=(0.25, 0.20, 0.17), glow=(1.0, 0.62, 0.28), lean_windows=True),
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
PALETTES["cyberpunk"] = dict(
    concrete=[(0.46, 0.47, 0.52), (0.40, 0.42, 0.49), (0.52, 0.49, 0.48), (0.34, 0.37, 0.45), (0.56, 0.54, 0.50)],
    panel=[(0.20, 0.22, 0.28), (0.27, 0.24, 0.33), (0.17, 0.25, 0.30), (0.30, 0.29, 0.31)],
    trim=[(0.86, 0.70, 0.16), (0.20, 0.58, 0.66), (0.72, 0.22, 0.28), (0.88, 0.46, 0.14), (0.62, 0.64, 0.68)],
    plastic=[(0.18, 0.55, 0.85), (0.92, 0.30, 0.30), (0.95, 0.80, 0.20), (0.25, 0.70, 0.45), (0.92, 0.92, 0.90)],
    awning=[(0.86, 0.22, 0.30), (0.18, 0.52, 0.78), (0.94, 0.64, 0.16), (0.30, 0.66, 0.42)],
    metal=(0.40, 0.42, 0.46), dark=(0.09, 0.09, 0.11), grime=(0.16, 0.15, 0.15), blind=(0.70, 0.66, 0.58),
    stone=(0.44, 0.44, 0.47), stone_dark=(0.30, 0.30, 0.33), iron=(0.15, 0.16, 0.18), timber=(0.30, 0.25, 0.22),
    under=(0.16, 0.16, 0.18), glass=(0.08, 0.11, 0.17), paint=[(0.20, 0.22, 0.28), (0.72, 0.22, 0.28)],
    glow=(1.0, 0.86, 0.66), glow_tint=(1.0, 0.9, 0.75))


class Surf(tuple):
    """A palette colour that knows its painted surface (living/tools/textures/surfaces.py): the
    detail layer the game multiplies into it. `mul`, `jitter` and `lerp` keep the tag, so parts
    coloured from a palette entry carry it into their vertex colours' alpha (`Builder.add`)."""
    surface = None


def tagged(c, surface):
    if surface is None:
        return tuple(c)
    t = Surf(c)
    t.surface = surface
    return t


# Each palette entry's surface; styles may override (cyberpunk stone is cast). Only glow and the
# window boxes' flowers stay plain here: glowing parts take glass in `Kit.add`, and blooms, fruit
# and goods stay untextured like nature's petals. Blinds are plastic slats (the cloth's folds read
# as pinstripes at a distance).
SURFACE_OF = {
    "plaster": "plaster", "cream": "plaster", "cap": "plaster",
    "timber": "wood", "under": "wood", "heart": "wood", "bark": "bark", "paint": "planks",
    "stone": "stone", "stone_dark": "stone", "brick": "brick", "concrete": "concrete", "grime": "concrete",
    "roof": "shingles", "grass": "thatch",
    "glass": "glass", "iron": "metal", "steel": "metal", "metal": "metal", "dark": "metal", "panel": "metal",
    "brass": "copper", "copper": "copper", "awning": "cloth",
    "plastic": "plastic", "trim": "plastic", "blind": "plastic", "earth": "earth",
}
SURFACE_STYLE = {"cyberpunk": {"stone": "concrete", "stone_dark": "concrete"}}


def surface_for(style, key, c):
    s = SURFACE_STYLE.get(style, {}).get(key, SURFACE_OF.get(key))
    # Red and orange roofs are clay tiles; blue, grey, green and brown ones slate or wood shingles.
    if s == "shingles" and c[0] > 0.6 and c[1] < 0.42:
        s = "tiles"
    return s


def tag_palettes():
    for style, pal in PALETTES.items():
        for key, v in list(pal.items()):
            if key.startswith("glow") or not isinstance(v, (tuple, list)):
                continue
            if isinstance(v, list):
                pal[key] = [tagged(c, surface_for(style, key, c)) for c in v]
            elif all(isinstance(x, (int, float)) for x in v):
                pal[key] = tagged(v, surface_for(style, key, v))


tag_palettes()

# Neon colours (linear emission), each its own glow material ("GlowPink"...): saturated pink,
# cyan and amber, plus red for aircraft warning lights and a cold white for strip lights.
NEON = {"pink": (1.0, 0.08, 0.50), "cyan": (0.04, 0.80, 1.0), "amber": (1.0, 0.50, 0.04), "red": (1.0, 0.05, 0.03),
        "white": (0.80, 0.90, 1.0)}
NEON_STRENGTH = 6.0


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
    return tagged(tuple(x + (y - x) * t for x, y in zip(a, b)), getattr(a if t < 0.5 else b, "surface", None))


def mul(c, k):
    return tagged(tuple(min(1.0, max(0.0, x * k)) for x in c), getattr(c, "surface", None))


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
            cols = [color_fn(loop.vert.co, nf.normal) for loop in nf.loops]
            # One surface per face (the first corner's), so the tag never blends across it.
            a = surface_alpha(getattr(cols[0], "surface", None))
            if UNTAGGED is not None and a == 1.0 and not mat.name.startswith("Glow"):
                import inspect
                who = next(f"{f.function}:{f.lineno}" for f in inspect.stack()[1:] if f.function not in ("add", "extra", "fn"))
                UNTAGGED[who] = UNTAGGED.get(who, 0) + len(nf.verts) - 2
            for loop, c in zip(nf.loops, cols):
                loop[self.col] = (*c, a)
        part.free()

    def finish(self, name, height=None, scale=1.0):
        """Scale uniformly, so the top is exactly `height` above the floor if given (z=0, kept as
        the origin; the foundation reaches below it), else by `scale`; centre the footprint on
        the origin, then make the object."""
        hi = max(v.co.z for v in self.bm.verts)
        k = height / max(hi, 1e-6) if height else scale
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


def lbox(lo, hi, fn=None, bevel=0.0, warp=None, open_bottom=False):
    """A box from lo to hi in local coordinates, optionally warped (local) and mapped (fn);
    `open_bottom` leaves out its (hidden) bottom face."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    size = hi - lo
    if open_bottom:
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z < -0.5], context="FACES_ONLY")
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

    def box(self, a0, a1, z0, z1, w0, w1, bevel=0.0, back=True):
        """A box on the wall; back=False leaves out its back face (at w0, against the wall)."""
        return lbox(Vector((a0, z0, w0)), Vector((a1, z1, w1)), fn=lambda q: self.p(q.x, q.y, q.z), bevel=bevel, open_bottom=not back)

    def obox(self, a, z, la, lz, w0, w1, angle, back=True):
        """A beam centred at (a, z), la long, lz thick, rotated in the wall plane."""
        c, s = math.cos(angle), math.sin(angle)

        def fn(q):
            return self.p(a + q.x * c - q.y * s, z + q.x * s + q.y * c, q.z)
        return lbox(Vector((-la / 2, -lz / 2, w0)), Vector((la / 2, lz / 2, w1)), fn=fn, open_bottom=not back)

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
    """A Builder with a palette, an RNG and shading helpers.

    `rng` is the design stream: every size, form and feature choice, and the colour jitter of
    each `add`, draws from it in order, so a model's footprint follows from its seed. `pr` is a
    separate stream for hand-made detail (crooked chimneys, uneven ridges, sills, linings);
    detail added through `extra` and `pr` leaves the design stream, and so every model's
    footprint and features, as they were."""

    def __init__(self, rng, pal, ao=1.2, pr=None):
        self.b = Builder()
        self.rng, self.pal = rng, pal
        self.pr = pr or random.Random(0)
        self.body = material("Body")
        self.glow_mat = material("Glow", (1, 1, 1), emission=pal["glow"], strength=2.6)
        self.neons = {}
        self.ao = ao

    def neon(self, name):
        """The glow material of one neon colour (NEON): its own material, since the game takes
        a glowing part's emission from its material, not its vertex colours."""
        if name not in self.neons:
            self.neons[name] = material("Glow" + name.title(), (1, 1, 1), emission=NEON[name], strength=NEON_STRENGTH)
        return self.neons[name]

    def add(self, bm, color, glow=False, soft=None, closed=True, vary=0.04, ao=True, tint=None):
        """Add a part in `color` (jittered by `vary`, darkened near the ground unless `ao` is
        off, and multiplied by `tint(co, n)` if given); a callable colour is used as it is."""
        if PROFILE is not None:
            import inspect
            who = inspect.stack()[1].function
            PROFILE[who] = PROFILE.get(who, 0) + sum(len(f.verts) - 2 for f in bm.faces)
        if color is None and not glow:
            # An unlit window pane.
            color, ao, vary = self.pal["glass"], False, 0.0
        if isinstance(glow, str):
            # A neon colour: saturated, a little paler in its vertex colour (the tube's hot core).
            core = tagged(lerp(NEON[glow], (1.0, 1.0, 1.0), 0.3), "glass")
            self.b.add(bm, self.neon(glow), lambda co, n: core, soft, closed)
            return
        if glow:
            warm = tagged(self.pal.get("glow_tint", (1.0, 0.78, 0.45)), "glass")
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
            return mul(c, k * (tint(co, n) if tint else 1.0))
        self.b.add(bm, self.body, fn, soft, closed)

    def extra(self, *a, **kw):
        """`add` with colour jitter from the detail stream, leaving the design stream alone."""
        main, self.rng = self.rng, self.pr
        try:
            self.add(*a, **kw)
        finally:
            self.rng = main

    def choice(self, xs):
        return self.rng.choice(xs)

    def u(self, a, b):
        return self.rng.uniform(a, b)


# ---------------------------------------------------------------------------------------------
# Roofs


def roof_color(k, color):
    """A roof colour that knows its painted surface: palette roofs carry theirs; a raw colour
    becomes slate or clay tiles by its hue (`surface_for`)."""
    if getattr(color, "surface", None):
        return color
    return tagged(color, surface_for(k.style, "roof", color))


def gable_roof(k, centre, axis, half_len, half_span, zw, oh_e, oh_g, color, sides=(-1, 1), course=0.48,
               th=None, sag=0.1, barge=None, cap=True, clip=0.0, cut=(1.1, 2.8), deck=None):
    """A gable (or, with one side, lean-to) roof of stepped, slightly uneven shingle courses on a
    thick deck, with a heavy eave board, barge boards and ridge cap, so its thickness and
    overhang read from the game camera; each course darkens towards its butt, so the courses
    read as lines. The ridge sags (`sag`) and, by the detail stream, tilts and waves a little.

    `centre` is the middle of the ridge (z = ridge height); the slopes run down across `axis` to
    the wall lines at `half_span`, where they are at `zw`, then on past them by `oh_e`.
    `clip` > 0 makes a half-hip (jerkinhead): the top `clip` of each gable is hipped back at the
    roof's own pitch. `cut` is the range of shingle-piece lengths (longer on big roofs). `deck`
    is the roof's thickness under the shingles (default: twice a course's, within 0.12-0.3 m).
    `th` is a course's thickness; by default 0.15 m on slopes pulled in so that the eave's outer
    edge stays where 0.1 m courses put it (the settlement table's footprints)."""
    rng = k.rng
    color = roof_color(k, color)
    th, th_ref = (0.15, 0.1) if th is None else (th, th)
    deck = deck if deck is not None else min(0.3, max(0.12, th * 2))
    centre, A = Vector(centre), Vector(axis).normalized()
    C = Vector((-A.y, A.x, 0))
    rise = centre.z - zw
    p = math.atan2(rise, half_span)
    S = (half_span + oh_e) / math.cos(p)
    n = max(3, round(S / course))
    # Thicker courses stand further out at the eave: pull the slope in by as much. Shingle cuts
    # are still counted along the slope's design length S0, so the design stream is unchanged.
    S0 = S
    S -= 2.4 * (th - th_ref) * math.tan(p)
    L = half_len + oh_g
    barge = barge or k.pal.get("timber", (0.3, 0.2, 0.15))
    under = k.pal.get("under", (0.3, 0.2, 0.15))
    # Half-hip: slope length hipped at each end, and the inset of the ridge's ends.
    tc = clip * half_span / math.cos(p)

    def reach(t):
        return L - max(0.0, tc - t) * math.cos(p)

    # Hand-made: one end a little lower, and a slow wave along the ridge (detail stream).
    tilt, wave, ph = k.pr.uniform(-1, 1) * sag * 0.8, sag * k.pr.uniform(0.2, 0.5), k.pr.uniform(0, math.tau)

    def droop(a, t):
        f = min(1.0, abs(a) / L)
        return (sag * (1 - f ** 2) + tilt * a / L + wave * math.sin(ph + 2.5 * a / L)) * (1 - 0.6 * t / S)

    for sgn in sides:
        D = C * (sgn * math.cos(p)) - Z * math.sin(p)
        N = C * (sgn * math.sin(p)) + Z * math.cos(p)

        def fn(q, D=D, N=N):
            return centre + A * q.x + D * q.y + N * q.z - Z * droop(q.x, q.y)
        if tc > 0:
            k.add(lbox(Vector((-reach(0), -0.05, -deck)), Vector((reach(0), tc, 0.0)), fn), under, ao=False)
            k.add(lbox(Vector((-L, tc, -deck)), Vector((L, S, 0.0)), fn), under, ao=False)
        else:
            k.add(lbox(Vector((-L, -0.05, -deck)), Vector((L, S, 0.0)), fn), under, ao=False)
        # A heavy eave board along the foot of the slope.
        k.extra(lbox(Vector((-L + 0.02, S - 0.1, -deck - 0.06)), Vector((L - 0.02, S, th * 1.4)), fn), mul(barge, 0.95), ao=False, vary=0.03)
        for i in range(n):
            t0, t1 = S * i / n - (0.14 if i else 0.06), S * (i + 1) / n
            Lc = reach(max(S0 * i / n - (0.14 if i else 0.06), 0.0))
            # Each course is a few pieces of uneven length, butt and thickness: hand-laid.
            cuts = [-Lc - rng.uniform(0.0, 0.08)]
            while cuts[-1] < Lc - 0.6:
                cuts.append(cuts[-1] + rng.uniform(*cut))
            cuts[-1] = Lc + rng.uniform(0.0, 0.08)
            for a0, a1 in zip(cuts, cuts[1:]):
                jl, jr = rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05)
                thick = th * rng.uniform(0.8, 1.2)

                def butt(co, n, t0=t0, t1=t1, D=D):
                    # Darker towards the butt: the shadow line under the course above.
                    t = ((co - centre).dot(D) - t0) / max(t1 - t0, 1e-3)
                    return 1.0 - 0.2 * min(1.0, max(0.0, t)) ** 2 - (0.12 if n.dot(D) > 0.5 else 0.0)

                def warp(q, t0=t0, t1=t1, jl=jl, jr=jr, a0=a0, a1=a1, thick=thick):
                    f = (q.x - a0) / max(a1 - a0, 1e-3)
                    if q.y > t1 - 1e-4:
                        q.y += jl + (jr - jl) * f
                    if q.z > 1e-4:
                        # Wedge: thicker at the butt end, so each course reads as a step.
                        q.z = thick * (0.4 + 1.6 * (q.y - t0) / max(t1 - t0, 1e-3))
                    return q
                r = rng.random()
                c = jitter(color, rng, 0.04) if r > 0.2 else mul(color, rng.uniform(0.88, 0.93)) if r > 0.08 else mul(color, 1.07)
                k.add(lbox(Vector((a0 + 0.015, t0, 0.0)), Vector((a1 - 0.015, t1, 1.0)), fn, warp=warp, open_bottom=True), c, ao=False, vary=0, tint=butt)
        if barge:
            for e in (-1, 1):
                a0 = e * L
                k.add(lbox(Vector((min(a0, a0 + e * 0.16), tc - 0.08, -deck - 0.12)), Vector((max(a0, a0 + e * 0.16), S + 0.04, 2.0 * th_ref + 2.4 * (th - th_ref))), fn), barge, ao=False)
    if tc > 0 and len(sides) == 2:
        # The hipped ends: a triangle from the ridge's end down to the top of each gable.
        h, dz = tc * math.cos(p), tc * math.sin(p)
        for e in (-1, 1):
            apex = centre + A * (e * (L - h)) + Z * 0.02
            pts = [apex, centre + A * (e * L) + C * h - Z * dz, centre + A * (e * L) - C * h - Z * dz]
            nrm = (pts[1] - pts[0]).cross(pts[2] - pts[0]).normalized()
            if nrm.dot(A * e + Z) < 0:
                nrm = -nrm
            k.add(slab(pts, nrm * 0.14, -nrm * 0.1), jitter(color, rng, 0.05), ao=False, vary=0)
    if cap and len(sides) == 2:
        def fc(q):
            return centre + A * q.x + C * q.y + Z * q.z - Z * droop(q.x, 0)
        Lr = reach(0)
        k.add(lbox(Vector((-Lr - 0.12, -0.27, -0.05)), Vector((Lr + 0.12, 0.27, th * 3.0)), fc, bevel=0.07), mul(color, 0.7), ao=False)
    return p


def slab(pts, up, down=None):
    """A flat polygon thickened between `down` and `up` offsets (vectors)."""
    down = down if down is not None else Vector((0, 0, 0))
    bm = bmesh.new()
    a = [bm.verts.new(Vector(p) + down) for p in pts]
    b = [bm.verts.new(Vector(p) + up) for p in pts]
    bm.faces.new(a)
    bm.faces.new(list(reversed(b)))
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([a[i], a[j], b[j], b[i]])
    return bm


def hip_roof(k, cx, cy, hx, hy, zw, zr, oh, color, course=0.55, lip=0.07, swap=False):
    """A hipped roof of stacked, stepped frustum courses (long axis X, or Y with swap)."""
    rng = k.rng
    color = roof_color(k, color)
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
    k.add(frustum(rect(0, -0.02, -0.3), rect(1, -0.02, -0.3)), under, ao=False)
    # A thick eave band round the foot: the roof's edge reads as a slab, not a sheet.
    k.extra(frustum(rect(0, lip - 0.03, -0.36), rect(0, lip - 0.03, -0.02)), mul(k.pal.get("timber", under), 0.95), ao=False, vary=0.03)
    for i in range(n):
        f0, f1 = i / n, (i + 1) / n
        c = jitter(color, rng, 0.05) if rng.random() > 0.15 else mul(color, rng.uniform(0.88, 0.93))
        k.add(frustum(rect(f0, lip + rng.uniform(-0.02, 0.02), -0.12), rect(min(1, f1 + 0.02), 0, 0.03)), c, ao=False, vary=0,
              tint=lambda co, nn: 0.86 if nn.z < 0.35 else 1.0)
    a, b = (Vector((cx - (0 if swap else ridge), cy - (ridge if swap else 0), zr)), Vector((cx + (0 if swap else ridge), cy + (ridge if swap else 0), zr)))
    if ridge > 0.1:
        k.add(cyl(a - (b - a).normalized() * 0.2, b + (b - a).normalized() * 0.2, 0.24, 0.24, 6), mul(color, 0.7), ao=False)
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
        z0, z1 = ze + (zt - ze) * f0 - 0.1, ze + (zt - ze) * f1
        cc = jitter(color, rng, 0.05) if rng.random() > 0.15 else mul(color, rng.uniform(0.88, 0.93))
        k.add(cyl(c + Z * z0, c + Z * z1, r0, r1, sides), cc, ao=False, vary=0, tint=lambda co, nn: 0.86 if nn.z < 0.0 else 1.0)


# ---------------------------------------------------------------------------------------------
# Openings and wall details (human metres; giants and small folk scale whole models)


def window(k, f, a, z0, w, h, frame, lit=None, shutters=None, mullion=True, box_color=None, sill=True, recess=0.0):
    """A framed window; with `recess` its pane and glazing bars sit that far back, in a hole cut
    by wall_skin, and the frame stays on the wall's face."""
    rng = k.rng
    lit = rng.random() < 0.6 if lit is None else lit
    wp = 0.03 if recess == 0 else 0.02 - recess  # the pane: on the wall, or just before the core
    if lit:
        k.add(f.quad(a - w / 2, a + w / 2, z0, z0 + h, wp), None, glow=True, closed=False)
    else:
        k.add(f.quad(a - w / 2, a + w / 2, z0, z0 + h, wp), k.pal["glass"], closed=False, ao=False)
    fw = 0.12
    k.add(f.box(a - w / 2 - fw, a + w / 2 + fw, z0 + h, z0 + h + fw * 1.2, 0.0, 0.12, back=False), frame)
    k.add(f.box(a - w / 2 - fw, a - w / 2, z0, z0 + h, 0.0, 0.1, back=False), frame)
    k.add(f.box(a + w / 2, a + w / 2 + fw, z0, z0 + h, 0.0, 0.1, back=False), frame)
    if sill:
        k.add(f.box(a - w / 2 - fw * 1.6, a + w / 2 + fw * 1.6, z0 - 0.1, z0 + 0.02, 0.0, 0.18), frame)
    if mullion:
        k.add(f.box(a - 0.035, a + 0.035, z0, z0 + h, 0.02 - recess, 0.07 - recess), frame)
        k.add(f.box(a - w / 2, a + w / 2, z0 + h * 0.58, z0 + h * 0.58 + 0.07, 0.02 - recess, 0.07 - recess), frame)
    if shutters:
        for e in (-1, 1):
            a0 = a + e * (w / 2 + fw + 0.02)
            a1 = a0 + e * w * 0.5
            k.add(f.box(min(a0, a1), max(a0, a1), z0 - 0.02, z0 + h + 0.02, 0.02, 0.08, back=False), shutters)
            k.add(f.box(min(a0, a1) + 0.04, max(a0, a1) - 0.04, z0 + h * 0.48, z0 + h * 0.52, 0.08, 0.1), mul(shutters, 0.75))
    if box_color and lit is not None:
        k.add(f.box(a - w / 2 - 0.05, a + w / 2 + 0.05, z0 - 0.32, z0 - 0.1, 0.05, 0.32), k.pal["timber"])
        for i in range(3):
            aa = a - w / 2 + (i + 0.5) * w / 3
            k.add(sphere(f.p(aa, z0 - 0.05, 0.2), 0.11, 0), jitter(box_color, rng, 0.1), ao=False)


def door(k, f, a, z0, w, h, color, frame, hood=None, arch=False, recess=0.0):
    """A plank door with a frame and, from the floor level z0 down to the ground, steps; with
    `recess` the door stands that far back, in a hole cut by wall_skin."""
    rng = k.rng
    planks = 3 if w < 1.2 else 4
    r = recess
    for i in range(planks):
        a0 = a - w / 2 + i * w / planks
        k.add(f.box(a0 + 0.01, a0 + w / planks - 0.01, z0, z0 + h - (0.0 if not arch else 0.0), -0.04 - r, 0.04 - r + rng.uniform(0, 0.015)), jitter(color, rng, 0.06), vary=0)
    if arch:
        n = 6
        pts = [(a + math.cos(math.pi * i / n) * w / 2, z0 + h + math.sin(math.pi * i / n) * w * 0.35) for i in range(n + 1)]
        k.add(f.poly(pts, -0.04 - r, 0.05 - r), color)
    fw = 0.16
    top = z0 + h + (w * 0.35 if arch else 0)
    k.add(f.box(a - w / 2 - fw, a - w / 2, z0, z0 + h, 0.0, 0.14), frame)
    k.add(f.box(a + w / 2, a + w / 2 + fw, z0, z0 + h, 0.0, 0.14), frame)
    k.add(f.box(a - w / 2 - fw * 1.4, a + w / 2 + fw * 1.4, top, top + 0.2, 0.0, 0.16), frame)
    k.add(f.box(a + w / 2 - 0.2, a + w / 2 - 0.12, z0 + h * 0.45, z0 + h * 0.5, 0.04 - r, 0.1 - r), k.pal["iron"], ao=False)
    k.add(f.box(a - w / 2 + 0.05, a + w / 2 - 0.05, z0 + h * 0.8, z0 + h * 0.83, 0.04 - r, 0.07 - r), k.pal["iron"], ao=False)
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
    k.add(f.box(-L / 2, L / 2, z0, z0 + 0.2, 0.0, out + 0.02, back=False), timber)
    k.add(f.box(-L / 2, L / 2, z1 - 0.22, z1, 0.0, out + 0.02, back=False), timber)
    edges = [-L / 2 + i * L / bays for i in range(bays + 1)]
    for i, e in enumerate(edges):
        a0 = e if i < bays else e - tw
        a0 = max(-L / 2, min(L / 2 - tw, a0 - (0 if i in (0, bays) else tw / 2)))
        k.add(f.box(a0, a0 + tw, z0, z1, 0.0, out, back=False), timber)
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
                k.add(f.obox((a0 + a1) / 2, (z0 + z1) / 2, ln, tw * 0.9, 0.0, out * 0.8, ang, back=False), timber)
            else:
                mid = (a0 + a1) / 2
                for e in (-1, 1):
                    ln = math.hypot((a1 - a0) / 2, h)
                    ang = math.atan2(h, (a1 - a0) / 2) * e
                    k.add(f.obox((mid + (a0 if e > 0 else a1)) / 2, (z0 + z1) / 2, ln, tw * 0.9, 0.0, out * 0.8, ang, back=False), timber)
        else:
            a, oz, w, h = op
            if oz - z0 > 0.6 and (a1 - a0) > w + 0.5:
                # Little braces under the window.
                for e in (-1, 1):
                    x0 = a + e * (w / 2 + 0.1)
                    xe = a1 if e > 0 else a0
                    ln = math.hypot(xe - x0, oz - z0 - 0.3)
                    ang = math.atan2(oz - z0 - 0.3, abs(xe - x0)) * (-e)
                    k.add(f.obox((x0 + xe) / 2, (z0 + 0.2 + oz - 0.1) / 2, ln, tw * 0.8, 0.0, out * 0.8, ang * -1, back=False), timber)


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


# How far windows and doors sit back in a wall (a person's metres).
RECESS = 0.24


def facing(bm, pts, normal):
    """A face through pts, wound to face `normal`."""
    f = bm.faces.new([bm.verts.new(p) for p in pts])
    f.normal_update()
    if f.normal.dot(normal) < 0:
        f.normal_flip()
    return f


def wall_skin(f, z0, z1, holes, depth):
    """A wall face from z0 to z1 with rectangular holes [(a0, a1, zb, zt)] cut through it, and
    the reveals of each hole running `depth` back to the wall's core: (face, reveals)."""
    L = f.length
    skin, rev = bmesh.new(), bmesh.new()

    def q(a0, a1, za, zb):
        if a1 - a0 > 1e-4 and zb - za > 1e-4:
            facing(skin, [f.p(a0, za, 0), f.p(a1, za, 0), f.p(a1, zb, 0), f.p(a0, zb, 0)], f.n)
    prev = -L / 2
    for a0, a1, zb, zt in sorted(holes):
        q(prev, a0, z0, z1)
        q(a0, a1, z0, zb)
        q(a0, a1, zt, z1)
        prev = a1
        for pts, nrm in (([(a0, zb), (a0, zt)], f.u), ([(a1, zb), (a1, zt)], -f.u), ([(a0, zb), (a1, zb)], Z), ([(a0, zt), (a1, zt)], -Z)):
            (pa, za), (pb, zz) = pts
            facing(rev, [f.p(pa, za, 0), f.p(pb, zz, 0), f.p(pb, zz, -depth), f.p(pa, za, -depth)], nrm)
    q(prev, L / 2, z0, z1)
    return skin, rev


def house_colours(k):
    """One building's colours: plaster, timber, roof, door paint, shutters, window boxes."""
    rng, pal = k.rng, k.pal
    return dict(plaster=k.choice(pal["plaster"]), timber=jitter(pal["timber"], rng, 0.08), stone=pal["stone"],
                roof=k.choice(pal["roof"]), paint=k.choice(pal["paint"]),
                shut=k.choice(pal["paint"]) if rng.random() < 0.6 else None,
                flowers=k.choice([(0.9, 0.3, 0.35), (0.95, 0.75, 0.3), (0.85, 0.45, 0.8)]) if rng.random() < 0.4 else None)


def block(k, P, x0, x1, y0, y1, storeys, hs=2.75, plinth=0.45, knee=0.0, jetty=0.0, jetty_back=False,
          ground="plaster", entry=None, skip=(), roof="gable", axis="x", pitch=55.0, oh_e=0.5, oh_g=0.35,
          clip=0.0, attic=0.75, shop=False, plinth_box=True, wins=None, win=(0.9, 1.15), course=0.55,
          cut=(1.4, 3.2), lamp=0.5, hood=None, door_w=1.1):
    """A storeyed rectangular block, x0..x1 along the front and y0 (front) to y1 (back), on a stone
    plinth, timber-framed plaster (or stone) storeys, each upper storey jettied `jetty` further out
    at the front (and back), and a roof: "gable" or "hip", ridge along `axis`, `clip` for a
    half-hip; None for no roof. `entry` is the door: (face, position as a fraction of its length), `wins`
    the chance of a window per bay and face, `skip` faces hidden by another part.

    Returns the top storey's extents and the roof's heights for chimneys, dormers and wings."""
    rng = k.rng
    timber, plaster, stone = P["timber"], P["plaster"], P["stone"]
    cx, hx = (x0 + x1) / 2, (x1 - x0) / 2
    if plinth_box and plinth > 0:
        k.add(box((x0 - 0.08, y0 - 0.08, 0), (x1 + 0.08, y1 + 0.08, plinth), 0.05), k.pal["stone_dark"])
        # A paler capping course with a weathered edge, so the plinth reads as its own band.
        k.extra(box((x0 - 0.12, y0 - 0.12, plinth - 0.12), (x1 + 0.12, y1 + 0.12, plinth + 0.02), 0.045), mul(k.pal["stone"], 1.04))
    wins = dict({"front": 0.85, "back": 0.45, "left": 0.45, "right": 0.45}, **(wins or {}))
    zw = plinth + storeys * hs + knee
    ww, wh = win
    for s in range(storeys):
        z0 = plinth + s * hs
        z1 = z0 + hs + (knee if s == storeys - 1 else 0)
        jf = jetty * s
        jb = jf if jetty_back else 0.0
        Y0, Y1 = y0 - jf, y1 + jb
        cy, hy = (Y0 + Y1) / 2, (Y1 - Y0) / 2
        mat = stone if (ground == "stone" and s == 0) or ground == "all_stone" else plaster
        # The storey is a core set back by RECESS and a skin on each face with its openings cut
        # through, so windows and doors sit in the wall. One colour per storey (design stream).
        R = RECESS
        wall_c = jitter(mat, rng, 0.02)
        k.extra(box((x0 + R, Y0 + R, z0 - 0.02), (x1 - R, Y1 - R, z1)), wall_c, vary=0)
        if s >= 1 and jetty > 0:
            # Jetty: a bressumer beam and the joist ends under each overhang.
            for e, ya, yb in ((-1, Y0, Y0 + jetty), (1, Y1 - jetty, Y1)):
                if e > 0 and not jetty_back:
                    continue
                yo = ya if e < 0 else yb
                k.add(box((x0, min(yo, yo - e * 0.2), z0 - 0.24), (x1, max(yo, yo - e * 0.2), z0)), timber)
                n = max(2, int(2 * hx / 0.7))
                for i in range(n):
                    x = x0 + (i + 0.5) * 2 * hx / n
                    k.add(box((x - 0.08, ya, z0 - 0.4), (x + 0.08, yb, z0 - 0.24)), timber)
        for name, f in box_faces(cx, cy, hx, hy).items():
            if name in skip or (name, s) in skip:
                k.extra(wall_skin(f, z0 - 0.02, z1, [], R)[0], wall_c, vary=0, closed=False)
                continue
            L = f.length
            bays = max(1, round(L / 2.3))
            bw = L / bays
            door_bay = shop_bay = None
            if s == 0 and entry and name == entry[0]:
                door_bay = min(range(bays), key=lambda i: abs(-L / 2 + (i + 0.5) * bw - entry[1] * L))
            if s == 0 and shop and name == "front" and bays >= 2:
                shop_bay = 0 if door_bay is None else door_bay + 1 if door_bay + 1 < bays else door_bay - 1
            openings = []
            for i in range(bays):
                a = -L / 2 + (i + 0.5) * bw
                if i == door_bay:
                    openings.append("door")
                elif i == shop_bay:
                    openings.append("shop")
                elif rng.random() < wins.get(name, 0.5) and bw > ww + 0.6:
                    openings.append((a, z0 + 0.95, min(ww, bw - 0.7), wh))
                else:
                    openings.append(None)
            front = name == "front"
            if mat is stone:
                # Quoins on the front and back faces cover all four corners.
                if name in ("front", "back"):
                    stone_quoins(k, f, z0, z1, mul(stone, 0.92), size=0.45)
            else:
                timber_storey(k, f, z0, z1, bays, [o if isinstance(o, tuple) else None for o in openings], timber, braces=front or rng.random() < 0.6)
            frame = timber if mat is plaster else mul(stone, 0.88)
            holes = []
            for i, op in enumerate(openings):
                a = -L / 2 + (i + 0.5) * bw
                if op == "door":
                    arch = mat is stone and rng.random() < 0.5
                    door(k, f, a, plinth, door_w, 2.15, P["paint"], frame, hood=hood, arch=arch, recess=R)
                    holes.append((a - door_w / 2, a + door_w / 2, plinth, plinth + 2.15 + (door_w * 0.35 if arch else 0.0)))
                    if rng.random() < lamp:
                        lantern(k, f.p(a + door_w * 0.5 + 0.4, plinth + 2.0, 0.28))
                elif op == "shop":
                    sw = min(2.2, bw - 0.5)
                    shopfront(k, f, a, z0, sw, P, recess=R)
                    holes.append((a - sw / 2, a + sw / 2, z0 + 0.8, z0 + 2.1))
                elif op:
                    window(k, f, *op, frame=frame, shutters=P["shut"] if front or rng.random() < 0.3 else None, mullion=front, sill=front,
                           box_color=P["flowers"] if front and s > 0 and rng.random() < 0.5 else None, recess=R)
                    oa, oz, ow, oh = op
                    holes.append((oa - ow / 2, oa + ow / 2, oz, oz + oh))
            skin, rev = wall_skin(f, z0 - 0.02, z1, holes, R)
            k.extra(skin, wall_c, vary=0, closed=False)
            k.extra(rev, mul(wall_c, 0.75), vary=0, closed=False, ao=False)
    jf = jetty * (storeys - 1)
    Y0, Y1 = y0 - jf, y1 + (jf if jetty_back else 0.0)
    cy, hy = (Y0 + Y1) / 2, (Y1 - Y0) / 2
    p = math.radians(pitch)
    half_span, half_len = (hy, hx) if axis == "x" else (hx, hy)
    ridge = zw + half_span * math.tan(p)
    info = dict(x0=x0, x1=x1, y0=y0, y1=y1, Y0=Y0, Y1=Y1, cx=cx, cy=cy, hx=hx, hy=hy, zw=zw, ridge=ridge, plinth=plinth,
                hs=hs, axis=axis, roof=roof, pitch=p, storeys=storeys, clip=clip)
    if roof is None:
        return info
    if roof == "hip":
        hip_roof(k, cx, cy, hx, hy, zw, ridge, oh_e, P["roof"], course=course + 0.07)
        return info
    A = X if axis == "x" else Y
    gable_roof(k, (cx, cy, ridge), A, half_len, half_span, zw, oh_e, oh_g, P["roof"], barge=timber, clip=clip, course=course, cut=cut)
    if axis == "x":
        gables = [("right", Face((x1, cy, 0), Y, 2 * hy)), ("left", Face((x0, cy, 0), -Y, 2 * hy))]
    else:
        gables = [("front", Face((cx, Y0, 0), X, 2 * hx)), ("back", Face((cx, Y1, 0), -X, 2 * hx))]
    for name, f in gables:
        if name not in skip:
            gable_wall(k, P, f, zw, ridge, clip, attic if name != "back" else attic * 0.5)
    return info


def gable_wall(k, P, f, zw, ridge, clip=0.0, attic=0.75):
    """The plaster gable under a roof's end: king post, collar, braces and an attic window."""
    rng, timber, plaster = k.rng, P["timber"], P["plaster"]
    half = f.length / 2
    zc = ridge - clip * (ridge - zw)
    hc = clip * half
    pts = [(-half, zw - 0.02), (half, zw - 0.02)] + ([(hc, zc), (-hc, zc)] if clip > 0 else [(0, ridge - 0.05)])
    k.add(f.poly(pts, -0.3, 0.0), plaster, vary=0.02)
    k.add(f.box(-0.09, 0.09, zw, min(zc, ridge - 0.25), 0.0, 0.06), timber)
    cz = zw + (ridge - zw) * 0.38
    cw = half * (1 - 0.38) - 0.1
    k.add(f.box(-cw, cw, cz, cz + 0.17, 0.0, 0.07), timber)
    if clip == 0:
        for e in (-1, 1):
            ln = math.hypot(half - 0.1, ridge - zw) - 0.2
            ang = math.atan2(ridge - zw, half) * e
            k.add(f.obox(e * -half / 2, zw + (ridge - zw) / 2 - 0.08, ln, 0.17, 0.0, 0.06, ang), timber)
    if zc - cz > 1.5 and rng.random() < attic:
        ww = min(0.7, cw * 0.5)
        for e in ((-1, 1) if cw > 1.6 and rng.random() < 0.5 else (0,)):
            window(k, f, e * cw * 0.5, cz + 0.4, ww, 0.85, timber, mullion=False, sill=True)


def shopfront(k, f, a, z0, w, P, recess=0.0):
    """A medieval shop: a wide window with a counter board that folds down and a pentice above."""
    rng = k.rng
    h = 1.3
    zb = z0 + 0.8
    k.add(f.box(a - w / 2, a + w / 2, zb, zb + h, -0.05 - recess, 0.03 - recess), None, glow=rng.random() < 0.8)
    k.add(f.box(a - w / 2 - 0.12, a + w / 2 + 0.12, zb + h, zb + h + 0.16, 0.0, 0.14), P["timber"])
    for e in (-1, 1):
        k.add(f.box(a + e * w / 2 - 0.08, a + e * w / 2 + 0.08, zb, zb + h, 0.0, 0.12), P["timber"])
    k.add(f.box(a - w / 2 - 0.1, a + w / 2 + 0.1, zb - 0.08, zb + 0.02, 0.0, 0.62), mul(P["timber"], 1.35))
    for e in (-1, 1):
        k.add(f.obox(a + e * (w / 2 - 0.15), zb - 0.32, 0.6, 0.06, 0.05, 0.12, 0.8 * e), P["timber"])
    goods = k.choice([(0.85, 0.2, 0.18), (0.95, 0.6, 0.15), (0.55, 0.75, 0.25), (0.82, 0.74, 0.55)])
    for i in range(int(w / 0.45)):
        k.add(sphere(f.p(a - w / 2 + 0.25 + i * 0.45, zb + 0.12, 0.35), 0.13, 0), jitter(goods, rng, 0.1), ao=False)
    if rng.random() < 0.6:
        # A striped cloth awning.
        cloth = tagged(k.choice([(0.82, 0.26, 0.22), (0.25, 0.46, 0.72), (0.28, 0.56, 0.36), (0.88, 0.66, 0.24)]), "cloth")
        n = max(3, int(w / 0.5))
        for i in range(n):
            a0 = a - w / 2 - 0.1 + i * (w + 0.2) / n
            k.add(prism([(0.0, zb + h + 0.45), (1.0, zb + h - 0.05), (1.0, zb + h + 0.0), (0.0, zb + h + 0.5)], a0, a0 + (w + 0.2) / n,
                        lambda q, s_, z: f.p(q, z, s_)), cloth if i % 2 == 0 else (0.96, 0.93, 0.84), ao=False)
    else:
        gable_roof(k, f.p(a, zb + h + 0.75, 0.05), f.u, w / 2 + 0.2, 0.75, zb + h + 0.25, 0.1, 0.05, P["roof"], sides=(1,) if f.n.cross(f.u).z > 0 else (-1,),
                   course=0.35, th=0.07, sag=0.0, cap=False)


def chimney(k, P, info, where="ridge", x=None):
    """A stone chimney through the roof near the ridge, or up the outside of a gable wall. Above
    the eaves it leans a little and kinks (a gable chimney only along its wall, so the model's
    footprint stays put), and it ends in a heavy cap with one or two pots, sooty at the top."""
    rng, stone = k.rng, P["stone"]
    top = info["ridge"] + rng.uniform(0.7, 1.2)
    ax = info["axis"]
    zb = info["zw"]
    pr = k.pr
    lean = Vector((pr.uniform(-1, 1), pr.uniform(-1, 1), 0)).normalized() * pr.uniform(0.05, 0.08)
    kink = pr.uniform(0.35, 0.65)
    gable = where == "gable" and info["roof"] != "hip"
    if gable:
        lean = Vector((0, lean.y, 0)) if ax == "x" else Vector((lean.x, 0, 0))

    def bend(q):
        # Lean grows above the eaves, and turns a little at the kink: built by hand, settled since.
        h = max(0.0, q.z - zb)
        hk = max(0.0, q.z - (zb + (top - zb) * kink))
        return q + lean * h - lean * hk * 0.8

    def sooty(co, n):
        return 1.0 - 0.35 * max(0.0, min(1.0, (co.z - top + 1.2) / 1.0))
    if gable:
        e = rng.choice([-1, 1]) if x is None else x
        if ax == "x":
            cx, cy = info["cx"] + e * (info["hx"] + 0.5), info["cy"] + rng.uniform(-0.4, 0.4)
        else:
            cx, cy = info["cx"] + rng.uniform(-0.5, 0.5), (info["Y1"] + 0.5)
        k.add(box((cx - 0.55, cy - 0.6, 0), (cx + 0.55, cy + 0.6, info["zw"] + 0.3), bevel=0.06), stone)
        # A sloped weathering where the breast steps in to the stack.
        k.extra(lbox(Vector((cx - 0.55, cy - 0.6, info["zw"] + 0.28)), Vector((cx + 0.55, cy + 0.6, info["zw"] + 0.42)), bevel=0.05), mul(stone, 0.85))
        k.add(lbox(Vector((cx - 0.4, cy - 0.42, info["zw"] + 0.25)), Vector((cx + 0.4, cy + 0.42, top - 0.3)), bevel=0.05, warp=bend), stone, tint=sooty)
    else:
        if ax == "x":
            cx = info["cx"] + (rng.uniform(-0.6, 0.6) * info["hx"] if x is None else x)
            cy = info["cy"] + rng.uniform(0.4, 1.0)
        else:
            cx = info["cx"] + rng.uniform(0.4, 1.0) * rng.choice([-1, 1])
            cy = info["cy"] + (rng.uniform(0.1, 0.6) * info["hy"] if x is None else x)
        k.add(lbox(Vector((cx - 0.4, cy - 0.4, info["zw"] - 0.6)), Vector((cx + 0.4, cy + 0.4, top - 0.3)), bevel=0.05, warp=bend), stone, tint=sooty)
    c = Vector((cx, cy, 0))
    k.add(lbox(c + Vector((-0.56, -0.56, top - 0.48)), c + Vector((0.56, 0.56, top - 0.2)), bevel=0.05, warp=bend), mul(stone, 0.8))
    pots = [Vector((0, 0, 0))] if pr.random() < 0.6 else [Vector((-0.2, 0, 0)), Vector((0.2, 0, 0))]
    for i, o in enumerate(pots):
        q = bend(c + o + Z * (top - 0.25))
        r = 0.17 if len(pots) == 1 else 0.14
        hh = pr.uniform(0.2, 0.28)
        part = lbox(q + Vector((-r, -r, 0)), q + Vector((r, r, hh)))
        (k.add if i == 0 else k.extra)(part, tagged((0.62, 0.36, 0.25), "brick"), tint=lambda co, n, z=q.z + hh: 0.6 if co.z > z - 0.05 and n.z > 0.5 else 1.0)


def dormers(k, P, info, xs, w=1.5):
    """Gabled dormers on the front slope of a roof whose ridge runs along X."""
    if info["axis"] != "x" or info["roof"] == "hip":
        return
    ridge, zw, Y0, cy = info["ridge"], info["zw"], info["Y0"], info["cy"]
    tanp = (ridge - zw) / info["hy"]
    hw = w / 2
    for xd in xs:
        yf = Y0 + 0.3
        zd0, zd1 = zw - 0.1, zw + 1.35
        zdr = zd1 + 0.75 * w / 1.5
        yb = cy - (ridge - zdr - 0.25) / tanp
        if yb <= yf + 0.4:
            continue
        k.add(box((xd - hw, yf, zd0), (xd + hw, yb, zd1)), P["plaster"], vary=0.02)
        fd = Face((xd, yf, 0), X, w)
        k.add(fd.poly([(-hw, zd1 - 0.02), (hw, zd1 - 0.02), (0, zdr - 0.03)], -0.25, 0.0), P["plaster"])
        window(k, fd, 0, zd0 + 0.3, min(0.75, w - 0.7), 0.85, P["timber"], shutters=None, sill=False)
        k.add(fd.box(-hw, -hw + 0.15, zd0, zd1, 0.0, 0.06), P["timber"])
        k.add(fd.box(hw - 0.15, hw, zd0, zd1, 0.0, 0.06), P["timber"])
        gable_roof(k, (xd, (yf - 0.3 + yb) / 2, zdr), Y, (yb - yf + 0.3) / 2, hw, zd1, 0.22, 0.0, P["roof"], course=0.45, th=0.08, sag=0.0, barge=P["timber"])


def lean_to(k, P, info, e, depth=None, length=None):
    """A board shed with a lean-to roof against a side wall (e = -1 left, 1 right)."""
    rng = k.rng
    lw = depth or rng.uniform(1.6, 2.1)
    D = info["y1"] - info["y0"]
    ld = length or rng.uniform(0.55, 0.8) * D
    xw = info["cx"] + e * info["hx"]
    y0 = rng.uniform(info["y0"], info["y1"] - ld)
    if info["axis"] == "x" or info["roof"] == "hip":
        top_in = info["plinth"] + min(info["hs"], 3.0) + 0.3
    else:
        top_in = info["zw"] - 0.55 * math.tan(info["pitch"]) - 0.25
    top_out = top_in - lw * 0.55
    shed = jitter((0.52, 0.43, 0.33), rng, 0.06)
    k.add(box((min(xw, xw + e * lw), y0, 0), (max(xw, xw + e * lw), y0 + ld, top_out)), boards(shed), vary=0)
    gable_roof(k, (xw, y0 + ld / 2, top_in), Y, ld / 2, lw, top_out, 0.3, 0.25, P["roof"], sides=(-e,), course=0.5, sag=0.0, barge=P["timber"])
    if rng.random() < 0.6:
        # A woodpile under the eave.
        fr = Face((xw + e * lw / 2, y0, 0), -X * e, lw)
        for r in range(3):
            for i in range(4 - r):
                a = -0.6 + (i + 0.5 * r) * 0.32
                k.add(cyl(fr.p(a, 0.15 + r * 0.26, 0.05), fr.p(a, 0.15 + r * 0.26, 0.75), 0.14, 0.14, 6), tagged((0.55, 0.40, 0.26), "wood"), ao=False)


def boards(c, w=0.32):
    """Vertical weatherboards as colour stripes (no extra geometry)."""
    def fn(co, n):
        u = co.x if abs(n.y) > abs(n.x) else co.y
        stripe = (0.9, 1.0, 0.95, 1.04)[int(math.floor(u / w)) % 4]
        return mul(c, stripe * (0.8 + 0.2 * min(1.0, co.z / 1.2)))
    return fn


def wing(k, P, info, wx, ww, depth, d=-1, storeys=1, ground="plaster", wins=None, entry=None, pitch=None, roof_clip=0.0):
    """A gabled wing `ww` wide at x = wx, `depth` out of the main block's front (d = -1) or back
    (d = 1), `storeys` high; its ridge runs back into the main roof (a cross gable)."""
    if d < 0:
        ya, yb = info["y0"] - depth, info["y0"] + 0.05
    else:
        ya, yb = info["y1"] - 0.05, info["y1"] + depth
    wi = block(k, P, wx - ww / 2, wx + ww / 2, ya, yb, storeys, hs=info["hs"], plinth=info["plinth"], ground=ground,
               entry=entry, skip=("back",) if d < 0 else ("front",), roof=None, wins=wins, lamp=0.3)
    zww = wi["zw"]
    p = math.radians(pitch) if pitch else info["pitch"]
    wr = min(zww + math.tan(p) * ww / 2, info["ridge"] - 0.5)
    tanp_main = (info["ridge"] - info["zw"]) / info["hy"]
    ym = info["cy"] + d * (info["ridge"] - wr) / tanp_main
    yo = ya if d < 0 else yb
    lo, hi = min(yo, ym), max(yo, ym)
    gable_roof(k, (wx, (lo + hi) / 2, wr), Y, (hi - lo) / 2, ww / 2, zww, 0.4, 0.3, P["roof"], barge=P["timber"], clip=roof_clip)
    f = Face((wx, ya, 0), X, ww) if d < 0 else Face((wx, yb, 0), -X, ww)
    gable_wall(k, P, f, zww, wr, roof_clip, 0.8)
    return wi


def turret(k, P, x, y, r, z0, z1, top, stone=False):
    """A round corner turret (an oriel on a corbel from z0) with a cone roof up to `top`."""
    rng = k.rng
    wall = P["stone"] if stone else P["plaster"]
    k.add(cyl((x, y, z0 - 1.0), (x, y, z0), r * 0.25, r, 12), mul(P["stone"], 0.9))
    k.add(cyl((x, y, z0), (x, y, z1), r, r, 12), wall, vary=0.02)
    z = z0
    while z < z1 - 0.5:
        k.add(cyl((x, y, z), (x, y, z + 0.18), r + 0.05, r + 0.05, 12), P["timber"])
        z += 2.75
    k.add(cyl((x, y, z1 - 0.2), (x, y, z1), r + 0.06, r + 0.06, 12), P["timber"])
    out = math.atan2(x, -y) if abs(x) + abs(y) > 0 else 0.0
    z = z0 + 0.8
    while z < z1 - 1.4:
        for da in (-0.9, 0.0, 0.9):
            window(k, cyl_face_at((x, y), r - 0.04, out + da), 0, z, 0.45, 1.0, P["timber"], mullion=False, sill=False)
        z += 2.75
    cone_roof(k, (x, y, 0), r, z1, top, P["roof"], oh=0.3, course=0.45, sides=12, flare=rng.uniform(0.0, 0.4))
    k.add(cyl((x, y, top - 0.2), (x, y, top + 0.6), 0.05, 0.03, 5), k.pal["iron"], ao=False)


def cyl_face_at(c, r, ang):
    """As cyl_face, about a vertical axis through c (x, y)."""
    f = cyl_face(r, ang)
    f.o = f.o + Vector((c[0], c[1], 0))
    return f


def lean(k):
    """Hand-made lean: shear the whole building a little."""
    rng = k.rng
    lx, ly = rng.uniform(-0.012, 0.012), rng.uniform(-0.008, 0.008)
    for v in k.b.bm.verts:
        v.co.x += lx * v.co.z
        v.co.y += ly * v.co.z


def roof_choice(rng, opts):
    """(roof, axis, clip) from weighted options [(weight, roof, axis, clip)]."""
    t = rng.random() * sum(o[0] for o in opts)
    for w, roof, axis, clip in opts:
        t -= w
        if t <= 0:
            return roof, axis, clip
    return opts[-1][1:]


def fantasy_house(k):
    """Houses by form: cottage, house, longhouse, L-house and corner house."""
    rng, form = k.rng, k.form
    u = rng.uniform
    P = house_colours(k)
    stone_ground = rng.random() < 0.35
    ground = "stone" if stone_ground else "plaster"
    plinth = u(0.38, 0.5)
    if form == "cottage":
        W, D = u(5.0, 7.0), u(4.4, 5.6)
        roof, axis, clip = roof_choice(rng, [(0.65, "gable", "x", 0.0), (0.35, "gable", "x", 0.38)])
        knee = rng.choice([0.0, 0.5, 0.9])
        info = block(k, P, -W / 2, W / 2, -D / 2, D / 2, 1, hs=3.0, plinth=plinth, knee=knee, ground=ground,
                     entry=("front", u(-0.25, 0.25)), roof=roof, axis=axis, pitch=u(50, 58), clip=clip,
                     hood=P["roof"] if rng.random() < 0.4 else None)
        if knee > 0 or info["ridge"] - info["zw"] > 3.4:
            dormers(k, P, info, [u(-0.6, 0.6)] if W < 6.4 else rng.choice([[u(-0.6, 0.6)], [-W / 4, W / 4]]))
        if rng.random() < 0.5:
            lean_to(k, P, info, rng.choice([-1, 1]))
        chimney(k, P, info, rng.choice(["ridge", "gable"]))
    elif form == "house":
        W, D = u(6.2, 8.0), u(5.0, 6.4)
        roof, axis, clip = roof_choice(rng, [(0.4, "gable", "x", 0.0), (0.25, "gable", "y", 0.0), (0.15, "hip", "x", 0.0), (0.2, "gable", "x", 0.35)])
        if axis == "y":
            W, D = u(5.6, 6.8), u(6.4, 8.0)
        jetty = 0.4 if rng.random() < 0.75 else 0.0
        info = block(k, P, -W / 2, W / 2, -D / 2, D / 2, 2, plinth=plinth, jetty=jetty, jetty_back=rng.random() < 0.5, ground=ground,
                     entry=("front", u(-0.3, 0.3)), roof=roof, axis=axis, pitch=u(52, 60), clip=clip,
                     hood=P["roof"] if axis == "y" and rng.random() < 0.6 else None)
        if rng.random() < 0.35:
            lean_to(k, P, info, rng.choice([-1, 1]))
        chimney(k, P, info, rng.choice(["ridge", "gable"]))
    elif form == "longhouse":
        W, D = u(11.0, 14.0), u(5.2, 6.2)
        roof, axis, clip = roof_choice(rng, [(0.45, "gable", "x", 0.0), (0.55, "gable", "x", 0.4)])
        e = rng.choice([-1, 1])
        info = block(k, P, -W / 2, W / 2, -D / 2, D / 2, 1, hs=3.0, plinth=plinth, knee=u(0.2, 0.6), ground=ground,
                     entry=("front", -e * u(0.12, 0.25)), roof=roof, axis=axis, pitch=u(48, 54), clip=clip,
                     course=0.55, cut=(1.6, 3.4))
        # The byre end: a wide plank door for the beasts.
        f = Face((0, -D / 2, 0), X, W)
        bx = e * (W / 2 - 1.8)
        k.add(f.box(bx - 1.0, bx + 1.0, plinth, plinth + 2.3, -0.04, 0.05), mul(P["timber"], 1.3))
        k.add(f.obox(bx, plinth + 1.15, 2.4, 0.14, 0.05, 0.11, 0.85), P["timber"])
        k.add(f.box(bx - 1.15, bx + 1.15, plinth + 2.3, plinth + 2.5, 0.0, 0.14), P["timber"])
        if rng.random() < 0.4:
            dormers(k, P, info, [-e * W / 4])
        if rng.random() < 0.4:
            lean_to(k, P, info, e)
        chimney(k, P, info, "ridge", x=-e * u(0.5, 2.5))
        if rng.random() < 0.5:
            chimney(k, P, info, "gable", x=-e)
    elif form in ("lhouse", "corner"):
        W, D = u(7.5, 9.5), u(5.4, 6.4)
        side = k.corner if form == "corner" else rng.choice([-1, 1])
        ww = u(3.2, 4.0)
        wx = side * (W / 2 - ww / 2 - (0.0 if form == "corner" else u(0.3, 0.8)))
        front_wing = form == "lhouse" and rng.random() < 0.55
        storeys = 2 if (form == "corner" or rng.random() < 0.7) else 1
        knee = 0.0 if storeys == 2 else 0.8
        wins = {"right": 0.9, "left": 0.3} if side > 0 else {"left": 0.9, "right": 0.3}
        da = (-side * 0.2) if front_wing else side * 0.3
        info = block(k, P, -W / 2, W / 2, -D / 2, D / 2, storeys, plinth=plinth, knee=knee, ground=ground,
                     entry=("front", da), roof="gable", axis="x", pitch=u(52, 58), wins=wins if form == "corner" else None,
                     hood=P["roof"] if rng.random() < 0.4 else None)
        depth = u(2.4, 3.6) if front_wing else u(4.0, 6.0)
        wing(k, P, info, wx, ww, depth, d=-1 if front_wing else 1, storeys=storeys, ground=ground,
             wins={"right": 0.9, "left": 0.5} if side > 0 else {"left": 0.9, "right": 0.5})
        if rng.random() < 0.3 and not front_wing:
            lean_to(k, P, info, -side)
        chimney(k, P, info, "ridge", x=-side * u(0.5, 2.0))
    else:
        raise ValueError(form)
    lean(k)


def fantasy_townhouse(k):
    """Townhouses by form: narrow (2-3 bays, gable to the street), wide (4-5 bays) and corner."""
    rng, form = k.rng, k.form
    u = rng.uniform
    P = house_colours(k)
    ground = "stone" if rng.random() < 0.45 else "plaster"
    plinth = u(0.38, 0.5)
    if form == "narrow":
        W, D = u(4.4, 5.8), u(7.5, 9.5)
        storeys = rng.choice([2, 3, 3])
        jetty = 0.35 if rng.random() < 0.7 else 0.0
        info = block(k, P, -W / 2, W / 2, -D / 2, D / 2, storeys, hs=2.65, plinth=plinth, jetty=jetty, ground=ground,
                     entry=("front", rng.choice([-0.3, 0.3])), roof="gable", axis="y", pitch=u(56, 62), oh_e=0.3,
                     shop=rng.random() < 0.5, wins={"left": 0.2, "right": 0.2, "back": 0.5}, attic=0.95,
                     hood=P["roof"] if rng.random() < 0.3 else None)
        if rng.random() < 0.35:
            # A hoist beam out of the front gable, for goods to the attic.
            zt = info["zw"] + (info["ridge"] - info["zw"]) * 0.72
            f = Face((0, info["Y0"], 0), X, W)
            k.add(f.box(-0.1, 0.1, zt - 0.1, zt + 0.1, 0.0, 1.1), P["timber"])
            k.add(f.box(-0.02, 0.02, zt - 1.6, zt - 0.1, 0.95, 0.99), (0.75, 0.66, 0.48), ao=False)
            k.add(cyl(f.p(0, zt - 0.12, 0.97), f.p(0, zt - 0.3, 0.97), 0.1, 0.1, 6), P["timber"], ao=False)
        chimney(k, P, info, "ridge", x=u(0.2, 0.6) * info["hy"])
    elif form == "wide":
        W, D = u(8.0, 10.5), u(6.6, 8.2)
        storeys = rng.choice([2, 2, 3])
        roof, axis, clip = roof_choice(rng, [(0.5, "gable", "x", 0.0), (0.25, "gable", "x", 0.33), (0.25, "hip", "x", 0.0)])
        jetty = 0.4 if rng.random() < 0.7 else 0.0
        cross = roof != "hip" and rng.random() < 0.45
        info = block(k, P, -W / 2, W / 2, -D / 2, D / 2, storeys, hs=2.7, plinth=plinth, jetty=jetty, ground=ground,
                     entry=("front", rng.choice([-0.35, 0.0, 0.35])), roof=roof, axis=axis, pitch=u(50, 57), clip=clip,
                     shop=rng.random() < 0.4, wins={"left": 0.35, "right": 0.35, "back": 0.45}, course=0.62, cut=(1.8, 3.8))
        if cross:
            # A wall gable: the front's middle bays rise into their own gable.
            ww = u(3.0, 3.8)
            wing(k, P, info, u(-0.15, 0.15) * W, ww, u(0.5, 0.9) + jetty * (storeys - 1), d=-1, storeys=storeys, ground="plaster",
                 wins={"front": 0.95, "left": 0.4, "right": 0.4})
        elif roof != "hip":
            dormers(k, P, info, rng.choice([[-W / 4, W / 4], [-W / 3, 0.0, W / 3], [0.0]]))
        chimney(k, P, info, "ridge")
        if rng.random() < 0.5:
            chimney(k, P, info, "gable")
    elif form == "corner":
        side = k.corner
        W, D = u(7.0, 8.6), u(7.4, 9.0)
        storeys = rng.choice([2, 3, 3])
        roof, axis, clip = roof_choice(rng, [(0.45, "hip", "x", 0.0), (0.35, "gable", "y", 0.0), (0.2, "gable", "x", 0.35)])
        jetty = 0.0
        wins = {"right": 0.85, "left": 0.2} if side > 0 else {"left": 0.85, "right": 0.2}
        info = block(k, P, -W / 2, W / 2, -D / 2, D / 2, storeys, hs=2.7, plinth=plinth, jetty=jetty, ground=ground,
                     entry=("front", -side * 0.3), roof=roof, axis=axis, pitch=u(52, 58), clip=clip,
                     shop=rng.random() < 0.6, wins=dict(wins, back=0.4), course=0.62, cut=(1.8, 3.8))
        r = u(1.1, 1.35)
        tx, ty = side * (W / 2 + 0.15), -D / 2 - 0.15
        turret(k, P, tx, ty, r, info["plinth"] + info["hs"], info["zw"] + 0.4, info["ridge"] + u(0.5, 2.0), stone=ground == "stone" and rng.random() < 0.3)
        chimney(k, P, info, "ridge", x=-side * u(0.5, 1.5) if axis == "x" else None)
    else:
        raise ValueError(form)
    lean(k)


def fantasy_inn(k):
    """An inn: a long two- or three-storey house on the square, a hanging sign, lanterns, benches
    and barrels at the door, maybe a carriage arch into its yard."""
    rng = k.rng
    u = rng.uniform
    P = house_colours(k)
    P["shut"] = P["shut"] or k.choice(k.pal["paint"])
    W, D = u(13.0, 16.0), u(8.8, 10.4)
    storeys = rng.choice([2, 2, 3])
    roof, axis, clip = roof_choice(rng, [(0.5, "gable", "x", 0.0), (0.5, "gable", "x", 0.35)])
    ground = "stone" if rng.random() < 0.55 else "plaster"
    plinth = u(0.45, 0.6)
    jetty = 0.45 if rng.random() < 0.7 else 0.0
    info = block(k, P, -W / 2, W / 2, -D / 2, D / 2, storeys, hs=2.9, plinth=plinth, jetty=jetty, ground=ground,
                 entry=("front", 0.0), roof=roof, axis=axis, pitch=u(48, 54), clip=clip, course=0.72, cut=(2.2, 4.4),
                 wins={"front": 0.95, "back": 0.3, "left": 0.3, "right": 0.3}, lamp=0.0, hood=P["roof"], door_w=1.5)
    dormers(k, P, info, rng.choice([[-W / 4, W / 4], [-W / 3, 0.0, W / 3]]), w=1.7)
    chimney(k, P, info, "gable", x=-1)
    chimney(k, P, info, "gable", x=1)
    f = Face((0, -D / 2, 0), X, W)
    for e in (-1, 1):
        lantern(k, f.p(e * 1.35, plinth + 2.1, 0.28), 1.2)
    # The sign: an iron bracket out of the wall over the door, a painted board hanging from it.
    sz = plinth + 2.9 + (0.4 if jetty else 0.0)
    sa = rng.choice([-1, 1]) * u(1.8, 2.6)
    sy = -D / 2 - jetty
    iron = k.pal["iron"]
    k.add(box((sa - 0.05, sy - 1.5, sz - 0.05), (sa + 0.05, sy, sz + 0.05)), iron, ao=False)
    k.add(lbox(Vector((-0.03, -1.05, -0.03)), Vector((0.03, 0.0, 0.03)), fn=lambda q: Vector((sa + q.x, sy + q.y, sz - 0.55 - q.y * 0.5 + q.z))), iron, ao=False)
    board = k.choice(k.pal["paint"])
    k.add(box((sa - 0.05, sy - 1.35, sz - 1.25), (sa + 0.05, sy - 0.3, sz - 0.25), 0.02), board)
    k.add(box((sa - 0.07, sy - 1.4, sz - 1.3), (sa + 0.07, sy - 0.25, sz - 1.2)), P["timber"])
    k.add(box((sa - 0.07, sy - 1.4, sz - 0.3), (sa + 0.07, sy - 0.25, sz - 0.2)), P["timber"])
    emblem = k.choice([(0.95, 0.78, 0.3), (0.92, 0.9, 0.82), (0.85, 0.3, 0.25)])
    for e in (-1, 1):
        k.add(sphere((sa + e * 0.07, sy - 0.82, sz - 0.75), 0.24, 1, squash=0.9), emblem, ao=False)
    for dy in (-1.2, -0.4):
        k.add(box((sa - 0.01, sy + dy - 0.01, sz - 0.25), (sa + 0.01, sy + dy + 0.01, sz)), iron, ao=False)
    # Benches and barrels along the front.
    wood = mul(P["timber"], 1.3)
    for e in (-1, 1):
        bx = e * u(3.2, W / 2 - 1.5)
        k.add(box((bx - 0.9, -D / 2 - 0.75, 0), (bx + 0.9, -D / 2 - 0.35, 0.45)), wood)
        k.add(box((bx - 1.0, -D / 2 - 0.8, 0.42), (bx + 1.0, -D / 2 - 0.3, 0.5)), mul(wood, 1.1))
        barrel(k, (bx + e * 1.5, -D / 2 - 0.6, 0), 0.34, 0.85, P["timber"])
    if rng.random() < 0.6:
        # A carriage arch at one end: a stone screen wall with a gateway into the yard behind.
        e = rng.choice([-1, 1])
        x0, x1 = (W / 2, W / 2 + 3.6) if e > 0 else (-W / 2 - 3.6, -W / 2)
        stone = P["stone"]
        hz = plinth + 2.9 + 1.0
        fa = Face(((x0 + x1) / 2, -D / 2 + 0.6, 0), X, x1 - x0)
        k.add(fa.box(-1.8, 1.8, 0, hz, -0.1, 0.5), stone, vary=0.03)
        n = 7
        k.add(fa.poly([(-1.3, 0.0), (1.3, 0.0)] + [(math.cos(math.pi * i / n) * 1.3, 2.6 + math.sin(math.pi * i / n) * 0.75) for i in range(n + 1)], 0.45, 0.53), (0.16, 0.13, 0.12))
        for i in range(n):
            a0, a1 = math.pi * i / n, math.pi * (i + 1) / n
            q = [(math.cos(a0) * 1.32, 2.6 + math.sin(a0) * 0.77), (math.cos(a0) * 1.6, 2.6 + math.sin(a0) * 1.0),
                 (math.cos(a1) * 1.6, 2.6 + math.sin(a1) * 1.0), (math.cos(a1) * 1.32, 2.6 + math.sin(a1) * 0.77)]
            k.add(fa.poly(q, 0.45, 0.58), mul(stone, rng.uniform(0.85, 0.95)), vary=0)
        k.add(fa.box(-1.95, 1.95, hz, hz + 0.25, -0.2, 0.75), mul(stone, 0.85))
        gable_roof(k, ((x0 + x1) / 2, -D / 2 + 0.85, hz + 0.75), X, 1.8, 0.65, hz + 0.25, 0.15, 0.1, P["roof"], course=0.35, th=0.07, sag=0.0, barge=P["timber"])
    lean(k)


def fantasy_hall(k):
    """A guildhall: an open stone arcade on the ground floor, a tall timber-framed hall above,
    a steep roof with a little bell turret on the ridge, and the guild's arms on the front."""
    rng = k.rng
    u = rng.uniform
    P = house_colours(k)
    W, D = u(14.0, 18.0), u(9.4, 11.2)
    hx, hy = W / 2, D / 2
    stone = P["stone"]
    za = u(3.6, 4.2)
    # Arcade: piers and round arches round the front and sides, a dark hall floor behind.
    k.add(box((-hx - 0.12, -hy - 0.12, 0), (hx + 0.12, hy + 0.12, 0.35), 0.05), k.pal["stone_dark"])
    k.add(box((-hx + 1.4, -hy + 1.4, 0.3), (hx - 1.4, hy - 0.05, za), 0.05), mul(P["plaster"], 0.8))
    k.add(box((-hx, hy - 1.4, 0.3), (hx, hy, za)), stone, vary=0.02)
    for name, f in box_faces(0, 0, hx, hy).items():
        if name == "back":
            continue
        L = f.length
        n = max(2, round(L / 3.3))
        span = L / n
        pier = 0.65
        for i in range(n + 1):
            a = -L / 2 + i * span
            a0, a1 = max(-L / 2, a - pier / 2), min(L / 2, a + pier / 2)
            k.add(f.box(a0, a1, 0.3, za, 0.0, 1.0 if name == "front" else 1.3), mul(stone, rng.uniform(0.95, 1.05)), vary=0)
        for i in range(n):
            ac = -L / 2 + (i + 0.5) * span
            r = span / 2 - pier / 2
            spring = za - 0.45 - r
            m = 6
            pts = [(ac - r, spring - 0.01), (ac - r - 0.05, za), (ac + r + 0.05, za), (ac + r, spring - 0.01)]
            pts += [(ac + math.cos(math.pi * j / m) * r, spring + math.sin(math.pi * j / m) * r) for j in range(1, m)]
            k.add(f.poly(pts, 0.0, 0.6), stone, vary=0.03)
        k.add(f.box(-L / 2 - 0.1, L / 2 + 0.1, za - 0.25, za + 0.05, 0.0, 1.1), mul(stone, 0.88))
    door(k, Face((0, -hy + 1.4, 0), X, W - 2.8), 0, 0.35, 1.4, 2.4, P["paint"], mul(stone, 0.85), arch=True)
    # Lanterns under the arcade.
    for x in (-hx / 2, hx / 2):
        lantern(k, (x, -hy + 0.7, za - 0.9), 1.1)
    # The hall storey above.
    ground = "plaster" if rng.random() < 0.65 else "all_stone"
    roof, axis, clip = roof_choice(rng, [(0.55, "hip", "x", 0.0), (0.45, "gable", "x", 0.3)])
    info = block(k, P, -hx, hx, -hy, hy, 1, hs=u(4.0, 4.6), plinth=za, plinth_box=False, knee=0.3, ground=ground,
                 roof=roof, axis=axis, pitch=u(54, 60), clip=clip, win=(1.0, 2.2), course=0.7, cut=(2.0, 4.2),
                 wins={"front": 1.0, "back": 0.6, "left": 0.8, "right": 0.8}, attic=0.9)
    # The guild's arms between the middle windows.
    f = Face((0, -hy, 0), X, W)
    arms = k.choice(k.pal["paint"])
    zc = za + 2.6
    k.add(f.poly([(-0.55, zc + 0.6), (0.55, zc + 0.6), (0.55, zc - 0.1), (0.0, zc - 0.75), (-0.55, zc - 0.1)], 0.05, 0.16), arms)
    k.add(f.poly([(-0.25, zc + 0.3), (0.25, zc + 0.3), (0.25, zc - 0.05), (0.0, zc - 0.35), (-0.25, zc - 0.05)], 0.16, 0.2), (0.95, 0.8, 0.35), ao=False)
    # A bell turret on the ridge: an open belfry and a slender spire.
    ridge = info["ridge"]
    tb = 0.85
    zt0 = ridge - 0.9
    k.add(box((-tb, -tb, zt0), (tb, tb, ridge + 0.5)), P["timber"])
    for dx in (-1, 1):
        for dy in (-1, 1):
            k.add(box((dx * (tb - 0.12) - 0.12, dy * (tb - 0.12) - 0.12, ridge + 0.5), (dx * (tb - 0.12) + 0.12, dy * (tb - 0.12) + 0.12, ridge + 2.0)), P["timber"])
    k.add(cyl((0, 0, ridge + 1.75), (0, 0, ridge + 1.15), 0.32, 0.45, 8), k.pal.get("brass", (0.85, 0.65, 0.3)), ao=False)
    k.add(box((-tb - 0.1, -tb - 0.1, ridge + 2.0), (tb + 0.1, tb + 0.1, ridge + 2.2)), P["timber"])
    cone_roof(k, (0, 0, 0), tb + 0.1, ridge + 2.2, ridge + u(4.0, 5.5), P["roof"], oh=0.2, course=0.45, sides=8)
    k.add(cyl((0, 0, ridge + 4.0), (0, 0, ridge + 6.2), 0.04, 0.03, 5), k.pal["iron"], ao=False)
    chimney(k, P, info, "ridge", x=-hx * 0.6)


def fantasy_chapel(k):
    """A stone chapel: a buttressed nave with lancet windows, a west tower with a belfry and a
    spire (or a pyramid roof) over the door, maybe an apse and a sacristy."""
    rng = k.rng
    u = rng.uniform
    pal = k.pal
    stone = jitter(pal["stone"], rng, 0.04)
    dark = pal["stone_dark"]
    slate = k.choice([(0.34, 0.36, 0.42), (0.28, 0.40, 0.62), (0.46, 0.43, 0.42), (0.74, 0.33, 0.22)])
    P = dict(plaster=stone, timber=mul(stone, 0.8), stone=stone, roof=slate, paint=k.choice(pal["paint"]))
    W, Ln = u(7.6, 9.4), u(13.0, 16.5)
    hx, hy = W / 2, Ln / 2
    hw = u(6.4, 7.8)
    k.add(box((-hx - 0.15, -hy - 0.15, 0), (hx + 0.15, hy + 0.15, 0.6), 0.05), dark)
    k.add(box((-hx, -hy, 0.55), (hx, hy, hw), 0.06), stone, vary=0.02)
    nb = max(3, round(Ln / 3.3))
    for e in (-1, 1):
        f = Face((e * hx, 0, 0), Y * e, Ln)
        for i in range(nb + 1):
            a = -Ln / 2 + i * Ln / nb
            a = max(-Ln / 2 + 0.35, min(Ln / 2 - 0.35, a))
            k.add(f.box(a - 0.35, a + 0.35, 0.0, hw * 0.72, 0.0, 0.85), mul(stone, 0.93))
            k.add(prism([(0.85, hw * 0.72), (0.0, hw - 0.2), (0.0, hw * 0.72)], a - 0.35, a + 0.35, lambda q, s_, z, f=f: f.p(q, z, s_)), mul(stone, 0.93))
        for i in range(nb):
            a = -Ln / 2 + (i + 0.5) * Ln / nb
            arch_window(k, f, a, 2.2, 0.8, hw - 4.0, mul(stone, 0.85), lit=rng.random() < 0.75, bars=False)
        k.add(f.box(-Ln / 2, Ln / 2, hw - 0.3, hw, 0.0, 0.25), mul(stone, 0.88))
    pitch = math.radians(u(54, 60))
    ridge = hw + hx * math.tan(pitch)
    gable_roof(k, (0, 0, ridge), Y, hy, hx, hw, 0.45, 0.3, slate, course=0.6, cut=(1.8, 3.6), barge=mul(stone, 0.85))
    # Stone gables with a coping, a cross on the east one.
    for e, f in ((-1, Face((0, -hy, 0), X, W)), (1, Face((0, hy, 0), -X, W))):
        k.add(f.poly([(-hx, hw - 0.02), (hx, hw - 0.02), (0, ridge - 0.05)], -0.3, 0.0), stone)
        for s_ in (-1, 1):
            ln = math.hypot(hx + 0.2, ridge - hw)
            k.add(f.obox(s_ * -(hx + 0.2) / 2, (hw + ridge) / 2 + 0.1, ln, 0.3, -0.1, 0.25, math.atan2(ridge - hw, hx + 0.2) * s_), mul(stone, 0.88))
        if e > 0:
            k.add(f.box(-0.08, 0.08, ridge, ridge + 1.2, 0.0, 0.16), mul(stone, 0.9))
            k.add(f.box(-0.4, 0.4, ridge + 0.65, ridge + 0.85, 0.0, 0.16), mul(stone, 0.9))
    # The apse: a half-round east end under a half cone.
    if rng.random() < 0.6:
        ra = hx - 0.4
        za = hw * 0.85
        k.add(cyl((0, hy, 0.55), (0, hy, za), ra, ra, 14), stone, vary=0.02)
        k.add(cyl((0, hy, 0), (0, hy, 0.6), ra + 0.15, ra + 0.15, 14), dark)
        for ang in (math.pi - 0.75, math.pi, math.pi + 0.75):
            arch_window(k, cyl_face_at((0, hy), ra - 0.03, ang), 0, 2.2, 0.6, za - 4.0, mul(stone, 0.85), lit=rng.random() < 0.7, bars=False)
        cone_roof(k, (0, hy, 0), ra, za, za + ra * math.tan(pitch) * 0.9, slate, oh=0.35, course=0.6, sides=14)
    # A sacristy on one side.
    if rng.random() < 0.45:
        e = rng.choice([-1, 1])
        sx0 = e * hx
        sx1 = e * (hx + 3.0)
        sy0 = u(0.0, hy - 4.0)
        k.add(box((min(sx0, sx1), sy0, 0), (max(sx0, sx1), sy0 + 3.8, 3.4), 0.05), stone)
        gable_roof(k, (sx0, sy0 + 1.9, 4.6), Y, 1.9, 3.0, 3.3, 0.3, 0.25, slate, sides=(-e,), course=0.55, sag=0.0, barge=mul(stone, 0.85))
        door(k, Face((sx1, sy0 + 1.9, 0), Y * e, 3.8), 0, 0.3, 1.0, 2.1, P["paint"], mul(stone, 0.8), arch=True)
    # The west tower, its door the chapel's door.
    ts = u(3.8, 4.6)
    tz = u(13.0, 16.0)
    ty0 = -hy - ts * 0.6
    tc = Vector((0, ty0 + ts / 2, 0))
    th = ts / 2
    k.add(box((-th - 0.25, ty0 - 0.25, 0), (th + 0.25, ty0 + ts + 0.25, 0.9), 0.05), dark)
    k.add(box((-th, ty0, 0.85), (th, ty0 + ts, tz), 0.06), stone, vary=0.02)
    for f in box_faces(0, tc.y, th, th).values():
        stone_quoins(k, f, 0.9, tz, mul(stone, 0.9), size=0.5)
    faces = box_faces(0, tc.y, th, th)
    fr = faces["front"]
    door(k, fr, 0, 0.5, 1.5, 2.6, P["paint"], mul(stone, 0.8), arch=True)
    rw = [(math.cos(i / 12 * math.tau) * 0.75, 5.2 + math.sin(i / 12 * math.tau) * 0.75) for i in range(12)]
    k.add(fr.poly(rw, -0.05, 0.08), mul(stone, 0.82))
    k.add(fr.poly([(x * 0.75, 5.2 + (z - 5.2) * 0.75) for x, z in rw], 0.08, 0.12), None, glow=True)
    for name, f in faces.items():
        if name != "front" and rng.random() < 0.6:
            window(k, f, 0, 6.0, 0.4, 1.1, mul(stone, 0.85), lit=rng.random() < 0.4, mullion=False)
        # Belfry: paired louvred openings.
        for e in (-0.6, 0.6):
            pts = [(e - 0.35, tz - 3.4), (e + 0.35, tz - 3.4)] + [(e + math.cos(math.pi * i / 6) * 0.35, tz - 1.8 + math.sin(math.pi * i / 6) * 0.35) for i in range(7)]
            k.add(f.poly(pts, -0.05, 0.04), tagged((0.12, 0.11, 0.12), "wood"))
            for zz in (tz - 3.0, tz - 2.6, tz - 2.2):
                k.add(f.box(e - 0.33, e + 0.33, zz, zz + 0.1, 0.0, 0.08), mul(P["timber"], 0.7), ao=False)
        k.add(f.box(-th - 0.1, th + 0.1, tz - 0.35, tz, 0.0, 0.2), mul(stone, 0.85))
    if rng.random() < 0.6:
        top = tz + u(8.0, 11.0)
        cone_roof(k, tc, th * 1.15, tz, top, slate, oh=0.25, course=0.6, sides=8, flare=u(0.0, 0.3))
    else:
        top = tz + u(3.5, 5.0)
        hip_roof(k, 0, tc.y, th, th, tz, top, 0.35, slate, course=0.55)
    k.add(cyl(tc + Z * (top - 0.3), tc + Z * (top + 1.3), 0.06, 0.04, 6), pal["iron"], ao=False)
    k.add(sphere(tc + Z * (top + 0.2), 0.16, 1), (0.85, 0.65, 0.3), ao=False)
    k.add(box(tc + Vector((-0.45, -0.04, top + 0.85)), tc + Vector((0.45, 0.04, top + 0.97))), pal["iron"], ao=False)


def fantasy_workshop(k):
    """A smithy (open forge bay, big chimney, a fenced yard with an anvil) or a workshop (cart
    doors, a hoist, a yard of stacked timber)."""
    rng, form = k.rng, k.form
    u = rng.uniform
    P = house_colours(k)
    plinth = u(0.3, 0.42)
    e = rng.choice([-1, 1])
    yard_w = u(3.4, 4.8)
    if form == "smithy":
        W, D = u(6.4, 8.2), u(5.4, 6.4)
        ground = "all_stone" if rng.random() < 0.55 else "stone"
        info = block(k, P, -W / 2, W / 2, -D / 2, D / 2, 1, hs=3.2, plinth=plinth, knee=u(0.2, 0.6), ground=ground,
                     entry=("front", -e * 0.3), roof="gable", axis="x", pitch=u(42, 50), wins={"front": 0.4})
        # The forge bay: a wide dark opening with the fire glowing inside.
        f = Face((0, -D / 2, 0), X, W)
        fa = e * (W / 2 - 1.7)
        k.add(f.box(fa - 1.3, fa + 1.3, plinth, plinth + 2.4, -0.02, 0.03), (0.13, 0.11, 0.1))
        k.add(f.box(fa - 1.45, fa + 1.45, plinth + 2.4, plinth + 2.65, 0.0, 0.2), P["timber"])
        k.add(f.box(fa - 0.5, fa + 0.5, plinth + 0.7, plinth + 1.0, -0.6, -0.02), None, glow=True)
        k.add(f.box(fa - 0.6, fa + 0.6, plinth, plinth + 0.7, -0.7, -0.02), mul(P["stone"], 0.6))
        # The forge chimney, big and sooty.
        cx = e * (W / 2 - 0.9)
        top = info["ridge"] + u(1.4, 2.2)
        k.add(box((cx - 0.75, D / 2 - 1.6, 0), (cx + 0.75, D / 2 + 0.2, top - 0.3), 0.06), lambda co, n: mul(P["stone"], 0.95 - 0.35 * max(0.0, (co.z - top + 2.0) / 2.0)))
        k.add(box((cx - 0.9, D / 2 - 1.75, top - 0.35), (cx + 0.9, D / 2 + 0.35, top), 0.04), (0.2, 0.18, 0.18))
        # The yard: fence, anvil on a stump, quench trough, iron bars.
        xw, xo = e * W / 2, e * (W / 2 + yard_w)
        yx0, yx1 = min(xw, xo), max(xw, xo)
        fence(k, P, [(xw, -D / 2 + 0.2), (xo, -D / 2 + 0.2), (xo, D / 2 - 0.2), (xw, D / 2 - 0.2)], gate=0)
        ax = (yx0 + yx1) / 2
        k.add(cyl((ax, 0, 0), (ax, 0, 0.55), 0.32, 0.3, 8), (0.5, 0.38, 0.26))
        k.add(box((ax - 0.35, -0.12, 0.55), (ax + 0.25, 0.12, 0.8)), k.pal["iron"], ao=False)
        k.add(cyl((ax + 0.25, 0, 0.72), (ax + 0.55, 0, 0.72), 0.1, 0.02, 6), k.pal["iron"], ao=False)
        k.add(box((ax - 0.5, D / 2 - 1.4, 0), (ax + 0.5, D / 2 - 0.7, 0.55), 0.04), mul(P["timber"], 1.2))
        k.add(box((ax - 0.42, D / 2 - 1.32, 0.45), (ax + 0.42, D / 2 - 0.78, 0.52)), (0.15, 0.22, 0.3), ao=False)
        barrel(k, (ax + e * 1.0, -D / 2 + 1.0, 0), 0.3, 0.8, P["timber"])
        if rng.random() < 0.5:
            lean_to(k, P, info, e, depth=yard_w * 0.6, length=D * 0.5)
    else:
        W, D = u(8.0, 10.0), u(5.8, 7.0)
        info = block(k, P, -W / 2, W / 2, -D / 2, D / 2, 1, hs=3.2, plinth=plinth, knee=u(0.7, 1.1), ground="stone" if rng.random() < 0.4 else "plaster",
                     entry=("front", e * 0.3), roof="gable", axis="x", pitch=u(48, 55), wins={"front": 0.7})
        # Cart doors: two broad braced leaves.
        f = Face((0, -D / 2, 0), X, W)
        da = -e * (W / 2 - 2.0)
        for s_ in (-1, 1):
            k.add(f.box(da + min(0, s_ * 1.25), da + max(0, s_ * 1.25), plinth, plinth + 2.7, -0.03, 0.06), mul(P["timber"], 1.3))
            k.add(f.obox(da + s_ * 0.62, plinth + 1.35, 2.9, 0.14, 0.06, 0.12, 1.1 * s_), P["timber"])
        k.add(f.box(da - 1.4, da + 1.4, plinth + 2.7, plinth + 2.95, 0.0, 0.16), P["timber"])
        dormers(k, P, info, [da])
        zt = info["zw"] + 1.3
        k.add(box((da - 0.1, -D / 2 - 1.2, zt + 0.5), (da + 0.1, -D / 2 + 0.6, zt + 0.7)), P["timber"])
        k.add(box((da - 0.02, -D / 2 - 1.1, zt - 1.2), (da + 0.02, -D / 2 - 1.06, zt + 0.5)), (0.75, 0.66, 0.48), ao=False)
        # The yard: a fence round stacked planks and logs under a pent roof.
        xw, xo = e * W / 2, e * (W / 2 + yard_w)
        yx0, yx1 = min(xw, xo), max(xw, xo)
        fence(k, P, [(xw, -D / 2 + 0.3), (xo, -D / 2 + 0.3), (xo, D / 2 - 0.3), (xw, D / 2 - 0.3)], gate=0)
        for r in range(3):
            for i in range(5 - r):
                y = -1.0 + (i + 0.5 * r) * 0.42
                k.add(cyl(((yx0 + yx1) / 2 - 1.2, y, 0.2 + r * 0.36), ((yx0 + yx1) / 2 + 1.2, y, 0.2 + r * 0.36), 0.19, 0.19, 7), tagged((0.58, 0.43, 0.28), "wood"), ao=False)
        for i in range(4):
            k.add(box((yx0 + 0.5, D / 2 - 1.6, i * 0.12), (yx1 - 0.5, D / 2 - 0.6, i * 0.12 + 0.1)), jitter((0.8, 0.66, 0.45), rng, 0.06), vary=0, ao=False)
        chimney(k, P, info, "ridge")
    lean(k)


def fence(k, P, pts, gate=None, h=1.1):
    """A post-and-rail fence along a polyline; segment `gate` is left open."""
    wood = mul(P["timber"], 1.25)
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        a, b = Vector((*a, 0)), Vector((*b, 0))
        L = (b - a).length
        n = max(1, round(L / 1.6))
        for j in range(n + 1):
            p = a + (b - a) * (j / n)
            k.add(box(p + Vector((-0.07, -0.07, 0)), p + Vector((0.07, 0.07, h))), wood)
        if i == gate:
            continue
        d = (b - a).normalized()
        nrm = Vector((-d.y, d.x, 0))
        for z in (h * 0.45, h * 0.85):
            k.add(lbox(Vector((0, -0.03, z - 0.05)), Vector((L, 0.03, z + 0.05)), fn=lambda q, a=a, d=d, nrm=nrm: a + d * q.x + nrm * q.y + Z * q.z), wood)


def fantasy_barn(k):
    """A barn (board walls, great doors, a big roof, maybe thatch) or a small shed."""
    rng, form = k.rng, k.form
    u = rng.uniform
    P = house_colours(k)
    wood = k.choice([(0.52, 0.40, 0.28), (0.45, 0.38, 0.32), (0.56, 0.27, 0.20), (0.40, 0.33, 0.26)])
    thatch = rng.random() < 0.4
    if thatch:
        P["roof"] = jitter((0.74, 0.62, 0.38), rng, 0.05)
    if form == "barn":
        W, D = u(9.0, 13.0), u(6.8, 8.6)
        hx, hy = W / 2, D / 2
        hw = u(3.6, 4.6)
        k.add(box((-hx - 0.1, -hy - 0.1, 0), (hx + 0.1, hy + 0.1, 0.6), 0.05), k.pal["stone_dark"])
        k.add(box((-hx, -hy, 0.55), (hx, hy, hw)), boards(wood), vary=0)
        for f in box_faces(0, 0, hx, hy).values():
            for a in (-f.length / 2, f.length / 2):
                k.add(f.box(a - 0.12 if a > 0 else a, a if a > 0 else a + 0.12, 0.55, hw, 0.0, 0.08), P["timber"])
            k.add(f.box(-f.length / 2, f.length / 2, hw - 0.2, hw, 0.0, 0.08), P["timber"])
        f = Face((0, -hy, 0), X, W)
        dw, dh = u(3.0, 3.6), u(3.2, 3.6)
        dh = min(dh, hw - 0.3)
        for s_ in (-1, 1):
            k.add(f.box(min(0, s_ * dw / 2), max(0, s_ * dw / 2), 0.1, dh, -0.03, 0.07), boards(mul(wood, 1.15), 0.28), vary=0)
            k.add(f.obox(s_ * dw / 4, dh / 2, math.hypot(dw / 2, dh) - 0.2, 0.14, 0.07, 0.13, math.atan2(dh, dw / 2) * s_), P["timber"])
            k.add(f.box(min(0, s_ * dw / 2), max(0, s_ * dw / 2), dh / 2 - 0.08, dh / 2 + 0.08, 0.07, 0.13), P["timber"])
        k.add(f.box(-dw / 2 - 0.2, dw / 2 + 0.2, dh, dh + 0.2, 0.0, 0.12), P["timber"])
        clip = 0.35 if rng.random() < 0.45 else 0.0
        pitch = math.radians(u(45, 52) if not thatch else u(52, 58))
        ridge = hw + hy * math.tan(pitch)
        gable_roof(k, (0, 0, ridge), X, hx, hy, hw, 0.55 if not thatch else 0.7, 0.4, P["roof"], course=0.7 if not thatch else 0.55,
                   th=0.1 if not thatch else 0.22, cut=(2.0, 4.0), clip=clip, barge=P["timber"] if not thatch else None)
        for e in (-1, 1):
            g = Face((e * hx, 0, 0), Y * e, D)
            zc = ridge - clip * (ridge - hw)
            pts = [(-hy, hw - 0.02), (hy, hw - 0.02)] + ([(clip * hy, zc), (-clip * hy, zc)] if clip else [(0, ridge - 0.05)])
            k.add(g.poly(pts, -0.3, 0.0), boards(wood), vary=0)
            k.add(g.box(-0.6, 0.6, hw + 0.4, hw + 1.6, -0.02, 0.06), (0.13, 0.11, 0.1))
            k.add(g.box(-0.7, 0.7, hw + 1.6, hw + 1.75, 0.0, 0.12), P["timber"])
        if rng.random() < 0.5:
            # Hay bales by the door.
            for i in range(rng.randint(2, 4)):
                bx = rng.choice([-1, 1]) * u(dw / 2 + 0.8, hx - 0.6)
                k.add(cyl((bx, -hy - 0.7, 0.55), (bx, -hy - 1.6, 0.55), 0.55, 0.55, 10), (0.86, 0.74, 0.42), ao=False)
    else:
        W, D = u(3.4, 5.0), u(2.8, 3.6)
        hx, hy = W / 2, D / 2
        hw = u(2.2, 2.6)
        k.add(box((-hx - 0.06, -hy - 0.06, 0), (hx + 0.06, hy + 0.06, 0.25), 0.04), k.pal["stone_dark"])
        k.add(box((-hx, -hy, 0.2), (hx, hy, hw)), boards(wood), vary=0)
        f = Face((0, -hy, 0), X, W)
        k.add(f.box(-0.5, 0.5, 0.25, 2.0, -0.03, 0.06), boards(mul(wood, 1.15), 0.25), vary=0)
        k.add(f.obox(0, 1.1, 1.8, 0.12, 0.06, 0.11, 1.05), P["timber"])
        if rng.random() < 0.5:
            gable_roof(k, (0, hy, hw + 0.9), X, hx, D, hw - 0.1, 0.35, 0.25, P["roof"], sides=(-1,), course=0.45, sag=0.0, barge=P["timber"])
        else:
            gable_roof(k, (0, 0, hw + hy * 0.95), X, hx, hy, hw, 0.35, 0.25, P["roof"], course=0.45, sag=0.02, barge=P["timber"])
        for r in range(3):
            for i in range(4 - r):
                a = -0.6 + (i + 0.5 * r) * 0.3
                k.add(cyl((hx + 0.5, a, 0.15 + r * 0.25), (hx + 1.0, a, 0.15 + r * 0.25), 0.13, 0.13, 6), tagged((0.55, 0.40, 0.26), "wood"), ao=False)
    lean(k)


def giant_hall(k):
    """The giants' longhall: low stave walls under a huge steep roof, a porch over a great door,
    crossed gable boards, painted shields and a smoke-hole lantern on the ridge."""
    rng = k.rng
    u = rng.uniform
    P = house_colours(k)
    W, D = u(13.0, 15.5), u(6.6, 7.6)
    hx, hy = W / 2, D / 2
    hw = u(2.7, 3.1)
    k.add(box((-hx - 0.12, -hy - 0.12, 0), (hx + 0.12, hy + 0.12, 0.6), 0.05), k.pal["stone_dark"])
    k.add(box((-hx, -hy, 0.55), (hx, hy, hw)), boards(mul(P["timber"], 1.35), 0.4), vary=0)
    for f in box_faces(0, 0, hx, hy).values():
        n = max(2, round(f.length / 2.0))
        for i in range(n + 1):
            a = -f.length / 2 + i * f.length / n
            a = max(-f.length / 2 + 0.15, min(f.length / 2 - 0.15, a))
            k.add(f.box(a - 0.15, a + 0.15, 0.55, hw, 0.0, 0.12), P["timber"])
    pitch = math.radians(u(58, 63))
    ridge = hw + hy * math.tan(pitch)
    clip = 0.25 if rng.random() < 0.5 else 0.0
    gable_roof(k, (0, 0, ridge), X, hx, hy, hw, 0.9, 0.5, P["roof"], course=0.7, cut=(2.2, 4.4), clip=clip, barge=P["timber"])
    for e in (-1, 1):
        g = Face((e * hx, 0, 0), Y * e, D)
        zc = ridge - clip * (ridge - hw)
        k.add(g.poly([(-hy, hw - 0.02), (hy, hw - 0.02)] + ([(clip * hy, zc), (-clip * hy, zc)] if clip else [(0, ridge - 0.05)]), -0.3, 0.0), boards(mul(P["timber"], 1.35), 0.4), vary=0)
        # Crossed gable boards over the apex.
        if not clip:
            for s_ in (-1, 1):
                k.add(g.obox(s_ * 0.55 * math.cos(pitch), ridge + 0.55 * math.sin(pitch), 1.9, 0.24, 0.05, 0.22, s_ * pitch), P["timber"])
        window(k, g, 0, hw + 1.0, 0.7, 1.0, P["timber"], mullion=False)
    # Porch over the great door.
    f = Face((0, -hy, 0), X, W)
    door(k, f, 0, 0.6, 1.5, 2.3, P["paint"], P["timber"], arch=False)
    for s_ in (-1, 1):
        k.add(box((s_ * 1.4 - 0.15, -hy - 1.9, 0), (s_ * 1.4 + 0.15, -hy - 1.6, hw + 0.4)), P["timber"])
    gable_roof(k, (0, -hy - 0.6, hw + 1.8), Y, 1.5, 1.8, hw + 0.3, 0.3, 0.2, P["roof"], course=0.5, barge=P["timber"])
    # Shields along the front, lanterns by the door.
    for i, a in enumerate((-hx * 0.75, -hx * 0.42, hx * 0.42, hx * 0.75)):
        c = k.choice(k.pal["paint"])
        sf = Face(f.p(a, 0, 0.12), X, 1)
        k.add(sf.poly([(math.cos(j / 12 * math.tau) * 0.55, hw * 0.55 + math.sin(j / 12 * math.tau) * 0.55) for j in range(12)], 0.0, 0.08), c)
        k.add(sf.poly([(math.cos(j / 8 * math.tau) * 0.15, hw * 0.55 + math.sin(j / 8 * math.tau) * 0.15) for j in range(8)], 0.08, 0.14), (0.85, 0.7, 0.35), ao=False)
    for s_ in (-1, 1):
        lantern(k, f.p(s_ * 1.2, 2.5, 0.5), 1.1)
    # Smoke-hole lantern on the ridge.
    k.add(box((-0.7, -0.5, ridge - 0.6), (0.7, 0.5, ridge + 0.6)), P["timber"])
    gable_roof(k, (0, 0, ridge + 1.2), X, 0.8, 0.75, ridge + 0.55, 0.15, 0.15, P["roof"], course=0.4, sag=0.0)


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
    stone, dark = tagged((0.68, 0.66, 0.61), "stone"), tagged((0.52, 0.50, 0.47), "stone")
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
    cloth = tagged(k.choice([(0.82, 0.26, 0.22), (0.25, 0.46, 0.72), (0.28, 0.56, 0.36), (0.88, 0.66, 0.24), (0.56, 0.32, 0.62)]), "cloth")
    cream = tagged((0.96, 0.93, 0.84), "cloth")
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
    # Rivets closer than about 0.7 m merge at game distance: draw every other one.
    step = max(step, 0.7)
    n = max(1, int((a1 - a0) / step))
    for i in range(n + 1):
        a = a0 + i * (a1 - a0) / n
        k.add(f.box(a - 0.05, a + 0.05, z - 0.05, z + 0.05, w, w + 0.05, back=False), color, ao=False, vary=0)


def arch_window(k, f, a, z0, w, h, frame, lit=None, bars=True):
    """A tall window with a round head, a brick arch of voussoirs and a stone sill. Palettes
    with `lean_windows` (steampunk, whose houses carry dozens) draw the pane as one face and
    five voussoirs; others keep the slab pane and seven."""
    rng = k.rng
    lean = k.pal.get("lean_windows", False)
    lit = rng.random() < 0.65 if lit is None else lit
    r = w / 2
    n = 8
    pts = [(a - r, z0), (a + r, z0)] + [(a + math.cos(math.pi * i / n) * r, z0 + h + math.sin(math.pi * i / n) * r) for i in range(n + 1)]
    if lean:
        pane = bmesh.new()
        facing(pane, [f.p(pa, pz, 0.02) for pa, pz in pts[1:2] + pts[2:] + pts[:1]], f.n)
    else:
        pane = f.poly(pts, -0.05, 0.02)
    if lit:
        k.add(pane, None, glow=True, closed=not lean)
    else:
        k.add(pane, k.pal["glass"], ao=False, closed=not lean)
    if bars:
        for e in (-1, 1):
            k.add(f.box(a + e * r / 3 - 0.03, a + e * r / 3 + 0.03, z0, z0 + h + r * 0.9, 0.0, 0.06), k.pal["iron"], ao=False)
        for zz in (z0 + h * 0.35, z0 + h * 0.7, z0 + h):
            k.add(f.box(a - r, a + r, zz - 0.03, zz + 0.03, 0.0, 0.06), k.pal["iron"], ao=False)
    m = 5 if lean else 7
    # The lean arch still takes the draws seven voussoirs did (a shade and a colour jitter
    # each), so the design stream, and with it every footprint, is the same either way.
    shades = [rng.uniform(0.92, 1.0) for _ in range(6)] if lean else None
    for i in range(m):
        a0, a1 = math.pi * i / m, math.pi * (i + 1) / m
        ro = r + (0.32 if i == m // 2 else 0.24)
        q = [(a + math.cos(a0) * (r + 0.02), z0 + h + math.sin(a0) * (r + 0.02)), (a + math.cos(a0) * ro, z0 + h + math.sin(a0) * ro),
             (a + math.cos(a1) * ro, z0 + h + math.sin(a1) * ro), (a + math.cos(a1) * (r + 0.02), z0 + h + math.sin(a1) * (r + 0.02))]
        shade = 1.08 if i == m // 2 else (shades[i] if lean else rng.uniform(0.92, 1.0))
        k.add(f.poly(q, 0.0, 0.1 if i == m // 2 else 0.07), mul(frame, shade), vary=0)
    if lean:
        for _ in range(7 - m):
            rng.random()
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


def steampunk_house(k, H=None):
    """A brick townhouse with a copper mansard: narrow (2-4 floors over the shop), wide (1-3),
    corner (a round turret with a copper dome on the corner, a second shop window round the
    side) or pub (a painted timber pub front, brass letters, a hanging sign, barrels)."""
    rng, pal = k.rng, k.pal
    brick = k.choice(pal["brick"])
    stone, copper, iron, brass = pal["stone"], k.choice(pal["copper"]), pal["iron"], pal["brass"]
    paint = k.choice(pal["paint"])
    if k.form == "wide":
        W, D, ups = rng.uniform(8.4, 11.0), rng.uniform(6.4, 8.0), rng.choice([1, 2, 2, 3])
    elif k.form == "corner":
        W, D, ups = rng.uniform(7.2, 9.0), rng.uniform(7.2, 9.0), rng.choice([2, 3, 3])
    elif k.form == "pub":
        W, D, ups = rng.uniform(9.0, 12.0), rng.uniform(7.5, 9.0), rng.choice([1, 2, 2])
    else:
        W, D, ups = rng.uniform(4.8, 6.6), rng.uniform(6.6, 8.4), rng.choice([2, 3, 3, 4])
    hx, hy = W / 2, D / 2
    plinth, g, s = 0.55, 3.4, 2.9
    zw = plinth + g + ups * s
    H = H or zw + 0.35 + 2.4 + 0.7
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
    oriel = rng.random() < 0.55 and k.form not in ("corner", "pub")
    for name, f in faces.items():
        L = f.length
        bays = max(2, round(L / 2.1))
        for st in range(ups):
            z0 = plinth + g + st * s + 0.75
            for i in range(bays):
                a = -L / 2 + (i + 0.5) * L / bays
                if oriel and name == "front" and abs(a) < 1.3:
                    continue
                if name == "front" or rng.random() < (0.35 if name == "back" else 0.55):
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
    for xd in ([-W / 3, 0.0, W / 3] if W > 9.0 else [-W / 4, W / 4] if W > 6.8 else [0.0]):
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
    if k.form == "corner":
        side = k.corner
        sf = faces["right" if side > 0 else "left"]
        # A shop window round the side (the side face runs front to back for side > 0).
        a0, a1 = (-hy + 1.9, hy - 0.8) if side > 0 else (-hy + 0.8, hy - 1.9)
        k.add(sf.box(a0, a1, plinth + 0.6, plinth + 2.8, -0.05, 0.04), None, glow=True)
        for i in range(4):
            a = a0 + i * (a1 - a0) / 3
            k.add(sf.box(a - 0.06, a + 0.06, plinth + 0.6, plinth + 2.8, 0.0, 0.1), brass)
        k.add(sf.box(a0 - 0.15, a1 + 0.15, plinth + 2.8, plinth + 3.15, 0.0, 0.2), paint)
        # The corner turret: brick drum, stone bands, windows round it, a copper dome.
        tx, ty, r = side * hx, -hy, rng.uniform(1.3, 1.6)
        k.add(cyl((tx, ty, plinth + g - 0.2), (tx, ty, zw + 0.35), r, r, 12), brick_fn(brick, rng))
        k.add(cyl((tx, ty, plinth + g - 1.0), (tx, ty, plinth + g - 0.2), r * 0.5, r, 12), stone)
        for st in range(ups + 1):
            zb = plinth + g + st * s - 0.1
            k.add(cyl((tx, ty, zb), (tx, ty, zb + 0.22), r + 0.08, r + 0.08, 12), stone if st < ups else iron, ao=False)
        for st in range(ups):
            z0 = plinth + g + st * s + 0.75
            for ang in (-math.pi / 2 - side * 0.5, -math.pi / 2 + side * 0.9, side * 0.25 if side > 0 else math.pi - 0.25):
                fc = Face((tx + math.cos(ang) * r, ty + math.sin(ang) * r, 0), Vector((-math.sin(ang), math.cos(ang), 0)), 1.0)
                fc.n = Vector((math.cos(ang), math.sin(ang), 0))
                arch_window(k, fc, 0, z0, 0.7, 1.2, stone, bars=False)
        zd = zw + 0.35
        for i in range(5):
            t0, t1 = i / 5, (i + 1) / 5
            k.add(cyl((tx, ty, zd + r * 1.1 * math.sin(t0 * math.pi / 2)), (tx, ty, zd + r * 1.1 * math.sin(t1 * math.pi / 2)),
                      (r + 0.15) * math.cos(t0 * math.pi / 2), max(0.15, (r + 0.15) * math.cos(t1 * math.pi / 2)), 12), copper_seams(copper, 0.4), ao=False)
        k.add(cyl((tx, ty, zd + r * 1.1), (tx, ty, zd + r * 1.1 + 1.2), 0.12, 0.02, 6), brass, ao=False)
        k.add(sphere((tx, ty, zd + r * 1.1 + 0.1), 0.2, 1), brass, ao=False)
    if k.form == "pub":
        # The pub front: painted timber over the ground floor, big lit windows, a fascia with
        # brass letters, a hanging sign on a bracket and barrels by the door.
        pc = k.choice([(0.12, 0.26, 0.18), (0.40, 0.10, 0.10), (0.10, 0.14, 0.24)])
        k.add(front.box(-hx + 0.2, hx - 0.2, plinth + 2.75, plinth + 3.35, 0.0, 0.32), pc)
        k.add(front.box(-hx + 0.1, hx - 0.1, plinth + 3.35, plinth + 3.5, 0.0, 0.42), mul(pc, 0.8))
        n = int((W - 1.0) / 0.55)
        for i in range(n):
            if k.pr.random() < 0.82:
                a = -hx + 0.6 + i * 0.55
                k.add(front.box(a, a + 0.32, plinth + 2.88, plinth + 3.22, 0.32, 0.36, back=False), brass, ao=False)
        for a in (-hx + 0.3, hx - 0.3, span0 - 0.1, span1 + 0.1):
            k.add(front.box(a - 0.18, a + 0.18, plinth, plinth + 2.75, 0.0, 0.28), pc)
            k.add(front.box(a - 0.22, a + 0.22, plinth + 2.55, plinth + 2.75, 0.0, 0.34), brass, ao=False)
        k.add(front.box(sa - sw / 2, sa + sw / 2, plinth, plinth + 0.6, 0.0, 0.24), pc)
        sa_ = -door_a * 0.9
        k.add(front.box(sa_ - 0.05, sa_ + 0.05, plinth + 3.6, plinth + 3.7, 0.0, 1.5), iron, ao=False)
        k.add(front.box(sa_ - 0.04, sa_ + 0.04, plinth + 2.5, plinth + 3.5, 0.5, 1.4), k.choice([(0.85, 0.7, 0.3), (0.6, 0.15, 0.12), (0.2, 0.3, 0.45)]))
        k.add(front.box(sa_ - 0.06, sa_ + 0.06, plinth + 2.45, plinth + 2.55, 0.45, 1.45), brass, ao=False)
        for w in (0.65, 1.25):
            k.add(front.box(sa_ - 0.015, sa_ + 0.015, plinth + 3.5, plinth + 3.6, w - 0.015, w + 0.015), iron, ao=False)
        gear(k, front.p(sa_ + 0.05, plinth + 3.0, 0.95), Y, Z, 0.3, 8, 0.03, brass)
        for e in (-1, 1):
            barrel(k, front.p(door_a + e * 1.2, 0.0, 0.7), 0.34, 0.85, pal["timber"])


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
        k.add(cyl((vx + math.cos(a0) * rw, math.sin(a0) * rw, wz), (vx + math.cos(a1) * rw, math.sin(a1) * rw, wz), 0.035, 0.035, 5), tagged((0.7, 0.18, 0.15), "metal"), ao=False)
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
    """A gas lamp (a fluted iron post, a ladder bar and a lantern, single or on a crossarm) or a
    brass-globe lamp with a gear on its post."""
    rng, pal = k.rng, k.pal
    iron, brass = pal["iron"], pal["brass"]
    if rng.random() < 0.6:
        k.add(cyl((0, 0, 0), (0, 0, 0.5), 0.3, 0.22, 8), iron)
        k.add(cyl((0, 0, 0.5), (0, 0, 0.75), 0.22, 0.12, 8), mul(iron, 1.15))
        double = rng.random() < 0.4
        top = H - (1.0 if double else 0.95)
        k.add(cyl((0, 0, 0.75), (0, 0, top), 0.1, 0.07, 8), iron)
        for z in (0.95, 1.9, top - 0.1):
            k.add(cyl((0, 0, z), (0, 0, z + 0.1), 0.13, 0.13, 8), mul(iron, 1.3), ao=False)
        # The lamplighter's ladder bar.
        k.add(box((-0.42, -0.03, top - 0.55), (0.42, 0.03, top - 0.47)), iron, ao=False)
        if double:
            k.add(box((-0.75, -0.04, top), (0.75, 0.04, top + 0.08)), iron, ao=False)
            for e in (-1, 1):
                k.add(Face((0, 0, 0), X, 1).obox(e * 0.35, top - 0.2, 0.6, 0.04, -0.02, 0.02, -e * 0.6), iron)
                lantern(k, (e * 0.75, 0, top + 0.08 + 0.24 * 1.3), 1.3)
            k.add(sphere((0, 0, top + 0.2), 0.1, 1), brass, ao=False)
        else:
            lantern(k, (0, 0, top + 0.24 * 1.6), 1.6)
            k.add(sphere((0, 0, top + 0.6 * 1.6), 0.07, 1), brass, ao=False)
        return
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


def strut(k, a, b, r, color, sides=4):
    k.add(cyl(a, b, r, r, sides), color, ao=False, vary=0.03)


def copper_seams(c, every=0.45):
    """Copper sheet with standing seams (stripes) and paler verdigris on what faces up."""
    def fn(co, n):
        stripe = 0.92 if int(math.floor((co.x + co.y) / every)) % 2 else 1.0
        return mul(c, stripe * (1.1 if n.z > 0.6 else 1.0))
    return fn


def clock_face(k, f, a, zc, r, frame, w=0.0):
    """A lit clock dial on a wall face: a brass bezel, twelve ticks and two hands."""
    k.add(cyl(f.p(a, zc, w), f.p(a, zc, w + 0.14), r + 0.28, r + 0.28, 16), frame, ao=False)
    k.add(cyl(f.p(a, zc, w + 0.14), f.p(a, zc, w + 0.18), r, r, 16), None, glow=True)
    dark = tagged((0.12, 0.10, 0.09), "metal")
    for i in range(12):
        t = i / 12 * math.tau
        ln = 0.3 if i % 3 == 0 else 0.16
        k.add(f.obox(a + math.cos(t) * (r - 0.08 - ln / 2), zc + math.sin(t) * (r - 0.08 - ln / 2), ln, 0.07, w + 0.18, w + 0.22, t), dark, ao=False, vary=0)
    hour, minute = k.pr.uniform(0, math.tau), k.pr.uniform(0, math.tau)
    for t, ln, th in ((hour, r * 0.55, 0.12), (minute, r * 0.85, 0.08)):
        k.add(f.obox(a + math.cos(t) * ln / 2, zc + math.sin(t) * ln / 2, ln, th, w + 0.22, w + 0.27, t), dark, ao=False, vary=0)
    k.add(cyl(f.p(a, zc, w + 0.18), f.p(a, zc, w + 0.3), 0.12, 0.12, 8), frame, ao=False)


def sp_walls(k, x0, x1, y0, y1, z0, z1, brick, stone, pil=3.4, plinth=0.6):
    """A brick block on a stone plinth, with brick pilasters every `pil` metres and a stone
    cornice: the steampunk wall. Returns its faces."""
    pal = k.pal
    hx, hy = (x1 - x0) / 2, (y1 - y0) / 2
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    k.add(box((x0 - 0.15, y0 - 0.15, z0), (x1 + 0.15, y1 + 0.15, z0 + plinth), 0.05), pal["stone_dark"])
    k.add(box((x0, y0, z0 + plinth - 0.05), (x1, y1, z1), 0.05), brick_fn(brick, k.rng))
    faces = box_faces(cx, cy, hx, hy)
    for f in faces.values():
        L = f.length
        n = max(1, round(L / pil))
        for i in range(n + 1):
            a = min(L / 2 - 0.3, max(-L / 2 + 0.3, -L / 2 + i * L / n))
            k.add(f.box(a - 0.3, a + 0.3, z0 + plinth, z1 - 0.3, 0.0, 0.18, back=False), brick_fn(mul(brick, 0.9), k.rng), vary=0)
        k.add(f.box(-L / 2 - 0.2, L / 2 + 0.2, z1 - 0.35, z1 + 0.15, 0.0, 0.32, bevel=0.04), stone)
    return faces


def steampunk_clocktower(k):
    """The landmark: a stone base with an arched door, a brick shaft banded with riveted iron,
    a stone clock stage with lit dials on all four faces and a gear on show, an open belfry
    with a bell, and a copper spire with a brass finial."""
    rng, pal = k.rng, k.pal
    u = rng.uniform
    brick, stone, iron, brass = k.choice(pal["brick"]), pal["stone"], pal["iron"], pal["brass"]
    copper = k.choice(pal["copper"])
    S = u(7.0, 8.2)
    h = S / 2
    zb = u(4.6, 5.4)
    # The base: rusticated stone with corner buttresses and a big arched door.
    k.add(box((-h - 0.2, -h - 0.2, 0), (h + 0.2, h + 0.2, 0.6), 0.05), pal["stone_dark"])
    k.add(box((-h, -h, 0.55), (h, h, zb), 0.05), stone, vary=0.02)
    for f in box_faces(0, 0, h, h).values():
        z = 0.65
        while z < zb - 0.4:
            k.add(f.box(-h + 0.05, h - 0.05, z, z + 0.5, 0.0, 0.05, back=False), jitter(stone, rng, 0.05), vary=0)
            z += 0.6
    for dx in (-1, 1):
        for dy in (-1, 1):
            k.add(box((dx * h - 0.55, dy * h - 0.55, 0), (dx * h + 0.55, dy * h + 0.55, zb + 0.4), 0.05), mul(stone, 0.92))
    front = Face((0, -h, 0), X, S)
    door(k, front, 0, 0.6, 1.6, 2.6, k.choice(pal["paint"]), mul(stone, 0.85), arch=True)
    for e in (-1, 1):
        lantern(k, front.p(e * 1.5, 2.8, 0.3), 1.1)
    k.add(box((-h - 0.3, -h - 0.3, zb), (h + 0.3, h + 0.3, zb + 0.35)), mul(stone, 1.05))
    # The shaft.
    s = h - 0.6
    zs = zb + u(15.0, 19.0)
    k.add(box((-s, -s, zb + 0.3), (s, s, zs), 0.05), brick_fn(brick, rng))
    for dx in (-1, 1):
        for dy in (-1, 1):
            k.add(box((dx * s - 0.35, dy * s - 0.35, zb + 0.3), (dx * s + 0.35, dy * s + 0.35, zs)), stone)
    z = zb + 4.2
    while z < zs - 1.5:
        for f in box_faces(0, 0, s, s).values():
            k.add(f.box(-s, s, z, z + 0.28, 0.0, 0.1, back=False), iron, ao=False)
            rivets(k, f, -s + 0.4, s - 0.4, z + 0.14, 0.1, 0.55, mul(iron, 1.5))
        z += 4.5
    for f in box_faces(0, 0, s, s).values():
        for zz in (zb + 2.0, zb + 7.5, zb + 12.0):
            if zz + 2.6 < zs - 0.5:
                arch_window(k, f, 0, zz, 0.7, 1.7, stone, bars=False)
    # The clock stage, wider, with a dial on each face.
    c = h - 0.3
    zc0, zc1 = zs, zs + u(5.0, 5.8)
    k.add(box((-c - 0.2, -c - 0.2, zc0 - 0.1), (c + 0.2, c + 0.2, zc0 + 0.35)), mul(stone, 1.05))
    k.add(box((-c, -c, zc0 + 0.3), (c, c, zc1)), stone, vary=0.02)
    k.add(box((-c - 0.3, -c - 0.3, zc1 - 0.1), (c + 0.3, c + 0.3, zc1 + 0.4), 0.05), mul(stone, 0.95))
    r = min(2.2, c - 0.8)
    for name, f in box_faces(0, 0, c, c).items():
        clock_face(k, f, 0, (zc0 + zc1) / 2 + 0.1, r, brass)
    # A gear train on show beside one dial.
    gf = Face((0, -c, 0), X, 2 * c)
    gs = rng.choice([-1, 1])
    gear(k, gf.p(gs * (c - 0.3), zc0 + 1.1, 0.05), X, Z, 0.9, 10, 0.12, mul(brass, 0.95))
    # Corner pinnacles.
    for dx in (-1, 1):
        for dy in (-1, 1):
            k.add(box((dx * c - 0.3, dy * c - 0.3, zc1 + 0.4), (dx * c + 0.3, dy * c + 0.3, zc1 + 1.6)), stone)
            k.add(cyl((dx * c, dy * c, zc1 + 1.6), (dx * c, dy * c, zc1 + 2.8), 0.32, 0.02, 4), copper_seams(copper), ao=False)
    # The belfry: four piers under a copper roof, a bell hanging inside.
    b = c - 0.7
    zf0, zf1 = zc1 + 0.4, zc1 + u(3.6, 4.2)
    for dx in (-1, 1):
        for dy in (-1, 1):
            k.add(box((dx * b - 0.45 * dx - 0.45, dy * b - 0.45 * dy - 0.45, zf0), (dx * b - 0.45 * dx + 0.45, dy * b - 0.45 * dy + 0.45, zf1)), brick_fn(brick, rng))
    k.add(box((-b, -b, zf0), (b, b, zf0 + 0.15)), mul(stone, 0.8))
    for f in box_faces(0, 0, b, b).values():
        k.add(f.box(-b, b, zf1 - 0.6, zf1, 0.0, 0.2, back=False), stone)
    k.add(cyl((0, 0, zf1 - 1.9), (0, 0, zf1 - 0.7), b * 0.55, b * 0.3, 10), brass, ao=False)
    k.add(box((-b, -0.08, zf1 - 0.75), (b, 0.08, zf1 - 0.6)), mul(iron, 1.4), ao=False)
    k.add(box((-b - 0.4, -b - 0.4, zf1), (b + 0.4, b + 0.4, zf1 + 0.3)), mul(stone, 0.95))
    # The spire: copper, eight-sided, a brass ball and a gear for a vane.
    zt = zf1 + 0.3 + u(6.0, 8.0)
    bm = cyl((0, 0, zf1 + 0.3), (0, 0, zt), b + 0.3, 0.06, 8)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 8, 3, "Z"))
    k.add(bm, copper_seams(copper, 0.35), ao=False)
    for e in (-1, 1):
        # Little lucarnes on the spire.
        zl = zf1 + 1.6
        y = e * (b - 0.2)
        k.add(box((-0.45, y - 0.35, zf1 + 0.3), (0.45, y + 0.35, zl + 0.6)), copper_seams(mul(copper, 0.9)), ao=False)
        k.add(Face((0, y + e * 0.36, 0), -X * e, 0.9).box(-0.3, 0.3, zf1 + 0.7, zl + 0.3, 0.0, 0.03, back=False), None, glow=True)
    k.add(sphere((0, 0, zt + 0.25), 0.35, 1), brass, ao=False)
    k.add(cyl((0, 0, zt + 0.5), (0, 0, zt + 2.0), 0.05, 0.05, 6), iron, ao=False)
    gear(k, Vector((0, 0.05, zt + 1.5)), X, Z, 0.45, 8, 0.06, brass)


def steampunk_mast(k):
    """An airship mooring mast: an iron lattice on a stone base with a winch house, a gallery
    at the top, a turning mooring head with a beacon, and (often) a small airship moored to it."""
    rng, pal = k.rng, k.pal
    u = rng.uniform
    iron, brass, stone = pal["iron"], pal["brass"], pal["stone"]
    copper = k.choice(pal["copper"])
    Hm = u(21.0, 25.0)
    rb, rt = u(2.6, 3.0), u(1.1, 1.3)
    k.add(box((-rb - 0.8, -rb - 0.8, 0), (rb + 0.8, rb + 0.8, 0.9), 0.06), pal["stone_dark"])
    k.add(box((-rb - 0.6, -rb - 0.6, 0.85), (rb + 0.6, rb + 0.6, 1.05)), stone)
    levels = 7
    corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]

    def leg(i, t):
        r = rb + (rt - rb) * t
        dx, dy = corners[i]
        return Vector((dx * r, dy * r, 1.0 + (Hm - 1.0) * t))
    for i in range(4):
        k.add(box(leg(i, 0) - Vector((0.3, 0.3, 1.0)), leg(i, 0) + Vector((0.3, 0.3, 0.25))), mul(stone, 0.9))
    for lv in range(levels):
        t0, t1 = lv / levels, (lv + 1) / levels
        for i in range(4):
            j = (i + 1) % 4
            strut(k, leg(i, t0), leg(i, t1), 0.16, iron)
            strut(k, leg(i, t1), leg(j, t1), 0.08, iron)
            strut(k, leg(i, t0), leg(j, t1), 0.06, mul(iron, 1.3))
            strut(k, leg(j, t0), leg(i, t1), 0.06, mul(iron, 1.3))
    # A lift cage up the middle, and a ladder.
    k.add(box((-0.6, -0.6, 1.0), (0.6, 0.6, 1.1)), iron, ao=False)
    for dx in (-1, 1):
        for dy in (-1, 1):
            strut(k, (dx * 0.6, dy * 0.6, 1.0), (dx * 0.6, dy * 0.6, Hm), 0.05, mul(iron, 1.4))
    zc = u(0.3, 0.7) * Hm
    k.add(box((-0.55, -0.55, zc), (0.55, 0.55, zc + 2.2)), lambda co, n: mul(brass, 0.9 if int(co.z / 0.3) % 2 else 1.0), ao=False)
    # The winch house at the foot.
    e = rng.choice([-1, 1])
    wx = e * (rb + 2.6)
    k.add(box((wx - 1.6, -1.8, 0), (wx + 1.6, 1.8, 3.0), 0.05), brick_fn(k.choice(pal["brick"]), rng))
    k.add(prism([(-2.0, 3.0), (2.0, 3.0), (0.0, 4.3)], wx - 1.8, wx + 1.8, lambda a, s_, z: Vector((a, s_, z))), copper_seams(copper))
    wf = Face((wx, -1.8, 0), X, 3.2)
    door(k, wf, -0.5, 0.0, 1.0, 2.1, k.choice(pal["paint"]), iron)
    arch_window(k, wf, 0.8, 1.0, 0.7, 0.9, stone, bars=True)
    k.add(cyl((wx - e * 1.6, 0, 1.5), (wx - e * 2.2, 0, 1.5), 0.8, 0.8, 12), lambda co, n: mul(iron, 1.3), ao=False)
    gear(k, Vector((wx, -1.85, 3.6)), X, Z, 0.5, 9, 0.08, brass)
    # The winch cable up to the head.
    k.add(cyl((wx - e * 2.2, 0, 2.3), (0, 0, Hm - 0.2), 0.03, 0.03, 4), (0.15, 0.13, 0.11), ao=False)
    # The gallery and mooring head.
    g = rt + 1.4
    bm = cyl((0, 0, Hm), (0, 0, Hm + 0.25), g, g, 8)
    k.add(bm, iron, ao=False)
    for i in range(8):
        t0, t1 = i / 8 * math.tau, (i + 1) / 8 * math.tau
        p0 = Vector((math.cos(t0) * (g - 0.05), math.sin(t0) * (g - 0.05), Hm + 0.25))
        p1 = Vector((math.cos(t1) * (g - 0.05), math.sin(t1) * (g - 0.05), Hm + 0.25))
        strut(k, p0, p0 + Z * 1.05, 0.04, iron)
        strut(k, p0 + Z * 1.05, p1 + Z * 1.05, 0.04, brass)
    k.add(cyl((0, 0, Hm + 0.25), (0, 0, Hm + 2.6), 0.9, 0.6, 10), copper_seams(copper), ao=False)
    k.add(cyl((0, 0, Hm + 2.6), (0, 0, Hm + 3.4), 0.75, 0.25, 10), brass, ao=False)
    k.add(sphere((0, 0, Hm + 3.7), 0.32, 1), None, glow=True)
    k.add(cyl((0, 0, Hm + 3.95), (0, 0, Hm + 4.3), 0.36, 0.05, 8), brass, ao=False)
    arm = rng.choice([-1, 1])
    k.add(box((-0.15, -0.15, Hm + 1.5), (arm * 2.4, 0.15, Hm + 1.8)), iron, ao=False)
    k.add(cyl((arm * 2.4, 0, Hm + 1.65), (arm * 3.0, 0, Hm + 1.65), 0.35, 0.12, 8), brass, ao=False)
    if rng.random() < 0.7:
        # A small airship moored nose-on to the head, drifting off on its line.
        L = u(13.0, 16.0)
        R = u(2.3, 2.8)
        cx = arm * (3.0 + L / 2 + 0.2)
        cz = Hm + 1.65 + u(-0.3, 0.6)
        canvas = k.choice([(0.82, 0.74, 0.58), (0.62, 0.24, 0.20), (0.70, 0.66, 0.60), (0.36, 0.42, 0.38)])
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        for v in bm.verts:
            x = v.co.x
            v.co.x = cx + x * L / 2
            # A blunter nose than tail.
            taper = 1.0 - 0.18 * max(0.0, x * arm * -1)
            v.co.y *= R * taper
            v.co.z = cz + v.co.z * R * taper
        k.add(bm, lambda co, n: mul(canvas, (0.9 if int(math.floor((co.x + 50) / 1.4)) % 2 else 1.0) * (1.05 if n.z > 0.3 else 0.92)), soft=Vector((cx, 0, cz)))
        for t in (-0.3, 0.05, 0.4):
            x = cx + t * L
            rr = R * math.sqrt(max(0.05, 1 - (2 * t) ** 2)) * (1.0 - 0.18 * max(0.0, 2 * t * arm * -1)) + 0.04
            k.add(cyl((x - 0.08, 0, cz), (x + 0.08, 0, cz), rr, rr, 14), brass, ao=False)
        # Tail fins.
        tx = cx - arm * L * 0.42
        for ang in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
            d = Vector((0, math.cos(ang), math.sin(ang)))
            p0 = Vector((tx, 0, cz)) + d * R * 0.45
            k.add(prism([(0.0, 0.0), (arm * 2.6, 0.0), (arm * 0.4, 1.7)], -0.06, 0.06,
                        lambda w, s_, z, p0=p0, d=d, ang=ang: p0 + Vector((-s_, 0, 0)) + d * z + Vector((0, -math.sin(ang), math.cos(ang))) * w), k.choice(pal["paint"]))
        # The gondola, its lit windows and a propeller each side.
        gz = cz - R - 0.9
        k.add(box((cx - 2.6, -0.8, gz - 0.6), (cx + 2.0, 0.8, gz + 0.6), 0.1), k.choice(pal["paint"]))
        for e2 in (-1, 1):
            gf = Face((cx - 0.3, e2 * 0.8, 0), -X * e2, 4.6)
            for a in (-1.4, -0.4, 0.6, 1.6):
                k.add(gf.box(a - 0.3, a + 0.3, gz - 0.2, gz + 0.35, 0.0, 0.03, back=False), None, glow=True)
            k.add(box((cx - 1.0, e2 * 0.8, gz + 0.2), (cx - 0.8, e2 * 1.6, gz + 0.35)), iron, ao=False)
            gear(k, Vector((cx - 1.0 - arm * 0.2, e2 * 1.75, gz + 0.28)), Y, Z, 0.7, 4, 0.06, brass)
        for xs in (-1.5, 1.0):
            strut(k, (cx + xs, 0, gz + 0.6), (cx + xs, 0, cz - R * 0.9), 0.05, iron)
        # The mooring line.
        sag_line(k, (arm * 3.0, 0, Hm + 1.65), (cx - arm * L / 2, 0, cz), 0.25, 0.05, (0.2, 0.17, 0.13), seg=3, surface="cloth")


def sp_hall(k, W, D, zw, brick, stone, front_door=True):
    """A brick works hall with arched windows between pilasters; returns its faces."""
    faces = sp_walls(k, -W / 2, W / 2, -D / 2, D / 2, 0.0, zw, brick, stone)
    for name, f in faces.items():
        L = f.length
        n = max(1, round(L / 3.4))
        for i in range(n):
            a = -L / 2 + (i + 0.5) * L / n
            if name == "front" and abs(a) < 2.8:
                continue
            arch_window(k, f, a, 2.0, min(1.6, L / n - 1.1), zw - 4.2, stone, bars=True)
    return faces


def steampunk_works(k):
    """A foundry (a furnace mouth glowing in its great arch, a lit clerestory, squat stacks, a
    ladle on rails and a gantry crane) or a gear-works (a train of huge gears on the front, a
    glazed lantern roof, steam pipes)."""
    rng, pal, form = k.rng, k.pal, k.form
    u = rng.uniform
    brick, stone, iron, brass = k.choice(pal["brick"]), pal["stone"], pal["iron"], pal["brass"]
    copper = k.choice(pal["copper"])
    W, D = u(16.0, 20.0), u(11.0, 13.0)
    zw = u(8.0, 9.0)
    hx, hy = W / 2, D / 2
    faces = sp_hall(k, W, D, zw, brick, stone)
    front = faces["front"]
    # A pitched slate roof with a raised clerestory along the ridge.
    rise = D * 0.28
    k.add(prism([(-hy - 0.5, zw), (hy + 0.5, zw), (hy + 0.5, zw + 0.25), (0.0, zw + rise + 0.25), (-hy - 0.5, zw + 0.25)], -hx - 0.4, hx + 0.4,
                lambda a, s_, z: Vector((a, s_, z))), lambda co, n: mul((0.30, 0.32, 0.36), 0.92 if int(co.z / 0.5) % 2 else 1.0), ao=False)
    for e in (-1, 1):
        k.add(prism([(-hy, zw), (hy, zw), (0.0, zw + rise)], e * hx - 0.1, e * hx + 0.1, lambda a, s_, z: Vector((a, s_, z))), brick_fn(brick, rng))
    cl = W * 0.7
    k.add(box((-cl / 2, -1.6, zw + rise - 0.6), (cl / 2, 1.6, zw + rise + 1.4)), mul(iron, 1.2), ao=False)
    for e in (-1, 1):
        cf = Face((0, e * 1.6, 0), -X * e, cl)
        for i in range(int(cl / 1.5)):
            a = -cl / 2 + (i + 0.5) * cl / int(cl / 1.5)
            k.add(cf.box(a - 0.55, a + 0.55, zw + rise - 0.3, zw + rise + 1.1, 0.0, 0.03, back=False), None, glow=form == "foundry" or rng.random() < 0.5)
    k.add(prism([(-1.9, zw + rise + 1.4), (1.9, zw + rise + 1.4), (0.0, zw + rise + 2.3)], -cl / 2 - 0.2, cl / 2 + 0.2, lambda a, s_, z: Vector((a, s_, z))), copper_seams(copper))
    if form == "foundry":
        # The furnace arch: dark iron doors pushed back, the fire glowing deep inside.
        aw, ah = 4.4, 4.8
        n = 8
        k.add(front.poly([(-aw / 2, 0.6), (aw / 2, 0.6)] + [(math.cos(math.pi * i / n) * aw / 2, 0.6 + ah - aw / 2 + math.sin(math.pi * i / n) * aw / 2) for i in range(n + 1)], -0.05, 0.03), None, glow="amber")
        for i in range(n):
            a0, a1 = math.pi * i / n, math.pi * (i + 1) / n
            rr0, rr1 = aw / 2 + 0.05, aw / 2 + 0.6
            zc = 0.6 + ah - aw / 2
            q = [(math.cos(a0) * rr0, zc + math.sin(a0) * rr0), (math.cos(a0) * rr1, zc + math.sin(a0) * rr1), (math.cos(a1) * rr1, zc + math.sin(a1) * rr1), (math.cos(a1) * rr0, zc + math.sin(a1) * rr0)]
            k.add(front.poly(q, 0.0, 0.25 if i == n // 2 else 0.18), mul(stone, 1.05 if i == n // 2 else u(0.88, 0.98)), vary=0)
        for e in (-1, 1):
            k.add(front.box(e * aw / 2 - 0.25, e * aw / 2 + 0.25, 0.6, zc, 0.0, 0.25), stone)
            k.add(front.obox(e * (aw / 2 + 0.9), 0.6 + 1.9, 1.8, 3.8, 0.1, 0.25, e * 0.25), mul(iron, 1.2))
        # Squat stacks with copper caps.
        for i in range(rng.choice([2, 3])):
            sx = -hx + 2.5 + i * (W - 5.0) / 2
            sy = hy * 0.4
            k.add(cyl((sx, sy, zw), (sx, sy, zw + rise + u(4.0, 6.0)), 0.9, 0.75, 10), brick_fn(mul(brick, 0.85), rng))
            k.add(cyl((sx, sy, zw + rise + 4.0), (sx, sy, zw + rise + 4.5), 0.95, 0.95, 10), iron, ao=False)
        # A ladle on rails out front, glowing, and ingots stacked by the wall.
        lx = rng.choice([-1, 1]) * u(3.0, 4.5)
        for e in (-1, 1):
            k.add(box((lx - 2.0, -hy - 2.2 + e * 0.6 - 0.06, 0), (lx + 2.0, -hy - 2.2 + e * 0.6 + 0.06, 0.12)), mul(iron, 1.3), ao=False)
        k.add(box((lx - 0.9, -hy - 3.0, 0.12), (lx + 0.9, -hy - 1.4, 0.6)), iron, ao=False)
        k.add(cyl((lx, -hy - 2.2, 0.6), (lx, -hy - 2.2, 1.8), 0.7, 0.85, 12), mul(iron, 1.1), ao=False)
        k.add(cyl((lx, -hy - 2.2, 1.78), (lx, -hy - 2.2, 1.82), 0.78, 0.78, 12), None, glow="amber")
        ix = -lx
        for r in range(3):
            for i in range(4 - r):
                k.add(box((ix - 1.0 + i * 0.5 + r * 0.25, -hy - 1.2, r * 0.18), (ix - 0.6 + i * 0.5 + r * 0.25, -hy - 0.4, r * 0.18 + 0.16)), brass, ao=False)
        # A gantry crane over the yard.
        for e in (-1, 1):
            k.add(box((e * 3.2 - 0.15, -hy - 4.0, 0), (e * 3.2 + 0.15, -hy - 3.7, 6.0)), iron, ao=False)
        k.add(box((-3.5, -hy - 4.05, 6.0), (3.5, -hy - 3.65, 6.4)), mul(iron, 1.2), ao=False)
        k.add(box((-0.3, -hy - 4.1, 5.6), (0.3, -hy - 3.6, 6.0)), brass, ao=False)
        k.add(cyl((0, -hy - 3.85, 5.6), (0, -hy - 3.85, 3.6), 0.02, 0.02, 4), (0.2, 0.18, 0.15), ao=False)
        k.add(box((-0.15, -hy - 3.95, 3.3), (0.15, -hy - 3.75, 3.6)), iron, ao=False)
    else:
        # Big doors, and a gear train across the front above them.
        dw = 3.2
        k.add(front.box(-dw / 2, dw / 2, 0.6, 4.6, -0.02, 0.1), k.choice(pal["paint"]))
        k.add(front.box(-dw / 2 - 0.2, dw / 2 + 0.2, 4.6, 4.9, 0.0, 0.25), iron)
        for e in (-1, 1):
            k.add(front.obox(0, 2.6, math.hypot(dw, 4.0), 0.14, 0.1, 0.16, math.atan2(4.0, dw) * e), iron)
        gz = u(6.4, 7.2)
        big = u(2.0, 2.4)
        x = rng.choice([-1, 1]) * u(0.0, 1.0)
        gear(k, front.p(x, gz, 0.35), X, Z, big, 16, 0.25, brass)
        r2 = big * u(0.45, 0.6)
        x2 = x + (big + r2) * 0.92
        gear(k, front.p(x2, gz + 0.8, 0.35), X, Z, r2, 10, 0.22, mul(copper, 1.1))
        r3 = big * u(0.5, 0.7)
        x3 = x - (big + r3) * 0.92
        gear(k, front.p(x3, gz - 0.6, 0.35), X, Z, r3, 12, 0.22, mul(brass, 0.85))
        k.add(cyl(front.p(x, gz, 0.0), front.p(x, gz, 0.7), 0.25, 0.25, 8), iron, ao=False)
        # A water tower on legs at a back corner, feeding the pipes.
        tx, ty = rng.choice([-1, 1]) * (hx - 2.0), hy + 2.2
        for dx in (-1, 1):
            for dy in (-1, 1):
                strut(k, (tx + dx * 1.2, ty + dy * 1.2, 0), (tx + dx * 0.9, ty + dy * 0.9, 9.0), 0.1, iron)
        k.add(cyl((tx, ty, 9.0), (tx, ty, 11.4), 1.5, 1.5, 12), lambda co, n: mul((0.45, 0.32, 0.22), 0.9 if int(co.z / 0.4) % 2 else 1.0), ao=False)
        k.add(cyl((tx, ty, 11.4), (tx, ty, 12.3), 1.65, 0.1, 12), copper_seams(copper), ao=False)
        pipe_run(k, [(tx, ty - 1.4, 10.0), (tx, hy + 0.2, 10.0), (tx, hy + 0.2, zw - 1.0)], 0.2, copper)
    for e in (-1, 1):
        lantern(k, front.p(e * (2.8 if form != "foundry" else 3.4), 3.0, 0.4), 1.2)
    pipe_run(k, [faces["right"].p(-hy * 0.5, 0.0, 0.3), faces["right"].p(-hy * 0.5, zw - 1.5, 0.3), faces["right"].p(hy * 0.5, zw - 1.5, 0.3)], 0.18, copper)


def steampunk_hall(k):
    """The exchange: a stone hall on a stepped podium, a portico of columns with a pediment and
    a lit clock, arched windows, and a copper dome on a windowed drum with a lantern and a brass
    gear finial."""
    rng, pal = k.rng, k.pal
    u = rng.uniform
    stone, brass, iron = pal["stone"], pal["brass"], pal["iron"]
    copper = k.choice(pal["copper"])
    W, D = u(16.0, 19.0), u(13.0, 16.0)
    hx, hy = W / 2, D / 2
    pod = 1.2
    zw = pod + u(8.5, 9.5)
    steps = 6
    k.add(box((-hx - 0.3, -hy - 0.3, 0), (hx + 0.3, hy + 0.3, pod), 0.05), pal["stone_dark"])
    pw = W * 0.62
    for i in range(steps):
        z = pod - i * pod / steps
        k.add(box((-pw / 2 - 0.3 * i, -hy - 3.4 - i * 0.35, 0), (pw / 2 + 0.3 * i, -hy - 3.4 - (i - 1) * 0.35, z), 0.03), mul(stone, 1.0 - 0.02 * i))
    k.add(box((-pw / 2, -hy - 3.4, 0), (pw / 2, -hy, pod)), stone)
    # The main block: rusticated base, smooth upper storey, cornice and balustrade.
    k.add(box((-hx, -hy, pod), (hx, hy, zw)), stone, vary=0.02)
    faces = box_faces(0, 0, hx, hy)
    for name, f in faces.items():
        L = f.length
        z = pod + 0.1
        while z < pod + 3.8:
            k.add(f.box(-L / 2, L / 2, z, z + 0.5, 0.0, 0.05, back=False), jitter(stone, rng, 0.04), vary=0)
            z += 0.6
        k.add(f.box(-L / 2 - 0.1, L / 2 + 0.1, pod + 3.9, pod + 4.2, 0.0, 0.2), mul(stone, 1.05))
        k.add(f.box(-L / 2 - 0.35, L / 2 + 0.35, zw - 0.45, zw, 0.0, 0.4, bevel=0.04), mul(stone, 1.05))
        k.add(f.box(-L / 2 - 0.2, L / 2 + 0.2, zw, zw + 1.0, 0.0, 0.25), mul(stone, 0.95))
        n = max(2, round(L / 3.0))
        for i in range(n):
            a = -L / 2 + (i + 0.5) * L / n
            if name == "front" and abs(a) < pw / 2:
                continue
            arch_window(k, f, a, pod + 1.0, 1.1, 1.7, mul(stone, 0.85), bars=True)
            arch_window(k, f, a, pod + 5.0, 1.1, 2.1, mul(stone, 0.85), bars=False)
    # The portico.
    py = -hy - 3.0
    cols = rng.choice([4, 6]) if pw > 9.5 else 4
    ch = zw - pod - 1.2
    for i in range(cols):
        x = -pw / 2 + 0.6 + i * (pw - 1.2) / (cols - 1)
        k.add(box((x - 0.55, py - 0.55, pod), (x + 0.55, py + 0.55, pod + 0.4)), mul(stone, 1.05))
        k.add(cyl((x, py, pod + 0.4), (x, py, pod + 0.4 + ch), 0.42, 0.36, 10), mul(stone, 1.08), ao=False)
        k.add(box((x - 0.55, py - 0.55, pod + 0.4 + ch), (x + 0.55, py + 0.55, pod + 0.8 + ch)), brass)
    ze = pod + 0.8 + ch
    k.add(box((-pw / 2 - 0.2, py - 0.8, ze), (pw / 2 + 0.2, -hy, ze + 0.9)), mul(stone, 1.05))
    rivets(k, Face((0, py - 0.8, 0), X, pw), -pw / 2 + 0.3, pw / 2 - 0.3, ze + 0.45, 0.0, 0.6, brass)
    pr_ = 2.0
    k.add(prism([(-pw / 2 - 0.4, ze + 0.9), (pw / 2 + 0.4, ze + 0.9), (0.0, ze + 0.9 + pr_)], py - 0.9, -hy, lambda w, s_, z: Vector((s_, w, z))), mul(stone, 1.02))
    pf = Face((0, py - 0.9, 0), X, pw)
    rake = math.atan2(pr_, pw / 2 + 0.4)
    for e in (-1, 1):
        k.add(pf.obox(e * (pw / 4 + 0.2), ze + 0.95 + pr_ / 2, math.hypot(pw / 2 + 0.8, pr_), 0.3, -0.1, 0.2, -e * rake), copper_seams(copper))
    clock_face(k, Face((0, py - 1.0, 0), X, pw), 0.0, ze + 1.55, 0.7, brass)
    door(k, Face((0, -hy, 0), X, W), 0.0, pod, 1.8, 3.2, k.choice(pal["paint"]), mul(stone, 0.85), arch=True)
    for e in (-1, 1):
        lantern(k, (e * 1.6, -hy - 0.3, pod + 2.7), 1.3)
    # The dome on its drum.
    dr = min(hx, hy) * u(0.48, 0.56)
    zd = zw + 1.0
    k.add(cyl((0, 0, zw), (0, 0, zd + 2.4), dr + 0.2, dr + 0.2, 16), mul(stone, 0.98))
    for i in range(8):
        t = i / 8 * math.tau
        f = Face((math.cos(t) * (dr + 0.2), math.sin(t) * (dr + 0.2), 0), Vector((-math.sin(t), math.cos(t), 0)), 1.0)
        f.n = Vector((math.cos(t), math.sin(t), 0))
        k.add(f.box(-0.4, 0.4, zd + 0.3, zd + 1.9, 0.0, 0.05, back=False), None, glow=rng.random() < 0.6)
    k.add(cyl((0, 0, zd + 2.4), (0, 0, zd + 2.7), dr + 0.45, dr + 0.45, 16), mul(stone, 1.05))
    rings = 6
    for i in range(rings):
        t0, t1 = i / rings, (i + 1) / rings
        r0, r1 = (dr + 0.3) * math.cos(t0 * math.pi / 2), (dr + 0.3) * math.cos(t1 * math.pi / 2)
        z0, z1 = zd + 2.7 + (dr + 0.3) * 0.95 * math.sin(t0 * math.pi / 2), zd + 2.7 + (dr + 0.3) * 0.95 * math.sin(t1 * math.pi / 2)
        k.add(cyl((0, 0, z0), (0, 0, z1), r0, max(0.5, r1), 16), copper_seams(copper, 0.5), ao=False)
    zt = zd + 2.7 + (dr + 0.3) * 0.95
    k.add(cyl((0, 0, zt - 0.1), (0, 0, zt + 1.4), 0.55, 0.55, 8), brass, ao=False)
    k.add(cyl((0, 0, zt + 0.2), (0, 0, zt + 1.1), 0.58, 0.58, 8), None, glow=True)
    k.add(cyl((0, 0, zt + 1.4), (0, 0, zt + 2.2), 0.7, 0.05, 8), copper_seams(copper), ao=False)
    gear(k, Vector((0, 0.04, zt + 2.7)), X, Z, 0.55, 10, 0.06, brass)


def steampunk_arcade(k):
    """A market arcade: iron columns carrying a barrel vault of glass on iron ribs, lunettes of
    radiating glazing bars at the ends, gas lamps hanging inside, and stalls under it."""
    rng, pal = k.rng, k.pal
    u = rng.uniform
    iron, brass, stone = pal["iron"], pal["brass"], pal["stone"]
    paint = k.choice(pal["paint"])
    L, Wd = u(16.0, 24.0), u(8.0, 10.0)
    hx, hy = L / 2, Wd / 2
    zc = u(5.0, 5.6)
    k.add(box((-hx - 0.3, -hy - 0.3, 0), (hx + 0.3, hy + 0.3, 0.2)), lambda co, n: mul(stone, 0.92 if (int(co.x + 50) + int(co.y + 50)) % 2 else 1.0), ao=False)
    bays = max(4, round(L / 3.2))
    xs = [-hx + i * L / bays for i in range(bays + 1)]
    for x in xs:
        for e in (-1, 1):
            y = e * hy
            k.add(box((x - 0.3, y - 0.3, 0.2), (x + 0.3, y + 0.3, 0.6)), stone)
            k.add(cyl((x, y, 0.6), (x, y, zc), 0.16, 0.14, 8), paint, ao=False)
            k.add(box((x - 0.28, y - 0.28, zc - 0.1), (x + 0.28, y + 0.28, zc + 0.15)), brass, ao=False)
            # Curly brackets as a slanted strut.
            strut(k, (x, y, zc - 1.0), (x, y - e * 0.8, zc + 0.1), 0.05, iron)
    for e in (-1, 1):
        k.add(box((-hx - 0.1, e * hy - 0.25, zc + 0.1), (hx + 0.1, e * hy + 0.25, zc + 0.6)), paint, ao=False)
        rivets(k, Face((0, e * hy + 0.25 * e, 0), -X * e, L), -hx + 0.2, hx - 0.2, zc + 0.35, 0.0, 0.5, brass)
    # The vault: glass panels between ribs.
    n = 10
    R = hy + 0.15
    glassc = (0.48, 0.62, 0.66)
    prof = [(math.cos(math.pi * i / n) * R, math.sin(math.pi * i / n) * R * 0.75) for i in range(n + 1)]
    inner = [(x * 0.98, y * 0.98) for x, y in reversed(prof)]
    k.add(prism(prof + inner, -hx, hx, lambda a, s_, z: Vector((a, s_, zc + 0.6 + z))), lambda co, nn: mul(glassc, 1.08 if nn.z > 0.7 else 0.95), ao=False)
    for x in xs:
        ring = [(math.cos(math.pi * j / n) * (R + 0.06), math.sin(math.pi * j / n) * (R * 0.75 + 0.06)) for j in range(n + 1)]
        k.add(prism(ring + [(x2 * 0.95, y2 * 0.95) for x2, y2 in reversed(ring)], x - 0.08, x + 0.08, lambda a, s_, z: Vector((a, s_, zc + 0.6 + z))), iron, ao=False)
    for j in range(1, n):
        t = math.pi * j / n
        y, z = math.cos(t) * (R + 0.04), math.sin(t) * (R * 0.75 + 0.04)
        k.add(box((-hx, y - 0.04, zc + 0.6 + z - 0.04), (hx, y + 0.04, zc + 0.6 + z + 0.04)), iron, ao=False)
    k.add(box((-hx - 0.2, -0.3, zc + 0.6 + R * 0.75), (hx + 0.2, 0.3, zc + 0.9 + R * 0.75)), brass, ao=False)
    # End lunettes.
    for e in (-1, 1):
        lf = Face((e * hx, 0, 0), Y * e, Wd)
        k.add(lf.poly([(math.cos(math.pi * i / n) * R * 0.97, zc + 0.6 + math.sin(math.pi * i / n) * R * 0.73) for i in range(n + 1)], -0.03, 0.0), None, glow=rng.random() < 0.5)
        for i in range(1, n, 2):
            t = math.pi * i / n
            ex, ez = math.cos(t) * R * 0.95, math.sin(t) * R * 0.71
            k.add(lf.obox(ex / 2, zc + 0.6 + ez / 2, math.hypot(ex, ez), 0.08, 0.0, 0.06, math.atan2(ez, ex)), iron, ao=False)
        k.add(lf.box(-hy, hy, zc + 0.5, zc + 0.7, 0.0, 0.1, back=False), paint, ao=False)
        k.add(lf.box(-1.4, 1.4, zc - 0.2, zc + 0.4, 0.05, 0.2, back=False), mul(paint, 0.7), ao=False)
        for i in range(5):
            k.add(lf.box(-1.2 + i * 0.55, -0.95 + i * 0.55, zc - 0.1, zc + 0.3, 0.2, 0.24, back=False), brass, ao=False)
    # Hanging gas lamps down the middle.
    for x in xs[1:-1:2]:
        k.add(cyl((x, 0, zc + 0.6 + R * 0.75), (x, 0, zc - 0.4), 0.025, 0.025, 4), iron, ao=False)
        lantern(k, (x, 0, zc - 0.7), 1.3)
    # Stalls along both sides: counters, awnings and goods.
    cloths = [(0.70, 0.22, 0.18), (0.20, 0.36, 0.30), (0.82, 0.62, 0.26), (0.30, 0.30, 0.48)]
    for e in (-1, 1):
        for i in range(bays):
            if rng.random() < 0.25:
                continue
            x0, x1 = xs[i] + 0.35, xs[i + 1] - 0.35
            y0 = e * (hy - 1.6)
            y1 = e * (hy - 0.5)
            k.add(box((x0, min(y0, y1), 0.2), (x1, max(y0, y1), 1.1)), mul(pal["timber"], 1.3))
            c = k.choice(cloths)
            k.add(prism([(e * (hy - 0.4), 2.7), (e * (hy - 2.2), 2.2), (e * (hy - 2.2), 2.28), (e * (hy - 0.4), 2.78)], x0, x1, lambda a, s_, z: Vector((a, s_, z))),
                  lambda co, nn, c=c: c if int(math.floor(co.x / 0.5)) % 2 else tagged((0.92, 0.88, 0.78), getattr(c, "surface", None)), ao=False)
            for j in range(3):
                gx = x0 + (j + 0.5) * (x1 - x0) / 3
                g = tagged(k.choice([(0.85, 0.3, 0.2), (0.9, 0.7, 0.25), (0.5, 0.65, 0.3), brass]), "cloth")
                k.add(box((gx - 0.25, e * (hy - 1.3) - 0.2, 1.1), (gx + 0.25, e * (hy - 1.3) + 0.2, 1.35)), g, ao=False)
            for x in (x0, x1):
                k.add(box((x - 0.04, e * (hy - 0.5) - 0.04, 1.1), (x + 0.04, e * (hy - 0.5) + 0.04, 2.75)), pal["timber"], ao=False)


# ---------------------------------------------------------------------------------------------
# Cyberpunk: stacked concrete blocks and slender towers with setbacks, grimy shopfronts behind
# shutters, neon blade signs, holo-billboards, rooftop tanks and antennas, hanging cables.
# Chunky and readable from the game camera: few big masses, every storey a band, every sign a
# glowing slab with glyphs, not text.

# Glyph strokes in a unit cell (x0, x1, z0, z1): 2-3 of them make a sign character.
STROKES = [(0, 1, 0.82, 1), (0, 1, 0.41, 0.59), (0, 1, 0, 0.18), (0, 0.18, 0, 1), (0.41, 0.59, 0, 1), (0.82, 1, 0, 1),
           (0, 0.18, 0.5, 1), (0.82, 1, 0, 0.5), (0, 0.55, 0.41, 0.59), (0.45, 1, 0.82, 1), (0.41, 0.59, 0, 0.5)]


def cp_colours(k):
    """One building's colours: wall, panels, trim and its two neon colours."""
    rng, pal = k.rng, k.pal
    neons = rng.sample(["pink", "cyan", "amber"], 2)
    return dict(wall=k.choice(pal["concrete"]), panel=k.choice(pal["panel"]), trim=k.choice(pal["trim"]), neon=neons,
                metal=pal["metal"], dark=pal["dark"], awning=k.choice(pal["awning"]))


def grime(c, dirty=6.0, floor=0.55):
    """Concrete darkened towards the street, with faint vertical streaks of runoff."""
    def fn(co, n):
        t = min(1.0, max(0.0, co.z / dirty)) ** 0.7
        streak = noise.noise(Vector((co.x * 0.8 + co.y * 0.8, 0.5, co.z * 0.05)))
        return mul(c, (floor + (1 - floor) * t) * (0.93 + 0.09 * streak))
    return fn


def stripes(c, every=0.12, dark=0.78, axis=2):
    """Corrugation (shutters, roof sheets) as alternating shades along one axis."""
    def fn(co, n):
        return mul(c, dark if int(math.floor(co[axis] / every)) % 2 else 1.0)
    return fn


def hazard(a, b, every=0.35):
    def fn(co, n):
        return a if int(math.floor((co.x + co.y + co.z) / every)) % 2 else b
    return fn


def flipped(f):
    """The same wall face, seen from its other side (for both faces of a blade sign)."""
    g = Face(f.o, f.u, f.length)
    g.n = -f.n
    return g


def cp_glyphs(k, f, a0, z0, n, gw, gh, gap, w, color, vertical=False):
    """n sign characters, each 2-3 glowing strokes, in a row (or a column down from z0)."""
    t = 0.05
    for i in range(n):
        ga = a0 if vertical else a0 + i * (gw + gap)
        gz = z0 - (i + 1) * gh - i * gap if vertical else z0
        for x0, x1, s0, s1 in k.pr.sample(STROKES, k.pr.choice([2, 2, 3])):
            # Flat strokes: the glow needs no thickness, and a sign is many of them.
            k.add(f.quad(ga + x0 * gw, ga + x1 * gw, gz + s0 * gh, gz + s1 * gh, w + t), None, glow=color, closed=False)


def cp_blade(k, f, a, ztop, h, out, color, frame, color2=None):
    """A vertical blade sign standing out of a wall face at `a`: a dark slab with a glowing
    border and a column of characters on both faces, on two brackets."""
    t = 0.4
    fb = Face(f.p(a, 0, 0), f.n, out)
    z0 = ztop - h
    k.add(fb.box(0.25, out, z0, ztop, -t / 2, t / 2), frame, ao=False)
    for z in (z0 + 0.3, ztop - 0.3):
        k.add(fb.box(0.0, 0.3, z - 0.1, z + 0.1, -0.08, 0.08), k.pal["metal"], ao=False)
    gw = (out - 0.25) * 0.56
    gh = gw * 0.9
    n = max(1, int((h - 0.5) / (gh + 0.18)))
    for side in (fb, flipped(fb)):
        e = 0.06
        for a0, a1, za, zb in ((0.3, out - 0.05, ztop - 0.13, ztop - 0.05), (0.3, out - 0.05, z0 + 0.05, z0 + 0.13),
                               (0.3, 0.38, z0 + 0.05, ztop - 0.05), (out - 0.13, out - 0.05, z0 + 0.05, ztop - 0.05)):
            k.add(side.box(a0, a1, za, zb, t / 2, t / 2 + e, back=False), None, glow=color2 or color)
        cp_glyphs(k, side, 0.25 + (out - 0.25 - gw) / 2, ztop - 0.3, n, gw, gh, 0.18, t / 2, color, vertical=True)


def cp_board(k, f, a0, a1, z0, z1, color, frame, w=0.0):
    """A horizontal shop sign: a dark board with a row of glowing characters and a tube under it."""
    k.add(f.box(a0, a1, z0, z1, w, w + 0.18, back=False), frame, ao=False)
    h = z1 - z0
    gh = h * 0.6
    gw = gh * 0.85
    n = max(1, int((a1 - a0 - 0.3) / (gw + 0.14)))
    span = n * gw + (n - 1) * 0.14
    cp_glyphs(k, f, (a0 + a1) / 2 - span / 2, z0 + h * 0.2, n, gw, gh, 0.14, w + 0.18, color)
    k.add(f.box(a0 + 0.05, a1 - 0.05, z0 - 0.08, z0 - 0.02, w + 0.1, w + 0.16), None, glow=color)


def cp_screen(k, f, a, z0, w, h, c1, c2, out=0.25):
    """A holo-billboard: a thin frame holding a glowing picture (a field, a figure and a band in
    a second colour), crossed by dark scan lines, off the wall on an emitter bar."""
    dark, metal = k.pal["dark"], k.pal["metal"]
    k.add(f.box(a - w / 2 - 0.12, a + w / 2 + 0.12, z0 - 0.35, z0 - 0.1, 0.0, out + 0.25), metal, ao=False)
    k.add(f.box(a - w / 2 + 0.2, a + w / 2 - 0.2, z0 - 0.12, z0 - 0.04, out, out + 0.1), None, glow=c1)
    k.add(f.box(a - w / 2, a + w / 2, z0, z0 + h, out, out + 0.06, back=False), None, glow=c1)
    rng = k.pr
    # The picture: a face-like disc or a product block, and a band.
    if rng.random() < 0.5:
        r = min(w, h) * rng.uniform(0.22, 0.32)
        ca = a + rng.uniform(-0.25, 0.25) * w
        k.add(cyl(f.p(ca, z0 + h * 0.55, out + 0.06), f.p(ca, z0 + h * 0.55, out + 0.1), r, r, 12), None, glow=c2)
    else:
        bw, bh = w * rng.uniform(0.2, 0.32), h * rng.uniform(0.45, 0.7)
        ca = a + rng.choice([-1, 1]) * w * 0.25
        k.add(f.box(ca - bw / 2, ca + bw / 2, z0 + h * 0.15, z0 + h * 0.15 + bh, out + 0.06, out + 0.1, back=False), None, glow=c2)
    k.add(f.box(a - w / 2, a + w / 2, z0 + h * 0.08, z0 + h * 0.2, out + 0.06, out + 0.1, back=False), None, glow=c2)
    for i in range(1, 5):
        z = z0 + h * i / 5
        k.add(f.box(a - w / 2, a + w / 2, z - 0.035, z + 0.035, out + 0.1, out + 0.13, back=False), dark, ao=False, vary=0)
    for e in (-1, 1):
        k.add(f.box(a + e * w / 2 - 0.05, a + e * w / 2 + 0.05, z0, z0 + h, out - 0.02, out + 0.12, back=False), dark, ao=False)


def sag_line(k, p0, p1, sag, r, color, seg=6, sides=4, surface="plastic"):
    """A cable hanging between two points (a parabola, close enough to a catenary)."""
    p0, p1 = Vector(p0), Vector(p1)
    pts = [p0.lerp(p1, i / seg) - Z * sag * 4 * (i / seg) * (1 - i / seg) for i in range(seg + 1)]
    for a, b in zip(pts, pts[1:]):
        k.add(cyl(a, b, r, r, sides), color if getattr(color, "surface", None) else tagged(color, surface), ao=False, vary=0.05)
    return pts


def cp_ac(k, f, a, z, metal):
    """A wall air-conditioner: a box on a bracket with a dark fan disc."""
    k.extra(f.box(a - 0.45, a + 0.45, z, z + 0.62, 0.0, 0.5, back=False), mul(metal, 1.25), ao=False)
    k.add(f.quad(a - 0.2, a + 0.3, z + 0.08, z + 0.54, 0.51), k.pal["dark"], ao=False, closed=False, vary=0)


def cp_storeys(k, P, x0, x1, y0, y1, z0, n, hs, wins, lit=0.55, bay=2.1, fins=True, clutter=True, glazing=None):
    """Upper storeys from z0: a wall box per storey (grimy towards the street), a slab band at
    each floor, and on each face in `wins` (face: chance of a lit window) a glazed bay between
    fins. Windows are lit warm, tinted by a neon now and then, dark, or show pale blinds."""
    rng, pal = k.rng, k.pal
    wall, panel = P["wall"], P["panel"]
    # Punched windows, or ribbon glazing between the fins with lit runs of offices.
    ribbon = (glazing or P.setdefault("glazing", rng.choice(["punched", "ribbon", "ribbon"]))) == "ribbon"
    for s in range(n):
        za, zb = z0 + s * hs, z0 + (s + 1) * hs
        k.add(box((x0, y0, za - 0.01), (x1, y1, zb)), grime(wall), ao=False, vary=0.02)
        k.add(box((x0 - 0.12, y0 - 0.12, zb - 0.3), (x1 + 0.12, y1 + 0.12, zb)), grime(mul(panel, 1.2), 10.0, 0.7), ao=False, vary=0.0)
    faces = box_faces((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2)
    for name, f in faces.items():
        p = wins.get(name, 0.0)
        if p <= 0:
            continue
        L = f.length
        nb = max(1, round(L / bay))
        bw = L / nb
        p *= 0.65
        for s in range(n):
            za = z0 + s * hs
            v = k.pr.random()
            for i in range(nb):
                a = -L / 2 + (i + 0.5) * bw
                if ribbon:
                    lo, hi = za + 0.7, za + hs - 0.45
                    q = f.quad(a - bw / 2 + 0.1, a + bw / 2 - 0.1, lo, hi, 0.03)
                    if k.pr.random() < 0.35:
                        v = k.pr.random()
                else:
                    lo, hi = za + 0.95, za + hs - 0.65
                    q = f.quad(a - bw / 2 + 0.3, a + bw / 2 - 0.3, lo, hi, 0.03)
                    v = k.pr.random()
                if v < p * 0.9:
                    k.add(q, None, glow=True, closed=False)
                elif v < p:
                    k.add(q, None, glow=k.pr.choice(P["neon"]), closed=False)
                elif v < p + (1 - p) * 0.3:
                    k.add(q, pal["blind"], closed=False, ao=False, vary=0.08)
                else:
                    k.add(q, pal["glass"], closed=False, ao=False)
                if not clutter:
                    continue
                c = k.pr.random()
                if name == "back" or c > 0.22:
                    continue
                if c < 0.08 and name == "front":
                    # A little balcony: a slab, a rail, laundry or plants.
                    k.extra(f.box(a - bw / 2 + 0.15, a + bw / 2 - 0.15, za - 0.02, za + 0.12, 0.0, 0.9, back=False), mul(P["panel"], 1.3), ao=False)
                    k.extra(f.box(a - bw / 2 + 0.15, a + bw / 2 - 0.15, za + 0.85, za + 0.95, 0.82, 0.9, back=False), k.pal["iron"], ao=False)
                    k.extra(f.box(a - bw / 2 + 0.15, a + bw / 2 - 0.15, za + 0.12, za + 0.5, 0.84, 0.88, back=False), mul(k.pal["iron"], 1.4), ao=False)
                    if k.pr.random() < 0.5:
                        k.extra(f.box(a - 0.4, a + 0.3, za + 0.95, za + 1.6, 0.45, 0.5, back=False), k.pr.choice(pal["plastic"]), ao=False)
                elif c < 0.17:
                    cp_ac(k, f, a + k.pr.uniform(-0.2, 0.2), za + 0.2, P["metal"])
                else:
                    # A projecting lightbox sign.
                    col = k.pr.choice(P["neon"])
                    fb = Face(f.p(a + bw / 2 - 0.1, 0, 0), f.n, 0.9)
                    k.extra(fb.box(0.0, 0.85, za + 0.8, za + 2.0, -0.15, 0.15), mul(pal["dark"], 1.6), ao=False)
                    k.add(fb.box(0.08, 0.8, za + 0.88, za + 1.92, -0.18, 0.18), None, glow=col)
        if fins:
            for i in range(nb + 1):
                a = min(L / 2 - 0.12, max(-L / 2 + 0.12, -L / 2 + i * bw))
                k.add(f.box(a - 0.12, a + 0.12, z0, z0 + n * hs, 0.0, 0.16, back=False), grime(mul(panel, 1.1), 10.0), ao=False, vary=0)
    return z0 + n * hs


def cp_ground(k, P, x0, x1, y0, y1, hs, shops, door_face="front"):
    """The street storey: a core set back RECESS behind a skin with openings cut through it.
    `shops` maps a face to its shopfront count; each opening is a lit shop window, a grimy
    rolled-down or half-open shutter, or a door; a sign board and maybe an awning over it."""
    rng, pal = k.rng, k.pal
    R = 0.35
    wall, metal, dark = P["wall"], P["metal"], pal["dark"]
    k.add(box((x0 + R, y0 + R, -0.01), (x1 - R, y1 - R, hs)), mul(dark, 1.5), ao=False, vary=0)
    shops = dict({"back": 1}, **shops)
    faces = box_faces((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2)
    for name, f in faces.items():
        L = f.length
        n = shops.get(name, 0)
        holes = []
        if n:
            sw = (L - 0.6 * (n + 1)) / n
            for i in range(n):
                a0 = -L / 2 + 0.6 + i * (sw + 0.6)
                holes.append((a0, a0 + sw, 0.0, hs - 1.15))
        skin, rev = wall_skin(f, 0.0, hs, holes, R)
        k.add(skin, grime(mul(wall, 0.85), hs + 2.0, 0.6), closed=False, ao=False, vary=0.02)
        k.add(rev, mul(wall, 0.45), closed=False, ao=False)
        for a0, a1, zb, zt in holes:
            v = rng.random()
            w = -R + 0.03
            a = (a0 + a1) / 2
            if name == "back":
                v = 0.7 if v < 0.5 else 0.0
            if name in (door_face, "back") and a0 == holes[0][0] and v < 0.3:
                # A door: dark glass, a lit call panel and a strip light above.
                k.add(f.quad(a0, a1, zb, zt, w), mul(dark, 1.3), closed=False, ao=False)
                k.add(f.box(a - 0.6, a + 0.6, 0.0, zt - 0.3, w, w + 0.06, back=False), mul(metal, 0.7), ao=False)
                k.add(f.box(a + 0.7, a + 0.85, 1.2, 1.5, w, w + 0.05, back=False), None, glow=P["neon"][0])
            elif v < 0.62 and name != "back":
                # A lit shop window with mullions.
                k.add(f.quad(a0, a1, zb, zt, w), None, glow=True if rng.random() < 0.6 else P["neon"][1], closed=False)
                for m in range(1, max(2, round((a1 - a0) / 1.4))):
                    am = a0 + m * (a1 - a0) / max(2, round((a1 - a0) / 1.4))
                    k.add(f.box(am - 0.05, am + 0.05, zb, zt, w, w + 0.08, back=False), metal, ao=False)
                k.add(f.box(a0, a1, zb, zb + 0.5, w, w + 0.12, back=False), mul(metal, 0.6), ao=False)
            else:
                # A roller shutter, down or part way, grimy and corrugated, with its housing.
                k.add(f.quad(a0, a1, zb, zt, w - 0.02), None, glow=True, closed=False)
                down = zb + (zt - zb) * (0.0 if v < 0.85 else rng.uniform(0.45, 0.7))
                k.add(f.box(a0, a1, down, zt, w, w + 0.06, back=False), lambda co, n, c=jitter(P["trim"] if rng.random() < 0.3 else metal, rng, 0.08): mul(stripes(c)(co, n), 0.55 + 0.45 * min(1.0, co.z / 3.0)), ao=False)
                k.add(f.box(a0 - 0.05, a1 + 0.05, zt - 0.05, zt + 0.25, 0.0, 0.3), mul(metal, 0.8), ao=False)
            # The sign over the opening.
            if name != "back" and rng.random() < 0.85:
                cp_board(k, f, a0 + 0.1, a1 - 0.1, zt + 0.2, hs - 0.15, rng.choice(P["neon"]), mul(dark, 1.4), w=0.0)
            if rng.random() < 0.4:
                # A slanted awning.
                aw = P["awning"]
                k.add(prism([(0.0, zt + 0.15), (0.0, zt + 0.25), (1.2, zt - 0.2), (1.2, zt - 0.3)], a0 - 0.1, a1 + 0.1,
                            lambda aa, s_, z, f=f: f.p(aa, z, s_)), stripes(aw, 0.5, 0.82, 0), ao=False)
    return faces


def cp_parapet(k, P, x0, x1, y0, y1, z, h=0.9):
    """A low parapet round a roof or terrace, with a lighter coping."""
    c = grime(P["wall"], 30.0)
    t = 0.25
    for lo, hi in (((x0, y0, z), (x1, y0 + t, z + h)), ((x0, y1 - t, z), (x1, y1, z + h)),
                   ((x0, y0 + t, z), (x0 + t, y1 - t, z + h)), ((x1 - t, y0 + t, z), (x1, y1 - t, z + h))):
        k.add(box(lo, hi), c, ao=False, vary=0.02)
    k.add(box((x0 - 0.06, y0 - 0.06, z + h), (x1 + 0.06, y1 + 0.06, z + h + 0.12)), mul(P["panel"], 1.4), ao=False)


def cp_tank(k, P, x, y, z, r, h):
    """A rooftop water tank on a steel stand, with a conical lid and hoops."""
    metal = P["metal"]
    for dx in (-1, 1):
        for dy in (-1, 1):
            k.add(box((x + dx * r * 0.7 - 0.08, y + dy * r * 0.7 - 0.08, z), (x + dx * r * 0.7 + 0.08, y + dy * r * 0.7 + 0.08, z + 1.2)), k.pal["iron"], ao=False)
    k.add(box((x - r, y - r, z + 1.1), (x + r, y + r, z + 1.25)), k.pal["iron"], ao=False)
    tc = tagged(k.choice([(0.45, 0.36, 0.30), mul(metal, 1.1), (0.26, 0.38, 0.40)]), "metal")
    k.add(cyl((x, y, z + 1.25), (x, y, z + 1.25 + h), r, r, 10), stripes(tc, 0.4, 0.88, 2), ao=False)
    for zz in (0.25, 0.75):
        k.add(cyl((x, y, z + 1.25 + h * zz), (x, y, z + 1.32 + h * zz), r + 0.04, r + 0.04, 10), k.pal["iron"], ao=False)
    k.add(cyl((x, y, z + 1.25 + h), (x, y, z + 1.25 + h + r * 0.45), r + 0.08, 0.1, 10), mul(tc, 0.8), ao=False)


def cp_antenna(k, x, y, z, h, metal):
    """A lattice-free antenna mast: a thin pole with crossbars and a red warning light."""
    k.add(cyl((x, y, z), (x, y, z + h), 0.09, 0.04, 6), metal, ao=False)
    for i in range(k.rng.choice([1, 2, 3])):
        zz = z + h * (0.45 + 0.17 * i)
        w = 0.7 - 0.15 * i
        k.add(box((x - w, y - 0.03, zz - 0.03), (x + w, y + 0.03, zz + 0.03)), metal, ao=False)
    k.add(sphere((x, y, z + h + 0.05), 0.12, 1), None, glow="red")


def cp_dish(k, x, y, z, r, metal, d):
    """A satellite dish on a post, tilted towards `d`."""
    k.add(cyl((x, y, z), (x, y, z + 0.9), 0.07, 0.07, 6), metal, ao=False)
    c = Vector((x, y, z + 0.9 + r * 0.6))
    axis = (Vector((d.x, d.y, 0.8))).normalized()
    k.add(cyl(c - axis * 0.1, c + axis * r * 0.35, r * 0.25, r, 10), mul(metal, 1.35), ao=False)
    k.add(cyl(c, c + axis * r * 0.9, 0.025, 0.025, 4), metal, ao=False)


def cp_roof(k, P, x0, x1, y0, y1, z, busy=1.0):
    """A flat roof: parapet, a tank, antennas, a dish, vents and AC boxes."""
    rng = k.rng
    metal = P["metal"]
    k.add(box((x0 + 0.2, y0 + 0.2, z - 0.05), (x1 - 0.2, y1 - 0.2, z + 0.06)), mul(k.pal["dark"], 2.2), ao=False, vary=0)
    cp_parapet(k, P, x0, x1, y0, y1, z)
    W, D = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if rng.random() < 0.8 * busy and min(W, D) > 4.0:
        r = min(1.4, min(W, D) * 0.16)
        tx = cx + rng.choice([-1, 1]) * (W / 2 - r - 0.8)
        cp_tank(k, P, tx, cy + rng.uniform(-0.2, 0.3) * D, z, r, rng.uniform(1.6, 2.4))
    for _ in range(rng.choice([1, 2, 2, 3]) if busy > 0.5 else 1):
        cp_antenna(k, cx + rng.uniform(-0.35, 0.35) * W, cy + rng.uniform(-0.3, 0.35) * D, z, rng.uniform(3.0, 7.0), metal)
    if rng.random() < 0.5 * busy:
        cp_dish(k, cx + rng.uniform(-0.3, 0.3) * W, y0 + 1.2, z, rng.uniform(0.6, 1.0), metal, Vector((rng.uniform(-1, 1), -1, 0)))
    for _ in range(rng.choice([1, 2, 3])):
        vx, vy = cx + rng.uniform(-0.38, 0.38) * W, cy + rng.uniform(-0.38, 0.38) * D
        if rng.random() < 0.5:
            k.add(box((vx - 0.7, vy - 0.5, z), (vx + 0.7, vy + 0.5, z + 0.9)), mul(metal, 1.2), ao=False)
            k.add(cyl((vx, vy, z + 0.9), (vx, vy, z + 0.95), 0.4, 0.4, 8), k.pal["dark"], ao=False)
        else:
            k.add(cyl((vx, vy, z), (vx, vy, z + 1.2), 0.25, 0.25, 8), metal, ao=False)
            k.add(cyl((vx, vy, z + 1.2), (vx, vy, z + 1.45), 0.4, 0.1, 8), mul(metal, 0.8), ao=False)


def cp_strip(k, f, a, z0, z1, color, w=0.0):
    """A vertical neon tube up a wall or a corner."""
    k.add(f.box(a - 0.07, a + 0.07, z0, z1, w, w + 0.1, back=False), None, glow=color)


def cp_fire_escape(k, P, f, a0, a1, z0, n, hs):
    """Grated landings with a rail on each storey, and stair flights zig-zagging between them."""
    iron = k.pal["iron"]
    for s in range(n):
        z = z0 + s * hs
        k.add(f.box(a0, a1, z - 0.08, z, 0.0, 1.1), iron, ao=False)
        k.add(f.box(a0, a1, z + 0.95, z + 1.02, 1.02, 1.1), iron, ao=False)
        for a in (a0, (a0 + a1) / 2, a1):
            k.add(f.box(a - 0.03, a + 0.03, z, z + 1.0, 1.04, 1.1), iron, ao=False)
        if s < n - 1:
            e = 1 if s % 2 == 0 else -1
            mid = (a0 + a1) / 2
            ang = math.atan2(hs, (a1 - a0) * 0.8) * e
            k.add(f.obox(mid, z + hs / 2, math.hypot(hs, (a1 - a0) * 0.8), 0.12, 0.25, 0.85, ang), iron)


def cp_hang_cables(k, f, a0, a1, z, n=3, sag=0.8):
    """Cables slung along a facade, between two brackets."""
    for i in range(n):
        dz = -0.15 * i
        c = k.choice([(0.08, 0.08, 0.09), (0.12, 0.11, 0.1), (0.5, 0.4, 0.12)])
        sag_line(k, f.p(a0, z + dz, 0.3 + 0.1 * i), f.p(a1, z + dz + k.pr.uniform(-0.2, 0.2), 0.3 + 0.1 * i), sag * (1 + 0.3 * i), 0.035, c, seg=5)


def cp_signage(k, P, f, z0, z1, L, corner=None, blade=True):
    """The neon on one street face above the shops: blade signs (one near a corner, maybe more
    along the front), a sign strip across the first floor, and a tube up a corner."""
    rng = k.rng
    frame = mul(k.pal["dark"], 1.6)
    if blade:
        side = corner or rng.choice([-1, 1])
        a = side * (L / 2 - rng.uniform(0.6, 1.2))
        h = min(z1 - z0 - 0.6, rng.uniform(5.5, 10.0))
        cp_blade(k, f, a, z0 + 0.3 + h, h, rng.uniform(1.5, 2.0), P["neon"][0], frame, P["neon"][1] if rng.random() < 0.5 else None)
        if L > 8.0:
            for _ in range(rng.choice([1, 1, 2])):
                a2 = rng.uniform(-0.3, 0.3) * L
                h2 = min(z1 - z0 - 1.0, rng.uniform(2.6, 4.5))
                zt = z0 + 0.4 + h2 + rng.uniform(0.0, max(0.0, z1 - z0 - h2 - 1.2))
                cp_blade(k, f, a2, zt, h2, rng.uniform(1.0, 1.4), rng.choice(P["neon"]), frame)
    if rng.random() < 0.55:
        cp_board(k, f, -L / 2 + 0.4, L / 2 - 0.4, z0 + 0.05, z0 + 0.85, rng.choice(P["neon"]), mul(frame, 0.9), w=0.16)
    # Boards on upper floors (clinics, bars, hostels), part of the front's width.
    for _ in range(rng.choice([0, 1, 1, 2])):
        st = rng.randrange(1, max(2, int((z1 - z0) / 3.2)))
        bw = L * rng.uniform(0.3, 0.55)
        ba = rng.uniform(-0.5, 0.5) * (L - bw)
        zb = z0 + st * 3.2 + 0.05
        if zb + 0.8 < z1:
            cp_board(k, f, ba - bw / 2, ba + bw / 2, zb, zb + 0.8, rng.choice(P["neon"]), mul(frame, 0.9), w=0.16)
    if rng.random() < 0.6:
        cp_strip(k, f, -rng.choice([-1, 1]) * (L / 2 - 0.06), z0, z1, P["neon"][1], w=0.02)


def cp_roof_sign(k, P, x0, x1, y, z, color):
    """A big sign frame on a roof edge facing the street: struts, a lattice and a board of
    large glowing characters."""
    iron = k.pal["iron"]
    W = x1 - x0
    h = min(3.2, max(1.8, W * 0.22))
    for x in (x0 + 0.4, (x0 + x1) / 2, x1 - 0.4):
        k.add(box((x - 0.07, y - 0.07, z), (x + 0.07, y + 0.07, z + h + 0.6)), iron, ao=False)
        k.add(Face((x, y, 0), Y, 1).obox(0.8, z + h * 0.45, h * 1.1, 0.1, -0.05, 0.05, 1.0), iron, ao=False)
    k.add(box((x0, y - 0.05, z + 0.6), (x1, y + 0.05, z + 0.7)), iron, ao=False)
    f = Face(((x0 + x1) / 2, y - 0.1, 0), X, W)
    cp_board(k, f, -W / 2 + 0.2, W / 2 - 0.2, z + 0.8, z + 0.8 + h, color, mul(k.pal["dark"], 1.5), w=0.0)


def cyber_block(k):
    """A mid-rise block by form: narrow (gable-end-free slab, 4-7 storeys), wide (5-6 storeys,
    maybe a taller stack on one side) or corner (shops on two streets, a round corner bay)."""
    rng, form = k.rng, k.form
    u = rng.uniform
    P = cp_colours(k)
    hs0, hs = u(4.2, 4.8), 3.2
    if form == "narrow":
        W, D = u(6.5, 9.0), u(10.0, 13.0)
        n = rng.choice([4, 5, 5, 6, 7])
    elif form == "wide":
        W, D = u(13.0, 18.0), u(10.0, 13.0)
        n = rng.choice([4, 5, 5, 6])
    else:
        W, D = u(10.0, 13.0), u(10.0, 13.0)
        n = rng.choice([5, 6, 6, 7, 8])
    x0, x1, y0, y1 = -W / 2, W / 2, -D / 2, D / 2
    side = k.corner if form == "corner" else 0
    shops = {"front": max(1, round(W / 4.5))}
    if side:
        shops["right" if side > 0 else "left"] = max(1, round(D / 4.5))
    cp_ground(k, P, x0, x1, y0, y1, hs0, shops)
    wins = {"front": 0.6, "back": 0.4, "left": 0.35, "right": 0.35}
    if side:
        wins["right" if side > 0 else "left"] = 0.6
    # Setbacks: the top storeys step back from the street, once or twice.
    lower = n - (rng.choice([1, 2]) if n >= 5 and rng.random() < 0.7 else 0)
    top = cp_storeys(k, P, x0, x1, y0, y1, hs0, lower, hs, wins)
    segs = [(x0, x1, y0, y1, top)]
    if form == "wide" and rng.random() < 0.6:
        # A taller stack on one side, the rest a terrace.
        e = rng.choice([-1, 1])
        sw = W * u(0.4, 0.55)
        sx0, sx1 = (x1 - sw, x1) if e > 0 else (x0, x0 + sw)
        cp_roof(k, P, x0, x1, y0, y1, top, busy=0.4)
        extra = rng.choice([2, 3, 4])
        top2 = cp_storeys(k, P, sx0 + 0.6, sx1 - 0.6, y0 + 1.0, y1 - 0.6, top, extra, hs, wins)
        segs.append((sx0 + 0.6, sx1 - 0.6, y0 + 1.0, y1 - 0.6, top2))
    elif lower < n:
        cp_parapet(k, P, x0, x1, y0, y1, top, h=1.0)
        inset = u(1.4, 2.4)
        top2 = cp_storeys(k, P, x0 + 0.5, x1 - 0.5, y0 + inset, y1 - 0.4, top, n - lower, hs, wins)
        segs.append((x0 + 0.5, x1 - 0.5, y0 + inset, y1 - 0.4, top2))
        # Terrace railing with planters and a strip light.
        k.add(box((x0 + 0.6, y0 + 0.3, top), (x0 + 1.4, y0 + 0.9, top + 0.6)), (0.22, 0.36, 0.20), ao=False)
    sx0, sx1, sy0, sy1, ztop = segs[-1]
    cp_roof(k, P, sx0, sx1, sy0, sy1, ztop)
    if rng.random() < 0.4:
        cp_roof_sign(k, P, sx0 + 0.3, sx1 - 0.3, sy0 + 0.6, ztop, rng.choice(P["neon"]))
    faces = box_faces(0, 0, W / 2, D / 2)
    cp_signage(k, P, faces["front"], hs0, top, W, corner=-side or None)
    if side:
        sf = faces["right" if side > 0 else "left"]
        cp_signage(k, P, sf, hs0, top, D, corner=-1 if side > 0 else 1, blade=False)
        # The corner bay: a drum up the storeys, a lit window ring on each floor and a neon crown.
        cxr, cyr = side * (W / 2), -D / 2
        r = u(1.5, 1.9)
        k.add(cyl((cxr, cyr, hs0 - 0.2), (cxr, cyr, top), r, r, 10), grime(P["wall"]), ao=False)
        for s in range(lower):
            z = hs0 + s * hs
            k.add(cyl((cxr, cyr, z + 0.85), (cxr, cyr, z + hs - 0.5), r + 0.05, r + 0.05, 10), None, glow=True if rng.random() < 0.7 else P["neon"][1])
            k.add(cyl((cxr, cyr, z + hs - 0.32), (cxr, cyr, z + hs), r + 0.15, r + 0.15, 10), mul(P["panel"], 1.2), ao=False)
        k.add(cyl((cxr, cyr, top), (cxr, cyr, top + 0.5), r + 0.2, r + 0.2, 10), None, glow=P["neon"][0])
        k.add(cyl((cxr, cyr, top + 0.5), (cxr, cyr, top + 0.8), r + 0.25, r + 0.1, 10), P["metal"], ao=False)
    # Cables along the front, a downpipe and maybe a fire escape on a side wall.
    f = faces["front"]
    cp_hang_cables(k, f, -W / 2 + 0.3, W / 2 - 0.3, hs0 + rng.uniform(0.2, 0.8), n=rng.choice([2, 3]))
    sfn = "left" if side > 0 else "right" if side < 0 else rng.choice(["left", "right"])
    sf = faces[sfn]
    pa = rng.uniform(-0.4, 0.4) * sf.length
    pipe_run(k, [sf.p(pa, 0.0, 0.2), sf.p(pa, top - 0.4, 0.2)], 0.1, mul(P["metal"], 0.8), 3.2)
    if form == "narrow" and rng.random() < 0.6 or form == "wide" and rng.random() < 0.3:
        fa = rng.uniform(-0.3, 0.1) * sf.length
        cp_fire_escape(k, P, sf, fa - 1.6, fa + 1.6, hs0 + hs, lower - 1, hs)
    if form == "wide" and rng.random() < 0.6:
        # A holo-billboard on the bare side wall.
        bw = min(D - 2.0, u(5.0, 7.5))
        cp_screen(k, sf, 0.0, hs0 + hs * 1.2, bw, bw * u(0.55, 0.75), P["neon"][1], P["neon"][0])


def cyber_tower(k):
    """A slender tower with setbacks (12-16 storeys over a shop podium) or the landmark: a wide
    podium, a shaft stepping back twice, giant screens and a lit crown with a spire."""
    rng, form = k.rng, k.form
    u = rng.uniform
    P = cp_colours(k)
    hs0, hs = u(4.4, 5.0), 3.3
    if form == "landmark":
        W, D = u(19.0, 23.0), u(19.0, 23.0)
        pod = 3
        steps = [(u(13.0, 15.0), u(13.0, 15.0), rng.choice([12, 13, 14])), (u(10.0, 11.5), u(10.0, 11.5), rng.choice([6, 7, 8])), (u(7.0, 8.0), u(7.0, 8.0), 3)]
    else:
        W, D = u(10.0, 13.0), u(10.0, 13.0)
        pod = rng.choice([1, 2])
        steps = [(W - u(1.4, 2.4), D - u(1.4, 2.4), rng.choice([6, 7, 8])), (W - u(3.2, 4.4), D - u(3.2, 4.4), rng.choice([3, 4, 5]))]
    x0, x1, y0, y1 = -W / 2, W / 2, -D / 2, D / 2
    cp_ground(k, P, x0, x1, y0, y1, hs0, {"front": max(2, round(W / 4.8)), "left": 1 if W > 15 else 0, "right": 1 if W > 15 else 0})
    z = cp_storeys(k, P, x0, x1, y0, y1, hs0, pod - 1, hs, {"front": 0.6, "back": 0.4, "left": 0.5, "right": 0.5}, bay=3.0) if pod > 1 else hs0
    faces = box_faces(0, 0, W / 2, D / 2)
    cp_signage(k, P, faces["front"], hs0, z, W)
    prev = (x0, x1, y0, y1)
    for i, (sw, sd, n) in enumerate(steps):
        cp_parapet(k, P, *prev, z, h=1.0)
        a0, a1, b0, b1 = -sw / 2, sw / 2, -sd / 2 + (0.6 if i == 0 and form != "landmark" else 0.0), sd / 2
        z1 = cp_storeys(k, P, a0, a1, b0, b1, z, n, hs, {"front": 0.55, "back": 0.45, "left": 0.5, "right": 0.5}, bay=2.5 if form == "landmark" else 2.3,
                        clutter=i == 0 and form != "landmark")
        sf = box_faces((a0 + a1) / 2, (b0 + b1) / 2, sw / 2, (b1 - b0) / 2)
        # Neon tubes up the shaft's corners.
        for name, e in (("front", -1), ("front", 1)) if form != "landmark" or i == 2 else (("front", -1), ("front", 1), ("back", -1), ("back", 1)):
            if form == "landmark" or rng.random() < 0.6:
                cp_strip(k, sf[name], e * (sf[name].length / 2 - 0.06), z, z1, P["neon"][i % 2], w=0.02)
        if i == 0:
            # A screen on the shaft: the tower's face from the street.
            fn = "front" if form == "landmark" or rng.random() < 0.5 else rng.choice(["left", "right"])
            bw = sf[fn].length * u(0.55, 0.75)
            bh = min((z1 - z) * 0.6, bw * (1.6 if form == "landmark" else 1.1))
            cp_screen(k, sf[fn], 0.0, z + (z1 - z) * 0.3, bw, bh, P["neon"][0], P["neon"][1], out=0.35)
            if form == "landmark":
                bw2 = sf["left"].length * 0.6
                cp_screen(k, sf["left"], 0.0, z + (z1 - z) * 0.45, bw2, bw2 * 0.8, P["neon"][1], P["neon"][0], out=0.35)
            for _ in range(rng.choice([2, 3])):
                f2 = sf[rng.choice(["left", "right", "back"])]
                cp_ac(k, f2, rng.uniform(-0.35, 0.35) * f2.length, z + rng.randrange(n) * hs + 0.2, P["metal"])
        prev = (a0, a1, b0, b1)
        z = z1
    a0, a1, b0, b1 = prev
    cw, cd = a1 - a0, b1 - b0
    # The crown: a glowing band, a cap and a spire, with antennas.
    k.add(box((a0 - 0.3, b0 - 0.3, z), (a1 + 0.3, b1 + 0.3, z + 0.35)), P["metal"], ao=False)
    k.add(box((a0 - 0.15, b0 - 0.15, z + 0.35), (a1 + 0.15, b1 + 0.15, z + 1.0)), None, glow=P["neon"][0])
    k.add(box((a0 - 0.35, b0 - 0.35, z + 1.0), (a1 + 0.35, b1 + 0.35, z + 1.5)), mul(P["panel"], 1.2), ao=False)
    if form == "landmark":
        # A halo ring on struts above the crown, and a tall spire.
        rr = max(cw, cd) * 0.75
        zh = z + 4.0
        for i in range(4):
            ang = i * math.pi / 2 + math.pi / 4
            k.add(cyl((math.cos(ang) * cw * 0.45, (b0 + b1) / 2 + math.sin(ang) * cd * 0.45, z + 1.5), (math.cos(ang) * rr, (b0 + b1) / 2 + math.sin(ang) * rr, zh), 0.12, 0.12, 6), P["metal"], ao=False)
        ring = 16
        for i in range(ring):
            t0, t1 = i / ring * math.tau, (i + 1) / ring * math.tau
            k.add(cyl((math.cos(t0) * rr, (b0 + b1) / 2 + math.sin(t0) * rr, zh), (math.cos(t1) * rr, (b0 + b1) / 2 + math.sin(t1) * rr, zh), 0.22, 0.22, 6), None, glow=P["neon"][1])
        k.add(cyl((0, (b0 + b1) / 2, z + 1.5), (0, (b0 + b1) / 2, z + 6.0), 1.2, 0.6, 8), P["metal"], ao=False)
        k.add(cyl((0, (b0 + b1) / 2, z + 6.0), (0, (b0 + b1) / 2, z + 18.0), 0.35, 0.06, 6), mul(P["metal"], 1.2), ao=False)
        k.add(sphere((0, (b0 + b1) / 2, z + 18.1), 0.25, 1), None, glow="red")
        k.add(sphere((0, (b0 + b1) / 2, z + 11.0), 0.2, 1), None, glow="red")
    else:
        zc = z + 1.5
        cp_parapet(k, P, a0, a1, b0, b1, zc, h=0.7)
        if rng.random() < 0.6:
            cp_tank(k, P, a0 + cw * 0.3, (b0 + b1) / 2, zc, min(1.2, cw * 0.18), u(1.5, 2.2))
        cp_antenna(k, a1 - cw * 0.3, (b0 + b1) / 2, zc, u(6.0, 10.0), P["metal"])
        if rng.random() < 0.5:
            cp_antenna(k, a0 + cw * 0.25, b1 - 1.0, zc, u(3.0, 5.0), P["metal"])
    f = faces["front"]
    cp_hang_cables(k, f, -W / 2 + 0.3, W / 2 - 0.3, hs0 + 0.5, n=2)


def cyber_market(k):
    """A street food court: a corrugated roof on steel columns over rows of food counters with
    glowing menus, tables and stools, paper lanterns on cables, and a neon name on the fascia."""
    rng = k.rng
    u = rng.uniform
    P = cp_colours(k)
    pal = k.pal
    W, D = u(16.0, 21.0), u(11.0, 14.0)
    hx, hy = W / 2, D / 2
    H = u(5.2, 6.0)
    metal, dark = P["metal"], pal["dark"]
    k.add(box((-hx, -hy, -0.01), (hx, hy, 0.15)), hazard(mul(P["wall"], 0.7), mul(P["wall"], 0.62), 1.0), ao=False)
    nc = max(3, round(W / 5.5))
    for i in range(nc + 1):
        x = -hx + 0.3 + i * (W - 0.6) / nc
        for y in (-hy + 0.3, hy - 0.3):
            k.add(box((x - 0.2, y - 0.2, 0.15), (x + 0.2, y + 0.2, H)), mul(metal, 0.9), ao=False)
        # Trusses across.
        k.add(box((x - 0.12, -hy, H - 0.6), (x + 0.12, hy, H - 0.4)), k.pal["iron"], ao=False)
    # The roof: a shallow corrugated butterfly with a glowing clerestory gap.
    for e in (-1, 1):
        y0, y1 = (0.3, hy + 0.8) if e > 0 else (-hy - 0.8, -0.3)
        zin, zout = H - 0.1, H + 0.6
        ya, yb = (y0, y1) if e > 0 else (y1, y0)
        k.add(prism([(ya, zin), (yb, zout), (yb, zout + 0.15), (ya, zin + 0.15)], -hx - 0.6, hx + 0.6, lambda a, s_, z: Vector((a, s_, z))),
              stripes(mul(P["panel"], 1.5), 0.35, 0.85, 0), ao=False)
    k.add(box((-hx - 0.5, -0.3, H - 0.05), (hx + 0.5, 0.3, H + 0.05)), None, glow="white")
    # The fascia on the front, with the court's name in neon and a tube along it.
    f = Face((0, -hy - 0.8, 0), X, W + 1.2)
    cp_board(k, f, -hx * 0.7, hx * 0.7, H + 0.75, H + 2.0, P["neon"][0], mul(dark, 1.4), w=0.0)
    k.add(box((-hx * 0.7, -hy - 0.6, H + 0.6), (hx * 0.7, -hy - 0.3, H + 0.8)), metal, ao=False)
    # Counters along the back with menus over them, and the cooks' gear.
    m = max(3, int(W / 3.6))
    cw = (W - 1.0) / m
    for i in range(m):
        x = -hx + 0.5 + (i + 0.5) * cw
        c = k.choice(pal["awning"])
        k.add(box((x - cw / 2 + 0.15, hy - 2.0, 0.15), (x + cw / 2 - 0.15, hy - 1.2, 1.15)), stripes(c, 0.5, 0.85, 0), ao=False)
        k.add(box((x - cw / 2 + 0.1, hy - 2.1, 1.15), (x + cw / 2 - 0.1, hy - 1.1, 1.25)), mul(metal, 1.3), ao=False)
        k.add(box((x - cw / 2 + 0.15, hy - 1.0, 0.15), (x + cw / 2 - 0.15, hy - 0.5, 2.6)), mul(dark, 1.6), ao=False)
        k.add(box((x - cw / 2 + 0.3, hy - 1.06, 2.75), (x + cw / 2 - 0.3, hy - 0.96, 3.6)), None, glow=rng.choice(P["neon"] + [True]))
        k.add(cyl((x - 0.4, hy - 1.6, 1.25), (x - 0.4, hy - 1.6, 1.6), 0.25, 0.25, 8), mul(metal, 1.2), ao=False)
        k.add(cyl((x + 0.4, hy - 1.6, 1.25), (x + 0.4, hy - 1.6, 1.3), 0.22, 0.22, 8), None, glow="amber")
        # A hood over the hob, and its flue up through the roof.
        k.add(box((x - 0.7, hy - 1.9, 3.7), (x + 0.7, hy - 1.0, 4.0)), mul(metal, 1.1), ao=False)
        k.add(cyl((x, hy - 1.45, 4.0), (x, hy - 1.45, H + 1.4), 0.15, 0.15, 6), metal, ao=False)
    # Tables and stools.
    for i in range(max(2, int(W / 4.5))):
        tx = -hx + 2.2 + i * (W - 4.4) / max(1, int(W / 4.5) - 1)
        for ty in (-hy + 2.6, -0.6):
            tz = 0.15
            k.add(cyl((tx, ty, tz), (tx, ty, tz + 0.72), 0.06, 0.06, 6), metal, ao=False)
            k.add(cyl((tx, ty, tz + 0.72), (tx, ty, tz + 0.78), 0.55, 0.55, 10), k.choice(pal["plastic"]), ao=False)
            for e in (-1, 1):
                k.add(cyl((tx + e * 0.85, ty, tz), (tx + e * 0.85, ty, tz + 0.45), 0.2, 0.2, 8), k.choice(pal["plastic"]), ao=False)
    # Lantern strings across, under the roof.
    for j in range(3):
        y = -hy + 1.0 + j * (D - 2.0) / 2
        pts = sag_line(k, (-hx + 0.3, y, H - 0.7), (hx - 0.3, y, H - 0.7), 0.5, 0.025, (0.1, 0.1, 0.1), seg=6)
        for p in pts[1:-1]:
            k.add(sphere(p - Z * 0.25, 0.2, 1, squash=1.2), None, glow=rng.choice(["amber", "pink", True]))
    # Neon at the corners, and vending machines at one end.
    for e in (-1, 1):
        k.add(box((e * hx - 0.08, -hy + 0.1, 0.4), (e * hx + 0.08, -hy + 0.5, H - 0.3)), None, glow=P["neon"][1])
    e = rng.choice([-1, 1])
    for i in range(2):
        y = -hy + 2.0 + i * 1.1
        x = e * (hx - 0.6)
        k.add(box((x - 0.45, y - 0.5, 0.15), (x + 0.45, y + 0.5, 2.1)), k.choice(pal["plastic"]), ao=False)
        k.add(Face((x - e * 0.45, y, 0), -Y * e, 1.0).box(-0.4, 0.4, 0.8, 1.95, 0.0, 0.04, back=False), None, glow=rng.choice(P["neon"]))


def cyber_workshop(k):
    """A garage (roller-shutter bays, one open on a lit interior, tyres and drums, a neon sign)
    or a fab shop (a tall shed with a sawtooth roof of cyan clerestories, stacks, a loading
    dock with hazard stripes)."""
    rng, form = k.rng, k.form
    u = rng.uniform
    P = cp_colours(k)
    pal = k.pal
    metal, dark = P["metal"], pal["dark"]
    if form == "garage":
        W, D = u(10.0, 13.0), u(9.0, 11.0)
        H1 = u(5.0, 5.6)
        hx, hy = W / 2, D / 2
        k.add(box((-hx, -hy, -0.01), (hx, hy, H1)), grime(mul(P["wall"], 0.9), 5.0, 0.5), ao=False)
        f = Face((0, -hy, 0), X, W)
        bays = 2 if W > 11.0 else 1
        bw = min(4.2, (W - 3.0) / bays - 0.4)
        for i in range(bays):
            a = -hx + 1.0 + bw / 2 + i * (bw + 0.6)
            k.add(f.box(a - bw / 2 - 0.2, a + bw / 2 + 0.2, 0.0, 3.9, 0.0, 0.12, back=False), hazard(P["trim"], mul(dark, 1.4), 0.4), ao=False)
            if i == 0:
                k.add(f.quad(a - bw / 2, a + bw / 2, 0.0, 3.6, 0.13), mul(dark, 1.2), closed=False, ao=False)
                k.add(f.box(a - bw / 2 + 0.2, a + bw / 2 - 0.2, 3.3, 3.45, 0.13, 0.2, back=False), None, glow="white")
                k.add(f.box(a - bw / 2, a + bw / 2, 3.0, 3.6, 0.13, 0.22, back=False), stripes(metal), ao=False)
                # The front of a car on the lift, nose out.
                k.add(box((a - 1.0, -hy - 1.3, 0.45), (a + 1.0, -hy + 0.1, 1.2), 0.15), k.choice(pal["plastic"]), ao=False)
                k.add(box((a - 0.85, -hy - 0.6, 1.15), (a + 0.85, -hy + 0.1, 1.6), 0.12), mul(dark, 1.6), ao=False)
                for e in (-1, 1):
                    k.add(cyl((a + e * 0.9, -hy - 0.8, 0.38), (a + e * 1.06, -hy - 0.8, 0.38), 0.36, 0.36, 8), dark, ao=False)
                    k.add(box((a + e * 0.65 - 0.25, -hy - 1.34, 0.9), (a + e * 0.65 + 0.25, -hy - 1.28, 1.05)), None, glow="white")
            else:
                k.add(f.box(a - bw / 2, a + bw / 2, 0.0, 3.6, 0.13, 0.2, back=False), lambda co, n, c=jitter(metal, rng): mul(stripes(c)(co, n), 0.6 + 0.4 * min(1.0, co.z / 3.0)), ao=False)
            k.add(f.box(a - bw / 2 - 0.1, a + bw / 2 + 0.1, 3.6, 3.95, 0.0, 0.35), mul(metal, 0.8), ao=False)
        # A person door with a lit panel, the sign over it all, a blade at the corner.
        da = hx - 1.2
        k.add(f.box(da - 0.5, da + 0.5, 0.0, 2.2, 0.0, 0.08, back=False), mul(metal, 0.7), ao=False)
        k.add(f.box(da - 0.4, da + 0.4, 2.3, 2.45, 0.0, 0.1, back=False), None, glow="white")
        cp_board(k, f, -hx + 0.6, hx - 0.6, 4.1, H1 - 0.2, P["neon"][0], mul(dark, 1.4), w=0.0)
        cp_blade(k, f, -hx + 0.4, H1 + 1.5, 3.6, 1.1, P["neon"][1], mul(dark, 1.6))
        z = H1
        if rng.random() < 0.55:
            # A flat over the shop.
            z = cp_storeys(k, P, -hx, hx, -hy + 0.8, hy, H1, 1, 3.2, {"front": 0.6, "left": 0.4, "right": 0.4})
            cp_parapet(k, P, -hx, hx, -hy, hy, H1, 0.8)
        cp_roof(k, P, -hx, hx, -hy + (0.8 if z > H1 else 0.0), hy, z, busy=0.7)
        # Tyres and drums by the wall.
        e = rng.choice([-1, 1])
        for i in range(rng.choice([3, 4, 5])):
            k.add(cyl((e * (hx + 0.55), -hy + 1.0, i * 0.26), (e * (hx + 0.55), -hy + 1.0, i * 0.26 + 0.24), 0.42, 0.42, 10), tagged((0.08, 0.08, 0.09), "plastic"), ao=False, vary=0)
        for i in range(2):
            k.add(cyl((e * (hx + 0.5), -hy + 2.2 + i * 0.7, 0), (e * (hx + 0.5), -hy + 2.2 + i * 0.7, 0.9), 0.3, 0.3, 8), stripes(k.choice(pal["trim"]), 0.3, 0.8), ao=False)
        sf = Face((hx if e > 0 else -hx, 0, 0), Y if e > 0 else -Y, D)
        cp_ac(k, sf, 1.0, 2.6, metal)
        pipe_run(k, [sf.p(-1.5, 0.0, 0.2), sf.p(-1.5, z - 0.4, 0.2)], 0.1, metal, 3.0)
    else:
        W, D = u(12.0, 16.0), u(10.0, 12.0)
        hx, hy = W / 2, D / 2
        H1 = u(6.0, 7.0)
        k.add(box((-hx, -hy, -0.01), (hx, hy, H1)), lambda co, n, c=mul(P["panel"], 1.5): mul(stripes(c, 0.6, 0.88, 0)(co, n) if abs(n.y) > 0.5 else stripes(c, 0.6, 0.88, 1)(co, n), 0.6 + 0.4 * min(1.0, co.z / 5.0)), ao=False)
        k.add(box((-hx - 0.1, -hy - 0.1, -0.01), (hx + 0.1, hy + 0.1, 1.0)), grime(P["wall"], 2.0, 0.6), ao=False)
        teeth = max(3, round(W / 4.0))
        tw = W / teeth
        for i in range(teeth):
            xa = -hx + i * tw
            zt = H1 + 2.2
            k.add(prism([(xa, H1), (xa + tw, H1), (xa + tw, zt), (xa + tw - 0.2, zt)], -hy - 0.2, hy + 0.2, lambda a, s_, z: Vector((s_, a, z))), stripes(mul(metal, 1.1), 0.5, 0.86, 1), ao=False)
            g = Face((xa + tw + 0.01, 0, 0), Y, D)
            k.add(g.box(-hy + 0.2, hy - 0.2, H1 + 0.3, zt - 0.25, -0.03, 0.02), None, glow="cyan" if rng.random() < 0.7 else True)
        f = Face((0, -hy, 0), X, W)
        # The loading dock: a raised platform with hazard edges, a big shutter and a ramp.
        da = rng.choice([-1, 1]) * (hx - 3.0)
        k.add(f.box(da - 2.6, da + 2.6, 0.0, 1.1, 0.0, 2.0), mul(P["wall"], 0.7), ao=False)
        k.add(f.box(da - 2.6, da + 2.6, 0.95, 1.12, 1.9, 2.1, back=False), hazard((0.95, 0.75, 0.1), (0.08, 0.08, 0.08), 0.35), ao=False)
        k.add(f.box(da - 2.0, da + 2.0, 1.1, 5.0, 0.0, 0.1, back=False), lambda co, n, c=jitter(P["trim"], rng): mul(stripes(c)(co, n), 0.6 + 0.4 * min(1.0, co.z / 4.0)), ao=False)
        k.add(f.box(da - 2.15, da + 2.15, 5.0, 5.35, 0.0, 0.35), mul(metal, 0.8), ao=False)
        k.add(f.box(da - 0.6, da + 0.6, 5.5, 5.75, 0.0, 0.3), None, glow="amber")
        # Stacks and ducts on the roof.
        for i in range(rng.choice([1, 2, 3])):
            sx = -da * 0.5 + (i - 1) * 2.0
            k.add(cyl((sx, hy - 1.5, H1), (sx, hy - 1.5, H1 + u(4.0, 6.0)), 0.45, 0.4, 10), stripes(mul(metal, 0.9), 0.8, 0.85), ao=False)
        pipe_run(k, [(-hx - 0.4, -hy + 2.0, 0.6), (-hx - 0.4, -hy + 2.0, H1 - 1.0), (-hx - 0.4, hy - 1.5, H1 - 1.0)], 0.22, mul(metal, 0.85), 2.5)
        cp_board(k, f, -da * 0.9 - 2.4, -da * 0.9 + 2.4, H1 - 1.6, H1 - 0.4, P["neon"][0], mul(dark, 1.4), w=0.0)
        fa = -da * 0.9
        k.add(f.box(fa - 0.5, fa + 0.5, 0.0, 2.2, 0.0, 0.08, back=False), mul(metal, 0.7), ao=False)
        k.add(f.box(fa - 0.4, fa + 0.4, 2.3, 2.42, 0.0, 0.1, back=False), None, glow="white")
        for _ in range(3):
            k.add(cyl((fa + u(-2.2, 2.2), -hy - 0.8, 0), (fa + u(-2.2, 2.2), -hy - 0.8, 0.9), 0.3, 0.3, 8), stripes(k.choice(pal["trim"]), 0.3, 0.8), ao=False)


def cyber_neon_sign(k, H):
    """A street sign on a post: a blade of characters, a round or arrow board, a lit base."""
    rng, pal = k.rng, k.pal
    metal, dark = pal["metal"], mul(pal["dark"], 1.6)
    c1, c2 = rng.sample(["pink", "cyan", "amber"], 2)
    k.add(box((-0.35, -0.35, 0), (0.35, 0.35, 0.4), 0.04), pal["stone"])
    k.add(box((-0.1, -0.1, 0.4), (0.1, 0.1, H - 0.2)), metal, ao=False)
    bh = rng.uniform(1.8, 2.4)
    cp_blade(k, Face((0.0, 0.0, 0), -Y, 1), 0.0, H - 0.05, bh, 1.3, c1, dark, c2 if rng.random() < 0.5 else None)
    if rng.random() < 0.6:
        # A round board at the top, glowing ring and a dark face.
        z = H - bh - 0.6
        k.add(cyl((0, -0.14, z), (0, 0.14, z), 0.55, 0.55, 12), dark, ao=False)
        k.add(cyl((0, -0.17, z), (0, 0.17, z), 0.42, 0.42, 12), None, glow=c2)
        k.add(cyl((0, -0.19, z), (0, 0.19, z), 0.3, 0.3, 12), dark, ao=False)
    k.add(box((-0.16, -0.16, 0.4), (0.16, 0.16, 0.55)), None, glow=c2)


def cyber_billboard(k, H):
    """A holo-billboard on two legs with a service catwalk: a screen both sides."""
    rng, pal = k.rng, k.pal
    metal, iron = pal["metal"], pal["iron"]
    c1, c2 = rng.sample(["pink", "cyan", "amber"], 2)
    w = rng.uniform(6.0, 8.0)
    h = rng.uniform(3.4, 4.2)
    z0 = H - h - 0.2
    for e in (-1, 1):
        x = e * w * 0.3
        k.add(box((x - 0.4, -0.4, 0), (x + 0.4, 0.4, 0.5), 0.05), pal["stone"])
        k.add(box((x - 0.18, -0.18, 0.5), (x + 0.18, 0.18, z0 - 0.3)), metal, ao=False)
        for zz in (z0 * 0.35, z0 * 0.7):
            k.add(box((x - 0.24, -0.24, zz), (x + 0.24, 0.24, zz + 0.15)), iron, ao=False)
    k.add(box((-w * 0.3, -0.1, z0 * 0.55), (w * 0.3, 0.1, z0 * 0.55 + 0.2)), iron, ao=False)
    # Catwalk under the screen.
    k.add(box((-w / 2, -0.9, z0 - 0.45), (w / 2, 0.9, z0 - 0.35)), iron, ao=False)
    for e in (-1, 1):
        k.add(box((-w / 2, e * 0.9 - 0.03, z0 - 0.35), (w / 2, e * 0.9 + 0.03, z0 + 0.6)), iron, ao=False)
    k.add(box((-w / 2 - 0.1, -0.15, z0 - 0.1), (w / 2 + 0.1, 0.15, H)), mul(pal["dark"], 1.5), ao=False)
    for side in (Face((0, -0.15, 0), X, w), flipped(Face((0, 0.15, 0), X, w))):
        cp_screen(k, side, 0.0, z0, w, h, c1, c2, out=0.0)


def cyber_cable(k, H):
    """A cable bundle to string between two buildings across a street: 4-7 cables of different
    weights and sag between two wall brackets, along Y, with a junction box and a few hanging
    lanterns and signs. Nothing touches the ground; the brackets are at the top."""
    rng, pal = k.rng, k.pal
    S = rng.uniform(10.0, 14.0)
    metal = pal["metal"]
    for e in (-1, 1):
        y = e * S / 2
        k.add(box((-0.45, y - 0.06 * e - 0.06, H - 0.9), (0.45, y + 0.06, H)), metal, ao=False)
        k.add(box((-0.2, y - e * 0.35 - 0.1, H - 0.6), (0.2, y + 0.1, H - 0.3)), pal["iron"], ao=False)
    n = rng.choice([4, 5, 6, 7])
    lows = []
    for i in range(n):
        x = (i - (n - 1) / 2) * 0.12
        z0, z1 = H - 0.35 - rng.uniform(0, 0.4), H - 0.35 - rng.uniform(0, 0.4)
        sag = rng.uniform(1.0, 2.4)
        r = rng.choice([0.03, 0.04, 0.05, 0.07])
        c = k.choice([(0.07, 0.07, 0.08), (0.07, 0.07, 0.08), (0.12, 0.11, 0.10), (0.55, 0.42, 0.10), (0.45, 0.12, 0.10)])
        pts = sag_line(k, (x, -S / 2 + 0.2, z0), (x, S / 2 - 0.2, z1), sag, r, c, seg=8)
        lows.append(pts)
    # Hanging things off the lowest cable.
    low = min(lows, key=lambda ps: min(p.z for p in ps))
    for j in rng.sample(range(2, 7), rng.choice([2, 3])):
        p = low[j]
        drop = rng.uniform(0.3, 0.8)
        k.add(cyl(p, p - Z * drop, 0.012, 0.012, 4), (0.1, 0.1, 0.1), ao=False, vary=0)
        if rng.random() < 0.55:
            k.add(sphere(p - Z * (drop + 0.22), 0.22, 1, squash=1.25), None, glow=rng.choice(["amber", "pink", "cyan"]))
        else:
            q = p - Z * (drop + 0.4)
            k.add(box(q - Vector((0.05, 0.35, 0.35)), q + Vector((0.05, 0.35, 0.35))), mul(pal["dark"], 1.5), ao=False)
            k.add(box(q - Vector((0.08, 0.25, 0.25)), q + Vector((0.08, 0.25, 0.25))), None, glow=rng.choice(["pink", "cyan", "amber"]))
    j = rng.choice([1, 7])
    p = lows[0][j]
    k.add(box(p - Vector((0.25, 0.2, 0.35)), p + Vector((0.25, 0.2, 0.1))), mul(metal, 0.9), ao=False)
    # A small buried anchor below the floor: clients that fit a model by its bounding box treat
    # what reaches below the floor as founded and stand it on its origin, so the bundle hangs
    # at its height instead of lying on the ground. Place it by its origin.
    k.add(box((-0.05, -0.05, -0.6), (0.05, 0.05, -0.5)), pal["dark"], ao=False, vary=0)


def cyber_kiosk(k, H):
    """A row of vending machines under a canopy, or a little booth with a half-open shutter."""
    rng, pal = k.rng, k.pal
    metal, dark = pal["metal"], pal["dark"]
    c1, c2 = rng.sample(["pink", "cyan", "amber"], 2)
    if rng.random() < 0.55:
        n = rng.choice([2, 3, 4])
        w = 0.95
        W = n * w
        k.add(box((-W / 2 - 0.1, -0.5, 0), (W / 2 + 0.1, 0.5, 0.12)), mul(metal, 0.8))
        for i in range(n):
            x = -W / 2 + (i + 0.5) * w
            k.add(box((x - w / 2 + 0.03, -0.4, 0.12), (x + w / 2 - 0.03, 0.4, 2.0), 0.03), k.choice(pal["plastic"]), ao=False)
            f = Face((x, -0.4, 0), X, w)
            k.add(f.box(-0.38, 0.38, 0.75, 1.9, 0.0, 0.04, back=False), None, glow=rng.choice([c1, c2, True, True]))
            for r in range(3):
                k.add(f.box(-0.36, 0.36, 0.95 + r * 0.32, 1.0 + r * 0.32, 0.04, 0.07, back=False), mul(dark, 1.5), ao=False, vary=0)
            k.add(f.box(-0.3, 0.3, 0.25, 0.5, 0.0, 0.08, back=False), mul(dark, 1.2), ao=False)
        k.add(box((-W / 2 - 0.25, -0.75, H - 0.25), (W / 2 + 0.25, 0.55, H - 0.05)), mul(metal, 1.1), ao=False)
        k.add(box((-W / 2 - 0.25, -0.8, H - 0.3), (W / 2 + 0.25, -0.72, H - 0.2)), None, glow=c1)
        for e in (-1, 1):
            k.add(box((e * (W / 2 + 0.15) - 0.05, 0.4, 0.12), (e * (W / 2 + 0.15) + 0.05, 0.5, H - 0.25)), metal, ao=False)
    else:
        W, D = rng.uniform(1.8, 2.4), rng.uniform(1.4, 1.8)
        k.add(box((-W / 2, -D / 2, 0), (W / 2, D / 2, H - 0.45), 0.04), lambda co, n, c=k.choice(pal["trim"]): mul(c, 0.6 + 0.4 * min(1.0, co.z / 2.0)), ao=False)
        f = Face((0, -D / 2, 0), X, W)
        k.add(f.quad(-W / 2 + 0.2, W / 2 - 0.2, 1.0, 2.1, 0.01), None, glow=True, closed=False)
        k.add(f.box(-W / 2 + 0.2, W / 2 - 0.2, 1.6, 2.1, 0.01, 0.06, back=False), stripes(metal), ao=False)
        k.add(f.box(-W / 2 + 0.1, W / 2 - 0.1, 0.95, 1.05, 0.0, 0.4), mul(metal, 1.2), ao=False)
        k.add(box((-W / 2 - 0.2, -D / 2 - 0.4, H - 0.45), (W / 2 + 0.2, D / 2 + 0.1, H - 0.3)), mul(metal, 0.9), ao=False)
        cp_board(k, Face((0, -D / 2 - 0.4, 0), X, W), -W / 2, W / 2, H - 0.3, H, c1, mul(dark, 1.4))
        for i in range(4):
            k.add(box((-W / 2 + 0.25 + i * 0.4, -D / 2 + 0.05, 1.05), (-W / 2 + 0.5 + i * 0.4, -D / 2 + 0.35, 1.35)), k.choice(pal["plastic"]), ao=False)


def cyber_food_stall(k, H):
    """A street-food stall: a counter on a cart, a striped awning, paper lanterns, a steaming
    pot on a glowing burner, a neon menu, stools and a gas bottle."""
    rng, pal = k.rng, k.pal
    metal, dark = pal["metal"], pal["dark"]
    c1 = rng.choice(["pink", "cyan", "amber"])
    w, d = rng.uniform(1.2, 1.6), 0.6
    k.add(box((-w, -d, 0.25), (w, d, 1.0), 0.04), stripes(k.choice(pal["trim"]), 0.25, 0.85), ao=False)
    k.add(box((-w - 0.1, -d - 0.25, 1.0), (w + 0.1, d + 0.05, 1.08)), mul(metal, 1.3), ao=False)
    for e in (-1, 1):
        k.add(cyl((e * (w - 0.3), -d - 0.02, 0.25), (e * (w - 0.3), d + 0.02, 0.25), 0.24, 0.24, 8), (0.08, 0.08, 0.09), ao=False)
    front, back = H - 0.5, H - 0.05
    for x in (-w, w):
        k.add(box((x - 0.05, -d - 0.05, 1.0), (x + 0.05, -d + 0.05, front)), metal, ao=False)
        k.add(box((x - 0.05, d - 0.05, 1.0), (x + 0.05, d + 0.05, back)), metal, ao=False)
    aw = k.choice(pal["awning"])
    k.add(prism([(d + 0.15, back), (-d - 0.8, front - 0.1), (-d - 0.8, front - 0.02), (d + 0.15, back + 0.08)], -w - 0.25, w + 0.25,
                lambda a, s_, z: Vector((a, s_, z))), stripes(aw, 0.4, 0.75, 0), ao=False)
    k.add(box((-w - 0.25, -d - 0.85, front - 0.4), (w + 0.25, -d - 0.78, front - 0.05)), aw, ao=False)
    # Lanterns along the awning's edge.
    for i in range(rng.choice([3, 4, 5])):
        x = -w + i * 2 * w / max(1, rng.choice([3, 4, 5]) - 1)
        x = max(-w, min(w, x))
        k.add(cyl((x, -d - 0.7, front - 0.4), (x, -d - 0.7, front - 0.55), 0.01, 0.01, 4), (0.1, 0.1, 0.1), ao=False, vary=0)
        k.add(sphere((x, -d - 0.7, front - 0.78), 0.2, 1, squash=1.3), None, glow=rng.choice(["amber", "amber", "pink", True]))
    # The menu: a glowing board under the awning at the back.
    k.add(box((-w + 0.1, d - 0.08, 1.5), (w - 0.1, d, back - 0.35)), mul(dark, 1.5), ao=False)
    f = Face((0, d - 0.08, 0), X, 2 * w)
    k.add(f.box(-w + 0.2, w - 0.2, 1.6, back - 0.45, 0.0, 0.03, back=False), None, glow=c1)
    for r in range(3):
        z = 1.75 + r * (back - 2.2) / 3
        k.add(f.box(-w + 0.3, w * 0.4, z, z + 0.05, 0.03, 0.05, back=False), mul(dark, 1.5), ao=False, vary=0)
    # Pot, burner, steam hood.
    px = rng.uniform(-w * 0.4, w * 0.4)
    k.add(cyl((px, 0.1, 1.08), (px, 0.1, 1.14), 0.3, 0.3, 10), None, glow="amber")
    k.add(cyl((px, 0.1, 1.14), (px, 0.1, 1.5), 0.32, 0.3, 10), mul(metal, 1.3), ao=False)
    k.add(cyl((px + 0.8 * (1 if px < 0 else -1), 0.1, 1.08), (px + 0.8 * (1 if px < 0 else -1), 0.1, 1.2), 0.3, 0.3, 10), mul(metal, 0.9), ao=False)
    for e in (-1, 1):
        k.add(cyl((e * w * 0.5, -d - 0.6, 0), (e * w * 0.5, -d - 0.6, 0.55), 0.18, 0.18, 8), k.choice(pal["plastic"]), ao=False)
    k.add(cyl((w + 0.35, 0.2, 0), (w + 0.35, 0.2, 0.75), 0.18, 0.18, 8), (0.75, 0.2, 0.18), ao=False)


def cyber_walkway(k, H):
    """A raised walkway: a deck on pillars along X, glass-free railings with a glowing strip
    under the handrail, a stair down at one end, and a canopy over the middle."""
    rng, pal = k.rng, k.pal
    metal, iron = pal["metal"], pal["iron"]
    L = rng.uniform(12.0, 16.0)
    zd = H - 2.6
    wd = 1.3
    c1 = rng.choice(["cyan", "amber", "pink"])
    n = 3 if L > 14 else 2
    for i in range(n):
        x = -L / 2 + 1.5 + i * (L - 3.0) / (n - 1)
        k.add(box((x - 0.45, -0.45, 0), (x + 0.45, 0.45, zd - 0.6)), grime(pal["concrete"][0], 4.0, 0.5), ao=False)
        k.add(box((x - 0.5, -wd, zd - 0.7), (x + 0.5, wd, zd - 0.4)), mul(metal, 0.8), ao=False)
    k.add(box((-L / 2, -wd, zd - 0.4), (L / 2, wd, zd)), mul(pal["concrete"][3], 0.9), ao=False)
    k.add(box((-L / 2, -wd - 0.05, zd - 0.5), (L / 2, -wd + 0.05, zd - 0.42)), None, glow=c1)
    for e in (-1, 1):
        y = e * (wd - 0.05)
        k.add(box((-L / 2, y - 0.04, zd + 1.0), (L / 2, y + 0.04, zd + 1.1)), metal, ao=False)
        k.add(box((-L / 2, y - 0.03, zd + 0.9), (L / 2, y + 0.03, zd + 0.97)), None, glow=c1)
        for j in range(int(L / 1.5) + 1):
            x = -L / 2 + 0.1 + j * (L - 0.2) / int(L / 1.5)
            k.add(box((x - 0.04, y - 0.04, zd), (x + 0.04, y + 0.04, zd + 1.0)), iron, ao=False)
        k.add(box((-L / 2, y - 0.02, zd + 0.1), (L / 2, y + 0.02, zd + 0.5)), mul(metal, 0.7), ao=False)
    # Stairs down at one end, along -Y.
    e = rng.choice([-1, 1])
    sx = e * (L / 2 - 0.8)
    steps = int(zd / 0.25)
    run = steps * 0.28
    for i in range(steps):
        z = zd - (i + 1) * zd / steps
        y = -wd - (i + 1) * 0.28
        k.add(box((sx - 0.7, y, z), (sx + 0.7, y + 0.3, z + 0.1)), mul(metal, 1.1), ao=False)
    for s in (-1, 1):
        k.add(Face((sx + s * 0.72, -wd, 0), -Y, 1).obox(run / 2, zd / 2, math.hypot(run, zd), 0.25, -0.05, 0.05, -math.atan2(zd, run)), iron, ao=False)
    k.add(box((sx - 0.3, -wd - run - 0.3, 0), (sx + 0.3, -wd - run + 0.1, 0.2)), mul(metal, 0.8))
    # The canopy.
    cl = L * 0.55
    for x in (-cl / 2, cl / 2):
        for y in (-wd + 0.1, wd - 0.1):
            k.add(box((x - 0.05, y - 0.05, zd), (x + 0.05, y + 0.05, H - 0.15)), metal, ao=False)
    k.add(box((-cl / 2 - 0.3, -wd - 0.3, H - 0.18), (cl / 2 + 0.3, wd + 0.3, H)), stripes(mul(pal["panel"][0], 1.6), 0.5, 0.85, 0), ao=False)
    k.add(box((-cl / 2, -0.15, H - 0.25), (cl / 2, 0.15, H - 0.18)), None, glow="white")
    f = Face((0, -wd - 0.3, 0), X, cl)
    cp_board(k, f, -cl * 0.35, cl * 0.35, H - 0.9, H - 0.2, rng.choice(["pink", "cyan", "amber"]), mul(pal["dark"], 1.4))


def cyber_lamp(k, H):
    """A street light: an angular pole, a long arm with a strip-lit head, maybe a hanging sign."""
    rng, pal = k.rng, k.pal
    metal = pal["metal"]
    k.add(box((-0.3, -0.3, 0), (0.3, 0.3, 0.4), 0.04), pal["stone"])
    k.add(box((-0.16, -0.16, 0.4), (0.16, 0.16, 1.4)), mul(metal, 0.8), ao=False)
    k.add(box((-0.1, -0.1, 1.4), (0.1, 0.1, H - 0.1)), metal, ao=False)
    head = rng.choice(["white", "white", "cyan", True])
    arms = [1] if rng.random() < 0.6 else [-1, 1]
    for e in arms:
        L = rng.uniform(1.6, 2.2)
        k.add(Face((0, 0, 0), X, 1).obox(e * 0.4, H - 0.45, 0.9, 0.12, -0.06, 0.06, e * 0.6), metal)
        k.add(box((min(0, e * L), -0.12, H - 0.25), (max(0, e * L), 0.12, H)), metal, ao=False)
        k.add(box((min(e * 0.6, e * L), -0.1, H - 0.3), (max(e * 0.6, e * L), 0.1, H - 0.25)), None, glow=head)
    k.add(box((-0.12, -0.12, 0.9), (0.12, 0.12, 1.0)), None, glow=rng.choice(["pink", "cyan", "amber"]))
    if rng.random() < 0.5:
        cp_blade(k, Face((0, 0, 0), -Y if rng.random() < 0.5 else Y, 1), 0.0, H - 1.0, 1.6, 0.8, rng.choice(["pink", "cyan", "amber"]), mul(pal["dark"], 1.6))


def cyber_wall(k, H):
    """One segment of the megacity's border wall (settle/metro.rs `WallSpec`: 14 m high, 4 m
    thick), 5.1 m along X so 5 m pieces overlap round the curve; outer face -Y. Precast concrete
    panels on a plinth, a hazard band at the foot outside, a parapet over a service walk, a cold
    strip light under the coping, conduits down the inner face; sometimes a buttress inside, a
    floodlight on top or a warning panel."""
    rng, pal = k.rng, k.pal
    conc = k.choice(pal["concrete"])
    L, T = 2.55, 2.0
    walk = H - 1.5

    def panels(c, dirty=8.0):
        # Panel joints every 3 m up and at the segment's ends (where pieces meet), darker.
        g = grime(c, dirty, 0.62)

        def fn(co, n):
            joint = (co.z % 3.0) < 0.09 or abs(abs(co.x) - L) < 0.08
            return mul(g(co, n), 0.72 if joint else 1.0)
        return fn
    out, inner = Face((0, -T, 0), X, 2 * L), Face((0, T, 0), -X, 2 * L)
    k.add(box((-L, -T - 0.45, 0), (L, T + 0.35, 1.2), 0.04), grime(mul(conc, 0.78), 1.5, 0.6))
    k.add(box((-L, -T, 1.1), (L, T, walk), 0.03), panels(conc))
    k.add(out.box(-L, L, 1.25, 1.7, 0.0, 0.06), hazard(pal["trim"][0], pal["dark"]), ao=False)
    # The walk: outer parapet with its coping, deck, low inner rail.
    k.add(box((-L, -T, walk - 0.05), (L, -T + 0.45, H - 0.2), 0.03), panels(mul(conc, 1.04)))
    k.add(box((-L, -T - 0.18, H - 0.2), (L, -T + 0.6, H), 0.02), pal["metal"])
    k.add(box((-L, -T + 0.45, walk - 0.12), (L, T - 0.3, walk)), mul(conc, 0.85), vary=0, ao=False)
    k.add(box((-L, T - 0.3, walk - 0.05), (L, T, walk + 1.0), 0.02), panels(conc))
    k.add(out.box(-L + 0.15, L - 0.15, H - 0.95, H - 0.8, 0.0, 0.1), None, glow="white", ao=False)
    # Conduits down the inner face, clamped.
    for x in (-1.3, 1.1):
        k.add(cyl((x, T + 0.16, 1.2), (x, T + 0.16, walk - 0.2), 0.11, 0.11, 8), pal["metal"], ao=False)
        for z in (3.0, 6.0, 9.0):
            k.add(box((x - 0.16, T, z), (x + 0.16, T + 0.3, z + 0.12)), pal["iron"], ao=False, vary=0)
    v = rng.random()
    if v < 0.3:
        k.add(box((-0.7, T, 1.2), (0.7, T + 1.4, walk - 2.0), 0.04), panels(mul(conc, 0.95)))
        k.add(prism([(T + 1.4, walk - 2.0), (T, walk - 0.4), (T, walk - 2.0)], -0.7, 0.7, lambda a, s, z: Vector((a, s, z))), panels(mul(conc, 0.95)))
    elif v < 0.5:
        # A floodlight on the inner rail, below the coping (the model's top stays at H).
        k.add(box((-0.1, T - 0.25, walk + 1.0), (0.1, T - 0.05, H - 0.3)), pal["metal"], ao=False)
        k.add(box((-0.35, T - 0.5, H - 0.55), (0.35, T - 0.05, H - 0.25)), pal["dark"], ao=False)
        k.add(box((-0.3, T - 0.52, H - 0.52), (0.3, T - 0.5, H - 0.28)), None, glow="white", ao=False)
    elif v < 0.62:
        k.add(out.box(-0.9, 0.9, 3.2, 4.4, 0.0, 0.05), pal["dark"], ao=False)
        k.add(out.box(-0.8, 0.8, 3.3, 3.45, 0.05, 0.07), None, glow="red", ao=False)
        k.add(out.box(-0.8, 0.8, 3.6, 4.3, 0.05, 0.06), hazard(pal["trim"][0], pal["dark"], 0.25), ao=False)


def cyber_crate(k, H):
    """Street clutter: stacked plastic crates, drums and boxes, about H high."""
    rng, pal = k.rng, k.pal
    v = rng.random()
    if v < 0.5:
        for i in range(rng.choice([2, 3])):
            for j in range(rng.choice([1, 2, 3])):
                x = (i - 1) * 0.62 + rng.uniform(-0.03, 0.03)
                z = j * 0.4
                if z + 0.4 > H:
                    break
                c = k.choice(pal["plastic"])
                k.add(box((x - 0.3, -0.22, z), (x + 0.3, 0.22, z + 0.38), 0.02), stripes(c, 0.1, 0.8), ao=False)
    elif v < 0.8:
        for i in range(rng.choice([2, 3])):
            x = (i - 1) * 0.65
            c = k.choice(pal["trim"])
            k.add(cyl((x, 0, 0), (x, 0, H * 0.75), 0.3, 0.3, 10), stripes(c, 0.3, 0.75), ao=False)
            k.add(cyl((x, 0, H * 0.75), (x, 0, H * 0.77), 0.27, 0.27, 10), mul(c, 0.7), ao=False)
        k.add(box((0.4, -0.3, 0), (1.0, 0.3, H)), (0.55, 0.44, 0.30))
    else:
        k.add(box((-0.7, -0.5, 0), (0.7, 0.5, H * 0.6), 0.03), (0.55, 0.44, 0.30))
        k.add(box((-0.5, -0.4, H * 0.6), (0.3, 0.3, H), 0.03), (0.60, 0.48, 0.33))
        k.add(box((-0.71, -0.2, H * 0.3), (0.71, 0.2, H * 0.36)), (0.85, 0.75, 0.6), ao=False)


# ---------------------------------------------------------------------------------------------
# Small folk (designed in human-equivalent metres, then scaled down to their height)


def burrow(k, H, R=None):
    """A turf mound with a stone front, round door and windows; a big mound (R > 4.8) has four
    windows and two chimneys."""
    rng, pal = k.rng, k.pal
    R = R or rng.uniform(3.4, 4.2)
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
    big = R > 4.8
    for e, wa in [(e, e * R * f_) for e in (-1, 1) for f_ in ((0.36, 0.6) if big else (0.48,))]:
        wz = mh * (0.33 if big else 0.38)
        k.add(f.poly([(wa + math.cos(i / 12 * math.tau) * 0.62, wz + math.sin(i / 12 * math.tau) * 0.62) for i in range(12)], 0.1, 0.24), pal["timber"])
        k.add(f.poly([(wa + math.cos(i / 12 * math.tau) * 0.45, wz + math.sin(i / 12 * math.tau) * 0.45) for i in range(12)], 0.12, 0.27), None, glow=rng.random() < 0.7)
        k.add(f.box(wa - 0.07, wa + 0.07, wz - 0.45, wz + 0.45, 0.24, 0.32), pal["timber"])
    # Doorstep path, a chimney poking out of the turf, and flowers.
    for i in range(3):
        sx = rng.uniform(-0.2, 0.2)
        k.add(cyl(f.p(sx, 0.0, -0.6 - i * 1.0), f.p(sx, 0.12, -0.6 - i * 1.0), 0.55, 0.5, 7), jitter(pal["stone"], rng, 0.08), ao=False)
    for cx in ([-R * 0.35, R * 0.4] if big else [rng.uniform(-0.4, 0.4) * R]):
        cy = R * 0.2
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
        k.add(sphere(c + Vector((x, y, z)), rng.uniform(0.22, 0.4) * CR / 2.4, 1, squash=0.45), tagged((0.97, 0.95, 0.9), "plaster"), ao=False)


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


def small_house(k):
    """Small folk's houses by form: burrow, big mound, mushroom and tree-stump houses (design
    metres for a person; scaled to small folk)."""
    u = k.rng.uniform
    if k.form == "burrow":
        burrow(k, u(4.3, 5.0))
    elif k.form == "mound":
        burrow(k, u(5.6, 6.4), R=u(5.2, 6.0))
    elif k.form == "mushroom":
        mushroom_house(k, u(4.6, 5.6))
    else:
        stump_house(k, u(4.4, 5.4))


def mushroom_hall(k):
    """The small folk's hall: a great mushroom with a wide double door, a ring of round windows
    and two little mushroom annexes."""
    rng, pal = k.rng, k.pal
    u = rng.uniform
    H = u(8.5, 10.0)
    sr, sh = u(2.6, 3.0), u(4.2, 4.8)
    cream = pal["cream"]
    k.add(cyl((0, 0, 0), (0, 0, sh), sr * 1.15, sr * 0.95, 16), lambda co, n: mul(cream, 0.8 + 0.2 * min(1.0, co.z / 2.0)))
    f = cyl_face(sr * 1.15 - 0.1, 0)
    door(k, Face(f.p(0, 0, 0.0), X, 2), 0, 0.25, 1.7, 2.1, k.choice(pal["paint"]), pal["timber"], arch=True)
    for row, z in enumerate((1.7, 3.3)):
        for a in (0.75, 1.5, 2.3, 3.14, -0.75, -1.5, -2.3):
            if row == 0 and abs(a) < 0.8:
                continue
            rr = sr * 1.15 + (sr * 0.95 - sr * 1.15) * z / sh
            wf = cyl_face(rr - 0.06, a)
            k.add(wf.poly([(math.cos(i / 10 * math.tau) * 0.42, z + math.sin(i / 10 * math.tau) * 0.42) for i in range(10)], 0.0, 0.13), pal["timber"])
            k.add(wf.poly([(math.cos(i / 10 * math.tau) * 0.3, z + math.sin(i / 10 * math.tau) * 0.3) for i in range(10)], 0.02, 0.16), None, glow=rng.random() < 0.8)
    mushroom_cap(k, (0, 0, sh - 0.5), u(5.0, 5.8), H - sh + 0.5, k.choice(pal["cap"]), spots=(12, 18), droop=0.22)
    for e in (-1, 1):
        ax = e * (sr + u(2.2, 2.6))
        ay = u(0.4, 1.4)
        ar, ah = u(0.9, 1.1), u(2.4, 2.9)
        k.add(cyl((ax, ay, 0), (ax, ay, ah), ar * 1.15, ar * 0.95, 12), lambda co, n: mul(cream, 0.82 + 0.18 * min(1.0, co.z / 1.5)))
        wf = cyl_face(ar * 1.1, 0)
        wf.o = wf.o + Vector((ax, ay, 0))
        k.add(wf.poly([(math.cos(i / 10 * math.tau) * 0.35, 1.3 + math.sin(i / 10 * math.tau) * 0.35) for i in range(10)], 0.0, 0.13), pal["timber"])
        k.add(wf.poly([(math.cos(i / 10 * math.tau) * 0.24, 1.3 + math.sin(i / 10 * math.tau) * 0.24) for i in range(10)], 0.02, 0.16), None, glow=True)
        mushroom_cap(k, (ax, ay, ah - 0.3), u(1.7, 2.1), u(1.1, 1.5), k.choice(pal["cap"]), spots=(4, 7))
        lantern(k, (e * 1.5, -sr * 1.15 - 0.6, 2.2), 1.2)
        k.add(box((e * 1.5 - 0.06, -sr * 1.15 - 0.66, 0), (e * 1.5 + 0.06, -sr * 1.15 - 0.54, 1.95)), pal["timber"])
    k.add(cyl((1.6, 0.8, sh), (1.6, 0.8, H - 0.1), 0.22, 0.22, 8), pal["iron"], ao=False)
    k.add(cyl((1.6, 0.8, H - 0.1), (1.6, 0.8, H + 0.2), 0.34, 0.3, 8), pal["iron"], ao=False)
    for i in range(4):
        sx = rng.uniform(-0.2, 0.2)
        k.add(cyl((sx, -sr * 1.15 - 0.5 - i * 0.95, 0), (sx, -sr * 1.15 - 0.5 - i * 0.95, 0.1), 0.48, 0.44, 7), jitter(pal["stone"], rng, 0.08), ao=False)


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
    if len(hull) < 3 or depth <= 0:
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
        # The top course pale, then alternating, so the courses read where a slope bares them.
        shade = 1.02 if i == 0 else 0.84 - 0.04 * i + (0.1 if i % 2 else 0.0)
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


# ---------------------------------------------------------------------------------------------
# Street props: ornaments and terracing the settlement planner places (settle/ornament.rs).
# One generator per kind, in the fantasy look (also for giants and small folk, scaled to them),
# with steampunk and cyberpunk equivalents. Low triangle counts: they are many and small.

WATER = (0.24, 0.46, 0.62)
# Street trees' and planters' leaves stay plain: on their small round lobes the leaves texture read
# as pitted, dirty blotches (blind A/B, 2026-11-09).
LEAF = [(0.30, 0.52, 0.22), (0.38, 0.58, 0.24), (0.26, 0.46, 0.24), (0.44, 0.56, 0.20)]
BLOOM = [(0.92, 0.30, 0.36), (0.96, 0.78, 0.22), (0.86, 0.50, 0.86), (0.98, 0.96, 0.92), (0.40, 0.56, 0.92)]


def look(k):
    """The prop's look: steampunk, cyberpunk or fantasy (giants and small folk too)."""
    return {"steampunk": "steam", "cyberpunk": "cyber"}.get(k.style, "fantasy")


def wood(k):
    return k.pal.get("timber", (0.36, 0.24, 0.16))


def flowers(k, x0, x1, y0, y1, z, n, r=0.09):
    """A bed of leaves with a few blooms on top, between x0..x1 and y0..y1 at height z."""
    rng = k.rng
    for i in range(max(1, int(n * 0.6))):
        c = (rng.uniform(x0, x1), rng.uniform(y0, y1), z)
        k.add(sphere(c, r * rng.uniform(1.4, 2.0), 1, squash=0.7), k.choice(LEAF), soft=Vector(c))
    for i in range(n):
        c = (rng.uniform(x0, x1), rng.uniform(y0, y1), z + r * rng.uniform(0.6, 1.4))
        k.add(sphere(c, r, 0), k.choice(BLOOM), ao=False)


def crown(k, c, r, color, lobes=4, squash=0.85):
    """A tree crown of a few soft lobes round c."""
    rng = k.rng
    k.add(sphere(c, r, 2, squash=squash), color, soft=Vector(c))
    for i in range(lobes):
        a = i / lobes * math.tau + rng.uniform(-0.3, 0.3)
        lc = (c[0] + math.cos(a) * r * 0.6, c[1] + math.sin(a) * r * 0.6, c[2] + rng.uniform(-0.3, 0.25) * r)
        k.add(sphere(lc, r * rng.uniform(0.55, 0.7), 1, squash=squash), mul(color, rng.uniform(0.9, 1.08)), soft=Vector(c))


def prop_barrel(k):
    """A barrel (single) or a group of two or three, one maybe on its side."""
    rng, pal, lk = k.rng, k.pal, look(k)
    n = 1 if k.form == "single" else rng.choice([2, 3])
    spots = [(0.0, 0.0), (0.68, 0.08), (0.32, 0.6)][:n]
    for i, (x, y) in enumerate(spots):
        x -= 0.3 * (n > 1)
        if lk == "fantasy":
            barrel(k, (x, y, 0), 0.32, 0.86, mul(wood(k), rng.uniform(1.0, 1.25)))
            k.add(cyl((x, y, 0.85), (x, y, 0.87), 0.28, 0.28, 10), mul(wood(k), 1.5), ao=False)
        elif lk == "steam":
            c = k.choice(pal["paint"]) if rng.random() < 0.6 else pal["steel"]
            k.add(cyl((x, y, 0), (x, y, 0.9), 0.3, 0.3, 10), c)
            for z in (0.08, 0.45, 0.82):
                k.add(cyl((x, y, z), (x, y, z + 0.05), 0.315, 0.315, 10), pal["brass"], ao=False)
            k.add(cyl((x + 0.12, y, 0.9), (x + 0.12, y, 0.95), 0.05, 0.05, 6), pal["brass"], ao=False)
        else:
            c = k.choice(pal["trim"])
            k.add(cyl((x, y, 0), (x, y, 0.88), 0.29, 0.29, 10), stripes(c, 0.29, 0.72), ao=False)
            k.add(cyl((x, y, 0.88), (x, y, 0.9), 0.26, 0.26, 10), mul(c, 0.6), ao=False)


def prop_crate(k):
    """A stack of plank crates and a sack or two."""
    rng = k.rng
    w = wood(k)
    c = tagged(lerp(w, (0.78, 0.62, 0.42), 0.55), "planks")
    for i, (x, z, s) in enumerate([(0.0, 0.0, 0.62), (0.68, 0.0, 0.55), (0.3, 0.62, 0.5)][:rng.choice([2, 3])]):
        cc = jitter(c, rng, 0.08)
        k.add(box((x - s / 2, -s / 2, z), (x + s / 2, s / 2, z + s), 0.02), lambda co, n, cc=cc, z=z, s=s: mul(cc, 0.82 if int((co.z - z) / (s / 3)) % 2 else 1.0))
    if rng.random() < 0.6:
        sc = (-0.6, 0.05, 0.28)
        k.add(sphere(sc, 0.3, 1, squash=1.1), (0.80, 0.72, 0.55), soft=Vector(sc))


def wheel(k, c, r, axis, color, rim, spokes=True):
    """A cart wheel: a rim, a hub and (spoked) a few spokes, turning about `axis` (X or Y)."""
    c = Vector(c)
    a = axis * 0.06
    k.add(cyl(c - a, c + a, r, r, 12), rim, ao=False)
    k.add(cyl(c - a * 1.3, c + a * 1.3, r * 0.82, r * 0.82, 12), mul(color, 0.7) if spokes else color, ao=False)
    k.add(cyl(c - a * 2.2, c + a * 2.2, r * 0.2, r * 0.2, 8), rim, ao=False)


def prop_cart(k):
    """A handcart or a wagon: wooden (fantasy), a coal truck or steam barrow (steampunk), a
    delivery trike or hover cart (cyberpunk). Shafts or handles to the front (-Y)."""
    rng, pal, lk = k.rng, k.pal, look(k)
    big = k.form == "wagon"
    L, W = (3.4, 1.7) if big else (2.0, 1.05)
    if lk == "cyber":
        body = k.choice(pal["plastic"])
        z0 = 0.55 if big else 0.4
        k.add(box((-W / 2, -L / 2 + 0.4, z0), (W / 2, L / 2, z0 + (1.1 if big else 0.8)), 0.04), body)
        k.add(box((-W / 2 - 0.01, -L / 2 + 0.4, z0 + 0.25), (W / 2 + 0.01, L / 2 + 0.01, z0 + 0.32)), None, glow="cyan")
        if big:
            for x in (-W / 2 + 0.2, W / 2 - 0.2):
                for y in (-L / 2 + 0.7, L / 2 - 0.3):
                    k.add(cyl((x, y, 0.0), (x, y, z0), 0.12, 0.08, 6), pal["metal"])
            k.add(box((-W / 2 + 0.1, -L / 2 + 0.6, z0 - 0.06), (W / 2 - 0.1, L / 2 - 0.2, z0 - 0.02)), None, glow="pink")
        else:
            for x in (-W / 2 - 0.1, W / 2 + 0.1):
                wheel(k, (x, L / 2 - 0.35, 0.28), 0.28, X, pal["dark"], pal["metal"], spokes=False)
            wheel(k, (0, -L / 2 + 0.25, 0.28), 0.28, X, pal["dark"], pal["metal"], spokes=False)
            k.add(box((-0.06, -L / 2 + 0.2, 0.3), (0.06, -L / 2 + 0.45, 1.1)), pal["metal"])
            k.add(box((-0.35, -L / 2 + 0.25, 1.05), (0.35, -L / 2 + 0.33, 1.12)), pal["dark"])
        return
    steam = lk == "steam"
    wd = mul(pal["iron"], 1.6) if steam else mul(wood(k), 1.25)
    rim = pal["brass"] if steam else pal["iron"]
    r = 0.55 if big else 0.45
    zb = r + 0.05
    k.add(box((-W / 2, -L / 2 + 0.3, zb), (W / 2, L / 2, zb + 0.08)), wd)
    for e in (-1, 1):
        k.add(box((e * W / 2 - 0.05, -L / 2 + 0.3, zb), (e * W / 2 + 0.05, L / 2, zb + 0.42)), wd)
    k.add(box((-W / 2, L / 2 - 0.08, zb), (W / 2, L / 2, zb + 0.42)), wd)
    k.add(box((-W / 2, -L / 2 + 0.3, zb), (W / 2, -L / 2 + 0.38, zb + 0.42)), wd)
    ys = [L * 0.2, -L * 0.25] if big else [L * 0.1]
    for y in ys:
        for e in (-1, 1):
            wheel(k, (e * (W / 2 + 0.1), y, r), r, X, wd, rim)
    if big and steam:
        # A little boiler and stack at the front of a steam barrow.
        k.add(cyl((0, -L / 2 + 0.75, zb + 0.08), (0, -L / 2 + 0.75, zb + 1.0), 0.38, 0.38, 10), k.choice(pal["copper"]))
        k.add(cyl((0, -L / 2 + 0.75, zb + 1.0), (0, -L / 2 + 0.75, zb + 1.7), 0.1, 0.14, 8), pal["iron"])
        k.add(cyl((0, -L / 2 + 0.75, zb + 1.7), (0, -L / 2 + 0.75, zb + 1.78), 0.2, 0.2, 8), pal["brass"], ao=False)
    else:
        # Shafts (a wagon) or handles (a handcart) to the front.
        for e in (-1, 1):
            x = e * (W / 2 - 0.1)
            k.add(box((x - 0.04, -L / 2, zb + 0.05), (x + 0.04, -L / 2 + 0.6, zb + 0.13)), wd)
    # A load: sacks, a barrel, coal.
    if steam:
        k.add(box((-W / 2 + 0.1, -L / 2 + 0.5 + (0.9 if big else 0), zb + 0.08), (W / 2 - 0.1, L / 2 - 0.1, zb + 0.32)), (0.12, 0.12, 0.13), ao=False)
    else:
        for i in range(rng.choice([1, 2, 3])):
            sc = (rng.uniform(-W / 4, W / 4), rng.uniform(-L / 4, L / 3), zb + 0.3)
            k.add(sphere(sc, 0.28, 1, squash=0.8), tagged((0.80, 0.72, 0.55), "cloth"), soft=Vector(sc))


def prop_bench(k):
    """A bench to sit on, its seat facing the front (-Y)."""
    rng, pal, lk = k.rng, k.pal, look(k)
    L = rng.uniform(1.6, 2.0)
    if lk == "cyber":
        k.add(box((-L / 2, -0.25, 0), (L / 2, 0.25, 0.45), 0.03), k.choice(pal["concrete"]))
        k.add(box((-L / 2 + 0.1, -0.26, 0.05), (L / 2 - 0.1, -0.25, 0.1)), None, glow=k.choice(["cyan", "pink"]))
        k.add(box((-L / 2, 0.2, 0.45), (L / 2, 0.3, 0.95), 0.02), pal["metal"])
        return
    seat = k.choice(pal["paint"]) if lk == "steam" else mul(wood(k), 1.3)
    leg = pal["iron"] if lk == "steam" else mul(wood(k), 1.0)
    back = lk == "steam" or rng.random() < 0.6
    for e in (-1, 1):
        x = e * (L / 2 - 0.15)
        if lk == "steam":
            k.add(box((x - 0.04, -0.28, 0), (x + 0.04, 0.24, 0.45)), leg)
            if back:
                k.add(Face((x, 0, 0), Y, 1).obox(0.2, 0.7, 0.55, 0.06, -0.04, 0.04, 1.35), leg)
        else:
            k.add(box((x - 0.07, -0.22, 0), (x + 0.07, 0.22, 0.42)), leg)
    slats = 3 if lk == "steam" else 2
    for i in range(slats):
        y = -0.24 + i * 0.48 / slats
        k.add(box((-L / 2, y, 0.42), (L / 2, y + 0.48 / slats - 0.03, 0.47)), seat)
    if back:
        for z in (0.62, 0.8):
            k.add(box((-L / 2, 0.24, z), (L / 2, 0.29, z + 0.1)), seat)
        if lk != "steam":
            for e in (-1, 1):
                x = e * (L / 2 - 0.15)
                k.add(box((x - 0.05, 0.22, 0.42), (x + 0.05, 0.3, 0.92)), leg)


def rim(k, r_in, r_out, z0, z1, n, color, ao=True):
    """A ring wall round the origin (a basin's rim) from n straight segments."""
    def polar(q):
        return Vector((q.y * math.cos(q.x), q.y * math.sin(q.x), q.z))
    for i in range(n):
        a0, a1 = i / n * math.tau, (i + 1.02) / n * math.tau
        k.add(lbox(Vector((a0, r_in, z0)), Vector((a1, r_out, z1)), fn=polar), color, ao=ao)


def prop_fountain(k):
    """The plaza's fountain: a stone basin with a column and bowl (fantasy), an iron basin with
    a column of gears and spouts (steampunk), a concrete basin with a lit ring and spire
    (cyberpunk)."""
    rng, pal, lk = k.rng, k.pal, look(k)
    R = rng.uniform(2.0, 2.4)
    stone = pal["stone"] if lk != "cyber" else k.choice(pal["concrete"])
    sides = 8 if lk == "fantasy" else 16
    # The basin: a low floor of water inside a rim with a coping.
    k.add(cyl((0, 0, 0), (0, 0, 0.42), R - 0.25, R - 0.25, sides), WATER, ao=False, vary=0.0)
    rim(k, R - 0.3, R, 0.0, 0.62, sides, stone if lk != "steam" else pal["iron"])
    rim(k, R - 0.34, R + 0.08, 0.62, 0.72, sides, mul(stone, 1.12) if lk != "steam" else pal["brass"], ao=False)
    if lk == "cyber":
        # A lit band round the coping (a thin ring, so the water shows).
        def polar(q):
            return Vector((q.y * math.cos(q.x), q.y * math.sin(q.x), q.z))
        for i in range(16):
            a0, a1 = i / 16 * math.tau, (i + 1.02) / 16 * math.tau
            k.add(lbox(Vector((a0, R + 0.08, 0.6)), Vector((a1, R + 0.1, 0.68)), fn=polar), None, glow="cyan")
        k.add(cyl((0, 0, 0.5), (0, 0, 3.6), 0.28, 0.12, 6), pal["metal"])
        k.add(cyl((0, 0, 1.2), (0, 0, 3.2), 0.18, 0.08, 6), None, glow=k.choice(["cyan", "pink"]))
        k.add(sphere((0, 0, 3.75), 0.2, 1), None, glow="white")
        return
    if lk == "steam":
        iron, brass = pal["iron"], pal["brass"]
        k.add(cyl((0, 0, 0.5), (0, 0, 2.6), 0.3, 0.22, 10), iron)
        for z, r in ((1.1, 0.55), (1.8, 0.42), (2.4, 0.32)):
            gear(k, Vector((0, 0, z)), X, Y, r, 10, 0.08, brass)
        for i in range(4):
            a = i / 4 * math.tau
            d = Vector((math.cos(a), math.sin(a), 0))
            pipe_run(k, [Vector((0, 0, 1.5)) + d * 0.25, Vector((0, 0, 1.5)) + d * 0.8, Vector((0, 0, 1.15)) + d * 0.95], 0.06, k.choice(pal["copper"]))
        k.add(sphere((0, 0, 2.75), 0.16, 1), brass, ao=False)
        return
    # Fantasy: a column with a bowl and a finial; jets as pale cones.
    k.add(cyl((0, 0, 0.5), (0, 0, 1.6), 0.28, 0.22, 8), mul(stone, 0.95))
    k.add(cyl((0, 0, 1.6), (0, 0, 1.8), 0.25, 0.95, 8), stone)
    k.add(cyl((0, 0, 1.8), (0, 0, 1.83), 0.82, 0.82, 8), WATER, ao=False, vary=0.0)
    rim(k, 0.82, 0.97, 1.8, 1.9, 8, mul(stone, 1.08))
    k.add(cyl((0, 0, 1.85), (0, 0, 2.5), 0.14, 0.1, 8), stone)
    k.add(sphere((0, 0, 2.62), 0.16, 1), mul(stone, 1.1))
    for i in range(4):
        a = i / 4 * math.tau + math.pi / 4
        k.add(cyl((math.cos(a) * 0.9, math.sin(a) * 0.9, 1.75), (math.cos(a) * 1.5, math.sin(a) * 1.5, 0.55), 0.05, 0.02, 4), (0.78, 0.88, 0.95), ao=False)


def prop_market_cross(k):
    """A market cross on steps (fantasy), a clock pillar (steampunk), an info pylon with
    screens (cyberpunk)."""
    rng, pal, lk = k.rng, k.pal, look(k)
    if lk == "cyber":
        c = k.choice(pal["panel"])
        k.add(box((-0.9, -0.9, 0), (0.9, 0.9, 0.3), 0.03), k.choice(pal["concrete"]))
        k.add(box((-0.5, -0.25, 0.3), (0.5, 0.25, 4.6), 0.03), c)
        for f in (Face((0, -0.25, 0), X, 1.0), flipped(Face((0, 0.25, 0), X, 1.0))):
            cp_screen(k, f, 0.0, 1.6, 0.8, 2.2, k.choice(list(NEON)[:3]), k.choice(list(NEON)[:3]), out=0.04)
        k.add(box((-0.52, -0.27, 4.4), (0.52, 0.27, 4.45)), None, glow="cyan")
        k.add(sphere((0, 0, 4.8), 0.14, 1), None, glow="red")
        k.add(cyl((0, 0, 4.6), (0, 0, 4.75), 0.03, 0.03, 4), pal["metal"])
        return
    stone = pal["stone"]
    for i, r in enumerate((1.5, 1.15, 0.8)):
        k.add(cyl((0, 0, i * 0.25), (0, 0, (i + 1) * 0.25), r, r, 8), mul(stone, 1.0 - 0.05 * i))
    if lk == "steam":
        iron, brass = pal["iron"], pal["brass"]
        k.add(cyl((0, 0, 0.75), (0, 0, 3.3), 0.16, 0.13, 10), iron)
        k.add(box((-0.42, -0.42, 3.3), (0.42, 0.42, 4.1), 0.03), iron)
        for f in box_faces(0, 0, 0.42, 0.42).values():
            clock_face(k, f, 0.0, 3.7, 0.28, brass)
        k.add(cyl((0, 0, 4.1), (0, 0, 4.6), 0.5, 0.05, 8), k.choice(pal["copper"]))
        k.add(sphere((0, 0, 4.65), 0.07, 1), brass, ao=False)
        return
    k.add(cyl((0, 0, 0.75), (0, 0, 4.2), 0.22, 0.16, 8), mul(stone, 1.05))
    k.add(box((-0.32, -0.32, 4.2), (0.32, 0.32, 4.6), 0.02), stone)
    k.add(box((-0.06, -0.06, 4.6), (0.06, 0.06, 5.4)), mul(stone, 1.1))
    k.add(box((-0.3, -0.06, 5.0), (0.3, 0.06, 5.12)), mul(stone, 1.1))


def prop_fence(k):
    """A fence section exactly as long as its form (f0.5 … f4 m, every 0.25 m: PROPS) along X: pickets
    on two rails (fantasy, small folk), post and rail (giants), iron railings on a brick plinth
    (steampunk), mesh panels (cyberpunk). The planner runs sections on from one another in equal
    pieces and fills beside a gate with what is left, so lengths come every 0.25 m: with only 2,
    3 and 4 m, sections fell up to a metre short of the next and gates stood in gaps. One design
    per style (FENCE_VARIANTS), so neighbouring sections match."""
    rng, pal, lk = k.rng, k.pal, look(k)
    L = float(k.form[1:])
    h = 1.1
    if lk == "steam":
        k.add(box((-L / 2, -0.14, 0), (L / 2, 0.14, 0.32)), k.choice(pal["brick"]))
        k.add(box((-L / 2, -0.16, 0.32), (L / 2, 0.16, 0.38)), pal["stone"])
        n = max(1, round(L / 0.16))
        for i in range(n):
            x = -L / 2 + (i + 0.5) * L / n
            k.add(box((x - 0.012, -0.012, 0.38), (x + 0.012, 0.012, h + 0.2)), pal["iron"], ao=False, vary=0.0)
            if i % 2 == 0:
                k.add(cyl((x, 0, h + 0.2), (x, 0, h + 0.3), 0.03, 0.0, 4), pal["iron"], ao=False, vary=0.0)
        k.add(box((-L / 2, -0.02, h + 0.08), (L / 2, 0.02, h + 0.13)), pal["iron"], ao=False)
        k.add(box((-L / 2, -0.02, 0.5), (L / 2, 0.02, 0.55)), pal["iron"], ao=False)
        return
    if lk == "cyber":
        posts = max(2, int(round(L / 2)) + 1)
        for i in range(posts):
            x = -L / 2 + 0.04 + i * (L - 0.08) / (posts - 1)
            k.add(box((x - 0.04, -0.04, 0), (x + 0.04, 0.04, 1.6)), pal["metal"])
        k.add(box((-L / 2, -0.01, 0.1), (L / 2, 0.01, 1.5)), lambda co, n: mul((0.30, 0.32, 0.36), 0.8 if int((co.x + co.z) / 0.1) % 2 else 1.0), ao=False)
        k.add(box((-L / 2, -0.03, 1.5), (L / 2, 0.03, 1.56)), hazard((0.9, 0.75, 0.1), (0.1, 0.1, 0.1), 0.3), ao=False)
        return
    w = mul(wood(k), 1.25)
    posts = max(2, int(round(L)) + 1)
    for i in range(posts):
        x = -L / 2 + 0.05 + i * (L - 0.1) / (posts - 1)
        k.add(box((x - 0.05, -0.05, 0), (x + 0.05, 0.05, h + 0.05)), mul(w, 0.85))
    if k.style == "giant":
        for z in (0.35, 0.85):
            k.add(box((-L / 2, -0.03, z), (L / 2, 0.03, z + 0.09)), w)
    else:
        k.add(box((-L / 2, -0.05, 0.25), (L / 2, -0.03, 0.33)), w)
        k.add(box((-L / 2, -0.05, 0.75), (L / 2, -0.03, 0.83)), w)
        n = max(1, round(L / 0.14))
        for i in range(n):
            x = -L / 2 + (i + 0.5) * L / n
            k.add(box((x - 0.04, -0.03, 0.05), (x + 0.04, -0.01, h - 0.05)), mul(w, 1.08), vary=0.06)


def prop_gate(k):
    """A garden gate between two posts, 1.4 m across."""
    rng, pal, lk = k.rng, k.pal, look(k)
    L = 1.4
    if lk == "cyber":
        for e in (-1, 1):
            k.add(box((e * L / 2 - 0.08, -0.08, 0), (e * L / 2 + 0.08, 0.08, 1.2)), pal["metal"])
        k.add(box((-L / 2 + 0.08, -0.03, 0.85), (L / 2 - 0.08, 0.03, 0.95)), hazard((0.9, 0.75, 0.1), (0.1, 0.1, 0.1), 0.2), ao=False)
        k.add(box((L / 2 - 0.1, -0.09, 1.2), (L / 2 + 0.1, 0.09, 1.28)), None, glow="red")
        return
    post = pal["stone"] if lk == "steam" else mul(wood(k), 0.85)
    for e in (-1, 1):
        k.add(box((e * L / 2 - 0.1, -0.1, 0), (e * L / 2 + 0.1, 0.1, 1.35)), post)
        k.add(box((e * L / 2 - 0.13, -0.13, 1.35), (e * L / 2 + 0.13, 0.13, 1.42)), mul(post, 1.1))
    if lk == "steam":
        n = 7
        for i in range(n):
            x = -L / 2 + 0.15 + i * (L - 0.3) / (n - 1)
            top = 1.0 + 0.22 * math.sin(math.pi * (i / (n - 1)))
            k.add(box((x - 0.015, -0.015, 0.08), (x + 0.015, 0.015, top)), pal["iron"], ao=False, vary=0.0)
        for z in (0.1, 0.55):
            k.add(box((-L / 2 + 0.1, -0.02, z), (L / 2 - 0.1, 0.02, z + 0.05)), pal["iron"], ao=False)
        k.add(sphere((0, 0, 1.25), 0.06, 0), pal["brass"], ao=False)
        return
    w = mul(wood(k), 1.3)
    for z in (0.15, 0.75):
        k.add(box((-L / 2 + 0.1, -0.03, z), (L / 2 - 0.1, 0.03, z + 0.1)), w)
    k.add(Face((0, -0.03, 0), X, 1).obox(0.0, 0.5, math.hypot(L - 0.3, 0.6), 0.09, -0.03, 0.03, math.atan2(0.6, L - 0.3)), w)
    for i in range(5):
        x = -L / 2 + 0.2 + i * (L - 0.4) / 4
        k.add(box((x - 0.04, -0.02, 0.1), (x + 0.04, 0.02, 1.0)), mul(w, 1.05))


def prop_planter(k):
    """A planted tub (fantasy), an iron urn on a pedestal (steampunk), a concrete box with a lit
    edge (cyberpunk)."""
    rng, pal, lk = k.rng, k.pal, look(k)
    if lk == "steam":
        k.add(cyl((0, 0, 0), (0, 0, 0.35), 0.28, 0.2, 8), pal["stone"])
        k.add(cyl((0, 0, 0.35), (0, 0, 0.75), 0.2, 0.42, 8), pal["iron"])
        k.add(cyl((0, 0, 0.75), (0, 0, 0.8), 0.46, 0.46, 8), pal["brass"], ao=False)
        flowers(k, -0.3, 0.3, -0.3, 0.3, 0.85, 7)
        return
    if lk == "cyber":
        L = rng.uniform(1.2, 1.8)
        k.add(box((-L / 2, -0.4, 0), (L / 2, 0.4, 0.6), 0.03), k.choice(pal["concrete"]))
        k.add(box((-L / 2 - 0.005, -0.405, 0.5), (L / 2 + 0.005, 0.405, 0.54)), None, glow=k.choice(["cyan", "pink", "amber"]))
        flowers(k, -L / 2 + 0.2, L / 2 - 0.2, -0.25, 0.25, 0.62, 3, r=0.14)
        return
    w = mul(wood(k), 1.2)
    k.add(cyl((0, 0, 0), (0, 0, 0.5), 0.36, 0.42, 10), w)
    for z in (0.08, 0.4):
        k.add(cyl((0, 0, z), (0, 0, z + 0.04), 0.4 + z * 0.12, 0.4 + z * 0.12, 10), pal["iron"], ao=False)
    flowers(k, -0.3, 0.3, -0.3, 0.3, 0.55, 8)


def prop_flower_box(k):
    """A trough of flowers to stand under a window or beside a door, 1-1.4 m long."""
    rng, pal, lk = k.rng, k.pal, look(k)
    L = rng.uniform(1.0, 1.4)
    if lk == "cyber":
        c = k.choice(pal["plastic"])
        k.add(box((-L / 2, -0.17, 0), (L / 2, 0.17, 0.4), 0.02), c)
        k.add(box((-L / 2 + 0.05, -0.18, 0.3), (L / 2 - 0.05, -0.17, 0.33)), None, glow="pink")
    elif lk == "steam":
        k.add(box((-L / 2, -0.17, 0), (L / 2, 0.17, 0.42), 0.02), pal["iron"])
        k.add(box((-L / 2 - 0.02, -0.19, 0.38), (L / 2 + 0.02, 0.19, 0.43)), pal["brass"], ao=False)
    else:
        k.add(box((-L / 2, -0.17, 0), (L / 2, 0.17, 0.4), 0.02), lambda co, n: mul(k.pal.get("timber", (0.4, 0.3, 0.2)), 1.25 if int(co.z / 0.13) % 2 else 1.1))
    flowers(k, -L / 2 + 0.12, L / 2 - 0.12, -0.08, 0.08, 0.42, int(L * 6))


def prop_sign(k):
    """A shop sign hanging from a bracket on a post (shop), or a signpost with pointing arms
    (post)."""
    rng, pal, lk = k.rng, k.pal, look(k)
    steam = lk == "steam"
    post = pal["iron"] if steam else mul(wood(k), 0.9)
    if k.form == "post":
        k.add(box((-0.07, -0.07, 0), (0.07, 0.07, 2.7)), post)
        for i in range(rng.choice([2, 3])):
            z = 2.35 - i * 0.32
            e = 1 if i % 2 == 0 else -1
            c = k.choice(pal["paint"]) if steam else mul(wood(k), 1.6)
            k.add(box((min(0, e * 0.95), -0.03, z), (max(0, e * 0.95), 0.03, z + 0.2)), c)
            k.add(Face((0, 0, 0), X, 1).obox(e * 1.0, z + 0.1, 0.16, 0.16, -0.03, 0.03, math.pi / 4), c)
        k.add(sphere((0, 0, 2.75), 0.08, 0), pal["brass"] if steam else post, ao=False)
        return
    k.add(box((-0.07, -0.07, 0), (0.07, 0.07, 3.1)), post)
    k.add(box((-0.06, -0.62, 2.85), (0.06, 0.06, 2.92)), post)
    k.add(Face((0, -0.04, 0), Y, 1).obox(-0.22, 2.62, 0.5, 0.05, -0.03, 0.03, 0.75), post)
    c = k.choice(pal["paint"])
    k.add(box((-0.03, -0.6, 2.1), (0.03, -0.12, 2.75)), c)
    k.add(box((-0.035, -0.56, 2.16), (0.035, -0.16, 2.69)), pal["brass"] if steam else mul(c, 1.5), ao=False)
    for y in (-0.52, -0.2):
        k.add(box((-0.01, y - 0.01, 2.75), (0.01, y + 0.01, 2.85)), pal["iron"], ao=False, vary=0.0)


def prop_banner(k):
    """A banner on a pole: cloth with a pennant (fantasy), with a gas globe (steampunk), a lit
    holo strip (cyberpunk)."""
    rng, pal, lk = k.rng, k.pal, look(k)
    H = 5.0
    pole = pal["metal"] if lk == "cyber" else pal["iron"] if lk == "steam" else mul(wood(k), 0.9)
    k.add(box((-0.25, -0.25, 0), (0.25, 0.25, 0.3)), pal["stone"])
    k.add(cyl((0, 0, 0.3), (0, 0, H), 0.07, 0.05, 6), pole)
    k.add(box((0.0, -0.03, H - 0.45), (0.85, 0.03, H - 0.4)), pole)
    if lk == "cyber":
        k.add(box((0.15, -0.03, H - 3.0), (0.75, 0.03, H - 0.5)), k.choice(pal["panel"]))
        k.add(box((0.2, -0.04, H - 2.9), (0.7, -0.03, H - 0.6)), None, glow=k.choice(["pink", "cyan", "amber"]))
        k.add(sphere((0, 0, H + 0.05), 0.08, 0), None, glow="red")
        return
    c = k.choice(pal["paint"])
    trim = pal["brass"] if lk == "steam" else (0.95, 0.85, 0.45)
    k.add(box((0.12, -0.02, H - 2.6), (0.78, 0.02, H - 0.45)), lambda co, n: c if co.z > H - 2.2 else mul(trim, 0.95))
    k.add(prism([(0.12, H - 2.6), (0.45, H - 2.9), (0.78, H - 2.6)], -0.02, 0.02, lambda a, s, z: Vector((s, a, z))), c)
    if lk == "steam":
        k.add(sphere((0, 0, H + 0.2), 0.18, 1), None, glow=True)
        k.add(cyl((0, 0, H), (0, 0, H + 0.05), 0.12, 0.12, 6), pal["brass"], ao=False)
    else:
        k.add(prism([(0.0, H), (0.6, H + 0.15), (0.0, H + 0.3)], -0.01, 0.01, lambda a, s, z: Vector((s, a, z))), k.choice(pal["paint"]))


def prop_washing_line(k):
    """A washing line with clothes pegged on it: between two posts in a garden (posts), or a
    bare line to string between two houses about 3.2 m up (span3, span45, span6)."""
    rng, pal, lk = k.rng, k.pal, look(k)
    posts = k.form == "posts"
    L = 4.0 if posts else {"span3": 3.0, "span45": 4.5, "span6": 6.0}[k.form]
    z = 2.0 if posts else 3.3
    if posts:
        for e in (-1, 1):
            k.add(box((e * L / 2 - 0.05, -0.05, 0), (e * L / 2 + 0.05, 0.05, z + 0.15)), mul(wood(k), 1.1))
            k.add(box((e * L / 2 - 0.05, -0.25, z + 0.05), (e * L / 2 + 0.05, 0.25, z + 0.12)), mul(wood(k), 1.1))
    sag_line(k, Vector((-L / 2, 0, z + 0.1)), Vector((L / 2, 0, z + 0.1)), 0.15, 0.012, (0.85, 0.82, 0.75), seg=6, sides=3, surface="cloth")
    cloth = [tagged(c, "cloth") for c in [(0.95, 0.94, 0.90), (0.80, 0.86, 0.95), (0.92, 0.70, 0.66), (0.86, 0.80, 0.55), (0.62, 0.74, 0.62)]]
    if lk == "cyber":
        cloth = pal["plastic"] + [tagged((0.95, 0.95, 0.95), "plastic")]
    x = -L / 2 + 0.3
    while x < L / 2 - 0.4:
        w = rng.uniform(0.3, 0.7)
        h = rng.uniform(0.35, 0.8)
        sag = 0.15 * (1 - (2 * (x + w / 2) / L) ** 2)
        top = z + 0.1 - sag
        k.add(box((x, -0.015, top - h), (x + w, 0.015, top)), k.choice(cloth), ao=False)
        x += w + rng.uniform(0.08, 0.35)


def prop_tree(k):
    """A tree for a garden (a fruit or shade tree) or a street (a trimmed crown over a stone
    ring, an iron grate and guard, or a lit concrete ring)."""
    rng, pal, lk = k.rng, k.pal, look(k)
    street = k.form == "street"
    bark = (0.40, 0.31, 0.24)
    leaf = k.choice(LEAF)
    trunk = rng.uniform(1.7, 2.3) if street else rng.uniform(1.1, 1.6)
    r = rng.uniform(1.3, 1.7) if street else rng.uniform(1.5, 2.0)
    lean = rng.uniform(-0.15, 0.15)
    k.add(cyl((0, 0, 0), (lean, 0, trunk + r * 0.4), 0.17, 0.11, 7), bark)
    for e in (-1, 1):
        k.add(cyl((lean * 0.7, 0, trunk * 0.8), (lean + e * r * 0.4, rng.uniform(-0.2, 0.2), trunk + r * 0.5), 0.07, 0.04, 5), bark)
    crown(k, (lean, 0, trunk + r * 0.85), r, leaf, lobes=rng.choice([3, 4, 5]))
    if not street and rng.random() < 0.5:
        fruit = k.choice([(0.85, 0.16, 0.12), (0.92, 0.62, 0.12), (0.6, 0.15, 0.4)])
        for i in range(9):
            a = rng.uniform(0, math.tau)
            c = (lean + math.cos(a) * r * 0.85, math.sin(a) * r * 0.85, trunk + r * rng.uniform(0.5, 1.1))
            k.add(sphere(c, 0.09, 0), fruit, ao=False)
    if not street:
        return
    if lk == "cyber":
        k.add(cyl((0, 0, 0), (0, 0, 0.45), 0.85, 0.85, 12), k.choice(pal["concrete"]))
        k.add(cyl((0, 0, 0.45), (0, 0, 0.48), 0.86, 0.86, 12), None, glow="cyan")
        k.add(cyl((0, 0, 0.4), (0, 0, 0.47), 0.7, 0.7, 12), (0.22, 0.18, 0.14), ao=False)
    elif lk == "steam":
        k.add(box((-0.6, -0.6, 0), (0.6, 0.6, 0.04)), lambda co, n: mul(pal["iron"], 0.7 if int((co.x + 2) / 0.12) % 2 else 1.0), ao=False)
        for i in range(8):
            a = i / 8 * math.tau
            k.add(cyl((math.cos(a) * 0.35, math.sin(a) * 0.35, 0), (math.cos(a) * 0.4, math.sin(a) * 0.4, 1.4), 0.015, 0.015, 4), pal["iron"], ao=False, vary=0.0)
        k.add(cyl((0, 0, 1.3), (0, 0, 1.36), 0.42, 0.42, 8), pal["iron"], ao=False)
    else:
        k.add(cyl((0, 0, 0), (0, 0, 0.3), 0.75, 0.8, 8), pal["stone"])
        k.add(cyl((0, 0, 0.25), (0, 0, 0.31), 0.62, 0.62, 8), (0.30, 0.22, 0.15), ao=False)


def prop_kerb(k):
    """Four metres of kerb along a street's edge (X), the road on the front (-Y) side: dressed
    stones (fantasy), granite with a drain grate (steampunk), painted concrete with lit studs
    (cyberpunk)."""
    rng, pal, lk = k.rng, k.pal, look(k)
    L, w, h = 4.0, 0.3, 0.14
    stone = k.choice(pal["concrete"]) if lk == "cyber" else pal["stone"]
    n = 4 if lk == "cyber" else 6
    for i in range(n):
        x0 = -L / 2 + i * L / n
        k.add(box((x0 + 0.01, -w / 2, 0), (x0 + L / n - 0.01, w / 2, h)), mul(stone, rng.uniform(0.92, 1.06)), ao=False)
    if lk == "cyber":
        k.add(box((-L / 2, -w / 2 - 0.005, h - 0.04), (L / 2, w / 2 + 0.005, h + 0.005)), hazard((0.9, 0.75, 0.1), (0.1, 0.1, 0.1), 0.4), ao=False)
        for x in (-1.0, 1.0):
            k.add(box((x - 0.05, -w / 2 - 0.01, 0.04), (x + 0.05, -w / 2, 0.09)), None, glow="amber")
    elif lk == "steam":
        # A darker granite top course.
        k.add(box((-L / 2, -w / 2 - 0.005, h - 0.03), (L / 2, w / 2 + 0.005, h + 0.005)), pal["stone_dark"], ao=False)


def prop_stairs(k):
    """A flight of steps rising 3 m over 5 m from its front (-Y, at the floor) to its back,
    between cheek walls with a parapet or railing; its sides stand on the lower terrace and
    cut into the upper one."""
    rng, pal, lk = k.rng, k.pal, look(k)
    T, R, W, cw = 3.0, 5.0, 2.4, 0.3
    n = 17
    if lk == "cyber":
        stone, tread = k.choice(pal["concrete"]), mul(k.choice(pal["concrete"]), 1.15)
    elif lk == "steam":
        stone, tread = pal["stone_dark"], pal["stone"]
    else:
        stone, tread = pal["stone"], mul(pal["stone"], 1.1)
    for i in range(n):
        y0 = -R / 2 + i * R / n
        z1 = (i + 1) * T / n
        k.add(box((-W / 2, y0, max(0.0, z1 - T / n - 0.25)), (W / 2, y0 + R / n + 0.02, z1)), tread if i % 2 else mul(tread, 0.94), ao=False, vary=0.0)
    # Cheek walls: the slope plus a parapet, square at the top.
    par = 0.9 if lk == "fantasy" else 0.12
    for e in (-1, 1):
        x0, x1 = (W / 2, W / 2 + cw) if e > 0 else (-W / 2 - cw, -W / 2)
        prof = [(-R / 2, 0.0), (R / 2, 0.0), (R / 2 + 0.01, T + par), (R / 2 - 0.2, T + par), (-R / 2 + 0.2, par + 0.3), (-R / 2, par + 0.3)]
        k.add(prism(prof, x0, x1, lambda a, s, z: Vector((a, s, z))), stone)
        if lk == "fantasy":
            k.add(prism([(-R / 2, par + 0.3), (-R / 2 + 0.2, par + 0.3), (R / 2 - 0.2, T + par), (R / 2 + 0.01, T + par), (R / 2 + 0.01, T + par + 0.08), (-R / 2, par + 0.38)], x0 - 0.04, x1 + 0.04, lambda a, s, z: Vector((a, s, z))), mul(stone, 1.12))
        else:
            # A railing on posts along the slope.
            rail = pal["iron"] if lk == "steam" else pal["metal"]
            xm = (x0 + x1) / 2
            for j in range(5):
                y = -R / 2 + 0.3 + j * (R - 0.6) / 4
                z = 0.3 + par + (y + R / 2 - 0.2) / (R - 0.4) * (T - 0.3)
                k.add(box((xm - 0.025, y - 0.025, z), (xm + 0.025, y + 0.025, z + 0.95)), rail, ao=False)
            a = Vector((xm, -R / 2 + 0.3, 0.3 + par + 0.95 + 0.1 * (T - 0.3) / (R - 0.4)))
            b = Vector((xm, R / 2 - 0.3, 0.3 + par + 0.95 + (R - 0.5) / (R - 0.4) * (T - 0.3)))
            k.add(cyl(a, b, 0.035, 0.035, 6), pal["brass"] if lk == "steam" else rail, ao=False)
            if lk == "cyber":
                k.add(cyl(a - Vector((0, 0, 0.08)), b - Vector((0, 0, 0.08)), 0.02, 0.02, 4), None, glow="cyan")


def retaining_footing(k, L, D, t, lk):
    """What joins a retaining wall to the ground. The drop it holds is the terrain's: a bank of
    1 m tiles whose lower slope rose through the wall's face, and whose steps showed between
    pieces and past their ends. So the wall stands on a sloped footing (a stone or cast toe
    from a third of its height down to the lower ground, 0.5 m out) and turns back into the
    bank at both ends (returns 0.35 m into the upper ground). Its length is unchanged, so pieces
    still run on from one another."""
    pal = k.pal
    c = k.choice(pal["concrete"]) if lk == "cyber" else pal["stone_dark"] if lk == "steam" else mul(pal["stone"], 0.92)
    h, out = min(1.1, D * 0.36), 0.5
    toe = [(-t / 2 + 0.05, -0.5), (-t / 2 + 0.05, h), (-t / 2 - 0.06, h), (-t / 2 - out, 0.05), (-t / 2 - out, -0.5)]
    k.add(prism(toe, -L / 2, L / 2, lambda a, s, z: Vector((a, s, z))), c)
    top = D + (0.15 if lk == "steam" else 0.75 if lk == "fantasy" else 0.9)
    for e in (-1, 1):
        x0, x1 = (L / 2 - 0.28, L / 2) if e > 0 else (-L / 2, -L / 2 + 0.28)
        k.add(box((x0, t / 2 - 0.05, -0.5), (x1, t / 2 + 0.35, top - 0.25)), c)


def prop_retaining_wall(k):
    """Four metres of retaining wall along X holding the ground 1.5 m (low) or 3 m (high) above
    its foot, the face to the front (-Y): battered stone with a coping (fantasy), brick with
    pilasters and an iron railing (steampunk), concrete with a hazard band and a lit strip
    (cyberpunk). The upper ground meets its back at the drop's height."""
    rng, pal, lk = k.rng, k.pal, look(k)
    L, D, t = 4.0, (1.5 if k.form == "low" else 3.0), 0.7
    retaining_footing(k, L, D, t, lk)
    if lk == "cyber":
        c = k.choice(pal["concrete"])
        k.add(box((-L / 2, -t / 2, 0), (L / 2, t / 2, D + 0.9)), grime(c))
        k.add(box((-L / 2, -t / 2 - 0.01, D * 0.12), (L / 2, -t / 2, D * 0.12 + 0.2)), hazard((0.9, 0.75, 0.1), (0.1, 0.1, 0.1), 0.45), ao=False)
        k.add(box((-L / 2, -t / 2 - 0.02, D + 0.7), (L / 2, -t / 2, D + 0.75)), None, glow=k.choice(["cyan", "pink"]))
        for x in (-L / 2 + 0.6, L / 2 - 0.6):
            k.add(box((x - 0.06, -t / 2 - 0.03, D * 0.4), (x + 0.06, -t / 2, D * 0.4 + 0.12)), (0.2, 0.2, 0.22), ao=False)
        return
    if lk == "steam":
        brick = k.choice(pal["brick"])
        k.add(box((-L / 2, -t / 2, 0), (L / 2, t / 2, D + 0.15)), brick_fn(brick, k.rng))
        for x in (-L / 2 + 0.2, L / 2 - 0.2):
            k.add(box((x - 0.22, -t / 2 - 0.12, 0), (x + 0.22, -t / 2, D + 0.15)), mul(brick, 0.9))
        k.add(box((-L / 2, -t / 2 - 0.1, D + 0.15), (L / 2, t / 2, D + 0.3)), pal["stone"])
        for i in range(9):
            x = -L / 2 + 0.2 + i * (L - 0.4) / 8
            k.add(box((x - 0.015, -0.015, D + 0.3), (x + 0.015, 0.015, D + 1.25)), pal["iron"], ao=False, vary=0.0)
        k.add(box((-L / 2, -0.025, D + 1.15), (L / 2, 0.025, D + 1.22)), pal["iron"], ao=False)
        return
    stone = pal["stone"]
    # Battered: the face leans back a little; courses as colour bands.
    prof = [(-t / 2, 0.0), (t / 2, 0.0), (t / 2, D + 0.75), (-t / 2 + 0.18, D + 0.75)]
    k.add(prism(prof, -L / 2, L / 2, lambda a, s, z: Vector((a, s, z))), lambda co, n: mul(stone, (0.86 if int(co.z / 0.32) % 2 else 1.0) * (0.92 + 0.08 * math.sin(co.x * 3.1 + co.z * 7))))
    k.add(box((-L / 2, -t / 2 + 0.1, D + 0.75), (L / 2, t / 2, D + 0.88)), mul(stone, 1.15))
    # A weep hole or two.
    for x in (-L / 4, L / 4):
        k.add(box((x - 0.08, -t / 2 - 0.02, D * 0.25), (x + 0.08, -t / 2 + 0.05, D * 0.25 + 0.12)), (0.18, 0.17, 0.16), ao=False)


KINDS = {
    ("fantasy", "tower"): fantasy_tower,
    ("fantasy", "wall"): fantasy_wall,
    ("fantasy", "market_stall"): market_stall,
    ("fantasy", "lamp"): fantasy_lamp,
    ("steampunk", "factory"): steampunk_factory,
    ("steampunk", "chimney"): steampunk_chimney,
    ("steampunk", "pipe"): steampunk_pipe,
    ("steampunk", "crate"): steampunk_crate,
    ("steampunk", "lamp"): steampunk_lamp,
    ("giant", "tower"): fantasy_tower,
    ("giant", "lamp"): fantasy_lamp,
    ("small", "tower"): small_tower,
    ("fantasy", "well"): well,
    ("giant", "well"): well,
    ("small", "well"): well,
    ("cyberpunk", "neon_sign"): cyber_neon_sign,
    ("cyberpunk", "billboard"): cyber_billboard,
    ("cyberpunk", "cable"): cyber_cable,
    ("cyberpunk", "kiosk"): cyber_kiosk,
    ("cyberpunk", "food_stall"): cyber_food_stall,
    ("cyberpunk", "walkway"): cyber_walkway,
    ("cyberpunk", "lamp"): cyber_lamp,
    ("cyberpunk", "crate"): cyber_crate,
    ("cyberpunk", "wall"): cyber_wall,
}

# Kinds that come in forms: the generator reads k.form (and k.corner, the side of a corner
# building's second street front: 1 = +X, -1 = -X) and builds to its own size.
FORM_KINDS = {
    ("fantasy", "house"): (fantasy_house, ["cottage", "house", "longhouse", "lhouse", "corner"]),
    ("fantasy", "townhouse"): (fantasy_townhouse, ["narrow", "wide", "corner"]),
    ("fantasy", "inn"): (fantasy_inn, ["inn"]),
    ("fantasy", "hall"): (fantasy_hall, ["guildhall"]),
    ("fantasy", "chapel"): (fantasy_chapel, ["chapel"]),
    ("fantasy", "workshop"): (fantasy_workshop, ["smithy", "workshop"]),
    ("fantasy", "barn"): (fantasy_barn, ["barn", "shed"]),
    ("giant", "house"): (fantasy_house, ["cottage", "house", "longhouse", "lhouse"]),
    ("giant", "hall"): (giant_hall, ["longhall"]),
    ("small", "house"): (small_house, ["burrow", "mound", "mushroom", "stump"]),
    ("small", "hall"): (mushroom_hall, ["mushroom_hall"]),
    ("steampunk", "house"): (steampunk_house, ["narrow", "wide", "corner"]),
    ("steampunk", "inn"): (steampunk_house, ["pub"]),
    ("steampunk", "hall"): (steampunk_hall, ["exchange"]),
    ("steampunk", "clocktower"): (steampunk_clocktower, ["clocktower"]),
    ("steampunk", "mast"): (steampunk_mast, ["mooring_mast"]),
    ("steampunk", "works"): (steampunk_works, ["foundry", "gearworks"]),
    ("steampunk", "arcade"): (steampunk_arcade, ["arcade"]),
    ("cyberpunk", "block"): (cyber_block, ["narrow", "wide", "corner"]),
    ("cyberpunk", "tower"): (cyber_tower, ["slender"]),
    ("cyberpunk", "landmark"): (cyber_tower, ["landmark"]),
    ("cyberpunk", "market"): (cyber_market, ["food_court"]),
    ("cyberpunk", "workshop"): (cyber_workshop, ["garage", "fab"]),
}

# Street props: kind -> (generator, forms), and which styles have which. Steampunk and
# cyberpunk crates (and the cyberpunk neon signs, cables, kiosks...) are fixed kinds above.
PROPS = {
    "barrel": (prop_barrel, ["single", "group"]),
    "crate": (prop_crate, ["stack"]),
    "cart": (prop_cart, ["handcart", "wagon"]),
    "bench": (prop_bench, ["bench"]),
    "fountain": (prop_fountain, ["fountain"]),
    "market_cross": (prop_market_cross, ["cross"]),
    "fence": (prop_fence, [f"f{0.5 + 0.25 * i:g}" for i in range(15)]),
    "gate": (prop_gate, ["gate"]),
    "planter": (prop_planter, ["planter"]),
    "flower_box": (prop_flower_box, ["box"]),
    "sign": (prop_sign, ["shop", "post"]),
    "banner": (prop_banner, ["banner"]),
    "washing_line": (prop_washing_line, ["posts", "span3", "span45", "span6"]),
    "tree": (prop_tree, ["street", "garden"]),
    "kerb": (prop_kerb, ["k4"]),
    "stairs": (prop_stairs, ["flight"]),
    "retaining_wall": (prop_retaining_wall, ["low", "high"]),
}
# Fence sections per length: one, so every section of a style matches its neighbours.
FENCE_VARIANTS = 1

PROP_STYLES = {
    "fantasy": list(PROPS),
    "steampunk": [p for p in PROPS if p != "crate"],
    "cyberpunk": [p for p in PROPS if p not in ("crate", "sign")],
    "giant": ["barrel", "crate", "cart", "bench", "fence", "gate", "planter", "sign", "tree", "washing_line"],
    "small": ["barrel", "crate", "bench", "fence", "gate", "planter", "flower_box", "tree"],
}
for _style, _kinds in PROP_STYLES.items():
    for _kind in _kinds:
        FORM_KINDS[(_style, _kind)] = PROPS[_kind]

# Who lives there: generators work in metres for a 1.75 m person, and the result is scaled to
# the inhabitants, so a giant's door is 5/1.75 times a person's and a small folk's 0.6/1.75.
STYLE_FOLK = {"fantasy": "human", "steampunk": "human", "cyberpunk": "human", "giant": "giant", "small": "small"}


def up(x):
    """Round up to the centimetre, so a lot sized by the table always holds the model."""
    return math.ceil(x * 100 - 1e-6) / 100


def write_table(path, root):
    """Gather every set's footprint sidecar under the envs root into the planner's table."""
    import glob
    models = []
    for side in sorted(glob.glob(os.path.join(root, "*", "*", "gen-*.json"))):
        with open(side) as f:
            d = json.load(f)
        rel = os.path.relpath(os.path.dirname(side), root)
        for m in d["models"]:
            models.append(dict(style=d["style"], kind=d["kind"], form=m["form"], file=f"{rel}/{m['file']}", width_m=m["width_m"],
                               depth_m=m["depth_m"], height_m=m["height_m"], foundation_m=m["foundation_m"], corner=m["corner"], tris=m["tris"]))
    models.sort(key=lambda m: (m["style"], m["kind"], m["file"]))
    kinds = {}
    for m in models:
        e = kinds.setdefault((m["style"], m["kind"]), dict(style=m["style"], kind=m["kind"], width_m=0.0, depth_m=0.0, height_m=0.0, foundation_m=0.0))
        for key in ("width_m", "depth_m", "height_m", "foundation_m"):
            e[key] = max(e[key], m[key])
    note = ("Written by living/tools/blender/buildings.py --table (gen_buildings.sh). models: every generated model, its file "
            "under envs/, form, footprint (width along the front, depth front to back, overhangs, steps and yards included), "
            "height above the floor, foundation depth below it, corner (the side of a corner building's second street front "
            "in the model's frame: 1 = +X, -1 = -X) and triangles. kinds: the envelope of every model of a kind.")
    with open(path, "w") as f:
        f.write("{\n " + json.dumps("note") + ": " + json.dumps(note) + ",\n \"kinds\": [\n")
        f.write(",\n".join("  " + json.dumps(kinds[key]) for key in sorted(kinds)))
        f.write("\n ],\n \"models\": [\n")
        f.write(",\n".join("  " + json.dumps(m) for m in models))
        f.write("\n ]\n}\n")
    print(f"TABLE {path} {len(kinds)} kinds, {len(models)} models")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", choices=sorted(PALETTES))
    ap.add_argument("--kind")
    ap.add_argument("--form", help="only this form of a kind with forms")
    ap.add_argument("--table", help="write the footprint table (JSON) the settlement planner reads from --envs, and exit")
    ap.add_argument("--envs", default="living/game/assets/envs", help="root of the generated sets, for --table")
    ap.add_argument("--count", type=int, default=8, help="models per form")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out")
    ap.add_argument("--profile", action="store_true", help="print triangles, and untagged lit triangles, per generator function")
    a = ap.parse_args(argv)
    global PROFILE, UNTAGGED
    if a.table:
        write_table(a.table, a.envs)
        return
    if not (a.style and a.kind and a.out):
        sys.exit("--style, --kind and --out are required unless --table is given")
    key = (a.style, a.kind)
    if key not in KINDS and key not in FORM_KINDS:
        sys.exit(f"unknown kind {a.kind} for style {a.style}; known: {sorted(KINDS) + sorted(FORM_KINDS)}")
    os.makedirs(a.out, exist_ok=True)
    folk = FOLK[STYLE_FOLK[a.style]] / FOLK["human"]
    if key in FORM_KINDS:
        gen, forms = FORM_KINDS[key]
        forms = [f for f in forms if a.form in (None, f)]
        count = min(a.count, FENCE_VARIANTS) if a.kind == "fence" else a.count
        jobs = [(form, i, random.Random(f"{a.seed}-{a.style}-{a.kind}-{form}-{i}")) for form in forms for i in range(count)]
    else:
        H = HEIGHTS[key]
        jobs = [("std", i, random.Random(a.seed * 1000 + i)) for i in range(a.count)]
    records = []
    for form, i, rng in jobs:
        reset()
        PROFILE = {} if a.profile else None
        UNTAGGED = {} if a.profile else None
        k = Kit(rng, PALETTES[a.style], ao=1.2, pr=random.Random(f"detail-{a.seed}-{a.style}-{a.kind}-{form}-{i}"))
        k.form = form
        k.style = a.style
        k.corner = (1 if i % 2 == 0 else -1) if "corner" in form else 0
        if key in FORM_KINDS:
            gen(k)
            foundation(k, FOUNDATION.get(a.kind, FOUNDATION_DEFAULT))
            obj, s = k.b.finish(f"{a.kind}_{a.style}_{form}_{i:02d}", scale=folk)
            name = f"gen-{a.kind}-{a.style}-{form}-{i:02d}.glb"
        else:
            # Design height, in metres for a 1.75 m person.
            KINDS[key](k, H / folk)
            foundation(k, FOUNDATION.get(a.kind, FOUNDATION_DEFAULT))
            obj, s = k.b.finish(f"{a.kind}_{a.style}_{i:02d}", height=H)
            name = f"gen-{a.kind}-{a.style}-{i:02d}.glb"
        tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
        path = os.path.join(a.out, name)
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_vertex_color="ACTIVE", export_normals=True, export_yup=True, use_selection=False)
        # Lots are centred on the origin: the footprint is twice the farthest reach from it.
        vs = obj.data.vertices
        fw, fd = 2 * max(abs(v.co.x) for v in vs), 2 * max(abs(v.co.y) for v in vs)
        top, below = max(v.co.z for v in vs), max(0.0, -min(v.co.z for v in vs))
        print(f"GEN {path} form={form} tris={tris} foot={fw:.2f}x{fd:.2f} h={top:.2f} below={below:.2f}")
        records.append(dict(file=name, form=form, width_m=up(fw), depth_m=up(fd), height_m=round(top, 2), foundation_m=round(below, 2), corner=k.corner, tris=tris))
        if PROFILE:
            print("  " + " ".join(f"{n}={t}" for n, t in sorted(PROFILE.items(), key=lambda x: -x[1])))
        if UNTAGGED:
            print("  untagged " + " ".join(f"{n}={t}" for n, t in sorted(UNTAGGED.items(), key=lambda x: -x[1])))
    if a.form is None:
        with open(os.path.join(a.out, f"gen-{a.kind}-{a.style}.json"), "w") as f:
            json.dump(dict(style=a.style, kind=a.kind, models=records), f, indent=1)


main()
