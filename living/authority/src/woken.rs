//! Woken residents (docs/TOWN_LIFE.md, "Layer 2"): on a world whose residents live on their
//! behaviour graphs alone (`rules.minds = false`), a resident someone engages becomes a mind,
//! and stays one.
//!
//! - **Engagement.** Being spoken to, an act aimed at the resident as it starts (a wave, a
//!   gift, a lesson, an offer, a blow…), a blow or missile landing, or being robbed of its store
//!   as it watches. The engine reports the facts, `"<what>:<by>"` (what: `speech`, the skill's
//!   name, `hurt`, `theft`; by: `player`, `mind` (a mind's decision), `habit` (a minded
//!   character's behaviour graph by itself) or `instinct`), and the `wakes` law of
//!   `skills.rhai` says whether that wakes the resident. Without the law nobody wakes.
//! - **Waking** hands the resident to the world's mind service as presence's takeover does
//!   (`controller` = the world admin, `ai`), keeps its behaviour graph (its starting ways run
//!   until its mind writes another), records a private `woken` row and asks for a first
//!   deliberation. From then on the engagement and everything after it are ordinary
//!   experiences. A woken resident never goes back to instinct only: away from players it is
//!   off stage under the mind service's level of detail.
//! - **Before waking** a resident keeps a ring of what it perceived (`prior`, the
//!   `woken_ring("slots")` law's number of slots per resident, updated in place): what it saw
//!   and heard, who came into view, events nearby, worded as it perceived them. Only what that
//!   resident perceived. The ring is what its mind internalizes at waking; nothing else of the
//!   world's past reaches it. Without the law no ring is kept.
//! - **Who reads it.** `woken`, `prior` and `prior_head` are private: the mind service reads
//!   them as the database owner, no client does (like `presence`).

use crate::common;
use crate::tables::*;
use spacetimedb::{ReducerContext, Table};

/// A settlement-less resident's settlement.
pub const NO_SETTLEMENT: u16 = u16::MAX;
/// Bits of a ring key for the slot (the `slots` law is capped to fit).
const SLOT_BITS: u32 = 8;

/// The `woken_ring` law: slots per resident (0: no ring), the least salience kept, the repeat
/// and sighting windows.
struct Ring {
    slots: u32,
    min_salience: f32,
    repeat_ms: u64,
    sighted_ms: u64,
}

fn ring_law(ctx: &ReducerContext) -> Ring {
    let sc = common::scripts(ctx);
    Ring {
        slots: sc.num_of("woken_ring", "slots", 0.0).clamp(0.0, (1u32 << SLOT_BITS) as f64) as u32,
        min_salience: sc.num_of("woken_ring", "min_salience", 0.0) as f32,
        repeat_ms: (sc.num_of("woken_ring", "repeat_s", 0.0).max(0.0) * 1000.0) as u64,
        sighted_ms: (sc.num_of("woken_ring", "sighted_s", 0.0).max(0.0) * 1000.0) as u64,
    }
}

/// Instinct-only people keep a ring under the current rules.
pub fn rings_kept(ctx: &ReducerContext) -> bool {
    ring_law(ctx).slots > 0
}

/// Lives on its behaviour graph alone: no mind reads its experiences.
pub fn instinct_only(ctx: &ReducerContext, c: &Character) -> bool {
    !c.ai && c.controller == ctx.database_identity()
}

/// An instinct-only living person past infancy: one who may keep a ring and be woken.
pub fn resident(ctx: &ReducerContext, c: &Character) -> bool {
    c.alive && c.stage >= 1 && &*c.kind == "person" && instinct_only(ctx, c)
}

/// Who acted, and how, as the `wakes` law reads it: `player`; `mind` for what a mind decided
/// (an act, its words); `habit` for what a minded character's behaviour graph did by itself
/// (its routines' greetings, a graph's `say`); `instinct` for an instinct-only creature.
fn by_class(ctx: &ReducerContext, c: &Character, decided: bool) -> &'static str {
    if instinct_only(ctx, c) {
        "instinct"
    } else if !c.ai {
        "player"
    } else if decided {
        "mind"
    } else {
        "habit"
    }
}

/// `by` engaged `who` with `what` (`speech`, a skill aimed at it, `hurt`, `theft`); `decided`
/// says whether it was decided (an act, chosen words) or a behaviour graph's doing. Call
/// before `who`'s percept of it, so the percept is an experience of its mind. An
/// instinct-only resident wakes when the `wakes` law says so; a woken one is marked engaged
/// by a player or a mind's decision.
pub fn engage(ctx: &ReducerContext, who: u32, by: u32, what: &str, decided: bool, now: u64) {
    if who == by || by == 0 {
        return;
    }
    let Some(b) = ctx.db.character().id().find(by).filter(|b| b.alive) else { return };
    let class = by_class(ctx, &b, decided);
    if let Some(mut w) = ctx.db.woken().id().find(who) {
        if class == "player" || class == "mind" {
            w.engaged_ms = now;
            w.engaged_by = by;
            w.engagements = w.engagements.saturating_add(1);
            ctx.db.woken().id().update(w);
        }
        return;
    }
    let Some(c) = ctx.db.character().id().find(who).filter(|c| resident(ctx, c)) else { return };
    if common::scripts(ctx).num_of("wakes", &format!("{what}:{class}"), 0.0) > 0.0 {
        wake(ctx, c, &b, what, now);
    }
}

