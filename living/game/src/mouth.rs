//! The mouth while a line is spoken: presentation only, nothing is sent and no rule is read
//! beyond what the world's ways of speaking already say.
//!
//! A line I heard (an experience row of a way's `kind`), a line someone was seen to say without
//! the words reaching me (a way's `noticed` kind, a whisper's onlookers), and my own last line
//! each move the speaker's `Fcl_MTH_A` while its bubble shows: open on vowels, nearly shut on
//! spaces, shut on punctuation, over a flap like look-dev's Talk act (about 11 rad/s, up to about
//! 0.8). The line is spoken at [`RATE`] characters a second, so a short line moves the mouth for
//! a moment and a long one for longer, never past the bubble's life; it stops when the line ends.
//!
//! How loud is the way's own: a way whose words reach a share of the hearing (`Carry::Hearing`)
//! opens the mouth by that share (a normal voice 0.8, a call that carries further more); a way
//! that reaches only a few metres or one ear (a whisper) moves it softly. Which way a heard row
//! is comes from its kind and, where ways share a kind, from the way's `heard` words the row
//! begins with; no way is named here.

use crate::phase::Phase;
use bevy::prelude::*;
use living_bindings::*;
use living_rules::script::speech::{Carry, WaySpec, SAY};
use spacetimedb_sdk::Table;
use std::collections::HashMap;

/// Characters a second a line is spoken at.
pub const RATE: f32 = 14.0;
/// A line is spoken for at least this long (s).
const SHORTEST_S: f32 = 0.6;
/// How fast the mouth opens at the first word, and closes after the last (s).
const ATTACK_S: f32 = 0.08;
const RELEASE_S: f32 = 0.15;
/// The flap's rate (rad/s), as look-dev's Talk act.
const FLAP: f32 = 11.0;
/// A normal voice's widest opening, and the softest a voice goes.
pub const VOICE: f32 = 0.8;
pub const HUSHED: f32 = 0.3;
/// Characters assumed for a line seen said but not heard.
const UNHEARD_CHARS: usize = 18;

/// A line being spoken: when it began (authority ms), its words, how long it shows (s), how wide
/// the mouth opens and a phase of its own so two lines never move alike.
#[derive(Clone, Debug, PartialEq)]
pub struct Line {
    pub start_ms: f64,
    pub chars: Vec<char>,
    pub life_s: f32,
    pub amp: f32,
    pub seed: f32,
}

impl Line {
    pub fn new(start_ms: f64, text: &str, life_s: f32, amp: f32) -> Self {
        let chars: Vec<char> = text.chars().collect();
        let seed = text.bytes().fold(2166136261u32, |h, b| (h ^ b as u32).wrapping_mul(16777619)) as f32 / u32::MAX as f32 * std::f32::consts::TAU;
        Line { start_ms, chars, life_s, amp, seed }
    }

    /// How long the words take to say (s): by their length, never past the bubble.
    pub fn talk_s(&self) -> f32 {
        (self.chars.len() as f32 / RATE).max(SHORTEST_S).min(self.life_s)
    }

    /// The mouth's opening at `now_ms`: 0 before the line and once its words are said.
    pub fn weight(&self, now_ms: f64) -> f32 {
        let t = ((now_ms - self.start_ms) / 1000.0) as f32;
        let talk = self.talk_s();
        if !(0.0..talk).contains(&t) || self.chars.is_empty() {
            return 0.0;
        }
        let env = (t / ATTACK_S).min(1.0) * ((talk - t) / RELEASE_S).min(1.0);
        // Where in the words: each character's shape, eased into the next.
        let at = t / talk * self.chars.len() as f32;
        let i = (at.floor() as usize).min(self.chars.len() - 1);
        let next = self.chars.get(i + 1).copied().map_or(0.0, shape);
        let f = at - i as f32;
        let shape = shape(self.chars[i]) * (1.0 - f) + next * f;
        // A little faster or slower per line.
        let rate = FLAP * (0.9 + 0.2 * (self.seed / std::f32::consts::TAU));
        let flap = ((t * rate + self.seed).sin() * 0.5 + 0.5) * ((t * 2.3 + self.seed * 1.7).sin() * 0.3 + 0.7);
        (self.amp * env * flap * shape).clamp(0.0, 1.0)
    }
}

