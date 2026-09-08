//! Ordered initialization shared by immediate and persisted world construction.
//! Progress belongs to the unpublished build, never to an active simulation.
use crate::*;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum Phase { Observations, ValidateKnowledge, Knowledge, Behaviors, Complete }

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Progress {
    initialization: u64,
    phase: Phase,
    ordinal: usize,
}

impl Progress {
    pub(crate) fn new(initialization: u64) -> Self {
        Self { initialization, phase: Phase::Observations, ordinal: 0 }
    }

    pub fn complete(&self) -> bool { self.phase == Phase::Complete }
}

impl World {
    /// Execute at most `limit` actors in one phase. Observation order follows
    /// the authored player vector; knowledge and habits follow their actor-key
    /// maps, preserving the original global audit sequence. Events may be
    /// drained between calls after they have been durably retained.
    ///
    /// Errors require discarding or rolling back both world and progress. An
    /// incomplete world must remain private and must not execute gameplay.
    pub fn initialize_batch(&mut self, progress: &mut Progress, limit: usize) -> Result<bool, String> {
        if limit == 0 { return Err("initialization batch must be positive".into()); }
        if self.tick != 0 || self.timing.time_ms != 0 || self.participant_mode {
            return Err("initialization requires an unpublished, unadvanced world".into());
        }
        let start = progress.ordinal;
        let end = start.saturating_add(limit);
        let total = match progress.phase {
            Phase::Observations => {
                for i in start..end.min(self.players.len()) {
                    self.players[i].last_cause = Some(progress.initialization);
                    // Starting beliefs are remembered reports, never access to
                    // the omniscient initialization payload.
                    for n in 0..self.players[i].beliefs.len() {
                        let claim = self.players[i].beliefs[n].claim.clone();
                        let source = self.perceive(i, progress.initialization, "prior_report",
                            None, claim.location, json!({"claim":claim}))?;
                        self.players[i].beliefs[n].source = source;
                    }
                    self.observe_site(i)?;
                }
                self.players.len()
            }
            Phase::ValidateKnowledge => {
                self.validate_initial_knowledge()?;
                0
            }
            Phase::Knowledge => {
                let actors: Vec<_> = self.initial.knowledge.keys().skip(start).take(limit).copied().collect();
                for actor in actors { self.initialize_actor_knowledge(actor, progress.initialization)?; }
                self.initial.knowledge.len()
            }
            Phase::Behaviors => {
                let actors: Vec<_> = self.initial.starting_behaviors.keys().skip(start).take(limit).copied().collect();
                for actor in actors { self.initialize_actor_behavior(actor, progress.initialization)?; }
                self.initial.starting_behaviors.len()
            }
            Phase::Complete => return Ok(true),
        };
        if end >= total {
            progress.ordinal = 0;
            progress.phase = match progress.phase {
                Phase::Observations => Phase::ValidateKnowledge,
                Phase::ValidateKnowledge => Phase::Knowledge,
                Phase::Knowledge => Phase::Behaviors,
                Phase::Behaviors | Phase::Complete => Phase::Complete,
            };
        } else { progress.ordinal = end; }
        Ok(progress.complete())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn persisted_batches_preserve_world_and_ordered_audit_in_every_mode() {
        for source in [include_str!("../../scenarios/survival.json"),
            include_str!("../../scenarios/faction-world-reality.json"),
            include_str!("../../scenarios/population-reproduction.json"),
            include_str!("../../scenarios/research-invention.json")] {
            let scenario:Scenario = serde_json::from_str(source).unwrap();
            for mode in 0..3 {
                let construct = [World::new, World::new_participant, World::new_client][mode];
                let expected = construct("initialization-batches".into(), scenario.clone()).unwrap();
                for limit in [1, 7, usize::MAX] {
                    let (mut world, mut progress) = World::begin_initialization(expected.run.clone(), scenario.clone()).unwrap();
                    let mut audit = std::mem::take(&mut world.events);
                    loop {
                        // Persist state and progress separately, with audit
                        // already drained as in authority transactions.
                        world = serde_json::from_slice(&serde_json::to_vec(&world).unwrap()).unwrap();
                        progress = serde_json::from_slice(&serde_json::to_vec(&progress).unwrap()).unwrap();
                        let done = world.initialize_batch(&mut progress, limit).unwrap();
                        audit.append(&mut world.events);
                        if done { break; }
                    }
                    if mode > 0 {
                        world.enable_participants();
                        for event in &audit { world.record_initial_participant_event(event); }
                    }
                    if mode > 1 {
                        let mut cursor = 0;
                        while cursor < world.players.len() {
                            cursor = world.initialize_client_batch(cursor, limit).unwrap();
                            world = serde_json::from_slice(&serde_json::to_vec(&world).unwrap()).unwrap();
                        }
                    }
                    assert_eq!(serde_json::to_value(&world).unwrap(), serde_json::to_value(&expected).unwrap());
                    assert_eq!(serde_json::to_value(&audit).unwrap(), serde_json::to_value(&expected.events).unwrap());
                }
            }
        }
    }

    #[test]
    fn invalid_batch_or_started_game_cannot_advance_initialization() {
        let scenario:Scenario = serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
        let (mut world, mut progress) = World::begin_initialization("invalid-batch".into(), scenario).unwrap();
        let before = serde_json::to_value(&world).unwrap();
        assert!(world.initialize_batch(&mut progress, 0).is_err());
        assert_eq!(before, serde_json::to_value(&world).unwrap());
        world.tick = 1;
        assert!(world.initialize_batch(&mut progress, 1).is_err());
        world.tick = 0;
        world.enable_participants();
        assert!(world.initialize_batch(&mut progress, 1).is_err());
    }
}
