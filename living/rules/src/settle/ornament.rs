//! Street ornaments: the planner dresses each finished settlement with small props where they
//! make sense (see `docs/FIRST_WORLD.md`, ornaments). Every rule is a field of [`Ornaments`];
//! models and their footprints come from `data/buildings.json` (`buildings.py` prop kinds).
//!
//! Placement keeps out of the way: no prop stands on a street's carriageway, across a door or
//! the path from a door to its street, on a stair or its landings, across a terrace's drop or
//! in a building's footprint. Props that block ([`PropKind::blocks`]) stand only in the plaza or
//! beside buildings, never in a lane.
//!
//! Retaining walls are placed here too: along every drop between terraces, and round a square
//! cut into the slope, wherever the finished ground actually drops.

use super::*;

/// How a spot may be used.
#[derive(Clone, Copy, Default)]
struct Spot {
    /// The prop belongs to this garden and may stand in it.
    garden: Option<u32>,
    /// The prop stands in the settlement's plaza.
    plaza: bool,
    /// Kerbs: on a street's edge, and across door paths.
    kerb: bool,
    /// Overhead (cables, washing lines between houses): only spacing matters.
    overhead: bool,
    /// Most the ground may vary under the footprint.
    flat: f32,
}

pub(crate) fn dress(land: &Land, p: &SettleParams, stairs: Vec<Prop>) -> Vec<Prop> {
    let mut d = Dress::new(land, p);
    for s in stairs {
        d.push(s);
    }
    for idx in 0..land.settlements.len() as u16 {
        d.settlement(idx);
    }
    d.props
}

struct Dress<'a> {
    land: &'a Land,
    p: &'a SettleParams,
    props: Vec<Prop>,
    prop_b: Buckets,
    lot_b: Buckets,
    road_b: Buckets,
    /// Building doors and a point on the way to their street.
    doors: Vec<(V2, V2)>,
    door_b: Buckets,
    near: Vec<u32>,
}

impl<'a> Dress<'a> {
    fn new(land: &'a Land, p: &'a SettleParams) -> Self {
        let s = land.size as f32;
        let mut lot_b = Buckets::new(s, 32.0);
        let mut doors = Vec::new();
        let mut door_b = Buckets::new(s, 32.0);
        for (i, l) in land.lots.iter().enumerate() {
            let (lo, hi) = l.rect().bbox(0.0);
            lot_b.insert(lo, hi, i as u32);
            if l.kind.padded() && l.kind != LotKind::Well && l.kind != LotKind::Tower {
                let door = add(l.centre, mul(l.front, l.depth_m * 0.5 + 0.5));
                let way = add(door, mul(l.front, 2.0 * land.settlements[l.settlement as usize].scale.max(0.4)));
                door_b.insert((door.0.min(way.0) - 1.0, door.1.min(way.1) - 1.0), (door.0.max(way.0) + 1.0, door.1.max(way.1) + 1.0), doors.len() as u32);
                doors.push((door, way));
            }
        }
        let mut road_b = Buckets::new(s, 32.0);
        for (ri, r) in land.roads.iter().enumerate() {
            for i in 0..r.points.len().saturating_sub(1) {
                let (a, b) = (r.points[i], r.points[i + 1]);
                let pad = r.width_m * 0.5 + 1.0;
                road_b.insert((a.0.min(b.0) - pad, a.1.min(b.1) - pad), (a.0.max(b.0) + pad, a.1.max(b.1) + pad), ri as u32);
            }
        }
        Self { land, p, props: Vec::new(), prop_b: Buckets::new(s, 16.0), lot_b, road_b, doors, door_b, near: Vec::new() }
    }

    fn push(&mut self, pr: Prop) {
        let (lo, hi) = pr.rect().bbox(0.0);
        self.prop_b.insert(lo, hi, self.props.len() as u32);
        self.props.push(pr);
    }

    /// Models of a prop kind in a style, those passing `ok`.
    fn models(&self, style: &str, kind: PropKind, ok: &dyn Fn(&ModelFootprint) -> bool) -> Vec<u32> {
        let id = kind.id();
        (0..self.p.buildings.models.len() as u32).filter(|&i| {
            let m = &self.p.buildings.models[i as usize];
            m.style == style && m.kind == id && ok(m)
        })
        .collect()
    }

