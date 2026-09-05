use super::*;

fn world() -> World {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/living-clearing.json")).unwrap();
    s.players.truncate(1);
    s.players[0].controller = Controller::Human;
    s.players[0].hunger = 10;
    s.players[0].energy = 10;
    World::new("sim-timing-test".into(), s).unwrap()
}
fn act(w: &mut World, action: Action) {
    w.submit(
        1,
        Controller::Human,
        Decision {
            reason: "timing experiment".into(),
            actions: vec![action],
            policy: None,
            reflections: vec![],
        },
        None,
    )
    .unwrap();
}
fn advance(w: &mut World, duration: u64, quantum: u64) {
    for _ in 0..duration / quantum {
        w.advance_ms(quantum);
    }
    assert!(!w
        .events
        .iter()
        .any(|e| matches!(e.kind.as_str(), "script_error" | "script_tick_failed")));
}

#[test]
fn movement_and_rest_use_elapsed_time_across_update_rates_and_reload() {
    for quantum in [50, 100] {
        let mut w = world();
        act(&mut w, Action::go(8));
        w.advance_ms(quantum);
        assert_eq!(w.players[0].position, 1, "first input acts at next update");
        advance(&mut w, 1000 - quantum, quantum);
        assert_eq!(w.players[0].position, 5);
        assert_eq!(w.players[0].energy, 5);
        let mut restored: World =
            serde_json::from_str(&serde_json::to_string(&w).unwrap()).unwrap();
        advance(&mut restored, 1000, quantum);
        assert_eq!(restored.players[0].position, 8);
        assert_eq!(restored.players[0].energy, 2);
        // A separate rest starts after the movement cooldown has elapsed.
        let mut rest = Action::new(Skill::Rest);
        rest.duration = 3;
        act(&mut restored, rest);
        advance(&mut restored, 7500, quantum);
        assert_eq!(restored.players[0].energy, 38);
        assert!(restored.players[0].execution.is_none());
        act(&mut restored, Action::go(9));
        restored.advance_ms(quantum);
        assert_eq!(
            restored.players[0].position, 9,
            "completed rest must not impose another rest interval"
        );
    }
}

#[test]
fn needs_hazards_and_legacy_expiry_units_do_not_accelerate_at_twenty_hz() {
    for quantum in [50, 100, 125] {
        let mut w = world();
        w.sites.iter_mut().find(|s| s.position == 0).unwrap().hazard = 3;
        advance(&mut w, 25_000, quantum);
        assert_eq!(w.timing.time_ms, 25_000);
        assert_eq!(w.timing.updates, 25_000 / quantum);
        assert_eq!(w.tick, 10);
        assert_eq!(w.players[0].hunger, 30);
        assert_eq!(w.players[0].health, 70);
    }
}

#[test]
fn cancelling_a_continuation_is_responsive_but_does_not_erase_paid_cooldowns() {
    let mut w = world();
    let mut rest = Action::new(Skill::Rest);
    rest.duration = 5;
    act(&mut w, rest);
    advance(&mut w, 200, 50);
    assert_eq!(w.players[0].energy, 10);
    act(&mut w, Action::go(3));
    w.advance_ms(50);
    assert_eq!(
        w.players[0].position, 1,
        "interrupting rest must not wait for its next energy pulse"
    );
    act(&mut w, Action::go(-3));
    w.advance_ms(50);
    assert_eq!(
        w.players[0].position, 1,
        "replacing movement must not bypass its cooldown"
    );
    advance(&mut w, 150, 50);
    assert_eq!(w.players[0].position, 0);
}

#[test]
fn rule_update_activates_before_first_legacy_tick_and_rejects_outage_jump() {
    let mut w = world();
    let mut law = w.scripts.history["law"][&1].clone();
    law.revision = 2;
    law.source = law.source.replace("needs_ms:2500", "needs_ms:1000");
    w.stage_scripts_by_operator(scripting::Update {
        api_version: scripting::API_VERSION,
        expected_revision: 1,
        definitions: vec![law],
    })
    .unwrap();
    w.advance_ms(50);
    assert_eq!(w.tick, 0);
    assert_eq!(w.scripts.revision, 2);
    advance(&mut w, 950, 50);
    assert_eq!(w.players[0].hunger, 12);
    w.advance_ms(60_001);
    assert_eq!(w.timing.time_ms, 1000);
    assert_eq!(w.events.last().unwrap().kind, "script_tick_failed");
}
