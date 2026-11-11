//! Preview of the km-scale land generator (`living_rules::land`): a top-down map with hill
//! shading, region colours, rivers and lakes, sites at their real radius, 50 m contours, a
//! 100 m grid, a scale bar and labels; an elevation cross-section at true scale through the
//! main summit; and a legend with the measured numbers.
//!
//! `cargo run --release -p living-rules --example land_preview --manifest-path living/Cargo.toml -- SEED SIZE_M OUT_DIR`
//!
//! Writes `land-SEED-SIZE.ppm`, `section-SEED-SIZE.ppm` and `legend-SEED-SIZE.txt`.

use living_rules::land::{self, Land, RegionKind, SiteKind};
use living_rules::map::Terrain;
use std::alloc::{GlobalAlloc, Layout, System};
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

const MB: f32 = 1024.0 * 1024.0;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let seed: u64 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(7);
    let size: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(2048);
    let dir = args.get(3).cloned().unwrap_or_else(|| ".".into());
    std::fs::create_dir_all(&dir).unwrap();

    let before = CUR.load(Relaxed);
    PEAK.store(before, Relaxed);
    let t0 = std::time::Instant::now();
    let land = land::generate_default(seed, size);
    let gen_s = t0.elapsed().as_secs_f32();
    let peak = (PEAK.load(Relaxed) - before) as f32 / MB;
    let kept = (CUR.load(Relaxed) - before) as f32 / MB;

    let w = size as usize;
    let t1 = std::time::Instant::now();
    let heights: Vec<f32> = (0..w * w).map(|k| land.height((k % w) as f32 + 0.5, (k / w) as f32 + 0.5)).collect();
    let height_ns = t1.elapsed().as_secs_f64() * 1e9 / (w * w) as f64;

    let mut img = Img::new(w, w);
    draw_map(&land, &heights, &mut img);
    let section = section_line(&land);
    draw_line(&mut img, section.0, section.1, [255, 255, 255]);
    img.text(section.0 .0 as i32 + 6, section.0 .1 as i32 + 6, "A", 3, [255, 255, 255]);
    img.text(section.1 .0 as i32 + 6, section.1 .1 as i32 + 6, "B", 3, [255, 255, 255]);
    draw_overlays(&land, &mut img);
    img.write(&format!("{dir}/land-{seed}-{size}.ppm"));
    draw_section(&land, section, &format!("{dir}/section-{seed}-{size}.ppm"));

    let legend = legend(&land, &heights, gen_s, peak, kept, height_ns);
    std::fs::write(format!("{dir}/legend-{seed}-{size}.txt"), &legend).unwrap();
    print!("{legend}");
}

fn region_colour(k: RegionKind) -> [f32; 3] {
    match k {
        RegionKind::Sea => [60.0, 110.0, 160.0],
        RegionKind::Beach => [170.0, 190.0, 120.0],
        RegionKind::Meadow => [140.0, 185.0, 90.0],
        RegionKind::Forest => [70.0, 130.0, 65.0],
        RegionKind::OldForest => [38.0, 92.0, 52.0],
        RegionKind::SpiritGrove => [70.0, 80.0, 150.0],
        RegionKind::Wetland => [95.0, 150.0, 120.0],
        RegionKind::Highland => [150.0, 150.0, 105.0],
        RegionKind::Peaks => [160.0, 155.0, 150.0],
    }
}

fn tile_colour(t: Terrain, kind: RegionKind) -> [f32; 3] {
    let k = region_colour(kind);
    let darker = |c: [f32; 3], f: f32| [c[0] * f, c[1] * f, c[2] * f];
    match t {
        Terrain::Grass => k,
        Terrain::Forest => match kind {
            RegionKind::SpiritGrove => [55.0, 50.0, 120.0],
            RegionKind::OldForest => [28.0, 70.0, 40.0],
            _ => darker([k[0] * 0.6 + 20.0, k[1] * 0.7 + 10.0, k[2] * 0.6 + 10.0], 0.85),
        },
        Terrain::Sand => [222.0, 206.0, 156.0],
        Terrain::Rock => [125.0, 120.0, 118.0],
        Terrain::Dirt => [150.0, 125.0, 92.0],
        Terrain::Road => [196.0, 176.0, 130.0],
        Terrain::Wall => [80.0, 70.0, 60.0],
        Terrain::Drop => [120.0, 104.0, 86.0],
        Terrain::Water => [60.0, 110.0, 170.0],
    }
}

