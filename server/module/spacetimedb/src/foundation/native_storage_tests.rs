use super::*;
use serde_json::json;
use simulation::{
    participant::{Command, Request, API_VERSION},
    participant_transaction::ParticipantTransaction,
    policy::Node,
    Action, Scenario, Skill,
};

#[test]
fn local_physical_domain_preserves_combat_movement_and_recipient_evidence() {
    for skill in [Skill::Attack,Skill::Move,Skill::Give,Skill::Build,Skill::Gather,Skill::Observe,Skill::Speak] {
        let mut seed:Scenario=serde_json::from_str(include_str!("../../../../../scenarios/living-clearing.json")).unwrap();
        seed.map=None;seed.arenas.clear();seed.weather=None;seed.food_sources.clear();
        let mut far=seed.players[0].clone();far.id=99;far.position=9;far.name="Far away".into();
        seed.players.push(far);
        for player in seed.players.iter_mut().filter(|p|p.id!=99) {player.position=0;player.food=10;player.energy=100;}
        let mut before=World::new("local-action-domain".into(),seed).unwrap();
        before.enable_client_controllers().unwrap();before.advance_ms(50);
        let actor=before.players[0].id;let target=before.players[1].id;
        if skill==Skill::Attack {before.players[1].health=20;}
        let mut action=Action::new(skill.clone());
        if matches!(skill,Skill::Attack|Skill::Give) {action.target=Some(target);}
        if skill==Skill::Move {action.destination=Some(1);}
        if skill==Skill::Speak {action.text=Some("Local spoken evidence".into());}
        let receipt=before.participant_apply(actor,Request {api_version:API_VERSION.into(),request_id:"local-action".into(),
            control_epoch:before.participants[&actor].control_epoch,
            command:if skill==Skill::Speak {Command::Speak{text:action.text.clone().unwrap(),expires_tick:10}}
                else {Command::StartAction{expected_revision:before.players[0].generation,action}}}).unwrap();
        assert!(receipt.ok,"{:?}",receipt.error);
        before.events.clear();
        let positions=action_clock::cells(&before.initial,before.players[0].position);
        let mut rows=fixture(&before);
        rows.actors.retain(|p|positions.contains(&p.position));
        let included:BTreeSet<_>=rows.actors.iter().map(|p|p.actor).collect();
        assert!(!included.contains(&99));
        rows.minds.retain(|p|included.contains(&p.actor));
        rows.mind_histories.retain(|p|included.contains(&p.actor));
        rows.participants.retain(|p|included.contains(&p.actor));
        rows.controllers.retain(|p|included.contains(&p.actor));
        rows.bootstraps.retain(|p|included.contains(&p.actor));
        rows.experiences.retain(|p|included.contains(&p.actor));
        rows.receipts.retain(|p|included.contains(&p.actor));
        rows.aux.retain(|p|included.contains(&p.actor));
        rows.sites.retain(|p|positions.contains(&p.position));
        rows.archives.retain(|p|positions.contains(&p.position));
        rows.stations.retain(|p|positions.contains(&p.position));
        let (mut local,_)=assemble(rows,None,false).unwrap();
        assert!(local.local_clock_actor(actor));
        let selection=simulation::clock::Selection::new(&local,[actor]);
        let mut reference=before.clone();reference.advance_ms(50);
        local.advance_actions_ms(50,&mut (),&selection,true);
        assert_eq!(json!(local.events),json!(reference.events),"ordered evidence for {skill:?}");
        for player in &reference.players {
            if included.contains(&player.id) {
                assert_eq!(json!(local.players.iter().find(|p|p.id==player.id).unwrap()),json!(player),"physical actor {skill:?}");
                assert_eq!(json!(local.participants[&player.id]),json!(reference.participants[&player.id]),"recipient {skill:?}");
            } else {
                assert_eq!(json!(before.players.iter().find(|p|p.id==player.id).unwrap()),json!(player),"omitted actor must not change");
                assert_eq!(json!(before.participants[&player.id]),json!(reference.participants[&player.id]));
            }
        }
        for site in &local.sites {assert_eq!(json!(site),json!(reference.sites.iter().find(|s|s.position==site.position).unwrap()));}
    }
}

