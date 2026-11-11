//! The goods audit (goods-3, [docs/GOODS.md](../../../docs/GOODS.md)): for a world, its rules
//! composed as it is created and its seed, every item and every kind of structure, where it comes
//! from and what it is for. Built from the rules, not written by hand:
//!
//! - **where a thing comes from**: the resource kinds the world has (wild, where the seed's
//!   `resource_scale` lets them grow, or placed by its plan or `resource_nodes`) and what each
//!   `yields`; the creature kinds it has and what each leaves in its remains (`carcass`); every
//!   recipe of `recipes()` by every way (make, craft, cook, smoke, build, pave), its inputs, tools,
//!   workplace and fuel; what every other skill's effects add (gathering, clearing, writing,
//!   planting), called on sample targets; and what the engine itself makes (a death leaves
//!   remains, writing a tablet or a sign, planting a berry bush, a trap meat while the trap law
//!   says so);
//! - **what a thing is for**: the recipes and acts that use it up or hold it as a tool, the fires
//!   it feeds, its nutrition, the room it adds to a pack (`room`), what every law and skill reads
//!   of a pack by name (the install's own field analysis: a spear for `attack`, a cloak for
//!   `rates`), what a structure kind does (its traits, the recipes made at it, the acts that pass
//!   only at it), and what the world's laws say it is kept for (`kept_for`).
//!
//! A thing has a source in the world when one of those makes it from things that have sources
//! (the inputs, which are used up, and the fuel); a tool held and the workplace are not used up,
//! so a seeded one serves. The audit fails for a thing the seed holds or places with no source in
//! the world, and for a thing with a source and no use, unless the world's laws mark it so on
//! purpose with the reason (`seeded`, `kept_for`); and for a `seeded` mark on a thing that has a
//! source. A thing that has no source and that the seed does not hold is not in that world (the
//! island's glass), and is listed as such.
//!
//! ```text
//! cargo test -p living-rules --lib goods_audit -- --nocapture          # the tables
//! just living-goods                                                    # writes docs/GOODS.md's tables
//! ```

use std::collections::{BTreeMap, BTreeSet};

use serde_json::Value;

use crate::script::{ActorFacts, Effect, Scripts, SkillCtx, TargetFacts};

/// One thing of a world, as the audit finds it.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Row {
    pub name: String,
    /// How it is come by in this world: each way whose inputs have sources here.
    pub sources: Vec<String>,
    /// Ways to make it that this world cannot follow, and what they lack.
    pub blocked: Vec<String>,
    /// What it is for here.
    pub uses: Vec<String>,
    /// How many the seed holds or places at the start (`None`: placed by the town generator,
    /// not counted here).
    pub seeded: Option<u64>,
    /// The world's laws' notes: why only the seed gives it, and what it is kept for.
    pub seeded_note: String,
    pub kept_for: String,
    pub verdict: Verdict,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub enum Verdict {
    /// It has a source in the world and a use.
    #[default]
    Sourced,
    /// Only the seed gives it, on purpose: the laws say why (`seeded`).
    SeedOnly,
    /// Not in this world: nothing here makes it and the seed holds none.
    Absent,
    /// What is wrong.
    Gap(String),
}

impl Verdict {
    fn word(&self) -> String {
        match self {
            Verdict::Sourced => "made here".into(),
            Verdict::SeedOnly => "seed only, on purpose".into(),
            Verdict::Absent => "not in this world".into(),
            Verdict::Gap(g) => format!("**gap**: {g}"),
        }
    }
}

/// A world's goods.
#[derive(Clone, Debug, Default)]
pub struct Audit {
    pub world: String,
    pub items: Vec<Row>,
    pub structures: Vec<Row>,
    /// The resource kinds the world has, and how they come to be there.
    pub resources: Vec<(String, String)>,
    /// The creature kinds it has.
    pub creatures: Vec<String>,
}

impl Audit {
    /// Every gap, as "item glass: …".
    pub fn gaps(&self) -> Vec<String> {
        let mut out = Vec::new();
        for (what, rows) in [("item", &self.items), ("structure", &self.structures)] {
            for r in rows {
                if let Verdict::Gap(g) = &r.verdict {
                    out.push(format!("{} {what} {}: {g}", self.world, r.name));
                }
            }
        }
        out
    }

    /// The tables, as Markdown.
    pub fn markdown(&self) -> String {
        let cell = |v: &[String]| if v.is_empty() { "—".to_string() } else { v.join("; ").replace('|', "\\|") };
        let seeded = |r: &Row| match r.seeded {
            None => "the town generator".to_string(),
            Some(0) => "—".to_string(),
            Some(n) => n.to_string(),
        };
        let note = |r: &Row| {
            let mut v = vec![r.verdict.word()];
            if !r.seeded_note.is_empty() {
                v.push(format!("seeded: {}", r.seeded_note));
            }
            if !r.kept_for.is_empty() {
                v.push(format!("kept for: {}", r.kept_for));
            }
            if !r.blocked.is_empty() && r.verdict != Verdict::Sourced {
                v.push(format!("cannot be made here: {}", r.blocked.join("; ")));
            }
            v.join(". ").replace('|', "\\|")
        };
        let mut s = String::new();
        s += &format!("Resources: {}. Creatures: {}.\n\n", self.resources.iter().map(|(k, how)| format!("{k} ({how})")).collect::<Vec<_>>().join(", "), if self.creatures.is_empty() { "none".to_string() } else { self.creatures.join(", ") });
        for (title, rows) in [("Items", &self.items), ("Structures", &self.structures)] {
            s += &format!("**{title}**\n\n| {} | Comes from | Used for | In the seed | Verdict |\n| --- | --- | --- | --- | --- |\n", if title == "Items" { "Item" } else { "Kind" });
            for r in rows {
                s += &format!("| {} | {} | {} | {} | {} |\n", r.name, cell(&r.sources), cell(&r.uses), seeded(r), note(r));
            }
            s += "\n";
        }
        s
    }
}

