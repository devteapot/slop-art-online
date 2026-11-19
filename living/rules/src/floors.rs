//! A floor's laws over the shared base script (see `docs/FLOORS.md`, mechanics that change
//! between floors).
//!
//! Every floor runs the same module and the same base script (`living/scripts/skills.rhai`). A
//! floor adds an overlay: Rhai functions that replace base functions of the same name, or add
//! new ones (skills of its own, laws it adds). [`compose`] renames each replaced base function
//! `fn NAME(` to `fn base_NAME(`, then appends the overlay, so:
//! - the overlay's `NAME` is the one every caller reaches, the engine and the base script's own
//!   functions alike (Rhai resolves functions by name at call time);
//! - the overlay can build on the base: `fn laws() { let l = base_laws(); l.fire_warmth = 5.0; l }`.
//!
//! The result is one ordinary script source for [`crate::script::Scripts::new`]: it is cached
//! per revision like any installed script, and the mind service and clients read the same text.

use std::collections::BTreeSet;

/// Function names an overlay defines (its Rhai `fn` items), in order of name.
pub fn overlay_functions(overlay: &str) -> Result<BTreeSet<String>, String> {
    let engine = crate::script::new_engine();
    let ast = engine.compile(overlay).map_err(|e| format!("floor overlay: {e}"))?;
    Ok(ast.iter_functions().map(|f| f.name.to_string()).collect())
}

/// The base script with an overlay's functions replacing the base's of the same name. Errors
/// when the overlay does not compile, or redefines a `base_` name.
pub fn compose(base: &str, overlay: &str) -> Result<String, String> {
    let names = overlay_functions(overlay)?;
    if let Some(n) = names.iter().find(|n| n.starts_with("base_")) {
        return Err(format!("floor overlay defines `{n}`: `base_` names are the replaced base functions"));
    }
    let mut out = String::with_capacity(base.len() + overlay.len() + 64);
    for line in base.split_inclusive('\n') {
        out.push_str(&rename_def(line, &names));
    }
    if !out.ends_with('\n') {
        out.push('\n');
    }
    out.push_str("\n// ---- floor overlay ----\n");
    out.push_str(overlay);
    Ok(out)
}

