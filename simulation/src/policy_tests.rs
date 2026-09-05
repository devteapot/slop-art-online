use super::*;
use crate::policy::{Comparison, Resource};
fn action(a: Action) -> Node {
    Node::Action { action: a }
}
fn guard(c: Condition, n: Node) -> Node {
    Node::Guard {
        condition: c,
        child: Box::new(n),
    }
}
fn sequence(children: Vec<Node>) -> Node {
    Node::Sequence { children }
}
fn priority(children: Vec<Node>) -> Node {
    Node::Priority { children }
}
fn policy(n: Node) -> Decision {
    Decision {
        reason: "deterministic policy fixture; not a model-quality proof".into(),
        actions: vec![],
        policy: Some(n),
        reflections: vec![],
    }
}
fn world() -> World {
    let mut scenario: Scenario =
        serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    scenario.max_ticks = 60;
    scenario.players.truncate(1);
    let p = &mut scenario.players[0];
    p.position = 0;
    p.food = 0;
    p.hunger = 10;
    p.energy = 40;
    p.beliefs.clear();
    scenario.sites = vec![Site {
        position: 1,
        food: 6,
        hazard: 5,
    }];
    World::new("reactive-test".into(), scenario).unwrap()
}
fn reactive() -> Node {
    priority(vec![
        guard(Condition::Danger { location: None }, action(Action::go(0))),
        guard(
            Condition::Not {
                condition: Box::new(Condition::Danger { location: Some(1) }),
            },
            sequence(vec![action(Action::go(3)), action(Action::say("arrived"))]),
        ),
        sequence(vec![
            Node::Reconsider {
                reason: "Reconsider the now dangerous route".into(),
            },
            action(Action {
                duration: 3,
                ..Action::new(Skill::Rest)
            }),
        ]),
    ])
}
fn install(w: &mut World, n: Node) -> u64 {
    w.request(0, "fixture install");
    let id = w.pending[0].id;
    w.model_result(
        id,
        &serde_json::to_string(&policy(n)).unwrap(),
        json!({"backend":"deterministic_fixture"}),
    )
    .unwrap();
    w.players[0].execution.as_ref().unwrap().decision
}
#[test]
fn installed_tree_reacts_to_new_danger_without_model_response_and_does_not_oscillate() {
    let mut w = world();
    let id = install(&mut w, reactive());
    let generation = w.players[0].generation;
    w.step();
    assert_eq!(w.players[0].position, 1);
    assert_eq!(w.players[0].health, 95);
    let pending = w.pending[0].id;
    assert_eq!(w.players[0].generation, generation);
    assert_eq!(w.players[0].execution.as_ref().unwrap().decision, id);
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "skill_result" && e.data["status"] == "interrupted"));
    w.step();
    assert_eq!(w.players[0].position, 0);
    for _ in 0..6 {
        w.step();
        assert_eq!(w.players[0].position, 0);
    }
    assert_eq!(w.players[0].health, 95);
    assert!(w.players[0].energy > 40);
    assert!(w.pending.iter().any(|p| p.id == pending));
    assert_eq!(w.players[0].execution.as_ref().unwrap().decision, id);
    assert!(!w
        .events
        .iter()
        .any(|e| e.data["controller"] == "authored_bootstrap"));
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "guard_evaluated" && e.data["result"] == true));
    assert_eq!(
        w.events.iter().filter(|e| e.kind == "model_result").count(),
        1
    );
}
#[test]
fn damage_during_reasoning_keeps_request_usable_and_preserves_newer_danger() {
    let mut w = world();
    w.request(0, "before damage");
    let request = w.pending[0].clone();
    let src = w.perceive(
        0,
        request.id,
        "prior_report",
        None,
        1,
        json!({"claim":"safe"}),
    );
    // Capture permitted source in the fixture's immutable supplied context.
    w.pending[0].context = w.context(0);
    let mut d = policy(reactive());
    d.reflections.push(Reflection {
        source: src,
        interpretation: "Old report said safe".into(),
        caution_delta: -3,
        trust_delta: 0,
        belief: Some(Belief {
            location: 1,
            danger: false,
            text: "old safe claim".into(),
        }),
    });
    w.players[0].position = 1;
    w.step();
    assert!(w.pending.iter().any(|p| p.id == request.id));
    w.model_result(request.id, &serde_json::to_string(&d).unwrap(), json!({}))
        .unwrap();
    assert!(w.players[0]
        .beliefs
        .iter()
        .any(|b| b.claim.location == 1 && b.claim.danger));
    assert!(w.events.iter().any(|e| e.kind == "reflection_skipped"));
    w.step();
    assert_eq!(w.players[0].position, 0);
}
#[test]
fn reactive_branch_preempts_running_skill_and_resets_abandoned_sequence() {
    let mut w = world();
    w.sites.clear();
    let n = priority(vec![
        guard(
            Condition::Resource {
                resource: Resource::Food,
                comparison: Comparison::AtLeast,
                value: 1,
            },
            action(Action::new(Skill::Eat)),
        ),
        sequence(vec![
            action(Action {
                duration: 3,
                ..Action::new(Skill::Rest)
            }),
            action(Action::say("rest finished")),
        ]),
    ]);
    install(&mut w, n);
    w.step();
    let first = w.players[0].execution.as_ref().unwrap().attempt.unwrap();
    w.players[0].food = 1;
    w.step();
    assert!(w.events.iter().any(|e| e.kind == "skill_result"
        && e.parents.contains(&first)
        && e.data["status"] == "interrupted"));
    assert_eq!(w.players[0].food, 0);
    w.step();
    w.step();
    assert!(!w.events.iter().any(|e| e.kind == "speech"));
    w.step();
    assert!(!w.events.iter().any(|e| e.kind == "speech"));
    w.step();
    assert_eq!(w.events.iter().filter(|e| e.kind == "speech").count(), 1);
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "branch_selected" && e.data["previous"].is_number()));
}
#[test]
fn running_policy_and_pending_context_survive_serialization_restart() {
    let mut w = world();
    w.sites.clear();
    install(
        &mut w,
        sequence(vec![
            action(Action::go(3)),
            action(Action {
                duration: 3,
                ..Action::new(Skill::Rest)
            }),
            action(Action::say("done")),
        ]),
    );
    w.step();
    assert!(w.players[0].execution.as_ref().unwrap().attempt.is_some());
    let mut restored: World = serde_json::from_str(&serde_json::to_string(&w).unwrap()).unwrap();
    for _ in 0..7 {
        w.events.clear();
        restored.events.clear();
        w.step();
        restored.step();
        assert_eq!(
            serde_json::to_value(&w).unwrap(),
            serde_json::to_value(&restored).unwrap()
        );
        assert_eq!(
            serde_json::to_value(&w.events).unwrap(),
            serde_json::to_value(&restored.events).unwrap()
        );
    }
}
#[test]
fn conditions_cannot_observe_remote_truth_and_latest_subjective_observation_wins() {
    let mut w = world();
    let food = Condition::FoodAt {
        location: 1,
        minimum: 1,
    };
    let danger = Condition::Danger { location: Some(1) };
    assert!(!food.evaluate(&w.players[0]).0);
    assert!(!danger.evaluate(&w.players[0]).0);
    w.sites[0].food = 99;
    w.sites[0].hazard = 99;
    assert!(!food.evaluate(&w.players[0]).0);
    assert!(!danger.evaluate(&w.players[0]).0);
    let cause = w.events[0].id;
    w.perceive(0, cause, "site", None, 1, json!({"food":3}));
    assert!(food.evaluate(&w.players[0]).0);
    w.perceive(0, cause, "site", None, 1, json!({"food":0}));
    assert!(!food.evaluate(&w.players[0]).0);
    assert!(!w.context(0).to_string().contains("hazard"));
}
#[test]
fn human_and_ai_policies_use_identical_skill_effects_and_death_cancels() {
    let mut human = world();
    human.sites[0].hazard = 0;
    let mut ai = human.clone();
    human.players[0].controller = Controller::Human;
    let d = policy(sequence(vec![
        action(Action::go(1)),
        action(Action::new(Skill::Gather)),
        action(Action::new(Skill::Eat)),
    ]));
    human.submit(1, Controller::Human, d.clone(), None).unwrap();
    ai.submit(1, Controller::Ai, d, None).unwrap();
    for _ in 0..3 {
        human.step();
        ai.step();
        assert_eq!(
            (
                human.players[0].position,
                human.players[0].energy,
                human.players[0].food,
                human.players[0].hunger
            ),
            (
                ai.players[0].position,
                ai.players[0].energy,
                ai.players[0].food,
                ai.players[0].hunger
            )
        );
    }
    let pending = ai.pending[0].id;
    ai.sites[0].hazard = 100;
    ai.step();
    assert_eq!(ai.players[0].health, 0);
    assert!(ai.pending.is_empty());
    assert!(ai
        .model_result(
            pending,
            &serde_json::to_string(&policy(reactive())).unwrap(),
            json!({})
        )
        .is_err());
    let attempts = ai
        .events
        .iter()
        .filter(|e| e.kind == "skill_attempt")
        .count();
    ai.step();
    assert_eq!(
        attempts,
        ai.events
            .iter()
            .filter(|e| e.kind == "skill_attempt")
            .count()
    );
    assert!(ai.events.iter().any(|e| e.kind == "model_cancelled"));
}
#[test]
fn policy_replacement_and_controller_change_reject_old_requests() {
    let mut w = world();
    install(&mut w, reactive());
    w.request(0, "pending revision");
    let old = w.pending[0].id;
    w.submit(
        1,
        Controller::Ai,
        policy(action(Action::new(Skill::Wait))),
        None,
    )
    .unwrap();
    assert!(w
        .model_result(
            old,
            &serde_json::to_string(&policy(reactive())).unwrap(),
            json!({})
        )
        .is_err());
    w.request(0, "new request");
    let old = w.pending[0].id;
    w.players[0].controller = Controller::Human;
    w.step();
    assert!(w.pending.is_empty());
    assert!(w
        .model_result(
            old,
            &serde_json::to_string(&policy(reactive())).unwrap(),
            json!({})
        )
        .is_err());
}
#[test]
fn invalid_unbounded_and_unknown_trees_are_rejected_without_replacement() {
    let mut w = world();
    let id = install(&mut w, reactive());
    let leaf = action(Action::new(Skill::Wait));
    let mut deep = leaf.clone();
    for _ in 0..10 {
        deep = sequence(vec![deep]);
    }
    let wide = sequence(vec![leaf.clone(); 9]);
    let huge = sequence(vec![sequence(vec![leaf.clone(); 8]); 8]);
    let bad = guard(
        Condition::Resource {
            resource: Resource::Energy,
            comparison: Comparison::Below,
            value: 101,
        },
        leaf.clone(),
    );
    let empty = sequence(vec![]);
    let wrong = action(Action {
        target: Some(2),
        ..Action::new(Skill::Wait)
    });
    for tree in [deep, wide, huge, bad, empty, wrong] {
        assert!(w.submit(1, Controller::Ai, policy(tree), None).is_err());
        assert_eq!(w.players[0].execution.as_ref().unwrap().decision, id);
    }
    assert!(
        serde_json::from_value::<Node>(json!({"kind":"omniscient_hazard","location":1})).is_err()
    );
    assert!(serde_json::from_value::<Node>(
        json!({"kind":"action","action":{"skill":"wait"},"hidden_world":true})
    )
    .is_err());
}
#[test]
fn failed_policy_never_reverts_to_authored_fallback_and_tick_cost_is_bounded() {
    let mut w = world();
    w.sites.clear();
    install(&mut w, action(Action::new(Skill::Gather)));
    for _ in 0..4 {
        w.step();
        assert!(w.players[0].execution.as_ref().unwrap().policy.is_some());
    }
    assert!(!w
        .events
        .iter()
        .any(|e| e.data["controller"] == "authored_bootstrap"));
    assert!(w
        .events
        .iter()
        .filter(|e| e.kind == "policy_tick")
        .all(|e| e.data["node_visits"].as_u64().unwrap() <= policy::TICK_BUDGET as u64));
    for tick in 1..=4 {
        assert!(
            w.events
                .iter()
                .filter(|e| e.kind == "skill_attempt" && e.tick == tick)
                .count()
                <= 1
        );
    }
}
#[test]
fn old_sequence_archive_deserializes_with_new_execution_defaults() {
    let mut w = world();
    w.sites.clear();
    w.submit(
        1,
        Controller::Ai,
        Decision {
            reason: "legacy".into(),
            actions: vec![Action::go(3)],
            policy: None,
            reflections: vec![],
        },
        None,
    )
    .unwrap();
    w.step();
    let mut old = serde_json::to_value(&w).unwrap();
    old["version"] = json!("m1-3");
    old["players"][0]["execution"]
        .as_object_mut()
        .unwrap()
        .remove("policy");
    old["players"][0]["execution"]
        .as_object_mut()
        .unwrap()
        .remove("state");
    let restored: World = serde_json::from_value(old).unwrap();
    assert_eq!(restored.version, "m1-3");
    assert_eq!(restored.players[0].execution.as_ref().unwrap().cursor, 0);
    assert!(restored.players[0]
        .execution
        .as_ref()
        .unwrap()
        .policy
        .is_none());
}

#[test]
fn transport_failure_is_not_mislabeled_as_bad_generated_decision() {
    let mut w = world();
    let installed = install(&mut w, reactive());
    w.request(0, "revision");
    let request = w.pending[0].id;
    let error = w
        .model_result(
            request,
            "",
            json!({"error":"provider HTTP 524 failure with non-JSON body"}),
        )
        .unwrap_err();
    assert!(error.contains("no proposal returned"));
    assert!(!error.contains("invalid model decision"));
    assert_eq!(w.players[0].execution.as_ref().unwrap().decision, installed);
}
