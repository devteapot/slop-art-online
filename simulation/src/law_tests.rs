use super::*;
use infrastructure::{ForecastInput, InfrastructureOperation as Op};
use law_research::LawCase;
use laws::{LawDraft, LawRef, LawRevision, LawScope};
use participant::{Command, Request, API_VERSION};
use scripting::Effect;
// All authored algorithms and cases below are deterministic tooling fixtures.
fn territory(id: &str) -> LawScope {
    LawScope::Territory { region: id.into() }
}
fn world() -> World {
    let mut s: Scenario =
        serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    s.map = Some(spatial::Grid {
        width: 4,
        height: 2,
        blocked: Default::default(),
        bounds: None,
    });
    s.arenas.clear();
    s.weather = None;
    s.max_ticks = 10000;
    s.starting_behaviors.clear();
    s.knowledge.clear();
    s.lifecycle = None;
    for p in &mut s.players {
        p.position = 0;
        p.health = 100;
        p.hunger = 0;
        p.energy = 100;
        p.food = 10;
        p.beliefs.clear();
        p.controller = Controller::Human;
    }
    s.sites = vec![
        Site {
            position: 0,
            food: 20,
            hazard: 0,
            shelter: 0,
        },
        Site {
            position: 3,
            food: 20,
            hazard: 0,
            shelter: 0,
        },
    ];
    s.food_sources = vec![
        ecology::FoodSource {
            position: 0,
            interval_ms: 2500,
            amount: 1,
            capacity: 100,
        },
        ecology::FoodSource {
            position: 3,
            interval_ms: 2500,
            amount: 1,
            capacity: 100,
        },
    ];
    s.archives = vec![knowledge::ArchiveSeed {
        id: 7,
        position: 0,
        label: "Law library".into(),
        capacity: 32,
    }];
    s.society = Some(society::SocietySeed {
        version: 1,
        regions: vec![
            society::Region {
                id: "west".into(),
                label: "West".into(),
                kind: society::RegionKind::Homeland,
                bounds: spatial::Bounds {
                    x: 0,
                    y: 0,
                    width: 2,
                    height: 2,
                },
                territorial_editors: vec![1],
                priority: 0,
            },
            society::Region {
                id: "east".into(),
                label: "East".into(),
                kind: society::RegionKind::Homeland,
                bounds: spatial::Bounds {
                    x: 2,
                    y: 0,
                    width: 2,
                    height: 2,
                },
                territorial_editors: vec![2],
                priority: 0,
            },
        ],
        organizations: vec![],
        offices: vec![society::Office {
            id: "council".into(),
            label: "Council seat".into(),
            region: "west".into(),
            holder: 3,
            represented_group: None,
        }],
    });
    s.infrastructure=Some(serde_json::from_value(json!({"version":1,"stations":[{"id":1,"owner":1,"position":0,"label":"Research","electricity":1000,"electricity_capacity":1000,"materials":{"water":1000},"modules":["terminal"],"access":{"2":{"use_allowed":true},"3":{"use_allowed":true}},"generation_period_ms":1000,"generation_amount":1},{"id":2,"owner":2,"position":3,"label":"East research","electricity":1000,"electricity_capacity":1000,"materials":{"water":1000},"modules":["terminal"],"access":{"1":{"use_allowed":true},"3":{"use_allowed":true}},"generation_period_ms":1000,"generation_amount":1}]})).unwrap());
    let mut w = World::new("law-fixture".into(), s).unwrap();
    w.enable_participants();
    w
}
fn draft(source: &str) -> LawDraft {
    LawDraft {
        interface_version: 1,
        source: source.into(),
    }
}
fn case(hook: &str, input: Value, expected: Value) -> LawCase {
    LawCase {
        hook: hook.into(),
        input,
        expected,
    }
}
fn action(op: Op) -> Action {
    Action {
        infrastructure: Some(op),
        ..Action::new(Skill::Infrastructure)
    }
}
fn apply(w: &mut World, actor: u32, op: Op) -> Result<(), String> {
    let mut next = w.clone();
    let i = next.idx(actor)?;
    let a = action(op.clone());
    let effect = Effect::Infrastructure { operation: op };
    next.validate_script_effect(i, &a, &effect)?;
    let cause = next.event(Some(actor), "law_test_input", vec![], json!({}));
    next.apply_script_effect(i, cause, effect)?;
    *w = next;
    Ok(())
}
fn fixture(w: &mut World, scope: LawScope, source: &str) {
    let revision = w.law_scope_revision(&scope) + 1;
    let artifact = laws::compile(&draft(source)).unwrap();
    let reference = LawRef {
        scope: scope.clone(),
        revision,
    };
    w.laws.active.insert(scope.key(), revision);
    w.laws.history.entry(scope.key()).or_default().insert(
        revision,
        LawRevision {
            reference,
            artifact,
            author: 1,
            origin: 1,
            installed_ms: w.timing.time_ms,
        },
    );
}
fn finish(w: &mut World, id: u64) -> (String, String) {
    for _ in 0..30 {
        if w.infrastructure.stations[0]
            .jobs
            .iter()
            .find(|j| j.id == id)
            .unwrap()
            .report
            .is_some()
        {
            break;
        }
        w.advance_ms(1000);
    }
    let j = w.infrastructure.stations[0]
        .jobs
        .iter()
        .find(|j| j.id == id)
        .unwrap();
    assert!(j.report.is_some(), "{:?}", w.events.last());
    (
        j.law_work.as_ref().unwrap().program_record.id.clone(),
        j.report.as_ref().unwrap().id.clone(),
    )
}
fn assess(w: &mut World, actor: u32, record: &str) {
    let i = w.idx(actor).unwrap();
    let source = w.players[i]
        .knowledge
        .iter()
        .find(|h| h.record.id == record)
        .unwrap()
        .source;
    let p = &w.participants[&actor];
    let result = w
        .participant_apply(
            actor,
            Request {
                api_version: API_VERSION.into(),
                request_id: format!("assess-{}", w.next_event),
                control_epoch: p.control_epoch,
                command: Command::Reflect {
                    expected_revision: p.learning_revision,
                    observed_cursor: p.cursor,
                    reflections: vec![Reflection {
                        source,
                        interpretation: "I assessed the exact experiment and its limited evidence."
                            .into(),
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
    assert!(result.ok, "{:?}", result.error);
}
fn prototype(
    w: &mut World,
    actor: u32,
    scope: LawScope,
    source: &str,
    cases: Vec<LawCase>,
) -> (String, String) {
    let id = w.infrastructure.next_job;
    apply(
        w,
        actor,
        Op::PrototypeLaw {
            station: 1,
            scope,
            draft: draft(source),
            cases,
            sources: vec![],
        },
    )
    .unwrap();
    let records = finish(w, id);
    apply(w, actor, Op::RetrieveReady { station: 1 }).unwrap();
    records
}
fn install(
    w: &mut World,
    actor: u32,
    scope: LawScope,
    record: &str,
    experiment: Option<&str>,
) -> Result<(), String> {
    let i = w.idx(actor)?;
    let binding = w.binding_for_scope(i, &scope)?;
    let revision = w.law_scope_revision(&scope);
    apply(
        w,
        actor,
        Op::InstallLaw {
            station: 1,
            scope,
            record: record.into(),
            experiment_record: experiment.map(str::to_owned),
            expected_revision: revision,
            expected_binding: binding.digest,
        },
    )
}
fn bootstrap(w: &mut World, actor: u32) {
    let id = w.infrastructure.next_job;
    apply(
        w,
        actor,
        Op::SubmitJob {
            station: 1,
            input: ForecastInput {
                stock: 10,
                inflow_per_min: 1,
                demand_per_min: 2,
                horizon_ms: 60000,
                sources: vec![],
            },
        },
    )
    .unwrap();
    for _ in 0..20 {
        if w.infrastructure.stations[0]
            .jobs
            .iter()
            .find(|j| j.id == id)
            .unwrap()
            .report
            .is_some()
        {
            break;
        }
        w.advance_ms(1000);
    }
    let record = w.infrastructure.stations[0]
        .jobs
        .iter()
        .find(|j| j.id == id)
        .unwrap()
        .report
        .as_ref()
        .unwrap()
        .id
        .clone();
    apply(w, actor, Op::RetrieveReady { station: 1 }).unwrap();
    assess(w, actor, &record);
}
fn decision(w: &mut World, actor: u32, a: Action) {
    let i = w.idx(actor).unwrap();
    let p = &w.participants[&actor];
    let request = Request {
        api_version: API_VERSION.into(),
        request_id: format!("law-action-{}", w.next_event),
        control_epoch: p.control_epoch,
        command: Command::ReplaceTree {
            expected_revision: w.players[i].generation,
            reason: "deterministic law integration fixture".into(),
            tree: Node::Once {
                child: Box::new(Node::Action { action: a }),
            },
        },
    };
    let receipt = w.participant_apply(actor, request).unwrap();
    assert!(receipt.ok, "{:?}", receipt.error);
}

#[test]
fn compiler_exposes_only_bounded_real_hooks() {
    for src in [
        "let x=1; fn cost(x){1}",
        "fn system_periods_ms(x){#{needs_ms:1,hazard_ms:1}}",
        "fn validate_common(x){\"\"}",
        "fn authorize_update(x){true}",
        "fn helper(x){x} fn cost(x){helper(2)}",
        "private fn cost(x){1}",
        "fn cost(x,y){1}",
        "fn cost(x){eval(\"1\")}",
    ] {
        assert!(laws::compile(&draft(src)).is_err(), "{src}");
    }
    let a = laws::compile(&draft(
        "fn cost(x){let total=0;for n in 0..4 {total+=n;} bounded(total,0,100)}",
    ))
    .unwrap();
    assert_eq!(a.hooks, vec!["cost"]);
    let mut b = a.clone();
    b.source.push(' ');
    assert!(laws::validate(&b).is_err());
    assert!(laws::compile(&draft(&"x".repeat(8193))).is_err());
    assert!(laws::validate_output("metabolism", &json!({"hunger":5,"fear":0})).is_ok());
    assert!(laws::validate_output("metabolism", &json!({"hunger":-1,"fear":0})).is_err());
}
#[test]
fn cells_drive_physiology_production_cost_and_universal_precedence() {
    let mut w = world();
    w.players[1].position = 3;
    fixture(&mut w,territory("west"),"fn metabolism(p){#{hunger:bounded(p.hunger+7*p.pulses,0,100),fear:0}} fn food_renewal(c){3*c.pulses} fn cost(s){2}");
    w.advance_ms(2500);
    assert_eq!(w.players[0].hunger, 7);
    assert_eq!(w.players[1].hunger, 2);
    assert_eq!(w.sites[0].food, 23);
    assert_eq!(w.sites[1].food, 21);
    decision(&mut w, 1, Action::new(Skill::Gather));
    w.advance_ms(1000);
    assert_eq!(
        w.players[0].energy,
        98,
        "{:?}",
        w.events
            .iter()
            .filter(|e| e.kind == "script_error")
            .collect::<Vec<_>>()
    );
    assert_eq!(w.players[0].food, 11);
    fixture(&mut w, LawScope::Universal, "fn cost(s){9}");
    let a: i32 = w.law_at(0, "cost", json!("gather")).unwrap();
    let b: i32 = w.law_at(3, "cost", json!("gather")).unwrap();
    assert_eq!((a, b), (9, 9));
    assert!(!w
        .events
        .iter()
        .any(|e| e.kind == "script_tick_failed" || e.kind == "script_error"));
}
#[test]
fn overlap_priority_area_and_id_are_deterministic() {
    let mut w = world();
    let mut r = w.initial.society.as_ref().unwrap().regions[0].clone();
    r.id = "all".into();
    r.bounds.width = 4;
    w.initial.society.as_mut().unwrap().regions.push(r);
    fixture(&mut w, territory("all"), "fn cost(s){3}");
    fixture(&mut w, territory("west"), "fn cost(s){5}");
    assert_eq!(w.law_at::<i32>(0, "cost", json!("gather")).unwrap(), 5);
    w.initial.society.as_mut().unwrap().regions[2].priority = 1;
    assert_eq!(w.law_at::<i32>(0, "cost", json!("gather")).unwrap(), 3);
    w.initial.society.as_mut().unwrap().regions[2].priority = 0;
    w.initial.society.as_mut().unwrap().regions[2].bounds.width = 2;
    assert_eq!(w.law_at::<i32>(0, "cost", json!("gather")).unwrap(), 3);
}
#[test]
fn local_god_paid_authoring_installation_and_death_persistence() {
    let mut w = world();
    let (code, proof) = prototype(
        &mut w,
        1,
        territory("west"),
        "fn cost(s){2}",
        vec![case("cost", json!("gather"), json!(2))],
    );
    assert!(
        w.players[0]
            .knowledge
            .iter()
            .find(|h| h.record.id == proof)
            .unwrap()
            .record
            .law_experiment
            .as_ref()
            .unwrap()
            .successful
    );
    assert!(!w.players[0]
        .knowledge
        .iter()
        .any(|h| h.interpreted_source.is_some()));
    install(&mut w, 1, territory("west"), &code, None).unwrap();
    assert_eq!(w.law_scope_revision(&territory("west")), 0);
    assert!(install(&mut w, 1, territory("west"), &code, None)
        .unwrap_err()
        .contains("pending"));
    w.advance_ms(50);
    assert_eq!(w.law_scope_revision(&territory("west")), 1);
    w.players[0].health = 0;
    w.players[0].knowledge.clear();
    apply(
        &mut w,
        2,
        Op::InspectInstalledLaw {
            station: 1,
            scope: territory("west"),
        },
    )
    .unwrap();
    assert!(w.players[1]
        .memories
        .iter()
        .any(|m| m.kind == "law_inspected"
            && m.content["law_program"]["source"].as_str() == Some("fn cost(s){2}")));
    let w: World = serde_json::from_value(json!(w)).unwrap();
    assert_eq!(w.law_at::<i32>(0, "cost", json!("gather")).unwrap(), 2);
}
#[test]
fn universal_requires_own_assessed_exact_experiment_not_council_or_local_escalation() {
    let mut w = world();
    assert!(apply(
        &mut w,
        3,
        Op::PrototypeLaw {
            station: 1,
            scope: LawScope::Universal,
            draft: draft("fn cost(s){3}"),
            cases: vec![case("cost", json!("gather"), json!(3))],
            sources: vec![]
        }
    )
    .is_err());
    fixture(&mut w, territory("west"), "fn authorize_law_edit(c){true}");
    bootstrap(&mut w, 3);
    let (code, proof) = prototype(
        &mut w,
        3,
        LawScope::Universal,
        "fn cost(s){3}",
        vec![case("cost", json!("gather"), json!(3))],
    );
    assert!(install(&mut w, 3, LawScope::Universal, &code, None).is_err());
    assess(&mut w, 3, &proof);
    install(&mut w, 3, LawScope::Universal, &code, Some(&proof)).unwrap();
    w.advance_ms(50);
    assert_eq!(w.law_scope_revision(&LawScope::Universal), 1);
    assert_eq!(w.law_at::<i32>(3, "cost", json!("gather")).unwrap(), 3);
}
#[test]
fn taught_code_needs_personal_practice_private_cases_do_not_travel() {
    let mut w = world();
    let (code, proof) = prototype(
        &mut w,
        1,
        territory("west"),
        "fn cost(s){4}",
        vec![case("cost", json!("private_987654"), json!(4))],
    );
    let record = w.players[0]
        .knowledge
        .iter()
        .find(|h| h.record.id == code)
        .unwrap()
        .record
        .clone();
    let mut a = Action::new(Skill::Teach);
    a.target = Some(2);
    a.record = Some(code.clone());
    w.validate_knowledge_effect(
        0,
        &a,
        &Effect::Teach {
            target: 2,
            record: code.clone(),
        },
    )
    .unwrap();
    w.apply_knowledge_effect(
        0,
        1,
        &Effect::Teach {
            target: 2,
            record: code.clone(),
        },
    )
    .unwrap();
    assert!(w.players[1]
        .knowledge
        .iter()
        .all(|h| h.record.law_experiment.is_none()));
    assert!(record.law_experiment.is_none());
    for i in [1, 2] {
        assert!(!serde_json::to_string(&w.context(i))
            .unwrap()
            .contains("private_987654"));
    }
    assess(&mut w, 2, &code);
    let id = w.infrastructure.next_job;
    apply(
        &mut w,
        2,
        Op::PracticeLaw {
            station: 1,
            scope: LawScope::Universal,
            record: code.clone(),
            cases: vec![case("cost", json!("gather"), json!(4))],
            sources: vec![],
        },
    )
    .unwrap();
    let (_, own) = finish(&mut w, id);
    apply(&mut w, 2, Op::RetrieveReady { station: 1 }).unwrap();
    assert!(install(&mut w, 2, LawScope::Universal, &code, Some(&proof)).is_err());
    assess(&mut w, 2, &own);
    install(&mut w, 2, LawScope::Universal, &code, Some(&own)).unwrap();
}
#[test]
fn failed_experiments_are_paid_and_invalid_source_has_no_effect() {
    let mut w = world();
    let before = json!(w.infrastructure);
    let bad = apply(
        &mut w,
        1,
        Op::PrototypeLaw {
            station: 1,
            scope: territory("west"),
            draft: draft("fn cost(s){"),
            cases: vec![case("cost", json!("gather"), json!(1))],
            sources: vec![],
        },
    );
    assert!(bad.is_err());
    assert_eq!(before, json!(w.infrastructure));
    let (code, proof) = prototype(
        &mut w,
        1,
        territory("west"),
        "fn cost(s){loop {}}",
        vec![case("cost", json!("gather"), json!(1))],
    );
    let e = w.players[0]
        .knowledge
        .iter()
        .find(|h| h.record.id == proof)
        .unwrap()
        .record
        .law_experiment
        .as_ref()
        .unwrap();
    assert!(!e.successful);
    assert!(e.paid_quanta > 0);
    assert!(e.results[0].is_err());
    assert!(!w.events.iter().any(|e| e.kind == "script_tick_failed"));
    install(&mut w, 1, territory("west"), &code, None).unwrap();
    w.advance_ms(50);
    assert_eq!(w.law_at::<i32>(0, "cost", json!("gather")).unwrap(), 4);
    assert_eq!(w.laws.faults.lock().len(), 1);
}
#[test]
fn bad_hook_quarantine_preserves_other_hooks_and_regions() {
    let mut w = world();
    w.players[1].position = 3;
    fixture(
        &mut w,
        territory("west"),
        "fn metabolism(p){throw \"test fault\"} fn food_renewal(c){5*c.pulses}",
    );
    let before = w.timing.time_ms;
    w.advance_ms(2500);
    assert_eq!(w.timing.time_ms, before + 2500);
    assert_eq!(w.players[0].hunger, 2);
    assert_eq!(w.players[1].hunger, 2);
    assert_eq!(w.sites[0].food, 25);
    assert_eq!(w.laws.faults.lock()[0].hook, "metabolism");
    assert!(w.players[0].memories.iter().any(|m| m.kind == "law_fault"));
    assert!(!w.players[1].memories.iter().any(|m| m.kind == "law_fault"));
    assert!(!w.events.iter().any(|e| e.kind == "script_tick_failed"));
    let count = w.laws.faults.lock().len();
    w.advance_ms(2500);
    assert_eq!(w.laws.faults.lock().len(), count);
}
#[test]
fn stationary_action_pins_formula_movement_rebinds_and_current_law_revokes() {
    let mut w = world();
    fixture(
        &mut w,
        territory("west"),
        "fn action_interval_ms(s){if s==\"rest\"{1000}else{250}}",
    );
    w.players[0].energy = 10;
    let mut rest = Action::new(Skill::Rest);
    rest.duration = 3;
    decision(&mut w, 1, rest);
    w.advance_ms(500);
    fixture(&mut w, territory("west"), "fn action_interval_ms(s){10000}");
    w.advance_ms(500);
    assert_eq!(
        w.players[0].energy,
        22,
        "{:?}",
        w.events
            .iter()
            .filter(|e| e.kind == "script_error")
            .collect::<Vec<_>>()
    );
    assert_eq!(w.players[0].execution.as_ref().unwrap().remaining, 2);
    // Fresh move crosses west/east; each cell uses the new cell's formula next time.
    let mut m = world();
    fixture(&mut m, territory("west"), "fn cost(s){1}");
    fixture(&mut m, territory("east"), "fn cost(s){7}");
    let mut a = Action::new(Skill::Move);
    a.destination = Some(3);
    decision(&mut m, 1, a);
    for _ in 0..3 {
        m.advance_ms(250);
    }
    assert_eq!(m.players[0].position, 3);
    assert_eq!(m.players[0].energy, 91);
    let mut q = world();
    let mut rest = Action::new(Skill::Rest);
    rest.duration = 3;
    q.players[0].energy = 10;
    decision(&mut q, 1, rest);
    q.advance_ms(1000);
    fixture(&mut q, territory("west"), "fn authorize_effect(c){false}");
    q.advance_ms(1500);
    assert_eq!(q.players[0].energy, 10);
    assert!(q.events.iter().any(|e| e.kind == "script_error"));
}
#[test]
fn stale_binding_and_source_hash_cannot_reuse_old_proof() {
    let mut w = world();
    bootstrap(&mut w, 2);
    let (code, proof) = prototype(
        &mut w,
        2,
        LawScope::Universal,
        "fn cost(s){3}",
        vec![case("cost", json!("gather"), json!(3))],
    );
    assess(&mut w, 2, &proof);
    fixture(&mut w, LawScope::Universal, "fn food_renewal(c){1}");
    assert!(install(&mut w, 2, LawScope::Universal, &code, Some(&proof)).is_err());
    let binding = w.binding_for_scope(1, &LawScope::Universal).unwrap();
    let result = apply(
        &mut w,
        2,
        Op::InstallLaw {
            station: 1,
            scope: LawScope::Universal,
            record: code,
            experiment_record: Some(proof),
            expected_revision: 0,
            expected_binding: binding.digest,
        },
    );
    assert!(result.unwrap_err().contains("stale"));
}

#[test]
fn damage_uses_current_victim_law_and_crossing_checks_destination_permission() {
    let mut w = world();
    fixture(&mut w, territory("east"), "fn authorize_effect(c){false}");
    let mut a = Action::new(Skill::Move);
    a.destination = Some(3);
    decision(&mut w, 1, a);
    w.advance_ms(250);
    assert_eq!(w.players[0].position, 1);
    w.advance_ms(250);
    assert_eq!(w.players[0].position, 1);
    assert_eq!(w.players[0].energy, 99);
    assert!(w.events.iter().any(|e| e.kind == "script_error"
        && e.data["error"]
            .as_str()
            .is_some_and(|s| s.contains("destination"))));
    let denied = w
        .events
        .iter()
        .rev()
        .find(|e| e.kind == "script_error")
        .unwrap();
    assert_eq!(denied.data["category"], "law_authorization_denied");
    assert_eq!(denied.data["destination"], 2);
    assert_eq!(
        denied.data["destination_binding"]["overlays"][0]["scope"]["region"],
        "east"
    );
    // The survivor's already-running rest retains its interval but damage uses new local policy.
    let mut w = world();
    fixture(&mut w, territory("west"), "fn action_interval_ms(s){1000}");
    w.players[0].energy = 10;
    let mut rest = Action::new(Skill::Rest);
    rest.duration = 3;
    decision(&mut w, 1, rest);
    w.advance_ms(500);
    let mut w: World = serde_json::from_value(json!(w)).unwrap();
    fixture(&mut w,territory("west"),"fn on_damage(c){#{health:c.actor.health,fear:0,caution:0,learn_danger:false,confidence:100,interrupt:false,dead:false}} fn action_interval_ms(s){9000}");
    w.damage(0, 20, None, 1, "attack").unwrap();
    assert_eq!(w.players[0].health, 100);
    w.advance_ms(500);
    assert_eq!(w.players[0].energy, 22);
    w.players[1].position = 3;
    w.damage(1, 20, None, 1, "attack").unwrap();
    assert_eq!(w.players[1].health, 80);
}
#[test]
fn participant_law_jobs_have_controller_name_parity_and_exact_physical_cost() {
    let mut a = world();
    let mut b = a.clone();
    b.players[0].controller = Controller::Ai;
    b.players[0].name = "A different ordinary person".into();
    b.players[0].role = "No magic title".into();
    for w in [&mut a, &mut b] {
        let before = w.infrastructure.stations[0].seed.electricity;
        let water = w.infrastructure.stations[0].seed.materials.water;
        let balance = w.infrastructure.balance.clone();
        let op = Op::PrototypeLaw {
            station: 1,
            scope: territory("west"),
            draft: draft("fn cost(s){2}"),
            cases: vec![case("cost", json!("gather"), json!(2))],
            sources: vec![],
        };
        decision(w, 1, action(op));
        w.advance_ms(1000);
        assert_eq!(w.infrastructure.stations[0].jobs.len(), 1);
        let (code, proof) = finish(w, 1);
        assert!(!code.is_empty() && !proof.is_empty());
        assert_eq!(
            w.infrastructure.stations[0].seed.electricity,
            before - balance.compute_electricity * balance.compute_quanta as i32
        );
        assert_eq!(
            w.infrastructure.stations[0].seed.materials.water,
            water - balance.compute_water * balance.compute_quanta as i32
        );
        assert!(
            w.infrastructure.stations[0].jobs[0]
                .report
                .as_ref()
                .unwrap()
                .law_experiment
                .as_ref()
                .unwrap()
                .successful
        );
    }
    assert_eq!(
        a.infrastructure.stations[0].jobs[0].input_hash,
        b.infrastructure.stations[0].jobs[0].input_hash
    );
    assert_eq!(a.players[0].food, b.players[0].food);
}
#[test]
fn private_fault_details_are_not_copied_into_other_peoples_bindings() {
    let mut w = world();
    fixture(
        &mut w,
        territory("west"),
        "fn research_authoring(c){throw c.proofs.to_string()} fn cost(s){2}",
    );
    let own = w.research_facts(1);
    assert!(!own.is_null());
    assert_eq!(w.laws.faults.lock()[0].hook, "research_authoring");
    let binding = w.law_binding_at(Some(0));
    assert!(json!(binding)["disabled"][0].get("error").is_none());
    assert!(w.laws.faults.lock()[0].error.contains("[]"));
    w.players[1].position = 3;
    let remote = w.law_research_facts(2);
    assert!(!serde_json::to_string(&remote)
        .unwrap()
        .contains("territory:west"));
    assert!(apply(
        &mut w,
        2,
        Op::InspectInstalledLaw {
            station: 2,
            scope: territory("west")
        }
    )
    .is_err());
}
#[test]
fn retained_law_jobs_and_inspection_do_not_overflow_unrelated_action_context() {
    let mut w = world();
    let large = format!("// {}\nfn cost(s){{2}}", "comment".repeat(1100));
    assert!(large.len() < 8192);
    let op = Op::PrototypeLaw {
        station: 1,
        scope: territory("west"),
        draft: draft(&large),
        cases: vec![case("cost", json!("gather"), json!(2))],
        sources: vec![],
    };
    for _ in 0..infrastructure::MAX_JOBS {
        apply(&mut w, 1, op.clone()).unwrap();
    }
    assert_eq!(
        w.infrastructure.stations[0].jobs.len(),
        infrastructure::MAX_JOBS
    );
    let mut rest = Action::new(Skill::Rest);
    rest.duration = 1;
    w.players[0].energy = 10;
    decision(&mut w, 1, rest);
    w.advance_ms(2500);
    assert_eq!(w.players[0].energy, 22);
    assert!(!w.events.iter().any(|e| e.kind == "script_error"));
    let (record, _) = finish(&mut w, 1);
    apply(&mut w, 1, Op::RetrieveReady { station: 1 }).unwrap();
    for _ in 0..16 {
        apply(
            &mut w,
            1,
            Op::InspectLaw {
                station: 1,
                record: record.clone(),
            },
        )
        .unwrap();
    }
    assert!(serde_json::to_vec(&w.players[0].memories).unwrap().len() > 60_000);
    assert!(
        serde_json::to_vec(&scripting::subjective(&w.players[0]))
            .unwrap()
            .len()
            < 16_384
    );
    assert!(Condition::At { location: 0 }.evaluate(&w.players[0]).0);
}
#[test]
fn pending_law_audit_retains_private_cases_after_physical_erasure() {
    let mut w = world();
    let input = json!("private_684921");
    apply(
        &mut w,
        1,
        Op::PrototypeLaw {
            station: 1,
            scope: territory("west"),
            draft: draft("fn cost(s){2}"),
            cases: vec![case("cost", input.clone(), json!(2))],
            sources: vec![],
        },
    )
    .unwrap();
    let source = w.infrastructure.stations[0].jobs[0].source;
    let event = w.events.iter().find(|e| e.id == source).unwrap();
    assert_eq!(event.data["cases"][0]["input"], input);
    assert!(event.data["binding"].is_object());
    assert!(event.data["program_record"]["law_program"].is_object());
    assert_eq!(
        event.data["input_hash"],
        laws::digest(&json!([
            event.data["scope"],
            event.data["binding"],
            event.data["program_record"],
            event.data["cases"],
            event.data["source_records"]
        ]))
    );
    apply(&mut w, 1, Op::EraseJob { station: 1, job: 1 }).unwrap();
    assert!(w.infrastructure.stations[0].jobs.is_empty());
    assert!(w
        .players
        .iter()
        .all(|p| p.knowledge.iter().all(|h| h.record.law_program.is_none())));
    assert_eq!(
        w.events.iter().find(|e| e.id == source).unwrap().data["cases"][0]["input"],
        input
    );
    assert!(!serde_json::to_string(&w.context(2))
        .unwrap()
        .contains("private_684921"));
}

#[test]
fn native_world_is_send_sync_and_fault_logs_are_transactionally_owned() {
    fn check<T: Send + Sync>() {}
    check::<World>();
    let mut w = world();
    fixture(
        &mut w,
        territory("west"),
        "fn cost(s){throw \"bounded failure\"}",
    );
    let rejected = w.clone();
    assert_eq!(
        rejected.law_at::<i32>(0, "cost", json!("gather")).unwrap(),
        4
    );
    assert_eq!(rejected.laws.faults.lock().len(), 1);
    assert!(w.laws.faults.lock().is_empty());
    let restored: World = serde_json::from_value(json!(rejected)).unwrap();
    assert_eq!(restored.laws.faults.lock().len(), 1);
    assert!(json!(restored)["laws"]["faults"].is_array());
}

#[test]
fn valid_law_vetoes_are_marked_separately_from_malformed_script_errors() {
    let mut w = world();
    let (code, _) = prototype(
        &mut w,
        1,
        territory("west"),
        "fn authorize_effect(c){false}",
        vec![case("authorize_effect", json!({}), json!(false))],
    );
    install(&mut w, 1, territory("west"), &code, None).unwrap();
    w.advance_ms(50);
    let before = (w.players[0].food, w.players[0].energy, w.sites[0].food);
    decision(&mut w, 1, Action::new(Skill::Gather));
    w.advance_ms(1000);
    assert_eq!(
        (w.players[0].food, w.players[0].energy, w.sites[0].food),
        before
    );
    let error = w
        .events
        .iter()
        .rev()
        .find(|e| e.kind == "script_error")
        .unwrap();
    assert_eq!(error.data["category"], "law_authorization_denied");
    assert_eq!(error.data["error"], "active law denied effect");
    assert_eq!(error.data["effects_committed"], false);
    assert!(
        error.data["law_binding"]["overlays"]
            .as_array()
            .unwrap()
            .len()
            > 0
    );
    assert!(w.laws.faults.lock().is_empty());
    let mut bad = world();
    fixture(&mut bad, territory("west"), "fn authorize_effect(c){false}");
    bad.scripts.history.get_mut("gather").unwrap().get_mut(&1).unwrap().source="fn validate(c){\"\"} fn step(c){#{status:\"success\",reason:\"\",remaining:0,state:(),effects:[#{kind:\"actor\",fields:#{health:0}}],progress:#{}}}".into();
    decision(&mut bad, 1, Action::new(Skill::Gather));
    bad.advance_ms(1000);
    let error = bad
        .events
        .iter()
        .rev()
        .find(|e| e.kind == "script_error")
        .unwrap();
    assert!(error.data.get("category").is_none());
    assert_eq!(
        error.data["error"],
        "script attempted to write outside actor capability"
    );
}

fn teach_law(w: &mut World, target: u32, code: &str) {
    let mut action = Action::new(Skill::Teach);
    action.target = Some(target);
    action.record = Some(code.into());
    let effect = Effect::Teach { target, record: code.into() };
    w.validate_knowledge_effect(0, &action, &effect).unwrap();
    let cause = w.event(Some(1), "law_test_teaching", vec![], json!({}));
    w.apply_knowledge_effect(0, cause, &effect).unwrap();
}
fn taught_law() -> (World, String, String) {
    let mut w = world();
    let (code, proof) = prototype(&mut w, 1, territory("west"), "fn cost(s){4}",
        vec![case("cost", json!("gather"), json!(4))]);
    teach_law(&mut w, 2, &code);
    (w, code, proof)
}
fn inspect_held_law(w: &mut World, actor: u32, code: &str) -> u64 {
    apply(w, actor, Op::InspectLaw { station: 1, record: code.into() }).unwrap();
    w.players[w.idx(actor).unwrap()].memories.iter().rev()
        .find(|p| p.kind == "law_inspected" && p.content["record"] == code).unwrap().source
}
fn law_assertion() -> knowledge::KnowledgeDraft {
    knowledge::KnowledgeDraft { topic: "Law reading".into(),
        text: "My reading is conditional and needs a separately paid test.".into(),
        location: None, confidence: 35 }
}
fn reflect_law(w: &mut World, actor: u32, source: u64, cursor: u64,
    draft: Option<knowledge::KnowledgeDraft>) -> participant::Receipt {
    w.participant_apply(actor, Request { api_version: API_VERSION.into(),
        request_id: format!("law-inspection-reflection-{}", w.next_event),
        control_epoch: w.participants[&actor].control_epoch,
        command: Command::Reflect { expected_revision: w.participants[&actor].learning_revision,
            observed_cursor: cursor, reflections: vec![Reflection { source,
                interpretation: "I assessed the exact law source and its limits; this reading is not a paid experiment.".into(),
                caution_delta: 0, trust_delta: 0, belief: None, knowledge: draft }], goal: None }
    }).unwrap()
}
fn practice_law(code: &str) -> Op {
    Op::PracticeLaw { station: 1, scope: LawScope::Universal, record: code.into(),
        cases: vec![case("cost", json!("gather"), json!(4))], sources: vec![] }
}
#[test]
fn own_law_inspection_assesses_code_but_installation_still_needs_own_assessed_paid_proof() {
    for derive in [false, true] {
        let (mut w, code, foreign_proof) = taught_law();
        teach_law(&mut w, 2, &foreign_proof);
        assess(&mut w, 2, &foreign_proof);
        let acquisition = w.players[1].knowledge.iter().find(|h| h.record.id == code).unwrap().source;
        let source = inspect_held_law(&mut w, 2, &code);
        let cursor = w.participants[&2].cursor;
        assert!(apply(&mut w, 2, practice_law(&code)).is_err());
        let receipt = reflect_law(&mut w, 2, source, cursor, derive.then(law_assertion));
        assert!(receipt.ok, "{:?}", receipt.error);
        let held = w.players[1].knowledge.iter().find(|h| h.record.id == code).unwrap();
        assert_eq!(held.source, acquisition);
        assert_eq!(held.interpreted_source, Some(source));
        assert!(w.events.iter().any(|e| e.kind == "knowledge_interpreted" && e.actor == Some(2)
            && e.data["record"] == code && e.data["source"] == source));
        if derive {
            let record = &w.players[1].knowledge.last().unwrap().record;
            assert!(record.program.is_none() && record.experiment.is_none()
                && record.law_program.is_none() && record.law_experiment.is_none());
        }
        assert!(install(&mut w, 2, LawScope::Universal, &code, Some(&foreign_proof)).is_err());
        let job = w.infrastructure.next_job;
        apply(&mut w, 2, practice_law(&code)).unwrap();
        let (_, proof) = finish(&mut w, job);
        apply(&mut w, 2, Op::RetrieveReady { station: 1 }).unwrap();
        assert!(install(&mut w, 2, LawScope::Universal, &code, Some(&proof)).is_err());
        assess(&mut w, 2, &proof);
        install(&mut w, 2, LawScope::Universal, &code, Some(&proof)).unwrap();
        w.advance_ms(50);
        assert_eq!(w.law_scope_revision(&LawScope::Universal), 1);
    }
}
#[test]
fn law_inspection_rejects_foreign_mismatched_and_invalid_assertions_atomically_without_resurrecting_copies() {
    let (mut original, code, _) = taught_law();
    let source = inspect_held_law(&mut original, 2, &code);
    let cursor = original.participants[&2].cursor;
    let mut foreign = original.clone();
    let before = json!(foreign.players[2]);
    assert!(!reflect_law(&mut foreign, 3, source, cursor, None).ok);
    assert_eq!(json!(foreign.players[2]), before);
    let mut missing = original.clone();
    missing.players[1].knowledge.retain(|h| h.record.id != code);
    let floor = missing.next_event;
    assert!(reflect_law(&mut missing, 2, source, cursor, Some(law_assertion())).ok);
    assert!(missing.players[1].knowledge.iter().all(|h| h.record.id != code && h.record.law_program.is_none()));
    assert!(!missing.events.iter().any(|e| e.id >= floor && e.kind == "knowledge_interpreted"));
    for corruption in ["source", "hash", "hooks", "version", "no_artifact", "invalid_draft"] {
        let mut w = original.clone();
        let record = &mut w.players[1].knowledge.iter_mut().find(|h| h.record.id == code).unwrap().record;
        let mut draft = law_assertion();
        match corruption {
            "source" => record.law_program.as_mut().unwrap().source.push_str("\n// changed"),
            "hash" => record.law_program.as_mut().unwrap().source_hash.push('x'),
            "hooks" => record.law_program.as_mut().unwrap().hooks.push("visible".into()),
            "version" => record.law_program.as_mut().unwrap().interface_version += 1,
            "no_artifact" => record.law_program = None,
            _ => draft.confidence = 101,
        }
        let before = json!(w.players[1]);
        let revision = w.participants[&2].learning_revision;
        let floor = w.next_event;
        assert!(!reflect_law(&mut w, 2, source, cursor, Some(draft)).ok, "{corruption}");
        assert_eq!(json!(w.players[1]), before);
        assert_eq!(w.participants[&2].learning_revision, revision);
        assert!(!w.events.iter().any(|e| e.id >= floor && matches!(e.kind.as_str(), "knowledge_interpreted" | "knowledge_asserted")));
    }
}
#[test]
fn leased_law_inspection_survives_eviction_and_reload_without_rewinding_assessment() {
    let (mut w, code, _) = taught_law();
    let older = inspect_held_law(&mut w, 2, &code);
    let old_cursor = w.participants[&2].cursor;
    assert!(w.participant_apply(2, Request { api_version: API_VERSION.into(), request_id: "pin-old-law".into(),
        control_epoch: w.participants[&2].control_epoch,
        command: Command::PinObservation { observed_cursor: old_cursor, sources: vec![older] } }).unwrap().ok);
    let newer = inspect_held_law(&mut w, 2, &code);
    let new_cursor = w.participants[&2].cursor;
    assert!(w.participant_apply(2, Request { api_version: API_VERSION.into(), request_id: "pin-new-law".into(),
        control_epoch: w.participants[&2].control_epoch,
        command: Command::PinObservation { observed_cursor: new_cursor, sources: vec![newer] } }).unwrap().ok);
    for _ in 0..100 { w.observe_site(1).unwrap(); }
    assert!(!w.players[1].memories.iter().any(|p| p.source == older));
    assert!(!w.participants[&2].experiences.iter().any(|p| p.source == older));
    let mut w: World = serde_json::from_value(json!(w)).unwrap();
    let mut first = w.clone();
    assert!(reflect_law(&mut first, 2, older, old_cursor, None).ok);
    assert_eq!(first.players[1].knowledge.iter().find(|h| h.record.id == code).unwrap().interpreted_source, Some(older));
    assert!(reflect_law(&mut w, 2, newer, new_cursor, None).ok);
    let floor = w.next_event;
    assert!(reflect_law(&mut w, 2, older, old_cursor, Some(law_assertion())).ok);
    assert_eq!(w.players[1].knowledge.iter().find(|h| h.record.id == code).unwrap().interpreted_source, Some(newer));
    assert!(!w.events.iter().any(|e| e.id >= floor && e.kind == "knowledge_interpreted"));
}
#[test]
fn legacy_human_and_ai_can_assess_exact_held_law_inspection() {
    let (mut original, code, _) = taught_law();
    let source = inspect_held_law(&mut original, 2, &code);
    for controller in [Controller::Human, Controller::Ai] {
        let mut w = original.clone();
        w.participant_mode = false;
        w.players[1].controller = controller.clone();
        w.submit(2, controller, Decision { reason: "Read the law source I inspected".into(),
            actions: vec![Action::new(Skill::Wait)], policy: None,
            reflections: vec![Reflection { source, interpretation: "I assessed this exact law source and its limits.".into(),
                caution_delta: 0, trust_delta: 0, belief: None, knowledge: Some(law_assertion()) }] }, None).unwrap();
        assert_eq!(w.players[1].knowledge.iter().find(|h| h.record.id == code).unwrap().interpreted_source, Some(source));
        assert!(install(&mut w, 2, LawScope::Universal, &code, None).is_err());
    }
}
#[test]
fn installed_law_inspection_never_acquires_or_assesses_a_personal_record() {
    for keep_copy in [false, true] {
        let (mut w, code, _) = taught_law();
        install(&mut w, 1, territory("west"), &code, None).unwrap();
        w.advance_ms(50);
        if !keep_copy { w.players[1].knowledge.clear(); }
        let holdings = w.players[1].knowledge.len();
        apply(&mut w, 2, Op::InspectInstalledLaw { station: 1, scope: territory("west") }).unwrap();
        let source = w.players[1].memories.iter().rev().find(|p| p.kind == "law_inspected").unwrap().source;
        let cursor = w.participants[&2].cursor;
        let floor = w.next_event;
        assert!(reflect_law(&mut w, 2, source, cursor, Some(law_assertion())).ok);
        assert_eq!(w.players[1].knowledge.len(), holdings + 1);
        assert!(w.players[1].knowledge.iter().filter(|h| h.record.law_program.is_some()).all(|h| h.interpreted_source.is_none()));
        assert!(!w.events.iter().any(|e| e.id >= floor && e.kind == "knowledge_interpreted"));
        assert!(apply(&mut w, 2, practice_law(&code)).is_err());
        assert!(install(&mut w, 2, LawScope::Universal, &code, None).is_err());
    }
}
