//! Canonical component rows. Full hydration is reserved for the global clock
//! kernel and explicit exports; participant transactions use indexed reads.
use trace::*;
use catalog::{sim_native_controller_catalog, sim_native_controller_catalog__view, SimNativeControllerCatalog};
use super::participant_delivery::{sim_participant_receipt, sim_participant_receipt__view};
use simulation::{
    deferred::Deferred,
    participant::{EvidenceLease, Experience, ExperienceRecord, ParticipantState, Receipt},
    Controller, Player, World,
};
use spacetimedb::{ReducerContext, Table, ViewContext};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

pub(super) const FORMAT: &str = "sao-native-components-v1";
pub(super) type LeaseIds = BTreeMap<u32, Vec<u64>>;
#[cfg(feature = "clock-profile")]
thread_local! { static COLD_READS: std::cell::Cell<[u64; 6]> = const { std::cell::Cell::new([0; 6]) }; }
#[inline]
fn count_cold_read(_kind: usize, _body_bytes: usize) {
    #[cfg(feature = "clock-profile")]
    COLD_READS.with(|counts| {
        let mut values = counts.get(); values[_kind * 2] += 1; values[_kind * 2 + 1] += _body_bytes as u64;
        counts.set(values);
    });
}
pub(super) fn report_clock_reads() {
    #[cfg(feature = "clock-profile")]
    COLD_READS.with(|counts| log::info!("clock_cold_reads {:?}", counts.get()));
}
fn key(run: &str, id: impl std::fmt::Display) -> String {
    format!("{run}:{id}")
}
fn json(value: &impl serde::Serialize) -> String {
    serde_json::to_string(value).expect("component serializes")
}
fn parse<T: serde::de::DeserializeOwned>(value: &str) -> Result<T, String> {
    serde_json::from_str(value).map_err(|e| format!("invalid native component: {e}"))
}

/// `scripting::facts` also reads these five mind fields. Keep the projected
/// target facts identical to the full kernel without materializing its history.
fn apply_visibility_facts(peer: &mut Player, facts: &SimNativeMind) {
    peer.caution=facts.caution;
    peer.empathy=facts.empathy;
    peer.introspection=facts.introspection;
    peer.fear=facts.fear;
    peer.failures=facts.failures;
}

/// Mutable action admission/delivery metadata, separated from the private seed.
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_controller)]
pub struct SimNativeController {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub known_targets: Vec<u32>,
    pub last_lifecycle: String,
    pub action: String,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_controller_bootstrap)]
pub struct SimControllerBootstrap {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub body: String,
}
impl SimNativeController {
    #[cfg(test)]
    fn from_state(run: &str, actor: u32, c: &simulation::controller::Authority) -> Self {
        Self::with_catalog(run, actor, c, json(&c.last_lifecycle))
    }
    fn with_catalog(run: &str, actor: u32, c: &simulation::controller::Authority, last_lifecycle: String) -> Self {
        Self { key: key(run, actor), run: run.into(), actor,
            known_targets: c.known_targets.iter().copied().collect(),
            last_lifecycle, action: json(&c.action) }
    }
}

#[derive(Clone, PartialEq, serde::Serialize, serde::Deserialize)]
#[spacetimedb::table(accessor = sim_native_head)]
pub struct SimNativeHead {
    #[primary_key]
    pub run: String,
    pub version: String,
    pub tick: u64,
    pub stopped: bool,
    pub participant_mode: bool,
    pub next_event: u64,
    pub next_actor: u32,
    pub time_ms: u64,
    pub updates: u64,
    pub delta_ms: u64,
    #[serde(default)]
    pub maintenance_ms: Option<u64>,
    pub needs_remainder_ms: u64,
    pub hazard_remainder_ms: u64,
    pub next_job: u64,
    pub applied_disturbances: Vec<u64>,
    pub food_remainder: String,
    pub pending: String,
    pub request_ids: Vec<u64>,
}
/// Presentation clock advances with physical/global commits. Actor-local action
/// admission does not invalidate every connected renderer through next_event.
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_render_clock)]
pub struct SimRenderClock {
    #[primary_key]
    pub run: String,
    pub head: String,
}
macro_rules! render_head {
    ($db:expr, $run:expr) => {{
        if let Some(row) = $db.sim_render_clock().run().find($run.to_owned()) {
            parse::<SimNativeHead>(&row.head)
        } else {
            // Existing databases acquire the presentation row on their next
            // global commit; until then retain the original read dependency.
            $db.sim_native_head().run().find($run.to_owned()).ok_or_else(|| "native run head missing".to_string())
        }
    }};
}
const CLOCK_INDEX_VERSION: u32 = 1;
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_clock_state)]
pub struct SimNativeClockState {
    #[primary_key]
    pub run: String,
    pub version: u32,
    pub script_revision: u64,
    pub actors: Vec<u32>,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_clock_actor,
    index(accessor = due, btree(columns = [run, due_ms])),
    index(accessor = active_actors, btree(columns = [run, active])))]
pub struct SimNativeClockActor {
    #[primary_key]
    pub key: String,
    pub run: String,
    pub actor: u32,
    pub due_ms: u64,
    pub active: bool,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_definition)]
pub struct SimNativeDefinition {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub kind: String,
    pub body: String,
}
/// Updated atomically with the authoritative definition. This small row lets a
/// disposable parsed cache avoid fetching the large body on matching versions.
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_definition_version)]
pub struct SimNativeDefinitionVersion {
    #[primary_key]
    pub key: String,
    pub digest: String,
}
struct DefinitionSet {
    initial: Deferred<simulation::Scenario>,
    scripts: Deferred<simulation::scripting::Registry>,
    laws: simulation::laws::LawState,
    balance: simulation::infrastructure::InfrastructureBalance,
}
macro_rules! read_definitions {
    ($db:expr, $run:expr) => { read_definitions!($db, $run, false) };
    ($db:expr, $run:expr, $owned:expr) => {{
        let run = $run;
        let initial = $db.sim_native_definition_version().key().find(key(run, "initial"));
        let scripts = $db.sim_native_definition_version().key().find(key(run, "scripts"));
        let initial_rows = $db.sim_native_definition().key();
        let initial_key = key(run, "initial");
        DefinitionSet {
            // Owner procedures serialize their coherent snapshot after the
            // transaction ends. Such reads must return loader-free values.
            initial: if $owned { super::definition_cache::initial_versioned(initial.as_ref().map(|r| r.digest.as_str()), || {
                initial_rows.find(&initial_key).map(|r| r.body).ok_or("native initial missing".into())
            })? } else { super::definition_cache::initial_deferred(initial.map(|r| r.digest), move || {
                initial_rows.find(&initial_key).map(|r| r.body).ok_or("native initial missing".into())
            })? },
            scripts: super::definition_cache::scripts_versioned(scripts.as_ref().map(|r| r.digest.as_str()), || {
                $db.sim_native_definition().key().find(key(run, "scripts")).map(|r| r.body).ok_or("native scripts missing".into())
            })?,
            laws: parse(&$db.sim_native_definition().key().find(key(run, "laws")).ok_or("native laws missing")?.body)?,
            balance: parse(&$db.sim_native_definition().key().find(key(run, "balance")).ok_or("native balance missing")?.body)?,
        }
    }};
}
/// Public body facts and physical state; no private trace or captured reads.
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_actor,
    index(accessor = location, btree(columns = [run, position])))]
pub struct SimNativeActor {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub ordinal: u32,
    pub name: String,
    pub human: bool,
    pub position: i32,
    pub health: i32,
    pub hunger: i32,
    pub energy: i32,
    pub food: i32,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_mind)]
pub struct SimNativeMind {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub motive: String,
    pub role: String,
    pub current_goal: Option<String>,
    pub caution: i32,
    pub empathy: i32,
    pub introspection: i32,
    pub fear: i32,
    pub generation: u64,
    pub failures: u32,
    pub last_reflection: u64,
    pub last_cause: Option<u64>,
    pub execution: String,
    pub beliefs: String,
    pub relationships: String,
    pub memories: String,
    pub site_observations: String,
    pub knowledge: String,
}
const MIND_HISTORY: &str = "sao-native-mind-history-v1";
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_mind_history)]
pub struct SimNativeMindHistory {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub beliefs: String,
    pub relationships: String,
    pub memories: String,
    pub site_observations: String,
    pub knowledge: String,
}
impl SimNativeMindHistory {
    fn from_player(run: &str, p: &Player) -> Self {
        Self { key: key(run, p.id), run: run.into(), actor: p.id,
            beliefs: json(&p.beliefs), relationships: json(&p.relationships),
            memories: json(&p.memories), site_observations: json(&p.site_observations),
            knowledge: json(&p.knowledge) }
    }
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_participant)]
pub struct SimNativeParticipant {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub control_epoch: u64,
    pub learning_revision: u64,
    pub cursor: u64,
    pub experiences: String,
    pub speech: String,
    pub last_speech_tick: Option<u64>,
    pub learned_sources: Vec<u64>,
    pub activity: String,
    pub activity_position: Option<i32>,
}

/// Private, individually retained personal evidence. The participant row stores
/// ordered cursor references, so changing a cursor does not rewrite old payloads.
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_experience,
    index(accessor = participant, btree(columns = [run, actor, cursor])),
    index(accessor = controller_scope, btree(columns = [run, actor])))]
pub struct SimNativeExperience {
    #[primary_key]
    pub key: String,
    pub run: String,
    pub actor: u32,
    pub cursor: u64,
    pub source: u64,
    pub tick: u64,
    pub location: i32,
    pub kind: String,
    pub parents: Vec<u64>,
    pub data: String,
}

#[derive(serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ExperienceRefs {
    native_experience_rows_v1: Vec<u64>,
}
// Compact metadata is sufficient for parent linkage, retention and activity.
// Payloads are fetched by cursor only when a mechanic actually inspects them.
type ExperienceIndex = (u64, u64, u64, i32, String, Vec<u64>);
#[derive(serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ExperienceHeads {
    native_experience_rows_v2: Vec<ExperienceIndex>,
}
const TRACE_INDEX: &str = "sao-native-trace-index-v3";
#[derive(Clone, PartialEq, spacetimedb::SpacetimeType)]
pub struct SimNativeTraceEntry {
    pub cursor: u64,
    pub source: u64,
    pub tick: u64,
    pub location: i32,
    pub kind: String,
    pub parents: Vec<u64>,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_trace_index)]
pub struct SimNativeTraceIndex {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub entries: Vec<SimNativeTraceEntry>,
}
impl SimNativeTraceIndex {
    fn from_state(run: &str, actor: u32, state: &ParticipantState) -> Self {
        Self {key:key(run,actor),run:run.into(),actor,
            entries:state.experiences.iter().map(|e|SimNativeTraceEntry {
                cursor:e.cursor,source:e.source,tick:e.tick,location:e.location,
                kind:e.kind.clone(),parents:e.parents.clone(),
            }).collect()}
    }
    fn indexes(self, run: &str, actor: u32) -> Result<Vec<ExperienceIndex>,String> {
        if self.run != run || self.actor != actor || self.key != key(run,actor) {
            return Err("native trace index scope mismatch".into());
        }
        Ok(self.entries.into_iter().map(|e|(e.cursor,e.source,e.tick,e.location,e.kind,e.parents)).collect())
    }
}
fn experience_index(e: &Experience) -> ExperienceIndex {
    (e.cursor, e.source, e.tick, e.location, e.kind.clone(), e.parents.clone())
}
fn experience_cursors(value: &str) -> Result<Vec<u64>, String> {
    if let Ok(heads) = parse::<ExperienceHeads>(value) {
        Ok(heads.native_experience_rows_v2.into_iter().map(|e| e.0).collect())
    } else {
        Ok(parse::<ExperienceRefs>(value)?.native_experience_rows_v1)
    }
}
impl SimNativeExperience {
    fn from_experience(run: &str, actor: u32, e: &Experience) -> Self {
        Self { key: key(run, format!("{actor}:{}", e.cursor)), run: run.into(), actor,
            cursor: e.cursor, source: e.source, tick: e.tick, location: e.location,
            kind: e.kind.clone(), parents: e.parents.clone(), data: json(&e.data) }
    }
    fn experience(self, run: &str) -> Result<Experience, String> {
        if self.run != run || self.key != key(run, format!("{}:{}", self.actor, self.cursor)) {
            return Err("native experience scope mismatch".into());
        }
        Ok(ExperienceRecord { cursor: self.cursor, source: self.source, tick: self.tick,
            location: self.location, kind: self.kind, parents: self.parents,
            data: parse(&self.data)? }.into())
    }
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_lease,
    index(accessor = participant, btree(columns = [run, actor])))]
