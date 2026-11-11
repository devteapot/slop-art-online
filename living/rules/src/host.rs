//! What the authority hosts from a generated [`Land`] (see `docs/ISLAND_AUTHORITY.md`), shared
//! with clients so both derive the same things from the same seed:
//! - which tiles buildings block ([`hosted_map`]), since a lot's model stands on its footprint,
//!   and which tiles the props that stand in the way block (fountains, carts, kiosks...);
//! - where each building's door is ([`door`]), the walkable point in front of its lot;
//! - where newcomers arrive ([`arrival`]): on the first town's square, where people are;
//! - digests of the tiles, the ground height and the layout ([`Digests`]), so a client that
//!   regenerates the land can prove it matches the authority's before it trusts its heights.

use crate::det::{fnv1a, FNV_OFFSET};
use crate::land::{Land, LandParams, SiteKind};
use crate::map::{Map, Terrain};
use crate::settle::{Lot, LotKind, ModelFootprint, Prop, Settlement};

/// Lots whose model blocks movement: buildings, towers, wells and market stalls. Lamps are
/// posts, and gardens and fields are open ground.
pub fn blocks(kind: LotKind) -> bool {
    kind.padded() || kind == LotKind::MarketStall
}

/// The style margin round a settlement's models (lots are the model's footprint plus this).
pub fn margin_of(land: &Land, p: &LandParams, lot: &Lot) -> f32 {
    // A planned settlement's lots are its models' footprints exactly.
    match land.settlements.get(lot.settlement as usize) {
        Some(s) if s.planned => 0.0,
        s => s.and_then(|s| p.settlements.style_for(s.kind, &s.style)).map_or(0.0, |s| s.margin_m),
    }
}

/// Tiles under a lot's model footprint: tiles whose centre lies inside the lot shrunk by the
/// margin.
pub fn footprint_tiles(lot: &Lot, margin_m: f32) -> Vec<(i32, i32)> {
    rect_tiles(lot.centre, lot.front, (lot.width_m * 0.5 - margin_m).max(0.25), (lot.depth_m * 0.5 - margin_m).max(0.25))
}

/// Tiles under a prop's footprint (tiles whose centre lies inside it).
pub fn prop_tiles(prop: &Prop) -> Vec<(i32, i32)> {
    rect_tiles(prop.centre, prop.front, (prop.width_m * 0.5).max(0.25), (prop.depth_m * 0.5).max(0.25))
}

pub(crate) fn rect_tiles(centre: (f32, f32), front: (f32, f32), hw: f32, hd: f32) -> Vec<(i32, i32)> {
    let (fx, fy) = front;
    let (ux, uy) = (-fy, fx);
    let r = (hw * hw + hd * hd).sqrt().ceil() as i32 + 1;
    let (cx, cy) = (centre.0.floor() as i32, centre.1.floor() as i32);
    let mut out = Vec::new();
    for j in cy - r..=cy + r {
        for i in cx - r..=cx + r {
            let (dx, dy) = (i as f32 + 0.5 - centre.0, j as f32 + 0.5 - centre.1);
            let (a, b) = (dx * ux + dy * uy, dx * fx + dy * fy);
            if a.abs() <= hw && b.abs() <= hd {
                out.push((i, j));
            }
        }
    }
    out
}

/// The point in front of a building, half a metre beyond its lot on the side it faces.
pub fn door(lot: &Lot) -> (f32, f32) {
    let k = lot.depth_m * 0.5 + 0.5;
    (lot.centre.0 + lot.front.0 * k, lot.centre.1 + lot.front.1 * k)
}

/// What [`hosted_map`] changed.
#[derive(Clone, Debug, Default)]
pub struct Hosted {
    /// Tiles turned into `Wall` or `Low` under building footprints and the props that block
    /// (walkable ground, or a drop's edge).
    pub blocked_tiles: u32,
    /// Walkable tiles that buildings cut off from the main walkable area (enclosed yards); they
    /// stay as they are, but nothing is placed there.
    pub cut_off_tiles: u32,
    /// Per tile: in the main walkable area (row-major, like `Map::tiles`).
    pub reachable: Vec<bool>,
}

/// What a tile under something that blocks walking becomes: `Wall` under a thing that hides
/// (`tall`), `Low` under one below the eye. Open ground (`open`: walkable, and not a road the
/// thing must leave alone) is covered; a drop's edge only by a thing that hides; a `Low` tile by
/// a taller thing over it. Walls, rock and water stay.
fn blocking(t: Terrain, tall: bool, open: bool) -> Option<Terrain> {
    match t {
        _ if t.walkable() && open => Some(if tall { Terrain::Wall } else { Terrain::Low }),
        Terrain::Drop | Terrain::Low if tall => Some(Terrain::Wall),
        _ => None,
    }
}

