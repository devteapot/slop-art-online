//! Preview of the settlement planner (`living_rules::settle`): the island's road network, and a
//! close-up of every settlement with its roads, plaza, wall and gates, lots coloured by kind
//! with a mark on each front, gardens, fields, contours and props (stairs orange, retaining
//! walls dark brown, kerbs pale grey, the rest small marks by kind); plus a legend with counts,
//! timings and checks.
//!
//! `cargo run --release -p living-rules --example town_preview --manifest-path living/Cargo.toml -- SEED SIZE_M OUT_DIR`
//!
//! Writes `roads-SEED.ppm`, `town-SEED-<n>-<site>.ppm` (and a core close-up of each town) and
//! `towns-SEED.txt`.

#[path = "common/img.rs"]
mod img;

use img::Img;
use living_rules::land::{self, Land, SiteKind};
use living_rules::map::Terrain;
use living_rules::settle::{LotKind, PropKind, RoadClass, Settlement};
use std::fmt::Write as _;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let seed: u64 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(7);
    let size: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(2048);
    let dir = args.get(3).cloned().unwrap_or_else(|| ".".into());
    std::fs::create_dir_all(&dir).unwrap();

    let t0 = std::time::Instant::now();
    let land = land::generate_default(seed, size);
    let gen_s = t0.elapsed().as_secs_f32();
    let mut p = land::LandParams::default();
    p.settlements.styles.clear();
    p.settlements.roads.landing_m = 0.0;
    p.settlements.roads.cave_path_m = 0.0;
    let t1 = std::time::Instant::now();
    let _bare = land::generate(seed, size, &p);
    let bare_s = t1.elapsed().as_secs_f32();

    // height() cost inside settlements, and over the whole map.
    let mut probe = 0.0;
    let t2 = std::time::Instant::now();
    let mut n = 0u32;
    for s in &land.settlements {
        let r = s.radius_m;
        let mut y = s.centre.1 - r;
        while y < s.centre.1 + r {
            let mut x = s.centre.0 - r;
            while x < s.centre.0 + r {
                probe += land.height(x, y);
                n += 1;
                x += 0.7 * s.scale.max(0.3);
            }
            y += 0.7 * s.scale.max(0.3);
        }
    }
    let town_ns = t2.elapsed().as_secs_f64() * 1e9 / n.max(1) as f64;
    let t3 = std::time::Instant::now();
    let w = size as usize;
    for k in (0..w * w).step_by(7) {
        probe += land.height((k % w) as f32 + 0.5, (k / w) as f32 + 0.5);
    }
    let map_ns = t3.elapsed().as_secs_f64() * 1e9 / (w * w / 7) as f64;
    std::hint::black_box(probe);

    island(&land, &format!("{dir}/roads-{seed}.ppm"));
    for (i, s) in land.settlements.iter().enumerate() {
        let half = s.radius_m + land_style_outskirts(s) + 12.0 * s.scale.max(0.5);
        let px = (1300.0 / (2.0 * half)).clamp(1.0, 16.0);
        let id = land.sites[s.site as usize].id();
        close_up(&land, s, s.centre, half, px, &format!("{dir}/town-{seed}-{i}-{id}.ppm"));
        if s.kind == SiteKind::Town {
            close_up(&land, s, s.centre, 75.0, 8.0, &format!("{dir}/town-{seed}-{i}-{id}-core.ppm"));
        }
    }
    let legend = legend(&land, gen_s, bare_s, town_ns, map_ns);
    std::fs::write(format!("{dir}/towns-{seed}.txt"), &legend).unwrap();
    print!("{legend}");
}

fn land_style_outskirts(s: &Settlement) -> f32 {
    land::LandParams::default().settlements.style_for(s.kind, &s.style).map_or(70.0, |st| st.outskirts_m)
}

fn prop_colour(k: PropKind) -> [u8; 3] {
    match k {
        PropKind::Stairs => [255, 140, 20],
        PropKind::RetainingWall => [74, 44, 26],
        PropKind::Kerb => [205, 205, 210],
        PropKind::Fence | PropKind::Gate => [110, 72, 40],
        PropKind::Tree => [30, 110, 40],
        PropKind::Bench => [150, 90, 200],
        PropKind::Fountain | PropKind::MarketCross => [40, 220, 255],
        PropKind::Banner | PropKind::Sign | PropKind::NeonSign => [255, 40, 120],
        PropKind::Cable | PropKind::WashingLine => [250, 250, 250],
        PropKind::FlowerBox | PropKind::Planter => [255, 120, 200],
        _ => [255, 220, 0],
    }
}

