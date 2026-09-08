//! The participant command kernel has an explicit, actor-scoped write set.
//! Storage supplies its read dependencies; this wrapper cannot advance physics.
use crate::{
    participant::{ParticipantState, Receipt, Request},
    Event, Player, World,
};
use std::collections::BTreeSet;

/// Initial-definition dependencies for start/cancel admission and control
/// changes. These operations do not initialize people, teach seed knowledge,
/// or expose authored starting habits. Physical execution and observations
/// still receive the complete seed. The participant commit excludes this projection.
pub fn action_admission_initial(seed: &crate::Scenario) -> crate::Scenario {
    crate::Scenario {
        society: seed.society.clone(), infrastructure: seed.infrastructure.clone(),
        lifecycle: seed.lifecycle.clone(), disturbances: seed.disturbances.clone(),
        knowledge: Default::default(), archives: seed.archives.clone(),
        starting_behaviors: Default::default(), food_sources: seed.food_sources.clone(),
        weather: seed.weather.clone(), arenas: seed.arenas.clone(), map: seed.map.clone(),
        name: seed.name.clone(), seed: seed.seed, max_ticks: seed.max_ticks,
        players: vec![], sites: seed.sites.clone(),
    }
}

/// Explicit target read dependencies, independent of remembered evidence.
/// Policy validation still enforces the node/depth/size limits at admission.
pub fn tree_targets(tree: &crate::Node) -> BTreeSet<u32> {
    let mut targets = BTreeSet::new();
    let mut pending = vec![tree];
    while let Some(node)=pending.pop() {
        match node {
            crate::Node::Action {action} => { targets.extend(action.target); },
            crate::Node::Once {child} | crate::Node::When {child,..} | crate::Node::Guard {child,..} => pending.push(child),
            crate::Node::Priority {children} | crate::Node::Sequence {children} => pending.extend(children),
            crate::Node::Reconsider {..} => (),
        }
    }
    targets
}

pub fn command_targets(command: &crate::participant::Command) -> BTreeSet<u32> {
    use crate::participant::Command;
    match command {
        Command::StartAction {action,..} => action.target.into_iter().collect(),
        Command::ReplaceTree {tree,..} => tree_targets(tree),
        Command::PatchSubtree {subtree,..} => tree_targets(subtree),
        Command::CancelAction {..} | Command::PublishKnowledge {..} | Command::ReadObservation {..}
        | Command::PinObservation {..} | Command::Speak {..} | Command::Reflect {..} => BTreeSet::new(),
    }
}

/// Start/cancel only admit or interrupt an actor's execution. Physical effects
/// run later under the action clock's dependencies. Validation still receives
/// the actor's complete facts/rules/map and each named target's visibility facts.
/// Other commands can construct observations or validate persistent policies.
pub fn command_reads_local_context(command: &crate::participant::Command) -> bool {
    use crate::participant::Command;
    match command {
        Command::StartAction { .. } | Command::CancelAction { .. } => false,
        Command::ReplaceTree { .. } | Command::PatchSubtree { .. }
        | Command::PublishKnowledge { .. } | Command::ReadObservation { .. }
        | Command::PinObservation { .. } | Command::Speak { .. }
        | Command::Reflect { .. } => true,
    }
}

pub fn decision_targets(decision: &crate::Decision) -> BTreeSet<u32> {
    let mut targets: BTreeSet<_> = decision.actions.iter().filter_map(|a|a.target).collect();
    if let Some(tree)=&decision.policy { targets.extend(tree_targets(tree)); }
    targets
}

/// The Bevy convenience call maps a client's single physical action to the
/// same StartAction command. Other intent forms retain their wider context.
pub fn intent_reads_local_context(client_controlled: bool, decision: &crate::Decision) -> bool {
    !client_controlled || !decision.reflections.is_empty() || decision.policy.is_some()
        || decision.actions.len() != 1 || decision.actions[0].skill == crate::Skill::Speak
}

