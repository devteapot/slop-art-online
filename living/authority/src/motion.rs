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

/// Report arrival when the final approach begins (the body glides on to the spot), so the
/// next activity takes over with momentum. Without it, arrival is reported at the goal.
pub const FLAG_EARLY: u8 = 1;
/// Report every steering update within reach of a creature (an approach checking its reach).
pub const FLAG_EACH: u8 = 2;
/// A dash: heading at once, no ramp and no slowing at the end.
pub const FLAG_AGILE: u8 = 4;
/// A player's run (the intent is kept while the same key is held).
pub const FLAG_RUN: u8 = 8;
/// Stuck once already; re-planned (internal).
const FLAG_STUCK: u8 = 16;

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
}

impl Goal {
    pub fn point(at: (f32, f32), speed: f32, flags: u8) -> Self {
        Self { kind: GOAL_POINT, target: 0, at, keep: 0.0, speed, flags }
    }
    pub fn creature(id: u32, keep: f32, speed: f32, flags: u8) -> Self {
        Self { kind: GOAL_CREATURE, target: id, at: (0.0, 0.0), keep, speed, flags }
    }
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
    Steer { id, goal: GOAL_NONE, target: 0, gx: 0.0, gy: 0.0, keep: 0.0, flags: 0, reported: false, plan_ms: 0, tokens: 0.0, input_ms: 0 }
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
    ctx.db.body().id().update(b);
}

/// Longest a finished segment is continued from where it ended, not from `now`.
const RESUME_MS: u64 = 40;

