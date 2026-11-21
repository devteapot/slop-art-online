"""Ink carriers from the generator (char-port-2 S4, `SLOP_PORT=ink`): the lid, its wing, lash
flicks and fringe, the outer lower lid and the brow, drawn as ink (docs/HANDMADE_INK.md v1.2) on
strips of their own, laid out on the types' shared ink page (docs/HANDMADE_COMPOSED.md v1.3,
"The ink page"). numpy only; head_mesh.Face calls `add`, and the page tool calls `page_strokes`.

**The strokes** are Cora's, traced from her drawing (docs/char-live-3/eye-frame/drawing-strokes.json,
the front view's +X eye) and accepted by the GC in char-live-3. They are kept here in *eye units*:
along the eye from the inner canthus (0) to the outer (1), across it in canthus distances. So
each face places them on its own eye:
- **The upper lid** follows the face's own opening edge (its `_lid`, so it blinks), its ink edge
  0.5 mm inside the opening, with the drawn half-widths, gained over the outer two thirds.
- **The wing** keeps its drawn shape beyond the outer canthus.
- **Lash flicks** (2) and a **fringe** (a sawtooth along the lid's top edge) ride the lid.
- **The outer lower lid** follows the lower edge, its upper edge on the rim.
- **The brow** is the face's own brow stroke (head_mesh.brow_shape), as ink.
- **A lid core:** an opaque strip inside the lid's ink (the face's line material), so the lid
  keeps its weight at play distance, where the ink fades.

**One topology a class.** A carrier is a ribbon at fixed stations along its stroke and fixed
rows across, the same numbers for every type of a class (an age-sex group: `adult-f` for
`adult-f-a`, `-b` and `-c`). Its UVs are laid out once, from the class's line b at rest, by
the ribbon's own 3D lengths (near-isometric), into the class's cell of the page; lines a and c
and every person of the class share them. A line's carriers differ only in position: an eye
3.5% larger draws its strokes 3.5% larger.

**What a class sets** (`CLASS`): the lid's width, its gain, the wing, the fringe, the flicks,
the lower lid and the brow's weight, by sex and age. Everything else is fixed style.
"""

import json
import math
import os
import sys

import numpy as np

_CHARACTERS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "characters")
if _CHARACTERS not in sys.path:
    sys.path.insert(1, _CHARACTERS)  # face_types, as person_params finds it

PORT = {f.strip() for f in os.environ.get("SLOP_PORT", "").split(",") if f.strip()}
ON = "ink" in PORT

