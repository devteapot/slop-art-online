//! Install-time validation: every law and skill function is called with sample inputs, the way
//! the engine calls it, and the script is refused if any call fails, returns the wrong shape, or
//! exceeds the engine's limits. Rhai reports a misspelled field or a type error only when the
//! line runs, so the samples cover the states the engine hands the laws: people of each age,
//! animals, every kind of target, every item and technique.
//!
//! The calls run on a second engine with the same limits that also counts operations, so the
//! report says what each function costs (the unit of `max_operations`).

use super::context::Plan;
use super::{ActorFacts, RegardIn, RoutineFacts, Scripts, SkillCtx, TargetFacts};
use crate::catalog;
use rhai::{Dynamic, Scope};
use std::cell::Cell;
use std::collections::BTreeMap;
use std::rc::Rc;

/// What an install measured: the most operations each function took over its samples, and
/// the calls made (samples that give a law the same input are called once).
#[derive(Clone, Debug, Default)]
pub struct Report {
    pub ops: BTreeMap<String, u64>,
    pub calls: usize,
}

impl Report {
    /// The heaviest function and its operations.
    pub fn heaviest(&self) -> Option<(&str, u64)> {
        self.ops.iter().max_by_key(|(_, n)| **n).map(|(f, n)| (f.as_str(), *n))
    }

    /// One line for the module log.
    pub fn summary(&self) -> String {
        let mut v: Vec<(&String, &u64)> = self.ops.iter().collect();
        v.sort_by(|a, b| b.1.cmp(a.1).then(a.0.cmp(b.0)));
        let top: Vec<String> = v.iter().take(8).map(|(f, n)| format!("{f} {n}")).collect();
        format!("{} calls over {} functions; most operations: {}", self.calls, self.ops.len(), top.join(", "))
    }
}

struct Probe<'a> {
    s: &'a Scripts,
    engine: rhai::Engine,
    count: Rc<Cell<u64>>,
    report: Report,
    /// Answers by function and by the values of the fields it reads: a law is a function of
    /// those alone, so a sample that agrees on them is the same call and is not repeated.
    seen: std::collections::HashMap<(String, Vec<u8>), Dynamic>,
    /// Every call and its answer, when asked for (`validate_traced`, the hashing-seed check).
    trace: Option<Vec<String>>,
}

impl Probe<'_> {
    fn raw(&mut self, f: &str, args: impl rhai::FuncArgs, about: &dyn Fn() -> String) -> Result<Dynamic, String> {
        self.count.set(0);
        let r = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.s.ast, f, args);
        let n = self.count.get();
        let e = self.report.ops.entry(f.to_string()).or_insert(0);
        *e = (*e).max(n);
        self.report.calls += 1;
        if let Some(t) = &mut self.trace {
            t.push(format!("{f} {} -> {:?}", about(), r.as_ref().map_err(|e| e.to_string())));
        }
        r.map_err(|e| format!("install refused: `{f}` failed {}: {e}", about()))
    }

    fn ctx(&mut self, f: &str, c: &SkillCtx) -> Result<Dynamic, String> {
        let (plan, knack) = (self.s.plan(f), self.s.shapes.knack(&c.skill));
        let mut key = Vec::new();
        super::context::key(c, knack, &plan, &mut key);
        let key = (f.to_string(), key);
        if let Some(d) = self.seen.get(&key) {
            return Ok(d.clone());
        }
        let d = self.raw(f, (super::context::map(c, knack, &plan),), &|| describe(c))?;
        self.seen.insert(key, d.clone());
        Ok(d)
    }
}

fn describe(c: &SkillCtx) -> String {
    let mut s = format!("for a {} ({}, hunger {}, energy {})", c.actor.kind, c.actor.stage, c.actor.hunger, c.actor.energy);
    if c.target.class != "none" {
        s += &format!(", target {} {}", c.target.class, c.target.kind);
    }
    if !c.item.is_empty() {
        s += &format!(", item {}", c.item);
    }
    if c.night {
        s += ", at night";
    }
    if c.raining {
        s += ", in rain";
    }
    s
}

/// The functions the engine calls with a context: `<skill>_check`, `_duration`, `_done`, `_hit`,
/// `_missile`, and the need laws.
pub const SKILL_PARTS: [&str; 5] = ["_check", "_duration", "_done", "_hit", "_missile"];
pub const CTX_LAWS: [&str; 7] = ["rates", "body_state", "move_speed", "senses", "motion", "theft", "glow"];

