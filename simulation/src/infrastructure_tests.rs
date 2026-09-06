use super::*;
use infrastructure::{
    ForecastInput, InfrastructureOperation as Op, InfrastructureSeed, Material, Module,
};
use scripting::Effect;

fn scenario() -> Scenario {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    s.weather = None;
    s.max_ticks = 1000;
    s.starting_behaviors.clear();
    for p in &mut s.players {
        p.position = 0;
        p.health = 100;
        p.hunger = 0;
        p.energy = 80;
        p.food = 10;
        p.beliefs.clear();
    }
    for site in &mut s.sites {
        site.hazard = 0;
    }
    s.infrastructure=Some(serde_json::from_value::<InfrastructureSeed>(json!({
        "version":1,"bodies":{"1":{"version":1,"support":"electric","capacity":100,"initial_charge":20,"drain_per_pulse":1}},
        "actor_materials":{"1":{"parts":20,"water":10},"2":{"parts":10,"water":5}},
        "stations":[{"id":1,"owner":1,"position":0,"label":"Utility station","electricity":30,"electricity_capacity":100,
            "materials":{"parts":5,"water":20},"modules":["charger","terminal"],
            "access":{"2":{"use_allowed":true,"maintain":true,"admin":false},"3":{"use_allowed":true}},
            "generation_period_ms":1000,"generation_amount":3}]
    })).unwrap());
    s
}
fn world() -> World {
    let mut w = World::new("infrastructure-test".into(), scenario()).unwrap();
    w.enable_participants();
    w
}
fn input() -> ForecastInput {
    ForecastInput {
        stock: 10,
        inflow_per_min: 3,
        demand_per_min: 5,
        horizon_ms: 120000,
        sources: vec![],
    }
}
fn action(op: Op) -> Action {
    Action {
        infrastructure: Some(op),
        ..Action::new(Skill::Infrastructure)
    }
}
fn apply(w: &mut World, actor: u32, op: Op) -> Result<(), String> {
    let i = w.idx(actor)?;
    let a = action(op.clone());
    let effect = Effect::Infrastructure { operation: op };
    w.validate_infrastructure_effect(i, &a, &effect)?;
    let cause = w.event(Some(actor), "infrastructure_test_input", vec![], json!({}));
    w.apply_infrastructure_effect(i, cause, &effect)
}
fn advance(w: &mut World, ms: u64) {
    w.timing.time_ms += ms;
    w.advance_infrastructure(ms).unwrap();
}
fn install(w: &mut World, actor: u32, a: Action) {
    w.participant_manual(
        actor,
        Decision {
            reason: "Use material infrastructure".into(),
            actions: vec![a],
            policy: None,
            reflections: vec![],
        },
    )
    .unwrap();
}
fn state(w: &World) -> Value {
    serde_json::to_value(&w.infrastructure).unwrap()
}
fn submit(w: &mut World, actor: u32) -> u64 {
    let id = w.infrastructure.next_job;
    apply(
        w,
        actor,
        Op::SubmitJob {
            station: 1,
            input: input(),
        },
    )
    .unwrap();
    id
}

#[test]
fn single_chosen_job_and_ready_retrieval_do_not_repeat_after_success_or_reload() {
    let mut w=world();
    let once=|op| Node::Once {child:Box::new(Node::Action {action:action(op)})};
    w.participant_manual(1,Decision {reason:"One forecast then retrieve its result and rest".into(),
        actions:vec![],reflections:vec![],policy:Some(Node::Priority {children:vec![
            once(Op::SubmitJob {station:1,input:input()}),
            once(Op::RetrieveReady {station:1}),
            Node::Action {action:Action::new(Skill::Rest)},
        ]})}).unwrap();
    for _ in 0..200 {w.advance_ms(50);}
    assert_eq!(w.infrastructure.stations[0].jobs.len(),1);
    assert!(w.infrastructure.stations[0].jobs[0].retrieved);
    assert_eq!(w.players[0].execution.as_ref().unwrap().state.once_completed.len(),2);
    assert_eq!(w.players[0].knowledge.len(),1);
    let restored: World=serde_json::from_str(&serde_json::to_string(&w).unwrap()).unwrap();
    w=restored;
    for _ in 0..100 {w.advance_ms(50);}
    assert_eq!(w.infrastructure.stations[0].jobs.len(),1);
    assert!(!w.events.iter().any(|e|e.kind=="compute_submitted" || e.kind=="compute_retrieved"));
}