/// How open a character leaves the mouth: vowels wide, other letters less, a space nearly shut,
/// punctuation shut (a pause).
fn shape(c: char) -> f32 {
    if c.is_whitespace() {
        0.3
    } else if c.is_alphanumeric() {
        if "aeiouyAEIOUYàáâäèéêëìíîïòóôöùúûü".contains(c) { 1.0 } else { 0.7 }
    } else if matches!(c, '\'' | '’' | '-') {
        0.6
    } else {
        0.0
    }
}

/// How widely a way of speaking opens the mouth.
pub fn loudness(w: &WaySpec) -> f32 {
    match w.carry {
        Carry::Hearing(k) if !w.only_to => (VOICE * k.max(0.0).powf(0.3)).clamp(HUSHED, 1.0),
        _ => HUSHED,
    }
}

/// A way's voice as a heard row shows it: its row kind, the literal words of its heard templates
/// (between `{a}`, `{b}`, `{d}`), its noticed kind and its loudness.
#[derive(Clone, Debug)]
pub struct Voice {
    kind: String,
    heard: Vec<Vec<String>>,
    noticed: Option<String>,
    pub amp: f32,
}

impl Voice {
    pub fn of(w: &WaySpec) -> Self {
        let pieces = |t: &str| -> Vec<String> { t.split(['{', '}']).enumerate().filter(|(i, s)| i % 2 == 0 && !s.trim().is_empty()).map(|(_, s)| s.to_string()).collect() };
        Voice { kind: w.kind.clone(), heard: [&w.heard, &w.heard_to, &w.heard_to_you].iter().map(|t| pieces(t)).collect(), noticed: w.noticed.as_ref().map(|n| n.kind.clone()), amp: loudness(w) }
    }

    /// How well a row's words before the line fit one of this way's heard templates: the length
    /// of its literal words found in order, None when one is missing.
    fn fits(&self, head: &str) -> Option<usize> {
        self.heard
            .iter()
            .filter_map(|pieces| {
                let mut from = 0;
                for p in pieces {
                    from += head[from..].find(p.as_str())? + p.len();
                }
                Some(pieces.iter().map(|p| p.len()).sum())
            })
            .max()
    }
}

/// What a row of `kind` reading `text` is: the line's words (None: a line seen said, not heard)
/// and how loud it was. None when no way writes rows of that kind.
pub fn heard(voices: &[Voice], kind: &str, text: &str) -> Option<(Option<String>, f32)> {
    let (head, words) = match (text.find('“'), text.rfind('”')) {
        (Some(a), Some(b)) if b > a => (&text[..a], Some(text[a + '“'.len_utf8()..b].to_string())),
        _ => (text, None),
    };
    if let Some(v) = voices.iter().find(|v| v.noticed.as_deref() == Some(kind)) {
        return Some((None, v.amp));
    }
    let ways: Vec<&Voice> = voices.iter().filter(|v| v.kind == kind).collect();
    let words = words?;
    let best = ways.iter().filter_map(|v| v.fits(head).map(|n| (n, v.amp))).max_by_key(|(n, _)| *n).map(|(_, a)| a).or_else(|| ways.first().map(|v| v.amp))?;
    Some((Some(words), best))
}

/// The voices of the world's ways, kept for the revision they were read under; the plain voice
/// of the say way before the rules have come.
#[derive(Default)]
struct Voices {
    revision: Option<u32>,
    all: Vec<Voice>,
}

