//! Sight-scoped things (docs/FEED_SCOPING.md, "Authority shapes"): what a character sees of
//! small mutable things (remains, storage, signs, traps, fires, lamps, brush, a gate's state,
//! a depleted resource node) is decided by one test, [`Eye::sees`], in every caller: a player's
//! perception sweep (its copies, `my_things`), a mind's noticing and its scene, and the
//! memory both keep (`remembered_thing`, `remembered` for gates). Everything here runs from
//! stage 1 on (`store::sighted`).
//!
//! - **Copies.** At a player's sweep, in the same pass and with the same senses, facing, map
//!   and cover as the people it sees, each candidate from its chunk's list of sight-scoped
//!   structures and depleted nodes is tested; the copies are diffed by payload in that one
//!   transaction (no observation time, so a sweep that changes nothing writes nothing).
//! - **Memory.** A sight-scoped structure seen is remembered as seen (place, kind, gate open,
//!   lit), written when first seen or when that changes. A memory goes only when a sighting of
//!   its place finds the thing missing; nothing else updates it (not the thing's own row).
//! - **Owner labels.** Architecture whose owner a viewer may be told (`owner_shown`), rebuilt
//!   when the viewer's knowledge or an owner changes.
//! - **Fuel.** Only lit or out is seen; how much fuel is left is found by looking a fire over
//!   (`inspect`), kept in `fuel_seen`.

use crate::common::{self, dist};
use crate::store;
use crate::tables::*;
use living_rules::map::Map;
use living_rules::script::{Scripts, Senses};
use spacetimedb::{Identity, ReducerContext, Table, ViewContext};
use std::cell::{Cell, RefCell};
use std::collections::{HashMap, HashSet};
use std::rc::Rc;

/// Most sight-scoped things a character remembers (the longest unseen go first).
pub const REMEMBER_THINGS: usize = 256;
/// Most fires a character remembers the fuel of.
pub const FUEL_SEEN: usize = 32;
/// Most containers a character remembers the contents of.
pub const CONTENTS_SEEN: usize = 32;
/// A character's remembered things are checked against a sighting of their places at most this
/// often (and at once in another chunk).
const RECHECK_MS: u64 = 5_000;

pub fn key(class: u8, id: u64) -> u64 {
    (class as u64) << 56 | id
}

/// One observer's view for the sight test: where it stands, which way it faces, its senses (the
/// gaze band's field and caps included), the map with its cover, and the glow cap for lights.
pub struct Eye<'a> {
    pub map: &'a Map,
    pub at: (f32, f32),
    pub heading: f32,
    pub senses: &'a Senses,
    /// The light a self-lit thing may lend itself (0: the world's laws light nothing).
    pub glow: f32,
    /// The keep margin for a thing already seen (`keep_seen_m`).
    pub keep: f32,
}

impl Eye<'_> {
    /// A thing at `p`, `d` away, with `glow` of its own light.
    pub fn sees_at(&self, p: (f32, f32), d: f32, glow: f32, kept: bool) -> bool {
        living_rules::sight::sees(self.map, self.at, self.heading, p, d, self.senses, glow.min(self.glow), kept.then_some(self.keep))
    }

    /// A structure: a lit fire or lamp lends itself its light.
    pub fn sees(&self, sc: &Scripts, s: &Structure, d: f32, kept: bool, now: u64) -> bool {
        let glow = if self.glow > 0.0 {
            let t = sc.structure(&s.kind);
            let l = t.light();
            if l > 0.0 && (t.burns.is_none() || living_rules::fire::lit(s.lit_until_ms, now)) { l } else { 0.0 }
        } else {
            0.0
        };
        self.sees_at((s.x, s.y), d, glow, kept)
    }
}

/// The parts of an eye that are owned: build with [`Look::of`], borrow with [`Look::eye`].
pub struct Look {
    pub map: Rc<Map>,
    pub at: (f32, f32),
    pub heading: f32,
    pub senses: Senses,
    pub glow: f32,
    pub keep: f32,
    pub gather: f32,
}

impl Look {
    pub fn from(ctx: &ReducerContext, map: Rc<Map>, at: (f32, f32), heading: f32, senses: Senses) -> Look {
        let keep = common::laws(ctx).keep_seen_m;
        let (gather, lit) = common::gather_radius(ctx, &senses, keep);
        let glow = if lit {
            match senses.gaze {
                Some(g) => g.glow,
                None => common::scripts(ctx).reach().glow,
            }
        } else {
            0.0
        };
        Look { map, at, heading, senses, glow, keep, gather }
    }

