use super::*;
use lifecycle::{BodyKind, LifecycleSeed, Origin};
use scripting::Effect;

fn scenario() -> Scenario {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    s.starting_behaviors.clear();
    s.weather = None;
    s.max_ticks = 1000;
    for p in &mut s.players {
        p.position = 0;
        p.health = 100;
        p.hunger = 0;
        p.energy = 100;
        p.food = 20;
        p.beliefs.clear();
    }
    s.sites.iter_mut().for_each(|s| s.hazard = 0);
    s.sites[0].food = 30;
    s.lifecycle = Some(serde_json::from_value::<LifecycleSeed>(json!({
        "workshops":[0],"max_total":10,"newcomer":{
            "name_prefix":"Newcomer","motive":"Learn to provide for myself", "caution":40,"empathy":60,"introspection":80,
            "starting_behavior":{"id":"dependent-wait","revision":1,"description":"Wait for care while learning",
                "tree":{"kind":"action","action":{"skill":"wait"}}}
        }
    })).unwrap());
    s
}
fn world() -> World {
    let mut w = World::new("lifecycle-fixture".into(), scenario()).unwrap();
    w.enable_participants();
    w
}
fn action(skill: Skill, target: Option<u32>) -> Action {
    Action {
        target,
        ..Action::new(skill)
    }
}
fn install(w: &mut World, actor: u32, a: Action) {
    w.participant_manual(
        actor,
        Decision {
            reason: "Exercise material population renewal".into(),
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
fn copy_effect(effect: &Effect) -> Effect {
    serde_json::from_value(serde_json::to_value(effect).unwrap()).unwrap()
}
fn apply(w: &mut World, actor: u32, a: Action, effect: Effect) -> Result<(), String> {
    let i = w.idx(actor)?;
    w.validate_lifecycle_effect(i, &a, &effect)?;
    let cause = w.event(Some(actor), "lifecycle_test_input", vec![], json!({}));
    w.apply_lifecycle_effect(i, cause, &effect)
}
fn offer(w: &mut World, actor: u32, partner: u32) {
    apply(
        w,
        actor,
        action(Skill::OfferReproduction, Some(partner)),
        Effect::OfferReproduction {
            partner,
            expires_ms: w.timing.time_ms + 120_000,
            food: 2,
            energy: 10,
        },
    )
    .unwrap();
}
fn reproduction(w: &World, actor: u32, partner: u32) -> Effect {
    Effect::Reproduce {
        partner,
        own_offer: w.reproduction_offers[&actor].source,
        partner_offer: w.reproduction_offers[&partner].source,
    }
}
fn fabricate(w: &mut World, actor: u32) -> u32 {
    let id = w.next_actor;
    apply(
        w,
        actor,
        Action::new(Skill::Fabricate),
        Effect::Fabricate {
            food: 6,
            energy: 30,
        },
    )
    .unwrap();
    id
}
fn care(w: &mut World, actor: u32, child: u32) {
    apply(
        w,
        actor,
        action(Skill::Care, Some(child)),
        Effect::Care {
            target: child,
            energy: 2,
            nutrition: 35,
        },
    )
    .unwrap();
}

#[test]
fn reproduction_requires_mutual_current_local_consent_and_resources() {
    let mut w = world();
    offer(&mut w, 1, 2);
    assert!(apply(
        &mut w,
        1,
        action(Skill::Reproduce, Some(2)),
        Effect::Reproduce {
            partner: 2,
            own_offer: 1,
            partner_offer: 0
        }
    )
    .is_err());
    offer(&mut w, 2, 1);
    let effect = reproduction(&w, 1, 2);
    for fault in [
        "remote",
        "dead",
        "food",
        "artificial",
        "dependent",
        "expired",
    ] {
        let mut bad = w.clone();
        match fault {
            "remote" => bad.players[1].position = 2,
            "dead" => bad.players[1].health = 0,
            "food" => bad.players[1].food = 1,
            "artificial" => bad.lifecycle.get_mut(&2).unwrap().body = BodyKind::Artificial,
            "dependent" => bad.lifecycle.get_mut(&2).unwrap().dependent = true,
            "expired" => bad.timing.time_ms = 120_000,
            _ => unreachable!(),
        }
        assert!(
            apply(
                &mut bad,
                1,
                action(Skill::Reproduce, Some(2)),
                copy_effect(&effect)
            )
            .is_err(),
            "{fault}"
        );
        assert_eq!(bad.players.len(), 3);
        assert_eq!(bad.players[0].food, 20);
    }
    apply(
        &mut w,
        1,
        action(Skill::Reproduce, Some(2)),
        copy_effect(&effect),
    )
    .unwrap();
    assert_eq!(w.players.len(), 4);
    assert_eq!((w.players[0].food, w.players[1].food), (18, 18));
    assert_eq!((w.players[0].energy, w.players[1].energy), (90, 90));
    assert!(w.reproduction_offers.is_empty());
    assert!(apply(&mut w, 1, action(Skill::Reproduce, Some(2)), effect).is_err());
}

#[test]
fn withdrawal_and_renewal_cannot_reauthorize_an_old_attempt() {
    let mut w = world();
    offer(&mut w, 1, 2);
    offer(&mut w, 2, 1);
    let old = reproduction(&w, 1, 2);
    apply(
        &mut w,
        2,
        Action::new(Skill::WithdrawReproduction),
        Effect::WithdrawReproduction,
    )
    .unwrap();
    offer(&mut w, 2, 1);
    assert!(apply(&mut w, 1, action(Skill::Reproduce, Some(2)), old).is_err());
    let current = reproduction(&w, 1, 2);
    apply(&mut w, 1, action(Skill::Reproduce, Some(2)), current).unwrap();
    assert_eq!(w.players.len(), 4);
}

#[test]
fn reciprocal_timed_attempts_commit_only_one_birth_and_charge_both_parents_once() {
    let mut w = world();
    finish(&mut w, 1, action(Skill::OfferReproduction, Some(2)), 1000);
    finish(&mut w, 2, action(Skill::OfferReproduction, Some(1)), 1000);
    assert_eq!(w.reproduction_offers.len(), 2);
    install(&mut w, 1, action(Skill::Reproduce, Some(2)));
    install(&mut w, 2, action(Skill::Reproduce, Some(1)));
    w.advance_ms(29_999);
    assert_eq!(w.players.len(), 3);
    assert_eq!((w.players[0].food, w.players[1].food), (20, 20));
    w = serde_json::from_value(serde_json::to_value(&w).unwrap()).unwrap();
    w.advance_ms(1);
    assert_eq!(
        w.players.len(),
        4,
        "{:?}",
        w.events.iter().rev().take(8).collect::<Vec<_>>()
    );
    assert_eq!((w.players[0].food, w.players[1].food), (18, 18));
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.kind == "actor_created")
            .count(),
        1
    );
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.kind == "food_consumed" && e.data["reason"] == "reproduction")
            .count(),
        2
    );
}

