fn main() {
    let seed: u64 = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(11);
    let r = living_rules::realm::generate(seed, 256, 256);
    for y in (0..256i32).step_by(4) {
        let row: String = (0..256i32).step_by(2).map(|x| {
            if r.towns.iter().any(|t| (t.0 as i32 - x).abs() < 3 && (t.1 as i32 - y).abs() < 3) { return 'T' }
            if r.wilds.iter().any(|t| (t.0 as i32 - x).abs() < 3 && (t.1 as i32 - y).abs() < 3) { return 'W' }
            match r.tiles[(y * 256 + x) as usize] { 0 => '.', 1 => 'f', 2 => '~', 3 => ':', 4 => '#', _ => ',' }
        }).collect();
        println!("{row}");
    }
    println!("towns {:?}\nwilds {:?}", r.towns, r.wilds);
}
