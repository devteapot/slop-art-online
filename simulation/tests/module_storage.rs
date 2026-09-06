//! Exercise the exact pure codec used by the module without a database runtime.
#[path = "../../server/module/spacetimedb/src/foundation/storage_codec.rs"]
mod storage_codec;
use serde_json::{json, Value};
use simulation::{
    participant::{Command, Request, API_VERSION, EVIDENCE_LEASE_MS},
    Scenario, World,
};
use std::collections::{BTreeMap, BTreeSet};
use storage_codec::{
    blob_key, decode, decode_for_save, decode_with_layout, derived_fragment_ids,
    derived_fragment_owners, encode, encode_with_previous, encode_with_reuse, expand_status,
    experience_decode_count, fragment_assembly_count, lease_validation_count,
    reset_experience_decode_count, reset_fragment_assembly_count, reset_lease_validation_count,
    status, Blobs,
};

#[derive(Clone, Default)]
struct MemoryBlobs {
    rows: BTreeMap<u64, (String, Option<u32>, String, String, String)>,
    next: u64,
    interns_by_kind: BTreeMap<String, usize>,
    gets_by_kind: BTreeMap<String, usize>,
    gets_by_scope: BTreeMap<(String, Option<u32>, String, u64), usize>,
    retains_by_kind: BTreeMap<String, usize>,
    interned: BTreeSet<u64>,
    fetched: BTreeSet<u64>,
    retained: BTreeSet<u64>,
    validated: BTreeMap<u64, (String, Option<u32>, String)>,
}
impl MemoryBlobs {
    fn clear_counts(&mut self) {
        self.interns_by_kind.clear();
        self.gets_by_kind.clear();
        self.gets_by_scope.clear();
        self.retains_by_kind.clear();
        self.interned.clear();
        self.fetched.clear();
        self.retained.clear();
    }
    fn interns(&self, kind: &str) -> usize {
        self.interns_by_kind.get(kind).copied().unwrap_or(0)
    }
    fn gets(&self, kind: &str) -> usize {
        self.gets_by_kind.get(kind).copied().unwrap_or(0)
    }
    fn retains(&self, kind: &str) -> usize {
        self.retains_by_kind.get(kind).copied().unwrap_or(0)
    }
    fn begin_transaction(&mut self) {
        self.clear_counts();
        self.validated.clear();
    }
}
impl Blobs for MemoryBlobs {
    fn intern(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        body: String,
    ) -> Result<u64, String> {
        *self.interns_by_kind.entry(kind.into()).or_default() += 1;
        let key = blob_key(run, actor, kind, &body);
        if let Some((id, row)) = self.rows.iter().find(|(_, row)| row.4 == key) {
            if row.0 != run || row.1 != actor || row.2 != kind || row.3 != body {
                return Err("collision".into());
            }
            self.interned.insert(*id);
            self.validated.insert(*id, (run.into(), actor, kind.into()));
            return Ok(*id);
        }
        self.next += 1;
        self.rows
            .insert(self.next, (run.into(), actor, kind.into(), body, key));
        self.interned.insert(self.next);
        self.validated
            .insert(self.next, (run.into(), actor, kind.into()));
        Ok(self.next)
    }
    fn get(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<String, String> {
        *self.gets_by_kind.entry(kind.into()).or_default() += 1;
        *self
            .gets_by_scope
            .entry((run.into(), actor, kind.into(), id))
            .or_default() += 1;
        self.fetched.insert(id);
        let row = self.rows.get(&id).ok_or("missing")?;
        if row.0 != run
            || row.1 != actor
            || row.2 != kind
            || row.4 != blob_key(run, actor, kind, &row.3)
        {
            return Err("scope or content mismatch".into());
        }
        self.validated.insert(id, (run.into(), actor, kind.into()));
        Ok(row.3.clone())
    }
    fn retain_validated(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<(), String> {
        *self.retains_by_kind.entry(kind.into()).or_default() += 1;
        if id == 0 || self.validated.get(&id) != Some(&(run.into(), actor, kind.into())) {
            return Err("retain requires matching current-transaction validated metadata".into());
        }
        self.retained.insert(id);
        Ok(())
    }
}
fn world() -> World {
    let mut scenario: Scenario =
        serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
    scenario.sites.iter_mut().for_each(|site| site.hazard = 0);
    let mut world = World::new("sim-storage".into(), scenario).unwrap();
    world.enable_participants();
    world.advance_ms(2500);
    send(
        &mut world,
        1,
        "first",
        Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    );
    world
}
fn send(world: &mut World, actor: u32, id: &str, command: Command) {
    let request = Request {
        api_version: API_VERSION.into(),
        request_id: id.into(),
        control_epoch: world.participants[&actor].control_epoch,
        command,
    };
    assert!(world.participant_apply(actor, request).unwrap().ok);
}
fn json_world(world: &World) -> Value {
    serde_json::to_value(world).unwrap()
}
fn round_trip(world: &World, store: &mut MemoryBlobs) -> String {
    let encoded = encode(world, store).unwrap();
    assert_eq!(
        json_world(&decode(&encoded.state, store).unwrap()),
        json_world(world)
    );
    for actor in world.participants.keys() {
        let cache = status(world, *actor, &encoded.layout).unwrap();
        let actual: Value =
            serde_json::from_str(&expand_status(&world.run, *actor, &cache, store).unwrap())
                .unwrap();
        let expected: Value =
            serde_json::from_str(&world.participant_status_json(*actor).unwrap()).unwrap();
        assert_eq!(actual, expected);
    }
    encoded.state
}
#[test]
fn self_contained_world_and_exact_subjective_status_round_trip_without_duplicate_payloads() {
    let world = world();
    let mut store = MemoryBlobs::default();
    let first = round_trip(&world, &mut store);
    let count = store.rows.len();
    assert_eq!(round_trip(&world, &mut store), first);
    assert_eq!(store.rows.len(), count);
    assert!(serde_json::from_str::<World>(&first).is_err());
    let compact: Value = serde_json::from_str(&first).unwrap();
    assert_eq!(
        compact["world"]["participants"]["1"]["experiences"],
        json!([])
    );
    assert_eq!(
        compact["world"]["participants"]["1"]["evidence_leases"][0]["observation"],
        Value::Null
    );
}
#[test]
fn old_atomic_read_survives_trace_eviction_expiry_and_control_change() {
    let mut world = world();
    let mut store = MemoryBlobs::default();
    let captured = world.participant_status(1).unwrap()["read_observations"].clone();
    round_trip(&world, &mut store);
    world.participants.get_mut(&1).unwrap().experiences.clear();
    round_trip(&world, &mut store);
    assert_eq!(
        world.participant_status(1).unwrap()["read_observations"],
        captured
    );
    world.timing.time_ms += EVIDENCE_LEASE_MS + 1;
    round_trip(&world, &mut store);
    assert_eq!(
        world.participant_status(1).unwrap()["read_observations"],
        json!([])
    );
    world.change_control(1).unwrap();
    round_trip(&world, &mut store);
}
#[test]
fn numeric_references_reject_missing_wrong_run_actor_kind_and_changed_content() {
    let world = world();
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let id = *store
        .rows
        .iter()
        .find(|(_, row)| row.1 == Some(1) && row.2 == "observation")
        .unwrap()
        .0;
    for mode in 0..5 {
        let mut bad = store.clone();
        if mode == 0 {
            bad.rows.remove(&id);
        } else {
            let row = bad.rows.get_mut(&id).unwrap();
            match mode {
                1 => row.0 = "other-run".into(),
                2 => row.1 = Some(2),
                3 => row.2 = "experience".into(),
                _ => row.3 = "{}".into(),
            }
        }
        assert!(decode(&encoded.state, &mut bad).is_err(), "mode {mode}");
    }
    let row = store.rows.get_mut(&id).unwrap();
    row.3 = "collision".into();
    assert!(encode(&world, &mut store).is_err());
}
#[test]
fn corrupt_envelopes_inline_data_metadata_and_trace_order_fail_closed() {
    let world = world();
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let original: Value = serde_json::from_str(&encoded.state).unwrap();
    for mode in 0..7 {
        let mut bad = original.clone();
        match mode {
            0 => bad["format"] = json!("future-version"),
            1 => {
                bad["world"]["participants"]["1"]["experiences"] =
                    json_world(&world)["participants"]["1"]["experiences"].clone()
            }
            2 => bad["world"]["participants"]["1"]["evidence_leases"][0]["expires_ms"] = json!(0),
            3 => bad["layout"]["participants"]["1"]["trace"]
                .as_array_mut()
                .unwrap()
                .reverse(),
            4 => bad["layout"]["initial"] = json!(0),
            5 => bad["world"]["players"][1]["id"] = json!(1),
            _ => {
                let id = bad["layout"]["participants"]["1"]["trace"][0].clone();
                bad["layout"]["participants"]["1"]["trace"]
                    .as_array_mut()
                    .unwrap()
                    .push(id);
            }
        }
        assert!(decode(&bad.to_string(), &mut store).is_err(), "mode {mode}");
    }
}
#[test]
fn captured_observation_header_and_status_scope_are_validated() {
    let world = world();
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let cache = status(&world, 1, &encoded.layout).unwrap();
    assert!(expand_status("other", 1, &cache, &mut store).is_err());
    assert!(expand_status(&world.run, 2, &cache, &mut store).is_err());
    let mut bad = world.clone();
    let lease = &mut bad.participants.get_mut(&1).unwrap().evidence_leases[0];
    let mut body: Value = serde_json::from_str(lease.observation.get()).unwrap();
    body["actor"] = json!(2);
    lease.observation = serde_json::value::to_raw_value(&body).unwrap().into();
    assert!(encode(&bad, &mut store).is_err());
}
#[test]
fn rejected_encode_cannot_replace_committed_state_or_publish_partial_rows() {
    let world = world();
    let mut committed = MemoryBlobs::default();
    let previous = round_trip(&world, &mut committed);
    let count = committed.rows.len();
    let mut candidate = world.clone();
    candidate.initial.name = "new initial blob staged before failure".into();
    candidate.participants.get_mut(&1).unwrap().evidence_leases[0].expires_ms = 0;
    let mut transaction = committed.clone();
    assert!(encode(&candidate, &mut transaction).is_err());
    assert!(transaction.rows.len() > count);
    assert_eq!(committed.rows.len(), count);
    assert_eq!(
        json_world(&decode(&previous, &mut committed).unwrap()),
        json_world(&world)
    );
}
#[test]
fn archive_records_and_job_inputs_stay_shared_when_progress_changes() {
    let scenario: Scenario =
        serde_json::from_str(include_str!("../../scenarios/infrastructure-baseline.json")).unwrap();
    let mut world = World::new("sim-station-storage".into(), scenario).unwrap();
    world.enable_participants();
    let owner = world.players[0].id;
    let record = json!({"id":"private-report","topic":"hypothesis","text":"large immutable report".repeat(100),"location":null,"author":owner,"origin":1,"confidence":25});
    world.archives.push(serde_json::from_value(json!({"id":999,"position":0,"label":"test","capacity":32,"records":[record],"destroyed":false,"revision":1})).unwrap());
    world.infrastructure.stations[0].jobs.push(serde_json::from_value(json!({"id":42,"owner":owner,"submitted_ms":0,"source":1,"input":{"stock":2,"inflow_per_min":3,"demand_per_min":4,"horizon_ms":60000,"sources":["private-report"]},"input_hash":"fixture","sources":[record],"progress":0,"required":3,"last_quantum_ms":null,"report":null,"retrieved":false})).unwrap());
    let mut store = MemoryBlobs::default();
    let first = round_trip(&world, &mut store);
    let count = store.rows.len();
    world.infrastructure.stations[0].jobs[0].progress = 1;
    world.infrastructure.stations[0].jobs[0].last_quantum_ms = Some(1000);
    let second = round_trip(&world, &mut store);
    assert_ne!(first, second);
    assert_eq!(store.rows.len(), count);
    let mut corrupt: Value = serde_json::from_str(&second).unwrap();
    corrupt["world"]["infrastructure"]["stations"][0]["jobs"][0]["owner"] = json!(999);
    assert!(decode(&corrupt.to_string(), &mut store).is_err());
    let mut corrupt: Value = serde_json::from_str(&second).unwrap();
    corrupt["world"]["archives"][0]["records"] = json!([record]);
    assert!(decode(&corrupt.to_string(), &mut store).is_err());
}
#[test]
fn pinned_evidence_keeps_the_callers_valid_nonascending_order() {
    let mut world = world();
    let state = &world.participants[&1];
    let sources: Vec<u64> = state
        .experiences
        .iter()
        .rev()
        .take(2)
        .map(|e| e.source)
        .collect();
    assert_eq!(sources.len(), 2);
    let cursor = state.cursor;
    send(
        &mut world,
        1,
        "pin",
        Command::PinObservation {
            observed_cursor: cursor,
            sources,
        },
    );
    round_trip(&world, &mut MemoryBlobs::default());
}

fn law_world() -> World {
    use simulation::{
        law_research::{LawCase, LawEvidence, LawWork},
        laws::{self, LawFault, LawRef, LawRevision, LawScope, PendingLaw},
    };
    let scenario: Scenario =
        serde_json::from_str(include_str!("../../scenarios/infrastructure-baseline.json")).unwrap();
    let mut world = World::new("sim-law-storage".into(), scenario).unwrap();
    world.enable_participants();
    let owner = world.players[0].id;
    let artifact = laws::compile(&laws::LawDraft {
        interface_version: 1,
        source: format!(
            "fn cost(c) {{ 2 }} //{}",
            "private authored source ".repeat(300)
        ),
    })
    .unwrap();
    for revision in 1..=127 {
        world
            .laws
            .history
            .entry("universal".into())
            .or_default()
            .insert(
                revision,
                LawRevision {
                    reference: LawRef {
                        scope: LawScope::Universal,
                        revision,
                    },
                    artifact: artifact.clone(),
                    author: owner,
                    origin: revision,
                    installed_ms: revision * 1000,
                },
            );
    }
    world.laws.active.insert("universal".into(), 127);
    let reference = LawRef {
        scope: LawScope::Universal,
        revision: 127,
    };
    world.laws.faults.lock().push(LawFault {
        reference: reference.clone(),
        hook: "cost".into(),
        error: "private quarantine reason".into(),
    });
    let binding = world.law_binding_at(Some(world.players[0].position));
    assert_eq!(binding.disabled.len(), 1);
    world.laws.pending.push(PendingLaw {
        update: 120,
        expected_binding: binding.clone(),
        location: world.players[0].position,
        revision: LawRevision {
            reference: LawRef {
                scope: LawScope::Universal,
                revision: 128,
            },
            artifact: artifact.clone(),
            author: owner,
            origin: 128,
            installed_ms: 128000,
        },
    });
    let program:simulation::knowledge::Record=serde_json::from_value(json!({"id":"private-law","topic":"law code","text":"physical code copy","author":owner,"origin":7,"confidence":10,"law_program":artifact})).unwrap();
    let cases = vec![LawCase {
        hook: "cost".into(),
        input: json!({"skill":"gather","private_case":"private evidence ".repeat(100)}),
        expected: json!(99),
    }];
    let evidence = LawEvidence {
        operator: owner,
        station: world.infrastructure.stations[0].seed.id,
        job: 42,
        scope: LawScope::Universal,
        binding: binding.clone(),
        program_hash: artifact.source_hash.clone(),
        input_hash: "fixture".into(),
        cases: cases.clone(),
        results: vec![Err("private experiment failed".into())],
        successful: false,
        paid_quanta: 3,
    };
    let report:simulation::knowledge::Record=serde_json::from_value(json!({"id":"failed-law-result","topic":"law experiment","text":"failed","author":owner,"origin":8,"confidence":10,"law_experiment":evidence})).unwrap();
    let mut job:simulation::infrastructure::ComputeJob=serde_json::from_value(json!({"id":42,"owner":owner,"submitted_ms":0,"source":7,"input":null,"input_hash":"fixture","sources":[program],"progress":3,"required":3,"last_quantum_ms":3000,"report":report,"retrieved":false})).unwrap();
    job.law_work = Some(LawWork {
        scope: LawScope::Universal,
        binding: binding.clone(),
        program_record: program.clone(),
        cases,
    });
    world.infrastructure.stations[0].jobs.push(job);
    world.players[0].knowledge.push(
        serde_json::from_value(
            json!({"record":program,"source":7,"interpretation":null,"confidence":null}),
        )
        .unwrap(),
    );
    world.archives.push(serde_json::from_value(json!({"id":999,"position":0,"label":"law copies","capacity":32,"records":[program,report],"destroyed":false,"revision":1})).unwrap());
    world.players[0].execution = Some(simulation::Execution {
        dialogue: false,
        decision: 10,
        tree: bonsai_bt::Behavior::Sequence(vec![]),
        cursor: 0,
        attempt: Some(11),
        remaining: 100,
        script: Some(simulation::scripting::Invocation {
            law_binding: Some(binding.clone()),
            law_position: Some(world.players[0].position),
            definition: binding.base,
            evaluated_ms: 0,
            wake_at_ms: 1000,
            state: json!({"fixture":"pinned invocation"}),
        }),
        policy: None,
        state: Default::default(),
    });
    world
}
#[test]
fn mature_law_history_pending_quarantine_and_private_jobs_round_trip_without_payload_rewrites() {
    let mut world = law_world();
    let mut store = MemoryBlobs::default();
    let original = json_world(&world);
    let first = round_trip(&world, &mut store);
    let count = store.rows.len();
    assert!(original.to_string().len() > 800_000);
    let compact: Value = serde_json::from_str(&first).unwrap();
    assert_eq!(compact["world"]["laws"]["history"], json!({}));
    assert_eq!(compact["world"]["laws"]["pending"], json!([]));
    assert_eq!(compact["world"]["laws"]["faults"], json!([]));
    assert!(compact["world"]["infrastructure"]["stations"][0]["jobs"][0]
        .get("law_work")
        .is_none());
    let mut changed_bytes = 0;
    for step in 1..=20 {
        world.timing.time_ms = step * 50;
        world.timing.updates = step;
        world.infrastructure.stations[0].jobs[0].progress = step as u32;
        world.infrastructure.stations[0].jobs[0].last_quantum_ms = Some(step * 50);
        world.laws.pending[0].update = step;
        world.laws.reported_faults = 1;
        let next = round_trip(&world, &mut store);
        changed_bytes += next.len();
        assert_eq!(store.rows.len(), count);
    }
    eprintln!("law storage fixture: {} full World bytes; {} compact envelope bytes; {} immutable rows; {} compact bytes across 20 progress updates; 0 new immutable rows", original.to_string().len(), first.len(), count, changed_bytes);
    assert!(
        changed_bytes < original.to_string().len() * 2,
        "mutable envelopes must exclude mature law source payloads"
    );
    let before = json_world(&world);
    let restored = decode(&round_trip(&world, &mut store), &mut store).unwrap();
    restored
        .laws
        .faults
        .lock()
        .push(simulation::laws::LawFault {
            reference: world.laws.history["universal"][&127].reference.clone(),
            hook: "visible".into(),
            error: "branch only".into(),
        });
    assert_eq!(json_world(&world), before);
    round_trip(&restored, &mut store);
}
#[test]
fn physical_copy_erasure_and_author_death_preserve_installed_history_and_pinned_binding() {
    let mut world = law_world();
    let history = serde_json::to_value(&world.laws.history).unwrap();
    let binding = serde_json::to_value(
        &world.players[0]
            .execution
            .as_ref()
            .unwrap()
            .script
            .as_ref()
            .unwrap()
            .law_binding,
    )
    .unwrap();
    let mut store = MemoryBlobs::default();
    round_trip(&world, &mut store);
    world.players[0].health = 0;
    world.players[0].knowledge.clear();
    world.infrastructure.stations[0].jobs.clear();
    world.archives.last_mut().unwrap().records.clear();
    world.archives.last_mut().unwrap().destroyed = true;
    let restored = decode(&round_trip(&world, &mut store), &mut store).unwrap();
    assert_eq!(
        serde_json::to_value(&restored.laws.history).unwrap(),
        history
    );
    assert_eq!(
        serde_json::to_value(
            &restored.players[0]
                .execution
                .as_ref()
                .unwrap()
                .script
                .as_ref()
                .unwrap()
                .law_binding
        )
        .unwrap(),
        binding
    );
    assert!(restored.infrastructure.stations[0].jobs.is_empty());
    assert!(restored.players[0].knowledge.is_empty());
}
#[test]
fn law_reference_scope_metadata_inline_payloads_and_fault_cursor_fail_closed() {
    let world = law_world();
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let original: Value = serde_json::from_str(&encoded.state).unwrap();
    for mode in 0..6 {
        let mut bad = original.clone();
        match mode {
            0 => {
                bad["layout"]["laws"]["history"]["universal"]["1"] =
                    bad["layout"]["laws"]["history"]["universal"]["2"].clone()
            }
            1 => bad["layout"]["laws"]["pending"][0]["reference"]["revision"] = json!(1),
            2 => bad["world"]["laws"]["history"] = json_world(&world)["laws"]["history"].clone(),
            3 => bad["world"]["laws"]["reported_faults"] = json!(2),
            4 => {
                bad["world"]["infrastructure"]["stations"][0]["jobs"][0]["law_work"] =
                    json_world(&world)["infrastructure"]["stations"][0]["jobs"][0]["law_work"]
                        .clone()
            }
            _ => {
                bad["layout"]["laws"]["faults"][0] =
                    bad["layout"]["laws"]["history"]["universal"]["1"].clone()
            }
        }
        assert!(decode(&bad.to_string(), &mut store).is_err(), "mode {mode}");
    }
}
#[test]
fn pre_law_normalized_envelope_remains_readable() {
    let world = world();
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let mut old: Value = serde_json::from_str(&encoded.state).unwrap();
    old["layout"].as_object_mut().unwrap().remove("laws");
    old["world"].as_object_mut().unwrap().remove("laws");
    assert_eq!(
        json_world(&decode(&old.to_string(), &mut store).unwrap()),
        json_world(&world)
    );
}

fn four_read_world() -> World {
    let mut world = world();
    world
        .participants
        .get_mut(&1)
        .unwrap()
        .evidence_leases
        .clear();
    world.participants.get_mut(&1).unwrap().receipts.clear();
    // Build a real 128-item ReadObservation page through the kernel's event and
    // command paths. Escaping and nested content must survive the RawValue path.
    for index in 0..140 {
        world.event(Some(1), "perception", vec![], json!({
            "kind":"storage fixture", "index":index,
            "content":{"text":"quote\" newline\n slash\\ unicode λ", "nested":[null,true,{"n":index}]}
        }));
    }
    for number in 1..=4 {
        world.timing.time_ms += 1;
        world.event(
            Some(1),
            "perception",
            vec![],
            json!({"kind":"new read", "number":number}),
        );
        send(
            &mut world,
            1,
            &format!("read-{number}"),
            Command::ReadObservation {
                after: 0,
                limit: 128,
            },
        );
    }
    assert_eq!(world.participants[&1].evidence_leases.len(), 4);
    assert!(world.participants[&1]
        .evidence_leases
        .iter()
        .all(|l| l.experiences.len() == 128));
    world
}

fn expanded(
    world: &World,
    actor: u32,
    layout: &storage_codec::Layout,
    store: &mut MemoryBlobs,
) -> Value {
    let private = status(world, actor, layout).unwrap();
    let actual: Value =
        serde_json::from_str(&expand_status(&world.run, actor, &private, store).unwrap()).unwrap();
    assert_eq!(actual, world.participant_status(actor).unwrap());
    actual
}

#[test]
fn assembled_four_read_cache_preserves_full_pages_order_and_immutable_capture() {
    let mut world = four_read_world();
    let mut store = MemoryBlobs::default();
    reset_fragment_assembly_count();
    let first = encode(&world, &mut store).unwrap();
    assert_eq!(fragment_assembly_count(), 4);
    assert_eq!(store.interns("captured_read_v1"), 4);
    assert_eq!(derived_fragment_ids(&first.layout).len(), 4);
    store.clear_counts();
    let captured = expanded(&world, 1, &first.layout, &mut store)["read_observations"].clone();
    assert_eq!(
        captured
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r["request_id"].as_str().unwrap())
            .collect::<Vec<_>>(),
        vec!["read-1", "read-2", "read-3", "read-4"]
    );
    assert!(captured
        .as_array()
        .unwrap()
        .iter()
        .all(|r| r["observation"]["experiences"].as_array().unwrap().len() == 128));
    assert!(captured.to_string().contains("unicode λ"));
    assert_eq!(store.gets("captured_read_v1"), 4);
    assert_eq!(store.gets("observation"), 0);
    assert_eq!(store.gets("experience"), 0);
    assert_eq!(
        store.interns_by_kind.len(),
        0,
        "view expansion must be read only"
    );
    assert_eq!(
        fragment_assembly_count(),
        4,
        "mapped view must not assemble fragments again"
    );

    // Trace rotation and mutable status changes must not rewrite old captures.
    for index in 0..300 {
        world.event(
            Some(1),
            "perception",
            vec![],
            json!({"kind":"later trace", "index":index}),
        );
    }
    world.timing.time_ms += 1;
    world.timing.updates += 1;
    let (_, previous) = decode_with_layout(&first.state, &mut store).unwrap();
    store.clear_counts();
    reset_fragment_assembly_count();
    let second = encode_with_previous(&world, &mut store, Some(&previous)).unwrap();
    assert_eq!(fragment_assembly_count(), 0);
    assert_eq!(store.interns("captured_read_v1"), 0);
    assert_eq!(store.gets("captured_read_v1"), 0);
    assert_eq!(
        derived_fragment_ids(&second.layout),
        derived_fragment_ids(&previous)
    );
    assert_eq!(
        expanded(&world, 1, &second.layout, &mut store)["read_observations"],
        captured
    );
    assert_eq!(
        json_world(&decode(&second.state, &mut store).unwrap()),
        json_world(&world)
    );
}

#[test]
fn warm_save_reuses_without_fragment_fetch_or_assembly_and_new_read_builds_once() {
    let mut world = four_read_world();
    let mut store = MemoryBlobs::default();
    let first = encode(&world, &mut store).unwrap();
    let (restored, mut layout) = decode_with_layout(&first.state, &mut store).unwrap();
    assert_eq!(json_world(&restored), json_world(&world));
    for _ in 0..3 {
        world.timing.time_ms += 1;
        world.timing.updates += 1;
        store.clear_counts();
        reset_fragment_assembly_count();
        let next = encode_with_previous(&world, &mut store, Some(&layout)).unwrap();
        assert_eq!(fragment_assembly_count(), 0);
        assert_eq!(store.interns("captured_read_v1"), 0);
        assert_eq!(store.gets("captured_read_v1"), 0);
        layout = next.layout;
    }
    send(
        &mut world,
        1,
        "read-5",
        Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    );
    store.clear_counts();
    reset_fragment_assembly_count();
    let next = encode_with_previous(&world, &mut store, Some(&layout)).unwrap();
    assert_eq!(fragment_assembly_count(), 1);
    assert_eq!(store.interns("captured_read_v1"), 1);
    assert_eq!(store.gets("captured_read_v1"), 0);
    let old = derived_fragment_ids(&layout);
    let new = derived_fragment_ids(&next.layout);
    assert_eq!(old.intersection(&new).count(), 3);
    assert_eq!(old.difference(&new).count(), 1);
    assert_eq!(new.difference(&old).count(), 1);
    let actual = expanded(&world, 1, &next.layout, &mut store);
    assert_eq!(
        actual["read_observations"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r["request_id"].as_str().unwrap())
            .collect::<Vec<_>>(),
        vec!["read-2", "read-3", "read-4", "read-5"]
    );
}

#[test]
fn cache_eligibility_matches_native_at_inclusive_expiry_control_change_and_pinned_only() {
    let mut world = four_read_world();
    let mut store = MemoryBlobs::default();
    let first = encode(&world, &mut store).unwrap();
    let mut previous = first.layout;
    let first_expiry = world.participants[&1].evidence_leases[0].expires_ms;
    let last_expiry = world.participants[&1].evidence_leases[3].expires_ms;
    for (time, expected) in [
        (first_expiry, 4),
        (first_expiry + 1, 3),
        (last_expiry, 1),
        (last_expiry + 1, 0),
    ] {
        world.timing.time_ms = time;
        reset_fragment_assembly_count();
        let next = encode_with_previous(&world, &mut store, Some(&previous)).unwrap();
        assert_eq!(fragment_assembly_count(), 0);
        assert_eq!(
            derived_fragment_ids(&next.layout).len(),
            4,
            "expired retained leases remain reachable until kernel eviction"
        );
        assert_eq!(
            expanded(&world, 1, &next.layout, &mut store)["read_observations"]
                .as_array()
                .unwrap()
                .len(),
            expected
        );
        previous = next.layout;
    }
    world.change_control(1).unwrap();
    let controlled = encode_with_previous(&world, &mut store, Some(&previous)).unwrap();
    assert!(derived_fragment_ids(&controlled.layout).is_empty());
    assert_eq!(
        expanded(&world, 1, &controlled.layout, &mut store)["read_observations"],
        json!([])
    );
    let cursor = world.participants[&1].cursor;
    let sources = world.participants[&1]
        .experiences
        .iter()
        .rev()
        .take(2)
        .map(|e| e.source)
        .collect();
    send(
        &mut world,
        1,
        "only-pin",
        Command::PinObservation {
            observed_cursor: cursor,
            sources,
        },
    );
    reset_fragment_assembly_count();
    let pinned = encode_with_previous(&world, &mut store, Some(&controlled.layout)).unwrap();
    assert_eq!(fragment_assembly_count(), 0);
    assert!(derived_fragment_ids(&pinned.layout).is_empty());
    assert!(world.participants[&1]
        .evidence_leases
        .iter()
        .all(|l| l.observation.get() == "null"));
    assert_eq!(
        expanded(&world, 1, &pinned.layout, &mut store)["read_observations"],
        json!([])
    );
}

#[test]
fn mapped_fragment_corruption_and_valid_cross_lease_swaps_fail_closed() {
    let mut world = four_read_world();
    send(
        &mut world,
        2,
        "actor-two",
        Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    );
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let private = status(&world, 1, &encoded.layout).unwrap();
    let cache: Value = serde_json::from_str(&private).unwrap();
    let refs = cache["captured_reads"].as_object().unwrap();
    let pairs: Vec<(String, u64)> = refs
        .iter()
        .map(|(k, v)| (k.clone(), v.as_u64().unwrap()))
        .collect();
    let fragment = pairs[0].1;
    for mode in 0..8 {
        let mut bad = store.clone();
        if mode == 0 {
            bad.rows.remove(&fragment);
        } else {
            let row = bad.rows.get_mut(&fragment).unwrap();
            match mode {
                1 => row.0 = "another-run".into(),
                2 => row.1 = Some(2),
                3 => row.2 = "captured_read_future".into(),
                4 => row.3 = "{}".into(), // Hash mismatch.
                5 => {
                    let mut body: Value = serde_json::from_str(&row.3).unwrap();
                    body["lease"] = json!(pairs[1].0.parse::<u64>().unwrap());
                    row.3 = body.to_string();
                    row.4 = blob_key(&row.0, row.1, &row.2, &row.3); // Valid hash; wrong canonical lease.
                }
                6 => {
                    row.3=json!({"lease":pairs[0].0.parse::<u64>().unwrap(),"observation":{},"future_field":true}).to_string();
                    row.4 = blob_key(&row.0, row.1, &row.2, &row.3);
                }
                _ => {
                    let mut body: Value = serde_json::from_str(&row.3).unwrap();
                    body["observation"]["actor"] = json!(2);
                    row.3 = body.to_string();
                    row.4 = blob_key(&row.0, row.1, &row.2, &row.3);
                }
            }
        }
        bad.clear_counts();
        assert!(
            expand_status(&world.run, 1, &private, &mut bad).is_err(),
            "fragment corruption mode {mode}"
        );
        assert_eq!(bad.interns_by_kind.len(), 0);
        assert_eq!(
            bad.gets("observation"),
            0,
            "present invalid cache may not silently fall back"
        );
    }
    for replacement in [
        0,
        999_999,
        pairs[1].1,
        *store
            .rows
            .iter()
            .find(|(_, r)| r.1 == Some(2) && r.2 == "captured_read_v1")
            .unwrap()
            .0,
    ] {
        let mut bad = cache.clone();
        bad["captured_reads"][&pairs[0].0] = json!(replacement);
        assert!(
            expand_status(&world.run, 1, &bad.to_string(), &mut store).is_err(),
            "replacement {replacement}"
        );
    }
    let mut extra = cache.clone();
    extra["captured_reads"]["999999"] = json!(fragment);
    assert!(expand_status(&world.run, 1, &extra.to_string(), &mut store).is_err());
    let mut stale_epoch = cache.clone();
    stale_epoch["head"]["control_epoch"] = json!(world.participants[&1].control_epoch + 1);
    assert!(expand_status(&world.run, 1, &stale_epoch.to_string(), &mut store).is_err());
}

#[test]
fn old_envelopes_and_status_rows_fall_back_then_upgrade_without_changing_world() {
    let world = four_read_world();
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let mut old_world: Value = serde_json::from_str(&encoded.state).unwrap();
    old_world["layout"]
        .as_object_mut()
        .unwrap()
        .remove("captured_reads");
    let mut old_status: Value =
        serde_json::from_str(&status(&world, 1, &encoded.layout).unwrap()).unwrap();
    old_status.as_object_mut().unwrap().remove("captured_reads");
    store.rows.retain(|_, row| row.2 != "captured_read_v1");
    let (restored, previous) = decode_with_layout(&old_world.to_string(), &mut store).unwrap();
    assert_eq!(json_world(&restored), json_world(&world));
    assert!(derived_fragment_ids(&previous).is_empty());
    store.clear_counts();
    reset_fragment_assembly_count();
    let actual: Value = serde_json::from_str(
        &expand_status(&world.run, 1, &old_status.to_string(), &mut store).unwrap(),
    )
    .unwrap();
    assert_eq!(actual, world.participant_status(1).unwrap());
    assert_eq!(fragment_assembly_count(), 4);
    assert_eq!(store.gets("observation"), 4);
    assert_eq!(store.gets("experience"), 4 * 128);
    assert_eq!(store.gets("captured_read_v1"), 0);
    assert!(store.interns_by_kind.is_empty());
    store.clear_counts();
    reset_fragment_assembly_count();
    let upgraded = encode_with_previous(&restored, &mut store, Some(&previous)).unwrap();
    assert_eq!(fragment_assembly_count(), 4);
    assert_eq!(store.interns("captured_read_v1"), 4);
    assert_eq!(
        json_world(&decode(&upgraded.state, &mut store).unwrap()),
        json_world(&world)
    );
    expanded(&world, 1, &upgraded.layout, &mut store);
}

// The memory transaction models reference reachability; it does not claim to
// exercise database rollback or the production adapter's actual table deletes.
fn memory_commit(previous: &str, world: &World, store: &mut MemoryBlobs) -> String {
    memory_commit_checked(previous, world, store).unwrap()
}
fn memory_commit_checked(
    previous: &str,
    world: &World,
    store: &mut MemoryBlobs,
) -> Result<String, String> {
    store.clear_counts();
    let (_, layout) = decode_with_layout(previous, store)?;
    let mut old = store.fetched.clone();
    old.extend(derived_fragment_ids(&layout));
    store.clear_counts();
    let next = encode_with_previous(world, store, Some(&layout))?;
    let mut live = store.interned.clone();
    live.extend(derived_fragment_ids(&next.layout));
    for (id, actor) in derived_fragment_owners(&layout) {
        if !live.contains(&id) {
            store.get(&world.run, Some(actor), "captured_read_v1", id)?;
        }
    }
    for orphan in old.difference(&live) {
        store.rows.remove(orphan);
    }
    assert_eq!(
        json_world(&decode(&next.state, store).unwrap()),
        json_world(world)
    );
    for actor in world.participants.keys() {
        expanded(world, *actor, &next.layout, store);
    }
    Ok(next.state)
}

#[test]
fn reference_reachability_collects_evicted_fragments_but_retains_live_shared_evidence() {
    let mut world = four_read_world();
    let mut store = MemoryBlobs::default();
    let first = encode(&world, &mut store).unwrap();
    let original_fragments = derived_fragment_ids(&first.layout);
    let first_cache: Value =
        serde_json::from_str(&status(&world, 1, &first.layout).unwrap()).unwrap();
    let oldest = world.participants[&1].evidence_leases[0].request_id.clone();
    assert_eq!(oldest, "read-1");
    send(
        &mut world,
        1,
        "read-5",
        Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    );
    let committed = memory_commit(&first.state, &world, &mut store);
    let (_, layout) = decode_with_layout(&committed, &mut store).unwrap();
    let live = derived_fragment_ids(&layout);
    assert_eq!(original_fragments.intersection(&live).count(), 3);
    assert!(original_fragments
        .difference(&live)
        .all(|id| !store.rows.contains_key(id)));
    assert!(live.iter().all(|id| store.rows.contains_key(id)));
    assert!(store.rows.values().any(|r| r.2 == "experience"));
    // The removed fragment was never fetched by World hydration, yet was swept.
    assert!(first_cache["captured_reads"]
        .as_object()
        .unwrap()
        .values()
        .any(|id| !store.rows.contains_key(&id.as_u64().unwrap())));
    world.change_control(1).unwrap();
    let controlled = memory_commit(&committed, &world, &mut store);
    let (_, layout) = decode_with_layout(&controlled, &mut store).unwrap();
    assert!(derived_fragment_ids(&layout).is_empty());
    assert!(store.rows.values().all(|r| r.2 != "captured_read_v1"));
    assert!(
        store.rows.values().any(|r| r.2 == "experience"),
        "current trace remains live"
    );
}

#[test]
fn derived_layout_rejects_wrong_scope_unknown_leases_zero_aliases_and_pinned_refs() {
    let mut world = four_read_world();
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let original: Value = serde_json::from_str(&encoded.state).unwrap();
    let pairs: Vec<(String, Value)> = original["layout"]["captured_reads"]["actors"]["1"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    for mode in 0..5 {
        let mut bad = original.clone();
        match mode {
            0 => bad["layout"]["captured_reads"]["run"] = json!("wrong-run"),
            1 => {
                let actor = bad["layout"]["captured_reads"]["actors"]["1"].clone();
                bad["layout"]["captured_reads"]["actors"]["99999"] = actor;
            }
            2 => bad["layout"]["captured_reads"]["actors"]["1"]["99999"] = json!(99999),
            3 => bad["layout"]["captured_reads"]["actors"]["1"][&pairs[0].0] = json!(0),
            _ => bad["layout"]["captured_reads"]["actors"]["1"][&pairs[0].0] = pairs[1].1.clone(),
        }
        store.clear_counts();
        assert!(
            decode_with_layout(&bad.to_string(), &mut store).is_err(),
            "derived layout mode {mode}"
        );
        assert_eq!(
            store.gets("captured_read_v1"),
            0,
            "small-reference validation must not fetch bodies"
        );
    }
    world.change_control(1).unwrap();
    let cursor = world.participants[&1].cursor;
    let sources = world.participants[&1]
        .experiences
        .iter()
        .rev()
        .take(2)
        .map(|e| e.source)
        .collect();
    send(
        &mut world,
        1,
        "pin-for-corruption",
        Command::PinObservation {
            observed_cursor: cursor,
            sources,
        },
    );
    let pinned = encode(&world, &mut store).unwrap();
    let mut bad: Value = serde_json::from_str(&pinned.state).unwrap();
    let lease = bad["layout"]["participants"]["1"]["leases"][0]
        .as_u64()
        .unwrap()
        .to_string();
    bad["layout"]["captured_reads"]["actors"]["1"] = json!({lease:pairs[0].1});
    assert!(decode_with_layout(&bad.to_string(), &mut store).is_err());
}

#[test]
fn corrupt_evicted_reference_cannot_collect_another_runs_fragment() {
    let mut world = four_read_world();
    let mut committed = MemoryBlobs::default();
    let encoded = encode(&world, &mut committed).unwrap();
    let mut foreign = World::new("other-storage-run".into(), world.initial.clone()).unwrap();
    foreign.enable_participants();
    send(
        &mut foreign,
        1,
        "foreign-read",
        Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    );
    let foreign_encoded = encode(&foreign, &mut committed).unwrap();
    let foreign_id = *derived_fragment_ids(&foreign_encoded.layout)
        .iter()
        .next()
        .unwrap();
    let foreign_row = committed.rows[&foreign_id].clone();
    let mut bad: Value = serde_json::from_str(&encoded.state).unwrap();
    let first = bad["layout"]["captured_reads"]["actors"]["1"]
        .as_object_mut()
        .unwrap()
        .values_mut()
        .next()
        .unwrap();
    *first = json!(foreign_id);
    // Reference-only hydration is intentional. Deleting an evicted reference
    // still requires scope/content validation before any commit-side sweep.
    decode_with_layout(&bad.to_string(), &mut committed).unwrap();
    world.change_control(1).unwrap();
    let old_rows = committed.rows.clone();
    let mut transaction = committed.clone();
    assert!(memory_commit_checked(&bad.to_string(), &world, &mut transaction).is_err());
    assert_eq!(committed.rows, old_rows);
    assert_eq!(transaction.rows[&foreign_id], foreign_row);
    assert_eq!(
        json_world(&decode(&foreign_encoded.state, &mut committed).unwrap()),
        json_world(&foreign)
    );
}

struct FailAfterFragment<'a> {
    store: &'a mut MemoryBlobs,
    staged_fragment: bool,
}
impl Blobs for FailAfterFragment<'_> {
    fn intern(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        body: String,
    ) -> Result<u64, String> {
        if self.staged_fragment {
            return Err("injected failure after new fragment".into());
        }
        let id = self.store.intern(run, actor, kind, body)?;
        if kind == "captured_read_v1" {
            self.staged_fragment = true;
        }
        Ok(id)
    }
    fn get(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<String, String> {
        self.store.get(run, actor, kind, id)
    }
    fn retain_validated(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<(), String> {
        self.store.retain_validated(run, actor, kind, id)
    }
}

#[test]
fn failed_transaction_after_fragment_creation_preserves_committed_world_status_and_refs() {
    let mut world = four_read_world();
    let mut committed = MemoryBlobs::default();
    let initial = encode(&world, &mut committed).unwrap();
    let old_world = json_world(&world);
    let old_status = expanded(&world, 1, &initial.layout, &mut committed);
    let old_rows = committed.rows.clone();
    send(
        &mut world,
        1,
        "not-committed",
        Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    );
    let mut transaction = committed.clone();
    let mut failing = FailAfterFragment {
        store: &mut transaction,
        staged_fragment: false,
    };
    assert!(encode_with_previous(&world, &mut failing, Some(&initial.layout)).is_err());
    assert!(failing.staged_fragment);
    assert!(
        transaction.rows.len() > old_rows.len(),
        "fixture must stage a derived blob before failing"
    );
    assert_eq!(committed.rows, old_rows);
    let (restored, layout) = decode_with_layout(&initial.state, &mut committed).unwrap();
    assert_eq!(json_world(&restored), old_world);
    assert_eq!(expanded(&restored, 1, &layout, &mut committed), old_status);
    assert!(derived_fragment_ids(&layout)
        .iter()
        .all(|id| committed.rows.contains_key(id)));
}

fn reset_reuse_counts(store: &mut MemoryBlobs) {
    store.clear_counts();
    reset_fragment_assembly_count();
    reset_lease_validation_count();
}

#[test]
fn validated_lease_hits_skip_payload_intern_and_validation_but_keep_mutable_trace_receipts() {
    let fixture = four_read_world();
    let mut store = MemoryBlobs::default();
    let initial = encode(&fixture, &mut store).unwrap();
    store.begin_transaction();
    reset_lease_validation_count();
    let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
    assert_eq!(
        lease_validation_count(),
        4,
        "load validates each lease exactly once"
    );
    assert_eq!(
        json_world(&world),
        json_world(&fixture),
        "transient tokens never enter World JSON"
    );
    world.timing.time_ms += 1;
    world.timing.updates += 1;
    world.event(
        Some(1),
        "perception",
        vec![],
        json!({"kind":"mutable trace still serialized"}),
    );
    let trace_count: usize = world
        .participants
        .values()
        .map(|p| p.experiences.len())
        .sum();
    let receipt_count: usize = world.participants.values().map(|p| p.receipts.len()).sum();
    let mut slow_store = store.clone();
    reset_reuse_counts(&mut store);
    let fast = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).unwrap();
    assert_eq!(lease_validation_count(), 0);
    assert_eq!(fragment_assembly_count(), 0);
    assert_eq!(store.interns("observation"), 0);
    assert_eq!(store.interns("lease"), 0);
    assert_eq!(
        store.interns("experience"),
        1,
        "only the appended trace entry needs interning"
    );
    assert_eq!(store.interns("receipt"), receipt_count);
    assert_eq!(store.retains("observation"), 4);
    assert_eq!(store.retains("lease"), 4);
    assert_eq!(store.retains("experience"), 4 * 128 + trace_count - 1);
    assert_eq!(
        store.gets_by_kind.len(),
        0,
        "fast retention never fetches bodies"
    );
    reset_reuse_counts(&mut slow_store);
    let slow = encode_with_previous(&world, &mut slow_store, Some(&layout)).unwrap();
    assert_eq!(lease_validation_count(), 4);
    assert_eq!(slow_store.interns("observation"), 4);
    assert_eq!(slow_store.interns("experience"), trace_count + 4 * 128);
    assert_eq!(fast.state, slow.state);
    assert_eq!(
        json_world(&decode(&fast.state, &mut store).unwrap()),
        json_world(&world)
    );
    for actor in world.participants.keys() {
        expanded(&world, *actor, &fast.layout, &mut store);
    }
}

#[test]
fn strong_reuse_owners_block_get_mut_and_make_mut_detaches_into_the_validated_slow_path() {
    let mut store = MemoryBlobs::default();
    let initial = encode(&four_read_world(), &mut store).unwrap();
    store.begin_transaction();
    let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
    let lease = &mut world.participants.get_mut(&1).unwrap().evidence_leases[0];
    assert!(std::sync::Arc::get_mut(&mut lease.observation).is_none());
    assert!(std::sync::Arc::get_mut(&mut lease.experiences).is_none());
    let original = lease.experiences.clone();
    let original_location = original[0].location;
    std::sync::Arc::make_mut(&mut lease.experiences)[0].location += 1;
    assert!(!std::sync::Arc::ptr_eq(&original, &lease.experiences));
    assert_eq!(original[0].location, original_location);
    let mut slow_store = store.clone();
    reset_reuse_counts(&mut store);
    let fast = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).unwrap();
    assert_eq!(lease_validation_count(), 1);
    assert_eq!(fragment_assembly_count(), 1);
    assert_eq!(store.interns("observation"), 1);
    assert_eq!(store.interns("lease"), 1);
    assert_eq!(store.retains("lease"), 3);
    let slow = encode_with_previous(&world, &mut slow_store, Some(&layout)).unwrap();
    assert_eq!(fast.state, slow.state);
    expanded(&world, 1, &fast.layout, &mut store);

