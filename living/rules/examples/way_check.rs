//! A way's refusal as a client sees it before sending: the world's script's `<way>_check` on
//! the facts a client has, through the function the authority calls
//! (`living_rules::script::speech::check_way`). The verify-player agreement test compares its
//! words with the reducer's.
//!
//! `way_check SCRIPT_FILE DAY_MS FACTS_JSON`, with FACTS_JSON
//! `{"way": "whisper", "text": "…", "to": null | {"id": 7, "alive": true, "dist": 3.2}, "since_ms": null | 2500, "knows": []}`,
//! prints `{"refused": "too far to whisper: step closer"}` or `{"refused": null}`.
use living_rules::script::{speech::check_way, ActorFacts, Scripts, TargetFacts};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        eprintln!("usage: way_check SCRIPT_FILE DAY_MS FACTS_JSON");
        std::process::exit(2);
    }
    let source = std::fs::read_to_string(&args[1]).expect("script file");
    let day_ms: u64 = args[2].parse().expect("DAY_MS");
    let f: serde_json::Value = serde_json::from_str(&args[3]).expect("FACTS_JSON");
    let sc = Scripts::with_day(&source, day_ms).expect("the script compiles");
    let way = f["way"].as_str().unwrap_or("say");
    let knows = f["knows"].as_array().map(|a| a.iter().filter_map(|k| k.as_str().map(String::from)).collect()).unwrap_or_default();
    let actor = ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), knows, ..Default::default() };
    let to = f["to"].as_object().map(|t| TargetFacts {
        class: "creature".into(),
        id: t.get("id").and_then(|v| v.as_u64()).unwrap_or(0),
        kind: "person".into(),
        alive: t.get("alive").and_then(|v| v.as_bool()).unwrap_or(true),
        dist: t.get("dist").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
        ..Default::default()
    });
    let refused = check_way(&sc, way, actor, to, f["text"].as_str().unwrap_or(""), f["since_ms"].as_u64()).err();
    println!("{}", serde_json::json!({ "refused": refused }));
}
