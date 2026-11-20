//! Where structures, gates and resource nodes are kept (docs/FEED_SCOPING.md, "Authority
//! shapes"). Until a world's feeds are scoped they are the public `structure`, `gate` and
//! `resource_node` tables, as before; at stage 2 every row moves, with its id, to the private
//! `structure_held`, `gate_held` and `resource_held`, and the public tables stay empty. From
//! stage 1 on, `map_structure` and `map_resource` carry the public map (architecture and
//! landmarks), kept here on every write. All authority code reads and writes these rows through
//! this module, so the stage is decided in one place.
//!
//! The stage follows the `feed_scope_on` law (`step`, once a second in housekeeping): on, a
//! world at 0 goes to 1 and, `feed_scope_grace_s` later, to 2. Off at 1 goes back to 0. Off at 2
//! changes nothing (the feeds stay closed: no fallback re-exposes current rows).

use crate::common;
use crate::tables::*;
use spacetimedb::{ReducerContext, Table};
use std::cell::Cell;

/// Kinds whose structure is public map knowledge (the shell; any state it has, a gate's open
/// or shut, a furnace's fire, is still seen only in sight). Every other kind, a seed's or a
/// script's own among them, is sight-scoped.
pub const MAP_KINDS: &[&str] = &["shelter", "house", "hall", "workshop", "market", "inn", "smokehouse", "furnace", "gate"];

pub fn on_map(kind: &str) -> bool {
    MAP_KINDS.contains(&kind)
}

/// A kind seen only in sight (remains, storage and caches, signs, traps, live brush, fires,
/// lamps, and anything the allowlist does not name).
pub fn scoped_kind(kind: &str) -> bool {
    !on_map(kind)
}

thread_local! {
    /// The stage as read in this transaction (its stamp, the stage).
    static STAGE: Cell<(i64, u8)> = const { Cell::new((0, 0)) };
    /// A world at stage 2 whose law was turned off has been told so (once per instance).
    static WARNED: Cell<bool> = const { Cell::new(false) };
}

/// The world's feed stage now (0, 1 or 2).
pub fn stage(ctx: &ReducerContext) -> u8 {
    let t = common::stamp(ctx);
    STAGE.with(|s| {
        let (at, v) = s.get();
        if at == t {
            return v;
        }
        let v = ctx.db.feed_scope().id().find(0).map_or(0, |r| r.stage);
        s.set((t, v));
        v
    })
}

/// Sight-scoped work runs: noticing, scenes and players' copies use the shared sight test.
pub fn sighted(ctx: &ReducerContext) -> bool {
    stage(ctx) >= 1
}

/// The canonical rows are the private held tables.
pub fn held(ctx: &ReducerContext) -> bool {
    stage(ctx) == 2
}

fn set_stage(ctx: &ReducerContext, stage: u8, now: u64) {
    let row = FeedScope { id: 0, stage, since_ms: now };
    if ctx.db.feed_scope().id().find(0).is_some() {
        ctx.db.feed_scope().id().update(row);
    } else {
        ctx.db.feed_scope().insert(row);
    }
    STAGE.with(|s| s.set((common::stamp(ctx), stage)));
    crate::scope::clear_memory();
    common::invalidate_structures(ctx);
    common::invalidate_resources(ctx, None);
    common::invalidate_map();
}

fn next_id(ctx: &ReducerContext, name: &str) -> u64 {
    let mut row = ctx.db.id_seq().name().find(name.to_string()).unwrap_or(IdSeq { name: name.to_string(), next: 1 });
    let id = row.next.max(1);
    row.next = id + 1;
    if ctx.db.id_seq().name().find(name.to_string()).is_some() {
        ctx.db.id_seq().name().update(row);
    } else {
        ctx.db.id_seq().insert(row);
    }
    id
}

// ---- structures ------------------------------------------------------------------------------

pub fn structure(ctx: &ReducerContext, id: u64) -> Option<Structure> {
    if held(ctx) {
        ctx.db.structure_held().id().find(id)
    } else {
        ctx.db.structure().id().find(id)
    }
}