pub struct ParticipantTransaction {
    world: World,
    actor: u32,
}
pub struct ParticipantCommit {
    pub clock_hint: crate::clock::ActorHint,
    pub player: Player,
    pub participant: ParticipantState,
    pub next_event: u64,
    pub events: Vec<Event>,
    pub dirty: Option<bool>,
    pub law_faults: Vec<crate::laws::LawFault>,
    pub receipt: Option<Receipt>,
}
impl ParticipantTransaction {
    /// `world` contains the actor's complete private state, explicitly targeted
    /// bodies and (when command_reads_local_context) co-located public
    /// bodies/lifecycle and stations, plus the facts
    /// consumed by current visibility laws, their own support/materials, shared rules
    /// and surveyed configuration. Other characters' minds are not required.
    /// Only the declared fields in ParticipantCommit can leave this boundary.
    pub fn new(world: World, actor: u32) -> Result<Self, String> {
        if world.participants.len() != 1 || !world.participants.contains_key(&actor) {
            return Err("participant transaction needs exactly its actor state".into());
        }
        world.idx(actor)?;
        Ok(Self { world, actor })
    }
    pub fn execute(mut self, request: Request) -> Result<ParticipantCommit, String> {
        // An added command must receive an explicit dependency/write-set review.
        match &request.command {
            crate::participant::Command::StartAction { .. }
            | crate::participant::Command::CancelAction { .. } => (),
            // Reads retained own evidence and holdings; writes only this actor's
            // assessment/assertion and scoped receipt/experience rows.
            crate::participant::Command::PublishKnowledge { .. } => (),
            crate::participant::Command::ReadObservation { .. }
            | crate::participant::Command::PinObservation { .. }
            | crate::participant::Command::Speak { .. }
            | crate::participant::Command::ReplaceTree { .. }
            | crate::participant::Command::PatchSubtree { .. }
            | crate::participant::Command::Reflect { .. } => (),
        }
        let receipt = self.world.participant_apply(self.actor, request)?;
        self.finish(Some(receipt))
    }
    pub fn execute_intent(
        mut self,
        decision: crate::Decision,
    ) -> Result<ParticipantCommit, String> {
        let receipt = self.world.participant_client_intent(self.actor, decision)?;
        self.finish(receipt)
    }
    /// Ownership invalidates slow work and queued speech using the shared
    /// kernel; installed physical behavior remains in force.
    pub fn change_control(mut self) -> Result<ParticipantCommit, String> {
        self.world.change_control(self.actor)?;
        self.finish(None)
    }
    fn finish(mut self, receipt: Option<Receipt>) -> Result<ParticipantCommit, String> {
        let i = self.world.idx(self.actor)?;
        Ok(ParticipantCommit {
            clock_hint: self.world.actor_clock_hint(i),
            player: self.world.players.remove(i),
            participant: self
                .world
                .participants
                .remove(&self.actor)
                .expect("validated actor state"),
            next_event: self.world.next_event,
            events: self.world.events,
            dirty: self.world.timing.dirty.get(&self.actor).copied(),
            law_faults: self.world.laws.faults.lock().clone(),
            receipt,
        })
    }
}

impl World {
    /// The Bevy convenience operation uses the same participant capabilities.
    /// Keeping its routing and rejection behavior here allows both storage
    /// adapters to execute exactly the same human-input transaction.
    pub fn participant_client_intent(
        &mut self,
        actor: u32,
        d: crate::Decision,
    ) -> Result<Option<Receipt>, String> {
        use crate::participant::{Command, Request, API_VERSION};
        if !self.participant_mode {
            return Err("not a participant run".into());
        }
        if !d.reflections.is_empty() {
            return Err("submit learning separately".into());
        }
        let i = self.idx(actor)?;
        if self.client_controlled(actor) {
            if d.policy.is_some() || d.actions.len() != 1 {
                return Err("client mode accepts one physical action; evaluate policies in the client".into());
            }
            let action = d.actions.into_iter().next().unwrap();
            let command = if action.skill == crate::Skill::Speak {
                Command::Speak {text:action.text.unwrap_or_default(),expires_tick:self.tick + 10}
            } else { Command::StartAction {expected_revision:self.players[i].generation,action} };
            return self.participant_apply(actor,Request {api_version:API_VERSION.into(),
                request_id:format!("bevy-{}",self.next_event),control_epoch:self.participants[&actor].control_epoch,command}).map(Some);
        }
        if d.policy.is_none()
            && !(d.actions.len() == 1 && d.actions[0].skill == crate::Skill::Speak)
        {
            let before = self.clone();
            if let Err(error) = self.participant_manual(actor, d) {
                *self = before;
                self.event(
                    Some(actor),
                    "participant_rejected",
                    vec![],
                    serde_json::json!({"error":error}),
                );
            }
            return Ok(None);
        }
        let command = if d.policy.is_none()
            && d.actions.len() == 1
            && d.actions[0].skill == crate::Skill::Speak
        {
            Command::Speak {
                text: d.actions[0].text.clone().unwrap_or_default(),
                expires_tick: self.tick + 10,
            }
        } else {
            if d.policy.is_some() && !d.actions.is_empty() {
                return Err("ambiguous policy/actions".into());
            }
            let tree = d.policy.unwrap_or_else(|| crate::Node::Sequence {
                children: d
                    .actions
                    .into_iter()
                    .map(|action| crate::Node::Action { action })
                    .collect(),
            });
            Command::ReplaceTree {
                expected_revision: self.players[i].generation,
                reason: d.reason,
                tree,
            }
        };
        self.participant_apply(
            actor,
            Request {
                api_version: API_VERSION.into(),
                request_id: format!("bevy-{}", self.next_event),
                control_epoch: self.participants[&actor].control_epoch,
                command,
            },
        )
        .map(Some)
    }
}
