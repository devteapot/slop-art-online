//! Preview of a land seed (`"map": {"kind": "land", ...}`), such as a floor in `docs/FLOORS.md`:
//! generation, hosting and digest times with peak and retained memory, counts, and a top-down
//! map of the hosted tiles with buildings shaded by height, roads by class and the wall.
//!
//! `cargo run --release -p living-rules --example floor_preview --manifest-path living/Cargo.toml -- SEED_JSON [SIZE_M] [OUT_DIR] [SCALE]`
//!
//! SIZE_M overrides the seed's size (0 keeps it); SCALE (default 1) is metres per map pixel.
//! Writes `floor-SEED-SIZE.ppm` and prints the numbers (also to `floor-SEED-SIZE.txt`).

use living_rules::host;
use living_rules::land::{self, LandParams};
use living_rules::map::Terrain;
use living_rules::settle::{LotKind, RoadClass};
use std::alloc::{GlobalAlloc, Layout, System};
use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::sync::atomic::{AtomicUsize, Ordering::Relaxed};

#[path = "common/img.rs"]
mod img;
use img::Img;

struct Counting;
static CUR: AtomicUsize = AtomicUsize::new(0);
static PEAK: AtomicUsize = AtomicUsize::new(0);

unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, l: Layout) -> *mut u8 {
        let p = unsafe { System.alloc(l) };
        if !p.is_null() {
            let c = CUR.fetch_add(l.size(), Relaxed) + l.size();
            PEAK.fetch_max(c, Relaxed);
        }
        p
    }
    unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
        unsafe { System.dealloc(p, l) };
        CUR.fetch_sub(l.size(), Relaxed);
    }
    unsafe fn realloc(&self, p: *mut u8, l: Layout, new: usize) -> *mut u8 {
        let q = unsafe { System.realloc(p, l, new) };
        if !q.is_null() {
            if new >= l.size() {
                let c = CUR.fetch_add(new - l.size(), Relaxed) + new - l.size();
                PEAK.fetch_max(c, Relaxed);
            } else {
                CUR.fetch_sub(l.size() - new, Relaxed);
            }
        }
        q
    }
}

#[global_allocator]
static ALLOC: Counting = Counting;

const MB: f64 = 1024.0 * 1024.0;

