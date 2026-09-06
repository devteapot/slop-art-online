//! Configured necessities produced by elapsed-time world laws, never by controllers.
use crate::*;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FoodSource {
    pub position: i32,
    pub interval_ms: u64,
    pub amount: i32,
    pub capacity: i32,
}

pub fn validate(scenario: &Scenario) -> Result<(), String> {
    let mut positions = std::collections::BTreeSet::new();
    for source in &scenario.food_sources {
        if !positions.insert(source.position)
            || !scenario.sites.iter().any(|site| site.position == source.position)
            || !(1_000..=3_600_000).contains(&source.interval_ms)
            || !(1..=100).contains(&source.amount)
            || !(1..=100).contains(&source.capacity)
        {
            return Err("food sources need unique existing sites, interval 1000..3600000 ms, amount/capacity 1..100".into());
        }
    }
    Ok(())
}

impl World {
    pub(super) fn renew_food(&mut self, delta_ms: u64) -> Result<(), String> {
        // Configuration is seed content; the active versioned law chooses production.
        for source in self.initial.food_sources.clone() {
            let remainder = self.timing.food_remainder_ms.entry(source.position).or_default();
            let pulses = timing::pulses(remainder, delta_ms, source.interval_ms)?;
            if pulses == 0 { continue; }
            let index = self.sites.iter().position(|site| site.position == source.position)
                .ok_or("food source site missing")?;
            let before = self.sites[index].food;
            let produced: i32 = self.law_at(source.position,"food_renewal", json!({"source":source,
                "food":before,"pulses":pulses,"elapsed_ms":pulses*source.interval_ms}))?;
            let after = before.checked_add(produced).ok_or("food production overflow")?;
            if produced < 0 || after > 1_000_000 { return Err("invalid food production effect".into()); }
            if produced == 0 { continue; }
            self.sites[index].food = after;
            let event = self.event(None,"resource_produced",vec![],json!({"location":source.position,
                "food_delta":produced,"food_before":before,"food_after":after,"source":source,"pulses":pulses,"law_binding":self.law_binding_at(Some(source.position))}));
            for i in 0..self.players.len() {
                if self.players[i].health > 0 && self.players[i].position == source.position {
                    self.perceive(i,event,"food_growth",None,source.position,json!({"food_delta":produced,"food_after":after}))?;
                    self.observe_site(i)?;
                    self.wake(self.players[i].id);
                }
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scenario() -> Scenario {
        let mut s: Scenario = serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
        s.arenas.clear();
        s.map = None;
        s.weather = None;
        s.max_ticks = 1000;
        s.players.truncate(2);
        for (i,p) in s.players.iter_mut().enumerate() {
            p.controller = Controller::Human;
            p.position = i as i32;
            p.health = 100;
            p.hunger = 10;
            p.food = 2;
            p.energy = 70;
        }
        s.sites = vec![Site {position:0,food:0,hazard:0,shelter:0}, Site {position:1,food:0,hazard:0,shelter:0}];
        s.food_sources = vec![FoodSource {position:0,interval_ms:2500,amount:1,capacity:3}];
        s
    }

    #[test]
    fn production_uses_elapsed_time_survives_reload_and_does_not_bank_at_capacity() {
        for quantum in [50,125,250] {
            let mut w = World::new("renewal-test".into(),scenario()).unwrap();
            for _ in 0..6250/quantum { w.advance_ms(quantum); }
            assert_eq!(w.sites[0].food,2);
            let mut w: World = serde_json::from_value(json!(w)).unwrap();
            w.advance_ms(1250);
            assert_eq!(w.sites[0].food,3);
            w.advance_ms(5000);
            assert_eq!(w.sites[0].food,3);
            w.sites[0].food=0; // Fixture harvests the whole patch after two full pulses.
            w.advance_ms(2499);
            assert_eq!(w.sites[0].food,0);
            w.advance_ms(1);
            assert_eq!(w.sites[0].food,1);
            assert!(!w.events.iter().any(|e|e.kind=="script_tick_failed"));
        }
    }

    #[test]
    fn growth_is_local_evidence_and_plain_sites_remain_finite() {
        let mut w=World::new("renewal-test".into(),scenario()).unwrap();
        w.advance_ms(2500);
        assert!(w.players[0].memories.iter().any(|m|m.kind=="food_growth"));
        assert!(!w.players[1].memories.iter().any(|m|m.kind=="food_growth"));
        assert!(w.players[1].site_observations.iter().all(|m|m.content["food_source"].is_null()));
        assert_eq!(w.players[0].site_observations.last().unwrap().content["food_source"]["capacity"],3);
        assert_eq!(w.sites[1].food,0);
        let mut finite=scenario();finite.food_sources.clear();
        let mut finite=World::new("finite-test".into(),finite).unwrap();
        finite.advance_ms(10000);
        assert!(finite.sites.iter().all(|s|s.food==0));
        assert!(!finite.events.iter().any(|e|e.kind=="resource_produced"));
    }

    #[test]
    fn sources_validate_and_failed_world_laws_commit_no_production_or_time() {
        let mut s=scenario();s.food_sources[0].position=9;
        assert!(World::new("bad-site".into(),s).is_err());
        let mut s=scenario();s.food_sources.push(s.food_sources[0].clone());
        assert!(World::new("duplicate-site".into(),s).is_err());
        let mut s=scenario();s.food_sources[0].interval_ms=0;
        assert!(World::new("bad-period".into(),s).is_err());
        let mut w=World::new("renewal-test".into(),scenario()).unwrap();
        let law=w.scripts.history.get_mut("law").unwrap().get_mut(&1).unwrap();
        law.source=law.source.replace("fn food_renewal(c) { bounded(c.source.amount*c.pulses,0,if c.food < c.source.capacity { c.source.capacity-c.food } else { 0 }) }","fn food_renewal(c) { -1 }");
        w.advance_ms(2500);
        assert_eq!(w.sites[0].food,0);
        assert_eq!(w.timing.time_ms,0);
        assert!(w.events.iter().any(|e|e.kind=="script_tick_failed"));
    }

    #[test]
    fn cultural_labels_do_not_change_production_or_harvesting_costs() {
        let mut base=scenario();base.food_sources[0].amount=2;
        let mut other=base.clone();other.name="Another setting".into();
        other.players[0].name="Another inhabitant".into();other.players[0].role="Another culture".into();
        let mut a=World::new("a".into(),base).unwrap();
        let mut b=World::new("b".into(),other).unwrap();
        for w in [&mut a,&mut b] {
            w.advance_ms(2500);
            w.submit(w.players[0].id,Controller::Human,Decision {reason:"harvest fixture".into(),actions:vec![Action::new(Skill::Gather)],policy:None,reflections:vec![]},None).unwrap();
            w.advance_ms(1000);
        }
        assert_eq!((a.sites[0].food,a.players[0].food,a.players[0].energy),(1,3,66));
        assert_eq!((b.sites[0].food,b.players[0].food,b.players[0].energy),(1,3,66));
    }
}
