//! Situational recall: what the moment brings to mind.
//!
//! A reasoning episode no longer receives the most recently written part of a mind. The
//! situation supplies cues — who and what is perceived and how close, places nearby, the
//! reason for thinking, what was just said or happened, the plan, the time of day — and
//! [`Store::recall`](crate::memory::Store::recall) spreads activation from them through the
//! character's own concepts. Only what clears a floor comes to mind, within a small budget, so
//! an internalized concept ("wolves near the ford", a grudge, a promise) returns when its cues
//! appear and stays out of the prompt otherwise. Stances are listed when the situation touches
//! them or the current graph tests them; the rest are summarized as a count.

use super::Minds;
use crate::llm;
use crate::memory::{self, Cues};
use living_bindings::*;
use serde_json::Value;
use spacetimedb_sdk::Table;

/// What a prompt shows from the mind.
#[derive(Default)]
pub(super) struct Recall {
    /// Beliefs and links that came to mind, most activated first.
    pub mind: Vec<String>,
    /// Memories brought back (cued, plus the most recent), oldest first.
    pub memories: Vec<String>,
    /// Stances on the mind now (cued, tested by the current graph, or held most strongly).
    pub judgments: Vec<String>,
    /// Only the stances the situation itself touched.
    pub cued_stances: Vec<String>,
}

/// Words for the part of the day, as cues ("at dawn", "tonight").
pub(super) fn day_words(hour: f32) -> &'static str {
    match hour as u32 {
        5..=6 => "dawn morning first light",
        7..=11 => "morning",
        12..=13 => "noon midday",
        14..=16 => "afternoon",
        17..=19 => "evening dusk",
        _ => "night tonight dark",
    }
}

impl Minds {
    /// People named in a text (by their names as words), for cues.
    pub(super) fn named_people(&self, text: &str) -> Vec<u32> {
        let words: Vec<String> = text.to_lowercase().split(|c: char| !c.is_alphabetic()).filter(|w| w.len() >= 3).map(String::from).collect();
        if words.is_empty() {
            return Vec::new();
        }
        self.conn.db.character().iter().filter(|c| c.kind == "person" && words.iter().any(|w| *w == c.name.to_lowercase())).map(|c| c.id).collect()
    }

    fn hour_now(&self) -> f32 {
        self.conn.db.world().id().find(&0).map(|w| living_rules::hour_of(llm::now_ms(), w.epoch_ms, w.day_ms)).unwrap_or(12.0)
    }

    /// Cues from what a character perceives (the authority's scene JSON), why it is thinking,
    /// its latest experiences and its current plan.
    pub(super) fn scene_cues(&self, actor: u32, scene: &Value, reason: &str) -> Cues {
        let mut cues = Cues::default();
        let named = |c: &mut Cues, text: &str, w: f64| {
            for id in self.named_people(text) {
                if id != actor {
                    c.key(format!("person:{id}"), w);
                }
            }
        };
        for cr in scene["creatures"].as_array().cloned().unwrap_or_default() {
            let dist = cr["dist"].as_f64().unwrap_or(10.0);
            let near = if dist <= 4.0 { 1.0 } else if dist <= 9.0 { 0.8 } else { 0.6 };
            let hurt = if cr["looks"] == "hurt" { 0.2 } else { 0.0 };
            match cr["kind"].as_str() {
                Some("person") => cues.key(format!("person:{}", cr["id"]), near + hurt),
                Some(k) => {
                    cues.key(format!("kind:{k}"), 0.9);
                    cues.text(k, 0.7);
                }
                None => {}
            }
        }
        for key in ["resources", "structures"] {
            for r in scene[key].as_array().cloned().unwrap_or_default() {
                if let Some(k) = r["kind"].as_str() {
                    let notable = matches!(k, "remains" | "gate" | "sign" | "wall");
                    cues.key(format!("kind:{k}"), if notable { 0.7 } else { 0.35 });
                    cues.text(k, if notable { 0.6 } else { 0.3 });
                }
            }
        }
        // Places one knows within sight.
        let at = (scene["you"]["at"][0].as_f64().unwrap_or(-1e6) as f32, scene["you"]["at"][1].as_f64().unwrap_or(-1e6) as f32);
        let sight = scene["time"]["sight"].as_f64().unwrap_or(11.0) as f32;
        for p in self.conn.db.place().iter().filter(|p| p.actor == actor) {
            let d = ((p.x - at.0).powi(2) + (p.y - at.1).powi(2)).sqrt();
            if d <= sight {
                if let Some(k) = memory::key(&p.name) {
                    cues.key(format!("place:{}", k.trim_start_matches("place:")), if d <= 4.0 { 0.7 } else { 0.5 });
                }
            }
        }
        let hour = scene["time"]["hour"].as_f64().map(|h| h as f32).unwrap_or_else(|| self.hour_now());
        cues.text(day_words(hour), 0.4);
        if let Some(season) = scene["time"]["season"].as_str() {
            cues.text(season, 0.3);
        }
        cues.text(reason, 1.0);
        named(&mut cues, reason, 1.1);
        let exps = self.experiences(actor);
        for e in exps.iter().rev().take(5) {
            cues.text(&e.text, 0.6);
            for id in [e.subject, e.object] {
                if id != 0 && id != actor && self.conn.db.character().id().find(&id).map_or(false, |c| c.kind == "person") {
                    cues.key(format!("person:{id}"), 0.9);
                }
            }
        }
        if let Some(b) = self.conn.db.brain().id().find(&actor) {
            cues.text(&b.plan, 0.4);
        }
        cues.bounded()
    }

