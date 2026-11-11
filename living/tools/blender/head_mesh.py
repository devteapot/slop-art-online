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

import numpy as np

from head_form import ORIGIN, lerp, smooth

ATLAS = 1024
EYE_ROWS = 192  # the eyes' strip, at the top of the atlas
EYE_COLS = 448  # each eye's rectangle; the rest of the strip is a swatch of plain skin
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


SWATCH_UV = ((2 * EYE_COLS + ATLAS) / 2 / ATLAS, 1 - EYE_ROWS / 2 / ATLAS)  # plain skin (ears)


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
        self.v, self.col, self.uv, self.f, self.fm = [], [], [], [], []

    def add(self, pts, cols, uvs, faces, mat, facing=None):
        """`facing(centre, normal)` says whether a face looks the right way; others are turned."""
        base = len(self.v)
        pts = [tuple(float(c) for c in p) for p in pts]
        self.v += pts
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
        self._topology(front, keep)
        neutral = self.build({})
        self.mesh = neutral
        self.morphs = {}
        v0 = np.array(neutral.v)
        for name, state in EXPRESSIONS.items():
            m = self.build(state)
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
        style = self.look.get("beard")
        sp = self.skin_pos
        cover = hf.beard_cover(style, np.abs(sp[:, 0]), sp[:, 2], np.degrees(np.arctan2(-sp[:, 0], sp[:, 1])), soft=0.004)
        if cover is not None:
            cover = cover * (sp[:, 1] > -0.03)
            cover[self.mouth_up + self.mouth_lo] = 0.0
            # Over the lip it stays thin, whatever the beard.
            thick = lerp(min(hf.BEARDS[style], 0.0022), hf.BEARDS[style], smooth((hf.mouth_z - 0.004 - sp[:, 2]) / 0.014))
            self.skin_pos = sp + self.skin_normals * (thick * cover)[:, None]
            if style == "full":
                hang = cover * smooth((hf.mouth_z - 0.010 - sp[:, 2]) / 0.03) * smooth((sp[:, 1] - 0.01) / 0.05)
                self.skin_pos[:, 2] -= 0.012 * hang
                self.skin_pos[:, 1] += 0.004 * hang
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
            # The lids' rim: the ring again, turned in behind the skin.
            ring_pos = skin[first : first + k]
            nrm = self.skin_normals[first : first + k]
            base = m.add(ring_pos - nrm * self.RIM, look["skin_rim"], self.skin_uvs[first : first + k], [], "face")
            mid_ring = ring_pos.mean(axis=0)
            for i in range(k):
                q = (first + i, first + (i + 1) % k, base + (i + 1) % k, base + i)
                c = np.array([m.v[v] for v in q])
                # The rim looks into the opening.
                if np.dot(np.cross(c[1] - c[0], c[2] - c[0]), mid_ring - c.mean(axis=0)) < 0:
                    q = tuple(reversed(q))
                m.f.append(q)
                m.fm.append("face")
            # The eye: a bowl behind the opening, carrying the painted eye.
            nx, nz = 10, 7
            mid, scale = eye_frame(hf)
            hw, hh = EYE_COLS / 2 / scale, EYE_ROWS / 2 / scale
            pts = [(side * hf.eye_x + lerp(-hw, hw, i / nx), hf.eye_z + mid + lerp(-hh, hh, j / nz)) for j in range(nz + 1) for i in range(nx + 1)]
            p, nr = hf.project_front(pts)
            faces = [(j * (nx + 1) + i, j * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i) for j in range(nz) for i in range(nx)]
            m.add(p - nr * self.BOWL, white, eye_uv(hf, side, [q[0] for q in pts], [q[1] for q in pts]), faces, "eye", facing=FORWARD)
            self._lines(m, side, state, dark)
            self._brow(m, side, state)
        self._mouth_inside(m, state)
        self._ears(m)
        return m

    def _shell(self, m, pts, faces, cols, mat, off):
        p, nr = self.hf.project_front(pts)
        m.add(p + nr * off, cols, None, faces, mat, facing=FORWARD)

    def _strip(self, m, top, bottom, col_top, col_bottom, mat, off):
        n = len(top)
        faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
        self._shell(m, list(top) + list(bottom), faces, [col_top] * n + [col_bottom] * n, mat, off)

    def _lines(self, m, side, state, dark):
        """The upper lash line with its wing and lashes, the lower lid's line, the lid's fold."""
        hf, look = self.hf, self.look
        ex, ew = hf.eye_x, hf.eye_w
        b = max(state.get("blink_l" if side < 0 else "blink_r", 0.0), state.get("joy", 0.0))

        def up(s):
            return float(self._lid(side, np.array(s, float), state)[0])

        def lo(s):
            return float(self._lid(side, np.array(s, float), state)[1])

        def at(s, dz):
            return (side * (ex + ew * s), hf.eye_z + dz)

        # Upper line: thin at the inner corner, heaviest past the middle, running on into a wing.
        k = look["lash_k"]
        n = 18
        ss = [-1.0 + 2.0 * i / (n - 1) for i in range(n)]
        th = [0.00045 + 0.0019 * k * smooth((s + 1.15) / 1.5) for s in ss]
        top = [at(s, up(s) + t) for s, t in zip(ss, th)]
        bot = [at(s, up(s) - 0.0005) for s in ss]
        # The wing leaves along the lid's own slope at the outer corner, lifted a little.
        slope = (up(1.0) - up(0.90)) / 0.10 / ew
        wl = ew * look["lash_wing"]
        lift = look.get("wing_lift", 0.25)
        for i in range(1, 5):
            t = i / 4
            x = ex + ew + wl * t
            z = up(1.0) + wl * t * (0.55 * slope + lift * (1 - 0.3 * t))
            w = th[-1] * (1 - t) ** 1.3
            top.append((side * x, hf.eye_z + z + w))
            bot.append((side * x, hf.eye_z + z - 0.0004 * (1 - t)))
        self._strip(m, top, bot, mix3(dark, look["lash_tip"], 0.35), dark, "line", 0.0012)
        # Lashes: short spikes off the outer part of the line.
        nl = look["lashes"]
        for i in range(nl):
            s = 0.55 + 0.42 * (i + 0.5) / max(nl, 1)
            root_z = up(s) + 0.6 * th[min(int((s + 1) / 2 * (n - 1)), n - 1)]
            ln = 0.0022 * k * (0.8 + 0.4 * (i % 2))
            a = math.radians(38 + 30 * i / max(nl, 1))
            pts = [at(s - 0.07, root_z), at(s + 0.07, root_z), (side * (ex + ew * s + ln * math.cos(a)), hf.eye_z + root_z + ln * math.sin(a))]
            self._shell(m, pts, [(0, 1, 2)], [dark, dark, look["lash_tip"]], "line", 0.0013)
        # Lower line: the outer part only.
        lk = look["lower"]
        s3 = [0.10 + 0.90 * i / 8 for i in range(9)]
        w3 = [(0.00022 + 0.00055 * lk * smooth((s - 0.1) / 0.6)) * (1.0 if s < 0.85 else 0.6) for s in s3]
        low_c = mix3(look["skin_line"], dark, 0.25 + 0.6 * min(lk, 1.0))
        self._strip(m, [at(s, lo(s) + 0.0003) for s in s3], [at(s, lo(s) - w) for s, w in zip(s3, w3)], low_c, low_c, "line", 0.0010)
        # The fold above the lid; it closes onto the lid with a blink.
        fold = look["fold"]
        gap = (0.0019 + 0.0016 * fold) * (1 - 0.75 * b)
        s4 = [-0.62 + 1.45 * i / 11 for i in range(12)]
        w4 = [0.00042 * fold * math.sin(math.pi * (0.08 + 0.92 * i / 11)) + 0.00008 for i in range(12)]
        self._strip(m, [at(s, up(min(s, 0.98)) + gap * (1 - 0.25 * s * s) + w) for s, w in zip(s4, w4)], [at(s, up(min(s, 0.98)) + gap * (1 - 0.25 * s * s) - w) for s, w in zip(s4, w4)],
                    look["skin_line"], look["skin_line"], "line", 0.0009)

    def _brow(self, m, side, state):
        hf, look = self.hf, self.look
        n = 14
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
        c = look["brow"]
        self._strip(m, top, bot, c, mix3(c, (0, 0, 0), 0.18), "brow", 0.0011)

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
        seg = 16
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


def FORWARD(centre, normal):
    return normal[1] > 0


def lin(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


def unlin(c):
    return tuple(1.055 * x ** (1 / 2.4) - 0.055 if x > 0.0031308 else 12.92 * x for x in c)


def mix3(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))
