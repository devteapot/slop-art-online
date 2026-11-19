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
/// A character's remembered things in one chunk are checked against a sighting of their place
/// at most this often (and at once in another chunk).
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

// ---- chunk-local candidates ------------------------------------------------------------------

thread_local! {
    /// Per chunk, its structures a player's copies may carry (sight-scoped kinds, gates and
    /// fires), drawn from the chunk's cached list and again whenever that list is.
    static CHUNK_COPIED: RefCell<HashMap<u32, (Rc<Vec<Structure>>, Rc<Vec<Structure>>)>> = RefCell::new(HashMap::new());
    static COPIED_REV: Cell<u32> = const { Cell::new(u32::MAX) };
    /// Per chunk, its resource nodes that may be short of full (held below their max when last
    /// written, or drawing on a pool), drawn again whenever the chunk's list is.
    static CHUNK_SHORT: RefCell<HashMap<u32, (Rc<Vec<ResourceNode>>, Rc<Vec<ResourceNode>>)>> = RefCell::new(HashMap::new());
    /// Each player's character: the inputs its owner labels were last written from.
    static OWNERS: RefCell<HashMap<u32, ((u64, u64), u64)>> = RefCell::new(HashMap::new());
    static OWNERS_REV: Cell<u64> = const { Cell::new(0) };
    /// Each character's last memory check per chunk.
    static CHECKED: RefCell<HashMap<u32, HashMap<u32, u64>>> = RefCell::new(HashMap::new());
}

/// Architecture changed owner (or appeared or went): every viewer's labels are rebuilt.
pub fn owners_changed() {
    OWNERS_REV.with(|r| r.set(r.get().wrapping_add(1)));
}

fn copied(sc: &Scripts, kind: &str) -> bool {
    store::scoped_kind(kind) || kind == "gate" || sc.structure(kind).fire()
}

pub fn chunk_copied(ctx: &ReducerContext, chunk: u32) -> Rc<Vec<Structure>> {
    let all = common::chunk_structures(ctx, chunk);
    let rev = common::scripts_rev(ctx);
    if COPIED_REV.with(|r| r.get()) != rev {
        CHUNK_COPIED.with(|c| c.borrow_mut().clear());
        COPIED_REV.with(|r| r.set(rev));
    }
    if let Some(v) = CHUNK_COPIED.with(|c| c.borrow().get(&chunk).filter(|(src, _)| Rc::ptr_eq(src, &all)).map(|(_, v)| v.clone())) {
        return v;
    }
    let sc = common::scripts(ctx);
    let v: Rc<Vec<Structure>> = Rc::new(all.iter().filter(|s| copied(&sc, &s.kind)).cloned().collect());
    CHUNK_COPIED.with(|c| c.borrow_mut().insert(chunk, (all, v.clone())));
    v
}

