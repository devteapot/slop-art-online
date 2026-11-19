#!/usr/bin/env python3
"""Measure geometric cover on a Cullet land_dump, without range, lighting or facing.

    python3 living/tools/cullet_cover_check.py DUMP [--json]

Uses the agreed 2.5D authoring rule. Tree defaults here are fixture assumptions;
the Spark's runtime may rasterize differently.
"""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

from cullet_check import Land, in_lot, lot_poly

EYE = 1.6
MIN_FILL = 0.6
CLIFF_STEP = 2.0
TRUNK_RADIUS = 0.2
TRUNK_HEIGHT = 3.2
PLAN = Path(__file__).resolve().parents[1] / "seeds/worlds/cullet/plan.json"


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def segment_cells(a, b):
    """Yield the cell and ray interval for each positive-length crossing."""
    cuts = {0.0, 1.0}
    for start, end in zip(a, b):
        if start != end:
            for edge in range(math.floor(min(start, end)) + 1, math.ceil(max(start, end))):
                cuts.add((edge - start) / (end - start))
    cuts = sorted(cuts)
    for lo, hi in zip(cuts, cuts[1:]):
        yield tuple(map(math.floor, lerp(a, b, (lo + hi) / 2))), lo, hi


def hits(a, b, c, d):
    """Parameters of an intersection of two nonparallel finite segments."""
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = d[0] - c[0], d[1] - c[1]
    det = ux * vy - uy * vx
    if abs(det) < 1e-9:
        return None
    x, y = c[0] - a[0], c[1] - a[1]
    t, s = (x * vy - y * vx) / det, (x * uy - y * ux) / det
    if 0 <= t <= 1 and 0 <= s <= 1:
        return t, s
    return None


def contains(poly, x, y):
    return sum(
        (ay > y) != (by > y) and x < ax + (bx - ax) * (y - ay) / (by - ay)
        for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1])
    ) % 2


def bounds(points):
    xs, ys = zip(*points)
    for y in range(math.floor(min(ys)), math.ceil(max(ys))):
        for x in range(math.floor(min(xs)), math.ceil(max(xs))):
            yield x, y


class Sight:
    def __init__(self, land, plan, to_land):
        self.land = land
        self.roofs = {}
        for lot in land.lay["lots"]:
            if lot["height_m"] > 0.6 and lot["kind"] not in ("garden", "field"):
                for x, y in bounds(lot_poly(lot)):
                    if in_lot(lot, x + 0.5, y + 0.5):
                        top = lot["floor_m"] + lot["height_m"]
                        if top > self.roofs.get((x, y), (-math.inf, None))[0]:
                            self.roofs[x, y] = top, lot["key"]
        self.brush = defaultdict(list)
        for patch in plan["cover"]["brush"]:
            if patch["height_m"] < EYE or patch["fill"] < MIN_FILL:
                continue
            poly = [to_land(p) for p in patch["area"]]
            for x, y in bounds(poly):
                # Sample the part of each 1 m cell inside the polygon, then apply its fill.
                fraction = sum(contains(poly, x + (i + 0.5) / 10, y + (j + 0.5) / 10)
                               for i in range(10) for j in range(10)) / 100
                if fraction * patch["fill"] >= MIN_FILL:
                    self.brush[x, y].append((land.ht(x, y) + patch["height_m"], patch["id"]))
        self.trees = defaultdict(list)
        trees = [r for r in plan["resources"] if r["kind"] == "tree"]
        for i, tree in enumerate(trees, 1):
            x, y = to_land(tree["at"])
            r = tree.get("trunk_r_m", TRUNK_RADIUS)
            top = land.ht(x, y) + tree.get("trunk_h_m", TRUNK_HEIGHT)
            for cell in bounds([(x - r, y - r), (x + r, y + r)]):
                self.trees[cell].append(((x, y), r, top, f"tree_resource_{i}"))
        self.faces = []
        for face in plan["cover"]["cliffs"]:
            points = list(map(to_land, face["points"]))
            for a, b in zip(points, points[1:]):
                self.faces.append((a, b, face))

    def trace(self, a, b, z0, z1, target_lot=None):
        """Return baseline visibility and all added blockers on a baseline-clear ray."""
        cells = list(segment_cells(a, b))
        source, destination = tuple(map(math.floor, a)), tuple(map(math.floor, b))
        # Within one authored patch, ignore brush until the ray leaves that patch.
        common = {name for _, name in self.brush.get(source, ())}
        common &= {name for _, name in self.brush.get(destination, ())}
        for cell, _, _ in cells:
            common &= {name for _, name in self.brush.get(cell, ())}
            if not common:
                break
        blockers = {
            name for cell, eye in ((source, z0), (destination, z1))
            for top, name in self.brush.get(cell, ()) if name not in common and top > eye
        }
        for cell, lo, hi in cells:
            line = min(z0 + (z1 - z0) * lo, z0 + (z1 - z0) * hi)
            x, y = cell
            if target_lot and in_lot(target_lot, *lerp(a, b, (lo + hi) / 2)):
                break
            if cell != source and cell != destination:
                if self.land.t(x, y) in (4, 7) or self.land.ht(x, y) > line + 1e-6:
                    return False, set()
                roof = self.roofs.get(cell)
                if roof and roof[0] > line:
                    return False, set()
                for (cx, cy), r, top, name in self.trees.get(cell, ()):
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    length_sq = dx * dx + dy * dy
                    t = ((cx - a[0]) * dx + (cy - a[1]) * dy) / length_sq
                    gap = math.dist(lerp(a, b, t), (cx, cy))
                    if gap < r:
                        half = math.sqrt((r * r - gap * gap) / length_sq)
                        enter, leave = max(lo, t - half), min(hi, t + half)
                        if enter < leave and top > min(z0 + (z1 - z0) * u for u in (enter, leave)):
                            blockers.add(name)
            for top, name in self.brush.get(cell, ()):
                if name not in common and top > line:
                    blockers.add(name)
        for c, d, face in self.faces:
            cross = hits(a, b, c, d)
            if cross and 0 < cross[0] < 1:
                p = lerp(a, b, cross[0])
                dx, dy = d[0] - c[0], d[1] - c[1]
                length = math.hypot(dx, dy)
                # Sample either side beyond the quarry's roughly 1 m Drop strip.
                nx, ny = -2 * dy / length, 2 * dx / length
                heights = (self.land.ht(p[0] + nx, p[1] + ny), self.land.ht(p[0] - nx, p[1] - ny))
                height = face.get("height_m", abs(heights[0] - heights[1]))
                if height >= CLIFF_STEP and min(heights) + height > z0 + (z1 - z0) * cross[0]:
                    blockers.add(face["id"])
        # A walkable-to-walkable terrain step has the high cell's ground as its top.
        # The baseline ground test above already tests that surface on either side.
        return True, blockers


