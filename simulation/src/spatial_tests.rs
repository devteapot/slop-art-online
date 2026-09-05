use super::*;
use participant::{Command, Request, API_VERSION};

fn world() -> World {
    let s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/woodland-pathfinding.json")).unwrap();
    let mut w = World::new("sim-grid-test".into(), s).unwrap();
    w.enable_participants();
    w
}
fn install(w: &mut World, tree: Node) -> participant::Receipt {
    w.participant_apply(
        1,
        Request {
            api_version: API_VERSION.into(),
            request_id: format!("grid-{}", w.next_event),
            control_epoch: w.participants[&1].control_epoch,
            command: Command::ReplaceTree {
                expected_revision: w.players[0].generation,
                reason: "explicit spatial contract fixture".into(),
                tree,
            },
        },
    )
    .unwrap()
}
fn movement(goal: i32) -> Node {
    serde_json::from_value(
        json!({"kind":"guard","condition":{"kind":"not","condition":{"kind":"at","location":goal}},
        "child":{"kind":"action","action":{"skill":"move","destination":goal}}}),
    )
    .unwrap()
}
fn advance(w: &mut World, ms: u64) {
    for _ in 0..ms / 50 {
        w.advance_ms(50);
    }
    assert!(!w
        .events
        .iter()
        .any(|e| matches!(e.kind.as_str(), "script_error" | "script_tick_failed")));
}

#[test]
fn participant_movement_follows_shortest_route_and_survives_reload() {
    let mut w = world();
    let grid = w.initial.map.clone().unwrap();
    let start = w.players[0].position;
    let expected = grid.route(start, 92).unwrap();
    assert!(expected.len() > grid.distance(start, 92) as usize);
    assert!(install(&mut w, movement(92)).ok);
    let energy = w.players[0].energy;
    advance(&mut w, 500);
    assert!(w.players[0].position != start && w.players[0].position != 92);
    let first: Vec<_> = w
        .events
        .iter()
        .filter(|e| e.actor == Some(1) && e.kind == "skill_progress")
        .filter_map(|e| e.data["position"].as_i64())
        .collect();
    w = serde_json::from_str(&serde_json::to_string(&w).unwrap()).unwrap();
    advance(&mut w, expected.len() as u64 * 250);
    assert_eq!(w.players[0].position, 92);
    assert_eq!(w.players[0].energy, energy - expected.len() as i32);
    // Route evidence and final position together describe every committed cell.
    let mut actual = first;
    actual.extend(
        w.events
            .iter()
            .filter(|e| e.actor == Some(1) && e.kind == "skill_progress")
            .filter_map(|e| e.data["position"].as_i64()),
    );
    actual.push(92);
    assert_eq!(
        actual,
        expected.iter().map(|&p| i64::from(p)).collect::<Vec<_>>()
    );
}

#[test]
fn no_route_and_exhaustion_have_no_movement_effects_and_invalid_targets_are_rejected() {
    let mut w = world();
    let before = w.players[0].position;
    assert!(
        !install(&mut w, movement(8)).ok,
        "wall cannot be a walking destination"
    );
    assert!(!install(&mut w, movement(384)).ok, "out of bounds");
    // Enclose the destination in the surveyed test terrain.
    w.initial
        .map
        .as_mut()
        .unwrap()
        .blocked
        .extend([68, 91, 93, 116]);
    assert!(install(&mut w, movement(92)).ok);
    advance(&mut w, 50);
    assert_eq!(w.players[0].position, before);
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "skill_result" && e.data["reason"] == "no route to destination"));
    let mut w = world();
    w.players[0].energy = 0;
    assert!(install(&mut w, movement(92)).ok);
    advance(&mut w, 50);
    assert_eq!(w.players[0].position, before);
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "skill_result" && e.data["reason"] == "exhausted"));
}