    /// A prop of the style's models (one passing `ok`), centred at `c`, facing `front`, if the
    /// spot allows it.
    #[allow(clippy::too_many_arguments)]
    fn put(&mut self, idx: u16, kind: PropKind, c: V2, front: V2, rng: &mut Rng, spot: Spot, ok: &dyn Fn(&ModelFootprint) -> bool) -> bool {
        let style = &self.land.settlements[idx as usize].style;
        let ms = self.models(style, kind, ok);
        if ms.is_empty() {
            return false;
        }
        let m = &self.p.buildings.models[ms[((rng.f() * ms.len() as f32) as usize).min(ms.len() - 1)] as usize];
        let front = norm(front);
        let pr = Prop { settlement: idx, kind, centre: c, width_m: m.width_m, depth_m: m.depth_m, front, yaw: yaw_of(front), floor_m: 0.0, model_file: Some(m.file.clone()), height_m: m.height_m };
        match self.fits(&pr, spot) {
            Some(floor) => {
                self.push(Prop { floor_m: floor, ..pr });
                true
            }
            None => false,
        }
    }

    /// Whether a prop fits; its floor (the lowest ground under it) if so.
    fn fits(&mut self, pr: &Prop, spot: Spot) -> Option<f32> {
        let land = self.land;
        // A tree takes room at its trunk; its crown overhangs.
        let r = pr.base();
        let k = land.settlements[pr.settlement as usize].scale.max(0.3);
        // Signs and flower boxes stand against a wall, in the lot's margin.
        let attached = matches!(pr.kind, PropKind::Sign | PropKind::NeonSign | PropKind::FlowerBox);
        let chain = |a: PropKind| matches!(a, PropKind::Kerb | PropKind::Fence | PropKind::Gate);
        let (lo, hi) = r.bbox(1.0);
        if lo.0 < 1.0 || lo.1 < 1.0 || hi.0 > land.size as f32 - 1.0 || hi.1 > land.size as f32 - 1.0 {
            return None;
        }
        // Dry, walkable, even ground (not across a drop).
        let mut pts: Vec<V2> = r.corners().to_vec();
        pts.push(r.c);
        let (mut hmin, mut hmax) = (f32::MAX, f32::MIN);
        for q in &pts {
            let t = land.map.at(q.0, q.1);
            if !t.walkable() || land.sd_at(q.0, q.1) < 0.8 {
                return None;
            }
            let h = land.height(q.0, q.1);
            hmin = hmin.min(h);
            hmax = hmax.max(h);
        }
        if hmax - hmin > spot.flat.max(0.35 * k) {
            return None;
        }
        // Clear of other props (and stairs' landings).
        let mut near = std::mem::take(&mut self.near);
        self.prop_b.query(lo, hi, &mut near);
        for &j in &near {
            let o = &self.props[j as usize];
            let mut orr = o.rect();
            if o.kind == PropKind::Stairs {
                orr.hd += 1.0 * k;
            }
            // Kerbs, fences and gates run on from one another.
            let both_kerbs = chain(o.kind) && chain(pr.kind);
            let overhead = spot.overhead || matches!(o.kind, PropKind::Cable) || (o.kind == PropKind::WashingLine && o.height_m > 2.6 * k);
            if o.kind == PropKind::Tree {
                orr = o.base();
            }
            if !both_kerbs && !overhead && r.gap(&orr) < 0.15 * k {
                self.near = near;
                return None;
            }
            if overhead && o.kind == pr.kind && r.gap(&orr) < 2.0 * k {
                self.near = near;
                return None;
            }
        }
        if !spot.overhead {
            // Off the carriageways (kerbs on their edge).
            self.road_b.query(lo, hi, &mut near);
            for &ri in &near {
                let rd = &land.roads[ri as usize];
                let need = rd.width_m * 0.5 + if spot.kerb { 0.0 } else { 0.15 * k };
                for i in 0..rd.points.len() - 1 {
                    if r.seg_dist(rd.points[i], rd.points[i + 1]) < need - 1e-3 {
                        self.near = near;
                        return None;
                    }
                }
            }
            // Out of buildings, and of gardens and fields that are not its own.
            self.lot_b.query(lo, hi, &mut near);
            for &li in &near {
                let l = &land.lots[li as usize];
                let gap = r.gap(&l.rect());
                let ok = match l.kind {
                    LotKind::Garden => spot.garden == Some(li) || gap >= 0.05,
                    LotKind::Lamp => spot.kerb || gap >= 0.2 * k,
                    LotKind::Field => gap >= 0.02,
                    // Against the wall: clear of the model's own footprint (the lot less its margin).
                    _ if attached => {
                        let set = &land.settlements[l.settlement as usize];
                        let m = self.p.style_for(set.kind, &set.style).map_or(0.0, |st| st.margin_m);
                        r.gap(&Rect { hw: l.width_m * 0.5 - m, hd: l.depth_m * 0.5 - m, ..l.rect() }) >= 0.02
                    }
                    _ if pr.kind == PropKind::Tree => gap >= 0.6 * k,
                    _ => gap >= 0.02,
                };
                if !ok {
                    self.near = near;
                    return None;
                }
            }
            // Clear of doors and the way out of them.
            if !spot.kerb {
                self.door_b.query(lo, hi, &mut near);
                for &di in &near {
                    let (door, way) = self.doors[di as usize];
                    if r.outside(door) < 0.9 * k || r.seg_dist(door, way) < 0.5 * k {
                        self.near = near;
                        return None;
                    }
                }
            }
            // In the plaza only when meant to be, and clear of town walls.
            let set = &land.settlements[pr.settlement as usize];
            let in_plaza = |q: V2| poly_contains(&set.plaza.points, q);
            let inside = pts.iter().filter(|q| in_plaza(**q)).count();
            if spot.plaza && inside != pts.len() || !spot.plaza && !spot.kerb && inside > 0 {
                self.near = near;
                return None;
            }
            for s in &land.settlements {
                if let Some(w) = &s.wall {
                    let m = w.ring.len();
                    if dist(s.centre, r.c) < s.radius_m + 40.0 && (0..m).any(|i| r.seg_dist(w.ring[i], w.ring[(i + 1) % m]) < w.thickness_m * 0.5 + 0.8) {
                        self.near = near;
                        return None;
                    }
                }
            }
        }
        self.near = near;
        Some(hmin)
    }

