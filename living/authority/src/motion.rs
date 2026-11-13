//! Steering locomotion. A body has a heading, a desired speed and a steering goal (a point,
//! a creature, a direction, or something to get away from). A steering update turns the
//! heading toward the next corner of a coarse path (or straight at the goal when it is in
//! view) at a bounded turn rate, bends around nearby bodies, slows for sharp turns and near
//! the destination, and sweeps the segment across the map so it stops short of obstacles.
//!
//! Positions are analytic between updates (a straight line or a circular arc, see
//! `living_rules::steer`), so the `body` row is written only at steering updates: events
//! (a path corner, the start of the final approach, arrival, a chunk crossing, a change
//! between road and open ground, an obstacle) plus a modest cadence while it matters
//! (among other bodies, chasing, fighting). Changing goals keeps the current heading and
//! speed, so one movement flows into the next instead of stopping and restarting.

use crate::common::{self, dist};
use crate::tables::*;
use living_rules::map::{chunk_of, Map};
use living_rules::nav::{NoLeg, RouteSpec, Walk};
use living_rules::steer::{self as geo, Want};
use spacetimedb::{ReducerContext, Table};

pub const IDLE: u64 = u64::MAX;

pub const GOAL_NONE: u8 = 0;
pub const GOAL_POINT: u8 = 1;
pub const GOAL_CREATURE: u8 = 2;
pub const GOAL_DIRECTION: u8 = 3;
pub const GOAL_FLEE: u8 = 4;
/// Hold a range band from a creature (`keep_distance`): `keep` the near edge, `far` the far one.
pub const GOAL_BAND: u8 = 5;
/// Go round a creature (`circle`): `keep` the radius, `far` the side (+1 left as one faces it).
pub const GOAL_ORBIT: u8 = 6;

/// Report arrival when the final approach begins (the body glides on to the spot), so the
/// next activity takes over with momentum. Without it, arrival is reported at the goal.
pub const FLAG_EARLY: u8 = 1;
/// Report every steering update within reach of a creature (an approach checking its reach).
pub const FLAG_EACH: u8 = 2;
/// A dash: heading at once, no ramp and no slowing at the end.
pub const FLAG_AGILE: u8 = 4;
/// A run, for any controller (a player's held key, a graph's or a mind's `run`, a flight): the
/// body runs at `steer.run_pace` while it has breath and walks at `steer.pace` when it has
/// none, running again once it has the `pools` law's `resume` (docs/STAMINA.md).
pub const FLAG_RUN: u8 = 8;
/// Stuck once already; re-planned (internal).
const FLAG_STUCK: u8 = 16;
/// A run out of breath, walking until it has enough to run again (internal).
const FLAG_WINDED: u8 = 32;
/// The run is draining breath now: its rate is on the vitals row (internal).
const FLAG_DRAIN: u8 = 64;
/// Held to a creature by perception (the movement intents, `living_rules::steer::INTENTS`):
/// at each steering update the target is tested with the one sight rule (or the body's scent);
/// seen, the body aims at where it is now and keeps that as last seen (`gx`/`gy`); unseen, it
/// goes by where it was last seen, and the goal is lost once the `lost_after_s` law has passed
/// since steering first found it out of sight (`unseen_ms`).
/// The body faces it as far as walking allows (a held look, `settle_face`).
pub const FLAG_SIGHT: u8 = 128;

/// While a held target stays in sight, its last-seen place is written when it has moved this
/// far (metres): a private row write now and then, not one per steering update.
const SEEN_MOVED_M: f32 = 0.5;

/// Minimum time between steering updates (except arrival at a spot).
const MIN_STEP_MS: u64 = 40;
/// A creature pursuit re-plans its coarse path at most this often.
const REPLAN_MS: u64 = 1_000;
/// A walk plans its next leg when the current leg's end is this close (`living_rules::nav`).
pub const REPLAN_AHEAD_M: f32 = 16.0;

/// Chunks whose walking regions a tick works out ahead of time, until the whole map's are
/// built (`Map::warm_routes`): at most about 0.4 ms of a tick, the 2048 m island in about
/// 5 s after the map is loaded. A route before then builds what it needs itself.
const WARM_CHUNKS: usize = 64;

pub fn warm_routes(ctx: &ReducerContext) {
    common::map(ctx).warm_routes(WARM_CHUNKS);
}

/// How walks are routed: the world's road speed, legs of the default length.
fn route_spec(laws: &living_rules::script::Laws) -> RouteSpec {
    RouteSpec { road_speed: laws.road_speed, ..Default::default() }
}

/// The waypoints of the next leg of a walk from `p` to `to` (they end at `to` on the last).
fn leg(map: &Map, p: (f32, f32), to: (f32, f32), laws: &living_rules::script::Laws) -> Option<Vec<Waypoint>> {
    let leg = map.route_leg(p, to, &route_spec(laws))?;
    Some(leg.points.into_iter().map(|(x, y)| Waypoint { x, y }).collect())
}

/// The next leg of body `id`'s walk to a place, along the route it keeps in `walk_route`
/// (searched afresh when it has none: a new walk).
fn walk_leg(ctx: &ReducerContext, id: u32, map: &Map, p: (f32, f32), to: (f32, f32), laws: &living_rules::script::Laws) -> Result<Vec<Waypoint>, NoLeg> {
    let row = ctx.db.walk_route().id().find(id);
    let mut walk = row.as_ref().map(|r| Walk::from_vec(&r.route)).unwrap_or_default();
    let leg = map.route_leg_along(p, to, &route_spec(laws), &mut walk);
    let route = walk.to_vec();
    match row {
        Some(r) if r.route == route => {}
        Some(_) if route.is_empty() => {
            ctx.db.walk_route().id().delete(id);
        }
        Some(_) => {
            ctx.db.walk_route().id().update(WalkRoute { id, route });
        }
        None if route.is_empty() => {}
        None => {
            ctx.db.walk_route().insert(WalkRoute { id, route });
        }
    }
    Ok(leg?.points.into_iter().map(|(x, y)| Waypoint { x, y }).collect())
}

/// A walk is over, or another goal starts: its route is not kept.
fn walk_over(ctx: &ReducerContext, id: u32) {
    ctx.db.walk_route().id().delete(id);
}

/// What a walker is told when its walk gets no nearer for `NO_HEADWAY_LEGS` legs.
const NO_HEADWAY: &str = "you were getting no nearer: the way kept turning back";

/// What to steer for.
#[derive(Clone, Copy, Debug)]
pub struct Goal {
    pub kind: u8,
    pub target: u32,
    pub at: (f32, f32),
    pub keep: f32,
    pub speed: f32,
    pub flags: u8,
    /// A run's speed without breath (`speed` is the run's); the speed for any other goal.
    pub pace: f32,
    /// A band's far edge or a circle's side (`GOAL_BAND`, `GOAL_ORBIT`).
    pub far: f32,
    /// How far to keep from seen others of one's own kind while holding it (0: no matter).
    pub apart: f32,
}

impl Goal {
    pub fn point(at: (f32, f32), speed: f32, flags: u8) -> Self {
        Self { kind: GOAL_POINT, target: 0, at, keep: 0.0, speed, flags, pace: speed, far: 0.0, apart: 0.0 }
    }
    pub fn creature(id: u32, keep: f32, speed: f32, flags: u8) -> Self {
        Self { kind: GOAL_CREATURE, target: id, at: (0.0, 0.0), keep, speed, flags, pace: speed, far: 0.0, apart: 0.0 }
    }
    /// A movement intent held to creature `id`, seen at `at` (`FLAG_SIGHT`).
    pub fn held(kind: u8, id: u32, at: (f32, f32), keep: f32, far: f32, speed: f32, flags: u8) -> Self {
        Self { kind, target: id, at, keep, speed, flags: flags | FLAG_SIGHT, pace: speed, far, apart: 0.0 }
    }
    /// The same goal keeping `m` from seen others of one's own kind (`Spacing::apart`).
    pub fn apart(self, m: f32) -> Self {
        Self { apart: m.max(0.0), ..self }
    }
    /// The same goal at a run of `speed`: without breath it goes at its own speed.
    pub fn run(self, speed: f32) -> Self {
        Self { pace: self.speed, speed, flags: self.flags | FLAG_RUN, ..self }
    }
}