    // The extra ownership belongs to the transient token, not an immortal cache.
    let (mut fresh, _, fresh_reuse) = decode_for_save(&initial.state, &mut store).unwrap();
    drop(fresh_reuse);
    let lease = &mut fresh.participants.get_mut(&1).unwrap().evidence_leases[0];
    assert!(std::sync::Arc::get_mut(&mut lease.observation).is_some());
    assert!(std::sync::Arc::get_mut(&mut lease.experiences).is_some());
}

#[test]
fn equal_content_new_arc_allocations_miss_reuse_and_invalid_detached_payloads_fail() {
    let mut base = MemoryBlobs::default();
    let initial = encode(&four_read_world(), &mut base).unwrap();
    for replace_observation in [true, false] {
        let mut store = base.clone();
        store.begin_transaction();
        let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
        let lease = &mut world.participants.get_mut(&1).unwrap().evidence_leases[0];
        if replace_observation {
            let replacement =
                serde_json::value::RawValue::from_string(lease.observation.get().to_owned())
                    .unwrap();
            lease.observation = replacement.into();
        } else {
            lease.experiences = std::sync::Arc::new((*lease.experiences).clone());
        }
        reset_reuse_counts(&mut store);
        let next = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).unwrap();
        assert_eq!(lease_validation_count(), 1);
        assert_eq!(store.interns("lease"), 1);
        assert_eq!(store.interns("observation"), 1);
        assert_eq!(store.retains("lease"), 3);
        assert_eq!(
            fragment_assembly_count(),
            0,
            "equal canonical content can still reuse its assembled fragment"
        );
        assert_eq!(next.state, initial.state);
        expanded(&world, 1, &next.layout, &mut store);
    }
    for corrupt_observation in [true, false] {
        let mut store = base.clone();
        store.begin_transaction();
        let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
        let lease = &mut world.participants.get_mut(&1).unwrap().evidence_leases[0];
        if corrupt_observation {
            let mut body: Value = serde_json::from_str(lease.observation.get()).unwrap();
            body["actor"] = json!(2);
            lease.observation = serde_json::value::to_raw_value(&body).unwrap().into();
        } else {
            std::sync::Arc::make_mut(&mut lease.experiences).swap(0, 1);
        }
        reset_reuse_counts(&mut store);
        assert!(encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).is_err());
        assert_eq!(
            lease_validation_count(),
            1,
            "detachment cannot bypass canonical validation"
        );
        assert_eq!(store.retains("lease"), 0);
    }
}

