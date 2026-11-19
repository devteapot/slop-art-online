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

fn read_status(d: Dynamic) -> Result<Vec<Status>, String> {
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
    pub(super) fn read_body(&self) -> Body {
        let (meters, errors) = if self.nullary.contains("meters") {
            match self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "meters", ()) {
                Ok(d) => read_meters(d),
                Err(e) => (default_meters(), vec![format!("meters: {e}")]),
            }
        } else {
            (default_meters(), Vec::new())
        };
        Body { meters, errors, memo: Default::default(), reads: Default::default() }
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
    pub fn status_of(&self, b: &BodyFacts) -> Result<Rc<Vec<Status>>, String> {
        if !self.unary.contains("status_of") {
            return Ok(Rc::new(Vec::new()));
        }
        super::calls::note(super::calls::STATUS_ASKED);
        let key = match self.status_reads() {
            Some(r) => b.key_reading(&r),
            None => b.key(),
        };
        if let Some(s) = self.body.memo.borrow().get(&key) {
            super::calls::note(super::calls::STATUS_MEMO);
            return Ok(s.clone());
        }
        super::calls::note(super::calls::STATUS_RUN);
        let d = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "status_of", (b.map(),)).map_err(|e| format!("status_of: {e}"))?;
        let s = Rc::new(read_status(d)?);
        let mut memo = self.body.memo.borrow_mut();
        if memo.len() >= KEPT {
            memo.clear();
        }
        memo.insert(key, s.clone());
        Ok(s)
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
}