/// Keep a run's drain of breath in step with the body (`FLAG_DRAIN`): a run under way that is
/// moving and has breath drains it; anything else (arrived, stopped, standing at a keep, out of
/// breath) lets it come back. One vitals write at each change, none while it holds. Returns
/// whether the steer row changed.
fn breathe(ctx: &ReducerContext, b: &Body, st: &mut Steer, now: u64) -> bool {
    let moving = b.vx != 0.0 || b.vy != 0.0;
    let want = st.goal != GOAL_NONE && st.flags & FLAG_RUN != 0 && st.flags & FLAG_WINDED == 0 && moving;
    let have = st.flags & FLAG_DRAIN != 0;
    if want == have {
        return false;
    }
    if want {
        crate::breath::drain(ctx, b.id, common::pools_of(ctx, b.id, now).breath.run_per_s, now);
        st.flags |= FLAG_DRAIN;
    } else {
        crate::breath::ease(ctx, b.id, now);
        st.flags &= !FLAG_DRAIN;
    }
    true
}

/// A run's breath at a steering update: out of breath, it walks; with enough again, it runs.
/// Returns whether the steer row changed.
fn run_or_walk(ctx: &ReducerContext, b: &mut Body, st: &mut Steer, now: u64) -> bool {
    if st.flags & FLAG_RUN == 0 || st.goal == GOAL_NONE {
        return false;
    }
    let breath = crate::breath::stamina_now(ctx, b.id, now);
    if st.flags & FLAG_WINDED == 0 && st.flags & FLAG_DRAIN != 0 && breath <= 0.05 {
        st.flags |= FLAG_WINDED;
        b.speed = st.pace;
        return true;
    }
    if st.flags & FLAG_WINDED != 0 && breath >= common::pools_of(ctx, b.id, now).breath.resume {
        st.flags &= !FLAG_WINDED;
        b.speed = st.run_pace;
        return true;
    }
    false
}

/// A running body looks again when its breath runs out, and a winded one when it can run again,
/// so the speed changes exactly there (the vitals row and the motion segment agree).
fn breath_due(ctx: &ReducerContext, b: &mut Body, st: &Steer, now: u64) {
    if st.flags & FLAG_RUN == 0 || st.goal == GOAL_NONE || b.next_ms == IDLE {
        return;
    }
    let Some(v) = ctx.db.vitals().id().find(b.id) else { return };
    let at = if st.flags & FLAG_DRAIN != 0 {
        living_rules::pools::reaches(v.stamina, v.stamina_rate, v.stamina_from_ms, v.at_ms, 0.0, now)
    } else if st.flags & FLAG_WINDED != 0 {
        let resume = common::pools_of(ctx, b.id, now).breath.resume;
        living_rules::pools::refilled(v.stamina, v.stamina_rate, v.stamina_from_ms, v.at_ms, v.stamina_max, resume, now)
    } else {
        None
    };
    if let Some(t) = at {
        b.next_ms = b.next_ms.min(t.max(now + MIN_STEP_MS));
    }
}

/// Whether the body's steering goal runs (a run under way, or out of breath and walking).
pub fn runs(ctx: &ReducerContext, id: u32) -> bool {
    ctx.db.steer().id().find(id).is_some_and(|st| st.goal != GOAL_NONE && st.flags & FLAG_RUN != 0)
}

/// End a run where the body stops (no steering update follows): its breath comes back.
fn end_run(ctx: &ReducerContext, st: &mut Steer, id: u32, now: u64) -> bool {
    if st.flags & FLAG_DRAIN == 0 {
        return false;
    }
    crate::breath::ease(ctx, id, now);
    st.flags &= !FLAG_DRAIN;
    true
}

/// What steering tells the activity driving it.
#[derive(Clone, Debug, PartialEq)]
pub enum Event {
    Arrived,
    Lost(String),
}

pub fn speed_of(b: &Body) -> f32 {
    (b.vx * b.vx + b.vy * b.vy).sqrt()
}

fn fresh_steer(id: u32) -> Steer {
    Steer { id, goal: GOAL_NONE, target: 0, gx: 0.0, gy: 0.0, keep: 0.0, flags: 0, reported: false, plan_ms: 0, tokens: 0.0, input_ms: 0, look_on: false, look: 0.0, pace: 0.0, run_pace: 0.0, far: 0.0, unseen_ms: 0, apart: 0.0 }
}

fn load_steer(ctx: &ReducerContext, id: u32) -> (Steer, bool) {
    match ctx.db.steer().id().find(id) {
        Some(s) => (s, true),
        None => (fresh_steer(id), false),
    }
}

fn save_steer(ctx: &ReducerContext, st: Steer, exists: bool) {
    if exists {
        ctx.db.steer().id().update(st);
    } else {
        ctx.db.steer().insert(st);
    }
}

fn put(ctx: &ReducerContext, b: Body, chunk_before: u32) {
    if b.chunk != chunk_before {
        common::invalidate_bodies();
    }
    crate::frame::moved(b.id);
    ctx.db.body().id().update(b);
}

/// Longest a finished segment is continued from where it ended, not from `now`.
const RESUME_MS: u64 = 40;

thread_local! {
    /// Segments this transaction began before its `now` (`resume_at`): the transaction
    /// (`common::tx_seq`) and its `now`, and, per body, the segment's start.
    static RESUMED: std::cell::RefCell<((u64, u64), std::collections::HashMap<u32, u64>)> = Default::default();
}

/// When the next segment of a moving body begins: where its last one ended (`next_ms`),
/// when that was at most `RESUME_MS` ago, otherwise `now`. A due body is reached by the
/// first tick after `next_ms` (up to 16.7 ms later at 60 Hz); starting the next segment at
/// `next_ms` keeps it moving through that gap instead of standing at the segment's end
/// until the tick, so observers see steady motion rather than a stop at every update.
/// The new segment is swept from the same pose, so it is as safe as starting at `now`.
///
/// A segment begun that way and replaced in the same transaction (the update reported an
/// arrival and the next activity set a new goal) is replaced from where it began:
/// observers never received it, only the one before it.
fn resume_at(b: &Body, now: u64) -> u64 {
    if (b.vx != 0.0 || b.vy != 0.0) && b.next_ms < now {
        return b.next_ms.max(now.saturating_sub(RESUME_MS)).max(b.t_ms);
    }
    if b.t_ms < now && RESUMED.with(|r| {
        let r = r.borrow();
        r.0 == (common::tx_seq(), now) && r.1.get(&b.id) == Some(&b.t_ms)
    }) {
        return b.t_ms;
    }
    now
}

/// Note that `id`'s segment was begun at `t0` by a transaction at `now`.
fn resumed(id: u32, t0: u64, now: u64) {
    if t0 >= now {
        return;
    }
    RESUMED.with(|r| {
        let mut r = r.borrow_mut();
        let key = (common::tx_seq(), now);
        if r.0 != key {
            r.0 = key;
            r.1.clear();
        }
        r.1.insert(id, t0);
    });
}

/// Re-anchor a body's segment at `now` (position and heading on the segment so far).
fn anchor(b: &mut Body, now: u64) {
    let dt = now.min(b.next_ms).saturating_sub(b.t_ms) as f32 / 1000.0;
    let v = speed_of(b);
    let (x, y, h) = geo::pose(b.x, b.y, b.heading, v, b.turn, b.turn_s, dt);
    b.x = x;
    b.y = y;
    b.t_ms = now;
    let left = (b.turn_s - dt).max(0.0);
    set_motion(b, geo::wrap(h), v, if left > 0.0 { b.turn } else { 0.0 }, left);
    // The facing's own turn goes on from where it is (an offset from the heading, which is
    // continuous here, so the facing is too).
    let off = geo::face_off(b.face_off, b.face_turn, b.face_turn_s, dt);
    let face_left = (b.face_turn_s - dt).max(0.0);
    b.face_off = off;
    b.face_turn = if face_left > 0.0 { b.face_turn } else { 0.0 };
    b.face_turn_s = if b.face_turn != 0.0 { face_left } else { 0.0 };
}

