//! A seed's laws overlay keeps what the shipped laws it replaces give.
//!
//! An overlay (a seed's `laws` or `laws_file`, composed over the shipped script by
//! [`crate::floors::compose`]) replaces whole functions. One that rewrites a law and leaves out a
//! line of the shipped one silently drops what that line gave: an overlay `senses(a)` without
//! the shipped `if law("fov_on") { s.field = sight_field(a); }` turns facing sight off in its
//! world whatever the `fov_on` law says. So, for every tracked seed with an overlay, with
//! `fov_on` set:
//! - `senses(a)` gives a `field`;
//! - every law the overlay replaces that answers with a map gives every key (nested maps
//!   included) that the shipped one (kept as `base_NAME`) gives, for the same context.
//!
//! A gap someone has taken on is listed in [`KNOWN_GAPS`] with its owner; the test fails on any
//! other gap, and on a listed one that has closed (remove its entry then). `LIVING_OVERLAY_CHECK`
//! adds overlay files outside the tracked seeds (a play scene's laws).
//!
//! Keys only, not values: a replaced law may change what a key holds (Cullet's `senses_law`
//! starts from `base_senses_law()` since f76783c4 and changes `covers`, `reach.glow` and `about`).

use super::{context, ActorFacts, Scripts, SkillCtx};
use rhai::{Dynamic, Map, Scope};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

const SHIPPED: &str = include_str!("../../../scripts/skills.rhai");

/// Gaps taken on: (overlay file under `living/seeds`, law, missing key path, owner and reason).
const KNOWN_GAPS: &[(&str, &str, &str, &str)] = &[];

/// The tracked seeds with an overlay: (seed name, overlay file or "<inline>", overlay, `rules`).
fn overlays() -> Vec<(String, String, String, Vec<(String, serde_json::Value)>)> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../seeds");
    let mut paths: Vec<_> = std::fs::read_dir(&dir).unwrap().map(|e| e.unwrap().path()).filter(|p| p.extension().is_some_and(|x| x == "json")).collect();
    paths.sort();
    let mut out = Vec::new();
    for path in paths {
        let Ok(v) = serde_json::from_str::<serde_json::Value>(&std::fs::read_to_string(&path).unwrap()) else { continue };
        let name = path.file_stem().unwrap().to_string_lossy().to_string();
        let inline = v.get("laws").and_then(|l| l.as_str()).filter(|l| !l.trim().is_empty());
        let (file, laws) = match (inline, v.get("laws_file").and_then(|f| f.as_str())) {
            (Some(l), _) => ("<inline>".to_string(), l.to_string()),
            (None, Some(f)) => (f.to_string(), std::fs::read_to_string(dir.join(f)).unwrap_or_else(|e| panic!("{name}: laws_file {f}: {e}"))),
            (None, None) => continue,
        };
        let rules = v.get("rules").and_then(|r| r.as_object()).map(|m| m.iter().map(|(k, v)| (k.clone(), v.clone())).collect()).unwrap_or_default();
        out.push((name, file, laws, rules));
    }
    // More overlay files to hold to the same check (a play scene's own laws before its launch):
    // `LIVING_OVERLAY_CHECK=a.rhai:b.rhai cargo test -p living-rules --lib overlay_check`.
    for f in std::env::var("LIVING_OVERLAY_CHECK").unwrap_or_default().split(':').filter(|f| !f.is_empty()) {
        let laws = std::fs::read_to_string(f).unwrap_or_else(|e| panic!("LIVING_OVERLAY_CHECK {f}: {e}"));
        out.push((f.to_string(), f.to_string(), laws, Vec::new()));
    }
    out
}

/// A person by day, and at night carrying a torch.
fn contexts() -> Vec<(&'static str, SkillCtx)> {
    let person = ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), hp: 100.0, hunger: 30.0, energy: 80.0, terrain: "grass".into(), ..Default::default() };
    let day = SkillCtx { actor: person.clone(), hour: 12.0, season: "summer".into(), ..Default::default() };
    let mut night = SkillCtx { actor: person, hour: 1.0, season: "winter".into(), night: true, dark: 1.0, ..Default::default() };
    night.actor.inv.push(("torch".into(), 1));
    vec![("a person by day", day), ("a person at night with a torch", night)]
}

/// Every key path of a map, nested maps included (`reach.night`).
fn key_paths(m: &Map, at: &str, out: &mut BTreeSet<String>) {
    for (k, v) in m {
        let p = format!("{at}{k}");
        if let Some(inner) = v.read_lock::<Map>() {
            key_paths(&inner, &format!("{p}."), out);
        }
        out.insert(p);
    }
}

/// What `f` answers in `s`: with no argument, or with the context map when its one parameter is
/// the shipped laws' context `a`. None when it takes anything else or fails.
fn answer(s: &Scripts, f: &str, ctx: &SkillCtx) -> Option<Dynamic> {
    let def = s.ast.iter_fn_def().find(|d| d.name.as_str() == f)?;
    let r = match def.params.iter().map(|p| p.as_str()).collect::<Vec<_>>().as_slice() {
        [] => s.engine.call_fn::<Dynamic>(&mut Scope::new(), &s.ast, f, ()),
        ["a"] => s.engine.call_fn::<Dynamic>(&mut Scope::new(), &s.ast, f, (context::map(ctx, "", &context::Plan::all()),)),
        _ => return None,
    };
    r.ok()
}