    pub fn eye(&self) -> Eye<'_> {
        Eye { map: &self.map, at: self.at, heading: self.heading, senses: &self.senses, glow: self.glow, keep: self.keep }
    }
}

// ---- candidates, by coarse cell ----------------------------------------------------------------

/// The side of a candidate cell in chunks (4 × 16 m = 64 m): a player's gather disc (about 50-60 m)
/// touches at most 3 × 3 cells, where a chunk walk touches about 49 chunks.
const CELL_CHUNKS: u32 = 4;

/// What the sweep needs of one candidate, read once when its cell is built (no script, world or
/// table read per test): its place and its light, and what its payload is made from.
#[derive(Clone)]
pub struct Cand {
    pub class: u8,
    pub id: u64,
    pub x: f32,
    pub y: f32,
    pub kind: Rc<str>,
    /// Its kind's light (0: none), lent to its own sight test while it burns.
    pub light: f32,
    /// A fire that burns fuel (`burns`): lit while `lit_until_ms` is ahead.
    pub burns: bool,
    /// A fire that needs no feeding: always lit.
    pub fire: bool,
    pub lit_until_ms: u64,
    pub owner: u32,
    /// A sight-scoped kind (remembered by the sight test's memory).
    pub scoped: bool,
    /// A resource node (class 0) that draws on another's stock (0: its own).
    pub pool: u64,
}

fn cell_of_chunk(chunk: u32) -> u32 {
    let (cx, cy) = living_rules::map::chunk_xy(chunk);
    living_rules::map::chunk_id(cx / CELL_CHUNKS, cy / CELL_CHUNKS)
}

thread_local! {
    /// Candidates by cell (sight-scoped structures, gates, fires, and resource nodes that may be
    /// short of full), with the chunk caches' rule: a cell read after a write in a transaction is
    /// read again in the next one (`common::WriteCache`), invalidated with them.
    static CELLS: RefCell<common::WriteCache<Rc<Vec<Cand>>>> = RefCell::new(common::WriteCache::new());
    static CELLS_REV: Cell<u32> = const { Cell::new(u32::MAX) };
    /// What one transaction worked out of each seen thing (lit, open, stock), shared by every viewer
    /// swept in it: (stamp, by key).
    static PAYLOAD: RefCell<(i64, HashMap<u64, Option<(bool, Option<bool>, Option<(u32, u32)>)>>)> = RefCell::new((0, HashMap::new()));
    /// Each player's character's copies as its sweeps last wrote them (key -> row id and payload).
    /// Module memory: dropped with the perception sweep's own memory when ticks did not follow on
    /// (`perception::sweep`, a rollback or another instance), and for a sweep outside the tick; the
    /// table is read again then.
    static COPIES: RefCell<HashMap<u32, HashMap<u64, (u64, SeenThing)>>> = RefCell::new(HashMap::new());
    /// Each player's character: the inputs its owner labels were last written from.
    static OWNERS: RefCell<HashMap<u32, ((u64, u64), u64)>> = RefCell::new(HashMap::new());
    static OWNERS_REV: Cell<u64> = const { Cell::new(0) };
    /// Each character's last memory check: its chunk and when.
    static CHECKED: RefCell<HashMap<u32, (u32, u64)>> = RefCell::new(HashMap::new());
    /// What each character's `remembered_thing` rows hold, as this instance last wrote or read them
    /// ((observer, target) -> place, open, lit): a sighting that changes nothing reads no row.
    /// Dropped with the copies (`clear_memory`) when ticks do not follow on.
    static MEMO: RefCell<HashMap<(u32, u64), (f32, f32, Option<bool>, bool)>> = RefCell::new(HashMap::new());
    /// Each player's character: when its far not-yet-seen things were last tested
    /// (`feed_scope_far_s`). Lost with the instance: they are tested at once then.
    static FAR: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    /// `feed_scope_popin_probe`: when each far thing a viewer had not yet seen first passed the
    /// sight test at a sweep that did not take it ((character, key) -> ms, distance).
    static POPIN: RefCell<HashMap<(u32, u64), (u64, f32)>> = RefCell::new(HashMap::new());
}

/// A structure or resource write: the cells it touches are built again (all of them for
/// structures, as the chunk cache does).
pub fn invalidate_cells(t: i64, chunk: Option<u32>) {
    CELLS.with(|c| c.borrow_mut().invalidate(t, chunk.map(cell_of_chunk)));
}

/// Module memory no longer follows the committed rows (`perception::sweep`).
pub fn clear_memory() {
    COPIES.with(|c| c.borrow_mut().clear());
    MEMO.with(|m| m.borrow_mut().clear());
}

