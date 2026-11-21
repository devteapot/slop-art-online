//! A body's meters and statuses: one law for players' screens and minds' words
//! (docs/INTERFACE.md, "Declarations that are not skills"; docs/WORLD_RULES.md, "Meters and
//! statuses").
//!
//! - **`meters()`** lists the bars a body has. Each row names fields of the `my_vitals` row:
//!   `#{ name: "health", value: "hp", max: "max_hp", order: 0 }`, `max` a field or a number, and
//!   `shown: false` for a meter the screen leaves out (it still bounds its value), `while_short:
//!   true` for one the screen shows only while it is not full (a pool that is mostly full). Nothing here
//!   lists the vitals: a world that adds one (a column at the end of `vitals`) adds its row.
//! - **`status_of(a)`** says how the body is: a list of `#{ name, tone, text }`, with optional
//!   `meter` (the meter it speaks of), `felt` (a mind's words for it), and an alarm told once per
//!   episode (`alarm`, `salience`, `think`: always, no_food or never, `routine`: the want whose
//!   routine is shown when it asks the mind to think). Its `a` is the body, not a skill's
//!   context: every numeric field of the vitals row by name, as it stands now (a field with a
//!   `<field>_rate` moved along it since `at_ms`, held within its meter; a pool, a field with a
//!   `<field>_from_ms`, moves by its rate a second from the later of `at_ms` and that time,
//!   docs/STAMINA.md), each `<x>_ms` time as
//!   `<x>_ago_s` (whole seconds, at most an hour; -1 never), `share` (each meter's value over
//!   its max, by meter name), `kind`, `stage` and `night`.
//!
//! - **`status_parts()`** (optional) names the functions `status_of` is made of, in order: each
//!   takes the same body and returns a list of its statuses, and `status_of` is their join. The
//!   engine keeps each part's answer on what that part reads (`fields::Fields`) and joins them, so
//!   a change of one fact asks again only the parts that read it (docs/STATUS_PARTS.md). The
//!   install refuses parts that do not join to `status_of`; the authority's `status_parts` law
//!   (off: whole) and `status_parts_check` (a diagnostic that compares every ask) switch it.
//!
//! The authority's bodily alarms, the mind service's body words and the game client's pills
//! all read `status_of`: one set of thresholds. Values reach the law rounded (whole numbers,
//! rates to a hundredth), so bodies in the same state share one answer (kept per state).

use super::Scripts;
use rhai::{Array, Dynamic, Map, Scope};
use std::cell::RefCell;
use std::collections::{BTreeSet, HashMap};
use std::rc::Rc;

/// How a status reads (append-only).
pub const TONES: [&str; 4] = ["good", "warn", "bad", "plain"];
/// When an alarm asks the mind to think (append-only).
pub const THINKS: [&str; 3] = ["always", "no_food", "never"];
/// Keys of a `status_of` entry.
const STATUS_KEYS: [&str; 9] = ["name", "tone", "text", "meter", "felt", "alarm", "salience", "think", "routine"];
/// Keys of a `meters()` row.
const METER_KEYS: [&str; 7] = ["name", "value", "max", "order", "label", "shown", "while_short"];
/// Fields of a vitals row that are not facts of the body: ids, the anchor and the rates' cache key.
const NOT_FACTS: [&str; 3] = ["id", "at_ms", "rate_key"];
/// A time ago is told up to this many seconds (beyond, all one state).
const AGO_MAX_S: f64 = 120.0;
/// States kept before the memo starts over.
const KEPT: usize = 4096;
/// The most parts `status_parts()` may name.
pub const MAX_PARTS: usize = 16;
/// Distinct answers kept per part before its memo starts over.
const ANSWERS_KEPT: usize = 256;
/// Differences `status_parts_check` keeps in words until they are taken.
const DIFFERENCES_KEPT: usize = 8;

/// How the authority asks `status_of` (its `status_parts` and `status_parts_check` laws). The
/// default, for the mind service and clients, goes by the parts with no check.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct StatusWay {
    /// By the parts the script declares (`status_parts()`); false: the whole law (the rollback).
    pub parts: bool,
    /// A diagnostic: every ask by the parts is also asked of the whole law with the whole body,
    /// the two compared (`calls::STATUS_CHECKED`, `calls::STATUS_DIFFERED`), and the whole law's
    /// answer given where they differ.
    pub check: bool,
}

impl Default for StatusWay {
    fn default() -> Self {
        StatusWay { parts: true, check: false }
    }
}

/// What one part of `status_of` reads of the body (`fields::Fields`), worked out once.
#[derive(Debug, Default)]
struct PartPlan {
    kind: bool,
    stage: bool,
    night: bool,
    /// Facts by name, in order of name.
    fields: Vec<String>,
    /// Meters whose share it reads, in order of name.
    shares: Vec<String>,
}

/// One declared part of `status_of` (`status_parts()`) and its memo: each answer it gave once,
/// and the answer's index by the values of what it reads.
struct Part {
    name: String,
    /// None: it reads the body whole or by computed names, and is kept on all of it.
    plan: Option<PartPlan>,
    memo: RefCell<HashMap<Vec<u8>, u32>>,
    answers: RefCell<Vec<Rc<Vec<Status>>>>,
}

impl Part {
    /// The values of what it reads, as a key: a byte for present or not and each value, in the
    /// plan's order (one plan per part, so no names).
    fn key(&self, b: &BodyFacts, k: &mut Vec<u8>) {
        let Some(p) = &self.plan else {
            k.extend(b.key());
            return;
        };
        if p.kind {
            k.extend(b.kind.as_bytes());
            k.push(0);
        }
        if p.stage {
            k.extend(b.stage.as_bytes());
            k.push(0);
        }
        if p.night {
            k.push(b.night as u8);
        }
        let mut put = |v: Option<f64>| match v {
            Some(v) => {
                k.push(1);
                k.extend(v.to_le_bytes());
            },
            None => k.push(0),
        };
        for f in &p.fields {
            put(b.get(f));
        }
        for m in &p.shares {
            put(b.share.iter().find(|(n, _)| n == m).map(|(_, v)| *v));
        }
    }

    /// The body as the part is called with it: what it reads alone (as a skill's check is
    /// given its plan's fields), or all of it.
    fn map(&self, b: &BodyFacts) -> Map {
        let Some(p) = &self.plan else { return b.map() };
        let mut m = Map::new();
        for f in &p.fields {
            if let Some(v) = b.get(f) {
                m.insert(f.as_str().into(), Dynamic::from_float(v));
            }
        }
        if !p.shares.is_empty() {
            let mut share = Map::new();
            for n in &p.shares {
                if let Some((_, v)) = b.share.iter().find(|(k, _)| k == n) {
                    share.insert(n.as_str().into(), Dynamic::from_float(*v));
                }
            }
            m.insert("share".into(), share.into());
        }
        if p.kind {
            m.insert("kind".into(), b.kind.clone().into());
        }
        if p.stage {
            m.insert("stage".into(), b.stage.clone().into());
        }
        if p.night {
            m.insert("night".into(), b.night.into());
        }
        m
    }
}

/// The parts `status_of` is declared in, their memos and the joined answers.
struct Parts {
    list: Vec<Part>,
    /// What is wrong with the declaration (an install refuses it; asks go to the whole law).
    errors: Vec<String>,
    /// The joined answer by the parts' answers (their indices, in order).
    joined: RefCell<HashMap<Vec<u32>, Rc<Vec<Status>>>>,
    /// What the parts read together, with the fields each share is made of (for
    /// `BodyFacts::next_change_ms`); None when one reads the body whole.
    reads: Option<Rc<BTreeSet<String>>>,
    /// The key of the part being asked, reused.
    key: RefCell<Vec<u8>>,
}

/// What bounds a meter: another field of the row, or a number.
#[derive(Clone, Debug, PartialEq)]
pub enum MeterMax {
    Field(String),
    Value(f64),
}

/// One bar of a body (`meters()`).
#[derive(Clone, Debug, PartialEq)]
pub struct Meter {
    pub name: String,
    /// The `my_vitals` field it shows.
    pub value: String,
    pub max: MeterMax,
    pub order: i32,
    /// Its words on screen (default: the name, capitalised).
    pub label: String,
    /// Drawn as a bar (false: it only bounds its value and feeds statuses).
    pub shown: bool,
    /// Drawn only while its value is below its max (a pool that is mostly full: focus).
    pub while_short: bool,
}

impl Meter {
    /// Its max for a row's fields.
    pub fn max_of(&self, fields: &[(String, f64)]) -> Option<f64> {
        match &self.max {
            MeterMax::Value(v) => Some(*v),
            MeterMax::Field(f) => fields.iter().find(|(k, _)| k == f).map(|(_, v)| *v),
        }
    }
}

/// When an alarm asks the mind to think.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Think {
    Always,
    /// Only when the body carries no food.
    NoFood,
    Never,
}

/// An alarm: told to the body's mind once each time the status begins.
#[derive(Clone, Debug, PartialEq)]
pub struct Alarm {
    pub text: String,
    pub salience: f32,
    pub think: Think,
    /// The want whose routine is quoted when it asks the mind to think (empty: none).
    pub routine: String,
}

/// How a body is (`status_of`).
#[derive(Clone, Debug, PartialEq)]
pub struct Status {
    pub name: String,
    /// One of [`TONES`].
    pub tone: String,
    /// Short words for a screen.
    pub text: String,
    /// The meter it speaks of (empty: none).
    pub meter: String,
    /// A mind's words for it (empty: it is not felt as words).
    pub felt: String,
    pub alarm: Option<Alarm>,
}

/// A body as `status_of` reads it.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct BodyFacts {
    pub kind: String,
    pub stage: String,
    pub night: bool,
    /// Each fact by name, as it stands now and rounded (see the module).
    pub fields: Vec<(String, f64)>,
    /// Each meter's value over its max.
    pub share: Vec<(String, f64)>,
}