pub fn validate(s: &Scripts, limits: super::Limits) -> Result<Report, String> {
    if let Some(f) = s.borrowed.first() {
        return Err(format!("install refused: the script has no `{f}` law (the engine asks it; see the shipped script)"));
    }
    // The samples are the script's own items and skills, not the process's world's.
    catalog::scoped(s.skills().clone(), || validate_scoped(s, limits, None).map(|(r, _)| r))
}

/// [`validate`], with every call it made and its answer (in no particular order).
#[cfg(test)]
pub fn validate_traced(s: &Scripts, limits: super::Limits) -> Result<(Report, Vec<String>), String> {
    catalog::scoped(s.skills().clone(), || validate_scoped(s, limits, Some(Vec::new())))
}

/// Laws the engine asks by name, besides those it calls with a context, a name or an event.
pub const ENGINE_LAWS: [&str; 13] = ["perceived_of", "record_text", "items", "structures", "resources", "know_how", "recipes", "structure_traits", "occupation_knows", "source_of", "carcass", "daylight", "life_years"];

/// Every law the engine asks is declared with a description for minds (`<law>_law()`, or listed
/// in another's `covers`), and every world constant has its words in `laws_about`.
fn described(s: &Scripts) -> Result<(), String> {
    let declared: std::collections::BTreeSet<&str> = s.laws.values().flat_map(|l| std::iter::once(l.name.as_str()).chain(l.covers.iter().map(|c| c.as_str()))).collect();
    let mut asked: Vec<String> = s.ctx_laws().into_iter().filter(|f| CTX_LAWS.contains(&f.as_str()) || f.starts_with("on_")).collect();
    asked.extend(super::name_laws(s).into_iter().map(|(f, _)| f));
    asked.extend(ENGINE_LAWS.iter().filter(|f| s.has(f)).map(|f| f.to_string()));
    // A skill's own numbers by kind (dodge_dist, jump_speed) are described by its spec.
    let skill_of = |f: &str| f.strip_suffix("_dist").or_else(|| f.strip_suffix("_speed")).is_some_and(|k| s.skills.get(k).is_some() || s.shapes.get(k).is_some());
    asked.retain(|f| !skill_of(f));
    asked.sort();
    asked.dedup();
    if let Some(e) = s.law_errors.borrow().first() {
        return Err(format!("install refused: a law's description failed: {e}"));
    }
    if let Some(f) = asked.iter().find(|f| !declared.contains(f.as_str())) {
        return Err(format!("install refused: the law `{f}` has no description (declare `{f}_law()` with `about`, or list it in another law's `covers`)"));
    }
    if s.has("laws") {
        let about = s.laws_about();
        for k in s.law_names() {
            if !about.iter().any(|(n, t)| *n == k && !t.trim().is_empty()) {
                return Err(format!("install refused: the world constant `{k}` has no description (give it words in `laws_about(l)`)"));
            }
        }
    }
    Ok(())
}

/// The interface declarations (`<name>_ui()`) read without a problem: an install refuses what a
/// client would only log and play on without (docs/INTERFACE.md §3).
fn interface(s: &Scripts) -> Result<(), String> {
    const SHOWN: usize = 12;
    let e = s.ui_errors();
    if e.is_empty() {
        return Ok(());
    }
    let more = if e.len() > SHOWN { format!("; and {} more", e.len() - SHOWN) } else { String::new() };
    Err(format!("install refused: {}{more}", e.iter().take(SHOWN).cloned().collect::<Vec<_>>().join("; ")))
}

fn validate_scoped(s: &Scripts, limits: super::Limits, trace: Option<Vec<String>>) -> Result<(Report, Vec<String>), String> {
    // Every law reads only fields the engine provides.
    for f in s.ctx_laws() {
        Plan::of(&f, s.fields.of(&f, 1).and_then(|u| u.first()), true).map_err(|e| format!("install refused: {e}"))?;
    }
    let count = Rc::new(Cell::new(0u64));
    let mut engine = super::engine_with(limits, &s.tables);
    super::register_day(&mut engine, s.hour_ms);
    let c2 = count.clone();
    engine.on_progress(move |n| {
        c2.set(n);
        None
    });
    let mut p = Probe { s, engine, count, report: Report::default(), seen: Default::default(), trace };
    laws_and_tables(&mut p)?;
    needs(&mut p)?;
    skills(&mut p)?;
    hooks(&mut p)?;
    yes_or_no(&mut p)?;
    described(s)?;
    interface(s)?;
    record_texts(&mut p)?;
    regard(&mut p)?;
    daylight(&mut p)?;
    life_years(s)?;
    Ok((p.report, p.trace.unwrap_or_default()))
}

