use super::*;
fn player(id: u32, controller: Controller, position: i32) -> Player {
    Player {
        id,
        name: format!("P{id}"),
        controller,
        motive: "survive to reunite with companions".into(),
        role: "forager".into(),
        position,
        health: 100,
        hunger: 40,
        energy: 70,
        food: 0,
        caution: 50,
        empathy: 40,
        introspection: 70,
        fear: 0,
        beliefs: vec![],
        relationships: BTreeMap::new(),
        memories: vec![],
        execution: None,
        generation: 0,
        failures: 0,
        last_reflection: 0,
        last_cause: None,
    }
}
fn world() -> World {
    World::new(
        "test".into(),
        Scenario {
            arenas: vec![],
            map: None,
            name: "test".into(),
            seed: 42,
            max_ticks: 40,
            players: vec![
                player(1, Controller::Human, 0),
                player(2, Controller::Human, 0),
                player(3, Controller::Human, 8),
            ],
            sites: vec![Site {
                position: 2,
                food: 4,
                hazard: 0,
            }],
        },
    )
    .unwrap()
}
fn decision(actions: Vec<Action>) -> Decision {
    Decision {
        reason: "test intention".into(),
        actions,
        policy: None,
        reflections: vec![],
    }
}
#[test]
fn sequence_waits_for_actual_completion_and_runs_each_skill() {
    let mut w = world();
    w.submit(
        1,
        Controller::Human,
        decision(vec![
            Action::go(2),
            Action::new(Skill::Gather),
            Action::new(Skill::Eat),
        ]),
        None,
    )
    .unwrap();
    w.step();
    assert_eq!(w.players[0].position, 1);
    assert_eq!(w.players[0].food, 0);
    w.step();
    assert_eq!(w.players[0].position, 2);
    assert_eq!(w.players[0].food, 0);
    w.step();
    assert_eq!(w.players[0].food, 1);
    w.step();
    assert_eq!(w.players[0].food, 0);
    assert!(w.players[0].hunger < 25);
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.actor == Some(1)
                && e.kind == "skill_result"
                && e.data["status"] == "completed")
            .count(),
        3
    );
}
#[test]
fn failed_precondition_stops_later_effects() {
    let mut w = world();
    w.submit(
        1,
        Controller::Human,
        decision(vec![
            Action::new(Skill::Gather),
            Action::say("should not happen"),
        ]),
        None,
    )
    .unwrap();
    w.step();
    w.step();
    assert!(w.players[0].execution.is_none());
    assert!(!w.events.iter().any(|e| e.kind == "speech"));
    assert!(w.events.iter().any(|e| e.data["status"] == "failed"));
}
#[test]
fn controllers_share_requirements_and_effects() {
    let mut a = world();
    let mut b = world();
    b.players[0].controller = Controller::Ai;
    let d = decision(vec![
        Action::go(2),
        Action::new(Skill::Gather),
        Action::new(Skill::Eat),
    ]);
    a.submit(1, Controller::Human, d.clone(), None).unwrap();
    b.submit(1, Controller::Ai, d, None).unwrap();
    for _ in 0..4 {
        a.step();
        b.step();
    }
    assert_eq!(
        (a.players[0].food, a.players[0].energy, a.players[0].hunger),
        (b.players[0].food, b.players[0].energy, b.players[0].hunger)
    );
    assert!(a
        .submit(
            1,
            Controller::Ai,
            decision(vec![Action::new(Skill::Eat)]),
            None
        )
        .is_err());
}
#[test]
fn interruption_has_distinct_result_and_permanent_death_keeps_history() {
    let mut w = world();
    w.players[0].health = 10;
    w.sites.push(Site {
        position: 0,
        food: 0,
        hazard: 20,
    });
    w.submit(
        1,
        Controller::Human,
        decision(vec![
            Action {
                duration: 5,
                ..Action::new(Skill::Rest)
            },
            Action::say("after death"),
        ]),
        None,
    )
    .unwrap();
    w.step();
    assert_eq!(w.players[0].health, 0);
    let n = w.events.len();
    w.step();
    assert!(w.events.len() >= n);
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "skill_result" && e.data["status"] == "interrupted"));
    assert!(w
        .submit(
            1,
            Controller::Human,
            decision(vec![Action::new(Skill::Rest)]),
            None
        )
        .is_err());
    assert!(w.players[2].memories.iter().all(|m| m.kind != "death"));
    assert!(w.players[1].memories.iter().any(|m| m.kind == "death"));
}
#[test]
fn free_speech_is_perceived_not_automatically_believed_or_world_truth() {
    let mut w = world();
    let text = "The pear-shaped moon owes me a breakfast. That clearing is perfectly safe!";
    w.submit(
        1,
        Controller::Human,
        decision(vec![Action::say(text)]),
        None,
    )
    .unwrap();
    w.step();
    assert!(w.players[1]
        .memories
        .iter()
        .any(|m| m.content["text"] == text));
    assert!(w.players[1].beliefs.is_empty());
    assert!(w.players[2].memories.iter().all(|m| m.kind != "speech"));
    assert_eq!(w.sites[0].food, 4);
}
#[test]
fn model_interpretation_changes_identity_and_later_context() {
    let mut w = world();
    w.players[1].controller = Controller::Ai;
    w.submit(
        1,
        Controller::Human,
        decision(vec![Action::say(
            "I was hurt at our camp. Please be careful.",
        )]),
        None,
    )
    .unwrap();
    w.step();
    let source = w.players[1]
        .memories
        .iter()
        .find(|m| m.kind == "speech")
        .unwrap()
        .source;
    let request = w.pending.iter().find(|p| p.actor == 2).unwrap().id;
    let mut d = decision(vec![Action::go(1)]);
    d.reflections.push(Reflection {
        source,
        interpretation: "I trust this warning, and should take more care".into(),
        caution_delta: 8,
        trust_delta: 4,
        belief: Some(Belief {
            location: 0,
            danger: true,
            text: "reported danger".into(),
        }),
    });
    w.model_result(
        request,
        &serde_json::to_string(&d).unwrap(),
        json!({"backend":"fixture"}),
    )
    .unwrap();
    assert_eq!(w.players[1].caution, 58);
    assert_eq!(w.players[1].relationships[&1], 4);
    assert_eq!(w.context(1)["player"]["personality"]["caution"], 58);
    w.step();
    assert_eq!(w.players[1].position, 1);
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "identity_change" && e.parents.contains(&source)));
}
#[test]
fn observer_truth_is_excluded_from_model_context() {
    let mut w = world();
    w.sites.push(Site {
        position: 9,
        food: 99,
        hazard: 77,
    });
    w.players[2].motive = "SECRET-MOTIVE".into();
    let text = w.context(0).to_string();
    assert!(!text.contains("SECRET-MOTIVE"));
    assert!(!text.contains("hazard"));
    assert!(!text.contains("99"));
    assert!(!text.contains("77"));
}
#[test]
fn stale_invalid_and_duplicate_model_outputs_are_evidence_not_effects() {
    let mut w = world();
    w.players[0].controller = Controller::Ai;
    w.request(0, "test");
    let id = w.pending[0].id;
    w.players[0].generation += 1;
    assert!(w
        .model_result(
            id,
            &serde_json::to_string(&decision(vec![Action::say("stale")])).unwrap(),
            json!({})
        )
        .is_err());
    assert!(w.model_result(id, "{}", json!({})).is_err());
    assert!(w.players[0].execution.is_none());
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.kind == "model_rejected")
            .count(),
        2
    );
}
#[test]
fn false_source_cannot_write_subjective_state() {
    let mut w = world();
    let mut d = decision(vec![Action::new(Skill::Wait)]);
    d.reflections.push(Reflection {
        source: 999,
        interpretation: "invented evidence".into(),
        caution_delta: 10,
        trust_delta: 0,
        belief: None,
    });
    assert!(w.submit(1, Controller::Human, d, None).is_err());
    assert_eq!(w.players[0].caution, 50);
}
#[test]
fn introspection_is_individual_and_does_not_require_dramatic_event() {
    let mut w = world();
    w.players[0].controller = Controller::Ai;
    w.players[1].controller = Controller::Ai;
    w.players[0].introspection = 100;
    w.players[1].introspection = 0;
    w.players[0].failures = 1;
    w.players[1].failures = 1;
    let mut counts = [0, 0];
    for _ in 0..14 {
        w.step();
        let requests = w.pending.clone();
        for r in requests {
            if r.actor < 3 {
                counts[(r.actor - 1) as usize] += 1;
            }
            let _ = w.model_result(r.id, "broken", json!({"error":"fixture failure"}));
        }
    }
    assert!(counts[0] > counts[1]);
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "model_request"
            && e.data["trigger"] == "lack of progress / introspection"));
}
#[test]
fn experience_changes_individuals_but_bootstrap_does_not_invent_survival_policy() {
    let mut w = world();
    w.players[0].controller = Controller::Ai;
    w.players[1].controller = Controller::Ai;
    w.players[0].caution = 60;
    w.players[0].introspection = 100;
    w.players[1].caution = 5;
    w.players[1].introspection = 0;
    w.players[0].hunger = 20;
    w.players[1].hunger = 20;
    w.sites.push(Site {
        position: 0,
        food: 10,
        hazard: 5,
    });
    w.step();
    assert_eq!(w.players[0].caution, 65);
    assert_eq!(w.players[1].caution, 6);
    w.step();
    assert_eq!(w.players[0].position, 0);
    assert_eq!(w.players[1].position, 0);
    assert!(w
        .events
        .iter()
        .filter(|e| e.kind == "decision")
        .all(|e| e.data["controller"] == "authored_bootstrap"));
}
#[test]
fn independent_worlds_and_snapshot_restart_preserve_execution() {
    let mut a = world();
    let b = world();
    a.submit(1, Controller::Human, decision(vec![Action::go(2)]), None)
        .unwrap();
    a.step();
    let mut restored: World = serde_json::from_str(&serde_json::to_string(&a).unwrap()).unwrap();
    a.step();
    restored.step();
    assert_eq!(
        serde_json::to_value(&a).unwrap(),
        serde_json::to_value(&restored).unwrap()
    );
    assert_eq!(b.tick, 0);
    assert_eq!(b.players[0].position, 0);
}