impl BodyFacts {
    /// A body from a vitals row's numeric fields by name (`raw`: any row; the client and the
    /// mind service read theirs generically from `my_vitals`/`vitals`), projected to `now_ms`
    /// along each `<field>_rate` (per minute since `at_ms`) and held within its meter.
    pub fn of(kind: &str, stage: &str, night: bool, raw: &[(String, f64)], meters: &[Meter], now_ms: u64) -> BodyFacts {
        let get = |k: &str| raw.iter().find(|(n, _)| n == k).map(|(_, v)| *v);
        let at = get("at_ms").unwrap_or(now_ms as f64);
        let minutes = ((now_ms as f64 - at) / 60_000.0).max(0.0);
        let mut fields: Vec<(String, f64)> = Vec::new();
        for (k, v) in raw {
            if NOT_FACTS.contains(&k.as_str()) || k.ends_with("_by") {
                continue;
            }
            if let Some(t) = k.strip_suffix("_ms") {
                let ago = if *v <= 0.0 { -1.0 } else { ((now_ms as f64 - v) / 1000.0).clamp(0.0, AGO_MAX_S).floor() };
                fields.push((format!("{t}_ago_s"), ago));
                continue;
            }
            if k.ends_with("_rate") {
                fields.push((k.clone(), (v * 100.0).round() / 100.0));
                continue;
            }
            let rate = get(&format!("{k}_rate")).unwrap_or(0.0);
            // A pool (`<field>_from_ms`): its rate is a second's, from the later of the anchor
            // and its start (`living_rules::pools::level`).
            let mut x = match get(&format!("{k}_from_ms")) {
                Some(from) => v + rate * ((now_ms as f64 - from.max(at)) / 1000.0).max(0.0),
                None => v + rate * minutes,
            };
            if rate != 0.0 {
                let max = meters.iter().find(|m| m.value == *k).and_then(|m| m.max_of(raw));
                x = x.max(0.0).min(max.unwrap_or(f64::MAX));
            }
            fields.push((k.clone(), x.round()));
        }
        let share = meters
            .iter()
            .filter_map(|m| {
                let v = fields.iter().find(|(k, _)| *k == m.value)?.1;
                let max = m.max_of(&fields)?;
                Some((m.name.clone(), if max > 0.0 { ((v / max) * 100.0).round() / 100.0 } else { 0.0 }))
            })
            .collect();
        BodyFacts { kind: kind.into(), stage: stage.into(), night, fields, share }
    }

    pub fn get(&self, k: &str) -> Option<f64> {
        self.fields.iter().find(|(n, _)| n == k).map(|(_, v)| *v)
    }

    /// The first time after `now_ms`, the row `raw` unchanged, at which a fact `reads` names may
    /// read differently from now (docs/BATTLE_SCALE.md, battle-cheap path 2): a rounded level
    /// crossing its next half, a whole second more since a `_ms` stamp. Never later than the
    /// change, sometimes a millisecond early; `u64::MAX` when none can change. `reads`: the facts
    /// `status_of` reads (`Scripts::status_reads`), every fact when `None`.
    pub fn next_change_ms(raw: &[(String, f64)], meters: &[Meter], now_ms: u64, reads: Option<&BTreeSet<String>>) -> u64 {
        let get = |k: &str| raw.iter().find(|(n, _)| n == k).map(|(_, v)| *v);
        let at = get("at_ms").unwrap_or(now_ms as f64);
        let now = now_ms as f64;
        let read = |name: &str| reads.is_none_or(|r| r.contains(name));
        let mut next = f64::INFINITY;
        for (k, v) in raw {
            if NOT_FACTS.contains(&k.as_str()) || k.ends_with("_by") || k.ends_with("_rate") {
                continue;
            }
            if let Some(t) = k.strip_suffix("_ms") {
                if !read(&format!("{t}_ago_s")) || *v <= 0.0 {
                    continue;
                }
                // floor((now - v) / 1000), clamped to [0, AGO_MAX_S]: the next whole second.
                let ago = ((now - v) / 1000.0).floor();
                if ago < AGO_MAX_S {
                    next = next.min(v + (ago.max(0.0) + 1.0) * 1000.0);
                }
                continue;
            }
            if !read(k) {
                continue;
            }
            let rate = get(&format!("{k}_rate")).unwrap_or(0.0);
            if rate == 0.0 {
                continue;
            }
            // The level as `of` projects it: per second from a pool's start, else per minute.
            let (start, per_ms) = match get(&format!("{k}_from_ms")) {
                Some(from) => (from.max(at), rate / 1000.0),
                None => (at, rate / 60_000.0),
            };
            let x_at = |t: f64| v + per_ms * (t - start).max(0.0);
            let max = meters.iter().find(|m| m.value == *k).and_then(|m| m.max_of(raw)).unwrap_or(f64::MAX);
            let x = x_at(now).max(0.0).min(max);
            let r = x.round();
            // The level at which the rounded value changes, in the direction it moves.
            let edge = if per_ms > 0.0 { r + 0.5 } else { r - 0.5 };
            if (per_ms > 0.0 && edge > max) || (per_ms < 0.0 && edge < 0.0) {
                continue;
            }
            let t = start.max(now) + (edge - x_at(start.max(now))) / per_ms;
            next = next.min(t.max(now));
        }
        if !next.is_finite() {
            return u64::MAX;
        }
        // A millisecond early, never late.
        ((next - 1.0).floor().max(now + 1.0)) as u64
    }

    pub(super) fn map_for_check(&self) -> Map {
        self.map()
    }

    fn map(&self) -> Map {
        let mut m = Map::new();
        for (k, v) in &self.fields {
            m.insert(k.as_str().into(), Dynamic::from_float(*v));
        }
        let mut share = Map::new();
        for (k, v) in &self.share {
            share.insert(k.as_str().into(), Dynamic::from_float(*v));
        }
        m.insert("share".into(), share.into());
        m.insert("kind".into(), self.kind.clone().into());
        m.insert("stage".into(), self.stage.clone().into());
        m.insert("night".into(), self.night.into());
        m
    }

    /// `key`, of the facts and shares `reads` names alone (`Scripts::status_reads`): the law is a
    /// function of what it reads, so two bodies that agree on those get the same statuses.
    fn key_reading(&self, reads: &BTreeSet<String>) -> Vec<u8> {
        let mut k = Vec::with_capacity(16 + reads.len() * 8);
        k.extend(self.kind.as_bytes());
        k.push(0);
        k.extend(self.stage.as_bytes());
        k.push(self.night as u8);
        for (n, v) in self.fields.iter().filter(|(n, _)| reads.contains(n)) {
            k.extend(n.as_bytes());
            k.extend(v.to_le_bytes());
        }
        for (n, v) in &self.share {
            if reads.contains(&format!("share.{n}")) {
                k.extend(n.as_bytes());
                k.extend(v.to_le_bytes());
            }
        }
        k
    }

    /// The values of the facts `reads` names alone, `kind`, `stage` and `night` only when named:
    /// two bodies with the same key get the same answer from a law that reads only those.
    pub(super) fn key_of_reads(&self, reads: &BTreeSet<String>) -> Vec<u8> {
        let mut k = Vec::with_capacity(16 + reads.len() * 9);
        if reads.contains("kind") {
            k.extend(self.kind.as_bytes());
        }
        k.push(0);
        if reads.contains("stage") {
            k.extend(self.stage.as_bytes());
        }
        k.push(0);
        k.push(if reads.contains("night") { self.night as u8 } else { 2 });
        for (n, v) in self.fields.iter().filter(|(n, _)| reads.contains(n)) {
            k.extend(n.as_bytes());
            k.push(0);
            k.extend(v.to_le_bytes());
        }
        for (n, v) in &self.share {
            if reads.contains(&format!("share.{n}")) {
                k.extend(n.as_bytes());
                k.push(1);
                k.extend(v.to_le_bytes());
            }
        }
        k
    }

    fn key(&self) -> Vec<u8> {
        let mut k = Vec::with_capacity(16 + self.fields.len() * 8);
        k.extend(self.kind.as_bytes());
        k.push(0);
        k.extend(self.stage.as_bytes());
        k.push(self.night as u8);
        for (_, v) in &self.fields {
            k.extend(v.to_le_bytes());
        }
        k
    }
}

/// The script's meters and the memo of its statuses.
#[derive(Default)]
pub(super) struct Body {
    pub meters: Vec<Meter>,
    pub errors: Vec<String>,
    memo: RefCell<HashMap<Vec<u8>, Rc<Vec<Status>>>>,
    /// What `status_of` reads, worked out once (`Scripts::status_reads`).
    reads: RefCell<Option<Option<Rc<BTreeSet<String>>>>>,
    /// The parts it is declared in (`status_parts()`); None: asked whole.
    parts: Option<Parts>,
    /// Differences `status_parts_check` found, in words, until taken.
    differed: RefCell<Vec<String>>,
}

/// The meters when the script declares none: health and energy, as the client drew them.
pub fn default_meters() -> Vec<Meter> {
    vec![
        Meter { name: "health".into(), value: "hp".into(), max: MeterMax::Field("max_hp".into()), order: 0, label: "Health".into(), shown: true, while_short: false },
        Meter { name: "energy".into(), value: "energy".into(), max: MeterMax::Value(100.0), order: 1, label: "Energy".into(), shown: true, while_short: false },
    ]
}

fn capitalised(s: &str) -> String {
    let mut c = s.chars();
    c.next().map_or(String::new(), |f| f.to_uppercase().collect::<String>() + c.as_str()).replace('_', " ")
}

