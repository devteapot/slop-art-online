//! Storage capacity on the structure kind and regrowth by season on the resource kind
//! (rules-3) against the script before them: on the shipped kinds every outcome the authority
//! works from must be what it was (docs/CULLET_RULES.md, "The labs are unchanged").
//!
//! ```text
//! git show 93019a37:living/scripts/skills.rhai > /tmp/old-skills.rhai
//! LIVING_OLD_SKILLS=/tmp/old-skills.rhai cargo test -p living-rules rules3_is_bit_identical -- --ignored --nocapture
//! ```
//!
//! Each side computes what the authority computes: the store and take checks' answers (`act`,
//! by the script's `store_check` and `take_check`) for every structure kind at many fills, the
//! words of every skill and law, the minds' world text with the seasons line, and a node's
//! amount after a while for every resource kind (`common::amount_now`: before, regrowth over
//! `growing_ms`; now over `regrowth_ms` with the kind's shares).

#[cfg(test)]
mod tests {
    use crate::script::{ActorFacts, Scripts, SkillCtx, TargetFacts};

    const NEW: &str = include_str!("../../scripts/skills.rhai");

    fn old() -> Option<Scripts> {
        let path = std::env::var("LIVING_OLD_SKILLS").ok()?;
        let src = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{path}: {e}"));
        Some(Scripts::new(&src).expect("the old script compiles"))
    }

    #[test]
    #[ignore = "needs LIVING_OLD_SKILLS: the script before rules-3 (see the module's docs)"]
    fn rules3_is_bit_identical() {
        let Some(old) = old() else { panic!("set LIVING_OLD_SKILLS to the old skills.rhai") };
        let new = Scripts::new(NEW).unwrap();
        assert!(old.has("storage_holds") && !new.has("storage_holds") && new.has("seasons_text"), "the old script has the one law, the new the kinds' values");
        let mut states = 0u64;
        let mut differ: Vec<String> = Vec::new();
        let mut same = |what: String, a: &str, b: &str| {
            states += 1;
            if a != b && differ.len() < 20 {
                differ.push(format!("{what}: {a:?} != {b:?}"));
            }
        };
        let answer = |r: Result<(), String>| r.err().unwrap_or_else(|| "ok".into());
        // Storing and taking: every kind of structure (and a creature, and a kind of no table),
        // at fills round the old 120, storing 1 to 25 and taking 1 to 3 of what is there.
        let mut kinds: Vec<String> = new.tables().names("structures").to_vec();
        kinds.extend(["no_such_kind", "person"].map(String::from));
        for kind in &kinds {
            for class in ["structure", "creature"] {
                for held in [0u32, 1, 50, 95, 99, 100, 110, 115, 119, 120, 121, 150] {
                    for qty in [1u32, 2, 5, 10, 20, 21, 25] {
                        for (pack, have) in [(30u32, 30u32), (3, 0)] {
                            let c = SkillCtx {
                                actor: ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), inv: vec![("wood".into(), pack)], ..Default::default() },
                                target: TargetFacts { class: class.into(), id: 7, kind: kind.clone(), dist: 1.0, inv: vec![("stone".into(), held), ("wood".into(), have)], ..Default::default() },
                                item: "wood".into(),
                                qty,
                                skill: "store".into(),
                                ..Default::default()
                            };
                            same(format!("store {qty} into a {class} {kind} holding {held}+{have}, carrying {pack}"), &answer(old.check("store", &c)), &answer(new.check("store", &c)));
                            let t = SkillCtx { skill: "take".into(), qty: qty.min(3), ..c.clone() };
                            same(format!("take {} from a {class} {kind} holding {held}+{have}, carrying {pack}", qty.min(3)), &answer(old.check("take", &t)), &answer(new.check("take", &t)));
                        }
                    }
                }
            }
        }
        // The words of every skill and law.
        for k in new.skills().iter() {
            let o = old.skills().get(&k.name).map(|o| format!("{}|{}|{}", o.about, o.takes, o.gives)).unwrap_or_default();
            same(format!("the words of {}", k.name), &o, &format!("{}|{}|{}", k.about, k.takes, k.gives));
        }
        for (name, l) in new.law_specs() {
            let o = old.law_specs().get(name).map(|l| l.about.clone()).unwrap_or_default();
            same(format!("the words of {name}_law"), &o, &l.about);
        }
        // The minds' world text, with the seasons line as the mind service builds it (before: a
        // fixed sentence after the calendar; now: the rules' `seasons_words`).
        let cal = "a year is 8 days — spring, summer, autumn, winter (2 days each).";
        let before = old.world_text(&[("seasons", format!("{cal} In winter nothing regrows and nights are colder: store food before it.")), ("life", "a person lives about 70 years.".into())]);
        let after = new.world_text(&[("seasons", format!("{cal} {}", new.seasons_words())), ("life", "a person lives about 70 years.".into())]);
        same("the minds' world text".into(), &before, &after);
        // Regrowth: a node's amount after a while, for every resource kind, from several amounts,
        // over times that cross every season, on the 12-minute day and others, in years of 8, 10
        // and 7 days.
        let mut rkinds: Vec<String> = new.tables().names("resources").to_vec();
        rkinds.push("no_such_resource".into());
        let epoch = 1_700_000_000_000u64;
        let mut amounts = 0u64;
        for (day, year) in [(crate::DEFAULT_DAY_MS, 8u64), (crate::DEFAULT_DAY_MS, 10), (48 * 60_000, 8), (1_000_003, 7)] {
            for k in &rkinds {
                let regen = new.regrow_per_min(k, 0.5) as f32;
                let by = new.regrow_seasons(k);
                let mut t0 = epoch - day;
                while t0 < epoch + day * year * 2 {
                    for len in [0u64, 1, 999, 60_000, 61_234, day / 7, day, day * 2 + 13, day * year] {
                        for amount in [0.0f32, 0.37, 2.0, 4.99] {
                            let a = (amount + regen * crate::growing_ms(t0, t0 + len, epoch, day, year) as f32 / 60_000.0).min(8.0);
                            let b = (amount + regen * crate::regrowth_ms(t0, t0 + len, epoch, day, year, &by) / 60_000.0).min(8.0);
                            amounts += 1;
                            same(format!("{k} from {amount} at {t0} after {len} ms (day {day}, year {year})"), &a.to_bits().to_string(), &b.to_bits().to_string());
                        }
                    }
                    t0 += day / 3 + 1_001;
                }
            }
        }
        println!("rules-3 against the old script: {states} states compared ({amounts} regrowth amounts), {} differ", differ.len());
        assert!(differ.is_empty(), "{differ:#?}");
    }
}