fn mb(v: usize) -> f64 {
    v as f64 / MB
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let path = args.get(1).expect("seed json path");
    let seed_json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(path).expect("read seed")).expect("seed json");
    let map = &seed_json["map"];
    assert_eq!(map["kind"], "land", "not a land seed");
    let seed = seed_json["seed"].as_u64().unwrap_or(7);
    let size = args.get(2).and_then(|s| s.parse::<u32>().ok()).filter(|s| *s > 0).unwrap_or(map["size"].as_u64().unwrap_or(2048) as u32);
    let dir = args.get(3).cloned().unwrap_or_else(|| ".".into());
    let px: usize = args.get(4).and_then(|s| s.parse().ok()).unwrap_or(1).max(1);
    std::fs::create_dir_all(&dir).unwrap();
    let params: LandParams = if map["params"].is_null() { LandParams::default() } else { serde_json::from_value(map["params"].clone()).expect("map.params") };

    let base = CUR.load(Relaxed);
    PEAK.store(base, Relaxed);
    let t0 = std::time::Instant::now();
    // Staged, as the authority runs it: one line per step with its time and live heap.
    let mut g = land::Gen::new(seed, size, params.clone());
    let mut steps = String::new();
    while !g.is_done() {
        let (label, ts) = (g.label(), std::time::Instant::now());
        g.step();
        let _ = writeln!(steps, "  step {:>2}/{} {:<28} {:>7.3} s  live {:>5.0} MB  peak {:>5.0} MB", g.done(), g.steps(), label, ts.elapsed().as_secs_f64(), mb(CUR.load(Relaxed) - base), mb(PEAK.load(Relaxed) - base));
    }
    let land = g.into_land();
    let gen_s = t0.elapsed().as_secs_f64();
    let gen_peak = PEAK.load(Relaxed) - base;
    let kept = CUR.load(Relaxed) - base;

    PEAK.store(CUR.load(Relaxed), Relaxed);
    let before_host = CUR.load(Relaxed);
    let t1 = std::time::Instant::now();
    let (hosted, h) = host::hosted_map(&land, &params);
    let host_s = t1.elapsed().as_secs_f64();
    let t2 = std::time::Instant::now();
    let d = host::digests(&land, &hosted);
    let digest_s = t2.elapsed().as_secs_f64();
    let host_peak = PEAK.load(Relaxed) - before_host;

    let mut out = String::new();
    let _ = writeln!(out, "seed {seed} size {size} m ({})", path);
    let _ = writeln!(out, "generate {gen_s:.2} s, peak {:.0} MB, Land kept {:.0} MB", mb(gen_peak), mb(kept));
    out.push_str(&steps);
    let _ = writeln!(out, "hosted_map {host_s:.2} s, digests {digest_s:.2} s, their peak {:.0} MB", mb(host_peak));
    let _ = writeln!(out, "digests tiles {:016x} heights {:016x} layout {:016x}", d.tiles, d.heights, d.layout);
    let _ = writeln!(out, "blocked {} tiles, cut off {}", h.blocked_tiles, h.cut_off_tiles);
    let mut styles: BTreeMap<String, (usize, usize)> = BTreeMap::new();
    for s in &land.settlements {
        let e = styles.entry(format!("{}:{}", s.kind.id(), s.style)).or_default();
        e.0 += 1;
        e.1 += (s.lots.1 - s.lots.0) as usize;
    }
    let _ = writeln!(out, "settlements {} (kind:style count lots): {:?}", land.settlements.len(), styles);
    let mut kinds: BTreeMap<&str, usize> = BTreeMap::new();
    for l in &land.lots {
        *kinds.entry(l.kind.id()).or_default() += 1;
    }
    let tall = land.lots.iter().filter(|l| l.height_m >= 50.0).count();
    let tallest = land.lots.iter().map(|l| l.height_m).fold(0.0, f32::max);
    let _ = writeln!(out, "lots {} ({tall} at least 50 m, tallest {tallest:.0} m): {kinds:?}", land.lots.len());
    let mut classes: BTreeMap<String, (usize, f32)> = BTreeMap::new();
    for r in &land.roads {
        let e = classes.entry(format!("{:?}", r.class)).or_default();
        e.0 += 1;
        e.1 += r.length_m / 1000.0;
    }
    let _ = writeln!(out, "roads {} (class: count km): {classes:?}", land.roads.len());
    let mut props: BTreeMap<&str, usize> = BTreeMap::new();
    for p in &land.props {
        *props.entry(p.kind.id()).or_default() += 1;
    }
    let _ = writeln!(out, "props {}: {props:?}", land.props.len());
    let _ = writeln!(out, "rivers {}, dry beds {}, lakes {}, sites {}", land.rivers.len(), land.dry_beds.len(), land.lakes.len(), land.sites.len());
    let mut tiles = [0usize; 8];
    for &t in &hosted.tiles {
        tiles[t as usize] += 1;
    }
    let _ = writeln!(out, "hosted tiles by class (grass forest water sand rock dirt road wall): {tiles:?}");
    // Places worth a look: each style's first square, the middle of the widest roads, gates.
    let mut seen = Vec::new();
    for s in &land.settlements {
        if !seen.contains(&s.style) {
            seen.push(s.style.clone());
            let _ = writeln!(out, "spot {} square ({:.0}, {:.0})", s.style, s.plaza.centre.0, s.plaza.centre.1);
        }
        if let Some(w) = &s.wall {
            for g in w.gates.iter().take(3) {
                let _ = writeln!(out, "spot gate ({:.0}, {:.0}) out ({:.2}, {:.2})", g.at.0, g.at.1, g.out.0, g.out.1);
            }
        }
    }
    let widest = land.roads.iter().map(|r| r.width_m).fold(0.0, f32::max);
    for r in land.roads.iter().filter(|r| r.width_m >= widest - 0.01).take(3) {
        let m = r.points[r.points.len() / 2];
        let _ = writeln!(out, "spot road {:.0} m wide ({:.0}, {:.0})", r.width_m, m.0, m.1);
    }
    print!("{out}");

    // The map: one pixel per `px` metres.
    let w = size as usize / px;
    let mut img = Img::new(w, w);
    let tall_of = {
        let mut v = vec![0f32; (w * w) as usize];
        for l in &land.lots {
            if !host::blocks(l.kind) {
                continue;
            }
            for (x, y) in host::footprint_tiles(l, 0.15) {
                if x >= 0 && y >= 0 && (x as usize) < size as usize && (y as usize) < size as usize {
                    let k = (y as usize / px) * w + x as usize / px;
                    if k < v.len() {
                        v[k] = v[k].max(l.height_m);
                    }
                }
            }
        }
        v
    };
    for y in 0..w {
        for x in 0..w {
            let (tx, ty) = ((x * px) as i32, (y * px) as i32);
            let t = hosted.get(tx, ty);
            let ht = land.height(tx as f32 + 0.5, ty as f32 + 0.5);
            let c: [f32; 3] = match t {
                Terrain::Water => [40.0, 80.0, 130.0],
                Terrain::Road => [70.0, 70.0, 78.0],
                Terrain::Wall => {
                    let hb = tall_of[y * w + x];
                    if hb > 0.0 {
                        // Buildings: dark low, bright and magenta-tinted tall.
                        let f = (hb / 110.0).clamp(0.0, 1.0);
                        [lerp(120.0, 255.0, f), lerp(110.0, 90.0, f), lerp(105.0, 220.0, f)]
                    } else {
                        [30.0, 28.0, 26.0]
                    }
                }
                Terrain::Sand => [205.0, 185.0, 140.0],
                Terrain::Rock => [120.0, 110.0, 100.0],
                Terrain::Dirt => [170.0, 140.0, 105.0],
                Terrain::Forest => [95.0, 115.0, 70.0],
                Terrain::Grass => [160.0, 158.0, 110.0],
            };
            let shade = if t == Terrain::Water { 1.0 } else { (0.85 + ht / 400.0).clamp(0.8, 1.25) };
            img.set(x as i32, y as i32, [(c[0] * shade).min(255.0) as u8, (c[1] * shade).min(255.0) as u8, (c[2] * shade).min(255.0) as u8]);
        }
    }
    // Highways and arterials brighter, so the rings read.
    for r in &land.roads {
        if r.class != RoadClass::Trunk || r.width_m < 10.0 {
            continue;
        }
        for p in r.points.windows(2) {
            let n = ((p[1].0 - p[0].0).hypot(p[1].1 - p[0].1) / px as f32).ceil() as usize + 1;
            for i in 0..=n {
                let t = i as f32 / n as f32;
                let (x, y) = (lerp(p[0].0, p[1].0, t) / px as f32, lerp(p[0].1, p[1].1, t) / px as f32);
                for dy in -1..=1 {
                    for dx in -1..=1 {
                        img.set(x as i32 + dx, y as i32 + dy, [235, 200, 90]);
                    }
                }
            }
        }
    }
    for s in &land.settlements {
        let fs = if size >= 4096 { 3 } else { 2 };
        if s.style != "metro" && s.style != "slum" && s.style != "works" {
            let (x, y) = (s.centre.0 / px as f32, s.centre.1 / px as f32);
            img.text(x as i32 + 8, y as i32 - 4, &s.style, fs, [255, 255, 255]);
        }
    }
    let lamps = land.lots.iter().filter(|l| l.kind == LotKind::Lamp).count();
    let _ = writeln!(out, "lamps {lamps}");
    img.write(&format!("{dir}/floor-{seed}-{size}.ppm"));
    std::fs::write(format!("{dir}/floor-{seed}-{size}.txt"), out).unwrap();
}

fn lerp(a: f32, b: f32, t: f32) -> f32 {
    a + (b - a) * t
}
