//! Direct tests of the production adapter's staged lookup/validation boundary.
//! Memory rows substitute only for host table access; no database rollback or
//! actual compound-index selection is inferred from these tests.
use super::*;
use serde_json::{json, Value};
use simulation::participant::{Command, Request, API_VERSION};
use simulation::Scenario;

fn blob(id: u64, run: &str, actor: Option<u32>, kind: &str, body: &str) -> SimWorldBlob {
    SimWorldBlob {
        id,
        key: codec::blob_key(run, actor, kind, body),
        run: run.into(),
        actor,
        kind: kind.into(),
        body: body.into(),
    }
}
fn get(
    catalog: &mut Catalog,
    raw: &mut BTreeMap<u64, SimWorldBlob>,
    id: u64,
) -> Result<String, String> {
    staged_cached(catalog, raw, "run", Some(1), "experience", id, || {
        panic!("a staged/cached hit must not point-fetch")
    })
}

#[test]
fn staged_rows_are_lazy_and_only_validated_requests_enter_the_catalog() {
    let valid = blob(1, "run", Some(1), "experience", "valid body");
    let mut corrupt = blob(2, "run", Some(1), "experience", "orphan");
    corrupt.body = "corrupt unreferenced body".into();
    let mut raw = BTreeMap::from([(1, valid), (2, corrupt)]);
    let mut catalog = Catalog::default();
    assert!(catalog.blobs.is_empty() && catalog.keys.is_empty() && catalog.live.is_empty());
    assert_eq!(get(&mut catalog, &mut raw, 1).unwrap(), "valid body");
    assert_eq!(catalog.blobs.keys().copied().collect::<Vec<_>>(), vec![1]);
    assert_eq!(catalog.keys.len(), 1);
    assert!(catalog.live.is_empty());
    assert_eq!(raw.keys().copied().collect::<Vec<_>>(), vec![2]);
    assert_eq!(get(&mut catalog, &mut raw, 1).unwrap(), "valid body");
    assert_eq!(
        raw.len(),
        1,
        "cached hit must not consume unrelated staging"
    );
    assert!(get(&mut catalog, &mut raw, 2).is_err());
    assert_eq!(catalog.blobs.len(), 1, "failed validation must not promote");
}

#[test]
fn raw_hits_preserve_every_first_use_identity_scope_and_hash_check() {
    for kind in PREFETCH_KINDS {
        for fault in ["zero", "id", "run", "actor", "none", "kind", "body", "key"] {
            let mut row = blob(1, "run", Some(1), kind, "payload");
            let requested = if fault == "zero" { 0 } else { 1 };
            match fault {
                "zero" => row.id = 0,
                "id" => row.id = 2,
                "run" => row.run = "other".into(),
                "actor" => row.actor = Some(2),
                "none" => row.actor = None,
                "kind" => row.kind = "captured_read_v1".into(),
                "body" => row.body = "changed".into(),
                "key" => row.key.push('x'),
                _ => unreachable!(),
            }
            let mut raw = BTreeMap::from([(requested, row)]);
            let mut catalog = Catalog::default();
            assert!(
                staged_cached(
                    &mut catalog,
                    &mut raw,
                    "run",
                    Some(1),
                    kind,
                    requested,
                    || { panic!("invalid staged rows must fail without point fallback") }
                )
                .is_err(),
                "accepted {kind} {fault}"
            );
            assert!(catalog.blobs.is_empty() && catalog.keys.is_empty() && catalog.live.is_empty());
        }
    }
}