pub struct SimNativeLease {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub ordinal: u32,
    pub request_id: String,
    pub observed_cursor: u64,
    pub expires_ms: u64,
    pub has_observation: bool,
    pub experiences: String,
}
const LEASE_EVIDENCE: &str = "sao-native-lease-evidence-v1";
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_lease_evidence)]
pub struct SimNativeLeaseEvidence {
    #[primary_key]
    pub lease_id: u64,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub experiences: String,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_capture)]
pub struct SimNativeCapture {
    #[primary_key]
    pub lease_id: u64,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub observation: String,
}
/// Actor-owned support, lifecycle and scheduling fields are independently
/// addressable even when the character has no participant controller.
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_actor_aux)]
pub struct SimNativeActorAux {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub arena: Option<String>,
    pub lifecycle: Option<String>,
    pub offer: Option<String>,
    pub body: Option<String>,
    pub materials: Option<String>,
    pub needs_remainder_ms: Option<u64>,
    pub hazard_remainder_ms: Option<u64>,
    pub action_ready_ms: Option<u64>,
    pub dialogue_ready_ms: Option<u64>,
    pub dirty: Option<bool>,
}
/// Presentation support excludes scheduling bookkeeping. An admitted action
/// can dirty its actor without invalidating every observer of physical bodies.
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_render_actor_support)]
pub struct SimRenderActorSupport {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: u32,
    pub arena: Option<String>,
    pub lifecycle: Option<String>,
    pub offer: Option<String>,
    pub body: Option<String>,
    pub materials: Option<String>,
}
impl SimRenderActorSupport {
    fn from_aux(row: SimNativeActorAux) -> Self {
        Self { key:row.key, run:row.run, actor:row.actor, arena:row.arena,
            lifecycle:row.lifecycle, offer:row.offer, body:row.body, materials:row.materials }
    }
    fn into_aux(self) -> SimNativeActorAux {
        SimNativeActorAux { key:self.key, run:self.run, actor:self.actor, arena:self.arena,
            lifecycle:self.lifecycle, offer:self.offer, body:self.body, materials:self.materials,
            needs_remainder_ms:None, hazard_remainder_ms:None, action_ready_ms:None,
            dialogue_ready_ms:None, dirty:None }
    }
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_site,
    index(accessor = location, btree(columns = [run, position])))]
pub struct SimNativeSite {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub ordinal: u32,
    pub position: i32,
    pub food: i32,
    pub hazard: i32,
    pub shelter: i32,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_station,
    index(accessor = location, btree(columns = [run, position])))]
pub struct SimNativeStation {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub station: u32,
    pub ordinal: u32,
    pub position: i32,
    pub owner: u32,
    pub label: String,
    pub electricity: i32,
    pub electricity_capacity: i32,
    pub parts: i32,
    pub water: i32,
    pub modules: String,
    pub access: String,
    pub generation_period_ms: u64,
    pub generation_amount: i32,
    pub enabled: bool,
    pub integrity: i32,
    pub embodied_parts: i32,
    pub repair_parts_consumed: i32,
    pub generation_remainder_ms: u64,
    pub compute_remainder_ms: u64,
    pub jobs: String,
}
#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_archive,
    index(accessor = location, btree(columns = [run, position])))]
pub struct SimNativeArchive {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub archive: u32,
    pub ordinal: u32,
    pub position: i32,
    pub label: String,
    pub capacity: u64,
    pub destroyed: bool,
    pub revision: u64,
    pub records: String,
}
impl SimNativeArchive {
    pub(super) fn archive(self) -> Result<simulation::knowledge::Archive, String> {
        Ok(simulation::knowledge::Archive {id:self.archive,position:self.position,label:self.label,
            capacity:self.capacity as usize,destroyed:self.destroyed,revision:self.revision,records:parse(&self.records)?})
    }
}

impl SimNativeHead {
    fn from_world(w: &World) -> Self {
        Self {
            run: w.run.clone(),
            version: w.version.clone(),
            tick: w.tick,
            stopped: w.stopped,
            participant_mode: w.participant_mode,
            next_event: w.next_event,
            next_actor: w.next_actor,
            time_ms: w.timing.time_ms,
            updates: w.timing.updates,
            delta_ms: w.timing.delta_ms,
            maintenance_ms: w.timing.maintenance_ms,
            needs_remainder_ms: w.timing.needs_remainder_ms,
            hazard_remainder_ms: w.timing.hazard_remainder_ms,
            next_job: w.infrastructure.next_job,
            applied_disturbances: w
                .timing
                .applied_disturbances
                .iter()
                .map(|&n| n as u64)
                .collect(),
            food_remainder: json(&w.timing.food_remainder_ms),
            pending: json(&w.pending),
            request_ids: w.request_ids.clone(),
        }
    }
}
impl SimNativeActor {
    fn from_player(run: &str, ordinal: usize, p: &Player) -> Self {
        Self {
            key: key(run, p.id),
            run: run.into(),
            actor: p.id,
            ordinal: ordinal as u32,
            name: p.name.clone(),
            human: p.controller == Controller::Human,
            position: p.position,
            health: p.health,
            hunger: p.hunger,
            energy: p.energy,
            food: p.food,
        }
    }
    /// Only these peer fields are consumed by the participant lifecycle catalog.
    /// Private peer state is deliberately absent from a scoped transaction.
    fn peer(&self) -> Player {
        simulation::PlayerData {
            id: self.actor,
            name: self.name.clone(),
            position: self.position,
            health: self.health,
            hunger: self.hunger,
            energy: self.energy,
            food: self.food,
            controller: if self.human {
                Controller::Human
            } else {
                Controller::Ai
            },
            motive: String::new(),
            role: String::new(),
            current_goal: None,
            caution: 0,
            empathy: 0,
            introspection: 0,
            fear: 0,
            knowledge: vec![].into(),
            beliefs: vec![].into(),
            relationships: BTreeMap::new().into(),
            memories: vec![].into(),
            site_observations: vec![].into(),
            execution: None,
            generation: 0,
            failures: 0,
            last_reflection: 0,
            last_cause: None,
        }
        .into()
    }
    fn player(&self, m: &SimNativeMind, history: Option<&SimNativeMindHistory>) -> Result<Player, String> {
        if self.run != m.run || self.actor != m.actor || self.key != m.key {
            return Err("native actor/mind identity mismatch".into());
        }
        let mut p = self.peer();
        p.motive = m.motive.clone();
        p.role = m.role.clone();
        p.current_goal = m.current_goal.clone();
        p.caution = m.caution;
        p.empathy = m.empathy;
        p.introspection = m.introspection;
        p.fear = m.fear;
        p.generation = m.generation;
        p.failures = m.failures;
        p.last_reflection = m.last_reflection;
        p.last_cause = m.last_cause;
        p.execution = parse(&m.execution)?;
        if m.memories == MIND_HISTORY {
            let h = history.ok_or("native mind history missing")?;
            if h.run != m.run || h.actor != m.actor || h.key != m.key {
                return Err("native mind history scope mismatch".into());
            }
            p.beliefs = parse(&h.beliefs)?;
            p.relationships = parse(&h.relationships)?;
            p.memories = parse(&h.memories)?;
            p.site_observations = parse(&h.site_observations)?;
            p.knowledge = parse(&h.knowledge)?;
        } else {
            p.beliefs = parse(&m.beliefs)?;
            p.relationships = parse(&m.relationships)?;
            p.memories = parse(&m.memories)?;
            p.site_observations = parse(&m.site_observations)?;
            p.knowledge = parse(&m.knowledge)?;
        }
        Ok(p)
    }
}
impl SimNativeMind {
    fn from_player(run: &str, p: &Player) -> Self {
        Self {
            key: key(run, p.id),
            run: run.into(),
            actor: p.id,
            motive: p.motive.clone(),
            role: p.role.clone(),
            current_goal: p.current_goal.clone(),
            caution: p.caution,
            empathy: p.empathy,
            introspection: p.introspection,
            fear: p.fear,
            generation: p.generation,
            failures: p.failures,
            last_reflection: p.last_reflection,
            last_cause: p.last_cause,
            execution: json(&p.execution),
            beliefs: "[]".into(),
            relationships: "{}".into(),
            memories: MIND_HISTORY.into(),
            site_observations: "[]".into(),
            knowledge: "[]".into(),
        }
    }
}
impl SimNativeParticipant {
    fn from_state(run: &str, actor: u32, s: &ParticipantState) -> Self {
        Self::from_state_with_heads(run, actor, s, None)
    }
    fn from_state_with_heads(run: &str, actor: u32, s: &ParticipantState, heads: Option<String>) -> Self {
        Self {
            key: key(run, actor),
            run: run.into(),
            actor,
            control_epoch: s.control_epoch,
            learning_revision: s.learning_revision,
            cursor: s.cursor,
            experiences: heads.unwrap_or_else(|| json(&ExperienceHeads { native_experience_rows_v2: s.experiences.iter().map(experience_index).collect() })),
            speech: json(&s.speech),
            last_speech_tick: s.last_speech_tick,
            learned_sources: s.learned_sources.clone(),
            activity: json(&s.activity),
            activity_position: s.activity_position,
        }
    }
    fn state(
        &self,
        mut experiences: BTreeMap<u64, Experience>,
        leases: Vec<EvidenceLease>,
        receipts: Vec<Receipt>,
    ) -> Result<ParticipantState, String> {
        let experiences = if self.experiences.starts_with('{') {
            let refs = experience_cursors(&self.experiences)?;
            if refs.len() != experiences.len() {
                return Err("native experience reference count mismatch".into());
            }
            let values = refs.into_iter()
                .map(|id| experiences.remove(&id).ok_or_else(|| "native experience missing or duplicated".into()))
                .collect::<Result<Vec<_>, String>>()?;
            if let Ok(heads) = parse::<ExperienceHeads>(&self.experiences) {
                if heads.native_experience_rows_v2 != values.iter().map(experience_index).collect::<Vec<_>>() {
                    return Err("native experience metadata mismatch".into());
                }
            }
            values
        } else {
            // Read old component rows until this actor's next ordinary save.
            parse(&self.experiences)?
        };
        self.state_from_experiences(experiences.into(), leases, receipts.into())
    }
    fn state_from_experiences(&self, experiences: simulation::deferred::Deferred<Vec<Experience>>, leases: Vec<EvidenceLease>,
        receipts: Deferred<Vec<Receipt>>) -> Result<ParticipantState, String> {
        Ok(simulation::participant::ParticipantStateData {
            client_controller: None,
            control_epoch: self.control_epoch,
            learning_revision: self.learning_revision,
            cursor: self.cursor,
            experiences: experiences.into(),
            speech: parse(&self.speech)?,
            last_speech_tick: self.last_speech_tick,
            learned_sources: self.learned_sources.clone(),
            activity: parse(&self.activity)?,
            activity_position: self.activity_position,
            evidence_leases: leases,
            receipts,
        }
        .into())
    }
}
impl SimNativeLease {
    fn lease(
        &self,
        captures: &BTreeMap<u64, SimNativeCapture>,
        evidence: &BTreeMap<u64, SimNativeLeaseEvidence>,
        cold: Option<&Arc<ColdReader>>,
        materialize: bool,
    ) -> Result<EvidenceLease, String> {
        let observation = if !self.has_observation {
            serde_json::value::to_raw_value(&serde_json::Value::Null)
                .unwrap()
                .into()
        } else if materialize {
            let row = captures
                .get(&self.id)
                .ok_or("native captured context missing")?;
            if row.run != self.run || row.actor != self.actor {
                return Err("native captured context scope mismatch".into());
            }
            serde_json::value::RawValue::from_string(row.observation.clone())
                .map_err(|e| e.to_string())?
                .into()
        } else {
            simulation::participant::Observation::deferred(self.id)
        };
        Ok(EvidenceLease {
            request_id: self.request_id.clone(),
            observed_cursor: self.observed_cursor,
            expires_ms: self.expires_ms,
            observation,
            experiences: if self.experiences != LEASE_EVIDENCE {
                parse(&self.experiences)?
            } else if let Some(reader) = cold {
                let reader = reader.clone();
                let (run, actor, id) = (self.run.clone(), self.actor, self.id);
                Deferred::load_with(move || (reader.lease)(&run, actor, id))
            } else {
                let row = evidence.get(&self.id).ok_or("native lease evidence missing")?;
                if row.run != self.run || row.actor != self.actor {
                    return Err("native lease evidence scope mismatch".into());
                }
                parse(&row.experiences)?
            },
        })
    }
}
impl SimNativeActorAux {
    fn from_world(w: &World, actor: u32) -> Self {
        Self {
            key: key(&w.run, actor),
            run: w.run.clone(),
            actor,
            arena: w.actor_arenas.get(&actor).cloned(),
            lifecycle: w.lifecycle.get(&actor).map(json),
            offer: w.reproduction_offers.get(&actor).map(json),
            body: w.infrastructure.bodies.get(&actor).map(json),
            materials: w.infrastructure.actor_materials.get(&actor).map(json),
            needs_remainder_ms: w.timing.actor_needs_remainder_ms.get(&actor).copied(),
            hazard_remainder_ms: w.timing.actor_hazard_remainder_ms.get(&actor).copied(),
            action_ready_ms: w.timing.action_ready_ms.get(&actor).copied(),
            dialogue_ready_ms: w.timing.dialogue_ready_ms.get(&actor).copied(),
            dirty: w.timing.dirty.get(&actor).copied(),
        }
    }
    fn apply(&self, w: &mut World) -> Result<(), String> {
        let actor = self.actor;
        macro_rules! decoded {
            ($field:ident,$map:expr) => {
                if let Some(v) = &self.$field {
                    $map.insert(actor, parse(v)?);
                }
            };
        }
        decoded!(lifecycle, w.lifecycle);
        decoded!(offer, w.reproduction_offers);
        decoded!(body, w.infrastructure.bodies);
        decoded!(materials, w.infrastructure.actor_materials);
        if let Some(v) = &self.arena {
            w.actor_arenas.insert(actor, v.clone());
        }
        macro_rules! copied {
            ($field:ident,$map:expr) => {
                if let Some(v) = self.$field {
                    $map.insert(actor, v);
                }
            };
        }
        copied!(needs_remainder_ms, w.timing.actor_needs_remainder_ms);
        copied!(hazard_remainder_ms, w.timing.actor_hazard_remainder_ms);
        copied!(action_ready_ms, w.timing.action_ready_ms);
        copied!(dialogue_ready_ms, w.timing.dialogue_ready_ms);
        copied!(dirty, w.timing.dirty);
        Ok(())
    }
}
impl SimNativeStation {
    fn from_station(run: &str, ordinal: usize, s: &simulation::infrastructure::Station) -> Self {
        Self {
            key: key(run, s.seed.id),
            run: run.into(),
            station: s.seed.id,
            ordinal: ordinal as u32,
            position: s.seed.position,
            owner: s.seed.owner,
            label: s.seed.label.clone(),
            electricity: s.seed.electricity,
            electricity_capacity: s.seed.electricity_capacity,
            parts: s.seed.materials.parts,
            water: s.seed.materials.water,
            modules: json(&s.seed.modules),
            access: json(&s.seed.access),
            generation_period_ms: s.seed.generation_period_ms,
            generation_amount: s.seed.generation_amount,
            enabled: s.enabled,
            integrity: s.integrity,
            embodied_parts: s.embodied_parts,
            repair_parts_consumed: s.repair_parts_consumed,
            generation_remainder_ms: s.generation_remainder_ms,
            compute_remainder_ms: s.compute_remainder_ms,
            jobs: json(&s.jobs),
        }
    }
    fn station(&self) -> Result<simulation::infrastructure::Station, String> {
        use simulation::infrastructure::{Materials, Station, StationSeed};
        Ok(Station {
            seed: StationSeed {
                id: self.station,
                owner: self.owner,
                position: self.position,
                label: self.label.clone(),
                electricity: self.electricity,
                electricity_capacity: self.electricity_capacity,
                materials: Materials {
                    parts: self.parts,
                    water: self.water,
                },
                modules: parse(&self.modules)?,
                access: parse(&self.access)?,
                generation_period_ms: self.generation_period_ms,
                generation_amount: self.generation_amount,
            },
            enabled: self.enabled,
            integrity: self.integrity,
            embodied_parts: self.embodied_parts,
            repair_parts_consumed: self.repair_parts_consumed,
            generation_remainder_ms: self.generation_remainder_ms,
            compute_remainder_ms: self.compute_remainder_ms,
            jobs: parse(&self.jobs)?,
        })
    }
}

