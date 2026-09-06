use super::*;
use infrastructure::{ForecastInput, InfrastructureOperation as Op, InfrastructureSeed};
use participant::{Command, Request, API_VERSION};
use research::ExperimentKind;
use research_programs::{ProgramDraft, ProgramError};
use scripting::Effect;

// Deterministic tooling fixture, never evidence of autonomous invention.
const TECHNIQUE: &str = r#"
fn positive(n) { if n>0 {n} else {0} }
fn technique(input) {
    let charge=input[0]; let capacity=input[1]; let unmet=0; let spilled=0;
    for i in range(2,input.len(),2) {
        let supply=charge+input[i]; spilled+=positive(supply-capacity);
        charge=if supply>capacity {capacity} else {supply};
        unmet+=positive(input[i+1]-charge); charge=positive(charge-input[i+1]);
    }
    [charge,unmet,spilled]
}
"#;
fn draft(source: &str) -> ProgramDraft {
    ProgramDraft {
        interface_version: 1,
        source: source.into(),
        input_contract: "Initial charge, capacity, then pairs of interval generation and demand"
            .into(),
        output_contract: "Final charge, unmet demand, spilled generation".into(),
    }
}
fn inputs() -> Vec<i64> {
    vec![2, 5, 8, 2, 0, 7]
}
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
        p.energy = 100;
        p.food = 10;
        p.beliefs.clear();
    }
    for site in &mut s.sites {
        site.hazard = 0;
    }
    s.archives = vec![knowledge::ArchiveSeed {
        id: 7,
        position: 0,
        label: "Technique archive".into(),
        capacity: 16,
    }];
    s.infrastructure=Some(serde_json::from_value::<InfrastructureSeed>(json!({"version":1,"actor_materials":{},"stations":[{"id":1,"owner":1,"position":0,"label":"Research terminal","electricity":200,"electricity_capacity":200,"materials":{"water":200},"modules":["terminal"],"access":{"2":{"use_allowed":true},"3":{"use_allowed":true}},"generation_period_ms":1000,"generation_amount":1}]})).unwrap());
    s
}
fn world() -> World {
    let mut w = World::new("research-fixture".into(), scenario()).unwrap();
    w.enable_participants();
    w
}
fn action(op: Op) -> Action {
    Action {
        infrastructure: Some(op),
        ..Action::new(Skill::Infrastructure)
    }
}
fn apply(w: &mut World, actor: u32, op: Op) -> Result<(), String> {
    let mut candidate = w.clone();
    let i = candidate.idx(actor)?;
    let a = action(op.clone());
    let effect = Effect::Infrastructure { operation: op };
    candidate.validate_infrastructure_effect(i, &a, &effect)?;
    let cause = candidate.event(Some(actor), "research_test_input", vec![], json!({}));
    candidate.apply_infrastructure_effect(i, cause, &effect)?;
    *w = candidate;
    Ok(())
}
fn complete(w: &mut World, job: u64) {
    for _ in 0..20 {
        if w.infrastructure.stations[0]
            .jobs
            .iter()
            .find(|j| j.id == job)
            .unwrap()
            .report
            .is_some()
        {
            return;
        }
        w.advance_ms(1000);
    }
    panic!(
        "job failed to complete: {:?}",
        w.infrastructure.stations[0]
            .jobs
            .iter()
            .find(|j| j.id == job)
    );
}
fn assess(w: &mut World, actor: u32, record: &str) {
    let source = w.players[w.idx(actor).unwrap()]
        .knowledge
        .iter()
        .find(|h| h.record.id == record)
        .unwrap()
        .source;
    let receipt=w.participant_apply(actor,Request {api_version:API_VERSION.into(),request_id:format!("research-assess-{}",w.next_event),control_epoch:w.participants[&actor].control_epoch,command:Command::Reflect {expected_revision:w.participants[&actor].learning_revision,observed_cursor:w.participants[&actor].cursor,reflections:vec![Reflection {source,interpretation:"I assessed this specific reported result and its limits; matching a prediction is not universal proof.".into(),caution_delta:0,trust_delta:0,belief:None,knowledge:None}],goal:None}}).unwrap();
    assert!(receipt.ok, "{:?}", receipt.error);
}
fn bootstrap(w: &mut World, actor: u32) -> String {
    let id = w.infrastructure.next_job;
    apply(
        w,
        actor,
        Op::SubmitJob {
            station: 1,
            input: ForecastInput {
                stock: 10,
                inflow_per_min: 3,
                demand_per_min: 5,
                horizon_ms: 120000,
                sources: vec![],
            },
        },
    )
    .unwrap();
    complete(w, id);
    apply(w, actor, Op::RetrieveReady { station: 1 }).unwrap();
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
    assess(w, actor, &record);
    record
}
fn prototype(w: &mut World, actor: u32, source: &str, expected: Vec<i64>) -> u64 {
    let id = w.infrastructure.next_job;
    apply(
        w,
        actor,
        Op::Prototype {
            station: 1,
            draft: draft(source),
            inputs: inputs(),
            sources: vec![],
            expected_results: expected,
        },
    )
    .unwrap();
    id
}
fn collect(w: &mut World, actor: u32, job: u64) -> (String, String) {
    complete(w, job);
    let j = w.infrastructure.stations[0]
        .jobs
        .iter()
        .find(|j| j.id == job)
        .unwrap();
    let report = j.report.as_ref().unwrap().id.clone();
    let program = j.program_work.as_ref().unwrap().program_record.id.clone();
    apply(w, actor, Op::RetrieveJob { station: 1, job }).unwrap();
    (report, program)
}
fn learned_author(w: &mut World) -> (String, String, u64) {
    bootstrap(w, 1);
    let job = prototype(w, 1, TECHNIQUE, vec![0, 4, 5]);
    let (report, program) = collect(w, 1, job);
    assess(w, 1, &report);
    assess(w, 1, &program);
    (report, program, job)
}
fn teach(w: &mut World, actor: u32, target: u32, record: &str) {
    w.participant_manual(
        actor,
        Decision {
            reason: "Communicate a specific physical knowledge copy".into(),
            actions: vec![Action {
                target: Some(target),
                record: Some(record.into()),
                ..Action::new(Skill::Teach)
            }],
            policy: None,
            reflections: vec![],
        },
    )
    .unwrap();
    w.advance_ms(2000);
    assert!(w.players[w.idx(target).unwrap()]
        .knowledge
        .iter()
        .any(|h| h.record.id == record));
}
fn stocks(w: &World) -> (i32, i32, i32, u64, usize) {
    let s = &w.infrastructure.stations[0];
    (
        s.seed.electricity,
        s.seed.materials.water,
        s.integrity,
        w.infrastructure.next_job,
        s.jobs.len(),
    )
}