#[test]
fn fabrication_is_local_timed_and_equal_for_human_and_ai() {
    for actor in [1, 3] {
        let mut w = world();
        finish(&mut w, actor, Action::new(Skill::Fabricate), 44_999);
        assert_eq!(w.players.len(), 3);
        w.advance_ms(1);
        assert_eq!(w.players.len(), 4);
        let p = &w.players[w.idx(actor).unwrap()];
        assert_eq!((p.food, p.energy), (14, 70));
        assert_eq!(w.lifecycle[&4].body, BodyKind::Artificial);
        assert!(
            matches!(w.lifecycle[&4].origin,Origin::Fabrication{creator,workshop:0} if creator==actor)
        );
        assert_eq!(
            (w.players[3].hunger, w.players[3].energy, w.players[3].food),
            (50, 50, 0),
            "newborn inherits no pre-birth needs pulses"
        );
    }
    let mut w = world();
    w.players[0].position = 2;
    assert!(apply(
        &mut w,
        1,
        Action::new(Skill::Fabricate),
        Effect::Fabricate {
            food: 6,
            energy: 30
        }
    )
    .is_err());
    w.players[0].position = 0;
    w.players[0].food = 5;
    assert!(apply(
        &mut w,
        1,
        Action::new(Skill::Fabricate),
        Effect::Fabricate {
            food: 6,
            energy: 30
        }
    )
    .is_err());
}

