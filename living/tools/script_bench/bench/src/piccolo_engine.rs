//! piccolo 0.3: a pure-Rust Lua (scripts/laws.lua) on a gc-arena; the context is a Lua table
//! shaped like Rhai's map.

use crate::ctx::{walk, Sink};
use crate::{Engine, Rates, SkillCtx, StrikeOut};
use piccolo::{Closure, Context, Executor, Function, Lua, StashedExecutor, StashedFunction, Table, Value};

/// Entropy for piccolo's dependencies on wasm32-unknown-unknown (see bench/Cargo.toml): fixed
/// bytes, since a SpacetimeDB module has no OS randomness (it would use the reducer's RNG).
#[cfg(target_arch = "wasm32")]
mod entropy {
    fn fill(buf: &mut [u8]) {
        for (i, b) in buf.iter_mut().enumerate() {
            *b = (i as u8).wrapping_mul(151).wrapping_add(7);
        }
    }
    fn v02(buf: &mut [u8]) -> Result<(), getrandom02::Error> {
        fill(buf);
        Ok(())
    }
    getrandom02::register_custom_getrandom!(v02);
    #[no_mangle]
    unsafe extern "Rust" fn __getrandom_v03_custom(dest: *mut u8, len: usize) -> Result<(), getrandom03::Error> {
        fill(unsafe { core::slice::from_raw_parts_mut(dest, len) });
        Ok(())
    }
}

pub const SOURCE: &str = include_str!("../../scripts/laws.lua");

pub struct PiccoloEngine {
    lua: Lua,
    ex: StashedExecutor,
    rates: StashedFunction,
    check: StashedFunction,
    done: StashedFunction,
    cooldown: StashedFunction,
}

fn e(x: impl std::fmt::Display) -> String {
    x.to_string()
}

impl PiccoloEngine {
    pub fn new() -> Result<Self, String> {
        let mut lua = Lua::core();
        let ex = lua.enter(|ctx| ctx.stash(Executor::new(ctx)));
        lua.try_enter(|ctx| {
            let c = Closure::load(ctx, Some("laws"), SOURCE.as_bytes())?;
            ctx.fetch(&ex).restart(ctx, c.into(), ());
            Ok(())
        })
        .map_err(e)?;
        lua.execute::<()>(&ex).map_err(e)?;
        let get = |lua: &mut Lua, name: &'static str| -> Result<StashedFunction, String> {
            lua.enter(|ctx| match ctx.get_global(name) {
                Value::Function(f) => Ok(ctx.stash(f)),
                _ => Err(format!("laws.lua must define {name}")),
            })
        };
        Ok(Self { rates: get(&mut lua, "rates")?, check: get(&mut lua, "strike_check")?, done: get(&mut lua, "strike_done")?, cooldown: get(&mut lua, "combat_cooldown")?, lua, ex })
    }

    /// Start `f` with the context table (or a string), run it to completion.
    fn run(&mut self, f: &StashedFunction, arg: Arg<'_>) {
        let Self { lua, ex, .. } = self;
        lua.enter(|ctx| {
            let f: Function = ctx.fetch(f);
            let v: Value = match arg {
                Arg::Ctx(c, knack) => Value::Table(walk(&mut LSink { ctx }, c, knack)),
                Arg::Str(s) => Value::String(ctx.intern(s.as_bytes())),
            };
            ctx.fetch(ex).restart(ctx, f, v);
        });
        lua.finish(ex);
    }
}

enum Arg<'a> {
    Ctx(&'a SkillCtx, &'a str),
    Str(&'a str),
}

struct LSink<'gc> {
    ctx: Context<'gc>,
}

