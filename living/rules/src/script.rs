//! Rhai skill runtime with a typed boundary.
//!
//! Scripts are functions only. For a skill `x` the runtime calls, when defined:
//! `x_check(a) -> ""|reason`, `x_duration(a) -> ms`, `x_done(a) -> [effect maps]`.
//! `rates(a)` returns need rates for the actor's current state; `move_speed(a)` tiles/second.
//! The context map `a` is built directly from typed facts (no JSON), and effects are
//! validated and applied by the authority.

use rhai::packages::Package;
use rhai::{Array, Dynamic, Engine, Map, Scope, AST};
use std::collections::HashSet;

#[derive(Clone, Debug, Default)]
pub struct ActorFacts {
    pub id: u32,
    pub kind: String,
    pub hp: f32,
    pub hunger: f32,
    pub energy: f32,
    pub near_fire: bool,
    pub near_shelter: bool,
    pub terrain: String,
    pub activity: String,
    pub inv: Vec<(String, u32)>,
    /// Age in in-world days.
    pub age: f32,
    /// Techniques this character knows how to do.
    pub knows: Vec<String>,
}

#[derive(Clone, Debug, Default)]
pub struct TargetFacts {
    /// `resource`, `structure`, `creature`, `place` or `none`.
    pub class: String,
    pub id: u64,
    pub kind: String,
    pub name: String,
    pub amount: f32,
    pub hp: f32,
    pub max_hp: f32,
    /// Milliseconds since the creature was last hurt (large when never).
    pub hurt_ago: f32,
    pub alive: bool,
    pub dist: f32,
    pub inv: Vec<(String, u32)>,
    pub knows: Vec<String>,
}

#[derive(Clone, Debug, Default)]
pub struct SkillCtx {
    pub actor: ActorFacts,
    pub target: TargetFacts,
    pub item: String,
    pub qty: u32,
    pub night: bool,
    pub hour: f32,
    pub season: String,
    pub text: String,
    pub topic: String,
    /// A fresh random number in [0, 1) from the authority (for chances).
    pub roll: f32,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Effect {
    /// Add items to the actor.
    Add { item: String, qty: u32 },
    /// Remove items from the actor (fails the action if missing).
    Remove { item: String, qty: u32 },
    /// Take units from the target resource.
    Harvest { qty: f32 },
    /// Change the actor's needs.
    Vitals { hp: f32, hunger: f32, energy: f32 },
    /// Damage the target creature.
    Damage { amount: f32 },
    /// Restore the target creature's health (tending wounds).
    Heal { amount: f32 },
    /// Move items from the actor to the target creature.
    Give { item: String, qty: u32 },
    /// Move items from the actor into the target structure.
    Store { item: String, qty: u32 },
    /// Move items from the target structure to the actor.
    Take { item: String, qty: u32 },
    /// Create a structure at the actor's position.
    Build { kind: String },
    /// Offer (or accept) starting a family with the target person.
    Bond,
    /// Make the species signal named by the action's item.
    Signal,
    /// The target person learns a technique from the actor.
    Teach { technique: String },
    /// The actor works out a technique.
    Learn { technique: String },
    /// Create the tablet or sign described by the action.
    Write,
    /// Read the tablet or sign the action resolved.
    Read,
    /// Grow a new berry bush where the actor stands.
    Plant,
    /// Propose a trade to the target.
    Offer,
    /// Accept the target's standing offer.
    Accept,
    Found,
    Join,
    Welcome,
    Leave,
}

/// World laws that parameterize the engine. Read once per script revision (the `laws()`
/// function), so they cost nothing per tick; defaults apply to anything a script omits.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Laws {
    pub sight_day: f32,
    pub sight_night: f32,
    pub sight_torch: f32,
    pub hearing: f32,
    pub fire_warmth: f32,
    pub shelter_warmth: f32,
    pub gestation_days: f32,
    pub bond_window_s: f32,
    pub crowd: f32,
    pub danger_near: f32,
    pub danger_far: f32,
    pub repeat_failure_s: f32,
}

