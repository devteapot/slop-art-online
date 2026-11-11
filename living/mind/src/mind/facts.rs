//! What the world holds about a resident, given to its mind as it is (docs/SEEDED_LIVES.md).
//!
//! Every person has a mind from the start. Before its first thought this service writes into
//! its mind, once:
//!
//! - **its world facts:** its background (town, occupation, household), its settlement and
//!   community, its family, its places (home, the town's centre, towns it has heard of, and
//!   every `place` row: work, square, inn, evening spot, the stages of a known way) with the
//!   lot each stands at, and its relations if any. They are written as given
//!   (`lived_under = ["world"]`);
//! - then **its authored sheet**, when its world's author wrote one (`background.sheet`),
//!   installed as written with no model call (`sheet_persona`, marked `authored`);
//! - otherwise **an identity from those facts:** one identity call writes who it is from
//!   them; everything the model adds (narrative, values, goals, traits, mood, feelings about
//!   people) is marked as the model's (`lived_under = ["ai"]`, the identity's
//!   `written_by: model` and the facts it was written from).
//!
//! Settlements and lots are read once, through one subscription applied and dropped, and
//! kept for the service's life (the land's layout does not change).

use super::{reference, strings, Minds};
use crate::llm::{self, Msg};
use crate::{memory, prompts};
use anyhow::{anyhow, Result};
use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, SubscriptionHandle as _, Table};
use std::time::Duration;

/// How long the one-off subscription to settlements and lots may take to apply.
const READ_WAIT: Duration = Duration::from_secs(30);

/// The land's settlements and lots, as read once.
#[derive(Default)]
pub(super) struct Layout {
    settlements: Vec<Settlement>,
    lots: Vec<Lot>,
}

impl Minds {
    /// Settlements and lots, read once through one subscription applied and dropped (no
    /// standing subscription to every lot).
    async fn layout(&self) -> Result<std::sync::Arc<Layout>> {
        self.layout
            .get_or_try_init(|| async {
                let (tx, rx) = tokio::sync::oneshot::channel::<()>();
                let handle = self
                    .conn
                    .subscription_builder()
                    .on_applied(move |_| {
                        let _ = tx.send(());
                    })
                    .on_error(|_, e| log::warn!("reading the land's settlements and lots: {e:?}"))
                    .subscribe(["SELECT * FROM settlement", "SELECT * FROM lot"]);
                tokio::time::timeout(READ_WAIT, rx).await.map_err(|_| anyhow!("settlements and lots did not arrive within {READ_WAIT:?}"))??;
                let layout = Layout { settlements: self.conn.db.settlement().iter().collect(), lots: self.conn.db.lot().iter().collect() };
                if let Err(e) = handle.unsubscribe() {
                    log::warn!("dropping the layout subscription: {e:?}");
                }
                log::info!("land layout read: {} settlements, {} lots", layout.settlements.len(), layout.lots.len());
                Ok(std::sync::Arc::new(layout))
            })
            .await
            .cloned()
    }

