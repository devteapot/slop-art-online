//! `cargo run --release -p living-rules --example path_probe -- <seed> <w> <x0> <y0> <x1> <y1> [budget]`
fn main() {
    let a: Vec<f32> = std::env::args().skip(1).map(|s| s.parse().unwrap()).collect();
    let m = living_rules::realm::generate(a[0] as u64, a[1] as u32, a[1] as u32).to_map();
    let budget = a.get(6).copied().unwrap_or(6000.0) as usize;
    let t = std::time::Instant::now();
    let p = m.path((a[2], a[3]), (a[4], a[5]), budget);
    println!("budget {budget}: {} waypoints in {:?}", p.map(|p| p.len() as i64).unwrap_or(-1), t.elapsed());
}
