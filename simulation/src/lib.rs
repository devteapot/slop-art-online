//! The authoritative M1 rules, invoked by SpacetimeDB reducers and unit tests.
//! No I/O, wall clock, model calls, or second approximation of world rules.
pub mod client_view;
pub mod participant;
use bonsai_bt::Behavior;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;

pub const VERSION: &str = "m1-5";
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
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Action {
    pub skill: Skill,
    #[serde(default)]
    pub destination: Option<i32>,
    #[serde(default)]
    pub target: Option<u32>,
    #[serde(default)]
    pub text: Option<String>,
    #[serde(default = "one")]
    #[cfg_attr(feature = "schema", schemars(range(min = 1, max = 5)))]
    pub duration: u32,
}
fn one() -> u32 {
    1
}
impl Action {
    pub fn new(skill: Skill) -> Self {
        Self {
            skill,
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
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Belief {
    pub location: i32,
    pub danger: bool,
    pub text: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Known {
    pub claim: Belief,
    pub source: u64,
    pub confidence: i32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
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
    pub decision: u64,
    pub tree: Behavior<Action>,
    pub cursor: usize,
    pub attempt: Option<u64>,
    pub remaining: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub policy: Option<Node>,
    #[serde(default, skip_serializing_if = "PolicyState::is_default")]
    pub state: PolicyState,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Player {
    pub id: u32,
    pub name: String,
    pub controller: Controller,
    pub motive: String,
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
    pub beliefs: Vec<Known>,
    #[serde(default)]
    pub relationships: BTreeMap<u32, i32>,
    #[serde(default)]
    pub memories: Vec<Percept>,
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
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Scenario {
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
    pub data: Value,
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
    pub initial: Scenario,
    pub tick: u64,
    pub players: Vec<Player>,
    pub sites: Vec<Site>,
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
        if scenario.players.is_empty()
            || scenario.players.len() > 16
            || scenario.max_ticks == 0
            || scenario.max_ticks > 10000
        {
            return Err("scenario needs 1..16 players and 1..10000 ticks".into());
        }
        let mut ids = std::collections::BTreeSet::new();
        for p in &scenario.players {
            if !ids.insert(p.id)
                || p.health <= 0
                || p.health > 100
                || !(-10..=10).contains(&p.position)
                || !(0..=100).contains(&p.hunger)
                || !(0..=100).contains(&p.energy)
                || !(0..=100).contains(&p.caution)
                || !(0..=100).contains(&p.empathy)
                || !(0..=100).contains(&p.introspection)
                || p.food < 0
                || p.food > 100
                || p.execution.is_some()
                || !p.memories.is_empty()
            {
                return Err("invalid initial player".into());
            }
        }
        let mut locations = std::collections::BTreeSet::new();
        for s in &scenario.sites {
            if !locations.insert(s.position)
                || !(-10..=10).contains(&s.position)
                || s.food < 0
                || s.food > 100
                || !(0..=100).contains(&s.hazard)
            {
                return Err("invalid site".into());
            }
        }
        let mut w = Self {
            run,
            version: VERSION.into(),
            players: scenario.players.clone(),
            sites: scenario.sites.clone(),
            initial: scenario,
            tick: 0,
            pending: vec![],
            next_event: 1,
            stopped: false,
            request_ids: vec![],
            participant_mode: false,
            participants: BTreeMap::new(),
            events: vec![],
        };
        let id=w.event(None,"initialization",vec![],json!({"scenario":w.initial,"rules":VERSION,"prompt":PROMPT,"seed_usage":"reserved; current world rules use no random draws"}));
        for i in 0..w.players.len() {
            w.players[i].last_cause = Some(id);
            // Authored starting knowledge is a remembered prior report, not a
            // reference to the observer's omniscient initialization payload.
            for n in 0..w.players[i].beliefs.len() {
                let claim = w.players[i].beliefs[n].claim.clone();
                let source = w.perceive(
                    i,
                    id,
                    "prior_report",
                    None,
                    claim.location,
                    json!({"claim":claim}),
                );
                w.players[i].beliefs[n].source = source;
            }
            w.observe_site(i);
        }
        Ok(w)
    }
    pub fn event(&mut self, actor: Option<u32>, kind: &str, parents: Vec<u64>, data: Value) -> u64 {
        let id = self.next_event;
        self.next_event += 1;
        self.events.push(Event {
            id,
            run: self.run.clone(),
            tick: self.tick,
            actor,
            kind: kind.into(),
            parents,
            data,
        });
        self.record_experience(&self.events.last().unwrap().clone());
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
    ) -> u64 {
        let id = self.event(
            Some(self.players[i].id),
            "perception",
            vec![world_event],
            json!({"kind":kind,"from":from,"location":location,"content":content}),
        );
        self.players[i].memories.push(Percept {
            source: id,
            tick: self.tick,
            kind: kind.into(),
            from,
            location,
            content,
        });
        if self.players[i].memories.len() > 16 {
            self.players[i].memories.remove(0);
        }
        self.players[i].last_cause = Some(id);
        id
    }
    fn observe_site(&mut self, i: usize) {
        if self.players[i].health <= 0 {
            return;
        }
        let pos = self.players[i].position;
        // Food is visible; hazard is learned through actual experience or a report.
        let food = self
            .sites
            .iter()
            .find(|s| s.position == pos)
            .map(|s| s.food)
            .unwrap_or(0);
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
        self.perceive(i, id, "site", None, pos, json!({"food":food}));
        let visible: Vec<_> = self
            .players
            .iter()
            .filter(|p| p.id != self.players[i].id && p.health > 0 && (p.position - pos).abs() <= 1)
            .map(|p| (p.id, p.name.clone(), p.position))
            .collect();
        for (other, name, location) in visible {
            self.perceive(
                i,
                id,
                "seen_player",
                Some(other),
                location,
                json!({"name":name,"position":location}),
            );
        }
    }
    pub fn context(&self, i: usize) -> Value {
        // Deliberate allowlist. Never serialize World, sites, other minds or audit into a prompt.
        let p = &self.players[i];
        let approach = p.execution.as_ref().map(|e| if let Some(policy)=&e.policy {json!({"decision":e.decision,"policy":policy,"state":e.state,"active_attempt":e.attempt})} else {json!(e)});
        json!({"player":{"id":p.id,"name":p.name,"role":p.role,"motive":p.motive,"position":p.position,"health":p.health,"hunger":p.hunger,"energy":p.energy,"food":p.food,"personality":{"caution":p.caution,"empathy":p.empathy,"introspection":p.introspection},"fear":p.fear,"beliefs":p.beliefs,"relationships":p.relationships,"memories":p.memories,"failures":p.failures,"current_approach":approach},"simulation_tick":self.tick,"skills":["move","gather","eat","rest","wait","speak","attack"]})
    }
    pub fn request(&mut self, i: usize, trigger: &str) {
        if self.participant_mode { return; }
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
            policy.validate()?
        } else {
            vec![]
        };
        for a in d.actions.iter().chain(policy_actions.iter().copied()) {
            if (a.skill != Skill::Move && a.destination.is_some())
                || (a.skill != Skill::Attack && a.target.is_some())
                || (a.skill != Skill::Speak && a.text.is_some())
            {
                return Err("skill contains arguments for a different skill".into());
            }
            if a.duration < 1 || a.duration > 5 {
                return Err("duration must be 1..5".into());
            }
            match a.skill {
                Skill::Move => {
                    if !a.destination.is_some_and(|x| (-10..=10).contains(&x)) {
                        return Err("invalid destination".into());
                    }
                }
                Skill::Speak => {
                    if a.text
                        .as_ref()
                        .is_none_or(|t| t.trim().is_empty() || t.chars().count() > 1000)
                    {
                        return Err("speech must contain 1..1000 characters".into());
                    }
                }
                Skill::Attack => {
                    if a.target.is_none() || a.target == Some(self.players[i].id) {
                        return Err("attack requires another target".into());
                    }
                }
                _ => {}
            }
        }
        let p = &self.players[i];
        for r in &d.reflections {
            let source = evidence
                .iter()
                .find(|m| m.source == r.source)
                .ok_or("reflection source not in remembered perceptions")?;
            if r.interpretation.trim().is_empty()
                || r.interpretation.len() > 2000
                || !(-10..=10).contains(&r.caution_delta)
                || !(-10..=10).contains(&r.trust_delta)
            {
                return Err("invalid interpretation/delta".into());
            }
            if let Some(b) = &r.belief {
                if b.text.len() > 1000
                    || (!p.beliefs.iter().any(|k| k.claim.location == b.location)
                        && b.location != source.location)
                {
                    return Err("belief location is not known".into());
                }
            }
        }
        Ok(())
    }
    fn interrupt(&mut self, i: usize, cause: u64, reason: &str) {
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
        if self.participant_mode { return Err("use actor-scoped participant commands".into()); }
        self.apply_decision(actor, controller, d, parent, None)
    }
    fn apply_decision(
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
        let evidence = remembered.unwrap_or_else(|| self.players[i].memories.clone());
        self.validate(i, &d, &evidence)?;
        // AI targets must be perceived, not guessed from observer IDs.
        {
            let policy_actions = d
                .policy
                .as_ref()
                .map(|p| p.validate())
                .transpose()?
                .unwrap_or_default();
            for a in d.actions.iter().chain(policy_actions.iter().copied()) {
                if let Some(target) = a.target {
                    if !evidence.iter().any(|m| m.from == Some(target)) {
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
            let from = evidence
                .iter()
                .find(|m| m.source == r.source)
                .and_then(|m| m.from);
            self.players[i].caution = (self.players[i].caution + r.caution_delta).clamp(0, 100);
            if let Some(from) = from {
                let entry = self.players[i].relationships.entry(from).or_default();
                *entry = (*entry + r.trust_delta).clamp(-100, 100);
            }
            if let Some(b) = &r.belief {
                self.players[i]
                    .beliefs
                    .retain(|k| k.claim.location != b.location);
                self.players[i].beliefs.push(Known {
                    claim: b.clone(),
                    source: r.source,
                    confidence: 60,
                });
            }
            self.event(Some(actor),"identity_change",vec![id,r.source],json!({"interpretation":r.interpretation,"before":{"caution":before.caution,"beliefs":before.beliefs,"relationships":before.relationships},"after":{"caution":self.players[i].caution,"beliefs":self.players[i].beliefs,"relationships":self.players[i].relationships}}));
        }
        self.players[i].generation += 1;
        self.players[i].execution = Some(Execution {
            decision: id,
            tree: Behavior::Sequence(d.actions.into_iter().map(Behavior::Action).collect()),
            cursor: 0,
            attempt: None,
            remaining: 0,
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
        if self.participant_mode { return Err("legacy model-result route disabled for participant runs".into()); }
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
    fn fallback(&mut self, i: usize) {
        let p = &self.players[i];
        let action = if p.food > 0 && p.hunger >= 25 {
            Action::new(Skill::Eat)
        } else if p.energy < 35 {
            Action::new(Skill::Rest)
        } else {
            Action::new(Skill::Wait)
        };
        let id=self.event(Some(p.id),"decision",p.last_cause.into_iter().collect(),json!({"controller":"authored_bootstrap","reported_explanation":"Minimal eat/rest/wait while awaiting an installed policy","context":self.context(i),"actions":[action],"behavior_version":VERSION}));
        self.players[i].execution = Some(Execution {
            decision: id,
            tree: Behavior::Sequence(vec![Behavior::Action(action)]),
            cursor: 0,
            attempt: None,
            remaining: 0,
            policy: None,
            state: PolicyState::default(),
        });
    }
    fn fail(&mut self, i: usize, attempt: u64, reason: &str) -> Status {
        let id = self.event(
            Some(self.players[i].id),
            "skill_result",
            vec![attempt],
            json!({"status":"failed","reason":reason}),
        );
        self.perceive(
            i,
            id,
            "failure",
            None,
            self.players[i].position,
            json!({"reason":reason}),
        );
        self.players[i].failures += 1;
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
    fn execute_action(&mut self, i: usize, e: &mut Execution, a: Action) -> Status {
        let actor = self.players[i].id;
        let attempt = if let Some(id) = e.attempt {
            id
        } else {
            let id=self.event(Some(actor),"skill_attempt",std::iter::once(e.decision).chain(e.state.last_guard).collect(),json!({"action":a,"step":e.cursor,"node_path":e.state.active_path,"skill_version":VERSION,"before":{"position":self.players[i].position,"food":self.players[i].food,"energy":self.players[i].energy,"hunger":self.players[i].hunger}}));
            e.attempt = Some(id);
            e.remaining = a.duration;
            id
        };
        self.players[i].execution = Some(e.clone());
        let pos = self.players[i].position;
        match a.skill {
            Skill::Move => {
                let dest = a.destination.unwrap();
                if self.players[i].energy < 1 {
                    e.attempt = None;
                    return self.fail(i, attempt, "exhausted");
                }
                self.players[i].position += (dest - pos).signum();
                self.players[i].energy -= 1;
                self.observe_site(i);
                if self.players[i].position != dest {
                    self.event(
                        Some(actor),
                        "skill_progress",
                        vec![attempt],
                        json!({"position":self.players[i].position}),
                    );
                    return Status::Running;
                }
            }
            Skill::Gather => {
                let site = self
                    .sites
                    .iter()
                    .position(|s| s.position == pos && s.food > 0);
                if site.is_none() || self.players[i].energy < 4 {
                    e.attempt = None;
                    return self.fail(i, attempt, "no food here or insufficient energy");
                }
                self.sites[site.unwrap()].food -= 1;
                self.players[i].food += 1;
                self.players[i].energy -= 4;
                self.event(Some(actor),"resource_change",vec![attempt],json!({"location":pos,"food_delta":-1,"food_after":self.sites[site.unwrap()].food}));
                self.observe_site(i);
            }
            Skill::Eat => {
                if self.players[i].food <= 0 {
                    e.attempt = None;
                    return self.fail(i, attempt, "no carried food");
                }
                self.players[i].food -= 1;
                self.players[i].hunger = (self.players[i].hunger - 35).max(0);
            }
            Skill::Rest => {
                self.players[i].energy = (self.players[i].energy + 12).min(100);
            }
            Skill::Wait => {}
            Skill::Speak => {
                if self.participant_mode && self.participants[&actor].last_speech_tick==Some(self.tick){return Status::Running;}
                self.emit_speech(i, attempt, a.text.as_deref().unwrap());
            }
            Skill::Attack => {
                let target = a.target.and_then(|id| self.idx(id).ok());
                if target.is_none() || self.players[i].energy < 8 {
                    e.attempt = None;
                    return self.fail(i, attempt, "target unavailable or insufficient energy");
                }
                let j = target.unwrap();
                if self.players[j].health <= 0 || self.players[j].position != pos {
                    e.attempt = None;
                    return self.fail(i, attempt, "target dead or out of range");
                }
                self.players[i].energy -= 8;
                self.damage(j, 20, Some(actor), attempt, "attack");
            }
        }
        if matches!(a.skill, Skill::Rest | Skill::Wait) && e.remaining > 1 {
            e.remaining -= 1;
            self.players[i].execution = Some(e.clone());
            self.event(Some(actor),"skill_progress",vec![attempt],json!({"energy":self.players[i].energy,"remaining":self.players[i].execution.as_ref().unwrap().remaining}));
            return Status::Running;
        }
        let result=self.event(Some(actor),"skill_result",vec![attempt],json!({"status":"completed","skill":a.skill,"after":{"position":self.players[i].position,"food":self.players[i].food,"energy":self.players[i].energy,"hunger":self.players[i].hunger}}));
        self.perceive(
            i,
            result,
            "own_result",
            None,
            self.players[i].position,
            json!({"skill":a.skill,"status":"completed"}),
        );
        e.attempt = None;
        e.remaining = 0;
        Status::Success
    }
    fn damage(&mut self, i: usize, amount: i32, from: Option<u32>, cause: u64, nature: &str) {
        let before = self.players[i].clone();
        self.players[i].health = (before.health - amount).max(0);
        let world=self.event(Some(before.id),"damage",vec![cause],json!({"from":from,"amount":amount,"before":before.health,"after":self.players[i].health,"location":before.position,"cause_kind":nature}));
        let perception = self.perceive(
            i,
            world,
            if nature == "starvation" {
                "starvation"
            } else {
                "danger"
            },
            from,
            before.position,
            json!({"damage":amount,"cause":nature}),
        );
        self.players[i].fear = (before.fear + 15).min(100);
        self.players[i].caution = (before.caution + 1 + before.introspection / 25).min(100);
        if nature != "starvation" {
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
                confidence: 95,
            });
        }
        self.event(Some(before.id),"identity_change",vec![perception],json!({"interpretation":"experienced harm; personal introspection changes caution","before":{"caution":before.caution,"fear":before.fear,"beliefs":before.beliefs},"after":{"caution":self.players[i].caution,"fear":self.players[i].fear,"beliefs":self.players[i].beliefs}}));
        self.interrupt(i, world, "damage");
        self.players[i].failures += 1;
        self.request(i, "experienced harm; installed policy remains active");
        if self.players[i].health == 0 {
            self.players[i].generation += 1;
            let death = self.event(
                Some(before.id),
                "death",
                vec![world],
                json!({"name":before.name,"position":before.position,"permanent":true}),
            );
            for j in 0..self.players.len() {
                if j != i
                    && self.players[j].health > 0
                    && (self.players[j].position - before.position).abs() <= 1
                {
                    self.perceive(
                        j,
                        death,
                        "death",
                        Some(before.id),
                        before.position,
                        json!({"name":before.name}),
                    );
                }
            }
        }
    }
    pub fn step(&mut self) {
        if self.stopped {
            return;
        }
        self.tick += 1;
        for i in 0..self.players.len() {
            if self.players[i].health <= 0 {
                continue;
            }
            let before = self.players[i].hunger;
            self.players[i].hunger = (before + 2).min(100);
            self.players[i].fear = (self.players[i].fear - 1).max(0);
            let metabolism=self.event(Some(self.players[i].id),"needs_change",vec![],json!({"hunger_before":before,"hunger_after":self.players[i].hunger,"fear":self.players[i].fear}));

            if self.players[i].health <= 0 {
                continue;
            }
            let interval = 4 + (100 - self.players[i].introspection) as u64 / 10;
            if self.tick == 1 || (self.tick - self.players[i].last_reflection >= interval) {
                self.request(
                    i,
                    if self.players[i].failures > 0 {
                        "lack of progress / introspection"
                    } else {
                        "reconsider goals"
                    },
                );
            }
            if !self.participant_mode && self.players[i].controller == Controller::Ai && self.players[i].execution.is_none() {
                self.fallback(i);
            }
            self.execute(i);
            if self.players[i].hunger >= 100 {
                self.damage(i, 8, None, metabolism, "starvation");
            }
            if self.players[i].health <= 0 {
                continue;
            }
            let hazard = self
                .sites
                .iter()
                .find(|s| s.position == self.players[i].position)
                .map(|s| s.hazard)
                .unwrap_or(0);
            if hazard > 0 {
                let event = self.event(
                    None,
                    "environment_hazard",
                    self.players[i].last_cause.into_iter().collect(),
                    json!({"location":self.players[i].position,"damage":hazard}),
                );
                self.damage(i, hazard, None, event, "environment");
            }
        }
        self.deliver_queued_speech();
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
        if self.tick >= self.initial.max_ticks || self.players.iter().all(|p| p.health <= 0) {
            self.stopped = true;
            self.deliver_queued_speech();
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
    }
}

#[cfg(test)]
mod policy_tests;
#[cfg(test)]
mod tests;

#[cfg(feature = "schema")]
pub mod contract;

#[cfg(test)]
mod participant_tests;