/// One character's copies are read from the table at its next sweep (a sweep outside the tick).
pub fn forget_memory(id: u32) {
    COPIES.with(|c| c.borrow_mut().remove(&id));
}

/// Architecture changed owner (or appeared or went): every viewer's labels are rebuilt.
pub fn owners_changed() {
    OWNERS_REV.with(|r| r.set(r.get().wrapping_add(1)));
}

fn copied(sc: &Scripts, kind: &str) -> bool {
    store::scoped_kind(kind) || kind == "gate" || sc.structure(kind).fire()
}

fn build_cell(ctx: &ReducerContext, cell: u32) -> Rc<Vec<Cand>> {
    let sc = common::scripts(ctx);
    let (gx, gy) = living_rules::map::chunk_xy(cell);
    let w = common::world(ctx);
    let (nx, ny) = (w.width.div_ceil(16), w.height.div_ceil(16));
    let mut v = Vec::new();
    for cy in gy * CELL_CHUNKS..((gy + 1) * CELL_CHUNKS).min(ny) {
        for cx in gx * CELL_CHUNKS..((gx + 1) * CELL_CHUNKS).min(nx) {
            let chunk = living_rules::map::chunk_id(cx, cy);
            for s in common::chunk_structures(ctx, chunk).iter().filter(|s| copied(&sc, &s.kind)) {
                let t = sc.structure(&s.kind);
                v.push(Cand { class: 1, id: s.id, x: s.x, y: s.y, kind: Rc::from(s.kind.as_str()), light: t.light(), burns: t.burns.is_some(), fire: t.fire(),
                              lit_until_ms: s.lit_until_ms, owner: s.owner, scoped: store::scoped_kind(&s.kind), pool: 0 });
            }
            for n in common::chunk_resources(ctx, chunk).iter().filter(|n| n.pool != 0 || n.amount < n.max) {
                v.push(Cand { class: 0, id: n.id, x: n.x, y: n.y, kind: Rc::from(n.kind.as_str()), light: 0.0, burns: false, fire: false, lit_until_ms: 0, owner: 0, scoped: false, pool: n.pool });
            }
        }
    }
    Rc::new(v)
}

fn cell(ctx: &ReducerContext, cell: u32) -> Rc<Vec<Cand>> {
    let rev = common::scripts_rev(ctx);
    let t = common::stamp(ctx);
    if CELLS_REV.with(|r| r.get()) != rev {
        CELLS.with(|c| c.borrow_mut().invalidate(t, None));
        CELLS_REV.with(|r| r.set(rev));
    }
    CELLS.with(|c| c.borrow_mut().get(t, cell, || build_cell(ctx, cell)))
}

/// The cells a disc of radius `r` round `at` touches.
fn cells_around(at: (f32, f32), r: f32) -> Vec<u32> {
    let side = (16 * CELL_CHUNKS) as f32;
    let lo = |v: f32| ((v - r).max(0.0) / side) as u32;
    let hi = |v: f32| ((v + r).max(0.0) / side) as u32;
    let mut out = Vec::with_capacity(9);
    for gy in lo(at.1)..=hi(at.1) {
        for gx in lo(at.0)..=hi(at.0) {
            out.push(living_rules::map::chunk_id(gx, gy));
        }
    }
    out
}

// ---- what is seen of a thing -----------------------------------------------------------------

/// Whether a structure reads as lit to one who sees it: a fire that burns fuel while it has
/// fuel, one that needs none always; anything else never.
pub fn lit(ctx: &ReducerContext, s: &Structure, now: u64) -> bool {
    crate::act::fire_state(ctx, s, now).0
}

fn seen_structure(ctx: &ReducerContext, s: &Structure, owner: u32, now: u64) -> SeenThing {
    let open = (s.kind == "gate").then(|| store::gate(ctx, s.id).map(|g| g.open)).flatten();
    SeenThing { key: key(1, s.id), class: 1, id: s.id, kind: s.kind.clone(), x: s.x, y: s.y, open, lit: lit(ctx, s, now), owner, left: None, max: None }
}

