//! Steering locomotion: pure geometry shared by the authority and the viewer.
//!
//! A body moves along *segments*: from a pose `(x, y, heading)` at `t_ms`, at constant
//! speed, first turning at `turn` rad/s for `turn_s` seconds (a circular arc) and then
//! going straight. Positions between steering updates are analytic ([`pose`]), so the
//! authority writes a body only when steering changes something, never per tick; a
//! turn toward the way ahead and the straight walk after it are one segment, one write.
//!
//! A steering update ([`plan`]) turns the heading toward a desired direction at a bounded
//! turn rate (a standing body turns on the spot), slows for sharp turns, speeds up with the
//! road just ahead, and sweeps the segment across the map so it ends before an obstacle or
//! just past a chunk boundary.

use crate::map::{chunk_of, Map, Terrain};

pub const TAU: f32 = std::f32::consts::TAU;
pub const PI: f32 = std::f32::consts::PI;

/// Pose after moving `dt` seconds on a constant-turn arc (no straight part).
pub fn arc(x: f32, y: f32, heading: f32, speed: f32, turn: f32, dt: f32) -> (f32, f32, f32) {
    if dt <= 0.0 {
        return (x, y, heading);
    }
    if speed == 0.0 {
        return (x, y, heading + turn * dt);
    }
    if turn.abs() < 1e-4 {
        return (x + speed * heading.cos() * dt, y + speed * heading.sin() * dt, heading);
    }
    let h1 = heading + turn * dt;
    let r = speed / turn;
    (x + r * (h1.sin() - heading.sin()), y - r * (h1.cos() - heading.cos()), h1)
}

/// Pose `dt` seconds into a segment: turning at `turn` for the first `turn_s` seconds,
/// straight afterwards.
pub fn pose(x: f32, y: f32, heading: f32, speed: f32, turn: f32, turn_s: f32, dt: f32) -> (f32, f32, f32) {
    if turn == 0.0 || turn_s <= 0.0 {
        return arc(x, y, heading, speed, 0.0, dt);
    }
    if dt <= turn_s {
        return arc(x, y, heading, speed, turn, dt);
    }
    let (x1, y1, h1) = arc(x, y, heading, speed, turn, turn_s);
    arc(x1, y1, h1, speed, 0.0, dt - turn_s)
}

/// Wrap an angle to (-π, π].
pub fn wrap(a: f32) -> f32 {
    let mut a = a % TAU;
    if a > PI {
        a -= TAU;
    } else if a <= -PI {
        a += TAU;
    }
    a
}

// ---- facing ----------------------------------------------------------------------------
//
// A body's facing (where its head and chest point: what facing sight, a guard's default and
// "you face" read) is its travel heading plus an offset that turns on a segment of its own:
// `off` at the segment's start, changing at `turn` rad/s for the first `turn_s` seconds, then
// held. The offset is not wrapped (wrap the sum). The facing never jumps and turns at most the
// body's turn rate in the world ([`walk_facing`], [`stand_facing`]); settled, the offset is within
// the `look_walk_deg` law while the body moves, and after a sudden change of the travel it may
// stand past it until it has turned back. A body with no held look has offset 0 and faces its heading. The authority
// and the clients evaluate it with these functions on the same `body` fields
// (`face_off`, `face_turn`, `face_turn_s`, from `t_ms`), so there is one definition.

/// The facing offset `dt` seconds into its segment.
pub fn face_off(off: f32, turn: f32, turn_s: f32, dt: f32) -> f32 {
    if turn == 0.0 || turn_s <= 0.0 {
        return off;
    }
    off + turn * dt.clamp(0.0, turn_s)
}

/// Which way a body faces `dt` seconds into its segment, its travel heading then being
/// `heading_now` (`pose`'s third value at the same `dt`).
pub fn facing(heading_now: f32, off: f32, turn: f32, turn_s: f32, dt: f32) -> f32 {
    wrap(heading_now + face_off(off, turn, turn_s, dt))
}

/// The facing segment `(turn, turn_s)` that takes the offset from `from` to `to` at `rate`
/// rad/s (none when they are equal).
pub fn face_turn(from: f32, to: f32, rate: f32) -> (f32, f32) {
    let d = to - from;
    if d.abs() < 1e-4 || rate <= 0.0 {
        return (0.0, 0.0);
    }
    (rate * d.signum(), d.abs() / rate)
}

/// A look within this of straight behind the way keeps the side the facing is already turned
/// to (radians): looking back over one shoulder does not swing the head across the front when
/// the look, or the way, wavers across the line behind.
pub const BEHIND_BAND: f32 = 15.0 * PI / 180.0;

/// The facing offset a body walking along `way` wants while it holds a look at `look`: the
/// look's angle from the way, clamped to `limit` radians either side (the `look_walk_deg`
/// law); within [`BEHIND_BAND`] of straight behind, on the side of the offset it has now
/// (`current`). The travel itself does not bend: the body goes where it is told, at full speed.
pub fn walk_face(way: f32, look: f32, limit: f32, current: f32) -> f32 {
    let limit = limit.clamp(0.0, PI);
    let mut d = wrap(look - way);
    if d.abs() > limit && d.abs() >= PI - BEHIND_BAND && current != 0.0 && current.signum() != d.signum() {
        d = current.signum() * d.abs();
    }
    d.clamp(-limit, limit)
}

/// A standing turn to face `want`, from travel heading `heading` and facing offset `off`:
/// the legs' turn `d_legs` (radians, signed; the way the upper body turns, so a body that faces
/// part way round already finishes that way) and the offset's end (0: the whole body faces it).
/// With no offset it is the plain shortest turn of the heading, as a standing body always
/// turned.
pub fn stand_turn(heading: f32, off: f32, want: f32) -> f32 {
    let d_face = wrap(want - wrap(heading + off));
    d_face + off
}

/// A facing segment (`body.face_*`): the offset from the travel heading at the segment's start,
/// its turn (rad/s) and for how long it turns; `due_s`, when set, asks steering to look again
/// that many seconds into the segment (the facing has more turning to do than this segment
/// carries).
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct FaceSeg {
    pub off: f32,
    pub turn: f32,
    pub turn_s: f32,
    pub due_s: Option<f32>,
}

/// The facing segment after a steering update, from where the body faced at the update
/// (`before`, world radians) over a travel segment that starts at `heading` and turns at
/// `turn` rad/s for `turn_s` seconds. It settles toward the held `look` within `limit` of the
/// travel's heading at the end of that turn (`walk_face`, on the side of that heading the
/// facing is on now), or on the travel with no look.
///
/// The facing never jumps and, in the world, never turns faster than `rate` rad/s: it goes
/// on from `before` (the offset is re-based on the new heading, not clamped, so after a sudden
/// change of the travel it may stand past `limit` until it has turned back within it), the
/// shorter way round to where it settles. Over the travel's own turn, the offset is set so that
/// the facing turns at an even rate across that turn (it stays put when the look holds it);
/// when it has further to go than `rate` allows in that time, it turns at `rate` and `due_s`
/// asks steering to look again at the end of the travel's turn to finish.
pub fn walk_facing(before: f32, heading: f32, turn: f32, turn_s: f32, look: Option<f32>, limit: f32, rate: f32) -> FaceSeg {
    let off = wrap(before - heading);
    let arc = if turn_s > 0.0 && turn != 0.0 { turn * turn_s } else { 0.0 };
    let end = heading + arc;
    let to = look.map_or(0.0, |l| walk_face(end, l, limit, wrap(before - end)));
    // How far the facing turns in the world, the shorter way.
    let world = wrap(end + to - before);
    if arc == 0.0 {
        let (turn, turn_s) = face_turn(off, off + world, rate);
        return FaceSeg { off, turn, turn_s, due_s: None };
    }
    let w = world.signum() * (world.abs() / turn_s).min(rate);
    let due_s = (world.abs() > rate * turn_s + 1e-4).then_some(turn_s);
    let rel = w - turn;
    if rel.abs() < 1e-6 {
        return FaceSeg { off, turn: 0.0, turn_s: 0.0, due_s };
    }
    FaceSeg { off, turn: rel, turn_s, due_s }
}

/// A standing body's turn to face `want` from travel heading `heading` with facing offset `off`
/// (`stand_turn`): the legs' turn (rad/s, seconds; 0 when they stay) and the facing segment.
/// The legs and the facing arrive together, neither turning faster than `rate` (the legs
/// slower when the facing has further to go). Within `slack` of it the legs stay and only the
/// facing finishes. None: nothing to do.
pub fn stand_facing(heading: f32, off: f32, want: f32, rate: f32, slack: f32) -> Option<((f32, f32), FaceSeg)> {
    let d = stand_turn(heading, off, want);
    if d.abs() > slack {
        let dur = d.abs().max((d - off).abs()) / rate;
        let face = if off != 0.0 { FaceSeg { off, turn: -off / dur, turn_s: dur, due_s: None } } else { FaceSeg::default() };
        Some(((d / dur, dur), face))
    } else if off != 0.0 {
        let (turn, turn_s) = face_turn(off, d, rate);
        Some(((0.0, 0.0), FaceSeg { off, turn, turn_s, due_s: None }))
    } else {
        None
    }
}