    fn settlement(&mut self, idx: u16) {
        let land = self.land;
        let set = &land.settlements[idx as usize];
        let Some(st) = self.p.style_for(set.kind, &set.style) else { return };
        let o = st.ornaments.clone();
        let k = set.scale.max(0.3);
        let flat = Spot { flat: 0.35 * k, ..Spot::default() };
        let mut rng = Rng(land.seed ^ 0x0E7A ^ (idx as u64) << 8);
        let lots = set.lots.0..set.lots.1;
        let centre = set.centre;
        let plaza = set.plaza.points.clone();
        let axis = norm(sub(plaza[0], centre));
        let cyber = set.style == "cyberpunk";
        // Where streets meet the plaza: (point on its edge, direction into it, half width).
        let exits: Vec<(V2, V2, f32)> = land
            .roads
            .iter()
            .filter_map(|r| {
                let n = r.points.len();
                if r.ends[1] == RoadEnd::Plaza(idx) {
                    Some((r.points[n - 1], norm(sub(r.points[n - 1], r.points[n - 2])), r.width_m * 0.5))
                } else if r.ends[0] == RoadEnd::Plaza(idx) {
                    Some((r.points[0], norm(sub(r.points[0], r.points[1])), r.width_m * 0.5))
                } else {
                    None
                }
            })
            .collect();
        let near_exit = |q: V2, extra: f32| exits.iter().any(|e| dist(e.0, q) < e.2 + extra);
        let any = |_: &ModelFootprint| true;

        // 1. Retaining walls along the terraces' drops and round a square cut into the slope.
        if set.terrace_m > 0.0 {
            if let Some(z) = land.mods.terr.iter().find(|z| z.site == set.site) {
                for (_, line) in z.risers(land) {
                    self.wall_along(idx, &line, None, &mut rng);
                }
            }
            // The plaza's drop lies in the middle of its skirt, outside its edge.
            let mut ring = plaza.clone();
            ring.push(plaza[0]);
            self.wall_along(idx, &ring, Some((centre, (st.skirt_m * 2.0).max(1.0) * 0.5)), &mut rng);
        }
        // 2. Kerbs along paved main streets and round a paved square.
        if o.kerbs {
            let kerb = Spot { kerb: true, flat: 0.5 * k, ..Spot::default() };
            for (ri, rd) in land.roads.iter().enumerate() {
                let mine = rd.settlement == Some(idx) || rd.ends.contains(&RoadEnd::Plaza(idx));
                if !mine || rd.class != RoadClass::Street {
                    continue;
                }
                let _ = ri;
                let (pts, hw) = (rd.points.clone(), rd.width_m * 0.5);
                let cl = cumlen(&pts);
                let total = *cl.last().unwrap();
                for side in [1.0f32, -1.0] {
                    let mut s = 0.5;
                    while s < total - 0.5 {
                        let (q, t) = at_s(&pts, &cl, s + 2.0 * k);
                        let n = mul(perp(t), side);
                        let c = add(q, mul(n, hw + 0.16 * k));
                        if dist(c, centre) > set.radius_m * 1.1 {
                            s += 4.0 * k;
                            continue;
                        }
                        self.put(idx, PropKind::Kerb, c, mul(n, -1.0), &mut rng, kerb, &any);
                        s += 4.0 * k;
                    }
                }
            }
            if set.plaza.paved {
                let mut ring = plaza.clone();
                ring.push(plaza[0]);
                let cl = cumlen(&ring);
                let total = *cl.last().unwrap();
                let mut s = 0.0;
                while s < total - 2.0 * k {
                    let (q, t) = at_s(&ring, &cl, s + 2.0 * k);
                    let mut n = perp(t);
                    if dot(n, sub(centre, q)) < 0.0 {
                        n = mul(n, -1.0);
                    }
                    if !near_exit(q, 1.5 * k) {
                        self.put(idx, PropKind::Kerb, add(q, mul(n, 0.2 * k)), n, &mut rng, Spot { plaza: true, ..kerb }, &any);
                    }
                    s += 4.0 * k;
                }
            }
        }
        // 3. The plaza's centrepiece: a fountain or a market cross.
        if let Some(cp) = o.centrepiece {
            let len_m = st.plaza_m[0];
            let offs = [(0.0, 0.0), (0.22, 0.0), (-0.22, 0.0), (0.36, 0.0), (-0.36, 0.0), (0.0, 0.25), (0.0, -0.25), (0.3, 0.25), (-0.3, -0.25)];
            for (a, b) in offs {
                let c = add(add(centre, mul(axis, a * len_m)), mul(perp(axis), b * st.plaza_m[1]));
                if self.put(idx, cp, c, perp(axis), &mut rng, Spot { plaza: true, flat: 0.3 * k, ..Spot::default() }, &any) {
                    break;
                }
            }
        }
        // 4. Banners where streets enter the plaza and inside the town's gates; signposts.
        for &(e, dir, hw) in &exits {
            if o.banners {
                for side in [1.0f32, -1.0] {
                    let c = add(add(e, mul(dir, 1.4 * k)), mul(perp(dir), side * (hw + 1.2 * k)));
                    self.put(idx, PropKind::Banner, c, dir, &mut rng, Spot { plaza: true, flat: 0.4 * k, ..Spot::default() }, &any);
                }
            }
            if o.signs {
                let kind = if cyber { PropKind::NeonSign } else { PropKind::Sign };
                for side in [1.0f32, -1.0] {
                    let c = add(sub(e, mul(dir, 3.0 * k)), mul(perp(dir), side * (hw + 0.9 * k)));
                    if self.put(idx, kind, c, mul(perp(dir), -side), &mut rng, flat, &|m: &ModelFootprint| m.form != "shop") {
                        break;
                    }
                }
            }
        }
        if o.banners {
            if let Some(w) = &set.wall {
                for g in &w.gates {
                    let along = perp(g.out);
                    for side in [1.0f32, -1.0] {
                        let c = add(sub(g.at, mul(g.out, w.thickness_m * 0.5 + 1.8 * k)), mul(along, side * (g.width_m * 0.5 + 1.0 * k)));
                        self.put(idx, PropKind::Banner, c, mul(g.out, -1.0), &mut rng, flat, &any);
                    }
                }
            }
        }
        // 5. Benches round the plaza, facing in; trees on it.
        if o.bench_m > 0.0 {
            let mut ring = plaza.clone();
            ring.push(plaza[0]);
            let cl = cumlen(&ring);
            let total = *cl.last().unwrap();
            let mut s = o.bench_m * 0.5;
            while s < total {
                let q = at_s(&ring, &cl, s).0;
                let n = norm(sub(centre, q));
                if !near_exit(q, 3.5 * k) {
                    for inset in [1.6f32, 2.6] {
                        if self.put(idx, PropKind::Bench, add(q, mul(n, inset * k)), n, &mut rng, Spot { plaza: true, ..flat }, &any) {
                            break;
                        }
                    }
                }
                s += o.bench_m;
            }
        }
        if o.plaza_trees > 0 {
            let form = if set.plaza.paved { "street" } else { "garden" };
            let mut placed = 0;
            let m = plaza.len();
            let mut order: Vec<usize> = (0..m).collect();
            // Farthest from the streets first.
            order.sort_by(|&a, &b| {
                let da = exits.iter().map(|e| dist(e.0, plaza[a])).fold(f32::MAX, f32::min);
                let db = exits.iter().map(|e| dist(e.0, plaza[b])).fold(f32::MAX, f32::min);
                db.total_cmp(&da).then(a.cmp(&b))
            });
            for i in order {
                if placed >= o.plaza_trees {
                    break;
                }
                let q = plaza[i];
                let c = add(q, mul(norm(sub(centre, q)), 4.5 * k));
                if self.put(idx, PropKind::Tree, c, norm(sub(centre, q)), &mut rng, Spot { plaza: true, ..flat }, &|mf: &ModelFootprint| mf.form == form) {
                    placed += 1;
                }
            }
        }
        // 6. The neon street: billboards round the plaza, then signs, stalls and cables.
        if o.billboards > 0 {
            let mut placed = 0;
            for i in 0..plaza.len() {
                if placed >= o.billboards {
                    break;
                }
                let q = plaza[(i * 3 + 1) % plaza.len()];
                let n = norm(sub(centre, q));
                if !near_exit(q, 4.0 * k) && self.put(idx, PropKind::Billboard, add(q, mul(n, 2.0 * k)), n, &mut rng, Spot { plaza: true, ..flat }, &any) {
                    placed += 1;
                }
            }
        }
        if o.neon_street {
            self.neon_street(idx, &o, &mut rng);
        }
        // 7. Inns, workshops, barns and stalls: clutter, signs and pipes.
        for li in lots.clone() {
            let l = land.lots[li as usize].clone();
            let u = perp(l.front);
            let front_mid = add(l.centre, mul(l.front, l.depth_m * 0.5));
            let clutter = |rng: &mut Rng| match rng.f() {
                x if x < 0.45 => PropKind::Barrel,
                x if x < 0.85 => PropKind::Crate,
                _ => PropKind::Cart,
            };
            match l.kind {
                LotKind::Inn | LotKind::Workshop | LotKind::Barn => {
                    if o.signs && l.kind != LotKind::Barn {
                        let kind = if cyber { PropKind::NeonSign } else { PropKind::Sign };
                        for side in [1.0f32, -1.0] {
                            let a = (l.width_m * 0.5 - 0.7 * k).min(2.4 * k).max(1.3 * k);
                            let c = add(add(front_mid, mul(u, side * a)), mul(l.front, 0.45 * k));
                            if self.put(idx, kind, c, l.front, &mut rng, flat, &|m: &ModelFootprint| m.form != "post") {
                                break;
                            }
                        }
                    }
                    let n_clutter = if l.kind == LotKind::Inn { 3 } else { 2 };
                    for j in 0..n_clutter {
                        if rng.f() > o.clutter {
                            continue;
                        }
                        let kind = clutter(&mut rng);
                        let side = if j % 2 == 0 { -1.0f32 } else { 1.0 };
                        // Beside the building's front corner, then along its side.
                        let spots = [
                            add(add(front_mid, mul(u, side * (l.width_m * 0.5 - 0.6 * k))), mul(l.front, 0.6 * k)),
                            add(add(l.centre, mul(u, side * (l.width_m * 0.5 + 1.0 * k))), mul(l.front, l.depth_m * 0.3)),
                            add(add(l.centre, mul(u, side * (l.width_m * 0.5 + 1.0 * k))), mul(l.front, -l.depth_m * 0.1)),
                        ];
                        for c in spots {
                            if self.put(idx, kind, c, l.front, &mut rng, flat, &any) {
                                break;
                            }
                        }
                    }
                    if l.kind == LotKind::Inn {
                        for side in [1.0f32, -1.0] {
                            let c = add(add(front_mid, mul(u, side * l.width_m * 0.3)), mul(l.front, 0.55 * k));
                            if self.put(idx, PropKind::Bench, c, l.front, &mut rng, flat, &any) {
                                break;
                            }
                        }
                    }
                    if o.pipes && matches!(l.kind, LotKind::Workshop | LotKind::Barn) {
                        for side in [1.0f32, -1.0] {
                            let c = add(l.centre, mul(u, side * (l.width_m * 0.5 + 0.6 * k)));
                            if self.put(idx, PropKind::Pipe, c, mul(u, side), &mut rng, flat, &any) {
                                break;
                            }
                        }
                    }
                }
                LotKind::MarketStall => {
                    if rng.f() < o.clutter {
                        let kind = clutter(&mut rng);
                        let c = sub(l.centre, mul(l.front, l.depth_m * 0.5 + 0.7 * k));
                        self.put(idx, kind, c, l.front, &mut rng, Spot { plaza: true, ..flat }, &|m: &ModelFootprint| m.form != "wagon");
                    }
                }
                LotKind::House | LotKind::Townhouse => {
                    let door_clear = 1.1 * k;
                    if rng.f() < o.flower_box && l.width_m > 3.0 * k {
                        let side = if rng.f() < 0.5 { 1.0f32 } else { -1.0 };
                        let a = (l.width_m * 0.3).max(door_clear + 0.7 * k).min(l.width_m * 0.5 - 0.6 * k);
                        let c = add(add(front_mid, mul(u, side * a)), mul(l.front, 0.25 * k));
                        self.put(idx, PropKind::FlowerBox, c, l.front, &mut rng, flat, &any);
                    }
                    if rng.f() < o.planter {
                        let side = if rng.f() < 0.5 { 1.0f32 } else { -1.0 };
                        let c = add(add(front_mid, mul(u, side * (l.width_m * 0.5 - 0.45 * k))), mul(l.front, 0.5 * k));
                        self.put(idx, PropKind::Planter, c, l.front, &mut rng, flat, &any);
                    }
                    if rng.f() < o.clutter * 0.2 {
                        // A rain barrel by a back corner.
                        let side = if rng.f() < 0.5 { 1.0f32 } else { -1.0 };
                        let c = add(add(l.centre, mul(u, side * (l.width_m * 0.5 + 0.55 * k))), mul(l.front, -l.depth_m * 0.3));
                        self.put(idx, PropKind::Barrel, c, u, &mut rng, flat, &|m: &ModelFootprint| m.form == "single");
                    }
                }
                LotKind::Garden => self.garden(idx, li, &o, &mut rng),
                _ => {}
            }
        }
        // 8. Washing lines across gaps between neighbouring houses.
        if o.washing_gap > 0.0 {
            for li in lots.clone() {
                let l = &land.lots[li as usize];
                if !matches!(l.kind, LotKind::House | LotKind::Townhouse) {
                    continue;
                }
                let (lo, hi) = l.rect().bbox(6.0 * k);
                let mut near = Vec::new();
                self.lot_b.query(lo, hi, &mut near);
                for &j in &near {
                    let m = &land.lots[j as usize];
                    if j <= li || m.settlement != idx || !matches!(m.kind, LotKind::House | LotKind::Townhouse) || dot(m.front, l.front) < 0.95 || m.frontage != l.frontage {
                        continue;
                    }
                    let u = perp(l.front);
                    let off = dot(sub(m.centre, l.centre), u);
                    let gap = off.abs() - (l.width_m + m.width_m) * 0.5;
                    if !(1.6 * k..=6.0 * k).contains(&gap) || dot(sub(m.centre, l.centre), l.front).abs() > 2.0 * k || rng.f() > o.washing_gap {
                        continue;
                    }
                    let mid = add(l.centre, mul(u, off.signum() * (l.width_m * 0.5 + gap * 0.5)));
                    let c = add(mid, mul(l.front, l.depth_m * 0.15));
                    let need = gap + 0.2 * k;
                    let widest = self.models(&set.style, PropKind::WashingLine, &|mf: &ModelFootprint| mf.form.starts_with("span") && mf.width_m >= need).into_iter().map(|i| self.p.buildings.models[i as usize].width_m).fold(f32::MAX, f32::min);
                    if widest < f32::MAX {
                        self.put(idx, PropKind::WashingLine, c, l.front, &mut rng, Spot { overhead: true, flat: 9.0, ..Spot::default() }, &|mf: &ModelFootprint| mf.form.starts_with("span") && (mf.width_m - widest).abs() < 0.01);
                    }
                }
            }
        }
        // 9. Trees along the main streets.
        if o.street_tree_m > 0.0 {
            for rd in land.roads.iter().filter(|r| r.settlement == Some(idx) && r.class == RoadClass::Street) {
                let (pts, hw) = (rd.points.clone(), rd.width_m * 0.5);
                let cl = cumlen(&pts);
                let total = *cl.last().unwrap();
                let mut s = o.street_tree_m * 0.5;
                let mut side = 1.0f32;
                while s < total {
                    for shift in [0.0f32, 2.0, -2.0, 4.0] {
                        let (q, t) = at_s(&pts, &cl, (s + shift * k).clamp(0.0, total));
                        let n = mul(perp(t), side);
                        if self.put(idx, PropKind::Tree, add(q, mul(n, hw + 0.9 * k)), mul(n, -1.0), &mut rng, flat, &|m: &ModelFootprint| m.form == "street") {
                            break;
                        }
                    }
                    side = -side;
                    s += o.street_tree_m;
                }
            }
        }
    }

