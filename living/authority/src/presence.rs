//! Presence: whether the person who plays a character is there, and who controls the
//! character while they are not (docs/PLAYER_MEMORY.md, "Presence and the offline character").
//!
//! - **Connections.** SpacetimeDB runs `client_connected` and `client_disconnected` for every
//!   connection, WebSocket or HTTP call alike, each with its `ConnectionId`; the host also runs
//!   `client_disconnected` at startup for every connection still recorded in `st_client`, so a
//!   server crash leaves none dangling (2.14.1 `host_controller.rs`, "Disconnect dangling
//!   clients"). Each open connection is a `connection` row, so several connections of one
//!   identity count exactly and a repeated event changes nothing.
//! - **Presence.** A played character's `presence` row says whether its person has a connection
//!   open now. It is private: the mind service reads it as the database owner, no client does.
//! - **Takeover.** When the last connection closes, the character stands as it is for the
//!   `takeover_s` law (a reload or an HTTP call between others is not leaving). Then the world's
//!   minds take it over: it becomes an AI character controlled by the mind service, lives under
//!   level of detail like any other, and the behaviour its minds installed before is installed
//!   again. What it lives meanwhile is kept for its person (`mind_consolidated` leaves a played
//!   character's experience rows in place).
//! - **Handback.** When a connection of its person opens, control goes back at once, inside
//!   `client_connected` (before the client subscribes): the minds' pending deliberation, decided
//!   acts and activity stop, their graph is kept on the presence row (it stays the
//!   character's), and the character waits for its person.

use crate::common;
use crate::tables::*;
use spacetimedb::{Identity, ReducerContext, Table};

/// Not pending.
const NEVER: u64 = u64::MAX;

fn open_connections(ctx: &ReducerContext, who: Identity) -> u32 {
    ctx.db.connection().identity().filter(who).count() as u32
}

#[spacetimedb::reducer(client_connected)]
pub fn client_connected(ctx: &ReducerContext) -> Result<(), String> {
    let now = common::now_ms(ctx);
    if let Some(id) = ctx.connection_id() {
        if ctx.db.connection().id().find(id).is_none() {
            ctx.db.connection().insert(Connection { id, identity: ctx.sender(), since_ms: now });
        }
    }
    adopt(ctx, ctx.sender(), now);
    settle(ctx, ctx.sender(), now);
    Ok(())
}

#[spacetimedb::reducer(client_disconnected)]
pub fn client_disconnected(ctx: &ReducerContext) -> Result<(), String> {
    if let Some(id) = ctx.connection_id() {
        ctx.db.connection().id().delete(id);
    }
    settle(ctx, ctx.sender(), common::now_ms(ctx));
    Ok(())
}

/// A character that joined before presence existed gets its row at its person's next connection.
fn adopt(ctx: &ReducerContext, who: Identity, now: u64) {
    let db = ctx.database_identity();
    if who == db || who == common::world(ctx).admin {
        return;
    }
    for c in ctx.db.character().controller().filter(who).filter(|c| c.alive && !c.ai) {
        if ctx.db.presence().id().find(c.id).is_none() {
            start(ctx, c.id, who, now);
        }
    }
}

/// A person's character begins (a join): its presence row.
pub fn start(ctx: &ReducerContext, id: u32, player: Identity, now: u64) {
    let connections = open_connections(ctx, player);
    let present = connections > 0;
    let takeover_ms = if present { NEVER } else { now + takeover_after(ctx) };
    ctx.db.presence().insert(Presence { id, player, connections, present, changed_ms: now, ai: false, control_ms: now, takeover_ms, ai_graph: String::new(), ai_plan: String::new() });
}

fn takeover_after(ctx: &ReducerContext) -> u64 {
    (common::laws(ctx).takeover_s * 1000.0) as u64
}

/// The person's connections changed: their characters' presence follows, and control comes
/// back at once when they return.
fn settle(ctx: &ReducerContext, who: Identity, now: u64) {
    let rows: Vec<Presence> = ctx.db.presence().player().filter(who).collect();
    if rows.is_empty() {
        return;
    }
    let n = open_connections(ctx, who);
    for mut p in rows {
        let before = p.clone();
        p.connections = n;
        if (n > 0) != p.present {
            p.present = n > 0;
            p.changed_ms = now;
        }
        if p.present {
            p.takeover_ms = NEVER;
            if p.ai {
                hand_back(ctx, &mut p, now);
            }
        } else if !p.ai && p.takeover_ms == NEVER {
            p.takeover_ms = now + takeover_after(ctx);
        }
        if p != before {
            ctx.db.presence().id().update(p);
        }
    }
}

