use super::*;
use scripting::{Definition, DefinitionRef, Update};

fn world() -> World {
    let mut scenario: Scenario =
        serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    scenario.players.truncate(2);
    for p in &mut scenario.players {
        p.controller = Controller::Human;
        p.position = 0;
        p.health = 100;
        p.energy = 70;
        p.hunger = 10;
        p.food = 2;
        p.beliefs.clear();
    }
    scenario.sites = vec![Site {
        position: 0,
        food: 10,
        hazard: 0,
    }];
    World::new("script-test".into(), scenario).unwrap()
}
fn submit(w: &mut World, action: Action) {
    w.submit(
        w.players[0].id,
        Controller::Human,
        Decision {
            reason: "script integration fixture".into(),
            actions: vec![action],
            policy: None,
            reflections: vec![],
        },
        None,
    )
    .unwrap();
}
fn update(w: &World, definitions: Vec<Definition>) -> Update {
    Update {
        api_version: scripting::API_VERSION,
        expected_revision: w.scripts.revision,
        definitions,
    }
}
fn revise(w: &World, id: &str) -> Definition {
    let mut d = w.scripts.history[id][&w.scripts.active[id]].clone();
    d.revision += 1;
    d
}
fn custom(id: &str, step: &str) -> Definition {
    Definition {
        id: id.into(),
        revision: 1,
        source: format!("fn validate(c) {{ \"\" }} fn step(c) {{ {step} }}"),
        description: "integration fixture".into(),
        dependencies: vec![],
    }
}

#[test]
fn bundled_survival_scenario_runs_without_script_faults() {
    let scenario = serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    let mut w = World::new("whole-scenario".into(), scenario).unwrap();
    for tick in 1..=3 {
        w.step();
        assert_eq!(w.tick, tick, "{:?}", w.events.last());
    }
    assert!(!w
        .events
        .iter()
        .any(|e| e.kind == "script_error" || e.kind == "script_tick_failed"));
}

#[test]
fn active_laws_change_but_running_skill_revision_remains_pinned_across_reload() {
    let mut w = world();
    submit(&mut w, Action::go(8));
    w.step();
    assert_eq!((w.players[0].position, w.players[0].energy), (1, 69));
    let mut law = revise(&w, "law");
    law.source = law.source.replace("\"move\" => 1", "\"move\" => 3");
    let mut movement = revise(&w, "move");
    movement.source = movement.source.replace("position+=1", "position+=2");
    w.stage_scripts_by_operator(update(&w, vec![law, movement]))
        .unwrap();
    assert_eq!(w.scripts.revision, 1);
    let mut restored: World = serde_json::from_value(json!(w)).unwrap();
    restored.step();
    assert_eq!(
        (restored.players[0].position, restored.players[0].energy),
        (2, 66)
    );
    assert_eq!(restored.scripts.active["move"], 2);
    assert_eq!(
        restored.players[0]
            .execution
            .as_ref()
            .unwrap()
            .script
            .as_ref()
            .unwrap()
            .definition
            .revision,
        1
    );
    submit(&mut restored, Action::go(8));
    restored.step();
    assert_eq!(
        (restored.players[0].position, restored.players[0].energy),
        (4, 63)
    );
    assert!(restored
        .events
        .iter()
        .any(|e| e.kind == "script_update_activated"));
    assert!(restored.scripts.history["move"].contains_key(&1));
}

#[test]
fn composed_skill_has_dynamic_identity_and_persistent_continuation() {
    let mut w = world();
    let mut stride = custom(
        "stride",
        r#"
        let first=move::step(c);
        if first.status == "failure" { return first; }
        c.actor.position=first.effects[0].fields.position;
        c.actor.energy=first.effects[0].fields.energy;
        let second=move::step(c);
        if second.status == "failure" { return second; }
        let effects=first.effects;
        for effect in second.effects { effects.push(effect); }
        second.effects=effects;
        second.state=#{steps:if c.state == () { 2 } else { c.state.steps+2 }};
        second
    "#,
    );
    stride.dependencies = vec![DefinitionRef {
        id: "move".into(),
        revision: 1,
    }];
    w.stage_scripts_by_operator(update(&w, vec![stride]))
        .unwrap();
    w.step();
    let mut action = Action::go(8);
    action.skill = Skill::Script("stride".into());
    submit(&mut w, action);
    w.step();
    assert_eq!((w.players[0].position, w.players[0].energy), (2, 68));
    let mut w: World = serde_json::from_value(json!(w)).unwrap();
    w.step();
    assert_eq!((w.players[0].position, w.players[0].energy), (4, 66));
    assert_eq!(
        w.players[0]
            .execution
            .as_ref()
            .unwrap()
            .script
            .as_ref()
            .unwrap()
            .state["steps"],
        4
    );
    assert!(w.context(0)["skill_definitions"]
        .as_array()
        .unwrap()
        .iter()
        .any(|d| d["id"] == "stride"));
}

#[test]
fn current_law_revalidates_running_action_before_effects() {
    let mut w = world();
    submit(&mut w, Action::go(5));
    w.step();
    let mut law = revise(&w, "law");
    law.source = law.source.replace(
        "let a = c.action;",
        "return \"movement prohibited by new law\"; let a = c.action;",
    );
    w.stage_scripts_by_operator(update(&w, vec![law])).unwrap();
    w.step();
    assert_eq!((w.players[0].position, w.players[0].energy), (1, 69));
    assert!(w.players[0].execution.is_none());
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "skill_result" && e.data["reason"] == "movement prohibited by new law"));
}