#[test]
fn all_lease_scalar_and_scope_changes_miss_the_fast_path_and_preserve_slow_validation() {
    let mut base = MemoryBlobs::default();
    let initial = encode(&four_read_world(), &mut base).unwrap();
    for change in ["request_id", "cursor", "expiry", "epoch", "actor", "run"] {
        let mut store = base.clone();
        store.begin_transaction();
        let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
        match change {
            "request_id" => {
                world.participants.get_mut(&1).unwrap().evidence_leases[0].request_id =
                    "renamed-read".into()
            }
            "cursor" => {
                world.participants.get_mut(&1).unwrap().evidence_leases[0].observed_cursor += 1
            }
            "expiry" => world.participants.get_mut(&1).unwrap().evidence_leases[0].expires_ms += 1,
            "epoch" => world.participants.get_mut(&1).unwrap().control_epoch += 1,
            "actor" => {
                let lease = world
                    .participants
                    .get_mut(&1)
                    .unwrap()
                    .evidence_leases
                    .remove(0);
                world
                    .participants
                    .get_mut(&1)
                    .unwrap()
                    .evidence_leases
                    .clear();
                world
                    .participants
                    .get_mut(&2)
                    .unwrap()
                    .evidence_leases
                    .push(lease);
            }
            _ => world.run = "different-reuse-run".into(),
        }
        let previous = if change == "run" { None } else { Some(&layout) };
        let mut slow_store = store.clone();
        reset_reuse_counts(&mut store);
        let fast = encode_with_reuse(&world, &mut store, previous, Some(&reuse));
        let validations = lease_validation_count();
        let slow = encode_with_previous(&world, &mut slow_store, previous);
        assert_eq!(fast.is_ok(), slow.is_ok(), "scope/scalar {change}");
        if change == "request_id" {
            assert_eq!(validations, 1);
            assert_eq!(store.retains("lease"), 3);
            let fast = fast.unwrap();
            assert_eq!(fast.state, slow.unwrap().state);
            expanded(&world, 1, &fast.layout, &mut store);
        } else {
            assert!(fast.is_err(), "scope/scalar {change}");
            assert_eq!(store.retains("lease"), 0);
            assert_eq!(validations, usize::from(change != "run"));
        }
    }
}

