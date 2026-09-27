//! Chooses the world seed compiled into the module: `seeds/$LIVING_SEED.json` (default
//! `world`, the active world). Lab scenarios build their own module with another seed
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
    let seed_text = std::fs::read_to_string(&src).unwrap_or_else(|e| panic!("seed {}: {e}", src.display()));
    std::fs::write(out.join("seed.json"), &seed_text).unwrap();
    let mut species: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&species_src).unwrap()).expect("species.json");
    let seed: serde_json::Value = serde_json::from_str(&seed_text).expect("seed json");
    if let Some(over) = seed.get("species") {
        merge(&mut species, over);
    }
    std::fs::write(out.join("species.json"), serde_json::to_string_pretty(&species).unwrap()).unwrap();
}
