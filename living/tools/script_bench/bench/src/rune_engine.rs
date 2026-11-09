//! Rune 0.14: the laws ported to Rune (scripts/laws.rn), compiled once to a Unit, run by its
//! VM; the context is a Rune object shaped like Rhai's map.

use crate::ctx::{walk, Sink};
use crate::{Engine, Rates, SkillCtx, StrikeOut};
use rune::alloc::String as RString;
use rune::runtime::{Object, Value, Vec as RVec};
use rune::{Context, Diagnostics, Hash, Source, Sources, Vm};
use std::sync::Arc;

pub const SOURCE: &str = include_str!("../../scripts/laws.rn");

pub struct RuneEngine {
    vm: Vm,
    rates: Hash,
    check: Hash,
    done: Hash,
    cooldown: Hash,
}

fn e(x: impl std::fmt::Display) -> String {
    x.to_string()
}

impl RuneEngine {
    pub fn new() -> Result<Self, String> {
        let context = Context::with_default_modules().map_err(e)?;
        let runtime = Arc::new(context.runtime().map_err(e)?);
        let mut sources = Sources::new();
        sources.insert(Source::memory(SOURCE).map_err(e)?).map_err(e)?;
        let mut diagnostics = Diagnostics::new();
        let unit = rune::prepare(&mut sources).with_context(&context).with_diagnostics(&mut diagnostics).build();
        let unit = unit.map_err(|err| format!("{err}: {:?}", diagnostics.diagnostics()))?;
        Ok(Self {
            vm: Vm::new(runtime, Arc::new(unit)),
            rates: Hash::type_hash(["rates"]),
            check: Hash::type_hash(["strike_check"]),
            done: Hash::type_hash(["strike_done"]),
            cooldown: Hash::type_hash(["combat_cooldown"]),
        })
    }

    fn arg(c: &SkillCtx, knack: &str) -> Object {
        walk(&mut RuneSink, c, knack)
    }
}

fn key(k: &str) -> RString {
    RString::try_from(k).unwrap()
}

fn sval(v: &str) -> Value {
    rune::to_value(RString::try_from(v).unwrap()).unwrap()
}

struct RuneSink;

impl Sink for RuneSink {
    type Map = Object;
    fn map(&mut self) -> Object {
        Object::new()
    }
    fn int(&mut self, m: &mut Object, k: &'static str, v: i64) {
        m.insert(key(k), Value::from(v)).unwrap();
    }
    fn float(&mut self, m: &mut Object, k: &'static str, v: f64) {
        m.insert(key(k), Value::from(v)).unwrap();
    }
    fn str(&mut self, m: &mut Object, k: &'static str, v: &str) {
        m.insert(key(k), sval(v)).unwrap();
    }
    fn bool(&mut self, m: &mut Object, k: &'static str, v: bool) {
        m.insert(key(k), Value::from(v)).unwrap();
    }
    fn ago(&mut self, m: &mut Object, k: &'static str, v: Option<f32>) {
        m.insert(key(k), rune::to_value(v.map(|x| x as f64)).unwrap()).unwrap();
    }
    fn strs(&mut self, m: &mut Object, k: &'static str, v: &[String]) {
        let mut l = RVec::new();
        for s in v {
            l.push(sval(s)).unwrap();
        }
        m.insert(key(k), rune::to_value(l).unwrap()).unwrap();
    }
    fn counts(&mut self, m: &mut Object, k: &'static str, v: &[(String, u32)]) {
        let mut o = Object::new();
        for (name, n) in v {
            o.insert(key(name), Value::from(*n as i64)).unwrap();
        }
        m.insert(key(k), rune::to_value(o).unwrap()).unwrap();
    }
    fn sub(&mut self, m: &mut Object, k: &'static str, v: Object) {
        m.insert(key(k), rune::to_value(v).unwrap()).unwrap();
    }
}

fn num(o: &Object, k: &str) -> f64 {
    match o.get(k) {
        Some(v) => rune::from_value::<f64>(v.clone()).or_else(|_| rune::from_value::<i64>(v.clone()).map(|i| i as f64)).unwrap_or(0.0),
        None => 0.0,
    }
}

impl Engine for RuneEngine {
    fn rates(&mut self, c: &SkillCtx) -> Rates {
        let v = self.vm.call(self.rates, (Self::arg(c, ""),)).expect("rates");
        let o: Object = rune::from_value(v).expect("rates must return an object");
        Rates { hunger_per_min: num(&o, "hunger") as f32, energy_per_min: num(&o, "energy") as f32, hp_per_min: num(&o, "hp") as f32 }
    }
    fn strike(&mut self, c: &SkillCtx) -> StrikeOut {
        let knack = crate::knack_of(&c.skill);
        let why: String = rune::from_value(self.vm.call(self.check, (Self::arg(c, knack),)).map_err(e)?).map_err(e)?;
        if !why.is_empty() {
            return Err(why);
        }
        let fx: Vec<Object> = rune::from_value(self.vm.call(self.done, (Self::arg(c, knack),)).map_err(e)?).map_err(e)?;
        fx.iter()
            .map(|o| {
                let op: String = o.get("op").and_then(|v| rune::from_value(v.clone()).ok()).unwrap_or_default();
                crate::effect_from(&op, |k| num(o, k))
            })
            .collect()
    }
    fn cooldown(&mut self, skill: &str) -> f64 {
        let v = self.vm.call(self.cooldown, (sval(skill),)).expect("cooldown");
        rune::from_value::<i64>(v).map(|i| i as f64).unwrap_or(0.0)
    }
}
