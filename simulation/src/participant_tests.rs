use super::*;
use participant::{Command, Request, API_VERSION};
fn world() -> World {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    s.sites.iter_mut().for_each(|s| s.hazard = 0);
    let mut w = World::new("sim-participant-test".into(), s).unwrap();
    w.enable_participants();
    w
}
fn send(w: &mut World, actor: u32, command: Command) -> participant::Receipt {
    let request = Request {
        api_version: API_VERSION.into(),
        request_id: format!("test-{}", w.next_event),
        control_epoch: w.participants[&actor].control_epoch,
        command,
    };
    w.participant_apply(actor, request).unwrap()
}
fn node(a: Action) -> Node {
    Node::Action { action: a }
}
fn install(w: &mut World, actor: u32, tree: Node) {
    let rev = w.players.iter().find(|p| p.id == actor).unwrap().generation;
    assert!(
        send(
            w,
            actor,
            Command::ReplaceTree {
                expected_revision: rev,
                reason: "test-authored fixture".into(),
                tree
            }
        )
        .ok
    );
}
#[test]
fn participant_runs_have_no_hidden_bootstrap_or_model_schedule() {
    let mut w = world();
    for _ in 0..5 {
        w.step();
    }
    assert!(w.pending.is_empty());
    assert!(w.players.iter().all(|p| p.execution.is_none()));
    assert!(w.model_result(1, "{}", json!({})).is_err());
    assert!(w
        .submit(
            1,
            Controller::Ai,
            Decision {
                reason: "bypass".into(),
                actions: vec![Action::new(Skill::Rest)],
                policy: None,
                reflections: vec![]
            },
            None
        )
        .is_err());
}
#[test]
fn inactive_patch_preserves_running_attempt_and_sequence_progress() {
    let mut w = world();
    install(
        &mut w,
        1,
        Node::Sequence {
            children: vec![node(Action::go(5)), node(Action::new(Skill::Rest))],
        },
    );
    w.step();
    let e = w.players[0].execution.clone().unwrap();
    let rev = w.players[0].generation;
    assert!(
        send(
            &mut w,
            1,
            Command::PatchSubtree {
                expected_revision: rev,
                reason: "change later action while thinking".into(),
                path: "root/1".into(),
                subtree: node(Action::new(Skill::Gather))
            }
        )
        .ok
    );
    assert_eq!(w.players[0].execution.as_ref().unwrap().attempt, e.attempt);
    for _ in 0..3 {
        w.step();
    }
    assert_eq!(w.players[0].position, 4);
    assert_eq!(w.players[0].execution.as_ref().unwrap().attempt, e.attempt);
}
#[test]
fn active_patch_interrupts_once_and_stale_invalid_patch_is_atomic() {
    let mut w = world();
    install(
        &mut w,
        1,
        Node::Sequence {
            children: vec![node(Action::go(5)), node(Action::new(Skill::Rest))],
        },
    );
    w.step();
    let rev = w.players[0].generation;
    assert!(
        send(
            &mut w,
            1,
            Command::PatchSubtree {
                expected_revision: rev,
                reason: "reverse direction".into(),
                path: "root/0".into(),
                subtree: node(Action::go(-2))
            }
        )
        .ok
    );
    assert!(w.players[0].execution.as_ref().unwrap().attempt.is_none());
    let prior = serde_json::to_value(&w.players[0].execution).unwrap();
    for path in ["root/99", "root/00"] {
        let rev = w.players[0].generation;
        assert!(
            !send(
                &mut w,
                1,
                Command::PatchSubtree {
                    expected_revision: rev,
                    reason: "bad path".into(),
                    path: path.into(),
                    subtree: node(Action::go(0))
                }
            )
            .ok
        );
    }
    assert!(
        !send(
            &mut w,
            1,
            Command::ReplaceTree {
                expected_revision: rev,
                reason: "stale".into(),
                tree: node(Action::go(5))
            }
        )
        .ok
    );
    assert_eq!(
        serde_json::to_value(&w.players[0].execution).unwrap(),
        prior
    );
    w.step();
    assert_eq!(w.players[0].position, 0);
}
#[test]
fn independent_speech_and_learning_leave_motion_intact() {
    let mut w = world();
    install(&mut w, 1, node(Action::go(5)));
    w.step();
    let e = w.players[0].execution.clone().unwrap();
    let rev = w.players[0].generation;
    assert!(
        send(
            &mut w,
            1,
            Command::Speak {
                text: "My chosen words".into(),
                expires_tick: 10
            }
        )
        .ok
    );
    let source = w.players[0]
        .memories
        .iter()
        .find(|p| p.kind == "site")
        .unwrap()
        .source;
    let cursor = w.participants[&1].cursor;
    assert!(
        send(
            &mut w,
            1,
            Command::Reflect {
                expected_revision: 0,
                observed_cursor: cursor,
                reflections: vec![Reflection {
                    source,
                    interpretation: "I choose to be more cautious".into(),
                    caution_delta: 2,
                    trust_delta: 0,
                    belief: None
                }],
                goal: Some("Find food for a companion".into())
            }
        )
        .ok
    );
    assert_eq!(w.players[0].generation, rev);
    assert_eq!(w.players[0].execution.as_ref().unwrap().attempt, e.attempt);
    w.step();
    assert_eq!(w.players[0].position, 2);
    assert!(w.players[1]
        .memories
        .iter()
        .any(|m| m.kind == "speech" && m.content["text"] == "My chosen words"));
    assert_eq!(w.players[0].execution.as_ref().unwrap().attempt, e.attempt);
}
#[test]
fn reflection_provenance_revision_and_duplicate_sources_are_enforced() {
    let mut w = world();
    let source = w.players[0]
        .memories
        .iter()
        .find(|p| p.kind == "site")
        .unwrap()
        .source;
    let r = Reflection {
        source,
        interpretation: "A possibly mistaken conclusion".into(),
        caution_delta: 1,
        trust_delta: 0,
        belief: Some(Belief {
            location: 0,
            danger: true,
            text: "I suspect danger here".into(),
        }),
    };
    let cursor = w.participants[&1].cursor;
    let make = |rev| Command::Reflect {
        expected_revision: rev,
        observed_cursor: cursor,
        reflections: vec![r.clone()],
        goal: None,
    };
    assert!(send(&mut w, 1, make(0)).ok);
    assert!(!send(&mut w, 1, make(0)).ok);
    assert!(!send(&mut w, 1, make(1)).ok);
    let c = w.players[0].caution;
    let bad = Reflection {
        source: 999999,
        ..r
    };
    let cursor = w.participants[&1].cursor;
    assert!(
        !send(
            &mut w,
            1,
            Command::Reflect {
                expected_revision: 1,
                observed_cursor: cursor,
                reflections: vec![bad],
                goal: None
            }
        )
        .ok
    );
    assert_eq!(w.players[0].caution, c);
    assert!(w.players[0]
        .beliefs
        .iter()
        .any(|b| b.claim.location == 0 && b.claim.danger));
}