fn site_colour(k: SiteKind) -> [u8; 3] {
    match k {
        SiteKind::Town => [230, 50, 40],
        SiteKind::Village => [250, 160, 30],
        SiteKind::Giants => [200, 60, 220],
        SiteKind::SmallFolk => [255, 240, 80],
        SiteKind::Cave => [20, 20, 20],
    }
}

fn draw_map(land: &Land, h: &[f32], img: &mut Img) {
    let w = img.w;
    let at = |x: usize, y: usize| h[y.min(w - 1) * w + x.min(w - 1)];
    let light = {
        let l = [-1.0f32, -1.0, 1.4];
        let n = (l[0] * l[0] + l[1] * l[1] + l[2] * l[2]).sqrt();
        [l[0] / n, l[1] / n, l[2] / n]
    };
    for y in 0..w {
        for x in 0..w {
            let k = y * w + x;
            let (fx, fy) = (x as f32 + 0.5, y as f32 + 0.5);
            let t = land.map.get(x as i32, y as i32);
            let kind = land.kind_at(fx, fy);
            let dx = (at(x + 1, y) - at(x.saturating_sub(1), y)) / 2.0;
            let dy = (at(x, y + 1) - at(x, y.saturating_sub(1))) / 2.0;
            let nl = (dx * dx + dy * dy + 1.0).sqrt();
            let dot = (-dx * light[0] - dy * light[1] + light[2]) / nl;
            let shade = (0.5 + 0.5 * dot / light[2]).clamp(0.45, 1.3);
            let mut c = if t == Terrain::Water {
                let depth = (land.water_level(fx, fy) - h[k]).max(0.0);
                let f = (depth / 6.0).min(1.0);
                [lerp(110.0, 30.0, f), lerp(170.0, 70.0, f), lerp(215.0, 140.0, f)]
            } else {
                let c = tile_colour(t, kind);
                // Higher ground pales a little.
                let hi = (h[k] / 500.0).clamp(0.0, 1.0) * 0.35;
                let c = [lerp(c[0], 235.0, hi), lerp(c[1], 235.0, hi), lerp(c[2], 230.0, hi)];
                [c[0] * shade, c[1] * shade, c[2] * shade]
            };
            if t != Terrain::Water {
                let band = |v: f32| (v / 50.0).floor();
                if band(h[k]) != band(at(x + 1, y)) || band(h[k]) != band(at(x, y + 1)) {
                    c = [c[0] * 0.7, c[1] * 0.7, c[2] * 0.7];
                }
            }
            let g = if x % 500 == 0 || y % 500 == 0 { 0.72 } else if x % 100 == 0 || y % 100 == 0 { 0.88 } else { 1.0 };
            img.set(x as i32, y as i32, [(c[0] * g).clamp(0.0, 255.0) as u8, (c[1] * g).clamp(0.0, 255.0) as u8, (c[2] * g).clamp(0.0, 255.0) as u8]);
        }
    }
}

