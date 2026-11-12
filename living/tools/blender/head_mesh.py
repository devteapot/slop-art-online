"""The head's mesh and the face's parts, as plain arrays. numpy only (no Blender).

person.py turns this into the `Face` object. The construction follows what the VRoid controls
showed (docs/CHARACTERS.md, "What was learnt from VRoid"), built here from nothing of theirs:

- **Skin:** a cube-sphere projected onto the head's form (head_form.py), denser toward the face.
- **Eye openings:** real holes. The skin round each eye is cut away and stitched to a clean ring of
  vertices on the lids' line, with a rim turned inward for the lids' thickness. Behind each
  opening sits a shallow bowl that carries the painted eye (white, iris, pupil, highlights, the
  lid's shadow: face_paint.py), so the eye is set back and the lids pass in front of it.
- **Lashes, lid lines and brows:** thin vector shapes standing just off the skin, coloured per
  vertex. They stay crisp at any distance and need no blending.
- **Mouth:** the skin is slit along the line between the lips. The lower edge drops with the jaw
  and shows the mouth's inside: teeth, the dark, the tongue.
- **Expressions:** the whole face is built again for each expression's state (lids, jaw, mouth
  corners, brows); the difference from the neutral face is the morph target, under VRoid's names.

All positions are in the head's own frame (head_form.py). UVs are Blender's (v up) into one
square atlas: the eyes' strip along the top, the skin below it, mapped by direction from the
head's middle with more texels given to the front.
"""

import math
import random

import numpy as np

from head_form import ORIGIN, lerp, smooth

ATLAS = 1024
EYE_ROWS = 192  # the eyes' strip, at the top of the atlas
EYE_COLS = 320  # each eye's white; then the iris's square, then a swatch of plain skin
IRIS_COL0, IRIS_PX = 2 * EYE_COLS, EYE_ROWS  # the iris both eyes share
IRIS_FILL = 0.47  # the iris's half height, as a share of its square
EYE_R = 0.080  # the radius of the ball an eye's white and iris lie on, m: about the face's own curve
K_AZ, K_EL, EL0 = 1.5, 0.7, -0.05
CUTS, WARP = 30, (0.0, 0.28, -0.34)  # the cube's front face runs from the brows to under the lip

# Expressions: VRoid's morph names and the face's state for each (everything else stays 0).
EXPRESSIONS = {
    "Fcl_EYE_Close": dict(blink_l=1, blink_r=1),
    "Fcl_EYE_Close_L": dict(blink_l=1),
    "Fcl_EYE_Close_R": dict(blink_r=1),
    "Fcl_EYE_Joy": dict(joy=1),
    "Fcl_MTH_A": dict(mouth=0.0095),
    "Fcl_MTH_I": dict(mouth=0.0030, wide=0.14),
    "Fcl_MTH_U": dict(mouth=0.0045, wide=-0.30),
    "Fcl_MTH_E": dict(mouth=0.0055, wide=0.10),
    "Fcl_MTH_O": dict(mouth=0.0085, wide=-0.22),
    "Fcl_MTH_Fun": dict(smile=0.0034, wide=0.10),
    "Fcl_MTH_Sorrow": dict(smile=-0.0030, wide=-0.04),
    "Fcl_BRW_Angry": dict(brow_in=-0.0042, brow_out=0.0022),
    "Fcl_BRW_Sorrow": dict(brow_in=0.0040, brow_out=-0.0024),
    "Fcl_BRW_Surprised": dict(brow_in=0.0048, brow_out=0.0048),
    "Fcl_BRW_Fun": dict(brow_in=0.0020, brow_out=0.0026),
}


def _g(t, k):
    return (1 + k) * t / (1 + k * np.abs(t))


def _gi(u, k):
    return u / (1 + k - k * np.abs(u))


def skin_uv(p):
    """Atlas UVs of points on the head, from their direction out of its middle."""
    d = np.asarray(p, float) - ORIGIN
    d = d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
    az = np.arctan2(-d[:, 0], d[:, 1]) / math.pi
    el = np.arcsin(np.clip(d[:, 2], -1, 1)) / (math.pi / 2)
    u = 0.5 + 0.5 * _g(az, K_AZ)
    t = 0.5 + 0.5 * _g(np.clip(el - EL0, -1, 1), K_EL)
    return np.stack([u, t * (1 - EYE_ROWS / ATLAS)], axis=1)


def skin_dirs(cols, rows):
    """The direction each texel of a cols×rows picture of the skin's region looks along (row 0 at
    the top), as rows×cols×3."""
    u = (np.arange(cols) + 0.5) / cols
    t = 1 - (np.arange(rows) + 0.5) / rows
    az = _gi(2 * u - 1, K_AZ) * math.pi
    el = (np.clip(_gi(2 * t - 1, K_EL) + EL0, -1, 1)) * (math.pi / 2)
    az, el = np.meshgrid(az, el)
    return np.stack([-np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el)], axis=2)


def eye_frame(hf):
    """How an eye's rectangle of the atlas maps the front view: the height (relative to eye_z) of
    its middle, and pixels per metre."""
    s = np.linspace(-1, 1, 41)
    up, lo = hf.lid(s)
    mid = (up.max() + lo.min()) / 2
    hh = (up.max() - lo.min()) / 2 + 0.0030
    hw = 1.10 * hf.eye_w + 0.0030
    return mid, min(EYE_COLS / (2 * hw), EYE_ROWS / (2 * hh))


def eye_uv(hf, side, x, z):
    """Atlas UVs of front-view points for the eye on `side` (-1 the character's left)."""
    mid, scale = eye_frame(hf)
    col = (0 if side < 0 else EYE_COLS) + EYE_COLS / 2 + (np.asarray(x) - side * hf.eye_x) * scale
    row = EYE_ROWS / 2 - (np.asarray(z) - hf.eye_z - mid) * scale
    return np.stack([col / ATLAS, 1 - row / ATLAS], axis=1)


SWATCH_UV = ((IRIS_COL0 + IRIS_PX + ATLAS) / 2 / ATLAS, 1 - EYE_ROWS / 2 / ATLAS)  # plain skin (ears)
IRIS_WIDE = 0.88  # the iris is taller than wide, as drawn eyes are


def iris_centre(hf, side):
    """Where the iris sits in the front view when the eye looks ahead: (x, z)."""
    up0, lo0 = hf.lid(np.array(0.0))
    r = hf.iris_r
    return side * (hf.eye_x - 0.035 * hf.eye_w), hf.eye_z + min(float(up0) - 0.74 * r, float(lo0) + 0.97 * r)


