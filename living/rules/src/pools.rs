//! Short pools: breath (`stamina`) and the non-bodily pool (`focus`), beside tiredness
//! (`energy`, the needs). docs/STAMINA_PROPOSAL.md §2 and docs/STAMINA.md.
//!
//! A pool is kept as a value anchored at the vitals row's `at_ms` with a signed rate per real
//! second that applies from `from_ms` (never before the anchor): while a run or a guard drains
//! it, the rate is negative and `from_ms` is the anchor; after a spend, the rate is the refill and
//! `from_ms` is the spend plus the pool's delay. So the row is written only when a drain starts or
//! stops or something is spent, never per tick, and a client animates the refill from the row.
//! The numbers come from the `pools(a)` law (kept per state, like `motion`); the engine finishes
//! the cap and the refill for the body's tiredness here.

/// One pool's law, as `pools(a)` gives it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PoolLaw {
    /// The most it holds, rested.
    pub max: f32,
    /// What it refills a real second, from `delay_ms` after the last spend or drain.
    pub regen_per_s: f32,
    pub delay_ms: u32,
    /// Tiredness caps it: full at or above `rested_at` energy, `spent_share` of `max` at 0,
    /// in a straight line between (`rested_at` 0: no cap).
    pub rested_at: f32,
    pub spent_share: f32,
    /// Below `exhausted_below` energy, the refill is `exhausted_regen` of itself.
    pub exhausted_below: f32,
    pub exhausted_regen: f32,
}

/// Breath's own numbers besides its pool: what a run and a held guard drain a second, the
/// level a run needs to start (or start again after running out), and the tiredness (energy)
/// each point spent costs.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Breath {
    pub run_per_s: f32,
    pub guard_per_s: f32,
    pub resume: f32,
    pub tires_per_point: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Pools {
    pub stamina: PoolLaw,
    pub breath: Breath,
    pub focus: PoolLaw,
}

impl Default for Pools {
    /// The shipped numbers (a script without a `pools` law).
    fn default() -> Self {
        Self {
            stamina: PoolLaw { max: 100.0, regen_per_s: 25.0, delay_ms: 1000, rested_at: 35.0, spent_share: 0.5, exhausted_below: 10.0, exhausted_regen: 0.5 },
            breath: Breath { run_per_s: 4.0, guard_per_s: 4.0, resume: 30.0, tires_per_point: 0.02 },
            focus: PoolLaw { max: 100.0, regen_per_s: 3.0, delay_ms: 2000, rested_at: 0.0, spent_share: 1.0, exhausted_below: 0.0, exhausted_regen: 1.0 },
        }
    }
}

impl PoolLaw {
    /// The most it holds at this tiredness.
    pub fn cap(&self, energy: f32) -> f32 {
        if self.rested_at <= 0.0 {
            return self.max;
        }
        let rested = (energy / self.rested_at).clamp(0.0, 1.0);
        self.max * (self.spent_share + (1.0 - self.spent_share) * rested)
    }
    /// What it refills a second at this tiredness.
    pub fn regen(&self, energy: f32) -> f32 {
        if energy < self.exhausted_below {
            self.regen_per_s * self.exhausted_regen
        } else {
            self.regen_per_s
        }
    }
}

/// A pool's level at `now`: `value` at `at_ms`, changing by `rate` a second from
/// `max(at_ms, from_ms)`, held within 0..`cap`.
pub fn level(value: f32, rate: f32, from_ms: u64, at_ms: u64, cap: f32, now: u64) -> f32 {
    let start = at_ms.max(from_ms);
    let s = now.saturating_sub(start) as f32 / 1000.0;
    (value + rate * s).clamp(0.0, cap.max(0.0))
}

/// When a draining pool (rate < 0) reaches `to` (ms; `None` when it is not draining or is
/// already there).
pub fn reaches(value: f32, rate: f32, from_ms: u64, at_ms: u64, to: f32, now: u64) -> Option<u64> {
    if rate >= 0.0 {
        return None;
    }
    let start = at_ms.max(from_ms);
    let v = level(value, rate, from_ms, at_ms, f32::INFINITY, now.max(start));
    if v <= to {
        return None;
    }
    Some(now.max(start) + ((v - to) / -rate * 1000.0).ceil() as u64)
}

/// When a refilling pool reaches `to` (ms; `Some(now)` when it is there already, `None` when it
/// never will: no refill, or a cap below `to`).
pub fn refilled(value: f32, rate: f32, from_ms: u64, at_ms: u64, cap: f32, to: f32, now: u64) -> Option<u64> {
    let v = level(value, rate, from_ms, at_ms, cap, now);
    if v >= to {
        return Some(now);
    }
    if rate <= 0.0 || cap < to {
        return None;
    }
    let start = at_ms.max(from_ms).max(now);
    let v0 = level(value, rate, from_ms, at_ms, cap, start);
    Some(start + ((to - v0) / rate * 1000.0).ceil() as u64)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tiredness_caps_breath_and_slows_its_refill() {
        let p = Pools::default();
        assert_eq!(p.stamina.cap(100.0), 100.0);
        assert_eq!(p.stamina.cap(35.0), 100.0);
        assert!((p.stamina.cap(17.5) - 75.0).abs() < 1e-4);
        assert_eq!(p.stamina.cap(0.0), 50.0);
        assert_eq!(p.stamina.regen(50.0), 25.0);
        assert_eq!(p.stamina.regen(9.0), 12.5);
        // Focus does not depend on tiredness.
        assert_eq!((p.focus.cap(0.0), p.focus.regen(0.0)), (100.0, 3.0));
    }

    #[test]
    fn a_pool_refills_after_its_delay_and_a_drain_runs_out() {
        // A dodge (20) spent at t=10 s from full: 80 until 11 s, then +25 a second.
        let (v, rate, from, at) = (80.0, 25.0, 11_000, 10_000);
        assert_eq!(level(v, rate, from, at, 100.0, 10_500), 80.0);
        assert_eq!(level(v, rate, from, at, 100.0, 11_000), 80.0);
        assert!((level(v, rate, from, at, 100.0, 11_400) - 90.0).abs() < 1e-3);
        assert_eq!(level(v, rate, from, at, 100.0, 20_000), 100.0);
        // Empty to full in 5 s after the delay.
        assert_eq!(refilled(0.0, 25.0, 1000, 0, 100.0, 100.0, 0), Some(5000));
        // Back to the run's resume level (30) 2.2 s after running out.
        assert_eq!(refilled(0.0, 25.0, 1000, 0, 100.0, 30.0, 0), Some(2200));
        assert_eq!(refilled(40.0, 25.0, 1000, 0, 100.0, 30.0, 0), Some(0));
        // A cap below the level asked for never gets there.
        assert_eq!(refilled(0.0, 25.0, 1000, 0, 25.0, 30.0, 0), None);
        // A run drains 4 a second: a full bar runs 25 s.
        assert_eq!(reaches(100.0, -4.0, 0, 0, 0.0, 0), Some(25_000));
        assert_eq!(level(100.0, -4.0, 0, 0, 100.0, 30_000), 0.0);
        assert_eq!(reaches(100.0, 25.0, 0, 0, 0.0, 0), None);
        // Focus: three fire bolts (30) from full, then one every 10 s.
        let f = Pools::default().focus;
        let after3 = 100.0 - 3.0 * 30.0;
        assert_eq!(refilled(after3, f.regen_per_s, f.delay_ms as u64, 0, f.cap(50.0), 30.0, 0), Some(2000 + 6667));
    }
}