/// The structures of one chunk, read from the table (callers on hot paths use
/// `common::chunk_structures`, its cached list).
pub fn structures_in(ctx: &ReducerContext, chunk: u32) -> Vec<Structure> {
    if held(ctx) {
        ctx.db.structure_held().chunk().filter(chunk).collect()
    } else {
        ctx.db.structure().chunk().filter(chunk).collect()
    }
}

/// Every structure (world creation and diagnostics only).
pub fn all_structures(ctx: &ReducerContext) -> Vec<Structure> {
    if held(ctx) {
        ctx.db.structure_held().iter().collect()
    } else {
        ctx.db.structure().iter().collect()
    }
}

fn map_row(s: &Structure) -> MapStructure {
    MapStructure { id: s.id, kind: s.kind.clone(), x: s.x, y: s.y, chunk: s.chunk }
}

/// Keep the public map and the owner index in step with one structure row (`None`: gone).
fn project_structure(ctx: &ReducerContext, id: u64, row: Option<&Structure>) {
    let want = row.filter(|s| on_map(&s.kind)).map(map_row);
    match (ctx.db.map_structure().id().find(id), want) {
        (Some(old), Some(new)) if old == new => {}
        (Some(_), Some(new)) => {
            ctx.db.map_structure().id().update(new);
        }
        (None, Some(new)) => {
            ctx.db.map_structure().insert(new);
        }
        (Some(_), None) => {
            ctx.db.map_structure().id().delete(id);
        }
        (None, None) => {}
    }
    let owned = row.filter(|s| on_map(&s.kind) && s.owner != 0).map(|s| OwnedBy { structure: s.id, owner: s.owner, kind: s.kind.clone() });
    match (ctx.db.owned_by().structure().find(id), owned) {
        (Some(old), Some(new)) if old.owner == new.owner && old.kind == new.kind => {}
        (Some(_), Some(new)) => {
            ctx.db.owned_by().structure().update(new);
            crate::scope::owners_changed();
        }
        (None, Some(new)) => {
            ctx.db.owned_by().insert(new);
            crate::scope::owners_changed();
        }
        (Some(_), None) => {
            ctx.db.owned_by().structure().delete(id);
            crate::scope::owners_changed();
        }
        (None, None) => {}
    }
}

pub fn insert_structure(ctx: &ReducerContext, mut s: Structure) -> Structure {
    let row = if held(ctx) {
        s.id = next_id(ctx, "structure");
        ctx.db.structure_held().insert(s)
    } else {
        ctx.db.structure().insert(s)
    };
    if sighted(ctx) {
        project_structure(ctx, row.id, Some(&row));
    }
    row
}

pub fn update_structure(ctx: &ReducerContext, s: Structure) {
    if sighted(ctx) {
        project_structure(ctx, s.id, Some(&s));
    }
    if held(ctx) {
        ctx.db.structure_held().id().update(s);
    } else {
        ctx.db.structure().id().update(s);
    }
}

pub fn delete_structure(ctx: &ReducerContext, id: u64) {
    if sighted(ctx) {
        project_structure(ctx, id, None);
    }
    if held(ctx) {
        ctx.db.structure_held().id().delete(id);
    } else {
        ctx.db.structure().id().delete(id);
    }
}

// ---- gates -----------------------------------------------------------------------------------

pub fn gate(ctx: &ReducerContext, id: u64) -> Option<Gate> {
    if held(ctx) {
        ctx.db.gate_held().id().find(id)
    } else {
        ctx.db.gate().id().find(id)
    }
}

pub fn all_gates(ctx: &ReducerContext) -> Vec<Gate> {
    if held(ctx) {
        ctx.db.gate_held().iter().collect()
    } else {
        ctx.db.gate().iter().collect()
    }
}

pub fn insert_gate(ctx: &ReducerContext, g: Gate) {
    if held(ctx) {
        ctx.db.gate_held().insert(g);
    } else {
        ctx.db.gate().insert(g);
    }
}

pub fn update_gate(ctx: &ReducerContext, g: Gate) {
    if held(ctx) {
        ctx.db.gate_held().id().update(g);
    } else {
        ctx.db.gate().id().update(g);
    }
}

// ---- resource nodes --------------------------------------------------------------------------

