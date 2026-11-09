"""Clothing pieces for the VRoid characters, fitted and skinned to their J_Bip skeleton.

Run headless (gen_outfits.sh runs every base):
    blender -b -P living/tools/blender/outfits.py -- --base living/game/assets/lookdev/vroid-Vivi.glb \
        --out living/game/assets/lookdev/outfits [--pieces cropped_jacket,visor] [--blend fit.blend]

Writes `<out>/<style>/<piece>-<base>.glb` per piece and merges each piece's record into
`<out>/outfits.json` (style, piece, base, file, slot, layer, bones, triangles, materials, which
base material groups it covers, and a rest-pose check).

Pieces:
- cyberpunk: cropped_jacket (glowing edges), high_collar, visor, glow_trim (bands on arms and
  legs), cargo_straps (belt, pouches, a bandolier and, where the thighs are bare, a thigh rig);
- steampunk: long_coat (lapels, brass buttons, split tails), waistcoat, top_hat, bowler,
  brass_goggles, gloves, boots.

How a piece is fitted (in the base's rest T-pose, Blender Z-up, the character facing +Y, its
left at -X):
- Shells (jacket, coat body, waistcoat, boots, bandolier, glow bands) are cut from a hull of the
  body: the body mesh voxel-remeshed into one outer surface (so the skin under the clothes and
  the clothes' own layers merge), each hull vertex tagged with its J_Bip bone by the body's
  weights, the region kept by bone and height, pushed out along its normals by the piece's
  offset, smoothed, decimated, then given thickness (solidify, whose rim faces are the trim).
- Gloves are the hand's own skin, inflated: a hull would merge the fingers.
- Collars, visors, goggles, hats and belts are rings fitted to the measured cross-section of
  the neck, head and hair (`ring_fit`), clearing the hair.
- Coat tails are two panels (left and right, open at the front with a back vent) flaring from
  the hips to below the knees, everywhere outside the body, dress or skirt below them.

How a piece is skinned: every vertex takes the J_Bip weights of the nearest point on the body's
surface (barycentric over its triangle). Weights on spring bones (hair and skirt joints) are
moved to their nearest J_Bip ancestor, at most four influences remain, normalised. Exceptions:
head pieces are on J_Bip_C_Head only; collars blend UpperChest to Neck; coat tails blend from
the hips (top) to half the same side's upper leg (hem), so the panels follow the legs' stride.

Colour is per vertex (COLOR_0) on a white "Outfit" material, as for the environment kits; glowing
parts use "GlowCyan", "GlowPink" or "GlowAmber" (emission) materials.

Output GLBs hold the base's whole armature (its rest pose, unchanged) and one skinned mesh. The
client should not spawn that armature: it binds the mesh to the character's own bone entities by
name (and, where a recipe's proportions put helper joints in a bone's place, to those helpers).
"""

import argparse
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))

NEON = {"cyan": (0.04, 0.80, 1.0), "pink": (1.0, 0.08, 0.50), "amber": (1.0, 0.50, 0.04)}

# Per base: the colours its outfits are made in (bases differ so the line-up reads).
LOOKS = {
    "vroid-Vivi": dict(neon="cyan", jacket=(0.10, 0.09, 0.14), panel=(0.30, 0.26, 0.40), coat=(0.34, 0.20, 0.11),
                       waistcoat=(0.44, 0.11, 0.10), hat=(0.07, 0.07, 0.08), band=(0.46, 0.12, 0.11), leather=(0.30, 0.18, 0.10)),
    "vroid-Sendagaya_Shino": dict(neon="pink", jacket=(0.07, 0.11, 0.12), panel=(0.22, 0.34, 0.36), coat=(0.12, 0.22, 0.16),
                                  waistcoat=(0.62, 0.46, 0.16), hat=(0.24, 0.16, 0.10), band=(0.08, 0.08, 0.08), leather=(0.12, 0.10, 0.09)),
}
DEFAULT_LOOK = LOOKS["vroid-Vivi"]
BRASS, STEEL, DARK = (0.80, 0.62, 0.30), (0.55, 0.56, 0.60), (0.06, 0.06, 0.07)

TORSO = {"J_Bip_C_Hips", "J_Bip_C_Spine", "J_Bip_C_Chest", "J_Bip_C_UpperChest", "J_Bip_L_Shoulder", "J_Bip_R_Shoulder"}
ARMS = {f"J_Bip_{s}_{b}" for s in "LR" for b in ("UpperArm", "LowerArm")}
FEET = {f"J_Bip_{s}_{b}" for s in "LR" for b in ("Foot", "ToeBase", "ToeBase_end")}


def is_hand(name):
    return name.startswith("J_Bip_") and any(f in name for f in ("Hand", "Index", "Middle", "Ring", "Little", "Thumb"))


# ---------------------------------------------------------------------------------------------
# The base