/// A standing body turns to face `want` (`steer::stand_turn`): its legs turn at `rate` the way
/// its upper body already leans, and any facing offset comes back to 0 over the same turn, so
/// the whole body ends facing it. Within `slack` of it, the legs stay and only the facing
/// finishes. False when there is nothing to do. With no offset this is the plain standing turn.
fn turn_to(b: &mut Body, want: f32, rate: f32, slack: f32) -> bool {
    let off = geo::face_off(b.face_off, b.face_turn, b.face_turn_s, 0.0);
    let Some(((legs, legs_s), face)) = geo::stand_facing(b.heading, off, want, rate, slack) else { return false };
    if legs_s > 0.0 {
        let h = b.heading;
        set_motion(b, h, 0.0, legs, legs_s);
    }
    put_face(b, face);
    true
}

/// Write a facing segment (`steer::FaceSeg`) into the body.
fn put_face(b: &mut Body, f: geo::FaceSeg) {
    b.face_off = f.off;
    b.face_turn = if f.turn_s > 0.0 { f.turn } else { 0.0 };
    b.face_turn_s = if b.face_turn != 0.0 { f.turn_s } else { 0.0 };
}

/// After a steering update: the facing segment from where the body faced at the update
/// (`before`, so the facing never jumps when the heading does) toward what it wants. With a
/// held look, standing with no walk under way, the whole body turns to the look (`turn_to`);
/// otherwise the facing turns toward the look within the `look_walk_deg` law of the travel's
/// heading at the end of the segment's turn, or back to the heading with no look
/// (`steer::walk_facing`: from where it faces, never faster than `rate` in the world; when the
/// travel's turn is too short for it, steering looks again at that turn's end). A body with no
/// look and no offset faces its heading and has no facing segment.
fn settle_face(b: &mut Body, st: &Steer, before: f32, had_off: bool, laws: &living_rules::script::Laws, rate: f32) {
    if !st.look_on && !had_off {
        b.face_off = 0.0;
        b.face_turn = 0.0;
        b.face_turn_s = 0.0;
        return;
    }
    let limit = laws.look_walk_deg.to_radians();
    let moving = b.vx != 0.0 || b.vy != 0.0;
    if !moving && st.look_on && st.goal != GOAL_DIRECTION {
        b.face_off = geo::wrap(before - b.heading);
        b.face_turn = 0.0;
        b.face_turn_s = 0.0;
        turn_to(b, st.look, rate, laws.look_slack_deg.to_radians());
        return;
    }
    let look = st.look_on.then_some(st.look);
    let f = geo::walk_facing(before, b.heading, b.turn, b.turn_s, look, limit, rate);
    put_face(b, f);
    if let Some(s) = f.due_s {
        // The facing has more turning to do than this segment carries: steering looks again
        // where it can go on (the end of the travel's turn).
        b.next_ms = b.next_ms.min(due(b.t_ms, s, MIN_STEP_MS));
    }
}

/// The travel's turn was cut short where the body was anchored (a stop, a glide to a stand): a
/// facing that was turning over it goes on from where it faces now toward where it settles over
/// the travel as it now is (`steer::walk_facing`, at the turn rate), rather than carrying on a
/// turn worked out against the travel's (which, the travel no longer turning, would swing it
/// away and back). Written with the row the stop writes anyway.
fn turn_cut(ctx: &ReducerContext, b: &mut Body, cut: bool, look: Option<f32>) {
    if !cut || b.face_turn == 0.0 {
        return;
    }
    let laws = common::laws(ctx);
    let rate = common::moves_of(ctx, b.id, b.t_ms).turn_rate.max(0.5);
    let facing = geo::wrap(b.heading + b.face_off);
    put_face(b, geo::walk_facing(facing, b.heading, 0.0, 0.0, look, laws.look_walk_deg.to_radians(), rate));
}

fn set_motion(b: &mut Body, heading: f32, speed: f32, turn: f32, turn_s: f32) {
    b.heading = heading;
    b.turn = if turn_s > 0.0 { turn } else { 0.0 };
    b.turn_s = if turn != 0.0 { turn_s } else { 0.0 };
    b.vx = speed * heading.cos();
    b.vy = speed * heading.sin();
}

fn halt(b: &mut Body) {
    b.vx = 0.0;
    b.vy = 0.0;
    b.turn = 0.0;
    b.turn_s = 0.0;
    b.running = false;
}

fn straight(heading: f32, speed: f32, dur: f32) -> geo::Segment {
    geo::Segment { heading, speed, turn: 0.0, turn_s: 0.0, dur, blocked: false }
}

fn due(now: u64, dur_s: f32, min_ms: u64) -> u64 {
    now + ((dur_s.max(0.0) * 1000.0).ceil() as u64).max(min_ms)
}

/// Coast for up to `secs` on the current heading at reduced speed, then stand (a stop that
/// is not a snap; a movement started meanwhile takes over with the momentum).
fn glide_stop(map: &Map, b: &mut Body, now: u64, secs: f32) {
    // A glide to a stand is no run (a goal that runs on sets it again at its next update).
    b.running = false;
    let v = speed_of(b) * 0.6;
    if v < 0.3 {
        halt(b);
        b.next_ms = IDLE;
        return;
    }
    let (dur, _) = geo::sweep(map, (b.x, b.y), &straight(b.heading, v, secs), 0.1);
    if dur < 0.05 {
        halt(b);
        b.next_ms = IDLE;
        return;
    }
    set_motion(b, b.heading, v, 0.0, 0.0);
    b.next_ms = due(now, dur, MIN_STEP_MS);
}

/// Drop reached corners, and corners the body can already see past.
fn advance_corners(map: &Map, p: (f32, f32), path: &mut Vec<Waypoint>, corner: f32) {
    while path.len() > 1 {
        let d = dist(p, (path[0].x, path[0].y));
        if d < 0.15 || (d < corner && map.line_clear(p, (path[1].x, path[1].y))) {
            path.remove(0);
        } else {
            break;
        }
    }
}

/// Bend `dir` away from bodies close ahead. Returns the new direction and whether anyone
/// was close enough to matter.
fn separate(ctx: &ReducerContext, id: u32, p: (f32, f32), dir: f32, exclude: u32, moves: &living_rules::script::Moves, now: u64) -> (f32, bool) {
    let r = moves.separation;
    if r <= 0.0 || moves.separation_weight <= 0.0 {
        return (dir, false);
    }
    let (ux, uy) = (dir.cos(), dir.sin());
    let (mut sx, mut sy, mut n) = (0.0f32, 0.0f32, 0);
    for c in common::creatures_near(ctx, p, r, now) {
        if c.id == id || c.id == exclude {
            continue;
        }
        let (dx, dy) = (p.0 - c.pos.0, p.1 - c.pos.1);
        let d = c.dist.max(0.05);
        // Only bodies beside or ahead of the way matter.
        if -(dx * ux + dy * uy) < -0.3 * d {
            continue;
        }
        let k = (1.0 - d / r) / d;
        sx += dx * k;
        sy += dy * k;
        n += 1;
    }
    if n == 0 {
        return (dir, false);
    }
    let w = moves.separation_weight;
    ((uy + w * sy).atan2(ux + w * sx), true)
}

/// The push away from others of the body's own kind that it sees within its goal's `apart`
/// (docs/PACK_MIND.md, A5): the same sight rule as any target (`perception::in_sight`), never
/// the one it holds the intent to. Zero when the goal has no `apart`.
fn apart_push(ctx: &ReducerContext, b: &Body, st: &Steer, p: (f32, f32), now: u64) -> (f32, f32) {
    if st.apart <= 0.0 {
        return (0.0, 0.0);
    }
    let map = common::map(ctx);
    let w = common::world(ctx);
    let facing = common::facing_at(b, now);
    let mates: Vec<(f32, f32)> = common::creatures_near(ctx, p, st.apart, now)
        .into_iter()
        .filter(|c| c.id != b.id && c.id != st.target && *c.kind == *b.kind)
        .filter(|c| crate::perception::in_sight(ctx, &map, b.id, p, facing, c.id, c.pos, c.dist, &w, now, true))
        .map(|c| c.pos)
        .collect();
    living_rules::steer::apart_push(p, &mates, st.apart)
}

