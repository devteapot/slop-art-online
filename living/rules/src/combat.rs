//! Combat vocabulary and geometry shared by the authority (which rules) and clients (which
//! only present). Numbers that balance combat (windups, damage, costs, cooldowns, missile
//! speeds) live in the Rhai skill script, not here; this module holds the codes clients and
//! the authority agree on and the pure geometry both sides evaluate the same way.
//!
//! The six starter skills (docs/GAME_BRIEF.md, 2026-11-09) and the older force skills share
//! one timing model: a **windup** (the skill's `_duration`, when others can see it coming),
//! the **release** (effects apply, or a missile leaves), a **recovery** (no other combat move
//! but a dodge) and a **cooldown** counted from the start. See docs/COMBAT.md.

/// The starter skills on the game's skill bar, in bar order (LMB, RMB, Q, E, R, Shift).
pub const STARTER: [&str; 6] = ["strike", "bowshot", "firebolt", "block", "heal", "dodge"];

/// Combat skills whose timing (cooldown, recovery, busy) the authority enforces.
pub const TIMED: [&str; 9] = ["strike", "bowshot", "firebolt", "block", "heal", "dodge", "attack", "shoot", "throw"];

/// Skills whose target is a direction (a skillshot), not a creature.
pub const AIMED: [&str; 2] = ["bowshot", "firebolt"];

/// Skills during whose windup the body stands still.
pub const ROOTED: [&str; 6] = ["strike", "bowshot", "firebolt", "heal", "attack", "shoot"];

pub fn timed(skill: &str) -> bool {
    TIMED.contains(&skill)
}

pub fn aimed(skill: &str) -> bool {
    AIMED.contains(&skill)
}

/// Presentation code of a skill (`fighter.act`, `combat_seen.skill`); 0 for none or unknown.
pub fn code(skill: &str) -> u8 {
    match skill {
        "strike" => 1,
        "bowshot" => 2,
        "firebolt" => 3,
        "block" => 4,
        "heal" => 5,
        "dodge" => 6,
        "attack" => 7,
        "shoot" => 8,
        "throw" => 9,
        "threaten" => 10,
        "tend" => 11,
        "yield" => 12,
        _ => 0,
    }
}

/// The skill named by a presentation code.
pub fn name(code: u8) -> &'static str {
    match code {
        1 => "strike",
        2 => "bowshot",
        3 => "firebolt",
        4 => "block",
        5 => "heal",
        6 => "dodge",
        7 => "attack",
        8 => "shoot",
        9 => "throw",
        10 => "threaten",
        11 => "tend",
        12 => "yield",
        _ => "",
    }
}

/// What a viewer perceived (`combat_seen.kind`).
pub mod seen {
    /// A windup released: a blow swung, a heal cast (x, y: the actor; dx, dy: its aim).
    pub const RELEASE: u8 = 1;
    /// A blow or missile landed on `target` (amount: damage, for the two involved).
    pub const HIT: u8 = 2;
    /// A blow found only air (the target was out of reach).
    pub const MISS: u8 = 3;
    /// The target's guard took the blow (amount: what still got through).
    pub const BLOCKED: u8 = 4;
    /// The target dodged it.
    pub const DODGED: u8 = 5;
    /// `target` was healed (amount: health restored, for the two involved).
    pub const HEALED: u8 = 6;
    /// `actor` died (target: the killer, if any).
    pub const DEATH: u8 = 7;
    /// For the one who died: `actor` saw it happen.
    pub const WITNESS: u8 = 8;
    /// For the actor only: the rules refused the attempt (`note` says why).
    pub const REFUSED: u8 = 9;
    /// A missile left (x, y: origin; dx, dy: direction; amount: speed in m/s; ms: its longest
    /// flight).
    pub const LAUNCH: u8 = 10;
    /// A missile stopped (x, y: where; target: whom it struck, 0 for nothing).
    pub const IMPACT: u8 = 11;
}

/// The health band others can see at a glance: 4 unhurt, 3 scratched, 2 hurt, 1 badly hurt,
/// 0 barely standing.
pub fn band(hp: f32, max_hp: f32) -> u8 {
    let f = if max_hp > 0.0 { hp / max_hp } else { 0.0 };
    if f >= 0.9 {
        4
    } else if f >= 0.65 {
        3
    } else if f >= 0.4 {
        2
    } else if f >= 0.2 {
        1
    } else {
        0
    }
}

/// A health fraction to draw for a band (the middle of its range).
pub fn band_fraction(band: u8) -> f32 {
    match band {
        4 => 0.95,
        3 => 0.77,
        2 => 0.52,
        1 => 0.3,
        _ => 0.1,
    }
}

