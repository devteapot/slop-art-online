//! A wasm32-unknown-unknown bench module: no imports, a few exports the host (sb-host, under
//! SpacetimeDB's wasmtime configuration) drives. Built once per engine feature.

use sb_bench::{fixtures, Kind, Law};

struct State {
    fx: fixtures::Fixtures,
    engines: Vec<Option<Box<dyn sb_bench::Engine>>>,
    buf: Vec<u8>,
    cursor: usize,
}

static mut STATE: Option<State> = None;

fn state() -> &'static mut State {
    // Single-threaded module; the host calls one export at a time.
    unsafe { (*(&raw mut STATE)).get_or_insert_with(|| State { fx: fixtures::build(), engines: (0..Kind::ALL.len()).map(|_| None).collect(), buf: Vec::new(), cursor: 0 }) }
}

/// Build the fixtures (kept apart from engine start-up in the timings).
#[no_mangle]
pub extern "C" fn sb_fixtures() -> u32 {
    state().fx.rates.len() as u32
}

/// Compile/load an engine. 0 on success; else the error text is in `sb_buf`.
#[no_mangle]
pub extern "C" fn sb_init(kind: u32) -> u32 {
    let s = state();
    let Some(k) = Kind::from_u32(kind) else { return 2 };
    match sb_bench::make(k) {
        Ok(e) => {
            s.engines[kind as usize] = Some(e);
            0
        },
        Err(err) => {
            s.buf = err.into_bytes();
            1
        },
    }
}

/// Run `n` calls of a law; returns a checksum.
#[no_mangle]
pub extern "C" fn sb_run(kind: u32, law: u32, n: u32) -> u64 {
    let s = state();
    let e = s.engines[kind as usize].as_deref_mut().expect("engine not initialized");
    sb_bench::run(e, &s.fx, Law::from_u32(law).expect("law"), &mut s.cursor, n)
}

/// Write a law's canonical outputs over all fixtures into `sb_buf`; returns its length.
#[no_mangle]
pub extern "C" fn sb_dump(kind: u32, law: u32) -> u32 {
    let s = state();
    let e = s.engines[kind as usize].as_deref_mut().expect("engine not initialized");
    s.buf = sb_bench::dump(e, &s.fx, Law::from_u32(law).expect("law")).into_bytes();
    s.buf.len() as u32
}

#[no_mangle]
pub extern "C" fn sb_buf() -> u32 {
    state().buf.as_ptr() as u32
}