#[test]
fn new_identity_has_own_registration_seed_policy_and_no_creator_inheritance() {
    let mut s = scenario();
    s.knowledge.insert(
        1,
        vec![knowledge::RecordSeed {
            id: "private-parent-report".into(),
            topic: "Private".into(),
            text: "PARENT PRIVATE SECRET".into(),
            location: Some(0),
            confidence: 80,
        }],
    );
    let mut w = World::new("newborn-private".into(), s).unwrap();
    w.enable_participants();
    w.players[0].current_goal = Some("PRIVATE PARENT GOAL".into());
    let initial = serde_json::to_value(&w.initial).unwrap();
    let id = fabricate(&mut w, 1);
    let i = w.idx(id).unwrap();
    let child = &w.players[i];
    assert_eq!(child.generation, 1);
    assert!(child.execution.is_some());
    assert!(
        child.knowledge.is_empty() && child.beliefs.is_empty() && child.relationships.is_empty()
    );
    assert_eq!(child.food, 0);
    assert_eq!(child.caution, 40);
    assert!(w.participants.contains_key(&id));
    let view = w.participant_snapshot(id, 0, 256).unwrap().to_string();
    assert!(!view.contains("PARENT PRIVATE SECRET") && !view.contains("PRIVATE PARENT GOAL"));
    assert!(view.contains("own_creation") && view.contains("dependent-wait"));
    assert_eq!(serde_json::to_value(&w.initial).unwrap(), initial);
    w.players[i].health = 0;
    let next = fabricate(&mut w, 2);
    assert_eq!(next, id + 1);
    assert!(w.lifecycle.contains_key(&id));
    assert_eq!(serde_json::to_value(&w.initial).unwrap(), initial);
}

#[test]
fn development_needs_real_care_personal_interpretation_guided_harvest_and_age() {
    let mut s = scenario();
    s.knowledge.insert(
        1,
        vec![knowledge::RecordSeed {
            id: "local-food".into(),
            topic: "Local food".into(),
            text: "I found food here".into(),
            location: Some(0),
            confidence: 70,
        }],
    );
    let mut w = World::new("development".into(), s).unwrap();
    w.enable_participants();
    let child = fabricate(&mut w, 1);
    let ci = w.idx(child).unwrap();
    for skill in [Skill::Gather, Skill::Script("gather".into())] {
        let resources = (w.players[ci].food, w.players[ci].energy, w.sites[0].food);
        finish(&mut w, child, Action::new(skill), 1);
        assert_eq!(
            (w.players[ci].food, w.players[ci].energy, w.sites[0].food),
            resources,
            "dependent cannot bypass provisioning gate through the scripted alias"
        );
        assert!(w.events.iter().any(|e| e.actor == Some(child)
            && e.kind == "skill_result"
            && e.data["status"] == "failed"
            && e.data["reason"]
                .as_str()
                .is_some_and(|reason| reason.contains("independent provisioning"))));
    }
    let mut practice = action(Skill::Practice, Some(1));
    practice.record = Some("local-food".into());
    let effect = Effect::Practice {
        guide: 1,
        record: "local-food".into(),
        energy: 4,
    };
    assert!(apply(&mut w, child, practice.clone(), copy_effect(&effect)).is_err());
    care(&mut w, 1, child);
    assert_eq!(w.players[ci].hunger, 15);
    assert!(
        apply(
            &mut w,
            1,
            action(Skill::Care, Some(child)),
            Effect::Care {
                target: child,
                energy: 2,
                nutrition: 35
            }
        )
        .is_err(),
        "unneeded food cannot farm care evidence"
    );
    let mut teach = action(Skill::Teach, Some(child));
    teach.record = Some("local-food".into());
    finish(&mut w, 1, teach, 2000);
    assert_eq!(w.players[ci].knowledge.len(), 1);
    assert!(
        apply(&mut w, child, practice.clone(), copy_effect(&effect)).is_err(),
        "receiving a report does not mean interpreting it"
    );
    let source = w.players[ci].knowledge[0].source;
    let receipt = w
        .participant_apply(
            child,
            participant::Request {
                api_version: participant::API_VERSION.into(),
                request_id: "interpret-food-report".into(),
                control_epoch: w.participants[&child].control_epoch,
                command: participant::Command::Reflect {
                    expected_revision: w.participants[&child].learning_revision,
                    observed_cursor: w.participants[&child].cursor,
                    reflections: vec![Reflection {
                        source,
                        interpretation: "I will test this report under guidance".into(),
                        caution_delta: 0,
                        trust_delta: 0,
                        belief: None,
                        knowledge: None,
                    }],
                    goal: None,
                },
            },
        )
        .unwrap();
    assert!(receipt.ok, "{receipt:?}");
    let mut wrong = practice.clone();
    wrong.target = Some(2);
    assert!(apply(
        &mut w,
        child,
        wrong,
        Effect::Practice {
            guide: 2,
            record: "local-food".into(),
            energy: 4
        }
    )
    .is_err());
    w.players[ci].position = 2;
    w.players[0].position = 2;
    assert!(
        apply(&mut w, child, practice.clone(), copy_effect(&effect)).is_err(),
        "typed report applies only to its location"
    );
    w.players[ci].position = 0;
    w.players[0].position = 0;
    let food = w.sites[0].food;
    let energy = w.players[ci].energy;
    finish(&mut w, child, practice, 5000);
    assert_eq!(w.sites[0].food, food - 1);
    assert_eq!(w.players[ci].food, 1);
    assert_eq!(w.players[ci].energy, energy - 4);
    assert_eq!(w.lifecycle[&child].practice, 1);
    w.advance_lifecycle().unwrap();
    assert!(w.lifecycle[&child].dependent);
    w.players[ci].hunger = 60;
    care(&mut w, 1, child);
    w.advance_lifecycle().unwrap();
    assert!(
        w.lifecycle[&child].dependent,
        "care and practice still require development time"
    );
    let stored_food = w.players[ci].food;
    finish(&mut w, child, Action::new(Skill::Gather), 1);
    assert_eq!(
        w.players[ci].food, stored_food,
        "care and practice do not bypass minimum age"
    );
    w.timing.time_ms = 60_000;
    w.advance_lifecycle().unwrap();
    assert!(!w.lifecycle[&child].dependent);
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.kind == "self_support_acquired" && e.actor == Some(child))
            .count(),
        1
    );
    w.advance_lifecycle().unwrap();
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.kind == "self_support_acquired" && e.actor == Some(child))
            .count(),
        1
    );
    for skill in [Skill::Gather, Skill::Script("gather".into())] {
        let food = w.players[ci].food;
        let available = w.sites[0].food;
        finish(&mut w, child, Action::new(skill), 2500);
        assert_eq!(
            w.players[ci].food,
            food + 1,
            "same individual can now provision independently"
        );
        assert_eq!(w.sites[0].food, available - 1);
    }
}

