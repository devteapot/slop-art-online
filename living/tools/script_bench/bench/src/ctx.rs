//! The context every script engine receives, field for field what living-rules' `to_map`
//! builds for Rhai: one walk over `SkillCtx` that each engine turns into its own values.

use crate::SkillCtx;

pub trait Sink {
    type Map;
    fn map(&mut self) -> Self::Map;
    fn int(&mut self, m: &mut Self::Map, k: &'static str, v: i64);
    fn float(&mut self, m: &mut Self::Map, k: &'static str, v: f64);
    fn str(&mut self, m: &mut Self::Map, k: &'static str, v: &str);
    fn bool(&mut self, m: &mut Self::Map, k: &'static str, v: bool);
    /// A time ago, or none (Rhai's unit `()`).
    fn ago(&mut self, m: &mut Self::Map, k: &'static str, v: Option<f32>);
    fn strs(&mut self, m: &mut Self::Map, k: &'static str, v: &[String]);
    /// A name → count map (inventory, senses).
    fn counts(&mut self, m: &mut Self::Map, k: &'static str, v: &[(String, u32)]);
    fn sub(&mut self, m: &mut Self::Map, k: &'static str, v: Self::Map);
}

pub fn walk<S: Sink>(s: &mut S, c: &SkillCtx, knack: &str) -> S::Map {
    let ac = &c.actor;
    let mut a = s.map();
    s.int(&mut a, "id", ac.id as i64);
    s.str(&mut a, "kind", &ac.kind);
    s.float(&mut a, "hp", ac.hp as f64);
    s.float(&mut a, "hunger", ac.hunger as f64);
    s.float(&mut a, "energy", ac.energy as f64);
    s.bool(&mut a, "near_fire", ac.near_fire);
    s.bool(&mut a, "near_shelter", ac.near_shelter);
    s.str(&mut a, "terrain", &ac.terrain);
    s.str(&mut a, "activity", &ac.activity);
    s.float(&mut a, "age", ac.age as f64);
    s.str(&mut a, "stage", &ac.stage);
    s.float(&mut a, "life", ac.life as f64);
    s.strs(&mut a, "knows", &ac.knows);
    s.counts(&mut a, "inv", &ac.inv);
    s.int(&mut a, "kin_near", ac.kin_near as i64);
    s.float(&mut a, "pasture", ac.pasture as f64);
    s.int(&mut a, "hurt_by", ac.hurt_by as i64);
    s.ago(&mut a, "hurt_ago", ac.hurt_ago);
    s.ago(&mut a, "yielded_ago", ac.yielded_ago);
    s.counts(&mut a, "sensed", &ac.sensed);
    s.bool(&mut a, "bold", ac.bold);
    s.int(&mut a, "room", ac.room as i64);
    for g in living_rules::genes::BODY {
        s.float(&mut a, g, living_rules::genes::gene(&ac.genes, g) as f64);
    }
    s.float(&mut a, "factor", living_rules::genes::skill_factor(&ac.genes, &ac.practice, &c.skill, knack) as f64);
    let tc = &c.target;
    let mut t = s.map();
    s.str(&mut t, "class", &tc.class);
    s.int(&mut t, "id", tc.id as i64);
    s.str(&mut t, "kind", &tc.kind);
    s.str(&mut t, "name", &tc.name);
    s.float(&mut t, "amount", tc.amount as f64);
    s.float(&mut t, "hp", tc.hp as f64);
    s.float(&mut t, "max_hp", tc.max_hp as f64);
    s.str(&mut t, "stage", &tc.stage);
    s.float(&mut t, "hurt_ago", tc.hurt_ago as f64);
    s.bool(&mut t, "alive", tc.alive);
    s.float(&mut t, "dist", tc.dist as f64);
    s.counts(&mut t, "inv", &tc.inv);
    s.strs(&mut t, "knows", &tc.knows);
    s.str(&mut t, "activity", &tc.activity);
    s.ago(&mut t, "yielded_ago", tc.yielded_ago);
    s.bool(&mut t, "near_fire", tc.near_fire);
    s.int(&mut t, "company", tc.company as i64);
    s.float(&mut t, "bearing", tc.bearing as f64);
    s.float(&mut t, "closing", tc.closing as f64);
    let mut r = s.map();
    s.bool(&mut r, "exists", c.routine.exists);
    s.int(&mut r, "ok", c.routine.ok as i64);
    s.int(&mut r, "failed", c.routine.failed as i64);
    s.float(&mut r, "changed_s", c.routine.changed_s as f64);
    let mut m = s.map();
    s.sub(&mut m, "actor", a);
    s.sub(&mut m, "target", t);
    s.sub(&mut m, "routine", r);
    s.str(&mut m, "item", &c.item);
    s.int(&mut m, "qty", c.qty as i64);
    s.bool(&mut m, "night", c.night);
    s.float(&mut m, "hour", c.hour as f64);
    s.str(&mut m, "season", &c.season);
    s.str(&mut m, "text", &c.text);
    s.str(&mut m, "topic", &c.topic);
    s.float(&mut m, "roll", c.roll as f64);
    s.bool(&mut m, "raining", c.raining);
    s.str(&mut m, "skill", &c.skill);
    m
}
