use serde_json::Value;
use simulation::{
    participant::{Command, Request, API_VERSION},
    Scenario, World,
};

fn world() -> World {
    let scenario: Scenario =
        serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    let mut world = World::new("delivery-parity".into(), scenario).unwrap();
    world.enable_participants();
    world
}

#[test]
fn immutable_delivery_matches_captured_status_and_survives_later_commands() {
    let mut world = world();
    let actor = world.players[0].id;
    let request = Request {
        api_version: API_VERSION.into(),
        request_id: "first".into(),
        control_epoch: world.participants[&actor].control_epoch,
        command: Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    };
    let before = world.participants[&actor].clone();
    let receipt = world.participant_apply(actor, request.clone()).unwrap();
    assert!(receipt.ok);
    assert!(!before.same_snapshot(&world.participants[&actor]));
    let captured = world.participants[&actor].evidence_leases[0].clone();
    let response = captured.response_json().unwrap();
    let status: Value =
        serde_json::from_str(&world.participant_status_json(actor).unwrap()).unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&response).unwrap(),
        status["read_observations"][0]["observation"]
    );
    let committed = world.participants[&actor].clone();
    assert_eq!(
        world
            .participant_apply(actor, request.clone())
            .unwrap()
            .event,
        receipt.event
    );
    assert!(
        committed.same_snapshot(&world.participants[&actor]),
        "idempotent replay must not dirty delivery"
    );
    let mut changed = request.clone();
    changed.command = Command::ReadObservation {
        after: u64::MAX,
        limit: 128,
    };
    assert!(world.participant_apply(actor, changed.clone()).is_err());
    assert!(committed.same_snapshot(&world.participants[&actor]));
    changed.request_id = "rejected".into();
    assert!(!world.participant_apply(actor, changed).unwrap().ok);
    assert!(!committed.same_snapshot(&world.participants[&actor]));
    assert_eq!(captured.response_json().unwrap(), response);
    world.timing.time_ms = captured.expires_ms;
    let at_expiry: Value =
        serde_json::from_str(&world.participant_status_json(actor).unwrap()).unwrap();
    assert_eq!(at_expiry["read_observations"].as_array().unwrap().len(), 1);
    world.timing.time_ms += 1;
    let expired: Value =
        serde_json::from_str(&world.participant_status_json(actor).unwrap()).unwrap();
    assert!(expired["read_observations"].as_array().unwrap().is_empty());
    assert_eq!(
        captured.response_json().unwrap(),
        response,
        "expiry changes access, never captured evidence"
    );
}

#[test]
fn idle_clock_does_not_dirty_unchanged_participant_rows() {
    let mut world = world();
    for player in &mut world.players {
        player.execution = None;
    }
    world.advance_ms(1);
    let before = world.participants.clone();
    world.advance_ms(1);
    for (&actor, state) in &world.participants {
        assert!(
            state.same_snapshot(&before[&actor]),
            "idle actor {actor} should not rewrite private state"
        );
    }
}