/// Host reads are kept separate from assembly so the exact representation and
/// scoped dependency projection can be differential-tested without a DB host.
struct ColdReader {
    paged: Box<dyn Fn(&str,u32) -> Result<Vec<SimNativePagedTraceEntry>,String> + Send + Sync>,
    payloads: trace::Payloads,
    trace: Box<dyn Fn(&str, u32) -> Result<SimNativeTraceIndex, String> + Send + Sync>,
    catalog: Box<dyn Fn(&str) -> Result<SimNativeControllerCatalog, String> + Send + Sync>,
    receipts: Box<dyn Fn(&str, u32) -> Result<Vec<Receipt>, String> + Send + Sync>,
    bootstrap: Box<dyn Fn(&str, u32) -> Result<simulation::controller::Bootstrap, String> + Send + Sync>,
    mind: Box<dyn Fn(&str, u32) -> Result<SimNativeMindHistory, String> + Send + Sync>,
    experience: Box<dyn Fn(&str, u32, u64) -> Result<SimNativeExperience, String> + Send + Sync>,
    legacy_experiences: Box<dyn Fn(&str, u32) -> Result<Vec<SimNativeExperience>, String> + Send + Sync>,
    lease: Box<dyn Fn(&str, u32, u64) -> Result<Vec<Experience>, String> + Send + Sync>,
}
macro_rules! cold_reader_for {
    ($ctx:expr) => {{
        let ctx = $ctx;
    let page_heads = ctx.db.sim_native_trace_head().key();
    let pages = ctx.db.sim_native_trace_page().participant();
    let bodies = ctx.db.sim_native_evidence_body().id();
    let traces = ctx.db.sim_native_trace_index().key();
    let catalogs = ctx.db.sim_native_controller_catalog().key();
    let receipts = ctx.db.sim_participant_receipt().participant();
    let bootstraps = ctx.db.sim_controller_bootstrap().key();
    let minds = ctx.db.sim_native_mind_history().key();
    let experiences = ctx.db.sim_native_experience().key();
    let legacy_experiences = ctx.db.sim_native_experience().participant();
    let leases = ctx.db.sim_native_lease_evidence().lease_id();
    Arc::new(ColdReader {
        paged: Box::new(move |run,actor| trace::unpack(run,actor,
            page_heads.find(key(run,actor)).ok_or("native trace head missing")?, pages.filter((run,actor)).collect())),
        payloads: trace::Payloads::new(move |run,id| {
            let data=trace::body_data(run,id,bodies.find(id).ok_or("native evidence body missing")?)?;
            count_cold_read(1,data.len()); Ok(data)
        }),
        trace: Box::new(move |run,actor| traces.find(key(run,actor)).ok_or("native trace index missing".into())),
        catalog: Box::new(move |id| {
            let row = catalogs.find(id.to_owned()).ok_or("controller catalog missing")?;
            #[cfg(feature = "clock-profile")]
            log::info!("controller-catalog-load bytes={}", row.body.len());
            Ok(row)
        }),
        receipts: Box::new(move |run, actor| {
            let mut values = receipts.filter((run, actor)).map(|r| Receipt {
                request_id:r.request_id, fingerprint:r.fingerprint, ok:r.ok, error:r.error, event:r.event,
            }).collect::<Vec<_>>();
            values.sort_by_key(|r| r.event);
            Ok(values)
        }),
        bootstrap: Box::new(move |run, actor| {
            let row = bootstraps.find(key(run, actor)).ok_or("controller bootstrap missing")?;
            if row.run != run || row.actor != actor { return Err("controller bootstrap scope mismatch".into()); }
            parse(&row.body)
        }),
        mind: Box::new(move |run, actor| {
            let row = minds.find(key(run, actor)).ok_or("native mind history missing")?;
            if row.run != run || row.actor != actor || row.key != key(run, actor) {
                return Err("native mind history scope mismatch".into());
            }
            count_cold_read(0, row.beliefs.len() + row.relationships.len() + row.memories.len()
                + row.site_observations.len() + row.knowledge.len());
            Ok(row)
        }),
        experience: Box::new(move |run, actor, cursor| {
            let row = experiences.find(key(run, format!("{actor}:{cursor}")))
                .ok_or("native experience missing")?;
            if row.run != run || row.actor != actor || row.cursor != cursor
                || row.key != key(run, format!("{actor}:{cursor}")) {
                return Err("native experience scope mismatch".into());
            }
            count_cold_read(1, row.data.len());
            Ok(row)
        }),
        legacy_experiences: Box::new(move |run, actor| {
            Ok(legacy_experiences.filter((run, actor)).collect())
        }),
        lease: Box::new(move |run, actor, id| {
            let row = leases.find(id).ok_or("native lease evidence missing")?;
            if row.run != run || row.actor != actor { return Err("native lease evidence scope mismatch".into()); }
            count_cold_read(2, row.experiences.len());
            parse(&row.experiences)
        }),
    })

    }};
}
fn cold_reader(ctx: &ReducerContext) -> Arc<ColdReader> { cold_reader_for!(ctx) }
fn view_cold_reader(ctx: &ViewContext) -> Arc<ColdReader> { cold_reader_for!(ctx) }

/// The caller has already authenticated the participant scope. Only this
/// actor's pages and actually delivered bodies enter the view's read set.
pub(super) fn experience_rows_for_view(ctx:&ViewContext,run:&str,actor:u32,after:u64) -> Vec<SimNativeExperience> {
    let paged=ctx.db.sim_native_participant().key().find(key(run,actor))
        .is_some_and(|p|p.experiences==trace::MARKER);
    if !paged {
        return ctx.db.sim_native_experience().controller_scope().filter((run,actor))
            .filter(|row|row.cursor>after).collect();
    }
    let entries=trace::view_entries(ctx,run,actor,after).expect("valid scoped trace pages");
    let mut bodies=BTreeMap::new();
    entries.into_iter().filter(|e|e.metadata.cursor>after).map(|entry| {
        let data=bodies.entry(entry.body).or_insert_with(|| {
            let row=ctx.db.sim_native_evidence_body().id().find(entry.body).expect("retained evidence body");
            trace::body_data(run,entry.body,row).expect("valid evidence body")
        }).clone();
        trace::to_row(run,actor,entry,data)
    }).collect()
}

