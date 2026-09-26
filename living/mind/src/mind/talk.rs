//! Conversations: an exchange of turns between two minds.
//!
//! When a character this service controls hears speech addressed to it (or, when it cares
//! about the speaker, speech nobody in particular was addressed by), its mind may get a
//! *reply turn*: a small model call with who it is, its temperament, how it feels about the
//! speaker, what the moment brings to mind (situational recall cued by the speaker, the words
//! said and the place), what happened between them lately, what they settled before, the
//! conversation so far and the line it is answering. The answer is spoken through `mind_say`
//! (kind `talk`), which keeps the behavior graph and leaves pending deliberations alone.
//!
//! Pacing comes from the people, not a fixed rule:
//! - how many turns someone takes in one exchange (their *stamina*) follows from their
//!   sociability, mood and fondness for the other; their last turn is told to wrap up;
//! - remarks that ask nothing are answered more often by the talkative than by the reserved;
//! - a turn can close the exchange by saying what is *settled* ("meet at the ford at dawn",
//!   "I'll think about it", "no") and *until* when; the pair then does not take turns again until that
//!   time comes, something happens between them, or one of them brings up something new
//!   (a question or request on another matter). Echoes of what was already said (including a
//!   behavior graph's `say` node repeating itself) do not reopen it.
//! - an outcome is the closing speaker's own conclusion, so it is written into their mind
//!   (`self -AGREED-> agreement:person_<id> -WITH-> person:<id>`) where recall brings it back
//!   when that person, the place or the time comes up again.
//!
//! The conversation state here is only a working memory of the exchange (per pair, in
//! memory). The authority remains the record: every line is a `speak` (chronicle and
//! experiences), so consolidation integrates conversations like anything else lived.

use super::{flatten, reference, Minds};
use crate::llm::{self, Msg};
use crate::memory::{self, Cues};
use crate::prompts;
use anyhow::{anyhow, Result};
use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::Table;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::oneshot;

/// Reply turns in one conversation (both sides together); stamina usually ends it sooner.
const MAX_TURNS: u32 = 12;
/// A conversation that has been quiet this long is over; the next line starts a new one.
const QUIET_MS: u64 = 90_000;
/// Speech older than this (e.g. replayed when the service starts) gets no turn.
const STALE_MS: u64 = 30_000;
/// A listener is invited by speech not addressed to them at most this often.
const OVERHEARD_GAP_MS: u64 = 60_000;
/// The authority refuses speech within 2 s of one's previous line.
const SPEECH_GAP_MS: u64 = 2_100;
/// Share of a line's words that must be new to the exchange for it to count as a new matter.
const NEW_MATTER: f64 = 0.5;

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
    /// The listener's experience of it (0 for one's own lines).
    exp: u64,
}

/// How an exchange was closed.
#[derive(Clone, Debug)]
struct Settled {
    outcome: String,
    until_ms: u64,
    at_ms: u64,
}

#[derive(Default)]
struct Conversation {
    lines: Vec<Line>,
    turns: u32,
    /// Reply turns each side has taken in this exchange.
    own: HashMap<u32, u32>,
    ended: bool,
    last_ms: u64,
    settled: Option<Settled>,
    /// What an exchange reopened after being settled starts from.
    reopened: Option<(Settled, String)>,
}

impl Conversation {
    /// Share of the line's words that nothing in this exchange (or what was settled) said.
    fn novelty(&self, text: &str) -> f64 {
        self.novelty_without(text, &[])
    }

