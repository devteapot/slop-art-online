//! Heredity and practice: what a body is born with and what it becomes by doing.
//!
//! Genes are an open set of named values, so every species and every skill has them without
//! a fixed list: temperament traits (`trait:<name>`, 0..100) and factors around 1.0 for the
//! body (`speed`, `strength`, `endurance`, `vitality`) and for each skill (`knack:<skill>`).
//! A child takes the midpoint of its parents, pulled a little toward its species' norm, plus
//! a mutation that is usually small and occasionally large in either direction: talents (and
//! weaknesses) arise by chance and spread only if they help their bearers live and breed.
//! Practice is separate and not inherited: each use of a skill makes one a little better at
//! it, with diminishing returns.

use std::collections::BTreeMap;

use crate::graph::{Desire, Node, Weight, PLAN_ROUTINE};

pub type Genes = BTreeMap<String, f32>;

/// Body genes every creature has.
pub const BODY: [&str; 4] = ["speed", "strength", "endurance", "vitality"];
/// Person temperament traits (animals take theirs from their species).
pub const PERSON_TRAITS: [&str; 8] = ["caution", "sociability", "empathy", "curiosity", "ambition", "introspection", "temper", "nurture"];
/// Skills whose pace is set by something else (walking speed, the body's needs, a signal).
const UNSKILLED: [&str; 9] = ["wait", "sleep", "rest", "eat", "signal", "goto", "follow", "wander", "flee"];

/// Chance that a gene mutates strongly (either way) in a birth.
const LARGE_MUTATION: f32 = 0.04;

fn is_trait(name: &str) -> bool {
    name.starts_with("trait:")
}

/// A standard normal sample from uniform draws in [0, 1).
fn normal(u: &mut dyn FnMut() -> f32) -> f32 {
    let a = u().max(1e-6);
    let b = u();
    (-2.0 * a.ln()).sqrt() * (std::f32::consts::TAU * b).cos()
}

/// A mutation of typical size `scale`: usually small, rarely six times larger.
fn mutation(u: &mut dyn FnMut() -> f32, scale: f32) -> f32 {
    let n = normal(u) * scale;
    if u() < LARGE_MUTATION {
        n * 6.0
    } else {
        n
    }
}

fn clamp(name: &str, v: f32) -> f32 {
    if is_trait(name) {
        v.clamp(0.0, 100.0)
    } else {
        v.clamp(0.4, 2.5)
    }
}

/// A founder's genes: temperament drawn within its species' ranges, body and knacks near 1.0.
pub fn founder(temperament: &BTreeMap<String, [f32; 2]>, skills: &[String], u: &mut dyn FnMut() -> f32) -> Genes {
    let mut g = Genes::new();
    for (k, [lo, hi]) in temperament {
        g.insert(format!("trait:{k}"), (lo + (hi - lo) * u()).round());
    }
    for k in BODY.iter().map(|s| s.to_string()).chain(skills.iter().filter(|s| !UNSKILLED.contains(&s.as_str())).map(|s| format!("knack:{s}"))) {
        let v = 1.0 + mutation(u, 0.06);
        g.insert(k.clone(), clamp(&k, v));
    }
    g
}

/// Person temperament ranges (animals have theirs in their species).
pub fn person_temperament() -> BTreeMap<String, [f32; 2]> {
    PERSON_TRAITS.iter().map(|t| (t.to_string(), [10.0, 90.0])).collect()
}

/// A child's genes from its parents'.
pub fn inherit(a: &Genes, b: &Genes, u: &mut dyn FnMut() -> f32) -> Genes {
    let mut g = Genes::new();
    let names: std::collections::BTreeSet<&String> = a.keys().chain(b.keys()).collect();
    for name in names {
        let mid = match (a.get(name), b.get(name)) {
            (Some(x), Some(y)) => (x + y) / 2.0,
            (Some(x), None) | (None, Some(x)) => *x,
            (None, None) => continue,
        };
        let (norm, scale) = if is_trait(name) { (50.0, 6.0) } else { (1.0, 0.05) };
        let v = mid + 0.1 * (norm - mid) + mutation(u, scale);
        g.insert(name.clone(), clamp(name, v));
    }
    g
}

/// A gene's value (1.0 for a missing factor, 50 for a missing trait).
pub fn gene(g: &Genes, name: &str) -> f32 {
    g.get(name).copied().unwrap_or(if is_trait(name) { 50.0 } else { 1.0 })
}

/// Whether a skill improves with a knack and practice.
pub fn is_skilled(skill: &str) -> bool {
    !UNSKILLED.contains(&skill)
}

/// How much better practice makes one at a skill after `uses` successful uses: up to 60%.
pub fn practice_factor(uses: u32) -> f32 {
    1.0 + 0.6 * (1.0 - (-(uses as f32) / 60.0).exp())
}

/// How good a body is at a skill: its inborn knack times its practice.
pub fn skill_factor(g: &Genes, practice: &BTreeMap<String, u32>, skill: &str) -> f32 {
    if UNSKILLED.contains(&skill) {
        return 1.0;
    }
    gene(g, &format!("knack:{skill}")) * practice_factor(practice.get(skill).copied().unwrap_or(0))
}

/// Temperament for a persona: trait name → 0..100.
pub fn temperament(g: &Genes) -> BTreeMap<String, f32> {
    g.iter().filter_map(|(k, v)| k.strip_prefix("trait:").map(|t| (t.to_string(), v.round()))).collect()
}

