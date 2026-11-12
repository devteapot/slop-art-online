//! goods-3 against main for the island (docs/GOODS.md, "The island"): every answer the rules
//! give must be what it was, except where goods-3 changes the island on purpose, which is only
//! that a pack counts each item by its `carry` (an arrow or a mark a tenth).
//!
//! ```text
//! git show origin/main:living/scripts/skills.rhai > /tmp/old-skills.rhai   # main before goods-3
//! LIVING_OLD_SKILLS=/tmp/old-skills.rhai \
//!   cargo test -p living-rules --release goods_check -- --ignored --nocapture
//! ```
//!
//! Three scripts answer each state: main's, this branch's, and this branch's with every item
//! counting 1 in a pack (`fn carry_of(item) { 1.0 }` composed over it). The third must answer
//! every state exactly as main does: building moved into the recipe table, the making check's
//! tools, the cheaper lookups and the audit's data traits change nothing on the island. Every
//! state where this branch differs from main must hold an item whose `carry` is not 1 (in the
//! actor's pack, the target's, or as the act's item) or be the food law's words, which now say
//! what counts for less.
//!
//! Compared for every skill with a check, duration or effects: its verdict and words, its
//! duration, and its effects where both pass; over actors (a grown person, a child, an infant,
//! an elder, a deer, a wolf), knowing nothing or everything, packs (empty, plenty of everything,
//! near the limit with arrows, marks, stones and a basket), targets (nothing, a place, a person
//! with an empty, a full and an arrow-laden pack, an infant, a deer, every resource kind, every
//! structure kind lit and out) and every item, structure and a few non-names as the act's item;
//! then every skill's spec as the engine reads it, the skill reference, the minds' world text and
//! every law's words, and `source_of`, `made_how`, `teach` and the recipe parts of every item.

#[cfg(test)]
mod tests {
    use crate::script::{ActorFacts, Scripts, SkillCtx, TargetFacts};

    const NEW: &str = include_str!("../../scripts/skills.rhai");

    struct Diff {
        states: u64,
        carry: u64,
        other: Vec<String>,
        shown_carry: Vec<String>,
        /// The carry differences by what differs (the skill and the part, or the law).
        by: std::collections::BTreeMap<String, u64>,
    }

    /// An answer without the script positions an error names ("(line 593, position 71)"):
    /// the two scripts' lines differ.
    fn unplaced(s: String) -> String {
        let mut out = String::new();
        let mut rest = s.as_str();
        while let Some(i) = rest.find("(line ") {
            out += &rest[..i];
            rest = rest[i..].find(')').map_or("", |j| &rest[i + j + 1..]);
        }
        out + rest
    }

