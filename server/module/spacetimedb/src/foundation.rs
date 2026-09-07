//! Dedicated M1 runs in the existing authoritative module. Legacy gameplay tables
//! remain available, but cannot mutate foundation characters or their history.
mod client_access;
mod storage;
mod storage_codec;
mod participant_delivery;
mod native_storage;
use storage::LoadedRun as SimRun;
use simulation::{Controller, Decision, Scenario, World};
use spacetimedb::{ReducerContext, Table};

/// Host timing is diagnostic only and never influences authoritative decisions.
/// The default build has no timer calls or additional retained log records.
fn measured<T>(_name: &str, work: impl FnOnce() -> T) -> T {
    #[cfg(feature = "clock-profile")]
    let _timer = spacetimedb::log_stopwatch::LogStopwatch::new(_name);
    work()
}

fn advance_clock(world: &mut World, delta_ms: u64) {
    #[cfg(feature = "clock-profile")]
    {
        #[derive(Default)]
        struct Phases(Option<spacetimedb::log_stopwatch::LogStopwatch>);
        impl simulation::timing::AdvanceObserver for Phases {
            fn begin(&mut self, phase: &'static str) {
                drop(self.0.take());
                self.0 = Some(spacetimedb::log_stopwatch::LogStopwatch::new(phase));
            }
        }
        world.advance_ms_observed(delta_ms, &mut Phases::default());
    }
    #[cfg(not(feature = "clock-profile"))]
    world.advance_ms(delta_ms);
}

#[spacetimedb::table(accessor = sim_audit,
    index(accessor = run_and_event, btree(columns = [run, event_id])))]
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
    let (row, state) = storage::load_owned(ctx, run)?;
    if state.version != simulation::VERSION {
        return Err(
            "saved rules version differs; inspect old archives read-only or start a new run".into(),
        );
    }
    Ok((row, state))
}
pub(super) fn save(ctx: &ReducerContext, mut row: SimRun, mut world: World) {
    let encoded = if row.state == native_storage::FORMAT {
        let ids = measured("native.save.rows", || native_storage::save(ctx, &world, &row.previous_participants, &row.native_lease_ids, &row.previous_players));
        measured("native.save.delivery", || participant_delivery::publish(ctx, &world, &ids, &row.previous_participants, row.previous_time_ms));
        None
    } else {
        let encoded = storage::encode(ctx, &mut row, &world).expect("valid normalized World storage");
        let ids = world.participants.keys().map(|&actor| (actor,
            encoded.layout.participant_leases(actor).expect("participant leases").to_vec())).collect();
        participant_delivery::publish(ctx, &world, &ids, &row.previous_participants, row.previous_time_ms);
        Some(encoded)
    };
    measured("native.save.audit", || append_audit(ctx, &world.run, world.events.drain(..)));
    if let Some(encoded) = encoded { storage::commit(ctx, row, encoded); }
    else { storage::commit_native(ctx, row); }
}
fn append_audit(ctx: &ReducerContext, run: &str, events: impl IntoIterator<Item = simulation::Event>) {
    for event in events {
        assert_eq!(event.run, run, "audit run identity");
        ctx.db.sim_audit().insert(SimAudit {
            key: format!("{}:{}", run, event.id),
            run: run.into(),
            event_id: event.id,
            kind: event.kind.clone(),
            actor: event.actor.unwrap_or(0),
            json: serde_json::to_string(&event).unwrap(),
        });
    }
}

/// Explicit representation migration. No gameplay event, controller change,
/// history truncation or simulation advance is implied by moving storage.
#[spacetimedb::reducer]
pub fn sim_migrate_native_state(ctx: &ReducerContext, run: String) -> Result<(), String> {
    use client_access::sim_participant_cache;
    use storage::sim_world_blob;
    let (mut row, world) = load(ctx, &run)?;
    if row.state == native_storage::FORMAT && native_storage::histories_separated(ctx, &run) { return Ok(()); }
    // Routine native hydration deliberately defers captured response bodies.
    // Migration compares complete snapshots, so explicitly materialize them.
    let world = if row.state == native_storage::FORMAT {
        native_storage::load_export(ctx, &run)?
    } else { world };
    let expected = serde_json::to_value(&world).map_err(|e|e.to_string())?;
    // Numeric lease identities belong to different representations. Clearing
    // the derived delivery rows avoids confusing an old blob ID with a new
    // native lease ID; captured evidence remains in the loaded canonical World.
    for actor in world.participants.keys() {
        participant_delivery::clear_actor(ctx, &run, *actor);
    }
    row.state = native_storage::FORMAT.into();
    row.previous_participants.clear();
    row.previous_players.clear();
    row.native_lease_ids.clear();
    save(ctx, row, world);
    let restored = native_storage::load_export(ctx, &run)?;
    if serde_json::to_value(&restored).map_err(|e|e.to_string())? != expected {
        return Err("native migration changed authoritative state; transaction rolled back".into());
    }
    // The complete canonical state was verified above, in this transaction.
    // Audit rows are separate and are deliberately never collected here.
    for blob in ctx.db.sim_world_blob().run().filter(run.as_str()) {
        ctx.db.sim_world_blob().id().delete(blob.id);
    }
    for actor in restored.participants.keys() {
        ctx.db.sim_participant_cache().key().delete(format!("{run}:{actor}"));
    }
    Ok(())
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
    if storage::exists(ctx, &run) {
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
    let row = storage::create(ctx, run);
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
        .run()
        .filter(&run)
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
