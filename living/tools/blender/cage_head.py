"""The head as a cage: a low-poly grid of quads laid on a face type's landmarks and subdivided.
numpy only (no Blender).

A face type (living/tools/characters/types.json; docs/CHARACTERS.md, "Types and rig") says where a
head's planes and features are, in units of its height H. This module builds that head in the
order a head is built:

1. **The skull and the face block:** at every height the head's plan is a line through the
   type's own points: the midline's front, the front plane beside the nose, the cheek corner (the
   face's half width within 0.15 H of depth), the side (within 0.30 H), the skull's widest line,
   the ear line, and round the back. Between those points the surface is flat: the planes are
   the type's, not a ball's.
2. **The grid:** 28 columns round the head and 22 rows from the crown to the neck. Columns run
   down the midline, the nose's side, the eye's corners, the cheek corner, the side and the
   back; rows lie on the brow, the lids, the cheekbone, the nose's tip and base, the lips, the
   chin and the jaw line, under which two more rows make the plane under the jaw and the neck.
   Lines of the mesh therefore follow the features and the plane breaks.
3. **Sockets and features:** the eye's opening is a hole in the grid whose edge lies on the lids,
   set back in a socket under the brow plane; the nose is a wedge on the two middle columns;
   the mouth is a slit along its row.
4. **Creases:** the cheek corner, the brow line and the jaw line carry a sharpness from the type.
5. **Subdivision:** one level of Catmull-Clark (written here), which keeps boundaries and
   creases. It is a linear operator, so an expression is the same operator on a moved cage.

`CageHead` answers what the rest of the generator asks of a head (head_form.Head's lookups:
`radius`, `normal`, `project_front`, `point`, the eyes', nose's and mouth's numbers, `lid`,
`eye_inside`, `mouth_line`, `beard_cover`), so hair, beards, headwear and the face's paint follow
the new head unchanged.

Positions are in head_form's frame: metres round the head's centre, +Y forward, +Z up, the
character's left at -X. A head is H_FILE high in a character file (a rest figure of 7 heads).
"""

import copy
import math

import numpy as np

import head_form
from head_form import ORIGIN, lerp

H_FILE = 0.2564  # the head's height in a character file, m: the rest figure (1.795 m) is 7 heads
ZC = 0.53  # the head's centre above the chin, in H
YB = 0.36  # how far the bridge of the nose stands ahead of the head's axis, in H
HALF = 15  # columns from the front midline round to the back midline
COLS = 2 * HALF - 2
# Column stations on the head's plan (half of it): the midline, the nose's side, beside the nose,
# four across the eye, the cheek corner, the side, the widest line, the ear line, three round
# the back, the back midline.
C_MID, C_NOSE, C_B, C_E0, C_E1, C_E2, C_E3, C_CORNER, C_SIDE, C_WIDE, C_EAR, C_K1, C_K2, C_K3, C_BACK = range(HALF)
EYE_S = (-0.8, -0.3, 0.3, 0.8)  # where the eye's four columns cross the lids
RIM_FOLD = 0.0025  # how far the lids' edge folds in behind the skin, m on the reference's head (23.3 cm)


def smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


class Plan:
    """A type's head as functions of height: what its sections say, in H (x across, y forward
    from the bridge of the nose, z up from the chin)."""

    def __init__(self, t):
        self.t = t
        s = t["sections"]
        self.z = list(s["z"])
        self.s = s
        self.crown = t["skull"]["crown"]
        e = t["eye"]
        self.eye_z, self.apart, self.eye_w, self.eye_h = e["z"], e["apart"], e["w"], e["h"]
        self.brow_z = t["brow"].get("brow_z", e["z"] + t["brow"]["above_eye"])
        no, m, jaw = t["nose"], t["mouth"], t["jaw"]
        self.nose, self.mouth, self.jaw = no, m, jaw
        self.top_kept = max(z for z, v in zip(self.z, s["w30"]) if v is not None)
        # The midline's profile without the nose: the front plane beside the nose, brought
        # forward to the midline, from the upper lip to the brow.
        self.lift = -self.raw("p08", self.eye_z)  # the midline at the eyes' height is the bridge: depth 0
        self.fore = max(self.raw("p08", z) + self.lift for z in (0.52, 0.64, 0.76))
        self.depth = t["skull"]["depth"]
        self.back_z = t["skull"]["back_z"]
        self.chin_y = self.raw("p00", 0.04) - 0.012

    def raw(self, key, z):
        pts = [(zz, v) for zz, v in zip(self.z, self.s[key]) if v is not None]
        if z <= pts[0][0]:
            return pts[0][1]
        for (za, a), (zb, b) in zip(pts, pts[1:]):
            if z <= zb:
                return lerp(a, b, (z - za) / (zb - za))
        return pts[-1][1]

    def midline(self, z):
        """The front of the midline at height z, the nose left out."""
        lip = self.mouth["z"] + 0.035
        if z <= lip - 0.02:
            return self.raw("p00", z)
        plane = self.raw("p08", z) + self.lift
        if z < lip:
            return lerp(self.raw("p00", z), plane, (z - (lip - 0.02)) / 0.02)
        return plane

    def jaw_line(self, z):
        """The jaw line's depth at height z: straight from the chin to the angle of the jaw."""
        return lerp(self.chin_y - 0.01, -self.jaw["angle_back"], min(max(z / self.jaw["angle_z"], 0.0), 1.0))

    def back(self, z):
        """The back of the skull's depth at height z, and below it the nape's."""
        yb = self.fore - self.depth
        if z >= self.back_z:
            k = min((z - self.back_z) / (self.crown - self.back_z), 1.0)
            return yb + (self.depth / 2) * (1 - math.sqrt(max(1 - k * k, 0.0)))
        return lerp(yb + 0.20, yb, smooth(z / self.back_z) ** 0.7)

    def dome(self, z):
        """Above the highest kept section the head closes to the crown: how much of that
        section's size is left at height z."""
        if z <= self.top_kept:
            return 1.0
        z0 = self.top_kept - 0.22 * (self.crown - self.top_kept) / 0.12
        r = lambda zz: math.sqrt(max(1 - ((zz - z0) / (self.crown - z0)) ** 2, 0.0))
        return r(z) / r(self.top_kept)

    def stations(self, z):
        """The plan's points at height z, front to back: (x, y) for the midline, beside the
        nose, the cheek corner, the side, the widest line, the ear line, the back midline."""
        zk = min(z, self.top_kept)
        w15, w30, wide = (self.raw(k, zk) / 2 for k in ("w15", "w30", "wide"))
        w30, wide = max(w30, w15), max(wide, max(w30, w15))
        a = (0.0, self.midline(zk))
        xb = min(0.08, 0.45 * w15)
        b = (xb, min(self.raw("p08", zk), a[1] - 0.002))
        # The corner, the side and the widest line lie just inside the depths their widths are
        # measured within (0.15, 0.30 and 0.42 H), so the measure finds them.
        pts = [a, b, (w15, -0.143), (w30, -0.288), (wide, -0.408), (wide * 0.985, -0.56), (0.0, self.back(zk))]
        k = self.dome(z)
        if k < 1.0:
            axis = (self.fore + self.back(self.top_kept)) / 2
            pts = [(x * k, axis + (y - axis) * k) for x, y in pts]
        return pts

    @staticmethod
    def front(b, c, fr):
        """A point of the front plane, the share fr of the way from beside the nose (b) to the
        cheek corner (c). The plane is nearly flat and turns back only near the corner: it
        passes 0.62 of the way across at 0.42 of the depth."""
        mx, my = lerp(b[0], c[0], 0.62), lerp(b[1], c[1], 0.42)
        if fr <= 0.62:
            return (lerp(b[0], mx, fr / 0.62), lerp(b[1], my, fr / 0.62))
        return (lerp(mx, c[0], (fr - 0.62) / 0.38), lerp(my, c[1], (fr - 0.62) / 0.38))

    def at(self, z, col, eye_f=None):
        """The plan point of a column at height z: (x, y)."""
        a, b, c, d, e, f, g = self.stations(z)
        if col == C_MID:
            return a
        if col == C_NOSE:
            return (lerp(a[0], b[0], 0.55), lerp(a[1], b[1], 0.55))
        if col == C_B:
            return b
        if C_E0 <= col <= C_E3:
            return self.front(b, c, eye_f[col - C_E0])
        if col in (C_CORNER, C_SIDE, C_WIDE, C_EAR):
            return (c, d, e, f)[col - C_CORNER]
        if col == C_BACK:
            return g
        # Round the back: from the ear line to the back midline.
        phi = math.radians((35.0, 60.0, 78.0)[col - C_K1])
        return (f[0] * math.cos(phi) ** 0.85, f[1] + (g[1] - f[1]) * math.sin(phi))


