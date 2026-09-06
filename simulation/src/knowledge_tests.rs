use super::*;
use knowledge::{ArchiveSeed, KnowledgeDraft, RecordSeed, MAX_HOLDINGS};
use participant::{Command, Request, API_VERSION};

const SECRET: &str = "CEDAR-77: I suspect the eastern garden needs a day between harvests.";
fn scenario() -> Scenario {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    s.starting_behaviors.clear();
    s.knowledge.clear();
    s.archives = vec![
        ArchiveSeed {
            id: 7,
            position: 0,
            label: "Field ledger".into(),
            capacity: 2,
        },
        ArchiveSeed {
            id: 8,
            position: 0,
            label: "Backup ledger".into(),
            capacity: 2,
        },
    ];
    s.knowledge.insert(
        1,
        vec![RecordSeed {
            id: "garden-report".into(),
            topic: "Garden supplies".into(),
            text: SECRET.into(),
            location: Some(2),
            confidence: 45,
        }],
    );
    s.weather = None;
    s.max_ticks = 200;
    s.sites.iter_mut().for_each(|s| s.hazard = 0);
    for p in &mut s.players {
        p.position = 0;
        p.health = 100;
        p.energy = 80;
        p.hunger = 10;
        p.food = 2;
        p.beliefs.clear();
    }
    s
}
fn world() -> World {
    let mut w = World::new("knowledge-fixture".into(), scenario()).unwrap();
    w.enable_participants();
    w
}
fn action(skill: Skill, target: Option<u32>, archive: Option<u32>, record: Option<&str>) -> Action {
    Action {
        target,
        archive,
        record: record.map(str::to_owned),
        ..Action::new(skill)
    }
}
fn install(w: &mut World, actor: u32, a: Action) {
    w.participant_manual(
        actor,
        Decision {
            reason: "test a material knowledge operation".into(),
            actions: vec![a],
            policy: None,
            reflections: vec![],
        },
    )
    .unwrap();
}
fn finish(w: &mut World, actor: u32, a: Action, ms: u64) {
    install(w, actor, a);
    w.advance_ms(ms);
    assert!(
        !w.events.iter().any(|e| e.kind == "script_tick_failed"),
        "{:?}",
        w.events.last()
    );
}
fn reflect(
    w: &mut World,
    actor: u32,
    source: u64,
    knowledge: Option<KnowledgeDraft>,
) -> participant::Receipt {
    let cursor=w.participants[&actor].cursor;
    reflect_at(w,actor,source,cursor,knowledge)
}
fn reflect_at(w:&mut World,actor:u32,source:u64,observed_cursor:u64,knowledge:Option<KnowledgeDraft>)->participant::Receipt {
    w.participant_apply(
        actor,
        Request {
            api_version: API_VERSION.into(),
            request_id: format!("knowledge-reflection-{}", w.next_event),
            control_epoch: w.participants[&actor].control_epoch,
            command: Command::Reflect {
                expected_revision: w.participants[&actor].learning_revision,
                observed_cursor,
                reflections: vec![Reflection {
                    source,
                    interpretation: "I retain this as a tentative account, not an observed fact"
                        .into(),
                    caution_delta: 0,
                    trust_delta: 0,
                    belief: None,
                    knowledge,
                }],
                goal: None,
            },
        },
    )
    .unwrap()
}

#[test]
fn private_seed_and_archive_catalog_do_not_disclose_unconsulted_content() {
    let mut w = world();
    assert!(w.context(0).to_string().contains(SECRET));
    assert!(!w.context(1).to_string().contains(SECRET));
    finish(
        &mut w,
        1,
        action(Skill::Record, None, Some(7), Some("garden-report")),
        2500,
    );
    w.observe_site(1).unwrap();
    let catalog = w.local_archive_catalog(1);
    assert_eq!(catalog[0]["records"][0]["id"], "garden-report");
    assert_eq!(catalog[0]["records"][0]["topic"], "Garden supplies");
    assert!(!catalog.to_string().contains(SECRET));
    assert!(!w
        .participant_snapshot(2, 0, 256)
        .unwrap()
        .to_string()
        .contains(SECRET));
    assert!(w.players[1].knowledge.is_empty());
    let mut query = action(Skill::Consult, None, Some(7), Some("garden-report"));
    w.players[1].position = 5;
    assert!(w.knowledge_script_context(1, &query)["archive"].is_null());
    query.archive = Some(9999);
    assert!(w.knowledge_script_context(1, &query)["archive"].is_null());
}

#[test]
fn teaching_takes_time_and_human_ai_capabilities_have_identical_costs() {
    let mut s = scenario();
    s.knowledge.insert(
        3,
        vec![RecordSeed {
            id: "human-report".into(),
            topic: "Garden supplies".into(),
            text: SECRET.into(),
            location: Some(2),
            confidence: 45,
        }],
    );
    let mut w = World::new("knowledge-parity".into(), s).unwrap();
    w.enable_participants();
    let scripts = serde_json::to_value(&w.scripts).unwrap();
    for (actor, id) in [(1, "garden-report"), (3, "human-report")] {
        install(&mut w, actor, action(Skill::Teach, Some(2), None, Some(id)));
    }
    w.advance_ms(1999);
    assert!(w.players[1].knowledge.is_empty());
    assert_eq!((w.players[0].energy, w.players[2].energy), (80, 80));
    w.advance_ms(1);
    assert_eq!(w.players[1].knowledge.len(), 2);
    assert_eq!((w.players[0].energy, w.players[2].energy), (78, 78));
    assert!(w.players[1]
        .knowledge
        .iter()
        .all(|h| h.interpretation.is_none() && h.confidence.is_none()));
    assert_eq!(
        serde_json::to_value(&w.scripts).unwrap(),
        scripts,
        "receiving a report must not install skills"
    );
    for h in &w.players[1].knowledge {
        assert_eq!(h.record.text, SECRET);
        assert_eq!(h.record.confidence, 45);
        assert!(w.participants[&2]
            .experiences
            .iter()
            .any(|e| e.source == h.source
                && e.kind == "perception"
                && e.data["kind"] == "knowledge_report"));
    }
}

