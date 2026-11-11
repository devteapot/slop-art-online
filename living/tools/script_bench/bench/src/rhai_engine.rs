//! Rhai exactly as the authority embeds it: living-rules' `Scripts` over the real
//! living/scripts/skills.rhai (same engine settings, AST compiled once).

use crate::{Engine, Rates, SkillCtx, StrikeOut};
use living_rules::script::Scripts;

pub const SOURCE: &str = include_str!("../../../../scripts/skills.rhai");

pub struct RhaiEmbed {
    s: Scripts,
}

impl RhaiEmbed {
    pub fn new() -> Result<Self, String> {
        Ok(Self { s: Scripts::new(SOURCE)? })
    }
}

impl Engine for RhaiEmbed {
    fn rates(&mut self, c: &SkillCtx) -> Rates {
        self.s.rates(c).expect("rates")
    }
    fn strike(&mut self, c: &SkillCtx) -> StrikeOut {
        self.s.check("strike", c)?;
        self.s.done("strike", c)
    }
    fn cooldown(&mut self, skill: &str) -> f64 {
        self.s.num_of("combat_cooldown", skill, 0.0)
    }
    fn rates_law(&mut self, c: &SkillCtx) -> Rates {
        self.s.rates_unshared(c).expect("rates")
    }
    fn perceived(&mut self, p: &crate::RegardIn) -> crate::Regard {
        self.s.perceived_of(p)
    }
    fn hook(&mut self, c: &SkillCtx) -> StrikeOut {
        self.s.hook("give", c)
    }
    fn senses(&mut self, c: &SkillCtx, shared: bool) -> (f32, f32) {
        let s = if shared { self.s.senses(c) } else { self.s.senses_unshared(c) }.expect("senses");
        (s.sight, s.hearing)
    }
}

/// Diagnostic: the context map alone. `Scripts::call` builds `to_map(ctx, knack)` for every
/// script call; this is a copy of that function (private in living-rules), built and dropped.
/// A strike is two script calls (check, done), so it builds two maps.
pub struct MapOnly;

impl Engine for MapOnly {
    fn rates(&mut self, c: &SkillCtx) -> Rates {
        let m = to_map(c, "");
        Rates { hunger_per_min: m.len() as f32, ..Default::default() }
    }
    fn strike(&mut self, c: &SkillCtx) -> StrikeOut {
        let a = to_map(c, "attack");
        let b = to_map(c, "attack");
        Err(format!("{}", a.len() + b.len()))
    }
    fn cooldown(&mut self, skill: &str) -> f64 {
        // num_of builds no map: only the argument string.
        let s = rhai::Dynamic::from(skill.to_string());
        s.is_string() as u8 as f64
    }
}

use rhai::{Array, Dynamic, Map, Scope, AST};

/// Copy of living-rules `script::engine()` (972aefd): the same limits and disabled symbols.
fn engine() -> rhai::Engine {
    use rhai::packages::Package;
    let mut e = rhai::Engine::new_raw();
    rhai::packages::StandardPackage::new().register_into_engine(&mut e);
    e.set_max_operations(20_000);
    e.set_max_call_levels(16);
    e.set_max_expr_depths(32, 24);
    e.set_max_string_size(4_096);
    e.set_max_array_size(256);
    e.set_max_map_size(256);
    for symbol in ["eval", "import", "print", "debug"] {
        e.disable_symbol(symbol);
    }
    e
}

pub struct RhaiLean {
    engine: rhai::Engine,
    ast: AST,
}

impl RhaiLean {
    pub fn new() -> Result<Self, String> {
        let engine = engine();
        let ast = engine.compile(SOURCE).map_err(|e| e.to_string())?.clone_functions_only();
        Ok(Self { engine, ast })
    }
    fn call(&self, f: &str, m: Map) -> Result<Dynamic, String> {
        self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (m,)).map_err(|e| format!("{f}: {e}"))
    }
}