def samples(length, spacing):
    n = max(1, math.ceil(length / spacing))
    return [(i + 0.5) / n for i in range(n)]


def collect_routes(plan, to_land):
    routes = [(r["id"], r["width_m"], list(map(to_land, r["points"])), r["class"] != "path")
              for r in plan["streets"]]
    routes.extend((r["id"], r["width_m"], list(map(to_land, (r["foot"], r["head"]))), False)
                  for r in plan["stairs"])
    return routes


def route_report(sight, routes):
    segments = [(name, width, a, b) for name, width, points, _ in routes
                for a, b in zip(points, points[1:]) if a != b]
    report = defaultdict(lambda: {"rays": 0, "before": 0, "after": 0, "hidden_m2": 0.0,
                                  "strip_m2": 0.0, "losses": Counter()})
    elev = sight.land.ht
    for name, width, a, b in segments:
        row = report[name]
        length = math.dist(a, b)
        normal = (-(b[1] - a[1]) / length, (b[0] - a[0]) / length)
        cuts = {0.0, 1.0}
        for other, _, c, d in segments:
            cross = hits(a, b, c, d)
            if other != name and cross:
                cuts.add(cross[0])
        cuts = sorted(cuts)
        for lo, hi in zip(cuts, cuts[1:]):
            for t in samples(length * (hi - lo), 3):
                p = lerp(a, b, lo + t * (hi - lo))
                for end in (lo, hi):
                    q = lerp(a, b, end)
                    before, blockers = sight.trace(p, q, elev(*p) + EYE, elev(*q) + EYE)
                    row["rays"] += 1
                    row["before"] += before
                    row["after"] += before and not blockers
                    row["losses"].update(sorted(blockers))
        along, across = samples(length, 0.25), samples(width, 0.25)
        area = length * width
        hidden = 0
        for t in along:
            p = lerp(a, b, t)
            for u in across:
                q = tuple(x + dx * (u - 0.5) * width for x, dx in zip(p, normal))
                hidden += bool(sight.brush.get(tuple(map(math.floor, q))))
        row["strip_m2"] += area
        row["hidden_m2"] += area * hidden / (len(along) * len(across))
    return report


def measure(land, plan):
    ox, oy = plan["origin"]
    if plan["rotation_deg"] != 0:
        raise ValueError("expected Cullet's unrotated plan")
    def to_land(p):
        return ox + p[0], oy - p[1]

    sight = Sight(land, plan, to_land)
    routes = collect_routes(plan, to_land)
    street_points = [lerp(a, b, t) for _, _, points, in_town in routes if in_town
                     for a, b in zip(points, points[1:]) for t in samples(math.dist(a, b), 6)]
    landmarks = {}
    for lot in land.lay["lots"]:
        if lot["landmark"]:
            before = after = 0
            for a in street_points:
                clear, blockers = sight.trace(a, lot["centre"], land.ht(*a) + EYE,
                                             lot["floor_m"] + 0.9 * lot["height_m"], lot)
                before += clear
                after += clear and not blockers
            landmarks[lot["key"]] = {"before": before, "after": after, "samples": len(street_points)}
    return {"digests": land.lay["digests"], "landmarks": landmarks, "routes": route_report(sight, routes)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", help="land_dump directory")
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = parser.parse_args()
    result = measure(Land(args.dump), json.loads(args.plan.read_text()))
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print("Landmark | Without cover | With cover")
    print("--- | ---: | ---:")
    for name, row in result["landmarks"].items():
        n = row["samples"]
        print(f"{name} | {row['before']}/{n} ({row['before']/n:.1%}) | {row['after']}/{n} ({row['after']/n:.1%})")
    print("\nRoute | Clear without cover | Clear with cover | Hidden brush m² / strip m² | Added blockers")
    print("--- | ---: | ---: | ---: | ---")
    for name, row in result["routes"].items():
        flags = ", ".join(f"{key} ({n})" for key, n in row["losses"].items()) or "—"
        print(f"{name} | {row['before']}/{row['rays']} | {row['after']}/{row['rays']} | "
              f"{row['hidden_m2']:.2f} / {row['strip_m2']:.2f} | {flags}")


if __name__ == "__main__":
    main()
