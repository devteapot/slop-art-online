//! Ways of speaking (docs/COMMUNICATION.md §3): each `<way>_speech()` in the script is a map
//! that says who receives the words, who notices only that something was said, what the way
//! requires, and the words listeners get. The authority's one speech primitive
//! (`perceive::speak`) applies them; it reads these specs once per script revision.
//!
//! Every key is checked when the script compiles, and an unknown one is refused: a way can
//! never claim a property (a privacy, a cost, a channel) that the primitive does not enforce.

use rhai::{Dynamic, Map};

use super::{ActorFacts, SkillCtx, TargetFacts};

/// `a.qty` of a way's check when the speaker never said a line in that way.
pub const NEVER_MS: u32 = 4_000_000_000;

/// The context of a way's `<way>_check(a)`, as every caller builds it: the authority before it
/// speaks a line, and a client before it sends one (the reducer returns the check's words, so
/// the client can show them first). `actor` is the speaker; `addressee` is `None` for the room,
/// and an addressee that is not there (absent or dead) is a creature that is not alive and very
/// far, so a check cannot tell the two apart; `text` is the line; `since_ms` is how long ago the
/// speaker last said a line in this way (`a.qty`, `NEVER_MS` if never).
pub fn check_ctx(way: &str, actor: ActorFacts, addressee: Option<TargetFacts>, text: &str, since_ms: Option<u64>) -> SkillCtx {
    let target = match addressee {
        None => TargetFacts { class: "none".into(), ..Default::default() },
        Some(t) if t.class != "creature" || !t.alive => TargetFacts { class: "creature".into(), id: t.id, kind: if t.kind.is_empty() { "person".into() } else { t.kind }, alive: false, dist: 1.0e9, ..Default::default() },
        Some(t) => t,
    };
    SkillCtx { actor, target, text: text.into(), qty: since_ms.map_or(NEVER_MS, |ms| ms.min(NEVER_MS as u64) as u32), skill: way.into(), ..Default::default() }
}

/// To whom a line may be said.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum To {
    /// The room, or one person.
    Optional,
    /// One person: a line to the room is refused.
    Required,
}

/// How far the words go.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Carry {
    /// A share of each listener's own hearing (the `senses` law): 1.0 is a normal voice.
    Hearing(f32),
    /// A fixed distance in metres (still within the listener's own hearing).
    Within(f32),
}

/// Who notices that a line was said without receiving the words (a whisper's onlookers).
#[derive(Clone, Debug, PartialEq)]
pub struct Noticed {
    /// Within this many metres of the speaker.
    pub within_m: f32,
    /// Only those who see the speaker (the sight rule).
    pub seen: bool,
    /// Their experience rows' kind.
    pub kind: String,
    /// Their words: `{a}` the speaker and `{b}` the addressee, as each noticer refers to them.
    pub text: String,
    pub salience: f32,
}

/// One way of speaking.
#[derive(Clone, Debug, PartialEq)]
pub struct WaySpec {
    pub name: String,
    /// The word a client shows for it ("Say", "Whisper").
    pub label: String,
    /// Where it comes among the ways (a client's chips; the world text).
    pub order: i32,
    /// What it is, for a mind (the world text) and a player (the box).
    pub about: String,
    pub to: To,
    pub carry: Carry,
    /// Only the addressee receives the words.
    pub only_to: bool,
    pub noticed: Option<Noticed>,
    /// The kind of the experience rows that carry the words to a listener.
    pub kind: String,
    /// Words for the speaker's own row and for listeners (the words follow: `: “…”`). `{a}` is
    /// the speaker and `{b}` the addressee as the reader refers to them, `{d}` how far the speaker
    /// is from the reader (whole metres).
    pub said: String,
    pub said_to: String,
    pub heard: String,
    pub heard_to: String,
    pub heard_to_you: String,
    /// What an animal in range hears ("a person's voice"); empty: animals hear nothing.
    pub animals: String,
    /// Seconds between two lines of this way (at least the speaking limit, 2 s).
    pub gap_s: f32,
    /// Longer lines are cut to this many characters.
    pub max_chars: usize,
    /// A technique the speaker must know ("" none).
    pub needs: String,
    /// The addressee must be within this many metres (0: any distance the words carry).
    pub reach: f32,
    /// The addressee must be in the speaker's sight.
    pub needs_sight: bool,
    /// A line with the speaker's own name in it tells it to those who receive the words.
    pub introduces: bool,
    /// A line to someone that holds their name tells it to those who receive the words and see
    /// whom it was for (overheard names).
    pub names: bool,
    /// Salience of the words for the one they are for, and for the others who hear them.
    pub addressed: f32,
    pub overheard: f32,
}

