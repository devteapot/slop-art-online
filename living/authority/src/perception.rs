//! What a character perceives (docs/PERCEPTION.md): the one sight rule, what an observer
//! perceives of another character, and what a human player's client may receive.
//!
//! - **The sight rule** ([`in_sight`]): within the observer's sight (the script's per-creature
//!   `senses` law: day, night, a torch; `common::sight_for`) and with a clear sight line (`Map::sight_clear`: walls, rock and
//!   shut gates hide). Players' perceived sets, minds' percepts and scenes, behaviour graphs and
//!   the combat feed all see by it.
//! - **What an observer perceives of a target** ([`project`]): the target's record through the
//!   script's `perceived_of(p)` law, which decides from what the observer knows and can do (a
//!   known name, its know-how, what a skill use such as `appraise` revealed) which fields it
//!   gets and how precisely: the name or a label, health as a band or exact. The law's answer
//!   depends only on a small input (`RegardIn`), so it is cached by that input and runs a few
//!   times per script revision. Minds' percepts and scenes and players' views use the same
//!   projection, so a mind and a player know the same things about the same target.
//! - **The perceived set.** Every [`SWEEP_MS`] the authority works out, for each living
//!   character a person controls, which creatures it sees. A creature already seen stays seen
//!   until it is the `keep_seen_m` law beyond sight, so one at the edge does not flicker. The answer
//!   is kept as `perceived` rows (private), written only when someone comes into or goes out of
//!   sight, and its projections as `projected` rows (private), written when a creature comes
//!   into sight and when its projection changes (whom the viewer knows, a reveal, a band).
//! - **The views.** `seen_*` return the rows of the perceived creatures and of the player's own
//!   living character (its body is part of the scene); `seen_characters` returns the
//!   projections, `seen_fighters` the moves with the projected band. `my_*` return the player's
//!   own state. Every view reads through point lookups only (`character.controller`,
//!   `perceived.viewer`, `projected.viewer`, primary keys, `*.actor`, `inventory.owner`,
//!   `experience.observer`): 2.14.1 records a point lookup as that key in the view's read set,
//!   but any range scan as a read of the whole table, which would re-run the view on every write.
//! - **The moving-body stream** is the narrow [`Motion`] row: what a client draws, without the
//!   path, the chunk or the kind (a creature's kind is on its projection).
//!
//! Spatial perception is enforced here, on the authority. The views are re-run by the server,
//! inside the transaction that wrote what they read, whenever a row they read changes, so the
//! cost grows with players × updates of what each perceives (measured in docs/PERCEPTION.md).

use crate::common::{self, pos, NearCreature};
use crate::tables::*;
use living_rules::map::Map;
use living_rules::combat::HealthSeen;
use living_rules::script::{Precision, Regard, RegardIn, Scripts};
use spacetimedb::rand::Rng;
use spacetimedb::{Identity, ReducerContext, SpacetimeType, Table, ViewContext};
use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::rc::Rc;

/// How often each player's perceived set is worked out again (ms), staggered by character.
pub const SWEEP_MS: u64 = 200;

/// A body's current motion segment as clients draw it (see `Body`): from `(x, y)` facing
/// `heading` at `t_ms`, moving at velocity `(vx, vy)`, turning at `turn` rad/s for `turn_s`
/// seconds, until `next_ms` (the segment's end, when steering looks again; `u64::MAX` at
/// rest). `speed` is the cruising speed of the movement under way, which tells its gait
/// (a walk, or a run at the creature's `motion` law's `run` times a walk). About 52 B against the `body`
/// row's 70 B plus 16 B per path corner.
#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub struct Motion {
    pub id: u32,
    pub x: f32,
    pub y: f32,
    pub t_ms: u64,
    pub vx: f32,
    pub vy: f32,
    pub heading: f32,
    pub turn: f32,
    pub turn_s: f32,
    pub next_ms: u64,
    pub speed: f32,
}

impl From<&Body> for Motion {
    fn from(b: &Body) -> Self {
        Self { id: b.id, x: b.x, y: b.y, t_ms: b.t_ms, vx: b.vx, vy: b.vy, heading: b.heading, turn: b.turn, turn_s: b.turn_s, next_ms: b.next_ms, speed: b.speed }
    }
}

/// A body's motion segment as clients receive it (`seen_bodies`, `my_body`): the travel
/// segment of [`Motion`] (where the legs go: `heading`, `turn`, `turn_s`) and the facing
/// segment (where the head and chest look) as an offset from the travel heading: `face_off`
/// radians at `t_ms`, turning at `face_turn` rad/s for the first `face_turn_s` seconds, then
/// held. Facing at time t is `steer::facing(heading_at(t), face_off, face_turn, face_turn_s,
/// t - t_ms)`, the function the authority's facing sight uses. 64 B. `Motion` itself stays as
/// it is: it is stored in `motion_seen`, and a column's type may not change in place
/// (automatic migrations), so the facing is appended there as its own columns.
#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub struct Moving {
    pub id: u32,
    pub x: f32,
    pub y: f32,
    pub t_ms: u64,
    pub vx: f32,
    pub vy: f32,
    pub heading: f32,
    pub turn: f32,
    pub turn_s: f32,
    pub next_ms: u64,
    pub speed: f32,
    pub face_off: f32,
    pub face_turn: f32,
    pub face_turn_s: f32,
    /// Running now (`body.running`): the gait to draw, for any controller.
    pub running: bool,
}

impl From<&Body> for Moving {
    fn from(b: &Body) -> Self {
        Self { id: b.id, x: b.x, y: b.y, t_ms: b.t_ms, vx: b.vx, vy: b.vy, heading: b.heading, turn: b.turn, turn_s: b.turn_s, next_ms: b.next_ms, speed: b.speed, face_off: b.face_off, face_turn: b.face_turn, face_turn_s: b.face_turn_s, running: b.running }
    }
}

impl MotionSeen {
    pub fn of(id: u64, viewer: Identity, b: &Body) -> Self {
        Self { id, viewer, motion: Motion::from(b), face_off: b.face_off, face_turn: b.face_turn, face_turn_s: b.face_turn_s, running: b.running }
    }
    pub fn moving(&self) -> Moving {
        let m = &self.motion;
        Moving { id: m.id, x: m.x, y: m.y, t_ms: m.t_ms, vx: m.vx, vy: m.vy, heading: m.heading, turn: m.turn, turn_s: m.turn_s, next_ms: m.next_ms, speed: m.speed, face_off: self.face_off, face_turn: self.face_turn, face_turn_s: self.face_turn_s, running: self.running }
    }
    /// Write `m` into this row (the motion and the facing columns).
    pub fn set(&mut self, m: &Moving) {
        self.motion = Motion { id: m.id, x: m.x, y: m.y, t_ms: m.t_ms, vx: m.vx, vy: m.vy, heading: m.heading, turn: m.turn, turn_s: m.turn_s, next_ms: m.next_ms, speed: m.speed };
        self.face_off = m.face_off;
        self.face_turn = m.face_turn;
        self.face_turn_s = m.face_turn_s;
        self.running = m.running;
    }
}