#[test]
fn starving_player_can_execute_eat_before_damage_and_does_not_blame_location() {
    let mut w = world();
    w.players[0].hunger = 100;
    w.players[0].food = 1;
    w.submit(
        1,
        Controller::Human,
        decision(vec![Action::new(Skill::Eat)]),
        None,
    )
    .unwrap();
    w.step();
    assert_eq!(w.players[0].health, 100);
    assert_eq!(w.players[0].hunger, 65);
    w.players[0].hunger = 100;
    w.step();
    assert_eq!(w.players[0].health, 92);
    assert!(w.players[0].beliefs.is_empty());
}

#[test]
fn authored_knowledge_has_subjective_provenance_and_can_be_reconsidered() {
    let mut s = world().initial;
    s.players[0].controller = Controller::Ai;
    s.players[0].beliefs.push(Known {
        claim: Belief {
            location: 2,
            danger: false,
            text: "A traveller reported food".into(),
        },
        source: 0,
        confidence: 50,
    });
    let mut w = World::new("test".into(), s).unwrap();
    let source = w.players[0].beliefs[0].source;
    assert_ne!(source, 1);
    w.request(0, "reconsider report");
    let request = w.pending[0].id;
    let mut d = decision(vec![Action::go(2)]);
    d.reflections.push(Reflection {
        source,
        interpretation: "The report is uncertain but worth investigating".into(),
        caution_delta: 2,
        trust_delta: 0,
        belief: None,
    });
    // Working request retains its supplied perceptions even if short-term memory forgets.
    w.players[0].memories.clear();
    w.model_result(
        request,
        &serde_json::to_string(&d).unwrap(),
        json!({"backend":"fixture"}),
    )
    .unwrap();
    assert_eq!(w.players[0].caution, 52);
}
