//! The cognitive loop for every AI character this service controls.
//!
//! - Experiences (SpacetimeDB, written by the authority) are integrated by consolidation:
//!   an LLM reasoning episode writes an open graph patch into the character's Neo4j mind,
//!   updates behavior-facing projections (relations, judgments, places, identity) and
//!   advances the character's `mind_cursor`. Nothing is lost if the service restarts.
//! - Deliberation requests (SpacetimeDB) are answered with a behavior graph and speech,
//!   using the part of the mind that concerns what the character currently perceives.
//! Every reasoning episode is logged as a `thought` with a `reference` the mind graph
//! points back to; exact prompts and replies are journaled on disk.

use crate::llm::{self, Llm, Msg};
use crate::memory::{self, Store};
use crate::prompts;
use anyhow::{anyhow, Result};
use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, Identity, Table};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::sync::{oneshot, Semaphore};

pub enum Event {
    Experience,
    Deliberation(u32),
}

#[derive(Default)]
struct ActorMind {
    consolidating: bool,
    deliberating: bool,
    again: bool,
    last_consolidated: Option<Instant>,
    failures: u32,
    retry_after: Option<Instant>,
    /// Parts of the last graph that were invalid and pruned (fed back next time).
    pruned: Vec<String>,
    /// Integrations since the last reorganization ("sleep") of the mind.
    since_sleep: u32,
    last_sleep: Option<Instant>,
}

pub struct Minds {
    pub conn: DbConnection,
    llm: Llm,
    store: Option<Store>,
    seed: Value,
    species: std::collections::BTreeMap<String, living_rules::species::Species>,
    me: Identity,
    actors: Mutex<HashMap<u32, ActorMind>>,
    sem: Semaphore,
    /// Deferrable work (consolidation, reorganization, identities) may hold at most half of the
    /// model slots, so deliberation (being attacked, spoken to, a plan failing) always gets one.
    slow: Semaphore,
    only: Option<std::collections::HashSet<u32>>,
}

fn flatten<E: std::fmt::Debug>(r: Result<Result<(), String>, E>) -> Result<(), String> {
    match r {
        Ok(r) => r,
        Err(e) => Err(format!("{e:?}")),
    }
}

fn strings(x: &Value) -> Vec<String> {
    x.as_array().map(|a| a.iter().filter_map(|s| s.as_str().map(String::from)).collect()).unwrap_or_default()
}

fn reference(actor: u32, kind: &str) -> String {
    format!("{kind}-{actor}-{}", llm::now_ms())
}

impl Minds {
    pub fn new(conn: DbConnection, llm: Llm, store: Option<Store>, seed: Value, concurrency: usize) -> Result<Arc<Self>> {
        let me = conn.try_identity().ok_or_else(|| anyhow!("not connected"))?;
        let species = living_rules::species::parse(&std::fs::read_to_string(crate::root().join("living/seeds/species.json"))?).map_err(|e| anyhow!(e))?;
        Ok(Arc::new(Self { conn, llm, store, seed, species, me, actors: Mutex::new(HashMap::new()), sem: Semaphore::new(concurrency), slow: Semaphore::new((concurrency / 2).max(1)), only: std::env::var("LIVING_ONLY").ok().map(|v| v.split(',').filter_map(|x| x.trim().parse().ok()).collect()) }))
    }

    fn mine(&self) -> Vec<Character> {
        self.conn.db.character().iter().filter(|c| c.ai && c.alive && c.controller == self.me && self.allowed(c.id)).collect()
    }

    /// `LIVING_ONLY=3,7` limits this service to those characters (experiments on a seeded
    /// world); the rest keep running on their instincts.
    fn allowed(&self, id: u32) -> bool {
        self.only.as_ref().map_or(true, |o| o.contains(&id))
    }

    fn name(&self, id: u32) -> String {
        self.conn.db.character().id().find(&id).map(|c| c.name).unwrap_or_else(|| format!("#{id}"))
    }

    fn fmt_time(&self) -> impl Fn(u64) -> String {
        let w = self.conn.db.world().id().find(&0);
        let (epoch, day) = w.map(|w| (w.epoch_ms, w.day_ms)).unwrap_or((0, living_rules::DEFAULT_DAY_MS));
        move |t| {
            if t == 0 {
                return "long ago".into();
            }
            let h = living_rules::hour_of(t, epoch, day);
            format!("day {} {:02}:{:02}", living_rules::day_of(t, epoch, day), h as u32, (h.fract() * 60.0) as u32)
        }
    }

    fn cursor(&self, actor: u32) -> u64 {
        self.conn.db.mind_cursor().actor().find(&actor).map(|c| c.upto).unwrap_or(0)
    }

    /// This character's experiences in the hot window, oldest first.
    fn experiences(&self, actor: u32) -> Vec<Experience> {
        let mut v: Vec<Experience> = self.conn.db.experience().iter().filter(|e| e.observer == actor).collect();
        v.sort_by_key(|e| e.id);
        v
    }

    /// Experience text with the ids of the people involved, so the mind anchors correctly.
    fn exp_line(&self, e: &Experience, fmt: &dyn Fn(u64) -> String, with_id: bool) -> String {
        let mut who = Vec::new();
        for id in [e.subject, e.object] {
            if id != 0 && id != e.observer {
                if let Some(c) = self.conn.db.character().id().find(&id) {
                    if c.kind == "person" && !who.iter().any(|w: &String| w.ends_with(&format!("#{id}"))) {
                        who.push(format!("{}=#{id}", c.name));
                    }
                }
            }
        }
        let tag = if who.is_empty() { String::new() } else { format!(" {{{}}}", who.join(", ")) };
        if with_id {
            format!("[{}] {} {}{tag}", e.id, fmt(e.at_ms), e.text)
        } else {
            format!("[{}] {}{tag}", fmt(e.at_ms), e.text)
        }
    }

    fn anchors(&self, e: &Experience) -> Vec<String> {
        let mut out = Vec::new();
        for id in [e.subject, e.object] {
            if id == 0 || id == e.observer {
                continue;
            }
            if let Some(c) = self.conn.db.character().id().find(&id) {
                out.push(if c.kind == "person" { format!("person:{id}") } else { format!("kind:{}", c.kind) });
            }
        }
        out
    }

    // ---- bootstrap -------------------------------------------------------------

    pub async fn bootstrap(self: &Arc<Self>) -> Result<()> {
        // Identities that need a model call (residents with only a background) are made
        // concurrently, bounded by the shared LLM semaphore.
        let mut pending = Vec::new();
        for c in self.mine() {
            if let Some(store) = &self.store {
                store.ensure_self(c.id, &c.name).await?;
            }
            if self.conn.db.persona().id().find(&c.id).is_none() {
                if c.parent_a != 0 {
                    self.birth_persona(&c).await?;
                } else if c.kind == "person" && self.conn.db.background().id().find(&c.id).is_some() {
                    let me = self.clone();
                    let c = c.clone();
                    pending.push(tokio::spawn(async move {
                        if let Err(e) = me.background_persona(&c).await {
                            log::warn!("{}: no identity from background yet: {e:#}", c.name);
                        }
                    }));
                } else {
                    self.seed_persona(&c).await?;
                }
            }
        }
        for p in pending {
            let _ = p.await;
        }
        // Re-publish what bodies read from minds (places, relations, judgments), so world state
        // matches the minds after repairs or a restart instead of waiting for each consolidation.
        if self.store.is_some() {
            for c in self.mine() {
                if let Err(e) = self.project(c.id, None, None).await {
                    log::warn!("{}: projection at start failed: {e:#}", c.name);
                }
            }
        }
        for c in self.mine() {
            let model = match self.llm.species_profile(&c.kind, "think") {
                Some(t) => format!("{} (compiled by {})", self.llm.model_name(&t), self.llm.model_name(&self.llm.species_profile(&c.kind, "compile").unwrap_or_default())),
                None => self.llm.model_name(&self.llm.profile_for(c.id, &c.name)),
            };
            log::info!("{} the {} (#{}) thinks with {model}; mind cursor at {}", c.name, c.kind, c.id, self.cursor(c.id));
        }
        Ok(())
    }

