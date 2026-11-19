//! The world's own law values laid over a compiled script (`law_override`, docs/LAW_OVERRIDE.md):
//! precedence decided in one place, a value-only edit equal to a fresh compile under the same
//! values (the laws in force read by Rust and by Rhai, and what the script derived from them),
//! a refused value leaving nothing changed, and the source guard that keeps a law a script reads
//! elsewhere out of the value-only path.

#![cfg(test)]

use crate::script::{with_world_laws, Applied, Scripts, SkillCtx, ValueOnly, VALUE_ONLY};
use crate::sight::GazeBand;
use serde_json::{json, Value};

const BASE: &str = include_str!("../../scripts/skills.rhai");
const CULLET: &str = include_str!("../../seeds/worlds/cullet/laws.rhai");
const DAY: u64 = crate::DEFAULT_DAY_MS;

/// A function of the test's own that reads a law through Rhai's `law(name)`, as the laws do.
const PROBE: &str = "fn probe_law(name) { law(name) }";

fn with_probe(src: &str) -> String {
    format!("{src}\n{PROBE}\n")
}

fn cullet() -> String {
    crate::floors::compose(BASE, CULLET).expect("Cullet's overlay composes")
}

/// Every senses sample the comparisons ask: each gaze band, by day, at dusk and at night, with
/// and without a torch, facing two ways.
fn samples() -> Vec<SkillCtx> {
    let mut out = Vec::new();
    for gaze_band in GazeBand::ALL {
        for (night, dark) in [(false, 0.0), (false, 0.4), (true, 1.0)] {
            for torch in [false, true] {
                let mut c = SkillCtx { gaze_band, night, dark, ..Default::default() };
                if torch {
                    c.actor.inv.push(("torch".into(), 1));
                }
                out.push(c);
            }
        }
    }
    out
}

/// Everything a reader of the laws in force can observe, through Rust and through Rhai.
#[derive(Debug, PartialEq)]
struct Seen {
    laws: crate::script::Laws,
    rust: Option<Value>,
    rhai: String,
    gaze: bool,
    gaze_reach: u32,
    senses: Vec<String>,
    about: Vec<(String, String)>,
}

fn seen(s: &Scripts, name: &str) -> Seen {
    Seen {
        laws: s.laws(),
        rust: s.law_value(name),
        rhai: s.call_test("probe_law", name),
        gaze: s.gaze_enabled(),
        gaze_reach: s.gaze_reach().to_bits(),
        // Through the memo (`senses`), as the engine asks them.
        senses: samples().iter().map(|c| format!("{:?}", s.senses(c))).collect(),
        about: s.laws_about(),
    }
}

/// The other value of a law: a flag flipped, a number moved.
fn other(v: &Value) -> Value {
    match v {
        Value::Bool(b) => json!(!b),
        Value::Number(n) => json!(n.as_f64().unwrap() + 0.5),
        _ => unreachable!("a law is a flag or a number"),
    }
}

#[test]
fn every_value_only_law_is_value_only_in_the_shipped_script_and_cullet() {
    for src in [BASE.to_string(), cullet()] {
        let s = Scripts::new(&src).unwrap();
        for (name, class) in VALUE_ONLY {
            assert_eq!(s.value_only(name), Some(class), "{name}");
            assert!(s.law_value(name).is_some(), "{name} is a law");
        }
        assert_eq!(s.value_only("fire_warmth"), None, "an ordinary law");
        assert_eq!(s.value_only("no_such_law"), None);
    }
}

#[test]
fn the_override_wins_over_the_script_s_values_and_its_written_values() {
    // The script says 3.5 (`laws()`); the values written at its end (an install's) say 2.0; the
    // override says 1.0. Through Rust (`laws`, `law_value`) and Rhai (`law`), alike.
    let src = with_probe(&with_world_laws(BASE, &[("fire_warmth".into(), json!(2.0))]));
    let plain = Scripts::new(&with_probe(BASE)).unwrap();
    assert_eq!(plain.laws().fire_warmth, 3.5);
    let written = Scripts::new(&src).unwrap();
    assert_eq!((written.laws().fire_warmth, written.call_test("probe_law", "fire_warmth")), (2.0, "2.0".to_string()));
    let over = vec![("fire_warmth".to_string(), json!(1.0))];
    let both = Scripts::with_overrides(&src, DAY, &over).unwrap();
    assert_eq!(both.laws().fire_warmth, 1.0);
    assert_eq!(both.law_value("fire_warmth"), Some(json!(1.0)));
    assert_eq!(both.call_test("probe_law", "fire_warmth"), "1.0");
    assert_eq!(both.laws_with(&[]).unwrap().fire_warmth, 1.0);
    assert_eq!(both.overrides(), over);
    // A name that is not a law, or a value of another kind, is left out.
    let odd = Scripts::with_overrides(&src, DAY, &[("no_such".into(), json!(1)), ("fov_on".into(), json!(3)), ("fire_warmth".into(), json!(true))]).unwrap();
    assert_eq!(odd.laws().fire_warmth, 2.0);
    assert!(!odd.laws().fov_on && odd.law_value("no_such").is_none());
}