#[test]
fn invalid_later_effect_rolls_back_creation_registration_identity_and_cost() {
    let mut w = world();
    let mut definition = w.scripts.history["fabricate"][&w.scripts.active["fabricate"]].clone();
    definition.revision += 1;
    definition.source="fn validate(c) { \"\" } fn step(c) { law::done([#{kind:\"fabricate\",food:6,energy:30},#{kind:\"actor\",fields:#{health:0}}]) }".into();
    w.stage_scripts_by_operator(scripting::Update {
        api_version: scripting::API_VERSION,
        expected_revision: w.scripts.revision,
        definitions: vec![definition],
    })
    .unwrap();
    w.advance_ms(1);
    finish(&mut w, 1, Action::new(Skill::Fabricate), 1);
    assert_eq!(w.players.len(), 3);
    assert_eq!(w.next_actor, 4);
    assert_eq!((w.players[0].food, w.players[0].energy), (20, 100));
    assert!(!w.participants.contains_key(&4) && !w.lifecycle.contains_key(&4));
    assert!(!w
        .events
        .iter()
        .any(|e| e.kind == "actor_created" || e.kind == "food_consumed"));
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "script_error" && e.data["effects_committed"] == false));
}

#[test]
fn newborn_scope_survives_reload_and_never_crosses_into_another_arena() {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/luna-arena-matrix.json")).unwrap();
    s.starting_behaviors.clear();
    let mut seed = scenario().lifecycle.unwrap();
    seed.max_total = 32;
    seed.workshops = vec![s.players[0].position];
    s.lifecycle = Some(seed);
    s.players[0].food = 20;
    s.players[0].energy = 100;
    let mut w = World::new("scoped-newborn".into(), s).unwrap();
    w.enable_participants();
    let initial = serde_json::to_value(&w.initial).unwrap();
    let id = fabricate(&mut w, 1);
    assert!(w.same_arena(id, 1));
    assert!(!w.same_arena(id, 3));
    assert_eq!(
        w.arena_for_actor(id).unwrap().id,
        w.arena_for_actor(1).unwrap().id
    );
    assert!(!w.map_for_actor(id).unwrap().contains(w.players[2].position));
    w = serde_json::from_value(serde_json::to_value(&w).unwrap()).unwrap();
    assert!(w.same_arena(id, 1));
    assert!(!w.same_arena(id, 3));
    assert_eq!(serde_json::to_value(&w.initial).unwrap(), initial);
    w.players[2].position = w.players[w.idx(id).unwrap()].position;
    assert!(apply(
        &mut w,
        3,
        action(Skill::Care, Some(id)),
        Effect::Care {
            target: id,
            energy: 2,
            nutrition: 35
        }
    )
    .is_err());
    assert!(!w.players[2]
        .memories
        .iter()
        .any(|m| m.kind == "new_individual" && m.from == Some(id)));
}