#[test]
fn recipient_departure_or_death_before_completion_prevents_transfer_and_cost() {
    for dead in [false, true] {
        let mut w = world();
        install(
            &mut w,
            1,
            action(Skill::Teach, Some(2), None, Some("garden-report")),
        );
        w.advance_ms(1000);
        if dead {
            w.players[1].health = 0;
        } else {
            w.players[1].position = 1;
        }
        w.advance_ms(1000);
        assert_eq!(w.players[0].energy, 80);
        assert!(w.players[1].knowledge.is_empty());
        assert!(!w.events.iter().any(|e| e.kind == "knowledge_taught"));
        assert!(w.events.iter().any(|e| e.actor == Some(1)
            && e.kind == "skill_result"
            && e.data["status"] == "failed"));
    }
}

#[test]
fn archive_survives_author_death_and_a_consulted_copy_survives_archive_destruction() {
    let mut w = world();
    let original = w.players[0].knowledge[0].record.clone();
    finish(
        &mut w,
        1,
        action(Skill::Record, None, Some(7), Some("garden-report")),
        2500,
    );
    w.players[0].health = 0;
    finish(
        &mut w,
        2,
        action(Skill::Consult, None, Some(7), Some("garden-report")),
        1500,
    );
    assert_eq!(w.players[1].knowledge[0].record, original);
    assert_ne!(
        w.players[1].knowledge[0].source,
        w.players[0].knowledge[0].source
    );
    finish(
        &mut w,
        3,
        action(Skill::DestroyArchive, None, Some(7), None),
        5000,
    );
    assert!(w.archives[0].destroyed && w.archives[0].records.is_empty());
    assert_eq!(w.players[1].knowledge[0].record, original);
    finish(
        &mut w,
        2,
        action(Skill::Record, None, Some(8), Some("garden-report")),
        2500,
    );
    assert_eq!(w.archives[1].records, vec![original]);
    assert_eq!(w.players[1].energy, 75);
}

#[test]
fn destroying_last_copy_and_losing_last_carrier_never_resurrects_from_seed_or_audit() {
    let mut w = world();
    finish(
        &mut w,
        1,
        action(Skill::Record, None, Some(7), Some("garden-report")),
        2500,
    );
    w.players[0].health = 0;
    finish(
        &mut w,
        3,
        action(Skill::DestroyArchive, None, Some(7), None),
        5000,
    );
    assert!(serde_json::to_string(&w.initial).unwrap().contains(SECRET));
    assert!(serde_json::to_string(&w.events).unwrap().contains(SECRET));
    assert!(!w
        .participant_snapshot(2, 0, 256)
        .unwrap()
        .to_string()
        .contains(SECRET));
    let mut restored: World = serde_json::from_value(serde_json::to_value(&w).unwrap()).unwrap();
    restored.enable_participants();
    let energy = restored.players[1].energy;
    finish(
        &mut restored,
        2,
        action(Skill::Consult, None, Some(7), Some("garden-report")),
        1500,
    );
    assert!(restored.players[1].knowledge.is_empty());
    assert_eq!(restored.players[1].energy, energy);
    assert!(!restored
        .participant_snapshot(2, 0, 256)
        .unwrap()
        .to_string()
        .contains(SECRET));
    let teach = action(Skill::Teach, Some(2), None, Some("garden-report"));
    assert!(restored
        .validate_knowledge_effect(
            0,
            &teach,
            &scripting::Effect::Teach {
                target: 2,
                record: "garden-report".into()
            }
        )
        .is_err());
}

