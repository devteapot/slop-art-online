//! Staged land generation as the authority runs it, one export call per step, so the host can
//! read each step's fuel (WASM instructions) under SpacetimeDB's wasmtime configuration.

use living_rules::host;
use living_rules::land::{Gen, LandParams};

struct State {
    input: Vec<u8>,
    out: Vec<u8>,
    gen: Option<Gen>,
    params: LandParams,
}

static mut STATE: Option<State> = None;

fn state() -> &'static mut State {
    // Single-threaded module; the host calls one export at a time.
    unsafe { (*(&raw mut STATE)).get_or_insert_with(|| State { input: Vec::new(), out: Vec::new(), gen: None, params: LandParams::default() }) }
}

/// A buffer of `len` bytes for the seed JSON; returns its address.
#[no_mangle]
pub extern "C" fn lf_input(len: u32) -> u32 {
    let s = state();
    s.input = vec![0; len as usize];
    s.input.as_mut_ptr() as u32
}

/// The text output buffer's address (its length is the last call's return value).
#[no_mangle]
pub extern "C" fn lf_out() -> u32 {
    state().out.as_ptr() as u32
}

/// Start generating the seed in the input buffer at `size` metres (0: the seed's own size);
/// returns the number of steps.
#[no_mangle]
pub extern "C" fn lf_new(size: u32) -> u32 {
    let s = state();
    let v: serde_json::Value = serde_json::from_slice(&s.input).expect("seed json");
    let map = &v["map"];
    let seed = v["seed"].as_u64().unwrap_or(7);
    let size = if size > 0 { size } else { map["size"].as_u64().unwrap_or(2048) as u32 };
    s.params = if map["params"].is_null() { LandParams::default() } else { serde_json::from_value(map["params"].clone()).expect("map.params") };
    let g = Gen::new(seed, size, s.params.clone());
    let n = g.steps();
    s.gen = Some(g);
    n
}

/// The next step's label into the output buffer; returns its length.
#[no_mangle]
pub extern "C" fn lf_label() -> u32 {
    let s = state();
    s.out = s.gen.as_ref().map(|g| g.label()).unwrap_or_default().into_bytes();
    s.out.len() as u32
}

/// Run one step; 1 once the land is complete.
#[no_mangle]
pub extern "C" fn lf_step() -> u32 {
    state().gen.as_mut().expect("lf_new first").step() as u32
}

/// Host the finished land (building footprints into the tiles) and compute its digests, as the
/// authority does after the last step; the digests go to the output buffer.
#[no_mangle]
pub extern "C" fn lf_host() -> u32 {
    let s = state();
    let land = s.gen.take().expect("lf_new first").into_land();
    let (map, _) = host::hosted_map(&land, &s.params);
    let d = host::digests(&land, &map);
    s.out = format!("tiles {:016x} heights {:016x} layout {:016x}", d.tiles, d.heights, d.layout).into_bytes();
    s.out.len() as u32
}