#[test]
fn novice_cannot_author_and_only_owned_paid_assessed_evidence_bootstraps() {
    let mut w = world();
    let before = stocks(&w);
    assert!(prototype_attempt(&mut w, 1, TECHNIQUE).is_err());
    assert_eq!(stocks(&w), before);
    let id = w.infrastructure.next_job;
    apply(
        &mut w,
        1,
        Op::SubmitJob {
            station: 1,
            input: ForecastInput {
                stock: 1,
                inflow_per_min: 1,
                demand_per_min: 1,
                horizon_ms: 60000,
                sources: vec![],
            },
        },
    )
    .unwrap();
    complete(&mut w, id);
    assert!(!w.research_facts(1)["can_author"].as_bool().unwrap());
    apply(&mut w, 1, Op::RetrieveReady { station: 1 }).unwrap();
    let report = w.infrastructure.stations[0].jobs[0]
        .report
        .as_ref()
        .unwrap()
        .id
        .clone();
    assert!(!w.research_facts(1)["can_author"].as_bool().unwrap());
    assess(&mut w, 1, &report);
    assert_eq!(w.research_facts(1)["can_author"], true);
    teach(&mut w, 1, 2, &report);
    assess(&mut w, 2, &report);
    assert_eq!(
        w.research_facts(2)["can_author"],
        false,
        "another person's evidence is not personal practice"
    );
    assert_eq!(w.infrastructure.stations[0].seed.electricity, 194);
    assert_eq!(w.infrastructure.stations[0].seed.materials.water, 197);
    let bad = json!({"topic":"forged","text":"I know how","location":null,"confidence":100,"program":research_programs::compile(&draft(TECHNIQUE)).unwrap()});
    assert!(serde_json::from_value::<knowledge::KnowledgeDraft>(bad.clone()).is_err());
    let mut seed = bad;
    seed["id"] = json!("forged-seed");
    assert!(serde_json::from_value::<knowledge::RecordSeed>(seed).is_err());
}
fn prototype_attempt(w: &mut World, actor: u32, source: &str) -> Result<(), String> {
    apply(
        w,
        actor,
        Op::Prototype {
            station: 1,
            draft: draft(source),
            inputs: inputs(),
            sources: vec![],
            expected_results: vec![0, 4, 5],
        },
    )
}

#[test]
fn preflight_invalid_code_and_unowned_sources_have_no_effects() {
    let mut w = world();
    bootstrap(&mut w, 1);
    let before = stocks(&w);
    for source in [
        "fn wrong(input) { input }",
        "fn technique(input) { [ }",
        "42; fn technique(input) { input }",
        "fn technique(input) { print(1); input }",
    ] {
        assert!(prototype_attempt(&mut w, 1, source).is_err());
        assert_eq!(stocks(&w), before);
    }
    assert!(apply(
        &mut w,
        1,
        Op::Prototype {
            station: 1,
            draft: draft(TECHNIQUE),
            inputs: inputs(),
            sources: vec!["guessed-foreign-record".into()],
            expected_results: vec![0, 4, 5]
        }
    )
    .is_err());
    assert_eq!(stocks(&w), before);
    assert!(apply(
        &mut w,
        1,
        Op::Prototype {
            station: 1,
            draft: draft(TECHNIQUE),
            inputs: vec![1; 65],
            sources: vec![],
            expected_results: vec![]
        }
    )
    .is_err());
    assert_eq!(stocks(&w), before);
}

