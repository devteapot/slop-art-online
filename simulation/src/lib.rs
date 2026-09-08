//! The authoritative M1 rules, invoked by SpacetimeDB reducers and unit tests.
//! No I/O, wall clock, model calls, or second approximation of world rules.
pub mod client_view;
pub mod ecology;
pub mod knowledge;
pub mod infrastructure;
pub mod initialization;
pub mod research;
pub mod laws;
pub mod law_research;
pub mod research_programs;
pub mod lifecycle;
mod lifecycle_view;
pub mod participant;
pub mod participant_transaction;
pub mod perturbations;
mod scripted_world;
pub mod scripting;
pub mod spatial;
mod visibility;
pub mod society;
pub mod starting_behaviors;
pub mod combat;
pub mod timing;
pub mod deferred;
pub mod clock;
pub mod controller;
use bonsai_bt::Behavior;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;

pub const VERSION: &str = "m7-1-scoped-laws.2";
pub const DECISION_FORMAT_VERSION: &str = "survivor-policy-v2";
pub const LEGACY_DECISION_FORMAT: &str = "survivor-sequence-v1";
pub mod policy;
pub use policy::{Condition, Node, PolicyState, Status};
pub const MAX_ACTIONS: usize = 8;
pub const MAX_REFLECTIONS: usize = 8;
pub const REQUEST_EXPIRY_TICKS: u64 = 30;
pub const PROMPT: &str = r#"You control ONE survivor. Your supplied understanding is subjective: reports may be false. Propose an intentional approach serving this individual's motive, needs, personality, emotions and relationships. Interpret relevant perceived experiences, including free-form speech and failures, and reconsider unsuccessful approaches. Use only perceived or known targets and locations. Choose your own speech; a speech claim never changes world facts. Give a short reported explanation, not private reasoning. Reflections must cite source IDs in the supplied memories and concern known locations. Rest and waiting need a purpose. Do not assume others know what you know. Avoid repeated speeches without action. The decision schema and skill contract supplied with this request describe this version of the simulation, not restrictions of the model provider."#;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Controller {
    Ai,
    Human,
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Skill {
    Move,
    Gather,
    Eat,
    Rest,
    Wait,
    Speak,
    Attack,
    Give,
    Deposit,
    Build,
    Observe,
    Teach,
    Record,
    Consult,
    RereadRecord,
    DestroyArchive,
    OfferReproduction,
    WithdrawReproduction,
    Reproduce,
    Fabricate,
    Care,
    Practice,
    Infrastructure,
    Script(String),
}
impl Skill {
    pub fn id(&self) -> &str {
        match self {
            Self::Move => "move",
            Self::Gather => "gather",
            Self::Eat => "eat",
            Self::Rest => "rest",
            Self::Wait => "wait",
            Self::Speak => "speak",
            Self::Attack => "attack",
            Self::Give => "give",
            Self::Deposit => "deposit",
            Self::Build => "build",
            Self::Observe => "observe",
            Self::Teach => "teach",
            Self::Record => "record",
            Self::Consult => "consult",
            Self::RereadRecord => "reread_record",
            Self::DestroyArchive => "destroy_archive",
            Self::OfferReproduction => "offer_reproduction",
            Self::WithdrawReproduction => "withdraw_reproduction",
            Self::Reproduce => "reproduce",
            Self::Fabricate => "fabricate",
            Self::Care => "care",
            Self::Practice => "practice",
            Self::Infrastructure => "infrastructure",
            Self::Script(id) => id,
        }
    }
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Action {
    pub skill: Skill,
    #[serde(default)]
    pub infrastructure: Option<infrastructure::InfrastructureOperation>,
    #[serde(default)]
    pub record: Option<String>,
    #[serde(default)]
    pub archive: Option<u32>,
    #[serde(default)]
    pub destination: Option<i32>,
    #[serde(default)]
    pub target: Option<u32>,
    #[serde(default)]
    pub text: Option<String>,
    #[serde(default = "one")]
    pub duration: u32,
}
fn one() -> u32 {
    1
}
impl Action {
    pub fn new(skill: Skill) -> Self {
        Self {
            skill,
            infrastructure: None,
            record: None,
            archive: None,
            destination: None,
            target: None,
            text: None,
            duration: 1,
        }
    }
    pub fn go(x: i32) -> Self {
        Self {
            destination: Some(x),
            ..Self::new(Skill::Move)
        }
    }
    pub fn say(text: &str) -> Self {
        Self {
            text: Some(text.into()),
            ..Self::new(Skill::Speak)
        }
    }
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Belief {
    pub location: i32,
    pub danger: bool,
    pub text: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Known {
    pub claim: Belief,
    pub source: u64,
    pub confidence: i32,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Percept {
    pub source: u64,
    pub tick: u64,
    pub kind: String,
    pub from: Option<u32>,
    pub location: i32,
    pub content: Value,
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Reflection {
    pub source: u64,
    pub interpretation: String,
    #[serde(default)]
    pub knowledge: Option<knowledge::KnowledgeDraft>,
    #[serde(default)]
    pub caution_delta: i32,
    #[serde(default)]
    pub trust_delta: i32,
    #[serde(default)]
    pub belief: Option<Belief>,
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Decision {
    pub reason: String,
    #[serde(default)]
    pub actions: Vec<Action>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub policy: Option<Node>,
    #[serde(default)]
    pub reflections: Vec<Reflection>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Execution {
    #[serde(default)]
    pub dialogue: bool,
    pub decision: u64,
    pub tree: Behavior<Action>,
    pub cursor: usize,
    pub attempt: Option<u64>,
    pub remaining: u32,
    #[serde(default)]
    pub script: Option<scripting::Invocation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub policy: Option<Node>,
    #[serde(default, skip_serializing_if = "PolicyState::is_default")]
    pub state: PolicyState,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Player(std::sync::Arc<PlayerData>);
impl From<PlayerData> for Player {
    fn from(data:PlayerData)->Self {Self(std::sync::Arc::new(data))}
}
impl std::ops::Deref for Player {
    type Target=PlayerData;
    fn deref(&self)->&Self::Target {&self.0}
}
impl std::ops::DerefMut for Player {
    fn deref_mut(&mut self)->&mut Self::Target {std::sync::Arc::make_mut(&mut self.0)}
}
impl Player {
    /// Transaction-local identity of an unchanged character, with copy-on-write
    /// isolation for candidate actions. This is not a persisted identity.
    pub fn same_snapshot(&self,other:&Self)->bool {std::sync::Arc::ptr_eq(&self.0,&other.0)}
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlayerData {
    pub id: u32,
    pub name: String,
    pub controller: Controller,
    pub motive: String,
    #[serde(default)]
    pub current_goal: Option<String>,
    pub role: String,
    pub position: i32,
    pub health: i32,
    pub hunger: i32,
    pub energy: i32,
    pub food: i32,
    pub caution: i32,
    pub empathy: i32,
    pub introspection: i32,
    pub fear: i32,
    #[serde(default)]
    pub knowledge: deferred::Deferred<Vec<knowledge::Holding>>,
    #[serde(default)]
    pub beliefs: deferred::Deferred<Vec<Known>>,
    #[serde(default)]
    pub relationships: deferred::Deferred<BTreeMap<u32, i32>>,
    #[serde(default)]
    pub memories: deferred::Deferred<Vec<Percept>>,
    #[serde(default)]
    pub site_observations: deferred::Deferred<Vec<Percept>>,
    #[serde(default)]
    pub execution: Option<Execution>,
    #[serde(default)]
    pub generation: u64,
    #[serde(default)]
    pub failures: u32,
    #[serde(default)]
    pub last_reflection: u64,
    #[serde(default)]
    pub last_cause: Option<u64>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Site {
    pub position: i32,
    pub food: i32,
    pub hazard: i32,
    #[serde(default)]
    pub shelter: i32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Weather {
    pub cold_after_ms: u64,
    pub damage_per_pulse: i32,
    pub shelter_required: i32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Scenario {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub society: Option<society::SocietySeed>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub infrastructure: Option<infrastructure::InfrastructureSeed>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lifecycle: Option<lifecycle::LifecycleSeed>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub disturbances: Vec<perturbations::Disturbance>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub knowledge: BTreeMap<u32, Vec<knowledge::RecordSeed>>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub archives: Vec<knowledge::ArchiveSeed>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub starting_behaviors: BTreeMap<u32, starting_behaviors::StartingBehavior>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub food_sources: Vec<ecology::FoodSource>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub weather: Option<Weather>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub arenas: Vec<spatial::Arena>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub map: Option<spatial::Grid>,
    pub name: String,
    pub seed: u64,
    pub max_ticks: u64,
    pub players: Vec<Player>,
    pub sites: Vec<Site>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Event {
    pub id: u64,
    pub run: String,
    pub tick: u64,
    pub actor: Option<u32>,
    pub kind: String,
    pub parents: Vec<u64>,
    pub data: participant::ExperienceData,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Pending {
    pub id: u64,
    pub actor: u32,
    pub generation: u64,
    pub tick: u64,
    pub context: Value,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct World {
    pub run: String,
    pub version: String,
    #[serde(default)]
    pub scripts: deferred::Deferred<scripting::Registry>,
    #[serde(default)]
    pub laws: laws::LawState,
    pub initial: deferred::Deferred<Scenario>,
    pub tick: u64,
    #[serde(default)]
    pub timing: timing::Timing,
    pub players: Vec<Player>,
    pub sites: Vec<Site>,
    #[serde(default)]
    pub infrastructure: infrastructure::InfrastructureState,
    #[serde(default)]
    pub archives: Vec<knowledge::Archive>,
    #[serde(default)]
    pub lifecycle: BTreeMap<u32, lifecycle::Lifecycle>,
    #[serde(default)]
    pub reproduction_offers: BTreeMap<u32, lifecycle::ReproductionOffer>,
    #[serde(default)]
    pub next_actor: u32,
    #[serde(default)]
    pub actor_arenas: BTreeMap<u32, String>,
    pub pending: Vec<Pending>,
    pub next_event: u64,
    pub stopped: bool,
    #[serde(default)]
    pub request_ids: Vec<u64>,
    #[serde(default)]
    pub participant_mode: bool,
    #[serde(default)]
    pub participants: BTreeMap<u32, participant::ParticipantState>,
    #[serde(skip)]
    pub events: Vec<Event>,
}
impl World {
    pub fn new(run: String, scenario: Scenario) -> Result<Self, String> {
        let (mut world, mut progress) = Self::begin_initialization(run, scenario)?;
        while !world.initialize_batch(&mut progress, 64)? {}
        Ok(world)
    }

    /// Begin an unpublished world. The caller must finish `initialize_batch`
    /// before admitting commands, advancing time, or granting access.
    pub fn begin_initialization(run: String, scenario: Scenario)
        -> Result<(Self, initialization::Progress), String> {

        if scenario.players.is_empty() || scenario.max_ticks == 0 {
            return Err("scenario needs players and a positive tick horizon".into());
        }
        if let Some(map) = &scenario.map {
            map.validate()?;
        }
        if scenario.weather.as_ref().is_some_and(|w| w.cold_after_ms > 25_000_000
            || !(1..=20).contains(&w.damage_per_pulse) || !(1..=12).contains(&w.shelter_required)) {
            return Err("invalid weather parameters".into());
        }
        let mut ids = std::collections::BTreeSet::new();
        for p in &scenario.players {
            if !ids.insert(p.id)
                || p.health <= 0
                || p.health > 100
                || !spatial::walkable(scenario.map.as_ref(), p.position)
                || !(0..=100).contains(&p.hunger)
                || !(0..=100).contains(&p.energy)
                || !(0..=100).contains(&p.caution)
                || !(0..=100).contains(&p.empathy)
                || !(0..=100).contains(&p.introspection)
                || p.food < 0
                || p.food > 100
                || p.execution.is_some()
                || !p.memories.is_empty()
                || !p.site_observations.is_empty()
                || !p.knowledge.is_empty()
            {
                return Err("invalid initial player".into());
            }
        }
        let mut locations = std::collections::BTreeSet::new();
        for s in &scenario.sites {
            if !locations.insert(s.position)
                || !spatial::walkable(scenario.map.as_ref(), s.position)
                || s.food < 0
                || s.food > 100
                || !(0..=100).contains(&s.hazard)
                || !(0..=12).contains(&s.shelter)
            {
                return Err("invalid site".into());
            }
        }
        spatial::validate_arenas(&scenario)?;
        ecology::validate(&scenario)?;
        society::validate(&scenario)?;
        perturbations::validate(&scenario)?;
        let mut w = Self {
            run,
            version: VERSION.into(),
            scripts: scripting::Registry::default().into(),
            laws: laws::LawState::default(),
            players: scenario.players.clone(),
            sites: scenario.sites.clone(),
            infrastructure: infrastructure::InfrastructureState::default(),
            archives: scenario.archives.iter().map(|s| knowledge::Archive {
                id:s.id,position:s.position,label:s.label.clone(),capacity:s.capacity,
                records:vec![],destroyed:false,revision:0,
            }).collect(),
            lifecycle: BTreeMap::new(),
            reproduction_offers: BTreeMap::new(),
            next_actor: 0,
            actor_arenas: scenario.arenas.iter().flat_map(|a| a.actors.iter().map(|id| (*id, a.id.clone()))).collect(),
            initial: scenario.into(),
            tick: 0,
            timing: timing::Timing::default(),
            pending: vec![],
            next_event: 1,
            stopped: false,
            request_ids: vec![],
            participant_mode: false,
            participants: BTreeMap::new(),
            events: vec![],
        };
        let id=w.event(None,"initialization",vec![],json!({"scenario":w.initial,"rules":VERSION,"scripts":w.scripts,"prompt":PROMPT,"seed_usage":"reserved; current world rules use no random draws"}));
        w.initialize_lifecycle(id)?;
        w.initialize_infrastructure(id)?;
        Ok((w, initialization::Progress::new(id)))
    }
    pub fn event(
        &mut self,
        actor: Option<u32>,
        kind: &str,
        parents: Vec<u64>,
        mut data: Value,
    ) -> u64 {
        self.event_metadata(&mut data);
        self.append_event(actor, kind, parents, data.into())
    }
    fn event_metadata(&self, data: &mut Value) {
        if let Some(object) = data.as_object_mut() {
            object.insert("rules_revision".into(), json!(self.scripts.revision));
            object.insert("time_ms".into(), json!(self.timing.time_ms));
            object.insert("update".into(), json!(self.timing.updates));
        }
    }
    fn append_event(&mut self, actor: Option<u32>, kind: &str, parents: Vec<u64>,
        data: participant::ExperienceData) -> u64 {
        let id = self.next_event;
        self.next_event += 1;
        let event = Event {
            id,
            run: self.run.clone(),
            tick: self.tick,
            actor,
            kind: kind.into(),
            parents,
            data,
        };
        // Personal evidence consumes this event and character state, never the
        // audit prefix. Borrow it before moving it into the ordered audit vector
        // instead of cloning every payload merely to cross the mutable boundary.
        self.record_experience(&event);
        self.events.push(event);
        id
    }
    fn idx(&self, actor: u32) -> Result<usize, String> {
        self.players
            .iter()
            .position(|p| p.id == actor)
            .ok_or("unknown player".into())
    }
    fn perceive(
        &mut self,
        i: usize,
        world_event: u64,
        kind: &str,
        from: Option<u32>,
        location: i32,
        content: Value,
    ) -> Result<u64, String> {
        self.perceive_with_payload(i, world_event, kind, from, location,
            std::borrow::Cow::Owned(content), None)
    }
    /// A notification may share its immutable payload among actual witnesses.
    /// Recipient authority, event identity and personal state remain separate.
    fn perceive_with_payload(
        &mut self, i: usize, world_event: u64, kind: &str, from: Option<u32>,
        location: i32, content: std::borrow::Cow<'_, Value>,
        payload: Option<&participant::ExperienceData>,
    ) -> Result<u64, String> {
        self.wake(self.players[i].id);
        let client = self.client_controlled(self.players[i].id);
        let limit: usize = if client { 0 } else { self.scripts.law("memory_limit", json!({}))? };
        if limit > 256 {
            return Err("memory policy exceeds storage budget".into());
        }
        let id = if let Some(payload) = payload {
            self.append_event(Some(self.players[i].id), "perception", vec![world_event], payload.clone())
        } else {
            self.event(Some(self.players[i].id), "perception", vec![world_event],
                json!({"kind":kind,"from":from,"location":location,"content":content.as_ref()}))
        };
        if client {
            let controller = self.participants.get_mut(&self.players[i].id).unwrap().client_controller.as_mut().unwrap();
            if let Some(target) = from { controller.remember_target(target); }
            if kind == "site" {
                controller.last_lifecycle = Some((&content["lifecycle"]).into());
                for person in content["lifecycle"]["people"].as_array().into_iter().flatten() {
                    if let Some(id) = person["id"].as_u64().and_then(|v| u32::try_from(v).ok()) {
                        controller.remember_target(id);
                    }
                }
            }
            self.players[i].last_cause = Some(id);
            return Ok(id);
        }
        let percept = Percept {
            source: id,
            tick: self.tick,
            kind: kind.into(),
            from,
            location,
            content: content.into_owned(),
        };
        if kind == "site" {
            self.players[i].site_observations.retain(|p| p.location != location);
            self.players[i].site_observations.push(percept.clone());
            if self.players[i].site_observations.len() > 64 { self.players[i].site_observations.remove(0); }
        }
        self.players[i].memories.push(percept);
        while self.players[i].memories.len() > limit {
            self.players[i].memories.remove(0);
        }
        self.players[i].last_cause = Some(id);
        Ok(id)
    }
    fn observe_site(&mut self, i: usize) -> Result<(), String> {
        let _profile = timing::DiagnosticScope::new("observe.total");
        if self.players[i].health <= 0 {
            return Ok(());
        }
        let id = self.observe_site_facts(i)?;
        let visibility_profile = timing::DiagnosticScope::new("observe.visibility");
        let mut visible = vec![];
        for other in self.visible_players(i, "sight")? {
            let p = &self.players[other];
            visible.push((p.id, p.name.clone(), p.position));
        }
        drop(visibility_profile);
        let _profile = timing::DiagnosticScope::new("observe.people_perception");
        for (other, name, location) in visible {
            self.perceive(i, id, "seen_player", Some(other), location,
                json!({"name":name,"position":location}))?;
        }
        Ok(())
    }
    /// Refresh the changed site's facts without manufacturing new sightings of
    /// every nearby person. Explicit observation still performs both operations.
    fn observe_site_facts(&mut self, i: usize) -> Result<u64, String> {
        self.observe_site_facts_with_lifecycle(i, None)
    }
    fn observe_site_facts_with_lifecycle(&mut self, i: usize, lifecycle: Option<participant::ExperienceData>) -> Result<u64, String> {
        let pos = self.players[i].position;
        let catalog_profile = timing::DiagnosticScope::new("observe.catalog");
        let mut observation: Value = self.actor_law(i,
            "observation",
            json!(self.sites.iter().find(|s| s.position == pos)),
        )?;
        observation["food_source"] = json!(self.initial.food_sources.iter().find(|s| s.position == pos));
        observation["archives"] = self.local_archive_catalog(i);
        let encoded_lifecycle = lifecycle.as_ref().filter(|_| self.client_controlled(self.players[i].id)).cloned();
        observation["lifecycle"] = if encoded_lifecycle.is_some() { Value::Null }
            else { lifecycle.map(|value| (*value).clone()).unwrap_or_else(|| self.local_lifecycle_catalog(i)) };
        observation["infrastructure"] = self.infrastructure_facts(self.players[i].id);
        drop(catalog_profile);
        let food = observation["food"].as_i64().unwrap_or(0);
        let parents = self.players[i]
            .execution
            .as_ref()
            .and_then(|e| e.attempt)
            .or(self.players[i].last_cause)
            .into_iter()
            .collect();
        let id = self.event(
            None,
            "world_observation",
            parents,
            json!({"location":pos,"visible_food":food}),
        );
        {
            let _profile = timing::DiagnosticScope::new("observe.site_perception");
            if let Some(lifecycle) = encoded_lifecycle {
                self.perceive_client_site(i, id, pos, observation, lifecycle)?;
            } else { self.perceive(i, id, "site", None, pos, observation)?; }
        }
        Ok(id)
    }

    fn perceive_client_site(&mut self, i: usize, world_event: u64, location: i32,
        observation: Value, lifecycle: participant::ExperienceData) -> Result<(), String> {
        use participant::ExperienceData;
        let actor = self.players[i].id;
        debug_assert!(self.client_controlled(actor));
        // Only the bundled-law refresh supplies an encoded lifecycle. Its site
        // object is not an inspection exception; redact the small remainder and
        // the shared lifecycle independently with the original source policy.
        debug_assert!(!matches!(observation["kind"].as_str(), Some("program_inspected" | "law_inspected")));
        let redacted_observation = research::redacted(observation.clone());
        let redacted_lifecycle = lifecycle.redacted();
        let content = ExperienceData::with_field(&observation, "lifecycle", &lifecycle);
        let redacted_content = if redacted_observation == observation && lifecycle.same_snapshot(&redacted_lifecycle) {
            content.clone()
        } else { ExperienceData::with_field(&redacted_observation, "lifecycle", &redacted_lifecycle) };
        let mut envelope = json!({"kind":"site","from":null,"location":location,"content":null});
        self.event_metadata(&mut envelope);
        let data = ExperienceData::with_field(&envelope, "content", &content);
        let personal = if content.same_snapshot(&redacted_content) { data.clone() }
            else { ExperienceData::with_field(&envelope, "content", &redacted_content) };
        // This fixed envelope has no source markers or inspection exception.
        data.cache_redaction(personal);
        self.wake(actor);
        let id = self.append_event(Some(actor), "perception", vec![world_event], data);
        let controller = self.participants.get_mut(&actor).unwrap().client_controller.as_mut().unwrap();
        for person in lifecycle["people"].as_array().into_iter().flatten() {
            if let Some(id) = person["id"].as_u64().and_then(|v| u32::try_from(v).ok()) {
                controller.remember_target(id);
            }
        }
        controller.last_lifecycle = Some(lifecycle);
        self.players[i].last_cause = Some(id);
        Ok(())
    }
    pub fn context(&self, i: usize) -> Value {
        self.context_inner(i, true)
    }
    pub(crate) fn presentation_context(&self, i: usize) -> Value {
        let p = &self.players[i];
        let starter = self.initial.starting_behaviors.get(&p.id).map(|b|(b,"authored world seed; revisable starting habit"))
            .or_else(||self.lifecycle.get(&p.id).is_some_and(|l| !matches!(l.origin, lifecycle::Origin::Initial)).then(|| self.initial.lifecycle.as_ref()
                .map(|l|(&l.newcomer.starting_behavior,"newborn seed; revisable starting habit"))).flatten());
        let approach = p.execution.as_ref().map(|e| if let Some(policy)=&e.policy {json!({"decision":e.decision,"policy":policy,"state":e.state,"active_attempt":e.attempt})} else {json!(e)});
        research::redacted(json!({"research":self.research_facts(p.id),"society":self.society_context(p.id),"infrastructure":self.infrastructure_facts(p.id),"body":self.body_support_context(p.id),"starting_behavior":starter.map(|(b,source)|json!({"id":b.id,"revision":b.revision,"description":b.description,"source":source,"revisable":true})),"recent_activity":self.participants.get(&p.id).map(|s|s.activity_summary(self.timing.time_ms)),"lifecycle":self.local_lifecycle_catalog(i),"player":{"development":self.lifecycle.get(&p.id),"id":p.id,"name":p.name,"role":p.role,"motive":p.motive,"current_goal":p.current_goal,"position":p.position,"health":p.health,"hunger":p.hunger,"energy":p.energy,"food":p.food,"personality":{"caution":p.caution,"empathy":p.empathy,"introspection":p.introspection},"fear":p.fear,"knowledge":p.knowledge,"beliefs":p.beliefs,"relationships":p.relationships,"memories":p.memories,"site_observations":p.site_observations,"failures":p.failures,"current_approach":approach}}))
    }
    fn context_inner(&self, i: usize, include_skill_catalog: bool) -> Value {
        let p = &self.players[i];
        let mut context = self.presentation_context(i);
        let extra = research::redacted(json!({"state_contract":participant::state_contract(),"weather_forecast":self.initial.weather,"map":self.map_for_actor(p.id),"map_contract":"If map is present, it is a shared surveyed terrain map: cell ID = y * width + x; north decreases y. blocked cells are walls. If bounds is present, only cells within that rectangle exist for you; all destinations must stay inside it. Move chooses a shortest cardinal route through surveyed walkable terrain; it does not avoid unseen dangers or choose goals. Use intermediate destinations to choose a different route. Resources and dangers are not included in the survey.","simulation_tick":self.tick,"skills":self.scripts.active.keys().filter(|id| id.as_str() != "law").collect::<Vec<_>>(),"skill_definitions":if include_skill_catalog { json!(self.scripts.catalog()) } else { Value::Null },"simulation_time_ms":self.timing.time_ms,"simulation_updates":self.timing.updates,"clock_unit_ms":timing::LEGACY_UNIT_MS,"rules_revision":self.scripts.revision,"rules_description":self.scripts.history["law"][&self.scripts.active["law"]].description}));
        context.as_object_mut().unwrap().extend(extra.as_object().unwrap().clone());
        context
    }
    pub fn request(&mut self, i: usize, trigger: &str) {
        if self.participant_mode {
            return;
        }
        let actor = self.players[i].id;
        if self.players[i].health <= 0
            || self.players[i].controller != Controller::Ai
            || self.pending.iter().any(|p| p.actor == actor)
        {
            return;
        }
        let context = self.context(i);
        let rethink = self.event(Some(actor), "rethinking", self.players[i].last_cause.into_iter().collect(), json!({"trigger":trigger,"policy_generation":self.players[i].generation,"installed_policy_keeps_executing":self.players[i].execution.as_ref().is_some_and(|e|e.policy.is_some())}));
        self.players[i].last_cause = Some(rethink);
        let id=self.event(Some(actor),"model_request",self.players[i].last_cause.into_iter().collect(),json!({"trigger":trigger,"context":context,"base_system_prompt":PROMPT,"rules":VERSION,"generation":self.players[i].generation}));
        self.request_ids.push(id);
        self.pending.push(Pending {
            id,
            actor,
            generation: self.players[i].generation,
            tick: self.tick,
            context,
        });
        self.players[i].last_reflection = self.tick;
    }
    fn validate(&self, i: usize, d: &Decision, evidence: &[Percept]) -> Result<(), String> {
        if (d.policy.is_none() && d.actions.is_empty())
            || (d.policy.is_some() && !d.actions.is_empty())
            || d.actions.len() > MAX_ACTIONS
            || d.reason.trim().is_empty()
            || d.reason.chars().count() > 1000
            || d.reflections.len() > MAX_REFLECTIONS
        {
            return Err(
                "decision needs explanation and 1..8 actions, at most 8 reflections".into(),
            );
        }
        let policy_actions = if let Some(policy) = &d.policy {
            policy.validate_with_map(&self.scripts, self.map_for_actor(self.players[i].id).as_ref())?
        } else {
            vec![]
        };
        for a in d.actions.iter().chain(policy_actions.iter().copied()) {
            self.validate_scoped_action(i,a)?;
        }
        let p = &self.players[i];
        for r in &d.reflections {
            let source = evidence
                .iter()
                .find(|m| m.source == r.source)
                .ok_or("reflection source not in remembered perceptions")?;
            let reason: String = self.scripts.law("validate_reflection", json!(r))?;
            if !reason.is_empty() {
                return Err(reason);
            }
            if let Some(b) = &r.belief {
                let record_location = if source.kind == "knowledge_report" {
                    source.content["record"]["location"].as_i64()
                } else if source.kind == "perception" && source.content["kind"] == "knowledge_report" {
                    source.content["content"]["record"]["location"].as_i64()
                } else { None };
                if b.text.len() > 1000
                    || (!p.beliefs.iter().any(|k| k.claim.location == b.location)
                        && b.location != source.location && record_location != Some(i64::from(b.location)))
                {
                    return Err("belief location is not known".into());
                }
            }
        }
        Ok(())
    }
    fn interrupt(&mut self, i: usize, cause: u64, reason: &str) {
        self.controller_action_status(self.players[i].id, Status::Interrupted, None);
        if let Some(mut e) = self.players[i].execution.take() {
            let persistent = e.policy.is_some();
            self.event(Some(self.players[i].id),if persistent {"action_interrupted"} else {"behavior_interrupted"},vec![cause,e.decision],json!({"cursor":e.cursor,"node_path":e.state.active_path,"reason":reason,"policy_preserved":persistent && reason != "approach revised"}));
            if let Some(attempt) = e.attempt.take() {
                self.event(
                    Some(self.players[i].id),
                    "skill_result",
                    vec![attempt, cause],
                    json!({"status":"interrupted","reason":reason}),
                );
            }
            e.remaining = 0;
            e.state.active_path = None;
            e.state.status = Status::Interrupted;
            if persistent && reason != "approach revised" {
                self.players[i].execution = Some(e);
            } else if persistent {
                self.event(
                    Some(self.players[i].id),
                    "policy_replaced",
                    vec![cause, e.decision],
                    json!({"reason":reason}),
                );
            }
        }
    }
    pub fn submit(
        &mut self,
        actor: u32,
        controller: Controller,
        d: Decision,
        parent: Option<u64>,
    ) -> Result<(), String> {
        if self.participant_mode {
            return Err("use actor-scoped participant commands".into());
        }
        self.apply_decision(actor, controller, d, parent, None)
    }
    fn target_perceived(&self, i: usize, target: u32, evidence: &[Percept]) -> Result<bool, String> {
        // Current perception is an authoritative law check, independent of the
        // bounded memory tail. Check only the requested pair, not every actor.
        if let Some(other) = self.players.iter().position(|p| p.id == target) {
            if self.visible(i, other, "sight")? { return Ok(true); }
        }
        if let Some(client) = self.participants.get(&self.players[i].id).and_then(|s|s.client_controller.as_ref()) {
            return Ok(client.known_targets.contains(&target));
        }
        Ok(evidence.iter().any(|memory| memory.from == Some(target))
            || self.players[i].site_observations.iter().any(|observation| {
                observation.kind == "site"
                    && observation.content["lifecycle"]["people"]
                        .as_array()
                        .is_some_and(|people| {
                            people.iter().any(|person| person["id"].as_u64() == Some(u64::from(target)))
                        })
            }))
    }
    fn apply_decision_inner(
        &mut self,
        actor: u32,
        controller: Controller,
        d: Decision,
        parent: Option<u64>,
        remembered: Option<Vec<Percept>>,
    ) -> Result<(), String> {
        let i = self.idx(actor)?;
        if self.stopped || self.players[i].health <= 0 {
            return Err("player is dead or run stopped".into());
        }
        if self.players[i].controller != controller {
            return Err("wrong controller".into());
        }
        let evidence = remembered.unwrap_or_else(|| self.players[i].memories.to_vec());
        self.validate(i, &d, &evidence)?;
        // Targets must be known through the actor's own evidence, including
        // retained local catalogs after their short arrival memories expire.
        {
            let policy_actions = d
                .policy
                .as_ref()
                .map(|p| p.validate_with_map(&self.scripts, self.map_for_actor(self.players[i].id).as_ref()))
                .transpose()?
                .unwrap_or_default();
            for a in d.actions.iter().chain(policy_actions.iter().copied()) {
                if let Some(target) = a.target {
                    if !self.target_perceived(i, target, &evidence)? {
                        return Err("target not perceived".into());
                    }
                }
            }
        }
        let id=self.event(Some(actor),"decision",parent.into_iter().chain(self.players[i].last_cause).collect(),json!({"controller":controller,"reported_explanation":d.reason,"context":self.context(i),"actions":d.actions,"policy":d.policy,"decision_format":if d.policy.is_some(){DECISION_FORMAT_VERSION}else{LEGACY_DECISION_FORMAT},"behavior_version":VERSION}));
        self.interrupt(i, id, "approach revised");
        for r in &d.reflections {
            // A delayed interpretation must not overwrite a newer direct/retained belief.
            if let Some(b) = &r.belief {
                if let Some(newer) = self.players[i]
                    .beliefs
                    .iter()
                    .find(|k| k.claim.location == b.location && k.source > r.source)
                {
                    self.event(
                        Some(actor),
                        "reflection_skipped",
                        vec![id, r.source, newer.source],
                        json!({"reason":"newer subjective evidence retained","reflection":r}),
                    );
                    continue;
                }
            }
            let before = self.players[i].clone();
            let source = evidence
                .iter()
                .find(|m| m.source == r.source)
                .ok_or("validated reflection source missing")?;
            self.reflect_identity(i, r, source)?;
            self.event(Some(actor),"identity_change",vec![id,r.source],json!({"interpretation":r.interpretation,"before":{"caution":before.caution,"beliefs":before.beliefs,"relationships":before.relationships},"after":{"caution":self.players[i].caution,"beliefs":self.players[i].beliefs,"relationships":self.players[i].relationships}}));
        }
        self.players[i].generation += 1;
        self.wake(actor);
        self.players[i].execution = Some(Execution {
            dialogue: false,
            decision: id,
            tree: Behavior::Sequence(d.actions.into_iter().map(Behavior::Action).collect()),
            cursor: 0,
            attempt: None,
            remaining: 0,
            script: None,
            policy: d.policy.clone(),
            state: PolicyState::default(),
        });
        if d.policy.is_some() {
            self.event(Some(actor), "policy_installed", vec![id], json!({"generation":self.players[i].generation,"policy_version":policy::POLICY_VERSION,"controller":controller,"persistent":true}));
        }
        self.players[i].last_cause = Some(id);
        Ok(())
    }
    pub fn model_result(&mut self, request: u64, raw: &str, metadata: Value) -> Result<(), String> {
        if self.participant_mode {
            return Err("legacy model-result route disabled for participant runs".into());
        }
        let no_proposal = raw.trim().is_empty() && metadata["error"].as_str().is_some();
        let pending = self
            .pending
            .iter()
            .position(|p| p.id == request)
            .map(|i| self.pending.remove(i));
        let response = self.event(
            pending.as_ref().map(|p| p.actor),
            "model_result",
            if self.request_ids.contains(&request) {
                vec![request]
            } else {
                vec![]
            },
            json!({"request_id":request,"raw":raw,"metadata":metadata}),
        );
        let result = (|| {
            let p = pending.ok_or("unknown or already resolved request")?;
            let i = self.idx(p.actor)?;
            if self.players[i].generation != p.generation
                || self.tick.saturating_sub(p.tick) > REQUEST_EXPIRY_TICKS
            {
                return Err("stale request".into());
            }
            if self.stopped
                || self.players[i].health <= 0
                || self.players[i].controller != Controller::Ai
            {
                return Err("player is dead, controller changed or run stopped".into());
            }
            if no_proposal {
                return Err(
                    "reasoning failed; no proposal returned (see model_result metadata)".into(),
                );
            }
            let d: Decision =
                serde_json::from_str(raw).map_err(|e| format!("invalid model decision: {e}"))?;
            let evidence: Vec<Percept> =
                serde_json::from_value(p.context["player"]["memories"].clone())
                    .map_err(|e| e.to_string())?;
            self.event(Some(p.actor), "proposal_revalidated", vec![response,p.id], json!({"context_tick":p.tick,"current_tick":self.tick,"policy_generation":p.generation,"rule":"same policy generation; current guards and skill prerequisites apply; newer beliefs retained"}));
            self.apply_decision(p.actor, Controller::Ai, d, Some(response), Some(evidence))
        })();
        if let Err(e) = &result {
            self.event(None, "model_rejected", vec![response], json!({"reason":e}));
        }
        result
    }
    fn fallback(&mut self, i: usize) -> Result<(), String> {
        let p = &self.players[i];
        let skill: Skill =
            serde_json::from_value(self.scripts.law("bootstrap", scripting::facts(p))?)
                .map_err(|e| e.to_string())?;
        let action = Action::new(skill);
        let id=self.event(Some(p.id),"decision",p.last_cause.into_iter().collect(),json!({"controller":"authored_bootstrap","reported_explanation":"Minimal eat/rest/wait while awaiting an installed policy","context":self.context(i),"actions":[action],"behavior_version":VERSION}));
        self.players[i].execution = Some(Execution {
            dialogue: false,
            decision: id,
            tree: Behavior::Sequence(vec![Behavior::Action(action)]),
            cursor: 0,
            attempt: None,
            remaining: 0,
            script: None,
            policy: None,
            state: PolicyState::default(),
        });
        Ok(())
    }
    fn fail(&mut self, i: usize, attempt: u64, reason: &str, dialogue: bool) -> Status {
        let id = self.event(
            Some(self.players[i].id),
            "skill_result",
            vec![attempt],
            json!({"status":"failed","reason":reason}),
        );
        if let Err(error) = self.perceive(
            i,
            id,
            "failure",
            None,
            self.players[i].position,
            json!({"reason":reason}),
        ) {
            self.event(
                Some(self.players[i].id),
                "script_error",
                vec![id],
                json!({"error":error}),
            );
        }
        self.players[i].failures += 1;
        let delay: u64 = self.scripts.law("retry_delay_ms", json!({})).unwrap_or(250);
        self.set_ready_at(
            self.players[i].id,
            dialogue,
            self.timing.time_ms.saturating_add(delay.clamp(1, 60_000)),
        );
        Status::Failure
    }
    fn execute(&mut self, i: usize) {
        let Some(mut e) = self.players[i].execution.clone() else {
            return;
        };
        if let Some(tree) = e.policy.clone() {
            self.execute_policy(i, &tree, e);
            return;
        }
        let Behavior::Sequence(steps) = &e.tree else {
            return;
        };
        let Some(Behavior::Action(a)) = steps.get(e.cursor) else {
            return;
        };
        let count = steps.len();
        let action = a.clone();
        let status = self.execute_action(i, &mut e, action);
        self.controller_action_status(self.players[i].id, status.clone(), e.attempt);
        match status {
            Status::Success => {
                e.cursor += 1;
                if e.cursor == count {
                    self.event(
                        Some(self.players[i].id),
                        "behavior_completed",
                        vec![e.decision],
                        json!({"steps":e.cursor}),
                    );
                    self.players[i].execution = None;
                } else {
                    self.players[i].execution = Some(e);
                }
            }
            Status::Running => self.players[i].execution = Some(e),
            _ => self.players[i].execution = None,
        }
    }
    fn execute_action_inner(
        &mut self,
        i: usize,
        e: &mut Execution,
        a: Action,
    ) -> Result<Status, ActionFailure> {
        let actor = self.players[i].id;
        let attempt = if let Some(id) = e.attempt {
            id
        } else {
            e.script = Some(scripting::Invocation {
                definition: self.scripts.resolve(a.skill.id())?,
                law_binding: Some(self.law_binding_at(Some(self.players[i].position))),
                law_position: Some(self.players[i].position),
                state: Value::Null,
                evaluated_ms: self.timing.time_ms.saturating_sub(self.timing.delta_ms),
                wake_at_ms: 0,
            });
            let id=self.event(Some(actor),"skill_attempt",std::iter::once(e.decision).chain(e.state.last_guard).collect(),json!({"action":a,"step":e.cursor,"node_path":e.state.active_path,"skill_version":VERSION,"definition":e.script.as_ref().map(|s| &s.definition),"law_revision":self.scripts.active["law"],"law_binding":e.script.as_ref().and_then(|s|s.law_binding.as_ref()),"before":{"position":self.players[i].position,"food":self.players[i].food,"energy":self.players[i].energy,"hunger":self.players[i].hunger}}));
            e.attempt = Some(id);
            e.remaining = a.duration;
            id
        };
        self.players[i].execution = Some(e.clone());
        if a.skill.id()=="move" {
            let position=self.players[i].position;
            if e.script.as_ref().is_some_and(|s|s.law_position!=Some(position)) {
                let binding=self.law_binding_at(Some(position));let invocation=e.script.as_mut().unwrap();invocation.law_binding=Some(binding);invocation.law_position=Some(position);
            }
        }
        let invocation = e.script.clone().ok_or("missing pinned skill")?;
        let binding=invocation.law_binding.clone().unwrap_or_else(||self.law_binding_at(Some(self.players[i].position)));
        let validation_profile = timing::DiagnosticScope::new("action.validate");
        let reason: String = self.bound_skill(
            &binding, &invocation.definition,
            "validate",
            json!({"action":a,"actor":scripting::facts(&self.players[i]),"map":self.map_for_actor(self.players[i].id)}),
        )?;
        drop(validation_profile);
        if !reason.is_empty() {
            e.attempt = None;
            e.script = None;
            e.remaining = 0;
            return Ok(self.fail(i, attempt, &reason, e.dialogue));
        }
        if self.lifecycle.get(&actor).is_some_and(|l| l.dependent)
            && matches!(a.skill.id(), "gather" | "build" | "offer_reproduction" | "reproduce" | "fabricate")
        {
            e.attempt = None;
            e.script = None;
            e.remaining = 0;
            return Ok(self.fail(i, attempt, "independent provisioning requires care, development and demonstrated guided practice", e.dialogue));
        }
        let step_profile = timing::DiagnosticScope::new("action.step");
        let result: scripting::StepResult = self.bound_skill(
            &binding, &invocation.definition,
            "step",
            self.script_context(i, &a, e),
        )?;
        drop(step_profile);
        if result.effects.len() > 32
            || result.remaining > 10000
            || matches!(result.status, Status::Interrupted)
        {
            return Err("script effect/lifecycle budget exceeded".into());
        }
        if result.status == Status::Failure {
            if !result.effects.is_empty() {
                return Err("failed script returned effects".into());
            }
            e.attempt = None;
            e.script = None;
            return Ok(self.fail(i, attempt, &result.reason, e.dialogue));
        }
        let effects_profile = timing::DiagnosticScope::new("action.effects");
        for effect in result.effects {
            // Validate against preceding staged effects; the enclosing transaction rolls
            // the whole invocation back if any capability or policy rejects the batch.
            let validation_profile = timing::DiagnosticScope::new("effect.validate");
            if let Err(message)=self.validate_script_effect(i, &a, &effect) {
                let law_denial=matches!(message.as_str(),"active law denied effect"|"destination law denied effect").then(|| {
                    let position=self.players[i].position;let destination=self.effect_destination(&effect);
                    json!({"law_binding":self.law_binding_at(Some(position)),"validation_position":position,"destination":destination,"destination_binding":destination.map(|p|self.law_binding_at(Some(p)))})
                });
                return Err(ActionFailure{message,law_denial});
            }
            drop(validation_profile);
            let _profile = timing::DiagnosticScope::new("effect.apply");
            self.apply_script_effect(i, attempt, effect)?;
        }
        drop(effects_profile);
        for deadline in [result.wake_at_ms, result.cooldown_until_ms]
            .into_iter()
            .flatten()
        {
            if deadline < self.timing.time_ms
                || deadline > self.timing.time_ms.saturating_add(3_600_000)
            {
                return Err("script deadline outside next hour".into());
            }
        }
        if let Some(deadline) = result.cooldown_until_ms {
            self.set_ready_at(actor, e.dialogue, deadline);
        }
        e.remaining = result.remaining;
        if let Some(invocation) = &mut e.script {
            invocation.state = result.state;
            invocation.evaluated_ms = self.timing.time_ms;
            invocation.wake_at_ms = result.wake_at_ms.unwrap_or(self.timing.time_ms);
        }
        if result.status == Status::Running {
            if result.progress.as_object().is_some_and(|p| !p.is_empty()) {
                self.event(
                    Some(actor),
                    "skill_progress",
                    vec![attempt],
                    result.progress,
                );
            }
            return Ok(Status::Running);
        }
        let result=self.event(Some(actor),"skill_result",vec![attempt],json!({"status":"completed","skill":a.skill,"after":{"position":self.players[i].position,"food":self.players[i].food,"energy":self.players[i].energy,"hunger":self.players[i].hunger}}));
        self.perceive(
            i,
            result,
            "own_result",
            None,
            self.players[i].position,
            json!({"skill":a.skill,"status":"completed"}),
        )?;
        e.attempt = None;
        e.remaining = 0;
        e.script = None;
        Ok(Status::Success)
    }
    fn damage(
        &mut self,
        i: usize,
        amount: i32,
        from: Option<u32>,
        cause: u64,
        nature: &str,
    ) -> Result<(), String> {
        let _profile = timing::DiagnosticScope::new("damage.total");
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Reaction {
            health: i32,
            fear: i32,
            caution: i32,
            learn_danger: bool,
            confidence: i32,
            interrupt: bool,
            dead: bool,
        }
        let before = self.players[i].clone();
        let reaction: Reaction = self.actor_law(i,
            "on_damage",
            json!({"actor":scripting::facts(&before),"amount":amount,"nature":nature}),
        )?;
        self.players[i].health = reaction.health;
        let world=self.event(Some(before.id),"damage",vec![cause],json!({"from":from,"amount":amount,"before":before.health,"after":self.players[i].health,"location":before.position,"cause_kind":nature,"law_binding":self.law_binding_at(Some(before.position))}));
        let perception = self.perceive(
            i,
            world,
            if nature == "starvation" {
                "starvation"
            } else if nature == "power_depletion" {
                "power_depletion"
            } else {
                "danger"
            },
            from,
            before.position,
            json!({"damage":amount,"cause":nature}),
        )?;
        self.players[i].fear = reaction.fear;
        if !self.client_controlled(before.id) {
        self.players[i].caution = reaction.caution;
        if reaction.learn_danger {
            self.players[i]
                .beliefs
                .retain(|k| k.claim.location != before.position);
            self.players[i].beliefs.push(Known {
                claim: Belief {
                    location: before.position,
                    danger: true,
                    text: "I was hurt here".into(),
                },
                source: perception,
                confidence: reaction.confidence,
            });
        }
        self.event(Some(before.id),"identity_change",vec![perception],json!({"interpretation":"experienced harm; personal introspection changes caution","before":{"caution":before.caution,"fear":before.fear,"beliefs":before.beliefs},"after":{"caution":self.players[i].caution,"fear":self.players[i].fear,"beliefs":self.players[i].beliefs}}));
        }
        if reaction.interrupt {
            self.interrupt(i, world, "damage");
        }
        self.players[i].failures += 1;
        self.request(i, "experienced harm; installed policy remains active");
        if reaction.dead {
            let _profile = timing::DiagnosticScope::new("damage.death_witnesses");
            self.players[i].generation += 1;
            let death = self.event(
                Some(before.id),
                "death",
                vec![world],
                json!({"name":before.name,"position":before.position,"permanent":true}),
            );
            let mut visibility = visibility::WitnessVisibility::default();
            let content = json!({"name":before.name});
            let mut data = json!({"kind":"death","from":before.id,"location":before.position,"content":content});
            self.event_metadata(&mut data);
            let payload: participant::ExperienceData = data.into();
            // These envelope fields cannot change during perception delivery.
            // Custom visibility/memory laws still run in original recipient
            // order and can reject the same operation before any event append.
            let share = true;
            #[cfg(test)]
            let share = share && !perception_tests::UNSHARED.with(|v| v.get());
            for j in 0..self.players.len() {
                if self.visible_to_witness(j, i, "death", &mut visibility)? {
                    self.perceive_with_payload(
                        j,
                        death,
                        "death",
                        Some(before.id),
                        before.position,
                        std::borrow::Cow::Borrowed(&content),
                        share.then_some(&payload),
                    )?;
                }
            }
        }
        Ok(())
    }
    fn step_inner(&mut self, delta_ms: u64, observer: &mut impl timing::AdvanceObserver,
        selection: Option<&clock::Selection>, maintenance: bool, outside_alive: bool) -> Result<(), String> {
        if self.stopped {
            return Ok(());
        }
        observer.begin("kernel.timing");
        let settled = self.timing.maintenance_ms.unwrap_or(self.timing.time_ms);
        if !maintenance { self.timing.maintenance_ms = Some(settled); }
        self.timing.time_ms = self
            .timing
            .time_ms
            .checked_add(delta_ms)
            .ok_or("time overflow")?;
        self.timing.delta_ms = delta_ms;
        self.timing.updates += 1;
        self.tick = self.timing.time_ms / timing::LEGACY_UNIT_MS;
        let world_delta = self.timing.time_ms.checked_sub(settled).ok_or("maintenance clock moved backwards")?;
        let periods: timing::Periods = self.scripts.law("system_periods_ms", json!({}))?;
        let needs_pulses = if maintenance { timing::pulses(
            &mut self.timing.needs_remainder_ms,
            world_delta,
            periods.needs_ms,
        )? } else { 0 };
        let hazard_pulses = if maintenance { timing::pulses(
            &mut self.timing.hazard_remainder_ms,
            world_delta,
            periods.hazard_ms,
        )? } else { 0 };
        if maintenance {
        observer.begin("kernel.ecology");
        self.renew_food(world_delta)?;
        self.apply_disturbances()?;
        observer.begin("kernel.infrastructure");
        self.advance_infrastructure(world_delta)?;
        }
        observer.begin("kernel.actors");
        for i in 0..self.players.len() {
            if self.players[i].health <= 0 {
                continue;
            }
            // A newborn's physiological clock starts at its birth, rather than
            // inheriting a partial global pulse accumulated before it existed.
            let (needs_pulses, hazard_pulses) = if let Some(life) = self.lifecycle.get(&self.players[i].id).filter(|l| !matches!(l.origin, lifecycle::Origin::Initial)) {
                let actor = self.players[i].id;
                let lived = if maintenance { world_delta.min(self.timing.time_ms.saturating_sub(life.born_ms)) } else { 0 };
                (
                    timing::pulses(self.timing.actor_needs_remainder_ms.entry(actor).or_default(), lived, periods.needs_ms)?,
                    timing::pulses(self.timing.actor_hazard_remainder_ms.entry(actor).or_default(), lived, periods.hazard_ms)?,
                )
            } else { (needs_pulses, hazard_pulses) };
            // Keep newborn clocks exact even on updates where no work is due.
            // Earlier actors may have changed this actor or woken its policy;
            // selection is rechecked here, in the original actor order.
            if needs_pulses == 0 && hazard_pulses == 0
                && selection.is_some_and(|s| !s.includes(self, &self.players[i])) {
                continue;
            }
            let before = self.players[i].hunger;
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Needs {
                hunger: i32,
                fear: i32,
            }
            let mut metabolism = self.players[i].last_cause.unwrap_or(1);
            if needs_pulses > 0 {
                let _profile = timing::DiagnosticScope::new("actor.metabolism");
                let mut facts = scripting::facts(&self.players[i]);
                facts["pulses"] = json!(needs_pulses);
                facts["body"] = self.body_support_context(self.players[i].id);
                facts["elapsed_ms"] = json!(needs_pulses * periods.needs_ms);
                let needs: Needs = self.actor_law(i,"metabolism", facts)?;
                self.players[i].hunger = needs.hunger;
                self.players[i].fear = needs.fear;
                self.wake(self.players[i].id);
                metabolism=self.event(Some(self.players[i].id),"needs_change",vec![],json!({"hunger_before":before,"hunger_after":self.players[i].hunger,"fear":self.players[i].fear,"elapsed_ms":needs_pulses*periods.needs_ms,"law_binding":self.law_binding_at(Some(self.players[i].position))}));
            }

            {
                let _profile = timing::DiagnosticScope::new("actor.body_charge");
                self.consume_body_charge(self.players[i].id, needs_pulses, metabolism)?;
            }
            if self.players[i].health <= 0 {
                continue;
            }
            if !self.client_controlled(self.players[i].id) {
            let interval: u64 = self
                .scripts
                .law("reconsider_interval", scripting::facts(&self.players[i]))?;
            if self.timing.updates == 1
                || (self.tick.saturating_sub(self.players[i].last_reflection) >= interval)
            {
                self.request(
                    i,
                    if self.players[i].failures > 0 {
                        "lack of progress / introspection"
                    } else {
                        "reconsider goals"
                    },
                );
            }
            }
            if !self.participant_mode
                && self.players[i].controller == Controller::Ai
                && self.players[i].execution.is_none()
            {
                self.fallback(i)?;
            }
            let actor = self.players[i].id;
            if self.timing.time_ms
                >= self.players[i]
                    .execution
                    .as_ref()
                    .map_or(0, |e| self.execution_ready_at(actor, e))
                || self.timing.dirty.get(&actor) == Some(&true)
            {
                self.timing.dirty.insert(actor, false);
                self.execute(i);
            }
            if hazard_pulses == 0 {
                continue;
            }
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Aftermath {
                starvation: i32,
                #[serde(default)]
                power_depletion: i32,
                hazard: i32,
                #[serde(default)]
                cold: i32,
            }
            let _profile = timing::DiagnosticScope::new("actor.aftermath");
            let after:Aftermath=self.actor_law(i,"aftermath",json!({"body":self.body_support_context(actor),"time_ms":self.timing.time_ms,"weather":self.initial.weather,"pulses":hazard_pulses,"last_hazard_pulse_ms":self.timing.actor_hazard_remainder_ms.get(&actor).map(|remainder|self.timing.time_ms.saturating_sub(*remainder)),"elapsed_ms":hazard_pulses*periods.hazard_ms,"actor":scripting::facts(&self.players[i]),"site":self.sites.iter().find(|s|s.position==self.players[i].position)}))?;
            if after.starvation < 0 || after.hazard < 0 || after.cold < 0 || after.power_depletion < 0 {
                return Err("negative damage policy".into());
            }
            self.clear_body_support_deficit(actor);
            if after.starvation > 0 {
                self.damage(i, after.starvation, None, metabolism, "starvation")?;
            }
            if self.players[i].health <= 0 {
                continue;
            }
            if after.power_depletion > 0 {
                self.damage(i, after.power_depletion, None, metabolism, "power_depletion")?;
                if self.players[i].health <= 0 { continue; }
            }
            if after.cold > 0 {
                self.damage(i, after.cold, None, metabolism, "weather")?;
                if self.players[i].health <= 0 { continue; }
            }
            let hazard = after.hazard;
            if hazard > 0 {
                let event = self.event(
                    None,
                    "environment_hazard",
                    self.players[i].last_cause.into_iter().collect(),
                    json!({"location":self.players[i].position,"damage":hazard}),
                );
                self.damage(i, hazard, None, event, "environment")?;
            }
        }
        observer.begin("kernel.lifecycle");
        self.advance_lifecycle()?;
        self.flush_law_faults()?;
        observer.begin("kernel.lifecycle_observation");
        self.refresh_lifecycle_observations()?;
        observer.begin("kernel.speech");
        self.deliver_queued_speech_selected(selection.is_some())?;
        observer.begin("kernel.requests");
        let invalid: Vec<_> = self
            .pending
            .iter()
            .filter(|r| {
                self.players
                    .iter()
                    .find(|p| p.id == r.actor)
                    .is_none_or(|p| {
                        p.health <= 0
                            || p.controller != Controller::Ai
                            || p.generation != r.generation
                    })
            })
            .cloned()
            .collect();
        for r in invalid {
            self.pending.retain(|p| p.id != r.id);
            self.event(
                Some(r.actor),
                "model_cancelled",
                std::iter::once(r.id)
                    .chain(
                        self.players
                            .iter()
                            .find(|p| p.id == r.actor)
                            .and_then(|p| p.last_cause),
                    )
                    .collect(),
                json!({"reason":"policy replaced, controller changed or character died"}),
            );
        }
        // Expire pending requests visibly; delayed responses remain recordable but cannot apply.
        let expired: Vec<u64> = self
            .pending
            .iter()
            .filter(|p| self.tick - p.tick > REQUEST_EXPIRY_TICKS)
            .map(|p| p.id)
            .collect();
        for id in expired {
            let _ = self.model_result(
                id,
                "",
                json!({"error":"simulation request deadline exceeded"}),
            );
        }
        if maintenance && self.timing.maintenance_ms.is_some() {
            self.timing.maintenance_ms = Some(self.timing.time_ms);
        }
        if self.tick >= self.initial.max_ticks || (!outside_alive && self.players.iter().all(|p| p.health <= 0)) {
            self.stopped = true;
            self.deliver_queued_speech()?;
            let stop = self.event(None, "run_stopped", vec![], json!({"tick":self.tick}));
            for i in 0..self.players.len() {
                self.interrupt(i, stop, "run ended");
            }
            let pending = std::mem::take(&mut self.pending);
            for p in pending {
                self.event(
                    Some(p.actor),
                    "model_cancelled",
                    vec![p.id, stop],
                    json!({"reason":"run ended before request resolved"}),
                );
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod policy_tests;
#[cfg(test)]
mod starting_behavior_tests;
#[cfg(test)]
mod knowledge_tests;
#[cfg(test)]
mod lifecycle_tests;
#[cfg(test)]
mod tests;

#[cfg(feature = "schema")]
pub mod contract;

#[cfg(test)]
mod participant_tests;
#[cfg(test)]
mod perception_tests;
#[cfg(test)]
mod scripting_tests;

#[cfg(test)]
mod timing_tests;

#[cfg(test)]
mod spatial_tests;

#[cfg(test)]
mod infrastructure_tests;

#[cfg(test)]
mod research_tests;

#[cfg(test)]
mod law_tests;

/// A normal law veto is distinguished from interpreter or effect-contract faults.
struct ActionFailure {message:String,law_denial:Option<Value>}
impl From<String> for ActionFailure {fn from(message:String)->Self{Self{message,law_denial:None}}}
impl From<&str> for ActionFailure {fn from(message:&str)->Self{message.to_owned().into()}}