/// A way something is come by: what it uses up, holds and needs, and what it gives.
#[derive(Clone, Debug, Default)]
struct Maker {
    words: String,
    /// What it makes, as a use of its inputs reads ("in glass", "in a wall").
    label: String,
    /// Each part used up: the items that satisfy it.
    takes: Vec<Vec<String>>,
    /// Each part held and kept (a tool).
    tools: Vec<Vec<String>>,
    /// Where (any of these structure kinds); empty: anywhere.
    at: Vec<String>,
    /// The fuel its heat needs, by workplace kind (a kind that burns nothing needs none).
    fuel: BTreeMap<String, Vec<String>>,
    /// A resource kind the world must have.
    resource: Option<String>,
    items: Vec<String>,
    structures: Vec<String>,
    resources: Vec<String>,
}

fn text(m: &rhai::Map, k: &str) -> Option<String> {
    m.get(k).and_then(|v| v.clone().into_string().ok()).filter(|s| !s.is_empty())
}
fn number(v: &rhai::Dynamic) -> Option<f64> {
    v.as_float().ok().or_else(|| v.as_int().ok().map(|n| n as f64))
}

/// The world: its rules and its seed.
pub struct World<'a> {
    pub name: &'a str,
    pub rules: &'a Scripts,
    pub seed: &'a Value,
}

/// Kinds of structure the town generator may place in a seed's towns (`living_rules::settle`'s
/// lots and fixtures and `seed.rs`'s houses, campfires, stores, gates and signs), for a seed
/// whose towns are generated rather than planned: the audit cannot count them offline.
const TOWN_GENERATOR: &[&str] = &["house", "inn", "hall", "workshop", "lamp", "gate", "sign", "storage", "campfire"];

fn add(m: &mut BTreeMap<String, u64>, k: &str, n: u64) {
    *m.entry(k.to_string()).or_default() += n;
}

fn counts(v: &Value, into: &mut BTreeMap<String, u64>) {
    if let Some(m) = v.as_object() {
        for (k, n) in m {
            add(into, k, n.as_u64().unwrap_or_else(|| n.as_f64().map_or(0, |f| f.max(0.0) as u64)));
        }
    }
}

/// What the seed holds and places: items (residents' packs, town stores, newcomers, a plan's
/// contents) and structures (a plan's, its lots', named buildings and homes).
fn seeded(seed: &Value) -> (BTreeMap<String, u64>, BTreeMap<String, u64>, bool) {
    let (mut items, mut kinds) = (BTreeMap::new(), BTreeMap::new());
    let mut generated = false;
    let none = Vec::new();
    for t in seed["towns"].as_array().unwrap_or(&none).iter().chain(seed["villages"].as_array().unwrap_or(&none)) {
        for r in t["residents"].as_array().unwrap_or(&none) {
            counts(&r["inventory"], &mut items);
        }
        counts(&t["stores"], &mut items);
        for b in t["buildings"].as_array().unwrap_or(&none) {
            if let Some(k) = b["kind"].as_str() {
                add(&mut kinds, k, 1);
            }
        }
        if let Some(h) = t["homes"].as_object() {
            add(&mut kinds, "house", h.len() as u64);
        }
        generated = true;
    }
    counts(&seed["newcomer"]["items"], &mut items);
    let plans = seed["map"]["params"]["plans"].as_array().cloned().unwrap_or_default();
    for p in &plans {
        for st in p["structures"].as_array().unwrap_or(&none) {
            if let Some(k) = st["kind"].as_str() {
                add(&mut kinds, k, 1);
            }
            counts(&st["contents"], &mut items);
        }
        for l in p["lots"].as_array().unwrap_or(&none) {
            if let Some(k) = l["structure"].as_str() {
                add(&mut kinds, k, 1);
            }
            counts(&l["contents"], &mut items);
        }
    }
    // A planned town is laid out by its plan, not generated.
    if !plans.is_empty() {
        generated = false;
    }
    (items, kinds, generated)
}