fn angle(from: (f32, f32), to: (f32, f32)) -> f32 {
    (to.1 - from.1).atan2(to.0 - from.0)
}

/// Where a goal held by perception (`FLAG_SIGHT`) aims now.
struct Held {
    /// Where the target is (seen) or was last seen.
    at: (f32, f32),
    /// Its velocity when seen (zero when going by its last-seen place).
    vel: (f32, f32),
    seen: bool,
}

/// The target of a goal held by perception: tested with the one sight rule
/// (`perception::in_sight`, the keep margins of something already seen, the body's facing now)
/// or within the body's scent. Seen, it is where it is now, kept as last seen when it has moved
/// `SEEN_MOVED_M` (`dirty`); unseen, it is where it was last seen, until the `lost_after_s` law
/// has passed since steering first found it out of sight. The steer row is written only at
/// those changes. Err: why the goal is lost.
fn held(ctx: &ReducerContext, b: &Body, st: &mut Steer, p: (f32, f32), now: u64, laws: &living_rules::script::Laws, dirty: &mut bool) -> Result<Held, String> {
    let alive = ctx.db.character().id().find(st.target).is_some_and(|c| c.alive);
    let tb = ctx.db.body().id().find(st.target).filter(|_| alive);
    if let Some(tb) = &tb {
        let tp = common::pos(tb, now);
        let d = dist(p, tp);
        let map = common::map(ctx);
        let w = common::world(ctx);
        let seen = crate::perception::in_sight(ctx, &map, b.id, p, common::facing_at(b, now), tb.id, tp, d, &w, now, true) || common::scent_of(&b.kind).is_some_and(|s| s.reaches(&tb.kind, d));
        if seen {
            if dist((st.gx, st.gy), tp) > SEEN_MOVED_M || st.unseen_ms != 0 {
                st.gx = tp.0;
                st.gy = tp.1;
                st.unseen_ms = 0;
                *dirty = true;
            }
            return Ok(Held { at: tp, vel: (tb.vx, tb.vy), seen: true });
        }
    }
    if st.unseen_ms == 0 {
        st.unseen_ms = now.max(1);
        *dirty = true;
    }
    if now.saturating_sub(st.unseen_ms) as f32 > laws.lost_after_s * 1000.0 {
        return Err(match tb {
            Some(_) => "lost sight of them".into(),
            None if alive => "it is gone".into(),
            None => "they are dead".into(),
        });
    }
    Ok(Held { at: (st.gx, st.gy), vel: (0.0, 0.0), seen: false })
}

/// Face what a held goal aims at, as far as walking allows (`settle_face`): a held look, as a
/// player's mouse holds one. Not written by itself: it is the steer row's when the row is.
fn look_at(st: &mut Steer, p: (f32, f32), at: (f32, f32)) {
    if dist(p, at) > 0.05 {
        st.look_on = true;
        st.look = angle(p, at);
    }
}

/// Heading for a creature at `tp` moving at `tv` until `keep` from it: straight at where it
/// will be (a second ahead at most) when the line is clear, else along a coarse path planned at
/// most every `REPLAN_MS`. Err: it cannot be reached.
#[allow(clippy::too_many_arguments)]
fn toward(ctx: &ReducerContext, b: &mut Body, st: &mut Steer, map: &Map, p: (f32, f32), tp: (f32, f32), tv: (f32, f32), keep: f32, max_dt: f32, laws: &living_rules::script::Laws, moves: &living_rules::script::Moves, agile: bool, now: u64, dirty: &mut bool) -> Result<Want, String> {
    let d = dist(p, tp);
    let cruise = b.speed.max(0.1);
    let mut v = cruise * ((d - keep) / laws.slow_radius.max(0.1)).clamp(0.35, 1.0);
    // A pursuit slowing near its distance (an approach to strike, a close_in, a follow; any
    // controller) does not drop below the speed at which the target draws away, so it closes on
    // one that walks off instead of trailing it forever just beyond its reach (up to its own
    // speed: a slower body still cannot catch a faster one).
    if d > 1e-3 {
        let away = ((tp.0 - p.0) * tv.0 + (tp.1 - p.1) * tv.1) / d;
        v = v.max((away + 0.3).min(cruise));
    }
    // Aim where they are going to be.
    let lead = (d / cruise).min(1.0);
    let ahead = (tp.0 + tv.0 * lead, tp.1 + tv.1 * lead);
    let aim = if map.free(ahead.0, ahead.1) { ahead } else { tp };
    let mut w = aim;
    if map.line_clear(p, aim) {
        b.path.clear();
    } else {
        let stale = b.path.last().map_or(true, |l| dist((l.x, l.y), tp) > 2.0);
        if stale && now.saturating_sub(st.plan_ms) >= REPLAN_MS {
            st.plan_ms = now;
            *dirty = true;
            match leg(map, p, tp, laws) {
                Some(path) => b.path = path,
                None => {
                    if b.path.is_empty() {
                        return Err("cannot reach them".into());
                    }
                }
            }
        }
        advance_corners(map, p, &mut b.path, laws.corner_radius);
        if let Some(c) = b.path.first() {
            w = (c.x, c.y);
        }
    }
    let max_dt = max_dt.min(((d - keep) / v).max(0.05));
    let (dir, _) = separate(ctx, b.id, p, angle(p, w), st.target, moves, now);
    Ok(Want { dir, speed: v, agile, max_dt })
}

/// One steering update at `now`, with a run's breath: a run out of breath walks (and runs again
/// when it can), the drain follows the body, and the next look comes when the breath changes it.
fn update(ctx: &ReducerContext, b: &mut Body, st: &mut Steer, now: u64) -> (Option<Event>, bool) {
    let paced = run_or_walk(ctx, b, st, now);
    let (ev, dirty) = face_update(ctx, b, st, now);
    let breathed = breathe(ctx, b, st, now);
    breath_due(ctx, b, st, now);
    // Published with the motion: running is a run that drains breath (moving, with breath).
    b.running = st.flags & FLAG_DRAIN != 0;
    (ev, dirty || paced || breathed)
}

/// One steering update at `now`: writes the new segment (from `resume_at`) into `b`, travel
/// and facing (`settle_face`), and possibly `st`.
/// Returns an event for the driving activity and whether `st` changed.
fn face_update(ctx: &ReducerContext, b: &mut Body, st: &mut Steer, now: u64) -> (Option<Event>, bool) {
    let laws = common::laws(ctx);
    let moves = common::moves_of(ctx, b.id, now);
    let before = common::facing_at(b, resume_at(b, now));
    let had_off = b.face_off != 0.0 || b.face_turn != 0.0;
    let out = steer_update(ctx, b, st, now, &laws, &moves);
    settle_face(b, st, before, had_off, &laws, moves.turn_rate.max(0.5));
    out
}