def subdivision(n_verts, faces, sharp=None, corners=()):
    """One level of Catmull-Clark on a mesh of quads and triangles with boundaries and creases.
    `sharp` maps an edge (a, b with a < b) to its sharpness 0..1; boundary edges are sharp.
    `corners` are vertices that stay where they are. Returns the operator S (new × old, dense:
    new positions are S @ old), the new quads, for each new vertex what it was (('v', old
    vertex), ('e', edge) or ('f', face)), and for each new quad the face it came from."""
    sharp = dict(sharp or {})
    edges, edge_faces = {}, {}
    for fi, f in enumerate(faces):
        for a, b in zip(f, f[1:] + f[:1]):
            e = (min(a, b), max(a, b))
            edges.setdefault(e, len(edges))
            edge_faces.setdefault(e, []).append(fi)
    for e, fs in edge_faces.items():
        if len(fs) == 1:
            sharp[e] = 1.0
    nf, ne = len(faces), len(edges)
    S = np.zeros((n_verts + ne + nf, n_verts))
    what = [("v", i) for i in range(n_verts)] + [None] * ne + [("f", i) for i in range(nf)]
    fpt = lambda fi: n_verts + ne + fi
    for fi, f in enumerate(faces):
        S[fpt(fi), list(f)] = 1.0 / len(f)
    for e, ei in edges.items():
        row = n_verts + ei
        what[row] = ("e", e)
        mid = np.zeros(n_verts)
        mid[list(e)] = 0.5
        k = sharp.get(e, 0.0)
        if len(edge_faces[e]) == 2:
            soft = 0.25 * (2 * mid + S[fpt(edge_faces[e][0])] + S[fpt(edge_faces[e][1])])
        else:
            soft, k = mid, 1.0
        S[row] = lerp(soft, mid, k)
    vert_faces, vert_edges = {}, {}
    for fi, f in enumerate(faces):
        for v in f:
            vert_faces.setdefault(v, []).append(fi)
    for e in edges:
        for v in e:
            vert_edges.setdefault(v, []).append(e)
    corners = set(corners)
    for v in range(n_verts):
        keep = np.zeros(n_verts)
        keep[v] = 1.0
        if v not in vert_faces:
            S[v] = keep
            continue
        es = vert_edges[v]
        hard = [e for e in es if sharp.get(e, 0.0) > 0]
        n = len(vert_faces[v])
        boundary = any(len(edge_faces[e]) == 1 for e in es)
        if boundary:
            soft = keep  # replaced by the crease rule below (a boundary vertex has two boundary edges)
        else:
            q = sum(S[fpt(fi)] for fi in vert_faces[v]) / n
            r = np.zeros(n_verts)
            for e in es:
                r[list(e)] += 0.5 / len(es)
            soft = (q + 2 * r + (n - 3) * keep) / n
        if v in corners or len(hard) >= 3:
            S[v] = keep if (v in corners or boundary) else lerp(soft, keep, max(sharp[e] for e in hard))
        elif len(hard) == 2:
            crease = 0.75 * keep
            for e in hard:
                other = e[0] if e[1] == v else e[1]
                crease[other] += 0.125
            k = 1.0 if boundary else (sharp[hard[0]] + sharp[hard[1]]) / 2
            S[v] = lerp(soft, crease, k)
        else:
            S[v] = soft
    quads, parent = [], []
    for fi, f in enumerate(faces):
        n = len(f)
        for i in range(n):
            a, b, z = f[i], f[(i + 1) % n], f[i - 1]
            quads.append((a, n_verts + edges[(min(a, b), max(a, b))], fpt(fi), n_verts + edges[(min(z, a), max(z, a))]))
            parent.append(fi)
    return S, quads, what, parent