# --- the page (docs/HANDMADE_COMPOSED.md, "The ink page") --------------------------------------
PAGE, CELL = 4096, 1024
TEXEL_M = 0.00025  # 0.25 mm a texel
M_UV = PAGE * TEXEL_M  # 1.024 m a UV unit
PAGE_PATH = "lookdev/types/types.eyes.ink.png"
CLASSES = ["child-u", "youth-f", "youth-m", "adult-f", "adult-m", "elder-f", "elder-m"]
CLASS_CELLS = {c: [i % 4, i // 4] for i, c in enumerate(CLASSES)}
# The map's range (G = 255 at this distance from a centreline): one page, one range. It holds the
# widest half-width a class draws (a man's brow, 3.3 mm) under the fade's bound (R <= 1 - 1/3).
RANGE_M = 0.0055
RANGE_UV = RANGE_M / M_UV
REACH_M = RANGE_M + 0.0015  # how far a carrier reaches past every centreline: the range and a pixel at the closest view
PAD = int(math.ceil(2 * RANGE_UV * PAGE)) + 8  # texels between islands, and from a cell's edge

LID_MAT, BROW_MAT = "M00_000_00_LidInk_00_FACE", "M00_000_00_FaceBrowInk_00_FACE"
AUBURN = [102, 46, 26]
INK = {
    # Cora's accepted lid ink (char-live-3 ink-batch-2) and her brow's, which follows the hair tag.
    LID_MAT: dict(color=[6, 2, 2], width="uv", min_px=1.0, fade_px=3.0, range=RANGE_UV, map=PAGE_PATH, m_uv=M_UV),
    BROW_MAT: dict(color=[57, 32, 20], ref=AUBURN, width="uv", min_px=1.0, fade_px=3.0, range=RANGE_UV, map=PAGE_PATH, m_uv=M_UV),
}

# --- Cora's strokes, as traced (drawing px, y down; the +X eye) --------------------------------
INNER, OUTER = (560.0, 288.0), (632.0, 275.0)  # the canthi the trace was registered on
DRAWN_LID = [(560, 288, 0), (564, 281, 2.2), (569, 275, 4), (576, 269, 5.8), (584, 266, 7.1), (594, 265, 7.4), (603, 264.6, 7.5), (611, 265, 7.8),
             (620, 266.7, 7.75), (626, 269, 7.75), (632, 271.6, 8.3), (636, 272, 7.95), (641, 271.5, 3.85), (646, 270.5, 1.6), (651, 268.7, 0)]
DRAWN_FLICKS = [[(612, 262.7, 2.4), (617, 261.7, 1.8), (623, 259.8, 0)], [(630, 266.7, 2.8), (636, 266.3, 2), (641, 264.6, 0)]]
DRAWN_LOWER = [(599, 294.4, 0), (607, 294.6, 1.6), (614, 292.5, 2.0), (620, 289.6, 2.3), (625, 285.5, 2.5), (629, 280, 2.6), (632, 274.5, 2.8)]


def _eye_units(pts):
    """Drawing points (x, y down, full width) as (a along the canthus chord from the inner, b up
    across it, half-width), in canthus distances."""
    c = complex(OUTER[0] - INNER[0], -(OUTER[1] - INNER[1]))
    out = []
    for x, y, w in pts:
        q = complex(x - INNER[0], -(y - INNER[1])) / c
        out.append((q.real, q.imag, w / 2 / abs(c)))
    return np.array(out)


LID_EU, LOWER_EU = _eye_units(DRAWN_LID), _eye_units(DRAWN_LOWER)
FLICKS_EU = [_eye_units(f) for f in DRAWN_FLICKS]

# --- fixed style (Cora's journal: char-live-3 ink-batch design.py, ink-batch-2 design2.py) ----------
LID_OVERLAP_M = 0.0005  # the lid's ink edge reaches this far into the opening
GAIN_FROM, GAIN_TO = 0.12, 0.42  # the lid's gain comes in over this share of the eye
FRINGE = dict(start=0.30, end=0.97, spacing_m=0.0009, length_m=0.0008, lean=0.35, root_m=0.00045, inset=0.35)
CORE_INSET, CORE_MARGIN_M = 0.35, 0.0006  # the core's half-width: hw - max(inset * hw, margin)
OFF = dict(lid=0.0014, core=0.0012, brow=0.0016)  # off the head's form, as the lines it replaces lie
# A carrier's rows lie further off the form the further they are from its spine: its margins
# carry no ink, and a wide face's temples (face_width +1) came through a brow carrier's edge.
LIFT = 0.12
END_M = 0.0025
N_LID, N_LOWER, N_BROW = 22, 9, 15  # stations along each stroke (and one past each end)
BROW_TS = np.linspace(0.0, 1.0, N_BROW)

# --- what a class sets ---------------------------------------------------------------------------
# lid: the drawn half-widths' scale; gain: over the outer two thirds (Cora's 1.25); wing: its
# length's share; fringe: its spikes' length's share (0 none); flicks: how many of the two drawn;
# lower: the drawn lower lid's scale (Cora's 1.3); brow: the brow stroke's weight over the type's.
SEX = dict(f=dict(lid=1.0, gain=1.25, wing=1.0, fringe=1.0, flicks=2, lower=1.3, brow=1.2),
           m=dict(lid=1.0, gain=1.0, wing=0.4, fringe=0.5, flicks=0, lower=0.9, brow=1.0),
           u=dict(lid=0.9, gain=1.1, wing=0.0, fringe=0.6, flicks=0, lower=1.0, brow=1.0))
AGE = dict(child=1.0, youth=1.0, adult=1.0, elder=0.85)  # the lid's and lower lid's widths


def class_of(tid):
    return tid.rsplit("-", 1)[0]


def params(cls):
    band, sex = cls.split("-")
    p = dict(SEX[sex])
    p["lid"] *= AGE[band]
    p["lower"] *= AGE[band]
    return p


def _smooth(x, a, b):
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _chaikin(P, n=2):
    P = np.asarray(P, float)
    for _ in range(n):
        Q = [P[0]]
        for a, b in zip(P[:-1], P[1:]):
            Q += [0.75 * a + 0.25 * b, 0.25 * a + 0.75 * b]
        Q.append(P[-1])
        P = np.array(Q)
    return P


def _resample(P, n):
    """n points at even shares of a polyline's length (columns beyond 2 interpolated alike)."""
    P = np.asarray(P, float)
    L = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P[:, :2], axis=0), axis=1))])
    s = np.linspace(0.0, L[-1], n)
    return np.stack([np.interp(s, L, P[:, k]) for k in range(P.shape[1])], 1)