fn laws_and_tables(p: &mut Probe) -> Result<(), String> {
    let s = p.s;
    for f in s.fns.iter().filter(|f| f.as_str() == "laws" || f.as_str() == "skill_bar" || f.ends_with("_combat") || f.ends_with("_shows")) {
        let d = p.raw(f, (), &|| String::new())?;
        if f == "laws" && !d.is_map() {
            return Err("install refused: `laws` must return a map".into());
        }
    }
    // The numbers the engine looks up by a name (cooldowns, lunge, max_hp, …), over every name
    // it asks them for.
    for (f, domain) in super::name_laws(s) {
        for arg in domain {
            let d = p.raw(&f, (arg.clone(),), &|| format!("for `{arg}`"))?;
            if super::number(&d).is_none() {
                return Err(format!("install refused: `{f}(\"{arg}\")` must return a number, got {}", d.type_name()));
            }
        }
    }
    // Every skill the script has rules for (a duration or effects) is declared, with a
    // description for minds.
    let mut ruled: Vec<&str> = s.unary.iter().filter_map(|f| f.strip_suffix("_done").or_else(|| f.strip_suffix("_duration"))).filter(|n| !n.is_empty()).collect();
    ruled.sort();
    ruled.dedup();
    if let Some(k) = ruled.iter().find(|k| s.skills.get(k).is_none()) {
        return Err(format!("install refused: `{k}` has rules but no `{k}_spec()` (every skill declares its arguments and a description for minds)"));
    }
    Ok(())
}

/// Laws that say yes or no of an act (`theft(a)` for a take), over each body and target.
fn yes_or_no(p: &mut Probe) -> Result<(), String> {
    let s = p.s;
    for f in ["theft"] {
        if !s.has(f) {
            continue;
        }
        for a in actors() {
            for t in targets() {
                let mut c = sample("take", &a, &t, "berries");
                for hosts in [false, true] {
                    c.target.hosts = hosts;
                    let d = p.ctx(f, &c)?;
                    if !d.is_bool() {
                        return Err(format!("install refused: `{f}` must return true or false, got {} ({})", d.type_name(), describe(&c)));
                    }
                }
            }
        }
    }
    Ok(())
}

fn needs(p: &mut Probe) -> Result<(), String> {
    let s = p.s;
    for actor in actors() {
        for (night, raining, season, warm) in [(false, false, "summer", false), (true, false, "summer", false), (true, true, "winter", false), (false, true, "spring", true), (true, false, "winter", true)] {
            let mut a = actor.clone();
            if warm {
                (a.near_fire, a.near_shelter) = (true, true);
            }
            let c = SkillCtx { actor: a, night, dark: if night { 1.0 } else { 0.0 }, raining, season: season.into(), hour: if night { 23.0 } else { 12.0 }, ..Default::default() };
            if s.has("rates") {
                let d = p.ctx("rates", &c)?;
                super::NeedLaw::from_dynamic(d, s.hour_ms).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
            }
            if s.has("body_state") {
                let d = p.ctx("body_state", &c)?;
                super::decode_body(d).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
            }
            if s.has("move_speed") {
                let d = p.ctx("move_speed", &c)?;
                super::number(&d).ok_or_else(|| format!("install refused: move_speed must return a number ({})", describe(&c)))?;
            }
            let d = p.ctx("motion", &c)?;
            super::decode_moves(d).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
            // Senses and glow, with and without a torch in the pack, in lamplight or not, and in
            // twilight: within the law's own reach.
            for (torch, lit, twilight) in [(false, false, false), (true, false, false), (false, true, false), (false, false, true), (true, true, true)] {
                let mut c = c.clone();
                if torch {
                    c.actor.inv.push(("torch".into(), 1));
                }
                c.actor.lit = lit;
                if twilight {
                    c.dark = 0.5;
                }
                let d = p.ctx("senses", &c)?;
                let reach = s.reach();
                let wide = super::decode_senses(d.clone(), &super::Reach { day: f32::MAX, night: f32::MAX, hearing: f32::MAX, glow: f32::MAX }, c.dark).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
                if wide.sight > reach.sight(c.dark) || wide.hearing > reach.hearing {
                    return Err(format!("install refused: senses gives sight {} and hearing {} {}, beyond senses_law's reach ({} by {}, hearing {}): raise the reach with the law", wide.sight, wide.hearing, describe(&c), reach.sight(c.dark), if c.dark >= 1.0 { "night" } else if c.dark <= 0.0 { "day" } else { "twilight" }, reach.hearing));
                }
                if s.has("glow") {
                    let d = p.ctx("glow", &c)?;
                    let g = super::decode_glow(d, &super::Reach { day: 0.0, night: 0.0, hearing: 0.0, glow: f32::MAX }).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
                    if g > reach.glow {
                        return Err(format!("install refused: glow gives {g} m {}, beyond senses_law's reach.glow ({} m): raise the reach with the law", describe(&c), reach.glow));
                    }
                }
            }
        }
    }
    Ok(())
}

