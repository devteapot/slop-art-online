//! Combat vocabulary and geometry shared by the authority (which rules) and clients (which
//! only present). Numbers that balance combat (windups, damage, costs, cooldowns, missile
//! speeds) and what each combat skill is (its `<skill>_combat()` shape) live in the Rhai skill
//! script, not here; this module holds the shape's vocabulary, the perception codes clients
//! and the authority agree on, and the pure geometry both sides evaluate the same way.
//!
//! The six starter skills (docs/GAME_BRIEF.md, 2026-11-09) and the older force skills share
//! one timing model: a **windup** (the skill's `_duration`, when others can see it coming),
//! the **release** (effects apply, or a missile leaves), a **recovery** (no other combat move
//! but a dodge) and a **cooldown** counted from the start. See docs/COMBAT.md.

/// How a player aims a combat skill, and which of the engine's primitives it is.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Aim {
    /// Not aimed by a player (or aimed by its graph leaf alone).
    #[default]
    None,
    /// A creature within reach and sight.
    Creature,
    /// Yourself (no target) or a creature that is not fighting you.
    SelfOrAlly,
    /// A ground point: a skillshot (the skill must have a `<skill>_missile`).
    Point,
    /// A held guard facing the aimed point, taking part of a blow from the front.
    Facing,
    /// A dash toward the aimed point (or away from a threat); what lands during it misses.
    Dash,
}

impl Aim {
    pub fn parse(s: &str) -> Option<Aim> {
        Some(match s {
            "" | "none" => Aim::None,
            "creature" => Aim::Creature,
            "self_or_ally" => Aim::SelfOrAlly,
            "point" => Aim::Point,
            "facing" => Aim::Facing,
            "dash" => Aim::Dash,
            _ => return None,
        })
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Aim::None => "none",
            Aim::Creature => "creature",
            Aim::SelfOrAlly => "self_or_ally",
            Aim::Point => "point",
            Aim::Facing => "facing",
            Aim::Dash => "dash",
        }
    }
}

/// What a combat skill is, as its script declares it (`<skill>_combat()`, read once when the
/// script compiles). The engine's primitives (a dash, a held guard, a missile, a melee blow
/// meant to hurt or kill) are chosen by these traits, never by the skill's name.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Shape {
    /// Presentation code (`fighter.act`, `combat_seen.skill`, `skill_card.code`): the skill's
    /// place among the script's combat skills in name order, from 1; 0 is none.
    pub code: u8,
    pub aim: Aim,
    /// Combat timing (one windup at a time, recovery, cooldown, `fighter`, `skill_use`).
    pub timed: bool,
    /// A player's movement waits while its windup runs.
    pub rooted: bool,
    /// Aimed against a creature: that creature is its victim, and sees it coming.
    pub hostile: bool,
    /// Takes the body back from a deliberate act.
    pub reflex: bool,
    /// Behavior of the moment: it belongs in a graph, not in a one-off act.
    pub real_time: bool,
    /// A blow in reach meant to hurt or to kill (its item), carrying the rules' `lunge(kind)`:
    /// out of reach by more when it releases, it misses.
    pub melee: bool,
    /// The rules are weighed before walking into reach (no closing in on someone the rules
    /// won't let you strike).
    pub closes_in: bool,
    /// A menace: made once per target in a while, and the target perceives it as a threat.
    pub menace: bool,
    /// A use of force: whether its actor has yielded is weighed.
    pub force: bool,
    /// The rules weigh the target before it: whether they yielded, and what a predator dares.
    pub dares: bool,
    /// It looses a missile (the script defines `<skill>_missile`).
    pub missile: bool,
    /// A held guard: the longest a player holds it (ms), how far either side of where it faces
    /// it covers (degrees), and the share of a covered blow that still lands.
    pub hold_ms: u32,
    pub arc: f32,
    pub takes: f32,
    /// The skill whose knack gene makes one good at it (itself by default).
    pub knack: String,
    /// What a player's bar shows as missing before the rules are asked: items carried, and
    /// techniques known. The skill's `_check` stays the rule.
    pub needs: Vec<String>,
    pub knows: Vec<String>,
}