#[test]
fn prototype_result_and_code_are_separate_and_retrieval_prechecks_both() {
    let mut w = world();
    bootstrap(&mut w, 1);
    let job = prototype(&mut w, 1, TECHNIQUE, vec![0, 4, 5]);
    complete(&mut w, job);
    let j = w.infrastructure.stations[0]
        .jobs
        .iter()
        .find(|j| j.id == job)
        .unwrap();
    let report = j.report.as_ref().unwrap().clone();
    let code = j.program_work.as_ref().unwrap().program_record.clone();
    assert!(report.program.is_none());
    assert!(code.experiment.is_none());
    assert_eq!(
        report.experiment.as_ref().unwrap().output,
        Some(vec![0, 4, 5])
    );
    assert!(!serde_json::to_string(&report)
        .unwrap()
        .contains("fn technique"));
    assert!(!serde_json::to_string(&code)
        .unwrap()
        .contains("expected_results"));
    assert_eq!(w.players[0].knowledge.len(), 1);
    // Fill with valid pre-existing held assertions to leave exactly one slot.
    for n in 0..30 {
        let mut filler = w.players[0].knowledge[0].clone();
        filler.record.id = format!("held-filler-{n}");
        filler.record.experiment = None;
        w.players[0].knowledge.push(filler);
    }
    let before = w.players[0].knowledge.len();
    assert!(apply(&mut w, 1, Op::RetrieveReady { station: 1 }).is_err());
    assert_eq!(w.players[0].knowledge.len(), before);
    assert!(
        !w.infrastructure.stations[0]
            .jobs
            .iter()
            .find(|j| j.id == job)
            .unwrap()
            .retrieved
    );
    w.players[0].knowledge.pop();
    apply(&mut w, 1, Op::RetrieveReady { station: 1 }).unwrap();
    assert_eq!(w.players[0].knowledge.len(), 32);
    let receipts: Vec<_> = w
        .events
        .iter()
        .filter(|e| e.kind == "compute_retrieved" && e.data["job"] == job)
        .collect();
    assert_eq!(receipts.len(), 2);
    assert_ne!(receipts[0].data["record"], receipts[1].data["record"]);
}

#[test]
fn paid_runtime_failure_and_wrong_predictions_do_not_grant_program_use() {
    for (source, expected_error) in [
        (
            "fn technique(input) { loop {} }",
            Some(ProgramError::OperationBudget),
        ),
        (
            "fn technique(input) { #{effects:[1]} }",
            Some(ProgramError::OutputType),
        ),
        (TECHNIQUE, None),
    ] {
        let mut w = world();
        bootstrap(&mut w, 1);
        let before = stocks(&w);
        let job = prototype(&mut w, 1, source, vec![999]);
        let (report, program) = collect(&mut w, 1, job);
        let evidence = w.players[0]
            .knowledge
            .iter()
            .find(|h| h.record.id == report)
            .unwrap()
            .record
            .experiment
            .as_ref()
            .unwrap();
        assert!(!evidence.successful);
        assert_eq!(evidence.runtime_error, expected_error);
        assert_eq!(evidence.paid_quanta, 3);
        assert_eq!(stocks(&w).0, before.0 - 6);
        assert_eq!(stocks(&w).1, before.1 - 3);
        assert_eq!(stocks(&w).2, before.2 - 3);
        assess(&mut w, 1, &report);
        assess(&mut w, 1, &program);
        assert!(apply(
            &mut w,
            1,
            Op::RunProgram {
                station: 1,
                record: program,
                inputs: inputs(),
                sources: vec![]
            }
        )
        .is_err());
        assert!(!w
            .events
            .iter()
            .any(|e| e.kind == "script_tick_failed" || e.kind == "script_error"));
    }
}

#[test]
fn communicated_program_requires_personal_interpretation_practice_and_assessment_before_use() {
    let mut w = world();
    let (report, program, _) = learned_author(&mut w);
    teach(&mut w, 1, 2, &program);
    assert!(w.players[1].knowledge.iter().all(|h| h.record.id != report));
    assert_eq!(w.research_facts(2)["can_author"], false);
    let op = Op::PracticeProgram {
        station: 1,
        record: program.clone(),
        inputs: vec![2, 5, 0, 7, 8, 2],
        sources: vec![],
        expected_results: vec![3, 5, 3],
    };
    assert!(apply(&mut w, 2, op.clone()).is_err());
    assess(&mut w, 2, &program);
    assert!(apply(
        &mut w,
        2,
        Op::RunProgram {
            station: 1,
            record: program.clone(),
            inputs: inputs(),
            sources: vec![]
        }
    )
    .is_err());
    let job = w.infrastructure.next_job;
    let before = stocks(&w);
    apply(&mut w, 2, op).unwrap();
    let (practice, received_program) = collect(&mut w, 2, job);
    assert_eq!(received_program, program);
    assert_eq!(stocks(&w).0, before.0 - 6);
    assert_eq!(stocks(&w).1, before.1 - 3);
    assert_eq!(w.research_facts(2)["can_author"], false);
    assess(&mut w, 2, &practice);
    assert_eq!(w.research_facts(2)["can_author"], true);
    let run = w.infrastructure.next_job;
    apply(
        &mut w,
        2,
        Op::RunProgram {
            station: 1,
            record: program.clone(),
            inputs: vec![2, 20, 8, 2, 0, 7],
            sources: vec![],
        },
    )
    .unwrap();
    complete(&mut w, run);
    let output = w.infrastructure.stations[0]
        .jobs
        .iter()
        .find(|j| j.id == run)
        .unwrap()
        .report
        .as_ref()
        .unwrap()
        .experiment
        .as_ref()
        .unwrap();
    assert_eq!(output.kind, ExperimentKind::Run);
    assert_eq!(output.output, Some(vec![1, 0, 0]));
    assert_eq!(
        output.program_hash,
        w.players[1]
            .knowledge
            .iter()
            .find(|h| h.record.id == program)
            .unwrap()
            .record
            .program
            .as_ref()
            .map(|p| p.source_hash.clone())
    );
}