/// The travel part of a steering update (`update`).
fn steer_update(ctx: &ReducerContext, b: &mut Body, st: &mut Steer, now: u64, laws: &living_rules::script::Laws, moves: &living_rules::script::Moves) -> (Option<Event>, bool) {
    let (laws, moves) = (*laws, *moves);
    let tune = moves.tuning(laws.road_speed);
    let map = common::map(ctx);
    let v_cur = speed_of(b);
    let t0 = resume_at(b, now);
    anchor(b, t0);
    resumed(b.id, t0, now);
    let p = (b.x, b.y);
    let mut ev = None;
    let mut dirty = false;
    let agile = st.flags & FLAG_AGILE != 0;
    // Stand still until `stand` (IDLE: until something changes the goal).
    let mut stand: Option<u64> = None;
    let mut want: Option<Want> = None;
    // A band's way when it moves: closing in (a path may be planned) or backing off.
    let mut closing: Option<bool> = None;
    match st.goal {
        GOAL_POINT => {
            let goal = (st.gx, st.gy);
            let dg = dist(p, goal);
            if dg <= 0.06 {
                b.x = goal.0;
                b.y = goal.1;
                b.path.clear();
                if !st.reported {
                    ev = Some(Event::Arrived);
                }
                st.goal = GOAL_NONE;
                st.reported = false;
                walk_over(ctx, b.id);
                dirty = true;
                stand = Some(IDLE);
            } else {
                if b.path.is_empty() {
                    b.path.push(Waypoint { x: goal.0, y: goal.1 });
                }
                advance_corners(&map, p, &mut b.path, laws.corner_radius);
                // A long walk goes leg by leg: near the end of one that stops short of the
                // goal, plan the next from here.
                let leg_end = b.path.last().map(|l| (l.x, l.y)).unwrap_or(goal);
                if leg_end != goal && dist(p, leg_end) < REPLAN_AHEAD_M {
                    match walk_leg(ctx, b.id, &map, p, goal, &laws) {
                        Ok(path) => b.path = path,
                        Err(NoLeg::NoHeadway) => ev = Some(Event::Lost(NO_HEADWAY.into())),
                        Err(NoLeg::NoPath) => ev = Some(Event::Lost("the way is blocked".into())),
                    }
                }
            }
            if !matches!(ev, Some(Event::Lost(_))) && st.goal == GOAL_POINT {
                let w = (b.path[0].x, b.path[0].y);
                let final_leg = b.path.len() == 1 && w == goal;
                let cruise = b.speed.max(0.1);
                if final_leg && (agile || dg <= laws.slow_radius.max(0.3)) {
                    // The final approach: glide straight in, slowing, and stop on the spot
                    // (a dash goes all the way at full speed).
                    let v = if agile { cruise } else { (cruise * 0.55).max(0.4).min(cruise) };
                    let h = angle(p, goal);
                    let (dur, blocked) = geo::sweep(&map, p, &straight(h, v, dg / v), 0.0);
                    if blocked && dur < 0.05 {
                        // Cannot quite reach the spot: this is as close as it gets.
                        b.path.clear();
                        if !st.reported {
                            ev = Some(Event::Arrived);
                        }
                        st.goal = GOAL_NONE;
                        st.reported = false;
                        dirty = true;
                        stand = Some(IDLE);
                    } else {
                        set_motion(b, h, v, 0.0, 0.0);
                        b.next_ms = due(t0, dur, 1);
                        b.chunk = chunk_of(p.0, p.1);
                        if st.flags & FLAG_EARLY != 0 && !st.reported {
                            st.reported = true;
                            dirty = true;
                            ev = Some(Event::Arrived);
                        }
                        return (ev, dirty);
                    }
                } else {
                    let mut dir = angle(p, w);
                    let d0 = dist(p, w);
                    let mut max_dt = laws.steer_s;
                    let look = if final_leg {
                        (dg - laws.slow_radius) / cruise
                    } else if d0 > laws.corner_radius {
                        (d0 - laws.corner_radius) / cruise
                    } else {
                        d0 / cruise
                    };
                    max_dt = max_dt.min(look.max(0.05));
                    if dg > 2.0 && !agile {
                        let (d, crowded) = separate(ctx, b.id, p, dir, 0, &moves, now);
                        dir = d;
                        if crowded {
                            max_dt = max_dt.min(1.0 / laws.crowd_hz);
                        }
                    }
                    // At a corner it cannot see past yet (a doorway, a gate), a walker heads
                    // straight for the corner instead of arcing into the wall beside it.
                    let tight = !final_leg && d0 <= laws.corner_radius;
                    want = Some(Want { dir, speed: cruise, agile: agile || tight, max_dt });
                }
            }
        }
        GOAL_CREATURE => {
            let sight = st.flags & FLAG_SIGHT != 0;
            let found = if sight {
                held(ctx, b, st, p, now, &laws, &mut dirty)
            } else {
                let alive = ctx.db.character().id().find(st.target).map_or(false, |c| c.alive);
                match ctx.db.body().id().find(st.target) {
                    None => Err(if alive { "it is gone".into() } else { "they are dead".into() }),
                    Some(tb) => {
                        let tp = common::pos(&tb, now);
                        let d = dist(p, tp);
                        let w = common::world(ctx);
                        // A creature one smells is followed by its scent as far as that reaches.
                        let scent = common::scent_of(&b.kind).filter(|s| s.reaches(&tb.kind, d)).map_or(0.0, |s| s.radius);
                        if d > (common::sight_for(ctx, b.id, &w, now) * laws.chase_lost_share).max(scent) {
                            Err("lost sight of them".into())
                        } else {
                            Ok(Held { at: tp, vel: (tb.vx, tb.vy), seen: true })
                        }
                    }
                }
            };
            match found {
                Err(why) => ev = Some(Event::Lost(why)),
                Ok(h) => {
                    if sight {
                        look_at(st, p, h.at);
                    }
                    let tp = h.at;
                    let d = dist(p, tp);
                    // A moving target is watched at chase cadence (combat cadence in a fight);
                    // a still one needs a look only when getting there. One out of sight is
                    // looked for at chase cadence.
                    let target_moving = h.vel.0 != 0.0 || h.vel.1 != 0.0 || !h.seen;
                    let fast = target_moving && ctx.db.mind_state().id().find(b.id).map_or(false, |m| m.fast_until > now);
                    let look = if fast { 1.0 / laws.combat_hz } else { 1.0 / laws.chase_hz };
                    let max_dt = if target_moving { look } else { laws.steer_s };
                    // Only one seen is reached: its last-seen place is not it.
                    if h.seen && d <= st.keep + 0.3 && st.flags & FLAG_EARLY != 0 {
                        ev = Some(Event::Arrived);
                        st.goal = GOAL_NONE;
                        dirty = true;
                        glide_stop(&map, b, t0, 0.3);
                        b.path.clear();
                        b.chunk = chunk_of(p.0, p.1);
                        return (ev, dirty);
                    }
                    if h.seen && d <= st.keep + 0.3 && st.flags & FLAG_EACH != 0 {
                        ev = Some(Event::Arrived);
                    }
                    let push = apart_push(ctx, b, st, p, now);
                    if d <= st.keep {
                        match geo::apart_way(p, tp, None, push) {
                            // Close in, and a mate is near: round it, away from the mate.
                            Some(dir) => {
                                b.path.clear();
                                want = Some(Want { dir, speed: b.speed.max(0.1), agile, max_dt: look });
                            }
                            None => {
                                b.heading = angle(p, tp);
                                b.path.clear();
                                stand = Some(due(t0, if target_moving { look } else { 1.0 }, MIN_STEP_MS));
                            }
                        }
                    } else {
                        match toward(ctx, b, st, &map, p, tp, h.vel, st.keep, max_dt, &laws, &moves, agile, now, &mut dirty) {
                            Ok(mut w) => {
                                if let Some(dir) = geo::apart_way(p, tp, Some(w.dir), push) {
                                    w.dir = dir;
                                }
                                want = Some(w)
                            }
                            Err(why) => ev = Some(Event::Lost(why)),
                        }
                    }
                }
            }
        }
        GOAL_BAND => match held(ctx, b, st, p, now, &laws, &mut dirty) {
            Err(why) => ev = Some(Event::Lost(why)),
            Ok(h) => {
                look_at(st, p, h.at);
                let target_moving = h.vel.0 != 0.0 || h.vel.1 != 0.0 || !h.seen;
                let fast = ctx.db.mind_state().id().find(b.id).map_or(false, |m| m.fast_until > now);
                let look = if fast { 1.0 / laws.combat_hz } else { 1.0 / laws.chase_hz };
                let go = geo::going(p, (b.vx, b.vy), h.at);
                let push = apart_push(ctx, b, st, p, now);
                match geo::band_way(p, h.at, st.keep, st.far, go) {
                    // In the band, a mate within `apart`: along the band, away from the mate.
                    None if geo::apart_way(p, h.at, None, push).is_some() => {
                        b.path.clear();
                        let dir = geo::apart_way(p, h.at, None, push).unwrap_or(b.heading);
                        want = Some(Want { dir, speed: b.speed.max(0.1), agile, max_dt: look });
                    }
                    // In the band: stand facing it, looking again at chase cadence while it moves.
                    None => {
                        b.path.clear();
                        stand = Some(due(t0, if target_moving { look } else { 1.0 }, MIN_STEP_MS));
                    }
                    // Too near: straight away from it, a margin into the band.
                    Some((way, false)) => {
                        closing = Some(false);
                        let edge = st.keep + geo::band_margin(st.keep, st.far);
                        let cruise = b.speed.max(0.1);
                        let max_dt = look.min(((edge - dist(p, h.at)) / cruise).max(0.05));
                        // Backing off takes open ground as a flight does.
                        let sight = common::sight_for(ctx, b.id, &common::world(ctx), now);
                        let way = geo::flee_way(&map, p, h.at, b.heading, (edge - dist(p, h.at)).min(sight), sight, tune.clearance).unwrap_or(way);
                        let way = geo::apart_way(p, h.at, Some(way), push).unwrap_or(way);
                        let (dir, _) = separate(ctx, b.id, p, way, st.target, &moves, now);
                        b.path.clear();
                        want = Some(Want { dir, speed: cruise, agile, max_dt });
                    }
                    // Too far: toward it as a pursuit does, a margin into the band.
                    Some((_, true)) => {
                        closing = Some(true);
                        let keep = (st.far - geo::band_margin(st.keep, st.far)).max(st.keep);
                        match toward(ctx, b, st, &map, p, h.at, h.vel, keep, look, &laws, &moves, agile, now, &mut dirty) {
                            Ok(mut w) => {
                                if let Some(dir) = geo::apart_way(p, h.at, Some(w.dir), push) {
                                    w.dir = dir;
                                }
                                want = Some(w)
                            }
                            Err(why) => ev = Some(Event::Lost(why)),
                        }
                    }
                }
            }
        },
        GOAL_ORBIT => match held(ctx, b, st, p, now, &laws, &mut dirty) {
            Err(why) => ev = Some(Event::Lost(why)),
            Ok(h) => {
                look_at(st, p, h.at);
                let fast = ctx.db.mind_state().id().find(b.id).map_or(false, |m| m.fast_until > now);
                let look = if fast { 1.0 / laws.combat_hz } else { 1.0 / laws.chase_hz };
                let cruise = b.speed.max(0.1);
                let way = geo::orbit_way(p, h.at, st.keep, st.far);
                let way = geo::apart_way(p, h.at, Some(way), apart_push(ctx, b, st, p, now)).unwrap_or(way);
                // Round a circle in steps of about 0.3 rad of it, at chase cadence at most.
                let max_dt = look.min((0.3 * st.keep / cruise).max(0.1));
                let (dir, _) = separate(ctx, b.id, p, way, st.target, &moves, now);
                b.path.clear();
                want = Some(Want { dir, speed: cruise, agile, max_dt });
            }
        },
        GOAL_DIRECTION => {
            // The way it is told to go, at full speed: a held look (`human_face`) turns only the
            // facing (`settle_face`), never the travel.
            let way = st.gy.atan2(st.gx);
            let (dir, crowded) = separate(ctx, b.id, p, way, 0, &moves, now);
            let max_dt = if crowded { laws.steer_s.min(1.0 / laws.crowd_hz) } else { laws.steer_s };
            want = Some(Want { dir, speed: b.speed.max(0.1), agile, max_dt });
        }
        GOAL_FLEE => {
            let (threat, moving) = if st.flags & FLAG_SIGHT != 0 {
                // Backing off (`back_off`): from where it is seen, else from where it was last
                // seen, facing it as far as walking allows.
                let h = held(ctx, b, st, p, now, &laws, &mut dirty).unwrap_or(Held { at: (st.gx, st.gy), vel: (0.0, 0.0), seen: false });
                look_at(st, p, h.at);
                (h.at, h.vel.0 != 0.0 || h.vel.1 != 0.0)
            } else {
                let body = if st.target != 0 { ctx.db.body().id().find(st.target) } else { None };
                (body.as_ref().map(|t| common::pos(t, now)).unwrap_or((st.gx, st.gy)), body.as_ref().map_or(false, |t| t.vx != 0.0 || t.vy != 0.0))
            };
            // A threat that moves is watched; a still one only needs the way ahead looked at.
            let mut max_dt = if moving { 1.0 / laws.chase_hz } else { laws.steer_s };
            let d = dist(p, threat);
            if st.flags & FLAG_SIGHT != 0 {
                // Backing off looks again when it is due at its distance, and stops there.
                max_dt = max_dt.min(((st.keep - d) / b.speed.max(0.1)).max(0.05));
            }
            if d >= st.keep {
                ev = Some(Event::Arrived);
                st.goal = GOAL_NONE;
                dirty = true;
                glide_stop(&map, b, t0, 1.0);
                b.path.clear();
                b.chunk = chunk_of(p.0, p.1);
                return (ev, dirty);
            }
            let away = if d < 0.01 { b.heading } else { angle(threat, p) };
            // Open ground: straight away while that way is open, else toward the reachable
            // ground within sight that gains the most distance (`steer::flee_way`); with none,
            // straight away, and the plan below finds it cornered.
            let sight = common::sight_for(ctx, b.id, &common::world(ctx), now);
            let way = geo::flee_way(&map, p, threat, b.heading, (st.keep - d).min(sight), sight, tune.clearance).unwrap_or(away);
            let (dir, _) = separate(ctx, b.id, p, way, st.target, &moves, now);
            want = Some(Want { dir, speed: b.speed.max(0.1), agile, max_dt });
        }
        _ => {
            // No goal: finish a glide, then stand (turning to a held look, `human_face`).
            stand = Some(IDLE);
        }
    }
    if let Some(Event::Lost(_)) = ev {
        st.goal = GOAL_NONE;
        walk_over(ctx, b.id);
        dirty = true;
        b.path.clear();
        glide_stop(&map, b, t0, 0.3);
        b.chunk = chunk_of(p.0, p.1);
        return (ev, dirty);
    }
    if let Some(w) = want {
        let mut seg = geo::plan(&map, p, b.heading, v_cur, w, &tune);
        let mut replanned = false;
        if seg.blocked && seg.speed == 0.0 {
            // Stuck against something the coarse path did not know (a gate shut, a wall
            // built, or pushed off the path): find a new way, or give up.
            let dest = match st.goal {
                GOAL_POINT => Some((st.gx, st.gy)),
                // Held by perception: a way to where it was last seen.
                GOAL_CREATURE | GOAL_BAND if st.flags & FLAG_SIGHT != 0 => Some((st.gx, st.gy)),
                GOAL_CREATURE => ctx.db.body().id().find(st.target).map(|t| common::pos(&t, now)),
                _ => None,
            };
            if st.goal == GOAL_FLEE || (st.goal == GOAL_BAND && closing != Some(true)) {
                ev = Some(Event::Lost("cornered".into()));
            } else if st.goal == GOAL_ORBIT {
                ev = Some(Event::Lost("the way round is blocked".into()));
            } else if st.flags & FLAG_STUCK != 0 {
                // A fresh plan did not get it moving either.
                ev = Some(Event::Lost("the way is blocked".into()));
            } else if let Some(dest) = dest {
                if now.saturating_sub(st.plan_ms) >= REPLAN_MS {
                    st.plan_ms = now;
                    st.flags |= FLAG_STUCK;
                    replanned = true;
                    dirty = true;
                    // A walk to a place keeps its route (searched again if the map changed).
                    let planned = if st.goal == GOAL_POINT { walk_leg(ctx, b.id, &map, p, dest, &laws).ok() } else { leg(&map, p, dest, &laws) };
                    match planned {
                        Some(path) if !path.is_empty() => {
                            b.path = path;
                            let dir = angle(p, (b.path[0].x, b.path[0].y));
                            seg = geo::plan(&map, p, b.heading, v_cur, Want { dir, ..w }, &tune);
                        }
                        _ => ev = Some(Event::Lost("the way is blocked".into())),
                    }
                }
            }
            if let Some(Event::Lost(_)) = ev {
                st.goal = GOAL_NONE;
                walk_over(ctx, b.id);
                b.path.clear();
                halt(b);
                b.next_ms = IDLE;
                b.chunk = chunk_of(p.0, p.1);
                return (ev, true);
            }
        }
        if seg.speed > 0.0 && !seg.blocked && !replanned && st.flags & FLAG_STUCK != 0 {
            st.flags &= !FLAG_STUCK;
            dirty = true;
        }
        set_motion(b, geo::wrap(seg.heading), seg.speed, seg.turn, seg.turn_s);
        b.next_ms = if seg.speed == 0.0 && seg.turn == 0.0 { due(t0, seg.dur.max(0.25), MIN_STEP_MS) } else { due(t0, seg.dur, MIN_STEP_MS) };
    } else if let Some(until) = stand {
        // Standing, a held look turns the body to it (`settle_face`).
        halt(b);
        b.next_ms = until;
    }
    b.chunk = chunk_of(p.0, p.1);
    (ev, dirty)
}

