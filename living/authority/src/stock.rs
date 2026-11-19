//! Remembered resources (talk-places, docs/COMMUNICATION.md §20): what a character has seen of
//! a kind of resource at a spot, and when, in `seen_stock`.
//!
//! A look is the scene's own rule for resources: every node within the character's sight
//! (`common::resources_near`, as the scene and the region line "here: 10 berry bush" count
//! them). A kind seen with something to gather that no remembered row holds becomes a row: its
//! nearest [`NODES`] with stock, the middle of them, how many, and the time. A remembered row
//! changes only by what the character itself sees again:
//! - any of its nodes in view with something on it: still there (its time is refreshed at most
//!   every [`REFRESH_MS`], and a gone row comes back);
//! - every one of its nodes in view and none with anything left: gone, at that look's time,
//!   told once ("Nothing is left to gather on the berry bush around (416, 239) …");
//! - only some in view, all bare: nothing is concluded (the rest may still bear).
//!
//! A patch stripped out of sight stays believed. Looks run at most once per [`LOOK_MS`] in one
//! chunk, and at once on entering another; for a mind at its noticing (`brain::noticed`), for
//! a player's character at its perception sweep (`perception::sweep_one`): the same rule for
//! every controller.

use crate::common;
use crate::perceive::percept;
use crate::tables::*;
use spacetimedb::{ReducerContext, Table};
use std::cell::RefCell;
use std::collections::HashMap;

/// At most this many nodes are remembered for one row.
pub const NODES: usize = 12;
/// At most this many rows a character; the longest unseen goes first.
pub const PER_ACTOR: usize = 24;
/// One look per chunk at most this often (another chunk is looked at at once).
pub const LOOK_MS: u64 = 30_000;
/// A sighting that changes nothing rewrites its time at most this often.
pub const REFRESH_MS: u64 = 120_000;

thread_local! {
    /// Each character's last look: its chunk and time (a cache: lost on reload, it only looks again).
    static LOOKED: RefCell<HashMap<u32, (u32, u64)>> = RefCell::new(HashMap::new());
}

fn bears(ctx: &ReducerContext, n: &ResourceNode, now: u64) -> bool {
    common::amount_now(ctx, &common::stock_of(ctx, n), now) >= 1.0
}

/// A look by `me` standing at `at`, seeing `sight()` metres (asked only when one is due).
pub fn look(ctx: &ReducerContext, me: &Character, at: (f32, f32), sight: impl FnOnce() -> f32, now: u64) {
    let chunk = living_rules::map::chunk_of(at.0, at.1);
    let due = LOOKED.with(|l| {
        let mut l = l.borrow_mut();
        let due = l.get(&me.id).map_or(true, |(c, t)| *c != chunk || now.saturating_sub(*t) >= LOOK_MS);
        if due {
            l.insert(me.id, (chunk, now));
        }
        due
    });
    if !due {
        return;
    }
    let sight = sight();
    if sight <= 0.0 {
        return;
    }
    let _span = common::span("stock.look");
    let near = common::resources_near(ctx, at, sight);
    let mut rows: Vec<SeenStock> = living_rules::map::chunks_around(at.0, at.1, sight + 8.0).into_iter().flat_map(|c| ctx.db.seen_stock().by_actor_chunk().filter((me.id, c)).collect::<Vec<_>>()).collect();
    for row in rows.iter_mut() {
        let in_view: Vec<&ResourceNode> = row.nodes.iter().filter_map(|id| near.iter().find(|(n, _)| n.id == *id).map(|(n, _)| n)).collect();
        if in_view.is_empty() {
            continue;
        }
        let bearing = in_view.iter().filter(|n| bears(ctx, n, now)).count() as u32;
        let all = in_view.len() == row.nodes.len();
        if bearing > 0 {
            let count = if all { bearing } else { row.count.max(bearing) };
            if row.gone_ms != 0 || count != row.count || now.saturating_sub(row.seen_ms) >= REFRESH_MS {
                row.count = count;
                row.seen_ms = now;
                row.gone_ms = 0;
                ctx.db.seen_stock().id().update(row.clone());
            }
        } else if all {
            let first = row.gone_ms == 0;
            if first || now.saturating_sub(row.gone_ms) >= REFRESH_MS {
                row.gone_ms = now;
                ctx.db.seen_stock().id().update(row.clone());
            }
            if first {
                let w = common::world(ctx);
                let text = format!(
                    "Nothing is left to gather on the {} around ({:.0}, {:.0}): {} had some when you saw them, {}.",
                    row.kind.replace('_', " "),
                    row.x,
                    row.y,
                    row.count,
                    living_rules::day_clock(row.seen_ms, w.epoch_ms, w.day_ms)
                );
                percept(ctx, me, now, "saw", 0, 0, (row.x, row.y), text, 0.3);
            }
        }
    }
    // Kinds in view with something to gather that no remembered row holds.
    let mut kinds: Vec<(&str, Vec<&ResourceNode>)> = Vec::new();
    for (n, _) in &near {
        if !bears(ctx, n, now) {
            continue;
        }
        match kinds.iter_mut().find(|k| k.0 == n.kind) {
            Some(k) => k.1.push(n),
            None => kinds.push((&n.kind, vec![n])),
        }
    }
    for (kind, nodes) in kinds {
        if rows.iter().any(|r| r.kind == kind && nodes.iter().any(|n| r.nodes.contains(&n.id))) {
            continue;
        }
        let nodes: Vec<&ResourceNode> = nodes.into_iter().take(NODES).collect();
        let x = nodes.iter().map(|n| n.x).sum::<f32>() / nodes.len() as f32;
        let y = nodes.iter().map(|n| n.y).sum::<f32>() / nodes.len() as f32;
        make_room(ctx, me.id);
        ctx.db.seen_stock().insert(SeenStock {
            id: 0,
            actor: me.id,
            chunk: living_rules::map::chunk_of(x, y),
            kind: kind.to_string(),
            x,
            y,
            count: nodes.len() as u32,
            nodes: nodes.iter().map(|n| n.id).collect(),
            seen_ms: now,
            gone_ms: 0,
        });
    }
}

/// Below [`PER_ACTOR`] rows before an insert: the rows seen longest ago go.
fn make_room(ctx: &ReducerContext, actor: u32) {
    let mut mine: Vec<(u64, u64)> = ctx.db.seen_stock().actor().filter(actor).map(|r| (r.seen_ms.max(r.gone_ms), r.id)).collect();
    if mine.len() < PER_ACTOR {
        return;
    }
    mine.sort_unstable();
    let over = mine.len() + 1 - PER_ACTOR;
    for (_, id) in mine.into_iter().take(over) {
        ctx.db.seen_stock().id().delete(id);
    }
}