#[test]
fn privacy_inspection_and_frozen_inputs_hold_across_reload_and_interruption() {
    let mut w = world();
    bootstrap(&mut w, 1);
    let job = prototype(&mut w, 1, TECHNIQUE, vec![0, 4, 5]);
    w.advance_ms(1333);
    apply(
        &mut w,
        1,
        Op::SetAccess {
            station: 1,
            actor: 1,
            use_allowed: false,
            maintain: true,
            admin: true,
        },
    )
    .unwrap();
    let before = stocks(&w);
    w.advance_ms(2000);
    assert_eq!(stocks(&w), before);
    w = serde_json::from_slice(&serde_json::to_vec(&w).unwrap()).unwrap();
    w.sites[0].food = 123456;
    w.players[1].food = 777;
    apply(
        &mut w,
        1,
        Op::SetAccess {
            station: 1,
            actor: 1,
            use_allowed: true,
            maintain: true,
            admin: true,
        },
    )
    .unwrap();
    let (report, program) = collect(&mut w, 1, job);
    assert_eq!(
        w.players[0]
            .knowledge
            .iter()
            .find(|h| h.record.id == report)
            .unwrap()
            .record
            .experiment
            .as_ref()
            .unwrap()
            .output,
        Some(vec![0, 4, 5])
    );
    let own = w.participant_snapshot(1, 0, 128).unwrap().to_string();
    let other = w.participant_snapshot(2, 0, 128).unwrap().to_string();
    assert!(!own.contains("let capacity=input[1]"));
    assert!(!other.contains("let capacity=input[1]"));
    assert!(!other.contains(&program));
    // The human presentation history must obey the same explicit-inspection
    // boundary as participant observations, including raw perception memories.
    let browser=crate::client_view::snapshot(&w,false,1,&w.events);
    assert!(!browser.to_string().contains("let capacity=input[1]"));
    assert!(browser["players"][0]["research"]["programs"].is_array());
    let other_browser=crate::client_view::snapshot(&w,false,2,&w.events);
    assert!(!other_browser.to_string().contains(&program));
    assert!(apply(
        &mut w,
        2,
        Op::InspectProgram {
            station: 1,
            record: program.clone()
        }
    )
    .is_err());
    apply(
        &mut w,
        1,
        Op::InspectProgram {
            station: 1,
            record: program,
        },
    )
    .unwrap();
    assert!(w.players[0]
        .memories
        .iter()
        .any(|m| m.kind == "program_inspected"
            && m.content["program"]["source"].as_str() == Some(TECHNIQUE)));
    let browser=crate::client_view::snapshot(&w,false,1,&w.events);
    assert!(browser["events"].as_array().unwrap().iter().any(|e|
        e["kind"]=="program_inspected" && e["data"]["program"]["source"].as_str()==Some(TECHNIQUE)));
    assert!(!w
        .participant_snapshot(2, 0, 128)
        .unwrap()
        .to_string()
        .contains(TECHNIQUE));
    assert!(
        serde_json::to_vec(&scripting::subjective(&w.players[0]))
            .unwrap()
            .len()
            < 65536
    );
}

