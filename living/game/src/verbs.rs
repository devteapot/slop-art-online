//! Verbs: what my character can do to what is in front of it, and to itself, offered from the
//! world's own rules (docs/GAME_BRIEF.md, "Verbs").
//!
//! Nothing here is written per skill. The client knows the world's skills from its installed
//! skill script (the public `script` row, compiled here with the same `living_rules::script` the
//! authority runs): each skill's `<skill>_spec()` says whether it takes a target or an item, the
//! items it is given, its description and what it takes and gives. Whether a skill
//! applies to what I point at is the rules' own `<skill>_check`, run on what my character knows
//! (my pack, my know-how, my needs; the target as I perceive it). A skill the rules add shows up
//! here with no client change, and a check the script changes changes what is offered.
//!
//! The authority decides: an option is a guess from my side of the world, and a refused act
//! comes back as the authority's reason (my `act` experience rows, or the reducer's error), shown
//! briefly over the hint.
//!
//! - **F** acts on what is under the cursor, else the nearest thing or creature within reach:
//!   a tap does the most likely act (the one I last chose for that kind, else the first the
//!   rules allow on a thing); holding F, or a tap with nothing likely (a person), opens the list.
//!   With nothing within reach, F says so (C opens the list of acts on myself).
//! - **C** opens the list of acts on myself (eat, sleep, craft, write, ...), with what I carry.
//! - **I** and **K** toggle the inventory and the know-how panels (`ui/verbs.rs`).
//! - In a list: 1–9 and 0 or a click picks, Esc or the same key closes. A skill with many items opens
//!   a second list ("give ›"). A skill that needs words (write, found) opens the text box.
//!
//! Everything goes through `human_act` (the act path minds use; ongoing skills such as sleep
//! become my behavior), and requests in words through `human_say`.

use crate::net::Net;
use crate::world::Scene;
use bevy::prelude::*;
use living_bindings::*;
use living_rules::catalog;
use living_rules::script::{ActorFacts, Scripts, SkillCtx, TargetFacts};
use spacetimedb_sdk::Table;
use std::collections::{HashMap, HashSet};

pub const INTERACT: KeyCode = KeyCode::KeyF;
pub const SELF_ACTS: KeyCode = KeyCode::KeyC;
pub const INVENTORY: KeyCode = KeyCode::KeyI;
pub const KNOW_HOW: KeyCode = KeyCode::KeyK;
/// Held this long, F opens the list instead of acting (s).
const HOLD_S: f64 = 0.28;
/// Things under the cursor within this distance of its ground point (m).
const CURSOR_THING_M: f32 = 1.6;
/// With nothing under the cursor, the nearest thing or creature within this distance (m).
const NEAR_M: f32 = 3.0;
/// F reaches no further than this (m): an act walks into reach, but not across the map.
const FAR_M: f32 = 30.0;
/// A list shows this many rows before More (toward a thing; toward a person, the likely acts).
const FOLDED: usize = 4;
/// A skill with more item options than this gets its own list (interface D: two or more, so
/// Give › is a list of what I carry, as the design shows).
const GROUP_OVER: usize = 1;
/// How often the hint's options are recomputed (s).
const HINT_EVERY_S: f64 = 0.25;
/// Most the hint's checks take in one frame (a unit is one or two script calls of about 50 µs);
/// a job toward a person takes several frames.
const HINT_BUDGET: std::time::Duration = std::time::Duration::from_micros(1_000);
/// How long an act's outcome is awaited (ms) and shown (s).
const AWAIT_MS: f64 = 180_000.0;
const TOAST_S: f64 = 4.5;

// ---- the world's rules -----------------------------------------------------------------

/// The world's installed skill script, compiled (the authority's `common::scripts`).
#[derive(Default)]
pub struct Rules {
    pub revision: u32,
    pub scripts: Option<Scripts>,
    pub error: Option<String>,
    /// Every skill there is, as the installed script declares it.
    pub skills: Vec<Skill>,
    /// How items look by the rules' `item_look` (icon id, label), kept for the revision they were
    /// read under (a Rhai call each, so never per frame).
    looks: std::cell::RefCell<(u32, HashMap<String, (String, String)>)>,
}

/// A skill as the world's script declares it (`<skill>_spec()`): whether it takes a target or an
/// item, the items it is given, the further arguments it reads and its description.
#[derive(Clone, Debug, PartialEq)]
pub struct Skill {
    pub name: String,
    pub target: bool,
    pub item: bool,
    pub items: Vec<String>,
    pub args: Vec<String>,
    pub help: String,
}

/// The skills the compiled script declares.
pub fn skills_of(sc: &Scripts) -> Vec<Skill> {
    sc.skills().iter().map(|s| Skill { name: s.name.clone(), target: s.needs_target, item: s.needs_item, items: s.items.clone(), args: s.args.clone(), help: s.about.clone() }).collect()
}

impl Rules {
    /// How an item looks: its icon id and its label, from the world's `item_look` (goods-2: an
    /// item's `icon`, `label` traits), else its name and the name with spaces.
    pub fn item_look(&self, item: &str) -> (String, String) {
        let mut c = self.looks.borrow_mut();
        if c.0 != self.revision {
            *c = (self.revision, HashMap::new());
        }
        c.1.entry(item.to_string())
            .or_insert_with(|| match self.scripts.as_ref().and_then(|sc| sc.item_look_of("item_look", item)) {
                Some(l) if !l.icon.is_empty() => (l.icon, if l.label.is_empty() { item.replace('_', " ") } else { l.label }),
                _ => (item.to_string(), item.replace('_', " ")),
            })
            .clone()
    }

    /// Recompile when the `script` row changes (an install).
    fn refresh(&mut self, conn: &DbConnection) {
        let Some(row) = conn.db.script().name().find(&"skills".to_string()) else { return };
        if self.scripts.is_some() && row.revision == self.revision || self.error.is_some() && row.revision == self.revision {
            return;
        }
        self.revision = row.revision;
        // The world's day: laws written per game hour, and the day's words, follow it.
        let day_ms = conn.db.world().iter().next().map(|w| w.day_ms).unwrap_or(living_rules::DEFAULT_DAY_MS);
        // On the frame (a law switched mid-play recompiles too): its cost is logged, since it is
        // a hitch of that much.
        let t0 = std::time::Instant::now();
        match Scripts::with_day(&row.source, day_ms) {
            Ok(s) => {
                self.skills = skills_of(&s);
                info!("rules: skill script revision {} compiled ({} skills) in {:.1} ms on the frame", row.revision, self.skills.len(), t0.elapsed().as_secs_f64() * 1000.0);
                catalog::set_skills(s.skills().clone());
                self.scripts = Some(s);
                self.error = None;
            }
            Err(e) => {
                warn!("rules: the world's skill script does not compile here: {e}");
                self.scripts = None;
                self.error = Some(e);
            }
        }
    }
}

// ---- what F acts on ---------------------------------------------------------------------

/// What an act is aimed at.
#[derive(Clone, Debug, PartialEq)]
pub enum Aim {
    /// A resource or structure: its class (`resource`, `structure`), kind, where (sim m), row id,
    /// what is left (a resource), and whether it is the nearest of its kind to me (an act names
    /// things only as `{"nearest": kind}`).
    Thing { class: &'static str, kind: String, at: Vec2, id: u64, amount: f32, nearest: bool },
    /// A creature I perceive.
    Creature { id: u32 },
    /// Myself: the skills that take no target.
    Me,
}

impl Aim {
    /// The key under which my last choice for this kind of target is kept.
    fn key(&self, kind_of: impl Fn(u32) -> String) -> String {
        match self {
            Aim::Thing { kind, .. } => kind.clone(),
            Aim::Creature { id } => kind_of(*id),
            Aim::Me => "self".into(),
        }
    }
}

/// One thing my character could do.
#[derive(Clone, Debug, PartialEq)]
pub struct Choice {
    pub skill: String,
    pub item: Option<String>,
    /// What an offer asks in return.
    pub want: Option<String>,
    /// It needs words (the check refuses an empty text): the text box opens first.
    pub words: bool,
    /// A request in words rather than a skill (asking to be taught).
    pub say: Option<String>,
    pub label: String,
    /// How many of its item I carry (0: not an item of my pack, or no item).
    pub have: u32,
}

impl Choice {
    fn new(skill: &str, label: String) -> Self {
        Self { skill: skill.to_string(), item: None, want: None, words: false, say: None, label, have: 0 }
    }

