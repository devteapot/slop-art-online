//! Breath (`stamina`) and focus on the vitals row (docs/STAMINA.md): spends, the drain of a run
//! and of a held guard, and their end. Every write here is an event (a spend, a drain starting
//! or stopping); the refill is the row's rate from `*_from_ms`, so nothing is written per tick.
//! The law's numbers are `pools(a)` (`common::pools_of`); tiredness caps breath.

use crate::common;
use crate::tables::*;
use living_rules::pools::{level, Pools};
use spacetimedb::ReducerContext;

/// Breath and focus now.
pub fn levels(v: &Vitals, now: u64) -> (f32, f32) {
    (
        level(v.stamina, v.stamina_rate, v.stamina_from_ms, v.at_ms, v.stamina_max, now),
        level(v.focus, v.focus_rate, v.focus_from_ms, v.at_ms, v.focus_max, now),
    )
}

/// Re-anchor the pools at `now` (the row's `at_ms` moves to `now` with the needs): their
/// levels, a drain's tiredness (each point of breath a run or a guard took since the last anchor
/// costs `tires_per_point` energy, already settled into `energy` at `now`), and the caps for
/// the tiredness now. `p` is the body's `pools` law.
pub fn settle(v: &mut Vitals, p: &Pools, energy_now: f32, now: u64) -> f32 {
    let (s, f) = levels(v, now);
    let drained = if v.stamina_rate < 0.0 { (v.stamina - s).max(0.0) } else { 0.0 };
    v.stamina = s;
    v.focus = f;
    // A refill already under way keeps its start; a drain continues from the new anchor.
    if v.stamina_rate < 0.0 {
        v.stamina_from_ms = now;
    }
    if v.focus_rate < 0.0 {
        v.focus_from_ms = now;
    }
    let energy = (energy_now - drained * p.breath.tires_per_point).clamp(0.0, 100.0);
    v.stamina_max = p.stamina.cap(energy);
    v.focus_max = p.focus.cap(energy);
    v.stamina = v.stamina.min(v.stamina_max);
    v.focus = v.focus.min(v.focus_max);
    // The refill at this tiredness (an exhausted body's comes back slower). A pool not draining
    // always refills: a row that never spent (rate 0, the migration's default) and was cut by a
    // lower cap comes back too, from its anchor.
    if v.stamina_rate >= 0.0 {
        v.stamina_rate = p.stamina.regen(energy);
    }
    if v.focus_rate >= 0.0 {
        v.focus_rate = p.focus.regen(energy);
    }
    energy
}

/// Take `amount` from `pool` ("stamina" or "focus") at `now`: its refill starts after the
/// pool's delay (a drain under way goes on). Breath spent tires a little.
pub fn spend(ctx: &ReducerContext, id: u32, pool: &str, amount: f32, now: u64) {
    let Some(mut v) = ctx.db.vitals().id().find(id) else { return };
    let p = common::pools_of(ctx, id, now);
    common::settle(ctx, &mut v, now);
    if pool == "focus" {
        v.focus = (v.focus - amount).max(0.0);
        if v.focus_rate >= 0.0 {
            v.focus_rate = p.focus.regen(v.energy);
            v.focus_from_ms = now + p.focus.delay_ms as u64;
        }
    } else {
        v.stamina = (v.stamina - amount).max(0.0);
        v.energy = (v.energy - amount * p.breath.tires_per_point).clamp(0.0, 100.0);
        if v.stamina_rate >= 0.0 {
            v.stamina_rate = p.stamina.regen(v.energy);
            v.stamina_from_ms = now + p.stamina.delay_ms as u64;
        }
    }
    v.rate_key = 0;
    ctx.db.vitals().id().update(v);
}

/// Start draining breath at `per_s` a second from `now` (a run, a held guard).
pub fn drain(ctx: &ReducerContext, id: u32, per_s: f32, now: u64) {
    let Some(mut v) = ctx.db.vitals().id().find(id) else { return };
    common::settle(ctx, &mut v, now);
    v.stamina_rate = -per_s;
    v.stamina_from_ms = now;
    ctx.db.vitals().id().update(v);
}

/// Stop a drain at `now`: breath comes back after the delay. Nothing is written when none is
/// under way.
pub fn ease(ctx: &ReducerContext, id: u32, now: u64) {
    let Some(mut v) = ctx.db.vitals().id().find(id) else { return };
    if v.stamina_rate >= 0.0 {
        return;
    }
    let p = common::pools_of(ctx, id, now);
    common::settle(ctx, &mut v, now);
    v.stamina_rate = p.stamina.regen(v.energy);
    v.stamina_from_ms = now + p.stamina.delay_ms as u64;
    ctx.db.vitals().id().update(v);
}

/// Breath now (the authority's own row).
pub fn stamina_now(ctx: &ReducerContext, id: u32, now: u64) -> f32 {
    ctx.db.vitals().id().find(id).map_or(0.0, |v| levels(&v, now).0)
}
