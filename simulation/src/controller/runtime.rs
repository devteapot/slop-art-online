//! Client-only decision state. This evaluator cannot advance the physical world.
use super::*;
use crate::participant::Experience;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Active {
    pub path: String,
    pub request_id: String,
    #[serde(default)]
    pub rejected: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum Dispatch {
    Start(Action),
    Cancel,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct JournalEntry {
    pub sequence: u64,
    pub kind: String,
    pub data: Value,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Runtime {
    pub version: String,
    pub run: String,
    pub actor: u32,
    pub player: Player,
    pub context: Value,
    pub tree: Option<Node>,
    pub state: PolicyState,
    pub policy_revision: u64,
    pub learning_revision: u64,
    #[serde(default)]
    pub knowledge_drafts: Vec<Reflection>,
    pub cursor: u64,
    pub active: Option<Active>,
    pub experiences: Vec<Experience>,
    pub learned_sources: BTreeSet<u64>,
    pub journal_sequence: u64,
    pub journal: Vec<JournalEntry>,
    pub reconsider: Option<String>,
    pub activity: participant::ParticipantState,
}
fn within(path: &str, root: &str) -> bool {
    path == root || path.starts_with(&format!("{root}/"))
}
impl Runtime {
    pub fn new(seed: &Bootstrap) -> Result<Self, String> {
        if seed.version != VERSION || seed.player.id != seed.actor { return Err("invalid controller bootstrap".into()); }
        let tree = seed.player.execution.as_ref().and_then(|e|e.policy.clone());
        let state = seed.player.execution.as_ref().map(|e|e.state.clone()).unwrap_or_default();
        let mut player = seed.player.clone();
        player.execution = None;
        Ok(Self { version: VERSION.into(), run:seed.run.clone(), actor:seed.actor,
            player, context:seed.context.clone(), tree, state,
            policy_revision:seed.player.generation, learning_revision:0, knowledge_drafts:vec![], cursor:0,
            active:None, experiences:vec![], learned_sources:BTreeSet::new(),
            journal_sequence:0, journal:vec![], reconsider:None, activity:Default::default() })
    }
    fn log(&mut self, kind: &str, data: Value) {
        self.journal_sequence += 1;
        self.journal.push(JournalEntry { sequence:self.journal_sequence,kind:kind.into(),data });
    }
    /// The caller durably appends these before truncating the in-memory journal.
    pub fn take_journal(&mut self) -> Vec<JournalEntry> { std::mem::take(&mut self.journal) }
    pub fn ingest(&mut self, e: Experience, laws: &scripting::Registry) -> Result<(), String> {
        if e.cursor <= self.cursor { return Ok(()); }
        if self.cursor != 0 && e.cursor != self.cursor + 1 { return Err("controller experience gap; recovery required".into()); }
        let time = e.data["time_ms"].as_u64().unwrap_or(e.tick * timing::LEGACY_UNIT_MS);
        participant::record_activity(&mut self.activity, &Event { id:e.source, run:self.run.clone(), tick:e.tick,
            actor:Some(self.actor), kind:e.kind.clone(),parents:e.parents.clone(),data:(*e.data).clone() }, time, e.location);
        if e.kind == "perception" {
            let p = Percept { source:e.source,tick:e.tick,kind:e.data["kind"].as_str().ok_or("perception kind missing")?.into(),
                from:e.data["from"].as_u64().and_then(|n|u32::try_from(n).ok()),location:e.location,
                content:e.data["content"].clone() };
            if p.kind == "site" {
                self.player.site_observations.retain(|old|old.location != p.location);
                self.player.site_observations.push(p.clone());
                if self.player.site_observations.len() > 64 { self.player.site_observations.remove(0); }
            }
            if matches!(p.kind.as_str(),"danger"|"starvation"|"power_depletion") {
                let outcome: Value = laws.law("on_damage",json!({"actor":scripting::facts(&self.player),
                    "amount":p.content["damage"],"nature":p.content["cause"]}))?;
                if let Some(c) = outcome["caution"].as_i64() { self.player.caution = c as i32; }
                if outcome["learn_danger"] == true {
                    self.player.beliefs.retain(|k|k.claim.location != p.location);
                    self.player.beliefs.push(Known { claim:Belief {location:p.location,danger:true,text:"I was hurt here".into()},
                        source:p.source,confidence:outcome["confidence"].as_i64().unwrap_or(0) as i32 });
                }
                self.log("experienced_harm",json!({"source":p.source,"caution":self.player.caution}));
            }
            // Initialization perceptions are also present in the immutable seed.
            self.player.memories.retain(|old|old.source != p.source);
            self.player.memories.push(p);
            let limit: usize = laws.law("memory_limit",json!({}))?;
            if limit > 256 { return Err("client memory budget exceeded".into()); }
            while self.player.memories.len() > limit { self.player.memories.remove(0); }
        }
        self.cursor = e.cursor;
        self.log("scoped_experience",json!(e));
        self.experiences.push(e);
        if self.experiences.len() > 256 { self.experiences.remove(0); }
        Ok(())
    }
    pub fn replace(&mut self, expected: u64, tree: Node, reason: &str) -> Result<(), String> {
        if expected != self.policy_revision { return Err("stale client policy revision".into()); }
        if reason.trim().is_empty() || reason.len() > 1000 { return Err("invalid policy reason".into()); }
        tree.validate()?;
        self.tree = Some(tree);
        self.reconsider = None;
        self.state = PolicyState::default();
        // Keep the old active request until the next tick replaces/cancels it.
        if let Some(a) = &mut self.active { a.path = "replaced".into(); }
        self.policy_revision += 1;
        self.log("policy_installed",json!({"revision":self.policy_revision,"reason":reason,"policy":self.tree}));
        Ok(())
    }
    pub fn patch(&mut self, expected: u64, path: &str, subtree: Node, reason: &str) -> Result<(), String> {
        if expected != self.policy_revision { return Err("stale client policy revision".into()); }
        if reason.trim().is_empty() || reason.len() > 1000 { return Err("invalid policy reason".into()); }
        let parts: Vec<_> = path.split('/').collect();
        if parts.first() != Some(&"root") { return Err("path must begin at root".into()); }
        let mut tree = self.tree.clone().ok_or("no installed client policy")?;
        participant::replace_at(&mut tree,&parts[1..],subtree)?;
        tree.validate()?;
        self.tree = Some(tree);
        self.reconsider = None;
        if let Some(a) = &mut self.active {
            if within(&a.path, path) { a.path = "replaced".into(); }
        }
        self.reset(path);
        self.state.once_completed.retain(|p|!within(p,path));
        self.policy_revision += 1;
        self.log("policy_patched",json!({"revision":self.policy_revision,"path":path,"reason":reason,"policy":self.tree}));
        Ok(())
    }
    fn reset(&mut self, path: &str) {
        if self.active.as_ref().is_some_and(|a|within(&a.path,path)) { self.active = None; }
        self.state.cursors.retain(|p,_|!within(p,path));
        self.state.branches.retain(|p,_|!within(p,path));
        self.state.entries.retain(|p|!within(p,path));
    }
    /// One controller update. `feedback` is exclusively authority-supplied.
    /// The returned request ID must be checkpointed with the returned dispatch.
    pub fn tick(&mut self, request_id: &str, feedback: Option<&ActionState>, laws: &scripting::Registry,
        charge: i32) -> Result<Option<Dispatch>, String> {
        if self.player.health <= 0 { return Ok(None); }
        let Some(tree) = self.tree.clone() else { return Ok(None); };
        let old = self.active.clone();
        let mut output = None;
        let mut budget = policy::TICK_BUDGET;
        let status = self.visit(&tree,"root",request_id,feedback,laws,charge,&mut budget,&mut false,&mut output)?;
        self.state.status = status.clone();
        if status != Status::Running {
            self.active = None;
            if status == Status::Failure {
                self.state.cursors.clear();
                self.state.entries.clear();
                self.reconsider = Some("installed client policy has no successful branch".into());
            }
        }
        self.state.active_path = self.active.as_ref().map(|a|a.path.clone());
        if output.is_none() && self.active.is_none() && old.is_some() && feedback.is_some_and(|f|f.status == Status::Running) {
            output = Some(Dispatch::Cancel);
        }
        Ok(output)
    }
    #[allow(clippy::too_many_arguments)]
    fn visit(&mut self, node: &Node, path: &str, request: &str, feedback: Option<&ActionState>,
        laws: &scripting::Registry, charge: i32, budget: &mut usize, acted: &mut bool,
        output: &mut Option<Dispatch>) -> Result<Status,String> {
        if *budget == 0 { return Err("client policy budget exceeded".into()); }
        *budget -= 1;
        macro_rules! visit { ($node:expr,$path:expr) => { self.visit($node,$path,request,feedback,laws,charge,budget,acted,output)? }; }
        Ok(match node {
            Node::Once {child} => {
                if self.state.once_completed.contains(path) { return Ok(Status::Failure); }
                let result = visit!(child,&format!("{path}/once"));
                if result == Status::Success { self.state.once_completed.insert(path.into()); }
                result
            }
            Node::Guard {condition,child} | Node::When {condition,child} => {
                let entry = matches!(node,Node::When {..});
                let allowed = if entry && self.state.entries.contains(path) { true } else {
                    let mut subject = laws.guard_subjective(&self.player,condition);
                    subject["charge"] = json!(charge);
                    let (result,sources): (bool,Vec<u64>) = laws.law("guard",json!({"condition":condition,"player":subject}))?;
                    self.log("guard_evaluated",json!({"path":path,"condition":condition,"result":result,"sources":sources}));
                    result
                };
                if !allowed { self.reset(path); Status::Failure } else {
                    if entry { self.state.entries.insert(path.into()); }
                    let result = visit!(child,&format!("{path}/{}",if entry {"when"} else {"guard"}));
                    if entry && result != Status::Running { self.state.entries.remove(path); }
                    result
                }
            }
            Node::Sequence {children} => {
                let mut n = *self.state.cursors.get(path).unwrap_or(&0);
                while n < children.len() {
                    match visit!(&children[n],&format!("{path}/{n}")) {
                        Status::Success => { n += 1; self.state.cursors.insert(path.into(),n); }
                        Status::Failure => { self.reset(path); return Ok(Status::Failure); }
                        other => return Ok(other),
                    }
                }
                self.state.cursors.remove(path);
                Status::Success
            }
            Node::Priority {children} => {
                for (n,child) in children.iter().enumerate() {
                    let result = visit!(child,&format!("{path}/{n}"));
                    if result != Status::Failure {
                        let old = self.state.branches.insert(path.into(),n);
                        if old != Some(n) {
                            self.log("branch_selected",json!({"path":path,"previous":old,"selected":n}));
                            if let Some(old) = old {
                                if self.active.as_ref().is_some_and(|a|within(&a.path,&format!("{path}/{old}"))) { self.active = None; }
                            }
                        }
                        return Ok(result);
                    }
                }
                Status::Failure
            }
            Node::Action {action} => {
                if *acted { return Ok(Status::Running); }
                *acted = true;
                if let Some(active) = self.active.as_ref().filter(|a|a.path == path) {
                    if active.rejected {
                        self.active = None;
                        return Ok(Status::Failure);
                    }
                    if let Some(f) = feedback.filter(|f|f.request_id == active.request_id) {
                        match f.status {
                            Status::Running => Status::Running,
                            // Physical interruption restarts the current task on a later tick.
                            Status::Interrupted => { self.active = None; Status::Running }
                            _ => { let status = f.status.clone(); self.active = None; status }
                        }
                    } else { Status::Running }
                } else {
                    self.active = Some(Active { path:path.into(),request_id:request.into(),rejected:false });
                    *output = Some(Dispatch::Start(action.clone()));
                    self.log("action_requested",json!({"request_id":request,"path":path,"action":action}));
                    Status::Running
                }
            }
            Node::Reconsider {reason} => { self.reconsider = Some(reason.clone()); Status::Success }
        })
    }
}

/// Scoped physical input. No policy, other minds, hidden sites or operator audit.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Frame {
    pub run: String,
    pub actor: u32,
    pub tick: u64,
    pub stopped: bool,
    pub paused: bool,
    pub control_epoch: u64,
    pub revision: u64,
    pub position: i32,
    pub health: i32,
    pub hunger: i32,
    pub energy: i32,
    pub food: i32,
    pub fear: i32,
    pub failures: u32,
    pub action: Option<ActionState>,
    pub body: Option<Value>,
    pub materials: Option<Value>,
    pub action_ready_ms: u64,
}
impl Runtime {
    pub fn apply_frame(&mut self, f: &Frame, holdings: Option<Vec<knowledge::Holding>>) -> Result<(),String> {
        if f.run != self.run || f.actor != self.actor { return Err("foreign controller frame".into()); }
        self.player.position=f.position; self.player.health=f.health; self.player.hunger=f.hunger;
        self.player.energy=f.energy; self.player.food=f.food; self.player.fear=f.fear;
        self.player.failures=f.failures;
        if let Some(mut holdings)=holdings {
            for holding in &mut holdings {
                if let Some(old)=self.player.knowledge.iter().find(|old|old.record.id==holding.record.id) {
                    if old.interpreted_source > holding.interpreted_source {
                        holding.interpretation=old.interpretation.clone();
                        holding.interpreted_source=old.interpreted_source;
                        holding.confidence=old.confidence;
                    }
                }
            }
            self.player.knowledge=holdings.into();
        }
        Ok(())
    }
    pub fn observation(&self, f: &Frame, after:u64, limit:usize) -> Value {
        let mut context=self.context.clone();
        let own=context["player"].as_object_mut().expect("bootstrap player context");
        for (key,value) in json!({"position":self.player.position,"health":self.player.health,
            "hunger":self.player.hunger,"energy":self.player.energy,"food":self.player.food,
            "fear":self.player.fear,"failures":self.player.failures,"current_goal":self.player.current_goal,
            "personality":{"caution":self.player.caution,"empathy":self.player.empathy,"introspection":self.player.introspection},
            "beliefs":self.player.beliefs,"relationships":self.player.relationships,"memories":self.player.memories,
            "site_observations":self.player.site_observations,"knowledge":self.player.knowledge,"private_knowledge_drafts":self.knowledge_drafts,
            "current_approach":{"policy":self.tree,"state":self.state,"authority_action":f.action}}).as_object().unwrap() { own.insert(key.clone(),value.clone()); }
        context["simulation_tick"]=json!(f.tick);
        context["simulation_time_ms"]=json!(f.tick * timing::LEGACY_UNIT_MS);
        context["recent_activity"]=self.activity.activity_summary(f.tick * timing::LEGACY_UNIT_MS);
        context["lifecycle"]=self.player.site_observations.iter().find(|p|p.location==f.position)
            .map(|p|p.content["lifecycle"].clone()).unwrap_or(Value::Null);
        if let Some(body)=&f.body {
            context["body"]=json!({"support":body["profile"]["support"],"version":body["profile"]["version"],
                "charge":body["charge"],"capacity":body["profile"]["capacity"],"drain_per_pulse":body["profile"]["drain_per_pulse"]});
        }
        let limit=limit.clamp(1,128);
        let start=if after==0 {self.cursor.saturating_sub(limit as u64)} else {after};
        let experiences:Vec<_>=self.experiences.iter().filter(|e|e.cursor>start).take(limit).collect();
        let observed=experiences.last().map_or(start,|e|e.cursor);
        json!({"api_version":participant::API_VERSION,"projection":"client subjective state; physical facts from scoped authority",
            "provenance":"client_controller","run":self.run,"actor":self.actor,"tick":f.tick,"stopped":f.stopped,
            "paused":f.paused,"control_epoch":f.control_epoch,"policy_revision":self.policy_revision,
            "learning_revision":self.learning_revision,"latest_cursor":self.cursor,"observed_cursor":observed,
            "oldest_cursor":self.experiences.first().map_or(1,|e|e.cursor),
            "gap":start+1<self.experiences.first().map_or(1,|e|e.cursor),"context":crate::research::redacted(context),"experiences":experiences,
            "reconsider_requested":self.reconsider,
            "capabilities":["read_observation","replace_tree","patch_subtree","speak","reflect","pin_observation","publish_knowledge"]})
    }
}

impl Runtime {
    /// Subjective changes are local. They do not manufacture authority-held proof.
    pub fn reflect(&mut self, expected:u64, observed:u64, reflections:&[Reflection], goal:Option<&str>,
        retained:&[Experience], laws:&scripting::Registry) -> Result<(),String> {
        if expected != self.learning_revision { return Err("stale client learning revision".into()); }
        if observed > self.cursor || reflections.is_empty() || reflections.len()>8 {return Err("invalid reflection batch/cursor".into());}
        if goal.is_some_and(|g|g.trim().is_empty() || g.len()>1000) {return Err("invalid goal".into());}
        // Roll back the complete batch on any validation failure.
        let mut next=self.clone();
        let mut sources=BTreeSet::new();
        for r in reflections {
            if !sources.insert(r.source) || next.learned_sources.contains(&r.source) {return Err("experience already interpreted".into());}
            let e=self.experiences.iter().chain(retained).find(|e|e.source==r.source && e.cursor<=observed)
                .ok_or("source not in retained own evidence")?;
            if !matches!(e.kind.as_str(),"perception"|"skill_result"|"skill_progress"|"action_interrupted"|"behavior_interrupted"|"speech_cancelled") {
                return Err("source is not an experienced observation/outcome".into());
            }
            let error:String=laws.law("validate_reflection",json!(r))?;
            if !error.is_empty() {return Err(error);}
            if let Some(draft)=&r.knowledge {
                knowledge::validate_assertion(&draft.topic,&draft.text,draft.confidence)?;
                if next.knowledge_drafts.len() >= knowledge::MAX_HOLDINGS {return Err("private knowledge draft storage is full".into());}
                next.knowledge_drafts.push(r.clone());
            }
            let from=if e.kind=="perception" {e.data["from"].as_u64().and_then(|v|u32::try_from(v).ok())} else {None};
            if r.trust_delta!=0 && from.is_none() {return Err("trust update requires perceived counterpart".into());}
            if let Some(b)=&r.belief {
                if next.player.beliefs.iter().any(|k|k.claim.location==b.location && k.source>r.source) {return Err("newer subjective evidence retained".into());}
                let known=next.player.beliefs.iter().any(|k|k.claim.location==b.location)
                    || b.location==e.location || e.data["content"]["record"]["location"].as_i64()==Some(i64::from(b.location));
                if !known || b.text.len()>1000 {return Err("belief location is not known".into());}
            }
            let trust=from.and_then(|id|next.player.relationships.get(&id)).copied().unwrap_or(0);
            #[derive(Deserialize)]
            struct Outcome {caution:i32,trust:i32,confidence:i32}
            let change:Outcome=laws.law("reflection",json!({"actor":scripting::facts(&next.player),"trust":trust,
                "caution_delta":r.caution_delta,"trust_delta":r.trust_delta}))?;
            next.player.caution=change.caution;
            if let Some(id)=from {next.player.relationships.insert(id,change.trust);}
            if let Some(b)=&r.belief {
                next.player.beliefs.retain(|k|k.claim.location!=b.location);
                next.player.beliefs.push(Known {claim:b.clone(),source:r.source,confidence:change.confidence});
            }
            if e.kind=="perception" {
                let content=&e.data["content"];
                let record=if e.data["kind"]=="knowledge_report" {content["record"]["id"].as_str()}
                    else if matches!(e.data["kind"].as_str(),Some("program_inspected"|"law_inspected")) {content["record"].as_str()}
                    else {None};
                if let Some(h)=next.player.knowledge.iter_mut().find(|h|Some(h.record.id.as_str())==record) {
                    if h.interpreted_source.is_none_or(|source|source<=r.source) {
                        h.interpretation=Some(r.interpretation.clone());h.interpreted_source=Some(r.source);
                    }
                }
            }
            next.learned_sources.insert(r.source);
            next.log("reflection",json!({"reflection":r,"observed_cursor":observed,"provenance":"client_reported"}));
        }
        if let Some(goal)=goal {next.player.current_goal=Some(goal.into());}
        next.learning_revision+=1;
        *self=next;
        Ok(())
    }
}

impl Runtime {
    pub fn record_receipt(&mut self, receipt: &participant::Receipt) {
        if !receipt.ok {
            if let Some(active)=self.active.as_mut().filter(|a|a.request_id==receipt.request_id) { active.rejected=true; }
        }
        self.log("authority_receipt",json!(receipt));
    }
}