def eye_ball(hf, side):
    """The ball an eye's white and iris lie on: its centre, set so the ball passes at least 2 mm
    behind the skin everywhere in the opening. The eye's bone sits at the centre, so turning the
    bone slides the iris over the white."""
    cx, cz = iris_centre(hf, side)
    s = np.linspace(-1, 1, 15)
    up, lo = hf.lid(s)
    pts = [(side * (hf.eye_x + hf.eye_w * a), hf.eye_z + b) for a, b in zip(s, up)] + [(side * (hf.eye_x + hf.eye_w * a), hf.eye_z + b) for a, b in zip(s, lo)] + [(cx, cz)]
    p, n = hf.project_front(pts)
    axis = n.mean(axis=0)
    axis /= np.linalg.norm(axis)
    depth = 0.0024
    for _ in range(40):
        c = p[-1] - axis * (EYE_R + depth)
        if (np.linalg.norm(p - c, axis=1) - EYE_R).min() >= 0.0020:
            break
        depth += 0.0003
    return c


def glints(hs, n=14):
    """The eye's highlights, in iris radii from the iris's centre: (x, z, the outline's offsets).
    One large oval high on the lit side, leaning, reaching over the iris's rim, as the reference
    has it; a small round one low on the other side."""
    out = []
    for hx, hz, rx, rz, lean in ((0.46 * hs, 0.50, 0.33, 0.20, 28.0 * hs), (-0.34 * hs, -0.46, 0.085, 0.075, 0.0)):
        c, s_ = math.cos(math.radians(lean)), math.sin(math.radians(lean))
        ring = [(rx * math.cos(2 * math.pi * i / n) * c - rz * math.sin(2 * math.pi * i / n) * s_, rx * math.cos(2 * math.pi * i / n) * s_ + rz * math.sin(2 * math.pi * i / n) * c) for i in range(n)]
        out.append((hx, hz, ring))
    return out


def on_ball(c, x, z, lift=0.0):
    """Points of an eye's ball (or `lift` outside it) seen at front-view (x, z)."""
    x, z = np.asarray(x, float), np.asarray(z, float)
    r = EYE_R
    y = c[1] + np.sqrt(np.maximum(r * r - (x - c[0]) ** 2 - (z - c[2]) ** 2, 1e-9))
    p = np.stack([x, y, z], axis=1)
    if lift:
        p = p + (p - c) / r * lift
    return p


def turn(p, c, yaw, pitch):
    """Points turned about an eye's centre: yaw degrees toward the character's left, pitch up."""
    if not yaw and not pitch:
        return p
    a, b = math.radians(yaw), math.radians(pitch)
    rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    return c + (p - c) @ (rz @ rx).T


def cube_sphere(n, warp):
    """Unit directions of a cube-sphere with n quads along each edge, pulled toward `warp`, its
    quads, and the front face's vertex grid [i][k] (i across from the character's right to left
    … in +X to -X order reversed: i grows with +X; k grows upward)."""
    index, dirs, quads = {}, [], []

    def vid(i, j, k):
        key = (i, j, k)
        if key not in index:
            index[key] = len(dirs)
            dirs.append([math.tan((2 * c / n - 1) * math.pi / 4) for c in key])
        return index[key]

    for axis in range(3):
        for side in (0, n):
            for a in range(n):
                for b in range(n):
                    c = [(a, b), (a + 1, b), (a + 1, b + 1), (a, b + 1)]
                    quads.append([vid(*(p[:axis] + (side,) + p[axis:])) for p in c])
    d = np.array(dirs)
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    d = d + np.array(warp)
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    front = [[index[(i, n, k)] for k in range(n + 1)] for i in range(n + 1)]
    return d, quads, front


class Mesh:
    """Geometry in progress: positions, per-vertex colours (sRGB) and UVs, faces with a material key."""

    def __init__(self):
        self.v, self.col, self.uv, self.f, self.fm, self.eye = [], [], [], [], [], []

    def add(self, pts, cols, uvs, faces, mat, facing=None, eye=None):
        """`eye`: (side, weight) for vertices that follow an eye's bone; the rest follow the head."""
        """`facing(centre, normal)` says whether a face looks the right way; others are turned."""
        base = len(self.v)
        pts = [tuple(float(c) for c in p) for p in pts]
        self.v += pts
        self.eye += [eye] * len(pts)
        self.col += [tuple(cols)] * len(pts) if isinstance(cols[0], (int, float)) else [tuple(c) for c in cols]
        self.uv += [(0.0, 0.0)] * len(pts) if uvs is None else [tuple(float(c) for c in t) for t in uvs]
        for f in faces:
            if facing is not None:
                q = np.array([pts[i] for i in f])
                nrm = np.cross(q[1] - q[0], q[2] - q[0])
                if not facing(q.mean(axis=0), nrm):
                    f = tuple(reversed(f))
            self.f.append(tuple(base + i for i in f))
            self.fm.append(mat)
        return base


def _loops(edges):
    """Chain directed-less boundary edges into closed loops of vertex ids."""
    nbr = {}
    for a, b in edges:
        nbr.setdefault(a, []).append(b)
        nbr.setdefault(b, []).append(a)
    loops, seen = [], set()
    for start in nbr:
        if start in seen:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nxt = [x for x in nbr[cur] if x != prev]
            nxt = [x for x in nxt if x not in seen] or [x for x in nxt if x == start]
            if not nxt or nxt[0] == start:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            loop.append(cur)
        loops.append(loop)
    return loops


def _zipper(outer, inner, xy):
    """Triangles filling the ring between two loops that run the same way round, by always
    taking the shorter of the two possible next edges. xy: every vertex's front-view position."""
    m, k = len(outer), len(inner)
    d = lambda a, b: float(np.hypot(*(xy[a] - xy[b])))
    # Start from the closest pair.
    i0, j0 = min(((i, j) for i in range(m) for j in range(k)), key=lambda t: d(outer[t[0]], inner[t[1]]))
    outer, inner = outer[i0:] + outer[:i0], inner[j0:] + inner[:j0]
    area = lambda a, b, c: float(np.cross(xy[b] - xy[a], xy[c] - xy[a]))
    tris, i, j = [], 0, 0
    while i < m or j < k:
        a, b = outer[i % m], inner[j % k]
        o, n = outer[(i + 1) % m], inner[(j + 1) % k]
        take_outer = j >= k or (i < m and d(o, b) <= d(a, n))
        # Never a triangle folded over (both loops run anticlockwise, the outer one outside).
        if i < m and j < k:
            if take_outer and area(a, o, b) <= 0 < area(a, n, b):
                take_outer = False
            elif not take_outer and area(a, n, b) <= 0 < area(a, o, b):
                take_outer = True
        if take_outer:
            tris.append((a, o, b))
            i += 1
        else:
            tris.append((a, n, b))
            j += 1
    return tris