/// A candidate's lit, open and stock as this transaction sees them (worked out once per
/// transaction and thing, for every viewer). `None`: a node at full stock (no copy).
fn payload(ctx: &ReducerContext, c: &Cand, now: u64) -> Option<(bool, Option<bool>, Option<(u32, u32)>)> {
    let t = common::stamp(ctx);
    let k = key(c.class, c.id);
    let hit = PAYLOAD.with(|p| {
        let mut p = p.borrow_mut();
        if p.0 != t {
            *p = (t, HashMap::new());
        }
        p.1.get(&k).copied()
    });
    if let Some(v) = hit {
        return v;
    }
    let v = if c.class == 0 {
        let stock = match c.pool {
            0 => None,
            pool => store::resource(ctx, pool),
        };
        let stock = match stock {
            Some(s) => s,
            None => store::resource(ctx, c.id).map(|n| common::stock_of(ctx, &n)).unwrap_or_else(|| ResourceNode { id: c.id, kind: c.kind.to_string(), x: c.x, y: c.y, chunk: 0, amount: 0.0, max: 0.0, regen: 0.0, at_ms: now, pool: 0 }),
        };
        let max = stock.max.max(0.0).floor() as u32;
        let left = common::amount_now(ctx, &stock, now).max(0.0).floor() as u32;
        (left < max).then_some((false, None, Some((left, max))))
    } else {
        let lit = if c.burns { living_rules::fire::lit(c.lit_until_ms, now) } else { c.fire };
        let open = (&*c.kind == "gate").then(|| store::gate(ctx, c.id).map(|g| g.open)).flatten();
        Some((lit, open, None))
    };
    PAYLOAD.with(|p| p.borrow_mut().1.insert(k, v));
    v
}

/// What `me` may be told of a thing's owner (its id, when the `owner_shown` law grants it).
fn owner_shown(ctx: &ReducerContext, me: &Character, owner: u32, kind: &str) -> u32 {
    if owner == 0 {
        return 0;
    }
    common::owner_label(ctx, me, owner, kind).map_or(0, |_| owner)
}

// ---- a player's copies -----------------------------------------------------------------------

/// A player's character's sweep (`perception::sweep_one`, the same pass as the people it sees):
/// the things in sight now, written as the viewer's copies; what it sees remembered.
///
/// `keep`: the sweep is the tick's (its copies may stay in module memory for the next sweep); a
/// sweep in another transaction (join, reclaim) keeps none, since that transaction may fail.
pub fn sweep(ctx: &ReducerContext, me: &Character, viewer: Identity, look: &Look, keep: bool, now: u64) {
    let span = common::detail_span("sight.player_things");
    let eye = look.eye();
    let mut prior: HashMap<u64, (u64, SeenThing)> = COPIES.with(|c| c.borrow_mut().remove(&me.id)).unwrap_or_else(|| {
        ctx.db.thing_seen().viewer().filter(viewer).filter(|r| r.character == me.id).map(|r| (r.thing.key, (r.id, r.thing))).collect()
    });
    let fresh_owners = OWNERS.with(|o| !o.borrow().contains_key(&me.id));
    let mut seen: Vec<(SeenThing, bool)> = Vec::new();
    let (mut tests, mut skipped) = (0u64, 0u64);
    let r2 = look.gather * look.gather;
    // Iteration 3 cadence (docs/FEED_SCOPING.md): what this viewer sees, and what it has not yet
    // seen within `feed_scope_near_m`, is tested at every sweep; not-yet-seen things beyond it once
    // every `feed_scope_far_s`.
    let laws = common::laws(ctx);
    let near2 = laws.feed_scope_near_m * laws.feed_scope_near_m;
    let far_every = (laws.feed_scope_far_s * 1000.0) as u64;
    let probe = laws.feed_scope_popin_probe;
    let far_due = FAR.with(|f| {
        let mut f = f.borrow_mut();
        let due = f.get(&me.id).is_none_or(|t| now.saturating_sub(*t) >= far_every);
        if due {
            f.insert(me.id, now);
        }
        due
    });
    for cid in cells_around(look.at, look.gather) {
        for c in cell(ctx, cid).iter() {
            let (dx, dy) = (c.x - look.at.0, c.y - look.at.1);
            let d2 = dx * dx + dy * dy;
            if d2 > r2 {
                continue;
            }
            let k = key(c.class, c.id);
            let before = prior.get(&k);
            // A node at full stock gets no copy (it is drawn as its landmark): known before any ray.
            let p = match payload(ctx, c, now) {
                Some(p) => p,
                None => continue,
            };
            let far = before.is_none() && d2 > near2;
            if far && !far_due && !probe {
                skipped += 1;
                continue;
            }
            tests += 1;
            let glow = if c.light > 0.0 && (!c.burns || p.0) { c.light } else { 0.0 };
            let visible = eye.sees_at((c.x, c.y), d2.sqrt(), glow, before.is_some());
            if far && probe {
                popin(me.id, k, visible, far_due, d2.sqrt(), now);
                if !far_due {
                    continue;
                }
            }
            if !visible {
                continue;
            }
            let (lit, open, stock) = p;
            let owner = match before {
                Some((_, t)) if !fresh_owners && (t.owner == 0 || t.owner == c.owner) => t.owner,
                _ if c.class == 1 => owner_shown(ctx, me, c.owner, &c.kind),
                _ => 0,
            };
            seen.push((SeenThing { key: k, class: c.class, id: c.id, kind: c.kind.to_string(), x: c.x, y: c.y, open, lit, owner, left: stock.map(|s| s.0), max: stock.map(|s| s.1) }, c.scoped));
        }
    }
    drop(span);
    common::diag(|| "scope:tests", tests);
    common::diag(|| "scope:far_skipped", skipped);
    let (mut ins, mut upd) = (0u64, 0u64);
    let mut keys: HashSet<u64> = HashSet::with_capacity(seen.len());
    let mut now_copies: HashMap<u64, (u64, SeenThing)> = HashMap::with_capacity(seen.len());
    for (thing, remember) in seen {
        keys.insert(thing.key);
        let (id, changed) = match prior.remove(&thing.key) {
            Some((id, p)) if p == thing => (id, false),
            Some((id, _)) if ctx.db.thing_seen().id().find(id).is_some() => {
                ctx.db.thing_seen().id().update(ThingSeen { id, viewer, character: me.id, thing: thing.clone() });
                upd += 1;
                (id, true)
            }
            _ => {
                let row = ctx.db.thing_seen().insert(ThingSeen { id: 0, viewer, character: me.id, thing: thing.clone() });
                ins += 1;
                (row.id, true)
            }
        };
        if changed && remember {
            remember_thing(ctx, me.id, &thing, now);
        }
        now_copies.insert(thing.key, (id, thing));
    }
    let gone = prior.len() as u64;
    for (_, (id, _)) in prior {
        // A row a stale memory names may be gone already; deleting nothing is harmless.
        ctx.db.thing_seen().id().delete(id);
    }
    if keep {
        COPIES.with(|c| c.borrow_mut().insert(me.id, now_copies));
    }
    common::diag(|| "scope:copy_insert", ins);
    common::diag(|| "scope:copy_update", upd);
    common::diag(|| "scope:copy_delete", gone);
    recheck(ctx, me.id, &eye, look.gather, |k| keys.contains(&k), now);
    owners(ctx, me, viewer);
}

