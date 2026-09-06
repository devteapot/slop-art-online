//! Subjective assertions move only between living carriers and physical copies.
//! Audit provenance is an opaque citation, never a content lookup capability.
use crate::*;
use scripting::Effect;

pub const MAX_HOLDINGS: usize = 32;
pub const MAX_ARCHIVES: usize = 32;
pub const MAX_RECORDS: usize = 32;

#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RecordSeed {
    pub id: String,
    pub topic: String,
    pub text: String,
    #[serde(default)]
    pub location: Option<i32>,
    pub confidence: i32,
}
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct KnowledgeDraft {
    pub topic: String,
    pub text: String,
    #[serde(default)]
    pub location: Option<i32>,
    pub confidence: i32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArchiveSeed {
    pub id: u32,
    pub position: i32,
    pub label: String,
    pub capacity: usize,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub id: String,
    pub topic: String,
    pub text: String,
    #[serde(default)]
    pub location: Option<i32>,
    pub author: u32,
    pub origin: u64,
    pub confidence: i32,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Holding {
    pub record: Record,
    pub source: u64,
    pub interpretation: Option<String>,
    #[serde(default)]
    pub interpreted_source: Option<u64>,
    pub confidence: Option<i32>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Archive {
    pub id: u32,
    pub position: i32,
    pub label: String,
    pub capacity: usize,
    pub records: Vec<Record>,
    pub destroyed: bool,
    pub revision: u64,
}

fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 80
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c))
}
fn validate_assertion(topic: &str, text: &str, confidence: i32) -> Result<(), String> {
    if topic.trim().is_empty()
        || topic.chars().count() > 160
        || text.trim().is_empty()
        || text.chars().count() > 1280
        || !(0..=100).contains(&confidence)
    {
        return Err("knowledge requires a topic (1..160 chars), assertion (1..1280 chars), and confidence 0..100".into());
    }
    Ok(())
}
fn check_copy<'a>(
    copies: impl Iterator<Item = &'a Record>,
    record: &Record,
    count: usize,
    capacity: usize,
) -> Result<(), String> {
    if let Some(old) = copies.into_iter().find(|old| old.id == record.id) {
        if old != record {
            return Err("record identity conflicts with existing immutable payload".into());
        }
    } else if count >= capacity {
        return Err("knowledge storage is full".into());
    }
    Ok(())
}

impl World {
    pub(super) fn initialize_knowledge(&mut self, initialization: u64) -> Result<(), String> {
        if self.archives.len() > MAX_ARCHIVES {
            return Err("too many physical archives".into());
        }
        let mut archive_ids = std::collections::BTreeSet::new();
        for archive in &self.archives {
            if !archive_ids.insert(archive.id)
                || archive.label.trim().is_empty()
                || archive.label.chars().count() > 120
                || !(1..=MAX_RECORDS).contains(&archive.capacity)
                || !spatial::walkable(self.initial.map.as_ref(), archive.position)
                || !archive.records.is_empty()
                || archive.destroyed
                || archive.revision != 0
            {
                return Err("invalid initial physical archive".into());
            }
            if !self.initial.arenas.is_empty()
                && !self
                    .players
                    .iter()
                    .any(|p| spatial::walkable(self.map_for_actor(p.id).as_ref(), archive.position))
            {
                return Err("archive outside inhabited arena bounds".into());
            }
        }
        if self.players.iter().any(|p| !p.knowledge.is_empty()) {
            return Err("initial personal knowledge must use scenario knowledge seeds".into());
        }
        let mut record_ids = std::collections::BTreeSet::new();
        // Validate the entire authored batch before creating any perceptions.
        for (actor, seeds) in &self.initial.knowledge {
            self.idx(*actor)?;
            if seeds.len() > MAX_HOLDINGS {
                return Err("too many seeded personal records".into());
            }
            for seed in seeds {
                if !valid_id(&seed.id) || !record_ids.insert(seed.id.clone()) {
                    return Err("invalid or duplicate seeded record identity".into());
                }
                validate_assertion(&seed.topic, &seed.text, seed.confidence)?;
                if seed.location.is_some_and(|location| {
                    !spatial::walkable(self.map_for_actor(*actor).as_ref(), location)
                }) {
                    return Err("seeded assertion location outside actor terrain capability".into());
                }
            }
        }
        for (actor, seeds) in self.initial.knowledge.clone() {
            let i = self.idx(actor)?;
            for seed in seeds {
                let origin = self.event(Some(actor), "knowledge_seeded", vec![initialization],
                    json!({"id":seed.id,"source":"authored initial assertion; not verified world truth"}));
                let record = Record {
                    id: seed.id,
                    topic: seed.topic,
                    text: seed.text,
                    location: seed.location,
                    author: actor,
                    origin,
                    confidence: seed.confidence,
                };
                self.receive_record(i, origin, None, &record, "authored initial assertion")?;
            }
        }
        Ok(())
    }

