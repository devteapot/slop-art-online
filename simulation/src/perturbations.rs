//! Explicit scenario interventions for controlled experiments, never character decisions.
//! The normal world update transaction commits their effects and applied indices together.
use crate::*;

pub const MAX_DISTURBANCES: usize = 64;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Disturbance {
    pub at_ms: u64,
    #[serde(flatten)]
    pub action: DisturbanceAction,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum DisturbanceAction {
    Damage { actor: u32, amount: i32 },
    DestroyArchive { archive: u32 },
}

pub fn validate(scenario: &Scenario) -> Result<(), String> {
    if scenario.disturbances.len() > MAX_DISTURBANCES {
        return Err("a scenario supports at most 64 authored disturbances".into());
    }
    let limit = scenario
        .max_ticks
        .checked_mul(timing::LEGACY_UNIT_MS)
        .ok_or("disturbance time limit overflow")?;
    for (index, disturbance) in scenario.disturbances.iter().enumerate() {
        if disturbance.at_ms > limit {
            return Err(format!(
                "disturbance {index} is beyond the scenario time limit"
            ));
        }
        match disturbance.action {
            DisturbanceAction::Damage { actor, amount } => {
                if !scenario.players.iter().any(|p| p.id == actor) || !(1..=100).contains(&amount) {
                    return Err(format!(
                        "disturbance {index} requires an existing actor and damage 1..100"
                    ));
                }
            }
            DisturbanceAction::DestroyArchive { archive } => {
                if !scenario.archives.iter().any(|a| a.id == archive) {
                    return Err(format!(
                        "disturbance {index} requires an existing initial archive"
                    ));
                }
            }
        }
    }
    Ok(())
}

impl World {
    pub(super) fn apply_disturbances(&mut self) -> Result<(), String> {
        // Input index is the stable ordering and persistence key. Do not sort by
        // scheduled time: one coarse update can make several unsorted entries due.
        for (index, disturbance) in self.initial.disturbances.clone().into_iter().enumerate() {
            if disturbance.at_ms > self.timing.time_ms
                || self.timing.applied_disturbances.contains(&index)
            {
                continue;
            }
            let skipped = match disturbance.action {
                DisturbanceAction::Damage { actor, .. } => {
                    let i = self.idx(actor)?;
                    (self.players[i].health <= 0).then_some("target already dead")
                }
                DisturbanceAction::DestroyArchive { archive } => {
                    let archive = self
                        .archives
                        .iter()
                        .find(|a| a.id == archive)
                        .ok_or("disturbance archive is missing")?;
                    archive.destroyed.then_some("archive already destroyed")
                }
            };
            let cause = self.event(
                None,
                "scenario_disturbance",
                vec![],
                json!({
                    "index":index,"scheduled_time_ms":disturbance.at_ms,
                    "action":disturbance.action,"source":"authored scenario intervention",
                    "status":if skipped.is_some() { "skipped" } else { "applied" },
                    "reason":skipped,
                }),
            );
            if skipped.is_none() {
                match disturbance.action {
                    DisturbanceAction::Damage { actor, amount } => {
                        let i = self.idx(actor)?;
                        self.damage(i, amount, None, cause, "scenario_disturbance")?;
                    }
                    DisturbanceAction::DestroyArchive { archive } => {
                        self.destroy_physical_archive(archive, cause, None)?;
                    }
                }
            }
            // A no-op on an already absent target is successfully consumed. Errors
            // return before this insertion and advance_ms discards the whole update.
            self.timing.applied_disturbances.insert(index);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scenario() -> Scenario {
        let mut s: Scenario =
            serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
        s.players.truncate(2);
        s.max_ticks = 100;
        s.map = None;
        s.arenas.clear();
        s.weather = None;
        s.food_sources.clear();
        s.starting_behaviors.clear();
        s.knowledge.clear();
        s.disturbances.clear();
        for (i, p) in s.players.iter_mut().enumerate() {
            p.controller = Controller::Human;
            p.position = i as i32 * 10;
            p.health = 100;
            p.hunger = 10;
            p.food = 2;
            p.energy = 70;
            p.beliefs.clear();
        }
        s.sites = vec![
            Site {
                position: 0,
                food: 5,
                hazard: 0,
                shelter: 0,
            },
            Site {
                position: 10,
                food: 5,
                hazard: 0,
                shelter: 0,
            },
        ];
        s.archives = vec![knowledge::ArchiveSeed {
            id: 7,
            position: 0,
            label: "Local archive".into(),
            capacity: 8,
        }];
        s
    }

    fn damage(at_ms: u64, amount: i32) -> Disturbance {
        Disturbance {
            at_ms,
            action: DisturbanceAction::Damage { actor: 1, amount },
        }
    }

    fn destruction(at_ms: u64) -> Disturbance {
        Disturbance {
            at_ms,
            action: DisturbanceAction::DestroyArchive { archive: 7 },
        }
    }

    #[test]
    fn damage_applies_at_first_due_update_once_across_reload() {
        let mut s = scenario();
        s.disturbances = vec![damage(501, 25)];
        let mut w = World::new("disturbance-time".into(), s).unwrap();
        w.advance_ms(500);
        assert_eq!(w.players[0].health, 100);
        assert!(w.timing.applied_disturbances.is_empty());
        w.advance_ms(1);
        assert_eq!(w.players[0].health, 75);
        assert!(w.timing.applied_disturbances.contains(&0));
        let intervention = w
            .events
            .iter()
            .find(|e| e.kind == "scenario_disturbance")
            .unwrap();
        assert!(intervention.actor.is_none());
        assert_eq!(intervention.data["scheduled_time_ms"], 501);
        assert_eq!(intervention.data["time_ms"], 501);
        assert!(w
            .events
            .iter()
            .any(|e| e.kind == "damage" && e.parents.contains(&intervention.id)));
        let mut restored: World = serde_json::from_value(json!(w)).unwrap();
        restored.advance_ms(499);
        assert_eq!(restored.players[0].health, 75);
        assert!(!restored
            .events
            .iter()
            .any(|e| e.kind == "scenario_disturbance"));
    }

    #[test]
    fn unsorted_due_entries_use_input_order_and_dead_targets_are_skipped() {
        let mut s = scenario();
        s.disturbances = vec![damage(100, 75), damage(50, 40), damage(0, 10)];
        let mut w = World::new("disturbance-order".into(), s).unwrap();
        w.advance_ms(101);
        let events: Vec<_> = w
            .events
            .iter()
            .filter(|e| e.kind == "scenario_disturbance")
            .collect();
        assert_eq!(
            events
                .iter()
                .map(|e| e.data["index"].as_u64().unwrap())
                .collect::<Vec<_>>(),
            vec![0, 1, 2]
        );
        assert_eq!(events[0].data["time_ms"], 101);
        assert_eq!(events[2].data["status"], "skipped");
        assert_eq!(events[2].data["reason"], "target already dead");
        assert_eq!(w.players[0].health, 0);
        assert_eq!(w.events.iter().filter(|e| e.kind == "death").count(), 1);
        assert_eq!(w.timing.applied_disturbances.len(), 3);
        assert!(!w.players[1]
            .memories
            .iter()
            .any(|m| m.kind == "death" || m.kind == "danger"));
        assert!(w.context(1).get("disturbances").is_none());
    }

    #[test]
    fn archive_destruction_is_local_once_and_does_not_disclose_private_payload() {
        let mut s = scenario();
        s.disturbances = vec![destruction(0), destruction(100)];
        let mut w = World::new("disturbance-archive".into(), s).unwrap();
        // Supplied physical dependency; the production destruction helper is exercised.
        w.archives[0].records.push(knowledge::Record {
            id: "private-record".into(),
            topic: "Route".into(),
            text: "UNPUBLISHED_ARCHIVE_PAYLOAD".into(),
            location: None,
            author: 1,
            origin: 1,
            confidence: 60,
        });
        w.advance_ms(50);
        assert!(w.archives[0].destroyed);
        assert!(w.archives[0].records.is_empty());
        assert_eq!(w.archives[0].revision, 1);
        assert!(w.players[0]
            .memories
            .iter()
            .any(|m| m.kind == "archive_destroyed"));
        assert!(!w.players[1]
            .memories
            .iter()
            .any(|m| m.kind == "archive_destroyed"));
        for i in 0..2 {
            assert!(!w
                .context(i)
                .to_string()
                .contains("UNPUBLISHED_ARCHIVE_PAYLOAD"));
        }
        let mut w: World = serde_json::from_value(json!(w)).unwrap();
        w.advance_ms(50);
        assert_eq!(w.archives[0].revision, 1);
        let skipped = w
            .events
            .iter()
            .find(|e| e.kind == "scenario_disturbance")
            .unwrap();
        assert_eq!(skipped.data["status"], "skipped");
        assert_eq!(skipped.data["reason"], "archive already destroyed");
        assert!(!w.events.iter().any(|e| e.kind == "archive_destroyed"));
    }

    #[test]
    fn failed_damage_law_rolls_back_earlier_intervention_and_consumed_indices() {
        let mut s = scenario();
        s.disturbances = vec![destruction(50), damage(50, 10)];
        let mut w = World::new("disturbance-rollback".into(), s).unwrap();
        let source = w.scripts.history["law"][&1].source.clone();
        w.scripts
            .history
            .get_mut("law")
            .unwrap()
            .get_mut(&1)
            .unwrap()
            .source = source.replace(
            "fn on_damage(c) {",
            "fn on_damage(c) { throw \"fixture damage failure\";",
        );
        w.advance_ms(50);
        assert_eq!(w.timing.time_ms, 0);
        assert!(w.timing.applied_disturbances.is_empty());
        assert!(!w.archives[0].destroyed);
        assert_eq!(w.players[0].health, 100);
        assert!(!w
            .events
            .iter()
            .any(|e| e.kind == "scenario_disturbance" || e.kind == "archive_destroyed"));
        assert!(w
            .events
            .iter()
            .any(|e| e.kind == "script_tick_failed" && e.data["effects_committed"] == false));
        w.scripts
            .history
            .get_mut("law")
            .unwrap()
            .get_mut(&1)
            .unwrap()
            .source = source;
        w.advance_ms(50);
        assert!(w.archives[0].destroyed);
        assert_eq!(w.players[0].health, 90);
        assert_eq!(w.timing.applied_disturbances.len(), 2);
    }

    #[test]
    fn rejected_elapsed_update_cannot_consume_due_intervention() {
        let mut s = scenario();
        s.disturbances = vec![damage(0, 10)];
        let mut w = World::new("disturbance-cancelled".into(), s).unwrap();
        w.advance_ms(60_001);
        assert_eq!(w.timing.time_ms, 0);
        assert_eq!(w.players[0].health, 100);
        assert!(w.timing.applied_disturbances.is_empty());
        w.advance_ms(50);
        assert_eq!(w.players[0].health, 90);
        assert_eq!(w.timing.applied_disturbances.len(), 1);
    }

    #[test]
    fn invalid_references_amounts_times_and_untyped_commands_are_rejected() {
        let mut s = scenario();
        for amount in [-1, 0, 101] {
            s.disturbances = vec![damage(0, amount)];
            assert!(validate(&s).is_err());
        }
        s.disturbances = vec![Disturbance {
            at_ms: 0,
            action: DisturbanceAction::Damage {
                actor: 99,
                amount: 10,
            },
        }];
        assert!(validate(&s).is_err());
        s.disturbances = vec![Disturbance {
            at_ms: 0,
            action: DisturbanceAction::DestroyArchive { archive: 99 },
        }];
        assert!(validate(&s).is_err());
        s.disturbances = vec![damage(s.max_ticks * timing::LEGACY_UNIT_MS + 1, 10)];
        assert!(validate(&s).is_err());
        s.disturbances = vec![damage(0, 10); MAX_DISTURBANCES + 1];
        assert!(validate(&s).is_err());
        s.disturbances = vec![damage(s.max_ticks * timing::LEGACY_UNIT_MS, 100)];
        assert!(validate(&s).is_ok());
        assert!(serde_json::from_value::<Disturbance>(
            json!({"at_ms":0,"kind":"execute","command":"edit_world"})
        )
        .is_err());
        assert!(serde_json::from_value::<Disturbance>(
            json!({"at_ms":0,"kind":"damage","actor":1,"amount":10,"command":"edit_world"})
        )
        .is_err());
        let parsed: Disturbance =
            serde_json::from_value(json!({"at_ms":0,"kind":"damage","actor":1,"amount":10}))
                .unwrap();
        assert!(matches!(
            parsed.action,
            DisturbanceAction::Damage {
                actor: 1,
                amount: 10
            }
        ));
    }
}
