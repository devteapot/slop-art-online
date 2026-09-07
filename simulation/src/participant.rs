//! Versioned, transport-independent character commands. Authority authenticates actor separately.
use super::*;
use std::sync::Arc;
use std::sync::OnceLock;
use serde_json::value::RawValue;
use sha2::{Digest, Sha256};
pub const API_VERSION: &str = "sao-participant-v1";
pub const TRACE_LIMIT: usize = 256;
pub const EVIDENCE_LEASE_MS: u64 = 330_000;
/// An immutable captured context, or a transaction-local storage reference.
/// Deferred payloads cannot serialize as World JSON: exports must materialize
/// them explicitly. Physics and interpretation only need the lease's evidence.
#[derive(Clone, Debug)]
pub struct Observation(ObservationPayload);
#[derive(Clone, Debug)]
enum ObservationPayload { Inline(Arc<RawValue>), Deferred(u64) }
impl Observation {
    pub fn deferred(id:u64)->Self {
        assert_ne!(id,0,"deferred observation needs a canonical identity");
        Self(ObservationPayload::Deferred(id))
    }
    pub fn reference(&self)->Option<u64> {
        match &self.0 {ObservationPayload::Deferred(id)=>Some(*id),_=>None}
    }
    pub fn raw(&self)->Result<&RawValue,String> {
        match &self.0 {ObservationPayload::Inline(value)=>Ok(value),
            ObservationPayload::Deferred(_)=>Err("captured observation must be materialized for export".into())}
    }
    pub fn is_capture(&self)->bool {
        match &self.0 {ObservationPayload::Inline(value)=>value.get()!="null",ObservationPayload::Deferred(_)=>true}
    }
}
impl From<Box<RawValue>> for Observation {
    fn from(value:Box<RawValue>)->Self {Self(ObservationPayload::Inline(value.into()))}
}
impl From<Arc<RawValue>> for Observation {
    fn from(value:Arc<RawValue>)->Self {Self(ObservationPayload::Inline(value))}
}
impl std::ops::Deref for Observation {
    type Target=Arc<RawValue>;
    fn deref(&self)->&Self::Target {
        match &self.0 {ObservationPayload::Inline(value)=>value,ObservationPayload::Deferred(_)=>panic!("deferred observation requires explicit materialization")}
    }
}
impl std::ops::DerefMut for Observation {
    fn deref_mut(&mut self)->&mut Self::Target {
        match &mut self.0 {ObservationPayload::Inline(value)=>value,ObservationPayload::Deferred(_)=>panic!("deferred observation requires explicit materialization")}
    }
}
impl Serialize for Observation {
    fn serialize<S:serde::Serializer>(&self,serializer:S)->Result<S::Ok,S::Error> {
        self.raw().map_err(serde::ser::Error::custom)?.serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for Observation {
    fn deserialize<D:serde::Deserializer<'de>>(deserializer:D)->Result<Self,D::Error> {
        Box::<RawValue>::deserialize(deserializer).map(Into::into)
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EvidenceLease {
    #[serde(default)]
    pub request_id: String,
    #[serde(default="empty_observation")]
    pub observation: Observation,
    pub observed_cursor: u64,
    pub expires_ms: u64,
    pub experiences: Arc<Vec<Experience>>,
}
fn empty_observation() -> Observation {
    serde_json::value::to_raw_value(&Value::Null).unwrap().into()
}
#[derive(Serialize)]
struct CapturedRead<'a> {request_id:&'a str, observation:Box<RawValue>}
fn captured_read(lease:&EvidenceLease) -> Result<CapturedRead<'_>,String> {
    // The captured context is immutable JSON. Keep it opaque during world
    // loading/cloning; append the separately retained evidence without parsing
    // its full object graph for every other character's command or clock pulse.
    let body=lease.observation.raw()?.get().trim();
    let prefix=body.strip_prefix('{').and_then(|_|body.strip_suffix('}')).ok_or("invalid captured observation object")?;
    let experiences=serde_json::to_string(&lease.experiences).map_err(|e|e.to_string())?;
    let mut result=String::with_capacity(body.len()+experiences.len()+20);
    result.push_str(prefix);
    if prefix.trim_end()!="{" {result.push(',');}
    result.push_str("\"experiences\":");result.push_str(&experiences);result.push('}');
    Ok(CapturedRead{request_id:&lease.request_id,observation:RawValue::from_string(result).map_err(|e|e.to_string())?})
}
impl EvidenceLease {
    /// Exact immutable response for row-based delivery. Call only when creating
    /// the response row, not when unrelated simulation state changes.
    pub fn response_json(&self) -> Result<String, String> {
        Ok(captured_read(self)?.observation.get().to_owned())
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Experience {
    pub cursor: u64,
    pub source: u64,
    pub tick: u64,
    pub location: i32,
    pub kind: String,
    pub parents: Vec<u64>,
    pub data: ExperienceData,
}
impl Experience {
    /// Whether a strongly owned snapshot still has this exact serialized value.
    /// Payload identity is sufficient because its stored JSON is immutable;
    /// filling its parsed-value cache does not change that JSON.
    pub fn can_reuse_encoding(&self, snapshot: &Self) -> bool {
        // Keep this exhaustive so new serialized fields require guard review.
        let Self {
            cursor, source, tick, location, kind, parents, data,
        } = self;
        *cursor == snapshot.cursor
            && *source == snapshot.source
            && *tick == snapshot.tick
            && *location == snapshot.location
            && *kind == snapshot.kind
            && *parents == snapshot.parents
            && Arc::ptr_eq(&data.0, &snapshot.data.0)
    }
}
// Historical payloads are immutable. Retain their JSON encoding across clock
// pulses and only materialize a value when an evidence check needs its fields.
// Clones share both representations; the persisted and participant API shapes
// remain ordinary JSON objects, with no wrapper fields.
#[derive(Clone, Debug)]
pub struct ExperienceData(Arc<ExperienceDataInner>);
#[derive(Debug)]
struct ExperienceDataInner {
    raw: Box<RawValue>,
    parsed: OnceLock<Value>,
}
impl From<&Value> for ExperienceData {
    fn from(value: &Value) -> Self {
        Self(Arc::new(ExperienceDataInner {
            raw: serde_json::value::to_raw_value(value).expect("JSON value serializes"),
            parsed: OnceLock::new(),
        }))
    }
}
impl std::ops::Deref for ExperienceData {
    type Target = Value;
    fn deref(&self) -> &Value {
        self.0.parsed.get_or_init(|| serde_json::from_str(self.0.raw.get()).expect("validated historical JSON"))
    }
}
impl Serialize for ExperienceData {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        self.0.raw.serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for ExperienceData {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Ok(Self(Arc::new(ExperienceDataInner {
            raw: Box::<RawValue>::deserialize(deserializer)?,
            parsed: OnceLock::new(),
        })))
    }
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ParticipantState(Arc<ParticipantStateData>);
impl From<ParticipantStateData> for ParticipantState {
    fn from(data:ParticipantStateData)->Self {Self(Arc::new(data))}
}
impl std::ops::Deref for ParticipantState {
    type Target=ParticipantStateData;
    fn deref(&self)->&Self::Target {&self.0}
}
impl std::ops::DerefMut for ParticipantState {
    fn deref_mut(&mut self)->&mut Self::Target {Arc::make_mut(&mut self.0)}
}
impl ParticipantState {
    /// A retained snapshot forces copy-on-write before any mutation. Equality
    /// here is a transaction-local change detector, never a durable identity.
    pub fn same_snapshot(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.0, &other.0)
    }
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ParticipantStateData {
    pub control_epoch: u64,
    pub learning_revision: u64,
    pub cursor: u64,
    pub experiences: Vec<Experience>,
    pub speech: Vec<QueuedSpeech>,
    #[serde(default)]
    pub last_speech_tick: Option<u64>,
    pub receipts: Vec<Receipt>,
    pub learned_sources: Vec<u64>,
    #[serde(default)]
    pub evidence_leases: Vec<EvidenceLease>,
    #[serde(default)]
    pub activity: Vec<Value>,
    #[serde(default)]
    pub activity_position: Option<i32>,
}
fn record_activity(state: &mut ParticipantState, event: &Event, time_ms: u64, position: i32) {
    let moved = state.activity_position.is_some_and(|old| old != position);
    if moved {
        state.activity.push(json!({"kind":"move_step","location":position,"time_ms":time_ms}));
    }
    if state.activity_position != Some(position) {
        state.activity_position = Some(position);
    }
    let data = &event.data;
    let item = match event.kind.as_str() {
        "resource_change" => Some(json!({"kind":"site_food","location":data["location"],"delta":data["food_delta"]})),
        "shelter_contribution" => Some(json!({"kind":"shelter","location":data["location"],"delta":data["amount"]})),
        "food_transfer" => Some(json!({"kind":"given_food","delta":data["amount"]})),
        "perception" if data["kind"] == "received_food" => Some(json!({"kind":"received_food","delta":data["content"]["amount"]})),
        "skill_result" => {
            let attempt = event.parents.iter().find_map(|id| state.experiences.iter().find(|e| e.source == *id && e.kind == "skill_attempt"));
            let skill = data.get("skill").cloned().or_else(|| attempt.map(|e| e.data["action"]["skill"].clone())).unwrap_or(Value::Null);
            let stationary = skill == "move" && data["status"] == "completed"
                && attempt.is_some_and(|e| e.data["before"]["position"] == data["after"]["position"]);
            Some(json!({"kind":"action","skill":skill,"status":data["status"],"stationary_move":stationary}))
        }
        _ => None,
    };
    let added = moved || item.is_some();
    if let Some(mut item) = item {
        item["time_ms"] = json!(time_ms);
        state.activity.push(item);
    }
    if !added { return; }
    state.activity.retain(|a| a["time_ms"].as_u64().unwrap_or(0).saturating_add(60_000) >= time_ms);
    while state.activity.len() > 512 { state.activity.remove(0); }
}
impl ParticipantState {
    pub fn activity_summary(&self, time_ms: u64) -> Value {
        let items: Vec<_> = self.activity.iter().filter(|a| a["time_ms"].as_u64().unwrap_or(0).saturating_add(60_000) >= time_ms).collect();
        let mut sites: BTreeMap<i64, (i64, i64)> = BTreeMap::new();
        let mut actions: BTreeMap<String, u64> = BTreeMap::new();
        for item in &items {
            if item["kind"] == "site_food" {
                let delta = item["delta"].as_i64().unwrap_or(0);
                let entry = sites.entry(item["location"].as_i64().unwrap_or(0)).or_default();
                if delta < 0 { entry.0 -= delta; } else { entry.1 += delta; }
            }
            if item["kind"] == "action" {
                *actions.entry(format!("{}:{}", item["skill"].as_str().unwrap_or("custom"), item["status"].as_str().unwrap_or("unknown"))).or_default() += 1;
            }
        }
        json!({"window_limit_ms":60_000,"record_limit":512,"since_ms":items.first().map(|a| &a["time_ms"]),"until_ms":time_ms,
            "own_actions":actions,"position_changes":items.iter().filter(|a|a["kind"]=="move_step").count(),
            "completed_moves_without_displacement":items.iter().filter(|a|a["stationary_move"]==true).count(),
            "own_site_food_changes":sites.into_iter().map(|(location,(withdrawn,deposited))|json!({"location":location,"withdrawn":withdrawn,"deposited":deposited,"net_added":deposited-withdrawn})).collect::<Vec<_>>(),
            "food_given":items.iter().filter(|a|a["kind"]=="given_food").map(|a|a["delta"].as_i64().unwrap_or(0)).sum::<i64>(),
            "food_received":items.iter().filter(|a|a["kind"]=="received_food").map(|a|a["delta"].as_i64().unwrap_or(0)).sum::<i64>(),
            "shelter_contributed":items.iter().filter(|a|a["kind"]=="shelter").map(|a|a["delta"].as_i64().unwrap_or(0)).sum::<i64>(),
            "meaning":"Derived only from your own executed outcomes. High action counts do not imply progress. Equal withdrawals and deposits at one site add zero food there. These aggregates are diagnostics; reflections still cite individual supplied experience sources."})
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QueuedSpeech {
    pub cause: u64,
    pub text: String,
    pub expires_tick: u64,
    #[serde(default)]
    pub execution: Option<Execution>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Receipt {
    pub request_id: String,
    pub fingerprint: String,
    pub ok: bool,
    pub error: Option<String>,
    pub event: u64,
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub api_version: String,
    pub request_id: String,
    pub control_epoch: u64,
    pub command: Command,
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum Command {
    ReadObservation { after: u64, limit: usize },
    PinObservation {
        observed_cursor: u64,
        sources: Vec<u64>,
    },
    ReplaceTree {
        expected_revision: u64,
        reason: String,
        tree: Node,
    },
    PatchSubtree {
        expected_revision: u64,
        reason: String,
        path: String,
        subtree: Node,
    },
    Speak {
        text: String,
        expires_tick: u64,
    },
    Reflect {
        expected_revision: u64,
        observed_cursor: u64,
        reflections: Vec<Reflection>,
        goal: Option<String>,
    },
}
fn within(p: &str, root: &str) -> bool {
    p == root || p.starts_with(&format!("{root}/"))
}
fn replace_at(node: &mut Node, parts: &[&str], replacement: Node) -> Result<(), String> {
    if parts.is_empty() {
        *node = replacement;
        return Ok(());
    }
    match node {
        Node::Once { child } if parts[0] == "once" => {
            replace_at(child, &parts[1..], replacement)
        }
        Node::Guard { child, .. } if parts[0] == "guard" => {
            replace_at(child, &parts[1..], replacement)
        }
        Node::When { child, .. } if parts[0] == "when" => {
            replace_at(child, &parts[1..], replacement)
        }
        Node::Priority { children } | Node::Sequence { children } => {
            let n: usize = parts[0].parse().map_err(|_| "invalid subtree index")?;
            if n.to_string() != parts[0] {
                return Err("noncanonical subtree index".into());
            }
            replace_at(
                children.get_mut(n).ok_or("subtree index out of bounds")?,
                &parts[1..],
                replacement,
            )
        }
        _ => Err("subtree path does not exist".into()),
    }
}
impl World {
    pub fn enable_participants(&mut self) {
        self.participant_mode = true;
        self.pending.clear();
        for p in &self.players {
            self.participants.entry(p.id).or_default();
        }
        // Initialization already generated safe perceptions; import those, never initialization truth.
        for event in self.events.clone() {
            self.record_experience(&event);
        }
    }
    pub fn record_initial_participant_event(&mut self, event: &Event) {
        if self.tick == 0 && matches!(event.kind.as_str(),"perception"|"starting_behavior_installed"|"policy_installed") {
            self.record_experience(event);
        }
    }
    pub(super) fn record_experience(&mut self, e: &Event) {
        if !self.participant_mode {
            return;
        }
        let Some(actor) = e.actor else {
            return;
        };
        let location = self.players.iter().find(|p| p.id == actor).map_or(0, |p| p.position);
        record_activity(self.participants.entry(actor).or_default(), e, self.timing.time_ms, location);
        if !matches!(
            e.kind.as_str(),
            "perception"
                | "skill_attempt"
                | "skill_progress"
                | "skill_result"
                | "action_interrupted"
                | "behavior_interrupted"
                | "speech"
                | "speech_queued"
                | "speech_cancelled"
                | "identity_change"
                | "policy_installed"
                | "starting_behavior_installed"
                | "policy_patched"
                | "branch_selected"
                | "participant_rejected"
                | "control_changed"
                | "reconsider_requested"
                | "death"
        ) {
            return;
        }
        let location = self
            .players
            .iter()
            .find(|p| p.id == actor)
            .map(|p| p.position)
            .unwrap_or(0);
        let s = self.participants.entry(actor).or_default();
        if e.kind == "identity_change" {
            s.learning_revision += 1;
        }
        s.cursor += 1;
        let parents = e
            .parents
            .iter()
            .filter(|id| s.experiences.iter().any(|x| x.source == **id))
            .copied()
            .collect();
        let cursor=s.cursor;
        s.experiences.push(Experience {
            cursor,
            source: e.id,
            tick: e.tick,
            location,
            kind: e.kind.clone(),
            parents,
            data: (&crate::research::redacted(e.data.clone())).into(),
        });
        if s.experiences.len() > TRACE_LIMIT {
            s.experiences.remove(0);
        }
    }
    pub fn participant_snapshot(
        &self,
        actor: u32,
        after: u64,
        limit: usize,
    ) -> Result<Value, String> {
        self.participant_snapshot_inner(actor,after,limit,true)
    }
    fn participant_snapshot_inner(&self, actor:u32, after:u64, limit:usize, include_reads:bool) -> Result<Value,String> {
        if !self.participant_mode {
            return Err("legacy run has no participant-v1 contract".into());
        }
        let i = self.idx(actor)?;
        let s = self
            .participants
            .get(&actor)
            .ok_or("character not provisioned")?;
        if after > s.cursor {
            return Err("cursor ahead of character trace".into());
        }
        let experiences: Vec<_> = s
            .experiences
            .iter()
            .filter(|e| e.cursor > after)
            .take(limit.clamp(1, TRACE_LIMIT))
            .collect();
        let next = experiences.last().map(|e| e.cursor).unwrap_or(after);
        let oldest = s.experiences.first().map(|e| e.cursor).unwrap_or(1);
        Ok(
            json!({"api_version":API_VERSION,"run":self.run,"actor":actor,"tick":self.tick,"time_ms":self.timing.time_ms,"updates":self.timing.updates,"clock_unit_ms":crate::timing::LEGACY_UNIT_MS,"stopped":self.stopped,
            "control_epoch":s.control_epoch,"policy_revision":self.players[i].generation,"learning_revision":s.learning_revision,
            "context":self.context(i),"experiences":experiences,"next_cursor":next,"latest_cursor":s.cursor,"oldest_cursor":oldest,"gap":after.saturating_add(1)<oldest,
            "receipts":s.receipts,"queued_speech":s.speech,
            "read_observations":s.evidence_leases.iter().filter(|l| include_reads && l.expires_ms >= self.timing.time_ms && l.observation.is_capture()).map(captured_read).collect::<Result<Vec<_>,_>>()?,"capabilities":["replace_tree","patch_subtree","speak","reflect","pin_observation","read_observation"],
            "limits":{"tree_nodes":64,"tree_depth":8,"children":8,"speech_queue":8,"trace_retention":TRACE_LIMIT,"evidence_lease_ms":EVIDENCE_LEASE_MS,"evidence_leases":4,"reflections":8},
            "patch_semantics":"Replace one node at a canonical path with NO leading slash. The whole tree is root; zero-based children are root/0, root/1, root/2. A guarded child is root/2/guard and a when child is root/2/when. Paths such as /2, /root/0 and root/children/0 are invalid. /guard and /when descend into the CHILD, not its condition; replace the enclosing guard node to change its condition. Repeating a condition inside the child keeps the old outer condition active. Reset cursors at/under patch; retain ancestor/sibling progress; interrupt active leaf only if inside patch; next update rechecks current guards"}),
        )
    }
    /// Subscription status is deliberately small and stable between commands.
    /// Fresh subjective state comes only from an atomic ReadObservation receipt.
    pub fn participant_status(&self, actor: u32) -> Result<Value, String> {
        serde_json::from_str(&self.participant_status_json(actor)?).map_err(|e|e.to_string())
    }
    /// Stream borrowed immutable read results directly. Building a Value tree
    /// here needlessly cloned every retained observation on every world save.
    pub fn participant_status_json(&self, actor: u32) -> Result<String, String> {
        self.participant_status_json_inner(actor, true)
    }
    /// Header-only private storage projection; the public API still includes reads.
    pub fn participant_status_header_json(&self, actor: u32) -> Result<String, String> {
        self.participant_status_json_inner(actor, false)
    }
    fn participant_status_json_inner(&self, actor: u32, include_reads: bool) -> Result<String, String> {
        #[derive(Serialize)]
        struct Status<'a> {#[serde(flatten)] head:Value, read_observations:Vec<CapturedRead<'a>>}
        if !self.participant_mode {return Err("legacy run has no participant-v1 contract".into());}
        let i=self.idx(actor)?;
        let s=self.participants.get(&actor).ok_or("character not provisioned")?;
        let head=json!({"api_version":API_VERSION,"projection":"status; use read_observation for fresh subjective state",
            "run":self.run,"actor":actor,"tick":self.tick,"stopped":self.stopped,
            "latest_cursor":s.cursor,"oldest_cursor":s.experiences.first().map(|e|e.cursor).unwrap_or(1),
            "control_epoch":s.control_epoch,"policy_revision":self.players[i].generation,"learning_revision":s.learning_revision,
            "context":{"player":{"health":self.players[i].health}},"receipts":s.receipts,
            "capabilities":["read_observation","replace_tree","patch_subtree","speak","reflect","pin_observation"]
        });
        let read_observations=s.evidence_leases.iter().filter(|l|include_reads && l.expires_ms>=self.timing.time_ms && l.observation.is_capture()).map(captured_read).collect::<Result<Vec<_>,_>>()?;
        serde_json::to_string(&Status{head,read_observations}).map_err(|e|e.to_string())
    }
    pub fn change_control(&mut self, actor: u32) -> Result<(), String> {
        let i = self.idx(actor)?;
        if !self.participant_mode {
            return Ok(());
        }
        self.participants.entry(actor).or_default().control_epoch += 1;
        self.participants.get_mut(&actor).unwrap().evidence_leases.clear();
        let id = self.event(
            Some(actor),
            "control_changed",
            vec![],
            json!({"epoch":self.participants[&actor].control_epoch}),
        );
        // Ownership changes invalidate slow work, not the already installed fast behavior.
        let _ = (i, id);
        self.cancel_speech(actor, "control changed");
        Ok(())
    }
    /// Bevy's finite manual action convenience uses the same capability validation/executor.
    /// It is not the agent interface; agents use persistent tree commands.
    pub fn participant_manual(&mut self, actor: u32, d: Decision) -> Result<(), String> {
        if !self.participant_mode {
            return Err("not a participant run".into());
        }
        if !d.reflections.is_empty() {
            return Err("learning must be submitted independently".into());
        }
        let i = self.idx(actor)?;
        let cause = self.event(
            Some(actor),
            "participant_command",
            vec![],
            json!({"source":"manual Bevy intent","reason":d.reason}),
        );
        self.apply_decision(
            actor,
            self.players[i].controller.clone(),
            d,
            Some(cause),
            None,
        )
    }
    pub fn participant_apply(&mut self, actor: u32, request: Request) -> Result<Receipt, String> {
        if !self.participant_mode {
            return Err("participant-v1 requires a participant run".into());
        }
        self.idx(actor)?;
        let bytes = serde_json::to_vec(&request).map_err(|e| e.to_string())?;
        if bytes.len() > 50_000 || request.request_id.is_empty() || request.request_id.len() > 100 {
            return Err("invalid request size/id".into());
        }
        let fingerprint = format!("{:x}", Sha256::digest(&bytes));
        if let Some(old) = self.participants[&actor]
            .receipts
            .iter()
            .find(|r| r.request_id == request.request_id)
        {
            return if old.fingerprint == fingerprint {
                Ok(old.clone())
            } else {
                Err("request ID reused with different content".into())
            };
        }
        // Clone/commit gives all-or-nothing updates, including multi-reflection validation and patch cursors.
        let mut candidate = self.clone();
        let result = candidate.apply_participant_inner(actor, &request);
        let (event, error) = match result {
            Ok(id) => {
                candidate.wake(actor);
                *self = candidate;
                (id, None)
            }
            Err(error) => {
                let id = self.event(
                    Some(actor),
                    "participant_rejected",
                    vec![],
                    json!({"request_id":request.request_id,"error":error}),
                );
                (id, Some(error))
            }
        };
        let receipt = Receipt {
            request_id: request.request_id,
            fingerprint,
            ok: error.is_none(),
            error,
            event,
        };
        let s = self.participants.get_mut(&actor).unwrap();
        s.receipts.push(receipt.clone());
        if s.receipts.len() > 64 {
            s.receipts.remove(0);
        }
        Ok(receipt)
    }
    fn apply_participant_inner(&mut self, actor: u32, request: &Request) -> Result<u64, String> {
        let i = self.idx(actor)?;
        if request.api_version != API_VERSION {
            return Err("unsupported participant API version".into());
        }
        if self.participants[&actor].control_epoch != request.control_epoch {
            return Err("stale control epoch".into());
        }
        if self.stopped || self.players[i].health <= 0 {
            return Err("character dead or run stopped".into());
        }
        let cause=self.event(Some(actor),"participant_command",vec![],json!({"request_id":request.request_id,"command":request.command,"control_epoch":request.control_epoch}));
        match &request.command {
            Command::ReadObservation { after, limit } => {
                let latest = self.participants[&actor].cursor;
                if *after > latest { return Err("cursor ahead of character trace".into()); }
                let limit = (*limit).clamp(1, 128);
                // Initial reads show the newest page. Incremental reads preserve cursor order.
                let start = if *after == 0 { latest.saturating_sub(limit as u64) } else { *after };
                let mut observation = self.participant_snapshot_inner(actor, start, limit, false)?;
                observation.as_object_mut().unwrap().remove("read_observations");
                let experiences: Vec<Experience> = serde_json::from_value(observation.as_object_mut().unwrap().remove("experiences").unwrap())
                    .map_err(|_| "invalid observation projection")?;
                observation["gap"] = json!(experiences.first().is_some_and(|e| e.cursor > after.saturating_add(1)));
                observation["evidence_lease"] = json!({"observed_cursor":latest,"duration_ms":EVIDENCE_LEASE_MS,"atomic":true});
                observation["limits"]["read_page"] = json!(128);
                let s = self.participants.get_mut(&actor).unwrap();
                s.evidence_leases.retain(|l| l.expires_ms >= self.timing.time_ms);
                s.evidence_leases.push(EvidenceLease { request_id: request.request_id.clone(), observation:serde_json::value::to_raw_value(&observation).map_err(|e|e.to_string())?.into(),
                    observed_cursor: latest, expires_ms: self.timing.time_ms.saturating_add(EVIDENCE_LEASE_MS), experiences:Arc::new(experiences) });
                if s.evidence_leases.len() > 4 { s.evidence_leases.remove(0); }
            }
            Command::PinObservation { observed_cursor, sources } => {
                let s = self.participants.get_mut(&actor).unwrap();
                if *observed_cursor > s.cursor || sources.len() > TRACE_LIMIT {
                    return Err("invalid evidence lease cursor/size".into());
                }
                let mut seen = std::collections::BTreeSet::new();
                let mut experiences = Vec::new();
                for source in sources {
                    if !seen.insert(*source) { return Err("duplicate evidence source".into()); }
                    let e = s.experiences.iter().find(|e| e.source == *source && e.cursor <= *observed_cursor)
                        .ok_or("observation advanced before evidence could be pinned; refresh")?;
                    experiences.push(e.clone());
                }
                s.evidence_leases.retain(|l| l.expires_ms >= self.timing.time_ms && l.observed_cursor != *observed_cursor);
                s.evidence_leases.push(EvidenceLease { request_id: request.request_id.clone(), observation: empty_observation(), observed_cursor: *observed_cursor,
                    expires_ms: self.timing.time_ms.saturating_add(EVIDENCE_LEASE_MS), experiences:Arc::new(experiences) });
                if s.evidence_leases.len() > 4 { s.evidence_leases.remove(0); }
            }
            Command::ReplaceTree {
                expected_revision,
                reason,
                tree,
            } => {
                if *expected_revision != self.players[i].generation {
                    return Err("stale policy revision".into());
                }
                self.apply_decision(
                    actor,
                    self.players[i].controller.clone(),
                    Decision {
                        reason: reason.clone(),
                        policy: Some(tree.clone()),
                        actions: vec![],
                        reflections: vec![],
                    },
                    Some(cause),
                    None,
                )?;
            }
            Command::PatchSubtree {
                expected_revision,
                reason,
                path,
                subtree,
            } => {
                if *expected_revision != self.players[i].generation {
                    return Err("stale policy revision".into());
                }
                let mut e = self.players[i]
                    .execution
                    .clone()
                    .ok_or("no installed tree")?;
                let mut tree = e
                    .policy
                    .clone()
                    .ok_or("legacy sequence cannot be patched")?;
                let parts: Vec<_> = path.split('/').collect();
                if parts.first() != Some(&"root") || parts.len() > 9 {
                    return Err("invalid subtree path".into());
                }
                replace_at(&mut tree, &parts[1..], subtree.clone())?;
                let d = Decision {
                    reason: reason.clone(),
                    policy: Some(tree.clone()),
                    actions: vec![],
                    reflections: vec![],
                };
                self.validate(i, &d, &self.players[i].memories)?;
                for action in tree.validate_with_map(&self.scripts, self.map_for_actor(actor).as_ref())? {
                    if let Some(target) = action.target {
                        if !self.target_perceived(i, target, &self.players[i].memories) {
                            return Err("target not perceived".into());
                        }
                    }
                }
                if e.state
                    .active_path
                    .as_ref()
                    .is_some_and(|p| within(p, path))
                {
                    self.interrupt(i, cause, "subtree patched");
                    e.attempt = None;
                    e.remaining = 0;
                    e.state.active_path = None;
                    e.state.status = Status::Interrupted;
                }
                e.state.cursors.retain(|p, _| !within(p, path));
                e.state.branches.retain(|p, _| !within(p, path));
                e.state.entries.retain(|p| !within(p, path));
                // Replacing a completed once subtree (or its child) explicitly
                // re-arms that intent; unrelated patches preserve completion.
                e.state.once_completed.retain(|p| !within(p,path) && !within(path,p));
                e.policy = Some(tree);
                e.decision = cause;
                self.players[i].execution = Some(e);
                self.players[i].generation += 1;
                self.event(
                    Some(actor),
                    "policy_patched",
                    vec![cause],
                    json!({"path":path,"revision":self.players[i].generation,"reason":reason}),
                );
            }
            Command::Speak { text, expires_tick } => {
                let error: String = self.scripts.law(
                    "validate_dialogue",
                    json!({"text":text,"expires_tick":expires_tick,"tick":self.tick}),
                )?;
                if !error.is_empty() {
                    return Err(error);
                }
                self.validate_scoped_action(i,&Action::say(text))?;
                if self.participants[&actor].speech.len() >= 8 {
                    return Err("speech queue full".into());
                }
                self.participants
                    .get_mut(&actor)
                    .unwrap()
                    .speech
                    .push(QueuedSpeech {
                        cause,
                        text: text.clone(),
                        expires_tick: *expires_tick,
                        execution: None,
                    });
                self.event(
                    Some(actor),
                    "speech_queued",
                    vec![cause],
                    json!({"text":text,"expires_tick":expires_tick}),
                );
            }
            Command::Reflect {
                expected_revision,
                observed_cursor,
                reflections,
                goal,
            } => {
                let s = &self.participants[&actor];
                if *expected_revision != s.learning_revision {
                    return Err("stale learning revision".into());
                }
                if *observed_cursor > s.cursor || reflections.is_empty() || reflections.len() > 8 {
                    return Err("invalid reflection batch/cursor".into());
                }
                if goal
                    .as_ref()
                    .is_some_and(|g| g.trim().is_empty() || g.len() > 1000)
                {
                    return Err("invalid goal".into());
                }
                let mut sources = std::collections::BTreeSet::new();
                let mut evidence = vec![];
                for r in reflections {
                    if !sources.insert(r.source) || s.learned_sources.contains(&r.source) {
                        return Err(
                            "experience already interpreted in an accepted reflection".into()
                        );
                    }
                    let e = s
                        .experiences
                        .iter()
                        .find(|e| e.source == r.source && e.cursor <= *observed_cursor)
                        .or_else(|| s.evidence_leases.iter()
                            .filter(|l| l.observed_cursor == *observed_cursor && l.expires_ms >= self.timing.time_ms)
                            .flat_map(|l| l.experiences.iter()).find(|e| e.source == r.source))
                        .ok_or("source not in supplied retained character trace")?;
                    let (from, location) = if e.kind == "perception" {
                        (
                            e.data["from"].as_u64().map(|n| n as u32),
                            e.data["location"]
                                .as_i64()
                                .unwrap_or(self.players[i].position as i64)
                                as i32,
                        )
                    } else {
                        (None, e.location)
                    };
                    if !matches!(
                        e.kind.as_str(),
                        "perception"
                            | "skill_result"
                            | "skill_progress"
                            | "action_interrupted"
                            | "behavior_interrupted"
                            | "speech_cancelled"
                    ) {
                        return Err("source is not an experienced observation/outcome".into());
                    }
                    if r.trust_delta != 0 && from.is_none() {
                        return Err("trust update requires a perceived counterpart".into());
                    }
                    if r.belief.as_ref().is_some_and(|b| {
                        self.players[i]
                            .beliefs
                            .iter()
                            .any(|k| k.claim.location == b.location && k.source > r.source)
                    }) {
                        return Err("newer subjective evidence retained".into());
                    }
                    evidence.push(Percept {
                        source: r.source,
                        tick: e.tick,
                        kind: e.kind.clone(),
                        from,
                        location,
                        content: (*e.data).clone(),
                    });
                }
                let d = Decision {
                    reason: "independent interpretation".into(),
                    policy: None,
                    actions: vec![Action::new(Skill::Wait)],
                    reflections: reflections.clone(),
                };
                self.validate(i, &d, &evidence)?;
                let before = json!({"caution":self.players[i].caution,"relationships":self.players[i].relationships,"beliefs":self.players[i].beliefs,"knowledge":self.players[i].knowledge,"goal":self.players[i].current_goal});
                for r in reflections {
                    let source = evidence
                        .iter()
                        .find(|e| e.source == r.source)
                        .ok_or("validated reflection source missing")?;
                    self.reflect_identity(i, r, source)?;
                    self.participants
                        .get_mut(&actor)
                        .unwrap()
                        .learned_sources
                        .push(r.source);
                }
                if let Some(goal) = goal {
                    self.players[i].current_goal = Some(goal.clone());
                }
                let valid: Vec<u64> = self.participants[&actor]
                    .experiences
                    .iter()
                    .chain(self.participants[&actor].evidence_leases.iter()
                        .filter(|l| l.expires_ms >= self.timing.time_ms).flat_map(|l| l.experiences.iter()))
                    .map(|e| e.source)
                    .collect();
                self.participants
                    .get_mut(&actor)
                    .unwrap()
                    .learned_sources
                    .retain(|id| valid.contains(id));
                self.event(Some(actor),"identity_change",std::iter::once(cause).chain(sources).collect(),json!({"reflections":reflections,"before":before,"after":{"caution":self.players[i].caution,"relationships":self.players[i].relationships,"beliefs":self.players[i].beliefs,"knowledge":self.players[i].knowledge,"goal":self.players[i].current_goal}}));
            }
        }
        Ok(cause)
    }
    pub(super) fn cancel_speech(&mut self, actor: u32, reason: &str) {
        if self.participants.get(&actor).is_some_and(|s| s.speech.is_empty()) { return; }
        let queued = std::mem::take(&mut self.participants.entry(actor).or_default().speech);
        for q in queued {
            self.event(
                Some(actor),
                "speech_cancelled",
                vec![q.cause],
                json!({"reason":reason}),
            );
        }
    }
    pub(super) fn deliver_queued_speech(&mut self) -> Result<(), String> {
        if !self.participant_mode {
            return Ok(());
        }
        for i in 0..self.players.len() {
            let actor = self.players[i].id;
            if self.stopped || self.players[i].health <= 0 {
                self.cancel_speech(actor, "character dead or run stopped");
                continue;
            }
            // One utterance per character per tick, after movement/consequences. FIFO with explicit expiry.
            let expired: Vec<_> = self.participants[&actor]
                .speech
                .iter()
                .filter(|q| q.expires_tick < self.tick)
                .cloned()
                .collect();
            if !expired.is_empty() {
                self.participants.get_mut(&actor).unwrap().speech.retain(|q| q.expires_tick >= self.tick);
            }
            for q in expired {
                self.event(
                    Some(actor),
                    "speech_cancelled",
                    vec![q.cause],
                    json!({"reason":"expired before delivery"}),
                );
            }
            if self.participants[&actor].last_speech_tick == Some(self.timing.updates) {
                continue;
            }
            if !self.participants[&actor].speech.is_empty() {
                let mut q = self.participants.get_mut(&actor).unwrap().speech.remove(0);
                let action = Action::say(&q.text);
                let mut execution = q.execution.take().unwrap_or_else(|| Execution {
                    dialogue: true,
                    decision: q.cause,
                    tree: Behavior::Action(action.clone()),
                    cursor: 0,
                    attempt: None,
                    remaining: 0,
                    script: None,
                    policy: None,
                    state: PolicyState::default(),
                });
                // Dialogue has its own continuation; preserve the independent behavior policy.
                let policy = self.players[i].execution.clone();
                let status = self.execute_action(i, &mut execution, action);
                self.players[i].execution = policy;
                if status == Status::Running {
                    q.execution = Some(execution);
                    self.participants
                        .get_mut(&actor)
                        .unwrap()
                        .speech
                        .insert(0, q);
                }
            }
        }
        Ok(())
    }
    pub(super) fn emit_speech(&mut self, i: usize, cause: u64, text: &str) -> Result<(), String> {
        let pos = self.players[i].position;
        let actor = self.players[i].id;
        if self.participant_mode {
            self.participants.get_mut(&actor).unwrap().last_speech_tick = Some(self.timing.updates);
        }
        let event = self.event(
            Some(actor),
            "speech",
            vec![cause],
            json!({"text":text,"position":pos}),
        );
        for j in 0..self.players.len() {
            if self.visible(j, i, "speech")? {
                self.perceive(
                    j,
                    event,
                    "speech",
                    Some(actor),
                    pos,
                    json!({"text":text,"speaker":self.players[i].name}),
                )?;
                self.request(j, "heard free-form speech");
            }
        }
        Ok(())
    }
}

/// Shared semantics available to every controller; describes machinery without choosing a policy.
pub fn state_contract() -> Value {
    json!({
        "resources": {
            "health":"0 means dead; 100 means full health. Death is permanent.",
            "hunger":"0 means fully fed; 100 means starving. Hunger INCREASES with time. Eating DECREASES hunger, so a HIGH hunger value means greater need for food, not greater fullness.",
            "energy":"0 means exhausted; 100 means fully rested. Actions may require energy and rest restores it.",
            "food":"Number of carried food units, not food visible at a site. An eat attempt requires at least one carried unit. Eating and resting are allowed at ANY position, including roads and the thicket; shelter only improves rest and protects from cold. Moving to shelter itself requires energy."
        },
        "behavior_execution": {
            "once":"Runs its child until first success, then returns failure on later visits so priority can choose other work. Completion persists across cycles and reload until the subtree or its child is explicitly replaced. Failed children may retry; preemption does not complete them.",
            "when":"Entry condition: checks its condition only before starting the child. Once started, a running child continues even if that condition changes. Completion, failure, replacement or a false enclosing continuous guard ends this commitment. A higher-priority branch suspends it; its entry condition and sequence progress are retained so it can resume afterward. The currently executing skill can restart on resumption. Use this node when the condition describes when a task may START, and guard when it must remain true throughout the task.",
            "guard":"Continuously rechecked while its child runs. It is not just an entry prerequisite. If it becomes false, the child branch and its sequence progress are abandoned. A condition that changes as a direct consequence of the child can therefore interrupt that child.",
            "sequence":"Runs children in order. Progress persists while the branch remains active. Failure or a false enclosing continuous guard clears its progress. Switching to a higher-priority branch suspends this sequence and retains its cursor; when selected again it resumes the unfinished child.",
            "priority":"Checks higher-priority branches again on each evaluation. A newly eligible higher branch can interrupt the current skill in a lower branch. Lower sequence cursors and when commitments remain suspended for later resumption; they are not silently restarted.",
            "repetition":"The root repeats. A successful action may execute again on later cycles. Completing move while already at its destination makes no displacement.",
            "knowledge":"Your knowledge holds attributed reports, not global truth or automatic skill mastery. has_knowledge checks your own record ID. Teach/record/consult/reread_record/destroy_archive are ordinary timed physical skills using target/record/archive arguments from their contracts. Site observations list local archive catalogs only; consult to read contents. An acquisition source can age out of the retained trace while your durable copy remains. Use reread_record with your own record ID (1500 ms and 1 energy) to create fresh personally citable knowledge_report evidence, then reflect on its new source. Rereading preserves the record identity, origin, ownership, number of copies and existing interpretation; executable source still requires its explicit terminal inspection. reflect assesses the cited report when you still hold its copy. It may also include knowledge:{topic,text,location,confidence} to create a new assertion citing that same own evidence; null knowledge makes no new assertion. Derived assertions never copy executable code or paid experiment proof. Preserve uncertainty and conflicting reports. A reported location can support a later locational belief. Copy lineage points to evidence but cannot recover destroyed content from audit history.",
            "independent_operations":"Speech and reflection do not replace the running behavior tree. A reflection alone does not alter the tree; later behavior authoring can apply the lesson."
        },
        "weather":"If weather_forecast is present, cold begins at cold_after_ms and causes damage_per_pulse each exposure pulse (2500 ms in the bundled law) at cells with less than shelter_required. Shelter belongs to the site and protects every occupant; food and shelter remain independent resources.",
        "food_supply":"Site food is finite unless your direct site observation includes a food_source. That source produces amount units per interval_ms up to capacity under the bundled law; full sites discard production opportunities rather than banking them. A source does not fill carried inventory: gathering is still required. Production and deposits are distinct. Site observations may become stale; locations without an observed source must not be assumed to replenish. Shared shelter and food are usable by every occupant. Safe, supplied waiting can serve an intent; physical movement is not progress by itself.",
        "population":"Population actions require configured lifecycle facilities. Each new person has a distinct identity, empty inventory and private knowledge, a revisable newborn starter and ordinary independent controller enrollment. Biological reproduction requires two explicit matching offers; both pay quoted costs and the exact offers are consumed only at completion. Fabrication creates a nutrient-supported artificial body at a workshop, not an obedient copy. A dependent can move, observe, speak, rest, eat supplied food, learn and perform guided practice, but cannot gather/build/create independently. Care consumes a real caregiver meal and records support. Guided practice requires a personally interpreted report about the current cell and a local prior caregiver, and actually gathers food. Default self-support requires 60000ms age, two care meals and one practice. Receiving a report or waiting alone grants no practical capability. Lifecycle site observations expose local body needs and offers addressed to you, never others’ private knowledge; needs_care uses retained observations. Inspect current skill definitions and your own development rather than assuming that a child is already capable. Artificial bodies in this representative slice use food; charging and compute are separate mechanics.",
        "social_skills":"Giving transfers carried food to a colocated perceived person. Deposits transfer it to a site anyone can gather from. Building permanently raises local shared shelter. These operations do not compel another character to cooperate or create agreements automatically.",
        "perception":"Terrain is surveyed. site_observations retains the latest direct observation at up to 64 visited cells, independently of the short recent-memory list. Observations may become stale; food_at reads this retained observation, false if unknown. Atomic reads capture up to 128 experiences and their context together, then retain that evidence for 330000 simulation ms (at most four concurrent reads); learning still checks control and learning revisions. A remembered resource at another cell does not make it available at your current position. Speech is a report, not a world-state change."
    })
}
