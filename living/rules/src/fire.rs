//! Fires that eat fuel (docs/WORLD_RULES.md, "Goods, recipes and fuel"). A structure whose kind
//! `burns` holds no fuel row: its one number is `lit_until_ms`, the moment its fuel runs out
//! at the kind's rate. The fuel left is that span times the rate, so a fire burns down without
//! anything being written or scanned while it burns; feeding it or drawing on it (a recipe's
//! `fuel`) settles the span and writes the new moment once. A fire whose moment has passed is
//! out, and stays out until it is fed again.

/// Milliseconds one unit of fuel lasts at `rate` units per game hour, on a day of `day_ms`.
pub fn ms_per_unit(rate: f32, day_ms: u64) -> f64 {
    if rate <= 0.0 {
        return f64::INFINITY;
    }
    day_ms as f64 / 24.0 / rate as f64
}

/// Whether a fire that runs out at `until_ms` burns at `now`.
pub fn lit(until_ms: u64, now: u64) -> bool {
    until_ms > now
}

/// The fuel a fire still holds at `now`, in units.
pub fn fuel_left(until_ms: u64, now: u64, rate: f32, day_ms: u64) -> f32 {
    if until_ms <= now {
        return 0.0;
    }
    ((until_ms - now) as f64 / ms_per_unit(rate, day_ms)) as f32
}

/// When a fire runs out after `units` more fuel is put on it at `now`: an out fire is lit
/// afresh, a lit one burns longer. None when the fire would hold more than `holds` units.
pub fn fed(until_ms: u64, now: u64, units: f32, rate: f32, day_ms: u64, holds: Option<f32>) -> Option<u64> {
    let left = fuel_left(until_ms, now, rate, day_ms);
    let total = left + units.max(0.0);
    if holds.is_some_and(|h| total > h + 1e-3) {
        return None;
    }
    Some(now + (total as f64 * ms_per_unit(rate, day_ms)).min(u64::MAX as f64 / 2.0) as u64)
}

/// When a lit fire runs out after `units` of its fuel are drawn at `now` (a recipe's heat).
/// None when it is out or holds less than that.
pub fn drawn(until_ms: u64, now: u64, units: f32, rate: f32, day_ms: u64) -> Option<u64> {
    let left = fuel_left(until_ms, now, rate, day_ms);
    if !lit(until_ms, now) || left + 1e-3 < units {
        return None;
    }
    let rest = (left - units.max(0.0)).max(0.0);
    Some(if rest <= 1e-3 { now } else { now + (rest as f64 * ms_per_unit(rate, day_ms)) as u64 })
}

#[cfg(test)]
mod tests {
    use super::*;

    const DAY: u64 = 12 * 60 * 1000;

    #[test]
    fn a_fire_burns_down_at_its_rate_and_goes_out() {
        // 2 units an hour on a 12-minute day: a unit lasts 15 real seconds.
        assert_eq!(ms_per_unit(2.0, DAY), 15_000.0);
        let until = fed(0, 1_000, 4.0, 2.0, DAY, None).unwrap();
        assert_eq!(until, 61_000);
        assert!(lit(until, 60_999) && !lit(until, 61_000));
        assert!((fuel_left(until, 31_000, 2.0, DAY) - 2.0).abs() < 1e-4);
        assert_eq!(fuel_left(until, 70_000, 2.0, DAY), 0.0);
    }

    #[test]
    fn feeding_settles_what_is_left_and_holds_its_limit() {
        let until = fed(0, 0, 4.0, 2.0, DAY, Some(6.0)).unwrap();
        // Half burnt: 2 left, 2 more fit, 5 do not.
        assert_eq!(fed(until, 30_000, 2.0, 2.0, DAY, Some(6.0)), Some(90_000));
        assert_eq!(fed(until, 30_000, 5.0, 2.0, DAY, Some(6.0)), None);
        // An out fire is lit afresh from now.
        assert_eq!(fed(until, 100_000, 1.0, 2.0, DAY, Some(6.0)), Some(115_000));
    }

    #[test]
    fn drawing_heat_shortens_the_burn_and_needs_enough() {
        let until = fed(0, 0, 4.0, 2.0, DAY, None).unwrap();
        assert_eq!(drawn(until, 0, 1.0, 2.0, DAY), Some(45_000));
        assert_eq!(drawn(until, 0, 4.0, 2.0, DAY), Some(0));
        assert_eq!(drawn(until, 0, 5.0, 2.0, DAY), None);
        assert_eq!(drawn(until, 60_000, 0.5, 2.0, DAY), None);
    }
}
