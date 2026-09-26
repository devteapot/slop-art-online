//! Chooses the world seed compiled into the module: `seeds/$LIVING_SEED.json` (default
//! `world`, the active world). Lab scenarios build their own module with another seed
//! without touching the active one.
fn main() {
    println!("cargo:rerun-if-env-changed=LIVING_SEED");
    let name = std::env::var("LIVING_SEED").unwrap_or_else(|_| "world".into());
    let src = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../seeds").join(format!("{name}.json"));
    println!("cargo:rerun-if-changed={}", src.display());
    let out = std::path::Path::new(&std::env::var("OUT_DIR").unwrap()).join("seed.json");
    std::fs::copy(&src, &out).unwrap_or_else(|e| panic!("seed {}: {e}", src.display()));
}
