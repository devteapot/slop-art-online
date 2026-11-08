"""Stylized nature generator for the game client's test environments.

Run headless:
    blender -b -P living/tools/blender/nature.py -- --kind tree --style meadow --count 12 --out DIR

Kinds: tree, pine, bush, rock, flower, glow_mushroom, crystal. Styles shift colours and shapes
(meadow, forest, spirit). Every asset is real-size in metres, origin at its base, +Z up in
Blender (+Y in glTF), coloured by vertex colours (gradients baked per vertex) on white
materials so the game's toon material does the shading. Glowing parts use a material named
"Glow" with emission.

Anime/Genshin-style foliage: leaf clumps get custom normals pointing out from the canopy's
centre, so each canopy shades as one soft mass instead of noisy facets.
"""

import argparse
import math
import random
import sys

import bmesh
import bpy
from mathutils import Color, Matrix, Vector, noise

STYLES = {
    # leaf colours (dark, light), bark, rock, moss, flower petals, glow colour
    "meadow": dict(leaf=((0.16, 0.36, 0.12), (0.45, 0.70, 0.25)), bark=(0.35, 0.24, 0.15), rock=(0.48, 0.47, 0.45), moss=(0.32, 0.48, 0.2),
                   petals=[(0.95, 0.5, 0.6), (0.98, 0.85, 0.35), (0.65, 0.55, 0.95), (0.98, 0.98, 0.98)], glow=(0.4, 1.0, 0.9)),
    "forest": dict(leaf=((0.08, 0.24, 0.1), (0.3, 0.52, 0.2)), bark=(0.28, 0.2, 0.13), rock=(0.42, 0.42, 0.4), moss=(0.22, 0.4, 0.16),
                   petals=[(0.9, 0.9, 0.95), (0.95, 0.75, 0.3)], glow=(0.4, 1.0, 0.9)),
    "spirit": dict(leaf=((0.05, 0.16, 0.22), (0.2, 0.55, 0.6)), bark=(0.2, 0.17, 0.22), rock=(0.3, 0.32, 0.4), moss=(0.15, 0.35, 0.4),
                   petals=[(0.6, 0.9, 1.0), (0.85, 0.6, 1.0)], glow=(0.35, 1.0, 0.9)),
}


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name, color=(1, 1, 1), emission=None, strength=4.0):
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


def jitter(c, rng, k=0.06):
    return tuple(min(1, max(0, x * (1 + rng.uniform(-k, k)))) for x in c)


class Builder:
    """Accumulates parts into one bmesh with a per-corner colour layer and material slots."""

    def __init__(self):
        self.bm = bmesh.new()
        self.col = self.bm.loops.layers.color.new("Color")
        # Foliage faces carry the index (+1) of the clump centre their normals point out from.
        self.soft_layer = self.bm.faces.layers.int.new("soft")
        self.mats = []
        self.centres = []

    def slot(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def add(self, bm_part, mat, color_fn, soft_centre=None):
        """Merge a part: color_fn(vertex_co, normal) -> rgb."""
        idx = self.slot(mat)
        if soft_centre is not None:
            self.centres.append(soft_centre)
        soft_id = len(self.centres) if soft_centre is not None else 0
        mapping = {}
        for v in bm_part.verts:
            mapping[v] = self.bm.verts.new(v.co)
        new_faces = []
        for f in bm_part.faces:
            try:
                nf = self.bm.faces.new([mapping[v] for v in f.verts])
            except ValueError:
                continue
            nf.material_index = idx
            nf[self.soft_layer] = soft_id
            nf.normal_update()
            for loop in nf.loops:
                loop[self.col] = (*color_fn(loop.vert.co, nf.normal), 1.0)
            new_faces.append(nf)
        bm_part.free()

    def finish(self, name):
        mesh = bpy.data.meshes.new(name)
        soft = [f[self.soft_layer] for f in self.bm.faces]
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
        # Custom normals: foliage points out from its clump centre; everything else flat.
        mesh.shade_flat()
        normals = [None] * len(mesh.loops)
        soft_faces = {i: self.centres[s - 1] for i, s in enumerate(soft) if s > 0}
        for poly in mesh.polygons:
            for li in poly.loop_indices:
                if poly.index in soft_faces:
                    v = mesh.vertices[mesh.loops[li].vertex_index].co
                    n = (v - soft_faces[poly.index]).normalized()
                    normals[li] = n.lerp(poly.normal, 0.15).normalized()
                else:
                    normals[li] = poly.normal.copy()
        mesh.normals_split_custom_set(normals)
        return obj


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


def cylinder(a, b, r0, r1, sides=7):
    bm = bmesh.new()
    axis = b - a
    length = axis.length
    bmesh.ops.create_cone(bm, cap_ends=True, segments=sides, radius1=r0, radius2=r1, depth=length)
    rot = axis.to_track_quat("Z", "Y").to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=Matrix.Translation((a + b) / 2) @ rot, verts=bm.verts)
    return bm