    /// The `human_act` node for this choice toward `aim`.
    pub fn node(&self, aim: &Aim, text: Option<&str>) -> serde_json::Value {
        let mut leaf = serde_json::json!({"do": self.skill});
        match aim {
            Aim::Creature { id } => leaf["target"] = serde_json::json!({"id": id}),
            Aim::Thing { kind, .. } => leaf["target"] = serde_json::json!({"nearest": kind}),
            Aim::Me => {}
        }
        if let Some(i) = &self.item {
            leaf["item"] = i.clone().into();
            leaf["qty"] = 1.into();
        }
        if let Some(w) = &self.want {
            leaf["want"] = w.clone().into();
            leaf["want_qty"] = 1.into();
        }
        if let Some(t) = text {
            leaf["text"] = t.into();
        }
        match aim {
            // Acts name things by kind, nearest first: walk to the one I mean, then act.
            Aim::Thing { at, nearest: false, .. } => serde_json::json!({"seq": [{"do": "goto", "target": {"at": [at.x, at.y]}}, leaf]}),
            _ => leaf,
        }
    }
}

/// What my character knows of itself, for the rules' checks.
#[derive(Clone, Debug, Default)]
pub struct Me {
    pub actor: ActorFacts,
    pub night: bool,
    pub hour: f32,
    pub raining: bool,
    /// The season by the world's calendar, and the clock (authority ms) and day length, for a
    /// fire's state.
    pub season: String,
    pub now_ms: f64,
    pub day_ms: u64,
}

/// Where and when I am, as the world's rules count it (audit 2026-11-11: the checks ran at
/// noon, in summer, on grass, so a fuel-burning workplace never offered `make`).
#[derive(Clone, Default)]
pub struct Here {
    /// The displayed hour and the `daylight` law's night.
    pub hour: f32,
    pub night: bool,
    /// The ground under me on the hosted map, if it is known.
    pub terrain: Option<String>,
}

/// Skills whose rules give no check say nothing about what they apply to; they are offered
/// only toward my own kind (a request to join, to be welcomed), never toward things.
fn has_check(sc: &Scripts, skill: &str) -> bool {
    sc.has(&format!("{skill}_check"))
}

/// The item names a skill's help lists (`(item: spear|cloak|torch)`), if it lists them.
fn pretty(s: &str) -> String {
    s.replace('_', " ")
}

/// Every choice the rules allow toward `aim`, as far as my character knows, in the catalog's
/// order. `target` is the target as I perceive it (none for myself); `skills` is the catalog.
pub fn choices(sc: &Scripts, me: &Me, aim: &Aim, target: Option<&TargetFacts>, skills: &[Skill]) -> Vec<Choice> {
    let mut out = Vec::new();
    for spec in skills {
        if let Some(p) = plan(sc, me, aim, target, spec) {
            for unit in 0..p.units(spec) {
                check_unit(sc, me, target, spec, &p, unit, &mut out);
            }
        }
    }
    in_order(sc, &mut out);
    out
}

/// What the rules check for this target first; skills they leave open (walk to, join) after.
fn in_order(sc: &Scripts, out: &mut [Choice]) {
    out.sort_by_key(|c| !has_check(sc, &c.skill));
}

/// One skill's share of [`choices`]: whether the rules decide it (`<skill>_check`), whether it
/// asks something in return, and the items to try (none for a skill that takes no item). Each
/// item is checked on its own ([`check_unit`]), so the hint can spread a list over frames.
struct Plan {
    checked: bool,
    asks: bool,
    items: Vec<String>,
}

impl Plan {
    /// The checks it takes: one, or one per item.
    fn units(&self, spec: &Skill) -> usize {
        if spec.item {
            self.items.len()
        } else {
            1
        }
    }
}

/// Whether `spec` is offered toward `aim` at all, and what to try with it.
fn plan(sc: &Scripts, me: &Me, aim: &Aim, target: Option<&TargetFacts>, spec: &Skill) -> Option<Plan> {
    let skill = spec.name.as_str();
    // Real-time skills (fighting, dashing) are the skill bar's; the rest are acts or behavior.
    if sc.shapes().get(skill).is_some_and(|s| s.real_time) {
        return None;
    }
    // Where its presentation puts it (`living_rules::ui`: the defaults are this list's own
    // choices; a declaration may take a skill from the lists, `on: []`, when a player does it
    // another way).
    if let Some(u) = sc.ui(skill) {
        use living_rules::ui::On;
        let place = match aim {
            Aim::Me => On::Me,
            Aim::Thing { .. } => On::Thing,
            Aim::Creature { .. } => On::Person,
        };
        if !u.is_on(place) {
            return None;
        }
    }
    let wants_target = *aim != Aim::Me;
    if spec.target != wants_target {
        return None;
    }
    let checked = has_check(sc, skill);
    let on_thing = matches!(aim, Aim::Thing { .. });
    let my_kind = target.is_some_and(|t| t.class == "creature" && t.kind == me.actor.kind);
    if !checked && (on_thing || (wants_target && !my_kind)) {
        return None;
    }
    // An argument this client cannot give: a behavior graph (reworking one's ways).
    if spec.args.iter().any(|a| a == "graph") {
        return None;
    }
    // A skill that asks something in return offers what I carry and its own words: the rules
    // let terms promise anything, and every item for every want is too long a list.
    let asks = spec.args.iter().any(|a| a == "want");
    let mut items: Vec<String> = Vec::new();
    if spec.item {
        // Item candidates: what I carry, what I know, what the help names, and (for something
        // that may hold things) every item there is.
        if checked && asks {
            items.extend(me.actor.inv.iter().map(|(i, _)| i.clone()));
        } else if checked {
            items.extend(me.actor.inv.iter().map(|(i, _)| i.clone()));
            // What I know is an item only to a person (teach spear) or myself; a thing holds
            // items, never know-how (play-test 2: F offered "take wound tending" at remains, and
            // the authority refused it three times).
            if !on_thing {
                items.extend(me.actor.knows.iter().cloned());
            }
            if !matches!(aim, Aim::Me) {
                items.extend(catalog::item_names());
            }
        }
        items.extend(spec.items.iter().cloned());
        let mut seen = HashSet::new();
        items.retain(|c| seen.insert(c.clone()));
    }
    Some(Plan { checked, asks, items })
}

/// The rules' checks for one unit of a skill's plan (the skill itself, or one of its items),
/// adding what they allow to `out`.
#[allow(clippy::too_many_arguments)]
fn check_unit(sc: &Scripts, me: &Me, target: Option<&TargetFacts>, spec: &Skill, plan: &Plan, unit: usize, out: &mut Vec<Choice>) {
    let skill = spec.name.as_str();
    let ctx = |item: &str, text: &str, tgt_holds: Option<&str>| {
        let mut t = target.cloned().unwrap_or_else(|| TargetFacts { class: "none".into(), ..Default::default() });
        // What a target holds is not perceived: assume it has what is asked of it.
        if let Some(i) = tgt_holds {
            if !t.inv.iter().any(|(k, _)| k == i) {
                t.inv.push((i.to_string(), 1));
            }
        }
        // A skill that asks something in return is checked with something to ask for (each
        // thing there is becomes its own choice below).
        let want = if spec.args.iter().any(|a| a == "want") { catalog::item_names().into_iter().find(|w| w != item).unwrap_or_default() } else { String::new() };
        SkillCtx { actor: me.actor.clone(), target: t, item: item.to_string(), qty: 1, want: want.to_string(), want_qty: (!want.is_empty()) as u32, night: me.night, hour: me.hour, season: me.season.clone(), text: text.to_string(), roll: 0.5, skill: skill.to_string(), raining: me.raining, ..Default::default() }
    };
    let allowed = |item: &str, text: &str| sc.check(skill, &ctx(item, text, (!item.is_empty()).then_some(item))).is_ok();
    // Words: refused without, allowed with.
    if !spec.item {
        if allowed("", "") {
            out.push(Choice::new(skill, pretty(skill)));
        } else if plan.checked && allowed("", "…") {
            out.push(Choice { words: true, ..Choice::new(skill, format!("{} …", pretty(skill))) });
        }
        return;
    }
    let item = plan.items[unit].as_str();
    let ok = allowed(item, "");
    let words = !ok && plan.checked && allowed(item, "…");
    if !ok && !words {
        return;
    }
    // How many I carry, unless it is the name of something I know (teach spear).
    let have = me.actor.inv.iter().find(|(k, _)| k == item).map(|(_, n)| *n);
    let count = have.filter(|_| !me.actor.knows.iter().any(|k| k == item)).map(|n| format!(" ×{n}")).unwrap_or_default();
    let label = format!("{} {}{count}{}", pretty(skill), pretty(item), if words { " …" } else { "" });
    let c = Choice { item: Some(item.to_string()), words, have: have.filter(|_| !me.actor.knows.iter().any(|k| k == item)).unwrap_or(0), ..Choice::new(skill, label) };
    // A trade or terms name what I ask in return: one choice per thing to ask for.
    if plan.asks {
        for w in catalog::item_names().into_iter().chain(spec.items.iter().cloned()).filter(|w| w != item) {
            out.push(Choice { want: Some(w.clone()), label: format!("{} {} for {}", pretty(skill), pretty(item), pretty(&w)), ..c.clone() });
        }
    } else {
        out.push(c);
    }
}

/// Requests in words to a person: to be taught what I don't know.
fn requests(me: &Me) -> Vec<Choice> {
    catalog::technique_names()
        .into_iter()
        .filter(|t| !me.actor.knows.iter().any(|k| k == t))
        .map(|t| Choice { say: Some(format!("Would you teach me {}?", pretty(&t))), label: format!("ask to be taught {}", pretty(&t)), ..Choice::new("ask", String::new()) })
        .collect()
}

/// A list's rows: a skill with many options becomes one row opening its own list.
#[derive(Clone, Debug, PartialEq)]
pub enum Row {
    Pick(Choice),
    Group { name: String, label: String, count: usize },
    /// The game UI's own rows toward a person: talk to them, open their window, introduce
    /// yourself (an editable line to them); and More, for the acts the list keeps folded.
    Talk,
    Window,
    Introduce,
    More,
}

impl Row {
    /// What the list shows for the row.
    pub fn label(&self) -> String {
        match self {
            Row::Pick(c) => c.label.clone(),
            Row::Group { label, .. } => label.clone(),
            Row::Talk => "talk".into(),
            Row::Window => "their window".into(),
            Row::Introduce => "introduce yourself".into(),
            Row::More => "more…".into(),
        }
    }
}

pub fn rows(choices: &[Choice], group: Option<&str>) -> Vec<Row> {
    let name_of = |c: &Choice| if c.say.is_some() { "ask".to_string() } else if c.want.is_some() { format!("offer {}", c.item.clone().unwrap_or_default()) } else { c.skill.clone() };
    if let Some(g) = group {
        // Inside an offer's list, one row per thing offered; inside that, what is asked.
        let inner: Vec<&Choice> = choices.iter().filter(|c| name_of(c) == g || (g == "offer" && c.want.is_some())).collect();
        if g == "offer" {
            let mut rows: Vec<Row> = Vec::new();
            for c in inner {
                let n = name_of(c);
                match rows.iter_mut().find(|r| matches!(r, Row::Group { name, .. } if *name == n)) {
                    Some(Row::Group { count, .. }) => *count += 1,
                    _ => rows.push(Row::Group { label: format!("offer {} ›", pretty(c.item.as_deref().unwrap_or(""))), name: n, count: 1 }),
                }
            }
            return rows;
        }
        return inner.into_iter().cloned().map(Row::Pick).collect();
    }
    let mut counts: HashMap<String, usize> = HashMap::new();
    for c in choices {
        let n = if c.want.is_some() { "offer".into() } else { name_of(c) };
        *counts.entry(n).or_default() += 1;
    }
    let mut out: Vec<Row> = Vec::new();
    let mut grouped = HashSet::new();
    for c in choices {
        let n = if c.want.is_some() { "offer".into() } else { name_of(c) };
        if counts[&n] > GROUP_OVER || c.want.is_some() || c.say.is_some() {
            if grouped.insert(n.clone()) {
                let label = if c.say.is_some() { "ask to be taught ›".to_string() } else { format!("{} ›", pretty(&n)) };
                out.push(Row::Group { name: n.clone(), label, count: counts[&n] });
            }
        } else {
            out.push(Row::Pick(c.clone()));
        }
    }
    out
}

/// The act a tap does: the one I last chose for this kind of target, else, on a thing, the
/// first the rules allow that needs no further choice, is no use of force and is not a gesture
/// toward it (a skill whose `_shows()` faces its target: waving, nodding, looking over, turning
/// to face; play-test 1 found F offering "face" on a berry bush).
pub fn likely<'a>(sc: &Scripts, aim: &Aim, choices: &'a [Choice], last: Option<&Choice>) -> Option<&'a Choice> {
    if let Some(l) = last {
        if let Some(c) = choices.iter().find(|c| c.skill == l.skill && c.item == l.item && c.want == l.want && c.say == l.say) {
            return Some(c);
        }
    }
    if !matches!(aim, Aim::Thing { .. }) {
        return None;
    }
    let force = |s: &str| sc.shapes().get(s).is_some_and(|s| s.hostile || s.force || s.menace);
    let per_skill = |s: &str| choices.iter().filter(|c| c.skill == s).count();
    let gesture = |s: &str| sc.shows().faces(s);
    choices.iter().find(|c| !c.words && c.want.is_none() && c.say.is_none() && !force(&c.skill) && !gesture(&c.skill) && per_skill(&c.skill) == 1)
}

// ---- state --------------------------------------------------------------------------------

/// An open list.
#[derive(Clone, Debug)]
pub struct Menu {
    pub aim: Aim,
    pub title: String,
    pub choices: Vec<Choice>,
    /// The open sub-list (a skill's name), if any.
    pub group: Option<String>,
    /// Shown only for this item (opened from the inventory).
    pub item: Option<String>,
    /// Toward a person: the list starts with Talk and their window.
    pub person: bool,
    /// Unfolded: every act, not only the likely ones.
    pub more: bool,
    /// Where the game UI puts it (UI px), if not over its target.
    pub at: Option<Vec2>,
}

