//! Dedicated M1 runs in the existing authoritative module. Legacy gameplay tables
//! remain available, but cannot mutate foundation characters or their history.
mod client_access;
use simulation::{Controller, Decision, Scenario, World};
use spacetimedb::{Identity, ReducerContext, Table};

#[spacetimedb::table(accessor = sim_run)]
pub struct SimRun {
    #[primary_key]
    pub id: String,
    pub owner: Identity,
    pub state: String,
    pub last_advanced_at: spacetimedb::Timestamp,
}
#[spacetimedb::table(accessor = sim_audit)]
pub struct SimAudit {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub event_id: u64,
    pub kind: String,
    pub actor: u32,
    pub json: String,
}
fn load(ctx: &ReducerContext, run: &str) -> Result<(SimRun, World), String> {
    let row = ctx
        .db
        .sim_run()
        .id()
        .find(&run.to_string())
        .ok_or("run not found")?;
    if row.owner != ctx.sender() {
        return Err("only this run's operator may mutate or submit model results".into());
    }
    let state: World =
        serde_json::from_str(&row.state).map_err(|e| format!("corrupt run state: {e}"))?;
    if state.version != simulation::VERSION {
        return Err(
            "saved rules version differs; inspect old archives read-only or start a new run".into(),
        );
    }
    Ok((row, state))
}
pub(super) fn save(ctx: &ReducerContext, mut row: SimRun, mut world: World) {
    client_access::publish_participants(ctx, &world);
    for event in world.events.drain(..) {
        ctx.db.sim_audit().insert(SimAudit {
            key: format!("{}:{}", world.run, event.id),
            run: world.run.clone(),
            event_id: event.id,
            kind: event.kind.clone(),
            actor: event.actor.unwrap_or(0),
            json: serde_json::to_string(&event).unwrap(),
        });
    }
    row.state = serde_json::to_string(&world).unwrap();
    ctx.db.sim_run().id().update(row);
}
#[spacetimedb::reducer]
pub fn sim_create(ctx: &ReducerContext, run: String, scenario: String) -> Result<(), String> {
    if !run.starts_with("sim-")
        || run.len() > 100
        || !run.chars().all(|c| c.is_ascii_alphanumeric() || c == '-')
    {
        return Err(
            "run ID must start sim- and contain only ASCII letters, digits, hyphens".into(),
        );
    }
    if ctx.db.sim_run().id().find(&run).is_some() {
        return Err("run already exists; never overwrite".into());
    }
    // The shared core permits 256 inhabitants with bounded personal knowledge.
    // Keep transport allocation bounded while allowing authored multi-settlement
    // seeds (the 36-person seed is already 117 KB after compact serialization).
    if scenario.len() > 2 * 1024 * 1024 {
        return Err("scenario too large".into());
    }
    let scenario: Scenario = serde_json::from_str(&scenario).map_err(|e| e.to_string())?;
    let world = World::new(run.clone(), scenario)?;
    let row = ctx.db.sim_run().insert(SimRun {
        id: run,
        owner: ctx.sender(),
        state: String::new(),
        last_advanced_at: ctx.timestamp,
    });
    save(ctx, row, world);
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_step(ctx: &ReducerContext, run: String) -> Result<(), String> {
    let (row, mut world) = load(ctx, &run)?;
    world.step();
    save(ctx, row, world);
    Ok(())
}

/// Operator-authenticated content installation. Participant endpoints cannot submit script source.
#[spacetimedb::reducer]
pub fn sim_stage_scripts(ctx: &ReducerContext, run: String, update: String) -> Result<(), String> {
    let (row, mut world) = load(ctx, &run)?;
    if update.len() > 262_144 {
        return Err("script update exceeds 256 KiB".into());
    }
    let result = serde_json::from_str::<simulation::scripting::Update>(&update)
        .map_err(|e| e.to_string())
        .and_then(|update| world.stage_scripts_by_operator(update));
    if let Err(error) = result {
        world.event(
            None,
            "script_update_rejected",
            vec![],
            serde_json::json!({"error":error}),
        );
    }
    save(ctx, row, world);
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_intent(
    ctx: &ReducerContext,
    run: String,
    actor: u32,
    decision: String,
) -> Result<(), String> {
    let (row, mut world) = load(ctx, &run)?;
    if world.participant_mode {
        return Err("operator intent route disabled; use scoped participant service".into());
    }
    if decision.len() > 50_000 {
        return Err("intent too large".into());
    }
    let input = world.event(
        Some(actor),
        "human_input",
        vec![],
        serde_json::json!({"raw":decision,"operator":ctx.sender().to_hex().to_string()}),
    );
    let result = serde_json::from_str::<Decision>(&decision)
        .map_err(|e| e.to_string())
        .and_then(|d| world.submit(actor, Controller::Human, d, Some(input)));
    if let Err(reason) = result {
        world.event(
            Some(actor),
            "intent_rejected",
            vec![input],
            serde_json::json!({"reason":reason}),
        );
    }
    save(ctx, row, world);
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_model_result(
    ctx: &ReducerContext,
    run: String,
    request: u64,
    raw: String,
    metadata: String,
) -> Result<(), String> {
    let (row, mut world) = load(ctx, &run)?;
    if world.participant_mode {
        return Err("operator model-result route disabled; use scoped participant service".into());
    }
    if raw.len() > 50_000 || metadata.len() > 100_000 {
        return Err("model response too large".into());
    }
    let metadata = serde_json::from_str(&metadata).map_err(|e| e.to_string())?;
    // Rejections are committed audit evidence, not transaction-rollbacks.
    let _ = world.model_result(request, &raw, metadata);
    save(ctx, row, world);
    Ok(())
}

/// Creates a separately owned run; provisioning is distinct from participant reasoning.
#[spacetimedb::reducer]
pub fn sim_create_participant(
    ctx: &ReducerContext,
    run: String,
    scenario: String,
) -> Result<(), String> {
    sim_create(ctx, run.clone(), scenario)?;
    let (row, mut w) = load(ctx, &run)?;
    // sim_create persisted its initial events; seed only safe initial perceptions into the trace.
    w.enable_participants();
    let events: Vec<simulation::Event> = ctx
        .db
        .sim_audit()
        .iter()
        .filter(|e| e.run == run)
        .filter_map(|e| serde_json::from_str(&e.json).ok())
        .collect();
    let mut events = events;
    events.sort_by_key(|e| e.id);
    for e in events {
        w.record_initial_participant_event(&e);
    }
    save(ctx, row, w);
    Ok(())
}