fn num(d: &Dynamic) -> f64 {
    d.as_int().map(|i| i as f64).or_else(|_| d.as_float()).unwrap_or(0.0)
}

/// Only what `rates(a)` reads.
fn lean_rates(c: &SkillCtx) -> Map {
    let f = |v: f32| Dynamic::from_float(v as f64);
    let g = |n: &str| Dynamic::from_float(living_rules::genes::gene(&c.actor.genes, n) as f64);
    let mut a = Map::new();
    a.insert("kind".into(), c.actor.kind.clone().into());
    a.insert("activity".into(), c.actor.activity.clone().into());
    a.insert("stage".into(), c.actor.stage.clone().into());
    a.insert("hunger".into(), f(c.actor.hunger));
    a.insert("energy".into(), f(c.actor.energy));
    a.insert("near_fire".into(), c.actor.near_fire.into());
    a.insert("near_shelter".into(), c.actor.near_shelter.into());
    a.insert("endurance".into(), g("endurance"));
    a.insert("vitality".into(), g("vitality"));
    a.insert("inv".into(), inv_map(&c.actor.inv).into());
    let mut m = Map::new();
    m.insert("actor".into(), a.into());
    m.insert("night".into(), c.night.into());
    m.insert("raining".into(), c.raining.into());
    m.insert("season".into(), c.season.clone().into());
    m
}

/// Only what `strike_check(a)` and `strike_done(a)` read.
fn lean_strike(c: &SkillCtx) -> Map {
    let f = |v: f32| Dynamic::from_float(v as f64);
    let ago = |v: Option<f32>| v.map_or(Dynamic::UNIT, |x| Dynamic::from_float(x as f64));
    let mut a = Map::new();
    a.insert("id".into(), Dynamic::from_int(c.actor.id as i64));
    a.insert("kind".into(), c.actor.kind.clone().into());
    a.insert("stage".into(), c.actor.stage.clone().into());
    a.insert("hunger".into(), f(c.actor.hunger));
    a.insert("energy".into(), f(c.actor.energy));
    a.insert("inv".into(), inv_map(&c.actor.inv).into());
    a.insert("hurt_by".into(), Dynamic::from_int(c.actor.hurt_by as i64));
    a.insert("hurt_ago".into(), ago(c.actor.hurt_ago));
    a.insert("yielded_ago".into(), ago(c.actor.yielded_ago));
    a.insert("sensed".into(), inv_map(&c.actor.sensed).into());
    a.insert("bold".into(), c.actor.bold.into());
    a.insert("strength".into(), f(living_rules::genes::gene(&c.actor.genes, "strength")));
    a.insert("factor".into(), f(living_rules::genes::skill_factor(&c.actor.genes, &c.actor.practice, &c.skill, crate::knack_of(&c.skill))));
    let mut t = Map::new();
    t.insert("class".into(), c.target.class.clone().into());
    t.insert("id".into(), Dynamic::from_int(c.target.id as i64));
    t.insert("kind".into(), c.target.kind.clone().into());
    t.insert("hp".into(), f(c.target.hp));
    t.insert("max_hp".into(), f(c.target.max_hp));
    t.insert("stage".into(), c.target.stage.clone().into());
    t.insert("alive".into(), c.target.alive.into());
    t.insert("inv".into(), inv_map(&c.target.inv).into());
    t.insert("activity".into(), c.target.activity.clone().into());
    t.insert("near_fire".into(), c.target.near_fire.into());
    t.insert("company".into(), Dynamic::from_int(c.target.company as i64));
    let mut m = Map::new();
    m.insert("actor".into(), a.into());
    m.insert("target".into(), t.into());
    m.insert("night".into(), c.night.into());
    m.insert("skill".into(), c.skill.clone().into());
    m
}

