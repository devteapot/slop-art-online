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

use super::{acts_of, acts_text, flatten, reference, Minds};
use crate::llm::{self, Lane, Msg};
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
/// `LIVING_GREET`: a line said to no one in particular within this many metres of a hearer
/// can draw that hearer in (`nearest`, `curious`), and the speaker faces a hearer at most this
/// far away (`facing`). The authority's own `address_m` law is 6 m by default.
const GREET_NEAR_M: f32 = 6.0;
/// `LIVING_GREET=facing`: a hearer within this many radians of the speaker's facing is faced.
const FACE_CONE: f32 = 0.6;
/// `LIVING_PARK=concurrent`: a line heard within this long after a deliberation's prompt was
/// built (so it never saw the line) gets its turn while the deliberation runs.
const FRESH_MS: u64 = 2_000;

/// What draws a listener into a line said to no one in particular by someone they have not met
/// or barely know (`LIVING_GREET`; `nearest` by default since 2026-11-11, the owner's choice
/// after the paid greeting batches gr1/gr2, docs/TRIALS.md). Under every mode other than `off`, an
/// addressed line from such a speaker always gets a turn (the turn may still say nothing),
/// and hostility no longer counts as caring: a listener who feels strongly against the
/// speaker answers only lines addressed to them.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Greet {
    /// The rule before 2026-11-11: only a listener who cares about the speaker may be drawn in.
    Off,
    /// The default. The nearest hearer within `GREET_NEAR_M` who is free to talk takes the one
    /// turn.
    Nearest,
    /// A hearer within `GREET_NEAR_M` is drawn in by curiosity, paced by curiosity and
    /// sociability; the first drawn takes the one turn.
    Curious,
    /// The hearer the speaker faces (within `GREET_NEAR_M` and `FACE_CONE`) is addressed,
    /// whoever the speaker is. Not for players yet: a player's facing is where they last
    /// walked until the client sends a look (`human_face`), and then it belongs to players'
    /// lines only, or as a tie-break.
    Facing,
}

/// What happens to a line addressed to a listener whose deliberation is running
/// (`LIVING_PARK`; `concurrent` by default since 2026-11-11).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Park {
    /// The rule before 2026-11-11: it waits for the deliberation to end (and gets no turn if
    /// the deliberation spoke to the speaker after hearing it).
    Wait,
    /// The default. It gets its turn alongside the deliberation when the deliberation's prompt was built
    /// just before the line (within `FRESH_MS`), or as soon as the deliberation has decided and
    /// its words are not for the speaker. Whichever of the two speaks to the speaker first
    /// is the answer; the other's words to them are not said.
    Concurrent,
}

#[derive(Clone, Copy, Debug)]
pub struct Config {
    pub greet: Greet,
    pub park: Park,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        Self::parse(std::env::var("LIVING_GREET").ok().as_deref(), std::env::var("LIVING_PARK").ok().as_deref())
    }

    fn parse(greet: Option<&str>, park: Option<&str>) -> Result<Self> {
        let greet = match greet.map(|s| s.trim().to_lowercase()).as_deref() {
            None | Some("") | Some("nearest") => Greet::Nearest,
            Some("off") | Some("0") => Greet::Off,
            Some("curious") => Greet::Curious,
            Some("facing") => Greet::Facing,
            Some(x) => return Err(anyhow!("LIVING_GREET={x}: expected off, nearest, curious or facing")),
        };
        let park = match park.map(|s| s.trim().to_lowercase()).as_deref() {
            None | Some("") | Some("concurrent") => Park::Concurrent,
            Some("wait") => Park::Wait,
            Some(x) => return Err(anyhow!("LIVING_PARK={x}: expected wait or concurrent")),
        };
        Ok(Self { greet, park })
    }

    /// Whether the modes read who heard a line and how they stood (the `audience` table,
    /// written where the world's `speech_audience` law is on).
    pub fn audience(&self) -> bool {
        matches!(self.greet, Greet::Nearest | Greet::Curious | Greet::Facing)
    }
}

/// How a listener stands toward a speaker, for `LIVING_GREET`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Familiarity {
    /// Family, one community, or a warm or trusting relation.
    Known,
    /// They feel strongly against the speaker (affinity <= -40).
    Hostile,
    /// Not met: the speaker's name is not known to them.
    Stranger,
    /// Met (the name is known) but no bond to speak of.
    Barely,
}

impl Familiarity {
    fn unfamiliar(self) -> bool {
        matches!(self, Self::Stranger | Self::Barely)
    }
}

/// What is known of a heard line when deciding whether it draws the listener in.
#[derive(Clone, Copy, Debug)]
struct Facts {
    /// Said to the listener (`to`).
    to_me: bool,
    /// Said to no one in particular.
    to_none: bool,
    /// The authority marked it addressed to the listener (named, or the only one close by).
    marked: bool,
    /// `LIVING_GREET=facing`: the listener is the hearer the speaker faced.
    faced: bool,
    /// Said to no one, and the listener is free to be drawn in (in no other exchange, not drawn
    /// in within the last minute, the line not yet claimed by another listener).
    free: bool,
    /// The listener cares about the speaker (family, a close label, strong feelings).
    cares: bool,
    /// The listener's draw for this line, and how likely they answer a remark / are drawn in
    /// by curiosity.
    draw: f64,
    answers: f64,
    curious: f64,
    familiarity: Familiarity,
    /// Within `GREET_NEAR_M` of the speaker.
    near: bool,
    /// `LIVING_GREET=nearest`: the listener is the nearest hearer free to take the turn.
    nearest_is_me: bool,
    /// The listener settled an exchange with the speaker and its time has not come.
    settled: bool,
}

impl Default for Facts {
    fn default() -> Self {
        Facts { to_me: false, to_none: false, marked: false, faced: false, free: false, cares: false, draw: 1.0, answers: 0.0, curious: 0.0, familiarity: Familiarity::Known, near: false, nearest_is_me: false, settled: false }
    }
}

