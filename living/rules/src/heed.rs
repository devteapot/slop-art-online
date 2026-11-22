//! Heed: whom a character keeps track of as individuals (docs/ATTENTION_BUDGET.md, v2; in code
//! "heed", since "attention" already names the gaze band and the cues, and "crowd" the crowd
//! laws). Everyone else in sight is a **throng**: counted, never named.
//!
//! A character heeds at most its **capacity** of the creatures in sight (the world's Rhai law
//! `heed_capacity(a)`, `Scripts::heed_capacity`, clamped by the world's `heed_ceiling`). Who
//! fills those places is the character's **heed policy**: a ranked list of rules in the
//! behaviour graph's condition words, written by its mind, or its species' starting **heed
//! instinct** ([`instinct`], seed content). Two kinds of creature are individuals whatever the
//! policy and outside the capacity ([`Place::Acting`], [`Place::Contact`]): the one the
//! character is acting on (one cannot strike a throng), and one that made contact with it in
//! the last `heed_contact_s` seconds (a blow that landed on it, or that it blocked or dodged:
//! the body delivers that, as it delivers today's "attacked" line). Anticipation (a windup at
//! me, someone closing) is the policy's: the instinct puts it first, a mind may drop it.
//!
//! Everything here is pure: no world access, no clock. The authority and the replay tool
//! (`living-mind heed-replay`) build [`Candidate`]s from what the character perceives (for a
//! player its sweep's seen set, for a mind its `Sensing`) and call the same functions, so the
//! experiments test the code that would run.
//!
//! # API (stable; the authority side builds on it)
//!
//! - [`parse`] / [`parse_value`]: a policy's JSON (`{"heed": [...]}` or the bare list) to a
//!   [`Policy`], validated against what the character knows ([`Known`]). An `Err` is the
//!   refusal's reason, in words a mind can read in its next prompt.
//! - [`instinct`] / [`instinct_json`]: a species' starting policy (`living/seeds/heed.json`).
//! - [`select`]: the full pass: the forced places first, then every candidate ranked by the
//!   policy, the first `capacity` taken, with each rule's own hold ([`Held`]). Returns
//!   [`Pick`]s in rank order; the forced ones do not count against the capacity.
//! - [`rank_of`] and [`admit`]: the event pass for one candidate (a windup, a blow, a line,
//!   someone coming into sight): forced, a free place, a displacement, or nothing.
//! - [`clamp_capacity`]: a capacity law's answer clamped to the ceiling.
//!
//! Rules are read in order. An `if` rule takes the candidates its condition holds for, in its
//! `order`, up to its `take`; a `score` rule sums the weights of the conditions each candidate
//! meets and takes the highest first (nearer first on ties). A rule's `hold_s` keeps what it
//! took for that long even when its condition stops holding, unless a better rule needs the
//! place (hysteresis as the policy's own content). A candidate taken earlier is not taken
//! again. Conditions read only what perception gives: one too far away to make out
//! ([`Candidate::made_out`] false) matches no id and no relation.

use crate::doing::Phase;
use serde_json::{Map, Value};

/// At most this many rules in a policy.
pub const MAX_RULES: usize = 12;
/// At most this many bytes of JSON in a policy.
pub const MAX_BYTES: usize = 4096;
/// At most this many characters in a rule's `why`.
pub const MAX_WHY: usize = 160;
/// A weight in a `score` rule lies within ±this.
pub const MAX_WEIGHT: f32 = 10.0;
/// Conditions nest at most this deep (`all`/`any`/`not`).
pub const MAX_DEPTH: usize = 6;
/// A rule holds what it took for at most this many seconds.
pub const MAX_HOLD_S: f32 = 60.0;
/// The contact window when the world gives none (`heed_contact_s`).
pub const DEFAULT_CONTACT_S: f32 = 4.0;

/// The skill whose knack × practice `a.actor.factor` reads in `heed_capacity(a)` when the
/// script's `heed_knack()` names none.
pub const DEFAULT_KNACK: &str = "watch";

/// A capacity law's answer, clamped to the world's ceiling: `floor(min(max(raw, 0), ceiling))`;
/// 0 for an answer that is not a finite number.
pub fn clamp_capacity(raw: f64, ceiling: f32) -> usize {
    if !raw.is_finite() || !ceiling.is_finite() {
        return 0;
    }
    raw.max(0.0).min(ceiling.max(0.0) as f64).floor() as usize
}

/// The species' starting heed policies (seed content).
pub const INSTINCTS: &str = include_str!("../../seeds/heed.json");

// ---------------------------------------------------------------------------------------------
// The grammar

/// A ranked heed policy.
#[derive(Clone, Debug, PartialEq)]
pub struct Policy {
    pub rules: Vec<Rule>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Rule {
    /// `{"if": cond, "order": ..., "take": ..., "hold_s": ..., "why": ...}`
    If { cond: Cond, order: Order, take: Take, hold_s: f32, why: String },
    /// `{"score": [{"if": cond, "w": 2.0}, ...], "take": ..., "hold_s": ..., "why": ...}`
    Score { weights: Vec<(Cond, f32)>, take: Take, hold_s: f32, why: String },
}

impl Rule {
    pub fn why(&self) -> &str {
        match self {
            Rule::If { why, .. } | Rule::Score { why, .. } => why,
        }
    }
    pub fn take(&self) -> Take {
        match self {
            Rule::If { take, .. } | Rule::Score { take, .. } => *take,
        }
    }
    /// How long what this rule took keeps its place after its condition stops holding (0: not).
    pub fn hold_s(&self) -> f32 {
        match self {
            Rule::If { hold_s, .. } | Rule::Score { hold_s, .. } => *hold_s,
        }
    }
}

/// How an `if` rule orders what it takes.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Order {
    /// Nearer first.
    #[default]
    Nearest,
    /// Coming toward me fastest first.
    Closing,
    /// In sight the shortest time first.
    Newest,
    /// Attended longest first (keeps who one already watches).
    Longest,
}

/// How many a rule may take.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Take {
    /// Every match (the default).
    #[default]
    All,
    /// At most this many.
    Up(u32),
}

/// What a creature is to the character (`who`'s `relation`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Relation {
    Friend,
    Enemy,
    /// One whose name the character does not know (the scene's rule, `perception::knows_name`).
    Stranger,
    Family,
    Community,
    Any,
}

