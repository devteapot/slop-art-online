//! Opt-in, systematically sampled diagnostics. No clock values affect gameplay.
#[cfg(feature = "clock-profile")]
use std::cell::Cell;

#[cfg(feature = "clock-profile")]
thread_local! {
    static COUNTS: Cell<[u64; 4]> = const { Cell::new([0; 4]) };
    static SCRIPT_COUNTS: Cell<[u64; 6]> = const { Cell::new([0; 6]) };
}

#[cfg(feature = "clock-profile")]
pub(super) struct KernelScope;
#[cfg(feature = "clock-profile")]
impl KernelScope {
    pub(super) fn new() -> Self {
        COUNTS.with(|c| c.set([0; 4]));
        SCRIPT_COUNTS.with(|c| c.set([0; 6]));
        Self
    }
}
#[cfg(feature = "clock-profile")]
impl Drop for KernelScope {
    fn drop(&mut self) {
        COUNTS.with(|c| log::info!("evidence-profile-counts {:?}", c.get()));
        SCRIPT_COUNTS.with(|c| log::info!("script-profile-counts {:?}", c.get()));
    }
}

#[cfg(feature = "clock-profile")]
pub(super) fn timer(name: &'static str) -> Box<dyn std::any::Any> {
    let script_slot = match name {
        "script.input_budget" => Some(0),
        "script.compiled" => Some(1),
        "script.input_convert" => Some(2),
        "script.invoke" => Some(3),
        "script.output_convert" => Some(4),
        "script.output_budget" => Some(5),
        _ => None,
    };
    if let Some(slot) = script_slot {
        let selected = SCRIPT_COUNTS.with(|counts| {
            let mut value = counts.get();
            let selected = value[slot] % 17 == 0;
            value[slot] += 1;
            counts.set(value);
            selected
        });
        return if selected { Box::new(spacetimedb::log_stopwatch::LogStopwatch::new(name)) }
            else { Box::new(()) };
    }
    let sample = match name {
        "evidence.record.cold" => Some((0, 7)),
        "evidence.record.warm" => Some((1, 67)),
        "evidence.parents" => Some((2, 67)),
        "evidence.append" => Some((3, 67)),
        _ => None,
    };
    let selected = sample.is_none_or(|(slot, stride)| COUNTS.with(|counts| {
        let mut value = counts.get();
        let selected = value[slot] % stride == 0;
        value[slot] += 1;
        counts.set(value);
        selected
    }));
    if selected { Box::new(spacetimedb::log_stopwatch::LogStopwatch::new(name)) }
    else { Box::new(()) }
}

pub(super) struct SaveScope {
    #[cfg(feature = "clock-profile")]
    span: Option<spacetimedb::log_stopwatch::LogStopwatch>,
}
impl SaveScope {
    #[inline]
    pub(super) fn new(_selected: bool, _name: &'static str) -> Self {
        Self {
            #[cfg(feature = "clock-profile")]
            span: _selected.then(|| spacetimedb::log_stopwatch::LogStopwatch::new(_name)),
        }
    }
    #[inline]
    pub(super) fn phase(&mut self, _selected: bool, _name: &'static str) {
        #[cfg(feature = "clock-profile")]
        {
            drop(self.span.take());
            self.span = _selected.then(|| spacetimedb::log_stopwatch::LogStopwatch::new(_name));
        }
    }
}
