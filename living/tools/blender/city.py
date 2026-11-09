"""The megacity kit: buildings, transport and street dressing for the megacity floor
(docs/FLOORS.md), on the buildings.py helpers and conventions (metres, origin at the floor
centred on the footprint, fronts face -Y in Blender, vertex colours on one white "Body"
material with surface tags in their alpha, glowing parts on the shared "Glow" and neon
materials).

Run headless:
    blender -b -P living/tools/blender/city.py -- --kind megatower --count 4 --out DIR
    blender -b -P living/tools/blender/city.py -- --all --count 4 --envs living/game/assets/envs

Kinds (KINDS; every kind comes in forms and keeps its designed size, measured per model):
- buildings: megatower (blade, stepped, twin, needle: 120-300 m), arcology (a terraced mountain
  of a building, 110-180 m), megablock (slab, court, stack: 50-130 m residential blocks), block
  (narrow, wide, corner mid-rise, buildings.py's), neon_tower (an entertainment tower dressed in
  screens and signs), old_block (an older brick and plaster block, retrofitted with neon),
  market (buildings.py's food court), shanty (shack, stack, lean: a few metres deep), container
  (stacked shipping containers, lived in or stored), warehouse (shed, sawtooth), workshop
  (buildings.py's garage and fab), ruin (shell, stump), wall_tower (a gun tower on the wall);
- transport: highway (an elevated deck piece on a central pier, 24 m long: `ring` 22 m wide at
  9 m, `arterial` 16 m wide at 17 m, so arterials pass over the rings);
- street dressing: vending, vent, trash, barrier, vehicle, hologram, scaffold, crane, salvage,
  and buildings.py's lamp, kiosk, food_stall, neon_sign, billboard, cable, crate, wall and street
  props in the cyberpunk look.

Text on signs is our own, in a 14-segment neon font (FONT): brands and trades of this city only
(BRANDS), each with its own logo mark. Nothing is copied from an existing game or franchise.

Lit windows: a share of each tower's windows glow, by storey and run, so the night shows
occupied and empty floors; the game scales all glow with the time of day (daylight.rs).

Each run writes `gen-<kind>-megacity.json` beside its models; `--table` (buildings.py) gathers
them into living/rules/data/buildings.json with every other set.
"""

import argparse
import json
import math
import os
import random
import sys

import bmesh
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildings as B  # noqa: E402
from buildings import X, Y, Z, Face, Kit, box, box_faces, cyl, flipped, grime, lerp, mul, prism, sphere, stripes, tagged  # noqa: E402

STYLE = "megacity"

# The megacity's palette: the cyberpunk kit's, with corporate glass and panels, old brick and
# plaster, container paints and rust.
PAL = dict(B.PALETTES["cyberpunk"])
PAL.update(
    curtain=[tagged(c, "glass") for c in [(0.10, 0.16, 0.24), (0.12, 0.20, 0.22), (0.16, 0.15, 0.22), (0.07, 0.10, 0.14)]],
    corp=[tagged(c, "metal") for c in [(0.62, 0.64, 0.68), (0.30, 0.32, 0.38), (0.78, 0.76, 0.72), (0.20, 0.22, 0.26)]],
    brick=[tagged(c, "brick") for c in [(0.52, 0.28, 0.22), (0.46, 0.30, 0.26), (0.58, 0.36, 0.28)]],
    plaster=[tagged(c, "plaster") for c in [(0.74, 0.68, 0.58), (0.62, 0.66, 0.62), (0.70, 0.58, 0.52)]],
    paintbox=[tagged(c, "metal") for c in [(0.66, 0.20, 0.16), (0.16, 0.34, 0.56), (0.80, 0.56, 0.12), (0.22, 0.48, 0.34), (0.48, 0.48, 0.50), (0.84, 0.82, 0.76)]],
    rust=tagged((0.42, 0.24, 0.14), "metal"),
    tarp=[tagged(c, "cloth") for c in [(0.20, 0.40, 0.70), (0.70, 0.52, 0.20), (0.36, 0.52, 0.30), (0.62, 0.30, 0.26)]],
    asphalt=tagged((0.16, 0.16, 0.18), "concrete"),
    road_line=tagged((0.86, 0.80, 0.42), "plastic"),
)

# Our own brands and trades (no existing franchise's names): name, neon colour, logo mark.
BRANDS = [("KAIROS", "cyan", "ring"), ("HALCYON", "amber", "sun"), ("VANTA", "pink", "chevron"), ("ORRERY", "cyan", "orbit"),
          ("MERIDIAN", "white", "bar"), ("NOVA", "pink", "star"), ("TESSER", "amber", "cube"), ("OKAPI", "cyan", "ring")]
TRADES = ["NOODLE", "RAMEN", "24H", "HOTEL", "BAR", "CLINIC", "PAWN", "ARCADE", "LIVE", "RENT", "SYNTH", "OPEN", "CREDIT", "GYM",
          "TEA", "KARAOKE", "DUMPLING", "REPAIR", "PARTS", "BATH"]

# 14-segment font: segments per character. a top, b upper right, c lower right, d bottom, e lower
# left, f upper left, g left middle, h right middle, i upper centre, l lower centre, j upper-left
# diagonal, k upper-right diagonal, m lower-left diagonal, n lower-right diagonal.
FONT = {
    "A": "abcefgh", "B": "abcdhil", "C": "adef", "D": "abcdil", "E": "adefg", "F": "aefg", "G": "acdefh", "H": "bcefgh",
    "I": "adil", "J": "bcde", "K": "efgkn", "L": "def", "M": "bcefjk", "N": "bcefjn", "O": "abcdef", "P": "abefgh",
    "Q": "abcdefn", "R": "abefghn", "S": "acdfgh", "T": "ail", "U": "bcdef", "V": "efkm", "W": "bcefmn", "X": "jkmn",
    "Y": "jkl", "Z": "adkm", "0": "abcdefkm", "1": "bc", "2": "abdegh", "3": "abcdh", "4": "bcfgh", "5": "acdfgh",
    "6": "acdefgh", "7": "abc", "8": "abcdefgh", "9": "abcdfgh",
}