#[test]
fn promoted_rows_reject_cross_scope_hits_and_numeric_key_aliases() {
    let first = blob(1, "run", Some(1), "experience", "same payload");
    let mut alias = first.clone();
    alias.id = 2;
    let mut raw = BTreeMap::from([(1, first), (2, alias)]);
    let mut catalog = Catalog::default();
    get(&mut catalog, &mut raw, 1).unwrap();
    for (run, actor, kind) in [
        ("other", Some(1), "experience"),
        ("run", Some(2), "experience"),
        ("run", None, "experience"),
        ("run", Some(1), "lease"),
    ] {
        assert!(
            staged_cached(&mut catalog, &mut raw, run, actor, kind, 1, || panic!(
                "cached scope mismatch must not fetch"
            ))
            .is_err()
        );
    }
    assert_eq!(
        get(&mut catalog, &mut raw, 2).unwrap_err(),
        "immutable key aliases numeric identities"
    );
    assert_eq!(catalog.blobs.keys().copied().collect::<Vec<_>>(), vec![1]);
    assert_eq!(catalog.keys.values().copied().collect::<Vec<_>>(), vec![1]);
    assert!(catalog.live.is_empty());
}

#[test]
fn missing_and_unselected_rows_keep_the_original_point_lookup_behavior() {
    let mut catalog = Catalog::default();
    let mut raw = BTreeMap::new();
    let mut fetches = 0;
    assert!(staged_cached(
        &mut catalog,
        &mut raw,
        "run",
        Some(1),
        "experience",
        1,
        || {
            fetches += 1;
            None
        }
    )
    .is_err());
    assert_eq!(fetches, 1);
    let body = staged_cached(&mut catalog, &mut raw, "run", Some(1), "lease", 2, || {
        fetches += 1;
        Some(blob(2, "run", Some(1), "lease", "lease body"))
    })
    .unwrap();
    assert_eq!(body, "lease body");
    assert_eq!(fetches, 2);
    assert_eq!(
        staged_cached(
            &mut catalog,
            &mut raw,
            "run",
            Some(1),
            "lease",
            2,
            || panic!("repeat lookup")
        )
        .unwrap(),
        body
    );
}

#[test]
fn raw_rows_cannot_authorize_retention_or_enter_canonical_gc_candidates() {
    let mut raw = BTreeMap::from([
        (1, blob(1, "run", Some(1), "experience", "shared")),
        (2, blob(2, "run", Some(1), "experience", "evicted")),
        (3, blob(3, "run", Some(1), "experience", "unreferenced")),
    ]);
    let mut catalog = Catalog::default();
    assert!(retain_validated(&mut catalog, "run", Some(1), "experience", 1).is_err());
    get(&mut catalog, &mut raw, 1).unwrap();
    get(&mut catalog, &mut raw, 2).unwrap();
    for (run, actor, kind) in [
        ("other", Some(1), "experience"),
        ("run", Some(2), "experience"),
        ("run", Some(1), "lease"),
    ] {
        assert!(retain_validated(&mut catalog, run, actor, kind, 1).is_err());
    }
    retain_validated(&mut catalog, "run", Some(1), "experience", 1).unwrap();
    // Exact canonical set boundary used by commit; derived layout validation
    // remains independently covered by codec and actual-runtime regressions.
    let previous: BTreeSet<_> = catalog.blobs.keys().copied().collect();
    let dead: Vec<_> = previous.difference(&catalog.live).copied().collect();
    assert_eq!(dead, vec![2]);
    assert!(!previous.contains(&3));
    let mut next_transaction = Catalog::default();
    assert!(retain_validated(&mut next_transaction, "run", Some(1), "experience", 1).is_err());
}

