//! Observable body needs are distinct from private reports, motives and intentions.
use crate::*;

type CareInputs = (i32, bool, i32, i32);
type CareResults = BTreeMap<CareInputs, bool>;

impl World {
    fn lifecycle_person(&self, p: &Player, care: Option<&mut CareResults>) -> Value {
        let life = self.lifecycle.get(&p.id);
        let dependent = life.is_some_and(|l| l.dependent);
        let evaluate = || self.law_at::<bool>(p.position,"needs_care", json!({
            "dependent":dependent,"hunger":p.hunger,"health":p.health
        })).unwrap_or(false);
        // A caller may supply this cache only under the exact bundled-law
        // contract. Keys contain the location and every actual hook input.
        // Custom/failing hooks keep their original invocation and fault order.
        let needs_care = if let Some(care) = care {
            *care.entry((p.position, dependent, p.hunger, p.health)).or_insert_with(evaluate)
        } else { evaluate() };
        json!({"id":p.id,"name":p.name,"body":life.map(|l|json!(l.body)).unwrap_or(json!("biological")),
            "dependent":dependent,"needs_care":needs_care,
            "care_meals":life.map_or(0, |l|l.care_meals),"practice":life.map_or(0, |l|l.practice)})
    }

    pub(super) fn local_lifecycle_catalog(&self, i: usize) -> Value {
        if self.initial.lifecycle.is_none() || self.players[i].health <= 0 { return Value::Null; }
        self.local_lifecycle_catalog_with_care_sharing(i, self.local_clock_laws())
    }

    fn local_lifecycle_catalog_with_care_sharing(&self, i: usize, shared: bool) -> Value {
        if self.initial.lifecycle.is_none() { return Value::Null; }
        let me = &self.players[i];
        if me.health <= 0 { return Value::Null; }
        let mut care = shared.then(CareResults::new);
        let people: Vec<_> = self.players.iter()
            .filter(|p| p.health > 0 && p.position == me.position && self.same_arena(me.id, p.id))
            .map(|p| self.lifecycle_person(p, care.as_mut())).collect();
        self.lifecycle_catalog_with_people(i, &people)
    }

    fn lifecycle_catalog_with_people(&self, i: usize, people: &[Value]) -> Value {
        let seed = self.initial.lifecycle.as_ref().expect("lifecycle enabled");
        let me = &self.players[i];
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
        // Only the exact bundled laws establish that observation cannot change
        // these public facts or emit law-fault evidence. Custom laws keep their
        // original invocation order, including failed/fallback evaluations.
        // This cache lives for this refresh only: actions, births, death, care,
        // movement and law activation have already settled before it is built.
        let shared = self.local_clock_laws();
        self.refresh_lifecycle_observations_with_sharing(shared)
    }