/// The rules changed: pending takeovers are due `takeover_s` after their person left (an admin
/// action; one row per played character).
pub fn reschedule(ctx: &ReducerContext, takeover_s: f32) {
    for mut p in ctx.db.presence().iter().filter(|p| p.takeover_ms != NEVER).collect::<Vec<_>>() {
        p.takeover_ms = p.changed_ms + (takeover_s * 1000.0) as u64;
        ctx.db.presence().id().update(p);
    }
}

/// Once a second: characters whose person has been gone for the `takeover_s` law pass to the
/// world's minds (an index range of the due rows only).
pub fn housekeeping(ctx: &ReducerContext, now: u64) {
    let due: Vec<Presence> = ctx.db.presence().takeover_ms().filter(..=now).collect();
    for mut p in due {
        if open_connections(ctx, p.player) > 0 {
            p.takeover_ms = NEVER;
        } else {
            take_over(ctx, &mut p, now);
        }
        ctx.db.presence().id().update(p);
    }
}

fn take_over(ctx: &ReducerContext, p: &mut Presence, now: u64) {
    p.takeover_ms = NEVER;
    let Some(mut c) = ctx.db.character().id().find(p.id).filter(|c| c.alive) else { return };
    // The world's mind service, as for every resident: a
    // person's character lives on under a mind, with its past (with no mind service running
    // it lives on its behaviour graph, a deliberation pending).
    c.controller = common::world(ctx).admin;
    c.ai = true;
    ctx.db.character().id().update(c);
    p.ai = true;
    p.control_ms = now;
    crate::combat::invalidate_humans();
    // Its person sees nothing while away; a fresh set is made on return.
    crate::perception::forget(ctx, p.id, p.player);
    // Asked first: reinstalling a mind's graph counts as having just thought (`think_min_s`).
    crate::perceive::request_deliberation(ctx, p.id, "A quiet moment to take stock of how things are going.", now);
    // The behaviour its minds installed before is its own again.
    if !p.ai_graph.is_empty() {
        if let Err(e) = crate::mind::set_graph(ctx, p.id, &p.ai_graph, &p.ai_plan, "mind", now) {
            log::warn!("takeover of {}: the held graph no longer installs ({e})", p.id);
        }
    }
    log::info!("character {} passed to the minds (its person left)", p.id);
}

fn hand_back(ctx: &ReducerContext, p: &mut Presence, now: u64) {
    p.ai = false;
    p.control_ms = now;
    let Some(mut c) = ctx.db.character().id().find(p.id).filter(|c| c.alive) else { return };
    // The minds' behaviour stays the character's: kept for the next takeover, not run.
    if let Some(b) = ctx.db.brain().id().find(p.id).filter(|b| b.source == "mind") {
        p.ai_graph = b.graph;
        p.ai_plan = b.plan;
    }
    c.controller = p.player;
    c.ai = false;
    ctx.db.character().id().update(c);
    crate::perception::set_player(ctx, p.player, p.id);
    // What the minds had going stops: a pending thought, decided acts, the activity under way.
    ctx.db.deliberation().actor().delete(p.id);
    ctx.db.act_queue().actor().delete(p.id);
    // A committed move under way runs its course (`combat::committed`).
    if let Some(a) = ctx.db.activity().id().find(p.id).filter(|a| !crate::combat::committed(&crate::common::scripts(ctx), a)) {
        crate::act::cancel(ctx, a, now, None);
    }
    if let Err(e) = crate::mind::set_graph(ctx, p.id, crate::WAITING_GRAPH, crate::WAITING, "human", now) {
        log::warn!("handback of {}: {e}", p.id);
    }
    crate::combat::invalidate_humans();
    crate::perception::sweep_now(ctx, p.id, p.player, now);
    log::info!("character {} is its person's again", p.id);
}

/// A played character died: if the minds had it, it is its person's again (their dead
/// character, for the death screen), and its presence row goes.
pub fn died(ctx: &ReducerContext, c: &mut Character) {
    if let Some(p) = ctx.db.presence().id().find(c.id) {
        c.controller = p.player;
        c.ai = false;
        ctx.db.presence().id().delete(c.id);
    }
}

/// A character a person plays (alive, whoever controls it now).
pub fn played(ctx: &ReducerContext, id: u32) -> bool {
    ctx.db.presence().id().find(id).is_some()
}