/// What a player perceives of a character in its scene (the `perceived_of` law's projection
/// of the character's record; its own character included). No controller, no home, no
/// parents: what anyone looking would see, and what this viewer knows.
#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub struct SeenCharacter {
    pub id: u32,
    /// The name when the viewer knows it, else empty.
    pub name: String,
    /// How the viewer refers to it: the name, or `a stranger`, `a child`, `a wolf`.
    pub label: String,
    pub kind: String,
    /// Life stage: 0 infant, 1 child, 2 adult, 3 elder.
    pub stage: u8,
    /// Build (`giants`, `small_folk`, or empty for the common one) and dress style, from the
    /// settlement the character lives in.
    pub folk: String,
    pub style: String,
    /// It is the viewer's own character.
    pub own: bool,
    /// Health band (4 unhurt … 0 barely standing; 255 not perceived), and exact health when
    /// the law grants it (else -1).
    pub band: u8,
    pub hp: f32,
    pub max_hp: f32,
}

/// A standing trade offer my living character is a party to (`my_offers`). `from` gives
/// `give_qty` `give_item` to `to` for `want_qty` `want_item`; both are character ids, which
/// the client names through `seen_characters` (no name here: the caller may not know it).
/// `incoming` is true when it is addressed to me (I may `accept` it toward `from`), false
/// when it is mine. It can be accepted until `until_ms` (world time, ms since the Unix epoch,
/// the clock of `experience.at_ms`); the row goes within a second after.
#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub struct MyOffer {
    pub id: u64,
    pub incoming: bool,
    pub from: u32,
    pub to: u32,
    pub give_item: String,
    pub give_qty: u32,
    pub want_item: String,
    pub want_qty: u32,
    pub at_ms: u64,
    pub until_ms: u64,
}

// ---- the one sight rule ------------------------------------------------------------------

/// The one sight rule: whether `observer`, its eye at `eye` and its body facing `heading`, sees
/// `at` (`dist` away), where creature `target` stands (0: a place, no light on it). Its own
/// senses now (the `senses` law: sight, and a field when the world's `fov_on` law is on), the
/// light on the target (the `glow` law, which shows it only within the field) and a clear sight
/// line, decided by `living_rules::sight::sees`, the function the game client calls too.
/// `kept`: the target is already seen (the keep margins on distance and angle). Players'
/// perceived sets, minds' percepts and scenes, behaviour graphs, witnesses, the combat feed and
/// a player's aimed act all see by this.
#[allow(clippy::too_many_arguments)]
pub fn in_sight(ctx: &ReducerContext, map: &Map, observer: u32, eye: (f32, f32), heading: f32, target: u32, at: (f32, f32), dist: f32, w: &World, now: u64, kept: bool) -> bool {
    let senses = common::senses_of(ctx, observer, w, now);
    let glow = if target != 0 { common::glow_of(ctx, target, w, now) } else { 0.0 };
    let keep = kept.then(|| common::laws(ctx).keep_seen_m);
    living_rules::sight::sees(map, eye, heading, at, dist, &senses, glow, keep)
}

/// Whether character `id`, its body `eye`, sees the place `at` now.
pub fn sees(ctx: &ReducerContext, id: u32, eye: &Body, at: (f32, f32), w: &World, map: &Map, now: u64) -> bool {
    let e = pos(eye, now);
    in_sight(ctx, map, id, e, common::facing_at(eye, now), 0, at, common::dist(e, at), w, now, false)
}

/// What character `id` at `at` sees now and what it hears but does not see, from one gather of
/// the creatures round it, nearest first, itself excluded. Seen: within its sight (`sight`, its
/// `senses` law's now) or the `glow` of a light on them (a carried torch, lamplight), within its
/// field when the world's law turns it on, with a clear line. Heard: only while it has a field,
/// within its hearing and not seen ([`heard`] for one that has no scene to share).
pub fn sensed(ctx: &ReducerContext, id: u32, at: (f32, f32), sight: f32, now: u64) -> (Vec<NearCreature>, Vec<NearCreature>) {
    let map = common::map(ctx);
    let w = common::world(ctx);
    let senses = common::senses_of(ctx, id, &w, now);
    let gather = common::gather_radius(ctx, sight);
    let lit = gather > sight;
    // Facing matters only with a field (one body lookup then), and only then is anything heard.
    let field = senses.field.is_some();
    let heading = if field { ctx.db.body().id().find(id).map_or(0.0, |b| common::facing_at(&b, now)) } else { 0.0 };
    let hearing = if field { senses.hearing } else { 0.0 };
    let (mut seen, mut heard) = (Vec::new(), Vec::new());
    for c in common::creatures_near(ctx, at, gather.max(hearing), now) {
        if c.id == id {
            continue;
        }
        if c.dist <= gather && living_rules::sight::sees(&map, at, heading, c.pos, c.dist, &senses, if lit { common::glow_of(ctx, c.id, &w, now) } else { 0.0 }, None) {
            seen.push(c);
        } else if c.dist <= hearing {
            heard.push(c);
        }
    }
    (seen, heard)
}

/// What `id` at `at`, facing `heading`, hears but does not see now, when its senses have a
/// field (the `fov_on` law; without one, nothing is told as heard and everything stays as it
/// was): every creature within its hearing, all round, that is not in `seen`. Nearest first.
pub fn heard(ctx: &ReducerContext, id: u32, at: (f32, f32), seen: &HashSet<u32>, now: u64) -> Vec<NearCreature> {
    let w = common::world(ctx);
    let s = common::senses_of(ctx, id, &w, now);
    if s.field.is_none() || s.hearing <= 0.0 {
        return Vec::new();
    }
    common::creatures_near(ctx, at, s.hearing, now).into_iter().filter(|c| c.id != id && !seen.contains(&c.id)).collect()
}

/// How a heard creature is told: its kind as a listener can tell it (the script's `heard_as`
/// law: "person", "deer", "wolf", else "creature").
pub fn heard_kind(ctx: &ReducerContext, kind: &str) -> String {
    let sc = common::scripts(ctx);
    sc.heard_as(kind)
}

/// The largest sight anyone has now (for gathering onlookers before each one's own test): the
/// `senses` law's reach.
pub fn widest_sight(ctx: &ReducerContext, w: &World, now: u64) -> f32 {
    common::widest_sight(ctx, w, now)
}

// ---- what an observer perceives of a target (the `perceived_of` law) ----------------------

/// The projection of a target's record for one observer.
#[derive(Clone, Debug, PartialEq)]
pub struct Projection {
    pub name: String,
    pub label: String,
    pub kind: String,
    pub stage: u8,
    pub folk: String,
    pub style: String,
    pub band: u8,
    pub hp: f32,
    pub max_hp: f32,
}

thread_local! {
    /// The law's answers by input (its answer depends only on `RegardIn`), for the script
    /// they came from: a handful of distinct inputs cover a world, so the law runs a few times
    /// per script revision, not per observer and target.
    static REGARDS: RefCell<Option<(Rc<Scripts>, HashMap<RegardIn, Regard>)>> = const { RefCell::new(None) };
    /// Knowledge epochs: a character's (bumped when whom it knows changes) and the world's
    /// (communities change). The sweep re-projects a viewer's rows when either moved.
    static KNOWLEDGE: RefCell<(u32, HashMap<u32, u32>)> = RefCell::new((0, HashMap::new()));
    /// Build and dress by home position (settlements are static).
    static DRESS: RefCell<HashMap<(u32, u32), (String, String)>> = RefCell::new(HashMap::new());
}