class Cage:
    """A type's head as a grid of quads. `v` are positions in head_form's frame; `faces` the
    quads (and the two poles' triangles); `sharp` the creases; `eye` and `mouth` name the
    vertices of the eyes' edges and the mouth's slit. `closed` keeps the eyes and mouth filled:
    the whole head, for what is laid on it (hair, beards, paint)."""

    def __init__(self, t, state=None, closed=False):
        self.t, self.closed = t, closed
        self.H = H_FILE
        state = state or {}
        p = Plan(t)
        self.plan = p
        e, no, m, jaw, planes = t["eye"], t["nose"], t["mouth"], t["jaw"], t["planes"]
        lid_top, lid_bot = p.eye_z + 0.50 * p.eye_h, p.eye_z - 0.50 * p.eye_h  # the type's eye height is the opening's middle
        cheek_z = min(0.28, lid_bot - 0.045)
        # Where the eye's columns lie across the front plane, as shares of it at the eye's height.
        _, b, c, *_ = p.stations(p.eye_z)
        self.eye_f = [min(max((p.apart / 2 + s * p.eye_w / 2 - b[0]) / (c[0] - b[0]), 0.04), 0.96) for s in EYE_S]
        rows = []  # (name, height or share, kind)
        eye_row = p.eye_z - 0.12 * p.eye_h
        top = [("crown1", lerp(p.brow_z, p.crown, 0.90)), ("crown2", lerp(p.brow_z, p.crown, 0.72)), ("crown3", lerp(p.brow_z, p.crown, 0.50)), ("forehead", lerp(p.brow_z, p.crown, 0.24)),
               ("brow", p.brow_z + 0.004), ("crease", max(lid_top + 0.022, lerp(lid_top, p.brow_z, 0.45))), ("lid_top", lid_top), ("eye", eye_row), ("lid_bot", lid_bot), ("under", lid_bot - 0.032), ("cheek", cheek_z)]
        shares = [("tip", min(no["tip_z"] / cheek_z, 0.90)), ("base", no["base_z"] / cheek_z), ("lip_up", (m["z"] + 0.024) / cheek_z), ("mouth", m["z"] / cheek_z), ("lip_low", (m["z"] - 0.024) / cheek_z),
                  ("chin_top", m["z"] * 0.50 / cheek_z), ("chin", 0.028 / cheek_z), ("jaw", 0.0)]
        self.row_names = ["pole"] + [n for n, _ in top] + [n for n, _ in shares] + ["under_jaw", "neck"]
        R = {n: i for i, n in enumerate(self.row_names)}
        self.R = R
        nrows = len(self.row_names)

        # Where each column meets the jaw line: the height at which its own depth is the jaw
        # line's. Below the angle of the jaw the head ends there; nothing lies behind it. The
        # columns behind the ear end on the nape.
        jz = []
        for col in range(HALF):
            if col >= C_EAR:
                jz.append((jaw["angle_z"] + 0.03, 0.20, 0.14, 0.09, 0.07)[col - C_EAR])
                continue
            lo, hi = 0.0, jaw["angle_z"]
            if p.at(lo, col, self.eye_f)[1] >= p.jaw_line(lo):
                jz.append(0.0)
                continue
            for _ in range(30):
                mid = (lo + hi) / 2
                if p.at(mid, col, self.eye_f)[1] < p.jaw_line(mid):
                    lo = mid
                else:
                    hi = mid
            jz.append(hi)
        self.jaw_z = jz
        grid = np.zeros((nrows, HALF, 3))  # x, y, z in H
        for name, z in top:
            for col in range(HALF):
                x, y = p.at(z, col, self.eye_f)
                grid[R[name], col] = (x, y, z)
        for name, share in shares:
            for col in range(HALF):
                z = lerp(jz[col], cheek_z, share)
                x, y = p.at(z, col, self.eye_f)
                grid[R[name], col] = (x, y, z)
        # Under the jaw and the neck's ring.
        # The neck's ring meets the neck's own tube (person.py make_neck: 5.35 cm round at 1.49 m, the chin at 1.535 m).
        neck_y, neck_r, neck_z = -0.018 / self.H - YB + 0.004 / self.H, 0.0545 / self.H, (1.490 - 1.535) / self.H
        for col in range(HALF):
            x, y, z = grid[R["cheek"], col]
            th = math.atan2(x, y - neck_y)
            nk = np.array([neck_r * math.sin(th), neck_y + neck_r * math.cos(th), neck_z])
            j = grid[R["jaw"], col]
            u = lerp(j, nk, 0.5)
            u[2] = lerp(j[2], neck_z, 0.42) - 0.012 * (col < C_WIDE)
            grid[R["under_jaw"], col] = u
            grid[R["neck"], col] = nk
        # The socket: the eye's edge sits behind the brow and the cheek; the rows round it lead in.
        # The eye's edge sits behind the surface over it (0.12 H above) and under it (0.10 H below) by the type's two depths.
        socket = 0.5 * (e["behind_brow"] + e["behind_cheek"])
        # Those depths are to the lid's folded-in edge (the reference's is measured there), so the lid itself is a fold nearer.
        fold = RIM_FOLD / 0.233
        rim_y = lambda x: 0.5 * ((self._plane_y(p, x, p.eye_z + 0.12) - e["behind_brow"]) + (self._plane_y(p, x, p.eye_z - 0.10) - e["behind_cheek"])) + fold + 0.007
        tilt = math.tan(math.radians(e.get("tilt_deg", 0.0)))
        lids = state.get("lids")

        def lid(s, upper):
            """A lid's height at s (-1 the inner corner to 1 the outer), in H: the type's own shape."""
            z = (0.62 if upper else -0.38) * p.eye_h * (1 - s * s) ** (0.60 if upper else 0.78)
            return p.eye_z - 0.12 * p.eye_h + z + tilt * s * p.eye_w / 2

        for k, s in enumerate(EYE_S):
            col = C_E0 + k
            x = p.apart / 2 + s * p.eye_w / 2
            for row, upper in (("lid_top", True), ("lid_bot", False)):
                grid[R[row], col] = (x, rim_y(x), lid(s, upper))
            for row, share in (("crease", 0.45), ("under", 0.40)):
                grid[R[row], col, 1] -= socket * share
        for col, s in ((C_E0, -1.0), (C_E3, 1.0)):  # the corners, on the eye's own row
            x = p.apart / 2 + s * p.eye_w / 2
            grid[R["eye"], col] = (x, rim_y(x) + 0.08 * socket, p.eye_z - 0.12 * p.eye_h + tilt * s * p.eye_w / 2)
        grid[R["eye"], C_B, 1] -= socket * 0.30
        # The nose: a wedge on the midline and the column beside it, from the bridge to the base.
        tip = np.array([0.0, no["tip_y"], no["tip_z"]])
        half_w = no["width"] / 2
        for name in ("under", "cheek", "tip", "base"):
            z = grid[R[name], C_MID, 2]
            ridge = lerp(0.0, no["tip_y"], smooth((p.eye_z - z) / max(p.eye_z - no["tip_z"], 1e-6)) ** 1.25) if z >= no["tip_z"] else lerp(grid[R[name], C_MID, 1] + 0.012, no["tip_y"] - 0.03, 0.75)
            grid[R[name], C_MID, 1] = max(ridge, grid[R[name], C_MID, 1])
            k = smooth((p.eye_z - z) / max(p.eye_z - no["base_z"], 1e-6))
            wx = lerp(0.022, half_w, k)
            base_y = self._plane_y(p, wx, z)
            grid[R[name], C_NOSE, 0] = wx
            grid[R[name], C_NOSE, 1] = lerp(base_y, grid[R[name], C_MID, 1], 0.42 * k) if name != "base" else base_y + 0.008
        grid[R["tip"], C_MID] = tip
        grid[R["base"], C_MID] = (0.0, no["tip_y"] - 0.034, no["base_z"])
        # The mouth: its row runs corner to corner; the lips stand a little forward.
        mw = m["w"] / 2
        mouth_open, wide_, smile = state.get("mouth", 0.0), state.get("wide", 0.0), state.get("smile", 0.0)
        for name, k in (("lip_up", 1.0), ("mouth", 0.0), ("lip_low", 0.85)):
            for col, share in ((C_MID, 0.0), (C_NOSE, 0.52), (C_B, 1.0)):
                x = mw * share * (1.12 if name != "mouth" and col == C_B else 1.0) * (1 + wide_ * (col == C_B))
                z = grid[R[name], col, 2] if name != "mouth" else m["z"] + (m.get("curve", 0.0) + smile) * share * share
                y = self._plane_y(p, x, z, lips=True) + m["lips"] * 0.34 * k * (1 - 0.6 * share) - 0.003 * (name == "mouth")
                grid[R[name], col] = (x, y, z)
        self.grid_h = grid
        # Both halves, into head_form's frame.
        H = self.H
        frame = lambda q: np.array([q[0] * H, (q[1] + YB) * H, (q[2] - ZC) * H])
        index, verts = {}, []

        def vid(r, j):
            j %= COLS
            if r == 0:
                key = (0, 0)
            else:
                key = (r, j)
            if key not in index:
                index[key] = len(verts)
                if r == 0:
                    verts.append(frame((0.0, (p.fore + p.back(p.top_kept)) / 2, p.crown)))
                else:
                    col = j if j < HALF else COLS - j
                    q = grid[r, col].copy()
                    if j >= HALF:
                        q[0] = -q[0]
                    verts.append(frame(q))
            return index[key]

        faces, face_row = [], []
        hole = lambda r, col: (not closed) and R["lid_top"] <= r < R["lid_bot"] and C_E0 <= col < C_E3
        for r in range(nrows - 1):
            for j in range(COLS):
                col = j if j < HALF - 1 else COLS - 1 - j  # the column this quad starts at, on either half
                if hole(r, col):
                    continue
                if r == 0:
                    faces.append((vid(0, 0), vid(1, j + 1), vid(1, j)))
                else:
                    faces.append((vid(r, j), vid(r, j + 1), vid(r + 1, j + 1), vid(r + 1, j)))
                face_row.append(r)
        self.vid = vid
        self.v = np.array(verts)
        # The lids as the face has them (its own lid shape, and an expression's: each eye its own).
        if lids is not None and not closed:
            for side in (1, -1):
                js = [c if side > 0 else COLS - c for c in range(C_E0, C_E3 + 1)]
                for k, s in enumerate(EYE_S):
                    for row, upper in (("lid_top", True), ("lid_bot", False)):
                        self.v[vid(R[row], js[k]), 2] = (p.eye_z - 0.12 * p.eye_h - ZC) * H + float(lids(side, s, upper))
                for j, s in ((js[0], -1.0), (js[-1], 1.0)):
                    self.v[vid(R["eye"], j), 2] = (p.eye_z - 0.12 * p.eye_h - ZC) * H + float(lids(side, s, True))
        # The mouth's slit: the row's vertices between the corners get a lower copy.
        self.mouth_up, self.mouth_lo = [], []
        if not closed:
            lower = {}
            for j in (COLS - 1, 0, 1):
                a = vid(R["mouth"], j)
                lower[a] = len(self.v) + len(lower)
                self.mouth_up.append(a)
            self.v = np.concatenate([self.v, self.v[list(lower)]])
            self.mouth_lo = list(lower.values())
            below = {vid(R["lip_low"], j) for j in range(-2, 3)}
            faces = [tuple(lower.get(v, v) for v in f) if any(v in below for v in f) else f for f in faces]
        # Outward winding, carried from face to face across shared edges. Asking each face
        # whether it looks away from the head's middle is wrong where the surface turns under
        # (below the nose's tip, under the chin): those faces were turned inward and showed as
        # a hole from below. One face that cannot be wrong starts it: the one furthest forward.
        faces = [tuple(f) for f in faces]
        edge = {}
        for i, f in enumerate(faces):
            for a, b in zip(f, f[1:] + f[:1]):
                edge.setdefault((min(a, b), max(a, b)), []).append(i)
        seed = max(range(len(faces)), key=lambda i: self.v[list(faces[i])].mean(axis=0)[1])
        q = self.v[list(faces[seed])]
        if np.cross(q[1] - q[0], q[2] - q[0])[1] < 0:
            faces[seed] = tuple(reversed(faces[seed]))
        done, todo = {seed}, [seed]
        while todo:
            i = todo.pop()
            f = faces[i]
            for a, b in zip(f, f[1:] + f[:1]):
                for k in edge[(min(a, b), max(a, b))]:
                    if k in done:
                        continue
                    g = faces[k]
                    if any((x, y) == (a, b) for x, y in zip(g, g[1:] + g[:1])):  # the same way along the shared edge: turn it
                        faces[k] = tuple(reversed(g))
                    done.add(k)
                    todo.append(k)
        assert len(done) == len(faces), "the cage is one connected surface"
        self.faces = faces
        self.face_row = face_row  # the row each face starts at: from the jaw line down it is the neck's skin, not the face's
        self.neck_ring = [vid(R["neck"], j) for j in range(COLS)]
        # Creases.
        sharp = {}

        def crease(a, b, k):
            if a != b and k > 0:
                sharp[(min(a, b), max(a, b))] = max(k, sharp.get((min(a, b), max(a, b)), 0.0))

        for j in (C_CORNER, COLS - C_CORNER):  # the cheek corner, from the brow to the jaw line
            for r in range(R["brow"], R["jaw"]):
                crease(vid(r, j), vid(r + 1, j), planes["cheek_corner"])
        for j in range(COLS):  # the brow line across the front, the jaw line to the angle of the jaw
            col = min(j, COLS - 1 - j)
            if col < C_CORNER:
                crease(vid(R["brow"], j), vid(R["brow"], j + 1), planes["brow_line"] * 0.8)
            if col < C_WIDE:
                crease(vid(R["jaw"], j), vid(R["jaw"], j + 1), planes["jaw_line"])
        self.sharp = sharp
        self.corners = []
        self.eye = {}
        if not closed:
            for side, js in ((1, list(range(C_E0, C_E3 + 1))), (-1, [COLS - c for c in range(C_E0, C_E3 + 1)])):
                loop = [vid(R["eye"], js[0])] + [vid(R["lid_top"], j) for j in js] + [vid(R["eye"], js[-1])] + [vid(R["lid_bot"], j) for j in reversed(js)]
                self.eye[side] = loop
                self.corners += [loop[0], loop[5]]
            self.corners += [vid(R["mouth"], 2), vid(R["mouth"], COLS - 2)]
        # A mouth that opens: the lower lip, chin and jaw drop about the jaw's hinge.
        self._sub = None
        if mouth_open and not closed:
            Hm = mouth_open
            low = set(self.mouth_lo) | {vid(r, j) for r in range(R["lip_low"], R["jaw"] + 1) for j in list(range(0, C_SIDE + 1)) + list(range(COLS - C_SIDE, COLS))}
            for v in low:
                q = self.v[v]
                fall = float(smooth((q[1] - 0.01) / 0.07))
                self.v[v, 2] -= Hm * fall
                self.v[v, 1] -= 0.22 * Hm * fall
        self.fit()

    @staticmethod
    def _plane_y(p, x, z, lips=False):
        """The front plane's depth at (x, z): between the midline, the plane beside the nose and the cheek corner."""
        a, b, c, *_ = p.stations(z)
        if x <= b[0]:
            return lerp(a[1], b[1], x / max(b[0], 1e-6))
        return Plan.front(b, c, min((x - b[0]) / max(c[0] - b[0], 1e-6), 1.0))[1]

    def subdivided(self):
        """The cage after one level: the operator, the quads, what each vertex was, each quad's face."""
        if self._sub is None:
            self._sub = subdivision(len(self.v), self.faces, self.sharp, self.corners)
        return self._sub

    def fit(self, rounds=5):
        """Move the cage so that its subdivided surface passes through the points it was laid
        on: subdivision draws a smooth vertex in, and this pushes it back out."""
        S = self.subdivided()[0]
        n = len(self.v)
        target = self.v.copy()
        v = self.v.copy()
        for _ in range(rounds):
            v += target - S[:n] @ v
        self.v = v