fn deferred_player(a: &SimNativeActor, m: &SimNativeMind, reader: &Arc<ColdReader>) -> Result<Player, String> {
    if m.memories != MIND_HISTORY { return a.player(m, None); }
    let mut hot = m.clone();
    hot.memories = "[]".into();
    let mut p = a.player(&hot, None)?;
    let (run, actor, reader) = (a.run.clone(), a.actor, reader.clone());
    let history = Deferred::load_with(move || (reader.mind)(&run, actor));
    macro_rules! field {
        ($field:ident) => {{
            let history = history.clone();
            Deferred::load_with(move || parse(&history.try_get()?.$field))
        }};
    }
    p.beliefs = field!(beliefs);
    p.relationships = field!(relationships);
    p.memories = field!(memories);
    p.site_observations = field!(site_observations);
    p.knowledge = field!(knowledge);
    Ok(p)
}
fn deferred_experiences(p: &SimNativeParticipant, reader: &Arc<ColdReader>) -> Result<(Vec<Experience>, bool), String> {
    if p.experiences == trace::MARKER {
        let entries=(reader.paged)(&p.run,p.actor)?;
        return Ok((reader.payloads.experiences(&p.run,entries),true));
    }
    let heads = if p.experiences == TRACE_INDEX {
        Some(ExperienceHeads {native_experience_rows_v2:(reader.trace)(&p.run,p.actor)?.indexes(&p.run,p.actor)?})
    } else { parse::<ExperienceHeads>(&p.experiences).ok() };
    let Some(heads) = heads else {
        // Old inline arrays need no external rows. V1 cursor-only headers are
        // read once through the indexed compatibility path and upgrade on save.
        let values = if p.experiences.starts_with('{') {
            (reader.legacy_experiences)(&p.run, p.actor)?.into_iter().map(|e| e.experience(&p.run)).collect()
        } else { Ok(vec![]) }?;
        return Ok((values, false));
    };
    let mut cursors = BTreeSet::new();
    if !heads.native_experience_rows_v2.iter().all(|e| cursors.insert(e.0)) {
        return Err("duplicate native experience cursor".into());
    }
    Ok((heads.native_experience_rows_v2.into_iter().map(|index| {
        let (run, actor, reader, expected) = (p.run.clone(), p.actor, reader.clone(), index.clone());
        ExperienceRecord { cursor: index.0, source: index.1, tick: index.2, location: index.3,
            kind: index.4, parents: index.5,
            data: simulation::participant::ExperienceData::load_with(move || {
                let row = (reader.experience)(&run, actor, expected.0)?;
                if (row.cursor, row.source, row.tick, row.location, row.kind, row.parents) != expected {
                    return Err("native experience metadata mismatch".into());
                }
                serde_json::value::RawValue::from_string(row.data).map_err(|e| e.to_string())
            }),
        }.into()
    }).collect(), true))
}
struct Rows {
    paged_heads: Vec<SimNativeTraceHead>,
    trace_pages: Vec<SimNativeTracePage>,
    evidence_bodies: Vec<SimNativeEvidenceBody>,
    trace_indexes: Vec<SimNativeTraceIndex>,
    catalogs: Vec<SimNativeControllerCatalog>,
    controllers: Vec<SimNativeController>,
    bootstraps: Vec<SimControllerBootstrap>,
    head: SimNativeHead,
    definitions: DefinitionSet,
    actors: Vec<SimNativeActor>,
    minds: Vec<SimNativeMind>,
    mind_histories: Vec<SimNativeMindHistory>,
    participants: Vec<SimNativeParticipant>,
    experiences: Vec<SimNativeExperience>,
    leases: Vec<SimNativeLease>,
    lease_evidence: Vec<SimNativeLeaseEvidence>,
    captures: Vec<SimNativeCapture>,
    receipts: Vec<super::participant_delivery::SimParticipantReceipt>,
    aux: Vec<SimNativeActorAux>,
    sites: Vec<SimNativeSite>,
    stations: Vec<SimNativeStation>,
    archives: Vec<SimNativeArchive>,
}
fn assemble(
    rows: Rows,
    scoped_actor: Option<u32>,
    materialize: bool,
) -> Result<(World, LeaseIds), String> {
    assemble_with(rows, scoped_actor, materialize, None)
}
fn assemble_with(
    mut rows: Rows,
    scoped_actor: Option<u32>,
    materialize: bool,
    cold: Option<Arc<ColdReader>>,
) -> Result<(World, LeaseIds), String> {
    let h = rows.head;
    let mut w = World {
        run: h.run,
        version: h.version,
        initial: rows.definitions.initial,
        scripts: rows.definitions.scripts,
        laws: rows.definitions.laws,
        tick: h.tick,
        timing: simulation::timing::Timing {
            time_ms: h.time_ms,
            updates: h.updates,
            delta_ms: h.delta_ms,
            maintenance_ms: h.maintenance_ms,
            needs_remainder_ms: h.needs_remainder_ms,
            hazard_remainder_ms: h.hazard_remainder_ms,
            applied_disturbances: h
                .applied_disturbances
                .into_iter()
                .map(|n| n as usize)
                .collect(),
            food_remainder_ms: parse(&h.food_remainder)?,
            actor_needs_remainder_ms: BTreeMap::new(),
            actor_hazard_remainder_ms: BTreeMap::new(),
            action_ready_ms: BTreeMap::new(),
            dialogue_ready_ms: BTreeMap::new(),
            dirty: BTreeMap::new(),
        },
        players: vec![],
        sites: vec![],
        infrastructure: simulation::infrastructure::InfrastructureState {
            balance: rows.definitions.balance,
            next_job: h.next_job,
            bodies: BTreeMap::new(),
            actor_materials: BTreeMap::new(),
            stations: vec![],
        },
        archives: vec![],
        lifecycle: BTreeMap::new(),
        reproduction_offers: BTreeMap::new(),
        next_actor: h.next_actor,
        actor_arenas: BTreeMap::new(),
        pending: parse(&h.pending)?,
        next_event: h.next_event,
        stopped: h.stopped,
        request_ids: h.request_ids,
        participant_mode: h.participant_mode,
        participants: BTreeMap::new(),
        events: vec![],
    };
    rows.actors.sort_by_key(|a| a.ordinal);
    let minds: BTreeMap<_, _> = rows.minds.into_iter().map(|m| (m.actor, m)).collect();
    let mind_histories: BTreeMap<_, _> = rows.mind_histories.into_iter().map(|m| (m.actor, m)).collect();
    for a in rows.actors {
        if a.run != w.run {
            return Err("native actor run mismatch".into());
        }
        w.players
            .push(if scoped_actor.is_some_and(|id| id != a.actor) {
                a.peer()
            } else if let Some(reader) = &cold {
                deferred_player(&a, minds.get(&a.actor).ok_or("native mind missing")?, reader)?
            } else {
                a.player(minds.get(&a.actor).ok_or("native mind missing")?, mind_histories.get(&a.actor))?
            });
    }
    rows.leases.sort_by_key(|l| (l.actor, l.ordinal));
    let captures = rows.captures.into_iter().map(|r| (r.lease_id, r)).collect();
    let lease_evidence = rows.lease_evidence.into_iter().map(|r| (r.lease_id, r)).collect();
    let mut lease_ids = LeaseIds::new();
    let mut leases: BTreeMap<u32, Vec<EvidenceLease>> = BTreeMap::new();
    for l in rows.leases {
        if l.run != w.run {
            return Err("native lease run mismatch".into());
        }
        lease_ids.entry(l.actor).or_default().push(l.id);
        leases
            .entry(l.actor)
            .or_default()
            .push(l.lease(&captures, &lease_evidence, cold.as_ref(), materialize)?);
    }
    rows.receipts.sort_by_key(|r| r.event);
    let mut receipts: BTreeMap<u32, Vec<Receipt>> = BTreeMap::new();
    for r in rows.receipts {
        if r.run != w.run {
            return Err("native receipt run mismatch".into());
        }
        receipts.entry(r.actor).or_default().push(Receipt {
            request_id: r.request_id,
            fingerprint: r.fingerprint,
            ok: r.ok,
            error: r.error,
            event: r.event,
        });
    }
    let mut experiences: BTreeMap<u32, BTreeMap<u64, Experience>> = BTreeMap::new();
    for row in rows.experiences {
        let actor = row.actor;
        let value = row.experience(&w.run)?;
        if experiences.entry(actor).or_default().insert(value.cursor, value).is_some() {
            return Err("duplicate native experience cursor".into());
        }
    }
    let mut paged_heads:BTreeMap<_,_>=rows.paged_heads.into_iter().map(|r|(r.actor,r)).collect();
    let mut trace_pages:BTreeMap<u32,Vec<SimNativeTracePage>>=BTreeMap::new();
    for page in rows.trace_pages {trace_pages.entry(page.actor).or_default().push(page);}
    let bodies:BTreeMap<_,_>=rows.evidence_bodies.into_iter().map(|row| {
        let id=row.id; trace::body_data(&w.run,id,row).map(|body|(id,body))
    }).collect::<Result<_,_>>()?;
    let mut trace_indexes: BTreeMap<_,_> = rows.trace_indexes.into_iter().map(|r|(r.actor,r)).collect();
    for mut p in rows.participants {
        if p.run != w.run {
            return Err("native participant run mismatch".into());
        }
        lease_ids.entry(p.actor).or_default();
        if let Some(reader) = &cold {
            let (source, reader) = (p.clone(), reader.clone());
            let trace = simulation::deferred::Deferred::load_with(move || {
                let (decoded, indexed) = deferred_experiences(&source, &reader)?;
                if indexed { return Ok(decoded); }
                let mut values = BTreeMap::new();
                for e in decoded {
                    if values.insert(e.cursor, e).is_some() {
                        return Err("duplicate native experience cursor".into());
                    }
                }
                // The legacy decoder validates cursor references and preserves
                // inline-array semantics before returning the exact trace.
                Ok(source.state(values, vec![], vec![])?.experiences.to_vec())
            });
            let (receipt_reader, receipt_run, receipt_actor) = (cold.as_ref().unwrap().clone(), w.run.clone(), p.actor);
            let receipt_values = Deferred::load_with(move || (receipt_reader.receipts)(&receipt_run, receipt_actor));
            w.participants.insert(p.actor, p.state_from_experiences(trace,
                leases.remove(&p.actor).unwrap_or_default(), receipt_values)?);
            continue;
        }
        if p.experiences == trace::MARKER {
            let entries=trace::unpack(&p.run,p.actor,paged_heads.remove(&p.actor).ok_or("native trace head missing")?,
                trace_pages.remove(&p.actor).unwrap_or_default())?;
            let mut values=Vec::with_capacity(entries.len());
            for entry in entries {
                let data=bodies.get(&entry.body).ok_or("native evidence body missing")?.clone();
                values.push(trace::to_row(&p.run,p.actor,entry,data).experience(&p.run)?);
            }
            w.participants.insert(p.actor,p.state_from_experiences(values.into(),
                leases.remove(&p.actor).unwrap_or_default(),receipts.remove(&p.actor).unwrap_or_default().into())?);
            continue;
        }
        if p.experiences == TRACE_INDEX {
            let index = trace_indexes.remove(&p.actor).ok_or("native trace index missing")?.indexes(&p.run,p.actor)?;
            // Eager exports retain the existing exact order/count/metadata checks.
            p.experiences = json(&ExperienceHeads {native_experience_rows_v2:index});
        }
        w.participants.insert(
            p.actor,
            p.state(
                experiences.remove(&p.actor).unwrap_or_default(),
                leases.remove(&p.actor).unwrap_or_default(),
                receipts.remove(&p.actor).unwrap_or_default(),
            )?,
        );
    }
    let mut bootstraps: BTreeMap<_, _> = rows.bootstraps.into_iter().map(|b|(b.actor,b)).collect();
    // Rows have already been selected by this transaction's authority scope.
    // Equal immutable payload bytes can share decoding/comparison work; retain
    // separate controller metadata and never fetch another row to find a match.
    let catalog_rows: BTreeMap<_, _> = rows.catalogs.into_iter().map(|row| (row.key.clone(), row)).collect();
    let mut lifecycle_payloads = BTreeMap::<String, Option<simulation::participant::ExperienceData>>::new();
    #[cfg(feature = "clock-profile")]
    let controller_rows = rows.controllers.len();
    #[cfg(feature = "clock-profile")]
    let controller_hot_bytes: usize = rows.controllers.iter().map(|c|c.last_lifecycle.len()).sum();
    #[cfg(feature = "clock-profile")]
    let mut catalog_reads = [0usize; 2];
    for c in rows.controllers {
        if c.run != w.run || c.key != key(&w.run, c.actor) { return Err("controller scope mismatch".into()); }
        let bootstrap = if let Some(reader) = &cold {
            let (reader, run, actor) = (reader.clone(), w.run.clone(), c.actor);
            Deferred::load_with(move || (reader.bootstrap)(&run, actor))
        } else {
            let b = bootstraps.remove(&c.actor).ok_or("controller bootstrap missing")?;
            if b.run != w.run || b.key != c.key { return Err("bootstrap scope mismatch".into()); }
            parse::<simulation::controller::Bootstrap>(&b.body)?.into()
        };
        let last_lifecycle = match lifecycle_payloads.entry(c.last_lifecycle) {
            std::collections::btree_map::Entry::Occupied(entry) => entry.get().clone(),
            std::collections::btree_map::Entry::Vacant(entry) => {
                let value = if let Some(reader) = &cold {
                    let reader = reader.clone();
                    catalog::deferred(&w.run, entry.key(), move |id| (reader.catalog)(id))?
                } else {
                    catalog::resolve(&w.run, entry.key(), |id| {
                        let row = catalog_rows.get(id).cloned().ok_or("controller catalog missing")?;
                        #[cfg(feature = "clock-profile")]
                        { catalog_reads[0] += 1; catalog_reads[1] += row.body.len(); }
                        Ok(row)
                    })?
                };
                entry.insert(value).clone()
            }
        };
        w.participants.get_mut(&c.actor).ok_or("controller participant missing")?.client_controller = Some(simulation::controller::Authority {
            bootstrap, known_targets: c.known_targets.into_iter().collect(),
            last_lifecycle, action: parse(&c.action)?,
        });
    }
    #[cfg(feature = "clock-profile")]
    log::info!("controller-catalogs rows={} distinct={}", controller_rows, lifecycle_payloads.len());
    #[cfg(feature = "clock-profile")]
    log::info!("controller-catalog-storage {}", serde_json::json!({
        "hot_bytes":controller_hot_bytes,"body_reads":catalog_reads[0],"body_bytes":catalog_reads[1],
        "deferred":cold.is_some()}));
    for aux in rows.aux {
        aux.apply(&mut w)?;
    }
    rows.sites.sort_by_key(|s| s.ordinal);
    w.sites = rows
        .sites
        .into_iter()
        .map(|s| simulation::Site {
            position: s.position,
            food: s.food,
            hazard: s.hazard,
            shelter: s.shelter,
        })
        .collect();
    rows.stations.sort_by_key(|s| s.ordinal);
    w.infrastructure.stations = rows
        .stations
        .into_iter()
        .map(|s| s.station())
        .collect::<Result<_, _>>()?;
    rows.archives.sort_by_key(|a| a.ordinal);
    w.archives = rows
        .archives
        .into_iter()
        .map(SimNativeArchive::archive)
        .collect::<Result<_, String>>()?;
    Ok((w, lease_ids))
}