#[test]
fn conflicting_reports_remain_distinct_and_learning_creates_no_world_truth_or_mastery() {
    let mut s = scenario();
    s.knowledge.insert(
        3,
        vec![RecordSeed {
            id: "contrary-report".into(),
            topic: "Garden supplies".into(),
            text: "I claim there is never food at the eastern garden.".into(),
            location: Some(2),
            confidence: 90,
        }],
    );
    let mut w = World::new("conflicting-knowledge".into(), s).unwrap();
    w.enable_participants();
    let sites = serde_json::to_value(&w.sites).unwrap();
    let registry = serde_json::to_value(&w.scripts).unwrap();
    finish(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
        2000,
    );
    finish(
        &mut w,
        3,
        action(Skill::Teach, Some(2), None, Some("contrary-report")),
        2000,
    );
    let reports = w.players[1].knowledge.clone();
    assert_eq!(reports.len(), 2);
    assert_eq!(reports[0].record.topic, reports[1].record.topic);
    assert_ne!(reports[0].record.text, reports[1].record.text);
    assert!(reflect(&mut w, 2, reports[0].source, None).ok);
    assert!(w.players[1].knowledge[0].interpretation.is_some());
    assert!(w.players[1].knowledge[1].interpretation.is_none());
    assert_eq!(serde_json::to_value(&w.sites).unwrap(), sites);
    assert_eq!(serde_json::to_value(&w.scripts).unwrap(), registry);
    assert!(w.players[1].beliefs.is_empty());
    assert!(
        reflect(
            &mut w,
            2,
            reports[1].source,
            Some(KnowledgeDraft {
                topic: "Garden supplies".into(),
                text: "These accounts conflict; I intend to inspect the garden.".into(),
                location: Some(2),
                confidence: 30,
            })
        )
        .ok
    );
    assert_eq!(w.players[1].knowledge.len(), 3);
    let new = &w.players[1].knowledge[2];
    assert_eq!(new.record.author, 2);
    assert_ne!(new.record.id, reports[0].record.id);
    assert_ne!(new.record.id, reports[1].record.id);
    assert_eq!(new.confidence, Some(30));
    assert!(w
        .events
        .iter()
        .any(|e| e.id == new.record.origin && e.parents.contains(&reports[1].source)));
    assert_eq!(w.players[1].knowledge[0].record, reports[0].record);
    assert_eq!(w.players[1].knowledge[1].record, reports[1].record);
}

#[test]
fn duplicate_copies_do_not_overwrite_interpretation_or_count_as_new_knowledge() {
    let mut w = world();
    finish(
        &mut w,
        1,
        action(Skill::Record, None, Some(7), Some("garden-report")),
        2500,
    );
    finish(
        &mut w,
        2,
        action(Skill::Consult, None, Some(7), Some("garden-report")),
        1500,
    );
    let source = w.players[1].knowledge[0].source;
    assert!(reflect(&mut w, 2, source, None).ok);
    let held = w.players[1].knowledge[0].clone();
    finish(
        &mut w,
        2,
        action(Skill::Consult, None, Some(7), Some("garden-report")),
        1500,
    );
    finish(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
        2000,
    );
    assert_eq!(w.players[1].knowledge.len(), 1);
    let refreshed = w.players[1].knowledge[0].clone();
    assert_eq!(refreshed.record, held.record);
    assert_eq!(refreshed.interpretation, held.interpretation);
    assert_eq!(refreshed.confidence, held.confidence);
    assert_ne!(refreshed.source, held.source);
    assert!(reflect(&mut w, 2, refreshed.source, None).ok);
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.kind == "knowledge_consulted" && e.data["new_copy"] == true)
            .count(),
        1
    );
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.kind == "knowledge_consulted" && e.data["new_copy"] == false)
            .count(),
        1
    );
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "knowledge_taught" && e.data["new_copy"] == false));
}

#[test]
fn archive_storage_is_bounded_and_payload_identity_collisions_fail_without_costs() {
    let mut w = world();
    w.archives[0].capacity = 1;
    finish(
        &mut w,
        1,
        action(Skill::Record, None, Some(7), Some("garden-report")),
        2500,
    );
    let mut conflicting = w.players[0].knowledge[0].clone();
    conflicting.record.text = "A forged payload under the same record identity".into();
    w.players[1].knowledge.push(conflicting);
    let energy = w.players[1].energy;
    finish(
        &mut w,
        2,
        action(Skill::Record, None, Some(7), Some("garden-report")),
        2500,
    );
    assert_eq!(w.archives[0].records[0].text, SECRET);
    assert_eq!(w.players[1].energy, energy);
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "script_error" && e.data["effects_committed"] == false));
    assert_eq!(w.archives[0].revision, 1);
}

#[test]
fn invalid_initial_archives_and_knowledge_reject_the_whole_world() {
    for case in 0..7 {
        let mut s = scenario();
        match case {
            0 => s.archives[0].capacity = 0,
            1 => s.archives[1].id = 7,
            2 => s.archives[0].position = 999,
            3 => s.knowledge.get_mut(&1).unwrap()[0].confidence = 101,
            4 => s.knowledge.get_mut(&1).unwrap()[0].id = "bad id".into(),
            5 => {
                let records = s.knowledge.remove(&1).unwrap();
                s.knowledge.insert(999, records);
            }
            _ => {
                let record = s.knowledge[&1][0].clone();
                s.knowledge.insert(3, vec![record]);
            }
        }
        assert!(World::new(format!("bad-knowledge-{case}"), s).is_err());
    }
}

#[test]
fn full_personal_storage_rejects_teaching_without_discarding_old_reports() {
    let mut s = scenario();
    s.knowledge.insert(
        2,
        (0..MAX_HOLDINGS)
            .map(|n| RecordSeed {
                id: format!("existing-{n}"),
                topic: format!("Topic {n}"),
                text: "A retained assertion".into(),
                location: None,
                confidence: 50,
            })
            .collect(),
    );
    let mut w = World::new("full-personal-storage".into(), s).unwrap();
    w.enable_participants();
    let retained = w.players[1].knowledge.clone();
    finish(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
        2000,
    );
    assert_eq!(w.players[1].knowledge, retained);
    assert_eq!(w.players[0].energy, 80);
}