fn fixture(w: &World) -> Rows {
    let mut next = 1;
    let mut captures = vec![];
    Rows {
        controllers: w.participants.iter().filter_map(|(&a,p)|p.client_controller.as_ref().map(|c|SimNativeController::from_state(&w.run,a,c))).collect(),
        bootstraps: w.participants.iter().filter_map(|(&a,p)|p.client_controller.as_ref().map(|c|SimControllerBootstrap { key:key(&w.run,a), run:w.run.clone(),actor:a,body:json(&c.bootstrap) })).collect(),
        head: SimNativeHead::from_world(w),
        definitions: definitions(w),
        actors: w
            .players
            .iter()
            .enumerate()
            .map(|(i, p)| SimNativeActor::from_player(&w.run, i, p))
            .collect(),
        minds: w
            .players
            .iter()
            .map(|p| SimNativeMind::from_player(&w.run, p))
            .collect(),
        mind_histories: w.players.iter().map(|p| SimNativeMindHistory::from_player(&w.run, p)).collect(),
        participants: w
            .participants
            .iter()
            .map(|(&a, s)| SimNativeParticipant::from_state(&w.run, a, s))
            .collect(),
        experiences: w.participants.iter().flat_map(|(&actor, state)| state.experiences.iter()
            .map(move |e| SimNativeExperience::from_experience(&w.run, actor, e))).collect(),
        leases: w
            .participants
            .iter()
            .flat_map(|(&actor, s)| {
                s.evidence_leases
                    .iter()
                    .enumerate()
                    .map(move |(ordinal, l)| (actor, ordinal, l))
            })
            .map(|(actor, ordinal, l)| {
                let id = next;
                next += 1;
                if l.observation.is_capture() {
                    captures.push(SimNativeCapture {
                        lease_id: id,
                        run: w.run.clone(),
                        actor,
                        observation: l.observation.get().into(),
                    });
                }
                SimNativeLease {
                    id,
                    run: w.run.clone(),
                    actor,
                    ordinal: ordinal as u32,
                    request_id: l.request_id.clone(),
                    observed_cursor: l.observed_cursor,
                    expires_ms: l.expires_ms,
                    has_observation: l.observation.is_capture(),
                    experiences: json(&l.experiences),
                }
            })
            .collect(),
        captures,
        lease_evidence: vec![],
        receipts: w
            .participants
            .iter()
            .flat_map(|(&actor, s)| {
                s.receipts.iter().map(move |r| {
                    super::super::participant_delivery::SimParticipantReceipt {
                        key: key(&w.run, format!("{actor}:{}", r.request_id)),
                        run: w.run.clone(),
                        actor,
                        request_id: r.request_id.clone(),
                        fingerprint: r.fingerprint.clone(),
                        ok: r.ok,
                        error: r.error.clone(),
                        event: r.event,
                    }
                })
            })
            .collect(),
        aux: aux_ids(w)
            .into_iter()
            .map(|a| SimNativeActorAux::from_world(w, a))
            .collect(),
        sites: w
            .sites
            .iter()
            .enumerate()
            .map(|(n, s)| SimNativeSite {
                key: key(&w.run, s.position),
                run: w.run.clone(),
                ordinal: n as u32,
                position: s.position,
                food: s.food,
                hazard: s.hazard,
                shelter: s.shelter,
            })
            .collect(),
        stations: w
            .infrastructure
            .stations
            .iter()
            .enumerate()
            .map(|(n, s)| SimNativeStation::from_station(&w.run, n, s))
            .collect(),
        archives: w
            .archives
            .iter()
            .enumerate()
            .map(|(n, a)| SimNativeArchive {
                key: key(&w.run, a.id),
                run: w.run.clone(),
                archive: a.id,
                ordinal: n as u32,
                position: a.position,
                label: a.label.clone(),
                capacity: a.capacity as u64,
                destroyed: a.destroyed,
                revision: a.revision,
                records: json(&a.records),
            })
            .collect(),
    }
}
fn scoped(w: &World, actor: u32) -> World {
    scoped_materialized(w, actor, false)
}
fn scoped_materialized(w: &World, actor: u32, materialize: bool) -> World {
    let mut rows = fixture(w);
    let position = rows
        .actors
        .iter()
        .find(|a| a.actor == actor)
        .unwrap()
        .position;
    rows.actors.retain(|a| a.position == position);
    rows.stations.retain(|s| s.position == position);
    let aux_ids: BTreeSet<_> = rows
        .actors
        .iter()
        .map(|a| a.actor)
        .chain(rows.stations.iter().map(|s| s.owner))
        .chain([actor])
        .collect();
    rows.aux.retain(|a| aux_ids.contains(&a.actor));
    if materialize {
        rows.aux = rows.aux.into_iter().map(|row| SimRenderActorSupport::from_aux(row).into_aux()).collect();
    }
    rows.minds.retain(|m| m.actor == actor);
    rows.mind_histories.retain(|m| m.actor == actor);
    rows.participants.retain(|p| p.actor == actor);
    rows.experiences.retain(|p| p.actor == actor);
    rows.leases.retain(|l| l.actor == actor);
    rows.receipts.retain(|r| r.actor == actor);
    rows.sites.clear();
    rows.archives.clear();
    rows.captures.retain(|c| materialize && c.actor == actor);
    assemble(rows, Some(actor), materialize).unwrap().0
}
fn worlds() -> Vec<World> {
    [
        include_str!("../../../../../scenarios/survival.json"),
        include_str!("../../../../../scenarios/infrastructure-baseline.json"),
        include_str!("../../../../../scenarios/population-reproduction.json"),
        include_str!("../../../../../scenarios/luna-arena-matrix.json"),
        include_str!("../../../../../scenarios/faction-world-reality.json"),
    ]
    .into_iter()
    .map(|source| {
        let s: Scenario = serde_json::from_str(source).unwrap();
        let mut w = World::new("sim-native-parity".into(), s).unwrap();
        w.enable_participants();
        w
    })
    .collect()
}

