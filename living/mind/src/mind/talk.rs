//! Conversations: an exchange of turns between two minds.
//!
//! When a character this service controls hears speech addressed to it (or, when it cares
//! about the speaker, speech nobody in particular was addressed by), its mind gets a
//! *reply turn*: a small model call with who it is, how it feels about the speaker, what it
//! holds about them, what happened between them lately and the conversation so far. The
//! answer is spoken through `mind_say` (kind `talk`), which keeps the behavior graph and
//! leaves pending deliberations alone. The other side hears it as an ordinary experience,
//! which gives them a turn in return, until someone ends the conversation, stays silent,
//! is out of earshot, or the exchange reaches `MAX_TURNS`.
//!
//! The conversation state here is only a working memory of the exchange (per pair, in
//! memory). The authority remains the record: every line is a `speak` (chronicle and
//! experiences), so consolidation integrates conversations like anything else lived.

use super::{flatten, reference, Minds};
use crate::llm::{self, Msg};
use crate::{memory, prompts};
use anyhow::{anyhow, Result};
use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::Table;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::oneshot;

/// Reply turns in one conversation (both sides together).
const MAX_TURNS: u32 = 8;
/// A conversation that has been quiet this long is over; the next line starts a new one.
const QUIET_MS: u64 = 90_000;
/// Speech older than this (e.g. replayed when the service starts) gets no turn.
const STALE_MS: u64 = 30_000;
/// A listener is invited by speech not addressed to them at most this often.
const OVERHEARD_GAP_MS: u64 = 60_000;
/// The authority refuses speech within 2 s of one's previous line.
const SPEECH_GAP_MS: u64 = 2_100;

#[derive(Clone, Debug)]
struct Line {
    speaker: u32,
    to: u32,
    text: String,
    at_ms: u64,
    /// Where it was said.
    at: (f32, f32),
    /// Spoken as a reply turn (as opposed to a deliberation, a human or another service).
    turn: bool,
}

#[derive(Default)]
struct Conversation {
    lines: Vec<Line>,
    turns: u32,
    ended: bool,
    last_ms: u64,
}

#[derive(Default)]
pub struct Talks {
    pairs: HashMap<(u32, u32), Conversation>,
    /// Characters with a reply turn in flight; the value is a newer speaker waiting for one.
    busy: HashMap<u32, Option<u32>>,
    /// Last time each listener was drawn in by speech not addressed to them.
    overheard: HashMap<u32, u64>,
    /// Speech not addressed to anyone gets at most one reply: (speaker, at_ms) → listener.
    claimed: HashMap<(u32, u64), u32>,
    /// When each character last spoke through a reply turn.
    spoke: HashMap<u32, u64>,
}

fn pair(a: u32, b: u32) -> (u32, u32) {
    (a.min(b), a.max(b))
}

/// The words inside “…” of an experience line.
fn quoted(text: &str) -> String {
    match (text.find('“'), text.rfind('”')) {
        (Some(a), Some(b)) if b > a => text[a + '“'.len_utf8()..b].to_string(),
        _ => text.to_string(),
    }
}

impl Talks {
    fn prune(&mut self, now: u64) {
        self.pairs.retain(|_, c| now.saturating_sub(c.last_ms) < QUIET_MS * 2);
        self.claimed.retain(|(_, at), _| now.saturating_sub(*at) < STALE_MS * 2);
    }
}