fn kind_colour(k: LotKind) -> [u8; 3] {
    match k {
        LotKind::House => [214, 120, 80],
        LotKind::Townhouse => [178, 64, 58],
        LotKind::Inn => [230, 60, 160],
        LotKind::Hall => [40, 190, 170],
        LotKind::Chapel => [250, 250, 250],
        LotKind::Workshop => [120, 90, 60],
        LotKind::Barn => [150, 110, 40],
        LotKind::Tower => [92, 70, 160],
        LotKind::Well => [60, 150, 220],
        LotKind::MarketStall => [240, 200, 60],
        LotKind::Lamp => [255, 240, 150],
        LotKind::Garden => [120, 170, 70],
        LotKind::Field => [196, 178, 96],
    }
}

fn road_colour(c: RoadClass) -> [u8; 3] {
    match c {
        RoadClass::Trunk => [236, 214, 160],
        RoadClass::Street => [250, 236, 200],
        RoadClass::Lane => [222, 206, 170],
        RoadClass::Path => [200, 170, 120],
    }
}

fn ground(t: Terrain) -> [f32; 3] {
    match t {
        Terrain::Grass => [128.0, 168.0, 92.0],
        Terrain::Forest => [70.0, 118.0, 64.0],
        Terrain::Water => [70.0, 120.0, 170.0],
        Terrain::Sand => [222.0, 206.0, 156.0],
        Terrain::Rock => [130.0, 124.0, 120.0],
        Terrain::Dirt => [156.0, 132.0, 96.0],
        Terrain::Road => [178.0, 164.0, 130.0],
        Terrain::Wall => [70.0, 62.0, 56.0],
    }
}

/// A view of the map: world window and scale.
struct View {
    x0: f32,
    y0: f32,
    px: f32,
}

impl View {
    fn to_px(&self, p: (f32, f32)) -> (f32, f32) {
        ((p.0 - self.x0) * self.px, (p.1 - self.y0) * self.px)
    }
    fn to_world(&self, x: usize, y: usize) -> (f32, f32) {
        (self.x0 + (x as f32 + 0.5) / self.px, self.y0 + (y as f32 + 0.5) / self.px)
    }
}

fn shade(land: &Land, img: &mut Img, v: &View, contour: f32) {
    let (w, h) = (img.w, img.h);
    let mut hs = vec![0f32; w * h];
    for y in 0..h {
        for x in 0..w {
            let p = v.to_world(x, y);
            hs[y * w + x] = land.height(p.0, p.1);
        }
    }
    let e = 1.0 / v.px;
    for y in 0..h {
        for x in 0..w {
            let p = v.to_world(x, y);
            let k = y * w + x;
            let hx = hs[y * w + (x + 1).min(w - 1)] - hs[y * w + x.saturating_sub(1)];
            let hy = hs[(y + 1).min(h - 1) * w + x] - hs[y.saturating_sub(1) * w + x];
            let (gx, gy) = (hx / (2.0 * e), hy / (2.0 * e));
            let lit = (0.75 + 0.45 * (-gx - gy) / (1.0 + gx * gx + gy * gy).sqrt()).clamp(0.35, 1.25);
            let t = land.map.at(p.0, p.1);
            let mut c = ground(t);
            if t != Terrain::Water {
                c = [c[0] * lit, c[1] * lit, c[2] * lit];
            }
            let hh = hs[k];
            let band = (hh / contour).floor();
            let right = (hs[y * w + (x + 1).min(w - 1)] / contour).floor();
            let down = (hs[(y + 1).min(h - 1) * w + x] / contour).floor();
            if (band != right || band != down) && t != Terrain::Water {
                let major = (band as i64).rem_euclid(5) == 0;
                let f = if major { 0.55 } else { 0.78 };
                c = [c[0] * f, c[1] * f, c[2] * f];
            }
            img.set(x as i32, y as i32, [c[0].min(255.0) as u8, c[1].min(255.0) as u8, c[2].min(255.0) as u8]);
        }
    }
}

