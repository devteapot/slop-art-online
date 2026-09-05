use super::*;
use participant::{Command, Request, API_VERSION};
use starting_behaviors::StartingBehavior;

fn action(action: Action) -> Node {
    Node::Action { action }
}
fn scenario() -> Scenario {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    s.starting_behaviors.clear();
    s.sites.iter_mut().for_each(|s| s.hazard = 0);
    s
}
fn seed(s: &mut Scenario, actor: u32, id: &str, tree: Node) {
    s.starting_behaviors.insert(
        actor,
        StartingBehavior {
            id: id.into(),
            revision: 1,
            description: format!("Private starting habit: {id}"),
            tree,
        },
    );
}
fn send(w: &mut World, command: Command) -> participant::Receipt {
    w.participant_apply(
        1,
        Request {
            api_version: API_VERSION.into(),
            request_id: format!("seed-test-{}", w.next_event),
            control_epoch: w.participants[&1].control_epoch,
            command,
        },
    )
    .unwrap()
}

#[test]
fn seeded_human_and_ai_move_immediately_with_equal_costs() {
    let mut s = scenario();
    seed(&mut s, 1, "travelling", action(Action::go(5)));
    seed(&mut s, 3, "travelling", action(Action::go(5)));
    let mut w = World::new("seed-costs".into(), s).unwrap();
    w.enable_participants();
    let energy = w.players[0].energy;
    assert!(w
        .players
        .iter()
        .filter(|p| p.id == 1 || p.id == 3)
        .all(|p| p.generation == 1));
    w.step();
    let ai = &w.players[0];
    let human = &w.players[2];
    assert_eq!((ai.position, human.position), (1, 1));
    assert!(ai.energy < energy);
    assert_eq!(
        (ai.energy, ai.hunger, ai.food),
        (human.energy, human.hunger, human.food)
    );
    assert!(w.pending.is_empty());
    assert!(!w.events.iter().any(|e| e.kind.starts_with("model_")));
    for actor in [1, 3] {
        assert!(w.events.iter().any(|e| e.actor == Some(actor)
            && e.kind == "skill_attempt"
            && e.data["action"]["skill"] == "move"));
    }
    assert!(
        w.players[1].execution.is_none(),
        "unseeded controls remain idle"
    );
}

#[test]
fn different_habits_produce_different_first_actions() {
    let mut s = scenario();
    seed(&mut s, 1, "explorer", action(Action::go(5)));
    seed(&mut s, 3, "rester", action(Action::new(Skill::Rest)));
    let mut w = World::new("seed-diversity".into(), s).unwrap();
    w.enable_participants();
    w.step();
    assert_eq!((w.players[0].position, w.players[2].position), (1, 0));
    for (actor, skill) in [(1, "move"), (3, "rest")] {
        assert!(w.events.iter().any(|e| e.actor == Some(actor)
            && e.kind == "skill_attempt"
            && e.data["action"]["skill"] == skill));
    }
}

#[test]
fn seed_provenance_survives_server_reload_without_cross_actor_or_initial_truth_leaks() {
    let mut s = scenario();
    seed(&mut s, 1, "own-explorer", action(Action::go(5)));
    seed(
        &mut s,
        3,
        "other-private-rester",
        action(Action::new(Skill::Rest)),
    );
    let original = World::new("seed-reload".into(), s).unwrap();
    let events = original.events.clone();
    let mut w: World = serde_json::from_value(serde_json::to_value(&original).unwrap()).unwrap();
    assert!(w.events.is_empty());
    w.enable_participants();
    for event in &events {
        w.record_initial_participant_event(event);
    }
    let own = w.context(0);
    assert_eq!(own["starting_behavior"]["id"], "own-explorer");
    assert_eq!(own["starting_behavior"]["revision"], 1);
    assert!(own["starting_behavior"]["source"]
        .as_str()
        .unwrap()
        .contains("revisable"));
    assert!(!own.to_string().contains("other-private-rester"));
    let view = client_view::snapshot(&w, false, 1, &events);
    assert_eq!(view["players"][0]["starting_behavior"]["id"], "own-explorer");
    assert!(!view.to_string().contains("other-private-rester"));
    let observer = client_view::snapshot(&w, true, 1, &events);
    assert_eq!(observer["players"][2]["starting_behavior"]["id"], "other-private-rester");
    let trace = &w.participants[&1].experiences;
    assert!(trace.iter().any(|e| e.kind == "starting_behavior_installed"
        && e.data["id"] == "own-explorer"
        && e.data["revisable"] == true));
    assert!(trace.iter().any(|e| e.kind == "policy_installed"));
    assert!(trace.iter().all(|e| events
        .iter()
        .any(|source| source.id == e.source && source.actor == Some(1))));
    assert!(trace.iter().all(|e| matches!(
        e.kind.as_str(),
        "perception" | "policy_installed" | "starting_behavior_installed"
    )));
    assert!(!serde_json::to_string(trace)
        .unwrap()
        .contains("other-private-rester"));
    w.step();
    assert_eq!(w.players[0].position, 1);
    assert_eq!(w.players[0].generation, 1);
    assert!(!w
        .events
        .iter()
        .any(|e| e.kind == "starting_behavior_installed"));
}