/// `meters()` read into rows; errors name the row.
fn read_meters(d: Dynamic) -> (Vec<Meter>, Vec<String>) {
    let mut out: Vec<Meter> = Vec::new();
    let mut errors = Vec::new();
    let Some(rows) = d.try_cast::<Array>() else { return (default_meters(), vec!["meters: must return a list of maps".into()]) };
    for (i, r) in rows.into_iter().enumerate() {
        let Some(m) = r.try_cast::<Map>() else {
            errors.push(format!("meters: row {i} is not a map"));
            continue;
        };
        if let Some(k) = m.keys().find(|k| !METER_KEYS.contains(&k.as_str())) {
            errors.push(format!("meters: row {i}: unknown key '{k}' (keys are {})", METER_KEYS.join(", ")));
        }
        let text = |k: &str| m.get(k).and_then(|v| v.clone().into_string().ok());
        let Some(name) = text("name").filter(|n| !n.is_empty()) else {
            errors.push(format!("meters: row {i} needs a `name`"));
            continue;
        };
        let Some(value) = text("value").filter(|n| !n.is_empty()) else {
            errors.push(format!("meters: `{name}` needs `value`, the my_vitals field it shows"));
            continue;
        };
        let max = match m.get("max") {
            Some(v) if v.is_string() => MeterMax::Field(v.clone().into_string().unwrap_or_default()),
            Some(v) => match super::number(v) {
                Some(x) if x > 0.0 => MeterMax::Value(x),
                _ => {
                    errors.push(format!("meters: `{name}`: `max` is a my_vitals field or a number above 0"));
                    continue;
                }
            },
            None => {
                errors.push(format!("meters: `{name}` needs `max`, a my_vitals field or a number"));
                continue;
            }
        };
        let order = m.get("order").and_then(|v| v.as_int().ok()).unwrap_or(out.len() as i64) as i32;
        let shown = m.get("shown").and_then(|v| v.as_bool().ok()).unwrap_or(true);
        let while_short = m.get("while_short").and_then(|v| v.as_bool().ok()).unwrap_or(false);
        if out.iter().any(|o| o.name == name) {
            errors.push(format!("meters: `{name}` is declared twice"));
            continue;
        }
        out.push(Meter { label: text("label").unwrap_or_else(|| capitalised(&name)), name, value, max, order, shown, while_short });
    }
    out.sort_by_key(|m| m.order);
    (out, errors)
}

pub(super) fn read_status(d: Dynamic) -> Result<Vec<Status>, String> {
    let list = d.try_cast::<Array>().ok_or("status_of must return a list of #{ name, tone, text }")?;
    list.into_iter()
        .map(|e| {
            let m = e.try_cast::<Map>().ok_or("status_of: each status is a map #{ name, tone, text }")?;
            if let Some(k) = m.keys().find(|k| !STATUS_KEYS.contains(&k.as_str())) {
                return Err(format!("status_of: unknown key '{k}' (keys are {})", STATUS_KEYS.join(", ")));
            }
            let text = |k: &str| -> Result<String, String> {
                match m.get(k) {
                    None => Ok(String::new()),
                    Some(v) => v.clone().into_string().map_err(|_| format!("status_of: `{k}` must be text")),
                }
            };
            let name = text("name")?;
            if name.is_empty() {
                return Err("status_of: a status needs a `name`".into());
            }
            let tone = text("tone")?;
            if !TONES.contains(&tone.as_str()) {
                return Err(format!("status_of: `{name}`: tone '{tone}' is not one of {}", TONES.join(", ")));
            }
            let shown = text("text")?;
            if shown.is_empty() {
                return Err(format!("status_of: `{name}` needs a `text`"));
            }
            let alarm = text("alarm")?;
            let alarm = if alarm.is_empty() {
                None
            } else {
                let think = match text("think")?.as_str() {
                    "" | "never" => Think::Never,
                    "always" => Think::Always,
                    "no_food" => Think::NoFood,
                    t => return Err(format!("status_of: `{name}`: think '{t}' is not one of {}", THINKS.join(", "))),
                };
                let salience = m.get("salience").map(|v| super::number(v).ok_or(format!("status_of: `{name}`: salience must be a number"))).transpose()?.unwrap_or(0.5) as f32;
                Some(Alarm { text: alarm, salience: salience.clamp(0.0, 1.0), think, routine: text("routine")? })
            };
            Ok(Status { name, tone, text: shown, meter: text("meter")?, felt: text("felt")?, alarm })
        })
        .collect()
}

