#!/usr/bin/env python3
"""Check Cullet as a city from a land dump (`living/rules/examples/land_dump.rs`).

    python3 living/tools/cullet_check.py DUMP_DIR OUT_DIR [--plan living/seeds/worlds/cullet/plan.json]

Writes into OUT_DIR
- `map.png`: the land top-down, hill-shaded, tiles coloured by class, lots shaded by height;
- `town.png`: the town at 4 px a metre; `plan.svg`: the plan's lots, streets and stairs on the
  town's map with every lot id (for the contact sheet);
- `check.json`: walking routes over the hosted tiles (8-neighbour Dijkstra on walkable tiles,
  at the rules' 2.6 m/s), and for each landmark the share of street points in town that see it
  (a 3D sight line from 1.6 m above the street to 90% of its height (its lantern, cupola, rim or capstone), from 1.6 m and from the game camera's height, over the ground and the
  other lots' boxes) and the largest distance from any street point in town to it. It also gives
  the rules' 2D sight (Wall and Rock tiles block, terrace drops included) for the same points.

Standard library only.
"""
import argparse
import heapq
import json
import math
import struct
import zlib
from array import array
from pathlib import Path

WALK = 2.6
EYE = 1.6
# The game camera: 22 m from the character, 28 degrees down (camera.rs), so about 12 m above it.
CAMERA = 1.6 + 22 * math.sin(math.radians(28))
COL = {0: (128, 126, 84), 1: (70, 96, 60), 2: (40, 78, 128), 3: (214, 204, 176), 4: (96, 94, 96), 5: (120, 96, 72), 6: (66, 66, 72), 7: (40, 40, 44)}


def png(path, w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


class Land:
    def __init__(self, d):
        d = Path(d)
        self.lay = json.loads((d / "layout.json").read_text())
        self.n = self.lay["size"]
        self.tiles = (d / "tiles.u8").read_bytes()
        self.h = array("f")
        self.h.frombytes((d / "heights.f32").read_bytes())

    def t(self, x, y):
        return self.tiles[y * self.n + x] if 0 <= x < self.n and 0 <= y < self.n else 2

    def walk(self, x, y):
        # Water, Rock, Wall, and since drop-1 Drop and Low: `Terrain::walkable` (living/rules/src/map.rs).
        return self.t(x, y) not in (2, 4, 7, 8, 9)

    def ht(self, x, y):
        x = min(max(int(x), 0), self.n - 1)
        y = min(max(int(y), 0), self.n - 1)
        return self.h[y * self.n + x]


def dijkstra(L, src, goals, limit=4000.0):
    n = L.n
    dist = {}
    s = (int(src[0]), int(src[1]))
    pq = [(0.0, s)]
    want = {(int(g[0]), int(g[1])) for g in goals}
    found = {}
    while pq:
        d, (x, y) = heapq.heappop(pq)
        if (x, y) in dist or d > limit:
            continue
        dist[(x, y)] = d
        if (x, y) in want:
            found[(x, y)] = d
            if len(found) == len(want):
                break
        for dx, dy, c in ((1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1), (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)):
            q = (x + dx, y + dy)
            if q in dist or not L.walk(*q):
                continue
            if dx and dy and not (L.walk(x + dx, y) and L.walk(x, y + dy)):
                continue
            heapq.heappush(pq, (d + c, q))
    return found


def nearest_walk(L, p):
    x0, y0 = int(p[0]), int(p[1])
    for r in range(0, 12):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) == r and L.walk(x0 + dx, y0 + dy):
                    return (x0 + dx, y0 + dy)
    return (x0, y0)


