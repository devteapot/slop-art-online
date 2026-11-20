"""Ink carriers for a hand-made face (docs/HANDMADE_INK.md, "Carriers").

A carrier is a ribbon of quads that lies 0.1-0.5 mm in front of the surface it draws on. Each
ribbon is laid out as a regular grid around a spine, lifted onto the face, mapped by its own
3D lengths, and bound to the triangles it rides, so every morph target carries it. Plain numpy:
the journal block hands it Blender's mesh arrays and writes the result back.

Generalises to any head: the spine and widths come from drawing measurements in eye or face
units; everything below is geometry.
"""
import numpy as np


# ---------------------------------------------------------------------------------------------
# Polylines

def cumlen(P):
    P = np.asarray(P, float)
    return np.concatenate([[0.], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])


def at_length(P, s):
    """Points at arc lengths s along polyline P (clamped linear extrapolation at the ends)."""
    P = np.asarray(P, float)
    L = cumlen(P)
    s = np.atleast_1d(np.asarray(s, float))
    i = np.clip(np.searchsorted(L, s, side='right') - 1, 0, len(P) - 2)
    t = (s - L[i]) / np.maximum(L[i + 1] - L[i], 1e-12)
    return P[i] + t[:, None] * (P[i + 1] - P[i])


def catmull(P, n=8):
    """A smooth curve through the points of P (uniform Catmull-Rom, n samples a segment)."""
    P = np.asarray(P, float)
    Q = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    for k in range(1, len(Q) - 2):
        p0, p1, p2, p3 = Q[k - 1:k + 3]
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-1])
    return np.array(out)


def left_normal(P):
    """Unit normals of a 2D polyline, its tangent turned +90 degrees."""
    P = np.asarray(P, float)
    T = np.gradient(P, axis=0)
    T /= np.linalg.norm(T, axis=1)[:, None]
    return np.stack([-T[:, 1], T[:, 0]], 1)


def project_2d(P, Q):
    """Arc length along polyline P and signed left offset of each 2D point in Q."""
    P = np.asarray(P, float)
    Q = np.atleast_2d(np.asarray(Q, float))
    L = cumlen(P)
    A, B = P[:-1], P[1:]
    d = B - A
    ll = np.maximum((d * d).sum(1), 1e-18)
    t = np.clip((((Q[:, None, :] - A[None]) * d[None]).sum(-1)) / ll[None], 0, 1)
    X = A[None] + t[..., None] * d[None]
    dist = np.linalg.norm(Q[:, None, :] - X, axis=-1)
    i = dist.argmin(1)
    r = np.arange(len(Q))
    s = L[i] + t[r, i] * np.sqrt(ll[i])
    dd = d[i] / np.sqrt(ll[i])[:, None]
    rel = Q - X[r, i]
    off = dd[:, 0] * rel[:, 1] - dd[:, 1] * rel[:, 0]
    return s, off


# ---------------------------------------------------------------------------------------------
# Triangles

def raycast(O, D, A, B, C, eps=1e-14, cull=False):
    """Nearest positive hit of each ray with triangles (A, B, C); t is inf on a miss. With
    `cull`, only triangles facing the ray (wound counter-clockwise towards it) are hit."""
    O = np.atleast_2d(O)
    D = np.broadcast_to(np.asarray(D, float), O.shape)
    e1, e2 = B - A, C - A
    out_t = np.full(len(O), np.inf)
    out_i = np.full(len(O), -1)
    out_b = np.zeros((len(O), 3))
    for s in range(0, len(O), 128):
        o, d = O[s:s + 128, None, :], D[s:s + 128, None, :]
        p = np.cross(d, e2[None])
        det = (e1[None] * p).sum(-1)
        ok = det > eps if cull else np.abs(det) > eps
        inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
        tv = o - A[None]
        u = (tv * p).sum(-1) * inv
        q = np.cross(tv, e1[None])
        v = (d * q).sum(-1) * inv
        t = (e2[None] * q).sum(-1) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)
        t = np.where(hit, t, np.inf)
        i = t.argmin(1)
        r = np.arange(len(i))
        out_t[s:s + 128] = t[r, i]
        out_i[s:s + 128] = np.where(np.isfinite(t[r, i]), i, -1)
        out_b[s:s + 128] = np.stack([1 - u[r, i] - v[r, i], u[r, i], v[r, i]], 1)
    return out_t, out_i, out_b