/// Whom `id` knows changed (`None`: anyone's may have, e.g. a community's members).
pub fn knowledge_changed(id: Option<u32>) {
    KNOWLEDGE.with(|k| {
        let mut k = k.borrow_mut();
        match id {
            Some(id) => *k.1.entry(id).or_default() += 1,
            None => k.0 += 1,
        }
    });
}

fn knowledge_epoch(id: u32) -> (u32, u32) {
    KNOWLEDGE.with(|k| {
        let k = k.borrow();
        (k.0, k.1.get(&id).copied().unwrap_or(0))
    })
}

fn regard_of(sc: &Rc<Scripts>, input: RegardIn) -> Regard {
    REGARDS.with(|r| {
        let mut r = r.borrow_mut();
        if r.as_ref().map_or(true, |(s, _)| !Rc::ptr_eq(s, sc)) {
            *r = Some((sc.clone(), HashMap::new()));
        }
        let (_, map) = r.as_mut().unwrap();
        if let Some(v) = map.get(&input) {
            return *v;
        }
        let v = sc.perceived_of(&input);
        map.insert(input, v);
        v
    })
}

/// Whether `observer` knows `target`'s name: itself, its parents, children and the parent of
/// its children, its community, someone its mind has feelings about (`relation`), or
/// someone who told it their name (`acquaintance`, which also keeps the names of its
/// community's dead: `remember_member`).
pub fn knows_name(ctx: &ReducerContext, observer: &Character, target: &Character) -> bool {
    let (o, t) = (observer.id, target.id);
    if o == t || observer.parent_a == t || observer.parent_b == t || target.parent_a == o || target.parent_b == o {
        return true;
    }
    // Told their name (an introduction). Having feelings about someone is not knowing their
    // name: a mind can feel for a stranger it only saw (docs/TOWN_LIFE.md, "Layer 2").
    if ctx.db.acquaintance().by_pair().filter((o, t)).next().is_some() {
        return true;
    }
    if let (Some(a), Some(b)) = (ctx.db.membership().member().find(o), ctx.db.membership().member().find(t)) {
        if a.community == b.community {
            return true;
        }
    }
    // The other parent of one's children.
    ctx.db.character().parent_a().filter(o).any(|c| c.parent_b == t) || ctx.db.character().parent_b().filter(o).any(|c| c.parent_a == t)
}

/// What a skill use still reveals to `observer` about `target` (sorted).
pub fn revealed(ctx: &ReducerContext, observer: u32, target: u32, now: u64) -> Vec<String> {
    let mut v: Vec<String> = ctx.db.reveal().observer().filter(observer).filter(|r| r.target == target && r.until_ms > now).map(|r| r.what).collect();
    v.sort();
    v.dedup();
    v
}

/// The law's answer for `observer` looking at `target` now.
pub fn regard(ctx: &ReducerContext, observer: &Character, target: &Character, now: u64) -> Regard {
    regard_knowing(ctx, observer, &known_techniques(ctx, observer.id), target, now)
}

/// What `observer` knows how to do, as the law receives it (sorted).
fn known_techniques(ctx: &ReducerContext, id: u32) -> Vec<String> {
    let mut knows = common::knows(ctx, id);
    knows.sort();
    knows
}

/// The law's answer with the observer's know-how already read (one observer, several targets).
fn regard_knowing(ctx: &ReducerContext, observer: &Character, knows: &[String], target: &Character, now: u64) -> Regard {
    let w = common::world(ctx);
    let sc = common::scripts(ctx);
    let knows = knows.to_vec();
    let input = RegardIn {
        observer_kind: observer.kind.clone(),
        knows,
        target_kind: target.kind.clone(),
        known: knows_name(ctx, observer, target),
        revealed: revealed(ctx, observer.id, target.id, now),
        own: observer.id == target.id,
        night: common::night(ctx, &w, now),
        dist: regard_dist(ctx, &sc, observer.id, target.id, now),
    };
    regard_of(&sc, input)
}

/// How far `target` is from `observer` for the `perceived_of` law, in whole metres rounded up;
/// 0 when the law does not read it (two body lookups otherwise).
fn regard_dist(ctx: &ReducerContext, sc: &Scripts, observer: u32, target: u32, now: u64) -> u16 {
    if observer == target || !sc.regard_reads_dist() {
        return 0;
    }
    match (ctx.db.body().id().find(observer), ctx.db.body().id().find(target)) {
        (Some(a), Some(b)) => common::dist(pos(&a, now), pos(&b, now)).ceil().clamp(0.0, u16::MAX as f32) as u16,
        _ => 0,
    }
}

/// How one refers to someone whose name one does not know.
pub fn stranger(kind: &str, stage: u8) -> String {
    if kind == "person" {
        return match stage {
            0 => "a baby",
            1 => "a child",
            3 => "an old stranger",
            _ => "a stranger",
        }
        .into();
    }
    let article = if kind.starts_with(['a', 'e', 'i', 'o', 'u']) { "an" } else { "a" };
    format!("{article} {kind}")
}

/// How one refers to someone the law does not name: a person too far away to make out
/// (`Regard::far`) is "someone too far away to make out", whoever they are; otherwise as
/// [`stranger`]. An animal keeps its kind ("a wolf") at any distance.
pub fn unnamed(t: &Character, far: bool) -> String {
    if far && t.kind == "person" {
        living_rules::script::FAR_PERSON.into()
    } else {
        stranger(&t.kind, t.stage)
    }
}

/// Build and dress as seen: from the settlement round the character's home.
fn dress(ctx: &ReducerContext, c: &Character) -> (String, String) {
    let key = (c.home_x.to_bits(), c.home_y.to_bits());
    if let Some(d) = DRESS.with(|d| d.borrow().get(&key).cloned()) {
        return d;
    }
    let home = (c.home_x, c.home_y);
    let d = if home == (0.0, 0.0) {
        (String::new(), String::new())
    } else {
        ctx.db
            .settlement()
            .iter()
            .filter(|s| common::dist((s.x, s.y), home) <= s.radius_m * 1.15)
            .min_by(|a, b| common::dist((a.x, a.y), home).total_cmp(&common::dist((b.x, b.y), home)))
            .map(|s| (if s.kind == "giants" || s.kind == "small_folk" { s.kind.clone() } else { String::new() }, s.style.clone()))
            .unwrap_or_default()
    };
    DRESS.with(|m| m.borrow_mut().insert(key, d.clone()));
    d
}

/// What `observer` perceives of `target` now: its record through the `perceived_of` law.
pub fn project(ctx: &ReducerContext, observer: &Character, target: &Character, now: u64) -> Projection {
    let r = regard(ctx, observer, target, now);
    let (folk, style) = dress(ctx, target);
    let (band, hp, max_hp) = match health_as(ctx, r.health, target.id, now) {
        None => (255, -1.0, -1.0),
        Some(HealthSeen { band, exact: None }) => (band, -1.0, -1.0),
        Some(HealthSeen { band, exact: Some((hp, max)) }) => (band, hp.max(0.0).round(), max.round()),
    };
    let label = if r.name { target.name.clone() } else { unnamed(target, r.far) };
    Projection { name: if r.name { target.name.clone() } else { String::new() }, label, kind: target.kind.clone(), stage: target.stage, folk, style, band, hp, max_hp }
}