class Base:
    """The imported character: armature, body, face and hair, its J_Bip-merged weights, the
    body's surface for weight lookups and a hull for shells."""

    def __init__(self, path):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=path, bone_heuristic="BLENDER", guess_original_bind_pose=False, disable_bone_shape=True)
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.look = LOOKS.get(self.name, DEFAULT_LOOK)
        arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
        if len(arms) != 1:
            raise SystemExit(f"expected one armature, found {len(arms)}")
        self.arm = arms[0]
        self.body = bpy.data.objects["Body"]
        self.face = bpy.data.objects.get("Face")
        self.hair = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("Hair")]
        bones = self.arm.data.bones
        self.head = {b.name: b.head_local.copy() for b in bones}
        self.tail = {b.name: b.tail_local.copy() for b in bones}

        def jbip(name):
            b = bones.get(name)
            while b is not None and not b.name.startswith("J_Bip"):
                b = b.parent
            return b.name if b is not None else "J_Bip_C_Hips"
        self.jbip = {b.name: jbip(b.name) for b in bones}
        # The body's weights, moved onto J_Bip bones.
        me = self.body.data
        names = {g.index: g.name for g in self.body.vertex_groups}
        self.weights = []
        for v in me.vertices:
            w = {}
            for g in v.groups:
                if g.weight <= 0:
                    continue
                n = self.jbip.get(names[g.group], "J_Bip_C_Hips")
                w[n] = w.get(n, 0.0) + g.weight
            s = sum(w.values()) or 1.0
            self.weights.append({k: x / s for k, x in w.items()})
        self.verts = [v.co.copy() for v in me.vertices]
        self.tris = []
        self.tri_mat = []
        for p in me.polygons:
            vs = list(p.vertices)
            for i in range(1, len(vs) - 1):
                self.tris.append((vs[0], vs[i], vs[i + 1]))
                self.tri_mat.append(me.materials[p.material_index].name if me.materials[p.material_index] else "")
        self.bvh = BVHTree.FromPolygons(self.verts, self.tris)
        # Each side's half of the body (with the middle), so a vertex off the centre line takes
        # its weights from its own side: the nearest point can be the other foot or knee.
        self.side = {}
        for s, keep in (("L", lambda x: x < 0.003), ("R", lambda x: x > -0.003)):
            ids = [i for i, t in enumerate(self.tris) if all(keep(self.verts[k].x) for k in t)]
            self.side[s] = (BVHTree.FromPolygons(self.verts, [self.tris[i] for i in ids]), ids)
        self.mat_names = [m.name for m in me.materials if m]
        self._hull = None

    def weights_at(self, co):
        """The body's J_Bip weights at the surface point nearest `co` (on its own side)."""
        if abs(co.x) > 0.004:
            tree, ids = self.side["L" if co.x < 0 else "R"]
            loc, _n, ti, _d = tree.find_nearest(co)
            ti = ids[ti]
        else:
            loc, _n, ti, _d = self.bvh.find_nearest(co)
        a, b, c = (self.verts[i] for i in self.tris[ti])
        u, v, w = barycentric(loc, a, b, c)
        out = {}
        for k, idx in zip((u, v, w), self.tris[ti]):
            for n, x in self.weights[idx].items():
                out[n] = out.get(n, 0.0) + k * x
        return out

    def bone_at(self, co):
        w = self.weights_at(co)
        return max(w, key=w.get) if w else "J_Bip_C_Hips"

    def hull(self, voxel=0.008):
        """The body as one closed outer surface (bmesh), each vertex tagged with its J_Bip bone."""
        if self._hull is None:
            ob = self.body.copy()
            ob.data = self.body.data.copy()
            ob.modifiers.clear()
            ob.parent = None
            bpy.context.collection.objects.link(ob)
            # Single-sided sheets (a dress's skirt, sleeves) have no volume, and a voxel remesh
            # drops them: give everything a little thickness first.
            sol = ob.modifiers.new("solid", "SOLIDIFY")
            sol.thickness, sol.offset = 0.012, 0.0
            m = ob.modifiers.new("remesh", "REMESH")
            m.mode = "VOXEL"
            m.voxel_size = voxel
            apply_modifiers(ob)
            bm = bmesh.new()
            bm.from_mesh(ob.data)
            bpy.data.objects.remove(ob)
            bm.normal_update()
            tag = bm.verts.layers.int.new("bone")
            self.bone_names = sorted(set(self.jbip.values()))
            idx = {n: i for i, n in enumerate(self.bone_names)}
            for v in bm.verts:
                v[tag] = idx[self.bone_at(v.co)]
            self._hull = bm
        return self._hull

    def hull_bone(self, bm, v):
        return self.bone_names[v[bm.verts.layers.int["bone"]]]

    def z(self, bone, t=0.0):
        """Height along a bone: t=0 its head, 1 its child's head (or its tail)."""
        return lerp(self.head[bone].z, self.tail[bone].z, t)

    def points(self, objs, za, zb):
        """Vertices of objects (rest pose) between heights za and zb."""
        out = []
        for o in objs:
            if o is None:
                continue
            for v in o.data.vertices:
                if za <= v.co.z <= zb:
                    out.append(v.co.copy())
        return out


def barycentric(p, a, b, c):
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11 = v0.dot(v0), v0.dot(v1), v1.dot(v1)
    d20, d21 = v2.dot(v0), v2.dot(v1)
    den = d00 * d11 - d01 * d01
    if abs(den) < 1e-12:
        return 1.0, 0.0, 0.0
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1.0 - v - w
    # Clamp onto the triangle and renormalise.
    u, v, w = max(u, 0.0), max(v, 0.0), max(w, 0.0)
    s = u + v + w or 1.0
    return u / s, v / s, w / s


def lerp(a, b, t):
    return a + (b - a) * t


def apply_modifiers(ob):
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.view_layer.objects:
        o.select_set(o == ob)
    for m in list(ob.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)


def ring_fit(pts, cx, cy, n=24, margin=0.01, smooth=2, floor=0.0):
    """Radii round the axis (cx, cy) that clear every point: per sector the farthest point, plus
    a margin, widened to its neighbours a little so the ring has no notches."""
    r = [floor] * n
    for p in pts:
        a = math.atan2(p.y - cy, p.x - cx) % math.tau
        i = int(a / math.tau * n) % n
        d = math.hypot(p.x - cx, p.y - cy)
        r[i] = max(r[i], d)
    # Empty sectors take the larger neighbour.
    for _ in range(n):
        for i in range(n):
            if r[i] <= floor:
                r[i] = max(r[i - 1], r[(i + 1) % n])
    for _ in range(smooth):
        r = [max(r[i], 0.5 * (r[i - 1] + r[(i + 1) % n])) for i in range(n)]
    return [x + margin for x in r]


def ring_radius(radii, a):
    n = len(radii)
    f = (a % math.tau) / math.tau * n - 0.5
    i = math.floor(f)
    t = f - i
    return lerp(radii[i % n], radii[(i + 1) % n], t)


# ---------------------------------------------------------------------------------------------
# Building pieces


class Piece:
    """A garment in progress: a bmesh with per-corner colours and materials, and how it skins."""

    def __init__(self, base, name, style):
        self.base, self.name, self.style = base, name, style
        self.bm = bmesh.new()
        self.col = self.bm.loops.layers.color.new("Color")
        self.mats = []
        self.rigid = None  # {bone: weight} for every vertex (head pieces), or None
        self.custom = None  # vertex index -> weights, for parts weighted by hand
        self.covers = []
        self.slot, self.layer = "", 0

    def mat(self, name):
        if name not in self.mats:
            self.mats.append(name)
        return self.mats.index(name)

    def add(self, part, color, glow=None, custom=None, style=None):
        """Merge a bmesh in; `color` is a colour or fn(co, normal) -> colour, `glow` a NEON name;
        or `style(face) -> (color, glow)` per face (a solid whose rim is the trim)."""
        bmesh.ops.recalc_face_normals(part, faces=part.faces)
        spec = {f: (style(f) if style else (color, glow)) for f in part.faces}
        mapping = {}
        for v in part.verts:
            nv = self.bm.verts.new(v.co)
            mapping[v] = nv
        self.bm.verts.index_update()
        for f in part.faces:
            try:
                nf = self.bm.faces.new([mapping[v] for v in f.verts])
            except ValueError:
                continue
            fc, fg = spec[f]
            nf.material_index = self.mat("Glow" + fg.title() if fg else "Outfit")
            if fg:
                fc = tuple(lerp(c, 1.0, 0.3) for c in NEON[fg])
            nf.normal_update()
            for loop in nf.loops:
                c = fc(loop.vert.co, nf.normal) if callable(fc) else fc
                loop[self.col] = (*c, 1.0)
        if custom is not None:
            self.custom = self.custom or {}
            for v, nv in mapping.items():
                self.custom[nv] = custom(v.co)
        part.free()


