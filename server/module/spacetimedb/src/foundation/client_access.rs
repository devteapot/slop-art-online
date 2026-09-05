//! Run-scoped browser grants. All checks use authenticated ctx.sender(), never a claimed actor.
use super::{save, sim_audit__view, sim_run, sim_run__view, SimRun};
use simulation::{Controller, Decision, World};
use spacetimedb::{Identity, ReducerContext, ScheduleAt, SpacetimeType, Table, ViewContext};

#[spacetimedb::table(accessor = sim_client_access)]
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

fn world(ctx: &ReducerContext, run: &str) -> Result<(SimRun, World), String> {
    let row = ctx
        .db
        .sim_run()
        .id()
        .find(run.to_string())
        .ok_or("run not found")?;
    let w: World = serde_json::from_str(&row.state).map_err(|_| "invalid run state")?;
    if w.version != simulation::VERSION {
        return Err("old rules are read-only".into());
    }
    Ok((row, w))
}
fn grant(ctx: &ReducerContext) -> Result<SimClientAccess, String> {
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
    let (row, w) = world(ctx, &run)?;
    if row.owner != ctx.sender() {
        return Err("only the run operator grants access".into());
    }
    if !w
        .players
        .iter()
        .any(|p| p.id == actor && p.controller == Controller::Human)
    {
        return Err("grant requires a human character".into());
    }
    // A human character has at most one client owner. Observer-only peers can inspect it.
    if !observer
        && ctx
            .db
            .sim_client_access()
            .iter()
            .any(|g| g.run == run && !g.observer && g.actor == actor && g.identity != identity)
    {
        return Err("human character already controlled by another client".into());
    }
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
    let (row, _) = world(ctx, &access.run)?;
    if row.owner != ctx.sender() {
        return Err("only operator revokes grants".into());
    }
    ctx.db.sim_client_access().identity().delete(identity);
    Ok(())
}
#[spacetimedb::view(accessor = sim_my_snapshot, public)]
pub fn sim_my_snapshot(ctx: &ViewContext) -> Option<SimClientSnapshot> {
    let access = ctx.db.sim_client_access().identity().find(ctx.sender())?;
    let row = ctx.db.sim_run().id().find(&access.run)?;
    let w: World = serde_json::from_str(&row.state).ok()?;
    let events = if access.observer {
        let mut events: Vec<simulation::Event> = ctx
            .db
            .sim_audit()
            .run().filter(&access.run)
            .filter_map(|e| serde_json::from_str(&e.json).ok())
            .collect();
        events.sort_by_key(|e| e.id);
        events
    } else {
        vec![]
    };
    let mut v = simulation::client_view::snapshot(&w, access.observer, access.actor, &events);
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
    let (row, mut w) = world(ctx, &access.run)?;
    if decision.len() > 50_000 {
        return Err("intent too large".into());
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
        scheduled_at: std::time::Duration::from_millis(2500).into(),
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
            w.step();
            save(ctx, row, w);
        }
        _ => return Err("unknown clock command".into()),
    }
    ctx.db.sim_client_clock().id().update(clock);
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_client_pulse(ctx: &ReducerContext, clock: SimClientClock) -> Result<(), String> {
    if ctx.sender() != ctx.identity() {
        return Err("scheduled clock only".into());
    }
    let current = ctx
        .db
        .sim_client_clock()
        .run()
        .find(&clock.run)
        .ok_or("clock missing")?;
    if !current.paused {
        let (row, mut w) = world(ctx, &clock.run)?;
        if !w.stopped {
            w.step();
            save(ctx, row, w);
        }
    }
    Ok(())
}

#[spacetimedb::reducer]
pub fn sim_operator_pause(ctx: &ReducerContext, run: String) -> Result<(), String> {
    let (row, _) = world(ctx, &run)?;
    if row.owner != ctx.sender() {
        return Err("operator only".into());
    }
    if let Some(mut clock) = ctx.db.sim_client_clock().run().find(&run) {
        clock.paused = true;
        ctx.db.sim_client_clock().id().update(clock);
    }
    Ok(())
}
