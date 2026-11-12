//! Handles for figures too far away to make out (far-handle, docs/STRANGERS.md §1).
//!
//! A person the `perceived_of` law marks `far` for an observer is named in that observer's
//! mind by a handle of the sighting, not by the person's id: their id would tie them to a name
//! through the relations, the community line or memory of the same prompt. The handle reaches
//! the person wherever a mind names it (graph and act targets, speech). Once the observer can
//! make them out, the observer is told whom the handle was, and its memory joins the two.
//! Players' views keep real ids: the client draws by id, and this concerns minds.

use crate::tables::*;
use living_rules::script::FAR_HANDLE_BASE;
use spacetimedb::{ReducerContext, Table};

/// A figure out of the observer's sight this long is a new sighting with a new handle.
pub const SIGHTING_GAP_MS: u64 = 60_000;
/// A handle's `last_ms` is written at most this often while the figure stays in sight.
const TOUCH_MS: u64 = 10_000;
/// Rows kept per observer (the oldest go first).
const KEEP: usize = 64;

/// Whether `id` is a far figure's handle (never a character, structure or resource id).
pub fn is_handle(id: u32) -> bool {
    id >= FAR_HANDLE_BASE
}

/// The handle of `target` as a figure `observer` cannot make out now: the current sighting's,
/// or a new one.
pub fn handle_for(ctx: &ReducerContext, observer: u32, target: u32, now: u64) -> u32 {
    let current = ctx.db.far_handle().by_observer_target().filter((observer, target)).filter(|h| h.made_out_ms == 0 && now.saturating_sub(h.last_ms) <= SIGHTING_GAP_MS).max_by_key(|h| h.id);
    let row = match current {
        Some(mut h) => {
            if now.saturating_sub(h.last_ms) >= TOUCH_MS {
                h.last_ms = now;
                ctx.db.far_handle().id().update(h.clone());
            }
            h
        }
        None => {
            let h = ctx.db.far_handle().insert(FarHandle { id: 0, observer, target, first_ms: now, last_ms: now, made_out_ms: 0 });
            prune(ctx, observer);
            h
        }
    };
    FAR_HANDLE_BASE.saturating_add(row.id as u32)
}

/// Whom `id` names for `observer`: the person behind one of its own handles, or `id` itself. A
/// handle of another observer's, or one no longer kept, names no one (0).
pub fn resolve(ctx: &ReducerContext, observer: u32, id: u32) -> u32 {
    if !is_handle(id) {
        return id;
    }
    ctx.db.far_handle().id().find((id - FAR_HANDLE_BASE) as u64).filter(|h| h.observer == observer).map_or(0, |h| h.target)
}

/// `observer` can make `target` out now: each of its handles for them that is not joined yet is
/// joined, and the observer is told whom it was, in an experience whose subject is the person
/// and object the handle ("Bram is the one you saw too far away to make out."), so its memory
/// can join the figure to the person.
pub fn made_out(ctx: &ReducerContext, observer: &Character, target: u32, now: u64) {
    let open: Vec<FarHandle> = ctx.db.far_handle().by_observer_target().filter((observer.id, target)).filter(|h| h.made_out_ms == 0).collect();
    for mut h in open {
        h.made_out_ms = now;
        ctx.db.far_handle().id().update(h.clone());
        let who = crate::common::label_cap(ctx, observer, target);
        let at = ctx.db.body().id().find(target).map(|b| crate::common::pos(&b, now)).unwrap_or((0.0, 0.0));
        crate::perceive::percept(ctx, observer, now, "made_out", target, FAR_HANDLE_BASE.saturating_add(h.id as u32), at, format!("{who} is the one you saw too far away to make out."), 0.3);
    }
}

/// How `observer` (a mind's character) refers by id to `target` now: a handle while it cannot
/// make them out, else their id (joining any handle it had for them).
pub fn id_for(ctx: &ReducerContext, observer: &Character, target: &Character, now: u64) -> u32 {
    if target.id == observer.id || target.kind != "person" {
        return target.id;
    }
    if crate::perception::regard(ctx, observer, target, now).far {
        handle_for(ctx, observer.id, target.id, now)
    } else {
        made_out(ctx, observer, target.id, now);
        target.id
    }
}

/// Keep at most `KEEP` rows per observer, dropping joined and long-unseen ones first.
fn prune(ctx: &ReducerContext, observer: u32) {
    let mut rows: Vec<FarHandle> = ctx.db.far_handle().observer().filter(observer).collect();
    if rows.len() <= KEEP {
        return;
    }
    rows.sort_by_key(|h| (h.made_out_ms == 0, h.last_ms));
    for h in &rows[..rows.len() - KEEP] {
        ctx.db.far_handle().id().delete(h.id);
    }
}