#[test]
fn evidence_lease_survives_trace_churn_reload_but_not_expiry_or_control_change() {
    let mut w = world();
    let source = w.players[0].memories.iter().find(|p| p.kind == "site").unwrap().source;
    let cursor = w.participants[&1].cursor;
    assert!(!send(&mut w, 2, Command::PinObservation { observed_cursor: cursor, sources: vec![source] }).ok);
    assert!(send(&mut w, 1, Command::PinObservation { observed_cursor: cursor, sources: vec![source] }).ok);
    for _ in 0..300 { w.observe_site(0).unwrap(); }
    assert!(!w.participants[&1].experiences.iter().any(|e| e.source == source));
    let make = |revision| Command::Reflect { expected_revision: revision, observed_cursor: cursor,
        reflections: vec![Reflection { source, interpretation: "I can still interpret my earlier observation".into(),
            caution_delta: 1, trust_delta: 0, belief: None }], goal: None };
    let mut expired = w.clone();
    expired.timing.time_ms = participant::EVIDENCE_LEASE_MS + 1;
    assert!(!send(&mut expired, 1, make(0)).ok);
    let mut transferred = w.clone();
    transferred.change_control(1).unwrap();
    assert!(!send(&mut transferred, 1, make(0)).ok);
    let mut loaded: World = serde_json::from_str(&serde_json::to_string(&w).unwrap()).unwrap();
    assert!(send(&mut loaded, 1, make(0)).ok);
    assert!(!send(&mut loaded, 1, make(1)).ok);
}

