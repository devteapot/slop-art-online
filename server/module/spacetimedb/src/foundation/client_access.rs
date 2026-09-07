//! Run-scoped browser grants. All checks use authenticated ctx.sender(), never a claimed actor.
use super::{save, sim_audit__view, storage, SimRun};
use simulation::{Controller, Decision, World};
use spacetimedb::{Identity, ReducerContext, ScheduleAt, SpacetimeType, Table, ViewContext};

#[spacetimedb::table(accessor = sim_client_access,
    index(accessor = actor_owner, btree(columns = [run, actor])))]
pub struct SimClientAccess {
    #[primary_key]
    pub identity: Identity,
    pub run: String,
    pub observer: bool,
    pub actor: u32,
}
#[spacetimedb::table(accessor = sim_client_clock, scheduled(sim_client_pulse))]
pub struct SimClientClock {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[unique]
    pub run: String,
    pub scheduled_at: ScheduleAt,
    pub paused: bool,
    pub evidence_mode: String,
}
#[derive(SpacetimeType)]
pub struct SimClientSnapshot {
    pub run: String,
    pub tick: u64,
    pub body: String,
}

// Retained legacy schema for existing normalized archives. New publication
// uses independent native rows; explicit migration collects this old cache.
#[spacetimedb::table(accessor = sim_participant_cache)]
pub struct SimParticipantCache {
    #[primary_key]
    pub key: String,
    pub run: String,
    pub tick: u64,
    pub body: String,
}
pub(super) fn world(ctx: &ReducerContext, run: &str) -> Result<(SimRun, World), String> {
    let (row, w) = storage::load(ctx, run)?;
    if w.version != simulation::VERSION {
        return Err("old rules are read-only".into());
    }
    Ok((row, w))
}
pub(super) fn grant(ctx: &ReducerContext) -> Result<SimClientAccess, String> {
    ctx.db
        .sim_client_access()
        .identity()
        .find(ctx.sender())
        .ok_or("this identity has no run access".into())
}
#[spacetimedb::reducer]
pub fn sim_grant_client(
    ctx: &ReducerContext,
    run: String,
    identity: Identity,
    observer: bool,
    actor: u32,
) -> Result<(), String> {
    let (row, mut w) = world(ctx, &run)?;
    if row.owner != ctx.sender() {
        return Err("only the run operator grants access".into());
    }
    if !(observer && actor == 0)
        && !w
            .players
            .iter()
            .any(|p| p.id == actor && (w.participant_mode || p.controller == Controller::Human))
    {
        return Err("grant requires an eligible character".into());
    }
    // A human character has at most one client owner. Observer-only peers can inspect it.
    if !observer
        && ctx
            .db
            .sim_client_access()
            .actor_owner()
            .filter((run.as_str(), actor))
            .any(|g| !g.observer && g.identity != identity)
    {
        return Err("character already controlled by another client".into());
    }
    let previous = ctx.db.sim_client_access().identity().find(identity);
    if let Some(old) = &previous {
        if !old.observer && (old.run != run || old.actor != actor) {
            let (oldrow, mut oldworld) = world(ctx, &old.run)?;
            if oldrow.owner != ctx.sender() {
                return Err("cannot replace another operator's grant".into());
            }
            if old.run == run {
                w.change_control(old.actor)?;
            } else {
                oldworld.change_control(old.actor)?;
                save(ctx, oldrow, oldworld);
            }
        }
    }
    if !observer
        && previous
            .as_ref()
            .is_none_or(|old| old.observer || old.run != run || old.actor != actor)
    {
        w.change_control(actor)?;
    }
    save(ctx, row, w);
    let access = SimClientAccess {
        identity,
        run,
        observer,
        actor,
    };
    if ctx
        .db
        .sim_client_access()
        .identity()
        .find(identity)
        .is_some()
    {
        ctx.db.sim_client_access().identity().update(access);
    } else {
        ctx.db.sim_client_access().insert(access);
    }
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_revoke_client(ctx: &ReducerContext, identity: Identity) -> Result<(), String> {
    let access = ctx
        .db
        .sim_client_access()
        .identity()
        .find(identity)
        .ok_or("grant not found")?;
    let (row, mut w) = world(ctx, &access.run)?;
    if row.owner != ctx.sender() {
        return Err("only operator revokes grants".into());
    }
    if !access.observer {
        w.change_control(access.actor)?;
        save(ctx, row, w);
    }
    ctx.db.sim_client_access().identity().delete(identity);
    Ok(())
}
#[spacetimedb::view(accessor = sim_my_snapshot, public)]
pub fn sim_my_snapshot(ctx: &ViewContext) -> Option<SimClientSnapshot> {
    let access = ctx.db.sim_client_access().identity().find(ctx.sender())?;
    let (w,can_participate) = if access.observer {
        (storage::world_for_view(ctx, &access.run)?,None)
    } else {
        let (world,can)=storage::participant_for_view(ctx,&access.run,access.actor)?;
        (world,Some(can))
    };
    let events = if access.observer {
        let mut events: Vec<simulation::Event> = ctx
            .db
            .sim_audit()
            .run_and_event()
            .filter((&access.run, w.next_event.saturating_sub(180)..w.next_event))
            .filter_map(|e| serde_json::from_str(&e.json).ok())
            .collect();
        events.sort_by_key(|e| e.id);
        events
    } else {
        vec![]
    };
    let mut v = simulation::client_view::snapshot(&w, access.observer, access.actor, &events);
    if let Some(can)=can_participate {v["can_participate"]=serde_json::json!(can);}
    if w.participant_mode && !access.observer {
        v["participant"] = w.participant_snapshot(access.actor, 0, 256).ok()?;
    }
    if let Some(clock) = ctx.db.sim_client_clock().run().find(&access.run) {
        v["paused"] = serde_json::json!(clock.paused);
        v["evidence_mode"] = serde_json::json!(clock.evidence_mode);
    }
    Some(SimClientSnapshot {
        run: access.run,
        tick: w.tick,
        body: v.to_string(),
    })
}
#[spacetimedb::reducer]
pub fn sim_client_intent(ctx: &ReducerContext, decision: String) -> Result<(), String> {
    let access = grant(ctx)?;
    if access.observer {
        return Err("enter participant mode to control your character".into());
    }
    if decision.len() > 50_000 {return Err("intent too large".into());}
    if storage::is_native(ctx,&access.run)? && super::native_storage::participant_mode(ctx,&access.run)? {
        let d:Decision=serde_json::from_str(&decision).map_err(|e|e.to_string())?;
        return super::native_storage::intent(ctx,&access.run,access.actor,d);
    }
    let (row,mut w)=world(ctx,&access.run)?;
    if w.participant_mode {
        let d:Decision=serde_json::from_str(&decision).map_err(|e|e.to_string())?;
        w.participant_client_intent(access.actor,d)?;
        save(ctx,row,w);
        return Ok(());
    }
    let input=w.event(Some(access.actor),"human_input",vec![],serde_json::json!({"raw":decision,"source":"authenticated Bevy client","identity":ctx.sender().to_hex().to_string()}));
    let result = serde_json::from_str::<Decision>(&decision)
        .map_err(|e| e.to_string())
        .and_then(|d| w.submit(access.actor, Controller::Human, d, Some(input)));
    if let Err(reason) = result {
        w.event(
            Some(access.actor),
            "intent_rejected",
            vec![input],
            serde_json::json!({"reason":reason}),
        );
    }
    save(ctx, row, w);
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_setup_client_clock(
    ctx: &ReducerContext,
    run: String,
    evidence_mode: String,
) -> Result<(), String> {
    let (row, _) = world(ctx, &run)?;
    if row.owner != ctx.sender() {
        return Err("only operator configures the clock".into());
    }
    if !["live_fixture", "live_bootstrap", "live_model"].contains(&evidence_mode.as_str()) {
        return Err("invalid evidence label".into());
    }
    if ctx.db.sim_client_clock().run().find(&run).is_some() {
        return Err("clock already exists".into());
    }
    ctx.db.sim_client_clock().insert(SimClientClock {
        id: 0,
        run,
        scheduled_at: std::time::Duration::from_millis(simulation::timing::UPDATE_MS).into(),
        paused: true,
        evidence_mode,
    });
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_client_control(ctx: &ReducerContext, command: String) -> Result<(), String> {
    let access = grant(ctx)?;
    if !access.observer {
        return Err("observer privilege required for time controls".into());
    }
    let mut clock = ctx
        .db
        .sim_client_clock()
        .run()
        .find(&access.run)
        .ok_or("clock not configured")?;
    match command.as_str() {
        "pause" => clock.paused = true,
        "resume" => clock.paused = false,
        "step" => {
            if !clock.paused {
                return Err("pause before stepping".into());
            }
            let (row, mut w) = world(ctx, &access.run)?;
            w.advance_ms(simulation::timing::UPDATE_MS);
            save(ctx, row, w);
        }
        _ => return Err("unknown clock command".into()),
    }
    let (mut row, w) = world(ctx, &clock.run)?;
    row.last_advanced_at = ctx.timestamp;
    save(ctx, row, w);
    ctx.db.sim_client_clock().id().update(clock);
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_client_pulse(ctx: &ReducerContext, clock: SimClientClock) -> Result<(), String> {
    if ctx.sender() != ctx.identity() {
        return Err("scheduled clock only".into());
    }
    let mut current = ctx
        .db
        .sim_client_clock()
        .run()
        .find(&clock.run)
        .ok_or("clock missing")?;
    if !current.paused {
        let (mut row, mut w) = super::measured("clock.load", || world(ctx, &clock.run))?;
        if !w.stopped {
            let elapsed = ctx
                .timestamp
                .duration_since(row.last_advanced_at)
                .ok_or("clock moved backwards")?;
            let delta_ms = elapsed.as_millis() as u64;
            if delta_ms > 60_000 {
                // An outage requires explicit recovery; never silently discard elapsed time.
                current.paused = true;
                ctx.db.sim_client_clock().id().update(current);
                w.event(
                    None,
                    "clock_recovery_required",
                    vec![],
                    serde_json::json!({"elapsed_ms":delta_ms}),
                );
            } else {
                super::measured("clock.advance", || super::advance_clock(&mut w, delta_ms));
                row.last_advanced_at += std::time::Duration::from_millis(delta_ms);
            }
            super::measured("clock.save", || save(ctx, row, w));
        }
    }
    Ok(())
}

#[spacetimedb::reducer]
pub fn sim_operator_clock(
    ctx: &ReducerContext,
    run: String,
    tick_ms: u64,
    paused: bool,
) -> Result<(), String> {
    let (mut row, mut w) = world(ctx, &run)?;
    if row.owner != ctx.sender() {
        return Err("operator only".into());
    }
    if !(50..=60_000).contains(&tick_ms) {
        return Err("clock interval must be 50..60000 milliseconds".into());
    }
    let mut clock = ctx
        .db
        .sim_client_clock()
        .run()
        .find(&run)
        .ok_or("clock missing")?;
    clock.scheduled_at = std::time::Duration::from_millis(tick_ms).into();
    clock.paused = paused;
    row.last_advanced_at = ctx.timestamp;
    ctx.db.sim_client_clock().id().update(clock);
    w.event(
        None,
        "clock_configured",
        vec![],
        serde_json::json!({"tick_ms":tick_ms,"paused":paused}),
    );
    save(ctx, row, w);
    Ok(())
}

#[spacetimedb::reducer]
pub fn sim_operator_pause(ctx: &ReducerContext, run: String) -> Result<(), String> {
    storage::require_owner(ctx, &run)?;
    if let Some(mut clock) = ctx.db.sim_client_clock().run().find(&run) {
        clock.paused = true;
        ctx.db.sim_client_clock().id().update(clock);
    }
    Ok(())
}

#[spacetimedb::view(accessor=sim_participant_state, public)]
pub fn sim_participant_state(ctx: &ViewContext) -> Option<SimClientSnapshot> {
    super::participant_delivery::legacy_status(ctx)
}
#[spacetimedb::reducer]
pub fn sim_participant_command(ctx: &ReducerContext, request: String) -> Result<(), String> {
    let access = grant(ctx)?;
    if access.observer {
        return Err("participant ownership required".into());
    }
    if request.len() > 50_000 {
        return Err("request too large".into());
    }
    let request: simulation::participant::Request =
        serde_json::from_str(&request).map_err(|e| e.to_string())?;
    if storage::is_native(ctx, &access.run)? {
        return super::native_storage::command(ctx, &access.run, access.actor, request);
    }
    let (row, mut w) = world(ctx, &access.run)?;
    w.participant_apply(access.actor, request)?;
    save(ctx, row, w);
    Ok(())
}
