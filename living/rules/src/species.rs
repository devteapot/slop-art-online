//! Species profiles: what a body can do and how its mind is paced. Data, not code —
//! the same pipeline serves people and animals (living/seeds/species.json).

use serde::Deserialize;
use std::collections::BTreeMap;

#[derive(Clone, Debug, Deserialize)]
pub struct Signal {
    pub sound: String,
    pub range: f32,
    pub salience: f32,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Cognition {
    pub think_min_s: u64,
    pub reflect_s: u64,
    pub consolidate_threshold: f32,
    pub max_nodes: usize,
    /// Minimum seconds between consolidations (unless experiences pile up).
    #[serde(default)]
    pub consolidate_min_s: u64,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Species {
    /// Allowed skills (`None` = every skill in the catalog).
    pub skills: Option<Vec<String>>,
    pub speaks: bool,
    #[serde(default)]
    pub signals: BTreeMap<String, Signal>,
    #[serde(default)]
    pub names: Vec<String>,
    #[serde(default)]
    pub temperament: BTreeMap<String, [f32; 2]>,
    #[serde(default)]
    pub nature: String,
    /// What the body eats, as the creature knows it (shown in its scene).
    #[serde(default)]
    pub eats: String,
    /// Lifespan and stages (see `life`).
    #[serde(default)]
    pub life: crate::life::Life,
    pub cognition: Cognition,
    /// How many of them a new world places together (a herd, a pack); 1 = alone.
    #[serde(default = "one")]
    pub group: u32,
    /// Kinds of creatures this body senses farther than it sees (none = sight only).
    #[serde(default)]
    pub scent: Option<Scent>,
}

/// Smell: some kinds of creatures are sensed within `radius` tiles, coarsely (kind, rough
/// direction and distance), even beyond sight (a wolf smells deer and other wolves).
#[derive(Clone, Debug, Default, Deserialize, PartialEq)]
pub struct Scent {
    pub radius: f32,
    #[serde(default)]
    pub kinds: Vec<String>,
}

impl Scent {
    /// Whether a creature of `kind` (a selector's `creature` = any kind smelled) at `dist`
    /// can be smelled.
    pub fn reaches(&self, kind: &str, dist: f32) -> bool {
        dist <= self.radius && (kind == "creature" && !self.kinds.is_empty() || self.kinds.iter().any(|k| k == kind))
    }
}

/// Scene key under which a body's perception lists creatures smelled but not seen.
pub const SMELLED: &str = "you smell (out of sight)";

/// Which creature a `nearest` selector for `kind` (`creature` = any) picks: the nearest one
/// seen, else, for a body with a scent for that kind, the nearest one smelled within the
/// scent radius. `seen` and `smelled` are `(id, kind, dist)` nearest first; `smelled` is
/// asked for only when nothing seen will do; `ok` applies the selector's other filters
/// (relations). Returns the id and whether it was only smelled.
pub fn pick_nearest<K: AsRef<str>>(
    kind: &str,
    seen: &[(u32, K, f32)],
    scent: Option<&Scent>,
    smelled: impl FnOnce() -> Vec<(u32, K, f32)>,
    mut ok: impl FnMut(u32) -> bool,
) -> Option<(u32, bool)> {
    let matches = |k: &str| kind == "creature" || k == kind;
    if let Some(c) = seen.iter().find(|c| matches(c.1.as_ref()) && ok(c.0)) {
        return Some((c.0, false));
    }
    let scent = scent.filter(|s| s.reaches(kind, s.radius))?;
    smelled().iter().find(|c| matches(c.1.as_ref()) && scent.reaches(c.1.as_ref(), c.2) && ok(c.0)).map(|c| (c.0, true))
}

fn one() -> u32 {
    1
}

impl Species {
    pub fn allows(&self, skill: &str) -> bool {
        self.skills.as_ref().map_or(true, |s| s.iter().any(|x| x == skill))
    }
}

pub fn parse(json: &str) -> Result<BTreeMap<String, Species>, String> {
    serde_json::from_str(json).map_err(|e| format!("species: {e}"))
}

/// Skill reference limited to what this body can do.
pub fn skills_help(sp: &Species) -> String {
    skills_help_io(sp, &|_| None)
}

/// Skill reference limited to what this body can do, with what each skill takes and gives.
pub fn skills_help_io(sp: &Species, io: crate::catalog::SkillIo) -> String {
    crate::catalog::SKILLS
        .iter()
        .filter(|s| sp.allows(s.name) && (sp.skills.is_some() || s.name != "graze"))
        .filter(|s| s.name != "signal" || !sp.signals.is_empty())
        .map(|s| crate::catalog::skill_line(s, if s.name == "signal" { "item: signal name" } else { "item" }, io))
        .collect::<Vec<_>>()
        .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scent_is_optional_species_data() {
        let species = parse(include_str!("../../seeds/species.json")).unwrap();
        assert!(species["person"].scent.is_none());
        let wolf = species["wolf"].scent.as_ref().expect("wolves smell");
        assert!(wolf.kinds.iter().any(|k| k == "deer") && wolf.radius > 20.0);
        assert!(species["deer"].scent.as_ref().is_some_and(|s| s.kinds == ["wolf"]));
        let bare = r#"{"x": {"skills": null, "speaks": false, "cognition": {"think_min_s": 1, "reflect_s": 1, "consolidate_threshold": 1.0, "max_nodes": 8}}}"#;
        assert!(parse(bare).unwrap()["x"].scent.is_none());
        let with = bare.replace("\"speaks\": false", "\"speaks\": false, \"scent\": {\"radius\": 40, \"kinds\": [\"deer\"]}");
        assert_eq!(parse(&with).unwrap()["x"].scent, Some(Scent { radius: 40.0, kinds: vec!["deer".into()] }));
    }

    #[test]
    fn nearest_prefers_sight_then_smell_within_the_radius() {
        let scent = Scent { radius: 60.0, kinds: vec!["deer".into(), "wolf".into()] };
        let seen = [(1, "person", 3.0), (2, "deer", 8.0)];
        let far = || vec![(3, "deer", 30.0), (4, "deer", 50.0)];
        // A deer in sight wins over a nearer smelled one, and smell is not consulted.
        assert_eq!(pick_nearest("deer", &seen, Some(&scent), || panic!("smell asked"), |_| true), Some((2, false)));
        // None seen: the nearest smelled one.
        assert_eq!(pick_nearest("deer", &seen[..1], Some(&scent), far, |_| true), Some((3, true)));
        // Filters apply to smelled ones too.
        assert_eq!(pick_nearest("deer", &seen[..1], Some(&scent), far, |id| id != 3), Some((4, true)));
        // Beyond the radius, of a kind not smelled, or without a scent: nothing.
        assert_eq!(pick_nearest("deer", &seen[..1], Some(&scent), || vec![(5, "deer", 61.0)], |_| true), None);
        assert_eq!(pick_nearest("person", &[], Some(&scent), || vec![(6, "person", 20.0)], |_| true), None);
        assert_eq!(pick_nearest("deer", &seen[..1], None, far, |_| true), None);
        // Any creature: only the kinds smelled.
        assert_eq!(pick_nearest("creature", &[], Some(&scent), || vec![(6, "person", 20.0), (7, "wolf", 40.0)], |_| true), Some((7, true)));
    }
}