impl Relation {
    pub const WORDS: [&'static str; 6] = ["friend", "enemy", "stranger", "family", "community", "any"];
    fn parse(s: &str) -> Option<Relation> {
        Some(match s {
            "friend" => Relation::Friend,
            "enemy" => Relation::Enemy,
            "stranger" => Relation::Stranger,
            "family" => Relation::Family,
            "community" => Relation::Community,
            "any" => Relation::Any,
            _ => return None,
        })
    }
}

/// `who`: by id, by kind, or by kind and relation.
#[derive(Clone, Debug, PartialEq)]
pub enum Who {
    Id(u32),
    Kind(String),
    Filter { kind: String, relation: Option<Relation> },
}

/// A bound on a number: `{"above": a, "below": b}` (either may be absent).
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Bound {
    pub above: Option<f32>,
    pub below: Option<f32>,
}

impl Bound {
    pub fn holds(&self, v: f32) -> bool {
        self.above.is_none_or(|a| v > a) && self.below.is_none_or(|b| v < b)
    }
}

/// A condition about the creature considered.
#[derive(Clone, Debug, PartialEq)]
pub enum Cond {
    Who(Who),
    /// Its attack or throw is winding up at me, or it is threatening me.
    Threatened(bool),
    /// What it visibly does: `is` (a skill's name, its label or a kind word such as `hostile`),
    /// `phase`, whether `at_me`, and within how many metres.
    Doing { is: Option<String>, phase: Option<Phase>, at_me: Option<bool>, within: Option<f32> },
    /// It hurt me within the last N seconds.
    Attacker { within_s: f32 },
    /// It spoke, waved or offered to me within the last N seconds.
    Addressing { within_s: f32 },
    /// It is the target of my own act now.
    ActedOn(bool),
    /// Within N metres.
    Near(f32),
    /// It matches one of my cues (docs/ATTENTION.md).
    Cued(bool),
    /// It is named in my controller's picks (a player's pin or focus; a Jev pick).
    Chosen(bool),
    /// How long I have heeded it (seconds; 0 when not heeded).
    HeededS(Bound),
    /// Salience: coming toward me (m/s; negative when moving away).
    Closing(Bound),
    /// Salience: visibly in a fight move.
    Fighting(bool),
    /// Salience: down or dead.
    Fallen(bool),
    /// Salience: its visible act is aimed at someone I heed.
    ActingOnHeeded(bool),
    /// Salience: in sight for under N seconds.
    New(f32),
    /// Salience: heard calling, shouting or crying.
    Loud(bool),
    /// Salience: carrying a light at night.
    Lit(bool),
    /// A gate on my own state.
    SelfGate(SelfCond),
    All(Vec<Cond>),
    Any(Vec<Cond>),
    Not(Box<Cond>),
}

/// `{"self": ...}`: a gate on the character's own state (the graph's self conditions).
#[derive(Clone, Debug, PartialEq)]
pub enum SelfCond {
    Health(Bound),
    Energy(Bound),
    Hunger(Bound),
    Stamina(Bound),
    Night(bool),
    HurtWithin(f32),
    /// How many creatures of a kind (and relation) are in sight, individuals and crowd alike,
    /// within a distance (none: all in sight).
    Count { kind: String, relation: Option<Relation>, within: Option<f32>, at_least: Option<u32>, at_most: Option<u32> },
}

// ---------------------------------------------------------------------------------------------
// Parsing and validation

/// What a policy may name, for validation: ids the character has met, and the world's creature
/// kinds. Each is a predicate so the caller keeps its own lookup.
pub struct Known<'a> {
    /// The character has met this id (a `familiar` or `relation` row, or knows the name).
    pub met: &'a dyn Fn(u32) -> bool,
    /// A creature kind of this world (`person`, `wolf`, ...).
    pub kind: &'a dyn Fn(&str) -> bool,
}

impl Known<'_> {
    /// Accepts any id and any kind (tests, the instincts' own check of their grammar).
    pub fn any() -> Known<'static> {
        Known { met: &|_| true, kind: &|_| true }
    }
}

/// The condition words a policy may use, for prompts and refusals.
pub const CONDITIONS: [&str; 22] = [
    "who", "threatened", "doing", "attacker", "addressing", "acted_on", "near", "cued", "chosen", "heeded_s", "closing", "fighting", "fallen",
    "acting_on_heeded", "new", "loud", "lit", "self", "all", "any", "not", "count",
];
/// The orders an `if` rule may take.
pub const ORDERS: [&str; 4] = ["nearest", "closing", "newest", "longest"];

/// A policy's JSON to a validated [`Policy`]. Accepts `{"heed": [...]}` or the bare list. An
/// `Err` is the refusal's reason, in words for the mind that wrote it.
pub fn parse(json: &str, known: &Known) -> Result<Policy, String> {
    if json.len() > MAX_BYTES {
        return Err(format!("the policy is {} bytes; at most {MAX_BYTES}", json.len()));
    }
    let v: Value = serde_json::from_str(json).map_err(|e| format!("not JSON: {e}"))?;
    parse_value(&v, known)
}

/// [`parse`] from a parsed value (a reply's `heed` field).
pub fn parse_value(v: &Value, known: &Known) -> Result<Policy, String> {
    let list = match v {
        Value::Array(a) => a,
        Value::Object(o) => {
            if let Some(k) = o.keys().find(|k| *k != "heed") {
                return Err(format!("unknown field `{k}`: a policy is {{\"heed\": [rules]}}"));
            }
            o.get("heed").and_then(Value::as_array).ok_or("a policy is {\"heed\": [rules]}")?
        }
        _ => return Err("a policy is {\"heed\": [rules]}".into()),
    };
    if serde_json::to_string(v).map_or(0, |s| s.len()) > MAX_BYTES {
        return Err(format!("the policy is longer than {MAX_BYTES} bytes"));
    }
    if list.len() > MAX_RULES {
        return Err(format!("{} rules; at most {MAX_RULES}", list.len()));
    }
    let rules = list.iter().enumerate().map(|(i, r)| rule(r, known).map_err(|e| format!("rule {}: {e}", i + 1))).collect::<Result<Vec<_>, _>>()?;
    Ok(Policy { rules })
}

fn rule(v: &Value, known: &Known) -> Result<Rule, String> {
    let o = v.as_object().ok_or("a rule is an object with `if` or `score`")?;
    let why = match o.get("why") {
        None => String::new(),
        Some(Value::String(s)) if s.chars().count() <= MAX_WHY => s.clone(),
        Some(Value::String(_)) => return Err(format!("`why` is longer than {MAX_WHY} characters")),
        Some(_) => return Err("`why` is your own words, a string".into()),
    };
    let take = match o.get("take") {
        None => Take::All,
        Some(Value::String(s)) if s == "rest" || s == "all" => Take::All,
        Some(Value::Number(n)) => match n.as_u64() {
            Some(0) => return Err("`take` 0 takes no one".into()),
            Some(n) if n <= 10_000 => Take::Up(n as u32),
            _ => return Err("`take` is a whole number or \"rest\"".into()),
        },
        Some(_) => return Err("`take` is a whole number or \"rest\"".into()),
    };
    let hold_s = match o.get("hold_s") {
        None => 0.0,
        Some(v) => match v.as_f64() {
            Some(n) if (0.0..=MAX_HOLD_S as f64).contains(&n) => n as f32,
            _ => return Err(format!("`hold_s` is seconds, 0 to {MAX_HOLD_S}")),
        },
    };
    match (o.get("if"), o.get("score")) {
        (Some(_), Some(_)) => Err("a rule has `if` or `score`, not both".into()),
        (Some(c), None) => {
            if let Some(k) = o.keys().find(|k| !["if", "order", "take", "hold_s", "why"].contains(&k.as_str())) {
                return Err(format!("unknown field `{k}` (an `if` rule has if, order, take, hold_s, why)"));
            }
            let order = match o.get("order") {
                None => Order::Nearest,
                Some(Value::String(s)) => match s.as_str() {
                    "nearest" => Order::Nearest,
                    "closing" => Order::Closing,
                    "newest" => Order::Newest,
                    "longest" => Order::Longest,
                    _ => return Err(format!("unknown order `{s}` (orders are {})", ORDERS.join(", "))),
                },
                Some(_) => return Err(format!("`order` is one of {}", ORDERS.join(", "))),
            };
            Ok(Rule::If { cond: cond(c, known, 0)?, order, take, hold_s, why })
        }
        (None, Some(s)) => {
            if let Some(k) = o.keys().find(|k| !["score", "take", "hold_s", "why"].contains(&k.as_str())) {
                return Err(format!("unknown field `{k}` (a `score` rule has score, take, hold_s, why)"));
            }
            let list = s.as_array().ok_or("`score` is a list of {\"if\": condition, \"w\": weight}")?;
            if list.is_empty() {
                return Err("`score` has no weights".into());
            }
            let mut weights = Vec::with_capacity(list.len());
            for w in list {
                let m = w.as_object().ok_or("`score` is a list of {\"if\": condition, \"w\": weight}")?;
                if let Some(k) = m.keys().find(|k| *k != "if" && *k != "w") {
                    return Err(format!("unknown field `{k}` in a weight (a weight has if, w)"));
                }
                let c = m.get("if").ok_or("a weight needs `if`")?;
                let x = m.get("w").and_then(Value::as_f64).ok_or("a weight needs a number `w`")? as f32;
                if !x.is_finite() || x.abs() > MAX_WEIGHT {
                    return Err(format!("a weight lies within -{MAX_WEIGHT}..{MAX_WEIGHT}"));
                }
                weights.push((cond(c, known, 0)?, x));
            }
            Ok(Rule::Score { weights, take, hold_s, why })
        }
        (None, None) => Err("a rule has `if` (a condition) or `score` (weighted conditions)".into()),
    }
}

