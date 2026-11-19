//! Model prices that are not committed. TypeSafe counts its pricing as Confidential Information
//! (docs/STORE.md, "Model terms"), so Jev's price lives in a local, untracked file:
//! - `LIVING_PRICES`, a path; else
//! - `living/configs/prices.local.json` under the root (gitignored); else
//! - `~/.config/slop-living/prices.local.json`, shared by every checkout on a machine.
//!
//! The shape is `living/configs/prices.example.json`. With no file, every price is unknown and a
//! journal's `cost_usd` is null, never 0. A file that exists but does not parse is an error.
use anyhow::{Context, Result};
use serde::Deserialize;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, Default, Deserialize)]
pub struct ModelPrice {
    /// $ per million input tokens.
    #[serde(default)]
    pub input_usd_per_m: Option<f64>,
}

#[derive(Clone, Debug, Default, Deserialize)]
struct PriceFile {
    #[serde(default)]
    models: BTreeMap<String, ModelPrice>,
}

#[derive(Clone, Debug, Default)]
pub struct Prices {
    models: BTreeMap<String, ModelPrice>,
    /// Where the prices came from; `None` when no file was found.
    pub source: Option<PathBuf>,
}

impl Prices {
    pub fn load(root: &Path) -> Result<Self> {
        let candidates: Vec<PathBuf> = match std::env::var("LIVING_PRICES") {
            Ok(p) if !p.is_empty() => vec![PathBuf::from(p)],
            _ => {
                let mut v = vec![root.join("living/configs/prices.local.json")];
                if let Some(home) = std::env::var_os("HOME") {
                    v.push(PathBuf::from(home).join(".config/slop-living/prices.local.json"));
                }
                v
            }
        };
        for path in candidates {
            match std::fs::read_to_string(&path) {
                Ok(text) => return Self::parse(&text, Some(path.clone())).with_context(|| format!("parse {}", path.display())),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
                Err(e) => return Err(e).with_context(|| format!("read {}", path.display())),
            }
        }
        Ok(Self::default())
    }

    fn parse(text: &str, source: Option<PathBuf>) -> Result<Self> {
        let f: PriceFile = serde_json::from_str(text)?;
        Ok(Self { models: f.models, source })
    }

    pub fn input_usd_per_m(&self, model: &str) -> Option<f64> {
        self.models.get(model).and_then(|p| p.input_usd_per_m).filter(|p| p.is_finite() && *p >= 0.0)
    }

    /// The input-only cost of a call, or `None` when the tokens or the price are unknown.
    pub fn input_cost(&self, model: &str, input_tokens: Option<u64>) -> Option<f64> {
        Some(input_tokens? as f64 * self.input_usd_per_m(model)? / 1e6)
    }

    /// One log line: where the prices came from, without the prices.
    pub fn describe(&self, model: &str) -> String {
        match (&self.source, self.input_usd_per_m(model)) {
            (Some(p), Some(_)) => format!("{model} priced from {}", p.display()),
            (Some(p), None) => format!("{model} has no price in {}: its cost is unknown", p.display()),
            (None, _) => format!("no prices file (living/configs/prices.example.json): {model}'s cost is unknown"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unknown_without_a_file_never_zero() {
        let p = Prices::default();
        assert_eq!(p.input_usd_per_m("jev-1.14.0"), None);
        assert_eq!(p.input_cost("jev-1.14.0", Some(1500)), None);
    }

    #[test]
    fn a_price_gives_a_cost_and_the_example_has_none() {
        let p = Prices::parse(r#"{"models": {"m": {"input_usd_per_m": 2.0}}}"#, None).unwrap();
        assert_eq!(p.input_cost("m", Some(500_000)), Some(1.0));
        assert_eq!(p.input_cost("m", None), None, "unknown tokens");
        assert_eq!(p.input_cost("other", Some(10)), None, "unlisted model");
        let example = std::fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../configs/prices.example.json")).unwrap();
        let e = Prices::parse(&example, None).unwrap();
        assert!(e.models.contains_key("jev-1.14.0"), "the example names the models it prices");
        assert!(e.models.values().all(|m| m.input_usd_per_m.is_none()), "the committed example carries no price");
    }

    #[test]
    fn a_broken_file_is_an_error() {
        assert!(Prices::parse("{not json", None).is_err());
    }

    #[test]
    fn the_committed_configs_carry_no_price() {
        for f in ["rethink.json", "judgments.json"] {
            let t = std::fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../configs").join(f)).unwrap();
            assert!(!t.contains("usd"), "{f} carries a price");
        }
    }
}
