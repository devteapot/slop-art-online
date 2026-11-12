//! The fast lane's triggers and turns (docs/FAST_LANE.md). A mind-run character is asked for a
//! quick re-plan between blows when it is struck, or when it sees the same creature start the
//! same move at it `seen_again_n` times in one fight. The count is kept here, for the trigger
//! only: nothing about it is told to anyone. The request's words are the event as the character
//! perceived it ("A stranger shot you with an arrow: hit for 7", "A stranger winds up an attack
//! at you").
//!
//! One `fast_ask` row per character holds its newest trigger. Rows are issued to the mind
//! service in turn, under the world's laws: at most `fast_lane_inflight` issued at once and
//! `fast_lane_rate` a second across the world, a character's at least `fast_lane_gap_s` apart,
//! the most recently triggered first; a trigger left waiting `fast_lane_stale_s` is dropped. The
//! mind answers through `mind_patch` or `mind_fast_done`, which release the turn (`answered`).
//!
//! Only a character whose mind runs is asked: alive, held by the minds (`ai`: an AI character,
//! or a person's character while the minds hold it), a person past infancy, awake, not
//! instinct-only. A person's return to their character, or a death, cancels its row.

use crate::common;
use crate::tables::*;
use spacetimedb::{ReducerContext, Table};
use std::cell::{Cell, RefCell};
use std::collections::HashMap;

/// A fight's moves are one fight while they come less than this apart (the first-blow window
/// `act::damage` uses).
const FIGHT_GAP_MS: u64 = 30_000;
/// An issued request not answered in this many stale windows is let go (the mind's call timed out
/// or the service went away).
const ISSUED_WINDOWS: u64 = 2;

thread_local! {
    /// (seer, mover, skill) → (moves seen in this fight, when the last was seen).
    static SEEN: RefCell<HashMap<(u32, u32, String), (u32, u64)>> = RefCell::new(HashMap::new());
    /// The world's issue bucket: tokens and when they were last refilled.
    static BUCKET: Cell<(f64, u64)> = const { Cell::new((0.0, 0)) };
    /// Some row may be waiting its turn (the tick pumps only then; housekeeping always).
    static WAITING: Cell<bool> = const { Cell::new(false) };
}

/// Whether the character's mind runs and may be asked now.
fn served(ctx: &ReducerContext, c: &Character) -> bool {
    c.alive && c.ai && c.kind == "person" && c.stage > 0 && !common::instinct_only(ctx, c) && !crate::perceive::asleep(ctx, c.id)
}

/// A blow, shot or bolt reached `vc`: `felt` is its own line for it.
pub fn struck(ctx: &ReducerContext, vc: &Character, felt: &str, now: u64) {
    if common::laws(ctx).fast_lane_on && served(ctx, vc) {
        trigger(ctx, vc.id, felt, now);
    }
}

/// A move with a victim was accepted (its windup began): counted for the victim when it sees the
/// mover, and at every `seen_again_n`-th of the same move by the same mover in a fight, a trigger.
pub fn move_started(ctx: &ReducerContext, a: &Activity, now: u64) {
    if a.victim == 0 || a.victim == a.id {
        return;
    }
    let laws = common::laws(ctx);
    if !laws.fast_lane_on {
        return;
    }
    let Some(vc) = ctx.db.character().id().find(a.victim) else { return };
    if !served(ctx, &vc) || !crate::perception::sees_creature(ctx, vc.id, a.id, now) {
        return;
    }
    let n = laws.seen_again_n.max(1.0) as u32;
    let count = SEEN.with(|s| {
        let mut s = s.borrow_mut();
        if s.len() > 4096 {
            s.retain(|_, (_, at)| now.saturating_sub(*at) < FIGHT_GAP_MS);
        }
        let e = s.entry((vc.id, a.id, a.skill.clone())).or_insert((0, now));
        if now.saturating_sub(e.1) >= FIGHT_GAP_MS {
            e.0 = 0;
        }
        e.0 += 1;
        e.1 = now;
        e.0
    });
    if count % n == 0 {
        let who = common::label_cap(ctx, &vc, a.id);
        let article = if a.skill.starts_with(['a', 'e', 'i', 'o', 'u']) { "an" } else { "a" };
        trigger(ctx, vc.id, &format!("{who} winds up {article} {} at you", a.skill), now);
    }
}