    /// A fenced garden with a gate at the back, a tree and a washing line.
    fn garden(&mut self, idx: u16, li: u32, o: &Ornaments, rng: &mut Rng) {
        let land = self.land;
        let g = land.lots[li as usize].clone();
        let k = land.settlements[idx as usize].scale.max(0.3);
        let own = Spot { garden: Some(li), flat: 0.5 * k, ..Spot::default() };
        if o.fences {
            // Front left, front right, back right, back left; the front faces the house.
            let cs = g.corners();
            let inset = 0.12 * k;
            let gc = g.centre;
            for (si, (a, b)) in [(cs[1], cs[2]), (cs[2], cs[3]), (cs[3], cs[0])].into_iter().enumerate() {
                let a = add(a, mul(norm(sub(gc, a)), inset));
                let b = add(b, mul(norm(sub(gc, b)), inset));
                let l = dist(a, b);
                let fences = self.models(&land.settlements[idx as usize].style, PropKind::Fence, &|_| true);
                let Some(longest) = fences.iter().map(|&i| self.p.buildings.models[i as usize].width_m).reduce(f32::max) else { return };
                let n = (l / longest).ceil().max(1.0) as usize;
                let piece = l / n as f32;
                let t = norm(sub(b, a));
                let mut out = perp(t);
                if dot(out, sub(a, gc)) < 0.0 {
                    out = mul(out, -1.0);
                }
                // The gate: in the middle of the back.
                let gate_at = if si == 1 && l > 2.5 * k { Some(n / 2) } else { None };
                for i in 0..n {
                    let c = add(a, mul(t, piece * (i as f32 + 0.5)));
                    if gate_at == Some(i) {
                        let gw = self.models(&land.settlements[idx as usize].style, PropKind::Gate, &|_| true).first().map(|&m| self.p.buildings.models[m as usize].width_m).unwrap_or(piece);
                        self.put(idx, PropKind::Gate, c, out, rng, own, &|_| true);
                        // Fill either side of a narrow gate.
                        let rest = (piece - gw) * 0.5;
                        if rest > 0.5 * k {
                            for s in [-1.0f32, 1.0] {
                                let cc = add(c, mul(t, s * (gw * 0.5 + rest * 0.5)));
                                self.put(idx, PropKind::Fence, cc, out, rng, own, &|m: &ModelFootprint| m.width_m <= rest + 0.05 * k);
                            }
                        }
                        continue;
                    }
                    let best = self.models(&land.settlements[idx as usize].style, PropKind::Fence, &|m: &ModelFootprint| m.width_m <= piece + 0.05 * k).into_iter().map(|i| self.p.buildings.models[i as usize].width_m).reduce(f32::max);
                    if let Some(bw) = best {
                        self.put(idx, PropKind::Fence, c, out, rng, own, &|m: &ModelFootprint| (m.width_m - bw).abs() < 0.01);
                    }
                }
            }
        }
        if rng.f() < o.garden_tree {
            let c = add(g.centre, mul(g.front, -g.depth_m * 0.18));
            let u = perp(g.front);
            for a in [0.0f32, 0.25, -0.25] {
                if self.put(idx, PropKind::Tree, add(c, mul(u, a * g.width_m)), g.front, rng, own, &|m: &ModelFootprint| m.form == "garden") {
                    break;
                }
            }
        }
        if rng.f() < o.washing {
            let c = add(g.centre, mul(g.front, g.depth_m * 0.2));
            let w = g.width_m - 0.8 * k;
            self.put(idx, PropKind::WashingLine, c, g.front, rng, own, &|m: &ModelFootprint| m.form == "posts" && m.width_m <= w);
        }
    }