/// Every skill the script has rules for, as the engine runs them: the check, and when it
/// passes, the duration, the effects, and a missile and its hit.
fn skills(p: &mut Probe) -> Result<(), String> {
    let s = p.s;
    let mut names: Vec<String> = s.unary.iter().filter_map(|f| SKILL_PARTS.iter().find_map(|x| f.strip_suffix(x))).filter(|n| !n.is_empty()).map(String::from).collect();
    names.sort();
    names.dedup();
    let actors = actors();
    let targets = targets();
    let items = items();
    // Where an item is used: on nothing, a place, a person, and the structures items go into.
    let item_targets: Vec<&TargetFacts> = targets.iter().filter(|t| matches!(t.class.as_str(), "none" | "place") || t.id == 9 || ["storage", "campfire", "remains"].contains(&t.kind.as_str()) || (t.class == "structure" && s.structure(&t.kind).fire())).collect();
    for skill in &names {
        let takes_item = s.skills.get(skill).is_none_or(|k| k.needs_item) || ["build", "craft"].contains(&skill.as_str());
        let mut samples: Vec<SkillCtx> = Vec::new();
        for a in &actors {
            for t in &targets {
                samples.push(sample(skill, a, t, ""));
            }
        }
        if takes_item {
            for item in &items {
                for t in &item_targets {
                    samples.push(sample(skill, &actors[0], t, item));
                }
            }
        }
        for mut c in samples {
            let has = |part: &str| s.unary.contains(&format!("{skill}{part}"));
            if has("_check") {
                let f = format!("{skill}_check");
                let d = p.ctx(&f, &c)?;
                let why = d.into_string().map_err(|t| format!("install refused: `{f}` must return a string, got {t} ({})", describe(&c)))?;
                if !why.is_empty() {
                    continue;
                }
            }
            if has("_duration") {
                let f = format!("{skill}_duration");
                let d = p.ctx(&f, &c)?;
                super::number(&d).ok_or_else(|| format!("install refused: `{f}` must return a number ({})", describe(&c)))?;
            }
            if has("_done") {
                let f = format!("{skill}_done");
                let d = p.ctx(&f, &c)?;
                super::decode_effects(&f, d).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
            }
            if has("_missile") {
                let f = format!("{skill}_missile");
                let d = p.ctx(&f, &c)?;
                super::decode_missile(&f, d).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
                // What the missile does to the creature it strikes.
                c.target = targets[3].clone();
            }
            if has("_hit") {
                let f = format!("{skill}_hit");
                let d = p.ctx(&f, &c)?;
                super::decode_effects(&f, d).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
            }
        }
    }
    Ok(())
}

/// Events the engine tells the rules of, besides a skill done (`on_<skill>`).
pub const EVENTS: [&str; 2] = ["expire", "death"];

/// Every hook, on the samples its event comes with: a skill's on that skill's samples, a record
/// falling due on each sample record, a death on each body. A hook returns only record, tell
/// and witness effects.
fn hooks(p: &mut Probe) -> Result<(), String> {
    let s = p.s;
    let mut hooks: Vec<String> = s.unary.iter().filter_map(|f| f.strip_prefix("on_")).map(String::from).collect();
    hooks.sort();
    let actors = actors();
    let targets = targets();
    for event in &hooks {
        if s.skills.get(event).is_none() && !EVENTS.contains(&event.as_str()) {
            return Err(format!("install refused: `on_{event}`: the engine calls on_<skill> after a skill is done, on_expire and on_death"));
        }
        let mut samples: Vec<SkillCtx> = Vec::new();
        match event.as_str() {
            "expire" => {
                for r in records() {
                    for a in &actors[..2] {
                        samples.push(SkillCtx { record: Some(r.clone()), ..sample("", a, &targets[3], "") });
                    }
                }
            },
            "death" => samples.extend(actors.iter().map(|a| sample("", a, &targets[0], ""))),
            skill => {
                for a in &actors {
                    for t in &targets {
                        for item in ["", "wood", "berries", "lodging"] {
                            samples.push(SkillCtx { qty: 2, ..sample(skill, a, t, item) });
                        }
                    }
                }
            },
        }
        let f = format!("on_{event}");
        for c in samples {
            let d = p.ctx(&f, &c)?;
            let fx = super::decode_effects(&f, d).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
            if let Some(e) = fx.iter().find(|e| !e.of_a_hook()) {
                return Err(format!("install refused: `{f}` returned {e:?}: a hook only makes, amends and closes records, tells and is seen"));
            }
        }
    }
    Ok(())
}

