//! A person's daily rhythm (docs/SEEDED_LIVES.md, "No lockstep"): when it rises and goes to
//! bed, how long its evening is, its working hours and an optional second sleep. These are a
//! person's starting values of the routines everyone has; graphs read them as the `bedtime`,
//! `evening` and `work_hours` weights and conditions. Nothing here is a role: a night stoker and
//! a baker differ only in their hours.

/// The hours of one person's day. Hours of the day are 0..24; an end may pass 24 (30.0 is 06:00
/// the next morning). `bed_h` lies in `rise_h + 8 ..= rise_h + 22`. A span whose end is not after
/// its start (the defaults, 0 and 0) is not set.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Hours {
    pub rise_h: f32,
    pub bed_h: f32,
    pub evening_h: f32,
    pub work_from_h: f32,
    pub work_to_h: f32,
    pub nap_from_h: f32,
    pub nap_to_h: f32,
}

/// Where a body is in its own day.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Phase {
    /// Between going to bed and rising, or in its second sleep.
    pub bedtime: bool,
    /// The hours before bed it keeps for itself (not during a second sleep).
    pub evening: bool,
    /// Its working hours; with none set, any waking hour outside its evening.
    pub work: bool,
}

/// `hour` lies in the span `from..to` (to > from; it may pass midnight).
fn within(hour: f32, from: f32, to: f32) -> bool {
    to > from && (hour - from).rem_euclid(24.0) < to - from
}

impl Hours {
    pub fn works(&self) -> Option<(f32, f32)> {
        (self.work_to_h > self.work_from_h).then_some((self.work_from_h, self.work_to_h))
    }

    pub fn naps(&self) -> Option<(f32, f32)> {
        (self.nap_to_h > self.nap_from_h).then_some((self.nap_from_h, self.nap_to_h))
    }

    /// Where the body is in its day at `hour` (0..24).
    pub fn phase(&self, hour: f32) -> Phase {
        // Hours from rising run rise..rise+24, so a bedtime past midnight compares in one range.
        // (For a rising before noon and a bed after it this gives exactly the comparisons of the
        // rule it replaced, which pivoted at noon: see the authority's `drawn_rhythms_keep_their_phase`.)
        let h = if hour < self.rise_h { hour + 24.0 } else { hour };
        let nap = self.naps().is_some_and(|(a, b)| within(hour, a, b));
        // `h < rise + 24` is true but for an hour within float rounding of rising, where the
        // old rule said "up" too; it is kept so drawn rhythms compare bit for bit as before.
        let bedtime = (h >= self.bed_h && h < self.rise_h + 24.0) || nap;
        let evening = h >= self.bed_h - self.evening_h && h < self.bed_h && !nap;
        let work = match self.works() {
            Some((a, b)) => within(hour, a, b),
            None => !bedtime && !evening,
        };
        Phase { bedtime, evening, work }
    }
}

/// What a seed gives of a rhythm (`residents[].rhythm`); whatever it leaves out stays as drawn.
#[derive(Clone, Copy, Debug, Default)]
pub struct Given {
    pub rises: Option<f32>,
    pub sleeps: Option<f32>,
    pub evening_hours: Option<f32>,
    pub works: Option<[f32; 2]>,
    pub second_sleep: Option<[f32; 2]>,
}

/// A span from clock hours: its start in 0..24 and its end after it (within a day); none for an
/// empty one.
fn span(s: [f32; 2]) -> (f32, f32) {
    let from = s[0].rem_euclid(24.0);
    let len = (s[1] - s[0]).rem_euclid(24.0);
    if len <= 0.0 {
        (0.0, 0.0)
    } else {
        (from, from + len)
    }
}

/// A drawn rhythm with what the seed gives laid over it. Rising may be any hour; going to bed is
/// the next time of that hour after rising, kept 8 to 22 hours after it (so 07:00 after rising at
/// 14:00 is 31.0); without one, the drawn length of the waking day. The evening is 0 to 8 hours.
pub fn given(base: Hours, g: &Given) -> Hours {
    let mut r = base;
    if let Some(x) = g.rises {
        r.rise_h = x.rem_euclid(24.0);
    }
    let awake = match g.sleeps {
        Some(b) => (b - r.rise_h).rem_euclid(24.0),
        None => base.bed_h - base.rise_h,
    };
    r.bed_h = (r.rise_h + awake).clamp(r.rise_h + 8.0, r.rise_h + 22.0);
    r.evening_h = g.evening_hours.unwrap_or(r.evening_h).clamp(0.0, 8.0);
    if let Some(w) = g.works {
        (r.work_from_h, r.work_to_h) = span(w);
    }
    if let Some(n) = g.second_sleep {
        (r.nap_from_h, r.nap_to_h) = span(n);
    }
    r
}