    fn own_record(&self, i: usize, id: &str) -> Result<&Record, String> {
        if self.players[i].health <= 0 {
            return Err("dead characters cannot transmit knowledge".into());
        }
        self.players[i]
            .knowledge
            .iter()
            .find(|h| h.record.id == id)
            .map(|h| &h.record)
            .ok_or_else(|| "record is not held by this living character".into())
    }
    fn local_archive(&self, i: usize, id: u32) -> Result<&Archive, String> {
        let actor = &self.players[i];
        self.archives
            .iter()
            .find(|archive| {
                archive.id == id
                    && archive.position == actor.position
                    && spatial::walkable(self.map_for_actor(actor.id).as_ref(), archive.position)
            })
            .ok_or_else(|| "archive is not at this character's location".into())
    }
    fn recipient(&self, i: usize, target: u32) -> Result<usize, String> {
        let j = self.idx(target)?;
        if i == j
            || self.players[j].health <= 0
            || self.players[i].health <= 0
            || self.players[j].position != self.players[i].position
            || !self.same_arena(self.players[i].id, target)
        {
            return Err("teaching requires another living character at the same location".into());
        }
        Ok(j)
    }
    fn check_holding(&self, i: usize, record: &Record) -> Result<(), String> {
        check_copy(
            self.players[i].knowledge.iter().map(|h| &h.record),
            record,
            self.players[i].knowledge.len(),
            MAX_HOLDINGS,
        )
    }
    pub(super) fn validate_knowledge_effect(
        &self,
        i: usize,
        a: &Action,
        effect: &Effect,
    ) -> Result<(), String> {
        if self.players[i].health <= 0 {
            return Err("dead characters cannot act on knowledge".into());
        }
        match effect {
            Effect::Teach { target, record } => {
                if a.skill.id() != "teach"
                    || a.target != Some(*target)
                    || a.record.as_ref() != Some(record)
                {
                    return Err("teaching effect exceeds selected record/target capability".into());
                }
                let personal = self.own_record(i, record)?;
                self.check_holding(self.recipient(i, *target)?, personal)?;
            }
            Effect::RecordKnowledge { archive, record } => {
                if a.skill.id() != "record"
                    || a.archive != Some(*archive)
                    || a.record.as_ref() != Some(record)
                {
                    return Err(
                        "recording effect exceeds selected archive/record capability".into(),
                    );
                }
                let personal = self.own_record(i, record)?;
                let archive = self.local_archive(i, *archive)?;
                if archive.destroyed {
                    return Err("archive is destroyed".into());
                }
                check_copy(
                    archive.records.iter(),
                    personal,
                    archive.records.len(),
                    archive.capacity,
                )?;
            }
            Effect::ConsultKnowledge { archive, record } => {
                if a.skill.id() != "consult"
                    || a.archive != Some(*archive)
                    || a.record.as_ref() != Some(record)
                {
                    return Err(
                        "consultation effect exceeds selected archive/record capability".into(),
                    );
                }
                let archive = self.local_archive(i, *archive)?;
                if archive.destroyed {
                    return Err("archive is destroyed".into());
                }
                let record = archive
                    .records
                    .iter()
                    .find(|r| r.id == *record)
                    .ok_or("record is absent from this archive")?;
                self.check_holding(i, record)?;
            }
            Effect::DestroyArchive { archive } => {
                if a.skill.id() != "destroy_archive" || a.archive != Some(*archive) {
                    return Err("destruction effect exceeds selected archive capability".into());
                }
                if self.local_archive(i, *archive)?.destroyed {
                    return Err("archive is already destroyed".into());
                }
            }
            _ => return Err("effect is not a knowledge operation".into()),
        }
        Ok(())
    }

    pub(super) fn receive_record(
        &mut self,
        i: usize,
        cause: u64,
        from: Option<u32>,
        record: &Record,
        via: &str,
    ) -> Result<(), String> {
        self.check_holding(i, record)?;
        let source = self.perceive(i, cause, "knowledge_report", from, self.players[i].position,
            json!({"record":record,"via":via,"new_copy":!self.players[i].knowledge.iter().any(|h| h.record.id == record.id),"meaning":"An attributed assertion, not verified truth or practical skill mastery"}))?;
        if let Some(holding) = self.players[i]
            .knowledge
            .iter_mut()
            .find(|h| h.record.id == record.id)
        {
            holding.source = source;
        } else {
            self.players[i].knowledge.push(Holding {
                record: record.clone(),
                source,
                interpretation: None,
                interpreted_source: None,
                confidence: None,
            });
        }
        // Refresh the citable acquisition while preserving immutable origin and any
        // interpretation, so a fresh consultation can be reflected after old trace expiry.
        self.wake(self.players[i].id);
        Ok(())
    }

