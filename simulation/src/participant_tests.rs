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