#[cfg(test)]
mod tests {
    use super::*;

    fn day(r: &Hours) -> Vec<Phase> {
        (0..24 * 60).map(|m| r.phase(m as f32 / 60.0)).collect()
    }

    #[test]
    fn a_night_worker_rises_in_the_afternoon_and_works_the_night() {
        // Thessaly: rises 14:00 after 7 hours' sleep, works the 22:00-06:00 watch.
        let r = given(Hours::default(), &Given { rises: Some(14.0), sleeps: Some(7.0), evening_hours: Some(1.0), works: Some([22.0, 30.0]), second_sleep: None });
        assert_eq!((r.rise_h, r.bed_h, r.work_from_h, r.work_to_h), (14.0, 31.0, 22.0, 30.0));
        let at = |h: f32| r.phase(h);
        assert!(at(10.0).bedtime && at(13.9).bedtime && at(7.0).bedtime);
        assert!(!at(14.0).bedtime && !at(23.0).bedtime && !at(5.0).bedtime);
        assert!(at(22.0).work && at(2.0).work && at(5.9).work && !at(6.0).work && !at(15.0).work);
        assert!(at(6.5).evening && !at(5.5).evening && !at(7.0).evening);
    }

    #[test]
    fn a_second_sleep_is_bedtime_and_not_evening() {
        // Pieter: up 02:30, bakes 03:00-10:00, sleeps 13:00-19:00, then to bed at 22:00.
        let r = given(Hours::default(), &Given { rises: Some(2.5), sleeps: Some(22.0), evening_hours: Some(3.0), works: Some([3.0, 10.0]), second_sleep: Some([13.0, 19.0]) });
        assert_eq!((r.rise_h, r.bed_h, r.nap_from_h, r.nap_to_h), (2.5, 22.0, 13.0, 19.0));
        let at = |h: f32| r.phase(h);
        assert!(at(23.0).bedtime && at(1.0).bedtime && !at(2.5).bedtime && !at(12.0).bedtime);
        assert!(at(13.0).bedtime && at(18.9).bedtime && !at(19.0).bedtime);
        assert!(at(20.0).evening && !at(18.0).evening);
        assert!(at(4.0).work && !at(11.0).work);
    }

    #[test]
    fn spans_cross_midnight_and_empty_ones_are_unset() {
        assert_eq!(span([22.0, 6.0]), (22.0, 30.0));
        assert_eq!(span([22.0, 30.0]), (22.0, 30.0));
        assert_eq!(span([25.0, 27.0]), (1.0, 3.0));
        assert_eq!(span([8.0, 8.0]), (0.0, 0.0));
        let r = Hours { rise_h: 6.0, bed_h: 22.0, evening_h: 3.0, ..Default::default() };
        assert!(r.works().is_none() && r.naps().is_none());
        // No set hours: working hours are every waking hour outside the evening.
        let d = day(&r);
        assert!(d.iter().all(|p| p.work == (!p.bedtime && !p.evening)));
    }

    #[test]
    fn bed_keeps_eight_to_twenty_two_hours_after_rising() {
        let base = Hours { rise_h: 6.0, bed_h: 22.0, evening_h: 3.0, ..Default::default() };
        let g = |rises, sleeps| given(base, &Given { rises, sleeps, ..Default::default() });
        assert_eq!(g(Some(20.0), Some(13.0)).bed_h, 37.0);
        assert_eq!(g(Some(6.0), Some(0.5)).bed_h, 24.5);
        assert_eq!(g(Some(6.0), Some(25.0)).bed_h, 25.0);
        assert_eq!(g(Some(6.0), Some(10.0)).bed_h, 14.0);
        // Rising later without a bedtime keeps the drawn day's length.
        assert_eq!(g(Some(14.0), None).bed_h, 30.0);
        assert_eq!(g(None, None), base);
    }
}
