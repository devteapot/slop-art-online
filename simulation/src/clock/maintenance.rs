//! Deadlines and physical dependency contracts for independently paced actions.
//! These select work only: the original laws and effects still execute it.
use crate::*;
thread_local! { static BUNDLED: scripting::Registry = scripting::Registry::default(); }

impl World {
    /// A conservative global barrier. Custom laws retain full-world execution
    /// until their time/spatial dependencies have an explicit reviewed contract.
    pub fn next_maintenance_ms(&self) -> u64 {
        let now = self.timing.time_ms;
        if !self.participant_mode || !self.pending.is_empty()
            || self.players.iter().any(|p| !self.client_controlled(p.id))
            || !self.local_clock_laws() {
            return now;
        }
        let settled = self.timing.maintenance_ms.unwrap_or(now);
        let Ok(periods) = self.scripts.law::<timing::Periods>("system_periods_ms", json!({})) else { return now; };
        if !(1..=3_600_000).contains(&periods.needs_ms)
            || !(1..=3_600_000).contains(&periods.hazard_ms) { return now; }
        let after = |period: u64, remainder: u64| settled.saturating_add(period.saturating_sub(remainder));
        let mut due = after(periods.needs_ms, self.timing.needs_remainder_ms)
            .min(after(periods.hazard_ms, self.timing.hazard_remainder_ms))
            .min(self.initial.max_ticks.saturating_mul(timing::LEGACY_UNIT_MS));
        for source in &self.initial.food_sources {
            due = due.min(after(source.interval_ms, self.timing.food_remainder_ms.get(&source.position).copied().unwrap_or(0)));
        }
        for station in &self.infrastructure.stations {
            due = due.min(after(station.seed.generation_period_ms, station.generation_remainder_ms))
                .min(after(self.infrastructure.balance.compute_quantum_ms, station.compute_remainder_ms));
        }
        for (index, disturbance) in self.initial.disturbances.iter().enumerate() {
            if !self.timing.applied_disturbances.contains(&index) { due = due.min(disturbance.at_ms); }
        }
        for player in &self.players {
            if player.health <= 0 { continue; }
            if let Some(life) = self.lifecycle.get(&player.id) {
                if !matches!(life.origin, lifecycle::Origin::Initial) {
                    due = due.min(after(periods.needs_ms, self.timing.actor_needs_remainder_ms.get(&player.id).copied().unwrap_or(0)))
                        .min(after(periods.hazard_ms, self.timing.actor_hazard_remainder_ms.get(&player.id).copied().unwrap_or(0)));
                }
                // Contract for the exact bundled development hook. Care/practice
                // effects still check development in the ordinary action tail.
                if life.dependent && life.care_meals >= 2 && life.practice >= 1 {
                    due = due.min(life.born_ms.saturating_add(60_000));
                }
            }
        }
        for offer in self.reproduction_offers.values() { due = due.min(offer.expires_ms); }
        // Keep overdue/faulted deadlines visible; never defer them into the future.
        due
    }

    pub fn local_clock_laws(&self) -> bool {
        self.scripts.api_version == scripting::API_VERSION
            && self.scripts.pending.is_none() && self.laws.pending.is_empty()
            && self.laws.active.is_empty()
            && self.scripts.active.get("law").and_then(|revision| self.scripts.history.get("law")?.get(revision))
                .is_some_and(|law| law.dependencies.is_empty() && law.source == include_str!("../../scripts/law.rhai"))
    }