/// `fn NAME(` (or `private fn NAME(`) at the start of a line becomes `fn base_NAME(` when the
/// overlay replaces `NAME`.
fn rename_def(line: &str, names: &BTreeSet<String>) -> String {
    let indent = line.len() - line.trim_start().len();
    let rest = &line[indent..];
    let (private, rest) = match rest.strip_prefix("private ") {
        Some(r) => ("private ", r.trim_start()),
        None => ("", rest),
    };
    let Some(after) = rest.strip_prefix("fn ") else { return line.to_string() };
    let after = after.trim_start();
    let end = after.find(|c: char| !(c.is_alphanumeric() || c == '_')).unwrap_or(after.len());
    let name = &after[..end];
    if !names.contains(name) || !after[end..].trim_start().starts_with('(') {
        return line.to_string();
    }
    format!("{}{private}fn base_{name}{}", &line[..indent], &after[end..])
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::script::{ActorFacts, Scripts, SkillCtx};

    const BASE: &str = include_str!("../../scripts/skills.rhai");

    /// A frozen floor: cold is any hour away from fire and shelter, not only nights; blizzards
    /// shorten sight, and a fire warms further.
    const FROZEN: &str = r#"
fn cold(a) {
    a.actor.kind == "person" && !a.actor.near_fire && !a.actor.near_shelter && inv(a, "cloak") == 0
}
fn freezing(a) { true }
fn laws() {
    let l = base_laws();
    l.fire_warmth = 5.0;
    l
}
fn sight_in(light) { if light == "day" { 7.0 } else { base_sight_in(light) } }
"#;

    fn person_by_day() -> SkillCtx {
        SkillCtx { actor: ActorFacts { id: 1, kind: "person".into(), hp: 100.0, hunger: 30.0, energy: 80.0, terrain: "snow".into(), ..Default::default() }, hour: 12.0, season: "summer".into(), ..Default::default() }
    }

    #[test]
    fn one_build_two_floors_two_sets_of_laws() {
        let base = Scripts::new(BASE).expect("base compiles");
        let frozen = Scripts::new(&compose(BASE, FROZEN).expect("composes")).expect("frozen floor compiles");
        // Laws read once per revision: the overlay builds on the base's own values.
        let (lb, lf) = (base.laws(), frozen.laws());
        assert_eq!((lb.fire_warmth, lf.fire_warmth), (3.5, 5.0));
        assert_eq!(lf.shelter_warmth, lb.shelter_warmth, "laws the overlay leaves alone keep the base's value");
        // A creature's senses are a law per creature: the floor shortens sight by day only.
        let day = person_by_day();
        let mut night = day.clone();
        night.night = true;
        assert_eq!((base.senses(&day).unwrap().sight, frozen.senses(&day).unwrap().sight), (11.0, 7.0));
        assert_eq!(frozen.senses(&night).unwrap(), base.senses(&night).unwrap());
        // The base `rates` calls `cold`, and reaches the floor's: a person away from fire loses
        // health by day on the frozen floor and heals on the base.
        let c = person_by_day();
        let (rb, rf) = (base.rates(&c).unwrap(), frozen.rates(&c).unwrap());
        assert!(rb.hp_per_min > 0.0, "base heals by day: {}", rb.hp_per_min);
        // (A freezing cold outside winter takes 1.5 a minute times `person_pace`, 0.3: 0.45.)
        assert!(rf.hp_per_min < rb.hp_per_min - 0.4, "frozen floor: {} vs {}", rf.hp_per_min, rb.hp_per_min);
        // By a fire the frozen floor is the base again.
        let mut warm = c.clone();
        warm.actor.near_fire = true;
        assert_eq!(frozen.rates(&warm).unwrap().hp_per_min, rb.hp_per_min);
    }

    /// What a law costs when the engine calls it per character, and when it reads a cached
    /// number: `cargo test --release -p living-rules floors::tests::law_call_cost -- --ignored
    /// --nocapture` (native; the WASM authority runs slower).
    #[test]
    #[ignore]
    fn law_call_cost() {
        let s = Scripts::new(BASE).unwrap();
        let c = person_by_day();
        let n = 20_000;
        let t = std::time::Instant::now();
        let mut acc = 0.0;
        for _ in 0..n {
            acc += s.rates(&c).unwrap().hp_per_min;
        }
        let rates_us = t.elapsed().as_secs_f64() * 1e6 / n as f64;
        let t = std::time::Instant::now();
        for _ in 0..n {
            acc += s.move_speed(&c).unwrap();
        }
        let speed_us = t.elapsed().as_secs_f64() * 1e6 / n as f64;
        let t = std::time::Instant::now();
        for _ in 0..n {
            acc += s.num_of("lunge", "person", 0.6) as f32;
        }
        let num_us = t.elapsed().as_secs_f64() * 1e6 / n as f64;
        let laws = s.laws();
        let t = std::time::Instant::now();
        for _ in 0..n {
            acc += std::hint::black_box(&laws).fire_warmth;
        }
        let cached_ns = t.elapsed().as_secs_f64() * 1e9 / n as f64;
        println!("rates {rates_us:.1} us, move_speed {speed_us:.1} us, num_of(lunge) {num_us:.1} us, cached law {cached_ns:.1} ns per call ({acc})");
    }

    #[test]
    fn overlay_adds_and_guards() {
        let added = compose(BASE, "fn fall_hurt(drop_m) { if drop_m > 3.0 { (drop_m - 3.0) * 12.0 } else { 0.0 } }").unwrap();
        assert!(Scripts::new(&added).is_ok());
        assert!(compose(BASE, "fn base_laws() { #{} }").is_err());
        assert!(compose(BASE, "fn laws( {").is_err());
        // Only definitions are renamed, not calls or other text.
        let s = compose("fn laws() { #{} }\nfn x() { laws() }\n", "fn laws() { base_laws() }").unwrap();
        assert!(s.contains("fn base_laws()") && s.contains("fn x() { laws() }"), "{s}");
    }
}
