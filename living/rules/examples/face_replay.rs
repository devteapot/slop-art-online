//! Replay a player's walk keys and looks through the steering rules and measure the facing.
//!
//! `cargo run -p living-rules --example face_replay -- <inputs.json> <track.json>`
//!
//! `inputs.json`: `{"events": [{"t": ms, "k": "move"|"look", "dx", "dy", "run"}],
//! "state": [{"t": ms, "face": rad}] (optional: a recorded travel track to compare),
//! "moments": [{"name", "from": ms, "to": ms}]}`. It prints, per moment, the facing's largest
//! change within 0.25 s, the stretches over 90 degrees, and the longest time after a change of
//! the keys until the facing is back within the `look_walk_deg` law of the travel; and writes
//! the 20 Hz track (t, facing, travel; degrees) of every moment to `track.json`.

use living_rules::map::Map;
use living_rules::steer as geo;
use serde_json::Value;

mod drive {
    use super::{geo, Map};
    include!("../src/steer_drive.rs");
}
use drive::*;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let v: Value = serde_json::from_str(&std::fs::read_to_string(&args[0]).expect("inputs")).expect("json");
    let f = |e: &Value, k: &str| e[k].as_f64().unwrap_or(0.0) as f32;
    let mut inputs = Vec::new();
    for e in v["events"].as_array().unwrap() {
        let t = e["t"].as_u64().unwrap();
        let dir = (f(e, "dx") != 0.0 || f(e, "dy") != 0.0).then(|| (f(e, "dx"), f(e, "dy")));
        match e["k"].as_str() {
            Some("move") => inputs.push((t, Input::Move { dir, run: e["run"].as_bool().unwrap_or(false) })),
            Some("look") => inputs.push((t, Input::Look { dir })),
            _ => {}
        }
    }
    let laws = Laws::default();
    let limit = laws.limit;
    let last = inputs.last().unwrap().0 + 3000;
    let first = inputs.first().unwrap().0;
    let (track, d) = replay(laws, 0.0, &inputs, first, last, 10);
    // The recorded travel against the replayed one, where both move.
    if let Some(st) = v["state"].as_array() {
        let mut errs: Vec<f32> = Vec::new();
        for s in st {
            let t = s["t"].as_u64().unwrap();
            if t < first || t > last {
                continue;
            }
            let i = ((t - first) / 10) as usize;
            if let Some((_, _, Some(tr))) = track.get(i) {
                errs.push(geo::wrap(f(s, "face") - tr).abs().to_degrees());
            }
        }
        errs.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let q = |p: f32| errs.get(((errs.len() as f32 - 1.0) * p) as usize).copied().unwrap_or(f32::NAN);
        println!("travel vs recorded (4 Hz, {} samples moving): median {:.1} deg, 90% {:.1}, within 5 deg {:.0}%", errs.len(), q(0.5), q(0.9), 100.0 * errs.iter().filter(|e| **e <= 5.0).count() as f32 / errs.len().max(1) as f32);
    }
    println!("{} rows written over {} inputs", d.rows.len(), inputs.len());
    let mut whole = Vec::new();
    let (w, n) = jumps(&track, 250, 90f32.to_radians());
    println!("whole session: largest change in 0.25 s {:.0} deg, {} stretches over 90 deg", w.to_degrees(), n);
    println!("{:<22} {:>12} {:>9} {:>14}", "moment", "max/0.25s", "jumps>90", "settle<=75 (s)");
    for m in v["moments"].as_array().map(|a| a.as_slice()).unwrap_or(&[]) {
        let (a, b) = (m["from"].as_u64().unwrap(), m["to"].as_u64().unwrap());
        let part: Vec<_> = track.iter().copied().filter(|s| s.0 >= a && s.0 <= b).collect();
        let (w, n) = jumps(&part, 250, 90f32.to_radians());
        // After each change of the walk keys in the moment: how long until the facing is within
        // the law (plus half a degree) of the travel, while the body moves.
        let mut settle = 0.0f32;
        for (t, i) in inputs.iter().filter(|(t, _)| *t >= a && *t <= b) {
            if !matches!(i, Input::Move { dir: Some(_), .. }) {
                continue;
            }
            let next = inputs.iter().find(|(u, j)| *u > *t && matches!(j, Input::Move { .. })).map_or(b, |x| x.0);
            let mut ok_at = None;
            for s in track.iter().filter(|s| s.0 >= *t && s.0 < next) {
                match s.2 {
                    Some(tr) if geo::wrap(s.1 - tr).abs() > limit + 0.5f32.to_radians() => ok_at = None,
                    _ => {
                        ok_at.get_or_insert(s.0);
                    }
                }
            }
            let took = ok_at.map_or((next - t) as f32 / 1000.0, |o| (o - t) as f32 / 1000.0);
            settle = settle.max(took);
        }
        println!("{:<22} {:>10.0}° {:>9} {:>14.2}", m["name"].as_str().unwrap_or("?"), w.to_degrees(), n, settle);
        whole.push(serde_json::json!({
            "name": m["name"], "from": a, "to": b, "max_change_deg": w.to_degrees(), "jumps_over_90": n, "settle_s": settle,
            "track": part.iter().step_by(5).map(|s| serde_json::json!([s.0, s.1.to_degrees(), s.2.map(|x| x.to_degrees())])).collect::<Vec<_>>(),
        }));
    }
    if let Some(out) = args.get(1) {
        std::fs::write(out, serde_json::to_string(&serde_json::json!({"moments": whole})).unwrap()).unwrap();
    }
}