#[test]
fn evidence_leases_bound_concurrent_reads_and_reject_forged_sources() {
    let mut w = world();
    for _ in 0..7 {
        w.observe_site(0).unwrap();
        let cursor = w.participants[&1].cursor;
        let source = w.players[0].site_observations.last().unwrap().source;
        assert!(send(&mut w, 1, Command::PinObservation { observed_cursor: cursor, sources: vec![source] }).ok);
    }
    assert_eq!(w.participants[&1].evidence_leases.len(), 4);
    let cursor = w.participants[&1].cursor;
    assert!(!send(&mut w, 1, Command::PinObservation { observed_cursor: cursor, sources: vec![u64::MAX] }).ok);
}

#[test]
fn latest_site_observation_survives_recent_memory_churn_and_updates_only_locally() {
    let mut w = world();
    let initial = w.players[0].site_observations.clone();
    for n in 0..40 { w.perceive(0, 0, "speech", Some(2), 0, json!({"text":format!("remark {n}")})).unwrap(); }
    assert!(w.players[0].memories.iter().all(|p| p.kind != "site"));
    assert_eq!(serde_json::to_value(&w.players[0].site_observations).unwrap(), serde_json::to_value(&initial).unwrap());
    let pos = w.players[0].position;
    let old_source = initial.iter().find(|p| p.location == pos).unwrap().source;
    w.observe_site(0).unwrap();
    assert!(w.players[0].site_observations.iter().find(|p| p.location == pos).unwrap().source > old_source);
    assert_eq!(w.players[0].site_observations.len(), initial.len());
}

#[test]
fn atomic_observation_captures_context_and_evidence_at_one_authority_revision() {
    let mut w = world();
    for _ in 0..300 { w.observe_site(0).unwrap(); }
    let cursor = w.participants[&1].cursor;
    assert!(send(&mut w, 1, Command::ReadObservation { after: 0, limit: 256 }).ok);
    let lease = w.participants[&1].evidence_leases.last().unwrap().clone();
    assert_eq!(lease.observed_cursor, cursor);
    assert_eq!(lease.experiences.len(), 128);
    assert_eq!(lease.observation["latest_cursor"], cursor);
    assert_eq!(lease.observation["context"]["player"]["food"], w.players[0].food);
    assert!(lease.observation.get("read_observations").is_none());
    let source = lease.experiences.iter().find(|e| e.kind == "perception" && e.data["kind"] == "site").unwrap().source;
    for _ in 0..300 { w.observe_site(0).unwrap(); }
    let motive = w.players[0].motive.clone();
    assert!(send(&mut w, 1, Command::Reflect { expected_revision: 0, observed_cursor: cursor,
        reflections: vec![Reflection { source, interpretation: "This is evidence from my captured read".into(),
            caution_delta: 0, trust_delta: 0, belief: None }], goal: Some("A revised near-term intention".into()) }).ok);
    assert_eq!(w.players[0].motive, motive);
    assert_eq!(w.players[0].current_goal.as_deref(), Some("A revised near-term intention"));
}

#[test]
fn entry_condition_persists_through_departure_reload_and_child_patch() {
    let mut w = world();
    let start = w.players[0].position;
    install(&mut w, 1, Node::When { condition: Condition::At { location: start },
        child: Box::new(node(Action::go(5))) });
    w.advance_ms(250);
    assert_eq!(w.players[0].position, start + 1);
    assert!(w.players[0].execution.as_ref().unwrap().state.entries.contains("root"));
    let mut w: World = serde_json::from_value(json!(w)).unwrap();
    let revision = w.players[0].generation;
    assert!(send(&mut w, 1, Command::PatchSubtree { expected_revision: revision, reason: "change destination while retaining entry".into(),
        path: "root/when".into(), subtree: node(Action::go(4)) }).ok);
    for _ in 0..4 { w.advance_ms(250); }
    assert_eq!(w.players[0].position, 4);
    assert!(w.players[0].execution.as_ref().unwrap().state.entries.is_empty());
}

