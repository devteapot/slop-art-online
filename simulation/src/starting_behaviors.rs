//! Explicit, versioned seed habits use the same policy installation as later choices.
use crate::*;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StartingBehavior {
    pub id: String,
    pub revision: u32,
    pub description: String,
    pub tree: Node,
}

impl World {
    #[cfg(test)]
    pub(super) fn install_starting_behaviors(&mut self, initialization: u64) -> Result<(), String> {
        for (actor, habit) in self.initial.starting_behaviors.clone() {
            // World::new owns the only reference to this unfinished world and
            // returns Err if any seed fails. Its enclosing transaction already
            // supplies rollback; cloning the entire initial event history for
            // every actor adds no atomicity and grows quadratically in a crowd.
            self.install_starting_behavior_inner(actor, &habit, initialization, "authored world seed", false)?;
        }
        Ok(())
    }

    pub(super) fn initialize_actor_behavior(&mut self, actor: u32, initialization: u64) -> Result<(), String> {
        if let Some(habit) = self.initial.starting_behaviors.get(&actor).cloned() {
            self.install_starting_behavior_inner(actor, &habit, initialization, "authored world seed", false)?;
        }
        Ok(())
    }

    pub(super) fn install_starting_behavior(
        &mut self, actor: u32, habit: &StartingBehavior, cause: u64, source: &str,
    ) -> Result<(), String> {
        self.install_starting_behavior_inner(actor,habit,cause,source,true)
    }
    fn install_starting_behavior_inner(
        &mut self, actor:u32, habit:&StartingBehavior, cause:u64, source:&str, transactional:bool,
    ) -> Result<(),String> {
            let i = self.idx(actor)?;
            if habit.id.is_empty()
                || habit.id.len() > 80
                || !habit
                    .id
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c))
                || habit.revision == 0
                || habit.description.trim().is_empty()
                || habit.description.chars().count() > 700
            {
                return Err("invalid starting behavior identity, revision or description".into());
            }
            let origin = self.event(
                Some(actor),
                "starting_behavior_installed",
                vec![cause],
                json!({"id":habit.id,"revision":habit.revision,"description":habit.description,
                    "source":source,"revisable":true}),
            );
            let decision=Decision {
                    reason: format!(
                        "Starting habit {}@{}: {}",
                        habit.id, habit.revision, habit.description
                    ),
                    actions: vec![],
                    policy: Some(habit.tree.clone()),
                    reflections: vec![],
                };
            if transactional {
                self.apply_decision(actor,self.players[i].controller.clone(),decision,Some(origin),None)?;
            } else {
                self.apply_decision_inner(actor,self.players[i].controller.clone(),decision,Some(origin),None)?;
            }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn construction_and_transactional_seed_installation_have_identical_state_and_evidence() {
        for source in [include_str!("../../scenarios/survival.json"),
            include_str!("../../scenarios/faction-world-reality.json")] {
            let mut scenario:Scenario=serde_json::from_str(source).unwrap();
            let habits=std::mem::take(&mut scenario.starting_behaviors);
            let mut a=World::new("seed-boundary-parity".into(),scenario).unwrap();
            let mut b=a.clone();
            a.initial.starting_behaviors=habits.clone();b.initial.starting_behaviors=habits.clone();
            a.install_starting_behaviors(1).unwrap();
            for (actor,habit) in habits {
                b.install_starting_behavior(actor,&habit,1,"authored world seed").unwrap();
            }
            assert_eq!(serde_json::to_value(&a).unwrap(),serde_json::to_value(&b).unwrap());
            assert_eq!(serde_json::to_value(&a.events).unwrap(),serde_json::to_value(&b.events).unwrap());
        }
    }
}
