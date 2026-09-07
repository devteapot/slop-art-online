//! Exact work selection for the shared clock. Hints are derived state, not a
//! second simulator. Storage persists/indexes them; all effects use World rules.
use crate::{timing, Controller, Player, World};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ActorHint {
    pub actor: u32,
    pub due_ms: u64,
    pub active: bool,
}

pub struct Selection {
    due: BTreeSet<u32>,
    before: BTreeMap<u32, Player>,
    force_all: bool,
}
impl Selection {
    pub fn new(world: &World, due: impl IntoIterator<Item = u32>) -> Self {
        Self {
            due: due.into_iter().collect(),
            before: world.players.iter().map(|p| (p.id, p.clone())).collect(),
            // Activation is ordered before all phases. Recompute hints after
            // installation, including operator changes to physiology periods.
            force_all: world.scripts.pending.is_some() || !world.laws.pending.is_empty(),
        }
    }
    pub(crate) fn includes(&self, world: &World, player: &Player) -> bool {
        self.force_all || self.due.contains(&player.id)
            || world.timing.dirty.get(&player.id) == Some(&true)
            || self.before.get(&player.id).is_none_or(|old| !player.same_snapshot(old))
    }
}

impl World {
    /// Earliest update at which this actor's ordinary phase can do work.
    /// An invalid hook is kept active so the normal clock reports the original
    /// failure; deriving a hint never swallows or commits an engine error.
    pub fn actor_clock_hint(&self, i: usize) -> ActorHint {
        let p = &self.players[i];
        let now = self.timing.time_ms;
        let active = || ActorHint { actor: p.id, due_ms: now, active: true };
        if p.health <= 0 {
            return ActorHint { actor: p.id, due_ms: u64::MAX, active: false };
        }
        let Ok(periods) = self.scripts.law::<timing::Periods>("system_periods_ms", serde_json::json!({})) else {
            return active();
        };
        let Ok(reconsider) = self.scripts.law::<u64>("reconsider_interval", crate::scripting::facts(p)) else {
            return active();
        };
        if !(1..=3_600_000).contains(&periods.needs_ms) || !(1..=3_600_000).contains(&periods.hazard_ms) {
            return active();
        }
        let born = self.lifecycle.get(&p.id)
            .is_some_and(|l| !matches!(l.origin, crate::lifecycle::Origin::Initial));
        let needs = if born { self.timing.actor_needs_remainder_ms.get(&p.id).copied().unwrap_or(0) }
            else { self.timing.needs_remainder_ms };
        let hazard = if born { self.timing.actor_hazard_remainder_ms.get(&p.id).copied().unwrap_or(0) }
            else { self.timing.hazard_remainder_ms };
        let mut due = now.saturating_add(periods.needs_ms.saturating_sub(needs))
            .min(now.saturating_add(periods.hazard_ms.saturating_sub(hazard)));
        if self.timing.dirty.get(&p.id) != Some(&false) { due = now; }
        if let Some(e) = &p.execution { due = due.min(self.execution_ready_at(p.id, e)); }
        // The law above still validates in participant mode, matching the old
        // loop. Its request() is a no-op there. It is also a no-op for a human
        // or an actor already awaiting a legacy model result.
        if !self.participant_mode && p.controller == Controller::Ai
            && !self.pending.iter().any(|r| r.actor == p.id) {
            due = due.min(p.last_reflection.saturating_add(reconsider).saturating_mul(timing::LEGACY_UNIT_MS));
            if self.timing.updates == 0 || p.execution.is_none() { due = now; }
        }
        if let Some(state) = self.participants.get(&p.id) {
            if let Some(q) = state.speech.first() {
                // The reference phase creates the queued continuation on its
                // first update even if a prior utterance still owns cooldown.
                let ready = q.execution.as_ref().map_or(now, |e| self.execution_ready_at(p.id, e));
                due = due.min(ready);
            }
            for q in &state.speech {
                due = due.min(q.expires_tick.saturating_add(1).saturating_mul(timing::LEGACY_UNIT_MS));
            }
        }
        ActorHint { actor: p.id, due_ms: due, active: due <= now }
    }