macro_rules! read_all {
    ($db:expr,$run:expr,$materialize:expr) => { read_all!($db,$run,$materialize,false) };
    ($db:expr,$run:expr,$materialize:expr,$cold:expr) => {{
        let run = $run;
        Rows {
            paged_heads: if $cold {vec![]} else {$db.sim_native_trace_head().run().filter(run).collect()},
            trace_pages: if $cold {vec![]} else {$db.sim_native_trace_page().participant().filter((run,)).collect()},
            evidence_bodies: if $cold {vec![]} else {$db.sim_native_evidence_body().run().filter(run).collect()},
            trace_indexes: if $cold {vec![]} else {$db.sim_native_trace_index().run().filter(run).collect()},
            catalogs: if $cold { vec![] } else { $db.sim_native_controller_catalog().run().filter(run).collect() },
            controllers: $db.sim_native_controller().run().filter(run).collect(),
            bootstraps: if $cold { vec![] } else { $db.sim_controller_bootstrap().run().filter(run).collect() },
            head: $db
                .sim_native_head()
                .run()
                .find(run.to_owned())
                .ok_or("native run head missing")?,
            definitions: read_definitions!($db, run, $materialize),
            actors: $db.sim_native_actor().run().filter(run).collect(),
            minds: $db.sim_native_mind().run().filter(run).collect(),
            mind_histories: if $cold { vec![] } else { $db.sim_native_mind_history().run().filter(run).collect() },
            participants: $db.sim_native_participant().run().filter(run).collect(),
            experiences: if $cold { vec![] } else { $db.sim_native_experience().participant().filter((run,)).collect() },
            leases: $db.sim_native_lease().run().filter(run).collect(),
            lease_evidence: if $cold { vec![] } else { $db.sim_native_lease_evidence().run().filter(run).collect() },
            captures: if $materialize {
                $db.sim_native_capture().run().filter(run).collect()
            } else {
                vec![]
            },
            receipts: if $cold { vec![] } else { $db
                .sim_participant_receipt()
                .participant()
                .filter((run,))
                .collect() },
            aux: $db.sim_native_actor_aux().run().filter(run).collect(),
            sites: $db.sim_native_site().run().filter(run).collect(),
            stations: $db.sim_native_station().run().filter(run).collect(),
            archives: $db.sim_native_archive().run().filter(run).collect(),
        }
    }};
}
pub(super) fn load(ctx: &ReducerContext, run: &str) -> Result<(World, LeaseIds), String> {
    assemble(read_all!(ctx.db, run, false), None, false)
}
pub(super) fn load_clock(ctx: &ReducerContext, run: &str) -> Result<(World, LeaseIds), String> {
    #[cfg(feature = "clock-profile")]
    COLD_READS.with(|counts| counts.set([0; 6]));
    let rows = super::measured("clock.read_rows", || Ok::<Rows, String>(read_all!(ctx.db, run, false, true)))?;
    super::measured("clock.assemble", || assemble_with(rows, None, false, Some(cold_reader(ctx))))
}
pub(super) fn select_clock(ctx: &ReducerContext, w: &World, delta_ms: u64) -> Option<simulation::clock::Selection> {
    let state = ctx.db.sim_native_clock_state().run().find(&w.run)?;
    if state.version != CLOCK_INDEX_VERSION || state.script_revision != w.scripts.revision
        || state.actors != w.players.iter().map(|p| p.id).collect::<Vec<_>>() {
        return None; // Old representations rebuild atomically after a full shared-kernel update.
    }
    let until = w.timing.time_ms.saturating_add(delta_ms);
    let actors = ctx.db.sim_native_clock_actor().active_actors().filter((w.run.as_str(), true))
        .chain(ctx.db.sim_native_clock_actor().due().filter((w.run.as_str(), ..=until)))
        .map(|r| r.actor).collect::<BTreeSet<_>>();
    Some(simulation::clock::Selection::new(w, actors))
}
pub(super) fn load_export(ctx: &ReducerContext, run: &str) -> Result<World, String> {
    assemble(read_all!(ctx.db, run, true), None, true).map(|(w, _)| w)
}
pub(super) fn load_view(ctx: &ViewContext, run: &str) -> Result<World, String> {
    assemble(read_all!(ctx.db, run, true), None, true).map(|(w, _)| w)
}
/// Observer-only caller authenticates before entering this path. Bodies remain
/// a run-indexed render set; private histories are read for one inspector only.
pub(super) fn observer_view(ctx: &ViewContext, run: &str, inspected: Option<u32>) -> Result<World, String> {
    let actors: Vec<_> = ctx.db.sim_native_actor().run().filter(run).collect();
    let actor = inspected.or_else(|| actors.first().map(|p| p.actor)).unwrap_or(0);
    let actor_key = key(run, actor);
    let support: Vec<_> = ctx.db.sim_render_actor_support().run().filter(run).collect();
    let aux = if support.is_empty() {
        // Existing databases acquire support rows on the next global commit.
        ctx.db.sim_native_actor_aux().run().filter(run).collect()
    } else { support.into_iter().map(SimRenderActorSupport::into_aux).collect() };
    let rows = Rows {
        paged_heads:vec![],trace_pages:vec![],evidence_bodies:vec![],
        trace_indexes: vec![],
        catalogs: vec![],
        head: render_head!(ctx.db, run)?,
        definitions: read_definitions!(ctx.db, run),
        actors,
        minds: ctx.db.sim_native_mind().key().find(&actor_key).into_iter().collect(),
        mind_histories: vec![],
        participants: ctx.db.sim_native_participant().key().find(&actor_key).into_iter().collect(),
        controllers: ctx.db.sim_native_controller().key().find(&actor_key).into_iter().collect(),
        bootstraps: vec![],
        experiences: vec![],
        // Inspection context does not read command receipts or captured leases.
        leases: vec![], lease_evidence: vec![], captures: vec![], receipts: vec![],
        aux,
        sites: ctx.db.sim_native_site().run().filter(run).collect(),
        stations: ctx.db.sim_native_station().run().filter(run).collect(),
        archives: ctx.db.sim_native_archive().run().filter(run).collect(),
    };
    assemble_with(rows, Some(actor), false, Some(view_cold_reader(ctx))).map(|(world, _)| world)
}
pub(super) fn histories_separated(ctx: &ReducerContext, run: &str) -> bool {
    ctx.db.sim_native_mind().run().filter(run).all(|m| m.memories == MIND_HISTORY)
        && ctx.db.sim_native_participant().run().filter(run).all(|p| p.experiences == trace::MARKER || p.experiences == TRACE_INDEX || parse::<ExperienceHeads>(&p.experiences).is_ok())
        && ctx.db.sim_native_lease().run().filter(run).all(|l| l.experiences == LEASE_EVIDENCE)
        && ctx.db.sim_native_clock_state().run().find(run.to_owned()).is_some_and(|s| s.version == CLOCK_INDEX_VERSION)
}

macro_rules! read_participant_rows {
    ($db:expr,$run:expr,$actor:expr,$materialize:expr) => {read_participant_rows!($db,$run,$actor,$materialize,false)};
    ($db:expr,$run:expr,$actor:expr,$materialize:expr,$cold:expr) => {read_participant_rows!($db,$run,$actor,$materialize,$cold,true)};
    ($db:expr,$run:expr,$actor:expr,$materialize:expr,$cold:expr,$leases:expr) => {read_participant_rows!($db,$run,$actor,$materialize,$cold,$leases,true)};
    ($db:expr,$run:expr,$actor:expr,$materialize:expr,$cold:expr,$leases:expr,$local:expr) => {{
        let run = $run;
        let actor = $actor;

        let own = $db
            .sim_native_actor()
            .key()
            .find(key(run, actor))
            .ok_or("unknown actor")?;
        let position = own.position;
        let actors: Vec<_> = if $local { $db
            .sim_native_actor()
            .location()
            .filter((run, position))
            .collect() } else { vec![own] };
        let stations: Vec<_> = if $local { $db
            .sim_native_station()
            .location()
            .filter((run, position))
            .collect() } else { vec![] };
        // An owned station may belong to an actor at a different location; arena
        // membership for that owner is a dependency even though their mind is not.
        let aux_ids: BTreeSet<_> = actors
            .iter()
            .map(|a| a.actor)
            .chain(stations.iter().map(|s| s.owner))
            .chain([actor])
            .collect();
        let leases: Vec<SimNativeLease> = if $leases { $db
            .sim_native_lease()
            .participant()
            .filter((run, actor))
            .collect() } else { vec![] };
        let captures = if $materialize {
            leases
                .iter()
                .filter(|l| l.has_observation)
                .map(|l| {
                    $db.sim_native_capture()
                        .lease_id()
                        .find(l.id)
                        .ok_or("native captured context missing")
                })
                .collect::<Result<Vec<_>, _>>()?
        } else {
            vec![]
        };
        Ok::<Rows, String>(Rows {
            paged_heads: if $cold {vec![]} else {$db.sim_native_trace_head().key().find(key(run,actor)).into_iter().collect()},
            trace_pages: if $cold {vec![]} else {$db.sim_native_trace_page().participant().filter((run,actor)).collect()},
            evidence_bodies: if $cold {vec![]} else {
                let ids:BTreeSet<_>=$db.sim_native_trace_page().participant().filter((run,actor))
                    .flat_map(|p|p.entries.into_iter().map(|e|e.body)).collect();
                ids.into_iter().map(|id|$db.sim_native_evidence_body().id().find(id).ok_or("native evidence body missing"))
                    .collect::<Result<Vec<_>,_>>()?
            },
            trace_indexes: if $cold {vec![]} else {$db.sim_native_trace_index().key().find(key(run,actor)).into_iter().collect()},
            catalogs: if $cold { vec![] } else {
                $db.sim_native_controller().key().find(key(run, actor))
                    .and_then(|c| c.last_lifecycle.strip_prefix("sao-controller-catalog-v1:").map(str::to_owned))
                    .and_then(|id| $db.sim_native_controller_catalog().key().find(id)).into_iter().collect()
            },
            controllers: $db.sim_native_controller().key().find(key(run, actor)).into_iter().collect(),
            bootstraps: if $cold {vec![]} else {$db.sim_controller_bootstrap().key().find(key(run, actor)).into_iter().collect()},
            head: if $materialize { render_head!($db, run)? } else { $db
                .sim_native_head()
                .run()
                .find(run.to_owned())
                .ok_or("native run head missing")? },
            definitions: read_definitions!($db, run),
            actors,
            minds: vec![$db
                .sim_native_mind()
                .key()
                .find(key(run, actor))
                .ok_or("native mind missing")?],
            mind_histories: if $cold {vec![]} else {$db.sim_native_mind_history().key().find(key(run, actor)).into_iter().collect()},
            participants: $db
                .sim_native_participant()
                .key()
                .find(key(run, actor))
                .into_iter()
                .collect(),
            experiences: if $cold {vec![]} else {$db.sim_native_experience().participant().filter((run, actor)).collect()},
            lease_evidence: if $cold {vec![]} else {leases.iter().filter(|l| l.experiences == LEASE_EVIDENCE)
                .filter_map(|l| $db.sim_native_lease_evidence().lease_id().find(l.id)).collect()},
            leases,
            captures,
            receipts: if $cold { vec![] } else { $db
                .sim_participant_receipt()
                .participant()
                .filter((run, actor))
                .collect() },
            aux: aux_ids
                .into_iter()
                .filter_map(|id| {
                    if $materialize {
                        if let Some(row) = $db.sim_render_actor_support().key().find(key(run, id)) {
                            return Some(row.into_aux());
                        }
                    }
                    $db.sim_native_actor_aux().key().find(key(run, id))
                })
                .collect(),
            sites: vec![],
            stations,
            archives: vec![],
        })
    }};
}
fn read_participant(ctx: &ReducerContext, run: &str, actor: u32, local_context: bool) -> Result<Rows, String> {
    let mut rows = read_participant_rows!(ctx.db, run, actor, false, true, true, local_context)?;
    if !local_context {
        rows.definitions.initial = action_admission_definition(ctx, run, rows.definitions.initial)?;
    }
    Ok(rows)
}

