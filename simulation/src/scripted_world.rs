//! Engine capability adapters and transactional script invocation. Gameplay formulas live in scripts.
use crate::*;
use scripting::{facts, Effect};

impl World {
    pub(super) fn apply_decision(
        &mut self,
        actor: u32,
        controller: Controller,
        decision: Decision,
        parent: Option<u64>,
        remembered: Option<Vec<Percept>>,
    ) -> Result<(), String> {
        let mut candidate = self.clone();
        candidate.apply_decision_inner(actor, controller, decision, parent, remembered)?;
        *self = candidate;
        Ok(())
    }
    /// Host must authenticate the world operator before calling this installation boundary.
    pub fn stage_scripts_by_operator(&mut self, update: scripting::Update) -> Result<(), String> {
        self.scripts.stage(update.clone(), self.timing.updates)?;
        self.event(
            None,
            "script_update_staged",
            vec![],
            json!({"activate_update":self.timing.updates+1,"update":update}),
        );
        Ok(())
    }

    pub(super) fn script_context(&self, i: usize, a: &Action, e: &Execution) -> Value {
        let p = &self.players[i];
        let target = a
            .target
            .and_then(|id| self.players.iter().find(|other| other.id == id && self.same_arena(p.id, other.id)))
            .map(|p| json!({"id":p.id,"position":p.position,"health":p.health}));
        // Any destination-bearing scripted skill may inspect this bounded terrain query.
        let navigation = if a.destination.is_some() {
            self.map_for_actor(p.id).as_ref().and_then(|map| a.destination.and_then(|goal| map.route(p.position, goal)))
                .map(|route| json!({"next":route.first().copied().unwrap_or(p.position),"remaining_steps":route.len()}))
        } else {
            None
        };
        let infrastructure_error = a.infrastructure.as_ref().map(|operation| {
            self.validate_infrastructure_effect(i,a,&Effect::Infrastructure {operation:operation.clone()}).err().unwrap_or_default()
        }).unwrap_or_default();
        json!({"infrastructure":self.infrastructure_script_facts(p.id,a.infrastructure.as_ref()),"infrastructure_error":infrastructure_error,"body":self.body_support_context(p.id),"map":self.map_for_actor(p.id),"navigation":navigation,"actor":facts(p),"action":a,"target":target,"knowledge":self.knowledge_script_context(i,a),"lifecycle":self.lifecycle_script_context(i,a),
            "site":self.sites.iter().find(|s| s.position==p.position).map(|s| json!({"position":s.position,"food":s.food,"shelter":s.shelter})),
            "time_ms":self.timing.time_ms,"delta_ms":self.timing.time_ms.saturating_sub(e.script.as_ref().map_or(self.timing.time_ms, |s| s.evaluated_ms)),
            "ready_at_ms":self.execution_ready_at(p.id,e),
            "remaining":e.remaining,"state":e.script.as_ref().map(|s| &s.state),
            "spoke":self.participants.get(&p.id).is_some_and(|s| s.last_speech_tick==Some(self.timing.updates))})
    }

    pub(super) fn execute_action(&mut self, i: usize, e: &mut Execution, a: Action) -> Status {
        if self.timing.time_ms < self.execution_ready_at(self.players[i].id, e) {
            return Status::Running;
        }
        // The audit prefix is append-only and is never an input to skill
        // execution. Personal evidence is already in participant/memory state.
        // Keep that prefix in the parent while the candidate stages new events;
        // otherwise the Nth action copies every earlier action's audit payload.
        let prior_events = std::mem::take(&mut self.events);
        let mut candidate = self.clone();
        self.events = prior_events;
        let mut execution = e.clone();
        match candidate.execute_action_inner(i, &mut execution, a.clone()) {
            Ok(status) => {
                let mut events = std::mem::take(&mut self.events);
                events.append(&mut candidate.events);
                candidate.events = events;
                *self = candidate;
                *e = execution;
                status
            }
            Err(error) => {
                let mut data=json!({"action":a,"definition":e.script,"error":error.message,"effects_committed":false});
                if let Some(denial)=error.law_denial {data["category"]=json!("law_authorization_denied");for (key,value) in denial.as_object().unwrap(){data[key]=value.clone();}}
                let cause = self.event(Some(self.players[i].id), "script_error", e.attempt.into_iter().collect(),data);
                e.attempt = None;
                e.script = None;
                e.remaining = 0;
                self.fail(i, cause, &error.message, e.dialogue)
            }
        }
    }

