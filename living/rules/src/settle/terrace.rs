//! Terraced settlements: where a settlement's site has relief, its ground steps down the hill
//! in level terraces with a steep drop between them (see `docs/FIRST_WORLD.md`).
//!
//! A terrace zone follows the site's natural ground, smoothed over about 12 m so its drops run
//! along clean contours: level `i` covers ground between `base + (i - 0.5) * step` and
//! `base + (i + 0.5) * step`, and is flat at `base + i * step`. The drop to the next level is
//! `drop_m` wide wherever the hill is steeper than that allows, and gentler where it is not. The
//! zone fades back to the natural ground beyond `r_in`.
//!
//! Streets crossing a drop become ramps (their graded profiles average over it), lanes stop
//! short of it, and the planner puts stairs (sloped pads) and retaining walls (props) on it.
//! [`paint_drops`] turns tiles beside any drop steeper than a step can climb into `Wall`, so
//! walking agrees with the ground: only roads, ramps and stairs join the levels.

use super::*;

#[derive(Clone, Debug)]
pub(crate) struct Terrace {
    /// Index into [`Land::sites`].
    pub(crate) site: u16,
    pub(crate) c: V2,
    pub(crate) r_in: f32,
    pub(crate) r_out: f32,
    pub(crate) base: f32,
    pub(crate) step: f32,
    pub(crate) drop_m: f32,
    x0: f32,
    y0: f32,
    cell: f32,
    n: usize,
    /// Smoothed natural ground and its gradient at the grid's nodes.
    s: Vec<f32>,
    g: Vec<V2>,
}

impl Terrace {
    /// Sample the ground around a site on a 4 m grid and smooth it.
    pub(crate) fn new(land: &Land, site: u16, c: V2, r_in: f32, r_out: f32, step: f32, drop_m: f32) -> Self {
        let cell = 4.0;
        let half = r_out + 4.0 * cell;
        let n = (2.0 * half / cell).ceil() as usize + 1;
        let (x0, y0) = (c.0 - half, c.1 - half);
        let mut s: Vec<f32> = (0..n * n)
            .map(|k| {
                let (x, y) = (x0 + (k % n) as f32 * cell, y0 + (k / n) as f32 * cell);
                let (x, y) = (x.clamp(0.5, land.size as f32 - 0.5), y.clamp(0.5, land.size as f32 - 0.5));
                land.height(x, y)
            })
            .collect();
        // Two box passes of radius 2 (about a 12 m kernel), separable.
        for _ in 0..2 {
            for axis in 0..2 {
                let src = s.clone();
                for j in 0..n {
                    for i in 0..n {
                        let (mut acc, mut w) = (0.0, 0.0);
                        for d in -2i32..=2 {
                            let (ii, jj) = if axis == 0 { (i as i32 + d, j as i32) } else { (i as i32, j as i32 + d) };
                            if ii >= 0 && jj >= 0 && (ii as usize) < n && (jj as usize) < n {
                                acc += src[jj as usize * n + ii as usize];
                                w += 1.0;
                            }
                        }
                        s[j * n + i] = acc / w;
                    }
                }
            }
        }
        let at = |i: usize, j: usize| s[j.min(n - 1) * n + i.min(n - 1)];
        let g = (0..n * n)
            .map(|k| {
                let (i, j) = (k % n, k / n);
                let (il, ir) = (i.saturating_sub(1), (i + 1).min(n - 1));
                let (jd, ju) = (j.saturating_sub(1), (j + 1).min(n - 1));
                ((at(ir, j) - at(il, j)) / ((ir - il).max(1) as f32 * cell), (at(i, ju) - at(i, jd)) / ((ju - jd).max(1) as f32 * cell))
            })
            .collect();
        let mut z = Self { site, c, r_in, r_out, base: 0.0, step, drop_m, x0, y0, cell, n, s, g };
        z.base = z.smooth(c).0;
        z
    }

    /// Smoothed ground and its gradient at a point (bilinear, so both are continuous).
    pub(crate) fn smooth(&self, p: V2) -> (f32, V2) {
        let n = self.n;
        let fx = ((p.0 - self.x0) / self.cell).clamp(0.0, (n - 1) as f32 - 1e-3);
        let fy = ((p.1 - self.y0) / self.cell).clamp(0.0, (n - 1) as f32 - 1e-3);
        let (i, j) = (fx.floor() as usize, fy.floor() as usize);
        let (tx, ty) = (fx - i as f32, fy - j as f32);
        let k = j * n + i;
        let s = lerp(lerp(self.s[k], self.s[k + 1], tx), lerp(self.s[k + n], self.s[k + n + 1], tx), ty);
        let gx = lerp(lerp(self.g[k].0, self.g[k + 1].0, tx), lerp(self.g[k + n].0, self.g[k + n + 1].0, tx), ty);
        let gy = lerp(lerp(self.g[k].1, self.g[k + 1].1, tx), lerp(self.g[k + n].1, self.g[k + n + 1].1, tx), ty);
        (s, (gx, gy))
    }

