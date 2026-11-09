#!/usr/bin/env python3
"""Anime face and hair shading data for a VRoid GLB: flattened face normals, a face shadow map,
and smoothed hair normals.

    python3 living/tools/face_normals.py IN.glb OUT.glb [--png OUT.face.png] [--flat 0.9] [--hair 0.35]

VRoid faces carry sculpted vertex normals, so a toon step drawn from N·L breaks into facets and
blotches round the nose, mouth and cheeks. Anime games replace them (docs/GAME_BRIEF.md, art
direction: Blue Protocol flattens face normals by hand; HoYoverse games shade faces from a
painted threshold map). This tool does both for the face's skin, the primitives whose material is
VRoid's `…Face_00_SKIN`:

- **Flattened normals:** each face vertex's normal becomes the normal of a smooth ellipsoid
  round the head at that point, blended with the original by `--flat`. The face's morph targets
  (blinks, mouth shapes) stop moving its normals, so expressions don't bring the facets back.
  Other primitives keep the shared normal accessor.
- **Head forward:** TEXCOORD_1 on the face's skin holds the face's rest-pose forward (x, z), the
  same for every vertex. The toon vertex shader turns it by the skinning, so the fragment shader
  knows where this head faces (`toon_vertex.wesl`).
- **Face shadow map** (`--png`, by default beside OUT as `<name>.face.png`): an RG image in the
  face texture's UV space. R is, for light from the face's right (+X in the file), the light's
  horizontal angle from forward (0..1 = 0..180°) up to which the texel stays lit; G the same for
  light from the left. The shader compares the sun's angle with it (`toon.wesl`), so the
  shadow's edge is a clean line that sweeps across the face as the light turns, whatever the
  sun's height, and the face stays fully lit while the light is within about 25° of its front.
  The threshold comes from the ellipsoid's horizontal facing (a nose shadow was tried and read
  as a blot in blind comparisons). Linear data, not colour: load it with sRGB off.
- **Hair normals** (`_HAIR` materials): blended by `--hair` toward a capsule round the head (a
  sphere above the head's centre, an upright cylinder below), so the toon step and the shader's
  angel ring read on the hair as one mass instead of streaking card by card.

Running it again on its own output gives the same result: the original normals are kept in the
primitives' extras. Plain Python, no dependencies (zlib for the PNG).
"""

import argparse
import math
import os
import struct
import sys
import zlib
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge_primitives import append_accessor, read_accessor, read_glb, write_glb  # noqa: E402

FLOAT, ARRAY_BUFFER = 5126, 34962

# Ellipsoid round the head, as fractions of the face skin's bounds: centre height (0 = chin, 1 =
# top), how far behind the face's front the centre sits (in face widths), and radii (in face
# half-widths). A longer forward radius flattens the front of the face more.
CENTRE_Y = 0.52
CENTRE_BACK = 0.62
RADII = (1.05, 1.25, 1.2)
# Shadow map: the light angle (fraction of 180°) up to which the whole face stays lit, and the
# half-width of the lit range round each texel's facing (fraction of 180°).
FLOOR = 0.14
SPREAD = 0.5


def is_face_skin(name):
    return "Face" in name and name.endswith("_SKIN")


