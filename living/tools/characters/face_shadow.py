#!/usr/bin/env python3
"""Designed shadows for a face type's head: planar normals and a drawn threshold map.

    python3 living/tools/characters/face_shadow.py IN.glb [OUT.glb] [--png OUT.face.png] [--sheet SHEET.jpg]

Run after face_normals.py on a file whose head is a face type's (it has the `J_Id_*` bones). It
replaces two things face_normals.py derives from an ellipsoid:

- **The face's normals** come from a planar proxy laid out from the type's landmarks: a front
  plane, side planes that break at the cheek's corner (the face's width within 0.15 H of depth),
  the nose's wedge, the planes under the nose and under the lip, the sockets, and the underside
  of the jaw (the skin under the jaw line, which the client shades by its normal: it now reads
  as one shape under the chin). Planes meet in short blends, not steps.
- **The shadow map** is built the way anime face maps are authored (docs/CHARACTER_RESEARCH.md,
  section 3): a shadow shape is drawn for each of N light angles, each drawing becomes a signed
  distance field, and the fields are interpolated into one threshold map. The shapes are drawn
  by this script from the same landmarks, in the face's front view:
    - the far side plane goes dark first, up to the cheek's corner line;
    - the edge then crosses the front following the cheek's own contour, not a vertical line,
      and below the nose it waits, so the mouth and chin keep their light longer;
    - the cheek triangle under the far eye holds its light while the shade closes round it;
    - the nose throws a wedge onto the far cheek that lengthens with the angle, and keeps its
      near side lit late;
    - between the brow and the nose's base the far half fills sooner, the edge running ahead
      to the bridge: the socket's shade;
    - a band along the far jaw rises as the light goes round.

The map's format is unchanged (face_normals.py; `face_lit` in living/game/src/toon.wesl): an RG
picture in the face texture's UV space, R the light's horizontal angle from the face's front
(0..1 for 0..180 degrees) up to which a texel stays lit for light from the face's right (+X in
the file), G the same for light from the left. Linear data. The client needs no change.

Landmarks are read from the file itself: the identity bones' bind positions (orbits, brows,
nose, mouth, chin), the eye primitive's openings and the skin's own sections, so the tool works
on a type's file and on any person of that type, composed or not. Plain Python, numpy and Pillow.
"""

import argparse
import math
import os
import sys
from array import array

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from merge_primitives import append_accessor, read_accessor, read_glb, write_glb  # noqa: E402

H = 0.2564  # a type's head in the file, chin to crown (types.json, file.head_height_m)
ANGLES = [24.0, 32.0, 40.0, 48.0, 56.0, 64.0, 72.0, 80.0, 90.0, 100.0, 112.0, 125.0, 140.0, 155.0, 168.0, 180.0]
FLOOR = 0.14  # the face is fully lit while the light is within this (of 180 degrees) of its front
PX = 0.0005  # the front view's drawing grid, metres a pixel
MAP = 512
SIDE = 36.0  # the side planes' turn from the front, degrees (see planar_normals)


def smooth(a, b, x):
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def edt(mask):
    """Each pixel's distance to the nearest True pixel (exact, two passes)."""
    h, w = mask.shape
    if not mask.any():
        return np.full((h, w), 1e6)
    big = h + w
    g = np.where(mask, 0.0, float(big))
    for y in range(1, h):
        g[y] = np.minimum(g[y], g[y - 1] + 1)
    for y in range(h - 2, -1, -1):
        g[y] = np.minimum(g[y], g[y + 1] + 1)
    xs = np.arange(w)
    d2 = (xs[:, None] - xs[None, :]) ** 2  # (x, j)
    out = np.empty((h, w))
    for y0 in range(0, h, 64):
        gg = g[y0 : y0 + 64] ** 2  # (rows, j)
        out[y0 : y0 + 64] = np.sqrt((gg[:, None, :] + d2[None, :, :]).min(axis=2))
    return out


def signed(mask):
    """Signed distance to a shape's edge in pixels: positive outside (lit), negative inside (shade)."""
    return edt(mask) - edt(~mask)