    /// How fully the terraces apply at a point (1 inside `r_in`, 0 beyond `r_out`).
    pub(crate) fn weight(&self, p: V2) -> f32 {
        1.0 - smoothstep(self.r_in, self.r_out, dist(p, self.c))
    }

    /// Position in level units (level `i` is flat around `u = i + 0.5`) and the drop's width
    /// there as a fraction of a level.
    fn u_eps(&self, p: V2) -> (f32, f32) {
        let (s, g) = self.smooth(p);
        let eps = (self.drop_m * len(g) / self.step).clamp(0.02, 0.5);
        ((s - self.base) / self.step + 0.5, eps)
    }

    /// The terrace level at a point: flat plateaus with a smooth drop between them.
    pub(crate) fn level(&self, p: V2) -> f32 {
        let (u, eps) = self.u_eps(p);
        let i = u.floor();
        self.base + self.step * (i + smoothstep(1.0 - eps, 1.0, u - i))
    }

    /// The plateau a point stands on (ignoring the drop's width).
    pub(crate) fn index(&self, p: V2) -> i32 {
        self.u_eps(p).0.floor() as i32
    }

    /// The flat level of plateau `i`.
    pub(crate) fn plateau(&self, i: i32) -> f32 {
        self.base + self.step * i as f32
    }

    /// The nearest plateau level to a height.
    pub(crate) fn snap(&self, h: f32) -> f32 {
        self.base + self.step * ((h - self.base) / self.step).round()
    }

    /// Ground `h` with the terraces applied, faded by `wf` (near water).
    #[inline]
    pub(crate) fn apply(&self, p: V2, h: f32, wf: f32) -> f32 {
        let d2 = (p.0 - self.c.0) * (p.0 - self.c.0) + (p.1 - self.c.1) * (p.1 - self.c.1);
        if d2 >= self.r_out * self.r_out {
            return h;
        }
        let w = self.weight(p) * wf;
        if w <= 0.0 {
            return h;
        }
        lerp(h, self.level(p), w)
    }

    /// Range of the smoothed ground within `r` of the centre.
    pub(crate) fn relief(&self, r: f32) -> f32 {
        let (mut lo, mut hi) = (f32::MAX, f32::MIN);
        for k in 0..self.n * self.n {
            let p = (self.x0 + (k % self.n) as f32 * self.cell, self.y0 + (k / self.n) as f32 * self.cell);
            if dist(p, self.c) <= r {
                lo = lo.min(self.s[k]);
                hi = hi.max(self.s[k]);
            }
        }
        (hi - lo).max(0.0)
    }

    /// The mid-lines of the drops, as polylines (1 m resolution), where the terraces apply in
    /// full and the ground is dry: `(lower plateau, points)`. Each runs along a contour.
    pub(crate) fn risers(&self, land: &Land) -> Vec<(i32, Vec<V2>)> {
        let half = self.r_in;
        let m = (2.0 * half).ceil() as usize + 1;
        let (ox, oy) = (self.c.0 - half, self.c.1 - half);
        let pt = |i: usize, j: usize| (ox + i as f32, oy + j as f32);
        let mut u = vec![f32::NAN; m * m];
        let (mut lo, mut hi) = (i32::MAX, i32::MIN);
        for j in 0..m {
            for i in 0..m {
                let p = pt(i, j);
                if p.0 < 1.0 || p.1 < 1.0 || p.0 > land.size as f32 - 1.0 || p.1 > land.size as f32 - 1.0 || self.weight(p) < 0.999 || land.sd_at(p.0, p.1) < 14.0 {
                    continue;
                }
                let (uu, eps) = self.u_eps(p);
                // Shift so the drop's middle (u = k + 1 - eps / 2) is the zero of `u - (k + 1)`.
                u[j * m + i] = uu + eps * 0.5;
                lo = lo.min(uu.floor() as i32);
                hi = hi.max(uu.floor() as i32);
            }
        }
        let mut out = Vec::new();
        if lo > hi {
            return out;
        }
        for k in lo..hi + 1 {
            let lvl = (k + 1) as f32;
            let f: Vec<f32> = u.iter().map(|v| v - lvl).collect();
            for line in iso_lines(&f, m, |i, j| pt(i, j)) {
                if line.len() >= 3 {
                    out.push((k, line));
                }
            }
        }
        out
    }
}

