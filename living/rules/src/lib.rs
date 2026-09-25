//! Shared rules for the living core: map, behavior graph grammar, vocabulary and the
//! Rhai skill runtime. Used by the authority module, the mind service and the viewer.

pub mod catalog;
pub mod graph;
pub mod map;
pub mod normalize;
#[cfg(feature = "scripting")]
pub mod script;
pub mod species;

/// Real milliseconds per in-world day.
pub const DEFAULT_DAY_MS: u64 = 12 * 60 * 1000;

/// Hour of day (0..24) given world epoch and day length.
pub fn hour_of(now_ms: u64, epoch_ms: u64, day_ms: u64) -> f32 {
    // The world starts at 07:00.
    let t = now_ms.saturating_sub(epoch_ms) + day_ms * 7 / 24;
    ((t % day_ms) as f64 / day_ms as f64 * 24.0) as f32
}

pub fn day_of(now_ms: u64, epoch_ms: u64, day_ms: u64) -> u64 {
    (now_ms.saturating_sub(epoch_ms) + day_ms * 7 / 24) / day_ms + 1
}

pub fn is_night(hour: f32) -> bool {
    !(6.0..20.0).contains(&hour)
}

pub const SIGHT: f32 = 11.0;
pub const NIGHT_SIGHT: f32 = 6.0;
pub const HEARING: f32 = 9.0;

/// Days after which a newborn counts as grown (can build, craft, fight, conceive).
pub const ADULT_DAYS: f32 = 3.0;
