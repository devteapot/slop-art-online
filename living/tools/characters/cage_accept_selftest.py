#!/usr/bin/env python3
"""Known-answer test for cage_accept.py's measuring path (docs/char-port-2/PLAN.md §7: a measuring tool passes a
known-answer test before its numbers are used): a synthetic head of known widths goes through cage_accept's own GLB
writer (`write_skin_glb`), the reference tool (`reference/measure.py`) and `face_types.measure_one`, and must come
back with the widths, the eye's height and the eyes' spacing it was built with.

**The head** (the cage's frame: x across, y forward, z up; H = 0.24 m, the chin at z = 0):
- level rings of one polygon shape, 0.01 H apart, closed top and bottom;
- each station of `face_types.Z` up to 0.76 H holds one cross-section from 0.02 H under it to 0.02 H over it, so the
  reference tool's cut there is exact. The section's half: the front's midline at depth 0, a flat front to `f`, then
  a vertex at (m, 0.14 H back) and one at (a, 0.29 H back), then the side and the back. So every point within
  0.15 H of the bridge has |x| <= m, and within 0.30 H, <= a: **w15 = 2m/H, w30 = 2a/H**, with no vertex near a
  threshold (the tool takes the cut's points, not interpolated ones, so a threshold between two vertices would
  read the nearer one);
- **two eye holes** (two by two quads each side, x 0.025-0.042 m, between the rings at 0.47 and 0.49 H): the eye's
  centre 0.48 H, the eyes 0.067 m apart (0.278 H);
- **a nose:** the front's midline vertex on the ring at 0.36 H, 0.015 m forward.

Each width must come back to 0.001 H, the eye's height and spacing to 0.002 H.

**The taper's allowance** (`check_type`: a tapered type is held to its record times the taper it took, at most
the cage's declared factor), on adult-f-b built with the port's `jaw` (S1's taper, S7's rise):
- **as built:** within 0.03 H of its tapered record;
- **a narrowing beyond the taper** (the cage's lower face, below 0.15 H, made 12% narrower only when the taper is
  on, so the second, untapered build does not show it): it must fail, though the width it took is all "taper";
- **a narrowing in both builds** (the same, taper or not: a plain defect): it must fail.

Exit status 1 on any failure.
    python3 living/tools/characters/cage_accept_selftest.py
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "blender"))
import cage_accept  # noqa: E402
import face_types  # noqa: E402

H = 0.24
DEFAULT = (0.050, 0.060, 0.070)  # (f, m, a) in m between stations
# The stations' (f, m, a), m: a lower face narrowing to the chin, widest at the cheeks.
KNOWN = {0.04: (0.010, 0.018, 0.030), 0.12: (0.022, 0.034, 0.048), 0.20: (0.030, 0.046, 0.060), 0.28: (0.036, 0.054, 0.068),
         0.40: (0.044, 0.062, 0.074), 0.52: (0.050, 0.066, 0.078), 0.64: (0.048, 0.064, 0.077), 0.76: (0.040, 0.056, 0.070)}
EYE_RINGS, NOSE_RING = (0.47, 0.49), 0.36


def half(f, m, a):
    """The section's right half, front midline to back midline: (x, depth forward) in m; front at 0."""
    front = [(f * k / 6, 0.0) for k in range(7)]
    return front + [(m, -0.14 * H), (a, -0.29 * H), (a, -0.60 * H), (0.6 * a, -0.85 * H), (0.0, -0.95 * H)]


def ring_shape(z):
    for s, fma in KNOWN.items():
        if abs(z - s) <= 0.02 + 1e-9:
            return fma
    return DEFAULT


def head():
    zs = [round(k * 0.01, 2) for k in range(0, 101)]
    n_half = len(half(*DEFAULT))
    V, F = [], []
    for zf in zs:
        h = half(*ring_shape(zf))
        ring = h + [(-x, d) for x, d in reversed(h[1:-1])]  # right half, then the left back to the front
        for x, d in ring:
            V.append([x, d, zf * H])
    n = 2 * n_half - 2
    V = np.array(V, float)
    k_nose = zs.index(NOSE_RING)
    V[k_nose * n, 1] += 0.015
    for r in range(len(zs) - 1):
        for i in range(n):
            j = (i + 1) % n
            if (r, i) in eye_quads:
                continue
            F.append((r * n + i, r * n + j, (r + 1) * n + j, (r + 1) * n + i))
    # caps
    for r, flip in ((0, True), (len(zs) - 1, False)):
        c = len(V)
        V = np.vstack([V, [[0.0, -0.45 * H, zs[r] * H]]])
        for i in range(n):
            a_, b_ = r * n + i, r * n + (i + 1) % n
            F.append((a_, c, b_) if flip else (a_, b_, c))
    return V, F