/// Skills that are not combat skills but are behavior of the moment (walking, resting): they
/// belong in a graph, not in an act. Combat skills say so themselves (`Shape::real_time`).
pub const MOVES: &[&str] = &["wander", "flee", "follow", "wait", "sleep", "rest", "graze"];

/// The combat skills a script declares, by name (the order their codes follow), and its
/// skill bar.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Shapes {
    by_name: std::collections::BTreeMap<String, Shape>,
    names: Vec<String>,
    bar: Vec<String>,
}

impl Shapes {
    /// From each skill's declared shape (codes are given here) and the bar's skills in order.
    pub fn new(shapes: std::collections::BTreeMap<String, Shape>, bar: Vec<String>) -> Result<Shapes, String> {
        if shapes.len() > 254 {
            return Err("at most 254 combat skills".into());
        }
        for s in &bar {
            match shapes.get(s) {
                None => return Err(format!("skill_bar: `{s}` has no `{s}_combat()`")),
                Some(sh) if sh.aim == Aim::None => return Err(format!("skill_bar: `{s}` has no aim")),
                _ => {}
            }
        }
        let mut by_name = shapes;
        let names: Vec<String> = by_name.keys().cloned().collect();
        for (i, sh) in by_name.values_mut().enumerate() {
            sh.code = i as u8 + 1;
        }
        Ok(Shapes { by_name, names, bar })
    }

    pub fn get(&self, skill: &str) -> Option<&Shape> {
        self.by_name.get(skill)
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &Shape)> {
        self.by_name.iter().map(|(k, v)| (k.as_str(), v))
    }

    /// The skills on the bar, in bar order.
    pub fn bar(&self) -> &[String] {
        &self.bar
    }

    pub fn on_bar(&self, skill: &str) -> bool {
        self.bar.iter().any(|s| s == skill)
    }

    pub fn timed(&self, skill: &str) -> bool {
        self.get(skill).is_some_and(|s| s.timed)
    }

    /// Presentation code of a skill; 0 for none or a skill that is not a combat skill.
    pub fn code(&self, skill: &str) -> u8 {
        self.get(skill).map_or(0, |s| s.code)
    }

    /// The skill a presentation code names ("" for none).
    pub fn name(&self, code: u8) -> &str {
        code.checked_sub(1).and_then(|i| self.names.get(i as usize)).map_or("", |s| s.as_str())
    }

    /// Ongoing or real-time behavior: it belongs in a graph, not in a one-off act.
    pub fn real_time(&self, skill: &str) -> bool {
        MOVES.contains(&skill) || self.get(skill).is_some_and(|s| s.real_time)
    }

    /// A reflex in a graph takes the body back from a deliberate act (fleeing, or a combat
    /// skill that says so).
    pub fn reflex(&self, skill: &str) -> bool {
        skill == "flee" || self.get(skill).is_some_and(|s| s.reflex)
    }

    /// The skill whose knack gene serves this one.
    pub fn knack<'a>(&'a self, skill: &'a str) -> &'a str {
        self.get(skill).map(|s| s.knack.as_str()).filter(|k| !k.is_empty()).unwrap_or(skill)
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
    fn codes_follow_names_and_round_trip() {
        let mut m = std::collections::BTreeMap::new();
        for n in ["strike", "block", "attack"] {
            m.insert(n.to_string(), Shape { aim: Aim::Creature, real_time: n != "attack", ..Default::default() });
        }
        let s = Shapes::new(m, vec!["strike".into()]).unwrap();
        assert_eq!((s.code("attack"), s.code("block"), s.code("strike")), (1, 2, 3));
        for n in ["strike", "block", "attack"] {
            assert_eq!(s.name(s.code(n)), n);
        }
        assert_eq!((s.code("gather"), s.name(0), s.name(9)), (0, "", ""));
        assert!(s.real_time("strike") && !s.real_time("attack") && s.real_time("wander") && !s.real_time("give"));
        assert_eq!(s.knack("strike"), "strike");
        let mut m = std::collections::BTreeMap::new();
        m.insert("heal".to_string(), Shape::default());
        assert!(Shapes::new(m, vec!["heal".into()]).unwrap_err().contains("no aim"));
        assert!(Shapes::new(Default::default(), vec!["fly".into()]).unwrap_err().contains("fly_combat"));
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