fn fill_poly(img: &mut Img, v: &View, poly: &[(f32, f32)], c: [u8; 3], alpha: f32) {
    let pts: Vec<(f32, f32)> = poly.iter().map(|p| v.to_px(*p)).collect();
    let lo = pts.iter().fold((f32::MAX, f32::MAX), |m, p| (m.0.min(p.0), m.1.min(p.1)));
    let hi = pts.iter().fold((f32::MIN, f32::MIN), |m, p| (m.0.max(p.0), m.1.max(p.1)));
    for y in lo.1.floor().max(0.0) as i32..=hi.1.ceil().min(img.h as f32 - 1.0) as i32 {
        for x in lo.0.floor().max(0.0) as i32..=hi.0.ceil().min(img.w as f32 - 1.0) as i32 {
            let q = (x as f32 + 0.5, y as f32 + 0.5);
            let mut inside = false;
            let n = pts.len();
            let mut j = n - 1;
            for i in 0..n {
                let (a, b) = (pts[i], pts[j]);
                if (a.1 > q.1) != (b.1 > q.1) && q.0 < (b.0 - a.0) * (q.1 - a.1) / (b.1 - a.1) + a.0 {
                    inside = !inside;
                }
                j = i;
            }
            if inside {
                blend(img, x, y, c, alpha);
            }
        }
    }
}

fn blend(img: &mut Img, x: i32, y: i32, c: [u8; 3], a: f32) {
    if x < 0 || y < 0 || x as usize >= img.w || y as usize >= img.h {
        return;
    }
    let i = (y as usize * img.w + x as usize) * 3;
    for k in 0..3 {
        img.px[i + k] = (img.px[i + k] as f32 * (1.0 - a) + c[k] as f32 * a) as u8;
    }
}

fn thick_line(img: &mut Img, v: &View, a: (f32, f32), b: (f32, f32), width_px: f32, c: [u8; 3]) {
    let (pa, pb) = (v.to_px(a), v.to_px(b));
    let r = (width_px * 0.5).max(0.5);
    let lo = (pa.0.min(pb.0) - r - 1.0, pa.1.min(pb.1) - r - 1.0);
    let hi = (pa.0.max(pb.0) + r + 1.0, pa.1.max(pb.1) + r + 1.0);
    let d = (pb.0 - pa.0, pb.1 - pa.1);
    let l2 = (d.0 * d.0 + d.1 * d.1).max(1e-6);
    for y in lo.1.max(0.0) as i32..=hi.1.min(img.h as f32 - 1.0) as i32 {
        for x in lo.0.max(0.0) as i32..=hi.0.min(img.w as f32 - 1.0) as i32 {
            let q = (x as f32 + 0.5, y as f32 + 0.5);
            let u = (((q.0 - pa.0) * d.0 + (q.1 - pa.1) * d.1) / l2).clamp(0.0, 1.0);
            let dd = (q.0 - pa.0 - u * d.0).hypot(q.1 - pa.1 - u * d.1);
            if dd <= r {
                img.set(x, y, c);
            }
        }
    }
}

fn draw_roads(land: &Land, img: &mut Img, v: &View, min_px: f32, only: Option<u16>) {
    // Casing then fill, so junctions read cleanly.
    for pass in 0..2 {
        for r in &land.roads {
            if let Some(si) = only {
                let near = r.points.iter().any(|p| (p.0 - land.settlements[si as usize].centre.0).abs() < 2000.0 && (p.1 - land.settlements[si as usize].centre.1).abs() < 2000.0);
                if !near {
                    continue;
                }
            }
            let wpx = (r.width_m * v.px).max(min_px);
            let c = if pass == 0 { [70, 58, 44] } else { road_colour(r.class) };
            let extra = if pass == 0 { 2.0 } else { 0.0 };
            for i in 0..r.points.len() - 1 {
                thick_line(img, v, r.points[i], r.points[i + 1], wpx + extra, c);
            }
        }
    }
}

