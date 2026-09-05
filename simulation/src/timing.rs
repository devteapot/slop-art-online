//! Simulation time is independent of scheduler frequency. No host clock enters this module.
use crate::*;

/// Compatibility unit for existing scenario limits, request cursors and `expires_tick`.
/// It is not an authoritative update interval. New integrations should use milliseconds.
pub const LEGACY_UNIT_MS: u64 = 2_500;
pub const UPDATE_MS: u64 = 50;

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Timing {
    pub time_ms: u64,
    pub updates: u64,
    pub delta_ms: u64,
    pub needs_remainder_ms: u64,
    pub hazard_remainder_ms: u64,
    #[serde(default)]
    pub food_remainder_ms: BTreeMap<i32, u64>,
    pub action_ready_ms: BTreeMap<u32, u64>,
    pub dialogue_ready_ms: BTreeMap<u32, u64>,
    pub dirty: BTreeMap<u32, bool>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Periods {
    pub needs_ms: u64,
    pub hazard_ms: u64,
}

pub fn pulses(remainder: &mut u64, delta: u64, interval: u64) -> Result<u64, String> {
    if !(1..=3_600_000).contains(&interval) {
        return Err("scripted interval must be 1..3600000 ms".into());
    }
    *remainder = remainder.checked_add(delta).ok_or("time overflow")?;
    let due = *remainder / interval;
    *remainder %= interval;
    Ok(due)
}

impl World {
    pub(super) fn execution_ready_at(&self, actor: u32, e: &Execution) -> u64 {
        let continuation = if e.attempt.is_some() {
            e.script.as_ref().map_or(0, |s| s.wake_at_ms)
        } else {
            0
        };
        self.ready_at(actor, e.dialogue).max(continuation)
    }

    pub(super) fn ready_at(&self, actor: u32, dialogue: bool) -> u64 {
        let times = if dialogue {
            &self.timing.dialogue_ready_ms
        } else {
            &self.timing.action_ready_ms
        };
        times.get(&actor).copied().unwrap_or(0)
    }
    pub(super) fn set_ready_at(&mut self, actor: u32, dialogue: bool, time_ms: u64) {
        let times = if dialogue {
            &mut self.timing.dialogue_ready_ms
        } else {
            &mut self.timing.action_ready_ms
        };
        times.insert(actor, time_ms);
    }
    pub(super) fn wake(&mut self, actor: u32) {
        self.timing.dirty.insert(actor, true);
    }
    /// A bounded coarse step for existing headless experiments; live reducers use `advance_ms`.
    pub fn step(&mut self) {
        self.advance_ms(LEGACY_UNIT_MS);
    }
}
