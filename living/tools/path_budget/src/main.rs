//! How many expansions `Map::path` needs between places on a world's real terrain (docs/SOAK.md):
//! `path-budget <world.json>` where the file holds `{"w","h","chunks":[[id,[tiles…]]…],"from":[x,y],
//! "to":[[name,x,y]…]}` (terrain_chunk rows as the authority stores them). For each target it tries
//! budgets doubling from 6,000 (the authority's `motion::start`) and prints the first that finds a
//! path, its length and the search time.
use living_rules::map::Map;
use std::time::Instant;

fn main() {
    let path = std::env::args().nth(1).expect("world.json");
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let (w, h) = (v["w"].as_u64().unwrap() as u32, v["h"].as_u64().unwrap() as u32);
    let chunks = v["chunks"].as_array().unwrap().iter().map(|c| {
        let id = c[0].as_u64().unwrap() as u32;
        let tiles: Vec<u8> = c[1].as_array().unwrap().iter().map(|t| t.as_u64().unwrap() as u8).collect();
        (id, tiles)
    });
    let map = Map::from_chunks(w, h, chunks);
    let from = (v["from"][0].as_f64().unwrap() as f32, v["from"][1].as_f64().unwrap() as f32);
    for t in v["to"].as_array().unwrap() {
        let name = t[0].as_str().unwrap_or("?").to_string();
        let raw = (t[1].as_f64().unwrap() as f32, t[2].as_f64().unwrap() as f32);
        let to = if map.free(raw.0, raw.1) { raw } else { map.nearest_walkable(raw.0, raw.1).unwrap_or(raw) };
        let straight = ((to.0 - from.0).powi(2) + (to.1 - from.1).powi(2)).sqrt();
        let mut budget = 6_000usize;
        let mut out = None;
        while budget <= 6_000 * 1024 {
            let t0 = Instant::now();
            let p = map.path(from, to, budget);
            let ms = t0.elapsed().as_secs_f64() * 1000.0;
            if let Some(p) = p {
                let len: f32 = p.windows(2).map(|w| ((w[1].0 - w[0].0).powi(2) + (w[1].1 - w[0].1).powi(2)).sqrt()).sum();
                out = Some((budget, len, ms, p.len()));
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