/// The heart of the value-only path: for each value-only law, on the island and on Cullet, a
/// compiled script whose memos are warm, given the law's other value in place, reads exactly as
/// a fresh compile with that value: the laws, the value through Rust and Rhai, the gaze ceilings
/// and every senses sample through the per-state memo, and the constants' words. A dependent
/// left stale (the senses memo after `gaze_on`, the ceilings, the words) fails it.
#[test]
fn a_value_only_edit_reads_as_a_fresh_compile_with_the_value() {
    for (world, src) in [("island", with_probe(BASE)), ("cullet", with_probe(&cullet()))] {
        let warm = Scripts::new(&src).unwrap();
        for (name, class) in VALUE_ONLY {
            let before = warm.law_value(name).unwrap();
            let after = other(&before);
            // Warm what a running world keeps: the senses memo, by every sample.
            let _ = seen(&warm, name);
            let over = vec![(name.to_string(), after.clone())];
            let a = warm.apply_overrides(&over).unwrap_or_else(|e| panic!("{world} {name}: {e}"));
            assert_eq!(a.changed, vec![name.to_string()], "{world} {name}");
            assert_eq!((a.delivery, a.cover, a.gaze), (class == ValueOnly::Delivery, class == ValueOnly::Cover, class == ValueOnly::Gaze));
            let fresh = Scripts::with_overrides(&src, DAY, &over).unwrap();
            assert_eq!(seen(&warm, name), seen(&fresh, name), "{world} {name}: the value-only edit differs from a fresh compile");
            assert_eq!(warm.law_value(name), Some(after.clone()));
            // And back: no override is the script's own value again.
            warm.apply_overrides(&[]).unwrap();
            let plain = Scripts::new(&src).unwrap();
            assert_eq!(seen(&warm, name), seen(&plain, name), "{world} {name}: back to the script's value");
        }
    }
}

#[test]
fn gaze_on_changes_the_fields_and_cover_and_delivery_change_only_their_laws() {
    let src = with_probe(BASE);
    let s = Scripts::new(&src).unwrap();
    let day = SkillCtx { gaze_band: GazeBand::Far, ..Default::default() };
    let off = s.senses(&day).unwrap();
    assert!(off.gaze.is_none() && !s.gaze_enabled());
    s.apply_overrides(&[("gaze_on".into(), json!(true))]).unwrap();
    let on = s.senses(&day).unwrap();
    assert!(s.gaze_enabled() && on.gaze.is_some_and(|g| g.band == GazeBand::Far), "{on:?}");
    assert!(on.field.is_some(), "gaze makes the field directional: {on:?}");
    // The memo kept the off answer under the same key: cleared, so the field is the law's.
    assert_eq!(on, s.senses_unshared(&day).unwrap());
    let cover = s.apply_overrides(&[("gaze_on".into(), json!(true)), ("cover_sight_on".into(), json!(true)), ("cover_brush_min_fill".into(), json!(0.4))]).unwrap();
    assert_eq!(cover, Applied { changed: vec!["cover_brush_min_fill".into(), "cover_sight_on".into()], cover: true, ..Default::default() });
    assert!(s.laws().cover_sight_on && (s.laws().cover_brush_min_fill - 0.4).abs() < 1e-6);
    assert_eq!(s.senses(&day).unwrap(), on, "cover reaches no senses");
    let delivery = s.apply_overrides(&[("gaze_on".into(), json!(true)), ("cover_sight_on".into(), json!(true)), ("cover_brush_min_fill".into(), json!(0.4)), ("cue_transport_on".into(), json!(false))]).unwrap();
    assert!(delivery.delivery && !delivery.cover && !delivery.gaze);
    assert!(!s.laws().cue_transport_on && s.laws().near_tier_on);
    // battle-views' kill switch is a delivery law too: on and off in place, words following.
    let tables = s.apply_overrides(&[("gaze_on".into(), json!(true)), ("cover_sight_on".into(), json!(true)), ("cover_brush_min_fill".into(), json!(0.4)), ("cue_transport_on".into(), json!(false)), ("motion_tables_on".into(), json!(true))]).unwrap();
    assert!(tables.delivery && !tables.cover && !tables.gaze && tables.changed == vec!["motion_tables_on".to_string()], "{tables:?}");
    assert!(s.laws().motion_tables_on);
    let about: std::collections::HashMap<String, String> = s.laws_about().into_iter().collect();
    assert!(about["motion_tables_on"].contains("meant for that player alone"), "{about:?}");
    let off = s.apply_overrides(&[("gaze_on".into(), json!(true)), ("cover_sight_on".into(), json!(true)), ("cover_brush_min_fill".into(), json!(0.4)), ("cue_transport_on".into(), json!(false))]).unwrap();
    assert!(off.delivery && !s.laws().motion_tables_on, "{off:?}");
    let about: std::collections::HashMap<String, String> = s.laws_about().into_iter().collect();
    assert!(about["cue_transport_on"].contains("with the rest of what it sees"), "the words follow the value: {about:?}");
}

