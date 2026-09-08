//! Optional absolute deadlines. There is one pending wake per run; old callbacks
//! cannot advance a reconfigured clock. This changes cadence, never game rules.
use super::{
    client_access::{self, sim_client_clock, SimClientClock},
    storage,
};
use spacetimedb::{ReducerContext, ScheduleAt, Table, Timestamp};
use std::time::Duration;

#[spacetimedb::table(accessor = sim_clock_deadline)]
pub struct SimClockDeadline {
    #[primary_key]
    pub run: String,
    pub enabled: bool,
    pub period_ms: u64,
    pub pending_id: u64,
    pub next_deadline: Timestamp,
    pub wakes: u64,
    pub missed_slots: u64,
    pub lateness_us: u64,
    pub max_lateness_us: u64,
}
#[spacetimedb::table(accessor = sim_clock_wake, scheduled(sim_deadline_pulse))]
pub struct SimClockWake {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub scheduled_at: ScheduleAt,
    pub run: String,
}

/// Optional rational-frequency grid, separate from the legacy millisecond
/// control row. One row per configured run, with no client subscription.
#[spacetimedb::table(accessor = sim_clock_rate)]
pub struct SimClockRate {
    #[primary_key]
    pub run: String,
    pub hz: u32,
    pub epoch: Timestamp,
    pub next_slot: u64,
}

fn slot_us(slot: u64, hz: u32) -> u64 {
    ((u128::from(slot) * 1_000_000) / u128::from(hz)) as u64
}

fn next_slot(elapsed_us: u64, current: u64, hz: u32) -> u64 {
    // Invert floor(slot * 1e6 / hz), including exact deadline boundaries.
    let at_or_before = ((u128::from(elapsed_us) + 1) * u128::from(hz) - 1) / 1_000_000;
    (at_or_before as u64 + 1).max(current + 1)
}

pub(super) fn enabled(ctx: &ReducerContext, run: &str) -> bool {
    ctx.db
        .sim_clock_deadline()
        .run()
        .find(run.to_owned())
        .is_some_and(|s| s.enabled)
}
fn arm(ctx: &ReducerContext, state: &mut SimClockDeadline) {
    let wake = ctx.db.sim_clock_wake().insert(SimClockWake {
        id: 0,
        scheduled_at: state.next_deadline.into(),
        run: state.run.clone(),
    });
    state.pending_id = wake.id;
}
// Called for explicit controls, not on every physical update. Starting a new
// grid is paired with the existing last_advanced_at reset on resume/configure.
pub(super) fn reset(ctx: &ReducerContext, clock: &mut SimClientClock, period_ms: u64) {
    let Some(mut state) = ctx.db.sim_clock_deadline().run().find(&clock.run) else {
        return;
    };
    if state.pending_id != 0 {
        ctx.db.sim_clock_wake().id().delete(state.pending_id);
    }
    state.pending_id = 0;
    if state.period_ms != period_ms {
        ctx.db.sim_clock_rate().run().delete(&clock.run);
    }
    state.period_ms = period_ms;
    state.next_deadline = ctx.timestamp + Duration::from_millis(period_ms);
    if let Some(mut rate) = ctx.db.sim_clock_rate().run().find(&clock.run) {
        rate.epoch = ctx.timestamp;
        rate.next_slot = 1;
        state.next_deadline = rate.epoch + Duration::from_micros(slot_us(1, rate.hz));
        ctx.db.sim_clock_rate().run().update(rate);
    }
    if state.enabled {
        // Keep the old control row/schema, with only a cheap minute heartbeat.
        clock.scheduled_at = Duration::from_secs(60).into();
        if !clock.paused {
            arm(ctx, &mut state);
        }
    } else {
        clock.scheduled_at = Duration::from_millis(period_ms).into();
    }
    ctx.db.sim_clock_deadline().run().update(state);
}
pub(super) fn period(ctx: &ReducerContext, clock: &SimClientClock) -> u64 {
    if let Some(state) = ctx.db.sim_clock_deadline().run().find(&clock.run) {
        return state.period_ms;
    }
    match clock.scheduled_at {
        ScheduleAt::Interval(value) => value.to_micros() as u64 / 1000,
        _ => simulation::timing::UPDATE_MS,
    }
}

#[spacetimedb::reducer]
pub fn sim_configure_deadline_clock(
    ctx: &ReducerContext,
    run: String,
    enabled: bool,
) -> Result<(), String> {
    storage::require_owner(ctx, &run)?;
    let mut clock = ctx
        .db
        .sim_client_clock()
        .run()
        .find(&run)
        .ok_or("clock missing")?;
    if !clock.paused {
        return Err("pause before changing clock mode".into());
    }
    let period_ms = period(ctx, &clock);
    if let Some(mut state) = ctx.db.sim_clock_deadline().run().find(&run) {
        state.enabled = enabled;
        ctx.db.sim_clock_deadline().run().update(state);
    } else {
        ctx.db.sim_clock_deadline().insert(SimClockDeadline {
            run,
            enabled,
            period_ms,
            pending_id: 0,
            next_deadline: ctx.timestamp,
            wakes: 0,
            missed_slots: 0,
            lateness_us: 0,
            max_lateness_us: 0,
        });
    }
    reset(ctx, &mut clock, period_ms);
    ctx.db.sim_client_clock().id().update(clock);
    Ok(())
}