const ADMISSION_INITIAL: &str = "admission_initial_v1";
const ADMISSION_SOURCE: &str = "admission_initial_source_v1";

fn action_admission_definition(ctx: &ReducerContext, run: &str,
    complete: Deferred<simulation::Scenario>,
) -> Result<Deferred<simulation::Scenario>, String> {
    let source = ctx.db.sim_native_definition_version().key().find(key(run, "initial"));
    let derived_from = ctx.db.sim_native_definition_version().key().find(key(run, ADMISSION_SOURCE));
    let version = ctx.db.sim_native_definition_version().key().find(key(run, ADMISSION_INITIAL));
    let Some((source, derived_from, version)) = source.zip(derived_from).zip(version).map(|((a,b),c)|(a,b,c)) else {
        return Ok(complete); // Existing worlds remain usable before explicit preparation.
    };
    if source.digest != derived_from.digest { return Ok(complete); }
    let rows = ctx.db.sim_native_definition().key();
    let run = run.to_owned();
    #[cfg(feature = "clock-profile")]
    log::info!("definition-admission-projection");
    super::definition_cache::admission_deferred(version.digest, move || {
        let row = rows.find(key(&run, ADMISSION_INITIAL)).ok_or("admission definition missing")?;
        if row.run != run || row.kind != ADMISSION_INITIAL { return Err("admission definition scope mismatch".into()); }
        Ok(row.body)
    })
}

pub(super) fn participant_view(
    ctx: &ViewContext,
    run: &str,
    actor: u32,
) -> Result<(World, bool), String> {
    let rows: Rows = read_participant_rows!(ctx.db, run, actor, true, true)?;
    let (world, _) = assemble_with(rows, Some(actor), true, Some(view_cold_reader(ctx)))?;
    let can_participate = ctx
        .db
        .sim_native_actor()
        .key()
        .find(key(run, 3))
        .is_some_and(|a| a.human);
    Ok((world, can_participate))
}
pub(super) fn inspector_view(ctx: &ViewContext, run: &str, actor: u32) -> Result<World, String> {
    // Same local physical/knowledge dependencies as personal presentation, with
    // no captured reads, command receipts or participant-status construction.
    let rows: Rows = read_participant_rows!(ctx.db, run, actor, true, true, false)?;
    assemble_with(rows, Some(actor), false, Some(view_cold_reader(ctx))).map(|(world, _)| world)
}
pub(super) fn render_event_end(ctx: &ViewContext, run: &str) -> Option<u64> {
    render_head!(ctx.db, run).ok().map(|h| h.next_event)
}
pub(super) fn render_memories(ctx: &ViewContext, run: &str, actor: u32) -> Option<Vec<simulation::Percept>> {
    let key = key(run, actor);
    if let Some(row) = ctx.db.sim_native_mind_history().key().find(&key) {
        return parse(&row.memories).ok();
    }
    ctx.db.sim_native_mind().key().find(&key).and_then(|row| parse(&row.memories).ok())
}

pub(super) fn render_timing(ctx: &ViewContext, run: &str) -> Option<SimNativeHead> {
    render_head!(ctx.db, run).ok()
}

pub(super) fn render_initial(ctx: &ViewContext, run: &str) -> Result<Deferred<simulation::Scenario>,String> {
    let version=ctx.db.sim_native_definition_version().key().find(key(run,"initial"));
    super::definition_cache::initial_versioned(version.as_ref().map(|r|r.digest.as_str()),|| {
        ctx.db.sim_native_definition().key().find(key(run,"initial")).map(|r|r.body).ok_or("native initial missing".into())
    })
}