/// The pop-in probe for one far thing this viewer has not yet seen, at one sweep: `visible` is the
/// sight test now, `taken` whether this sweep takes far things. A sighting at a sweep that does not
/// take it starts its clock; the sweep that takes it logs the extra delay (0 when it was taken at
/// its first sighting); one that leaves sight before it is taken logs a miss.
fn popin(id: u32, k: u64, visible: bool, taken: bool, dist: f32, now: u64) {
    POPIN.with(|p| {
        let mut p = p.borrow_mut();
        match (visible, taken) {
            (true, true) => {
                let (since, at) = p.remove(&(id, k)).unwrap_or((now, dist));
                log::info!("feed scope pop-in: {} ms at {:.1} m", now.saturating_sub(since), at);
            }
            (true, false) => {
                p.entry((id, k)).or_insert((now, dist));
            }
            (false, _) => {
                if let Some((since, at)) = p.remove(&(id, k)) {
                    log::info!("feed scope pop-in missed: in sight {} ms at {:.1} m", now.saturating_sub(since), at);
                }
            }
        }
    });
}

/// A player's character perceives nothing any more (death, a hand-over to the minds).
pub fn forget(ctx: &ReducerContext, id: u32, viewer: Identity) {
    for r in ctx.db.thing_seen().viewer().filter(viewer).map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.thing_seen().id().delete(r);
    }
    for r in ctx.db.owner_seen().viewer().filter(viewer).map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.owner_seen().id().delete(r);
    }
    OWNERS.with(|o| o.borrow_mut().remove(&id));
    COPIES.with(|c| c.borrow_mut().remove(&id));
    FAR.with(|f| f.borrow_mut().remove(&id));
    POPIN.with(|p| p.borrow_mut().retain(|(c, _), _| *c != id));
}

/// A character died: what it remembered and found out goes with it.
pub fn forget_dead(ctx: &ReducerContext, id: u32) {
    ctx.db.remembered_thing().observer().delete(id);
    MEMO.with(|m| m.borrow_mut().retain(|(o, _), _| *o != id));
    ctx.db.fuel_seen().observer().delete(id);
    ctx.db.contents_seen().observer().delete(id);
    ctx.db.seen_structures_scoped().actor().delete(id);
    CHECKED.with(|c| c.borrow_mut().remove(&id));
    OWNERS.with(|o| o.borrow_mut().remove(&id));
}