def shell(base, keep, offset, faces=1400, smooth=3, cut=None, split=False):
    """A region of the hull: vertices where keep(v, bone) holds, minus where cut(co) holds,
    smoothed, decimated to about `faces` faces and pushed out by `offset` (a bmesh). `split`
    drops every face that straddles the centre line: where the hull joins close legs, a bridge
    between the two sides would stretch into bars as soon as the legs part."""
    hull = base.hull()
    bm = hull.copy()
    bm.verts.ensure_lookup_table()
    tag = bm.verts.layers.int["bone"]
    names = base.bone_names
    kill = [v for v in bm.verts if not keep(v.co, names[v[tag]]) or (cut is not None and cut(v.co))]
    bmesh.ops.delete(bm, geom=kill, context="VERTS")
    # Keep the larger pieces only (voxel crumbs).
    islands = connected(bm)
    if islands:
        big = max(len(i) for i in islands)
        drop = [f for i in islands if len(i) < 0.08 * big for f in i]
        bmesh.ops.delete(bm, geom=drop, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    ob = to_object(bm, "shell")
    m = ob.modifiers.new("smooth", "SMOOTH")
    m.factor, m.iterations = 0.5, smooth
    if len(ob.data.polygons) > faces:
        d = ob.modifiers.new("decimate", "DECIMATE")
        d.ratio = faces / len(ob.data.polygons)
    apply_modifiers(ob)
    out = bmesh.new()
    out.from_mesh(ob.data)
    bpy.data.objects.remove(ob)
    if split:
        cross = [f for f in out.faces if min(v.co.x for v in f.verts) < -0.001 and max(v.co.x for v in f.verts) > 0.001]
        bmesh.ops.delete(out, geom=cross, context="FACES")
        bmesh.ops.delete(out, geom=[v for v in out.verts if not v.link_faces], context="VERTS")
    out.normal_update()
    for v in out.verts:
        v.co += v.normal * offset
    return out


def connected(bm):
    seen, out = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        stack, isl = [f], []
        seen.add(f)
        while stack:
            g = stack.pop()
            isl.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        out.append(isl)
    return out


def to_object(bm, name):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob


def thicken(bm, t, rim_color=None, rim_glow=None, body_color=None):
    """Give a sheet thickness (outward), its rim faces the trim: a colour or a neon."""
    ob = to_object(bm, "thicken")
    me = ob.data
    for p in me.polygons:
        p.material_index = 0
    ob.data.materials.append(bpy.data.materials.new("a"))
    ob.data.materials.append(bpy.data.materials.new("b"))
    s = ob.modifiers.new("solid", "SOLIDIFY")
    s.thickness, s.offset, s.use_rim, s.material_offset_rim = t, 1.0, True, 1
    # Even thickness spikes at the near-degenerate faces decimation leaves; plain offset doesn't.
    s.use_even_offset = False
    apply_modifiers(ob)
    out = bmesh.new()
    out.from_mesh(ob.data)
    bpy.data.objects.remove(ob)
    rim = {f for f in out.faces if f.material_index == 1}
    body = [f for f in out.faces if f.material_index == 0]
    return out, rim, body


def split_faces(bm, faces):
    """A new bmesh of just these faces (to add with their own colour or material)."""
    out = bmesh.new()
    vmap = {}
    for f in faces:
        for v in f.verts:
            if v not in vmap:
                vmap[v] = out.verts.new(v.co)
        try:
            out.faces.new([vmap[v] for v in f.verts])
        except ValueError:
            pass
    return out


def add_thick(pc, bm, t, color, rim=None, glow_rim=None, glow=None, custom=None):
    """Thicken a sheet and add it as one solid: body in `color` (or glowing `glow`), rim in
    `rim` or glowing `glow_rim`."""
    out, rim_f, _body = thicken(bm, t)
    pc.add(out, None, custom=custom, style=lambda f: ((rim or color), glow_rim) if f in rim_f else (color, glow))


def band(radii_fn, z0, z1, cx, cy, n=24, a0=0.0, a1=math.tau, rows=2, flare=0.0, closed=None):
    """A ring band (sheet) from z0 to z1 round (cx, cy), radius radii_fn(angle, t) at height
    fraction t; an arc from a0 to a1 if it is not the whole ring."""
    closed = closed if closed is not None else abs(a1 - a0 - math.tau) < 1e-6
    bm = bmesh.new()
    cols = n if closed else n + 1
    grid = []
    for r in range(rows + 1):
        t = r / rows
        z = lerp(z0, z1, t)
        row = []
        for i in range(cols):
            a = a0 + (a1 - a0) * i / n
            rad = radii_fn(a, t) + flare * t
            row.append(bm.verts.new((cx + math.cos(a) * rad, cy + math.sin(a) * rad, z)))
        grid.append(row)
    for r in range(rows):
        for i in range(n):
            j = (i + 1) % cols
            bm.faces.new([grid[r][i], grid[r][j], grid[r + 1][j], grid[r + 1][i]])
    return bm


def disc(c, axis, r, depth, sides=16):
    """A short cylinder (closed) centred at c along axis."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=sides, radius1=r, radius2=r, depth=depth)
    rot = Vector(axis).to_track_quat("Z", "Y").to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=Matrix.Translation(Vector(c)) @ rot, verts=bm.verts)
    return bm


def cube(c, size, rot=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    m = Matrix.Diagonal((*size, 1.0))
    if rot is not None:
        m = rot.to_4x4() @ m
    bmesh.ops.transform(bm, matrix=Matrix.Translation(Vector(c)) @ m, verts=bm.verts)
    return bm


def sphere(c, r, sub=1):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r)
    bmesh.ops.translate(bm, vec=Vector(c), verts=bm.verts)
    return bm


# ---------------------------------------------------------------------------------------------
# Measurements


def torso_axis(b):
    return b.head["J_Bip_C_Spine"].y


def head_band(b, za, zb, margin, n=32):
    """Radii round the head axis that clear face and hair between za and zb."""
    c = b.head["J_Bip_C_Head"]
    pts = b.points([b.face, b.body] + b.hair, za, zb)
    pts = [p for p in pts if math.hypot(p.x - c.x, p.y - c.y) < 0.16]
    return c.x, c.y, ring_fit(pts, c.x, c.y, n=n, margin=margin)


def hips_band(b, za, zb, margin, n=32):
    hull = b.hull()
    cx, cy = 0.0, b.head["J_Bip_C_Hips"].y
    pts = [v.co for v in hull.verts if za <= v.co.z <= zb]
    return cx, cy, ring_fit(pts, cx, cy, n=n, margin=margin)


def leg_is_bare(b, side, z):
    """Whether the hull round the upper leg at height z is a leg (not a dress or skirt)."""
    hull = b.hull()
    c = b.head[f"J_Bip_{side}_UpperLeg"]
    sign = 1 if c.x > 0 else -1
    near = [v.co for v in hull.verts if abs(v.co.z - z) < 0.01 and v.co.x * sign > 0]
    if not near:
        return False
    return max(math.hypot(p.x - c.x, p.y - c.y) for p in near) < 0.11


# ---------------------------------------------------------------------------------------------
# Cyberpunk


def cropped_jacket(b):
    pc = Piece(b, "cropped_jacket", "cyberpunk")
    pc.slot, pc.layer, pc.covers = "torso_outer", 3, ["Tops"]
    L = b.look
    zc = b.z("J_Bip_C_Chest", 0.15)
    zn = b.head["J_Bip_C_Neck"].z + 0.005
    hand_x = abs(b.head["J_Bip_L_Hand"].x)
    cy = torso_axis(b)

    def keep(co, bone):
        if bone in TORSO:
            return zc <= co.z <= zn
        if bone in ARMS or bone in ("J_Bip_L_Shoulder", "J_Bip_R_Shoulder"):
            return abs(co.x) < hand_x - 0.03 and co.z >= zc
        return False
    cut = lambda co: co.y > cy and abs(co.x) < 0.03 and co.z < zn - 0.02
    sh = shell(b, keep, 0.018, faces=1100, cut=cut)
    sx = abs(b.head["J_Bip_L_UpperArm"].x)

    def color(co, n):
        # Shoulder and upper-sleeve panels in a lighter tone; the rest dark, darker inside.
        c = L["panel"] if (sx - 0.02 < abs(co.x) < sx + 0.09 and co.z > b.head["J_Bip_L_UpperArm"].z - 0.01) else L["jacket"]
        return c
    add_thick(pc, sh, 0.008, color, glow_rim=L["neon"])
    # A glowing seam down each sleeve's top.
    for s in (-1, 1):
        x0, x1 = s * (sx + 0.04), s * (hand_x - 0.05)
        top = b.head["J_Bip_L_UpperArm"].z
        pts = [p for p in [v.co for v in b.hull().verts] if abs(p.y - b.head["J_Bip_L_UpperArm"].y) < 0.012 and min(x0, x1) < p.x < max(x0, x1) and p.z > top - 0.02]
        if pts:
            zt = max(p.z for p in pts) + 0.019
            pc.add(cube(((x0 + x1) / 2, b.head["J_Bip_L_UpperArm"].y, zt), (abs(x1 - x0), 0.012, 0.006)), None, glow=L["neon"])
    return pc


def high_collar(b):
    pc = Piece(b, "high_collar", "cyberpunk")
    pc.slot, pc.layer, pc.covers = "neck", 4, []
    L = b.look
    neck = b.head["J_Bip_C_Neck"]
    z0, z1 = neck.z - 0.015, b.z("J_Bip_C_Neck", 0.95) + 0.01
    pts = b.points([b.body], z0, z1 - 0.01)
    pts = [p for p in pts if abs(p.x) < 0.09]
    radii = ring_fit(pts, neck.x, neck.y, n=24, margin=0.012)
    # Open a little at the front, under the chin.
    front = math.pi / 2
    sh = band(lambda a, t: ring_radius(radii, a) + 0.012 * t, z0, z1, neck.x, neck.y, n=22, a0=front + 0.35, a1=front + math.tau - 0.35, rows=3)
    add_thick(pc, sh, 0.008, L["jacket"], glow_rim=L["neon"])
    pc.custom = {}
    for v in pc.bm.verts:
        t = min(1.0, max(0.0, (v.co.z - z0) / (z1 - z0)))
        pc.custom[v] = {"J_Bip_C_UpperChest": 1.0 - t, "J_Bip_C_Neck": t}
    return pc


def visor(b):
    pc = Piece(b, "visor", "cyberpunk")
    pc.slot, pc.layer, pc.covers = "eyes", 5, []
    L = b.look
    eyes = [v.co for v in b.face.data.vertices] if b.face else []
    ez = [p.z for p in eyes if p.y > 0.03 and abs(p.x) < 0.07]
    zc = (min(ez) + max(ez)) / 2 if ez else b.z("J_Bip_C_Head", 0.35)
    # The eye band of the face mesh: from the eye materials' extent.
    me = b.face.data
    eye_z = [me.vertices[i].co.z for p in me.polygons if "EyeWhite" in me.materials[p.material_index].name for i in p.vertices]
    if eye_z:
        zc = (min(eye_z) + max(eye_z)) / 2
    h = 0.05
    cx, cy, radii = head_band(b, zc - h / 2 - 0.01, zc + h / 2 + 0.01, 0.012)
    front = math.pi / 2
    span = 1.9
    lens = band(lambda a, t: ring_radius(radii, a) + 0.004 * math.sin(t * math.pi), zc - h / 2, zc + h / 2, cx, cy, n=20, a0=front - span / 2, a1=front + span / 2, rows=2)
    add_thick(pc, lens, 0.006, None, rim=DARK, glow=L["neon"])
    # A frame over and under the lens, and pods at the temples.
    for z, hh in ((zc + h / 2 + 0.004, 0.009), (zc - h / 2 - 0.004, 0.007)):
        fr = band(lambda a, t: ring_radius(radii, a) + 0.004, z - hh / 2, z + hh / 2, cx, cy, n=20, a0=front - span / 2 - 0.05, a1=front + span / 2 + 0.05, rows=1)
        add_thick(pc, fr, 0.012, (0.16, 0.16, 0.19))
    for s in (-1, 1):
        a = front + s * (span / 2 + 0.06)
        r = ring_radius(radii, a) + 0.008
        c = Vector((cx + math.cos(a) * r, cy + math.sin(a) * r, zc))
        pc.add(disc(c, Vector((math.cos(a), math.sin(a), 0)), 0.022, 0.018, 12), (0.14, 0.14, 0.17))
        pc.add(disc(c + Vector((math.cos(a), math.sin(a), 0)) * 0.01, Vector((math.cos(a), math.sin(a), 0)), 0.008, 0.006, 8), None, glow="amber")
    # A thin strap round the back of the head.
    st = band(lambda a, t: ring_radius(radii, a) + 0.002, zc - 0.008, zc + 0.008, cx, cy, n=16, a0=front + span / 2 + 0.06, a1=front + math.tau - span / 2 - 0.06, rows=1)
    add_thick(pc, st, 0.004, (0.10, 0.10, 0.12))
    pc.rigid = {"J_Bip_C_Head": 1.0}
    return pc


def limb_band(b, a, d, half, offset):
    """A band of the hull round a limb: hull vertices within `half` of the plane through a
    with normal d."""
    def keep(co, bone):
        # Only this limb's side: the hull can join close knees.
        return abs((co - a).dot(d)) < half and (co - a).length < 0.16 and co.x * a.x > 0 and abs(co.x) > 0.01
    return shell(b, keep, offset, faces=220, smooth=2, split=True)


def glow_trim(b):
    pc = Piece(b, "glow_trim", "cyberpunk")
    pc.slot, pc.layer, pc.covers = "trim", 6, []
    L = b.look
    for s in "LR":
        ua, la, ul, ll = (b.head[f"J_Bip_{s}_{n}"] for n in ("UpperArm", "LowerArm", "UpperLeg", "LowerLeg"))
        hand, foot = b.head[f"J_Bip_{s}_Hand"], b.head[f"J_Bip_{s}_Foot"]
        for p, q, t, off in ((ua, la, 0.45, 0.024), (la, hand, 0.55, 0.022), (ul, ll, 0.75, 0.012), (ll, foot, 0.45, 0.01)):
            a = p.lerp(q, t)
            d = (q - p).normalized()
            if q is ll and not leg_is_bare(b, s, a.z):
                continue
            sh = limb_band(b, a, d, 0.008, off)
            if sh.faces:
                add_thick(pc, sh, 0.004, None, glow=L["neon"], glow_rim=L["neon"])
    return pc


def cargo_straps(b):
    pc = Piece(b, "cargo_straps", "cyberpunk")
    pc.slot, pc.layer, pc.covers = "belt", 7, []
    L = b.look
    strap, pouch, metal = (0.30, 0.29, 0.20), (0.42, 0.36, 0.24), (0.58, 0.59, 0.62)
    hips = b.head["J_Bip_C_Hips"]
    zb = hips.z + 0.01
    cx, cy, radii = hips_band(b, zb - 0.03, zb + 0.03, 0.008)
    belt = band(lambda a, t: ring_radius(radii, a), zb - 0.018, zb + 0.018, cx, cy, n=32, rows=1)
    add_thick(pc, belt, 0.007, strap, rim=mul(strap, 0.7))
    front = math.pi / 2
    r = ring_radius(radii, front) + 0.008
    pc.add(cube((cx, cy + r, zb), (0.05, 0.012, 0.04)), metal)
    # Pouches round the belt.
    for a in (front + 1.0, front + 2.0, front - 1.0, front - 2.2, front + math.pi):
        r = ring_radius(radii, a) + 0.02
        c = Vector((cx + math.cos(a) * r, cy + math.sin(a) * r, zb - 0.022))
        rot = Matrix.Rotation(a - math.pi / 2, 3, "Z")
        pc.add(cube(c, (0.065, 0.035, 0.07), rot), pouch)
        pc.add(cube(c + Vector((0, 0, 0.032)) + rot @ Vector((0, 0.004, 0)), (0.07, 0.04, 0.012), rot), mul(pouch, 0.8))
        pc.add(cube(c + rot @ Vector((0, 0.019, 0.012)), (0.014, 0.004, 0.014), rot), metal)
    # A bandolier: the hull where a tilted plane crosses the torso, shoulder to hip.
    top = b.head["J_Bip_R_Shoulder"]
    n = Vector((1.0, 0.0, 1.0)).normalized()
    c0 = Vector((0.0, torso_axis(b), b.z("J_Bip_C_Chest", 0.6)))
    zl = b.head["J_Bip_C_Neck"].z - 0.01

    def keep(co, bone):
        return bone in TORSO and abs((co - c0).dot(n)) < 0.022 and hips.z < co.z < zl
    sh = shell(b, keep, 0.012, faces=320, smooth=2)
    add_thick(pc, sh, 0.006, strap, rim=mul(strap, 0.7))
    # Two magazine pouches on the chest strap, front.
    for t in (0.3, 0.55):
        z = lerp(zl, hips.z, t)
        x = -(z - c0.z)
        hits = [v.co for v in b.hull().verts if abs(v.co.z - z) < 0.01 and abs(v.co.x - x) < 0.015 and v.co.y > cy]
        if hits:
            y = max(p.y for p in hits) + 0.028
            pc.add(cube((x, y, z), (0.04, 0.025, 0.055)), pouch)
            pc.add(cube((x, y + 0.013, z + 0.015), (0.03, 0.004, 0.012)), None, glow=L["neon"])
    # A thigh rig on each side where the thigh is bare: two straps and a pouch.
    for s in "LR":
        ul, ll = b.head[f"J_Bip_{s}_UpperLeg"], b.head[f"J_Bip_{s}_LowerLeg"]
        for t in (0.55, 0.75):
            a = ul.lerp(ll, t)
            if not leg_is_bare(b, s, a.z):
                continue
            sh = limb_band(b, a, (ll - ul).normalized(), 0.011, 0.006)
            if sh.faces:
                add_thick(pc, sh, 0.005, strap, rim=mul(strap, 0.7))
        a = ul.lerp(ll, 0.65)
        if leg_is_bare(b, s, a.z):
            side = -1 if s == "L" else 1
            hits = [v.co for v in b.hull().verts if abs(v.co.z - a.z) < 0.01 and (v.co.x - a.x) * side > 0 and abs(v.co.y - a.y) < 0.02]
            if hits:
                x = max(abs(p.x) for p in hits) * side + side * 0.02
                pc.add(cube((x, a.y, a.z), (0.03, 0.07, 0.09)), pouch)
    return pc


# ---------------------------------------------------------------------------------------------
# Steampunk


def mul(c, k):
    return tuple(min(1.0, x * k) for x in c)


def coat_tails(b, pc, z_top, z_hem, color, offset):
    """Two flared panels from z_top to z_hem, outside everything below the hips, open at the
    front with a vent at the back; weighted hips (top) to half the same side's thigh (hem)."""
    hull = b.hull()
    cx, cy = 0.0, b.head["J_Bip_C_Hips"].y
    n = 36
    rows = 6
    # Per sector, the farthest the body reaches at or above each height (so the coat never
    # narrows going down), plus a flare.
    zs = [lerp(z_top, z_hem, r / rows) for r in range(rows + 1)]
    reach = []
    for r, z in enumerate(zs):
        pts = [v.co for v in hull.verts if z - 0.02 <= v.co.z <= z_top + 0.02]
        rad = ring_fit(pts, cx, cy, n=n, margin=offset)
        if reach:
            rad = [max(a, c) for a, c in zip(rad, reach[-1])]
        reach.append([x + 0.035 * (r / rows) ** 1.4 for x in rad])
    front, back = math.pi / 2, -math.pi / 2
    gap_f, gap_b = 0.16, 0.05
    hips = b.head["J_Bip_C_Hips"]
    for side, (a0, a1) in (("R", (back + gap_b, front - gap_f)), ("L", (front + gap_f, back + math.tau - gap_b))):
        bm = bmesh.new()
        cols = 18
        grid = []
        for r, z in enumerate(zs):
            row = []
            for i in range(cols + 1):
                a = lerp(a0, a1, i / cols)
                # The back vent opens only on the lower half.
                if r < rows / 2 and (i == 0 if side == "R" else i == cols):
                    a += (-gap_b if side == "R" else gap_b) * 0.95
                rad = ring_radius(reach[r], a)
                row.append(bm.verts.new((cx + math.cos(a) * rad, cy + math.sin(a) * rad, z)))
            grid.append(row)
        for r in range(rows):
            for i in range(cols):
                bm.faces.new([grid[r][i], grid[r][i + 1], grid[r + 1][i + 1], grid[r + 1][i]])
        leg = f"J_Bip_{side}_UpperLeg"

        def w(co, leg=leg):
            t = min(1.0, max(0.0, (z_top - co.z) / (z_top - z_hem)))
            k = 0.5 * t ** 1.2
            return {"J_Bip_C_Hips": 1.0 - k, leg: k}
        add_thick(pc, bm, 0.007, color, rim=mul(color, 0.6), custom=w)


def long_coat(b):
    pc = Piece(b, "long_coat", "steampunk")
    pc.slot, pc.layer, pc.covers = "torso_outer", 3, ["Tops"]
    L = b.look
    hips = b.head["J_Bip_C_Hips"]
    zt = hips.z + 0.03
    zn = b.head["J_Bip_C_Neck"].z + 0.005
    hand_x = abs(b.head["J_Bip_L_Hand"].x)
    cy = torso_axis(b)
    zchest = b.z("J_Bip_C_Chest", 0.3)

    def keep(co, bone):
        if bone in TORSO:
            return zt - 0.04 <= co.z <= zn
        if bone in ARMS:
            return abs(co.x) < hand_x - 0.015 and co.z > zt
        return False

    def cut(co):
        # Open front, a deeper V above the chest for the lapels and the waistcoat.
        if co.y <= cy or co.z > zn - 0.015:
            return False
        w = 0.025 + max(0.0, (co.z - zchest)) * 0.6
        return abs(co.x) < w
    sh = shell(b, keep, 0.026, faces=1300, cut=cut)
    lap = lambda co: co.y > cy and co.z > zchest - 0.02 and abs(co.x) < 0.11
    col = lambda co, n: mul(L["coat"], 0.75) if lap(co) else L["coat"]
    # Lapels: the front edge above the chest stands proud.
    for v in sh.verts:
        if lap(v.co):
            v.co += v.normal * 0.005
    add_thick(pc, sh, 0.008, col, rim=mul(L["coat"], 0.6))
    # A standing collar.
    neck = b.head["J_Bip_C_Neck"]
    pts = [p for p in b.points([b.body], neck.z - 0.03, neck.z + 0.02) if abs(p.x) < 0.11]
    radii = ring_fit(pts, neck.x, neck.y, n=24, margin=0.022)
    front = math.pi / 2
    cb = band(lambda a, t: ring_radius(radii, a) + 0.02 * t, neck.z - 0.02, neck.z + 0.045, neck.x, neck.y, n=20, a0=front + 0.55, a1=front + math.tau - 0.55, rows=2)
    add_thick(pc, cb, 0.007, mul(L["coat"], 0.8))
    # Brass buttons down both front edges.
    for side in (-1, 1):
        for t in (0.15, 0.35, 0.55):
            z = lerp(zt + 0.02, zchest, t / 0.55 * 0.95)
            x = side * 0.045
            hits = [v.co for v in b.hull().verts if abs(v.co.z - z) < 0.008 and abs(v.co.x - x) < 0.012 and v.co.y > cy]
            if hits:
                y = max(p.y for p in hits) + 0.036
                pc.add(disc((x, y, z), Y, 0.009, 0.006, 10), BRASS)
    # Cuffs at the sleeve ends.
    for s in (-1, 1):
        x = s * (hand_x - 0.03)
        pts = [v.co for v in b.hull().verts if abs(v.co.x - x) < 0.01]
        if pts:
            cyz = (sum(p.y for p in pts) / len(pts), sum(p.z for p in pts) / len(pts))
            r = max(math.hypot(p.y - cyz[0], p.z - cyz[1]) for p in pts) + 0.036
            pc.add(disc((x - s * 0.02, cyz[0], cyz[1]), X, r, 0.04, 14), mul(L["coat"], 0.7))
    # The tails.
    knee = b.head["J_Bip_L_LowerLeg"].z
    coat_tails(b, pc, zt + 0.02, knee - 0.06, L["coat"], 0.03)
    return pc


def waistcoat(b):
    pc = Piece(b, "waistcoat", "steampunk")
    pc.slot, pc.layer, pc.covers = "torso_mid", 2, []
    L = b.look
    hips = b.head["J_Bip_C_Hips"]
    z0 = hips.z + 0.035
    z1 = b.z("J_Bip_C_UpperChest", 0.7)
    cy = torso_axis(b)
    zv = b.z("J_Bip_C_Chest", 0.55)
    sx = abs(b.head["J_Bip_L_UpperArm"].x)

    def keep(co, bone):
        return bone in TORSO and z0 <= co.z <= z1 and abs(co.x) < sx - 0.012

    def cut(co):
        if co.y <= cy:
            return False
        return co.z > zv and abs(co.x) < 0.01 + (co.z - zv) * 0.75 or abs(co.x) < 0.006
    sh = shell(b, keep, 0.012, faces=900, cut=cut)
    c = L["waistcoat"]
    stripe = lambda co, n: mul(c, 0.86) if int(math.floor((co.x + 1.0) / 0.012)) % 2 else c
    col = lambda co, n: mul(c, 0.55) if co.y < cy - 0.02 else stripe(co, n)
    add_thick(pc, sh, 0.006, col, rim=mul(c, 0.6))
    for i in range(4):
        z = lerp(z0 + 0.02, zv, i / 3.4)
        hits = [v.co for v in b.hull().verts if abs(v.co.z - z) < 0.008 and abs(v.co.x - 0.015) < 0.012 and v.co.y > cy]
        if hits:
            y = max(p.y for p in hits) + 0.02
            pc.add(sphere((0.016, y, z), 0.0065, 1), BRASS)
    # A watch chain across the front.
    zc = lerp(z0, zv, 0.35)
    for i in range(8):
        x = -0.06 + i * 0.016
        z = zc - 0.012 * math.sin(i / 7 * math.pi)
        hits = [v.co for v in b.hull().verts if abs(v.co.z - z) < 0.008 and abs(v.co.x - x) < 0.01 and v.co.y > cy]
        if hits:
            pc.add(sphere((x, max(p.y for p in hits) + 0.02, z), 0.0035, 0), BRASS)
    return pc


def hat_fit(b, depth):
    """Where a hat sits: its base height and the radii that clear the hair above it."""
    head = b.head["J_Bip_C_Head"]
    top = max(v.co.z for o in b.hair for v in o.data.vertices)
    zb = top - depth
    pts = b.points(b.hair + [b.face], zb - 0.01, top + 0.01)
    radii = ring_fit(pts, head.x, head.y, n=28, margin=0.006)
    return head.x, head.y, zb, top, radii


def top_hat(b):
    pc = Piece(b, "top_hat", "steampunk")
    pc.slot, pc.layer, pc.covers = "head", 8, []
    L = b.look
    cx, cy, zb, top, radii = hat_fit(b, 0.085)
    rmean = sum(radii) / len(radii)
    crown = band(lambda a, t: ring_radius(radii, a) * (1.0 + 0.06 * t), zb, top + 0.11, cx, cy, n=28, rows=3)
    add_thick(pc, crown, 0.005, L["hat"])
    lid = bmesh.new()
    ring = [lid.verts.new((cx + math.cos(i / 28 * math.tau) * ring_radius(radii, i / 28 * math.tau) * 1.06, cy + math.sin(i / 28 * math.tau) * ring_radius(radii, i / 28 * math.tau) * 1.06, top + 0.11)) for i in range(28)]
    lid.faces.new(ring)
    add_thick(pc, lid, 0.006, mul(L["hat"], 1.3))
    add_thick(pc, band(lambda a, t: ring_radius(radii, a) * 1.06 + 0.004, zb + 0.012, zb + 0.04, cx, cy, n=28, rows=1), 0.003, L["band"])
    brim = band(lambda a, t: ring_radius(radii, a) + 0.004 + 0.05 * t, zb + 0.004, zb + 0.004 + 0.012 * (1.0), cx, cy, n=28, rows=1)
    for v in brim.verts:
        # Curl the brim's sides up.
        a = math.atan2(v.co.y - cy, v.co.x - cx)
        d = math.hypot(v.co.x - cx, v.co.y - cy) - rmean
        v.co.z = zb + 0.004 + max(0.0, d) * 0.5 * abs(math.cos(a))
    add_thick(pc, brim, 0.006, L["hat"])
    pc.rigid = {"J_Bip_C_Head": 1.0}
    return pc


def bowler(b):
    pc = Piece(b, "bowler", "steampunk")
    pc.slot, pc.layer, pc.covers = "head", 8, []
    L = b.look
    cx, cy, zb, top, radii = hat_fit(b, 0.07)
    h = (top - zb) + 0.05
    rows = 6
    dome = bmesh.new()
    grid = []
    for r in range(rows + 1):
        t = r / rows
        k = math.cos(t * math.pi / 2) ** 0.7 if t > 0.2 else 1.0
        z = zb + h * math.sin(t * math.pi / 2)
        grid.append([dome.verts.new((cx + math.cos(i / 28 * math.tau) * ring_radius(radii, i / 28 * math.tau) * max(k, 0.05),
                                     cy + math.sin(i / 28 * math.tau) * ring_radius(radii, i / 28 * math.tau) * max(k, 0.05), z)) for i in range(28)])
    for r in range(rows):
        for i in range(28):
            j = (i + 1) % 28
            dome.faces.new([grid[r][i], grid[r][j], grid[r + 1][j], grid[r + 1][i]])
    dome.faces.new(grid[-1])
    add_thick(pc, dome, 0.005, L["hat"])
    add_thick(pc, band(lambda a, t: ring_radius(radii, a) * 1.01 + 0.006, zb + 0.006, zb + 0.026, cx, cy, n=28, rows=1), 0.003, L["band"])
    brim = band(lambda a, t: ring_radius(radii, a) + 0.003 + 0.032 * t, zb, zb + 0.008, cx, cy, n=28, rows=1)
    for v in brim.verts:
        d = math.hypot(v.co.x - cx, v.co.y - cy) - min(radii)
        v.co.z += max(0.0, d) * 0.35
    add_thick(pc, brim, 0.005, L["hat"])
    pc.rigid = {"J_Bip_C_Head": 1.0}
    return pc


def brass_goggles(b):
    pc = Piece(b, "brass_goggles", "steampunk")
    pc.slot, pc.layer, pc.covers = "forehead", 9, []
    L = b.look
    me = b.face.data
    brow = [me.vertices[i].co.z for p in me.polygons if "FaceBrow" in me.materials[p.material_index].name for i in p.vertices]
    zg = (max(brow) if brow else b.z("J_Bip_C_Head", 0.55)) + 0.028
    cx, cy, radii = head_band(b, zg - 0.02, zg + 0.02, 0.006)
    strap = band(lambda a, t: ring_radius(radii, a), zg - 0.011, zg + 0.011, cx, cy, n=28, rows=1)
    add_thick(pc, strap, 0.004, L["leather"])
    front = math.pi / 2
    for s in (-1, 1):
        a = front + s * 0.36
        r = ring_radius(radii, a)
        d = Vector((math.cos(a), math.sin(a), 0))
        c = Vector((cx, cy, zg)) + d * r
        pc.add(disc(c + d * 0.012, d, 0.026, 0.026, 14), BRASS)
        pc.add(disc(c + d * 0.027, d, 0.029, 0.006, 14), mul(BRASS, 1.12))
        pc.add(disc(c + d * 0.029, d, 0.02, 0.004, 14), (0.30, 0.50, 0.48))
        for k in range(4):
            ang = k / 4 * math.tau + 0.4
            u = d.cross(Z).normalized()
            pc.add(sphere(c + d * 0.03 + (u * math.cos(ang) + Z * math.sin(ang)) * 0.024, 0.003, 0), mul(BRASS, 0.8))
    a0, a1 = front - 0.36, front + 0.36
    mid = Vector((cx, cy, zg)) + Vector((0, 1, 0)) * (ring_radius(radii, front) + 0.012)
    pc.add(cube(mid, (0.03, 0.01, 0.008)), BRASS)
    pc.rigid = {"J_Bip_C_Head": 1.0}
    return pc


def gloves(b):
    pc = Piece(b, "gloves", "steampunk")
    pc.slot, pc.layer, pc.covers = "hands", 2, []
    L = b.look
    me = b.body.data
    hand_x = abs(b.head["J_Bip_L_Hand"].x)
    cuff_x = hand_x - 0.075
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    keepv = set()
    for v in bm.verts:
        w = b.weights[v.index]
        hand = sum(x for n, x in w.items() if is_hand(n))
        if abs(v.co.x) > cuff_x and (hand > 0.3 or any(n.endswith("LowerArm") for n in w)):
            keepv.add(v)
    skin = [f for f in bm.faces if all(v in keepv for v in f.verts) and "SKIN" in (me.materials[f.material_index].name if me.materials[f.material_index] else "")]
    part = split_faces(bm, skin)
    bm.free()
    part.normal_update()
    for v in part.verts:
        # Inflated, more at the cuff, which flares.
        k = max(0.0, 1.0 - (abs(v.co.x) - cuff_x) / 0.05)
        v.co += v.normal * (0.0035 + 0.01 * k ** 2)
    c = L["leather"]
    add_thick(pc, part, 0.002, c, rim=mul(c, 0.7))
    return pc


def boots(b):
    pc = Piece(b, "boots", "steampunk")
    pc.slot, pc.layer, pc.covers = "feet", 2, ["Shoes"]
    L = b.look
    ztop = {s: lerp(b.head[f"J_Bip_{s}_Foot"].z, b.head[f"J_Bip_{s}_LowerLeg"].z, 0.55) for s in "LR"}

    def keep(co, bone):
        side = "L" if co.x < 0 else "R"
        # Split at the middle: the hull may join close shoes.
        return (bone in FEET or bone.endswith("LowerLeg")) and co.z <= ztop[side] and abs(co.x) > 0.012
    sh = shell(b, keep, 0.008, faces=1200, smooth=2, split=True)
    c = L["leather"]
    sole = lambda co, n: (0.10, 0.08, 0.07) if co.z < 0.022 else c
    add_thick(pc, sh, 0.006, sole, rim=mul(c, 0.7))
    # Cuffs and a buckle strap at each top.
    for s in "LR":
        ll = b.head[f"J_Bip_{s}_LowerLeg"]
        z = ztop[s] - 0.012
        # This leg's side only, clear of where the hull joins close calves.
        own = lambda co: (co.x < 0) == (s == "L") and abs(co.x) > 0.015
        pts = [v.co for v in b.hull().verts if abs(v.co.z - z) < 0.012 and own(v.co)]
        if not pts:
            continue
        cxl, cyl = sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts)
        radii = ring_fit(pts, cxl, cyl, n=20, margin=0.019)
        cuff = band(lambda a, t: ring_radius(radii, a) + 0.004 * t, z - 0.02, z + 0.018, cxl, cyl, n=20, rows=1)
        add_thick(pc, cuff, 0.006, mul(c, 0.85))
        zs = lerp(b.head[f"J_Bip_{s}_Foot"].z, z, 0.5)
        pts2 = [v.co for v in b.hull().verts if abs(v.co.z - zs) < 0.01 and own(v.co)]
        if pts2:
            r2 = ring_fit(pts2, cxl, cyl, n=20, margin=0.016)
            add_thick(pc, band(lambda a, t: ring_radius(r2, a), zs - 0.008, zs + 0.008, cxl, cyl, n=20, rows=1), 0.003, (0.08, 0.07, 0.06))
            side = -1 if s == "L" else 1
            a = 0.0 if side > 0 else math.pi
            pc.add(cube((cxl + math.cos(a) * ring_radius(r2, a), cyl, zs), (0.008, 0.022, 0.02)), BRASS)
    return pc