def text(k, f, a, z, s, h, color, w=0.0, t=0.06):
    """Neon letters of height h centred at `a` on face f, bottom at z, standing w off the wall."""
    cw, gap = h * 0.55, h * 0.22
    span = len(s) * cw + (len(s) - 1) * gap
    x = a - span / 2
    st = max(0.05, h * 0.07)
    for ch in s:
        segs = FONT.get(ch, "")
        x0, x1, zm, z1 = x, x + cw, z + h / 2, z + h
        xm = (x0 + x1) / 2
        bars = {"a": (x0, x1, z1 - st, z1), "d": (x0, x1, z, z + st), "g": (x0, xm, zm - st / 2, zm + st / 2), "h": (xm, x1, zm - st / 2, zm + st / 2),
                "f": (x0, x0 + st, zm, z1), "e": (x0, x0 + st, z, zm), "b": (x1 - st, x1, zm, z1), "c": (x1 - st, x1, z, zm),
                "i": (xm - st / 2, xm + st / 2, zm, z1), "l": (xm - st / 2, xm + st / 2, z, zm)}
        for sg in segs:
            if sg in bars:
                a0, a1, b0, b1 = bars[sg]
                k.add(f.quad(a0, a1, b0, b1, w + t), None, glow=color, closed=False)
            else:
                # Diagonals: from a corner of the upper or lower half to its middle.
                (p, q) = {"j": ((x0, z1), (xm, zm)), "k": ((x1, z1), (xm, zm)), "m": ((x0, z), (xm, zm)), "n": ((x1, z), (xm, zm))}[sg]
                L = math.hypot(q[0] - p[0], q[1] - p[1])
                ang = math.atan2(q[1] - p[1], q[0] - p[0])
                k.add(f.obox((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, L, st, w + t - 0.02, w + t + 0.02, ang), None, glow=color)
        x += cw + gap
    return span


def logo(k, f, a, z, r, mark, color, w=0.0):
    """A brand's mark: a ring, a sun, a chevron, an orbit, a bar, a star or a cube, in neon."""
    c = f.p(a, z, w + 0.05)
    n = f.n
    if mark in ("ring", "orbit", "sun"):
        seg = 18
        for i in range(seg):
            t0, t1 = i / seg * math.tau, (i + 1) / seg * math.tau
            p0 = c + f.u * math.cos(t0) * r + Z * math.sin(t0) * r
            p1 = c + f.u * math.cos(t1) * r + Z * math.sin(t1) * r
            k.add(cyl(p0, p1, r * 0.08, r * 0.08, 4), None, glow=color)
        if mark == "orbit":
            k.add(sphere(c + f.u * r * 0.95 + Z * r * 0.3, r * 0.18, 1), None, glow="white")
        if mark == "sun":
            for i in range(8):
                t = i / 8 * math.tau
                k.add(cyl(c + (f.u * math.cos(t) + Z * math.sin(t)) * r * 1.2, c + (f.u * math.cos(t) + Z * math.sin(t)) * r * 1.55, r * 0.06, r * 0.06, 4), None, glow=color)
        else:
            k.add(cyl(c - n * 0.02, c + n * 0.04, r * 0.35, r * 0.35, 10), None, glow=color)
    elif mark == "chevron":
        for e in (-1, 1):
            k.add(f.obox(a + e * r * 0.45, z, r * 1.25, r * 0.22, w, w + 0.08, -e * 0.85), None, glow=color)
    elif mark == "star":
        for i in range(3):
            k.add(f.obox(a, z, r * 2.0, r * 0.18, w, w + 0.08, i * math.pi / 3), None, glow=color)
    elif mark == "cube":
        k.add(f.box(a - r * 0.6, a + r * 0.6, z - r * 0.6, z + r * 0.6, w, w + 0.06, back=False), None, glow=color)
        k.add(f.box(a - r * 0.35, a + r * 0.35, z - r * 0.35, z + r * 0.35, w + 0.06, w + 0.1, back=False), mul(k.pal["dark"], 1.4), ao=False)
    else:
        k.add(f.box(a - r, a + r, z - r * 0.18, z + r * 0.18, w, w + 0.08, back=False), None, glow=color)


def curtain(k, f, z0, z1, hs, lit, col, frame, bays=None):
    """A glass curtain wall on face f: one pane band per storey split into runs of lit and dark
    offices (a few quads a storey, not one per window), mullion fins and slab lines."""
    L = f.length
    n = max(1, int((z1 - z0) / hs))
    runs = bays or max(2, int(L / 9))
    rl = L / runs
    for s in range(n):
        za = z0 + s * hs
        occupied = k.pr.random() < lit
        for r in range(runs):
            a0 = -L / 2 + r * rl
            on = occupied and k.pr.random() < 0.7
            q = f.quad(a0 + 0.05, a0 + rl - 0.05, za + 0.25, za + hs - 0.15, 0.02)
            if on:
                k.add(q, None, glow=True if k.pr.random() < 0.85 else k.pr.choice(["cyan", "white"]), closed=False)
            else:
                k.add(q, col, closed=False, ao=False, vary=0.05)
    # Slab lines every storey and mullion fins every few metres, as long boxes.
    for s in range(0, n + 1, 1 if n < 30 else 2):
        za = z0 + s * hs
        k.add(f.box(-L / 2, L / 2, za - 0.12, za + 0.12, 0.0, 0.12, back=False), frame, ao=False, vary=0)
    nf = max(2, int(L / 3.0))
    for i in range(nf + 1):
        a = -L / 2 + i * L / nf
        k.add(f.box(a - 0.09, a + 0.09, z0, z0 + n * hs, 0.0, 0.25, back=False), frame, ao=False, vary=0)
    return z0 + n * hs


def shaft(k, x0, x1, y0, y1, z0, z1, hs, lit, P, faces=("front", "back", "left", "right")):
    """A tower's glazed shaft: a core box and curtain walls on its faces."""
    k.add(box((x0 + 0.3, y0 + 0.3, z0), (x1 - 0.3, y1 - 0.3, z1)), mul(P["frame"], 0.6), ao=False, vary=0)
    fs = box_faces((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2)
    top = z1
    for name in faces:
        top = curtain(k, fs[name], z0, z1, hs, lit, P["glass"], P["frame"])
    return fs, top


def corp_colours(k):
    brand = k.rng.choice(BRANDS)
    return dict(glass=k.choice(PAL["curtain"]), frame=k.choice(PAL["corp"]), brand=brand, neon=[brand[1], k.rng.choice(["cyan", "pink", "amber"])],
                wall=k.choice(PAL["concrete"]), panel=k.choice(PAL["panel"]), trim=k.choice(PAL["trim"]), metal=PAL["metal"], dark=PAL["dark"],
                awning=k.choice(PAL["awning"]))


def podium(k, P, W, D, storeys=2):
    """A street podium: shops round the foot (buildings.py's street storey) and office storeys."""
    hs0 = k.u(4.6, 5.4)
    B.cp_ground(k, P, -W / 2, W / 2, -D / 2, D / 2, hs0, {"front": max(2, round(W / 6.0)), "left": max(1, round(D / 9.0)), "right": max(1, round(D / 9.0))})
    z = hs0
    if storeys > 1:
        z = B.cp_storeys(k, P, -W / 2, W / 2, -D / 2, D / 2, hs0, storeys - 1, 4.0, {"front": 0.6, "left": 0.5, "right": 0.5, "back": 0.4}, bay=3.4, clutter=False, glazing="ribbon")
    B.cp_parapet(k, P, -W / 2, W / 2, -D / 2, D / 2, z, h=1.1)
    return z


def crown(k, P, x0, x1, y0, y1, z, name_face="front", spire=True, h=None):
    """A tower's crown: a lit band, the brand's name and mark in neon on the street face, a cap,
    maintenance rails and a spire with warning lights."""
    W, D = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    h = h or k.u(5.0, 8.0)
    k.add(box((x0 - 0.2, y0 - 0.2, z), (x1 + 0.2, y1 + 0.2, z + 0.5)), P["frame"], ao=False)
    k.add(box((x0 + 0.1, y0 + 0.1, z + 0.5), (x1 - 0.1, y1 - 0.1, z + h)), mul(P["dark"], 1.8), ao=False)
    k.add(box((x0 - 0.05, y0 - 0.05, z + h - 0.6), (x1 + 0.05, y1 + 0.05, z + h - 0.3)), None, glow=P["neon"][0])
    k.add(box((x0 - 0.3, y0 - 0.3, z + h), (x1 + 0.3, y1 + 0.3, z + h + 0.6)), P["frame"], ao=False)
    fs = box_faces(cx, cy, W / 2, D / 2)
    name, col, mark = P["brand"]
    for fn in ([name_face, "back"] if W > 14 else [name_face]):
        f = fs[fn]
        lh = min(h * 0.5, f.length / (len(name) * 0.77 + 2.4))
        span = len(name) * lh * 0.55 + (len(name) - 1) * lh * 0.22
        start = -(lh + 0.4 * lh + span) / 2
        logo(k, f, start + lh / 2, z + 0.5 + h / 2, lh * 0.45, mark, col, w=0.12)
        text(k, f, start + 1.4 * lh + span / 2, z + 0.5 + (h - lh) / 2, name, lh, col, w=0.12)
    top = z + h + 0.6
    if spire:
        sh = k.u(10.0, 26.0)
        k.add(cyl((cx, cy, top), (cx, cy, top + sh * 0.3), min(W, D) * 0.08, min(W, D) * 0.05, 8), P["frame"], ao=False)
        k.add(cyl((cx, cy, top + sh * 0.3), (cx, cy, top + sh), 0.35, 0.06, 6), mul(P["frame"], 1.2), ao=False)
        k.add(sphere((cx, cy, top + sh + 0.1), 0.35, 1), None, glow="red")
        k.add(sphere((cx, cy, top + sh * 0.6), 0.25, 1), None, glow="red")
    for (x, y) in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        k.add(sphere((x, y, top + 0.2), 0.3, 1), None, glow="red")
    return top


def holo_column(k, f, a, z0, h, w, c1, c2):
    """A tall vertical screen up a shaft face (buildings.py's holo-billboard, stood on end)."""
    B.cp_screen(k, f, a, z0, w, h, c1, c2, out=0.45)


def megatower(k):
    """A corporate megatower over a shop podium, by form: blade (a slab with a screen up its
    face), stepped (setbacks every 15-25 storeys), twin (two shafts and a sky bridge) or needle
    (a tapering stack of glazed drums). Glass curtain walls with runs of lit offices, sky lobbies,
    and a crown with the brand's name and mark."""
    form = k.form
    P = corp_colours(k)
    hs = 3.9
    if form == "blade":
        W, D = k.u(34.0, 44.0), k.u(20.0, 26.0)
        zp = podium(k, P, W + 6.0, D + 6.0, k.rng.choice([2, 3]))
        n = k.rng.choice([34, 40, 46])
        fs, top = shaft(k, -W / 2, W / 2, -D / 2, D / 2, zp, zp + n * hs, hs, k.u(0.45, 0.7), P)
        holo_column(k, fs["front"], W * k.u(-0.2, 0.2), zp + n * hs * 0.25, n * hs * 0.45, W * 0.28, P["neon"][0], P["neon"][1])
        for zz in (zp + n * hs * 0.33, zp + n * hs * 0.66):
            k.add(box((-W / 2 - 0.1, -D / 2 - 0.1, zz - 0.5), (W / 2 + 0.1, D / 2 + 0.1, zz + 0.5)), None, glow=P["neon"][1])
        crown(k, P, -W / 2, W / 2, -D / 2, D / 2, top)
    elif form == "stepped":
        W, D = k.u(36.0, 46.0), k.u(32.0, 40.0)
        z = podium(k, P, W + 6.0, D + 6.0, 3)
        w, d = W, D
        for i in range(k.rng.choice([3, 4])):
            n = k.rng.choice([14, 16, 20])
            _, z1 = shaft(k, -w / 2, w / 2, -d / 2, d / 2, z, z + n * hs, hs, k.u(0.4, 0.7), P)
            # A terrace with a lit edge and planters at each setback.
            k.add(box((-w / 2, -d / 2, z1), (w / 2, d / 2, z1 + 0.4)), P["frame"], ao=False)
            k.add(box((-w / 2 - 0.05, -d / 2 - 0.05, z1 + 0.4), (w / 2 + 0.05, d / 2 + 0.05, z1 + 0.6)), None, glow=P["neon"][0])
            z = z1 + 0.4
            w, d = w * k.u(0.72, 0.8), d * k.u(0.72, 0.8)
        crown(k, P, -w / 2, w / 2, -d / 2, d / 2, z)
    elif form == "twin":
        W, D = k.u(46.0, 56.0), k.u(22.0, 28.0)
        zp = podium(k, P, W + 4.0, D + 6.0, 3)
        sw = W * 0.38
        heights = [k.rng.choice([36, 42]), k.rng.choice([30, 36])]
        tops = []
        for e, n in zip((-1, 1), heights):
            cx = e * (W / 2 - sw / 2)
            _, t = shaft(k, cx - sw / 2, cx + sw / 2, -D / 2, D / 2, zp, zp + n * hs, hs, k.u(0.45, 0.7), P)
            tops.append(t)
        # Sky bridges between the shafts.
        for zz in (zp + 18 * hs, zp + 28 * hs):
            k.add(box((-W / 2 + sw - 0.2, -D * 0.22, zz), (W / 2 - sw + 0.2, D * 0.22, zz + 2 * hs)), P["frame"], ao=False)
            f = Face((0, -D * 0.22, 0), X, W - 2 * sw)
            k.add(f.quad(-f.length / 2 + 0.3, f.length / 2 - 0.3, zz + 0.6, zz + 2 * hs - 0.4, 0.02), None, glow=True, closed=False)
        for e, t in zip((-1, 1), tops):
            cx = e * (W / 2 - sw / 2)
            crown(k, P, cx - sw / 2, cx + sw / 2, -D / 2, D / 2, t, spire=e == -1)
    else:  # needle
        R = k.u(13.0, 17.0)
        zp = podium(k, P, 2 * R + 8.0, 2 * R + 8.0, 2)
        z = zp
        r = R
        sides = 12
        for i in range(5):
            n = k.rng.choice([10, 12, 14])
            z1 = z + n * hs
            k.add(cyl((0, 0, z), (0, 0, z1), r, r * 0.97, sides), P["glass"], ao=False, vary=0.02)
            # Lit storeys as rings of panes round the drum.
            for s in range(n):
                if k.pr.random() < 0.55:
                    za = z + s * hs
                    for j in range(sides):
                        if k.pr.random() < 0.6:
                            t0, t1 = j / sides * math.tau, (j + 1) / sides * math.tau
                            rr = r * 0.995 + 0.03
                            p0, p1 = (math.cos(t0) * rr, math.sin(t0) * rr), (math.cos(t1) * rr, math.sin(t1) * rr)
                            bm = bmesh.new()
                            vs = [bm.verts.new((p0[0], p0[1], za + 0.3)), bm.verts.new((p1[0], p1[1], za + 0.3)), bm.verts.new((p1[0], p1[1], za + hs - 0.2)), bm.verts.new((p0[0], p0[1], za + hs - 0.2))]
                            bm.faces.new(vs)
                            k.add(bm, None, glow=True, closed=False)
            k.add(cyl((0, 0, z1 - 0.1), (0, 0, z1 + 0.6), r + 0.4, r + 0.4, sides), P["frame"], ao=False)
            k.add(cyl((0, 0, z1 + 0.6), (0, 0, z1 + 0.8), r + 0.45, r + 0.45, sides), None, glow=P["neon"][i % 2])
            z = z1 + 0.8
            r *= k.u(0.78, 0.86)
        k.add(cyl((0, 0, z), (0, 0, z + 30.0), r * 0.5, 0.15, 8), P["frame"], ao=False)
        k.add(sphere((0, 0, z + 30.1), 0.4, 1), None, glow="red")
        f = Face((0, -R - 4.0 - 0.05, 0), X, 2 * R + 8.0)
        text(k, f, 0.0, zp + 0.6, P["brand"][0], 2.2, P["brand"][1], w=0.15)


def arcology(k):
    """An arcology: a terraced mountain of a building (a city in one structure). Stacked
    rectangular tiers stepping back on all sides, each with glazed faces and planted terrace
    edges, light wells, a ring of screens, a crowning hall and a beacon."""
    P = corp_colours(k)
    P["glass"] = k.choice(PAL["curtain"])
    hs = 4.2
    W, D = k.u(84.0, 100.0), k.u(78.0, 92.0)
    B.cp_ground(k, P, -W / 2, W / 2, -D / 2, D / 2, 6.0, {"front": round(W / 7.0), "left": round(D / 8.0), "right": round(D / 8.0), "back": 3})
    z = 6.0
    w, d = W, D
    tiers = k.rng.choice([6, 7])
    for i in range(tiers):
        n = k.rng.choice([5, 6, 7])
        fs, z1 = shaft(k, -w / 2, w / 2, -d / 2, d / 2, z, z + n * hs, hs, k.u(0.5, 0.75), P)
        # The terrace: a lit edge, planters and a rail.
        k.add(box((-w / 2, -d / 2, z1), (w / 2, d / 2, z1 + 0.5)), P["frame"], ao=False)
        k.add(box((-w / 2 - 0.05, -d / 2 - 0.05, z1 + 0.5), (w / 2 + 0.05, d / 2 + 0.05, z1 + 0.65)), None, glow=P["neon"][i % 2])
        nw = w * k.u(0.78, 0.84)
        nd = d * k.u(0.78, 0.84)
        green = tagged((0.26, 0.42, 0.24), "leaves")
        for (fx, fy, fw, fd) in ((0, -(d + nd) / 4, w - 1.0, (d - nd) / 2 - 1.0), (0, (d + nd) / 4, w - 1.0, (d - nd) / 2 - 1.0)):
            if fd > 1.2:
                k.add(box((fx - fw / 2, fy - 0.6, z1 + 0.5), (fx + fw / 2, fy + 0.6, z1 + 1.4)), green, ao=False)
        if i == 1:
            for fn in ("front", "left", "right"):
                f = fs[fn]
                B.cp_screen(k, f, 0.0, z + 2 * hs, f.length * 0.4, n * hs * 0.6, P["neon"][0], P["neon"][1], out=0.4)
        z = z1 + 0.5
        w, d = nw, nd
    # The crowning hall: a glass dome-like drum and a beacon.
    k.add(cyl((0, 0, z), (0, 0, z + 10.0), min(w, d) * 0.45, min(w, d) * 0.4, 16), P["glass"], ao=False)
    k.add(cyl((0, 0, z + 10.0), (0, 0, z + 14.0), min(w, d) * 0.4, min(w, d) * 0.1, 16), P["frame"], ao=False)
    k.add(cyl((0, 0, z + 14.0), (0, 0, z + 34.0), 0.6, 0.1, 6), P["frame"], ao=False)
    k.add(sphere((0, 0, z + 34.2), 0.7, 1), None, glow="red")
    f = Face((0, -D / 2 - 0.05, 0), X, W)
    text(k, f, 0.0, 6.3, P["brand"][0], 3.0, P["brand"][1], w=0.2)


def megablock(k):
    """A residential megablock, by form: slab (a long block with deep light wells, balconies
    and laundry), court (four wings round a courtyard, open on the front for the street) or stack
    (offset boxes piled up, walkways between them). Punched windows lit by household, AC units,
    fire escapes down the ends, rooftop clutter, shops at the foot."""
    form = k.form
    P = B.cp_colours(k)
    hs0, hs = k.u(4.4, 4.8), 3.1
    lit = k.u(0.5, 0.7)
    if form == "slab":
        W, D = k.u(70.0, 96.0), k.u(20.0, 26.0)
        n = k.rng.choice([20, 24, 28, 32])
        B.cp_ground(k, P, -W / 2, W / 2, -D / 2, D / 2, hs0, {"front": round(W / 5.5), "back": round(W / 9.0), "left": 1, "right": 1})
        # Wings between light wells cut into the front.
        wings = k.rng.choice([3, 4])
        ww = W / wings
        for i in range(wings):
            x0 = -W / 2 + i * ww + (0.0 if i == 0 else 2.0)
            x1 = -W / 2 + (i + 1) * ww - (0.0 if i == wings - 1 else 2.0)
            z1 = B.cp_storeys(k, P, x0, x1, -D / 2, D / 2, hs0, n, hs, {"front": lit, "back": lit * 0.8, "left": 0.4 if i == 0 else 0.0, "right": 0.4 if i == wings - 1 else 0.0}, bay=2.4, clutter=True)
            B.cp_roof(k, P, x0, x1, -D / 2, D / 2, z1, busy=0.7)
        for i in range(1, wings):
            x = -W / 2 + i * ww
            k.add(box((x - 2.05, -D / 2 + 4.0, hs0), (x + 2.05, D / 2, hs0 + n * hs)), grime(mul(P["wall"], 0.7)), ao=False)
            # Laundry across the light well.
            for s in range(2, n, 3):
                B.sag_line(k, (x - 2.0, -D / 2 + 4.2, hs0 + s * hs + 1.6), (x + 2.0, -D / 2 + 4.2, hs0 + s * hs + 1.5), 0.25, 0.03, (0.2, 0.2, 0.2), seg=3)
        fs = box_faces(0, 0, W / 2, D / 2)
        B.cp_fire_escape(k, P, fs["left"], -D / 2 + 2.0, -D / 2 + 6.0, hs0, n, hs)
        B.cp_fire_escape(k, P, fs["right"], D / 2 - 6.0, D / 2 - 2.0, hs0, n, hs)
        B.cp_signage(k, P, fs["front"], hs0, hs0 + 4 * hs, W)
    elif form == "court":
        W, D = k.u(64.0, 80.0), k.u(56.0, 70.0)
        n = k.rng.choice([16, 18, 22])
        t = k.u(14.0, 17.0)
        B.cp_ground(k, P, -W / 2, W / 2, -D / 2, -D / 2 + t, hs0, {"front": round(W / 5.5), "left": 1, "right": 1})
        wings = [(-W / 2, -W / 2 + t, -D / 2 + t, D / 2), (W / 2 - t, W / 2, -D / 2 + t, D / 2), (-W / 2 + t, W / 2 - t, D / 2 - t, D / 2)]
        for (x0, x1, y0, y1) in wings:
            k.add(box((x0, y0, -0.01), (x1, y1, hs0)), grime(mul(P["wall"], 0.8)), ao=False)
            z1 = B.cp_storeys(k, P, x0, x1, y0, y1, hs0, n, hs, {"front": lit, "back": lit * 0.7, "left": lit * 0.6, "right": lit * 0.6}, bay=2.4, clutter=True)
            B.cp_roof(k, P, x0, x1, y0, y1, z1, busy=0.6)
        z1 = B.cp_storeys(k, P, -W / 2, W / 2, -D / 2, -D / 2 + t, hs0, n - 4, hs, {"front": lit, "back": lit * 0.7, "left": 0.5, "right": 0.5}, bay=2.4, clutter=True)
        B.cp_roof(k, P, -W / 2, W / 2, -D / 2, -D / 2 + t, z1, busy=0.8)
        fs = box_faces(0, -D / 2 + t / 2, W / 2, t / 2)
        B.cp_signage(k, P, fs["front"], hs0, hs0 + 5 * hs, W)
        # A gate passage through the front wing to the court.
        f = fs["front"]
        k.add(f.box(-3.0, 3.0, 0.0, hs0 + 2 * hs, -0.3, 0.05, back=False), mul(P["dark"], 1.4), ao=False)
        text(k, f, 0.0, hs0 + 2 * hs + 0.4, k.rng.choice(["BLOCK", "COURT", "ESTATE"]) + str(k.rng.randrange(1, 99)), 1.2, P["neon"][0], w=0.1)
    else:  # stack
        W, D = k.u(40.0, 52.0), k.u(28.0, 36.0)
        B.cp_ground(k, P, -W / 2, W / 2, -D / 2, D / 2, hs0, {"front": round(W / 5.5), "left": 1, "right": 1})
        z = hs0
        x0, x1, y0, y1 = -W / 2, W / 2, -D / 2, D / 2
        for i in range(k.rng.choice([4, 5, 6])):
            n = k.rng.choice([4, 5, 6])
            z1 = B.cp_storeys(k, P, x0, x1, y0, y1, z, n, hs, {"front": lit, "back": lit * 0.7, "left": lit * 0.6, "right": lit * 0.6}, bay=2.4, clutter=True)
            B.cp_parapet(k, P, x0, x1, y0, y1, z1, h=1.0)
            # The next box shifts and turns its size.
            w2, d2 = k.u(0.6, 0.85) * (x1 - x0), k.u(0.7, 1.0) * (y1 - y0)
            sx = k.u(-0.5, 0.5) * ((x1 - x0) - w2)
            sy = k.u(-0.5, 0.5) * ((y1 - y0) - d2)
            nx0, nx1 = (x0 + x1) / 2 + sx - w2 / 2, (x0 + x1) / 2 + sx + w2 / 2
            ny0, ny1 = (y0 + y1) / 2 + sy - d2 / 2, (y0 + y1) / 2 + sy + d2 / 2
            # A walkway on the terrace it leaves, lit along its edge.
            k.add(box((x0 + 0.3, y0 + 0.3, z1 + 0.95), (x1 - 0.3, y0 + 1.2, z1 + 1.05)), None, glow=P["neon"][i % 2])
            x0, x1, y0, y1, z = nx0, nx1, ny0, ny1, z1
        B.cp_roof(k, P, x0, x1, y0, y1, z, busy=1.0)
        fs = box_faces(0, 0, W / 2, D / 2)
        B.cp_signage(k, P, fs["front"], hs0, hs0 + 4 * hs, W)


def neon_tower(k):
    """An entertainment tower: a slender block (buildings.py's tower) wrapped in screens, a
    stack of blade signs and a name in big letters, with a club entrance lit at the foot."""
    k.form = "slender"
    B.cyber_tower(k)
    P = B.cp_colours(k)
    vs = k.b.bm.verts
    W = 2 * max(abs(v.co.x) for v in vs)
    D = 2 * max(abs(v.co.y) for v in vs)
    H = max(v.co.z for v in vs)
    fs = box_faces(0, 0, W / 2 - 0.4, D / 2 - 0.4)
    for fn in ("left", "right"):
        f = fs[fn]
        B.cp_screen(k, f, 0.0, H * 0.35, f.length * 0.8, H * 0.35, P["neon"][0], P["neon"][1], out=0.6)
    f = fs["front"]
    trade = k.rng.choice(["KARAOKE", "ARCADE", "LIVE", "BAR", "HOTEL", "BATH"])
    lh = min(2.4, (H * 0.5) / (len(trade) * 1.0))
    fb = Face(f.p(f.length / 2 - 0.2, 0, 0), f.n, 3.0)
    for side in (fb, flipped(fb)):
        for i, ch in enumerate(trade):
            text(k, side, 1.6, H * 0.8 - (i + 1) * lh * 1.25, ch, lh, P["neon"][i % 2], w=0.25)
    k.add(fb.box(0.2, 3.0, H * 0.8 - len(trade) * lh * 1.25 - 0.4, H * 0.8 + 0.2, -0.22, 0.22), mul(PAL["dark"], 1.5), ao=False)


def old_block(k):
    """An older city block, by form (narrow, wide): brick or plaster over arcaded shops, tall
    shuttered windows and cornices, now hung with neon, cables, AC boxes and satellite dishes."""
    form = k.form
    pal = PAL
    wall = k.choice(pal["brick"] + pal["plaster"])
    trim = k.choice(pal["plaster"])
    P = B.cp_colours(k)
    P["wall"] = wall
    W = k.u(9.0, 12.0) if form == "narrow" else k.u(16.0, 22.0)
    D = k.u(11.0, 14.0)
    n = k.rng.choice([3, 4, 5]) if form == "narrow" else k.rng.choice([4, 5, 6])
    hs0, hs = k.u(4.0, 4.6), k.u(3.2, 3.5)
    B.cp_ground(k, P, -W / 2, W / 2, -D / 2, D / 2, hs0, {"front": max(2, round(W / 4.0)), "left": 0, "right": 0})
    for s in range(n):
        za = hs0 + s * hs
        k.add(box((-W / 2, -D / 2, za - 0.01), (W / 2, D / 2, za + hs)), grime(wall, 12.0, 0.6), ao=False, vary=0.02)
        k.add(box((-W / 2 - 0.1, -D / 2 - 0.15, za - 0.05), (W / 2 + 0.1, D / 2 + 0.1, za + 0.18)), trim, ao=False)
    fs = box_faces(0, 0, W / 2, D / 2)
    for fn in ("front", "back"):
        f = fs[fn]
        nb = max(2, round(f.length / 2.6))
        for s in range(n):
            za = hs0 + s * hs
            for i in range(nb):
                a = -f.length / 2 + (i + 0.5) * f.length / nb
                q = f.quad(a - 0.55, a + 0.55, za + 0.7, za + hs - 0.5, 0.02)
                v = k.pr.random()
                if v < 0.42:
                    k.add(q, None, glow=True, closed=False)
                else:
                    k.add(q, pal["glass"] if v < 0.8 else pal["blind"], closed=False, ao=False)
                # Shutters, open.
                for e in (-1, 1):
                    k.extra(f.box(a + e * 0.6, a + e * 1.05, za + 0.7, za + hs - 0.5, 0.02, 0.08, back=False), stripes(mul(k.choice(pal["paintbox"]), 0.8), 0.18, 0.85, 2), ao=False)
                k.extra(f.box(a - 0.65, a + 0.65, za + 0.6, za + 0.7, 0.0, 0.2, back=False), trim, ao=False)
                if k.pr.random() < 0.12 and fn == "front":
                    B.cp_ac(k, f, a + 0.9, za + 0.3, P["metal"])
    top = hs0 + n * hs
    # A heavy cornice and a roof with a water tank and dishes.
    k.add(box((-W / 2 - 0.4, -D / 2 - 0.5, top), (W / 2 + 0.4, D / 2 + 0.3, top + 0.7)), trim, ao=False)
    B.cp_roof(k, P, -W / 2, W / 2, -D / 2, D / 2, top + 0.7, busy=0.8)
    B.cp_signage(k, P, fs["front"], hs0, top, W)
    B.cp_hang_cables(k, fs["front"], -W / 2 + 0.3, W / 2 - 0.3, hs0 + 0.6, n=3)


def shanty(k):
    """Slum housing a few metres deep, by form: shack (one room of sheet and scrap on a slab),
    stack (two to four shacks piled up, ladders and a stair, tarps and laundry) or lean (a
    lean-to against a blank wall). Patched panels, a glowing doorway, a TV glow, wires."""
    form = k.form
    pal = PAL
    metal = pal["metal"]
    rust = pal["rust"]

    def shack(x0, x1, y0, y1, z0, h):
        panels = max(2, int((x1 - x0) / 1.2))
        pw = (x1 - x0) / panels
        for i in range(panels):
            c = k.choice([rust, mul(metal, 0.8), k.choice(pal["paintbox"]), k.choice(pal["tarp"])])
            k.add(box((x0 + i * pw, y0, z0), (x0 + (i + 1) * pw + 0.02, y1, z0 + h + k.pr.uniform(-0.15, 0.15))), stripes(c, 0.16, 0.86, 0), ao=False)
        # A sloped sheet roof, overhanging.
        k.add(prism([(y0 - 0.4, z0 + h + 0.1), (y1 + 0.3, z0 + h + 0.45), (y1 + 0.3, z0 + h + 0.55), (y0 - 0.4, z0 + h + 0.2)], x0 - 0.3, x1 + 0.3,
                    lambda a, s_, z: Vector((a, s_, z))), stripes(k.choice([mul(metal, 0.7), rust]), 0.2, 0.84, 0), ao=False)
        f = Face(((x0 + x1) / 2, y0, 0), X, x1 - x0)
        a = k.u(-0.25, 0.25) * (x1 - x0)
        k.add(f.quad(a - 0.45, a + 0.45, z0, z0 + 1.9, 0.02), None, glow=True if k.pr.random() < 0.6 else k.pr.choice(["cyan", "pink"]), closed=False)
        if x1 - x0 > 2.6:
            k.add(f.quad(a + 0.8, a + 1.5, z0 + 1.0, z0 + 1.6, 0.02), None, glow=k.pr.random() < 0.5, closed=False) if k.pr.random() < 0.7 else None
        return f

    if form == "shack":
        W, D = k.u(3.4, 5.5), k.u(3.0, 4.2)
        k.add(box((-W / 2 - 0.2, -D / 2 - 0.2, -0.01), (W / 2 + 0.2, D / 2 + 0.2, 0.2)), pal["stone"])
        f = shack(-W / 2, W / 2, -D / 2, D / 2, 0.2, k.u(2.3, 2.8))
        if k.pr.random() < 0.6:
            B.cp_board(k, f, -W / 2 + 0.2, W / 2 - 0.2, 2.6, 3.1, k.pr.choice(["pink", "cyan", "amber"]), mul(pal["dark"], 1.4), w=0.05)
    elif form == "stack":
        W, D = k.u(4.5, 7.0), k.u(3.6, 5.0)
        k.add(box((-W / 2 - 0.2, -D / 2 - 0.2, -0.01), (W / 2 + 0.2, D / 2 + 0.2, 0.2)), pal["stone"])
        z = 0.2
        levels = k.rng.choice([2, 3, 3, 4])
        for i in range(levels):
            sx = k.u(-0.6, 0.6) if i else 0.0
            w = W * k.u(0.75, 1.0) if i else W
            h = k.u(2.3, 2.7)
            shack(sx - w / 2, sx + w / 2, -D / 2, D / 2 - (0.6 if i else 0.0), z, h)
            # A deck and rail round each upper floor.
            if i:
                k.add(box((sx - w / 2 - 0.6, -D / 2 - 1.0, z - 0.12), (sx + w / 2 + 0.6, D / 2, z)), mul(metal, 0.7), ao=False)
                k.add(box((sx - w / 2 - 0.6, -D / 2 - 1.0, z + 0.9), (sx + w / 2 + 0.6, -D / 2 - 0.92, z + 1.0)), pal["iron"], ao=False)
            z += h + 0.55
        # A ladder up the side.
        for e in (0.0, 0.5):
            k.add(box((W / 2 + 0.25 + e, -D / 2 - 0.4, 0.0), (W / 2 + 0.31 + e, -D / 2 - 0.34, z - 0.4)), pal["iron"], ao=False)
        for zz in range(int(z / 0.4)):
            k.add(box((W / 2 + 0.25, -D / 2 - 0.4, zz * 0.4), (W / 2 + 0.81, -D / 2 - 0.36, zz * 0.4 + 0.05)), pal["iron"], ao=False)
        B.sag_line(k, (-W / 2, -D / 2 - 0.9, z - 1.0), (W / 2, -D / 2 - 0.9, z - 1.2), 0.3, 0.025, (0.12, 0.1, 0.1), seg=4)
        for i in range(k.rng.choice([2, 3, 4])):
            x = k.u(-W / 2 + 0.3, W / 2 - 0.3)
            k.add(box((x - 0.25, -D / 2 - 0.92, z - 1.6), (x + 0.25, -D / 2 - 0.9, z - 1.1)), k.choice(pal["tarp"]), ao=False)
        if k.pr.random() < 0.6:
            f = Face((0, -D / 2 - 1.0, 0), X, W)
            text(k, f, 0.0, z - 0.2, k.pr.choice(["REPAIR", "PARTS", "TEA", "NOODLE", "RENT"]), 0.5, k.pr.choice(["pink", "cyan", "amber"]), w=0.05)
    else:  # lean
        W, D = k.u(5.0, 8.0), k.u(2.6, 3.4)
        k.add(box((-W / 2, D / 2 - 0.6, -0.01), (W / 2, D / 2, k.u(5.0, 7.0))), grime(k.choice(pal["concrete"]), 6.0), ao=False)
        shack(-W / 2 + 0.2, W / 2 - 0.2, -D / 2, D / 2 - 0.6, 0.0, k.u(2.2, 2.6))
        k.add(box((-W / 2 + 0.4, -D / 2 - 1.4, 2.4), (W / 2 - 0.4, -D / 2, 2.5)), stripes(k.choice(pal["tarp"]), 0.5, 0.85, 0), ao=False)
        for e in (-1, 1):
            k.add(box((e * (W / 2 - 0.5) - 0.05, -D / 2 - 1.35, 0.0), (e * (W / 2 - 0.5) + 0.05, -D / 2 - 1.25, 2.45)), pal["iron"], ao=False)


def container_box(k, x, y, z, L, rot90, color, door=False, home=False):
    """One shipping container (12 or 6 m): corrugated sides, end doors with bars, corner
    castings; as a home, a cut window glowing and a door."""
    W, H = 2.44, 2.6
    lx, ly = (W, L) if rot90 else (L, W)
    k.add(box((x - lx / 2, y - ly / 2, z), (x + lx / 2, y + ly / 2, z + H)), stripes(color, 0.3, 0.84, 1 if rot90 else 0), ao=False, vary=0.06)
    for (cx, cy) in ((x - lx / 2, y - ly / 2), (x + lx / 2, y - ly / 2), (x - lx / 2, y + ly / 2), (x + lx / 2, y + ly / 2)):
        k.extra(box((cx - 0.12, cy - 0.12, z), (cx + 0.12, cy + 0.12, z + 0.2)), mul(PAL["metal"], 0.6), ao=False)
        k.extra(box((cx - 0.12, cy - 0.12, z + H - 0.2), (cx + 0.12, cy + 0.12, z + H)), mul(PAL["metal"], 0.6), ao=False)
    if home:
        f = Face((x, y - ly / 2, 0), X, lx)
        a = k.u(-0.3, 0.3) * lx
        k.add(f.quad(a - 0.6, a + 0.6, z + 1.0, z + 1.9, 0.02), None, glow=k.pr.random() < 0.7, closed=False)


def container(k):
    """Stacked shipping containers: stack2/stack3 (a port's stored containers, or homes cut into
    them with windows, a stair and a deck when `home`)."""
    form = k.form
    home = form.startswith("home")
    levels = 3 if form.endswith("3") else 2
    cols = k.rng.choice([2, 3])
    L = 12.2 if not home else k.rng.choice([6.1, 12.2])
    for lv in range(levels):
        for c in range(cols - (1 if lv == levels - 1 and k.rng.random() < 0.4 else 0)):
            x = (c - (cols - 1) / 2) * 2.5
            container_box(k, x, 0.0, lv * 2.6, L, True, k.choice(PAL["paintbox"]), home=home)
    if home:
        D = L
        for lv in range(1, levels):
            k.add(box((-cols * 1.25 - 1.0, -D / 2 - 1.1, lv * 2.6 - 0.1), (cols * 1.25, -D / 2, lv * 2.6)), mul(PAL["metal"], 0.7), ao=False)
            k.add(box((-cols * 1.25 - 1.0, -D / 2 - 1.1, lv * 2.6 + 0.9), (cols * 1.25, -D / 2 - 1.02, lv * 2.6 + 1.0)), PAL["iron"], ao=False)
        f = Face((0, -D / 2 - 1.1, 0), X, cols * 2.5)
        text(k, f, 0.0, levels * 2.6 + 0.3, k.pr.choice(["RENT", "HOTEL", "24H", "TEA"]), 0.7, k.pr.choice(["pink", "cyan", "amber"]), w=0.05)
        k.add(box((-0.8, -0.8, levels * 2.6), (0.8, 0.8, levels * 2.6 + 1.6)), k.choice(PAL["tarp"]), ao=False)


def warehouse(k):
    """An industrial shed, by form: shed (a big portal-frame hall, loading doors, a gantry
    sign) or sawtooth (a north-light roof over a works), with tanks, pipes and stacks."""
    form = k.form
    pal = PAL
    P = B.cp_colours(k)
    W, D = k.u(26.0, 40.0), k.u(18.0, 28.0)
    H = k.u(9.0, 13.0)
    clad = k.choice(pal["paintbox"] + [mul(pal["metal"], 0.9)])
    k.add(box((-W / 2, -D / 2, -0.01), (W / 2, D / 2, H)), lambda co, n, c=clad: mul(stripes(c, 0.3, 0.86, 0 if abs(n.y) > 0.5 else 1)(co, n), 0.6 + 0.4 * min(1.0, co.z / 6.0)), ao=False)
    if form == "sawtooth":
        teeth = max(3, int(W / 6.0))
        tw = W / teeth
        for i in range(teeth):
            x0 = -W / 2 + i * tw
            k.add(prism([(-D / 2, H), (D / 2, H), (D / 2, H + 0.2), (-D / 2, H + 3.2)], x0, x0 + tw, lambda a, s_, z: Vector((a, s_, z))), stripes(mul(pal["metal"], 0.8), 0.25, 0.85, 0), ao=False)
            k.add(box((x0 + 0.2, -D / 2 + 0.2, H + 0.3), (x0 + 0.4, D / 2 - 0.2, H + 2.9)), None, glow=k.pr.random() < 0.6)
    else:
        k.add(prism([(-D / 2 - 0.4, H), (D / 2 + 0.4, H), (0.0, H + 2.6)], -W / 2 - 0.3, W / 2 + 0.3, lambda a, s_, z: Vector((a, s_, z))), stripes(mul(pal["metal"], 0.75), 0.4, 0.85, 1), ao=False)
    fs = box_faces(0, 0, W / 2, D / 2)
    f = fs["front"]
    nd = max(2, int(W / 9.0))
    for i in range(nd):
        a = -W / 2 + (i + 0.5) * W / nd
        k.add(f.box(a - 2.2, a + 2.2, 0.0, 5.0, 0.0, 0.1, back=False), lambda co, n: stripes(mul(pal["metal"], 0.7), 0.2, 0.85, 2)(co, n), ao=False)
        k.add(f.box(a - 2.4, a + 2.4, 5.0, 5.3, 0.0, 0.25, back=False), hazard(tagged((0.9, 0.7, 0.1), "plastic"), tagged((0.1, 0.1, 0.1), "plastic")), ao=False)
        k.add(f.box(a - 0.4, a + 0.4, 5.5, 5.8, 0.0, 0.35, back=False), None, glow=True)
    name = k.rng.choice(BRANDS)[0] + " " + k.rng.choice(["LOGISTICS", "WORKS", "PARTS"])[:5]
    text(k, f, 0.0, H - 2.4, name[:12], 1.4, k.rng.choice(["amber", "white", "cyan"]), w=0.1)
    # Tanks and a stack beside it.
    for i in range(k.rng.choice([1, 2])):
        x = -W / 2 + 3.0 + i * 4.0
        B.cp_tank(k, P, x, D / 2 + 2.5, 0.0, 1.6, 3.0)
    sx = W / 2 - 3.0
    k.add(cyl((sx, D / 2 - 2.0, H), (sx, D / 2 - 2.0, H + 9.0), 0.8, 0.7, 10), stripes(mul(pal["metal"], 0.8), 1.2, 0.8, 2), ao=False)
    k.add(cyl((sx, D / 2 - 2.0, H + 8.5), (sx, D / 2 - 2.0, H + 8.8), 0.85, 0.85, 10), None, glow="red")


def hazard(a, b, every=0.35):
    return B.hazard(a, b, every)


def ruin(k):
    """A ruin in the wastes, by form: shell (a gutted block, its floors fallen and walls broken
    to jagged tops, rebar showing) or stump (the base of a tower, rubble round it)."""
    form = k.form
    pal = PAL
    c = k.choice(pal["concrete"])
    W, D = (k.u(12.0, 18.0), k.u(10.0, 14.0)) if form == "shell" else (k.u(14.0, 20.0), k.u(14.0, 20.0))
    t = 0.5
    n = k.rng.choice([2, 3, 4]) if form == "shell" else k.rng.choice([1, 2])
    hs = 3.3
    for side, (x0, x1, y0, y1) in enumerate(((-W / 2, W / 2, -D / 2, -D / 2 + t), (-W / 2, W / 2, D / 2 - t, D / 2), (-W / 2, -W / 2 + t, -D / 2, D / 2), (W / 2 - t, W / 2, -D / 2, D / 2))):
        cols = max(2, int(max(x1 - x0, y1 - y0) / 2.0))
        for i in range(cols):
            h = hs * n * k.u(0.3, 1.0) if k.pr.random() < 0.8 else 0.0
            if h <= 0.5:
                continue
            if x1 - x0 > y1 - y0:
                a0, a1 = x0 + i * (x1 - x0) / cols, x0 + (i + 1) * (x1 - x0) / cols
                k.add(box((a0, y0, -0.01), (a1, y1, h)), grime(c, 4.0, 0.5), ao=False)
            else:
                a0, a1 = y0 + i * (y1 - y0) / cols, y0 + (i + 1) * (y1 - y0) / cols
                k.add(box((x0, a0, -0.01), (x1, a1, h)), grime(c, 4.0, 0.5), ao=False)
            if k.pr.random() < 0.4:
                mx, my = ((a0 + a1) / 2, (y0 + y1) / 2) if x1 - x0 > y1 - y0 else ((x0 + x1) / 2, (a0 + a1) / 2)
                k.extra(cyl((mx, my, h), (mx + k.pr.uniform(-0.3, 0.3), my + k.pr.uniform(-0.3, 0.3), h + k.pr.uniform(0.5, 1.5)), 0.03, 0.03, 4), pal["rust"], ao=False)
    # A sagging floor slab and rubble heaps.
    k.add(prism([(-D / 2 + t, hs), (D / 2 - t, hs * k.u(0.3, 0.8)), (D / 2 - t, hs * k.u(0.3, 0.8) + 0.3), (-D / 2 + t, hs + 0.3)], -W / 2 + t, W / 2 * k.u(0.0, 0.6), lambda a, s_, z: Vector((a, s_, z))), mul(c, 0.85), ao=False)
    for _ in range(k.rng.choice([3, 4, 5])):
        x, y = k.u(-W / 2, W / 2), k.u(-D / 2 - 2.0, D / 2)
        k.add(sphere((x, y, 0.0), k.u(0.8, 1.8), 1, squash=0.45), mul(c, 0.8), ao=False)
    if form == "stump":
        k.add(box((-W / 2 + 2.0, -D / 2 + 2.0, -0.01), (W / 2 - 2.0, D / 2 - 2.0, hs * 0.6)), grime(mul(c, 0.8), 3.0, 0.5), ao=False)


def wall_tower(k):
    """A tower on the city wall: a square concrete tower rising above the 14 m wall, a gallery
    with a hazard band, floodlights, a searchlight, antennas and warning lights."""
    pal = PAL
    c = k.choice(pal["concrete"])
    W = k.u(9.0, 11.0)
    H = k.u(22.0, 28.0)
    k.add(box((-W / 2, -W / 2, -0.01), (W / 2, W / 2, H)), grime(c, 14.0, 0.6), ao=False)
    for zz in range(4, int(H) - 2, 4):
        k.add(box((-W / 2 - 0.08, -W / 2 - 0.08, zz), (W / 2 + 0.08, W / 2 + 0.08, zz + 0.12)), mul(c, 0.8), ao=False)
    k.add(box((-W / 2 - 1.0, -W / 2 - 1.0, H), (W / 2 + 1.0, W / 2 + 1.0, H + 0.6)), mul(pal["metal"], 0.8), ao=False)
    k.add(box((-W / 2 - 1.05, -W / 2 - 1.05, H - 0.6), (W / 2 + 1.05, W / 2 + 1.05, H)), hazard(tagged((0.9, 0.7, 0.1), "plastic"), tagged((0.1, 0.1, 0.1), "plastic"), 0.8), ao=False)
    k.add(box((-W / 2 + 0.5, -W / 2 + 0.5, H + 0.6), (W / 2 - 0.5, W / 2 - 0.5, H + 3.6)), mul(pal["dark"], 1.8), ao=False)
    for fn, f in box_faces(0, 0, W / 2 - 0.5, W / 2 - 0.5).items():
        k.add(f.quad(-f.length / 2 + 0.6, f.length / 2 - 0.6, H + 1.3, H + 2.4, 0.02), None, glow="white" if fn == "front" else True, closed=False)
    k.add(box((-W / 2 - 1.0, -W / 2 - 1.0, H + 3.6), (W / 2 + 1.0, W / 2 + 1.0, H + 4.1)), mul(pal["metal"], 0.8), ao=False)
    k.add(cyl((0, -W / 2 - 1.2, H + 4.1), (0, -W / 2 - 2.0, H + 5.1), 0.6, 0.9, 10), mul(pal["metal"], 1.2), ao=False)
    k.add(cyl((0, -W / 2 - 2.0, H + 5.1), (0, -W / 2 - 2.05, H + 5.15), 0.85, 0.85, 10), None, glow="white")
    B.cp_antenna(k, W / 2 - 1.0, W / 2 - 1.0, H + 4.1, 6.0, pal["metal"])
    for (x, y) in ((-W / 2 - 1.0, -W / 2 - 1.0), (W / 2 + 1.0, -W / 2 - 1.0), (-W / 2 - 1.0, W / 2 + 1.0), (W / 2 + 1.0, W / 2 + 1.0)):
        k.add(sphere((x, y, H + 4.4), 0.3, 1), None, glow="red")


# ---------------------------------------------------------------------------------------------
# Transport


def highway(k):
    """One 24 m piece of elevated highway along Y (its front -Y), on a central pier at its middle:
    `ring` decks are 22 m wide at 9 m, `arterial` decks 16 m wide at 17 m, so arterials pass over
    the rings. Box girders, barriers with a lit strip, lane markings, lamp masts, sign gantries
    now and then, and grime and drips under the deck."""
    pal = PAL
    form = k.form
    W, Hd = (22.0, 9.0) if form == "ring" else (16.0, 17.0)
    L = 24.0
    c = k.choice(pal["concrete"])
    # The pier: a tapered column with a hammerhead cap.
    k.add(box((-1.6, -1.4, -0.01), (1.6, 1.4, Hd - 2.6)), grime(c, Hd, 0.55), ao=False)
    k.add(prism([(-1.4, Hd - 2.6), (1.4, Hd - 2.6), (W * 0.4, Hd - 1.5), (W * 0.4, Hd - 1.2), (-W * 0.4, Hd - 1.2), (-W * 0.4, Hd - 1.5)], -1.6, 1.6,
                lambda a, s_, z: Vector((s_, a, z))), grime(mul(c, 0.95), Hd, 0.7), ao=False)
    # Girders and the deck.
    for e in (-1, 1):
        k.add(box((e * W * 0.25 - 1.6, -L / 2, Hd - 1.2), (e * W * 0.25 + 1.6, L / 2, Hd - 0.3)), mul(c, 0.85), ao=False)
    k.add(box((-W / 2, -L / 2, Hd - 0.3), (W / 2, L / 2, Hd + 0.2)), mul(c, 0.9), ao=False)
    k.add(box((-W / 2 + 0.6, -L / 2, Hd + 0.2), (W / 2 - 0.6, L / 2, Hd + 0.25)), pal["asphalt"], ao=False, vary=0.0)
    # Lane markings: dashes.
    lanes = 3 if form == "ring" else 2
    lw = (W - 2.0) / (2 * lanes)
    for side in (-1, 1):
        for li in range(1, lanes):
            x = side * li * lw
            for j in range(4):
                y0 = -L / 2 + j * 6.0 + 1.0
                k.add(box((x - 0.08, y0, Hd + 0.25), (x + 0.08, y0 + 3.0, Hd + 0.27)), pal["road_line"], ao=False, vary=0)
    # Barriers with a cold strip light, and a median barrier.
    for e in (-1, 1):
        x = e * (W / 2 - 0.3)
        k.add(box((x - 0.3, -L / 2, Hd + 0.2), (x + 0.3, L / 2, Hd + 1.1)), mul(c, 1.1), ao=False)
        k.add(box((x - 0.32 * e - 0.02, -L / 2, Hd + 0.85), (x - 0.32 * e + 0.02, L / 2, Hd + 0.95)), None, glow="white")
    k.add(box((-0.25, -L / 2, Hd + 0.2), (0.25, L / 2, Hd + 0.95)), mul(c, 1.05), ao=False)
    # Lamp masts on the median, and drips of grime under the deck edge.
    for y in (-L / 4, L / 4):
        k.add(cyl((0, y, Hd + 0.95), (0, y, Hd + 9.0), 0.12, 0.08, 6), pal["metal"], ao=False)
        for e in (-1, 1):
            k.add(box((0, y - 0.1, Hd + 8.8), (e * 3.0, y + 0.1, Hd + 9.0)), pal["metal"], ao=False)
            k.add(box((e * 2.2 - 0.5 * e - 0.25, y - 0.2, Hd + 8.6), (e * 2.2 + 0.25, y + 0.2, Hd + 8.8)), None, glow=True)
    if k.rng.random() < 0.35:
        # A sign gantry over the carriageway, with a route board.
        y = k.u(-L / 3, L / 3)
        for e in (-1, 1):
            k.add(box((e * (W / 2 - 0.6) - 0.2, y - 0.2, Hd + 1.1), (e * (W / 2 - 0.6) + 0.2, y + 0.2, Hd + 7.5)), pal["metal"], ao=False)
        k.add(box((-W / 2 + 0.6, y - 0.25, Hd + 7.0), (W / 2 - 0.6, y + 0.25, Hd + 7.6)), pal["metal"], ao=False)
        f = Face((0, y - 0.3, 0), X, W)
        k.add(f.box(-W * 0.3, W * 0.3, Hd + 4.6, Hd + 6.9, 0.0, 0.1, back=False), tagged((0.08, 0.30, 0.18), "metal"), ao=False)
        text(k, f, 0.0, Hd + 5.2, k.rng.choice(["RING 1", "RING 2", "PORT", "CORE", "GATE 3", "WEST"]), 1.1, "white", w=0.12)


# ---------------------------------------------------------------------------------------------
# Street dressing


def vending(k):
    """A bank of vending machines: glowing fronts with product rows, a logo panel, a bin."""
    pal = PAL
    n = 2 if k.form == "bank2" else 3
    for i in range(n):
        x = (i - (n - 1) / 2) * 1.0
        body = k.choice(pal["plastic"])
        k.add(box((x - 0.46, -0.4, 0.0), (x + 0.46, 0.4, 1.9)), body, ao=False)
        f = Face((x, -0.4, 0), X, 0.92)
        k.add(f.quad(-0.36, 0.2, 0.75, 1.75, 0.02), None, glow=True, closed=False)
        for r in range(4):
            k.add(f.box(-0.34, 0.18, 0.85 + r * 0.24, 0.9 + r * 0.24, 0.02, 0.05, back=False), k.choice(pal["plastic"]), ao=False, vary=0)
        k.add(f.quad(0.24, 0.4, 1.2, 1.6, 0.02), None, glow=k.choice(["cyan", "pink", "amber"]), closed=False)
        k.add(f.box(-0.36, 0.36, 0.25, 0.5, 0.0, 0.08, back=False), mul(pal["dark"], 1.5), ao=False)
        logo(k, f, 0.0, 1.82, 0.05, k.choice(BRANDS)[2], "white", w=0.0)
    k.add(cyl((n * 0.5 + 0.1, 0.0, 0.0), (n * 0.5 + 0.1, 0.0, 0.8), 0.25, 0.25, 8), mul(pal["metal"], 0.8), ao=False)


def vent(k):
    """A steam vent: a street grate with a short stack (`stack`), or a grille in a kerb box
    (`grate`); the game adds the steam."""
    pal = PAL
    if k.form == "stack":
        k.add(box((-0.7, -0.7, 0.0), (0.7, 0.7, 0.15)), mul(pal["metal"], 0.6), ao=False)
        k.add(cyl((0, 0, 0.15), (0, 0, 1.6), 0.35, 0.32, 10), stripes(mul(pal["metal"], 0.8), 0.25, 0.8, 2), ao=False)
        k.add(cyl((0, 0, 1.6), (0, 0, 1.8), 0.5, 0.5, 10), mul(pal["metal"], 0.7), ao=False)
        k.add(cyl((0, 0, 1.79), (0, 0, 1.8), 0.4, 0.4, 10), mul(pal["dark"], 1.1), ao=False)
    else:
        k.add(box((-1.0, -0.6, 0.0), (1.0, 0.6, 0.12)), mul(pal["metal"], 0.55), ao=False)
        for i in range(8):
            x = -0.85 + i * 0.24
            k.add(box((x, -0.5, 0.12), (x + 0.1, 0.5, 0.16)), mul(pal["dark"], 1.3), ao=False)


def trash(k):
    """Rubbish: bags piled against a wall (`bags`), wheelie bins (`bins`) or a heap of boxes
    and scrap (`heap`)."""
    pal = PAL
    if k.form == "bins":
        for i in range(k.rng.choice([2, 3])):
            x = (i - 1) * 0.9
            c = k.choice([tagged((0.18, 0.36, 0.22), "plastic"), tagged((0.22, 0.22, 0.26), "plastic"), tagged((0.70, 0.52, 0.12), "plastic")])
            k.add(box((x - 0.38, -0.4, 0.0), (x + 0.38, 0.4, 1.05)), c, ao=False)
            k.add(box((x - 0.42, -0.45, 1.05), (x + 0.42, 0.45, 1.15)), mul(c, 0.8), ao=False)
    else:
        for _ in range(k.rng.choice([5, 7, 9]) if k.form == "heap" else k.rng.choice([4, 6])):
            x, y = k.u(-0.9, 0.9), k.u(-0.5, 0.5)
            r = k.u(0.25, 0.45)
            c = k.choice([tagged((0.08, 0.08, 0.09), "plastic"), tagged((0.16, 0.24, 0.40), "plastic"), tagged((0.50, 0.44, 0.36), "cloth")])
            k.add(sphere((x, y, r * 0.7), r, 1, squash=0.75), c, ao=False)
        if k.form == "heap":
            for _ in range(3):
                x, y = k.u(-0.8, 0.8), k.u(-0.4, 0.4)
                k.add(box((x - 0.3, y - 0.25, 0.0), (x + 0.3, y + 0.25, 0.45)), tagged((0.56, 0.44, 0.30), "planks"), ao=False)


def barrier(k):
    """Road barriers: a run of concrete jersey blocks with hazard paint (`jersey`), steel
    bollards (`bollards`) or a police-style checkpoint barrier with a light (`checkpoint`)."""
    pal = PAL
    c = k.choice(pal["concrete"])
    if k.form == "jersey":
        for i in range(3):
            x = (i - 1) * 2.05
            k.add(prism([(-0.3, 0.0), (0.3, 0.0), (0.1, 0.3), (0.1, 0.8), (-0.1, 0.8), (-0.1, 0.3)], x - 1.0, x + 1.0, lambda a, s_, z: Vector((a, s_, z))), grime(c, 1.0, 0.7), ao=False)
            k.add(box((x - 1.0, -0.21, 0.45), (x + 1.0, -0.19, 0.6)), hazard(tagged((0.9, 0.7, 0.1), "plastic"), tagged((0.1, 0.1, 0.1), "plastic"), 0.3), ao=False)
    elif k.form == "bollards":
        for i in range(5):
            x = (i - 2) * 1.2
            k.add(cyl((x, 0, 0), (x, 0, 0.95), 0.12, 0.12, 8), mul(pal["metal"], 0.9), ao=False)
            k.add(cyl((x, 0, 0.75), (x, 0, 0.82), 0.125, 0.125, 8), None, glow="amber")
    else:
        k.add(box((-0.3, -0.3, 0.0), (0.3, 0.3, 1.1)), tagged((0.86, 0.84, 0.80), "plastic"), ao=False)
        k.add(box((0.3, -0.06, 0.85), (4.2, 0.06, 0.97)), hazard(tagged((0.85, 0.1, 0.1), "plastic"), tagged((0.95, 0.95, 0.95), "plastic"), 0.4), ao=False)
        k.add(sphere((0.0, 0.0, 1.2), 0.15, 1), None, glow="red")


def vehicle(k):
    """A parked vehicle (front -Y): a compact car, a delivery van, a motorbike or a flatbed
    truck; boxy panels, glass, a glowing light bar, wheels."""
    pal = PAL
    form = k.form
    paint = k.choice(pal["paintbox"] + [tagged((0.10, 0.10, 0.12), "metal"), tagged((0.82, 0.82, 0.80), "metal")])
    glass = pal["glass"]

    def wheels(xs, ys, r, w):
        for x in xs:
            for y in ys:
                k.add(cyl((x - w / 2, y, r), (x + w / 2, y, r), r, r, 10), mul(pal["dark"], 1.2), ao=False)

    if form == "bike":
        k.add(box((-0.15, -0.9, 0.35), (0.15, 0.9, 0.75)), paint, ao=False)
        k.add(box((-0.2, 0.0, 0.75), (0.2, 0.7, 0.9)), mul(pal["dark"], 1.4), ao=False)
        k.add(box((-0.35, -0.95, 0.95), (0.35, -0.85, 1.05)), pal["metal"], ao=False)
        k.add(sphere((0, -1.0, 0.75), 0.1, 1), None, glow="white")
        wheels([0.0], [-0.75, 0.75], 0.33, 0.12)
        return
    L, W, H, cab = {"car": (4.2, 1.8, 1.45, 0.55), "van": (5.2, 2.0, 2.3, 0.3), "truck": (7.0, 2.3, 2.6, 0.28)}[form]
    k.add(box((-W / 2, -L / 2, 0.35), (W / 2, L / 2, H * 0.62)), paint, ao=False)
    if form == "car":
        k.add(box((-W / 2 + 0.12, -L / 2 + L * 0.28, H * 0.62), (W / 2 - 0.12, L / 2 - L * 0.22, H)), paint, ao=False)
        for e in (-1, 1):
            k.add(Face((e * (W / 2 - 0.11), 0, 0), Y * e if e > 0 else -Y, L).quad(-L * 0.2, L * 0.25, H * 0.66, H * 0.95, 0.02), glass, closed=False, ao=False)
        k.add(Face((0, -L / 2 + L * 0.28 - 0.01, 0), X, W).quad(-W / 2 + 0.2, W / 2 - 0.2, H * 0.66, H * 0.95, 0.0), glass, closed=False, ao=False)
    elif form == "van":
        k.add(box((-W / 2, -L / 2 + 0.3, H * 0.62), (W / 2, L / 2, H)), paint, ao=False)
        k.add(Face((0, -L / 2 + 0.29, 0), X, W).quad(-W / 2 + 0.15, W / 2 - 0.15, H * 0.66, H * 0.92, 0.0), glass, closed=False, ao=False)
        f = Face((W / 2 + 0.01, 0, 0), Y, L)
        text(k, f, 0.4, H * 0.5, k.choice(["REPAIR", "NOODLE", "PARTS", "RENT"]), 0.45, k.choice(["cyan", "amber", "pink"]), w=0.0)
    else:
        k.add(box((-W / 2, -L / 2, H * 0.62), (W / 2, -L / 2 + 2.0, H)), paint, ao=False)
        k.add(box((-W / 2, -L / 2 + 2.2, 0.9), (W / 2, L / 2, 1.1)), mul(pal["metal"], 0.8), ao=False)
        container_box(k, 0.0, 1.0, 1.1, 4.5, True, k.choice(pal["paintbox"]))
    f = Face((0, -L / 2 - 0.01, 0), X, W)
    for e in (-1, 1):
        k.add(f.quad(e * W * 0.32 - 0.18, e * W * 0.32 + 0.18, 0.55, 0.75, 0.0), None, glow="white", closed=False)
    k.add(Face((0, L / 2 + 0.01, 0), -X, W).quad(-W * 0.45, W * 0.45, 0.6, 0.72, 0.0), None, glow="red", closed=False)
    wheels([-W / 2 + 0.15, W / 2 - 0.15], [-L * 0.32, L * 0.32], 0.36 if form == "car" else 0.45, 0.25)


def hologram(k):
    """A hologram advert: a projector on a pole (`pole`) or a ground emitter disc (`disc`)
    throwing a glowing figure, a brand mark or a spinning name, as stacked glowing slices."""
    pal = PAL
    name, col, mark = k.choice(BRANDS)
    if k.form == "pole":
        k.add(cyl((0, 0, 0), (0, 0, 5.0), 0.15, 0.1, 8), pal["metal"], ao=False)
        k.add(box((-0.4, -0.4, 5.0), (0.4, 0.4, 5.4)), mul(pal["dark"], 1.6), ao=False)
        f = Face((0, 0, 0), X, 4.0)
        logo(k, f, 0.0, 7.0, 1.2, mark, col)
        logo(k, flipped(f), 0.0, 7.0, 1.2, mark, col)
        text(k, f, 0.0, 5.6, name[:7], 0.5, col, w=0.0)
    else:
        k.add(cyl((0, 0, 0), (0, 0, 0.3), 1.2, 1.3, 16), mul(pal["metal"], 0.8), ao=False)
        k.add(cyl((0, 0, 0.3), (0, 0, 0.34), 1.0, 1.0, 16), None, glow=col)
        # A figure of light: slices of a tall ellipsoid.
        for i in range(10):
            z = 0.6 + i * 0.32
            r = 0.45 * math.sin(math.pi * (i + 0.5) / 10) + 0.1
            k.add(cyl((0, 0, z), (0, 0, z + 0.06), r, r, 12), None, glow=col if i % 3 else "white")


def scaffold(k):
    """A scaffold tower against a facade (front -Y is the street side): tube frames, boards,
    netting and a ladder, with work lights."""
    pal = PAL
    W = k.u(4.0, 8.0)
    levels = k.rng.choice([3, 4, 5, 6])
    D = 1.4
    tube = tagged((0.55, 0.56, 0.58), "metal")
    for i in range(int(W / 2.0) + 1):
        x = -W / 2 + i * W / max(1, int(W / 2.0))
        for y in (-D / 2, D / 2):
            k.add(cyl((x, y, 0), (x, y, levels * 2.0 + 1.0), 0.04, 0.04, 4), tube, ao=False)
    for lv in range(1, levels + 1):
        z = lv * 2.0
        k.add(box((-W / 2, -D / 2, z - 0.05), (W / 2, D / 2, z)), tagged((0.56, 0.44, 0.30), "planks"), ao=False)
        k.add(box((-W / 2, -D / 2 - 0.02, z + 0.95), (W / 2, -D / 2 + 0.02, z + 1.0)), tube, ao=False)
    k.add(box((-W / 2, -D / 2 - 0.05, 2.0), (W / 2, -D / 2 - 0.04, levels * 2.0 + 1.0)), tagged((0.20, 0.42, 0.40), "cloth"), ao=False)
    k.add(sphere((W / 2, -D / 2 - 0.1, levels * 2.0 + 0.8), 0.15, 1), None, glow="amber")


def crane(k):
    """A port gantry crane (`gantry`, front -Y over the water) or a tower crane over a works
    (`tower`), in hazard paint with red lights."""
    pal = PAL
    yellow = tagged((0.86, 0.62, 0.10), "metal")
    if k.form == "gantry":
        W, D, H = 18.0, 14.0, 34.0
        for x in (-W / 2, W / 2):
            for y in (-D / 2, D / 2):
                k.add(box((x - 0.6, y - 0.6, 0), (x + 0.6, y + 0.6, H)), yellow, ao=False)
            k.add(box((x - 0.5, -D / 2, H * 0.4), (x + 0.5, D / 2, H * 0.4 + 1.0)), yellow, ao=False)
        k.add(box((-W / 2 - 1.0, -D / 2 - 26.0, H), (W / 2 + 1.0, D / 2 + 8.0, H + 2.5)), yellow, ao=False)
        k.add(box((-3.0, -6.0, H - 4.0), (3.0, 2.0, H)), mul(yellow, 0.8), ao=False)
        k.add(Face((0, -6.01, 0), X, 6.0).quad(-2.5, 2.5, H - 3.5, H - 1.0, 0.0), None, glow=True, closed=False)
        for x in (-W / 2 - 1.0, W / 2 + 1.0):
            k.add(sphere((x, -D / 2 - 26.0, H + 2.7), 0.35, 1), None, glow="red")
        k.add(cyl((0, -20.0, H), (0, -20.0, H - 18.0), 0.05, 0.05, 4), pal["iron"], ao=False)
        container_box(k, 0.0, -20.0, H - 20.8, 12.2, True, k.choice(pal["paintbox"]))
        text(k, Face((0, -D / 2 - 26.0 - 0.01, 0), X, W), 0.0, H + 0.4, "PORT " + str(k.rng.randrange(1, 9)), 1.4, "white", w=0.05)
    else:
        H = k.u(40.0, 55.0)
        k.add(box((-1.2, -1.2, 0), (1.2, 1.2, H)), lambda co, n: yellow if int(co.z / 2.0) % 2 else mul(yellow, 0.7), ao=False)
        k.add(box((-4.0, -1.0, H), (30.0, 1.0, H + 1.6)), yellow, ao=False)
        k.add(box((-10.0, -1.2, H - 0.5), (-4.0, 1.2, H + 2.0)), mul(pal["metal"], 0.8), ao=False)
        k.add(box((-1.5, -1.5, H + 1.6), (1.5, 1.5, H + 4.0)), yellow, ao=False)
        k.add(sphere((30.0, 0, H + 1.8), 0.3, 1), None, glow="red")
        k.add(sphere((0, 0, H + 4.2), 0.3, 1), None, glow="red")


def salvage(k):
    """A salvage pile in the wastes: a heap of scrap, wrecked car shells and drums (`heap`), or
    a stripped vehicle wreck on blocks with a tarp (`wreck`)."""
    pal = PAL
    if k.form == "heap":
        for _ in range(k.rng.choice([6, 8, 10])):
            x, y = k.u(-3.0, 3.0), k.u(-2.5, 2.5)
            r = k.u(0.6, 1.4)
            k.add(sphere((x, y, r * 0.3), r, 1, squash=0.55), k.choice([pal["rust"], mul(pal["metal"], 0.6), tagged((0.40, 0.36, 0.30), "earth")]), ao=False)
        for _ in range(3):
            x, y = k.u(-2.5, 2.5), k.u(-2.0, 2.0)
            k.add(cyl((x, y, 0), (x, y, 0.9), 0.3, 0.3, 8), stripes(k.choice(pal["paintbox"]), 0.3, 0.8, 2), ao=False)
        x = k.u(-1.0, 1.0)
        k.add(box((x - 0.9, -0.5, 0.6), (x + 0.9, 1.8, 1.5)), mul(pal["rust"], 0.9), ao=False)
    else:
        for (x, y) in ((-0.7, -1.4), (0.7, -1.4), (-0.7, 1.4), (0.7, 1.4)):
            k.add(box((x - 0.25, y - 0.25, 0), (x + 0.25, y + 0.25, 0.4)), k.choice(pal["concrete"]), ao=False)
        k.add(box((-0.9, -2.1, 0.4), (0.9, 2.1, 1.1)), pal["rust"], ao=False)
        k.add(box((-0.8, -0.8, 1.1), (0.8, 1.2, 1.6)), mul(pal["rust"], 0.8), ao=False)
        k.add(prism([(-1.1, 1.0), (1.1, 1.0), (0.0, 2.0)], -1.2, 1.8, lambda a, s_, z: Vector((s_, a, z))), k.choice(pal["tarp"]), ao=False)


# ---------------------------------------------------------------------------------------------
# Kinds

KINDS = {
    "megatower": (megatower, ["blade", "stepped", "twin", "needle"]),
    "arcology": (arcology, ["arcology"]),
    "megablock": (megablock, ["slab", "court", "stack"]),
    "block": (B.cyber_block, ["narrow", "wide", "corner"]),
    "neon_tower": (neon_tower, ["neon"]),
    "old_block": (old_block, ["narrow", "wide"]),
    "market": (B.cyber_market, ["food_court"]),
    "shanty": (shanty, ["shack", "stack", "lean"]),
    "container": (container, ["stack2", "stack3", "home2", "home3"]),
    "warehouse": (warehouse, ["shed", "sawtooth"]),
    "workshop": (B.cyber_workshop, ["garage", "fab"]),
    "ruin": (ruin, ["shell", "stump"]),
    "wall_tower": (wall_tower, ["tower"]),
    "highway": (highway, ["ring", "arterial"]),
    "vending": (vending, ["bank2", "bank3"]),
    "vent": (vent, ["stack", "grate"]),
    "trash": (trash, ["bags", "bins", "heap"]),
    "barrier": (barrier, ["jersey", "bollards", "checkpoint"]),
    "vehicle": (vehicle, ["car", "van", "bike", "truck"]),
    "hologram": (hologram, ["pole", "disc"]),
    "scaffold": (scaffold, ["tower"]),
    "crane": (crane, ["gantry", "tower"]),
    "salvage": (salvage, ["heap", "wreck"]),
}

# The cyberpunk kit's fixed-height kinds and street props, made again in the megacity's folder
# so a city ward finds every model in one environment: kind -> (generator, height or None).
REUSE = {
    "lamp": (B.cyber_lamp, B.HEIGHTS[("cyberpunk", "lamp")]),
    "kiosk": (B.cyber_kiosk, B.HEIGHTS[("cyberpunk", "kiosk")]),
    "food_stall": (B.cyber_food_stall, B.HEIGHTS[("cyberpunk", "food_stall")]),
    "neon_sign": (B.cyber_neon_sign, B.HEIGHTS[("cyberpunk", "neon_sign")]),
    "billboard": (B.cyber_billboard, B.HEIGHTS[("cyberpunk", "billboard")]),
    "cable": (B.cyber_cable, B.HEIGHTS[("cyberpunk", "cable")]),
    "crate": (B.cyber_crate, B.HEIGHTS[("cyberpunk", "crate")]),
    "wall": (B.cyber_wall, B.HEIGHTS[("cyberpunk", "wall")]),
    "walkway": (B.cyber_walkway, B.HEIGHTS[("cyberpunk", "walkway")]),
}
REUSE_PROPS = ["barrel", "cart", "bench", "fountain", "market_cross", "planter", "banner", "washing_line", "tree", "kerb", "fence", "gate"]

FOUNDATION = {"highway": 0.6, "vending": 0.1, "vent": 0.0, "trash": 0.0, "barrier": 0.0, "vehicle": 0.0, "hologram": 0.4, "scaffold": 0.0,
              "crane": 0.8, "salvage": 0.0, "container": 0.4, "shanty": 0.4, "wall_tower": 1.8}


def build(kind, out, count, seed, only_form=None):
    os.makedirs(out, exist_ok=True)
    records = []
    if kind in KINDS:
        gen, forms = KINDS[kind]
        jobs = [(f, i) for f in forms if only_form in (None, f) for i in range(count)]
    elif kind in REUSE:
        gen, H = REUSE[kind]
        jobs = [("std", i) for i in range(count)]
    elif kind in REUSE_PROPS:
        gen, forms = B.PROPS[kind]
        jobs = [(f, i) for f in forms for i in range(min(count, B.FENCE_VARIANTS) if kind == "fence" else count)]
    else:
        sys.exit(f"unknown kind {kind}")
    for form, i in jobs:
        B.reset()
        rng = random.Random(f"{seed}-{STYLE}-{kind}-{form}-{i}")
        reuse = kind in REUSE or kind in REUSE_PROPS
        k = Kit(rng, B.PALETTES["cyberpunk"] if reuse else PAL, ao=1.2, pr=random.Random(f"detail-{seed}-{STYLE}-{kind}-{form}-{i}"))
        k.form, k.corner = form, ((1 if i % 2 == 0 else -1) if "corner" in form else 0)
        # Reused generators branch on the cyberpunk look.
        k.style = "cyberpunk" if reuse else STYLE
        if kind in REUSE:
            gen(k, H)
            B.foundation(k, B.FOUNDATION.get(kind, B.FOUNDATION_DEFAULT))
            obj, _ = k.b.finish(f"{kind}_{STYLE}_{i:02d}", height=H)
            name = f"gen-{kind}-{STYLE}-{i:02d}.glb"
        else:
            gen(k)
            B.foundation(k, FOUNDATION.get(kind, B.FOUNDATION.get(kind, B.FOUNDATION_DEFAULT)))
            obj, _ = k.b.finish(f"{kind}_{STYLE}_{form}_{i:02d}", scale=1.0)
            name = f"gen-{kind}-{STYLE}-{form}-{i:02d}.glb"
        tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
        path = os.path.join(out, name)
        import bpy
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_vertex_color="ACTIVE", export_normals=True, export_yup=True, use_selection=False)
        vs = obj.data.vertices
        fw, fd = 2 * max(abs(v.co.x) for v in vs), 2 * max(abs(v.co.y) for v in vs)
        top, below = max(v.co.z for v in vs), max(0.0, -min(v.co.z for v in vs))
        print(f"GEN {path} form={form} tris={tris} foot={fw:.2f}x{fd:.2f} h={top:.2f} below={below:.2f}")
        records.append(dict(file=name, form=form, width_m=B.up(fw), depth_m=B.up(fd), height_m=round(top, 2), foundation_m=round(below, 2), corner=k.corner, tris=tris))
    if only_form is None:
        with open(os.path.join(out, f"gen-{kind}-{STYLE}.json"), "w") as f:
            json.dump(dict(style=STYLE, kind=kind, models=records), f, indent=1)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind")
    ap.add_argument("--form")
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true", help="print every kind and exit")
    a = ap.parse_args(argv)
    if a.list:
        print("KINDS " + " ".join(list(KINDS) + list(REUSE) + REUSE_PROPS))
        return
    build(a.kind, a.out, a.count, a.seed, a.form)


if __name__ == "__main__":
    main()