def _normals(P):
    """Unit normals of a front-view polyline, turned toward +z (up)."""
    T = np.gradient(P[:, :2], axis=0)
    T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
    N = np.stack([-T[:, 1], T[:, 0]], 1)
    return N * np.where(N[:, 1:2] < 0, -1.0, 1.0), T


def _extend(P, by):
    """One station more past each end, `by` beyond it, straight on."""
    t0 = (P[0, :2] - P[1, :2]) / max(np.linalg.norm(P[0, :2] - P[1, :2]), 1e-12)
    t1 = (P[-1, :2] - P[-2, :2]) / max(np.linalg.norm(P[-1, :2] - P[-2, :2]), 1e-12)
    a, b = P[0].copy(), P[-1].copy()
    a[:2] += t0 * by
    b[:2] += t1 * by
    a[2:] = 0.0
    b[2:] = 0.0
    return np.vstack([a, P, b])


# --- the strokes on a face ---------------------------------------------------------------------
class Eye:
    """One eye's strokes in the front view, outward (|x|), for a face state: `lid(s)` gives the
    upper and lower lids' heights at s in -1..1 (head_mesh.Face._lid for that state)."""

    def __init__(self, hf, lid, cls):
        self.hf, self.p = hf, params(cls)
        ex, ew, ez = hf.eye_x, hf.eye_w, hf.eye_z
        up = lambda s: float(lid(np.array(s, float))[0])
        lo = lambda s: float(lid(np.array(s, float))[1])
        self.c_in = np.array([ex - ew, ez + up(-1.0)])
        self.c_out = np.array([ex + ew, ez + up(1.0)])
        chord = self.c_out - self.c_in
        self.D = float(np.linalg.norm(chord))
        self.ax, self.ay = chord / self.D, np.array([-chord[1], chord[0]]) / self.D
        a = np.linspace(0.0, 1.0, 81)
        s = 2 * a - 1
        self.upper = np.stack([ex + ew * s, [ez + up(v) for v in s]], 1)
        self.lower = np.stack([ex + ew * s, [ez + lo(v) for v in s]], 1)
        self.a = a

    def eu(self, a, b):
        """Eye units to the front view (outward)."""
        return self.c_in + np.outer(a, self.ax * self.D) + np.outer(b, self.ay * self.D)

    def lid_stroke(self):
        """The upper lid and wing: centreline points (x, z) and half-widths (m)."""
        p, D = self.p, self.D
        body = LID_EU[:, 0] <= 1.0 + 1e-6
        a_b = LID_EU[body, 0]
        gain = 1 + (p["gain"] - 1) * _smooth(LID_EU[:, 0], GAIN_FROM, GAIN_TO)
        hw = LID_EU[:, 2] * D * p["lid"] * gain
        E = np.stack([np.interp(a_b, self.a, self.upper[:, k]) for k in (0, 1)], 1)
        N, _ = _normals(np.stack([np.interp(np.linspace(0, 1, 81), self.a, self.upper[:, k]) for k in (0, 1)], 1))
        Nb = np.stack([np.interp(a_b, self.a, N[:, k]) for k in (0, 1)], 1)
        Nb /= np.linalg.norm(Nb, axis=1, keepdims=True)
        centre = E + Nb * np.clip(hw[body] - LID_OVERLAP_M, 0.0, None)[:, None]
        centre[0] = E[0]
        # The wing beyond the outer canthus keeps its drawn shape, from where the lid's centre ends;
        # a class's wing is a share of its length.
        wing = LID_EU[~body]
        drawn = self.eu(wing[:, 0], wing[:, 1]) - self.eu([LID_EU[body][-1, 0]], [LID_EU[body][-1, 1]])
        drawn = centre[-1] + drawn * max(p["wing"], 0.08)
        pts = np.vstack([centre, drawn])
        return np.column_stack([pts, hw])

    def lower_stroke(self):
        p, D = self.p, self.D
        hw = LOWER_EU[:, 2] * D * p["lower"]
        a = LOWER_EU[:, 0]
        L = np.stack([np.interp(a, self.a, self.lower[:, k]) for k in (0, 1)], 1)
        N, _ = _normals(np.stack([np.interp(np.linspace(0, 1, 81), self.a, self.lower[:, k]) for k in (0, 1)], 1))
        Na = np.stack([np.interp(a, self.a, N[:, k]) for k in (0, 1)], 1)
        Na /= np.linalg.norm(Na, axis=1, keepdims=True)
        return np.column_stack([L - Na * hw[:, None], hw])  # its upper edge on the rim

    def flicks(self, spine):
        """The drawn lash flicks rooted on the lid's top edge: polylines (x, z, half-width)."""
        out = []
        for f in FLICKS_EU[: self.p["flicks"]]:
            root = self.eu([f[0, 0]], [f[0, 1]])[0]
            k = int(np.argmin(np.linalg.norm(spine[:, :2] - root, axis=1)))
            n, _ = _normals(spine[:, :2])
            base = spine[k, :2] + n[k] * spine[k, 2] * 0.85
            pts = base + (self.eu(f[:, 0], f[:, 1]) - self.eu([f[0, 0]], [f[0, 1]]))
            out.append(np.column_stack([pts, f[:, 2] * self.D]))
        return out


