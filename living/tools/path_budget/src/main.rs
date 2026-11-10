//! Walking-route costs on a world's real terrain (docs/SOAK.md D1, docs/PATHS.md).
//!
//! `path-budget <world.json> [plain|legs|clicks <clicks.json>]` where the world file holds
//! `{"w","h","chunks":[[id,[tiles…]]…],"from":[x,y],"to":[[name,x,y]…]}` (terrain_chunk rows as
//! the authority stores them).
//!
//! - `plain` (the default): for each target, the plain tile search's budget, doubling from
//!   6,000 (the authority's old `motion::start`), that finds a path, with its length and time.
//! - `legs`: each target walked leg by leg with `Map::route_leg`, re-planning 16 m before each
//!   leg's end as `motion` does: legs, areas, regions and tiles expanded per leg, time per
//!   leg, and the walked length against the plain search's optimum.
//! - `clicks <clicks.json>`: replays click-to-move requests `[{"from":[x,y],"to":[x,y],"out":…}]`
//!   (the soak's, reconstructed from its events) through the old and the new first step.
use living_rules::map::Map;
use living_rules::nav::RouteSpec;
use std::time::Instant;

/// Re-plan when the current leg's end is this close (`motion::REPLAN_AHEAD_M`).
const AHEAD: f32 = 16.0;

fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}

fn length(from: (f32, f32), p: &[(f32, f32)]) -> f32 {
    let mut at = from;
    let mut l = 0.0;
    for q in p {
        l += dist(at, *q);
        at = *q;
    }
    l
}

fn pct(v: &mut [f64], q: f64) -> f64 {
    if v.is_empty() {
        return 0.0;
    }
    v.sort_by(|a, b| a.total_cmp(b));
    v[((v.len() - 1) as f64 * q).round() as usize]
}

/// The goal as `motion::start` takes it: the clicked point, or the nearest walkable tile.
fn goal(map: &Map, raw: (f32, f32)) -> Option<(f32, f32)> {
    if map.free(raw.0, raw.1) {
        Some(raw)
    } else {
        map.nearest_walkable(raw.0, raw.1)
    }
}

struct Walk {
    legs: usize,
    walked: f32,
    max_areas: usize,
    max_regions: usize,
    max_tiles: usize,
    leg_ms: Vec<f64>,
}

/// Walk from `from` to `to` along legs, cutting each leg `AHEAD` before its end.
fn walk(map: &Map, from: (f32, f32), to: (f32, f32), spec: &RouteSpec) -> Option<Walk> {
    let mut at = from;
    let mut w = Walk { legs: 0, walked: 0.0, max_areas: 0, max_regions: 0, max_tiles: 0, leg_ms: Vec::new() };
    for _ in 0..2_000 {
        let t0 = Instant::now();
        let leg = map.route_leg(at, to, spec)?;
        w.leg_ms.push(t0.elapsed().as_secs_f64() * 1000.0);
        w.legs += 1;
        w.max_areas = w.max_areas.max(leg.areas);
        w.max_regions = w.max_regions.max(leg.regions);
        w.max_tiles = w.max_tiles.max(leg.tiles);
        if leg.last {
            w.walked += length(at, &leg.points);
            return Some(w);
        }
        // Walk the leg's corners, in half-metre steps, until its end is `AHEAD` away.
        let end = *leg.points.last().unwrap();
        'leg: for q in &leg.points {
            let n = (dist(at, *q) / 0.5).ceil().max(1.0) as usize;
            let a = at;
            for k in 1..=n {
                let t = k as f32 / n as f32;
                let p = (a.0 + (q.0 - a.0) * t, a.1 + (q.1 - a.1) * t);
                w.walked += dist(at, p);
                at = p;
                if dist(at, end) < AHEAD {
                    break 'leg;
                }
            }
        }
    }
    None
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&args[1]).unwrap()).unwrap();
    let mode = args.get(2).map(String::as_str).unwrap_or("plain");
    let (w, h) = (v["w"].as_u64().unwrap() as u32, v["h"].as_u64().unwrap() as u32);
    let chunks = v["chunks"].as_array().unwrap().iter().map(|c| {
        let id = c[0].as_u64().unwrap() as u32;
        let tiles: Vec<u8> = c[1].as_array().unwrap().iter().map(|t| t.as_u64().unwrap() as u8).collect();
        (id, tiles)
    });
    let map = Map::from_chunks(w, h, chunks);
    let spec = RouteSpec::default();
    let from = (v["from"][0].as_f64().unwrap() as f32, v["from"][1].as_f64().unwrap() as f32);
    match mode {
        "clicks" => return clicks(&map, &args[3], &spec),
        "cache" => {
            while map.warm_routes(4096) {}
            let (c, r, a) = map.route_cache();
            println!("whole map built: {c} chunks, {r} regions, {a} areas");
            return;
        }
        "legs" => {
            // Warm every region first, so leg times are searches only; the cold column is a
            // fresh copy's first leg (building the regions it needs).
            for t in v["to"].as_array().unwrap() {
                let raw = (t[1].as_f64().unwrap() as f32, t[2].as_f64().unwrap() as f32);
                let _ = walk(&map, from, goal(&map, raw).unwrap_or(raw), &spec);
            }
            println!("target\tstraight m\tlegs\twalked m\toptimum m\tratio\tmax areas\tmax regions\tmax tiles\tleg ms p50\tp99\tmax\tfirst leg ms (cold)");
        }
        _ => {}
    }
    for t in v["to"].as_array().unwrap() {
        let name = t[0].as_str().unwrap_or("?").to_string();
        let raw = (t[1].as_f64().unwrap() as f32, t[2].as_f64().unwrap() as f32);
        let to = goal(&map, raw).unwrap_or(raw);
        let straight = dist(from, to);
        if mode == "legs" {
            let cold = map.clone_cold();
            let t0 = Instant::now();
            let _ = cold.route_leg(from, to, &spec);
            let cold_ms = t0.elapsed().as_secs_f64() * 1000.0;
            let opt = map.path(from, to, 6_000 * 1024).map(|p| length(from, &p));
            match walk(&map, from, to, &spec) {
                Some(mut wk) => {
                    let o = opt.unwrap_or(f32::NAN);
                    let (p50, p99, max) = (pct(&mut wk.leg_ms, 0.5), pct(&mut wk.leg_ms, 0.99), pct(&mut wk.leg_ms, 1.0));
                    println!("{name}\t{straight:.0}\t{}\t{:.0}\t{o:.0}\t{:.3}\t{}\t{}\t{}\t{p50:.3}\t{p99:.3}\t{max:.3}\t{cold_ms:.2}", wk.legs, wk.walked, wk.walked / o, wk.max_areas, wk.max_regions, wk.max_tiles);
                }
                None => println!("{name}\t{straight:.0}\tno route"),
            }
            continue;
        }
        let mut budget = 6_000usize;
        let mut out = None;
        while budget <= 6_000 * 1024 {
            let t0 = Instant::now();
            let p = map.path(from, to, budget);
            let ms = t0.elapsed().as_secs_f64() * 1000.0;
            if let Some(p) = p {
                out = Some((budget, length(from, &p), ms, p.len()));
                break;
            }
            budget *= 2;
        }
        match out {
            Some((b, len, ms, n)) => println!("{name}\tstraight {straight:.0} m\tfound with budget {b}\tpath {len:.0} m ({n} waypoints)\tsearch {ms:.1} ms"),
            None => println!("{name}\tstraight {straight:.0} m\tno path within {} expansions", 6_000 * 1024),
        }
    }
}