/// How `observer` perceives `target`'s health now, as the `perceived_of` law grants it: the
/// band everyone sees, exact for oneself or while a reveal (`appraise`) is in force for this
/// observer, `None` where the law hides it. Every text that tells a mind or a player about
/// another's health goes through this (the projection, the scene, fight reports, graph
/// conditions), never through the target's `vitals`.
pub fn health_seen(ctx: &ReducerContext, observer: &Character, target: &Character, now: u64) -> Option<HealthSeen> {
    health_as(ctx, regard(ctx, observer, target, now).health, target.id, now)
}

fn health_as(ctx: &ReducerContext, precision: Precision, id: u32, now: u64) -> Option<HealthSeen> {
    let (hp, max_hp) = ctx.db.vitals().id().find(id).map(|v| (common::needs(&v, now).hp, v.max_hp)).unwrap_or((0.0, 0.0));
    let band = living_rules::combat::band(hp, max_hp);
    match precision {
        Precision::None => None,
        Precision::Band => Some(HealthSeen { band, exact: None }),
        Precision::Exact => Some(HealthSeen { band, exact: Some((hp, max_hp)) }),
    }
}

/// How `observer` refers to `id` (the projection's label).
pub fn label(ctx: &ReducerContext, observer: &Character, id: u32, now: u64) -> String {
    labels(ctx, observer, &[id], now).pop().unwrap_or_default()
}

/// How `observer` refers to each of `ids`, its know-how read once.
pub fn labels(ctx: &ReducerContext, observer: &Character, ids: &[u32], now: u64) -> Vec<String> {
    let knows = known_techniques(ctx, observer.id);
    ids.iter()
        .map(|id| match ctx.db.character().id().find(*id) {
            Some(t) => {
                let r = regard_knowing(ctx, observer, &knows, &t, now);
                if r.name {
                    t.name
                } else {
                    unnamed(&t, r.far)
                }
            }
            None => "someone".into(),
        })
        .collect()
}

impl Projection {
    fn into_row(self, viewer: Identity, body: u32, own: bool, id: u64) -> Projected {
        Projected { id, viewer, body, own, name: self.name, label: self.label, kind: self.kind, stage: self.stage, folk: self.folk, style: self.style, band: self.band, hp: self.hp, max_hp: self.max_hp }
    }

    fn same_as(&self, p: &Projected) -> bool {
        self.name == p.name && self.label == p.label && self.kind == p.kind && self.stage == p.stage && self.folk == p.folk && self.style == p.style && self.band == p.band && self.hp == p.hp && self.max_hp == p.max_hp
    }
}

// ---- what an observer perceives a target doing --------------------------------------------

/// How near the line of a mover's heading something must be to be what it walks toward: within
/// about 18° of it.
const TOWARD_COS: f32 = 0.95;

/// What a creature is perceived doing (a mind's scene, the first sight of someone): its
/// activity's label, which is what anyone sees of it ("goto → person"), except when its body is
/// moving under its controller's direct intent (`motion::GOAL_DIRECTION`: a player's movement
/// keys) and its activity is none or `wait`. Then the motion is what is seen ([`moving_label`]).
/// It reads the body and its steering, never who controls it, so the same body behaviour reads
/// the same whoever plays it (docs/PERCEPTION.md, "Activity derived from the body").
/// `observer` and `seen` (what it sees) are whom the walker can be heading toward. Point lookups
/// on `activity`, `steer` and `body` only; nothing is written.
pub fn doing_of(ctx: &ReducerContext, id: u32, observer: (u32, &str, (f32, f32)), seen: &[NearCreature], now: u64) -> Option<String> {
    let a = ctx.db.activity().id().find(id);
    if a.as_ref().is_some_and(|a| a.skill != "wait") {
        return a.map(|a| a.label);
    }
    let st = ctx.db.steer().id().find(id).filter(|s| s.goal == crate::motion::GOAL_DIRECTION);
    let b = st.as_ref().and_then(|_| ctx.db.body().id().find(id)).filter(|b| b.vx != 0.0 || b.vy != 0.0);
    match (st, b) {
        (Some(st), Some(b)) => {
            let dt = now.min(b.next_ms).saturating_sub(b.t_ms) as f32 / 1000.0;
            let (x, y, heading) = living_rules::steer::pose(b.x, b.y, b.heading, b.vx.hypot(b.vy), b.turn, b.turn_s, dt);
            let among = std::iter::once((observer.1, observer.2)).filter(|_| observer.0 != id).chain(seen.iter().filter(|c| c.id != id).map(|c| (&*c.kind, c.pos)));
            Some(moving_label(st.flags & crate::motion::FLAG_RUN != 0, (x, y), heading, among))
        }
        _ => a.map(|a| a.label),
    }
}

/// The motion seen of a body moving with no activity of its own, in the style of an activity's
/// label: `walk` or `run` (the run input), then `→ <kind>` of the nearest creature its heading
/// points at, else the compass way it goes ("walk east").
pub fn moving_label<'a>(run: bool, at: (f32, f32), heading: f32, among: impl IntoIterator<Item = (&'a str, (f32, f32))>) -> String {
    let gait = if run { "run" } else { "walk" };
    let (hx, hy) = (heading.cos(), heading.sin());
    let ahead = among
        .into_iter()
        .filter_map(|(kind, p)| {
            let (dx, dy) = (p.0 - at.0, p.1 - at.1);
            let d = dx.hypot(dy);
            (d > 0.3 && (dx * hx + dy * hy) / d >= TOWARD_COS).then_some((d, kind))
        })
        .min_by(|a, b| a.0.total_cmp(&b.0));
    match ahead {
        Some((_, kind)) => format!("{gait} → {kind}"),
        None => format!("{gait} {}", common::direction(at, (at.0 + 2.0 * hx, at.1 + 2.0 * hy))),
    }
}

#[cfg(test)]
mod doing_tests {
    use super::moving_label;

    #[test]
    fn a_walker_heading_at_someone_walks_toward_them() {
        // Heading east (+x) at a person 6 m ahead, a wolf off to the side.
        let l = moving_label(false, (0.0, 0.0), 0.0, [("wolf", (3.0, 4.0)), ("person", (6.0, 0.5))]);
        assert_eq!(l, "walk → person");
        // The nearest of those ahead.
        assert_eq!(moving_label(true, (0.0, 0.0), 0.0, [("person", (9.0, 0.0)), ("deer", (4.0, 0.2))]), "run → deer");
    }

    #[test]
    fn a_walker_heading_at_no_one_goes_a_compass_way() {
        // +y is south; someone behind or well off the line is not what it walks toward.
        let l = moving_label(false, (0.0, 0.0), std::f32::consts::FRAC_PI_2, [("person", (0.0, -5.0)), ("person", (4.0, 4.0))]);
        assert_eq!(l, "walk south");
        assert_eq!(moving_label(true, (10.0, 10.0), std::f32::consts::PI, []), "run west");
    }
}