pub fn resource(ctx: &ReducerContext, id: u64) -> Option<ResourceNode> {
    if held(ctx) {
        ctx.db.resource_held().id().find(id)
    } else {
        ctx.db.resource_node().id().find(id)
    }
}

pub fn resources_in(ctx: &ReducerContext, chunk: u32) -> Vec<ResourceNode> {
    if held(ctx) {
        ctx.db.resource_held().chunk().filter(chunk).collect()
    } else {
        ctx.db.resource_node().chunk().filter(chunk).collect()
    }
}

pub fn all_resources(ctx: &ReducerContext) -> Vec<ResourceNode> {
    if held(ctx) {
        ctx.db.resource_held().iter().collect()
    } else {
        ctx.db.resource_node().iter().collect()
    }
}

fn landmark(n: &ResourceNode) -> MapResource {
    MapResource { id: n.id, kind: n.kind.clone(), x: n.x, y: n.y, chunk: n.chunk }
}

pub fn insert_resource(ctx: &ReducerContext, mut n: ResourceNode) -> ResourceNode {
    let row = if held(ctx) {
        n.id = next_id(ctx, "resource");
        ctx.db.resource_held().insert(n)
    } else {
        ctx.db.resource_node().insert(n)
    };
    if sighted(ctx) {
        ctx.db.map_resource().insert(landmark(&row));
    }
    row
}

pub fn update_resource(ctx: &ReducerContext, n: ResourceNode) {
    if sighted(ctx) {
        let want = landmark(&n);
        match ctx.db.map_resource().id().find(n.id) {
            Some(old) if old == want => {}
            Some(_) => {
                ctx.db.map_resource().id().update(want);
            }
            None => {
                ctx.db.map_resource().insert(want);
            }
        }
    }
    if held(ctx) {
        ctx.db.resource_held().id().update(n);
    } else {
        ctx.db.resource_node().id().update(n);
    }
}

// ---- lots ------------------------------------------------------------------------------------

/// The structure at a lot's door (0: none), wherever the link is kept.
pub fn lot_structure(ctx: &ReducerContext, lot: &Lot) -> u64 {
    if held(ctx) {
        ctx.db.lot_door().lot().find(lot.id).map_or(0, |d| d.structure)
    } else {
        lot.structure
    }
}

// ---- the cutover -----------------------------------------------------------------------------

/// Follow the `feed_scope_on` law (housekeeping, once a second).
pub fn step(ctx: &ReducerContext, now: u64) {
    let laws = common::laws(ctx);
    let row = ctx.db.feed_scope().id().find(0);
    let (st, since) = row.as_ref().map_or((0, 0), |r| (r.stage, r.since_ms));
    match (laws.feed_scope_on, st) {
        (true, 0) => begin(ctx, now),
        (true, 1) if now.saturating_sub(since) as f32 >= laws.feed_scope_grace_s * 1000.0 => close(ctx, now),
        (false, 1) => revert(ctx, now),
        // The scoped rows go one housekeeping step after the stage went back to 0, so a client
        // has them while it subscribes the legacy set again (make-before-break).
        (false, 0) if row.is_some() && leftover(ctx) => clear(ctx),
        (false, 2) => {
            if !WARNED.with(|w| w.replace(true)) {
                log::warn!("feed scope: the law is off but this world's legacy feeds are closed (stage 2 is latched); nothing is re-exposed");
            }
        }
        _ => {}
    }
}

/// Stage 0 to 1: the public map is written beside the legacy feeds; sight-scoped work starts
/// (each player's copies at its next sweep).
fn begin(ctx: &ReducerContext, now: u64) {
    let _span = common::span("feed_scope.begin");
    // Rows a revert left for a step (the law turned on again within it) are written afresh.
    if leftover(ctx) {
        clear(ctx);
    }
    let mut n = (0u32, 0u32);
    for s in ctx.db.structure().iter() {
        if on_map(&s.kind) {
            ctx.db.map_structure().insert(map_row(&s));
            n.0 += 1;
            if s.owner != 0 {
                ctx.db.owned_by().insert(OwnedBy { structure: s.id, owner: s.owner, kind: s.kind.clone() });
            }
        }
    }
    for r in ctx.db.resource_node().iter() {
        ctx.db.map_resource().insert(landmark(&r));
        n.1 += 1;
    }
    set_stage(ctx, 1, now);
    crate::scope::owners_changed();
    log::info!("feed scope: stage 1 ({} map structures, {} landmarks); the legacy feeds close in {} s", n.0, n.1, common::laws(ctx).feed_scope_grace_s);
}

