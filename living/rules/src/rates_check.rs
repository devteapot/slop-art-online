//! The rates written in game time since rates-2 (spoiling, regrowth of resources and grass,
//! traps, remains) against the same laws as the script before it wrote them, per real minute and
//! real second: on the shipped 12-minute day every number the authority works with must be bit
//! for bit what it was (docs/CULLET_RULES.md, "The labs are unchanged").
//!
//! ```text
//! git show f2d803fa:living/scripts/skills.rhai > /tmp/old-skills.rhai
//! LIVING_OLD_SKILLS=/tmp/old-skills.rhai cargo test -p living-rules rates_are_bit_identical -- --ignored --nocapture
//! ```
//!
//! Each side computes exactly what the authority computes from the law: a stack's expected loss in
//! one spoiling sweep (`tick::spoil`, by owner: a pack by carrier kind, or a structure by kind), a
//! resource's or a pasture's amount after some growing time (`common::resource_now`,
//! `pasture_now`), a trap's catches after some time (`common::trap_catch`) and when remains are
//! due (`act::die`). The old side reads the old laws by name as the authority did.

#[cfg(test)]
mod tests {
    use crate::script::Scripts;

    const NEW: &str = include_str!("../../scripts/skills.rhai");

    fn old() -> Option<Scripts> {
        let path = std::env::var("LIVING_OLD_SKILLS").ok()?;
        let src = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{path}: {e}"));
        Some(Scripts::new(&src).expect("the old script compiles"))
    }