fn cold_fixture(w: &World) -> (World, [Arc<std::sync::atomic::AtomicUsize>; 3], BTreeMap<u64, SimNativeCapture>) {
    use std::sync::atomic::{AtomicUsize, Ordering};
    let mut rows = fixture(w);
    let counts = std::array::from_fn(|_| Arc::new(AtomicUsize::new(0)));
    let mind_count = counts[0].clone();
    let experience_count = counts[1].clone();
    let lease_count = counts[2].clone();
    let minds: BTreeMap<_, _> = std::mem::take(&mut rows.mind_histories).into_iter().map(|m| (m.actor, m)).collect();
    let experiences: Arc<BTreeMap<_, _>> = Arc::new(std::mem::take(&mut rows.experiences).into_iter()
        .map(|e| ((e.actor, e.cursor), e)).collect());
    let legacy = experiences.clone();
    let leases: BTreeMap<_, _> = rows.leases.iter_mut().map(|l| {
        let data = SimNativeLeaseEvidence { lease_id: l.id, run: l.run.clone(), actor: l.actor,
            experiences: std::mem::replace(&mut l.experiences, LEASE_EVIDENCE.into()) };
        (l.id, data)
    }).collect();
    let captures = std::mem::take(&mut rows.captures).into_iter().map(|c| (c.lease_id, c)).collect();
    let bootstraps: BTreeMap<_,_> = std::mem::take(&mut rows.bootstraps).into_iter().map(|b|(b.actor,b)).collect();
    let receipt_values: BTreeMap<u32, Vec<Receipt>> = rows.participants.iter().map(|p| (p.actor,
        rows.receipts.iter().filter(|r|r.actor==p.actor).map(|r|Receipt {
            request_id:r.request_id.clone(), fingerprint:r.fingerprint.clone(), ok:r.ok, error:r.error.clone(), event:r.event,
        }).collect())).collect();
    rows.receipts.clear();
    let reader = Arc::new(ColdReader {
        receipts: Box::new(move |_,actor| Ok(receipt_values.get(&actor).cloned().unwrap_or_default())),
        bootstrap: Box::new(move |run,actor| {
            let b = bootstraps.get(&actor).ok_or("missing bootstrap")?;
            if b.run != run { return Err("foreign bootstrap".into()); }
            parse(&b.body)
        }),
        mind: Box::new(move |run, actor| {
            mind_count.fetch_add(1, Ordering::SeqCst);
            let row = minds.get(&actor).ok_or("missing mind")?;
            if row.run != run || row.actor != actor { return Err("foreign mind".into()); }
            Ok(row.clone())
        }),
        experience: Box::new(move |run, actor, cursor| {
            experience_count.fetch_add(1, Ordering::SeqCst);
            let row = experiences.get(&(actor, cursor)).ok_or("missing experience")?;
            if row.run != run { return Err("foreign experience".into()); }
            Ok(row.clone())
        }),
        legacy_experiences: Box::new(move |run, actor| Ok(legacy.values()
            .filter(|e| e.run == run && e.actor == actor).cloned().collect())),
        lease: Box::new(move |run, actor, id| {
            lease_count.fetch_add(1, Ordering::SeqCst);
            let row = leases.get(&id).ok_or("missing lease")?;
            if row.run != run || row.actor != actor { return Err("foreign lease".into()); }
            parse(&row.experiences)
        }),
    });
    let world = assemble_with(rows, None, false, Some(reader)).unwrap().0;
    (world, counts, captures)
}
fn materialize_test_captures(w: &mut World, captures: &BTreeMap<u64, SimNativeCapture>) {
    for state in w.participants.values_mut() {
        for lease in &mut state.evidence_leases {
            if let Some(id) = lease.observation.reference() {
                lease.observation = serde_json::value::RawValue::from_string(captures[&id].observation.clone()).unwrap().into();
            }
        }
    }
}