    #[test]
    #[ignore = "needs LIVING_OLD_SKILLS: main's script before goods-3 (see the module's docs)"]
    fn the_island_changes_only_by_carry() {
        let path = std::env::var("LIVING_OLD_SKILLS").expect("set LIVING_OLD_SKILLS to main's skills.rhai");
        let old = Scripts::new(&std::fs::read_to_string(&path).unwrap()).expect("main's script compiles");
        let new = Scripts::new(NEW).unwrap();
        let ones = Scripts::new(&crate::floors::compose(NEW, "fn carry_of(item) { 1.0 }").unwrap()).unwrap();
        assert!(!old.has("carry_of") && new.has("carry_of"), "main's script has no carry, this branch's has");
        let light: Vec<String> = new.tables().names("items").iter().filter(|i| new.num_of("carry_of", i, 1.0) != 1.0).cloned().collect();
        assert_eq!(light, ["arrow", "mark"]);
        let mut d = Diff { states: 0, carry: 0, other: Vec::new(), shown_carry: Vec::new(), by: Default::default() };
        // One state: main against the branch with carry 1 (must agree), and against the branch
        // (may differ only where something light is involved).
        let same = |d: &mut Diff, what: &dyn Fn() -> String, o: String, one: String, n: String, light_here: bool| {
            let (o, one, n) = (unplaced(o), unplaced(one), unplaced(n));
            d.states += 1;
            if o != one && d.other.len() < 30 {
                d.other.push(format!("{} (carry 1):\n    main {o}\n    here {one}", what()));
            }
            if o != n {
                if light_here {
                    d.carry += 1;
                    let w = what();
                    let mut key = w.split_whitespace().next().unwrap_or("").to_string();
                    for part in ["duration", "effects"] {
                        if w.ends_with(part) {
                            key = format!("{key} {part}");
                        }
                    }
                    *d.by.entry(key).or_default() += 1;
                    if d.shown_carry.len() < 12 {
                        d.shown_carry.push(format!("{}:\n    main {o}\n    here {n}", what()));
                    }
                } else if d.other.len() < 30 {
                    d.other.push(format!("{}:\n    main {o}\n    here {n}", what()));
                }
            }
        };
        let names = |t: &str| new.tables().names(t).to_vec();
        let items = names("items");
        let structures = names("structures");
        let mut words: Vec<String> = items.clone();
        words.extend(structures.iter().cloned());
        words.extend(["", "fuel", "food", "road", "wall", "bridge", "no_such_thing", "cooking"].map(String::from));
        let actors: Vec<(&str, &str)> = vec![("person", "adult"), ("person", "child"), ("person", "infant"), ("person", "elder"), ("deer", "adult"), ("wolf", "adult")];
        let all_know = names("know_how");
        let inv = |v: &[(&str, u32)]| v.iter().map(|(i, n)| (i.to_string(), *n)).collect::<Vec<_>>();
        let plenty: Vec<(String, u32)> = items.iter().map(|i| (i.clone(), 10)).collect();
        let packs: Vec<Vec<(String, u32)>> = vec![
            vec![],
            items.iter().map(|i| (i.clone(), 1)).collect(),
            plenty.clone(),
            inv(&[("stone", 39)]),
            inv(&[("stone", 40)]),
            inv(&[("stone", 39), ("arrow", 5)]),
            inv(&[("stone", 36), ("arrow", 40)]),
            inv(&[("stone", 39), ("mark", 9)]),
            inv(&[("arrow", 399)]),
            inv(&[("stone", 50), ("basket", 1), ("arrow", 30)]),
            inv(&[("stone", 59), ("basket", 1)]),
            inv(&[("wood", 2), ("stone", 2), ("fiber", 3), ("arrow", 3)]),
        ];
        let mut targets: Vec<TargetFacts> = vec![
            TargetFacts { class: "none".into(), ..Default::default() },
            TargetFacts { class: "place".into(), dist: 1.0, ..Default::default() },
        ];
        for (stage, pack) in [("adult", vec![]), ("adult", inv(&[("stone", 39)])), ("adult", inv(&[("stone", 36), ("arrow", 30)])), ("adult", inv(&[("stone", 50), ("basket", 1), ("mark", 50)])), ("infant", inv(&[("berries", 3)]))] {
            targets.push(TargetFacts { class: "creature".into(), id: 9, kind: "person".into(), stage: stage.into(), alive: true, hp: 60.0, max_hp: 100.0, hurt_ago: 60_000.0, dist: 1.0, inv: pack, ..Default::default() });
        }
        targets.push(TargetFacts { class: "creature".into(), id: 8, kind: "deer".into(), alive: true, hp: 40.0, max_hp: 40.0, dist: 1.0, ..Default::default() });
        for r in names("resources") {
            targets.push(TargetFacts { class: "resource".into(), id: 5, kind: r, amount: 3.0, dist: 1.0, ..Default::default() });
        }
        for k in &structures {
            for (lit, fuel) in [(false, 0.0f32), (true, 6.0)] {
                targets.push(TargetFacts { class: "structure".into(), id: 7, kind: k.clone(), dist: 1.0, lit, fuel, inv: inv(&[("wood", 3), ("arrow", 20)]), ..Default::default() });
            }
        }
        let is_light = |i: &str| light.iter().any(|l| l == i);
        let skills: Vec<String> = new.skills().names().map(String::from).collect();
        let ctx = |kind: &str, stage: &str, knows: &[String], pack: &[(String, u32)], t: &TargetFacts, skill: &str, item: &str, qty: u32| SkillCtx {
            actor: ActorFacts { id: 1, kind: kind.into(), stage: stage.into(), hp: 80.0, hunger: 40.0, energy: 80.0, inv: pack.to_vec(), knows: knows.to_vec(), terrain: "forest".into(), ..Default::default() },
            target: t.clone(),
            item: item.into(),
            qty,
            skill: skill.into(),
            hour: 12.0,
            season: "summer".into(),
            text: "a note".into(),
            ..Default::default()
        };
        let compare = |d: &mut Diff, c: &SkillCtx| {
            let skill = c.skill.as_str();
            let light_here = c.actor.inv.iter().chain(c.target.inv.iter()).any(|(i, n)| *n > 0 && is_light(i)) || is_light(&c.item);
            let at = || format!("{skill} {:?}x{} by a {} {} knowing {} carrying {:?} at {} {} {:?}", c.item, c.qty, c.actor.stage, c.actor.kind, c.actor.knows.len(), c.actor.inv, c.target.class, c.target.kind, c.target.inv);
            let (co, c1, cn) = (old.check(skill, c), ones.check(skill, c), new.check(skill, c));
            same(d, &at, format!("{co:?}"), format!("{c1:?}"), format!("{cn:?}"), light_here);
            let dur = |s: &Scripts| format!("{:?}", s.duration_ms(skill, c));
            same(d, &|| format!("{} duration", at()), dur(&old), dur(&ones), dur(&new), light_here);
            if co.is_ok() || cn.is_ok() {
                let fx = |s: &Scripts| format!("{:?}", s.done(skill, c));
                same(d, &|| format!("{} effects", at()), fx(&old), fx(&ones), fx(&new), light_here);
            }
        };
        for skill in &skills {
            let item_words: Vec<String> = if new.skills().get(skill).is_some_and(|k| k.needs_item) || ["build", "craft"].contains(&skill.as_str()) { words.clone() } else { vec![String::new()] };
            for (kind, stage) in &actors {
                for k in [&vec![], &all_know] {
                    for t in &targets {
                        for item in &item_words {
                            for p in [&packs[0], &plenty] {
                                compare(&mut d, &ctx(kind, stage, k, p, t, skill, item, 1));
                            }
                        }
                    }
                }
            }
            for t in &targets {
                for item in &item_words {
                    for p in &packs {
                        for qty in [1, 5] {
                            compare(&mut d, &ctx("person", "adult", &all_know, p, t, skill, item, qty));
                        }
                    }
                }
            }
        }
        // Each name: how it is come by, made, taught, and laid out in a grid.
        for w in &words {
            let c = ctx("person", "adult", &all_know, &[], &targets[2], "teach", w, 1);
            let teach = |s: &Scripts| format!("{:?}", s.check("teach", &c));
            same(&mut d, &|| format!("teach {w:?}"), teach(&old), teach(&ones), teach(&new), false);
            for f in ["source_of", "made_how"] {
                let t = |s: &Scripts| format!("{:?}", s.text_of(f, w));
                same(&mut d, &|| format!("{f}({w:?})"), t(&old), t(&ones), t(&new), false);
            }
            for skill in ["craft", "cook", "smoke", "make"] {
                let p = |s: &Scripts| format!("{:?}", s.recipe_parts(skill, w));
                same(&mut d, &|| format!("recipe_parts({skill}, {w:?})"), p(&old), p(&ones), p(&new), false);
            }
        }
        // Every skill as the engine reads it, the skill reference, every law's words and the
        // minds' world text.
        let (so, s1, sn) = (old.skills(), ones.skills(), new.skills());
        let list = |s: &crate::catalog::Skills| s.names().collect::<Vec<_>>().join(" ");
        same(&mut d, &|| "skills".into(), list(so), list(s1), list(sn), false);
        for n in so.names() {
            same(&mut d, &|| format!("{n}_spec"), format!("{:?}", so.get(n)), format!("{:?}", s1.get(n)), format!("{:?}", sn.get(n)), false);
        }
        same(&mut d, &|| "skill reference".into(), crate::catalog::skills_help_of(so), crate::catalog::skills_help_of(s1), crate::catalog::skills_help_of(sn), false);
        for (l, spec) in old.law_specs() {
            // What the law says, and where; what it declares besides its name is checked below.
            let words = |x: Option<&crate::script::LawSpec>| format!("{:?}", x.map(|x| (&x.about, &x.cadence, &x.topic)));
            same(&mut d, &|| format!("{l}_law"), words(Some(spec)), words(ones.law_specs().get(l)), words(new.law_specs().get(l)), l == "food");
            let mut covers = new.law_specs()[l].covers.clone();
            covers.retain(|c| c != "carry_of");
            same(&mut d, &|| format!("{l}_law covers"), format!("{:?}", spec.covers), format!("{covers:?}"), format!("{covers:?}"), false);
        }
        // The food law declares the new carry law besides its name.
        assert!(new.law_specs()["food"].covers.iter().any(|c| c == "carry_of"));
        let w = [("seasons", "(the world's calendar)".to_string()), ("life", "(the world's life table)".to_string())];
        same(&mut d, &|| "world text".into(), old.world_text(&w), ones.world_text(&w), new.world_text(&w), true);
        println!("island: {} states; {} differ from main where something counts for less than one in a pack (carry); others: {}", d.states, d.carry, d.other.len());
        println!("  carry differences by what differs: {:?}", d.by);
        for s in &d.shown_carry {
            println!("  carry: {s}");
        }
        assert!(d.other.is_empty(), "differences that are not the carry change:\n  {}", d.other.join("\n  "));
        assert!(d.carry > 0, "the carry change shows");
    }
}
