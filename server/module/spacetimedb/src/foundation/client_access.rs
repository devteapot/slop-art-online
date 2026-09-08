//! Run-scoped browser grants. All checks use authenticated ctx.sender(), never a claimed actor.
use super::{save, sim_audit__view, storage, SimRun};
use super::native_storage::{sim_native_actor, sim_native_head};
use super::storage::sim_run_store;
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
// Native grants need only the run header and addressed actor. Legacy archives
// keep their original adapter. Both sides of a handoff commit in one reducer,
// including epoch/evidence invalidation and durable audit publication.
enum GrantWorld {
    Native { run: String, participant: bool },
    Legacy(SimRun, World),
}
impl GrantWorld {
    fn load(ctx: &ReducerContext, run: &str) -> Result<(Identity, Self), String> {
        let row = ctx.db.sim_run_store().id().find(run.to_owned()).ok_or("run not found")?;
        if row.state == super::native_storage::FORMAT {
            let head = ctx.db.sim_native_head().run().find(run.to_owned()).ok_or("native head missing")?;
            if head.version != simulation::VERSION { return Err("old rules are read-only".into()); }
            Ok((row.owner, Self::Native { run: run.into(), participant: head.participant_mode }))
        } else {
            let (row, w) = world(ctx, run)?;
            Ok((row.owner, Self::Legacy(row, w)))
        }
    }
    fn eligible(&self, ctx: &ReducerContext, actor: u32) -> bool {
        match self {
            Self::Native { run, participant } => ctx.db.sim_native_actor().key()
                .find(format!("{run}:{actor}")).is_some_and(|p| *participant || p.human),
            Self::Legacy(_, w) => w.players.iter().any(|p| p.id == actor && (w.participant_mode || p.controller == Controller::Human)),
        }
    }
    fn change_control(&mut self, ctx: &ReducerContext, actor: u32) -> Result<(), String> {
        match self {
            Self::Native { run, participant: true } => super::native_storage::change_control(ctx, run, actor),
            Self::Native { run, participant: false } => {
                // The shared nonparticipant operation validates existence only.
                ctx.db.sim_native_actor().key().find(format!("{run}:{actor}"))
                    .ok_or("unknown actor")?;
                Ok(())
            }
            Self::Legacy(_, w) => w.change_control(actor),
        }
    }
    fn save(self, ctx: &ReducerContext) {
        if let Self::Legacy(row, w) = self { save(ctx, row, w); }
    }
}
#[spacetimedb::reducer]
pub fn sim_grant_client(
    ctx: &ReducerContext,
    run: String,
    identity: Identity,
    observer: bool,
    actor: u32,
) -> Result<(), String> {
    let (owner, mut w) = GrantWorld::load(ctx, &run)?;
    if owner != ctx.sender() {
        return Err("only the run operator grants access".into());
    }
    if !(observer && actor == 0)
        && !w.eligible(ctx, actor)
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
            let (oldowner, mut oldworld) = GrantWorld::load(ctx, &old.run)?;
            if oldowner != ctx.sender() {
                return Err("cannot replace another operator's grant".into());
            }
            if old.run == run {
                w.change_control(ctx, old.actor)?;
            } else {
                oldworld.change_control(ctx, old.actor)?;
                oldworld.save(ctx);
            }
        }
    }
    if !observer
        && previous
            .as_ref()
            .is_none_or(|old| old.observer || old.run != run || old.actor != actor)
    {
        w.change_control(ctx, actor)?;
    }
    w.save(ctx);
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
    let (owner, mut w) = GrantWorld::load(ctx, &access.run)?;
    if owner != ctx.sender() {
        return Err("only operator revokes grants".into());
    }
    if !access.observer {
        w.change_control(ctx, access.actor)?;
        w.save(ctx);
    }
    ctx.db.sim_client_access().identity().delete(identity);
    Ok(())
}
#[spacetimedb::table(accessor = sim_client_inspector)]
pub struct SimClientInspector {
    #[primary_key]
    pub identity: Identity,
    pub run: String,
    pub actor: Option<u32>,
}
#[spacetimedb::reducer]
pub fn sim_select_inspector(ctx: &ReducerContext, actor: Option<u32>) -> Result<(), String> {
    let access = grant(ctx)?;
    if !access.observer { return Err("observer privilege required for inspection selection".into()); }
    if let Some(actor) = actor {
        if storage::is_native(ctx, &access.run)? {
            if ctx.db.sim_native_actor().key().find(format!("{}:{actor}",access.run)).is_none() {
                return Err("unknown actor".into());
            }
        } else if !world(ctx, &access.run)?.1.players.iter().any(|p| p.id == actor) {
            return Err("unknown actor".into());
        }
    }
    let row = SimClientInspector { identity:ctx.sender(), run:access.run, actor };
    if ctx.db.sim_client_inspector().identity().find(ctx.sender()).is_some() {
        ctx.db.sim_client_inspector().identity().update(row);
    } else { ctx.db.sim_client_inspector().insert(row); }
    Ok(())
}
#[spacetimedb::view(accessor = sim_my_snapshot, public)]
pub fn sim_my_snapshot(ctx: &ViewContext) -> Option<SimClientSnapshot> {
    render_snapshot(ctx, true)
}
#[spacetimedb::view(accessor = sim_my_render_snapshot, public)]
pub fn sim_my_render_snapshot(ctx: &ViewContext) -> Option<SimClientSnapshot> {
    render_snapshot(ctx, false)
}
pub(super) fn render_snapshot(ctx: &ViewContext, include_history: bool) -> Option<SimClientSnapshot> {
    #[cfg(feature = "clock-profile")]
    let phase = spacetimedb::log_stopwatch::LogStopwatch::new("view.render.load");
    let access = ctx.db.sim_client_access().identity().find(ctx.sender())?;
    let inspected = ctx.db.sim_client_inspector().identity().find(ctx.sender())
        .filter(|row| row.run == access.run).and_then(|row| row.actor);
    let (w,can_participate) = if access.observer {
        (storage::observer_for_view(ctx, &access.run, inspected)?,None)
    } else {
        let (world,can)=storage::participant_for_view(ctx,&access.run,access.actor)?;
        (world,Some(can))
    };
    #[cfg(feature = "clock-profile")]
    drop(phase);
    #[cfg(feature = "clock-profile")]
    let phase = spacetimedb::log_stopwatch::LogStopwatch::new("view.render.projection");
    let events = if access.observer && include_history {
        // The pinned host tracks a range scan as a whole-table dependency.
        // The clock supplies exact contiguous event IDs, so point reads keep
        // unrelated action-admission appends outside this view's read set.
        let mut events: Vec<simulation::Event> = (w.next_event.saturating_sub(180).max(1)..w.next_event)
            .filter_map(|id| ctx.db.sim_audit().key().find(format!("{}:{id}", access.run)))
            .filter_map(|e| serde_json::from_str(&e.json).ok())
            .collect();
        events.sort_by_key(|e| e.id);
        events
    } else {
        vec![]
    };
    let mut v = if !include_history { simulation::client_view::live_render(&w, access.observer, access.actor, inspected) }
        else if access.observer { simulation::client_view::observer_render(&w, inspected, &events) }
        else { simulation::client_view::snapshot(&w, false, access.actor, &events) };
    if let Some(can)=can_participate {v["can_participate"]=serde_json::json!(can);}
    #[cfg(feature = "clock-profile")]
    drop(phase);
    #[cfg(feature = "clock-profile")]
    let phase = spacetimedb::log_stopwatch::LogStopwatch::new("view.render.status");
    if w.participant_mode && !access.observer {
        // Bevy renders the scoped player projection above. The participant
        // protocol has its own views and explicit reads; do not duplicate its
        // complete context and retained experience tail in every render frame.
        v["participant"] = w.participant_status(access.actor).ok()?;
    }
    if let Some(clock) = ctx.db.sim_client_clock().run().find(&access.run) {
        v["paused"] = serde_json::json!(clock.paused);
        v["evidence_mode"] = serde_json::json!(clock.evidence_mode);
    }
    #[cfg(feature = "clock-profile")]
    drop(phase);
    Some(SimClientSnapshot {
        run: access.run,
        tick: w.tick,
        body: super::measured("view.render.serialize", || v.to_string()),
    })
}

