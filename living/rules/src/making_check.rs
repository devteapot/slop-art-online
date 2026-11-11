//! Crafting, cooking and smoking as recipes (recipes-1) against the script before it folded them
//! into `recipes()`: for the island and for Cullet, every answer the rules give about making must
//! be what it was (docs/WORLD_RULES.md, "One table of what is made").
//!
//! ```text
//! git show 3c73d835:living/scripts/skills.rhai > /tmp/old-skills.rhai
//! git show 3c73d835:living/seeds/worlds/cullet/laws.rhai > /tmp/old-cullet.rhai
//! LIVING_OLD_SKILLS=/tmp/old-skills.rhai LIVING_OLD_CULLET=/tmp/old-cullet.rhai \
//!   cargo test -p living-rules --release making_is_bit_identical -- --ignored --nocapture
//! ```
//!
//! Compared, old against new, for every state below: each making skill's check (its verdict and
//! its words), its duration and, where the check passes, its effects (what is used, what is made,
//! the fuel drawn, the energy spent); `teach_check` on every item (a crafted thing names its
//! technique); `source_of` on every item (how a thing is come by, in every refusal); every skill's
//! spec as the engine reads it; the skill reference and the minds' world text; and old behaviour
//! graphs naming `craft`, `cook` and `smoke`, normalized against each script's skills.
//!
//! The states: actors (a grown person, a child, an infant, an elder, a deer, a wolf), what they
//! know (nothing, everything, each one technique), what they carry (nothing, plenty of
//! everything, one of each item, plenty of everything but one item), the targets an act can have
//! (none, a place, a person, a resource, every structure kind, each fire lit and out with no,
//! little and plenty of fuel) and every item, structure and a few non-names as the act's item.

#[cfg(test)]
mod tests {
    use crate::script::{ActorFacts, Scripts, SkillCtx, TargetFacts};

    const NEW: &str = include_str!("../../scripts/skills.rhai");
    const NEW_CULLET: &str = include_str!("../../seeds/worlds/cullet/laws.rhai");
    const SKILLS: [&str; 4] = ["craft", "cook", "smoke", "make"];

