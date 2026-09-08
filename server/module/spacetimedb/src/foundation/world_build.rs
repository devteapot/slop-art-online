//! Resumable initialization under a private run reservation. No SimRunStore,
//! grants, or timers exist until the ready build is atomically activated.
use super::{native_storage, participant_delivery, seed_upload, sim_audit, storage};
use simulation::{initialization::Progress, World};
use spacetimedb::{Identity, ReducerContext, Table, ViewContext};
use std::collections::BTreeMap;

const ACTORS_PER_BATCH: usize = 16;
const EVENTS_PER_BATCH: usize = 128;

#[spacetimedb::table(accessor = sim_world_build)]
pub struct SimWorldBuild {
    #[primary_key]
    pub run: String,
    #[unique]
    pub owner: Identity,
    pub phase: String,
    pub cursor: u64,
    pub step: u64,
    pub kernel: String,
}

/// Safe initial-event references only; bodies remain in the canonical audit.
#[spacetimedb::table(accessor = sim_world_build_event,
    index(accessor = ordered, btree(columns = [run, event_id])))]
pub struct SimWorldBuildEvent {
    #[primary_key]
    pub key: String,
    pub run: String,
    pub event_id: u64,
}

#[spacetimedb::view(accessor = sim_my_world_build, public)]
pub fn sim_my_world_build(ctx: &ViewContext) -> Option<SimWorldBuild> {
    ctx.db.sim_world_build().owner().find(ctx.sender())
}

fn append(ctx: &ReducerContext, world: &mut World, participant: bool) {
    for event in &world.events {
        if participant && matches!(event.kind.as_str(), "perception"|"starting_behavior_installed"|"policy_installed") {
            ctx.db.sim_world_build_event().insert(SimWorldBuildEvent {
                key: format!("{}:{}", world.run, event.id), run: world.run.clone(), event_id: event.id,
            });
        }
    }
    super::append_audit(ctx, &world.run, world.events.drain(..));
}

#[spacetimedb::reducer]
pub fn sim_prepare_world_build(ctx: &ReducerContext, run: String) -> Result<(), String> {
    let upload = seed_upload::owned(ctx, &run)?;
    if storage::exists(ctx, &run) { return Err("run already exists".into()); }
    if let Some(build) = ctx.db.sim_world_build().run().find(&run) {
        if build.phase == "cancelling" { return Err("build is being cancelled".into()); }
        return Ok(());
    }
    let scenario = serde_json::from_str(&seed_upload::verified_seed(ctx, &upload)?).map_err(|e|e.to_string())?;
    let (mut world, progress) = World::begin_initialization(run.clone(), scenario)?;
    native_storage::save(ctx, &world, &BTreeMap::new(), &BTreeMap::new(), &BTreeMap::new(), None);
    append(ctx, &mut world, upload.mode != "world");
    ctx.db.sim_world_build().insert(SimWorldBuild { run, owner:ctx.sender(), phase:"kernel".into(),
        cursor:0, step:0, kernel:serde_json::to_string(&progress).unwrap() });
    Ok(())
}

