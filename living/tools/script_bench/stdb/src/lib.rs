//! Calibration module: the same bench code inside a real SpacetimeDB 2.14.1 module, so the
//! wasmtime harness can be related to the host's reducer timing and energy (fuel).
//! Not the full authority: it links living-rules and the bench, nothing else.
//!
//!   bench_init(engine)        compile/load an engine (timed by LogStopwatch)
//!   bench(engine, law, n)     n calls of a law (timed by LogStopwatch); energy per reducer
//!                             call is in the caller's v1 TransactionUpdate (stdb_energy.py)
//! Engine and law ids: sb_bench::Kind and sb_bench::Law. Admin (the publisher) only.

use sb_bench::{fixtures, Kind, Law};
use spacetimedb::log_stopwatch::LogStopwatch;
use spacetimedb::{Identity, ReducerContext, Table};
use std::cell::RefCell;

#[spacetimedb::table(accessor = bench_admin)]
pub struct BenchAdmin {
    #[primary_key]
    pub id: u8,
    pub admin: Identity,
}

struct State {
    fx: fixtures::Fixtures,
    engines: Vec<Option<Box<dyn sb_bench::Engine>>>,
    cursor: usize,
}

thread_local! {
    static STATE: RefCell<Option<State>> = const { RefCell::new(None) };
}

fn require_admin(ctx: &ReducerContext) -> Result<(), String> {
    match ctx.db.bench_admin().id().find(0) {
        Some(a) if a.admin == ctx.sender() => Ok(()),
        _ => Err("admin only".into()),
    }
}

fn with_state<R>(f: impl FnOnce(&mut State) -> R) -> R {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        let st = s.get_or_insert_with(|| State { fx: fixtures::build(), engines: (0..Kind::ALL.len()).map(|_| None).collect(), cursor: 0 });
        f(st)
    })
}

#[spacetimedb::reducer(init)]
pub fn init(ctx: &ReducerContext) {
    ctx.db.bench_admin().insert(BenchAdmin { id: 0, admin: ctx.sender() });
}

#[spacetimedb::reducer]
pub fn bench_init(ctx: &ReducerContext, engine: u32) -> Result<(), String> {
    require_admin(ctx)?;
    let kind = Kind::from_u32(engine).ok_or("unknown engine")?;
    with_state(|_| ());
    let sw = LogStopwatch::new(&format!("init {}", kind.name()));
    let e = sb_bench::make(kind)?;
    drop(sw);
    with_state(|s| s.engines[engine as usize] = Some(e));
    Ok(())
}

#[spacetimedb::reducer]
pub fn bench(ctx: &ReducerContext, engine: u32, law: u32, n: u32) -> Result<(), String> {
    require_admin(ctx)?;
    let kind = Kind::from_u32(engine).ok_or("unknown engine")?;
    let law = Law::from_u32(law).ok_or("unknown law")?;
    with_state(|s| {
        if s.engines[engine as usize].is_none() {
            s.engines[engine as usize] = Some(sb_bench::make(kind)?);
            log::info!("bench: {} was not initialized; initialized it outside the timed span", kind.name());
        }
        let e = s.engines[engine as usize].as_deref_mut().unwrap();
        let sw = LogStopwatch::new(&format!("{} {} x{n}", kind.name(), law.name()));
        let sum = sb_bench::run(e, &s.fx, law, &mut s.cursor, n);
        drop(sw);
        log::info!("bench {} {} x{n} checksum {sum:016x}", kind.name(), law.name());
        Ok(())
    })
}

/// Equivalence inside the real host: the digest of a law's outputs over all fixtures.
#[spacetimedb::reducer]
pub fn bench_digest(ctx: &ReducerContext, engine: u32, law: u32) -> Result<(), String> {
    require_admin(ctx)?;
    let kind = Kind::from_u32(engine).ok_or("unknown engine")?;
    let law = Law::from_u32(law).ok_or("unknown law")?;
    with_state(|s| {
        if s.engines[engine as usize].is_none() {
            s.engines[engine as usize] = Some(sb_bench::make(kind)?);
        }
        let e = s.engines[engine as usize].as_deref_mut().unwrap();
        let text = sb_bench::dump(e, &s.fx, law);
        log::info!("digest {} {} {:016x}", kind.name(), law.name(), sb_bench::digest(&text));
        Ok(())
    })
}
