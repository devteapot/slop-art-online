//! Residents woken into minds (docs/TOWN_LIFE.md, "Layer 2").
//!
//! On a world whose residents live on their behaviour graphs alone, the authority hands a
//! resident someone engages to this service (`woken` row; `ai`, controlled by it). Before its
//! first thought this service makes its mind, once:
//!
//! - **its authored sheet**, when its world's author wrote one (`background.sheet`): installed
//!   as written, with no model call, as at bootstrap (docs/SEEDED_LIVES.md);
//! - otherwise **identity from the world's facts:** its background (town, occupation, household), its
//!   settlement and community, its family, its places (home, work, square, evening spot), the
//!   lots they stand on, its know-how and inborn temperament, its relations if any. One
//!   identity call writes who it is from them. The facts are written to its mind as they are
//!   (`lived_under = ["world"]`); everything the model adds (narrative, values, goals, traits,
//!   mood, feelings about people) is marked as the model's (`lived_under = ["ai"]`, the
//!   identity's `written_by: model` and the facts it was written from, the thought's
//!   `model_written`);
//! - **its ring:** what it perceived before it woke (`prior`, read once through a subscription
//!   to its own rows), taken in as one integration through player memory's path (lived.rs,
//!   `Source::Ring`, `lived_under = ["instinct"]`). How far is kept on its `self` node
//!   (`woken_upto`), so a restart does not take it in twice.
//!
//! Its first deliberation waits for this (at most the `woken_stage("wait_s")` law); a line
//! spoken to it meanwhile is left to that deliberation, as for any character deliberating.
//!
//! **The stage cap:** with the level of detail or a staged mix, at most the
//! `woken_stage("cap")` law's number of woken residents of one settlement are on stage at
//! once. A resident who would go over it takes the stage from the least recently engaged
//! (`woken.engaged_ms`) if it was engaged more recently, else stays off stage. Each time the
//! cap binds it is logged and journaled (`purpose: stage_cap`) in the resident's journal.

use super::lived::Source;
use super::{reference, Minds};
use crate::llm::{self, Msg};
use crate::{memory, prompts};
use anyhow::{anyhow, Result};
use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, SubscriptionHandle as _, Table};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// Ring perceptions become experience-shaped lines with ids above any experience row's, so a
/// memory cites them without colliding with real experiences.
pub(super) const RING_ID: u64 = 1 << 48;
/// How long the ring's one-off subscription may take to apply.
const READ_WAIT: Duration = Duration::from_secs(30);
/// A cap report per resident at most this often.
const REPORT_EVERY: Duration = Duration::from_secs(60);

#[derive(Clone, Copy, Debug, PartialEq)]
enum State {
    Making,
    Made,
}

#[derive(Default)]
pub struct Wakes {
    state: HashMap<u32, State>,
    reported: HashMap<u32, Instant>,
    /// Cap reports waiting to be journaled (actor name, entry).
    reports: Vec<(String, Value)>,
}

pub(super) type WakesLock = Mutex<Wakes>;

impl Minds {
    pub(super) fn is_woken(&self, id: u32) -> bool {
        self.conn.db.woken().id().find(&id).is_some()
    }

    /// Whether a woken resident's mind is still being made (its first thought waits).
    pub(super) fn woken_waiting(&self, id: u32) -> bool {
        self.is_woken(id) && self.wakes.lock().unwrap().state.get(&id) != Some(&State::Made)
    }

    /// Make a woken resident's mind, once (idempotent; a restart finds what is already made).
    pub(super) fn awaken(self: Arc<Self>, id: u32) {
        if !self.allowed(id) || !self.is_woken(id) {
            return;
        }
        {
            let mut w = self.wakes.lock().unwrap();
            if w.state.contains_key(&id) {
                return;
            }
            w.state.insert(id, State::Making);
        }
        tokio::spawn(async move {
            let started = Instant::now();
            if let Err(e) = self.make_mind(id).await {
                log::warn!("{}: its mind was not fully made on waking: {e:#}", self.name(id));
            }
            log::info!("{} (#{id}) woke: its mind made in {:.1} s", self.name(id), started.elapsed().as_secs_f64());
            self.wakes.lock().unwrap().state.insert(id, State::Made);
        });
    }

