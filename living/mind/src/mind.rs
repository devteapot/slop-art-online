//! The cognitive loop for every AI character this service controls.
//!
//! - Experiences (SpacetimeDB, written by the authority) are integrated by consolidation:
//!   an LLM reasoning episode writes an open graph patch into the character's Neo4j mind,
//!   updates behavior-facing projections (relations, judgments, places, identity) and
//!   advances the character's `mind_cursor`. Nothing is lost if the service restarts.
//! - Deliberation requests (SpacetimeDB) are answered with a behavior graph and speech,
//!   using the part of the mind that concerns what the character currently perceives.
//! Every reasoning episode is logged as a `thought` with a `reference` the mind graph
//! points back to; exact prompts and replies are journaled on disk.

use crate::llm::{self, Lane, Llm, Msg};
use crate::memory::{self, Store};
use crate::prompts;
use anyhow::{anyhow, Result};
use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, Identity, Table};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::sync::{oneshot, Semaphore};

mod animal;
mod dealings;
mod judge;
mod lived;
pub mod lod;
mod recall;
pub mod rethink;
mod sleep;
mod talk;
mod woken;

/// How much of a remembered thing's salience and confidence is kept after a step failed at it.
const MISSED_WEAKEN: f64 = 0.5;

pub enum Event {
    /// Speech heard (or unanswered) by one of this service's characters.
    Speech(Experience),
    Deliberation(u32),
    /// With the level of detail on: a pending deliberation as it now stands (inserted or
    /// merged), and the exact old row that is gone.
    Pending(Deliberation),
    PendingGone(Deliberation),
    /// With the level of detail on: a human player was part of what this character experienced.
    Contact(u32),
    /// With `LIVING_PLAYER_MEMORY=1`: an experience of a character a person plays.
    Lived(Experience),
    /// With the rethink gate on: a percept of one of this service's characters.
    Percept(Experience),
    /// A resident was woken into a mind (docs/TOWN_LIFE.md, "Layer 2").
    Woken(u32),
}

pub use lived::enabled as player_memory;

#[derive(Default)]
struct ActorMind {
    consolidating: bool,
    deliberating: bool,
    again: bool,
    last_consolidated: Option<Instant>,
    failures: u32,
    retry_after: Option<Instant>,
    /// Parts of the last graph that were invalid and pruned (fed back next time).
    pruned: Vec<String>,
    /// Merges refused since the last reorganization, and why (fed back in the next one).
    refused_merges: Vec<String>,
    /// The last experience read for failures at remembered things (`weaken_missed`); `None`
    /// until read from the mind after a start.
    missed_upto: Option<u64>,
    /// Integrations since the last reorganization ("sleep") of the mind.
    since_sleep: u32,
    last_sleep: Option<Instant>,
    /// The night it last went to sleep on, and whether its last batch failed (the next sleep
    /// is then a direct call); see sleep.rs.
    slept_night: Option<u64>,
    direct_next: bool,
    /// Level of detail (see lod.rs): when the last deliberation ended, until when the
    /// character is on stage, and when it last took a conversation turn.
    last_deliberated: Option<Instant>,
    onstage_until: Option<Instant>,
    last_talk: Option<Instant>,
    /// A pending deliberation is being held back off stage (it does not keep the character
    /// from conversation turns meanwhile).
    deferring: bool,
    /// Deliberations in a row whose model could not be reached (their request waits).
    model_failures: u32,
}

/// Where a character's first identity comes from, when the service finds none.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Origin {
    /// Its world's author wrote it (installed as written).
    Sheet,
    /// A child, raised by its parents (`birth_persona`, written as a very young child).
    Birth,
    /// From its background row (town, occupation, household), by one identity call.
    Background,
    /// The seed's own persona for it, if the seed has one (and animals' species nature).
    /// Nothing is written otherwise: a joined player's character, for one, is who its
    /// conduct shows (docs/PLAYER_MEMORY.md).
    Seed,
}

impl Origin {
    /// By life stage before parentage: an authored resident's sheet may name parents at any
    /// age (`seed.rs`, authored towns), and an adult with a parent recorded was given a
    /// newborn's identity ("I am very small"). Only the young (infant or child) are born into one.
    fn of(person: bool, sheet: bool, background: bool, stage: u8, parent: bool, seeded: bool) -> Self {
        let young = stage <= 1;
        match (person, sheet, parent && young, background, seeded) {
            (false, ..) if parent => Self::Birth,
            (false, ..) => Self::Seed,
            (true, true, ..) => Self::Sheet,
            (true, false, true, ..) => Self::Birth,
            (true, false, false, true, _) => Self::Background,
            (true, false, false, false, _) => Self::Seed,
        }
    }
}

/// A deliberation whose model could not be reached (an outage, a refused or failed call): its
/// request is kept, not skipped.
#[derive(Debug)]
struct ModelUnavailable(String);

impl std::fmt::Display for ModelUnavailable {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "model unavailable: {}", self.0)
    }
}

impl std::error::Error for ModelUnavailable {}

/// A model call's error, as a deliberation whose model could not be reached.
pub(super) fn unavailable(e: anyhow::Error) -> anyhow::Error {
    anyhow::Error::new(ModelUnavailable(format!("{e:#}")))
}

/// How long a request waits after its model failed `failures` times in a row: 5 s, doubling,
/// at most 5 minutes.
fn model_backoff(failures: u32) -> Duration {
    Duration::from_secs((5u64 << failures.saturating_sub(1).min(6)).min(300))
}

pub struct Minds {
    pub conn: DbConnection,
    llm: Llm,
    store: Option<Store>,
    seed: Value,
    species: std::collections::BTreeMap<String, living_rules::species::Species>,
    me: Identity,
    actors: Mutex<HashMap<u32, ActorMind>>,
    /// Bound concurrent background memory work independently of network admission.
    slow: Semaphore,
    talk: Mutex<talk::Talks>,
    only: Option<std::collections::HashSet<u32>>,
    /// `LIVING_ONLY` names `woken`: residents woken into minds are this service's too.
    only_woken: bool,
    /// Woken residents whose minds are being made, and stage-cap reports (woken.rs).
    wakes: woken::WakesLock,
    lod: lod::Lod,
    /// Pending deliberations by actor (kept only with the level of detail on, when many
    /// requests wait at once and scanning the view for each would be costly).
    pending: Mutex<HashMap<u32, lod::PendingRequest>>,
    /// Each person's model group (see `llm::group_of`; it never changes) and the profile
    /// last logged for each character.
    groups: Mutex<HashMap<u32, Option<String>>>,
    routed: Mutex<HashMap<u32, String>>,
    /// What human-played characters live, waiting to be internalized (see lived.rs).
    lived_cfg: lived::Config,
    lived: Mutex<lived::Lived>,
    /// When minds reorganize (sleep.rs), and when the last night batch went out.
    sleep_cfg: sleep::Config,
    sleep_batch_at: Mutex<Option<Instant>>,
    /// Cheaper animal minds (animal.rs): the switches, each animal's last salient signature
    /// and the pack decisions shared with members.
    animal_cfg: animal::Config,
    animal_sigs: Mutex<HashMap<u32, animal::Signature>>,
    packs: Mutex<HashMap<u32, animal::PackDecision>>,
    /// Typed judgments refreshed in the background (judge.rs; `LIVING_JEV=1`).
    jev: Option<judge::Jev>,
    asked: Mutex<HashMap<u32, judge::Asked>>,
    /// Each character's body as it last perceived it (its latest deliberation scene's `you`),
    /// for judgments between thoughts.
    felt: Mutex<HashMap<u32, (Instant, Value)>>,
    /// The rethink gate in front of non-urgent deliberations (rethink.rs; `LIVING_RETHINK`).
    rethink: Option<rethink::Gate>,
    rethink_track: Mutex<HashMap<u32, rethink::Track>>,
    rethink_stats: Mutex<rethink::Stats>,
    rethink_logged: Mutex<Option<Instant>>,
}

fn flatten<E: std::fmt::Debug>(r: Result<Result<(), String>, E>) -> Result<(), String> {
    match r {
        Ok(r) => r,
        Err(e) => Err(format!("{e:?}")),
    }
}

fn strings(x: &Value) -> Vec<String> {
    x.as_array().map(|a| a.iter().filter_map(|s| s.as_str().map(String::from)).collect()).unwrap_or_default()
}

/// A reply's deliberate acts (`acts`, or a single `act`), as JSON for `mind_act`; the
/// authority normalizes each for the body and tells back any it cannot do.
pub(crate) fn acts_of(v: &Value) -> Vec<String> {
    let list = match (&v["acts"], &v["act"]) {
        (Value::Array(a), _) => a.clone(),
        (o @ Value::Object(_), _) => vec![o.clone()],
        (_, o @ Value::Object(_)) => vec![o.clone()],
        _ => Vec::new(),
    };
    list.into_iter().filter(|x| x.is_object()).take(living_rules::acts::MAX_QUEUED).map(|x| x.to_string()).collect()
}

/// The persona's line on one's community: how many others belong, and by name only those one
/// has feelings about (a town of 77 listed every name: 11–20% of a think or consolidation
/// prompt, growing with the town).
fn belonging(community: &str, others: usize, known: &[String]) -> String {
    const NAMED: usize = 12;
    let mut line = format!("\nYou belong to {community}");
    match others {
        0 => line.push_str(" (no one else yet)"),
        1 => line.push_str(" (with one other"),
        n => line.push_str(&format!(" (with {n} others")),
    }
    if others > 0 {
        if !known.is_empty() {
            let more = known.len().saturating_sub(NAMED);
            line.push_str(&format!(", among them {}{}", known[..known.len().min(NAMED)].join(", "), if more > 0 { format!(" and {more} more you know") } else { String::new() }));
        }
        line.push(')');
    }
    line
}

/// Speech is not an act: the authority refuses `{"do": "say"}` ("an act is a single {"do":
/// skill, ...} node"). A compile that expressed the decision's words as one (15 of 434
/// compiles on rules2-r2, by this count; reviewers counted 15, when the think step put them in `intend`) would have them never
/// spoken. The first such act becomes the reply's `say` when it has none, and every say act
/// leaves the acts.
fn say_acts_into_speech(v: &mut Value) {
    let is_say = |a: &Value| a["do"].as_str().is_some_and(|d| d.trim().eq_ignore_ascii_case("say"));
    let mut said: Vec<Value> = Vec::new();
    if let Some(acts) = v.get_mut("acts").and_then(|a| a.as_array_mut()) {
        said.extend(acts.iter().filter(|a| is_say(a)).cloned());
        acts.retain(|a| !is_say(a));
    }
    if v.get("acts").is_some_and(|a| is_say(a)) {
        said.push(v["acts"].take());
    }
    if v.get("act").is_some_and(|a| is_say(a)) {
        said.push(v["act"].take());
    }
    let silent = match &v["say"] {
        Value::String(s) => s.trim().is_empty(),
        Value::Object(o) => o.get("text").and_then(|t| t.as_str()).is_none_or(|t| t.trim().is_empty()),
        _ => true,
    };
    let words = said.iter().find_map(|a| {
        let text = a["text"].as_str().or_else(|| a["say"].as_str()).map(str::trim).filter(|t| !t.is_empty())?;
        let to = a.get("to").and_then(living_rules::normalize::reply_id).or_else(|| a["target"].get("id").and_then(living_rules::normalize::reply_id));
        Some(json!({"text": text, "to": to}))
    });
    if let (true, Some(words)) = (silent, words) {
        v["say"] = words;
    }
}

/// Real-time moves a mind decided on as acts (dodge, block, attack, flee...) are its body's
/// behavior, not one-off acts: they become what it means to do now (its intent), weighed
/// above staying safe since it chose them in the moment, instead of being refused. In the
/// village, minds decided "dodge, block, throw my spear" while a wolf killed them one by one,
/// and every such decision was refused as an act.
fn real_time_into_intent(v: &mut Value) {
    let skill_of = |a: &Value| match &a["do"] {
        Value::String(s) => Some(s.to_lowercase()),
        Value::Object(o) => o.get("skill").and_then(|s| s.as_str()).map(|s| s.to_lowercase()),
        _ => a["skill"].as_str().map(|s| s.to_lowercase()),
    };
    let Some(acts) = v.get("acts").and_then(|a| a.as_array()).cloned() else { return };
    let shapes = prompts::shapes();
    let (moves, rest): (Vec<Value>, Vec<Value>) = acts.into_iter().partition(|a| skill_of(a).is_some_and(|s| shapes.real_time(&s)));
    if moves.is_empty() {
        return;
    }
    v["acts"] = Value::Array(rest);
    let fight = if moves.len() == 1 { moves[0].clone() } else { json!({"seq": moves}) };
    let graph = match v.get("intent").and_then(|i| i.get("graph")).filter(|g| g.is_object()) {
        Some(g) => json!({"first": [fight, g.clone()]}),
        None => fight,
    };
    v["intent"] = json!({"weight": {"base": 3.5}, "graph": graph});
}

/// A short description of acts for logs and thought summaries.
pub(crate) fn acts_text(acts: &[String]) -> String {
    acts.iter()
        .map(|a| {
            serde_json::from_str::<Value>(a)
                .ok()
                .and_then(|v| living_rules::acts::parse(v, None, &prompts::shapes()).ok())
                .map(|x| living_rules::graph::describe(&living_rules::graph::Node::Do(x)))
                .unwrap_or_else(|| a.chars().take(80).collect())
        })
        .collect::<Vec<_>>()
        .join("; ")
}

fn reference(actor: u32, kind: &str) -> String {
    format!("{kind}-{actor}-{}", llm::now_ms())
}

impl Minds {
    pub fn new(conn: DbConnection, llm: Llm, store: Option<Store>, seed: Value, concurrency: usize) -> Result<Arc<Self>> {
        let me = conn.try_identity().ok_or_else(|| anyhow!("not connected"))?;
        let species = living_rules::species::parse(&std::fs::read_to_string(crate::root().join("living/seeds/species.json"))?).map_err(|e| anyhow!(e))?;
        let jev = judge::Jev::from_env(&crate::root())?;
        let rethink = rethink::Gate::from_env(&crate::root())?;
        if let Some(j) = &jev {
            prompts::set_judgments(j.grammar());
        }
        let only_env = std::env::var("LIVING_ONLY").ok();
        let only_woken = only_env.as_deref().is_some_and(|v| v.split(',').any(|x| x.trim() == "woken"));
        let lived_cfg = lived::Config::from_env();
        if lived_cfg.on {
            if let Some(route) = &lived_cfg.profile {
                llm.warn_effort_gaps("LIVING_PLAYER_MEMORY_MODEL", route, &["internalize"]);
            }
        }
        Ok(Arc::new(Self { conn, llm, store, seed, species, me, actors: Mutex::new(HashMap::new()), slow: Semaphore::new((concurrency / 2).max(1)), talk: Mutex::new(talk::Talks::default()), only: only_env.map(|v| v.split(',').filter_map(|x| x.trim().parse().ok()).collect()), only_woken, wakes: Default::default(), lod: lod::Lod::from_env(), pending: Mutex::new(HashMap::new()), groups: Mutex::new(HashMap::new()), routed: Mutex::new(HashMap::new()), lived_cfg, lived: Mutex::new(lived::Lived::default()), sleep_cfg: sleep::Config::from_env(), sleep_batch_at: Mutex::new(None), animal_cfg: animal::Config::from_env(), animal_sigs: Mutex::new(HashMap::new()), packs: Mutex::new(HashMap::new()), jev, asked: Mutex::new(HashMap::new()), felt: Mutex::new(HashMap::new()), rethink, rethink_track: Mutex::new(HashMap::new()), rethink_stats: Mutex::new(rethink::Stats::default()), rethink_logged: Mutex::new(None) }))
    }