impl Menu {
    pub fn rows(&self) -> Vec<Row> {
        let list: Vec<Choice> = match &self.item {
            Some(i) => self.choices.iter().filter(|c| c.item.as_deref() == Some(i)).cloned().collect(),
            None => self.choices.clone(),
        };
        let mut out = rows(&list, self.group.as_deref());
        if self.group.is_some() || self.item.is_some() {
            return out;
        }
        if self.person {
            out.insert(0, Row::Talk);
            out.insert(1, Row::Window);
            out.insert(2, Row::Introduce);
        }
        // Folded: the acts a player wants in the moment; the rest behind More (play-test 4: the
        // list ran "Threaten, Conceive, Host…").
        if !self.more {
            let likely = |r: &Row| match r {
                Row::Talk | Row::Window => true,
                Row::Group { name, .. } => matches!(name.as_str(), "give" | "offer"),
                Row::Pick(c) => matches!(c.skill.as_str(), "wave" | "appraise"),
                _ => false,
            };
            let keep: Vec<Row> = if self.person { out.iter().filter(|r| likely(r)).cloned().collect() } else { out.iter().take(FOLDED).cloned().collect() };
            if keep.len() < out.len() {
                let mut keep = keep;
                keep.push(Row::More);
                return keep;
            }
        }
        out
    }
}

/// An act sent, awaiting the authority's word.
#[derive(Clone, Debug)]
struct Pending {
    sent_ms: f64,
    /// Through the act path (an outcome row will come) or as my behavior (the body shows it).
    act: bool,
    /// The kind of target it went to and the choice, so a refusal stops it being the tap's act.
    key: String,
    choice: Choice,
}

/// A short note over the hint: what the authority said of my act.
#[derive(Clone, Debug)]
pub struct Toast {
    pub text: String,
    pub ok: Option<bool>,
    pub at: f64,
}

#[derive(Resource, Default)]
pub struct Verbs {
    /// What F would act on now, and the act a tap would do.
    pub aim: Option<Aim>,
    pub aim_name: String,
    pub likely: Option<Choice>,
    pub has_options: bool,
    pub menu: Option<Menu>,
    pub inventory: bool,
    pub know_how: bool,
    /// The know-how panel's selected skill.
    pub selected: usize,
    pub toasts: Vec<Toast>,
    /// A row clicked in the list (`ui/verbs.rs`), or an inventory row.
    pub clicked: Option<usize>,
    pub clicked_item: Option<String>,
    /// A choice waiting for words (the text box is open).
    pub compose: Option<(Aim, Choice)>,
    /// Open the list of acts on myself (Menu › Character, until the character window exists).
    pub open_self: bool,
    /// The game UI's requests (`ui/people.rs`, `ui/pack.rs`): work out every choice toward a
    /// person (kept in `toward`), open a person's list at a group (Trade… opens `offer`), send
    /// choices, and an item let go on a person.
    pub want_toward: Option<u32>,
    pub toward: Option<(u32, Vec<Choice>)>,
    pub open_group: Option<(u32, String)>,
    pub send: Vec<(Aim, Choice)>,
    /// Acts built by the rules' presentation (`living_rules::ui::act_node`: an offer's Accept),
    /// sent as built, reported on as any act.
    pub send_node: Vec<(Aim, Choice, serde_json::Value)>,
    pub drop_item: Option<(u32, String)>,
    /// Asked of the game UI: open this person's window (the list's "Their window").
    pub open_window: Option<u32>,
    /// A script's `panel:none`: close the pack and the know-how windows (`panel:inventory` and
    /// `panel:know-how` set `inventory` and `know_how`, which open them).
    pub close_panels: bool,
    /// Where the game UI wants the next list opened (UI px), as beside a pack cell.
    pub place_next: Option<Vec2>,
    /// The list's Introduce yourself (`ui/people.rs` puts the line in their box).
    pub introduce: Option<u32>,
    pub want_intro: Option<u32>,
    /// Open every act toward a person, unfolded, at a place (a person window's More…).
    pub open_list: Option<(u32, Option<Vec2>)>,
    /// The open wheel (`ui/wheel.rs`, docs/INTERFACE.md §8), and a script's direction for it.
    pub wheel: Option<crate::ui::wheel::WheelOpen>,
    pub wheel_point: Option<living_rules::ui::Dir>,
    /// Where the cursor was when F went down (a flick opens the wheel with its direction).
    f_at: Option<Vec2>,
    composing: bool,
    pending: Vec<Pending>,
    last: HashMap<String, Choice>,
    f_down: Option<f64>,
    hint_at: f64,
    /// The hint being worked out ([`HintJob`]).
    job: Option<HintJob>,
    seen: HashSet<u64>,
    errors_seen: usize,
}

/// Steps a headless script asks for (`live.rs` `act:`, `menu:`, `panel:`).
#[derive(Resource, Default)]
pub struct Scripted {
    /// `act:SKILL[:ITEM][@AIM]`: (skill, item, aim spec).
    pub acts: Vec<(String, String, String)>,
    /// `menu:f|c|close|N`.
    pub menu: Vec<String>,
    /// `panel:inventory|know-how|none`.
    pub panel: Vec<String>,
    /// `wheel:DIR`: point the open wheel at a direction (as the arrows do).
    pub wheel: Option<String>,
}

pub struct VerbsPlugin;

impl Plugin for VerbsPlugin {
    fn build(&self, app: &mut App) {
        app.init_non_send::<Rules>()
            .init_resource::<Verbs>()
            .init_resource::<Scripted>()
            .add_systems(Update, (aim, input).chain().in_set(crate::phase::Phase::Input).after(crate::combat::pick))
            .add_systems(Update, outcomes.in_set(crate::phase::Phase::Present));
    }
}

// ---- what I know of myself and of what I aim at ----------------------------------------

pub(crate) fn stage_name(s: u8) -> &'static str {
    match s {
        0 => "infant",
        1 => "child",
        3 => "elder",
        _ => "adult",
    }
}