#[test]
fn cold_clock_defers_payloads_and_matches_full_clock_across_storage_reload() {
    use std::sync::atomic::Ordering;
    for mut full in worlds() {
        let actor = full.players[0].id;
        let read = request(&full, actor, Command::ReadObservation { after: 0, limit: 128 });
        full.participant_apply(actor, read).unwrap();
        for delta in [50, 75, 250, 2_500, 50] {
            full.events.clear();
            let (mut cold, counts, captures) = cold_fixture(&full);
            assert_eq!(counts.each_ref().map(|n| n.load(Ordering::SeqCst)), [0, 0, 0], "assembly fetches no cold rows");
            assert!(cold.participants.values().all(|s| !s.experiences.is_loaded()), "assembly does not decode trace metadata");
            let due = (0..cold.players.len()).map(|i| cold.actor_clock_hint(i))
                .filter(|h| h.active || h.due_ms <= cold.timing.time_ms + delta).map(|h| h.actor).collect::<Vec<_>>();
            let selection = simulation::clock::Selection::new(&cold, due);
            full.advance_ms(delta);
            cold.advance_ms_selected(delta, &mut (), Some(&selection));
            assert_eq!(counts[2].load(Ordering::SeqCst), 0, "physics does not read leased evidence");
            materialize_test_captures(&mut cold, &captures);
            assert_eq!(json(&cold), json(&full), "full state, evidence and ordering after reload");
        }
    }
}

#[test]
fn idle_clock_has_no_cold_dependencies_and_cow_does_not_load_untouched_fields() {
    use std::sync::atomic::Ordering;
    let mut full = worlds().remove(0);
    for player in &mut full.players { player.execution = None; }
    full.advance_ms(50);
    full.events.clear();
    let (mut cold, counts, _) = cold_fixture(&full);
    let selection = simulation::clock::Selection::new(&cold, []);
    full.advance_ms(50);
    cold.advance_ms_selected(50, &mut (), Some(&selection));
    assert_eq!(counts.each_ref().map(|n| n.load(Ordering::SeqCst)), [0, 0, 0]);
    assert!(cold.participants.values().all(|s| !s.experiences.is_loaded()), "idle physics leaves trace metadata untouched");
    assert!(cold.participants.values().all(|s| !s.receipts.is_loaded()), "idle physics must not fetch command receipts");
    assert_eq!(json(&cold), json(&full));
}