// ---- owner labels ----------------------------------------------------------------------------

fn owners(ctx: &ReducerContext, me: &Character, viewer: Identity) {
    let epoch = crate::perception::epoch_of(ctx, me.id);
    let rev = OWNERS_REV.with(|r| r.get());
    if OWNERS.with(|o| o.borrow().get(&me.id) == Some(&(epoch, rev))) {
        return;
    }
    let _span = common::detail_span("scope.owners");
    let sc = common::scripts(ctx);
    let mut want: HashMap<u64, u32> = HashMap::new();
    let mut add = |row: &OwnedBy| {
        if common::owner_label(ctx, me, row.owner, &row.kind).is_some() {
            want.insert(row.structure, row.owner);
        }
    };
    let mut owners: Vec<u32> = crate::perception::known_name_ids(ctx, me).into_iter().collect();
    owners.push(me.id);
    owners.sort_unstable();
    owners.dedup();
    for o in owners {
        for row in ctx.db.owned_by().owner().filter(o) {
            add(&row);
        }
    }
    // A kind that shows its owner to anyone (its `shows_owner`).
    if store::MAP_KINDS.iter().any(|k| sc.structure(k).shows_owner) {
        for row in ctx.db.owned_by().iter().filter(|r| sc.structure(&r.kind).shows_owner) {
            add(&row);
        }
    }
    let mut had: HashMap<u64, OwnerSeen> = ctx.db.owner_seen().viewer().filter(viewer).map(|r| (r.structure, r)).collect();
    for (structure, owner) in want {
        match had.remove(&structure) {
            Some(r) if r.owner == owner => {}
            Some(r) => {
                ctx.db.owner_seen().id().update(OwnerSeen { owner, ..r });
            }
            None => {
                ctx.db.owner_seen().insert(OwnerSeen { id: 0, viewer, structure, owner });
            }
        }
    }
    for (_, r) in had {
        ctx.db.owner_seen().id().delete(r.id);
    }
    OWNERS.with(|o| o.borrow_mut().insert(me.id, (epoch, rev)));
}

// ---- memory ----------------------------------------------------------------------------------

/// Remember a sight-scoped structure as just seen (a player's copy entering or changing; a mind's
/// noticing).
fn remember_thing(ctx: &ReducerContext, observer: u32, t: &SeenThing, now: u64) {
    let state = (t.x, t.y, t.open, t.lit);
    if MEMO.with(|m| m.borrow().get(&(observer, t.id)) == Some(&state)) {
        return;
    }
    MEMO.with(|m| m.borrow_mut().insert((observer, t.id), state));
    let chunk = living_rules::map::chunk_of(t.x, t.y);
    match ctx.db.remembered_thing().by_observer_target().filter((observer, t.id)).next() {
        Some(r) if r.x == t.x && r.y == t.y && r.open == t.open && r.lit == t.lit && r.kind == t.kind => {}
        Some(r) => {
            ctx.db.remembered_thing().id().update(RememberedThing { kind: t.kind.clone(), x: t.x, y: t.y, chunk, open: t.open, lit: t.lit, seen_ms: now, ..r });
            common::diag(|| "scope:memory_write", 1);
        }
        None => {
            let mine: Vec<(u64, u64, u64)> = ctx.db.remembered_thing().observer().filter(observer).map(|r| (r.seen_ms, r.id, r.target)).collect();
            if mine.len() >= REMEMBER_THINGS {
                let mut mine = mine;
                mine.sort_unstable();
                for (_, id, target) in &mine[..mine.len() + 1 - REMEMBER_THINGS] {
                    ctx.db.remembered_thing().id().delete(*id);
                    MEMO.with(|m| m.borrow_mut().remove(&(observer, *target)));
                }
            }
            ctx.db.remembered_thing().insert(RememberedThing { id: 0, observer, target: t.id, kind: t.kind.clone(), x: t.x, y: t.y, chunk, open: t.open, lit: t.lit, seen_ms: now });
            common::diag(|| "scope:memory_write", 1);
        }
    }
}