def brow_stroke(hf, side, state, brow_shape, weight=1.0):
    """The type's own brow (head_mesh.brow_shape, which a state raises or lowers), as a centreline
    (outward x, z) and half-widths."""
    top, bot = (np.array(e, float) for e in brow_shape(hf, side, state, ts=BROW_TS))
    top[:, 0], bot[:, 0] = np.abs(top[:, 0]), np.abs(bot[:, 0])
    return np.column_stack([(top + bot) / 2, weight * np.abs(top[:, 1] - bot[:, 1]) / 2])


# --- ribbons: fixed stations and rows ----------------------------------------------------------
class Ribbon:
    """A carrier's grid in the front view: `P` (stations x rows x 2, outward) and its rows'
    offsets across the spine (stations x rows, metres, + toward the spine's normal)."""

    def __init__(self, name, spine, rows):
        self.name, self.spine = name, spine
        N, _ = _normals(spine[:, :2])
        self.rows = rows
        self.P = spine[:, None, :2] + N[:, None, :] * rows[:, :, None]


def lid_ribbons(eye, layout_rows=None):
    """The lid's and the lower lid's ribbons and the strokes on them, for one eye."""
    p = eye.p
    stroke = eye.lid_stroke()
    spine = _resample(_chaikin(stroke), N_LID)
    low = _resample(_chaikin(eye.lower_stroke()), N_LOWER)
    # A face's ribbons are its class's, scaled by its eye's size against line b's.
    k = eye.D / layout_rows["D"] if layout_rows else 1.0
    # Past each end by the reach and more: the lid's inner end turns sharply, and its rows bunch
    # there (the audit found the lid's tip within the range of the strip's end).
    spine = _extend(spine, (REACH_M + END_M) * k)
    low = _extend(low, (REACH_M + END_M) * k)
    if layout_rows is None:
        # The class's rows, from line b: below the spine, the widest half-width and the reach; above
        # it, the half-width, the fringe and the reach, and the flicks' height where they stand.
        hw = spine[:, 2]
        up = hw + p["fringe"] * FRINGE["length_m"] + REACH_M
        for f in eye.flicks(spine[1:-1]):
            for q in f:
                kq = int(np.argmin(np.linalg.norm(spine[:, :2] - q[:2], axis=1)))
                n, _ = _normals(spine[:, :2])
                # The flick's height held over its neighbours (it leans across them), a millimetre
                # more: the audit found its tip within the range of the strip's edge.
                h = float(np.dot(q[:2] - spine[kq, :2], n[kq])) + q[2] + REACH_M + 0.001
                for j in range(max(kq - 3, 0), min(kq + 4, len(spine))):
                    up[j] = max(up[j], h)
        down = np.full(len(spine), float(np.max(hw)) + REACH_M)
        rows = np.stack([-down, -0.5 * down, np.zeros(len(spine)), 0.5 * up, up], 1)
        lrow = np.full(len(low), float(np.max(low[:, 2])) + REACH_M)
        lrows = np.stack([-lrow, np.zeros(len(low)), lrow], 1)
        layout_rows = dict(D=eye.D, lid=rows, lower=lrows)
    return (Ribbon("lid", spine, layout_rows["lid"] * k), Ribbon("lower", low, layout_rows["lower"] * k), stroke, layout_rows)