def write_png(path, w, h, rows):
    """An 8-bit RGB PNG; `rows` is a list of h bytearrays of w*3 bytes."""
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--png")
    ap.add_argument("--flat", type=float, default=0.9, help="0 keeps the sculpted normals, 1 uses the ellipsoid's")
    ap.add_argument("--hair", type=float, default=0.35, help="how far hair normals turn toward the head's capsule")
    ap.add_argument("--size", type=int, default=512)
    a = ap.parse_args()
    png = a.png or os.path.splitext(a.out)[0] + ".face.png"

    j, binary = read_glb(a.inp)
    mats = j["materials"]
    faces = [(m, p) for m in j["meshes"] for p in m["primitives"] if "material" in p and is_face_skin(mats[p["material"]].get("name", ""))]
    if not faces:
        print(f"face_normals: no face skin in {a.inp}; unchanged")
        if a.inp != a.out:
            write_glb(a.out, j, binary)
        return
    attrs = faces[0][1]["attributes"]
    original = faces[0][1].get("extras", {}).get("face_normals_from", attrs["NORMAL"])
    pos, _ = read_accessor(j, binary, attrs["POSITION"])
    nor, _ = read_accessor(j, binary, original)
    uv, _ = read_accessor(j, binary, attrs["TEXCOORD_0"])
    tris = []
    for _, p in faces:
        idx, _ = read_accessor(j, binary, p["indices"])
        tris += [tuple(idx[k : k + 3]) for k in range(0, len(idx) - 2, 3)]
    verts = sorted({v for t in tris for v in t})

    # The face's frame: forward from the mean sculpted normal (VRoid faces −Z), right = up × forward.
    fz = sum(nor[3 * v + 2] for v in verts)
    fwd = (0.0, -1.0) if fz < 0 else (0.0, 1.0)
    xs = [pos[3 * v] for v in verts]
    ys = [pos[3 * v + 1] for v in verts]
    zs = [pos[3 * v + 2] for v in verts]
    half = (max(xs) - min(xs)) / 2
    front = min(zs) if fwd[1] < 0 else max(zs)
    centre = ((max(xs) + min(xs)) / 2, min(ys) + (max(ys) - min(ys)) * CENTRE_Y, front - fwd[1] * CENTRE_BACK * 2 * half)
    radii = tuple(r * half for r in RADII)

    def proxy(p):
        """The ellipsoid's normal at p (its gradient), in file space."""
        g = [(p[k] - centre[k]) / (radii[k] ** 2) for k in range(3)]
        n = math.sqrt(sum(c * c for c in g)) or 1.0
        return [c / n for c in g]

    # Flattened normals for the face's vertices.
    new = array("f", nor)
    for v in verts:
        q = proxy(pos[3 * v : 3 * v + 3])
        o = nor[3 * v : 3 * v + 3]
        m = [o[k] * (1 - a.flat) + q[k] * a.flat for k in range(3)]
        n = math.sqrt(sum(c * c for c in m)) or 1.0
        new[3 * v : 3 * v + 3] = array("f", [c / n for c in m])
    count = len(nor) // 3
    nacc = append_accessor(j, binary, new, FLOAT, "VEC3", False, ARRAY_BUFFER)
    zero = append_accessor(j, binary, array("f", [0.0]) * (3 * count), FLOAT, "VEC3", False, ARRAY_BUFFER)
    fw = append_accessor(j, binary, array("f", fwd * count), FLOAT, "VEC2", False, ARRAY_BUFFER)
    for _, p in faces:
        p.setdefault("extras", {})["face_normals_from"] = original
        p["attributes"]["NORMAL"] = nacc
        p["attributes"]["TEXCOORD_1"] = fw
        for t in p.get("targets", []):
            if "NORMAL" in t:
                t["NORMAL"] = zero

    # Hair normals, blended toward a capsule round the head: a sphere above the head's centre,
    # an upright cylinder below it (hanging hair). Card-by-card normals scatter the toon step and
    # the angel ring into streaks; these shade the hair as one mass. A card side that faces in
    # keeps facing in.
    hair = {}
    for m in j["meshes"]:
        for p in m["primitives"]:
            if "material" in p and "_HAIR" in mats[p["material"]].get("name", ""):
                src = p.get("extras", {}).get("hair_normals_from", p["attributes"]["NORMAL"])
                hair.setdefault((p["attributes"]["POSITION"], src), []).append(p)
    hair_verts = 0
    for (pacc, src), prims in hair.items():
        hpos, _ = read_accessor(j, binary, pacc)
        hnor, _ = read_accessor(j, binary, src)
        used = set()
        for p in prims:
            idx, _ = read_accessor(j, binary, p["indices"])
            used.update(idx)
        out = array("f", hnor)
        for v in used:
            p3 = hpos[3 * v : 3 * v + 3]
            axis = (centre[0], min(p3[1], centre[1]), centre[2])
            q = [p3[k] - axis[k] for k in range(3)]
            qn = math.sqrt(sum(c * c for c in q)) or 1.0
            o = hnor[3 * v : 3 * v + 3]
            side = 1.0 if sum(o[k] * q[k] for k in range(3)) >= 0 else -1.0
            mix = [o[k] * (1 - a.hair) + side * q[k] / qn * a.hair for k in range(3)]
            n = math.sqrt(sum(c * c for c in mix)) or 1.0
            out[3 * v : 3 * v + 3] = array("f", [c / n for c in mix])
        acc = append_accessor(j, binary, out, FLOAT, "VEC3", False, ARRAY_BUFFER)
        for p in prims:
            p.setdefault("extras", {})["hair_normals_from"] = src
            p["attributes"]["NORMAL"] = acc
        hair_verts += len(used)
    write_glb(a.out, j, binary)
    print(f"face_normals: {hair_verts} hair vertices blended toward the head's capsule ({a.hair})")

    # The face shadow map. A texel's horizontal facing β (radians from forward, + toward the
    # face's right) stays lit for light angles up to β + SPREAD·π, and always up to FLOOR·π.
    right = (-fwd[1], fwd[0])  # up × forward, in (x, z)

    def thresholds(p):
        q = proxy(p)
        fx, fz2 = q[0] * fwd[0] + q[2] * fwd[1], q[0] * right[0] + q[2] * right[1]
        beta = math.atan2(fz2, fx)
        out = []
        for side in (1.0, -1.0):
            t = (side * beta) / math.pi + SPREAD
            out.append(min(max(t, FLOOR), 1.0))
        return out

    size = a.size
    grid = [None] * (size * size)
    for t in tris:
        (u0, v0), (u1, v1), (u2, v2) = ((uv[2 * k] * size, uv[2 * k + 1] * size) for k in t)
        area = (u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0)
        if abs(area) < 1e-9:
            continue
        P = [pos[3 * k : 3 * k + 3] for k in t]
        for y in range(max(int(min(v0, v1, v2)) - 1, 0), min(int(max(v0, v1, v2)) + 2, size)):
            for x in range(max(int(min(u0, u1, u2)) - 1, 0), min(int(max(u0, u1, u2)) + 2, size)):
                px, py = x + 0.5, y + 0.5
                b1 = ((px - u0) * (v2 - v0) - (u2 - u0) * (py - v0)) / area
                b2 = ((u1 - u0) * (py - v0) - (px - u0) * (v1 - v0)) / area
                b0 = 1 - b1 - b2
                if min(b0, b1, b2) < -0.02:
                    continue
                grid[y * size + x] = thresholds([P[0][k] * b0 + P[1][k] * b1 + P[2][k] * b2 for k in range(3)])
    # Grow the covered texels outward so filtering at UV seams never reads empty ones.
    for _ in range(8):
        grown = list(grid)
        for i, g in enumerate(grid):
            if g is not None:
                continue
            x, y = i % size, i // size
            near = [grid[yy * size + xx] for xx, yy in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)) if 0 <= xx < size and 0 <= yy < size and grid[yy * size + xx] is not None]
            if near:
                grown[i] = [sum(n[k] for n in near) / len(near) for k in range(2)]
        grid = grown
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            g = grid[y * size + x] or (1.0, 1.0)
            row += bytes((round(g[0] * 255), round(g[1] * 255), 0))
        rows.append(row)
    write_png(png, size, size, rows)
    print(f"face_normals: {len(verts)} face vertices in {len(faces)} primitives flattened ({a.flat}); shadow map {png}")


if __name__ == "__main__":
    main()