class Face:
    """One person's head: the neutral mesh and its expressions.

    hf: head_form.Head. look: colours and line weights (person.py's `look()`): skin, skin_shade,
    lash, brow, lash_k (the lash line's weight), lash_wing, lashes (how many), fold (the lid
    fold's strength), lower (the lower lid line's strength). keep(centre) says which of the
    scalp's quads to keep (the rest are under the hair)."""

    RING = 34  # vertices round each eye's opening
    RIM = 0.0024  # how far the lids' rim turns in, m
    BOWL = 0.0026  # how far the eye sits behind the skin, m

    def __init__(self, hf, look, keep=None):
        self.hf, self.look = hf, look
        dirs, quads, front = cube_sphere(CUTS, WARP)
        self.base_pos = ORIGIN + dirs * hf.radius(dirs)[:, None]
        self.base_quads = quads  # the whole head before any cutting: hair and beards build on it
        self.balls = {side: eye_ball(hf, side) for side in (-1, 1)}
        self._topology(front, keep)
        neutral = self.build(dict(look=look.get("gaze", (0.0, 0.0))))
        self.mesh = neutral
        self.morphs = {}
        v0 = np.array(neutral.v)
        for name, state in EXPRESSIONS.items():
            m = self.build(dict(state, look=look.get("gaze", (0.0, 0.0))))
            assert len(m.v) == len(neutral.v), name
            self.morphs[name] = np.array(m.v) - v0

    # ---------------------------------------------------------------------------- the skin

    def _topology(self, front, keep):
        hf = self.hf
        pos = [p.copy() for p in self.base_pos]
        quads = [list(q) for q in self.base_quads]
        n = CUTS
        self._front, self._mouth_cols = front, None
        # The mouth: the grid row nearest the line between the lips is laid on it, and split.
        mid = n // 2
        row = min(range(n + 1), key=lambda k: abs(pos[front[mid][k]][2] - hf.mouth_z))
        mw = hf.mouth_w
        ids = [front[i][row] for i in range(n + 1)]
        xs = np.array([pos[v][0] for v in ids])
        near = [i for i in range(n + 1) if abs(xs[i]) < mw + 0.004]
        ends = (min(near, key=lambda i: abs(xs[i] + mw)), min(near, key=lambda i: abs(xs[i] - mw)))
        lo_i, hi_i = min(ends), max(ends)
        self.mouth_up, self.mouth_lo = [], []
        row = min(max(row, 2), n - 2)
        for i in range(lo_i, hi_i + 1):
            # Spread evenly between the corners, so a vertex sits on each corner.
            x = lerp(-mw, mw, (i - lo_i) / (hi_i - lo_i))
            zl = float(hf.mouth_line(np.array([x]))[0])
            # The rows above and below make room for the moved row.
            for sign, reach in ((-1, min(4, row)), (1, min(4, n - row))):
                far = pos[front[i][row + sign * reach]]
                for dk in range(1, reach):
                    t = dk / reach
                    pos[front[i][row + sign * dk]] = hf.project_front([(lerp(x, far[0], t), lerp(zl, far[2], t))])[0][0]
            p = hf.project_front([(x, zl)])[0][0]
            pos[ids[i]] = p
            if lo_i < i < hi_i:
                pos.append(p.copy())
                self.mouth_up.append(ids[i])
                self.mouth_lo.append(len(pos) - 1)
        lower = dict(zip(self.mouth_up, self.mouth_lo))
        below = {front[i][row - 1] for i in range(n + 1)}
        for q in quads:
            if any(v in below for v in q) and any(v in lower for v in q):
                q[:] = [lower.get(v, v) for v in q]
        # The eyes: cut the skin away round each opening and stitch it to a ring on the lids.
        p_arr = np.array(pos)
        tris = []
        self.rings = {}
        for side in (-1, 1):
            inside, _, _, _ = hf.eye_inside(p_arr[:, 0], p_arr[:, 2], grow=0.0028)
            inside &= (p_arr[:, 1] > 0) & (p_arr[:, 0] * side > 0)
            gone = [any(inside[v] for v in q) for q in quads]
            count = {}
            for q, g in zip(quads, gone):
                for a, b in zip(q, q[1:] + q[:1]):
                    e = (min(a, b), max(a, b))
                    c = count.setdefault(e, [0, 0])
                    c[1 if g else 0] += 1
            edges = [e for e, (kept, cut) in count.items() if kept and cut]
            loops = _loops(edges)
            outer = max(loops, key=len)
            quads = [q for q, g in zip(quads, gone) if not g]
            # The ring: upper lid from the inner corner out, then the lower lid back.
            k = self.RING // 2
            s_up = [-math.cos(math.pi * i / k) for i in range(k + 1)]
            s_lo = [math.cos(math.pi * i / k) for i in range(1, k)]
            ring = [(s, True) for s in s_up] + [(s, False) for s in s_lo]
            first = len(pos)
            cz = float(np.mean([hf.lid(0.0)[0], hf.lid(0.0)[1]])) + hf.eye_z
            centre = np.array([side * hf.eye_x, cz])
            pts = [self._lid_point(side, s, upper, {}) for s, upper in ring]
            pp = hf.project_front(pts)[0]
            pos += [p for p in pp]
            p_arr = np.array(pos)

            inner = list(range(first, first + len(ring)))

            def turning(loop):
                """A loop running anticlockwise in the front view."""
                a = np.arctan2(p_arr[loop, 2] - centre[1], p_arr[loop, 0] - centre[0])
                return loop if np.diff(np.unwrap(np.append(a, a[0]))).sum() > 0 else loop[::-1]

            tris += _zipper(turning(list(outer)), turning(inner), p_arr[:, [0, 2]])
            self.rings[side] = dict(first=first, ring=ring)
        self.skin_n = len(pos)
        self.skin_pos = np.array(pos)
        self.skin_uvs = skin_uv(self.skin_pos)
        self.skin_normals = hf.normal(self.skin_pos)
        # A beard is the skin itself standing off the face (its hairs are painted): thick for a
        # full beard, which also hangs below the chin.
        self.skin_pos = beard_offset(hf, self.look.get("beard"), self.skin_pos, self.skin_normals, clear=self.mouth_up + self.mouth_lo)
        faces = [tuple(q) for q in quads] + tris
        # Outward winding, and drop what the hair covers.
        out = []
        for f in faces:
            c = self.skin_pos[list(f)].mean(axis=0)
            if keep is not None and not keep(c):
                continue
            a, b, d = self.skin_pos[f[0]], self.skin_pos[f[1]], self.skin_pos[f[2]]
            if np.dot(np.cross(b - a, d - a), c - ORIGIN) < 0:
                f = tuple(reversed(f))
            out.append(f)
        # The atlas wraps round the back of the head. A face across that seam would stretch over
        # the whole picture (and the face's shadow map, drawn in the same UVs, would take the
        # back of the head's values across the jaw): such faces get their own vertices on the
        # seam's far side, a full turn on in u.
        uvs, extra = self.skin_uvs, {}
        for n_, f in enumerate(out):
            u = uvs[list(f), 0]
            if u.max() - u.min() <= 0.5:
                continue
            g = []
            for v in f:
                if uvs[v, 0] < 0.5:
                    if v not in extra:
                        extra[v] = self.skin_n + len(extra)
                    v = extra[v]
                g.append(v)
            out[n_] = tuple(g)
        if extra:
            src = np.array(list(extra))
            self.skin_pos = np.concatenate([self.skin_pos, self.skin_pos[src]])
            self.skin_normals = np.concatenate([self.skin_normals, self.skin_normals[src]])
            self.skin_uvs = np.concatenate([uvs, uvs[src] + np.array([1.0, 0.0])])
            self.skin_n += len(extra)
        self.skin_faces = out

    def _lid(self, side, s, state):
        """Heights of the upper and lower lids at s for a face state, relative to eye_z."""
        hf = self.hf
        up, lo = hf.lid(s)
        b = state.get("blink_l" if side < 0 else "blink_r", 0.0)
        if b:
            up = lerp(up, lo + 0.0002, b)
        j = state.get("joy", 0.0)
        if j:
            sc = np.clip(s, -1, 1)
            arc = hf.eye_tilt * hf.eye_w * sc + 0.36 * hf.eye_up * (1 - sc * sc) - 0.10 * hf.eye_up
            up, lo = lerp(up, arc + 0.0002, j), lerp(lo, arc, j)
        return up, lo

    def _lid_point(self, side, s, upper, state):
        up, lo = self._lid(side, np.array(s, float), state)
        return (side * (self.hf.eye_x + self.hf.eye_w * s), self.hf.eye_z + float(up if upper else lo))

    def _skin(self, state):
        """The skin's positions for a face state."""
        hf = self.hf
        pos = self.skin_pos.copy()
        # Lids.
        if any(state.get(k) for k in ("blink_l", "blink_r", "joy")):
            for side, r in self.rings.items():
                pts = [self._lid_point(side, s, upper, state) for s, upper in r["ring"]]
                pos[r["first"] : r["first"] + len(pts)] = hf.project_front(pts)[0]
        # The jaw and the mouth's corners.
        d, wide, smile = state.get("mouth", 0.0), state.get("wide", 0.0), state.get("smile", 0.0)
        if d or wide or smile:
            x, y, z = self.skin_pos[:, 0], self.skin_pos[:, 1], self.skin_pos[:, 2]
            mw = hf.mouth_w
            line = hf.mouth_line(x)
            ax = np.abs(x)
            if d:
                reach = lerp(0.0012, 0.016, smooth((ax - 0.7 * mw) / (0.6 * mw)))
                wz = smooth((line - z) / reach) * (y > 0.0)
                hinge = np.clip((y - 0.005) / 0.075, 0, 1) ** 0.8
                drop = d * wz * hinge
                lo_ids = np.array(self.mouth_lo, int)
                drop[lo_ids] = d * (1 - (x[lo_ids] / mw) ** 2) ** 0.75
                pos[:, 2] -= drop
                pos[:, 1] -= 0.22 * drop
            if wide or smile:
                for sx in (-1, 1):
                    dist = np.hypot(x - sx * mw, z - hf.mouth_z)
                    w = np.exp(-((dist / 0.013) ** 2)) * (y > 0.02)
                    pos[:, 0] += sx * mw * wide * w
                    pos[:, 2] += smile * w
                    pos[:, 1] -= 0.25 * mw * max(wide, 0) * w
                # Narrowed lips push forward.
                if wide < 0:
                    pos[:, 1] += -wide * 0.010 * np.exp(-((ax / (0.9 * mw)) ** 2 + ((z - hf.mouth_z) / 0.010) ** 2)) * (y > 0.02)
        return pos

    # --------------------------------------------------------------------------- the parts

    def build(self, state):
        hf, look = self.hf, self.look
        m = Mesh()
        skin = self._skin(state)
        white = (1.0, 1.0, 1.0)
        m.add(skin, white, self.skin_uvs, self.skin_faces, "face")
        dark = look["lash"]
        for side in (-1, 1):
            r = self.rings[side]
            first, ring = r["first"], r["ring"]
            k = len(ring)
            self._eye(m, skin, side, state)
            self._lines(m, side, state, dark)
            self._brow(m, side, state)
        self._mouth_inside(m, state)
        self._ears(m)
        return m

    def _eye(self, m, skin, side, state):
        """An eye behind its opening: the lids' rim turned in, the white, the iris on the eye's bone and the highlights."""
        hf, look = self.hf, self.look
        white = (1.0, 1.0, 1.0)
        r = self.rings[side]
        first, ring = r["first"], r["ring"]
        k = len(ring)
        # The lids' rim: the ring again, turned in behind the skin as far as the eye's ball.
        ring_pos = skin[first : first + k]
        nrm = self.skin_normals[first : first + k]
        ball = self.balls[side]
        oc = ring_pos - ball
        b_ = np.sum(oc * -nrm, axis=1)
        disc = b_ * b_ - (np.sum(oc * oc, axis=1) - EYE_R * EYE_R)
        reach = np.where(disc > 0, -b_ - np.sqrt(np.maximum(disc, 0)), self.RIM)
        reach = np.clip(reach + 0.0005, self.RIM, 0.012)
        base = m.add(ring_pos - nrm * reach[:, None], look["skin_rim"], self.skin_uvs[first : first + k], [], "face")
        mid_ring = ring_pos.mean(axis=0)
        for i in range(k):
            q = (first + i, first + (i + 1) % k, base + (i + 1) % k, base + i)
            c = np.array([m.v[v] for v in q])
            # The rim looks into the opening.
            if np.dot(np.cross(c[1] - c[0], c[2] - c[0]), mid_ring - c.mean(axis=0)) < 0:
                q = tuple(reversed(q))
            m.f.append(q)
            m.fm.append("face")
        # The eye's white: a patch of its ball behind the opening, with the lid's shadow painted.
        nx, nz = 10, 7
        mid, scale = eye_frame(hf)
        hw, hh = EYE_COLS / 2 / scale, EYE_ROWS / 2 / scale
        pts = [(side * hf.eye_x + lerp(-hw, hw, i / nx), hf.eye_z + mid + lerp(-hh, hh, j / nz)) for j in range(nz + 1) for i in range(nx + 1)]
        faces = [(j * (nx + 1) + i, j * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i) for j in range(nz) for i in range(nx)]
        m.add(on_ball(ball, [q[0] for q in pts], [q[1] for q in pts]), white, eye_uv(hf, side, [q[0] for q in pts], [q[1] for q in pts]), faces, "eye", facing=FORWARD)
        # The iris: its own layer just off the white, following the eye's bone, so the eye
        # can look round. `look` (yaw, pitch in degrees) turns it in the file, to photograph.
        yaw, pitch = state.get("look", (0.0, 0.0))
        cx, cz = iris_centre(hf, side)
        r = hf.iris_r
        seg = 24
        ring_uv = lambda rho: [(math.cos(2 * math.pi * i / seg) * rho, math.sin(2 * math.pi * i / seg) * rho) for i in range(seg)]
        disc_ = [(0.0, 0.0)] + ring_uv(0.55) + ring_uv(1.0)
        xs = [cx + a * r * IRIS_WIDE for a, _ in disc_]
        zs = [cz + b * r for _, b in disc_]
        half = IRIS_PX * IRIS_FILL
        uv = [((IRIS_COL0 + IRIS_PX / 2 + side * -a * half * IRIS_WIDE * 0 + a * half * IRIS_WIDE) / ATLAS, 1 - (IRIS_PX / 2 - b * half) / ATLAS) for a, b in disc_]
        faces = [(0, 1 + i, 1 + (i + 1) % seg) for i in range(seg)] + [(1 + i, 1 + seg + i, 1 + seg + (i + 1) % seg, 1 + (i + 1) % seg) for i in range(seg)]
        m.add(turn(on_ball(ball, xs, zs, 0.0006), ball, yaw, pitch), white, uv, faces, "iris", facing=FORWARD, eye=(side, 1.0))
        # Highlights: both eyes are lit from the same side. They follow the eye half way,
        # as a reflection does.
        hs = look.get("light_side", 1.0)
        for hx, hz, ring_ in glints(hs):
            n_ = len(ring_)
            ex = [cx + hx * r] + [cx + (hx + a_) * r for a_, _ in ring_]
            ez = [cz + hz * r] + [cz + (hz + b_) * r for _, b_ in ring_]
            m.add(turn(on_ball(ball, ex, ez, 0.0011), ball, 0.5 * yaw, 0.5 * pitch), (1.0, 1.0, 0.985), None, [(0, 1 + i, 1 + (i + 1) % n_) for i in range(n_)], "glint", facing=FORWARD, eye=(side, 0.5))

    LASH_OUT = 0.0  # how far the lash line's upper edge and the lashes' tips stand forward of the lid, m (a cage head's visor)

    def _shell(self, m, pts, faces, cols, mat, off):
        """Shapes drawn in the front view, laid `off` metres off the skin (one distance, or one a point)."""
        p, nr = self.hf.project_front(pts)
        m.add(p + nr * np.reshape(np.asarray(off, float), (-1, 1)), cols, None, faces, mat, facing=FORWARD)

    def _strip(self, m, top, bottom, col_top, col_bottom, mat, off, off_top=None):
        n = len(top)
        faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
        tops = [off] * n if off_top is None else (list(off_top) if isinstance(off_top, (list, tuple)) else [off_top] * n)  # one distance, or one a point
        self._shell(m, list(top) + list(bottom), faces, [col_top] * n + [col_bottom] * n, mat, tops + [off] * n)

    def _lines(self, m, side, state, dark):
        """The upper lash as the reference draws it: a broad dark band over the whole lid with an
        ink line along the lid's edge, flicks along its top and a fan of them at the outer
        corner. Then the lower lid's line and lashes, and the lid's fold."""
        hf, look = self.hf, self.look
        ex, ew = hf.eye_x, hf.eye_w
        b = max(state.get("blink_l" if side < 0 else "blink_r", 0.0), state.get("joy", 0.0))

        def up(s):
            return float(self._lid(side, np.array(s, float), state)[0])

        def lo(s):
            return float(self._lid(side, np.array(s, float), state)[1])

        def at(s, dz):
            return (side * (ex + ew * s), hf.eye_z + dz)

        # The band's height is a share of the open eye's (the rest state's, so a blink does not
        # thin it): about a quarter on a woman's or a child's eye, a seventh on a man's.
        k = look["lash_k"]
        rest = self._lid(side, np.array(0.0), {})
        opening = float(rest[0] - rest[1])
        full = opening * (0.07 + 0.09 * k)
        n = 22
        ss = [-1.0 + 2.0 * i / (n - 1) for i in range(n)]
        # Thickest past the middle, thinner toward both corners.
        th = [full * (0.58 + 0.42 * smooth((s + 1.1) / 1.3)) * (0.55 + 0.45 * smooth((s + 1.0) / 0.25)) * (0.62 + 0.38 * smooth((1.0 - s) / 0.30)) for s in ss]
        th_at = lambda s: float(np.interp(s, ss, th))
        out = self.LASH_OUT
        # A deep red-brown band and a near-black edge. Both are darker than they are to look: the
        # client draws a face's parts unshaded, which comes out lighter.
        band = mix3(dark, (0.26, 0.05, 0.06), 0.45)
        ink = mix3(dark, (0.01, 0.008, 0.012), 0.88)
        top = [at(s, up(s) + t) for s, t in zip(ss, th)]
        bot = [at(s, up(s) - 0.0005) for s in ss]
        # The band runs on past the outer corner to a point: outward and a little up, not down the
        # side of the eye along the lid's slope, which bracketed the eye and made it droop.
        slope = (up(1.0) - up(0.90)) / 0.10 / ew
        wl = ew * look["lash_wing"]
        lift = look.get("wing_lift", 0.25)
        for i in range(1, 5):
            t = i / 4
            x = ex + ew + wl * t
            z = up(1.0) + wl * t * (0.12 * slope + 0.35 + lift * (1 - 0.3 * t))
            w = th[-1] * (1 - t) ** 1.3
            top.append((side * x, hf.eye_z + z + w))
            bot.append((side * x, hf.eye_z + z - 0.0004 * (1 - t)))
        self._strip(m, top, bot, mix3(band, look["lash_tip"], 0.30), band, "line", 0.0012, off_top=0.0012 + out)
        # The ink line along the lid's edge, on the band: it is what holds the eye's shape from far off.
        we = [opening * (0.040 + 0.016 * k) * (0.6 + 0.4 * smooth((s + 1.0) / 1.2)) for s in ss]
        self._strip(m, [at(s, up(s) + w) for s, w in zip(ss, we)], [at(s, up(s) - 0.0006) for s in ss], ink, ink, "line", 0.0016, off_top=[0.0016 + out * w / max(t, 1e-6) for w, t in zip(we, th)])
        rng = random.Random(f"lash/{look.get('seed', 0)}/{side}")
        nl = look["lashes"]
        shut = 1 - 0.6 * b
        # Flicks along the band's top: broad at the root, leaning toward the outer corner.
        for i in range(nl):
            f = (i + 0.5) / max(nl, 1)
            s = lerp(-0.55, 0.92, f) + rng.uniform(-0.03, 0.03)
            ln = opening * (0.07 + 0.07 * f) * (0.75 + 0.25 * k / 1.9) * rng.uniform(0.85, 1.15) * shut
            a = math.radians(lerp(96, 38, f ** 0.8) + rng.uniform(-6, 6))
            self._strand(m, side, (ex + ew * s, hf.eye_z + up(s) + 0.80 * th_at(s)), a, ln, opening * 0.030, bend=-0.25, cols=(band, look["lash_tip"]), mat="line", off=0.0013, rise=0.80)
        # A fan at the outer corner, from the band's end: the longest points out and a little down.
        fan = min(nl, 4) if nl else 0
        for i in range(fan):
            f = i / max(fan - 1, 1)
            root = (ex + ew * (0.97 + 0.04 * f), hf.eye_z + up(0.97) + th[-1] * lerp(0.85, 0.10, f))
            ln = opening * lerp(0.14, 0.20, math.sin(math.pi * f)) * (0.8 + 0.2 * k / 1.9) * shut
            a = math.radians(lerp(30, -24, f) + rng.uniform(-4, 4))
            self._strand(m, side, root, a, ln, opening * 0.034, bend=-0.20, cols=(band, look["lash_tip"]), mat="line", off=0.0013, rise=lerp(0.85, 0.10, f))
        # Two short ones at the inner corner.
        for i in range(2 if nl >= 6 else 0):
            s = -0.90 + 0.16 * i
            self._strand(m, side, (ex + ew * s, hf.eye_z + up(s) + 0.7 * th_at(s)), math.radians(140 - 22 * i), opening * 0.055 * shut, opening * 0.022, bend=0.2, cols=(band, look["lash_tip"]), mat="line", off=0.0013, rise=0.7)
        # A few under the outer corner.
        for i in range(look.get("lashes_low", 0)):
            f = (i + 0.5) / look["lashes_low"]
            s = lerp(0.50, 0.94, f)
            ln = opening * (0.045 + 0.035 * f) * shut
            self._strand(m, side, (ex + ew * s, hf.eye_z + lo(s) - 0.0002), math.radians(-70 + 34 * f), ln, opening * 0.016, bend=-0.3, cols=(band, look["lash_tip"]), mat="line", off=0.0011, rise=0.0)
        # Lower line: the outer part only, as the reference has it.
        lk = look["lower"]
        s3 = [0.22 + 0.78 * i / 8 for i in range(9)]
        w3 = [(0.00022 + 0.00060 * lk * smooth((s - 0.22) / 0.5)) * (1.0 if s < 0.85 else 0.6) for s in s3]
        low_c = mix3(look["skin_line"], band, 0.30 + 0.55 * min(lk, 1.0))
        self._strip(m, [at(s, lo(s) + 0.0003) for s in s3], [at(s, lo(s) - w) for s, w in zip(s3, w3)], low_c, low_c, "line", 0.0010)
        # The fold above the lid: it stands clear of the band, and closes onto the lid with a blink.
        fold = look["fold"]
        gap = (0.0016 + 0.0014 * fold) * (1 - 0.75 * b)
        s4 = [-0.62 + 1.30 * i / 11 for i in range(12)]
        w4 = [0.00042 * fold * math.sin(math.pi * (0.08 + 0.92 * i / 11)) + 0.00008 for i in range(12)]
        z4 = [up(min(s, 0.98)) + th_at(min(s, 0.98)) + gap * (1 - 0.25 * s * s) for s in s4]
        self._strip(m, [at(s, z + w) for s, z, w in zip(s4, z4, w4)], [at(s, z - w) for s, z, w in zip(s4, z4, w4)], look["skin_line"], look["skin_line"], "line", 0.0009)

    def _brow(self, m, side, state):
        hf, look = self.hf, self.look
        n = 14
        top, bot = brow_shape(hf, side, state, n)
        c = look["brow"]
        # A soft shape under the hairs, so the brow still reads from far off.
        under = mix3(c, look["skin"], 0.12)
        self._strip(m, [(x, lerp(zb, zt, 0.88)) for (x, zt), (_, zb) in zip(top, bot)], [(x, lerp(zb, zt, 0.12)) for (x, zt), (_, zb) in zip(top, bot)], under, mix3(under, (0, 0, 0), 0.12), "brow", 0.0010)
        # The hairs: strands as the hair's locks are in small, growing up at the inner end and
        # sweeping along the brow toward its tail.
        rng = random.Random(f"brow/{look.get('seed', 0)}/{side}")
        count = look.get("brow_hairs", 24)
        for i in range(count):
            t = (i + rng.uniform(0.1, 0.9)) / count
            j = min(int(t * (n - 1)), n - 2)
            f = t * (n - 1) - j
            (xa, za), (xb, zb_) = top[j], top[j + 1]
            (xc, zc), (xd, zd) = bot[j], bot[j + 1]
            xt, zt, zl = lerp(abs(xa), abs(xb), f), lerp(za, zb_, f), lerp(zc, zd, f)
            w = zt - zl
            root = (xt, lerp(zl, zt, rng.uniform(0.05, 0.55)))
            slope = math.atan2(zb_ - za, abs(xb) - abs(xa))
            a = slope + math.radians(lerp(72, 14, smooth(t / 0.45)) + rng.uniform(-9, 9))
            ln = max(w, 0.0012) * lerp(1.15, 1.9, smooth(t / 0.5)) * rng.uniform(0.8, 1.15) * (1 - 0.35 * smooth((t - 0.75) / 0.25))
            tone = rng.uniform(-0.16, 0.16)
            col = mix3(c, (0, 0, 0), -tone) if tone < 0 else mix3(c, look["skin"], tone * 0.8)
            self._strand(m, side, root, a, ln, 0.00055 + 0.085 * max(w, 0.001), bend=-0.18, cols=(col, mix3(col, look["skin"], 0.25)), mat="brow", off=0.0012)

    def _strand(self, m, side, root, angle, length, width, bend, cols, mat, off, rise=None):
        """One hair on the face: a tapering card from `root` (front view: |x|, z) along `angle`
        (radians from pointing outward along +|x|, anticlockwise toward up), bending as it goes.
        `rise` (0..1) is for a lash that stands on the lash band: how far up the band's forward
        lean its root is, so it starts on the band and not behind it."""
        x0, z0 = root
        pts, cs = [], []
        for q, (t, wk) in enumerate(((0.0, 1.0), (0.55, 0.72), (1.0, 0.0))):
            a = angle + bend * t
            cx, cz = x0 + length * t * math.cos(angle + 0.5 * bend * t), z0 + length * t * math.sin(angle + 0.5 * bend * t)
            nx, nz = -math.sin(a), math.cos(a)
            if wk > 0:
                pts += [(side * (cx + nx * width * wk), cz + nz * width * wk), (side * (cx - nx * width * wk), cz - nz * width * wk)]
                cs += [mix3(cols[0], cols[1], t)] * 2
            else:
                pts.append((side * cx, cz))
                cs.append(cols[1])
        lo_ = self.LASH_OUT * (mat == "line")
        if rise is None:
            offs = [off, off, off + 0.55 * lo_, off + 0.55 * lo_, off + lo_]
        else:
            r0 = off + lo_ * rise
            offs = [r0, r0, r0 + 0.25 * lo_, r0 + 0.25 * lo_, r0 + 0.45 * lo_]
        self._shell(m, pts, [(0, 1, 3, 2), (2, 3, 4)], cs, mat, offs)

    def _mouth_inside(self, m, state):
        """What an open mouth shows: a dark back, the upper teeth, the tongue."""
        hf = self.hf
        mw, zm = hf.mouth_w, hf.mouth_z
        d = state.get("mouth", 0.0)
        nx, nz = 8, 4
        pts = [(lerp(-mw * 0.96, mw * 0.96, i / nx), lerp(zm + 0.004, zm - 0.018, j / nz)) for j in range(nz + 1) for i in range(nx + 1)]
        p, nr = hf.project_front(pts)
        faces = [(j * (nx + 1) + i, j * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i) for j in range(nz) for i in range(nx)]
        cols = [mix3((0.34, 0.10, 0.10), (0.16, 0.05, 0.06), j / nz) for j in range(nz + 1) for i in range(nx + 1)]
        depth = np.array([0.0030 + 0.0040 * (1 - (q[0] / mw) ** 2) for q in pts])
        m.add(p - nr * depth[:, None], cols, None, faces, "mouth", facing=FORWARD)
        # Upper teeth: a band just behind the upper lip.
        n = 9
        xs = [lerp(-0.82 * mw, 0.82 * mw, i / (n - 1)) for i in range(n)]
        edge = [zm - 0.0034 * (1 - 0.5 * (x / mw) ** 2) for x in xs]
        p, nr = hf.project_front([(x, zm + 0.003) for x in xs] + [(x, z) for x, z in zip(xs, edge)])
        m.add(p - nr * np.array([0.0014 + 0.0016 * (1 - (x / mw) ** 2) for x in xs] * 2)[:, None], [(0.93, 0.91, 0.86)] * n + [(0.86, 0.84, 0.80)] * n, None, [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)], "mouth", facing=FORWARD)
        # The tongue rides the jaw.
        k = 10
        cz = zm - 0.0075 - d
        pts = [(0.0, cz)] + [(0.58 * mw * math.cos(2 * math.pi * i / k), cz + 0.0048 * math.sin(2 * math.pi * i / k)) for i in range(k)]
        p, nr = hf.project_front([(x, max(min(z, zm + 0.004), zm - 0.02)) for x, z in pts])
        p = p - nr * 0.0036
        p[:, 2] = [z for _, z in pts]
        m.add(p, [(0.80, 0.42, 0.42)] + [(0.66, 0.30, 0.32)] * k, None, [(0, 1 + i, 1 + (i + 1) % k) for i in range(k)], "mouth", facing=FORWARD)

    def _ears(self, m):
        """Each ear: a back wall off the head, a rim, the slope inside it, the bowl."""
        hf, look = self.hf, self.look
        size = hf.ear_size
        zc = lerp(hf.eye_z + 0.020, hf.nose_base_z, 0.5)
        half_h = 0.0315 * size
        half_w = 0.0170 * size
        yc = -0.016
        seg = getattr(self, "EAR_SEG", 16)  # the far head's ears are a rim and a middle
        skin, shade = look["skin"], look["skin_shade"]
        tan_out = math.tan(math.radians(hf.ear_out))
        for side in (-1, 1):
            root = hf.point(-side * 90.0, zc)
            x_root = abs(root[0]) - 0.004

            def ring(scale, lift, dy=0.0, dz=0.0):
                pts = []
                for i in range(seg):
                    a = 2 * math.pi * i / seg
                    u, v = math.cos(a), math.sin(a)  # u forward, v up
                    # An ear's outline: wider above, a lobe below, leaning back.
                    w = half_w * (1.0 + 0.22 * v) * scale
                    y = yc + dy + u * w - 0.10 * v * half_h
                    z = zc + dz + v * half_h * scale * (1.0 if v > 0 else 0.92)
                    # It stands out more toward its back edge.
                    out = lift + tan_out * max(0.0, (yc + half_w - y)) * (0.25 + 0.75 * min(scale, 1.0))
                    pts.append((side * (x_root + out), y, z))
                return pts

            rings = [ring(0.50, 0.000, dy=0.004), ring(1.00, 0.0015), ring(0.80, 0.0045), ring(0.50, 0.0010, dy=0.002, dz=-0.001)]
            tint = [skin, mix3(skin, look["skin_warm"], 0.25), mix3(skin, shade, 0.35), mix3(skin, shade, 0.85)]
            if hasattr(self, "EAR_RINGS"):
                rings, tint = [rings[0]] + [rings[i] for i in self.EAR_RINGS], [tint[0]] + [tint[i] for i in self.EAR_RINGS]
            pts, cols = [], []
            for r, c in zip(rings, tint):
                pts += r
                cols += [c] * seg
            pts.append((side * (x_root + 0.0005), yc + 0.003, zc - 0.002))
            cols.append(mix3(skin, shade, 1.0))
            # Vertex colours multiply the swatch of plain skin the ears' UVs point at.
            rel = [unlin(tuple(min(a / max(b, 1e-4), 1.0) for a, b in zip(lin(c), lin(skin)))) for c in cols]
            base = m.add(pts, rel, [SWATCH_UV] * len(pts), [], "face")
            axis = np.array([side * (x_root + 0.004), yc, zc])
            for r in range(len(rings)):
                for i in range(seg):
                    a, b = r * seg + i, r * seg + (i + 1) % seg
                    f = (a, b, b + seg, a + seg) if r < len(rings) - 1 else (a, b, len(pts) - 1)
                    q = np.array([pts[v] for v in f])
                    nrm = np.cross(q[1] - q[0], q[2] - q[0])
                    # The back wall looks away from the ear's middle; the rest looks out sideways.
                    good = np.dot(nrm, q.mean(axis=0) - axis) > 0 if r == 0 else nrm[0] * side > 0
                    m.f.append(tuple(base + v for v in (f if good else reversed(f))))
                    m.fm.append("face")