    /// An animal's starting self: its species nature and a temperament of its own.
    async fn animal_persona(&self, c: &Character) -> Result<()> {
        let Some(sp) = self.species.get(&c.kind) else { return Ok(()) };
        let mut h: u64 = 0xcbf29ce484222325 ^ c.id as u64;
        let mut traits = serde_json::Map::new();
        for (k, [lo, hi]) in &sp.temperament {
            h = (h ^ k.len() as u64).wrapping_mul(0x100000001b3).rotate_left(17);
            let t = (h % 1000) as f32 / 1000.0;
            traits.insert(k.clone(), json!((lo + (hi - lo) * t).round()));
        }
        let persona = json!({
            "narrative": format!("I am {}, a {}.", c.name, c.kind),
            "values": [], "goals": [],
            "traits": traits,
            "mood": "alert",
        });
        let thought = reference(c.id, "born");
        let now = llm::now_ms();
        if let Some(store) = &self.store {
            let mut patch = memory::Patch::default();
            memory::sugar_into(&json!({"places": [{"name": "home", "x": c.home_x, "y": c.home_y}]}), &mut patch, &[]);
            store.ensure_self(c.id, &c.name).await?;
            store.apply(c.id, &patch, &thought, now).await?;
            store.set_identity(c.id, 1, &persona, "born", &thought, now).await?;
        }
        let p = PersonaIn { narrative: persona["narrative"].as_str().unwrap_or_default().into(), values: Vec::new(), goals: Vec::new(), traits: persona["traits"].to_string(), mood: "alert".into() };
        self.project(c.id, Some(p), None).await
    }

    async fn seed_persona(&self, c: &Character) -> Result<()> {
        if c.kind != "person" {
            return self.animal_persona(c).await;
        }
        let Some(p) = self.seed["people"].as_array().and_then(|ps| ps.iter().find(|p| p["name"] == c.name.as_str())) else { return Ok(()) };
        let persona = p["persona"].clone();
        let thought = reference(c.id, "seed");
        let now = llm::now_ms();
        let mut patch = memory::Patch::default();
        let mut sugar = json!({"relations": [], "places": [{"name": "home", "x": c.home_x, "y": c.home_y}]});
        for r in p["relations"].as_array().cloned().unwrap_or_default() {
            let Some(other) = self.conn.db.character().iter().find(|o| o.name == r["name"].as_str().unwrap_or_default()) else { continue };
            patch.nodes.push(memory::NodeOp { key: format!("person:{}", other.id), labels: vec!["Person".into()], name: Some(other.name.clone()), props: Default::default() });
            sugar["relations"].as_array_mut().unwrap().push(json!({"id": other.id, "trust": r["trust"], "affinity": r["affinity"], "label": r["label"], "note": r["note"]}));
        }
        memory::sugar_into(&sugar, &mut patch, &[]);
        if let Some(store) = &self.store {
            store.ensure_self(c.id, &c.name).await?;
            store.apply(c.id, &patch, &thought, now).await?;
            store.set_identity(c.id, 1, &persona, "who I was when this began", &thought, now).await?;
        }
        let persona = PersonaIn {
            narrative: persona["narrative"].as_str().unwrap_or_default().into(),
            values: strings(&persona["values"]),
            goals: strings(&persona["goals"]),
            traits: persona["traits"].to_string(),
            mood: persona["mood"].as_str().unwrap_or_default().into(),
        };
        self.project(c.id, Some(persona), None).await
    }

