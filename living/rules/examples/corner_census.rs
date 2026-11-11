//! What the corner rule of fix-dealings (2026-11-11) changed in a live world's sight: the sight
//! line through a tile corner exactly is stopped only when both tiles beside the corner are
//! opaque, where the walk before broke the tie toward one side (so one of two people across one
//! wall's end saw the other and not back). Compares `Map::sight_clear` with that old walk over:
//!
//! - `people`: every ordered pair of bodies within 30 m of each other (their start positions);
//! - `near walls`: every walkable tile centre within 2 tiles of an opaque tile (walls, rock, shut
//!   gates), paired with every walkable tile centre within 12 m of it (beyond day sight, 11 m),
//!   both ways; tile centres are where bodies are placed and where exact corner crossings
//!   happen.
//!
//! For each it counts the lines that went from hidden to seen and from seen to hidden, and the
//! pairs seen one way and not the other under each rule.
//!
//!     cargo run --release -p living-rules --example corner_census -- DUMP.json
//!
//! DUMP.json: `{"w", "h", "chunks": [[id, "hex tiles"], ...], "shut": [tile index, ...],
//! "bodies": [[x, y], ...]}` from a world's `terrain_chunk`, shut `gate` rows and `body` rows.

use living_rules::map::Map;

/// The walk before fix-dealings: an exact corner tie stepped along y, sums of steps for t.
fn old_walk(m: &Map, a: (f32, f32), b: (f32, f32)) -> bool {
    let (mut tx, mut ty) = (a.0.floor() as i32, a.1.floor() as i32);
    let end = (b.0.floor() as i32, b.1.floor() as i32);
    let (dx, dy) = (b.0 - a.0, b.1 - a.1);
    let (sx, sy) = (dx.signum() as i32, dy.signum() as i32);
    let next = |p: f32, d: f32, t: i32| if d > 0.0 { (t as f32 + 1.0 - p) / d } else if d < 0.0 { (t as f32 - p) / d } else { f32::INFINITY };
    let (mut tmx, mut tmy) = (next(a.0, dx, tx), next(a.1, dy, ty));
    let (tdx, tdy) = (if dx != 0.0 { 1.0 / dx.abs() } else { f32::INFINITY }, if dy != 0.0 { 1.0 / dy.abs() } else { f32::INFINITY });
    let mut guard = (end.0 - tx).abs() + (end.1 - ty).abs() + 2;
    while (tx, ty) != end && guard > 0 {
        guard -= 1;
        if tmx < tmy {
            tx += sx;
            tmx += tdx;
        } else {
            ty += sy;
            tmy += tdy;
        }
        if (tx, ty) != end && !m.passable_missile(tx as f32 + 0.5, ty as f32 + 0.5) {
            return false;
        }
    }
    true
}

#[derive(Default)]
struct Tally {
    lines: u64,
    seen_old: u64,
    seen_new: u64,
    hidden_to_seen: u64,
    seen_to_hidden: u64,
    one_way_old: u64,
    one_way_new: u64,
}

impl Tally {
    fn pair(&mut self, m: &Map, a: (f32, f32), b: (f32, f32)) {
        let (o_ab, o_ba) = (old_walk(m, a, b), old_walk(m, b, a));
        let (n_ab, n_ba) = (m.sight_clear(a, b), m.sight_clear(b, a));
        for (o, n) in [(o_ab, n_ab), (o_ba, n_ba)] {
            self.lines += 1;
            self.seen_old += o as u64;
            self.seen_new += n as u64;
            self.hidden_to_seen += (!o && n) as u64;
            self.seen_to_hidden += (o && !n) as u64;
        }
        self.one_way_old += (o_ab != o_ba) as u64;
        self.one_way_new += (n_ab != n_ba) as u64;
    }
    fn print(&self, name: &str) {
        println!(
            "{name}: {} lines ({} pairs both ways); seen {} before, {} now; hidden -> seen {}, seen -> hidden {}; pairs seen one way only: {} before, {} now",
            self.lines,
            self.lines / 2,
            self.seen_old,
            self.seen_new,
            self.hidden_to_seen,
            self.seen_to_hidden,
            self.one_way_old,
            self.one_way_new
        );
    }
}

fn main() {
    let path = std::env::args().nth(1).expect("DUMP.json");
    let d: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&path).expect("dump")).expect("dump json");
    let (w, h) = (d["w"].as_u64().unwrap() as u32, d["h"].as_u64().unwrap() as u32);
    let chunks = d["chunks"].as_array().unwrap().iter().map(|c| {
        let hex = c[1].as_str().unwrap().trim_start_matches("0x");
        let bytes = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap()).collect();
        (c[0].as_u64().unwrap() as u32, bytes)
    });
    let mut m = Map::from_chunks(w, h, chunks);
    for s in d["shut"].as_array().unwrap() {
        m.blocked.insert(s.as_u64().unwrap() as u32);
    }
    let bodies: Vec<(f32, f32)> = d["bodies"].as_array().unwrap().iter().map(|b| (b[0].as_f64().unwrap() as f32, b[1].as_f64().unwrap() as f32)).collect();

    let mut people = Tally::default();
    for (i, &a) in bodies.iter().enumerate() {
        for &b in &bodies[i + 1..] {
            if (a.0 - b.0).hypot(a.1 - b.1) <= 30.0 {
                people.pair(&m, a, b);
            }
        }
    }
    people.print(&format!("people ({} bodies, pairs within 30 m)", bodies.len()));

    let opaque = |x: i32, y: i32| x < 0 || y < 0 || x >= w as i32 || y >= h as i32 || !m.passable_missile(x as f32 + 0.5, y as f32 + 0.5);
    let walk = |x: i32, y: i32| x >= 0 && y >= 0 && x < w as i32 && y < h as i32 && m.walkable(x, y);
    let mut near = Tally::default();
    let mut eyes = 0u64;
    for y in 0..h as i32 {
        for x in 0..w as i32 {
            if !walk(x, y) || !(-2..=2).any(|dy| (-2..=2).any(|dx| opaque(x + dx, y + dy))) {
                continue;
            }
            eyes += 1;
            let a = (x as f32 + 0.5, y as f32 + 0.5);
            // Each unordered pair once: targets after the eye in reading order.
            for ty in y..=(y + 12).min(h as i32 - 1) {
                for tx in (x - 12).max(0)..=(x + 12).min(w as i32 - 1) {
                    if (ty == y && tx <= x) || !walk(tx, ty) {
                        continue;
                    }
                    let b = (tx as f32 + 0.5, ty as f32 + 0.5);
                    if (a.0 - b.0).hypot(a.1 - b.1) <= 12.0 {
                        near.pair(&m, a, b);
                    }
                }
            }
        }
    }
    near.print(&format!("near walls ({eyes} eye tiles within 2 of an opaque tile, targets within 12 m)"));
}
