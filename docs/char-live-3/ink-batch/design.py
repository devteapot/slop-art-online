"""Register the drawing's measured strokes onto Cora's face and lay out their carriers.

The drawing is a target, never a texture: only its traced centrelines and widths
(eye-frame/drawing-strokes.json) are read, converted to eye or face units through landmark
similarities, and rebuilt on the 3D face:

- the upper lid follows the skin's own eye-opening edge, its lower ink edge 0.25 mm inside the
  opening, with the drawn width profile; the wing, the two lash flicks and the outer lower lid
  keep their drawn shape relative to the canthi;
- the brows keep their drawn shape relative to the eye;
- the nostrils come from the face similarity through the pupils;
- the jaw line follows the face's own contour (where the surface turns `jaw_facing` from the
  front view) between the drawn end heights, with the drawn width profile.

Plain numpy; `build(...)` is called from the journal block with Blender's arrays.
"""
import numpy as np
from carriers import (Ribbon, Surface, at_length, catmull, clearance, cumlen, left_normal,
                      lift_front, project_2d, raycast)

PARAMS = dict(
    # Shared carrier geometry.
    carrier_offset_m=.0003,       # carrier in front of the surface it draws on, at its vertices
    skin_offset_m=.0003,
    core_offset_m=.00015,         # opaque core under the lid ink, between both
    carrier_clear_m=.00035,       # and everywhere across its quads, in every morph (clearance)
    core_clear_m=.00015,
    core_inset=.35,               # core half-width = hw - max(core_inset*hw, core_margin_m)
    core_margin_m=.0006,
    lid_overlap_m=.0005,          # ink edge reaches this far into the opening
    eyes_range_m=.0055,           # eyes map: lid, lashes, lower lid, brows
    skin_range_m=.0035,           # skin map: jaw and nose
    eyes_side_m=.26,              # map side in metres (one texel density per material)
    skin_side_m=.21,
    margin_m=.0018,               # carrier reach beyond range (a pixel at the closest view and the chords)
    # Jaw contour: surface turned this far from the front view (cos of the angle).
    outline_smooth=12,            # smoothing passes over the face outline (1 mm spacing)
    jaw_inset_m=.0003,            # jaw stroke's outer edge inside the face outline
    jaw_end_drop_m=.008,          # the jaw ends this far below the drawn ends (behind the hair)
    jaw_min_facing=.55,           # the jaw carrier floats flat where the face turns steeper
    max_stretch=2.5,              # cap on surface/projected width where the face turns away
    # Width gains from the first measured portraits (widths.py): drawn widths x gain.
    brow_gain=1.,
    nostril_gain=.8,
    lower_gain=1.3,
)


def similarity(src_a, src_b, dst_a, dst_b):
    """2D similarity mapping drawing pixels (y down) onto design metres (x, z up)."""
    za, zb = complex(src_a[0], -src_a[1]), complex(src_b[0], -src_b[1])
    wa, wb = complex(*dst_a), complex(*dst_b)
    a = (wb - wa) / (zb - za)
    b = wa - a * za

    def f(p):
        p = np.atleast_2d(np.asarray(p, float))
        w = a * (p[:, 0] - 1j * p[:, 1]) + b
        return np.stack([w.real, w.imag], 1)
    f.scale = abs(a)
    f.rotate = lambda v: np.stack([(a / abs(a) * (np.asarray(v)[:, 0] - 1j * np.asarray(v)[:, 1])).real,
                                   (a / abs(a) * (np.asarray(v)[:, 0] - 1j * np.asarray(v)[:, 1])).imag], 1)
    return f