#[test]
fn invalid_effects_and_runtime_budgets_never_commit_partial_actions() {
    for (name, source) in [
        (
            "bad_effect",
            r#"law::done([#{kind:"actor",fields:#{energy:99}},#{kind:"actor",fields:#{other_actor:5}}])"#,
        ),
        ("endless", "loop {} law::done([])"),
        ("host_access", "read_file(\"unavailable\"); law::done([])"),
        (
            "hidden_access",
            "let secret=c.world.players[1].beliefs; law::done([])",
        ),
        (
            "throwing",
            r#"let effects=[#{kind:"actor",fields:#{energy:99}}]; throw "failed"; law::done(effects)"#,
        ),
    ] {
        let mut w = world();
        w.stage_scripts_by_operator(update(&w, vec![custom(name, source)]))
            .unwrap();
        w.step();
        submit(&mut w, Action::new(Skill::Script(name.into())));
        w.step();
        assert_eq!(w.players[0].energy, 70, "{name}");
        assert!(
            w.events
                .iter()
                .any(|e| e.kind == "script_error" && e.data["effects_committed"] == false),
            "{name}"
        );
    }
}

#[test]
fn failed_law_activation_rolls_back_whole_tick_and_can_be_corrected() {
    let mut w = world();
    submit(&mut w, Action::go(4));
    let before = json!(w.players);
    let mut law = revise(&w, "law");
    law.source = law.source.replace(
        "fn metabolism(p) {",
        "fn metabolism(p) { if p.id == 2 { throw \"broken law\"; }",
    );
    w.stage_scripts_by_operator(update(&w, vec![law])).unwrap();
    w.step();
    assert_eq!(w.tick, 0);
    assert_eq!(json!(w.players), before);
    assert_eq!(w.scripts.active["law"], 1);
    assert!(w.scripts.pending.is_none());
    assert!(w.events.iter().any(|e| e.kind == "script_tick_failed"));
    w.step();
    assert_eq!(w.players[0].position, 1);
}

#[test]
fn update_authorization_uses_old_law_and_registry_rejects_stale_or_cyclic_changes() {
    let mut w = world();
    let a = custom("cycle_a", "law::done([])");
    let mut b = custom("cycle_b", "law::done([])");
    b.dependencies = vec![DefinitionRef {
        id: "cycle_a".into(),
        revision: 1,
    }];
    let mut a = a;
    a.dependencies = vec![DefinitionRef {
        id: "cycle_b".into(),
        revision: 1,
    }];
    let before = json!(w.scripts);
    assert!(w.stage_scripts_by_operator(update(&w, vec![a, b])).is_err());
    assert_eq!(json!(w.scripts), before);
    let mut denied = revise(&w, "law");
    denied.source = denied.source.replace(
        "fn authorize_update(c) { c.operator }",
        "fn authorize_update(c) { false }",
    );
    let accepted = update(&w, vec![denied]);
    w.stage_scripts_by_operator(accepted.clone()).unwrap();
    assert!(w.stage_scripts_by_operator(accepted).is_err());
    w.step();
    let mut enabled = revise(&w, "law");
    enabled.source = enabled.source.replace(
        "fn authorize_update(c) { false }",
        "fn authorize_update(c) { true }",
    );
    assert!(w
        .stage_scripts_by_operator(update(&w, vec![enabled]))
        .unwrap_err()
        .contains("denies"));
}

#[test]
fn scripts_do_not_replace_authenticated_participant_operations() {
    let mut w = world();
    w.enable_participants();
    let request = json!({"api_version":participant::API_VERSION,"request_id":"no-script-install","control_epoch":0,
        "command":{"op":"stage_scripts","definitions":[]}});
    assert!(serde_json::from_value::<participant::Request>(request).is_err());
    assert!(w.context(0).get("history").is_none());
    assert!(w.context(0).to_string().find("fn on_damage").is_none());
}

#[test]
fn queued_dialogue_uses_revised_speech_and_preserves_independent_motion() {
    let mut w = world();
    w.enable_participants();
    let actor = w.players[0].id;
    w.participant_manual(
        actor,
        Decision {
            reason: "walk while talking".into(),
            actions: vec![Action::go(5)],
            policy: None,
            reflections: vec![],
        },
    )
    .unwrap();
    let receipt = w
        .participant_apply(
            actor,
            participant::Request {
                api_version: participant::API_VERSION.into(),
                request_id: "scripted-dialogue".into(),
                control_epoch: w.participants[&actor].control_epoch,
                command: participant::Command::Speak {
                    text: "original words".into(),
                    expires_tick: 10,
                },
            },
        )
        .unwrap();
    assert!(receipt.ok);
    let mut speech = revise(&w, "speak");
    speech.source = speech.source.replace(
        "text:c.action.text",
        "text:c.action.text + \" under new rules\"",
    );
    w.stage_scripts_by_operator(update(&w, vec![speech]))
        .unwrap();
    w.step();
    assert_eq!(w.players[0].position, 1);
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "speech" && e.data["text"] == "original words under new rules"));
    w.step();
    assert_eq!(w.players[0].position, 2);
    assert!(w.participants[&actor].speech.is_empty());
}

#[test]
fn condition_limits_follow_active_laws() {
    let mut w = world();
    let policy: Node=serde_json::from_value(json!({"kind":"guard","condition":{"kind":"at","location":11},"child":{"kind":"action","action":{"skill":"wait"}}})).unwrap();
    assert!(policy.validate_with_laws(&w.scripts).is_err());
    let mut law = revise(&w, "law");
    law.source = law.source.replace("c.location > 10", "c.location > 20");
    w.stage_scripts_by_operator(update(&w, vec![law])).unwrap();
    w.step();
    assert!(policy.validate_with_laws(&w.scripts).is_ok());
}