def cone(base, height, r, sides=7, tip=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=sides, radius1=r, radius2=tip, depth=height)
    bmesh.ops.translate(bm, vec=base + Vector((0, 0, height / 2)), verts=bm.verts)
    return bm


def gradient(lo, hi, z0, z1, rng, k=0.05):
    def f(co, n):
        t = min(1, max(0, (co.z - z0) / max(z1 - z0, 1e-3)))
        # Light from above: tops lighter, plus a little per-vertex variation.
        return jitter(lerp(lo, hi, t * 0.85 + 0.15 * max(0, n.z)), rng, k)
    return f


def tree(rng, st):
    b = Builder()
    bark = material("Bark")
    leaves = material("Leaves")
    h = rng.uniform(7, 13)
    lean = Vector((rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), 0))
    top = Vector((0, 0, h * 0.62)) + lean
    b.add(cylinder(Vector((0, 0, -0.3)), top, h * 0.035, h * 0.02), bark, lambda c, n: jitter(st["bark"], rng))
    # Branches up to the clumps, and clumps round a canopy centre.
    canopy = top + Vector((0, 0, h * 0.12))
    clumps = rng.randint(5, 8)
    cr = h * 0.2
    centre_of_canopy = canopy.copy()
    for i in range(clumps):
        a = i / clumps * math.tau + rng.uniform(-0.3, 0.3)
        up = rng.uniform(-0.25, 0.55)
        c = canopy + Vector((math.cos(a) * cr * 0.9, math.sin(a) * cr * 0.9, up * cr))
        b.add(cylinder(top, c, h * 0.015, h * 0.008, 5), bark, lambda co, n: jitter(st["bark"], rng))
        b.add(blob(c, cr * rng.uniform(0.6, 0.85), rng, squash=0.8), leaves, gradient(*st["leaf"], canopy.z - cr, canopy.z + cr * 1.2, rng), centre_of_canopy)
    b.add(blob(canopy + Vector((0, 0, cr * 0.5)), cr * 0.85, rng, squash=0.85), leaves, gradient(*st["leaf"], canopy.z - cr, canopy.z + cr * 1.2, rng), centre_of_canopy)
    return b


def pine(rng, st):
    b = Builder()
    bark = material("Bark")
    leaves = material("Leaves")
    h = rng.uniform(9, 16)
    b.add(cylinder(Vector((0, 0, -0.3)), Vector((0, 0, h * 0.6)), h * 0.03, h * 0.015), bark, lambda c, n: jitter(st["bark"], rng))
    tiers = rng.randint(4, 6)
    for i in range(tiers):
        t = i / tiers
        base = Vector((0, 0, h * (0.18 + 0.68 * t)))
        r = h * 0.2 * (1 - t * 0.75)
        bm = cone(base, h * 0.3 * (1 - t * 0.4), r, sides=9)
        for v in bm.verts:
            if v.co.z < base.z + 0.05:
                v.co.z -= rng.uniform(0.0, 0.25) * r
        b.add(bm, leaves, gradient(*st["leaf"], 0, h, rng), Vector((0, 0, base.z + h * 0.08)))
    return b


def bush(rng, st):
    b = Builder()
    leaves = material("Leaves")
    r = rng.uniform(0.5, 0.9)
    centre = Vector((0, 0, r * 0.7))
    for i in range(rng.randint(3, 5)):
        a = rng.uniform(0, math.tau)
        c = centre + Vector((math.cos(a) * r * 0.55, math.sin(a) * r * 0.55, rng.uniform(-0.2, 0.3) * r))
        b.add(blob(c, r * rng.uniform(0.55, 0.8), rng, squash=0.85), leaves, gradient(*st["leaf"], 0, r * 1.6, rng), centre)
    if rng.random() < 0.5:
        berry = material("Berry", (0.75, 0.12, 0.25))
        for i in range(10):
            a, z = rng.uniform(0, math.tau), rng.uniform(0.4, 1.1) * r
            c = Vector((math.cos(a) * r * 0.95, math.sin(a) * r * 0.95, z))
            b.add(blob(c, 0.05, rng, subdiv=1, roughness=0), berry, lambda co, n: (1, 1, 1))
    return b