impl Voices {
    fn update(&mut self, rules: &crate::verbs::Rules) {
        let rev = rules.scripts.as_ref().map(|_| rules.revision);
        if self.revision == rev && !self.all.is_empty() {
            return;
        }
        self.revision = rev;
        self.all = match rules.scripts.as_ref() {
            Some(sc) if !sc.ways().is_empty() => sc.ways().iter().map(Voice::of).collect(),
            _ => vec![Voice::of(&WaySpec::say())],
        };
    }

    /// My own line's voice: the say way's (the box speaks only that way today).
    fn mine(&self, rules: &crate::verbs::Rules) -> f32 {
        rules.scripts.as_ref().and_then(|sc| sc.way(SAY)).map_or(VOICE, loudness)
    }
}

/// Each speaker's line now, and each drawn body's mouth this frame (`lookdev::face` reads it).
#[derive(Resource, Default)]
pub struct Mouths {
    lines: HashMap<u32, (u64, Line)>,
    /// Rows already read (id → authority ms), for the last 10 s.
    read: HashMap<u64, u64>,
    /// The mouth's opening of each drawn body that is speaking (others are shut).
    pub open: HashMap<Entity, f32>,
    /// The same by character id, for the dump and the record.
    pub by_id: HashMap<u32, f32>,
    voices: Voices,
}

pub struct MouthPlugin;

impl Plugin for MouthPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Mouths>().add_systems(Update, lines.in_set(Phase::Present).before(crate::lookdev::animate));
    }
}

