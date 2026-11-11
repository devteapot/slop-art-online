//! What the rules decide must not depend on Rhai's hashing keys ([`super::HASHING_SEED`]).
//!
//! The keys decide where Rhai puts a function, a call signature or an interned string in its
//! hash tables, and so the order in which it hands back a script's functions
//! (`AST::iter_functions`). A fixed seed makes that order the same in every build of one target,
//! but the hashes themselves still differ between targets: `ahash` multiplies differently on
//! wasm32 (the authority) than on x86_64 and aarch64 (the client and the mind service), and
//! hashes a `usize` in four bytes there instead of eight. So the authority, a client and the
//! mind agree on a rule only if no rule depends on that order. `fov-1`'s field analysis did
//! (fixed with `Fields::under`).
//!
//! This check digests everything a script compiles to and every answer the install checks and
//! the engine's own calls give over the install samples, for the shipped script and Cullet's
//! laws, and compares the digests in three processes: under [`super::HASHING_SEED`], under
//! other keys, and under the keys this build of `ahash` drew (`LIVING_RHAI_TEST_SEED`, read only
//! by tests). Another target's hashes are another set of keys, as far as order goes.

use super::{check, RegardIn, Scripts, LIMITS};
use crate::catalog;
use std::collections::HashSet;

const SHIPPED: &str = include_str!("../../../scripts/skills.rhai");
const CULLET: &str = include_str!("../../../seeds/worlds/cullet/laws.rhai");

fn sorted(h: &HashSet<String>) -> Vec<String> {
    let mut v: Vec<String> = h.iter().cloned().collect();
    v.sort();
    v
}

/// Everything `s` compiled to and every answer over the samples, one line each, sorted.
fn lines(s: &Scripts) -> Vec<String> {
    let mut v = vec![format!("fns {:?}", sorted(&s.fns)), format!("unary {:?}", sorted(&s.unary)), format!("nullary {:?}", sorted(&s.nullary))];
    v.extend(s.fields.summaries.iter().map(|(k, u)| format!("fields {k:?} {u:?}")));
    v.push(format!("fields gave up {}", s.fields.gave_up));
    v.push(format!("laws {:?}", s.laws()));
    v.push(format!("law specs {:?}", s.laws));
    v.push(format!("skills {:?}", s.skills));
    v.push(format!("shapes {:?}", s.shapes));
    v.push(format!("shows {:?}", s.shows));
    v.extend(s.structures.iter().map(|(k, t)| format!("structure {k} {t:?}")));
    v.push(format!("reach {:?}", s.reach));
    v.push(format!("ui {:?}", s.ui));
    v.push(format!("borrowed {:?} law errors {:?}", s.borrowed, s.law_errors.borrow()));
    for t in ["items", "structures", "resources", "recipes", "know_how"] {
        v.push(format!("table {t} {:?}", s.tables().names(t)));
    }
    let (report, trace) = check::validate_traced(s, LIMITS).expect("the script passes its install checks");
    v.push(format!("install {} calls {:?}", report.calls, report.ops));
    v.extend(trace);
    // The engine's own calls (its engine, its caches), as the authority makes them.
    catalog::scoped(s.skills().clone(), || {
        let skills: Vec<String> = s.skills.names().map(String::from).collect();
        for a in check::actors() {
            for t in check::targets() {
                let c = check::sample("", &a, &t, "");
                let who = format!("{} {} {} -> {} {}", a.id, a.kind, a.stage, t.class, t.kind);
                v.push(format!("rates {who} {:?}", s.rates_unshared(&c)));
                v.push(format!("senses {who} {:?}", s.senses_unshared(&c)));
                v.push(format!("motion {who} {:?}", s.moves_unshared(&c)));
                v.push(format!("speed {who} {:?}", s.move_speed(&c)));
                for k in &skills {
                    let c = check::sample(k, &a, &t, "wood");
                    v.push(format!("{k} {who} check {:?} takes {:?} done {:?}", s.check(k, &c), s.duration_ms(k, &c), s.done(k, &c)));
                }
            }
        }
    });
    for (o, t) in [("person", "person"), ("person", "wolf"), ("wolf", "wolf"), ("deer", "person")] {
        for (known, own, night) in [(false, false, false), (true, false, true), (false, true, false)] {
            for revealed in [vec![], vec!["health".to_string()]] {
                let p = RegardIn { observer_kind: o.into(), knows: vec!["fire".into(), "spear".into()], target_kind: t.into(), known, revealed, own, night, dist: 3 };
                v.push(format!("perceived {p:?} {:?}", s.perceived_of(&p)));
            }
        }
    }
    v.sort();
    v
}

