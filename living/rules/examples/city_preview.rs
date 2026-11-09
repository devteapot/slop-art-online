//! The megacity's districts and capture spots, from a land seed with a city (`docs/FLOORS.md`).
//!
//! `cargo run --release -p living-rules --example city_preview --manifest-path living/Cargo.toml -- SEED_JSON [SIZE_M]`
//!
//! Prints each district style's wards, lots, tallest building and props, then one line per
//! capture spot as `name x z yaw` (yaw in degrees, 0 looking north, clockwise: the look-dev
//! tour's convention), looking at what the spot is for: the core's tallest towers, a neon
//! street, a megablock, the slums against the wall, a highway, the market, the port, the wastes
//! outside a gate and a salvage camp. The same rules pick spots in any city layout, so captures
//! of two generators compare like with like.

use living_rules::land::{self, Land, LandParams};
use living_rules::settle::{LotKind, PropKind, RoadClass};
use std::collections::BTreeMap;

fn yaw_to(from: (f32, f32), to: (f32, f32)) -> f32 {
    (to.0 - from.0).atan2(-(to.1 - from.1)).to_degrees().rem_euclid(360.0)
}

fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    (a.0 - b.0).hypot(a.1 - b.1)
}

/// Settlements of the first of `styles` that the land has.
fn wards<'a>(land: &'a Land, styles: &[&str]) -> Vec<usize> {
    for s in styles {
        let v: Vec<usize> = (0..land.settlements.len()).filter(|&i| land.settlements[i].style == *s).collect();
        if !v.is_empty() {
            return v;
        }
    }
    Vec::new()
}