    /// Novelty, not counting the given words (e.g. the pair's own names).
    fn novelty_without(&self, text: &str, skip: &[String]) -> f64 {
        let words: Vec<String> = memory::cue_words(text).into_iter().filter(|w| !skip.contains(w)).collect();
        if words.is_empty() {
            return 0.0;
        }
        let mut known: Vec<String> = self.lines.iter().flat_map(|l| memory::cue_words(&l.text)).collect();
        for s in self.settled.iter().chain(self.reopened.iter().map(|r| &r.0)) {
            known.extend(memory::cue_words(&s.outcome));
        }
        words.iter().filter(|w| !known.contains(w)).count() as f64 / words.len() as f64
    }
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
    /// Recent reply-turn lines per character (for "you have talked a lot lately").
    said: HashMap<u32, Vec<u64>>,
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

/// A small deterministic draw in [0, 1) for one listener and line.
fn draw(listener: u32, at_ms: u64) -> f64 {
    let mut h: u64 = 0x9E3779B97F4A7C15 ^ ((listener as u64) << 32) ^ at_ms;
    h ^= h >> 33;
    h = h.wrapping_mul(0xff51afd7ed558ccd);
    h ^= h >> 33;
    (h % 10_000) as f64 / 10_000.0
}

/// Someone's temperament for talk: sociability 0-100 (50 if unknown) and mood.
#[derive(Clone, Debug)]
struct Temper {
    sociability: f64,
    introspection: f64,
    mood: String,
}

impl Temper {
    fn from(traits: &str, mood: &str) -> Self {
        let t: Value = serde_json::from_str(traits).unwrap_or_default();
        let num = |k: &str| t[k].as_f64().or_else(|| t[k].as_str().and_then(|s| s.parse().ok())).unwrap_or(50.0).clamp(0.0, 100.0);
        Temper { sociability: num("sociability"), introspection: num("introspection"), mood: mood.to_string() }
    }

    /// Own turns in one exchange before wanting to move on: 1 for the most reserved, up to 6
    /// for the most sociable; a low or withdrawn mood shortens it, a bright one and fondness
    /// for the other lengthen it.
    fn stamina(&self, affinity: f32) -> u32 {
        let m = self.mood.to_lowercase();
        let low = ["grief", "griev", "sad", "tired", "exhaust", "weary", "withdrawn", "angry", "bitter", "numb", "afraid", "fear"].iter().any(|w| m.contains(w));
        let bright = ["cheer", "happy", "playful", "excited", "joy", "warm", "curious", "hopeful"].iter().any(|w| m.contains(w));
        let base = 1.0 + self.sociability / 25.0 - if low { 1.0 } else { 0.0 } + if bright { 0.5 } else { 0.0 } + if affinity >= 60.0 { 1.0 } else { 0.0 };
        (base.round() as i64).clamp(1, 6) as u32
    }

    /// How likely a remark that asks nothing draws an answer.
    fn answers_remarks(&self) -> f64 {
        0.3 + 0.65 * self.sociability / 100.0
    }

    fn describe(&self) -> String {
        let s = self.sociability;
        let how = if s < 35.0 {
            "you speak little and let silences be"
        } else if s < 65.0 {
            "you talk when there is something to say"
        } else {
            "you enjoy talking and draw others out"
        };
        format!("sociability {s:.0}/100 ({how}), introspection {:.0}/100; mood: {}", self.introspection, if self.mood.is_empty() { "—" } else { &self.mood })
    }
}

/// When to take a matter up again, from a reply's `until` (an hour or words like "dawn",
/// "tomorrow", "evening"), as a time in ms; `None` if not understood.
fn until_ms(until: &Value, now: u64, epoch: u64, day_ms: u64) -> Option<u64> {
    let hour_ms = day_ms as f64 / 24.0;
    let at_hour = |target: f64, tomorrow: bool| -> u64 {
        let ch = living_rules::hour_of(now, epoch, day_ms) as f64;
        let mut delta = (target - ch).rem_euclid(24.0);
        if delta < 0.5 {
            delta += 24.0;
        }
        if tomorrow && ch + delta < 24.0 && ch >= 6.0 {
            delta += 24.0;
        }
        now + (delta * hour_ms) as u64
    };
    match until {
        Value::Number(n) => n.as_f64().filter(|h| (0.0..=24.0).contains(h)).map(|h| at_hour(h, false)),
        Value::String(s) => {
            let s = s.to_lowercase();
            let tomorrow = s.contains("tomorrow");
            let table: &[(&[&str], f64)] = &[
                (&["dawn", "first light", "sunrise", "daybreak"], 6.0),
                (&["morning"], 8.0),
                (&["noon", "midday"], 12.0),
                (&["afternoon"], 15.0),
                (&["evening", "dusk", "sunset"], 18.0),
                (&["night", "tonight", "dark"], 21.0),
            ];
            for (words, h) in table {
                if words.iter().any(|w| s.contains(w)) {
                    return Some(at_hour(*h, tomorrow));
                }
            }
            if let Some(h) = s.split(|c: char| !c.is_ascii_digit()).find(|x| !x.is_empty()).and_then(|x| x.parse::<f64>().ok()).filter(|h| *h <= 24.0) {
                return Some(at_hour(h, tomorrow));
            }
            if tomorrow {
                return Some(at_hour(8.0, true));
            }
            if ["later", "soon", "after", "while"].iter().any(|w| s.contains(w)) {
                return Some(now + (2.0 * hour_ms) as u64);
            }
            None
        }
        _ => None,
    }
}

impl Talks {
    fn prune(&mut self, now: u64) {
        self.pairs.retain(|_, c| now.saturating_sub(c.last_ms) < QUIET_MS * 2 || c.settled.as_ref().map_or(false, |s| now < s.until_ms));
        self.claimed.retain(|(_, at), _| now.saturating_sub(*at) < STALE_MS * 2);
        for v in self.said.values_mut() {
            v.retain(|t| now.saturating_sub(*t) < 5 * 60_000);
        }
    }
}

impl Minds {
    fn temper(&self, id: u32) -> Temper {
        self.conn.db.persona().id().find(&id).map(|p| Temper::from(&p.traits, &p.mood)).unwrap_or_else(|| Temper::from("{}", ""))
    }