def preview(path, v, faces, size=520, views=("front", "three-quarter", "side"), colours=None):
    """A flat-shaded picture of a mesh, to judge a cage without the game (Pillow)."""
    from PIL import Image, ImageDraw

    v = np.asarray(v, float)
    img = Image.new("RGB", (size * len(views), size), (120, 138, 160))
    d = ImageDraw.Draw(img)
    light = np.array([0.35, 0.55, 0.75])
    light /= np.linalg.norm(light)
    centre = (v.max(axis=0) + v.min(axis=0)) / 2
    span = (v.max(axis=0) - v.min(axis=0)).max() * 1.08
    for k, view in enumerate(views):
        a = math.radians(dict(front=0.0, side=90.0, back=180.0).get(view, 38.0))
        # The camera looks along -Y turned by a about Z; screen x to the camera's right.
        right = np.array([math.cos(a), -math.sin(a), 0.0])
        fwd = np.array([-math.sin(a), -math.cos(a), 0.0])  # from the camera into the scene
        tris = []
        for fi, f in enumerate(faces):
            q = v[list(f)]
            n = np.cross(q[1] - q[0], q[2] - q[0])
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                continue
            n /= ln
            if np.dot(n, fwd) > 0.05:
                continue
            world_light = right * light[0] - fwd * light[2] + np.array([0, 0, 1.0]) * light[1]
            shade = 0.38 + 0.62 * max(float(np.dot(n, world_light / np.linalg.norm(world_light))), 0.0)
            base = np.array(colours[fi] if colours is not None else (236, 200, 178), float)
            pts = [(k * size + size / 2 + float(np.dot(p_ - centre, right)) / span * size, size / 2 - (p_[2] - centre[2]) / span * size) for p_ in q]
            tris.append((float(np.dot(q.mean(axis=0), fwd)), pts, tuple(int(c * shade) for c in base)))
        for _, pts, col in sorted(tris, key=lambda t: -t[0]):
            d.polygon(pts, fill=col, outline=tuple(int(c * 0.82) for c in col))
    img.save(path)
    return path


# ---------------------------------------------------------------------------------------------
# What the rest of the generator asks of a head.


