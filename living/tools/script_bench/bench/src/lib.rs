//! Script engine spike: the same three laws in several engines, with identical typed inputs
//! (`SkillCtx`, as the authority gathers it) and outputs (`Rates`, `Vec<Effect>`, a number).
//!
//! A "call" is what the authority pays: typed facts in, engine value built, law run, result
//! decoded back to typed values. See docs/SCRIPT_ENGINES.md.

pub use living_rules::script::{ActorFacts, Effect, Rates, Regard, RegardIn, SkillCtx, TargetFacts};
use std::fmt::Write as _;

pub mod ctx;
pub mod fixtures;
pub mod native;
#[cfg(feature = "rhai")]
pub mod rhai_engine;
#[cfg(feature = "rune")]
pub mod rune_engine;
#[cfg(feature = "wasmi")]
pub mod wasmi_engine;
#[cfg(feature = "piccolo")]
pub mod piccolo_engine;
#[cfg(feature = "koto")]
pub mod koto_engine;
#[cfg(feature = "mlua")]
pub mod mlua_engine;

/// The laws under test.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Law {
    /// (a) `rates(a)` over a realistic actor.
    Rates = 0,
    /// (b) `strike_check(a)` then `strike_done(a)`: a reason or an effect list.
    Strike = 1,
    /// (c) `combat_cooldown(skill)`: a constant lookup by name.
    Cooldown = 2,
    /// `perceived_of(p)`: what an observer perceives of a target (Rhai and native only).
    Perceived = 3,
    /// `rates(a)` asked every time: the law's own cost where the authority shares one answer
    /// per state (`Scripts::rates_unshared`; other engines run `rates`).
    RatesLaw = 4,
}

impl Law {
    /// The laws every engine runs (run.sh's equivalence check).
    pub const ALL: [Law; 3] = [Law::Rates, Law::Strike, Law::Cooldown];
    /// Cases added after the spike, run when asked (`sb-host --laws`).
    pub const EXTRA: [Law; 2] = [Law::Perceived, Law::RatesLaw];
    pub fn from_u32(v: u32) -> Option<Law> {
        Self::ALL.into_iter().chain(Self::EXTRA).find(|l| *l as u32 == v)
    }
    pub fn from_name(n: &str) -> Option<Law> {
        Self::ALL.into_iter().chain(Self::EXTRA).find(|l| l.name() == n)
    }
    pub fn name(self) -> &'static str {
        match self {
            Law::Rates => "rates",
            Law::Strike => "strike",
            Law::Cooldown => "cooldown",
            Law::Perceived => "perceived",
            Law::RatesLaw => "rates-law",
        }
    }
}

pub type StrikeOut = Result<Vec<Effect>, String>;

/// One engine running the three laws.
pub trait Engine {
    fn rates(&mut self, c: &SkillCtx) -> Rates;
    fn strike(&mut self, c: &SkillCtx) -> StrikeOut;
    fn cooldown(&mut self, skill: &str) -> f64;
    fn rates_law(&mut self, c: &SkillCtx) -> Rates {
        self.rates(c)
    }
    fn perceived(&mut self, _p: &RegardIn) -> Regard {
        unimplemented!("perceived_of is benchmarked for native and rhai only")
    }
}

/// Engine ids shared by the module exports, the host and the calibration module.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Native = 0,
    Rhai = 1,
    /// Diagnostic: only Rhai's context map (the to_map copy), built and dropped per script call.
    RhaiMap = 2,
    Rune = 3,
    Wasmi = 4,
    /// wasmi with its own fuel metering on (a per-call instruction budget).
    WasmiFuel = 5,
    Piccolo = 6,
    Koto = 7,
    Mlua = 8,
    /// Diagnostic: the same Rhai engine settings and skills.rhai, called with only the fields
    /// each law reads (a lean context) instead of the full map.
    RhaiLean = 9,
}

impl Kind {
    pub const ALL: [Kind; 10] = [Kind::Native, Kind::Rhai, Kind::RhaiMap, Kind::Rune, Kind::Wasmi, Kind::WasmiFuel, Kind::Piccolo, Kind::Koto, Kind::Mlua, Kind::RhaiLean];
    pub fn from_u32(v: u32) -> Option<Kind> {
        Self::ALL.into_iter().find(|k| *k as u32 == v)
    }
    pub fn name(self) -> &'static str {
        match self {
            Kind::Native => "native",
            Kind::Rhai => "rhai",
            Kind::RhaiMap => "rhai-map-only",
            Kind::Rune => "rune",
            Kind::Wasmi => "wasmi",
            Kind::WasmiFuel => "wasmi-fuel",
            Kind::Piccolo => "piccolo",
            Kind::Koto => "koto",
            Kind::Mlua => "mlua",
            Kind::RhaiLean => "rhai-lean",
        }
    }
}