    pub(super) fn validate_script_effect(
        &self,
        i: usize,
        a: &Action,
        effect: &Effect,
    ) -> Result<(), String> {
        match effect {
            Effect::Infrastructure { .. } => self.validate_infrastructure_effect(i,a,effect)?,
            Effect::OfferReproduction { .. } | Effect::WithdrawReproduction | Effect::Reproduce { .. }
            | Effect::Fabricate { .. } | Effect::Care { .. } | Effect::Practice { .. } => self.validate_lifecycle_effect(i,a,effect)?,
            Effect::Teach { .. } | Effect::RecordKnowledge { .. } | Effect::ConsultKnowledge { .. } | Effect::ReadRecord { .. } | Effect::DestroyArchive { .. } => self.validate_knowledge_effect(i,a,effect)?,
            Effect::TransferFood { target, amount } => {
                let actor = &self.players[i];
                if *amount <= 0 || *amount > actor.food {
                    return Err("food transfer exceeds carried resource".into());
                }
                let destination_food = if let Some(target) = target {
                    let recipient = self.players.iter().find(|p| p.id == *target)
                        .ok_or("unknown food recipient")?;
                    if a.target != Some(*target) || *target == actor.id || recipient.health <= 0
                        || !self.same_arena(actor.id, *target) || recipient.position != actor.position {
                        return Err("food recipient outside local target capability".into());
                    }
                    recipient.food
                } else {
                    self.sites.iter().find(|s| s.position == actor.position)
                        .ok_or("deposit site unavailable")?.food
                };
                if destination_food.checked_add(*amount).is_none() {
                    return Err("food transfer overflow".into());
                }
            }
            Effect::SiteShelter { amount } => {
                let site = self.sites.iter().find(|s| s.position == self.players[i].position)
                    .ok_or("shelter site unavailable")?;
                if *amount <= 0 || site.shelter.checked_add(*amount).is_none_or(|v| v > 12) {
                    return Err("shelter contribution outside site capability".into());
                }
            }
            Effect::Actor { fields } => {
                if fields.get("position").is_some_and(|&position| !spatial::walkable(self.map_for_actor(self.players[i].id).as_ref(), position)) {
                    return Err("position outside actor terrain capability".into());
                }
                if fields
                    .keys()
                    .any(|k| !matches!(k.as_str(), "position" | "energy" | "food" | "hunger"))
                {
                    return Err("script attempted to write outside actor capability".into());
                }
            }
            Effect::SiteFood { .. }
                if !self
                    .sites
                    .iter()
                    .any(|s| s.position == self.players[i].position) =>
            {
                return Err("site capability unavailable".into())
            }
            Effect::Speech { text } if text.trim().is_empty() || text.chars().count() > 1000 => {
                return Err("speech effect exceeds contract".into())
            }
            Effect::Damage { target, amount }
                if a.target != Some(*target)
                    || *target == self.players[i].id
                    || *amount < 0
                    || self.idx(*target).is_err()
                    || !self.same_arena(self.players[i].id, *target) =>
            {
                return Err("damage effect outside target capability".into())
            }
            _ => (),
        }
        let allowed: bool = self.actor_law(i,
            "authorize_effect",
            json!({"actor":facts(&self.players[i]),"action":a,"effect":effect}),
        )?;
        if !allowed {
            return Err("active law denied effect".into());
        }
        let destination = self.effect_destination(effect);
        if let Some(position)=destination {if position!=self.players[i].position {
            let allowed:bool=self.law_at(position,"authorize_effect",json!({"actor":facts(&self.players[i]),"action":a,"effect":effect,"destination":position}))?;
            if !allowed{return Err("destination law denied effect".into());}
        }}
        Ok(())
    }