/// What a heard line draws from the listener.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Drawn {
    /// Drawn into a remark not addressed to them (cares, or `LIVING_GREET`).
    overheard: bool,
    /// Drawn in by `LIVING_GREET` (nearest or curious).
    greeted: bool,
    /// The turn is taken without the remark draw (a stranger's line that drew them in or was
    /// addressed to them).
    no_remark_draw: bool,
}

impl Facts {
    fn addressed(&self) -> bool {
        self.to_me || (self.to_none && self.marked) || self.faced
    }

    fn drawn(&self, greet: Greet) -> Drawn {
        let addressed = self.addressed();
        // With `LIVING_GREET`, hostility is not caring.
        let cares = self.cares && (greet == Greet::Off || self.familiarity == Familiarity::Known);
        let overheard = self.free && cares && self.draw < self.answers;
        let stranger = greet != Greet::Off && self.familiarity.unfamiliar();
        let greeted = self.free
            && !addressed
            && !overheard
            && stranger
            && !self.settled
            && match greet {
                Greet::Nearest => self.nearest_is_me,
                Greet::Curious => self.near && self.draw < self.curious,
                Greet::Off | Greet::Facing => false,
            };
        Drawn { overheard: overheard || greeted, greeted, no_remark_draw: greeted || (addressed && stranger) }
    }
}

/// The hearer a speaker faces: within `GREET_NEAR_M` and `FACE_CONE` of the facing, the one
/// most nearly straight ahead (the nearer on a tie).
fn faced(hearers: &[Hearer]) -> Option<u32> {
    hearers
        .iter()
        .filter(|h| h.d <= GREET_NEAR_M && h.off <= FACE_CONE)
        .min_by(|a, b| a.off.total_cmp(&b.off).then(a.d.total_cmp(&b.d)))
        .map(|h| h.id)
}

/// A running deliberation, as conversation turns see it (`LIVING_PARK=concurrent`).
#[derive(Default, Clone, Debug)]
struct Deliberating {
    /// When its prompt read the experiences (lines heard later were not in it).
    prompt_ms: Option<u64>,
    /// Whom its words are for, once it has decided (empty: nobody it is waiting to answer).
    decided: Option<Vec<u32>>,
    /// Lines its character said in turns taken alongside it: (to, at_ms, words).
    answered: Vec<(u32, u64, String)>,
}

impl Deliberating {
    /// Whether a line from `other` heard at `heard_ms` gets its turn alongside: never before
    /// the prompt is built (it will see the line); once decided, unless its words are for
    /// `other`; before that, when the line came within `FRESH_MS` after the prompt.
    fn alongside(&self, other: u32, heard_ms: u64) -> bool {
        let Some(prompt) = self.prompt_ms else { return false };
        match &self.decided {
            Some(targets) => !targets.contains(&other),
            None => heard_ms > prompt && heard_ms - prompt <= FRESH_MS,
        }
    }

    /// The people its character answered alongside it since its prompt.
    fn answered_since_prompt(&self) -> Vec<u32> {
        self.answered.iter().filter(|(_, at, _)| self.prompt_ms.is_some_and(|p| *at >= p)).map(|(o, _, _)| *o).collect()
    }
}

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
    /// Lines that came while the listener's deliberation was running (its prompt already
    /// built): listener → (speaker, when the line was heard). Taken up when it ends.
    parked: HashMap<u32, Vec<(u32, u64)>>,
    /// When a deliberation last spoke to someone: (speaker, listener) → at_ms.
    deliberated_to: HashMap<(u32, u32), u64>,
    /// Running deliberations (`LIVING_PARK=concurrent` only).
    deliberating: HashMap<u32, Deliberating>,
    /// Whether a missing `audience` row was reported (once).
    no_audience_logged: bool,
}

/// Relation labels that are a close bond.
const CLOSE: &[&str] = &["family", "partner", "friend", "parent", "mother", "father", "child", "son", "daughter", "sibling", "brother", "sister", "spouse", "wife", "husband", "lover"];

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
    curiosity: f64,
    mood: String,
}