/// What one can tell about one's own body: the genes far enough from the usual to notice.
pub fn notable(g: &Genes) -> Vec<String> {
    let mut out = Vec::new();
    for (k, v) in g {
        if is_trait(k) {
            continue;
        }
        let word = match k.as_str() {
            "speed" => ("unusually fast", "slow on your feet"),
            "strength" => ("unusually strong", "weak for your kind"),
            "endurance" => ("tireless", "quick to tire"),
            "vitality" => ("hardy", "frail"),
            _ => ("", ""),
        };
        let skill = k.strip_prefix("knack:");
        if *v >= 1.2 {
            out.push(match skill {
                Some(s) => format!("a natural gift for {s}"),
                None => word.0.to_string(),
            });
        } else if *v <= 0.8 {
            out.push(match skill {
                Some(s) => format!("clumsy at {s}"),
                None => word.1.to_string(),
            });
        }
    }
    out
}

/// How practised one is at a skill, in words.
pub fn practised(uses: u32) -> &'static str {
    match uses {
        0..=9 => "a beginner",
        10..=49 => "practised",
        50..=149 => "skilled",
        _ => "a master",
    }
}

/// The ways a young one grows into: a parent's top level with the current plan dropped and
/// each weight varied a little (occasionally a lot), so ways of life also vary and evolve.
pub fn vary_ways(top: &Node, u: &mut dyn FnMut() -> f32) -> Option<Node> {
    let Node::Desires(ds) = top else { return None };
    let vary = |x: f32, u: &mut dyn FnMut() -> f32| if x == 0.0 { 0.0 } else { x * (1.0 + mutation(u, 0.08)) };
    let out: Vec<Desire> = ds
        .iter()
        .filter(|d| !matches!(&*d.body, Node::Routine(r) if r.eq_ignore_ascii_case(PLAN_ROUTINE)))
        .map(|d| {
            let w = &d.weight;
            let weight = Weight {
                base: w.base + mutation(u, 0.05),
                hunger: vary(w.hunger, u),
                tired: vary(w.tired, u),
                hurt: vary(w.hurt, u),
                night: vary(w.night, u),
                day: vary(w.day, u),
                threatened: vary(w.threatened, u),
                alone: vary(w.alone, u),
                company: vary(w.company, u),
                winter: vary(w.winter, u),
                longing: vary(w.longing, u),
                courted: vary(w.courted, u),
                believes: w.believes.clone(),
            };
            Desire { want: d.want.clone(), weight, body: d.body.clone() }
        })
        .collect();
    Some(Node::Desires(out))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rng(seed: u64) -> impl FnMut() -> f32 {
        let mut s = seed;
        move || {
            s = s.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((s >> 40) as f32) / (1u64 << 24) as f32
        }
    }

    #[test]
    fn children_vary_around_their_parents_with_rare_outliers_both_ways() {
        let mut u = rng(7);
        let low: Genes = [("strength".to_string(), 0.7)].into();
        let high: Genes = [("strength".to_string(), 1.3)].into();
        let kids_low: Vec<f32> = (0..4000).map(|_| gene(&inherit(&low, &low, &mut u), "strength")).collect();
        let kids_high: Vec<f32> = (0..4000).map(|_| gene(&inherit(&high, &high, &mut u), "strength")).collect();
        let mean = |v: &[f32]| v.iter().sum::<f32>() / v.len() as f32;
        // Mostly like their parents (pulled a little toward the norm)...
        assert!((mean(&kids_low) - 0.73).abs() < 0.02, "{}", mean(&kids_low));
        assert!((mean(&kids_high) - 1.27).abs() < 0.02, "{}", mean(&kids_high));
        // ...but now and then a weak pair has a strong child, and a strong pair a weak one.
        assert!(kids_low.iter().any(|&x| x > 1.0));
        assert!(kids_high.iter().any(|&x| x < 1.0));
        assert!(kids_low.iter().filter(|&&x| x > 1.0).count() < 200);
    }

    #[test]
    fn founders_have_every_knack_and_practice_helps_with_diminishing_returns() {
        let mut u = rng(3);
        let g = founder(&person_temperament(), &["gather".into(), "wait".into()], &mut u);
        assert!(g.contains_key("knack:gather") && !g.contains_key("knack:wait"));
        assert!(g.contains_key("trait:caution"));
        assert!(practice_factor(0) == 1.0 && practice_factor(60) > 1.3 && practice_factor(1000) < 1.61);
        assert_eq!(skill_factor(&g, &BTreeMap::new(), "wait"), 1.0);
    }

    #[test]
    fn ways_drop_the_plan_and_keep_the_desires() {
        let mut u = rng(1);
        let top = crate::graph::parse(r#"{"desires": [{"want": "the plan", "weight": {"base": 0.6}, "do": {"routine": "current plan"}}, {"want": "food", "weight": {"base": -0.5, "hunger": 1.5}, "do": {"routine": "eat"}}]}"#).unwrap().root;
        let Some(Node::Desires(ds)) = vary_ways(&top, &mut u) else { panic!() };
        assert_eq!(ds.len(), 1);
        assert_eq!(ds[0].want, "food");
        assert!((ds[0].weight.hunger - 1.5).abs() < 1.0);
    }
}