fn draw_overlays(land: &Land, img: &mut Img) {
    let fs = if land.size >= 2048 { 3 } else { 2 };
    // Region labels (land regions only), small.
    for r in &land.regions {
        if r.kind == RegionKind::Sea || r.land_m2 < 20_000.0 {
            continue;
        }
        let name = r.kind.id().replace('_', " ").to_uppercase();
        let (x, y) = (r.centre.0 as i32, r.centre.1 as i32);
        let tw = img.text_width(&name, fs - 1);
        img.text(x - tw / 2, y, &name, fs - 1, [255, 255, 245]);
    }
    for l in &land.lakes {
        let s = format!("LAKE {:.0} M", l.across_m);
        let tw = img.text_width(&s, fs - 1);
        img.text(l.centre.0 as i32 - tw / 2, l.centre.1 as i32 - 4, &s, fs - 1, [210, 235, 255]);
    }
    for (i, g) in land.ranges.iter().enumerate() {
        let (x, y, h) = g.summit;
        let (x, y) = (x as i32, y as i32);
        for d in 0..14 {
            for e in -d / 2..=d / 2 {
                img.set(x + e, y - 14 + d, [30, 20, 20]);
            }
        }
        img.text(x + 10, y - 12, &format!("{} {:.0} M", if i == 0 { "PEAK" } else { "PEAK 2" }, h), fs, [255, 255, 255]);
    }
    let mut count = std::collections::HashMap::new();
    for s in &land.sites {
        let c = site_colour(s.kind);
        let r = s.radius_m.max(6.0);
        let steps = (r * 8.0) as i32;
        for a in 0..steps {
            let t = a as f32 / steps as f32 * std::f32::consts::TAU;
            for dr in [-1.0, 0.0, 1.0] {
                img.set((s.x + (r + dr) * t.cos()) as i32, (s.y + (r + dr) * t.sin()) as i32, c);
            }
        }
        let n = count.entry(s.kind).or_insert(0);
        *n += 1;
        let name = match s.kind {
            SiteKind::Town => "TOWN".to_string(),
            SiteKind::Village => format!("VILLAGE {n}"),
            SiteKind::Giants => "GIANTS".to_string(),
            SiteKind::SmallFolk => "SMALL FOLK".to_string(),
            SiteKind::Cave => format!("CAVE {n}"),
        };
        let tw = img.text_width(&name, fs);
        img.text(s.x as i32 - tw / 2, (s.y - r) as i32 - 9 * fs as i32, &name, fs, c);
    }
    // Scale bar: 500 m with 100 m ticks.
    let (bx, by) = (40, img.h as i32 - 60);
    for x in 0..=500 {
        for t in 0..6 {
            img.set(bx + x, by + t, if (x / 100) % 2 == 0 { [255, 255, 255] } else { [20, 20, 20] });
        }
    }
    img.text(bx, by - 26, "0", fs, [255, 255, 255]);
    img.text(bx + 500 - img.text_width("500 M", fs), by - 26, "500 M", fs, [255, 255, 255]);
    img.text(bx, by + 14, &format!("SEED {} - {} M - GRID 100 M - CONTOURS 50 M", land.seed, land.size), fs - 1, [255, 255, 255]);
}

/// A line through the main summit across the range, clipped to the map.
fn section_line(land: &Land) -> ((f32, f32), (f32, f32)) {
    let g = &land.ranges[0];
    let (sx, sy, _) = g.summit;
    let mut best = (f32::MAX, (1.0, 0.0));
    for p in g.spine.windows(2) {
        let (mx, my) = ((p[0].0 + p[1].0) / 2.0, (p[0].1 + p[1].1) / 2.0);
        let d = (mx - sx).hypot(my - sy);
        if d < best.0 {
            let (dx, dy) = (p[1].0 - p[0].0, p[1].1 - p[0].1);
            let l = dx.hypot(dy);
            best = (d, (dx / l, dy / l));
        }
    }
    let (nx, ny) = (-best.1 .1, best.1 .0);
    let s = land.size as f32 - 1.0;
    let reach = |sign: f32| {
        let mut t = 0.0;
        while t < 5000.0 {
            let (x, y) = (sx + sign * nx * (t + 1.0), sy + sign * ny * (t + 1.0));
            if x < 0.0 || y < 0.0 || x > s || y > s {
                break;
            }
            t += 1.0;
        }
        (sx + sign * nx * t, sy + sign * ny * t)
    };
    (reach(-1.0), reach(1.0))
}