    async fn make_mind(&self, id: u32) -> Result<()> {
        let c = self.conn.db.character().id().find(&id).ok_or_else(|| anyhow!("no character"))?;
        let w = self.conn.db.woken().id().find(&id).ok_or_else(|| anyhow!("not woken"))?;
        let (ring, lots) = self.read_once(id, w.settlement).await?;
        if let Some(store) = &self.store {
            store.ensure_self(id, &c.name).await?;
        }
        if self.conn.db.persona().id().find(&id).is_none() {
            match self.authored(&c) {
                // A resident its world's author wrote: its world facts as given (`world`), then
                // its sheet as written (`authored`), with no model call (docs/SEEDED_LIVES.md).
                // A model writes an identity from the world's facts only for a resident without
                // one. The ring comes after either.
                Some(bg) => {
                    let facts = self.world_facts(&c, &w, &lots);
                    self.given_facts(&c, &facts, &reference(id, "awaken"), llm::now_ms()).await?;
                    self.sheet_persona(&c, &bg).await?;
                }
                None => self.woken_identity(&c, &w, &lots).await?,
            }
        }
        let Some(store) = &self.store else {
            log::info!("{}: no memory store, so its {} perceptions from before it woke are not taken in", c.name, ring.len());
            return Ok(());
        };
        let upto = store.woken_upto(id).await?.unwrap_or(0);
        let mut lines: Vec<Experience> = ring.iter().filter(|p| p.seq as u64 > upto).map(|p| self.ring_line(p)).collect();
        lines.sort_by_key(|e| e.id);
        let Some(last) = lines.last().map(|e| e.id - RING_ID) else { return Ok(()) };
        if !lines.iter().any(|e| e.salience >= 0.2) {
            return store.set_woken_upto(id, last, llm::now_ms()).await;
        }
        let prep = self.integration(&c, lines, last, "woke", Source::Ring).await?;
        let reply = {
            let _slow = self.slow.acquire().await?;
            let route = self.profile(&c);
            self.llm.chat(&route, self.attention(id, None), "internalize", &c.name, &prep.msgs).await?
        };
        self.lived_finish(prep, reply, "direct").await
    }

    /// One perception of the ring as an experience-shaped line (its id above experience ids).
    fn ring_line(&self, p: &Prior) -> Experience {
        let text = if p.times > 1 { format!("{} (×{})", p.text, p.times) } else { p.text.clone() };
        Experience { id: RING_ID + p.seq as u64, observer: p.resident, controller: self.me, at_ms: p.at_ms, kind: p.kind.clone(), subject: p.subject, object: p.object, x: p.x, y: p.y, text, salience: p.salience }
    }

    /// The resident's ring and its settlement's lots, through one subscription applied and
    /// dropped (no standing subscription to every ring).
    async fn read_once(&self, id: u32, settlement: u16) -> Result<(Vec<Prior>, Vec<Lot>)> {
        let (tx, rx) = tokio::sync::oneshot::channel::<()>();
        let mut queries = vec![format!("SELECT * FROM prior WHERE resident = {id}")];
        if settlement != u16::MAX {
            queries.push(format!("SELECT * FROM lot WHERE settlement = {settlement}"));
        }
        let handle = self
            .conn
            .subscription_builder()
            .on_applied(move |_| {
                let _ = tx.send(());
            })
            .on_error(|_, e| log::warn!("reading a woken resident's ring: {e:?}"))
            .subscribe(queries);
        tokio::time::timeout(READ_WAIT, rx).await.map_err(|_| anyhow!("its ring did not arrive within {READ_WAIT:?}"))??;
        let ring: Vec<Prior> = self.conn.db.prior().iter().filter(|p| p.resident == id).collect();
        let lots: Vec<Lot> = self.conn.db.lot().iter().filter(|l| l.settlement == settlement).collect();
        if let Err(e) = handle.unsubscribe() {
            log::warn!("dropping the ring subscription: {e:?}");
        }
        Ok((ring, lots))
    }