#[derive(Default)]
struct FixtureStore {
    rows: BTreeMap<u64, SimWorldBlob>,
    catalog: Catalog,
    staged: BTreeMap<u64, SimWorldBlob>,
    point_gets: BTreeMap<String, usize>,
}
impl FixtureStore {
    fn begin(rows: &BTreeMap<u64, SimWorldBlob>, run: &str, prefetch: bool) -> Self {
        Self {
            rows: rows.clone(),
            staged: if prefetch {
                prefetch_selected_blobs(|kind| {
                    rows.values()
                        .filter(move |row| row.run == run && row.kind == kind)
                        .cloned()
                })
            } else {
                BTreeMap::new()
            },
            ..Self::default()
        }
    }
    fn point_gets(&self, kind: &str) -> usize {
        self.point_gets.get(kind).copied().unwrap_or(0)
    }
}
impl Blobs for FixtureStore {
    fn get(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<String, String> {
        staged_cached(
            &mut self.catalog,
            &mut self.staged,
            run,
            actor,
            kind,
            id,
            || {
                *self.point_gets.entry(kind.into()).or_default() += 1;
                self.rows.get(&id).cloned()
            },
        )
    }
    fn retain_validated(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<(), String> {
        retain_validated(&mut self.catalog, run, actor, kind, id)
    }
    fn intern(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        body: String,
    ) -> Result<u64, String> {
        // Supply host-table identity allocation/deduplication for fixture
        // construction. Content validation and retention use production code.
        let key = codec::blob_key(run, actor, kind, &body);
        let id = match self.rows.values().find(|row| row.key == key) {
            Some(row) => row.id,
            None => {
                let id = self.rows.keys().next_back().copied().unwrap_or(0) + 1;
                self.rows.insert(id, blob(id, run, actor, kind, &body));
                id
            }
        };
        if self.get(run, actor, kind, id)? != body {
            return Err("fixture hash collision".into());
        }
        self.retain_validated(run, actor, kind, id)?;
        Ok(id)
    }
}
fn command(world: &mut World, request_id: &str) {
    let request = Request {
        api_version: API_VERSION.into(),
        request_id: request_id.into(),
        control_epoch: world.participants[&1].control_epoch,
        command: Command::ReadObservation {
            after: 0,
            limit: 128,
        },
    };
    assert!(world.participant_apply(1, request).unwrap().ok);
}
fn fixture_world() -> World {
    let mut scenario: Scenario = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../scenarios/survival.json"
    )))
    .unwrap();
    for site in &mut scenario.sites {
        site.hazard = 0;
    }
    let mut world = World::new("adapter-prefetch".into(), scenario).unwrap();
    world.enable_participants();
    world.advance_ms(2500);
    world.event(
        Some(1),
        "resource_change",
        vec![],
        json!({"location":0,"food_delta":-1}),
    );
    for index in 0..140 {
        world.event(
            Some(1),
            "perception",
            vec![],
            json!({"kind":"adapter fixture","index":index,"text":"quote\" newline\n λ"}),
        );
    }
    for index in 0..4 {
        world.timing.time_ms += 1;
        command(&mut world, &format!("read-{index}"));
    }
    assert_eq!(world.participants[&1].evidence_leases.len(), 4);
    world
}
fn world_json(world: &World) -> Value {
    serde_json::to_value(world).unwrap()
}
fn exact_status(world: &World, layout: &codec::Layout, store: &mut FixtureStore) {
    for actor in world.participants.keys() {
        let compact = codec::status(world, *actor, layout).unwrap();
        // Same empty-staging behavior as status_for_view, using actual helper.
        let mut status_store = FixtureStore::begin(&store.rows, &world.run, false);
        let actual: Value = serde_json::from_str(
            &codec::expand_status(&world.run, *actor, &compact, &mut status_store).unwrap(),
        )
        .unwrap();
        let expected: Value =
            serde_json::from_str(&world.participant_status_json(*actor).unwrap()).unwrap();
        assert_eq!(actual, expected);
    }
}