#[spacetimedb::reducer]
pub fn sim_advance_world_build(ctx: &ReducerContext, run: String, expected_step: u64) -> Result<(), String> {
    let upload = seed_upload::owned(ctx, &run)?;
    let mut build = ctx.db.sim_world_build().run().find(&run).ok_or("world build unavailable")?;
    if build.owner != ctx.sender() || storage::exists(ctx, &run) { return Err("world build unavailable".into()); }
    if build.phase == "cancelling" { return Err("build is being cancelled".into()); }
    if expected_step < build.step { return Ok(()); } // Lost acknowledgement: do not apply twice.
    if expected_step != build.step { return Err("world build step is ahead of stored progress".into()); }
    if build.phase == "ready" { return Ok(()); }
    let (mut world, ids) = native_storage::load_clock(ctx, &run)?;
    let previous_players = world.players.iter().map(|p|(p.id,p.clone())).collect();
    let previous = world.participants.clone();
    let definitions = (world.initial.clone(), world.scripts.clone());
    match build.phase.as_str() {
        "kernel" => {
            let mut progress:Progress = serde_json::from_str(&build.kernel).map_err(|e|e.to_string())?;
            if world.initialize_batch(&mut progress, ACTORS_PER_BATCH)? {
                build.phase = if upload.mode == "world" {"ready"} else {"participants"}.into();
            }
            build.kernel = serde_json::to_string(&progress).unwrap();
        }
        "participants" => {
            // Audit was drained at each earlier commit. Import only the safe
            // references below, preserving new_participant's original contract.
            world.enable_participants();
            build.phase = "experiences".into();
            build.cursor = 1;
        }
        "experiences" => {
            // Point reads in explicit audit order; index iterator ordering is
            // not an application sequence guarantee.
            let end = build.cursor.saturating_add(EVENTS_PER_BATCH as u64).min(world.next_event);
            for id in build.cursor..end {
                let key = format!("{run}:{id}");
                let Some(reference) = ctx.db.sim_world_build_event().key().find(&key) else { continue; };
                let row = ctx.db.sim_audit().key().find(&key).ok_or("initial event missing")?;
                let event:simulation::Event = serde_json::from_str(&row.json).map_err(|e|e.to_string())?;
                if event.run != run || event.id != reference.event_id { return Err("initial event scope mismatch".into()); }
                world.record_initial_participant_event(&event);
                ctx.db.sim_world_build_event().key().delete(&key);
            }
            build.cursor = end;
            if end == world.next_event {
                build.phase = if upload.mode == "client" {"controllers"} else {"publication"}.into();
                build.cursor = 0;
            }
        }
        "controllers" => {
            build.cursor = world.initialize_client_batch(build.cursor as usize, ACTORS_PER_BATCH)? as u64;
            if build.cursor as usize == world.players.len() { build.phase="publication".into(); build.cursor=0; }
        }
        "publication" => {
            let end = (build.cursor as usize + ACTORS_PER_BATCH).min(world.players.len());
            for player in &world.players[build.cursor as usize..end] {
                let state = world.participants.get(&player.id).ok_or("participant missing")?;
                participant_delivery::publish_actor(ctx, &run, world.tick, world.timing.time_ms, world.stopped,
                    player, state, ids.get(&player.id).ok_or("participant leases missing")?, None, 0);
            }
            build.cursor = end as u64;
            if end == world.players.len() { build.phase="ready".into(); }
        }
        _ => return Err("invalid world build phase".into()),
    }
    native_storage::save(ctx, &world, &previous, &ids, &previous_players, Some(&definitions));
    append(ctx, &mut world, upload.mode != "world");
    build.step = build.step.checked_add(1).ok_or("build step overflow")?;
    ctx.db.sim_world_build().run().update(build);
    Ok(())
}

pub(super) fn finish(ctx: &ReducerContext, upload: &seed_upload::SimWorldUpload) -> Result<bool, String> {
    let Some(build) = ctx.db.sim_world_build().run().find(&upload.run) else { return Ok(false); };
    if build.owner != ctx.sender() || build.phase != "ready" { return Err("world build is not ready".into()); }
    if storage::exists(ctx, &upload.run) { return Err("run already exists".into()); }
    if ctx.db.sim_world_build_event().ordered().filter((upload.run.as_str(),)).next().is_some() {
        return Err("initial evidence import incomplete".into());
    }
    // All native and delivery rows are already durable. This single row admits
    // the completed world and establishes its wall-clock origin at activation.
    storage::create(ctx, upload.run.clone());
    ctx.db.sim_world_build().run().delete(&upload.run);
    seed_upload::remove(ctx, upload);
    Ok(true)
}

pub(super) fn cancel(ctx: &ReducerContext, run: &str) -> Result<bool, String> {
    let Some(mut build) = ctx.db.sim_world_build().run().find(run.to_owned()) else { return Ok(true); };
    if build.owner != ctx.sender() || storage::exists(ctx, run) { return Err("world build unavailable".into()); }
    build.phase="cancelling".into();
    ctx.db.sim_world_build().run().update(build);
    let refs:Vec<_> = ctx.db.sim_world_build_event().ordered().filter((run,)).take(EVENTS_PER_BATCH).collect();
    for row in &refs { ctx.db.sim_world_build_event().key().delete(&row.key); }
    if !refs.is_empty() { return Ok(false); }
    let events:Vec<_> = ctx.db.sim_audit().run().filter(run).take(EVENTS_PER_BATCH).collect();
    for row in &events { ctx.db.sim_audit().key().delete(&row.key); }
    if !events.is_empty() { return Ok(false); }
    if !native_storage::discard_unpublished_batch(ctx, run, EVENTS_PER_BATCH) { return Ok(false); }
    ctx.db.sim_world_build().run().delete(run.to_owned());
    Ok(true)
}