#[test]
fn consulted_location_is_a_report_and_draft_locations_remain_actor_scoped() {
    let mut w = world();
    let foreign_source = w.players[0].knowledge[0].source;
    let draft = KnowledgeDraft {
        topic: "Invented attribution".into(),
        text: "A claim citing another person's private evidence".into(),
        location: Some(2),
        confidence: 40,
    };
    assert!(!reflect(&mut w, 2, foreign_source, Some(draft)).ok);
    assert!(w.players[1].knowledge.is_empty());
    let own_source = w.players[1]
        .memories
        .iter()
        .find(|m| m.kind == "site")
        .unwrap()
        .source;
    let draft = KnowledgeDraft {
        topic: "Out of bounds".into(),
        text: "A speculation about an unreachable world".into(),
        location: Some(1000),
        confidence: 40,
    };
    assert!(!reflect(&mut w, 2, own_source, Some(draft)).ok);
    assert!(w.players[1].knowledge.is_empty());
    finish(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
        2000,
    );
    assert_eq!(w.players[1].knowledge[0].record.location, Some(2));
    assert!(
        !w.players[1]
            .site_observations
            .iter()
            .any(|m| m.location == 2),
        "teaching must not fabricate direct site observation"
    );
}

#[test]
fn environmental_archive_loss_is_local_and_invalidates_inflight_consultation() {
    let mut w = world();
    finish(
        &mut w,
        1,
        action(Skill::Record, None, Some(7), Some("garden-report")),
        2500,
    );
    w.players[2].position = 5;
    install(
        &mut w,
        2,
        action(Skill::Consult, None, Some(7), Some("garden-report")),
    );
    w.advance_ms(750);
    assert!(w.players[1].knowledge.is_empty());
    let cause = w.event(
        None,
        "authored_test_disturbance",
        vec![],
        json!({"nature":"archive loss"}),
    );
    w.destroy_physical_archive(7, cause, None).unwrap();
    w.advance_ms(750);
    assert!(w.players[1].knowledge.is_empty());
    assert_eq!(w.players[1].energy, 80);
    let loss = w
        .events
        .iter()
        .find(|e| e.kind == "archive_destroyed")
        .unwrap();
    assert_eq!(loss.actor, None);
    assert_eq!(loss.parents, vec![cause]);
    assert!(w.players[1]
        .memories
        .iter()
        .any(|m| m.kind == "archive_destroyed" && m.from.is_none()));
    assert!(!w.players[2]
        .memories
        .iter()
        .any(|m| m.kind == "archive_destroyed"));
}

#[test]
fn seeded_assertions_cannot_smuggle_locations_from_another_arena() {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/luna-arena-matrix.json")).unwrap();
    s.starting_behaviors.clear();
    s.knowledge.clear();
    s.archives.clear();
    let actor = s.arenas[0].actors[0];
    let other = s.arenas[1].actors[0];
    let remote = s.players.iter().find(|p| p.id == other).unwrap().position;
    assert!(s.map.as_ref().unwrap().walkable(remote));
    assert!(World::new("scoped-knowledge-control".into(), s.clone()).is_ok());
    s.knowledge.insert(
        actor,
        vec![RecordSeed {
            id: "cross-arena".into(),
            topic: "Remote site".into(),
            text: "An out-of-scope report".into(),
            location: Some(remote),
            confidence: 10,
        }],
    );
    assert!(World::new("scoped-knowledge-rejection".into(), s).is_err());
}

#[test]
fn maximum_unicode_personal_records_do_not_overflow_behavior_guard_input() {
    let mut s = scenario();
    s.knowledge.insert(
        1,
        (0..MAX_HOLDINGS)
            .map(|n| RecordSeed {
                id: format!("unicode-{n}"),
                topic: "A long retained account".into(),
                text: "界".repeat(1280),
                location: None,
                confidence: 50,
            })
            .collect(),
    );
    let mut w = World::new("bounded-unicode-knowledge".into(), s).unwrap();
    w.enable_participants();
    assert!(serde_json::to_vec(&w.players[0].knowledge).unwrap().len() > 65_536);
    let last = w.players[0].knowledge.last().unwrap();
    let condition = Condition::HasKnowledge {
        record: last.record.id.clone(),
    };
    assert_eq!(condition.evaluate(&w.players[0]), (true, vec![last.source]));
    w.participant_manual(
        1,
        Decision {
            reason: "exercise full-storage guard".into(),
            actions: vec![],
            policy: Some(Node::Guard {
                condition,
                child: Box::new(Node::Action {
                    action: Action::new(Skill::Rest),
                }),
            }),
            reflections: vec![],
        },
    )
    .unwrap();
    w.advance_ms(2500);
    assert_eq!(w.players[0].energy, 92);
    assert!(!w
        .events
        .iter()
        .any(|e| matches!(e.kind.as_str(), "script_error" | "script_tick_failed")));
}

