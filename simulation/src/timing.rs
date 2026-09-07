//! Simulation time is independent of scheduler frequency. No host clock enters this module.
use crate::*;

/// Compatibility unit for existing scenario limits, request cursors and `expires_tick`.
/// It is not an authoritative update interval. New integrations should use milliseconds.
pub const LEGACY_UNIT_MS: u64 = 2_500;
pub const UPDATE_MS: u64 = 50;

/// Optional diagnostic phase notifications. No measured time enters the kernel,
/// persisted state or gameplay decisions. The normal path uses the no-op sink.
pub trait AdvanceObserver {
    fn begin(&mut self, phase: &'static str);
}
impl AdvanceObserver for () {
    fn begin(&mut self, _: &'static str) {}
}

/// Diagnostic host spans are erased in normal builds. The host owns clocks and
/// logging; their values never enter simulation state or execution decisions.
pub struct DiagnosticScope {
    #[cfg(feature = "runtime-profile")]
    _host: Option<Box<dyn std::any::Any>>,
}
impl DiagnosticScope {
    #[inline]
    pub fn new(_name: &'static str) -> Self {
        Self {
            #[cfg(feature = "runtime-profile")]
            _host: DIAGNOSTICS.with(|f| f.get().map(|f| f(_name))),
        }
    }
}
#[cfg(feature = "runtime-profile")]
type DiagnosticFactory = fn(&'static str) -> Box<dyn std::any::Any>;
#[cfg(feature = "runtime-profile")]
thread_local! {
    static DIAGNOSTICS: std::cell::Cell<Option<DiagnosticFactory>> = const { std::cell::Cell::new(None) };
}
#[cfg(feature = "runtime-profile")]
pub fn with_diagnostics<T>(factory: DiagnosticFactory, work: impl FnOnce() -> T) -> T {
    struct Restore(Option<DiagnosticFactory>);
    impl Drop for Restore {
        fn drop(&mut self) { DIAGNOSTICS.with(|f| f.set(self.0)); }
    }
    let _restore = Restore(DIAGNOSTICS.with(|f| f.replace(Some(factory))));
    work()
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Timing {
    #[serde(default)]
    pub applied_disturbances: std::collections::BTreeSet<usize>,
    pub time_ms: u64,
    pub updates: u64,
    pub delta_ms: u64,
    /// When present, slow-system remainders are settled through this time.
    /// Action transactions can advance time without rewriting those systems.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub maintenance_ms: Option<u64>,
    pub needs_remainder_ms: u64,
    pub hazard_remainder_ms: u64,
    #[serde(default)]
    pub actor_needs_remainder_ms: BTreeMap<u32, u64>,
    #[serde(default)]
    pub actor_hazard_remainder_ms: BTreeMap<u32, u64>,
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