fn draw_line(img: &mut Img, a: (f32, f32), b: (f32, f32), c: [u8; 3]) {
    let len = (b.0 - a.0).hypot(b.1 - a.1);
    for i in 0..len as i32 {
        if (i / 12) % 2 == 0 {
            let t = i as f32 / len;
            let (x, y) = (lerp(a.0, b.0, t), lerp(a.1, b.1, t));
            img.set(x as i32, y as i32, c);
            img.set(x as i32 + 1, y as i32, c);
        }
    }
}

fn draw_section(land: &Land, (a, b): ((f32, f32), (f32, f32)), path: &str) {
    let len = (b.0 - a.0).hypot(b.1 - a.1);
    let wpx = 2000usize;
    let ppm = wpx as f32 / len;
    let samples: Vec<(f32, f32, f32, Terrain, RegionKind)> = (0..wpx)
        .map(|i| {
            let t = (i as f32 + 0.5) / wpx as f32;
            let (x, y) = (lerp(a.0, b.0, t), lerp(a.1, b.1, t));
            (x, y, land.height(x, y), land.map.at(x, y), land.kind_at(x, y))
        })
        .collect();
    let top = samples.iter().map(|s| s.2).fold(0.0, f32::max) + 60.0;
    let bottom = -30.0;
    let (ml, mt, mb) = (90usize, 50usize, 50usize);
    let hpx = ((top - bottom) * ppm) as usize + mt + mb;
    let mut img = Img::new(wpx + ml + 20, hpx);
    img.fill([235, 240, 248]);
    let ypx = |h: f32| (mt as f32 + (top - h) * ppm) as i32;
    // Height grid every 100 m.
    let mut h = 0.0;
    while h < top {
        for x in ml..ml + wpx {
            img.set(x as i32, ypx(h), [190, 195, 210]);
        }
        img.text(8, ypx(h) - 10, &format!("{h:.0} M"), 2, [60, 60, 80]);
        h += 100.0;
    }
    for (i, s) in samples.iter().enumerate() {
        let x = (ml + i) as i32;
        let gy = ypx(s.2);
        if s.3 == Terrain::Water {
            let wy = ypx(land.water_level(s.0, s.1));
            for y in wy..gy {
                img.set(x, y, [70, 130, 200]);
            }
        }
        let c = tile_colour(s.3, s.4);
        for y in gy..ypx(bottom) {
            let f = if y < gy + 3 { 1.0 } else { 0.75 };
            img.set(x, y, [(c[0] * f) as u8, (c[1] * f) as u8, (c[2] * f) as u8]);
        }
        for site in &land.sites {
            if (s.0 - site.x).hypot(s.1 - site.y) < site.radius_m.max(6.0) {
                for y in gy - 14..gy - 8 {
                    img.set(x, y, site_colour(site.kind));
                }
            }
        }
    }
    // Distance ticks every 250 m.
    let mut d = 0.0;
    while d <= len {
        let x = ml as i32 + (d * ppm) as i32;
        for y in ypx(bottom)..ypx(bottom) + 8 {
            img.set(x, y, [40, 40, 40]);
        }
        img.text(x - 10, ypx(bottom) + 12, &format!("{d:.0}"), 2, [40, 40, 40]);
        d += 250.0;
    }
    img.text(ml as i32, 12, &format!("A TO B THROUGH THE MAIN SUMMIT, {len:.0} M, TRUE SCALE (1 PX = {:.2} M BOTH WAYS)", 1.0 / ppm), 2, [30, 30, 50]);
    img.write(path);
}