/// Compile or load an engine (this is what `install_script` would pay).
pub fn make(kind: Kind) -> Result<Box<dyn Engine>, String> {
    match kind {
        Kind::Native => Ok(Box::new(native::Native)),
        #[cfg(feature = "rhai")]
        Kind::Rhai => Ok(Box::new(rhai_engine::RhaiEmbed::new()?)),
        #[cfg(feature = "rhai")]
        Kind::RhaiMap => Ok(Box::new(rhai_engine::MapOnly)),
        #[cfg(feature = "rhai")]
        Kind::RhaiLean => Ok(Box::new(rhai_engine::RhaiLean::new()?)),
        #[cfg(feature = "rune")]
        Kind::Rune => Ok(Box::new(rune_engine::RuneEngine::new()?)),
        #[cfg(feature = "wasmi")]
        Kind::Wasmi => Ok(Box::new(wasmi_engine::WasmiEngine::new(false)?)),
        #[cfg(feature = "wasmi")]
        Kind::WasmiFuel => Ok(Box::new(wasmi_engine::WasmiEngine::new(true)?)),
        #[cfg(feature = "piccolo")]
        Kind::Piccolo => Ok(Box::new(piccolo_engine::PiccoloEngine::new()?)),
        #[cfg(feature = "koto")]
        Kind::Koto => Ok(Box::new(koto_engine::KotoEngine::new()?)),
        #[cfg(feature = "mlua")]
        Kind::Mlua => Ok(Box::new(mlua_engine::MluaEngine::new()?)),
        #[allow(unreachable_patterns)]
        k => Err(format!("engine {} not built into this module", k.name())),
    }
}

/// The skill whose knack gene serves a skill (`<skill>_combat().knack`, else itself): the
/// starter strike uses the attack knack (skills.rhai `strike_combat`).
pub fn knack_of(skill: &str) -> &str {
    match skill {
        "strike" | "attack" => "attack",
        "bowshot" | "shoot" => "shoot",
        "firebolt" | "throw" => "throw",
        "heal" | "tend" => "tend",
        s => s,
    }
}

/// The derived numbers `to_map` puts in the actor map (body genes, the skill factor).
pub fn body_of(c: &SkillCtx) -> native::Body {
    use living_rules::genes::{gene, skill_factor};
    let g = &c.actor.genes;
    native::Body {
        strength: gene(g, "strength") as f64,
        endurance: gene(g, "endurance") as f64,
        vitality: gene(g, "vitality") as f64,
        factor: skill_factor(g, &c.actor.practice, &c.skill, knack_of(&c.skill)) as f64,
    }
}

/// Run `n` calls of a law, cycling through its fixtures from `cursor` (kept across batches, so
/// short batches still cover every fixture). Returns a checksum of the outputs so nothing is
/// optimized away.
pub fn run(e: &mut dyn Engine, fx: &fixtures::Fixtures, law: Law, cursor: &mut usize, n: u32) -> u64 {
    let mut sum = 0u64;
    let mut i = *cursor;
    for _ in 0..n {
        sum = sum.wrapping_add(match law {
            Law::Rates => {
                let r = e.rates(&fx.rates[i % fx.rates.len()]);
                (r.hunger_per_min.to_bits() ^ r.energy_per_min.to_bits().rotate_left(7) ^ r.hp_per_min.to_bits().rotate_left(13)) as u64
            },
            Law::Strike => match e.strike(&fx.strike[i % fx.strike.len()]) {
                Ok(v) => v.len() as u64 + 1,
                Err(s) => s.len() as u64,
            },
            Law::Cooldown => e.cooldown(fx.skills[i % fx.skills.len()]).to_bits(),
            Law::Perceived => {
                let r = e.perceived(&fx.perceived[i % fx.perceived.len()]);
                r.name as u64 + 2 * r.health as u64
            },
            Law::RatesLaw => {
                let r = e.rates_law(&fx.rates[i % fx.rates.len()]);
                (r.hunger_per_min.to_bits() ^ r.energy_per_min.to_bits().rotate_left(7) ^ r.hp_per_min.to_bits().rotate_left(13)) as u64
            },
        });
        i += 1;
    }
    *cursor = i;
    sum
}

/// Canonical text of a law's outputs over all its fixtures (bit-exact floats).
pub fn dump(e: &mut dyn Engine, fx: &fixtures::Fixtures, law: Law) -> String {
    let mut s = String::new();
    match law {
        Law::Rates => {
            for (i, c) in fx.rates.iter().enumerate() {
                let r = e.rates(c);
                let _ = writeln!(s, "{i} {:?} {:?} {:?}", r.hunger_per_min, r.energy_per_min, r.hp_per_min);
            }
        },
        Law::Strike => {
            for (i, c) in fx.strike.iter().enumerate() {
                let _ = writeln!(s, "{i} {:?}", e.strike(c));
            }
        },
        Law::Cooldown => {
            for k in fx.skills {
                let _ = writeln!(s, "{k} {:?}", e.cooldown(k));
            }
        },
        Law::Perceived => {
            for (i, p) in fx.perceived.iter().enumerate() {
                let _ = writeln!(s, "{i} {:?}", e.perceived(p));
            }
        },
        Law::RatesLaw => {
            for (i, c) in fx.rates.iter().enumerate() {
                let r = e.rates_law(c);
                let _ = writeln!(s, "{i} {:?} {:?} {:?}", r.hunger_per_min, r.energy_per_min, r.hp_per_min);
            }
        },
    }
    s
}

/// A cheap stable digest (FNV-1a 64) of a dump.
pub fn digest(s: &str) -> u64 {
    let mut h = 0xcbf29ce484222325u64;
    for b in s.bytes() {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

/// Decode one effect map the way living-rules' `effect()` does, for the ops these laws use.
pub fn effect_from(op: &str, num: impl Fn(&str) -> f64) -> Result<Effect, String> {
    Ok(match op {
        "damage" => Effect::Damage { amount: num("amount") as f32 },
        "vitals" => Effect::Vitals { hp: num("hp") as f32, hunger: num("hunger") as f32, energy: num("energy") as f32 },
        other => return Err(format!("unknown effect op `{other}`")),
    })
}
