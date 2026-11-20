//! Known ground and remembered gates (docs/MOVEMENT_MIND.md, step 3).
//!
//! - **Marking.** At each look (the 900 ms noticing cadence, every character, a person's too),
//!   the 4 m cells within the ground it sees (`ground_sight_m` by day, its own sight at night;
//!   the one sight rule, facing included when the field is on) that it has not marked are
//!   marked, nearest first, at most `known_cells_pass` a look (0: no cap; the rest come with the
//!   next looks while they are in view). Changed blocks are kept in module memory and written at
//!   most every `FLUSH_MS` per character: a lost buffer only forgets cells that are seen again.
//! - **Gates.** A gate in view is remembered open or shut (`remembered`), written when that
//!   changes.
//! - **Edits.** A terrain tile changed after genesis is logged (`ground_edit`) with its byte
//!   before, so a character's belief of a chunk is the map as it was when seen.
//! - **Belief.** `belief` builds a `living_rules::known::Belief` that reads only a character's
//!   own rows (and the map under its seen cells), for the walking plan.

use crate::common;
use crate::tables::*;
use living_rules::known::{self as kn, Belief, Edit, Known};
use spacetimedb::{ReducerContext, Table};
use std::cell::{Cell, RefCell};
use std::collections::{HashMap, VecDeque};
use std::rc::Rc;

/// Minimum interval between an actor's known-ground row writes.
const FLUSH_MS: u64 = 5_500;
/// Most remembered things a character keeps (oldest seen go first).
const REMEMBER_LIMIT: usize = 512;

struct Pending {
    blocks: HashMap<u32, Known>,
    dirty: VecDeque<u32>,
    flushed_ms: u64,
}

thread_local! {
    static SEARCH: RefCell<HashMap<u32, (SearchKey, kn::Search)>> = RefCell::new(HashMap::new());
    static REVISION: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    static PENDING: RefCell<HashMap<u32, Pending>> = RefCell::new(HashMap::new());
    static RINGS: RefCell<HashMap<u32, Rc<Vec<(i32, i32)>>>> = RefCell::new(HashMap::new());
    /// The map's edit count (the newest `ground_edit` id), once read.
    static EPOCH: Cell<Option<u32>> = const { Cell::new(None) };
}

/// The map's edit count now.
pub fn epoch(ctx: &ReducerContext) -> u32 {
    if let Some(e) = EPOCH.with(|e| e.get()) {
        return e;
    }
    let e = ctx.db.ground_edit().iter().map(|r| r.id as u32).max().unwrap_or(0);
    EPOCH.with(|c| c.set(Some(e)));
    e
}

/// Log a terrain tile's change (`common::set_tile`): its byte before.
pub fn record_edit(ctx: &ReducerContext, x: i32, y: i32, before: u8, now: u64) {
    let (chunk, _) = kn::cell_of(x, y);
    let tile = ((y as u32 % living_rules::map::CHUNK) * living_rules::map::CHUNK + x as u32 % living_rules::map::CHUNK) as u16;
    let row = ctx.db.ground_edit().insert(GroundEdit { id: 0, chunk, tile, before, at_ms: now });
    EPOCH.with(|c| c.set(Some(row.id as u32)));
}

fn ring(radius: f32) -> Rc<Vec<(i32, i32)>> {
    let key = (radius * 4.0).round() as u32;
    RINGS.with(|r| r.borrow_mut().entry(key).or_insert_with(|| Rc::new(kn::ring(radius))).clone())
}

/// A character's block: the pending copy, else its row.
fn block(ctx: &ReducerContext, id: u32, block: u32) -> Option<Known> {
    if let Some(k) = PENDING.with(|p| p.borrow().get(&id).and_then(|p| p.blocks.get(&block).cloned())) {
        return Some(k);
    }
    ctx.db.known_ground().by_actor_block().filter((id, block)).next().map(|r| Known::from_bytes(&r.cells, &r.seen_at))
}

/// How far `id` sees ground now: `ground_sight_m` by day; at night (its sight under the day's),
/// its own sight.
pub fn ground_radius(ctx: &ReducerContext, id: u32, w: &World, now: u64) -> f32 {
    let laws = common::laws(ctx);
    let senses = common::senses_of(ctx, id, w, now);
    if let Some(gaze) = senses.gaze {
        return gaze.ground.min(laws.ground_sight_m);
    }
    let sight = senses.sight;
    let day = common::scripts(ctx).reach().day;
    if sight + 0.01 < day {
        sight.min(laws.ground_sight_m)
    } else {
        laws.ground_sight_m
    }
}

