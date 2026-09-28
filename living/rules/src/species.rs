//! Species profiles: what a body can do and how its mind is paced. Data, not code —
//! the same pipeline serves people and animals (living/seeds/species.json).

use serde::Deserialize;
use std::collections::BTreeMap;

#[derive(Clone, Debug, Deserialize)]
pub struct Signal {
    pub sound: String,
    pub range: f32,
    pub salience: f32,
    /// How one's own kind hears it, when "{name} makes {sound}" would mislead
    /// (`{name}` is the signaller), e.g. "{name}, a baby, is crying".
    #[serde(default)]
    pub heard: String,
    /// Only those who care about the signaller (parents, siblings, anyone with feelings
    /// about them) are prompted to think by it; everyone in range still hears it.
    #[serde(default)]
    pub kin_only: bool,
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
    /// The wilds beyond the map: newcomers of this kind arrive when few are left (none = never).
    #[serde(default)]
    pub migrate: Option<Migrate>,
}

/// A floor under a population, supplied by the world beyond the map: while fewer than `below`
/// of the kind live, a group of `group` grown ones comes in at a map edge on fitting ground,
/// at most once every `every_min` real minutes. `text` is the chronicle line (`{dir}` is the
/// side they came from).
#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct Migrate {
    pub below: u32,
    pub group: u32,
    pub every_min: f32,
    #[serde(default)]
    pub text: String,
}

impl Migrate {
    /// Whether a group comes in now: few enough alive, and none came within the interval
    /// (`last_ms`: when the last newcomers of the kind arrived, or the world began).
    pub fn due(&self, alive: u32, last_ms: u64, now_ms: u64) -> bool {
        alive < self.below && now_ms.saturating_sub(last_ms) as f32 >= self.every_min * 60_000.0
    }

    /// The chronicle line for newcomers of `kind` from `dir`.
    pub fn story(&self, kind: &str, dir: &str) -> String {
        if self.text.is_empty() {
            format!("Some {kind} came in from the {dir}")
        } else {
            self.text.replace("{dir}", dir)
        }
    }
}

/// Where newcomers from beyond a `w`×`h` map come in: a tile on fitting `ground` within a few
/// tiles of a random edge (sides without such ground, like a sea coast, are never chosen), and
/// the side it is on. `rand` gives uniform numbers in [0, 1).
pub fn edge_spot(w: u32, h: u32, ground: impl Fn(i32, i32) -> bool, mut rand: impl FnMut() -> f32) -> Option<((f32, f32), &'static str)> {
    let (w, h) = (w as i32, h as i32);
    let mut pick = |n: i32| ((rand() * n as f32) as i32).clamp(0, n - 1);
    // Close to the edge first; deeper in only if the edges are poor in fitting ground.
    for (tries, depth) in [(400, 12), (400, 40)] {
        for _ in 0..tries {
            let side = pick(4);
            let d = 1 + pick(depth);
            let along = 1 + pick(if side < 2 { w - 2 } else { h - 2 });
            let (x, y, dir) = match side {
                0 => (along, d, "north"),
                1 => (along, h - 1 - d, "south"),
                2 => (d, along, "west"),
                _ => (w - 1 - d, along, "east"),
            };
            if ground(x, y) {
                return Some(((x as f32 + 0.5, y as f32 + 0.5), dir));
            }
        }
    }
    None
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
    fn migration_is_an_optional_floor() {
        let species = parse(include_str!("../../seeds/species.json")).unwrap();
        assert!(species["person"].migrate.is_none());
        let deer = species["deer"].migrate.clone().expect("deer come in from the wilds");
        let wolf = species["wolf"].migrate.clone().expect("wolves come in from the wilds");
        // A group big enough to breed, arriving only while the population is low.
        assert!(deer.group >= 2 && wolf.group >= 2 && deer.below > deer.group / 2);
        let min = 60_000u64;
        let every = (deer.every_min * 60_000.0) as u64;
        assert!(deer.due(deer.below - 1, 0, every));
        assert!(!deer.due(deer.below, 0, every), "not while the population is healthy");
        assert!(!deer.due(0, every, every + min), "at most once per interval");
        assert!(deer.due(0, every, 2 * every));
        assert!(deer.story("deer", "west").contains("west"));
        let bare = Migrate { below: 3, group: 3, every_min: 30.0, text: String::new() };
        assert_eq!(bare.story("wolf", "north"), "Some wolf came in from the north");
    }

    #[test]
    fn newcomers_arrive_at_an_edge_on_fitting_ground() {
        let mut seed = 7u64;
        let mut rand = move || {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            (seed >> 40) as f32 / (1u64 << 24) as f32
        };
        // A 64×64 map whose east half is sea: newcomers never come from the east.
        let land = |x: i32, _y: i32| x < 32;
        for _ in 0..50 {
            let ((x, y), dir) = edge_spot(64, 64, land, &mut rand).expect("land along three sides");
            assert!(land(x as i32, y as i32));
            assert_ne!(dir, "east");
            let edge = match dir {
                "north" => y,
                "south" => 64.0 - y,
                "west" => x,
                _ => unreachable!(),
            };
            assert!(edge <= 13.0, "near the edge when the edge has fitting ground");
        }
        // Only a pocket 17-27 tiles in from the south edge: found on the deeper pass.
        let pocket = |x: i32, y: i32| (60..68).contains(&x) && (100..=110).contains(&y);
        assert!(edge_spot(128, 128, pocket, &mut rand).is_some_and(|(_, d)| d == "south"));
        assert!(edge_spot(64, 64, |_, _| false, &mut rand).is_none());
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
