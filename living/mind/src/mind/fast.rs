//! The fast lane (docs/FAST_LANE.md): a quick re-plan between blows. The authority issues a
//! `fast_ask` row for a character its mind holds (a blow taken, or the same move seen started at
//! it `seen_again_n` times; the count is the authority's and is never told), under the world's
//! laws for how many and how often. This service answers each issued row with one call on the
//! fast route (`rethink.json` `fast.route`, the `Urgent` lane, purpose `fast`) and one reducer:
//! `mind_patch` (the character's `combat` branch, or one of its own routines, changed) or
//! `mind_fast_done` (kept as it is, no usable answer, off stage, timed out).
//!
//! The prompt holds only the character's own perception and plans: why now (the event as it
//! perceived it), who it is with its own moves' timings, what has just happened, its top level
//! and its routines; the world's rules and the graph grammar. No tactic text. A reply may not
//! speak, act or create routines: that stays with the slow mind.

use super::Minds;
use crate::llm::{self, Attention, Lane, Msg};
use crate::prompts;
use anyhow::{anyhow, Result};
use living_bindings::*;
use serde::Deserialize;
use spacetimedb_sdk::Table;
use serde_json::{json, Value};
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::oneshot;

#[derive(Clone, Debug, Deserialize)]
#[serde(default)]
pub struct Config {
    /// A profile, `profile@effort` or a mix (purpose `fast`).
    pub route: String,
    /// A reply later than this is dropped (journaled as a timeout) and changes nothing.
    pub timeout_ms: u64,
    /// The newest experiences in the prompt.
    pub experiences: usize,
}

impl Default for Config {
    fn default() -> Self {
        Self { route: "deepseek-flash".into(), timeout_ms: 6_000, experiences: 12 }
    }
}

impl Config {
    /// The `fast` section of the rethink gate's file (`LIVING_RETHINK_CONFIG`, else
    /// `living/configs/rethink.json`); the defaults when it has none.
    pub fn load(root: &Path) -> Self {
        let path = std::env::var("LIVING_RETHINK_CONFIG").map(std::path::PathBuf::from).unwrap_or_else(|_| root.join("living/configs/rethink.json"));
        std::fs::read_to_string(&path).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok()).and_then(|v| serde_json::from_value(v["fast"].clone()).ok()).unwrap_or_default()
    }
}

/// What a reply asks for.
enum Change {
    /// `mind_patch` with this target and graph.
    Patch { target: String, graph: String, what: String },
    /// No change, and why.
    Keep(String),
}

impl Minds {
    /// An issued `fast_ask` row: served once (a row updated by the authority for the same issue
    /// is the same request).
    pub(super) fn fast_issued(self: Arc<Self>, ask: FastAsk) {
        if ask.issued_ms == 0 || !self.allowed(ask.actor) {
            return;
        }
        {
            let mut a = self.actors.lock().unwrap();
            let m = a.entry(ask.actor).or_default();
            if m.fast_issued >= ask.issued_ms {
                return;
            }
            m.fast_issued = ask.issued_ms;
        }
        tokio::spawn(async move {
            if let Err(e) = self.fast_serve(&ask).await {
                log::warn!("fast lane for {}: {e:#}", ask.actor);
            }
        });
    }