impl Engine for RhaiLean {
    fn rates(&mut self, c: &SkillCtx) -> Rates {
        // Since rates(a) returns parameters (rules/src/script.rs `NeedLaw`), decode them the
        // authority's way.
        let d = self.call("rates", lean_rates(c)).expect("rates");
        living_rules::script::NeedLaw::from_dynamic(d).expect("rates").rates(&c.actor)
    }
    fn strike(&mut self, c: &SkillCtx) -> StrikeOut {
        let why = self.call("strike_check", lean_strike(c))?.into_string().map_err(|t| format!("strike_check returned {t}"))?;
        if !why.is_empty() {
            return Err(why);
        }
        let fx = self.call("strike_done", lean_strike(c))?.try_cast::<Array>().ok_or("strike_done must return an array")?;
        fx.into_iter()
            .map(|d| {
                let m = d.try_cast::<Map>().ok_or("effect must be a map")?;
                let op = m.get("op").and_then(|v| v.clone().into_string().ok()).unwrap_or_default();
                crate::effect_from(&op, |k| m.get(k).map(num).unwrap_or(0.0))
            })
            .collect()
    }
    fn cooldown(&mut self, skill: &str) -> f64 {
        self.call_str("combat_cooldown", skill)
    }
}

impl RhaiLean {
    fn call_str(&self, f: &str, arg: &str) -> f64 {
        self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (arg.to_string(),)).map(|d| num(&d)).unwrap_or(0.0)
    }
}

fn inv_map(inv: &[(String, u32)]) -> Map {
    let mut m = Map::new();
    for (k, v) in inv {
        m.insert(k.as_str().into(), Dynamic::from_int(*v as i64));
    }
    m
}