thread_local! {
    /// Destinations a body recently found no path to (body, tile) -> when: a walk asked for
    /// again within `UNREACHABLE_MS` fails at once with the same reason instead of searching
    /// the whole budget again every second. Only a cache: a lost entry costs one search.
    static UNREACHABLE: std::cell::RefCell<std::collections::HashMap<(u32, i32, i32), u64>> = std::cell::RefCell::new(std::collections::HashMap::new());
}
const UNREACHABLE_MS: u64 = 15_000;

fn unreachable(id: u32, at: (f32, f32), now: u64) -> bool {
    UNREACHABLE.with(|u| u.borrow().get(&(id, at.0.floor() as i32, at.1.floor() as i32)).is_some_and(|t| now.saturating_sub(*t) < UNREACHABLE_MS && *t <= now))
}

fn no_path(id: u32, at: (f32, f32), now: u64) {
    UNREACHABLE.with(|u| {
        let mut u = u.borrow_mut();
        if u.len() > 4096 {
            u.retain(|_, t| now.saturating_sub(*t) < UNREACHABLE_MS);
        }
        u.insert((id, at.0.floor() as i32, at.1.floor() as i32), now);
    });
}

/// Steer toward a new goal from the current pose and speed. Returns `None` when a point goal
/// is already reached (nothing to do), otherwise what the first steering update found (an
/// arrival or a loss the caller must act on at once).
pub fn start(ctx: &ReducerContext, id: u32, goal: Goal, now: u64) -> Result<Option<Option<Event>>, String> {
    let Some(mut b) = ctx.db.body().id().find(id) else {
        return Err("no body".into());
    };
    let map = common::map(ctx);
    let p = common::pos(&b, now);
    let (mut st, exists) = load_steer(ctx, id);
    let before = b.chunk;
    b.path.clear();
    // A new goal: any walk's route so far is not this one's.
    walk_over(ctx, id);
    let mut at = goal.at;
    match goal.kind {
        GOAL_POINT => {
            if !map.free(at.0, at.1) {
                at = map.nearest_reachable(p, at.0, at.1).ok_or("destination unreachable")?;
            }
            if dist(p, at) <= 0.06 {
                return Ok(None);
            }
            if unreachable(id, at, now) {
                return Err("no path there".into());
            }
            let Ok(path) = walk_leg(ctx, id, &map, p, at, &common::laws(ctx)) else {
                no_path(id, at, now);
                return Err("no path there".into());
            };
            b.path = path;
        }
        GOAL_DIRECTION => {
            let n = (at.0 * at.0 + at.1 * at.1).sqrt();
            if n < 1e-3 {
                return Err("no direction".into());
            }
            at = (at.0 / n, at.1 / n);
        }
        _ => {}
    }
    // A walk of any other kind (a path, a pursuit, a flight; a mind's or a command's) faces
    // its way: a player's held look serves only its own movement keys.
    if goal.kind != GOAL_DIRECTION {
        st.look_on = false;
    }
    st.goal = goal.kind;
    st.target = goal.target;
    st.gx = at.0;
    st.gy = at.1;
    st.keep = goal.keep;
    st.far = goal.far;
    st.apart = goal.apart;
    // Held by sight: it starts in sight (the act's check).
    st.unseen_ms = 0;
    // A run already under way keeps its drain (and needs no breath to start again).
    let draining = st.flags & FLAG_DRAIN;
    st.flags = goal.flags | draining;
    st.reported = false;
    st.plan_ms = 0;
    st.pace = goal.pace;
    st.run_pace = if goal.flags & FLAG_RUN != 0 { goal.speed } else { 0.0 };
    b.speed = goal.speed;
    if goal.flags & FLAG_RUN != 0 && draining == 0 && crate::breath::stamina_now(ctx, id, now) < common::pools_of(ctx, id, now).breath.resume {
        // Not enough breath to set off running: it walks until it has.
        st.flags |= FLAG_WINDED;
        b.speed = goal.pace;
    }
    let (ev, _) = update(ctx, &mut b, &mut st, now);
    save_steer(ctx, st, exists);
    put(ctx, b, before);
    Ok(Some(ev))
}