def closest(P, A, B, C):
    """Closest point on any of the triangles: index, barycentric weights and the point."""
    P = np.atleast_2d(P)
    n = len(P)
    bi, bb, bp = np.zeros(n, int), np.zeros((n, 3)), np.zeros((n, 3))
    ab, ac = B - A, C - A
    for s in range(0, n, 64):
        p = P[s:s + 64, None, :]
        ap, bp_, cp = p - A, p - B, p - C
        d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
        d3, d4 = (ab * bp_).sum(-1), (ac * bp_).sum(-1)
        d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
        va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
        den = va + vb + vc
        den = np.where(np.abs(den) < 1e-30, 1e-30, den)
        v, w = vb / den, vc / den
        u = 1 - v - w

        def put(mask, uu, vv, ww):
            nonlocal u, v, w
            u, v, w = np.where(mask, uu, u), np.where(mask, vv, v), np.where(mask, ww, w)

        z = np.zeros_like(u)
        q1 = (d4 - d3) + (d5 - d6)
        t = np.clip((d4 - d3) / np.where(q1 == 0, 1, q1), 0, 1)
        put((va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0), z, 1 - t, t)
        t = np.clip(d2 / np.where(d2 - d6 == 0, 1, d2 - d6), 0, 1)
        put((vb <= 0) & (d2 >= 0) & (d6 <= 0), 1 - t, z, t)
        t = np.clip(d1 / np.where(d1 - d3 == 0, 1, d1 - d3), 0, 1)
        put((vc <= 0) & (d1 >= 0) & (d3 <= 0), 1 - t, t, z)
        put((d6 >= 0) & (d5 <= d6), z, z, z + 1)
        put((d3 >= 0) & (d4 <= d3), z, z + 1, z)
        put((d1 <= 0) & (d2 <= 0), z + 1, z, z)
        q = u[..., None] * A[None] + v[..., None] * B[None] + w[..., None] * C[None]
        dd = ((q - p) ** 2).sum(-1)
        i = dd.argmin(1)
        r = np.arange(len(i))
        bi[s:s + 64], bp[s:s + 64] = i, q[r, i]
        bb[s:s + 64] = np.stack([u[r, i], v[r, i], w[r, i]], 1)
    return bi, bb, bp


class Surface:
    """Triangles of one mesh (indices into its vertex array) with smooth vertex normals."""

    def __init__(self, V, T, VN):
        self.V, self.T, self.VN = np.asarray(V, float), np.asarray(T, int), np.asarray(VN, float)

    def abc(self, V=None):
        V = self.V if V is None else V
        return V[self.T[:, 0]], V[self.T[:, 1]], V[self.T[:, 2]]

    def normal(self, tri, bary):
        n = (self.VN[self.T[tri]] * bary[..., None]).sum(-2)
        return n / np.linalg.norm(n, axis=-1)[..., None]

    def nearest(self, P):
        tri, bary, q = closest(P, *self.abc())
        return tri, bary, q, self.normal(tri, bary)


def frames(V, T):
    """Orthonormal frames (t1, t2, n) of triangles T in positions V: (K, 3, 3)."""
    A, B, C = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    e1 = B - A
    n = np.cross(e1, C - A)
    n /= np.linalg.norm(n, axis=1)[:, None]
    t1 = e1 / np.linalg.norm(e1, axis=1)[:, None]
    return np.stack([t1, np.cross(n, t1), n], 1)


class Binding:
    """Each point held on its nearest rest triangle: barycentric anchor plus a local offset."""

    def __init__(self, P, surface):
        self.surface = surface
        self.tri, self.bary, q = closest(P, *surface.abc())
        F = frames(surface.V, surface.T[self.tri])
        self.off = np.einsum('kij,kj->ki', F, np.asarray(P) - q)

    def at(self, V):
        T = self.surface.T[self.tri]
        q = (V[T] * self.bary[..., None]).sum(1)
        F = frames(V, T)
        return q + np.einsum('kij,ki->kj', F, self.off)

    def weights(self, W):
        """Per-vertex rows of W (vertex x group), blended by the anchors."""
        return (W[self.surface.T[self.tri]] * self.bary[..., None]).sum(1)


# ---------------------------------------------------------------------------------------------
# Ribbons