fn legend(land: &Land, h: &[f32], gen_s: f32, peak: f32, kept: f32, height_ns: f64) -> String {
    let mut o = String::new();
    let tiles = &land.map.tiles;
    let pct = |t: Terrain| tiles.iter().filter(|&&v| v == t as u8).count() as f32 / tiles.len() as f32 * 100.0;
    let (lo, hi) = h.iter().fold((f32::MAX, f32::MIN), |a, &v| (a.0.min(v), a.1.max(v)));
    let walk = tiles.iter().filter(|&&v| Terrain::from_u8(v).walkable()).count();
    writeln!(o, "seed {} size {} m ({} tiles, {} chunks of 16 x 16)", land.seed, land.size, tiles.len(), land.map.chunks().count()).unwrap();
    writeln!(o, "generate {gen_s:.2} s, peak heap {peak:.0} MB, retained {kept:.0} MB; height() {height_ns:.0} ns per call").unwrap();
    writeln!(o, "height {lo:.1} .. {hi:.1} m").unwrap();
    for (i, g) in land.ranges.iter().enumerate() {
        writeln!(o, "range {}: summit {:.0} m at ({:.0}, {:.0}), half width {:.0} m", i + 1, g.summit.2, g.summit.0, g.summit.1, g.half_width_m).unwrap();
    }
    writeln!(
        o,
        "tiles: water {:.1}%, grass {:.1}%, forest {:.1}%, rock {:.1}%, dirt {:.1}%, sand {:.1}%; walkable {:.2} km2",
        pct(Terrain::Water),
        pct(Terrain::Grass),
        pct(Terrain::Forest),
        pct(Terrain::Rock),
        pct(Terrain::Dirt),
        pct(Terrain::Sand),
        walk as f32 / 1e6
    )
    .unwrap();
    writeln!(o, "connectivity: opened {} blocked tiles, closed {} pockets", land.opened_tiles, land.closed_pockets).unwrap();
    let land_regions: Vec<_> = land.regions.iter().filter(|r| r.kind != RegionKind::Sea).collect();
    let mut across: Vec<f32> = land_regions.iter().map(|r| 2.0 * (r.area_m2 / std::f32::consts::PI).sqrt()).collect();
    across.sort_by(f32::total_cmp);
    writeln!(o, "regions: {} land of {}; across (equal-area circle) {:.0} / {:.0} / {:.0} m (min / median / max)", land_regions.len(), land.regions.len(), across[0], across[across.len() / 2], across[across.len() - 1]).unwrap();
    for k in RegionKind::ALL {
        let rs: Vec<_> = land.regions.iter().filter(|r| r.kind == k).collect();
        if rs.is_empty() {
            continue;
        }
        let area: f32 = rs.iter().map(|r| r.land_m2).sum();
        writeln!(o, "  {:13} {:2} regions, land {:.2} km2, env {}", k.id(), rs.len(), area / 1e6, k.env().unwrap_or("-")).unwrap();
    }
    writeln!(o, "rivers: {}", land.rivers.len()).unwrap();
    for (i, r) in land.rivers.iter().enumerate() {
        let wmax = r.width_m.iter().cloned().fold(0.0, f32::max);
        writeln!(o, "  river {}: {:.0} m long from {:.0} m, up to {:.1} m wide, {} fords", i + 1, r.length_m, r.source_m, wmax, r.fords.len()).unwrap();
    }
    writeln!(o, "lakes: {}", land.lakes.len()).unwrap();
    for l in &land.lakes {
        writeln!(o, "  lake at ({:.0}, {:.0}): {:.0} m across, level {:.1} m", l.centre.0, l.centre.1, l.across_m, l.level_m).unwrap();
    }
    writeln!(o, "sites: {}", land.sites.len()).unwrap();
    for s in &land.sites {
        writeln!(o, "  {:10} at ({:4.0}, {:4.0}) radius {:3.0} m, ground {:5.1} m, scale {:.2}, in {}, env {}", s.kind.id(), s.x, s.y, s.radius_m, s.ground_m, s.scale, s.region.id(), s.kind.env()).unwrap();
    }
    o
}

fn lerp(a: f32, b: f32, t: f32) -> f32 {
    a + (b - a) * t
}