/// Records of each kind the shipped rules make, as a party to them sees them.
pub fn records() -> Vec<crate::records::RecordFacts> {
    use crate::records::{RecordFacts, COMMUNITY};
    let t = |v: serde_json::Value| v.as_object().cloned().unwrap_or_default();
    let deal = |from_done: i64, to_done: i64| t(serde_json::json!({"from_gives": "berries", "from_qty": 3, "to_gives": "wood", "to_qty": 10, "from_done": from_done, "to_done": to_done, "from_home": "10,10", "to_home": "", "words": "stack the wood at my store by dark", "due_h": 8.0}));
    vec![
        RecordFacts { id: 1, kind: "agreement".into(), status: "offered".into(), open: true, terms: deal(0, 0), parties: vec![("from".into(), 9), ("to".into(), 1)], me: "to".into(), by: 9, age_s: 30.0, due_s: Some(100.0) },
        RecordFacts { id: 2, kind: "agreement".into(), status: "agreed".into(), open: true, terms: deal(0, 4), parties: vec![("from".into(), 1), ("to".into(), 9)], me: "from".into(), by: 1, age_s: 300.0, due_s: Some(200.0) },
        RecordFacts { id: 3, kind: "agreement".into(), status: "agreed".into(), open: true, terms: deal(0, 10), parties: vec![("from".into(), 9), ("to".into(), 1)], me: "to".into(), by: 9, age_s: 300.0, due_s: Some(0.0) },
        RecordFacts { id: 4, kind: "agreement".into(), status: "kept".into(), open: false, terms: deal(3, 10), parties: vec![("from".into(), 9), ("to".into(), 1)], me: "to".into(), by: 9, age_s: 900.0, due_s: Some(60.0) },
        RecordFacts { id: 5, kind: "demand".into(), status: "open".into(), open: true, terms: t(serde_json::json!({"item": "berries", "qty": 2, "done": 0, "words": "the gate-due"})), parties: vec![("by".into(), 9), ("of".into(), 1)], me: "of".into(), by: 9, age_s: 20.0, due_s: Some(40.0) },
        RecordFacts { id: 6, kind: "demand".into(), status: "open".into(), open: true, terms: t(serde_json::json!({"item": "wood", "qty": 1, "done": 0, "words": ""})), parties: vec![("by".into(), 1), ("of".into(), 9)], me: "by".into(), by: 1, age_s: 20.0, due_s: Some(0.0) },
        RecordFacts { id: 7, kind: "regard".into(), status: "held".into(), open: true, terms: t(serde_json::json!({"label": "rival town", "value": -40, "why": "the broken match"})), parties: vec![("holder".into(), COMMUNITY | 2), ("toward".into(), COMMUNITY | 3)], me: "holder".into(), by: 0, age_s: 9_000.0, due_s: None },
    ]
}

/// How each sample record reads to its party.
fn record_texts(p: &mut Probe) -> Result<(), String> {
    if !p.s.has("record_text") {
        return Ok(());
    }
    for r in records() {
        let d = p.raw("record_text", (super::context::record_map(&r),), &|| format!("for a {} record ({})", r.kind, r.status))?;
        if !d.is_string() {
            return Err(format!("install refused: `record_text` must return a text (a {} record)", r.kind));
        }
    }
    Ok(())
}

fn regard(p: &mut Probe) -> Result<(), String> {
    if !p.s.has("perceived_of") {
        return Ok(());
    }
    for (observer, target) in [("person", "person"), ("wolf", "wolf"), ("wolf", "person"), ("person", "deer")] {
        for (known, revealed, own, night) in [(false, false, false, false), (true, false, false, true), (false, true, false, false), (true, true, true, false)] {
            let dist = if night { 30 } else { 4 };
            let r = RegardIn { observer_kind: observer.into(), knows: vec!["fire".into(), "wound_tending".into()], target_kind: target.into(), known, revealed: if revealed { vec!["health".into()] } else { vec![] }, own, night, dist };
            let d = p.raw("perceived_of", (super::regard_map(&r),), &|| format!("for a {observer} looking at a {target}"))?;
            super::decode_regard(d, &r).map_err(|e| format!("install refused: {e} (a {observer} looking at a {target})"))?;
        }
    }
    Ok(())
}

/// How light it is, at every half hour of the day: a number from 0 to 1.
fn daylight(p: &mut Probe) -> Result<(), String> {
    if !p.s.has("daylight") {
        return Ok(());
    }
    for half in 0..48 {
        let h = half as f64 / 2.0;
        let d = p.raw("daylight", (h,), &|| format!("at hour {h}"))?;
        match super::number(&d) {
            Some(v) if (0.0..=1.0).contains(&v) => {},
            _ => return Err(format!("install refused: `daylight({h})` must return a number from 0 (night) to 1 (day), got {d}")),
        }
    }
    Ok(())
}