class Ribbon:
    """A regular grid of quads around a 2D design spine: columns along it every `ds`, rows
    across it from `o0` to `o1` every `do` (all in design metres)."""

    def __init__(self, name, spine, o0, o1, ds, do):
        spine = np.asarray(spine, float)
        L = cumlen(spine)[-1]
        nc = max(2, int(np.ceil(L / ds)) + 1)
        nr = max(2, int(np.ceil((o1 - o0) / do)) + 1)
        self.name, self.spine = name, spine
        self.s = np.linspace(0, L, nc)
        self.o = np.linspace(o0, o1, nr)
        C = at_length(spine, self.s)
        dense = at_length(spine, np.linspace(0, L, 4 * nc))
        N = left_normal(dense)[np.linspace(0, 4 * nc - 1, nc).round().astype(int)]
        self.design = C[:, None, :] + self.o[None, :, None] * N[:, None, :]
        self.strokes = []

    @property
    def shape(self):
        return self.design.shape[:2]

    def grid_of(self, Q):
        """Fractional (column, row) of 2D design points."""
        s, off = project_2d(self.spine, Q)
        return s / (self.s[1] - self.s[0]), (off - self.o[0]) / (self.o[1] - self.o[0])

    def bilinear(self, G, fc, fr):
        nc, nr = self.shape
        c = np.clip(np.floor(fc).astype(int), 0, nc - 2)
        r = np.clip(np.floor(fr).astype(int), 0, nr - 2)
        a, b = (fc - c)[:, None], (fr - r)[:, None]
        return ((1 - a) * (1 - b) * G[c, r] + a * (1 - b) * G[c + 1, r]
                + (1 - a) * b * G[c, r + 1] + a * b * G[c + 1, r + 1])


def lift_front(ribbon, surface, offset, view=np.array([0., 1., 0.]), min_facing=.35):
    """Lift the design grid (x, z) onto the surface along the view direction, `offset` metres
    out along the surface normal. Where the ray misses or meets the surface steeper than
    `min_facing` (an eye opening's rolled rim, the face's outline), the ribbon continues flat
    across the view from its nearest good point, so it stays isometric to its design."""
    X = ribbon.design
    nc, nr = X.shape[:2]
    O = np.stack([X[..., 0], np.full(X.shape[:2], -1.), X[..., 1]], -1).reshape(-1, 3)
    t, tri, bary = raycast(O, view, *surface.abc(), cull=True)
    hit = np.isfinite(t)
    P = O + np.where(hit, t, 0)[:, None] * view
    N = np.zeros_like(P)
    N[hit] = surface.normal(tri[hit], bary[hit])
    N[hit] *= np.where((N[hit] @ view) > 0, -1., 1.)[:, None]
    hit &= np.abs(N @ view) >= min_facing
    P[hit] += offset * N[hit]
    P, N, hit = P.reshape(nc, nr, 3), N.reshape(nc, nr, 3), hit.reshape(nc, nr)
    # Keep each column continuous: walking out from its middle row, a hit whose depth jumps by
    # more than 3 row steps (another surface behind or beyond an outline) ends that side.
    step = abs(ribbon.o[1] - ribbon.o[0])
    mid = int(np.argmin(np.abs(ribbon.o)))
    for c in range(nc):
        for rows in (range(mid + 1, nr), range(mid - 1, -1, -1)):
            last, gone = (P[c, mid, 1] if hit[c, mid] else None), False
            for r in rows:
                if gone or not hit[c, r]:
                    hit[c, r] = hit[c, r] and not gone
                    continue
                if last is not None and abs(P[c, r, 1] - last) > 3 * step:
                    hit[c, r] = False
                    gone = True
                    continue
                last = P[c, r, 1]
    assert hit.any(), ribbon.name
    # Fill the rest smoothly: depth and normals by harmonic interpolation over the grid from the
    # good points, x and z from the design, so the filled part neither folds nor steps.
    Y = np.where(hit, P[..., 1], P[..., 1][hit].mean())
    M = np.where(hit[..., None], N, N[hit].mean(0))
    for _ in range(800):
        Yp = np.pad(Y, 1, mode='edge')
        Mp = np.pad(M, ((1, 1), (1, 1), (0, 0)), mode='edge')
        Yn = (Yp[:-2, 1:-1] + Yp[2:, 1:-1] + Yp[1:-1, :-2] + Yp[1:-1, 2:]) / 4
        Mn = (Mp[:-2, 1:-1] + Mp[2:, 1:-1] + Mp[1:-1, :-2] + Mp[1:-1, 2:]) / 4
        Y = np.where(hit, Y, Yn)
        M = np.where(hit[..., None], M, Mn)
    miss = ~hit
    P[miss] = np.stack([X[..., 0], Y, X[..., 1]], -1)[miss]
    N[miss] = M[miss] / np.linalg.norm(M[miss], axis=-1)[:, None]
    ribbon.P, ribbon.N, ribbon.hit = P, N, hit
    return P


