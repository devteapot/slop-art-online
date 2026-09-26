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
        Map { w, h, tiles: vec![Terrain::Grass as u8; (w * h) as usize], blocked: Default::default() }
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