/// My character's facts as far as its client knows them: its rows, the world's calendar, the
/// ground under it and the fires about it, as the authority's `act::facts` builds them.
#[allow(clippy::too_many_arguments)]
fn me_facts(conn: &DbConnection, me: u32, now_ms: f64, rules: &Scripts, weather: Option<bool>, things: &[(&'static str, String, Vec2, u64, f32)], at: Vec2, here: &Here) -> Me {
    let c = conn.db.my_characters().id().find(&me);
    let v = conn.db.my_vitals().id().find(&me);
    let (hp, hunger, energy) = v.map_or((100.0, 0.0, 100.0), |v| {
        let m = (now_ms - v.at_ms as f64).max(0.0) as f32 / 60_000.0;
        ((v.hp + v.hp_rate * m).clamp(0.0, v.max_hp), (v.hunger + v.hunger_rate * m).clamp(0.0, 100.0), (v.energy + v.energy_rate * m).clamp(0.0, 100.0))
    });
    let mut inv: Vec<(String, u32)> = Vec::new();
    for r in conn.db.my_inventory().iter().filter(|r| r.owner == me as u64 && r.qty > 0) {
        match inv.iter_mut().find(|(k, _)| *k == r.item) {
            Some((_, n)) => *n += r.qty,
            None => inv.push((r.item, r.qty)),
        }
    }
    let knows: Vec<String> = conn.db.my_know_how().iter().filter(|k| k.actor == me).map(|k| k.technique).collect();
    let laws = rules.laws();
    let w = conn.db.world().iter().next();
    let (epoch, day_ms, year) = w.as_ref().map_or((0, living_rules::DEFAULT_DAY_MS, 4), |w| (w.epoch_ms, w.day_ms, w.year_days.max(4) as u64));
    let now = now_ms.max(0.0) as u64;
    // Warmth as the authority's `act::warmth` counts it: a roof within `shelter_warmth`; a
    // fire that needs no feeding within `fire_warmth`; one that burns fuel within its own
    // warmth, only while lit.
    let (mut near_fire, mut near_shelter) = (false, false);
    for (class, kind, p, id, _) in things.iter().filter(|t| t.0 == "structure") {
        let _ = class;
        let d = p.distance(at);
        let t = rules.structure(kind);
        if t.roof && d <= laws.shelter_warmth {
            near_shelter = true;
        }
        match &t.burns {
            Some(b) => {
                let lit = conn.db.structure().id().find(id).is_some_and(|s| living_rules::fire::lit(s.lit_until_ms, now));
                near_fire |= lit && d <= b.warmth;
            }
            None => {
                let reach = if t.roof { laws.shelter_warmth } else { laws.fire_warmth };
                near_fire |= t.warms && d <= reach;
            }
        }
    }
    let actor = ActorFacts {
        id: me,
        kind: c.as_ref().map_or("person".into(), |c| c.kind.clone()),
        hp,
        hunger,
        energy,
        near_fire,
        near_shelter,
        // The ground under me on the hosted map (the authority decides where building works).
        terrain: here.terrain.clone().unwrap_or_else(|| "grass".into()),
        stage: stage_name(c.as_ref().map_or(2, |c| c.stage)).into(),
        inv,
        knows,
        age: 30.0,
        life: 0.4,
        room: 25,
        ..Default::default()
    };
    let season = living_rules::SEASONS[living_rules::season_of(now, epoch, day_ms, year)].to_string();
    Me { actor, night: here.night, hour: here.hour, raining: weather.unwrap_or(false), season, now_ms, day_ms }
}

/// The hour (the displayed clock), night (the `daylight` law) and the ground under me (the
/// hosted map the client keeps for sight, `live.rs`).
fn here_of(sc: &Scripts, clock: &crate::daylight::Clock, live: &crate::live::Live, at: Vec2) -> Here {
    let hour = clock.hour();
    Here { hour, night: sc.is_night(hour), terrain: live.hosted_map().map(|m| m.at(at.x, at.y).name().to_string()) }
}

/// A structure's fire as the authority's `act::fire_state` reads it: lit, and the fuel left.
fn fire_facts(conn: &DbConnection, rules: &Scripts, t: &mut TargetFacts, me: &Me) {
    if t.class != "structure" {
        return;
    }
    // The rules' own reading of a fire (`StructureTraits::fire_state`, as the authority reads it):
    // a fuel fire is lit while its row's `lit_until_ms` is ahead, holding what is left at its rate.
    let lit_until = conn.db.structure().id().find(&t.id).map_or(0, |s| s.lit_until_ms);
    workplace(rules, t, lit_until, me.now_ms.max(0.0) as u64, me.day_ms);
}

/// A workplace's `lit` and `fuel` for the rules' checks (`make_check`'s `burning(a)` and fuel):
/// lit while `lit_until_ms` is ahead of `now`; fuel the hours left × its kind's `burns.rate`
/// (`StructureTraits::fire_state`, the authority's reading); a kind without `burns` as its traits say.
fn workplace(rules: &Scripts, t: &mut TargetFacts, lit_until_ms: u64, now: u64, day_ms: u64) {
    (t.lit, t.fuel) = rules.structure(&t.kind).fire_state(lit_until_ms, now, day_ms);
}

/// A creature as I perceive it, for the rules' checks.
fn creature_facts(conn: &DbConnection, rules: &Scripts, id: u32, dist: f32) -> Option<TargetFacts> {
    let c = conn.db.seen_characters().id().find(&id)?;
    let max = if c.max_hp > 0.0 { c.max_hp } else { rules.num_of("max_hp", &c.kind, 100.0) as f32 };
    let hp = if c.hp >= 0.0 {
        c.hp
    } else if c.band <= 4 {
        living_rules::combat::band_fraction(c.band) * max
    } else {
        max
    };
    Some(TargetFacts { class: "creature".into(), id: id as u64, kind: c.kind, name: c.name, hp, max_hp: max, stage: stage_name(c.stage).into(), hurt_ago: 1e9, alive: true, dist, ..Default::default() })
}

fn thing_facts(class: &'static str, kind: &str, id: u64, amount: f32, dist: f32) -> TargetFacts {
    TargetFacts { class: class.into(), id, kind: kind.to_string(), amount, dist, alive: false, ..Default::default() }
}

/// Resources and structures my client has rows for: (class, kind, where, id, what is left).
fn things(conn: &DbConnection, now_ms: f64) -> Vec<(&'static str, String, Vec2, u64, f32)> {
    let (resources, structures) = (conn.db.resource_node(), conn.db.structure());
    let res = resources.iter().map(|r| {
        let left = (r.amount + r.regen * ((now_ms - r.at_ms as f64).max(0.0) / 60_000.0) as f32).min(r.max);
        ("resource", r.kind, Vec2::new(r.x, r.y), r.id, left)
    });
    let st = structures.iter().map(|s| ("structure", s.kind, Vec2::new(s.x, s.y), s.id, 0.0));
    res.chain(st).collect()
}

/// What `id` is called, as I perceive it.
/// A list's title for what it acts on (a person's is `looks.rs`'s).
fn label_of_aim(conn: &DbConnection, aim: &Aim) -> String {
    match aim {
        Aim::Me => "Yourself".into(),
        Aim::Thing { kind, .. } => crate::ui::label(&pretty(kind)),
        Aim::Creature { id } => crate::ui::label(&label_of(conn, *id)),
    }
}

fn label_of(conn: &DbConnection, id: u32) -> String {
    conn.db.seen_characters().id().find(&id).map_or_else(|| "someone".into(), |c| c.label)
}

/// What the choices toward an aim are worked out from: its title, the target as I perceive it,
/// whether the rules are asked at all (a creature I no longer perceive has no choices), and
/// whether requests in words follow (a person of my kind).
struct Toward {
    title: String,
    target: Option<TargetFacts>,
    open: bool,
    requests: bool,
}

fn toward(conn: &DbConnection, rules: &Scripts, me: &Me, my_at: Vec2, aim: &Aim) -> Toward {
    match aim {
        Aim::Me => Toward { title: "Yourself".into(), target: None, open: true, requests: false },
        Aim::Thing { class, kind, at, id, amount, .. } => {
            let mut t = thing_facts(class, kind, *id, *amount, at.distance(my_at));
            fire_facts(conn, rules, &mut t, me);
            Toward { title: pretty(kind), target: Some(t), open: true, requests: false }
        }
        Aim::Creature { id } => match creature_facts(conn, rules, *id, 0.0) {
            Some(t) => Toward { title: label_of(conn, *id), requests: t.kind == me.actor.kind && t.kind == "person", target: Some(t), open: true },
            None => Toward { title: label_of(conn, *id), target: None, open: false, requests: false },
        },
    }
}

/// The choices toward an aim, with its title.
fn options(conn: &DbConnection, rules: &Scripts, skills: &[Skill], me: &Me, my_at: Vec2, aim: &Aim) -> (String, Vec<Choice>) {
    let t = toward(conn, rules, me, my_at, aim);
    if !t.open {
        return (t.title, Vec::new());
    }
    let mut c = choices(rules, me, aim, t.target.as_ref(), skills);
    if t.requests {
        c.extend(requests(me));
    }
    (t.title, c)
}

/// Where a target's list opens, for `menus()`: the place and the target's kind.
fn place_of(conn: &DbConnection, aim: &Aim) -> (living_rules::ui::On, String) {
    use living_rules::ui::On;
    match aim {
        Aim::Creature { id } => (On::Person, conn.db.seen_characters().id().find(id).map_or_else(String::new, |c| c.kind)),
        Aim::Thing { kind, .. } => (On::Thing, kind.clone()),
        Aim::Me => (On::Me, String::new()),
    }
}

/// The rules' own words for refusing a skill toward this target now (its `_check`), for the
/// wheel's hub: the same text a mind gets back for the same facts.
fn refusal(sc: &Scripts, me: &Me, target: Option<&TargetFacts>, spec: &Skill) -> (String, String) {
    // An item-taking skill is asked with a real item: its own first (a product to make), else
    // the first I carry; the act sent from a greyed section names the same one.
    let item = if spec.item { spec.items.first().cloned().or_else(|| me.actor.inv.first().map(|(i, _)| i.clone())).unwrap_or_default() } else { String::new() };
    let t = target.cloned().unwrap_or_else(|| TargetFacts { class: "none".into(), ..Default::default() });
    let want = if spec.args.iter().any(|a| a == "want") { catalog::item_names().into_iter().find(|w| *w != item).unwrap_or_default() } else { String::new() };
    let ctx = SkillCtx { actor: me.actor.clone(), target: t, item, qty: 1, want_qty: (!want.is_empty()) as u32, want, night: me.night, hour: me.hour, season: me.season.clone(), roll: 0.5, skill: spec.name.clone(), raining: me.raining, ..Default::default() };
    (sc.check(&spec.name, &ctx).err().unwrap_or_default(), ctx.item)
}

/// The wheel toward a target, where the world's `menus()` gives its place one
/// (`living_rules::ui::wheel_of` over the list's own choices): None keeps the list.
#[allow(clippy::too_many_arguments)]
fn wheel_toward(conn: &DbConnection, sc: &Scripts, skills: &[Skill], me: &Me, my_at: Vec2, aim: &Aim, person: bool, title: String, at: Vec2) -> Option<crate::ui::wheel::WheelOpen> {
    use living_rules::ui::{wheel_of, Candidate, Choose, Pin, Section};
    let (on, kind) = place_of(conn, aim);
    let spec = sc.menu_for(on, &kind).filter(|m| m.choose == Choose::Wheel)?.clone();
    let t = toward(conn, sc, me, my_at, aim);
    let choices = if t.open { choices(sc, me, aim, t.target.as_ref(), skills) } else { Vec::new() };
    let mut cands: Vec<Candidate> = Vec::new();
    let own = |s: Section| Candidate { what: Pin::Own(s), allowed: true, sub: false, words: false };
    if person {
        cands.push(own(Section::Talk));
        cands.push(own(Section::Window));
    }
    // One section per skill (Give is one section whatever I carry), in the list's order.
    for c in &choices {
        let name = if c.say.is_some() { "ask".to_string() } else { c.skill.clone() };
        if cands.iter().any(|k| k.what.name() == name) {
            continue;
        }
        let all: Vec<&Choice> = choices.iter().filter(|o| o.skill == c.skill && o.say.is_none() == c.say.is_none()).collect();
        let sub = all.len() > 1 || c.item.is_some() || c.want.is_some();
        cands.push(Candidate { what: Pin::Skill(name), allowed: true, sub, words: !sub && c.words });
    }
    if person {
        cands.push(own(Section::Introduce));
    }
    let layout = wheel_of(&spec, &cands);
    let mut w = crate::ui::wheel::WheelOpen { aim: aim.clone(), title, layout, choices, labels: Default::default(), icons: Default::default(), abouts: Default::default(), reasons: Default::default(), grey_items: Default::default(), held: true, at, vec: Vec2::ZERO, sel: None };
    for sec in w.layout.sections.clone() {
        let (label, icon, about) = match &sec.what {
            Pin::Own(Section::Talk) => ("Talk".to_string(), None, "Say something to them.".to_string()),
            Pin::Own(Section::Window) => ("Their window".to_string(), None, "What you know of them and what you have said.".to_string()),
            Pin::Own(Section::Introduce) => ("Introduce yourself".to_string(), None, "Tell them your name.".to_string()),
            Pin::Own(Section::More) => ("More".to_string(), None, "Every act toward them.".to_string()),
            Pin::Skill(k) => {
                let u = sc.ui(k);
                let help = skills.iter().find(|s| &s.name == k).map(|s| s.help.clone()).unwrap_or_default();
                (u.map_or_else(|| pretty(k), |u| u.label.clone()), u.and_then(|u| u.look.icon.map(String::from)), crate::ui::wheel::first_sentence(&help))
            }
        };
        if let (false, Pin::Skill(k)) = (sec.allowed, &sec.what) {
            let (why, item) = skills.iter().find(|s| &s.name == k).map(|s| refusal(sc, me, t.target.as_ref(), s)).unwrap_or_default();
            let why = if why.is_empty() { "Not now".to_string() } else { why };
            w.reasons.insert(sec.what.clone(), crate::ui::label(&why));
            if !item.is_empty() {
                w.grey_items.insert(sec.what.clone(), item);
            }
        }
        w.labels.insert(sec.what.clone(), label);
        w.icons.insert(sec.what.clone(), icon);
        w.abouts.insert(sec.what.clone(), about);
    }
    Some(w)
}

/// The hint's choices being worked out a few rule checks at a time ([`HINT_BUDGET`]), so the
/// checks toward a person (a hundred script calls and more, `teach` alone about 4 ms) never stall
/// one frame. What the hint shows changes only once a job is done.
struct HintJob {
    aim: Aim,
    me: Me,
    toward: Toward,
    /// The script revision it is checked against; the skill and the unit of its plan next.
    revision: u32,
    skill: usize,
    unit: usize,
    plan: Option<Plan>,
    out: Vec<Choice>,
}

impl HintJob {
    /// Check units until the budget is spent (at least one). Returns whether every skill is done.
    fn step(&mut self, sc: &Scripts, skills: &[Skill], budget: std::time::Duration) -> bool {
        let t0 = std::time::Instant::now();
        let HintJob { aim, me, toward, skill, unit, plan: current, out, .. } = self;
        while toward.open && *skill < skills.len() {
            let spec = &skills[*skill];
            let Some(p) = current.as_ref() else {
                *current = plan(sc, me, aim, toward.target.as_ref(), spec);
                *unit = 0;
                if current.is_none() {
                    *skill += 1;
                }
                continue;
            };
            if *unit >= p.units(spec) {
                *current = None;
                *skill += 1;
                continue;
            }
            check_unit(sc, me, toward.target.as_ref(), spec, p, *unit, out);
            *unit += 1;
            if t0.elapsed() >= budget {
                return false;
            }
        }
        true
    }
}

// ---- systems ----------------------------------------------------------------------------

/// Pick what F acts on and keep the hint's likely act current.
#[allow(clippy::too_many_arguments)]
fn aim(
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    mut rules: NonSendMut<Rules>,
    cam: Res<crate::camera::Cam>,
    target: Res<crate::controls::Target>,
    combat: Res<crate::combat::Combat>,
    town: Res<crate::town::Town>,
    weather: Res<crate::weather::Weather>,
    time: Res<Time>,
    mut v: ResMut<Verbs>,
    (clock, live): (Res<crate::daylight::Clock>, Res<crate::live::Live>),
) {
    let Some(conn) = net.conn.as_ref() else {
        v.aim = None;
        return;
    };
    rules.refresh(conn);
    let (Some(me), Some(me3), Some(sc)) = (net.my_id, target.0, rules.scripts.as_ref()) else {
        v.aim = None;
        v.likely = None;
        return;
    };
    let now = time.elapsed_secs_f64();
    // A hint under way goes on where it stopped; a script install starts it again.
    if let Some(mut job) = v.job.take() {
        if job.revision != rules.revision {
            return;
        }
        if !job.step(sc, &rules.skills, HINT_BUDGET) {
            v.job = Some(job);
            return;
        }
        let HintJob { aim: a, toward, mut out, .. } = job;
        in_order(sc, &mut out);
        if toward.requests {
            out.extend(requests(&job.me));
        }
        let key = a.key(|id| conn.db.seen_characters().id().find(&id).map_or_else(String::new, |c| c.kind));
        v.likely = likely(sc, &a, &out, v.last.get(&key)).cloned();
        v.has_options = !out.is_empty();
        v.aim_name = toward.title;
        v.aim = Some(a);
        return;
    }
    if now - v.hint_at < HINT_EVERY_S {
        return;
    }
    v.hint_at = now;
    let my_at = Vec2::new(me3.x, me3.z);
    let all = things(conn, scene.now_ms);
    let cursor = cam.cursor_ground.map(|c| Vec2::new(c.x, c.z));
    // Under the cursor: a creature (combat's pick), else a thing near its ground point.
    let thing_near = |p: Vec2, r: f32| all.iter().filter(|t| t.2.distance(p) <= r && t.1 != "remains" || t.1 == "remains" && t.2.distance(p) <= r).min_by(|a, b| a.2.distance(p).total_cmp(&b.2.distance(p)));
    let creature_ok = |id: u32| id != me && !town.hidden(id) && scene.shown.get(&id).is_some_and(|(p, _)| p.distance(my_at) <= FAR_M);
    let picked = combat.target.filter(|id| creature_ok(*id)).map(|id| Aim::Creature { id });
    let under = picked.or_else(|| cursor.and_then(|c| thing_near(c, CURSOR_THING_M)).filter(|t| t.2.distance(my_at) <= FAR_M).map(|t| (t.0, t.1.clone(), t.2, t.3, t.4)).map(|(class, kind, at, id, amount)| Aim::Thing { class, kind, at, id, amount, nearest: false }));
    let near = || {
        let c = scene.shown.iter().filter(|(id, (p, _))| creature_ok(**id) && p.distance(my_at) <= NEAR_M).map(|(id, (p, _))| (p.distance(my_at), Aim::Creature { id: *id }));
        let t = all.iter().filter(|t| t.2.distance(my_at) <= NEAR_M).map(|t| (t.2.distance(my_at), Aim::Thing { class: t.0, kind: t.1.clone(), at: t.2, id: t.3, amount: t.4, nearest: false }));
        c.chain(t).min_by(|a, b| a.0.total_cmp(&b.0)).map(|(_, a)| a)
    };
    let mut aim = under.or_else(near);
    // Whether the thing is the nearest of its kind to me (acts resolve `{"nearest": kind}`).
    if let Some(Aim::Thing { kind, id, at, nearest, .. }) = aim.as_mut() {
        let d = at.distance(my_at);
        *nearest = !all.iter().any(|t| t.1 == *kind && t.3 != *id && t.2.distance(my_at) < d - 0.05);
    }
    let here = here_of(sc, &clock, &live, my_at);
    let me_facts = me_facts(conn, me, scene.now_ms, sc, weather.authority.map(|(r, _)| r), &all, my_at, &here);
    match aim {
        // The hint follows once its job is done (this frame's share is started now).
        Some(a) => {
            let toward = toward(conn, sc, &me_facts, my_at, &a);
            let mut job = HintJob { aim: a, me: me_facts, toward, revision: rules.revision, skill: 0, unit: 0, plan: None, out: Vec::new() };
            job.step(sc, &rules.skills, HINT_BUDGET);
            v.job = Some(job);
        }
        None => {
            v.aim = None;
            v.likely = None;
            v.has_options = false;
        }
    }
}

/// Send a choice: an act through `human_act`, a request through `human_say`.
fn send(net: &Net, conn: &DbConnection, rules: &Scripts, aim: &Aim, c: &Choice, text: Option<&str>, now_ms: f64, v: &mut Verbs, input: &mut crate::controls::Input) {
    if let Some(line) = &c.say {
        let to = match aim {
            Aim::Creature { id } => *id,
            _ => 0,
        };
        let r = conn.reducers.human_say_then(line.clone(), to, net.on_reply("say", "human_say", || serde_json::json!({"text": line, "to": to})));
        if r.is_ok() {
            input.said.push((now_ms as u64, line.clone()));
        }
        net.report("say", r);
        return;
    }
    dispatch(net, conn, rules, aim, c, c.node(aim, text), now_ms, v);
}

/// Send an act's node through `human_act` and await its outcome.
#[allow(clippy::too_many_arguments)]
fn dispatch(net: &Net, conn: &DbConnection, rules: &Scripts, aim: &Aim, c: &Choice, node: serde_json::Value, now_ms: f64, v: &mut Verbs) {
    // An act (a one-off the authority reports on) or behavior (ongoing: the body shows it).
    let act = node.get("do").is_some() && living_rules::acts::not_an_act(&c.skill, rules.shapes()).is_none();
    info!("verbs: {} → {}", c.label, node);
    let node_s = node.to_string();
    let r = conn.reducers.human_act_then(node_s.clone(), net.on_reply("act", "human_act", || serde_json::json!({"node": node_s})));
    net.report("act", r);
    let key = aim.key(|id| conn.db.seen_characters().id().find(&id).map_or_else(String::new, |c| c.kind));
    v.pending.push(Pending { sent_ms: now_ms, act, key, choice: c.clone() });
    if !act {
        v.toasts.push(Toast { text: c.label.clone(), ok: None, at: now_ms / 1000.0 });
    }
}

/// F, C, I, K, the lists and the script's steps.
#[allow(clippy::too_many_arguments)]
pub fn input(
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    rules: NonSend<Rules>,
    keys: Res<ButtonInput<KeyCode>>,
    target: Res<crate::controls::Target>,
    weather: Res<crate::weather::Weather>,
    mut controls: ResMut<crate::controls::Input>,
    mut scripted: ResMut<Scripted>,
    mut wants: ResMut<crate::hud::UiWants>,
    time: Res<Time>,
    mut v: ResMut<Verbs>,
    (binds, looks, mut talk): (Res<crate::keys::Binds>, Res<crate::looks::Looks>, Option<ResMut<crate::talk::Talk>>),
    (clock, live, mut pointer, mouse): (Res<crate::daylight::Clock>, Res<crate::live::Live>, ResMut<crate::pointer::Pointer>, Res<ButtonInput<MouseButton>>),
) {
    let now = time.elapsed_secs_f64();
    let now_ms = scene.now_ms;
    wants.menu = v.menu.is_some() || v.wheel.is_some();
    let (Some(conn), Some(me), Some(me3), Some(sc)) = (net.conn.as_ref(), net.my_id, target.0, rules.scripts.as_ref()) else {
        v.menu = None;
        v.wheel = None;
        pointer.hold = false;
        return;
    };
    let my_at = Vec2::new(me3.x, me3.z);
    let typing = controls.chat_open || wants.keyboard;
    let free = !typing && !controls.demo;
    let pressed = |k: KeyCode| free && keys.just_pressed(k);
    let all = || things(conn, now_ms);
    let here = here_of(sc, &clock, &live, my_at);
    let facts = |_: &Aim| me_facts(conn, me, now_ms, sc, weather.authority.map(|(r, _)| r), &all(), my_at, &here);
    let is_person = |aim: &Aim| matches!(aim, Aim::Creature { id } if conn.db.seen_characters().id().find(id).is_some_and(|c| c.kind == "person"));
    let open = |v: &mut Verbs, aim: Aim, item: Option<String>| {
        let (_, choices) = options(conn, sc, &rules.skills, &facts(&aim), my_at, &aim);
        let title = match &aim {
            Aim::Creature { id } => looks.cap(*id),
            _ => label_of_aim(conn, &aim),
        };
        let person = is_person(&aim);
        let at = v.place_next.take();
        v.menu = Some(Menu { aim, title, choices, group: None, item, person, at, more: false });
    };
    // A wheel where the world's `menus()` gives the target's place one, else the list.
    let wheel_or_list = |v: &mut Verbs, aim: Aim, held: bool, at: Vec2| {
        let title = match &aim {
            Aim::Creature { id } => looks.cap(*id),
            _ => label_of_aim(conn, &aim),
        };
        match wheel_toward(conn, sc, &rules.skills, &facts(&aim), my_at, &aim, is_person(&aim), title, at) {
            Some(mut w) => {
                w.held = held;
                info!("ui: wheel toward {} ({}): {}; behind More: {}", w.title, if held { "held" } else { "sticky" }, w.layout.sections.iter().map(|s| format!("{} {}{}", s.dir.as_str(), s.what.name(), if s.allowed { "" } else { " (grey)" })).collect::<Vec<_>>().join(", "), w.more_names());
                v.wheel = Some(w);
                v.menu = None;
            }
            None => open(v, aim, None),
        }
    };
    let mut pick: Option<usize> = None;

    // The wheel (`ui/wheel.rs`): the held cursor's motion picks a section; letting go of F (or,
    // opened sticky, a click, Enter or F) chooses; letting go in the hub chooses nothing.
    let mut chosen: Option<Option<living_rules::ui::Dir>> = None;
    if let Some(d) = scripted.wheel.take().and_then(|d| living_rules::ui::Dir::parse(&d)) {
        v.wheel_point = Some(d);
    }
    if let (Some(d), Some(w)) = (v.wheel_point.take(), v.wheel.as_mut()) {
        w.point(d);
    }
    if let Some(w) = v.wheel.as_mut() {
        use living_rules::ui::Dir;
        w.nudge(pointer.held_delta);
        // The arrows point it (they are unbound by default).
        let k = |c: KeyCode| free && keys.pressed(c);
        let (x, y) = ((k(KeyCode::ArrowRight) as i32 - k(KeyCode::ArrowLeft) as i32) as f32, (k(KeyCode::ArrowDown) as i32 - k(KeyCode::ArrowUp) as i32) as f32);
        if x != 0.0 || y != 0.0 {
            let deg = x.atan2(-y).to_degrees().rem_euclid(360.0);
            w.point(Dir::at(((deg / 45.0).round() as usize) % 8));
        }
        // 1–8 choose at once, clockwise from north.
        const NUM: [KeyCode; 8] = [KeyCode::Digit1, KeyCode::Digit2, KeyCode::Digit3, KeyCode::Digit4, KeyCode::Digit5, KeyCode::Digit6, KeyCode::Digit7, KeyCode::Digit8];
        if let Some(i) = NUM.iter().position(|c| pressed(*c)) {
            if w.layout.at(Dir::at(i)).is_some() {
                chosen = Some(Some(Dir::at(i)));
            }
        }
        let f_up = binds.just_released(crate::keys::Act::Interact, &keys) || !binds.pressed(crate::keys::Act::Interact, &keys);
        if chosen.is_none() {
            if w.held && f_up {
                chosen = Some(w.sel);
            } else if !w.held && (pressed(KeyCode::Enter) || (free && binds.just_pressed(crate::keys::Act::Interact, &keys)) || mouse.just_pressed(MouseButton::Left)) {
                chosen = Some(w.sel);
            }
        }
        // Another bar key closes it without choosing (a player attacked mid-choice can fight).
        let bar = [crate::keys::Act::Skill1, crate::keys::Act::Skill2, crate::keys::Act::Skill3, crate::keys::Act::Jump, crate::keys::Act::Dodge, crate::keys::Act::Run];
        // Digits belong to the wheel (1–3 are also the skill keys' twins).
        let fled = chosen.is_none() && bar.iter().any(|a| binds.just_pressed(*a, &keys));
        // Its target left sight (or died): it closes, saying so.
        let gone = matches!(&w.aim, Aim::Creature { id } if conn.db.seen_characters().id().find(id).is_none());
        let note = gone.then(|| format!("{} is out of sight", w.title));
        if gone || fled {
            info!("ui: wheel closed ({})", if gone { "its target left sight" } else { "another key" });
            v.wheel = None;
            chosen = None;
        }
        if let Some(text) = note {
            v.toasts.push(Toast { text, ok: None, at: now });
        }
    }
    if let Some(sel) = chosen {
        use living_rules::ui::{Pin, Section};
        if let Some(w) = v.wheel.take() {
            let sec = sel.and_then(|d| w.layout.at(d).cloned());
            info!("ui: wheel chose {}", sec.as_ref().map_or("the hub: nothing sent".to_string(), |s| format!("{} {}{}", s.dir.as_str(), s.what.name(), if s.allowed { "" } else { " (grey: sent, the authority decides)" })));
            let id = match &w.aim {
                Aim::Creature { id } => Some(*id),
                _ => None,
            };
            match sec.map(|s| s.what) {
                None => {}
                Some(Pin::Own(Section::Talk)) => {
                    if let (Some(id), Some(t)) = (id, talk.as_mut()) {
                        t.open_to = Some(id);
                    }
                }
                Some(Pin::Own(Section::Window)) => v.open_window = id,
                Some(Pin::Own(Section::Introduce)) => v.introduce = id,
                Some(Pin::Own(Section::More)) => {
                    let person = is_person(&w.aim);
                    v.menu = Some(Menu { aim: w.aim.clone(), title: w.title.clone(), choices: w.choices.clone(), group: None, item: None, person, at: None, more: true });
                }
                Some(Pin::Skill(k)) => {
                    let cs: Vec<&Choice> = w.choices.iter().filter(|c| if k == "ask" { c.say.is_some() } else { c.skill == k && c.say.is_none() }).collect();
                    match cs.as_slice() {
                        [c] if c.item.is_none() && c.want.is_none() => {
                            let c = (*c).clone();
                            if c.words {
                                v.compose = Some((w.aim.clone(), c));
                            } else {
                                send(&net, conn, sc, &w.aim, &c, None, now_ms, &mut v, &mut controls);
                            }
                        }
                        // Greyed: sent all the same; the authority decides and says why.
                        [] => {
                            let item = w.grey_items.get(&Pin::Skill(k.clone())).cloned();
                            let c = Choice { item, ..Choice::new(&k, pretty(&k)) };
                            send(&net, conn, sc, &w.aim, &c, None, now_ms, &mut v, &mut controls);
                        }
                        // A further choice: its sub-list, beside the hub.
                        _ => {
                            let person = is_person(&w.aim);
                            let group = if cs.iter().any(|c| c.want.is_some()) { "offer".to_string() } else { k.clone() };
                            v.menu = Some(Menu { aim: w.aim.clone(), title: w.title.clone(), choices: w.choices.clone(), group: Some(group), item: None, person, at: None, more: true });
                        }
                    }
                }
            }
        }
    }

    // Panels.
    // I and K are the game UI's windows (`ui/win.rs`): the pack and skills and know-how.
    if v.know_how && free {
        let n = rules.skills.len().max(1);
        if keys.just_pressed(KeyCode::ArrowDown) {
            v.selected = (v.selected + 1) % n;
        }
        if keys.just_pressed(KeyCode::ArrowUp) {
            v.selected = (v.selected + n - 1) % n;
        }
    }
    // An inventory row: what I can do with that item myself.
    if let Some(item) = v.clicked_item.take() {
        open(&mut v, Aim::Me, Some(item));
    }

    // F: tap acts, hold opens the list.
    let interact = |k: &ButtonInput<KeyCode>| binds.just_pressed(crate::keys::Act::Interact, k);
    if v.menu.is_none() && v.wheel.is_none() && chosen.is_none() && free && interact(&keys) {
        v.f_down = Some(now);
        v.f_at = pointer.pos;
    }
    // F down and a flick before the wheel would draw: it opens with that direction chosen.
    if let (Some(t0), Some(at), Some(pos), Some(aim)) = (v.f_down, v.f_at, pointer.pos, v.aim.clone()) {
        let moved = pos - at;
        if now - t0 >= crate::ui::wheel::FLICK_MIN_S && moved.length() >= crate::ui::wheel::FLICK_PX && binds.pressed(crate::keys::Act::Interact, &keys) {
            let (on, kind) = place_of(conn, &aim);
            if sc.menu_for(on, &kind).is_some_and(|m| m.choose == living_rules::ui::Choose::Wheel) {
                v.f_down = None;
                wheel_or_list(&mut v, aim, true, at);
                if let Some(w) = v.wheel.as_mut() {
                    w.nudge(moved);
                }
                pointer.place = Some(at);
            }
        }
    }
    if let Some(t0) = v.f_down {
        let released = binds.just_released(crate::keys::Act::Interact, &keys) || !binds.pressed(crate::keys::Act::Interact, &keys);
        let held = now - t0 >= HOLD_S;
        if held || released {
            v.f_down = None;
            // A tap of F on a peaceful person talks to them; held, it lists the acts.
            let person = v.aim.as_ref().filter(|a| is_person(a)).and_then(|a| match a {
                Aim::Creature { id } => Some(*id),
                _ => None,
            });
            if let (Some(id), false, Some(t)) = (person.filter(|id| !crate::combat::hostile_to_me(conn, *id, me, now_ms)), held, talk.as_mut()) {
                t.open_to = Some(id);
            } else if let Some(aim) = v.aim.clone() {
                // Held, or a tap with nothing likely: the wheel where the world gives one (held
                // or sticky), else the list.
                let at = v.f_at.or(pointer.pos).unwrap_or(Vec2::new(800.0, 450.0));
                match v.likely.clone().filter(|_| !held) {
                    Some(c) if c.words => v.compose = Some((aim, c)),
                    Some(c) => send(&net, conn, sc, &aim, &c, None, now_ms, &mut v, &mut controls),
                    None if v.has_options => wheel_or_list(&mut v, aim, held, at),
                    // Held where the world pins acts: the wheel, greyed, says what belongs here
                    // and why not now (a cold hearth's Make and Feed).
                    None if held && sc.menu_for(place_of(conn, &aim).0, &place_of(conn, &aim).1).is_some_and(|m| m.choose == living_rules::ui::Choose::Wheel && m.wheel.iter().any(|p| p.is_some())) => wheel_or_list(&mut v, aim, true, at),
                    None => {
                        let text = format!("Nothing to do with {}", v.aim_name);
                        v.toasts.push(Toast { text, ok: None, at: now });
                    }
                }
            } else {
                // Nothing within reach: say so, briefly. Opening my own list here (as before) met a
                // newcomer's first F with fourteen abstract acts (play-test 1); C opens it.
                v.toasts.push(Toast { text: "Nothing within reach — C for your own acts".into(), ok: None, at: now });
            }
        }
    } else if v.menu.as_ref().is_some_and(|m| m.aim != Aim::Me) && pressed(INTERACT) {
        v.menu = None;
    }
    // The wheel holds the cursor while it is open (`pointer.rs`).
    pointer.hold = v.wheel.is_some();
    // C: acts on myself.
    if std::mem::take(&mut v.open_self) {
        open(&mut v, Aim::Me, None);
    }
    // The game UI's requests.
    if let Some(id) = v.want_toward.take() {
        let aim = Aim::Creature { id };
        let (_, choices) = options(conn, sc, &rules.skills, &facts(&aim), my_at, &aim);
        v.toward = Some((id, choices));
    }
    if let Some((id, at)) = v.open_list.take() {
        v.place_next = at;
        open(&mut v, Aim::Creature { id }, None);
        if let Some(m) = v.menu.as_mut() {
            m.more = true;
        }
    }
    if let Some((id, group)) = v.open_group.take() {
        open(&mut v, Aim::Creature { id }, None);
        if let Some(m) = v.menu.as_mut() {
            if m.rows().iter().any(|r| matches!(r, Row::Group { name, .. } if *name == group)) {
                m.group = Some(group);
            } else {
                v.toasts.push(Toast { text: format!("Nothing to {} with {}", pretty(&group), looks.of(id).unwrap_or("them")), ok: None, at: now });
                v.menu = None;
            }
        }
    }
    for (aim, c) in std::mem::take(&mut v.send) {
        if c.words {
            v.compose = Some((aim, c));
        } else {
            send(&net, conn, sc, &aim, &c, None, now_ms, &mut v, &mut controls);
        }
    }
    for (aim, c, node) in std::mem::take(&mut v.send_node) {
        dispatch(&net, conn, sc, &aim, &c, node, now_ms, &mut v);
    }
    if let Some((id, item)) = v.drop_item.take() {
        let aim = Aim::Creature { id };
        let (_, choices) = options(conn, sc, &rules.skills, &facts(&aim), my_at, &aim);
        let force = |s: &str| sc.shapes().get(s).is_some_and(|s| s.hostile || s.force || s.menace);
        match choices.iter().find(|c| c.item.as_deref() == Some(item.as_str()) && c.want.is_none() && c.say.is_none() && !c.words && c.have > 0 && !force(&c.skill)) {
            Some(c) => {
                let c = c.clone();
                info!("verbs: {} let go on #{id}: {}", item, c.label);
                send(&net, conn, sc, &aim, &c, None, now_ms, &mut v, &mut controls);
            }
            None => {
                info!("verbs: {} let go on #{id}: nothing the rules allow", item);
                v.toasts.push(Toast { text: format!("Nothing to do with {} for {}", pretty(&item), looks.of(id).unwrap_or("them")), ok: Some(false), at: now });
            }
        }
    }
    if free && binds.just_pressed(crate::keys::Act::Character, &keys) {
        if v.menu.as_ref().is_some_and(|m| m.aim == Aim::Me) {
            v.menu = None;
        } else {
            open(&mut v, Aim::Me, None);
        }
    }
    let _ = (SELF_ACTS, INTERACT);
    // Esc is the game UI's (`ui/win.rs`: a list closes first).
    if v.menu.is_some() && free {
        const DIGITS: [KeyCode; 10] = [KeyCode::Digit1, KeyCode::Digit2, KeyCode::Digit3, KeyCode::Digit4, KeyCode::Digit5, KeyCode::Digit6, KeyCode::Digit7, KeyCode::Digit8, KeyCode::Digit9, KeyCode::Digit0];
        pick = DIGITS.iter().position(|k| keys.just_pressed(*k));
    }
    if let Some(i) = v.clicked.take() {
        pick = Some(i);
    }

    // The script's steps. An aim is `nearest:KIND`, `id:N`, `self`, or nothing (what F aims at
    // now, else myself).
    let aim_of = |v: &Verbs, at: &str| match at.split_once(':') {
        Some(("id", n)) => n.parse().ok().map(|id| Aim::Creature { id }),
        Some(("nearest", kind)) => {
            let a = all();
            a.iter().filter(|t| t.1 == kind).min_by(|x, y| x.2.distance(my_at).total_cmp(&y.2.distance(my_at))).map(|t| Aim::Thing { class: t.0, kind: t.1.clone(), at: t.2, id: t.3, amount: t.4, nearest: true }).or_else(|| {
                scene.shown.iter().filter(|(id, _)| **id != me && conn.db.seen_characters().id().find(id).is_some_and(|c| c.kind == kind)).min_by(|x, y| x.1 .0.distance(my_at).total_cmp(&y.1 .0.distance(my_at))).map(|(id, _)| Aim::Creature { id: *id })
            })
        }
        _ if at == "self" => Some(Aim::Me),
        _ => v.aim.clone().or(Some(Aim::Me)),
    };
    for step in std::mem::take(&mut scripted.menu) {
        let (what, at) = step.split_once('@').unwrap_or((&step, ""));
        match what {
            "f" => {
                if let Some(aim) = aim_of(&v, at) {
                    open(&mut v, aim, None);
                }
            }
            "c" => open(&mut v, Aim::Me, None),
            "close" => v.menu = None,
            n => pick = n.parse::<usize>().ok().map(|n| n.saturating_sub(1)),
        }
    }
    for p in std::mem::take(&mut scripted.panel) {
        let (p, select) = p.split_once(':').unwrap_or((&p, ""));
        if let Some(i) = rules.skills.iter().position(|k| k.name == select) {
            v.selected = i;
        }
        match p {
            "inventory" => v.inventory = true,
            "know-how" | "knowhow" => v.know_how = true,
            _ => v.close_panels = true,
        }
    }
    for (skill, item, at) in std::mem::take(&mut scripted.acts) {
        let aim = aim_of(&v, &at);
        let Some(aim) = aim else {
            warn!("live script: act {skill} at {at}: nothing there");
            continue;
        };
        let (_, ch) = options(conn, sc, &rules.skills, &facts(&aim), my_at, &aim);
        let offered = ch.iter().find(|c| c.skill == skill && c.item.as_deref().unwrap_or("") == item).cloned();
        info!("live script: act {skill} {item} at {aim:?}: {} by the rules as this client knows them", if offered.is_some() { "offered" } else { "not offered" });
        // Sent either way: the authority decides, and a refusal is part of what is shown.
        let c = offered.unwrap_or_else(|| Choice { item: (!item.is_empty()).then(|| item.clone()), ..Choice::new(&skill, format!("{} {}", pretty(&skill), pretty(&item)).trim().to_string()) });
        if c.words {
            v.compose = Some((aim, c));
        } else {
            send(&net, conn, sc, &aim, &c, None, now_ms, &mut v, &mut controls);
        }
    }

    // A pick in the open list.
    if let (Some(i), Some(m)) = (pick, v.menu.clone()) {
        match m.rows().get(i) {
            Some(Row::Group { name, .. }) => {
                if let Some(mm) = v.menu.as_mut() {
                    mm.group = Some(name.clone());
                }
            }
            Some(Row::Talk) => {
                if let (Aim::Creature { id }, Some(t)) = (&m.aim, talk.as_mut()) {
                    t.open_to = Some(*id);
                }
                v.menu = None;
            }
            Some(Row::More) => {
                if let Some(mm) = v.menu.as_mut() {
                    mm.more = true;
                }
            }
            Some(Row::Introduce) => {
                if let Aim::Creature { id } = &m.aim {
                    v.introduce = Some(*id);
                }
                v.menu = None;
            }
            Some(Row::Window) => {
                if let Aim::Creature { id } = &m.aim {
                    v.open_window = Some(*id);
                }
                v.menu = None;
            }
            Some(Row::Pick(c)) => {
                let key = m.aim.key(|id| conn.db.seen_characters().id().find(&id).map_or_else(String::new, |c| c.kind));
                v.last.insert(key, c.clone());
                v.menu = None;
                if c.words {
                    v.compose = Some((m.aim.clone(), c.clone()));
                } else {
                    send(&net, conn, sc, &m.aim, c, None, now_ms, &mut v, &mut controls);
                }
            }
            None => {}
        }
    }
    // Words for a choice that needs them: the text box (`ui/chat.rs`) collects them.
    if let Some(words) = controls.composed.take() {
        v.composing = false;
        if let Some((aim, c)) = v.compose.take() {
            if !words.trim().is_empty() {
                send(&net, conn, sc, &aim, &c, Some(words.trim()), now_ms, &mut v, &mut controls);
            }
        }
    } else if let Some((_, c)) = v.compose.as_ref() {
        if !v.composing {
            controls.compose = Some(c.label.trim_end_matches(" …").to_string());
            v.composing = true;
        } else if controls.compose.is_none() {
            // Esc in the text box: the act is dropped.
            v.compose = None;
            v.composing = false;
        }
    }
    // Following the open list: a person who walks off closes it.
    if let Some(Aim::Creature { id }) = v.menu.as_ref().map(|m| m.aim.clone()) {
        if !scene.shown.get(&id).is_some_and(|(p, _)| p.distance(my_at) <= FAR_M) {
            v.menu = None;
        }
    }
    wants.menu = v.menu.is_some();
}

/// An outcome line's note, from its structured row (`my_act_outcomes`, joined by the line's
/// id): what was done, or the rules' own words for why not. A line whose row has not come
/// (an older line, a row not yet here) is read from its words.
pub fn outcome_of(conn: &DbConnection, e: &Experience) -> (Option<bool>, String) {
    match conn.db.my_act_outcomes().id().find(&e.id) {
        Some(o) if o.ok => (Some(true), crate::ui::label(&o.what)),
        Some(o) if !o.why.trim().is_empty() => (Some(false), crate::ui::label(o.why.trim().trim_end_matches('.'))),
        Some(o) => (Some(false), crate::ui::label(&o.what)),
        None => outcome_text(&e.text),
    }
}

/// The authority's word on what I sent: my `act` experiences and refused calls.
fn outcomes(net: NonSend<Net>, scene: NonSend<Scene>, time: Res<Time>, mut v: ResMut<Verbs>) {
    let now = time.elapsed_secs_f64();
    let now_ms = scene.now_ms;
    v.toasts.retain(|t| now - t.at < TOAST_S);
    v.pending.retain(|p| now_ms - p.sent_ms < AWAIT_MS);
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else { return };
    // A refused call (the reducer's error).
    let errs = net.errors.lock().unwrap().clone();
    if v.errors_seen > errs.len() {
        v.errors_seen = 0;
    }
    for e in errs.iter().skip(v.errors_seen) {
        if let Some(why) = e.strip_prefix("act refused: ").or_else(|| e.strip_prefix("say refused: ")) {
            v.toasts.push(Toast { text: why.to_string(), ok: Some(false), at: now });
        }
    }
    v.errors_seen = errs.len();
    let oldest = v.pending.iter().map(|p| p.sent_ms).fold(f64::MAX, f64::min);
    let mut fresh: Vec<Experience> = conn.db.my_experience().iter().filter(|e| e.observer == me && e.kind == "act" && !v.seen.contains(&e.id)).collect();
    fresh.sort_by_key(|e| e.at_ms);
    for e in fresh {
        v.seen.insert(e.id);
        // Only outcomes of what I sent from here (minds' and earlier rows stay out).
        if (e.at_ms as f64) + 1_000.0 < oldest || v.pending.is_empty() {
            continue;
        }
        let (ok, text) = outcome_of(conn, &e);
        v.toasts.push(Toast { text, ok, at: now });
        if let Some(i) = v.pending.iter().position(|p| p.act) {
            let p = v.pending.remove(i);
            // Refused: a tap no longer repeats it on that kind of target.
            if ok == Some(false) && v.last.get(&p.key) == Some(&p.choice) {
                v.last.remove(&p.key);
            }
        }
    }
    // What the world's rules tell me of my dealings (an agreement kept or broken, a demand paid),
    // from now on: rows already there when the client connected are history.
    let told: Vec<Experience> = conn.db.my_experience().iter().filter(|e| e.observer == me && e.kind == "record" && !v.seen.contains(&e.id)).collect();
    for e in told {
        v.seen.insert(e.id);
        if (e.at_ms as f64) + 5_000.0 >= now_ms {
            v.toasts.push(Toast { text: outcome_text(&e.text).1, ok: None, at: now });
        }
    }
    let n = v.toasts.len();
    if n > 3 {
        v.toasts.drain(..n - 3);
    }
    if v.seen.len() > 1024 {
        let live: HashSet<u64> = conn.db.my_experience().iter().map(|e| e.id).collect();
        v.seen.retain(|id| live.contains(id));
    }
}

/// The authority's `act` feedback, shortened: whether it worked, and what or why.
pub fn outcome_text(t: &str) -> (Option<bool>, String) {
    // The UI's font has no arrows; names read as words.
    let cap = |s: &str| {
        let s = s.trim().trim_end_matches('.').replace(" → ", " › ").replace('_', " ");
        let s = s.as_str();
        let mut c = s.chars();
        c.next().map_or(String::new(), |f| f.to_uppercase().collect::<String>() + c.as_str())
    };
    if let Some(r) = t.strip_prefix("You did what you had decided: ") {
        return (Some(true), cap(r));
    }
    if let Some(r) = t.strip_prefix("What you had decided did not work out: ") {
        // "<what>: <why>." → the why.
        let why = r.split_once(": ").map_or(r, |(_, w)| w);
        return (Some(false), cap(why));
    }
    if let Some(r) = t.strip_prefix("You could not act on what you decided") {
        let why = r.split_once("): ").map_or(r, |(_, w)| w);
        return (Some(false), cap(why));
    }
    (None, cap(t))
}

#[cfg(test)]
mod tests {
    use super::*;

    const SKILLS: &str = include_str!("../../scripts/skills.rhai");

    fn me(inv: &[(&str, u32)], knows: &[&str]) -> Me {
        Me {
            actor: ActorFacts { id: 1, kind: "person".into(), hp: 100.0, hunger: 30.0, energy: 80.0, terrain: "grass".into(), stage: "adult".into(), inv: inv.iter().map(|(k, n)| (k.to_string(), *n)).collect(), knows: knows.iter().map(|s| s.to_string()).collect(), room: 25, ..Default::default() },
            hour: 12.0,
            season: "summer".into(),
            ..Default::default()
        }
    }

    fn bush() -> (Aim, TargetFacts) {
        (Aim::Thing { class: "resource", kind: "berry_bush".into(), at: Vec2::ZERO, id: 9, amount: 4.0, nearest: true }, thing_facts("resource", "berry_bush", 9, 4.0, 1.0))
    }

    fn person() -> (Aim, TargetFacts) {
        (Aim::Creature { id: 7 }, TargetFacts { class: "creature".into(), id: 7, kind: "person".into(), name: "Mira".into(), hp: 100.0, max_hp: 100.0, stage: "adult".into(), hurt_ago: 1e9, alive: true, dist: 1.0, ..Default::default() })
    }

    fn skills(c: &[Choice]) -> Vec<String> {
        c.iter().map(|c| format!("{}{}", c.skill, c.item.as_ref().map(|i| format!(":{i}")).unwrap_or_default())).collect()
    }

    #[test]
    fn the_hint_spread_over_frames_finds_what_the_whole_list_finds() {
        let sc = Scripts::new(SKILLS).unwrap();
        let all = skills_of(&sc);
        let m = me(&[("berries", 4), ("wood", 3)], &["spear", "archery"]);
        for (aim, t) in [person(), bush()] {
            let whole = choices(&sc, &m, &aim, Some(&t), &all);
            let toward = Toward { title: String::new(), target: Some(t), open: true, requests: false };
            let mut job = HintJob { aim, me: m.clone(), toward, revision: 0, skill: 0, unit: 0, plan: None, out: Vec::new() };
            // With no budget each frame does one check unit.
            let mut frames = 1;
            while !job.step(&sc, &all, std::time::Duration::ZERO) {
                frames += 1;
            }
            in_order(&sc, &mut job.out);
            assert_eq!(job.out, whole);
            assert!(frames > 1, "spread over frames ({frames})");
        }
    }

    #[test]
    fn make_is_offered_at_a_furnace_only_while_it_burns_with_fuel() {
        // Cullet's glass: at a furnace, lit, 1 fuel, 2 sand and an alkali (ash), glassmaking.
        let src = living_rules::floors::compose(SKILLS, include_str!("../../seeds/worlds/cullet/laws.rhai")).unwrap();
        let day = 2_880_000;
        let sc = Scripts::with_day(&src, day).unwrap();
        let aim = Aim::Thing { class: "structure", kind: "furnace".into(), at: Vec2::ZERO, id: 5, amount: 0.0, nearest: true };
        let m = me(&[("sand", 2), ("ash", 1)], &["glassmaking"]);
        let glass = |lit_until: u64| {
            let mut t = thing_facts("structure", "furnace", 5, 0.0, 1.0);
            workplace(&sc, &mut t, lit_until, 1_000_000, day);
            let offered = choices(&sc, &m, &aim, Some(&t), &skills_of(&sc)).iter().any(|c| c.skill == "make" && c.item.as_deref() == Some("glass"));
            (t.lit, t.fuel, offered)
        };
        let hour = day / 24;
        // Two hours left at 3 units an hour: lit, 6 units.
        let (lit, fuel, offered) = glass(1_000_000 + 2 * hour);
        assert!(lit && (fuel - 6.0).abs() < 1e-3 && offered, "lit {lit} fuel {fuel} offered {offered}");
        // A sixth of an hour: lit, half a unit, too little for glass.
        let (lit, fuel, offered) = glass(1_000_000 + hour / 6);
        assert!(lit && (fuel - 0.5).abs() < 1e-3 && !offered, "lit {lit} fuel {fuel} offered {offered}");
        // Out.
        let (lit, fuel, offered) = glass(999_000);
        assert!(!lit && fuel == 0.0 && !offered, "lit {lit} fuel {fuel} offered {offered}");
    }

    #[test]
    fn a_bush_is_gathered_and_a_tap_gathers() {
        let sc = Scripts::new(SKILLS).unwrap();
        let (aim, t) = bush();
        let c = choices(&sc, &me(&[], &[]), &aim, Some(&t), &skills_of(&sc));
        // Gathering. Not facing it: the rules' `face` takes anything in sight, but a player faces
        // where it looks, so `face_ui()` puts it in no list (play-test 5).
        assert_eq!(skills(&c), vec!["gather"], "{c:?}");
        assert_eq!(likely(&sc, &aim, &c, None).map(|c| c.skill.as_str()), Some("gather"));
        // A full pack: the rules refuse to gather, so it is not offered, and nothing is.
        let full = me(&[("wood", 40)], &[]);
        assert!(skills(&choices(&sc, &full, &aim, Some(&t), &skills_of(&sc))).is_empty());
    }

    #[test]
    fn i_eat_food_i_carry_and_craft_what_i_know_and_can_afford() {
        let sc = Scripts::new(SKILLS).unwrap();
        let m = me(&[("berries", 4), ("wood", 3), ("stone", 1)], &["spear"]);
        let c = choices(&sc, &m, &Aim::Me, None, &skills_of(&sc));
        let s = skills(&c);
        assert!(s.contains(&"eat:berries".to_string()), "{s:?}");
        assert!(!s.contains(&"eat:wood".to_string()), "{s:?}");
        assert!(s.contains(&"craft:spear".to_string()), "{s:?}");
        assert!(!s.contains(&"craft:bow".to_string()), "not known: {s:?}");
        assert!(s.contains(&"sleep".to_string()) && s.contains(&"drop:berries".to_string()), "{s:?}");
        assert_eq!(c.iter().find(|c| c.skill == "eat").unwrap().label, "eat berries ×4");
        // Writing needs words: offered once known, with the text box first.
        let w = choices(&sc, &me(&[("wood", 1)], &["writing"]), &Aim::Me, None, &skills_of(&sc));
        assert!(w.iter().any(|c| c.skill == "write" && c.item.as_deref() == Some("tablet") && c.words), "{w:?}");
        // Nothing on myself is a use of force or a real-time skill.
        assert!(!s.iter().any(|k| k == "dodge" || k == "block" || k == "heal"), "{s:?}");
    }

    #[test]
    fn to_a_person_i_give_offer_teach_and_greet_but_a_tap_asks() {
        let sc = Scripts::new(SKILLS).unwrap();
        let (aim, t) = person();
        let m = me(&[("berries", 4)], &["fire"]);
        let c = choices(&sc, &m, &aim, Some(&t), &skills_of(&sc));
        let s = skills(&c);
        for want in ["give:berries", "teach:fire", "wave", "nod", "appraise"] {
            assert!(s.contains(&want.to_string()), "{want} missing: {s:?}");
        }
        assert!(c.iter().any(|c| c.skill == "offer" && c.want.as_deref() == Some("wood")), "{s:?}");
        assert!(!s.contains(&"give:wood".to_string()), "not carried: {s:?}");
        assert!(!s.contains(&"gather".to_string()), "{s:?}");
        assert!(likely(&sc, &aim, &c, None).is_none(), "a person opens the list");
        // The offers fold into one row with a list per thing offered.
        let r = rows(&c, None);
        assert!(r.iter().any(|r| matches!(r, Row::Group { name, .. } if name == "offer")), "{r:?}");
        let r = rows(&c, Some("offer"));
        assert!(matches!(&r[0], Row::Group { name, .. } if name == "offer berries"), "{r:?}");
        assert!(rows(&c, Some("offer berries")).len() > 10);
        // Last time I waved: a tap waves again.
        let wave = c.iter().find(|c| c.skill == "wave").cloned();
        assert_eq!(likely(&sc, &aim, &c, wave.as_ref()).map(|c| c.skill.as_str()), Some("wave"));
    }

    /// Terms and demands toward a person come from their specs like any act: what I carry for
    /// each thing to ask for (and lodging, the terms' own word), and the node `human_act` takes.
    #[test]
    fn to_a_person_i_offer_terms_and_make_demands() {
        let sc = Scripts::new(SKILLS).unwrap();
        let (aim, t) = person();
        let m = me(&[("berries", 4)], &[]);
        let c = choices(&sc, &m, &aim, Some(&t), &skills_of(&sc));
        let terms: Vec<&Choice> = c.iter().filter(|c| c.skill == "offer_terms").collect();
        assert!(terms.iter().any(|c| c.item.as_deref() == Some("berries") && c.want.as_deref() == Some("wood")), "{terms:?}");
        assert!(terms.iter().any(|c| c.want.as_deref() == Some("lodging")), "{terms:?}");
        assert!(terms.iter().all(|c| c.item.as_deref() != Some("stone")), "only what I carry is promised: {terms:?}");
        let node = terms.iter().find(|c| c.want.as_deref() == Some("wood")).unwrap().node(&aim, None);
        assert_eq!(node, serde_json::json!({"do": "offer_terms", "target": {"id": 7}, "item": "berries", "qty": 1, "want": "wood", "want_qty": 1}));
        living_rules::graph::parse(&node.to_string()).unwrap();
        assert!(c.iter().any(|c| c.skill == "demand" && c.item.as_deref() == Some("berries")), "{c:?}");
    }

    /// A skill the world's script adds is offered with no change here: declared by its spec,
    /// aimed by its check.
    #[test]
    fn at_remains_i_may_take_items_but_never_know_how() {
        let sc = Scripts::new(SKILLS).unwrap();
        let aim = Aim::Thing { class: "structure", kind: "remains".into(), at: Vec2::ZERO, id: 5, amount: 0.0, nearest: true };
        let t = thing_facts("structure", "remains", 5, 0.0, 1.0);
        // Play-test 2's newcomer: a bow, arrows and berries; fire, the fire bolt and wound tending.
        let m = me(&[("bow", 1), ("arrow", 30), ("berries", 4)], &["fire", "fire_bolt", "wound_tending"]);
        let c = choices(&sc, &m, &aim, Some(&t), &skills_of(&sc));
        let takes: Vec<&str> = c.iter().filter(|c| c.skill == "take").filter_map(|c| c.item.as_deref()).collect();
        assert!(takes.contains(&"berries") && takes.contains(&"bow"), "{takes:?}");
        for k in ["fire", "fire_bolt", "wound_tending"] {
            assert!(!takes.contains(&k), "take {k} offered: {takes:?}");
        }
        // To a person, what I know is still mine to teach.
        let (aim, t) = person();
        let c = choices(&sc, &m, &aim, Some(&t), &skills_of(&sc));
        assert!(c.iter().any(|c| c.skill == "teach" && c.item.as_deref() == Some("fire")), "{:?}", skills(&c));
    }

    #[test]
    fn a_skill_the_rules_add_is_offered() {
        let src = format!("{SKILLS}\nfn polish_spec() {{ #{{ target: true, reach: 1.3, about: \"polish a boulder\" }} }}\nfn polish_check(a) {{ if a.target.kind != \"boulder\" {{ return \"nothing to polish\"; }} \"\" }}\nfn polish_duration(a) {{ 2000 }}\nfn polish_done(a) {{ [] }}\n");
        let sc = Scripts::new(&src).unwrap();
        let boulder = Aim::Thing { class: "resource", kind: "boulder".into(), at: Vec2::ZERO, id: 3, amount: 5.0, nearest: true };
        let t = thing_facts("resource", "boulder", 3, 5.0, 1.0);
        let c = choices(&sc, &me(&[], &[]), &boulder, Some(&t), &skills_of(&sc));
        assert!(skills(&c).contains(&"polish".to_string()), "{c:?}");
        let (aim, t) = bush();
        let c = choices(&sc, &me(&[], &[]), &aim, Some(&t), &skills_of(&sc));
        assert!(!skills(&c).contains(&"polish".to_string()), "{c:?}");
        // Declared by the script alone, and never offered on myself: it takes a target.
        assert!(skills_of(&sc).iter().any(|k| k.name == "polish" && k.target));
        assert!(!skills(&choices(&sc, &me(&[], &[]), &Aim::Me, None, &skills_of(&sc))).contains(&"polish".to_string()));
    }

    #[test]
    fn nodes_name_targets_as_acts_do() {
        let (aim, _) = bush();
        let g = Choice::new("gather", "gather".into());
        assert_eq!(g.node(&aim, None), serde_json::json!({"do": "gather", "target": {"nearest": "berry_bush"}}));
        let far = Aim::Thing { class: "resource", kind: "berry_bush".into(), at: Vec2::new(3.0, 4.0), id: 9, amount: 4.0, nearest: false };
        assert_eq!(g.node(&far, None)["seq"][0]["do"], "goto");
        let give = Choice { item: Some("berries".into()), ..Choice::new("give", String::new()) };
        assert_eq!(give.node(&Aim::Creature { id: 7 }, None), serde_json::json!({"do": "give", "target": {"id": 7}, "item": "berries", "qty": 1}));
        for n in [g.node(&aim, None), g.node(&far, None), give.node(&Aim::Creature { id: 7 }, None)] {
            living_rules::graph::parse(&n.to_string()).unwrap();
        }
    }

    #[test]
    fn outcomes_read_short() {
        assert_eq!(outcome_text("You did what you had decided: eat berries."), (Some(true), "Eat berries".into()));
        assert_eq!(outcome_text("What you had decided did not work out: craft bow: you don't know how to make a bow (archery: learn it)."), (Some(false), "You don't know how to make a bow (archery: learn it)".into()));
    }
}