fn chunk_short(ctx: &ReducerContext, chunk: u32) -> Rc<Vec<ResourceNode>> {
    let all = common::chunk_resources(ctx, chunk);
    if let Some(v) = CHUNK_SHORT.with(|c| c.borrow().get(&chunk).filter(|(src, _)| Rc::ptr_eq(src, &all)).map(|(_, v)| v.clone())) {
        return v;
    }
    let v: Rc<Vec<ResourceNode>> = Rc::new(all.iter().filter(|n| n.pool != 0 || n.amount < n.max).cloned().collect());
    CHUNK_SHORT.with(|c| c.borrow_mut().insert(chunk, (all, v.clone())));
    v
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

/// What `me` may be told of a thing's owner (its id, when the `owner_shown` law grants it).
fn owner_shown(ctx: &ReducerContext, me: &Character, s: &Structure) -> u32 {
    if s.owner == 0 {
        return 0;
    }
    common::owner_label(ctx, me, s.owner, &s.kind).map_or(0, |_| s.owner)
}

// ---- a player's copies -----------------------------------------------------------------------

/// A player's character's sweep (`perception::sweep_one`, the same pass as the people it sees):
/// the things in sight now, written as the viewer's copies; what it sees remembered.
pub fn sweep(ctx: &ReducerContext, me: &Character, viewer: Identity, look: &Look, now: u64) {
    let span = common::detail_span("sight.player_things");
    let eye = look.eye();
    let sc = common::scripts(ctx);
    let prior: HashMap<u64, ThingSeen> = ctx.db.thing_seen().viewer().filter(viewer).map(|r| (r.thing.key, r)).collect();
    let fresh_owners = OWNERS.with(|o| !o.borrow().contains_key(&me.id));
    let mut seen: Vec<(SeenThing, bool)> = Vec::new();
    let mut tests = 0u64;
    for c in living_rules::map::chunks_around(look.at.0, look.at.1, look.gather) {
        for s in chunk_copied(ctx, c).iter() {
            let d = dist(look.at, (s.x, s.y));
            if d > look.gather {
                continue;
            }
            tests += 1;
            let k = key(1, s.id);
            let before = prior.get(&k);
            if !eye.sees(&sc, s, d, before.is_some(), now) {
                continue;
            }
            // The owner as this viewer may be told it: worked out when the thing comes into
            // sight (or this instance has not yet), kept while it stays.
            let owner = match before {
                Some(p) if !fresh_owners && (p.thing.owner == 0 || p.thing.owner == s.owner) => p.thing.owner,
                _ => owner_shown(ctx, me, s),
            };
            seen.push((seen_structure(ctx, s, owner, now), store::scoped_kind(&s.kind)));
        }
        for n in chunk_short(ctx, c).iter() {
            let d = dist(look.at, (n.x, n.y));
            if d > look.gather {
                continue;
            }
            let stock = common::stock_of(ctx, n);
            let max = stock.max.max(0.0).floor() as u32;
            let left = common::amount_now(ctx, &stock, now).max(0.0).floor() as u32;
            if left >= max {
                continue;
            }
            tests += 1;
            let k = key(0, n.id);
            if !eye.sees_at((n.x, n.y), d, 0.0, prior.contains_key(&k)) {
                continue;
            }
            seen.push((SeenThing { key: k, class: 0, id: n.id, kind: n.kind.clone(), x: n.x, y: n.y, open: None, lit: false, owner: 0, left: Some(left), max: Some(max) }, false));
        }
    }
    drop(span);
    common::diag(|| "scope:tests", tests);
    let mut prior = prior;
    let (mut ins, mut upd) = (0u64, 0u64);
    let mut keys: HashSet<u64> = HashSet::with_capacity(seen.len());
    for (thing, remember) in seen {
        keys.insert(thing.key);
        let changed = match prior.remove(&thing.key) {
            Some(p) if p.thing == thing && p.character == me.id => false,
            Some(p) => {
                ctx.db.thing_seen().id().update(ThingSeen { id: p.id, viewer, character: me.id, thing: thing.clone() });
                upd += 1;
                true
            }
            None => {
                ctx.db.thing_seen().insert(ThingSeen { id: 0, viewer, character: me.id, thing: thing.clone() });
                ins += 1;
                true
            }
        };
        if changed && remember {
            remember_thing(ctx, me.id, &thing, now);
        }
    }
    let gone = prior.len() as u64;
    for (_, p) in prior {
        ctx.db.thing_seen().id().delete(p.id);
    }
    common::diag(|| "scope:copy_insert", ins);
    common::diag(|| "scope:copy_update", upd);
    common::diag(|| "scope:copy_delete", gone);
    recheck(ctx, me.id, &eye, look.gather, |k| keys.contains(&k), now);
    owners(ctx, me, viewer);
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
}

/// A character died: what it remembered and found out goes with it.
pub fn forget_dead(ctx: &ReducerContext, id: u32) {
    ctx.db.remembered_thing().observer().delete(id);
    ctx.db.fuel_seen().observer().delete(id);
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
    let chunk = living_rules::map::chunk_of(t.x, t.y);
    match ctx.db.remembered_thing().by_observer_target().filter((observer, t.id)).next() {
        Some(r) if r.x == t.x && r.y == t.y && r.open == t.open && r.lit == t.lit && r.kind == t.kind => {}
        Some(r) => {
            ctx.db.remembered_thing().id().update(RememberedThing { kind: t.kind.clone(), x: t.x, y: t.y, chunk, open: t.open, lit: t.lit, seen_ms: now, ..r });
            common::diag(|| "scope:memory_write", 1);
        }
        None => {
            let mine: Vec<(u64, u64)> = ctx.db.remembered_thing().observer().filter(observer).map(|r| (r.seen_ms, r.id)).collect();
            if mine.len() >= REMEMBER_THINGS {
                let mut mine = mine;
                mine.sort_unstable();
                for (_, id) in &mine[..mine.len() + 1 - REMEMBER_THINGS] {
                    ctx.db.remembered_thing().id().delete(*id);
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
    let chunks = living_rules::map::chunks_around(eye.at.0, eye.at.1, gather);
    let due: Vec<u32> = CHECKED.with(|c| {
        let mut c = c.borrow_mut();
        let m = c.entry(observer).or_default();
        m.retain(|ch, t| chunks.contains(ch) && now.saturating_sub(*t) < RECHECK_MS);
        let due: Vec<u32> = chunks.iter().copied().filter(|ch| !m.contains_key(ch)).collect();
        for ch in &due {
            m.insert(*ch, now);
        }
        due
    });
    for ch in due {
        for r in ctx.db.remembered_thing().by_observer_chunk().filter((observer, ch)).collect::<Vec<_>>() {
            let d = dist(eye.at, (r.x, r.y));
            if d > gather || seen(key(1, r.target)) {
                continue;
            }
            if eye.sees_at((r.x, r.y), d, 0.0, false) {
                ctx.db.remembered_thing().id().delete(r.id);
                common::diag(|| "scope:memory_gone", 1);
            }
        }
    }
}

/// A mind's noticing (`brain::noticed`): what it sees of sight-scoped structures (`visible`, the
/// scene's list after the sight test) is remembered by the same rule as a player's.
pub fn remember_seen(ctx: &ReducerContext, observer: u32, look: &Look, visible: &[(Structure, f32)], now: u64) {
    let mut keys: HashSet<u64> = HashSet::new();
    for (s, _) in visible {
        if !store::scoped_kind(&s.kind) {
            continue;
        }
        keys.insert(key(1, s.id));
        let t = seen_structure(ctx, s, 0, now);
        remember_thing(ctx, observer, &t, now);
    }
    recheck(ctx, observer, &look.eye(), look.gather, |k| keys.contains(&k), now);
}

// ---- looking a fire over ---------------------------------------------------------------------

/// `inspect` on a fire: how much fuel is left, kept (`fuel_seen`) and told. Returns the line.
pub fn inspect(ctx: &ReducerContext, me: u32, target: u64, now: u64) -> Result<String, String> {
    let s = store::structure(ctx, target).ok_or("it is gone")?;
    let sc = common::scripts(ctx);
    let t = sc.structure(&s.kind);
    let b = t.burns.clone().ok_or_else(|| format!("the {} burns no fuel", s.kind.replace('_', " ")))?;
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
    let kind = s.kind.replace('_', " ");
    Ok(if lit {
        format!("You look the {kind} over: about {} hours of {} left on it.", fuel_words(hours), b.fuel.replace('_', " "))
    } else {
        format!("You look the {kind} over: it is out, with no {} left on it.", b.fuel.replace('_', " "))
    })
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

/// The fuel my living character found on fires it looked over (`inspect`).
#[spacetimedb::view(accessor = my_fuel_seen, public, primary_key = id)]
pub fn my_fuel_seen(ctx: &ViewContext) -> Vec<FuelSeen> {
    crate::perception::living(ctx).map(|c| ctx.db.fuel_seen().observer().filter(c.id).collect()).unwrap_or_default()
}
