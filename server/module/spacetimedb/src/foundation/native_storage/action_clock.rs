//! Local physical clock transactions. No population reconciliation or slow-system
//! row writes occur here. Unsupported dependencies fall back before any mutation.
use super::*;

pub(crate) struct Outcome {
    pub alive: u64,
    pub actors_loaded: u64,
    pub stopped: bool,
}

pub(super) fn cells(initial: &simulation::Scenario, position: i32) -> BTreeSet<i32> {
    if let Some(map) = &initial.map {
        let (x, y) = (position % map.width, position / map.width);
        (-3i32..=3).flat_map(|dy| (-3i32..=3).map(move |dx| (dx, dy)))
            .filter(|(dx, dy)| dx.abs() + dy.abs() <= 3)
            .filter_map(|(dx, dy)| {
                let (x, y) = (x + dx, y + dy);
                (x >= 0 && y >= 0 && x < map.width && y < map.height).then_some(y * map.width + x)
            }).collect()
    } else {
        (position.saturating_sub(3)..=position.saturating_add(3)).collect()
    }
}

pub(crate) fn advance_actions(ctx: &ReducerContext, run: &str, head: SimNativeHead,
    delta_ms: u64, alive: u64) -> Result<Option<Outcome>, String> {
    #[cfg(feature = "clock-profile")]
    let read_profile = spacetimedb::log_stopwatch::LogStopwatch::new("actions.read");
    let until = head.time_ms.checked_add(delta_ms).ok_or("physical clock overflow")?;
    let due: BTreeSet<_> = ctx.db.sim_native_clock_actor().active_actors().filter((run, true))
        .chain(ctx.db.sim_native_clock_actor().due().filter((run, ..=until)))
        .map(|row| row.actor).collect();
    let definitions = clock_definitions(ctx, run)?;
    // Radius three includes one movement step, its observers, local catalogs,
    // speech recipients and death witnesses under the verified bundled laws.
    let mut positions = BTreeSet::new();
    let mut bodies = BTreeMap::new();
    for actor in &due {
        let body = ctx.db.sim_native_actor().key().find(key(run, actor)).ok_or("clock actor missing")?;
        positions.extend(cells(&definitions.initial, body.position));
        bodies.insert(body.actor, body);
    }
    for position in &positions {
        for body in ctx.db.sim_native_actor().location().filter((run, *position)) { bodies.insert(body.actor, body); }
    }
    let mut minds = BTreeMap::new();
    // Explicit remote targets are read even when the bundled action will reject
    // their range. Preserve that original failure rather than inventing absence.
    let mut targets = BTreeSet::new();
    for actor in &due {
        let mind = ctx.db.sim_native_mind().key().find(key(run, actor)).ok_or("clock mind missing")?;
        let execution: Option<simulation::Execution> = parse(&mind.execution)?;
        if let Some(execution) = execution {
            if let bonsai_bt::Behavior::Sequence(actions) = execution.tree {
                for action in actions {
                    if let bonsai_bt::Behavior::Action(action) = action { targets.extend(action.target); }
                }
            }
        }
        minds.insert(*actor, mind);
    }
    for actor in targets {
        if let Some(body) = ctx.db.sim_native_actor().key().find(key(run, actor)) {
            // Load its entire cell because local lifecycle catalog refresh is a
            // shared action-tail operation for every body in the transaction.
            if positions.insert(body.position) {
                for peer in ctx.db.sim_native_actor().location().filter((run, body.position)) { bodies.insert(peer.actor, peer); }
            }
            bodies.insert(actor, body);
        }
    }
    let mut sites = vec![];
    let mut stations = vec![];
    let mut archives = vec![];
    for position in &positions {
        sites.extend(ctx.db.sim_native_site().location().filter((run, *position)));
        stations.extend(ctx.db.sim_native_station().location().filter((run, *position)));
        archives.extend(ctx.db.sim_native_archive().location().filter((run, *position)));
    }
    let aux_ids: BTreeSet<_> = bodies.keys().copied().chain(stations.iter().map(|s| s.owner)).collect();
    let mut participants = vec![];
    let mut controllers = vec![];
    let mut leases = vec![];
    for actor in bodies.keys() {
        if !minds.contains_key(actor) {
            minds.insert(*actor, ctx.db.sim_native_mind().key().find(key(run, actor)).ok_or("local mind missing")?);
        }
        participants.extend(ctx.db.sim_native_participant().key().find(key(run, actor)));
        controllers.extend(ctx.db.sim_native_controller().key().find(key(run, actor)));
        leases.extend(ctx.db.sim_native_lease().participant().filter((run, *actor)));
    }
    let rows = Rows {
        paged_heads:vec![],trace_pages:vec![],evidence_bodies:vec![],
        trace_indexes: vec![],
        catalogs: vec![],
        head, definitions, actors:bodies.values().cloned().collect(), minds:minds.into_values().collect(),
        mind_histories:vec![], participants, controllers, bootstraps:vec![], experiences:vec![],
        leases, lease_evidence:vec![], captures:vec![], receipts:vec![],
        aux:aux_ids.into_iter().filter_map(|actor|ctx.db.sim_native_actor_aux().key().find(key(run,actor))).collect(),
        sites, stations, archives,
    };
    let site_rows: BTreeMap<_,_> = rows.sites.iter().map(|s|(s.position,s.clone())).collect();
    #[cfg(feature = "clock-profile")]
    drop(read_profile);
    let (mut world, previous_ids) = super::super::measured("actions.assemble", || assemble_with(rows,None,false,Some(cold_reader(ctx))))?;
    if !world.local_clock_laws() || due.iter().any(|actor| !world.local_clock_actor(*actor)) {
        return Ok(None);
    }
    let previous_alive = world.players.iter().filter(|p|p.health>0).count() as u64;
    let outside_alive = alive.checked_sub(previous_alive).ok_or("physical population counter mismatch")?;
    let previous_players: BTreeMap<_,_> = world.players.iter().map(|p|(p.id,p.clone())).collect();
    let previous_participants = world.participants.clone();
    let previous_time = world.timing.time_ms;
    let selection = simulation::clock::Selection::new(&world,due.iter().copied());
    super::super::measured("actions.execute", || super::super::observe_clock(|observer|
        world.advance_actions_ms(delta_ms,observer,&selection,outside_alive>0)));
    #[cfg(feature = "clock-profile")]
    log::info!("clock_action_domain {}", serde_json::json!({"time_ms":world.timing.time_ms,
        "loaded":world.players.len(),"alive_before":previous_alive,"due":due.len(),
        "events":world.events.len()}));
    if world.players.len()!=bodies.len() || world.players.iter().any(|p|!bodies.contains_key(&p.id)) {
        return Err("local action changed undeclared population".into());
    }
    let alive = outside_alive + world.players.iter().filter(|p|p.health>0).count() as u64;
    #[cfg(feature = "clock-profile")]
    let save_profile = spacetimedb::log_stopwatch::LogStopwatch::new("actions.save");
    let mut save_phase = super::super::evidence_profile::SaveScope::new(true, "actions.save.actors");
    for (i,player) in world.players.iter().enumerate() {
        let sampled = i % 17 == 0;
        let old = &previous_players[&player.id];
        if !player.same_snapshot(old) {
            let _profile = super::super::evidence_profile::SaveScope::new(sampled, "actions.save.actor.body");
            upsert!(ctx,sim_native_actor,key,SimNativeActor::from_player(run,bodies[&player.id].ordinal as usize,player));
            save_mind(ctx,run,player,Some(old));
        }
        let aux_profile = super::super::evidence_profile::SaveScope::new(sampled, "actions.save.actor.aux");
        let aux = SimNativeActorAux::from_world(&world,player.id);
        upsert!(ctx,sim_render_actor_support,key,SimRenderActorSupport::from_aux(aux.clone()));
        upsert!(ctx,sim_native_actor_aux,key,aux);
        drop(aux_profile);
        if due.contains(&player.id) || !player.same_snapshot(old)
            || world.participants.get(&player.id).is_some_and(|p|previous_participants.get(&player.id).is_none_or(|old|!p.same_snapshot(old))) {
            let _profile = super::super::evidence_profile::SaveScope::new(sampled, "actions.save.actor.hint");
            save_clock_hint(ctx,run,world.actor_clock_hint(i));
        }
    }
    save_phase.phase(true, "actions.save.sites");
    for site in &world.sites {
        let mut row = site_rows.get(&site.position).ok_or("local action created undeclared site")?.clone();
        row.food=site.food;row.hazard=site.hazard;row.shelter=site.shelter;
        upsert!(ctx,sim_native_site,key,row);
    }
    save_phase.phase(true, "actions.save.participants");
    let ids = save_participants(ctx,&world,&previous_participants,&previous_ids);
    save_phase.phase(true, "actions.save.head");
    let head = SimNativeHead::from_world(&world);
    upsert!(ctx,sim_render_clock,run,SimRenderClock {run:run.into(),head:json(&head)});
    upsert!(ctx,sim_native_head,run,head);
    drop(save_phase);
    #[cfg(feature = "clock-profile")]
    drop(save_profile);
    super::super::measured("actions.delivery", ||
        super::super::participant_delivery::publish(ctx,&world,&ids,&previous_participants,previous_time));
    let outcome = Outcome {alive,actors_loaded:world.players.len() as u64,stopped:world.stopped};
    super::super::measured("actions.audit", || super::super::append_audit(ctx,run,world.events));
    Ok(Some(outcome))
}
