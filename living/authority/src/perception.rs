//! What a character perceives (docs/PERCEPTION.md): the one sight rule, what an observer
//! perceives of another character, and what a human player's client may receive.
//!
//! - **The sight rule** ([`in_sight`]): within the observer's sight (day, night, or night with a
//!   torch: `common::sight_for`) and with a clear sight line (`Map::sight_clear`: walls, rock and
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
//!   until it is [`KEEP_MARGIN`] beyond sight, so one at the edge does not flicker. The answer
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
use living_rules::script::{Precision, Regard, RegardIn, Scripts};
use spacetimedb::{Identity, ReducerContext, SpacetimeType, Table, ViewContext};
use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::rc::Rc;

/// How often each player's perceived set is worked out again (ms), staggered by character.
pub const SWEEP_MS: u64 = 200;
/// Tiles beyond sight a creature already seen stays seen.
pub const KEEP_MARGIN: f32 = 1.0;

/// A body's current motion segment as clients draw it (see `Body`): from `(x, y)` facing
/// `heading` at `t_ms`, moving at velocity `(vx, vy)`, turning at `turn` rad/s for `turn_s`
/// seconds, until `next_ms` (the segment's end, when steering looks again; `u64::MAX` at
/// rest). `speed` is the cruising speed of the movement under way, which tells its gait
/// (a walk, or a run at the rules' `run_speed` times a walk). About 52 B against the `body`
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

// ---- the one sight rule ------------------------------------------------------------------

/// Whether an eye at `eye` sees `at`, `dist` away, with sight `sight`: within it, and no
/// rock, wall or shut gate between (`Map::sight_clear`). Players' perceived sets, minds'
/// percepts and scenes, behaviour graphs and the combat feed all see by this.
pub fn in_sight(map: &Map, eye: (f32, f32), at: (f32, f32), dist: f32, sight: f32) -> bool {
    dist <= sight && map.sight_clear(eye, at)
}

/// Whether character `id`, standing at `eye`, sees `at` now (its own sight: day, night or a
/// torch).
pub fn sees(ctx: &ReducerContext, id: u32, eye: (f32, f32), at: (f32, f32), w: &World, map: &Map, now: u64) -> bool {
    in_sight(map, eye, at, common::dist(eye, at), common::sight_for(ctx, id, w, now))
}

/// The creatures a character at `at` with sight `sight` sees (itself excluded), nearest first.
pub fn visible(ctx: &ReducerContext, id: u32, at: (f32, f32), sight: f32, now: u64) -> Vec<NearCreature> {
    let map = common::map(ctx);
    common::creatures_near(ctx, at, sight, now).into_iter().filter(|c| c.id != id && map.sight_clear(at, c.pos)).collect()
}

