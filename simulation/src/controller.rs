//! Transport-neutral boundary between controller decisions and physical skills.
//! This module owns no network, database or wall-clock access.
use crate::*;
use std::collections::BTreeSet;

pub const VERSION: &str = "sao-client-controller-v1";

/// Immutable initial state for this character's controller, never another mind.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Bootstrap {
    pub version: String,
    pub run: String,
    pub actor: u32,
    pub player: Player,
    pub context: Value,
}

/// Physical action receipt state. Controller policy state is deliberately absent.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ActionState {
    pub request_id: String,
    pub revision: u64,
    pub accepted_event: u64,
    pub status: Status,
    pub attempt: Option<u64>,
}

/// Authorization/delivery metadata, not the client's interpretation or memory.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Authority {
    pub bootstrap: deferred::Deferred<Bootstrap>,
    pub known_targets: BTreeSet<u32>,
    pub last_lifecycle: Option<Value>,
    pub action: Option<ActionState>,
}

impl World {
    pub fn client_controlled(&self, actor: u32) -> bool {
        self.participants.get(&actor).is_some_and(|p| p.client_controller.is_some())
    }

    pub fn enable_client_controllers(&mut self) -> Result<(), String> {
        if !self.participant_mode { self.enable_participants(); }
        for i in 0..self.players.len() { self.enable_actor_client(i)?; }
        Ok(())
    }

    pub(super) fn enable_actor_client(&mut self, i: usize) -> Result<(), String> {
        let actor = self.players[i].id;
        if self.client_controlled(actor) { return Ok(()); }
        let bootstrap = Bootstrap { version: VERSION.into(), run: self.run.clone(), actor,
            player: self.players[i].clone(), context: self.context(i) };
        let mut known_targets = BTreeSet::new();
        for perception in self.players[i].memories.iter().chain(self.players[i].site_observations.iter()) {
            if let Some(target) = perception.from { known_targets.insert(target); }
            for p in perception.content["lifecycle"]["people"].as_array().into_iter().flatten() {
                if let Some(id) = p["id"].as_u64().and_then(|n| u32::try_from(n).ok()) { known_targets.insert(id); }
            }
        }
        let last_lifecycle = self.players[i].site_observations.iter()
            .find(|p| p.location == self.players[i].position && p.kind == "site")
            .map(|p| p.content["lifecycle"].clone());
        self.participants.entry(actor).or_default().client_controller = Some(Authority {
            bootstrap: bootstrap.into(), known_targets, last_lifecycle, action: None,
        });
        self.players[i].execution = None;
        self.players[i].memories = vec![].into();
        self.players[i].site_observations = vec![].into();
        self.players[i].beliefs = vec![].into();
        self.players[i].relationships = BTreeMap::new().into();
        self.players[i].current_goal = None;
        self.participants.get_mut(&actor).unwrap().activity.clear();
        self.wake(actor);
        Ok(())
    }

    pub(super) fn controller_start_action(&mut self, i: usize, request_id: &str,
        revision: u64, action: &Action, cause: u64) -> Result<(), String> {
        let actor = self.players[i].id;
        if !self.client_controlled(actor) { return Err("action API requires client controller mode".into()); }
        if revision != self.players[i].generation { return Err("stale action revision".into()); }
        self.validate_scoped_action(i, action)?;
        if action.target.is_some_and(|target| !self.target_perceived(i, target, &[])) {
            return Err("target not perceived".into());
        }
        self.interrupt(i, cause, "action replaced");
        self.players[i].generation += 1;
        self.players[i].execution = Some(Execution {
            dialogue: false, decision: cause,
            tree: Behavior::Sequence(vec![Behavior::Action(action.clone())]), cursor: 0,
            attempt: None, remaining: 0, script: None, policy: None, state: PolicyState::default(),
        });
        self.participants.get_mut(&actor).unwrap().client_controller.as_mut().unwrap().action = Some(ActionState {
            request_id: request_id.into(), revision: self.players[i].generation,
            accepted_event: cause, status: Status::Running, attempt: None,
        });
        self.wake(actor);
        Ok(())
    }

    pub(super) fn controller_cancel_action(&mut self, i: usize, revision: u64, cause: u64) -> Result<(), String> {
        let actor = self.players[i].id;
        if !self.client_controlled(actor) { return Err("action API requires client controller mode".into()); }
        if revision != self.players[i].generation { return Err("stale action revision".into()); }
        self.interrupt(i, cause, "client cancelled action");
        self.players[i].generation += 1;
        self.controller_action_status(actor, Status::Interrupted, None);
        Ok(())
    }

    pub(super) fn controller_action_status(&mut self, actor: u32, status: Status, attempt: Option<u64>) {
        if let Some(action) = self.participants.get_mut(&actor)
            .and_then(|p| p.client_controller.as_mut()).and_then(|p| p.action.as_mut()) {
            action.status = status;
            action.attempt = attempt;
        }
    }
}

pub mod runtime;

#[cfg(test)]
mod tests;