    /// Supported action contracts cannot create entities or modify global rules.
    /// All other skills retain the complete shared-kernel transaction for now.
    pub fn local_clock_actor(&self, actor: u32) -> bool {
        let Ok(i) = self.idx(actor) else { return false; };
        let player = &self.players[i];
        if !self.client_controlled(actor) { return false; }
        let supported = |action: &Action, execution: &Execution| {
            if execution.script.as_ref().and_then(|s|s.law_binding.as_ref()).is_some_and(|binding|
                !binding.overlays.is_empty() || self.scripts.definition(&binding.base).is_err()
                || self.scripts.definition(&binding.base).is_ok_and(|law|
                    !law.dependencies.is_empty() || law.source != include_str!("../../scripts/law.rhai"))) { return false; }
            if !matches!(action.skill, Skill::Move | Skill::Gather | Skill::Eat | Skill::Rest
                | Skill::Wait | Skill::Speak | Skill::Attack | Skill::Give | Skill::Deposit
                | Skill::Build | Skill::Observe) { return false; }
            let reference = execution.script.as_ref().map(|s| s.definition.clone())
                .or_else(|| self.scripts.active.get(action.skill.id()).map(|&revision| scripting::DefinitionRef {
                    id: action.skill.id().into(), revision,
                }));
            let Some(reference) = reference else { return false; };
            let Ok(definition) = self.scripts.definition(&reference) else { return false; };
            BUNDLED.with(|bundled| bundled.history.get(action.skill.id()).and_then(|h| h.values().next())
                .is_some_and(|expected| definition.source == expected.source)) && definition.dependencies.iter().all(|dependency|
                dependency.id == "law" && self.scripts.definition(dependency).is_ok_and(|law|
                    law.dependencies.is_empty() && law.source == include_str!("../../scripts/law.rhai")))
        };
        if let Some(execution) = &player.execution {
            let Behavior::Sequence(actions) = &execution.tree else { return false; };
            if actions.len() != 1 || execution.policy.is_some() { return false; }
            let Behavior::Action(action) = &actions[0] else { return false; };
            if !supported(action, execution) { return false; }
        }
        // Speech has the same bounded recipient contract; queued entries can
        // initialize an execution on this update, so check the active definition.
        if let Some(state) = self.participants.get(&actor) {
            if !state.speech.is_empty() {
                let Some(revision) = self.scripts.active.get("speak") else { return false; };
                let Some(definition) = self.scripts.history.get("speak").and_then(|h| h.get(revision)) else { return false; };
                if definition.source != include_str!("../../scripts/speak.rhai") { return false; }
                if !definition.dependencies.iter().all(|dependency| dependency.id=="law"
                    && self.scripts.definition(dependency).is_ok_and(|law|law.dependencies.is_empty()
                        && law.source==include_str!("../../scripts/law.rhai"))) { return false; }
                for speech in &state.speech {
                    if let Some(execution) = &speech.execution {
                        if !supported(&Action::new(Skill::Speak), execution) { return false; }
                    }
                }
            }
        }
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Compare the same physical state at the same instant. Lazy remainders have
    /// a declared earlier origin; normalize just that representation for comparison.
    fn canonical(mut world: World) -> Value {
        if let Some(settled) = world.timing.maintenance_ms.take() {
            let delta = world.timing.time_ms-settled;
            let periods: timing::Periods=world.scripts.law("system_periods_ms",json!({})).unwrap();
            assert_eq!(timing::pulses(&mut world.timing.needs_remainder_ms,delta,periods.needs_ms).unwrap(),0);
            assert_eq!(timing::pulses(&mut world.timing.hazard_remainder_ms,delta,periods.hazard_ms).unwrap(),0);
            for source in &world.initial.food_sources {
                assert_eq!(timing::pulses(world.timing.food_remainder_ms.entry(source.position).or_default(),delta,source.interval_ms).unwrap(),0);
            }
            for station in &mut world.infrastructure.stations {
                assert_eq!(timing::pulses(&mut station.generation_remainder_ms,delta,station.seed.generation_period_ms).unwrap(),0);
                assert_eq!(timing::pulses(&mut station.compute_remainder_ms,delta,world.infrastructure.balance.compute_quantum_ms).unwrap(),0);
            }
            for player in &world.players {
                if player.health<=0 {continue;}
                if let Some(life)=world.lifecycle.get(&player.id).filter(|l|!matches!(l.origin,lifecycle::Origin::Initial)) {
                    let lived=delta.min(world.timing.time_ms.saturating_sub(life.born_ms));
                    assert_eq!(timing::pulses(world.timing.actor_needs_remainder_ms.entry(player.id).or_default(),lived,periods.needs_ms).unwrap(),0);
                    assert_eq!(timing::pulses(world.timing.actor_hazard_remainder_ms.entry(player.id).or_default(),lived,periods.hazard_ms).unwrap(),0);
                }
            }
        }
        json!(world)
    }

    fn pair(source:&str)->(World,World) {
        let mut world=World::new("independent-clock".into(),serde_json::from_str(source).unwrap()).unwrap();
        world.enable_client_controllers().unwrap();
        (world.clone(),world)
    }

    fn advance(reference:&mut World, split:&mut World, delta:u64)->bool {
        let until=split.timing.time_ms+delta;
        let due:Vec<_>=(0..split.players.len()).map(|i|split.actor_clock_hint(i))
            .filter(|hint|hint.active || hint.due_ms<=until).map(|hint|hint.actor).collect();
        let fast=split.next_maintenance_ms()>until && due.iter().all(|actor|split.local_clock_actor(*actor));
        let selection=crate::clock::Selection::new(split,due);
        reference.advance_ms(delta);
        if fast {split.advance_actions_ms(delta,&mut (),&selection,false);}
        else {split.advance_ms_selected(delta,&mut (),Some(&selection));}
        assert_eq!(canonical(split.clone()),json!(reference),"complete state and ordered evidence at {}",reference.timing.time_ms);
        fast
    }

    fn start(world:&mut World,actor:u32,action:Action) {
        use participant::{Request,Command,API_VERSION};
        let revision=world.players[world.idx(actor).unwrap()].generation;
        let receipt=world.participant_apply(actor,Request {api_version:API_VERSION.into(),request_id:format!("action-{}",world.next_event),
            control_epoch:world.participants[&actor].control_epoch,command:Command::StartAction{expected_revision:revision,action}}).unwrap();
        assert!(receipt.ok,"{:?}",receipt.error);
    }

    #[test]
    fn independent_phases_preserve_world_effects_actions_and_reload() {
        for source in [include_str!("../../../scenarios/survival.json"),
            include_str!("../../../scenarios/infrastructure-baseline.json"),
            include_str!("../../../scenarios/population-reproduction.json"),
            include_str!("../../../scenarios/faction-world-reality.json")] {
            let (mut reference,mut split)=pair(source);
            for world in [&mut reference,&mut split] {
                let actor=world.players[0].id;
                start(world,actor,Action::new(Skill::Rest));
            }
            let mut fast=0;
            for n in 0..100 {
                fast+=usize::from(advance(&mut reference,&mut split,[17,33,50,100,250][n%5]));
                if n==35 {split=serde_json::from_value(json!(split)).unwrap();}
            }
            assert!(fast>50,"ordinary actions should not execute global maintenance every frame");
        }
    }

    #[test]
    fn due_food_and_damage_keep_the_same_order_as_contested_actions() {
        let (mut reference,mut split)=pair(include_str!("../../../scenarios/living-clearing.json"));
        for world in [&mut reference,&mut split] {
            for player in &mut world.players {player.position=0;player.food=0;player.energy=100;}
            world.initial.food_sources=vec![ecology::FoodSource {position:0,interval_ms:1000,amount:1,capacity:1}];
            world.sites.iter_mut().find(|s|s.position==0).unwrap().food=0;
            world.initial.disturbances=vec![perturbations::Disturbance {at_ms:1000,
                action:perturbations::DisturbanceAction::Damage{actor:world.players[1].id,amount:100}}];
        }
        for _ in 0..19 {assert!(advance(&mut reference,&mut split,50));}
        for world in [&mut reference,&mut split] {
            for actor in [world.players[0].id,world.players[1].id] {start(world,actor,Action::new(Skill::Gather));}
        }
        assert!(!advance(&mut reference,&mut split,50));
        assert_eq!(split.players[0].food,1);
        assert_eq!(split.players[1].health,0);
    }

    #[test]
    fn custom_law_and_unsupported_action_keep_the_global_path() {
        let (_,mut world)=pair(include_str!("../../../scenarios/survival.json"));
        assert!(world.next_maintenance_ms()>0);
        world.scripts.history.get_mut("law").unwrap().get_mut(&1).unwrap().source.push_str("\n// edited law\n");
        assert_eq!(world.next_maintenance_ms(),world.timing.time_ms);
        let (_,mut world)=pair(include_str!("../../../scenarios/survival.json"));
        let actor=world.players[0].id;
        start(&mut world,actor,Action::new(Skill::Wait));
        assert!(world.local_clock_actor(actor));
        world.scripts.history.get_mut("wait").unwrap().get_mut(&1).unwrap().source.push_str("\n// edited skill\n");
        assert!(!world.local_clock_actor(actor));
    }
}