#[test]
fn expired_or_dead_partner_cannot_complete_unfinished_reproduction() {
    for fault in ["expiry", "death", "withdrawal"] {
        let mut w = world();
        offer(&mut w, 1, 2);
        offer(&mut w, 2, 1);
        if fault == "expiry" {
            w.reproduction_offers.get_mut(&2).unwrap().expires_ms = 29_000;
        }
        install(&mut w, 1, action(Skill::Reproduce, Some(2)));
        w.advance_ms(15_000);
        assert_eq!(w.players.len(), 3);
        if fault == "death" {
            w.players[1].health = 0;
        }
        if fault == "withdrawal" {
            apply(
                &mut w,
                2,
                Action::new(Skill::WithdrawReproduction),
                Effect::WithdrawReproduction,
            )
            .unwrap();
            offer(&mut w, 2, 1);
        }
        w.advance_ms(15_000);
        assert_eq!(w.players.len(), 3, "{fault}");
        assert_eq!((w.players[0].food, w.players[1].food), (20, 20));
        assert!(!w.events.iter().any(|e| e.kind == "actor_created"));
    }
}

#[test]
fn retained_population_capacity_is_not_reclaimed_by_death() {
    let mut s = scenario();
    s.lifecycle.as_mut().unwrap().max_total = 4;
    let mut w = World::new("capacity".into(), s).unwrap();
    w.enable_participants();
    let id = fabricate(&mut w, 1);
    let i = w.idx(id).unwrap();
    w.players[i].health = 0;
    assert!(apply(
        &mut w,
        2,
        Action::new(Skill::Fabricate),
        Effect::Fabricate {
            food: 6,
            energy: 30
        }
    )
    .is_err());
    assert_eq!(w.next_actor, 5);
    assert_eq!(w.players.len(), 4);
    assert_eq!(w.players[1].food, 20);
}

#[test]
fn newborn_metabolism_starts_at_birth_between_global_pulse_boundaries() {
    let mut w = world();
    w.advance_ms(333);
    finish(&mut w, 1, Action::new(Skill::Fabricate), 45_000);
    let child = 4;
    let i = w.idx(child).unwrap();
    assert_eq!(w.lifecycle[&child].born_ms, 45_333);
    assert_eq!(w.players[i].hunger, 50);
    // Global adults pulse at 47500; this infant's first pulse belongs at 47833.
    w.advance_ms(2167);
    assert_eq!(w.timing.time_ms, 47_500);
    assert_eq!(w.players[i].hunger, 50);
    w = serde_json::from_value(serde_json::to_value(&w).unwrap()).unwrap();
    w.advance_ms(332);
    assert_eq!(w.players[i].hunger, 50);
    w.advance_ms(1);
    assert_eq!(w.players[i].hunger, 52);
}