#[test]
fn reordered_and_expired_leases_and_pins_retain_exact_order_and_inclusive_eligibility() {
    let mut fixture = four_read_world();
    let cursor = fixture.participants[&2].cursor;
    let sources = fixture.participants[&2]
        .experiences
        .iter()
        .rev()
        .take(2)
        .map(|e| e.source)
        .collect();
    send(
        &mut fixture,
        2,
        "reused-pin",
        Command::PinObservation {
            observed_cursor: cursor,
            sources,
        },
    );
    let mut store = MemoryBlobs::default();
    let initial = encode(&fixture, &mut store).unwrap();
    store.begin_transaction();
    let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
    world
        .participants
        .get_mut(&1)
        .unwrap()
        .evidence_leases
        .reverse();
    let first_expiry = world.participants[&1]
        .evidence_leases
        .last()
        .unwrap()
        .expires_ms;
    for (time, count) in [(first_expiry, 4), (first_expiry + 1, 3)] {
        world.timing.time_ms = time;
        reset_reuse_counts(&mut store);
        let next = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).unwrap();
        assert_eq!(lease_validation_count(), 0);
        assert_eq!(store.retains("lease"), 5);
        assert_eq!(store.retains("observation"), 4);
        assert_eq!(store.interns("lease"), 0);
        let actual = expanded(&world, 1, &next.layout, &mut store);
        assert_eq!(actual["read_observations"].as_array().unwrap().len(), count);
        assert_eq!(actual["read_observations"][0]["request_id"], "read-4");
        assert_eq!(
            expanded(&world, 2, &next.layout, &mut store)["read_observations"],
            json!([])
        );
    }
}