#[test]
fn ready_retrieval_selects_only_own_uncollected_physical_output() {
    let mut w=world();
    assert!(apply(&mut w,1,Op::RetrieveReady{station:1}).is_err());
    submit(&mut w,2);
    advance(&mut w,3000);
    assert!(apply(&mut w,1,Op::RetrieveReady{station:1}).is_err());
    apply(&mut w,2,Op::RetrieveReady{station:1}).unwrap();
    assert!(apply(&mut w,2,Op::RetrieveReady{station:1}).is_err());
    assert_eq!(w.players[1].knowledge.len(),1);
    assert!(w.players[0].knowledge.is_empty());
}

#[test]
fn infrastructure_permissions_materials_and_selection_are_atomic() {
    let mut w = world();
    let before = state(&w);
    for op in [
        Op::TakeMaterial {
            station: 1,
            material: Material::Parts,
            amount: 6,
        },
        Op::DepositMaterial {
            station: 1,
            material: Material::Water,
            amount: 11,
        },
        Op::Charge {
            station: 1,
            amount: 31,
        },
        Op::Build {
            station: 1,
            module: Module::Terminal,
        },
    ] {
        assert!(apply(&mut w, 1, op).is_err());
        assert_eq!(state(&w), before);
    }
    assert!(apply(
        &mut w,
        3,
        Op::Build {
            station: 1,
            module: Module::Generator
        }
    )
    .is_err());
    assert!(apply(
        &mut w,
        2,
        Op::SetEnabled {
            station: 1,
            enabled: false
        }
    )
    .is_err());
    let effect = Effect::Infrastructure {
        operation: Op::TakeMaterial {
            station: 1,
            material: Material::Water,
            amount: 1,
        },
    };
    assert!(w
        .validate_infrastructure_effect(
            0,
            &action(Op::Charge {
                station: 1,
                amount: 1
            }),
            &effect
        )
        .is_err());
    apply(
        &mut w,
        1,
        Op::TakeMaterial {
            station: 1,
            material: Material::Parts,
            amount: 5,
        },
    )
    .unwrap();
    apply(
        &mut w,
        1,
        Op::DepositMaterial {
            station: 1,
            material: Material::Water,
            amount: 4,
        },
    )
    .unwrap();
    apply(
        &mut w,
        1,
        Op::Build {
            station: 1,
            module: Module::Generator,
        },
    )
    .unwrap();
    assert_eq!(w.infrastructure.actor_materials[&1].parts, 19);
    assert_eq!(w.infrastructure.stations[0].embodied_parts, 14);
    assert_eq!(w.infrastructure.actor_materials[&1].water, 6);
    assert_eq!(w.infrastructure.stations[0].seed.materials.water, 24);
    advance(&mut w, 1000);
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 33);
    apply(
        &mut w,
        1,
        Op::Charge {
            station: 1,
            amount: 12,
        },
    )
    .unwrap();
    assert_eq!(w.infrastructure.bodies[&1].charge, 32);
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 21);
    w.infrastructure.stations[0].integrity = 70;
    apply(
        &mut w,
        2,
        Op::Repair {
            station: 1,
            parts: 2,
        },
    )
    .unwrap();
    assert_eq!(w.infrastructure.stations[0].integrity, 100);
    assert_eq!(w.infrastructure.actor_materials[&2].parts, 8);
    assert_eq!(w.infrastructure.stations[0].repair_parts_consumed, 2);
}