/// Replay clicks: what the old first step (`Map::path` at 6,000) and the new one
/// (`Map::route_leg`) answer, tallied against the outcome the run saw.
fn clicks(map: &Map, file: &str, spec: &RouteSpec) {
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(file).unwrap()).unwrap();
    let mut tally = std::collections::BTreeMap::<String, usize>::new();
    let mut ms = Vec::new();
    let mut ratio = Vec::new();
    for r in v.as_array().unwrap() {
        let Some(f) = r["from"].as_array() else { continue };
        let from = (f[0].as_f64().unwrap() as f32, f[1].as_f64().unwrap() as f32);
        let raw = (r["to"][0].as_f64().unwrap() as f32, r["to"][1].as_f64().unwrap() as f32);
        let seen = r["out"].as_str().unwrap_or("?");
        let Some(to) = goal(map, raw) else {
            *tally.entry(format!("{seen:24} | no walkable tile within 12 m of the click")).or_default() += 1;
            continue;
        };
        let old = map.path(from, to, 6_000).is_some();
        let t0 = Instant::now();
        let new = map.route_leg(from, to, spec);
        ms.push(t0.elapsed().as_secs_f64() * 1000.0);
        let new_s = match &new {
            Some(_) => "route",
            None if !map.free(from.0, from.1) => "no route (start on a blocked tile)",
            None => "no route",
        };
        if new.is_some() {
            if let (Some(wk), Some(o)) = (walk(map, from, to, spec), map.path(from, to, 6_000 * 1024).map(|p| length(from, &p))) {
                ratio.push((wk.walked / o) as f64);
            }
        }
        *tally.entry(format!("{seen:24} | old {} | new {new_s}", if old { "path" } else { "none" })).or_default() += 1;
    }
    for (k, n) in &tally {
        println!("{n:4}  {k}");
    }
    println!("first leg ms: p50 {:.3} p99 {:.3} max {:.3}", pct(&mut ms, 0.5), pct(&mut ms, 0.99), pct(&mut ms, 1.0));
    println!("walked / optimum: p50 {:.3} p90 {:.3} max {:.3} (n {})", pct(&mut ratio, 0.5), pct(&mut ratio, 0.9), pct(&mut ratio, 1.0), ratio.len());
}

trait ColdClone {
    fn clone_cold(&self) -> Map;
}

impl ColdClone for Map {
    /// The same terrain with no regions built yet.
    fn clone_cold(&self) -> Map {
        Map::from_chunks(self.w, self.h, self.chunks().map(|id| (id, self.chunk_bytes(id))).collect::<Vec<_>>())
    }
}