    /// A resident's settlement: its community's, else the one its home lies in.
    fn settlement_of<'a>(&self, c: &Character, layout: &'a Layout) -> Option<&'a Settlement> {
        let community = self.conn.db.membership().iter().find(|m| m.member == c.id).map(|m| m.community).filter(|k| *k != 0);
        let d = |s: &Settlement| ((s.x - c.home_x).powi(2) + (s.y - c.home_y).powi(2)).sqrt();
        community
            .and_then(|k| layout.settlements.iter().find(|s| s.community == k))
            .or_else(|| layout.settlements.iter().filter(|s| d(s) <= s.radius_m.max(40.0)).min_by(|a, b| d(a).total_cmp(&d(b))))
    }

    /// What the world holds about a resident, as given (nothing a model wrote).
    pub(super) async fn world_facts(&self, c: &Character) -> Result<Value> {
        let layout = self.layout().await?;
        let bg: Value = self.conn.db.background().id().find(&c.id).and_then(|b| serde_json::from_str(&b.text).ok()).unwrap_or_else(|| json!({}));
        let mut f = match bg.clone() {
            Value::Object(m) => m,
            _ => Default::default(),
        };
        // The authored sheet goes in as written (`sheet_persona`), not as a fact.
        f.remove("sheet");
        f.insert("stage".into(), json!(match c.stage { 1 => "child", 3 => "elder", _ => "adult" }));
        if let Some(s) = self.settlement_of(c, &layout) {
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
        let lot_at = |x: f32, y: f32| layout.lots.iter().filter(|l| ((l.door_x - x).powi(2) + (l.door_y - y).powi(2)).sqrt() <= 2.5 || ((l.x - x).powi(2) + (l.y - y).powi(2)).sqrt() <= 2.5).map(|l| l.kind.clone()).next();
        let mut places = vec![json!({"name": "home", "x": c.home_x.round(), "y": c.home_y.round(), "lot": lot_at(c.home_x, c.home_y)})];
        let at = |v: &Value| v.as_array().map(|a| (a.first().and_then(|x| x.as_f64()).unwrap_or(0.0) as f32, a.get(1).and_then(|y| y.as_f64()).unwrap_or(0.0) as f32));
        if let Some((x, y)) = at(&bg["town_center"]) {
            places.push(json!({"name": format!("{} center", bg["town"].as_str().unwrap_or("town")), "x": x.round(), "y": y.round()}));
        }
        if let Some((x, y)) = at(&bg["camp"]) {
            places.push(json!({"name": "camp", "x": x.round(), "y": y.round()}));
        }
        // Other towns one has heard of, and the named buildings of one's own settlement.
        for t in bg["towns_known"].as_array().into_iter().chain(bg["places"].as_array()).flatten() {
            if let (Some(name), Some((x, y))) = (t["name"].as_str(), at(&t["at"])) {
                places.push(json!({"name": name, "x": x.round(), "y": y.round()}));
            }
        }
        for p in self.conn.db.place().iter().filter(|p| p.actor == c.id) {
            places.push(json!({"name": p.name, "x": p.x.round(), "y": p.y.round(), "lot": lot_at(p.x, p.y)}));
        }
        f.insert("places".into(), json!(places));
        let relations: Vec<Value> = self.conn.db.relation().iter().filter(|r| r.actor == c.id).map(|r| json!({"id": r.other, "label": r.label, "trust": r.trust, "affinity": r.affinity})).collect();
        if !relations.is_empty() {
            f.insert("relations".into(), json!(relations));
        }
        Ok(Value::Object(f))
    }

    /// The people a resident lives with and its family, and its places, written to its mind as
    /// given (`lived_under = ["world"]`). Nothing without a memory store.
    pub(super) async fn given_facts(&self, c: &Character, facts: &Value, thought: &str, now: u64) -> Result<()> {
        let Some(store) = &self.store else { return Ok(()) };
        let mut given = memory::Patch::default();
        for (id, name) in self.known_people(facts) {
            given.nodes.push(memory::NodeOp { key: format!("person:{id}"), labels: vec!["Person".into()], name: Some(name), props: Default::default() });
        }
        let places: Vec<Value> = facts["places"].as_array().cloned().unwrap_or_default().into_iter().map(|p| json!({"name": p["name"], "x": p["x"], "y": p["y"]})).collect();
        // `sugar_into` bounds a model reply's lists; given facts are taken whole.
        for chunk in places.chunks(8) {
            memory::sugar_into(&json!({"places": chunk}), &mut given, &[]);
        }
        given.lived_under = Some("world".into());
        store.ensure_self(c.id, &c.name).await?;
        store.apply(c.id, &given, thought, now).await?;
        Ok(())
    }

    /// The household, companions and family the world's facts name, with their names.
    fn known_people(&self, facts: &Value) -> Vec<(u32, String)> {
        ["household", "companions", "parents", "children"]
            .iter()
            .flat_map(|k| facts[*k].as_array().cloned().unwrap_or_default())
            .filter_map(|p| Some((p["id"].as_u64()? as u32, p["name"].as_str().map(String::from).unwrap_or_else(|| self.name(p["id"].as_u64().unwrap_or(0) as u32)))))
            .collect()
    }

    /// An authored resident: its world facts as given (`world`), then its sheet as written
    /// (`authored`), with no model call.
    pub(super) async fn sheet_identity(&self, c: &Character, bg: &Value) -> Result<()> {
        let facts = self.world_facts(c).await?;
        self.given_facts(c, &facts, &reference(c.id, "facts"), llm::now_ms()).await?;
        self.sheet_persona(c, bg).await
    }

    /// Its first identity, written by a model from the world's facts only, and marked so.
    pub(super) async fn facts_identity(&self, c: &Character) -> Result<()> {
        let facts = self.world_facts(c).await?;
        let profile = self.profile(c);
        let knows: Vec<String> = self.conn.db.know_how().iter().filter(|k| k.actor == c.id).map(|k| k.technique).collect();
        let born = self.born_temperament(c.id);
        let user = prompts::identity_user(&c.name, c.id, &knows, &facts, born.as_ref());
        let reply = {
            let _slow = self.slow.acquire().await?;
            self.llm.chat(&profile, self.attention(c.id, None), "consolidate", &c.name, &[Msg { role: "system", content: prompts::identity_system() }, Msg { role: "user", content: user }]).await?
        };
        let mut v = llm::parse_json(&reply.content)?;
        let thought = reference(c.id, "background");
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
            store.set_identity(c.id, 1, &v, "who I was when this began", &thought, now).await?;
        }
        log::info!("{} (#{}) from the world's facts: {}", c.name, c.id, v["narrative"].as_str().unwrap_or_default());
        let persona = PersonaIn {
            narrative: v["narrative"].as_str().unwrap_or_default().into(),
            values: strings(&v["values"]),
            goals: strings(&v["goals"]),
            traits: born.clone().unwrap_or_else(|| v["traits"].clone()).to_string(),
            mood: v["mood"].as_str().unwrap_or("settled").into(),
        };
        let detail = json!({"facts": facts, "model_written": ["narrative", "values", "goals", "traits", "mood", "relations"], "traits_from": if born.is_some() { "genome" } else { "model" }, "reply": v});
        let t = ThoughtIn { kind: "consolidate".into(), summary: "Who I am, from what the world holds about me.".into(), detail: detail.to_string(), latency_ms: reply.latency_ms, tokens: reply.tokens, model: reply.model, reference: thought };
        self.project(c.id, Some(persona), Some(t)).await
    }
}