/// Which of a thing's footprint `tiles` hide what is behind them, by the land's
/// [`Sight`](crate::land::Sight): none when it rises no higher than the eye; where its model's
/// footprint is measured at eye height (`eye_cells`, [`ModelFootprint::eye`]), the tiles in which
/// a square of the model blocks at least `sight.solid` of the view (a wall, a room, a post and a
/// beam together); otherwise, or for a kind named in `hides_m`, every tile. The model stands
/// centred on `centre` facing `front`, its +X along `(front.1, -front.0)` (as the client places
/// it, `Lot::yaw`).
pub fn hiding_tiles(sight: &crate::land::Sight, kind: &str, height_m: f32, model: Option<&ModelFootprint>, centre: (f32, f32), front: (f32, f32), tiles: &[(i32, i32)]) -> Vec<bool> {
    if !sight.hides(kind, height_m) {
        return vec![false; tiles.len()];
    }
    let Some(eye) = model.filter(|_| sight.by_cells(kind)).and_then(|m| m.eye()) else {
        return vec![true; tiles.len()];
    };
    // A level is at least that many tenths blocked, so `solid` 0.6 needs level 6.
    let need = (sight.solid * 10.0 - 1e-4).ceil().clamp(0.0, 10.0) as u8;
    let (fx, fy) = front;
    let solid: std::collections::HashSet<(i32, i32)> = eye
        .levels
        .iter()
        .enumerate()
        .filter(|&(_, &l)| l >= need)
        .map(|(k, _)| {
            // The square's centre in the model's frame (x: +X, y: toward its back), on the map.
            let (bx, by) = eye.centre(k % eye.cols, k / eye.cols);
            ((centre.0 + bx * fy - by * fx).floor() as i32, (centre.1 - bx * fx - by * fy).floor() as i32)
        })
        .collect();
    tiles.iter().map(|t| solid.contains(t)).collect()
}

/// Whether a plan's blocking fixture hides what is behind it, by the land's
/// [`Sight`](crate::land::Sight): by its kind's `hides_m` when the seed names it; else never
/// when it rises no higher than the eye; else, when the plan gives the share of the view it
/// blocks at eye height (`eye_solid`: a paling fence, a net rack), when that reaches
/// `sight.solid`; else (a wall) it does.
pub fn fixture_hides(sight: &crate::land::Sight, fx: &crate::settle::LaidFixture) -> bool {
    sight.hides(&fx.kind, fx.height_m) && (!sight.by_cells(&fx.kind) || fx.eye_solid.map_or(true, |v| v >= sight.solid))
}

/// The land's tiles as the authority hosts them: building footprints block like walls, `Wall`
/// where the model hides what is behind it at eye height and `Low` where it does not
/// ([`hiding_tiles`], `LandParams::sight`). Water under a footprint is left alone, and so are roads, except under what
/// stands in a paved plaza by design: wells, market stalls and a landmark (a clock tower). Props that stand in the way
/// ([`crate::settle::PropKind::blocks`]: fountains, market crosses, carts, kiosks, food stalls)
/// block every walkable tile under them, in the same way; the planner keeps them off streets and door paths.
/// A plan's blocking fixtures (its walls and fences, `PlanSpec::fixtures`) block the tiles they
/// stand on ([`fixture_hides`]).
/// (Terrace drops, as `Drop`, and stair tiles are already in the land's own tiles; a drop
/// under a footprint or a blocking prop becomes `Wall` where it hides.) Also marks the main
/// walkable area, found from the first settlement's plaza.
pub fn hosted_map(land: &Land, p: &LandParams) -> (Map, Hosted) {
    let mut map = land.map.clone();
    let mut h = Hosted::default();
    let models: std::collections::HashMap<&str, &ModelFootprint> = p.settlements.buildings.models.iter().map(|m| (m.file.as_str(), m)).collect();
    let model = |file: &Option<String>| file.as_deref().and_then(|f| models.get(f).copied());
    for lot in land.lots.iter().filter(|l| blocks(l.kind)) {
        let on_plaza = matches!(lot.kind, LotKind::Well | LotKind::MarketStall) || land.settlements.get(lot.settlement as usize).is_some_and(|s| s.in_plaza(lot.centre));
        let tiles = footprint_tiles(lot, margin_of(land, p, lot));
        let hide = hiding_tiles(&p.sight, lot.kind.id(), lot.height_m, model(&lot.model_file), lot.centre, lot.front, &tiles);
        for (&(x, y), &tall) in tiles.iter().zip(&hide) {
            let t = map.get(x, y);
            if let Some(b) = blocking(t, tall, t != Terrain::Road || on_plaza) {
                map.set(x, y, b);
                h.blocked_tiles += 1;
            }
        }
    }
    for prop in land.props.iter().filter(|p| p.kind.blocks()) {
        let tiles = prop_tiles(prop);
        let hide = hiding_tiles(&p.sight, prop.kind.id(), prop.height_m, model(&prop.model_file), prop.centre, prop.front, &tiles);
        for (&(x, y), &tall) in tiles.iter().zip(&hide) {
            if let Some(b) = blocking(map.get(x, y), tall, true) {
                map.set(x, y, b);
                h.blocked_tiles += 1;
            }
        }
    }
    // A plan's fixtures that block (walls, fences, stacks: `PlanSpec::fixtures`): every walkable
    // tile under them, a street's too (the plan's author put the wall there), `Wall` where the
    // fixture hides and `Low` where it is seen over or through.
    for fx in land.plans.iter().flat_map(|p| p.fixtures.iter()) {
        let tall = fixture_hides(&p.sight, fx);
        for &(x, y) in &fx.tiles {
            if let Some(b) = blocking(map.get(x, y), tall, true) {
                map.set(x, y, b);
                h.blocked_tiles += 1;
            }
        }
    }
    let start = land.settlements.first().map(|s| s.plaza.centre).or_else(|| land.sites.first().map(|s| (s.x, s.y))).unwrap_or((map.w as f32 / 2.0, map.h as f32 / 2.0));
    // A building may stand in the middle of the first square (the megacity's arcology): start
    // from its walkable edge then.
    let start = if map.walkable(start.0 as i32, start.1 as i32) {
        start
    } else {
        land.settlements.first().and_then(|s| s.plaza.points.iter().map(|q| ((q.0 + start.0) * 0.5 + (q.0 - start.0) * 0.4, (q.1 + start.1) * 0.5 + (q.1 - start.1) * 0.4)).find(|q| map.walkable(q.0 as i32, q.1 as i32))).unwrap_or(start)
    };
    h.reachable = reach(&map, start);
    let walkable = map.tiles.iter().filter(|t| Terrain::from_u8(**t).walkable()).count() as u32;
    h.cut_off_tiles = walkable - h.reachable.iter().filter(|r| **r).count() as u32;
    (map, h)
}

