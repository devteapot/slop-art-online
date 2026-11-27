//! Stores looked into (perception parity, docs/PERCEPTION_PARITY_AUDIT.md, the `holds` row):
//! under the `perceived_holds_on` law, what a character knows a store (a storage, remains, a
//! trap) holds is only what it saw inside, in `seen_store`.
//!
//! A look is the sight of a store's inside from beside it (within [`LOOK_M`], nearer than any
//! sight; a store is seen by distance, as the scene sees structures): its true contents then,
//! written as the character's own row. Looks are taken at a mind's noticing (`brain::noticed`),
//! at a player's character's perception sweep (`perception::sweep_one`), and whenever a graph
//! asks `holds` of a store beside it: the same rule for every controller. A remembered row
//! changes only by another look, so what was taken or put there out of sight is not known.
//!
//! What a graph's `{"nearest": {"kind": …, "holds": item}}` then reads ([`holds`]):
//! - beside the store: what is in it now (and the look is written);
//! - remembered with the item: it holds it (a trip there corrects a stale belief);
//! - remembered without it: it does not, for [`STALE_MS`] after the look; older, it may have
//!   been filled since, so it is worth another look;
//! - never looked into: it may hold anything, so it is worth a look (as `can` assumes of
//!   what another holds under `perceived_can_on`).
//!
//! Off, no row is written or read: a graph's `holds` reads the store's true contents.

use crate::common::{self, dist};
use crate::tables::*;
use spacetimedb::{ReducerContext, Table};
use std::cell::RefCell;
use std::collections::BTreeMap;

/// How near a store one must be to see what is inside it (m): beside it (take and store reach 1.5 m).
pub const LOOK_M: f32 = 2.5;
/// At most this many stores remembered a character; the longest unseen goes first.
pub const PER_ACTOR: usize = 32;
/// A store remembered without an item is believed without it for this long (ms).
pub const STALE_MS: u64 = 600_000;
/// A look that changes nothing rewrites its time at most this often (ms).
pub const REFRESH_MS: u64 = 60_000;
/// One sweep of the stores round a character at most this often (ms; a graph's `holds` looks at once).
const SWEEP_MS: u64 = 1_000;

thread_local! {
    /// Each character's last sweep (a cache: lost on reload, it only looks again).
    static SWEPT: RefCell<BTreeMap<u32, u64>> = const { RefCell::new(BTreeMap::new()) };
}

/// Whether a structure of `kind` holds things one may look into.
pub fn is_store(ctx: &ReducerContext, kind: &str) -> bool {
    kind == "remains" || kind == "trap" || common::scripts(ctx).structure(kind).holds.is_some()
}

/// `me` looks into store `s` from beside it: its row now says what is in it.
pub fn look_one(ctx: &ReducerContext, me: u32, s: &Structure, now: u64) {
    let (items, qty): (Vec<String>, Vec<u32>) = common::inv_list(ctx, STRUCTURE_BIT | s.id).into_iter().unzip();
    match ctx.db.seen_store().by_actor_structure().filter((me, s.id)).next() {
        Some(mut r) => {
            if r.items != items || r.qty != qty || now.saturating_sub(r.seen_ms) >= REFRESH_MS {
                r.items = items;
                r.qty = qty;
                r.seen_ms = now;
                ctx.db.seen_store().id().update(r);
            }
        }
        None => {
            make_room(ctx, me);
            ctx.db.seen_store().insert(SeenStore { id: 0, actor: me, structure: s.id, items, qty, seen_ms: now });
        }
    }
}

/// `me`, standing at `at`, looks into every store beside it (at most once per [`SWEEP_MS`]).
pub fn look(ctx: &ReducerContext, me: u32, at: (f32, f32), now: u64) {
    let due = SWEPT.with(|l| {
        let mut l = l.borrow_mut();
        let due = l.get(&me).is_none_or(|t| now.saturating_sub(*t) >= SWEEP_MS);
        if due {
            l.insert(me, now);
        }
        due
    });
    if !due {
        return;
    }
    let _span = common::span("stores.look");
    for (s, _) in common::structures_near(ctx, at, LOOK_M) {
        if is_store(ctx, &s.kind) {
            look_one(ctx, me, &s, now);
        }
    }
}

/// What `me`, standing at `at`, knows store `s` holds of `item`: `Some(true)` or `Some(false)`
/// when it sees or remembers, `None` when it does not know (see the module's rules). A look
/// is taken when the store is beside it.
pub fn known(ctx: &ReducerContext, me: u32, at: (f32, f32), s: &Structure, item: &str, now: u64) -> Option<bool> {
    if dist(at, (s.x, s.y)) <= LOOK_M {
        look_one(ctx, me, s, now);
        return Some(common::inv_count(ctx, STRUCTURE_BIT | s.id, item) >= 1);
    }
    let r = ctx.db.seen_store().by_actor_structure().filter((me, s.id)).next()?;
    if r.items.iter().zip(&r.qty).any(|(i, q)| i == item && *q >= 1) {
        Some(true)
    } else if now.saturating_sub(r.seen_ms) < STALE_MS {
        Some(false)
    } else {
        None
    }
}

/// A graph's `holds` under the law: what it knows, and a store it does not know is worth a look.
pub fn holds(ctx: &ReducerContext, me: u32, at: (f32, f32), s: &Structure, item: &str, now: u64) -> bool {
    known(ctx, me, at, s, item, now).unwrap_or(true)
}

/// What `me` last saw in store `s` and when, if it ever looked (a mind's scene).
pub fn remembered(ctx: &ReducerContext, me: u32, s: u64) -> Option<SeenStore> {
    ctx.db.seen_store().by_actor_structure().filter((me, s)).next()
}

/// Below [`PER_ACTOR`] rows before an insert: the rows seen longest ago go.
fn make_room(ctx: &ReducerContext, actor: u32) {
    let mut mine: Vec<(u64, u64)> = ctx.db.seen_store().actor().filter(actor).map(|r| (r.seen_ms, r.id)).collect();
    if mine.len() < PER_ACTOR {
        return;
    }
    mine.sort_unstable();
    let over = mine.len() + 1 - PER_ACTOR;
    for (_, id) in mine.into_iter().take(over) {
        ctx.db.seen_store().id().delete(id);
    }
}