#[test]
fn fast_retain_rejects_missing_and_wrong_scope_catalog_entries_without_unchecked_fallback() {
    let mut base = MemoryBlobs::default();
    let initial = encode(&four_read_world(), &mut base).unwrap();
    for mode in [
        "unvalidated",
        "missing-lease",
        "wrong-run",
        "wrong-actor",
        "wrong-kind",
    ] {
        let mut store = base.clone();
        store.begin_transaction();
        let (world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
        let state: Value = serde_json::from_str(&initial.state).unwrap();
        let id = state["layout"]["participants"]["1"]["leases"][0]
            .as_u64()
            .unwrap();
        match mode {
            "unvalidated" => store.validated.clear(),
            "missing-lease" => {
                store.validated.remove(&id);
            }
            "wrong-run" => store.validated.get_mut(&id).unwrap().0 = "foreign".into(),
            "wrong-actor" => store.validated.get_mut(&id).unwrap().1 = Some(2),
            _ => store.validated.get_mut(&id).unwrap().2 = "experience".into(),
        }
        reset_reuse_counts(&mut store);
        assert!(
            encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).is_err(),
            "catalog mode {mode}"
        );
        assert_eq!(
            lease_validation_count(),
            0,
            "invalid token retention must fail instead of silently retrying slow"
        );
        assert_eq!(store.gets_by_kind.len(), 0);
        assert!(store.retained.is_empty());
    }
    assert!(base
        .retain_validated("sim-storage", Some(1), "lease", 0)
        .is_err());
    assert!(base
        .retain_validated("sim-storage", Some(1), "lease", u64::MAX)
        .is_err());
}