/// The resource kinds the world has: wild where the seed lets them grow (`resource_scale`, 1 by
/// default), and placed by a plan or the seed's `resource_nodes`.
fn resources_present(s: &Scripts, seed: &Value) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    for k in s.tables().names("resources") {
        if seed["resource_scale"][k.as_str()].as_f64().unwrap_or(1.0) > 0.0 {
            out.insert(k.clone(), "wild".to_string());
        }
    }
    let none = Vec::new();
    let mut placed = |k: &str, how: &str| {
        out.entry(k.to_string()).and_modify(|h| {
            if !h.contains(how) {
                *h += &format!(", {how}");
            }
        }).or_insert_with(|| how.to_string());
    };
    for p in seed["map"]["params"]["plans"].as_array().unwrap_or(&none) {
        for r in p["resources"].as_array().unwrap_or(&none) {
            if let Some(k) = r["kind"].as_str() {
                placed(k, "placed by the plan");
            }
        }
    }
    for r in seed["resource_nodes"].as_array().unwrap_or(&none) {
        if let Some(k) = r["kind"].as_str() {
            placed(k, "placed by the seed");
        }
    }
    out
}

/// The creature kinds the world has: its animals and packs, and people where it has residents
/// or newcomers.
fn creatures_present(seed: &Value) -> Vec<String> {
    let mut out = BTreeSet::new();
    if let Some(m) = seed["animals"].as_object() {
        for (k, n) in m {
            if n.as_u64().unwrap_or(0) > 0 {
                out.insert(k.clone());
            }
        }
    }
    let none = Vec::new();
    for p in seed["packs"].as_array().unwrap_or(&none) {
        if p["count"].as_u64().unwrap_or(0) > 0 {
            if let Some(k) = p["kind"].as_str() {
                out.insert(k.to_string());
            }
        }
    }
    let people = seed["towns"].as_array().unwrap_or(&none).iter().chain(seed["villages"].as_array().unwrap_or(&none)).any(|t| t["residents"].as_array().is_some_and(|r| !r.is_empty()));
    if people || seed.get("newcomer").is_some() {
        out.insert("person".to_string());
    }
    out.into_iter().collect()
}

/// The items that satisfy a recipe's part: the item of that name, or every item with that trait.
fn any_of(s: &Scripts, name: &str) -> Vec<String> {
    let t = s.tables();
    if t.entry("items", name).is_some() {
        vec![name.to_string()]
    } else {
        t.having("items", name)
    }
}

/// A part in words: "2 sand", "1 alkali (ash)".
/// "a furnace", "an oven".
fn a(k: &str) -> String {
    if k.starts_with(['a', 'e', 'i', 'o', 'u']) { format!("an {k}") } else { format!("a {k}") }
}

fn part_words(s: &Scripts, name: &str, qty: i64) -> String {
    let any = any_of(s, name);
    if any.len() == 1 && any[0] == name {
        format!("{qty} {name}")
    } else {
        format!("{qty} {name} ({})", any.join(" or "))
    }
}

/// Every recipe as a way of coming by things (`recipes()`, by every way, including building).
fn recipe_makers(s: &Scripts) -> Vec<Maker> {
    let mut out = Vec::new();
    let names = s.tables().names("recipes").to_vec();
    let kinds = s.tables().names("structures").to_vec();
    // "at a fire": every kind the rules' `fire_kind` takes for one.
    let fires: Vec<String> = kinds.iter().filter(|k| s.yes_of("fire_kind", k)).cloned().collect();
    for n in names {
        let Some(r) = s.tables().entry("recipes", &n).cloned() else { continue };
        let by = text(&r, "by").unwrap_or_else(|| "make".into());
        let parts = |k: &str| -> Vec<(String, i64)> {
            r.get(k).and_then(|v| v.clone().try_cast::<rhai::Map>()).map(|m| m.iter().map(|(n, q)| (n.to_string(), q.as_int().unwrap_or(1))).collect()).unwrap_or_default()
        };
        let takes = parts("takes");
        let tools = parts("tools");
        let at = match text(&r, "at") {
            None => Vec::new(),
            Some(a) if a == "fire" => fires.clone(),
            Some(a) => vec![a],
        };
        let heat = r.get("lit").is_some_and(|v| v.as_bool() == Ok(true)) || r.get("fuel").is_some_and(|v| !v.is_unit());
        let mut fuel = BTreeMap::new();
        if heat {
            for k in &at {
                if let Some(b) = &s.structure(k).burns {
                    fuel.insert(k.clone(), s.tables().having("items", &b.fuel));
                }
            }
        }
        let place = match text(&r, "at") {
            None => String::new(),
            Some(a) if a == "fire" => " at a fire".into(),
            Some(k) => format!(" at {}", a(&k)),
        };
        let held = if tools.is_empty() { String::new() } else { format!(", with {}", tools.iter().map(|(n, q)| part_words(s, n, *q)).collect::<Vec<_>>().join(", ")) };
        let know = text(&r, "knows").map_or(String::new(), |k| format!(", knowing {k}"));
        let used = |t: &[(String, i64)]| t.iter().map(|(n, q)| part_words(s, n, *q)).collect::<Vec<_>>().join(", ");
        if let Some(trait_) = text(&r, "turns") {
            for i in s.tables().having("items", &trait_) {
                let Some(p) = s.tables().entry("items", &i).and_then(|e| text(e, &trait_)) else { continue };
                out.push(Maker {
                    words: format!("{by} {i}{place}{held}{know}"),
                    label: p.clone(),
                    takes: vec![vec![i.clone()]],
                    tools: tools.iter().map(|(n, _)| any_of(s, n)).collect(),
                    at: at.clone(),
                    fuel: fuel.clone(),
                    items: vec![p],
                    ..Default::default()
                });
            }
            continue;
        }
        let gives = text(&r, "gives").unwrap_or_else(|| n.clone());
        let makes = r.get("makes").and_then(number).unwrap_or(1.0);
        let mut m = Maker {
            words: format!("{by}{} from {}{place}{held}{know}", if makes > 1.0 { format!(" {makes}") } else { String::new() }, used(&takes)),
            label: gives.clone(),
            takes: takes.iter().map(|(n, _)| any_of(s, n)).collect(),
            tools: tools.iter().map(|(n, _)| any_of(s, n)).collect(),
            at,
            fuel,
            ..Default::default()
        };
        if by == "build" || by == "pave" {
            // Building makes a structure (a wall, a bridge and road are ground, not kinds).
            if kinds.contains(&gives) {
                m.structures.push(gives);
            } else {
                m.words = format!("{by} {} from {}{know}", a(&gives), used(&takes));
                m.label = a(&gives);
            }
        } else {
            m.items.push(gives);
        }
        out.push(m);
    }
    out
}