fn trigger(ctx: &ReducerContext, actor: u32, reason: &str, now: u64) {
    let reason: String = reason.chars().take(300).collect();
    match ctx.db.fast_ask().actor().find(actor) {
        Some(mut r) => {
            if r.issued_ms == 0 && r.first_ms == 0 {
                r.first_ms = now;
            }
            r.reason = reason;
            r.trigger_ms = now;
            ctx.db.fast_ask().actor().update(r);
        }
        None => {
            ctx.db.fast_ask().insert(FastAsk { actor, reason, trigger_ms: now, first_ms: now, issued_ms: 0, last_issued_ms: 0, base_ms: 0 });
        }
    }
    WAITING.with(|w| w.set(true));
    pump(ctx, now);
}

/// From the tick: only while some row may be waiting.
pub fn tick(ctx: &ReducerContext, now: u64) {
    if WAITING.with(|w| w.get()) {
        pump(ctx, now);
    }
}

/// A row is waiting (`first_ms` set, not issued), issued (`issued_ms` set) or idle (neither: it
/// keeps the character's last issue for `fast_lane_gap_s`, and goes once that has passed).
fn idle(ctx: &ReducerContext, mut r: FastAsk) {
    r.issued_ms = 0;
    r.first_ms = 0;
    ctx.db.fast_ask().actor().update(r);
}

/// Issue waiting rows in turn under the laws; drop stale ones; let go of unanswered ones.
pub fn pump(ctx: &ReducerContext, now: u64) {
    let laws = common::laws(ctx);
    let stale = (laws.fast_lane_stale_s * 1000.0) as u64;
    let gap = (laws.fast_lane_gap_s * 1000.0) as u64;
    let rows: Vec<FastAsk> = ctx.db.fast_ask().iter().collect();
    if rows.is_empty() {
        WAITING.with(|w| w.set(false));
        return;
    }
    let mut inflight = 0usize;
    let mut waiting = Vec::new();
    for r in rows {
        if r.issued_ms != 0 {
            if now.saturating_sub(r.issued_ms) > stale * ISSUED_WINDOWS {
                idle(ctx, r);
            } else {
                inflight += 1;
            }
        } else if r.first_ms == 0 {
            if now.saturating_sub(r.last_issued_ms) >= gap {
                ctx.db.fast_ask().actor().delete(r.actor);
            }
        } else if now.saturating_sub(r.first_ms) > stale || !laws.fast_lane_on {
            idle(ctx, r);
        } else {
            waiting.push(r);
        }
    }
    WAITING.with(|w| w.set(!waiting.is_empty()));
    if waiting.is_empty() {
        return;
    }
    // Refill the bucket: `fast_lane_rate` a second, holding at most one second's worth (at least one).
    let rate = laws.fast_lane_rate.max(0.0) as f64;
    let (mut tokens, at) = BUCKET.with(|b| b.get());
    tokens = (tokens + rate * now.saturating_sub(at) as f64 / 1000.0).min(rate.max(1.0));
    let cap = laws.fast_lane_inflight.max(0.0) as usize;
    waiting.sort_by(|a, b| b.trigger_ms.cmp(&a.trigger_ms));
    for mut r in waiting {
        if inflight >= cap || tokens < 1.0 {
            break;
        }
        if r.last_issued_ms != 0 && now.saturating_sub(r.last_issued_ms) < gap {
            continue;
        }
        let Some(c) = ctx.db.character().id().find(r.actor).filter(|c| served(ctx, c)) else {
            ctx.db.fast_ask().actor().delete(r.actor);
            continue;
        };
        r.issued_ms = now;
        r.last_issued_ms = now;
        r.base_ms = ctx.db.brain().id().find(c.id).map_or(0, |b| b.installed_ms);
        ctx.db.fast_ask().actor().update(r);
        inflight += 1;
        tokens -= 1.0;
    }
    BUCKET.with(|b| b.set((tokens, now)));
}

/// The mind answered the request issued at `issued_ms` (a patch, a refusal or no change): its
/// turn is over. Triggers that came while it was served wait for the next turn.
pub fn answered(ctx: &ReducerContext, actor: u32, issued_ms: u64, now: u64) {
    if let Some(mut r) = ctx.db.fast_ask().actor().find(actor).filter(|r| r.issued_ms == issued_ms && issued_ms != 0) {
        if r.trigger_ms > issued_ms {
            r.issued_ms = 0;
            r.first_ms = r.trigger_ms;
            ctx.db.fast_ask().actor().update(r);
            WAITING.with(|w| w.set(true));
        } else {
            idle(ctx, r);
            // The idle row goes once its gap has passed (housekeeping, or the next pump).
            WAITING.with(|w| w.set(true));
        }
    }
    pump(ctx, now);
}

/// The character's mind no longer holds it (its person is back) or it died: nothing is asked.
pub fn cancel(ctx: &ReducerContext, actor: u32) {
    ctx.db.fast_ask().actor().delete(actor);
}
