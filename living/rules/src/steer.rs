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
// held. The offset is not wrapped; the authority keeps it within the `look_walk_deg` law while
// the body moves. A body with no held look has offset 0 and faces its heading. The authority
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
}

impl Default for Tuning {
    fn default() -> Self {
        Self { turn_rate: 6.0, snap: 0.12, sharp: 1.1, turn_slow: 0.4, clearance: 0.25, road_speed: 1.4 }
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
    let base = want.speed * (1.0 + (t.road_speed - 1.0) * road_share(map, p, dir));
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
}
