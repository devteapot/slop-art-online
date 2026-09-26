//! Life course: stages as fractions of a species' lifespan, at the world's pace.
//!
//! The same mechanics run at any pace: a world for play has long lives; a lab scenario
//! compresses them (`World.life_pace` < 1) to watch births, growing up and old age in an
//! evening. Age is measured in world days (`birth_age_days` + elapsed days).

use serde::Deserialize;

#[derive(Clone, Copy, Debug, Deserialize)]
pub struct Life {
    /// Lifespan in years (a world's year has `year_days` days).
    pub years: f32,
    /// Stage ends, as fractions of the lifespan.
    #[serde(default = "infant")]
    pub infant: f32,
    #[serde(default = "child")]
    pub child: f32,
    #[serde(default = "elder")]
    pub elder: f32,
    /// Deaths of old age fall between this fraction and 1.0 (each creature's own point).
    #[serde(default = "old_age")]
    pub old_age: f32,
    /// Pregnancy, as a fraction of the lifespan.
    #[serde(default = "gestation")]
    pub gestation: f32,
    /// Young born at once (the upper bound; at least one).
    #[serde(default = "one")]
    pub litter: u32,
}

fn infant() -> f32 {
    0.004
}
fn child() -> f32 {
    0.05
}
fn elder() -> f32 {
    0.75
}
fn old_age() -> f32 {
    0.8
}
fn gestation() -> f32 {
    0.01
}
fn one() -> u32 {
    1
}

impl Default for Life {
    fn default() -> Self {
        Self { years: 70.0, infant: infant(), child: child(), elder: elder(), old_age: old_age(), gestation: gestation(), litter: 1 }
    }
}

/// A world's time: days per calendar year and how fast lives run.
#[derive(Clone, Copy, Debug)]
pub struct Pace {
    pub year_days: f32,
    pub pace: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stage {
    Infant,
    Child,
    Adult,
    Elder,
}

impl Stage {
    pub fn name(self) -> &'static str {
        match self {
            Stage::Infant => "infant",
            Stage::Child => "child",
            Stage::Adult => "adult",
            Stage::Elder => "elder",
        }
    }
}

impl Life {
    /// Lifespan in world days: years × days per year × the world's pace.
    pub fn span(&self, year_days: f32, pace: f32) -> f32 {
        (self.years * year_days * pace.max(0.0001)).max(0.01)
    }

    /// Fraction of the lifespan lived.
    pub fn fraction(&self, age_days: f32, t: Pace) -> f32 {
        age_days / self.span(t.year_days, t.pace)
    }

    pub fn stage(&self, age_days: f32, t: Pace) -> Stage {
        let f = self.fraction(age_days, t);
        if f < self.infant {
            Stage::Infant
        } else if f < self.child {
            Stage::Child
        } else if f < self.elder {
            Stage::Adult
        } else {
            Stage::Elder
        }
    }

    /// The fraction of its lifespan at which this creature dies of old age: its own point
    /// between `old_age` and 1.0, fixed by its id (no stored dice roll).
    pub fn deathline(&self, id: u32) -> f32 {
        let mut h = (id as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ 0x5851_F42D_4C95_7F2D;
        h ^= h >> 29;
        h = h.wrapping_mul(0xBF58_476D_1CE4_E5B9);
        h ^= h >> 32;
        let u = (h % 10_000) as f32 / 10_000.0;
        self.old_age + (1.0 - self.old_age) * u
    }

    /// Age in world days for a given fraction of the lifespan (for seeding).
    pub fn age_at(&self, fraction: f32, t: Pace) -> f32 {
        fraction * self.span(t.year_days, t.pace)
    }

    pub fn gestation_days(&self, t: Pace) -> f32 {
        self.gestation * self.span(t.year_days, t.pace)
    }

    /// Age in whole years.
    pub fn years_old(&self, age_days: f32, t: Pace) -> f32 {
        age_days / (t.year_days * t.pace.max(0.0001)).max(0.0001)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stages_follow_the_pace() {
        let l = Life { years: 70.0, infant: 0.03, child: 0.23, elder: 0.85, ..Life::default() };
        let t = Pace { year_days: 1800.0, pace: 1.0 };
        assert_eq!(l.stage(1.0 * 1800.0, t), Stage::Infant);
        assert_eq!(l.stage(10.0 * 1800.0, t), Stage::Child);
        assert_eq!(l.stage(30.0 * 1800.0, t), Stage::Adult);
        assert_eq!(l.stage(65.0 * 1800.0, t), Stage::Elder);
        // A lab with short years: the same fractions, much sooner.
        let lab = Pace { year_days: 1.0, pace: 1.0 };
        assert_eq!(l.stage(30.0, lab), Stage::Adult);
        assert!((l.years_old(30.0 * 1800.0, t) - 30.0).abs() < 0.01);
        let d = l.deathline(7);
        assert!((l.old_age..=1.0).contains(&d));
        assert_ne!(l.deathline(7), l.deathline(8));
    }
}
