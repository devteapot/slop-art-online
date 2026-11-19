//! Who is hidden from the arrival square's eye within a radius, on a land's hosted tiles, under
//! four versions of them: `before` (drops and low things as `Wall`, as before 2026-11-11),
//! `height` (the height rule of 2026-11-11: a thing hides throughout when its model rises above
//! the eye), `after` (the seed's own `sight` parameters: where each model is solid at eye height,
//! its measured `eye_cells`) and `open_stalls` (the same with `hides_m {"market_stall": 0}`).
//! Also lists the things that block walking within the radius, with their heights, how many of
//! their tiles hide, and their models' measured solid share at eye height.
//!
//!     cargo run --release -p living-rules --example sight_census -- SEED.json [POSITIONS.json] [RADIUS_M] [MAP.ppm]
//!
//! POSITIONS.json is a list of `[x, y]` (people's positions from a live world, for example from
//! `SELECT x, y FROM body`); without it (or `-`) every walkable tile centre within the radius
//! counts. The eye is the arrival point (`host::arrival`, on the first town's square). MAP.ppm,
//! if given, is a top-down picture of the radius, 4 pixels a tile: walkable ground seen (light)
//! and hidden (dark), `Wall` (black), `Low` (orange), drops (blue), water, and the eye (red);
//! the height rule's beside it (`MAP-height.ppm`).

use living_rules::host;
use living_rules::land::{self, LandParams};
use living_rules::map::{Map, Terrain};