class Head:
    """A typed head's landmarks and sections, read from its file. File space: X the character's
    right, Y up, Z back (the face looks along -Z)."""

    def __init__(self, j, binary):
        mats = j["materials"]
        self.skin, self.under, eye = [], [], []
        for m in j["meshes"]:
            for p in m["primitives"]:
                name = mats[p["material"]].get("name", "")
                if name.endswith("Face_00_SKIN"):
                    self.skin.append(p)
                elif m.get("name") == "Face" and name.endswith("Body_00_SKIN"):
                    self.under.append(p)
                elif name.endswith("_EYE"):
                    eye.append(p)
        if not self.skin:
            raise ValueError("no face skin")
        names = [n.get("name") for n in j["nodes"]]
        skin = j["skins"][0]
        ibm = np.array(read_accessor(j, binary, skin["inverseBindMatrices"])[0]).reshape(-1, 4, 4).transpose(0, 2, 1)
        self.bone = {names[n]: np.linalg.inv(ibm[k])[:3, 3] for k, n in enumerate(skin["joints"])}
        if "J_Id_Orbit_L" not in self.bone:
            raise ValueError("no identity bones: this head is not a face type's")
        p = self.skin[0]
        self.pos = np.array(read_accessor(j, binary, p["attributes"]["POSITION"])[0], float).reshape(-1, 3)
        self.uv = np.array(read_accessor(j, binary, p["attributes"]["TEXCOORD_0"])[0], float).reshape(-1, 2)
        self.tris = np.concatenate([np.array(read_accessor(j, binary, q["indices"])[0], np.int64).reshape(-1, 3) for q in self.skin])
        P, T = self.pos, self.tris
        fn = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
        # Geometric normals, shared by vertices at the same place.
        _, pt = np.unique(np.round(P / 2e-5).astype(np.int64), axis=0, return_inverse=True)
        pt = pt.reshape(-1)
        acc = np.zeros((pt.max() + 1, 3))
        for k in range(3):
            np.add.at(acc, pt[T[:, k]], fn)
        self.geo = unit(acc[pt])
        used = np.zeros(len(P), bool)
        used[T.ravel()] = True
        self.used = used
        front = used & (self.geo[:, 2] < -0.2)
        self.chin = float(P[front & (np.abs(P[:, 0]) < 0.02), 1].min())
        b = self.bone
        self.eye_y = float((b["J_Id_Orbit_L"][1] + b["J_Id_Orbit_R"][1]) / 2)
        self.brow_y = float(b["J_Id_Brow_L"][1])
        self.tip_y, self.mouth_y = float(b["J_Id_NoseTip"][1]), float(b["J_Id_Mouth"][1])
        self.mouth_w = float(abs(b["J_Id_MouthCorner_L"][0]))
        # The eyes' openings, from the eye primitive (its white is cut to the lids' opening).
        ep = np.concatenate([np.array(read_accessor(j, binary, q["attributes"]["POSITION"])[0], float).reshape(-1, 3) for q in eye])
        right = ep[ep[:, 0] > 0]
        self.eye_x = float((right[:, 0].max() + right[:, 0].min()) / 2)
        self.eye_w = float((right[:, 0].max() - right[:, 0].min()) / 2)
        self.eye_h = float((right[:, 1].max() - right[:, 1].min()) / 2)
        self.eye_y = float((right[:, 1].max() + right[:, 1].min()) / 2)
        # The bridge: the front of the midline at eye height. Depth is measured back from it.
        mid = front & (np.abs(P[:, 0]) < 0.006)
        self.bridge_z = float(P[mid & (np.abs(P[:, 1] - self.eye_y) < 0.012), 2].min())
        self.tip_z = float(P[mid & (np.abs(P[:, 1] - self.tip_y) < 0.012), 2].min())
        # Under the nose: the midline's most receded point between the tip and the mouth.
        band = mid & (P[:, 1] < self.tip_y - 0.002) & (P[:, 1] > self.mouth_y + 0.004)
        self.base_y = float(P[band][np.argmax(P[band][:, 2]), 1]) if band.any() else self.tip_y - 0.03 * H
        self.nose_w = 0.50 * (self.eye_x - self.eye_w)  # half the nose's width at its wings
        # Sections by height, from the skin drawn in the front view at a millimetre a pixel: the
        # silhouette's half-width, the cheek's corner (half the width within 0.15 H of depth
        # behind the bridge) and the jaw's contour (the lowest skin in each column).
        from PIL import Image, ImageDraw

        half = float(np.abs(P[used, 0]).max()) + 0.004
        top = self.chin + H + 0.012
        w, ht = int(round(2 * half / PX)), int(round((H + 0.024) / PX))
        tri = P[T]
        facing = fn[:, 2] < 0
        near = facing & ((tri[:, :, 2].mean(axis=1) - self.bridge_z) < 0.15 * H)
        pics = []
        for sel in (facing, near):
            im = Image.new("1", (w, ht), 0)
            d = ImageDraw.Draw(im)
            for t in tri[sel]:
                d.polygon([((q[0] + half) / PX, (top - q[1]) / PX) for q in t], fill=1)
            pic = np.array(im, bool)
            pics.append(pic | pic[:, ::-1])
        xs_px = np.abs((np.arange(w) + 0.5) * PX - half)
        self.ys = top - (np.arange(ht) + 0.5) * PX
        kw = int(round(0.009 / PX)) | 1
        k = np.ones(kw) / kw
        rows = [np.where(pic.any(axis=1), (pic * xs_px[None, :]).max(axis=1), 0.0) for pic in pics]
        self.sil = np.convolve(np.pad(rows[0], kw // 2, mode="edge"), k, mode="valid")
        self.cor = np.minimum(np.convolve(np.pad(rows[1], kw // 2, mode="edge"), k, mode="valid"), self.sil)
        self.ys, self.sil, self.cor = self.ys[::-1], self.sil[::-1], self.cor[::-1]  # rising, for np.interp
        below = pics[0] & ((top - (np.arange(ht) + 0.5) * PX) < self.eye_y)[:, None]
        cols = np.arange(w // 2, w)
        self.xs = xs_px[cols]
        low = np.array([top - (np.nonzero(below[:, c])[0].max() + 1) * PX if below[:, c].any() else np.nan for c in cols])
        ok = ~np.isnan(low)
        self.low = np.interp(self.xs, self.xs[ok], low[ok])
        kj = int(round(0.007 / PX)) | 1
        self.low = np.convolve(np.pad(self.low, kj // 2, mode="edge"), np.ones(kj) / kj, mode="valid")

    def silhouette(self, y):
        return np.interp(y, self.ys, self.sil)

    def corner(self, y):
        return np.interp(y, self.ys, self.cor)

    def jaw(self, x):
        return np.interp(np.abs(x), self.xs, self.low)


# ---------------------------------------------------------------------------------------------
# The drawn shapes.


def draw_masks(h):
    """The shade drawn in the front view for light from +X at each of ANGLES: a list of boolean
    pictures (True is shade), with the grid's (x, y) of every pixel. Each is a superset of the one
    before, so a texel goes dark once."""
    from PIL import Image, ImageDraw

    x0, x1 = -h.sil.max() - 0.012, h.sil.max() + 0.012
    y0, y1 = h.chin - 0.012, h.chin + H + 0.012
    w, ht = int(round((x1 - x0) / PX)), int(round((y1 - y0) / PX))
    X = x0 + (np.arange(w) + 0.5) * PX
    Y = y1 - (np.arange(ht) + 0.5) * PX
    gx, gy = np.meshgrid(X, Y)
    sil, cor = h.silhouette(gy), np.maximum(h.corner(gy), 0.004)
    jaw = h.jaw(gx)
    ex, ey, ew, eh = h.eye_x, h.eye_y, h.eye_w, h.eye_h
    px = lambda x, y: ((x - x0) / PX, (y1 - y) / PX)

    def poly(points):
        im = Image.new("1", (w, ht), 0)
        ImageDraw.Draw(im).polygon([px(*p) for p in points], fill=1)
        return np.array(im, bool)

    # How far up the face a height lies (0 the chin, 1 the brow), for the edge's lean.
    up = np.clip((gy - h.chin) / max(h.brow_y - h.chin, 1e-6), 0.0, 1.3)
    masks = []
    for a in ANGLES:
        m = np.zeros((ht, w), bool)
        if a >= 180.0:
            masks.append(np.ones((ht, w), bool))
            continue
        # 1. The far side plane, from the silhouette in to the cheek's corner line.
        t = smooth(24.0, 42.0, a)
        m |= gx < -(sil + (cor - sil) * t) + 0.0005
        # 2. Across the front, following the cheek's own contour: the edge is the corner line
        # scaled toward the midline, leaning so it reaches the forehead a little later than the
        # mouth (a rounded brow keeps its light) and passing the midline at 90 degrees.
        # Below the nose the far half waits: the mouth and chin keep their light while the cheek
        # beside them is already dark, so the edge leaves the nose's wing and runs out and down
        # to the jaw, and is not one line down the middle of the face. It catches up past 90.
        lean = 7.0 * (up - 0.5)
        wait = 24.0 * float(smooth(118.0, 84.0, a)) * smooth(h.base_y + 0.002, h.base_y - 0.022, gy)
        f = np.clip((90.0 + lean + wait - a) / 48.0, -1.0, 1.0)  # 1 at the far corner, 0 the midline, -1 the near corner
        # Between the brow and the nose's base the far half fills sooner: the socket is set back
        # and the nose stands in the light's way, so there the edge runs ahead to the bridge
        # while the forehead and the mouth still wait. That bulge is the socket's shade.
        ahead = float(smooth(50.0, 66.0, a)) * smooth(h.brow_y + 0.022, h.brow_y - 0.004, gy) * smooth(h.base_y - 0.012, h.base_y - 0.001, gy)
        f = np.where(f > 0, f * (1 - ahead), f)
        if a >= 42.0:
            m |= gx < -cor * f
        # 3. The near side plane, from the near corner out to the silhouette.
        if a >= 138.0:
            t = smooth(138.0, 172.0, a)
            m |= gx < cor + (sil - cor) * t
        # 4. The nose's wedge on the far cheek: from the bridge's far edge down to the wing,
        # its point reaching further out and a little lower as the light goes round.
        if a >= 30.0:
            reach = min(math.tan(math.radians(min(a, 75.0))) * 0.55 * (h.bridge_z - h.tip_z + 0.006), 1.7 * h.nose_w) * float(smooth(30.0, 40.0, a))
            top = h.tip_y + 0.55 * (ey - h.tip_y)
            m |= poly([(-0.0012, top), (-h.nose_w - reach, h.base_y + 0.25 * (h.tip_y - h.base_y) - 0.15 * reach), (-0.5 * h.nose_w, h.base_y - 0.003), (0.0, h.base_y + 0.001)])
        # 5. A band along the far jaw, rising as the light goes round; the near jaw's after 100.
        band = 0.050 * H * smooth(30.0, 80.0, a) * smooth(0.0, 0.012, -gx)
        m |= (gy < jaw + band) & (gx < 0)
        if a >= 100.0:
            band = 0.050 * H * smooth(100.0, 150.0, a) * smooth(0.0, 0.012, gx)
            m |= (gy < jaw + band) & (gx > 0)
        # Holds: what keeps its light while the shade closes round it.
        # The cheek triangle under the far eye, shrinking toward its top edge until it closes.
        if a < 92.0:
            k = float(smooth(92.0, 56.0, a))  # 1 whole, 0 closed
            a1, a2 = (-(ex - 0.55 * ew), ey - 1.55 * eh), (-(ex + 0.95 * ew), ey - 1.45 * eh)
            apex = (-(ex + 0.05 * ew), ey - 1.5 * eh - k * 0.80 * (ey - 1.5 * eh - h.base_y + 0.012))
            hold = poly([a1, a2, apex]) if k > 0.02 else np.zeros((ht, w), bool)
            m &= ~hold
        # The nose's near side, lit until the light is well behind.
        if 90.0 <= a < 150.0:
            k = float(smooth(150.0, 112.0, a))
            top = h.tip_y + 0.75 * (ey - h.tip_y)
            hold = poly([(0.0008, top), (0.0008 + 0.25 * h.nose_w * k, top), (h.nose_w * k, h.base_y + 0.004), (0.0008, h.base_y + 0.002)]) if k > 0.02 else np.zeros((ht, w), bool)
            m &= ~hold
        if masks:
            m |= masks[-1]
        masks.append(m)
    return masks, (x0, y1, w, ht)


def thresholds(masks):
    """One picture of the angle (0..1 of 180 degrees) at which each pixel goes dark, by
    interpolating between the drawings' signed distance fields."""
    fields = [signed(m) for m in masks]
    out = np.full(masks[0].shape, 1.0)
    soft = 0.010 / PX  # pixels over which the first and the last drawing fade in
    done = masks[0].copy()
    out[done] = FLOOR
    for i in range(1, len(masks)):
        new = masks[i] & ~done
        a0, a1 = ANGLES[i - 1], ANGLES[i]
        d0, d1 = fields[i - 1], fields[i]
        if not masks[i - 1].any():  # nothing drawn before: fade in from the shape's own edge
            t = 1.0 - np.clip(-d1 / soft, 0.0, 1.0)
        elif masks[i].all():  # everything dark after: fade out from the last shape's edge
            t = np.clip(d0 / soft, 0.0, 1.0)
        else:
            t = np.clip(d0 / np.maximum(d0 - d1, 1e-6), 0.0, 1.0)
        out[new] = ((a0 + (a1 - a0) * t) / 180.0)[new]
        done |= masks[i]
    # The drawings are pixels: a light blur (about a millimetre) takes their steps out of the
    # field, so the edge the shader cuts from it is a clean line.
    k = np.array([1, 4, 6, 4, 1], float)
    k /= k.sum()
    for axis in (0, 1):
        pad = [(2, 2) if a == axis else (0, 0) for a in (0, 1)]
        padded = np.pad(out, pad, mode="edge")
        out = sum(k[i] * np.take(padded, np.arange(i, i + out.shape[axis]), axis=axis) for i in range(5))
    return np.clip(out, FLOOR, 1.0)


def sample(pic, frame, x, y):
    """A front-view picture at (x, y) in metres, bilinear, clamped to its edge."""
    x0, y1, w, ht = frame
    u = np.clip((x - x0) / PX - 0.5, 0, w - 1.001)
    v = np.clip((y1 - y) / PX - 0.5, 0, ht - 1.001)
    i, k = np.floor(u).astype(int), np.floor(v).astype(int)
    fu, fv = u - i, v - k
    return (pic[k, i] * (1 - fu) + pic[k, i + 1] * fu) * (1 - fv) + (pic[k + 1, i] * (1 - fu) + pic[k + 1, i + 1] * fu) * fv


def bake_map(h, th, frame, size=MAP):
    """The threshold picture into the face's UV space: (size, size, 2) for light from +X and -X.
    Where the skin turns away from the front (the sides behind the cheek, the skull) the drawn
    picture gives way to the plain rule of a round head: lit up to 90 degrees past its facing."""
    P, T, uv = h.pos, h.tris, h.uv * size
    grid = np.full((size, size, 2), np.nan)
    centre_z = h.bridge_z + 0.36 * H
    for tri in T:
        (u0, v0), (u1, v1), (u2, v2) = uv[tri]
        area = (u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0)
        if abs(area) < 1e-9:
            continue
        xa, xb = max(int(min(u0, u1, u2)) - 1, 0), min(int(max(u0, u1, u2)) + 2, size)
        ya, yb = max(int(min(v0, v1, v2)) - 1, 0), min(int(max(v0, v1, v2)) + 2, size)
        if xa >= xb or ya >= yb:
            continue
        gx, gy = np.meshgrid(np.arange(xa, xb) + 0.5, np.arange(ya, yb) + 0.5)
        b1 = ((gx - u0) * (v2 - v0) - (u2 - u0) * (gy - v0)) / area
        b2 = ((u1 - u0) * (gy - v0) - (gx - u0) * (v1 - v0)) / area
        b0 = 1 - b1 - b2
        ok = np.minimum(np.minimum(b0, b1), b2) >= -0.02
        if not ok.any():
            continue
        p = b0[..., None] * P[tri[0]] + b1[..., None] * P[tri[1]] + b2[..., None] * P[tri[2]]
        n = unit(b0[..., None] * h.geo[tri[0]] + b1[..., None] * h.geo[tri[1]] + b2[..., None] * h.geo[tri[2]])
        facing = smooth(0.12, 0.45, -n[..., 2])  # 1 where the skin faces the front
        beta = np.arctan2(p[..., 0], -(p[..., 2] - centre_z))  # the point's place round the head, + toward +X
        for c, side in ((0, 1.0), (1, -1.0)):
            drawn = sample(th, frame, side * p[..., 0], p[..., 1])
            plain = np.clip(side * beta / math.pi + 0.5, FLOOR, 1.0)
            val = drawn * facing + plain * (1 - facing)
            sub = grid[ya:yb, xa:xb, c]
            sub[ok] = val[ok]
    # Grow the covered texels outward so filtering at UV seams never reads empty ones.
    for _ in range(8):
        empty = np.isnan(grid[..., 0])
        if not empty.any():
            break
        acc, cnt = np.zeros_like(grid), np.zeros(grid.shape[:2])
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            sh = np.roll(grid, (dy, dx), axis=(0, 1))
            good = ~np.isnan(sh[..., 0])
            if dy == 1:
                good[0] = False
            if dy == -1:
                good[-1] = False
            if dx == 1:
                good[:, 0] = False
            if dx == -1:
                good[:, -1] = False
            acc[good] += sh[good]
            cnt += good
        fill = empty & (cnt > 0)
        grid[fill] = acc[fill] / cnt[fill][:, None]
    return np.nan_to_num(grid, nan=1.0)


# ---------------------------------------------------------------------------------------------
# The planar proxy's normals.


def planar_normals(h):
    """Each face-skin vertex's normal on the planar proxy (file space, unit)."""
    P = h.pos
    x, y = P[:, 0], P[:, 1]
    sx = np.where(x >= 0, 1.0, -1.0)
    cor = np.maximum(h.corner(y), 0.004)
    # Front and side planes, breaking at the cheek's corner.
    side = smooth(-0.004, 0.006, np.abs(x) - cor)
    # The side plane is turned SIDE degrees from the front, less than the skull's own side
    # (about 65): today's client looks up a face's cast shadow 12 cm out along this normal
    # (toon.wesl, `lift`), and a point 12 cm to the side of a cheek is under the hair, which put
    # a dark band along the jaw. At 36 degrees the point is in front of the face.
    az = np.radians(11.0 * np.clip(np.abs(x) / cor, 0, 1) * (1 - side) + SIDE * side)
    pitch = np.radians(-5.0 * smooth(h.tip_y, h.chin, y))  # the lower face leans back a little
    n = np.stack([sx * np.sin(az) * np.cos(pitch), np.sin(pitch), -np.cos(az) * np.cos(pitch)], axis=1)

    def lay(weight, normal):
        nonlocal n
        n = unit(n * (1 - weight[:, None]) + normal * weight[:, None])

    # Sockets: under the brow they look down, beside the bridge they look out.
    for s in (-1.0, 1.0):
        dx, dy = (x - s * h.eye_x) / (1.35 * h.eye_w), (y - h.eye_y) / np.where(y > h.eye_y, max(h.brow_y - h.eye_y, 1e-4), 1.6 * h.eye_h)
        wgt = smooth(1.0, 0.55, np.hypot(dx, dy))
        down = np.where(y > h.eye_y, -0.42, 0.12)
        lay(wgt * 0.85, unit(np.stack([s * 0.10 * np.ones_like(x), down, -np.ones_like(x)], axis=1)))
    # The nose's wedge: two side planes and a narrow ridge.
    top = h.tip_y + 0.9 * (h.eye_y - h.tip_y)
    wid = h.nose_w * (0.35 + 0.65 * smooth(top, h.tip_y, y))
    inside = smooth(1.15, 0.85, np.abs(x) / wid) * smooth(h.base_y - 0.002, h.base_y + 0.004, y) * smooth(top + 0.006, top - 0.004, y)
    ridge = smooth(0.0030, 0.0012, np.abs(x))
    wedge = unit(np.stack([sx * math.sin(math.radians(54.0)) * (1 - ridge), np.zeros_like(x), -np.ones_like(x) * (math.cos(math.radians(54.0)) * (1 - ridge) + ridge)], axis=1))
    lay(inside, wedge)
    # Under the nose, and under the lip.
    under = smooth(1.25, 0.9, np.abs(x) / h.nose_w) * smooth(h.tip_y + 0.001, h.tip_y - 0.004, y) * smooth(h.base_y - 0.006, h.base_y, y) * smooth(-0.15, -0.45, h.geo[:, 1])
    lay(under, np.tile(unit(np.array([0.0, -0.85, -0.5])), (len(x), 1)))
    lip = smooth(1.0, 0.6, np.abs(x) / max(h.mouth_w, 1e-4)) * smooth(h.mouth_y - 0.085 * H, h.mouth_y - 0.055 * H, y) * smooth(h.mouth_y - 0.018 * H, h.mouth_y - 0.034 * H, y)
    lay(lip * 0.8, np.tile(unit(np.array([0.0, -0.55, -0.83])), (len(x), 1)))
    # Above the forehead and wherever the skin turns from the front, the head's own round form.
    round_ = np.maximum(smooth(h.brow_y + 0.06 * H, h.brow_y + 0.16 * H, y), smooth(-0.25, 0.05, h.geo[:, 2]))
    lay(round_, h.geo)
    return n


def jaw_normals(j, binary, prim):
    """The skin under the jaw: one plane looking down, easing into the neck's own normals at the ring."""
    pos = np.array(read_accessor(j, binary, prim["attributes"]["POSITION"])[0], float).reshape(-1, 3)
    src = prim.get("extras", {}).get("jaw_normals_from", prim["attributes"]["NORMAL"])
    nor = np.array(read_accessor(j, binary, src)[0], float).reshape(-1, 3)
    low = pos[:, 1].min()
    w = smooth(low + 0.004, low + 0.016, pos[:, 1])
    plane = unit(np.array([0.0, -1.0, -0.04]))  # straight down: a low sun in front must not light it
    return unit(nor * (1 - w[:, None]) + plane * w[:, None]), src


# ---------------------------------------------------------------------------------------------


def write_png(path, rg):
    from PIL import Image

    size = rg.shape[0]
    img = np.zeros((size, size, 3), np.uint8)
    img[..., :2] = np.round(np.clip(rg, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(img, "RGB").save(path, optimize=True)


def sheet(path, h, masks, th, frame):
    """The drawn shapes at each angle and the map they make, to judge them as drawings."""
    from PIL import Image, ImageDraw

    x0, y1, w, ht = frame
    px = lambda x, y: ((x - x0) / PX, (y1 - y) / PX)
    ys = h.ys
    outline = [px(-h.silhouette(y), y) for y in ys if h.silhouette(y) > 0.002] + [px(h.silhouette(y), y) for y in ys[::-1] if h.silhouette(y) > 0.002]

    def face(shade):
        im = Image.new("RGB", (w, ht), (150, 165, 185))
        d = ImageDraw.Draw(im)
        d.polygon(outline, fill=(244, 214, 196))
        lit = np.array(im)
        dark = (lit * np.array([0.80, 0.70, 0.74])).astype(np.uint8)
        inside = np.all(lit == (244, 214, 196), axis=2)
        lit[inside & shade] = dark[inside & shade]
        im = Image.fromarray(lit)
        d = ImageDraw.Draw(im)
        for s in (-1, 1):
            d.ellipse([px(s * h.eye_x - h.eye_w, h.eye_y + h.eye_h), px(s * h.eye_x + h.eye_w, h.eye_y - h.eye_h)], fill=(250, 250, 250), outline=(70, 50, 45))
            d.ellipse([px(s * h.eye_x - 0.6 * h.eye_h, h.eye_y + 0.9 * h.eye_h), px(s * h.eye_x + 0.6 * h.eye_h, h.eye_y - 0.9 * h.eye_h)], fill=(70, 90, 110))
            d.line([px(s * (h.eye_x - h.eye_w), h.brow_y), px(s * (h.eye_x + h.eye_w), h.brow_y + 0.003)], fill=(90, 60, 50), width=2)
        d.line([px(-0.004, h.base_y), px(0.004, h.base_y)], fill=(170, 120, 110), width=1)
        d.line([px(-h.mouth_w, h.mouth_y), px(h.mouth_w, h.mouth_y)], fill=(170, 90, 90), width=2)
        return im

    show = [a for a in ANGLES if a < 180]
    cols = 8
    rows = (len(show) + cols - 1) // cols
    img = Image.new("RGB", (cols * w, rows * (ht + 22) + ht + 30), (246, 244, 240))
    d = ImageDraw.Draw(img)
    for k, a in enumerate(show):
        ox, oy = (k % cols) * w, (k // cols) * (ht + 22)
        img.paste(face(masks[ANGLES.index(a)]), (ox, oy))
        d.text((ox + 4, oy + ht + 3), f"drawn at {a:.0f} degrees" + (" (the light is on the face's right, the picture's left)" if k == 0 else ""), fill=(40, 40, 40))
    # The map itself, and the shade it gives at angles between the drawings.
    oy = rows * (ht + 22)
    grey = (np.clip(th, 0, 1) * 255).astype(np.uint8)
    img.paste(Image.fromarray(grey, "L").convert("RGB"), (0, oy))
    d.text((4, oy + ht + 3), "the threshold map (dark goes into shade first)", fill=(40, 40, 40))
    for k, a in enumerate((36.0, 52.0, 68.0, 85.0, 106.0, 132.0, 160.0)):
        img.paste(face(th < a / 180.0), ((k + 1) * w, oy))
        d.text(((k + 1) * w + 4, oy + ht + 3), f"from the map at {a:.0f} degrees", fill=(40, 40, 40))
    img.save(path, quality=90)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inp")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--png", help="the shadow map (default: beside OUT as <name>.face.png)")
    ap.add_argument("--sheet", help="a picture of the drawn shapes at every angle and of the map")
    ap.add_argument("--size", type=int, default=MAP)
    ap.add_argument("--if-typed", action="store_true", help="leave a file whose head is not a face type's as it is, without failing")
    a = ap.parse_args()
    out = a.out or a.inp
    png = a.png or os.path.splitext(out)[0] + ".face.png"
    j, binary = read_glb(a.inp)
    try:
        h = Head(j, binary)
    except ValueError as e:
        if a.if_typed:
            print(f"face_shadow: {a.inp}: {e}; unchanged")
            return
        raise SystemExit(f"face_shadow: {a.inp}: {e}")
    # Normals.
    n = planar_normals(h)
    src = h.skin[0].get("extras", {}).get("face_normals_from", h.skin[0]["attributes"]["NORMAL"])
    nacc = append_accessor(j, binary, array("f", n.astype(np.float32).ravel().tolist()), 5126, "VEC3", False, 34962)
    for p in h.skin:
        p.setdefault("extras", {})["face_normals_from"] = src
        p["extras"]["face_shadow"] = "planar"
        p["attributes"]["NORMAL"] = nacc
    for p in h.under:
        jn, jsrc = jaw_normals(j, binary, p)
        p.setdefault("extras", {})["jaw_normals_from"] = jsrc
        p["attributes"]["NORMAL"] = append_accessor(j, binary, array("f", jn.astype(np.float32).ravel().tolist()), 5126, "VEC3", False, 34962)
    write_glb(out, j, binary)
    # The map.
    masks, frame = draw_masks(h)
    th = thresholds(masks)
    write_png(png, bake_map(h, th, frame, a.size))
    if a.sheet:
        sheet(a.sheet, h, masks, th, frame)
    print(f"face_shadow: {out}: planar normals on {int(h.used.sum())} face vertices and {len(h.under)} jaw primitive(s); {len(ANGLES)} drawn angles into {png}")


if __name__ == "__main__":
    main()