impl<'gc> Sink for LSink<'gc> {
    type Map = Table<'gc>;
    fn map(&mut self) -> Table<'gc> {
        Table::new(&self.ctx)
    }
    fn int(&mut self, m: &mut Table<'gc>, k: &'static str, v: i64) {
        m.set(self.ctx, k, v).unwrap();
    }
    fn float(&mut self, m: &mut Table<'gc>, k: &'static str, v: f64) {
        m.set(self.ctx, k, v).unwrap();
    }
    fn str(&mut self, m: &mut Table<'gc>, k: &'static str, v: &str) {
        m.set(self.ctx, k, self.ctx.intern(v.as_bytes())).unwrap();
    }
    fn bool(&mut self, m: &mut Table<'gc>, k: &'static str, v: bool) {
        m.set(self.ctx, k, v).unwrap();
    }
    fn ago(&mut self, m: &mut Table<'gc>, k: &'static str, v: Option<f32>) {
        if let Some(x) = v {
            m.set(self.ctx, k, x as f64).unwrap();
        }
    }
    fn strs(&mut self, m: &mut Table<'gc>, k: &'static str, v: &[String]) {
        let t = Table::new(&self.ctx);
        for (i, s) in v.iter().enumerate() {
            t.set(self.ctx, (i + 1) as i64, self.ctx.intern(s.as_bytes())).unwrap();
        }
        m.set(self.ctx, k, t).unwrap();
    }
    fn counts(&mut self, m: &mut Table<'gc>, k: &'static str, v: &[(String, u32)]) {
        let t = Table::new(&self.ctx);
        for (name, n) in v {
            t.set(self.ctx, self.ctx.intern(name.as_bytes()), *n as i64).unwrap();
        }
        m.set(self.ctx, k, t).unwrap();
    }
    fn sub(&mut self, m: &mut Table<'gc>, k: &'static str, v: Table<'gc>) {
        m.set(self.ctx, k, v).unwrap();
    }
}

fn num(v: Value<'_>) -> f64 {
    match v {
        Value::Integer(i) => i as f64,
        Value::Number(f) => f,
        _ => 0.0,
    }
}

impl Engine for PiccoloEngine {
    fn rates(&mut self, c: &SkillCtx) -> Rates {
        let f = self.rates.clone();
        self.run(&f, Arg::Ctx(c, ""));
        let ex = &self.ex;
        self.lua.enter(|ctx| {
            let t: Table = ctx.fetch(ex).take_result::<Table>(ctx).unwrap().expect("rates must return a table");
            Rates { hunger_per_min: num(t.get(ctx, "hunger")) as f32, energy_per_min: num(t.get(ctx, "energy")) as f32, hp_per_min: num(t.get(ctx, "hp")) as f32 }
        })
    }
    fn strike(&mut self, c: &SkillCtx) -> StrikeOut {
        let knack = crate::knack_of(&c.skill);
        let f = self.check.clone();
        self.run(&f, Arg::Ctx(c, knack));
        let ex = &self.ex;
        let why: String = self.lua.enter(|ctx| ctx.fetch(ex).take_result::<String>(ctx).unwrap().map_err(e))?;
        if !why.is_empty() {
            return Err(why);
        }
        let f = self.done.clone();
        self.run(&f, Arg::Ctx(c, knack));
        let ex = &self.ex;
        self.lua.enter(|ctx| {
            let list: Table = ctx.fetch(ex).take_result::<Table>(ctx).unwrap().map_err(e)?;
            (1..=list.length())
                .map(|i| {
                    let Value::Table(o) = list.get(ctx, i) else { return Err("effect must be a table".to_string()) };
                    let op = match o.get(ctx, "op") {
                        Value::String(s) => std::string::String::from_utf8_lossy(s.as_bytes()).into_owned(),
                        _ => String::new(),
                    };
                    crate::effect_from(&op, |k| num(o.get(ctx, ctx.intern(k.as_bytes()))))
                })
                .collect()
        })
    }
    fn cooldown(&mut self, skill: &str) -> f64 {
        let f = self.cooldown.clone();
        self.run(&f, Arg::Str(skill));
        let ex = &self.ex;
        self.lua.enter(|ctx| num(ctx.fetch(ex).take_result::<Value>(ctx).unwrap().unwrap()))
    }
}