#[test]
fn higher_priority_branch_suspends_and_resumes_an_entry_condition_commitment() {
    let mut w = world();
    let start = w.players[0].position;
    install(&mut w, 1, Node::Priority { children: vec![
        Node::Guard { condition: Condition::Resource { resource: policy::Resource::Energy, comparison: policy::Comparison::Below, value: 20 },
            child: Box::new(node(Action::new(Skill::Rest))) },
        Node::When { condition: Condition::At { location: start }, child: Box::new(node(Action::go(5))) }
    ] });
    w.advance_ms(250);
    assert_eq!(w.players[0].position, start + 1);
    w.players[0].energy = 0;
    w.wake(1);
    w.advance_ms(250);
    assert_eq!(w.players[0].position, start + 1);
    assert!(w.players[0].execution.as_ref().unwrap().state.entries.contains("root/1"));
    assert!(w.events.iter().any(|e| e.kind == "action_interrupted"));
    w.players[0].energy = 80;
    w.wake(1);
    for _ in 0..5 { w.advance_ms(250); }
    assert_eq!(w.players[0].position, 5);
    assert!(w.players[0].execution.as_ref().unwrap().state.entries.is_empty());
}

#[test]
fn activity_reports_net_resource_flow_without_exposing_other_actors() {
    let mut w = world();
    w.event(Some(1), "resource_change", vec![], json!({"location":0,"food_delta":-3}));
    w.event(Some(1), "resource_change", vec![], json!({"location":0,"food_delta":3}));
    w.event(Some(2), "resource_change", vec![], json!({"location":5,"food_delta":99}));
    let a = w.context(0)["recent_activity"].clone();
    assert_eq!(a["own_site_food_changes"], json!([{"location":0,"withdrawn":3,"deposited":3,"net_added":0}]));
    assert!(!a.to_string().contains("99"));
    w.timing.time_ms = 60_001;
    assert_eq!(w.context(0)["recent_activity"]["own_site_food_changes"], json!([]));
}

#[test]
fn activity_distinguishes_stationary_move_success_from_displacement() {
    let mut w = world();
    let position = w.players[0].position;
    install(&mut w, 1, node(Action::go(position)));
    w.advance_ms(250);
    assert_eq!(w.context(0)["recent_activity"]["completed_moves_without_displacement"], 1);
    install(&mut w, 1, node(Action::go(position+1)));
    w.advance_ms(250);
    assert_eq!(w.context(0)["recent_activity"]["position_changes"], 1);
    assert_eq!(w.context(0)["recent_activity"]["completed_moves_without_displacement"], 1);
}

#[test]
fn completed_urgent_action_does_not_erase_a_suspended_journey() {
    let mut w = world();
    let start = w.players[0].position;
    install(&mut w, 1, Node::Priority { children: vec![
        Node::Guard { condition: Condition::Resource { resource: policy::Resource::Hunger, comparison: policy::Comparison::AtLeast, value: 60 },
            child: Box::new(node(Action::new(Skill::Eat))) },
        Node::Sequence { children: vec![
            Node::When { condition: Condition::At { location: start }, child: Box::new(node(Action::go(4))) },
            Node::Reconsider { reason: "journey completed".into() }
        ] }
    ] });
    w.advance_ms(250);
    w.advance_ms(250);
    assert_eq!(w.players[0].position, start+2);
    w.players[0].hunger = 60;
    w.players[0].food = 1;
    w.wake(1);
    w.advance_ms(250);
    assert_eq!(w.players[0].food, 0);
    assert!(w.players[0].execution.as_ref().unwrap().state.entries.contains("root/1/0"));
    let mut w: World = serde_json::from_value(json!(w)).unwrap();
    for _ in 0..10 { w.advance_ms(250); }
    assert_eq!(w.players[0].position, 4, "resume the journey after the higher-priority meal completes");
}

