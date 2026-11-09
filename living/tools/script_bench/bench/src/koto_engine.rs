//! Koto 0.16: a pure-Rust scripting language made for embedding in Rust (scripts/laws.koto);
//! the context is a Koto map shaped like Rhai's.

use crate::ctx::{walk, Sink};
use crate::{Engine, Rates, SkillCtx, StrikeOut};
use koto::prelude::*;

pub const SOURCE: &str = include_str!("../../scripts/laws.koto");

pub struct KotoEngine {
    koto: Koto,
    rates: KValue,
    check: KValue,
    done: KValue,
    cooldown: KValue,
}

fn e(x: impl std::fmt::Display) -> String {
    x.to_string()
}

impl KotoEngine {
    pub fn new() -> Result<Self, String> {
        let mut koto = Koto::new();
        koto.compile_and_run(SOURCE).map_err(e)?;
        let get = |k: &Koto, name: &str| k.exports().get(name).ok_or_else(|| format!("laws.koto must export {name}"));
        Ok(Self { rates: get(&koto, "rates")?, check: get(&koto, "strike_check")?, done: get(&koto, "strike_done")?, cooldown: get(&koto, "combat_cooldown")?, koto })
    }
}

struct KSink;

impl Sink for KSink {
    type Map = KMap;
    fn map(&mut self) -> KMap {
        KMap::with_capacity(32)
    }
    fn int(&mut self, m: &mut KMap, k: &'static str, v: i64) {
        m.insert(k, KValue::Number(v.into()));
    }
    fn float(&mut self, m: &mut KMap, k: &'static str, v: f64) {
        m.insert(k, KValue::Number(v.into()));
    }
    fn str(&mut self, m: &mut KMap, k: &'static str, v: &str) {
        m.insert(k, v);
    }
    fn bool(&mut self, m: &mut KMap, k: &'static str, v: bool) {
        m.insert(k, v);
    }
    fn ago(&mut self, m: &mut KMap, k: &'static str, v: Option<f32>) {
        m.insert(k, v.map_or(KValue::Null, |x| KValue::Number((x as f64).into())));
    }
    fn strs(&mut self, m: &mut KMap, k: &'static str, v: &[String]) {
        let l: Vec<KValue> = v.iter().map(|s| KValue::from(s.as_str())).collect();
        m.insert(k, KList::from_slice(&l));
    }
    fn counts(&mut self, m: &mut KMap, k: &'static str, v: &[(String, u32)]) {
        let o = KMap::with_capacity(v.len());
        for (name, n) in v {
            o.insert(name.as_str(), KValue::Number((*n as i64).into()));
        }
        m.insert(k, o);
    }
    fn sub(&mut self, m: &mut KMap, k: &'static str, v: KMap) {
        m.insert(k, v);
    }
}

fn num(v: Option<KValue>) -> f64 {
    match v {
        Some(KValue::Number(n)) => f64::from(n),
        _ => 0.0,
    }
}

impl Engine for KotoEngine {
    fn rates(&mut self, c: &SkillCtx) -> Rates {
        let a = walk(&mut KSink, c, "");
        let KValue::Map(m) = self.koto.call_function(self.rates.clone(), &[KValue::Map(a)]).expect("rates") else { panic!("rates must return a map") };
        Rates { hunger_per_min: num(m.get("hunger")) as f32, energy_per_min: num(m.get("energy")) as f32, hp_per_min: num(m.get("hp")) as f32 }
    }
    fn strike(&mut self, c: &SkillCtx) -> StrikeOut {
        let knack = crate::knack_of(&c.skill);
        let a = walk(&mut KSink, c, knack);
        match self.koto.call_function(self.check.clone(), &[KValue::Map(a)]).map_err(e)? {
            KValue::Str(s) if s.is_empty() => {},
            KValue::Str(s) => return Err(s.to_string()),
            _ => return Err("strike_check must return a string".into()),
        }
        let a = walk(&mut KSink, c, knack);
        let KValue::List(l) = self.koto.call_function(self.done.clone(), &[KValue::Map(a)]).map_err(e)? else { return Err("strike_done must return a list".into()) };
        let items: Vec<KValue> = l.data().iter().cloned().collect();
        items
            .into_iter()
            .map(|v| {
                let KValue::Map(o) = v else { return Err("effect must be a map".to_string()) };
                let op = match o.get("op") {
                    Some(KValue::Str(s)) => s.to_string(),
                    _ => String::new(),
                };
                crate::effect_from(&op, |k| num(o.get(k)))
            })
            .collect()
    }
    fn cooldown(&mut self, skill: &str) -> f64 {
        num(Some(self.koto.call_function(self.cooldown.clone(), &[KValue::from(skill)]).expect("cooldown")))
    }
}