    /// What the world holds about a resident, as given (nothing a model wrote).
    pub(super) fn world_facts(&self, c: &Character, w: &Woken, lots: &[Lot]) -> Value {
        let bg: Value = self.conn.db.background().id().find(&c.id).and_then(|b| serde_json::from_str(&b.text).ok()).unwrap_or_else(|| json!({}));
        let mut f = match bg {
            Value::Object(m) => m,
            _ => Default::default(),
        };
        f.insert("stage".into(), json!(match c.stage { 1 => "child", 3 => "elder", _ => "adult" }));
        if let Some(s) = self.conn.db.settlement().id().find(&w.settlement) {
            let name = self.conn.db.community().id().find(&s.community).map(|k| k.name).unwrap_or_else(|| format!("a {}", s.kind.replace('_', " ")));
            f.insert("settlement".into(), json!({"name": name, "kind": s.kind, "at": [s.x.round(), s.y.round()]}));
        }
        if let Some(m) = self.conn.db.membership().iter().find(|m| m.member == c.id) {
            if let Some(k) = self.conn.db.community().id().find(&m.community) {
                f.insert("community".into(), json!(k.name));
            }
        }
        let person = |id: u32| self.conn.db.character().id().find(&id).filter(|p| p.alive).map(|p| json!({"id": p.id, "name": p.name}));
        let parents: Vec<Value> = [c.parent_a, c.parent_b].into_iter().filter(|p| *p != 0).filter_map(person).collect();
        let children: Vec<Value> = self.conn.db.character().iter().filter(|k| k.alive && (k.parent_a == c.id || k.parent_b == c.id)).map(|k| json!({"id": k.id, "name": k.name})).collect();
        if !parents.is_empty() {
            f.insert("parents".into(), json!(parents));
        }
        if !children.is_empty() {
            f.insert("children".into(), json!(children));
        }
        // Its places, and the lot each stands at (a house, an inn, a field…).
        let lot_at = |x: f32, y: f32| lots.iter().filter(|l| ((l.door_x - x).powi(2) + (l.door_y - y).powi(2)).sqrt() <= 2.5 || ((l.x - x).powi(2) + (l.y - y).powi(2)).sqrt() <= 2.5).map(|l| l.kind.clone()).next();
        let mut places = vec![json!({"name": "home", "x": c.home_x.round(), "y": c.home_y.round(), "lot": lot_at(c.home_x, c.home_y)})];
        for p in self.conn.db.place().iter().filter(|p| p.actor == c.id) {
            places.push(json!({"name": p.name, "x": p.x.round(), "y": p.y.round(), "lot": lot_at(p.x, p.y)}));
        }
        f.insert("places".into(), json!(places));
        let relations: Vec<Value> = self.conn.db.relation().iter().filter(|r| r.actor == c.id).map(|r| json!({"id": r.other, "label": r.label, "trust": r.trust, "affinity": r.affinity})).collect();
        if !relations.is_empty() {
            f.insert("relations".into(), json!(relations));
        }
        Value::Object(f)
    }

    /// The people a woken resident lives with and its family, and its places, written to its
    /// mind as given (`lived_under = ["world"]`). Nothing without a memory store.
    async fn given_facts(&self, c: &Character, facts: &Value, thought: &str, now: u64) -> Result<()> {
        let Some(store) = &self.store else { return Ok(()) };
        let mut given = memory::Patch::default();
        for (id, name) in self.known_people(facts) {
            given.nodes.push(memory::NodeOp { key: format!("person:{id}"), labels: vec!["Person".into()], name: Some(name), props: Default::default() });
        }
        let places: Vec<Value> = facts["places"].as_array().cloned().unwrap_or_default().into_iter().map(|p| json!({"name": p["name"], "x": p["x"], "y": p["y"]})).collect();
        memory::sugar_into(&json!({"places": places}), &mut given, &[]);
        given.lived_under = Some("world".into());
        store.apply(c.id, &given, thought, now).await?;
        Ok(())
    }

    /// The household and family the world's facts name, with their names.
    fn known_people(&self, facts: &Value) -> Vec<(u32, String)> {
        ["household", "parents", "children"]
            .iter()
            .flat_map(|k| facts[*k].as_array().cloned().unwrap_or_default())
            .filter_map(|p| Some((p["id"].as_u64()? as u32, p["name"].as_str().map(String::from).unwrap_or_else(|| self.name(p["id"].as_u64().unwrap_or(0) as u32)))))
            .collect()
    }