def brow_ribbon(hf, side, state, brow_shape, layout_rows=None, weight=1.0):
    st = brow_stroke(hf, side, state, brow_shape, weight)
    B = float(hf.brow_w) if hasattr(hf, "brow_w") else float(np.max(st[:, 2]))
    reach = REACH_M * B / layout_rows["B"] if layout_rows else REACH_M
    spine = _extend(st, reach)
    if layout_rows is None:
        r = float(np.max(st[:, 2])) + REACH_M
        layout_rows = dict(B=B, rows=np.tile(np.array([-r, -0.5 * r, 0.0, 0.5 * r, r]) / B, (len(spine), 1)))
    return Ribbon("brow", spine, layout_rows["rows"] * B), st, layout_rows


def core_strip(lid_ribbon):
    """The opaque core inside the lid's ink: stations along the lid, its half-width inset."""
    sp = lid_ribbon.spine[1:-1]
    hw = sp[:, 2]
    hc = np.clip(hw - np.maximum(CORE_INSET * hw, CORE_MARGIN_M), 0.0, None)
    N, _ = _normals(sp[:, :2])
    return sp[:, :2] + N * hc[:, None], sp[:, :2] - N * hc[:, None]


# --- the class's layout on the page ---------------------------------------------------------------
_LAYOUTS = {}


def _uv_grid(hf, rib, off):
    """A ribbon's UVs in metres by its own 3D lengths: along its middle row, and across from it."""
    S, J = rib.P.shape[:2]
    P3 = np.array([hf.project_front(rib.P[:, j])[0] + hf.project_front(rib.P[:, j])[1] * (off + LIFT * np.abs(rib.rows[:, j]))[:, None] for j in range(J)]).transpose(1, 0, 2)
    mid = int(np.argmin(np.abs(rib.rows[0])))
    UV = np.zeros((S, J, 2))
    km = S // 2
    for j in range(J):
        # Each row by its own length (a row bent round a corner is longer or shorter than the
        # spine), all of them meeting the spine's at the middle station.
        along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P3[:, j], axis=0), axis=1))])
        UV[:, j, 0] = along - along[km]
        d = np.linalg.norm(P3[:, j] - P3[:, mid], axis=1)
        UV[:, j, 1] = -np.sign(rib.rows[:, j]) * d  # page v grows downward; the spine's normal points up
    return UV