fn next_offset(lateness_us: u64, period_us: u64) -> (u64, u64) {
    let missed = lateness_us / period_us;
    (missed, (missed + 1) * period_us)
}

/// Explicit owner-only experiment control. Reconfiguration always starts paused
/// on a fresh grid; changing the legacy period subsequently returns to ms mode.
#[spacetimedb::reducer]
pub fn sim_configure_clock_rate(ctx: &ReducerContext, run: String, hz: u32) -> Result<(), String> {
    storage::require_owner(ctx, &run)?;
    if !(1..=1000).contains(&hz) { return Err("clock rate must be 1..=1000 Hz".into()); }
    let mut clock = ctx.db.sim_client_clock().run().find(&run).ok_or("clock missing")?;
    let mut state = ctx.db.sim_clock_deadline().run().find(&run).ok_or("deadline clock missing")?;
    if !clock.paused || !state.enabled { return Err("pause and enable deadline clock before setting Hz".into()); }
    state.period_ms = 1000 / u64::from(hz);
    let period_ms = state.period_ms;
    ctx.db.sim_clock_deadline().run().update(state);
    let rate = SimClockRate { run:run.clone(), hz, epoch:ctx.timestamp, next_slot:1 };
    if ctx.db.sim_clock_rate().run().find(&run).is_some() { ctx.db.sim_clock_rate().run().update(rate); }
    else { ctx.db.sim_clock_rate().insert(rate); }
    reset(ctx, &mut clock, period_ms);
    ctx.db.sim_client_clock().id().update(clock);
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_deadline_pulse(ctx: &ReducerContext, wake: SimClockWake) -> Result<(), String> {
    if ctx.sender() != ctx.identity() {
        return Err("scheduled clock only".into());
    }
    let Some(mut state) = ctx.db.sim_clock_deadline().run().find(&wake.run) else {
        return Ok(());
    };
    if !state.enabled || state.pending_id != wake.id {
        return Ok(());
    }
    let clock = ctx
        .db
        .sim_client_clock()
        .run()
        .find(&wake.run)
        .ok_or("clock missing")?;
    state.pending_id = 0;
    // A fresh ID matters: the host deletes a one-shot row after this callback.
    ctx.db.sim_clock_wake().id().delete(wake.id);
    if !clock.paused {
        let late = ctx
            .timestamp
            .duration_since(state.next_deadline)
            .ok_or("early clock wake")?
            .as_micros() as u64;
        let (missed, next_deadline) = if let Some(mut rate) = ctx.db.sim_clock_rate().run().find(&wake.run) {
            let elapsed = ctx.timestamp.duration_since(rate.epoch).ok_or("clock before epoch")?.as_micros() as u64;
            let next = next_slot(elapsed, rate.next_slot, rate.hz);
            let missed = next - rate.next_slot - 1;
            rate.next_slot = next;
            let deadline = rate.epoch + Duration::from_micros(slot_us(next, rate.hz));
            ctx.db.sim_clock_rate().run().update(rate);
            (missed, deadline)
        } else {
            let (missed, offset) = next_offset(late, state.period_ms * 1000);
            (missed, state.next_deadline + Duration::from_micros(offset))
        };
        state.wakes += 1;
        state.missed_slots += missed;
        state.lateness_us = state.lateness_us.saturating_add(late);
        state.max_lateness_us = state.max_lateness_us.max(late);
        // Exactly one execution opportunity. Shared advancement accounts for all
        // actual elapsed time; no fake 50ms steps or unbounded action replay.
        let paused = client_access::advance_pulse(ctx, clock)?;
        if !paused {
            state.next_deadline = next_deadline;
            arm(ctx, &mut state);
        }
    }
    ctx.db.sim_clock_deadline().run().update(state);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rational_grid_has_no_drift_and_skips_outages_without_replay() {
        for hz in [30, 60] {
            for seconds in [1, 60, 1800, 28800] {
                assert_eq!(slot_us(seconds * u64::from(hz), hz), seconds * 1_000_000);
            }
            for slot in 1..=hz as u64 * 60 {
                let deadline = slot_us(slot, hz);
                for late in [0, 1, 16_667, 33_334, 60_000_001] {
                    let now = deadline + late;
                    let next = next_slot(now, slot, hz);
                    assert!(slot_us(next, hz) > now);
                    assert!(slot_us(next - 1, hz) <= now);
                    assert!(slot_us(next, hz) - now <= 1_000_000u64.div_ceil(hz as u64));
                }
            }
        }
    }
    #[test]
    fn deadlines_preserve_phase_skip_missed_slots_and_schedule_strictly_after_now() {
        for (late, missed, offset) in [
            (0, 0, 50_000),
            (49_999, 0, 50_000),
            (50_000, 1, 100_000),
            (175_000, 3, 200_000),
            (60_000_001, 1200, 60_050_000),
        ] {
            assert_eq!(next_offset(late, 50_000), (missed, offset));
            assert!(offset > late && offset - late <= 50_000);
            assert_eq!(offset % 50_000, 0);
        }
    }
}