#[test]
fn canonical_fast_reuse_collects_evicted_ids_but_keeps_shared_evidence_and_current_reads() {
    let mut store = MemoryBlobs::default();
    let initial = encode(&four_read_world(), &mut store).unwrap();
    store.begin_transaction();
    let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
    let mut old_ids = store.fetched.clone();
    old_ids.extend(derived_fragment_ids(&layout));
    let private: Value = serde_json::from_str(&initial.state).unwrap();
    let ids = private["layout"]["participants"]["1"]["leases"]
        .as_array()
        .unwrap();
    let evicted_lease = ids[0].as_u64().unwrap();
    let old: Value = serde_json::from_str(&store.rows[&evicted_lease].3).unwrap();
    let second: Value = serde_json::from_str(&store.rows[&ids[1].as_u64().unwrap()].3).unwrap();
    let shared = old["experiences"]
        .as_array()
        .unwrap()
        .iter()
        .find(|id| second["experiences"].as_array().unwrap().contains(id))
        .unwrap()
        .as_u64()
        .unwrap();
    let evicted_observation = old["observation"].as_u64().unwrap();
    send(
        &mut world,
        1,
        "new-fifth",
        Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    );
    let mut slow_store = store.clone();
    reset_reuse_counts(&mut store);
    let next = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).unwrap();
    assert_eq!(lease_validation_count(), 1);
    assert_eq!(store.interns("observation"), 1);
    assert_eq!(store.interns("lease"), 1);
    assert_eq!(store.retains("lease"), 3);
    assert_eq!(store.retains("observation"), 3);
    assert!(!store.retained.contains(&evicted_lease));
    assert!(!store.retained.contains(&evicted_observation));
    assert!(store.retained.contains(&shared));
    let slow = encode_with_previous(&world, &mut slow_store, Some(&layout)).unwrap();
    assert_eq!(next.state, slow.state);
    let mut live = store.interned.clone();
    live.extend(&store.retained);
    live.extend(derived_fragment_ids(&next.layout));
    for (id, actor) in derived_fragment_owners(&layout) {
        if !live.contains(&id) {
            store
                .get(&world.run, Some(actor), "captured_read_v1", id)
                .unwrap();
        }
    }
    for orphan in old_ids.difference(&live) {
        store.rows.remove(orphan);
    }
    assert!(!store.rows.contains_key(&evicted_lease));
    assert!(!store.rows.contains_key(&evicted_observation));
    assert!(store.rows.contains_key(&shared));
    assert_eq!(
        json_world(&decode(&next.state, &mut store).unwrap()),
        json_world(&world)
    );
    expanded(&world, 1, &next.layout, &mut store);
    // Dropped leases' transient strong owners cannot retain durable data after
    // control reset. The ordinary modeled commit checks the next empty layout.
    world.change_control(1).unwrap();
    memory_commit(&next.state, &world, &mut store);
    assert!(store
        .rows
        .values()
        .all(|row| row.2 != "captured_read_v1" && row.2 != "lease" && row.2 != "observation"));
}

#[test]
fn fast_reuse_transaction_failure_keeps_the_previous_committed_world_and_reachability() {
    let mut committed = MemoryBlobs::default();
    let initial = encode(&four_read_world(), &mut committed).unwrap();
    let old_rows = committed.rows.clone();
    let mut transaction = committed.clone();
    transaction.begin_transaction();
    let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut transaction).unwrap();
    let old_world = json_world(&world);
    send(
        &mut world,
        1,
        "rolled-back-fast-read",
        Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    );
    reset_reuse_counts(&mut transaction);
    let mut failing = FailAfterFragment {
        store: &mut transaction,
        staged_fragment: false,
    };
    assert!(encode_with_reuse(&world, &mut failing, Some(&layout), Some(&reuse)).is_err());
    assert!(failing.staged_fragment);
    assert_eq!(transaction.retains("lease"), 3);
    assert_eq!(lease_validation_count(), 1);
    assert_eq!(committed.rows, old_rows);
    let restored = decode(&initial.state, &mut committed).unwrap();
    assert_eq!(json_world(&restored), old_world);
    expanded(&restored, 1, &layout, &mut committed);
}

fn referenced_experiences(state: &str, store: &MemoryBlobs) -> BTreeSet<(u32, u64)> {
    let stored: Value = serde_json::from_str(state).unwrap();
    let mut result = BTreeSet::new();
    for (actor, participant) in stored["layout"]["participants"].as_object().unwrap() {
        let actor = actor.parse::<u32>().unwrap();
        for id in participant["trace"].as_array().unwrap() {
            result.insert((actor, id.as_u64().unwrap()));
        }
        for id in participant["leases"].as_array().unwrap() {
            let lease: Value = serde_json::from_str(&store.rows[&id.as_u64().unwrap()].3).unwrap();
            for id in lease["experiences"].as_array().unwrap() {
                result.insert((actor, id.as_u64().unwrap()));
            }
        }
    }
    result
}

