//! Print the realm terrain around a point: `cargo run -p living-rules --example tile_at -- <seed> <w> <x> <y> [r]`
fn main() {
    let a: Vec<f32> = std::env::args().skip(1).map(|s| s.parse().unwrap()).collect();
    let (seed, w, x, y) = (a[0] as u64, a[1] as u32, a[2] as i32, a[3] as i32);
    let r = a.get(4).copied().unwrap_or(6.0) as i32;
    let m = living_rules::realm::generate(seed, w, w).to_map();
    for yy in y - r..=y + r {
        let line: String = (x - r..=x + r).map(|xx| if xx == x && yy == y { '@' } else { match m.get(xx, yy) as u8 { 0 => '.', 1 => 'T', 2 => '~', 3 => '_', 4 => '^', _ => ',' } }).collect();
        println!("{yy:4} {line}");
    }
}
