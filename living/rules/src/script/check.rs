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
use rhai::{Dynamic, Map, Scope};
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
}

impl Probe<'_> {
    fn raw(&mut self, f: &str, args: impl rhai::FuncArgs, about: &dyn Fn() -> String) -> Result<Dynamic, String> {
        self.count.set(0);
        let r = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.s.ast, f, args);
        let n = self.count.get();
        let e = self.report.ops.entry(f.to_string()).or_insert(0);
        *e = (*e).max(n);
        self.report.calls += 1;
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
pub const CTX_LAWS: [&str; 3] = ["rates", "body_state", "move_speed"];

pub fn validate(s: &Scripts, limits: super::Limits) -> Result<Report, String> {
    // Every law reads only fields the engine provides.
    for f in s.ctx_laws() {
        Plan::of(&f, s.fields.of(&f, 1).and_then(|u| u.first()), true).map_err(|e| format!("install refused: {e}"))?;
    }
    let count = Rc::new(Cell::new(0u64));
    let mut engine = super::engine_with(limits);
    let c2 = count.clone();
    engine.on_progress(move |n| {
        c2.set(n);
        None
    });
    let mut p = Probe { s, engine, count, report: Report::default(), seen: Default::default() };
    laws_and_tables(&mut p)?;
    needs(&mut p)?;
    skills(&mut p)?;
    regard(&mut p)?;
    Ok(p.report)
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
    if s.has("skill_io") {
        for k in catalog::SKILLS {
            let d = p.raw("skill_io", (k.name.to_string(),), &|| format!("for `{}`", k.name))?;
            let ok = d.clone().try_cast::<Map>().is_some_and(|m| m.values().all(|v| v.is_string()));
            if !ok {
                return Err(format!("install refused: `skill_io(\"{}\")` must return a map of texts", k.name));
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
            let c = SkillCtx { actor: a, night, raining, season: season.into(), hour: if night { 23.0 } else { 12.0 }, ..Default::default() };
            if s.has("rates") {
                let d = p.ctx("rates", &c)?;
                super::NeedLaw::from_dynamic(d).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
            }
            if s.has("body_state") {
                let d = p.ctx("body_state", &c)?;
                super::decode_body(d).map_err(|e| format!("install refused: {e} ({})", describe(&c)))?;
            }
            if s.has("move_speed") {
                let d = p.ctx("move_speed", &c)?;
                super::number(&d).ok_or_else(|| format!("install refused: move_speed must return a number ({})", describe(&c)))?;
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
    let item_targets: Vec<&TargetFacts> = targets.iter().filter(|t| matches!(t.class.as_str(), "none" | "place") || t.id == 9 || ["storage", "campfire", "remains"].contains(&t.kind.as_str())).collect();
    for skill in &names {
        let takes_item = catalog::skill(skill).is_none_or(|k| k.needs_item) || ["build", "craft"].contains(&skill.as_str());
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

fn regard(p: &mut Probe) -> Result<(), String> {
    if !p.s.has("perceived_of") {
        return Ok(());
    }
    for (observer, target) in [("person", "person"), ("wolf", "wolf"), ("wolf", "person"), ("person", "deer")] {
        for (known, revealed, own, night) in [(false, false, false, false), (true, false, false, true), (false, true, false, false), (true, true, true, false)] {
            let r = RegardIn { observer_kind: observer.into(), knows: vec!["fire".into(), "mending".into()], target_kind: target.into(), known, revealed: if revealed { vec!["health".into()] } else { vec![] }, own, night };
            let d = p.raw("perceived_of", (super::regard_map(&r),), &|| format!("for a {observer} looking at a {target}"))?;
            super::decode_regard(d, &r).map_err(|e| format!("install refused: {e} (a {observer} looking at a {target})"))?;
        }
    }
    Ok(())
}

fn sample(skill: &str, a: &ActorFacts, t: &TargetFacts, item: &str) -> SkillCtx {
    let mut c = SkillCtx { actor: a.clone(), target: t.clone(), item: item.into(), skill: skill.into(), season: "summer".into(), hour: 12.0, roll: 0.2, ..Default::default() };
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
    let all_items: Vec<(String, u32)> = catalog::ITEMS.iter().map(|i| (i.name.to_string(), 3)).collect();
    let all_known: Vec<String> = catalog::TECHNIQUES.iter().map(|t| t.name.to_string()).collect();
    let base = ActorFacts { id: 1, kind: "person".into(), hp: 70.0, hunger: 40.0, energy: 80.0, terrain: "grass".into(), age: 20.0, stage: "adult".into(), life: 0.3, kin_near: 2, pasture: 5.0, room: 25, ..Default::default() };
    vec![
        ActorFacts { inv: all_items, knows: all_known, practice: [("strike".to_string(), 30)].into(), ..base.clone() },
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
        TargetFacts { inv: vec![("berries".into(), 2), ("armor".into(), 1), ("hide".into(), 3)], knows: vec!["fire".into()], company: 0, closing: 1.0, bearing: 0.2, yielded_ago: Some(3_000.0), ..creature("person", 9, 40.0, 100.0) },
        TargetFacts { stage: "child".into(), activity: "sleep".into(), dist: 3.0, ..creature("person", 10, 100.0, 100.0) },
        TargetFacts { stage: "infant".into(), inv: vec![("berries".into(), 3)], near_fire: true, ..creature("person", 11, 100.0, 100.0) },
        TargetFacts { hurt_ago: 1e9, dist: 1.2, ..creature("wolf", 12, 55.0, 55.0) },
        creature("deer", 13, 40.0, 40.0),
        TargetFacts { alive: false, hp: 0.0, ..creature("person", 14, 0.0, 100.0) },
    ];
    for (kind, _) in catalog::RESOURCES {
        v.push(TargetFacts { class: "resource".into(), id: 20, kind: kind.to_string(), amount: 5.0, dist: 1.0, ..Default::default() });
    }
    for kind in catalog::STRUCTURES {
        v.push(TargetFacts { class: "structure".into(), id: 30, kind: kind.to_string(), dist: 1.0, inv: vec![("berries".into(), 5), ("meat".into(), 2), ("wood".into(), 3)], ..Default::default() });
    }
    v
}

/// Every item and technique, and the words the engine passes as items.
pub fn items() -> Vec<String> {
    let mut v: Vec<String> = catalog::ITEMS.iter().map(|i| i.name.to_string()).chain(catalog::TECHNIQUES.iter().map(|t| t.name.to_string())).collect();
    v.extend(catalog::STRUCTURES.iter().chain(catalog::TERRAIN_BUILDS).map(|s| s.to_string()));
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
    fn refused(overlay: &str) -> String {
        let s = Scripts::new(&crate::floors::compose(SKILLS, overlay).unwrap()).expect("compiles");
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
        let passes = |l: Limits| Scripts::new(SKILLS).ok().filter(|_| super::super::engine_with(l).compile(SKILLS).is_ok()).is_some_and(|s| validate(&s, l).is_ok());
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