#[test]
fn compute_requires_both_inputs_each_quantum_and_resumes_without_refunds_or_catchup() {
    let mut w = world();
    let job = submit(&mut w, 2);
    w.infrastructure.stations[0].seed.materials.water = 1;
    advance(&mut w, 999);
    assert_eq!(w.infrastructure.stations[0].jobs[0].progress, 0);
    advance(&mut w, 1);
    assert_eq!(w.infrastructure.stations[0].jobs[0].progress, 1);
    advance(&mut w, 5000);
    let s = &w.infrastructure.stations[0];
    assert_eq!(s.jobs[0].progress, 1);
    assert_eq!(s.seed.electricity, 28);
    assert_eq!(s.seed.materials.water, 0);
    assert_eq!(s.jobs[0].blocked_reason.as_deref(), Some("cooling_water"));
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.kind == "compute_availability_changed")
            .count(),
        1
    );
    apply(
        &mut w,
        2,
        Op::DepositMaterial {
            station: 1,
            material: Material::Water,
            amount: 2,
        },
    )
    .unwrap();
    advance(&mut w, 1000);
    assert_eq!(w.infrastructure.stations[0].jobs[0].progress, 2);
    w.infrastructure.stations[0].seed.electricity = 1;
    advance(&mut w, 1000);
    assert_eq!(w.infrastructure.stations[0].seed.materials.water, 1);
    assert_eq!(w.infrastructure.stations[0].jobs[0].progress, 2);
    w.infrastructure.stations[0].seed.electricity = 2;
    advance(&mut w, 1000);
    assert_eq!(w.infrastructure.stations[0].jobs[0].id, job);
    assert!(w.infrastructure.stations[0].jobs[0].report.is_some());
    assert_eq!(w.infrastructure.stations[0].seed.materials.water, 0);
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 0);
    assert_eq!(
        w.events
            .iter()
            .filter(|e| e.kind == "compute_quantum")
            .count(),
        3
    );
    let report = w
        .events
        .iter()
        .find(|e| e.kind == "compute_completed")
        .unwrap();
    assert_eq!(report.data["output"]["projected_stock"], 6);
    assert_eq!(report.data["record"]["origin"], report.id);
    let before = state(&w);
    advance(&mut w, 1000);
    assert_eq!(state(&w), before);
}

#[test]
fn compute_reload_fractional_work_and_station_fifo_are_deterministic() {
    let mut w = world();
    let first = submit(&mut w, 2);
    let second = submit(&mut w, 3);
    advance(&mut w, 1333);
    let saved = serde_json::to_vec(&w).unwrap();
    let mut loaded: World = serde_json::from_slice(&saved).unwrap();
    advance(&mut w, 4667);
    for _ in 0..93 {
        advance(&mut loaded, 50)
    }
    advance(&mut loaded, 17);
    assert_eq!(state(&w), state(&loaded));
    let events: Vec<_> = w
        .events
        .iter()
        .filter(|e| e.kind == "compute_quantum")
        .map(|e| {
            (
                e.data["job"].as_u64().unwrap(),
                e.data["progress"].as_u64().unwrap(),
                e.data["quantum_at_ms"].as_u64().unwrap(),
            )
        })
        .collect();
    assert_eq!(
        events,
        vec![
            (first, 1, 1000),
            (first, 2, 2000),
            (first, 3, 3000),
            (second, 1, 4000),
            (second, 2, 5000),
            (second, 3, 6000)
        ]
    );
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 18);
    assert_eq!(w.infrastructure.stations[0].seed.materials.water, 14);
}

#[test]
fn revoked_or_disabled_jobs_hold_fifo_until_restored_or_explicitly_cancelled() {
    let mut w = world();
    let first = submit(&mut w, 2);
    let second = submit(&mut w, 3);
    advance(&mut w, 1000);
    apply(
        &mut w,
        1,
        Op::SetAccess {
            station: 1,
            actor: 2,
            use_allowed: false,
            maintain: true,
            admin: false,
        },
    )
    .unwrap();
    advance(&mut w, 2000);
    assert_eq!(w.infrastructure.stations[0].jobs[0].progress, 1);
    assert_eq!(w.infrastructure.stations[0].jobs[1].progress, 0);
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 28);
    assert!(apply(
        &mut w,
        3,
        Op::CancelJob {
            station: 1,
            job: first
        }
    )
    .is_err());
    apply(
        &mut w,
        1,
        Op::CancelJob {
            station: 1,
            job: first,
        },
    )
    .unwrap();
    advance(&mut w, 1000);
    assert_eq!(w.infrastructure.stations[0].jobs[1].progress, 1);
    apply(
        &mut w,
        1,
        Op::SetEnabled {
            station: 1,
            enabled: false,
        },
    )
    .unwrap();
    advance(&mut w, 1500);
    assert_eq!(w.infrastructure.stations[0].jobs[1].progress, 1);
    apply(
        &mut w,
        1,
        Op::SetEnabled {
            station: 1,
            enabled: true,
        },
    )
    .unwrap();
    advance(&mut w, 1500);
    assert_eq!(w.infrastructure.stations[0].jobs[1].progress, 3);
    assert_eq!(w.infrastructure.stations[0].jobs[1].id, second);
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 22);
    assert_eq!(w.infrastructure.stations[0].seed.materials.water, 16);
}