#[test]
fn typed_experience_decode_memo_fetches_each_scoped_id_once_across_trace_and_four_reads() {
    let world = four_read_world();
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let expected = referenced_experiences(&encoded.state, &store);
    let occurrence_count: usize = world
        .participants
        .values()
        .map(|p| {
            p.experiences.len()
                + p.evidence_leases
                    .iter()
                    .map(|l| l.experiences.len())
                    .sum::<usize>()
        })
        .sum();
    assert!(
        occurrence_count > expected.len() + 400,
        "fixture must repeatedly reference cached IDs"
    );
    store.begin_transaction();
    reset_experience_decode_count();
    let (restored, layout, reuse) = decode_for_save(&encoded.state, &mut store).unwrap();
    assert_eq!(store.gets("experience"), expected.len());
    assert_eq!(experience_decode_count(), expected.len());
    for (actor, id) in &expected {
        assert_eq!(
            store
                .gets_by_scope
                .get(&(world.run.clone(), Some(*actor), "experience".into(), *id)),
            Some(&1)
        );
    }
    assert_eq!(json_world(&restored), json_world(&world));
    for actor in restored.participants.keys() {
        expanded(&restored, *actor, &layout, &mut store);
    }
    // Memo misses still populate the adapter Catalog, so canonical retain/GC
    // has every referenced ID even when repeats did not call the adapter again.
    reset_reuse_counts(&mut store);
    let next = encode_with_reuse(&restored, &mut store, Some(&layout), Some(&reuse)).unwrap();
    assert_eq!(lease_validation_count(), 0);
    let trace_count: usize = restored
        .participants
        .values()
        .map(|p| p.experiences.len())
        .sum();
    assert_eq!(store.retains("experience"), 4 * 128 + trace_count);
    assert_eq!(next.state, encoded.state);
}

#[test]
fn typed_experience_memo_clones_mutable_metadata_between_trace_and_captured_lists() {
    let world = four_read_world();
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let mut restored = decode(&encoded.state, &mut store).unwrap();
    let leases = &restored.participants[&1].evidence_leases;
    let shared = leases[0]
        .experiences
        .iter()
        .find(|e| {
            leases[1]
                .experiences
                .iter()
                .any(|other| other.source == e.source)
        })
        .unwrap()
        .source;
    let first_index = leases[0]
        .experiences
        .iter()
        .position(|e| e.source == shared)
        .unwrap();
    let second_index = leases[1]
        .experiences
        .iter()
        .position(|e| e.source == shared)
        .unwrap();
    let before = serde_json::to_value(&leases[0].experiences[first_index]).unwrap();
    let trace = restored
        .participants
        .get_mut(&1)
        .unwrap()
        .experiences
        .iter_mut()
        .find(|e| e.source == shared)
        .unwrap();
    // Populating immutable ExperienceData's parsed memo is harmless; all other
    // Experience fields must be independent owned values after typed cloning.
    let _: &Value = &trace.data;
    trace.location += 17;
    trace.tick += 3;
    trace.parents.push(999_999);
    trace.kind.push_str(" changed trace");
    assert_eq!(
        serde_json::to_value(
            &restored.participants[&1].evidence_leases[0].experiences[first_index]
        )
        .unwrap(),
        before
    );
    assert_eq!(
        serde_json::to_value(
            &restored.participants[&1].evidence_leases[1].experiences[second_index]
        )
        .unwrap(),
        before
    );
    let first = &mut restored.participants.get_mut(&1).unwrap().evidence_leases[0];
    let changed = &mut std::sync::Arc::make_mut(&mut first.experiences)[first_index];
    changed.location -= 23;
    changed.kind.push_str(" changed capture");
    changed.parents.push(888_888);
    assert_eq!(
        serde_json::to_value(
            &restored.participants[&1].evidence_leases[1].experiences[second_index]
        )
        .unwrap(),
        before
    );
    assert_eq!(
        json_world(&world),
        json_world(&decode(&encoded.state, &mut store).unwrap())
    );
}

#[test]
fn typed_experience_memo_never_reuses_another_actors_cached_numeric_id() {
    let world = four_read_world();
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let mut bad: Value = serde_json::from_str(&encoded.state).unwrap();
    let cached = bad["layout"]["participants"]["1"]["trace"][0]
        .as_u64()
        .unwrap();
    bad["layout"]["participants"]["2"]["trace"] = json!([cached]);
    // Avoid a cursor failure masking the required actor-scope validation.
    bad["world"]["participants"]["2"]["cursor"] = json!(u64::MAX);
    store.begin_transaction();
    reset_experience_decode_count();
    let error = match decode(&bad.to_string(), &mut store) {
        Ok(_) => panic!("foreign cached experience accepted"),
        Err(e) => e,
    };
    assert!(error.contains("scope"), "unexpected rejection: {error}");
    assert_eq!(
        store
            .gets_by_scope
            .get(&(world.run.clone(), Some(1), "experience".into(), cached)),
        Some(&1)
    );
    assert_eq!(
        store
            .gets_by_scope
            .get(&(world.run.clone(), Some(2), "experience".into(), cached)),
        Some(&1)
    );
}

#[test]
fn typed_experience_memo_revalidates_every_list_cursor_duplicates_and_read_order() {
    let world = four_read_world();
    let mut base = MemoryBlobs::default();
    let encoded = encode(&world, &mut base).unwrap();
    let original: Value = serde_json::from_str(&encoded.state).unwrap();
    let trace_count = original["layout"]["participants"]["1"]["trace"]
        .as_array()
        .unwrap()
        .len();
    let lease_id = original["layout"]["participants"]["1"]["leases"][0]
        .as_u64()
        .unwrap();
    for mode in [
        "lease-cursor",
        "lease-duplicate",
        "lease-order",
        "trace-cursor",
        "trace-duplicate",
        "trace-order",
    ] {
        let mut bad = original.clone();
        let mut store = base.clone();
        if mode.starts_with("lease") {
            // Keep the descriptor identity and scope self-consistent while
            // changing only its evidence list; all IDs were already memoized
            // through this actor's valid retained trace before this list loads.
            let row = store.rows.get_mut(&lease_id).unwrap();
            let mut refs: Value = serde_json::from_str(&row.3).unwrap();
            let ids = refs["experiences"].as_array_mut().unwrap();
            match mode {
                "lease-cursor" => ids.push(
                    bad["layout"]["participants"]["1"]["trace"]
                        .as_array()
                        .unwrap()
                        .last()
                        .unwrap()
                        .clone(),
                ),
                "lease-duplicate" => ids.push(ids[0].clone()),
                _ => ids.reverse(),
            }
            row.3 = refs.to_string();
            row.4 = blob_key(&row.0, row.1, &row.2, &row.3);
        } else {
            match mode {
                "trace-cursor" => bad["world"]["participants"]["1"]["cursor"] = json!(0),
                "trace-duplicate" => {
                    let ids = bad["layout"]["participants"]["1"]["trace"]
                        .as_array_mut()
                        .unwrap();
                    ids.push(ids[0].clone());
                }
                _ => bad["layout"]["participants"]["1"]["trace"]
                    .as_array_mut()
                    .unwrap()
                    .reverse(),
            }
        }
        store.begin_transaction();
        reset_experience_decode_count();
        let error = match decode(&bad.to_string(), &mut store) {
            Ok(_) => panic!("invalid list accepted: {mode}"),
            Err(e) => e,
        };
        assert!(
            error.contains("cursor") || error.contains("order") || error.contains("duplicate"),
            "{mode}: {error}"
        );
        if mode.starts_with("lease") {
            assert_eq!(
                store.gets("experience"),
                trace_count,
                "cached list must still validate without refetch: {mode}"
            );
            assert_eq!(experience_decode_count(), trace_count);
        }
    }
}

#[test]
fn typed_experience_memo_preserves_nonascending_pin_order_and_ends_at_decode_return() {
    let mut world = four_read_world();
    let cursor = world.participants[&1].cursor;
    let sources: Vec<u64> = world.participants[&1]
        .experiences
        .iter()
        .rev()
        .take(3)
        .map(|e| e.source)
        .collect();
    send(
        &mut world,
        1,
        "memo-pin",
        Command::PinObservation {
            observed_cursor: cursor,
            sources: sources.clone(),
        },
    );
    let mut store = MemoryBlobs::default();
    let encoded = encode(&world, &mut store).unwrap();
    let expected = referenced_experiences(&encoded.state, &store).len();
    for _ in 0..2 {
        store.begin_transaction();
        reset_experience_decode_count();
        let restored = decode(&encoded.state, &mut store).unwrap();
        assert_eq!(store.gets("experience"), expected);
        assert_eq!(
            experience_decode_count(),
            expected,
            "each decode owns its own memo"
        );
        let pin = restored.participants[&1]
            .evidence_leases
            .iter()
            .find(|l| l.request_id == "memo-pin")
            .unwrap();
        assert_eq!(
            pin.experiences.iter().map(|e| e.source).collect::<Vec<_>>(),
            sources
        );
        assert!(pin
            .experiences
            .windows(2)
            .all(|xs| xs[0].cursor > xs[1].cursor));
        assert_eq!(json_world(&restored), json_world(&world));
    }
    let id = *store
        .rows
        .iter()
        .find(|(_, row)| row.2 == "experience")
        .unwrap()
        .0;
    store.rows.get_mut(&id).unwrap().3 = "{}".into();
    store.begin_transaction();
    reset_experience_decode_count();
    assert!(
        decode(&encoded.state, &mut store).is_err(),
        "a prior decode's typed memo must not mask subsequent hash corruption"
    );
}

fn trace_world() -> World {
    let mut world = four_read_world();
    for participant in world.participants.values_mut() {
        participant.evidence_leases.clear();
    }
    world
}