/// A refused value changes nothing: not the laws in force, the overrides, the ceilings, the
/// senses or the words. Here a world whose gaze ceiling is out of bounds, given `gaze_on`; and
/// a change of an ordinary law, which needs an install.
#[test]
fn a_refused_value_leaves_everything_as_it_was() {
    let src = with_probe(&crate::floors::compose(BASE, "fn gaze_ceiling(band) { 999.0 }").unwrap());
    let s = Scripts::new(&src).unwrap();
    let before = seen(&s, "gaze_on");
    let over_before = s.overrides();
    let e = s.apply_overrides(&[("gaze_on".into(), json!(true))]).unwrap_err();
    assert!(e.contains("gaze_ceiling"), "{e}");
    assert_eq!(seen(&s, "gaze_on"), before);
    assert_eq!(s.overrides(), over_before);
    assert!(Scripts::with_overrides(&src, DAY, &[("gaze_on".into(), json!(true))]).is_err(), "a compile with the value refuses it too");
    // An ordinary law is not laid over in place.
    let e = s.apply_overrides(&[("fire_warmth".into(), json!(1.0))]).unwrap_err();
    assert!(e.contains("fire_warmth") && e.contains("install"), "{e}");
    assert_eq!(seen(&s, "fire_warmth"), seen(&Scripts::new(&src).unwrap(), "fire_warmth"));
    // Nor alongside a value-only one: all or nothing.
    assert!(s.apply_overrides(&[("cue_transport_on".into(), json!(false)), ("fire_warmth".into(), json!(1.0))]).is_err());
    assert!(s.laws().cue_transport_on);
    // Unchanged values are no change at all.
    assert_eq!(s.apply_overrides(&[("fire_warmth".into(), json!(3.5))]).unwrap(), Applied::default());
}

/// A script that reads a value-only law anywhere but the constants makes it an ordinary law:
/// its derived state could depend on the value in ways the value-only path does not refresh.
#[test]
fn a_law_a_script_reads_elsewhere_is_not_value_only() {
    let sneaky = crate::floors::compose(BASE, "fn heard_as(kind) { if law(\"near_tier_on\") { kind } else { \"creature\" } }").unwrap();
    let s = Scripts::new(&sneaky).unwrap();
    assert_eq!(s.value_only("near_tier_on"), None);
    assert_eq!(s.value_only("cue_transport_on"), Some(ValueOnly::Delivery));
    assert_eq!(s.value_only("motion_tables_on"), Some(ValueOnly::Delivery));
    assert!(s.apply_overrides(&[("near_tier_on".into(), json!(false))]).unwrap_err().contains("not value-only"));
    // A field of the constants read elsewhere counts too (`laws().gaze_on`).
    let field = crate::floors::compose(BASE, "fn heard_as(kind) { if laws().gaze_on { kind } else { \"creature\" } }").unwrap();
    assert_eq!(Scripts::new(&field).unwrap().value_only("gaze_on"), None);
    // A longer name holding it (`gaze_on_x`) is another word.
    let longer = crate::floors::compose(BASE, "fn heard_as(kind) { let gaze_on_x = 1; kind }").unwrap();
    assert_eq!(Scripts::new(&longer).unwrap().value_only("gaze_on"), Some(ValueOnly::Gaze));
}

/// What a value-only edit costs here, natively, per law (`--ignored --nocapture`): the lay-over
/// alone, warm, on the island and Cullet. The module's own spans are the measure that counts
/// (`law_override.py time`); this splits the work.
#[test]
#[ignore]
fn value_only_edit_cost() {
    for (world, src) in [("island", BASE.to_string()), ("cullet", cullet())] {
        let s = Scripts::new(&src).unwrap();
        for (name, _) in VALUE_ONLY {
            let v = other(&s.law_value(name).unwrap());
            let t = std::time::Instant::now();
            let n = 20;
            for i in 0..n {
                let over = if i % 2 == 0 { vec![(name.to_string(), v.clone())] } else { vec![] };
                s.apply_overrides(&over).unwrap();
            }
            println!("{world} {name}: {:.3} ms per edit", t.elapsed().as_secs_f64() * 1000.0 / n as f64);
        }
        let t = std::time::Instant::now();
        let _ = s.laws_about();
        println!("{world} laws_about (kept): {:.3} ms", t.elapsed().as_secs_f64() * 1000.0);
    }
}