#[test]
fn an_actual_received_report_changes_a_previously_installed_conditional_action() {
    let mut w = world();
    let policy = Node::Priority {
        children: vec![
            Node::Guard {
                condition: Condition::HasKnowledge {
                    record: "garden-report".into(),
                },
                child: Box::new(Node::Action {
                    action: Action::go(2),
                }),
            },
            Node::Action {
                action: Action::new(Skill::Wait),
            },
        ],
    };
    w.participant_manual(
        2,
        Decision {
            reason: "visit the garden if I receive the report".into(),
            actions: vec![],
            policy: Some(policy),
            reflections: vec![],
        },
    )
    .unwrap();
    install(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
    );
    let revision = w.players[1].generation;
    w.advance_ms(1000);
    assert_eq!(w.players[1].position, 0);
    assert!(w.players[1].knowledge.is_empty());
    w.advance_ms(1000);
    assert!(!w.players[1].knowledge.is_empty());
    assert_eq!(w.players[1].position, 1);
    assert_eq!(
        w.players[1].generation, revision,
        "receipt must not rewrite the installed policy"
    );
    assert!(w.events.iter().any(|e| e.actor == Some(2)
        && e.kind == "skill_attempt"
        && e.data["action"]["skill"] == "move"));
    assert!(!w.events.iter().any(|e| e.kind.starts_with("model_")));
}

fn assess_report(
    w: &mut World,
    actor: u32,
    source: u64,
    observed_cursor: u64,
    interpretation: &str,
) -> participant::Receipt {
    w.participant_apply(
        actor,
        Request {
            api_version: API_VERSION.into(),
            request_id: format!("assess-report-{}", w.next_event),
            control_epoch: w.participants[&actor].control_epoch,
            command: Command::Reflect {
                expected_revision: w.participants[&actor].learning_revision,
                observed_cursor,
                reflections: vec![Reflection {
                    source,
                    interpretation: interpretation.into(),
                    caution_delta: 0,
                    trust_delta: 0,
                    belief: None,
                    knowledge: None,
                }],
                goal: None,
            },
        },
    )
    .unwrap()
}

#[test]
fn an_older_leased_receipt_can_assess_a_report_after_duplicate_acquisition_and_trace_eviction() {
    let mut w = world();
    finish(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
        2000,
    );
    let older = w.players[1].knowledge[0].source;
    let cursor = w.participants[&2].cursor;
    assert!(
        w.participant_apply(
            2,
            Request {
                api_version: API_VERSION.into(),
                request_id: "lease-original-report".into(),
                control_epoch: w.participants[&2].control_epoch,
                command: Command::PinObservation {
                    observed_cursor: cursor,
                    sources: vec![older]
                },
            }
        )
        .unwrap()
        .ok
    );
    finish(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
        2000,
    );
    let latest = w.players[1].knowledge[0].source;
    assert!(latest > older);
    assert!(w.players[1].knowledge[0].interpretation.is_none());
    // Evict the old source from both ordinary retention windows; only the private
    // evidence lease can authorize this still-in-flight interpretation.
    for _ in 0..100 {
        w.observe_site(1).unwrap();
    }
    assert!(!w.players[1].memories.iter().any(|p| p.source == older));
    assert!(!w.participants[&2]
        .experiences
        .iter()
        .any(|e| e.source == older));
    assert!(w.participants[&2]
        .evidence_leases
        .iter()
        .any(|l| l.experiences.iter().any(|e| e.source == older)));
    w.events.clear();
    let interpretation = "The earlier teaching is useful but remains uncertain.";
    let receipt = assess_report(&mut w, 2, older, cursor, interpretation);
    assert!(receipt.ok, "{:?}", receipt.error);
    let held = &w.players[1].knowledge[0];
    assert_eq!(
        held.source, latest,
        "assessment must not rewind acquisition"
    );
    assert_eq!(held.interpreted_source, Some(older));
    assert_eq!(held.interpretation.as_deref(), Some(interpretation));
    assert_eq!(held.record.text, SECRET);
}

#[test]
fn an_older_unused_receipt_cannot_overwrite_assessment_of_a_newer_receipt() {
    let mut w = world();
    finish(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
        2000,
    );
    let older = w.players[1].knowledge[0].source;
    finish(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
        2000,
    );
    let newer = w.players[1].knowledge[0].source;
    let cursor = w.participants[&2].cursor;
    let latest_assessment = "I considered the more recent receipt and remain cautious.";
    assert!(assess_report(&mut w, 2, newer, cursor, latest_assessment).ok);
    let cursor = w.participants[&2].cursor;
    assert!(
        assess_report(
            &mut w,
            2,
            older,
            cursor,
            "An older assessment should not replace it."
        )
        .ok
    );
    let held = &w.players[1].knowledge[0];
    assert_eq!(held.source, newer);
    assert_eq!(held.interpreted_source, Some(newer));
    assert_eq!(held.interpretation.as_deref(), Some(latest_assessment));
}

#[test]
fn legacy_raw_perception_receipts_resolve_the_same_immutable_report() {
    let mut w = world();
    finish(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
        2000,
    );
    let older = w.players[1].knowledge[0].source;
    finish(
        &mut w,
        1,
        action(Skill::Teach, Some(2), None, Some("garden-report")),
        2000,
    );
    let latest = w.players[1].knowledge[0].source;
    assert!(w.players[1]
        .memories
        .iter()
        .any(|p| p.source == older && p.kind == "knowledge_report"));
    w.participant_mode = false;
    w.submit(
        2,
        Controller::Ai,
        Decision {
            reason: "Interpret retained direct report evidence".into(),
            actions: vec![Action::new(Skill::Wait)],
            policy: None,
            reflections: vec![Reflection {
                source: older,
                interpretation: "This old receipt still refers to my same report.".into(),
                caution_delta: 0,
                trust_delta: 0,
                belief: None,
                knowledge: None,
            }],
        },
        None,
    )
    .unwrap();
    assert_eq!(w.players[1].knowledge[0].source, latest);
    assert_eq!(w.players[1].knowledge[0].interpreted_source, Some(older));
    assert!(w.players[1].knowledge[0].interpretation.is_some());
}

