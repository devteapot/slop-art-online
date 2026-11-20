"""Attempt 2 of the ink batch: the upper lid's weight, on top of the first attempt's design.

Reuses ../ink-batch/design.py and carriers.py unchanged. What differs:

- the upper lid's drawn half-widths are scaled by `lid_gain` over the outer two thirds (a
  smoothstep from `lid_gain_from` to `lid_gain_to` of the canthus-to-canthus fraction, the
  wing included), with the stroke still growing upward from the same opening edge;
- a lash fringe: a separate stroke on its own island, a sawtooth along the band's top edge
  (roots inside the band, tapered tips out along the lid's normal and leaning outward), over the
  outer two thirds and into the wing root;
- the lash flicks sit on the wider band's top edge;
- the passed strokes (brows, outer lower lids) are the first attempt's ribbons, mapped and packed
  exactly as there, so their carriers and their texels in the eyes map stay the same; the new
  lid islands are placed in the free space around them;
- no jaw and no nostril carriers (the jaw is dropped; the nostrils are painted).
"""
import numpy as np
import design as d1
from carriers import (at_length, clearance, cumlen, flatten, isometry, left_normal, lift_front,
                      pack, project_2d, stroke_uv)

PARAMS2 = dict(d1.PARAMS,
               margin_m=.003,            # the new islands reach range + 3 mm (the lid's curve compresses its inner side)
               lid_gain=1.25,            # drawn lid half-width x gain over the outer two thirds
               lid_gain_from=.12,
               lid_gain_to=.42,
               fringe_from=.30,          # canthus-to-canthus fraction where the fringe starts
               fringe_to=.97,            # and ends (just inside the outer canthus: the wing stays clean)
               fringe_spacing_m=.0009,   # spike spacing along the band's top edge
               fringe_length_m=.0008,    # spike length out of the band at full envelope
               fringe_lean=.35,          # outward lean of a spike (tangent share)
               fringe_root_hw_m=.00045,  # half-width at a spike's root
               fringe_root_inset=.35)    # root depth inside the band, in band half-widths