    #[test]
    #[ignore = "needs LIVING_OLD_SKILLS: the script before rates-2 (see the module's docs)"]
    fn rates_are_bit_identical() {
        let Some(old) = old() else { panic!("set LIVING_OLD_SKILLS to the old skills.rhai") };
        let new = Scripts::new(NEW).unwrap();
        assert!(!old.has("spoil_per_h") && old.has("spoil_rate") && new.has("spoil_per_h") && !new.has("spoil_rate"), "the old script writes real time, the new game time");
        let mut states = 0u64;
        let mut differ: Vec<String> = Vec::new();
        let mut same = |what: String, a: u64, b: u64| {
            states += 1;
            if a != b && differ.len() < 20 {
                differ.push(format!("{what}: {a:#x} != {b:#x}"));
            }
        };
        let names = |s: &Scripts, t: &str| s.tables().names(t).to_vec();
        let mut items = names(&new, "items");
        items.extend(["meat", "fish", "unknown_thing", ""].map(String::from));
        let mut structures = names(&new, "structures");
        structures.push("remains".into());
        let carriers = ["person", "deer", "wolf", "no_such_kind"];
        let qtys = [1u32, 2, 3, 5, 7, 10, 16, 33, 64, 100, 255, 1000, 4096, 65_535];
        // Spoiling: one sweep's expected loss of a stack, in a pack and in each kind of structure.
        for item in &items {
            let (ro, rn) = (old.num_of("spoil_rate", item, 0.0) as f32, new.spoil_per_min(item) as f32);
            same(format!("spoil_rate({item})"), ro.to_bits() as u64, rn.to_bits() as u64);
            for q in qtys {
                for c in carriers {
                    let (so, sn) = (old.num_of("carried_spoil", c, 1.0) as f32, new.num_of("carried_spoil", c, 1.0) as f32);
                    same(format!("{q} {item} carried by a {c}"), (q as f32 * (ro * so)).to_bits() as u64, (q as f32 * (rn * sn)).to_bits() as u64);
                }
                for k in &structures {
                    let (ko, kn) = (old.num_of("kept_spoil", k, 1.0 / 3.0) as f32, new.num_of("kept_spoil", k, 1.0 / 3.0) as f32);
                    same(format!("{q} {item} kept in a {k}"), (q as f32 * (ro * ko)).to_bits() as u64, (q as f32 * (rn * kn)).to_bits() as u64);
                }
            }
        }
        // Regrowth: a node's amount after growing time, from empty and from part full.
        let mut kinds = names(&new, "resources");
        kinds.push("no_such_resource".into());
        let grow_ms = [0u64, 1, 999, 1_000, 30_000, 59_999, 60_000, 61_234, 600_000, 720_000, 3_600_000, 86_400_000];
        for k in &kinds {
            for default in [0.5f64, 1.0] {
                let (go, gn) = (old.num_of("regrow", k, default) as f32, new.regrow_per_min(k, default) as f32);
                same(format!("regrow({k}) default {default}"), go.to_bits() as u64, gn.to_bits() as u64);
                for amount in [0.0f32, 0.37, 2.0, 4.99] {
                    for g in grow_ms {
                        let (a, b) = ((amount + go * g as f32 / 60_000.0).min(8.0), (amount + gn * g as f32 / 60_000.0).min(8.0));
                        same(format!("{k} from {amount} after {g} ms"), a.to_bits() as u64, b.to_bits() as u64);
                    }
                }
            }
        }
        // Grass: a chunk's regrowth (its grassy tiles times the law) and its amount after a while.
        let (po, pn) = (old.laws().pasture_regen, new.laws().pasture_regen);
        for tiles in 0..=256u32 {
            let (ro, rn) = (tiles as f32 * po, tiles as f32 * pn);
            same(format!("pasture of {tiles} tiles"), ro.to_bits() as u64, rn.to_bits() as u64);
            for g in grow_ms {
                let max = tiles as f32 * 0.02;
                same(format!("pasture of {tiles} tiles after {g} ms"), (ro * g as f32 / 60_000.0).min(max).to_bits() as u64, (rn * g as f32 / 60_000.0).min(max).to_bits() as u64);
            }
        }
        // Traps: catches after a while.
        let (to, tn) = ((old.num_of("trap_every_s", "meat", 240.0) * 1000.0) as u64, new.trap_every_ms() as u64);
        same("trap_every".into(), to, tn);
        for since in (0..2_000_000u64).step_by(7_919) {
            same(format!("trap catches after {since} ms"), since / to.max(1), since / tn.max(1));
        }
        // Remains: when they are due, by kind.
        for c in carriers {
            let (ro, rn) = ((old.num_of("remains_s", c, 1800.0).max(0.0) * 1000.0) as u64, new.remains_ms(c).max(0.0) as u64);
            for now in [0u64, 1, 123_456_789, 1_700_000_000_000] {
                same(format!("remains of a {c} died at {now}"), now + ro, now + rn);
            }
        }
        // Need rates (rates-2 asks `cold` and `wet` once each in `rates`): every kind, stage and
        // activity in each combination of cloak, fire, shelter, night, winter and rain, at five
        // levels of hunger and energy, as rules-1 compared them.
        use crate::script::{ActorFacts, SkillCtx};
        for kind in ["person", "deer", "wolf"] {
            for stage in ["infant", "child", "adult", "elder"] {
                for activity in ["", "sleep", "rest", "block", "walk"] {
                    for bits in 0..64u32 {
                        for (hunger, energy) in [(0.0, 100.0), (40.0, 60.0), (69.9, 15.1), (100.0, 0.0), (120.0, 5.0)] {
                            let b = |i: u32| bits & (1 << i) != 0;
                            let inv = if b(0) { vec![("cloak".to_string(), 1)] } else { vec![] };
                            let actor = ActorFacts { id: 1, kind: kind.into(), stage: stage.into(), activity: activity.into(), hunger, energy, hp: 50.0, inv, near_fire: b(1), near_shelter: b(2), terrain: "grass".into(), ..Default::default() };
                            let c = SkillCtx { actor, night: b(3), dark: if b(3) { 1.0 } else { 0.0 }, season: if b(4) { "winter" } else { "summer" }.into(), raining: b(5), ..Default::default() };
                            let (ro, rn) = (old.rates_unshared(&c).unwrap(), new.rates_unshared(&c).unwrap());
                            let bits_of = |r: &crate::script::Rates| (r.hunger_per_min.to_bits() as u64) << 32 ^ (r.energy_per_min.to_bits() as u64) << 16 ^ r.hp_per_min.to_bits() as u64;
                            same(format!("rates of a {stage} {kind} {activity:?} bits {bits:06b} at {hunger}/{energy}"), bits_of(&ro), bits_of(&rn));
                            let (so, sn) = (old.duration_ms("sleep", &c), new.duration_ms("sleep", &c));
                            same(format!("sleep of a {stage} {kind} bits {bits:06b} at {energy}"), so.unwrap_or(u64::MAX), sn.unwrap_or(u64::MAX));
                        }
                    }
                }
            }
        }
        // What minds are told of food, making and remains: the same words.
        for (name, l) in new.law_specs() {
            let o = old.law_specs().get(name).map(|l| l.about.clone()).unwrap_or_default();
            same(format!("the words of {name}_law"), (o == l.about) as u64, 1);
        }
        println!("rates-2 against the old script, 12-minute day: {states} states compared, {} differ", differ.len());
        assert!(differ.is_empty(), "{differ:#?}");
    }
}