#[test]
fn legacy_component_histories_remain_readable_and_split_references_fail_closed() {
    let w = worlds().remove(0);
    let expected = serde_json::to_value(&w).unwrap();
    let mut legacy = fixture(&w);
    for mind in &mut legacy.minds {
        let h = legacy.mind_histories.iter().find(|h| h.actor == mind.actor).unwrap();
        mind.beliefs = h.beliefs.clone();
        mind.relationships = h.relationships.clone();
        mind.memories = h.memories.clone();
        mind.site_observations = h.site_observations.clone();
        mind.knowledge = h.knowledge.clone();
    }
    legacy.mind_histories.clear();
    for p in &mut legacy.participants {
        p.experiences = json(&w.participants[&p.actor].experiences);
    }
    legacy.experiences.clear();
    assert_eq!(serde_json::to_value(assemble(legacy, None, true).unwrap().0).unwrap(), expected);
    let mut missing = fixture(&w);
    assert!(missing.experiences.pop().is_some());
    assert!(assemble(missing, None, true).is_err(), "must not silently truncate evidence");
    let mut foreign = fixture(&w);
    foreign.experiences[0].run = "sim-other".into();
    assert!(assemble(foreign, None, true).is_err());
    let mut missing_mind = fixture(&w);
    missing_mind.mind_histories.clear();
    assert!(assemble(missing_mind, None, true).is_err());
}
fn request(w: &World, actor: u32, command: Command) -> Request {
    Request {
        api_version: API_VERSION.into(),
        request_id: format!("request-{}", w.next_event),
        control_epoch: w.participants[&actor].control_epoch,
        command,
    }
}
fn differential(w: &mut World, actor: u32, request: Request) {
    differential_operation(w, actor, Some(request), None);
}
fn differential_operation(
    w: &mut World,
    actor: u32,
    request: Option<Request>,
    intent: Option<simulation::Decision>,
) {
    w.events.clear();
    let captures: BTreeMap<_, _> = fixture(w)
        .captures
        .into_iter()
        .map(|c| (c.lease_id, c))
        .collect();
    let context = scoped(w, actor);
    assert_eq!(context.participants.len(), 1);
    assert!(context
        .players
        .iter()
        .filter(|p| p.id != actor)
        .all(|p| p.memories.is_empty() && p.knowledge.is_empty()));
    let transaction = ParticipantTransaction::new(context, actor).unwrap();
    let mut full = w.clone();
    let (actual, expected) = if let Some(request) = request {
        (
            transaction.execute(request.clone()),
            full.participant_apply(actor, request).map(Some),
        )
    } else {
        let intent = intent.unwrap();
        (
            transaction.execute_intent(intent.clone()),
            full.participant_client_intent(actor, intent),
        )
    };
    match (actual, expected) {
        (Err(actual), Err(expected)) => assert_eq!(actual, expected),
        (Ok(mut commit), Ok(receipt)) => {
            assert_eq!(json(&commit.receipt), json(&receipt));
            *w.players.iter_mut().find(|p| p.id == actor).unwrap() = commit.player;
            for lease in &mut commit.participant.evidence_leases {
                if let Some(id) = lease.observation.reference() {
                    lease.observation =
                        serde_json::value::RawValue::from_string(captures[&id].observation.clone())
                            .unwrap()
                            .into();
                }
            }
            w.participants.insert(actor, commit.participant);
            w.next_event = commit.next_event;
            w.events = commit.events;
            match commit.dirty {
                Some(v) => {
                    w.timing.dirty.insert(actor, v);
                }
                None => {
                    w.timing.dirty.remove(&actor);
                }
            }
            *w.laws.faults.lock() = commit.law_faults;
            assert_eq!(
                serde_json::to_value(&*w).unwrap(),
                serde_json::to_value(&full).unwrap(),
                "entire authoritative state must match"
            );
            assert_eq!(
                json(&w.events),
                json(&full.events),
                "exact audit and event ordering must match"
            );
        }
        _ => panic!("scoped and full command acceptance differs"),
    }
}
#[test]
fn native_components_roundtrip_full_dynamic_world_and_captured_reads() {
    for mut w in worlds() {
        for round in 0..3 {
            w.advance_ms(2500);
            let actor = w.players[round % w.players.len()].id;
            let r = request(
                &w,
                actor,
                Command::ReadObservation {
                    after: 0,
                    limit: 128,
                },
            );
            w.participant_apply(actor, r).unwrap();
            let (decoded, ids) = assemble(fixture(&w), None, true).unwrap();
            assert_eq!(
                serde_json::to_value(&decoded).unwrap(),
                serde_json::to_value(&w).unwrap()
            );
            assert_eq!(
                ids[&actor].len(),
                w.participants[&actor].evidence_leases.len()
            );
            assert_eq!(
                decoded.participant_status(actor).unwrap(),
                w.participant_status(actor).unwrap()
            );
        }
    }
}

