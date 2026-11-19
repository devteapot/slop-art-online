//! Opt-in module-log markers for the input latency experiment. Nothing is replicated or stored
//! in game tables. A marker from a reducer that rolled back is still an attempted operation.

use spacetimedb::ReducerContext;
use std::{cell::Cell, fmt::Arguments};

thread_local! {
    static LAST_MARK: Cell<Option<i64>> = const { Cell::new(None) };
}

/// Called after the tick's last write. View refresh and commit are later, in the host.
pub fn end_tick(ctx: &ReducerContext, tick: u64, now: u64) {
    let reducer_us = crate::common::stamp(ctx);
    if LAST_MARK.with(|last| last.take()) == Some(reducer_us) {
        log::info!("input_latency tick_end 0 {tick} {reducer_us} {tick} {now}");
    }
}

pub fn nav(ctx: &ReducerContext, actor: u32, stage: &str, key: u64, detail: Arguments<'_>) {
    let from = crate::common::laws(ctx).latency_nav_from;
    if from != 0 && (actor == 0 || actor >= from) {
        mark(ctx, actor, stage, key, detail);
    }
}

pub fn fast(ctx: &ReducerContext, actor: u32, stage: &str, key: u64, detail: Arguments<'_>) {
    if crate::common::laws(ctx).latency_fast {
        mark(ctx, actor, stage, key, detail);
    }
}

fn mark(ctx: &ReducerContext, actor: u32, stage: &str, key: u64, detail: Arguments<'_>) {
    let clock = crate::common::clock(ctx);
    let reducer_us = crate::common::stamp(ctx);
    LAST_MARK.with(|last| last.set(Some(reducer_us)));
    // The logger supplies its own wall timestamp. The reducer timestamp is the transaction's
    // common start stamp. The clock row can still hold the preceding tick inside a tick reducer.
    log::info!("input_latency {stage} {actor} {key} {reducer_us} {} {} {detail}", clock.tick, clock.last_ms);
}