impl Default for Laws {
    fn default() -> Self {
        Self {
            sight_day: crate::SIGHT,
            sight_night: crate::NIGHT_SIGHT,
            sight_torch: crate::TORCH_SIGHT,
            hearing: crate::HEARING,
            fire_warmth: 3.5,
            shelter_warmth: 2.5,
            gestation_days: 1.0,
            bond_window_s: 120.0,
            crowd: 6.0,
            danger_near: 8.0,
            danger_far: 12.0,
            repeat_failure_s: 120.0,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Rates {
    pub hunger_per_min: f32,
    pub energy_per_min: f32,
    pub hp_per_min: f32,
}

pub struct Scripts {
    engine: Engine,
    ast: AST,
    fns: HashSet<String>,
}

pub const MAX_SOURCE: usize = 64 * 1024;

fn engine() -> Engine {
    let mut e = Engine::new_raw();
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

impl Scripts {
    pub fn new(source: &str) -> Result<Self, String> {
        if source.len() > MAX_SOURCE {
            return Err("script source exceeds 64 KiB".into());
        }
        let engine = engine();
        let ast = engine.compile(source).map_err(|e| format!("script compile: {e}"))?.clone_functions_only();
        let fns = ast.iter_functions().map(|f| f.name.to_string()).collect();
        let s = Self { engine, ast, fns };
        // Required entry points.
        for f in ["rates", "move_speed"] {
            if !s.fns.contains(f) {
                return Err(format!("script must define `{f}(a)`"));
            }
        }
        Ok(s)
    }

    pub fn has(&self, f: &str) -> bool {
        self.fns.contains(f)
    }

    fn call(&self, f: &str, ctx: &SkillCtx) -> Result<Dynamic, String> {
        self.engine
            .call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (to_map(ctx),))
            .map_err(|e| format!("{f}: {e}"))
    }

    pub fn check(&self, skill: &str, ctx: &SkillCtx) -> Result<(), String> {
        let f = format!("{skill}_check");
        if !self.has(&f) {
            return Ok(());
        }
        let r = self.call(&f, ctx)?;
        let s = r.into_string().map_err(|t| format!("{f} must return a string, got {t}"))?;
        if s.is_empty() {
            Ok(())
        } else {
            Err(s)
        }
    }

    pub fn duration_ms(&self, skill: &str, ctx: &SkillCtx) -> Result<u64, String> {
        let f = format!("{skill}_duration");
        if !self.has(&f) {
            return Ok(1_000);
        }
        let v = number(&self.call(&f, ctx)?).ok_or_else(|| format!("{f} must return a number"))?;
        Ok(v.clamp(0.0, 600_000.0) as u64)
    }

    pub fn done(&self, skill: &str, ctx: &SkillCtx) -> Result<Vec<Effect>, String> {
        let f = format!("{skill}_done");
        if !self.has(&f) {
            return Ok(Vec::new());
        }
        let r = self.call(&f, ctx)?;
        let arr: Array = r.try_cast::<Array>().ok_or_else(|| format!("{f} must return an array"))?;
        arr.into_iter().map(effect).collect()
    }

    pub fn rates(&self, ctx: &SkillCtx) -> Result<Rates, String> {
        let m = self.call("rates", ctx)?.try_cast::<Map>().ok_or("rates must return a map")?;
        let g = |k: &str| m.get(k).and_then(number).unwrap_or(0.0) as f32;
        Ok(Rates { hunger_per_min: g("hunger"), energy_per_min: g("energy"), hp_per_min: g("hp") })
    }

    pub fn move_speed(&self, ctx: &SkillCtx) -> Result<f32, String> {
        let v = number(&self.call("move_speed", ctx)?).ok_or("move_speed must return a number")?;
        Ok((v as f32).clamp(0.2, 12.0))
    }

    pub fn laws(&self) -> Laws {
        let mut l = Laws::default();
        if !self.has("laws") {
            return l;
        }
        let Ok(m) = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "laws", ()).map(|d| d.try_cast::<Map>().unwrap_or_default()) else { return l };
        let g = |k: &str, d: f32| m.get(k).and_then(number).map(|v| v as f32).unwrap_or(d);
        l = Laws {
            sight_day: g("sight_day", l.sight_day),
            sight_night: g("sight_night", l.sight_night),
            sight_torch: g("sight_torch", l.sight_torch),
            hearing: g("hearing", l.hearing),
            fire_warmth: g("fire_warmth", l.fire_warmth),
            shelter_warmth: g("shelter_warmth", l.shelter_warmth),
            gestation_days: g("gestation_days", l.gestation_days),
            bond_window_s: g("bond_window_s", l.bond_window_s),
            crowd: g("crowd", l.crowd),
            danger_near: g("danger_near", l.danger_near),
            danger_far: g("danger_far", l.danger_far),
            repeat_failure_s: g("repeat_failure_s", l.repeat_failure_s),
        };
        l
    }

    /// Numeric function of one string argument, e.g. `max_hp("deer")`.
    pub fn num_of(&self, f: &str, arg: &str, default: f64) -> f64 {
        if !self.has(f) {
            return default;
        }
        self.engine
            .call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (arg.to_string(),))
            .ok()
            .and_then(|d| number(&d))
            .unwrap_or(default)
    }

    /// Generic numeric query, e.g. `attack_cooldown`.
    pub fn number(&self, f: &str, ctx: &SkillCtx, default: f64) -> f64 {
        if !self.has(f) {
            return default;
        }
        self.call(f, ctx).ok().and_then(|d| number(&d)).unwrap_or(default)
    }
}

fn number(d: &Dynamic) -> Option<f64> {
    if let Ok(i) = d.as_int() {
        return Some(i as f64);
    }
    d.as_float().ok()
}

fn inv_map(inv: &[(String, u32)]) -> Map {
    let mut m = Map::new();
    for (k, v) in inv {
        m.insert(k.as_str().into(), Dynamic::from_int(*v as i64));
    }
    m
}

fn to_map(c: &SkillCtx) -> Map {
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
    a.insert("knows".into(), c.actor.knows.iter().map(|k| Dynamic::from(k.clone())).collect::<Array>().into());
    a.insert("inv".into(), inv_map(&c.actor.inv).into());
    let mut t = Map::new();
    t.insert("class".into(), c.target.class.clone().into());
    t.insert("id".into(), Dynamic::from_int(c.target.id as i64));
    t.insert("kind".into(), c.target.kind.clone().into());
    t.insert("name".into(), c.target.name.clone().into());
    t.insert("amount".into(), f(c.target.amount));
    t.insert("hp".into(), f(c.target.hp));
    t.insert("max_hp".into(), f(c.target.max_hp));
    t.insert("hurt_ago".into(), f(c.target.hurt_ago));
    t.insert("alive".into(), c.target.alive.into());
    t.insert("dist".into(), f(c.target.dist));
    t.insert("inv".into(), inv_map(&c.target.inv).into());
    t.insert("knows".into(), c.target.knows.iter().map(|k| Dynamic::from(k.clone())).collect::<Array>().into());
    let mut m = Map::new();
    m.insert("actor".into(), a.into());
    m.insert("target".into(), t.into());
    m.insert("item".into(), c.item.clone().into());
    m.insert("qty".into(), Dynamic::from_int(c.qty as i64));
    m.insert("night".into(), c.night.into());
    m.insert("hour".into(), f(c.hour));
    m.insert("season".into(), c.season.clone().into());
    m.insert("text".into(), c.text.clone().into());
    m.insert("topic".into(), c.topic.clone().into());
    m.insert("roll".into(), f(c.roll));
    m
}

fn effect(d: Dynamic) -> Result<Effect, String> {
    let m = d.try_cast::<Map>().ok_or("effect must be a map")?;
    let s = |k: &str| m.get(k).and_then(|v| v.clone().into_string().ok()).unwrap_or_default();
    let n = |k: &str| m.get(k).and_then(number).unwrap_or(0.0);
    let qty = || {
        let q = n("qty");
        if q < 1.0 {
            Err("effect qty must be >= 1".to_string())
        } else {
            Ok(q as u32)
        }
    };
    Ok(match s("op").as_str() {
        "add" => Effect::Add { item: s("item"), qty: qty()? },
        "remove" => Effect::Remove { item: s("item"), qty: qty()? },
        "harvest" => Effect::Harvest { qty: n("qty") as f32 },
        "vitals" => Effect::Vitals { hp: n("hp") as f32, hunger: n("hunger") as f32, energy: n("energy") as f32 },
        "damage" => Effect::Damage { amount: n("amount") as f32 },
        "heal" => Effect::Heal { amount: n("amount") as f32 },
        "give" => Effect::Give { item: s("item"), qty: qty()? },
        "store" => Effect::Store { item: s("item"), qty: qty()? },
        "take" => Effect::Take { item: s("item"), qty: qty()? },
        "build" => Effect::Build { kind: s("kind") },
        "bond" => Effect::Bond,
        "signal" => Effect::Signal,
        "teach" => Effect::Teach { technique: s("technique") },
        "learn" => Effect::Learn { technique: s("technique") },
        "write" => Effect::Write,
        "read" => Effect::Read,
        "plant" => Effect::Plant,
        "offer" => Effect::Offer,
        "accept" => Effect::Accept,
        "found" => Effect::Found,
        "join" => Effect::Join,
        "welcome" => Effect::Welcome,
        "leave" => Effect::Leave,
        other => return Err(format!("unknown effect op `{other}`")),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scripts() -> Scripts {
        Scripts::new(include_str!("../../scripts/skills.rhai")).expect("skills compile")
    }

    fn ctx() -> SkillCtx {
        SkillCtx {
            actor: ActorFacts { id: 1, kind: "person".into(), hp: 100.0, hunger: 50.0, energy: 80.0, terrain: "grass".into(), ..Default::default() },
            ..Default::default()
        }
    }

    #[test]
    fn gather_berries_yields_items() {
        let s = scripts();
        let mut c = ctx();
        c.target = TargetFacts { class: "resource".into(), kind: "berry_bush".into(), amount: 3.0, ..Default::default() };
        assert!(s.check("gather", &c).is_ok());
        assert!(s.duration_ms("gather", &c).unwrap() > 0);
        let fx = s.done("gather", &c).unwrap();
        assert!(fx.contains(&Effect::Add { item: "berries".into(), qty: 1 }));
        c.target.amount = 0.0;
        assert!(s.check("gather", &c).is_err());
    }

    #[test]
    fn eat_requires_item_and_reduces_hunger() {
        let s = scripts();
        let mut c = ctx();
        c.item = "berries".into();
        assert!(s.check("eat", &c).is_err());
        c.actor.inv = vec![("berries".into(), 2)];
        assert!(s.check("eat", &c).is_ok());
        let fx = s.done("eat", &c).unwrap();
        assert!(fx.iter().any(|e| matches!(e, Effect::Vitals { hunger, .. } if *hunger < 0.0)));
    }

    #[test]
    fn rates_depend_on_activity_and_night() {
        let s = scripts();
        let mut c = ctx();
        let day = s.rates(&c).unwrap();
        assert!(day.hunger_per_min > 0.0);
        c.actor.activity = "sleep".into();
        assert!(s.rates(&c).unwrap().energy_per_min > 0.0);
        c.actor.activity = String::new();
        c.actor.hunger = 80.0; // no regeneration, so the cold alone shows
        c.night = true;
        assert!(s.rates(&c).unwrap().hp_per_min < 0.0, "cold nights hurt without fire or shelter");
        c.actor.near_fire = true;
        assert!(s.rates(&c).unwrap().hp_per_min >= 0.0);
    }
}
