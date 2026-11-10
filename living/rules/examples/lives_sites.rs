//! The settlements of a land seed, as an author places people in them (docs/SEEDED_LIVES.md):
//! each settlement's site id, region kind, centre, homes and lots, and how the authority's
//! walk search (`Map::path`, 6,000 expansions) reaches from one settlement to the others.
//!
//! `cargo run --release -p living-rules --example lives_sites --manifest-path living/Cargo.toml -- SEED SIZE_M [PARAMS_JSON] > sites.json`
use living_rules::host;
use living_rules::land::{self, LandParams};
use living_rules::settle::LotKind;

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let seed: u64 = a[0].parse().expect("seed");
    let size: u32 = a[1].parse().expect("size");
    let params: LandParams = a.get(2).map(|p| serde_json::from_str(p).expect("params")).unwrap_or_default();
    let l = land::generate(seed, size, &params);
    let (map, _) = host::hosted_map(&l, &params);
    let d = host::digests(&l, &map);
    let near = |p: (f32, f32)| map.nearest_walkable(p.0, p.1).unwrap_or(p);
    // PROBE=x0,y0,x1,y1: one walk search on the hosted map, then exit.
    if let Ok(q) = std::env::var("PROBE") {
        let v: Vec<f32> = q.split(',').map(|x| x.parse().unwrap()).collect();
        let budget: usize = std::env::var("BUDGET").ok().and_then(|b| b.parse().ok()).unwrap_or(6_000);
        let p = map.path((v[0], v[1]), (v[2], v[3]), budget);
        println!("from {:?} ({}) to {:?} ({}): line clear {}, path {:?}", (v[0], v[1]), map.at(v[0], v[1]).name(), (v[2], v[3]), map.at(v[2], v[3]).name(), map.line_clear((v[0], v[1]), (v[2], v[3])), p.map(|p| p.len()));
        return;
    }
    let mut out = Vec::new();
    for (i, s) in l.settlements.iter().enumerate() {
        let lots = &l.lots[s.lots.0 as usize..s.lots.1 as usize];
        let mut kinds = std::collections::BTreeMap::<&str, u32>::new();
        for x in lots {
            *kinds.entry(x.kind.id()).or_default() += 1;
        }
        let homes = lots.iter().filter(|x| matches!(x.kind, LotKind::House | LotKind::Townhouse)).count();
        let mut reach = Vec::new();
        for (j, o) in l.settlements.iter().enumerate().filter(|(j, _)| *j != i) {
            let (a, b) = (near(s.plaza.centre), near(o.plaza.centre));
            let straight = (a.0 - b.0).hypot(a.1 - b.1);
            let t = std::time::Instant::now();
            let budget: usize = std::env::var("BUDGET").ok().and_then(|b| b.parse().ok()).unwrap_or(6_000);
            let p = map.path(a, b, budget);
            let walk: Option<f32> = p.as_ref().map(|p| {
                let mut at = a;
                let mut len = 0.0;
                for q in p {
                    len += (q.0 - at.0).hypot(q.1 - at.1);
                    at = *q;
                }
                len
            });
            reach.push(serde_json::json!({"to": j, "straight_m": straight.round(), "walk_m": walk.map(|w| w.round()), "search_ms": (t.elapsed().as_secs_f64() * 1000.0 * 10.0).round() / 10.0}));
        }
        out.push(serde_json::json!({
            "index": i,
            "site": l.sites[s.site as usize].id(),
            "region": l.sites[s.site as usize].region,
            "centre": [s.plaza.centre.0.round(), s.plaza.centre.1.round()],
            "radius_m": s.radius_m.round(),
            "homes": homes,
            "lots": kinds,
            "reach": reach,
        }));
    }
    println!("{}", serde_json::to_string_pretty(&serde_json::json!({"seed": seed, "size": size, "digests": {"tiles": format!("{:016x}", d.tiles), "heights": format!("{:016x}", d.heights), "layout": format!("{:016x}", d.layout)}, "settlements": out})).unwrap());
}