#[test]
fn prefetched_full_world_decode_matches_point_reads_through_mutation_and_gc() {
    let initial_world = fixture_world();
    let mut committed = FixtureStore::default();
    let encoded = codec::encode(&initial_world, &mut committed).unwrap();
    let orphan = committed.rows.keys().next_back().unwrap() + 1;
    committed.rows.insert(
        orphan,
        blob(
            orphan,
            &initial_world.run,
            Some(1),
            "experience",
            "unreferenced orphan",
        ),
    );
    committed.rows.get_mut(&orphan).unwrap().key = "corrupt orphan key".into();
    let foreign = orphan + 1;
    committed.rows.insert(
        foreign,
        blob(foreign, "other-run", Some(1), "experience", "foreign"),
    );
    let baseline_rows = committed.rows.clone();
    for mutation in ["unchanged", "append", "fifth-read", "control-reset"] {
        let mut slow = FixtureStore::begin(&baseline_rows, &initial_world.run, false);
        let mut fast = FixtureStore::begin(&baseline_rows, &initial_world.run, true);
        let (mut slow_world, slow_layout, slow_reuse) =
            codec::decode_for_save(&encoded.state, &mut slow).unwrap();
        let (mut fast_world, fast_layout, fast_reuse) =
            codec::decode_for_save(&encoded.state, &mut fast).unwrap();
        assert_eq!(world_json(&fast_world), world_json(&slow_world));
        for kind in PREFETCH_KINDS {
            assert_eq!(fast.point_gets(kind), 0, "staged {kind} missed");
            assert!(slow.point_gets(kind) > 0, "fixture lacks {kind}");
        }
        assert!(slow.point_gets("experience") > 100);
        assert!(!fast.catalog.blobs.contains_key(&orphan));
        assert!(!fast.catalog.blobs.contains_key(&foreign));
        // Hydration's temporary Writer drops raw leftovers before mutation.
        fast.staged.clear();
        for world in [&mut fast_world, &mut slow_world] {
            match mutation {
                "append" => {
                    world.event(Some(1), "perception", vec![], json!({"kind":"appended"}));
                }
                "fifth-read" => {
                    world.timing.time_ms += 1;
                    command(world, "fifth");
                }
                "control-reset" => {
                    world.change_control(1).unwrap();
                }
                _ => {}
            }
        }
        slow.catalog.live.clear();
        fast.catalog.live.clear();
        let slow_next = codec::encode_with_reuse(
            &slow_world,
            &mut slow,
            Some(&slow_layout),
            Some(&slow_reuse),
        )
        .unwrap();
        let fast_next = codec::encode_with_reuse(
            &fast_world,
            &mut fast,
            Some(&fast_layout),
            Some(&fast_reuse),
        )
        .unwrap();
        assert_eq!(
            fast_next.state, slow_next.state,
            "state differs after {mutation}"
        );
        let mut collected = Vec::new();
        for (store, layout, next) in [
            (&mut slow, &slow_layout, &slow_next),
            (&mut fast, &fast_layout, &fast_next),
        ] {
            store
                .catalog
                .live
                .extend(codec::derived_fragment_ids(&next.layout));
            let mut previous: BTreeSet<_> = store.catalog.blobs.keys().copied().collect();
            for (id, actor) in codec::derived_fragment_owners(layout) {
                if !store.catalog.live.contains(&id) {
                    validate(
                        &store.rows[&id],
                        &initial_world.run,
                        Some(actor),
                        "captured_read_v1",
                        id,
                    )
                    .unwrap();
                }
                previous.insert(id);
            }
            let dead: BTreeSet<_> = previous.difference(&store.catalog.live).copied().collect();
            assert!(!dead.contains(&orphan) && !dead.contains(&foreign));
            for id in &dead {
                store.rows.remove(id);
            }
            collected.push(dead);
        }
        assert_eq!(collected[0], collected[1], "GC differs after {mutation}");
        let mut view = FixtureStore::begin(&fast.rows, &initial_world.run, true);
        let full = codec::decode(&fast_next.state, &mut view).unwrap();
        assert_eq!(world_json(&full), world_json(&fast_world));
        for kind in PREFETCH_KINDS {
            assert_eq!(view.point_gets(kind), 0, "full World Reader missed {kind}");
        }
        exact_status(&fast_world, &fast_next.layout, &mut fast);
    }
}

