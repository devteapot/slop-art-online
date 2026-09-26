//! Kinematic motion. A body moves along straight segments between waypoints; its row is
//! rewritten only at waypoints and chunk crossings, so cost scales with path events,
//! not with tick rate or population.

use crate::tables::*;
use crate::common::{self, dist, pos};
use living_rules::map::{chunk_of, CHUNK};
use spacetimedb::{ReducerContext, Table};

pub const IDLE: u64 = u64::MAX;

fn begin_segment(b: &mut Body, now: u64) {
    loop {
        let Some(w) = b.path.first().copied() else {
            b.vx = 0.0;
            b.vy = 0.0;
            b.next_ms = IDLE;
            b.chunk = chunk_of(b.x, b.y);
            return;
        };
        let d = dist((b.x, b.y), (w.x, w.y));
        if d < 0.02 {
            b.x = w.x;
            b.y = w.y;
            b.path.remove(0);
            continue;
        }
        let speed = b.speed.max(0.1);
        b.vx = (w.x - b.x) / d * speed;
        b.vy = (w.y - b.y) / d * speed;
        b.t_ms = now;
        b.chunk = chunk_of(b.x, b.y);
        let arrive = now + (d / speed * 1000.0).ceil() as u64;
        // Time until the body leaves its current chunk.
        let cx = (b.x.max(0.0) as u32 / CHUNK) as f32 * CHUNK as f32;
        let cy = (b.y.max(0.0) as u32 / CHUNK) as f32 * CHUNK as f32;
        let tx = if b.vx > 0.0 {
            (cx + CHUNK as f32 - b.x) / b.vx
        } else if b.vx < 0.0 {
            (b.x - cx) / -b.vx
        } else {
            f32::INFINITY
        };
        let ty = if b.vy > 0.0 {
            (cy + CHUNK as f32 - b.y) / b.vy
        } else if b.vy < 0.0 {
            (b.y - cy) / -b.vy
        } else {
            f32::INFINITY
        };
        let cross = tx.min(ty);
        b.next_ms = if cross.is_finite() {
            arrive.min(now + ((cross * 1000.0) as u64).max(20) + 5)
        } else {
            arrive
        };
        return;
    }
}

/// Plan and start a path to `to`. Fails when the destination is unreachable.
pub fn start_move(ctx: &ReducerContext, id: u32, to: (f32, f32), speed: f32, now: u64) -> Result<(), String> {
    let Some(mut b) = ctx.db.body().id().find(id) else {
        return Err("no body".into());
    };
    let map = common::map(ctx);
    let p = pos(&b, now);
    let dest = if map.at(to.0, to.1).walkable() {
        to
    } else {
        map.nearest_walkable(to.0, to.1).ok_or("destination unreachable")?
    };
    let path = map.path(p, dest, 6_000).ok_or("no path there")?;
    b.x = p.0;
    b.y = p.1;
    b.t_ms = now;
    b.speed = speed;
    b.path = path.into_iter().map(|(x, y)| Waypoint { x, y }).collect();
    begin_segment(&mut b, now);
    ctx.db.body().id().update(b);
    Ok(())
}

pub fn stop(ctx: &ReducerContext, id: u32, now: u64) {
    if let Some(mut b) = ctx.db.body().id().find(id) {
        if b.next_ms == IDLE && b.path.is_empty() {
            return;
        }
        let p = pos(&b, now);
        b.x = p.0;
        b.y = p.1;
        b.t_ms = now;
        b.path.clear();
        begin_segment(&mut b, now);
        ctx.db.body().id().update(b);
    }
}

/// Process one due body. Returns true when it reached the end of its path.
pub fn advance(ctx: &ReducerContext, mut b: Body, now: u64) -> bool {
    let p = pos(&b, now);
    b.x = p.0;
    b.y = p.1;
    b.t_ms = now;
    if let Some(w) = b.path.first().copied() {
        if dist(p, (w.x, w.y)) < 0.05 {
            b.x = w.x;
            b.y = w.y;
            b.path.remove(0);
        }
    }
    let before = b.chunk;
    begin_segment(&mut b, now);
    if b.chunk != before {
        common::invalidate_bodies();
    }
    let arrived = b.path.is_empty();
    ctx.db.body().id().update(b);
    arrived
}

pub fn spawn_body(ctx: &ReducerContext, id: u32, kind: &str, at: (f32, f32), now: u64) {
    common::invalidate_bodies();
    ctx.db.body().insert(Body {
        id,
        kind: kind.into(),
        x: at.0,
        y: at.1,
        t_ms: now,
        vx: 0.0,
        vy: 0.0,
        path: Vec::new(),
        speed: 2.5,
        chunk: chunk_of(at.0, at.1),
        next_ms: IDLE,
    });
}