#[test]
fn care_need_guard_refreshes_after_meal_departure_and_other_cell_observation() {
    let mut w = world();
    let child = fabricate(&mut w, 1);
    let i = w.idx(child).unwrap();
    let guard = Condition::NeedsCare { target: child };
    w.refresh_lifecycle_observations().unwrap();
    assert!(guard.evaluate(&w.players[0]).0);
    assert!(
        !Condition::NeedsCare { target: 999 }
            .evaluate(&w.players[0])
            .0
    );
    care(&mut w, 1, child);
    w.refresh_lifecycle_observations().unwrap();
    assert!(!guard.evaluate(&w.players[0]).0);
    w.players[i].hunger = 60;
    w.refresh_lifecycle_observations().unwrap();
    assert!(guard.evaluate(&w.players[0]).0);
    w.players[i].position = 2;
    w.refresh_lifecycle_observations().unwrap();
    assert!(
        !guard.evaluate(&w.players[0]).0,
        "the current site observation no longer includes the child"
    );
    w.players[0].position = 2;
    w.refresh_lifecycle_observations().unwrap();
    assert!(guard.evaluate(&w.players[0]).0);
    w.players[0].position = 0;
    assert!(
        !guard.evaluate(&w.players[0]).0,
        "retained child needs at another cell do not authorize local care"
    );
}

#[test]
fn newborn_cold_damage_uses_birth_relative_hazard_pulse_times() {
    // Actual infant pulse times are 2833, 5333 and 7833 ms. A late update
    // must neither charge a pre-onset pulse nor omit a post-onset pulse.
    for (cold_after_ms, elapsed_ms, expected_health) in
        [(2600, 2500, 98), (2850, 2567, 100), (5100, 7500, 96)]
    {
        let mut s = scenario();
        s.weather = Some(Weather {
            cold_after_ms,
            damage_per_pulse: 2,
            shelter_required: 12,
        });
        let mut w = World::new("newborn-cold-phase".into(), s).unwrap();
        w.enable_participants();
        w.advance_ms(333);
        let child = fabricate(&mut w, 1);
        let i = w.idx(child).unwrap();
        w.advance_ms(elapsed_ms);
        assert_eq!(
            w.players[i].health, expected_health,
            "cold onset {cold_after_ms}, update elapsed {elapsed_ms}"
        );
    }
}

#[test]
fn private_lifecycle_offers_and_newborn_origin_do_not_leak_to_bystanders() {
    let mut w = world();
    offer(&mut w, 1, 2);
    let peer = w.local_lifecycle_catalog(1);
    let bystander = w.local_lifecycle_catalog(2);
    assert_eq!(peer["offers_to_you"].as_array().unwrap().len(), 1);
    assert_eq!(bystander["offers_to_you"], json!([]));
    assert!(bystander["own_offer"].is_null());
    w.refresh_lifecycle_observations().unwrap();
    let public = client_view::snapshot(&w, false, 3, &w.events);
    assert!(
        !public.to_string().contains("food_commitment"),
        "unaddressed offers are not public events"
    );
    w.players[2].position = 2;
    let bystander = w.local_lifecycle_catalog(2);
    assert_eq!(bystander["people"].as_array().unwrap().len(), 1);
    let child = fabricate(&mut w, 1);
    let remote = client_view::snapshot(&w, false, 3, &w.events);
    assert!(!remote.to_string().contains(&format!("Newcomer {child}")));
    assert!(!w.players[2]
        .memories
        .iter()
        .any(|m| m.kind == "new_individual" && m.from == Some(child)));
}