    fn old(var: &str) -> Option<String> {
        let path = std::env::var(var).ok()?;
        Some(std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{path}: {e}")))
    }

    fn worlds() -> Vec<(&'static str, Scripts, Scripts)> {
        let (Some(os), Some(oc)) = (old("LIVING_OLD_SKILLS"), old("LIVING_OLD_CULLET")) else { panic!("set LIVING_OLD_SKILLS and LIVING_OLD_CULLET (see the module's docs)") };
        let day = crate::cullet_check::CULLET_DAY_MS;
        let cullet = |base: &str, laws: &str| Scripts::with_day(&crate::floors::compose(base, laws).unwrap(), day).unwrap();
        vec![("island", Scripts::new(&os).unwrap(), Scripts::new(NEW).unwrap()), ("cullet", cullet(&os, &oc), cullet(NEW, NEW_CULLET))]
    }

    struct Diff {
        states: u64,
        differ: u64,
        shown: Vec<String>,
    }
    impl Diff {
        fn same(&mut self, what: impl FnOnce() -> String, a: &str, b: &str) {
            self.states += 1;
            if a != b {
                self.differ += 1;
                if self.shown.len() < 30 {
                    self.shown.push(format!("{}:\n    old {a}\n    new {b}", what()));
                }
            }
        }
    }

    /// Writes Cullet's laws composed over this branch's shipped script to `LIVING_COMPOSED_OUT`,
    /// for installing on a Cullet world made before recipes-1 (as `floors::compose` does at
    /// creation).
    #[test]
    #[ignore = "writes a file: needs LIVING_COMPOSED_OUT"]
    fn write_cullet_composed() {
        let path = std::env::var("LIVING_COMPOSED_OUT").expect("set LIVING_COMPOSED_OUT");
        std::fs::write(&path, crate::floors::compose(NEW, NEW_CULLET).unwrap()).unwrap();
    }

    #[test]
    #[ignore = "needs LIVING_OLD_SKILLS and LIVING_OLD_CULLET: the scripts before recipes-1 (see the module's docs)"]
    fn making_is_bit_identical() {
        for (world, old, new) in worlds() {
            assert!(!old.has("craft_making") && new.has("craft_making"), "{world}: the old script has no ways of making, the new one does");
            let mut d = Diff { states: 0, differ: 0, shown: Vec::new() };
            let names = |t: &str| new.tables().names(t).to_vec();
            let items = names("items");
            let structures = names("structures");
            // Act items: every item, some structures and techniques, and some that are none.
            let mut words: Vec<String> = items.clone();
            words.extend(["", "fuel", "food", "no_such_thing", "smoking", "cooking", "campfire", "furnace", "house"].map(String::from));
            // Actors.
            let actors: Vec<(&str, &str)> = vec![("person", "adult"), ("person", "child"), ("person", "infant"), ("person", "elder"), ("deer", "adult"), ("wolf", "adult")];
            // What they know: nothing, everything, and each technique a recipe or a fire asks.
            let all_know: Vec<String> = names("know_how");
            let mut knows: Vec<Vec<String>> = vec![vec![], all_know.clone()];
            for k in ["fire", "cooking", "smoking", "spear", "cloak", "torch", "toolmaking", "fishing", "basketry", "archery", "medicine", "tanning", "glassmaking"] {
                if all_know.iter().any(|t| t == k) {
                    knows.push(vec![k.to_string()]);
                }
            }
            // What they carry.
            let plenty: Vec<(String, u32)> = items.iter().map(|i| (i.clone(), 10)).collect();
            let mut packs: Vec<Vec<(String, u32)>> = vec![vec![], plenty.clone()];
            for i in &items {
                packs.push(vec![(i.clone(), 1)]);
                packs.push(plenty.iter().filter(|(n, _)| n != i).cloned().collect());
            }
            // Targets.
            let mut targets: Vec<TargetFacts> = vec![
                TargetFacts::default(),
                TargetFacts { class: "none".into(), ..Default::default() },
                TargetFacts { class: "place".into(), dist: 1.0, ..Default::default() },
                TargetFacts { class: "creature".into(), id: 9, kind: "person".into(), alive: true, dist: 1.0, ..Default::default() },
            ];
            for r in names("resources") {
                targets.push(TargetFacts { class: "resource".into(), id: 5, kind: r, amount: 3.0, dist: 1.0, ..Default::default() });
            }
            for k in &structures {
                for (lit, fuel) in [(false, 0.0f32), (true, 0.2), (true, 0.5), (true, 6.0)] {
                    targets.push(TargetFacts { class: "structure".into(), id: 7, kind: k.clone(), dist: 1.0, lit, fuel, ..Default::default() });
                }
            }
            let ctx = |kind: &str, stage: &str, knows: &[String], inv: &[(String, u32)], t: &TargetFacts, skill: &str, item: &str| SkillCtx {
                actor: ActorFacts { id: 1, kind: kind.into(), stage: stage.into(), hp: 80.0, hunger: 40.0, energy: 80.0, inv: inv.to_vec(), knows: knows.to_vec(), terrain: "grass".into(), ..Default::default() },
                target: t.clone(),
                item: item.into(),
                qty: 1,
                skill: skill.into(),
                ..Default::default()
            };
            let mut passed = 0u64;
            let mut compare = |d: &mut Diff, c: &SkillCtx| {
                let skill = c.skill.as_str();
                let (co, cn) = (old.check(skill, c), new.check(skill, c));
                let at = || format!("{world} {skill} {:?} by a {} {} knowing {:?} carrying {:?} at {} {} lit {} fuel {}", c.item, c.actor.stage, c.actor.kind, c.actor.knows, c.actor.inv, c.target.class, c.target.kind, c.target.lit, c.target.fuel);
                d.same(at, &format!("{co:?}"), &format!("{cn:?}"));
                let (to, tn) = (old.duration_ms(skill, c), new.duration_ms(skill, c));
                d.same(|| format!("{} duration", at()), &format!("{to:?}"), &format!("{tn:?}"));
                if co.is_ok() && cn.is_ok() {
                    passed += 1;
                    let (fo, fe) = (old.done(skill, c), new.done(skill, c));
                    d.same(|| format!("{} effects", at()), &format!("{fo:?}"), &format!("{fe:?}"));
                }
            };
            for skill in SKILLS {
                // Who, what they know and where, for every item, with three packs.
                for (kind, stage) in &actors {
                    for k in &knows {
                        for t in &targets {
                            for item in &words {
                                for inv in [&packs[0], &packs[1], &vec![(item.clone(), 1)]] {
                                    compare(&mut d, &ctx(kind, stage, k, inv, t, skill, item));
                                }
                            }
                        }
                    }
                }
                // What they carry, for a grown person who knows everything, at every target.
                for t in &targets {
                    for item in &words {
                        for inv in &packs {
                            compare(&mut d, &ctx("person", "adult", &all_know, inv, t, skill, item));
                        }
                    }
                }
            }
            // A crafted thing named for teaching; how each thing is come by.
            for item in &words {
                let c = ctx("person", "adult", &all_know, &[], &targets[3], "teach", item);
                d.same(|| format!("{world} teach {item:?}"), &format!("{:?}", old.check("teach", &c)), &format!("{:?}", new.check("teach", &c)));
                d.same(|| format!("{world} source_of({item:?})"), &format!("{:?}", old.text_of("source_of", item)), &format!("{:?}", new.text_of("source_of", item)));
            }
            // Every skill as the engine reads it, the skill reference and the minds' world text.
            let (so, sn) = (old.skills(), new.skills());
            let mut skill_names: Vec<&str> = so.names().collect();
            skill_names.sort();
            let mut new_names: Vec<&str> = sn.names().collect();
            new_names.sort();
            d.same(|| format!("{world} skills"), &skill_names.join(" "), &new_names.join(" "));
            for n in &skill_names {
                d.same(|| format!("{world} {n}_spec"), &format!("{:?}", so.get(n)), &format!("{:?}", sn.get(n)));
            }
            d.same(|| format!("{world} skill reference"), &crate::catalog::skills_help_of(so), &crate::catalog::skills_help_of(sn));
            let w = [("seasons", "(the world's calendar)".to_string()), ("life", "(the world's life table)".to_string())];
            d.same(|| format!("{world} world text"), &old.world_text(&w), &new.world_text(&w));
            // Old graphs naming the old skills normalize the same against either script.
            let graphs = [
                serde_json::json!({"first": [{"if": {"has": "fish"}, "then": {"do": "cook", "target": {"nearest": "campfire"}, "item": "fish"}}, {"do": "smoke", "target": {"nearest": "campfire"}, "item": "meat"}]}),
                serde_json::json!({"seq": [{"do": "craft", "item": "spear"}, {"do": "craft", "item": "arrow"}, {"do": "cook", "item": "fish", "target": {"nearest": "campfire"}}]}),
                serde_json::json!({"do": "craft", "item": "no_such_tool"}),
                serde_json::json!({"if": {"can": {"do": "cook", "item": "fish", "target": {"nearest": "campfire"}}}, "then": {"do": "eat", "item": "cooked_fish"}}),
            ];
            for g in &graphs {
                crate::catalog::set_skills(so.clone());
                let a = crate::normalize::graph(g.clone());
                crate::catalog::set_skills(sn.clone());
                let b = crate::normalize::graph(g.clone());
                d.same(|| format!("{world} graph {g}"), &format!("{a:?}"), &format!("{b:?}"));
                assert!(a.is_err() || b.is_ok(), "{world}: an old graph naming the old skills still normalizes: {b:?}");
            }
            println!("{world}: {} states, {} differ; {passed} acts made", d.states, d.differ);
            assert!(d.shown.is_empty(), "{world}: {} of {} differ:\n  {}", d.differ, d.states, d.shown.join("\n  "));
            assert!(passed > 1000, "{world}: the states make things ({passed})");
        }
    }
}