/// Stop where the body stands, at once (work, a windup, a guard).
pub fn stop(ctx: &ReducerContext, id: u32, now: u64) {
    let Some(mut b) = ctx.db.body().id().find(id) else { return };
    let (mut st, exists) = load_steer(ctx, id);
    let look = st.look_on.then_some(st.look);
    if exists && (st.goal != GOAL_NONE || st.flags & FLAG_DRAIN != 0) {
        st.goal = GOAL_NONE;
        st.reported = false;
        end_run(ctx, &mut st, id, now);
        save_steer(ctx, st, exists);
    }
    if b.next_ms == IDLE && b.path.is_empty() && b.vx == 0.0 && b.vy == 0.0 {
        return;
    }
    let before = b.chunk;
    let t0 = resume_at(&b, now);
    anchor(&mut b, t0);
    resumed(b.id, t0, now);
    let cut = b.turn_s > 0.0;
    halt(&mut b);
    turn_cut(ctx, &mut b, cut, look);
    b.path.clear();
    b.next_ms = IDLE;
    b.chunk = chunk_of(b.x, b.y);
    put(ctx, b, before);
}

/// Turn a standing body where it stands to face `toward`, at the `turn_rate` law (one row
/// write; observers see the turn as the segment's arc, and a facing offset left from a walk
/// coming back over it: `turn_to`). A moving body is left alone: its steering keeps its heading.
pub fn face(ctx: &ReducerContext, id: u32, toward: (f32, f32), now: u64) {
    let Some(mut b) = ctx.db.body().id().find(id) else { return };
    if b.next_ms != IDLE || b.vx != 0.0 || b.vy != 0.0 {
        return;
    }
    let before = b.chunk;
    anchor(&mut b, now);
    let want = (toward.1 - b.y).atan2(toward.0 - b.x);
    if (toward.0 - b.x).hypot(toward.1 - b.y) < 0.05 {
        return;
    }
    let rate = common::moves_of(ctx, id, now).turn_rate.max(0.5);
    if !turn_to(&mut b, want, rate, 0.05) {
        return;
    }
    b.next_ms = IDLE;
    put(ctx, b, before);
}

/// Drop the goal and coast to a stand (an activity replaced or abandoned). A goal set in
/// the same transaction takes over with the body's momentum.
pub fn brake(ctx: &ReducerContext, id: u32, now: u64) {
    let (mut st, exists) = load_steer(ctx, id);
    let look = st.look_on.then_some(st.look);
    if exists && (st.goal != GOAL_NONE || st.flags & FLAG_DRAIN != 0) {
        st.goal = GOAL_NONE;
        st.reported = false;
        end_run(ctx, &mut st, id, now);
        save_steer(ctx, st, exists);
    }
    let Some(mut b) = ctx.db.body().id().find(id) else { return };
    if b.next_ms == IDLE && b.vx == 0.0 && b.vy == 0.0 {
        return;
    }
    let before = b.chunk;
    let t0 = resume_at(&b, now);
    anchor(&mut b, t0);
    resumed(b.id, t0, now);
    b.path.clear();
    let cut = b.turn_s > 0.0;
    glide_stop(&common::map(ctx), &mut b, t0, 0.3);
    turn_cut(ctx, &mut b, cut, look);
    b.chunk = chunk_of(b.x, b.y);
    put(ctx, b, before);
}

/// Process one due body (its steering update). Returns an event for its activity.
pub fn advance(ctx: &ReducerContext, mut b: Body, now: u64) -> Option<Event> {
    let (mut st, exists) = load_steer(ctx, b.id);
    let before = b.chunk;
    let (ev, dirty) = update(ctx, &mut b, &mut st, now);
    if dirty {
        save_steer(ctx, st, exists);
    }
    put(ctx, b, before);
    ev
}