/// A grown person who knows everything, carrying `inv`.
fn actor(s: &Scripts, inv: Vec<(String, u32)>) -> ActorFacts {
    let knows = s.tables().names("know_how").to_vec();
    ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), hp: 60.0, hunger: 50.0, energy: 80.0, inv, knows, terrain: "forest".into(), ..Default::default() }
}

/// The ways of making (skills with recipes: their effects are the table's, read above).
fn ways(s: &Scripts) -> BTreeSet<String> {
    let mut out: BTreeSet<String> = ["make".to_string()].into_iter().collect();
    for n in s.tables().names("recipes") {
        if let Some(by) = s.tables().entry("recipes", n).and_then(|r| text(r, "by")) {
            out.insert(by);
        }
    }
    // Building and paving are acts with their own rule (`build_check`), probed below as well
    // as read from the table: a script that builds by a list of its own is read the same.
    out.remove("build");
    out.remove("pave");
    out
}

/// What every other skill's effects make and use, called on sample targets: each resource kind
/// the world has, a place, nothing, and a hurt person; with no item and with each item its spec
/// lists. Effects the engine carries out by name are what it makes: writing a tablet (or, with
/// the item "sign", a sign), planting a berry bush (`act.rs`, `Effect::Write`, `Effect::Plant`).
fn act_makers(s: &Scripts, present: &BTreeMap<String, String>) -> (Vec<Maker>, BTreeMap<String, BTreeSet<String>>) {
    let mut makers = Vec::new();
    let mut uses: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let items = s.tables().names("items").to_vec();
    let pack: Vec<(String, u32)> = items.iter().map(|i| (i.clone(), 3)).collect();
    let ways = ways(s);
    let mut targets: Vec<(TargetFacts, Option<String>)> = vec![
        (TargetFacts { class: "none".into(), ..Default::default() }, None),
        (TargetFacts { class: "place".into(), dist: 1.0, ..Default::default() }, None),
        (TargetFacts { class: "creature".into(), id: 9, kind: "person".into(), alive: true, hp: 50.0, max_hp: 100.0, hurt_ago: 60_000.0, dist: 1.0, inv: pack.clone(), ..Default::default() }, None),
    ];
    for k in present.keys() {
        targets.push((TargetFacts { class: "resource".into(), id: 5, kind: k.clone(), amount: 3.0, dist: 1.0, ..Default::default() }, Some(k.clone())));
    }
    let skills: Vec<_> = s.skills().iter().filter(|k| !ways.contains(&k.name)).cloned().collect();
    let yields = |r: &str| s.tables().entry("resources", r).and_then(|e| text(e, "yields"));
    for spec in skills {
        let mut words: Vec<String> = vec![String::new()];
        words.extend(spec.items.iter().cloned());
        // What the act gives wherever it is done (clearing, writing), recorded once.
        let mut anywhere: Vec<(Vec<String>, Vec<String>, Vec<String>)> = Vec::new();
        for (t, resource) in &targets {
            for item in &words {
                let c = SkillCtx { actor: actor(s, pack.clone()), target: t.clone(), item: item.clone(), qty: 1, skill: spec.name.clone(), hour: 12.0, season: "summer".into(), text: "a note".into(), roll: 0.1, ..Default::default() };
                let Ok(fx) = s.done(&spec.name, &c) else { continue };
                let mut m = Maker { resource: resource.clone(), ..Default::default() };
                for e in &fx {
                    match e {
                        Effect::Add { item, .. } if !item.is_empty() => m.items.push(item.clone()),
                        Effect::Remove { item, qty } if !item.is_empty() => {
                            m.takes.push(vec![item.clone()]);
                            m.label.push_str(&format!("{}{qty} {item}", if m.label.is_empty() { "" } else { ", " }));
                        }
                        Effect::Fuel { item, .. } if !item.is_empty() => {
                            uses.entry(item.clone()).or_default().insert("fed to a fire (feed)".into());
                        }
                        Effect::Build { kind } if s.tables().entry("structures", kind).is_some() => m.structures.push(kind.clone()),
                        Effect::Write => {
                            if item == "sign" {
                                m.structures.push("sign".into());
                            } else {
                                m.items.push("tablet".into());
                            }
                        }
                        Effect::Plant => m.resources.push("berry_bush".into()),
                        _ => {}
                    }
                }
                if m.items.is_empty() && m.structures.is_empty() && m.resources.is_empty() {
                    // Used up by an act that makes nothing (eating, a shot, tending with a salve).
                    for t in &m.takes {
                        uses.entry(t[0].clone()).or_default().insert(spec.name.clone());
                    }
                    continue;
                }
                let gives = (m.items.clone(), m.structures.clone(), m.resources.clone());
                let takes: Vec<String> = if m.label.is_empty() { Vec::new() } else { vec![std::mem::take(&mut m.label)] };
                if let Some(r) = &resource {
                    // Gathering what the resource yields is its own source ("gathered at");
                    // what an act gives anywhere is recorded where it was first found.
                    if takes.is_empty() && m.structures.is_empty() && m.resources.is_empty() && m.items.iter().all(|i| yields(r).as_deref() == Some(i.as_str())) {
                        continue;
                    }
                    if anywhere.contains(&gives) {
                        continue;
                    }
                } else if anywhere.contains(&gives) {
                    continue;
                } else {
                    anywhere.push(gives.clone());
                }
                m.label = m.items.iter().chain(&m.structures).cloned().chain(m.resources.iter().map(|r| a(r))).collect::<Vec<_>>().join(", ");
                m.words = match (&resource, takes.is_empty()) {
                    (Some(r), true) => format!("{} at {}", spec.name, a(r)),
                    (Some(r), false) => format!("{} at {} from {}", spec.name, a(r), takes.join(", ")),
                    (None, true) => spec.name.clone(),
                    (None, false) => format!("{} from {}", spec.name, takes.join(", ")),
                };
                if !makers.iter().any(|x: &Maker| x.words == m.words && x.items == m.items && x.structures == m.structures) {
                    makers.push(m);
                }
            }
        }
    }
    (makers, uses)
}

