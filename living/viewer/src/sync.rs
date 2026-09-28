//! Smooth display of analytic body segments.
//!
//! Bodies are segments that start at the authority's time `t_ms` (see
//! `living_rules::steer::pose`), so where a body is drawn depends on which instant of the
//! authority's clock the viewer shows. Using the local wall clock directly makes bodies
//! stop at the end of every segment until the next row arrives and then jump ahead by the
//! delivery delay, and any offset between the two clocks (another device, a tunnel)
//! multiplies that at every update.
//!
//! [`ServerClock`] instead shows the authority's time a little in the past: its offset from a
//! local monotonic clock is estimated from the rows themselves (a row written at `t_ms`
//! cannot arrive before `t_ms`), set so that almost every row has arrived before the display
//! reaches it, and slewed gently (the display clock never steps except to resynchronize).
//! [`Tracks`] keeps each body's segments in time order and switches to a new one when the
//! display clock reaches its start, so continuous authority motion is drawn continuously; a
//! row that still arrives late is blended in over about 100 ms instead of snapping, while a
//! real jump (a teleport) is shown as one.

use bevy::platform::time::Instant;
use bevy_egui::egui;
use living_bindings::Body;
use std::collections::{HashMap, VecDeque};

/// How far back row arrival delays are remembered.
const WINDOW_MS: f64 = 4_000.0;
/// Share of the most delayed arrivals in the window that may still arrive late.
const LATE_SHARE: f64 = 0.02;
/// Extra delay beyond the estimate (ms).
const MARGIN_MS: f64 = 4.0;
/// Most the display clock may run fast or slow while adjusting (fraction of real time).
const SLEW: f64 = 0.1;
/// Offsets further than this from the estimate are resynchronized at once (ms).
const RESYNC_MS: f64 = 1_000.0;
/// Delay assumed before the first row arrives (ms).
const DEFAULT_DELAY_MS: f64 = 100.0;

/// The authority's clock as displayed: `local monotonic ms + offset`.
pub struct ServerClock {
    start: Instant,
    off: f64,
    synced: bool,
    last: f64,
    /// (local ms, row `t_ms` minus local ms at arrival).
    lags: VecDeque<(f64, f64)>,
    scratch: Vec<f64>,
}

impl Default for ServerClock {
    fn default() -> Self {
        let start = Instant::now();
        Self { start, off: crate::clock::now_ms() as f64 - DEFAULT_DELAY_MS, synced: false, last: 0.0, lags: VecDeque::new(), scratch: Vec::new() }
    }
}

impl ServerClock {
    fn local(&self) -> f64 {
        self.start.elapsed().as_secs_f64() * 1000.0
    }

    /// Advance the display clock for a frame. `latest_t` is the latest `t_ms` among body rows
    /// updated since the previous frame (0 when none). Returns the displayed authority time (ms).
    pub fn frame(&mut self, latest_t: u64) -> f64 {
        let now = self.local();
        let dt = (now - self.last).max(0.0);
        self.last = now;
        if latest_t > 0 {
            self.lags.push_back((now, latest_t as f64 - now));
        }
        while self.lags.front().is_some_and(|(t, _)| now - t > WINDOW_MS) {
            self.lags.pop_front();
        }
        if !self.lags.is_empty() {
            self.scratch.clear();
            self.scratch.extend(self.lags.iter().map(|(_, l)| *l));
            let k = ((self.scratch.len() as f64 * LATE_SHARE) as usize).min(self.scratch.len() - 1);
            let (_, low, _) = self.scratch.select_nth_unstable_by(k, |a, b| a.total_cmp(b));
            let target = *low - MARGIN_MS;
            let gap = target - self.off;
            if !self.synced || gap.abs() > RESYNC_MS {
                self.off = target;
                self.synced = true;
            } else {
                self.off += gap.clamp(-SLEW * dt, SLEW * dt);
            }
        }
        now + self.off
    }

    /// How far behind the newest rows the display runs (ms), for diagnostics.
    pub fn delay_ms(&self) -> f64 {
        self.lags.back().map_or(0.0, |(t, l)| (t + l) - (t + self.off))
    }
}