def lot_poly(l):
    (cx, cy), (fx, fy) = l["centre"], l["front"]
    ux, uy = -fy, fx
    hw, hd = l["width_m"] / 2, l["depth_m"] / 2
    return [(cx + ux * a * hw + fx * b * hd, cy + uy * a * hw + fy * b * hd) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def in_lot(l, x, y):
    (cx, cy), (fx, fy) = l["centre"], l["front"]
    dx, dy = x - cx, y - cy
    return abs(dx * -fy + dy * fx) <= l["width_m"] / 2 and abs(dx * fx + dy * fy) <= l["depth_m"] / 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("out")
    ap.add_argument("--plan", default=str(Path(__file__).resolve().parents[2] / "living/seeds/worlds/cullet/plan.json"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    L = Land(a.dump)
    n = L.n
    plan = json.loads(Path(a.plan).read_text())
    O = plan["origin"]
    to_land = lambda p: (O[0] + p[0], O[1] - p[1])
    lots = L.lay["lots"]
    by_key = {l["key"]: l for l in lots if l["key"]}
    # Lot height raster (roof heights over the ground) for sight lines and shading.
    roof = {}
    for l in lots:
        if l["height_m"] <= 0.6 or l["kind"] in ("garden", "field"):
            continue
        xs = [p[0] for p in lot_poly(l)]
        ys = [p[1] for p in lot_poly(l)]
        for y in range(int(min(ys)), int(max(ys)) + 1):
            for x in range(int(min(xs)), int(max(xs)) + 1):
                if in_lot(l, x + 0.5, y + 0.5):
                    roof[(x, y)] = (l["floor_m"] + l["height_m"], l["key"])

    # ---- maps
    def shade(x, y):
        h = L.ht(x, y)
        gx = L.ht(x + 1, y) - L.ht(x - 1, y)
        gy = L.ht(x, y + 1) - L.ht(x, y - 1)
        nx, ny, nz = -gx, -gy, 2.0
        m = math.sqrt(nx * nx + ny * ny + nz * nz)
        lam = max(0.0, (nx * -0.5 + ny * -0.6 + nz * 0.62) / m)
        return h, 0.55 + 0.6 * lam

    def colour(x, y):
        t = L.t(x, y)
        h, s = shade(x, y)
        c = COL.get(t, (255, 0, 255))
        r = roof.get((x, y))
        if r:
            k = min(1.0, (r[0] - L.ht(x, y)) / 24.0)
            c = (int(150 + 80 * k), int(110 + 30 * k), int(100 + 40 * k))
            s = 1.0
        if t == 2:
            depth = max(0.0, -h)
            c = (int(40 + 60 * max(0, 1 - depth / 6)), int(78 + 70 * max(0, 1 - depth / 6)), int(128 + 50 * max(0, 1 - depth / 6)))
            s = 1.0
        elif h > 0 and int(h) % 5 == 0 and int(L.ht(x + 1, y)) != int(h):
            s *= 0.8  # 5 m contours
        return tuple(min(255, int(v * s)) for v in c)

    rgb = bytearray()
    for y in range(n):
        for x in range(n):
            rgb.extend(colour(x, y))
    png(out / "map.png", n, n, rgb)
    # The town at 3 px a metre.
    tx0, ty0, tw, th = int(O[0] - 140), int(O[1] - 210), 330, 290
    k = 3
    rgb = bytearray()
    for py in range(th * k):
        for px in range(tw * k):
            rgb.extend(colour(tx0 + px // k, ty0 + py // k))
    png(out / "town.png", tw * k, th * k, rgb)

    # SVG plan over the town image, in land metres.
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{tx0} {ty0} {tw} {th}" font-family="sans-serif">',
           f'<image href="town.png" x="{tx0}" y="{ty0}" width="{tw}" height="{th}" opacity="0.75"/>']
    for r in L.lay["roads"]:
        if r["settlement"] is None:
            continue
        pts = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in r["points"])
        svg.append(f'<polyline points="{pts}" fill="none" stroke="#3a3a44" stroke-opacity="0.55" stroke-width="{r["width_m"]}" stroke-linecap="round"/>')
    for st in plan["stairs"]:
        f, h = to_land(st["foot"]), to_land(st["head"])
        svg.append(f'<line x1="{f[0]}" y1="{f[1]}" x2="{h[0]}" y2="{h[1]}" stroke="#e0a040" stroke-width="{st["width_m"]}"/>')
    for l in lots:
        if not l["key"]:
            continue
        pts = " ".join(f"{p[0]:.2f},{p[1]:.2f}" for p in lot_poly(l))
        fill = "#c04040" if l["landmark"] else ("#8a8a90" if l["kind"] not in ("garden", "field") else "none")
        svg.append(f'<polygon points="{pts}" fill="{fill}" fill-opacity="0.8" stroke="#202024" stroke-width="0.25"><title>{l["key"]}: {l["name"] or ""} ({l["kind"]}, {l["height_m"]:.1f} m)</title></polygon>')
        c = l["centre"]
        fs = 1.4 if l["width_m"] < 6 else 2.0
        svg.append(f'<text x="{c[0]:.1f}" y="{c[1]:.1f}" font-size="{fs}" text-anchor="middle" dominant-baseline="middle" fill="#000">{l["key"]}</text>')
    svg.append("</svg>")
    (out / "plan.svg").write_text("\n".join(svg))

    # ---- walking
    def pl(key):
        return nearest_walk(L, by_key[key]["door"])
    fish = nearest_walk(L, to_land((0, 3)))
    crown = nearest_walk(L, to_land((-17.5, 136.0)))
    crown_mid = pl("readers_house")
    quay_w, quay_e = nearest_walk(L, to_land((-75, 5))), nearest_walk(L, to_land((75, 5)))
    strand_far = nearest_walk(L, to_land((-300, 38)))
    routes = {}
    d = dijkstra(L, fish, [crown, crown_mid, strand_far, pl("lintel"), pl("turf_house"), pl("hanger_cottage"), pl("watchglass"), pl("cone")])
    names = {crown: "the Crown bench (its south edge)", crown_mid: "the Readers' House (the Crown's middle)", strand_far: "the far end of the Wrack Strand", pl("lintel"): "the Lintel", pl("turf_house"): "the turf house on the Moss", pl("hanger_cottage"): "the Hanger cottage", pl("watchglass"): "the Watchglass", pl("cone"): "the Cone's mouth"}
    for q, nm in names.items():
        v = d.get(q)
        routes[f"the Fish Steps to {nm}"] = {"m": round(v, 1) if v else None, "s": round(v / WALK) if v else None, "straight_m": round(math.dist(fish, q), 1)}
    dq = dijkstra(L, quay_w, [quay_e]).get(quay_e)
    routes["the quay, end to end"] = {"m": round(dq, 1) if dq else None, "s": round(dq / WALK) if dq else None, "straight_m": round(math.dist(quay_w, quay_e), 1)}

    # ---- sight
    town_roads = [r for r in L.lay["roads"] if r["settlement"] is not None and r["class"] != "Path"]
    pts = []
    for r in town_roads:
        p = r["points"]
        for i in range(len(p) - 1):
            seg = math.dist(p[i], p[i + 1])
            m = max(1, int(seg / 6))
            for j in range(m):
                u = j / m
                pts.append((p[i][0] + (p[i + 1][0] - p[i][0]) * u, p[i][1] + (p[i + 1][1] - p[i][1]) * u))
    sight = {}
    marks = []
    for key in sorted(k for k, l in by_key.items() if l["landmark"]):
        l = by_key[key]
        c = l["centre"]
        top = l["floor_m"] + 0.9 * l["height_m"]
        seen = {"eye": 0, "camera": 0, "rules": 0}
        far = 0.0
        for p in pts:
            dd = math.dist(p, c)
            far = max(far, dd)
            g0 = L.ht(*p)
            steps = max(2, int(dd))
            ok = {"eye": True, "camera": True, "rules": True}
            for s in range(1, steps):
                u = s / steps
                x, y = p[0] + (c[0] - p[0]) * u, p[1] + (c[1] - p[1]) * u
                ix, iy = int(x), int(y)
                if in_lot(l, x, y):
                    break
                g = L.ht(x, y)
                rf = roof.get((ix, iy))
                if rf and rf[1] == key:
                    rf = None  # its own tiles: the line has arrived
                for kk, eye in (("eye", g0 + EYE), ("camera", g0 + CAMERA)):
                    line = eye + (top - eye) * u
                    if g > line or (rf and rf[0] > line):
                        ok[kk] = False
                if L.t(ix, iy) in (4, 7) and not (roof.get((ix, iy)) or (0, ""))[1] == key:
                    ok["rules"] = False
                if not any(ok.values()):
                    break
            for kk in seen:
                seen[kk] += ok[kk]
            marks.append((key, p, ok["camera"]))
        sight[key] = {"street_points": len(pts), "seen_from_eye": round(seen["eye"] / len(pts), 3), "seen_from_camera": round(seen["camera"] / len(pts), 3), "seen_rules_2d": round(seen["rules"] / len(pts), 3), "farthest_street_point_m": round(far, 1), "top_m": round(top, 1)}
    # One map per landmark: street points that see it from the camera (green) or not (red).
    for key in sorted({m[0] for m in marks}):
        c = by_key[key]["centre"]
        s2 = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{tx0} {ty0} {tw} {th}">', f'<image href="town.png" x="{tx0}" y="{ty0}" width="{tw}" height="{th}" opacity="0.6"/>']
        for k2, p, ok in marks:
            if k2 == key:
                s2.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="1.6" fill="{"#1a9a40" if ok else "#d03030"}"/>')
        s2.append(f'<circle cx="{c[0]:.1f}" cy="{c[1]:.1f}" r="4" fill="none" stroke="#000" stroke-width="1.2"/></svg>')
        (out / f"sight-{key}.svg").write_text("\n".join(s2))
    res = {"digests": L.lay["digests"], "stranded": L.lay["stranded"], "blocked_tiles": L.lay["blocked_tiles"], "cut_off_tiles": L.lay["cut_off_tiles"], "walking_m_s": WALK, "routes": routes, "landmarks": sight}
    (out / "check.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
