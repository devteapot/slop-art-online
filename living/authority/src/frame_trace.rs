//! Profiling only: how often frames look at each viewer/creature pair, and how stale what they
//! deliver is (`frame.rs`; `living/tools/tick_cost.py` reads the lines). From frame-fresh's
//! pair cadence, with the staleness of deliveries added.
use spacetimedb::ReducerContext;
use std::cell::RefCell;
use std::collections::{BTreeMap, HashMap};

thread_local! {
    /// When a frame last looked at each pair (`frame::key`).
    static LAST: RefCell<HashMap<u64, u64>> = RefCell::new(HashMap::new());
}

/// A creature died: its pairs' last looks go.
pub(crate) fn forget(body: u32) {
    LAST.with(|l| l.borrow_mut().retain(|k, _| *k == u64::MAX || (*k & 0xFFFF_FFFF) as u32 != body));
}

#[derive(Default)]
pub(crate) struct Trace {
    /// Interval (ms) → (pairs, near pairs).
    cadence: BTreeMap<u64, (u32, u32)>,
    /// Staleness (ms) from a creature's first change not yet delivered to its delivery → (frame
    /// writes, of which near, cues).
    stale: BTreeMap<u64, (u32, u32, u32)>,
}

impl Trace {
    /// A frame looked at a pair (whether or not a row needed writing).
    pub fn served(&mut self, viewer: u32, body: u32, now: u64, near: bool) {
        let previous = LAST.with(|l| l.borrow_mut().insert(crate::frame::key(viewer, body), now));
        if let Some(previous) = previous.filter(|p| *p < now) {
            let c = self.cadence.entry(now - previous).or_default();
            c.0 += 1;
            c.1 += u32::from(near);
        }
    }

    /// A tick's cues looked at `pairs` near pairs (every tick does: a pair's interval is the
    /// interval between ticks).
    pub fn cue_pass(&mut self, now: u64, pairs: u32) {
        let previous = LAST.with(|l| l.borrow_mut().insert(u64::MAX, now));
        if let Some(previous) = previous.filter(|p| *p < now) {
            let c = self.cadence.entry(now - previous).or_default();
            c.0 += pairs;
            c.1 += pairs;
        }
    }

    /// A change reached a viewer `ms` after it was made, by a frame's copy or by a cue.
    pub fn stale(&mut self, ms: u64, near: bool, cue: bool) {
        let s = self.stale.entry(ms).or_default();
        if cue {
            s.2 += 1;
        } else {
            s.0 += 1;
            s.1 += u32::from(near);
        }
    }

    pub fn log(self, ctx: &ReducerContext) {
        let ts = ctx.timestamp.to_micros_since_unix_epoch();
        if !self.cadence.is_empty() {
            let counts: Vec<_> = self.cadence.into_iter().map(|(ms, (all, near))| (ms, all, near)).collect();
            log::info!("frame pair cadence: {ts} {counts:?}");
        }
        if !self.stale.is_empty() {
            let counts: Vec<_> = self.stale.into_iter().map(|(ms, (all, near, cue))| (ms, all, near, cue)).collect();
            log::info!("frame staleness: {ts} {counts:?}");
        }
    }
}