def _triangles(faces):
    out = []
    for f in faces:
        out.append((f[0], f[1], f[2]))
        if len(f) == 4:
            out.append((f[0], f[2], f[3]))
    return np.array(out)


def radial_grid(v, tris, step=2.0):
    """The distance from ORIGIN to a closed mesh along a grid of directions (degrees round, degrees
    up), by casting each ray against every triangle. Directions that leave through the neck take
    the nearest answer above them."""
    az = np.arange(-180.0, 180.0, step)
    el = np.arange(-90.0, 90.0 + 1e-6, step)
    aa, ee = np.meshgrid(np.radians(az), np.radians(el), indexing="ij")
    d = np.stack([-np.sin(aa) * np.cos(ee), np.cos(aa) * np.cos(ee), np.sin(ee)], axis=-1).reshape(-1, 3)
    v0 = v[tris[:, 0]]
    e1, e2 = v[tris[:, 1]] - v0, v[tris[:, 2]] - v0
    s = ORIGIN - v0
    q = np.cross(s, e1)
    out = np.full(len(d), np.nan)
    for a in range(0, len(d), 384):
        dd = d[a : a + 384]
        p = np.cross(dd[:, None, :], e2[None, :, :])
        det = np.einsum("ntk,tk->nt", p, e1)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        u = np.einsum("ntk,tk->nt", p, s) * inv
        w = np.einsum("nk,tk->nt", dd, q) * inv
        t = np.einsum("tk,tk->t", e2, q)[None, :] * inv
        hit = ok & (u >= -1e-6) & (w >= -1e-6) & (u + w <= 1 + 1e-6) & (t > 1e-6)
        t = np.where(hit, t, np.inf)
        best = t.max(axis=1, where=hit, initial=-1.0)  # the outermost surface along the ray
        out[a : a + 384] = np.where(best > 0, best, np.nan)
    R = out.reshape(len(az), len(el))
    for i in range(len(az)):
        col = R[i]
        good = np.where(~np.isnan(col))[0]
        col[np.isnan(col)] = np.interp(np.where(np.isnan(col))[0], good, col[good])
    return az, el, R


class CageHead(head_form.Head):
    """A type's head, answering what head_form.Head answers: the surface along a direction, its
    normal, points of the front view, and the features' numbers in head_form's units. `t` is a
    type's record (or a person's: face_types.apply)."""

    def __init__(self, t, masc=0.0, child=0.0, elder=0.0):
        self.t = t
        self.masc, self.child, self.elder, self.m, self.style = masc, child, elder, lerp(masc, 0.3, child), 1.0
        H = H_FILE
        self.H = H
        hz = lambda z: (z - ZC) * H
        e, b, no, m, ear = t["eye"], t["brow"], t["nose"], t["mouth"], t["ear"]
        self.chin_z, self.top_z = hz(0.0), hz(t["skull"]["crown"])
        self.L = (e["z"] * H) / 0.133
        self.eye_x, self.eye_z, self.eye_w = e["apart"] / 2 * H, hz(e["z"] - 0.12 * e["h"]), e["w"] / 2 * H  # eye_z is the lids' zero; the opening's middle is the type's eye height
        self.eye_up, self.eye_lo = 0.62 * e["h"] * H, 0.38 * e["h"] * H
        self.eye_tilt = math.tan(math.radians(e.get("tilt_deg", 0.0)))
        self.eye_peak = e.get("shape", 0.0)
        self.iris_r = min(0.60 * (self.eye_up + self.eye_lo), e["iris"] * 1.25 * self.eye_w)
        brow_z = b.get("brow_z", e["z"] + b["above_eye"])
        self.brow_w = b["thick"] * H
        self.brow_arch = 0.0048 * (b["arch"] / 0.3)
        self.brow_up = hz(brow_z) - self.eye_z - self.eye_up - 0.5 * self.brow_arch
        self.brow_tilt = math.tan(math.radians(b["tilt_deg"])) * 0.020
        self.brow_len = b.get("length", 1.0)
        self.brow_ridge = 0.0
        self.nasion_z, self.nose_tip_z, self.nose_base_z = hz(no["bridge_z"]), hz(no["tip_z"]), hz(no["base_z"])
        self.nose_wid = (no["width"] / 2 * H) / 0.0112
        self.nose_len = self.nose_out = self.nose_curve = 1.0
        self.nose_turn = 0.0
        self.mouth_z, self.mouth_w = hz(m["z"]), m["w"] / 2 * H
        self.lip = m["lips"] / 0.026
        self.mouth_curve = m.get("curve", 0.0) * H
        self.ear_size, self.ear_out = ear["size"] / 0.235 * (H / 0.246) * 0.92, ear["out_deg"]
        self.cheek = self.jowl = self.chin_f = 0.0
        # The whole head, eyes and mouth filled in: what hair, beards, headwear and paint lie on.
        cage = Cage(t, closed=True)
        S, quads, _, _ = cage.subdivided()
        self.base_pos = S @ cage.v
        self.base_quads = [list(q) for q in quads]
        self.cage = cage
        self._az, self._el, self._R = radial_grid(self.base_pos, _triangles(quads))

    def radius(self, dirs):
        d = np.asarray(dirs, float)
        az = np.degrees(np.arctan2(-d[:, 0], d[:, 1]))
        el = np.degrees(np.arcsin(np.clip(d[:, 2] / np.maximum(np.linalg.norm(d, axis=1), 1e-12), -1, 1)))
        step = self._az[1] - self._az[0]
        fa = (az + 180.0) / step
        fe = np.clip((el + 90.0) / step, 0, len(self._el) - 1 - 1e-6)
        ia, ie = np.floor(fa).astype(int), np.floor(fe).astype(int)
        ta, te = fa - ia, fe - ie
        i0, i1 = ia % len(self._az), (ia + 1) % len(self._az)
        R = self._R
        return (R[i0, ie] * (1 - ta) + R[i1, ie] * ta) * (1 - te) + (R[i0, ie + 1] * (1 - ta) + R[i1, ie + 1] * ta) * te

    def f(self, p):
        """Negative inside the head, positive outside (the distance along the ray from its middle)."""
        q = np.asarray(p, float) - ORIGIN
        r = np.maximum(np.linalg.norm(q, axis=1), 1e-9)
        return r - self.radius(q / r[:, None])

    def normal(self, p):
        e = 2.5e-3
        g = np.stack([self.f(p + np.array(v) * e) - self.f(p - np.array(v) * e) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))], axis=1)
        return g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-12)

    def eye_pivot(self, side):
        """Where an eye's bone sits: behind the iris and nearer the midline, as the reference's
        (5.5 cm behind, 2 cm out): turning it slides the iris across the opening."""
        cx, cz = head_mesh.iris_centre(self, side)
        y = self.project_front([(side * self.eye_x, self.eye_z)])[0][0][1]
        return np.array([cx * 0.45, y - 0.055 * self.H / 0.233, cz])


# ---------------------------------------------------------------------------------------------
# Identity: the rig's bones on a head, and each point's share of them.

import head_mesh  # noqa: E402  (after CageHead: head_mesh does not need this module)


