//! Shared rules for the living core: map, behavior graph grammar, vocabulary and the
//! Rhai skill runtime. Used by the authority module, the mind service and the viewer.

pub mod catalog;
pub mod graph;
pub mod map;
pub mod city;
pub mod life;
pub mod realm;
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

/// A span of world days in words ("a few hours", "about 2 days").
pub fn describe_days(d: f32) -> String {
    if d < 0.2 {
        "a few hours".into()
    } else if d < 0.75 {
        "half a day".into()
    } else if d < 1.5 {
        "a day".into()
    } else {
        format!("{:.0} days", d)
    }
}

/// In-world days per year: spring, summer, autumn, winter (two days each), from day 1.
pub const YEAR_DAYS: u64 = 8;
pub const SEASONS: [&str; 4] = ["spring", "summer", "autumn", "winter"];

/// Season index for a calendar year of `year_days` days (four equal seasons).
pub fn season_of(now_ms: u64, epoch_ms: u64, day_ms: u64, year_days: u64) -> usize {
    let y = year_days.max(4);
    ((((day_of(now_ms, epoch_ms, day_ms) - 1) % y) * 4) / y) as usize
}

/// Milliseconds of growing time (not winter) between `t0` and `t1`; plants regrow only then.
pub fn growing_ms(t0: u64, t1: u64, epoch_ms: u64, day_ms: u64, year_days: u64) -> u64 {
    if t1 <= t0 {
        return 0;
    }
    let offset = day_ms * 7 / 24; // the world starts at 07:00 on day 1
    let y = year_days.max(4);
    let year = day_ms * y;
    let winter_start = day_ms * y * 3 / 4;
    // Growing time from the epoch-aligned origin to `t`.
    let grown = |t: u64| -> u64 {
        let x = t.saturating_sub(epoch_ms) + offset;
        let whole = x / year;
        let rest = x % year;
        whole * winter_start + rest.min(winter_start)
    };
    grown(t1).saturating_sub(grown(t0))
}

#[cfg(test)]
mod season_tests {
    use super::*;

    #[test]
    fn winter_stops_growth() {
        let day = DEFAULT_DAY_MS;
        let epoch = 1_000_000;
        let start = epoch + day * 17 / 24; // day 1, 07:00 == epoch
        let y = YEAR_DAYS;
        assert_eq!(season_of(epoch, epoch, day, y), 0);
        assert_eq!(season_of(epoch + day * 6, epoch, day, y), 3);
        assert_eq!(growing_ms(epoch, epoch + day, epoch, day, y), day);
        let w0 = epoch + day * 6 - day * 7 / 24; // start of day 7 (winter)
        assert_eq!(growing_ms(w0, w0 + day * 2, epoch, day, y), 0);
        assert_eq!(growing_ms(w0 - day, w0 + day, epoch, day, y), day);
        // A long year: winter is its last quarter.
        assert_eq!(season_of(epoch + day * 1400, epoch, day, 1800), 3);
        assert_eq!(season_of(epoch + day * 500, epoch, day, 1800), 1);
        let _ = start;
    }
}

/// Sight at night while carrying a torch.
pub const TORCH_SIGHT: f32 = 9.0;
