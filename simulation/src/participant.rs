//! Versioned, transport-independent character commands. Authority authenticates actor separately.
use super::*;
use sha2::{Digest, Sha256};
pub const API_VERSION: &str = "sao-participant-v1";
pub const TRACE_LIMIT: usize = 256;
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Experience {
    pub cursor: u64,
    pub source: u64,
    pub tick: u64,
    pub location: i32,
    pub kind: String,
    pub parents: Vec<u64>,
    pub data: Value,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ParticipantState {
    pub control_epoch: u64,
    pub learning_revision: u64,
    pub cursor: u64,
    pub experiences: Vec<Experience>,
    pub speech: Vec<QueuedSpeech>,
    #[serde(default)]
    pub last_speech_tick: Option<u64>,
    pub receipts: Vec<Receipt>,
    pub learned_sources: Vec<u64>,
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
        Node::Guard { child, .. } if parts[0] == "guard" => {
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
        if self.tick == 0 && event.kind == "perception" {
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
                | "policy_patched"
                | "branch_selected"
                | "policy_tick"
                | "participant_command"
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
        s.experiences.push(Experience {
            cursor: s.cursor,
            source: e.id,
            tick: e.tick,
            location,
            kind: e.kind.clone(),
            parents,
            data: e.data.clone(),
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
            json!({"api_version":API_VERSION,"run":self.run,"actor":actor,"tick":self.tick,"stopped":self.stopped,
            "control_epoch":s.control_epoch,"policy_revision":self.players[i].generation,"learning_revision":s.learning_revision,
            "context":self.context(i),"experiences":experiences,"next_cursor":next,"latest_cursor":s.cursor,"oldest_cursor":oldest,"gap":after.saturating_add(1)<oldest,
            "receipts":s.receipts,"queued_speech":s.speech,"capabilities":["replace_tree","patch_subtree","speak","reflect"],
            "limits":{"tree_nodes":64,"tree_depth":8,"children":8,"speech_queue":8,"trace_retention":TRACE_LIMIT,"reflections":8},
            "patch_semantics":"replace one node at canonical root/n/guard path; reset cursors at/under patch; retain ancestor/sibling progress; interrupt active leaf only if inside patch; next tick rechecks current guards"}),
        )
    }
    pub fn change_control(&mut self, actor: u32) -> Result<(), String> {
        let i = self.idx(actor)?;
        if !self.participant_mode {
            return Ok(());
        }
        self.participants.entry(actor).or_default().control_epoch += 1;
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
                for action in tree.validate_with_laws(&self.scripts)? {
                    if let Some(target) = action.target {
                        if !self.players[i]
                            .memories
                            .iter()
                            .any(|m| m.from == Some(target))
                        {
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
                self.scripts
                    .validate_action(&Action::say(text), &self.players[i])?;
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
                        content: e.data.clone(),
                    });
                }
                let d = Decision {
                    reason: "independent interpretation".into(),
                    policy: None,
                    actions: vec![Action::new(Skill::Wait)],
                    reflections: reflections.clone(),
                };
                self.validate(i, &d, &evidence)?;
                let before = json!({"caution":self.players[i].caution,"relationships":self.players[i].relationships,"beliefs":self.players[i].beliefs,"goal":self.players[i].motive});
                for r in reflections {
                    let from = evidence
                        .iter()
                        .find(|e| e.source == r.source)
                        .and_then(|e| e.from);
                    self.reflect_identity(i, r, from)?;
                    self.participants
                        .get_mut(&actor)
                        .unwrap()
                        .learned_sources
                        .push(r.source);
                }
                if let Some(goal) = goal {
                    self.players[i].motive = goal.clone();
                }
                let valid: Vec<u64> = self.participants[&actor]
                    .experiences
                    .iter()
                    .map(|e| e.source)
                    .collect();
                self.participants
                    .get_mut(&actor)
                    .unwrap()
                    .learned_sources
                    .retain(|id| valid.contains(id));
                self.event(Some(actor),"identity_change",std::iter::once(cause).chain(sources).collect(),json!({"reflections":reflections,"before":before,"after":{"caution":self.players[i].caution,"relationships":self.players[i].relationships,"beliefs":self.players[i].beliefs,"goal":self.players[i].motive}}));
            }
        }
        Ok(cause)
    }
    pub(super) fn cancel_speech(&mut self, actor: u32, reason: &str) {
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
            self.participants
                .get_mut(&actor)
                .unwrap()
                .speech
                .retain(|q| q.expires_tick >= self.tick);
            for q in expired {
                self.event(
                    Some(actor),
                    "speech_cancelled",
                    vec![q.cause],
                    json!({"reason":"expired before delivery"}),
                );
            }
            if self.participants[&actor].last_speech_tick == Some(self.tick) {
                continue;
            }
            if !self.participants[&actor].speech.is_empty() {
                let mut q = self.participants.get_mut(&actor).unwrap().speech.remove(0);
                let action = Action::say(&q.text);
                let mut execution = q.execution.take().unwrap_or_else(|| Execution {
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
            self.participants.get_mut(&actor).unwrap().last_speech_tick = Some(self.tick);
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
