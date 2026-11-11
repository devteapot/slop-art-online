//! Top-down preview of the realm generator at a given size: terrain colours with hill shading
//! from the shared ground heights, suggested sites, and a 100 m grid.
//! `cargo run --release -p living-rules --example realm_preview -- SEED SIZE_M OUT.ppm`

use living_rules::height::Ground;
use living_rules::map::Terrain;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let seed: u64 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(7);
    let size: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(1024);
    let out = args.get(3).cloned().unwrap_or_else(|| "realm.ppm".into());
    let t0 = std::time::Instant::now();
    let realm = living_rules::realm::generate(seed, size, size);
    let map = realm.to_map();
    let t1 = t0.elapsed();
    let ground = Ground::new(&map, seed);
    let t2 = t0.elapsed();
    let (mut lo, mut hi) = (f32::MAX, f32::MIN);
    let mut img = vec![0u8; (size * size * 3) as usize];
    for y in 0..size {
        for x in 0..size {
            let (fx, fy) = (x as f32 + 0.5, y as f32 + 0.5);
            let h = ground.height(fx, fy);
            lo = lo.min(h);
            hi = hi.max(h);
            // Light from the north-west.
            let shade = (1.0 - (ground.height(fx + 1.0, fy + 1.0) - ground.height(fx - 1.0, fy - 1.0)) * 0.35).clamp(0.55, 1.3);
            let c: [f32; 3] = match map.get(x as i32, y as i32) {
                Terrain::Grass => [118.0, 170.0, 84.0],
                Terrain::Forest => [52.0, 110.0, 58.0],
                Terrain::Water => [58.0, 110.0, 170.0],
                Terrain::Sand => [222.0, 204.0, 150.0],
                Terrain::Rock => [128.0, 122.0, 118.0],
                Terrain::Dirt => [150.0, 120.0, 84.0],
                Terrain::Road => [196.0, 176.0, 130.0],
                Terrain::Wall => [80.0, 70.0, 60.0],
                Terrain::Drop => [120.0, 104.0, 86.0],
            };
            let grid = x % 100 == 0 || y % 100 == 0;
            let i = ((y * size + x) * 3) as usize;
            for k in 0..3 {
                let v = c[k] * shade * if grid { 0.85 } else { 1.0 };
                img[i + k] = v.clamp(0.0, 255.0) as u8;
            }
        }
    }
    let mut mark = |(cx, cy): (f32, f32), col: [u8; 3]| {
        for dy in -6i32..=6 {
            for dx in -6i32..=6 {
                if dx * dx + dy * dy > 36 {
                    continue;
                }
                let (x, y) = (cx as i32 + dx, cy as i32 + dy);
                if x >= 0 && y >= 0 && (x as u32) < size && (y as u32) < size {
                    let i = ((y as u32 * size + x as u32) * 3) as usize;
                    img[i..i + 3].copy_from_slice(&col);
                }
            }
        }
    };
    realm.towns.iter().for_each(|&p| mark(p, [220, 40, 40]));
    realm.villages.iter().for_each(|&p| mark(p, [240, 160, 30]));
    realm.wilds.iter().for_each(|&p| mark(p, [150, 60, 200]));
    let mut f = format!("P6 {size} {size} 255\n").into_bytes();
    f.extend(img);
    std::fs::write(&out, f).unwrap();
    let count = |t: Terrain| map.tiles.iter().filter(|&&v| v == t as u8).count() as f32 / map.tiles.len() as f32 * 100.0;
    println!(
        "size {size} m: generate {:.1}s, heights {:.1}s; heights {lo:.0}..{hi:.0} m; water {:.0}%, forest {:.0}%, rock {:.0}%, grass {:.0}%; towns {}, villages {}, wilds {}",
        t1.as_secs_f32(),
        (t2 - t1).as_secs_f32(),
        count(Terrain::Water),
        count(Terrain::Forest),
        count(Terrain::Rock),
        count(Terrain::Grass),
        realm.towns.len(),
        realm.villages.len(),
        realm.wilds.len()
    );
}