    /// A seeded resident's starting identity, written by their mind from their background
    /// (town, occupation, household or band history). Afterwards it is ordinary identity.
    async fn background_persona(&self, c: &Character) -> Result<()> {
        let bg: Value = self.conn.db.background().id().find(&c.id).and_then(|b| serde_json::from_str(&b.text).ok()).unwrap_or_default();
        let profile = self.llm.profile_for(c.id, &c.name);
        let system = format!(
            "You create the starting identity of a person in a persistent simulated world. {}\n\n\
The person has lived before this moment: use their background, but give them an individual temperament, private hopes, worries, \
likes and grudges of their own (not a job description; what they did so far is history, not destiny). Write the narrative in the first person, \
2-4 sentences. Relations: how they feel about each person named in the background (trust and affinity -100..100, a label such as \
family, partner, friend, rival, stranger, and a short note in their words). Reply with ONE JSON object: {{\"narrative\": \"...\", \"values\": [...], \"goals\": [...], \
\"traits\": {{\"caution\": 0-100, \"sociability\": 0-100, \"empathy\": 0-100, \"curiosity\": 0-100, \"ambition\": 0-100, \"introspection\": 0-100, \"temper\": 0-100}}, \"mood\": \"...\", \
\"relations\": [{{\"id\": person id, \"trust\": 0, \"affinity\": 0, \"label\": \"...\", \"note\": \"...\"}}]}}",
            prompts::world_rules()
        );
        let knows: Vec<String> = self.conn.db.know_how().iter().filter(|k| k.actor == c.id).map(|k| k.technique).collect();
        let user = format!("Person: {} (#{}). Knows how to: {}.\nBackground: {}", c.name, c.id, if knows.is_empty() { "nothing special".into() } else { knows.join(", ") }, bg);
        let reply = {
            let _slow = self.slow.acquire().await?;
            let _permit = self.sem.acquire().await?;
            self.llm.chat(&profile, "consolidate", &c.name, &[Msg { role: "system", content: system }, Msg { role: "user", content: user }]).await?
        };
        let v = llm::parse_json(&reply.content)?;
        let thought = reference(c.id, "background");
        let now = llm::now_ms();
        let known: Vec<u32> = ["household", "companions"].iter().flat_map(|k| bg[*k].as_array().cloned().unwrap_or_default()).filter_map(|p| p["id"].as_u64().map(|i| i as u32)).collect();
        let mut places = vec![json!({"name": "home", "x": c.home_x, "y": c.home_y})];
        if let Some([x, y]) = bg["town_center"].as_array().map(|a| [a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0)]) {
            places.push(json!({"name": format!("{} center", bg["town"].as_str().unwrap_or("town")), "x": x, "y": y}));
        }
        if let Some([x, y]) = bg["camp"].as_array().map(|a| [a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0)]) {
            places.push(json!({"name": "camp", "x": x, "y": y}));
        }
        let relations: Vec<Value> = v["relations"].as_array().cloned().unwrap_or_default().into_iter().filter(|r| r["id"].as_u64().map_or(false, |i| known.contains(&(i as u32)))).collect();
        if let Some(store) = &self.store {
            let mut patch = memory::Patch::default();
            for id in &known {
                patch.nodes.push(memory::NodeOp { key: format!("person:{id}"), labels: vec!["Person".into()], name: Some(self.name(*id)), props: Default::default() });
            }
            memory::sugar_into(&json!({"relations": relations, "places": places}), &mut patch, &[]);
            store.ensure_self(c.id, &c.name).await?;
            store.apply(c.id, &patch, &thought, now).await?;
            store.set_identity(c.id, 1, &v, "who I was when this began", &thought, now).await?;
        }
        log::info!("{} (#{}) from background: {}", c.name, c.id, v["narrative"].as_str().unwrap_or_default());
        let persona = PersonaIn {
            narrative: v["narrative"].as_str().unwrap_or_default().into(),
            values: strings(&v["values"]),
            goals: strings(&v["goals"]),
            traits: v["traits"].to_string(),
            mood: v["mood"].as_str().unwrap_or("settled").into(),
        };
        let t = ThoughtIn { kind: "consolidate".into(), summary: "Who I am, from where I come from.".into(), detail: v.to_string(), latency_ms: reply.latency_ms, tokens: reply.tokens, model: reply.model, reference: thought };
        self.project(c.id, Some(persona), Some(t)).await
    }

    /// A newborn's starting identity: its own temperament, raised by its parents.
    async fn birth_persona(&self, c: &Character) -> Result<()> {
        let parent = |id: u32| {
            let name = self.name(id);
            let p = self.conn.db.persona().id().find(&id).map(|p| format!("{} Values: {}. Traits: {}", p.narrative, p.values.join("; "), p.traits)).unwrap_or_default();
            (name, p)
        };
        let (an, ap) = parent(c.parent_a);
        let (bn, bp) = parent(c.parent_b);
        let profile = self.llm.profile_for(c.id, &c.name);
        let system = format!(
            "You create the starting identity of a newborn person in a persistent simulated world. {}\n\nThe child has its own temperament: \
traits are influenced by the parents but varied (never copied), and the child knows almost nothing yet. Write the narrative in the first person, \
simple and short, as a very young child. Reply with ONE JSON object: {{\"narrative\": \"...\", \"values\": [...], \"goals\": [...], \
\"traits\": {{\"caution\": 0-100, \"sociability\": 0-100, \"empathy\": 0-100, \"curiosity\": 0-100, \"ambition\": 0-100, \"introspection\": 0-100, \"temper\": 0-100}}, \"mood\": \"...\"}}",
            prompts::world_rules()
        );
        let user = format!("Newborn: {} (#{}).\nParent {} (#{}): {}\nParent {} (#{}): {}", c.name, c.id, an, c.parent_a, ap, bn, c.parent_b, bp);
        let _slow = self.slow.acquire().await?;
        let _permit = self.sem.acquire().await?;
        let reply = self.llm.chat(&profile, "consolidate", &c.name, &[Msg { role: "system", content: system }, Msg { role: "user", content: user }]).await?;
        let v = llm::parse_json(&reply.content)?;
        let thought = reference(c.id, "birth");
        let now = llm::now_ms();
        let parents: Vec<(u32, String)> = [(c.parent_a, an.clone()), (c.parent_b, bn.clone())].into_iter().filter(|(id, _)| *id != 0).collect();
        if let Some(store) = &self.store {
            let mut patch = memory::Patch::default();
            for (id, name) in &parents {
                let key = format!("person:{id}");
                patch.nodes.push(memory::NodeOp { key: key.clone(), labels: vec!["Person".into(), "Parent".into()], name: Some(name.clone()), props: Default::default() });
                patch.edges.push(memory::EdgeOp { from: "self".into(), rel: "CHILD_OF".into(), to: key, confidence: 1.0, because: Vec::new(), props: Default::default() });
            }
            let sugar = json!({
                "relations": parents.iter().map(|(id, _)| json!({"id": id, "trust": 70, "affinity": 80, "label": "parent"})).collect::<Vec<_>>(),
                "places": [{"name": "home", "x": c.home_x, "y": c.home_y}]
            });
            memory::sugar_into(&sugar, &mut patch, &[]);
            store.ensure_self(c.id, &c.name).await?;
            store.apply(c.id, &patch, &thought, now).await?;
            store.set_identity(c.id, 1, &v, "born", &thought, now).await?;
        }
        log::info!("{} was born to {an} and {bn}: {}", c.name, v["narrative"].as_str().unwrap_or_default());
        let persona = PersonaIn {
            narrative: v["narrative"].as_str().unwrap_or_default().into(),
            values: strings(&v["values"]),
            goals: strings(&v["goals"]),
            traits: v["traits"].to_string(),
            mood: v["mood"].as_str().unwrap_or("curious").into(),
        };
        let t = ThoughtIn { kind: "consolidate".into(), summary: format!("Born to {an} and {bn}."), detail: v.to_string(), latency_ms: reply.latency_ms, tokens: reply.tokens, model: reply.model, reference: thought };
        self.project(c.id, Some(persona), Some(t)).await
    }

    /// Recompute what the body reads from the mind (relations, judgments, places and the
    /// observer's belief summary) and publish it with an optional identity and thought.
    async fn project(&self, actor: u32, persona: Option<PersonaIn>, thought: Option<ThoughtIn>) -> Result<()> {
        let Some(store) = &self.store else {
            return self.update(actor, MindUpdate { persona, relations: Vec::new(), beliefs: None, judgments: Vec::new(), places: Vec::new(), thought, replace: false }).await;
        };
        let fmt = self.fmt_time();
        let p = store.projection(actor).await?;
        let facts = store.around(actor, &[], 30).await.unwrap_or_default();
        let relations = p
            .feelings
            .into_iter()
            .filter(|(id, ..)| *id != actor && self.conn.db.character().id().find(id).map_or(false, |c| c.kind == "person"))
            .map(|(other, trust, affinity, label, note)| RelationIn { other, trust: trust as f32, affinity: affinity as f32, label, note })
            .collect();
        let judgments = p.judgments.into_iter().map(|(key, value, why)| JudgmentIn { key, value: value as f32, why }).collect();
        let places = p.places.into_iter().map(|(name, x, y)| PlaceIn { name, x: x as f32, y: y as f32 }).collect();
        let beliefs = Some(facts.iter().map(|f| BeliefIn { about: format!("{} → {}", f.a, f.b), text: memory::render(f, &fmt), confidence: f.confidence as f32 }).collect());
        self.update(actor, MindUpdate { persona, relations, beliefs, judgments, places, thought, replace: true }).await
    }

    // ---- reducer calls -----------------------------------------------------------

    async fn update(&self, actor: u32, u: MindUpdate) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_update_then(actor, u, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_update: {e}"))
    }

    async fn consolidated(&self, actor: u32, upto: u64) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_consolidated_then(actor, upto, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_consolidated: {e}"))
    }

    #[allow(clippy::too_many_arguments)]
    async fn install(&self, actor: u32, graph: String, plan: String, say: String, to: u32, seen: u64, t: ThoughtIn) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_install_then(actor, graph, plan, say, to, seen, t, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_install: {e}"))
    }

    async fn skip(&self, actor: u32, seen: u64, t: ThoughtIn) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_skip_then(actor, seen, t, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_skip: {e}"))
    }

    // ---- event loop -------------------------------------------------------------

    pub async fn run(self: Arc<Self>, mut rx: tokio::sync::mpsc::UnboundedReceiver<Event>) -> Result<()> {
        let mut tick = tokio::time::interval(Duration::from_millis(2000));
        for d in self.conn.db.my_deliberations().iter() {
            self.clone().schedule(d.actor);
        }
        loop {
            tokio::select! {
                ev = rx.recv() => match ev {
                    Some(Event::Experience) => {}
                    Some(Event::Deliberation(actor)) => self.clone().schedule(actor),
                    None => return Err(anyhow!("event channel closed")),
                },
                _ = tick.tick() => self.clone().check_consolidation(),
            }
        }
    }

    fn schedule(self: Arc<Self>, actor: u32) {
        if !self.allowed(actor) {
            return;
        }
        {
            let mut a = self.actors.lock().unwrap();
            let m = a.entry(actor).or_default();
            if m.deliberating {
                m.again = true;
                return;
            }
            m.deliberating = true;
        }
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(400)).await;
            let mut seen = 0u64;
            loop {
                let pending = self.conn.db.my_deliberations().iter().find(|d| d.actor == actor && d.updated_ms > seen);
                let Some(d) = pending else { break };
                seen = d.updated_ms;
                if let Err(e) = self.deliberate(&d).await {
                    log::warn!("deliberation for {} failed: {e:#}", self.name(actor));
                }
                let again = std::mem::take(&mut self.actors.lock().unwrap().entry(actor).or_default().again);
                if !again {
                    tokio::time::sleep(Duration::from_millis(300)).await;
                }
            }
            self.actors.lock().unwrap().entry(actor).or_default().deliberating = false;
        });
    }

    fn consolidation_threshold(&self, actor: u32) -> f32 {
        if let Some(c) = self.conn.db.character().id().find(&actor).filter(|c| c.kind != "person") {
            return self.species.get(&c.kind).map(|s| s.cognition.consolidate_threshold).unwrap_or(3.0);
        }
        let intro = self
            .conn
            .db
            .persona()
            .id()
            .find(&actor)
            .and_then(|p| serde_json::from_str::<Value>(&p.traits).ok())
            .and_then(|t| t["introspection"].as_f64())
            .unwrap_or(50.0) as f32;
        3.2 * (1.35 - intro / 100.0)
    }

    /// Start consolidation for characters whose unintegrated experiences matter enough.
    fn check_consolidation(self: Arc<Self>) {
        for c in self.mine() {
            let cursor = self.cursor(c.id);
            let pending: Vec<Experience> = self.experiences(c.id).into_iter().filter(|e| e.id > cursor).collect();
            let meaningful: Vec<&Experience> = pending.iter().filter(|e| e.salience >= 0.2).collect();
            let salience: f32 = meaningful.iter().map(|e| e.salience).sum();
            let due = {
                let mut a = self.actors.lock().unwrap();
                let m = a.entry(c.id).or_default();
                let stale = m.last_consolidated.map_or(true, |t| t.elapsed() > Duration::from_secs(240));
                let min_gap = self.species.get(&c.kind).map(|s| s.cognition.consolidate_min_s).unwrap_or(90);
                let rested = m.last_consolidated.map_or(true, |t| t.elapsed() > Duration::from_secs(min_gap));
                let wanted = (rested && (salience >= self.consolidation_threshold(c.id) || meaningful.len() >= 30 || (stale && meaningful.len() >= 4))) || pending.len() >= 120;
                let allowed = !m.consolidating && m.retry_after.map_or(true, |t| Instant::now() >= t);
                let sleepy = m.since_sleep >= 6 || (m.since_sleep >= 2 && m.last_sleep.map_or(true, |t| t.elapsed() > Duration::from_secs(20 * 60)));
                if allowed && (wanted || sleepy) {
                    m.consolidating = true;
                    Some(!wanted)
                } else {
                    None
                }
            };
            let Some(sleep) = due else { continue };
            let this = self.clone();
            let actor = c.id;
            tokio::spawn(async move {
                let r = if sleep { this.reorganize(actor).await } else { this.consolidate(actor).await };
                if r.is_ok() {
                    let mut a = this.actors.lock().unwrap();
                    let m = a.entry(actor).or_default();
                    if sleep {
                        m.since_sleep = 0;
                        m.last_sleep = Some(Instant::now());
                    } else {
                        m.since_sleep += 1;
                    }
                }
                let mut a = this.actors.lock().unwrap();
                let m = a.entry(actor).or_default();
                m.consolidating = false;
                match r {
                    Ok(()) => {
                        m.failures = 0;
                        m.retry_after = None;
                        m.last_consolidated = Some(Instant::now());
                    }
                    Err(e) => {
                        m.failures += 1;
                        m.retry_after = Some(Instant::now() + Duration::from_secs(20 * m.failures as u64));
                        log::warn!("consolidation for {} failed ({}x): {e:#}", this.name(actor), m.failures);
                    }
                }
            });
        }
    }

    // ---- shared context -----------------------------------------------------------

    fn persona_text(&self, actor: u32) -> String {
        match self.conn.db.persona().id().find(&actor) {
            Some(p) => {
                let mut knows: Vec<String> = self.conn.db.know_how().iter().filter(|k| k.actor == actor).map(|k| k.technique).collect();
                knows.sort();
                let know = if knows.is_empty() { "nothing yet".to_string() } else { knows.join(", ") };
                let belong = match self.conn.db.membership().member().find(&actor) {
                    Some(m) => {
                        let name = self.conn.db.community().id().find(&m.community).map(|c| c.name).unwrap_or_default();
                        let others: Vec<String> = self.conn.db.membership().iter().filter(|x| x.community == m.community && x.member != actor).map(|x| self.name(x.member)).collect();
                        format!("\nYou belong to {name}{}", if others.is_empty() { String::new() } else { format!(" (with {})", others.join(", ")) })
                    }
                    None => "\nYou belong to no community.".into(),
                };
                format!("{}\nValues: {}\nGoals: {}\nTraits: {}\nMood: {}\nYou know how to: {know}{belong}", p.narrative, p.values.join("; "), p.goals.join("; "), p.traits, p.mood)
            }
            None => "(no persona yet)".into(),
        }
    }

    fn relations(&self, actor: u32) -> Vec<String> {
        let mut rs: Vec<Relation> = self.conn.db.relation().iter().filter(|r| r.actor == actor).collect();
        rs.sort_by(|a, b| (b.trust.abs() + b.affinity.abs()).total_cmp(&(a.trust.abs() + a.affinity.abs())));
        rs.into_iter()
            .take(16)
            .map(|r| {
                format!(
                    "{} (#{}): {}, trust {:.0}, affinity {:.0}{}",
                    self.name(r.other),
                    r.other,
                    r.label,
                    r.trust,
                    r.affinity,
                    if r.note.is_empty() { String::new() } else { format!(" — {}", r.note) }
                )
            })
            .collect()
    }

    fn judgments(&self, actor: u32) -> Vec<String> {
        self.conn.db.judgment().iter().filter(|j| j.actor == actor).map(|j| format!("{} = {:.2} ({})", j.key, j.value, j.why)).collect()
    }

    fn places(&self, actor: u32) -> Vec<String> {
        self.conn.db.place().iter().filter(|p| p.actor == actor).map(|p| format!("\"{}\" at [{:.0}, {:.0}]", p.name, p.x, p.y)).collect()
    }

    async fn mind_lines(&self, actor: u32, seeds: &[String], limit: usize) -> (Vec<String>, Vec<String>) {
        let Some(store) = &self.store else { return (Vec::new(), Vec::new()) };
        let fmt = self.fmt_time();
        let facts = store.around(actor, seeds, limit).await.unwrap_or_else(|e| {
            log::warn!("mind query for {actor}: {e:#}");
            Vec::new()
        });
        let memories = store.memories(actor, 8).await.unwrap_or_default();
        let mut facts: Vec<String> = facts.iter().map(|f| memory::render(f, &fmt)).collect();
        facts.reverse();
        let memories = memories.into_iter().rev().map(|(exp, t, gist)| format!("[{}] {gist} (experience {exp})", fmt(t))).collect();
        (facts, memories)
    }

    // ---- deliberation ------------------------------------------------------------

    async fn deliberate(&self, d: &Deliberation) -> Result<()> {
        let actor = d.actor;
        let Some(c) = self.conn.db.character().id().find(&actor) else { return Ok(()) };
        if !c.alive {
            return Ok(());
        }
        if self.conn.db.persona().id().find(&actor).is_none() {
            if let Some(store) = &self.store {
                store.ensure_self(c.id, &c.name).await?;
            }
            if c.parent_a != 0 {
                self.birth_persona(&c).await?;
            } else {
                self.seed_persona(&c).await?;
            }
            for _ in 0..20 {
                if self.conn.db.persona().id().find(&actor).is_some() {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        }
        if c.kind != "person" {
            return self.deliberate_animal(d, &c).await;
        }
        let profile = self.llm.profile_for(actor, &c.name);
        let scene: Value = serde_json::from_str(&d.scene).unwrap_or(json!({}));
        let mut seeds = vec!["self".to_string()];
        for cr in scene["creatures"].as_array().cloned().unwrap_or_default() {
            if cr["kind"] == "person" {
                seeds.push(format!("person:{}", cr["id"]));
            } else if let Some(k) = cr["kind"].as_str() {
                seeds.push(format!("kind:{k}"));
            }
        }
        for key in ["resources", "structures"] {
            for r in scene[key].as_array().cloned().unwrap_or_default() {
                if let Some(k) = r["kind"].as_str() {
                    seeds.push(format!("kind:{k}"));
                }
            }
        }
        let (mind, memories) = self.mind_lines(actor, &seeds, 30).await;
        let brain = self.conn.db.brain().id().find(&actor);
        // Show the mind its own graph; the body habits are described, not repeated (models
        // copied the layer back into their graphs, making them deeper and longer).
        let outline = brain
            .as_ref()
            .and_then(|b| living_rules::graph::parse(&b.graph).ok())
            .map(|g| match g.root {
                living_rules::graph::Node::First(c) if c.label.as_deref() == Some("reflexes") => {
                    let own = c.children.last().map(living_rules::graph::outline).unwrap_or_default();
                    format!("(your body habits run before this)\n{own}")
                }
                root => living_rules::graph::outline(&root),
            })
            .unwrap_or_default();
        let plan = brain.as_ref().map(|b| b.plan.clone()).unwrap_or_default();
        let fmt = self.fmt_time();
        let experiences: Vec<String> = {
            let all = self.experiences(actor);
            let n = all.len();
            all.iter().skip(n.saturating_sub(16)).map(|e| self.exp_line(e, &fmt, false)).collect()
        };
        let pruned = self.actors.lock().unwrap().entry(actor).or_default().pruned.clone();
        let mut reason = d.reason.clone();
        if !pruned.is_empty() {
            reason.push_str(&format!("\n(Note: parts of your previous graph were invalid and dropped: {})", pruned.join("; ")));
        }
        let ctx = prompts::Ctx {
            name: &c.name,
            clock: fmt(llm::now_ms()),
            persona: self.persona_text(actor),
            relations: self.relations(actor),
            mind,
            memories,
            judgments: self.judgments(actor),
            places: self.places(actor),
            experiences,
        };
        let system = prompts::deliberate_system(&c.name);
        let user = prompts::deliberate_user(&ctx, &d.scene, &outline, &plan, &reason);
        let _permit = self.sem.acquire().await?;
        let mut messages = vec![Msg { role: "system", content: system }, Msg { role: "user", content: user }];
        let mut last_err = String::new();
        let mut total_latency = 0u32;
        let mut total_tokens = 0u32;
        let thought_ref = reference(actor, "deliberate");
        let mut profile = profile;
        for attempt in 0..3 {
            let reply = match self.llm.chat(&profile, "deliberate", &c.name, &messages).await {
                Ok(r) => r,
                Err(e) => {
                    last_err = format!("model error: {e:#}");
                    break;
                }
            };
            total_latency += reply.latency_ms;
            total_tokens += reply.tokens;
            // Only talking: keep the current behavior and just speak.
            if let Ok(v) = llm::parse_json(&reply.content) {
                if v["graph"].is_null() || v["graph"].as_str().map_or(false, |g| g.trim().eq_ignore_ascii_case("keep")) {
                    let (say, to) = match &v["say"] {
                        Value::String(s) => (s.clone(), 0),
                        Value::Object(o) => (o.get("text").and_then(|t| t.as_str()).unwrap_or_default().to_string(), o.get("to").and_then(|t| t.as_u64()).unwrap_or(0) as u32),
                        _ => (String::new(), 0),
                    };
                    let thought = v["thought"].as_str().unwrap_or_default().to_string();
                    let t = ThoughtIn {
                        kind: "deliberate".into(),
                        summary: format!("{thought} → (carries on){}", if say.is_empty() { String::new() } else { format!(" and says “{say}”") }),
                        detail: json!({"reason": d.reason, "reply": v, "attempts": attempt + 1}).to_string(),
                        latency_ms: total_latency,
                        tokens: total_tokens,
                        model: reply.model.clone(),
                        reference: thought_ref.clone(),
                    };
                    log::info!("{} carries on{}", c.name, if say.is_empty() { String::new() } else { format!(" — says “{say}”") });
                    let (tx, rx) = oneshot::channel();
                    self.conn.reducers.mind_say_then(actor, say, to, d.updated_ms, t, move |_, r| {
                        let _ = tx.send(flatten(r));
                    })?;
                    return rx.await?.map_err(|e| anyhow!("mind_say: {e}"));
                }
            }
            // A patch replaces one labeled branch (e.g. combat tactics mid-fight) and keeps the rest.
            let current = self.conn.db.brain().id().find(&actor).and_then(|b| serde_json::from_str::<Value>(&b.graph).ok());
            let parsed = llm::parse_json(&reply.content).and_then(|mut v| {
                if v["patch"].is_object() && (v["graph"].is_null() || v["graph"].is_string()) {
                    let label = v["patch"]["label"].as_str().unwrap_or("combat").to_string();
                    let node = v["patch"]["graph"].clone();
                    v["graph"] = patch_branch(current.clone().unwrap_or(json!({"wait": 3})), &label, node);
                }
                let (g, pruned) = living_rules::graph::from_value_lenient(v["graph"].clone()).map_err(|e| anyhow!(e))?;
                Ok((v, g, pruned))
            });
            match parsed {
                Ok((v, g, pruned)) => {
                    self.actors.lock().unwrap().entry(actor).or_default().pruned = pruned.clone();
                    let (say, to) = match &v["say"] {
                        Value::String(s) => (s.clone(), 0),
                        Value::Object(o) => (o.get("text").and_then(|t| t.as_str()).unwrap_or_default().to_string(), o.get("to").and_then(|t| t.as_u64()).unwrap_or(0) as u32),
                        _ => (String::new(), 0),
                    };
                    let plan = v["plan"].as_str().unwrap_or_default().to_string();
                    let thought = v["thought"].as_str().unwrap_or_default().to_string();
                    let mut patch = memory::Patch::default();
                    memory::sugar_into(&json!({"judgments": v["judgments"], "places": v["places"]}), &mut patch, &[]);
                    if !patch.nodes.is_empty() || !patch.edges.is_empty() {
                        if let Some(store) = &self.store {
                            store.apply(actor, &patch, &thought_ref, llm::now_ms()).await?;
                        }
                        self.project(actor, None, None).await?;
                    }
                    let t = ThoughtIn {
                        kind: "deliberate".into(),
                        summary: format!("{thought} → {plan}"),
                        detail: json!({"reason": d.reason, "reply": v, "attempts": attempt + 1, "pruned": pruned}).to_string(),
                        latency_ms: total_latency,
                        tokens: total_tokens,
                        model: reply.model.clone(),
                        reference: thought_ref.clone(),
                    };
                    log::info!("{} decided: {plan}{}", c.name, if say.is_empty() { String::new() } else { format!(" — says “{say}”") });
                    return self.install(actor, g.to_json(), plan, say, to, d.updated_ms, t).await;
                }
                Err(e) => {
                    last_err = format!("{e:#}");
                    // A reply that is not JSON at all is usually a degenerate generation (runs of
                    // whitespace or brackets): retry with the most reliable model, and don't
                    // send the runaway text back.
                    let unusable = llm::parse_json(&reply.content).is_err();
                    if unusable && profile != self.llm.default_profile() {
                        log::warn!("{}: unusable reply from {} ({} chars); retrying with {}", c.name, reply.model, reply.content.len(), self.llm.default_profile());
                        profile = self.llm.default_profile();
                    }
                    messages.push(Msg { role: "assistant", content: reply.content.chars().take(3000).collect() });
                    messages.push(Msg { role: "user", content: format!("That reply was rejected: {last_err}. Return the complete corrected JSON object.") });
                }
            }
        }
        let t = ThoughtIn {
            kind: "error".into(),
            summary: format!("could not decide: {last_err}"),
            detail: String::new(),
            latency_ms: total_latency,
            tokens: total_tokens,
            model: self.llm.model_name(&profile),
            reference: thought_ref,
        };
        self.skip(actor, d.updated_ms, t).await
    }

    /// Animals: a small model feels an impulse; a competent model compiles it into a graph
    /// the body allows. The compiler is told to add nothing the animal does not have.
    async fn deliberate_animal(&self, d: &Deliberation, c: &Character) -> Result<()> {
        let actor = c.id;
        let Some(sp) = self.species.get(&c.kind).cloned() else { return Ok(()) };
        let think = self.llm.species_profile(&c.kind, "think").unwrap_or_else(|| self.llm.profile_for(actor, &c.name));
        let compile = self.llm.species_profile(&c.kind, "compile").unwrap_or_else(|| self.llm.profile_for(actor, &c.name));
        let fmt = self.fmt_time();
        let scene: Value = serde_json::from_str(&d.scene).unwrap_or(json!({}));
        let mut seeds = vec!["self".to_string()];
        for cr in scene["creatures"].as_array().cloned().unwrap_or_default() {
            seeds.push(if cr["kind"] == "person" { format!("person:{}", cr["id"]) } else { format!("kind:{}", cr["kind"].as_str().unwrap_or_default()) });
        }
        let (mind, _) = self.mind_lines(actor, &seeds, 12).await;
        let experiences: Vec<String> = {
            let all = self.experiences(actor);
            let n = all.len();
            all.iter().skip(n.saturating_sub(8)).map(|e| self.exp_line(e, &fmt, false)).collect()
        };
        let temperament = self.conn.db.persona().id().find(&actor).map(|p| format!("{} (mood: {})", p.traits, p.mood)).unwrap_or_default();
        let thought_ref = reference(actor, "deliberate");
        let _permit = self.sem.acquire().await?;
        let felt = self
            .llm
            .chat(&think, "deliberate", &c.name, &[
                Msg { role: "system", content: prompts::animal_think_system(&c.name, &c.kind, &sp.nature, &temperament) },
                Msg { role: "user", content: prompts::animal_think_user(&mind, &experiences, &d.scene, &d.reason) },
            ])
            .await?;
        let (feeling, impulse) = match llm::parse_json(&felt.content) {
            Ok(v) => (flat(&v["feeling"]), flat(&v["impulse"])),
            Err(_) => (String::new(), felt.content.chars().take(400).collect()),
        };
        let signals = sp.signals.iter().map(|(k, s)| format!("{k} = {}", s.sound)).collect::<Vec<_>>().join("; ");
        let system = prompts::animal_compile_system(&c.kind, &living_rules::species::skills_help(&sp), &signals, sp.cognition.max_nodes);
        let user = format!("Impulse of {} the {}: {impulse}\nFeeling: {feeling}\n\nAround it now:\n{}\n\nIts current graph:\n{}", c.name, c.kind, d.scene,
            self.conn.db.brain().id().find(&actor).and_then(|b| living_rules::graph::parse(&b.graph).ok()).map(|g| living_rules::graph::outline(&g.root)).unwrap_or_default());
        let mut messages = vec![Msg { role: "system", content: system }, Msg { role: "user", content: user }];
        let mut last_err = String::new();
        let (mut latency, mut tokens) = (felt.latency_ms, felt.tokens);
        for attempt in 0..3 {
            let reply = self.llm.chat(&compile, "deliberate", &c.name, &messages).await?;
            latency += reply.latency_ms;
            tokens += reply.tokens;
            let parsed = llm::parse_json(&reply.content).and_then(|v| {
                let (g, pruned) = living_rules::graph::from_value_for(v["graph"].clone(), &sp).map_err(|e| anyhow!(e))?;
                Ok((v, g, pruned))
            });
            match parsed {
                Ok((v, g, pruned)) => {
                    let t = ThoughtIn {
                        kind: "deliberate".into(),
                        summary: format!("{feeling} → {impulse}"),
                        detail: json!({"reason": d.reason, "feeling": feeling, "impulse": impulse, "think_model": felt.model, "compiled": v, "attempts": attempt + 1, "pruned": pruned}).to_string(),
                        latency_ms: latency,
                        tokens,
                        model: format!("{} → {}", felt.model, reply.model),
                        reference: thought_ref.clone(),
                    };
                    log::info!("{} the {} feels: {feeling} → {impulse}", c.name, c.kind);
                    return self.install(actor, g.to_json(), impulse.clone(), String::new(), 0, d.updated_ms, t).await;
                }
                Err(e) => {
                    last_err = format!("{e:#}");
                    messages.push(Msg { role: "assistant", content: reply.content });
                    messages.push(Msg { role: "user", content: format!("That reply was rejected: {last_err}. Return the complete corrected JSON object.") });
                }
            }
        }
        let t = ThoughtIn { kind: "error".into(), summary: format!("could not act on: {impulse} ({last_err})"), detail: String::new(), latency_ms: latency, tokens, model: self.llm.model_name(&compile), reference: thought_ref };
        self.skip(actor, d.updated_ms, t).await
    }

    // ---- consolidation ------------------------------------------------------------

    async fn consolidate(&self, actor: u32) -> Result<()> {
        let Some(c) = self.conn.db.character().id().find(&actor) else { return Ok(()) };
        let cursor = self.cursor(actor);
        let batch: Vec<Experience> = self.experiences(actor).into_iter().filter(|e| e.id > cursor).take(40).collect();
        let Some(upto) = batch.last().map(|e| e.id) else { return Ok(()) };
        // Only experiences that carry meaning go to the model; routine results are passed over.
        let meaningful: Vec<&Experience> = batch.iter().filter(|e| e.salience >= 0.2).collect();
        if meaningful.is_empty() {
            return self.consolidated(actor, upto).await;
        }
        let profile = self.llm.profile_for(actor, &c.name);
        let fmt = self.fmt_time();
        let mut seeds = vec!["self".to_string()];
        for e in &meaningful {
            seeds.extend(self.anchors(e));
        }
        seeds.sort();
        seeds.dedup();
        let (mind, memories) = self.mind_lines(actor, &seeds, 40).await;
        let ctx = prompts::Ctx {
            name: &c.name,
            clock: fmt(llm::now_ms()),
            persona: self.persona_text(actor),
            relations: self.relations(actor),
            mind,
            memories,
            judgments: self.judgments(actor),
            places: self.places(actor),
            experiences: meaningful.iter().map(|e| self.exp_line(e, &fmt, true)).collect(),
        };
        let animal = c.kind != "person";
        let system = match self.species.get(&c.kind).filter(|_| animal) {
            Some(sp) => prompts::animal_consolidate_system(&c.name, &c.kind, &sp.nature),
            None => prompts::consolidate_system(&c.name),
        };
        let user = prompts::consolidate_user(&ctx);
        let remember = if animal { self.llm.species_profile(&c.kind, "remember").unwrap_or(profile.clone()) } else { profile.clone() };
        let _slow = self.slow.acquire().await?;
        let _permit = self.sem.acquire().await?;
        let msgs = [Msg { role: "system", content: system }, Msg { role: "user", content: user }];
        let mut reply = self.llm.chat(&remember, "consolidate", &c.name, &msgs).await?;
        let v = match llm::parse_json(&reply.content) {
            Ok(v) => v,
            // A small mind's unusable output is re-done by the competent model.
            Err(e) if animal => {
                let compile = self.llm.species_profile(&c.kind, "compile").unwrap_or(profile.clone());
                log::info!("{}'s memory reply was unusable ({e:#}); retrying with {compile}", c.name);
                reply = self.llm.chat(&compile, "consolidate", &c.name, &msgs).await?;
                llm::parse_json(&reply.content)?
            }
            Err(e) => return Err(e),
        };
        let now = llm::now_ms();
        let thought_ref = reference(actor, "consolidate");
        let known: Vec<u64> = meaningful.iter().map(|e| e.id).collect();
        let lookup = |id: u64| batch.iter().find(|e| e.id == id).map(|e| (e.at_ms, e.salience as f64, self.anchors(e)));
        let (mut patch, notes) = memory::patch_from(&v, &known, &lookup);
        memory::sugar_into(&v, &mut patch, &known);
        self.canonical_people(&mut patch);
        // Name person anchors from what the character perceives, when the model did not.
        for n in patch.nodes.iter_mut() {
            if n.name.is_none() {
                if let Some(id) = n.key.strip_prefix("person:").and_then(|s| s.parse::<u32>().ok()) {
                    n.name = Some(self.name(id));
                }
            }
        }
        let mut people: Vec<String> = patch.edges.iter().flat_map(|e| [e.from.clone(), e.to.clone()]).filter(|k| k.starts_with("person:") && !patch.nodes.iter().any(|n| &n.key == k)).collect();
        people.sort();
        people.dedup();
        for k in people {
            if let Some(id) = k.strip_prefix("person:").and_then(|s| s.parse::<u32>().ok()) {
                patch.nodes.push(memory::NodeOp { key: k, labels: vec!["Person".into()], name: Some(self.name(id)), props: Default::default() });
            }
        }

        // Identity shifts slowly: at most once per 8 minutes unless something momentous happened.
        let momentous = meaningful.iter().any(|e| e.salience >= 0.9);
        let settled = self.conn.db.persona().id().find(&actor).map_or(true, |p| now.saturating_sub(p.updated_ms) > 8 * 60_000);
        let mut v = v;
        if animal {
            if let (Some(id), Some(cur)) = (v["identity"].as_object_mut(), self.conn.db.persona().id().find(&actor)) {
                id.insert("narrative".into(), json!(cur.narrative));
                id.entry("traits").or_insert(serde_json::from_str::<Value>(&cur.traits).unwrap_or(json!({})));
                id.insert("values".into(), json!(cur.values));
                id.insert("goals".into(), json!(cur.goals));
            }
        }
        let identity = match &v["identity"] {
            Value::Object(p) if p.get("narrative").and_then(|n| n.as_str()).map_or(false, |n| !n.is_empty()) && (momentous || settled) && self.persona_changed(actor, p) => Some(Value::Object(p.clone())),
            _ => None,
        };
        if let Some(store) = &self.store {
            store.apply(actor, &patch, &thought_ref, now).await?;
            if let Some(p) = &identity {
                let version = self.conn.db.persona().id().find(&actor).map(|x| x.version + 1).unwrap_or(1);
                store.set_identity(actor, version, p, p["why"].as_str().unwrap_or_default(), &thought_ref, now).await?;
            }
        }

        let summary = v["summary"].as_str().unwrap_or_default().to_string();
        let changed = identity.as_ref().map(|p| format!(" Identity changed: {}", p["why"].as_str().unwrap_or_default())).unwrap_or_default();
        log::info!(
            "{} integrated {} experiences (+{} edges, -{} retracted, {} memories): {summary}{changed}",
            c.name,
            meaningful.len(),
            patch.edges.len(),
            patch.retract.len(),
            patch.remember.len()
        );
        let persona = identity.map(|p| PersonaIn {
            narrative: p["narrative"].as_str().unwrap_or_default().into(),
            values: strings(&p["values"]),
            goals: strings(&p["goals"]),
            traits: p["traits"].to_string(),
            mood: p["mood"].as_str().unwrap_or_default().into(),
        });
        let thought = ThoughtIn {
            kind: "consolidate".into(),
            summary: format!("{summary}{changed}"),
            detail: json!({"experiences": known, "reply": v, "patch": patch, "notes": notes}).to_string(),
            latency_ms: reply.latency_ms,
            tokens: reply.tokens,
            model: reply.model,
            reference: thought_ref,
        };
        self.project(actor, persona, Some(thought)).await?;
        self.consolidated(actor, upto).await
    }

    /// Sleep-like reorganization: let weak unreinforced beliefs fade, then let the mind merge
    /// duplicates, generalize repeated specifics, relabel and retract.
    async fn reorganize(&self, actor: u32) -> Result<()> {
        let Some(store) = &self.store else { return Ok(()) };
        let Some(c) = self.conn.db.character().id().find(&actor) else { return Ok(()) };
        let now = llm::now_ms();
        let faded = store.fade(actor, 0.2, now).await?;
        let (nodes, edges) = store.size(actor).await?;
        if edges < 25 || c.kind != "person" {
            log::info!("{} rested (mind small: {nodes} concepts, {edges} links; {faded} faded)", c.name);
            return Ok(());
        }
        let fmt = self.fmt_time();
        let concepts = store.concepts(actor, 60).await?;
        let facts = store.around(actor, &[], 120).await?;
        let lines: Vec<String> = facts.iter().map(|f| memory::render_keys(f, &fmt)).collect();
        let profile = self.llm.profile_for(actor, &c.name);
        let _slow = self.slow.acquire().await?;
        let _permit = self.sem.acquire().await?;
        let reply = self
            .llm
            .chat(&profile, "consolidate", &c.name, &[Msg { role: "system", content: prompts::reorganize_system(&c.name) }, Msg { role: "user", content: prompts::reorganize_user(&self.persona_text(actor), &concepts, &lines) }])
            .await?;
        let v = llm::parse_json(&reply.content)?;
        let known: Vec<u64> = self.experiences(actor).iter().map(|e| e.id).collect();
        let (mut patch, notes) = memory::patch_from(&v, &known, &|_| None);
        memory::sugar_into(&json!({"judgments": v["judgments"]}), &mut patch, &[]);
        self.canonical_people(&mut patch);
        let thought_ref = reference(actor, "reorganize");
        store.apply(actor, &patch, &thought_ref, now).await?;
        let (nodes2, edges2) = store.size(actor).await?;
        let summary = format!(
            "{} (mind {nodes}→{nodes2} concepts, {edges}→{edges2} links; {} merged, {} retracted, {} generalized, {faded} faded)",
            v["summary"].as_str().unwrap_or("I rested and my thoughts settled."),
            patch.merges.len(),
            patch.retract.len(),
            patch.edges.len()
        );
        log::info!("{} slept on it: {summary}", c.name);
        let thought = ThoughtIn {
            kind: "reorganize".into(),
            summary,
            detail: json!({"reply": v, "patch": patch, "notes": notes, "faded": faded}).to_string(),
            latency_ms: reply.latency_ms,
            tokens: reply.tokens,
            model: reply.model,
            reference: thought_ref,
        };
        self.project(actor, None, Some(thought)).await
    }

    /// `person:kael` → `person:7`: people are anchored by id so one person stays one concept.
    fn canonical_people(&self, patch: &mut memory::Patch) {
        let people: Vec<(String, u32)> = self.conn.db.character().iter().filter(|c| c.kind == "person").map(|c| (c.name.to_lowercase(), c.id)).collect();
        let fix = |k: &mut String| {
            if let Some(rest) = k.strip_prefix("person:") {
                if rest.parse::<u32>().is_err() {
                    let name = rest.trim_start_matches('#').replace('_', " ");
                    if let Some((_, id)) = people.iter().find(|(n, _)| *n == name) {
                        *k = format!("person:{id}");
                    }
                }
            }
        };
        for n in patch.nodes.iter_mut() {
            fix(&mut n.key);
        }
        for e in patch.edges.iter_mut() {
            fix(&mut e.from);
            fix(&mut e.to);
        }
        for r in patch.retract.iter_mut() {
            fix(&mut r.0);
            fix(&mut r.2);
        }
        for m in patch.merges.iter_mut() {
            fix(&mut m.0);
            fix(&mut m.1);
        }
        patch.merges.retain(|(a, b)| a != b);
        // Merge duplicate node ops created by the rewrite.
        let mut seen = std::collections::HashSet::new();
        patch.nodes.retain(|n| seen.insert(n.key.clone()));
    }

    /// A model may echo the identity unchanged; only real changes become a new version.
    fn persona_changed(&self, actor: u32, p: &serde_json::Map<String, Value>) -> bool {
        let why = p.get("why").and_then(|w| w.as_str()).unwrap_or_default().to_lowercase();
        if ["no change", "no new", "unchanged", "nothing changed", "no significant"].iter().any(|x| why.contains(x)) {
            return false;
        }
        let Some(cur) = self.conn.db.persona().id().find(&actor) else { return true };
        let same_traits = serde_json::from_str::<Value>(&cur.traits).ok().as_ref() == p.get("traits");
        !(p.get("narrative").and_then(|n| n.as_str()) == Some(cur.narrative.as_str())
            && strings(p.get("values").unwrap_or(&Value::Null)) == cur.values
            && strings(p.get("goals").unwrap_or(&Value::Null)) == cur.goals
            && p.get("mood").and_then(|m| m.as_str()) == Some(cur.mood.as_str())
            && same_traits)
    }
}

/// A model's string field, tolerating small models that nest objects where text was asked.
fn flat(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string().chars().take(400).collect(),
    }
}