#[test]
fn emergency_preempts_route_and_visibility_uses_geometry_not_cell_id_difference() {
    let mut w = world();
    let tree=serde_json::from_value(json!({"kind":"priority","children":[
        {"kind":"guard","condition":{"kind":"resource","resource":"health","comparison":"below","value":90},
         "child":{"kind":"action","action":{"skill":"wait"}}},movement(92)]})).unwrap();
    assert!(install(&mut w, tree).ok);
    advance(&mut w, 500);
    let pos = w.players[0].position;
    let cause = w.event(Some(1), "test_injury", vec![], json!({}));
    w.damage(0, 15, None, cause, "attack").unwrap();
    advance(&mut w, 1000);
    assert_eq!(w.players[0].position, pos);
    assert!(w.events.iter().any(|e| e.kind == "action_interrupted"));
    // One vertical neighbor is 24 IDs away; row-end adjacency is false.
    w.players[0].position = 0;
    w.players[1].position = 24;
    assert!(w.visible(0, 1, "speech").unwrap());
    w.players[0].position = 23;
    assert!(!w.visible(0, 1, "speech").unwrap());
}

#[test]
fn observer_needs_no_character_and_survey_excludes_resource_and_danger_truth() {
    let w = world();
    let v = client_view::snapshot(&w, true, 0, &w.events);
    assert!(v["actor"].is_null());
    assert_eq!(v["players"].as_array().unwrap().len(), 2);
    assert_eq!(v["can_participate"], false);
    assert!(client_view::snapshot(&w, false, 0, &w.events).is_null());
    let a = w.participant_snapshot(1, 0, 256).unwrap();
    let b = w.participant_snapshot(2, 0, 256).unwrap();
    assert_eq!(a["context"]["map"], b["context"]["map"]);
    assert_eq!(a["context"]["map"].as_object().unwrap().len(), 3);
    assert!(a["context"].get("sites").is_none());
    assert!(!a.to_string().contains("hazard"));
}

fn matrix() -> World {
    let scenario: Scenario = serde_json::from_str(include_str!("../../scenarios/luna-arena-matrix.json")).unwrap();
    let mut w = World::new("sim-matrix-test".into(), scenario).unwrap();
    w.enable_participants();
    w
}
#[test]
fn matrix_scope_blocks_movement_conditions_perception_and_script_effects() {
    let mut w = matrix();
    let other = w.players[2].position;
    assert!(!install(&mut w, movement(other)).ok);
    let map = w.map_for_actor(1).unwrap();
    assert!(!map.contains(other));
    assert!(map.route(w.players[0].position, other).is_none());
    let participant = w.participant_snapshot(1,0,256).unwrap();
    assert!(participant["context"].get("arenas").is_none());
    assert!(participant["context"]["map"]["blocked"].as_array().unwrap().is_empty());
    assert!(!w.same_arena(1,3));
    assert!(w.same_arena(1,2));
    // Even when an operator-authored visibility law or skill ignores walls, engine scope holds.
    w.players[2].position = w.players[0].position;
    assert!(!w.visible(0,2,"speech").unwrap());
    assert!(!w.visible(0,2,"death").unwrap());
    let action = serde_json::from_value(json!({"skill":"attack","target":3})).unwrap();
    assert!(w.validate_script_effect(0,&action,&scripting::Effect::Damage{target:3,amount:20}).is_err());
    assert!(w.validate_script_effect(0,&action,&scripting::Effect::Actor{fields:std::collections::BTreeMap::from([("position".into(),other)])}).is_err());
    w.emit_speech(0,1,"test isolation").unwrap();
    assert!(!w.players[2].memories.iter().any(|m| m.kind=="speech"));
}
#[test]
fn matrix_requires_sealed_boundaries_and_advances_all_arenas_after_reload() {
    let mut w = matrix();
    let mut invalid = w.initial.clone();
    invalid.map.as_mut().unwrap().blocked.remove(&0);
    assert!(World::new("invalid".into(),invalid).is_err());
    let mut invalid = w.initial.clone();
    invalid.arenas[1].actors.push(1);
    assert!(World::new("invalid".into(),invalid).is_err());
    let goal = w.players[0].position+5;
    assert!(install(&mut w,movement(goal)).ok);
    w = serde_json::from_str(&serde_json::to_string(&w).unwrap()).unwrap();
    advance(&mut w,5000);
    assert_eq!(w.players[0].position,goal);
    for p in &w.players {assert!(w.map_for_actor(p.id).unwrap().walkable(p.position));}
    assert_eq!(client_view::snapshot(&w,true,0,&w.events)["arenas"].as_array().unwrap().len(),6);
}