    /// Characters this service thinks for: alive, AI-controlled, and past infancy (infants
    /// run on their instincts until they become children).
    fn mine(&self) -> Vec<Character> {
        self.conn.db.character().iter().filter(|c| c.ai && c.alive && c.stage != 0 && c.controller == self.me && self.allowed(c.id)).collect()
    }

    /// A character's model. A person thinks with their group's (`groups` in the models file:
    /// their town or band, or for those born in the world their parents') unless assigned
    /// one by name; without a group, children think with the "child" stage model when
    /// configured. Otherwise assignment, rotation or the default. Logged when it changes.
    fn profile(&self, c: &Character) -> String {
        let group = if c.kind == "person" { self.group(c.id) } else { None };
        // A resident woken into a mind takes the models file's `woken` route when it has one.
        let woken = (c.kind == "person" && self.is_woken(c.id)).then(|| self.llm.woken_route(&c.name)).flatten();
        let p = if let Some(w) = woken {
            w
        } else if c.kind == "person" {
            self.llm.person_profile(c.id, &c.name, group.as_deref(), c.stage <= 1)
        } else {
            self.llm.profile_for(c.id, &c.name)
        };
        if self.routed.lock().unwrap().insert(c.id, p.clone()).as_ref() != Some(&p) {
            log::info!("{} (#{}) thinks with profile {p} ({}){}", c.name, c.id, self.llm.model_name(&p), group.map(|g| format!(", group {g}")).unwrap_or_default());
        }
        p
    }

    /// A person's model group: the `town` or `band` of their background, or their parents'.
    fn group(&self, id: u32) -> Option<String> {
        if !self.llm.has_groups() {
            return None;
        }
        if let Some(g) = self.groups.lock().unwrap().get(&id) {
            return g.clone();
        }
        let of = |x: u32| {
            let c = self.conn.db.character().id().find(&x)?;
            let bg: Value = self.conn.db.background().id().find(&x).and_then(|b| serde_json::from_str(&b.text).ok()).unwrap_or_default();
            Some((bg["town"].as_str().or(bg["band"].as_str()).map(String::from), c.parent_a, c.parent_b))
        };
        let g = llm::group_of(id, &of, llm::GROUP_DEPTH);
        self.groups.lock().unwrap().insert(id, g.clone());
        g
    }

    /// `LIVING_ONLY=3,7` limits this service to those characters (experiments on a seeded
    /// world); the rest keep running on their instincts. `woken` in the list admits every
    /// resident woken into a mind as well (`LIVING_ONLY=12,woken`).
    fn allowed(&self, id: u32) -> bool {
        self.only.as_ref().map_or(true, |o| o.contains(&id) || (self.only_woken && self.is_woken(id)))
    }

    /// How `me` knows `other`: their name where the authority counts it known
    /// (`perception::knows_name`: itself, family, the other parent of its children, its
    /// community, someone who told it their name), else "a stranger" (docs/PERCEPTION.md: names
    /// only when known). For prompts and for what goes into a character's own memory; logs and
    /// developer records keep names.
    pub(super) fn known_as(&self, me: u32, other: u32) -> String {
        let Some(o) = self.conn.db.character().id().find(&other) else { return "someone".into() };
        let family = |a: &Character, b: &Character| a.parent_a == b.id || a.parent_b == b.id || b.parent_a == a.id || b.parent_b == a.id;
        let community = |id: u32| self.conn.db.membership().iter().find(|m| m.member == id).map(|m| m.community);
        let known = me == other
            || self.conn.db.acquaintance().iter().any(|a| a.observer == me && a.known == other)
            || self.conn.db.character().id().find(&me).is_some_and(|m| family(&m, &o))
            || community(me).is_some_and(|k| community(other) == Some(k))
            || self.conn.db.character().iter().any(|k| (k.parent_a == me && k.parent_b == other) || (k.parent_b == me && k.parent_a == other));
        if known {
            o.name
        } else if o.kind != "person" {
            format!("a {}", o.kind)
        } else {
            "a stranger".into()
        }
    }

    fn name(&self, id: u32) -> String {
        self.conn.db.character().id().find(&id).map(|c| c.name).unwrap_or_else(|| format!("#{id}"))
    }

    fn fmt_time(&self) -> impl Fn(u64) -> String {
        let w = self.conn.db.world().id().find(&0);
        let (epoch, day) = w.map(|w| (w.epoch_ms, w.day_ms)).unwrap_or((0, living_rules::DEFAULT_DAY_MS));
        move |t| {
            if t == 0 {
                return "long ago".into();
            }
            let h = living_rules::hour_of(t, epoch, day);
            format!("day {} {:02}:{:02}", living_rules::day_of(t, epoch, day), h as u32, (h.fract() * 60.0) as u32)
        }
    }

    /// The character's needs and health now, from its `vitals` row (needs move linearly between
    /// writes, at the row's rates, as `common::needs` in the authority computes them).
    pub(crate) fn body_now(&self, actor: u32) -> Option<prompts::Body> {
        let v = self.conn.db.vitals().id().find(&actor)?;
        let m = llm::now_ms().saturating_sub(v.at_ms) as f32 / 60_000.0;
        Some(prompts::Body {
            hp: (v.hp + v.hp_rate * m).clamp(0.0, v.max_hp),
            max_hp: v.max_hp,
            hunger: (v.hunger + v.hunger_rate * m).clamp(0.0, 100.0),
            energy: (v.energy + v.energy_rate * m).clamp(0.0, 100.0),
            hp_rate: v.hp_rate,
        })
    }

    /// How the character's body feels now, in words; empty when its vitals are not known.
    pub(crate) fn body_text(&self, actor: u32) -> String {
        self.body_now(actor).map(prompts::felt_body).unwrap_or_default()
    }

    /// The character's routines as the mind sees them: how each has gone, and its graph.
    fn repertoire_text(&self, actor: u32) -> String {
        let mut out = String::new();
        for (i, (r, head)) in self.routine_digest(actor).iter().enumerate() {
            out.push_str(&format!("## {head} [{}]\n", r.source));
            if i < 12 {
                if let Ok(g) = living_rules::graph::parse(&r.graph) {
                    out.push_str(&living_rules::graph::outline(&g.root));
                }
            }
        }
        out
    }

    /// One line per routine (those the top level calls first, then the latest changed): its
    /// name, what it serves and how that need stands, and how it has gone since it last changed.
    fn routine_digest(&self, actor: u32) -> Vec<(Routine, String)> {
        let top = self.conn.db.brain().id().find(&actor).and_then(|b| living_rules::graph::parse(&b.graph).ok());
        let called: Vec<String> = top.as_ref().map(|g| living_rules::graph::routines_called(&g.root).into_iter().map(|r| r.to_lowercase()).collect()).unwrap_or_default();
        let mut rs: Vec<Routine> = self.conn.db.routine().iter().filter(|r| r.actor == actor).collect();
        rs.sort_by_key(|r| (!called.contains(&r.name.to_lowercase()), std::cmp::Reverse(r.updated_ms)));
        // What each routine is for, and how that need stands now (so a routine that "succeeds"
        // while its need goes unmet shows as such).
        let vit = self.body_now(actor);
        let serves: Vec<(String, String)> = match top.as_ref().map(|g| &g.root) {
            Some(living_rules::graph::Node::Desires(ds)) => ds
                .iter()
                .filter_map(|d| {
                    let living_rules::graph::Node::Routine(name) = &*d.body else { return None };
                    let w = &d.weight;
                    let state = vit.as_ref().map(|v| {
                        let mut parts = Vec::new();
                        if w.hunger > 0.0 {
                            parts.push(format!("hunger {:.0}/100", v.hunger));
                        }
                        if w.tired > 0.0 {
                            parts.push(format!("energy {:.0}/100", v.energy));
                        }
                        if w.hurt > 0.0 {
                            parts.push(format!("health {:.0}/{:.0}", v.hp, v.max_hp));
                        }
                        parts.join(", ")
                    });
                    let state = state.filter(|s| !s.is_empty()).map(|s| format!(": {s}")).unwrap_or_default();
                    Some((name.to_lowercase(), format!("serves {}{state}", d.want)))
                })
                .collect(),
            _ => Vec::new(),
        };
        rs.into_iter()
            .map(|r| {
                let stat = self.conn.db.routine_stat().id().find(&r.id);
                let how = match &stat {
                    Some(s) if s.failed > 0 && !s.last_fail.is_empty() => format!("done {}×, failed {}× (last: {})", s.ok, s.failed, s.last_fail),
                    Some(s) => format!("done {}×, failed {}×", s.ok, s.failed),
                    None => "not tried yet".into(),
                };
                let serve = serves.iter().filter(|(n, _)| *n == r.name.to_lowercase()).map(|(_, t)| format!(" ({t})")).collect::<String>();
                let head = format!("{}{serve} — {how}", r.name);
                (r, head)
            })
            .collect()
    }

    /// A reply's `intent` ({"weight", "graph"}) as ordinary edits: the graph becomes the
    /// "current plan" routine and the top level weighs it among the character's desires.
    /// Replies without one (or with a new top level of their own) pass through unchanged.
    fn plan_into_desires(&self, actor: u32, v: Value) -> Option<Value> {
        let person = self.conn.db.character().id().find(&actor).map_or(false, |c| c.kind == "person");
        let v = self.plan_as_intent(actor, v, person)?;
        Some(if person { self.keep_needs(actor, v) } else { v })
    }

    /// A person's needs (food, sleep, safety, warmth) belong to the body: however a top level
    /// is rewritten, those desires stay among it (their weights remain the person's to set), and
    /// their routines are restored from the person's first habits if retired. A top level that
    /// is not desires at all is rebuilt around them.
    fn keep_needs(&self, actor: u32, mut v: Value) -> Value {
        let rep: Value = serde_json::from_str(include_str!("../../seeds/repertoire.json")).unwrap_or_default();
        let seed: Vec<Value> = rep["top"]["desires"].as_array().cloned().unwrap_or_default();
        let needs: Vec<Value> = seed.into_iter().filter(|d| matches!(d["want"].as_str(), Some("food" | "sleep" | "safety" | "warmth"))).collect();
        let routine_of = |d: &Value| d["do"]["routine"].as_str().unwrap_or_default().to_lowercase();
        let current_is_desires = self.conn.db.brain().id().find(&actor).map_or(false, |b| b.graph.trim_start().starts_with("{\"desires\""));
        if !v["graph"].is_object() && !current_is_desires {
            // Repair a top level that lost its desires (the plan, if any, stays as a desire).
            let mut ds = needs.clone();
            if self.conn.db.routine().iter().any(|r| r.actor == actor && r.name.eq_ignore_ascii_case(living_rules::graph::PLAN_ROUTINE)) {
                ds.insert(0, json!({"want": living_rules::graph::PLAN_WANT, "weight": {"base": 0.6}, "do": {"routine": living_rules::graph::PLAN_ROUTINE}}));
            }
            v["graph"] = json!({"desires": ds});
        }
        if let Some(ds) = v["graph"].get_mut("desires").and_then(|d| d.as_array_mut()) {
            for n in &needs {
                if !ds.iter().any(|d| routine_of(d) == routine_of(n) || d["want"] == n["want"]) {
                    ds.push(n.clone());
                }
            }
            let mut routines = v["routines"].as_array().cloned().unwrap_or_default();
            for n in &needs {
                let name = routine_of(n);
                let have = self.conn.db.routine().iter().any(|r| r.actor == actor && r.name.to_lowercase() == name)
                    || routines.iter().any(|r| r["name"].as_str().map_or(false, |x| x.to_lowercase() == name) && !r["graph"].is_null());
                if !have {
                    if let Some(g) = rep["common"].get(name.as_str()) {
                        routines.push(json!({"name": name, "graph": g}));
                    }
                }
            }
            v["routines"] = Value::Array(routines);
        }
        v
    }

    fn plan_as_intent(&self, actor: u32, mut v: Value, person: bool) -> Option<Value> {
        // A top level replaces the character's ways only when it says so ("restructure"), and
        // only as desires; otherwise a graph is what it means to do now, weighed like an intent.
        let restructure = v["restructure"].as_bool() == Some(true) && (!person || v["graph"].get("desires").is_some());
        let intent = match v.get("intent").filter(|i| i.is_object()) {
            Some(i) => i.clone(),
            None if v["graph"].is_object() && !restructure => json!({"weight": v.get("weight").cloned().unwrap_or(json!(0.6)), "graph": v["graph"].clone()}),
            None => return Some(v),
        };
        let own_top = v["graph"].is_object() && restructure;
        let weight = match &intent["weight"] {
            Value::Number(n) => living_rules::graph::Weight { base: n.as_f64().unwrap_or(0.6) as f32, ..Default::default() },
            w @ Value::Object(_) => serde_json::from_value(w.clone()).unwrap_or(living_rules::graph::Weight { base: 0.6, ..Default::default() }),
            _ => living_rules::graph::Weight { base: 0.6, ..Default::default() },
        };
        let top = self.conn.db.brain().id().find(&actor).and_then(|b| living_rules::graph::parse(&b.graph).ok())?;
        let mut routines = v["routines"].as_array().cloned().unwrap_or_default();
        routines.push(json!({"name": living_rules::graph::PLAN_ROUTINE, "graph": intent["graph"]}));
        v["routines"] = Value::Array(routines);
        if !own_top {
            match living_rules::graph::with_plan(&top.root, weight.clone()) {
                Some(root) => v["graph"] = serde_json::to_value(&root).ok()?,
                // A flat top level has nothing to weigh against: for a person it is rebuilt
                // around their needs (see keep_needs) with the plan among them; an animal's
                // plan is its top level.
                None if person => {
                    v["graph"] = json!({"desires": [{"want": living_rules::graph::PLAN_WANT, "weight": serde_json::to_value(&weight).ok()?, "do": {"routine": living_rules::graph::PLAN_ROUTINE}}]});
                }
                None => v["graph"] = intent["graph"].clone(),
            }
        }
        Some(v)
    }

