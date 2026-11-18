//! Profiling-only interval counts, pooled over viewer/body pairs.
use spacetimedb::ReducerContext;
use std::collections::BTreeMap;

#[derive(Default)]
pub(crate) struct Cadence(BTreeMap<u64, (u32, u32)>);

impl Cadence {
    pub fn served(&mut self, now: u64, last: &mut u64, relevant: bool) {
        let previous = std::mem::replace(last, now);
        if previous != 0 {
            let counts = self.0.entry(now - previous).or_default();
            counts.0 += 1;
            counts.1 += u32::from(relevant);
        }
    }

    pub fn log(self, ctx: &ReducerContext) {
        if !self.0.is_empty() {
            let counts: Vec<_> = self.0.into_iter().map(|(interval, (all, relevant))| (interval, all, relevant)).collect();
            log::info!("frame pair cadence: {} {:?}", ctx.timestamp.to_micros_since_unix_epoch(), counts);
        }
    }
}
