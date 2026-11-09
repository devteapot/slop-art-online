//! The laws written in Rust and compiled to wasm32-unknown-unknown, for wasmi to run inside the
//! bench module. The host writes the context (bench/src/wasmi_engine.rs, in `ctx::walk`
//! order) into `sb_in`, calls a law, and reads the result from `sb_out`.

#[derive(Clone, Copy, Debug, Default)]
pub struct Rates {
    pub hunger_per_min: f32,
    pub energy_per_min: f32,
    pub hp_per_min: f32,
}

pub enum Effect {
    Damage { amount: f32 },
    Vitals { hp: f32, hunger: f32, energy: f32 },
}

include!("../../port.rs");

#[derive(Default)]
pub struct Actor<'a> {
    pub id: u32,
    pub kind: &'a str,
    pub hunger: f32,
    pub energy: f32,
    pub near_fire: bool,
    pub near_shelter: bool,
    pub activity: &'a str,
    pub stage: &'a str,
    pub inv: Vec<(&'a str, u32)>,
    pub hurt_by: u32,
    pub hurt_ago: Option<f32>,
    pub yielded_ago: Option<f32>,
    pub sensed: Vec<(&'a str, u32)>,
    pub bold: bool,
}

#[derive(Default)]
pub struct Target<'a> {
    pub class: &'a str,
    pub id: u64,
    pub kind: &'a str,
    pub hp: f32,
    pub max_hp: f32,
    pub stage: &'a str,
    pub alive: bool,
    pub inv: Vec<(&'a str, u32)>,
    pub activity: &'a str,
    pub near_fire: bool,
    pub company: u32,
}

#[derive(Default)]
pub struct Ctx<'a> {
    pub actor: Actor<'a>,
    pub target: Target<'a>,
    pub night: bool,
    pub season: &'a str,
    pub raining: bool,
    pub skill: &'a str,
}

law_fns!(Ctx<'_>);

struct R<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> R<'a> {
    fn take(&mut self, n: usize) -> &'a [u8] {
        let s = &self.b[self.i..self.i + n];
        self.i += n;
        s
    }
    fn u8(&mut self) -> u8 {
        self.take(1)[0]
    }
    fn b(&mut self) -> bool {
        self.u8() != 0
    }
    fn i(&mut self) -> i64 {
        i64::from_le_bytes(self.take(8).try_into().unwrap())
    }
    fn f(&mut self) -> f64 {
        f64::from_le_bytes(self.take(8).try_into().unwrap())
    }
    fn s(&mut self) -> &'a str {
        let n = u16::from_le_bytes(self.take(2).try_into().unwrap()) as usize;
        core::str::from_utf8(self.take(n)).unwrap_or("")
    }
    fn ago(&mut self) -> Option<f32> {
        if self.b() {
            Some(self.f() as f32)
        } else {
            None
        }
    }
    fn strs(&mut self) {
        let n = u16::from_le_bytes(self.take(2).try_into().unwrap());
        for _ in 0..n {
            self.s();
        }
    }
    fn counts(&mut self) -> Vec<(&'a str, u32)> {
        let n = u16::from_le_bytes(self.take(2).try_into().unwrap());
        (0..n).map(|_| (self.s(), self.i() as u32)).collect()
    }
}