    pub(crate) fn queued_speech_due(&self, actor: u32) -> bool {
        let Some(state) = self.participants.get(&actor) else { return false; };
        if state.speech.iter().any(|q| q.expires_tick < self.tick) { return true; }
        state.speech.first().is_some_and(|q| q.execution.as_ref()
            .is_none_or(|e| self.timing.time_ms >= self.execution_ready_at(actor, e)))
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::{Action, Decision, Scenario, Skill};

    pub(crate) fn advance_pair(eager: &mut World, selected: &mut World, delta: u64) {
        let due = (0..selected.players.len()).map(|i| selected.actor_clock_hint(i))
            .filter(|h| h.active || h.due_ms <= selected.timing.time_ms.saturating_add(delta))
            .map(|h| h.actor).collect::<Vec<_>>();
        let selection = Selection::new(selected, due);
        eager.advance_ms(delta);
        selected.advance_ms_selected(delta, &mut (), Some(&selection));
        assert_eq!(serde_json::to_value(&*selected).unwrap(), serde_json::to_value(&*eager).unwrap(),
            "full state and ordered evidence at update {}", eager.timing.updates);
    }
    fn worlds(source: &str, participant: bool) -> (World, World) {
        let scenario: Scenario = serde_json::from_str(source).unwrap();
        let mut w = World::new("sim-hybrid-equivalence".into(), scenario).unwrap();
        if participant { w.enable_participants(); }
        (w.clone(), w)
    }

    #[test]
    fn selection_preserves_complete_states_across_world_families_and_reload() {
        for source in [
            include_str!("../../scenarios/survival.json"),
            include_str!("../../scenarios/infrastructure-baseline.json"),
            include_str!("../../scenarios/population-reproduction.json"),
            include_str!("../../scenarios/luna-arena-matrix.json"),
            include_str!("../../scenarios/faction-world-reality.json"),
        ] {
            for participant in [false, true] {
                let (mut eager, mut selected) = worlds(source, participant);
                for n in 0..24 {
                    advance_pair(&mut eager, &mut selected, [50, 75, 250, 1_200, 2_500, 50][n % 6]);
                    if n == 12 {
                        selected = serde_json::from_value(serde_json::to_value(&selected).unwrap()).unwrap();
                    }
                }
            }
        }
    }

    #[test]
    fn sleeping_actor_is_not_selected_and_earlier_actor_can_wake_it_in_order() {
        let (mut eager, mut selected) = worlds(include_str!("../../scenarios/living-clearing.json"), true);
        for w in [&mut eager, &mut selected] {
            for p in &mut w.players { p.execution = None; p.position = 0; p.food = 3; }
            w.advance_ms(50);
            let target = w.players[1].id;
            let actor = w.players[0].id;
            w.participant_manual(actor, Decision { reason: "wake a sleeping recipient through real transfer".into(),
                actions: vec![Action { target: Some(target), ..Action::new(Skill::Give) }],
                policy: None, reflections: vec![] }).unwrap();
        }
        let target = selected.players[1].id;
        assert!(!selected.actor_clock_hint(1).active);
        assert!(selected.actor_clock_hint(1).due_ms > selected.timing.time_ms + 50);
        advance_pair(&mut eager, &mut selected, 50);
        assert!(selected.events.iter().any(|e| e.actor == Some(target)
            && e.kind == "perception" && e.data["kind"] == "received_food"));
        assert_eq!(selected.timing.dirty.get(&target), Some(&false), "later actor consumed same-update wake");
    }

    #[test]
    fn selected_actor_order_preserves_contested_resource_and_failed_attempt() {
        let (mut eager, mut selected) = worlds(include_str!("../../scenarios/living-clearing.json"), true);
        for w in [&mut eager, &mut selected] {
            w.players.swap(0, 1); // Table deadline order must not replace world actor order.
            for p in &mut w.players { p.position = 0; p.execution = None; p.energy = 100; p.food = 0; }
            w.sites.iter_mut().find(|s| s.position == 0).unwrap().food = 1;
            for i in 0..2 {
                let actor = w.players[i].id;
                w.participant_manual(actor, Decision { reason: "compete for one physical item".into(),
                    actions: vec![Action::new(Skill::Gather)], policy: None, reflections: vec![] }).unwrap();
            }
        }
        advance_pair(&mut eager, &mut selected, 50);
        assert_eq!(selected.players[0].food, 1);
        assert_eq!(selected.players[1].food, 0);
        assert!(selected.players[1].failures > 0);
    }

    #[test]
    fn delayed_speech_initialization_fifo_and_expiry_remain_exact() {
        let (mut eager, mut selected) = worlds(include_str!("../../scenarios/living-clearing.json"), true);
        for w in [&mut eager, &mut selected] {
            let actor = w.players[0].id;
            w.timing.dialogue_ready_ms.insert(actor, 10_000);
            w.participant_apply(actor, crate::participant::Request {
                api_version: crate::participant::API_VERSION.into(), request_id: "delayed-voice".into(),
                control_epoch: w.participants[&actor].control_epoch,
                command: crate::participant::Command::Speak { text: "queued speech with a deadline".into(), expires_tick: 1 },
            }).unwrap();
        }
        for delta in [50, 75, 2_375, 2_500, 5_000] {
            advance_pair(&mut eager, &mut selected, delta);
        }
        assert!(selected.events.iter().any(|e| e.kind == "speech_cancelled"
            && e.data["reason"] == "expired before delivery"));
    }

    #[test]
    fn operator_activation_failure_and_long_gap_keep_reference_outcomes() {
        let (mut eager, mut selected) = worlds(include_str!("../../scenarios/living-clearing.json"), true);
        advance_pair(&mut eager, &mut selected, 50);
        for w in [&mut eager, &mut selected] {
            let mut law = w.scripts.history["law"][&w.scripts.active["law"]].clone();
            law.revision += 1;
            law.source = law.source.replace("needs_ms:2500", "needs_ms:0");
            w.stage_scripts_by_operator(crate::scripting::Update {
                api_version: crate::scripting::API_VERSION, expected_revision: w.scripts.revision,
                definitions: vec![law],
            }).unwrap();
        }
        advance_pair(&mut eager, &mut selected, 50);
        assert!(selected.events.iter().any(|e| e.kind == "script_tick_failed"));
        advance_pair(&mut eager, &mut selected, 60_001);
        advance_pair(&mut eager, &mut selected, 50);
    }
}