    /// Retaining-wall pieces along a line wherever the finished ground drops across it;
    /// `outward` moves them that far away from a centre (a plaza's edge to its drop).
    fn wall_along(&mut self, idx: u16, line: &[V2], outward: Option<(V2, f32)>, rng: &mut Rng) {
        let land = self.land;
        let set = &land.settlements[idx as usize];
        let k = set.scale.max(0.3);
        let step = set.terrace_m.max(1.0);
        let style = set.style.clone();
        let walls = self.models(&style, PropKind::RetainingWall, &|_| true);
        if walls.is_empty() || line.len() < 2 {
            return;
        }
        let piece = self.p.buildings.models[walls[0] as usize].width_m;
        let cl = cumlen(line);
        let total = *cl.last().unwrap();
        let n = (total / piece).floor() as usize;
        for i in 0..n {
            let (c, t) = at_s(line, &cl, (i as f32 + 0.5) * piece);
            let nrm = perp(t);
            let c = match outward {
                Some((oc, shift)) => {
                    let out = if dot(nrm, sub(c, oc)) > 0.0 { nrm } else { mul(nrm, -1.0) };
                    add(c, mul(out, shift))
                }
                None => c,
            };
            let (a, b) = (add(c, mul(nrm, 1.3 * k)), sub(c, mul(nrm, 1.3 * k)));
            let (ha, hb) = (land.height(a.0, a.1), land.height(b.0, b.1));
            let drop = (ha - hb).abs();
            if drop < 0.45 * step {
                continue;
            }
            // Face the lower side.
            let front = if ha < hb { nrm } else { mul(nrm, -1.0) };
            let floor = ha.min(hb);
            let high = drop > step * 0.72;
            let ms: Vec<u32> = walls.iter().copied().filter(|&m| (self.p.buildings.models[m as usize].form == "high") == high).collect();
            let ms = if ms.is_empty() { walls.clone() } else { ms };
            let m = &self.p.buildings.models[ms[((rng.f() * ms.len() as f32) as usize).min(ms.len() - 1)] as usize];
            let pr = Prop { settlement: idx, kind: PropKind::RetainingWall, centre: c, width_m: m.width_m, depth_m: m.depth_m, front, yaw: yaw_of(front), floor_m: floor, model_file: Some(m.file.clone()), height_m: m.height_m };
            if self.wall_fits(&pr) {
                self.push(pr);
            }
        }
    }