#[test]
fn false_continuous_guard_cancels_a_suspended_entry_condition() {
    let mut w = world();
    let start = w.players[0].position;
    install(&mut w, 1, Node::Guard {
        condition: Condition::Resource { resource: policy::Resource::Fear, comparison: policy::Comparison::Below, value: 50 },
        child: Box::new(Node::When { condition: Condition::At { location: start }, child: Box::new(node(Action::go(4))) })
    });
    w.advance_ms(250);
    assert_eq!(w.players[0].position, start+1);
    w.players[0].fear = 80;
    w.wake(1);
    w.advance_ms(250);
    assert!(w.players[0].execution.as_ref().unwrap().state.entries.is_empty());
    w.players[0].fear = 0;
    w.wake(1);
    w.advance_ms(250);
    assert_eq!(w.players[0].position, start+1, "cancelled entry condition must be checked again");
}
#[test]
fn receipts_reconnect_epochs_and_bounded_trace_gaps() {
    let mut w = world();
    let r = Request {
        api_version: API_VERSION.into(),
        request_id: "stable-retry".into(),
        control_epoch: 0,
        command: Command::Speak {
            text: "Only once".into(),
            expires_tick: 10,
        },
    };
    let first = w.participant_apply(1, r.clone()).unwrap();
    assert_eq!(
        w.participant_apply(1, r.clone()).unwrap().event,
        first.event
    );
    assert_eq!(w.participants[&1].speech.len(), 1);
    w.change_control(1).unwrap();
    assert!(w.participants[&1].speech.is_empty());
    let mut stale = r;
    stale.request_id = "old-epoch".into();
    assert!(!w.participant_apply(1, stale).unwrap().ok);
    for _ in 0..300 {
        w.event(Some(1), "skill_progress", vec![], json!({"position":0}));
    }
    let v = w.participant_snapshot(1, 0, 8).unwrap();
    assert_eq!(v["experiences"].as_array().unwrap().len(), 8);
    assert_eq!(v["gap"], true);
    assert_eq!(w.participants[&1].experiences.len(), 256);
    assert!(!v.to_string().contains("hazard"));
}
#[test]
fn speech_delivery_uses_post_movement_location_and_death_cancels() {
    let mut w = world();
    install(&mut w, 1, node(Action::go(5)));
    w.players[1].position = 4;
    send(
        &mut w,
        1,
        Command::Speak {
            text: "moving".into(),
            expires_tick: 10,
        },
    );
    w.step();
    assert!(!w.players[1].memories.iter().any(|m| m.kind == "speech"));
    send(
        &mut w,
        1,
        Command::Speak {
            text: "never delivered".into(),
            expires_tick: 10,
        },
    );
    w.players[0].health = 0;
    w.step();
    assert!(w.participants[&1].speech.is_empty());
    assert!(!w
        .events
        .iter()
        .any(|e| e.kind == "speech" && e.data["text"] == "never delivered"));
}

#[test]
fn finite_human_actions_and_control_transfer_keep_fast_progress() {
    let mut w = world();
    w.participant_manual(
        3,
        Decision {
            reason: "human chosen move".into(),
            actions: vec![Action::go(2)],
            policy: None,
            reflections: vec![],
        },
    )
    .unwrap();
    w.step();
    let position = w.players[2].position;
    let attempt = w.players[2].execution.as_ref().unwrap().attempt;
    let revision = w.players[2].generation;
    w.change_control(3).unwrap();
    assert_eq!(w.players[2].generation, revision);
    assert_eq!(w.players[2].execution.as_ref().unwrap().attempt, attempt);
    for _ in 0..8 {
        w.step();
    }
    assert_eq!(w.players[2].position, 2);
    assert!(position != 2 || w.players[2].execution.is_none());
    assert!(w.players[2].execution.is_none());
}

#[test]
fn queued_and_tree_speech_share_one_utterance_slot() {
    let mut w = world();
    let mut action = Action::new(Skill::Speak);
    action.text = Some("chosen tree speech".into());
    install(&mut w, 1, node(action));
    assert!(
        send(
            &mut w,
            1,
            Command::Speak {
                text: "queued independent words".into(),
                expires_tick: 2
            }
        )
        .ok
    );
    for _ in 0..3 {
        w.step();
    }
    for tick in 1..=3 {
        assert_eq!(
            w.events
                .iter()
                .filter(|e| e.actor == Some(1) && e.kind == "speech" && e.tick == tick)
                .count(),
            1
        );
    }
    assert!(w.participants[&1].speech.is_empty());
    assert!(w
        .events
        .iter()
        .any(|e| e.actor == Some(1) && e.kind == "speech_cancelled"));
}
