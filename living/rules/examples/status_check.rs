//! A body's statuses as a client works them out from its `my_vitals` row (the game's pills,
//! `living/game/src/ui/live.rs` `my_body`): the world's script's `status_of` over
//! `BodyFacts::of`, by its parts (`status_parts()`, as every client asks) and whole (the
//! authority's rollback). The verify-player status check compares the two and reads the pills.
//!
//! `status_check SCRIPT_FILE DAY_MS FACTS_JSON`, with FACTS_JSON
//! `{"kind": "person", "stage": "adult", "night": false, "now_ms": 123, "row": {<my_vitals row>}}`,
//! prints `{"parts": [names], "whole": [names], "same": true, "pills": [names of non-plain], "felt": "…", "declared": [part names]}`.
use living_rules::script::{body::fields_of_json, BodyFacts, Scripts, StatusWay};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        eprintln!("usage: status_check SCRIPT_FILE DAY_MS FACTS_JSON");
        std::process::exit(2);
    }
    let source = std::fs::read_to_string(&args[1]).expect("script file");
    let day_ms: u64 = args[2].parse().expect("DAY_MS");
    let f: serde_json::Value = serde_json::from_str(&args[3]).expect("FACTS_JSON");
    let sc = Scripts::with_day(&source, day_ms).expect("the script compiles");
    let fields = fields_of_json(&f["row"]);
    let b = BodyFacts::of(f["kind"].as_str().unwrap_or("person"), f["stage"].as_str().unwrap_or("adult"), f["night"].as_bool().unwrap_or(false), &fields, sc.meters(), f["now_ms"].as_u64().unwrap_or(0));
    let parts = sc.status_of(&b).expect("status_of by parts");
    let whole = sc.status_of_profiled(&b, StatusWay { parts: false, check: false }, |_| ()).expect("status_of whole");
    let names = |v: &[living_rules::script::Status]| v.iter().map(|s| s.name.clone()).collect::<Vec<_>>();
    println!(
        "{}",
        serde_json::json!({
            "parts": names(&parts),
            "whole": names(&whole),
            "same": *parts == *whole,
            "pills": parts.iter().filter(|s| s.tone != "plain").map(|s| s.name.clone()).collect::<Vec<_>>(),
            "felt": sc.felt(&b).unwrap_or_default(),
            "declared": sc.status_part_names(),
            "facts": b.fields,
        })
    );
}