#[derive(SpacetimeType)]
pub struct SimClientRenderEvent {
    pub run: String,
    pub event: u64,
    pub body: String,
}
#[spacetimedb::view(accessor = sim_my_render_events, public)]
pub fn sim_my_render_events(ctx: &ViewContext) -> Vec<SimClientRenderEvent> {
    let Some(access) = ctx.db.sim_client_access().identity().find(ctx.sender()) else { return vec![]; };
    if access.observer {
        let end = super::native_storage::render_event_end(ctx, &access.run).or_else(||
            storage::observer_for_view(ctx, &access.run, None).map(|w| w.next_event));
        let Some(end) = end else { return vec![]; };
        (end.saturating_sub(180).max(1)..end).filter_map(|event| {
            let row = ctx.db.sim_audit().key().find(format!("{}:{event}", access.run))?;
            let body = if matches!(row.kind.as_str(), "model_request" | "model_result") {
                let value: simulation::Event = serde_json::from_str(&row.json).ok()?;
                simulation::client_view::observer_event(&value).to_string()
            } else { row.json };
            Some(SimClientRenderEvent {run:access.run.clone(),event,body})
        }).collect()
    } else {
        let memories = super::native_storage::render_memories(ctx, &access.run, access.actor).or_else(||
            storage::participant_for_view(ctx, &access.run, access.actor)
                .and_then(|(w,_)| w.players.iter().find(|p|p.id==access.actor).map(|p|p.memories.to_vec())));
        memories.unwrap_or_default().into_iter().map(|m| SimClientRenderEvent {
            run:access.run.clone(),event:m.source,
            body:simulation::research::redacted(serde_json::json!({"id":m.source,"tick":m.tick,
                "actor":access.actor,"kind":m.kind,"parents":[],"data":m.content})).to_string(),
        }).collect()
    }
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
    let period = super::deadline_clock::period(ctx, &clock);
    super::deadline_clock::reset(ctx, &mut clock, period);
    ctx.db.sim_client_clock().id().update(clock);
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_client_pulse(ctx: &ReducerContext, clock: SimClientClock) -> Result<(), String> {
    if ctx.sender() != ctx.identity() {
        return Err("scheduled clock only".into());
    }
    if super::deadline_clock::enabled(ctx, &clock.run) { return Ok(()); }
    let current = ctx
        .db
        .sim_client_clock()
        .run()
        .find(&clock.run)
        .ok_or("clock missing")?;
    advance_pulse(ctx, current).map(|_| ())
}

pub(super) fn advance_pulse(ctx: &ReducerContext, mut current: SimClientClock) -> Result<bool, String> {
    let mut paused = current.paused;
    if !current.paused {
        if let Some(paused) = super::physical_clock::advance_actions(ctx, &current)? { return Ok(paused); }
        let (mut row, mut w) = super::measured("clock.load", || storage::load_clock(ctx, &current.run))?;
        if !w.stopped {
            let elapsed = ctx
                .timestamp
                .duration_since(row.last_advanced_at)
                .ok_or("clock moved backwards")?;
            let delta_ms = elapsed.as_millis() as u64;
            if delta_ms > 60_000 {
                // An outage requires explicit recovery; never silently discard elapsed time.
                current.paused = true;
                paused = true;
                ctx.db.sim_client_clock().id().update(current);
                w.event(
                    None,
                    "clock_recovery_required",
                    vec![],
                    serde_json::json!({"elapsed_ms":delta_ms}),
                );
            } else {
                #[cfg(not(feature = "clock-scan"))]
                let selection = super::native_storage::select_clock(ctx, &w, delta_ms);
                #[cfg(feature = "clock-scan")]
                let selection = None;
                super::measured("clock.advance", || super::advance_clock(&mut w, delta_ms, selection.as_ref()));
                row.last_advanced_at += std::time::Duration::from_millis(delta_ms);
            }
            super::measured("clock.save", || save(ctx, row, w));
            super::native_storage::report_clock_reads();
        }
    }
    Ok(paused)
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
    if !(10..=60_000).contains(&tick_ms) {
        return Err("clock interval must be 10..60000 milliseconds".into());
    }
    let mut clock = ctx
        .db
        .sim_client_clock()
        .run()
        .find(&run)
        .ok_or("clock missing")?;
    clock.scheduled_at = std::time::Duration::from_millis(tick_ms).into();
    clock.paused = paused;
    super::deadline_clock::reset(ctx, &mut clock, tick_ms);
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
    super::physical_clock::cancel(ctx, &run);
    if let Some(mut clock) = ctx.db.sim_client_clock().run().find(&run) {
        clock.paused = true;
        let period = super::deadline_clock::period(ctx, &clock);
        super::deadline_clock::reset(ctx, &mut clock, period);
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