/// A sighting of remembered places: a remembered thing whose place is in sight now but which is
/// not among what is seen is gone (or moved): the memory goes. Each chunk at most every
/// [`RECHECK_MS`] per character.
fn recheck(ctx: &ReducerContext, observer: u32, eye: &Eye, gather: f32, seen: impl Fn(u64) -> bool, now: u64) {
    let here = living_rules::map::chunk_of(eye.at.0, eye.at.1);
    let due = CHECKED.with(|c| {
        let mut c = c.borrow_mut();
        let due = c.get(&observer).is_none_or(|(ch, t)| *ch != here || now.saturating_sub(*t) >= RECHECK_MS);
        if due {
            c.insert(observer, (here, now));
        }
        due
    });
    if !due {
        return;
    }
    for r in ctx.db.remembered_thing().observer().filter(observer).collect::<Vec<_>>() {
        let d = dist(eye.at, (r.x, r.y));
        if d > gather || seen(key(1, r.target)) {
            continue;
        }
        if eye.sees_at((r.x, r.y), d, 0.0, false) {
            ctx.db.remembered_thing().id().delete(r.id);
            MEMO.with(|m| m.borrow_mut().remove(&(observer, r.target)));
            common::diag(|| "scope:memory_gone", 1);
        }
    }
}

/// A mind's noticing (`brain::noticed`): what it sees of sight-scoped structures (`visible`, the
/// scene's list after the sight test) is remembered by the same rule as a player's.
///
/// `present`: the sight-scoped things there now within the look's radius (tested or not): a
/// memory of one of them is never taken as a witnessed absence.
pub fn remember_seen(ctx: &ReducerContext, observer: u32, look: &Look, visible: &[(Structure, f32)], present: &[u64], now: u64) {
    let keys: HashSet<u64> = present.iter().map(|id| key(1, *id)).collect();
    for (s, _) in visible {
        if !store::scoped_kind(&s.kind) {
            continue;
        }
        let t = seen_structure(ctx, s, 0, now);
        remember_thing(ctx, observer, &t, now);
    }
    recheck(ctx, observer, &look.eye(), look.gather, |k| keys.contains(&k), now);
}

// ---- looking a thing over: fuel and contents -------------------------------------------------

/// A kind whose inside can be looked into: one that `holds` things, remains, a trap.
pub fn container(sc: &Scripts, kind: &str) -> bool {
    sc.structure(kind).holds.is_some() || kind == "remains" || kind == "trap"
}

/// What `me` knows a container holds, as it found it (`None`: it has not looked inside).
pub fn known_contents(ctx: &ReducerContext, me: u32, target: u64) -> Option<ContentsSeen> {
    ctx.db.contents_seen().by_observer_target().filter((me, target)).next()
}

/// `me` sees inside container `target` now (it looked in, took or stored): kept as found.
pub fn record_contents(ctx: &ReducerContext, me: u32, target: u64, now: u64) -> Vec<ItemCount> {
    let items: Vec<ItemCount> = common::inv_list(ctx, STRUCTURE_BIT | target).into_iter().filter(|(_, q)| *q > 0).map(|(item, qty)| ItemCount { item, qty }).collect();
    match known_contents(ctx, me, target) {
        Some(r) if r.items == items && now.saturating_sub(r.seen_ms) < 60_000 => {}
        Some(r) => {
            ctx.db.contents_seen().id().update(ContentsSeen { items: items.clone(), seen_ms: now, ..r });
        }
        None => {
            let mine: Vec<(u64, u64)> = ctx.db.contents_seen().observer().filter(me).map(|r| (r.seen_ms, r.id)).collect();
            if mine.len() >= CONTENTS_SEEN {
                let mut mine = mine;
                mine.sort_unstable();
                for (_, id) in &mine[..mine.len() + 1 - CONTENTS_SEEN] {
                    ctx.db.contents_seen().id().delete(*id);
                }
            }
            ctx.db.contents_seen().insert(ContentsSeen { id: 0, observer: me, target, items: items.clone(), seen_ms: now });
        }
    }
    items
}

pub fn contents_words(items: &[ItemCount]) -> String {
    if items.is_empty() {
        return "nothing".into();
    }
    items.iter().map(|i| format!("{} {}", i.qty, i.item.replace('_', " "))).collect::<Vec<_>>().join(", ")
}

