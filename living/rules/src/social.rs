//! What others see of a skill and what it means to them: `<skill>_shows()` in the skill
//! script (docs/TOWN_LIFE.md). Like the combat shapes, the script declares it and the engine
//! never matches skill names: it picks a primitive by trait.
//!
//! Traits (`look` required, the rest optional flags):
//! - `look`: how it looks, for clients (`gesture`, `turn`, `step`, `play`, `work`, `eat`,
//!   `sleep`, `rest`, ...). Clients draw a skill by name when they know it and by `look`
//!   otherwise.
//! - `faces`: the body turns where it stands to face the skill's target when it starts.
//! - `turn`: turning is all it does: facing its target already (within the `face_slack`
//!   law), there is nothing to do, and it is refused before its rules are asked.
//! - `aside`: a short walk a pace to the side of the creature it targets (`<skill>_dist`);
//!   refused before its rules are asked unless that creature is coming toward the actor.
//! - `record`: each use is kept in `skill_use`, like a combat move (intention to outcome).

use std::collections::BTreeMap;

pub const TRAITS: &[&str] = &["look", "faces", "turn", "aside", "record"];

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Show {
    /// Its presentation code (`act_card.code`, `doing.code`): stable across script installs on
    /// the authority (`Shows::set_codes`); before that, its place among the shown skills in name
    /// order, from 1.
    pub code: u8,
    pub look: String,
    pub faces: bool,
    pub turn: bool,
    pub aside: bool,
    pub record: bool,
}

#[derive(Clone, Debug, Default)]
pub struct Shows {
    by_name: BTreeMap<String, Show>,
}

impl Shows {
    pub fn new(by_name: BTreeMap<String, Show>) -> Self {
        let order: BTreeMap<String, u8> = by_name.keys().enumerate().map(|(i, k)| (k.clone(), (i + 1).min(255) as u8)).collect();
        let mut s = Self { by_name };
        s.set_codes(&order);
        s
    }

    /// Give each shown skill the code `codes` holds for it (0, none, for a skill it lacks).
    pub fn set_codes(&mut self, codes: &BTreeMap<String, u8>) {
        for (name, s) in self.by_name.iter_mut() {
            s.code = codes.get(name).copied().unwrap_or(0);
        }
    }

    pub fn names(&self) -> impl Iterator<Item = &str> {
        self.by_name.keys().map(|k| k.as_str())
    }

    pub fn get(&self, skill: &str) -> Option<&Show> {
        self.by_name.get(skill)
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &Show)> {
        self.by_name.iter().map(|(k, v)| (k.as_str(), v))
    }

    pub fn code(&self, skill: &str) -> u8 {
        self.get(skill).map_or(0, |s| s.code)
    }

    pub fn faces(&self, skill: &str) -> bool {
        self.get(skill).is_some_and(|s| s.faces)
    }

    pub fn aside(&self, skill: &str) -> bool {
        self.get(skill).is_some_and(|s| s.aside)
    }

    pub fn record(&self, skill: &str) -> bool {
        self.get(skill).is_some_and(|s| s.record)
    }
}

/// How far a body facing `heading` would have to turn to face `to` from `from` (0..pi).
pub fn bearing(from: (f32, f32), heading: f32, to: (f32, f32)) -> f32 {
    let (dx, dy) = (to.0 - from.0, to.1 - from.1);
    if dx.abs() < 1e-4 && dy.abs() < 1e-4 {
        return 0.0;
    }
    crate::steer::wrap(dy.atan2(dx) - heading).abs()
}

/// How fast something at `at` moving with velocity `v` closes on `me` (tiles/s; negative when
/// it moves away).
pub fn closing(me: (f32, f32), at: (f32, f32), v: (f32, f32)) -> f32 {
    let (dx, dy) = (me.0 - at.0, me.1 - at.1);
    let d = (dx * dx + dy * dy).sqrt();
    if d < 1e-4 {
        return 0.0;
    }
    (v.0 * dx + v.1 * dy) / d
}

/// Where to step to let someone pass: a pace of `dist` to the side of their path that I am
/// already on (`me` beside the line from `at` along `v`), or away from them when they stand.
pub fn aside_point(me: (f32, f32), at: (f32, f32), v: (f32, f32), dist: f32) -> [(f32, f32); 2] {
    let speed = (v.0 * v.0 + v.1 * v.1).sqrt();
    let dir = if speed > 0.1 { (v.0 / speed, v.1 / speed) } else {
        let (dx, dy) = (me.0 - at.0, me.1 - at.1);
        let d = (dx * dx + dy * dy).sqrt().max(1e-4);
        (-dx / d, -dy / d)
    };
    // Left of their way is (dy, -dx) turned; pick the side I am on first.
    let side = (-dir.1, dir.0);
    let on = (me.0 - at.0) * side.0 + (me.1 - at.1) * side.1;
    let s = if on >= 0.0 { 1.0 } else { -1.0 };
    [(me.0 + side.0 * dist * s, me.1 + side.1 * dist * s), (me.0 - side.0 * dist * s, me.1 - side.1 * dist * s)]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bearing_closing_and_aside() {
        // Facing east, something to the north (y grows south) is a quarter turn away.
        assert!((bearing((0.0, 0.0), 0.0, (0.0, -5.0)) - std::f32::consts::FRAC_PI_2).abs() < 1e-4);
        assert!(bearing((0.0, 0.0), 0.0, (5.0, 0.0)) < 1e-4);
        // Someone walking west toward me from the east closes at their speed.
        assert!((closing((0.0, 0.0), (5.0, 0.0), (-2.0, 0.0)) - 2.0).abs() < 1e-4);
        assert!(closing((0.0, 0.0), (5.0, 0.0), (2.0, 0.0)) < 0.0);
        // I stand a little south of their westward path: I step further south first.
        let [first, other] = aside_point((0.0, 0.3), (5.0, 0.0), (-2.0, 0.0), 1.2);
        assert!(first.1 > 1.0 && other.1 < -0.5, "{first:?} {other:?}");
    }

    #[test]
    fn codes_follow_name_order() {
        let mut m = BTreeMap::new();
        m.insert("wave".to_string(), Show { look: "gesture".into(), faces: true, ..Default::default() });
        m.insert("nod".to_string(), Show { look: "gesture".into(), ..Default::default() });
        let s = Shows::new(m);
        assert_eq!((s.code("nod"), s.code("wave"), s.code("gather")), (1, 2, 0));
        assert!(s.faces("wave") && !s.faces("nod"));
    }
}