/// A player's movement intent: move in `dir` (unit-less; `None` = stop) at walking or
/// running speed. Rate-limited per character by the `input_hz`/`input_burst` laws;
/// repeating the current intent costs nothing.
pub fn intent(ctx: &ReducerContext, id: u32, dir: Option<(f32, f32)>, run: bool, walk_speed: impl FnOnce() -> f32, now: u64) -> Result<(), String> {
    let (mut st, exists) = load_steer(ctx, id);
    let laws = common::laws(ctx);
    let run_flag = if run { FLAG_RUN } else { 0 };
    let unit = dir.and_then(|(x, y)| {
        let n = (x * x + y * y).sqrt();
        (n.is_finite() && n > 1e-3).then(|| (x / n, y / n))
    });
    let same = match unit {
        None => st.goal != GOAL_DIRECTION,
        Some(u) => st.goal == GOAL_DIRECTION && st.flags & FLAG_RUN == run_flag && (u.0 * st.gx + u.1 * st.gy) > 0.9998,
    };
    if same {
        return Ok(());
    }
    let refill = now.saturating_sub(st.input_ms) as f32 / 1000.0 * laws.input_hz;
    let tokens = if exists { (st.tokens + refill).min(laws.input_burst) } else { laws.input_burst };
    if tokens < 1.0 {
        return Err("too many movement inputs".into());
    }
    st.tokens = tokens - 1.0;
    st.input_ms = now;
    let keep_speed = st.goal == GOAL_DIRECTION && st.flags & FLAG_RUN == run_flag;
    let kept = (st.run_pace, st.pace);
    save_steer(ctx, st, exists);
    match unit {
        None => {
            brake(ctx, id, now);
            Ok(())
        }
        Some(u) => {
            // A run costs breath and becomes a walk without it, as for every controller.
            let (speed, pace) = match ctx.db.body().id().find(id) {
                Some(_) if keep_speed && run => kept,
                Some(b) if keep_speed => (b.speed, b.speed),
                _ => {
                    let walk = walk_speed();
                    (walk * if run { common::moves_of(ctx, id, now).run } else { 1.0 }, walk)
                }
            };
            start(ctx, id, Goal { kind: GOAL_DIRECTION, target: 0, at: u, keep: 0.0, speed, flags: run_flag, pace, far: 0.0, apart: 0.0 }, now).map(|_| ())
        }
    }
}

/// A held look (`human_face`): face `dir` (`None`: release, the facing returns to the way the
/// body walks). Standing, the body turns where it stands at its turn rate. Walking under its
/// movement keys, it still goes where the keys say at full speed; only its facing (`body.face_*`,
/// `common::facing_at`) turns toward the look at the turn rate, at most the `look_walk_deg` law
/// off its way, and when it stops the whole body finishes the turn. A look within the
/// `look_slack_deg` law of the held one (or, standing, of where the body faces) writes nothing;
/// any other spends a token of the movement input bucket.
pub fn look(ctx: &ReducerContext, id: u32, dir: Option<(f32, f32)>, now: u64) -> Result<(), String> {
    let (mut st, exists) = load_steer(ctx, id);
    let laws = common::laws(ctx);
    let slack = laws.look_slack_deg.to_radians();
    let want = dir.and_then(|(x, y)| (x.is_finite() && y.is_finite() && x.hypot(y) > 1e-3).then(|| y.atan2(x)));
    let Some(b) = ctx.db.body().id().find(id) else { return Err("no body".into()) };
    let moving = b.vx != 0.0 || b.vy != 0.0;
    let walking = st.goal == GOAL_DIRECTION;
    match want {
        None if !st.look_on => return Ok(()),
        Some(w) if st.look_on && geo::wrap(w - st.look).abs() <= slack && (moving || geo::wrap(w - common::facing_at(&b, now)).abs() <= slack) => return Ok(()),
        Some(w) if !st.look_on && !moving && geo::wrap(w - common::facing_at(&b, now)).abs() <= slack => return Ok(()),
        _ => {}
    }
    let refill = now.saturating_sub(st.input_ms) as f32 / 1000.0 * laws.input_hz;
    let tokens = if exists { (st.tokens + refill).min(laws.input_burst) } else { laws.input_burst };
    if tokens < 1.0 {
        return Err("too many movement inputs".into());
    }
    st.tokens = tokens - 1.0;
    st.input_ms = now;
    st.look_on = want.is_some();
    if let Some(w) = want {
        st.look = w;
    }
    let (gx, gy, flags) = (st.gx, st.gy, st.flags & (FLAG_RUN | FLAG_EARLY | FLAG_EACH | FLAG_AGILE));
    let (speed, pace) = if flags & FLAG_RUN != 0 { (st.run_pace, st.pace) } else { (b.speed, b.speed) };
    save_steer(ctx, st, exists);
    if walking && moving {
        // Steer again now: the facing toward the look or back to the way (the travel is unchanged).
        start(ctx, id, Goal { kind: GOAL_DIRECTION, target: 0, at: (gx, gy), keep: 0.0, speed, flags, pace, far: 0.0, apart: 0.0 }, now).map(|_| ())
    } else if let (Some(w), false) = (want, moving) {
        let p = common::pos(&b, now);
        face(ctx, id, (p.0 + w.cos(), p.1 + w.sin()), now);
        Ok(())
    } else {
        // A release while standing keeps the facing; a look during a glide or a dash is taken
        // when the body stands.
        Ok(())
    }
}

/// Spend one token of a player's input bucket (the `input_hz`/`input_burst` laws, shared with
/// movement) for a skill input; false when the bucket is empty.
pub fn spend_input(ctx: &ReducerContext, id: u32, now: u64) -> bool {
    let (mut st, exists) = load_steer(ctx, id);
    let laws = common::laws(ctx);
    let refill = now.saturating_sub(st.input_ms) as f32 / 1000.0 * laws.input_hz;
    let tokens = if exists { (st.tokens + refill).min(laws.input_burst) } else { laws.input_burst };
    if tokens < 1.0 {
        return false;
    }
    st.tokens = tokens - 1.0;
    st.input_ms = now;
    save_steer(ctx, st, exists);
    true
}

/// Re-steer bodies near a place whose passability changed (a gate shut, a wall built).
pub fn resteer_near(ctx: &ReducerContext, at: (f32, f32), r: f32, now: u64) {
    for c in living_rules::map::chunks_around(at.0, at.1, r) {
        let moving: Vec<Body> = ctx.db.body().chunk().filter(c).filter(|b| b.next_ms != IDLE && b.next_ms > now).collect();
        for mut b in moving {
            if dist(common::pos(&b, now), at) <= r {
                let t0 = resume_at(&b, now);
                anchor(&mut b, t0);
                resumed(b.id, t0, now);
                b.next_ms = now;
                crate::frame::moved(b.id);
                ctx.db.body().id().update(b);
            }
        }
    }
}

/// Put a body somewhere at rest (test support).
pub fn place(ctx: &ReducerContext, id: u32, at: (f32, f32), now: u64) -> Result<(), String> {
    let mut b = ctx.db.body().id().find(id).ok_or("no such body")?;
    let (mut st, exists) = load_steer(ctx, id);
    if exists {
        st.goal = GOAL_NONE;
        end_run(ctx, &mut st, id, now);
        save_steer(ctx, st, exists);
    }
    b.x = at.0;
    b.y = at.1;
    b.t_ms = now;
    halt(&mut b);
    b.face_off = 0.0;
    b.face_turn = 0.0;
    b.face_turn_s = 0.0;
    b.path.clear();
    b.next_ms = IDLE;
    b.chunk = chunk_of(at.0, at.1);
    crate::frame::moved(b.id);
    ctx.db.body().id().update(b);
    common::invalidate_bodies();
    Ok(())
}

pub fn remove(ctx: &ReducerContext, id: u32) {
    ctx.db.steer().id().delete(id);
    walk_over(ctx, id);
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
        heading: (id as f32 * 2.399_963).rem_euclid(geo::TAU) - geo::PI,
        turn: 0.0,
        turn_s: 0.0,
        face_off: 0.0,
        face_turn: 0.0,
        face_turn_s: 0.0,
        running: false,
    });
}