/// Replace the branch labeled `label` in a graph (outside the reflex layer) with `node`,
/// labeling the new branch; if no such branch exists, add it at top priority.
fn patch_branch(graph: Value, label: &str, node: Value) -> Value {
    let inner = match &graph["first"] {
        Value::Object(o) if o.get("label").and_then(|l| l.as_str()) == Some("reflexes") => o["children"].as_array().and_then(|c| c.last()).cloned().unwrap_or(json!({"wait": 3})),
        _ => graph,
    };
    let labeled = label_node(node, label);
    fn replace(v: &mut Value, label: &str, with: &Value) -> bool {
        match v {
            Value::Object(o) => {
                for key in ["first", "seq"] {
                    if let Some(Value::Object(c)) = o.get(key) {
                        if c.get("label").and_then(|l| l.as_str()) == Some(label) {
                            *v = with.clone();
                            return true;
                        }
                    }
                }
                o.values_mut().any(|x| replace(x, label, with))
            }
            Value::Array(a) => a.iter_mut().any(|x| replace(x, label, with)),
            _ => false,
        }
    }
    let mut inner = inner;
    if replace(&mut inner, label, &labeled) {
        return inner;
    }
    // Not found: the new branch takes priority over the existing behavior.
    match inner.get("first") {
        Some(Value::Array(children)) => {
            let mut c = vec![labeled];
            c.extend(children.iter().cloned());
            json!({"first": c})
        }
        Some(Value::Object(o)) => {
            let mut c = vec![labeled];
            c.extend(o.get("children").and_then(|x| x.as_array()).cloned().unwrap_or_default());
            json!({"first": {"label": o.get("label").cloned().unwrap_or(json!("plan")), "children": c}})
        }
        _ => json!({"first": [labeled, inner]}),
    }
}

