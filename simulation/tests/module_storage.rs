//! Exercise the exact pure codec used by the module without a database runtime.
#[path = "../../server/module/spacetimedb/src/foundation/storage_codec.rs"]
mod storage_codec;
use serde_json::{json, Value};
use simulation::{
    participant::{Command, Request, API_VERSION, EVIDENCE_LEASE_MS},
    Scenario, World,
};
use std::collections::BTreeMap;
use storage_codec::{blob_key, decode, encode, expand_status, status, Blobs};

#[derive(Clone, Default)]
struct MemoryBlobs {
    rows: BTreeMap<u64, (String, Option<u32>, String, String, String)>,
    next: u64,
}
impl Blobs for MemoryBlobs {
    fn intern(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        body: String,
    ) -> Result<u64, String> {
        let key = blob_key(run, actor, kind, &body);
        if let Some((id, row)) = self.rows.iter().find(|(_, row)| row.4 == key) {
            if row.0 != run || row.1 != actor || row.2 != kind || row.3 != body {
                return Err("collision".into());
            }
            return Ok(*id);
        }
        self.next += 1;
        self.rows
            .insert(self.next, (run.into(), actor, kind.into(), body, key));
        Ok(self.next)
    }
    fn get(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<String, String> {
        let row = self.rows.get(&id).ok_or("missing")?;
        if row.0 != run
            || row.1 != actor
            || row.2 != kind
            || row.4 != blob_key(run, actor, kind, &row.3)
        {
            return Err("scope or content mismatch".into());
        }
        Ok(row.3.clone())
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