/// Stage 1 to 2: every canonical row moves to its private table with its id, the public ones
/// are emptied and lots stop naming their door structure. One transaction.
fn close(ctx: &ReducerContext, now: u64) {
    let _span = common::span("feed_scope.close");
    let structures: Vec<Structure> = ctx.db.structure().iter().collect();
    let gates: Vec<Gate> = ctx.db.gate().iter().collect();
    let resources: Vec<ResourceNode> = ctx.db.resource_node().iter().collect();
    let top_s = structures.iter().map(|s| s.id).max().unwrap_or(0);
    let top_r = resources.iter().map(|r| r.id).max().unwrap_or(0);
    for s in &structures {
        ctx.db.structure().id().delete(s.id);
    }
    for s in structures.iter().cloned() {
        ctx.db.structure_held().insert(s);
    }
    let n_gates = gates.len();
    for g in gates {
        ctx.db.gate().id().delete(g.id);
        ctx.db.gate_held().insert(g);
    }
    for r in &resources {
        ctx.db.resource_node().id().delete(r.id);
    }
    for r in resources.iter().cloned() {
        ctx.db.resource_held().insert(r);
    }
    for (name, top) in [("structure", top_s), ("resource", top_r)] {
        let row = IdSeq { name: name.into(), next: top + 1 };
        if ctx.db.id_seq().name().find(name.to_string()).is_some() {
            ctx.db.id_seq().name().update(row);
        } else {
            ctx.db.id_seq().insert(row);
        }
    }
    let lots: Vec<Lot> = ctx.db.lot().iter().filter(|l| l.structure != 0).collect();
    let n_lots = lots.len();
    for mut l in lots {
        ctx.db.lot_door().insert(LotDoor { lot: l.id, structure: l.structure });
        l.structure = 0;
        ctx.db.lot().id().update(l);
    }
    set_stage(ctx, 2, now);
    log::info!("feed scope: stage 2 ({} structures, {} gates, {} resource nodes and {} lot doors held privately); the legacy feeds are closed", structures.len(), n_gates, resources.len(), n_lots);
}

/// Stage 1 back to 0 (the law turned off before the legacy feeds closed): the stage first, so
/// clients switch back while the scoped rows are still there; the rows go at the next step
/// (`clear`). What characters remember stays theirs.
fn revert(ctx: &ReducerContext, now: u64) {
    set_stage(ctx, 0, now);
    log::info!("feed scope: back to stage 0 (the law went off before the legacy feeds closed); the scoped rows go at the next step");
}

/// Scoped rows written at stage 1 are still there.
fn leftover(ctx: &ReducerContext) -> bool {
    ctx.db.map_structure().iter().next().is_some() || ctx.db.map_resource().iter().next().is_some() || ctx.db.thing_seen().iter().next().is_some() || ctx.db.owner_seen().iter().next().is_some()
}

/// The scoped rows of stage 1 go (a step after a revert, or before a new begin).
fn clear(ctx: &ReducerContext) {
    let _span = common::span("feed_scope.clear");
    for id in ctx.db.thing_seen().iter().map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.thing_seen().id().delete(id);
    }
    for id in ctx.db.owner_seen().iter().map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.owner_seen().id().delete(id);
    }
    for id in ctx.db.map_structure().iter().map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.map_structure().id().delete(id);
    }
    for id in ctx.db.map_resource().iter().map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.map_resource().id().delete(id);
    }
    for id in ctx.db.owned_by().iter().map(|r| r.structure).collect::<Vec<_>>() {
        ctx.db.owned_by().structure().delete(id);
    }
    crate::scope::clear_memory();
    crate::scope::owners_changed();
    log::info!("feed scope: the scoped rows of stage 1 are cleared");
}