fn island(land: &Land, path: &str) {
    let size = land.size as usize;
    let px = (2048.0 / size as f32).min(1.0);
    let w = (size as f32 * px) as usize;
    let mut img = Img::new(w, w);
    let v = View { x0: 0.0, y0: 0.0, px };
    shade(land, &mut img, &v, 25.0);
    for s in &land.settlements {
        for l in &land.lots[s.lots.0 as usize..s.lots.1 as usize] {
            fill_poly(&mut img, &v, &l.corners(), kind_colour(l.kind), 0.9);
        }
    }
    draw_roads(land, &mut img, &v, 3.0, None);
    for s in &land.settlements {
        if let Some(wall) = &s.wall {
            for run in &wall.runs {
                for i in 0..run.len() - 1 {
                    thick_line(&mut img, &v, run[i], run[i + 1], 3.0, [50, 40, 36]);
                }
            }
        }
    }
    for c in &land.crossings {
        let p = v.to_px(c.at);
        let col = if c.kind == living_rules::settle::CrossingKind::Bridge { [240, 60, 60] } else { [255, 255, 255] };
        for d in -5..=5 {
            img.set(p.0 as i32 + d, p.1 as i32, col);
            img.set(p.0 as i32, p.1 as i32 + d, col);
        }
    }
    for (i, s) in land.sites.iter().enumerate() {
        let name = match s.kind {
            SiteKind::Cave => "CAVE".to_string(),
            _ => format!("{} {i}", s.id().replace('_', " ").to_uppercase()),
        };
        let p = v.to_px((s.x, s.y));
        img.text(p.0 as i32 + 8, p.1 as i32 - 20, &name, 2, [255, 255, 255]);
    }
    img.text(20, img.h as i32 - 30, &format!("SEED {} ROADS - CROSS: FORD WHITE, BRIDGE RED", land.seed), 2, [255, 255, 255]);
    img.write(path);
}

fn close_up(land: &Land, s: &Settlement, c: (f32, f32), half: f32, px: f32, path: &str) {
    let w = (2.0 * half * px) as usize;
    let mut img = Img::new(w, w);
    let v = View { x0: c.0 - half, y0: c.1 - half, px };
    let contour = match s.kind {
        SiteKind::Giants => 2.0,
        SiteKind::SmallFolk => 0.25,
        _ => 1.0,
    };
    shade(land, &mut img, &v, contour);
    // Fields and gardens under everything.
    for l in &land.lots {
        if !matches!(l.kind, LotKind::Field | LotKind::Garden) {
            continue;
        }
        let a = if l.kind == LotKind::Field { 0.55 } else { 0.7 };
        fill_poly(&mut img, &v, &l.corners(), kind_colour(l.kind), a);
        if l.kind == LotKind::Field {
            // Furrows along the depth.
            let cs = l.corners();
            let n = (l.width_m / 2.0).max(2.0) as usize;
            for i in 1..n {
                let t = i as f32 / n as f32;
                let a = (cs[0].0 + (cs[1].0 - cs[0].0) * t, cs[0].1 + (cs[1].1 - cs[0].1) * t);
                let b = (cs[3].0 + (cs[2].0 - cs[3].0) * t, cs[3].1 + (cs[2].1 - cs[3].1) * t);
                thick_line(&mut img, &v, a, b, 1.0, [150, 130, 70]);
            }
        }
    }
    fill_poly(&mut img, &v, &s.plaza.points, if s.plaza.paved { [226, 210, 176] } else { [150, 196, 110] }, 0.85);
    draw_roads(land, &mut img, &v, 1.5, None);
    if let Some(wall) = &s.wall {
        for run in &wall.runs {
            for i in 0..run.len() - 1 {
                thick_line(&mut img, &v, run[i], run[i + 1], wall.thickness_m * px, [60, 50, 44]);
            }
        }
        for g in &wall.gates {
            let p = v.to_px(g.at);
            img.text(p.0 as i32 + 6, p.1 as i32 + 6, "GATE", 2, [255, 230, 160]);
        }
    }
    for l in &land.lots {
        if matches!(l.kind, LotKind::Field | LotKind::Garden) {
            continue;
        }
        let cs = l.corners();
        let col = kind_colour(l.kind);
        fill_poly(&mut img, &v, &cs, col, 1.0);
        let dark = [col[0] / 3, col[1] / 3, col[2] / 3];
        for i in 0..4 {
            thick_line(&mut img, &v, cs[i], cs[(i + 1) % 4], 1.0, dark);
        }
        // Front mark: a bar along the front edge's middle third, and a tick out of it.
        let a = (cs[0].0 + (cs[1].0 - cs[0].0) / 3.0, cs[0].1 + (cs[1].1 - cs[0].1) / 3.0);
        let b = (cs[0].0 + (cs[1].0 - cs[0].0) * 2.0 / 3.0, cs[0].1 + (cs[1].1 - cs[0].1) * 2.0 / 3.0);
        thick_line(&mut img, &v, a, b, (0.5 * px).max(2.0), [255, 255, 255]);
        if l.landmark {
            let p = v.to_px(l.centre);
            img.text(p.0 as i32 - 20, p.1 as i32 - 4, l.kind.id(), 1, [255, 255, 255]);
        }
    }
    // Props: ground ones under the overhead ones.
    let idx = land.settlements.iter().position(|x| std::ptr::eq(x, s)).unwrap() as u16;
    for pass in 0..2 {
        for pr in land.props.iter().filter(|p| p.settlement == idx) {
            let overhead = matches!(pr.kind, PropKind::Cable | PropKind::WashingLine);
            if overhead != (pass == 1) {
                continue;
            }
            let cs = pr.corners();
            let col = prop_colour(pr.kind);
            if overhead {
                let a = ((cs[0].0 + cs[1].0) * 0.5, (cs[0].1 + cs[1].1) * 0.5);
                let b = ((cs[2].0 + cs[3].0) * 0.5, (cs[2].1 + cs[3].1) * 0.5);
                let (a, b) = if pr.kind == PropKind::Cable { (a, b) } else { (((cs[0].0 + cs[3].0) * 0.5, (cs[0].1 + cs[3].1) * 0.5), ((cs[1].0 + cs[2].0) * 0.5, (cs[1].1 + cs[2].1) * 0.5)) };
                thick_line(&mut img, &v, a, b, 1.0, col);
                continue;
            }
            fill_poly(&mut img, &v, &cs, col, 1.0);
            if pr.kind == PropKind::Stairs {
                // Treads across the flight, and a dark bar at its foot.
                for t in 1..6 {
                    let f = t as f32 / 6.0;
                    let a = (cs[0].0 + (cs[3].0 - cs[0].0) * f, cs[0].1 + (cs[3].1 - cs[0].1) * f);
                    let b = (cs[1].0 + (cs[2].0 - cs[1].0) * f, cs[1].1 + (cs[2].1 - cs[1].1) * f);
                    thick_line(&mut img, &v, a, b, 1.0, [120, 60, 0]);
                }
                thick_line(&mut img, &v, cs[0], cs[1], 2.0, [60, 20, 0]);
            }
        }
    }
    let sb = if half > 200.0 { 100.0 } else if half > 50.0 { 50.0 } else { 10.0 };
    let (bx, by) = (20, img.h as i32 - 40);
    for x in 0..(sb * px) as i32 {
        for t in 0..5 {
            img.set(bx + x, by + t, [255, 255, 255]);
        }
    }
    img.text(bx, by - 20, &format!("{sb:.0} M"), 2, [255, 255, 255]);
    let props = land.props.iter().filter(|p| p.settlement == idx).count();
    let terr = if s.terrace_m > 0.0 { format!(" - TERRACES {} M", s.terrace_m) } else { String::new() };
    let title = format!("SEED {} {} - CONTOURS {} M - {} LOTS - {} PROPS{}", land.seed, land.sites[s.site as usize].id().replace('_', " ").to_uppercase(), contour, s.lots.1 - s.lots.0, props, terr);
    img.text(20, 20, &title, 2, [255, 255, 255]);
    img.write(path);
}