// ---- the perceived set ---------------------------------------------------------------------

thread_local! {
    /// When each player's character was last swept (module cache; a fresh instance sweeps
    /// everyone once, staggered).
    static LAST: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    /// The knowledge epochs each player's rows were last projected at, and the targets a
    /// reveal held for it then.
    static PROJECTED: RefCell<HashMap<u32, ((u32, u32), HashSet<u32>)>> = RefCell::new(HashMap::new());
}

/// Sweep the players whose turn it is (every tick; each player every [`SWEEP_MS`]).
pub fn sweep(ctx: &ReducerContext, now: u64) {
    let humans = crate::combat::humans(ctx);
    if humans.is_empty() {
        return;
    }
    let due: Vec<(u32, Identity)> = LAST.with(|l| {
        let mut l = l.borrow_mut();
        let ids: HashSet<u32> = humans.iter().map(|(h, _)| *h).collect();
        l.retain(|id, _| ids.contains(id));
        PROJECTED.with(|p| p.borrow_mut().retain(|id, _| ids.contains(id)));
        humans
            .into_iter()
            .filter(|(id, _)| {
                // A character first seen by this instance gets a staggered start.
                let last = *l.entry(*id).or_insert_with(|| now.saturating_sub((*id as u64).wrapping_mul(37) % SWEEP_MS));
                if now.saturating_sub(last) >= SWEEP_MS {
                    l.insert(*id, now);
                    true
                } else {
                    false
                }
            })
            .collect()
    });
    if due.is_empty() {
        return;
    }
    let w = common::world(ctx);
    let map = common::map(ctx);
    for (id, viewer) in due {
        sweep_one(ctx, id, viewer, &w, &map, now);
    }
}

/// Work out one player's perceived set now (also right after a join or a return).
pub fn sweep_now(ctx: &ReducerContext, id: u32, viewer: Identity, now: u64) {
    crate::frame::catch_up_lines(ctx, id);
    crate::combat::clear_feed(ctx, viewer);
    LAST.with(|l| l.borrow_mut().insert(id, now));
    PROJECTED.with(|p| p.borrow_mut().remove(&id));
    sweep_one(ctx, id, viewer, &common::world(ctx), &common::map(ctx), now);
}

fn sweep_one(ctx: &ReducerContext, id: u32, viewer: Identity, w: &World, map: &Map, now: u64) {
    let Some(b) = ctx.db.body().id().find(id) else { return };
    let Some(me) = ctx.db.character().id().find(id) else { return };
    let here = pos(&b, now);
    let heading = common::facing_at(&b, now);
    let senses = common::senses_of(ctx, id, w, now);
    let sight = senses.sight;
    let rows: Vec<Perceived> = ctx.db.perceived().viewer().filter(viewer).collect();
    let had: HashSet<u32> = rows.iter().map(|p| p.body).collect();
    let mut seen: HashSet<u32> = HashSet::new();
    let keep = common::laws(ctx).keep_seen_m;
    // Gathered within the viewer's sight, or the farthest glow when the world's laws light
    // people (a carried torch, lamplight); each is then seen by the one sight rule: its reach
    // in that direction (the field, when the world's law gives one), the light on it, and a
    // clear line. A creature already seen keeps the margins (`keep_seen_m`, the field's angle).
    let gather = common::gather_radius(ctx, sight);
    let lit = gather > sight;
    for c in common::creatures_near(ctx, here, gather + keep, now) {
        if c.id == id {
            continue;
        }
        let glow = if lit { common::glow_of(ctx, c.id, w, now) } else { 0.0 };
        let kept = had.contains(&c.id).then_some(keep);
        if living_rules::sight::sees(map, here, heading, c.pos, c.dist, &senses, glow, kept) {
            seen.insert(c.id);
        }
    }
    hear(ctx, id, viewer, here, &seen, now);
    for p in &rows {
        if !seen.contains(&p.body) {
            ctx.db.perceived().id().delete(p.id);
            ctx.db.motion_seen().id().delete(crate::frame::key(id, p.body));
            ctx.db.fighter_seen().id().delete(crate::frame::key(id, p.body));
            ctx.db.doing_seen().id().delete(crate::frame::key(id, p.body));
        }
    }
    let entered: Vec<u32> = seen.difference(&had).copied().collect();
    let left = had.len() + entered.len() != seen.len();
    for body in &entered {
        ctx.db.perceived().insert(Perceived { id: 0, viewer, body: *body, since_ms: now });
        // How it moves, as it is now; frames keep it current (`frame.rs`).
        if let Some(b) = ctx.db.body().id().find(*body) {
            let row = MotionSeen::of(crate::frame::key(id, *body), viewer, &b);
            if ctx.db.motion_seen().id().find(row.id).is_some() {
                ctx.db.motion_seen().id().update(row);
            } else {
                ctx.db.motion_seen().insert(row);
            }
        }
    }
    crate::frame::scene(id, viewer, &seen);
    // The projections follow: a row per creature in the scene (itself included), projected
    // when it comes into sight, and again only when an input of the law changed: whom the
    // viewer knows (its knowledge epoch, or this instance has not projected it yet), a reveal
    // that holds or has just stopped holding, and its own row (exact health). Band changes
    // reach the rows through `health_moved`.
    let epoch = knowledge_epoch(id);
    let revealing: HashSet<u32> = ctx.db.reveal().observer().filter(id).filter(|r| r.until_ms > now).map(|r| r.target).collect();
    let (all, mut again) = PROJECTED.with(|p| {
        let mut p = p.borrow_mut();
        match p.insert(id, (epoch, revealing.clone())) {
            Some((e, old)) if e == epoch => (false, old.union(&revealing).copied().collect::<HashSet<u32>>()),
            _ => (true, HashSet::new()),
        }
    });
    // A law that reads how far the target is (names only within a distance) may answer
    // otherwise as anyone moves: every row is projected again, and written only if it changed.
    let all = all || common::scripts(ctx).regard_reads_dist();
    // The viewer's own row (its exact health drifting between blows) is projected again about
    // once a second; blows reach it at once through `health_moved`.
    let own_due = (now / SWEEP_MS) % 5 == id as u64 % 5;
    // Nothing came or went and no input changed: only that row.
    if !all && again.is_empty() && entered.is_empty() && !left {
        if own_due {
            if let Some(p) = ctx.db.projected().body().filter(id).find(|p| p.own && p.viewer == viewer) {
                let pr = project(ctx, &me, &me, now);
                if !pr.same_as(&p) {
                    ctx.db.projected().id().update(pr.into_row(viewer, id, true, p.id));
                }
                return;
            }
        } else {
            return;
        }
    }
    if own_due {
        again.insert(id);
    }
    seen.insert(id);
    let mut have: HashSet<u32> = HashSet::new();
    for p in ctx.db.projected().viewer().filter(viewer).collect::<Vec<_>>() {
        if !seen.contains(&p.body) || p.own != (p.body == id) || !have.insert(p.body) {
            ctx.db.projected().id().delete(p.id);
            continue;
        }
        if all || again.contains(&p.body) {
            let Some(t) = ctx.db.character().id().find(p.body) else { continue };
            let pr = project(ctx, &me, &t, now);
            if !pr.same_as(&p) {
                ctx.db.projected().id().update(pr.into_row(viewer, p.body, p.own, p.id));
            }
        }
    }
    for body in seen.difference(&have) {
        let Some(t) = ctx.db.character().id().find(*body) else { continue };
        let pr = project(ctx, &me, &t, now);
        ctx.db.projected().insert(pr.into_row(viewer, *body, *body == id, 0));
    }
    // The move of each newcomer that has fought, with the band its projection grants.
    for body in &entered {
        crate::frame::show_fighter(ctx, id, viewer, *body, true, now);
        crate::frame::show_doing(ctx, id, viewer, *body);
    }
}