#[test]
fn maximum_local_archive_catalog_does_not_overflow_unrelated_behavior_guards() {
    let mut s = scenario();
    s.archives = (0..knowledge::MAX_ARCHIVES)
        .map(|n| ArchiveSeed {
            id: n as u32 + 1,
            position: 0,
            label: format!("Public ledger {n}"),
            capacity: knowledge::MAX_RECORDS,
        })
        .collect();
    let topic = "界".repeat(160);
    s.knowledge.insert(
        1,
        (0..MAX_HOLDINGS)
            .map(|n| RecordSeed {
                id: format!("catalog-report-{n}"),
                topic: topic.clone(),
                text: "A bounded attributed report".into(),
                location: None,
                confidence: 50,
            })
            .collect(),
    );
    let mut w = World::new("bounded-archive-catalog".into(), s).unwrap();
    w.enable_participants();
    // These are legitimate identical copies; construct them directly so this
    // projection test does not require 1024 separate recording actions.
    let copies: Vec<_> = w.players[0]
        .knowledge
        .iter()
        .map(|h| h.record.clone())
        .collect();
    for archive in &mut w.archives {
        archive.records = copies.clone();
        archive.revision = 1;
    }
    w.observe_site(0).unwrap();
    let catalog = w.local_archive_catalog(0);
    assert!(serde_json::to_vec(&catalog).unwrap().len() > 65_536);
    let observation = w.players[0]
        .site_observations
        .iter()
        .find(|p| p.location == 0)
        .unwrap();
    assert_eq!(
        observation.content["archives"], catalog,
        "perception must retain the full local catalog"
    );
    assert_eq!(
        observation.content["archives"][0]["records"][0]["topic"],
        topic
    );
    assert!(
        serde_json::to_vec(&scripting::subjective(&w.players[0]))
            .unwrap()
            .len()
            < 65_536
    );
    assert!(w.context(0)["player"]["site_observations"]
        .as_array()
        .unwrap()
        .iter()
        .any(|p| p["location"] == 0 && p["content"]["archives"] == catalog));
    w.participant_manual(
        1,
        Decision {
            reason: "An unrelated local food guard must work beside a large archive".into(),
            actions: vec![],
            policy: Some(Node::Guard {
                condition: Condition::FoodAt {
                    location: 0,
                    minimum: 1,
                },
                child: Box::new(Node::Action {
                    action: Action::new(Skill::Rest),
                }),
            }),
            reflections: vec![],
        },
    )
    .unwrap();
    w.advance_ms(2500);
    assert!(
        !w.events
            .iter()
            .any(|e| matches!(e.kind.as_str(), "script_error" | "script_tick_failed")),
        "{:?}",
        w.events
            .iter()
            .filter(|e| matches!(e.kind.as_str(), "script_error" | "script_tick_failed"))
            .collect::<Vec<_>>()
    );
    assert_eq!(w.players[0].energy, 92);
}

#[test]
fn rereading_expired_acquisition_is_paid_and_restores_personal_citable_evidence() {
    let mut w = world();
    let held = w.players[0].knowledge[0].clone();
    // Actual private trace churn, without recovering the receipt from audit history.
    for n in 0..participant::TRACE_LIMIT + 1 {
        let event = w.event(Some(1), "reread_fixture", vec![], json!({}));
        w.perceive(0, event, "heard", None, 0, json!({"text":format!("ordinary trace {n}")})).unwrap();
    }
    assert!(!w.participants[&1].experiences.iter().any(|e| e.source == held.source));
    assert!(!reflect(&mut w, 1, held.source, None).ok);
    assert_eq!(w.players[0].knowledge[0].record, held.record);
    let energy = w.players[0].energy;
    install(&mut w, 1, action(Skill::RereadRecord, None, None, Some("garden-report")));
    w.advance_ms(1499);
    assert_eq!(w.players[0].knowledge[0].source, held.source);
    assert_eq!(w.players[0].energy, energy);
    w.advance_ms(1);
    let refreshed = w.players[0].knowledge[0].clone();
    assert_eq!(w.players[0].energy, energy - 1);
    assert_ne!(refreshed.source, held.source);
    assert_eq!(refreshed.record, held.record);
    assert_eq!(refreshed.interpretation, held.interpretation);
    assert_eq!(w.players[0].knowledge.len(), 1);
    assert_eq!(w.archives.iter().map(|a| a.records.len()).sum::<usize>(), 0);
    assert!(w.players[1].knowledge.is_empty());
    let receipt = w.participants[&1].experiences.iter().find(|e|e.source == refreshed.source).unwrap();
    assert_eq!(receipt.data["kind"], "knowledge_report");
    assert_eq!(receipt.data["content"]["new_copy"], false);
    assert!(!w.participants[&2].experiences.iter().any(|e|e.source == refreshed.source));
    assert!(reflect(&mut w, 1, refreshed.source, None).ok);
    assert!(w.players[0].knowledge[0].interpretation.is_some());
}