#[test]
fn erased_terminal_and_lost_carriers_do_not_restore_source_from_audit_or_hash() {
    let mut w = world();
    let (_, program, job) = learned_author(&mut w);
    let i = 0;
    let a = Action {
        archive: Some(7),
        record: Some(program.clone()),
        ..Action::new(Skill::Record)
    };
    let effect = Effect::RecordKnowledge {
        archive: 7,
        record: program.clone(),
    };
    w.validate_knowledge_effect(i, &a, &effect).unwrap();
    w.apply_knowledge_effect(i, 1, &effect).unwrap();
    apply(&mut w, 1, Op::EraseJob { station: 1, job }).unwrap();
    assert!(w.infrastructure.stations[0]
        .jobs
        .iter()
        .all(|j| j.id != job));
    let next = w.infrastructure.next_job;
    w.players[0].health = 0;
    let destroy = Effect::DestroyArchive { archive: 7 };
    w.validate_knowledge_effect(
        1,
        &Action {
            archive: Some(7),
            ..Action::new(Skill::DestroyArchive)
        },
        &destroy,
    )
    .unwrap();
    w.apply_knowledge_effect(1, 1, &destroy).unwrap();
    assert!(
        w.events
            .iter()
            .any(|e| e.kind == "compute_submitted" && e.data["program_record"]["id"] == program),
        "observer history still exists"
    );
    assert!(apply(
        &mut w,
        2,
        Op::InspectProgram {
            station: 1,
            record: program.clone()
        }
    )
    .is_err());
    assert!(apply(
        &mut w,
        2,
        Op::PracticeProgram {
            station: 1,
            record: program,
            inputs: inputs(),
            sources: vec![],
            expected_results: vec![0, 4, 5]
        }
    )
    .is_err());
    let id = w.infrastructure.next_job;
    apply(
        &mut w,
        2,
        Op::SubmitJob {
            station: 1,
            input: ForecastInput {
                stock: 1,
                inflow_per_min: 1,
                demand_per_min: 1,
                horizon_ms: 60000,
                sources: vec![],
            },
        },
    )
    .unwrap();
    assert_eq!(id, next);
    assert_eq!(w.infrastructure.next_job, next + 1);
    assert!(w.infrastructure.stations[0]
        .jobs
        .iter()
        .all(|j| j.program_work.is_none()));
}

#[test]
fn controller_identity_and_real_participant_execution_share_authorship_costs() {
    let mut outcomes = vec![];
    for controller in [Controller::Human, Controller::Ai] {
        let mut s = scenario();
        s.players[0].controller = controller;
        s.players[0].name = "Ordinary citizen".into();
        s.players[0].role = "Council chair without editing powers".into();
        let mut w = World::new("author-parity".into(), s).unwrap();
        w.enable_participants();
        assert_eq!(w.research_facts(1)["can_author"], false);
        bootstrap(&mut w, 1);
        let id = w.infrastructure.next_job;
        w.participant_manual(
            1,
            Decision {
                reason: "Test an independently supplied nonlinear numerical technique".into(),
                actions: vec![action(Op::Prototype {
                    station: 1,
                    draft: draft(TECHNIQUE),
                    inputs: inputs(),
                    sources: vec![],
                    expected_results: vec![0, 4, 5],
                })],
                policy: None,
                reflections: vec![],
            },
        )
        .unwrap();
        w.advance_ms(1);
        complete(&mut w, id);
        outcomes.push((
            stocks(&w).0,
            stocks(&w).1,
            w.infrastructure.stations[0]
                .jobs
                .last()
                .unwrap()
                .report
                .as_ref()
                .unwrap()
                .experiment
                .as_ref()
                .unwrap()
                .output
                .clone(),
        ));
        assert!(!w
            .events
            .iter()
            .any(|e| e.kind == "script_tick_failed" || e.kind == "script_error"));
    }
    assert_eq!(outcomes[0], outcomes[1]);
}

#[test]
fn sharing_portable_code_never_copies_private_experiment_inputs() {
    let mut w = world();
    bootstrap(&mut w, 1);
    let id = w.infrastructure.next_job;
    apply(
        &mut w,
        1,
        Op::Prototype {
            station: 1,
            draft: draft(TECHNIQUE),
            inputs: vec![987654, 5, 8, 2, 0, 7],
            sources: vec![],
            expected_results: vec![0, 4, 987657],
        },
    )
    .unwrap();
    let (report, program) = collect(&mut w, 1, id);
    assert!(w.context(0).to_string().contains("987654"));
    teach(&mut w, 1, 2, &program);
    assert!(w.players[1]
        .knowledge
        .iter()
        .any(|h| h.record.id == program && h.record.program.is_some()));
    assert!(w.players[1]
        .knowledge
        .iter()
        .all(|h| h.record.id != report && h.record.experiment.is_none()));
    assert!(!w
        .participant_snapshot(2, 0, 128)
        .unwrap()
        .to_string()
        .contains("987654"));
    assert!(!client_view::snapshot(&w, false, 2, &w.events)
        .to_string()
        .contains("987654"));
    assert!(!w.infrastructure_facts(2).to_string().contains("987654"));
}