/// A world's life table: the `life_years` law over a person's table (the shipped one's
/// numbers; the engine gives it each species' own) gives ages in order within the lifespan.
fn life_years(s: &Scripts) -> Result<(), String> {
    let person = crate::life::Life { years: 70.0, infant: 0.03, child: 0.23, elder: 0.85, old_age: 0.87, gestation: 0.011, litter: 1, interbirth: 0.03, breeding_radius: 0.0 };
    for (kind, base) in [("person", person), ("wolf", crate::life::Life::default())] {
        s.life_law(kind, base).map_err(|e| format!("install refused: {e}"))?;
    }
    Ok(())
}

pub(super) fn sample(skill: &str, a: &ActorFacts, t: &TargetFacts, item: &str) -> SkillCtx {
    let mut c = SkillCtx { actor: a.clone(), target: t.clone(), item: item.into(), skill: skill.into(), season: "summer".into(), hour: 12.0, roll: 0.2, want: "wood".into(), want_qty: 2, ..Default::default() };
    // The actor's records come with it (the first body holds every kind).
    c.records = if a.id == 1 { records() } else { Vec::new() };
    if t.class == "creature" && t.id == 0 {
        c.target.id = a.id as u64;
    }
    match skill {
        "found" | "write" | "say" => c.text = "a new way of doing things".into(),
        // A reworked routine arrives whole as the act's text: up to 32,000 characters
        // (authority act.rs), far past the engine's string limit, which bounds only what a script
        // builds.
        "rework" => c.text = format!("{{\"first\": [{}]}}", "{\"do\": \"rest\"}, ".repeat(1_800)),
        _ => {},
    }
    if skill == "rework" {
        c.routine = RoutineFacts { exists: true, ok: 2, failed: 2, changed_s: 1_000.0 };
    }
    if skill == "wait" || skill == "block" {
        c.qty = 3;
    }
    c
}

/// People of each age and both animals, in the states the engine hands the laws.
pub fn actors() -> Vec<ActorFacts> {
    let all_items: Vec<(String, u32)> = catalog::item_names().into_iter().map(|i| (i, 3)).collect();
    let all_known: Vec<String> = catalog::technique_names();
    let base = ActorFacts { id: 1, kind: "person".into(), hp: 70.0, hunger: 40.0, energy: 80.0, terrain: "grass".into(), age: 20.0, stage: "adult".into(), life: 0.3, kin_near: 2, pasture: 5.0, room: 25, ..Default::default() };
    vec![
        ActorFacts { inv: all_items, knows: all_known, practice: [("strike".to_string(), 30)].into(), community: crate::records::COMMUNITY | 2, home: "10,10".into(), ..base.clone() },
        ActorFacts { id: 2, hp: 20.0, hunger: 100.0, energy: 0.0, terrain: "forest".into(), activity: "sleep".into(), stage: "elder".into(), age: 60.0, life: 0.95, near_shelter: true, hurt_by: 7, hurt_ago: Some(2_000.0), yielded_ago: Some(1_000.0), room: 12, ..base.clone() },
        ActorFacts { id: 3, hunger: 60.0, energy: 50.0, terrain: "dirt".into(), activity: "rest".into(), stage: "child".into(), age: 6.0, life: 0.1, inv: vec![("berries".into(), 2)], ..base.clone() },
        ActorFacts { id: 4, energy: 30.0, stage: "infant".into(), age: 0.5, life: 0.01, near_fire: true, ..base.clone() },
        ActorFacts { id: 5, kind: "wolf".into(), hunger: 90.0, energy: 60.0, sensed: vec![("deer".into(), 1)], hurt_by: 9, hurt_ago: Some(5_000.0), activity: "block".into(), ..base.clone() },
        ActorFacts { id: 6, kind: "deer".into(), hunger: 50.0, energy: 8.0, bold: true, ..base },
    ]
}