impl Scripts {
    /// `whole_only`: the script's own `status_of` came without its own `status_parts` while the
    /// rest of the shipped script was merged under it (`Scripts::with_day`): its law is asked
    /// whole, so the shipped parts never stand in for it.
    pub(super) fn read_body(&self, whole_only: bool) -> Body {
        let (meters, errors) = if self.nullary.contains("meters") {
            match self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "meters", ()) {
                Ok(d) => read_meters(d),
                Err(e) => (default_meters(), vec![format!("meters: {e}")]),
            }
        } else {
            (default_meters(), Vec::new())
        };
        let parts = if whole_only { None } else { self.read_parts(&meters) };
        Body { meters, errors, memo: Default::default(), reads: Default::default(), parts, differed: Default::default() }
    }

    /// `status_parts()`, its names checked and each part's reads worked out.
    fn read_parts(&self, meters: &[Meter]) -> Option<Parts> {
        if !self.nullary.contains("status_parts") {
            return None;
        }
        let mut errors = Vec::new();
        let mut names: Vec<String> = Vec::new();
        match self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "status_parts", ()) {
            Err(e) => errors.push(format!("status_parts: {e}")),
            Ok(d) => match d.try_cast::<Array>() {
                None => errors.push("status_parts: must return a list of the names of its parts".into()),
                Some(list) => {
                    for (i, v) in list.into_iter().enumerate() {
                        match v.into_string() {
                            Err(_) => errors.push(format!("status_parts: entry {i} is not a function's name")),
                            Ok(n) if n == "status_of" || n == "status_parts" => errors.push(format!("status_parts: `{n}` cannot be one of its parts")),
                            Ok(n) if !self.unary.contains(&n) => errors.push(format!("status_parts: `{n}` is not a function of one parameter (the body) in the script")),
                            Ok(n) if names.contains(&n) => errors.push(format!("status_parts: `{n}` is named twice")),
                            Ok(n) => names.push(n),
                        }
                    }
                },
            },
        }
        if !self.unary.contains("status_of") {
            errors.push("status_parts: the script has no `status_of(a)`, the parts' reference".into());
        }
        if names.is_empty() && errors.is_empty() {
            errors.push("status_parts: names no part".into());
        }
        if names.len() > MAX_PARTS {
            errors.push(format!("status_parts: names {} parts (at most {MAX_PARTS})", names.len()));
        }
        let list: Vec<Part> = names.into_iter().map(|name| Part { plan: self.part_plan(&name, meters), name, memo: Default::default(), answers: Default::default() }).collect();
        let mut reads = Some(BTreeSet::new());
        for p in &list {
            let (Some(r), Some(plan)) = (reads.as_mut(), p.plan.as_ref()) else {
                reads = None;
                break;
            };
            r.extend(plan.fields.iter().cloned());
            for (on, k) in [(plan.kind, "kind"), (plan.stage, "stage"), (plan.night, "night")] {
                if on {
                    r.insert(k.to_string());
                }
            }
            for n in &plan.shares {
                let m = meters.iter().find(|m| m.name == *n).expect("part_plan: shares are meters");
                r.insert(format!("share.{n}"));
                r.insert(m.value.clone());
                if let MeterMax::Field(f) = &m.max {
                    r.insert(f.clone());
                }
            }
        }
        Some(Parts { list, errors, joined: Default::default(), reads: reads.map(Rc::new), key: Default::default() })
    }

    /// What part `name` reads of the body; None when it reads it whole, by computed names, or
    /// the share of a meter there is not.
    fn part_plan(&self, name: &str, meters: &[Meter]) -> Option<PartPlan> {
        let u = self.fields.of(name, 1)?.first()?;
        if u.all || !u.by_param.is_empty() {
            return None;
        }
        let mut p = PartPlan::default();
        for (k, sub) in &u.keys {
            match k.as_str() {
                "kind" => p.kind = true,
                "stage" => p.stage = true,
                "night" => p.night = true,
                "share" => {
                    if sub.all || !sub.by_param.is_empty() {
                        return None;
                    }
                    for n in sub.keys.keys() {
                        meters.iter().find(|m| m.name == *n)?;
                        p.shares.push(n.clone());
                    }
                },
                _ => p.fields.push(k.clone()),
            }
        }
        Some(p)
    }

    /// The body's meters (`meters()`, else health and energy), in their order.
    pub fn meters(&self) -> &[Meter] {
        &self.body.meters
    }

    /// What is wrong with `meters()` (an install refuses it).
    pub fn meter_errors(&self) -> &[String] {
        &self.body.errors
    }

    /// Meters that name a field the vitals row does not have (`fields`: the row's columns, as
    /// the authority knows them).
    pub fn meters_unknown(&self, fields: &[&str]) -> Vec<String> {
        let mut out = Vec::new();
        for m in self.meters() {
            if !fields.contains(&m.value.as_str()) {
                out.push(format!("meters: `{}` shows '{}', which is not a my_vitals field ({})", m.name, m.value, fields.join(", ")));
            }
            if let MeterMax::Field(f) = &m.max {
                if !fields.contains(&f.as_str()) {
                    out.push(format!("meters: `{}`'s max '{f}' is not a my_vitals field ({})", m.name, fields.join(", ")));
                }
            }
        }
        out
    }

    /// How a body is (`status_of(a)`), kept per state; none when the script has no such law.
    /// By its parts (`status_parts()`) when the script declares them, else whole.
    pub fn status_of(&self, b: &BodyFacts) -> Result<Rc<Vec<Status>>, String> {
        self.status_of_profiled(b, StatusWay::default(), |_| ())
    }

    /// [`Self::status_of`] the way `way` says (the authority's `status_parts` and
    /// `status_parts_check` laws), timing its steps with caller-provided guards
    /// (`status.lookup`, `status.miss`, `status.rhai`, `status.check`).
    pub fn status_of_profiled<T>(&self, b: &BodyFacts, way: StatusWay, span: impl Fn(&str) -> T) -> Result<Rc<Vec<Status>>, String> {
        if !self.unary.contains("status_of") {
            return Ok(Rc::new(Vec::new()));
        }
        super::calls::note(super::calls::STATUS_ASKED);
        if !self.uses_parts(way) {
            return self.status_whole(b, &span);
        }
        let s = self.status_by_parts(b, &span)?;
        if way.check {
            // The reference, asked afresh of the whole law with the whole body: no memo, no plan.
            let _check = span("status.check");
            super::calls::note(super::calls::STATUS_CHECKED);
            let whole = self.status_fresh(b)?;
            if whole != *s {
                super::calls::note(super::calls::STATUS_DIFFERED);
                let names = |v: &[Status]| v.iter().map(|x| x.name.as_str()).collect::<Vec<_>>().join(", ");
                let mut told = self.body.differed.borrow_mut();
                if told.len() < DIFFERENCES_KEPT {
                    told.push(format!("the parts gave [{}] where status_of gives [{}] for a {} {}{} ({})", names(&s), names(&whole), b.stage, b.kind, if b.night { " at night" } else { "" }, b.fields.iter().map(|(k, v)| format!("{k} {v}")).collect::<Vec<_>>().join(", ")));
                }
                return Ok(Rc::new(whole));
            }
        }
        Ok(s)
    }

    /// Whether an ask the way `way` says goes by the parts: the script declares them well, and
    /// `way` does not ask for the whole law.
    pub fn uses_parts(&self, way: StatusWay) -> bool {
        way.parts && self.body.parts.as_ref().is_some_and(|p| p.errors.is_empty())
    }

    /// The whole law, kept on what it reads (the way before `status_parts`, and its rollback).
    fn status_whole<T>(&self, b: &BodyFacts, span: &impl Fn(&str) -> T) -> Result<Rc<Vec<Status>>, String> {
        let lookup = span("status.lookup");
        let key = match self.status_reads() {
            Some(r) => b.key_reading(&r),
            None => b.key(),
        };
        if let Some(s) = self.body.memo.borrow().get(&key) {
            super::calls::note(super::calls::STATUS_MEMO);
            return Ok(s.clone());
        }
        drop(lookup);
        let _miss = span("status.miss");
        super::calls::note(super::calls::STATUS_RUN);
        let s = {
            let _rhai = span("status.rhai");
            Rc::new(self.status_fresh(b)?)
        };
        let mut memo = self.body.memo.borrow_mut();
        if memo.len() >= KEPT {
            memo.clear();
        }
        memo.insert(key, s.clone());
        Ok(s)
    }

    /// `status_of(a)` run on the whole body, kept nowhere.
    fn status_fresh(&self, b: &BodyFacts) -> Result<Vec<Status>, String> {
        let d = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "status_of", (b.map(),)).map_err(|e| format!("status_of: {e}"))?;
        read_status(d)
    }

    /// The parts' answers joined in their order, each part's kept on what it reads.
    fn status_by_parts<T>(&self, b: &BodyFacts, span: &impl Fn(&str) -> T) -> Result<Rc<Vec<Status>>, String> {
        let parts = self.body.parts.as_ref().expect("uses_parts");
        let _all = span("status.parts");
        super::calls::note(super::calls::PARTS_ASKED);
        let mut ids = [0u32; MAX_PARTS];
        let n = parts.list.len();
        let mut key = parts.key.borrow_mut();
        for (i, part) in parts.list.iter().enumerate() {
            key.clear();
            part.key(b, &mut key);
            let found = part.memo.borrow().get(key.as_slice()).copied();
            ids[i] = match found {
                Some(id) => {
                    super::calls::note(super::calls::PART_MEMO);
                    id
                },
                None => {
                    let _miss = span("status.miss");
                    super::calls::note(super::calls::PART_RUN);
                    super::calls::note(super::calls::PART_RUN_BY + i.min(MAX_PARTS - 1));
                    let d = {
                        let _rhai = span("status.rhai");
                        self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, &part.name, (part.map(b),)).map_err(|e| format!("{}: {e}", part.name))?
                    };
                    let answer = read_status(d).map_err(|e| e.replacen("status_of", &part.name, 1))?;
                    let mut answers = part.answers.borrow_mut();
                    let id = match answers.iter().position(|a| **a == answer) {
                        Some(id) => id as u32,
                        None => {
                            if answers.len() >= ANSWERS_KEPT {
                                // The ids name answers in the joined memo: both start over.
                                answers.clear();
                                part.memo.borrow_mut().clear();
                                parts.joined.borrow_mut().clear();
                            }
                            answers.push(Rc::new(answer));
                            (answers.len() - 1) as u32
                        },
                    };
                    let mut memo = part.memo.borrow_mut();
                    if memo.len() >= KEPT {
                        memo.clear();
                    }
                    memo.insert(key.clone(), id);
                    id
                },
            };
        }
        drop(key);
        let ids = &ids[..n];
        if let Some(s) = parts.joined.borrow().get(ids) {
            super::calls::note(super::calls::PARTS_JOINED);
            return Ok(s.clone());
        }
        let mut out = Vec::new();
        for (part, id) in parts.list.iter().zip(ids) {
            out.extend(part.answers.borrow()[*id as usize].iter().cloned());
        }
        let s = Rc::new(out);
        let mut joined = parts.joined.borrow_mut();
        if joined.len() >= KEPT {
            joined.clear();
        }
        joined.insert(ids.to_vec(), s.clone());
        Ok(s)
    }

    /// The differences `status_parts_check` found since the last take (at most a few, in words),
    /// cleared: for the caller to log.
    pub fn take_status_differences(&self) -> Vec<String> {
        std::mem::take(&mut *self.body.differed.borrow_mut())
    }

    /// The parts the script declares (`status_parts()`), in their order: empty when it declares
    /// none.
    pub fn status_part_names(&self) -> Vec<String> {
        self.body.parts.as_ref().map(|p| p.list.iter().map(|x| x.name.clone()).collect()).unwrap_or_default()
    }

    /// Whether `status_of` is written as its declared parts joined in order (`hunger_part(a) +
    /// energy_part(a) + …`, as shipped): then the parts joined are the law by construction, and
    /// the install need not run the law on every sample to compare (`check.rs` `body`).
    pub fn status_of_is_join(&self) -> bool {
        let names = self.status_part_names();
        !names.is_empty() && super::fields::is_join(&self.ast, "status_of", &names)
    }

    /// What is wrong with `status_parts()` (an install refuses it; the whole law answers).
    pub fn status_parts_errors(&self) -> &[String] {
        self.body.parts.as_ref().map(|p| p.errors.as_slice()).unwrap_or(&[])
    }

    /// What one part reads (`BodyFacts` field names, `share.<meter>`, `kind`, `stage`,
    /// `night`); `None` when it reads the body whole or is not a part.
    pub fn status_part_reads(&self, name: &str) -> Option<BTreeSet<String>> {
        let p = self.body.parts.as_ref()?.list.iter().find(|p| p.name == name)?;
        let plan = p.plan.as_ref()?;
        let mut out: BTreeSet<String> = plan.fields.iter().cloned().collect();
        out.extend(plan.shares.iter().map(|s| format!("share.{s}")));
        for (on, k) in [(plan.kind, "kind"), (plan.stage, "stage"), (plan.night, "night")] {
            if on {
                out.insert(k.into());
            }
        }
        Some(out)
    }

    /// The facts the answer read the way `way` says depends on, for when a kept answer can
    /// change (`BodyFacts::next_change_ms`): the parts' reads together when it goes by the
    /// parts (`None` when one reads the body whole), else [`Self::status_reads`].
    pub fn status_reads_as(&self, way: StatusWay) -> Option<Rc<BTreeSet<String>>> {
        if self.uses_parts(way) {
            return self.body.parts.as_ref().and_then(|p| p.reads.clone());
        }
        self.status_reads()
    }

    /// The facts `status_of` reads from a body (`BodyFacts` field names, and `share.<meter>` for
    /// each share), with the fields each share is made of; `None` when it reads the body whole or
    /// by computed names (docs/BATTLE_SCALE.md, battle-cheap path 2).
    pub fn status_reads(&self) -> Option<Rc<BTreeSet<String>>> {
        if let Some(r) = self.body.reads.borrow().as_ref() {
            return r.clone();
        }
        let r = (|| {
            if !self.unary.contains("status_of") {
                return None;
            }
            let u = self.fields.of("status_of", 1)?.first()?;
            if u.all || !u.by_param.is_empty() {
                return None;
            }
            let mut out = BTreeSet::new();
            for (k, sub) in &u.keys {
                if k != "share" {
                    out.insert(k.clone());
                    continue;
                }
                if sub.all || !sub.by_param.is_empty() {
                    return None;
                }
                for name in sub.keys.keys() {
                    let m = self.body.meters.iter().find(|m| m.name == *name)?;
                    out.insert(format!("share.{name}"));
                    out.insert(m.value.clone());
                    if let MeterMax::Field(f) = &m.max {
                        out.insert(f.clone());
                    }
                }
            }
            Some(Rc::new(out))
        })();
        *self.body.reads.borrow_mut() = Some(r.clone());
        r
    }

    /// A mind's words for how its body feels: the `felt` words of its statuses in their order,
    /// those of meters first ("very hungry, exhausted, badly wounded"), then the others after a
    /// semicolon ("; you are growing weaker").
    pub fn felt(&self, b: &BodyFacts) -> Result<String, String> {
        let st = self.status_of(b)?;
        let words = |metered: bool| st.iter().filter(|s| !s.felt.is_empty() && s.meter.is_empty() != metered).map(|s| s.felt.as_str()).collect::<Vec<_>>();
        let mut out = words(true).join(", ");
        for w in words(false) {
            out.push_str(if out.is_empty() { "" } else { "; " });
            out.push_str(w);
        }
        Ok(out)
    }

    /// Each meter's felt word (`{meter: felt}`), for a mind's summary of its body.
    pub fn felt_by_meter(&self, b: &BodyFacts) -> Result<Vec<(String, String)>, String> {
        Ok(self.status_of(b)?.iter().filter(|s| !s.meter.is_empty() && !s.felt.is_empty()).map(|s| (s.meter.clone(), s.felt.clone())).collect())
    }

    /// Sample bodies for the install's check: every meter from empty to full, by day and
    /// at night, hurt just now and never, falling and rising; `fields` are the row's columns.
    pub fn sample_bodies(&self, fields: &[&str]) -> Vec<BodyFacts> {
        let mut out = Vec::new();
        for (kind, stage) in [("person", "adult"), ("person", "infant"), ("wolf", "adult")] {
            // Every meter in steps of a twentieth, so a law's bands are each met.
            for level in (0..=20).map(|i| i as f64 / 20.0) {
                for (night, hurt, rate) in [(false, 0.0, 0.0), (true, 1.0, -1.0), (false, 1.0, 1.0)] {
                    let mut raw: Vec<(String, f64)> = fields.iter().map(|f| (f.to_string(), 0.0)).collect();
                    let set = |raw: &mut Vec<(String, f64)>, k: &str, v: f64| match raw.iter_mut().find(|(n, _)| n == k) {
                        Some(e) => e.1 = v,
                        None => raw.push((k.to_string(), v)),
                    };
                    for m in self.meters() {
                        let max = match &m.max {
                            MeterMax::Value(v) => *v,
                            MeterMax::Field(f) => {
                                set(&mut raw, f, 100.0);
                                100.0
                            }
                        };
                        set(&mut raw, &m.value, max * level);
                        set(&mut raw, &format!("{}_rate", m.value), rate);
                    }
                    set(&mut raw, "at_ms", 1_000_000.0);
                    for f in fields.iter().filter(|f| f.ends_with("_ms") && **f != "at_ms") {
                        set(&mut raw, f, if hurt > 0.0 { 999_000.0 } else { 0.0 });
                    }
                    out.push(BodyFacts::of(kind, stage, night, &raw, self.meters(), 1_000_000));
                }
            }
        }
        out
    }
}