def brow_shape(hf, side, state=None, n=14):
    """A brow's upper and lower edges in the front view, from its inner end out: two lists of
    (x, z). `state` raises or lowers its ends (expressions)."""
    state = state or {}
    x0 = hf.eye_x - hf.eye_w * 1.02 - 0.0015
    x1 = hf.eye_x + hf.eye_w * (1.12 + 0.30 * (hf.brow_len - 1)) + 0.002
    x0 = max(x0, 0.0085)
    top, bot = [], []
    peak = 0.62
    for i in range(n):
        t = i / (n - 1)
        x = lerp(x0, x1, t)
        arch = hf.brow_arch * (math.sin(math.pi * min(t / peak, 1.0) * 0.5) if t < peak else math.cos(math.pi * 0.5 * ((t - peak) / (1 - peak)) ** 1.15) ** 0.9)
        z = hf.eye_z + hf.eye_up + hf.brow_up + arch + hf.brow_tilt * (2 * t - 1) - 0.0012 * (t > peak) * ((t - peak) / (1 - peak))
        z += lerp(state.get("brow_in", 0.0), state.get("brow_out", 0.0), smooth(t * 1.2))
        w = hf.brow_w * (0.55 + 0.45 * smooth(t / 0.16)) * (1 - 0.88 * smooth((t - 0.45) / 0.55) ** 1.2)
        top.append((side * x, z + 0.55 * w))
        bot.append((side * x, z - 0.45 * w))
    return top, bot