/// The motion part of a body row: one analytic segment.
#[derive(Clone, Copy, PartialEq, Debug)]
pub struct Seg {
    pub x: f32,
    pub y: f32,
    pub t_ms: u64,
    pub vx: f32,
    pub vy: f32,
    pub heading: f32,
    pub turn: f32,
    pub turn_s: f32,
    pub next_ms: u64,
}

impl Seg {
    pub fn of(b: &Body) -> Self {
        Self { x: b.x, y: b.y, t_ms: b.t_ms, vx: b.vx, vy: b.vy, heading: b.heading, turn: b.turn, turn_s: b.turn_s, next_ms: b.next_ms }
    }

    /// Seconds into the segment at `now` (ms), held at `next_ms` until the next segment.
    fn dt(&self, now: f64) -> f32 {
        ((now.min(self.next_ms as f64) - self.t_ms as f64).max(0.0) / 1000.0) as f32
    }

    /// Where the body is at `now` (see `living_rules::steer::pose`).
    pub fn pos(&self, now: f64) -> egui::Pos2 {
        let dt = self.dt(now);
        if self.turn == 0.0 || self.turn_s <= 0.0 {
            return egui::pos2(self.x + self.vx * dt, self.y + self.vy * dt);
        }
        let (x, y, _) = living_rules::steer::pose(self.x, self.y, self.heading, self.vx.hypot(self.vy), self.turn, self.turn_s, dt);
        egui::pos2(x, y)
    }

    /// Direction of travel at `now`, when moving.
    pub fn heading(&self, now: f64) -> Option<f32> {
        if (self.vx == 0.0 && self.vy == 0.0) || self.next_ms as f64 <= now {
            return None;
        }
        Some(if self.turn == 0.0 { self.vy.atan2(self.vx) } else { self.heading + self.turn * self.dt(now).min(self.turn_s) })
    }
}

/// Corrections longer than this are shown as jumps, not blended (tiles).
const BLEND_MAX: f32 = 2.0;
/// Time constant of a blended correction (s): about 95% gone after 120 ms.
const BLEND_TAU: f32 = 0.04;
/// Future segments kept per body.
const QUEUE: usize = 8;

struct Track {
    /// The segment in effect at the display time.
    cur: Seg,
    /// Segments starting after the display time, in order.
    queue: VecDeque<Seg>,
    /// The latest row seen (to notice a new one).
    seen: Seg,
    /// Offset still being blended out (tiles).
    corr: egui::Vec2,
}

impl Track {
    /// Put `seg` in effect, keeping the drawn position continuous: whatever separates the two
    /// segments at `at` becomes a correction blended out over the next frames. `at` is the
    /// new segment's start when it was queued in time (so only a discontinuity in the
    /// authority's own motion is blended), or the display time for a row that came late.
    fn switch(&mut self, seg: Seg, at: f64) {
        let before = self.cur.pos(at) + self.corr;
        self.cur = seg;
        let c = before - seg.pos(at);
        self.corr = if c.length() > BLEND_MAX || !c.x.is_finite() || !c.y.is_finite() { egui::Vec2::ZERO } else { c };
    }
}

/// Per-body display segments.
#[derive(Default)]
pub struct Tracks {
    tracks: HashMap<u32, Track>,
}