def layout(cls, types, cage_head, face_types, head_mesh):
    """The class's carriers at rest on its line b, their UVs on the page and the strokes there.
    Cached a process."""
    if cls in _LAYOUTS:
        return _LAYOUTS[cls]
    tid = f"{cls}-b"
    t = types[tid]
    hf = cage_head.CageHead(face_types.apply(t, {}))
    face_lid = lambda s: hf.lid(s)
    eye = Eye(hf, face_lid, cls)
    lid, low, stroke, rows = lid_ribbons(eye)
    brow, bst, brow_rows = brow_ribbon(hf, 1, {}, head_mesh.brow_shape, weight=eye.p["brow"])
    ribs = [(lid, OFF["lid"]), (low, OFF["lid"]), (brow, OFF["brow"])]
    grids = {r.name: _uv_grid(hf, r, off) for r, off in ribs}
    # Islands stacked down the class's cell, each its padding from the last and from the edges.
    cx, cy = CLASS_CELLS[cls]
    y = PAD * TEXEL_M
    place = {}
    for name in ("lid", "lower", "brow"):
        g = grids[name]
        lo, hi = g.reshape(-1, 2).min(0), g.reshape(-1, 2).max(0)
        place[name] = (PAD * TEXEL_M - lo[0], y - lo[1])
        if hi[0] - lo[0] + 2 * PAD * TEXEL_M > CELL * TEXEL_M:
            raise ValueError(f"ink: {cls}'s {name} carrier is {(hi[0] - lo[0]) * 1000:.1f} mm long; its cell holds {CELL * TEXEL_M * 1000 - 2 * PAD * TEXEL_M * 1000:.1f}")
        y += hi[1] - lo[1] + PAD * TEXEL_M
    if y > CELL * TEXEL_M:
        raise ValueError(f"ink: {cls}'s carriers take {y * 1000:.1f} mm of a {CELL * TEXEL_M * 1000:.1f} mm cell")
    uv = {}
    for name, g in grids.items():
        m = g + np.array(place[name])
        uv[name] = (m / TEXEL_M + np.array([cx * CELL, cy * CELL])) / PAGE
    # The strokes in page UV: each point found on its ribbon by its station and row.
    strokes = []

    def on(rib, name, pts):
        """Front-view points (x, z, hw) on a ribbon to page UV and f."""
        N, _ = _normals(rib.spine[:, :2])
        out = []
        for q in pts:
            k = int(np.argmin(np.linalg.norm(rib.spine[:, :2] - q[:2], axis=1)))
            # Refine along the neighbouring segments.
            best = None
            for k0 in (k - 1, k):
                if k0 < 0 or k0 + 1 >= len(rib.spine):
                    continue
                a, b = rib.spine[k0, :2], rib.spine[k0 + 1, :2]
                t = float(np.clip(np.dot(q[:2] - a, b - a) / max(np.dot(b - a, b - a), 1e-18), 0, 1))
                pt = a + t * (b - a)
                n = N[k0] * (1 - t) + N[k0 + 1] * t
                n /= np.linalg.norm(n)
                o = float(np.dot(q[:2] - pt, n))
                d = float(np.linalg.norm(q[:2] - pt - n * o))
                if best is None or d < best[0]:
                    best = (d, k0 + t, o)
            _, kk, o = best
            k0 = min(int(kk), len(rib.spine) - 2)
            t = kk - k0
            u = []
            for kq in (k0, k0 + 1):
                rr = rib.rows[kq]
                j = int(np.clip(np.searchsorted(rr, o) - 1, 0, len(rr) - 2))
                w = (o - rr[j]) / max(rr[j + 1] - rr[j], 1e-12)
                u.append(uv[name][kq, j] * (1 - w) + uv[name][kq, j + 1] * w)
            p = u[0] * (1 - t) + u[1] * t
            out.append([float(p[0]), float(p[1]), float(np.clip(q[2] / RANGE_M, 0.0, 1.0))])
        return out

    sp = lid.spine[1:-1]
    strokes.append(dict(carrier=LID_MAT, part="lid", points=on(lid, "lid", _resample(_chaikin(stroke, 3), 48))))
    for f in eye.flicks(sp):
        strokes.append(dict(carrier=LID_MAT, part="flick", points=on(lid, "lid", _resample(f, 8))))
    strokes += [dict(carrier=LID_MAT, part="fringe", points=on(lid, "lid", s)) for s in fringe(sp, eye)]
    strokes.append(dict(carrier=LID_MAT, part="lower", points=on(low, "lower", _resample(_chaikin(eye.lower_stroke(), 3), 24))))
    strokes.append(dict(carrier=BROW_MAT, part="brow", points=on(brow, "brow", _resample(_chaikin(bst, 3), 40))))
    _LAYOUTS[cls] = dict(rows=rows, brow_rows=brow_rows, uv=uv, strokes=strokes)
    return _LAYOUTS[cls]


