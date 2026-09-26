//! Preview a realm: `cargo run -p living-rules --example realm_preview -- <seed> [w] [h]`
//! Prints a downsampled terrain map (T = town site, W = wild site) and site coordinates.

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let seed: u64 = a.get(1).and_then(|s| s.parse().ok()).unwrap_or(1);
    let w: u32 = a.get(2).and_then(|s| s.parse().ok()).unwrap_or(256);
    let h: u32 = a.get(3).and_then(|s| s.parse().ok()).unwrap_or(w);
    let r = living_rules::realm::generate(seed, w, h);
    let step = (w / 96).max(1) as usize * 2;
    let glyph = |t: u8| match t {
        0 => '.',
        1 => '♣',
        2 => '~',
        3 => '_',
        4 => '^',
        5 => ',',
        _ => '?',
    };
    for y in (0..h as usize).step_by(step) {
        let mut line = String::new();
        for x in (0..w as usize).step_by((step / 2).max(1)) {
            let near = |p: &(f32, f32)| (p.0 as usize / (step / 2).max(1) == x / (step / 2).max(1)) && (p.1 as usize / step == y / step);
            if r.towns.iter().any(near) {
                line.push('T');
            } else if r.wilds.iter().any(near) {
                line.push('W');
            } else {
                line.push(glyph(r.tiles[y * w as usize + x]));
            }
        }
        println!("{line}");
    }
    let mut counts = [0usize; 8];
    for t in &r.tiles {
        counts[*t as usize % 8] += 1;
    }
    println!("tiles by kind: {counts:?}");
    println!("towns: {:?}\nwilds: {:?}", r.towns, r.wilds);
}