#[test]
fn terminal_report_is_private_physical_copy_with_explicit_local_retrieval_and_sources() {
    let mut s = scenario();
    s.knowledge.insert(
        2,
        vec![knowledge::RecordSeed {
            id: "private-assumption".into(),
            topic: "Supply assumption".into(),
            text: "My private estimate is sensitive-alpha".into(),
            location: None,
            confidence: 60,
        }],
    );
    let mut w = World::new("private-compute".into(), s).unwrap();
    let mut supplied = input();
    supplied.sources = vec!["private-assumption".into()];
    supplied.stock = 456789;
    assert!(apply(
        &mut w,
        1,
        Op::SubmitJob {
            station: 1,
            input: supplied.clone()
        }
    )
    .is_err());
    apply(
        &mut w,
        2,
        Op::SubmitJob {
            station: 1,
            input: supplied,
        },
    )
    .unwrap();
    let other = w.infrastructure_facts(1).to_string();
    assert!(!other.contains("private-assumption"));
    assert!(!other.contains("456789"));
    assert!(!other.contains("sensitive-alpha"));
    w.players[1].position = 2;
    let memories = w.players[1].memories.clone();
    advance(&mut w, 3000);
    assert_eq!(
        serde_json::to_value(&w.players[1].memories).unwrap(),
        serde_json::to_value(memories).unwrap()
    );
    assert_eq!(w.players[1].knowledge.len(), 1);
    assert_eq!(w.infrastructure_facts(2)["stations"], json!([]));
    assert!(apply(&mut w, 2, Op::RetrieveJob { station: 1, job: 1 }).is_err());
    assert!(apply(&mut w, 1, Op::RetrieveJob { station: 1, job: 1 }).is_err());
    w.players[1].position = 0;
    apply(&mut w, 2, Op::RetrieveJob { station: 1, job: 1 }).unwrap();
    let held = &w.players[1].knowledge[1];
    assert!(held.record.text.contains("456789"));
    assert!(held.record.text.contains("private-assumption"));
    assert!(held.interpretation.is_none());
    assert!(held.interpreted_source.is_none());
    assert_eq!(held.record.location, None);
    let id = held.record.id.clone();
    apply(&mut w, 2, Op::RetrieveJob { station: 1, job: 1 }).unwrap();
    assert_eq!(
        w.players[1]
            .knowledge
            .iter()
            .filter(|h| h.record.id == id)
            .count(),
        1
    );
    let ev = w
        .events
        .iter()
        .find(|e| e.kind == "compute_completed")
        .unwrap();
    assert_eq!(ev.data["record"]["id"], id);
    assert!(w.players[0].knowledge.is_empty());
}

#[test]
fn authorized_computation_survives_owners_death_without_inheritance_or_dead_perception() {
    let mut w = world();
    submit(&mut w, 2);
    w.players[1].health = 0;
    let count = w.players[1].memories.len();
    advance(&mut w, 3000);
    assert!(w.infrastructure.stations[0].jobs[0].report.is_some());
    assert_eq!(w.players[1].memories.len(), count);
    assert!(apply(&mut w, 2, Op::RetrieveJob { station: 1, job: 1 }).is_err());
    assert!(apply(&mut w, 1, Op::RetrieveJob { station: 1, job: 1 }).is_err());
    assert!(w.players.iter().all(|p| p.knowledge.is_empty()));
}

#[test]
fn electric_metabolism_eating_rest_and_controller_changes_do_not_mint_power() {
    let mut outcomes = vec![];
    for controller in [Controller::Human, Controller::Ai] {
        let mut s = scenario();
        s.players[0].controller = controller;
        s.players[0].energy = 10;
        let mut w = World::new("body-parity".into(), s).unwrap();
        w.enable_participants();
        install(&mut w, 1, Action::new(Skill::Eat));
        w.advance_ms(50);
        assert_eq!(w.players[0].food, 10);
        assert_eq!(w.infrastructure.bodies[&1].charge, 20);
        install(&mut w, 1, Action::new(Skill::Rest));
        w.advance_ms(2500);
        assert_eq!(w.infrastructure.bodies[&1].charge, 19);
        assert_eq!(w.players[0].hunger, 0);
        assert!(w.players[0].energy > 10);
        install(
            &mut w,
            1,
            action(Op::Charge {
                station: 1,
                amount: 10,
            }),
        );
        w.advance_ms(50);
        assert_eq!(w.infrastructure.bodies[&1].charge, 29);
        assert_eq!(w.infrastructure.stations[0].seed.electricity, 20);
        outcomes.push((
            w.players[0].health,
            w.players[0].energy,
            w.players[0].food,
            w.infrastructure.bodies[&1].charge,
            w.infrastructure.stations[0].seed.electricity,
        ));
        assert!(!w.events.iter().any(|e| e.kind == "script_tick_failed"));
    }
    assert_eq!(outcomes[0], outcomes[1]);
}