// ---- heard, not seen -----------------------------------------------------------------------

/// How long a heard key's salt epoch lasts: a sound that starts in another epoch gets a key
/// that cannot be matched with an earlier one of the same creature (ms).
const HEAR_EPOCH_MS: u64 = 240_000;

thread_local! {
    /// When each (listener, target) was last heard (module memory; a fresh instance starts each
    /// row's linger at its first sweep).
    static HEARD_LAST: RefCell<HashMap<(u32, u32), u64>> = RefCell::new(HashMap::new());
}

fn hear_salt(ctx: &ReducerContext) -> u64 {
    if let Some(s) = ctx.db.hear_salt().id().find(0) {
        return s.salt;
    }
    let salt: u64 = ctx.rng().gen();
    ctx.db.hear_salt().insert(HearSalt { id: 0, salt });
    salt
}

/// A listener's key for a sound: from the listener, the target and the secret salt of the epoch
/// it began in. Not the character id, and not derivable from it without the salt.
fn heard_key(salt: u64, listener: u32, target: u32, now: u64) -> u64 {
    let mut x = salt ^ ((listener as u64) << 32 | target as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ (now / HEAR_EPOCH_MS).wrapping_mul(0xC2B2_AE3D_27D4_EB4F);
    // splitmix64's finalizer.
    x = (x ^ (x >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    x ^ (x >> 31)
}

/// What a player hears but does not see, kept in its `heard` rows (the `heard_sounds` view):
/// written when a sound starts or its bearing or band changes; gone when the creature comes into
/// sight, or `heard_linger_s` after it was last heard. Nothing while its senses have no field.
fn hear(ctx: &ReducerContext, id: u32, viewer: Identity, here: (f32, f32), seen: &HashSet<u32>, now: u64) {
    let now_heard = heard(ctx, id, here, seen, now);
    let rows: Vec<Heard> = ctx.db.heard().viewer().filter(viewer).collect();
    if now_heard.is_empty() && rows.is_empty() {
        return;
    }
    let laws = common::laws(ctx);
    let linger = (laws.heard_linger_s * 1000.0) as u64;
    let mut current: HashSet<u32> = HashSet::new();
    let mut salt = None;
    for c in &now_heard {
        current.insert(c.id);
        HEARD_LAST.with(|h| h.borrow_mut().insert((id, c.id), now));
        let bearing = living_rules::sight::compass8(here, c.pos);
        let band = living_rules::sight::heard_band(c.dist, laws.heard_near_m, laws.heard_close_m);
        match rows.iter().find(|r| r.target == c.id && r.listener == id) {
            Some(r) if r.bearing == bearing && r.band == band => {}
            Some(r) => {
                ctx.db.heard().key().update(Heard { bearing, band, ..r.clone() });
            }
            None => {
                let salt = *salt.get_or_insert_with(|| hear_salt(ctx));
                let key = heard_key(salt, id, c.id, now);
                if ctx.db.heard().key().find(key).is_none() {
                    ctx.db.heard().insert(Heard { key, viewer, listener: id, target: c.id, kind: heard_kind(ctx, &c.kind), bearing, band, since_ms: now });
                }
            }
        }
    }
    for r in rows.iter().filter(|r| !current.contains(&r.target)) {
        let last = HEARD_LAST.with(|h| *h.borrow_mut().entry((id, r.target)).or_insert(now));
        if r.listener != id || seen.contains(&r.target) || now.saturating_sub(last) >= linger {
            ctx.db.heard().key().delete(r.key);
            HEARD_LAST.with(|h| h.borrow_mut().remove(&(id, r.target)));
        }
    }
}

/// A creature's health moved (a blow, a heal, the 1 Hz band follow-up): the players who
/// perceive it see its band follow, and exact health where the law grants it: its own player
/// at once, the others at their next frame (`frame.rs`).
pub fn health_moved(ctx: &ReducerContext, id: u32, now: u64) {
    crate::frame::hurt(id);
    let rows: Vec<Projected> = ctx.db.projected().body().filter(id).filter(|p| p.own).collect();
    if rows.is_empty() {
        return;
    }
    let Some(v) = ctx.db.vitals().id().find(id) else { return };
    let hp = common::needs(&v, now).hp;
    let band = living_rules::combat::band(hp, v.max_hp);
    for mut p in rows {
        let exact = if p.hp >= 0.0 { hp.max(0.0).round() } else { p.hp };
        let b = if p.band == 255 { 255 } else { band };
        if b != p.band || exact != p.hp {
            p.band = b;
            p.hp = exact;
            ctx.db.projected().id().update(p);
        }
    }
}

/// A player's character died: it perceives nothing any more.
pub fn forget(ctx: &ReducerContext, id: u32, viewer: Identity) {
    crate::frame::forget(ctx, id);
    for p in ctx.db.perceived().viewer().filter(viewer).map(|p| p.id).collect::<Vec<_>>() {
        ctx.db.perceived().id().delete(p);
    }
    for p in ctx.db.motion_seen().viewer().filter(viewer).map(|p| p.id).collect::<Vec<_>>() {
        ctx.db.motion_seen().id().delete(p);
    }
    for p in ctx.db.fighter_seen().viewer().filter(viewer).map(|p| p.id).collect::<Vec<_>>() {
        ctx.db.fighter_seen().id().delete(p);
    }
    for p in ctx.db.doing_seen().viewer().filter(viewer).map(|p| p.id).collect::<Vec<_>>() {
        ctx.db.doing_seen().id().delete(p);
    }
    for p in ctx.db.projected().viewer().filter(viewer).map(|p| p.id).collect::<Vec<_>>() {
        ctx.db.projected().id().delete(p);
    }
    for k in ctx.db.heard().viewer().filter(viewer).map(|h| h.key).collect::<Vec<_>>() {
        ctx.db.heard().key().delete(k);
    }
    HEARD_LAST.with(|h| h.borrow_mut().retain(|(l, _), _| *l != id));
}

/// A character is no longer seen by anyone (it died): its rows in others' sets go, its motion
/// in the same update (a body leaves `seen_bodies` with its death's feed row).
pub fn gone(ctx: &ReducerContext, id: u32) {
    let rows: Vec<Projected> = ctx.db.projected().body().filter(id).collect();
    if rows.is_empty() {
        return;
    }
    let players: HashMap<Identity, u32> = crate::combat::humans(ctx).into_iter().map(|(c, who)| (who, c)).collect();
    for p in rows {
        if let Some(viewer) = players.get(&p.viewer) {
            ctx.db.motion_seen().id().delete(crate::frame::key(*viewer, id));
            ctx.db.fighter_seen().id().delete(crate::frame::key(*viewer, id));
            ctx.db.doing_seen().id().delete(crate::frame::key(*viewer, id));
        }
        ctx.db.projected().id().delete(p.id);
    }
}

/// Reveals that ended are dropped (once a second; an index range of the ended ones).
pub fn expire(ctx: &ReducerContext, now: u64) {
    for id in ctx.db.reveal().until_ms().filter(..=now).map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.reveal().id().delete(id);
    }
}

/// `observer` learns `known`'s name (they told it). True when it is news.
pub fn introduce(ctx: &ReducerContext, observer: u32, known: u32, now: u64) -> bool {
    if observer == known || ctx.db.acquaintance().by_pair().filter((observer, known)).next().is_some() {
        return false;
    }
    ctx.db.acquaintance().insert(Acquaintance { id: 0, observer, known, since_ms: now });
    knowledge_changed(Some(observer));
    true
}

/// `dead` dies a member of `community`: the others knew their name through it (`knows_name`
/// reads living membership, which goes with the dead), so they keep it as an acquaintance and
/// still name them in the death percept, at the remains and in memory. Call it before the
/// membership row goes. One row per other member, gone when that member dies (`forget_dead`).
pub fn remember_member(ctx: &ReducerContext, dead: u32, community: u32, now: u64) {
    for m in ctx.db.membership().community().filter(community).map(|m| m.member).collect::<Vec<_>>() {
        if m != dead {
            introduce(ctx, m, dead, now);
        }
    }
}

/// A skill use reveals `what` of `target` to `observer` for `secs` seconds.
pub fn reveal(ctx: &ReducerContext, observer: u32, target: u32, what: &str, secs: f32, now: u64) {
    let until_ms = now + (secs.max(0.0) * 1000.0) as u64;
    match ctx.db.reveal().observer().filter(observer).find(|r| r.target == target && r.what == what) {
        Some(mut r) => {
            r.until_ms = r.until_ms.max(until_ms);
            ctx.db.reveal().id().update(r);
        }
        None => {
            ctx.db.reveal().insert(Reveal { id: 0, observer, target, what: what.into(), until_ms });
        }
    }
}

// ---- views --------------------------------------------------------------------------------

/// The character this connection's person plays now, or the one that died last until they
/// join again (`player`). Not a character the world's minds hold while its person is away
/// (`ai`), and not minds' characters: a mind service's identity reads the tables themselves.
/// A person with no `player` row yet (a world from before the table) is found by the old
/// walk over every character it controlled, until its next reducer call writes the row.
pub(crate) fn current(ctx: &ViewContext) -> Option<Character> {
    let me = ctx.sender();
    match ctx.db.player().identity().find(me) {
        Some(p) => ctx.db.character().id().find(p.character).filter(|c| c.controller == me && !c.ai),
        None => ctx.db.character().controller().filter(me).filter(|c| !c.ai).max_by_key(|c| (c.alive, c.id)),
    }
}

/// The current character while it lives.
pub(crate) fn living(ctx: &ViewContext) -> Option<Character> {
    current(ctx).filter(|c| c.alive)
}

/// The caller's living character for a player reducer (`player`; a person with no row yet is
/// found by the old walk, and the row is written).
pub fn player_character(ctx: &ReducerContext) -> Option<Character> {
    let me = ctx.sender();
    if let Some(p) = ctx.db.player().identity().find(me) {
        return ctx.db.character().id().find(p.character).filter(|c| c.alive && !c.ai && c.controller == me);
    }
    let c = ctx.db.character().controller().filter(me).find(|c| c.alive && !c.ai)?;
    set_player(ctx, me, c.id);
    Some(c)
}

/// `who` plays `character` now.
pub fn set_player(ctx: &ReducerContext, who: Identity, character: u32) {
    let row = Player { identity: who, character };
    if let Some(old) = ctx.db.player().identity().find(who) {
        // The character played before: its outcome rows have no reader any more.
        if old.character != character {
            crate::outcomes::forget(ctx, old.character);
        }
        ctx.db.player().identity().update(row);
    } else {
        ctx.db.player().insert(row);
    }
}

/// What I perceive of each creature in my scene, mine included (the projections).
fn projections(ctx: &ViewContext) -> impl Iterator<Item = Projected> + '_ {
    ctx.db.projected().viewer().filter(ctx.sender())
}

/// How the bodies in my scene move (the narrow stream): the others, as my last frame showed
/// them (`motion_seen`, `frame.rs`). My own body is `my_body`, so my own moves and steering
/// re-run one row, not my whole scene.
/// Someone my character knows by name (`my_known_names`; owner-known, 2026-11-12).
#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub struct KnownName {
    pub id: u32,
    pub name: String,
}

