//! The floor: the laws written in Rust in the same module, reading `SkillCtx` directly.

use crate::{Effect, Engine, Rates, SkillCtx, StrikeOut};

include!("../../port.rs");

law_fns!(SkillCtx);

pub struct Native;

impl Engine for Native {
    fn rates(&mut self, c: &SkillCtx) -> Rates {
        // Written in Rust, a law reads only what it needs: here two genes, no skill factor.
        use living_rules::genes::gene;
        let b = Body { endurance: gene(&c.actor.genes, "endurance") as f64, vitality: gene(&c.actor.genes, "vitality") as f64, ..Default::default() };
        rates(c, &b)
    }
    fn strike(&mut self, c: &SkillCtx) -> StrikeOut {
        strike(c, &crate::body_of(c)).map_err(str::to_string)
    }
    fn cooldown(&mut self, skill: &str) -> f64 {
        combat_cooldown(skill)
    }
    fn perceived(&mut self, p: &crate::RegardIn) -> crate::Regard {
        // skills.rhai's `perceived_of` is the engine's own default rule.
        crate::Regard::default_for(p)
    }
}