/// Steering constants (world laws; see `Laws`).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Tuning {
    /// Maximum turn rate while moving, rad/s.
    pub turn_rate: f32,
    /// Heading errors below this are taken up at once (no arc).
    pub snap: f32,
    /// Turns sharper than this slow down (an arc on its own, then a new look).
    pub sharp: f32,
    /// Speed kept in the sharpest turns (fraction of desired).
    pub turn_slow: f32,
    /// Keep the body's center this far from obstacles ahead.
    pub clearance: f32,
    /// Walking speed multiplier on road tiles.
    pub road_speed: f32,
    /// The road's bonus stops at this speed (m/s; a body faster on its own keeps its speed).
    pub top: f32,
}

impl Default for Tuning {
    fn default() -> Self {
        Self { turn_rate: 6.0, snap: 0.12, sharp: 1.1, turn_slow: 0.4, clearance: 0.25, road_speed: 1.4, top: f32::INFINITY }
    }
}

/// One planned segment.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Segment {
    pub heading: f32,
    pub speed: f32,
    pub turn: f32,
    /// Seconds of turning at the start of the segment (then straight).
    pub turn_s: f32,
    /// Seconds until the next steering update is due.
    pub dur: f32,
    /// The sweep stopped at an obstacle (the next update must find another way).
    pub blocked: bool,
}

impl Segment {
    pub fn still(heading: f32, dur: f32) -> Self {
        Self { heading, speed: 0.0, turn: 0.0, turn_s: 0.0, dur, blocked: false }
    }
    /// Pose `dt` seconds into this segment from `p`.
    pub fn at(&self, p: (f32, f32), dt: f32) -> (f32, f32, f32) {
        pose(p.0, p.1, self.heading, self.speed, self.turn, self.turn_s, dt)
    }
}

/// How the body should move now.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Want {
    /// Desired direction of travel, radians.
    pub dir: f32,
    /// Desired speed off-road (tiles/s); roads multiply it.
    pub speed: f32,
    /// Take the heading at once (a dash, a slide along a wall): no turn limit.
    pub agile: bool,
    /// Longest the segment may last before steering looks again, seconds.
    pub max_dt: f32,
}