/// The keys a `<way>_speech()` map may have.
pub const WAY_TRAITS: &[&str] = &[
    "about", "label", "order", "to", "words", "noticed", "kind", "said", "said_to", "heard", "heard_to", "heard_to_you", "animals", "gap_s", "max_chars", "needs", "reach", "needs_sight", "introduces",
    "names", "salience",
];

/// The way every line takes when none is named, and the one a script without ways speaks by.
pub const SAY: &str = "say";

impl WaySpec {
    /// Today's speech (before ways were declared): the shipped `say_speech()`.
    pub fn say() -> Self {
        WaySpec {
            name: SAY.into(),
            label: "Say".into(),
            order: 0,
            about: "Speak aloud. Everyone within earshot hears you, also when you speak to one person.".into(),
            to: To::Optional,
            carry: Carry::Hearing(1.0),
            only_to: false,
            noticed: None,
            kind: "speech".into(),
            said: "You said".into(),
            said_to: "You said to {b}".into(),
            heard: "{a} said".into(),
            heard_to: "{a} said to {b}".into(),
            heard_to_you: "{a} said to you".into(),
            animals: "a person's voice".into(),
            gap_s: 2.0,
            max_chars: 400,
            needs: String::new(),
            reach: 0.0,
            needs_sight: false,
            introduces: true,
            names: true,
            addressed: 0.9,
            overheard: 0.45,
        }
    }

    /// How far the words go for a listener whose own hearing is `hearing`.
    pub fn carry_for(&self, hearing: f32) -> f32 {
        match self.carry {
            Carry::Hearing(k) => hearing * k,
            Carry::Within(m) => m.min(hearing),
        }
    }

    /// The farthest the words go, for gathering listeners (`widest` is the farthest anyone hears).
    pub fn widest(&self, widest: f32) -> f32 {
        let words = match self.carry {
            Carry::Hearing(k) => widest * k,
            Carry::Within(m) => m.min(widest),
        };
        let noticed = self.noticed.as_ref().map_or(0.0, |n| n.within_m);
        // Animals hear the voice where a person would hear the words.
        words.max(noticed)
    }

    /// Whether a listener who is not the addressee may receive the words.
    pub fn public(&self) -> bool {
        !self.only_to
    }
}

fn capitalized(s: &str) -> String {
    let mut c = s.chars();
    c.next().map(|f| f.to_uppercase().chain(c).collect()).unwrap_or_default()
}

fn number(d: &Dynamic) -> Option<f64> {
    d.as_float().ok().or_else(|| d.as_int().ok().map(|i| i as f64))
}