    pub(super) fn apply_knowledge_effect(
        &mut self,
        i: usize,
        cause: u64,
        effect: &Effect,
    ) -> Result<(), String> {
        let actor = self.players[i].id;
        let location = self.players[i].position;
        match effect {
            Effect::Teach { target, record } => {
                let record = self.own_record(i, record)?.clone();
                let j = self.recipient(i, *target)?;
                self.check_holding(j, &record)?;
                let event = self.event(
                    Some(actor),
                    "knowledge_taught",
                    vec![cause],
                    json!({"target":target,"record":record.id,"location":location,"new_copy":!self.players[j].knowledge.iter().any(|h| h.record.id == record.id)}),
                );
                self.receive_record(j, event, Some(actor), &record, "teaching")?;
                self.perceive(
                    i,
                    event,
                    "knowledge_taught",
                    Some(*target),
                    location,
                    json!({"record":record.id}),
                )?;
            }
            Effect::RecordKnowledge { archive, record } => {
                let record = self.own_record(i, record)?.clone();
                let local = self.local_archive(i, *archive)?;
                if local.destroyed {
                    return Err("archive is destroyed".into());
                }
                check_copy(
                    local.records.iter(),
                    &record,
                    local.records.len(),
                    local.capacity,
                )?;
                let stored = self.archives.iter_mut().find(|a| a.id == *archive).unwrap();
                let added = !stored.records.iter().any(|r| r.id == record.id);
                if added {
                    stored.records.push(record.clone());
                    stored.revision = stored
                        .revision
                        .checked_add(1)
                        .ok_or("archive revision overflow")?;
                }
                let revision = stored.revision;
                let event = self.event(Some(actor), "knowledge_recorded", vec![cause],
                    json!({"archive":archive,"record":record.id,"location":location,"revision":revision,"added":added,"new_copy":added}));
                self.perceive(
                    i,
                    event,
                    "knowledge_recorded",
                    None,
                    location,
                    json!({"archive":archive,"record":record.id,"revision":revision}),
                )?;
                self.observe_site(i)?;
            }
            Effect::ConsultKnowledge { archive, record } => {
                let local = self.local_archive(i, *archive)?;
                if local.destroyed {
                    return Err("archive is destroyed".into());
                }
                let record = local
                    .records
                    .iter()
                    .find(|r| r.id == *record)
                    .ok_or("record is absent from this archive")?
                    .clone();
                self.check_holding(i, &record)?;
                let event = self.event(
                    Some(actor),
                    "knowledge_consulted",
                    vec![cause],
                    json!({"archive":archive,"record":record.id,"location":location,"new_copy":!self.players[i].knowledge.iter().any(|h| h.record.id == record.id)}),
                );
                self.receive_record(i, event, None, &record, "physical archive consultation")?;
            }
            Effect::DestroyArchive { archive } => {
                self.local_archive(i, *archive)?;
                self.destroy_physical_archive(*archive, cause, Some(actor))?;
            }
            _ => return Err("effect is not a knowledge operation".into()),
        }
        Ok(())
    }

    /// Authoritative callers establish physical authorization; None denotes a seeded
    /// environmental disturbance. Only living witnesses at this site learn of the loss.
    pub(super) fn destroy_physical_archive(
        &mut self,
        archive: u32,
        cause: u64,
        actor: Option<u32>,
    ) -> Result<(), String> {
        let stored = self
            .archives
            .iter_mut()
            .find(|a| a.id == archive)
            .ok_or("unknown archive")?;
        if stored.destroyed {
            return Err("archive is already destroyed".into());
        }
        let revision = stored
            .revision
            .checked_add(1)
            .ok_or("archive revision overflow")?;
        let location = stored.position;
        let count = stored.records.len();
        stored.records.clear();
        stored.destroyed = true;
        stored.revision = revision;
        let event = self.event(actor, "archive_destroyed", vec![cause],
            json!({"archive":archive,"location":location,"copies_destroyed":count,"revision":revision}));
        for j in 0..self.players.len() {
            if self.players[j].health > 0
                && self.players[j].position == location
                && spatial::walkable(self.map_for_actor(self.players[j].id).as_ref(), location)
            {
                self.perceive(
                    j,
                    event,
                    "archive_destroyed",
                    actor,
                    location,
                    json!({"archive":archive,"copies_destroyed":count,"revision":revision}),
                )?;
                self.observe_site(j)?;
            }
        }
        Ok(())
    }

