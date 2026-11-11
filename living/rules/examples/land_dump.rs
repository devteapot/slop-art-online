//! Dump a land seed's generated land for tools outside Rust (plan maps, walking distances, sight
//! lines; `living/tools/cullet_check.py`): the hosted tiles, the ground height at every tile
//! centre, the region kind of every tile, and the layout (lots with their plan ids, roads, props,
//! planned resources) as JSON.
//!
//! `cargo run --release -p living-rules --example land_dump --manifest-path living/Cargo.toml -- SEED_JSON OUT_DIR`
//!
//! Writes `tiles.u8` (size² bytes, `Terrain` values, row-major from the north-west corner),
//! `heights.f32` (size² little-endian floats, metres), `regions.u8` (`RegionKind::ALL` indices)
//! and `layout.json`.

use living_rules::host;
use living_rules::land::{self, LandParams, RegionKind};
use serde_json::json;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let path = args.get(1).expect("seed json path");
    let dir = args.get(2).cloned().unwrap_or_else(|| ".".into());
    std::fs::create_dir_all(&dir).unwrap();
    let seed_json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(path).expect("read seed")).expect("seed json");
    let map = &seed_json["map"];
    assert_eq!(map["kind"], "land", "not a land seed");
    let seed = seed_json["seed"].as_u64().unwrap_or(7);
    let size = map["size"].as_u64().unwrap_or(2048) as u32;
    let params: LandParams = if map["params"].is_null() { LandParams::default() } else { serde_json::from_value(map["params"].clone()).expect("map.params") };
    let land = land::generate(seed, size, &params);
    let (hosted, h) = host::hosted_map(&land, &params);
    let d = host::digests(&land, &hosted);
    let w = size as usize;
    let mut heights = Vec::with_capacity(w * w * 4);
    let mut regions = Vec::with_capacity(w * w);
    for j in 0..w {
        for i in 0..w {
            let (x, y) = (i as f32 + 0.5, j as f32 + 0.5);
            heights.extend_from_slice(&land.height(x, y).to_le_bytes());
            let k = land.kind_at(x, y);
            regions.push(RegionKind::ALL.iter().position(|r| *r == k).unwrap_or(0) as u8);
        }
    }
    std::fs::write(format!("{dir}/tiles.u8"), &hosted.tiles).unwrap();
    std::fs::write(format!("{dir}/heights.f32"), heights).unwrap();
    std::fs::write(format!("{dir}/regions.u8"), regions).unwrap();
    let mut keys = std::collections::HashMap::new();
    for p in &land.plans {
        for l in &p.lots {
            keys.insert(l.lot as usize, (l.key.clone(), l.name.clone(), l.spots.clone()));
        }
    }
    let lots: Vec<_> = land
        .lots
        .iter()
        .enumerate()
        .map(|(i, l)| {
            let k = keys.get(&i);
            json!({"key": k.map(|k| k.0.clone()), "name": k.and_then(|k| k.1.clone()), "kind": l.kind.id(), "centre": [l.centre.0, l.centre.1], "width_m": l.width_m, "depth_m": l.depth_m, "front": [l.front.0, l.front.1], "yaw": l.yaw, "floor_m": l.floor_m, "height_m": l.height_m, "landmark": l.landmark, "door": host::door(l), "spots": k.map(|k| k.2.clone()).unwrap_or_default()})
        })
        .collect();
    let roads: Vec<_> = land.roads.iter().map(|r| json!({"class": format!("{:?}", r.class), "width_m": r.width_m, "settlement": r.settlement, "points": r.points})).collect();
    let props: Vec<_> = land.props.iter().map(|p| json!({"kind": format!("{:?}", p.kind), "centre": [p.centre.0, p.centre.1], "width_m": p.width_m, "depth_m": p.depth_m, "front": [p.front.0, p.front.1], "floor_m": p.floor_m, "height_m": p.height_m})).collect();
    let resources: Vec<_> = land.plans.iter().flat_map(|p| p.resources.iter().map(|r| json!({"kind": r.kind, "at": [r.at.0, r.at.1], "pool": r.pool}))).collect();
    let squares: Vec<_> = land.settlements.iter().map(|s| json!({"style": s.style, "centre": [s.plaza.centre.0, s.plaza.centre.1], "points": s.plaza.points})).collect();
    let out = json!({
        "seed": seed, "size": size,
        "digests": {"tiles": format!("{:016x}", d.tiles), "heights": format!("{:016x}", d.heights), "layout": format!("{:016x}", d.layout)},
        "arrival": host::arrival(&land, &hosted),
        "blocked_tiles": h.blocked_tiles, "cut_off_tiles": h.cut_off_tiles,
        "stranded": living_rules::settle::stranded_doors(&land, &hosted, &h.reachable),
        "lots": lots, "roads": roads, "props": props, "resources": resources, "squares": squares,
    });
    std::fs::write(format!("{dir}/layout.json"), serde_json::to_string(&out).unwrap()).unwrap();
    println!("{dir}: {} lots, {} roads, {} props, {} planned resources; digests {} {} {}", land.lots.len(), land.roads.len(), land.props.len(), out["resources"].as_array().unwrap().len(), out["digests"]["tiles"], out["digests"]["heights"], out["digests"]["layout"]);
}
