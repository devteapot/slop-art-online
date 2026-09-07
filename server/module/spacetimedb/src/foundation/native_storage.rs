//! Canonical component rows. Full hydration is reserved for the global clock
//! kernel and explicit exports; participant transactions use indexed reads.
use super::participant_delivery::{sim_participant_receipt, sim_participant_receipt__view};
use simulation::{
    participant::{EvidenceLease, Experience, ParticipantState, Receipt},
    Controller, Player, World,
};
use spacetimedb::{ReducerContext, Table, ViewContext};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

pub(super) const FORMAT: &str = "sao-native-components-v1";
pub(super) type LeaseIds = BTreeMap<u32, Vec<u64>>;
fn key(run: &str, id: impl std::fmt::Display) -> String {
    format!("{run}:{id}")
}
fn json(value: &impl serde::Serialize) -> String {
    serde_json::to_string(value).expect("component serializes")
}
fn parse<T: serde::de::DeserializeOwned>(value: &str) -> Result<T, String> {
    serde_json::from_str(value).map_err(|e| format!("invalid native component: {e}"))
}

#[derive(Clone, PartialEq)]
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
    pub needs_remainder_ms: u64,
    pub hazard_remainder_ms: u64,
    pub next_job: u64,
    pub applied_disturbances: Vec<u64>,
    pub food_remainder: String,
    pub pending: String,
    pub request_ids: Vec<u64>,
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
    index(accessor = participant, btree(columns = [run, actor, cursor])))]
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
        Ok(Experience { cursor: self.cursor, source: self.source, tick: self.tick,
            location: self.location, kind: self.kind, parents: self.parents,
            data: parse(&self.data)? })
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
            knowledge: vec![],
            beliefs: vec![],
            relationships: BTreeMap::new(),
            memories: vec![],
            site_observations: vec![],
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
        Self {
            key: key(run, actor),
            run: run.into(),
            actor,
            control_epoch: s.control_epoch,
            learning_revision: s.learning_revision,
            cursor: s.cursor,
            experiences: json(&ExperienceRefs { native_experience_rows_v1: s.experiences.iter().map(|e| e.cursor).collect() }),
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
            let refs: ExperienceRefs = parse(&self.experiences)?;
            if refs.native_experience_rows_v1.len() != experiences.len() {
                return Err("native experience reference count mismatch".into());
            }
            refs.native_experience_rows_v1.into_iter()
                .map(|id| experiences.remove(&id).ok_or_else(|| "native experience missing or duplicated".into()))
                .collect::<Result<Vec<_>, String>>()?
        } else {
            // Read old component rows until this actor's next ordinary save.
            parse(&self.experiences)?
        };
        Ok(simulation::participant::ParticipantStateData {
            control_epoch: self.control_epoch,
            learning_revision: self.learning_revision,
            cursor: self.cursor,
            experiences,
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
            experiences: Arc::new(parse(&self.experiences)?),
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
struct Rows {
    head: SimNativeHead,
    definitions: Vec<SimNativeDefinition>,
    actors: Vec<SimNativeActor>,
    minds: Vec<SimNativeMind>,
    mind_histories: Vec<SimNativeMindHistory>,
    participants: Vec<SimNativeParticipant>,
    experiences: Vec<SimNativeExperience>,
    leases: Vec<SimNativeLease>,
    captures: Vec<SimNativeCapture>,
    receipts: Vec<super::participant_delivery::SimParticipantReceipt>,
    aux: Vec<SimNativeActorAux>,
    sites: Vec<SimNativeSite>,
    stations: Vec<SimNativeStation>,
    archives: Vec<SimNativeArchive>,
}
fn assemble(
    mut rows: Rows,
    scoped_actor: Option<u32>,
    materialize: bool,
) -> Result<(World, LeaseIds), String> {
    let h = rows.head;
    let definitions: BTreeMap<_, _> = rows
        .definitions
        .into_iter()
        .map(|d| (d.kind, d.body))
        .collect();
    let definition = |kind: &str| {
        definitions
            .get(kind)
            .ok_or_else(|| format!("native {kind} missing"))
    };
    let mut w = World {
        run: h.run,
        version: h.version,
        initial: parse(definition("initial")?)?,
        scripts: parse(definition("scripts")?)?,
        laws: parse(definition("laws")?)?,
        tick: h.tick,
        timing: simulation::timing::Timing {
            time_ms: h.time_ms,
            updates: h.updates,
            delta_ms: h.delta_ms,
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
            balance: parse(definition("balance")?)?,
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
            } else {
                a.player(minds.get(&a.actor).ok_or("native mind missing")?, mind_histories.get(&a.actor))?
            });
    }
    rows.leases.sort_by_key(|l| (l.actor, l.ordinal));
    let captures = rows.captures.into_iter().map(|r| (r.lease_id, r)).collect();
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
            .push(l.lease(&captures, materialize)?);
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
    for p in rows.participants {
        if p.run != w.run {
            return Err("native participant run mismatch".into());
        }
        lease_ids.entry(p.actor).or_default();
        w.participants.insert(
            p.actor,
            p.state(
                experiences.remove(&p.actor).unwrap_or_default(),
                leases.remove(&p.actor).unwrap_or_default(),
                receipts.remove(&p.actor).unwrap_or_default(),
            )?,
        );
    }
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
        .map(|a| {
            Ok(simulation::knowledge::Archive {
                id: a.archive,
                position: a.position,
                label: a.label,
                capacity: a.capacity as usize,
                destroyed: a.destroyed,
                revision: a.revision,
                records: parse(&a.records)?,
            })
        })
        .collect::<Result<_, String>>()?;
    Ok((w, lease_ids))
}

macro_rules! read_all {
    ($db:expr,$run:expr,$materialize:expr) => {{
        let run = $run;
        Rows {
            head: $db
                .sim_native_head()
                .run()
                .find(run.to_owned())
                .ok_or("native run head missing")?,
            definitions: $db.sim_native_definition().run().filter(run).collect(),
            actors: $db.sim_native_actor().run().filter(run).collect(),
            minds: $db.sim_native_mind().run().filter(run).collect(),
            mind_histories: $db.sim_native_mind_history().run().filter(run).collect(),
            participants: $db.sim_native_participant().run().filter(run).collect(),
            experiences: $db.sim_native_experience().participant().filter((run,)).collect(),
            leases: $db.sim_native_lease().run().filter(run).collect(),
            captures: if $materialize {
                $db.sim_native_capture().run().filter(run).collect()
            } else {
                vec![]
            },
            receipts: $db
                .sim_participant_receipt()
                .participant()
                .filter((run,))
                .collect(),
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
pub(super) fn load_export(ctx: &ReducerContext, run: &str) -> Result<World, String> {
    assemble(read_all!(ctx.db, run, true), None, true).map(|(w, _)| w)
}
pub(super) fn load_view(ctx: &ViewContext, run: &str) -> Result<World, String> {
    assemble(read_all!(ctx.db, run, true), None, true).map(|(w, _)| w)
}
pub(super) fn histories_separated(ctx: &ReducerContext, run: &str) -> bool {
    ctx.db.sim_native_mind().run().filter(run).all(|m| m.memories == MIND_HISTORY)
        && ctx.db.sim_native_participant().run().filter(run).all(|p| p.experiences.starts_with('{'))
}

macro_rules! read_participant_rows {
    ($db:expr,$run:expr,$actor:expr,$materialize:expr) => {{
        let run = $run;
        let actor = $actor;

        let own = $db
            .sim_native_actor()
            .key()
            .find(key(run, actor))
            .ok_or("unknown actor")?;
        let actors: Vec<_> = $db
            .sim_native_actor()
            .location()
            .filter((run, own.position))
            .collect();
        let stations: Vec<_> = $db
            .sim_native_station()
            .location()
            .filter((run, own.position))
            .collect();
        // An owned station may belong to an actor at a different location; arena
        // membership for that owner is a dependency even though their mind is not.
        let aux_ids: BTreeSet<_> = actors
            .iter()
            .map(|a| a.actor)
            .chain(stations.iter().map(|s| s.owner))
            .chain([actor])
            .collect();
        let leases: Vec<SimNativeLease> = $db
            .sim_native_lease()
            .participant()
            .filter((run, actor))
            .collect();
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
            head: $db
                .sim_native_head()
                .run()
                .find(run.to_owned())
                .ok_or("native run head missing")?,
            definitions: ["initial", "scripts", "laws", "balance"]
                .into_iter()
                .map(|kind| {
                    $db.sim_native_definition()
                        .key()
                        .find(key(run, kind))
                        .ok_or("native definition missing")
                })
                .collect::<Result<_, _>>()?,
            actors,
            minds: vec![$db
                .sim_native_mind()
                .key()
                .find(key(run, actor))
                .ok_or("native mind missing")?],
            mind_histories: $db.sim_native_mind_history().key().find(key(run, actor)).into_iter().collect(),
            participants: $db
                .sim_native_participant()
                .key()
                .find(key(run, actor))
                .into_iter()
                .collect(),
            experiences: $db.sim_native_experience().participant().filter((run, actor)).collect(),
            leases,
            captures,
            receipts: $db
                .sim_participant_receipt()
                .participant()
                .filter((run, actor))
                .collect(),
            aux: aux_ids
                .into_iter()
                .filter_map(|id| $db.sim_native_actor_aux().key().find(key(run, id)))
                .collect(),
            sites: vec![],
            stations,
            archives: vec![],
        })
    }};
}
fn read_participant(ctx: &ReducerContext, run: &str, actor: u32) -> Result<Rows, String> {
    read_participant_rows!(ctx.db, run, actor, false)
}
pub(super) fn participant_view(
    ctx: &ViewContext,
    run: &str,
    actor: u32,
) -> Result<(World, bool), String> {
    let rows: Rows = read_participant_rows!(ctx.db, run, actor, true)?;
    let (world, _) = assemble(rows, Some(actor), true)?;
    let can_participate = ctx
        .db
        .sim_native_actor()
        .key()
        .find(key(run, 3))
        .is_some_and(|a| a.human);
    Ok((world, can_participate))
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
pub(super) fn command(
    ctx: &ReducerContext,
    run: &str,
    actor: u32,
    request: simulation::participant::Request,
) -> Result<(), String> {
    transact(ctx, run, actor, |transaction| transaction.execute(request))
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
pub(super) fn intent(
    ctx: &ReducerContext,
    run: &str,
    actor: u32,
    decision: simulation::Decision,
) -> Result<(), String> {
    transact(ctx, run, actor, |transaction| {
        transaction.execute_intent(decision)
    })
}
fn transact(
    ctx: &ReducerContext,
    run: &str,
    actor: u32,
    execute: impl FnOnce(
        simulation::participant_transaction::ParticipantTransaction,
    ) -> Result<simulation::participant_transaction::ParticipantCommit, String>,
) -> Result<(), String> {
    let rows = read_participant(ctx, run, actor)?;
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
    let (world, ids) = assemble(rows, Some(actor), false)?;
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
        execute(simulation::participant_transaction::ParticipantTransaction::new(world, actor)?)?;
    head.next_event = commit.next_event;
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
        save_participant_state(ctx, run, actor, &commit.participant, Some(&previous));
        save_leases(ctx, run, actor, &commit.participant)
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
    super::participant_delivery::publish_actor(
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
    );
    super::append_audit(ctx, run, commit.events);
    Ok(())
}
fn save_leases(ctx: &ReducerContext, run: &str, actor: u32, state: &ParticipantState) -> Vec<u64> {
    let old: Vec<_> = ctx
        .db
        .sim_native_lease()
        .participant()
        .filter((run, actor))
        .collect();
    let mut retained = BTreeSet::new();
    let mut ids = vec![];
    for (ordinal, l) in state.evidence_leases.iter().enumerate() {
        let experiences = json(&l.experiences);
        let existing = old.iter().find(|r| {
            !retained.contains(&r.id)
                && r.request_id == l.request_id
                && r.observed_cursor == l.observed_cursor
                && r.expires_ms == l.expires_ms
                && r.has_observation == l.observation.is_capture()
                && r.experiences == experiences
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
            if row.ordinal != ordinal as u32 {
                let mut row = row.clone();
                row.ordinal = ordinal as u32;
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
                    experiences,
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
        retained.insert(id);
        ids.push(id);
    }
    for row in old {
        if !retained.contains(&row.id) {
            ctx.db.sim_native_lease().id().delete(row.id);
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
        save_participant_state(ctx, &w.run, actor, state, previous.get(&actor));
        ids.insert(actor, save_leases(ctx, &w.run, actor, state));
    }
    ids
}

fn save_participant_state(ctx: &ReducerContext, run: &str, actor: u32,
    state: &ParticipantState, previous: Option<&ParticipantState>) {
    let row = SimNativeParticipant::from_state(run, actor, state);
    let old = ctx.db.sim_native_participant().key().find(&row.key);
    let stored: BTreeSet<u64> = old.as_ref().filter(|r| r.experiences.starts_with('{'))
        .map(|r| parse::<ExperienceRefs>(&r.experiences).expect("validated experience references")
            .native_experience_rows_v1.into_iter().collect()).unwrap_or_default();
    let current: BTreeMap<_, _> = state.experiences.iter().map(|e| (e.cursor, e)).collect();
    assert_eq!(current.len(), state.experiences.len(), "unique personal cursors");
    let previous: BTreeMap<_, _> = previous.into_iter().flat_map(|p| p.experiences.iter())
        .map(|e| (e.cursor, e)).collect();
    for cursor in stored.iter().filter(|id| !current.contains_key(id)) {
        ctx.db.sim_native_experience().key().delete(key(run, format!("{actor}:{cursor}")));
    }
    for (&cursor, value) in &current {
        if stored.contains(&cursor) && previous.get(&cursor).is_some_and(|old| value.can_reuse_encoding(old)) {
            continue;
        }
        upsert!(ctx, sim_native_experience, key, SimNativeExperience::from_experience(run, actor, value));
    }
    match old {
        Some(old) if old == row => (),
        Some(_) => { ctx.db.sim_native_participant().key().update(row); }
        None => { ctx.db.sim_native_participant().insert(row); }
    }
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
fn definitions(w: &World) -> Vec<SimNativeDefinition> {
    [
        ("initial", json(&w.initial)),
        ("scripts", json(&w.scripts)),
        ("laws", json(&w.laws)),
        ("balance", json(&w.infrastructure.balance)),
    ]
    .into_iter()
    .map(|(kind, body)| SimNativeDefinition {
        key: key(&w.run, kind),
        run: w.run.clone(),
        kind: kind.into(),
        body,
    })
    .collect()
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
) -> LeaseIds {
    upsert!(ctx, sim_native_head, run, SimNativeHead::from_world(w));
    for d in definitions(w) {
        upsert!(ctx, sim_native_definition, key, d);
    }
    // Global clock/population operations can add/remove entities. Their full
    // run-indexed reconciliation is not used by participant command commits.
    macro_rules! reconcile {
        ($table:ident,$rows:expr) => {{
            let rows: Vec<_> = $rows;
            let keys: BTreeSet<_> = rows.iter().map(|r| r.key.clone()).collect();
            for old in ctx.db.$table().run().filter(w.run.as_str()) {
                if !keys.contains(&old.key) {
                    ctx.db.$table().key().delete(old.key);
                }
            }
            for row in rows {
                upsert!(ctx, $table, key, row);
            }
        }};
    }
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
    reconcile!(
        sim_native_actor_aux,
        aux_ids(w)
            .into_iter()
            .map(|a| SimNativeActorAux::from_world(w, a))
            .collect()
    );
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
    save_participants(ctx, w, previous, previous_ids)
}

#[cfg(test)]
#[path = "native_storage_tests.rs"]
mod tests;
