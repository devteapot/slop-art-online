//! ASCII preview of a settlement layout: `cargo run -p living-rules --example city_preview -- [households] [radius] [walled]`
fn main() {
    use living_rules::map::{Map, Terrain};
    let a: Vec<String> = std::env::args().collect();
    let n: usize = a.get(1).and_then(|s| s.parse().ok()).unwrap_or(10);
    let r: i32 = a.get(2).and_then(|s| s.parse().ok()).unwrap_or(18);
    let walled = a.get(3).map_or(true, |s| s != "open");
    let mut map = Map { w: 64, h: 64, tiles: vec![Terrain::Grass as u8; 64 * 64], blocked: Default::default() };
    let l = living_rules::city::lay_out(&mut map, (32.5, 32.5), n, r, walled);
    for y in 0..64 {
        let line: String = (0..64)
            .map(|x| {
                let c = (x as f32 + 0.5, y as f32 + 0.5);
                if l.houses.contains(&c) { 'H' } else if l.gates.contains(&(x, y)) { 'G' } else if l.fields.contains(&c) { '*' } else {
                    match map.get(x, y) { Terrain::Road => '=', Terrain::Wall => '#', _ => '.' }
                }
            })
            .collect();
        println!("{line}");
    }
    let d: Vec<i32> = l.houses.iter().map(|h| ((h.0 - 32.5).abs().max((h.1 - 32.5).abs())) as i32).collect();
    println!("houses {} at ring distances {:?}", l.houses.len(), d);
}