/// FNV-1a over the lines: the same in every process and on every target.
fn digest(lines: &[String]) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in lines.iter().flat_map(|l| l.bytes().chain([b'\n'])) {
        h = (h ^ b as u64).wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}

fn digests() -> String {
    let shipped = Scripts::new(SHIPPED).expect("the shipped script compiles");
    let cullet = Scripts::with_day(&crate::floors::compose(SHIPPED, CULLET).expect("Cullet's overlay composes"), crate::cullet_check::CULLET_DAY_MS).expect("Cullet's laws compile");
    let (a, b) = (lines(&shipped), lines(&cullet));
    if let Ok(dir) = std::env::var("LIVING_RHAI_DIGEST_DIR") {
        let _ = std::fs::create_dir_all(&dir);
        std::fs::write(format!("{dir}/shipped.txt"), a.join("\n")).unwrap();
        std::fs::write(format!("{dir}/cullet.txt"), b.join("\n")).unwrap();
    }
    format!("shipped {:016x} ({} lines) cullet {:016x} ({} lines)", digest(&a), a.len(), digest(&b), b.len())
}

#[test]
#[ignore = "run by the seed check below, in a process of its own per hashing seed"]
fn rules_digest() {
    println!("rules digest: {} under {:?}", digests(), rhai::config::hashing::get_hashing_seed());
}

/// The rules' digest in a fresh process of this test binary under `seed` (`LIVING_RHAI_TEST_SEED`).
fn digest_under(seed: &str) -> String {
    let out = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "script::seed_check::rules_digest", "--ignored", "--nocapture", "--test-threads", "1"])
        .env("LIVING_RHAI_TEST_SEED", seed)
        .output()
        .expect("the test binary runs");
    let text = String::from_utf8_lossy(&out.stdout);
    assert!(out.status.success(), "the digest under {seed} failed:\n{text}\n{}", String::from_utf8_lossy(&out.stderr));
    let line = text.lines().find_map(|l| l.split_once("rules digest: ").map(|(_, d)| d)).unwrap_or_else(|| panic!("no digest under {seed}:\n{text}"));
    line.split(" under ").next().unwrap().to_string()
}

#[test]
fn every_engine_runs_under_the_fixed_seed() {
    if std::env::var_os("LIVING_RHAI_TEST_SEED").is_some() {
        return;
    }
    let _ = Scripts::new(SHIPPED).unwrap();
    assert_eq!(rhai::config::hashing::get_hashing_seed(), &Some(super::HASHING_SEED));
    assert_eq!(super::fix_hashing(), super::HASHING_SEED);
}

#[test]
fn the_rules_do_not_depend_on_the_hashing_seed() {
    let real = super::HASHING_SEED.map(|w| w.to_string()).join(",");
    let seeds = [real.as_str(), "11400714819323198485,13787848793156543929,1442695040888963407,6364136223846793005", "build"];
    let digests: Vec<String> = std::thread::scope(|sc| {
        let hs: Vec<_> = seeds.iter().map(|s| sc.spawn(move || digest_under(s))).collect();
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });
    for (s, d) in seeds.iter().zip(&digests).skip(1) {
        assert_eq!(d, &digests[0], "the rules decide differently under hashing keys {s} than under HASHING_SEED (dump both with LIVING_RHAI_DIGEST_DIR and diff)");
    }
}