fn number(v: &Value, what: &str) -> Result<f32, String> {
    let n = v.as_f64().ok_or_else(|| format!("`{what}` is a number"))? as f32;
    if !n.is_finite() || n < 0.0 {
        return Err(format!("`{what}` is a number of 0 or more"));
    }
    Ok(n)
}

fn flag(v: &Value, what: &str) -> Result<bool, String> {
    v.as_bool().ok_or_else(|| format!("`{what}` is true or false"))
}

fn bound(v: &Value, what: &str) -> Result<Bound, String> {
    let o = v.as_object().ok_or_else(|| format!("`{what}` is {{\"above\": n, \"below\": n}}"))?;
    if let Some(k) = o.keys().find(|k| *k != "above" && *k != "below") {
        return Err(format!("unknown field `{k}` in `{what}` (above, below)"));
    }
    let get = |k: &str| -> Result<Option<f32>, String> {
        match o.get(k) {
            None => Ok(None),
            Some(x) => x.as_f64().map(|n| Some(n as f32)).ok_or_else(|| format!("`{what}.{k}` is a number")),
        }
    };
    let b = Bound { above: get("above")?, below: get("below")? };
    if b.above.is_none() && b.below.is_none() {
        return Err(format!("`{what}` needs `above` or `below`"));
    }
    Ok(b)
}

fn relation(v: Option<&Value>) -> Result<Option<Relation>, String> {
    match v {
        None => Ok(None),
        Some(Value::String(s)) => Relation::parse(s).map(Some).ok_or_else(|| format!("unknown relation `{s}` (relations are {})", Relation::WORDS.join(", "))),
        Some(_) => Err("`relation` is a word".into()),
    }
}

fn kind(s: &str, known: &Known) -> Result<String, String> {
    if (known.kind)(s) {
        Ok(s.to_string())
    } else {
        Err(format!("unknown kind of creature `{s}`"))
    }
}

fn who(v: &Value, known: &Known) -> Result<Who, String> {
    match v {
        Value::Number(n) => {
            let id = n.as_u64().filter(|id| *id > 0 && *id <= u32::MAX as u64).ok_or("`who` by id is a creature's id")? as u32;
            if !(known.met)(id) {
                return Err(format!("#{id} is no one you have met"));
            }
            Ok(Who::Id(id))
        }
        Value::String(s) => Ok(Who::Kind(kind(s, known)?)),
        Value::Object(o) => {
            if let Some(k) = o.keys().find(|k| *k != "kind" && *k != "relation") {
                return Err(format!("unknown field `{k}` in `who` (kind, relation)"));
            }
            let k = o.get("kind").and_then(Value::as_str).ok_or("`who` as an object needs a `kind`")?;
            Ok(Who::Filter { kind: kind(k, known)?, relation: relation(o.get("relation"))? })
        }
        _ => Err("`who` is an id, a kind, or {\"kind\": ..., \"relation\": ...}".into()),
    }
}

fn self_cond(v: &Value, known: &Known) -> Result<SelfCond, String> {
    let o = v.as_object().filter(|o| o.len() == 1).ok_or("`self` is one condition on your own state")?;
    let (k, x) = o.iter().next().expect("one entry");
    Ok(match k.as_str() {
        "health" => SelfCond::Health(bound(x, "health")?),
        "energy" => SelfCond::Energy(bound(x, "energy")?),
        "hunger" => SelfCond::Hunger(bound(x, "hunger")?),
        "stamina" => SelfCond::Stamina(bound(x, "stamina")?),
        "night" => SelfCond::Night(flag(x, "night")?),
        "hurt_within" => SelfCond::HurtWithin(number(x, "hurt_within")?),
        "count" => {
            let m = x.as_object().ok_or("`count` is {\"of\": kind, \"within\": metres, \"at_least\": n, \"at_most\": n}")?;
            if let Some(k) = m.keys().find(|k| !["of", "within", "at_least", "at_most"].contains(&k.as_str())) {
                return Err(format!("unknown field `{k}` in `count` (of, within, at_least, at_most)"));
            }
            let (kind_s, rel) = match m.get("of") {
                Some(Value::String(s)) => (kind(s, known)?, None),
                Some(Value::Object(f)) => {
                    let k = f.get("kind").and_then(Value::as_str).ok_or("`count.of` needs a `kind`")?;
                    (kind(k, known)?, relation(f.get("relation"))?)
                }
                _ => return Err("`count` needs `of`: a kind".into()),
            };
            let n = |k: &str| -> Result<Option<u32>, String> { m.get(k).map(|x| x.as_u64().map(|n| n as u32).ok_or_else(|| format!("`count.{k}` is a whole number"))).transpose() };
            let within = m.get("within").map(|x| number(x, "count.within")).transpose()?;
            let (at_least, at_most) = (n("at_least")?, n("at_most")?);
            if at_least.is_none() && at_most.is_none() {
                return Err("`count` needs `at_least` or `at_most`".into());
            }
            SelfCond::Count { kind: kind_s, relation: rel, within, at_least, at_most }
        }
        other => return Err(format!("`self` reads health, energy, hunger, stamina, night, hurt_within or count, not `{other}`")),
    })
}

fn within_s(v: &Value, what: &str) -> Result<f32, String> {
    match v {
        Value::Bool(true) => Ok(10.0),
        Value::Object(o) => {
            if let Some(k) = o.keys().find(|k| *k != "within_s") {
                return Err(format!("unknown field `{k}` in `{what}` (within_s)"));
            }
            number(o.get("within_s").ok_or_else(|| format!("`{what}` needs `within_s`"))?, "within_s")
        }
        _ => Err(format!("`{what}` is true or {{\"within_s\": seconds}}")),
    }
}

fn cond(v: &Value, known: &Known, depth: usize) -> Result<Cond, String> {
    if depth > MAX_DEPTH {
        return Err(format!("conditions nest more than {MAX_DEPTH} deep"));
    }
    let o: &Map<String, Value> = v.as_object().filter(|o| o.len() == 1).ok_or("a condition is one word and its value, e.g. {\"near\": 8}")?;
    let (k, x) = o.iter().next().expect("one entry");
    let list = |x: &Value| -> Result<Vec<Cond>, String> {
        let a = x.as_array().filter(|a| !a.is_empty()).ok_or_else(|| format!("`{k}` is a list of conditions"))?;
        a.iter().map(|c| cond(c, known, depth + 1)).collect()
    };
    Ok(match k.as_str() {
        "who" => Cond::Who(who(x, known)?),
        "threatened" => Cond::Threatened(flag(x, k)?),
        "doing" => {
            let m = x.as_object().ok_or("`doing` is {\"is\": ..., \"phase\": ..., \"at_me\": true, \"within\": metres}")?;
            if let Some(f) = m.keys().find(|f| !["is", "phase", "at_me", "within"].contains(&f.as_str())) {
                return Err(format!("unknown field `{f}` in `doing` (is, phase, at_me, within)"));
            }
            let is = m.get("is").map(|s| s.as_str().map(str::to_string).ok_or("`doing.is` is a word")).transpose()?;
            let phase = match m.get("phase") {
                None => None,
                Some(Value::String(s)) => {
                    Some(Phase::parse(s).ok_or_else(|| format!("unknown phase `{s}` (phases are {})", Phase::ALL.iter().map(|p| p.word()).collect::<Vec<_>>().join(", ")))?)
                }
                Some(_) => return Err("`doing.phase` is a word".into()),
            };
            let at_me = m.get("at_me").map(|b| flag(b, "doing.at_me")).transpose()?;
            let within = m.get("within").map(|w| number(w, "doing.within")).transpose()?;
            Cond::Doing { is, phase, at_me, within }
        }
        "attacker" => Cond::Attacker { within_s: within_s(x, k)? },
        "addressing" => Cond::Addressing { within_s: within_s(x, k)? },
        "acted_on" => Cond::ActedOn(flag(x, k)?),
        "near" => Cond::Near(number(x, k)?),
        "cued" => Cond::Cued(flag(x, k)?),
        "chosen" => Cond::Chosen(flag(x, k)?),
        "heeded_s" => Cond::HeededS(bound(x, k)?),
        "closing" => Cond::Closing(bound(x, k)?),
        "fighting" => Cond::Fighting(flag(x, k)?),
        "fallen" => Cond::Fallen(flag(x, k)?),
        "acting_on_heeded" => Cond::ActingOnHeeded(flag(x, k)?),
        "new" => Cond::New(number(x, k)?),
        "loud" => Cond::Loud(flag(x, k)?),
        "lit" => Cond::Lit(flag(x, k)?),
        "self" => Cond::SelfGate(self_cond(x, known)?),
        "count" => Cond::SelfGate(self_cond(&serde_json::json!({ "count": x }), known)?),
        "all" => Cond::All(list(x)?),
        "any" => Cond::Any(list(x)?),
        "not" => Cond::Not(Box::new(cond(x, known, depth + 1)?)),
        other => return Err(format!("unknown condition `{other}` (conditions are {})", CONDITIONS.join(", "))),
    })
}