macro_rules! upsert {
    ($ctx:expr,$table:ident,$index:ident,$row:expr) => {{
        let row = $row;
        match $ctx.db.$table().$index().find(&row.$index) {
            Some(old) if old == row => (),
            Some(_) => {
                $ctx.db.$table().$index().update(row);
            }
            None => {
                $ctx.db.$table().insert(row);
            }
        }
    }};
}
/// Derived representation only; does not change World, audit, grants or clocks.
/// Provisioning/full saves maintain it atomically with the source definition.
/// The existing explicit migration reducer prepares already separated worlds.
pub(super) fn prepare_action_admission(ctx: &ReducerContext, w: &World) {
    let source = match ctx.db.sim_native_definition_version().key().find(key(&w.run, "initial")) {
        Some(version) => version,
        None => {
            let row = ctx.db.sim_native_definition().key().find(key(&w.run, "initial")).expect("native initial exists");
            let version = SimNativeDefinitionVersion {
                key: key(&w.run, "initial"), digest: format!("{:x}", Sha256::digest(row.body.as_bytes())),
            };
            upsert!(ctx, sim_native_definition_version, key, version.clone());
            version
        }
    };
    if ctx.db.sim_native_definition_version().key().find(key(&w.run, ADMISSION_SOURCE))
        .is_some_and(|r| r.digest == source.digest)
        && ctx.db.sim_native_definition_version().key().find(key(&w.run, ADMISSION_INITIAL)).is_some()
        && ctx.db.sim_native_definition().key().find(key(&w.run, ADMISSION_INITIAL)).is_some() { return; }
    let body = json(&simulation::participant_transaction::action_admission_initial(&w.initial));
    let digest = format!("{:x}", Sha256::digest(body.as_bytes()));
    upsert!(ctx, sim_native_definition, key, SimNativeDefinition {
        key: key(&w.run, ADMISSION_INITIAL), run: w.run.clone(), kind: ADMISSION_INITIAL.into(), body,
    });
    upsert!(ctx, sim_native_definition_version, key, SimNativeDefinitionVersion { key: key(&w.run, ADMISSION_INITIAL), digest });
    upsert!(ctx, sim_native_definition_version, key, SimNativeDefinitionVersion { key: key(&w.run, ADMISSION_SOURCE), digest: source.digest });
}
pub(super) fn command(
    ctx: &ReducerContext,
    run: &str,
    actor: u32,
    request: simulation::participant::Request,
) -> Result<(), String> {
    let targets = simulation::participant_transaction::command_targets(&request.command);
    let local_context = simulation::participant_transaction::command_reads_local_context(&request.command);
    let include_old_tree = matches!(&request.command, simulation::participant::Command::PatchSubtree {..});
    transact(ctx, run, actor, targets, include_old_tree, local_context, |transaction| transaction.execute(request))
}
pub(super) fn participant_mode(ctx: &ReducerContext, run: &str) -> Result<bool, String> {
    Ok(ctx
        .db
        .sim_native_head()
        .run()
        .find(run.to_owned())
        .ok_or("native head missing")?
        .participant_mode)
}
pub(super) fn change_control(ctx: &ReducerContext, run: &str, actor: u32) -> Result<(), String> {
    transact(ctx, run, actor, BTreeSet::new(), false, false, |transaction| transaction.change_control())
}
pub(super) fn intent(
    ctx: &ReducerContext,
    run: &str,
    actor: u32,
    decision: simulation::Decision,
) -> Result<(), String> {
    let targets = simulation::participant_transaction::decision_targets(&decision);
    let client_controlled = ctx.db.sim_native_controller().key().find(key(run, actor)).is_some();
    let local_context = simulation::participant_transaction::intent_reads_local_context(client_controlled, &decision);
    transact(ctx, run, actor, targets, false, local_context, |transaction| {
        transaction.execute_intent(decision)
    })
}
fn transact(
    ctx: &ReducerContext,
    run: &str,
    actor: u32,
    mut targets: BTreeSet<u32>,
    include_old_tree: bool,
    local_context: bool,
    execute: impl FnOnce(
        simulation::participant_transaction::ParticipantTransaction,
    ) -> Result<simulation::participant_transaction::ParticipantCommit, String>,
) -> Result<(), String> {
    let mut rows = super::measured("command.read", || read_participant(ctx, run, actor, local_context))?;
    if include_old_tree {
        if let Some(mind)=rows.minds.iter().find(|m|m.actor==actor) {
            if let Some(execution)=parse::<Option<simulation::Execution>>(&mind.execution)? {
                if let Some(tree)=execution.policy {targets.extend(simulation::participant_transaction::tree_targets(&tree));}
            }
        }
    }
    // A finite action/policy names a bounded set of targets. Point-read their
    // body, arena and law-visible numerical facts; never hydrate remote minds,
    // leases or experience history, and never scan every actor for this check.
    let mut target_facts = Vec::new();
    for target in targets.into_iter().filter(|target| *target != actor) {
        let target_key=key(run,target);
        let Some(body)=ctx.db.sim_native_actor().key().find(&target_key) else {continue;};
        if !rows.actors.iter().any(|p|p.actor==target) {rows.actors.push(body);}
        if !rows.aux.iter().any(|p|p.actor==target) {
            rows.aux.push(ctx.db.sim_native_actor_aux().key().find(&target_key).ok_or("target support missing")?);
        }
        target_facts.push(ctx.db.sim_native_mind().key().find(&target_key).ok_or("target facts missing")?);
    }
    #[cfg(feature = "clock-profile")]
    spacetimedb::log::info!("command-scope local={} actors={} auxiliary={} stations={} target_facts={}",
        local_context, rows.actors.len(), rows.aux.len(), rows.stations.len(), target_facts.len());
    let mut head = rows.head.clone();
    if !head.participant_mode {
        return Err("participant-v1 requires a participant run".into());
    }
    if head.version != simulation::VERSION {
        return Err("old rules are read-only".into());
    }
    let ordinal = rows
        .actors
        .iter()
        .find(|a| a.actor == actor)
        .ok_or("unknown actor")?
        .ordinal;
    let mut aux = rows.aux.iter().find(|a| a.actor == actor).cloned();
    let (mut world, ids) = super::measured("command.assemble", || assemble_with(rows, Some(actor), false, Some(cold_reader(ctx))))?;
    for facts in target_facts {
        if let Some(peer)=world.players.iter_mut().find(|p|p.id==facts.actor) {
            apply_visibility_facts(peer, &facts);
        }
    }
    let previous = world
        .participants
        .get(&actor)
        .ok_or("character not provisioned")?
        .clone();
    let previous_player = world
        .players
        .iter()
        .find(|p| p.id == actor)
        .expect("validated actor")
        .clone();
    let laws = world.laws.clone();
    let commit =
        super::measured("command.execute", || execute(simulation::participant_transaction::ParticipantTransaction::new(world, actor)?))?;
    #[cfg(feature = "clock-profile")]
    let save_timer = spacetimedb::log_stopwatch::LogStopwatch::new("command.save");
    head.next_event = commit.next_event;
    save_clock_hint(ctx, run, commit.clock_hint);
    upsert!(ctx, sim_native_head, run, head.clone());
    if !previous_player.same_snapshot(&commit.player) {
        upsert!(
            ctx,
            sim_native_actor,
            key,
            SimNativeActor::from_player(run, ordinal as usize, &commit.player)
        );
        save_mind(ctx, run, &commit.player, Some(&previous_player));
    }
    if let Some(row) = &mut aux {
        row.dirty = commit.dirty;
        upsert!(ctx, sim_native_actor_aux, key, row.clone());
    } else if commit.dirty.is_some() {
        return Err("native actor scheduling state missing".into());
    }
    let lease_ids = if previous.same_snapshot(&commit.participant) {
        ids[&actor].clone()
    } else {
        let mut catalogs = catalog::Writes::default();
        let mut traces = trace::Writes::default();
        save_participant_state(ctx, run, actor, &commit.participant, Some(&previous), &mut catalogs, &mut traces, false);
        // A newly retained lease may still hold a lazy payload that this action
        // evicts from the current trace. Materialize the lease before releasing
        // the final current-trace body reference.
        let leases=save_leases(ctx, run, actor, &commit.participant, Some(&previous), &ids[&actor]);
        catalogs.finish(ctx, run);
        traces.finish(ctx, run);
        leases
    };
    *laws.faults.lock() = commit.law_faults;
    upsert!(
        ctx,
        sim_native_definition,
        key,
        SimNativeDefinition {
            key: key(run, "laws"),
            run: run.into(),
            kind: "laws".into(),
            body: json(&laws)
        }
    );
    #[cfg(feature = "clock-profile")]
    drop(save_timer);
    super::measured("command.delivery", || super::participant_delivery::publish_actor(
        ctx,
        run,
        head.tick,
        head.time_ms,
        head.stopped,
        &commit.player,
        &commit.participant,
        &lease_ids,
        Some(&previous),
        head.time_ms,
    ));
    super::measured("command.audit", || super::append_audit(ctx, run, commit.events));
    Ok(())
}
fn save_leases(ctx: &ReducerContext, run: &str, actor: u32, state: &ParticipantState,
    previous: Option<&ParticipantState>, previous_ids: &[u64]) -> Vec<u64> {
    let old: Vec<_> = ctx
        .db
        .sim_native_lease()
        .participant()
        .filter((run, actor))
        .collect();
    let mut retained = BTreeSet::new();
    let mut ids = vec![];
    for (ordinal, l) in state.evidence_leases.iter().enumerate() {
        // Retained transaction snapshots prove exact reuse without reading the
        // immutable evidence body again on every clock event for this actor.
        let reused = previous.into_iter().flat_map(|p| p.evidence_leases.iter().zip(previous_ids))
            .find(|(p, id)| !retained.contains(*id)
                && p.request_id == l.request_id && p.observed_cursor == l.observed_cursor
                && p.expires_ms == l.expires_ms && p.observation.same_snapshot(&l.observation)
                && p.experiences.same_snapshot(&l.experiences))
            .and_then(|(_, id)| old.iter().find(|r| r.id == *id && r.experiences == LEASE_EVIDENCE));
        if let Some(row) = reused {
            if row.ordinal != ordinal as u32 {
                let mut row = row.clone(); row.ordinal = ordinal as u32;
                ctx.db.sim_native_lease().id().update(row);
            }
            retained.insert(row.id); ids.push(row.id); continue;
        }
        let experiences = json(&l.experiences);
        let existing = old.iter().find(|r| {
            !retained.contains(&r.id)
                && r.request_id == l.request_id
                && r.observed_cursor == l.observed_cursor
                && r.expires_ms == l.expires_ms
                && r.has_observation == l.observation.is_capture()
                && if r.experiences == LEASE_EVIDENCE {
                    ctx.db.sim_native_lease_evidence().lease_id().find(r.id)
                        .is_some_and(|e| e.run == run && e.actor == actor && e.experiences == experiences)
                } else { r.experiences == experiences }
                && if let Some(id) = l.observation.reference() {
                    r.id == id
                } else if r.has_observation {
                    ctx.db
                        .sim_native_capture()
                        .lease_id()
                        .find(r.id)
                        .is_some_and(|c| {
                            c.run == run && c.actor == actor && c.observation == l.observation.get()
                        })
                } else {
                    true
                }
        });
        let id = if let Some(row) = existing {
            if row.ordinal != ordinal as u32 || row.experiences != LEASE_EVIDENCE {
                let mut row = row.clone();
                row.ordinal = ordinal as u32;
                row.experiences = LEASE_EVIDENCE.into();
                ctx.db.sim_native_lease().id().update(row);
            }
            row.id
        } else {
            assert!(
                l.observation.reference().is_none(),
                "unmatched deferred observation must not be reinterpreted"
            );
            let id = ctx
                .db
                .sim_native_lease()
                .insert(SimNativeLease {
                    id: 0,
                    run: run.into(),
                    actor,
                    ordinal: ordinal as u32,
                    request_id: l.request_id.clone(),
                    observed_cursor: l.observed_cursor,
                    expires_ms: l.expires_ms,
                    has_observation: l.observation.is_capture(),
                    experiences: LEASE_EVIDENCE.into(),
                })
                .id;
            if l.observation.is_capture() {
                ctx.db.sim_native_capture().insert(SimNativeCapture {
                    lease_id: id,
                    run: run.into(),
                    actor,
                    observation: l.observation.get().into(),
                });
            }
            id
        };
        upsert!(ctx, sim_native_lease_evidence, lease_id, SimNativeLeaseEvidence {
            lease_id: id, run: run.into(), actor, experiences,
        });
        retained.insert(id);
        ids.push(id);
    }
    for row in old {
        if !retained.contains(&row.id) {
            ctx.db.sim_native_lease().id().delete(row.id);
            ctx.db.sim_native_lease_evidence().lease_id().delete(row.id);
            if row.has_observation {
                ctx.db.sim_native_capture().lease_id().delete(row.id);
            }
        }
    }
    ids
}
fn save_participants(
    ctx: &ReducerContext,
    w: &World,
    previous: &BTreeMap<u32, ParticipantState>,
    previous_ids: &LeaseIds,
) -> LeaseIds {
    let mut ids = LeaseIds::new();
    let mut catalogs = catalog::Writes::default();
    let mut traces = trace::Writes::default();
    let mut saved = 0usize;
    for (&actor, state) in &w.participants {
        if previous.get(&actor).is_some_and(|p| p.same_snapshot(state)) {
            ids.insert(
                actor,
                previous_ids
                    .get(&actor)
                    .cloned()
                    .expect("loaded participant leases"),
            );
            continue;
        }
        save_participant_state(ctx, &w.run, actor, state, previous.get(&actor), &mut catalogs, &mut traces, saved % 17 == 0);
        saved += 1;
        ids.insert(actor, save_leases(ctx, &w.run, actor, state, previous.get(&actor),
            previous_ids.get(&actor).map(Vec::as_slice).unwrap_or(&[])));
    }
    #[cfg(feature = "clock-profile")]
    log::info!("participant-save-samples eligible={} sampled={}",saved,saved.div_ceil(17));
    catalogs.finish(ctx, &w.run);
    traces.finish(ctx, &w.run);
    ids
}

fn save_participant_state(ctx: &ReducerContext, run: &str, actor: u32,
    state: &ParticipantState, previous: Option<&ParticipantState>, catalogs: &mut catalog::Writes, traces: &mut trace::Writes, sampled: bool) {
    let mut profile = super::evidence_profile::SaveScope::new(sampled, "participant.save.controller");
    if let Some(controller) = &state.client_controller {
        let old = ctx.db.sim_native_controller().key().find(key(run, actor));
        let retained = retained_controller_catalog(run, actor, controller,
            previous.and_then(|p|p.client_controller.as_ref()), old.as_ref());
        let last_lifecycle = retained.unwrap_or_else(|| catalogs.replace(run,
            old.as_ref().map(|r|r.last_lifecycle.as_str()), json(&controller.last_lifecycle)));
        let row = SimNativeController::with_catalog(run, actor, controller, last_lifecycle);
        match old {
            Some(old) if old == row => (),
            Some(_) => { ctx.db.sim_native_controller().key().update(row); }
            None => { ctx.db.sim_native_controller().insert(row); }
        }
        if previous.and_then(|p|p.client_controller.as_ref()).is_none_or(|p| !p.bootstrap.same_snapshot(&controller.bootstrap)) {
            upsert!(ctx, sim_controller_bootstrap, key, SimControllerBootstrap {
                key: key(run, actor), run: run.into(), actor, body: json(&controller.bootstrap),
            });
        }
    }
    profile.phase(sampled, "participant.save.header");
    let old = ctx.db.sim_native_participant().key().find(key(run, actor));
    // Activity/controller changes do not necessarily change personal evidence.
    // Reuse only the retained transaction snapshot and the current row format;
    // legacy rows still take the migration/reconciliation path below.
    let heads = retained_experience_heads(state, previous, old.as_ref());
    let unchanged_experiences = heads.is_some();
    let row = SimNativeParticipant::from_state_with_heads(run, actor, state, Some(heads.unwrap_or_else(||trace::MARKER.into())));
    if !unchanged_experiences {
        // End the header timer before the trace writer's separately measured phases.
        profile.phase(false, "participant.save.header");
        traces.save(ctx,run,actor,state,previous,old.as_ref(),sampled);
    }
    profile.phase(sampled, "participant.save.commit");
    match old {
        Some(old) if old == row => (),
        Some(_) => { ctx.db.sim_native_participant().key().update(row); }
        None => { ctx.db.sim_native_participant().insert(row); }
    }
}

/// The previous controller is the strongly owned snapshot loaded from this
/// actor's row in the current transaction. Reuse only a current-format reference;
/// legacy inline values still migrate through ordinary validated serialization.
fn retained_controller_catalog(run: &str, actor: u32,
    current: &simulation::controller::Authority, previous: Option<&simulation::controller::Authority>,
    row: Option<&SimNativeController>) -> Option<String> {
    let (current, previous) = (current.last_lifecycle.as_ref()?, previous?.last_lifecycle.as_ref()?);
    if !current.same_snapshot(previous) { return None; }
    let row = row?;
    (row.run == run && row.actor == actor && row.key == key(run, actor)
        && catalog::valid_reference(&row.last_lifecycle)).then(||row.last_lifecycle.clone())
}

fn retained_experience_heads(state: &ParticipantState, previous: Option<&ParticipantState>,
    row: Option<&SimNativeParticipant>) -> Option<String> {
    if !previous.is_some_and(|p| p.experiences.same_snapshot(&state.experiences)) { return None; }
    let row = row?;
    if row.experiences != trace::MARKER && row.experiences != TRACE_INDEX { parse::<ExperienceHeads>(&row.experiences).ok()?; }
    Some(row.experiences.clone())
}