/// Decode in `ctx::walk` order (fields the laws do not read are skipped but still crossed).
fn decode(b: &[u8]) -> (Ctx<'_>, Body) {
    let mut r = R { b, i: 0 };
    let mut c = Ctx::default();
    let mut body = Body::default();
    let a = &mut c.actor;
    a.id = r.i() as u32;
    a.kind = r.s();
    let _hp = r.f();
    a.hunger = r.f() as f32;
    a.energy = r.f() as f32;
    a.near_fire = r.b();
    a.near_shelter = r.b();
    let _terrain = r.s();
    a.activity = r.s();
    let _age = r.f();
    a.stage = r.s();
    let _life = r.f();
    r.strs();
    a.inv = r.counts();
    let _kin = r.i();
    let _pasture = r.f();
    a.hurt_by = r.i() as u32;
    a.hurt_ago = r.ago();
    a.yielded_ago = r.ago();
    a.sensed = r.counts();
    a.bold = r.b();
    let _room = r.i();
    // genes::BODY order: speed, strength, endurance, vitality; then the skill factor.
    let _speed = r.f();
    body.strength = r.f();
    body.endurance = r.f();
    body.vitality = r.f();
    body.factor = r.f();
    let t = &mut c.target;
    t.class = r.s();
    t.id = r.i() as u64;
    t.kind = r.s();
    let _name = r.s();
    let _amount = r.f();
    t.hp = r.f() as f32;
    t.max_hp = r.f() as f32;
    t.stage = r.s();
    let _hurt_ago = r.f();
    t.alive = r.b();
    let _dist = r.f();
    t.inv = r.counts();
    r.strs();
    t.activity = r.s();
    let _yielded = r.ago();
    t.near_fire = r.b();
    t.company = r.i() as u32;
    let _bearing = r.f();
    let _closing = r.f();
    let _exists = r.b();
    let _ok = r.i();
    let _failed = r.i();
    let _changed = r.f();
    let _item = r.s();
    let _qty = r.i();
    c.night = r.b();
    let _hour = r.f();
    c.season = r.s();
    let _text = r.s();
    let _topic = r.s();
    let _roll = r.f();
    c.raining = r.b();
    c.skill = r.s();
    (c, body)
}

const IN_SIZE: usize = 16 * 1024;
static mut IN: [u8; IN_SIZE] = [0; IN_SIZE];
static mut OUT: [u8; 1024] = [0; 1024];

#[no_mangle]
pub extern "C" fn sb_in() -> *mut u8 {
    &raw mut IN as *mut u8
}

#[no_mangle]
pub extern "C" fn sb_out() -> *mut u8 {
    &raw mut OUT as *mut u8
}

fn input(len: u32) -> &'static [u8] {
    unsafe { core::slice::from_raw_parts(&raw const IN as *const u8, len as usize) }
}

fn out() -> &'static mut [u8; 1024] {
    unsafe { &mut *(&raw mut OUT) }
}

#[no_mangle]
pub extern "C" fn law_rates(len: u32) -> u32 {
    let (c, b) = decode(input(len));
    let r = rates(&c, &b);
    let o = out();
    o[0..4].copy_from_slice(&r.hunger_per_min.to_le_bytes());
    o[4..8].copy_from_slice(&r.energy_per_min.to_le_bytes());
    o[8..12].copy_from_slice(&r.hp_per_min.to_le_bytes());
    12
}

#[no_mangle]
pub extern "C" fn law_strike(len: u32) -> u32 {
    let (c, b) = decode(input(len));
    let o = out();
    let mut n = 0usize;
    let mut put = |bytes: &[u8]| {
        o[n..n + bytes.len()].copy_from_slice(bytes);
        n += bytes.len();
    };
    match strike(&c, &b) {
        Ok(fx) => {
            put(&[0, fx.len() as u8]);
            for e in fx {
                match e {
                    Effect::Damage { amount } => {
                        put(&[0]);
                        put(&amount.to_le_bytes());
                    },
                    Effect::Vitals { hp, hunger, energy } => {
                        put(&[1]);
                        put(&hp.to_le_bytes());
                        put(&hunger.to_le_bytes());
                        put(&energy.to_le_bytes());
                    },
                }
            }
        },
        Err(why) => {
            put(&[1]);
            put(&(why.len() as u16).to_le_bytes());
            put(why.as_bytes());
        },
    }
    n as u32
}

#[no_mangle]
pub extern "C" fn law_cooldown(len: u32) -> u32 {
    let skill = core::str::from_utf8(input(len)).unwrap_or("");
    out()[0..8].copy_from_slice(&combat_cooldown(skill).to_le_bytes());
    8
}
