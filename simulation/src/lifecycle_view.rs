//! Observable body needs are distinct from private reports, motives and intentions.
use crate::*;

impl World {
    pub(super) fn local_lifecycle_catalog(&self, i: usize) -> Value {
        let Some(seed) = &self.initial.lifecycle else { return Value::Null; };
        let me = &self.players[i];
        if me.health <= 0 { return Value::Null; }
        let people: Vec<_> = self.players.iter()
            .filter(|p| p.health > 0 && p.position == me.position && self.same_arena(me.id, p.id))
            .map(|p| {
                let life = self.lifecycle.get(&p.id);
                let dependent = life.is_some_and(|l| l.dependent);
                let needs_care = self.law_at::<bool>(p.position,"needs_care", json!({
                    "dependent":dependent,"hunger":p.hunger,"health":p.health
                })).unwrap_or(false);
                json!({"id":p.id,"name":p.name,"body":life.map(|l|json!(l.body)).unwrap_or(json!("biological")),
                    "dependent":dependent,"needs_care":needs_care,
                    "care_meals":life.map_or(0, |l|l.care_meals),"practice":life.map_or(0, |l|l.practice)})
            }).collect();
        let offers: Vec<_> = self.reproduction_offers.iter()
            .filter(|(actor, offer)| offer.partner == me.id && offer.expires_ms > self.timing.time_ms
                && self.players.iter().any(|p| p.id == **actor && p.health > 0 && p.position == me.position
                    && self.same_arena(me.id,p.id)))
            .map(|(actor,offer)|json!({"actor":actor,"offer":offer})).collect();
        json!({"workshop":seed.workshops.contains(&me.position),"people":people,
            "own_offer":self.reproduction_offers.get(&me.id),"offers_to_you":offers})
    }

    pub(super) fn refresh_lifecycle_observations(&mut self) -> Result<(), String> {
        if self.initial.lifecycle.is_none() { return Ok(()); }
        for i in 0..self.players.len() {
            if self.players[i].health <= 0 { continue; }
            let current = self.local_lifecycle_catalog(i);
            let remembered = self.players[i].site_observations.iter()
                .find(|m|m.location == self.players[i].position && m.kind == "site")
                .map(|m|&m.content["lifecycle"]);
            if remembered != Some(&current) {
                self.observe_site(i)?;
                self.wake(self.players[i].id);
            }
        }
        Ok(())
    }
}