fn wake(ctx: &ReducerContext, mut c: Character, by: &Character, what: &str, now: u64) {
    let id = c.id;
    let settlement = settlement_of(ctx, &c);
    let who = common::label_cap(ctx, &c, by.id);
    c.controller = common::world(ctx).admin;
    c.ai = true;
    ctx.db.character().id().update(c);
    let prior = ctx.db.prior_head().id().find(id).map_or(0, |h| h.seq);
    // The places it knew before (its work, its square, its evening spot) are world facts its
    // starting ways walk to; a mind's projection keeps them unless the mind names them.
    let places: Vec<String> = ctx.db.place().actor().filter(id).map(|p| p.name).collect();
    ctx.db.woken().insert(Woken { id, settlement, woken_ms: now, by: by.id, why: what.into(), engaged_ms: now, engaged_by: by.id, engagements: 1, prior, places });
    // It has not thought yet: its starting graph's install is not a mind's thought, so the
    // first deliberation is not held back by `think_min_s`.
    if let Some(mut st) = ctx.db.mind_state().id().find(id) {
        st.deliberated_ms = 0;
        ctx.db.mind_state().id().update(st);
    }
    let did = match what {
        "speech" => "spoke to you".to_string(),
        "hurt" => "hurt you".to_string(),
        "theft" => "took from your store".to_string(),
        skill => format!("turned to you ({skill})"),
    };
    crate::perceive::request_deliberation(ctx, id, &format!("{who} {did}."), now);
    log::info!("resident {id} woke: {what} by {} ({prior} perceptions before)", by.id);
}

/// The settlement a resident belongs to: its community's, else the one its home lies in.
fn settlement_of(ctx: &ReducerContext, c: &Character) -> u16 {
    let community = ctx.db.membership().member().find(c.id).map(|m| m.community).filter(|k| *k != 0);
    let home = (c.home_x, c.home_y);
    let rows: Vec<Settlement> = ctx.db.settlement().iter().collect();
    if let Some(s) = community.and_then(|k| rows.iter().find(|s| s.community == k)) {
        return s.id;
    }
    rows.iter()
        .filter(|s| common::dist((s.x, s.y), home) <= s.radius_m.max(40.0))
        .min_by(|a, b| common::dist((a.x, a.y), home).total_cmp(&common::dist((b.x, b.y), home)))
        .map_or(NO_SETTLEMENT, |s| s.id)
}

/// Places a woken resident's mind projection must not drop (those it knew before waking).
pub fn kept_places(ctx: &ReducerContext, id: u32) -> Vec<String> {
    ctx.db.woken().id().find(id).map(|w| w.places.iter().map(|p| p.to_lowercase()).collect()).unwrap_or_default()
}

fn key(id: u32, slot: u32) -> u64 {
    (id as u64) << SLOT_BITS | slot as u64
}

/// An instinct-only resident perceived something: into its ring (the same perception again
/// soon after is counted in the slot it is in).
#[allow(clippy::too_many_arguments)]
pub fn remember(ctx: &ReducerContext, who: &Character, now: u64, kind: &str, subject: u32, object: u32, at: (f32, f32), text: &str, salience: f32) {
    if !resident(ctx, who) {
        return;
    }
    let law = ring_law(ctx);
    if law.slots == 0 || salience < law.min_salience {
        return;
    }
    let id = who.id;
    let head = ctx.db.prior_head().id().find(id);
    let seq = head.as_ref().map_or(0, |h| h.seq);
    if seq > 0 {
        if let Some(mut last) = ctx.db.prior().key().find(key(id, (seq - 1) % law.slots)) {
            if last.text == text && last.subject == subject && now.saturating_sub(last.at_ms) < law.repeat_ms {
                last.times = last.times.saturating_add(1);
                last.at_ms = now;
                ctx.db.prior().key().update(last);
                return;
            }
        }
    }
    let row = Prior { key: key(id, seq % law.slots), resident: id, seq: seq + 1, at_ms: now, kind: kind.into(), subject, object, x: at.0, y: at.1, text: text.into(), salience, times: 1 };
    if ctx.db.prior().key().find(row.key).is_some() {
        ctx.db.prior().key().update(row);
    } else {
        ctx.db.prior().insert(row);
    }
    match head {
        Some(mut h) => {
            h.seq = seq + 1;
            ctx.db.prior_head().id().update(h);
        }
        None => {
            ctx.db.prior_head().insert(PriorHead { id, seq: 1 });
        }
    }
    common::count(|k| k.percepts += 1);
}

/// A player's character came into view of an instinct-only resident who sees it back (from
/// the player's perceived-set sweep): noted again only after the `sighted_s` law.
pub fn sighted(ctx: &ReducerContext, resident: &Character, other: u32, at: (f32, f32), now: u64) {
    let law = ring_law(ctx);
    if law.slots == 0 {
        return;
    }
    if ctx.db.prior().resident().filter(resident.id).any(|p| p.kind == "sighted" && p.subject == other && now.saturating_sub(p.at_ms) < law.sighted_ms) {
        return;
    }
    let text = format!("{} came into view.", common::label_cap(ctx, resident, other));
    remember(ctx, resident, now, "sighted", other, 0, at, &text, 0.2);
}

/// A character died: its ring and its woken row go.
pub fn forget_dead(ctx: &ReducerContext, id: u32) {
    ctx.db.woken().id().delete(id);
    ctx.db.prior().resident().delete(id);
    ctx.db.prior_head().id().delete(id);
}