def beard_offset(hf, style, sp, normals, clear=()):
    """Skin positions with a beard standing off them (its hairs are painted): thick for a full
    beard, which also hangs below the chin. `clear` lists vertices that stay on the skin."""
    cover = hf.beard_cover(style, np.abs(sp[:, 0]), sp[:, 2], np.degrees(np.arctan2(-sp[:, 0], sp[:, 1])), soft=0.004)
    if cover is None:
        return sp
    cover = cover * (sp[:, 1] > -0.03)
    cover[list(clear)] = 0.0
    # Over the lip it stays thin, whatever the beard.
    thick = lerp(min(hf.BEARDS[style], 0.0022), hf.BEARDS[style], smooth((hf.mouth_z - 0.004 - sp[:, 2]) / 0.014))
    out = sp + normals * (thick * cover)[:, None]
    if style == "full":
        hang = cover * smooth((hf.mouth_z - 0.010 - sp[:, 2]) / 0.03) * smooth((sp[:, 1] - 0.01) / 0.05)
        out[:, 2] -= 0.012 * hang
        out[:, 1] += 0.004 * hang
    return out


FAR_CUTS = 12  # the far head's grid: 12 quads along each edge of the cube


class FarFace:
    """The far model's head (person.py --lod far): the same form on a coarse grid, with no eye
    openings, no mouth slit and no expressions. Its eyes, lash lines and brows are painted on
    the skin (face_paint.paint_far). `mesh` has one material, `face`; base_pos and base_quads
    are the whole head for hair and headwear, as Face's are."""

    EAR_SEG, EAR_RINGS = 6, (1, 2)

    def __init__(self, hf, look, keep=None):
        self.hf, self.look = hf, look
        dirs, quads, _ = cube_sphere(FAR_CUTS, WARP)
        self.base_pos = ORIGIN + dirs * hf.radius(dirs)[:, None]
        self.base_quads = quads
        normals = hf.normal(self.base_pos)
        pos = beard_offset(hf, look.get("beard"), self.base_pos.copy(), normals)
        uvs = skin_uv(self.base_pos)
        faces = []
        for q in quads:
            c = pos[list(q)].mean(axis=0)
            if keep is not None and not keep(c):
                continue
            a, b, d = pos[q[0]], pos[q[1]], pos[q[2]]
            faces.append(tuple(q) if np.dot(np.cross(b - a, d - a), c - ORIGIN) >= 0 else tuple(reversed(q)))
        # Faces across the atlas's seam at the back of the head get their own vertices (Face).
        extra = {}
        for n_, f in enumerate(faces):
            u = uvs[list(f), 0]
            if u.max() - u.min() <= 0.5:
                continue
            faces[n_] = tuple(extra.setdefault(v, len(pos) + len(extra)) if uvs[v, 0] < 0.5 else v for v in f)
        if extra:
            src = np.array(list(extra))
            pos = np.concatenate([pos, pos[src]])
            uvs = np.concatenate([uvs, uvs[src] + np.array([1.0, 0.0])])
        used = sorted({v for f in faces for v in f})
        index = {v: i for i, v in enumerate(used)}
        m = Mesh()
        m.add(pos[used], (1.0, 1.0, 1.0), uvs[used], [tuple(index[v] for v in f) for f in faces], "face")
        Face._ears(self, m)
        self.mesh = m


def FORWARD(centre, normal):
    return normal[1] > 0


def lin(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


def unlin(c):
    return tuple(1.055 * x ** (1 / 2.4) - 0.055 if x > 0.0031308 else 12.92 * x for x in c)


def mix3(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))