#[test]
fn rereading_preserves_existing_interpretation_and_durable_identity() {
    let mut w = world();
    let source = w.players[0].knowledge[0].source;
    assert!(reflect(&mut w, 1, source, None).ok);
    let held = w.players[0].knowledge[0].clone();
    finish(&mut w, 1, action(Skill::RereadRecord, None, None, Some("garden-report")), 1500);
    let after = &w.players[0].knowledge[0];
    assert_eq!(after.record, held.record);
    assert_eq!(after.interpretation, held.interpretation);
    assert_eq!(after.interpreted_source, held.interpreted_source);
    assert_eq!(after.confidence, held.confidence);
    assert_ne!(after.source, held.source);
    let source = after.source;
    assert!(reflect(&mut w, 1, source, None).ok);
    assert_eq!(w.players[0].knowledge.len(), 1);
}

#[test]
fn rereading_rejects_foreign_missing_dead_and_substituted_records() {
    use scripting::Effect;
    for (actor, record, dead) in [(2, "garden-report", false), (1, "missing", false), (1, "garden-report", true)] {
        let mut w = world();
        let i = w.idx(actor).unwrap();
        if dead { w.players[i].health = 0; }
        let a = action(Skill::RereadRecord, None, None, Some(record));
        let effect = Effect::ReadRecord { record:record.into() };
        assert!(w.validate_script_effect(i, &a, &effect).is_err());
        let before = w.players[i].knowledge.clone();
        let energy = w.players[i].energy;
        if !dead { finish(&mut w, actor, a, 1500); }
        assert_eq!(w.players[i].energy, energy);
        assert_eq!(serde_json::to_value(&w.players[i].knowledge).unwrap(), serde_json::to_value(before).unwrap());
        assert!(!w.events.iter().any(|e| e.kind == "knowledge_reread"));
    }
    let mut w = world();
    let effect = Effect::ReadRecord { record:"garden-report".into() };
    assert!(w.validate_script_effect(0, &action(Skill::RereadRecord, None, None, Some("different")), &effect).is_err());
    assert!(w.validate_script_effect(0, &action(Skill::Consult, None, Some(7), Some("garden-report")), &effect).is_err());
    let result = w.participant_manual(1, Decision { reason:"invalid reread target".into(), actions:vec![action(Skill::RereadRecord,Some(2),None,Some("garden-report"))], policy:None,reflections:vec![] });
    assert!(result.is_err());
    // Losing the copy during an otherwise valid action must cancel its receipt and cost.
    install(&mut w, 1, action(Skill::RereadRecord, None, None, Some("garden-report")));
    w.advance_ms(750);
    w.players[0].knowledge.clear();
    w.advance_ms(750);
    assert_eq!(w.players[0].energy, 80);
    assert!(!w.events.iter().any(|e|e.kind == "knowledge_reread"));
}

#[test]
fn rereading_executable_record_reports_metadata_without_source_inspection() {
    let mut w = world();
    let program = research_programs::compile(&research_programs::ProgramDraft {
        interface_version:1, source:"// private_reread_source_82971\nfn technique(input){input}".into(), input_contract:"Numbers".into(),output_contract:"Same numbers".into()
    }).unwrap();
    w.players[0].knowledge[0].record.program = Some(program.clone());
    finish(&mut w, 1, action(Skill::RereadRecord, None, None, Some("garden-report")), 1500);
    let held = &w.players[0].knowledge[0];
    assert_eq!(held.record.program.as_ref(), Some(&program));
    let report = w.players[0].memories.iter().find(|m|m.source == held.source).unwrap();
    assert_eq!(report.kind, "knowledge_report");
    assert!(report.content["record"]["program"].get("source").is_none());
    assert_eq!(report.content["record"]["program"]["source_omitted"], true);
    assert!(!w.context(0).to_string().contains("private_reread_source_82971"));
    assert!(!crate::client_view::snapshot(&w, false, 1, &w.events).to_string().contains("private_reread_source_82971"));
    assert!(!w.players[0].memories.iter().any(|m|m.kind == "program_inspected"));
}