/// Tiles reachable on foot from a point (4-connected, which 8-connected movement with its
/// no-corner-cutting rule also allows).
pub fn reach(map: &Map, from: (f32, f32)) -> Vec<bool> {
    let (w, h) = (map.w as i32, map.h as i32);
    let mut seen = vec![false; (map.w * map.h) as usize];
    let Some(s) = map.nearest_walkable(from.0, from.1) else { return seen };
    let mut stack = vec![(s.0 as i32, s.1 as i32)];
    seen[(s.1 as i32 * w + s.0 as i32) as usize] = true;
    while let Some((x, y)) = stack.pop() {
        for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
            let (nx, ny) = (x + dx, y + dy);
            if nx < 0 || ny < 0 || nx >= w || ny >= h {
                continue;
            }
            let i = (ny * w + nx) as usize;
            if !seen[i] && map.walkable(nx, ny) {
                seen[i] = true;
                stack.push((nx, ny));
            }
        }
    }
    seen
}

/// The settlement newcomers arrive at: the first plain town (a seed's `town`), else the first
/// town of any style, else the first settlement.
pub fn arrival_settlement(land: &Land) -> Option<&Settlement> {
    let plain = |s: &&Settlement| land.sites.get(s.site as usize).is_some_and(|x| x.kind == SiteKind::Town && x.style.is_none());
    land.settlements.iter().find(plain).or_else(|| land.settlements.iter().find(|s| s.kind == SiteKind::Town)).or_else(|| land.settlements.first())
}

/// How far from the square's heart, toward the first gate, a newcomer arrives (metres), at
/// most half the way to the square's edge.
const ARRIVAL_STEP_M: f32 = 6.0;
/// How far beyond the square's outline (tiles) the walkable ground connected to it is searched.
const ARRIVAL_MARGIN: i32 = 16;

/// Where newcomers arrive on a hosted land (`map` from [`hosted_map`]): on the arrival
/// settlement's square, where its people gather, a few metres from its heart on the side of
/// the town's first gate (the way one comes in), on a walkable tile connected to the square.
/// Without a settlement, the walkable tile nearest the land's middle. Deterministic for a seed,
/// size and parameters; part of the layout digest.
pub fn arrival(land: &Land, map: &Map) -> (f32, f32) {
    let middle = (land.size as f32 / 2.0, land.size as f32 / 2.0);
    let Some(s) = arrival_settlement(land) else { return map.nearest_walkable(middle.0, middle.1).unwrap_or(middle) };
    let c = s.plaza.centre;
    // Where one can stand on the square: its heart, or round a building standing in it (the
    // megacity core's arcology) near its outline's corners and the middles of its edges.
    let n = s.plaza.points.len();
    let edges = (0..n).map(|i| {
        let (a, b) = (s.plaza.points[i], s.plaza.points[(i + 1) % n]);
        ((a.0 + b.0) * 0.5, (a.1 + b.1) * 0.5)
    });
    let starts: Vec<(i32, i32)> = std::iter::once(c)
        .chain(s.plaza.points.iter().copied().chain(edges).map(|q| (q.0 * 0.9 + c.0 * 0.1, q.1 * 0.9 + c.1 * 0.1)))
        .map(|q| (q.0.floor() as i32, q.1.floor() as i32))
        .filter(|&(x, y)| map.walkable(x, y))
        .collect();
    let inner = s.plaza.points.iter().map(|q| (q.0 - c.0).hypot(q.1 - c.1)).fold(f32::INFINITY, f32::min);
    let step = if inner.is_finite() { ARRIVAL_STEP_M.min(inner * 0.5) } else { 0.0 };
    let want = match s.wall.as_ref().and_then(|w| w.gates.first()) {
        Some(g) => {
            let (dx, dy) = (g.at.0 - c.0, g.at.1 - c.1);
            let n = dx.hypot(dy).max(1e-3);
            (c.0 + dx / n * step, c.1 + dy / n * step)
        }
        None => c,
    };
    // The tile nearest `want` among those connected to the square, within the box round the
    // square's outline and `ARRIVAL_MARGIN` tiles beyond it (4-connected, as `reach`), ties to
    // the first found.
    let (mut x0, mut y0, mut x1, mut y1) = (c.0.floor() as i32, c.1.floor() as i32, c.0.floor() as i32, c.1.floor() as i32);
    for q in &s.plaza.points {
        (x0, y0, x1, y1) = (x0.min(q.0.floor() as i32), y0.min(q.1.floor() as i32), x1.max(q.0.floor() as i32), y1.max(q.1.floor() as i32));
    }
    let (x0, y0, x1, y1) = (x0 - ARRIVAL_MARGIN, y0 - ARRIVAL_MARGIN, x1 + ARRIVAL_MARGIN, y1 + ARRIVAL_MARGIN);
    let side = x1 - x0 + 1;
    let mut seen = vec![false; (side * (y1 - y0 + 1)) as usize];
    let idx = |x: i32, y: i32| ((y - y0) * side + (x - x0)) as usize;
    let inside = |x: i32, y: i32| (x0..=x1).contains(&x) && (y0..=y1).contains(&y);
    let mut queue = std::collections::VecDeque::new();
    for &(x, y) in &starts {
        if inside(x, y) && !seen[idx(x, y)] {
            seen[idx(x, y)] = true;
            queue.push_back((x, y));
        }
    }
    let mut best: Option<((f32, f32), f32)> = None;
    while let Some((x, y)) = queue.pop_front() {
        let p = (x as f32 + 0.5, y as f32 + 0.5);
        let d = (p.0 - want.0).hypot(p.1 - want.1);
        if best.map_or(true, |(_, bd)| d < bd) {
            best = Some((p, d));
        }
        for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
            let (nx, ny) = (x + dx, y + dy);
            if inside(nx, ny) && !seen[idx(nx, ny)] && map.walkable(nx, ny) {
                seen[idx(nx, ny)] = true;
                queue.push_back((nx, ny));
            }
        }
    }
    best.map(|b| b.0).or_else(|| map.nearest_walkable(c.0, c.1)).unwrap_or(c)
}