def hole_chains(V, loop):
    """Upper and lower chains of an eye opening's boundary loop, each inner to outer canthus."""
    loop = list(loop)
    x = V[loop, 0]
    side = np.sign(x.mean())
    i_in, i_out = int(np.argmin(np.abs(x))), int(np.argmax(np.abs(x)))
    n = len(loop)
    a = [loop[(i_in + k) % n] for k in range(((i_out - i_in) % n) + 1)]
    b = [loop[(i_in - k) % n] for k in range(((i_in - i_out) % n) + 1)]
    up, low = (a, b) if V[a, 2].mean() > V[b, 2].mean() else (b, a)
    return up, low


def smooth_curve(P2, hw, n=6):
    """Smooth a 2D centreline with its half-widths (Catmull-Rom on x, z, hw)."""
    Q = catmull(np.column_stack([P2, hw]), n)
    return Q[:, :2], np.maximum(Q[:, 2], 0)


def extend(P, by):
    """Extend a polyline straight past both ends by `by` metres."""
    t0 = P[0] - P[1]
    t1 = P[-1] - P[-2]
    return np.vstack([P[0] + by * t0 / np.linalg.norm(t0), P, P[-1] + by * t1 / np.linalg.norm(t1)])


class Stroke:
    def __init__(self, name, pts, hw):
        self.name, self.pts, self.hw = name, np.asarray(pts, float), np.asarray(hw, float)


