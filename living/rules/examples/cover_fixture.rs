//! Find fixed probes in a generated land fixture without inventing a second sight trace.
use living_rules::{cover, host, land::{self, LandParams}, map::{Map, Terrain}};
use serde_json::{json, Value};
use std::sync::Arc;

fn main() {
    let path = std::env::args().nth(1).expect("land seed JSON");
    let seed: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let params: LandParams = serde_json::from_value(seed["map"]["params"].clone()).unwrap();
    let land = land::generate(seed["seed"].as_u64().unwrap(), seed["map"]["size"].as_u64().unwrap() as u32, &params);
    let (map, _) = host::hosted_map(&land, &params);
    let policy = cover::Policy { eye_height_m: 1.6, brush_on: true, brush_min_fill: 0.6, cliff_step_m: 2.0 };
    let mut covered = map.clone();
    covered.cover = Some(Arc::new(cover::compile(&map, cover::ground(&land), &params, policy)));
    let clear = |m: &Map, a: [f32; 2], b: [f32; 2]| m.sight_clear((a[0],a[1]), (b[0],b[1]));
    let probe = |feature: &str| {
        for y in 8..map.h-8 {
            for x in 8..map.w-8 {
                let target = [x as f32 + 0.5, y as f32 + 0.5];
                let solid = !covered.passable_missile(target[0],target[1]) && map.passable_missile(target[0],target[1]);
                if feature == "brush" && (solid || !map.free(target[0],target[1])) { continue; }
                if feature == "trunk" && (!solid || map.at(target[0],target[1]) == Terrain::Drop) { continue; }
                if matches!(feature, "cliff" | "overlook") && (!solid || map.at(target[0],target[1]) != Terrain::Drop) { continue; }
                // The intervening cell must be the candidate feature.
                for (dx,dy) in [(1.0,0.0),(0.0,1.0),(-1.0,0.0),(0.0,-1.0)] {
                    let range = if feature == "brush" { 4..8 } else { 2..6 };
                    for d in range {
                        let a = [target[0]-dx*d as f32, target[1]-dy*d as f32];
                        let b = if feature == "brush" { target } else { [target[0]+dx*2.0,target[1]+dy*2.0] };
                        if !map.free(a[0],a[1]) || !map.free(b[0],b[1]) || !clear(&map,a,b) { continue; }
                        let passes = clear(&covered,a,b);
                        if feature == "brush" && (passes || !(0..=d).all(|i|
                            covered.passable_missile(target[0]-dx*i as f32, target[1]-dy*i as f32))) { continue; }
                        if feature == "overlook" {
                            if !passes { continue; }
                            let dz = (land.height(a[0],a[1])-land.height(b[0],b[1])).abs();
                            if dz < 2.0 { continue; }
                        } else if passes { continue; }
                        if feature == "trunk" && ((land.height(a[0],a[1])-land.height(b[0],b[1])).abs() > 0.8) { continue; }
                        return json!({"from":a,"to":b,"cell":target});
                    }
                }
            }
        }
        panic!("{feature} probe missing")
    };
    println!("{}", json!({"trunk":probe("trunk"), "brush":probe("brush"),
        "cliff":probe("cliff"), "overlook":probe("overlook")}));
}
