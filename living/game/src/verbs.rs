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
/// A skill with more item options than this gets its own list.
const GROUP_OVER: usize = 2;
/// How often the hint's options are recomputed (s).
const HINT_EVERY_S: f64 = 0.25;
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
    /// Recompile when the `script` row changes (an install).
    fn refresh(&mut self, conn: &DbConnection) {
        let Some(row) = conn.db.script().name().find(&"skills".to_string()) else { return };
        if self.scripts.is_some() && row.revision == self.revision || self.error.is_some() && row.revision == self.revision {
            return;
        }
        self.revision = row.revision;
        match Scripts::new(&row.source) {
            Ok(s) => {
                self.skills = skills_of(&s);
                info!("rules: skill script revision {} compiled ({} skills)", row.revision, self.skills.len());
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
}

impl Choice {
    fn new(skill: &str, label: String) -> Self {
        Self { skill: skill.to_string(), item: None, want: None, words: false, say: None, label }
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
    let shapes = sc.shapes();
    let pack: Vec<(String, u32)> = me.actor.inv.clone();
    let techniques = me.actor.knows.clone();
    let on_thing = matches!(aim, Aim::Thing { .. });
    let my_kind = target.is_some_and(|t| t.class == "creature" && t.kind == me.actor.kind);
    let mut out = Vec::new();
    for spec in skills {
        let skill = spec.name.as_str();
        // Real-time skills (fighting, dashing) are the skill bar's; the rest are acts or behavior.
        if shapes.get(skill).is_some_and(|s| s.real_time) {
            continue;
        }
        let wants_target = *aim != Aim::Me;
        if spec.target != wants_target {
            continue;
        }
        let checked = has_check(sc, skill);
        if !checked && (on_thing || (wants_target && !my_kind)) {
            continue;
        }
        // An argument this client cannot give: a behavior graph (reworking one's ways).
        if spec.args.iter().any(|a| a == "graph") {
            continue;
        }
        let ctx = |item: &str, text: &str, tgt_holds: Option<&str>| {
            let mut t = target.cloned().unwrap_or_else(|| TargetFacts { class: "none".into(), ..Default::default() });
            // What a target holds is not perceived: assume it has what is asked of it.
            if let Some(i) = tgt_holds {
                if !t.inv.iter().any(|(k, _)| k == i) {
                    t.inv.push((i.to_string(), 1));
                }
            }
            SkillCtx { actor: me.actor.clone(), target: t, item: item.to_string(), qty: 1, night: me.night, hour: me.hour, season: "summer".into(), text: text.to_string(), roll: 0.5, skill: skill.to_string(), raining: me.raining, ..Default::default() }
        };
        let allowed = |item: &str, text: &str| sc.check(skill, &ctx(item, text, (!item.is_empty()).then_some(item))).is_ok();
        // Words: refused without, allowed with.
        let words_needed = |item: &str| checked && !allowed(item, "") && allowed(item, "…");
        if !spec.item {
            if allowed("", "") {
                out.push(Choice::new(skill, pretty(skill)));
            } else if words_needed("") {
                out.push(Choice { words: true, ..Choice::new(skill, format!("{} …", pretty(skill))) });
            }
            continue;
        }
        // Item candidates: what I carry, what I know, what the help names, and (for something
        // that may hold things) every item there is.
        let mut cands: Vec<String> = Vec::new();
        let listed = spec.items.clone();
        // A skill that asks something in return offers what I carry and its own words: the
        // rules let terms promise anything, and every item for every want is too long a list.
        let asks = spec.args.iter().any(|a| a == "want");
        if checked && asks {
            cands.extend(pack.iter().map(|(i, _)| i.clone()));
        } else if checked {
            cands.extend(pack.iter().map(|(i, _)| i.clone()));
            cands.extend(techniques.iter().cloned());
            if !matches!(aim, Aim::Me) {
                cands.extend(catalog::ITEMS.iter().map(|i| i.name.to_string()));
            }
        }
        cands.extend(listed);
        let mut seen = HashSet::new();
        cands.retain(|c| seen.insert(c.clone()));
        let have = |i: &str| pack.iter().find(|(k, _)| k == i).map(|(_, n)| *n);
        for item in cands {
            let ok = allowed(&item, "");
            let words = !ok && words_needed(&item);
            if !ok && !words {
                continue;
            }
            // How many I carry, unless it is the name of something I know (teach spear).
            let count = have(&item).filter(|_| !techniques.contains(&item)).map(|n| format!(" ×{n}")).unwrap_or_default();
            let label = format!("{} {}{count}{}", pretty(skill), pretty(&item), if words { " …" } else { "" });
            let c = Choice { item: Some(item.clone()), words, ..Choice::new(skill, label) };
            // A trade or terms name what I ask in return: one choice per thing to ask for.
            if asks {
                for w in catalog::ITEMS.iter().map(|i| i.name.to_string()).chain(spec.items.iter().cloned()).filter(|w| *w != item) {
                    out.push(Choice { want: Some(w.clone()), label: format!("{} {} for {}", pretty(skill), pretty(&item), pretty(&w)), ..c.clone() });
                }
            } else {
                out.push(c);
            }
        }
    }
    // What the rules check for this target first; skills they leave open (walk to, join) after.
    out.sort_by_key(|c| !has_check(sc, &c.skill));
    out
}

/// Requests in words to a person: to be taught what I don't know.
fn requests(me: &Me) -> Vec<Choice> {
    catalog::TECHNIQUES
        .iter()
        .filter(|t| !me.actor.knows.iter().any(|k| k == t.name))
        .map(|t| Choice { say: Some(format!("Would you teach me {}?", pretty(t.name))), label: format!("ask to be taught {}", pretty(t.name)), ..Choice::new("ask", String::new()) })
        .collect()
}

/// A list's rows: a skill with many options becomes one row opening its own list.
#[derive(Clone, Debug, PartialEq)]
pub enum Row {
    Pick(Choice),
    Group { name: String, label: String, count: usize },
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
/// first the rules allow that needs no further choice and is no use of force.
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
    choices.iter().find(|c| !c.words && c.want.is_none() && c.say.is_none() && !force(&c.skill) && per_skill(&c.skill) == 1)
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
}

impl Menu {
    pub fn rows(&self) -> Vec<Row> {
        let list: Vec<Choice> = match &self.item {
            Some(i) => self.choices.iter().filter(|c| c.item.as_deref() == Some(i)).cloned().collect(),
            None => self.choices.clone(),
        };
        rows(&list, self.group.as_deref())
    }
}

/// An act sent, awaiting the authority's word.
#[derive(Clone, Debug)]
struct Pending {
    sent_ms: f64,
    /// Through the act path (an outcome row will come) or as my behavior (the body shows it).
    act: bool,
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
    composing: bool,
    pending: Vec<Pending>,
    last: HashMap<String, Choice>,
    f_down: Option<f64>,
    hint_at: f64,
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
}

pub struct VerbsPlugin;

impl Plugin for VerbsPlugin {
    fn build(&self, app: &mut App) {
        app.init_non_send::<Rules>()
            .init_resource::<Verbs>()
            .init_resource::<Scripted>()
            .add_systems(Update, (aim, input, outcomes).chain().after(crate::combat::pick).after(crate::town::shows).before(crate::camera::follow));
    }
}

// ---- what I know of myself and of what I aim at ----------------------------------------

fn stage_name(s: u8) -> &'static str {
    match s {
        0 => "infant",
        1 => "child",
        3 => "elder",
        _ => "adult",
    }
}

/// My character's facts as far as its client knows them.
fn me_facts(conn: &DbConnection, me: u32, now_ms: f64, rules: &Scripts, weather: Option<bool>, things: &[(&'static str, String, Vec2, u64, f32)], at: Vec2) -> Me {
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
    let near = |kinds: &[&str], r: f32| things.iter().any(|(_, k, p, _, _)| kinds.contains(&k.as_str()) && p.distance(at) <= r);
    let actor = ActorFacts {
        id: me,
        kind: c.as_ref().map_or("person".into(), |c| c.kind.clone()),
        hp,
        hunger,
        energy,
        near_fire: near(&["campfire"], laws.fire_warmth),
        near_shelter: near(&["shelter", "house"], laws.shelter_warmth),
        // The ground under me is not in my rows; the authority decides where building works.
        terrain: "grass".into(),
        stage: stage_name(c.as_ref().map_or(2, |c| c.stage)).into(),
        inv,
        knows,
        age: 30.0,
        life: 0.4,
        room: 25,
        ..Default::default()
    };
    Me { actor, night: false, hour: 12.0, raining: weather.unwrap_or(false) }
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
fn label_of(conn: &DbConnection, id: u32) -> String {
    conn.db.seen_characters().id().find(&id).map_or_else(|| "someone".into(), |c| c.label)
}

/// The choices toward an aim, with its title.
fn options(conn: &DbConnection, rules: &Scripts, skills: &[Skill], me: &Me, my_at: Vec2, aim: &Aim) -> (String, Vec<Choice>) {
    match aim {
        Aim::Me => ("Yourself".into(), choices(rules, me, aim, None, skills)),
        Aim::Thing { class, kind, at, id, amount, .. } => {
            let t = thing_facts(class, kind, *id, *amount, at.distance(my_at));
            (pretty(kind), choices(rules, me, aim, Some(&t), skills))
        }
        Aim::Creature { id } => {
            let Some(t) = creature_facts(conn, rules, *id, 0.0) else { return (label_of(conn, *id), Vec::new()) };
            let person = t.kind == me.actor.kind;
            let mut c = choices(rules, me, aim, Some(&t), skills);
            if person && t.kind == "person" {
                c.extend(requests(me));
            }
            (label_of(conn, *id), c)
        }
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
    let me_facts = me_facts(conn, me, scene.now_ms, sc, weather.authority.map(|(r, _)| r), &all, my_at);
    match aim {
        Some(a) => {
            let (name, ch) = options(conn, sc, &rules.skills, &me_facts, my_at, &a);
            let key = a.key(|id| conn.db.seen_characters().id().find(&id).map_or_else(String::new, |c| c.kind));
            v.likely = likely(sc, &a, &ch, v.last.get(&key)).cloned();
            v.has_options = !ch.is_empty();
            v.aim_name = name;
            v.aim = Some(a);
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
        let r = conn.reducers.human_say_then(line.clone(), to, net.on_reply("say"));
        if r.is_ok() {
            input.said.push((now_ms as u64, line.clone()));
        }
        net.report("say", r);
        return;
    }
    let node = c.node(aim, text);
    // An act (a one-off the authority reports on) or behavior (ongoing: the body shows it).
    let act = node.get("do").is_some() && living_rules::acts::not_an_act(&c.skill, rules.shapes()).is_none();
    info!("verbs: {} → {}", c.label, node);
    let r = conn.reducers.human_act_then(node.to_string(), net.on_reply("act"));
    net.report("act", r);
    v.pending.push(Pending { sent_ms: now_ms, act });
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
) {
    let now = time.elapsed_secs_f64();
    let now_ms = scene.now_ms;
    wants.menu = v.menu.is_some() || v.inventory || v.know_how;
    let (Some(conn), Some(me), Some(me3), Some(sc)) = (net.conn.as_ref(), net.my_id, target.0, rules.scripts.as_ref()) else {
        v.menu = None;
        return;
    };
    let my_at = Vec2::new(me3.x, me3.z);
    let typing = controls.chat_open || wants.keyboard;
    let free = !typing && !controls.demo;
    let pressed = |k: KeyCode| free && keys.just_pressed(k);
    let all = || things(conn, now_ms);
    let facts = |_: &Aim| me_facts(conn, me, now_ms, sc, weather.authority.map(|(r, _)| r), &all(), my_at);
    let open = |v: &mut Verbs, aim: Aim, item: Option<String>| {
        let (title, choices) = options(conn, sc, &rules.skills, &facts(&aim), my_at, &aim);
        v.menu = Some(Menu { aim, title, choices, group: None, item });
    };
    let mut pick: Option<usize> = None;

    // Panels.
    if pressed(INVENTORY) {
        v.inventory = !v.inventory;
    }
    if pressed(KNOW_HOW) {
        v.know_how = !v.know_how;
    }
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
    if v.menu.is_none() && pressed(INTERACT) {
        v.f_down = Some(now);
    }
    if let Some(t0) = v.f_down {
        let released = keys.just_released(INTERACT) || !keys.pressed(INTERACT);
        let held = now - t0 >= HOLD_S;
        if held || released {
            v.f_down = None;
            if let Some(aim) = v.aim.clone() {
                match v.likely.clone().filter(|_| !held) {
                    Some(c) if c.words => v.compose = Some((aim, c)),
                    Some(c) => send(&net, conn, sc, &aim, &c, None, now_ms, &mut v, &mut controls),
                    None if v.has_options => open(&mut v, aim, None),
                    None => {
                        let text = format!("Nothing to do with {}", v.aim_name);
                        v.toasts.push(Toast { text, ok: None, at: now });
                    }
                }
            } else {
                open(&mut v, Aim::Me, None);
            }
        }
    } else if v.menu.as_ref().is_some_and(|m| m.aim != Aim::Me) && pressed(INTERACT) {
        v.menu = None;
    }
    // C: acts on myself.
    if pressed(SELF_ACTS) {
        if v.menu.as_ref().is_some_and(|m| m.aim == Aim::Me) {
            v.menu = None;
        } else {
            open(&mut v, Aim::Me, None);
        }
    }
    if free && keys.just_pressed(KeyCode::Escape) {
        match v.menu.as_mut() {
            Some(m) if m.group.is_some() => m.group = None,
            Some(_) => v.menu = None,
            None => {
                v.inventory = false;
                v.know_how = false;
            }
        }
    }
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
            _ => {
                v.inventory = false;
                v.know_how = false;
            }
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
    wants.menu = v.menu.is_some() || v.inventory || v.know_how;
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
        if let Some(why) = e.strip_prefix("act refused: ") {
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
        let (ok, text) = outcome_text(&e.text);
        v.toasts.push(Toast { text, ok, at: now });
        if let Some(i) = v.pending.iter().position(|p| p.act) {
            v.pending.remove(i);
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
    fn a_bush_is_gathered_and_a_tap_gathers() {
        let sc = Scripts::new(SKILLS).unwrap();
        let (aim, t) = bush();
        let c = choices(&sc, &me(&[], &[]), &aim, Some(&t), &skills_of(&sc));
        // Gathering, and turning to face it (the rules' `face` takes anything in sight).
        assert_eq!(skills(&c), vec!["gather", "face"], "{c:?}");
        assert_eq!(likely(&sc, &aim, &c, None).map(|c| c.skill.as_str()), Some("gather"));
        // A full pack: the rules refuse to gather, so it is not offered.
        let full = me(&[("wood", 40)], &[]);
        assert_eq!(skills(&choices(&sc, &full, &aim, Some(&t), &skills_of(&sc))), vec!["face"]);
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

    /// A skill the world's script adds is offered with no change here: declared by its spec,
    /// aimed by its check.
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