/// One look: mark the ground `id` sees from `at` facing `heading`, remember the gates in view, and
/// write what changed when it is due. Returns whether the belief changed.
pub fn mark(ctx: &ReducerContext, id: u32, at: (f32, f32), heading: f32, now: u64) -> bool {
    let _span = common::span("known.mark");
    let laws = common::laws(ctx);
    let w = common::world(ctx);
    let radius = ground_radius(ctx, id, &w, now);
    if radius <= 0.0 {
        return false;
    }
    let map = common::map(ctx);
    let mut senses = common::senses_of(ctx, id, &w, now);
    senses.sight = radius;
    let offsets = ring(radius);
    let ep = epoch(ctx);
    // The blocks in reach, as the character holds them.
    let mut blocks: HashMap<u32, Option<Known>> = HashMap::new();
    let found = kn::newly_seen(
        &map,
        at,
        &offsets,
        radius,
        laws.known_cells_pass as usize,
        |chunk, bit| {
            let (b, slot) = kn::block_of(chunk);
            blocks.entry(b).or_insert_with(|| block(ctx, id, b)).as_ref().is_some_and(|k| k.has(slot, bit))
        },
        |p, d| living_rules::sight::within(at, heading, p, d, &senses, 0.0, None) && map.sight_clear(at, p),
    );
    if !found.is_empty() {
        common::diag(|| "known:cells", found.len() as u64);
        PENDING.with(|p| {
            let mut p = p.borrow_mut();
            let pend = p.entry(id).or_insert_with(|| Pending { blocks: HashMap::new(), dirty: VecDeque::new(), flushed_ms: now });
            for (chunk, bit) in &found {
                let (b, slot) = kn::block_of(*chunk);
                let k = pend.blocks.entry(b).or_insert_with(|| blocks.get(&b).cloned().flatten().unwrap_or_default());
                k.mark(slot, *bit, ep);
                if !pend.dirty.contains(&b) {
                    pend.dirty.push_back(b);
                }
            }
        });
    }
    crate::latency::nav(ctx, id, "ground_look", 0, format_args!(""));
    let changed = remember_gates(ctx, id, at, heading, &senses, &map, now) || !found.is_empty();
    if changed {
        REVISION.with(|r| *r.borrow_mut().entry(id).or_default() += 1);
    }
    flush(ctx, id, now);
    changed
}

/// Write one dirty block per interval, oldest first, while the planner reads pending observations.
fn flush(ctx: &ReducerContext, id: u32, now: u64) {
    let todo = PENDING.with(|p| {
        let mut p = p.borrow_mut();
        let pend = p.get_mut(&id)?;
        if now.saturating_sub(pend.flushed_ms) < FLUSH_MS {
            return None;
        }
        let b = pend.dirty.pop_front()?;
        pend.flushed_ms = now;
        let k = pend.blocks.remove(&b).expect("dirty block in buffer");
        Some((b, k))
    });
    if let Some((b, k)) = todo {
        common::diag(|| "known:writes", 1);
        match ctx.db.known_ground().by_actor_block().filter((id, b)).next() {
            Some(mut row) => {
                row.cells = k.cells_bytes();
                row.seen_at = k.seen_bytes();
                row.last_ms = now;
                ctx.db.known_ground().id().update(row);
            }
            None => {
                ctx.db.known_ground().insert(KnownGround { id: 0, actor: id, block: b, cells: k.cells_bytes(), seen_at: k.seen_bytes(), last_ms: now });
            }
        }
    }
}

/// Gates in view are remembered open or shut, written when that changes.
fn remember_gates(ctx: &ReducerContext, id: u32, at: (f32, f32), heading: f32, senses: &living_rules::script::Senses, map: &living_rules::map::Map, now: u64) -> bool {
    let mut changed = false;
    for (s, d) in common::structures_near(ctx, at, senses.sight) {
        if &*s.kind != "gate" {
            continue;
        }
        let p = (s.x, s.y);
        if !(living_rules::sight::within(at, heading, p, d, senses, 0.0, None) && map.sight_clear(at, p)) {
            continue;
        }
        let Some(g) = ctx.db.gate().id().find(s.id) else { continue };
        let state = u8::from(g.open);
        match ctx.db.remembered().by_observer_target().filter((id, s.id)).next() {
            Some(r) if r.state == state => {}
            Some(mut r) => {
                changed = true;
                r.state = state;
                r.seen_ms = now;
                ctx.db.remembered().id().update(r);
                crate::latency::nav(ctx, id, "gate_remembered", u64::from(s.id), format_args!("{state} {}", g.changed_ms));
            }
            None => {
                changed = true;
                ctx.db.remembered().insert(Remembered { id: 0, observer: id, target: s.id, kind: REMEMBER_GATE, x: s.x, y: s.y, state, seen_ms: now });
                crate::latency::nav(ctx, id, "gate_remembered", u64::from(s.id), format_args!("{state} {}", g.changed_ms));
                let rows: Vec<(u64, u64)> = ctx.db.remembered().observer().filter(id).map(|r| (r.seen_ms, r.id)).collect();
                if rows.len() > REMEMBER_LIMIT {
                    let mut rows = rows;
                    rows.sort_unstable();
                    for (_, rid) in &rows[..rows.len() - REMEMBER_LIMIT] {
                        ctx.db.remembered().id().delete(*rid);
                    }
                }
            }
        }
    }
    changed
}