#[test]
fn cultural_identity_and_controller_do_not_change_creation_physics() {
    let baseline = scenario();
    let mut renamed = baseline.clone();
    renamed.name = "A different culture with the same material conditions".into();
    for player in &mut renamed.players {
        player.name = format!("Other culture member {}", player.id);
        player.motive = "I value a different tradition and choose my own commitments".into();
        player.controller = match player.controller {
            Controller::Ai => Controller::Human,
            Controller::Human => Controller::Ai,
        };
    }
    let newcomer = &mut renamed.lifecycle.as_mut().unwrap().newcomer;
    newcomer.name_prefix = "Other culture newcomer".into();
    newcomer.motive = "I want to understand this other culture through my own experience".into();
    let mut a = World::new("identity-baseline".into(), baseline).unwrap();
    let mut b = World::new("identity-renamed".into(), renamed).unwrap();
    for w in [&mut a, &mut b] {
        w.enable_participants();
        assert_eq!(fabricate(w, 1), 4);
        offer(w, 1, 2);
        offer(w, 2, 1);
        let committed = reproduction(w, 1, 2);
        apply(w, 1, action(Skill::Reproduce, Some(2)), committed).unwrap();
    }
    assert_ne!(a.players[0].name, b.players[0].name);
    assert_ne!(a.players[0].controller, b.players[0].controller);
    assert_ne!(a.players[3].motive, b.players[3].motive);
    let physical = |w: &World| {
        w.players
            .iter()
            .map(|p| (p.id, p.position, p.health, p.hunger, p.energy, p.food))
            .collect::<Vec<_>>()
    };
    assert_eq!(physical(&a), physical(&b));
    assert_eq!(
        physical(&a),
        vec![
            (1, 0, 100, 0, 60, 12),
            (2, 0, 100, 0, 90, 18),
            (3, 0, 100, 0, 100, 20),
            (4, 0, 100, 50, 50, 0),
            (5, 0, 100, 50, 50, 0)
        ]
    );
    assert_eq!(
        serde_json::to_value(&a.lifecycle).unwrap(),
        serde_json::to_value(&b.lifecycle).unwrap()
    );
    assert_eq!(a.next_actor, b.next_actor);
    assert!(a.reproduction_offers.is_empty() && b.reproduction_offers.is_empty());
    let costs = |w: &World| {
        w.events
            .iter()
            .filter(|e| e.kind == "food_consumed")
            .map(|e| (e.actor, e.data.clone()))
            .collect::<Vec<_>>()
    };
    assert_eq!(costs(&a), costs(&b));
}

#[test]
fn retained_local_catalog_authorizes_care_install_and_patch_after_arrival_memory_eviction() {
    let mut s = scenario();
    s.players[2].position = 5;
    let mut baseline = World::new("retained-care-target".into(), s).unwrap();
    baseline.enable_participants();
    let child = fabricate(&mut baseline, 1);
    baseline.refresh_lifecycle_observations().unwrap();
    for _ in 0..20 {
        let source = baseline.event(Some(1), "unrelated_test_experience", vec![], json!({}));
        baseline
            .perceive(
                0,
                source,
                "own_experience",
                None,
                0,
                json!({"meaning":"another experience"}),
            )
            .unwrap();
    }
    assert!(!baseline.players[0]
        .memories
        .iter()
        .any(|m| m.from == Some(child)));
    assert!(baseline.players[0]
        .site_observations
        .iter()
        .any(|m| m.content["lifecycle"]["people"]
            .as_array()
            .is_some_and(|people| people.iter().any(|p| p["id"] == child))));
    let send = |w: &mut World, command| {
        w.participant_apply(
            1,
            participant::Request {
                api_version: participant::API_VERSION.into(),
                request_id: format!("retained-target-{}", w.next_event),
                control_epoch: w.participants[&1].control_epoch,
                command,
            },
        )
        .unwrap()
    };
    for patch in [false, true] {
        for (target, retain_catalog) in [(child, true), (child, false), (3, true), (9999, true)] {
            let mut w = baseline.clone();
            if !retain_catalog {
                w.players[0].site_observations.clear();
            }
            if patch {
                let revision = w.players[0].generation;
                assert!(
                    send(
                        &mut w,
                        participant::Command::ReplaceTree {
                            expected_revision: revision,
                            reason: "install a tree to patch".into(),
                            tree: Node::Action {
                                action: Action::new(Skill::Wait)
                            },
                        }
                    )
                    .ok
                );
            }
            let tree = Node::Action {
                action: action(Skill::Care, Some(target)),
            };
            let revision = w.players[0].generation;
            let command = if patch {
                participant::Command::PatchSubtree {
                    expected_revision: revision,
                    reason: "care for a person in my retained observation".into(),
                    path: "root".into(),
                    subtree: tree,
                }
            } else {
                participant::Command::ReplaceTree {
                    expected_revision: revision,
                    reason: "care for a person in my retained observation".into(),
                    tree,
                }
            };
            let receipt = send(&mut w, command);
            assert_eq!(
                receipt.ok,
                target == child && retain_catalog,
                "patch={patch}, target={target}, receipt={receipt:?}"
            );
            if target == child && retain_catalog {
                w.advance_ms(3000);
                assert_eq!(w.lifecycle[&child].care_meals, 1);
                assert_eq!(w.players[0].food, baseline.players[0].food - 1);
            } else {
                assert_eq!(w.players[0].generation, revision);
                assert_eq!(w.lifecycle[&child].care_meals, 0);
            }
        }
    }
}
