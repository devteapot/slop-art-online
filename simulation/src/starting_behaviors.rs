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
    pub(super) fn install_starting_behaviors(&mut self, initialization: u64) -> Result<(), String> {
        for (actor, habit) in self.initial.starting_behaviors.clone() {
            self.install_starting_behavior(actor, &habit, initialization, "authored world seed")?;
        }
        Ok(())
    }

    pub(super) fn install_starting_behavior(
        &mut self, actor: u32, habit: &StartingBehavior, cause: u64, source: &str,
    ) -> Result<(), String> {
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
            self.apply_decision(
                actor,
                self.players[i].controller.clone(),
                Decision {
                    reason: format!(
                        "Starting habit {}@{}: {}",
                        habit.id, habit.revision, habit.description
                    ),
                    actions: vec![],
                    policy: Some(habit.tree.clone()),
                    reflections: vec![],
                },
                Some(origin),
                None,
            )?;
        Ok(())
    }
}