fn legend(land: &Land, gen_s: f32, bare_s: f32, town_ns: f64, map_ns: f64) -> String {
    let mut o = String::new();
    let _ = writeln!(o, "seed {} size {} m", land.seed, land.size);
    let _ = writeln!(o, "generate: {gen_s:.2} s with settlements, {bare_s:.2} s without (settlements {:.2} s)", gen_s - bare_s);
    let _ = writeln!(o, "height(): {town_ns:.0} ns inside settlements, {map_ns:.0} ns over the map");
    let mut by_class = std::collections::BTreeMap::new();
    for r in &land.roads {
        let e = by_class.entry(format!("{:?}", r.class)).or_insert((0, 0.0f32));
        e.0 += 1;
        e.1 += r.length_m;
    }
    for (c, (n, l)) in by_class {
        let _ = writeln!(o, "roads {c}: {n}, {l:.0} m");
    }
    let fords = land.crossings.iter().filter(|c| c.kind == living_rules::settle::CrossingKind::Ford).count();
    let _ = writeln!(o, "river crossings: {} ({fords} fords, {} bridges)", land.crossings.len(), land.crossings.len() - fords);
    // Steepest graded road (over 10 m runs), per class.
    let mut by_cls: std::collections::BTreeMap<String, f32> = Default::default();
    let mut steep = 0.0f32;
    for r in &land.roads {
        let before = steep;
        steep = 0.0;
        let mut acc = 0.0;
        let mut j = 0;
        for i in 1..r.points.len() {
            acc += (r.points[i].0 - r.points[i - 1].0).hypot(r.points[i].1 - r.points[i - 1].1);
            while acc > 10.0 && j < i {
                let g = (r.heights[i] - r.heights[j]).abs() / acc;
                steep = steep.max(g);
                acc -= (r.points[j + 1].0 - r.points[j].0).hypot(r.points[j + 1].1 - r.points[j].1);
                j += 1;
            }
        }
        let e = by_cls.entry(format!("{:?}", r.class)).or_insert(0.0);
        *e = e.max(steep);
        steep = steep.max(before);
    }
    let per: Vec<String> = by_cls.iter().map(|(c, g)| format!("{c} {:.0}%", g * 100.0)).collect();
    let _ = writeln!(o, "steepest road grade over 10 m: {:.1}% ({})", steep * 100.0, per.join(", "));
    for (i, s) in land.settlements.iter().enumerate() {
        let lots = &land.lots[s.lots.0 as usize..s.lots.1 as usize];
        let mut counts = std::collections::BTreeMap::new();
        for l in lots {
            *counts.entry(l.kind.id()).or_insert(0) += 1;
        }
        let c: Vec<String> = counts.iter().map(|(k, n)| format!("{k} {n}")).collect();
        // Variety: distinct footprints and forms of the buildings people live in, and corners.
        let table = living_rules::settle::Buildings::default();
        let homes: Vec<_> = lots.iter().filter(|l| matches!(l.kind, LotKind::House | LotKind::Townhouse)).collect();
        let mut feet: Vec<(i32, i32)> = homes.iter().map(|l| ((l.width_m * 2.0).round() as i32, (l.depth_m * 2.0).round() as i32)).collect();
        feet.sort();
        feet.dedup();
        let mut forms: std::collections::BTreeMap<String, u32> = Default::default();
        let mut corners = 0;
        for l in &homes {
            if let Some(m) = l.model_file.as_deref().and_then(|f| table.model(f)) {
                *forms.entry(format!("{} {}", m.kind, m.form)).or_insert(0) += 1;
                corners += (m.corner != 0) as u32;
            }
        }
        let forms: Vec<String> = forms.iter().map(|(k, n)| format!("{k} {n}")).collect();
        let named = lots.iter().filter(|l| l.model_file.is_some()).count();
        let mut worst = 0.0f32;
        for l in lots.iter().filter(|l| l.kind.padded()) {
            for (a, b) in [(0.0, 0.0), (0.45, 0.45), (-0.45, 0.45), (0.45, -0.45), (-0.45, -0.45)] {
                let u = (-l.front.1, l.front.0);
                let p = (l.centre.0 + u.0 * a * l.width_m + l.front.0 * b * l.depth_m, l.centre.1 + u.1 * a * l.width_m + l.front.1 * b * l.depth_m);
                worst = worst.max((land.height(p.0, p.1) - l.floor_m).abs());
            }
        }
        let mut pc: std::collections::BTreeMap<&str, u32> = Default::default();
        for pr in land.props.iter().filter(|p| p.settlement == i as u16) {
            *pc.entry(pr.kind.id()).or_insert(0) += 1;
        }
        let pc: Vec<String> = pc.iter().map(|(k, n)| format!("{k} {n}")).collect();
        let _ = writeln!(
            o,
            "settlement {i} {} at ({:.0}, {:.0}) r {:.0} m, plaza {:.0} m floor, {} roads, wall {}, gates {}: {} | pads off level by at most {:.4} m\n  {named} lots name a model; homes: {} footprints (0.5 m), {corners} corner buildings; {}",
            land.sites[s.site as usize].id(),
            s.centre.0,
            s.centre.1,
            s.radius_m,
            s.plaza.floor_m,
            s.roads.len(),
            s.wall.as_ref().map_or("none".to_string(), |w| format!("{} runs", w.runs.len())),
            s.wall.as_ref().map_or(0, |w| w.gates.len()),
            c.join(", "),
            worst,
            feet.len(),
            forms.join(", ")
        );
        let _ = writeln!(o, "  props: {}{}", pc.join(", "), if s.terrace_m > 0.0 { format!("; terraced, {} m steps", s.terrace_m) } else { String::new() });
    }
    o
}
