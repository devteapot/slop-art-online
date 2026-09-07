//! Independently scheduled maintenance, with a barrier in the fast action path.
//! The shared kernel determines deadlines and executes all physical effects.
use super::{client_access::{self, sim_client_clock, SimClientClock}, native_storage::{self, sim_native_head}, storage::{self, sim_run_store}};
use spacetimedb::{ReducerContext, ScheduleAt, Table, Timestamp};
use std::time::Duration;

#[spacetimedb::table(accessor = sim_physical_clock)]
pub struct SimPhysicalClock {
    #[primary_key]
    pub run: String,
    pub enabled: bool,
    pub next_world_ms: u64,
    pub alive: u64,
    pub pending_id: u64,
    pub world_deadline: Timestamp,
    pub action_transactions: u64,
    pub world_transactions: u64,
    pub action_actors_loaded: u64,
    pub max_action_actors_loaded: u64,
}

#[spacetimedb::table(accessor = sim_world_wake, scheduled(sim_world_pulse))]
pub struct SimWorldWake {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub scheduled_at: ScheduleAt,
    pub run: String,
}

pub(super) fn cancel(ctx: &ReducerContext, run: &str) {
    if let Some(mut state) = ctx.db.sim_physical_clock().run().find(run.to_owned()) {
        if state.pending_id != 0 { ctx.db.sim_world_wake().id().delete(state.pending_id); }
        state.pending_id = 0;
        ctx.db.sim_physical_clock().run().update(state);
    }
}

/// Full-world operations can alter any deadline or dependency. Update the small
/// barrier row atomically with their physical rows. Action-only commits retain it.
pub(super) fn refresh(ctx: &ReducerContext, world: &simulation::World, advanced_at: Timestamp) {
    let Some(mut state) = ctx.db.sim_physical_clock().run().find(&world.run) else { return; };
    state.world_transactions += 1;
    state.alive = world.players.iter().filter(|p|p.health>0).count() as u64;
    state.next_world_ms = world.next_maintenance_ms();
    let paused = ctx.db.sim_client_clock().run().find(&world.run).is_none_or(|clock|clock.paused);
    let arm = state.enabled && !paused && !world.stopped && state.next_world_ms > world.timing.time_ms;
    let deadline = advanced_at + Duration::from_millis(state.next_world_ms.saturating_sub(world.timing.time_ms));
    if state.pending_id != 0 && (!arm || deadline != state.world_deadline) {
        ctx.db.sim_world_wake().id().delete(state.pending_id);
        state.pending_id = 0;
    }
    if arm && state.pending_id == 0 {
        state.world_deadline = deadline;
        state.pending_id = ctx.db.sim_world_wake().insert(SimWorldWake {
            id:0,run:world.run.clone(),scheduled_at:deadline.into(),
        }).id;
    }
    ctx.db.sim_physical_clock().run().update(state);
}

#[spacetimedb::reducer]
pub fn sim_configure_physical_clock(ctx: &ReducerContext, run: String, enabled: bool) -> Result<(),String> {
    storage::require_owner(ctx,&run)?;
    let clock = ctx.db.sim_client_clock().run().find(&run).ok_or("clock missing")?;
    if !clock.paused { return Err("pause before changing physical clock mode".into()); }
    if !storage::is_native(ctx,&run)? { return Err("physical clock requires native storage".into()); }
    let (row,mut world) = storage::load_clock(ctx,&run)?;
    if !world.participant_mode || world.players.iter().any(|p|!world.client_controlled(p.id)) {
        return Err("physical clock requires client controllers".into());
    }
    if let Some(mut state) = ctx.db.sim_physical_clock().run().find(&run) {
        state.enabled = enabled;
        ctx.db.sim_physical_clock().run().update(state);
    } else {
        ctx.db.sim_physical_clock().insert(SimPhysicalClock {
            run,enabled,next_world_ms:world.timing.time_ms,alive:0,pending_id:0,world_deadline:ctx.timestamp,
            action_transactions:0,world_transactions:0,action_actors_loaded:0,max_action_actors_loaded:0,
        });
    }
    // Disabling does not discard unsettled elapsed time. The next full shared
    // advance consumes it, including across pause/resume or a reload.
    if enabled && world.timing.maintenance_ms.is_none() { world.timing.maintenance_ms=Some(world.timing.time_ms); }
    super::save(ctx,row,world);
    Ok(())
}

/// Some means the local transaction handled the opportunity; None asks the
/// existing full shared path to resolve due maintenance or broader dependencies.
pub(super) fn advance_actions(ctx: &ReducerContext, clock: &SimClientClock) -> Result<Option<bool>,String> {
    let Some(mut state) = ctx.db.sim_physical_clock().run().find(&clock.run).filter(|s|s.enabled) else { return Ok(None); };
    let mut row = ctx.db.sim_run_store().id().find(&clock.run).ok_or("run missing")?;
    let head = ctx.db.sim_native_head().run().find(&clock.run).ok_or("native head missing")?;
    if head.stopped { return Ok(Some(false)); }
    let delta = ctx.timestamp.duration_since(row.last_advanced_at).ok_or("clock moved backwards")?.as_millis() as u64;
    if delta == 0 { return Ok(Some(false)); }
    let until = head.time_ms.checked_add(delta).ok_or("physical clock overflow")?;
    if delta > 60_000 || until >= state.next_world_ms { return Ok(None); }
    let Some(outcome) = native_storage::advance_actions(ctx,&clock.run,head,delta,state.alive)? else { return Ok(None); };
    row.last_advanced_at += Duration::from_millis(delta);
    ctx.db.sim_run_store().id().update(row);
    state.alive = outcome.alive;
    state.action_transactions += 1;
    state.action_actors_loaded += outcome.actors_loaded;
    state.max_action_actors_loaded = state.max_action_actors_loaded.max(outcome.actors_loaded);
    if outcome.stopped && state.pending_id != 0 {
        ctx.db.sim_world_wake().id().delete(state.pending_id);
        state.pending_id = 0;
    }
    ctx.db.sim_physical_clock().run().update(state);
    Ok(Some(false))
}

#[spacetimedb::reducer]
pub fn sim_world_pulse(ctx: &ReducerContext, wake: SimWorldWake) -> Result<(),String> {
    if ctx.sender()!=ctx.identity() { return Err("scheduled world maintenance only".into()); }
    let Some(mut state)=ctx.db.sim_physical_clock().run().find(&wake.run) else { return Ok(()); };
    if !state.enabled || state.pending_id!=wake.id { return Ok(()); }
    state.pending_id=0;
    ctx.db.sim_world_wake().id().delete(wake.id);
    ctx.db.sim_physical_clock().run().update(state);
    let clock=ctx.db.sim_client_clock().run().find(&wake.run).ok_or("clock missing")?;
    if !clock.paused { client_access::advance_pulse(ctx,clock)?; }
    Ok(())
}