/// `inspect`: a fire's fuel left, and a container's contents, found out, kept (`fuel_seen`,
/// `contents_seen`) and told. Returns the line.
pub fn inspect(ctx: &ReducerContext, me: u32, target: u64, now: u64) -> Result<String, String> {
    let s = store::structure(ctx, target).ok_or("it is gone")?;
    let sc = common::scripts(ctx);
    let t = sc.structure(&s.kind);
    let kind = s.kind.replace('_', " ");
    let mut lines = Vec::new();
    if let Some(b) = t.burns.clone() {
        let (lit, fuel) = crate::act::fire_state(ctx, &s, now);
        let hours = if lit { fuel / b.rate.max(1e-6) } else { 0.0 };
        match ctx.db.fuel_seen().by_observer_target().filter((me, target)).next() {
            Some(r) => {
                ctx.db.fuel_seen().id().update(FuelSeen { left: hours, seen_ms: now, ..r });
            }
            None => {
                let mine: Vec<(u64, u64)> = ctx.db.fuel_seen().observer().filter(me).map(|r| (r.seen_ms, r.id)).collect();
                if mine.len() >= FUEL_SEEN {
                    let mut mine = mine;
                    mine.sort_unstable();
                    for (_, id) in &mine[..mine.len() + 1 - FUEL_SEEN] {
                        ctx.db.fuel_seen().id().delete(*id);
                    }
                }
                ctx.db.fuel_seen().insert(FuelSeen { id: 0, observer: me, target, left: hours, seen_ms: now });
            }
        }
        lines.push(if lit {
            format!("You look the {kind} over: about {} hours of {} left on it.", fuel_words(hours), b.fuel.replace('_', " "))
        } else {
            format!("You look the {kind} over: it is out, with no {} left on it.", b.fuel.replace('_', " "))
        });
    }
    if container(&sc, &s.kind) {
        let items = record_contents(ctx, me, target, now);
        lines.push(format!("You look inside the {kind}: {}.", contents_words(&items)));
    }
    if lines.is_empty() {
        return Err(format!("there is nothing to look over on the {kind}"));
    }
    Ok(lines.join(" "))
}

pub fn fuel_words(hours: f32) -> String {
    if hours < 1.0 {
        "less than an hour's".to_string()
    } else {
        format!("{:.0}", hours)
    }
}

// ---- what a client is shown (sender-scoped views) --------------------------------------------

/// What my character sees now of sight-scoped things (and of a gate's state, a fire's, a
/// depleted node's stock): my copies, one index key.
#[spacetimedb::view(accessor = my_things, public, primary_key = key)]
pub fn my_things(ctx: &ViewContext) -> Vec<SeenThing> {
    ctx.db.thing_seen().viewer().filter(ctx.sender()).map(|r| r.thing).collect()
}

/// What my living character remembers of sight-scoped things and gates, as last seen.
#[spacetimedb::view(accessor = my_remembered_things, public, primary_key = key)]
pub fn my_remembered_things(ctx: &ViewContext) -> Vec<RememberedSeen> {
    let Some(c) = crate::perception::living(ctx) else { return Vec::new() };
    let gates = ctx.db.remembered().observer().filter(c.id).filter(|r| r.kind == REMEMBER_GATE).map(|r| RememberedSeen {
        key: key(1, r.target),
        class: 1,
        id: r.target,
        kind: "gate".into(),
        x: r.x,
        y: r.y,
        open: Some(r.state == 1),
        lit: false,
        seen_ms: r.seen_ms,
    });
    let things = ctx.db.remembered_thing().observer().filter(c.id).map(|r| RememberedSeen {
        key: key(1, r.target),
        class: 1,
        id: r.target,
        kind: r.kind,
        x: r.x,
        y: r.y,
        open: r.open,
        lit: r.lit,
        seen_ms: r.seen_ms,
    });
    gates.chain(things).collect()
}

/// The owners of architecture my character may be told (`owner_shown`), by structure.
#[spacetimedb::view(accessor = my_owners, public, primary_key = structure)]
pub fn my_owners(ctx: &ViewContext) -> Vec<OwnerLabel> {
    ctx.db.owner_seen().viewer().filter(ctx.sender()).map(|r| OwnerLabel { structure: r.structure, owner: r.owner }).collect()
}

/// What my living character remembers of resources (talk-places, `stock.rs`).
#[spacetimedb::view(accessor = my_stock, public, primary_key = id)]
pub fn my_stock(ctx: &ViewContext) -> Vec<SeenStock> {
    crate::perception::living(ctx).map(|c| ctx.db.seen_stock().actor().filter(c.id).collect()).unwrap_or_default()
}

/// What my living character found inside containers when it last looked (`inspect`, take, store).
#[spacetimedb::view(accessor = my_contents_seen, public, primary_key = id)]
pub fn my_contents_seen(ctx: &ViewContext) -> Vec<ContentsSeen> {
    crate::perception::living(ctx).map(|c| ctx.db.contents_seen().observer().filter(c.id).collect()).unwrap_or_default()
}

/// The fuel my living character found on fires it looked over (`inspect`).
#[spacetimedb::view(accessor = my_fuel_seen, public, primary_key = id)]
pub fn my_fuel_seen(ctx: &ViewContext) -> Vec<FuelSeen> {
    crate::perception::living(ctx).map(|c| ctx.db.fuel_seen().observer().filter(c.id).collect()).unwrap_or_default()
}