thread_local! {
    /// Segments this transaction began before its `now` (`resume_at`): the transaction's
    /// `now` and, per body, the segment's start.
    static RESUMED: std::cell::RefCell<(u64, std::collections::HashMap<u32, u64>)> = Default::default();
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
        r.0 == now && r.1.get(&b.id) == Some(&b.t_ms)
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
        if r.0 != now {
            r.0 = now;
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

fn angle(from: (f32, f32), to: (f32, f32)) -> f32 {
    (to.1 - from.1).atan2(to.0 - from.0)
}

/// One steering update at `now`: writes the new segment (from `resume_at`) into `b` and
/// possibly `st`.
/// Returns an event for the driving activity and whether `st` changed.
fn update(ctx: &ReducerContext, b: &mut Body, st: &mut Steer, now: u64) -> (Option<Event>, bool) {
    let laws = common::laws(ctx);
    let moves = common::moves_of(ctx, b.id, now);
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
            let target = ctx.db.body().id().find(st.target);
            let alive = ctx.db.character().id().find(st.target).map_or(false, |c| c.alive);
            match target {
                None => ev = Some(Event::Lost(if alive { "it is gone".into() } else { "they are dead".into() })),
                Some(tb) => {
                    let tp = common::pos(&tb, now);
                    let d = dist(p, tp);
                    let w = common::world(ctx);
                    // A moving target is watched at chase cadence (combat cadence in a fight);
                    // a still one needs a look only when getting there.
                    let target_moving = tb.vx != 0.0 || tb.vy != 0.0;
                    let fast = target_moving && ctx.db.mind_state().id().find(b.id).map_or(false, |m| m.fast_until > now);
                    let look = if fast { 1.0 / laws.combat_hz } else { 1.0 / laws.chase_hz };
                    let mut max_dt = if target_moving { look } else { laws.steer_s };
                    // A creature one smells is followed by its scent as far as that reaches.
                    let scent = common::scent_of(&b.kind).filter(|s| s.reaches(&tb.kind, d)).map_or(0.0, |s| s.radius);
                    if d > (common::sight_for(ctx, b.id, &w, now) * laws.chase_lost_share).max(scent) {
                        ev = Some(Event::Lost("lost sight of them".into()));
                    } else if d <= st.keep + 0.3 && st.flags & FLAG_EARLY != 0 {
                        ev = Some(Event::Arrived);
                        st.goal = GOAL_NONE;
                        dirty = true;
                        glide_stop(&map, b, t0, 0.3);
                        b.path.clear();
                        b.chunk = chunk_of(p.0, p.1);
                        return (ev, dirty);
                    } else {
                        if d <= st.keep + 0.3 && st.flags & FLAG_EACH != 0 {
                            ev = Some(Event::Arrived);
                        }
                        if d <= st.keep {
                            b.heading = angle(p, tp);
                            b.path.clear();
                            stand = Some(due(t0, if target_moving { look } else { 1.0 }, MIN_STEP_MS));
                        } else {
                            let cruise = b.speed.max(0.1);
                            let v = cruise * ((d - st.keep) / laws.slow_radius.max(0.1)).clamp(0.35, 1.0);
                            // Aim where they are going to be.
                            let lead = (d / cruise).min(1.0);
                            let ahead = (tp.0 + tb.vx * lead, tp.1 + tb.vy * lead);
                            let aim = if map.free(ahead.0, ahead.1) { ahead } else { tp };
                            let mut w = aim;
                            if map.line_clear(p, aim) {
                                b.path.clear();
                            } else {
                                let stale = b.path.last().map_or(true, |l| dist((l.x, l.y), tp) > 2.0);
                                if stale && now.saturating_sub(st.plan_ms) >= REPLAN_MS {
                                    st.plan_ms = now;
                                    dirty = true;
                                    match leg(&map, p, tp, &laws) {
                                        Some(path) => b.path = path,
                                        None => {
                                            if b.path.is_empty() {
                                                ev = Some(Event::Lost("cannot reach them".into()));
                                            }
                                        }
                                    }
                                }
                                advance_corners(&map, p, &mut b.path, laws.corner_radius);
                                if let Some(c) = b.path.first() {
                                    w = (c.x, c.y);
                                }
                            }
                            if !matches!(ev, Some(Event::Lost(_))) {
                                max_dt = max_dt.min(((d - st.keep) / v).max(0.05));
                                let (dir, _) = separate(ctx, b.id, p, angle(p, w), st.target, &moves, now);
                                want = Some(Want { dir, speed: v, agile, max_dt });
                            }
                        }
                    }
                }
            }
        }
        GOAL_DIRECTION => {
            let (dir, crowded) = separate(ctx, b.id, p, st.gy.atan2(st.gx), 0, &moves, now);
            let max_dt = if crowded { laws.steer_s.min(1.0 / laws.crowd_hz) } else { laws.steer_s };
            want = Some(Want { dir, speed: b.speed.max(0.1), agile, max_dt });
        }
        GOAL_FLEE => {
            let body = if st.target != 0 { ctx.db.body().id().find(st.target) } else { None };
            let threat = body.as_ref().map(|t| common::pos(t, now)).unwrap_or((st.gx, st.gy));
            // A threat that moves is watched; a still one only needs the way ahead looked at.
            let max_dt = if body.as_ref().map_or(false, |t| t.vx != 0.0 || t.vy != 0.0) { 1.0 / laws.chase_hz } else { laws.steer_s };
            let d = dist(p, threat);
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
            let (dir, _) = separate(ctx, b.id, p, away, st.target, &moves, now);
            want = Some(Want { dir, speed: b.speed.max(0.1), agile, max_dt });
        }
        _ => {
            // No goal: finish a glide, then stand.
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
                GOAL_CREATURE => ctx.db.body().id().find(st.target).map(|t| common::pos(&t, now)),
                _ => None,
            };
            if st.goal == GOAL_FLEE {
                ev = Some(Event::Lost("cornered".into()));
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
    st.goal = goal.kind;
    st.target = goal.target;
    st.gx = at.0;
    st.gy = at.1;
    st.keep = goal.keep;
    st.flags = goal.flags;
    st.reported = false;
    st.plan_ms = 0;
    b.speed = goal.speed;
    let (ev, _) = update(ctx, &mut b, &mut st, now);
    save_steer(ctx, st, exists);
    put(ctx, b, before);
    Ok(Some(ev))
}

/// Stop where the body stands, at once (work, a windup, a guard).
pub fn stop(ctx: &ReducerContext, id: u32, now: u64) {
    let Some(mut b) = ctx.db.body().id().find(id) else { return };
    let (mut st, exists) = load_steer(ctx, id);
    if exists && st.goal != GOAL_NONE {
        st.goal = GOAL_NONE;
        st.reported = false;
        save_steer(ctx, st, exists);
    }
    if b.next_ms == IDLE && b.path.is_empty() && b.vx == 0.0 && b.vy == 0.0 {
        return;
    }
    let before = b.chunk;
    let t0 = resume_at(&b, now);
    anchor(&mut b, t0);
    resumed(b.id, t0, now);
    halt(&mut b);
    b.path.clear();
    b.next_ms = IDLE;
    b.chunk = chunk_of(b.x, b.y);
    put(ctx, b, before);
}

/// Turn a standing body where it stands to face `toward`, at the `turn_rate` law (one row
/// write; observers see the turn as the segment's arc). A moving body is left alone: its
/// steering keeps its heading.
pub fn face(ctx: &ReducerContext, id: u32, toward: (f32, f32), now: u64) {
    let Some(mut b) = ctx.db.body().id().find(id) else { return };
    if b.next_ms != IDLE || b.vx != 0.0 || b.vy != 0.0 {
        return;
    }
    let before = b.chunk;
    anchor(&mut b, now);
    let want = (toward.1 - b.y).atan2(toward.0 - b.x);
    let d = geo::wrap(want - b.heading);
    if d.abs() < 0.05 || (toward.0 - b.x).hypot(toward.1 - b.y) < 0.05 {
        return;
    }
    let rate = common::moves_of(ctx, id, now).turn_rate.max(0.5);
    let h = b.heading;
    set_motion(&mut b, h, 0.0, rate * d.signum(), d.abs() / rate);
    b.next_ms = IDLE;
    put(ctx, b, before);
}

/// Drop the goal and coast to a stand (an activity replaced or abandoned). A goal set in
/// the same transaction takes over with the body's momentum.
pub fn brake(ctx: &ReducerContext, id: u32, now: u64) {
    let (mut st, exists) = load_steer(ctx, id);
    if exists && st.goal != GOAL_NONE {
        st.goal = GOAL_NONE;
        st.reported = false;
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
    glide_stop(&common::map(ctx), &mut b, t0, 0.3);
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
    save_steer(ctx, st, exists);
    match unit {
        None => {
            brake(ctx, id, now);
            Ok(())
        }
        Some(u) => {
            let speed = match ctx.db.body().id().find(id) {
                Some(b) if keep_speed => b.speed,
                _ => walk_speed() * if run { common::moves_of(ctx, id, now).run } else { 1.0 },
            };
            start(ctx, id, Goal { kind: GOAL_DIRECTION, target: 0, at: u, keep: 0.0, speed, flags: run_flag }, now).map(|_| ())
        }
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
        save_steer(ctx, st, exists);
    }
    b.x = at.0;
    b.y = at.1;
    b.t_ms = now;
    halt(&mut b);
    b.path.clear();
    b.next_ms = IDLE;
    b.chunk = chunk_of(at.0, at.1);
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
    });
}