#[test]
fn every_seed_overlay_keeps_the_shipped_laws_shapes() {
    let seeds = overlays();
    assert!(seeds.iter().any(|(n, ..)| n == "cullet"), "Cullet has its own laws");
    let mut gaps: BTreeMap<(String, String, String), Vec<String>> = BTreeMap::new();
    let mut fails = Vec::new();
    let mut compared: BTreeSet<(String, String)> = BTreeSet::new();
    for (name, file, laws, rules) in &seeds {
        let mut values = rules.clone();
        values.retain(|(k, _)| k != "fov_on");
        values.push(("fov_on".into(), serde_json::json!(true)));
        let src = super::with_world_laws(&crate::floors::compose(SHIPPED, laws).unwrap_or_else(|e| panic!("{name}: {e}")), &values);
        let s = Scripts::new(&src).unwrap_or_else(|e| panic!("{name}: {e}"));
        let replaced: BTreeSet<String> = crate::floors::overlay_functions(laws).unwrap().into_iter().filter(|f| s.ast.iter_fn_def().any(|d| d.name.as_str() == format!("base_{f}"))).collect();
        for (who, ctx) in contexts() {
            match s.senses_unshared(&ctx) {
                Ok(v) if v.field.is_some() => {},
                Ok(_) => fails.push(format!("{name} ({file}): with fov_on set, senses(a) gives no `field` for {who} (keep the shipped `if law(\"fov_on\") {{ s.field = sight_field(a); }}`)")),
                Err(e) => fails.push(format!("{name} ({file}): senses for {who}: {e}")),
            }
            for f in &replaced {
                let (Some(ours), Some(shipped)) = (answer(&s, f, &ctx), answer(&s, &format!("base_{f}"), &ctx)) else { continue };
                let (Some(ours), Some(shipped)) = (ours.read_lock::<Map>().map(|m| m.clone()), shipped.read_lock::<Map>().map(|m| m.clone())) else { continue };
                compared.insert((file.clone(), f.clone()));
                let (mut have, mut want) = (BTreeSet::new(), BTreeSet::new());
                key_paths(&ours, "", &mut have);
                key_paths(&shipped, "", &mut want);
                for k in want.difference(&have) {
                    gaps.entry((file.clone(), f.clone(), k.clone())).or_default().push(format!("{name}, {who}"));
                }
            }
        }
    }
    // Not vacuous: Cullet's map laws were compared.
    for law in ["senses", "senses_law", "rates"] {
        assert!(compared.contains(&("worlds/cullet/laws.rhai".to_string(), law.to_string())), "Cullet's `{law}` was not compared: {compared:?}");
    }
    for ((file, f, k), seen) in &gaps {
        if !KNOWN_GAPS.iter().any(|(gf, gl, gk, _)| gf == file && gl == f && gk == k) {
            fails.push(format!("{file}: `{f}` drops the shipped key `{k}` ({}): compose the shipped law (`base_{f}`) or give the key", seen.join("; ")));
        }
    }
    for (gf, gl, gk, why) in KNOWN_GAPS {
        if !gaps.contains_key(&(gf.to_string(), gl.to_string(), gk.to_string())) {
            fails.push(format!("{gf}: the known gap `{gl}` drops `{gk}` ({why}) has closed: remove its KNOWN_GAPS entry"));
        }
    }
    assert!(fails.is_empty(), "seed overlays lose what the shipped laws give:\n{}", fails.join("\n"));
}

/// The check catches an overlay `senses(a)` written without the field, and a replaced map law
/// that drops a key.
#[test]
fn the_check_catches_a_dropped_field_and_a_dropped_key() {
    let overlay = "fn senses(a) { #{ sight: 10.0, hearing: 9.0 } }\nfn senses_law() { let l = base_senses_law(); l.remove(\"topic\"); l }\n";
    let src = super::with_world_laws(&crate::floors::compose(SHIPPED, overlay).unwrap(), &[("fov_on".into(), serde_json::json!(true))]);
    let s = Scripts::new(&src).unwrap();
    let (_, ctx) = contexts().remove(0);
    assert_eq!(s.senses_unshared(&ctx).unwrap().field, None);
    let (ours, shipped) = (answer(&s, "senses_law", &ctx).unwrap().cast::<Map>(), answer(&s, "base_senses_law", &ctx).unwrap().cast::<Map>());
    let (mut have, mut want) = (BTreeSet::new(), BTreeSet::new());
    key_paths(&ours, "", &mut have);
    key_paths(&shipped, "", &mut want);
    assert_eq!(want.difference(&have).cloned().collect::<Vec<_>>(), vec!["topic".to_string()]);
}