    pub(super) fn effect_destination(&self,effect:&Effect)->Option<i32> {
        match effect {
            Effect::Actor{fields}=>fields.get("position").copied(),
            Effect::Damage{target,..}|Effect::TransferFood{target:Some(target),..}=>self.players.iter().find(|p|p.id==*target).map(|p|p.position),
            _=>None,
        }
    }

    pub(super) fn apply_script_effect(
        &mut self,
        i: usize,
        cause: u64,
        effect: Effect,
    ) -> Result<(), String> {
        match effect {
            Effect::Infrastructure { .. } => self.apply_infrastructure_effect(i,cause,&effect)?,
            Effect::OfferReproduction { .. } | Effect::WithdrawReproduction | Effect::Reproduce { .. }
            | Effect::Fabricate { .. } | Effect::Care { .. } | Effect::Practice { .. } => self.apply_lifecycle_effect(i,cause,&effect)?,
            Effect::Teach { .. } | Effect::RecordKnowledge { .. } | Effect::ConsultKnowledge { .. } | Effect::ReadRecord { .. } | Effect::DestroyArchive { .. } => self.apply_knowledge_effect(i,cause,&effect)?,
            Effect::TransferFood { target, amount } => {
                let actor = self.players[i].id;
                let location = self.players[i].position;
                self.players[i].food -= amount;
                if let Some(target) = target {
                    let j = self.idx(target)?;
                    self.players[j].food += amount;
                    let id = self.event(Some(actor), "food_transfer", vec![cause],
                        json!({"target":target,"location":location,"amount":amount,"donor_food":self.players[i].food,"recipient_food":self.players[j].food}));
                    self.perceive(j, id, "received_food", Some(actor), location,
                        json!({"amount":amount,"food_after":self.players[j].food}))?;
                    self.perceive(i, id, "gave_food", Some(target), location, json!({"amount":amount}))?;
                    self.wake(target);
                } else {
                    let site = self.sites.iter_mut().find(|s| s.position == location).ok_or("deposit site unavailable")?;
                    site.food += amount;
                    let food_after = site.food;
                    self.event(Some(actor), "resource_change", vec![cause],
                        json!({"location":location,"food_delta":amount,"food_after":food_after,"nature":"deposit"}));
                }
            }
            Effect::SiteShelter { amount } => {
                let location = self.players[i].position;
                let site = self.sites.iter_mut().find(|s| s.position == location).ok_or("shelter site unavailable")?;
                site.shelter += amount;
                let shelter_after = site.shelter;
                let id = self.event(Some(self.players[i].id), "shelter_contribution", vec![cause],
                    json!({"location":location,"amount":amount,"shelter_after":shelter_after}));
                for j in 0..self.players.len() {
                    if j != i && self.players[j].health > 0 && self.players[j].position == location
                        && self.same_arena(self.players[i].id, self.players[j].id) {
                        self.perceive(j, id, "shelter_work", Some(self.players[i].id), location,
                            json!({"amount":amount,"shelter_after":shelter_after}))?;
                        self.observe_site(j)?;
                    }
                }
            }
            Effect::Actor { fields } => {
                for (field, value) in fields {
                    let p = &mut self.players[i];
                    match field.as_str() {
                        "position" => p.position = value,
                        "energy" => p.energy = value,
                        "food" => p.food = value,
                        "hunger" => p.hunger = value,
                        _ => return Err("unknown actor field".into()),
                    }
                }
            }
            Effect::SiteFood { value } => {
                let pos = self.players[i].position;
                let site = self
                    .sites
                    .iter_mut()
                    .find(|s| s.position == pos)
                    .ok_or("site capability unavailable")?;
                let before = site.food;
                site.food = value;
                self.event(Some(self.players[i].id),"resource_change",vec![cause],json!({"location":pos,"food_delta":i64::from(value)-i64::from(before),"food_after":value}));
            }
            Effect::Observe => self.observe_site(i)?,
            Effect::Speech { text } => self.emit_speech(i, cause, &text)?,
            Effect::Damage { target, amount } => self.damage(
                self.idx(target)?,
                amount,
                Some(self.players[i].id),
                cause,
                "attack",
            )?,
        }
        Ok(())
    }

