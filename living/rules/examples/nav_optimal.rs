//! Optimal walks for the navigation arenas (docs/MOVEMENT_MIND.md §4.1): for each walk, the best
//! path on the true map and the best on the walker's belief at the moment of its order, by an
//! exact 8-connected tile search with the planner's own costs (`living_rules::known::Shape`:
//! roads at `road_speed`, unseen ground at `unknown_cost`), with no node limit. The leg planner
//! can only match or exceed these, so they are floors.
//!
//! `cargo run --release -p living-rules --example nav_optimal -- TILES.bin W H WALKS.json`
//!
//! TILES.bin is the world's tiles, row-major (`y * W + x`), one byte each (`Terrain`). WALKS.json
//! is a list of walks: `{"start": [x, y], "goal": [x, y], "shut": [[x, y], …], "known": [{"block",
//! "cells", "seen_at"}], "edits": [{"chunk", "epoch", "tile", "before"}], "gates_seen": [[x, y,
//! open], …], "road_speed", "unknown_cost"}`. `shut` is the gates shut now (the true map);
//! `known`, `edits` and `gates_seen` are the walker's `known_ground` rows, the world's
//! `ground_edit` rows and its remembered gates, as read at the order. Prints one JSON line per
//! walk: for the true map and the belief, the path's time in metres at walking pace (roads at
//! `road_speed`, as the ground is), its length in metres and its tile count; for the belief also
//! `expected_m` (unseen ground at walking pace: what the walker expects) and the tiles of it that
//! are blocked in truth; `null` where no path exists. With `"path": true`, the
//! true path's tiles too.

use living_rules::known::{Belief, Edit, Ground, Known};
use living_rules::map::Map;
use serde_json::{json, Value};
use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap};

/// Best path from `s` to `g` where `cost(x, y)` is a tile's cost per metre (None: blocked).
/// Returns (cost, tiles) with tiles from start to goal.
fn search(w: i32, h: i32, s: (i32, i32), g: (i32, i32), min_cost: f32, cost: impl Fn(i32, i32) -> Option<f32>) -> Option<(f32, Vec<(i32, i32)>)> {
    let key = |p: (i32, i32)| (p.1 * w + p.0) as usize;
    let heur = |p: (i32, i32)| {
        let (dx, dy) = ((p.0 - g.0).abs() as f32, (p.1 - g.1).abs() as f32);
        (dx.max(dy) + (std::f32::consts::SQRT_2 - 1.0) * dx.min(dy)) * min_cost
    };
    let mut best: HashMap<usize, f32> = HashMap::new();
    let mut from: HashMap<usize, (i32, i32)> = HashMap::new();
    let mut heap = BinaryHeap::new();
    best.insert(key(s), 0.0);
    heap.push(Reverse(((heur(s) * 1000.0) as u64, (0.0f32 * 1000.0) as u64, s)));
    while let Some(Reverse((_, gk, p))) = heap.pop() {
        let gp = gk as f32 / 1000.0;
        if gp > best.get(&key(p)).copied().unwrap_or(f32::MAX) + 1e-3 {
            continue;
        }
        if p == g {
            let mut path = vec![p];
            let mut q = p;
            while let Some(&r) = from.get(&key(q)) {
                path.push(r);
                q = r;
            }
            path.reverse();
            return Some((gp, path));
        }
        for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)] {
            let q = (p.0 + dx, p.1 + dy);
            if q.0 < 0 || q.1 < 0 || q.0 >= w || q.1 >= h {
                continue;
            }
            let Some(c) = cost(q.0, q.1) else { continue };
            // No corner cutting: a diagonal step needs both sides open.
            if dx != 0 && dy != 0 && (cost(p.0 + dx, p.1).is_none() || cost(p.0, p.1 + dy).is_none()) {
                continue;
            }
            let step = if dx != 0 && dy != 0 { std::f32::consts::SQRT_2 } else { 1.0 };
            let gq = gp + step * c;
            if gq + 1e-3 < best.get(&key(q)).copied().unwrap_or(f32::MAX) {
                best.insert(key(q), gq);
                from.insert(key(q), p);
                heap.push(Reverse((((gq + heur(q)) * 1000.0) as u64, (gq * 1000.0) as u64, q)));
            }
        }
    }
    None
}

fn length(path: &[(i32, i32)]) -> f32 {
    path.windows(2).map(|w| (((w[1].0 - w[0].0).pow(2) + (w[1].1 - w[0].1).pow(2)) as f32).sqrt()).sum()
}

/// The walking-pace time (metres) of a path where `pace(x, y)` is a tile's cost per metre.
fn timed(path: &[(i32, i32)], pace: impl Fn(i32, i32) -> f32) -> f32 {
    path.windows(2)
        .map(|w| {
            let d = (((w[1].0 - w[0].0).pow(2) + (w[1].1 - w[0].1).pow(2)) as f32).sqrt();
            d * pace(w[1].0, w[1].1)
        })
        .sum()
}

