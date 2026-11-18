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


def clip(poly, nx, ny, limit):
    """Intersect a convex polygon with one half plane."""
    out = []
    for a, b in zip(poly[-1:] + poly[:-1], poly):
        da = a[0] * nx + a[1] * ny - limit
        db = b[0] * nx + b[1] * ny - limit
        if da * db < 0:
            t = da / (da - db)
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
        if db <= 0:
            out.append(b)
    return out


def crowns(patch, rng):
    """Partition the authored convex area into tuft territories. Scaling their two
    axes by sqrt(fill) preserves the requested area share even at clipped edges."""
    poly = patch["area"]
    xs, ys = zip(*poly)
    w, d = patch["size"]
    hedge = patch["id"].endswith("_hedge")
    nx, ny = (
        (1, math.ceil(d / 0.8)) if hedge else (math.ceil(w / 1.8), math.ceil(d / 1.8))
    )
    centres = [
        (
            min(xs) + (i + rng.uniform(0.22, 0.78)) * w / nx
            if not hedge
            else patch["at"][0],
            min(ys) + (j + rng.uniform(0.22, 0.78)) * d / ny,
        )
        for j in range(ny)
        for i in range(nx)
    ]
    # Seed crowns on the patch itself. An outside centre can claim a long,
    # millimetre-wide sliver inside a sloping edge, too thin for a leaf spray.
    inside = [
        (x, y)
        for x, y in centres
        if all(
            (b[0] - a[0]) * (y - a[1]) >= (b[1] - a[1]) * (x - a[0])
            for a, b in zip(poly, poly[1:] + poly[:1])
        )
    ]
    centres = inside or [(sum(xs) / len(xs), sum(ys) / len(ys))]
    for x, y in centres:
        cell = poly
        for u, v in centres:
            if (x, y) != (u, v):
                cell = clip(
                    cell, u - x, v - y, ((u - x) * (u + x) + (v - y) * (v + y)) / 2
                )
                if not cell:
                    break
        if len(cell) < 3:
            continue
        cx, cy = (sum(q[i] for q in cell) / len(cell) for i in range(2))
        sx, sy = patch["fill"], 1
        if not hedge:
            # Round off the corners. The area ratio compensates for the
            # removed tips and keeps the authored projected cover exactly.
            def area(points):
                return (
                    abs(
                        sum(
                            a[0] * b[1] - a[1] * b[0]
                            for a, b in zip(points, points[1:] + points[:1])
                        )
                    )
                    / 2
                )

            rounded = [
                (ax + (bx - ax) * t, ay + (by - ay) * t)
                for (ax, ay), (bx, by) in zip(cell, cell[1:] + cell[:1])
                for t in (0.2, 0.8)
            ]
            sx = sy = math.sqrt(patch["fill"] * area(cell) / area(rounded))
            cell = rounded
        yield (cx, cy), [(cx + (u - cx) * sx, cy + (v - cy) * sy) for u, v in cell]


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