    async fn fast_serve(&self, ask: &FastAsk) -> Result<()> {
        let picked_ms = llm::now_ms();
        let actor = ask.actor;
        let Some(c) = self.conn.db.character().id().find(&actor) else { return Ok(()) };
        // Not the mind's now (its person is back, or it died): the authority has dropped the row.
        if !c.alive || !c.ai || c.controller != self.me {
            return Ok(());
        }
        let reference = super::reference(actor, "fast");
        let base = json!({"trigger_ms": ask.trigger_ms, "issued_ms": ask.issued_ms, "picked_ms": picked_ms, "reason": ask.reason});
        // Off stage by the level of detail (`LIVING_LOD`), not merely unwatched: with a staged model
        // mix every character no player watches counts as off stage for model routing, which
        // would leave a fight with no player in sight (an arena) without the lane at all.
        if self.lod.on && self.attention(actor, None) != Attention::OnStage {
            return self.fast_done(actor, ask.issued_ms, "off stage", base, &reference, None).await;
        }
        let fmt = self.fmt_time();
        let experiences: Vec<String> = {
            let all = self.experiences(actor);
            let n = all.len();
            all.iter().skip(n.saturating_sub(self.fast.experiences)).map(|e| self.exp_line(e, &fmt, false)).collect()
        };
        let brain = self.conn.db.brain().id().find(&actor);
        let outline = brain.as_ref().and_then(|b| living_rules::graph::parse(&b.graph).ok()).map(|g| living_rules::graph::outline(&g.root)).unwrap_or_default();
        let plan = brain.as_ref().map(|b| b.plan.clone()).unwrap_or_default();
        let persona = format!("{}{}", self.persona_text(actor), self.own_timings(actor));
        let msgs = vec![
            Msg { role: "system", content: prompts::fast_system() },
            Msg { role: "user", content: prompts::fast_user(&ask.reason, &persona, &experiences, &plan, &outline, &self.repertoire_text(actor)) },
        ];
        let call = self.llm.chat_in_lane(&self.fast.route, Attention::OnStage, "fast", &c.name, &msgs, Lane::Urgent);
        let reply = match tokio::time::timeout(Duration::from_millis(self.fast.timeout_ms), call).await {
            Err(_) => {
                // A reply past the timeout is dropped: journaled as a timeout, nothing changes.
                self.llm
                    .journal_entry(&c.name, &json!({
                        "at_ms": llm::now_ms(), "actor": c.name, "purpose": "fast", "profile": self.fast.route, "model": null,
                        "latency_ms": self.fast.timeout_ms, "lane": "urgent", "queue_wait_ms": null, "prompt_tokens": null,
                        "completion_tokens": null, "cached_tokens": null, "cost_usd": null, "request": null, "reply": null,
                        "error": format!("timeout after {} ms (fast lane)", self.fast.timeout_ms),
                    }))
                    .await;
                return self.fast_done(actor, ask.issued_ms, "timed out", base, &reference, None).await;
            }
            Ok(Err(e)) => return self.fast_done(actor, ask.issued_ms, &format!("no answer: {e:#}"), base, &reference, None).await,
            Ok(Ok(r)) => r,
        };
        let v = llm::parse_json(&reply.content).unwrap_or(Value::Null);
        let thought = v["thought"].as_str().unwrap_or_default().trim().to_string();
        let mut detail = base;
        detail["model_ms"] = json!(reply.latency_ms);
        detail["reply"] = v.clone();
        let routines: Vec<String> = self.conn.db.routine().iter().filter(|r| r.actor == actor).map(|r| living_rules::normalize::routine_name(&r.name)).collect();
        let change = change_of(&v, &routines);
        // Its person may have come back while the model answered.
        if !self.conn.db.character().id().find(&actor).is_some_and(|c| c.alive && c.ai && c.controller == self.me) {
            return Ok(());
        }
        match change {
            Change::Keep(why) => {
                let summary = if thought.is_empty() { why } else { format!("{why}: {thought}") };
                self.fast_done(actor, ask.issued_ms, &summary, detail, &reference, Some(&reply)).await
            }
            Change::Patch { target, graph, what } => {
                detail["sent_ms"] = json!(llm::now_ms());
                let t = ThoughtIn {
                    kind: "fast".into(),
                    summary: if thought.is_empty() { what } else { format!("{thought} → {what}") },
                    detail: detail.to_string(),
                    latency_ms: reply.latency_ms,
                    tokens: reply.tokens,
                    model: reply.model.clone(),
                    reference,
                };
                log::info!("{} fast lane: {}", c.name, t.summary);
                let (tx, rx) = oneshot::channel();
                self.conn.reducers.mind_patch_then(actor, target, graph, ask.issued_ms, t, move |_, r| {
                    let _ = tx.send(super::flatten(r));
                })?;
                rx.await?.map_err(|e| anyhow!("mind_patch: {e}"))
            }
        }
    }