def fringe(sp, eye):
    """The lash fringe: a sawtooth along the lid's top edge over FRINGE's span of the eye."""
    p = eye.p
    if p["fringe"] <= 0:
        return []
    N, T = _normals(sp[:, :2])
    L = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(sp[:, :2], axis=0), axis=1))])
    a = np.array([float(np.dot(q - eye.c_in, eye.ax) / eye.D) for q in sp[:, :2]])
    s0, s1 = np.interp(FRINGE["start"], a, L), np.interp(FRINGE["end"], a, L)
    n = max(int((s1 - s0) / FRINGE["spacing_m"]), 1)
    out = []
    for i in range(n):
        s = s0 + (i + 0.5) * (s1 - s0) / n
        c = np.array([np.interp(s, L, sp[:, k]) for k in (0, 1)])
        hw = float(np.interp(s, L, sp[:, 2]))
        nn = np.array([np.interp(s, L, N[:, k]) for k in (0, 1)])
        tt = np.array([np.interp(s, L, T[:, k]) for k in (0, 1)])
        f = (s - s0) / max(s1 - s0, 1e-9)
        env = math.sin(math.pi * min(max(f, 0.0), 1.0)) ** 0.5
        ln = FRINGE["length_m"] * p["fringe"] * env
        root = c + nn * hw * (1 - FRINGE["inset"])
        tip = c + nn * (hw + ln) + tt * FRINGE["lean"] * ln
        out.append(np.array([[*root, FRINGE["root_m"]], [*(0.5 * (root + tip)), FRINGE["root_m"] * 0.45], [*tip, 0.0]]))
    return out


# --- building a face's carriers ------------------------------------------------------------------
def add(m, face, side, state, cage_head, face_types, head_mesh, colours):
    """Add one eye's carriers (lid with lower lid, brow) and its lid core to the mesh `m`, for a
    face state. Their UVs are the class's on the page (Blender's V up)."""
    hf = face.hf
    cls = class_of(hf.t["id"])
    lay = layout(cls, face_types.load()["types"], cage_head, face_types, head_mesh)
    eye = Eye(hf, lambda s: face._lid(side, s, state), cls)
    lid, low, _, _ = lid_ribbons(eye, lay["rows"])
    brow, _, _ = brow_ribbon(hf, side, state, head_mesh.brow_shape, lay["brow_rows"], eye.p["brow"])
    for rib, name, mat, off in ((lid, "lid", "lidink", OFF["lid"]), (low, "lower", "lidink", OFF["lid"]), (brow, "brow", "browink", OFF["brow"])):
        S, J = rib.P.shape[:2]
        pts = rib.P.reshape(-1, 2) * np.array([side, 1.0])
        p, nr = hf.project_front(pts)
        uv = lay["uv"][name].reshape(-1, 2)
        faces = [(k * J + j, k * J + j + 1, (k + 1) * J + j + 1, (k + 1) * J + j) for k in range(S - 1) for j in range(J - 1)]
        lift = (off + LIFT * np.abs(rib.rows)).reshape(-1, 1)
        P = p + nr * lift
        if "faceprop" in PORT and name == "lid":
            P = clear_of_skin(m, P, nr, faces, 0.5 * off)
        m.add(P, (1.0, 1.0, 1.0), [(u, 1.0 - v) for u, v in uv], faces, mat, facing=head_mesh.FORWARD)
    top, bot = core_strip(lid)
    n = len(top)
    pts = np.vstack([top, bot]) * np.array([side, 1.0])
    p, nr = hf.project_front(pts)
    m.add(p + nr * OFF["core"], colours["core"], None, [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)], "line", facing=head_mesh.FORWARD)