    /// Its first identity, written by a model from the world's facts only, and marked so.
    async fn woken_identity(&self, c: &Character, w: &Woken, lots: &[Lot]) -> Result<()> {
        let facts = self.world_facts(c, w, lots);
        let profile = self.profile(c);
        let knows: Vec<String> = self.conn.db.know_how().iter().filter(|k| k.actor == c.id).map(|k| k.technique).collect();
        let born = self.born_temperament(c.id);
        let user = prompts::identity_user(&c.name, c.id, &knows, &facts, born.as_ref());
        let reply = {
            let _slow = self.slow.acquire().await?;
            self.llm.chat(&profile, self.attention(c.id, None), "consolidate", &c.name, &[Msg { role: "system", content: prompts::identity_system() }, Msg { role: "user", content: user }]).await?
        };
        let mut v = llm::parse_json(&reply.content)?;
        let thought = reference(c.id, "awaken");
        let now = llm::now_ms();
        let known = self.known_people(&facts);
        let relations: Vec<Value> = v["relations"].as_array().cloned().unwrap_or_default().into_iter().filter(|r| living_rules::normalize::reply_id(&r["id"]).is_some_and(|i| known.iter().any(|(k, _)| *k as u64 == i))).collect();
        if let Some(store) = &self.store {
            self.given_facts(c, &facts, &thought, now).await?;
            // What the model wrote beyond them: how it feels about those people.
            let mut written = memory::Patch::default();
            memory::sugar_into(&json!({"relations": relations}), &mut written, &[]);
            written.lived_under = Some("ai".into());
            store.apply(c.id, &written, &thought, now).await?;
            if let Value::Object(m) = &mut v {
                m.insert("written_by".into(), json!("model"));
                m.insert("from_facts".into(), facts.clone());
            }
            store.set_identity(c.id, 1, &v, "who I was when I woke", &thought, now).await?;
        }
        log::info!("{} (#{}) woke as: {}", c.name, c.id, v["narrative"].as_str().unwrap_or_default());
        let persona = PersonaIn {
            narrative: v["narrative"].as_str().unwrap_or_default().into(),
            values: v["values"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default(),
            goals: v["goals"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default(),
            traits: born.clone().unwrap_or_else(|| v["traits"].clone()).to_string(),
            mood: v["mood"].as_str().unwrap_or("settled").into(),
        };
        let detail = json!({"facts": facts, "model_written": ["narrative", "values", "goals", "traits", "mood", "relations"], "traits_from": if born.is_some() { "genome" } else { "model" }, "reply": v});
        let t = ThoughtIn { kind: "awaken".into(), summary: "Who I am, from what the world holds about me.".into(), detail: detail.to_string(), latency_ms: reply.latency_ms, tokens: reply.tokens, model: reply.model, reference: thought };
        self.project(c.id, Some(persona), Some(t)).await
    }

    /// Whether a woken resident may be on stage now under the `woken_stage("cap")` law (see
    /// the module notes). Characters that are not woken residents are always admitted.
    pub(super) fn admit(&self, actor: u32, actors: &mut HashMap<u32, super::ActorMind>) -> bool {
        let cap = prompts::woken_laws().stage_cap as usize;
        if cap == 0 {
            return true;
        }
        let Some(me) = self.conn.db.woken().id().find(&actor) else { return true };
        let now = Instant::now();
        let on = |id: u32| actors.get(&id).and_then(|m| m.onstage_until).is_some_and(|t| t > now);
        if on(actor) {
            return true;
        }
        let peers: Vec<Woken> = self.conn.db.woken().iter().filter(|w| w.settlement == me.settlement && w.id != actor && on(w.id)).collect();
        if peers.len() < cap {
            return true;
        }
        let least = peers.iter().min_by_key(|w| w.engaged_ms).expect("cap > 0");
        let admitted = me.engaged_ms > least.engaged_ms;
        if admitted {
            if let Some(m) = actors.get_mut(&least.id) {
                m.onstage_until = None;
            }
        }
        let mut wakes = self.wakes.lock().unwrap();
        if wakes.reported.get(&actor).is_none_or(|t| now.duration_since(*t) >= REPORT_EVERY) {
            wakes.reported.insert(actor, now);
            let name = self.name(actor);
            let on_stage: Vec<u32> = peers.iter().map(|w| w.id).collect();
            if admitted {
                log::info!("stage cap {cap} binds in settlement {}: {name} (#{actor}) takes the stage from {} (#{}), engaged less recently", me.settlement, self.name(least.id), least.id);
            } else {
                log::info!("stage cap {cap} binds in settlement {}: {name} (#{actor}) stays off stage ({} on stage)", me.settlement, peers.len());
            }
            let entry = json!({"purpose": "stage_cap", "at_ms": llm::now_ms(), "actor": name, "id": actor, "settlement": me.settlement, "cap": cap, "on_stage": on_stage, "admitted": admitted, "displaced": admitted.then_some(least.id)});
            wakes.reports.push((name, entry));
        }
        admitted
    }

    /// Journal the cap reports gathered since the last tick.
    pub(super) async fn journal_cap_reports(&self) {
        let reports = std::mem::take(&mut self.wakes.lock().unwrap().reports);
        for (actor, entry) in reports {
            self.llm.journal_entry(&actor, &entry).await;
        }
    }
}