/// How a band looks, in words.
pub fn band_words(band: u8) -> &'static str {
    match band {
        4 => "unhurt",
        3 => "scratched",
        2 => "hurt",
        1 => "badly hurt",
        _ => "barely standing",
    }
}

/// A unit vector, if the input has a direction.
pub fn unit(dx: f32, dy: f32) -> Option<(f32, f32)> {
    let n = (dx * dx + dy * dy).sqrt();
    (n.is_finite() && n > 1e-4).then(|| (dx / n, dy / n))
}

/// Where along the segment `a → b` (as a fraction 0..=1) a circle of radius `r` at `c` is
/// first touched, if it is.
pub fn sweep(a: (f32, f32), b: (f32, f32), c: (f32, f32), r: f32) -> Option<f32> {
    let d = (b.0 - a.0, b.1 - a.1);
    let f = (a.0 - c.0, a.1 - c.1);
    let dd = d.0 * d.0 + d.1 * d.1;
    let ff = f.0 * f.0 + f.1 * f.1 - r * r;
    if ff <= 0.0 {
        return Some(0.0);
    }
    if dd < 1e-9 {
        return None;
    }
    let fd = f.0 * d.0 + f.1 * d.1;
    let disc = fd * fd - dd * ff;
    if disc < 0.0 {
        return None;
    }
    let t = (-fd - disc.sqrt()) / dd;
    (0.0..=1.0).contains(&t).then_some(t)
}

/// Whether a guard facing `guard` (unit) covers a blow coming from `from` (unit, from the
/// defender toward where the blow comes from), within `arc_deg` either side of the guard.
pub fn guarded(guard: (f32, f32), from: (f32, f32), arc_deg: f32) -> bool {
    guard.0 * from.0 + guard.1 * from.1 >= arc_deg.to_radians().cos()
}

/// A missile's flight, from the skill script (`<skill>_missile(a)`): metres per second, how
/// far it flies, and its radius (a body's own radius is added when it is swept).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MissileSpec {
    pub speed: f32,
    pub range: f32,
    pub radius: f32,
}

/// The radius of a body for missiles and blows (tiles).
pub fn body_radius(kind: &str) -> f32 {
    match kind {
        "deer" => 0.45,
        "wolf" => 0.4,
        _ => 0.35,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn codes_round_trip() {
        for s in TIMED.iter().chain(["threaten", "tend", "yield"].iter()) {
            assert_eq!(name(code(s)), *s);
        }
        assert_eq!(code("gather"), 0);
        assert_eq!(name(0), "");
    }

    #[test]
    fn bands_cover_the_range() {
        assert_eq!(band(100.0, 100.0), 4);
        assert_eq!(band(70.0, 100.0), 3);
        assert_eq!(band(45.0, 100.0), 2);
        assert_eq!(band(25.0, 100.0), 1);
        assert_eq!(band(5.0, 100.0), 0);
        assert_eq!(band(5.0, 0.0), 0);
        for b in 0..=4u8 {
            assert_eq!(band(band_fraction(b) * 100.0, 100.0), b);
        }
    }

    #[test]
    fn sweep_finds_the_first_touch() {
        // Straight through a circle at x = 5: first touch at x = 4.5.
        let t = sweep((0.0, 0.0), (10.0, 0.0), (5.0, 0.0), 0.5).unwrap();
        assert!((t - 0.45).abs() < 1e-4, "{t}");
        // Passing 1 m beside a 0.5 m circle misses; 0.4 m beside it hits.
        assert!(sweep((0.0, 0.0), (10.0, 0.0), (5.0, 1.0), 0.5).is_none());
        assert!(sweep((0.0, 0.0), (10.0, 0.0), (5.0, 0.4), 0.5).is_some());
        // Behind the start, or beyond the end, is no hit.
        assert!(sweep((0.0, 0.0), (10.0, 0.0), (-2.0, 0.0), 0.5).is_none());
        assert!(sweep((0.0, 0.0), (10.0, 0.0), (11.0, 0.0), 0.5).is_none());
        // Starting inside counts at once.
        assert_eq!(sweep((0.0, 0.0), (1.0, 0.0), (0.1, 0.0), 0.5), Some(0.0));
    }

    #[test]
    fn a_guard_covers_the_front_only() {
        let east = (1.0, 0.0);
        assert!(guarded(east, (1.0, 0.0), 75.0));
        assert!(guarded(east, unit(1.0, 1.0).unwrap(), 75.0));
        assert!(!guarded(east, (0.0, 1.0), 75.0));
        assert!(!guarded(east, (-1.0, 0.0), 75.0));
    }
}