/// `id`'s belief over the map: its own seen cells and remembered gates.
pub fn belief<'a>(ctx: &'a ReducerContext, id: u32, map: &'a living_rules::map::Map) -> Belief<'a> {
    let gates: HashMap<u32, bool> = ctx
        .db
        .remembered()
        .observer()
        .filter(id)
        .filter(|r| r.kind == REMEMBER_GATE)
        .filter_map(|r| {
            let g = ctx.db.gate().id().find(r.target)?;
            (g.x >= 0 && g.y >= 0).then(|| (g.y as u32 * map.w + g.x as u32, r.state == 1))
        })
        .collect();
    Belief::new(
        map,
        move |b| block(ctx, id, b),
        move |chunk| ctx.db.ground_edit().chunk().filter(chunk).map(|e| Edit { epoch: e.id as u32, tile: e.tile, before: e.before }).collect(),
        gates,
    )
}

#[derive(PartialEq)]
struct SearchKey {
    revision: u64,
    from: (f32, f32),
    to: (f32, f32),
    unknown_cost: f32,
    road_speed: f32,
}

/// Advance one slice of the actor's search. A missing cache after a reload starts a new search
/// from the persisted steering goal and pose.
pub fn leg(ctx: &ReducerContext, id: u32, map: &living_rules::map::Map, from: (f32, f32), to: (f32, f32)) -> Result<Option<Vec<Waypoint>>, kn::NoLeg> {
    let _span = common::span("known.leg");
    let laws = common::laws(ctx);
    let revision = REVISION.with(|r| r.borrow().get(&id).copied().unwrap_or_default());
    let key = SearchKey { revision, from, to, unknown_cost: laws.unknown_cost, road_speed: laws.road_speed };
    let b = belief(ctx, id, map);
    let shape = kn::Shape { unknown_cost: laws.unknown_cost, road_speed: laws.road_speed, ..Default::default() };
    SEARCH.with(|cache| {
        let mut cache = cache.borrow_mut();
        let mut search = match cache.remove(&id) {
            Some((previous, search)) if previous == key => search,
            _ => kn::Search::new(&b, from, to, shape)?,
        };
        match search.advance(&b, kn::STEERING_POPS) {
            Some(result) => result.map(|points| Some(points.into_iter().map(|(x, y)| Waypoint { x, y }).collect())),
            None => {
                cache.insert(id, (key, search));
                Ok(None)
            }
        }
    })
}

pub fn end_search(id: u32) {
    SEARCH.with(|s| s.borrow_mut().remove(&id));
}

/// Whether a walk's path, from `at`, crosses ground `id` now believes blocked (a wall it has just
/// seen): its leg must be planned again.
pub fn path_blocked(ctx: &ReducerContext, id: u32, map: &living_rules::map::Map, at: (f32, f32), path: &[Waypoint]) -> bool {
    let b = belief(ctx, id, map);
    let mut a = at;
    for w in path {
        if !b.line_open(a, (w.x, w.y)) {
            return true;
        }
        a = (w.x, w.y);
    }
    false
}

/// Death: the character's known ground and remembered things go.
pub fn forget(ctx: &ReducerContext, id: u32) {
    end_search(id);
    REVISION.with(|r| r.borrow_mut().remove(&id));
    PENDING.with(|p| p.borrow_mut().remove(&id));
    let rows: Vec<u64> = ctx.db.known_ground().actor().filter(id).map(|r| r.id).collect();
    for r in rows {
        ctx.db.known_ground().id().delete(r);
    }
    let rows: Vec<u64> = ctx.db.remembered().observer().filter(id).map(|r| r.id).collect();
    for r in rows {
        ctx.db.remembered().id().delete(r);
    }
}