fn pair(v: &Value) -> (f32, f32) {
    (v[0].as_f64().unwrap_or(0.0) as f32, v[1].as_f64().unwrap_or(0.0) as f32)
}

fn bytes(v: &Value) -> Vec<u8> {
    v.as_array().map(|a| a.iter().map(|x| x.as_u64().unwrap_or(0) as u8).collect()).unwrap_or_default()
}

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    assert!(a.len() == 4, "usage: nav_optimal TILES.bin W H WALKS.json");
    let tiles = std::fs::read(&a[0]).expect("tiles");
    let (w, h): (u32, u32) = (a[1].parse().unwrap(), a[2].parse().unwrap());
    assert_eq!(tiles.len(), (w * h) as usize, "tiles must be W × H bytes");
    let mut map = Map::from_chunks(w, h, std::iter::empty());
    map.tiles = tiles;
    let walks: Vec<Value> = serde_json::from_str(&std::fs::read_to_string(&a[3]).expect("walks")).expect("walks json");
    for walk in &walks {
        let road = walk["road_speed"].as_f64().unwrap_or(1.4) as f32;
        let unknown = walk["unknown_cost"].as_f64().unwrap_or(1.5) as f32;
        let shut: std::collections::HashSet<(i32, i32)> = walk["shut"].as_array().into_iter().flatten().map(|p| (p[0].as_i64().unwrap_or(-1) as i32, p[1].as_i64().unwrap_or(-1) as i32)).collect();
        let (s, g) = (pair(&walk["start"]), pair(&walk["goal"]));
        let (st, gt) = ((s.0.floor() as i32, s.1.floor() as i32), (g.0.floor() as i32, g.1.floor() as i32));
        let true_ground = |x: i32, y: i32| -> Option<f32> {
            if x < 0 || y < 0 || x >= w as i32 || y >= h as i32 || shut.contains(&(x, y)) {
                return None;
            }
            let t = living_rules::map::Terrain::from_u8(map.tiles[(y as u32 * w + x as u32) as usize]);
            if !t.walkable() {
                return None;
            }
            Some(if t == living_rules::map::Terrain::Road { 1.0 / road } else { 1.0 })
        };
        let want_path = walk["path"].as_bool().unwrap_or(false);
        let truth = search(w as i32, h as i32, st, gt, 1.0 / road, true_ground).map(|(c, p)| {
            let mut v = json!({"time_m": c, "len_m": length(&p), "tiles": p.len()});
            if want_path {
                v["path"] = json!(p.iter().map(|q| [q.0, q.1]).collect::<Vec<_>>());
            }
            v
        });
        // The belief at the order.
        let mut blocks: HashMap<u32, Known> = HashMap::new();
        for k in walk["known"].as_array().into_iter().flatten() {
            blocks.insert(k["block"].as_u64().unwrap_or(0) as u32, Known::from_bytes(&bytes(&k["cells"]), &bytes(&k["seen_at"])));
        }
        let mut edits: HashMap<u32, Vec<Edit>> = HashMap::new();
        for e in walk["edits"].as_array().into_iter().flatten() {
            edits.entry(e["chunk"].as_u64().unwrap_or(0) as u32).or_default().push(Edit { epoch: e["epoch"].as_u64().unwrap_or(0) as u32, tile: e["tile"].as_u64().unwrap_or(0) as u16, before: e["before"].as_u64().unwrap_or(0) as u8 });
        }
        let gates: HashMap<u32, bool> = walk["gates_seen"].as_array().into_iter().flatten().filter_map(|v| Some(((v[1].as_i64()? as u32) * w + v[0].as_i64()? as u32, v[2].as_bool()?))).collect();
        let belief = Belief::new(&map, move |b| blocks.get(&b).cloned(), move |c| edits.get(&c).cloned().unwrap_or_default(), gates);
        let plan_cost = |x: i32, y: i32| match belief.ground(x, y) {
            Ground::Blocked => None,
            Ground::Road => Some(1.0 / road),
            Ground::Unknown => Some(unknown),
            Ground::Open => Some(1.0),
        };
        let believed = search(w as i32, h as i32, st, gt, (1.0 / road).min(unknown), plan_cost).map(|(c, p)| {
            // Timed on the ground as it is (roads at road pace), so it compares with the walk;
            // and as the walker expects it (unseen ground at walking pace).
            let t = timed(&p, |x, y| true_ground(x, y).unwrap_or(1.0));
            let expected = timed(&p, |x, y| if belief.ground(x, y) == Ground::Road { 1.0 / road } else { 1.0 });
            let unseen = p.iter().filter(|q| belief.ground(q.0, q.1) == Ground::Unknown).count();
            let blocked = p.iter().filter(|q| true_ground(q.0, q.1).is_none()).count();
            json!({"time_m": t, "expected_m": expected, "plan_cost": c, "len_m": length(&p), "tiles": p.len(), "unseen_tiles": unseen, "blocked_in_truth": blocked})
        });
        println!("{}", json!({"start": [s.0, s.1], "goal": [g.0, g.1], "true": truth, "belief": believed}));
    }
}