/// Copy of living-rules `script::to_map` (2026-11-09, 972aefd).
pub fn to_map(c: &SkillCtx, knack: &str) -> Map {
    let f = |v: f32| Dynamic::from_float(v as f64);
    let mut a = Map::new();
    a.insert("id".into(), Dynamic::from_int(c.actor.id as i64));
    a.insert("kind".into(), c.actor.kind.clone().into());
    a.insert("hp".into(), f(c.actor.hp));
    a.insert("hunger".into(), f(c.actor.hunger));
    a.insert("energy".into(), f(c.actor.energy));
    a.insert("near_fire".into(), c.actor.near_fire.into());
    a.insert("near_shelter".into(), c.actor.near_shelter.into());
    a.insert("terrain".into(), c.actor.terrain.clone().into());
    a.insert("activity".into(), c.actor.activity.clone().into());
    a.insert("age".into(), f(c.actor.age));
    a.insert("stage".into(), c.actor.stage.clone().into());
    a.insert("life".into(), f(c.actor.life));
    a.insert("knows".into(), c.actor.knows.iter().map(|k| Dynamic::from(k.clone())).collect::<Array>().into());
    a.insert("inv".into(), inv_map(&c.actor.inv).into());
    a.insert("kin_near".into(), Dynamic::from_int(c.actor.kin_near as i64));
    a.insert("pasture".into(), f(c.actor.pasture));
    let ago = |v: Option<f32>| v.map_or(Dynamic::UNIT, |x| Dynamic::from_float(x as f64));
    a.insert("hurt_by".into(), Dynamic::from_int(c.actor.hurt_by as i64));
    a.insert("hurt_ago".into(), ago(c.actor.hurt_ago));
    a.insert("yielded_ago".into(), ago(c.actor.yielded_ago));
    a.insert("sensed".into(), inv_map(&c.actor.sensed).into());
    a.insert("bold".into(), c.actor.bold.into());
    a.insert("room".into(), Dynamic::from_int(c.actor.room as i64));
    for g in living_rules::genes::BODY {
        a.insert(g.into(), f(living_rules::genes::gene(&c.actor.genes, g)));
    }
    a.insert("factor".into(), f(living_rules::genes::skill_factor(&c.actor.genes, &c.actor.practice, &c.skill, knack)));
    let mut t = Map::new();
    t.insert("class".into(), c.target.class.clone().into());
    t.insert("id".into(), Dynamic::from_int(c.target.id as i64));
    t.insert("kind".into(), c.target.kind.clone().into());
    t.insert("name".into(), c.target.name.clone().into());
    t.insert("amount".into(), f(c.target.amount));
    t.insert("hp".into(), f(c.target.hp));
    t.insert("max_hp".into(), f(c.target.max_hp));
    t.insert("stage".into(), c.target.stage.clone().into());
    t.insert("hurt_ago".into(), f(c.target.hurt_ago));
    t.insert("alive".into(), c.target.alive.into());
    t.insert("dist".into(), f(c.target.dist));
    t.insert("inv".into(), inv_map(&c.target.inv).into());
    t.insert("knows".into(), c.target.knows.iter().map(|k| Dynamic::from(k.clone())).collect::<Array>().into());
    t.insert("activity".into(), c.target.activity.clone().into());
    t.insert("yielded_ago".into(), ago(c.target.yielded_ago));
    t.insert("near_fire".into(), c.target.near_fire.into());
    t.insert("company".into(), Dynamic::from_int(c.target.company as i64));
    t.insert("bearing".into(), f(c.target.bearing));
    t.insert("closing".into(), f(c.target.closing));
    let mut r = Map::new();
    r.insert("exists".into(), c.routine.exists.into());
    r.insert("ok".into(), Dynamic::from_int(c.routine.ok as i64));
    r.insert("failed".into(), Dynamic::from_int(c.routine.failed as i64));
    r.insert("changed_s".into(), f(c.routine.changed_s));
    let mut m = Map::new();
    m.insert("actor".into(), a.into());
    m.insert("target".into(), t.into());
    m.insert("routine".into(), r.into());
    m.insert("item".into(), c.item.clone().into());
    m.insert("qty".into(), Dynamic::from_int(c.qty as i64));
    m.insert("night".into(), c.night.into());
    m.insert("hour".into(), f(c.hour));
    m.insert("season".into(), c.season.clone().into());
    m.insert("text".into(), c.text.clone().into());
    m.insert("topic".into(), c.topic.clone().into());
    m.insert("roll".into(), f(c.roll));
    m.insert("raining".into(), c.raining.into());
    m.insert("skill".into(), c.skill.clone().into());
    m
}

/// Rhai operations per call (the unit of `set_max_operations`, 20,000 in the authority), the
/// largest over the fixtures: (rates, strike_check, strike_done, combat_cooldown).
pub fn ops_per_law(fx: &crate::fixtures::Fixtures) -> [u64; 4] {
    use std::sync::atomic::{AtomicU64, Ordering};
    static OPS: AtomicU64 = AtomicU64::new(0);
    let mut engine = engine();
    engine.on_progress(|n| {
        OPS.fetch_max(n, Ordering::Relaxed);
        None
    });
    let ast = engine.compile(SOURCE).unwrap().clone_functions_only();
    let mut out = [0u64; 4];
    let mut measure = |i: usize, f: &str, m: Map| {
        OPS.store(0, Ordering::Relaxed);
        let _ = engine.call_fn::<Dynamic>(&mut Scope::new(), &ast, f, (m,));
        out[i] = out[i].max(OPS.load(Ordering::Relaxed));
    };
    for c in &fx.rates {
        measure(0, "rates", to_map(c, ""));
    }
    for c in &fx.strike {
        measure(1, "strike_check", to_map(c, "attack"));
        measure(2, "strike_done", to_map(c, "attack"));
    }
    drop(measure);
    for s in fx.skills {
        OPS.store(0, Ordering::Relaxed);
        let _ = engine.call_fn::<Dynamic>(&mut Scope::new(), &ast, "combat_cooldown", (s.to_string(),));
        out[3] = out[3].max(OPS.load(Ordering::Relaxed));
    }
    out
}