#[test]
fn exact_source_hash_and_current_capability_law_gate_reuse() {
    let mut w = world();
    let (_, first, _) = learned_author(&mut w);
    let modified = format!("{TECHNIQUE}\n// distinct exact source revision");
    let job = prototype(&mut w, 1, &modified, vec![0, 4, 5]);
    let (report, second) = collect(&mut w, 1, job);
    assess(&mut w, 1, &second);
    assert_ne!(
        w.players[0]
            .knowledge
            .iter()
            .find(|h| h.record.id == first)
            .unwrap()
            .record
            .program
            .as_ref()
            .unwrap()
            .source_hash,
        w.players[0]
            .knowledge
            .iter()
            .find(|h| h.record.id == second)
            .unwrap()
            .record
            .program
            .as_ref()
            .unwrap()
            .source_hash
    );
    let op = Op::RunProgram {
        station: 1,
        record: second.clone(),
        inputs: inputs(),
        sources: vec![],
    };
    assert!(apply(&mut w, 1, op.clone()).is_err());
    assess(&mut w, 1, &report);
    apply(&mut w, 1, op).unwrap();
    let mut law = w.scripts.history["law"][&w.scripts.active["law"]].clone();
    law.revision += 1;
    law.source = law.source.replace(
        "fn research_use(c) { c.held_interpreted && c.own_matching_practice_assessed }",
        "fn research_use(c) { false }",
    );
    w.stage_scripts_by_operator(scripting::Update {
        api_version: scripting::API_VERSION,
        expected_revision: w.scripts.revision,
        definitions: vec![law],
    })
    .unwrap();
    w.advance_ms(1);
    let before = stocks(&w);
    assert!(apply(
        &mut w,
        1,
        Op::RunProgram {
            station: 1,
            record: first,
            inputs: inputs(),
            sources: vec![]
        }
    )
    .is_err());
    assert_eq!(stocks(&w), before);
}

#[test]
fn a_full_private_program_queue_does_not_overflow_unrelated_action_context() {
    let mut w = world();
    bootstrap(&mut w, 1);
    let source = format!("fn technique(input) {{ input }}\n//{}", "x".repeat(8000));
    for _ in 0..63 {
        apply(
            &mut w,
            1,
            Op::Prototype {
                station: 1,
                draft: draft(&source),
                inputs: vec![i64::MAX; 64],
                sources: vec![],
                expected_results: vec![i64::MAX; 64],
            },
        )
        .unwrap();
    }
    assert_eq!(w.infrastructure.stations[0].jobs.len(), 64);
    assert!(
        serde_json::to_vec(&w.infrastructure_facts(1))
            .unwrap()
            .len()
            > 65536
    );
    let compact = w.infrastructure_script_facts(1, Some(&Op::RetrieveReady { station: 1 }));
    assert!(serde_json::to_vec(&compact).unwrap().len() < 4096);
    w.players[0].energy = 20;
    w.participant_manual(
        1,
        Decision {
            reason: "Rest while physical research remains queued".into(),
            actions: vec![Action::new(Skill::Rest)],
            policy: None,
            reflections: vec![],
        },
    )
    .unwrap();
    w.advance_ms(2500);
    assert!(w.players[0].energy > 20);
    assert!(!w
        .events
        .iter()
        .any(|e| e.kind == "script_tick_failed" || e.kind == "script_error"));
}

fn assess_and_derive(w:&mut World,actor:u32,record:&str) {
    let source=w.players[w.idx(actor).unwrap()].knowledge.iter().find(|h|h.record.id==record).unwrap().source;
    let receipt=w.participant_apply(actor,Request{api_version:API_VERSION.into(),request_id:format!("research-derived-{}",w.next_event),control_epoch:w.participants[&actor].control_epoch,
        command:Command::Reflect{expected_revision:w.participants[&actor].learning_revision,observed_cursor:w.participants[&actor].cursor,
            reflections:vec![Reflection{source,interpretation:"I assessed this paid result, its supplied assumptions and its conditional limits.".into(),caution_delta:0,trust_delta:0,belief:None,
                knowledge:Some(knowledge::KnowledgeDraft{topic:"Conditional inference".into(),text:"The measured result supports a limited hypothesis under these inputs.".into(),location:None,confidence:30})}],goal:None}}).unwrap();
    assert!(receipt.ok,"{:?}",receipt.error);
    let original=w.players[w.idx(actor).unwrap()].knowledge.iter().find(|h|h.record.id==record).unwrap();
    assert_eq!(original.interpreted_source,Some(source));
    let derived=w.players[w.idx(actor).unwrap()].knowledge.last().unwrap();
    assert_ne!(derived.record.id,record);assert!(derived.record.program.is_none());assert!(derived.record.experiment.is_none());
}
#[test]
fn optional_assertion_bootstraps_only_the_actors_own_paid_assessed_forecast() {
    let mut w=world();let job=w.infrastructure.next_job;
    apply(&mut w,1,Op::SubmitJob{station:1,input:ForecastInput{stock:1,inflow_per_min:1,demand_per_min:1,horizon_ms:60000,sources:vec![]}}).unwrap();
    complete(&mut w,job);apply(&mut w,1,Op::RetrieveJob{station:1,job}).unwrap();
    let report=w.infrastructure.stations[0].jobs.iter().find(|j|j.id==job).unwrap().report.as_ref().unwrap().id.clone();
    assert_eq!(w.research_facts(1)["can_author"],false);
    assess_and_derive(&mut w,1,&report);
    assert_eq!(w.research_facts(1)["can_author"],true);assert!(prototype_attempt(&mut w,1,TECHNIQUE).is_ok());
    teach(&mut w,1,2,&report);assess_and_derive(&mut w,2,&report);
    assert_eq!(w.research_facts(2)["can_author"],false);assert!(prototype_attempt(&mut w,2,TECHNIQUE).is_err());
    // The derived assertion alone carries no portable proof of the paid result.
    w.players[0].knowledge.retain(|h|h.record.id!=report);
    assert_eq!(w.research_facts(1)["can_author"],false);
}
#[test]
fn optional_assertion_assessment_preserves_exact_source_paid_practice_gating() {
    let mut w=world();let (authors_report,program,_)=learned_author(&mut w);
    teach(&mut w,1,2,&program);teach(&mut w,1,2,&authors_report);
    assess_and_derive(&mut w,2,&program);assess_and_derive(&mut w,2,&authors_report);
    let run=Op::RunProgram{station:1,record:program.clone(),inputs:inputs(),sources:vec![]};
    assert!(apply(&mut w,2,run.clone()).is_err(),"a copied assessed result is not personal practice");
    let job=w.infrastructure.next_job;
    apply(&mut w,2,Op::PracticeProgram{station:1,record:program.clone(),inputs:vec![2,5,0,7,8,2],sources:vec![],expected_results:vec![3,5,3]}).unwrap();
    let (practice,_)=collect(&mut w,2,job);
    assert!(apply(&mut w,2,run.clone()).is_err(),"retrieval alone is not assessment");
    assess_and_derive(&mut w,2,&practice);assert!(apply(&mut w,2,run).is_ok());
    let held=w.players[1].knowledge.iter().find(|h|h.record.id==program).unwrap().clone();
    let mut different=held;different.record.id="different-valid-source".into();
    different.record.program=Some(research_programs::compile(&draft(&format!("{TECHNIQUE}\n// distinct exact source"))).unwrap());
    let other_id=different.record.id.clone();w.players[1].knowledge.push(different);
    assert!(apply(&mut w,2,Op::RunProgram{station:1,record:other_id,inputs:inputs(),sources:vec![]}).is_err(),"own practice is bound to the exact source hash");
}