def lift_surface(ribbon, spine3d, surface, offset, step=.0005):
    """Lay the grid on the surface by marching each column's rows along it from a 3D spine
    (for strokes that wrap round the face, such as the jaw)."""
    nc, nr = ribbon.shape
    S = at_length(spine3d, ribbon.s * cumlen(spine3d)[-1] / ribbon.s[-1])
    T = np.gradient(S, axis=0)
    T /= np.linalg.norm(T, axis=1)[:, None]
    P = np.zeros((nc, nr, 3))
    N = np.zeros((nc, nr, 3))
    for c in range(nc):
        _, _, q, n = surface.nearest(S[c:c + 1])
        for sign in (1, -1):
            p, nn, o = q[0], n[0], 0.
            targets = [r for r in range(nr) if np.sign(ribbon.o[r]) == sign or (sign == 1 and ribbon.o[r] == 0)]
            for r in sorted(targets, key=lambda r: abs(ribbon.o[r])):
                while o + 1e-12 < abs(ribbon.o[r]):
                    h = min(step, abs(ribbon.o[r]) - o)
                    a = np.cross(nn, T[c])
                    a /= np.linalg.norm(a)
                    _, _, qq, n2 = surface.nearest((p + sign * h * a)[None])
                    p, nn, o = qq[0], n2[0], o + h
                P[c, r], N[c, r] = p, nn
    ribbon.P, ribbon.N, ribbon.hit = P + offset * N, N, np.ones((nc, nr), bool)
    return ribbon.P


def flatten(P, init, iters=600):
    """UVs in metres matching the grid's own 3D lengths (springs on rows, columns and both
    diagonals, relaxed from `init`)."""
    nc, nr = P.shape[:2]
    idx = np.arange(nc * nr).reshape(nc, nr)
    E = np.vstack([np.stack([idx[:-1, :].ravel(), idx[1:, :].ravel()], 1),
                   np.stack([idx[:, :-1].ravel(), idx[:, 1:].ravel()], 1),
                   np.stack([idx[:-1, :-1].ravel(), idx[1:, 1:].ravel()], 1),
                   np.stack([idx[1:, :-1].ravel(), idx[:-1, 1:].ravel()], 1)])
    X = P.reshape(-1, 3)
    L = np.linalg.norm(X[E[:, 1]] - X[E[:, 0]], axis=1)
    U = np.asarray(init, float).reshape(-1, 2).copy()
    cnt = np.bincount(E.ravel(), minlength=len(U))[:, None]
    for _ in range(iters):
        d = U[E[:, 1]] - U[E[:, 0]]
        ln = np.maximum(np.linalg.norm(d, axis=1), 1e-12)
        corr = ((ln - L) / ln)[:, None] * d * .5
        acc = np.zeros_like(U)
        np.add.at(acc, E[:, 0], corr)
        np.add.at(acc, E[:, 1], -corr)
        U += .9 * acc / cnt
    return U.reshape(nc, nr, 2)


def isometry(P, U):
    """Per-triangle metres per UV unit (sqrt of area ratio), for the audit's density check."""
    nc, nr = P.shape[:2]
    out = []
    for c in range(nc - 1):
        for r in range(nr - 1):
            for tri in (((c, r), (c + 1, r), (c + 1, r + 1)), ((c, r), (c + 1, r + 1), (c, r + 1))):
                a, b, cc = (P[i] for i in tri)
                ua, ub, uc = (U[i] for i in tri)
                A3 = np.linalg.norm(np.cross(b - a, cc - a)) / 2
                A2 = abs((ub - ua)[0] * (uc - ua)[1] - (ub - ua)[1] * (uc - ua)[0]) / 2
                out.append(np.sqrt(A3 / max(A2, 1e-20)))
    return np.array(out)


def pack(ribbons, side, gap):
    """Place every ribbon's metre UVs (turned to lie along x) on shelves in a square map `side`
    metres wide, `gap` metres apart; sets ribbon.uv in 0..1 (glTF orientation, top-left)."""
    boxes = []
    for rb in ribbons:
        U = rb.uv_m.reshape(-1, 2)
        U = U - U.mean(0)
        w, v = np.linalg.eigh(np.cov(U.T))
        R = v[:, ::-1]
        if np.linalg.det(R) < 0:
            R[:, 1] *= -1
        U = U @ R
        U -= U.min(0)
        boxes.append(U)
    order = sorted(range(len(ribbons)), key=lambda i: -boxes[i][:, 1].max())
    x = y = shelf = gap
    for i in order:
        U = boxes[i]
        w, h = U.max(0)
        if x + w + gap > side:
            x, y, shelf = gap, shelf, shelf
        place = U + [x, y]
        shelf = max(shelf, y + h + gap)
        x += w + gap
        assert shelf <= side, ('map too small', side)
        ribbons[i].uv = (place / side).reshape(ribbons[i].uv_m.shape)
    return shelf / side