def clear_of_skin(m, P, nr, faces, need, rounds=4):
    """Port `faceprop` (S6b), the upper lid and its wing only: a ribbon's quads in front of the skin
    by `need` over their whole face, not only at their corners. Each vertex is projected onto the
    head and lifted, and a flat quad between lifted corners can dip behind a skin that turns away
    fast under it: the wing's end at the temple, sharper once the face is narrowed, sank up to
    2.8 mm behind it and broke the drawn wing at half a blink. Each corner is raised along its
    normal by the most any of its quads lacks, sampled over the quad against the skin facing the
    same way (not the eye opening's turned-in rim), round after round. The lower lid is left as
    built: lifted the same way, its line drew darker and fuller than the unnarrowed type's."""
    try:
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree
    except ImportError:  # outside Blender (cage_accept.py measures the skin alone)
        return P

    V = np.array(m.v)
    tree = BVHTree.FromPolygons(V.tolist(), [f for f, k in zip(m.f, m.fm) if k == "face"])
    P = np.array(P, float)
    grid = [(a, b) for a in (0.0, 0.25, 0.5, 0.75, 1.0) for b in (0.0, 0.25, 0.5, 0.75, 1.0)]
    for _ in range(rounds):
        push = np.zeros(len(P))
        for f in faces:
            A, B, C, D = P[list(f)]
            n = nr[list(f)].mean(axis=0)
            for a, b in grid:
                q = (1 - a) * (1 - b) * A + a * (1 - b) * B + a * b * C + (1 - a) * b * D
                co, sn, _, _ = tree.find_nearest(Vector(q))
                if co is None or float(np.dot(np.array(sn), n)) < 0.5:
                    continue
                lack = need - float(np.dot(q - np.array(co), np.array(sn)))
                if lack > 0:
                    push[list(f)] = np.maximum(push[list(f)], lack)
        if push.max() < 1e-6:
            break
        P = P + nr * push[:, None]
    return P


def page_strokes(types, cage_head, face_types, head_mesh):
    """Every class's strokes on the page, for ink_field.py (`{"size", "strokes"}`), and the manifest."""
    strokes = []
    for cls in CLASSES:
        if f"{cls}-b" not in types:
            continue
        strokes += [dict(points=s["points"], carrier=s["carrier"], part=s["part"], cls=cls) for s in layout(cls, types, cage_head, face_types, head_mesh)["strokes"]]
    manifest = {"pages": {"eyes": PAGE_PATH}, "size": PAGE, "cell": CELL, "density_mm": TEXEL_M * 1000, "classes": CLASS_CELLS, "types": {},
                "range": RANGE_UV, "materials": INK}
    return {"size": [PAGE, PAGE], "strokes": strokes}, manifest


def slop(name):
    """A carrier material's `slop` (HANDMADE_INK v1.2, `ink` with v1.3's `ref`, `m_uv` and `map`)."""
    return {"slot": "eyes", "ink": json.loads(json.dumps(INK[name]))}
