fn main() {
    let seed: u64 = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(7);
    let m = living_rules::map::generate(seed);
    for y in (0..living_rules::map::MAP_H as i32).step_by(2) {
        let row: String = (0..living_rules::map::MAP_W as i32).map(|x| match m.get(x, y) as u8 { 0 => '.', 1 => 'T', 2 => '~', 3 => ':', 4 => '#', _ => ',' }).collect();
        println!("{row}");
    }
}
