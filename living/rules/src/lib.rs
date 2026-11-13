//! Shared rules for the living core: map, behavior graph grammar, vocabulary and the
//! Rhai skill runtime. Used by the authority module, the mind service and the viewer.

pub mod acts;
pub mod catalog;
pub mod combat;
pub mod det;
pub mod doing;
pub mod fire;
pub mod fold;
pub mod graph;
pub mod height;
pub mod host;
pub mod land;
pub mod settle;
pub mod outcome;
pub mod sight;
pub mod map;
pub mod nav;
pub mod pools;
pub mod city;
pub mod genes;
pub mod life;
pub mod look;
pub mod rhythm;
pub mod sex;
pub mod realm;
pub mod reasons;
pub mod records;
pub mod normalize;
#[cfg(feature = "scripting")]
pub mod floors;
#[cfg(feature = "scripting")]
pub mod cullet_check;
mod making_check;
mod goods_check;
#[cfg(feature = "scripting")]
pub mod goods_audit;
mod rates_check;
mod rules3_check;
#[cfg(feature = "scripting")]
pub mod script;
pub mod social;
pub mod species;
pub mod steer;
pub mod ui;
pub mod ways;

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

/// Night as the shipped `daylight` law has it (20:00 to 06:00), for a client that does not
/// compile the world's script (the developer observer's clock label). The authority, the mind
/// service and the rules ask the world's own law (`script::Scripts::is_night`).
pub fn shipped_night(hour: f32) -> bool {
    !(6.0..20.0).contains(&hour)
}

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

/// The shipped share of a resource's regrowth rate in each season (spring, summer, autumn,
/// winter): full while growing, none in winter. A resource kind's `regrow_by_season` trait
/// replaces it ([`crate::script::Scripts::regrow_seasons`]).
pub const GROWING: [f32; 4] = [1.0, 1.0, 1.0, 0.0];

/// Milliseconds of each season (spring, summer, autumn, winter) between `t0` and `t1`, on the
/// same quarters of the year as [`growing_ms`] (the first three of them sum to it exactly).
pub fn season_ms(t0: u64, t1: u64, epoch_ms: u64, day_ms: u64, year_days: u64) -> [u64; 4] {
    if t1 <= t0 {
        return [0; 4];
    }
    let offset = day_ms * 7 / 24; // the world starts at 07:00 on day 1
    let y = year_days.max(4);
    let year = day_ms * y;
    let bound = |k: u64| day_ms * y * k / 4;
    // Time of season `k` from the epoch-aligned origin to `t`.
    let upto = |t: u64, k: u64| -> u64 {
        let x = t.saturating_sub(epoch_ms) + offset;
        let (whole, rest) = (x / year, x % year);
        let (lo, hi) = (bound(k), bound(k + 1));
        whole * (hi - lo) + rest.clamp(lo, hi) - lo
    };
    [0, 1, 2, 3].map(|k| upto(t1, k).saturating_sub(upto(t0, k)))
}

/// Real milliseconds of full-rate regrowth between `t0` and `t1` for a resource growing `by`
/// of its rate in each season (spring, summer, autumn, winter): a node's amount grows by its
/// per-minute `regen` times this over 60,000. With the shipped shares ([`GROWING`]) it is
/// [`growing_ms`] exactly, so worlds without the trait regrow bit for bit as before.
pub fn regrowth_ms(t0: u64, t1: u64, epoch_ms: u64, day_ms: u64, year_days: u64, by: &[f32; 4]) -> f32 {
    if *by == GROWING {
        return growing_ms(t0, t1, epoch_ms, day_ms, year_days) as f32;
    }
    let s = season_ms(t0, t1, epoch_ms, day_ms, year_days);
    s.iter().zip(by).map(|(ms, f)| *ms as f64 * *f as f64).sum::<f64>() as f32
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

    #[test]
    fn seasons_split_time_on_growings_quarters() {
        let epoch = 1_000_000;
        for (day, y) in [(DEFAULT_DAY_MS, YEAR_DAYS), (48 * 60_000, YEAR_DAYS), (720_000, 10), (1_000_003, 7)] {
            let w0 = epoch + day * 6 - day * 7 / 24;
            let mut t0 = epoch.saturating_sub(day);
            while t0 < epoch + day * y * 3 {
                for len in [0, 1, 59_999, day / 3, day, day * 2 + 17, day * y + 5] {
                    let t1 = t0 + len;
                    let s = season_ms(t0, t1, epoch, day, y);
                    assert_eq!(s[0] + s[1] + s[2], growing_ms(t0, t1, epoch, day, y), "{t0} {t1} {day} {y}");
                    assert_eq!(s.iter().sum::<u64>(), t1.max(epoch) - t0.max(epoch));
                    assert_eq!(regrowth_ms(t0, t1, epoch, day, y, &GROWING).to_bits(), (growing_ms(t0, t1, epoch, day, y) as f32).to_bits());
                    assert_eq!(regrowth_ms(t0, t1, epoch, day, y, &[1.0, 1.0, 1.0, 1.0]).to_bits(), (s.iter().sum::<u64>() as f32).to_bits());
                }
                t0 += day / 5 + 7;
            }
            if y == YEAR_DAYS {
                // A Cullet winter's two days: all winter, so a kind growing 0.75 of its rate then
                // grows three quarters of two days; one resting grows nothing.
                assert_eq!(season_ms(w0, w0 + day * 2, epoch, day, y), [0, 0, 0, day * 2]);
                assert_eq!(regrowth_ms(w0, w0 + day * 2, epoch, day, y, &[1.0, 1.0, 1.0, 0.75]), (day * 2) as f32 * 0.75);
                assert_eq!(regrowth_ms(w0, w0 + day * 2, epoch, day, y, &GROWING), 0.0);
            }
        }
    }
}