#[test]
fn deferred_captures_are_not_read_by_physics_and_cannot_be_exported_incompletely() {
    let mut w = worlds().remove(0);
    let actor = w.players[0].id;
    let r = request(
        &w,
        actor,
        Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    );
    assert!(w.participant_apply(actor, r).unwrap().ok);
    let mut rows = fixture(&w);
    rows.captures.clear();
    assert!(assemble(fixture(&w), None, true).is_ok());
    let mut absent = fixture(&w);
    absent.captures.clear();
    assert!(
        assemble(absent, None, true).is_err(),
        "full export requires every payload"
    );
    let (mut light, _) = assemble(rows, None, false).unwrap();
    assert!(
        serde_json::to_string(&light).is_err(),
        "never serialize references as missing observation data"
    );
    assert!(light.participant_status(actor).is_err());
    light.events.clear();
    w.events.clear();
    light.advance_ms(2500);
    w.advance_ms(2500);
    let captures: BTreeMap<_, _> = fixture(&w)
        .captures
        .into_iter()
        .map(|c| (c.lease_id, c))
        .collect();
    for state in light.participants.values_mut() {
        for lease in &mut state.evidence_leases {
            if let Some(id) = lease.observation.reference() {
                lease.observation =
                    serde_json::value::RawValue::from_string(captures[&id].observation.clone())
                        .unwrap()
                        .into();
            }
        }
    }
    assert_eq!(
        serde_json::to_value(&light).unwrap(),
        serde_json::to_value(&w).unwrap()
    );
    assert_eq!(json(&light.events), json(&w.events));
}
#[test]
fn indexed_participant_scope_matches_full_kernel_for_commands_and_failures() {
    for mut w in worlds() {
        w.advance_ms(2500);
        let actor = w.players[0].id;
        for command in [
            Command::ReadObservation {
                after: 0,
                limit: 128,
            },
            Command::Speak {
                text: "A scoped message, awaiting physical delivery.".into(),
                expires_tick: w.tick + 20,
            },
            Command::ReplaceTree {
                expected_revision: w.players[0].generation,
                reason: "Wait here".into(),
                tree: Node::Action {
                    action: Action::new(Skill::Wait),
                },
            },
            Command::ReadObservation {
                after: u64::MAX,
                limit: 0,
            },
            Command::Reflect {
                expected_revision: 0,
                observed_cursor: u64::MAX,
                reflections: vec![],
                goal: None,
            },
            Command::PinObservation {
                observed_cursor: u64::MAX,
                sources: vec![],
            },
        ] {
            let r = request(&w, actor, command);
            differential(&mut w, actor, r);
        }
        let r = request(
            &w,
            actor,
            Command::PatchSubtree {
                expected_revision: w.players[0].generation,
                reason: "Rest instead".into(),
                path: "root".into(),
                subtree: Node::Action {
                    action: Action::new(Skill::Rest),
                },
            },
        );
        differential(&mut w, actor, r);
        let r = request(&w, actor, Command::ReadObservation { after: 0, limit: 1 });
        differential(&mut w, actor, r.clone());
        differential(&mut w, actor, r.clone());
        let mut reused = r.clone();
        reused.command = Command::ReadObservation { after: 1, limit: 1 };
        differential(&mut w, actor, reused);
        let mut stale = request(
            &w,
            actor,
            Command::ReadObservation {
                after: 0,
                limit: 128,
            },
        );
        stale.control_epoch += 1;
        differential(&mut w, actor, stale);
        if let Some(source) = w.participants[&actor]
            .experiences
            .iter()
            .find(|e| e.kind == "perception")
            .map(|e| e.source)
        {
            let cursor = w.participants[&actor].cursor;
            let r = request(
                &w,
                actor,
                Command::PinObservation {
                    observed_cursor: cursor,
                    sources: vec![source],
                },
            );
            differential(&mut w, actor, r);
            assert!(w.participants[&actor].receipts.last().unwrap().ok);
            let r = request(
                &w,
                actor,
                Command::Reflect {
                    expected_revision: w.participants[&actor].learning_revision,
                    observed_cursor: cursor,
                    goal: Some("Remember what I experienced".into()),
                    reflections: vec![simulation::Reflection {
                        source,
                        interpretation: "I observed my local surroundings.".into(),
                        knowledge: None,
                        caution_delta: 0,
                        trust_delta: 0,
                        belief: None,
                    }],
                },
            );
            differential(&mut w, actor, r);
            assert!(w.participants[&actor].receipts.last().unwrap().ok);
        }
        w.advance_ms(2500);
        for actor in w.players.iter().map(|p| p.id).collect::<Vec<_>>() {
            let r = request(
                &w,
                actor,
                Command::ReadObservation {
                    after: 0,
                    limit: 128,
                },
            );
            differential(&mut w, actor, r);
        }
        let actor = w.players[0].id;
        w.players[0].health = 0;
        let r = request(
            &w,
            actor,
            Command::ReadObservation {
                after: 0,
                limit: 128,
            },
        );
        differential(&mut w, actor, r);
    }
}