/// What each law and skill reads of a pack by name (the install's field analysis): the item, the
/// laws reading it in the actor's pack, and in the target's.
fn reads(s: &Scripts) -> BTreeMap<String, (BTreeSet<String>, BTreeSet<String>)> {
    let mut out: BTreeMap<String, (BTreeSet<String>, BTreeSet<String>)> = BTreeMap::new();
    for (f, fields) in s.law_fields() {
        let law = ["_check", "_duration", "_done", "_hit", "_missile"].iter().find_map(|x| f.strip_suffix(x)).unwrap_or(&f).to_string();
        for d in fields {
            for (pre, target) in [("actor.inv[", false), ("target.inv[", true)] {
                let Some(list) = d.strip_prefix(pre).and_then(|r| r.strip_suffix(']')) else { continue };
                if list == "*" {
                    continue;
                }
                for i in list.split(',').filter(|i| !i.is_empty()) {
                    let e = out.entry(i.to_string()).or_default();
                    if target { e.1.insert(law.clone()) } else { e.0.insert(law.clone()) };
                }
            }
        }
    }
    out
}

/// What an act passes at a kind of structure and refuses at a kind that is none: the acts for
/// which that kind is the place (open a gate, take from a store, feed a fire).
fn acts_at(s: &Scripts, kind: &str) -> Vec<String> {
    let inv: Vec<(String, u32)> = ["wood", "fish", "peat", "stone"].iter().filter(|i| s.tables().entry("items", i).is_some()).map(|i| (i.to_string(), 1)).collect();
    let ways = ways(s);
    let mut out = Vec::new();
    for spec in s.skills().iter().filter(|k| k.needs_target && !ways.contains(&k.name)) {
        for item in ["", "wood", "fish", "fuel"] {
            let at = |k: &str| {
                let t = TargetFacts { class: "structure".into(), id: 7, kind: k.into(), dist: 1.0, lit: true, fuel: 4.0, inv: vec![("wood".into(), 3), ("fish".into(), 3)], ..Default::default() };
                let c = SkillCtx { actor: actor(s, inv.clone()), target: t, item: item.into(), qty: 1, skill: spec.name.clone(), hour: 12.0, season: "summer".into(), ..Default::default() };
                s.check(&spec.name, &c).is_ok()
            };
            if at(kind) && !at("no_such_kind") {
                out.push(spec.name.clone());
                break;
            }
        }
    }
    out
}

