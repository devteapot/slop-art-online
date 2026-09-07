use super::*;
use simulation::{
    participant::{Command, Request, API_VERSION},
    participant_transaction::ParticipantTransaction,
    policy::Node,
    Action, Scenario, Skill,
};

fn fixture(w: &World) -> Rows {
    let mut next = 1;
    let mut captures = vec![];
    Rows {
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