    /// Apply routine edits from a reply: add/replace (normalized for this body) or retire.
    async fn apply_routines(&self, c: &Character, v: &Value) -> Result<()> {
        let Some(items) = v.as_array() else { return Ok(()) };
        let mut edits = Vec::new();
        for it in items.iter().take(8) {
            let name = it["name"].as_str().unwrap_or_default().trim().to_string();
            if name.is_empty() {
                continue;
            }
            if it["retire"].as_bool() == Some(true) || it["graph"].is_null() {
                edits.push(RoutineIn { name, graph: String::new() });
                continue;
            }
            let parsed = match self.species.get(&c.kind) {
                Some(sp) => living_rules::graph::from_value_for(it["graph"].clone(), sp),
                None => living_rules::graph::from_value_lenient(it["graph"].clone()),
            };
            match parsed {
                Ok((g, _)) => edits.push(RoutineIn { name, graph: g.to_json() }),
                Err(e) => log::info!("{}: routine {name} not kept: {e}", c.name),
            }
        }
        if edits.is_empty() {
            return Ok(());
        }
        log::info!("{} reworks routines: {}", c.name, edits.iter().map(|e| if e.graph.is_empty() { format!("-{}", e.name) } else { e.name.clone() }).collect::<Vec<_>>().join(", "));
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_routines_then(c.id, edits, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_routines: {e}"))
    }

    fn cursor(&self, actor: u32) -> u64 {
        self.conn.db.mind_cursor().actor().find(&actor).map(|c| c.upto).unwrap_or(0)
    }

    /// This character's experiences in the hot window, oldest first.
    /// A step or act that failed at a thing named by id (not in sight where the body was, or
    /// bare) weakens what the mind remembered of it before it next thinks, so recall stops
    /// presenting it as sure (docs/TRIALS.md, "A phantom map"). Returns the ids whose memories
    /// were weakened, for the feedback line.
    async fn weaken_missed(&self, actor: u32) -> Vec<u64> {
        let Some(store) = &self.store else { return Vec::new() };
        let known = self.actors.lock().unwrap().entry(actor).or_default().missed_upto;
        let from = match known {
            Some(upto) => upto,
            // After a restart: past the last failure that weakened anything here.
            None => match store.weakened_upto(actor).await {
                Ok(upto) => upto,
                Err(e) => {
                    log::warn!("#{actor}: where failures were last read is unknown ({e:#}); reading from now");
                    self.experiences(actor).last().map_or(0, |e| e.id)
                }
            },
        };
        let mut ids: Vec<(u64, u64)> = Vec::new();
        let mut upto = from;
        for e in self.experiences(actor).into_iter().filter(|e| e.id > from) {
            upto = upto.max(e.id);
            if let Some(id) = (e.kind == "act").then(|| memory::failed_at_thing(&e.text)).flatten() {
                // A person or animal out of sight has not gone anywhere a memory should doubt:
                // only things (structures, resources) are weakened. An id shared by a creature
                // and a thing is left alone.
                if u32::try_from(id).map_or(false, |c| self.conn.db.character().id().find(&c).is_some()) {
                    continue;
                }
                if !ids.iter().any(|(i, _)| *i == id) {
                    ids.push((id, e.id));
                }
            }
        }
        self.actors.lock().unwrap().entry(actor).or_default().missed_upto = Some(upto);
        let mut weakened = Vec::new();
        for (id, exp) in ids {
            match store.weaken(actor, id, MISSED_WEAKEN, &format!("exp:{exp}"), llm::now_ms()).await {
                Ok(n) if n > 0 => {
                    log::info!("#{actor}: {n} memories of #{id} weakened (failed at it, experience {exp})");
                    weakened.push(id);
                }
                Ok(_) => {}
                Err(e) => log::warn!("#{actor}: weakening memories of #{id}: {e:#}"),
            }
        }
        weakened
    }

    fn experiences(&self, actor: u32) -> Vec<Experience> {
        let mut v: Vec<Experience> = self.conn.db.experience().iter().filter(|e| e.observer == actor).collect();
        v.sort_by_key(|e| e.id);
        v
    }

    /// Experience text with the ids of the people involved, so the mind anchors correctly.
    fn exp_line(&self, e: &Experience, fmt: &dyn Fn(u64) -> String, with_id: bool) -> String {
        let mut who = Vec::new();
        for id in [e.subject, e.object] {
            if id != 0 && id != e.observer {
                if let Some(c) = self.conn.db.character().id().find(&id) {
                    if c.kind == "person" && !who.iter().any(|w: &String| w.ends_with(&format!("#{id}"))) {
                        // A name only where the authority gave it (the character knows it):
                        // otherwise the person stays as they were perceived, with an id to anchor.
                        let label = if e.text.contains(&c.name) { c.name } else { "someone".into() };
                        who.push(format!("{label}=#{id}"));
                    }
                }
            }
        }
        let tag = if who.is_empty() { String::new() } else { format!(" {{{}}}", who.join(", ")) };
        if with_id {
            format!("[{}] {} {}{tag}", e.id, fmt(e.at_ms), e.text)
        } else {
            format!("[{}] {}{tag}", fmt(e.at_ms), e.text)
        }
    }

    fn anchors(&self, e: &Experience) -> Vec<String> {
        let mut out = Vec::new();
        for id in [e.subject, e.object] {
            if id == 0 || id == e.observer {
                continue;
            }
            if let Some(c) = self.conn.db.character().id().find(&id) {
                out.push(if c.kind == "person" { format!("person:{id}") } else { format!("kind:{}", c.kind) });
            }
        }
        out.extend(recall::techniques_in(&e.text).into_iter().map(|t| format!("know:{t}")));
        out
    }

    // ---- bootstrap -------------------------------------------------------------

    pub async fn bootstrap(self: &Arc<Self>) -> Result<()> {
        // Identities that need a model call (residents with only a background) are made
        // concurrently, bounded by the shared LLM semaphore.
        let mut pending = Vec::new();
        for c in self.mine() {
            if let Some(store) = &self.store {
                store.ensure_self(c.id, &c.name).await?;
            }
            if self.conn.db.persona().id().find(&c.id).is_none() {
                if self.is_woken(c.id) {
                    // Its mind is made from its authored sheet or the world's facts, and its ring
                    // (woken.rs, below).
                    continue;
                }
                match self.origin(&c) {
                    // An authored sheet is installed as written (no model call); a background
                    // takes a model call. Both run concurrently with the rest.
                    o @ (Origin::Sheet | Origin::Background) => {
                        let me = self.clone();
                        let c = c.clone();
                        pending.push(tokio::spawn(async move {
                            if let Err(e) = me.first_identity(&c, o).await {
                                log::warn!("{}: no identity ({o:?}) yet: {e:#}", c.name);
                            }
                        }));
                    }
                    o => self.first_identity(&c, o).await?,
                }
            }
        }
        for p in pending {
            let _ = p.await;
        }
        // Re-publish what bodies read from minds (places, relations, judgments), so world state
        // matches the minds after repairs or a restart instead of waiting for each consolidation.
        if self.store.is_some() {
            for c in self.mine() {
                if let Err(e) = self.project(c.id, None, None).await {
                    log::warn!("{}: projection at start failed: {e:#}", c.name);
                }
            }
        }
        for c in self.mine().into_iter().filter(|c| self.is_woken(c.id)) {
            self.clone().awaken(c.id);
        }
        for c in self.mine() {
            let model = match self.llm.species_profile(&c.kind, "think") {
                Some(t) => format!("{} (compiled by {})", self.llm.model_name(&t), self.llm.model_name(&self.llm.species_profile(&c.kind, "compile").unwrap_or_default())),
                None => self.llm.model_name(&self.profile(&c)),
            };
            log::info!("{} the {} (#{}) thinks with {model}; mind cursor at {}", c.name, c.kind, c.id, self.cursor(c.id));
        }
        Ok(())
    }

    /// An animal's starting self: its species nature and a temperament of its own.
    async fn animal_persona(&self, c: &Character) -> Result<()> {
        let Some(sp) = self.species.get(&c.kind) else { return Ok(()) };
        let mut h: u64 = 0xcbf29ce484222325 ^ c.id as u64;
        let mut traits = serde_json::Map::new();
        for (k, [lo, hi]) in &sp.temperament {
            h = (h ^ k.len() as u64).wrapping_mul(0x100000001b3).rotate_left(17);
            let t = (h % 1000) as f32 / 1000.0;
            traits.insert(k.clone(), json!((lo + (hi - lo) * t).round()));
        }
        let traits = self.born_temperament(c.id).and_then(|t| t.as_object().cloned()).unwrap_or(traits);
        let persona = json!({
            "narrative": format!("I am {}, a {}.", c.name, c.kind),
            "values": [], "goals": [],
            "traits": traits,
            "mood": "alert",
        });
        let thought = reference(c.id, "born");
        let now = llm::now_ms();
        if let Some(store) = &self.store {
            let mut patch = memory::Patch::default();
            memory::sugar_into(&json!({"places": [{"name": "home", "x": c.home_x, "y": c.home_y}]}), &mut patch, &[]);
            store.ensure_self(c.id, &c.name).await?;
            store.apply(c.id, &patch, &thought, now).await?;
            store.set_identity(c.id, 1, &persona, "born", &thought, now).await?;
        }
        let p = PersonaIn { narrative: persona["narrative"].as_str().unwrap_or_default().into(), values: Vec::new(), goals: Vec::new(), traits: persona["traits"].to_string(), mood: "alert".into() };
        self.project(c.id, Some(p), None).await
    }

    /// Inborn temperament (trait → 0..100) from the character's genes, if any.
    fn born_temperament(&self, id: u32) -> Option<Value> {
        let g = self.conn.db.genome().id().find(&id)?;
        let genes: living_rules::genes::Genes = serde_json::from_str(&g.genes).ok()?;
        let t = living_rules::genes::temperament(&genes);
        (!t.is_empty()).then(|| json!(t))
    }

    async fn seed_persona(&self, c: &Character) -> Result<()> {
        if c.kind != "person" {
            return self.animal_persona(c).await;
        }
        let Some(p) = self.seed["people"].as_array().and_then(|ps| ps.iter().find(|p| p["name"] == c.name.as_str())) else { return Ok(()) };
        let persona = p["persona"].clone();
        let thought = reference(c.id, "seed");
        let now = llm::now_ms();
        let mut patch = memory::Patch::default();
        let mut sugar = json!({"relations": [], "places": [{"name": "home", "x": c.home_x, "y": c.home_y}]});
        for r in p["relations"].as_array().cloned().unwrap_or_default() {
            let Some(other) = self.conn.db.character().iter().find(|o| o.name == r["name"].as_str().unwrap_or_default()) else { continue };
            patch.nodes.push(memory::NodeOp { key: format!("person:{}", other.id), labels: vec!["Person".into()], name: Some(other.name.clone()), props: Default::default() });
            sugar["relations"].as_array_mut().unwrap().push(json!({"id": other.id, "trust": r["trust"], "affinity": r["affinity"], "label": r["label"], "note": r["note"]}));
        }
        memory::sugar_into(&sugar, &mut patch, &[]);
        if let Some(store) = &self.store {
            store.ensure_self(c.id, &c.name).await?;
            store.apply(c.id, &patch, &thought, now).await?;
            store.set_identity(c.id, 1, &persona, "who I was when this began", &thought, now).await?;
        }
        let persona = PersonaIn {
            narrative: persona["narrative"].as_str().unwrap_or_default().into(),
            values: strings(&persona["values"]),
            goals: strings(&persona["goals"]),
            traits: persona["traits"].to_string(),
            mood: persona["mood"].as_str().unwrap_or_default().into(),
        };
        self.project(c.id, Some(persona), None).await
    }

    /// A seeded resident's starting identity, written by their mind from their background
    /// (town, occupation, household or band history). Afterwards it is ordinary identity.
    async fn background_persona(&self, c: &Character) -> Result<()> {
        let bg: Value = self.conn.db.background().id().find(&c.id).and_then(|b| serde_json::from_str(&b.text).ok()).unwrap_or_default();
        let profile = self.profile(&c);
        let system = prompts::identity_system();
        let knows: Vec<String> = self.conn.db.know_how().iter().filter(|k| k.actor == c.id).map(|k| k.technique).collect();
        let born = self.born_temperament(c.id);
        let user = prompts::identity_user(&c.name, c.id, &knows, &bg, born.as_ref());
        let reply = {
            let _slow = self.slow.acquire().await?;
            self.llm.chat(&profile, self.attention(c.id, None), "consolidate", &c.name, &[Msg { role: "system", content: system }, Msg { role: "user", content: user }]).await?
        };
        let v = llm::parse_json(&reply.content)?;
        let thought = reference(c.id, "background");
        let now = llm::now_ms();
        let known: Vec<u32> = ["household", "companions"].iter().flat_map(|k| bg[*k].as_array().cloned().unwrap_or_default()).filter_map(|p| p["id"].as_u64().map(|i| i as u32)).collect();
        let mut places = vec![json!({"name": "home", "x": c.home_x, "y": c.home_y})];
        if let Some([x, y]) = bg["town_center"].as_array().map(|a| [a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0)]) {
            places.push(json!({"name": format!("{} center", bg["town"].as_str().unwrap_or("town")), "x": x, "y": y}));
        }
        if let Some([x, y]) = bg["camp"].as_array().map(|a| [a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0)]) {
            places.push(json!({"name": "camp", "x": x, "y": y}));
        }
        // Other towns one has heard of since childhood.
        for t in bg["towns_known"].as_array().cloned().unwrap_or_default() {
            if let (Some(name), Some(at)) = (t["name"].as_str(), t["at"].as_array()) {
                places.push(json!({"name": name, "x": at[0].as_f64().unwrap_or(0.0), "y": at[1].as_f64().unwrap_or(0.0)}));
            }
        }
        let relations: Vec<Value> = v["relations"].as_array().cloned().unwrap_or_default().into_iter().filter(|r| living_rules::normalize::reply_id(&r["id"]).map_or(false, |i| known.contains(&(i as u32)))).collect();
        if let Some(store) = &self.store {
            let mut patch = memory::Patch::default();
            for id in &known {
                patch.nodes.push(memory::NodeOp { key: format!("person:{id}"), labels: vec!["Person".into()], name: Some(self.name(*id)), props: Default::default() });
            }
            memory::sugar_into(&json!({"relations": relations, "places": places}), &mut patch, &[]);
            store.ensure_self(c.id, &c.name).await?;
            store.apply(c.id, &patch, &thought, now).await?;
            store.set_identity(c.id, 1, &v, "who I was when this began", &thought, now).await?;
        }
        log::info!("{} (#{}) from background: {}", c.name, c.id, v["narrative"].as_str().unwrap_or_default());
        let persona = PersonaIn {
            narrative: v["narrative"].as_str().unwrap_or_default().into(),
            values: strings(&v["values"]),
            goals: strings(&v["goals"]),
            traits: born.clone().unwrap_or_else(|| v["traits"].clone()).to_string(),
            mood: v["mood"].as_str().unwrap_or("settled").into(),
        };
        let t = ThoughtIn { kind: "consolidate".into(), summary: "Who I am, from where I come from.".into(), detail: v.to_string(), latency_ms: reply.latency_ms, tokens: reply.tokens, model: reply.model, reference: thought };
        self.project(c.id, Some(persona), Some(t)).await
    }

    /// The background of a person the world's author wrote, when it carries a sheet with a
    /// narrative (see docs/AUTHORED_WORLDS.md).
    fn authored(&self, c: &Character) -> Option<Value> {
        if c.kind != "person" {
            return None;
        }
        let bg: Value = serde_json::from_str(&self.conn.db.background().id().find(&c.id)?.text).ok()?;
        bg["sheet"]["narrative"].as_str().filter(|n| !n.trim().is_empty())?;
        Some(bg)
    }

    /// An authored person's secret. It is not in any public table: it comes from the seed the
    /// service runs (`LIVING_SEED`), for people whose background carries a sheet.
    fn secret(&self, actor: u32) -> Option<String> {
        let c = self.conn.db.character().id().find(&actor)?;
        self.conn.db.background().id().find(&actor).filter(|b| b.text.contains("\"sheet\":"))?;
        ["towns", "villages"]
            .iter()
            .flat_map(|k| self.seed[*k].as_array().into_iter().flatten())
            .flat_map(|t| t["residents"].as_array().into_iter().flatten())
            .find(|r| r["name"].as_str() == Some(c.name.as_str()))
            .and_then(|r| r["sheet"]["secret"].as_str())
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
    }

    /// An authored person's starting self, installed as written, without a model call: who
    /// they are (identity version 1), how they feel about the people they name, the places
    /// they know, their stances and their memories go into their mind like anything else they
    /// hold, and are theirs to revise from then on. Without a mind store, the projections the
    /// body reads are published directly.
    async fn sheet_persona(&self, c: &Character, bg: &Value) -> Result<()> {
        let sheet = &bg["sheet"];
        let thought = reference(c.id, "sheet");
        let now = llm::now_ms();
        let id_of = |v: &Value| v["id"].as_u64().map(|i| i as u32).filter(|i| *i != c.id);
        let relations: Vec<Value> = sheet["relations"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|r| id_of(r).map(|id| json!({"id": id, "trust": r["trust"], "affinity": r["affinity"], "label": r["label"].as_str().unwrap_or("acquaintance"), "note": r["note"]})))
            .collect();
        let judgments: Vec<Value> = sheet["stances"].as_array().into_iter().flatten().filter(|j| j["key"].is_string()).map(|j| json!({"key": j["key"], "value": j["value"].as_f64().unwrap_or(0.5), "why": j["why"]})).collect();
        let mut places = vec![json!({"name": "home", "x": c.home_x, "y": c.home_y})];
        if let Some([x, y]) = bg["town_center"].as_array().map(|a| [a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0)]) {
            places.push(json!({"name": format!("{} center", bg["town"].as_str().unwrap_or("town")), "x": x, "y": y}));
        }
        // Other towns one has heard of, and the named buildings of one's own settlement.
        for t in bg["towns_known"].as_array().into_iter().chain(bg["places"].as_array()).flatten() {
            if let (Some(name), Some(at)) = (t["name"].as_str(), t["at"].as_array()) {
                places.push(json!({"name": name, "x": at[0].as_f64().unwrap_or(0.0), "y": at[1].as_f64().unwrap_or(0.0)}));
            }
        }
        places.extend(sheet["places"].as_array().into_iter().flatten().filter(|p| p["name"].is_string() && p["x"].is_number() && p["y"].is_number()).cloned());
        let traits = self.born_temperament(c.id).unwrap_or_else(|| if sheet["traits"].is_object() { sheet["traits"].clone() } else { json!({}) });
        let mut identity = json!({
            "narrative": sheet["narrative"],
            "values": strings(&sheet["values"]),
            "goals": strings(&sheet["goals"]),
            "traits": traits,
            "mood": sheet["mood"].as_str().unwrap_or("settled"),
        });
        if let Some(secret) = self.secret(c.id) {
            identity["secret"] = json!(secret);
        }
        identity["written_by"] = json!("author");
        if let Some(store) = &self.store {
            let mut patch = memory::Patch::default();
            // Everyone they know of: household, the people they feel something about and the
            // people in their memories.
            let mut people: Vec<u32> = bg["household"].as_array().into_iter().flatten().filter_map(id_of).collect();
            people.extend(relations.iter().filter_map(id_of));
            people.extend(sheet["memories"].as_array().into_iter().flatten().flat_map(|m| m["about"].as_array().into_iter().flatten().filter_map(id_of)));
            people.sort_unstable();
            people.dedup();
            // Named as this person knows them (`known_as`): someone the author says they know
            // only by sight stays "a stranger" until they are told the name.
            for id in &people {
                patch.nodes.push(memory::NodeOp { key: format!("person:{id}"), labels: vec!["Person".into()], name: Some(self.known_as(c.id, *id)), props: Default::default() });
            }
            // Everything the sheet installs is the author's (`lived_under = ["authored"]`), apart
            // from world facts (`world`), what a model writes (`ai`) and what was lived (`instinct`,
            // `human`).
            patch.lived_under = Some("authored".into());
            // `sugar_into` bounds a model reply's lists; an authored sheet is taken whole.
            for chunk in relations.chunks(12) {
                memory::sugar_into(&json!({"relations": chunk}), &mut patch, &[]);
            }
            for chunk in judgments.chunks(12) {
                memory::sugar_into(&json!({"judgments": chunk}), &mut patch, &[]);
            }
            for chunk in places.chunks(8) {
                memory::sugar_into(&json!({"places": chunk}), &mut patch, &[]);
            }
            // Memories from before, recalled by their words and by the people in them.
            for (i, m) in sheet["memories"].as_array().into_iter().flatten().enumerate() {
                let gist: String = m["gist"].as_str().unwrap_or_default().trim().chars().take(300).collect();
                if gist.is_empty() {
                    continue;
                }
                let involves = m["about"].as_array().into_iter().flatten().filter_map(id_of).map(|id| format!("person:{id}")).collect();
                patch.remember.push(memory::MemoryOp { exp: memory::AUTHORED_MEMORY + i as u64, t: now, gist, salience: m["salience"].as_f64().unwrap_or(0.7).clamp(0.0, 1.0), involves, childhood: false });
            }
            store.ensure_self(c.id, &c.name).await?;
            store.apply(c.id, &patch, &thought, now).await?;
            store.mark_formative(c.id, &thought).await?;
            store.set_identity(c.id, 1, &identity, "who I was when this began", &thought, now).await?;
        }
        log::info!("{} (#{}) as authored: {}", c.name, c.id, identity["narrative"].as_str().unwrap_or_default());
        let persona = PersonaIn {
            narrative: identity["narrative"].as_str().unwrap_or_default().into(),
            values: strings(&identity["values"]),
            goals: strings(&identity["goals"]),
            traits: identity["traits"].to_string(),
            mood: identity["mood"].as_str().unwrap_or_default().into(),
        };
        // Thoughts are public: the detail is the sheet as the background has it, never a secret.
        let mut detail = sheet.clone();
        if let Some(o) = detail.as_object_mut() {
            o.remove("secret");
        }
        let t = ThoughtIn { kind: "consolidate".into(), summary: "Who I am (authored).".into(), detail: detail.to_string(), latency_ms: 0, tokens: 0, model: "authored".into(), reference: thought };
        if self.store.is_some() {
            return self.project(c.id, Some(persona), Some(t)).await;
        }
        let num = |v: &Value| v.as_f64().unwrap_or(0.0) as f32;
        let relations = relations.iter().filter_map(|r| Some(RelationIn { other: id_of(r)?, trust: num(&r["trust"]), affinity: num(&r["affinity"]), label: r["label"].as_str().unwrap_or_default().into(), note: r["note"].as_str().unwrap_or_default().into() })).collect();
        let judgments = judgments.iter().filter_map(|j| Some(JudgmentIn { key: memory::key(j["key"].as_str()?.trim_start_matches("stance:"))?.replace(':', "_"), value: num(&j["value"]), why: j["why"].as_str().unwrap_or_default().into() })).collect();
        let places = places.iter().map(|p| PlaceIn { name: p["name"].as_str().unwrap_or_default().into(), x: num(&p["x"]), y: num(&p["y"]) }).collect();
        self.update(c.id, MindUpdate { persona: Some(persona), relations, beliefs: None, judgments, places, thought: Some(t), replace: false }).await
    }

    /// Where a character's first identity comes from (see [`Origin::of`]).
    fn origin(&self, c: &Character) -> Origin {
        let seeded = self.seed["people"].as_array().is_some_and(|ps| ps.iter().any(|p| p["name"] == c.name.as_str()));
        Origin::of(c.kind == "person", self.authored(c).is_some(), self.conn.db.background().id().find(&c.id).is_some(), c.stage, c.parent_a != 0, seeded)
    }

    async fn first_identity(&self, c: &Character, origin: Origin) -> Result<()> {
        match origin {
            Origin::Sheet => match self.authored(c) {
                Some(bg) => self.sheet_persona(c, &bg).await,
                None => Ok(()),
            },
            Origin::Birth => self.birth_persona(c).await,
            Origin::Background => self.background_persona(c).await,
            Origin::Seed => self.seed_persona(c).await,
        }
    }

    /// A newborn's starting identity: its own temperament, raised by its parents.
    async fn birth_persona(&self, c: &Character) -> Result<()> {
        if c.kind != "person" {
            return self.animal_persona(c).await;
        }
        let parent = |id: u32| {
            let name = self.name(id);
            let p = self.conn.db.persona().id().find(&id).map(|p| format!("{} Values: {}. Traits: {}", p.narrative, p.values.join("; "), p.traits)).unwrap_or_default();
            (name, p)
        };
        let (an, ap) = parent(c.parent_a);
        let (bn, bp) = parent(c.parent_b);
        let profile = self.profile(&c);
        let system = prompts::birth_identity_system();
        let born = self.born_temperament(c.id);
        let user = prompts::birth_identity_user(&c.name, c.id, [(&an, c.parent_a, &ap), (&bn, c.parent_b, &bp)], born.as_ref());
        let _slow = self.slow.acquire().await?;
        let reply = self.llm.chat(&profile, self.attention(c.id, None), "consolidate", &c.name, &[Msg { role: "system", content: system }, Msg { role: "user", content: user }]).await?;
        let v = llm::parse_json(&reply.content)?;
        let thought = reference(c.id, "birth");
        let now = llm::now_ms();
        let parents: Vec<(u32, String)> = [(c.parent_a, an.clone()), (c.parent_b, bn.clone())].into_iter().filter(|(id, _)| *id != 0).collect();
        if let Some(store) = &self.store {
            let mut patch = memory::Patch::default();
            for (id, name) in &parents {
                let key = format!("person:{id}");
                patch.nodes.push(memory::NodeOp { key: key.clone(), labels: vec!["Person".into(), "Parent".into()], name: Some(name.clone()), props: Default::default() });
                patch.edges.push(memory::EdgeOp { from: "self".into(), rel: "CHILD_OF".into(), to: key, confidence: 1.0, because: Vec::new(), props: Default::default(), firsthand: false, sources: Vec::new() });
            }
            let sugar = json!({
                "relations": parents.iter().map(|(id, _)| json!({"id": id, "trust": 70, "affinity": 80, "label": "parent"})).collect::<Vec<_>>(),
                "places": [{"name": "home", "x": c.home_x, "y": c.home_y}]
            });
            memory::sugar_into(&sugar, &mut patch, &[]);
            store.ensure_self(c.id, &c.name).await?;
            store.apply(c.id, &patch, &thought, now).await?;
            store.set_identity(c.id, 1, &v, "born", &thought, now).await?;
        }
        log::info!("{} was born to {an} and {bn}: {}", c.name, v["narrative"].as_str().unwrap_or_default());
        let persona = PersonaIn {
            narrative: v["narrative"].as_str().unwrap_or_default().into(),
            values: strings(&v["values"]),
            goals: strings(&v["goals"]),
            traits: born.clone().unwrap_or_else(|| v["traits"].clone()).to_string(),
            mood: v["mood"].as_str().unwrap_or("curious").into(),
        };
        let t = ThoughtIn { kind: "consolidate".into(), summary: format!("Born to {an} and {bn}."), detail: v.to_string(), latency_ms: reply.latency_ms, tokens: reply.tokens, model: reply.model, reference: thought };
        self.project(c.id, Some(persona), Some(t)).await
    }

    /// Recompute what the body reads from the mind (relations, judgments, places and the
    /// observer's belief summary) and publish it with an optional identity and thought.
    async fn project(&self, actor: u32, persona: Option<PersonaIn>, thought: Option<ThoughtIn>) -> Result<()> {
        let Some(store) = &self.store else {
            return self.update(actor, MindUpdate { persona, relations: Vec::new(), beliefs: None, judgments: Vec::new(), places: Vec::new(), thought, replace: false }).await;
        };
        let fmt = self.fmt_time();
        let p = store.projection(actor).await?;
        let facts = store.around(actor, &[], 30).await.unwrap_or_default();
        let relations = p
            .feelings
            .into_iter()
            .filter(|(id, ..)| *id != actor && self.conn.db.character().id().find(id).map_or(false, |c| c.kind == "person"))
            .map(|(other, trust, affinity, label, note)| RelationIn { other, trust: trust as f32, affinity: affinity as f32, label, note })
            .collect();
        let judgments = p.judgments.into_iter().map(|(key, value, why)| JudgmentIn { key, value: value as f32, why }).collect();
        let places = p.places.into_iter().map(|(name, x, y)| PlaceIn { name, x: x as f32, y: y as f32 }).collect();
        let beliefs = Some(facts.iter().map(|f| BeliefIn { about: format!("{} → {}", f.a, f.b), text: memory::render(f, &fmt), confidence: f.confidence as f32 }).collect());
        self.update(actor, MindUpdate { persona, relations, beliefs, judgments, places, thought, replace: true }).await
    }

    // ---- reducer calls -----------------------------------------------------------

    async fn update(&self, actor: u32, u: MindUpdate) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_update_then(actor, u, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_update: {e}"))
    }

    async fn consolidated(&self, actor: u32, upto: u64) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_consolidated_then(actor, upto, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_consolidated: {e}"))
    }

    #[allow(clippy::too_many_arguments)]
    async fn install(&self, actor: u32, graph: String, plan: String, say: String, to: u32, seen: u64, t: ThoughtIn) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_install_then(actor, graph, plan, say, to, seen, t, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_install: {e}"))
    }

    /// Hand deliberate acts to the authority (carried out once each, in order).
    pub(crate) async fn act(&self, actor: u32, acts: Vec<String>, source: &str) -> Result<()> {
        if acts.is_empty() {
            return Ok(());
        }
        log::info!("{} acts ({source}): {}", self.name(actor), acts_text(&acts));
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_act_then(actor, acts, source.to_string(), move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_act: {e}"))
    }

    async fn skip(&self, actor: u32, seen: u64, t: ThoughtIn) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_skip_then(actor, seen, t, move |_, r| {
            let _ = tx.send(flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_skip: {e}"))
    }

    // ---- event loop -------------------------------------------------------------

    pub async fn run(self: Arc<Self>, mut rx: tokio::sync::mpsc::UnboundedReceiver<Event>) -> Result<()> {
        let mut tick = tokio::time::interval(Duration::from_millis(2000));
        if self.lod.on {
            log::info!("level of detail on: {:?}", self.lod);
        }
        for d in self.conn.db.my_deliberations().iter() {
            let actor = d.actor;
            if self.lod.on {
                self.pending.lock().unwrap().insert(actor, lod::PendingRequest::new(d));
            }
            self.clone().schedule(actor);
        }
        log::info!("reorganization: {:?}", self.sleep_cfg);
        tokio::spawn(self.clone().collect_left_batches());
        if self.animal_cfg.any() {
            log::info!("animal minds: {:?}", self.animal_cfg);
        }
        if let Some(j) = &self.jev {
            log::info!("judgments on: {} via {} ({})", j.file.judgments.keys().cloned().collect::<Vec<_>>().join(", "), j.file.provider.url, j.file.provider.model);
        }
        if let Some(g) = &self.rethink {
            log::info!("rethink gate on: {:?} (deliberate at p >= {}, hold at most {} s)", g.mode, g.threshold(), g.file.max_hold_s);
        }
        if self.lived_cfg.on {
            log::info!("player memory on: {:?}", self.lived_cfg);
            for e in self.conn.db.experience().iter().filter(|e| e.controller != self.me) {
                self.lived_add(e);
            }
        }
        self.refresh_rules();
        loop {
            tokio::select! {
                ev = rx.recv() => match ev {
                    Some(Event::Speech(e)) => self.clone().on_speech(e),
                    Some(Event::Deliberation(actor)) => self.clone().schedule(actor),
                    Some(Event::Pending(d)) => {
                        let mut p = self.pending.lock().unwrap();
                        if let Some(request) = p.get_mut(&d.actor) {
                            request.refresh(d);
                        } else {
                            p.insert(d.actor, lod::PendingRequest::new(d));
                        }
                    }
                    Some(Event::PendingGone(d)) => {
                        let mut p = self.pending.lock().unwrap();
                        if p.get(&d.actor).is_some_and(|request| request.row == d) {
                            if let Some(request) = p.remove(&d.actor) {
                                request.changed.notify_one();
                            }
                        }
                    }
                    Some(Event::Contact(actor)) => {
                        {
                            let mut actors = self.actors.lock().unwrap();
                            if self.admit(actor, &mut actors) {
                                actors.entry(actor).or_default().onstage_until = Some(Instant::now() + self.lod.sticky);
                            }
                        }
                        if let Some(request) = self.pending.lock().unwrap().get(&actor) {
                            request.changed.notify_one();
                        }
                    }
                    Some(Event::Lived(e)) => self.lived_add(e),
                    Some(Event::Percept(e)) => self.rethink_percept(&e),
                    Some(Event::Woken(id)) => self.clone().awaken(id),
                    None => return Err(anyhow!("event channel closed")),
                },
                _ = tick.tick() => {
                    self.refresh_rules();
                    self.clone().check_consolidation();
                    self.clone().check_sleep();
                    self.clone().check_judgments();
                    self.clone().check_rethink();
                    self.clone().check_lived();
                    let this = self.clone();
                    tokio::spawn(async move { this.journal_cap_reports().await });
                }
            }
        }
    }

    /// Keep the skills' takes and gives in prompts in step with the world's rule script.
    fn refresh_rules(&self) {
        if let Some(s) = self.conn.db.script().iter().find(|s| s.name == "skills") {
            prompts::set_rules(s.revision, &s.source);
        }
    }

    fn schedule(self: Arc<Self>, actor: u32) {
        if !self.allowed(actor) || self.conn.db.character().id().find(&actor).map_or(false, |c| c.stage == 0) {
            return;
        }
        {
            let mut a = self.actors.lock().unwrap();
            let m = a.entry(actor).or_default();
            if m.deliberating {
                m.again = true;
                return;
            }
            m.deliberating = true;
        }
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(400)).await;
            // A character the minds just took over thinks with its own past: what its person
            // lived is internalized first (bounded by `LIVING_TAKEOVER_WAIT_S`).
            let started = Instant::now();
            while self.lived_waiting(actor) && started.elapsed() < self.lived_cfg.takeover_wait {
                tokio::time::sleep(Duration::from_millis(500)).await;
            }
            // A resident just woken into a mind thinks once its mind is made: who it is from the
            // world's facts, and what it perceived before (woken.rs; the `woken_stage("wait_s")` law).
            if self.is_woken(actor) {
                self.clone().awaken(actor);
                let wait = Duration::from_secs_f64(prompts::woken_laws().wait_s);
                let started = Instant::now();
                while self.woken_waiting(actor) && started.elapsed() < wait {
                    tokio::time::sleep(Duration::from_millis(500)).await;
                }
            }
            let mut seen = 0u64;
            loop {
                let pending = if self.lod.on {
                    self.pending.lock().unwrap().get(&actor).map(|p| &p.row).filter(|d| d.updated_ms > seen).cloned()
                } else {
                    self.conn.db.my_deliberations().iter().find(|d| d.actor == actor && d.updated_ms > seen)
                };
                let Some(d) = pending else { break };
                // Off stage, routine reasons wait (and gather) until the mind is due again.
                let wait = self.lod_wait(&d);
                if self.lod.on {
                    self.actors.lock().unwrap().entry(actor).or_default().deferring = wait.is_some();
                    let decision = {
                        let mut pending = self.pending.lock().unwrap();
                        let Some(request) = pending.get_mut(&actor) else { continue };
                        if request.row != d {
                            continue;
                        }
                        (request.decide(wait), request.changed.clone())
                    };
                    if let (Some(until), changed) = decision {
                        tokio::select! {
                            _ = tokio::time::sleep_until(until.into()) => {},
                            _ = changed.notified() => {},
                        }
                        continue;
                    }
                }
                seen = d.updated_ms;
                // The rethink gate may hold a non-urgent request: it stays pending and gathers
                // what comes next, and each new reason asks again (rethink.rs).
                if !self.rethink_gate(&d).await {
                    self.actors.lock().unwrap().entry(actor).or_default().deferring = true;
                    if let Some(request) = self.pending.lock().unwrap().get_mut(&actor) {
                        request.state = lod::PendingState::Ready;
                    }
                    continue;
                }
                match self.deliberate(&d).await {
                    Ok(()) => {
                        self.actors.lock().unwrap().entry(actor).or_default().model_failures = 0;
                        self.rethink_thought(actor, d.updated_ms);
                    }
                    Err(e) if e.is::<ModelUnavailable>() => {
                        // Its model could not be reached: the request and its reasons stay pending
                        // (merging what comes next), and it is tried again after a backoff. Meanwhile
                        // the character takes conversation turns, as while held.
                        let failures = {
                            let mut a = self.actors.lock().unwrap();
                            let m = a.entry(actor).or_default();
                            m.model_failures += 1;
                            m.deferring = true;
                            m.model_failures
                        };
                        let wait = model_backoff(failures);
                        log::warn!("deliberation for {} could not reach its model ({failures}x); the request waits {:.0} s: {e:#}", self.name(actor), wait.as_secs_f64());
                        if failures == 1 {
                            let t = ThoughtIn { kind: "error".into(), summary: format!("could not reach the model; the request waits: {e:#}").chars().take(600).collect(), detail: String::new(), latency_ms: 0, tokens: 0, model: String::new(), reference: reference(actor, "deliberate") };
                            if let Err(e) = self.update(actor, MindUpdate { persona: None, relations: Vec::new(), beliefs: None, judgments: Vec::new(), places: Vec::new(), thought: Some(t), replace: false }).await {
                                log::warn!("{}: the failure was not recorded: {e:#}", self.name(actor));
                            }
                        }
                        tokio::time::sleep(wait).await;
                        if self.lod.on {
                            if let Some(request) = self.pending.lock().unwrap().get_mut(&actor) {
                                request.state = lod::PendingState::Ready;
                            }
                        }
                        self.actors.lock().unwrap().entry(actor).or_default().deferring = false;
                        // The same request (or what it has become) is due again.
                        seen = 0;
                        continue;
                    }
                    Err(e) => log::warn!("deliberation for {} failed: {e:#}", self.name(actor)),
                }
                if self.lod.on {
                    self.actors.lock().unwrap().entry(actor).or_default().last_deliberated = Some(Instant::now());
                    if let Some(request) = self.pending.lock().unwrap().get_mut(&actor) {
                        request.state = lod::PendingState::Ready;
                    }
                }
                let again = std::mem::take(&mut self.actors.lock().unwrap().entry(actor).or_default().again);
                if !again {
                    tokio::time::sleep(Duration::from_millis(300)).await;
                }
            }
            let held = self.rethink_holding(actor);
            let mut a = self.actors.lock().unwrap();
            let m = a.entry(actor).or_default();
            m.deliberating = false;
            m.deferring = held;
        });
    }

    /// A character controlled by a human (not by a mind service; benchmark characters on
    /// instinct also count).
    fn is_player(&self, id: u32) -> bool {
        self.conn.db.character().id().find(&id).is_some_and(|c| lod::is_player(&c, self.me))
    }

    fn deliberation_lane(&self, d: &Deliberation) -> Lane {
        let player_act = self.conn.db.experience().iter().filter(|e| e.observer == d.actor).any(|e| {
            if e.at_ms < d.requested_ms.saturating_sub(1000) || e.at_ms > d.updated_ms {
                return false;
            }
            [e.subject, e.object].into_iter().filter(|id| self.is_player(*id)).any(|id| {
                (!e.text.is_empty() && d.reason.contains(&e.text))
                    || d.reason.contains(&format!("(#{id})"))
                    || (e.kind == "combat" && self.conn.db.character().id().find(&id)
                        .is_some_and(|c| d.reason.contains(&format!("The fight with {}:", c.name))))
            })
        });
        Lane::deliberation(&d.reason, player_act)
    }

    /// Whether a person is on stage (see lod.rs): always, with the level of detail off; while a
    /// human player is in the scene of a pending request (`scene`) or was recently part of
    /// what they experienced.
    fn onstage(&self, actor: u32, scene: Option<&str>) -> bool {
        !self.lod.on || self.watched(actor, scene)
    }

    /// The stage of attention a model mix chooses by (`llm::Choice::Staged`). It is tracked
    /// whenever the level of detail is on or a mix is staged; otherwise everyone is on stage.
    fn attention(&self, actor: u32, scene: Option<&str>) -> llm::Attention {
        if !(self.lod.on || self.llm.staged()) || self.watched(actor, scene) {
            llm::Attention::OnStage
        } else {
            llm::Attention::OffStage
        }
    }

    /// Whether a human player is in the scene (`scene`) or was recently part of what the
    /// character lived (`onstage_until`, kept by `Event::Contact`).
    fn watched(&self, actor: u32, scene: Option<&str>) -> bool {
        let now = Instant::now();
        if self.actors.lock().unwrap().get(&actor).and_then(|m| m.onstage_until).is_some_and(|t| t > now) {
            return true;
        }
        let seen = scene.and_then(|s| serde_json::from_str::<Value>(s).ok()).and_then(|v| v["creatures"].as_array().map(|cs| cs.iter().filter_map(|c| c["id"].as_u64()).any(|id| self.is_player(id as u32)))).unwrap_or(false);
        if !seen {
            return false;
        }
        // A woken resident goes on stage only within its settlement's cap (woken.rs).
        let mut actors = self.actors.lock().unwrap();
        if !self.admit(actor, &mut actors) {
            return false;
        }
        actors.entry(actor).or_default().onstage_until = Some(now + self.lod.sticky);
        true
    }

    /// How much longer a pending deliberation waits under the level of detail (people, and
    /// animals, which the authority already lets think only near a person).
    fn lod_wait(&self, d: &Deliberation) -> Option<Duration> {
        if !self.lod.on {
            return None;
        }
        let last = self.actors.lock().unwrap().get(&d.actor).and_then(|m| m.last_deliberated);
        let onstage = self.onstage(d.actor, Some(&d.scene));
        self.lod.wait(&d.reason, onstage, last)
    }

    fn consolidation_threshold(&self, actor: u32) -> f32 {
        if let Some(c) = self.conn.db.character().id().find(&actor).filter(|c| c.kind != "person") {
            return self.species.get(&c.kind).map(|s| s.cognition.consolidate_threshold).unwrap_or(3.0);
        }
        let intro = self
            .conn
            .db
            .persona()
            .id()
            .find(&actor)
            .and_then(|p| serde_json::from_str::<Value>(&p.traits).ok())
            .and_then(|t| t["introspection"].as_f64())
            .unwrap_or(50.0) as f32;
        3.2 * (1.35 - intro / 100.0)
    }

    /// Start consolidation for characters whose unintegrated experiences matter enough.
    fn check_consolidation(self: Arc<Self>) {
        // One pass over the experience inbox for everyone (a scan per character would cost
        // characters × experiences every two seconds).
        // Only what a character lived under this service's minds: rows its person lived while
        // playing it are internalized as theirs (lived.rs).
        let mut inbox: HashMap<u32, Vec<Experience>> = HashMap::new();
        for e in self.conn.db.experience().iter().filter(|e| e.controller == self.me) {
            inbox.entry(e.observer).or_default().push(e);
        }
        for c in self.mine() {
            // Off stage, a person integrates experience less often (see lod.rs).
            let offstage = self.lod.on && c.kind == "person" && !self.onstage(c.id, None);
            let cursor = self.cursor(c.id);
            let pending: Vec<Experience> = inbox.remove(&c.id).unwrap_or_default().into_iter().filter(|e| e.id > cursor).collect();
            let meaningful: Vec<&Experience> = pending.iter().filter(|e| e.salience >= 0.2).collect();
            let salience: f32 = meaningful.iter().map(|e| e.salience).sum();
            let due = {
                let mut a = self.actors.lock().unwrap();
                let m = a.entry(c.id).or_default();
                let stale = m.last_consolidated.map_or(true, |t| t.elapsed() > Duration::from_secs(240));
                let min_gap = if offstage { self.lod.consolidate.as_secs() } else { self.species.get(&c.kind).map(|s| s.cognition.consolidate_min_s).unwrap_or(90) };
                let rested = m.last_consolidated.map_or(true, |t| t.elapsed() > Duration::from_secs(min_gap));
                // The minimum gap holds even for a large backlog (it is then integrated in one
                // batch): in a crisis, forcing a consolidation per 120 experiences re-summarized
                // the same events every ~40 s and ratcheted stances toward absolutes.
                let wanted = rested && (salience >= self.consolidation_threshold(c.id) || meaningful.len() >= 30 || (stale && meaningful.len() >= 4) || pending.len() >= 120);
                let allowed = !m.consolidating && m.retry_after.map_or(true, |t| Instant::now() >= t);
                // Under the timer (`LIVING_REORGANIZE=timer`), a rested mind with nothing salient
                // to integrate reorganizes; otherwise that happens at night (sleep.rs).
                let timer = self.sleep_cfg.mode == sleep::Mode::Timer;
                let sleepy = timer && rested && (m.since_sleep >= 6 || (m.since_sleep >= 2 && m.last_sleep.map_or(true, |t| t.elapsed() > Duration::from_secs(20 * 60))));
                if allowed && (wanted || sleepy) {
                    m.consolidating = true;
                    Some(!wanted)
                } else {
                    None
                }
            };
            let Some(sleep) = due else { continue };
            let this = self.clone();
            let actor = c.id;
            tokio::spawn(async move {
                if sleep {
                    let r = this.reorganize(actor).await;
                    return this.slept(actor, r, false);
                }
                let r = this.consolidate(actor).await;
                if r.is_ok() {
                    this.actors.lock().unwrap().entry(actor).or_default().since_sleep += 1;
                }
                let mut a = this.actors.lock().unwrap();
                let m = a.entry(actor).or_default();
                m.consolidating = false;
                match r {
                    Ok(()) => {
                        m.failures = 0;
                        m.retry_after = None;
                        m.last_consolidated = Some(Instant::now());
                    }
                    Err(e) => {
                        m.failures += 1;
                        m.retry_after = Some(Instant::now() + Duration::from_secs(20 * m.failures as u64));
                        log::warn!("consolidation for {} failed ({}x): {e:#}", this.name(actor), m.failures);
                    }
                }
            });
        }
    }

    /// The stances and places a decision named become part of the mind, whether it changes
    /// the graph or carries on.
    async fn decided_stances(&self, actor: u32, v: &Value, thought_ref: &str) -> Result<()> {
        let mut patch = memory::Patch::default();
        memory::sugar_into(&json!({"judgments": v["judgments"], "places": v["places"]}), &mut patch, &[]);
        if patch.nodes.is_empty() && patch.edges.is_empty() {
            return Ok(());
        }
        if let Some(store) = &self.store {
            store.apply(actor, &patch, thought_ref, llm::now_ms()).await?;
        }
        self.project(actor, None, None).await
    }

    // ---- shared context -----------------------------------------------------------

    fn persona_text(&self, actor: u32) -> String {
        match self.conn.db.persona().id().find(&actor) {
            Some(p) => {
                let mut knows: Vec<String> = self.conn.db.know_how().iter().filter(|k| k.actor == actor).map(|k| k.technique).collect();
                knows.sort();
                let know = if knows.is_empty() { "nothing yet".to_string() } else { knows.join(", ") };
                let belong = match self.conn.db.membership().member().find(&actor) {
                    Some(m) => {
                        let name = self.conn.db.community().id().find(&m.community).map(|c| c.name).unwrap_or_default();
                        let others: Vec<u32> = self.conn.db.membership().iter().filter(|x| x.community == m.community && x.member != actor).map(|x| x.member).collect();
                        let felt: std::collections::HashSet<u32> = self.conn.db.relation().iter().filter(|r| r.actor == actor).map(|r| r.other).collect();
                        let known: Vec<String> = others.iter().filter(|id| felt.contains(id)).map(|id| format!("{} (#{id})", self.known_as(actor, *id))).collect();
                        belonging(&name, others.len(), &known)
                    }
                    None => "\nYou belong to no community.".into(),
                };
                let secret = self.secret(actor).map(|s| format!("\nKnown only to you: {s}")).unwrap_or_default();
                format!("{}{secret}\nValues: {}\nGoals: {}\nTraits: {}\nMood: {}\nYou know how to: {know}{belong}", p.narrative, p.values.join("; "), p.goals.join("; "), p.traits, p.mood)
            }
            None => "(no persona yet)".into(),
        }
    }

    fn relations(&self, actor: u32) -> Vec<String> {
        let mut rs: Vec<Relation> = self.conn.db.relation().iter().filter(|r| r.actor == actor).collect();
        rs.sort_by(|a, b| (b.trust.abs() + b.affinity.abs()).total_cmp(&(a.trust.abs() + a.affinity.abs())));
        rs.into_iter()
            .take(16)
            .map(|r| {
                format!(
                    "{} (#{}): {}, trust {:.0}, affinity {:.0}{}",
                    self.known_as(actor, r.other),
                    r.other,
                    r.label,
                    r.trust,
                    r.affinity,
                    if r.note.is_empty() { String::new() } else { format!(" — {}", r.note) }
                )
            })
            .collect()
    }

    fn judgments(&self, actor: u32) -> Vec<String> {
        self.conn.db.judgment().iter().filter(|j| j.actor == actor).map(|j| format!("{} = {:.2} ({})", j.key, j.value, j.why)).collect()
    }

    fn places(&self, actor: u32) -> Vec<String> {
        self.conn.db.place().iter().filter(|p| p.actor == actor).map(|p| format!("\"{}\" at [{:.0}, {:.0}]", p.name, p.x, p.y)).collect()
    }

    // ---- deliberation ------------------------------------------------------------

    async fn deliberate(&self, d: &Deliberation) -> Result<()> {
        let actor = d.actor;
        let lane = self.deliberation_lane(d);
        let Some(c) = self.conn.db.character().id().find(&actor) else { return Ok(()) };
        if !c.alive {
            return Ok(());
        }
        if self.conn.db.persona().id().find(&actor).is_none() {
            if let Some(store) = &self.store {
                store.ensure_self(c.id, &c.name).await?;
            }
            // A woken resident's identity is made by its waking (woken.rs), from the world's facts.
            if !self.is_woken(actor) {
                self.first_identity(&c, self.origin(&c)).await?;
            }
            for _ in 0..20 {
                if self.conn.db.persona().id().find(&actor).is_some() {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        }
        if c.kind != "person" {
            if self.animal_cfg.any() {
                return self.deliberate_animal_cheap(d, &c, lane).await;
            }
            return self.deliberate_animal(d, &c, lane).await;
        }
        let profile = self.profile(&c);
        let scene: Value = serde_json::from_str(&d.scene).unwrap_or(json!({}));
        let at = self.attention(actor, Some(&d.scene));
        self.felt.lock().unwrap().insert(actor, (Instant::now(), scene["you"].clone()));
        let missed = self.weaken_missed(actor).await;
        // What this moment brings to mind (see recall.rs).
        let recalled = self.recall_for(actor, &self.scene_cues(actor, &scene, &d.reason), 18, 5, "decide").await;
        let (mind, memories) = (recalled.mind, recalled.memories);
        let brain = self.conn.db.brain().id().find(&actor);
        let outline = brain.as_ref().and_then(|b| living_rules::graph::parse(&b.graph).ok()).map(|g| living_rules::graph::outline(&g.root)).unwrap_or_default();
        let plan = brain.as_ref().map(|b| b.plan.clone()).unwrap_or_default();
        let fmt = self.fmt_time();
        let experiences: Vec<String> = {
            let all = self.experiences(actor);
            let n = all.len();
            all.iter().skip(n.saturating_sub(16)).map(|e| self.exp_line(e, &fmt, false)).collect()
        };
        let pruned = self.actors.lock().unwrap().entry(actor).or_default().pruned.clone();
        let mut reason = d.reason.clone();
        if !pruned.is_empty() {
            reason.push_str(&format!("\n(Note: parts of your previous graph were invalid and dropped: {})", pruned.join("; ")));
        }
        for id in &missed {
            reason.push_str(&format!("\n(You went by what you remembered of #{id}, and it was not there to act on where you were; that memory feels less sure now.)"));
        }
        let ctx = prompts::Ctx {
            name: &c.name,
            clock: fmt(llm::now_ms()),
            body: self.body_text(actor),
            persona: self.persona_text(actor),
            relations: self.relations(actor),
            mind,
            memories,
            judgments: recalled.judgments,
            places: self.places(actor),
            experiences,
            dealings: self.dealings(actor),
        };
        let repertoire = self.repertoire_text(actor);
        // Think first, as the person and without the grammar; then compile the decision.
        let habits: String = self.routine_digest(actor).into_iter().map(|(_, head)| format!("- {head}\n")).collect();
        let think_msgs = vec![
            Msg { role: "system", content: prompts::think_system() },
            Msg { role: "user", content: prompts::think_user(&ctx, &d.scene, &plan, &reason, &habits) },
        ];
        let mut decision = Value::Null;
        let (mut think_latency, mut think_tokens) = (0u32, 0u32);
        for p in [profile.clone(), self.llm.default_profile()] {
            if let Ok(r) = self.llm.chat_in_lane(&p, at, "think", &c.name, &think_msgs, lane).await {
                think_latency += r.latency_ms;
                think_tokens += r.tokens;
                if let Ok(v) = llm::parse_json(&r.content) {
                    decision = v;
                    break;
                }
            }
        }
        let intend: Vec<String> = decision["intend"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default();
        let decided = format!(
            "{}\nIntentions (in order): {}",
            decision["thought"].as_str().unwrap_or_default(),
            if intend.is_empty() { "(nothing new: carry on)".to_string() } else { intend.join("; ") }
        );
        let system = prompts::deliberate_system();
        let user = prompts::compile_user(&decided, prompts::deliberate_user(&ctx, &d.scene, &outline, &plan, &reason, &repertoire));
        let mut messages = vec![Msg { role: "system", content: system }, Msg { role: "user", content: user }];
        let mut last_err = String::new();
        let mut total_latency = think_latency;
        let mut total_tokens = think_tokens;
        let thought_ref = reference(actor, "deliberate");
        // The decision's own words (thought, speech, stances, places) are kept whatever the compiler says.
        let keep = |raw: &str| -> String {
            match llm::parse_json(raw) {
                Ok(mut v) => {
                    if decision.is_object() {
                        for k in ["thought", "say", "judgments", "places"] {
                            v[k] = decision[k].clone();
                        }
                        if v["plan"].as_str().map_or(true, |p| p.is_empty()) && !intend.is_empty() {
                            v["plan"] = json!(intend.join("; "));
                        }
                    }
                    say_acts_into_speech(&mut v);
                    v.to_string()
                }
                Err(_) => raw.to_string(),
            }
        };
        let mut profile = profile;
        for attempt in 0..3 {
            let reply = match self.llm.chat_in_lane(&profile, at, "deliberate", &c.name, &messages, lane).await {
                Ok(r) => r,
                // The request stays pending: `schedule` tries it again after a backoff.
                Err(e) => return Err(unavailable(e)),
            };
            total_latency += reply.latency_ms;
            total_tokens += reply.tokens;
            let raw = keep(&reply.content);
            // An intention becomes the "current plan" routine, weighed among the desires. Ways
            // change only through the rework skill (an act), not by a reply rewriting them.
            let intended = llm::parse_json(&raw)
                .ok()
                .map(|mut v| {
                    if let Some(o) = v.as_object_mut() {
                        o.remove("routines");
                        o.remove("restructure");
                    }
                    real_time_into_intent(&mut v);
                    v
                })
                .and_then(|v| self.plan_into_desires(actor, v));
            let content = intended.as_ref().map(|v| v.to_string()).unwrap_or_else(|| raw.clone());
            // Routine edits apply whatever else the reply does (they are idempotent upserts).
            if let Ok(v) = llm::parse_json(&content) {
                if let Err(e) = self.apply_routines(&c, &v["routines"]).await {
                    log::warn!("{}: routines not applied: {e:#}", c.name);
                }
            }
            // Only talking: keep the current behavior and just speak.
            if let Ok(v) = llm::parse_json(&content) {
                if v["graph"].is_null() || v["graph"].as_str().map_or(false, |g| g.trim().eq_ignore_ascii_case("keep")) {
                    self.decided_stances(actor, &v, &thought_ref).await?;
                    let (say, to) = match &v["say"] {
                        Value::String(s) => (s.clone(), 0),
                        Value::Object(o) => (o.get("text").and_then(|t| t.as_str()).unwrap_or_default().to_string(), o.get("to").and_then(living_rules::normalize::reply_id).unwrap_or(0) as u32),
                        _ => (String::new(), 0),
                    };
                    // A format placeholder ("text", "your words") is not something to say aloud.
                    let say = if living_rules::normalize::placeholder_words(&say) { String::new() } else { say };
                    let thought = v["thought"].as_str().unwrap_or_default().to_string();
                    let acts = acts_of(&v);
                    let t = ThoughtIn {
                        kind: "deliberate".into(),
                        summary: format!(
                            "{thought} → (carries on){}{}",
                            if acts.is_empty() { String::new() } else { format!(" and acts: {}", acts_text(&acts)) },
                            if say.is_empty() { String::new() } else { format!(" and says “{say}”") }
                        ),
                        detail: json!({"reason": d.reason, "reply": v, "attempts": attempt + 1}).to_string(),
                        latency_ms: total_latency,
                        tokens: total_tokens,
                        model: reply.model.clone(),
                        reference: thought_ref.clone(),
                    };
                    log::info!("{} carries on{}", c.name, if say.is_empty() { String::new() } else { format!(" — says “{say}”") });
                    let (tx, rx) = oneshot::channel();
                    self.conn.reducers.mind_say_then(actor, say, to, d.updated_ms, t, move |_, r| {
                        let _ = tx.send(flatten(r));
                    })?;
                    rx.await?.map_err(|e| anyhow!("mind_say: {e}"))?;
                    return self.act(actor, acts, "deliberate").await;
                }
            }
            // A patch replaces one labeled branch (e.g. combat tactics mid-fight) and keeps the rest.
            let current = self.conn.db.brain().id().find(&actor).and_then(|b| serde_json::from_str::<Value>(&b.graph).ok());
            let parsed = llm::parse_json(&content).and_then(|mut v| {
                if v["patch"].is_object() && (v["graph"].is_null() || v["graph"].is_string()) {
                    let label = v["patch"]["label"].as_str().unwrap_or("combat").to_string();
                    let node = v["patch"]["graph"].clone();
                    v["graph"] = patch_branch(current.clone().unwrap_or(json!({"wait": 3})), &label, node);
                }
                let (g, pruned) = living_rules::graph::from_value_lenient(v["graph"].clone()).map_err(|e| anyhow!(e))?;
                Ok((v, g, pruned))
            });
            match parsed {
                Ok((v, g, pruned)) => {
                    self.actors.lock().unwrap().entry(actor).or_default().pruned = pruned.clone();
                    let (say, to) = match &v["say"] {
                        Value::String(s) => (s.clone(), 0),
                        Value::Object(o) => (o.get("text").and_then(|t| t.as_str()).unwrap_or_default().to_string(), o.get("to").and_then(living_rules::normalize::reply_id).unwrap_or(0) as u32),
                        _ => (String::new(), 0),
                    };
                    // A format placeholder ("text", "your words") is not something to say aloud.
                    let say = if living_rules::normalize::placeholder_words(&say) { String::new() } else { say };
                    let plan = v["plan"].as_str().unwrap_or_default().to_string();
                    let thought = v["thought"].as_str().unwrap_or_default().to_string();
                    self.decided_stances(actor, &v, &thought_ref).await?;
                    let acts = acts_of(&v);
                    let t = ThoughtIn {
                        kind: "deliberate".into(),
                        summary: format!("{thought} → {plan}{}", if acts.is_empty() { String::new() } else { format!(" (acts: {})", acts_text(&acts)) }),
                        detail: json!({"reason": d.reason, "reply": v, "attempts": attempt + 1, "pruned": pruned}).to_string(),
                        latency_ms: total_latency,
                        tokens: total_tokens,
                        model: reply.model.clone(),
                        reference: thought_ref.clone(),
                    };
                    log::info!("{} decided: {plan}{}", c.name, if say.is_empty() { String::new() } else { format!(" — says “{say}”") });
                    self.install(actor, g.to_json(), plan, say, to, d.updated_ms, t).await?;
                    return self.act(actor, acts, "deliberate").await;
                }
                Err(e) => {
                    last_err = format!("{e:#}");
                    // A reply that is not JSON at all is usually a degenerate generation (runs of
                    // whitespace or brackets): retry with the most reliable model, and don't
                    // send the runaway text back.
                    let unusable = llm::parse_json(&reply.content).is_err();
                    if unusable && profile != self.llm.default_profile() {
                        log::warn!("{}: unusable reply from {} ({} chars); retrying with {}", c.name, reply.model, reply.content.len(), self.llm.default_profile());
                        profile = self.llm.default_profile();
                    }
                    messages.push(Msg { role: "assistant", content: reply.content.chars().take(3000).collect() });
                    messages.push(Msg { role: "user", content: format!("That reply was rejected: {last_err}. Return the complete corrected JSON object.") });
                }
            }
        }
        let t = ThoughtIn {
            kind: "error".into(),
            summary: format!("could not decide: {last_err}"),
            detail: String::new(),
            latency_ms: total_latency,
            tokens: total_tokens,
            model: self.llm.model_name(&profile),
            reference: thought_ref,
        };
        self.skip(actor, d.updated_ms, t).await
    }

    /// Animals: a small model feels an impulse; a competent model compiles it into a graph
    /// the body allows. The compiler is told to add nothing the animal does not have.
    async fn deliberate_animal(&self, d: &Deliberation, c: &Character, lane: Lane) -> Result<()> {
        let actor = c.id;
        let Some(sp) = self.species.get(&c.kind).cloned() else { return Ok(()) };
        let think = self.llm.species_profile(&c.kind, "think").unwrap_or_else(|| self.llm.profile_for(actor, &c.name));
        let compile = self.llm.species_profile(&c.kind, "compile").unwrap_or_else(|| self.llm.profile_for(actor, &c.name));
        let at = self.attention(actor, Some(&d.scene));
        let fmt = self.fmt_time();
        let scene: Value = serde_json::from_str(&d.scene).unwrap_or(json!({}));
        let recalled = self.recall_for(actor, &self.scene_cues(actor, &scene, &d.reason), 10, 0, "animal").await;
        let mut mind = recalled.mind;
        mind.extend(recalled.judgments.into_iter().filter(|j| !j.starts_with('(')).map(|j| format!("feels sure: {j}")));
        let experiences: Vec<String> = {
            let all = self.experiences(actor);
            let n = all.len();
            all.iter().skip(n.saturating_sub(8)).map(|e| self.exp_line(e, &fmt, false)).collect()
        };
        let temperament = self.conn.db.persona().id().find(&actor).map(|p| format!("{} (mood: {})", p.traits, p.mood)).unwrap_or_default();
        let thought_ref = reference(actor, "deliberate");
        let felt = self
            .llm
            .chat_in_lane(&think, at, "deliberate", &c.name, &[
                Msg { role: "system", content: prompts::animal_think_system(&c.kind, &sp.nature) },
                Msg { role: "user", content: prompts::animal_think_user(&c.name, &c.kind, &temperament, &mind, &experiences, &d.scene, &d.reason) },
            ], lane)
            .await
            .map_err(unavailable)?;
        let (feeling, impulse) = match llm::parse_json(&felt.content) {
            Ok(v) => (flat(&v["feeling"]), flat(&v["impulse"])),
            Err(_) => (String::new(), felt.content.chars().take(400).collect()),
        };
        let signals = sp.signals.iter().map(|(k, s)| format!("{k} = {}", s.sound)).collect::<Vec<_>>().join("; ");
        let system = prompts::animal_compile_system(&c.kind, &prompts::species_skills_help(&sp), &signals, &prompts::scent_help(&sp), sp.cognition.max_nodes);
        let top = self.conn.db.brain().id().find(&actor).and_then(|b| living_rules::graph::parse(&b.graph).ok()).map(|g| living_rules::graph::outline(&g.root)).unwrap_or_default();
        let user = prompts::animal_compile_user(&c.name, &c.kind, &impulse, &feeling, &d.scene, &top, &self.repertoire_text(actor));
        let mut messages = vec![Msg { role: "system", content: system }, Msg { role: "user", content: user }];
        let mut last_err = String::new();
        let (mut latency, mut tokens) = (felt.latency_ms, felt.tokens);
        for attempt in 0..3 {
            let reply = self.llm.chat_in_lane(&compile, at, "deliberate", &c.name, &messages, lane).await.map_err(unavailable)?;
            latency += reply.latency_ms;
            tokens += reply.tokens;
            // An impulse is weighed among the animal's desires, like a person's plan. Its
            // instincts are inherited and not rewritten by an impulse: routine edits and new top
            // levels from the compiler are not taken.
            let content = llm::parse_json(&reply.content)
                .ok()
                .map(|mut v| {
                    if let Some(o) = v.as_object_mut() {
                        o.remove("routines");
                        o.remove("restructure");
                    }
                    v
                })
                .and_then(|v| self.plan_into_desires(actor, v))
                .map(|v| v.to_string())
                .unwrap_or_else(|| reply.content.clone());
            if let Ok(v) = llm::parse_json(&content) {
                if v["graph"].is_null() || v["graph"].as_str().map_or(false, |g| g.trim().eq_ignore_ascii_case("keep")) {
                    let changed: Vec<String> = v["routines"].as_array().map(|a| a.iter().filter_map(|r| r["name"].as_str().map(String::from)).collect()).unwrap_or_default();
                    let t = ThoughtIn {
                        kind: "deliberate".into(),
                        summary: format!("{feeling} → {impulse}{}", if changed.is_empty() { String::new() } else { format!(" (reworks {})", changed.join(", ")) }),
                        detail: json!({"reason": d.reason, "feeling": feeling, "impulse": impulse, "think_model": felt.model, "compiled": v, "attempts": attempt + 1}).to_string(),
                        latency_ms: latency,
                        tokens,
                        model: format!("{} → {}", felt.model, reply.model),
                        reference: thought_ref.clone(),
                    };
                    log::info!("{} the {} feels: {feeling} → {impulse}", c.name, c.kind);
                    let (tx, rx) = oneshot::channel();
                    self.conn.reducers.mind_say_then(actor, String::new(), 0, d.updated_ms, t, move |_, r| {
                        let _ = tx.send(flatten(r));
                    })?;
                    return rx.await?.map_err(|e| anyhow!("mind_say: {e}"));
                }
            }
            let parsed = llm::parse_json(&content).and_then(|v| {
                let (g, pruned) = living_rules::graph::from_value_for(v["graph"].clone(), &sp).map_err(|e| anyhow!(e))?;
                Ok((v, g, pruned))
            });
            match parsed {
                Ok((v, g, pruned)) => {
                    let t = ThoughtIn {
                        kind: "deliberate".into(),
                        summary: format!("{feeling} → {impulse}"),
                        detail: json!({"reason": d.reason, "feeling": feeling, "impulse": impulse, "think_model": felt.model, "compiled": v, "attempts": attempt + 1, "pruned": pruned}).to_string(),
                        latency_ms: latency,
                        tokens,
                        model: format!("{} → {}", felt.model, reply.model),
                        reference: thought_ref.clone(),
                    };
                    log::info!("{} the {} feels: {feeling} → {impulse}", c.name, c.kind);
                    return self.install(actor, g.to_json(), impulse.clone(), String::new(), 0, d.updated_ms, t).await;
                }
                Err(e) => {
                    last_err = format!("{e:#}");
                    // Not a runaway reply in full (the person path keeps 3,000 characters too).
                    messages.push(Msg { role: "assistant", content: reply.content.chars().take(3000).collect() });
                    messages.push(Msg { role: "user", content: format!("That reply was rejected: {last_err}. Return the complete corrected JSON object.") });
                }
            }
        }
        let t = ThoughtIn { kind: "error".into(), summary: format!("could not act on: {impulse} ({last_err})"), detail: String::new(), latency_ms: latency, tokens, model: self.llm.model_name(&compile), reference: thought_ref };
        self.skip(actor, d.updated_ms, t).await
    }

    // ---- consolidation ------------------------------------------------------------

    async fn consolidate(&self, actor: u32) -> Result<()> {
        // A woken resident's mind is made first (woken.rs): its identity, from its sheet or the
        // world's facts, then its ring. A consolidation started meanwhile would be shown no
        // identity ("(no persona yet)") and write one afresh over the one being installed, so it
        // waits, as the first deliberation does (the `woken_stage("wait_s")` law).
        if self.is_woken(actor) {
            let wait = Duration::from_secs_f64(prompts::woken_laws().wait_s);
            let started = Instant::now();
            while self.woken_waiting(actor) && started.elapsed() < wait {
                tokio::time::sleep(Duration::from_millis(500)).await;
            }
        }
        let Some(c) = self.conn.db.character().id().find(&actor) else { return Ok(()) };
        let cursor = self.cursor(actor);
        // A reply that ran too long failed: take fewer experiences at a time until it fits.
        let failures = self.actors.lock().unwrap().get(&actor).map_or(0, |m| m.failures);
        let take = (40 / (1 + failures as usize)).max(6);
        let batch: Vec<Experience> = self.experiences(actor).into_iter().filter(|e| e.id > cursor && e.controller == self.me).take(take).collect();
        let Some(upto) = batch.last().map(|e| e.id) else { return Ok(()) };
        // Only experiences that carry meaning go to the model; routine results are passed over.
        let meaningful: Vec<&Experience> = batch.iter().filter(|e| e.salience >= 0.2).collect();
        if meaningful.is_empty() {
            return self.consolidated(actor, upto).await;
        }
        let profile = self.profile(&c);
        let fmt = self.fmt_time();
        // What these experiences bring to mind: what they may confirm, contradict or update.
        let recalled = self.recall_for(actor, &self.experience_cues(actor, &meaningful), 32, 6, "consolidate").await;
        let (mind, memories) = (recalled.mind, recalled.memories);
        let ctx = prompts::Ctx {
            name: &c.name,
            clock: fmt(llm::now_ms()),
            body: String::new(),
            persona: self.persona_text(actor),
            relations: self.relations(actor),
            mind,
            memories,
            judgments: recalled.judgments,
            places: self.places(actor),
            experiences: meaningful.iter().map(|e| self.exp_line(e, &fmt, true)).collect(),
            dealings: self.dealings(actor),
        };
        let animal = c.kind != "person";
        let system = match self.species.get(&c.kind).filter(|_| animal) {
            Some(sp) => prompts::animal_consolidate_system(&c.kind, &sp.nature),
            None => prompts::consolidate_system(),
        };
        let user = prompts::consolidate_user(&ctx);
        let remember = if animal { self.llm.species_profile(&c.kind, "remember").unwrap_or(profile.clone()) } else { profile.clone() };
        let at = self.attention(actor, None);
        let _slow = self.slow.acquire().await?;
        let msgs = [Msg { role: "system", content: system }, Msg { role: "user", content: user }];
        let mut reply = self.llm.chat(&remember, at, "consolidate", &c.name, &msgs).await?;
        let v = match llm::parse_json(&reply.content) {
            Ok(v) => v,
            // A small mind's unusable output is re-done by the competent model.
            Err(e) if animal => {
                let compile = self.llm.species_profile(&c.kind, "compile").unwrap_or(profile.clone());
                log::info!("{}'s memory reply was unusable ({e:#}); retrying with {compile}", c.name);
                reply = self.llm.chat(&compile, at, "consolidate", &c.name, &msgs).await?;
                llm::parse_json(&reply.content)?
            }
            Err(e) => return Err(e),
        };
        let now = llm::now_ms();
        let thought_ref = reference(actor, "consolidate");
        let known: Vec<u64> = meaningful.iter().map(|e| e.id).collect();
        let lookup = |id: u64| batch.iter().find(|e| e.id == id).map(|e| (e.at_ms, e.salience as f64, self.anchors(e)));
        let (mut patch, mut notes) = memory::patch_from(&v, &known, &lookup);
        memory::sugar_into(&v, &mut patch, &known);
        notes.extend(self.canonical_people(actor, &mut patch));
        self.keep_refused_merges(actor, &notes);
        let told = |id: u64| batch.iter().find(|e| e.id == id).map(|e| matches!(e.kind.as_str(), "speech" | "read").then_some(e.subject));
        memory::attribute(&mut patch, actor, &told);
        if c.stage <= 1 {
            for m in patch.remember.iter_mut() {
                m.childhood = true;
            }
        }
        self.name_people(actor, &mut patch);
        // Lived under the minds (a character's history shows both kinds: docs/PLAYER_MEMORY.md).
        patch.lived_under = Some("ai".into());

        // Identity shifts slowly: at most once per 8 minutes unless something momentous happened.
        let momentous = meaningful.iter().any(|e| e.salience >= 0.9);
        let settled = self.conn.db.persona().id().find(&actor).map_or(true, |p| now.saturating_sub(p.updated_ms) > 8 * 60_000);
        let mut v = v;
        if animal {
            if let (Some(id), Some(cur)) = (v["identity"].as_object_mut(), self.conn.db.persona().id().find(&actor)) {
                id.insert("narrative".into(), json!(cur.narrative));
                id.entry("traits").or_insert(serde_json::from_str::<Value>(&cur.traits).unwrap_or(json!({})));
                id.insert("values".into(), json!(cur.values));
                id.insert("goals".into(), json!(cur.goals));
            }
        }
        let identity = match &v["identity"] {
            Value::Object(p) if p.get("narrative").and_then(|n| n.as_str()).map_or(false, |n| !n.is_empty()) && (momentous || settled) && self.persona_changed(actor, p) => Some(Value::Object(p.clone())),
            _ => None,
        };
        if let Some(store) = &self.store {
            store.apply(actor, &patch, &thought_ref, now).await?;
            if let Some(p) = &identity {
                let version = self.conn.db.persona().id().find(&actor).map(|x| x.version + 1).unwrap_or(1);
                store.set_identity(actor, version, p, p["why"].as_str().unwrap_or_default(), &thought_ref, now).await?;
            }
        }

        let summary = v["summary"].as_str().unwrap_or_default().to_string();
        let changed = identity.as_ref().map(|p| format!(" Identity changed: {}", p["why"].as_str().unwrap_or_default())).unwrap_or_default();
        log::info!(
            "{} integrated {} experiences (+{} edges, -{} retracted, {} memories): {summary}{changed}",
            c.name,
            meaningful.len(),
            patch.edges.len(),
            patch.retract.len(),
            patch.remember.len()
        );
        let persona = identity.map(|p| PersonaIn {
            narrative: p["narrative"].as_str().unwrap_or_default().into(),
            values: strings(&p["values"]),
            goals: strings(&p["goals"]),
            traits: p["traits"].to_string(),
            mood: p["mood"].as_str().unwrap_or_default().into(),
        });
        let thought = ThoughtIn {
            kind: "consolidate".into(),
            summary: format!("{summary}{changed}"),
            detail: json!({"experiences": known, "reply": v, "patch": patch, "notes": notes}).to_string(),
            latency_ms: reply.latency_ms,
            tokens: reply.tokens,
            model: reply.model,
            reference: thought_ref,
        };
        self.project(actor, persona, Some(thought)).await?;
        self.consolidated(actor, upto).await
    }

    /// Name person anchors from what the character perceives, when the model did not, and
    /// give every person an edge mentions a node.
    /// People in a patch are named as `actor` knows them (`known_as`): a stranger stays "a
    /// stranger" in its memory, whatever name the model wrote, until it is told the name.
    fn name_people(&self, actor: u32, patch: &mut memory::Patch) {
        for n in patch.nodes.iter_mut() {
            if let Some(id) = n.key.strip_prefix("person:").and_then(|s| s.parse::<u32>().ok()) {
                n.name = Some(self.known_as(actor, id));
            }
        }
        let mut people: Vec<String> = patch.edges.iter().flat_map(|e| [e.from.clone(), e.to.clone()]).filter(|k| k.starts_with("person:") && !patch.nodes.iter().any(|n| &n.key == k)).collect();
        people.sort();
        people.dedup();
        for k in people {
            if let Some(id) = k.strip_prefix("person:").and_then(|s| s.parse::<u32>().ok()) {
                patch.nodes.push(memory::NodeOp { key: k, labels: vec!["Person".into()], name: Some(self.known_as(actor, id)), props: Default::default() });
            }
        }
    }

    /// `person:kael` → `person:7`: people are anchored by id so one person stays one concept.
    /// Then merges are checked again (`memory::merge_refusal`) with people named by id and the
    /// communities and places this mind has located; the refusals are returned as notes and
    /// kept for the next reorganization.
    fn canonical_people(&self, actor: u32, patch: &mut memory::Patch) -> Vec<String> {
        let people: Vec<(String, u32)> = self.conn.db.character().iter().filter(|c| c.kind == "person").map(|c| (c.name.to_lowercase(), c.id)).collect();
        let fix = |k: &mut String| {
            if let Some(rest) = k.strip_prefix("person:") {
                if rest.parse::<u32>().is_err() {
                    let name = rest.trim_start_matches('#').replace('_', " ");
                    if let Some((_, id)) = people.iter().find(|(n, _)| *n == name) {
                        *k = format!("person:{id}");
                    }
                }
            }
        };
        for n in patch.nodes.iter_mut() {
            fix(&mut n.key);
        }
        for e in patch.edges.iter_mut() {
            fix(&mut e.from);
            fix(&mut e.to);
        }
        for r in patch.retract.iter_mut() {
            fix(&mut r.0);
            fix(&mut r.2);
        }
        for m in patch.merges.iter_mut() {
            fix(&mut m.0);
            fix(&mut m.1);
        }
        let known = self.known_anchors(actor);
        let mut notes = Vec::new();
        patch.merges.retain(|(a, b)| match memory::merge_refusal(a, b, &known) {
            _ if a == b => false,
            Some(why) => {
                notes.push(format!("merge {a} → {b} refused: {why}"));
                false
            }
            None => true,
        });
        // Merge duplicate node ops created by the rewrite.
        let mut seen = std::collections::HashSet::new();
        patch.nodes.retain(|n| seen.insert(n.key.clone()));
        notes
    }

    /// Communities by name and the places this mind has located, keyed as concepts are.
    fn known_anchors(&self, actor: u32) -> memory::Known {
        let named = |n: &str| memory::key(n).map(|k| k.trim_start_matches("place:").to_string());
        memory::Known {
            communities: self.conn.db.community().iter().filter_map(|c| Some((named(&c.name)?, c.id))).collect(),
            places: self.conn.db.place().iter().filter(|p| p.actor == actor).filter_map(|p| Some((named(&p.name)?, p.x, p.y))).collect(),
        }
    }

    /// Keep the merge refusals among a patch's notes for the next reorganization (a few, the latest).
    fn keep_refused_merges(&self, actor: u32, notes: &[String]) {
        let mut a = self.actors.lock().unwrap();
        let kept = &mut a.entry(actor).or_default().refused_merges;
        for n in notes.iter().filter(|n| n.starts_with("merge ") && n.contains(" refused: ")) {
            if !kept.contains(n) {
                kept.push(n.clone());
            }
        }
        let over = kept.len().saturating_sub(12);
        kept.drain(..over);
    }

    /// A model may echo the identity unchanged; only real changes become a new version.
    fn persona_changed(&self, actor: u32, p: &serde_json::Map<String, Value>) -> bool {
        let why = p.get("why").and_then(|w| w.as_str()).unwrap_or_default().to_lowercase();
        if ["no change", "no new", "unchanged", "nothing changed", "no significant"].iter().any(|x| why.contains(x)) {
            return false;
        }
        let Some(cur) = self.conn.db.persona().id().find(&actor) else { return true };
        let same_traits = serde_json::from_str::<Value>(&cur.traits).ok().as_ref() == p.get("traits");
        !(p.get("narrative").and_then(|n| n.as_str()) == Some(cur.narrative.as_str())
            && strings(p.get("values").unwrap_or(&Value::Null)) == cur.values
            && strings(p.get("goals").unwrap_or(&Value::Null)) == cur.goals
            && p.get("mood").and_then(|m| m.as_str()) == Some(cur.mood.as_str())
            && same_traits)
    }
}

/// A model's string field, tolerating small models that nest objects where text was asked.
fn flat(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string().chars().take(400).collect(),
    }
}

/// Replace the branch labeled `label` in a graph (outside the reflex layer) with `node`,
/// labeling the new branch; if no such branch exists, add it at top priority.
fn patch_branch(graph: Value, label: &str, node: Value) -> Value {
    let inner = match &graph["first"] {
        Value::Object(o) if o.get("label").and_then(|l| l.as_str()) == Some("reflexes") => o["children"].as_array().and_then(|c| c.last()).cloned().unwrap_or(json!({"wait": 3})),
        _ => graph,
    };
    let labeled = label_node(node, label);
    fn replace(v: &mut Value, label: &str, with: &Value) -> bool {
        match v {
            Value::Object(o) => {
                for key in ["first", "seq"] {
                    if let Some(Value::Object(c)) = o.get(key) {
                        if c.get("label").and_then(|l| l.as_str()) == Some(label) {
                            *v = with.clone();
                            return true;
                        }
                    }
                }
                o.values_mut().any(|x| replace(x, label, with))
            }
            Value::Array(a) => a.iter_mut().any(|x| replace(x, label, with)),
            _ => false,
        }
    }
    let mut inner = inner;
    if replace(&mut inner, label, &labeled) {
        return inner;
    }
    // Not found: the new branch takes priority over the existing behavior.
    match inner.get("first") {
        Some(Value::Array(children)) => {
            let mut c = vec![labeled];
            c.extend(children.iter().cloned());
            json!({"first": c})
        }
        Some(Value::Object(o)) => {
            let mut c = vec![labeled];
            c.extend(o.get("children").and_then(|x| x.as_array()).cloned().unwrap_or_default());
            json!({"first": {"label": o.get("label").cloned().unwrap_or(json!("plan")), "children": c}})
        }
        _ => json!({"first": [labeled, inner]}),
    }
}

/// Ensure a patched branch carries its label (wrapping non-composite nodes).
fn label_node(node: Value, label: &str) -> Value {
    for key in ["first", "seq"] {
        match node.get(key) {
            Some(Value::Array(children)) => return json!({key: {"label": label, "children": children}}),
            Some(Value::Object(o)) => {
                let mut o = o.clone();
                o.insert("label".into(), json!(label));
                return json!({key: o});
            }
            _ => {}
        }
    }
    json!({"first": {"label": label, "children": [node]}})
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A compile that put the decision's words in a say act (a real rules2-r2 reply's shape)
    /// speaks them when the decision said nothing; when it did, its speech stands. Either way
    /// no say act reaches the authority.
    /// An adult with a parent on record (an authored resident whose sheet names them) is not
    /// given a newborn's identity; a child is; a background or the seed's persona come next.
    #[test]
    fn a_first_identity_follows_life_stage_before_parentage() {
        use Origin::*;
        // (person, sheet, background, stage, parent, seeded)
        assert_eq!(Origin::of(true, false, true, 2, true, false), Background, "an adult with parents and a background");
        assert_eq!(Origin::of(true, false, false, 3, true, false), Seed, "an elder with parents and nothing else: no newborn identity, and nothing invented");
        assert_eq!(Origin::of(true, false, false, 2, true, true), Seed, "an adult the seed describes");
        assert_eq!(Origin::of(true, false, true, 1, true, false), Birth, "a child raised by its parents");
        assert_eq!(Origin::of(true, false, false, 0, true, false), Birth, "a newborn");
        assert_eq!(Origin::of(true, true, true, 2, true, false), Sheet, "an authored sheet wins");
        assert_eq!(Origin::of(true, true, true, 1, true, false), Sheet);
        assert_eq!(Origin::of(true, false, false, 1, false, false), Seed, "a child with no parent on record and no background");
        assert_eq!(Origin::of(true, false, false, 2, false, false), Seed, "a joined player's character: who it is shows in what it does");
        assert_eq!(Origin::of(false, false, false, 2, true, false), Birth, "an animal born in the world");
        assert_eq!(Origin::of(false, false, false, 2, false, false), Seed);
    }

    #[test]
    fn a_request_whose_model_failed_waits_longer_each_time_up_to_five_minutes() {
        let secs: Vec<u64> = (1..=9).map(|n| model_backoff(n).as_secs()).collect();
        assert_eq!(secs, [5, 10, 20, 40, 80, 160, 300, 300, 300]);
        assert!(unavailable(anyhow!("HTTP 500")).is::<ModelUnavailable>());
    }

    #[test]
    fn the_community_line_counts_members_and_names_only_those_one_feels_about() {
        let named: Vec<String> = (1..=14).map(|i| format!("P{i} (#{i})")).collect();
        assert_eq!(belonging("Saltreach", 76, &named[..2]), "\nYou belong to Saltreach (with 76 others, among them P1 (#1), P2 (#2))");
        assert_eq!(belonging("Saltreach", 76, &[]), "\nYou belong to Saltreach (with 76 others)");
        assert_eq!(belonging("Saltreach", 76, &named), format!("\nYou belong to Saltreach (with 76 others, among them {} and 2 more you know)", named[..12].join(", ")));
        assert_eq!(belonging("Hollow band", 1, &named[..1]), "\nYou belong to Hollow band (with one other, among them P1 (#1))");
        assert_eq!(belonging("Newtown", 0, &[]), "\nYou belong to Newtown (no one else yet)");
    }

    #[test]
    fn a_compiled_say_act_becomes_the_speech_and_leaves_the_acts() {
        let compiled = || json!({"plan": "meet Marta", "say": null, "acts": [
            {"do": "say", "text": "Morning, Marta — Arlen, here as promised.", "to": "312"},
            {"do": "give", "target": {"id": 312}, "item": "berries", "qty": 2}]});
        let mut v = compiled();
        say_acts_into_speech(&mut v);
        assert_eq!(v["say"], json!({"text": "Morning, Marta — Arlen, here as promised.", "to": 312}));
        assert_eq!(acts_of(&v), vec![json!({"do": "give", "target": {"id": 312}, "item": "berries", "qty": 2}).to_string()]);
        let mut v = compiled();
        v["say"] = json!({"text": "Hello the house!", "to": null});
        say_acts_into_speech(&mut v);
        assert_eq!(v["say"]["text"], "Hello the house!", "the decision's own speech stands");
        assert_eq!(acts_of(&v).len(), 1);
        let mut v = json!({"act": {"do": "say", "target": {"nearest": {"kind": "person"}}, "text": "Anyone home?"}});
        say_acts_into_speech(&mut v);
        assert_eq!((v["say"]["text"].as_str(), v["say"]["to"].is_null(), acts_of(&v).is_empty()), (Some("Anyone home?"), true, true));
    }

    #[test]
    fn patches_replace_labeled_branch_or_take_priority() {
        let g = json!({"first": {"label": "reflexes", "children": [{"wait": 1}, {"first": [
            {"first": {"label": "combat", "children": [{"do": "attack", "target": "attacker"}]}},
            {"do": "wander"}]}]}});
        let p = patch_branch(g, "combat", json!({"first": [{"if": {"threatened": true}, "then": {"do": "dodge"}}, {"do": "attack", "target": "attacker"}]}));
        let s = p.to_string();
        assert!(s.contains("dodge") && s.contains("wander") && !s.contains("reflexes"), "{s}");
        let q = patch_branch(json!({"first": [{"do": "wander"}]}), "combat", json!({"do": "flee", "target": "attacker"}));
        assert_eq!(q["first"][0]["first"]["label"], "combat");
        assert!(living_rules::graph::from_value(q).is_ok());
    }
}