/// A point `back` metres from a lot's front, looking at it.
fn facing(l: &living_rules::settle::Lot, back: f32) -> (f32, f32, f32) {
    let p = (l.centre.0 + l.front.0 * (l.depth_m * 0.5 + back), l.centre.1 + l.front.1 * (l.depth_m * 0.5 + back));
    (p.0, p.1, yaw_to(p, l.centre))
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let path = args.get(1).expect("seed json path");
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(path).expect("read seed")).expect("seed json");
    let map = &v["map"];
    let seed = v["seed"].as_u64().unwrap_or(7);
    let size = args.get(2).and_then(|s| s.parse::<u32>().ok()).filter(|s| *s > 0).unwrap_or(map["size"].as_u64().unwrap_or(2048) as u32);
    let params: LandParams = serde_json::from_value(map["params"].clone()).expect("map.params");
    let land = land::generate(seed, size, &params);
    let centre = params.metro.as_ref().map_or((size as f32 / 2.0, size as f32 / 2.0), |m| (m.centre[0] * size as f32, m.centre[1] * size as f32));

    // Districts.
    let mut by: BTreeMap<String, (usize, usize, f32, BTreeMap<String, usize>)> = BTreeMap::new();
    for (si, s) in land.settlements.iter().enumerate() {
        let e = by.entry(s.style.clone()).or_default();
        e.0 += 1;
        for l in land.lots.iter().filter(|l| l.settlement as usize == si) {
            e.1 += 1;
            e.2 = e.2.max(l.height_m);
            if let Some(m) = l.model_file.as_deref().and_then(living_rules::settle::asset_kind) {
                *e.3.entry(m.to_string()).or_default() += 1;
            }
        }
    }
    for (style, (n, lots, tall, kinds)) in &by {
        println!("district {style}: {n} settlements, {lots} lots, tallest {tall:.0} m, models {kinds:?}");
    }
    let mut props: BTreeMap<&str, usize> = BTreeMap::new();
    for p in &land.props {
        *props.entry(p.kind.id()).or_default() += 1;
    }
    println!("props {props:?}");

    let mut spots: Vec<(&str, (f32, f32, f32))> = Vec::new();
    // The core: from the central plaza toward its tallest tower.
    if let Some(&c) = wards(&land, &["corporate", "metro"]).iter().min_by(|a, b| dist(land.settlements[**a].plaza.centre, centre).total_cmp(&dist(land.settlements[**b].plaza.centre, centre))) {
        let set = &land.settlements[c];
        let pc = set.plaza.centre;
        // A building in the middle of the square (an arcology): stand out along the street it
        // faces, 120 m from it, and look at it.
        let inside = land.lots.iter().find(|l| l.settlement as usize == c && dist(l.centre, pc) < 1.0);
        let at = inside.map_or(pc, |l| (pc.0 + l.front.0 * 120.0, pc.1 + l.front.1 * 120.0));
        if let Some(l) = inside {
            spots.push(("core", (at.0, at.1, yaw_to(at, l.centre))));
        } else if let Some(t) = land.lots.iter().filter(|l| dist(l.centre, pc) < 160.0).max_by(|a, b| a.height_m.total_cmp(&b.height_m)) {
            spots.push(("core", (at.0, at.1, yaw_to(at, t.centre))));
        }
    }
    // A neon street: the 40 m with the most neon signs, looking along its street.
    let neon: Vec<(f32, f32)> = land.props.iter().filter(|p| p.kind == PropKind::NeonSign).map(|p| p.centre).collect();
    if let Some(best) = neon.iter().max_by_key(|p| neon.iter().filter(|q| dist(**p, **q) < 40.0).count()) {
        let road = land.roads.iter().filter(|r| r.class != RoadClass::Trunk).flat_map(|r| r.points.windows(2).map(move |w| (w[0], w[1]))).min_by(|a, b| dist(a.0, *best).total_cmp(&dist(b.0, *best)));
        let (p, yaw) = road.map_or((*best, 0.0), |(a, b)| (a, yaw_to(a, b)));
        spots.push(("neon_street", (p.0, p.1, yaw)));
    }
    // A megablock: the dense residential district's biggest footprint.
    if let Some(l) = land.lots.iter().filter(|l| wards(&land, &["megablock", "metro"]).contains(&(l.settlement as usize)) && l.kind != LotKind::Lamp).max_by(|a, b| (a.width_m * a.depth_m).total_cmp(&(b.width_m * b.depth_m))) {
        spots.push(("megablock", facing(l, 14.0)));
    }
    // The slums against the wall: the slum lot farthest from the centre, looking outward.
    if let Some(l) = land.lots.iter().filter(|l| wards(&land, &["slum"]).contains(&(l.settlement as usize))).max_by(|a, b| dist(a.centre, centre).total_cmp(&dist(b.centre, centre))) {
        let p = (l.centre.0 + (centre.0 - l.centre.0) * 0.06, l.centre.1 + (centre.1 - l.centre.1) * 0.06);
        spots.push(("slum_wall", (p.0, p.1, yaw_to(p, l.centre))));
    }
    // A highway: the elevated highway where it crosses an arterial nearest the first ring, else
    // a trunk road there.
    let ring = land.roads.iter().filter(|r| r.class == RoadClass::Trunk && r.settlement.is_none()).flat_map(|r| r.points.iter().copied()).min_by(|a, b| (dist(*a, centre) - size as f32 * 0.11).abs().total_cmp(&(dist(*b, centre) - size as f32 * 0.11).abs()));
    if let Some(p) = ring {
        let q = land.props.iter().filter(|pr| pr.kind.id().starts_with("highway")).min_by(|a, b| dist(a.centre, p).total_cmp(&dist(b.centre, p))).map_or(p, |pr| pr.centre);
        spots.push(("overpass", (q.0 + 18.0, q.1 + 18.0, yaw_to((q.0 + 18.0, q.1 + 18.0), q))));
    }
    // The market: a market district's square, else the square with the most stalls.
    let market = wards(&land, &["market"]).first().copied().or_else(|| (0..land.settlements.len()).filter(|&i| land.settlements[i].style == "metro").max_by_key(|&i| land.props.iter().filter(|p| p.settlement as usize == i && matches!(p.kind, PropKind::FoodStall | PropKind::Kiosk)).count()));
    if let Some(m) = market {
        let pc = land.settlements[m].plaza.centre;
        spots.push(("market", (pc.0, pc.1, yaw_to(pc, centre))));
    }
    // The port: the works district's lot nearest the sea, looking at it.
    if let Some(l) = land.lots.iter().filter(|l| wards(&land, &["works"]).contains(&(l.settlement as usize)) && l.kind.model().is_some()).max_by(|a, b| dist(a.centre, centre).total_cmp(&dist(b.centre, centre))) {
        spots.push(("port", facing(l, 16.0)));
    }
    // The old town's square.
    if let Some(&o) = wards(&land, &["oldtown"]).first() {
        let pc = land.settlements[o].plaza.centre;
        spots.push(("old_town", (pc.0, pc.1, yaw_to(pc, centre))));
    }
    // The wastes' edge: outside the wall's first gate, looking back at the city.
    if let Some(g) = land.settlements.iter().filter_map(|s| s.wall.as_ref()).flat_map(|w| w.gates.iter()).next() {
        let p = (g.at.0 + g.out.0 * 60.0, g.at.1 + g.out.1 * 60.0);
        spots.push(("wastes_edge", (p.0, p.1, yaw_to(p, g.at))));
    }
    // A salvage camp's square, looking toward the city.
    if let Some(&s) = wards(&land, &["salvage"]).first() {
        let pc = land.settlements[s].plaza.centre;
        spots.push(("salvage_camp", (pc.0, pc.1, yaw_to(pc, centre))));
    }
    for (name, (x, z, yaw)) in spots {
        println!("spot {name} {x:.0} {z:.0} {yaw:.0}");
    }
}