    pub(super) fn visible(&self, viewer: usize, other: usize, kind: &str) -> Result<bool, String> {
        if !self.same_arena(self.players[viewer].id, self.players[other].id) { return Ok(false); }
        self.actor_law(viewer,"visible",json!({"viewer":facts(&self.players[viewer]),"other":facts(&self.players[other]),"kind":kind,"distance":self.initial.map.as_ref().map_or((self.players[viewer].position-self.players[other].position).abs(), |map| map.distance(self.players[viewer].position,self.players[other].position))}))
    }

    pub(super) fn reflect_identity(
        &mut self,
        i: usize,
        r: &Reflection,
        source: &Percept,
    ) -> Result<(), String> {
        let from = source.from;
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Outcome {
            caution: i32,
            trust: i32,
            confidence: i32,
        }
        let trust = from
            .and_then(|id| self.players[i].relationships.get(&id))
            .copied()
            .unwrap_or(0);
        let change:Outcome=self.actor_law(i,"reflection",json!({"actor":facts(&self.players[i]),"trust":trust,"caution_delta":r.caution_delta,"trust_delta":r.trust_delta}))?;
        self.players[i].caution = change.caution;
        if let Some(from) = from {
            self.players[i].relationships.insert(from, change.trust);
        }
        if let Some(b) = &r.belief {
            self.players[i]
                .beliefs
                .retain(|k| k.claim.location != b.location);
            self.players[i].beliefs.push(Known {
                claim: b.clone(),
                source: r.source,
                confidence: change.confidence,
            });
        }
        self.interpret_knowledge(i,r,source)?;
        Ok(())
    }

    pub fn advance_ms(&mut self, delta_ms: u64) {
        self.advance_ms_observed(delta_ms, &mut ());
    }

    pub fn advance_ms_observed(
        &mut self,
        delta_ms: u64,
        observer: &mut impl timing::AdvanceObserver,
    ) {
        if self.stopped || delta_ms == 0 {
            return;
        }
        if delta_ms > 60_000 {
            self.event(None,"script_tick_failed",vec![],json!({"error":"elapsed update exceeds 60000 ms; explicit recovery required","effects_committed":false}));
            return;
        }
        if self.version != VERSION {
            self.event(None,"script_tick_failed",vec![],json!({"error":"saved world requires an explicit rules migration","effects_committed":false}));
            return;
        }
        observer.begin("kernel.clone");
        let mut candidate = self.clone();
        observer.begin("kernel.activation");
        if candidate.scripts.activate(candidate.timing.updates + 1) {
            for p in &candidate.players {
                candidate.timing.dirty.insert(p.id, true);
            }
            candidate.event(None,"script_update_activated",vec![],json!({"effective_update":candidate.timing.updates+1,"revision":candidate.scripts.revision,"active":candidate.scripts.active}));
        }
        let activation=candidate.activate_laws(candidate.timing.updates+1);
        let result = activation.and_then(|_|candidate.step_inner(delta_ms, observer));
        observer.begin("kernel.commit");
        match result {
            Ok(()) => *self = candidate,
            Err(error) => {
                let rejected = self.scripts.pending.take();
                self.event(
                    None,
                    "script_tick_failed",
                    vec![],
                    json!({"error":error,"effects_committed":false,"rejected_update":rejected}),
                );
            }
        }
    }
}