/// A way from what `<way>_speech()` returned.
pub fn way_of(name: &str, m: &Map) -> Result<WaySpec, String> {
    let f = format!("{name}_speech");
    if let Some(k) = m.keys().find(|k| !WAY_TRAITS.contains(&k.as_str())) {
        return Err(format!("{f}: unknown trait `{k}` (traits are {})", WAY_TRAITS.join(", ")));
    }
    let base = WaySpec::say();
    let text = |m: &Map, k: &str, d: &str| -> Result<String, String> { m.get(k).map_or(Ok(d.to_string()), |v| v.clone().into_string().map_err(|_| format!("{f}: `{k}` must be a string"))) };
    let flag = |k: &str, d: bool| m.get(k).map_or(Ok(d), |v| v.as_bool().map_err(|_| format!("{f}: `{k}` must be true or false")));
    let num = |m: &Map, k: &str, d: f64, lo: f64, hi: f64| -> Result<f64, String> {
        m.get(k).map_or(Ok(d), |v| number(v).filter(|n| n.is_finite() && *n >= lo && *n <= hi).ok_or_else(|| format!("{f}: `{k}` must be a number from {lo} to {hi}")))
    };
    let about = text(m, "about", "")?;
    if about.trim().is_empty() {
        return Err(format!("{f}: `about` says what the way is, for a mind and a player"));
    }
    let to = match text(m, "to", "optional")?.as_str() {
        "optional" => To::Optional,
        "required" => To::Required,
        other => return Err(format!("{f}: `to` is \"optional\" or \"required\", not {other:?}")),
    };
    // words: #{ hearing: share } or #{ within_m: metres }, and `only_to`.
    let (carry, only_to) = match m.get("words") {
        None => (base.carry, false),
        Some(v) => {
            let w = v.clone().try_cast::<Map>().ok_or_else(|| format!("{f}: `words` is a map (hearing or within_m, only_to)"))?;
            if let Some(k) = w.keys().find(|k| !["hearing", "within_m", "only_to"].contains(&k.as_str())) {
                return Err(format!("{f}: unknown `words` trait `{k}` (they are hearing, within_m, only_to)"));
            }
            let carry = match (w.get("hearing"), w.get("within_m")) {
                (Some(_), Some(_)) => return Err(format!("{f}: `words` has either `hearing` or `within_m`, not both")),
                (_, Some(_)) => Carry::Within(num(&w, "within_m", 0.0, 0.0, 256.0)? as f32),
                _ => Carry::Hearing(num(&w, "hearing", 1.0, 0.0, 8.0)? as f32),
            };
            let only_to = w.get("only_to").map_or(Ok(false), |v| v.as_bool().map_err(|_| format!("{f}: `words.only_to` must be true or false")))?;
            (carry, only_to)
        }
    };
    if only_to && to != To::Required {
        return Err(format!("{f}: words only for the addressee need `to: \"required\"`"));
    }
    let noticed = match m.get("noticed") {
        None => None,
        Some(v) => {
            let n = v.clone().try_cast::<Map>().ok_or_else(|| format!("{f}: `noticed` is a map (within_m, seen, kind, text, salience)"))?;
            if let Some(k) = n.keys().find(|k| !["within_m", "seen", "kind", "text", "salience"].contains(&k.as_str())) {
                return Err(format!("{f}: unknown `noticed` trait `{k}` (they are within_m, seen, kind, text, salience)"));
            }
            let kind = text(&n, "kind", "")?;
            let words = text(&n, "text", "")?;
            if kind.is_empty() || words.is_empty() {
                return Err(format!("{f}: `noticed` names its rows' `kind` and their `text`"));
            }
            if ["speech", "said", base.kind.as_str()].contains(&kind.as_str()) {
                return Err(format!("{f}: `noticed.kind` must not be a kind that carries words ({kind})"));
            }
            Some(Noticed {
                within_m: num(&n, "within_m", 0.0, 0.0, 256.0)? as f32,
                seen: n.get("seen").map_or(Ok(true), |v| v.as_bool().map_err(|_| format!("{f}: `noticed.seen` must be true or false")))?,
                kind,
                text: words,
                salience: num(&n, "salience", 0.3, 0.0, 1.0)? as f32,
            })
        }
    };
    let (addressed, overheard) = match m.get("salience") {
        None => (base.addressed, base.overheard),
        Some(v) => {
            let s = v.clone().try_cast::<Map>().ok_or_else(|| format!("{f}: `salience` is a map (addressed, overheard)"))?;
            (num(&s, "addressed", base.addressed as f64, 0.0, 1.0)? as f32, num(&s, "overheard", base.overheard as f64, 0.0, 1.0)? as f32)
        }
    };
    let gap_s = num(m, "gap_s", base.gap_s as f64, 0.0, 600.0)? as f32;
    let reach = num(m, "reach", 0.0, 0.0, 256.0)? as f32;
    let kind = text(m, "kind", &base.kind)?;
    if kind.trim().is_empty() || ["said", "silence", "repeat", "signal", "introduced"].contains(&kind.as_str()) {
        return Err(format!("{f}: `kind` names the rows that carry the words, not {kind:?}"));
    }
    let label = text(m, "label", &capitalized(name))?;
    Ok(WaySpec {
        name: name.to_string(),
        label,
        order: num(m, "order", 0.0, -1000.0, 1000.0)? as i32,
        about,
        to,
        carry,
        only_to,
        noticed,
        kind,
        said: text(m, "said", &base.said)?,
        said_to: text(m, "said_to", &base.said_to)?,
        heard: text(m, "heard", &base.heard)?,
        heard_to: text(m, "heard_to", &base.heard_to)?,
        heard_to_you: text(m, "heard_to_you", &base.heard_to_you)?,
        // A way for one ear alone reaches no animal unless it says so.
        animals: text(m, "animals", if only_to { "" } else { &base.animals })?,
        gap_s,
        max_chars: num(m, "max_chars", base.max_chars as f64, 1.0, 400.0)? as usize,
        needs: text(m, "needs", "")?,
        reach,
        needs_sight: match flag("needs_sight", false)? {
            // Ways that need sight wait for signing (docs/COMMUNICATION.md item 13).
            true => return Err(format!("{f}: `needs_sight` is not built yet (a way that needs its addressee in sight waits for signing)")),
            false => false,
        },
        introduces: flag("introduces", true)?,
        // Words for one ear alone teach no bystander a name.
        names: flag("names", !only_to)?,
        addressed,
        overheard,
    })
}