/// The audit of one world.
pub fn audit(w: &World) -> Audit {
    let s = w.rules;
    let present = resources_present(s, w.seed);
    let creatures = creatures_present(w.seed);
    let (held, placed, generated) = seeded(w.seed);
    let items = s.tables().names("items").to_vec();
    let kinds = s.tables().names("structures").to_vec();
    let mut makers = recipe_makers(s);
    let (acts, act_uses) = act_makers(s, &present);
    // A structure the recipe table builds is read from it (its words name the technique); the
    // probe of `build` adds only what the table does not hold.
    let built: BTreeSet<String> = makers.iter().flat_map(|m| m.structures.clone()).collect();
    makers.extend(acts.into_iter().filter(|m| m.structures.is_empty() || m.structures.iter().any(|k| !built.contains(k))));
    // What the engine makes by itself: a trap catches meat while the trap law says so (`common.rs`,
    // `trap_catch`); remains are left by a death.
    if s.trap_every_ms() > 0.0 && kinds.iter().any(|k| k == "trap") {
        makers.push(Maker { words: "caught in a trap".into(), label: "meat".into(), at: vec!["trap".into()], items: vec!["meat".into()], ..Default::default() });
    }
    let mut sources: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut have_items: BTreeSet<String> = BTreeSet::new();
    let mut have_kinds: BTreeSet<String> = BTreeSet::new();
    let mut have_res: BTreeSet<String> = present.keys().cloned().collect();
    let tables = s.tables();
    let yields = |r: &str| tables.entry("resources", r).and_then(|e| text(e, "yields"));
    for c in &creatures {
        have_kinds.insert("remains".into());
        sources.entry("s:remains".into()).or_default().push(format!("{}'s death", a(c)));
        for (i, n) in s.items_of("carcass", c) {
            sources.entry(format!("i:{i}")).or_default().push(format!("the remains of {} ({n})", a(c)));
            have_items.insert(i);
        }
    }
    sources.entry("s:remains".into()).or_default().dedup();
    // Whatever is placed is there to work at and hold, though not made.
    let stands = |k: &str, have: &BTreeSet<String>| have.contains(k) || placed.get(k).is_some_and(|n| *n > 0) || (generated && TOWN_GENERATOR.contains(&k));
    let holds = |i: &String, have: &BTreeSet<String>| have.contains(i) || held.get(i).is_some_and(|n| *n > 0);
    let mut used: Vec<bool> = vec![false; makers.len()];
    loop {
        let mut changed = false;
        for r in have_res.clone() {
            if let Some(y) = yields(&r) {
                if have_items.insert(y.clone()) {
                    changed = true;
                }
                let words = format!("gathered at {}", a(&r));
                let v = sources.entry(format!("i:{y}")).or_default();
                if !v.contains(&words) {
                    v.push(words);
                }
            }
        }
        for (j, m) in makers.iter().enumerate() {
            if used[j] {
                continue;
            }
            let fed = |k: &String| m.fuel.get(k).is_none_or(|f| f.iter().any(|i| have_items.contains(i)));
            let ok = m.takes.iter().all(|p| p.iter().any(|i| have_items.contains(i)))
                && m.tools.iter().all(|p| p.iter().any(|i| holds(i, &have_items)))
                && (m.at.is_empty() || m.at.iter().any(|k| stands(k, &have_kinds) && fed(k)))
                && m.resource.as_ref().is_none_or(|r| have_res.contains(r));
            if !ok {
                continue;
            }
            used[j] = true;
            changed = true;
            for i in &m.items {
                have_items.insert(i.clone());
                sources.entry(format!("i:{i}")).or_default().push(m.words.clone());
            }
            for k in &m.structures {
                have_kinds.insert(k.clone());
                sources.entry(format!("s:{k}")).or_default().push(m.words.clone());
            }
            for r in &m.resources {
                have_res.insert(r.clone());
            }
        }
        if !changed {
            break;
        }
    }
    drop(tables);
    // What each thing is for.
    let mut uses: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut put = |k: String, u: String| {
        let v = uses.entry(k).or_default();
        if !v.contains(&u) {
            v.push(u);
        }
    };
    for (j, m) in makers.iter().enumerate() {
        if !used[j] {
            continue;
        }
        let what = if m.label.is_empty() { m.words.clone() } else { m.label.clone() };
        for p in &m.takes {
            for i in p {
                put(format!("i:{i}"), format!("in {what}"));
            }
        }
        for p in &m.tools {
            for i in p {
                put(format!("i:{i}"), format!("tool for {what}"));
            }
        }
        for k in &m.at {
            if stands(k, &have_kinds) {
                put(format!("s:{k}"), format!("where {what} is made"));
            }
        }
    }
    for (i, laws) in act_uses {
        for l in laws {
            put(format!("i:{i}"), l);
        }
    }
    for (i, (mine, theirs)) in reads(s) {
        if !mine.is_empty() {
            put(format!("i:{i}"), format!("held: {}", mine.into_iter().collect::<Vec<_>>().join(", ")));
        }
        if !theirs.is_empty() {
            put(format!("i:{i}"), format!("worn against: {}", theirs.into_iter().collect::<Vec<_>>().join(", ")));
        }
    }
    for k in &kinds {
        let t = s.structure(k);
        if let Some(b) = &t.burns {
            if stands(k, &have_kinds) {
                for i in s.tables().having("items", &b.fuel) {
                    put(format!("i:{i}"), format!("fuel for {}", a(k)));
                }
            }
            put(format!("s:{k}"), format!("a fire that burns {}", b.fuel));
        }
        if t.warms {
            put(format!("s:{k}"), "warms".into());
        }
        if t.roof {
            put(format!("s:{k}"), "a roof".into());
        }
        if t.lights > 0.0 || t.burns.as_ref().is_some_and(|b| b.light > 0.0) {
            put(format!("s:{k}"), "lights".into());
        }
        if let Some(h) = t.holds {
            put(format!("s:{k}"), format!("a store of {h}"));
        }
        for a in acts_at(s, k) {
            put(format!("s:{k}"), a);
        }
    }
    for i in &items {
        if s.num_of("nutrition", i, 0.0) > 0.0 {
            put(format!("i:{i}"), "food".into());
        }
        if let Some(r) = s.tables().number("items", i, "room") {
            put(format!("i:{i}"), format!("{r} more room in a pack"));
        }
    }
    // The rows.
    let row = |key: String, name: &String, table: &str, count: Option<u64>| -> Row {
        let entry = s.tables().entry(table, name).cloned().unwrap_or_default();
        let mut r = Row {
            name: name.clone(),
            sources: sources.get(&key).cloned().unwrap_or_default(),
            uses: uses.get(&key).cloned().unwrap_or_default(),
            seeded: count,
            seeded_note: text(&entry, "seeded").unwrap_or_default(),
            kept_for: text(&entry, "kept_for").unwrap_or_default(),
            ..Default::default()
        };
        let made = !r.sources.is_empty();
        let in_seed = count.is_none_or(|n| n > 0);
        r.verdict = if made && !r.seeded_note.is_empty() {
            Verdict::Gap(format!("marked seed-only ({}), but it is made here", r.seeded_note))
        } else if made && r.uses.is_empty() && r.kept_for.is_empty() {
            Verdict::Gap("made here, and nothing uses it".into())
        } else if made {
            Verdict::Sourced
        } else if !r.seeded_note.is_empty() {
            Verdict::SeedOnly
        } else if in_seed {
            Verdict::Gap(match count {
                Some(n) => format!("the seed holds {n} and nothing here makes it"),
                None => "the town generator places it and nothing here builds it".into(),
            })
        } else {
            Verdict::Absent
        };
        r
    };
    let mut out = Audit { world: w.name.to_string(), resources: present.into_iter().collect(), creatures, ..Default::default() };
    for i in &items {
        let mut r = row(format!("i:{i}"), i, "items", Some(held.get(i).copied().unwrap_or(0)));
        r.blocked = blocked(s, &makers, &used, |m| m.items.contains(i), &have_items);
        out.items.push(r);
    }
    for k in &kinds {
        let count = match placed.get(k) {
            Some(n) => Some(*n),
            None if generated && TOWN_GENERATOR.contains(&k.as_str()) => None,
            None => Some(0),
        };
        let mut r = row(format!("s:{k}"), k, "structures", count);
        r.blocked = blocked(s, &makers, &used, |m| m.structures.contains(k), &have_items);
        out.structures.push(r);
    }
    out
}

