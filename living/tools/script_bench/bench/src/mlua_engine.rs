//! mlua 0.12 with vendored PUC Lua 5.4 (scripts/laws.lua). Builds natively; see
//! docs/SCRIPT_ENGINES.md for why it does not build for wasm32-unknown-unknown.

use crate::ctx::{walk, Sink};
use crate::{Engine, Rates, SkillCtx, StrikeOut};
use mlua::{Function, Lua, Table, Value};

pub const SOURCE: &str = include_str!("../../scripts/laws.lua");

pub struct MluaEngine {
    lua: Lua,
    rates: Function,
    check: Function,
    done: Function,
    cooldown: Function,
}

fn e(x: impl std::fmt::Display) -> String {
    x.to_string()
}

impl MluaEngine {
    pub fn new() -> Result<Self, String> {
        let lua = Lua::new();
        lua.load(SOURCE).set_name("laws").exec().map_err(e)?;
        let g = lua.globals();
        Ok(Self { rates: g.get("rates").map_err(e)?, check: g.get("strike_check").map_err(e)?, done: g.get("strike_done").map_err(e)?, cooldown: g.get("combat_cooldown").map_err(e)?, lua })
    }
}

struct LSink<'a>(&'a Lua);

impl Sink for LSink<'_> {
    type Map = Table;
    fn map(&mut self) -> Table {
        self.0.create_table().unwrap()
    }
    fn int(&mut self, m: &mut Table, k: &'static str, v: i64) {
        m.raw_set(k, v).unwrap();
    }
    fn float(&mut self, m: &mut Table, k: &'static str, v: f64) {
        m.raw_set(k, v).unwrap();
    }
    fn str(&mut self, m: &mut Table, k: &'static str, v: &str) {
        m.raw_set(k, v).unwrap();
    }
    fn bool(&mut self, m: &mut Table, k: &'static str, v: bool) {
        m.raw_set(k, v).unwrap();
    }
    fn ago(&mut self, m: &mut Table, k: &'static str, v: Option<f32>) {
        if let Some(x) = v {
            m.raw_set(k, x as f64).unwrap();
        }
    }
    fn strs(&mut self, m: &mut Table, k: &'static str, v: &[String]) {
        let t = self.0.create_table().unwrap();
        for (i, s) in v.iter().enumerate() {
            t.raw_set(i + 1, s.as_str()).unwrap();
        }
        m.raw_set(k, t).unwrap();
    }
    fn counts(&mut self, m: &mut Table, k: &'static str, v: &[(String, u32)]) {
        let t = self.0.create_table().unwrap();
        for (name, n) in v {
            t.raw_set(name.as_str(), *n as i64).unwrap();
        }
        m.raw_set(k, t).unwrap();
    }
    fn sub(&mut self, m: &mut Table, k: &'static str, v: Table) {
        m.raw_set(k, v).unwrap();
    }
}

fn num(v: Value) -> f64 {
    match v {
        Value::Integer(i) => i as f64,
        Value::Number(f) => f,
        _ => 0.0,
    }
}

impl Engine for MluaEngine {
    fn rates(&mut self, c: &SkillCtx) -> Rates {
        let a = walk(&mut LSink(&self.lua), c, "");
        let t: Table = self.rates.call(a).expect("rates");
        let g = |k: &str| num(t.raw_get(k).unwrap()) as f32;
        Rates { hunger_per_min: g("hunger"), energy_per_min: g("energy"), hp_per_min: g("hp") }
    }
    fn strike(&mut self, c: &SkillCtx) -> StrikeOut {
        let knack = crate::knack_of(&c.skill);
        let why: String = self.check.call(walk(&mut LSink(&self.lua), c, knack)).map_err(e)?;
        if !why.is_empty() {
            return Err(why);
        }
        let list: Table = self.done.call(walk(&mut LSink(&self.lua), c, knack)).map_err(e)?;
        list.sequence_values::<Table>()
            .map(|o| {
                let o = o.map_err(e)?;
                let op: String = o.raw_get("op").unwrap_or_default();
                crate::effect_from(&op, |k| num(o.raw_get(k).unwrap()))
            })
            .collect()
    }
    fn cooldown(&mut self, skill: &str) -> f64 {
        num(self.cooldown.call(skill).expect("cooldown"))
    }
}