impl Minds {
    /// A speech or silence experience of one of this service's characters.
    pub(super) fn on_speech(self: Arc<Self>, e: Experience) {
        let now = llm::now_ms();
        if now.saturating_sub(e.at_ms) > STALE_MS || !self.allowed(e.observer) {
            return;
        }
        if e.kind == "silence" {
            // Called someone who is out of earshot: that conversation is over.
            if let Some(c) = self.talk.lock().unwrap().pairs.get_mut(&pair(e.observer, e.subject)) {
                c.ended = true;
                log::info!("{} and {}: out of earshot, conversation over", self.name(e.observer), self.name(e.subject));
            }
            return;
        }
        let (listener, speaker, to) = (e.observer, e.subject, e.object);
        if speaker == 0 || speaker == listener {
            return;
        }
        let person = |id: u32| self.conn.db.character().id().find(&id).filter(|c| c.kind == "person" && c.alive);
        let Some(me) = person(listener).filter(|c| c.ai && c.controller == self.me) else { return };
        if person(speaker).is_none() {
            return;
        }
        let text = quoted(&e.text);
        // Addressed by name, by `to`, or as the only person close by (the authority marks these).
        let addressed = to == listener || (to == 0 && e.salience >= 0.8);
        let cares = || self.cares(listener, speaker);
        let go = {
            let mut t = self.talk.lock().unwrap();
            t.prune(now);
            let key = pair(listener, speaker);
            let active = t.pairs.get(&key).map_or(false, |c| !c.ended && now.saturating_sub(c.last_ms) < QUIET_MS);
            let in_other = t.pairs.iter().any(|(k, c)| *k != key && (k.0 == listener || k.1 == listener) && !c.ended && now.saturating_sub(c.last_ms) < QUIET_MS);
            let overheard_ok = to == 0
                && !in_other
                && t.overheard.get(&listener).map_or(true, |at| now.saturating_sub(*at) > OVERHEARD_GAP_MS)
                && !t.claimed.contains_key(&(speaker, e.at_ms))
                && cares();
            if !(addressed || (active && to == 0) || overheard_ok) {
                return;
            }
            if !addressed && !active {
                t.overheard.insert(listener, now);
                t.claimed.insert((speaker, e.at_ms), listener);
            }
            let c = t.pairs.entry(key).or_default();
            if now.saturating_sub(c.last_ms) >= QUIET_MS {
                *c = Conversation::default();
            }
            // Our own reply turns record their lines when they speak; anything else is new.
            let known = c.lines.iter().any(|l| l.turn && l.speaker == speaker && l.text == text && e.at_ms.abs_diff(l.at_ms) < 20_000);
            if !known {
                c.lines.push(Line { speaker, to, text: text.clone(), at_ms: e.at_ms, at: (e.x, e.y), turn: false });
                // A line from outside the exchange (a decision, a human) reopens a finished one.
                if c.ended || c.turns >= MAX_TURNS {
                    c.ended = false;
                    c.turns = 0;
                }
            }
            c.last_ms = now;
            if c.ended || c.turns >= MAX_TURNS {
                return;
            }
            match t.busy.get_mut(&listener) {
                Some(waiting) => {
                    *waiting = Some(speaker);
                    false
                }
                None => {
                    t.busy.insert(listener, None);
                    true
                }
            }
        };
        if !go {
            return;
        }
        log::debug!("{} gets a reply turn for {}", me.name, self.name(speaker));
        tokio::spawn(async move {
            let mut speaker = speaker;
            loop {
                if let Err(e) = self.reply_turn(listener, speaker).await {
                    log::warn!("reply turn for {} failed: {e:#}", self.name(listener));
                    if let Some(c) = self.talk.lock().unwrap().pairs.get_mut(&pair(listener, speaker)) {
                        c.ended = true;
                    }
                }
                let next = {
                    let mut t = self.talk.lock().unwrap();
                    let waiting = t.busy.get_mut(&listener).and_then(|w| w.take());
                    // Someone else spoke to them meanwhile and is still waiting for an answer.
                    let due = waiting.filter(|s| t.pairs.get(&pair(listener, *s)).map_or(false, |c| !c.ended && c.turns < MAX_TURNS && c.lines.last().map_or(false, |l| l.speaker == *s)));
                    if due.is_none() {
                        t.busy.remove(&listener);
                    }
                    due
                };
                match next {
                    Some(s) => speaker = s,
                    None => break,
                }
            }
        });
    }

    /// Whether a listener cares enough about a speaker to answer a remark not meant for them:
    /// family and close bonds, and strong feelings either way.
    fn cares(&self, listener: u32, speaker: u32) -> bool {
        self.conn.db.relation().iter().find(|r| r.actor == listener && r.other == speaker).map_or(false, |r| {
            let label = r.label.to_lowercase();
            const CLOSE: &[&str] = &["family", "partner", "friend", "parent", "mother", "father", "child", "son", "daughter", "sibling", "brother", "sister", "spouse", "wife", "husband", "lover"];
            CLOSE.iter().any(|w| label.contains(w)) || r.affinity.abs() >= 40.0 || r.trust >= 60.0
        })
    }

    /// Full deliberations take priority over conversation turns.
    fn thinking(&self, actor: u32) -> bool {
        self.actors.lock().unwrap().get(&actor).map_or(false, |m| m.deliberating) || self.conn.db.my_deliberations().iter().any(|d| d.actor == actor)
    }