#[test]
fn charge_care_requires_real_local_dependent_and_a_substantial_transfer() {
    let mut w = world();
    w.lifecycle.get_mut(&1).unwrap().dependent = true;
    apply(
        &mut w,
        2,
        Op::SupportCharge {
            station: 1,
            target: 1,
            amount: 1,
        },
    )
    .unwrap();
    assert_eq!(w.lifecycle[&1].care_meals, 0);
    apply(
        &mut w,
        2,
        Op::SupportCharge {
            station: 1,
            target: 1,
            amount: 20,
        },
    )
    .unwrap();
    assert_eq!(w.lifecycle[&1].care_meals, 1);
    assert_eq!(w.lifecycle[&1].care[0].caregiver, 2);
    assert_eq!(w.infrastructure.bodies[&1].charge, 41);
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 9);
    assert_eq!(w.players[1].food, 10);
    w.players[0].position = 2;
    assert!(apply(
        &mut w,
        2,
        Op::SupportCharge {
            station: 1,
            target: 1,
            amount: 1
        }
    )
    .is_err());
    w.players[0].position = 0;
    w.lifecycle.get_mut(&1).unwrap().dependent = false;
    assert!(apply(
        &mut w,
        2,
        Op::SupportCharge {
            station: 1,
            target: 1,
            amount: 1
        }
    )
    .is_err());
}

#[test]
fn seed_bounds_and_unperceived_grants_do_not_create_access_capabilities() {
    let mut s = scenario();
    s.players[2].position = 10;
    s.infrastructure.as_mut().unwrap().stations[0]
        .access
        .remove(&3);
    let mut w = World::new("unseen-access".into(), s.clone()).unwrap();
    assert!(apply(
        &mut w,
        1,
        Op::SetAccess {
            station: 1,
            actor: 3,
            use_allowed: true,
            maintain: false,
            admin: false
        }
    )
    .is_err());
    assert!(apply(
        &mut w,
        1,
        Op::SetAccess {
            station: 1,
            actor: 999,
            use_allowed: true,
            maintain: false,
            admin: false
        }
    )
    .is_err());
    s.infrastructure.as_mut().unwrap().stations[0].electricity = -1;
    assert!(World::new("bad-stock".into(), s).is_err());
    let mut s = scenario();
    s.infrastructure.as_mut().unwrap().balance.compute_water = 0;
    assert!(World::new("free-cooling".into(), s).is_err());
}

#[test]
fn only_unfunded_support_pulses_harm_electric_bodies_and_reload_preserves_debt() {
    let mut s = scenario();
    s.infrastructure
        .as_mut()
        .unwrap()
        .bodies
        .get_mut(&1)
        .unwrap()
        .initial_charge = 1;
    let mut w = World::new("last-funded-pulse".into(), s.clone()).unwrap();
    w.enable_participants();
    install(&mut w, 1, Action::new(Skill::Wait));
    w.advance_ms(2500);
    assert_eq!(w.infrastructure.bodies[&1].charge, 0);
    assert_eq!(w.players[0].health, 100);
    w.advance_ms(2500);
    assert_eq!(w.players[0].health, 92);
    let mut coarse = World::new("batched-support".into(), s).unwrap();
    coarse.enable_participants();
    install(&mut coarse, 1, Action::new(Skill::Wait));
    coarse.advance_ms(7500);
    assert_eq!(coarse.players[0].health, 84);
    let mut debt = world();
    debt.infrastructure.bodies.get_mut(&1).unwrap().charge = 1;
    debt.consume_body_charge(1, 3, 1).unwrap();
    assert_eq!(debt.body_support_context(1)["unpaid_support_pulses"], 2);
    debt = serde_json::from_slice(&serde_json::to_vec(&debt).unwrap()).unwrap();
    apply(
        &mut debt,
        1,
        Op::Charge {
            station: 1,
            amount: 10,
        },
    )
    .unwrap();
    assert_eq!(
        debt.body_support_context(1)["unpaid_support_pulses"],
        2,
        "later charge cannot erase previously unpaid metabolism"
    );
    debt.clear_body_support_deficit(1);
    assert_eq!(debt.body_support_context(1)["unpaid_support_pulses"], 0);
}

