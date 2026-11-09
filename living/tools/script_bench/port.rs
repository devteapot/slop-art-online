// Rust port of three laws from living/scripts/skills.rhai, kept line for line with the
// script: `rates(a)`, `strike_check(a)` + `strike_done(a)`, and `combat_cooldown(skill)`.
//
// Shared through `include!` by the native floor (bench/src/native.rs, over living-rules'
// SkillCtx) and the wasmi guest (guest/src/lib.rs, over the facts it decodes). Each side
// provides `Rates`, `Effect::{Damage, Vitals}`, a context `c` with the fields read below, and
// `Body` (the to_map-derived body genes and skill factor, as f64).
//
// Rhai computes in f64 from the f32 facts and the authority casts results to f32; so does this.

#[derive(Clone, Copy, Debug, Default)]
pub struct Body {
    pub strength: f64,
    pub endurance: f64,
    pub vitality: f64,
    pub factor: f64,
}

#[inline]
fn st<T: AsRef<str> + ?Sized>(x: &T) -> &str {
    x.as_ref()
}

/// `inv(a, item)`: a count, 0 when absent.
#[inline]
fn count<K: AsRef<str>>(list: &[(K, u32)], item: &str) -> i64 {
    // Rhai builds a map from the list, so a later duplicate wins; fixtures have none.
    for (k, v) in list {
        if k.as_ref() == item {
            return *v as i64;
        }
    }
    0
}

/// `within(ago, ms)`: `ago != () && ago < ms`.
#[inline]
fn within(ago: Option<f32>, ms: f64) -> bool {
    match ago {
        Some(x) => (x as f64) < ms,
        None => false,
    }
}

pub fn combat_cooldown(skill: &str) -> f64 {
    (match skill {
        "strike" => 650,
        "bowshot" => 900,
        "firebolt" => 4000,
        "heal" => 8000,
        "dodge" => 900,
        "block" => 400,
        _ => 0,
    }) as f64
}

fn combat_cost(skill: &str) -> f64 {
    match skill {
        "strike" => 2.0,
        "bowshot" => 1.5,
        "firebolt" => 12.0,
        "heal" => 15.0,
        "dodge" => 4.0,
        "block" => 1.0,
        _ => 0.0,
    }
}

macro_rules! law_fns {
    ($Ctx:ty) => {
        fn cold(c: &$Ctx) -> bool {
            c.night && st(&c.actor.kind) == "person" && !c.actor.near_fire && !c.actor.near_shelter && count(&c.actor.inv, "cloak") == 0
        }

        fn wet(c: &$Ctx) -> bool {
            c.raining && st(&c.actor.kind) == "person" && !c.actor.near_shelter
        }

        pub fn rates(c: &$Ctx, b: &Body) -> Rates {
            let kind = st(&c.actor.kind);
            let mut hunger: f64 = match kind {
                "deer" => 6.0,
                "wolf" => 1.5,
                _ => 5.0,
            };
            let mut energy: f64 = -3.0;
            let mut hp: f64 = 0.0;
            let act = st(&c.actor.activity);
            if act == "sleep" {
                energy = if c.actor.near_shelter { 26.0 } else { 16.0 };
                hunger *= 0.5;
            } else if act == "rest" {
                energy = 6.0;
            } else if act == "block" {
                energy = -12.0;
            }
            let (h, e) = (c.actor.hunger as f64, c.actor.energy as f64);
            if h >= 100.0 {
                hp -= 6.0;
            } else if h < 70.0 && e > 15.0 {
                hp += 3.0;
            }
            if e <= 0.0 {
                hp -= 2.0;
            }
            let stage = st(&c.actor.stage);
            if stage == "elder" {
                if hp > 0.0 {
                    hp *= 0.5;
                }
                energy *= 1.3;
            }
            if stage == "infant" {
                hunger *= if kind == "person" { 0.6 } else { 0.3 };
            }
            if energy < 0.0 {
                energy /= b.endurance;
            }
            if hp > 0.0 {
                hp *= b.vitality;
            }
            if wet(c) {
                energy -= if count(&c.actor.inv, "cloak") > 0 { 1.0 } else { 2.5 };
            }
            if cold(c) {
                hp -= if st(&c.season) == "winter" { 5.0 } else { 2.0 };
            }
            Rates { hunger_per_min: hunger as f32, energy_per_min: energy as f32, hp_per_min: hp as f32 }
        }

        fn young(c: &$Ctx) -> bool {
            let s = st(&c.actor.stage);
            s == "infant" || s == "child"
        }

        fn dares(c: &$Ctx) -> &'static str {
            let kind = st(&c.actor.kind);
            if kind == "person" || st(&c.target.kind) != "person" {
                return "";
            }
            if c.actor.bold {
                return "";
            }
            // fight_back_ms(kind) = 10000.0
            if c.actor.hurt_by as i64 == c.target.id as i64 && within(c.actor.hurt_ago, 10000.0) {
                return "";
            }
            // prey_of(kind): a wolf hunts deer.
            let mut prey: i64 = 0;
            if kind == "wolf" {
                prey += count(&c.actor.sensed, "deer");
            }
            // desperate_hunger(kind) = 85.0
            if c.actor.hunger as f64 >= 85.0 && prey == 0 {
                return "";
            }
            let t = &c.target;
            let ts = st(&t.stage);
            if ts == "infant" || ts == "child" {
                return "";
            }
            // easy_hurt(kind) = 0.35
            if (t.max_hp as f64) > 0.0 && (t.hp as f64) < 0.35 * (t.max_hp as f64) {
                return "";
            }
            if !t.near_fire && (st(&t.activity) == "sleep" || (c.night && t.company == 0)) {
                return "";
            }
            "you do not dare: people are dangerous"
        }

        fn attack_check(c: &$Ctx) -> &'static str {
            if st(&c.actor.kind) == "person" && young(c) {
                return "too young to fight";
            }
            if st(&c.target.class) != "creature" || !c.target.alive {
                return "nothing to attack";
            }
            if c.target.id as i64 == c.actor.id as i64 {
                return "cannot attack yourself";
            }
            // yield_ms(kind) = 20000.0
            if within(c.actor.yielded_ago, 20000.0) {
                return "you have yielded: you do not strike back while it holds";
            }
            dares(c)
        }

        /// `strike_check(a)`, then (when it passes) `strike_done(a)`.
        pub fn strike(c: &$Ctx, b: &Body) -> Result<Vec<Effect>, &'static str> {
            let why = attack_check(c);
            if !why.is_empty() {
                return Err(why);
            }
            // winded(a)
            if (c.actor.energy as f64) < combat_cost(st(&c.skill)) {
                return Err("too tired");
            }
            let dmg: f64 = if count(&c.actor.inv, "spear") > 0 { 15.0 } else { 10.0 };
            // armor(a)
            let armor = if count(&c.target.inv, "armor") < 1 { 1.0 } else { 0.65 };
            let dmg = dmg * b.strength * b.factor * armor;
            Ok(vec![Effect::Damage { amount: dmg as f32 }, Effect::Vitals { hp: 0.0, hunger: 0.0, energy: (-combat_cost("strike")) as f32 }])
        }
    };
}