PIECES = {
    "cyberpunk": [cropped_jacket, high_collar, visor, glow_trim, cargo_straps],
    "steampunk": [long_coat, waistcoat, top_hat, bowler, brass_goggles, gloves, boots],
}


# ---------------------------------------------------------------------------------------------
# Skinning and export


def material(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (1, 1, 1, 1)
    bsdf.inputs["Roughness"].default_value = 0.8
    if name.startswith("Glow"):
        c = NEON[name[4:].lower()]
        bsdf.inputs["Emission Color"].default_value = (*c, 1)
        bsdf.inputs["Emission Strength"].default_value = 5.0
    return m


def finish(b, pc, out_dir, report):
    """Skin the piece, make it an object under the armature, export it with the armature and
    check the rest pose survived."""
    bm = pc.bm
    wmap = {}
    for v in bm.verts:
        if pc.rigid:
            w = dict(pc.rigid)
        elif pc.custom and v in pc.custom:
            w = dict(pc.custom[v])
        else:
            w = b.weights_at(v.co)
        # A vertex clearly on one side never follows the other side's limbs (the hull can bridge
        # close feet or knees, and the nearest body point can be the other leg).
        if v.co.x < -0.02:
            w = {n: x for n, x in w.items() if not n.startswith("J_Bip_R_")} or w
        elif v.co.x > 0.02:
            w = {n: x for n, x in w.items() if not n.startswith("J_Bip_L_")} or w
        # At most four influences, normalised.
        top = sorted(w.items(), key=lambda x: -x[1])[:4]
        s = sum(x for _, x in top) or 1.0
        wmap[v] = {n: x / s for n, x in top if x / s > 0.002}

    # No face may join a vertex that follows a left limb to one that follows a right limb: where
    # the hull joins close legs, such a face stretches into a bar as soon as they part.
    def limb(w, side):
        return sum(x for n, x in w.items() if n.startswith(f"J_Bip_{side}_"))
    torn = [f for f in bm.faces if any(limb(wmap[v], "L") > 0.3 for v in f.verts) and any(limb(wmap[v], "R") > 0.3 for v in f.verts)]
    bmesh.ops.delete(bm, geom=torn, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.verts.index_update()
    weights = [wmap[v] for v in bm.verts]
    if torn:
        print(f"SPLIT {pc.name}: {len(torn)} faces joined left and right limbs")
    me = bpy.data.meshes.new(pc.name)
    bm.to_mesh(me)
    for name in pc.mats:
        me.materials.append(material(name))
    if "Color" in me.color_attributes:
        me.color_attributes.active_color = me.color_attributes["Color"]
        me.color_attributes.render_color_index = me.color_attributes.active_color_index
    ob = bpy.data.objects.new(f"{pc.name}", me)
    bpy.context.collection.objects.link(ob)
    me.shade_smooth()
    groups = {}
    for i, w in enumerate(weights):
        for n, x in w.items():
            g = groups.get(n) or ob.vertex_groups.new(name=n)
            groups[n] = g
            g.add([i], x, "REPLACE")
    ob.parent = b.arm
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = b.arm
    # Only the armature and this piece go into the file.
    for o in list(bpy.data.objects):
        if o not in (b.arm, ob):
            bpy.data.objects.remove(o)
    d = os.path.join(out_dir, pc.style)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{pc.name}-{b.name}.glb")
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_yup=True, export_skins=True, export_animations=False,
                              export_vertex_color="ACTIVE", export_normals=True, export_materials="EXPORT", export_def_bones=False,
                              export_leaf_bone=False, export_rest_position_armature=True, use_selection=False)
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    # Fit check: how far any vertex stands off the body's surface (spikes, loose parts).
    reach = max((b.bvh.find_nearest(v.co)[3] for v in me.vertices), default=0.0)
    longest = max((( me.vertices[e.vertices[0]].co - me.vertices[e.vertices[1]].co).length for e in me.edges), default=0.0)
    rec = dict(style=pc.style, piece=pc.name, base=b.name, file=f"{pc.style}/{pc.name}-{b.name}.glb", slot=pc.slot, layer=pc.layer,
               covers=pc.covers, tris=tris, materials=pc.mats, bones=sorted(groups), rest=check_rest(b.src, path), reach_m=round(reach, 3), longest_edge_m=round(longest, 3))
    report.append(rec)
    print(f"OUTFIT {path} tris={tris} bones={len(groups)} reach={reach:.3f} edge={longest:.3f} rest={rec['rest']}")
    ob.parent = None
    bpy.data.objects.remove(ob)


def glb_json(path):
    import struct
    with open(path, "rb") as f:
        data = f.read()
    n = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20 + n])