/// Whom my current character knows by name, with the name: itself, its parents, its children and
/// their other parent, its community, and whoever told it their name (`acquaintance`, which also
/// keeps the names of its community's dead). The same sources as `knows_name`, read by index. A
/// client names a structure's owner from it under the world's `owner_shown` law ("Agnes
/// Fenner's house" to one who knows her, else "a house"), as the authority tells minds.
#[spacetimedb::view(accessor = my_known_names, public, primary_key = id)]
pub fn my_known_names(ctx: &ViewContext) -> Vec<KnownName> {
    let Some(me) = current(ctx) else { return Vec::new() };
    let mut ids = std::collections::BTreeSet::new();
    ids.insert(me.id);
    for p in [me.parent_a, me.parent_b] {
        if p != 0 {
            ids.insert(p);
        }
    }
    for child in ctx.db.character().parent_a().filter(me.id).chain(ctx.db.character().parent_b().filter(me.id)) {
        ids.insert(child.id);
        for other in [child.parent_a, child.parent_b] {
            if other != 0 {
                ids.insert(other);
            }
        }
    }
    ids.extend(ctx.db.acquaintance().observer().filter(me.id).map(|a| a.known));
    if let Some(m) = ctx.db.membership().member().find(me.id) {
        ids.extend(ctx.db.membership().community().filter(m.community).map(|x| x.member));
    }
    ids.into_iter().filter_map(|i| ctx.db.character().id().find(i).map(|c| KnownName { id: c.id, name: c.name })).collect()
}

#[spacetimedb::view(accessor = seen_bodies, public, primary_key = id)]
pub fn seen_bodies(ctx: &ViewContext) -> Vec<Moving> {
    ctx.db.motion_seen().viewer().filter(ctx.sender()).map(|m| m.moving()).collect()
}

/// How my own living character's body moves, as it is.
#[spacetimedb::view(accessor = my_body, public, primary_key = id)]
pub fn my_body(ctx: &ViewContext) -> Vec<Moving> {
    living(ctx).and_then(|c| ctx.db.body().id().find(c.id)).map(|b| Moving::from(&b)).into_iter().collect()
}

/// What I perceive of the creatures in my scene, mine included: their records through the
/// `perceived_of` law (name or label, kind, stage, build and dress, health as I can tell it).
/// It reads only my `projected` rows, so it re-runs when what I perceive of someone changes.
#[spacetimedb::view(accessor = seen_characters, public, primary_key = id)]
pub fn seen_characters(ctx: &ViewContext) -> Vec<SeenCharacter> {
    projections(ctx)
        .map(|p| SeenCharacter { id: p.body, name: p.name, label: p.label, kind: p.kind, stage: p.stage, folk: p.folk, style: p.style, own: p.own, band: p.band, hp: p.hp, max_hp: p.max_hp })
        .collect()
}