// ---------------------------------------------------------------------------------------------
// The species' instincts

/// A species' starting heed policy as JSON (`heed_<kind>` in `living/seeds/heed.json`); a kind
/// without its own takes `heed_default`.
pub fn instinct_json(kind: &str) -> Value {
    let all: Value = serde_json::from_str(INSTINCTS).expect("heed instincts json");
    all.get(format!("heed_{kind}")).or_else(|| all.get("heed_default")).cloned().expect("heed_default")
}

/// A species' starting heed policy, parsed (the instincts name kinds, never ids).
pub fn instinct(kind: &str) -> Policy {
    parse_value(&instinct_json(kind), &Known::any()).expect("the heed instincts parse")
}

/// A policy with every rule's hold taken out (for measuring what the holds do).
pub fn without_holds(p: &Policy) -> Policy {
    let rules = p
        .rules
        .iter()
        .cloned()
        .map(|r| match r {
            Rule::If { cond, order, take, why, .. } => Rule::If { cond, order, take, hold_s: 0.0, why },
            Rule::Score { weights, take, why, .. } => Rule::Score { weights, take, hold_s: 0.0, why },
        })
        .collect();
    Policy { rules }
}

// ---------------------------------------------------------------------------------------------
// What the selector reads

/// Bits of [`Candidate::relations`].
pub mod rel {
    pub const FAMILY: u8 = 1;
    pub const FRIEND: u8 = 2;
    pub const ENEMY: u8 = 4;
    /// The character does not know its name.
    pub const STRANGER: u8 = 8;
    pub const COMMUNITY: u8 = 16;
}

/// What a creature visibly does (`perception::visibly`): the words it can be named by (the
/// skill's name, its label, its kind words such as `hostile`, `melee`, `missile`), its phase,
/// and whether it is aimed at me.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Visible {
    pub is: Vec<String>,
    pub phase: Option<Phase>,
    pub at_me: bool,
}

/// A creature in the character's sight, as its perception gives it. The caller fills what it
/// knows; defaults are "no" and "never".
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Candidate {
    pub id: u32,
    pub kind: String,
    /// Metres.
    pub dist: f32,
    /// Metres a second toward me (negative: moving away).
    pub closing: f32,
    /// The character can make it out (false: the far label; no id or relation matches).
    pub made_out: bool,
    /// [`rel`] bits.
    pub relations: u8,
    /// Its attack or throw is winding up at me, or it threatens me.
    pub threatening: bool,
    pub doing: Option<Visible>,
    /// Seconds since it last hurt me.
    pub hurt_me_ago_s: Option<f32>,
    /// Seconds since it last spoke, waved or offered to me.
    pub addressed_me_ago_s: Option<f32>,
    /// The target of my own act now (forced: [`Place::Acting`]).
    pub acted_on: bool,
    /// Seconds since it last made contact with me: a blow of its that landed on me, or that I
    /// blocked or dodged (forced within the contact window: [`Place::Contact`]).
    pub contact_ago_s: Option<f32>,
    pub cued: bool,
    /// My controller's pick of it (a weight in 0..1), if any.
    pub chosen: Option<f32>,
    /// Seconds I have heeded it (none: not heeded now).
    pub heeded_s: Option<f32>,
    /// Seconds it has been in sight.
    pub in_sight_s: f32,
    pub fighting: bool,
    pub fallen: bool,
    pub acting_on_heeded: bool,
    pub loud: bool,
    pub lit: bool,
}

/// The character's own state, for `self` gates.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct SelfState {
    /// Percent of full health.
    pub health: f32,
    pub energy: f32,
    pub hunger: f32,
    pub stamina: f32,
    pub night: bool,
    /// Seconds since it was last hurt.
    pub hurt_ago_s: Option<f32>,
}

/// Why a creature is an individual to the character.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Place {
    /// It is the target of the character's own act: one cannot act on a throng. Forced.
    Acting,
    /// It made contact with the character within the contact window. Forced.
    Contact,
    /// The policy's rule at this index took it.
    Rule(usize),
}

impl Place {
    pub fn forced(self) -> bool {
        !matches!(self, Place::Rule(_))
    }
    pub fn rule(self) -> Option<usize> {
        match self {
            Place::Rule(r) => Some(r),
            _ => None,
        }
    }
}

/// One heeded: which creature, and why. `held`: it has its place only by its rule's hold (its
/// rule would not take it now on its own merit); the caller keeps, per creature, when it last
/// had its place on merit, for the next pass's [`Held`].
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Pick {
    pub id: u32,
    pub place: Place,
    pub held: bool,
}

impl Pick {
    pub fn new(id: u32, place: Place) -> Pick {
        Pick { id, place, held: false }
    }
}

/// One heeded before this pass by a rule, whose rule last took it on merit `lapsed_s` seconds
/// ago: it keeps that rule's place while `lapsed_s` is under the rule's `hold_s` (hysteresis as
/// the policy's own content: what a rule took stays for that long after the rule stops taking
/// it, unless a better rule needs the place).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Held {
    pub id: u32,
    pub rule: usize,
    pub lapsed_s: f32,
}

/// The bounds of a pass: the capacity (the law's answer, clamped) and the contact window.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Limits {
    pub capacity: usize,
    pub contact_s: f32,
}

impl Limits {
    pub fn new(capacity: usize) -> Limits {
        Limits { capacity, contact_s: DEFAULT_CONTACT_S }
    }
}

/// The forced place of `c`, if it has one.
pub fn forced(c: &Candidate, limits: &Limits) -> Option<Place> {
    if c.acted_on {
        Some(Place::Acting)
    } else if c.contact_ago_s.is_some_and(|a| a <= limits.contact_s) {
        Some(Place::Contact)
    } else {
        None
    }
}

// ---------------------------------------------------------------------------------------------
// Evaluation

fn who_holds(w: &Who, c: &Candidate) -> bool {
    match w {
        Who::Id(id) => c.made_out && c.id == *id,
        Who::Kind(k) => c.kind == *k,
        Who::Filter { kind, relation } => c.kind == *kind && relation.is_none_or(|r| relation_holds(r, c)),
    }
}

fn relation_holds(r: Relation, c: &Candidate) -> bool {
    if r == Relation::Any {
        return true;
    }
    if !c.made_out {
        return false;
    }
    let bit = match r {
        Relation::Family => rel::FAMILY,
        Relation::Friend => rel::FRIEND,
        Relation::Enemy => rel::ENEMY,
        Relation::Stranger => rel::STRANGER,
        Relation::Community => rel::COMMUNITY,
        Relation::Any => unreachable!(),
    };
    c.relations & bit != 0
}