fn inspection_reflection(w:&mut World,actor:u32,source:u64,cursor:u64,draft:Option<knowledge::KnowledgeDraft>)->participant::Receipt {
    w.participant_apply(actor,Request{api_version:API_VERSION.into(),request_id:format!("inspect-reflect-{}",w.next_event),control_epoch:w.participants[&actor].control_epoch,
        command:Command::Reflect{expected_revision:w.participants[&actor].learning_revision,observed_cursor:cursor,
            reflections:vec![Reflection{source,interpretation:"I inspected this exact implementation and considered its stated inputs and limits; this is not paid practice.".into(),caution_delta:0,trust_delta:0,belief:None,knowledge:draft}],goal:None}}).unwrap()
}
fn inspect_code(w:&mut World,actor:u32,record:&str)->u64 {
    apply(w,actor,Op::InspectProgram{station:1,record:record.into()}).unwrap();
    w.players[w.idx(actor).unwrap()].memories.iter().rev().find(|p|p.kind=="program_inspected" && p.content["record"]==record).unwrap().source
}
fn inspection_draft()->knowledge::KnowledgeDraft {
    knowledge::KnowledgeDraft{topic:"Implementation assessment".into(),text:"My reading supports a conditional interpretation, pending a separate paid test.".into(),location:None,confidence:35}
}
#[test]
fn taught_code_inspection_reflection_enables_practice_but_only_own_assessed_practice_enables_run() {
    for derive in [false,true] {
        let mut w=world();let (_,program,_)=learned_author(&mut w);teach(&mut w,1,2,&program);
        let acquisition=w.players[1].knowledge.iter().find(|h|h.record.id==program).unwrap().source;
        let source=inspect_code(&mut w,2,&program);let cursor=w.participants[&2].cursor;
        let practice=Op::PracticeProgram{station:1,record:program.clone(),inputs:vec![2,5,0,7,8,2],sources:vec![],expected_results:vec![3,5,3]};
        assert!(apply(&mut w,2,practice.clone()).is_err(),"inspection alone does not assess code");
        let receipt=inspection_reflection(&mut w,2,source,cursor,derive.then(inspection_draft));assert!(receipt.ok,"{:?}",receipt.error);
        let held=w.players[1].knowledge.iter().find(|h|h.record.id==program).unwrap();
        assert_eq!(held.source,acquisition);assert_eq!(held.interpreted_source,Some(source));
        assert!(w.events.iter().any(|e|e.kind=="knowledge_interpreted" && e.actor==Some(2) && e.data["record"]==program && e.data["source"]==source));
        if derive {let assertion=w.players[1].knowledge.last().unwrap();assert!(assertion.record.program.is_none());assert!(assertion.record.experiment.is_none());}
        assert_eq!(w.research_facts(2)["can_author"],false);
        let run=Op::RunProgram{station:1,record:program.clone(),inputs:inputs(),sources:vec![]};
        assert!(apply(&mut w,2,run.clone()).is_err());
        let job=w.infrastructure.next_job;apply(&mut w,2,practice).unwrap();let (result,_)=collect(&mut w,2,job);
        assert!(apply(&mut w,2,run.clone()).is_err(),"paid result still requires its own assessment");
        assess(&mut w,2,&result);let job=w.infrastructure.next_job;apply(&mut w,2,run).unwrap();complete(&mut w,job);
        assert!(w.infrastructure.stations[0].jobs.iter().find(|j|j.id==job).unwrap().report.is_some());
    }
}
#[test]
fn inspection_assessment_requires_current_exact_own_copy_and_invalid_draft_is_atomic() {
    let mut original=world();let (_,program,_)=learned_author(&mut original);teach(&mut original,1,2,&program);
    let source=inspect_code(&mut original,2,&program);let cursor=original.participants[&2].cursor;
    let mut foreign=original.clone();let before=serde_json::to_value(&foreign.players[2]).unwrap();
    assert!(!inspection_reflection(&mut foreign,3,source,cursor,None).ok);assert_eq!(serde_json::to_value(&foreign.players[2]).unwrap(),before);
    let mut missing=original.clone();missing.players[1].knowledge.retain(|h|h.record.id!=program);let event_floor=missing.next_event;
    assert!(inspection_reflection(&mut missing,2,source,cursor,Some(inspection_draft())).ok);
    assert!(missing.players[1].knowledge.iter().all(|h|h.record.id!=program && h.record.program.is_none()));
    assert!(!missing.events.iter().any(|e|e.id>=event_floor && e.kind=="knowledge_interpreted"));
    for corrupt_copy in [false,true] {
        let mut w=original.clone();let mut draft=inspection_draft();
        if corrupt_copy {w.players[1].knowledge.iter_mut().find(|h|h.record.id==program).unwrap().record.program.as_mut().unwrap().source.push_str("\n// changed after inspection");}
        else {draft.confidence=101;}
        let before=serde_json::to_value(&w.players[1]).unwrap();let revision=w.participants[&2].learning_revision;let event_floor=w.next_event;
        assert!(!inspection_reflection(&mut w,2,source,cursor,Some(draft)).ok);
        assert_eq!(serde_json::to_value(&w.players[1]).unwrap(),before);assert_eq!(w.participants[&2].learning_revision,revision);
        assert!(!w.events.iter().any(|e|e.id>=event_floor && matches!(e.kind.as_str(),"knowledge_interpreted"|"knowledge_asserted")));
    }
}
#[test]
fn leased_inspection_survives_trace_eviction_without_rewinding_a_newer_assessment() {
    let mut w=world();let (_,program,_)=learned_author(&mut w);teach(&mut w,1,2,&program);
    let older=inspect_code(&mut w,2,&program);let old_cursor=w.participants[&2].cursor;
    assert!(w.participant_apply(2,Request{api_version:API_VERSION.into(),request_id:"lease-old-inspection".into(),control_epoch:w.participants[&2].control_epoch,command:Command::PinObservation{observed_cursor:old_cursor,sources:vec![older]}}).unwrap().ok);
    let newer=inspect_code(&mut w,2,&program);let new_cursor=w.participants[&2].cursor;
    assert!(w.participant_apply(2,Request{api_version:API_VERSION.into(),request_id:"lease-new-inspection".into(),control_epoch:w.participants[&2].control_epoch,command:Command::PinObservation{observed_cursor:new_cursor,sources:vec![newer]}}).unwrap().ok);
    for _ in 0..100 {w.observe_site(1).unwrap();}
    assert!(!w.players[1].memories.iter().any(|p|p.source==older));assert!(!w.participants[&2].experiences.iter().any(|e|e.source==older));
    let mut first=w.clone();assert!(inspection_reflection(&mut first,2,older,old_cursor,None).ok);
    assert_eq!(first.players[1].knowledge.iter().find(|h|h.record.id==program).unwrap().interpreted_source,Some(older));
    assert!(inspection_reflection(&mut w,2,newer,new_cursor,None).ok);let event_floor=w.next_event;
    assert!(inspection_reflection(&mut w,2,older,old_cursor,Some(inspection_draft())).ok);
    assert_eq!(w.players[1].knowledge.iter().find(|h|h.record.id==program).unwrap().interpreted_source,Some(newer));
    assert!(!w.events.iter().any(|e|e.id>=event_floor && e.kind=="knowledge_interpreted"));
}
#[test]
fn human_and_ai_legacy_decisions_can_assess_their_exact_inspection() {
    let mut original=world();let (_,program,_)=learned_author(&mut original);teach(&mut original,1,2,&program);
    let source=inspect_code(&mut original,2,&program);
    for controller in [Controller::Human,Controller::Ai] {
        let mut w=original.clone();w.participant_mode=false;w.players[1].controller=controller.clone();
        w.submit(2,controller,Decision{reason:"Consider the code I actually inspected".into(),actions:vec![Action::new(Skill::Wait)],policy:None,
            reflections:vec![Reflection{source,interpretation:"I considered this exact implementation and its limits.".into(),caution_delta:0,trust_delta:0,belief:None,knowledge:Some(inspection_draft())}]},None).unwrap();
        assert_eq!(w.players[1].knowledge.iter().find(|h|h.record.id==program).unwrap().interpreted_source,Some(source));
        assert_eq!(w.research_facts(2)["can_author"],false);
    }
}
