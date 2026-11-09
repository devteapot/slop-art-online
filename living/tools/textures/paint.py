#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=2", "pillow>=10"]
# ///
"""Stylised, hand-painted, tileable textures for the game's shared toon look.

    uv run living/tools/textures/paint.py [--set ground|material|all] [--size 512] [--seed 1]
        [--out living/game/assets/textures] [--only KIND,...] [--preview SHEET.png]

Every texture is painted from the same few procedural gestures, all periodic so the image tiles
without seams:
- brush dabs: soft-edged, tapered strokes with bristle ridges, stamped by the thousand along a
  flow field (grass blades, bark fissures, leaf litter);
- shape clusters: wrapped Voronoi cells filled flat, with darkened gaps and a soft top-lit bevel
  (cobbles, flagstones, rock facets, bricks, shingles);
- soft value patches: periodic noise posterised into a few levels and blurred back, the flat
  shapes a painter blocks in before details.

The output is detail, not colour. RGB is a factor around mid-grey (128 = 1.0) that the shader
multiplies into the vertex colour, so palettes and regional colours stay as they are; values stay
within a narrow band so the toon bands and colour grading still read. Each texture may carry a
small hue of its own (warm leaves in the forest floor, cool gaps between stones). Alpha is a
height map (stones above their gaps, grass clumps above soil) for height-aware blending and puddles.
The data is linear: load it with sRGB off.

Sets:
- `ground` (the terrain material, `living/game/src/terrain.rs`; layer order is the `Layer` enum
  there): grass, lush_grass, dry_grass, forest_floor, dirt, sand, rock, cobble, flagstone, mud,
  spirit_moss, pavers (a cyberpunk town's large square panels).
- `material` (phase 2, models through the toon shader; not used yet): bark, planks, plaster,
  stone, brick, shingles, metal, leaves.

Each set is written as one vertical strip, `<set>.png` (layer k at rows k*size..), plus
`<set>.txt` naming the layers in order. The game stacks the strip into a texture array and builds
its mipmaps when it loads it. `--preview` writes a contact sheet: each texture tiled 2x2 (seams
would show at the centre), tinted by a typical colour.
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

GROUND = ["grass", "lush_grass", "dry_grass", "forest_floor", "dirt", "sand", "rock", "cobble", "flagstone", "mud", "spirit_moss", "pavers"]
MATERIAL = ["bark", "planks", "plaster", "stone", "brick", "shingles", "metal", "leaves"]

# Typical vertex colours (sRGB), only for the preview sheet.
TINT = {
    "grass": (112, 160, 74), "lush_grass": (96, 140, 70), "dry_grass": (150, 150, 96), "forest_floor": (80, 118, 62),
    "dirt": (132, 112, 80), "sand": (214, 196, 146), "rock": (128, 122, 116), "cobble": (178, 160, 120),
    "flagstone": (176, 160, 128), "mud": (100, 104, 80), "spirit_moss": (52, 92, 100), "pavers": (60, 62, 72),
    "bark": (110, 84, 62), "planks": (150, 112, 74), "plaster": (220, 210, 190), "stone": (150, 144, 134),
    "brick": (160, 84, 62), "shingles": (120, 70, 60), "metal": (120, 126, 130), "leaves": (90, 140, 70),
}


class Painter:
    """A periodic RGB canvas of factors around 0.5, plus a height channel."""

    def __init__(self, n: int, rng: np.random.Generator):
        self.n = n
        self.rng = rng
        self.rgb = np.full((n, n, 3), 0.5, np.float32)
        self.h = np.full((n, n), 0.5, np.float32)
        y, x = np.mgrid[0:n, 0:n].astype(np.float32)
        self.u, self.v = x / n, y / n

    # --- periodic fields -------------------------------------------------------------------
    def noise(self, cells: int, octaves: int = 1, gain: float = 0.5) -> np.ndarray:
        """Periodic value noise in 0..1 with `cells` lattice cells across the tile."""
        out = np.zeros((self.n, self.n), np.float32)
        amp, tot = 1.0, 0.0
        for o in range(octaves):
            c = cells * (2**o)
            g = self.rng.random((c, c)).astype(np.float32)
            x, y = self.u * c, self.v * c
            x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
            fx, fy = x - x0, y - y0
            fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
            x0 %= c
            y0 %= c
            x1, y1 = (x0 + 1) % c, (y0 + 1) % c
            a = g[y0, x0] + (g[y0, x1] - g[y0, x0]) * fx
            b = g[y1, x0] + (g[y1, x1] - g[y1, x0]) * fx
            out += amp * (a + (b - a) * fy)
            tot += amp
            amp *= gain
        return out / tot

    def blur(self, a: np.ndarray, r: float) -> np.ndarray:
        """Periodic Gaussian blur (FFT), radius in pixels."""
        if r <= 0:
            return a
        f = np.fft.fftfreq(self.n)
        k = np.exp(-2 * (math.pi * r) ** 2 * (f[:, None] ** 2 + f[None, :] ** 2)).astype(np.float32)
        if a.ndim == 3:
            return np.stack([np.real(np.fft.ifft2(np.fft.fft2(a[..., i]) * k)) for i in range(a.shape[2])], -1).astype(np.float32)
        return np.real(np.fft.ifft2(np.fft.fft2(a) * k)).astype(np.float32)

    def posterise(self, a: np.ndarray, levels: int, soft: float = 1.5) -> np.ndarray:
        """Flat painted shapes: quantise to a few levels, then soften the edges a little."""
        lo, hi = np.percentile(a, 2), np.percentile(a, 98)
        q = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 0.999)
        q = np.floor(q * levels) / max(levels - 1, 1)
        return self.blur(q, soft)

    def voronoi(self, pts: np.ndarray, aniso: tuple[float, float] = (1.0, 1.0)):
        """Wrapped Voronoi of points in 0..1: nearest index, distance to it, and to the edge.
        `aniso` stretches distances (x, y), for slabs and bricks."""
        n = self.n
        best = np.full((n, n), 1e9, np.float32)
        second = np.full((n, n), 1e9, np.float32)
        idx = np.zeros((n, n), np.int32)
        ax, ay = aniso
        for i, (px, py) in enumerate(pts):
            dx = (self.u - px + 0.5) % 1.0 - 0.5
            dy = (self.v - py + 0.5) % 1.0 - 0.5
            d = np.sqrt((dx * ax) ** 2 + (dy * ay) ** 2)
            closer = d < best
            second = np.where(closer, best, np.minimum(second, d))
            idx = np.where(closer, i, idx)
            best = np.where(closer, d, best)
        return idx, best, (second - best) * 0.5

    # --- gestures ----------------------------------------------------------------------------
    def dab(self, x: float, y: float, length: float, width: float, angle: float, color, alpha: float = 1.0, height: float | None = None, bristle: float = 0.35, taper: float = 0.6):
        """One brush stroke centred at (x, y) px: tapered, soft-edged, with bristle ridges. Wraps."""
        r = int(max(length, width) * 0.6) + 3
        ys = np.arange(int(y) - r, int(y) + r + 1)
        xs = np.arange(int(x) - r, int(x) + r + 1)
        gy, gx = np.meshgrid(ys - y, xs - x, indexing="ij")
        ca, sa = math.cos(angle), math.sin(angle)
        along = gx * ca + gy * sa
        across = -gx * sa + gy * ca
        t = along / (length * 0.5)
        # Tapered toward the tip (+t), rounder at the base.
        w = width * 0.5 * (1.0 - taper * np.clip((t + 1) * 0.5, 0, 1) ** 2)
        m = np.clip(1.0 - np.abs(t), 0, 1) ** 0.35 * np.clip(1.0 - (np.abs(across) / np.maximum(w, 0.3)) ** 2, 0, 1)
        m = np.clip(m * 1.8, 0, 1)
        if bristle > 0:
            ph = self.rng.random() * 6.28
            m *= 1.0 - bristle * (0.5 + 0.5 * np.sin(across / max(width, 1) * 9.0 + ph))
        a = (m * alpha)[..., None]
        iy, ix = ys % self.n, xs % self.n
        sub = self.rgb[np.ix_(iy, ix)]
        self.rgb[np.ix_(iy, ix)] = sub * (1 - a) + np.asarray(color, np.float32) * a
        if height is not None:
            hs = self.h[np.ix_(iy, ix)]
            self.h[np.ix_(iy, ix)] = hs * (1 - a[..., 0]) + height * a[..., 0]

    def blob(self, x: float, y: float, r: float, color, alpha: float = 1.0, height: float | None = None, soft: float = 0.35, squash: float = 1.0, angle: float = 0.0, dome: float = 0.0):
        """A soft round shape (cushion, pebble, leaf mass). `dome` lightens its upper side."""
        rr = int(r * max(1.0, 1.0 / squash)) + 3
        ys = np.arange(int(y) - rr, int(y) + rr + 1)
        xs = np.arange(int(x) - rr, int(x) + rr + 1)
        gy, gx = np.meshgrid(ys - y, xs - x, indexing="ij")
        ca, sa = math.cos(angle), math.sin(angle)
        a1 = (gx * ca + gy * sa) / r
        a2 = (-gx * sa + gy * ca) / (r * squash)
        d = np.sqrt(a1 * a1 + a2 * a2)
        m = np.clip((1.0 - d) / soft, 0, 1)
        col = np.broadcast_to(np.asarray(color, np.float32), m.shape + (3,)).copy()
        if dome:
            col = col * (1.0 + dome * np.clip(-gy / r, -1, 1)[..., None])
        a = (m * alpha)[..., None]
        iy, ix = ys % self.n, xs % self.n
        sub = self.rgb[np.ix_(iy, ix)]
        self.rgb[np.ix_(iy, ix)] = sub * (1 - a) + col * a
        if height is not None:
            hs = self.h[np.ix_(iy, ix)]
            self.h[np.ix_(iy, ix)] = np.maximum(hs, (height * (1 - d * d * 0.6)) * (m > 0)) * (m > 0) + hs * (m <= 0)

    def tone(self, factor: np.ndarray, hue=(1.0, 1.0, 1.0), amount: float = 1.0):
        """Multiply the canvas by a value field around 1, optionally tinted."""
        f = 1.0 + (factor - 1.0) * amount
        self.rgb *= f[..., None] * np.asarray(hue, np.float32) ** (factor[..., None] - 1.0)

    def finish(self, spread: float = 0.075, clip: tuple[float, float] = (0.3, 0.72)) -> np.ndarray:
        """Normalise to mean grey per channel, then fit luminance into a narrow band."""
        rgb = self.rgb / self.rgb.reshape(-1, 3).mean(0) * 0.5
        lum = rgb @ np.array([0.3, 0.59, 0.11], np.float32)
        sd = lum.std()
        k = spread / max(sd, 1e-6)
        rgb = 0.5 + (rgb - 0.5) * k
        rgb = np.clip(rgb, *clip)
        rgb = rgb / rgb.reshape(-1, 3).mean(0) * 0.5
        h = self.h
        h = (h - h.min()) / max(h.max() - h.min(), 1e-6)
        return np.dstack([np.clip(rgb, 0, 1), h])


def c(r, g, b):
    return (r, g, b)


# --- ground --------------------------------------------------------------------------------------
def grass(p: Painter, lush: float = 0.0, dry: float = 0.0):
    n = p.n
    # Blocked-in light and dark patches.
    patches = p.posterise(p.noise(8, 2, 0.55), 4, 2.5)
    p.tone(0.9 + 0.2 * patches, hue=(1.06, 1.0, 0.86))
    if dry:
        bare = p.posterise(p.noise(8, 2), 3, 2.0)
        p.tone(1.0 + 0.10 * dry * (bare > 0.7), hue=(1.25, 1.0, 0.7))
    flow = p.noise(3, 2) * 2 * math.pi
    count = int(n * n / (95 - 35 * lush + 25 * dry))
    for _ in range(count):
        x, y = p.rng.random(2) * n
        a = -math.pi / 2 + (flow[int(y), int(x)] - math.pi) * 0.35 + p.rng.normal(0, 0.35)
        light = p.rng.random()
        v = 0.38 + 0.26 * light
        # Light blades lean yellow, dark ones blue-green.
        col = c(v * (1.0 + 0.10 * (light - 0.5) + 0.12 * dry), v * (1.0 + 0.02 * (light - 0.5)), v * (1.0 - 0.18 * (light - 0.5) - 0.12 * dry))
        L = (n / 512) * p.rng.uniform(9, 20) * (1 + 0.5 * lush - 0.2 * dry)
        p.dab(x, y, L, L * p.rng.uniform(0.22, 0.34), a, col, alpha=p.rng.uniform(0.5, 0.9), height=0.4 + 0.5 * light)
    # Clumps: soft tufts, some darker and some lighter, each with a lit top.
    for _ in range(int(18 + 20 * lush)):
        x, y = p.rng.random(2) * n
        v = p.rng.choice([0.44, 0.47, 0.56])
        p.blob(x, y, n / 512 * p.rng.uniform(10, 22), c(v, v * 1.02, v * 0.96), alpha=0.22, soft=0.7, squash=0.6, dome=0.25, height=0.85)
    if lush:
        for _ in range(int(60 * lush)):
            x, y = p.rng.random(2) * n
            p.blob(x, y, n / 512 * p.rng.uniform(2.0, 3.5), c(0.62, 0.64, 0.56), alpha=0.7, soft=0.5, height=0.9)


def forest_floor(p: Painter):
    n = p.n
    # No blocked-in patches: at this tile size their lattice repeats visibly (blind A/B, 2026-11-09);
    # the macro layer in the shader varies the floor at larger scales instead.
    # Moss strokes all over, like short grass but rounder.
    for _ in range(int(n * n / 160)):
        x, y = p.rng.random(2) * n
        light = p.rng.random()
        v = 0.42 + 0.2 * light
        L = n / 512 * p.rng.uniform(6, 12)
        p.dab(x, y, L, L * 0.45, p.rng.random() * 6.28, c(v * (0.97 + 0.06 * light), v * 1.02, v * (0.98 - 0.08 * light)), alpha=0.45, bristle=0.3, height=0.4 + 0.4 * light)
    # Leaf litter in drifts: warm and olive leaves, denser where the noise says.
    drift = p.noise(5, 2)
    for _ in range(int(n * n / 650)):
        x, y = p.rng.random(2) * n
        if drift[int(y) % n, int(x) % n] < p.rng.uniform(0.35, 0.75):
            continue
        warm = p.rng.random()
        v = p.rng.uniform(0.46, 0.6)
        col = c(v * (1.0 + 0.22 * warm), v * (1.0 + 0.04 * warm), v * (1.0 - 0.3 * warm))
        r = n / 512 * p.rng.uniform(5, 9)
        p.blob(x, y, r, col, alpha=p.rng.uniform(0.55, 0.85), soft=0.35, squash=p.rng.uniform(0.38, 0.55), angle=p.rng.random() * 6.28, dome=0.12, height=0.6)
    # Moss cushions with a lit top.
    for _ in range(int(n * n / 3200)):
        x, y = p.rng.random(2) * n
        p.blob(x, y, n / 512 * p.rng.uniform(7, 13), c(0.5, 0.55, 0.47), alpha=0.45, soft=0.7, dome=0.3, height=0.85)


def dirt(p: Painter):
    n = p.n
    p.tone(0.86 + 0.28 * p.posterise(p.noise(8, 2, 0.55), 4, 2.0), hue=(1.08, 1.0, 0.92))
    # Scuffed strokes.
    for _ in range(int(n * n / 700)):
        x, y = p.rng.random(2) * n
        v = p.rng.uniform(0.42, 0.6)
        L = n / 512 * p.rng.uniform(12, 30)
        p.dab(x, y, L, L * 0.35, p.rng.random() * 6.28, c(v, v * 0.98, v * 0.95), alpha=0.35, bristle=0.5, height=0.5)
    # Pebbles.
    for _ in range(int(n * n / 1800)):
        x, y = p.rng.random(2) * n
        v = p.rng.uniform(0.5, 0.66)
        p.blob(x, y, n / 512 * p.rng.uniform(2.5, 6), c(v, v, v * 1.02), alpha=0.85, soft=0.35, squash=p.rng.uniform(0.6, 0.9), angle=p.rng.random() * 6, dome=0.3, height=0.9)
    # Dry cracks.
    crack = p.voronoi(p.rng.random((10, 2)))[2]
    p.tone(1.0 - 0.18 * np.clip(1 - crack * n / 2.2, 0, 1) * (p.noise(6) > 0.45), hue=(1.0, 0.95, 0.9))


def sand(p: Painter):
    n = p.n
    warp = p.noise(3, 2) * 1.6
    ripple = 0.5 + 0.5 * np.sin((p.v * 7 + p.u * 2 + warp) * 2 * math.pi)
    p.tone(0.94 + 0.12 * p.posterise(ripple, 3, 3.0), hue=(1.04, 1.0, 0.94))
    p.tone(0.92 + 0.16 * p.posterise(p.noise(4, 2), 3, 4.0))
    for _ in range(int(n * n / 300)):
        x, y = p.rng.random(2) * n
        v = p.rng.uniform(0.42, 0.6)
        p.blob(x, y, n / 512 * p.rng.uniform(0.8, 1.8), c(v, v, v), alpha=0.5, soft=0.6)
    p.h = 0.5 + 0.3 * ripple


def rock(p: Painter):
    n = p.n
    pts = p.rng.random((26, 2))
    idx, d, edge = p.voronoi(pts, aniso=(1.0, 1.6))
    # Each facet a flat value with a gentle painted gradient across it.
    vals = p.rng.uniform(0.8, 1.2, len(pts)).astype(np.float32)
    ang = p.rng.uniform(0, 6.28, len(pts))
    wx = (p.u - pts[idx, 0] + 0.5) % 1.0 - 0.5
    wy = (p.v - pts[idx, 1] + 0.5) % 1.0 - 0.5
    grad = np.cos(ang)[idx] * wx + np.sin(ang)[idx] * wy
    face = vals[idx] + 1.2 * grad
    p.tone(p.blur(face, 1.2), hue=(1.03, 1.0, 0.97))
    # Strata: soft horizontal bands, for the cliff faces the side projections show.
    strata = 0.5 + 0.5 * np.sin((p.v * 9 + p.noise(3) * 0.8) * 2 * math.pi)
    p.tone(0.93 + 0.14 * p.posterise(strata, 3, 2.0))
    # Cracks along facet borders, a lit lip above each.
    gap = np.clip(1.0 - edge * n / 3.0, 0, 1)
    lip = np.clip(1.0 - np.abs(edge * n - 4.5) / 2.5, 0, 1)
    p.tone(1.0 - 0.32 * gap + 0.08 * lip, hue=(0.95, 0.97, 1.08))
    # Lichen flecks.
    for _ in range(int(n * n / 3000)):
        x, y = p.rng.random(2) * n
        p.blob(x, y, n / 512 * p.rng.uniform(3, 8), c(0.56, 0.58, 0.5), alpha=0.4, soft=0.7)
    p.h = np.clip(0.3 + 0.7 * np.clip(edge * n / 10, 0, 1) + 0.15 * (face - 1), 0, 1)


def masonry(p: Painter, rows: int, widths: tuple[float, float], gap_px: float, round_px: float, bevel_px: float, var: float, mortar=(0.32, 0.31, 0.30), hue=(1.0, 1.0, 1.0), bond: float | None = None, wobble: float = 0.004, split: float = 0.0):
    """Rows of rectangular stones (setts, slabs, bricks) with rounded corners, dark gaps and a lit
    top bevel. `widths` is the stone width range (tile units); `bond` offsets every other row by
    that much (half a brick: running bond), else random; `split` is the chance a slab is cut across its height."""
    n = p.n
    u = (p.u + wobble * (p.noise(6, 2) - 0.5) * 2) % 1.0
    v = (p.v + wobble * (p.noise(6, 2) - 0.5) * 2) % 1.0
    row = np.floor(v * rows).astype(int) % rows
    fv = v * rows - np.floor(v * rows)
    ey = np.minimum(fv, 1 - fv) / rows
    ex = np.zeros_like(u)
    sid = np.zeros(u.shape, np.int64)
    for j in range(rows):
        cuts = [0.0]
        while cuts[-1] < 1.0:
            cuts.append(cuts[-1] + p.rng.uniform(*widths))
        cuts = np.array(cuts) / cuts[-1]
        off = bond * (j % 2) if bond is not None else p.rng.random()
        m = row == j
        uu = (u[m] + off) % 1.0
        k = np.clip(np.searchsorted(cuts, uu, side="right") - 1, 0, len(cuts) - 2)
        ex[m] = np.minimum(uu - cuts[k], cuts[k + 1] - uu)
        sid[m] = j * 1000 + k
        if split:
            cut_h = p.rng.random(len(cuts)) < split
            half = np.abs(fv[m] - 0.5) / rows
            ey_m = ey[m]
            ey[m] = np.where(cut_h[k], np.minimum(ey_m, half), ey_m)
            sid[m] = sid[m] + np.where(cut_h[k] & (fv[m] > 0.5), 500, 0)
    ex, ey = ex * n, ey * n
    r = round_px
    qx, qy = np.maximum(r - ex, 0), np.maximum(r - ey, 0)
    e = np.minimum(ex, ey)
    e = np.where((qx > 0) & (qy > 0), r - np.sqrt(qx * qx + qy * qy), e)
    ids, inv = np.unique(sid, return_inverse=True)
    inv = inv.reshape(sid.shape)
    vals = p.rng.uniform(1 - var, 1 + var, len(ids)).astype(np.float32)
    hues = p.rng.normal(0, 0.03, (len(ids), 3)).astype(np.float32)
    inside = np.clip((e - gap_px * 0.5) / 1.5, 0, 1)
    face = vals[inv][..., None] * (1 + hues[inv]) * np.asarray(hue, np.float32)
    gy = (np.roll(e, -1, 0) - np.roll(e, 1, 0)) * 0.5
    gx = (np.roll(e, -1, 1) - np.roll(e, 1, 1)) * 0.5
    bevel = np.clip(1 - (e - gap_px * 0.5) / bevel_px, 0, 1) * np.clip(gy * 0.8 + gx * 0.4, -1, 1)
    face = face * (1 + 0.18 * bevel)[..., None]
    face = face * (0.94 + 0.12 * p.posterise(p.noise(12, 2), 3, 1.5))[..., None]
    rgb = face * 0.5 * inside[..., None] + np.asarray(mortar, np.float32) * (1 - inside[..., None])
    p.rgb = p.blur(rgb, 0.6)
    p.h = np.clip((e - gap_px * 0.5) / (bevel_px * 1.6), 0, 1) ** 0.6 * 0.9 + 0.1 * (vals[inv] - 1) / max(var, 1e-3)


def cobble(p: Painter):
    s = p.n / 512
    masonry(p, rows=10, widths=(0.075, 0.12), gap_px=5 * s, round_px=11 * s, bevel_px=12 * s, var=0.13, wobble=0.006)
    for _ in range(int(p.n * p.n / 4000)):
        x, y = p.rng.random(2) * p.n
        p.blob(x, y, s * p.rng.uniform(2, 5), c(0.4, 0.43, 0.36), alpha=0.35, soft=0.8)


def flagstone(p: Painter):
    s = p.n / 512
    masonry(p, rows=4, widths=(0.2, 0.42), gap_px=4 * s, round_px=6 * s, bevel_px=10 * s, var=0.09, mortar=(0.34, 0.33, 0.31), wobble=0.005, split=0.3)
    # Worn scuffs.
    for _ in range(int(p.n * p.n / 2500)):
        x, y = p.rng.random(2) * p.n
        L = s * p.rng.uniform(20, 45)
        p.dab(x, y, L, L * 0.4, p.rng.random() * 6.28, c(0.55, 0.54, 0.52), alpha=0.18, bristle=0.6)
    # Hairline cracks.
    crack = p.voronoi(p.rng.random((8, 2)))[2] * p.n
    p.tone(1 - 0.16 * np.clip(1 - crack / 1.2, 0, 1) * (p.noise(5) > 0.62))


def mud(p: Painter):
    n = p.n
    base = p.posterise(p.noise(6, 2, 0.6), 4, 3.0)
    p.tone(0.92 + 0.14 * base, hue=(1.05, 1.0, 0.9))
    # Wet sheen: lighter, cooler smears where the ground is lowest.
    low = base < 0.35
    p.tone(1.0 + 0.08 * p.blur(low.astype(np.float32), 4.0), hue=(0.92, 1.0, 1.12))
    # Trampled ridges.
    for _ in range(int(n * n / 900)):
        x, y = p.rng.random(2) * n
        L = n / 512 * p.rng.uniform(14, 34)
        v = p.rng.uniform(0.4, 0.58)
        p.dab(x, y, L, L * 0.3, p.rng.normal(0.3, 0.5), c(v, v * 0.98, v * 0.9), alpha=0.4, bristle=0.4, height=0.6)
    # A few reed and grass blades at the edges of dry patches.
    for _ in range(int(n * n / 1600)):
        x, y = p.rng.random(2) * n
        if base[int(y), int(x)] < 0.6:
            continue
        L = n / 512 * p.rng.uniform(10, 18)
        p.dab(x, y, L, L * 0.25, -math.pi / 2 + p.rng.normal(0, 0.4), c(0.55, 0.6, 0.45), alpha=0.7, height=0.8)
    p.h = np.clip(0.2 + 0.8 * base, 0, 1)


def spirit_moss(p: Painter):
    n = p.n
    p.tone(0.88 + 0.2 * p.posterise(p.noise(6, 2, 0.55), 3, 3.0), hue=(0.92, 1.03, 1.1))
    # Cushions of moss, soft and domed, overlapping.
    for _ in range(int(n * n / 1500)):
        x, y = p.rng.random(2) * n
        r = n / 512 * p.rng.uniform(7, 18)
        v = p.rng.uniform(0.44, 0.6)
        p.blob(x, y, r, c(v * 0.95, v * 1.02, v * 1.05), alpha=0.85, soft=0.45, dome=0.28, height=0.6 + 0.4 * p.rng.random())
    # Fine fronds on the cushions.
    for _ in range(int(n * n / 320)):
        x, y = p.rng.random(2) * n
        L = n / 512 * p.rng.uniform(4, 8)
        v = p.rng.uniform(0.45, 0.62)
        p.dab(x, y, L, L * 0.4, p.rng.random() * 6.28, c(v, v * 1.03, v * 1.06), alpha=0.45, bristle=0.2)
    # Pale spore specks (light, a little cyan).
    for _ in range(int(n * n / 1100)):
        x, y = p.rng.random(2) * n
        p.blob(x, y, n / 512 * p.rng.uniform(1.2, 2.4), c(0.68, 0.74, 0.76), alpha=0.8, soft=0.5, height=1.0)


def pavers(p: Painter):
    """Large square panels in a grid, crisp joints, stains and patched slabs."""
    s = p.n / 512
    masonry(p, rows=3, widths=(1 / 3, 1 / 3), gap_px=3 * s, round_px=2 * s, bevel_px=4 * s, var=0.06, mortar=(0.36, 0.36, 0.37), bond=0.0, wobble=0.0005)
    # Saw-cut lines across some panels.
    lines = (np.abs(((p.u * 6) % 1.0) - 0.5) > 0.497) & (p.noise(3) > 0.55)
    p.tone(1 - 0.12 * p.blur(lines.astype(np.float32), 0.6))
    # Stains and wear, soft.
    p.tone(0.95 + 0.1 * p.posterise(p.noise(6, 2), 3, 3.0), hue=(0.98, 1.0, 1.03))
    for _ in range(int(p.n * p.n / 5000)):
        x, y = p.rng.random(2) * p.n
        p.blob(x, y, s * p.rng.uniform(6, 16), c(0.44, 0.44, 0.45), alpha=0.2, soft=0.9, squash=0.7, angle=p.rng.random() * 6)


# --- material (phase 2) --------------------------------------------------------------------------
def bark(p: Painter):
    n = p.n
    p.tone(0.86 + 0.28 * p.posterise(p.noise(3, 2), 3, 3.0))
    # Long vertical plates and dark fissures (stretched noise).
    plates = p.voronoi(p.rng.random((22, 2)), aniso=(1.0, 0.18))[2] * n
    p.tone(1.0 - 0.35 * np.clip(1 - plates / 3.5, 0, 1), hue=(1.05, 0.98, 0.92))
    for _ in range(int(n * n / 500)):
        x, y = p.rng.random(2) * n
        L = n / 512 * p.rng.uniform(20, 50)
        v = p.rng.uniform(0.42, 0.6)
        p.dab(x, y, L, L * 0.12, math.pi / 2 + p.rng.normal(0, 0.06), c(v, v * 0.97, v * 0.93), alpha=0.4, bristle=0.5)
    p.h = np.clip(plates / 12, 0, 1)


def planks(p: Painter):
    n = p.n
    boards = 6
    row = np.floor(p.v * boards).astype(int)
    off = p.rng.random(boards)[row]
    vals = p.rng.uniform(0.88, 1.12, boards)[row]
    grain = 0.5 + 0.5 * np.sin((p.v * boards * 3.0 + p.noise(4, 2) * 1.5 + off * 7) * 2 * math.pi * 2.0)
    p.tone(vals * (0.93 + 0.14 * p.posterise(grain, 4, 1.0)), hue=(1.04, 1.0, 0.94))
    seam = np.abs(((p.v * boards) % 1.0) - 0.5) * 2
    gap = np.clip((seam - 0.94) / 0.04, 0, 1)
    # End joints, staggered per board.
    ends = np.abs(((p.u + off) * 2 % 1.0) - 0.5) * 2
    gap = np.maximum(gap, np.clip((ends - 0.985) / 0.01, 0, 1))
    p.tone(1 - 0.4 * gap)
    # Knots.
    for _ in range(6):
        x, y = p.rng.random(2) * n
        p.blob(x, y, n / 512 * p.rng.uniform(4, 7), c(0.36, 0.33, 0.3), alpha=0.7, soft=0.6, squash=0.6)
    p.h = 1 - gap


def plaster(p: Painter):
    n = p.n
    p.tone(0.9 + 0.2 * p.posterise(p.noise(3, 3, 0.55), 4, 5.0))
    for _ in range(int(n * n / 600)):
        x, y = p.rng.random(2) * n
        L = n / 512 * p.rng.uniform(20, 50)
        v = p.rng.uniform(0.46, 0.56)
        p.dab(x, y, L, L * 0.5, p.rng.random() * 6.28, c(v, v, v * 0.98), alpha=0.25, bristle=0.4)
    # Patches where the stone shows through, and hairline cracks.
    show = p.noise(5, 2) > 0.8
    p.tone(1 - 0.12 * p.blur(show.astype(np.float32), 1.5), hue=(1.05, 1.0, 0.9))
    crack = p.voronoi(p.rng.random((6, 2)))[2] * n
    p.tone(1 - 0.2 * np.clip(1 - crack / 1.2, 0, 1) * (p.noise(5) > 0.6))


def ashlar(p: Painter):
    s = p.n / 512
    masonry(p, rows=5, widths=(0.22, 0.36), gap_px=4 * s, round_px=7 * s, bevel_px=9 * s, var=0.12, wobble=0.003)


def brick(p: Painter):
    s = p.n / 512
    masonry(p, rows=12, widths=(0.25, 0.25), gap_px=5 * s, round_px=3 * s, bevel_px=5 * s, var=0.12, mortar=(0.62, 0.6, 0.56), hue=(1.04, 0.98, 0.95), bond=0.125, wobble=0.0015)


def shingles(p: Painter):
    n = p.n
    rows, cols = 8, 6
    img = np.zeros((n, n, 3), np.float32)
    hgt = np.zeros((n, n), np.float32)
    # Rows overlap from the top down: each tile a rounded-bottom shape, darker under the one above.
    for j in range(rows):
        for i in range(cols):
            cx = (i + 0.5 * (j % 2) + 0.5) / cols
            cy = (j + 1.0) / rows
            dx = (p.u - cx + 0.5) % 1.0 - 0.5
            dy = (p.v - cy + 0.5) % 1.0 - 0.5
            w = 0.5 / cols
            m = (np.abs(dx) < w * 0.96) & (dy < 0) & (dy > -1.0 / rows) | ((dx / w) ** 2 + (dy * rows * 3) ** 2 < 0.92) & (dy >= 0)
            v = p.rng.uniform(0.85, 1.15)
            shade = 1.0 - 0.25 * np.clip(-dy * rows, 0, 1)
            img = np.where(m[..., None], v * shade[..., None] * 0.5, img)
            hgt = np.where(m, 1 - np.clip(-dy * rows, 0, 1), hgt)
    p.rgb = p.blur(img, 0.7) + 0.0
    p.rgb = np.where(p.rgb < 0.05, 0.3, p.rgb)
    p.h = hgt


def metal(p: Painter):
    n = p.n
    streak = p.blur(p.rng.random((n, n)).astype(np.float32), 0.5)
    streak = np.mean([np.roll(streak, k, axis=1) for k in range(0, 40, 2)], axis=0)
    p.tone(0.94 + 0.12 * (streak - streak.mean()) / max(streak.std(), 1e-6) * 0.3)
    patina = p.posterise(p.noise(4, 3), 3, 3.0)
    p.tone(1.0 + 0.1 * (patina - 0.5), hue=(0.9, 1.05, 1.08))
    # Panel seams and rivets.
    seam = (np.abs((p.u * 2 % 1.0) - 0.5) > 0.495) | (np.abs((p.v * 2 % 1.0) - 0.5) > 0.495)
    p.tone(1 - 0.3 * p.blur(seam.astype(np.float32), 0.8))
    for j in range(4):
        for i in range(16):
            x, y = (i + 0.5) / 16 * n, ((j // 2) * 0.5 + (0.03 if j % 2 == 0 else 0.47)) * n
            p.blob(x, y, n / 512 * 3.0, c(0.62, 0.62, 0.62), alpha=0.9, soft=0.4, dome=0.4, height=1.0)


def leaves(p: Painter):
    n = p.n
    p.tone(0.8 + 0.3 * p.posterise(p.noise(3, 2), 3, 3.0))
    for _ in range(int(n * n / 140)):
        x, y = p.rng.random(2) * n
        v = p.rng.uniform(0.38, 0.64)
        warm = p.rng.random() * 0.3
        r = n / 512 * p.rng.uniform(6, 12)
        p.blob(x, y, r, c(v * (1 + warm * 0.3), v * 1.03, v * (1 - warm)), alpha=0.95, soft=0.25, squash=0.45, angle=p.rng.random() * 6.28, dome=0.3, height=v)


PAINT = {
    "grass": lambda p: grass(p),
    "lush_grass": lambda p: grass(p, lush=1.0),
    "dry_grass": lambda p: grass(p, dry=1.0),
    "forest_floor": forest_floor,
    "dirt": dirt,
    "sand": sand,
    "rock": rock,
    "cobble": cobble,
    "flagstone": flagstone,
    "mud": mud,
    "spirit_moss": spirit_moss,
    "pavers": pavers,
    "bark": bark,
    "planks": planks,
    "plaster": plaster,
    "stone": ashlar,
    "brick": brick,
    "shingles": shingles,
    "metal": metal,
    "leaves": leaves,
}

# How far each texture's luminance spreads (the narrow band), by kind.
SPREAD = {"pavers": 0.06, "spirit_moss": 0.085, "sand": 0.045, "plaster": 0.05, "metal": 0.05, "mud": 0.07, "cobble": 0.09, "flagstone": 0.08, "rock": 0.09, "brick": 0.09, "shingles": 0.09}


def paint(kind: str, size: int, seed: int) -> np.ndarray:
    # Each kind its own stream, so adding a kind never changes the others.
    rng = np.random.default_rng([seed, sum(ord(ch) * 131**i for i, ch in enumerate(kind)) % (2**31)])
    p = Painter(size, rng)
    PAINT[kind](p)
    return p.finish(SPREAD.get(kind, 0.075))


def to_u8(a: np.ndarray) -> np.ndarray:
    return (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)


def preview(kinds: list[str], images: dict[str, np.ndarray], out: Path):
    cell = 256
    cols = 4
    rows = (len(kinds) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (cell + 8), rows * (cell + 26)), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    for k, kind in enumerate(kinds):
        a = images[kind][..., :3]
        tiled = np.tile(a, (2, 2, 1))
        tint = np.asarray(TINT.get(kind, (160, 160, 160)), np.float32) / 255.0
        lin = (tint**2.2) * tiled * 2.0
        srgb = np.clip(lin, 0, 1) ** (1 / 2.2)
        im = Image.fromarray(to_u8(srgb)).resize((cell, cell), Image.LANCZOS)
        x, y = (k % cols) * (cell + 8) + 4, (k // cols) * (cell + 26) + 22
        sheet.paste(im, (x, y))
        draw.text((x, y - 16), kind, fill=(230, 230, 230))
    sheet.save(out)


def main():
    root = Path(__file__).resolve().parents[3]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", choices=["ground", "material", "all"], default="ground")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=str(root / "living/game/assets/textures"))
    ap.add_argument("--only", default="", help="comma-separated kinds (preview only; strips need the whole set)")
    ap.add_argument("--preview", default="", help="write a contact sheet here")
    a = ap.parse_args()
    sets = {"ground": GROUND, "material": MATERIAL}
    chosen = list(sets) if a.set == "all" else [a.set]
    only = [k for k in a.only.split(",") if k]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    images: dict[str, np.ndarray] = {}
    shown: list[str] = []
    for s in chosen:
        kinds = [k for k in sets[s] if not only or k in only]
        for kind in kinds:
            images[kind] = paint(kind, a.size, a.seed)
            shown.append(kind)
        if not only:
            strip = np.concatenate([to_u8(images[k]) for k in kinds], axis=0)
            Image.fromarray(strip, "RGBA").save(out / f"{s}.png", optimize=True)
            (out / f"{s}.txt").write_text("\n".join(kinds) + "\n")
            print(f"{s}: {len(kinds)} layers of {a.size} px -> {out / (s + '.png')}")
    if a.preview:
        preview(shown, images, Path(a.preview))
        print(f"preview -> {a.preview}")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONHASHSEED", "0")
    main()
