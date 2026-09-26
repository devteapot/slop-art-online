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
    crate::catalog::SKILLS
        .iter()
        .filter(|s| sp.allows(s.name) && (sp.skills.is_some() || s.name != "graze"))
        .filter(|s| s.name != "signal" || !sp.signals.is_empty())
        .map(|s| {
            let mut args = Vec::new();
            if s.needs_target {
                args.push("target");
            }
            if s.needs_item {
                args.push(if s.name == "signal" { "item: signal name" } else { "item" });
            }
            format!("- {}({}): {}", s.name, args.join(", "), s.help)
        })
        .collect::<Vec<_>>()
        .join("\n")
}