#[test]
fn selected_kind_prefetch_scopes_rows_and_leaves_unused_rows_unvalidated() {
    let mut rows = BTreeMap::new();
    for kind in ["experience", "memory", "activity", "receipt"] {
        for (run, actor) in [("run", 1), ("run", 2), ("foreign", 1)] {
            let id = rows.len() as u64 + 1;
            let mut row = blob(id, run, Some(actor), kind, "payload");
            if actor == 2 {
                row.key = "corrupt unreferenced row".into();
            }
            rows.insert(id, row);
        }
    }
    for kind in ["observation", "lease", "captured_read_v1"] {
        let id = rows.len() as u64 + 1;
        rows.insert(id, blob(id, "run", Some(1), kind, "unselected"));
    }
    let mut queries = Vec::new();
    let mut staged = prefetch_selected_blobs(|kind| {
        queries.push(("run", kind));
        rows.values()
            .filter(move |row| row.run == "run" && row.kind == kind)
            .cloned()
    });
    assert_eq!(
        queries,
        vec![
            ("run", "experience"),
            ("run", "memory"),
            ("run", "activity"),
            ("run", "receipt")
        ]
    );
    assert_eq!(staged.len(), 8);
    let mut catalog = Catalog::default();
    for row in staged.values() {
        assert!(retain_validated(&mut catalog, "run", row.actor, &row.kind, row.id).is_err());
    }
    let requested: Vec<_> = staged
        .values()
        .filter(|row| row.actor == Some(1))
        .cloned()
        .collect();
    for row in requested {
        assert_eq!(
            staged_cached(
                &mut catalog,
                &mut staged,
                "run",
                row.actor,
                &row.kind,
                row.id,
                || panic!("selected kind must be staged")
            )
            .unwrap(),
            row.body
        );
        retain_validated(&mut catalog, "run", row.actor, &row.kind, row.id).unwrap();
    }
    assert_eq!(catalog.blobs.len(), 4);
    assert_eq!(catalog.live.len(), 4);
    assert_eq!(staged.len(), 4);
    for row in staged.values() {
        assert!(retain_validated(&mut catalog, "run", row.actor, &row.kind, row.id).is_err());
        assert!(!catalog.blobs.contains_key(&row.id));
        assert!(!catalog.live.contains(&row.id));
    }
}

#[test]
fn corruption_in_a_new_transaction_is_not_masked_by_prior_prefetch_validation() {
    let world = fixture_world();
    let mut committed = FixtureStore::default();
    let encoded = codec::encode(&world, &mut committed).unwrap();
    let baseline_keys: Vec<_> = committed
        .rows
        .values()
        .map(|row| (row.id, row.key.clone(), row.body.clone()))
        .collect();
    let mut first = FixtureStore::begin(&committed.rows, &world.run, true);
    codec::decode_for_save(&encoded.state, &mut first).unwrap();
    let referenced = *first
        .catalog
        .blobs
        .iter()
        .find(|(_, row)| row.kind == "experience")
        .unwrap()
        .0;
    let mut failed = FixtureStore::begin(&committed.rows, &world.run, true);
    failed.staged.get_mut(&referenced).unwrap().body = "{}".into();
    assert!(codec::decode_for_save(&encoded.state, &mut failed).is_err());
    assert!(!failed.catalog.blobs.contains_key(&referenced));
    assert_eq!(
        committed
            .rows
            .values()
            .map(|row| (row.id, row.key.clone(), row.body.clone()))
            .collect::<Vec<_>>(),
        baseline_keys
    );
    let mut restored = FixtureStore::begin(&committed.rows, &world.run, true);
    assert_eq!(
        world_json(&codec::decode(&encoded.state, &mut restored).unwrap()),
        world_json(&world)
    );
}