    async fn fast_done(&self, actor: u32, issued_ms: u64, summary: &str, detail: Value, reference: &str, reply: Option<&llm::Reply>) -> Result<()> {
        let t = ThoughtIn {
            kind: "fast".into(),
            summary: format!("kept: {summary}"),
            detail: detail.to_string(),
            latency_ms: reply.map_or(0, |r| r.latency_ms),
            tokens: reply.map_or(0, |r| r.tokens),
            model: reply.map(|r| r.model.clone()).unwrap_or_default(),
            reference: reference.to_string(),
        };
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_fast_done_then(actor, issued_ms, t, move |_, r| {
            let _ = tx.send(super::flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_fast_done: {e}"))
    }
}

/// What a reply asks for, checked against the character's own routines (normalized names).
fn change_of(v: &Value, routines: &[String]) -> Change {
    let graph_of = |g: &Value| living_rules::graph::from_value_lenient(g.clone()).ok().map(|(g, _)| g.to_json());
    if v["keep"].as_bool() == Some(true) {
        return Change::Keep("as it is".into());
    }
    if v["patch"].is_object() {
        return match graph_of(&v["patch"]["graph"]) {
            Some(graph) => Change::Patch { target: "combat".into(), graph, what: "combat branch rewritten".into() },
            None => Change::Keep("the combat branch it wrote is not a graph".into()),
        };
    }
    if v["routine"].is_object() {
        let name = living_rules::normalize::routine_name(v["routine"]["name"].as_str().unwrap_or_default());
        if !routines.contains(&name) {
            return Change::Keep(format!("it has no routine called {name}"));
        }
        return match graph_of(&v["routine"]["graph"]) {
            Some(graph) => Change::Patch { target: format!("routine:{name}"), graph, what: format!("routine {name} rewritten") },
            None => Change::Keep(format!("routine {name} as written is not a graph")),
        };
    }
    if let Some(name) = v["switch"].as_str() {
        let name = living_rules::normalize::routine_name(name);
        if !routines.contains(&name) {
            return Change::Keep(format!("it has no routine called {name}"));
        }
        return Change::Patch { target: "combat".into(), graph: json!({"routine": name}).to_string(), what: format!("combat branch switched to {name}") };
    }
    Change::Keep("no usable answer".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_reply_changes_only_what_it_may() {
        let mine = vec!["stay safe".to_string()];
        assert!(matches!(change_of(&json!({"keep": true}), &mine), Change::Keep(_)));
        match change_of(&json!({"patch": {"label": "combat", "graph": {"do": "dodge"}}}), &mine) {
            Change::Patch { target, .. } => assert_eq!(target, "combat"),
            _ => panic!("a patch"),
        }
        match change_of(&json!({"switch": "Stay safe"}), &mine) {
            Change::Patch { target, graph, .. } => assert!(target == "combat" && graph.contains("stay safe"), "{graph}"),
            _ => panic!("a switch to its own routine"),
        }
        // A routine it does not have is neither switched to nor written.
        assert!(matches!(change_of(&json!({"switch": "win the fight"}), &mine), Change::Keep(_)));
        assert!(matches!(change_of(&json!({"routine": {"name": "win the fight", "graph": {"do": "dodge"}}}), &mine), Change::Keep(_)));
        assert!(matches!(change_of(&json!({"say": "hello"}), &mine), Change::Keep(_)));
    }

    #[test]
    fn the_prompt_has_no_count_and_no_tactic() {
        // What the repeat trigger contributes is the event as perceived: no count, no "again".
        let reason = "A stranger winds up an attack at you";
        let user = prompts::fast_user(reason, "Wren", &["A stranger attacked you (9 damage)".into()], "walk to town", "first: …", "- stay safe");
        // The stable parts come first, for the providers' prefix caches; why now and what has just
        // happened come last.
        assert!(user.starts_with("# Who you are\nWren") && user.find("# Your routines") < user.find("# Why now"), "{user}");
        let why = user.split("# Why now").nth(1).unwrap().split("# What has just happened").next().unwrap();
        assert!(!why.contains("again") && !why.chars().any(|c| c.is_ascii_digit()), "{why}");
        // The rules text keeps its own words ("ready again 900 ms"); nothing counts anyone's moves.
        for text in [&user, &prompts::fast_system()] {
            assert!(!regex_like_count(text), "a count in the fast lane's prompt");
            for tactic in ["dodge on", "when they wind up", "counter"] {
                assert!(!text.to_lowercase().contains(tactic), "tactic text {tactic:?} in the fast lane's prompt");
            }
        }
    }

    fn regex_like_count(t: &str) -> bool {
        t.contains("times now") || t.contains("(×") || t.contains("for the third time")
    }
}
