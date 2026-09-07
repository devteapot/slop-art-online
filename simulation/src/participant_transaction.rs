//! The participant command kernel has an explicit, actor-scoped write set.
//! Storage supplies its read dependencies; this wrapper cannot advance physics.
use crate::{
    participant::{ParticipantState, Receipt, Request},
    Event, Player, World,
};

pub struct ParticipantTransaction {
    world: World,
    actor: u32,
}
pub struct ParticipantCommit {
    pub player: Player,
    pub participant: ParticipantState,
    pub next_event: u64,
    pub events: Vec<Event>,
    pub dirty: Option<bool>,
    pub law_faults: Vec<crate::laws::LawFault>,
    pub receipt: Option<Receipt>,
}
impl ParticipantTransaction {
    /// `world` contains the actor's complete private state, co-located public
    /// bodies/lifecycle and stations, their own support/materials, shared rules
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
    fn finish(mut self, receipt: Option<Receipt>) -> Result<ParticipantCommit, String> {
        let i = self.world.idx(self.actor)?;
        Ok(ParticipantCommit {
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