fn stored_run(id: &str, owner: Identity, state: String) -> SimRunStore {
    SimRunStore {
        id: id.into(),
        owner,
        state,
        last_advanced_at: spacetimedb::Timestamp::UNIX_EPOCH,
    }
}

#[test]
fn owner_export_denies_missing_foreign_participant_and_observer_before_reader_creation() {
    let owner = Identity::from_byte_array([1; 32]);
    // An observer/participant grant is deliberately not an input to this
    // owner-only decision; identities with any such grants remain nonowners.
    for caller in [
        Identity::from_byte_array([2; 32]),
        Identity::from_byte_array([3; 32]),
        Identity::ZERO,
    ] {
        let missing = decode_owned_export::<FixtureStore>(None, caller, |_| {
            panic!("missing run must not prefetch")
        });
        let foreign = decode_owned_export::<FixtureStore>(
            Some(stored_run("private", owner, "corrupt private root".into())),
            caller,
            |_| panic!("foreign run must not prefetch or hydrate"),
        );
        assert_eq!(missing.err().unwrap(), "run unavailable");
        assert_eq!(foreign.err().unwrap(), "run unavailable");
    }
}

#[test]
fn owner_export_is_exact_repeatable_and_survives_source_row_changes_after_decode() {
    let original = fixture_world();
    let owner = Identity::from_byte_array([1; 32]);
    let mut source = FixtureStore::default();
    let encoded = codec::encode(&original, &mut source).unwrap();
    let original_bytes = serde_json::to_string(&original).unwrap();
    for _ in 0..2 {
        let world = decode_owned_export(
            Some(stored_run(&original.run, owner, encoded.state.clone())),
            owner,
            |run| FixtureStore::begin(&source.rows, run, true),
        )
        .unwrap();
        assert_eq!(serde_json::to_string(&world).unwrap(), original_bytes);
    }
    let snapshot = decode_owned_export(
        Some(stored_run(&original.run, owner, encoded.state)),
        owner,
        |run| FixtureStore::begin(&source.rows, run, true),
    )
    .unwrap();
    source.rows.clear();
    // Mirrors the procedure boundary: fully owned hydrated payloads outlive
    // the read transaction; serialization cannot consult changed source rows.
    assert_eq!(serde_json::to_string(&snapshot).unwrap(), original_bytes);
}

#[test]
fn owner_export_retains_canonical_validation_and_generic_corruption_errors() {
    let original = fixture_world();
    let owner = Identity::from_byte_array([1; 32]);
    let mut source = FixtureStore::default();
    let encoded = codec::encode(&original, &mut source).unwrap();
    let mut invalid_rows = source.rows.clone();
    let id = *invalid_rows
        .iter()
        .find(|(_, row)| row.kind == "experience")
        .unwrap()
        .0;
    invalid_rows.get_mut(&id).unwrap().body = "corrupt".into();
    let invalid = decode_owned_export(
        Some(stored_run(&original.run, owner, encoded.state.clone())),
        owner,
        |run| FixtureStore::begin(&invalid_rows, run, true),
    );
    assert_eq!(invalid.err().unwrap(), "stored run invalid");
    let wrong_root = decode_owned_export(
        Some(stored_run("wrong-root", owner, encoded.state)),
        owner,
        |run| FixtureStore::begin(&source.rows, run, true),
    );
    assert_eq!(wrong_root.err().unwrap(), "stored run invalid");
}

#[test]
fn owner_export_adapter_rejects_writes_without_host_access() {
    let ctx = ReducerContext::__dummy();
    let mut reader = OwnerExportReader {
        ctx: &ctx,
        catalog: Catalog::default(),
        staged_blobs: BTreeMap::new(),
    };
    assert_eq!(
        reader
            .intern("run", Some(1), "experience", "body".into())
            .unwrap_err(),
        "read-only storage adapter"
    );
    assert!(reader.catalog.blobs.is_empty() && reader.catalog.live.is_empty());
}