    /// Cues from a batch of experiences being integrated: who and what they involve, and
    /// what they say.
    pub(super) fn experience_cues(&self, actor: u32, exps: &[&Experience]) -> Cues {
        let mut cues = Cues::default();
        for e in exps {
            for k in self.anchors(e) {
                cues.key(k, 1.0);
            }
            cues.text(&e.text, 0.7);
            for id in self.named_people(&e.text) {
                if id != actor {
                    cues.key(format!("person:{id}"), 0.8);
                }
            }
        }
        cues.bounded()
    }

    /// Recall from the character's mind and render it for a prompt.
    pub(super) async fn recall_for(&self, actor: u32, cues: &Cues, budget: usize, mem_budget: usize) -> Recall {
        let Some(store) = &self.store else { return Recall { judgments: self.judgments(actor), ..Default::default() } };
        let fmt = self.fmt_time();
        let r = match store.recall(actor, cues, budget, mem_budget).await {
            Ok(r) => r,
            Err(e) => {
                log::warn!("recall for {}: {e:#}", self.name(actor));
                return Recall { judgments: self.judgments(actor), ..Default::default() };
            }
        };
        log::debug!(
            "recall for {}: {} cues → {} seeds, {} links considered → {} beliefs, {} stances, {} memories in {} ms",
            self.name(actor),
            cues.keys.len() + cues.words.len(),
            r.seeds,
            r.considered,
            r.facts.len(),
            r.stances.len(),
            r.memories.len(),
            r.ms
        );
        if let Err(e) = store.rehearse(actor, &r.rehearse).await {
            log::warn!("rehearsal for {}: {e:#}", self.name(actor));
        }
        let mind = r.facts.iter().map(|f| memory::render(f, &fmt)).collect();
        let memories = r.memories.iter().map(|(exp, t, gist)| format!("[{}] {gist} (experience {exp})", fmt(*t))).collect();
        let cued_stances = self
            .conn
            .db
            .judgment()
            .iter()
            .filter(|j| j.actor == actor && r.stances.iter().any(|(k, _)| k == &j.key))
            .map(|j| format!("{} = {:.2} ({})", j.key, j.value, j.why))
            .collect();
        Recall { mind, memories, judgments: self.judgments_on_mind(actor, &r.stances), cued_stances }
    }

    /// Stances on the mind now: those the situation touched, those the current graph tests
    /// (`believes`), and, if few, the ones held most strongly; the rest are counted.
    fn judgments_on_mind(&self, actor: u32, cued: &[(String, f64)]) -> Vec<String> {
        let graph = self.conn.db.brain().id().find(&actor).map(|b| b.graph).unwrap_or_default();
        let mut all: Vec<Judgment> = self.conn.db.judgment().iter().filter(|j| j.actor == actor).collect();
        let tested = |k: &str| graph.contains(&format!("\"{k}\""));
        let rank = |j: &Judgment| -> f64 {
            let c = cued.iter().find(|(k, _)| k == &j.key).map_or(0.0, |x| 1.0 + x.1);
            let t = if tested(&j.key) { 1.0 } else { 0.0 };
            c + t + (j.value as f64 - 0.5).abs()
        };
        all.sort_by(|a, b| rank(b).total_cmp(&rank(a)));
        let on_mind = |j: &Judgment| cued.iter().any(|(k, _)| k == &j.key) || tested(&j.key);
        let mut shown: Vec<&Judgment> = all.iter().filter(|j| on_mind(j)).take(10).collect();
        for j in all.iter().filter(|j| !on_mind(j)) {
            if shown.len() >= 3 {
                break;
            }
            shown.push(j);
        }
        let mut out: Vec<String> = shown.iter().map(|j| format!("{} = {:.2} ({})", j.key, j.value, j.why)).collect();
        let hidden = all.len().saturating_sub(shown.len());
        if hidden > 0 {
            out.push(format!("({hidden} other stances you hold are not on your mind now)"));
        }
        out
    }
}