/// Digests the authority stores with the world and a client recomputes after regenerating the
/// land from the same seed, size and parameters.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Digests {
    /// The hosted tiles (with building footprints), before anyone changes them.
    pub tiles: u64,
    /// `Land::height` and `Land::water_level` on a lattice every `HEIGHT_STEP_M` metres.
    pub heights: u64,
    /// Settlements, lots (kind, centre, size, front, floor, model), roads (points, heights),
    /// props (kind, centre, size, front, floor, model) and the arrival point ([`arrival`]).
    pub layout: u64,
}

pub const HEIGHT_STEP_M: u32 = 8;

pub fn digests(land: &Land, hosted: &Map) -> Digests {
    let tiles = fnv1a(FNV_OFFSET, &hosted.tiles);
    let mut heights = FNV_OFFSET;
    let mut y = 0;
    while y < land.size {
        let mut x = 0;
        while x < land.size {
            let (fx, fy) = (x as f32 + 0.37, y as f32 + 0.61);
            heights = fnv1a(heights, &land.height(fx, fy).to_bits().to_le_bytes());
            heights = fnv1a(heights, &land.water_level(fx, fy).to_bits().to_le_bytes());
            x += HEIGHT_STEP_M;
        }
        y += HEIGHT_STEP_M;
    }
    let mut layout = FNV_OFFSET;
    let mut f = |v: f32| layout = fnv1a(layout, &v.to_bits().to_le_bytes());
    for s in &land.settlements {
        f(s.centre.0);
        f(s.centre.1);
        f(s.radius_m);
        f(s.plaza.floor_m);
    }
    for l in &land.lots {
        f(l.kind as u8 as f32);
        for v in [l.centre.0, l.centre.1, l.width_m, l.depth_m, l.front.0, l.front.1, l.floor_m, l.height_m] {
            f(v);
        }
    }
    for r in &land.roads {
        for (p, h) in r.points.iter().zip(&r.heights) {
            f(p.0);
            f(p.1);
            f(*h);
        }
    }
    for l in &land.lots {
        layout = fnv1a(layout, l.model_file.as_deref().unwrap_or("").as_bytes());
    }
    for pr in &land.props {
        layout = fnv1a(layout, &[pr.kind as u8]);
        for v in [pr.centre.0, pr.centre.1, pr.width_m, pr.depth_m, pr.front.0, pr.front.1, pr.floor_m, pr.height_m] {
            layout = fnv1a(layout, &v.to_bits().to_le_bytes());
        }
        layout = fnv1a(layout, pr.model_file.as_deref().unwrap_or("").as_bytes());
    }
    let a = arrival(land, hosted);
    for v in [a.0, a.1] {
        layout = fnv1a(layout, &v.to_bits().to_le_bytes());
    }
    Digests { tiles, heights, layout }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::land;

    /// Seed 7 at 2048 m, the first world: buildings block, every building's door and every
    /// plaza is in the main walkable area, and few tiles are cut off.
    #[test]
    fn hosted_island_keeps_doors_reachable() {
        let p = LandParams::default();
        let l = land::generate(7, 2048, &p);
        let (map, h) = hosted_map(&l, &p);
        let at = |pt: (f32, f32)| {
            let q = map.nearest_walkable(pt.0, pt.1).expect("walkable near");
            h.reachable[(q.1 as u32 * map.w + q.0 as u32) as usize]
        };
        assert!(h.blocked_tiles > 5_000, "buildings block: {}", h.blocked_tiles);
        for s in &l.settlements {
            assert!(at(s.plaza.centre), "plaza of {:?} reachable", s.kind);
        }
        let mut doors = 0;
        let mut stranded = Vec::new();
        for (i, lot) in l.lots.iter().enumerate().filter(|(_, l)| blocks(l.kind) && l.kind != LotKind::MarketStall && l.kind != LotKind::Well) {
            doors += 1;
            if !at(door(lot)) {
                stranded.push((i, lot.kind, lot.centre));
            }
        }
        eprintln!("blocked {} tiles, cut off {} tiles, {} doors, {} stranded", h.blocked_tiles, h.cut_off_tiles, doors, stranded.len());
        assert!(stranded.len() * 50 <= doors, "doors cut off: {stranded:?}");
    }

    /// The megacity floor at 2048 m, hosted: buildings block, and every ward's square and
    /// nearly every door is in the main walkable area.
    #[test]
    fn hosted_megacity_keeps_doors_reachable() {
        let v: serde_json::Value = serde_json::from_str(include_str!("../../seeds/floor-megacity.json")).unwrap();
        let p: LandParams = serde_json::from_value(v["map"]["params"].clone()).unwrap();
        let l = land::generate(v["seed"].as_u64().unwrap(), 2048, &p);
        let (map, h) = hosted_map(&l, &p);
        let at = |pt: (f32, f32)| {
            let q = map.nearest_walkable(pt.0, pt.1).expect("walkable near");
            h.reachable[(q.1 as u32 * map.w + q.0 as u32) as usize]
        };
        // A square is reachable at its middle, or round a building standing in it (the core's
        // arcology) at the middle of its outline's edges.
        for s in &l.settlements {
            let n = s.plaza.points.len();
            let edges = (0..n).map(|i| {
                let (a, b) = (s.plaza.points[i], s.plaza.points[(i + 1) % n]);
                ((a.0 + b.0) * 0.5 * 0.9 + s.plaza.centre.0 * 0.1, (a.1 + b.1) * 0.5 * 0.9 + s.plaza.centre.1 * 0.1)
            });
            assert!(std::iter::once(s.plaza.centre).chain(edges).any(|q| map.walkable(q.0 as i32, q.1 as i32) && at(q)), "square of the {} settlement at {:?} reachable", s.style, s.plaza.centre);
        }
        let mut doors = 0;
        let mut stranded = 0;
        for lot in l.lots.iter().filter(|l| blocks(l.kind) && l.kind != LotKind::MarketStall && l.kind != LotKind::Well) {
            doors += 1;
            if !at(door(lot)) {
                stranded += 1;
            }
        }
        eprintln!("megacity 2048: blocked {} tiles, cut off {}, {doors} doors, {stranded} stranded", h.blocked_tiles, h.cut_off_tiles);
        assert!(stranded * 50 <= doors, "{stranded} of {doors} doors cut off");
    }

    /// Newcomers arrive on the first town's square, in the main walkable area, on the island's
    /// world seeds and on the megacity floor; the point is repeatable and in the layout digest.
    #[test]
    fn arrival_is_on_the_first_towns_square() {
        let v: serde_json::Value = serde_json::from_str(include_str!("../../seeds/floor-megacity.json")).unwrap();
        let mega: LandParams = serde_json::from_value(v["map"]["params"].clone()).unwrap();
        let worlds = [7u64, 11, 13].map(|s| (s, LandParams::default())).into_iter().chain([(v["seed"].as_u64().unwrap(), mega)]);
        for (seed, p) in worlds {
            let l = land::generate(seed, 2048, &p);
            let (map, h) = hosted_map(&l, &p);
            let a = arrival(&l, &map);
            let s = arrival_settlement(&l).expect("a settlement");
            let c = s.plaza.centre;
            let inner = s.plaza.points.iter().map(|q| (q.0 - c.0).hypot(q.1 - c.1)).fold(f32::INFINITY, f32::min);
            let d = (a.0 - c.0).hypot(a.1 - c.1);
            assert!(map.walkable(a.0 as i32, a.1 as i32) && h.reachable[(a.1 as u32 * map.w + a.0 as u32) as usize], "seed {seed}: arrival {a:?} walkable and reachable");
            assert!(d <= ARRIVAL_STEP_M.max(inner) + 1.0, "seed {seed}: arrival {a:?} {d:.1} m from the square's heart (inner {inner:.1})");
            if p.metro.is_none() {
                assert!(s.kind == SiteKind::Town && l.sites[s.site as usize].style.is_none(), "seed {seed}: arrives at the plain town");
            }
            assert_eq!(a, arrival(&l, &map), "repeatable");
            // Only the arrival reads the square's own centre: moving it moves the arrival, and
            // the layout digest with it (the megacity core's heart is built on, so its arrival
            // on the square's edge may not move).
            if p.metro.is_none() {
                let mut moved = l.clone();
                moved.settlements.iter_mut().for_each(|t| t.plaza.centre.0 += 3.0);
                assert_ne!(arrival(&moved, &map), a);
                assert_ne!(digests(&l, &map).layout, digests(&moved, &map).layout, "the layout digest covers the arrival");
            }
            eprintln!("seed {seed}: arrival {a:?}, {d:.1} m from the square's heart");
        }
    }

    /// The island (seed 7 at 2048 m, default parameters), generated once for the sight tests.
    fn island() -> &'static Land {
        static L: std::sync::OnceLock<Land> = std::sync::OnceLock::new();
        L.get_or_init(|| land::generate(7, 2048, &LandParams::default()))
    }

    /// Lines past a thing, one per direction of 32 that has one: an eye a few metres before it
    /// and a point just behind it, both on open ground, such that only the thing's own tiles lie
    /// between (without them the line is clear; with them as walls it is not).
    fn lines_past(m: &Map, tiles: &[(i32, i32)], c: (f32, f32), half: f32) -> Vec<((f32, f32), (f32, f32))> {
        let mut without = m.clone();
        let mut walled = m.clone();
        for &(x, y) in tiles {
            if !matches!(m.get(x, y), Terrain::Water | Terrain::Road) && !m.get(x, y).walkable() {
                without.set(x, y, Terrain::Grass);
                walled.set(x, y, Terrain::Wall);
            }
        }
        (0..32)
            .map(|k| k as f32 * std::f32::consts::TAU / 32.0)
            .filter_map(|a| {
                let d = (a.cos(), a.sin());
                let e = (c.0 - d.0 * (half + 3.0), c.1 - d.1 * (half + 3.0));
                let r = (c.0 + d.0 * (half + 1.5), c.1 + d.1 * (half + 1.5));
                (m.free(e.0, e.1) && m.free(r.0, r.1) && without.sight_clear(e, r) && !walled.sight_clear(e, r)).then_some((e, r))
            })
            .collect()
    }

    /// The land data that decides sight: a cart's footprint is `Low` (no walking, but one sees
    /// and shoots over it, 1.02-1.12 m, below the 1.6 m eye) and someone behind it is seen. The
    /// seed's `hides_m` decides a kind outright, without code: stalls hiding to 3 m hide
    /// throughout, and a well seen over its rim (`{"well": 0.95}`) hides no one. The tiles
    /// digest covers it. An empty map is the default; an eye outside the band the models were
    /// measured in (3 m) falls back to the height rule, so a 2.6 m stall is low.
    #[test]
    fn sight_is_blocked_only_above_eye_height() {
        let l = island();
        let p = LandParams::default();
        let (m, _) = hosted_map(l, &p);
        let lot_tiles = |lot: &Lot| footprint_tiles(lot, margin_of(l, &p, lot));
        // A cart (the island's carts stand in its towns' streets): Low, and seen over.
        let carts: Vec<&crate::settle::Prop> = l.props.iter().filter(|x| x.kind == crate::settle::PropKind::Cart).collect();
        assert!(!carts.is_empty() && carts.iter().all(|c| c.height_m > 0.0 && c.height_m < 1.6), "carts below the eye: {:?}", carts.iter().map(|c| c.height_m).collect::<Vec<_>>());
        let mut seen_past_a_cart = 0;
        for c in &carts {
            let tiles = prop_tiles(c);
            assert!(tiles.iter().any(|&(x, y)| m.get(x, y) == Terrain::Low), "a cart at {:?} stands on low tiles", c.centre);
            assert!(tiles.iter().all(|&(x, y)| !m.walkable(x, y)), "no one walks through a cart at {:?}", c.centre);
            if let Some(&(e, r)) = lines_past(&m, &tiles, c.centre, c.width_m.max(c.depth_m) * 0.5).first() {
                assert!(m.sight_clear(e, r), "someone behind the cart at {:?} is seen", c.centre);
                seen_past_a_cart += 1;
            }
        }
        assert!(seen_past_a_cart > 0, "no line past a cart to test");
        let eye = arrival(l, &m);
        let near = |q: (f32, f32)| ((q.0 - eye.0).powi(2) + (q.1 - eye.1).powi(2)).sqrt() <= 48.0;
        let on_square = |kind: LotKind| l.lots.iter().filter(move |x| x.kind == kind && near(x.centre)).collect::<Vec<_>>();
        let all_wall = |m: &Map, lot: &Lot| lot_tiles(lot).iter().all(|&(x, y)| m.get(x, y) == Terrain::Wall);
        let no_wall = |m: &Map, lot: &Lot| lot_tiles(lot).iter().all(|&(x, y)| m.get(x, y) != Terrain::Wall);
        // The seed decides a kind outright: stalls hiding to 3 m, wells seen over their rim.
        let mut kinds = p.clone();
        kinds.sight.hides_m.insert("market_stall".into(), 3.0);
        kinds.sight.hides_m.insert("well".into(), 0.95);
        let (mk, _) = hosted_map(l, &kinds);
        assert_eq!(digests(l, &mk).heights, digests(l, &m).heights);
        assert_ne!(digests(l, &mk).tiles, digests(l, &m).tiles, "the tiles digest covers `hides_m`");
        assert!(!on_square(LotKind::MarketStall).is_empty() && on_square(LotKind::MarketStall).iter().all(|x| all_wall(&mk, x)), "stalls hiding to 3 m hide throughout");
        assert!(!on_square(LotKind::Well).is_empty() && on_square(LotKind::Well).iter().all(|x| no_wall(&mk, x)), "a well seen over its rim hides nowhere");
        // An empty map is the default; at a 3 m eye the cells do not apply and a 2.6 m stall is low.
        let (me, _) = hosted_map(l, &LandParams { sight: land::Sight { eye_m: 1.6, hides_m: Default::default(), ..Default::default() }, ..p.clone() });
        assert_eq!(me.tiles, m.tiles);
        let (tall, _) = hosted_map(l, &LandParams { sight: land::Sight { eye_m: 3.0, ..Default::default() }, ..p.clone() });
        assert!(on_square(LotKind::MarketStall).iter().all(|lot| no_wall(&tall, lot)), "at a 3 m eye a 2.6 m stall is low");
    }

    /// Where a model rises above the eye, it hides only where its mesh is solid at eye height
    /// (`eye_cells` in data/buildings.json, measured by buildings.py): on Brackenford's square
    /// (the island's arrival) the market stalls are open (four posts, a counter below the band)
    /// and every line past one is seen; so is every line across the fantasy well (a 0.95 m rim
    /// under a roof on two posts, a windlass across them at eye height: about 70% of its posts'
    /// squares' view, below `Sight::solid`); a townhouse, a closed building, hides on every
    /// line past it. Everything else is as by the height rule: the tiles differ from it only
    /// where its `Wall` is now `Low` (or, over a drop, `Drop`), and the square hides fewer of its
    /// walkable points.
    #[test]
    fn a_well_and_an_open_stall_are_seen_through_but_a_closed_building_is_not() {
        let l = island();
        let p = LandParams::default();
        let (m, _) = hosted_map(l, &p);
        let lot_tiles = |lot: &Lot| footprint_tiles(lot, margin_of(l, &p, lot));
        let eye = arrival(l, &m);
        let near = |q: (f32, f32)| ((q.0 - eye.0).powi(2) + (q.1 - eye.1).powi(2)).sqrt() <= 48.0;
        let on_square = |kind: LotKind| l.lots.iter().filter(move |x| x.kind == kind && near(x.centre)).collect::<Vec<_>>();
        // Every model on the square is measured, and placed as the client places it.
        for lot in l.lots.iter().filter(|x| blocks(x.kind) && near(x.centre)) {
            let model = p.settlements.buildings.model(lot.model_file.as_deref().expect("a model")).expect("in the table");
            assert!(model.eye().is_some_and(|e| e.cols as f32 * crate::settle::EYE_CELL_M >= model.width_m), "{} is measured", model.file);
            assert!((lot.yaw - lot.front.0.atan2(lot.front.1)).rem_euclid(std::f32::consts::TAU).min((lot.front.0.atan2(lot.front.1) - lot.yaw).rem_euclid(std::f32::consts::TAU)) < 1e-3, "{:?}'s yaw faces its front", lot.kind);
        }
        let lines = |lot: &Lot| lines_past(&m, &lot_tiles(lot), lot.centre, lot.width_m.max(lot.depth_m) * 0.5);
        let stalls = on_square(LotKind::MarketStall);
        assert!(stalls.len() >= 5, "stalls on the square: {}", stalls.len());
        let mut stall_lines = 0;
        for lot in &stalls {
            assert!(lot_tiles(lot).iter().all(|&(x, y)| m.get(x, y) != Terrain::Wall), "an open stall at {:?} hides nowhere", lot.centre);
            for (e, r) in lines(lot) {
                assert!(m.sight_clear(e, r), "someone behind the stall at {:?} is seen", lot.centre);
                stall_lines += 1;
            }
        }
        assert!(stall_lines > 0, "no line past a stall");
        let wells = on_square(LotKind::Well);
        assert!(!wells.is_empty());
        for lot in &wells {
            let tiles = lot_tiles(lot);
            assert!(tiles.iter().all(|&(x, y)| m.get(x, y) == Terrain::Low), "the well at {:?} hides nowhere", lot.centre);
            let ls = lines(lot);
            assert!(!ls.is_empty() && ls.iter().all(|&(e, r)| m.sight_clear(e, r)), "someone across the well at {:?} is seen", lot.centre);
            // Its posts' squares (post and windlass) block most of the view, not nearly all: at
            // a lower `solid` they hide, on the tiles they land on.
            let mut strict = p.clone();
            strict.sight.solid = 0.6;
            let (ms, _) = hosted_map(l, &strict);
            assert!(tiles.iter().any(|&(x, y)| ms.get(x, y) == Terrain::Wall), "at 0.6 the well's posts hide");
        }
        let houses = on_square(LotKind::Townhouse);
        let mut house_lines = 0;
        for lot in &houses {
            for (e, r) in lines(lot) {
                assert!(!m.sight_clear(e, r), "a townhouse at {:?} hides what is behind it", lot.centre);
                house_lines += 1;
            }
        }
        assert!(house_lines > 0, "no line past a townhouse");
        // Against the height rule (the same land with no model measured).
        let mut tall = p.clone();
        for md in tall.settlements.buildings.models.iter_mut() {
            md.eye_cells = None;
        }
        let (hr, _) = hosted_map(l, &tall);
        let mut low = 0;
        for (k, (&a, &b)) in m.tiles.iter().zip(&hr.tiles).enumerate() {
            if a != b {
                assert!(b == Terrain::Wall as u8 && (a == Terrain::Low as u8 || a == Terrain::Drop as u8), "tile {k}: {a} by the cells, {b} by height");
                low += 1;
            }
        }
        assert!(low > 0);
        assert_eq!(digests(l, &m).heights, digests(l, &hr).heights);
        assert_eq!(digests(l, &m).layout, digests(l, &hr).layout);
        let pts: Vec<(f32, f32)> = (eye.1 as i32 - 48..=eye.1 as i32 + 48).flat_map(|y| (eye.0 as i32 - 48..=eye.0 as i32 + 48).map(move |x| (x, y))).filter(|&(x, y)| m.walkable(x, y)).map(|(x, y)| (x as f32 + 0.5, y as f32 + 0.5)).filter(|&q| near(q)).collect();
        let hidden = |m: &Map| pts.iter().filter(|&&q| !m.sight_clear(eye, q)).count();
        let (a, b) = (hidden(&hr), hidden(&m));
        assert!(b < a, "the square's hidden points: {a} by height, {b} by the cells");
        eprintln!("arrival square, walkable points within 48 m: {}; hidden {a} by height, {b} by the cells; {low} tiles from Wall to Low or Drop on the land", pts.len());
    }

    /// The table's eye cells decode, and a square's centre is in the model's frame.
    #[test]
    fn eye_cells_decode() {
        let m = crate::settle::ModelFootprint { style: "x".into(), kind: "x".into(), form: "x".into(), file: "x".into(), width_m: 1.5, depth_m: 1.0, height_m: 2.0, foundation_m: 0.0, corner: 0, tris: 0, eye_solid: Some(0.3), eye_cells: Some("3:2a1k3b".into()) };
        let e = m.eye().expect("decodes");
        assert_eq!((e.cols, e.rows, e.levels.clone()), (3, 2, vec![0, 0, 10, 1, 1, 1]));
        assert_eq!(e.centre(0, 0), (-0.5, -0.25));
        assert_eq!(e.centre(2, 1), (0.5, 0.25));
        for bad in ["", "3", "0:3a", "3:2a", "3:a", "3:3z", "3:3a2"] {
            assert!(crate::settle::ModelFootprint { eye_cells: Some(bad.into()), ..m.clone() }.eye().is_none(), "{bad:?}");
        }
        // A thing on the map: one square fully blocked, the front row's first (the model's -X
        // side). The model's +X points along (front.1, -front.0): +x here, with front +y.
        let front = (0.0, 1.0);
        let one = crate::settle::ModelFootprint { width_m: 2.0, depth_m: 2.0, eye_cells: Some("4:1k15a".into()), ..m.clone() };
        let tiles: Vec<(i32, i32)> = (8..12).flat_map(|y| (8..12).map(move |x| (x, y))).collect();
        let hide = hiding_tiles(&land::Sight::default(), "well", 3.0, Some(&one), (10.0, 10.0), front, &tiles);
        let hid: Vec<(i32, i32)> = tiles.iter().zip(&hide).filter(|(_, &h)| h).map(|(t, _)| *t).collect();
        // Square (0, 0): model x -0.75, y -0.75 (toward the front) -> map (10 - 0.75, 10 + 0.75).
        assert_eq!(hid, vec![(9, 10)]);
        assert!(hiding_tiles(&land::Sight::default(), "well", 1.5, Some(&one), (10.0, 10.0), front, &tiles).iter().all(|h| !h), "below the eye: nothing");
        assert!(hiding_tiles(&land::Sight::default(), "well", 3.0, None, (10.0, 10.0), front, &tiles).iter().all(|h| *h), "no model: all");
    }

    /// Prints the digests of the first world (seed 7, 2048 m) for comparison with the WASM
    /// authority's `land` row: `cargo test --release -p living-rules host::tests::print_digests
    /// -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn print_digests() {
        let p = LandParams::default();
        let l = land::generate(7, 2048, &p);
        let (m, _) = hosted_map(&l, &p);
        let d = digests(&l, &m);
        println!("digests seed 7 2048: tiles {:016x} heights {:016x} layout {:016x}", d.tiles, d.heights, d.layout);
    }

    /// The island (seed 7 at 2048 m, `seeds/island.json`) and the megacity floor at 2048 m
    /// (`seeds/floor-megacity.json`, as verify-generation's `floor-megacity-2k`) keep their
    /// digests: a change that should leave existing lands alone (a seed field they do not use,
    /// such as an empty `plans`) must not move a tile, a height or a lot. A change that is meant
    /// to change them updates these values in the same commit, and says so.
    #[test]
    fn pinned_digests_hold() {
        let island: serde_json::Value = serde_json::from_str(include_str!("../../seeds/island.json")).unwrap();
        let mega: serde_json::Value = serde_json::from_str(include_str!("../../seeds/floor-megacity.json")).unwrap();
        let params = |v: &serde_json::Value| -> LandParams { if v["map"]["params"].is_null() { LandParams::default() } else { serde_json::from_value(v["map"]["params"].clone()).unwrap() } };
        let cases = [
            // Tiles moved on 2026-11-11 (eye-2: models hide only where solid at eye height) from
            // 1a2a9a096caa8e21 and a3d6f6164c07192c, which the height rule (the last field: the
            // same land with no model's `eye_cells`) still gives exactly.
            ("island", island["seed"].as_u64().unwrap(), island["map"]["size"].as_u64().unwrap() as u32, params(&island), (0xe051dd1788c4d9f9u64, 0x0d2f77752781845c, 0x8ff57472b004a13f), 0x1a2a9a096caa8e21u64),
            ("floor-megacity-2k", mega["seed"].as_u64().unwrap(), 2048, params(&mega), (0x5340b81e0eef2bd4, 0xc06f16f3dcac1290, 0x0c6b3f2c51f13129), 0xa3d6f6164c07192c),
        ];
        let mut bad = Vec::new();
        for (name, seed, size, p, want, by_height) in cases {
            let l = land::generate(seed, size, &p);
            let (m, _) = hosted_map(&l, &p);
            let d = digests(&l, &m);
            eprintln!("{name}: tiles {:016x} heights {:016x} layout {:016x}", d.tiles, d.heights, d.layout);
            if (d.tiles, d.heights, d.layout) != want {
                bad.push(format!("{name}: tiles {:016x} heights {:016x} layout {:016x}, pinned {:016x} {:016x} {:016x}", d.tiles, d.heights, d.layout, want.0, want.1, want.2));
            }
            let mut tall = p.clone();
            for md in tall.settlements.buildings.models.iter_mut() {
                md.eye_cells = None;
            }
            let (hr, _) = hosted_map(&l, &tall);
            if digests(&l, &hr).tiles != by_height {
                bad.push(format!("{name}: by height tiles {:016x}, pinned {by_height:016x}", digests(&l, &hr).tiles));
            }
            // A pure reclassification: only the height rule's walls under models became low (or,
            // over a drop, stayed a drop).
            let moved = m.tiles.iter().zip(&hr.tiles).filter(|(a, b)| a != b).count();
            let reclassified = m.tiles.iter().zip(&hr.tiles).filter(|(&a, &b)| a != b && b == Terrain::Wall as u8 && (a == Terrain::Low as u8 || a == Terrain::Drop as u8)).count();
            eprintln!("{name}: {moved} tiles from Wall to Low or Drop");
            if moved != reclassified {
                bad.push(format!("{name}: {} tiles moved otherwise", moved - reclassified));
            }
        }
        assert!(bad.is_empty(), "digests moved: {bad:?}");
    }

    #[test]
    fn digests_are_repeatable() {
        let p = LandParams::default();
        let a = land::generate(5, 1024, &p);
        let b = land::generate(5, 1024, &p);
        let (ma, _) = hosted_map(&a, &p);
        let (mb, _) = hosted_map(&b, &p);
        assert_eq!(digests(&a, &ma), digests(&b, &mb));
    }
}