/// Ensure a patched branch carries its label (wrapping non-composite nodes).
fn label_node(node: Value, label: &str) -> Value {
    for key in ["first", "seq"] {
        match node.get(key) {
            Some(Value::Array(children)) => return json!({key: {"label": label, "children": children}}),
            Some(Value::Object(o)) => {
                let mut o = o.clone();
                o.insert("label".into(), json!(label));
                return json!({key: o});
            }
            _ => {}
        }
    }
    json!({"first": {"label": label, "children": [node]}})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn patches_replace_labeled_branch_or_take_priority() {
        let g = json!({"first": {"label": "reflexes", "children": [{"wait": 1}, {"first": [
            {"first": {"label": "combat", "children": [{"do": "attack", "target": "attacker"}]}},
            {"do": "wander"}]}]}});
        let p = patch_branch(g, "combat", json!({"first": [{"if": {"threatened": true}, "then": {"do": "dodge"}}, {"do": "attack", "target": "attacker"}]}));
        let s = p.to_string();
        assert!(s.contains("dodge") && s.contains("wander") && !s.contains("reflexes"), "{s}");
        let q = patch_branch(json!({"first": [{"do": "wander"}]}), "combat", json!({"do": "flee", "target": "attacker"}));
        assert_eq!(q["first"][0]["first"]["label"], "combat");
        assert!(living_rules::graph::from_value(q).is_ok());
    }
}
