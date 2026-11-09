//! What a human player's client may receive (docs/PERCEPTION.md): what the player's character
//! perceives now, and the character's own state.
//!
//! - **The perceived set.** Every [`SWEEP_MS`] the authority works out, for each living
//!   character a person controls, which creatures it can see: within its sight (day, night, or
//!   night with a torch: `common::sight_for`, the radius minds perceive by) and with a clear
//!   sight line (`Map::sight_clear`: walls, rock and shut gates hide). A creature already seen
//!   stays seen until it is [`KEEP_MARGIN`] beyond sight, so one at the edge does not flicker.
//!   The answer is kept as `perceived` rows (private), written only when someone comes into or
//!   goes out of sight.
//! - **The views.** `seen_*` return the rows of the perceived creatures and of the player's own
//!   living character (its body is part of the scene). `my_*` return the player's own state.
//!   Every view reads through point lookups only (`character.controller`, `perceived.viewer`,
//!   primary keys, `*.actor`, `inventory.owner`, `experience.observer`): 2.14.1 records a point
//!   lookup as that key in the view's read set, but any range scan as a read of the whole table,
//!   which would re-run the view on every write to it.
//! - **The moving-body stream** is the narrow [`Motion`] row: what a client draws, without the
//!   path, the chunk or the kind (a creature's kind is on its `character` row).
//!
//! Spatial perception is enforced here, on the authority. The views are re-run by the server,
//! inside the transaction that wrote what they read, whenever a row they read changes, so the
//! cost grows with players × updates of what each perceives (measured in docs/PERCEPTION.md).

use crate::common::{self, pos};
use crate::tables::*;
use spacetimedb::{Identity, ReducerContext, SpacetimeType, Table, ViewContext};
use std::cell::RefCell;
use std::collections::{HashMap, HashSet};

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

thread_local! {
    /// When each player's character was last swept (module cache; a fresh instance sweeps
    /// everyone once, staggered).
    static LAST: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
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

/// Work out one player's perceived set now (also right after a join).
pub fn sweep_now(ctx: &ReducerContext, id: u32, viewer: Identity, now: u64) {
    LAST.with(|l| l.borrow_mut().insert(id, now));
    sweep_one(ctx, id, viewer, &common::world(ctx), &common::map(ctx), now);
}

fn sweep_one(ctx: &ReducerContext, id: u32, viewer: Identity, w: &World, map: &living_rules::map::Map, now: u64) {
    let Some(b) = ctx.db.body().id().find(id) else { return };
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
        if c.dist <= reach && map.sight_clear(here, c.pos) {
            seen.insert(c.id);
        }
    }
    for p in &rows {
        if !seen.contains(&p.body) {
            ctx.db.perceived().id().delete(p.id);
        }
    }
    for body in seen.difference(&had) {
        ctx.db.perceived().insert(Perceived { id: 0, viewer, body: *body, since_ms: now });
    }
}

/// A player's character died: it perceives nothing any more.
pub fn forget(ctx: &ReducerContext, viewer: Identity) {
    for p in ctx.db.perceived().viewer().filter(viewer).map(|p| p.id).collect::<Vec<_>>() {
        ctx.db.perceived().id().delete(p);
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

/// How the bodies in my scene move (the narrow stream; my own body included).
#[spacetimedb::view(accessor = seen_bodies, public, primary_key = id)]
pub fn seen_bodies(ctx: &ViewContext) -> Vec<Motion> {
    scene(ctx).into_iter().filter_map(|id| ctx.db.body().id().find(id)).map(|b| Motion::from(&b)).collect()
}

/// Who the creatures in my scene are (name, kind, life stage; mine included).
#[spacetimedb::view(accessor = seen_characters, public, primary_key = id)]
pub fn seen_characters(ctx: &ViewContext) -> Vec<Character> {
    scene(ctx).into_iter().filter_map(|id| ctx.db.character().id().find(id)).collect()
}

/// How the fighters in my scene look: health band and the move under way.
#[spacetimedb::view(accessor = seen_fighters, public, primary_key = id)]
pub fn seen_fighters(ctx: &ViewContext) -> Vec<Fighter> {
    scene(ctx).into_iter().filter_map(|id| ctx.db.fighter().id().find(id)).collect()
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