#[test]
fn scoped_presentation_and_human_intents_match_full_kernel() {
    for mut w in worlds() {
        w.advance_ms(2500);
        for actor in w.players.iter().map(|p| p.id).collect::<Vec<_>>() {
            let r = request(
                &w,
                actor,
                Command::ReadObservation {
                    after: 0,
                    limit: 16,
                },
            );
            differential(&mut w, actor, r);
            let light = scoped_materialized(&w, actor, true);
            let mut projected = simulation::client_view::snapshot(&light, false, actor, &[]);
            projected["can_participate"] =
                serde_json::json!(fixture(&w).actors.iter().any(|a| a.actor == 3 && a.human));
            assert_eq!(
                projected,
                simulation::client_view::snapshot(&w, false, actor, &[])
            );
            assert_eq!(
                light.participant_snapshot(actor, 0, 256).unwrap(),
                w.participant_snapshot(actor, 0, 256).unwrap()
            );
        }
        let actor = w.players[0].id;
        for intent in [
            serde_json::json!({"reason":"manual wait","actions":[{"skill":"wait"}]}),
            serde_json::json!({"reason":"say something","actions":[{"skill":"speak","text":"Human scoped speech"}]}),
            serde_json::json!({"reason":"invalid empty intent","actions":[]}),
            serde_json::to_value(simulation::Decision {
                reason: "replace policy".into(),
                actions: vec![],
                policy: Some(Node::Action {
                    action: Action::new(Skill::Rest),
                }),
                reflections: vec![],
            })
            .unwrap(),
        ] {
            let intent: simulation::Decision = serde_json::from_value(intent).unwrap();
            differential_operation(&mut w, actor, None, Some(intent));
        }
    }
}

#[test]
fn observer_render_matches_full_truth_with_one_private_inspector() {
    for mut w in worlds() {
        w.advance_ms(2500);
        let full = simulation::client_view::snapshot(&w, true, 0, &w.events);
        for actor in w.players.iter().map(|p| p.id) {
            let mut rows = fixture(&w);
            rows.minds.retain(|p| p.actor == actor);
            rows.mind_histories.retain(|p| p.actor == actor);
            rows.participants.retain(|p| p.actor == actor);
            rows.controllers.retain(|p| p.actor == actor);
            rows.bootstraps.retain(|p| p.actor == actor);
            rows.experiences.retain(|p| p.actor == actor);
            rows.leases.clear(); rows.lease_evidence.clear(); rows.captures.clear(); rows.receipts.clear();
            rows.aux = rows.aux.into_iter().map(|row| SimRenderActorSupport::from_aux(row).into_aux()).collect();
            let (light, _) = assemble(rows, Some(actor), false).unwrap();
            for selected in [Some(actor), None] {
                let projected = simulation::client_view::observer_render(&light, selected, &w.events);
                assert_eq!(projected, simulation::client_view::observer_render(&w, selected, &w.events));
                for player in projected["players"].as_array().unwrap() {
                    let id = player["id"].as_u64().unwrap() as u32;
                    let original = full["players"].as_array().unwrap().iter().find(|p| p["id"] == id).unwrap();
                    if selected == Some(id) { assert_eq!(player, original); }
                    else {
                        assert!(player.get("beliefs").is_none());
                        assert!(player.get("knowledge").is_none());
                        for field in ["id","name","position","health","hunger","energy","food","controller"] {
                            assert_eq!(player[field], original[field], "render field {field}");
                        }
                    }
                }
            }
        }
    }
}