    fn affinity(&self, me: u32, other: u32) -> f32 {
        self.conn.db.relation().iter().find(|r| r.actor == me && r.other == other).map_or(0.0, |r| r.affinity)
    }

    /// What happened to the listener since `since` that the pair may want to talk about:
    /// events involving the other (not speech), or anything momentous.
    fn happened_since(&self, listener: u32, other: u32, since: u64) -> Vec<String> {
        self.experiences(listener)
            .into_iter()
            .filter(|x| x.at_ms > since && !matches!(x.kind.as_str(), "speech" | "silence" | "repeat"))
            .filter(|x| ((x.subject == other || x.object == other) && x.salience >= 0.4) || x.salience >= 0.7)
            .map(|x| x.text)
            .collect()
    }

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
        let asks = text.contains('?');
        let temper = self.temper(listener);
        let stamina = temper.stamina(self.affinity(listener, speaker));
        let cares = || self.cares(listener, speaker);
        let key = pair(listener, speaker);
        let settled_at = self.talk.lock().unwrap().pairs.get(&key).and_then(|c| c.settled.as_ref().map(|s| s.at_ms));
        let names: Vec<String> = [listener, speaker].iter().flat_map(|id| memory::cue_words(&self.name(*id))).collect();
        let happened = settled_at.map(|at| self.happened_since(listener, speaker, at)).unwrap_or_default();
        let go = {
            let mut t = self.talk.lock().unwrap();
            t.prune(now);
            let active = t.pairs.get(&key).map_or(false, |c| !c.ended && now.saturating_sub(c.last_ms) < QUIET_MS);
            let in_other = t.pairs.iter().any(|(k, c)| *k != key && (k.0 == listener || k.1 == listener) && !c.ended && now.saturating_sub(c.last_ms) < QUIET_MS);
            let overheard_ok = to == 0
                && !in_other
                && t.overheard.get(&listener).map_or(true, |at| now.saturating_sub(*at) > OVERHEARD_GAP_MS)
                && !t.claimed.contains_key(&(speaker, e.at_ms))
                && cares()
                && draw(listener, e.at_ms) < temper.answers_remarks();
            if !(addressed || (active && to == 0) || overheard_ok) {
                return;
            }
            if !addressed && !active {
                t.overheard.insert(listener, now);
                t.claimed.insert((speaker, e.at_ms), listener);
            }
            let c = t.pairs.entry(key).or_default();
            if now.saturating_sub(c.last_ms) >= QUIET_MS && c.settled.is_none() {
                *c = Conversation::default();
            }
            // Our own reply turns record their lines when they speak; anything else is new.
            let known = c.lines.iter().any(|l| l.turn && l.speaker == speaker && l.text == text && e.at_ms.abs_diff(l.at_ms) < 20_000);
            let novelty = if known { 0.0 } else { c.novelty(&text) };
            c.last_ms = now;
            // A settled exchange stays settled until its time comes, something happens between
            // them, or one of them brings up something new.
            if let Some(s) = c.settled.clone() {
                let why = if now >= s.until_ms {
                    Some("the time you set has come".to_string())
                } else if let Some(h) = happened.iter().find(|h| c.novelty_without(h, &names) >= NEW_MATTER) {
                    // Only news: an offer or act they already talked over does not reopen it.
                    Some(format!("since then: {h}"))
                } else if !known && novelty >= NEW_MATTER && (asks || addressed) {
                    Some("they bring up something new".to_string())
                } else {
                    None
                };
                match why {
                    None => {
                        if !known {
                            c.lines.push(Line { speaker, to, text: text.clone(), at_ms: e.at_ms, at: (e.x, e.y), turn: false, exp: e.id });
                        }
                        log::info!(
                            "{} hears {} but they settled{} — no turn",
                            me.name,
                            self.name(speaker),
                            if s.outcome.is_empty() { String::new() } else { format!(" “{}”", s.outcome) }
                        );
                        return;
                    }
                    Some(why) => {
                        log::info!("{} and {}: settled exchange reopens ({why})", me.name, self.name(speaker));
                        let lines = std::mem::take(&mut c.lines);
                        *c = Conversation { reopened: Some((s, why)), last_ms: now, ..Default::default() };
                        c.lines = lines.into_iter().rev().take(4).rev().collect();
                    }
                }
            }
            if !known {
                c.lines.push(Line { speaker, to, text: text.clone(), at_ms: e.at_ms, at: (e.x, e.y), turn: false, exp: e.id });
                // A line from outside the exchange (a decision, a human) reopens a finished one
                // only when it says something new.
                if (c.ended || c.turns >= MAX_TURNS) && novelty >= NEW_MATTER {
                    c.ended = false;
                    c.turns = 0;
                    c.own.clear();
                }
            }
            if c.ended || c.turns >= MAX_TURNS {
                return;
            }
            // They have said their piece for this exchange (their last turn wrapped up).
            if c.own.get(&listener).copied().unwrap_or(0) >= stamina {
                log::debug!("{} has said enough to {} for now", me.name, self.name(speaker));
                return;
            }
            // A remark that asks nothing does not always draw an answer: the talkative answer
            // more often than the reserved.
            if !asks && draw(listener, e.at_ms ^ 0x5EED) >= temper.answers_remarks() {
                log::debug!("{} lets {}'s remark pass", me.name, self.name(speaker));
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
                    let due = waiting.filter(|s| {
                        t.pairs.get(&pair(listener, *s)).map_or(false, |c| !c.ended && c.settled.is_none() && c.turns < MAX_TURNS && c.lines.last().map_or(false, |l| l.speaker == *s))
                    });
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
        let temper = self.temper(me);
        let stamina = temper.stamina(self.affinity(me, other));
        let (lines, own, reopened, lately_said) = {
            let mut t = self.talk.lock().unwrap();
            let now = llm::now_ms();
            let lately_said = t.said.get(&me).map_or(0, |v| v.iter().filter(|x| now.saturating_sub(**x) < 5 * 60_000).count());
            let conv = t.pairs.entry(pair(me, other)).or_default();
            (conv.lines.clone(), conv.own.get(&me).copied().unwrap_or(0), conv.reopened.clone(), lately_said)
        };
        let Some(heard) = lines.iter().rev().find(|l| l.speaker == other).cloned() else { return Ok(()) };
        let last_word = own + 1 >= stamina;
        let ctx = TalkCtx { temper: &temper, lately_said, own, last_word, reopened: reopened.as_ref() };
        let (system, user) = self.talk_prompt(&c, other, &lines, &heard, &ctx).await;
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
        // What the speaker says is now settled closes the exchange (their own judgment).
        let outcome = flat(if v["settled"].is_null() || v["settled"] == json!(false) { &v["outcome"] } else { &v["settled"] }).trim().to_string();
        let outcome: String = if ["null", "none", "nothing", "-", "n/a", "false", "no", "open"].contains(&outcome.to_lowercase().as_str()) { String::new() } else { outcome.chars().take(160).collect() };
        let end = v["end"].as_bool().unwrap_or(false) || say.is_empty() || !outcome.is_empty();
        // "Nothing more to say" closes without anything to remember.
        let outcome = if outcome.to_lowercase().starts_with("nothing") { String::new() } else { outcome };
        let thought = flat(&v["thought"]);
        let other_name = self.name(other);
        let now = llm::now_ms();
        let (epoch, day_ms) = self.conn.db.world().id().find(&0).map(|w| (w.epoch_ms, w.day_ms)).unwrap_or((0, living_rules::DEFAULT_DAY_MS));
        let hour_ms = day_ms / 24;
        // Closed with an outcome: settled until the time given (or a while); closed without
        // one: at rest for a few hours of the day unless something new comes up.
        let settled = end.then(|| Settled {
            outcome: outcome.clone(),
            until_ms: until_ms(&v["until"], now, epoch, day_ms).unwrap_or(now + if outcome.is_empty() { 4 } else { 6 } * hour_ms),
            at_ms: now,
        });
        let fmt = self.fmt_time();
        let summary = format!(
            "{thought} → {}{}",
            if say.is_empty() { format!("says nothing to {other_name}") } else { format!("says to {}: “{say}”", self.name(to)) },
            match &settled {
                Some(s) if !s.outcome.is_empty() => format!(" (settled: {} — until {})", s.outcome, fmt(s.until_ms)),
                Some(_) if !say.is_empty() => " (and ends the conversation)".to_string(),
                _ => String::new(),
            }
        );
        let t = ThoughtIn {
            kind: "talk".into(),
            summary,
            detail: json!({"with": other, "heard": heard.text, "reply": v, "stamina": stamina, "own_turns": own + 1, "last_word": last_word,
                           "settled": settled.as_ref().map(|s| json!({"outcome": s.outcome, "until_ms": s.until_ms})),
                           "conversation": lines.iter().map(|l| json!({"speaker": l.speaker, "to": l.to, "text": l.text})).collect::<Vec<_>>()})
            .to_string(),
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
                tk.said.entry(me).or_default().push(now);
            }
            let c = tk.pairs.entry(pair(me, other)).or_default();
            c.turns += 1;
            *c.own.entry(me).or_default() += 1;
            c.ended |= end || (to != other && !say.is_empty());
            c.last_ms = now;
            if let Some(s) = &settled {
                c.settled = Some(s.clone());
                c.reopened = None;
            }
            if !say.is_empty() {
                let line = Line { speaker: me, to, text: text.clone(), at_ms: now, at: heard.at, turn: true, exp: 0 };
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
        // What was settled is the speaker's own conclusion: it goes into their mind.
        if let (Some(s), Some(store)) = (&settled, &self.store) {
            if !s.outcome.is_empty() {
                let key = format!("agreement:person_{other}");
                let mut props = serde_json::Map::new();
                props.insert("with".into(), json!(other_name));
                props.insert("until".into(), json!(fmt(s.until_ms)));
                props.insert("settled".into(), json!(fmt(s.at_ms)));
                let mut edge_props = serde_json::Map::new();
                edge_props.insert("until".into(), json!(fmt(s.until_ms)));
                let because: Vec<u64> = (heard.exp != 0).then_some(heard.exp).into_iter().collect();
                let patch = memory::Patch {
                    nodes: vec![memory::NodeOp { key: key.clone(), labels: vec!["Agreement".into()], name: Some(s.outcome.clone()), props }],
                    edges: vec![
                        memory::EdgeOp { from: "self".into(), rel: "AGREED".into(), to: key.clone(), confidence: 0.9, because: because.clone(), props: edge_props },
                        memory::EdgeOp { from: key, rel: "WITH".into(), to: format!("person:{other}"), confidence: 0.9, because, props: Default::default() },
                    ],
                    ..Default::default()
                };
                if let Err(e) = store.apply(me, &patch, &t.reference, now).await {
                    log::warn!("{}: agreement not remembered: {e:#}", c.name);
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
        log::info!(
            "{} {}",
            c.name,
            if say.is_empty() {
                format!("says nothing to {other_name}")
            } else {
                format!(
                    "to {}: “{say}”{}",
                    self.name(to),
                    match &settled {
                        Some(s) if !s.outcome.is_empty() => format!(" (settled: {})", s.outcome),
                        Some(_) => " (ends)".into(),
                        None => String::new(),
                    }
                )
            }
        );
        result
    }

    async fn say(&self, actor: u32, say: String, to: u32, t: ThoughtIn) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_say_then(actor, say, to, 0, t, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_say: {e}"))
    }

    /// Who they are and how they talk, how they feel about the other, what the moment brings
    /// to mind, what happened between them lately and what they settled before, where they
    /// are, the conversation so far and the line they are answering.
    async fn talk_prompt(&self, c: &Character, other: u32, lines: &[Line], heard: &Line, ctx: &TalkCtx<'_>) -> (String, String) {
        let me = c.id;
        let other_name = self.name(other);
        let fmt = self.fmt_time();
        let persona = self.conn.db.persona().id().find(&me);
        let identity = match &persona {
            Some(p) => format!("{}\nValues: {}\nGoals: {}", p.narrative, p.values.join("; "), p.goals.join("; ")),
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
        let lately: Vec<String> = {
            let all: Vec<Experience> = self.experiences(me).into_iter().filter(|e| (e.subject == other || e.object == other) && !matches!(e.kind.as_str(), "speech" | "repeat")).collect();
            let n = all.len();
            all.iter().skip(n.saturating_sub(5)).map(|e| self.exp_line(e, &fmt, false)).collect()
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
        let near = self
            .conn
            .db
            .place()
            .iter()
            .filter(|p| p.actor == me)
            .map(|p| (((p.x - heard.at.0).powi(2) + (p.y - heard.at.1).powi(2)).sqrt(), p.name))
            .filter(|(d, _)| *d <= 15.0)
            .min_by(|a, b| a.0.total_cmp(&b.0));
        let place = near.as_ref().map(|(d, n)| if *d <= 4.0 { format!("at \"{n}\"") } else { format!("near \"{n}\"") }).unwrap_or_else(|| "away from the places you know".into());
        let plan = self.conn.db.brain().id().find(&me).map(|b| b.plan).filter(|p| !p.is_empty());
        let doing = plan.clone().unwrap_or_else(|| "going about your day".into());
        let scene = format!("{} ({part}), {place}. What you are doing: {doing}.", fmt(now));
        // What this exchange brings to mind: the other person, what was said, the place, the hour.
        let mut cues = Cues::default();
        cues.key(format!("person:{other}"), 1.2);
        cues.text(&heard.text, 1.0);
        for l in lines.iter().rev().skip(1).take(4) {
            cues.text(&l.text, 0.5);
        }
        for id in self.named_people(&lines.iter().rev().take(3).map(|l| l.text.as_str()).collect::<Vec<_>>().join(" ")) {
            if id != me && id != other {
                cues.key(format!("person:{id}"), 0.8);
            }
        }
        if let Some((_, n)) = &near {
            if let Some(k) = memory::key(n) {
                cues.key(format!("place:{}", k.trim_start_matches("place:")), 0.6);
            }
        }
        cues.text(super::recall::day_words(hour), 0.4);
        if let Some(p) = &plan {
            cues.text(p, 0.3);
        }
        let recalled = self.recall_for(me, &cues.bounded(), 8, 3).await;
        let mut mind = recalled.mind;
        mind.extend(recalled.cued_stances.into_iter().take(3).map(|s| format!("you hold: {s}")));
        let convo: Vec<String> = lines
            .iter()
            .rev()
            .take(12)
            .rev()
            .map(|l| {
                let who = if l.speaker == me { "You".to_string() } else { self.name(l.speaker) };
                let to = if l.to != 0 && l.to != me && l.to != other { format!(" (to {})", self.name(l.to)) } else { String::new() };
                format!("{who}{to}: “{}”", l.text)
            })
            .collect();
        let mut pacing = format!(
            "{}\nYou have said {} thing{} in conversations over the last few minutes; this is your turn number {} with {other_name} now.",
            ctx.temper.describe(),
            ctx.lately_said,
            if ctx.lately_said == 1 { "" } else { "s" },
            ctx.own + 1
        );
        if ctx.last_word {
            pacing.push_str(" You have said about as much as you want to for now: make this your last word (end: true), and say what was settled, if anything.");
        }
        let earlier = ctx.reopened.map(|(s, why)| format!("Earlier you two settled{} ({}). Now {why}.", if s.outcome.is_empty() { " nothing in particular and parted".to_string() } else { format!(": “{}”", s.outcome) }, fmt(s.at_ms)));
        let t = prompts::TalkUser {
            identity: &identity,
            pacing: &pacing,
            other: &other_name,
            other_id: other,
            feeling: &feeling,
            mind: &mind,
            memories: &recalled.memories,
            lately: &lately,
            earlier: earlier.as_deref(),
            scene: &scene,
            conversation: &convo,
            heard: &heard.text,
        };
        (prompts::talk_system(&c.name, &other_name, other), prompts::talk_user(&t))
    }
}

/// Talk context beyond the conversation itself.
struct TalkCtx<'a> {
    temper: &'a Temper,
    lately_said: usize,
    own: u32,
    last_word: bool,
    reopened: Option<&'a (Settled, String)>,
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

    #[test]
    fn stamina_follows_temperament() {
        let quiet = Temper::from(r#"{"sociability": 10}"#, "weary");
        let warm = Temper::from(r#"{"sociability": 90}"#, "cheerful");
        assert_eq!(quiet.stamina(0.0), 1);
        assert!(warm.stamina(70.0) >= 5);
        assert!(quiet.answers_remarks() < 0.4 && warm.answers_remarks() > 0.85);
        assert_eq!(Temper::from("not json", "").stamina(0.0), 3);
    }

    #[test]
    fn until_understands_times_of_day() {
        let day = 24 * 60_000u64; // an hour is a real minute
        let epoch = 0;
        let now = 13 * 60_000; // 20:00 (the world starts at 07:00)
        assert_eq!(until_ms(&json!("dawn"), now, epoch, day), Some(now + 10 * 60_000));
        assert_eq!(until_ms(&json!(22), now, epoch, day), Some(now + 2 * 60_000));
        assert_eq!(until_ms(&json!("tomorrow morning"), now, epoch, day), Some(now + 12 * 60_000));
        assert_eq!(until_ms(&json!("later"), now, epoch, day), Some(now + 2 * 60_000));
        assert_eq!(until_ms(&json!("whenever"), now, epoch, day), None);
    }

    #[test]
    fn echoes_are_not_new_matter() {
        let mut c = Conversation::default();
        c.lines.push(Line { speaker: 1, to: 2, text: "Let's meet at the ford at dawn to check the traps.".into(), at_ms: 0, at: (0.0, 0.0), turn: true, exp: 0 });
        c.settled = Some(Settled { outcome: "meet at the ford at dawn".into(), until_ms: 1, at_ms: 0 });
        assert!(c.novelty("At dawn then, at the ford, for the traps.") < NEW_MATTER);
        assert!(c.novelty("Did you hear that Bram's roof collapsed last night?") >= NEW_MATTER);
        // An act they already talked over is not news.
        c.lines.push(Line { speaker: 2, to: 1, text: "Three berries for one wood, then.".into(), at_ms: 0, at: (0.0, 0.0), turn: true, exp: 0 });
        assert!(c.novelty_without("Iseisevik offers you 3 berries for 1 wood.", &["iseisevik".to_string()]) < NEW_MATTER);
    }
}