fn hidden(m: &Map, eye: (f32, f32), pts: &[(f32, f32)]) -> usize {
    pts.iter().filter(|&&q| !m.sight_clear(eye, q)).count()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let seed: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&args[1]).expect("seed")).expect("seed json");
    let p: LandParams = if seed["map"]["params"].is_null() { LandParams::default() } else { serde_json::from_value(seed["map"]["params"].clone()).expect("params") };
    let size = seed["map"]["size"].as_u64().expect("map.size") as u32;
    let radius: f32 = args.get(3).and_then(|r| r.parse().ok()).unwrap_or(48.0);
    let l = land::generate(seed["seed"].as_u64().expect("seed"), size, &p);
    let (after, _) = host::hosted_map(&l, &p);
    // The height rule: the same parameters with every model's eye measure left out.
    let mut tall = p.clone();
    for m in tall.settlements.buildings.models.iter_mut() {
        m.eye_cells = None;
    }
    let (height, _) = host::hosted_map(&l, &tall);
    let mut before = height.clone();
    for t in before.tiles.iter_mut() {
        if *t == Terrain::Drop as u8 || *t == Terrain::Low as u8 {
            *t = Terrain::Wall as u8;
        }
    }
    before.opaque = Default::default();
    let mut open = p.clone();
    open.sight.hides_m.insert("market_stall".into(), 0.0);
    let (stalls, _) = host::hosted_map(&l, &open);
    let eye = host::arrival(&l, &after);
    let set = host::arrival_settlement(&l).expect("a settlement");
    println!("eye {eye:?} on the settlement at {:?} ({}), radius {radius} m, eye height {} m", set.centre, set.style, p.sight.eye_m);
    let near = |c: (f32, f32)| ((c.0 - eye.0).powi(2) + (c.1 - eye.1).powi(2)).sqrt() <= radius;
    let model = |f: &Option<String>| f.as_deref().and_then(|f| p.settlements.buildings.model(f));
    let solid = |f: &Option<String>| model(f).and_then(|m| m.eye_solid).map_or("-".to_string(), |s| format!("{s:.2}"));
    let walls = |tiles: &[(i32, i32)]| tiles.iter().filter(|&&(x, y)| after.get(x, y) == Terrain::Wall).count();
    for lot in l.lots.iter().filter(|x| host::blocks(x.kind) && near(x.centre)) {
        let tiles = host::footprint_tiles(lot, host::margin_of(&l, &p, lot));
        println!("lot {:<14} {:>5.2} m, solid at the eye {:>4}, {:>3} of {:>3} tiles hide ({})", lot.kind.id(), lot.height_m, solid(&lot.model_file), walls(&tiles), tiles.len(), lot.model_file.as_deref().unwrap_or("no model"));
    }
    for pr in l.props.iter().filter(|x| x.kind.blocks() && near(x.centre)) {
        let tiles = host::prop_tiles(pr);
        println!("prop {:<13} {:>5.2} m, solid at the eye {:>4}, {:>3} of {:>3} tiles hide ({})", pr.kind.id(), pr.height_m, solid(&pr.model_file), walls(&tiles), tiles.len(), pr.model_file.as_deref().unwrap_or("no model"));
    }
    let pts: Vec<(f32, f32)> = match args.get(2).filter(|a| !a.is_empty() && a.as_str() != "-") {
        Some(path) => {
            let v: Vec<(f32, f32)> = serde_json::from_str(&std::fs::read_to_string(path).expect("positions")).expect("positions json");
            v.into_iter().filter(|&q| near(q) && q != eye).collect()
        }
        None => {
            let r = radius.ceil() as i32;
            let (ex, ey) = (eye.0.floor() as i32, eye.1.floor() as i32);
            (ey - r..=ey + r).flat_map(|y| (ex - r..=ex + r).map(move |x| (x, y))).filter(|&(x, y)| after.walkable(x, y)).map(|(x, y)| (x as f32 + 0.5, y as f32 + 0.5)).filter(|&q| near(q) && q != eye).collect()
        }
    };
    let (b, hr, a, s) = (hidden(&before, eye, &pts), hidden(&height, eye, &pts), hidden(&after, eye, &pts), hidden(&stalls, eye, &pts));
    let nearest_hidden = |m: &Map| pts.iter().filter(|&&q| !m.sight_clear(eye, q)).map(|q| ((q.0 - eye.0).powi(2) + (q.1 - eye.1).powi(2)).sqrt()).fold(f32::INFINITY, f32::min);
    println!("points within {radius} m: {}", pts.len());
    println!(
        "hidden before {b} (nearest {:.1} m), by height {hr} (nearest {:.1} m), after {a} (nearest {:.1} m), with open stalls {s} (nearest {:.1} m)",
        nearest_hidden(&before),
        nearest_hidden(&height),
        nearest_hidden(&after),
        nearest_hidden(&stalls)
    );
    if let Some(path) = args.get(4) {
        // This change's tiles at PATH, the height rule's beside it (`-height` before `.ppm`).
        let draw = |m: &Map, path: &str| {
            let r = radius.ceil() as i32;
            let (ex, ey) = (eye.0.floor() as i32, eye.1.floor() as i32);
            let side = (2 * r + 1) as usize;
            let k = 4usize;
            let mut img = vec![0u8; side * k * side * k * 3];
            for j in 0..side {
                for i in 0..side {
                    let (x, y) = (ex - r + i as i32, ey - r + j as i32);
                    let q = (x as f32 + 0.5, y as f32 + 0.5);
                    let c: [u8; 3] = match m.get(x, y) {
                        _ if (x, y) == (ex, ey) => [220, 30, 30],
                        Terrain::Wall | Terrain::Rock => [20, 20, 20],
                        Terrain::Low => [235, 150, 40],
                        Terrain::Drop => [60, 110, 220],
                        Terrain::Water => [90, 150, 200],
                        _ if !near(q) => [120, 120, 120],
                        _ if m.sight_clear(eye, q) => [240, 236, 220],
                        _ => [150, 140, 125],
                    };
                    for dy in 0..k {
                        for dx in 0..k {
                            let o = ((j * k + dy) * side * k + i * k + dx) * 3;
                            img[o..o + 3].copy_from_slice(&c);
                        }
                    }
                }
            }
            let mut out = format!("P6 {} {} 255\n", side * k, side * k).into_bytes();
            out.extend_from_slice(&img);
            std::fs::write(path, out).expect("write the map");
            println!("map written to {path}");
        };
        draw(&after, path);
        draw(&height, &path.replace(".ppm", "-height.ppm"));
    }
    // Every kind that blocks walking on the land: how many, their heights, and any without one.
    let mut kinds: std::collections::BTreeMap<String, (u32, f32, f32, u32)> = Default::default();
    let things = l.lots.iter().filter(|x| host::blocks(x.kind)).map(|x| (x.kind.id(), x.height_m)).chain(l.props.iter().filter(|x| x.kind.blocks()).map(|x| (x.kind.id(), x.height_m)));
    for (k, h) in things {
        let e = kinds.entry(k.to_string()).or_insert((0, f32::INFINITY, 0.0, 0));
        e.0 += 1;
        e.1 = e.1.min(h);
        e.2 = e.2.max(h);
        e.3 += (h <= 0.0) as u32;
    }
    for (k, (n, lo, hi, none)) in &kinds {
        println!("kind {k:<14} {n:>5} things, {lo:.2}-{hi:.2} m, {none} without a height, rises above the eye {}", if p.sight.hides(k, *lo) == p.sight.hides(k, *hi) { p.sight.hides(k, *hi).to_string() } else { "by model".into() });
    }
    let low = after.tiles.iter().filter(|&&t| t == Terrain::Low as u8).count();
    let drop = after.tiles.iter().filter(|&&t| t == Terrain::Drop as u8).count();
    println!("land: {low} low tiles, {drop} drop tiles; digests {:?}", host::digests(&l, &after));
}