impl Tracks {
    /// Take in the current rows and return each body's displayed position and direction of
    /// travel at `now`; `dt` is the frame time (s).
    pub fn update<'a>(&mut self, bodies: impl Iterator<Item = &'a Body>, now: f64, dt: f32, mut out: impl FnMut(u32, egui::Pos2, Option<f32>)) {
        let decay = (-dt.max(0.0) / BLEND_TAU).exp();
        for b in bodies {
            let seg = Seg::of(b);
            let tr = self.tracks.entry(b.id).or_insert(Track { cur: seg, queue: VecDeque::new(), seen: seg, corr: egui::Vec2::ZERO });
            if seg != tr.seen {
                tr.seen = seg;
                if seg.t_ms as f64 > now {
                    // Starts later than shown: switch when the display reaches it.
                    while tr.queue.back().is_some_and(|q| q.t_ms >= seg.t_ms) {
                        tr.queue.pop_back();
                    }
                    if tr.queue.len() >= QUEUE {
                        tr.queue.pop_front();
                    }
                    tr.queue.push_back(seg);
                } else {
                    tr.queue.clear();
                    tr.switch(seg, now);
                }
            }
            while let Some(q) = tr.queue.front().copied().filter(|q| q.t_ms as f64 <= now) {
                tr.queue.pop_front();
                tr.switch(q, q.t_ms as f64);
            }
            tr.corr *= decay;
            if tr.corr.length_sq() < 1e-8 {
                tr.corr = egui::Vec2::ZERO;
            }
            out(b.id, tr.cur.pos(now) + tr.corr, tr.cur.heading(now));
        }
    }

    /// Forget bodies that are gone.
    pub fn retain(&mut self, keep: impl Fn(u32) -> bool) {
        self.tracks.retain(|id, _| keep(*id));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn body(x: f32, t_ms: u64, vx: f32, next_ms: u64) -> Body {
        Body { id: 1, kind: "person".into(), x, y: 0.0, t_ms, vx, vy: 0.0, path: Vec::new(), speed: vx, chunk: 0, next_ms, heading: 0.0, turn: 0.0, turn_s: 0.0 }
    }

    fn shown(tracks: &mut Tracks, b: &Body, now: f64, dt: f32) -> f32 {
        let mut x = f32::NAN;
        tracks.update(std::iter::once(b), now, dt, |_, p, _| x = p.x);
        x
    }

    #[test]
    fn a_row_received_ahead_of_the_display_takes_over_seamlessly() {
        let mut t = Tracks::default();
        let a = body(0.0, 1_000, 2.0, 1_500);
        assert_eq!(shown(&mut t, &a, 1_100.0, 0.01), 0.2);
        // The next segment (continuing from where `a` ends, 20 ms after it) arrives early.
        let b = body(1.0, 1_500, 2.0, 2_000);
        assert!((shown(&mut t, &b, 1_400.0, 0.1) - 0.8).abs() < 1e-5, "still on the first segment");
        // Frames straddling the switch move at the segment speed, with nothing to blend.
        assert!((shown(&mut t, &b, 1_504.0, 0.104) - 1.008).abs() < 1e-5);
        assert!((shown(&mut t, &b, 1_512.0, 0.008) - 1.024).abs() < 1e-5);
    }

    #[test]
    fn a_late_row_is_blended_and_a_jump_is_shown() {
        let mut t = Tracks::default();
        let a = body(0.0, 1_000, 2.0, 1_500);
        shown(&mut t, &a, 1_490.0, 0.01);
        // Arrives when the display is already 30 ms past its start: held at 1.0, not snapped to 1.06.
        let b = body(1.0, 1_500, 2.0, 2_000);
        let x = shown(&mut t, &b, 1_530.0, 0.0);
        assert!((x - 1.0).abs() < 1e-5, "{x}");
        // ... and caught up within ~120 ms.
        let mut now = 1_530.0;
        let mut x = 0.0;
        for _ in 0..15 {
            now += 8.0;
            x = shown(&mut t, &b, now, 0.008);
        }
        let truth = 1.0 + 2.0 * (now as f32 - 1_500.0) / 1000.0;
        assert!((x - truth).abs() < 0.004, "{x} vs {truth}");
        // A teleport is shown as one.
        let c = body(20.0, 1_700, 0.0, u64::MAX);
        assert_eq!(shown(&mut t, &c, 1_710.0, 0.008), 20.0);
    }

    #[test]
    fn the_display_clock_follows_row_times_without_stepping() {
        let mut c = ServerClock::default();
        let local = c.local();
        // Rows stamped 5 s ahead of this machine's clock (another device's clock).
        let t0 = c.frame((local + 5_000.0) as u64);
        assert!((t0 - (local + 5_000.0)).abs() < 50.0, "synchronized at once: {t0} vs {}", local + 5_000.0);
        let t1 = c.frame(0);
        assert!(t1 >= t0);
    }
}