def smooth_field(D, passes=2):
    """Box-smooth a displacement field over the grid (edge-clamped)."""
    for _ in range(passes):
        P = np.pad(D, ((1, 1), (1, 1), (0, 0)), mode='edge')
        D = sum(P[1 + i:P.shape[0] - 1 + i, 1 + j:P.shape[1] - 1 + j] for i in (-1, 0, 1) for j in (-1, 0, 1)) / 9
    return D


def stroke_uv(ribbon, pts, hw, range_m, max_stretch=np.inf):
    """Map design-plane stroke points with design half-widths to [u, v, f] for ink_field.py.
    The half-width is turned into surface metres by the grid's local stretch across the
    stroke (capped at `max_stretch`), then into f = half-width / range."""
    pts = np.asarray(pts, float)
    fc, fr = ribbon.grid_of(pts)
    uv = ribbon.bilinear(ribbon.uv, fc, fr)
    # Surface metres per design metre across the stroke: the grid's local Jacobian
    # (UV over design, through the grid indices) applied to the stroke's own normal.
    nc, nr = ribbon.shape
    def d(G, axis):
        D = np.diff(G, axis=axis)
        return np.concatenate([D, D[-1:] if axis == 0 else D[:, -1:]], axis)
    A = np.stack([ribbon.bilinear(d(ribbon.design, 0), fc, fr), ribbon.bilinear(d(ribbon.design, 1), fc, fr)], -1)
    B = np.stack([ribbon.bilinear(d(ribbon.uv_m, 0), fc, fr), ribbon.bilinear(d(ribbon.uv_m, 1), fc, fr)], -1)
    J = B @ np.linalg.inv(A)
    nrm = left_normal(pts) if len(pts) > 1 else np.array([[0., 1.]])
    stretch = np.linalg.norm(np.einsum('kij,kj->ki', J, nrm), axis=1)
    stretch = np.minimum(stretch, max_stretch)
    f = np.asarray(hw) * stretch / range_m
    return [[float(a), float(b), float(c)] for (a, b), c in zip(uv, f)], stretch


def clearance(P, N, surface, V, clear, iters=4, reach=.003, sub=4):
    """Push a ribbon's vertices out along N until every point of its quads (sampled `sub` x
    `sub`) lies at least `clear` metres in front of the surface (triangles at positions V).
    Coarse carriers then never dip into a curved surface between their vertices. Points with
    no surface within `reach` (floating over an opening) are not constrained."""
    P = P.copy()
    nc, nr = P.shape[:2]
    lo, hi = P.reshape(-1, 3).min(0) - .006, P.reshape(-1, 3).max(0) + .006
    T = surface.T[np.all((V[surface.T] >= lo) & (V[surface.T] <= hi), axis=(1, 2))]
    if not len(T):
        return P
    near = Surface(V, T, surface.VN)
    t = (np.arange(sub) + .5) / sub
    a, b = np.meshgrid(t, t, indexing='ij')
    a, b = a.ravel(), b.ravel()
    w = np.stack([(1 - a) * (1 - b), a * (1 - b), (1 - a) * b, a * b], 1)
    for _ in range(iters):
        C4 = np.stack([P[:-1, :-1], P[1:, :-1], P[:-1, 1:], P[1:, 1:]], 2)      # (nc-1, nr-1, 4, 3)
        S = np.einsum('sk,crkd->crsd', w, C4).reshape(-1, 3)
        tri, bary, q, n = near.nearest(S)
        dist = np.linalg.norm(S - q, axis=1)
        s = ((S - q) * n).sum(1)
        deficit = np.where(dist < reach, np.maximum(0, clear - s), 0).reshape(nc - 1, nr - 1, -1)
        if deficit.max() < 1e-6:
            break
        # Each corner takes the largest deficit of the samples it weighs most in.
        need = np.zeros((nc, nr))
        for k, (dc, dr) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
            dk = (deficit * (w[:, k] >= .25 * w.max())[None, None]).max(-1)
            need[dc:nc - 1 + dc, dr:nr - 1 + dr] = np.maximum(need[dc:nc - 1 + dc, dr:nr - 1 + dr], dk)
        P += (need * 1.1)[..., None] * N
    return P
