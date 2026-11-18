"""Derived Cullet kit fixtures, in the north-positive plan frame."""

import math
import subprocess
import sys
from array import array
from pathlib import Path
from tempfile import TemporaryDirectory


def fixtures(plan):
    for patch in plan.get("cover", {}).get("brush", []):
        xs, ys = zip(*patch["area"])
        centre = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
        yield dict(
            patch,
            what="fixture",
            at=centre,
            size=[max(xs) - min(xs), max(ys) - min(ys)],
            facing="south",
            model=f"cullet/brush/{patch['id']}.glb",
            seed=patch["id"],
        )


def area(poly):
    return (
        abs(sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(poly, poly[1:] + poly[:1])))
        / 2
    )


def clipped(poly, distance):
    """Clip vertices (x, y, field value) against one linear half-plane."""
    result = []
    for a, b in zip(poly[-1:] + poly[:-1], poly):
        da, db = distance(a), distance(b)
        if da * db < 0:
            t = da / (da - db)
            result.append(tuple(u + t * (v - u) for u, v in zip(a, b)))
        if db >= 0:
            result.append(b)
    return result


def thicket(patch, rng, field):
    """Contour a continuous field across the patch. Solve for the contour
    level whose projected triangle area gives the authored fill."""
    poly = patch["area"]
    xs, ys = zip(*poly)
    w, d = patch["size"]
    spacing = 0.88 if w * d > 25 else 0.35
    nx, ny = math.ceil(w / spacing), math.ceil(d / spacing)
    grid = []
    for j in range(ny + 1):
        row = []
        for i in range(nx + 1):
            x = min(xs) + (i + (rng.uniform(-0.25, 0.25) if 0 < i < nx else 0)) * w / nx
            y = min(ys) + (j + (rng.uniform(-0.25, 0.25) if 0 < j < ny else 0)) * d / ny
            edge = min(
                ((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]))
                / math.dist(a, b)
                for a, b in zip(poly, poly[1:] + poly[:1])
            )
            row.append((x, y, field(x, y) + min(0, edge / spacing - 0.95) * 0.7))
        grid.append(row)
    pieces = []
    for j in range(ny):
        for i in range(nx):
            quad = [grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]]
            if rng.random() < 0.5:
                quad = quad[1:] + quad[:1]
            for k in (1, 2):
                face = [quad[0], quad[k], quad[k + 1]]
                for a, b in zip(poly, poly[1:] + poly[:1]):
                    face = clipped(
                        face,
                        lambda q: (
                            (b[0] - a[0]) * (q[1] - a[1])
                            - (b[1] - a[1]) * (q[0] - a[0])
                        ),
                    )
                if len(face) >= 3 and area(face) > 1e-8:
                    pieces.append(face)
    target = area(poly) * patch["fill"]
    low, high = (
        min(q[2] for f in pieces for q in f),
        max(q[2] for f in pieces for q in f),
    )
    peak = high
    for _ in range(24):
        level = (low + high) / 2
        regions = [clipped(f, lambda q: q[2] - level) for f in pieces]
        if sum(map(area, regions)) > target:
            low = level
        else:
            high = level
    return [f for f in regions if len(f) >= 3 and area(f) > 1e-8], level, peak


def hedge_sections(patch, rng):
    """Cross sections through the field margin, with a width profile whose
    trapezoidal area is exactly the specified fraction of the polygon."""
    poly = patch["area"]
    ys = sorted({y for _, y in poly})
    stations = [ys[0]]
    for a, b in zip(ys, ys[1:]):
        count = math.ceil((b - a) / 0.20)
        stations.extend(a + (b - a) * i / count for i in range(1, count + 1))
    sections = []
    for y in stations:
        xs = []
        for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
            if ay == by == y:
                xs.extend((ax, bx))
            elif ay != by and min(ay, by) <= y <= max(ay, by):
                xs.append(ax + (bx - ax) * (y - ay) / (by - ay))
        width = max(xs) - min(xs)
        t = (y - ys[0]) / (ys[-1] - ys[0])
        fullness = 0.92 + 0.045 * math.sin(11 * t) + rng.uniform(-0.035, 0.035)
        fullness *= 0.52 + 0.48 * min(1, 8 * t, 8 * (1 - t))
        sections.append((y, min(xs), width, width * fullness))
    projected = sum(
        (b[0] - a[0]) * (a[3] + b[3]) / 2 for a, b in zip(sections, sections[1:])
    )
    scale = area(poly) * patch["fill"] / projected
    for y, left, width, rough in sections:
        span = rough * scale
        start = left + (width - span) * rng.uniform(0.2, 0.8)
        yield y, start, start + span


def terrain_sampler(plan, height_path=None):
    """Read native land_dump tile-centre heights, in plan coordinates."""
    if height_path:
        data = Path(height_path).read_bytes()
    else:
        root = Path(__file__).resolve().parents[2]
        with TemporaryDirectory(prefix="cullet-brush-") as terrain:
            subprocess.run(
                [
                    "cargo",
                    "run",
                    "--quiet",
                    "--manifest-path",
                    "living/Cargo.toml",
                    "-p",
                    "living-rules",
                    "--example",
                    "land_dump",
                    "--",
                    "living/seeds/cullet.json",
                    terrain,
                ],
                check=True,
                cwd=root,
            )
            data = (Path(terrain) / "heights.f32").read_bytes()
    heights = array("f")
    heights.frombytes(data)
    if sys.byteorder != "little":
        heights.byteswap()
    n = math.isqrt(len(heights))
    if not n or n * n != len(heights):
        raise ValueError("expected a square land_dump height field")
    ox, oy = plan["origin"]

    def ground(x, y):
        x, y = ox + x - 0.5, oy - y - 0.5
        i, j = math.floor(x), math.floor(y)
        dx, dy = x - i, y - j
        return sum(
            heights[(j + b) * n + i + a] * wx * wy
            for a, wx in enumerate((1 - dx, dx))
            for b, wy in enumerate((1 - dy, dy))
        )

    return ground