def rig_pivots(hf):
    """Where each identity bone sits on a head, in head_form's frame: {bone: position}. A paired
    bone's name ends _L (the character's left, -X) or _R."""
    t, H = hf.t, hf.H
    e, b, no, m, jaw = t["eye"], t["brow"], t["nose"], t["mouth"], t["jaw"]
    hz = lambda z: (z - ZC) * H
    brow_z = b.get("brow_z", e["z"] + b["above_eye"])
    front = lambda x, z: hf.project_front([(x, z)])[0][0]
    p = Plan(t)
    out = {"J_Id_Cranium": np.array([0.0, (p.fore - p.depth / 2 + YB) * H, hz(brow_z)]), "J_Id_Forehead": front(0.0, hz(lerp(brow_z, t["skull"]["crown"], 0.35))), "J_Id_Glabella": front(0.0, hz(brow_z)),
           "J_Id_Face": front(0.0, hz(no["bridge_z"])), "J_Id_Jaw": np.array([0.0, (-jaw["angle_back"] - 0.04 + YB) * H, hz(e["z"] - 0.06)]), "J_Id_Chin": front(0.0, hz(0.02)),
           "J_Id_Nose": front(0.0, hz(lerp(no["bridge_z"], no["tip_z"], 0.5))), "J_Id_NoseTip": front(0.0, hz(no["tip_z"])), "J_Id_Mouth": front(0.0, hz(m["z"]))}
    s = t["sections"]
    w = lambda key, z: Plan(t).raw(key, z) / 2 * H
    for sx, side in ((-1, "L"), (1, "R")):
        out[f"J_Id_Orbit_{side}"] = front(sx * hf.eye_x, hf.eye_z)
        out[f"J_Id_Brow_{side}"] = front(sx * hf.eye_x, hz(brow_z))
        out[f"J_Id_Corner_{side}"] = np.array([sx * w("w15", e["z"]), (-0.15 + YB) * H, hf.eye_z])
        out[f"J_Id_Zygoma_{side}"] = np.array([sx * w("w30", 0.28) * 0.96, (-0.26 + YB) * H, hz(0.28)])
        out[f"J_Id_Cheek_{side}"] = front(sx * w("w15", 0.18) * 0.72, hz(0.18))
        out[f"J_Id_Gonion_{side}"] = np.array([sx * w("wide", jaw["angle_z"]), (-jaw["angle_back"] + YB) * H, hz(jaw["angle_z"])])
        out[f"J_Id_MouthCorner_{side}"] = front(sx * hf.mouth_w, hf.mouth_z)
        out[f"J_Id_Ear_{side}"] = np.array([sx * w("wide", t["ear"]["z"]), (-t["ear"]["back"] + YB) * H, hz(t["ear"]["z"])])
    return out


RIG_PARENT = {"J_Id_Cranium": "J_Bip_C_Head", "J_Id_Forehead": "J_Id_Cranium", "J_Id_Glabella": "J_Id_Cranium", "J_Id_Face": "J_Bip_C_Head", "J_Id_Jaw": "J_Id_Face", "J_Id_Chin": "J_Id_Jaw",
              "J_Id_Nose": "J_Id_Face", "J_Id_NoseTip": "J_Id_Nose", "J_Id_Mouth": "J_Id_Face"}
for _side in "LR":
    RIG_PARENT.update({f"J_Id_Orbit_{_side}": "J_Id_Face", f"J_Id_Brow_{_side}": "J_Id_Face", f"J_Id_Corner_{_side}": "J_Id_Face", f"J_Id_Zygoma_{_side}": "J_Id_Face", f"J_Id_Cheek_{_side}": "J_Id_Face",
                       f"J_Id_Gonion_{_side}": "J_Id_Jaw", f"J_Id_MouthCorner_{_side}": "J_Id_Mouth", f"J_Id_Ear_{_side}": "J_Bip_C_Head"})


def identity_weights(hf, pts, pivots=None):
    """Each point's share of the identity bones: a list of {bone: weight} summing to 1, at most
    four bones a point.

    Features come first, each riding its own bone in full: an eye's opening and the skin round
    it its orbit, the brow its brow bone, the nose, the mouth and its corners, the chin. Each
    field is 1 over the feature and falls to 0 a little way off, and a bone takes its share of
    what the bones before it left. Then the points that shape the outline (cheek corner,
    cheekbone, cheek, the jaw's angle, forehead, between the brows), and last the three broad
    bones that divide what is left: the cranium above the brow line, the jaw (the lower face
    below a line from the mouth back up to the jaw's angle), the face block in front, and the
    head's own bone for the back of the head below the brows."""
    pts = np.asarray(pts, float).reshape(-1, 3)
    piv = pivots or rig_pivots(hf)
    H = hf.H
    t = hf.t
    hz = lambda z: (z - ZC) * H
    brow_z = hz(t["brow"].get("brow_z", t["eye"]["z"] + t["brow"]["above_eye"]))
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    n = len(pts)

    def fall(d, r0, r1):
        """1 within r0, 0 beyond r1 (of a distance already in H)."""
        return 1.0 - smooth((d - r0) / max(r1 - r0, 1e-9))

    def ball(name, r0, r1, side=True):
        c = piv[name]
        w = fall(np.linalg.norm(pts - c, axis=1) / H, r0, r1)
        if side and name.endswith(("_L", "_R")):
            w = w * (np.sign(c[0]) * x > -0.003)
        return w

    fields = []  # in order of precedence
    eh = (hf.eye_up + hf.eye_lo) / 2
    for sd in "LR":
        c = piv[f"J_Id_Orbit_{sd}"]
        ex = np.sign(c[0]) * hf.eye_x
        ez = hf.eye_z + (hf.eye_up - hf.eye_lo) / 2
        d = np.hypot((x - ex) / (hf.eye_w * 1.22), (z - ez) / (eh * 1.55)) * (np.abs(y - c[1]) < 0.20 * H) + 9.0 * (np.abs(y - c[1]) >= 0.20 * H)
        fields.append((f"J_Id_Orbit_{sd}", fall(d, 1.0, 1.9) * (np.sign(c[0]) * x > -0.003)))
    for sd in "LR":
        c = piv[f"J_Id_Brow_{sd}"]
        d = np.hypot((x - c[0]) / (hf.eye_w * 1.45), (z - c[2]) / (0.030 * H)) + 9.0 * (np.abs(y - c[1]) >= 0.16 * H)
        fields.append((f"J_Id_Brow_{sd}", fall(d, 1.0, 1.8) * (np.sign(c[0]) * x > -0.003)))
    fields.append(("J_Id_NoseTip", ball("J_Id_NoseTip", 0.022, 0.060)))
    bridge, tip = piv["J_Id_Face"], piv["J_Id_NoseTip"]
    along = np.clip((bridge[2] - z) / max(bridge[2] - tip[2] + 0.03 * H, 1e-6), 0, 1)
    d = np.hypot(x / (0.050 * H), np.maximum(np.maximum(z - bridge[2], tip[2] - 0.035 * H - z), 0) / (0.03 * H)) + 9.0 * (y < piv["J_Id_Nose"][1] - 0.10 * H)
    fields.append(("J_Id_Nose", fall(d, 1.0, 2.0) * (0.35 + 0.65 * along)))
    for sd in "LR":
        fields.append((f"J_Id_MouthCorner_{sd}", ball(f"J_Id_MouthCorner_{sd}", 0.012, 0.040)))
    c = piv["J_Id_Mouth"]
    d = np.hypot(x / (hf.mouth_w * 1.15), (z - c[2]) / (0.034 * H)) + 9.0 * (y < c[1] - 0.10 * H)
    fields.append(("J_Id_Mouth", fall(d, 1.0, 2.0)))
    fields.append(("J_Id_Chin", ball("J_Id_Chin", 0.045, 0.125)))
    for sd in "LR":
        fields += [(f"J_Id_Ear_{sd}", ball(f"J_Id_Ear_{sd}", 0.085, 0.14)), (f"J_Id_Corner_{sd}", ball(f"J_Id_Corner_{sd}", 0.03, 0.13) * 0.8), (f"J_Id_Zygoma_{sd}", ball(f"J_Id_Zygoma_{sd}", 0.035, 0.15) * 0.8),
                   (f"J_Id_Cheek_{sd}", ball(f"J_Id_Cheek_{sd}", 0.03, 0.12) * 0.8), (f"J_Id_Gonion_{sd}", ball(f"J_Id_Gonion_{sd}", 0.05, 0.16) * 0.85)]
    fields += [("J_Id_Glabella", ball("J_Id_Glabella", 0.03, 0.09) * 0.8), ("J_Id_Forehead", ball("J_Id_Forehead", 0.07, 0.24) * 0.8)]
    # What is left goes to the broad bones.
    up = smooth((z - (brow_z - 0.05 * H)) / (0.11 * H))
    depth = y / H - YB
    front = smooth((depth + 0.50) / 0.14)
    jaw_top = hf.mouth_z + 0.035 * H + smooth((-0.05 - depth) / 0.33) * (hz(t["jaw"]["angle_z"] + 0.08) - hf.mouth_z - 0.035 * H)
    jaw = smooth((jaw_top - z) / (0.07 * H)) * front
    fields += [("J_Id_Cranium", up), ("J_Id_Jaw", (1 - up) * jaw), ("J_Id_Face", (1 - up) * front * (1 - jaw)), ("J_Bip_C_Head", np.ones(n))]
    left = np.ones(n)
    shares = []
    for name, f in fields:
        w = np.clip(f, 0, 1) * left
        left = left - w
        shares.append((name, w))
    out = []
    for i in range(n):
        w = sorted(((name, float(v[i])) for name, v in shares if v[i] > 0.015), key=lambda kv: -kv[1])[:4]
        total = sum(v for _, v in w) or 1.0
        out.append({name: v / total for name, v in w})
    return out