/// How the fighters in my scene look: the move under way, and the health band as I perceive
/// it (the projection's; 255 when not perceived), as my last frame showed them (`fighter_seen`,
/// `frame.rs`). Mine is `my_fighter`.
#[spacetimedb::view(accessor = seen_fighters, public, primary_key = id)]
pub fn seen_fighters(ctx: &ViewContext) -> Vec<Fighter> {
    ctx.db.fighter_seen().viewer().filter(ctx.sender()).map(|f| f.fighter).collect()
}

/// My own living character's move under way and health band, as they are.
#[spacetimedb::view(accessor = my_fighter, public, primary_key = id)]
pub fn my_fighter(ctx: &ViewContext) -> Vec<Fighter> {
    living(ctx).and_then(|c| ctx.db.fighter().id().find(c.id)).into_iter().collect()
}

/// What the creatures in my scene are visibly doing, as my last frame showed them
/// (`doing_seen`, `frame.rs`). Mine is `my_doing`.
#[spacetimedb::view(accessor = seen_doing, public, primary_key = id)]
pub fn seen_doing(ctx: &ViewContext) -> Vec<Doing> {
    ctx.db.doing_seen().viewer().filter(ctx.sender()).map(|d| d.doing).collect()
}

/// What my own living character is visibly doing, as it is.
#[spacetimedb::view(accessor = my_doing, public, primary_key = id)]
pub fn my_doing(ctx: &ViewContext) -> Vec<Doing> {
    living(ctx).and_then(|c| ctx.db.doing().id().find(c.id)).into_iter().collect()
}

/// What a player hears but cannot see (a row of `heard_sounds`): what it sounds like, one of
/// eight compass ways, how far as a band, and a key that stays the same while the sound lasts.
/// Never who it is.
#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub struct HeardSound {
    /// Stable while the sound lasts; derived from the listener, the creature and a secret salt
    /// that rotates every few minutes, so it names no one.
    pub key: u64,
    /// "person", "deer", "wolf" or "creature".
    pub kind: String,
    /// 0 north, then clockwise: 1 north-east … 7 north-west.
    pub bearing: u8,
    /// 0 near (within `heard_near_m`), 1 close (`heard_close_m`), 2 far (out to hearing).
    pub band: u8,
}

/// What my character hears and does not see now (only while the world's `fov_on` law gives
/// sight a field). Reads only my `heard` rows.
#[spacetimedb::view(accessor = heard_sounds, public, primary_key = key)]
pub fn heard_sounds(ctx: &ViewContext) -> Vec<HeardSound> {
    ctx.db.heard().viewer().filter(ctx.sender()).map(|h| HeardSound { key: h.key, kind: h.kind, bearing: h.bearing, band: h.band }).collect()
}

/// My current character, alive, or the one that died last until I join again (the death
/// screen). Not every character I ever had.
#[spacetimedb::view(accessor = my_characters, public, primary_key = id)]
pub fn my_characters(ctx: &ViewContext) -> Vec<Character> {
    current(ctx).into_iter().collect()
}

/// My living character's exact needs and health.
#[spacetimedb::view(accessor = my_vitals, public, primary_key = id)]
pub fn my_vitals(ctx: &ViewContext) -> Vec<Vitals> {
    living(ctx).and_then(|c| ctx.db.vitals().id().find(c.id)).into_iter().collect()
}

/// What my living character senses now: how far it sees and hears, and how its sight narrows
/// away from facing (the `senses` law with all its facts; `character_senses`). One point
/// lookup; it re-runs only when a value changes (nightfall, dawn, a torch), not every tick.
#[spacetimedb::view(accessor = my_senses, public, primary_key = id)]
pub fn my_senses(ctx: &ViewContext) -> Vec<CharacterSenses> {
    living(ctx).and_then(|c| ctx.db.character_senses().id().find(c.id)).into_iter().collect()
}

/// How my acts and my death came out lately, in codes (`act_outcome`, one row per line of
/// `my_experience` that tells one, keyed by its id): of my living character, or of the one that
/// died last until I join again (the death screen). One btree point read by character.
#[spacetimedb::view(accessor = my_act_outcomes, public, primary_key = id)]
pub fn my_act_outcomes(ctx: &ViewContext) -> Vec<ActOutcome> {
    current(ctx).map(|c| ctx.db.act_outcome().observer().filter(c.id).collect()).unwrap_or_default()
}

/// What reached my character's senses lately: the newest `frame::LINES_SHOWN` lines of my
/// living character, released at its frames (`line_seen`, `frame.rs`), or, while none lives,
/// of the one that died last (the death screen). Not every dead character's: a player who
/// dies often would re-read all of their windows at each line.
#[spacetimedb::view(accessor = my_experience, public, primary_key = id)]
pub fn my_experience(ctx: &ViewContext) -> Vec<Experience> {
    current(ctx).map(|c| ctx.db.line_seen().by_observer_shown().filter((c.id, true)).map(|l| l.line).collect()).unwrap_or_default()
}

/// The places my living characters know.
#[spacetimedb::view(accessor = my_places, public, primary_key = id)]
pub fn my_places(ctx: &ViewContext) -> Vec<Place> {
    living(ctx).map(|c| ctx.db.place().actor().filter(c.id).collect()).unwrap_or_default()
}

/// What my living characters carry.
#[spacetimedb::view(accessor = my_inventory, public, primary_key = id)]
pub fn my_inventory(ctx: &ViewContext) -> Vec<Inventory> {
    living(ctx).map(|c| ctx.db.inventory().owner().filter(c.id as u64).collect()).unwrap_or_default()
}

/// What my living characters know how to do.
#[spacetimedb::view(accessor = my_know_how, public, primary_key = id)]
pub fn my_know_how(ctx: &ViewContext) -> Vec<KnowHow> {
    living(ctx).map(|c| ctx.db.know_how().actor().filter(c.id).collect()).unwrap_or_default()
}

/// The trade offers addressed to my living character, and the one it has made (a character
/// has at most one standing offer). Two point reads on `trade_offer` (`to`, `from`), so it
/// re-runs only when an offer to or from me is written or goes.
#[spacetimedb::view(accessor = my_offers, public, primary_key = id)]
pub fn my_offers(ctx: &ViewContext) -> Vec<MyOffer> {
    let Some(c) = living(ctx) else { return Vec::new() };
    let row = |o: TradeOffer, incoming: bool| MyOffer {
        id: o.id,
        incoming,
        from: o.from,
        to: o.to,
        give_item: o.give_item,
        give_qty: o.give_qty,
        want_item: o.want_item,
        want_qty: o.want_qty,
        at_ms: o.at_ms,
        until_ms: o.until_ms,
    };
    let to_me = ctx.db.trade_offer().to().filter(c.id).map(|o| row(o, true));
    let mine = ctx.db.trade_offer().from().filter(c.id).filter(|o| o.to != c.id).map(|o| row(o, false));
    to_me.chain(mine).collect()
}