fn smoothstep(a: f32, b: f32, x: f32) -> f32 {
    let t = ((x - a) / (b - a)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

/// Whether a body can be at `p` moving along `h` (terrain there and just ahead).
pub fn passable(map: &Map, p: (f32, f32), h: f32, clearance: f32) -> bool {
    map.free(p.0, p.1) && map.free(p.0 + h.cos() * clearance, p.1 + h.sin() * clearance)
}

/// Plan a segment from pose `(p, heading)` moving at `cur_speed` toward `want`.
pub fn plan(map: &Map, p: (f32, f32), heading: f32, cur_speed: f32, want: Want, t: &Tuning) -> Segment {
    if want.speed <= 0.0 {
        return Segment::still(heading, want.max_dt);
    }
    let first = sweep_plan(map, p, heading, cur_speed, want.dir, want, t);
    if !first.blocked || first.dur > 0.12 {
        return first;
    }
    // Blocked right ahead: turn on the spot toward the wish, or slide along the obstacle,
    // trying directions nearest the wish first.
    for off in [0.0f32, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5] {
        let dir = want.dir + off;
        let slide = Want { agile: true, speed: want.speed * 0.8, ..want };
        let s = sweep_plan(map, p, dir, cur_speed, dir, slide, t);
        if s.dur >= 0.15 {
            return s;
        }
    }
    Segment { blocked: true, ..Segment::still(heading, want.max_dt.min(0.5)) }
}

fn sweep_plan(map: &Map, p: (f32, f32), heading: f32, cur_speed: f32, dir: f32, want: Want, t: &Tuning) -> Segment {
    let err = wrap(dir - heading);
    let base = road_pace(want.speed, road_share(map, p, dir), t);
    // Standing, a body turns on the spot (no arc) and sets off facing the way.
    let from_rest = cur_speed < base * 0.3;
    let mut seg = if want.agile || from_rest || err.abs() <= t.snap {
        Segment { heading: dir, speed: base, turn: 0.0, turn_s: 0.0, dur: want.max_dt, blocked: false }
    } else {
        let turn = t.turn_rate * err.signum();
        let turn_s = err.abs() / t.turn_rate;
        if err.abs() > t.sharp {
            // A sharp turn: slow arc until facing the way, then look again.
            let k = 1.0 - (1.0 - t.turn_slow) * smoothstep(0.6, 2.2, err.abs());
            Segment { heading, speed: base * k, turn, turn_s, dur: want.max_dt.min(turn_s), blocked: false }
        } else {
            // A bend: turn while walking on, then straight, in one segment.
            Segment { heading, speed: base, turn, turn_s, dur: want.max_dt, blocked: false }
        }
    };
    let (free, blocked) = sweep(map, p, &seg, t.clearance);
    seg.dur = free;
    seg.blocked = blocked;
    seg
}

/// A body's speed with the road under it: the road's bonus in proportion to the road ahead,
/// up to the top speed (`motion(a).top`); a body already faster on its own is not slowed.
pub fn road_pace(speed: f32, share: f32, t: &Tuning) -> f32 {
    let boosted = speed * (1.0 + (t.road_speed - 1.0) * share);
    if boosted > t.top { t.top.max(speed) } else { boosted }
}

/// Share of road on the ground just ahead (the next two tiles along `dir`): roads speed a
/// walker up in proportion, without a steering update at every road edge.
pub fn road_share(map: &Map, p: (f32, f32), dir: f32) -> f32 {
    let (c, s) = (dir.cos(), dir.sin());
    let n = (0..5).filter(|k| map.at(p.0 + c * 0.5 * *k as f32, p.1 + s * 0.5 * *k as f32) == Terrain::Road).count();
    n as f32 / 5.0
}

/// Sweep a segment across the map from `p`. Returns how long it may run (stopping just past
/// a chunk boundary, and before an obstacle) and whether an obstacle cut it short.
pub fn sweep(map: &Map, p: (f32, f32), seg: &Segment, clearance: f32) -> (f32, bool) {
    let dur = seg.dur;
    if seg.speed <= 0.0 || dur <= 0.0 {
        return (dur.max(0.0), false);
    }
    let step = 0.2 / seg.speed;
    let n = (dur / step).ceil().max(1.0) as u32;
    let chunk = chunk_of(p.0, p.1);
    let mut last_ok = 0.0f32;
    for k in 1..=n {
        let s = (k as f32 * step).min(dur);
        let (x, y, h) = seg.at(p, s);
        if !passable(map, (x, y), h, clearance) {
            return (last_ok, true);
        }
        if chunk_of(x, y) != chunk {
            return (s, false);
        }
        last_ok = s;
    }
    (dur, false)
}

// ---- flight --------------------------------------------------------------------------------
//
// A body running from something looks for open ground, as a person does. Straight away when that
// way is open as far as it still has to go; else it weighs the ground it can reach within sight
// (a small Dijkstra "flee map", as roguelikes' safety maps do) and makes for the spot that puts
// the most distance between it and the threat soonest, without running past the threat. It is
// the same for every flight (`flee`, `back_off`, a band backing off, an animal's flight) and
// reads only the ground within the body's sight.

/// The least room (m) a way out must gain: with no reachable spot within sight that much farther
/// from the threat, a flight is cornered.
pub const ROOM_M: f32 = 1.0;
/// The farthest (m) a flight weighs the ground round it, however far it sees.
pub const FLEE_REACH_M: f32 = 16.0;

/// How far a body can go straight along `h` from `p`, up to `max` metres (0.25 m steps, kept
/// `clearance` from obstacles as steering keeps it).
pub fn free_run(map: &Map, p: (f32, f32), h: f32, max: f32, clearance: f32) -> f32 {
    let (c, s) = (h.cos(), h.sin());
    let n = (max / 0.25).ceil().max(1.0) as u32;
    let mut ok = 0.0f32;
    for k in 1..=n {
        let d = (k as f32 * 0.25).min(max);
        if !passable(map, (p.0 + c * d, p.1 + s * d), h, clearance) {
            return ok;
        }
        ok = d;
    }
    max
}

/// The way a flight takes from `p`, running from `threat`, with `look` metres still to go and
/// `reach` the ground it sees (its sight). `heading` is the way it goes now.
///
/// Straight away when that is open for `look`. Otherwise every tile reachable within `reach`
/// (path length up to 1.5 × `reach`, steps between walkable tiles, a diagonal only past two open
/// sides as the route search takes it) is scored: its distance from the threat (counted only up to
/// `look` farther than now), less a quarter of the way there, less twice how much nearer the way
/// passes to the threat than the body is now; a little for keeping the way it goes. The body heads
/// for the farthest point of the way to the best tile that it can see in a straight line. `None`:
/// no reachable tile is [`ROOM_M`] farther from the threat (cornered).
pub fn flee_way(map: &Map, p: (f32, f32), threat: (f32, f32), heading: f32, look: f32, reach: f32, clearance: f32) -> Option<f32> {
    let d0 = (p.0 - threat.0).hypot(p.1 - threat.1);
    let away = if d0 < 1e-3 { heading } else { (p.1 - threat.1).atan2(p.0 - threat.0) };
    let look = look.max(ROOM_M * 2.0);
    if free_run(map, p, away, look, clearance) >= look {
        return Some(away);
    }
    let r = reach.clamp(2.0, FLEE_REACH_M).ceil() as i32;
    let side = 2 * r + 1;
    let (ox, oy) = (p.0.floor() as i32 - r, p.1.floor() as i32 - r);
    let idx = |x: i32, y: i32| -> Option<usize> {
        let (i, j) = (x - ox, y - oy);
        (i >= 0 && j >= 0 && i < side && j < side).then(|| (j * side + i) as usize)
    };
    let open = |x: i32, y: i32| map.free(x as f32 + 0.5, y as f32 + 0.5);
    let n = (side * side) as usize;
    // Cost so far in centimetres (integers, so the order is exact), parent, nearest approach.
    let mut g = vec![u32::MAX; n];
    let mut parent = vec![usize::MAX; n];
    let mut near = vec![f32::INFINITY; n];
    let (sx, sy) = (p.0.floor() as i32, p.1.floor() as i32);
    let start = idx(sx, sy)?;
    g[start] = 0;
    near[start] = d0;
    let limit = (reach.min(FLEE_REACH_M) * 150.0) as u32;
    let mut heap = std::collections::BinaryHeap::new();
    heap.push(std::cmp::Reverse((0u32, start)));
    let centre = |k: usize| ((ox + (k as i32 % side)) as f32 + 0.5, (oy + (k as i32 / side)) as f32 + 0.5);
    let mut best: Option<(f32, usize)> = None;
    while let Some(std::cmp::Reverse((cost, k))) = heap.pop() {
        if cost > g[k] {
            continue;
        }
        let (cx, cy) = centre(k);
        if k != start {
            let dt = (cx - threat.0).hypot(cy - threat.1);
            let gain = dt.min(d0 + look);
            let toward = (cy - p.1).atan2(cx - p.0);
            let score = gain - 0.25 * cost as f32 / 100.0 + 2.0 * (near[k] - d0).min(0.0) + 0.3 * wrap(toward - heading).cos();
            if dt >= d0 + ROOM_M && best.map_or(true, |(b, _)| score > b) {
                best = Some((score, k));
            }
        }
        let (x, y) = (cx.floor() as i32, cy.floor() as i32);
        for (dx, dy, step) in [(1, 0, 100u32), (-1, 0, 100), (0, 1, 100), (0, -1, 100), (1, 1, 141), (1, -1, 141), (-1, 1, 141), (-1, -1, 141)] {
            let (nx, ny) = (x + dx, y + dy);
            let Some(j) = idx(nx, ny) else { continue };
            if !open(nx, ny) || (dx != 0 && dy != 0 && !(open(x + dx, y) && open(x, y + dy))) {
                continue;
            }
            let c = cost + step;
            if c > limit || c >= g[j] {
                continue;
            }
            g[j] = c;
            parent[j] = k;
            let (jx, jy) = centre(j);
            near[j] = near[k].min((jx - threat.0).hypot(jy - threat.1));
            heap.push(std::cmp::Reverse((c, j)));
        }
    }
    let (_, goal) = best?;
    // The farthest point along the way that the body sees straight from where it stands.
    let mut k = goal;
    let mut aim = centre(goal);
    while k != start {
        let c = centre(k);
        if map.line_clear(p, c) {
            aim = c;
            break;
        }
        k = parent[k];
        aim = c;
    }
    Some((aim.1 - p.1).atan2(aim.0 - p.0))
}

// ---- movement intents ---------------------------------------------------------------------
//
// Ways for any controller to move relative to a creature it perceives: hold a range band from
// it (`keep_distance`), close in to a distance (`close_in`), go round it (`circle`), step back
// to a distance (`back_off`), keep beside it (`follow`). They choose only the way to go; the
// body goes there under the same steering, speeds, breath, terrain and facing as a player's
// keys. They are moves, not tactics: nothing here decides when to use one.

/// The intents and the arguments each reads.
pub const INTENTS: [&str; 5] = ["keep_distance", "close_in", "circle", "back_off", "follow"];

/// Longest distance an intent may name (metres): beyond anyone's sight.
pub const INTENT_MAX_M: f32 = 40.0;
/// Narrowest circle a body walks round something (metres).
pub const CIRCLE_MIN_M: f32 = 0.8;

/// The distances an intent names (`{"do": "keep_distance", "min": 3, "max": 6}`).
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Spacing {
    /// `keep_distance`: the near edge of the band.
    pub min: Option<f32>,
    /// `keep_distance`: the far edge of the band.
    pub max: Option<f32>,
    /// `circle`: how far from it to go round (none: as far as one is when it starts).
    pub radius: Option<f32>,
    /// `circle`: +1 to one's left as one faces it, -1 to one's right.
    pub side: Option<f32>,
    /// `close_in`, `follow`: how near to come; `back_off`: how far to get.
    pub distance: Option<f32>,
    /// `keep_distance`, `close_in`, `circle`: keep this far from others of one's own kind
    /// that one sees, while holding the intent (docs/PACK_MIND.md, A5). How far, never where.
    pub apart: Option<f32>,
}

/// The widest `apart` an intent may ask (m): beyond about one's sight it would not be seen.
pub const APART_MAX_M: f32 = 12.0;
/// The narrowest (m): steering already keeps bodies about this far apart.
pub const APART_MIN_M: f32 = 1.0;
/// The intents that take `apart`.
pub const APART_INTENTS: [&str; 3] = ["keep_distance", "close_in", "circle"];

/// The push away from seen others of one's kind (`mates`, positions) within `apart` m of `me`:
/// the sum of the unit ways from each to `me`, each weighted by how far inside `apart` it is
/// (1 touching, 0 at the edge). Zero when none is that near.
pub fn apart_push(me: (f32, f32), mates: &[(f32, f32)], apart: f32) -> (f32, f32) {
    let (mut x, mut y) = (0.0f32, 0.0f32);
    if apart <= 0.0 {
        return (x, y);
    }
    for q in mates {
        let (dx, dy) = (me.0 - q.0, me.1 - q.1);
        let d = dx.hypot(dy);
        if d >= apart {
            continue;
        }
        let w = 1.0 - d / apart;
        if d < 1e-3 {
            // On top of each other: a fixed way out, the same for both, so they part.
            x += w;
            continue;
        }
        x += dx / d * w;
        y += dy / d * w;
    }
    (x, y)
}

/// How strongly the push bends the way an intent takes (against the way's unit length).
pub const APART_WEIGHT: f32 = 1.5;

/// The way a body holding an intent round `at` takes with `apart` from its mates (`push`, from
/// [`apart_push`]): `way` (None: it stands, in its band) bent by the push; standing in its band,
/// along the band, to the side the push points (round `at`, never in or out of the band).
/// `None` when there is no push and it stands.
pub fn apart_way(me: (f32, f32), at: (f32, f32), way: Option<f32>, push: (f32, f32)) -> Option<f32> {
    let strength = push.0.hypot(push.1);
    if strength < 1e-3 {
        return way;
    }
    match way {
        Some(w) => Some((w.sin() + APART_WEIGHT * push.1).atan2(w.cos() + APART_WEIGHT * push.0)),
        None => {
            // Along the circle about `at` through `me`: the tangent the push leans to.
            let (dx, dy) = (me.0 - at.0, me.1 - at.1);
            let d = dx.hypot(dy);
            if d < 1e-3 {
                return Some(push.1.atan2(push.0));
            }
            let (tx, ty) = (-dy / d, dx / d);
            let along = push.0 * tx + push.1 * ty;
            // A push straight in or out (a mate directly behind or ahead): no side is nearer;
            // stay standing rather than leave the band.
            if along.abs() < 0.05 * strength {
                return None;
            }
            let s = along.signum();
            Some((s * ty).atan2(s * tx))
        }
    }
}

/// A side word: `left` (+1) or `right` (-1), as one faces what one circles.
pub fn side_of(word: &str) -> Option<f32> {
    match word.trim().to_lowercase().replace(['-', ' '], "_").as_str() {
        "left" | "l" | "counterclockwise" | "anticlockwise" | "counter_clockwise" | "ccw" => Some(1.0),
        "right" | "r" | "clockwise" | "cw" => Some(-1.0),
        _ => None,
    }
}

impl Spacing {
    /// Whether `skill`'s distances make sense: each a number from 0 to [`INTENT_MAX_M`], a band
    /// whose near edge is not beyond its far one, a circle no narrower than [`CIRCLE_MIN_M`]. The error says what to write instead.
    pub fn check(&self, skill: &str) -> Result<(), String> {
        for (k, v) in [("min", self.min), ("max", self.max), ("radius", self.radius), ("distance", self.distance)] {
            if let Some(v) = v {
                if !v.is_finite() || !(0.0..=INTENT_MAX_M).contains(&v) {
                    return Err(format!("{skill}: `{k}` is metres from 0 to {INTENT_MAX_M}"));
                }
            }
        }
        if let Some(a) = self.apart {
            if !APART_INTENTS.contains(&skill) {
                return Err(format!("{skill}: `apart` is for {} (keeping apart from your own kind while you hold it)", APART_INTENTS.join(", ")));
            }
            if !a.is_finite() || !(APART_MIN_M..=APART_MAX_M).contains(&a) {
                return Err(format!("{skill}: `apart` is metres from {APART_MIN_M} to {APART_MAX_M}"));
            }
        }
        match skill {
            "keep_distance" => match (self.min, self.max) {
                (Some(a), Some(b)) if a > b => Err(format!("keep_distance: `min` ({a}) is beyond `max` ({b})")),
                _ => Ok(()),
            },
            "circle" if self.radius.is_some_and(|r| r < CIRCLE_MIN_M) => Err(format!("circle: `radius` is at least {CIRCLE_MIN_M} m")),
            "back_off" if self.distance.is_some_and(|d| d <= 0.0) => Err("back_off: `distance` is how far from it to get, more than 0 m".into()),
            _ => Ok(()),
        }
    }

    /// The band `keep_distance` holds, `(near, far)`, starting `d` metres away: a missing edge
    /// is 0 or [`INTENT_MAX_M`]; with neither, the distance it starts at, a metre either way.
    pub fn band(&self, d: f32) -> (f32, f32) {
        if self.min.is_none() && self.max.is_none() {
            let d = d.clamp(0.0, INTENT_MAX_M);
            return ((d - 1.0).max(0.0), (d + 1.0).min(INTENT_MAX_M));
        }
        let near = self.min.unwrap_or(0.0);
        (near, self.max.unwrap_or(INTENT_MAX_M).max(near))
    }
}

/// How far inside a band a body that had to move goes before it stands again (metres): a
/// quarter of the band, at most half a metre, so a body at its edge does not stop and start.
pub fn band_margin(near: f32, far: f32) -> f32 {
    ((far - near) * 0.25).clamp(0.0, 0.5)
}

/// Where a body holding a band `[near, far]` from `at` goes: `None` to stand (it is in the
/// band), `Some((way, closing))` otherwise. `going` is how it moves now relative to `at`
/// (-1 backing off, +1 closing in, 0 standing): one that is moving carries on [`band_margin`]
/// into the band before it stands.
pub fn band_way(me: (f32, f32), at: (f32, f32), near: f32, far: f32, going: i8) -> Option<(f32, bool)> {
    let d = (at.0 - me.0).hypot(at.1 - me.1);
    let m = band_margin(near, far);
    let toward = (at.1 - me.1).atan2(at.0 - me.0);
    if d < near || (going < 0 && d < near + m) {
        return Some((if d < 1e-3 { 0.0 } else { wrap(toward + PI) }, false));
    }
    if d > far || (going > 0 && d > far - m) {
        return Some((toward, true));
    }
    None
}

/// The way round `at` at `radius` on `side` (+1 to one's left as one faces it): along the
/// circle, bent in when outside it and out when inside, up to straight in or out when more than
/// half the radius (at least a metre) off it.
pub fn orbit_way(me: (f32, f32), at: (f32, f32), radius: f32, side: f32) -> f32 {
    let (dx, dy) = (me.0 - at.0, me.1 - at.1);
    let d = dx.hypot(dy);
    let out = if d < 1e-3 { 0.0 } else { dy.atan2(dx) };
    // A positive angle is a turn to the left (`walk_face`): facing it (out + π), one's left is
    // out + π + π/2, the way round with the angle about it decreasing.
    let s = if side < 0.0 { 1.0 } else { -1.0 };
    let off = ((d - radius) / (radius * 0.5).max(1.0)).clamp(-1.0, 1.0) * (PI / 2.0);
    wrap(out + s * (PI / 2.0 + off))
}

/// How a body moves relative to `at`: -1 away, +1 toward, 0 standing or going round.
pub fn going(me: (f32, f32), v: (f32, f32), at: (f32, f32)) -> i8 {
    let s = v.0.hypot(v.1);
    if s < 1e-3 {
        return 0;
    }
    let (dx, dy) = (at.0 - me.0, at.1 - me.1);
    let d = dx.hypot(dy).max(1e-3);
    let c = (v.0 * dx + v.1 * dy) / (s * d);
    if c > 0.3 {
        1
    } else if c < -0.3 {
        -1
    } else {
        0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn open(w: u32, h: u32) -> Map {
        Map { w, h, tiles: vec![Terrain::Grass as u8; (w * h) as usize], blocked: Default::default(), opaque: Default::default(), nav: Default::default() }
    }

    #[test]
    fn arcs_are_continuous_and_keep_speed() {
        let (x, y, h) = arc(10.0, 10.0, 0.0, 2.0, 1.5, 1.0);
        // Chord length of an arc of radius 2/1.5 over 1.5 rad.
        let r = 2.0 / 1.5;
        let chord = 2.0 * r * (0.75f32).sin();
        assert!((((x - 10.0).powi(2) + (y - 10.0).powi(2)).sqrt() - chord).abs() < 1e-3);
        assert!((h - 1.5).abs() < 1e-6);
        // Two half steps equal one full step.
        let (x1, y1, h1) = arc(10.0, 10.0, 0.0, 2.0, 1.5, 0.5);
        let (x2, y2, _) = arc(x1, y1, h1, 2.0, 1.5, 0.5);
        assert!((x2 - x).abs() < 1e-4 && (y2 - y).abs() < 1e-4);
        // Straight when not turning.
        assert_eq!(pose(1.0, 1.0, 0.0, 3.0, 0.0, 0.0, 2.0), (7.0, 1.0, 0.0));
        // A turn then straight: continuous at the join, straight along the final heading.
        let (xa, ya, ha) = pose(0.0, 0.0, 0.0, 2.0, 2.0, 0.5, 0.5);
        let (xb, yb, hb) = pose(0.0, 0.0, 0.0, 2.0, 2.0, 0.5, 1.5);
        assert!((ha - 1.0).abs() < 1e-6 && (hb - 1.0).abs() < 1e-6);
        assert!((xb - (xa + 2.0 * 1f32.cos())).abs() < 1e-4 && (yb - (ya + 2.0 * 1f32.sin())).abs() < 1e-4);
    }

    #[test]
    fn turns_toward_the_wish_at_a_bounded_rate() {
        let m = open(64, 64);
        let t = Tuning::default();
        // A bend while walking: one segment, turn then straight, at full speed.
        let want = Want { dir: 0.8, speed: 2.6, agile: false, max_dt: 2.0 };
        let s = plan(&m, (20.0, 20.0), 0.0, 2.6, want, &t);
        assert!(s.turn > 0.0 && !s.blocked && (s.speed - 2.6).abs() < 1e-6);
        assert!((s.turn_s - 0.8 / t.turn_rate).abs() < 1e-4 && (s.dur - 2.0).abs() < 1e-6, "{s:?}");
        let (_, _, h) = s.at((20.0, 20.0), 1.0);
        assert!((h - 0.8).abs() < 1e-5, "faces the way after the turn");
        // A sharp turn slows and stops at alignment for another look.
        let want = Want { dir: PI / 2.0 + 0.6, speed: 2.6, agile: false, max_dt: 2.0 };
        let s = plan(&m, (20.0, 20.0), 0.0, 2.6, want, &t);
        assert!(s.speed < 2.6 && s.speed >= 2.6 * t.turn_slow - 1e-4, "slows for the turn: {s:?}");
        assert!((s.dur - s.turn_s).abs() < 1e-5);
        // Aligned: straight, full cruise, until the cadence.
        let want = Want { dir: PI / 2.0, speed: 2.6, agile: false, max_dt: 2.0 };
        let s = plan(&m, (20.0, 20.0), PI / 2.0 - 0.05, 2.6, want, &t);
        assert_eq!(s.turn, 0.0);
        assert!((s.heading - PI / 2.0).abs() < 1e-6 && (s.speed - 2.6).abs() < 1e-6);
        // From rest: turn on the spot and set off facing the way.
        let s = plan(&m, (20.0, 20.0), 0.0, 0.0, want, &t);
        assert!((s.speed - 2.6).abs() < 1e-6 && s.turn == 0.0 && (s.heading - PI / 2.0).abs() < 1e-6);
    }

    /// Walking under the keys with a look held off them: the travel is the keys' way at full
    /// speed (no bend, no sideways drift), and only the facing turns toward the look, at most
    /// the limit off the way (`look_walk_deg`, 75 shipped).
    #[test]
    fn a_held_look_turns_the_facing_and_not_the_walk() {
        let m = open(64, 64);
        let t = Tuning::default();
        let limit = 75f32.to_radians();
        let way = 0.0;
        for (look_deg, want_deg) in [(45.0f32, 45.0f32), (90.0, 75.0), (135.0, 75.0), (180.0, 75.0), (-90.0, -75.0), (-30.0, -30.0)] {
            let look = look_deg.to_radians();
            // The travel the authority asks for is the keys' way whatever the look.
            let s = plan(&m, (20.0, 20.5), way, 2.6, Want { dir: way, speed: 2.6, agile: false, max_dt: 1.0 }, &t);
            let (x, y, h) = s.at((20.0, 20.5), 1.0);
            assert!((s.speed - 2.6).abs() < 1e-6 && h.abs() < 1e-6, "look {look_deg}: {s:?}");
            assert!((x - 22.6).abs() < 1e-4 && (y - 20.5).abs() < 1e-6, "full speed along the keys, no drift: ({x},{y})");
            let off = walk_face(way, look, limit, 0.0);
            assert!((off.abs() - want_deg.abs().to_radians()).abs() < 1e-5 && off.signum() == want_deg.signum(), "look {look_deg}: facing {}", off.to_degrees());
            assert!((facing(h, off, 0.0, 0.0, 0.0) - want_deg.to_radians()).abs() < 1e-5);
        }
        // Looking straight back clamps to one side and keeps the shoulder it is over: a look
        // swung round past 180 degrees, or a way that wavers, does not swing it across the front.
        let back = walk_face(0.3, 0.3 + PI, limit, 0.0);
        assert!((back.abs() - limit).abs() < 1e-5);
        assert!((walk_face(0.0, PI, limit, -limit) + limit).abs() < 1e-6, "over the right shoulder, it stays there");
        assert!((walk_face(0.0, -PI + 0.1, limit, limit) - limit).abs() < 1e-6, "over the left, a look just past behind stays left");
        assert!((walk_face(0.0, 2.6, limit, -limit) - limit).abs() < 1e-6, "well round to the left (149 degrees), it turns left");
        // A limit of 180 lets the facing go all the way round; 0 keeps it on the way.
        assert!((walk_face(0.0, 2.5, PI, 0.0) - 2.5).abs() < 1e-6);
        assert_eq!(walk_face(0.0, 2.5, 0.0, 0.0), 0.0);
    }

    /// The facing turns toward its wanted offset at the body's turn rate on a segment of its
    /// own, then holds; a body facing its way (offset 0) faces its heading on any segment.
    #[test]
    fn the_facing_turns_at_the_turn_rate() {
        let rate = 6.0;
        let to = 75f32.to_radians();
        let (turn, turn_s) = face_turn(0.0, to, rate);
        assert_eq!(turn, rate);
        assert!((turn_s - to / rate).abs() < 1e-6);
        assert!((face_off(0.0, turn, turn_s, 0.1) - 0.6).abs() < 1e-6, "0.1 s at 6 rad/s");
        assert!((face_off(0.0, turn, turn_s, 5.0) - to).abs() < 1e-6, "then held");
        assert_eq!(face_off(0.0, turn, turn_s, -1.0), 0.0, "not before the segment");
        // Back toward the way when the look is let go.
        let (back, back_s) = face_turn(to, 0.0, rate);
        assert!(back < 0.0 && (face_off(to, back, back_s, back_s) - 0.0).abs() < 1e-6);
        assert_eq!(face_turn(0.4, 0.4, rate), (0.0, 0.0));
        // With no offset the facing is the travel heading along the segment, turn included.
        let (_, _, h) = pose(0.0, 0.0, 0.2, 2.6, 1.5, 0.4, 0.3);
        assert!((facing(h, 0.0, 0.0, 0.0, 0.3) - h).abs() < 1e-6);
    }

    /// Standing, a body turns to a look as it always did: the shortest turn of its heading
    /// when it faces its heading. One that faces part way round already (stopped from a walk
    /// with its head turned) finishes that way, its legs coming round after it.
    #[test]
    fn a_standing_turn_is_the_heading_s_shortest_turn() {
        for (h, want) in [(0.0f32, 1.0f32), (0.0, -2.0), (3.0, -3.0), (-2.5, 2.5), (1.0, 1.0)] {
            assert!((stand_turn(h, 0.0, want) - wrap(want - h)).abs() < 1e-6, "{h} -> {want}");
        }
        let off = 75f32.to_radians();
        assert!((stand_turn(0.0, off, PI) - PI).abs() < 1e-5, "the side the head already turned");
        assert!((stand_turn(0.0, off, (-170f32).to_radians()) - 190f32.to_radians()).abs() < 1e-5);
        assert!((stand_turn(0.0, -off, (-170f32).to_radians()) - (-170f32).to_radians()).abs() < 1e-5);
    }

    #[test]
    fn stops_short_of_walls_and_slides_along_them() {
        let mut m = open(64, 64);
        for y in 0..64 {
            m.set(30, y, Terrain::Wall);
        }
        let t = Tuning::default();
        let want = Want { dir: 0.0, speed: 2.0, agile: false, max_dt: 5.0 };
        let s = plan(&m, (25.0, 20.5), 0.0, 2.0, want, &t);
        assert!(s.blocked);
        let (x, _, _) = s.at((25.0, 20.5), s.dur);
        assert!(x < 30.0 - t.clearance + 0.01 && x > 29.0, "stops at the wall: {x}");
        // Pressing diagonally into the wall slides along it.
        let want = Want { dir: 0.6, speed: 2.0, agile: false, max_dt: 1.0 };
        let s = plan(&m, (29.6, 20.5), 0.6, 2.0, want, &t);
        let (x, y, _) = s.at((29.6, 20.5), s.dur);
        assert!(s.speed > 0.0 && x < 30.0 && y > 20.7, "slides: {s:?} -> ({x},{y})");
    }

    #[test]
    fn segments_end_at_chunk_boundaries_and_roads_speed_up() {
        let mut m = open(64, 64);
        let t = Tuning::default();
        let want = Want { dir: 0.0, speed: 2.0, agile: false, max_dt: 5.0 };
        let s = plan(&m, (14.0, 5.5), 0.0, 2.0, want, &t);
        let (x, _, _) = s.at((14.0, 5.5), s.dur);
        assert!(x >= 16.0 && x < 16.3, "just past the chunk edge: {x}");
        for x in 4..10 {
            m.set(x, 5, Terrain::Road);
        }
        let s = plan(&m, (5.0, 5.5), 0.0, 2.0, want, &t);
        assert!((s.speed - 2.0 * t.road_speed).abs() < 1e-5, "faster on road");
        // Leaving the road: in proportion to the road still ahead.
        let s = plan(&m, (8.8, 5.5), 0.0, 2.0, want, &t);
        assert!(s.speed > 2.0 && s.speed < 2.0 * t.road_speed, "{s:?}");
    }

    #[test]
    fn a_road_speeds_a_run_only_up_to_the_top_speed() {
        let t = Tuning { top: 5.5, ..Default::default() };
        // A walk (2.6) on a road: 3.64, under the top.
        assert!((road_pace(2.6, 1.0, &t) - 3.64).abs() < 1e-4);
        // A run of 4.5 m/s: 6.3 uncapped, 5.5 capped.
        assert_eq!(road_pace(4.5, 1.0, &t), 5.5);
        assert!((road_pace(4.5, 0.0, &t) - 4.5).abs() < 1e-6, "off road the run is its own");
        // Faster than the top on its own (a deer's flight, 6.8): not slowed by a road.
        assert_eq!(road_pace(6.8, 1.0, &t), 6.8);
        assert_eq!(road_pace(4.5, 1.0, &Tuning::default()), 4.5 * 1.4, "no top: no cap");
    }

    /// A band holds: out of it the way is straight out or straight in; in it, standing; a body
    /// already moving goes a margin into the band before it stands.
    #[test]
    fn a_band_backs_off_closes_in_and_holds() {
        let at = (10.0, 10.0);
        // 2 m away, band 3..6: straight away from it.
        let (way, closing) = band_way((8.0, 10.0), at, 3.0, 6.0, 0).unwrap();
        assert!(!closing && (wrap(way - PI)).abs() < 1e-5, "{way}");
        // 9 m away: straight at it.
        let (way, closing) = band_way((10.0, 1.0), at, 3.0, 6.0, 0).unwrap();
        assert!(closing && (way - PI / 2.0).abs() < 1e-5, "{way}");
        // In the band, standing: stay.
        assert_eq!(band_way((14.0, 10.0), at, 3.0, 6.0, 0), None);
        // Just inside the near edge while backing off: on to the margin (0.5 m), then stand.
        assert!(band_way((13.2, 10.0), at, 3.0, 6.0, -1).is_some());
        assert_eq!(band_way((13.6, 10.0), at, 3.0, 6.0, -1), None);
        // Just inside the far edge while closing: on to the margin, then stand.
        assert!(band_way((15.8, 10.0), at, 3.0, 6.0, 1).is_some());
        assert_eq!(band_way((15.4, 10.0), at, 3.0, 6.0, 1), None);
        // A band with no width holds at its edge: the margin is 0.
        assert_eq!(band_margin(4.0, 4.0), 0.0);
        assert_eq!(band_way((14.0, 10.0), at, 4.0, 4.0, 1), None);
        assert_eq!(band_margin(3.0, 4.0), 0.25);
    }

    /// Walking the way `orbit_way` gives keeps a body on its circle, on the side asked for.
    #[test]
    fn a_circle_keeps_its_radius_on_its_side() {
        let at = (0.0, 0.0);
        // On the circle, facing it from the east: left is south (the angle about it decreasing).
        assert!((orbit_way((4.0, 0.0), at, 4.0, 1.0) - (-PI / 2.0)).abs() < 1e-5);
        assert!((orbit_way((4.0, 0.0), at, 4.0, -1.0) - (PI / 2.0)).abs() < 1e-5);
        // Far outside: straight in; far inside: straight out.
        assert!((wrap(orbit_way((12.0, 0.0), at, 4.0, 1.0) - PI)).abs() < 1e-5);
        assert!(orbit_way((0.5, 0.0), at, 4.0, 1.0).abs() < 1e-5);
        // Stepping along it from off the circle, at a walk with a look every 0.25 s, the
        // distance comes to the radius and stays near it, going round the way asked.
        for (side, start) in [(1.0f32, (6.0f32, 0.0f32)), (-1.0, (2.5, 0.0))] {
            let mut p = start;
            let mut swept = 0.0f32;
            let mut last = p.1.atan2(p.0);
            let mut worst = 0.0f32;
            for k in 0..160 {
                let way = orbit_way(p, at, 4.0, side);
                p = (p.0 + way.cos() * 2.6 * 0.25, p.1 + way.sin() * 2.6 * 0.25);
                let a = p.1.atan2(p.0);
                swept += wrap(a - last);
                last = a;
                if k > 20 {
                    worst = worst.max((p.0.hypot(p.1) - 4.0).abs());
                }
            }
            assert!(worst < 0.6, "side {side}: off the circle by {worst}");
            assert!(swept * -side > 2.0 * TAU, "side {side}: went round {swept} rad");
        }
    }

    #[test]
    fn going_reads_toward_away_and_round() {
        assert_eq!(going((0.0, 0.0), (1.0, 0.0), (5.0, 0.0)), 1);
        assert_eq!(going((0.0, 0.0), (-1.0, 0.1), (5.0, 0.0)), -1);
        assert_eq!(going((0.0, 0.0), (0.0, 1.0), (5.0, 0.0)), 0);
        assert_eq!(going((0.0, 0.0), (0.0, 0.0), (5.0, 0.0)), 0);
    }

    #[test]
    fn spacing_is_checked_with_the_fix() {
        let band = |min, max| Spacing { min, max, ..Default::default() };
        assert!(band(Some(3.0), Some(6.0)).check("keep_distance").is_ok());
        assert!(band(None, Some(6.0)).check("keep_distance").is_ok());
        assert!(band(None, None).check("keep_distance").is_ok(), "the distance it starts at");
        assert_eq!(band(None, None).band(5.0), (4.0, 6.0));
        assert_eq!(band(None, None).band(0.5), (0.0, 1.5));
        assert!(band(Some(6.0), Some(3.0)).check("keep_distance").unwrap_err().contains("beyond `max`"));
        assert!(band(Some(-1.0), None).check("keep_distance").unwrap_err().contains("metres from 0 to 40"));
        assert!(band(Some(f32::NAN), None).check("keep_distance").is_err());
        assert_eq!(band(Some(3.0), None).band(9.0), (3.0, INTENT_MAX_M));
        assert_eq!(band(None, Some(6.0)).band(9.0), (0.0, 6.0));
        assert!(Spacing { radius: Some(0.3), ..Default::default() }.check("circle").unwrap_err().contains("at least 0.8"));
        assert!(Spacing::default().check("circle").is_ok(), "a circle at the distance one is");
        assert!(Spacing { distance: Some(0.0), ..Default::default() }.check("back_off").is_err());
        assert!(Spacing { distance: Some(60.0), ..Default::default() }.check("follow").is_err());
        assert!(Spacing { apart: Some(4.0), ..Default::default() }.check("keep_distance").is_ok());
        assert!(Spacing { apart: Some(4.0), ..Default::default() }.check("back_off").unwrap_err().contains("`apart` is for"));
        assert!(Spacing { apart: Some(0.5), ..Default::default() }.check("circle").unwrap_err().contains("from 1 to 12"));
        assert!(Spacing { apart: Some(f32::NAN), ..Default::default() }.check("close_in").is_err());
        assert_eq!((side_of("Left"), side_of("clockwise"), side_of("up")), (Some(1.0), Some(-1.0), None));
    }

    fn walled(w: u32, h: u32, walls: &[((u32, u32), (u32, u32))]) -> Map {
        let mut m = open(w, h);
        for &((x0, y0), (x1, y1)) in walls {
            for y in y0..=y1 {
                for x in x0..=x1 {
                    m.set(x as i32, y as i32, Terrain::Wall);
                }
            }
        }
        m
    }

    /// Runs a flight from `threat` with the body's own steering (`flee_way` then `plan`, a
    /// look every quarter second) until it is 9 m farther than it began; returns the distances.
    fn flight(m: &Map, from: (f32, f32), threat: (f32, f32)) -> Result<(f32, f32), String> {
        let c = Tuning::default().clearance;
        let t = Tuning::default();
        let (mut p, mut heading, mut speed) = (from, 0.0f32, 0.0f32);
        let start = (p.0 - threat.0).hypot(p.1 - threat.1);
        let mut last = start;
        for _ in 0..120 {
            let left = start + 9.0 - (p.0 - threat.0).hypot(p.1 - threat.1);
            if left <= 0.0 {
                break;
            }
            let dir = flee_way(m, p, threat, heading, left, 11.0, c).ok_or(format!("cornered at {p:?}"))?;
            let seg = plan(m, p, heading, speed, Want { dir, speed: 3.0, agile: false, max_dt: 0.25 }, &t);
            if seg.blocked && seg.speed == 0.0 {
                return Err(format!("stuck at {p:?}"));
            }
            let (x, y, h) = seg.at(p, seg.dur.min(0.25));
            (p, heading, speed) = ((x, y), h, seg.speed);
            let d = (p.0 - threat.0).hypot(p.1 - threat.1);
            if d < last - 0.8 {
                return Err(format!("closed on the threat: {last} -> {d} at {p:?}"));
            }
            last = last.max(d);
        }
        Ok((start, last))
    }

    /// In the open a flight runs straight away; against a wall it turns along it; out of an
    /// inside corner and past a dead-end pocket it takes the open side; boxed in it is cornered.
    #[test]
    fn a_flight_looks_for_open_ground() {
        let c = Tuning::default().clearance;
        let m = open(64, 64);
        let h = flee_way(&m, (32.0, 32.0), (32.0 - 5.0 * 0.3f32.cos(), 32.0 - 5.0 * 0.3f32.sin()), 0.3, 9.0, 11.0, c).unwrap();
        assert!((h - 0.3).abs() < 1e-4, "{h}");
        // A wall 3 m east across the whole way, the threat west: along the wall, and clear.
        let m = walled(64, 64, &[((35, 0), (35, 63))]);
        let h = flee_way(&m, (32.0, 32.0), (27.0, 32.0), 0.0, 9.0, 11.0, c).unwrap();
        assert!(h.abs() > 0.5, "turns along the wall: {h}");
        let (a, b) = flight(&m, (32.0, 32.0), (27.0, 32.0)).unwrap();
        assert!(b >= a + 8.0, "{a} -> {b}");
        // An inside corner (walls east and south, y grows south) with the threat west: out by the
        // open north side.
        let m = walled(64, 64, &[((36, 10), (36, 40)), ((10, 36), (36, 36))]);
        let (a, b) = flight(&m, (32.5, 33.0), (26.0, 33.0)).unwrap();
        assert!(b >= a + 8.0, "{a} -> {b}");
        // A dead-end pocket straight away (a channel 6 m deep, closed at its end), open ground
        // north and south of its mouth: the flight goes round it, not into it.
        let m = walled(64, 64, &[((31, 29), (38, 29)), ((31, 35), (38, 35)), ((38, 29), (38, 35))]);
        let (a, b) = flight(&m, (30.5, 32.5), (25.5, 32.5)).unwrap();
        assert!(b >= a + 8.0, "{a} -> {b}");
        // Keeps the way it goes when two are as good (a straight wall: north or south).
        let m = walled(64, 64, &[((35, 0), (35, 63))]);
        let north = flee_way(&m, (32.5, 32.5), (27.5, 32.5), -PI / 2.0, 9.0, 11.0, c).unwrap();
        let south = flee_way(&m, (32.5, 32.5), (27.5, 32.5), PI / 2.0, 9.0, 11.0, c).unwrap();
        assert!(north < 0.0 && south > 0.0, "{north} {south}");
        // Boxed in: nowhere farther from the threat.
        let m = walled(64, 64, &[((31, 31), (33, 31)), ((31, 33), (33, 33)), ((31, 31), (31, 33)), ((33, 31), (33, 33))]);
        assert_eq!(flee_way(&m, (32.5, 32.5), (30.0, 32.5), 0.0, 9.0, 11.0, c), None);
    }
}

#[cfg(test)]
mod apart_tests {
    use super::*;

    #[test]
    fn the_push_is_away_from_mates_inside_apart_only() {
        let p = apart_push((0.0, 0.0), &[(2.0, 0.0), (10.0, 0.0)], 4.0);
        assert!(p.0 < -0.4 && p.1.abs() < 1e-6, "{p:?}");
        assert_eq!(apart_push((0.0, 0.0), &[(5.0, 0.0)], 4.0), (0.0, 0.0));
        assert_eq!(apart_push((0.0, 0.0), &[(1.0, 0.0)], 0.0), (0.0, 0.0));
    }

    #[test]
    fn standing_in_the_band_a_mate_moves_one_round_the_target_not_in_or_out() {
        // Target at the origin; me 4 m east; a mate 1.5 m north of me (also about 4 m out).
        let me = (4.0, 0.0);
        let push = apart_push(me, &[(3.7, -1.5)], 4.0);
        let w = apart_way(me, (0.0, 0.0), None, push).expect("moves");
        // Round the circle: tangent at (4, 0) is ±y; away from the mate at -y is +y (south).
        assert!((w - std::f32::consts::FRAC_PI_2).abs() < 0.05, "{w}");
        // A mate straight behind (farther out on the same ray): no side, stays.
        let push = apart_push(me, &[(6.0, 0.0)], 4.0);
        assert_eq!(apart_way(me, (0.0, 0.0), None, push), None);
    }

    #[test]
    fn moving_the_way_is_bent_away_from_the_mate() {
        let me = (0.0, 0.0);
        let push = apart_push(me, &[(0.0, 1.0)], 4.0);
        // Going east with a mate just south (+y): bent north (negative angle).
        let w = apart_way(me, (10.0, 0.0), Some(0.0), push).unwrap();
        assert!(w < -0.3, "{w}");
        // No mate near: the way is unchanged.
        assert_eq!(apart_way(me, (10.0, 0.0), Some(0.0), (0.0, 0.0)), Some(0.0));
    }

    /// Four bodies start bunched on one side of a target at the origin and each, every step,
    /// holds 3-5 m from it and keeps `apart` m from the others: Muro et al.'s two rules with
    /// this module's geometry, stepping 0.2 m. Returns the coverage they end at (degrees).
    fn spread_round(apart: f32) -> f32 {
        let mut p: Vec<(f32, f32)> = vec![(-4.0, 0.0), (-4.0, 0.6), (-4.2, -0.5), (-3.8, 0.3)];
        for _ in 0..600 {
            let snapshot = p.clone();
            for i in 0..p.len() {
                let mates: Vec<(f32, f32)> = snapshot.iter().enumerate().filter(|(j, _)| *j != i).map(|(_, q)| *q).collect();
                let way = band_way(p[i], (0.0, 0.0), 3.0, 5.0, 0).map(|(w, _)| w);
                let push = apart_push(p[i], &mates, apart);
                if let Some(w) = apart_way(p[i], (0.0, 0.0), way, push) {
                    p[i] = (p[i].0 + 0.2 * w.cos(), p[i].1 + 0.2 * w.sin());
                }
            }
        }
        let mut b: Vec<f32> = p.iter().map(|q| q.1.atan2(q.0).rem_euclid(2.0 * PI)).collect();
        b.sort_by(|x, y| x.partial_cmp(y).unwrap());
        let gaps: Vec<f32> = (0..b.len()).map(|i| if i + 1 < b.len() { b[i + 1] - b[i] } else { b[0] + 2.0 * PI - b[i] }).collect();
        for q in &p {
            let d = q.0.hypot(q.1);
            assert!((2.5..=5.5).contains(&d), "{d}");
        }
        (2.0 * PI - gaps.iter().cloned().fold(0.0, f32::max)).to_degrees()
    }

    #[test]
    fn mates_who_each_follow_the_rule_spread_round_a_standing_target() {
        // 4 m apart on a circle of about 4 m is about 60° between neighbours: four span about
        // 180° (from bunched within 1 m: under 20°). Wider apart, wider round.
        let c4 = spread_round(4.0);
        assert!(c4 >= 170.0, "{c4}");
        let c6 = spread_round(6.0);
        assert!(c6 >= 240.0 && c6 > c4, "{c6} {c4}");
    }
}

#[cfg(test)]
mod reversal_tests {
    use super::*;

    mod drive {
        pub use crate::map::Map;
        pub use crate::steer as geo;
        include!("steer_drive.rs");
    }
    use drive::{jumps, replay, Input, Laws};

    const RATE: f32 = 6.0;

    /// Three moments of a play-test (2026-11-12, 22:00:44, 22:04:12 and 22:05:51) where the walk
    /// keys reversed and turned sharply with the look held far aside: only the movement keys
    /// and the looks, as (ms from the first, `M` walk / `R` run / `L` look, direction in degrees
    /// with +y south, None to stop or let go).
    const PLAYTEST: [&[(u64, u8, Option<f32>)]; 3] = [
        &[(0, b'M', Some(112.5)), (1759, b'M', None), (1767, b'M', Some(22.5)), (2260, b'L', Some(-79.5)), (2758, b'M', None), (3258, b'M', Some(-157.5)), (3336, b'L', Some(-75.4)), (3460, b'M', None), (3525, b'M', Some(22.5)), (4259, b'L', Some(-79.4)), (4317, b'M', None), (4633, b'M', Some(-157.5)), (4759, b'L', Some(-75.1)), (4951, b'M', Some(-112.5)), (5576, b'L', Some(-80.1)), (5683, b'L', Some(-101.2)), (5927, b'M', Some(-157.5)), (5975, b'M', None), (6117, b'L', Some(-105.5)), (6259, b'L', Some(-109.7)), (6542, b'L', Some(-113.8)), (6643, b'L', Some(-124.3))],
        &[(0, b'M', Some(157.5)), (343, b'M', None), (468, b'L', Some(146.9)), (574, b'L', Some(137.5)), (675, b'L', Some(129.2)), (701, b'M', Some(-22.5)), (774, b'L', Some(121.5)), (892, b'L', Some(90.6)), (993, b'L', Some(20.8)), (1099, b'L', Some(8.8)), (1725, b'M', Some(22.5)), (1799, b'L', Some(4.5)), (1849, b'M', Some(-22.5)), (1899, b'L', Some(-8.2)), (2018, b'L', Some(-2.0)), (2117, b'M', None), (2124, b'L', Some(3.8)), (2458, b'L', Some(-0.6)), (2683, b'L', Some(-4.6)), (2751, b'M', Some(67.5)), (2792, b'L', Some(-10.1)), (2866, b'M', None), (2891, b'L', Some(-21.4)), (3076, b'L', Some(-26.2)), (3150, b'L', None), (3250, b'L', Some(140.6)), (3366, b'L', Some(112.3)), (3483, b'L', Some(95.4)), (3584, b'L', Some(86.3)), (3690, b'L', Some(80.0)), (3800, b'L', Some(75.7)), (3923, b'M', Some(-112.5)), (3957, b'M', Some(-67.5)), (4017, b'L', Some(80.9)), (4118, b'L', Some(101.2)), (4249, b'L', Some(108.0)), (4317, b'M', None), (4350, b'L', Some(114.7)), (4516, b'L', Some(120.8)), (4634, b'L', Some(129.8)), (4734, b'L', Some(134.2)), (4940, b'L', Some(139.0)), (5040, b'L', Some(153.8)), (5142, b'L', Some(167.5))],
        &[(0, b'M', Some(180.0)), (42, b'L', Some(107.4)), (192, b'L', Some(103.0)), (299, b'L', Some(90.9)), (400, b'L', Some(86.1)), (475, b'M', Some(157.5)), (699, b'L', Some(81.6)), (816, b'L', Some(73.0)), (924, b'L', Some(67.9)), (949, b'M', Some(135.0)), (1400, b'L', Some(63.1)), (1500, b'L', Some(56.7)), (1608, b'L', Some(51.7)), (1625, b'M', Some(112.5)), (2266, b'L', Some(47.7)), (2549, b'L', Some(43.4)), (2625, b'M', None), (3115, b'L', Some(47.4)), (3175, b'M', Some(-90.0)), (3257, b'L', Some(51.4)), (3449, b'M', None), (4083, b'M', Some(90.0)), (4124, b'L', Some(47.3)), (4240, b'L', Some(43.2)), (4299, b'M', None), (4749, b'L', Some(47.2)), (4807, b'M', Some(-90.0)), (4899, b'L', Some(51.7)), (5132, b'M', Some(-45.0)), (5265, b'L', Some(55.9)), (5686, b'L', Some(60.2)), (5783, b'M', Some(0.0)), (5982, b'R', Some(0.0)), (6015, b'L', Some(64.4)), (6115, b'L', Some(70.6)), (6191, b'R', Some(-45.0)), (6215, b'L', Some(76.4)), (6332, b'L', Some(82.0)), (6619, b'L', Some(87.2))],
    ];

    fn inputs(seq: &[(u64, u8, Option<f32>)]) -> Vec<(u64, Input)> {
        let dir = |a: Option<f32>| a.map(|d: f32| (d.to_radians().cos(), d.to_radians().sin()));
        seq.iter()
            .map(|(t, k, a)| {
                let i = match k {
                    b'L' => Input::Look { dir: dir(*a) },
                    _ => Input::Move { dir: dir(*a), run: *k == b'R' },
                };
                (10_000 + t, i)
            })
            .collect()
    }

    /// The walk keys reversing and turning sharply with the look held aside (a play-test's
    /// worst moments, replayed through steering as the authority drives it): the facing never
    /// turns faster than the turn rate in the world, so it never jumps, and once the facing has
    /// had time to come round it is within the `look_walk_deg` law of the travel while the body
    /// moves.
    #[test]
    fn the_facing_never_jumps_when_the_walk_reverses() {
        let laws = Laws::default();
        for (k, seq) in PLAYTEST.iter().enumerate() {
            let inp = inputs(seq);
            let heading = seq[0].2.unwrap().to_radians();
            let (from, to) = (inp[0].0, inp.last().unwrap().0 + 2000);
            let (track, d) = replay(laws, heading, &inp, from, to, 10);
            if std::env::var("FACE_DEBUG").is_ok() {
                for (t, r) in &d.rows {
                    eprintln!("row {} {:?}", t - from, r);
                }
            }
            // A steering update runs at the first tick after it falls due and starts where the
            // last segment ended (`motion::resume_at`), so a sample may take in one tick (1/60 s)
            // of turning it had not seen yet.
            for w in track.windows(2) {
                let d = wrap(w[1].1 - w[0].1).abs();
                assert!(d <= RATE * (0.010 + 1.0 / 60.0) + 1e-3, "moment {k}: the facing turned {:.1} degrees in 10 ms at {} ms", d.to_degrees(), w[1].0 - from);
            }
            let (worst, n) = jumps(&track, 250, 90f32.to_radians());
            assert!(n == 0 && worst <= RATE * 0.25 + 0.01, "moment {k}: {:.0} degrees in 0.25 s, {n} jumps over 90", worst.to_degrees());
            // Settled: from π / rate after each change of the keys (the longest the facing and
            // the travel's own turn take) until the next, within the law of the travel.
            let settle = (PI / RATE * 1000.0) as u64 + 50;
            for (i, (t, input)) in inp.iter().enumerate() {
                if !matches!(input, Input::Move { dir: Some(_), .. }) {
                    continue;
                }
                let next = inp[i + 1..].iter().find(|(_, j)| matches!(j, Input::Move { .. })).map_or(to, |x| x.0);
                for s in track.iter().filter(|s| s.0 >= t + settle && s.0 < next) {
                    if let Some(tr) = s.2 {
                        let off = wrap(s.1 - tr).abs();
                        assert!(off <= laws.limit + 0.01, "moment {k}: {:.0} degrees off the travel {} ms after the keys changed", off.to_degrees(), s.0 - t);
                    }
                }
            }
        }
    }

    fn world(heading: f32, turn: f32, turn_s: f32, f: FaceSeg, t: f32) -> f32 {
        let (_, _, h) = pose(0.0, 0.0, heading, 0.0, turn, turn_s, t);
        facing(h, f.off, f.turn, f.turn_s, t)
    }

    /// The facing segment itself: from where the body faces, on at the turn rate at most, the
    /// short way, toward the look's side; over a travel's own turn, evenly across it.
    #[test]
    fn a_reversal_turns_the_facing_on_from_where_it_was() {
        let (limit, look) = (75f32.to_radians(), 47f32.to_radians());
        let settled = (-15f32).to_radians();
        // From rest: the travel is set to -90 at once (from +90), the facing at the look.
        let f = walk_facing(look, -PI / 2.0, 0.0, 0.0, Some(look), limit, RATE);
        assert!((world(-PI / 2.0, 0.0, 0.0, f, 0.0) - look).abs() < 1e-5, "no jump: {f:?}");
        assert!((f.turn + RATE).abs() < 1e-5 && f.due_s.is_none(), "{f:?}");
        assert!((world(-PI / 2.0, 0.0, 0.0, f, 1.0) - settled).abs() < 1e-4);
        // Moving: the travel turns from +90 through 180 to -90 (away from the look); the facing
        // goes the short way through the look's side, evenly over that turn, and arrives with it.
        let th = PI / RATE;
        let f = walk_facing(look, PI / 2.0, RATE, th, Some(look), limit, RATE);
        assert!(f.due_s.is_none(), "{f:?}");
        let mut last = look;
        for i in 1..=100 {
            let t = th * i as f32 / 100.0;
            let w = world(PI / 2.0, RATE, th, f, t);
            assert!(wrap(w - last).abs() <= RATE * th / 100.0 + 1e-4, "at {t}: {last} -> {w}");
            assert!(wrap(w - look).abs() <= 62f32.to_radians() + 1e-3, "it stays on the look's side: {}", w.to_degrees());
            last = w;
        }
        assert!(wrap(last - settled).abs() < 1e-3, "{}", last.to_degrees());
        assert!((world(PI / 2.0, RATE, th, f, 2.0) - settled).abs() < 1e-3, "then held");
        // A bend the facing has further to go than: it turns with the travel at the turn rate
        // and asks steering to look again at the end of the bend.
        let bend = 45f32.to_radians();
        let f = walk_facing(-60f32.to_radians(), 0.0, RATE, bend / RATE, None, limit, RATE);
        assert_eq!((f.turn, f.due_s), (0.0, Some(bend / RATE)), "{f:?}");
        // The look held still through a bend: the facing stays put as the travel turns under it.
        let f = walk_facing(0.3, 0.0, RATE, bend / RATE, Some(0.3), limit, RATE);
        assert!((f.turn + RATE).abs() < 1e-5 && (world(0.0, RATE, bend / RATE, f, bend / RATE) - 0.3).abs() < 1e-4, "{f:?}");
    }

    /// Standing, the legs and the facing arrive together and the facing never turns faster than
    /// the turn rate, even when it has further to go than the legs.
    #[test]
    fn a_standing_turn_keeps_the_facing_within_the_rate() {
        let off = 75f32.to_radians();
        let want = (-25f32).to_radians();
        let ((legs, legs_s), f) = stand_facing(0.0, off, want, RATE, 0.05).unwrap();
        assert!((legs_s - 100f32.to_radians() / RATE).abs() < 1e-4 && legs.abs() <= RATE, "{legs} for {legs_s}");
        let at = |t: f32| facing(legs * t.min(legs_s), f.off, f.turn, f.turn_s, t);
        for i in 1..=50 {
            let t = legs_s * i as f32 / 50.0;
            assert!(wrap(at(t) - at(t - legs_s / 50.0)).abs() <= RATE * legs_s / 50.0 + 1e-4);
        }
        assert!(wrap(at(legs_s) - want).abs() < 1e-4);
    }
}
