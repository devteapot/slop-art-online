//! Act outcomes for a person's client (`act_outcome`, `my_act_outcomes`; docs/PERCEPTION.md,
//! "Act outcomes"): how an act or a death came out, as codes (`living_rules::outcome`) and the
//! rules' words, keyed by the experience line that tells it. The line stays the record a mind
//! and the log read; this row is what a client draws a note or a death screen from, so it does
//! not parse the line's English.

use crate::tables::*;
use spacetimedb::{ReducerContext, Table};

/// What one outcome says.
pub struct Told<'a> {
    pub kind: &'static str,
    pub ok: bool,
    pub skill: &'a str,
    pub code: &'static str,
    pub what: &'a str,
    pub why: &'a str,
    pub other: u32,
}

/// Write the row of line `line` (just written for `observer`), when a person plays it now
/// (`force`: whoever holds it, for a death).
pub fn write(ctx: &ReducerContext, observer: u32, line: u64, now: u64, t: &Told, force: bool) {
    if !force && crate::combat::human(ctx, observer).is_none() {
        return;
    }
    let cut = |s: &str, n: usize| s.chars().take(n).collect::<String>();
    ctx.db.act_outcome().insert(ActOutcome {
        id: line,
        observer,
        at_ms: now,
        kind: t.kind.into(),
        ok: t.ok,
        skill: cut(t.skill, 64),
        code: t.code.into(),
        what: cut(t.what, 200),
        why: cut(t.why, 400),
        other: t.other,
    });
}

/// The row of a line that left `my_experience`.
pub fn dropped(ctx: &ReducerContext, line: u64) {
    ctx.db.act_outcome().id().delete(line);
}

/// A person no longer plays `character` (they joined with another): its rows go.
pub fn forget(ctx: &ReducerContext, character: u32) {
    for id in ctx.db.act_outcome().observer().filter(character).map(|o| o.id).collect::<Vec<_>>() {
        ctx.db.act_outcome().id().delete(id);
    }
}