/// The fields of the shipped `vitals` row, for checks with no authority at hand (the rules'
/// tests and `validate`); the authority checks a script against its own row's columns.
pub const SHIPPED_VITALS: [&str; 20] = [
    "id", "hp", "max_hp", "hunger", "energy", "at_ms", "hp_rate", "hunger_rate", "energy_rate", "rate_key", "hurt_ms", "hurt_by",
    "stamina", "stamina_max", "stamina_rate", "stamina_from_ms", "focus", "focus_max", "focus_rate", "focus_from_ms",
];

/// A vitals row as `(field, value)` pairs from its JSON object (numbers only): how the mind
/// service and a client read their `vitals`/`my_vitals` rows without naming the columns.
pub fn fields_of_json(v: &serde_json::Value) -> Vec<(String, f64)> {
    v.as_object().map(|o| o.iter().filter_map(|(k, x)| x.as_f64().map(|n| (k.clone(), n))).collect()).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::super::calls;
    use super::*;

    const SHIPPED: &str = include_str!("../../../scripts/skills.rhai");

    fn row(hp: f64, hunger: f64, energy: f64, hp_rate: f64) -> Vec<(String, f64)> {
        let v = [0.0, hp, 100.0, hunger, energy, 0.0, hp_rate, 0.0, 0.0, 0.0, 0.0, 0.0, 100.0, 100.0, 0.0, 0.0, 100.0, 100.0, 0.0, 0.0];
        SHIPPED_VITALS.iter().zip(v).map(|(k, v)| (k.to_string(), v)).collect()
    }

    fn statuses(sc: &Scripts, r: &[(String, f64)], night: bool) -> Vec<String> {
        sc.status_of(&BodyFacts::of("person", "adult", night, r, sc.meters(), 0)).unwrap().iter().map(|s| s.name.clone()).collect()
    }

    #[test]
    fn the_shipped_meters_name_vitals_fields() {
        let sc = Scripts::new(SHIPPED).unwrap();
        let names: Vec<(&str, &str, bool)> = sc.meters().iter().map(|m| (m.name.as_str(), m.value.as_str(), m.shown)).collect();
        assert_eq!(names, [("health", "hp", true), ("stamina", "stamina", true), ("focus", "focus", true), ("energy", "energy", false), ("hunger", "hunger", false)]);
        assert_eq!(sc.meters()[0].max, MeterMax::Field("max_hp".into()));
        assert!(sc.meters_unknown(&SHIPPED_VITALS).is_empty());
        assert!(sc.meter_errors().is_empty());
    }

    #[test]
    fn one_set_of_thresholds_for_screens_alarms_and_words() {
        let sc = Scripts::new(SHIPPED).unwrap();
        assert_eq!(statuses(&sc, &row(100.0, 30.0, 60.0, 0.0), false), ["not_hungry", "rested", "unhurt"]);
        assert_eq!(statuses(&sc, &row(30.0, 82.0, 8.0, -0.5), true), ["very_hungry", "exhausted", "badly_hurt", "freezing", "slowed", "wasting"]);
        // The alarms the authority used to hold in Rust, at their thresholds.
        let alarms = |r: Vec<(String, f64)>, night| sc.status_of(&BodyFacts::of("person", "adult", night, &r, sc.meters(), 0)).unwrap().iter().filter_map(|s| s.alarm.clone()).map(|a| (a.text, a.think)).collect::<Vec<_>>();
        assert_eq!(alarms(row(100.0, 80.0, 60.0, 0.0), false), [("You are very hungry.".to_string(), Think::NoFood)]);
        assert_eq!(alarms(row(100.0, 97.0, 60.0, 0.0), false), [("You are starving: your body is wasting away.".to_string(), Think::Always)]);
        assert_eq!(alarms(row(100.0, 30.0, 11.0, 0.0), false), [("You are exhausted.".to_string(), Think::Never)]);
        assert_eq!(alarms(row(30.0, 30.0, 60.0, 0.0), false), [("You are badly hurt.".to_string(), Think::Always)]);
        assert!(alarms(row(90.0, 30.0, 60.0, -0.5), true).iter().any(|(t, _)| t.starts_with("You are freezing")));
        assert!(alarms(row(90.0, 30.0, 60.0, -0.5), false).iter().all(|(t, _)| !t.starts_with("You are freezing")));
        // Badly hurt and barely alive are one alarm (one episode).
        assert_eq!(alarms(row(10.0, 30.0, 60.0, 0.0), false)[0].0, "You are badly hurt.");
        let starving = sc.status_of(&BodyFacts::of("person", "adult", false, &row(100.0, 99.0, 60.0, 0.0), sc.meters(), 0)).unwrap();
        assert_eq!(starving[0].alarm.as_ref().unwrap().routine, "food");
        assert_eq!(sc.felt(&BodyFacts::of("person", "adult", false, &row(30.0, 82.0, 8.0, -0.5), sc.meters(), 0)).unwrap(), "very hungry, exhausted, badly wounded, walking slower; you are growing weaker");
        let by = sc.felt_by_meter(&BodyFacts::of("person", "adult", false, &row(90.0, 85.0, 20.0, 0.0), sc.meters(), 0)).unwrap();
        assert_eq!(by, [("hunger".to_string(), "very hungry".to_string()), ("energy".to_string(), "tired".to_string()), ("health".to_string(), "unhurt".to_string())]);
    }

    #[test]
    fn the_body_moves_along_its_rates_and_stays_within_its_meters() {
        let sc = Scripts::new(SHIPPED).unwrap();
        let mut r = row(50.0, 90.0, 5.0, -1.0);
        for (k, v) in r.iter_mut() {
            match k.as_str() {
                "at_ms" => *v = 0.0,
                "hunger_rate" => *v = 2.0,
                "energy_rate" => *v = -1.0,
                "hurt_ms" => *v = 50_000.0,
                _ => {}
            }
        }
        // Ten minutes on.
        let b = BodyFacts::of("person", "adult", false, &r, sc.meters(), 600_000);
        assert_eq!((b.get("hp"), b.get("hunger"), b.get("energy")), (Some(40.0), Some(100.0), Some(0.0)));
        assert_eq!(b.get("hurt_ago_s"), Some(120.0), "times ago are told up to two minutes");
        assert_eq!(b.get("hurt_ms"), None);
        assert_eq!(b.get("id"), None);
        assert_eq!(b.share, [("health".to_string(), 0.4), ("stamina".to_string(), 1.0), ("focus".to_string(), 1.0), ("energy".to_string(), 0.0), ("hunger".to_string(), 1.0)]);
        let never = BodyFacts::of("person", "adult", false, &row(50.0, 0.0, 50.0, 0.0), sc.meters(), 600_000);
        assert_eq!(never.get("hurt_ago_s"), Some(-1.0));
    }

    #[test]
    fn a_world_adds_a_vital_with_a_meters_row() {
        // A column `thirst` (and its rate) on the vitals row, one meters row and a status: no change
        // to the engine. Breath and focus came this way (docs/STAMINA.md): `vitals` columns,
        // `Vitals::FIELDS` in the authority and rows in the shipped `meters()`.
        let overlay = r#"
fn meters() { base_meters() + [#{ name: "thirst", value: "thirst", max: "max_thirst", order: 9 }] }
fn status_of(a) {
    let out = base_status_of(a);
    if a.thirst != () && a.thirst < 10.0 { out.push(#{ name: "parched", tone: "warn", text: "Parched", meter: "thirst", felt: "parched" }); }
    out
}
"#;
        let src = crate::floors::compose(SHIPPED, overlay).unwrap();
        let sc = Scripts::new(&src).unwrap();
        sc.validate().unwrap();
        let mut fields: Vec<&str> = SHIPPED_VITALS.to_vec();
        assert_eq!(sc.meters_unknown(&fields).len(), 2, "the shipped row has no thirst");
        fields.extend(["thirst", "max_thirst", "thirst_rate"]);
        assert!(sc.meters_unknown(&fields).is_empty());
        let mut r = row(100.0, 30.0, 60.0, 0.0);
        r.extend([("thirst".to_string(), 20.0), ("max_thirst".to_string(), 50.0), ("thirst_rate".to_string(), -2.0)]);
        // Six minutes on: 20 - 12 = 8.
        let b = BodyFacts::of("person", "adult", false, &r, sc.meters(), 360_000);
        assert_eq!(b.get("thirst"), Some(8.0));
        assert!(sc.status_of(&b).unwrap().iter().any(|s| s.name == "parched"));
        assert!(sc.felt(&b).unwrap().contains("parched"));
        assert_eq!(sc.meters().last().unwrap().name, "thirst");
    }

    #[test]
    fn breath_and_focus_are_bars_always_and_tiredness_is_a_pill() {
        let sc = Scripts::new(SHIPPED).unwrap();
        let names: Vec<(&str, bool, bool)> = sc.meters().iter().map(|m| (m.name.as_str(), m.shown, m.while_short)).collect();
        assert_eq!(names, [("health", true, false), ("stamina", true, false), ("focus", true, false), ("energy", false, false), ("hunger", false, false)]);
        assert_eq!(sc.meters()[2].label, "Mana", "the world's word for focus");
        // A pool moves by its rate a second from its start, not along the needs' anchor: 40
        // breath at t=0, refilling at 25 a second from 1 s on, is 65 at 2 s.
        let mut r = row(100.0, 30.0, 60.0, 0.0);
        for (k, v) in r.iter_mut() {
            match k.as_str() {
                "stamina" => *v = 40.0,
                "stamina_rate" => *v = 25.0,
                "stamina_from_ms" => *v = 1000.0,
                _ => {}
            }
        }
        let b = BodyFacts::of("person", "adult", false, &r, sc.meters(), 2000);
        assert_eq!(b.get("stamina"), Some(65.0));
        assert_eq!(BodyFacts::of("person", "adult", false, &r, sc.meters(), 500).get("stamina"), Some(40.0), "before its start it holds");
        assert_eq!(BodyFacts::of("person", "adult", false, &r, sc.meters(), 60_000).get("stamina"), Some(100.0), "within its meter");
        // Out of breath below 20, felt in the refusal's words; slowed when exhausted, and why.
        let mut low = row(100.0, 30.0, 60.0, 0.0);
        for (k, v) in low.iter_mut() {
            if k == "stamina" { *v = 10.0; }
        }
        let st = statuses(&sc, &low, false);
        assert!(st.contains(&"out_of_breath".to_string()), "{st:?}");
        assert!(sc.felt(&BodyFacts::of("person", "adult", false, &low, sc.meters(), 0)).unwrap().contains("out of breath"));
        assert!(!statuses(&sc, &row(100.0, 30.0, 60.0, 0.0), false).contains(&"out_of_breath".to_string()));
        assert!(statuses(&sc, &row(100.0, 30.0, 5.0, 0.0), false).contains(&"slowed".to_string()));
        assert!(!statuses(&sc, &row(100.0, 30.0, 20.0, 0.0), false).contains(&"slowed".to_string()), "tired on the island walks at its pace");
        let cullet = Scripts::new(&crate::floors::compose(SHIPPED, include_str!("../../../seeds/worlds/cullet/laws.rhai")).unwrap()).unwrap();
        assert!(statuses(&cullet, &row(100.0, 30.0, 20.0, 0.0), false).contains(&"slowed".to_string()), "tired on Cullet walks slower, and says so");
    }

    #[test]
    fn bad_meters_and_statuses_are_refused_at_install() {
        let bad = |from: &str, to: &str| {
            let src = SHIPPED.replace(from, to);
            assert_ne!(src, SHIPPED, "{from}");
            Scripts::new(&src).and_then(|s| s.validate().map(|_| ())).unwrap_err()
        };
        assert!(bad(r#"#{ name: "energy", value: "energy", max: 100.0, order: 3, shown: false },"#, r#"#{ name: "energy", value: "energy", max: 0.0, order: 3, shown: false },"#).contains("max"));
        assert!(bad(r#"#{ name: "energy", value: "energy", max: 100.0, order: 3, shown: false },"#, r#"#{ name: "energy", value: "energy", max: 100.0, order: 3, shown: false, colour: "red" },"#).contains("unknown key 'colour'"));
        assert!(bad(r#"tone: "warn", text: "Tired""#, r#"tone: "amber", text: "Tired""#).contains("tone 'amber'"));
        assert!(bad(r#"think: "no_food""#, r#"think: "maybe""#).contains("think 'maybe'"));
        let sc = Scripts::new(&SHIPPED.replace(r#"value: "energy", max: 100.0"#, r#"value: "thirst", max: 100.0"#)).unwrap();
        assert!(sc.meters_unknown(&SHIPPED_VITALS)[0].contains("'thirst', which is not a my_vitals field"));
    }

    #[test]
    fn alarm_cells_give_the_law_s_answer_at_every_moment() {
        // battle-cheap path 2: a body's statuses kept until the first moment a fact the law reads
        // can change (`next_change_ms`) are the law's at every millisecond in between. Rows of a
        // fighter: breath refilling, health mending or draining, hunger rising, a blow just taken,
        // starting below, at and above the law's levels; replayed millisecond by millisecond.
        let sc = Scripts::new(SHIPPED).unwrap();
        let reads = sc.status_reads().expect("status_of reads named facts");
        for f in ["hunger", "energy", "stamina", "hurt_ago_s", "hp_rate", "share.health", "hp", "max_hp"] {
            assert!(reads.contains(f), "status_of reads {f}: {reads:?}");
        }
        assert!(!reads.contains("focus"), "{reads:?}");
        let meters = sc.meters().to_vec();
        let mut checked = 0u64;
        let mut asked = 0u64;
        for (hp, hp_rate, stamina, stamina_rate, hurt_ms, hunger) in
            [(58.0, 2.0, 3.0, 8.0, 9_500.0, 40.0), (14.6, -3.0, 19.2, 12.0, 9_990.0, 99.95), (89.5, 0.6, 0.0, 25.0, 0.0, 10.0), (35.2, 0.0, 99.7, 5.0, 4_000.0, 60.0), (60.0, -60.0, 50.0, -4.0, 9_000.0, 0.0)]
        {
            let mut raw = row(hp, hunger, 70.0, hp_rate);
            let set = |raw: &mut Vec<(String, f64)>, k: &str, v: f64| raw.iter_mut().find(|(n, _)| n == k).unwrap().1 = v;
            set(&mut raw, "at_ms", 10_000.0);
            set(&mut raw, "hunger_rate", 0.4);
            set(&mut raw, "stamina", stamina);
            set(&mut raw, "stamina_rate", stamina_rate);
            set(&mut raw, "stamina_from_ms", 10_000.0);
            set(&mut raw, "hurt_ms", hurt_ms);
            let law = |t: u64| sc.status_of(&BodyFacts::of("person", "adult", false, &raw, &meters, t)).unwrap();
            let (mut until, mut kept) = (0u64, law(10_000));
            for t in 10_000..25_000u64 {
                if t >= until {
                    kept = law(t);
                    until = BodyFacts::next_change_ms(&raw, &meters, t, Some(&reads));
                    assert!(until > t, "a cell lasts at least to the next millisecond");
                    asked += 1;
                }
                assert_eq!(kept, law(t), "at {t} ms (row hp {hp}, stamina {stamina}): the kept answer is the law's");
                checked += 1;
            }
        }
        assert!(asked * 10 < checked, "asked {asked} times in {checked} moments");
    }

    #[test]
    fn bodies_in_one_state_share_one_answer() {
        let sc = Scripts::new(SHIPPED).unwrap();
        let a = sc.status_of(&BodyFacts::of("person", "adult", false, &row(70.2, 30.4, 60.0, 0.0), sc.meters(), 0)).unwrap();
        let b = sc.status_of(&BodyFacts::of("person", "adult", false, &row(69.8, 29.6, 60.0, 0.0), sc.meters(), 0)).unwrap();
        assert!(Rc::ptr_eq(&a, &b), "whole numbers: one state");
    }

    #[test]
    fn cullet_composes_with_the_body_law() {
        let laws = include_str!("../../../seeds/worlds/cullet/laws.rhai");
        let src = crate::floors::compose(SHIPPED, laws).unwrap();
        let sc = Scripts::new(&src).unwrap();
        sc.validate().unwrap();
        assert_eq!(sc.meters().len(), 5);
    }

    // ---- status_parts (docs/STATUS_PARTS.md) ------------------------------------------------

    /// The shipped `status_of` as it stood before it was split into parts (main 9d112a51), as an
    /// overlay: the reference the parts are held to.
    const BEFORE_PARTS: &str = include_str!("status_of_before_parts.rhai");
    const WHOLE: StatusWay = StatusWay { parts: false, check: false };

    /// A small deterministic generator for sampled bodies.
    struct Lcg(u64);
    impl Lcg {
        fn next(&mut self) -> u64 {
            self.0 = self.0.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            self.0 >> 33
        }
        fn pick<T: Copy>(&mut self, xs: &[T]) -> T {
            xs[(self.next() % xs.len() as u64) as usize]
        }
    }

    /// A vitals row and the moment it is read at: each meter at, just under and just over the
    /// law's levels, rates falling, still and rising, hurt never, just now and long ago, and now
    /// and then a field missing (a body the row does not give hunger or breath).
    fn sampled_row(g: &mut Lcg) -> (Vec<(String, f64)>, u64) {
        let hunger = g.pick(&[0.0, 10.0, 15.0, 15.4, 16.0, 30.0, 40.0, 40.6, 41.0, 55.0, 55.6, 56.0, 70.0, 79.4, 80.0, 90.0, 96.4, 97.0, 99.0, 99.6, 100.0]);
        let energy = g.pick(&[0.0, 0.4, 1.0, 5.0, 9.4, 9.6, 10.0, 11.0, 11.6, 12.0, 20.0, 29.6, 30.0, 49.0, 50.0, 70.0, 84.6, 85.0, 100.0]);
        let max_hp = g.pick(&[100.0, 80.0, 40.0, 7.0]);
        let share = g.pick(&[0.0, 0.05, 0.14, 0.145, 0.15, 0.2, 0.34, 0.35, 0.5, 0.59, 0.6, 0.75, 0.89, 0.9, 0.95, 0.985, 0.99, 0.995, 1.0]);
        let hp_rate = g.pick(&[-3.0, -0.5, -0.02, -0.011, -0.01, -0.004, 0.0, 0.004, 0.01, 0.011, 0.02, 0.6, 2.0]);
        let stamina = g.pick(&[0.0, 5.0, 19.0, 19.4, 19.6, 20.0, 21.0, 60.0, 100.0]);
        let hurt = g.pick(&[-1.0, 0.0, 0.4, 1.0, 14.0, 14.9, 15.0, 15.2, 60.0, 119.0, 200.0]);
        let now = 1_000_000u64;
        let mut raw = row(share * max_hp, hunger, energy, hp_rate);
        let set = |raw: &mut Vec<(String, f64)>, k: &str, v: f64| raw.iter_mut().find(|(n, _)| n == k).unwrap().1 = v;
        set(&mut raw, "max_hp", max_hp);
        set(&mut raw, "at_ms", now as f64);
        set(&mut raw, "stamina", stamina);
        set(&mut raw, "stamina_from_ms", now as f64);
        set(&mut raw, "hurt_ms", if hurt < 0.0 { 0.0 } else { now as f64 - hurt * 1000.0 });
        for gone in ["hunger", "energy", "stamina", "hp_rate", "hurt_ms"] {
            if g.next() % 23 == 0 {
                raw.retain(|(k, _)| k != gone);
            }
        }
        (raw, now)
    }

    fn sampled_body(g: &mut Lcg, sc: &Scripts) -> BodyFacts {
        let (kind, stage) = g.pick(&[("person", "adult"), ("person", "infant"), ("person", "elder"), ("wolf", "adult"), ("deer", "adult")]);
        let night = g.next() % 2 == 0;
        let (raw, now) = sampled_row(g);
        BodyFacts::of(kind, stage, night, &raw, sc.meters(), now)
    }

    #[test]
    fn the_shipped_parts_joined_are_the_law_before_the_split() {
        // The parts (with their memos and reduced bodies), the whole law (now their join) and the
        // law as it was written before the split give the same ordered statuses, every field
        // alike, on 6,000 sampled bodies; and on Cullet, whose `slow_words` differs.
        for overlay in ["", include_str!("../../../seeds/worlds/cullet/laws.rhai")] {
            let base = if overlay.is_empty() { SHIPPED.to_string() } else { crate::floors::compose(SHIPPED, overlay).unwrap() };
            let sc = Scripts::new(&base).unwrap();
            assert_eq!(sc.status_part_names().len(), 8);
            let before = Scripts::new(&crate::floors::compose(&base, BEFORE_PARTS).unwrap()).unwrap();
            assert!(before.status_part_names().is_empty(), "an overlay of status_of alone is asked whole");
            let mut g = Lcg(7);
            let mut seen = std::collections::BTreeSet::new();
            for _ in 0..6000 {
                let b = sampled_body(&mut g, &sc);
                let parts = sc.status_of(&b).unwrap();
                assert_eq!(*parts, *sc.status_of_profiled(&b, WHOLE, |_| ()).unwrap(), "{b:?}");
                assert_eq!(*parts, *before.status_of(&b).unwrap(), "{b:?}");
                seen.extend(parts.iter().map(|s| s.name.clone()));
            }
            for name in ["starving", "very_hungry", "hungry", "peckish", "fed", "not_hungry", "spent", "exhausted", "tired", "a_little_tired", "well_rested", "rested", "barely_alive", "badly_hurt", "hurt", "a_little_hurt", "unhurt", "freezing", "in_combat", "out_of_breath", "slowed", "wasting", "recovering"] {
                assert!(seen.contains(name), "the samples meet `{name}`: {seen:?}");
            }
        }
    }

    #[test]
    fn each_part_is_kept_on_what_it_reads() {
        let sc = Scripts::new(SHIPPED).unwrap();
        let reads = |p: &str| sc.status_part_reads(p).unwrap_or_else(|| panic!("{p} reads named facts")).into_iter().collect::<Vec<_>>();
        assert_eq!(reads("hunger_part"), ["hunger"]);
        assert_eq!(reads("energy_part"), ["energy"]);
        assert_eq!(reads("health_part"), ["share.health"]);
        assert_eq!(reads("cold_part"), ["hp_rate", "hunger", "kind", "night"]);
        assert_eq!(reads("combat_part"), ["hurt_ago_s"]);
        assert_eq!(reads("breath_part"), ["stamina"]);
        let slowed = reads("slowed_part");
        assert!(slowed.contains(&"energy".to_string()) && slowed.iter().all(|r| r == "energy" || r == "kind"), "{slowed:?}");
        assert_eq!(reads("mending_part"), ["hp_rate", "share.health"]);
        // Written as its parts joined in order: equal by construction, so the install does not
        // run the law on every sample to compare (check.rs `body`).
        assert!(sc.status_of_is_join());
        let cullet = Scripts::new(&crate::floors::compose(SHIPPED, include_str!("../../../seeds/worlds/cullet/laws.rhai")).unwrap()).unwrap();
        assert!(cullet.status_of_is_join());
        let not_join = |overlay: &str| !Scripts::new(&crate::floors::compose(SHIPPED, overlay).unwrap()).unwrap().status_of_is_join();
        assert!(not_join(BEFORE_PARTS), "a law written whole");
        assert!(not_join(r#"fn status_parts() { ["hunger_part", "breath_part"] } fn status_of(a) { breath_part(a) + hunger_part(a) }"#), "out of order");
        assert!(not_join(r#"fn status_parts() { ["hunger_part", "breath_part"] } fn status_of(a) { hunger_part(a) }"#), "a part left out");
        assert!(not_join(r#"fn status_parts() { ["hunger_part", "breath_part"] } fn status_of(a) { let x = hunger_part(a); x + breath_part(a) }"#), "more than the join");
        assert!(not_join(r#"fn status_parts() { ["hunger_part", "breath_part"] } fn status_of(a) { hunger_part(a) + breath_part(#{}) }"#), "a part on another body");
        assert!(not_join(r#"fn status_parts() { ["hunger_part"] }"#), "the parts replaced, the shipped join of eight kept");
        // A kept answer lasts until a fact a part reads can change: the same facts as the whole law's.
        assert_eq!(sc.status_reads_as(StatusWay::default()), sc.status_reads());
        assert_eq!(sc.status_reads_as(WHOLE), sc.status_reads());
    }

    #[test]
    fn a_change_of_breath_alone_asks_one_part() {
        let sc = Scripts::new(SHIPPED).unwrap();
        let mut raw = row(58.0, 40.0, 70.0, 0.0);
        let body = |raw: &[(String, f64)]| BodyFacts::of("person", "adult", false, raw, sc.meters(), 0);
        sc.status_of(&body(&raw)).unwrap();
        let _ = calls::take();
        for stamina in [3.0, 4.0, 17.0, 33.0] {
            raw.iter_mut().find(|(k, _)| k == "stamina").unwrap().1 = stamina;
            let s = sc.status_of(&body(&raw)).unwrap();
            assert_eq!(*s, *sc.status_of_profiled(&body(&raw), WHOLE, |_| ()).unwrap());
            let c = calls::take();
            let ran: Vec<usize> = (0..8).filter(|i| c[calls::PART_RUN_BY + i] > 0).collect();
            assert_eq!((c[calls::PART_RUN], ran), (1, vec![5]), "stamina {stamina}: only breath_part runs (the whole check above ran the whole law)");
            assert_eq!(c[calls::PART_MEMO], 7);
        }
        // The same breath again: no part runs, the joined answer is the one kept.
        let a = sc.status_of(&body(&raw)).unwrap();
        let b = sc.status_of(&body(&raw)).unwrap();
        assert!(Rc::ptr_eq(&a, &b));
        let c = calls::take();
        assert_eq!((c[calls::PART_RUN], c[calls::PARTS_JOINED]), (0, 2));
    }

    #[test]
    fn full_memos_start_over_with_the_same_answers() {
        // A part read on a fact of thousands of values, each its own answer: its memo and its
        // answers fill and start over (and the joined answers with them), and every answer is
        // still the whole law's.
        let overlay = r#"
fn status_parts() { ["level_part", "breath_part"] }
fn level_part(a) { if a.hp == () { [] } else { [#{ name: "level", tone: "plain", text: "Level " + a.hp.to_string() }] } }
fn status_of(a) { level_part(a) + breath_part(a) }
"#;
        let sc = Scripts::new(&crate::floors::compose(SHIPPED, overlay).unwrap()).unwrap();
        assert_eq!(sc.status_part_names(), ["level_part", "breath_part"]);
        sc.validate().unwrap();
        let mut raw = row(0.0, 40.0, 70.0, 0.0);
        raw.iter_mut().find(|(k, _)| k == "max_hp").unwrap().1 = 10_000.0;
        for round in 0..2 {
            for hp in (0..(KEPT as u32 + 300)).step_by(if round == 0 { 1 } else { 7 }) {
                raw.iter_mut().find(|(k, _)| k == "hp").unwrap().1 = hp as f64;
                raw.iter_mut().find(|(k, _)| k == "stamina").unwrap().1 = (hp % 40) as f64;
                let b = BodyFacts::of("person", "adult", false, &raw, sc.meters(), 0);
                assert_eq!(*sc.status_of(&b).unwrap(), sc.status_fresh(&b).unwrap(), "hp {hp}");
            }
        }
        let parts = sc.body.parts.as_ref().unwrap();
        assert!(parts.list[0].answers.borrow().len() <= ANSWERS_KEPT && parts.list[0].memo.borrow().len() <= KEPT);
        assert!(parts.joined.borrow().len() <= KEPT);
    }

    #[test]
    fn a_part_that_reads_the_body_whole_is_kept_on_all_of_it() {
        let overlay = r#"
fn status_parts() { ["counted_part", "breath_part"] }
fn counted_part(a) { if a.len() > 3 { [#{ name: "many", tone: "plain", text: "Many facts" }] } else { [] } }
fn status_of(a) { counted_part(a) + breath_part(a) }
"#;
        let sc = Scripts::new(&crate::floors::compose(SHIPPED, overlay).unwrap()).unwrap();
        sc.validate().unwrap();
        assert!(sc.status_part_reads("counted_part").is_none());
        assert!(sc.status_reads_as(StatusWay::default()).is_none(), "one part reads the body whole: every fact may change it");
        let mut g = Lcg(11);
        for _ in 0..300 {
            let b = sampled_body(&mut g, &sc);
            assert_eq!(*sc.status_of(&b).unwrap(), sc.status_fresh(&b).unwrap());
        }
    }

    #[test]
    fn floors_that_change_the_body_law_keep_their_law() {
        // A floor that replaces `status_of` alone (Cullet's thirst, above) is asked it whole.
        let thirst = r#"
fn status_of(a) {
    let out = base_status_of(a);
    if a.stamina != () && a.stamina < 50.0 { out.push(#{ name: "winded", tone: "warn", text: "Winded" }); }
    out
}
"#;
        let sc = Scripts::new(&crate::floors::compose(SHIPPED, thirst).unwrap()).unwrap();
        sc.validate().unwrap();
        assert!(sc.status_part_names().is_empty());
        let mut r = row(100.0, 30.0, 60.0, 0.0);
        r.iter_mut().find(|(k, _)| k == "stamina").unwrap().1 = 30.0;
        assert!(statuses(&sc, &r, false).contains(&"winded".to_string()));
        // A floor that changes one part: both ways give its answer.
        let breath = r#"fn breath_part(a) { if a.stamina != () && a.stamina < 40.0 { [#{ name: "out_of_breath", tone: "warn", text: "Out of breath", meter: "stamina", felt: "out of breath" }] } else { [] } }"#;
        let sc = Scripts::new(&crate::floors::compose(SHIPPED, breath).unwrap()).unwrap();
        sc.validate().unwrap();
        assert_eq!(sc.status_part_names().len(), 8);
        let b = BodyFacts::of("person", "adult", false, &r, sc.meters(), 0);
        assert!(sc.status_of(&b).unwrap().iter().any(|s| s.name == "out_of_breath"));
        assert_eq!(sc.status_of(&b).unwrap(), sc.status_of_profiled(&b, WHOLE, |_| ()).unwrap());
        // Both replaced and in agreement: accepted.
        let both = r#"
fn status_parts() { ["breath_part", "hunger_part"] }
fn status_of(a) { breath_part(a) + hunger_part(a) }
"#;
        let sc = Scripts::new(&crate::floors::compose(SHIPPED, both).unwrap()).unwrap();
        sc.validate().unwrap();
        assert_eq!(sc.status_part_names(), ["breath_part", "hunger_part"]);
        // Both replaced, in disagreement: refused, naming the body and both answers.
        let differ = r#"
fn status_parts() { ["hunger_part", "breath_part"] }
fn status_of(a) { breath_part(a) + hunger_part(a) }
"#;
        let e = Scripts::new(&crate::floors::compose(SHIPPED, differ).unwrap()).unwrap().validate().unwrap_err();
        assert!(e.contains("status_of and status_parts disagree: override both or neither") && e.contains("the parts joined give [") && e.contains("for a adult person"), "{e}");
        // The parts alone replaced, so they no longer join to the base's `status_of`: refused.
        let e = Scripts::new(&crate::floors::compose(SHIPPED, r#"fn status_parts() { ["hunger_part"] }"#).unwrap()).unwrap().validate().unwrap_err();
        assert!(e.contains("status_of and status_parts disagree"), "{e}");
    }

    #[test]
    fn a_script_of_its_own_status_of_on_the_shipped_laws_is_asked_it_whole() {
        // A script without some required laws runs on the shipped script's (`borrowed`); its own
        // `status_of` is not replaced by the shipped parts merged under it.
        let own = r#"
fn rates(a) { #{ hunger: 0.0, energy: 0.0, hp: 0.0 } }
fn move_speed(a) { 1.0 }
fn status_of(a) { [#{ name: "fine", tone: "plain", text: "Fine" }] }
"#;
        let sc = Scripts::new(own).unwrap();
        assert!(sc.status_part_names().is_empty());
        assert_eq!(statuses(&sc, &row(10.0, 99.0, 1.0, -1.0), true), ["fine"]);
    }

    #[test]
    fn bad_declarations_of_parts_are_refused_at_install() {
        let bad = |overlay: &str| Scripts::new(&crate::floors::compose(SHIPPED, overlay).unwrap()).and_then(|s| s.validate().map(|_| ())).unwrap_err();
        assert!(bad(r#"fn status_parts() { ["hunger_part", "thirst_part"] }"#).contains("`thirst_part` is not a function of one parameter"));
        assert!(bad(r#"fn status_parts() { ["hunger_part", "hunger_part"] }"#).contains("`hunger_part` is named twice"));
        assert!(bad(r#"fn status_parts() { ["hunger_status_of"] } fn hunger_status_of(a, b) { [] }"#).contains("not a function of one parameter"));
        assert!(bad(r#"fn status_parts() { "hunger_part" }"#).contains("must return a list"));
        assert!(bad(r#"fn status_parts() { [] }"#).contains("names no part"));
        assert!(bad(r#"fn status_parts() { ["status_of"] }"#).contains("cannot be one of its parts"));
        let e = bad(r#"fn breath_part(a) { [#{ name: "out_of_breath", tone: "teal", text: "Out of breath" }] }"#);
        assert!(e.contains("breath_part") && e.contains("tone 'teal'"), "{e}");
        let e = bad(r#"fn breath_part(a) { 3 }"#);
        assert!(e.contains("breath_part"), "{e}");
        // Not installed, a bad declaration asks the whole law.
        let sc = Scripts::new(&crate::floors::compose(SHIPPED, r#"fn status_parts() { ["hunger_part", "hunger_part"] }"#).unwrap()).unwrap();
        assert!(!sc.uses_parts(StatusWay::default()));
        assert_eq!(statuses(&sc, &row(100.0, 30.0, 60.0, 0.0), false), ["not_hungry", "rested", "unhurt"]);
    }

    #[test]
    fn the_check_compares_with_the_whole_law_and_gives_it_where_they_differ() {
        let sc = Scripts::new(SHIPPED).unwrap();
        let check = StatusWay { parts: true, check: true };
        let mut g = Lcg(3);
        let _ = calls::take();
        for _ in 0..200 {
            let b = sampled_body(&mut g, &sc);
            sc.status_of_profiled(&b, check, |_| ()).unwrap();
        }
        let c = calls::take();
        assert_eq!((c[calls::STATUS_CHECKED], c[calls::STATUS_DIFFERED]), (200, 0));
        assert!(c[calls::PART_MEMO] > 0, "kept parts were checked too");
        assert!(sc.take_status_differences().is_empty());
        // Parts that are not the law (a script not installed, so not refused): counted, told,
        // and the whole law's answer given.
        let differ = r#"
fn status_parts() { ["hunger_part", "breath_part"] }
fn status_of(a) { breath_part(a) + hunger_part(a) }
"#;
        let sc = Scripts::new(&crate::floors::compose(SHIPPED, differ).unwrap()).unwrap();
        let mut r = row(100.0, 30.0, 60.0, 0.0);
        r.iter_mut().find(|(k, _)| k == "stamina").unwrap().1 = 5.0;
        let b = BodyFacts::of("person", "adult", false, &r, sc.meters(), 0);
        let s = sc.status_of_profiled(&b, check, |_| ()).unwrap();
        assert_eq!(s.iter().map(|x| x.name.as_str()).collect::<Vec<_>>(), ["out_of_breath", "not_hungry"]);
        assert_eq!(calls::take()[calls::STATUS_DIFFERED], 1);
        let told = sc.take_status_differences();
        assert!(told.len() == 1 && told[0].contains("the parts gave [not_hungry, out_of_breath] where status_of gives [out_of_breath, not_hungry]"), "{told:?}");
        // The rollback: the whole law, as before.
        assert_eq!(sc.status_of_profiled(&b, WHOLE, |_| ()).unwrap().iter().map(|x| x.name.as_str()).collect::<Vec<_>>(), ["out_of_breath", "not_hungry"]);
    }
}