def check_rest(src, out):
    """Whether every J_Bip node in the piece has the base's rest translation and rotation, and
    the skin's joints are J_Bip bones (so the client can bind to the character's bones)."""
    a, b = glb_json(src), glb_json(out)
    na = {n.get("name"): n for n in a["nodes"]}
    worst = 0.0
    for n in b["nodes"]:
        name = n.get("name", "")
        if not name.startswith("J_Bip"):
            continue
        o = na.get(name)
        if o is None:
            return "missing " + name
        for key, dflt in (("translation", [0, 0, 0]), ("rotation", [0, 0, 0, 1])):
            worst = max(worst, max(abs(x - y) for x, y in zip(n.get(key, dflt), o.get(key, dflt))))
    joints = [b["nodes"][j].get("name", "") for s in b.get("skins", []) for j in s["joints"]]
    foreign = [j for j in joints if j not in na]
    if foreign:
        return f"joints missing from the base {foreign[:3]}"
    return f"ok (max diff {worst:.1e})" if worst < 1e-4 else f"differs by {worst:.1e}"


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pieces", default="")
    a = ap.parse_args(argv)
    want = set(p for p in a.pieces.split(",") if p)
    report = []
    jobs = [(style, fn) for style, fns in PIECES.items() for fn in fns if not want or fn.__name__ in want]
    for style, fn in jobs:
        # A fresh import per piece: finishing one removes everything but the armature.
        b = Base(a.base)
        b.src = a.base
        pc = fn(b)
        finish(b, pc, a.out, report)
    index = os.path.join(a.out, "outfits.json")
    old = []
    if os.path.exists(index):
        with open(index) as f:
            old = json.load(f).get("pieces", [])
    keys = {(r["style"], r["piece"], r["base"]) for r in report}
    pieces = [r for r in old if (r["style"], r["piece"], r["base"]) not in keys] + report
    pieces.sort(key=lambda r: (r["style"], r["piece"], r["base"]))
    note = ("Written by living/tools/blender/outfits.py (gen_outfits.sh). Each piece is a GLB with the base's armature (rest pose "
            "unchanged) and one mesh skinned to its J_Bip bones: bind it to the character's own bone entities by name instead of "
            "spawning that armature. slot: where it is worn; layer: draw/fit order (higher sits outside lower); covers: the base's "
            "material groups it covers (Tops, Bottoms, Shoes; the client may hide them); rest: the check that its J_Bip rest pose "
            "matches the base file's.")
    with open(index, "w") as f:
        json.dump(dict(note=note, pieces=pieces), f, indent=1)
    print(f"INDEX {index} {len(pieces)} pieces")


main()
