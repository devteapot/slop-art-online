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
use crate::settle::{Lot, LotKind, Prop, Settlement};

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

fn rect_tiles(centre: (f32, f32), front: (f32, f32), hw: f32, hd: f32) -> Vec<(i32, i32)> {
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
    /// Tiles turned into `Wall` under building footprints and the props that block.
    pub blocked_tiles: u32,
    /// Walkable tiles that buildings cut off from the main walkable area (enclosed yards); they
    /// stay as they are, but nothing is placed there.
    pub cut_off_tiles: u32,
    /// Per tile: in the main walkable area (row-major, like `Map::tiles`).
    pub reachable: Vec<bool>,
}

/// The land's tiles as the authority hosts them: building footprints become `Wall` (they block
/// like walls). Water under a footprint is left alone, and so are roads, except under what
/// stands in a paved plaza by design: wells, market stalls and a landmark (a clock tower). Props that stand in the way
/// ([`crate::settle::PropKind::blocks`]: fountains, market crosses, carts, kiosks, food stalls)
/// block every walkable tile under them; the planner keeps them off streets and door paths.
/// (Terrace drops and stair tiles are already in the land's own tiles.) Also marks the main
/// walkable area, found from the first settlement's plaza.
pub fn hosted_map(land: &Land, p: &LandParams) -> (Map, Hosted) {
    let mut map = land.map.clone();
    let mut h = Hosted::default();
    for lot in land.lots.iter().filter(|l| blocks(l.kind)) {
        let on_plaza = matches!(lot.kind, LotKind::Well | LotKind::MarketStall) || land.settlements.get(lot.settlement as usize).is_some_and(|s| s.in_plaza(lot.centre));
        for (x, y) in footprint_tiles(lot, margin_of(land, p, lot)) {
            let t = map.get(x, y);
            if t.walkable() && (t != Terrain::Road || on_plaza) {
                map.set(x, y, Terrain::Wall);
                h.blocked_tiles += 1;
            }
        }
    }
    for prop in land.props.iter().filter(|p| p.kind.blocks()) {
        for (x, y) in prop_tiles(prop) {
            if map.get(x, y).walkable() {
                map.set(x, y, Terrain::Wall);
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
            ("island", island["seed"].as_u64().unwrap(), island["map"]["size"].as_u64().unwrap() as u32, params(&island), (0x9b403da95bba9407u64, 0x0d2f77752781845c, 0x8ff57472b004a13f)),
            ("floor-megacity-2k", mega["seed"].as_u64().unwrap(), 2048, params(&mega), (0xdb59549c884bf8b8, 0xc06f16f3dcac1290, 0x0c6b3f2c51f13129)),
        ];
        let mut bad = Vec::new();
        for (name, seed, size, p, want) in cases {
            let l = land::generate(seed, size, &p);
            let (m, _) = hosted_map(&l, &p);
            let d = digests(&l, &m);
            eprintln!("{name}: tiles {:016x} heights {:016x} layout {:016x}", d.tiles, d.heights, d.layout);
            if (d.tiles, d.heights, d.layout) != want {
                bad.push(format!("{name}: tiles {:016x} heights {:016x} layout {:016x}, pinned {:016x} {:016x} {:016x}", d.tiles, d.heights, d.layout, want.0, want.1, want.2));
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