/// Every kind of target: none, a place, oneself, people, animals, the dead, each resource and
/// each structure.
pub fn targets() -> Vec<TargetFacts> {
    let creature = |kind: &str, id: u64, hp: f32, max_hp: f32| TargetFacts { class: "creature".into(), id, kind: kind.into(), name: if kind == "person" { "Grim".into() } else { String::new() }, hp, max_hp, stage: "adult".into(), hurt_ago: 20_000.0, alive: true, dist: 1.0, ..Default::default() };
    let mut v = vec![
        TargetFacts { class: "none".into(), ..Default::default() },
        TargetFacts { class: "place".into(), dist: 1.0, bearing: 0.5, ..Default::default() },
        // Oneself (the sample gives it the actor's id).
        TargetFacts { hp: 50.0, ..creature("person", 0, 50.0, 100.0) },
        TargetFacts { inv: vec![("berries".into(), 2), ("armor".into(), 1), ("hide".into(), 3)], knows: vec!["fire".into()], company: 0, closing: 1.0, bearing: 0.2, yielded_ago: Some(3_000.0), community: crate::records::COMMUNITY | 3, home: "40,12".into(), ..creature("person", 9, 40.0, 100.0) },
        TargetFacts { stage: "child".into(), activity: "sleep".into(), dist: 3.0, ..creature("person", 10, 100.0, 100.0) },
        TargetFacts { stage: "infant".into(), inv: vec![("berries".into(), 3)], near_fire: true, ..creature("person", 11, 100.0, 100.0) },
        TargetFacts { hurt_ago: 1e9, dist: 1.2, ..creature("wolf", 12, 55.0, 55.0) },
        creature("deer", 13, 40.0, 40.0),
        TargetFacts { alive: false, hp: 0.0, ..creature("person", 14, 0.0, 100.0) },
    ];
    for kind in catalog::resource_names() {
        v.push(TargetFacts { class: "resource".into(), id: 20, kind: kind.to_string(), amount: 5.0, dist: 1.0, ..Default::default() });
    }
    for kind in catalog::structure_names() {
        v.push(TargetFacts { class: "structure".into(), id: 30, kind: kind.to_string(), dist: 1.0, inv: vec![("berries".into(), 5), ("meat".into(), 2), ("wood".into(), 3)], ..Default::default() });
        // Someone's household store.
        if kind == "storage" {
            v.push(TargetFacts { class: "structure".into(), id: 31, kind: kind.to_string(), dist: 1.0, owner: 9, home: "40,12".into(), ..Default::default() });
        }
        // A fire burning with some fuel left (the samples above are out, with none).
        v.push(TargetFacts { class: "structure".into(), id: 32, kind: kind.to_string(), dist: 1.0, lit: true, fuel: 3.0, ..Default::default() });
    }
    v
}

/// Every item and technique, and the words the engine passes as items.
pub fn items() -> Vec<String> {
    let mut v: Vec<String> = catalog::item_names().into_iter().chain(catalog::technique_names()).collect();
    v.extend(catalog::structure_names().into_iter().chain(catalog::TERRAIN_BUILDS.iter().map(|s| s.to_string())));
    v.extend(["food", "top level", "retire", "tablet", "sign", "alarm"].map(String::from));
    v.sort();
    v.dedup();
    v
}

#[cfg(test)]
mod tests {
    use super::super::{context, Limits, Scripts, LIMITS};
    use super::*;

    const SKILLS: &str = include_str!("../../../scripts/skills.rhai");

    /// The rules with `overlay`'s functions in place of theirs, as a floor composes them.
    /// The shipped rules with `overlay` (and a description for the test skill `zap`).
    fn refused(overlay: &str) -> String {
        let overlay = format!("{overlay}\nfn zap_spec() {{ #{{ target: true, about: \"a test skill that zaps\" }} }}");
        let s = Scripts::new(&crate::floors::compose(SKILLS, &overlay).unwrap()).expect("compiles");
        s.validate().expect_err("refused")
    }

    #[test]
    fn the_rules_pass_their_install_checks() {
        let s = Scripts::new(SKILLS).unwrap();
        let r = s.validate().unwrap();
        let (f, n) = r.heaviest().unwrap();
        assert!(n * 2 <= LIMITS.operations, "{f} takes {n} operations; the limit is {}", LIMITS.operations);
        assert!(r.ops.contains_key("rates") && r.ops.contains_key("strike_done") && r.ops.contains_key("combat_cooldown") && r.ops.contains_key("perceived_of"), "{r:?}");
    }