def bone_matrices(hf, values):
    """Each identity bone's skinning matrix for a set of values (world pose × inverse bind), in head_form's frame."""
    piv = rig_pivots(hf)
    import compose  # living/tools/characters: what the client computes from the values

    tr = compose.transforms(values, hf.H)
    world = {"J_Bip_C_Head": np.eye(4)}
    out = {"J_Bip_C_Head": np.eye(4)}

    def w(name):
        if name in world:
            return world[name]
        parent = RIG_PARENT.get(name) or {"J_Adj_L_FaceEye": "J_Id_Orbit_L", "J_Adj_R_FaceEye": "J_Id_Orbit_R"}[name]
        move, rot, scale = tr.get(name, ([0, 0, 0], None, [1, 1, 1]))
        # compose's file axes (X, Y up, Z back) into head_form's (x, y forward, z up).
        m = np.eye(4)
        r = np.eye(3)
        if rot is not None:
            x, y, z, ww = rot
            rf = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * ww), 2 * (x * z + y * ww)], [2 * (x * y + z * ww), 1 - 2 * (x * x + z * z), 2 * (y * z - x * ww)], [2 * (x * z - y * ww), 2 * (y * z + x * ww), 1 - 2 * (x * x + y * y)]])
            c = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)  # file -> form: (X, Y, Z) -> (X, -Z, Y)
            r = c @ rf @ c.T
        m[:3, :3] = r * np.array([scale[0], scale[2], scale[1]])[None, :]
        rest = piv[name] - (piv[parent] if parent in piv else np.zeros(3))
        m[:3, 3] = rest + np.array([move[0], -move[2], move[1]])
        world[name] = w(parent) @ m
        return world[name]

    # The eye bones ride the orbits and carry a value of their own (the eye's size).
    piv = dict(piv)
    for side, name in ((-1, "J_Adj_L_FaceEye"), (1, "J_Adj_R_FaceEye")):
        piv[name] = np.array(hf.eye_pivot(side), float)
    for name in piv:
        bind = np.eye(4)
        bind[:3, 3] = -piv[name]
        out[name] = w(name) @ bind
    return out



# ---------------------------------------------------------------------------------------------
# The face's mesh on the cage.