/// Zero lines of a field on an `m` × `m` grid (NaN marks cells to skip), chained into
/// polylines by marching squares. Deterministic: segments are visited in grid order.
fn iso_lines(f: &[f32], m: usize, pt: impl Fn(usize, usize) -> V2) -> Vec<Vec<V2>> {
    // Edge ids: horizontal edge from (i, j) to (i + 1, j) is 2k, vertical to (i, j + 1) is 2k + 1.
    let eid = |i: usize, j: usize, vertical: bool| (2 * (j * m + i) + vertical as usize) as u32;
    let cross = |a: (usize, usize), b: (usize, usize)| {
        let (fa, fb) = (f[a.1 * m + a.0], f[b.1 * m + b.0]);
        let t = (fa / (fa - fb)).clamp(0.0, 1.0);
        let (pa, pb) = (pt(a.0, a.1), pt(b.0, b.1));
        (lerp(pa.0, pb.0, t), lerp(pa.1, pb.1, t))
    };
    let mut segs: Vec<(u32, u32, V2, V2)> = Vec::new();
    for j in 0..m - 1 {
        for i in 0..m - 1 {
            let c = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)];
            let v: Vec<f32> = c.iter().map(|q| f[q.1 * m + q.0]).collect();
            if v.iter().any(|x| x.is_nan()) {
                continue;
            }
            let idx = (v[0] > 0.0) as u8 | ((v[1] > 0.0) as u8) << 1 | ((v[2] > 0.0) as u8) << 2 | ((v[3] > 0.0) as u8) << 3;
            // Edges: 0 bottom (c0-c1), 1 right (c1-c2), 2 top (c3-c2), 3 left (c0-c3).
            let e = |k: usize| match k {
                0 => (eid(i, j, false), cross(c[0], c[1])),
                1 => (eid(i + 1, j, true), cross(c[1], c[2])),
                2 => (eid(i, j + 1, false), cross(c[3], c[2])),
                _ => (eid(i, j, true), cross(c[0], c[3])),
            };
            let centre = (v[0] + v[1] + v[2] + v[3]) * 0.25 > 0.0;
            let pairs: &[(usize, usize)] = match idx {
                0 | 15 => &[],
                1 | 14 => &[(3, 0)],
                2 | 13 => &[(0, 1)],
                3 | 12 => &[(3, 1)],
                4 | 11 => &[(1, 2)],
                6 | 9 => &[(0, 2)],
                7 | 8 => &[(3, 2)],
                5 => {
                    if centre {
                        &[(3, 2), (0, 1)]
                    } else {
                        &[(3, 0), (1, 2)]
                    }
                }
                _ => {
                    if centre {
                        &[(3, 0), (1, 2)]
                    } else {
                        &[(3, 2), (0, 1)]
                    }
                }
            };
            for &(a, b) in pairs {
                let (ea, pa) = e(a);
                let (eb, pb) = e(b);
                segs.push((ea, eb, pa, pb));
            }
        }
    }
    // Chain: each edge joins at most two segments.
    let mut at: std::collections::HashMap<u32, [u32; 2]> = std::collections::HashMap::new();
    for (si, s) in segs.iter().enumerate() {
        for e in [s.0, s.1] {
            let slot = at.entry(e).or_insert([u32::MAX; 2]);
            if slot[0] == u32::MAX {
                slot[0] = si as u32;
            } else {
                slot[1] = si as u32;
            }
        }
    }
    let mut used = vec![false; segs.len()];
    let mut lines = Vec::new();
    for start in 0..segs.len() {
        if used[start] {
            continue;
        }
        used[start] = true;
        let mut line: std::collections::VecDeque<V2> = [segs[start].2, segs[start].3].into_iter().collect();
        for (dir, mut e) in [(1, segs[start].1), (0, segs[start].0)] {
            loop {
                let Some(slot) = at.get(&e) else { break };
                let Some(&next) = slot.iter().find(|&&s| s != u32::MAX && !used[s as usize]) else { break };
                used[next as usize] = true;
                let s = &segs[next as usize];
                let (p, ne) = if s.0 == e { (s.3, s.1) } else { (s.2, s.0) };
                if dir == 1 {
                    line.push_back(p);
                } else {
                    line.push_front(p);
                }
                e = ne;
            }
        }
        lines.push(dedup(line.into_iter().collect()));
    }
    lines
}

