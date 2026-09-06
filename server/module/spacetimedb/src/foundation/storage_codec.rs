//! Module-only storage representation. `World` itself remains a self-contained
//! serializable value; only private durable rows contain these numeric references.
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::{json, value::RawValue, Value};
use sha2::{Digest, Sha256};
use simulation::{
    participant::{EvidenceLease, Experience},
    World,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

const FORMAT: &str = "sao-normalized-world-v1";

/// Implementations must validate run, actor, kind and content identity on both
/// intern and get. All puts and the final state replacement share one transaction.
pub(super) trait Blobs {
    fn intern(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        body: String,
    ) -> Result<u64, String>;
    fn get(&mut self, run: &str, actor: Option<u32>, kind: &str, id: u64)
        -> Result<String, String>;
    /// Retain only a scoped immutable row already validated in this adapter's
    /// current transaction. This must not fetch or rehash its body, and must
    /// reject unknown IDs. Read-only and ordinary fixture adapters fail closed.
    fn retain_validated(
        &mut self,
        _run: &str,
        _actor: Option<u32>,
        _kind: &str,
        _id: u64,
    ) -> Result<(), String> {
        Err("adapter cannot retain validated immutable references".into())
    }
}
pub(super) fn blob_key(run: &str, actor: Option<u32>, kind: &str, body: &str) -> String {
    let mut hash = Sha256::new();
    for bytes in [run.as_bytes(), kind.as_bytes(), body.as_bytes()] {
        hash.update((bytes.len() as u64).to_le_bytes());
        hash.update(bytes);
    }
    hash.update(actor.map_or_else(|| "shared".into(), |id| id.to_string()));
    format!("{:x}", hash.finalize())
}
fn put<T: Serialize + ?Sized>(
    store: &mut impl Blobs,
    run: &str,
    actor: Option<u32>,
    kind: &str,
    value: &T,
) -> Result<u64, String> {
    store.intern(
        run,
        actor,
        kind,
        serde_json::to_string(value).map_err(|_| "blob encoding failed")?,
    )
}
fn get<T: DeserializeOwned>(
    store: &mut impl Blobs,
    run: &str,
    actor: Option<u32>,
    kind: &str,
    id: u64,
) -> Result<T, String> {
    if id == 0 {
        return Err("zero immutable reference".into());
    }
    serde_json::from_str(&store.get(run, actor, kind, id)?)
        .map_err(|_| "invalid immutable payload".into())
}
fn put_list<T: Serialize>(
    store: &mut impl Blobs,
    run: &str,
    actor: u32,
    kind: &str,
    items: &[T],
) -> Result<Vec<u64>, String> {
    items
        .iter()
        .map(|item| put(store, run, Some(actor), kind, item))
        .collect()
}
fn get_list<T: DeserializeOwned>(
    store: &mut impl Blobs,
    run: &str,
    actor: u32,
    kind: &str,
    ids: &[u64],
) -> Result<Vec<T>, String> {
    ids.iter()
        .map(|id| get(store, run, Some(actor), kind, *id))
        .collect()
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct LeaseRefs {
    request_id: String,
    control_epoch: u64,
    observed_cursor: u64,
    expires_ms: u64,
    observation: Option<u64>,
    experiences: Vec<u64>,
}
// These hints exist only between one reducer's validated load and save. Strong
// Arc owners prevent in-place payload mutation and pointer-address reuse. Trace
// snapshots also own independent metadata for exact comparison on save. They
// are deliberately not serializable or constructible outside this codec.
pub(super) struct LeaseReuse {
    run: String,
    actors: BTreeMap<u32, Vec<ValidatedLease>>,
    traces: BTreeMap<u32, ValidatedTrace>,
}
struct ValidatedTrace {
    epoch: u64,
    entries: BTreeMap<u64, (u64, Experience)>,
}
struct ValidatedLease {
    epoch: u64,
    lease: EvidenceLease,
    refs: LeaseRefs,
    id: u64,
}
impl LeaseReuse {
    fn matching_trace(&self, actor: u32, epoch: u64, experience: &Experience) -> Option<u64> {
        let trace = self.traces.get(&actor)?;
        if trace.epoch != epoch {
            return None;
        }
        let (id, snapshot) = trace.entries.get(&experience.cursor)?;
        experience.can_reuse_encoding(snapshot).then_some(*id)
    }

    fn matching(&self, actor: u32, epoch: u64, lease: &EvidenceLease) -> Option<&ValidatedLease> {
        self.actors.get(&actor)?.iter().find(|old| {
            old.epoch == epoch
                && old.lease.request_id == lease.request_id
                && old.lease.observed_cursor == lease.observed_cursor
                && old.lease.expires_ms == lease.expires_ms
                && Arc::ptr_eq(&old.lease.observation, &lease.observation)
                && Arc::ptr_eq(&old.lease.experiences, &lease.experiences)
        })
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PlayerRefs {
    memories: Vec<u64>,
    sites: Vec<u64>,
    knowledge: Vec<u64>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ParticipantRefs {
    trace: Vec<u64>,
    activity: Vec<u64>,
    receipts: Vec<u64>,
    leases: Vec<u64>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct JobRefs {
    id: u64,
    owner: u32,
    payload: u64,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct JobPayload {
    input: Option<simulation::infrastructure::ForecastInput>,
    program_work: Option<simulation::research::ProgramWork>,
    #[serde(default)]
    law_work: Option<simulation::law_research::LawWork>,
    sources: Vec<simulation::knowledge::Record>,
    report: Option<simulation::knowledge::Record>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PendingLawRefs {
    update: u64,
    expected_binding: simulation::laws::LawBinding,
    reference: simulation::laws::LawRef,
    revision: u64,
    location: i32,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct LawRefs {
    history: BTreeMap<String, BTreeMap<u64, u64>>,
    pending: Vec<PendingLawRefs>,
    faults: Vec<u64>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CapturedReadRefs {
    run: String,
    actors: BTreeMap<u32, BTreeMap<u64, u64>>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CapturedReadBlob {
    lease: u64,
    observation: Box<RawValue>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Layout {
    initial: u64,
    scripts: u64,
    #[serde(default)]
    laws: LawRefs,
    archive_records: BTreeMap<u32, Vec<u64>>,
    station_jobs: BTreeMap<u32, Vec<JobRefs>>,
    players: BTreeMap<u32, PlayerRefs>,
    participants: BTreeMap<u32, ParticipantRefs>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    captured_reads: Option<CapturedReadRefs>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredWorld {
    format: String,
    world: World,
    layout: Layout,
}
pub(super) struct Encoded {
    pub state: String,
    pub layout: Layout,
}

/// Derived blobs are not hydrated into World. Keep their reachability separate
/// from the canonical blobs a storage adapter actually reads during decode.
pub(super) fn derived_fragment_ids(layout: &Layout) -> BTreeSet<u64> {
    derived_fragment_owners(layout).into_keys().collect()
}

pub(super) fn derived_fragment_owners(layout: &Layout) -> BTreeMap<u64, u32> {
    layout
        .captured_reads
        .as_ref()
        .into_iter()
        .flat_map(|refs| refs.actors.iter())
        .flat_map(|(actor, refs)| refs.values().map(move |id| (*id, *actor)))
        .collect()
}

fn initial_placeholder() -> Result<simulation::Scenario, String> {
    serde_json::from_value(json!({"name":"","seed":0,"max_ticks":0,"players":[],"sites":[]}))
        .map_err(|_| "initial placeholder failed".into())
}
pub(super) fn encode(world: &World, store: &mut impl Blobs) -> Result<Encoded, String> {
    encode_with_previous(world, store, None)
}

pub(super) fn encode_with_previous(
    world: &World,
    store: &mut impl Blobs,
    previous: Option<&Layout>,
) -> Result<Encoded, String> {
    encode_with_reuse(world, store, previous, None)
}

pub(super) fn encode_with_reuse(
    world: &World,
    store: &mut impl Blobs,
    previous: Option<&Layout>,
    reuse: Option<&LeaseReuse>,
) -> Result<Encoded, String> {
    let run = &world.run;
    if reuse.is_some_and(|reuse| reuse.run != *run) {
        return Err("validated lease reuse belongs to another run".into());
    }
    let previous_reads = previous.and_then(|layout| layout.captured_reads.as_ref());
    if previous_reads.is_some_and(|refs| refs.run != *run) {
        return Err("previous captured reads belong to another run".into());
    }
    let mut layout = Layout {
        initial: put(store, run, None, "initial", &world.initial)?,
        scripts: put(store, run, None, "scripts", &world.scripts)?,
        players: BTreeMap::new(),
        participants: BTreeMap::new(),
        archive_records: BTreeMap::new(),
        station_jobs: BTreeMap::new(),
        laws: LawRefs::default(),
        captured_reads: Some(CapturedReadRefs {
            run: run.clone(),
            actors: BTreeMap::new(),
        }),
    };
    let mut compact = world.clone();
    // These placeholders never escape the private storage envelope. Hydration
    // restores every field before a World reaches a reducer, SQL caller or view.
    compact.initial = initial_placeholder()?;
    compact.scripts = simulation::scripting::Registry {
        api_version: 0,
        revision: 0,
        active: BTreeMap::new(),
        history: BTreeMap::new(),
        pending: None,
    };
    for (scope, revisions) in &world.laws.history {
        let mut ids = BTreeMap::new();
        for (revision, value) in revisions {
            if value.reference.scope.key() != *scope || value.reference.revision != *revision {
                return Err("law history reference identity differs".into());
            }
            ids.insert(*revision, put(store, run, None, "law_revision", value)?);
        }
        layout.laws.history.insert(scope.clone(), ids);
    }
    for pending in &world.laws.pending {
        layout.laws.pending.push(PendingLawRefs {
            update: pending.update,
            expected_binding: pending.expected_binding.clone(),
            reference: pending.revision.reference.clone(),
            revision: put(store, run, None, "law_revision", &pending.revision)?,
            location: pending.location,
        });
    }
    {
        let faults = world.laws.faults.lock();
        if world.laws.reported_faults > faults.len() {
            return Err("reported law faults exceed retained faults".into());
        }
        layout.laws.faults = faults
            .iter()
            .map(|fault| put(store, run, None, "law_fault", fault))
            .collect::<Result<_, _>>()?;
    }
    compact.laws.history.clear();
    compact.laws.pending.clear();
    compact.laws.faults.lock().clear();
    for (source, target) in world.archives.iter().zip(&mut compact.archives) {
        let ids = source
            .records
            .iter()
            .map(|record| put(store, run, None, "archive_record", record))
            .collect::<Result<_, _>>()?;
        if layout.archive_records.insert(source.id, ids).is_some() {
            return Err("duplicate archive identity".into());
        }
        target.records.clear();
    }
    for (source, target) in world
        .infrastructure
        .stations
        .iter()
        .zip(&mut compact.infrastructure.stations)
    {
        let mut ids = Vec::with_capacity(source.jobs.len());
        let mut seen = BTreeSet::new();
        for (job, stub) in source.jobs.iter().zip(&mut target.jobs) {
            if !seen.insert(job.id) {
                return Err("duplicate station job identity".into());
            }
            let payload = JobPayload {
                input: job.input.clone(),
                program_work: job.program_work.clone(),
                law_work: job.law_work.clone(),
                sources: job.sources.clone(),
                report: job.report.clone(),
            };
            ids.push(JobRefs {
                id: job.id,
                owner: job.owner,
                payload: put(store, run, Some(job.owner), "job_payload", &payload)?,
            });
            stub.input = None;
            stub.program_work = None;
            stub.law_work = None;
            stub.sources.clear();
            stub.report = None;
        }
        if layout.station_jobs.insert(source.seed.id, ids).is_some() {
            return Err("duplicate station identity".into());
        }
    }
    for (source, target) in world.players.iter().zip(&mut compact.players) {
        if layout
            .players
            .insert(
                source.id,
                PlayerRefs {
                    memories: put_list(store, run, source.id, "memory", &source.memories)?,
                    sites: put_list(store, run, source.id, "memory", &source.site_observations)?,
                    knowledge: put_list(store, run, source.id, "holding", &source.knowledge)?,
                },
            )
            .is_some()
        {
            return Err("duplicate player identity".into());
        }
        target.memories.clear();
        target.site_observations.clear();
        target.knowledge.clear();
    }
    for (&actor, source) in &world.participants {
        let mut leases = Vec::with_capacity(source.evidence_leases.len());
        for lease in &source.evidence_leases {
            let old = reuse.and_then(|reuse| reuse.matching(actor, source.control_epoch, lease));
            let (lease_id, has_observation) = if let Some(old) = old {
                store.retain_validated(run, Some(actor), "lease", old.id)?;
                if let Some(id) = old.refs.observation {
                    store.retain_validated(run, Some(actor), "observation", id)?;
                }
                for id in &old.refs.experiences {
                    store.retain_validated(run, Some(actor), "experience", *id)?;
                }
                (old.id, old.refs.observation.is_some())
            } else {
                validate_lease(run, actor, source.control_epoch, lease)?;
                let refs = LeaseRefs {
                    request_id: lease.request_id.clone(),
                    control_epoch: source.control_epoch,
                    observed_cursor: lease.observed_cursor,
                    expires_ms: lease.expires_ms,
                    observation: if lease.observation.get() == "null" {
                        None
                    } else {
                        Some(put(
                            store,
                            run,
                            Some(actor),
                            "observation",
                            &*lease.observation,
                        )?)
                    },
                    experiences: put_list(store, run, actor, "experience", &lease.experiences)?,
                };
                (
                    put(store, run, Some(actor), "lease", &refs)?,
                    refs.observation.is_some(),
                )
            };
            if has_observation {
                let previous_fragment = previous_reads
                    .and_then(|refs| refs.actors.get(&actor))
                    .and_then(|refs| refs.get(&lease_id))
                    .copied();
                let fragment = match previous_fragment {
                    Some(0) => return Err("zero captured read reference".into()),
                    // A private reference can be retained without reading its
                    // large body. Serving it still requires scoped/hash-checked
                    // retrieval and matching the embedded canonical lease ID.
                    Some(id) => id,
                    None => put(
                        store,
                        run,
                        Some(actor),
                        "captured_read_v1",
                        &CapturedReadBlob {
                            lease: lease_id,
                            observation: assemble_observation(lease)?,
                        },
                    )?,
                };
                layout
                    .captured_reads
                    .as_mut()
                    .unwrap()
                    .actors
                    .entry(actor)
                    .or_default()
                    .insert(lease_id, fragment);
            }
            leases.push(lease_id);
        }
        let trace = source
            .experiences
            .iter()
            .map(|experience| {
                match reuse
                    .and_then(|reuse| reuse.matching_trace(actor, source.control_epoch, experience))
                {
                    Some(id) => {
                        // Only entries still visited in the current trace stay live.
                        // Token ownership alone must not retain evicted entries.
                        store.retain_validated(run, Some(actor), "experience", id)?;
                        Ok(id)
                    }
                    None => put(store, run, Some(actor), "experience", experience),
                }
            })
            .collect::<Result<Vec<_>, String>>()?;
        layout.participants.insert(
            actor,
            ParticipantRefs {
                trace,
                activity: put_list(store, run, actor, "activity", &source.activity)?,
                receipts: put_list(store, run, actor, "receipt", &source.receipts)?,
                leases,
            },
        );
        let target = compact
            .participants
            .get_mut(&actor)
            .ok_or("participant copy missing")?;
        target.experiences.clear();
        target.activity.clear();
        target.receipts.clear();
        for lease in &mut target.evidence_leases {
            lease.observation = serde_json::value::to_raw_value(&Value::Null)
                .map_err(|_| "null encoding failed")?
                .into();
            lease.experiences = Arc::new(vec![]);
        }
    }
    let stored = StoredWorld {
        format: FORMAT.into(),
        world: compact,
        layout,
    };
    let state = serde_json::to_string(&stored).map_err(|_| "normalized world encoding failed")?;
    Ok(Encoded {
        state,
        layout: stored.layout,
    })
}
// Typed values are shared only within one decode, after scoped immutable get
// validation. Experience::clone keeps independent metadata while sharing its
// immutable ExperienceData. List-specific cursor/order checks still run below.
struct ExperienceMemo {
    run: String,
    entries: BTreeMap<(u32, u64), Experience>,
}
impl ExperienceMemo {
    fn new(run: &str) -> Self {
        Self {
            run: run.into(),
            entries: BTreeMap::new(),
        }
    }
    fn read(
        &mut self,
        store: &mut impl Blobs,
        run: &str,
        actor: u32,
        id: u64,
    ) -> Result<Experience, String> {
        if self.run != run {
            return Err("experience memo run scope mismatch".into());
        }
        if id == 0 {
            return Err("zero immutable reference".into());
        }
        if let Some(value) = self.entries.get(&(actor, id)) {
            return Ok(value.clone());
        }
        let value: Experience = get(store, run, Some(actor), "experience", id)?;
        #[cfg(test)]
        EXPERIENCE_DECODES.with(|count| count.set(count.get() + 1));
        self.entries.insert((actor, id), value.clone());
        Ok(value)
    }
}

fn experiences(
    store: &mut impl Blobs,
    memo: &mut ExperienceMemo,
    run: &str,
    actor: u32,
    ids: &[u64],
    cursor: u64,
) -> Result<Vec<Experience>, String> {
    let items: Vec<Experience> = ids
        .iter()
        .map(|id| memo.read(store, run, actor, *id))
        .collect::<Result<_, _>>()?;
    let mut seen = BTreeSet::new();
    if items
        .iter()
        .any(|item| item.cursor > cursor || !seen.insert(item.cursor))
    {
        return Err("invalid experience reference order or cursor".into());
    }
    Ok(items)
}
pub(super) fn decode(text: &str, store: &mut impl Blobs) -> Result<World, String> {
    decode_with_layout(text, store).map(|(world, _)| world)
}

pub(super) fn decode_with_layout(
    text: &str,
    store: &mut impl Blobs,
) -> Result<(World, Layout), String> {
    decode_inner(text, store, false).map(|(world, layout, _)| (world, layout))
}

pub(super) fn decode_for_save(
    text: &str,
    store: &mut impl Blobs,
) -> Result<(World, Layout, LeaseReuse), String> {
    let (world, layout, reuse) = decode_inner(text, store, true)?;
    Ok((world, layout, reuse.ok_or("validated lease reuse missing")?))
}

fn decode_inner(
    text: &str,
    store: &mut impl Blobs,
    retain_leases: bool,
) -> Result<(World, Layout, Option<LeaseReuse>), String> {
    let mut stored: StoredWorld =
        serde_json::from_str(text).map_err(|_| "invalid normalized world envelope")?;
    if stored.format != FORMAT {
        return Err("unsupported normalized world format".into());
    }
    let retained_layout = stored.layout.clone();
    let world = &mut stored.world;
    let layout = stored.layout;
    let run = &world.run;
    let mut experience_memo = ExperienceMemo::new(run);
    let mut reuse = retain_leases.then(|| LeaseReuse {
        run: run.clone(),
        actors: BTreeMap::new(),
        traces: BTreeMap::new(),
    });
    if let Some(captured) = &layout.captured_reads {
        if captured.run != *run {
            return Err("captured read layout scope mismatch".into());
        }
        let mut fragments = BTreeSet::new();
        for (actor, reads) in &captured.actors {
            let participant = layout
                .participants
                .get(actor)
                .ok_or("captured read actor missing")?;
            for (lease, fragment) in reads {
                if *fragment == 0
                    || !participant.leases.contains(lease)
                    || !fragments.insert(*fragment)
                {
                    return Err("captured read layout reference mismatch".into());
                }
            }
        }
    }
    if world.players.len() != layout.players.len()
        || world.participants.len() != layout.participants.len()
    {
        return Err("normalized actor references differ".into());
    }
    if serde_json::to_value(&world.initial).map_err(|_| "invalid initial placeholder")?
        != serde_json::to_value(initial_placeholder()?)
            .map_err(|_| "invalid initial placeholder")?
        || world.scripts.api_version != 0
        || world.scripts.revision != 0
        || !world.scripts.active.is_empty()
        || !world.scripts.history.is_empty()
        || world.scripts.pending.is_some()
    {
        return Err("mixed inline and referenced initial configuration".into());
    }
    if !world.laws.history.is_empty()
        || !world.laws.pending.is_empty()
        || !world.laws.faults.lock().is_empty()
    {
        return Err("mixed inline and referenced law data".into());
    }
    for (scope, revisions) in layout.laws.history {
        let mut restored = BTreeMap::new();
        for (revision, id) in revisions {
            let value: simulation::laws::LawRevision = get(store, run, None, "law_revision", id)?;
            if value.reference.scope.key() != scope || value.reference.revision != revision {
                return Err("law history reference identity differs".into());
            }
            restored.insert(revision, value);
        }
        world.laws.history.insert(scope, restored);
    }
    for refs in layout.laws.pending {
        let revision: simulation::laws::LawRevision =
            get(store, run, None, "law_revision", refs.revision)?;
        if revision.reference != refs.reference {
            return Err("pending law reference identity differs".into());
        }
        world.laws.pending.push(simulation::laws::PendingLaw {
            update: refs.update,
            expected_binding: refs.expected_binding,
            revision,
            location: refs.location,
        });
    }
    {
        let mut faults = world.laws.faults.lock();
        *faults = layout
            .laws
            .faults
            .iter()
            .map(|id| get(store, run, None, "law_fault", *id))
            .collect::<Result<_, _>>()?;
        if world.laws.reported_faults > faults.len() {
            return Err("reported law faults exceed retained faults".into());
        }
    }
    world.initial = get(store, run, None, "initial", layout.initial)?;
    world.scripts = get(store, run, None, "scripts", layout.scripts)?;
    if world.archives.len() != layout.archive_records.len()
        || world.infrastructure.stations.len() != layout.station_jobs.len()
    {
        return Err("normalized collection references differ".into());
    }
    let mut archives = BTreeSet::new();
    for archive in &mut world.archives {
        if !archives.insert(archive.id) || !archive.records.is_empty() {
            return Err("duplicate archive or mixed inline records".into());
        }
        archive.records = layout
            .archive_records
            .get(&archive.id)
            .ok_or("missing archive references")?
            .iter()
            .map(|id| get(store, run, None, "archive_record", *id))
            .collect::<Result<_, _>>()?;
    }
    let mut stations = BTreeSet::new();
    for station in &mut world.infrastructure.stations {
        if !stations.insert(station.seed.id) {
            return Err("duplicate station identity".into());
        }
        let refs = layout
            .station_jobs
            .get(&station.seed.id)
            .ok_or("missing station references")?;
        if station.jobs.len() != refs.len() {
            return Err("station job reference count differs".into());
        }
        let mut jobs = BTreeSet::new();
        for (job, refs) in station.jobs.iter_mut().zip(refs) {
            if !jobs.insert(job.id) || job.id != refs.id || job.owner != refs.owner {
                return Err("station job reference identity differs".into());
            }
            if job.input.is_some()
                || job.program_work.is_some()
                || job.law_work.is_some()
                || !job.sources.is_empty()
                || job.report.is_some()
            {
                return Err("mixed inline and referenced job payload".into());
            }
            let payload: JobPayload =
                get(store, run, Some(job.owner), "job_payload", refs.payload)?;
            job.input = payload.input;
            job.program_work = payload.program_work;
            job.law_work = payload.law_work;
            job.sources = payload.sources;
            job.report = payload.report;
        }
    }
    let mut actors = BTreeSet::new();
    for player in &mut world.players {
        if !actors.insert(player.id) {
            return Err("duplicate player identity".into());
        }
        if !player.memories.is_empty()
            || !player.site_observations.is_empty()
            || !player.knowledge.is_empty()
        {
            return Err("mixed inline and referenced player data".into());
        }
        let refs = layout
            .players
            .get(&player.id)
            .ok_or("missing player references")?;
        player.memories = get_list(store, run, player.id, "memory", &refs.memories)?;
        player.site_observations = get_list(store, run, player.id, "memory", &refs.sites)?;
        player.knowledge = get_list(store, run, player.id, "holding", &refs.knowledge)?;
    }
    for (&actor, state) in &mut world.participants {
        let refs = layout
            .participants
            .get(&actor)
            .ok_or("missing participant references")?;
        if !state.experiences.is_empty()
            || !state.activity.is_empty()
            || !state.receipts.is_empty()
            || state.evidence_leases.len() != refs.leases.len()
        {
            return Err("mixed inline and referenced participant data".into());
        }
        state.experiences = experiences(
            store,
            &mut experience_memo,
            run,
            actor,
            &refs.trace,
            state.cursor,
        )?;
        if state
            .experiences
            .windows(2)
            .any(|pair| pair[0].cursor >= pair[1].cursor)
        {
            return Err("unordered retained trace".into());
        }
        if let Some(reuse) = &mut reuse {
            reuse.traces.insert(
                actor,
                ValidatedTrace {
                    epoch: state.control_epoch,
                    entries: state
                        .experiences
                        .iter()
                        .zip(&refs.trace)
                        .map(|(experience, id)| (experience.cursor, (*id, experience.clone())))
                        .collect(),
                },
            );
        }
        state.activity = get_list(store, run, actor, "activity", &refs.activity)?;
        state.receipts = get_list(store, run, actor, "receipt", &refs.receipts)?;
        let control_epoch = state.control_epoch;
        for (lease, id) in state.evidence_leases.iter_mut().zip(&refs.leases) {
            if lease.observation.get() != "null" || !lease.experiences.is_empty() {
                return Err("mixed inline and referenced read data".into());
            }
            let refs: LeaseRefs = get(store, run, Some(actor), "lease", *id)?;
            if refs.observation.is_none()
                && layout
                    .captured_reads
                    .as_ref()
                    .and_then(|reads| reads.actors.get(&actor))
                    .is_some_and(|reads| reads.contains_key(id))
            {
                return Err("pinned-only lease has captured read reference".into());
            }
            if refs.request_id != lease.request_id
                || refs.observed_cursor != lease.observed_cursor
                || refs.expires_ms != lease.expires_ms
                || refs.control_epoch != control_epoch
            {
                return Err("lease reference metadata differs".into());
            }
            if let Some(id) = refs.observation {
                lease.observation =
                    get::<Box<RawValue>>(store, run, Some(actor), "observation", id)?.into();
            }
            lease.experiences = Arc::new(experiences(
                store,
                &mut experience_memo,
                run,
                actor,
                &refs.experiences,
                lease.observed_cursor,
            )?);
            validate_lease(run, actor, control_epoch, lease)?;
            if let Some(reuse) = &mut reuse {
                reuse.actors.entry(actor).or_default().push(ValidatedLease {
                    epoch: control_epoch,
                    lease: lease.clone(),
                    refs,
                    id: *id,
                });
            }
        }
    }
    Ok((stored.world, retained_layout, reuse))
}

#[derive(Deserialize)]
struct ObservationHeader {
    api_version: String,
    run: String,
    actor: u32,
    control_epoch: u64,
    latest_cursor: u64,
    time_ms: u64,
    evidence_lease: ObservationLease,
}
#[derive(Deserialize)]
struct ObservationLease {
    observed_cursor: u64,
    duration_ms: u64,
    atomic: bool,
}
fn validate_lease(run: &str, actor: u32, epoch: u64, lease: &EvidenceLease) -> Result<(), String> {
    #[cfg(test)]
    LEASE_VALIDATIONS.with(|count| count.set(count.get() + 1));
    let mut seen = BTreeSet::new();
    if lease
        .experiences
        .iter()
        .any(|e| e.cursor > lease.observed_cursor || !seen.insert(e.cursor))
    {
        return Err("lease experience cursor or duplicate invalid".into());
    }
    if lease.observation.get() == "null" {
        return Ok(());
    }
    // PinObservation deliberately preserves caller order; ReadObservation pages
    // are ordered. Do not invent a stricter rule for valid existing pinned leases.
    if lease
        .experiences
        .windows(2)
        .any(|pair| pair[0].cursor >= pair[1].cursor)
    {
        return Err("unordered read observation evidence".into());
    }
    validate_observation_header(
        run,
        actor,
        epoch,
        lease.observed_cursor,
        lease.expires_ms,
        lease.observation.get(),
    )
}

fn validate_observation_header(
    run: &str,
    actor: u32,
    epoch: u64,
    cursor: u64,
    expires_ms: u64,
    observation: &str,
) -> Result<(), String> {
    let header: ObservationHeader =
        serde_json::from_str(observation).map_err(|_| "invalid captured observation header")?;
    if header.api_version != simulation::participant::API_VERSION
        || header.run != run
        || header.actor != actor
        || header.control_epoch != epoch
        || header.latest_cursor != cursor
        || header.evidence_lease.observed_cursor != cursor
        || !header.evidence_lease.atomic
        || header.evidence_lease.duration_ms != simulation::participant::EVIDENCE_LEASE_MS
        || header
            .time_ms
            .saturating_add(header.evidence_lease.duration_ms)
            != expires_ms
    {
        return Err("captured observation identity or lease metadata differs".into());
    }
    Ok(())
}

#[cfg(test)]
thread_local! { static FRAGMENT_ASSEMBLIES: std::cell::Cell<usize> = const { std::cell::Cell::new(0) }; }
#[cfg(test)]
thread_local! { static LEASE_VALIDATIONS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) }; }
#[cfg(test)]
thread_local! { static EXPERIENCE_DECODES: std::cell::Cell<usize> = const { std::cell::Cell::new(0) }; }
#[cfg(test)]
pub(super) fn reset_experience_decode_count() {
    EXPERIENCE_DECODES.with(|count| count.set(0));
}
#[cfg(test)]
pub(super) fn experience_decode_count() -> usize {
    EXPERIENCE_DECODES.with(|count| count.get())
}
#[cfg(test)]
pub(super) fn reset_lease_validation_count() {
    LEASE_VALIDATIONS.with(|count| count.set(0));
}
#[cfg(test)]
pub(super) fn lease_validation_count() -> usize {
    LEASE_VALIDATIONS.with(|count| count.get())
}
#[cfg(test)]
pub(super) fn reset_fragment_assembly_count() {
    FRAGMENT_ASSEMBLIES.with(|count| count.set(0));
}
#[cfg(test)]
pub(super) fn fragment_assembly_count() -> usize {
    FRAGMENT_ASSEMBLIES.with(|count| count.get())
}

fn assemble_observation(lease: &EvidenceLease) -> Result<Box<RawValue>, String> {
    #[cfg(test)]
    FRAGMENT_ASSEMBLIES.with(|count| count.set(count.get() + 1));
    let prefix = lease
        .observation
        .get()
        .trim()
        .strip_suffix('}')
        .filter(|s| s.starts_with('{'))
        .ok_or("captured observation is not an object")?;
    let experiences =
        serde_json::to_string(&lease.experiences).map_err(|_| "experience encoding failed")?;
    let mut observation = String::with_capacity(prefix.len() + experiences.len() + 20);
    observation.push_str(prefix);
    if prefix.trim_end() != "{" {
        observation.push(',');
    }
    observation.push_str("\"experiences\":");
    observation.push_str(&experiences);
    observation.push('}');
    RawValue::from_string(observation).map_err(|_| "invalid captured observation".into())
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredStatus {
    run: String,
    actor: u32,
    time_ms: u64,
    head: Value,
    receipts: Vec<u64>,
    leases: Vec<u64>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    captured_reads: BTreeMap<u64, u64>,
}
pub(super) fn status(world: &World, actor: u32, layout: &Layout) -> Result<String, String> {
    let mut head: Value = serde_json::from_str(&world.participant_status_header_json(actor)?)
        .map_err(|_| "invalid status header")?;
    let object = head
        .as_object_mut()
        .ok_or("status header is not an object")?;
    object.remove("read_observations");
    object.remove("receipts");
    let participant = world
        .participants
        .get(&actor)
        .ok_or("missing participant")?;
    let refs = layout
        .participants
        .get(&actor)
        .ok_or("missing participant references")?;
    if refs.leases.len() != participant.evidence_leases.len() {
        return Err("lease reference count differs".into());
    }
    let leases: Vec<u64> = participant
        .evidence_leases
        .iter()
        .zip(&refs.leases)
        .filter_map(|(lease, id)| {
            (lease.expires_ms >= world.timing.time_ms && lease.observation.get() != "null")
                .then_some(*id)
        })
        .collect();
    if layout
        .captured_reads
        .as_ref()
        .is_some_and(|refs| refs.run != world.run)
    {
        return Err("captured read layout scope mismatch".into());
    }
    let captured_reads = layout
        .captured_reads
        .as_ref()
        .and_then(|refs| refs.actors.get(&actor))
        .map(|refs| {
            leases
                .iter()
                .filter_map(|lease| refs.get(lease).map(|id| (*lease, *id)))
                .collect()
        })
        .unwrap_or_default();
    serde_json::to_string(&StoredStatus {
        run: world.run.clone(),
        actor,
        time_ms: world.timing.time_ms,
        head,
        receipts: refs.receipts.clone(),
        leases,
        captured_reads,
    })
    .map_err(|_| "status storage encoding failed".into())
}
pub(super) fn expand_status(
    run: &str,
    actor: u32,
    text: &str,
    store: &mut impl Blobs,
) -> Result<String, String> {
    let mut stored: StoredStatus =
        serde_json::from_str(text).map_err(|_| "invalid normalized participant status")?;
    if stored.run != run
        || stored.actor != actor
        || stored.head["run"] != run
        || stored.head["actor"] != actor
    {
        return Err("participant status scope mismatch".into());
    }
    let epoch = stored.head["control_epoch"]
        .as_u64()
        .ok_or("missing status control epoch")?;
    if stored
        .captured_reads
        .keys()
        .any(|id| !stored.leases.contains(id))
    {
        return Err("captured status reference has no active lease".into());
    }
    let receipts: Vec<simulation::participant::Receipt> =
        get_list(store, run, actor, "receipt", &stored.receipts)?;
    stored.head["receipts"] = json!(receipts);
    #[derive(Serialize)]
    struct Read {
        request_id: String,
        observation: Box<RawValue>,
    }
    #[derive(Serialize)]
    struct Status {
        #[serde(flatten)]
        head: Value,
        read_observations: Vec<Read>,
    }
    let mut reads = vec![];
    for id in stored.leases {
        let refs: LeaseRefs = get(store, run, Some(actor), "lease", id)?;
        if refs.control_epoch != epoch || refs.expires_ms < stored.time_ms {
            return Err("inactive status lease".into());
        }
        if refs.observation.is_none() {
            return Err("status contains a pinned-only lease".into());
        }
        if let Some(fragment) = stored.captured_reads.get(&id) {
            let captured: CapturedReadBlob =
                get(store, run, Some(actor), "captured_read_v1", *fragment)?;
            if captured.lease != id {
                return Err("captured read lease identity differs".into());
            }
            validate_observation_header(
                run,
                actor,
                epoch,
                refs.observed_cursor,
                refs.expires_ms,
                captured.observation.get(),
            )?;
            reads.push(Read {
                request_id: refs.request_id,
                observation: captured.observation,
            });
            continue;
        }
        let body: Box<RawValue> = get(
            store,
            run,
            Some(actor),
            "observation",
            refs.observation
                .ok_or("status contains a pinned-only lease")?,
        )?;
        let xs: Vec<Experience> = get_list(store, run, actor, "experience", &refs.experiences)?;
        let lease = EvidenceLease {
            request_id: refs.request_id,
            observation: body.into(),
            observed_cursor: refs.observed_cursor,
            expires_ms: refs.expires_ms,
            experiences: Arc::new(xs),
        };
        validate_lease(run, actor, epoch, &lease)?;
        let observation = assemble_observation(&lease)?;
        reads.push(Read {
            request_id: lease.request_id,
            observation,
        });
    }
    serde_json::to_string(&Status {
        head: stored.head,
        read_observations: reads,
    })
    .map_err(|_| "status expansion failed".into())
}