/// The ways to make a thing this world cannot follow, with what they lack.
fn blocked(_s: &Scripts, makers: &[Maker], used: &[bool], makes: impl Fn(&Maker) -> bool, have: &BTreeSet<String>) -> Vec<String> {
    let mut out = Vec::new();
    for (j, m) in makers.iter().enumerate() {
        if used[j] || !makes(m) {
            continue;
        }
        let lacks: Vec<String> = m.takes.iter().filter(|p| !p.iter().any(|i| have.contains(i))).map(|p| p.join(" or ")).collect();
        let why = if lacks.is_empty() { "its tools or workplace".to_string() } else { lacks.join(", ") };
        out.push(format!("{} (no {why})", m.words));
    }
    out
}

/// The shipped worlds: the island and Cullet, each as created.
pub fn shipped_worlds() -> Vec<(&'static str, Scripts, Value)> {
    let island: Value = serde_json::from_str(include_str!("../../seeds/island.json")).expect("the island's seed parses");
    let cullet: Value = serde_json::from_str(include_str!("../../seeds/cullet.json")).expect("Cullet's seed parses");
    vec![("island", crate::cullet_check::island(), island), ("cullet", crate::cullet_check::cullet(), cullet)]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn audits() -> Vec<Audit> {
        shipped_worlds().iter().map(|(name, s, seed)| audit(&World { name, rules: s, seed })).collect()
    }

    /// Every item and structure of the island and of Cullet comes from the world or is seeded on
    /// purpose, and everything made is for something (docs/GOODS.md). `--nocapture` prints the
    /// tables.
    #[test]
    fn the_goods_come_from_the_world() {
        let mut gaps = Vec::new();
        for a in audits() {
            println!("## {}\n\n{}", a.world, a.markdown());
            gaps.extend(a.gaps());
        }
        assert!(gaps.is_empty(), "goods with no source or no use:\n{}", gaps.join("\n"));
    }

    /// What is read once when the script compiles grows with a world's goods (every recipe in
    /// the making law's words, every built kind in `build`'s): it stays within half its budget
    /// (`script::COMPILE_OPERATIONS`). `--nocapture` prints the heaviest.
    #[test]
    fn descriptions_fit_their_budget() {
        for (name, s, _) in shipped_worlds() {
            let mut heavy: Vec<(u64, String)> = s.law_specs().keys().map(|l| format!("{l}_law")).chain(s.skills().names().map(|k| format!("{k}_spec"))).filter(|f| s.has(f)).map(|f| (s.ops_of(&f), f)).collect();
            heavy.sort_by(|a, b| b.cmp(a));
            println!("{name}: {:?}", &heavy[..5]);
            assert!(heavy[0].0 * 2 <= crate::script::COMPILE_OPERATIONS, "{name}: {} takes {} operations", heavy[0].1, heavy[0].0);
        }
    }

    /// The audit reads the rules: a world whose laws drop a source, or add a made thing nothing
    /// uses, or mark seed-only what it makes, is caught.
    #[test]
    fn the_audit_finds_what_is_wrong() {
        let (_, _, seed) = shipped_worlds().remove(1);
        const BASE: &str = include_str!("../../scripts/skills.rhai");
        const CULLET: &str = include_str!("../../seeds/worlds/cullet/laws.rhai");
        let with = |laws: String| Scripts::with_day(&crate::floors::compose(BASE, &laws).unwrap(), crate::cullet_check::CULLET_DAY_MS).unwrap();
        let gaps = |laws: String| audit(&World { name: "cullet", rules: &with(laws), seed: &seed }).gaps();
        let made = "fn made_here() {\n    [\n";
        assert!(CULLET.contains(made));
        // The drops' recipe gone: the seed's 377 marks have no source.
        let g = gaps(CULLET.lines().filter(|l| !l.contains("#{ name: \"mark\", at: \"furnace\"")).collect::<Vec<_>>().join("\n"));
        assert!(g.iter().any(|g| g.contains("item mark: the seed holds 377 and nothing here makes it")), "{g:?}");
        // A bead blown of glass that nothing uses.
        let bead = CULLET.replace(made, &format!("{made}        #{{ name: \"bead\", at: \"furnace\", lit: true, takes: #{{ glass: 1 }}, knows: \"glassmaking\" }},\n")).replace("    out + [\n        // Gathered on the shore", "    out + [\n        #{ name: \"bead\" },\n        // Gathered on the shore");
        let g = gaps(bead);
        assert!(g.iter().any(|g| g.contains("item bead: made here, and nothing uses it")), "{g:?}");
        // A blowpipe made of something: its seed-only mark no longer holds.
        let g = gaps(CULLET.replace(made, &format!("{made}        #{{ name: \"blowpipe\", at: \"furnace\", lit: true, takes: #{{ glass: 3 }} }},\n")));
        assert!(g.iter().any(|g| g.contains("item blowpipe: marked seed-only")), "{g:?}");
        // The kelp beds gone from the world: ash, glass and everything of glass have no source,
        // and the seed's ash is a gap.
        let mut bare = seed.clone();
        for p in bare["map"]["params"]["plans"].as_array_mut().unwrap() {
            p["resources"].as_array_mut().unwrap().retain(|r| r["kind"] != "kelp_bed");
        }
        let g = audit(&World { name: "cullet", rules: &crate::cullet_check::cullet(), seed: &bare }).gaps();
        assert!(g.iter().any(|g| g.contains("item ash: the seed holds 3")) && g.iter().any(|g| g.contains("item mark: the seed holds 377")), "{g:?}");
    }

    /// The audit of main before goods-3 (docs/GOODS.md, "What the audit found"): main's shipped
    /// script and Cullet's laws (`LIVING_OLD_SKILLS`, `LIVING_OLD_CULLET`) over the seeds as they
    /// were (`LIVING_OLD_CULLET_SEED`; the island's seed is unchanged). Prints the gaps.
    #[test]
    #[ignore = "needs LIVING_OLD_SKILLS, LIVING_OLD_CULLET and LIVING_OLD_CULLET_SEED"]
    fn audit_of_main() {
        let read = |v: &str| std::fs::read_to_string(std::env::var(v).unwrap_or_else(|_| panic!("set {v}"))).unwrap();
        let (skills, cullet) = (read("LIVING_OLD_SKILLS"), read("LIVING_OLD_CULLET"));
        let island = Scripts::new(&skills).unwrap();
        let c = Scripts::with_day(&crate::floors::compose(&skills, &cullet).unwrap(), crate::cullet_check::CULLET_DAY_MS).unwrap();
        let seeds = shipped_worlds();
        let old_seed: Value = serde_json::from_str(&read("LIVING_OLD_CULLET_SEED")).unwrap();
        for (name, s, seed) in [("island", &island, &seeds[0].2), ("cullet", &c, &old_seed)] {
            let a = audit(&World { name, rules: s, seed });
            println!("## {name} on main: {} gaps\n{}\n", a.gaps().len(), a.gaps().join("\n"));
            println!("{}", a.markdown());
        }
    }

    /// Writes the generated tables into docs/GOODS.md between its markers.
    #[test]
    #[ignore = "writes docs/GOODS.md: `just living-goods`"]
    fn write_goods_audit() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../docs/GOODS.md");
        let doc = std::fs::read_to_string(&path).expect("docs/GOODS.md");
        let (begin, end) = ("<!-- goods-audit: begin -->", "<!-- goods-audit: end -->");
        let (head, rest) = doc.split_once(begin).expect("the begin marker");
        let (_, tail) = rest.split_once(end).expect("the end marker");
        let mut body = String::from("\n");
        for a in audits() {
            body += &format!("### {}\n\n{}", if a.world == "island" { "The island" } else { "Cullet" }, a.markdown());
        }
        std::fs::write(&path, format!("{head}{begin}{body}{end}{tail}")).unwrap();
    }
}