/// The largest sight anyone has now (for gathering onlookers before each one's own test).
pub fn widest_sight(ctx: &ReducerContext, w: &World, now: u64) -> f32 {
    common::sight(ctx, w, now).max(common::laws(ctx).sight_torch)
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
/// someone who told it their name (`acquaintance`).
pub fn knows_name(ctx: &ReducerContext, observer: &Character, target: &Character) -> bool {
    let (o, t) = (observer.id, target.id);
    if o == t || observer.parent_a == t || observer.parent_b == t || target.parent_a == o || target.parent_b == o {
        return true;
    }
    if ctx.db.acquaintance().by_pair().filter((o, t)).next().is_some() || ctx.db.relation().by_pair().filter((o, t)).next().is_some() {
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
    let w = common::world(ctx);
    let mut knows = common::knows(ctx, observer.id);
    knows.sort();
    let input = RegardIn {
        observer_kind: observer.kind.clone(),
        knows,
        target_kind: target.kind.clone(),
        known: knows_name(ctx, observer, target),
        revealed: revealed(ctx, observer.id, target.id, now),
        own: observer.id == target.id,
        night: common::night(&w, now),
    };
    regard_of(&common::scripts(ctx), input)
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
    let (hp, max_hp) = ctx.db.vitals().id().find(target.id).map(|v| (common::needs(&v, now).hp, v.max_hp)).unwrap_or((0.0, 0.0));
    let (band, hp, max_hp) = match r.health {
        Precision::None => (255, -1.0, -1.0),
        Precision::Band => (living_rules::combat::band(hp, max_hp), -1.0, -1.0),
        Precision::Exact => (living_rules::combat::band(hp, max_hp), hp.max(0.0).round(), max_hp.round()),
    };
    let label = if r.name { target.name.clone() } else { stranger(&target.kind, target.stage) };
    Projection { name: if r.name { target.name.clone() } else { String::new() }, label, kind: target.kind.clone(), stage: target.stage, folk, style, band, hp, max_hp }
}

/// How `observer` refers to `id` (the projection's label).
pub fn label(ctx: &ReducerContext, observer: &Character, id: u32, now: u64) -> String {
    match ctx.db.character().id().find(id) {
        Some(t) => {
            if regard(ctx, observer, &t, now).name {
                t.name
            } else {
                stranger(&t.kind, t.stage)
            }
        }
        None => "someone".into(),
    }
}

impl Projection {
    fn into_row(self, viewer: Identity, body: u32, own: bool, id: u64) -> Projected {
        Projected { id, viewer, body, own, name: self.name, label: self.label, kind: self.kind, stage: self.stage, folk: self.folk, style: self.style, band: self.band, hp: self.hp, max_hp: self.max_hp }
    }

    fn same_as(&self, p: &Projected) -> bool {
        self.name == p.name && self.label == p.label && self.kind == p.kind && self.stage == p.stage && self.folk == p.folk && self.style == p.style && self.band == p.band && self.hp == p.hp && self.max_hp == p.max_hp
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
        l.retain(|id, _| humans.iter().any(|(h, _)| h == id));
        PROJECTED.with(|p| p.borrow_mut().retain(|id, _| humans.iter().any(|(h, _)| h == id)));
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
    LAST.with(|l| l.borrow_mut().insert(id, now));
    PROJECTED.with(|p| p.borrow_mut().remove(&id));
    sweep_one(ctx, id, viewer, &common::world(ctx), &common::map(ctx), now);
}

fn sweep_one(ctx: &ReducerContext, id: u32, viewer: Identity, w: &World, map: &Map, now: u64) {
    let Some(b) = ctx.db.body().id().find(id) else { return };
    let Some(me) = ctx.db.character().id().find(id) else { return };
    let here = pos(&b, now);
    let sight = common::sight_for(ctx, id, w, now);
    let rows: Vec<Perceived> = ctx.db.perceived().viewer().filter(viewer).collect();
    let had: HashSet<u32> = rows.iter().map(|p| p.body).collect();
    let mut seen: HashSet<u32> = HashSet::new();
    for c in common::creatures_near(ctx, here, sight + KEEP_MARGIN, now) {
        if c.id == id {
            continue;
        }
        let reach = if had.contains(&c.id) { sight + KEEP_MARGIN } else { sight };
        if in_sight(map, here, c.pos, c.dist, reach) {
            seen.insert(c.id);
        }
    }
    for p in &rows {
        if !seen.contains(&p.body) {
            ctx.db.perceived().id().delete(p.id);
        }
    }
    let entered: Vec<u32> = seen.difference(&had).copied().collect();
    let left = had.len() + entered.len() != seen.len();
    for body in &entered {
        ctx.db.perceived().insert(Perceived { id: 0, viewer, body: *body, since_ms: now });
        // An instinct-only resident who sees the player's character back keeps that it came
        // into view, for the mind it may get (`woken`).
        if let Some(r) = ctx.db.character().id().find(*body).filter(|r| crate::woken::resident(ctx, r) && crate::woken::rings_kept(ctx)) {
            if let Some(eye) = ctx.db.body().id().find(*body).map(|rb| pos(&rb, now)) {
                if in_sight(map, eye, here, common::dist(eye, here), common::sight_for(ctx, *body, w, now)) {
                    crate::woken::sighted(ctx, &r, id, here, now);
                }
            }
        }
    }
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
}

/// A creature's health moved (a blow, a heal, the 1 Hz band follow-up): the players who
/// perceive it see its band follow, and exact health where the law grants it.
pub fn health_moved(ctx: &ReducerContext, id: u32, now: u64) {
    let rows: Vec<Projected> = ctx.db.projected().body().filter(id).collect();
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
pub fn forget(ctx: &ReducerContext, viewer: Identity) {
    for p in ctx.db.perceived().viewer().filter(viewer).map(|p| p.id).collect::<Vec<_>>() {
        ctx.db.perceived().id().delete(p);
    }
    for p in ctx.db.projected().viewer().filter(viewer).map(|p| p.id).collect::<Vec<_>>() {
        ctx.db.projected().id().delete(p);
    }
}

/// A character is no longer seen by anyone (it died): its rows in others' sets go.
pub fn gone(ctx: &ReducerContext, id: u32) {
    for p in ctx.db.projected().body().filter(id).map(|p| p.id).collect::<Vec<_>>() {
        ctx.db.projected().id().delete(p);
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

/// The characters this connection's person controls (not minds' characters: a mind service's
/// identity reads the tables themselves).
fn mine(ctx: &ViewContext) -> impl Iterator<Item = Character> + '_ {
    ctx.db.character().controller().filter(ctx.sender()).filter(|c| !c.ai)
}

/// The creatures in the scene: my living character, then everyone it perceives.
fn scene(ctx: &ViewContext) -> Vec<u32> {
    let mut ids: Vec<u32> = mine(ctx).filter(|c| c.alive).map(|c| c.id).collect();
    for p in ctx.db.perceived().viewer().filter(ctx.sender()) {
        if !ids.contains(&p.body) {
            ids.push(p.body);
        }
    }
    ids
}

/// What I perceive of each creature in my scene, mine included (the projections).
fn projections(ctx: &ViewContext) -> impl Iterator<Item = Projected> + '_ {
    ctx.db.projected().viewer().filter(ctx.sender())
}

/// How the bodies in my scene move (the narrow stream; my own body included).
#[spacetimedb::view(accessor = seen_bodies, public, primary_key = id)]
pub fn seen_bodies(ctx: &ViewContext) -> Vec<Motion> {
    scene(ctx).into_iter().filter_map(|id| ctx.db.body().id().find(id)).map(|b| Motion::from(&b)).collect()
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
/// it (the projection's; 255 when not perceived).
#[spacetimedb::view(accessor = seen_fighters, public, primary_key = id)]
pub fn seen_fighters(ctx: &ViewContext) -> Vec<Fighter> {
    projections(ctx).filter_map(|p| ctx.db.fighter().id().find(p.body).map(|f| Fighter { band: p.band, ..f })).collect()
}

/// What the creatures in my scene are visibly doing.
#[spacetimedb::view(accessor = seen_doing, public, primary_key = id)]
pub fn seen_doing(ctx: &ViewContext) -> Vec<Doing> {
    scene(ctx).into_iter().filter_map(|id| ctx.db.doing().id().find(id)).collect()
}

/// My characters, the dead included (the death screen).
#[spacetimedb::view(accessor = my_characters, public, primary_key = id)]
pub fn my_characters(ctx: &ViewContext) -> Vec<Character> {
    mine(ctx).collect()
}

/// My living characters' exact needs and health.
#[spacetimedb::view(accessor = my_vitals, public, primary_key = id)]
pub fn my_vitals(ctx: &ViewContext) -> Vec<Vitals> {
    mine(ctx).filter(|c| c.alive).filter_map(|c| ctx.db.vitals().id().find(c.id)).collect()
}

/// What reached my characters' senses (the bounded per-character window), the dead included.
#[spacetimedb::view(accessor = my_experience, public, primary_key = id)]
pub fn my_experience(ctx: &ViewContext) -> Vec<Experience> {
    mine(ctx).flat_map(|c| ctx.db.experience().observer().filter(c.id).collect::<Vec<_>>()).collect()
}

/// The places my living characters know.
#[spacetimedb::view(accessor = my_places, public, primary_key = id)]
pub fn my_places(ctx: &ViewContext) -> Vec<Place> {
    mine(ctx).filter(|c| c.alive).flat_map(|c| ctx.db.place().actor().filter(c.id).collect::<Vec<_>>()).collect()
}

/// What my living characters carry.
#[spacetimedb::view(accessor = my_inventory, public, primary_key = id)]
pub fn my_inventory(ctx: &ViewContext) -> Vec<Inventory> {
    mine(ctx).filter(|c| c.alive).flat_map(|c| ctx.db.inventory().owner().filter(c.id as u64).collect::<Vec<_>>()).collect()
}

/// What my living characters know how to do.
#[spacetimedb::view(accessor = my_know_how, public, primary_key = id)]
pub fn my_know_how(ctx: &ViewContext) -> Vec<KnowHow> {
    mine(ctx).filter(|c| c.alive).flat_map(|c| ctx.db.know_how().actor().filter(c.id).collect::<Vec<_>>()).collect()
}