#[test]
fn trace_encoding_certificate_guards_every_metadata_field_and_strong_data_identity() {
    let mut original = trace_world().participants[&1].experiences[0].clone();
    original.parents = vec![9, 4];
    let snapshot = original.clone();
    let before = serde_json::to_value(&original).unwrap();
    assert!(original.can_reuse_encoding(&snapshot));
    // The parsed OnceLock can warm without changing serialized bytes or the
    // immutable allocation identity shared by these strongly owned clones.
    let parsed: &Value = &original.data;
    assert!(parsed.is_object());
    assert_eq!(serde_json::to_value(&original).unwrap(), before);
    assert!(original.can_reuse_encoding(&snapshot));
    for field in [
        "cursor",
        "source",
        "tick",
        "location",
        "kind",
        "parents-length",
        "parents-order",
        "data-equal",
        "data-changed",
    ] {
        let mut changed = original.clone();
        match field {
            "cursor" => changed.cursor += 1,
            "source" => changed.source += 1,
            "tick" => changed.tick += 1,
            "location" => changed.location += 1,
            "kind" => changed.kind.push_str(" changed"),
            "parents-length" => changed.parents.push(7),
            "parents-order" => changed.parents.reverse(),
            "data-equal" => {
                changed.data = simulation::participant::ExperienceData::from(&*original.data)
            }
            _ => {
                changed.data =
                    simulation::participant::ExperienceData::from(&json!({"changed":true}))
            }
        }
        assert!(
            !changed.can_reuse_encoding(&snapshot),
            "certificate accepted {field}"
        );
        assert_eq!(
            serde_json::to_value(&snapshot).unwrap(),
            before,
            "snapshot mutated through {field}"
        );
        if field == "data-equal" {
            assert_eq!(serde_json::to_value(&changed).unwrap(), before);
        }
    }
    drop(original);
    let retained = snapshot.clone();
    assert!(
        retained.can_reuse_encoding(&snapshot),
        "strong snapshot remains valid after original owner drops"
    );
    let reconstructed: simulation::participant::Experience =
        serde_json::from_value(before).unwrap();
    assert!(
        !reconstructed.can_reuse_encoding(&snapshot),
        "equal JSON in a fresh allocation is a safe miss"
    );
}

#[test]
fn unchanged_trace_and_appended_entry_reuse_exact_ids_without_requiring_latest_cursor_identity() {
    let fixture = trace_world();
    let mut store = MemoryBlobs::default();
    let initial = encode(&fixture, &mut store).unwrap();
    store.begin_transaction();
    let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
    let trace_count: usize = world
        .participants
        .values()
        .map(|p| p.experiences.len())
        .sum();
    reset_reuse_counts(&mut store);
    let unchanged = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).unwrap();
    assert_eq!(store.interns("experience"), 0);
    assert_eq!(store.retains("experience"), trace_count);
    assert_eq!(unchanged.state, initial.state);
    let cursor = world.participants[&1].cursor;
    world.event(
        Some(1),
        "perception",
        vec![],
        json!({"kind":"one newly appended entry"}),
    );
    assert!(world.participants[&1].cursor > cursor);
    let mut slow_store = store.clone();
    reset_reuse_counts(&mut store);
    let fast = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).unwrap();
    assert_eq!(store.interns("experience"), 1);
    assert_eq!(store.retains("experience"), trace_count);
    assert_eq!(store.gets("experience"), 0);
    let slow = encode_with_previous(&world, &mut slow_store, Some(&layout)).unwrap();
    assert_eq!(fast.state, slow.state);
    assert_eq!(
        json_world(&decode(&fast.state, &mut store).unwrap()),
        json_world(&world)
    );
    for actor in world.participants.keys() {
        expanded(&world, *actor, &fast.layout, &mut store);
    }
}

#[test]
fn each_trace_metadata_or_payload_replacement_interns_only_that_entry_and_preserves_order_checks() {
    let mut base = MemoryBlobs::default();
    let initial = encode(&trace_world(), &mut base).unwrap();
    for field in [
        "cursor",
        "source",
        "tick",
        "location",
        "kind",
        "parents",
        "data-equal",
        "data-changed",
    ] {
        let mut store = base.clone();
        store.begin_transaction();
        let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
        let trace_count: usize = world
            .participants
            .values()
            .map(|p| p.experiences.len())
            .sum();
        let entry = &mut world.participants.get_mut(&1).unwrap().experiences[0];
        match field {
            "cursor" => entry.cursor += 1, // Duplicate of next cursor: encode preserves it; decode must still reject.
            "source" => entry.source += 100_000,
            "tick" => entry.tick += 1,
            "location" => entry.location += 1,
            "kind" => entry.kind.push_str(" amended"),
            "parents" => entry.parents.push(123_456),
            "data-equal" => {
                entry.data = simulation::participant::ExperienceData::from(&*entry.data)
            }
            _ => {
                entry.data =
                    simulation::participant::ExperienceData::from(&json!({"changed":"payload"}))
            }
        }
        let mut slow_store = store.clone();
        reset_reuse_counts(&mut store);
        let fast = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).unwrap();
        assert_eq!(store.interns("experience"), 1, "{field}");
        assert_eq!(store.retains("experience"), trace_count - 1, "{field}");
        let slow = encode_with_previous(&world, &mut slow_store, Some(&layout)).unwrap();
        assert_eq!(fast.state, slow.state, "{field}");
        if field == "cursor" {
            assert!(decode(&fast.state, &mut store).is_err());
        } else {
            assert_eq!(
                json_world(&decode(&fast.state, &mut store).unwrap()),
                json_world(&world)
            );
        }
    }
    let mut store = base.clone();
    store.begin_transaction();
    let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
    world
        .participants
        .get_mut(&1)
        .unwrap()
        .experiences
        .reverse();
    let mut slow_store = store.clone();
    reset_reuse_counts(&mut store);
    let fast = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).unwrap();
    assert_eq!(
        store.interns("experience"),
        0,
        "entry identity must not assume original list position"
    );
    let slow = encode_with_previous(&world, &mut slow_store, Some(&layout)).unwrap();
    assert_eq!(fast.state, slow.state);
    assert!(
        decode(&fast.state, &mut store).is_err(),
        "existing strict trace-order validation must remain"
    );
}

#[test]
fn trace_reuse_epoch_actor_and_run_guards_preserve_scope_and_fail_closed_retention() {
    let mut base = MemoryBlobs::default();
    let initial = encode(&trace_world(), &mut base).unwrap();
    for scope in ["epoch", "actor", "run"] {
        let mut store = base.clone();
        store.begin_transaction();
        let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
        let actor_trace = world.participants[&1].experiences.len();
        match scope {
            "epoch" => world.participants.get_mut(&1).unwrap().control_epoch += 1,
            "actor" => {
                let trace =
                    std::mem::take(&mut world.participants.get_mut(&1).unwrap().experiences);
                let cursor = world.participants[&1].cursor;
                world.participants.get_mut(&2).unwrap().experiences = trace;
                world.participants.get_mut(&2).unwrap().cursor = cursor;
            }
            _ => world.run = "foreign-trace-run".into(),
        }
        let mut slow_store = store.clone();
        reset_reuse_counts(&mut store);
        let fast = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse));
        if scope == "run" {
            assert!(fast.is_err());
            assert_eq!(store.retains("experience"), 0);
        } else {
            assert_eq!(store.interns("experience"), actor_trace, "{scope}");
            let fast = fast.unwrap();
            let slow = encode_with_previous(&world, &mut slow_store, Some(&layout)).unwrap();
            assert_eq!(fast.state, slow.state);
            assert_eq!(
                json_world(&decode(&fast.state, &mut store).unwrap()),
                json_world(&world)
            );
        }
    }
    for wrong_scope in [false, true] {
        let mut store = base.clone();
        store.begin_transaction();
        let (world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
        let encoded: Value = serde_json::from_str(&initial.state).unwrap();
        let id = encoded["layout"]["participants"]["1"]["trace"][0]
            .as_u64()
            .unwrap();
        if wrong_scope {
            store.validated.get_mut(&id).unwrap().1 = Some(2);
        } else {
            store.validated.remove(&id);
        }
        reset_reuse_counts(&mut store);
        assert!(encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).is_err());
        assert_eq!(
            store.interns("experience"),
            0,
            "invalid retained Catalog ID may not silently fall back"
        );
        assert_eq!(store.gets("experience"), 0);
    }
}

#[test]
fn trace_eviction_drops_token_only_ids_and_preserves_lease_shared_canonical_evidence() {
    let mut store = MemoryBlobs::default();
    let initial = encode(&four_read_world(), &mut store).unwrap();
    store.begin_transaction();
    let (mut world, layout, reuse) = decode_for_save(&initial.state, &mut store).unwrap();
    let mut old_ids = store.fetched.clone();
    old_ids.extend(derived_fragment_ids(&layout));
    let encoded: Value = serde_json::from_str(&initial.state).unwrap();
    let trace_ids: Vec<u64> = encoded["layout"]["participants"]["1"]["trace"]
        .as_array()
        .unwrap()
        .iter()
        .map(|id| id.as_u64().unwrap())
        .collect();
    let mut lease_ids = BTreeSet::new();
    for id in encoded["layout"]["participants"]["1"]["leases"]
        .as_array()
        .unwrap()
    {
        let refs: Value = serde_json::from_str(&store.rows[&id.as_u64().unwrap()].3).unwrap();
        lease_ids.extend(
            refs["experiences"]
                .as_array()
                .unwrap()
                .iter()
                .map(|id| id.as_u64().unwrap()),
        );
    }
    let orphan = *trace_ids
        .iter()
        .find(|id| !lease_ids.contains(id))
        .expect("fixture needs an old trace entry outside captured pages");
    let shared = *trace_ids.iter().find(|id| lease_ids.contains(id)).unwrap();
    for index in 0..300 {
        world.event(
            Some(1),
            "perception",
            vec![],
            json!({"kind":"rotate trace", "index":index}),
        );
    }
    let mut slow_store = store.clone();
    reset_reuse_counts(&mut store);
    let fast = encode_with_reuse(&world, &mut store, Some(&layout), Some(&reuse)).unwrap();
    assert_eq!(
        store.interns("experience"),
        simulation::participant::TRACE_LIMIT
    );
    assert!(
        !store.retained.contains(&orphan),
        "token ownership must not retain an evicted trace-only ID"
    );
    assert!(
        store.retained.contains(&shared),
        "current leases still retain evicted trace evidence"
    );
    let slow = encode_with_previous(&world, &mut slow_store, Some(&layout)).unwrap();
    assert_eq!(fast.state, slow.state);
    let mut live = store.interned.clone();
    live.extend(&store.retained);
    live.extend(derived_fragment_ids(&fast.layout));
    for (id, actor) in derived_fragment_owners(&layout) {
        if !live.contains(&id) {
            store
                .get(&world.run, Some(actor), "captured_read_v1", id)
                .unwrap();
        }
    }
    for id in old_ids.difference(&live) {
        store.rows.remove(id);
    }
    assert!(!store.rows.contains_key(&orphan));
    assert!(store.rows.contains_key(&shared));
    assert_eq!(
        json_world(&decode(&fast.state, &mut store).unwrap()),
        json_world(&world)
    );
    expanded(&world, 1, &fast.layout, &mut store);
}