# The eye holes: on the rings at 0.47-0.49 H the front is the eye band's (DEFAULT f = 0.050 there: front vertices at
# x = 0, 0.0083, 0.0167, 0.025, 0.0333, 0.0417, 0.05). Two quads each side between x 0.025 and 0.0417 (indices 3-5
# on the right; mirrored on the left), between the rings at 0.47 and 0.48, and 0.48 and 0.49 H.
def eye_quad_set(n, k0):
    q = set()
    for r in (k0, k0 + 1):
        for i in (3, 4):
            q.add((r, i))
            q.add((r, n - i - 1))
    return q


def taper_cases():
    """The taper's allowance end to end, on a real type: (label, got, want, tol) rows."""
    import cage_head

    os.environ["SLOP_PORT"] = "jaw"
    t = face_types.load()["types"]["adult-f-b"]
    out = []
    fit = cage_head.Cage.fit

    def narrowed(only_tapered):
        def f(self, rounds=5):
            if not only_tapered or self.t["jaw"].get("chin_taper"):
                low = self.v[:, 2] < 0.15
                self.v[low, 0] *= 0.88
            return fit(self, rounds)
        return f

    with tempfile.TemporaryDirectory() as ref:
        os.makedirs(os.path.join(ref, "npz"))
        for label, patch, want in (("adult-f-b as built: within its tapered record", None, True),
                                   ("a narrowing beyond the taper (only with it on) fails", narrowed(True), False),
                                   ("a narrowing in both builds fails", narrowed(False), False)):
            if patch:
                cage_head.Cage.fit = patch
            try:
                ok, row = cage_accept.check_type(t, ref)
            finally:
                cage_head.Cage.fit = fit
            out.append((f"{label} (worst {row['worst_width']:.3f} H of the tapered record, {row['worst_from_record']:.3f} H of the record)", ok, want, 0))
    return out


def main():
    global eye_quads
    zs = [round(k * 0.01, 2) for k in range(0, 101)]
    n = 2 * len(half(*DEFAULT)) - 2
    eye_quads = eye_quad_set(n, zs.index(EYE_RINGS[0]))
    V, F = head()
    f_eye = DEFAULT[0]
    ex0, ex1 = 3 * f_eye / 6, 5 * f_eye / 6
    want_apart = (ex0 + ex1) / H
    want_eye = 0.48
    with tempfile.TemporaryDirectory() as ref:
        os.makedirs(os.path.join(ref, "npz"))
        glb = os.path.join(ref, "npz", "synthetic.glb")
        cage_accept.write_skin_glb(glb, V, F)
        out = os.path.join("npz", "synthetic_m.json")
        subprocess.run([sys.executable, "-I", os.path.join(HERE, "reference", "measure.py"), glb, out, str(1.535 + H)], cwd=ref, check=True, capture_output=True)
        m = face_types.measure_one(os.path.join(ref, out))
    checks = []
    for i, z in enumerate(face_types.Z):
        if z not in KNOWN:
            continue
        f, mm, a = KNOWN[z]
        checks += [(f"w15 at {z:.2f} H", m["w15"][i], round(2 * mm / H, 3), 0.001), (f"w30 at {z:.2f} H", m["w30"][i], round(2 * a / H, 3), 0.001)]
    checks += [("eye centre (H)", m["eye_z"], want_eye, 0.002), ("eyes apart (H)", m["eye_apart"], round(want_apart, 3), 0.002)]
    checks += taper_cases()
    bad = 0
    for label, got, want, tol in checks:
        ok = got == want if isinstance(want, bool) else (got is not None and abs(got - want) <= tol + 1e-9)
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {got} (known {want})")
    print("cage_accept_selftest:", "PASS" if not bad else f"{bad} FAILED")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