    async fn reply_turn(&self, me: u32, other: u32) -> Result<()> {
        if self.thinking(me) {
            // The deliberation sees the line among recent experiences and may answer there.
            log::info!("{} is deliberating; the line from {} is left to that deliberation", self.name(me), self.name(other));
            return Ok(());
        }
        let Some(c) = self.conn.db.character().id().find(&me) else { return Ok(()) };
        let lines = self.talk.lock().unwrap().pairs.get(&pair(me, other)).map(|c| c.lines.clone()).unwrap_or_default();
        let Some(heard) = lines.iter().rev().find(|l| l.speaker == other).cloned() else { return Ok(()) };
        let (system, user) = self.talk_prompt(&c, other, &lines, &heard).await;
        let mut profile = self.profile(&c);
        let messages = [Msg { role: "system", content: system }, Msg { role: "user", content: user }];
        let (reply, v) = {
            let _talk = self.talk_sem.acquire().await?;
            let _permit = self.sem.acquire().await?;
            let mut attempt = 0;
            loop {
                let reply = self.llm.chat(&profile, "talk", &c.name, &messages).await?;
                match llm::parse_json(&reply.content) {
                    Ok(v) => break (reply, v),
                    Err(e) if attempt == 0 && profile != self.llm.default_profile() => {
                        log::warn!("{}: unusable talk reply from {} ({e:#}); retrying with {}", c.name, reply.model, self.llm.default_profile());
                        profile = self.llm.default_profile();
                        attempt += 1;
                    }
                    Err(e) => return Err(e),
                }
            }
        };
        let (say, to) = match &v["say"] {
            Value::String(s) => (s.trim().to_string(), id_of(&v["to"])),
            Value::Object(o) => (o.get("text").and_then(|t| t.as_str()).unwrap_or_default().trim().to_string(), o.get("to").map(id_of).unwrap_or(0).max(id_of(&v["to"]))),
            _ => (String::new(), 0),
        };
        let say = if say.eq_ignore_ascii_case("null") || say == "..." { String::new() } else { say };
        let to = if to != 0 && to != me && self.conn.db.character().id().find(&to).map_or(false, |c| c.kind == "person") { to } else { other };
        let end = v["end"].as_bool().unwrap_or(false) || say.is_empty();
        let thought = flat(&v["thought"]);
        let other_name = self.name(other);
        let summary = format!(
            "{thought} → {}{}",
            if say.is_empty() { format!("says nothing to {other_name}") } else { format!("says to {}: “{say}”", self.name(to)) },
            if end && !say.is_empty() { " (and ends the conversation)" } else { "" }
        );
        let t = ThoughtIn {
            kind: "talk".into(),
            summary,
            detail: json!({"with": other, "heard": heard.text, "reply": v, "conversation": lines.iter().map(|l| json!({"speaker": l.speaker, "to": l.to, "text": l.text})).collect::<Vec<_>>()}).to_string(),
            latency_ms: reply.latency_ms,
            tokens: reply.tokens,
            model: reply.model.clone(),
            reference: reference(me, "talk"),
        };
        // Answer once the other has had time to say their line (and no faster than the
        // authority allows one to speak).
        let last = self.talk.lock().unwrap().spoke.get(&me).copied().unwrap_or(0);
        let wait = (last + SPEECH_GAP_MS).max(heard.at_ms + saying_ms(&heard.text)).saturating_sub(llm::now_ms());
        if wait > 0 {
            tokio::time::sleep(Duration::from_millis(wait)).await;
        }
        // Record the turn before speaking: the listener's experience of this line can arrive
        // before the reducer's reply, and must be recognized as part of this exchange.
        let text: String = say.chars().take(400).collect();
        let now = llm::now_ms();
        {
            let mut tk = self.talk.lock().unwrap();
            if !say.is_empty() {
                tk.spoke.insert(me, now);
            }
            let c = tk.pairs.entry(pair(me, other)).or_default();
            c.turns += 1;
            c.ended |= end || (to != other && !say.is_empty());
            c.last_ms = now;
            if !say.is_empty() {
                let line = Line { speaker: me, to, text: text.clone(), at_ms: now, at: heard.at, turn: true };
                if to == other {
                    c.lines.push(line);
                } else {
                    // Turned to someone else: that is a conversation with them now.
                    let d = tk.pairs.entry(pair(me, to)).or_default();
                    d.lines.push(line);
                    d.last_ms = now;
                }
            }
        }
        let mut result = self.say(me, say.clone(), to, t.clone()).await;
        if matches!(&result, Err(e) if e.to_string().contains("too fast")) {
            tokio::time::sleep(Duration::from_millis(SPEECH_GAP_MS)).await;
            result = self.say(me, say.clone(), to, t).await;
        }
        if result.is_err() && !say.is_empty() {
            let mut tk = self.talk.lock().unwrap();
            if let Some(c) = tk.pairs.get_mut(&pair(me, to)) {
                c.lines.retain(|l| !(l.turn && l.speaker == me && l.at_ms == now));
            }
        }
        log::info!("{} {}", c.name, if say.is_empty() { format!("says nothing to {other_name}") } else { format!("to {}: “{say}”{}", self.name(to), if end { " (ends)" } else { "" }) });
        result
    }