#[test]
fn invalid_seed_rejects_whole_world_including_unknown_actor_and_illegal_destination() {
    for invalid in 0..5 {
        let mut s = scenario();
        seed(&mut s, 1, "valid", action(Action::go(5)));
        seed(&mut s, 3, "invalid", action(Action::new(Skill::Rest)));
        match invalid {
            0 => s.starting_behaviors.get_mut(&3).unwrap().revision = 0,
            1 => s.starting_behaviors.get_mut(&3).unwrap().id = "bad id".into(),
            2 => {
                s.starting_behaviors.get_mut(&3).unwrap().tree = Node::Sequence { children: vec![] }
            }
            3 => {
                let habit = s.starting_behaviors.remove(&3).unwrap();
                s.starting_behaviors.insert(999, habit);
            }
            _ => s.starting_behaviors.get_mut(&3).unwrap().tree = action(Action::go(100_000)),
        }
        assert!(
            World::new(format!("invalid-seed-{invalid}"), s).is_err(),
            "invalid seed case {invalid} published a partially initialized world"
        );
    }
    let w = World::new("no-default".into(), scenario()).unwrap();
    assert!(w
        .players
        .iter()
        .all(|p| p.execution.is_none() && p.generation == 0));
}

#[test]
fn rejected_replacements_preserve_seed_and_successful_changes_stay_changed() {
    let mut s = scenario();
    seed(&mut s, 1, "explorer", action(Action::go(5)));
    let mut w = World::new("seed-evolution".into(), s).unwrap();
    w.enable_participants();
    w.step();
    let before = serde_json::to_value(&w.players[0].execution).unwrap();
    for (revision, tree) in [
        (0, action(Action::new(Skill::Rest))),
        (1, Node::Sequence { children: vec![] }),
    ] {
        assert!(
            !send(
                &mut w,
                Command::ReplaceTree {
                    expected_revision: revision,
                    reason: "model candidate".into(),
                    tree
                }
            )
            .ok
        );
        assert_eq!(
            serde_json::to_value(&w.players[0].execution).unwrap(),
            before
        );
        assert_eq!(w.players[0].generation, 1);
    }
    assert!(
        send(
            &mut w,
            Command::ReplaceTree {
                expected_revision: 1,
                reason: "choose to recover".into(),
                tree: action(Action::new(Skill::Rest))
            }
        )
        .ok
    );
    assert_eq!(w.players[0].generation, 2);
    w.step();
    assert_eq!(w.players[0].position, 1);
    assert!(
        send(
            &mut w,
            Command::PatchSubtree {
                expected_revision: 2,
                reason: "return home".into(),
                path: "root".into(),
                subtree: action(Action::go(0))
            }
        )
        .ok
    );
    w.step();
    assert_eq!(w.players[0].position, 0);
    assert_eq!(w.players[0].generation, 3);
    for _ in 0..3 {
        w.step();
    }
    assert_eq!(w.players[0].position, 0);
    assert_eq!(w.players[0].generation, 3);
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.kind == "starting_behavior_installed")
            .count(),
        1
    );
}

#[test]
fn settlement_seed_trees_start_four_distinct_people_before_any_model_call() {
    let s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/settlement-renewable.json")).unwrap();
    let mut w = World::new("settlement-startup".into(), s).unwrap();
    w.enable_participants();
    assert_eq!(w.players.len(), 4);
    assert!(w
        .players
        .iter()
        .all(|p| p.generation == 1 && p.execution.is_some()));
    w.step();
    for (name, skill) in [
        ("Mira", "build"),
        ("Tovan", "gather"),
        ("Iri", "observe"),
        ("Renn", "gather"),
    ] {
        let player = w.players.iter().find(|p| p.name == name).unwrap();
        let attempt = w
            .events
            .iter()
            .find(|e| e.actor == Some(player.id) && e.kind == "skill_attempt")
            .unwrap_or_else(|| panic!("{name} did not begin an action on the first update"));
        assert_eq!(
            attempt.data["action"]["skill"], skill,
            "{name}'s first action"
        );
        assert_eq!(player.generation, 1);
    }
    assert!(w.pending.is_empty());
    assert!(!w.events.iter().any(|e| e.kind.starts_with("model_")));
}

#[test]
fn seed_cannot_address_another_arena_even_when_the_cell_exists() {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/luna-arena-matrix.json")).unwrap();
    s.starting_behaviors.clear();
    let actor = s.arenas[0].actors[0];
    let other_actor = s.arenas[1].actors[0];
    let destination = s
        .players
        .iter()
        .find(|p| p.id == other_actor)
        .unwrap()
        .position;
    assert!(s.map.as_ref().unwrap().walkable(destination));
    assert!(World::new("arena-control".into(), s.clone()).is_ok());
    seed(
        &mut s,
        actor,
        "out-of-scope",
        action(Action::go(destination)),
    );
    assert!(World::new("arena-seed-rejection".into(), s).is_err());
}
