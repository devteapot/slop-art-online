//! Laws written in Rust, compiled to WASM (guest/), run by wasmi inside this module. Each call
//! encodes the full context into the guest's memory (the same fields Rhai's map carries), calls
//! the law, and decodes its typed result: the boundary cost is in every number.

use crate::ctx::{walk, Sink};
use crate::{Effect, Engine, Rates, SkillCtx, StrikeOut};
use wasmi::{Config, Engine as WEngine, Linker, Memory, Module, Store, TypedFunc};

/// Built by run.sh: `cargo build -p sb-guest --target wasm32-unknown-unknown --release`.
pub const GUEST: &[u8] = include_bytes!("../../guest.wasm");

/// Instructions a call may run when wasmi's own fuel is on (a per-call limit, like Rhai's
/// max_operations).
pub const CALL_FUEL: u64 = 1_000_000;

pub struct WasmiEngine {
    store: Store<()>,
    mem: Memory,
    inp: usize,
    out: usize,
    rates: TypedFunc<u32, u32>,
    strike: TypedFunc<u32, u32>,
    cooldown: TypedFunc<u32, u32>,
    fuel: bool,
    buf: Vec<u8>,
}

fn e(x: impl std::fmt::Display) -> String {
    x.to_string()
}

impl WasmiEngine {
    pub fn new(fuel: bool) -> Result<Self, String> {
        let mut config = Config::default();
        config.consume_fuel(fuel);
        let engine = WEngine::new(&config);
        let module = Module::new(&engine, GUEST).map_err(e)?;
        let mut store = Store::new(&engine, ());
        if fuel {
            store.set_fuel(CALL_FUEL).map_err(e)?;
        }
        let linker = Linker::<()>::new(&engine);
        let inst = linker.instantiate_and_start(&mut store, &module).map_err(e)?;
        let mem = inst.get_memory(&store, "memory").ok_or("guest has no memory")?;
        let ptr = |store: &mut Store<()>, f: &str| -> Result<usize, String> { Ok(inst.get_typed_func::<(), u32>(&*store, f).map_err(e)?.call(store, ()).map_err(e)? as usize) };
        let inp = ptr(&mut store, "sb_in")?;
        let out = ptr(&mut store, "sb_out")?;
        let f = |name: &str| inst.get_typed_func::<u32, u32>(&store, name).map_err(e);
        Ok(Self { rates: f("law_rates")?, strike: f("law_strike")?, cooldown: f("law_cooldown")?, store, mem, inp, out, fuel, buf: Vec::with_capacity(2048) })
    }

    fn call(&mut self, f: TypedFunc<u32, u32>, write: impl FnOnce(&mut Vec<u8>)) -> usize {
        self.buf.clear();
        write(&mut self.buf);
        let len = self.buf.len();
        self.mem.data_mut(&mut self.store)[self.inp..self.inp + len].copy_from_slice(&self.buf);
        if self.fuel {
            self.store.set_fuel(CALL_FUEL).unwrap();
        }
        f.call(&mut self.store, len as u32).expect("guest call") as usize
    }

    fn output(&self, n: usize) -> &[u8] {
        &self.mem.data(&self.store)[self.out..self.out + n]
    }
}

/// Positional encoding in `walk` order: keys are not sent, the guest knows the layout.
struct Enc<'a>(&'a mut Vec<u8>);

impl Enc<'_> {
    fn s(&mut self, v: &str) {
        self.0.extend_from_slice(&(v.len() as u16).to_le_bytes());
        self.0.extend_from_slice(v.as_bytes());
    }
}

impl Sink for Enc<'_> {
    type Map = ();
    fn map(&mut self) {}
    fn int(&mut self, _: &mut (), _: &'static str, v: i64) {
        self.0.extend_from_slice(&v.to_le_bytes());
    }
    fn float(&mut self, _: &mut (), _: &'static str, v: f64) {
        self.0.extend_from_slice(&v.to_le_bytes());
    }
    fn str(&mut self, _: &mut (), _: &'static str, v: &str) {
        self.s(v);
    }
    fn bool(&mut self, _: &mut (), _: &'static str, v: bool) {
        self.0.push(v as u8);
    }
    fn ago(&mut self, _: &mut (), _: &'static str, v: Option<f32>) {
        match v {
            Some(x) => {
                self.0.push(1);
                self.0.extend_from_slice(&(x as f64).to_le_bytes());
            },
            None => self.0.push(0),
        }
    }
    fn strs(&mut self, _: &mut (), _: &'static str, v: &[String]) {
        self.0.extend_from_slice(&(v.len() as u16).to_le_bytes());
        for s in v {
            self.s(s);
        }
    }
    fn counts(&mut self, _: &mut (), _: &'static str, v: &[(String, u32)]) {
        self.0.extend_from_slice(&(v.len() as u16).to_le_bytes());
        for (k, n) in v {
            self.s(k);
            self.0.extend_from_slice(&(*n as i64).to_le_bytes());
        }
    }
    fn sub(&mut self, _: &mut (), _: &'static str, _: ()) {}
}

fn f32_at(b: &[u8], i: usize) -> f32 {
    f32::from_le_bytes(b[i..i + 4].try_into().unwrap())
}

impl Engine for WasmiEngine {
    fn rates(&mut self, c: &SkillCtx) -> Rates {
        let n = self.call(self.rates, |b| walk(&mut Enc(b), c, ""));
        let o = self.output(n);
        Rates { hunger_per_min: f32_at(o, 0), energy_per_min: f32_at(o, 4), hp_per_min: f32_at(o, 8) }
    }
    fn strike(&mut self, c: &SkillCtx) -> StrikeOut {
        let knack = crate::knack_of(&c.skill);
        let n = self.call(self.strike, |b| walk(&mut Enc(b), c, knack));
        let o = self.output(n);
        if o[0] == 1 {
            let len = u16::from_le_bytes([o[1], o[2]]) as usize;
            return Err(String::from_utf8_lossy(&o[3..3 + len]).into_owned());
        }
        let mut fx = Vec::with_capacity(o[1] as usize);
        let mut i = 2;
        for _ in 0..o[1] {
            if o[i] == 0 {
                fx.push(Effect::Damage { amount: f32_at(o, i + 1) });
                i += 5;
            } else {
                fx.push(Effect::Vitals { hp: f32_at(o, i + 1), hunger: f32_at(o, i + 5), energy: f32_at(o, i + 9) });
                i += 13;
            }
        }
        Ok(fx)
    }
    fn cooldown(&mut self, skill: &str) -> f64 {
        let n = self.call(self.cooldown, |b| b.extend_from_slice(skill.as_bytes()));
        f64::from_le_bytes(self.output(n)[0..8].try_into().unwrap())
    }
}
