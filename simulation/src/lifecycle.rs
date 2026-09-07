//! Material population renewal. Consent, resource accounting and new identities are
//! authoritative; balances and elapsed work live in Rhai, never in a controller.
use crate::*;
use scripting::Effect;
use starting_behaviors::StartingBehavior;

pub const MAX_TOTAL_ACTORS: usize = 256;
pub const MAX_PRACTICE_EVIDENCE: usize = 16;
fn default_max_total() -> usize {
    64
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum BodyKind {
    #[default]
    Biological,
    Artificial,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LifecycleSeed {
    pub workshops: Vec<i32>,
    pub newcomer: NewcomerSeed,
    #[serde(default = "default_max_total")]
    pub max_total: usize,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NewcomerSeed {
    pub name_prefix: String,
    pub motive: String,
    pub caution: i32,
    pub empathy: i32,
    pub introspection: i32,
    pub starting_behavior: StartingBehavior,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "method", rename_all = "snake_case", deny_unknown_fields)]
pub enum Origin {
    Initial,
    Reproduction { parents: [u32; 2] },
    Fabrication { creator: u32, workshop: i32 },
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct CareEvidence {
    pub caregiver: u32,
    pub source: u64,
    pub meals: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct PracticeEvidence {
    pub source: u64,
    pub guide: u32,
    pub record: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Lifecycle {
    pub body: BodyKind,
    pub origin: Origin,
    pub born_ms: u64,
    pub dependent: bool,
    pub care_meals: u32,
    pub practice: u32,
    pub care: Vec<CareEvidence>,
    pub practice_evidence: Vec<PracticeEvidence>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ReproductionOffer {
    pub partner: u32,
    pub source: u64,
    pub expires_ms: u64,
    pub food_commitment: i32,
    pub energy_commitment: i32,
}

fn bounded_cost(value: i32) -> bool {
    (1..=100).contains(&value)
}
fn valid_identity(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 80
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c))
}
impl Lifecycle {
    fn new(body: BodyKind, origin: Origin, born_ms: u64, dependent: bool) -> Self {
        Self {
            body,
            origin,
            born_ms,
            dependent,
            care_meals: 0,
            practice: 0,
            care: vec![],
            practice_evidence: vec![],
        }
    }
}

impl World {
    pub(super) fn initialize_lifecycle(&mut self, _initialization: u64) -> Result<(), String> {
        if !self.lifecycle.is_empty() || !self.reproduction_offers.is_empty() {
            return Err("initial lifecycle state must be created by the authority".into());
        }
        if let Some(seed) = &self.initial.lifecycle {
            if seed.max_total < self.players.len()
                || seed.max_total > MAX_TOTAL_ACTORS
                || seed.workshops.len() > 32
                || seed
                    .workshops
                    .iter()
                    .collect::<std::collections::BTreeSet<_>>()
                    .len()
                    != seed.workshops.len()
                || seed.workshops.iter().any(|&position| {
                    !spatial::walkable(self.initial.map.as_ref(), position)
                        || (!self.initial.arenas.is_empty()
                            && !self.players.iter().any(|p| {
                                spatial::walkable(self.map_for_actor(p.id).as_ref(), position)
                            }))
                })
            {
                return Err("invalid lifecycle capacity or workshop locations".into());
            }
            let n = &seed.newcomer;
            if n.name_prefix.trim().is_empty()
                || n.name_prefix.chars().count() > 60
                || n.motive.trim().is_empty()
                || n.motive.chars().count() > 1500
                || [n.caution, n.empathy, n.introspection]
                    .iter()
                    .any(|v| !(0..=100).contains(v))
            {
                return Err("invalid newcomer identity template".into());
            }
            let habit = &n.starting_behavior;
            if !valid_identity(&habit.id)
                || habit.revision == 0
                || habit.description.trim().is_empty()
                || habit.description.chars().count() > 700
            {
                return Err("invalid newcomer starting behavior identity".into());
            }
            for p in &self.players {
                habit
                    .tree
                    .validate_with_map(&self.scripts, self.map_for_actor(p.id).as_ref())?;
            }
        }
        let next = self
            .players
            .iter()
            .map(|p| p.id)
            .max()
            .unwrap_or(0)
            .checked_add(1);
        if self.initial.lifecycle.is_some() && next.is_none() {
            return Err("initial actor IDs leave no identity for population renewal".into());
        }
        self.next_actor = next.unwrap_or(u32::MAX);
        for p in &self.players {
            self.lifecycle.insert(
                p.id,
                Lifecycle::new(BodyKind::Biological, Origin::Initial, 0, false),
            );
        }
        Ok(())
    }
    fn lifecycle_enabled(&self) -> Result<&LifecycleSeed, String> {
        self.initial
            .lifecycle
            .as_ref()
            .ok_or_else(|| "population renewal is not configured in this world".into())
    }
    fn life(&self, actor: u32) -> Result<&Lifecycle, String> {
        self.lifecycle
            .get(&actor)
            .ok_or_else(|| "actor lifecycle is not registered".into())
    }
    fn local_living_peer(&self, i: usize, target: u32) -> Result<usize, String> {
        let j = self.idx(target)?;
        if i == j
            || self.players[i].health <= 0
            || self.players[j].health <= 0
            || self.players[i].position != self.players[j].position
            || !self.same_arena(self.players[i].id, target)
        {
            return Err("operation requires another living character at the same location".into());
        }
        Ok(j)
    }
    fn independent(&self, i: usize) -> Result<(), String> {
        if self.players[i].health <= 0 || self.life(self.players[i].id)?.dependent {
            return Err("operation requires a living self-supporting character".into());
        }
        Ok(())
    }
    fn reproductive_pair(&self, i: usize, partner: u32) -> Result<usize, String> {
        self.lifecycle_enabled()?;
        self.independent(i)?;
        let j = self.local_living_peer(i, partner)?;
        self.independent(j)?;
        if self.life(self.players[i].id)?.body != BodyKind::Biological
            || self.life(partner)?.body != BodyKind::Biological
        {
            return Err("paired reproduction requires two biological bodies".into());
        }
        Ok(j)
    }
    fn check_capacity(&self, i: usize) -> Result<(), String> {
        let seed = self.lifecycle_enabled()?;
        if self.players.len() >= seed.max_total || self.players.len() >= MAX_TOTAL_ACTORS {
            return Err("this bounded world's retained actor capacity is full".into());
        }
        if self.next_actor == u32::MAX || self.players.iter().any(|p| p.id == self.next_actor) {
            return Err("no unused next actor identity".into());
        }
        if !self.initial.arenas.is_empty() && !self.actor_arenas.contains_key(&self.players[i].id) {
            return Err("creator has no registered arena scope".into());
        }
        Ok(())
    }
    fn quoted_pair(
        &self,
        i: usize,
        partner: u32,
        own_source: u64,
        other_source: u64,
    ) -> Result<(usize, ReproductionOffer, ReproductionOffer), String> {
        let j = self.reproductive_pair(i, partner)?;
        self.check_capacity(i)?;
        let actor = self.players[i].id;
        let own = self
            .reproduction_offers
            .get(&actor)
            .ok_or("your reproduction offer is absent")?;
        let other = self
            .reproduction_offers
            .get(&partner)
            .ok_or("partner reproduction offer is absent")?;
        if own.partner != partner
            || other.partner != actor
            || own.source != own_source
            || other.source != other_source
            || own.expires_ms <= self.timing.time_ms
            || other.expires_ms <= self.timing.time_ms
        {
            return Err("mutual reproduction consent expired, changed, or does not match".into());
        }
        for (person, offer) in [(&self.players[i], own), (&self.players[j], other)] {
            if !bounded_cost(offer.food_commitment)
                || !bounded_cost(offer.energy_commitment)
                || person.food < offer.food_commitment
                || person.energy < offer.energy_commitment
            {
                return Err(
                    "parent cannot meet the explicitly quoted reproduction commitment".into(),
                );
            }
        }
        Ok((j, own.clone(), other.clone()))
    }
    fn check_fabrication(&self, i: usize, food: i32, energy: i32) -> Result<(), String> {
        self.independent(i)?;
        let seed = self.lifecycle_enabled()?;
        self.check_capacity(i)?;
        if !seed.workshops.contains(&self.players[i].position) {
            return Err("fabrication requires a configured workshop at this location".into());
        }
        if !bounded_cost(food)
            || !bounded_cost(energy)
            || self.players[i].food < food
            || self.players[i].energy < energy
        {
            return Err("insufficient food or energy for fabrication".into());
        }
        Ok(())
    }
    fn check_care(
        &self,
        i: usize,
        target: u32,
        energy: i32,
        nutrition: i32,
    ) -> Result<usize, String> {
        self.lifecycle_enabled()?;
        self.independent(i)?;
        let j = self.local_living_peer(i, target)?;
        if !self.life(target)?.dependent {
            return Err("care requires a dependent recipient".into());
        }
        if !bounded_cost(energy)
            || !bounded_cost(nutrition)
            || self.players[i].energy < energy
            || self.players[i].food < 1
            || self.players[j].hunger < nutrition
        {
            return Err(
                "care requires a full needed meal and sufficient caregiver food/energy".into(),
            );
        }
        if self.life(target)?.care_meals == u32::MAX {
            return Err("care accounting overflow".into());
        }
        Ok(j)
    }
    fn check_practice(
        &self,
        i: usize,
        guide: u32,
        record: &str,
        energy: i32,
    ) -> Result<usize, String> {
        self.lifecycle_enabled()?;
        let actor = self.players[i].id;
        let life = self.life(actor)?;
        if !life.dependent {
            return Err("guided practice is for a dependent learner".into());
        }
        let j = self.local_living_peer(i, guide)?;
        self.independent(j)?;
        if !life.care.iter().any(|care| care.caregiver == guide) {
            return Err("guide has not actually cared for this learner".into());
        }
        if !self.players[i].knowledge.iter().any(|h| {
            h.record.id == record
                && h.interpretation.is_some()
                && h.record.location == Some(self.players[i].position)
        }) {
            return Err(
                "practice needs a personally interpreted report about this location".into(),
            );
        }
        if !bounded_cost(energy)
            || self.players[i].energy < energy
            || self.players[i].food.checked_add(1).is_none()
            || !self
                .sites
                .iter()
                .any(|s| s.position == self.players[i].position && s.food > 0)
        {
            return Err("practice requires available local food and learner energy".into());
        }
        if life.practice == u32::MAX {
            return Err("practice accounting overflow".into());
        }
        Ok(j)
    }

    pub(super) fn validate_lifecycle_effect(
        &self,
        i: usize,
        a: &Action,
        effect: &Effect,
    ) -> Result<(), String> {
        self.lifecycle_enabled()?;
        if self.players[i].health <= 0 {
            return Err("dead characters cannot renew or support population".into());
        }
        match effect {
            Effect::OfferReproduction {
                partner,
                expires_ms,
                food,
                energy,
            } => {
                if a.skill.id() != "offer_reproduction" || a.target != Some(*partner) {
                    return Err("offer exceeds selected partner capability".into());
                }
                self.reproductive_pair(i, *partner)?;
                if !bounded_cost(*food)
                    || !bounded_cost(*energy)
                    || *expires_ms <= self.timing.time_ms
                    || *expires_ms > self.timing.time_ms.saturating_add(3_600_000)
                {
                    return Err("invalid reproduction commitment or offer deadline".into());
                }
            }
            Effect::WithdrawReproduction => {
                if a.skill.id() != "withdraw_reproduction" {
                    return Err("withdrawal exceeds own consent capability".into());
                }
            }
            Effect::Reproduce {
                partner,
                own_offer,
                partner_offer,
            } => {
                if a.skill.id() != "reproduce" || a.target != Some(*partner) {
                    return Err("reproduction exceeds selected partner capability".into());
                }
                self.quoted_pair(i, *partner, *own_offer, *partner_offer)?;
            }
            Effect::Fabricate { food, energy } => {
                if a.skill.id() != "fabricate" {
                    return Err("fabrication exceeds selected action capability".into());
                }
                self.check_fabrication(i, *food, *energy)?;
            }
            Effect::Care {
                target,
                energy,
                nutrition,
            } => {
                if a.skill.id() != "care" || a.target != Some(*target) {
                    return Err("care exceeds selected recipient capability".into());
                }
                self.check_care(i, *target, *energy, *nutrition)?;
            }
            Effect::Practice {
                guide,
                record,
                energy,
            } => {
                if a.skill.id() != "practice"
                    || a.target != Some(*guide)
                    || a.record.as_ref() != Some(record)
                {
                    return Err("practice exceeds selected guide or record capability".into());
                }
                self.check_practice(i, *guide, record, *energy)?;
            }
            _ => return Err("effect is not a lifecycle operation".into()),
        }
        Ok(())
    }

    fn consume_food(
        &mut self,
        i: usize,
        amount: i32,
        reason: &str,
        target: Option<u32>,
        cause: u64,
    ) -> Result<(), String> {
        if amount <= 0 || self.players[i].food < amount {
            return Err("food consumption exceeds carried resources".into());
        }
        self.players[i].food -= amount;
        self.event(Some(self.players[i].id), "food_consumed", vec![cause],
            json!({"amount":amount,"reason":reason,"target":target,"food_after":self.players[i].food}));
        Ok(())
    }
    fn create_dependent(
        &mut self,
        i: usize,
        body: BodyKind,
        origin: Origin,
        cause: u64,
    ) -> Result<u32, String> {
        self.check_capacity(i)?;
        let template = self.lifecycle_enabled()?.newcomer.clone();
        let actor = self.next_actor;
        let next = actor.checked_add(1).ok_or("actor identity overflow")?;
        let position = self.players[i].position;
        let arena = self.actor_arenas.get(&self.players[i].id).cloned();
        let (method, creators) = match &origin {
            Origin::Reproduction { parents } => ("reproduction", parents.to_vec()),
            Origin::Fabrication { creator, .. } => ("fabrication", vec![*creator]),
            Origin::Initial => {
                return Err("runtime creation cannot masquerade as an initial actor".into())
            }
        };
        let name = format!("{} {}", template.name_prefix.trim(), actor);
        self.players.push(PlayerData {
            id: actor,
            name: name.clone(),
            controller: Controller::Ai,
            motive: template.motive,
            current_goal: None,
            role: "newcomer".into(),
            position,
            health: 100,
            hunger: 50,
            energy: 50,
            food: 0,
            caution: template.caution,
            empathy: template.empathy,
            introspection: template.introspection,
            fear: 0,
            knowledge: vec![],
            beliefs: vec![],
            relationships: BTreeMap::new(),
            memories: vec![],
            site_observations: vec![],
            execution: None,
            generation: 0,
            failures: 0,
            last_reflection: self.tick,
            last_cause: None,
        }.into());
        let child = self.players.len() - 1;
        self.next_actor = next;
        if let Some(arena) = &arena {
            self.actor_arenas.insert(actor, arena.clone());
        }
        self.lifecycle.insert(
            actor,
            Lifecycle::new(body, origin, self.timing.time_ms, true),
        );
        self.participants
            .insert(actor, participant::ParticipantState::default());
        self.timing
            .action_ready_ms
            .insert(actor, self.timing.time_ms);
        self.timing
            .dialogue_ready_ms
            .insert(actor, self.timing.time_ms);
        self.wake(actor);
        let created = self.event(Some(actor), "actor_created", vec![cause],
            json!({"born_ms":self.timing.time_ms,"method":method,"creators":creators,"arena":arena,
                "initial_resources":{"food":0,"health":100,"hunger":50,"energy":50},"name":name,"body":body}));
        self.perceive(child, created, "own_creation", creators.first().copied(), position,
            json!({"method":method,"creators":creators,"body":body,"dependent":true,
                "meaning":"You are a new individual. No creator's possessions, private knowledge or practical mastery were inherited."}))?;
        self.observe_site(child)?;
        for j in 0..child {
            if self.players[j].health > 0
                && self.players[j].position == position
                && self.same_arena(actor, self.players[j].id)
            {
                self.perceive(j, created, "new_individual", Some(actor), position,
                    json!({"id":actor,"name":name,"method":method,"body":body,"dependent":true,"needs_care":true}))?;
            }
        }
        self.install_starting_behavior(
            actor,
            &template.starting_behavior,
            created,
            "newborn seed habit",
        )?;
        Ok(actor)
    }
    pub(super) fn apply_lifecycle_effect(
        &mut self,
        i: usize,
        cause: u64,
        effect: &Effect,
    ) -> Result<(), String> {
        let actor = self.players[i].id;
        let position = self.players[i].position;
        match effect {
            Effect::OfferReproduction {
                partner,
                expires_ms,
                food,
                energy,
            } => {
                let j = self.reproductive_pair(i, *partner)?;
                let source = self.event(Some(actor), "reproduction_offer", vec![cause],
                    json!({"partner":partner,"expires_ms":expires_ms,"food_commitment":food,"energy_commitment":energy}));
                let offer = ReproductionOffer {
                    partner: *partner,
                    source,
                    expires_ms: *expires_ms,
                    food_commitment: *food,
                    energy_commitment: *energy,
                };
                self.reproduction_offers.insert(actor, offer.clone());
                self.perceive(
                    i,
                    source,
                    "reproduction_offer_sent",
                    Some(*partner),
                    position,
                    json!({"offer":offer}),
                )?;
                self.perceive(
                    j,
                    source,
                    "reproduction_offer_received",
                    Some(actor),
                    position,
                    json!({"offer":offer}),
                )?;
            }
            Effect::WithdrawReproduction => {
                if let Some(offer) = self.reproduction_offers.remove(&actor) {
                    let event = self.event(
                        Some(actor),
                        "reproduction_offer_withdrawn",
                        vec![cause, offer.source],
                        json!({"partner":offer.partner,"offer":offer.source}),
                    );
                    self.perceive(
                        i,
                        event,
                        "reproduction_offer_withdrawn",
                        Some(offer.partner),
                        position,
                        json!({"offer":offer.source}),
                    )?;
                    if let Ok(j) = self.local_living_peer(i, offer.partner) {
                        self.perceive(
                            j,
                            event,
                            "reproduction_offer_withdrawn",
                            Some(actor),
                            position,
                            json!({"offer":offer.source}),
                        )?;
                    }
                }
            }
            Effect::Reproduce {
                partner,
                own_offer,
                partner_offer,
            } => {
                let (j, own, other) = self.quoted_pair(i, *partner, *own_offer, *partner_offer)?;
                let child = self.next_actor;
                self.consume_food(i, own.food_commitment, "reproduction", Some(child), cause)?;
                self.consume_food(j, other.food_commitment, "reproduction", Some(child), cause)?;
                self.players[i].energy -= own.energy_commitment;
                self.players[j].energy -= other.energy_commitment;
                self.reproduction_offers.remove(&actor);
                self.reproduction_offers.remove(partner);
                let agreement = self.event(Some(actor), "reproduction_committed", vec![cause, own.source, other.source],
                    json!({"partner":partner,"child":child,"own_offer":own.source,"partner_offer":other.source}));
                self.create_dependent(
                    i,
                    BodyKind::Biological,
                    Origin::Reproduction {
                        parents: [actor, *partner],
                    },
                    agreement,
                )?;
                self.wake(*partner);
            }
            Effect::Fabricate { food, energy } => {
                self.check_fabrication(i, *food, *energy)?;
                self.consume_food(i, *food, "fabrication", Some(self.next_actor), cause)?;
                self.players[i].energy -= *energy;
                self.create_dependent(
                    i,
                    BodyKind::Artificial,
                    Origin::Fabrication {
                        creator: actor,
                        workshop: position,
                    },
                    cause,
                )?;
            }
            Effect::Care {
                target,
                energy,
                nutrition,
            } => {
                let j = self.check_care(i, *target, *energy, *nutrition)?;
                self.consume_food(i, 1, "care", Some(*target), cause)?;
                self.players[i].energy -= *energy;
                self.players[j].hunger -= *nutrition;
                let event = self.event(Some(actor), "care_given", vec![cause],
                    json!({"target":target,"nutrition":nutrition,"location":position,"recipient_hunger":self.players[j].hunger}));
                let source = self.perceive(
                    j,
                    event,
                    "care_received",
                    Some(actor),
                    position,
                    json!({"nutrition":nutrition,"hunger":self.players[j].hunger}),
                )?;
                let life = self.lifecycle.get_mut(target).unwrap();
                life.care_meals += 1;
                if let Some(care) = life.care.iter_mut().find(|care| care.caregiver == actor) {
                    care.source = source;
                    care.meals = care.meals.saturating_add(1);
                } else {
                    // One entry per actual actor is bounded by max_total (at most256).
                    life.care.push(CareEvidence {
                        caregiver: actor,
                        source,
                        meals: 1,
                    });
                }
                self.perceive(
                    i,
                    event,
                    "care_completed",
                    Some(*target),
                    position,
                    json!({"nutrition":nutrition}),
                )?;
                self.wake(*target);
            }
            Effect::Practice {
                guide,
                record,
                energy,
            } => {
                let j = self.check_practice(i, *guide, record, *energy)?;
                self.players[i].energy -= *energy;
                self.players[i].food += 1;
                let site = self
                    .sites
                    .iter_mut()
                    .find(|s| s.position == position)
                    .unwrap();
                site.food -= 1;
                let food_after = site.food;
                let resource = self.event(Some(actor), "resource_change", vec![cause],
                    json!({"location":position,"food_delta":-1,"food_after":food_after,"nature":"guided_practice"}));
                let held = self.players[i]
                    .knowledge
                    .iter()
                    .find(|h| h.record.id == *record)
                    .unwrap();
                let sources = vec![resource, held.interpreted_source.unwrap_or(held.source)];
                let event = self.event(
                    Some(actor),
                    "practice_completed",
                    sources,
                    json!({"guide":guide,"record":record,"location":position,"gathered":1}),
                );
                let source = self.perceive(
                    i,
                    event,
                    "guided_practice",
                    Some(*guide),
                    position,
                    json!({"record":record,"gathered":1,"food":self.players[i].food}),
                )?;
                let life = self.lifecycle.get_mut(&actor).unwrap();
                life.practice += 1;
                life.practice_evidence.push(PracticeEvidence {
                    source,
                    guide: *guide,
                    record: record.clone(),
                });
                if life.practice_evidence.len() > MAX_PRACTICE_EVIDENCE {
                    life.practice_evidence.remove(0);
                }
                self.perceive(
                    j,
                    event,
                    "practice_guided",
                    Some(actor),
                    position,
                    json!({"gathered":1}),
                )?;
                self.observe_site(i)?;
            }
            _ => return Err("effect is not a lifecycle operation".into()),
        }
        Ok(())
    }

    pub(super) fn advance_lifecycle(&mut self) -> Result<(), String> {
        let expired: Vec<_> = self
            .reproduction_offers
            .iter()
            .filter(|(actor, offer)| {
                offer.expires_ms <= self.timing.time_ms
                    || self
                        .players
                        .iter()
                        .find(|p| p.id == **actor)
                        .is_none_or(|p| p.health <= 0)
            })
            .map(|(actor, offer)| (*actor, offer.clone()))
            .collect();
        for (actor, offer) in expired {
            self.reproduction_offers.remove(&actor);
            let event = self.event(
                Some(actor),
                "reproduction_offer_expired",
                vec![offer.source],
                json!({"offer":offer.source}),
            );
            if let Ok(i) = self.idx(actor) {
                if self.players[i].health > 0 {
                    self.perceive(
                        i,
                        event,
                        "reproduction_offer_expired",
                        None,
                        self.players[i].position,
                        json!({"offer":offer.source}),
                    )?;
                }
            }
        }
        for i in 0..self.players.len() {
            let actor = self.players[i].id;
            let Some(life) = self.lifecycle.get(&actor) else {
                continue;
            };
            if self.players[i].health <= 0 || !life.dependent {
                continue;
            }
            let age_ms = self.timing.time_ms.saturating_sub(life.born_ms);
            let ready: bool = self.actor_law(i,
                "development",
                json!({"body":life.body,"age_ms":age_ms,
                "care_meals":life.care_meals,"practice":life.practice}),
            )?;
            if ready {
                let body = life.body;
                let care_meals = life.care_meals;
                let practice = life.practice;
                let sources = life
                    .care
                    .iter()
                    .map(|c| c.source)
                    .chain(life.practice_evidence.iter().map(|p| p.source))
                    .collect::<Vec<_>>();
                self.lifecycle.get_mut(&actor).unwrap().dependent = false;
                let event = self.event(Some(actor), "self_support_acquired", sources,
                    json!({"body":body,"age_ms":age_ms,"care_meals":care_meals,"practice":practice}));
                self.perceive(i, event, "self_support", None, self.players[i].position,
                    json!({"meaning":"Development, actual care and guided practice now permit independent provisioning. No creator's skills or memories were inherited."}))?;
                self.wake(actor);
            }
        }
        Ok(())
    }
    pub(super) fn lifecycle_script_context(&self, i: usize, a: &Action) -> Value {
        let p = &self.players[i];
        let life = self.lifecycle.get(&p.id);
        let peer = a
            .target
            .and_then(|target| self.local_living_peer(i, target).ok());
        let target = peer.map(|j| {
            let other = &self.players[j];
            let other_life = self.lifecycle.get(&other.id);
            json!({"id":other.id,"position":other.position,"health":other.health,"hunger":other.hunger,
                "food":other.food,"energy":other.energy,"body":other_life.map(|l|l.body).unwrap_or_default(),
                "dependent":other_life.is_some_and(|l|l.dependent)})
        });
        let own_offer = self
            .reproduction_offers
            .get(&p.id)
            .filter(|o| Some(o.partner) == a.target && o.expires_ms > self.timing.time_ms);
        let partner_offer = peer
            .and_then(|j| self.reproduction_offers.get(&self.players[j].id))
            .filter(|o| o.partner == p.id && o.expires_ms > self.timing.time_ms);
        let guided = peer.is_some_and(|j| {
            !self
                .lifecycle
                .get(&self.players[j].id)
                .is_some_and(|l| l.dependent)
                && life.is_some_and(|l| l.care.iter().any(|c| c.caregiver == self.players[j].id))
        });
        let record_ready = a.record.as_ref().is_some_and(|id| {
            p.knowledge.iter().any(|h| {
                &h.record.id == id
                    && h.interpretation.is_some()
                    && h.record.location == Some(p.position)
            })
        });
        json!({"enabled":self.initial.lifecycle.is_some(),
            "own":{"body":life.map(|l|l.body).unwrap_or_default(),"dependent":life.is_some_and(|l|l.dependent),
                "age_ms":life.map(|l|self.timing.time_ms.saturating_sub(l.born_ms)).unwrap_or(0),
                "care_meals":life.map(|l|l.care_meals).unwrap_or(0),"practice":life.map(|l|l.practice).unwrap_or(0)},
            "target":target,"own_offer":own_offer,"partner_offer":partner_offer,
            "workshop":self.initial.lifecycle.as_ref().is_some_and(|s|s.workshops.contains(&p.position)),
            "capacity":self.check_capacity(i).is_ok(),"guided":guided,"record_ready":record_ready,
            "site_food":self.sites.iter().find(|s|s.position==p.position).map(|s|s.food).unwrap_or(0)})
    }
}