def rock(rng, st):
    b = Builder()
    stone = material("Stone")
    r = rng.uniform(0.4, 1.6)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r)
    off = Vector((rng.random() * 50, rng.random() * 50, 0))
    for v in bm.verts:
        v.co *= 1 + noise.noise(v.co * (1.2 / r) + off) * 0.35
        v.co.z = v.co.z * rng.uniform(0.5, 0.8)
    bmesh.ops.translate(bm, vec=Vector((0, 0, r * 0.35)), verts=bm.verts)
    moss = st["moss"]

    def col(co, n):
        # Moss on top faces, stone below.
        return jitter(lerp(st["rock"], moss, max(0, n.z - 0.55) / 0.45), rng, 0.08)

    b.add(bm, stone, col)
    return b


def flower(rng, st):
    b = Builder()
    stem = material("Stem")
    petal = material("Petal")
    h = rng.uniform(0.25, 0.55)
    b.add(cylinder(Vector((0, 0, 0)), Vector((0, 0, h)), 0.012, 0.008, 5), stem, lambda c, n: st["leaf"][1])
    pc = rng.choice(st["petals"])
    for i in range(6):
        a = i / 6 * math.tau
        c = Vector((math.cos(a) * 0.05, math.sin(a) * 0.05, h))
        b.add(blob(c, 0.04, rng, subdiv=1, squash=0.35, roughness=0), petal, lambda co, n: jitter(pc, rng))
    b.add(blob(Vector((0, 0, h + 0.01)), 0.025, rng, subdiv=1, roughness=0), petal, lambda co, n: (0.98, 0.8, 0.2))
    return b


def glow_mushroom(rng, st):
    b = Builder()
    stem = material("Stem")
    glow = material("Glow", (1, 1, 1), emission=st["glow"], strength=3.0)
    h = rng.uniform(0.3, 1.2)
    b.add(cylinder(Vector((0, 0, 0)), Vector((rng.uniform(-0.1, 0.1) * h, 0, h)), h * 0.07, h * 0.05, 7), stem, lambda c, n: (0.9, 0.88, 0.8))
    cap = blob(Vector((0, 0, h)), h * 0.32, rng, subdiv=2, squash=0.45, roughness=0.08)
    bmesh.ops.delete(cap, geom=[v for v in cap.verts if v.co.z < h - h * 0.03], context="VERTS")
    b.add(cap, glow, lambda co, n: (1, 1, 1), Vector((0, 0, h - h * 0.1)))
    return b


def crystal(rng, st):
    b = Builder()
    glow = material("Glow", (1, 1, 1), emission=st["glow"], strength=2.5)
    for i in range(rng.randint(3, 6)):
        h = rng.uniform(0.5, 2.0)
        r = h * 0.14
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=r, radius2=r, depth=h * 0.75)
        bmesh.ops.translate(bm, vec=Vector((0, 0, h * 0.375)), verts=bm.verts)
        tip = bmesh.new()
        bmesh.ops.create_cone(tip, cap_ends=True, segments=6, radius1=r, radius2=0, depth=h * 0.25)
        bmesh.ops.translate(tip, vec=Vector((0, 0, h * 0.875)), verts=tip.verts)
        tilt = Matrix.Rotation(rng.uniform(-0.5, 0.5), 4, "X") @ Matrix.Rotation(rng.uniform(-0.5, 0.5), 4, "Y")
        off = Vector((rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25), 0))
        for part in (bm, tip):
            bmesh.ops.transform(part, matrix=Matrix.Translation(off) @ tilt, verts=part.verts)
            b.add(part, glow, lambda co, n: lerp((0.7, 0.8, 1.0), (1, 1, 1), max(0, n.z)))
    return b


KINDS = dict(tree=tree, pine=pine, bush=bush, rock=rock, flower=flower, glow_mushroom=glow_mushroom, crystal=crystal)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True, choices=sorted(KINDS))
    ap.add_argument("--style", default="meadow", choices=sorted(STYLES))
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    import os
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
