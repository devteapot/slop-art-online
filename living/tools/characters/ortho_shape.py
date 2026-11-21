#!/usr/bin/env python3
"""The measuring view's known-answer subject (docs/char-port-2/measure-view/README.md): a head of known
size on a neck, written as a hand-made character file so the client draws it as it draws a
character (the toon material, a character's outline and ink, the file's declared forward).

    python3 living/tools/characters/ortho_shape.py OUT.glb [--known OUT.json]

- **The head:** an ellipsoid, WIDTH across (x), DEPTH front to back (z), HEIGHT tall (y), its
  middle at MIDDLE_Y. It is a UV sphere of 128 meridians and 64 rings, with the equator and the
  meridians through ±x and ±z among them, so its widest outline from the front and the side is
  exactly WIDTH and DEPTH (the facets lie inside the ellipsoid, never outside).
- **The eyes:** two dark spheres of radius EYE_R, EYE_SPACING apart (centre to centre) at
  EYE_Y, each standing EYE_OUT in front of the head's surface. They sit in front of the head's
  outline, as a face's eyes do: the measure perspective widens.
- **The neck:** a cylinder of radius NECK_R from the ground into the head, so the model stands
  on its lowest point (the asset view stands models on their lowest point) and the head is at a
  person's height.
- **The file:** scene extras `{"slop": {"contract": 1, "character": "handmade", "forward":
  "+Z"}}` (handmade.rs), the eyes on +Z; materials with slots `skin` and `eyes`.

Plain Python (no numpy). `known()` returns the answers the selftest holds the pictures to.
"""
import argparse
import json
import math
import os
import sys
from array import array

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from merge_primitives import append_accessor, write_glb  # noqa: E402

WIDTH, DEPTH, HEIGHT = 0.150, 0.200, 0.240
MIDDLE_Y = 1.55
EYE_SPACING, EYE_R, EYE_Y, EYE_OUT = 0.064, 0.012, 1.57, 0.004
NECK_R, NECK_TOP = 0.030, MIDDLE_Y - 0.08
MERIDIANS, RINGS = 128, 64
FLOAT, USHORT, UINT, ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 5126, 5123, 5125, 34962, 34963


def front_z(x, y):
    """The head's front surface (+z) at (x, y), m."""
    a, b, c = WIDTH / 2, HEIGHT / 2, DEPTH / 2
    s = 1 - (x / a) ** 2 - ((y - MIDDLE_Y) / b) ** 2
    return c * math.sqrt(max(s, 0.0))


def known():
    eye_z = front_z(EYE_SPACING / 2, EYE_Y) + EYE_OUT
    return dict(
        width_m=WIDTH, depth_m=DEPTH, height_m=HEIGHT, middle_y_m=MIDDLE_Y,
        top_y_m=MIDDLE_Y + HEIGHT / 2, bottom_y_m=MIDDLE_Y - HEIGHT / 2,
        eye_spacing_m=EYE_SPACING, eye_radius_m=EYE_R, eye_y_m=EYE_Y, eye_centre_z_m=eye_z,
        width_over_eyes=WIDTH / EYE_SPACING, neck_radius_m=NECK_R,
        forward="+Z",
    )


def ellipsoid(cx, cy, cz, a, b, c, meridians, rings):
    """Positions, normals and triangles of a UV ellipsoid (poles on y)."""
    pos, nor, tri = [], [], []
    for r in range(rings + 1):
        phi = -math.pi / 2 + math.pi * r / rings
        for m in range(meridians):
            th = 2 * math.pi * m / meridians
            ux, uy, uz = math.cos(phi) * math.cos(th), math.sin(phi), math.cos(phi) * math.sin(th)
            pos.append((cx + a * ux, cy + b * uy, cz + c * uz))
            n = (ux / a, uy / b, uz / c)
            k = math.sqrt(sum(v * v for v in n)) or 1.0
            nor.append(tuple(v / k for v in n))
    for r in range(rings):
        for m in range(meridians):
            i0, i1 = r * meridians + m, r * meridians + (m + 1) % meridians
            j0, j1 = i0 + meridians, i1 + meridians
            # Outward (counter-clockwise from outside).
            tri += [(i0, j1, i1), (i0, j0, j1)]
    return pos, nor, tri


def cylinder(cx, cz, r, y0, y1, n=48):
    pos, nor, tri = [], [], []
    for y in (y0, y1):
        for m in range(n):
            th = 2 * math.pi * m / n
            pos.append((cx + r * math.cos(th), y, cz + r * math.sin(th)))
            nor.append((math.cos(th), 0.0, math.sin(th)))
    for m in range(n):
        a, b = m, (m + 1) % n
        tri += [(a, b + n, b), (a, a + n, b + n)]
    return pos, nor, tri


def merge(*parts):
    pos, nor, tri = [], [], []
    for p, n, t in parts:
        base = len(pos)
        pos += p
        nor += n
        tri += [(i + base, j + base, k + base) for i, j, k in t]
    return pos, nor, tri


def write(path):
    head = ellipsoid(0.0, MIDDLE_Y, 0.0, WIDTH / 2, HEIGHT / 2, DEPTH / 2, MERIDIANS, RINGS)
    neck = cylinder(0.0, 0.0, NECK_R, 0.0, NECK_TOP)
    k = known()
    eyes = merge(*[ellipsoid(s * EYE_SPACING / 2, EYE_Y, k["eye_centre_z_m"], EYE_R, EYE_R, EYE_R, 24, 12) for s in (-1, 1)])
    j = {
        "asset": {"version": "2.0", "generator": "ortho_shape.py"},
        "scene": 0,
        "scenes": [{"name": "ortho_head", "nodes": [0], "extras": {"slop": {"contract": 1, "character": "handmade", "forward": "+Z"}}}],
        "nodes": [{"name": "ortho_head", "mesh": 0}],
        "meshes": [{"name": "ortho_head", "primitives": []}],
        "materials": [
            {"name": "skin", "pbrMetallicRoughness": {"baseColorFactor": [0.85, 0.62, 0.50, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9}, "extras": {"slop": {"slot": "skin"}}},
            {"name": "eyes", "pbrMetallicRoughness": {"baseColorFactor": [0.05, 0.05, 0.08, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9}, "extras": {"slop": {"slot": "eyes"}}},
        ],
        "accessors": [],
        "bufferViews": [],
        "buffers": [{"byteLength": 0}],
    }
    binary = bytearray()
    for (pos, nor, tri), mat in ((merge(head, neck), 0), (eyes, 1)):
        p = append_accessor(j, binary, array("f", [v for q in pos for v in q]), FLOAT, "VEC3", False, ARRAY_BUFFER)
        n = append_accessor(j, binary, array("f", [v for q in nor for v in q]), FLOAT, "VEC3", False, ARRAY_BUFFER)
        big = len(pos) > 65535
        i = append_accessor(j, binary, array("I" if big else "H", [v for t in tri for v in t]), UINT if big else USHORT, "SCALAR", False, ELEMENT_ARRAY_BUFFER)
        j["meshes"][0]["primitives"].append({"attributes": {"POSITION": p, "NORMAL": n}, "indices": i, "material": mat})
    write_glb(path, j, binary)
    return k


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("--known", help="also write the known answers here (JSON)")
    a = ap.parse_args()
    k = write(a.out)
    if a.known:
        with open(a.known, "w") as f:
            json.dump(k, f, indent=1)
    print(json.dumps(k))


if __name__ == "__main__":
    main()