    async fn say(&self, actor: u32, say: String, to: u32, t: ThoughtIn) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_say_then(actor, say, to, 0, t, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_say: {e}"))
    }

    /// Who they are, how they feel about the other, what they hold about them, what happened
    /// between them lately, where they are, and the conversation so far.
    async fn talk_prompt(&self, c: &Character, other: u32, lines: &[Line], heard: &Line) -> (String, String) {
        let me = c.id;
        let other_name = self.name(other);
        let fmt = self.fmt_time();
        let persona = self.conn.db.persona().id().find(&me);
        let identity = match &persona {
            Some(p) => format!("{}\nValues: {}\nGoals: {}\nMood: {}", p.narrative, p.values.join("; "), p.goals.join("; "), p.mood),
            None => format!("You are {}.", c.name),
        };
        let feeling = self
            .conn
            .db
            .relation()
            .iter()
            .find(|r| r.actor == me && r.other == other)
            .map(|r| format!("{}: trust {:.0}, affinity {:.0}{}", if r.label.is_empty() { "no word for it yet" } else { &r.label }, r.trust, r.affinity, if r.note.is_empty() { String::new() } else { format!(" — {}", r.note) }))
            .unwrap_or_else(|| "You have no settled feelings about them yet.".into());
        let beliefs: Vec<String> = match &self.store {
            Some(store) => store.around(me, &[format!("person:{other}")], 10).await.unwrap_or_default().iter().map(|f| memory::render(f, &fmt)).collect(),
            None => Vec::new(),
        };
        let lately: Vec<String> = {
            let all: Vec<Experience> = self.experiences(me).into_iter().filter(|e| (e.subject == other || e.object == other) && e.kind != "speech").collect();
            let n = all.len();
            all.iter().skip(n.saturating_sub(6)).map(|e| self.exp_line(e, &fmt, false)).collect()
        };
        let now = llm::now_ms();
        let w = self.conn.db.world().id().find(&0);
        let hour = w.as_ref().map(|w| living_rules::hour_of(now, w.epoch_ms, w.day_ms)).unwrap_or(12.0);
        let part = match hour as u32 {
            6..=11 => "morning",
            12..=16 => "afternoon",
            17..=19 => "evening",
            _ => "night",
        };
        let place = self
            .conn
            .db
            .place()
            .iter()
            .filter(|p| p.actor == me)
            .map(|p| (((p.x - heard.at.0).powi(2) + (p.y - heard.at.1).powi(2)).sqrt(), p.name))
            .filter(|(d, _)| *d <= 15.0)
            .min_by(|a, b| a.0.total_cmp(&b.0))
            .map(|(d, n)| if d <= 4.0 { format!("at \"{n}\"") } else { format!("near \"{n}\"") })
            .unwrap_or_else(|| "away from the places you know".into());
        let doing = self.conn.db.brain().id().find(&me).map(|b| b.plan).filter(|p| !p.is_empty()).unwrap_or_else(|| "going about your day".into());
        let scene = format!("{} ({part}), {place}. What you are doing: {doing}.", fmt(now));
        let convo: Vec<String> = lines.iter().rev().take(12).rev().map(|l| {
            let who = if l.speaker == me { "You".to_string() } else { self.name(l.speaker) };
            let to = if l.to != 0 && l.to != me && l.to != other { format!(" (to {})", self.name(l.to)) } else { String::new() };
            format!("{who}{to}: “{}”", l.text)
        }).collect();
        (prompts::talk_system(&c.name, &other_name, other), prompts::talk_user(&identity, &other_name, other, &feeling, &beliefs, &lately, &scene, &convo))
    }
}

/// About how long a line takes to say aloud (people speak ~3 words a second).
fn saying_ms(text: &str) -> u64 {
    (text.split_whitespace().count() as u64 * 330).clamp(1_500, 8_000)
}

fn id_of(v: &Value) -> u32 {
    match v {
        Value::Number(n) => n.as_u64().unwrap_or(0) as u32,
        Value::String(s) => s.trim().trim_start_matches('#').parse().unwrap_or(0),
        _ => 0,
    }
}

fn flat(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string().chars().take(300).collect(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quoted_words_and_ids() {
        assert_eq!(quoted("Mira said to you: “Did you sleep?”"), "Did you sleep?");
        assert_eq!(quoted("no quotes"), "no quotes");
        assert_eq!(id_of(&json!("#7")), 7);
        assert_eq!(id_of(&json!(12)), 12);
        assert_eq!(id_of(&Value::Null), 0);
        assert_eq!(saying_ms("Hi."), 1_500);
        assert_eq!(saying_ms(&"word ".repeat(12)), 3_960);
    }
}