def lid_strokes(V, up, low, drawing, p):
    """Upper lid with wing, two lash flicks and the outer lower lid for the +X eye."""
    d = drawing['views']['front']['strokes']
    lid = np.array(d['upper lid + wing']['source_xy_width'], float)
    lower = np.array(d['outer lower lid']['source_xy_width'], float)
    inner_d, outer_d = (560., 288.), (632., 275.)
    E = catmull(V[up][:, [0, 2]], 6)
    Lw = catmull(V[low][:, [0, 2]], 6)
    S = similarity(inner_d, outer_d, E[0], E[-1])
    nE = left_normal(E)                                # up, away from the opening
    nE *= np.sign(nE[len(nE) // 2, 1])
    nL = left_normal(Lw)
    nL *= -np.sign(nL[len(nL) // 2, 1])                # down, away from the opening
    hw_d = lid[:, 2] / 2 * S.scale
    body = lid[:, 0] <= outer_d[0]
    s, _ = project_2d(E, S(lid[body, :2]))
    sE = cumlen(E)
    centre = at_length(E, s) + np.interp(s, sE, nE[:, 0])[:, None] * 0 + 0
    nn = np.stack([np.interp(s, sE, nE[:, 0]), np.interp(s, sE, nE[:, 1])], 1)
    nn /= np.linalg.norm(nn, axis=1)[:, None]
    centre = at_length(E, s) + nn * (hw_d[body] - p['lid_overlap_m']).clip(0)[:, None]
    centre[0] = E[0]
    canthus_centre = centre[-1]
    wing = S(lid[~body, :2]) + (canthus_centre - S(lid[body][-1:, :2])[0])
    pts, hw = smooth_curve(np.vstack([centre, wing]), hw_d)
    upper = Stroke('upper lid', pts, hw)

    def lid_at(q):
        sq, off = project_2d(pts, q)
        k = np.clip(np.searchsorted(cumlen(pts), sq), 0, len(pts) - 1)
        nrm = left_normal(pts)[k]
        nrm *= np.sign(nrm[:, 1])[:, None]
        return sq, at_length(pts, sq), nrm, np.interp(sq, cumlen(pts), hw)

    lashes = []
    drawn_c, drawn_hw = lid[:, :2], lid[:, 2] / 2
    for key in ('lash 1', 'lash 2'):
        L = np.array(d[key]['source_xy_width'], float)
        # Where the root sits in the drawn lid: its share of the drawn half-width above it.
        sd, offd = project_2d(drawn_c * [1, -1], (L[:1, :2] * [1, -1]))
        k = offd[0] / np.interp(sd[0], cumlen(drawn_c * [1, -1]), drawn_hw)
        root_design = S(L[:1, :2])
        _, c3, nrm, h3 = lid_at(root_design)
        root = c3[0] + nrm[0] * k * h3[0]
        rest = root + (S(L[:, :2]) - S(L[:1, :2]))
        lp = np.vstack([c3[0], rest])
        lw = np.concatenate([[L[0, 2] / 2], L[:, 2] / 2]) * S.scale
        lashes.append(Stroke(key, *smooth_curve(lp, lw, 4)))

    sL = cumlen(Lw)
    s, _ = project_2d(Lw, S(lower[:, :2]))
    hw_l = lower[:, 2] / 2 * S.scale * p['lower_gain']
    nn = np.stack([np.interp(s, sL, nL[:, 0]), np.interp(s, sL, nL[:, 1])], 1)
    nn /= np.linalg.norm(nn, axis=1)[:, None]
    lc = at_length(Lw, s) + nn * (hw_l - p['lid_overlap_m'] * .8).clip(0)[:, None]
    lower_stroke = Stroke('lower lid', *smooth_curve(lc, hw_l, 4))
    brow = np.array(d['brow']['source_xy_width'], float)
    brow_stroke = Stroke('brow', *smooth_curve(S(brow[:, :2]), brow[:, 2] / 2 * S.scale * p['brow_gain'], 6))
    info = dict(eye_scale_m_per_px=S.scale, eye_width_m=float(np.linalg.norm(E[-1] - E[0])))
    return upper, lashes, lower_stroke, brow_stroke, info


def mirror(stroke):
    return Stroke(stroke.name, stroke.pts * [-1, 1], stroke.hw)


def nose_strokes(V, skin, irises, drawing, p):
    """Nostrils from the face similarity through the pupils. The drawn three-quarter underside
    stroke is the nose's midline profile, a silhouette: as a surface stroke it would draw a
    vertical line under the tip in front, where the front drawing has none. The underside is
    carried by the painted underside shade instead (paint.py)."""
    d = drawing['views']['front']['strokes']
    left = min(irises, key=lambda c: c[0])
    right = max(irises, key=lambda c: c[0])
    G = similarity((455., 277.), (594., 277.), (left[0], left[2]), (right[0], right[2]))
    out = []
    for key in ('nostril A', 'nostril B'):
        N = np.array(d[key]['source_xy_width'], float)
        out.append(Stroke(key, *smooth_curve(G(N[:, :2]), N[:, 2] / 2 * G.scale * p['nostril_gain'], 4)))
    return out, dict(face_scale_m_per_px=G.scale), G


def smooth_spine(pts, reach, degrees=(4, 3, 2, 1)):
    """A spine for a stroke's carrier: the highest-degree polynomial fit over the stroke's chord
    whose radius of curvature stays above 1.3 x the reach, so rows offset by the reach never
    cross. Returns the spine (extended straight by `reach` at both ends) and the stroke's signed
    offsets from it."""
    a, b = pts[0], pts[-1]
    u = (b - a) / np.linalg.norm(b - a)
    v = np.array([-u[1], u[0]])
    x, y = (pts - a) @ u, (pts - a) @ v
    xs = np.linspace(x.min(), x.max(), 60)
    for deg in degrees:
        c = np.polyfit(x, y, min(deg, len(x) - 1))
        d1, d2 = np.polyval(np.polyder(c), xs), np.polyval(np.polyder(c, 2), xs)
        k = np.abs(d2) / (1 + d1 * d1) ** 1.5
        if k.max() * 1.3 * reach < 1:
            break
    sp = a + xs[:, None] * u + np.polyval(c, xs)[:, None] * v
    return extend(sp, reach), y - np.polyval(c, x)


def ribbon_for(name, stroke, rng, p, ds, rows):
    """A carrier round one stroke: it reaches `range` plus a margin beyond the centreline on
    each side and past each end (docs/HANDMADE_INK.md, "Carriers"), in `rows` rows, about a
    smooth spine that its rows never fold over."""
    reach = rng + p['margin_m']
    spine, dev = smooth_spine(stroke.pts, reach)
    spine, dev = smooth_spine(stroke.pts, reach + max(0., -dev.min(), dev.max()))
    o0, o1 = -(reach + max(0., -dev.min())), reach + max(0., dev.max())
    if o1 - o0 < 1e-6:
        o1 = o0 + 1e-3
    rb = Ribbon(name, spine, o0, o1, ds, (o1 - o0) / (rows - 1) * (1 - 1e-9))
    rb.strokes.append(stroke)
    return rb


def core_for(name, stroke, p, ds=.0035):
    hw = stroke.hw - np.maximum(p['core_inset'] * stroke.hw, p['core_margin_m'])
    keep = hw > 1e-5
    if keep.sum() < 2:
        return None
    i0, i1 = np.flatnonzero(keep)[[0, -1]]
    pts, hw = stroke.pts[i0:i1 + 1], hw[i0:i1 + 1].clip(1e-5)
    rb = Ribbon(name, pts, -1, 1, ds, 2.)
    L = cumlen(pts)
    h = np.interp(rb.s, L, hw)
    C = at_length(pts, rb.s)
    dense = at_length(pts, np.linspace(0, L[-1], 4 * len(rb.s)))
    N = left_normal(dense)[np.linspace(0, 4 * len(rb.s) - 1, len(rb.s)).round().astype(int)]
    rb.design = C[:, None, :] + (rb.o[None, :, None] * h[:, None, None]) * N[:, None, :]
    return rb


def face_outline(skin, centre, z_top, p, step=.0002):
    """The face's outline in the front view below `z_top`: for rays fanning down from `centre`
    in the (x, z) plane, the farthest point whose front ray still meets front-facing skin."""
    A, B, C = skin.abc()
    out = []
    for ang in np.radians(np.arange(-88, 88.1, 1.)):
        d = np.array([np.sin(ang), -np.cos(ang)])
        r = np.arange(.02, .09, step)
        Q = centre + r[:, None] * d
        O = np.stack([Q[:, 0], np.full(len(r), -1.), Q[:, 1]], 1)
        t, _, _ = raycast(O, np.array([0., 1., 0.]), A, B, C, cull=True)
        ok = np.flatnonzero(np.isfinite(t) & (t < .97))
        if len(ok):
            out.append(centre + r[ok.max()] * d)
    out = np.array(out)
    out = out[out[:, 1] <= z_top]
    out = at_length(out, np.linspace(0, cumlen(out)[-1], 160))
    for _ in range(p['outline_smooth']):
        out[1:-1] = .25 * out[:-2] + .5 * out[1:-1] + .25 * out[2:]
    return out


def build(V, VN, T_skin, eye_loop, irises, drawing, p=PARAMS):
    skin = Surface(V, T_skin, VN)
    up, low = hole_chains(V, eye_loop)
    upper, lashes, lower, brow, info = lid_strokes(V, up, low, drawing, p)
    noses, ninfo, G = nose_strokes(V, skin, irises, drawing, p)
    info.update(ninfo)
    er, sr = p['eyes_range_m'], p['skin_range_m']
    eyes, skins, cores = [], [], []
    for side, tag in ((1, 'R'), (-1, 'L')):
        m = (lambda s: s) if side == 1 else mirror
        eyes.append(ribbon_for(f'lid {tag}', m(upper), er, p, .0035, 4))
        for k, ls in enumerate(lashes):
            eyes.append(ribbon_for(f'lash {k + 1} {tag}', m(ls), er, p, .003, 3))
        eyes.append(ribbon_for(f'lower lid {tag}', m(lower), er, p, .004, 3))
        eyes.append(ribbon_for(f'brow {tag}', m(brow), er, p, .004, 4))
        for name, st in ((f'lid core {tag}', m(upper)),):
            c = core_for(name, st, p)
            if c is not None:
                cores.append(c)
    for st in noses:
        skins.append(ribbon_for(st.name, st, sr, p, .003, 3))
    jaw, jinfo = jaw_stroke(skin, drawing, G, p)
    info.update(jinfo)
    skins.append(ribbon_for('jaw', jaw, sr, p, .0035, 3))
    for rb in eyes + skins + cores:
        off = (p['core_offset_m'] if 'core' in rb.name else p['skin_offset_m'] if rb in skins
               else p['carrier_offset_m'])
        lift_front(rb, skin, off, min_facing=p['jaw_min_facing'] if rb.name == 'jaw' else .35)
        rb.N = rb.N / np.linalg.norm(rb.N, axis=-1)[..., None]
        rb.clear = p['core_clear_m'] if 'core' in rb.name else p['carrier_clear_m']
        rb.P = clearance(rb.P, rb.N, skin, V, rb.clear)
    return dict(eyes=eyes, skins=skins, cores=cores, info=info, G=G, skin=skin)


def jaw_stroke(skin, drawing, G, p):
    """The jaw line just inside the face's own front outline, between the drawn end heights,
    with the drawn projected width profile; its outer edge sits `jaw_inset_m` inside."""
    J = np.array(drawing['views']['front']['strokes']['jaw']['source_xy_width'], float)
    z_top = float(G(J[[0, -1], :2])[:, 1].mean())
    O = face_outline(skin, np.array([0., z_top + .017]), z_top - p['jaw_end_drop_m'], p)
    O = at_length(O, np.linspace(0, cumlen(O)[-1], 160))
    t_d = cumlen(J[:, :2]) / cumlen(J[:, :2])[-1]
    t_o = cumlen(O) / cumlen(O)[-1]
    hw = np.interp(t_o, t_d, J[:, 2] / 2 * G.scale)
    n = left_normal(O)
    n *= np.sign((n * (np.array([0., z_top + .017]) - O)).sum(1))[:, None]   # inward
    pts = O + n * (hw + p['jaw_inset_m'])[:, None]
    st = Stroke('jaw', pts, hw)
    return st, dict(jaw_top_z=z_top, jaw_length_m=float(cumlen(pts)[-1]))


def finish(R, p=PARAMS, size=2048):
    """Map every carrier by its own lengths, pack each slot's map and write its strokes."""
    from carriers import flatten, isometry, pack, stroke_uv
    maps = {}
    for key, rbs, rng, side in (('eyes', R['eyes'], p['eyes_range_m'], p['eyes_side_m']),
                                ('skin', R['skins'], p['skin_range_m'], p['skin_side_m'])):
        dens = []
        for rb in rbs:
            S, O = np.meshgrid(rb.s, rb.o, indexing='ij')
            rb.uv_m = flatten(rb.P, np.stack([S, O], -1))
            dens.append(isometry(rb.P, rb.uv_m))
        texel = side / size
        used = pack(rbs, side, 2 * rng + 8 * texel)
        strokes, widths = [], {}
        for rb in rbs:
            for st in rb.strokes:
                pts, stretch = stroke_uv(rb, st.pts, st.hw, rng, p['max_stretch'])
                strokes.append(dict(name=rb.name, points=[[round(a, 6), round(b, 6), round(min(c, 1.), 5)] for a, b, c in pts]))
                widths[rb.name] = dict(max_f=float(max(c for _, _, c in pts)),
                                       max_surface_hw_mm=float(max(c for _, _, c in pts) * rng * 1000),
                                       stretch=[float(stretch.min()), float(stretch.max())])
        d = np.concatenate(dens)
        med = np.median(d)
        maps[key] = dict(size=[size, size], range_m=rng, side_m=side, range_uv=rng / side,
                         used_fraction=float(used), m_uv_median=float(med),
                         density_within_25=float(np.mean(np.abs(d / med - 1) <= .25)),
                         strokes=strokes, widths=widths)
    return maps