fn self_holds(s: &SelfCond, me: &SelfState, all: &[Candidate]) -> bool {
    match s {
        SelfCond::Health(b) => b.holds(me.health),
        SelfCond::Energy(b) => b.holds(me.energy),
        SelfCond::Hunger(b) => b.holds(me.hunger),
        SelfCond::Stamina(b) => b.holds(me.stamina),
        SelfCond::Night(n) => me.night == *n,
        SelfCond::HurtWithin(s) => me.hurt_ago_s.is_some_and(|a| a <= *s),
        SelfCond::Count { kind, relation, within, at_least, at_most } => {
            let n = all.iter().filter(|c| c.kind == *kind && relation.is_none_or(|r| relation_holds(r, c)) && within.is_none_or(|w| c.dist <= w)).count() as u32;
            at_least.is_none_or(|a| n >= a) && at_most.is_none_or(|m| n <= m)
        }
    }
}

/// Whether `cond` holds for `c`, given the character's state and everyone in its sight.
pub fn holds(cond: &Cond, c: &Candidate, me: &SelfState, all: &[Candidate]) -> bool {
    match cond {
        Cond::Who(w) => who_holds(w, c),
        Cond::Threatened(b) => (c.threatening || c.doing.as_ref().is_some_and(|d| d.at_me && d.is.iter().any(|w| w == "hostile") && d.phase.is_some_and(|p| p.fits(Phase::WindingUp)))) == *b,
        Cond::Doing { is, phase, at_me, within } => c.doing.as_ref().is_some_and(|d| {
            is.as_ref().is_none_or(|w| d.is.iter().any(|x| x == w))
                && phase.is_none_or(|p| d.phase.is_some_and(|seen| seen.fits(p)))
                && at_me.is_none_or(|m| d.at_me == m)
                && within.is_none_or(|w| c.dist <= w)
        }),
        Cond::Attacker { within_s } => c.hurt_me_ago_s.is_some_and(|a| a <= *within_s),
        Cond::Addressing { within_s } => c.addressed_me_ago_s.is_some_and(|a| a <= *within_s),
        Cond::ActedOn(b) => c.acted_on == *b,
        Cond::Near(m) => c.dist <= *m,
        Cond::Cued(b) => c.cued == *b,
        Cond::Chosen(b) => c.chosen.is_some() == *b,
        Cond::HeededS(b) => b.holds(c.heeded_s.unwrap_or(0.0)),
        Cond::Closing(b) => b.holds(c.closing),
        Cond::Fighting(b) => c.fighting == *b,
        Cond::Fallen(b) => c.fallen == *b,
        Cond::ActingOnHeeded(b) => c.acting_on_heeded == *b,
        Cond::New(s) => c.in_sight_s < *s,
        Cond::Loud(b) => c.loud == *b,
        Cond::Lit(b) => c.lit == *b,
        Cond::SelfGate(s) => self_holds(s, me, all),
        Cond::All(v) => v.iter().all(|x| holds(x, c, me, all)),
        Cond::Any(v) => v.iter().any(|x| holds(x, c, me, all)),
        Cond::Not(x) => !holds(x, c, me, all),
    }
}

/// The sort key of a candidate within a rule (smaller first): the rule's order, then distance,
/// then id (so the selection never depends on the input's order).
fn key(rule: &Rule, c: &Candidate, me: &SelfState, all: &[Candidate]) -> (f32, f32, u32) {
    let primary = match rule {
        Rule::If { order: Order::Nearest, .. } => c.dist,
        Rule::If { order: Order::Closing, .. } => -c.closing,
        Rule::If { order: Order::Newest, .. } => c.in_sight_s,
        Rule::If { order: Order::Longest, .. } => -c.heeded_s.unwrap_or(0.0),
        Rule::Score { weights, .. } => -score(weights, c, me, all),
    };
    (primary, c.dist, c.id)
}

fn score(weights: &[(Cond, f32)], c: &Candidate, me: &SelfState, all: &[Candidate]) -> f32 {
    weights.iter().filter(|(w, _)| holds(w, c, me, all)).map(|(_, x)| *x).sum()
}

/// Whether `rule` would take `c` at all (a score rule takes anyone).
fn matches(rule: &Rule, c: &Candidate, me: &SelfState, all: &[Candidate]) -> bool {
    match rule {
        Rule::If { cond, .. } => holds(cond, c, me, all),
        Rule::Score { .. } => true,
    }
}

/// The first rule that would take `c` (ignoring `take` and capacity): its rank for the event
/// pass. None: no rule takes it.
pub fn rank_of(policy: &Policy, c: &Candidate, me: &SelfState, all: &[Candidate]) -> Option<usize> {
    policy.rules.iter().position(|r| matches(r, c, me, all))
}

/// The full pass. First the forced places ([`forced`]), outside the capacity; then every other
/// candidate in sight ranked by the policy, at most `limits.capacity` taken, in rank order. A
/// [`Held`] creature still in sight whose rule's `hold_s` has not run out keeps that rule's place
/// (it is ranked first within that rule, counting toward the rule's `take`), unless a better rule
/// now takes it. A pick is marked `held` when the same pass without holds would not have given
/// it that place.
pub fn select(policy: &Policy, me: &SelfState, all: &[Candidate], limits: &Limits, held: &[Held]) -> Vec<Pick> {
    let mut out = fill(policy, me, all, limits, held);
    if held.is_empty() {
        return out;
    }
    let merit = fill(policy, me, all, limits, &[]);
    for p in &mut out {
        p.held = !p.place.forced() && !merit.iter().any(|m| m.id == p.id && m.place == p.place);
    }
    out
}

fn fill(policy: &Policy, me: &SelfState, all: &[Candidate], limits: &Limits, held: &[Held]) -> Vec<Pick> {
    let mut out: Vec<Pick> = Vec::new();
    let mut taken = vec![false; all.len()];
    let mut forced_ones: Vec<(Place, usize)> = all.iter().enumerate().filter_map(|(i, c)| forced(c, limits).map(|p| (p, i))).collect();
    forced_ones.sort_by(|a, b| a.0.cmp(&b.0).then(all[a.1].dist.total_cmp(&all[b.1].dist)).then(all[a.1].id.cmp(&all[b.1].id)));
    for (place, i) in forced_ones {
        taken[i] = true;
        out.push(Pick::new(all[i].id, place));
    }
    let capacity = limits.capacity;
    let mut n_rule = 0usize;
    let index = |id: u32| all.iter().position(|c| c.id == id);
    for (ri, rule) in policy.rules.iter().enumerate() {
        if n_rule >= capacity {
            break;
        }
        // Held by this rule within its hold, and not taken by an earlier one.
        let mut held_here: Vec<usize> =
            held.iter().filter(|h| h.rule == ri && h.lapsed_s < rule.hold_s()).filter_map(|h| index(h.id)).filter(|&i| !taken[i]).collect();
        held_here.sort_by(|&a, &b| key(rule, &all[a], me, all).partial_cmp(&key(rule, &all[b], me, all)).unwrap_or(std::cmp::Ordering::Equal));
        let mut n = 0usize;
        for i in held_here {
            if n_rule >= capacity {
                break;
            }
            taken[i] = true;
            out.push(Pick::new(all[i].id, Place::Rule(ri)));
            n += 1;
            n_rule += 1;
        }
        let limit_hit = |n: usize| match rule.take() {
            Take::All => false,
            Take::Up(k) => n >= k as usize,
        };
        if limit_hit(n) {
            continue;
        }
        let mut m: Vec<(usize, (f32, f32, u32))> =
            all.iter().enumerate().filter(|(i, c)| !taken[*i] && matches(rule, c, me, all)).map(|(i, c)| (i, key(rule, c, me, all))).collect();
        m.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
        let limit = match rule.take() {
            Take::All => usize::MAX,
            Take::Up(k) => k as usize,
        };
        for (i, _) in m {
            if n_rule >= capacity || n >= limit {
                break;
            }
            taken[i] = true;
            out.push(Pick::new(all[i].id, Place::Rule(ri)));
            n += 1;
            n_rule += 1;
        }
    }
    out
}