fn save_mind(ctx: &ReducerContext, run: &str, player: &Player, previous: Option<&Player>) {
    let row = SimNativeMind::from_player(run, player);
    let old = ctx.db.sim_native_mind().key().find(&row.key);
    let separated = old.as_ref().is_some_and(|m| m.memories == MIND_HISTORY);
    let unchanged = previous.is_some_and(|p| p.beliefs == player.beliefs
        && p.relationships == player.relationships && p.memories == player.memories
        && p.site_observations == player.site_observations && p.knowledge == player.knowledge);
    if !separated || !unchanged {
        upsert!(ctx, sim_native_mind_history, key, SimNativeMindHistory::from_player(run, player));
    }
    match old {
        Some(old) if old == row => (),
        Some(_) => { ctx.db.sim_native_mind().key().update(row); }
        None => { ctx.db.sim_native_mind().insert(row); }
    }
}
#[cfg(test)]
fn definitions(w: &World) -> DefinitionSet {
    DefinitionSet {
        initial: super::definition_cache::initial(&json(&w.initial)).unwrap(),
        scripts: super::definition_cache::scripts(&json(&w.scripts)).unwrap(),
        laws: parse(&json(&w.laws)).unwrap(),
        balance: parse(&json(&w.infrastructure.balance)).unwrap(),
    }
}
fn save_clock_hint(ctx: &ReducerContext, run: &str, hint: simulation::clock::ActorHint) {
    upsert!(ctx, sim_native_clock_actor, key, SimNativeClockActor {
        key: key(run, hint.actor), run: run.into(), actor: hint.actor,
        due_ms: hint.due_ms, active: hint.active,
    });
}
fn save_clock_index(ctx: &ReducerContext, w: &World, previous_players: &BTreeMap<u32, Player>,
    previous_participants: &BTreeMap<u32, ParticipantState>) {
    let actors: Vec<_> = w.players.iter().map(|p| p.id).collect();
    let state = SimNativeClockState { run: w.run.clone(), version: CLOCK_INDEX_VERSION,
        script_revision: w.scripts.revision, actors };
    let prior = ctx.db.sim_native_clock_state().run().find(&w.run);
    let rebuild = prior.as_ref() != Some(&state);
    let due: BTreeSet<_> = ctx.db.sim_native_clock_actor().active_actors().filter((w.run.as_str(), true))
        .chain(ctx.db.sim_native_clock_actor().due().filter((w.run.as_str(), ..=w.timing.time_ms)))
        .map(|r| r.actor).collect();
    for (i, p) in w.players.iter().enumerate() {
        if rebuild || due.contains(&p.id) || w.timing.dirty.get(&p.id) == Some(&true)
            || previous_players.get(&p.id).is_none_or(|old| !p.same_snapshot(old))
            || w.participants.get(&p.id).is_some_and(|s|
                previous_participants.get(&p.id).is_none_or(|old| !s.same_snapshot(old))) {
            save_clock_hint(ctx, &w.run, w.actor_clock_hint(i));
        }
    }
    if let Some(prior) = prior {
        for actor in prior.actors.iter().filter(|id| !state.actors.contains(id)) {
            ctx.db.sim_native_clock_actor().key().delete(key(&w.run, actor));
        }
    }
    upsert!(ctx, sim_native_clock_state, run, state);
}
fn aux_ids(w: &World) -> BTreeSet<u32> {
    w.players
        .iter()
        .map(|p| p.id)
        .chain(w.actor_arenas.keys().copied())
        .chain(w.lifecycle.keys().copied())
        .chain(w.reproduction_offers.keys().copied())
        .chain(w.infrastructure.bodies.keys().copied())
        .chain(w.infrastructure.actor_materials.keys().copied())
        .chain(w.timing.actor_needs_remainder_ms.keys().copied())
        .chain(w.timing.actor_hazard_remainder_ms.keys().copied())
        .chain(w.timing.action_ready_ms.keys().copied())
        .chain(w.timing.dialogue_ready_ms.keys().copied())
        .chain(w.timing.dirty.keys().copied())
        .collect()
}
pub(super) fn save(
    ctx: &ReducerContext,
    w: &World,
    previous: &BTreeMap<u32, ParticipantState>,
    previous_ids: &LeaseIds,
    previous_players: &BTreeMap<u32, Player>,
    previous_definitions: Option<&super::storage::PreviousDefinitions>,
) -> LeaseIds {
    #[cfg(feature = "clock-profile")]
    let phase = spacetimedb::log_stopwatch::LogStopwatch::new("native.rows.definitions");
    let head = SimNativeHead::from_world(w);
    upsert!(ctx, sim_render_clock, run, SimRenderClock { run:w.run.clone(), head:json(&head) });
    upsert!(ctx, sim_native_head, run, head);
    // The loaded immutable snapshots belong to this transaction. Avoid
    // serializing and fetching unchanged scenario/script rows on every pulse.
    for (kind, body) in [
        ("initial", (!previous_definitions.is_some_and(|(p, _)| p.same_snapshot(&w.initial))
            || ctx.db.sim_native_definition_version().key().find(key(&w.run,"initial")).is_none()).then(|| json(&w.initial))),
        ("scripts", (!previous_definitions.is_some_and(|(_, p)| p.same_snapshot(&w.scripts))
            || ctx.db.sim_native_definition_version().key().find(key(&w.run,"scripts")).is_none()).then(|| json(&w.scripts))),
        ("laws", Some(json(&w.laws))),
        ("balance", Some(json(&w.infrastructure.balance))),
    ] {
        if let Some(body) = body {
            if kind == "initial" || kind == "scripts" {
                upsert!(ctx, sim_native_definition_version, key, SimNativeDefinitionVersion {
                    key:key(&w.run,kind), digest:format!("{:x}",Sha256::digest(body.as_bytes())),
                });
            }
            upsert!(ctx, sim_native_definition, key, SimNativeDefinition {
                key: key(&w.run, kind), run: w.run.clone(), kind: kind.into(), body,
            });
        }
    }
    prepare_action_admission(ctx, w);
    // Global clock/population operations can add/remove entities. Their full
    // run-indexed reconciliation is not used by participant command commits.
    macro_rules! reconcile {
        ($table:ident,$rows:expr) => {{
            let rows: Vec<_> = $rows;
            let mut previous: BTreeMap<_, _> = ctx.db.$table().run().filter(w.run.as_str())
                .map(|row| (row.key.clone(), row)).collect();
            for row in rows {
                match previous.remove(&row.key) {
                    Some(old) if old == row => (),
                    Some(_) => { ctx.db.$table().key().update(row); },
                    None => { ctx.db.$table().insert(row); },
                }
            }
            for key in previous.into_keys() {
                ctx.db.$table().key().delete(key);
            }
        }};
    }
    #[cfg(feature = "clock-profile")]
    drop(phase);
    #[cfg(feature = "clock-profile")]
    let phase = spacetimedb::log_stopwatch::LogStopwatch::new("native.rows.actors");
    let actors: BTreeSet<_> = w.players.iter().map(|p| p.id).collect();
    for actor in previous_players.keys().filter(|id| !actors.contains(id)) {
        ctx.db.sim_native_actor().key().delete(key(&w.run, actor));
        ctx.db.sim_native_mind().key().delete(key(&w.run, actor));
        ctx.db.sim_native_mind_history().key().delete(key(&w.run, actor));
    }
    for (ordinal, player) in w.players.iter().enumerate() {
        // Body rows remain cheap to compare and preserve explicit actor order.
        // A retained snapshot lets unchanged private state avoid serialization
        // and table reads altogether, including during global clock commits.
        upsert!(
            ctx,
            sim_native_actor,
            key,
            SimNativeActor::from_player(&w.run, ordinal, player)
        );
        if !previous_players
            .get(&player.id)
            .is_some_and(|old| old.same_snapshot(player))
        {
            save_mind(ctx, &w.run, player, previous_players.get(&player.id));
        }
    }
    #[cfg(feature = "clock-profile")]
    drop(phase);
    #[cfg(feature = "clock-profile")]
    let phase = spacetimedb::log_stopwatch::LogStopwatch::new("native.rows.auxiliary");
    reconcile!(
        sim_native_actor_aux,
        aux_ids(w)
            .into_iter()
            .map(|a| SimNativeActorAux::from_world(w, a))
            .collect()
    );
    reconcile!(sim_render_actor_support, aux_ids(w).into_iter()
        .map(|a| SimRenderActorSupport::from_aux(SimNativeActorAux::from_world(w, a))).collect());
    #[cfg(feature = "clock-profile")]
    drop(phase);
    #[cfg(feature = "clock-profile")]
    let phase = spacetimedb::log_stopwatch::LogStopwatch::new("native.rows.sites");
    reconcile!(
        sim_native_site,
        w.sites
            .iter()
            .enumerate()
            .map(|(n, s)| SimNativeSite {
                key: key(&w.run, s.position),
                run: w.run.clone(),
                ordinal: n as u32,
                position: s.position,
                food: s.food,
                hazard: s.hazard,
                shelter: s.shelter
            })
            .collect()
    );
    reconcile!(
        sim_native_station,
        w.infrastructure
            .stations
            .iter()
            .enumerate()
            .map(|(n, s)| SimNativeStation::from_station(&w.run, n, s))
            .collect()
    );
    reconcile!(
        sim_native_archive,
        w.archives
            .iter()
            .enumerate()
            .map(|(n, a)| SimNativeArchive {
                key: key(&w.run, a.id),
                run: w.run.clone(),
                archive: a.id,
                ordinal: n as u32,
                position: a.position,
                label: a.label.clone(),
                capacity: a.capacity as u64,
                destroyed: a.destroyed,
                revision: a.revision,
                records: json(&a.records)
            })
            .collect()
    );
    #[cfg(feature = "clock-profile")]
    drop(phase);
    let ids = super::measured("native.rows.participants", || save_participants(ctx, w, previous, previous_ids));
    super::measured("native.rows.clock_index", || save_clock_index(ctx, w, previous_players, previous));
    ids
}

/// Delete only an unpublished run held by world_build's authenticated private
/// reservation. All body digests are run-scoped, so no other run holds these
/// rows. The caller keeps the reservation until every bounded pass completes.
pub(super) fn discard_unpublished_batch(ctx: &ReducerContext, run: &str, limit: usize) -> bool {
    assert!(!super::storage::exists(ctx, run));
    let mut remaining = limit;
    // Delivery headers have actor keys rather than run indexes. Remove them
    // using the native actor index before removing their addressing rows.
    let actors:Vec<_> = ctx.db.sim_native_actor().run().filter(run).take(remaining).collect();
    for actor in &actors {
        super::participant_delivery::clear_actor(ctx, run, actor.actor);
        use super::controller_delivery::sim_controller_frame_state;
        ctx.db.sim_controller_frame_state().key().delete(&actor.key);
        ctx.db.sim_native_actor().key().delete(&actor.key);
    }
    remaining -= actors.len();
    if remaining == 0 { return false; }
    macro_rules! clear {
        ($table:ident, $index:ident, $filter:expr, $key:ident) => {{
            let rows:Vec<_> = ctx.db.$table().$index().filter($filter).take(remaining).collect();
            for row in &rows { ctx.db.$table().$key().delete(row.$key.clone()); }
            remaining -= rows.len();
            if remaining == 0 { return false; }
        }};
    }
    clear!(sim_native_mind,run,run,key);
    clear!(sim_native_mind_history,run,run,key);
    clear!(sim_native_actor_aux,run,run,key);
    clear!(sim_render_actor_support,run,run,key);
    clear!(sim_native_controller,run,run,key);
    clear!(sim_controller_bootstrap,run,run,key);
    clear!(sim_native_participant,run,run,key);
    clear!(sim_native_experience,participant,(run,),key);
    clear!(sim_native_trace_index,run,run,key);
    clear!(sim_native_trace_head,run,run,key);
    clear!(sim_native_trace_page,participant,(run,),key);
    clear!(sim_native_evidence_body,run,run,id);
    clear!(sim_native_evidence_retention,run,run,id);
    clear!(sim_native_controller_catalog,run,run,key);
    clear!(sim_native_lease,run,run,id);
    clear!(sim_native_lease_evidence,run,run,lease_id);
    clear!(sim_native_capture,run,run,lease_id);
    clear!(sim_native_clock_actor,due,(run,),key);
    clear!(sim_native_site,run,run,key);
    clear!(sim_native_station,run,run,key);
    clear!(sim_native_archive,run,run,key);
    clear!(sim_native_definition,run,run,key);
    // A constant number of run headers, beyond the row batch above.
    for kind in ["initial", "scripts", ADMISSION_INITIAL, ADMISSION_SOURCE] {
        ctx.db.sim_native_definition_version().key().delete(key(run,kind));
    }
    ctx.db.sim_native_clock_state().run().delete(run.to_owned());
    ctx.db.sim_render_clock().run().delete(run.to_owned());
    ctx.db.sim_native_head().run().delete(run.to_owned());
    true
}

#[cfg(test)]
#[path = "native_storage_tests.rs"]
mod tests;

mod action_clock;
pub(super) use action_clock::advance_actions;
fn clock_definitions(ctx: &ReducerContext, run: &str) -> Result<DefinitionSet,String> {
    Ok(read_definitions!(ctx.db, run))
}

mod catalog;
mod trace;