class CageFace(head_mesh.Face):
    """A head's skin from the cage, with the parts head_mesh.Face lays on a head (lash lines and
    lashes, brows, the mouth's inside, ears) and the eye the reference's way: the iris a flat
    disc 4 mm behind the lid, the white a bowl falling away 15 mm behind it, the lash line
    standing forward. Expressions are the same subdivision on a moved cage."""

    LASH_OUT = 0.0045

    def __init__(self, hf, look, keep=None):
        self.hf, self.look, self.keep = hf, look, keep
        self.t = hf.t
        self.base_pos, self.base_quads = hf.base_pos, hf.base_quads
        self._topology(None, keep)
        gaze = look.get("gaze", (0.0, 0.0))
        self.mesh = self.build(dict(look=gaze))
        v0 = np.array(self.mesh.v)
        self.morphs = {}
        for name, state in head_mesh.EXPRESSIONS.items():
            m = self.build(dict(state, look=gaze))
            assert len(m.v) == len(v0), name
            self.morphs[name] = np.array(m.v) - v0

    def _cage(self, state):
        hf = self.hf
        st = dict(state or {})
        lids = lambda side, s, upper: self._lid(side, np.array(s, float), st)[0 if upper else 1]
        return Cage(self.t, state=dict(mouth=st.get("mouth", 0.0), wide=st.get("wide", 0.0), smile=st.get("smile", 0.0) / hf.H, lids=lids))

    def _topology(self, front, keep):
        hf = self.hf
        cage = self._cage({})
        S, quads, what, parent = cage.subdivided()
        edge_row = {w[1]: i for i, w in enumerate(what) if w and w[0] == "e"}
        pos = S @ cage.v
        # The eyes' edges, in order round each opening, moved to the end so each is one run.
        loops = {}
        for side, loop in cage.eye.items():
            ring = []
            for a, b in zip(loop, loop[1:] + loop[:1]):
                ring += [a, edge_row[(min(a, b), max(a, b))]]
            loops[side] = ring
        ringed = [v for side in (-1, 1) for v in loops[side]]
        rest = [i for i in range(len(pos)) if i not in set(ringed)]
        order = rest + ringed
        new = {old: k for k, old in enumerate(order)}
        self._S = S[order]
        self.skin_pos = pos[order]
        self.rings = {}
        first = len(rest)
        for side in (-1, 1):
            k = len(loops[side])
            # Inner corner, the upper lid outward, outer corner, the lower lid back.
            self.rings[side] = dict(first=first, ring=[(0.0, i <= k // 2) for i in range(k)])
            first += k
        low = set(cage.mouth_lo)
        self.mouth_up = [new[i] for i in cage.mouth_up] + [new[edge_row[e]] for e in edge_row if e[0] in cage.mouth_up and e[1] in cage.mouth_up]
        self.mouth_lo = [new[i] for i in cage.mouth_lo] + [new[edge_row[e]] for e in edge_row if e[0] in low and e[1] in low]
        faces = [tuple(new[v] for v in q) for q in quads]
        self.skin_n = len(self.skin_pos)
        self.skin_normals = self._normals(self.skin_pos, faces)
        self.skin_pos = head_mesh.beard_offset(hf, self.look.get("beard"), self.skin_pos, self.skin_normals, clear=self.mouth_up + self.mouth_lo)
        self._beard = self.skin_pos - self._S @ cage.v
        # From the jaw line down the skin is the neck's (the plane under the jaw, the neck's ring): its
        # own faces, coloured and shaded as body skin, as the reference's face mask ends at the jaw.
        jaw_row = cage.R["jaw"]
        self.under_faces = [f for f, fi in zip(faces, parent) if cage.face_row[fi] >= jaw_row]
        self.neck_ring = {new[v] for v in cage.neck_ring} | {new[edge_row[e]] for e in edge_row if e[0] in set(cage.neck_ring) and e[1] in set(cage.neck_ring)}
        out = []
        for f, fi in zip(faces, parent):
            if cage.face_row[fi] >= jaw_row:
                continue
            c = self.skin_pos[list(f)].mean(axis=0)
            if keep is not None and not keep(c):
                continue
            out.append(f)
        # Faces across the atlas's seam at the back of the head get their own vertices (head_mesh.Face).
        uvs, extra = head_mesh.skin_uv(self.skin_pos), {}
        for n_, f in enumerate(out):
            u = uvs[list(f), 0]
            if u.max() - u.min() <= 0.5:
                continue
            out[n_] = tuple(extra.setdefault(v, self.skin_n + len(extra)) if uvs[v, 0] < 0.5 else v for v in f)
        self._extra = np.array(list(extra), int)
        if len(self._extra):
            uvs = np.concatenate([uvs, uvs[self._extra] + np.array([1.0, 0.0])])
            self.skin_normals = np.concatenate([self.skin_normals, self.skin_normals[self._extra]])
        self.skin_uvs = uvs
        self.skin_faces = out
        self.balls = {side: hf.eye_pivot(side) for side in (-1, 1)}

    @staticmethod
    def _normals(pos, faces):
        n = np.zeros_like(pos)
        for f in faces:
            q = pos[list(f)]
            fn = np.cross(q[1] - q[0], q[2] - q[0])
            for v in f:
                n[v] += fn
        return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)

    def _skin(self, state):
        pos = self._S @ self._cage(state).v + self._beard
        return np.concatenate([pos, pos[self._extra]]) if len(self._extra) else pos

    def build(self, state):
        m = super().build(state)
        # Under the jaw, with vertices of its own along the jaw line: a different skin meets there.
        skin = self._skin(state)
        used = sorted({v for f in self.under_faces for v in f})
        index = {v: i for i, v in enumerate(used)}
        look = self.look
        shade = tuple(a + (b - a) * 0.25 for a, b in zip(look["skin"], look["skin_shade"]))
        base = m.add(skin[used], shade, None, [tuple(index[v] for v in f) for f in self.under_faces], "under")
        self.under_neck = [base + index[v] for v in used if v in self.neck_ring]
        return m

    def _eye(self, m, skin, side, state):
        hf, look = self.hf, self.look
        white = (1.0, 1.0, 1.0)
        r = self.rings[side]
        first, k = r["first"], len(r["ring"])
        ring_pos = skin[first : first + k]
        scale = hf.H / 0.233  # the reference's depths were measured on a head of 23.3 cm
        d_iris, d_white, d_rim = 0.004 * scale, 0.015 * scale, RIM_FOLD * scale
        mid = ring_pos.mean(axis=0)
        # The opening's own plane (it leans back toward the outer corner, as the front plane does):
        # depths behind the lid are measured from it.
        A = np.stack([np.ones(k), ring_pos[:, 0], ring_pos[:, 2]], axis=1)
        coef = np.linalg.lstsq(A, ring_pos[:, 1], rcond=None)[0]
        lid_y = lambda x, z: coef[0] + coef[1] * x + coef[2] * z
        # The lids' rim: the edge again, turned in as far as the white's rim.
        rim = ring_pos.copy()
        rim[:, 1] = ring_pos[:, 1] - d_rim
        base = m.add(rim, look["skin_rim"], self.skin_uvs[first : first + k], [], "face")
        for i in range(k):
            q = (first + i, first + (i + 1) % k, base + (i + 1) % k, base + i)
            c = np.array([m.v[v] for v in q])
            if np.dot(np.cross(c[1] - c[0], c[2] - c[0]), mid - c.mean(axis=0)) < 0:
                q = tuple(reversed(q))
            m.f.append(q)
            m.fm.append("face")
        # The white: a bowl behind the opening, its rim just behind the lids and its middle
        # d_white further back, so it falls away behind the iris. It is cut to the opening (the
        # lids' own loop, a little wider so no gap shows where the lids' weights and the white's
        # differ) and not a rectangle: where the skin turns back, beside the nose and at the outer
        # corner, a rectangle's corners came through it.
        over = 0.0012 * scale
        out = ring_pos - mid
        out[:, 1] = 0.0
        out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)
        shrink = (0.78, 0.52, 0.26)
        bowl = [(p[0] + o[0] * over, p[1] - d_rim - 0.0006, p[2] + o[2] * over) for p, o in zip(ring_pos, out)]
        for sh in shrink:
            for p in ring_pos:
                x, z = lerp(mid[0], p[0], sh), lerp(mid[2], p[2], sh)
                bowl.append((x, lerp(lid_y(x, z), p[1], sh ** 4) - d_rim - 0.0006 - d_white * (1 - sh * sh), z))
        bowl.append((mid[0], lid_y(mid[0], mid[2]) - d_rim - 0.0006 - d_white, mid[2]))
        rows = len(shrink) + 1
        faces = [(j * k + i, j * k + (i + 1) % k, (j + 1) * k + (i + 1) % k, (j + 1) * k + i) for j in range(rows - 1) for i in range(k)]
        faces += [((rows - 1) * k + i, (rows - 1) * k + (i + 1) % k, rows * k) for i in range(k)]
        m.add(bowl, white, head_mesh.eye_uv(hf, side, [q[0] for q in bowl], [q[2] for q in bowl]), faces, "eye", facing=head_mesh.FORWARD)
        # The iris: a flat disc d_iris behind the lid, on the eye's bone.
        yaw, pitch = state.get("look", (0.0, 0.0))
        cx, cz = head_mesh.iris_centre(hf, side)
        rad = hf.iris_r
        seg = 24
        disc = [(0.0, 0.0)] + [(math.cos(2 * math.pi * i / seg) * rho, math.sin(2 * math.pi * i / seg) * rho) for rho in (0.55, 1.0) for i in range(seg)]
        iris_y = lambda x, z: lid_y(x, z) - d_iris
        ip = np.array([(cx + a * rad * head_mesh.IRIS_WIDE, iris_y(cx + a * rad * head_mesh.IRIS_WIDE, cz + b * rad), cz + b * rad) for a, b in disc])
        half = head_mesh.IRIS_PX * head_mesh.IRIS_FILL
        uv = [((head_mesh.IRIS_COL0 + head_mesh.IRIS_PX / 2 + a * half * head_mesh.IRIS_WIDE) / head_mesh.ATLAS, 1 - (head_mesh.IRIS_PX / 2 - b * half) / head_mesh.ATLAS) for a, b in disc]
        faces = [(0, 1 + i, 1 + (i + 1) % seg) for i in range(seg)] + [(1 + i, 1 + seg + i, 1 + seg + (i + 1) % seg, 1 + (i + 1) % seg) for i in range(seg)]
        ball = self.balls[side]
        m.add(head_mesh.turn(ip, ball, yaw, pitch), white, uv, faces, "iris", facing=head_mesh.FORWARD, eye=(side, 1.0))
        hs = look.get("light_side", 1.0)
        for hx, hz_, hrx, hrz in ((0.36 * hs, 0.36, 0.25, 0.20), (-0.34 * hs, -0.46, 0.105, 0.09)):
            n_ = 12
            ring_ = [(cx + hx * rad, cz + hz_ * rad)] + [(cx + (hx + hrx * math.cos(2 * math.pi * i / n_)) * rad, cz + (hz_ + hrz * math.sin(2 * math.pi * i / n_)) * rad) for i in range(n_)]
            gp = np.array([(x, iris_y(x, z) + 0.0006, z) for x, z in ring_])
            m.add(head_mesh.turn(gp, ball, 0.5 * yaw, 0.5 * pitch), (1.0, 1.0, 0.985), None, [(0, 1 + i, 1 + (i + 1) % n_) for i in range(n_)], "glint", facing=head_mesh.FORWARD, eye=(side, 0.5))