/// The event pass's answer for one candidate against the heeded set.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Admit {
    /// Already heeded (and not newly forced), or no rule takes it, or it ranks below everyone
    /// heeded at capacity.
    No,
    /// It is forced now ([`Place::Acting`], [`Place::Contact`]): it becomes an individual
    /// whatever the capacity (if it was heeded by a rule, its place changes to the forced one).
    Forced(Place),
    /// A place is free: it takes it at this rule.
    Take { rule: usize },
    /// The rule places are full: it takes the place of `drop` (the one ranked last by rule).
    Replace { rule: usize, drop: u32 },
}

/// The event pass: whether `c` enters the heeded set `heeded` (as [`select`] gives it) now,
/// without re-ranking the rest. A tie with the last does not displace it (the one already heeded
/// keeps its place); the next full pass settles the order. `take` limits are left to it.
pub fn admit(policy: &Policy, c: &Candidate, me: &SelfState, all: &[Candidate], heeded: &[Pick], limits: &Limits) -> Admit {
    let now = heeded.iter().find(|p| p.id == c.id);
    if let Some(place) = forced(c, limits) {
        return match now {
            Some(p) if p.place.forced() => Admit::No,
            _ => Admit::Forced(place),
        };
    }
    if limits.capacity == 0 || now.is_some() {
        return Admit::No;
    }
    let Some(rule) = rank_of(policy, c, me, all) else { return Admit::No };
    let by_rule: Vec<&Pick> = heeded.iter().filter(|p| !p.place.forced()).collect();
    if by_rule.len() < limits.capacity {
        return Admit::Take { rule };
    }
    let last = by_rule.iter().max_by_key(|p| p.place.rule()).expect("full set");
    if Some(rule) < last.place.rule() {
        Admit::Replace { rule, drop: last.id }
    } else {
        Admit::No
    }
}

// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn cand(id: u32, kind: &str, dist: f32) -> Candidate {
        Candidate { id, kind: kind.into(), dist, made_out: true, in_sight_s: 60.0, ..Default::default() }
    }
    fn me() -> SelfState {
        SelfState { health: 100.0, energy: 80.0, ..Default::default() }
    }
    fn lim(n: usize) -> Limits {
        Limits::new(n)
    }
    fn ids(p: &[Pick]) -> Vec<u32> {
        p.iter().map(|p| p.id).collect()
    }
    fn refuse(v: Value) -> String {
        parse_value(&v, &Known { met: &|id| id == 7, kind: &|k| ["person", "wolf", "deer"].contains(&k) }).unwrap_err()
    }

    #[test]
    fn the_grammar_takes_every_condition() {
        let p = json!({"heed": [
            {"if": {"all": [{"who": 7}, {"who": "wolf"}, {"who": {"kind": "person", "relation": "family"}}]}, "order": "closing", "take": 2, "hold_s": 3, "why": "mine"},
            {"if": {"any": [{"threatened": true}, {"doing": {"is": "hostile", "phase": "winding_up", "at_me": true, "within": 20}},
                             {"attacker": {"within_s": 5}}, {"addressing": true}, {"acted_on": true}, {"near": 8}, {"cued": true}, {"chosen": true},
                             {"heeded_s": {"above": 2}}, {"closing": {"above": 1.0}}, {"fighting": true}, {"fallen": false},
                             {"acting_on_heeded": true}, {"new": 5}, {"loud": true}, {"lit": true},
                             {"self": {"health": {"below": 50}}}, {"self": {"night": true}}, {"self": {"hurt_within": 3}},
                             {"count": {"of": "person", "within": 10, "at_least": 20}}, {"not": {"who": "deer"}}]}},
            {"score": [{"if": {"fighting": true}, "w": 2}, {"if": {"new": 3}, "w": -1.5}], "take": "rest", "hold_s": 2.5}
        ]});
        let pol = parse_value(&p, &Known { met: &|id| id == 7, kind: &|_| true }).unwrap();
        assert_eq!(pol.rules.len(), 3);
        assert!(matches!(&pol.rules[0], Rule::If { order: Order::Closing, take: Take::Up(2), .. }));
        assert_eq!(pol.rules[0].hold_s(), 3.0);
        assert!(matches!(&pol.rules[2], Rule::Score { take: Take::All, .. }));
        assert_eq!(pol.rules[2].hold_s(), 2.5);
        assert_eq!(without_holds(&pol).rules.iter().map(|r| r.hold_s()).sum::<f32>(), 0.0);
        // The bare list is a policy too.
        assert_eq!(parse(&serde_json::to_string(&p["heed"]).unwrap(), &Known::any()).unwrap().rules.len(), 3);
    }

    #[test]
    fn refusals_say_why() {
        assert!(refuse(json!({"heed": [{"if": {"near": 8}}], "extra": 1})).contains("unknown field `extra`"));
        assert!(refuse(json!({"attend": [{"if": {"near": 8}}]})).contains("unknown field `attend`"));
        assert!(refuse(json!({"heed": [{"if": {"gaze": 8}}]})).contains("unknown condition `gaze`"));
        assert!(refuse(json!({"heed": [{"if": {"who": 99}}]})).contains("#99 is no one you have met"));
        assert!(refuse(json!({"heed": [{"if": {"who": "dragon"}}]})).contains("unknown kind of creature `dragon`"));
        assert!(refuse(json!({"heed": [{"if": {"doing": {"phase": "dancing"}}}]})).contains("unknown phase `dancing`"));
        assert!(refuse(json!({"heed": [{"if": {"near": 8}, "order": "loudest"}]})).contains("unknown order `loudest`"));
        assert!(refuse(json!({"heed": [{"if": {"near": 8}, "take": 0}]})).contains("`take` 0"));
        assert!(refuse(json!({"heed": [{"if": {"near": 8}, "hold_s": 61}]})).contains("`hold_s` is seconds"));
        assert!(refuse(json!({"heed": [{"if": {"near": 8}, "why": "x".repeat(161)}]})).contains("longer than 160"));
        assert!(refuse(json!({"heed": [{"score": []}]})).contains("no weights"));
        assert!(refuse(json!({"heed": [{"score": [{"if": {"near": 3}, "w": 11}]}]})).contains("-10..10"));
        assert!(refuse(json!({"heed": [{"if": {"near": 3}, "score": [{"if": {"near": 3}, "w": 1}]}]})).contains("not both"));
        assert!(refuse(json!({"heed": [{"if": {"who": {"kind": "person", "relation": "rival"}}}]})).contains("unknown relation `rival`"));
        assert!(refuse(json!({"heed": [{"if": {"self": {"sees": "wolf"}}}]})).contains("`self` reads"));
        assert!(refuse(json!({"heed": [{"if": {"near": 3, "who": "wolf"}}]})).contains("one word and its value"));
        let deep = (0..8).fold(json!({"near": 1}), |c, _| json!({"not": c}));
        assert!(refuse(json!({"heed": [{"if": deep}]})).contains("nest more than"));
        let many: Vec<Value> = (0..13).map(|_| json!({"if": {"near": 3}})).collect();
        assert!(refuse(json!({"heed": many})).contains("13 rules; at most 12"));
        assert!(parse(&"x".repeat(MAX_BYTES + 1), &Known::any()).unwrap_err().contains("bytes"));
        // A refusal names the rule.
        assert!(refuse(json!({"heed": [{"if": {"near": 8}}, {"if": {"who": 99}}]})).starts_with("rule 2:"));
        // A policy with no threat rule is accepted: anticipating attacks is the mind's choice.
        assert!(parse_value(&json!({"heed": [{"if": {"who": "deer"}}]}), &Known::any()).is_ok());
    }

    #[test]
    fn the_instincts_parse_and_rank_in_their_order() {
        for kind in ["person", "wolf", "deer", "boar"] {
            let p = instinct(kind);
            assert!(!p.rules.is_empty() && p.rules.len() <= MAX_RULES, "{kind}");
            assert!(serde_json::to_string(&instinct_json(kind)).unwrap().len() <= MAX_BYTES);
        }
        let p = instinct("person");
        // A crowd round a person: an archer winding up at it from 20 m, a speaker, a family
        // member at 15 m, ten others close, and a wolf at 30 m.
        let mut all = vec![];
        let mut archer = cand(1, "person", 20.0);
        archer.doing = Some(Visible { is: vec!["shoot".into(), "hostile".into(), "missile".into()], phase: Some(Phase::WindingUp), at_me: true });
        all.push(archer);
        let mut speaker = cand(2, "person", 6.0);
        speaker.addressed_me_ago_s = Some(2.0);
        all.push(speaker);
        let mut kin = cand(3, "person", 15.0);
        kin.relations = rel::FAMILY;
        all.push(kin);
        for i in 0..10 {
            all.push(cand(10 + i, "person", 1.0 + i as f32 * 0.5));
        }
        all.push(cand(50, "wolf", 30.0));
        let picks = select(&p, &me(), &all, &lim(10), &[]);
        assert_eq!(&ids(&picks)[..3], &[1, 2, 3], "the windup at me, then the speaker, then family: {picks:?}");
        assert_eq!(picks[0].place, Place::Rule(0));
        assert_eq!(picks.len(), 10);
        // Six nearest within 8 m, then the score rule's pick (the wolf: kind weight 2).
        assert_eq!(&ids(&picks)[3..9], &[10, 11, 12, 13, 14, 15]);
        assert_eq!(picks[9].id, 50, "the wolf stands out over the rest of the crowd: {picks:?}");
        assert_eq!(ids(&select(&p, &me(), &all, &lim(2), &[])), vec![1, 2]);
        assert!(select(&p, &me(), &all, &lim(0), &[]).is_empty());
    }

    #[test]
    fn acting_and_contact_are_forced_outside_capacity_and_policy() {
        // A policy that ignores everyone, at capacity 0: the forced ones are still individuals.
        let p = parse_value(&json!({"heed": [{"if": {"who": "deer"}}]}), &Known::any()).unwrap();
        let mut target = cand(1, "person", 2.0);
        target.acted_on = true;
        let mut striker = cand(2, "person", 1.5);
        striker.contact_ago_s = Some(1.0);
        let mut old = cand(3, "person", 1.0);
        old.contact_ago_s = Some(9.0);
        let mut winder = cand(4, "person", 2.5);
        winder.doing = Some(Visible { is: vec!["strike".into(), "hostile".into()], phase: Some(Phase::WindingUp), at_me: true });
        let all = vec![target, striker, old, winder];
        let picks = select(&p, &me(), &all, &lim(0), &[]);
        assert_eq!(picks, vec![Pick::new(1, Place::Acting), Pick::new(2, Place::Contact)]);
        // Contact older than the window is not forced; a windup is not contact: the policy decides.
        assert!(!ids(&picks).contains(&3) && !ids(&picks).contains(&4));
        // The window is the world's.
        let wide = Limits { capacity: 0, contact_s: 10.0 };
        assert_eq!(ids(&select(&p, &me(), &all, &wide, &[])), vec![1, 3, 2], "contacts nearer first");
        // Forced places do not use the capacity: the instinct still fills its own.
        let picks = select(&instinct("person"), &me(), &all, &lim(1), &[]);
        assert_eq!(picks.iter().filter(|p| !p.place.forced()).count(), 1);
        assert_eq!(picks.last().unwrap().id, 4, "the instinct takes the windup with its one place");
    }

    #[test]
    fn a_far_figure_matches_no_id_and_no_relation() {
        let p = parse_value(&json!({"heed": [{"if": {"who": 5}}, {"if": {"who": {"kind": "person", "relation": "family"}}}]}), &Known::any()).unwrap();
        let mut far = cand(5, "person", 40.0);
        far.relations = rel::FAMILY;
        far.made_out = false;
        assert!(select(&p, &me(), &[far.clone()], &lim(4), &[]).is_empty());
        far.made_out = true;
        assert_eq!(select(&p, &me(), &[far], &lim(4), &[])[0].place, Place::Rule(0));
    }

    #[test]
    fn take_order_and_score_behave() {
        let p = parse_value(
            &json!({"heed": [{"if": {"near": 10}, "order": "closing", "take": 1},
                             {"score": [{"if": {"fighting": true}, "w": 2}, {"if": {"new": 5}, "w": 1}], "take": 2}]}),
            &Known::any(),
        )
        .unwrap();
        let mut a = cand(1, "person", 2.0);
        a.closing = 0.5;
        let mut b = cand(2, "person", 9.0);
        b.closing = 3.0;
        let mut c = cand(3, "person", 30.0);
        c.fighting = true;
        let mut d = cand(4, "person", 25.0);
        d.in_sight_s = 1.0;
        let e = cand(5, "person", 12.0);
        let picks = select(&p, &me(), &[a, b, c, d, e], &lim(10), &[]);
        assert_eq!(ids(&picks), vec![2, 3, 4]);
        assert_eq!(picks.iter().map(|p| p.place).collect::<Vec<_>>(), vec![Place::Rule(0), Place::Rule(1), Place::Rule(1)]);
    }

    #[test]
    fn a_rule_s_hold_keeps_what_it_took() {
        let p = parse_value(&json!({"heed": [{"if": {"near": 5}, "hold_s": 3}, {"if": {"near": 20}}]}), &Known::any()).unwrap();
        // 9 walked out of 5 m a second ago: within its rule's hold it keeps rule 0's place against
        // the nearer 2 and 3, marked held.
        let all = vec![cand(9, "person", 6.0), cand(2, "person", 3.0), cand(3, "person", 4.0)];
        assert_eq!(ids(&select(&p, &me(), &all, &lim(2), &[])), vec![2, 3]);
        let held = [Held { id: 9, rule: 0, lapsed_s: 1.0 }];
        let picks = select(&p, &me(), &all, &lim(2), &held);
        assert_eq!(ids(&picks), vec![9, 2]);
        assert_eq!(picks.iter().map(|p| p.held).collect::<Vec<_>>(), vec![true, false]);
        // One still in reach of its rule is not held: it has its place on merit.
        let near_held = select(&p, &me(), &all, &lim(2), &[Held { id: 2, rule: 0, lapsed_s: 0.0 }]);
        assert!(near_held.iter().all(|p| !p.held));
        // The hold has run out.
        assert_eq!(ids(&select(&p, &me(), &all, &lim(2), &[Held { id: 9, rule: 0, lapsed_s: 3.5 }])), vec![2, 3]);
        // A hold counts toward the rule's take.
        let one = parse_value(&json!({"heed": [{"if": {"near": 5}, "take": 1, "hold_s": 3}]}), &Known::any()).unwrap();
        assert_eq!(ids(&select(&one, &me(), &all, &lim(4), &[Held { id: 9, rule: 0, lapsed_s: 1.0 }])), vec![9]);
        // Without the policy's hold, no hold.
        assert_eq!(ids(&select(&without_holds(&p), &me(), &all, &lim(2), &held)), vec![2, 3]);
        // A held one gone from sight is ignored.
        assert_eq!(ids(&select(&p, &me(), &all[1..], &lim(2), &held)), vec![2, 3]);
    }

    #[test]
    fn the_event_pass_admits_by_rank_and_forces_contact() {
        let p = instinct("person");
        let crowd: Vec<Candidate> = (0..4).map(|i| cand(10 + i, "person", 2.0 + i as f32)).collect();
        let heeded = select(&p, &me(), &crowd, &lim(4), &[]);
        let mut archer = cand(1, "person", 20.0);
        archer.threatening = true;
        let mut all = crowd.clone();
        all.push(archer.clone());
        // Full: the windup at me displaces the one ranked last.
        assert_eq!(admit(&p, &archer, &me(), &all, &heeded, &lim(4)), Admit::Replace { rule: 0, drop: heeded.last().unwrap().id });
        assert_eq!(admit(&p, &archer, &me(), &all, &heeded[..3], &lim(4)), Admit::Take { rule: 0 });
        // A policy without the threat rule leaves the windup in the throng...
        let blind = parse_value(&json!({"heed": [{"if": {"near": 8}}]}), &Known::any()).unwrap();
        assert_eq!(admit(&blind, &archer, &me(), &all, &heeded, &lim(4)), Admit::No);
        // ...until its blow lands: contact is forced, whatever the policy and the capacity.
        let mut struck = archer.clone();
        struck.contact_ago_s = Some(0.0);
        assert_eq!(admit(&blind, &struck, &me(), &all, &heeded, &lim(4)), Admit::Forced(Place::Contact));
        // One already heeded by a rule becomes forced on contact; one already forced: no change.
        let mut close = crowd[0].clone();
        close.contact_ago_s = Some(0.0);
        assert_eq!(admit(&p, &close, &me(), &all, &heeded, &lim(4)), Admit::Forced(Place::Contact));
        let forced_set = [Pick::new(close.id, Place::Contact)];
        assert_eq!(admit(&p, &close, &me(), &all, &forced_set, &lim(4)), Admit::No);
        let walker = cand(30, "person", 7.0);
        assert_eq!(admit(&p, &walker, &me(), &all, &heeded, &lim(4)), Admit::No);
        assert_eq!(admit(&p, &crowd[0], &me(), &all, &heeded, &lim(4)), Admit::No);
    }

    #[test]
    fn self_gates_and_counts_read_the_whole_sight() {
        let p = parse_value(
            &json!({"heed": [{"if": {"all": [{"self": {"health": {"below": 50}}}, {"closing": {"above": 0.5}}]}},
                             {"if": {"all": [{"count": {"of": "person", "at_least": 3}}, {"who": "wolf"}]}}]}),
            &Known::any(),
        )
        .unwrap();
        let mut runner = cand(1, "person", 10.0);
        runner.closing = 2.0;
        let all = vec![runner, cand(2, "person", 3.0), cand(3, "person", 4.0), cand(4, "wolf", 9.0)];
        assert_eq!(ids(&select(&p, &me(), &all, &lim(5), &[])), vec![4]);
        let hurt = SelfState { health: 30.0, ..me() };
        assert_eq!(ids(&select(&p, &hurt, &all, &lim(5), &[])), vec![1, 4]);
        assert_eq!(ids(&select(&p, &hurt, &all[..2], &lim(5), &[])), vec![1], "two people: the count gate fails");
    }
}