impl Temper {
    fn from(traits: &str, mood: &str) -> Self {
        let t: Value = serde_json::from_str(traits).unwrap_or_default();
        let num = |k: &str| t[k].as_f64().or_else(|| t[k].as_str().and_then(|s| s.parse().ok())).unwrap_or(50.0).clamp(0.0, 100.0);
        Temper { sociability: num("sociability"), introspection: num("introspection"), curiosity: num("curiosity"), mood: mood.to_string() }
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

    /// `LIVING_GREET=curious`: how likely an unfamiliar person's remark close by draws them
    /// in: the remark draw, scaled from half (incurious) to whole (most curious).
    fn curious_of_strangers(&self) -> f64 {
        self.answers_remarks() * (0.5 + 0.5 * self.curiosity / 100.0)
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
    /// Whether a listener is in a live exchange with anyone but the other of `key`.
    fn in_other(&self, listener: u32, key: (u32, u32), now: u64) -> bool {
        self.pairs.iter().any(|(k, c)| *k != key && (k.0 == listener || k.1 == listener) && !c.ended && now.saturating_sub(c.last_ms) < QUIET_MS)
    }

    /// Whether a listener has settled an exchange with a speaker and its time has not come
    /// (a remark to no one does not reopen it).
    fn settled_with(&self, listener: u32, speaker: u32, now: u64) -> bool {
        self.pairs.get(&pair(listener, speaker)).and_then(|c| c.settled.as_ref()).is_some_and(|s| now < s.until_ms)
    }

    /// Whether a listener may be drawn in by a remark not addressed to them now.
    fn overhear_free(&self, listener: u32, now: u64) -> bool {
        self.overheard.get(&listener).map_or(true, |at| now.saturating_sub(*at) > OVERHEARD_GAP_MS)
    }

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
            .filter(|x| x.at_ms > since && !matches!(x.kind.as_str(), "speech" | "whisper" | "silence" | "repeat"))
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
        let greet = self.talk_cfg.greet;
        // With `LIVING_GREET`, who heard a line said to no one in particular and how they stood
        // (the authority's `audience` row, where the world keeps it).
        let audience = if to == 0 && self.talk_cfg.audience() { self.audience_of(speaker, e.at_ms) } else { None };
        let familiarity = if greet == Greet::Off { Familiarity::Known } else { self.familiarity(listener, speaker) };
        let faced_me = greet == Greet::Facing && audience.as_deref().and_then(faced) == Some(listener);
        // Addressed by name, by `to`, or as the only person close by (the authority marks these);
        // with `LIVING_GREET=facing`, also as the hearer the speaker faces.
        let addressed = Facts { to_me: to == listener, to_none: to == 0, marked: e.salience >= 0.8, faced: faced_me, ..Default::default() }.addressed();
        let asks = text.contains('?');
        let temper = self.temper(listener);
        let stamina = temper.stamina(self.affinity(listener, speaker));
        // (With `LIVING_GREET`, hostility is not caring: `Facts::drawn`.)
        let cares = || self.cares(listener, speaker);
        // `LIVING_GREET=nearest`: the hearers free to take the turn, nearest first (decided under
        // the lock below, from what each finds of the speaker).
        let candidates: Vec<(u32, f32)> = match (&audience, greet) {
            (Some(hs), Greet::Nearest) if !addressed && familiarity.unfamiliar() => {
                let mut v: Vec<(u32, f32)> = hs
                    .iter()
                    .filter(|h| h.d <= GREET_NEAR_M && self.thinks_for(h.id) && self.familiarity(h.id, speaker).unfamiliar())
                    .map(|h| (h.id, h.d))
                    .collect();
                v.sort_by(|a, b| a.1.total_cmp(&b.1));
                v
            }
            _ => Vec::new(),
        };
        let near_me = audience.as_deref().and_then(|hs| hs.iter().find(|h| h.id == listener)).map_or(false, |h| h.d <= GREET_NEAR_M);
        let key = pair(listener, speaker);
        let settled_at = self.talk.lock().unwrap().pairs.get(&key).and_then(|c| c.settled.as_ref().map(|s| s.at_ms));
        let names: Vec<String> = [listener, speaker].iter().flat_map(|id| memory::cue_words(&self.name(*id))).collect();
        let happened = settled_at.map(|at| self.happened_since(listener, speaker, at)).unwrap_or_default();
        // Level of detail (lod.rs): off stage, at most one turn per `LIVING_LOD_TALK_S`.
        let lod_hold = self.lod.on && !self.onstage(listener, None) && self.actors.lock().unwrap().get(&listener).and_then(|m| m.last_talk).is_some_and(|t| t.elapsed() < self.lod.talk);
        let go = {
            let mut t = self.talk.lock().unwrap();
            t.prune(now);
            let active = t.pairs.get(&key).map_or(false, |c| !c.ended && now.saturating_sub(c.last_ms) < QUIET_MS);
            let in_other = t.in_other(listener, key, now);
            let free = to == 0 && !in_other && t.overhear_free(listener, now) && !t.claimed.contains_key(&(speaker, e.at_ms));
            let facts = Facts {
                to_me: to == listener,
                to_none: to == 0,
                marked: e.salience >= 0.8,
                faced: faced_me,
                free,
                // Read only when it can matter (a relation scan), as before.
                cares: free && cares(),
                draw: draw(listener, e.at_ms),
                answers: temper.answers_remarks(),
                curious: temper.curious_of_strangers(),
                familiarity,
                near: near_me,
                // The first hearer, nearest first, who would take the turn: free to talk and not
                // settled with the speaker.
                nearest_is_me: greet == Greet::Nearest
                    && candidates
                        .iter()
                        .find(|(h, _)| (*h == listener || (t.overhear_free(*h, now) && !t.in_other(*h, pair(*h, speaker), now))) && !t.settled_with(*h, speaker, now))
                        .map(|(h, _)| *h)
                        == Some(listener),
                settled: t.settled_with(listener, speaker, now),
            };
            let drawn = facts.drawn(greet);
            if drawn.greeted {
                log::info!("{} is drawn in by {}'s remark ({greet:?})", me.name, self.name(speaker));
            } else if faced_me && e.salience < 0.8 {
                log::info!("{} is faced by {} and takes the remark as addressed", me.name, self.name(speaker));
            }
            let overheard_ok = drawn.overheard;
            let greeted = drawn.no_remark_draw;
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
            if !asks && !greeted && draw(listener, e.at_ms ^ 0x5EED) >= temper.answers_remarks() {
                log::debug!("{} lets {}'s remark pass", me.name, self.name(speaker));
                return;
            }
            if lod_hold {
                log::debug!("{} is off stage and talked recently: no turn", me.name);
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
        self.spawn_turns(listener, speaker);
    }

    /// Run reply turns for a listener who claimed one (`busy`), then for whoever spoke to them
    /// meanwhile.
    fn spawn_turns(self: Arc<Self>, listener: u32, speaker: u32) {
        if self.lod.on {
            self.actors.lock().unwrap().entry(listener).or_default().last_talk = Some(std::time::Instant::now());
        }
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

    /// Who heard a line and how they stood (`audience`, kept by the authority where the world's
    /// `speech_audience` law is on). `None` (and the line is treated as without the modes that
    /// need it) when the world does not keep it.
    fn audience_of(&self, speaker: u32, at_ms: u64) -> Option<Vec<Hearer>> {
        let found = self.conn.db.audience().iter().find(|a| a.speaker == speaker && a.at_ms == at_ms).map(|a| a.hearers);
        if found.is_none() {
            let mut t = self.talk.lock().unwrap();
            if !t.no_audience_logged {
                t.no_audience_logged = true;
                log::warn!("LIVING_GREET={:?} needs who heard each line, and this world does not keep it (set the `speech_audience` law in the seed's rules)", self.talk_cfg.greet);
            }
        }
        found
    }

    /// A person this service takes conversation turns for.
    fn thinks_for(&self, id: u32) -> bool {
        self.allowed(id) && self.conn.db.character().id().find(&id).is_some_and(|c| c.kind == "person" && c.alive && c.ai && c.stage != 0 && c.controller == self.me)
    }

    /// How a listener stands toward a speaker (`LIVING_GREET`): hostile when they feel strongly
    /// against them; known through family, one community or a warm, trusting or close bond; a
    /// stranger while the speaker's name is unknown to them; otherwise barely known.
    fn familiarity(&self, listener: u32, speaker: u32) -> Familiarity {
        let r = self.conn.db.relation().iter().find(|r| r.actor == listener && r.other == speaker);
        if r.as_ref().is_some_and(|r| r.affinity <= -40.0) {
            return Familiarity::Hostile;
        }
        let close = r.as_ref().is_some_and(|r| CLOSE.iter().any(|w| r.label.to_lowercase().contains(w)) || r.affinity >= 40.0 || r.trust >= 60.0);
        let (Some(a), Some(b)) = (self.conn.db.character().id().find(&listener), self.conn.db.character().id().find(&speaker)) else { return Familiarity::Stranger };
        let family = a.parent_a == b.id || a.parent_b == b.id || b.parent_a == a.id || b.parent_b == a.id;
        let community = |id: u32| self.conn.db.membership().iter().find(|m| m.member == id).map(|m| m.community);
        if close || family || community(listener).is_some_and(|k| community(speaker) == Some(k)) {
            Familiarity::Known
        } else if self.known_as(listener, speaker) == b.name {
            Familiarity::Barely
        } else {
            Familiarity::Stranger
        }
    }

    /// Whether a listener cares enough about a speaker to answer a remark not meant for them:
    /// family and close bonds, and strong feelings either way.
    fn cares(&self, listener: u32, speaker: u32) -> bool {
        self.conn.db.relation().iter().find(|r| r.actor == listener && r.other == speaker).map_or(false, |r| {
            let label = r.label.to_lowercase();
            CLOSE.iter().any(|w| label.contains(w)) || r.affinity.abs() >= 40.0 || r.trust >= 60.0
        })
    }

    /// Full deliberations take priority over conversation turns while one is running (its
    /// prompt is being built or the model is answering). A request that is only pending
    /// (queued, held by the rethink gate or off stage) is not thinking: the line gets its turn
    /// now, and the deliberation, when it comes, sees the line and the answer among recent
    /// experiences.
    fn thinking(&self, actor: u32) -> bool {
        self.actors.lock().unwrap().get(&actor).map_or(false, |m| m.running)
    }

    /// Whom a deliberation's words are for: `to`, or for unaddressed words a waiting speaker
    /// they name, or the only one waiting (the authority hears such words as addressed to the
    /// only person close by). `waiting` are the speakers whose lines wait on it.
    fn say_targets(&self, say: &str, to: u32, waiting: Vec<u32>) -> Vec<u32> {
        if say.trim().is_empty() {
            return Vec::new();
        }
        if to != 0 {
            return vec![to];
        }
        let words = memory::cue_words(say);
        let named: Vec<u32> = waiting.iter().copied().filter(|s| memory::cue_words(&self.name(*s)).iter().any(|w| words.contains(w))).collect();
        if named.is_empty() && waiting.len() == 1 { waiting } else { named }
    }

    /// A deliberation is about to speak (to `to`, or to nobody in particular).
    pub(super) fn deliberation_says(&self, actor: u32, say: &str, to: u32) {
        if say.trim().is_empty() {
            return;
        }
        let now = llm::now_ms();
        let waiting: Vec<u32> = self.talk.lock().unwrap().parked.get(&actor).map(|v| v.iter().map(|(s, _)| *s).collect()).unwrap_or_default();
        let named = self.say_targets(say, to, waiting);
        let mut t = self.talk.lock().unwrap();
        for o in named {
            t.deliberated_to.insert((actor, o), now);
        }
        t.deliberated_to.retain(|_, at| now.saturating_sub(*at) < QUIET_MS * 2);
    }

    /// `LIVING_PARK=concurrent`: a deliberation's prompt has just read the experiences.
    pub(super) fn deliberation_prompt(&self, actor: u32) {
        if self.talk_cfg.park != Park::Concurrent {
            return;
        }
        self.talk.lock().unwrap().deliberating.insert(actor, Deliberating { prompt_ms: Some(llm::now_ms()), ..Default::default() });
    }

    /// `LIVING_PARK=concurrent`: a deliberation has decided (its think step answered). Lines
    /// waiting on it whose speaker its words are not for get their turn now.
    pub(super) fn deliberation_decided(self: &Arc<Self>, actor: u32, decision: &Value) {
        if self.talk_cfg.park != Park::Concurrent {
            return;
        }
        let (say, to) = match &decision["say"] {
            Value::String(s) => (s.clone(), 0),
            Value::Object(o) => (o.get("text").and_then(|t| t.as_str()).unwrap_or_default().to_string(), o.get("to").and_then(living_rules::normalize::reply_id).unwrap_or(0) as u32),
            _ => (String::new(), 0),
        };
        let say = if living_rules::normalize::placeholder_words(&say) { String::new() } else { say };
        let waiting: Vec<u32> = self.talk.lock().unwrap().parked.get(&actor).map(|v| v.iter().map(|(s, _)| *s).collect()).unwrap_or_default();
        let targets = self.say_targets(&say, to, waiting);
        let now = llm::now_ms();
        let due: Vec<u32> = {
            let mut t = self.talk.lock().unwrap();
            t.deliberating.entry(actor).or_default().decided = Some(targets.clone());
            let lines = t.parked.remove(&actor).unwrap_or_default();
            let (keep, go): (Vec<(u32, u64)>, Vec<(u32, u64)>) = lines.into_iter().partition(|(s, _)| targets.contains(s));
            if !keep.is_empty() {
                t.parked.insert(actor, keep);
            }
            let mut due = Vec::new();
            for (speaker, at) in go {
                if !due.contains(&speaker) && now.saturating_sub(at) <= QUIET_MS {
                    due.push(speaker);
                }
            }
            due
        };
        for speaker in due {
            log::info!("{}'s deliberation has decided, and not to speak to {}: the line gets its turn now", self.name(actor), self.name(speaker));
            self.clone().claim_turn(actor, speaker);
        }
    }

    /// Start a reply turn for a listener, or leave the speaker waiting for the one in flight.
    fn claim_turn(self: Arc<Self>, listener: u32, speaker: u32) {
        let go = {
            let mut t = self.talk.lock().unwrap();
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
        if go {
            self.spawn_turns(listener, speaker);
        }
    }

    fn park_concurrent(&self) -> bool {
        self.talk_cfg.park == Park::Concurrent
    }

    /// `LIVING_PARK=concurrent`: whether a line heard at `heard_ms` from `other` gets its turn
    /// while `me`'s deliberation runs. Not while the prompt is still to be built (it will see
    /// the line); once the deliberation has decided, unless its words are for `other`; before
    /// that, when the line came just after the prompt was built (within `FRESH_MS`).
    fn turn_alongside(&self, me: u32, other: u32, heard_ms: u64) -> bool {
        self.talk_cfg.park == Park::Concurrent && self.talk.lock().unwrap().deliberating.get(&me).is_some_and(|d| d.alongside(other, heard_ms))
    }

    /// `LIVING_PARK=concurrent`: a deliberation's words for someone its character already
    /// answered in a turn taken alongside it are not said (the plan and acts stand).
    pub(super) fn unanswered_say(&self, actor: u32, say: String, to: u32) -> String {
        if self.talk_cfg.park != Park::Concurrent || say.trim().is_empty() {
            return say;
        }
        let t = self.talk.lock().unwrap();
        let Some(d) = t.deliberating.get(&actor) else { return say };
        let answered = d.answered_since_prompt();
        drop(t);
        let targets = self.say_targets(&say, to, answered.clone());
        if let Some(o) = targets.iter().find(|o| answered.contains(o)) {
            log::info!("{} already answered {} in conversation while deliberating: the deliberation's words “{say}” are not said", self.name(actor), self.name(*o));
            return String::new();
        }
        say
    }

    /// `LIVING_PARK=concurrent`: what a character said in turns taken alongside its running
    /// deliberation, for the deliberation's compile step.
    pub(super) fn said_alongside(&self, actor: u32) -> Option<String> {
        if self.talk_cfg.park != Park::Concurrent {
            return None;
        }
        let t = self.talk.lock().unwrap();
        let d = t.deliberating.get(&actor)?;
        if d.answered.is_empty() {
            return None;
        }
        let lines: Vec<String> = d.answered.iter().map(|(o, _, w)| format!("to {}: “{w}”", self.known_as(actor, *o))).collect();
        Some(format!("While you were thinking this over, you also answered in conversation: {}.", lines.join("; ")))
    }

    /// A deliberation ended: lines that came while it ran get their turn, unless it spoke to
    /// that person after hearing them.
    pub(super) fn deliberation_ended(self: Arc<Self>, actor: u32) {
        let now = llm::now_ms();
        let due: Vec<u32> = {
            let mut t = self.talk.lock().unwrap();
            t.deliberating.remove(&actor);
            let lines = t.parked.remove(&actor).unwrap_or_default();
            let mut due = Vec::new();
            for (speaker, at) in lines {
                if due.contains(&speaker) {
                    continue;
                }
                if t.deliberated_to.get(&(actor, speaker)).is_some_and(|said| *said >= at) {
                    log::info!("{} answered {} in its deliberation", self.name(actor), self.name(speaker));
                    continue;
                }
                if now.saturating_sub(at) > QUIET_MS {
                    continue;
                }
                due.push(speaker);
            }
            due
        };
        for speaker in due {
            let go = {
                let mut t = self.talk.lock().unwrap();
                match t.busy.get_mut(&actor) {
                    Some(waiting) => {
                        *waiting = Some(speaker);
                        false
                    }
                    None => {
                        t.busy.insert(actor, None);
                        true
                    }
                }
            };
            log::info!("{}'s deliberation ended: the line from {} gets its turn", self.name(actor), self.name(speaker));
            if go {
                self.clone().spawn_turns(actor, speaker);
            }
        }
    }

    async fn reply_turn(&self, me: u32, other: u32) -> Result<()> {
        let thinking = self.thinking(me);
        let alongside = thinking && self.park_concurrent() && {
            let heard = self.talk.lock().unwrap().pairs.get(&pair(me, other)).and_then(|c| c.lines.iter().rev().find(|l| l.speaker == other).map(|l| l.at_ms)).unwrap_or_else(llm::now_ms);
            self.turn_alongside(me, other, heard)
        };
        if alongside {
            log::info!("{} is deliberating; the line from {} gets its turn alongside", self.name(me), self.name(other));
        } else if thinking {
            // Its prompt may already be built: the line waits for the deliberation to end.
            log::info!("{} is deliberating; the line from {} waits for it to end", self.name(me), self.name(other));
            let heard = self.talk.lock().unwrap().pairs.get(&pair(me, other)).and_then(|c| c.lines.iter().rev().find(|l| l.speaker == other).map(|l| l.at_ms)).unwrap_or_else(llm::now_ms);
            let mut t = self.talk.lock().unwrap();
            let v = t.parked.entry(me).or_default();
            match v.iter_mut().find(|(s, _)| *s == other) {
                Some(x) => x.1 = x.1.max(heard),
                None => v.push((other, heard)),
            }
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
        let lane = if self.is_player(me) || self.is_player(other) || lines.iter().any(|l| self.is_player(l.speaker) || self.is_player(l.to)) {
            Lane::Interactive
        } else {
            Lane::Routine
        };
        let last_word = own + 1 >= stamina;
        let ctx = TalkCtx { temper: &temper, lately_said, own, last_word, reopened: reopened.as_ref() };
        let (system, user) = self.talk_prompt(&c, other, &lines, &heard, &ctx).await;
        let mut profile = self.profile(&c);
        let messages = [Msg { role: "system", content: system }, Msg { role: "user", content: user }];
        let (reply, v) = {
            let mut attempt = 0;
            loop {
                let reply = self.llm.chat_in_lane(&profile, self.attention(me, None), "talk", &c.name, &messages, lane).await?;
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
        let say = if say.eq_ignore_ascii_case("null") || living_rules::normalize::placeholder_words(&say) { String::new() } else { say };
        // The way it is said (`"way": "whisper"`, or inside `say`); one the world does not have
        // is said aloud. A whisper is answered in a whisper unless the reply says otherwise.
        let way = way_of(&v).unwrap_or_else(|| if self.how_heard(&heard) == "whisper" && prompts::ways().iter().any(|w| w == "whisper") { "whisper".into() } else { "say".into() });
        let to = if to != 0 && to != me && self.conn.db.character().id().find(&to).map_or(false, |c| c.kind == "person") { to } else { other };
        // What the speaker says is now settled closes the exchange (their own judgment).
        let outcome = flat(if v["settled"].is_null() || v["settled"] == json!(false) { &v["outcome"] } else { &v["settled"] }).trim().to_string();
        let outcome: String = if ["null", "none", "nothing", "-", "n/a", "false", "no", "open"].contains(&outcome.to_lowercase().as_str()) { String::new() } else { outcome.chars().take(160).collect() };
        let end = v["end"].as_bool().unwrap_or(false) || say.is_empty() || !outcome.is_empty();
        // "Nothing more to say" closes without anything to remember.
        let outcome = if outcome.to_lowercase().starts_with("nothing") { String::new() } else { outcome };
        let thought = flat(&v["thought"]);
        // Deliberate acts decided in this turn (e.g. both choosing to start a family).
        let acts = acts_of(&v);
        let other_name = self.known_as(c.id, other);
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
            "{thought} → {}{}{}",
            if say.is_empty() { format!("says nothing to {other_name}") } else { format!("says to {}: “{say}”", self.name(to)) },
            if acts.is_empty() { String::new() } else { format!(" and acts: {}", acts_text(&acts)) },
            match &settled {
                Some(s) if !s.outcome.is_empty() => format!(" (settled: {} — until {})", s.outcome, fmt(s.until_ms)),
                Some(_) if !say.is_empty() => " (and ends the conversation)".to_string(),
                _ => String::new(),
            }
        );
        let mut t = ThoughtIn {
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
        // `LIVING_PARK=concurrent`: a turn taken alongside a deliberation that has meanwhile
        // spoken to them says nothing and acts on nothing (that deliberation was the answer).
        let (say, acts) = if alongside && self.talk.lock().unwrap().deliberated_to.get(&(me, other)).is_some_and(|at| *at >= heard.at_ms) {
            log::info!("{}'s deliberation spoke to {} first: the turn taken alongside says nothing", c.name, other_name);
            t.summary = format!("{} (not said: the deliberation answered first)", t.summary);
            (String::new(), Vec::new())
        } else {
            (say, acts)
        };
        // Record the turn before speaking: the listener's experience of this line can arrive
        // before the reducer's reply, and must be recognized as part of this exchange.
        let text: String = say.chars().take(400).collect();
        let now = llm::now_ms();
        {
            let mut tk = self.talk.lock().unwrap();
            if !say.is_empty() {
                tk.spoke.insert(me, now);
                tk.said.entry(me).or_default().push(now);
                if alongside {
                    if let Some(d) = tk.deliberating.get_mut(&me) {
                        d.answered.push((to, now, text.clone()));
                    }
                }
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
                        memory::EdgeOp { from: "self".into(), rel: "AGREED".into(), to: key.clone(), confidence: 0.9, because: because.clone(), props: edge_props, firsthand: false, sources: Vec::new() },
                        memory::EdgeOp { from: key, rel: "WITH".into(), to: format!("person:{other}"), confidence: 0.9, because, props: Default::default(), firsthand: false, sources: Vec::new() },
                    ],
                    ..Default::default()
                };
                if let Err(e) = store.apply(me, &patch, &t.reference, now).await {
                    log::warn!("{}: agreement not remembered: {e:#}", c.name);
                }
            }
        }
        let mut result = self.say(me, say.clone(), to, way.clone(), t.clone()).await;
        if matches!(&result, Err(e) if e.to_string().contains("too fast")) {
            tokio::time::sleep(Duration::from_millis(SPEECH_GAP_MS)).await;
            result = self.say(me, say.clone(), to, way.clone(), t).await;
        }
        if result.is_err() && !say.is_empty() {
            let mut tk = self.talk.lock().unwrap();
            if let Some(c) = tk.pairs.get_mut(&pair(me, to)) {
                c.lines.retain(|l| !(l.turn && l.speaker == me && l.at_ms == now));
            }
        }
        if let Err(e) = self.act(me, acts, "talk").await {
            log::warn!("{}: acts from a conversation not taken: {e:#}", c.name);
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

    async fn say(&self, actor: u32, say: String, to: u32, way: String, t: ThoughtIn) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_say_then(actor, say, to, way, 0, t, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_say: {e}"))
    }

    /// How the line being answered was said: its way (`whisper`, `call`, `say`), from the
    /// listener's row and the speaker's `heard` row. (How far away the speaker stood is in the
    /// row's own words when the way says it, "calls out to you from about 25 m": this service
    /// does not follow bodies.)
    fn how_heard(&self, heard: &Line) -> String {
        self.how_heard_told(heard).0
    }

    /// The way it was said, and how the listener's own row tells it, without the words ("Bram
    /// calls out to you from about 25 m").
    fn how_heard_told(&self, heard: &Line) -> (String, String) {
        let e = self.conn.db.experience().id().find(&heard.exp);
        let told = e.as_ref().map(|e| e.text.split_once(": “").map_or(e.text.as_str(), |(head, _)| head).to_string()).unwrap_or_default();
        let way = match &e {
            Some(e) if e.kind == "whisper" => "whisper".to_string(),
            Some(e) => self.conn.db.line_heard().iter().find(|h| h.speaker == heard.speaker && h.at_ms == e.at_ms).map(|h| h.way).unwrap_or_else(|| "say".into()),
            None => "say".into(),
        };
        (way, told)
    }

    /// Who they are and how they talk, how they feel about the other, what the moment brings
    /// to mind, what happened between them lately and what they settled before, where they
    /// are, the conversation so far and the line they are answering.
    async fn talk_prompt(&self, c: &Character, other: u32, lines: &[Line], heard: &Line, ctx: &TalkCtx<'_>) -> (String, String) {
        let me = c.id;
        // As this character knows them: the name only where the authority gave it.
        let other_name = self.known_as(me, other);
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
            let all: Vec<Experience> = self.experiences(me).into_iter().filter(|e| (e.subject == other || e.object == other) && !matches!(e.kind.as_str(), "speech" | "whisper" | "repeat")).collect();
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
        let body = self.body_text(c.id);
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
        let recalled = self.recall_for(me, &cues.bounded(), 8, 3, "talk").await;
        let mut mind = recalled.mind;
        mind.extend(recalled.cued_stances.into_iter().take(3).map(|s| format!("you hold: {s}")));
        let convo: Vec<String> = lines
            .iter()
            .rev()
            .take(12)
            .rev()
            .map(|l| {
                let who = if l.speaker == me { "You".to_string() } else { self.known_as(me, l.speaker) };
                let to = if l.to != 0 && l.to != me && l.to != other { format!(" (to {})", self.known_as(me, l.to)) } else { String::new() };
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
        // What stands between them now: proposals either way (answerable with an act).
        let mut between = Vec::new();
        for o in self.conn.db.bond_offer().iter().filter(|o| now.saturating_sub(o.at_ms) <= 120_000) {
            if o.from == other && o.to == me {
                between.push(format!("{other_name} has asked to start a family with you ({}s ago); it happens if you also choose it (the act conceive toward them) within two minutes of their asking.", now.saturating_sub(o.at_ms) / 1000));
            } else if o.from == me && o.to == other {
                between.push(format!("You asked {other_name} to start a family ({}s ago); they have not chosen it yet.", now.saturating_sub(o.at_ms) / 1000));
            }
        }
        for o in self.conn.db.trade_offer().iter().filter(|o| now.saturating_sub(o.at_ms) <= 180_000) {
            if o.from == other && o.to == me {
                between.push(format!("{other_name} offers you {} {} for {} {} (offer {}: accept to exchange, or decline).", o.give_qty, o.give_item, o.want_qty, o.want_item, o.id));
            } else if o.from == me && o.to == other {
                between.push(format!("You offered {other_name} {} {} for {} {}; they have not accepted yet.", o.give_qty, o.give_item, o.want_qty, o.want_item));
            }
        }
        // Agreements and demands between the two, as the world keeps them.
        between.extend(self.dealings_with(me, other));
        // How it was said: a whisper is between the two; a call came from beyond a voice.
        let voice = prompts::voice_m();
        let (way, told) = self.how_heard_told(heard);
        let how = match way.as_str() {
            "whisper" => "They whispered this to you; only you heard the words. To keep it between you, whisper back (\"way\": \"whisper\"); a whisper reaches only someone beside you.".to_string(),
            "call" => format!("{}. An ordinary voice carries {voice:.0} m: if they are farther than that, call back (\"way\": \"call\") or go over to them.", if told.is_empty() { "They called this out".to_string() } else { told }),
            _ => String::new(),
        };
        let t = prompts::TalkUser {
            name: &c.name,
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
            body: &body,
            conversation: &convo,
            heard: &heard.text,
            how: &how,
            between: &between,
        };
        (prompts::talk_system(), prompts::talk_user(&t))
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
    living_rules::normalize::reply_id(v).unwrap_or(0) as u32
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
    fn the_defaults_are_nearest_and_concurrent() {
        for (g, p) in [(None, None), (Some(""), Some("")), (Some(" Nearest "), Some("CONCURRENT"))] {
            let c = Config::parse(g, p).unwrap();
            assert_eq!((c.greet, c.park), (Greet::Nearest, Park::Concurrent));
            assert!(c.audience());
        }
    }

    #[test]
    fn the_old_rules_stay_selectable_and_typos_are_refused() {
        for (g, p) in [(Some("off"), Some("wait")), (Some(" OFF "), Some("Wait")), (Some("0"), Some("wait"))] {
            let c = Config::parse(g, p).unwrap();
            assert_eq!((c.greet, c.park), (Greet::Off, Park::Wait));
            assert!(!c.audience());
        }
        assert_eq!(Config::parse(Some("nearest"), Some("concurrent")).unwrap().park, Park::Concurrent);
        assert!(Config::parse(Some("curious"), None).unwrap().audience());
        assert!(Config::parse(Some("facing"), None).unwrap().audience());
        assert!(Config::parse(Some("nearst"), None).is_err());
        assert!(Config::parse(None, Some("concurent")).is_err());
    }

    /// Every combination of what a heard line can be, as `Facts`.
    fn every_line() -> Vec<Facts> {
        let mut out = Vec::new();
        let fams = [Familiarity::Known, Familiarity::Hostile, Familiarity::Stranger, Familiarity::Barely];
        for bits in 0u32..1 << 9 {
            let b = |i: u32| bits & (1 << i) != 0;
            for familiarity in fams {
                for draw in [0.0, 0.29, 0.5, 0.71, 0.99] {
                    out.push(Facts {
                        to_me: b(0),
                        to_none: b(1),
                        marked: b(2),
                        faced: false,
                        free: b(3),
                        cares: b(4),
                        draw,
                        answers: if b(5) { 0.3 } else { 0.7 },
                        curious: 0.6,
                        familiarity,
                        near: b(6),
                        nearest_is_me: b(7),
                        settled: b(8),
                    });
                }
            }
        }
        out
    }

    #[test]
    fn greet_off_is_the_old_rule() {
        // `LIVING_GREET=off`, selected explicitly (the default is `nearest`).
        // Before LIVING_GREET: addressed by `to` or by the authority's mark; drawn into a remark
        // only when free, caring (hostility included) and the remark draw passes; the remark
        // draw always applies. Whatever else is known of a line changes nothing.
        for f in every_line() {
            assert_eq!(f.addressed(), f.to_me || (f.to_none && f.marked), "{f:?}");
            let d = f.drawn(Greet::Off);
            assert_eq!(d, Drawn { overheard: f.free && f.cares && f.draw < f.answers, greeted: false, no_remark_draw: false }, "{f:?}");
        }
    }

    #[test]
    fn greet_modes_draw_in_one_stranger_and_not_the_hostile() {
        for f in every_line() {
            for greet in [Greet::Nearest, Greet::Curious, Greet::Facing] {
                let d = f.drawn(greet);
                // Hostility never draws one into a remark, and an addressed line from someone
                // one hates keeps the remark draw.
                if f.familiarity == Familiarity::Hostile {
                    assert!(!d.overheard && !d.greeted && !d.no_remark_draw, "{greet:?} {f:?}");
                }
                // Only strangers and the barely known are greeted, and only remarks to no one
                // that the listener is free to take, not settled with the speaker.
                if d.greeted {
                    assert!(f.familiarity.unfamiliar() && f.free && !f.addressed() && !f.settled, "{greet:?} {f:?}");
                }
                // Known people are drawn in exactly as before.
                if f.familiarity == Familiarity::Known {
                    assert_eq!(d, f.drawn(Greet::Off), "{greet:?} {f:?}");
                }
            }
        }
        let stranger = Facts { to_none: true, free: true, familiarity: Familiarity::Stranger, draw: 0.5, answers: 0.6, curious: 0.4, ..Default::default() };
        assert!(Facts { nearest_is_me: true, ..stranger }.drawn(Greet::Nearest).greeted);
        assert!(!stranger.drawn(Greet::Nearest).greeted);
        // Curious: close by and the curiosity draw passes.
        assert!(!Facts { near: true, ..stranger }.drawn(Greet::Curious).greeted);
        assert!(Facts { near: true, draw: 0.3, ..stranger }.drawn(Greet::Curious).greeted);
        assert!(!Facts { near: false, draw: 0.3, ..stranger }.drawn(Greet::Curious).greeted);
        // A stranger's addressed line is answered without the remark draw.
        assert!(Facts { to_me: true, ..stranger }.drawn(Greet::Facing).no_remark_draw);
        assert!(!Facts { to_me: true, ..stranger }.drawn(Greet::Off).no_remark_draw);
        // Facing: the faced hearer is addressed, whoever spoke.
        assert!(Facts { faced: true, ..Default::default() }.addressed());
        // Hatred counted as caring before; with the switch it does not.
        let hated = Facts { to_none: true, free: true, cares: true, familiarity: Familiarity::Hostile, draw: 0.1, answers: 0.6, ..Default::default() };
        assert!(hated.drawn(Greet::Off).overheard && !hated.drawn(Greet::Nearest).overheard);
    }

    #[test]
    fn the_faced_hearer_is_the_one_straight_ahead() {
        let h = |id, d, off| Hearer { id, d, off };
        assert_eq!(faced(&[h(1, 2.0, 0.5), h(2, 3.0, 0.1), h(3, 1.0, 2.5)]), Some(2));
        // Too far, or outside the cone: nobody.
        assert_eq!(faced(&[h(1, 7.0, 0.0), h(2, 2.0, 0.9)]), None);
        // A tie in the angle goes to the nearer.
        assert_eq!(faced(&[h(1, 4.0, 0.2), h(2, 2.0, 0.2)]), Some(2));
        assert_eq!(faced(&[]), None);
    }

    #[test]
    fn a_line_gets_its_turn_alongside_only_when_the_deliberation_cannot_answer_it() {
        // The prompt is not built yet: it will see the line.
        assert!(!Deliberating::default().alongside(7, 1_000));
        let d = Deliberating { prompt_ms: Some(10_000), ..Default::default() };
        // Heard before the prompt (it is in it), just after (it is not, and the deliberation
        // has most of its run ahead), and well after (it may be about to decide).
        assert!(!d.alongside(7, 9_500));
        assert!(d.alongside(7, 10_600));
        assert!(d.alongside(7, 12_000));
        assert!(!d.alongside(7, 12_001));
        // Decided: alongside unless its words are for that speaker.
        let d = Deliberating { decided: Some(vec![7]), ..d };
        assert!(!d.alongside(7, 20_000));
        assert!(d.alongside(8, 20_000));
        let d = Deliberating { prompt_ms: Some(10_000), answered: vec![(7, 9_000, "earlier".into()), (8, 11_000, "hello".into())], ..Default::default() };
        assert_eq!(d.answered_since_prompt(), vec![8]);
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

/// The way of speaking a reply names (`"way"` beside or inside `say`): `None` when it names
/// none, `say` when it names one the world's rules do not have.
fn way_of(v: &Value) -> Option<String> {
    let named = v["way"].as_str().or_else(|| v["say"]["way"].as_str())?.trim().to_lowercase().replace([' ', '-'], "_");
    if named.is_empty() {
        return None;
    }
    Some(match crate::prompts::ways() {
        ways if ways.iter().any(|w| *w == named) => named,
        _ => "say".into(),
    })
}