#[test]
fn client_controller_rows_roundtrip_without_hydrating_seed_on_clock() {
    let scenario = serde_json::from_str(include_str!("../../../../../scenarios/survival.json")).unwrap();
    let mut original = World::new("native-client-boundary".into(),scenario).unwrap();
    original.enable_client_controllers().unwrap();
    let expected = serde_json::to_value(&original).unwrap();
    let (roundtrip,_) = assemble(fixture(&original),None,true).unwrap();
    assert_eq!(serde_json::to_value(&roundtrip).unwrap(),expected);
    let mut rows = fixture(&original);
    let bootstraps: BTreeMap<_,_> = std::mem::take(&mut rows.bootstraps).into_iter().map(|b|(b.actor,b)).collect();
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let seen = calls.clone();
    let reader = Arc::new(ColdReader {
        receipts:Box::new(|_,_|Err("unexpected receipts load".into())),
        bootstrap:Box::new(move |run,actor| {
            seen.fetch_add(1,std::sync::atomic::Ordering::SeqCst);
            let b=bootstraps.get(&actor).ok_or("missing seed")?;
            if b.run != run {return Err("foreign seed".into());}
            parse(&b.body)
        }),
        mind:Box::new(|_,_|Err("unexpected mind load".into())),
        experience:Box::new(|_,_,_|Err("unexpected experience load".into())),
        legacy_experiences:Box::new(|_,_|Err("unexpected trace load".into())),
        lease:Box::new(|_,_,_|Err("unexpected lease load".into())),
    });
    // Test the seed loader independently of the existing history loaders.
    let (mut roundtrip,_) = assemble(fixture(&original),None,true).unwrap();
    for c in rows.controllers {
        let (reader,run,actor)=(reader.clone(),c.run,c.actor);
        roundtrip.participants.get_mut(&actor).unwrap().client_controller.as_mut().unwrap().bootstrap = Deferred::load_with(move || (reader.bootstrap)(&run,actor));
    }
    roundtrip.advance_ms(50);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst),0);
    assert!(roundtrip.participants.values().all(|p|!p.client_controller.as_ref().unwrap().bootstrap.is_loaded()));
}
#[test]
fn unchanged_personal_evidence_reuses_heads_without_loading_history() {
    let mut state = ParticipantState::default();
    let row = SimNativeParticipant::from_state("retained-evidence", 3, &state);
    state.experiences = Deferred::load_with(|| Err("unchanged history must remain unloaded".into()));
    let previous = state.clone();
    state.control_epoch += 1;
    let heads = retained_experience_heads(&state, Some(&previous), Some(&row));
    assert_eq!(heads.as_deref(), Some(row.experiences.as_str()));
    let updated = SimNativeParticipant::from_state_with_heads("retained-evidence", 3, &state, heads);
    assert_eq!(updated.control_epoch, 1);
    assert_eq!(updated.experiences, row.experiences);
    assert!(!state.experiences.is_loaded());
    assert!(retained_experience_heads(&state, None, Some(&row)).is_none());
    let mut legacy = row.clone();
    legacy.experiences = "{\"native_experience_rows_v1\":[]}".into();
    assert!(retained_experience_heads(&state, Some(&previous), Some(&legacy)).is_none());
    state.experiences = Vec::new().into();
    assert!(retained_experience_heads(&state, Some(&previous), Some(&row)).is_none());
}

#[test]
fn deferred_render_matches_eager_without_experience_payload_reads() {
    use std::sync::atomic::Ordering;
    for mut world in worlds() {
        world.advance_ms(2500);
        let (cold, counts, _) = cold_fixture(&world);
        for player in &world.players {
            for observer in [false, true] {
                assert_eq!(
                    simulation::client_view::live_render(&cold, observer, player.id, Some(player.id)),
                    simulation::client_view::live_render(&world, observer, player.id, Some(player.id)));
            }
            assert_eq!(cold.participant_status(player.id).unwrap(), world.participant_status(player.id).unwrap());
        }
        assert_eq!(counts[1].load(Ordering::SeqCst), 0, "render must not load private experience payloads");
    }
}