#[test]
fn infrastructure_effect_batch_rolls_back_resources_job_ids_and_observations() {
    let mut w = world();
    let initial = state(&w);
    let mut definition =
        w.scripts.history["infrastructure"][&w.scripts.active["infrastructure"]].clone();
    definition.revision += 1;
    definition.source="fn validate(c) { \"\" } fn step(c) { law::done([#{kind:\"infrastructure\",operation:c.action.infrastructure},#{kind:\"actor\",fields:#{health:0}}]) }".into();
    w.stage_scripts_by_operator(scripting::Update {
        api_version: scripting::API_VERSION,
        expected_revision: w.scripts.revision,
        definitions: vec![definition],
    })
    .unwrap();
    w.advance_ms(1);
    install(
        &mut w,
        1,
        action(Op::SubmitJob {
            station: 1,
            input: input(),
        }),
    );
    w.advance_ms(1);
    let mut actual = state(&w);
    let mut expected = initial;
    actual["stations"][0]["generation_remainder_ms"] = json!(0);
    actual["stations"][0]["compute_remainder_ms"] = json!(0);
    expected["stations"][0]["generation_remainder_ms"] = json!(0);
    expected["stations"][0]["compute_remainder_ms"] = json!(0);
    assert_eq!(actual, expected);
    assert!(!w.events.iter().any(|e| e.kind == "compute_submitted"));
    assert!(w
        .events
        .iter()
        .any(|e| e.kind == "script_error" && e.data["effects_committed"] == false));
}

#[test]
fn generator_cap_spill_disabled_time_and_multiple_stations_account_separately() {
    let mut s = scenario();
    let station = &mut s.infrastructure.as_mut().unwrap().stations[0];
    station.modules.push(Module::Generator);
    station.electricity = 99;
    let mut second = station.clone();
    second.id = 2;
    second.electricity = 10;
    second.materials.water = 0;
    s.infrastructure.as_mut().unwrap().stations.push(second);
    let mut w = World::new("two-stations".into(), s).unwrap();
    submit(&mut w, 2);
    apply(
        &mut w,
        2,
        Op::SubmitJob {
            station: 2,
            input: input(),
        },
    )
    .unwrap();
    advance(&mut w, 1000);
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 98);
    assert_eq!(w.infrastructure.stations[0].jobs[0].progress, 1);
    assert_eq!(w.infrastructure.stations[1].jobs[0].progress, 0);
    assert_eq!(w.infrastructure.stations[1].seed.electricity, 13);
    assert_eq!(
        w.events
            .iter()
            .find(|e| e.kind == "electricity_generated" && e.data["station"] == 1)
            .unwrap()
            .data["spilled"],
        2
    );
    apply(
        &mut w,
        1,
        Op::SetEnabled {
            station: 1,
            enabled: false,
        },
    )
    .unwrap();
    advance(&mut w, 5000);
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 98);
    apply(
        &mut w,
        1,
        Op::SetEnabled {
            station: 1,
            enabled: true,
        },
    )
    .unwrap();
    advance(&mut w, 1000);
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 98);
    assert_eq!(
        w.infrastructure.stations[0].jobs[0].progress, 2,
        "disabled time does not accumulate work credit"
    );
}

#[test]
fn infrastructure_scope_survives_reload_and_coincident_foreign_positions() {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/luna-arena-matrix.json")).unwrap();
    s.starting_behaviors.clear();
    let mut infra = scenario().infrastructure.unwrap();
    infra.stations[0].position = s.players[0].position;
    infra.stations[0].access.retain(|a, _| *a == 2);
    s.infrastructure = Some(infra);
    let mut w = World::new("infrastructure-scopes".into(), s).unwrap();
    w = serde_json::from_slice(&serde_json::to_vec(&w).unwrap()).unwrap();
    w.players[2].position = w.players[0].position;
    assert!(w.infrastructure_facts(3)["stations"]
        .as_array()
        .unwrap()
        .is_empty());
    assert!(apply(
        &mut w,
        3,
        Op::TakeMaterial {
            station: 1,
            material: Material::Parts,
            amount: 1
        }
    )
    .is_err());
    assert!(apply(
        &mut w,
        1,
        Op::SetAccess {
            station: 1,
            actor: 3,
            use_allowed: true,
            maintain: false,
            admin: false
        }
    )
    .is_err());
    assert_eq!(w.infrastructure.stations[0].seed.materials.parts, 5);
}