/// Terrace zones for every settlement whose style terraces and whose site has the relief.
pub(crate) fn terraces(land: &Land, p: &SettleParams) -> Vec<Terrace> {
    let mut out = Vec::new();
    for (si, site) in land.sites.iter().enumerate() {
        if site.kind == SiteKind::Cave || site.plan.is_some() {
            continue;
        }
        let Some(st) = p.style_for_site(site) else { continue };
        if st.terrace_m <= 0.0 {
            continue;
        }
        let k = site.scale.max(0.3);
        let r_in = site.radius_m * st.bound + st.outskirts_m * 0.25;
        let z = Terrace::new(land, si as u16, (site.x, site.y), r_in, r_in + 16.0 * k, st.terrace_m, 0.8 * k);
        // The built-up area decides: a flat town keeps its ground even if its fields slope.
        if z.relief(site.radius_m * st.bound) >= st.terrace_relief_m {
            out.push(z);
        }
    }
    out
}

/// Inside terrace zones, turn tiles beside a drop no one can step up into `Wall`: of two
/// neighbouring tiles whose ground differs by more than `CLIMB_M`, the upper one (where a
/// retaining wall's top stands), or the lower one when the upper is a road, a stair, water,
/// under a building (which blocks anyway) or under a lamp post. Roads, stairs (painted as road) and water are never
/// walled. Planned settlements' drops are walled the same way within `planned` (centre, radius).
/// Returns the tiles walled.
pub(crate) fn paint_drops(land: &mut Land, lots: &[Lot], settlements: &[Settlement], p: &SettleParams, planned: &[(V2, f32)]) -> u32 {
    // (centre, outer radius, climb, planned) of every terrace zone, then of every plan.
    let zones: Vec<(V2, f32, f32, bool)> = land.mods.terr.iter().map(|z| (z.c, z.r_out, CLIMB_M * (z.drop_m / 0.8), false)).chain(planned.iter().map(|&(c, r)| (c, r, CLIMB_M, true))).collect();
    let w = land.size as i32;
    let mut built = std::collections::HashSet::new();
    // Buildings keep their footprint (the tiles `host::hosted_map` walls: the lot less its
    // style's margin), and lamp posts their ground.
    for l in lots.iter().filter(|l| (l.kind.padded() || l.kind == LotKind::Lamp) && zones.iter().any(|z| dist(z.0, l.centre) < z.1 + 30.0)) {
        let set = &settlements[l.settlement as usize];
        let m = if l.kind == LotKind::Lamp || set.planned { 0.0 } else { p.style_for(set.kind, &set.style).map_or(0.0, |st| st.margin_m) };
        let r = Rect { hw: (l.width_m * 0.5 - m).max(0.25), hd: (l.depth_m * 0.5 - m).max(0.25), ..l.rect() };
        let (lo, hi) = r.bbox(0.0);
        for y in lo.1.floor() as i32..=hi.1.ceil() as i32 {
            for x in lo.0.floor() as i32..=hi.0.ceil() as i32 {
                if x >= 0 && y >= 0 && x < w && y < w && r.outside((x as f32 + 0.5, y as f32 + 0.5)) == 0.0 {
                    built.insert((y * w + x) as usize);
                }
            }
        }
    }
    let mut mark: Vec<usize> = Vec::new();
    for &(c, r_out, climb, plan) in &zones {
        let r = r_out.ceil() as i32 + 1;
        let (x0, y0) = ((c.0 as i32 - r).max(0), (c.1 as i32 - r).max(0));
        let (x1, y1) = ((c.0 as i32 + r).min(w - 1), (c.1 as i32 + r).min(w - 1));
        let (nw, nh) = ((x1 - x0 + 1) as usize, (y1 - y0 + 1) as usize);
        let hs: Vec<f32> = (0..nw * nh).map(|k| land.height((x0 + (k % nw) as i32) as f32 + 0.5, (y0 + (k / nw) as i32) as f32 + 0.5)).collect();
        let tile = |i: usize, j: usize| (y0 as usize + j) * w as usize + x0 as usize + i;
        let open = |k: usize| land.map.tiles[k] != Terrain::Road as u8 && land.map.tiles[k] != Terrain::Water as u8 && !built.contains(&k);
        for j in 0..nh {
            for i in 0..nw {
                for (di, dj) in [(1usize, 0usize), (0, 1)] {
                    let (i2, j2) = (i + di, j + dj);
                    if i2 >= nw || j2 >= nh {
                        continue;
                    }
                    let (ha, hb) = (hs[j * nw + i], hs[j2 * nw + i2]);
                    if (ha - hb).abs() <= climb {
                        continue;
                    }
                    let (a, b) = (tile(i, j), tile(i2, j2));
                    // A planned quay or bank meets the water as it stands: the water blocks.
                    if plan && (land.map.tiles[a] == Terrain::Water as u8 || land.map.tiles[b] == Terrain::Water as u8) {
                        continue;
                    }
                    let (up, down) = if ha > hb { (a, b) } else { (b, a) };
                    if open(up) {
                        mark.push(up);
                    } else if open(down) {
                        mark.push(down);
                    }
                }
            }
        }
    }
    let mut n = 0;
    for k in mark {
        if Terrain::from_u8(land.map.tiles[k]).walkable() {
            land.map.tiles[k] = Terrain::Wall as u8;
            n += 1;
        }
    }
    // Walls along drops can seal off a sliver of ground between them, water and rock. Like
    // the land's own small pockets, a sealed pocket inside a zone (not reaching its edge) is
    // closed; one larger than `POCKET_TILES` is left for the tests to find.
    for &(c, r_out, _, _) in &zones {
        let r = r_out.ceil() as i32 + 2;
        let (x0, y0) = ((c.0 as i32 - r).max(0), (c.1 as i32 - r).max(0));
        let (x1, y1) = ((c.0 as i32 + r).min(w - 1), (c.1 as i32 + r).min(w - 1));
        let (nw, nh) = ((x1 - x0 + 1) as usize, (y1 - y0 + 1) as usize);
        let tile = |i: usize, j: usize| (y0 as usize + j) * w as usize + x0 as usize + i;
        let mut seen = vec![false; nw * nh];
        for s in 0..nw * nh {
            if seen[s] || !Terrain::from_u8(land.map.tiles[tile(s % nw, s / nw)]).walkable() {
                continue;
            }
            let (mut stack, mut cells, mut edge) = (vec![s], Vec::new(), false);
            seen[s] = true;
            while let Some(c) = stack.pop() {
                cells.push(c);
                let (i, j) = (c % nw, c / nw);
                edge |= i == 0 || j == 0 || i == nw - 1 || j == nh - 1;
                for (di, dj) in [(-1i32, 0i32), (1, 0), (0, -1), (0, 1)] {
                    let (ii, jj) = (i as i32 + di, j as i32 + dj);
                    if ii < 0 || jj < 0 || ii >= nw as i32 || jj >= nh as i32 {
                        continue;
                    }
                    let q = jj as usize * nw + ii as usize;
                    if !seen[q] && Terrain::from_u8(land.map.tiles[tile(ii as usize, jj as usize)]).walkable() {
                        seen[q] = true;
                        stack.push(q);
                    }
                }
            }
            if !edge && cells.len() < POCKET_TILES {
                for c in cells {
                    land.map.tiles[tile(c % nw, c / nw)] = Terrain::Wall as u8;
                    n += 1;
                }
            }
        }
    }
    n
}

/// Sealed pockets smaller than this (tiles) inside a terrace zone are closed.
const POCKET_TILES: usize = 150;

/// The most a walkable tile's ground may differ from its neighbour's (metres, for a
/// person-sized settlement; scaled with the folk).
pub(crate) const CLIMB_M: f32 = 0.8;

/// Paint stair tiles as road (walkable), before drops are walled.
pub(crate) fn paint_stairs(land: &mut Land, stairs: &[Prop]) {
    let w = land.size as i32;
    for s in stairs {
        let r = s.rect();
        let (lo, hi) = r.bbox(0.0);
        for y in lo.1.floor() as i32..=hi.1.ceil() as i32 {
            for x in lo.0.floor() as i32..=hi.0.ceil() as i32 {
                if x < 0 || y < 0 || x >= w || y >= w || r.outside((x as f32 + 0.5, y as f32 + 0.5)) > 0.0 {
                    continue;
                }
                let k = (y * w + x) as usize;
                if land.map.tiles[k] != Terrain::Water as u8 {
                    land.map.tiles[k] = Terrain::Road as u8;
                }
            }
        }
    }
}