    pub(super) fn interpret_knowledge(
        &mut self,
        i: usize,
        r: &Reflection,
        source: &Percept,
    ) -> Result<(), String> {
        if source.source != r.source {
            return Err("knowledge interpretation evidence does not match cited source".into());
        }
        if let Some(draft) = &r.knowledge {
            validate_assertion(&draft.topic, &draft.text, draft.confidence)?;
            if draft.location.is_some_and(|location| {
                !spatial::walkable(self.map_for_actor(self.players[i].id).as_ref(), location)
            }) {
                return Err("assertion location outside actor terrain capability".into());
            }
            if self.players[i].knowledge.len() >= MAX_HOLDINGS {
                return Err("personal knowledge storage is full".into());
            }
            let actor = self.players[i].id;
            let id = format!("assertion-{actor}-{}", self.next_event);
            if self
                .players
                .iter()
                .flat_map(|p| &p.knowledge)
                .any(|h| h.record.id == id)
                || self
                    .archives
                    .iter()
                    .flat_map(|a| &a.records)
                    .any(|r| r.id == id)
            {
                return Err("generated assertion identity already exists".into());
            }
            let origin = self.event(
                Some(actor),
                "knowledge_asserted",
                vec![r.source],
                json!({"id":id,"interpretation":r.interpretation,"evidence":r.source}),
            );
            let record = Record {
                id,
                topic: draft.topic.clone(),
                text: draft.text.clone(),
                location: draft.location,
                author: actor,
                origin,
                confidence: draft.confidence,
            };
            self.receive_record(
                i,
                origin,
                Some(actor),
                &record,
                "personal interpretation of supplied evidence",
            )?;
            let holding = self.players[i].knowledge.last_mut().unwrap();
            holding.interpretation = Some(r.interpretation.clone());
            holding.interpreted_source = Some(r.source);
            holding.confidence = Some(draft.confidence);
        } else {
            // Source ownership and retention are established by the caller. Resolve
            // only that supplied report, never an origin ID through world/audit state.
            let record = match source.kind.as_str() {
                "knowledge_report" => source.content["record"]["id"].as_str(),
                "perception" if source.content["kind"] == "knowledge_report" => {
                    source.content["content"]["record"]["id"].as_str()
                }
                _ => None,
            };
            if let Some(holding) = self.players[i]
                .knowledge
                .iter_mut()
                .find(|h| Some(h.record.id.as_str()) == record)
            {
                // Acquisition can refresh while a previously read report is still
                // leased. Assessments follow cited evidence order, independently.
                let assessed = holding
                    .interpreted_source
                    .or_else(|| holding.interpretation.as_ref().map(|_| holding.source));
                if assessed.is_none_or(|previous| previous <= r.source) {
                    holding.interpretation = Some(r.interpretation.clone());
                    holding.interpreted_source = Some(r.source);
                }
            }
        }
        Ok(())
    }

    pub(super) fn local_archive_catalog(&self, i: usize) -> Value {
        let actor = &self.players[i];
        json!(self.archives.iter().filter(|archive| actor.health > 0 && archive.position == actor.position
            && spatial::walkable(self.map_for_actor(actor.id).as_ref(), archive.position))
            .map(|archive| json!({"id":archive.id,"position":archive.position,"label":archive.label,
                "revision":archive.revision,"destroyed":archive.destroyed,
                "records":archive.records.iter().filter(|_| !archive.destroyed)
                    .map(|r| json!({"id":r.id,"topic":r.topic,"author":r.author})).collect::<Vec<_>>()})).collect::<Vec<_>>())
    }
    pub(super) fn knowledge_script_context(&self, i: usize, a: &Action) -> Value {
        let record = a
            .record
            .as_deref()
            .and_then(|id| self.own_record(i, id).ok());
        let archive = a.archive.and_then(|id| self.local_archive(i, id).ok()).map(|archive|
            json!({"id":archive.id,"destroyed":archive.destroyed,"revision":archive.revision,
                "capacity":archive.capacity,"record_count":archive.records.len(),
                "contains_record":!archive.destroyed && a.record.as_ref().is_some_and(|id| archive.records.iter().any(|r| &r.id == id))}));
        let target = a.target.and_then(|target| self.recipient(i, target).ok()).map(|j|
            json!({"id":self.players[j].id,"knowledge_count":self.players[j].knowledge.len(),"capacity":MAX_HOLDINGS,
                "has_record":a.record.as_ref().is_some_and(|id| self.players[j].knowledge.iter().any(|h| &h.record.id == id))}));
        json!({"record":record,"archive":archive,"target":target,
            "own_count":self.players[i].knowledge.len(),"own_capacity":MAX_HOLDINGS})
    }
}
