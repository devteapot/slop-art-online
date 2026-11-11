//! Chooses the world seed compiled into the module: `seeds/$LIVING_SEED.json` (default
//! `world`, the active world), or none (`LIVING_SEED=none`: a floor module, seeded at runtime
//! by `create_floor`). Lab scenarios build their own module with another seed
//! without touching the active one. A seed may carry a `species` object whose entries are
//! merged over `seeds/species.json` (e.g. an ecology lab varying the wolves' breeding).
fn merge(base: &mut serde_json::Value, over: &serde_json::Value) {
    match (base, over) {
        (serde_json::Value::Object(b), serde_json::Value::Object(o)) => {
            for (k, v) in o {
                merge(b.entry(k.clone()).or_insert(serde_json::Value::Null), v);
            }
        }
        (b, o) => *b = o.clone(),
    }
}

fn main() {
    println!("cargo:rerun-if-env-changed=LIVING_SEED");
    let name = std::env::var("LIVING_SEED").unwrap_or_else(|_| "world".into());
    let seeds = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../seeds");
    let src = seeds.join(format!("{name}.json"));
    let species_src = seeds.join("species.json");
    println!("cargo:rerun-if-changed={}", src.display());
    println!("cargo:rerun-if-changed={}", species_src.display());
    let out = std::path::Path::new(&std::env::var("OUT_DIR").unwrap()).to_path_buf();
    // `none`: a floor module, with no seed compiled in; `create_floor` gives it one at runtime.
    let mut seed_text = if name == "none" { String::new() } else { std::fs::read_to_string(&src).unwrap_or_else(|e| panic!("seed {}: {e}", src.display())) };
    // A seed's laws overlay kept in its own file (`laws_file`, relative to `living/seeds`) is
    // compiled in as its text (`laws`), as `living/tools/seed_text.py` sends it to `create_floor`.
    if !seed_text.is_empty() {
        let mut v: serde_json::Value = serde_json::from_str(&seed_text).expect("seed json");
        let file = v.get("laws_file").and_then(|f| f.as_str()).map(String::from);
        if let Some(file) = file.filter(|_| v.get("laws").and_then(|l| l.as_str()).is_none_or(|l| l.trim().is_empty())) {
            let path = seeds.join(&file);
            println!("cargo:rerun-if-changed={}", path.display());
            let laws = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("seed laws_file {}: {e}", path.display()));
            v["laws"] = serde_json::Value::String(laws);
            seed_text = serde_json::to_string(&v).unwrap();
        }
    }
    std::fs::write(out.join("seed.json"), &seed_text).unwrap();
    let mut species: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&species_src).unwrap()).expect("species.json");
    let seed: serde_json::Value = if seed_text.is_empty() { serde_json::json!({}) } else { serde_json::from_str(&seed_text).expect("seed json") };
    if let Some(over) = seed.get("species") {
        merge(&mut species, over);
    }
    std::fs::write(out.join("species.json"), serde_json::to_string_pretty(&species).unwrap()).unwrap();
    // A seed's `rules` are no longer compiled in: they are the world's own values of the
    // script's laws, kept when the world is created (`world_law`, docs/WORLD_RULES.md).
    // What a player's client may read (docs/PERCEPTION.md). `scoped` (the default) keeps
    // bodies, characters, fighters, `doing` and every character's vitals, experiences, places,
    // inventory and know-how private, so a player receives only what the `seen_*` and `my_*`
    // views return. `open` makes those nine public again, for the lab observer without a
    // token and for diagnostics; it is not a perception boundary. Developer audit truth is
    // private in both.
    println!("cargo:rerun-if-env-changed=LIVING_PERCEPTION");
    println!("cargo:rustc-check-cfg=cfg(open_tables)");
    match std::env::var("LIVING_PERCEPTION").as_deref() {
        Ok("scoped") | Err(_) => {}
        Ok("open") => println!("cargo:rustc-cfg=open_tables"),
        Ok(other) => panic!("LIVING_PERCEPTION must be `open` or `scoped`, not `{other}`"),
    }
}