    /// A retaining wall fits off the carriageways, out of buildings, stairs and water.
    fn wall_fits(&mut self, pr: &Prop) -> bool {
        let land = self.land;
        let r = pr.rect();
        let k = land.settlements[pr.settlement as usize].scale.max(0.3);
        let (lo, hi) = r.bbox(0.5);
        if lo.0 < 1.0 || lo.1 < 1.0 || hi.0 > land.size as f32 - 1.0 || hi.1 > land.size as f32 - 1.0 {
            return false;
        }
        if r.corners().iter().any(|q| land.sd_at(q.0, q.1) < 1.0) {
            return false;
        }
        let mut near = std::mem::take(&mut self.near);
        let mut ok = true;
        self.road_b.query(lo, hi, &mut near);
        'roads: for &ri in &near {
            let rd = &land.roads[ri as usize];
            for i in 0..rd.points.len() - 1 {
                if r.seg_dist(rd.points[i], rd.points[i + 1]) < rd.width_m * 0.5 + 0.1 * k {
                    ok = false;
                    break 'roads;
                }
            }
        }
        if ok {
            self.lot_b.query(lo, hi, &mut near);
            ok = near.iter().all(|&li| {
                let l = &land.lots[li as usize];
                matches!(l.kind, LotKind::Garden | LotKind::Field) || r.gap(&l.rect()) >= 0.02
            });
        }
        if ok {
            self.prop_b.query(lo, hi, &mut near);
            ok = near.iter().all(|&j| {
                let o = &self.props[j as usize];
                o.kind != PropKind::Stairs && o.kind != PropKind::RetainingWall || r.gap(&o.rect()) >= 0.05
            });
        }
        self.near = near;
        ok
    }

    /// Signs, kiosks and food stalls along the main street with the most buildings, and cables
    /// strung across it.
    fn neon_street(&mut self, idx: u16, o: &Ornaments, rng: &mut Rng) {
        let land = self.land;
        let set = &land.settlements[idx as usize];
        let k = set.scale.max(0.3);
        let flat = Spot { flat: 0.35 * k, ..Spot::default() };
        let mut best: Option<(usize, u32)> = None;
        for (ri, rd) in land.roads.iter().enumerate() {
            if rd.settlement != Some(idx) || rd.class != RoadClass::Street {
                continue;
            }
            let n = land.lots[set.lots.0 as usize..set.lots.1 as usize].iter().filter(|l| l.frontage == Frontage::Road(ri as u32) && l.kind.padded()).count();
            if best.is_none_or(|b| n > b.0) {
                best = Some((n, ri as u32));
            }
        }
        let Some((_, rid)) = best else { return };
        let rd = &land.roads[rid as usize];
        let (pts, hw) = (rd.points.clone(), rd.width_m * 0.5);
        let cl = cumlen(&pts);
        let total = *cl.last().unwrap();
        // Signs and stalls wherever the frontage leaves room, alternating sides.
        let mut s = 2.0 * k;
        let mut i = 0u32;
        while s < total {
            let (q, t) = at_s(&pts, &cl, s);
            for side in [1.0f32, -1.0] {
                let n = mul(perp(t), side);
                let kind = match (i + side as u32) % 3 {
                    0 => PropKind::NeonSign,
                    1 => PropKind::Kiosk,
                    _ => PropKind::FoodStall,
                };
                let depth = if kind == PropKind::NeonSign { 0.5 } else { 1.3 };
                self.put(idx, kind, add(q, mul(n, hw + (0.25 + depth) * k)), mul(n, -1.0), rng, flat, &|_| true);
            }
            i += 1;
            s += 4.0 * k;
        }
        // Cables between the buildings either side.
        if o.cable_m > 0.0 {
            let mut s = o.cable_m * 0.5;
            while s < total {
                let (q, t) = at_s(&pts, &cl, s);
                let n = perp(t);
                let both = [1.0f32, -1.0].iter().all(|&side| {
                    let probe = add(q, mul(n, side * (hw + 3.0 * k)));
                    let mut near = Vec::new();
                    self.lot_b.query((probe.0 - 4.0, probe.1 - 4.0), (probe.0 + 4.0, probe.1 + 4.0), &mut near);
                    near.iter().any(|&li| land.lots[li as usize].kind.padded() && land.lots[li as usize].rect().outside(probe) < 2.5 * k)
                });
                if both {
                    self.put(idx, PropKind::Cable, q, n, rng, Spot { overhead: true, flat: 9.0, ..Spot::default() }, &|_| true);
                }
                s += o.cable_m;
            }
        }
    }
}