    #[test]
    fn an_install_names_the_function_it_refuses() {
        // A law that reads a field the engine does not provide.
        let why = refused("fn rates(a) { #{ hunger: a.actor.hungr, energy: 0.0, hp: 0.0 } }");
        assert!(why.contains("rates reads `a.actor.hungr`") && why.contains("hunger"), "{why}");
        assert!(refused("fn zap_check(a) { if a.target.colour == \"red\" { \"no\" } else { \"\" } }").contains("zap_check reads `a.target.colour`"));
        // A skill whose effects fail on a state the engine sends.
        let why = refused("fn zap_check(a) { \"\" }\nfn zap_done(a) { [#{ op: \"damage\", amount: a.qty / 0 }] }");
        assert!(why.contains("`zap_done` failed"), "{why}");
        // An effect the engine does not know, and a check that is not a reason.
        assert!(refused("fn zap_done(a) { [#{ op: \"teleport\" }] }").contains("unknown effect op `teleport`"));
        assert!(refused("fn zap_check(a) { 3 }").contains("`zap_check` must return a string"));
        // A law that runs past the engine's limit on operations.
        let why = refused("fn zap_duration(a) { let n = 0; while true { n += 1; } n }");
        assert!(why.contains("`zap_duration` failed") && why.contains("operations"), "{why}");
        // A number looked up by a name that is not a number.
        assert!(refused("fn lunge(kind) { if kind == \"wolf\" { \"far\" } else { 0.6 } }").contains("`lunge(\"wolf\")` must return a number"));
        assert!(refused("fn perceived_of(p) { #{ name: p.observer.name } }").contains("perceived_of"));
    }

    /// A law called with only the fields it reads answers exactly as with the whole context,
    /// over every install sample.
    #[test]
    fn lean_contexts_answer_as_the_whole_context_does() {
        let s = Scripts::new(SKILLS).unwrap();
        let (actors, targets) = (actors(), targets());
        let mut compared = 0;
        let mut lean_fields = 0;
        for f in s.ctx_laws() {
            let plan = s.plan(&f);
            lean_fields += (plan.actor.count_ones() + plan.target.count_ones()) as usize;
            for a in &actors {
                for t in &targets {
                    for item in ["", "berries", "cloak", "fire", "spear", "storage"] {
                        let mut c = sample(f.split('_').next().unwrap_or(""), a, t, item);
                        c.night = compared % 3 == 0;
                        c.raining = compared % 5 == 0;
                        let knack = s.shapes.knack(&c.skill).to_string();
                        let call = |p: &context::Plan| format!("{:?}", s.engine.call_fn::<Dynamic>(&mut Scope::new(), &s.ast, &f, (context::map(&c, &knack, p),)));
                        assert_eq!(call(&plan), call(&context::Plan::all()), "{f} {}", describe(&c));
                        compared += 1;
                    }
                }
            }
        }
        assert!(compared > 10_000 && lean_fields > 0, "{compared} calls compared");
        // What the hot laws read.
        let fields: std::collections::BTreeMap<String, Vec<String>> = s.law_fields().into_iter().collect();
        assert_eq!(fields["rates"], ["actor.kind", "actor.near_fire", "actor.near_shelter", "actor.activity", "actor.stage", "actor.inv[cloak]", "night", "season", "raining"]);
        assert!(!fields["strike_check"].iter().any(|f| f == "*" || f.starts_with("routine")), "{:?}", fields["strike_check"]);
    }

    /// The limits and what the rules use of them: `cargo test -p living-rules --release
    /// measure_limits -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn measure_limits() {
        let s = Scripts::new(SKILLS).unwrap();
        let r = s.validate().unwrap();
        let mut v: Vec<(&String, &u64)> = r.ops.iter().collect();
        v.sort_by(|a, b| b.1.cmp(a.1));
        println!("{} calls; operations per function (max over the samples):", r.calls);
        for (f, n) in &v {
            println!("  {f:24} {n}");
        }
        let passes = |l: Limits| Scripts::new(SKILLS).ok().filter(|_| super::super::engine_with(l, &Default::default()).compile(SKILLS).is_ok()).is_some_and(|s| validate(&s, l).is_ok());
        let least = |set: &dyn Fn(usize) -> Limits, hi: usize| {
            let (mut lo, mut hi) = (1usize, hi);
            while lo < hi {
                let mid = (lo + hi) / 2;
                if passes(set(mid)) {
                    hi = mid;
                } else {
                    lo = mid + 1;
                }
            }
            lo
        };
        println!("least that pass: string {}, array {}, map {}, expr depth {} / {} (in functions), call levels {}",
            least(&|n| Limits { string: n, ..LIMITS }, LIMITS.string),
            least(&|n| Limits { array: n, ..LIMITS }, LIMITS.array),
            least(&|n| Limits { map: n, ..LIMITS }, LIMITS.map),
            least(&|n| Limits { expr_depth: (n, LIMITS.expr_depth.1.min(n)), ..LIMITS }, LIMITS.expr_depth.0),
            least(&|n| Limits { expr_depth: (LIMITS.expr_depth.0, n), ..LIMITS }, LIMITS.expr_depth.1),
            least(&|n| Limits { call_levels: n, ..LIMITS }, LIMITS.call_levels));
        for (f, p) in s.law_fields() {
            println!("  {f:24} {}", p.join(" "));
        }
    }
}