/// The lines spoken now, from what I heard and saw said and my own last line, onto the bodies
/// drawn.
fn lines(mut m: ResMut<Mouths>, net: NonSend<crate::net::Net>, scene: NonSend<crate::world::Scene>, rules: NonSend<crate::verbs::Rules>, input: Res<crate::controls::Input>, live: Res<crate::live::Live>) {
    let now = scene.now_ms;
    let m = &mut *m;
    m.voices.update(&rules);
    if let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) {
        for e in conn.db.my_experience().iter().filter(|e| e.observer == me && e.subject != me && now - (e.at_ms as f64) < 10_000.0) {
            if m.read.insert(e.id, e.at_ms).is_some() || m.lines.get(&e.subject).is_some_and(|(_, l)| l.start_ms > e.at_ms as f64) {
                continue;
            }
            let Some((words, amp)) = heard(&m.voices.all, &e.kind, &e.text) else { continue };
            let line = match words {
                Some(w) => Line::new(e.at_ms as f64, &w, crate::ui::model::bubble_life(&w), amp),
                None => Line { chars: vec!['a'; UNHEARD_CHARS], ..Line::new(e.at_ms as f64, &e.text, crate::ui::model::bubble_life(""), amp) },
            };
            m.lines.insert(e.subject, (e.id, line));
        }
        if let Some((t, text)) = input.said.last() {
            if !m.lines.get(&me).is_some_and(|(_, l)| l.start_ms >= *t as f64) {
                let amp = m.voices.mine(&rules);
                m.lines.insert(me, (0, Line::new(*t as f64, text, crate::ui::model::bubble_life(text), amp)));
            }
        }
    } else {
        m.lines.clear();
    }
    m.lines.retain(|_, (_, l)| now - l.start_ms < l.life_s as f64 * 1000.0);
    m.read.retain(|_, at| now - (*at as f64) < 10_000.0);
    m.open.clear();
    m.by_id.clear();
    for (id, e) in live.drawn() {
        if let Some((_, l)) = m.lines.get(&id) {
            let w = l.weight(now);
            m.open.insert(e, w);
            m.by_id.insert(id, w);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn life(text: &str) -> f32 {
        crate::ui::model::bubble_life(text)
    }

    /// The mouth over a line's lifetime: shut before it, moving while its words are said (wide
    /// at times, never past the voice), shut on its pauses and from its last word to the end of
    /// its bubble; a longer line moves longer, never past its bubble.
    #[test]
    fn the_mouth_over_a_line() {
        let text = "Good morning. The bread is fresh today, come and see.";
        let l = Line::new(1000.0, text, life(text), VOICE);
        let talk = l.talk_s();
        assert!((talk - text.chars().count() as f32 / RATE).abs() < 1e-4 && talk < l.life_s, "{talk} of {}", l.life_s);
        let at = |s: f32| l.weight(1000.0 + s as f64 * 1000.0);
        assert_eq!(at(-0.1), 0.0);
        assert_eq!(at(0.0), 0.0, "shut as the line begins");
        let samples: Vec<f32> = (0..400).map(|i| at(talk * i as f32 / 400.0)).collect();
        let most = samples.iter().cloned().fold(0.0, f32::max);
        assert!(most > 0.5 && most <= VOICE + 1e-4, "opens wide, never past the voice: {most}");
        // It moves: many openings and closings, not one held shape.
        let turns = samples.windows(3).filter(|w| (w[1] - w[0]) * (w[2] - w[1]) < 0.0).count();
        assert!(turns >= 6, "{turns} turns");
        // The full stop after "morning" is a pause.
        let stop = text.find('.').unwrap() as f32 + 0.02;
        assert!(at(stop / text.chars().count() as f32 * talk) < 0.05, "a pause at the full stop");
        for s in [talk + 0.01, (talk + l.life_s) / 2.0, l.life_s, l.life_s + 5.0] {
            assert_eq!(at(s), 0.0, "shut at {s} s, after the words");
        }
        // A short line moves for a moment; a very long one fills its bubble and no more.
        let hi = Line::new(0.0, "Hi", life("Hi"), VOICE);
        assert!((hi.talk_s() - SHORTEST_S).abs() < 1e-4);
        let long = "a".repeat(400);
        let l2 = Line::new(0.0, &long, life(&long), VOICE);
        assert_eq!(l2.talk_s(), l2.life_s);
        assert_eq!(l2.weight(l2.life_s as f64 * 1000.0), 0.0);
        // Two lines do not move alike.
        let other = Line::new(1000.0, "Good morning. The bread is fresh today, come and look.", life(text), VOICE);
        let differ = (1..40).filter(|i| (at(*i as f32 * 0.05) - other.weight(1000.0 + *i as f64 * 50.0)).abs() > 0.05).count();
        assert!(differ > 10, "{differ} of 39 samples differ");
    }

    /// The shipped ways: a whisper softly, a call wider than speech; a heard row finds its way by
    /// its kind and its words, a whisper's onlookers by the noticed kind.
    #[test]
    fn loudness_comes_from_the_ways() {
        let sc = living_rules::script::Scripts::new(include_str!("../../scripts/skills.rhai")).unwrap();
        let voices: Vec<Voice> = sc.ways().iter().map(Voice::of).collect();
        assert!(voices.len() >= 3, "say, whisper and call");
        let say = loudness(sc.way(SAY).unwrap());
        assert!((say - VOICE).abs() < 1e-4);
        let row = |w: &WaySpec, to_you: bool| {
            let t = if to_you { &w.heard_to_you } else { &w.heard };
            format!("{}: “Over here!”", t.replace("{a}", "Vessa").replace("{b}", "Oren").replace("{d}", "12"))
        };
        for w in sc.ways() {
            for to_you in [false, true] {
                let (words, amp) = heard(&voices, &w.kind, &row(w, to_you)).expect("a way's row");
                assert_eq!(words.as_deref(), Some("Over here!"));
                assert_eq!(amp, loudness(w), "{} ({to_you})", w.label);
            }
            if let Some(n) = &w.noticed {
                assert_eq!(heard(&voices, &n.kind, "Vessa whispers something to Oren."), Some((None, loudness(w))));
            }
        }
        let amps: Vec<f32> = sc.ways().iter().map(loudness).collect();
        assert!(amps.iter().any(|a| *a < say) && amps.iter().any(|a| *a > say), "softer and louder than speech: {amps:?}");
        assert!(amps.iter().all(|a| *a >= HUSHED && *a <= 1.0));
        assert_eq!(heard(&voices, "gift", "Vessa gave you 1 berries."), None);
    }
}