def smoothstep(a, b, x):
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def lid_strokes2(V, up, low, drawing, p):
    """The upper lid (gained), its lash flicks and its fringe, for the +X eye."""
    S_ = d1
    d = drawing['views']['front']['strokes']
    lid = np.array(d['upper lid + wing']['source_xy_width'], float)
    inner_d, outer_d = (560., 288.), (632., 275.)
    E = S_.catmull(V[up][:, [0, 2]], 6)
    S = S_.similarity(inner_d, outer_d, E[0], E[-1])
    nE = left_normal(E)
    nE *= np.sign(nE[len(nE) // 2, 1])
    x_in, x_out = E[0, 0], E[-1, 0]
    t_of = lambda x: (np.asarray(x) - x_in) / (x_out - x_in)
    hw_d = lid[:, 2] / 2 * S.scale
    body = lid[:, 0] <= outer_d[0]
    # The gain by where each drawn point falls along the eye (the wing beyond keeps the gain).
    t_drawn = t_of(S(lid[:, :2])[:, 0])
    gain = 1 + (p['lid_gain'] - 1) * smoothstep(p['lid_gain_from'], p['lid_gain_to'], t_drawn)
    hw_d = hw_d * gain
    s, _ = project_2d(E, S(lid[body, :2]))
    sE = cumlen(E)
    nn = np.stack([np.interp(s, sE, nE[:, 0]), np.interp(s, sE, nE[:, 1])], 1)
    nn /= np.linalg.norm(nn, axis=1)[:, None]
    centre = at_length(E, s) + nn * (hw_d[body] - p['lid_overlap_m']).clip(0)[:, None]
    centre[0] = E[0]
    canthus_centre = centre[-1]
    wing = S(lid[~body, :2]) + (canthus_centre - S(lid[body][-1:, :2])[0])
    pts, hw = S_.smooth_curve(np.vstack([centre, wing]), hw_d)
    upper = S_.Stroke('upper lid', pts, hw)
    L = cumlen(pts)
    up_n = left_normal(pts)
    up_n *= np.sign(up_n[:, 1])[:, None]
    tang = np.gradient(pts, axis=0)
    tang /= np.linalg.norm(tang, axis=1)[:, None]

    def lid_at(q):
        sq, _ = project_2d(pts, q)
        k = np.clip(np.searchsorted(L, sq), 0, len(pts) - 1)
        return sq, at_length(pts, sq), up_n[k], np.interp(sq, L, hw)

    lashes = []
    drawn_c, drawn_hw = lid[:, :2], lid[:, 2] / 2
    for key in ('lash 1', 'lash 2'):
        Ls = np.array(d[key]['source_xy_width'], float)
        sd, offd = project_2d(drawn_c * [1, -1], (Ls[:1, :2] * [1, -1]))
        k = offd[0] / np.interp(sd[0], cumlen(drawn_c * [1, -1]), drawn_hw)
        _, c3, nrm, h3 = lid_at(S(Ls[:1, :2]))
        root = c3[0] + nrm[0] * k * h3[0]
        rest = root + (S(Ls[:, :2]) - S(Ls[:1, :2]))
        lp = np.vstack([c3[0], rest])
        lw = np.concatenate([[Ls[0, 2] / 2], Ls[:, 2] / 2]) * S.scale
        lashes.append(S_.Stroke(key, *S_.smooth_curve(lp, lw, 4)))

    # The fringe: a sawtooth along the band's top edge.
    t_pts = t_of(pts[:, 0])
    on = np.flatnonzero((t_pts >= p['fringe_from']) & (t_pts <= p['fringe_to']))
    s0, s1 = L[on[0]], L[on[-1]]
    n_sp = int((s1 - s0) / p['fringe_spacing_m'])
    fp, fw = [], []
    for i in range(n_sp + 1):
        sk = s0 + i * p['fringe_spacing_m']
        k = min(int(np.searchsorted(L, sk)), len(pts) - 1)
        h = np.interp(sk, L, hw)
        c = at_length(pts, sk)[0]
        tk = t_of(c[0])
        env = smoothstep(p['fringe_from'], p['fringe_from'] + .15, tk) * (1 - .6 * smoothstep(.95, p['fringe_to'], tk))
        root = c + up_n[k] * h * (1 - p['fringe_root_inset'])
        fp.append(root)
        fw.append(p['fringe_root_hw_m'] * max(env, .3))
        if i < n_sp:
            sm = sk + .5 * p['fringe_spacing_m']
            km = min(int(np.searchsorted(L, sm)), len(pts) - 1)
            cm = at_length(pts, sm)[0]
            hm = np.interp(sm, L, hw)
            out = up_n[km] + p['fringe_lean'] * tang[km]
            out /= np.linalg.norm(out)
            fp.append(cm + up_n[km] * hm + out * p['fringe_length_m'] * env)
            fw.append(0.)
    fringe = S_.Stroke('lash fringe', np.array(fp), np.array(fw))
    return upper, lashes, fringe


def build2(V, VN, T_skin, eye_loop, irises, drawing, p=PARAMS2):
    skin = d1.Surface(V, T_skin, VN)
    up, low = d1.hole_chains(V, eye_loop)
    # The first attempt's eye strokes, built exactly as there (their islands are pinned).
    upper1, lashes1, lower, brow, info = d1.lid_strokes(V, up, low, drawing, d1.PARAMS)
    upper, lashes, fringe = lid_strokes2(V, up, low, drawing, p)
    er = p['eyes_range_m']
    first, kept, new, cores, eyes = [], [], [], [], []
    for side, tag in ((1, 'R'), (-1, 'L')):
        m = (lambda s: s) if side == 1 else d1.mirror
        first.append(d1.ribbon_for(f'lid {tag}', m(upper1), er, d1.PARAMS, .0035, 4))
        for k, ls in enumerate(lashes1):
            first.append(d1.ribbon_for(f'lash {k + 1} {tag}', m(ls), er, d1.PARAMS, .003, 3))
        low_rb = d1.ribbon_for(f'lower lid {tag}', m(lower), er, d1.PARAMS, .004, 3)
        brow_rb = d1.ribbon_for(f'brow {tag}', m(brow), er, d1.PARAMS, .004, 4)
        first += [low_rb, brow_rb]
        kept += [low_rb, brow_rb]
        side_new = [d1.ribbon_for(f'lid {tag}', m(upper), er, p, .0035, 4)]
        for k, ls in enumerate(lashes):
            side_new.append(d1.ribbon_for(f'lash {k + 1} {tag}', m(ls), er, p, .003, 3))
        fr = d1.ribbon_for(f'lash fringe {tag}', m(fringe), er, p, .0035, 3)
        new += side_new + [fr]
        # The first attempt's order (lid, lashes, lower lid, brow), the fringe after them.
        eyes += side_new + [low_rb, brow_rb, fr]
        c = d1.core_for(f'lid core {tag}', m(upper), p)
        if c is not None:
            cores.append(c)
    for rb in first + new + cores:
        off = p['core_offset_m'] if 'core' in rb.name else p['carrier_offset_m']
        lift_front(rb, skin, off, min_facing=.35)
        rb.N = rb.N / np.linalg.norm(rb.N, axis=-1)[..., None]
        rb.clear = p['core_clear_m'] if 'core' in rb.name else p['carrier_clear_m']
        rb.P = clearance(rb.P, rb.N, skin, V, rb.clear)
    return dict(first=first, kept=kept, eyes=eyes, new=new, cores=cores, info=info, skin=skin)


def free_place(boxes, size, side, gap):
    """First position, scanning rows then columns every millimetre, where a `size` box clears
    every placed box by `gap`, inside the map."""
    w, h = size
    for y in np.arange(gap, side - h - gap + 1e-9, .001):
        for x in np.arange(gap, side - w - gap + 1e-9, .001):
            if all(x + w + gap <= bx or bx + bw + gap <= x or y + h + gap <= by or by + bh + gap <= y
                   for bx, by, bw, bh in boxes):
                return float(x), float(y)
    raise AssertionError('map too small')


def finish2(R, p=PARAMS2, size=2048):
    """Map every carrier by its own lengths. The first attempt's layout is reproduced to pin the
    kept islands; the new ones go into the space left round them."""
    rng, side = p['eyes_range_m'], p['eyes_side_m']
    texel = side / size
    gap = 2 * rng + 8 * texel
    for rb in R['first'] + R['new']:
        S_, O_ = np.meshgrid(rb.s, rb.o, indexing='ij')
        rb.uv_m = flatten(rb.P, np.stack([S_, O_], -1))
    pack(R['first'], side, gap)                     # the first attempt's packing, as it was
    boxes = []
    for rb in R['kept']:
        U = rb.uv.reshape(-1, 2) * side
        lo, hi = U.min(0), U.max(0)
        boxes.append((lo[0], lo[1], hi[0] - lo[0], hi[1] - lo[1]))
    def turned(rb):
        U = rb.uv_m.reshape(-1, 2)
        U = U - U.mean(0)
        _, v = np.linalg.eigh(np.cov(U.T))
        Rm = v[:, ::-1]
        if np.linalg.det(Rm) < 0:
            Rm[:, 1] *= -1
        U = U @ Rm
        return U - U.min(0)
    for rb in sorted(R['new'], key=lambda r: -turned(r)[:, 1].max()):
        U = turned(rb)
        x, y = free_place(boxes, tuple(U.max(0)), side, gap)
        boxes.append((x, y, *U.max(0)))
        rb.uv = ((U + [x, y]) / side).reshape(rb.uv_m.shape)
    dens = np.concatenate([isometry(rb.P, rb.uv_m) for rb in R['eyes']])
    med = np.median(dens)
    strokes, widths = [], {}
    for rb in R['eyes']:
        for st in rb.strokes:
            pts, stretch = stroke_uv(rb, st.pts, st.hw, rng, p['max_stretch'])
            strokes.append(dict(name=rb.name, points=[[round(a, 6), round(b, 6), round(min(c, 1.), 5)] for a, b, c in pts]))
            widths[rb.name] = dict(max_f=float(max(c for _, _, c in pts)),
                                   max_surface_hw_mm=float(max(c for _, _, c in pts) * rng * 1000))
    used = max(by + bh for _, by, _, bh in boxes) / side
    return {'eyes': dict(size=[size, size], range_m=rng, side_m=side, range_uv=rng / side,
                         used_fraction=float(used), m_uv_median=float(med),
                         density_within_25=float(np.mean(np.abs(dens / med - 1) <= .25)),
                         strokes=strokes, widths=widths)}