#[cfg(all(test, feature = "scripting"))]
mod capacity_tests {
    use super::*;
    use crate::script::{ActorFacts, Scripts, SkillCtx};

    const SHIPPED: &str = include_str!("../../scripts/skills.rhai");
    const OVERLAY: &str = include_str!("../../seeds/worlds/heed/laws.rhai");

    fn person(stage: &str) -> SkillCtx {
        SkillCtx {
            actor: ActorFacts { id: 1, kind: "person".into(), stage: stage.into(), hp: 1.0e6, energy: 80.0, stamina: 60.0, ..Default::default() },
            ..Default::default()
        }
    }

    #[test]
    fn the_ceiling_clamps() {
        assert_eq!(clamp_capacity(20.0, 16.0), 16);
        assert_eq!(clamp_capacity(9.9, 16.0), 9);
        assert_eq!(clamp_capacity(-3.0, 16.0), 0);
        assert_eq!(clamp_capacity(f64::NAN, 16.0), 0);
        assert_eq!(clamp_capacity(12.0, 0.0), 0);
        assert_eq!(clamp_capacity(12.0, f32::INFINITY), 0);
    }

    #[test]
    fn the_starting_formula_gives_its_cases() {
        let s = Scripts::new(SHIPPED).expect("skills compile");
        let cap = |c: &SkillCtx, ceiling: f32| s.heed_capacity(c, ceiling).expect("the law runs");
        // An untrained, rested, unhurt adult.
        assert_eq!(cap(&person("adult"), 32.0), 10);
        // Long practice at `watch`: knack 1.0 × 1.6.
        let mut practised = person("adult");
        practised.actor.practice.insert("watch".into(), 100_000);
        assert_eq!(cap(&practised, 32.0), 16);
        // … and the technique: 20, clamped to the ceiling.
        practised.actor.knows = vec!["keeping_watch".into()];
        assert_eq!(cap(&practised, 32.0), 20);
        assert_eq!(cap(&practised, 16.0), 16);
        // An inborn knack counts too.
        let mut keen = person("adult");
        keen.actor.genes.insert("knack:watch".into(), 1.2);
        assert_eq!(cap(&keen, 32.0), 12);
        // Badly hurt and exhausted: 10 × 0.6 × 0.6; out of breath too: × 0.85.
        let mut worn = person("adult");
        worn.actor.hp = 0.1;
        worn.actor.energy = 10.0;
        assert_eq!(cap(&worn, 32.0), 3);
        worn.actor.stamina = 5.0;
        assert_eq!(cap(&worn, 32.0), 3);
        // Tired (energy below 35: × 0.8) and badly hurt (hp 1, below a quarter of any kind's
        // health: × 0.6): 4.8.
        let mut tired = person("adult");
        tired.actor.energy = 30.0;
        tired.actor.hp = 1.0;
        assert_eq!(cap(&tired, 32.0), 4);
        // Life stages and kinds.
        assert_eq!(cap(&person("child"), 32.0), 7);
        assert_eq!(cap(&person("elder"), 32.0), 9);
        assert_eq!(cap(&person("infant"), 32.0), 3);
        let mut wolf = person("adult");
        wolf.actor.kind = "wolf".into();
        assert_eq!(cap(&wolf, 32.0), 8);
        wolf.actor.kind = "deer".into();
        assert_eq!(cap(&wolf, 32.0), 6);
        // Never below 1 before the clamp, and the ceiling clamps to 0 when the world says so.
        let mut infant = person("infant");
        infant.actor.hp = 0.1;
        infant.actor.energy = 5.0;
        assert_eq!(cap(&infant, 32.0), 1);
        assert_eq!(cap(&person("adult"), 0.0), 0);
    }

    #[test]
    fn a_script_without_the_law_says_so() {
        let s = Scripts::new(&SHIPPED.replace("fn heed_capacity(a)", "fn heed_capacity_old(a)")).expect("compiles");
        assert!(s.heed_capacity(&person("adult"), 16.0).unwrap_err().contains("no heed_capacity law"));
    }

    #[test]
    fn the_experiments_overlay_installs_and_widens_capacity() {
        let src = crate::floors::compose(SHIPPED, OVERLAY).expect("composes");
        let s = Scripts::new(&src).expect("compiles");
        s.validate().expect("installs");
        assert!(s.skills().names().any(|n| n == "watch"), "the overlay adds the watch skill");
        assert!(s.tables().names("know_how").iter().any(|n| n == "keeping_watch"), "and the keeping_watch technique");
        // The shipped script has neither.
        let shipped = Scripts::new(SHIPPED).unwrap();
        assert!(!shipped.skills().names().any(|n| n == "watch"));
        assert!(!shipped.tables().names("know_how").iter().any(|n| n == "keeping_watch"));
        let mut c = person("adult");
        c.actor.knows = vec!["keeping_watch".into()];
        assert_eq!(s.heed_capacity(&c, 32.0).unwrap(), 14);
    }
}