fn derived_draft() -> KnowledgeDraft {
    KnowledgeDraft {topic:"Conditional inference".into(),text:"The reported result suggests a hypothesis under its supplied conditions, not a general fact.".into(),location:None,confidence:35}
}
#[test]
fn derived_assertion_also_assesses_its_held_report_without_copying_its_payload() {
    let mut w=world();
    let original=w.players[0].knowledge[0].clone();
    assert!(reflect(&mut w,1,original.source,Some(derived_draft())).ok);
    let held=&w.players[0].knowledge[0];
    assert_eq!(held.record,original.record);assert_eq!(held.source,original.source);
    assert_eq!(held.interpreted_source,Some(original.source));assert!(held.interpretation.is_some());
    let derived=w.players[0].knowledge.last().unwrap();
    assert_ne!(derived.record.id,held.record.id);assert_eq!(derived.record.author,1);
    assert!(derived.record.program.is_none());assert!(derived.record.experiment.is_none());
    assert_eq!(derived.interpreted_source,Some(original.source));
    assert!(w.events.iter().any(|e|e.kind=="knowledge_asserted" && e.parents==vec![original.source]));
}
#[test]
fn invalid_optional_assertion_does_not_partially_assess_or_change_identity() {
    for mode in 0..4 {
        let mut w=world();let source=w.players[0].knowledge[0].source;
        let evidence=w.players[0].memories.iter().find(|p|p.source==source).unwrap().clone();
        let mut draft=derived_draft();
        match mode {0=>draft.confidence=101,1=>draft.text.clear(),2=>{w.initial.map=Some(spatial::Grid{width:4,height:2,blocked:Default::default(),bounds:None});draft.location=Some(-1)},_=>{
            let original=w.players[0].knowledge[0].clone();
            for n in 1..MAX_HOLDINGS {let mut h=original.clone();h.record.id=format!("fixture-{n}");w.players[0].knowledge.push(h);}
        }}
        let reflection=Reflection{source,interpretation:"I assessed the original report, but this whole request must reject.".into(),caution_delta:5,trust_delta:0,belief:None,knowledge:Some(draft.clone())};
        let before=serde_json::to_value(&w).unwrap();let events=serde_json::to_value(&w.events).unwrap();
        assert!(w.interpret_knowledge(0,&reflection,&evidence).is_err(),"mode {mode}");
        assert_eq!(serde_json::to_value(&w).unwrap(),before);assert_eq!(serde_json::to_value(&w.events).unwrap(),events);
        let player=serde_json::to_value(&w.players[0]).unwrap();let revision=w.participants[&1].learning_revision;
        assert!(!reflect(&mut w,1,source,Some(draft)).ok);
        assert_eq!(serde_json::to_value(&w.players[0]).unwrap(),player);assert_eq!(w.participants[&1].learning_revision,revision);
        assert!(!w.events.iter().any(|e|e.kind=="knowledge_asserted"));
    }
}
#[test]
fn optional_assertion_respects_leased_evidence_order_and_does_not_restore_a_missing_copy() {
    let mut w=world();
    finish(&mut w,1,action(Skill::Teach,Some(2),None,Some("garden-report")),2000);
    let older=w.players[1].knowledge[0].source;let cursor=w.participants[&2].cursor;
    assert!(w.participant_apply(2,Request{api_version:API_VERSION.into(),request_id:"assertion-lease".into(),control_epoch:w.participants[&2].control_epoch,command:Command::PinObservation{observed_cursor:cursor,sources:vec![older]}}).unwrap().ok);
    finish(&mut w,1,action(Skill::Teach,Some(2),None,Some("garden-report")),2000);
    let newer=w.players[1].knowledge[0].source;let newer_cursor=w.participants[&2].cursor;
    assert!(w.participant_apply(2,Request{api_version:API_VERSION.into(),request_id:"assertion-newer-lease".into(),control_epoch:w.participants[&2].control_epoch,command:Command::PinObservation{observed_cursor:w.participants[&2].cursor,sources:vec![newer]}}).unwrap().ok);
    let mut missing=w.clone();missing.players[1].knowledge.clear();
    for _ in 0..100 {w.observe_site(1).unwrap();}
    assert!(!w.players[1].memories.iter().any(|p|p.source==older));
    assert!(!w.participants[&2].experiences.iter().any(|e|e.source==older));
    let mut branch=w.clone();
    let receipt=reflect_at(&mut branch,2,older,cursor,Some(derived_draft()));assert!(receipt.ok,"{:?}",receipt.error);
    assert_eq!(branch.players[1].knowledge[0].source,newer);assert_eq!(branch.players[1].knowledge[0].interpreted_source,Some(older));
    // A newer valid assessment wins even when an older in-flight reflection also
    // creates an assertion; derived knowledge must not rewind the original copy.
    assert!(reflect_at(&mut w,2,newer,newer_cursor,None).ok);
    let latest_assessment=w.players[1].knowledge[0].interpretation.clone();
    assert!(reflect_at(&mut w,2,older,cursor,Some(derived_draft())).ok);
    assert_eq!(w.players[1].knowledge[0].interpretation,latest_assessment);
    assert_eq!(w.players[1].knowledge[0].interpreted_source,Some(newer));
    let receipt=reflect_at(&mut missing,2,older,cursor,Some(derived_draft()));assert!(receipt.ok,"{:?}",receipt.error);
    assert!(missing.players[1].knowledge.iter().all(|h|h.record.id!="garden-report"));
    let before=w.players[2].knowledge.len();
    assert!(!reflect(&mut w,3,older,Some(derived_draft())).ok);
    assert_eq!(w.players[2].knowledge.len(),before);
}
#[test]
fn human_and_ai_decisions_assess_and_derive_through_the_same_atomic_path() {
    for controller in [Controller::Human,Controller::Ai] {
        let mut w=world();w.participant_mode=false;w.players[0].controller=controller.clone();
        let source=w.players[0].knowledge[0].source;
        let decision=|draft|Decision{reason:"Assess personally held report and derive a conditional assertion".into(),actions:vec![Action::new(Skill::Wait)],policy:None,reflections:vec![Reflection{source,interpretation:"This is a conditional report, not a guaranteed result.".into(),caution_delta:2,trust_delta:0,belief:None,knowledge:Some(draft)}]};
        let before=serde_json::to_value(&w).unwrap();let events=serde_json::to_value(&w.events).unwrap();
        let mut invalid=derived_draft();invalid.confidence=101;
        assert!(w.submit(1,controller.clone(),decision(invalid),None).is_err());
        assert_eq!(serde_json::to_value(&w).unwrap(),before);assert_eq!(serde_json::to_value(&w.events).unwrap(),events);
        w.submit(1,controller,decision(derived_draft()),None).unwrap();
        assert_eq!(w.players[0].knowledge[0].interpreted_source,Some(source));assert_eq!(w.players[0].knowledge.len(),2);
    }
}