    fn refresh_lifecycle_observations_with_sharing(&mut self, shared: bool) -> Result<(), String> {
        if self.initial.lifecycle.is_none() { return Ok(()); }
        let mut groups: BTreeMap<(i32, Option<String>), Vec<Value>> = BTreeMap::new();
        let mut membership = BTreeMap::new();
        let mut catalogs = BTreeMap::<(i32, Option<String>), participant::ExperienceData>::new();
        if shared {
            let mut care = CareResults::new();
            for p in &self.players {
                if p.health <= 0 { continue; }
                let arena = self.arena_for_actor(p.id);
                // An actor without an arena cannot see even itself when arenas
                // are enabled. Do not group such actors into a shared domain.
                if !self.initial.arenas.is_empty() && arena.is_none() { continue; }
                let key = (p.position, arena.map(|a| a.id.clone()));
                membership.insert(p.id, key.clone());
                groups.entry(key).or_default().push(self.lifecycle_person(p, Some(&mut care)));
            }
        }
        for i in 0..self.players.len() {
            if self.players[i].health <= 0 { continue; }
            let current = if shared && self.reproduction_offers.is_empty() {
                // With no offers, all living recipients in this scope receive
                // the same public facts. Encode once, then compare retained JSON
                // without cloning/serializing every person for every recipient.
                // Missing-arena actors still have an empty people list; their
                // position is retained because workshop availability is local.
                let key = membership.get(&self.players[i].id).cloned()
                    .unwrap_or((self.players[i].position, None));
                let people: &[Value] = groups.get(&key).map_or(&[], Vec::as_slice);
                catalogs.entry(key).or_insert_with(||
                    (&self.lifecycle_catalog_with_people(i, people)).into()).clone()
            } else {
                let value = if shared {
                    let people = membership.get(&self.players[i].id).and_then(|key|groups.get(key));
                    self.lifecycle_catalog_with_people(i, people.map_or(&[], Vec::as_slice))
                } else { self.local_lifecycle_catalog_with_care_sharing(i, false) };
                participant::ExperienceData::from(&value)
            };
            let unchanged = if let Some(controller) = self.participants.get(&self.players[i].id).and_then(|p|p.client_controller.as_ref()) {
                controller.last_lifecycle.as_ref().is_some_and(|old| old.matches_data(&current))
            } else { self.players[i].site_observations.iter()
                .find(|m|m.location == self.players[i].position && m.kind == "site")
                .is_some_and(|m| current.matches_value(&m.content["lifecycle"])) };
            if !unchanged {
                // A changed care/development catalog updates those site facts.
                // It does not cause a fresh sighting of every unchanged peer.
                // Death witnesses and explicit Observe retain their own paths.
                if shared { self.observe_site_facts_with_lifecycle(i, Some(current))?; }
                else { self.observe_site_facts(i)?; }
                self.wake(self.players[i].id);
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn compare_refresh(world: &mut World) {
        // Do not warm a custom hook's quarantine before the independent ordered
        // fault comparison below. Bundled care evaluation has no such effects.
        if world.local_clock_laws() {
            for i in 0..world.players.len() {
                assert_eq!(world.local_lifecycle_catalog(i),
                    world.local_lifecycle_catalog_with_care_sharing(i, false),
                    "direct current catalog agrees with original care-hook evaluation");
            }
        }
        let mut reference = world.clone();
        reference.refresh_lifecycle_observations_with_sharing(false).unwrap();
        world.refresh_lifecycle_observations().unwrap();
        fn compare(actual: &Value, expected: &Value, path: &str) {
            match (actual, expected) {
                (Value::Object(a), Value::Object(b)) => {
                    assert_eq!(a.keys().collect::<Vec<_>>(), b.keys().collect::<Vec<_>>(), "keys at {path}");
                    for (k,v) in a { compare(v, &b[k], &format!("{path}/{k}")); }
                }
                (Value::Array(a), Value::Array(b)) => {
                    assert_eq!(a.len(), b.len(), "length at {path}");
                    for (i,(a,b)) in a.iter().zip(b).enumerate() { compare(a,b,&format!("{path}/{i}")); }
                }
                _ => assert_eq!(actual, expected, "value at {path}"),
            }
        }
        compare(&serde_json::to_value(&world.events).unwrap(), &serde_json::to_value(&reference.events).unwrap(), "events");
        assert_eq!(serde_json::to_string(&world.events).unwrap(), serde_json::to_string(&reference.events).unwrap(),
            "encoded composition preserves original event JSON bytes");
        compare(&serde_json::to_value(&*world).unwrap(), &serde_json::to_value(reference).unwrap(), "world");
    }

    #[test]
    fn shared_catalog_preserves_changes_offers_scope_and_recovery() {
        for source in [include_str!("../../scenarios/population-reproduction.json"),
            include_str!("../../scenarios/faction-world-reality.json")] {
            for client in [false, true] {
                let mut scenario: Scenario = serde_json::from_str(source).unwrap();
                if scenario.lifecycle.is_none() {
                    let seed: Scenario = serde_json::from_str(include_str!("../../scenarios/population-reproduction.json")).unwrap();
                    scenario.lifecycle = seed.lifecycle;
                    scenario.lifecycle.as_mut().unwrap().max_total = 64;
                }
                let mut world = World::new("lifecycle-refresh-parity".into(), scenario).unwrap();
                world.enable_participants();
                if client { world.enable_client_controllers().unwrap(); }
                compare_refresh(&mut world);
                let unchanged = serde_json::to_value(&world).unwrap();
                compare_refresh(&mut world);
                assert_eq!(serde_json::to_value(&world).unwrap(), unchanged, "unchanged catalog emits no events");

                // Deliberately mutate dependencies at a completed action boundary.
                // The next refresh must neither reuse old facts nor share offers.
                let actor = world.players[0].id;
                let partner = world.players[1].id;
                world.players[1].position = world.players[0].position;
                world.players[1].hunger = 40;
                if let Some(life) = world.lifecycle.get_mut(&partner) {
                    life.dependent = true;
                    life.care_meals = 1;
                    life.practice = 1;
                }
                world.reproduction_offers.insert(actor, crate::lifecycle::ReproductionOffer {
                    partner, source: 1, expires_ms: world.timing.time_ms + 100,
                    food_commitment: 2, energy_commitment: 10,
                });
                compare_refresh(&mut world);
                world.timing.time_ms += 100;
                compare_refresh(&mut world);
                world.players[1].health = 0;
                compare_refresh(&mut world);
                world.players[0].position += 1;
                compare_refresh(&mut world);
                world = serde_json::from_value(serde_json::to_value(&world).unwrap()).unwrap();
                compare_refresh(&mut world);
            }
        }
    }

    #[test]
    fn catalog_sharing_keeps_overlapping_arenas_separate() {
        let mut scenario: Scenario = serde_json::from_str(include_str!("../../scenarios/luna-arena-matrix.json")).unwrap();
        let lifecycle: Scenario = serde_json::from_str(include_str!("../../scenarios/population-reproduction.json")).unwrap();
        scenario.lifecycle = lifecycle.lifecycle;
        scenario.lifecycle.as_mut().unwrap().max_total = 32;
        // Construct a valid world first, then supply overlapping physical cells
        // as a focused scope fixture. Arena membership still controls visibility.
        let mut world = World::new("lifecycle-arena-parity".into(), scenario).unwrap();
        world.enable_client_controllers().unwrap();
        let position = world.players[0].position;
        for p in &mut world.players { p.position = position; }
        compare_refresh(&mut world);
        for i in 0..world.players.len() {
            let catalog = world.local_lifecycle_catalog(i);
            assert!(catalog["people"].as_array().unwrap().iter().all(|p|
                world.same_arena(world.players[i].id, p["id"].as_u64().unwrap() as u32)));
        }
    }

    #[test]
    fn custom_law_faults_keep_original_evaluation_order() {
        let mut world = World::new("lifecycle-law-parity".into(),
            serde_json::from_str(include_str!("../../scenarios/population-reproduction.json")).unwrap()).unwrap();
        world.enable_client_controllers().unwrap();
        let artifact = laws::compile(&laws::LawDraft { interface_version: 1,
            source: "fn needs_care(c) { throw \"original care-law failure\"; }".into() }).unwrap();
        world.laws.active.insert("universal".into(), 1);
        world.laws.history.entry("universal".into()).or_default().insert(1, laws::LawRevision {
            reference: laws::LawRef { scope: laws::LawScope::Universal, revision: 1 },
            artifact, author: 1, origin: 1, installed_ms: 0,
        });
        assert!(!world.local_clock_laws());
        compare_refresh(&mut world);
        world.flush_law_faults().unwrap();
        assert!(world.events.iter().any(|e| e.kind == "law_hook_quarantined"));
    }

    #[test]
    fn lifecycle_change_retains_death_evidence_without_repeating_peer_sightings() {
        let mut scenario: Scenario = serde_json::from_str(include_str!("../../scenarios/population-reproduction.json")).unwrap();
        let template = scenario.players[0].clone();
        scenario.players = (1..=24).map(|id| { let mut p=template.clone(); p.id=id; p }).collect();
        scenario.arenas[0].actors = (1..=24).collect();
        scenario.arenas[0].controllers.clear();
        scenario.starting_behaviors.clear();
        scenario.lifecycle.as_mut().unwrap().max_total = 32;
        for client in [false, true] {
            let mut world = World::new("lifecycle-death-evidence".into(), scenario.clone()).unwrap();
            world.enable_participants();
            if client { world.enable_client_controllers().unwrap(); }
            world.damage(1, 100, Some(1), 1, "attack").unwrap();
            assert_eq!(world.players[1].health, 0);
            let death_perceptions = world.events.iter().filter(|e|
                e.kind == "perception" && e.data["kind"] == "death").count();
            assert_eq!(death_perceptions, 23, "actual visibility determines death witnesses");
            let before = world.events.len();
            world.refresh_lifecycle_observations().unwrap();
            let perceptions: Vec<_> = world.events[before..].iter().filter(|e|e.kind=="perception").collect();
            assert_eq!(perceptions.len(), 23, "one changed catalog per living recipient");
            for event in perceptions {
                assert_eq!(event.data["kind"], "site");
                let people = event.data["content"]["lifecycle"]["people"].as_array().unwrap();
                assert_eq!(people.len(), 23);
                assert!(people.iter().all(|p|p["id"] != 2));
            }
            if !client {
                assert!(world.players[0].memories.iter().any(|m|m.kind=="death" && m.from==Some(2)),
                    "automatic catalog refresh must not evict death evidence with repeated sightings");
            }
            let before = world.events.len();
            world.observe_site(0).unwrap();
            assert_eq!(world.events[before..].iter().filter(|e|
                e.kind=="perception" && e.data["kind"]=="seen_player").count(), 22,
                "explicit observation still performs the normal visibility and perception path");
        }
    }
}
