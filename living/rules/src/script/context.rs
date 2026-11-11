//! The context map `a` a law is called with, built from typed facts with only the fields the
//! law reads ([`Plan`], from [`super::fields`]). The fields and their values are the same as the
//! full map's; a field the law never reads is left out.

use super::fields::Use;
use super::SkillCtx;
use rhai::{Array, Dynamic, Map};

/// Fields of `a`. The order is the bit order of [`Plan::top`].
pub const TOP: [&str; 18] = ["actor", "target", "routine", "item", "qty", "night", "hour", "season", "text", "topic", "roll", "raining", "skill", "want", "want_qty", "records", "record", "daylight"];
/// Fields of `a.actor` (the body genes are `genes::BODY`; `factor` is the skill factor).
pub const ACTOR: [&str; 30] = [
    "id", "kind", "hp", "hunger", "energy", "near_fire", "near_shelter", "terrain", "activity", "age", "stage", "life", "knows", "inv", "kin_near", "pasture", "hurt_by", "hurt_ago", "yielded_ago", "sensed", "bold", "room", "community", "home", "speed", "strength", "endurance", "vitality", "factor", "lit",
];
pub const TARGET: [&str; 25] = ["class", "id", "kind", "name", "amount", "hp", "max_hp", "stage", "hurt_ago", "alive", "dist", "inv", "knows", "activity", "yielded_ago", "near_fire", "company", "bearing", "closing", "community", "owner", "home", "hosts", "lit", "fuel"];
pub const ROUTINE: [&str; 4] = ["exists", "ok", "failed", "changed_s"];

const _: () = assert!(crate::genes::BODY.len() == 4);

/// Which entries of an inventory-like map a law reads.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Keys {
    All,
    Only(Vec<String>),
}

impl Keys {
    fn of(u: &Use) -> Keys {
        if u.all || !u.by_param.is_empty() {
            Keys::All
        } else {
            Keys::Only(u.keys.keys().cloned().collect())
        }
    }

    fn has(&self, k: &str) -> bool {
        match self {
            Keys::All => true,
            Keys::Only(v) => v.iter().any(|x| x == k),
        }
    }
}

/// The fields of the context a law reads.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Plan {
    pub top: u32,
    pub actor: u32,
    pub target: u32,
    pub routine: u8,
    pub actor_inv: Keys,
    pub actor_sensed: Keys,
    pub target_inv: Keys,
}

impl Plan {
    pub fn all() -> Plan {
        Plan { top: u32::MAX, actor: u32::MAX, target: u32::MAX, routine: u8::MAX, actor_inv: Keys::All, actor_sensed: Keys::All, target_inv: Keys::All }
    }

    /// The plan for a law reading `u` of its context. `strict` refuses a field the engine does not
    /// provide (an install); otherwise such a read is left out, and reads `()` as it always has.
    pub fn of(law: &str, u: Option<&Use>, strict: bool) -> Result<Plan, String> {
        let Some(u) = u.filter(|u| !u.all && u.by_param.is_empty()) else { return Ok(Plan::all()) };
        let mut p = Plan { top: 0, actor: 0, target: 0, routine: 0, actor_inv: Keys::Only(vec![]), actor_sensed: Keys::Only(vec![]), target_inv: Keys::Only(vec![]) };
        let unknown = |at: &str, k: &str, fields: &[&str]| -> Result<(), String> {
            if strict {
                Err(format!("{law} reads `a.{at}{k}`, which the engine does not provide (a.{at}* is {})", fields.join(", ")))
            } else {
                Ok(())
            }
        };
        for (k, v) in &u.keys {
            let Some(i) = TOP.iter().position(|f| f == k) else {
                unknown("", k, &TOP)?;
                continue;
            };
            p.top |= 1 << i;
            let whole = v.all || !v.by_param.is_empty();
            match k.as_str() {
                "actor" => {
                    if whole {
                        (p.actor, p.actor_inv, p.actor_sensed) = (u32::MAX, Keys::All, Keys::All);
                        continue;
                    }
                    for (f, w) in &v.keys {
                        let Some(j) = ACTOR.iter().position(|x| x == f) else {
                            unknown("actor.", f, &ACTOR)?;
                            continue;
                        };
                        p.actor |= 1 << j;
                        match f.as_str() {
                            "inv" => p.actor_inv = Keys::of(w),
                            "sensed" => p.actor_sensed = Keys::of(w),
                            _ => {},
                        }
                    }
                },
                "target" => {
                    if whole {
                        (p.target, p.target_inv) = (u32::MAX, Keys::All);
                        continue;
                    }
                    for (f, w) in &v.keys {
                        let Some(j) = TARGET.iter().position(|x| x == f) else {
                            unknown("target.", f, &TARGET)?;
                            continue;
                        };
                        p.target |= 1 << j;
                        if f == "inv" {
                            p.target_inv = Keys::of(w);
                        }
                    }
                },
                "routine" => {
                    if whole {
                        p.routine = u8::MAX;
                        continue;
                    }
                    for f in v.keys.keys() {
                        let Some(j) = ROUTINE.iter().position(|x| x == f) else {
                            unknown("routine.", f, &ROUTINE)?;
                            continue;
                        };
                        p.routine |= 1 << j;
                    }
                },
                _ => {},
            }
        }
        Ok(p)
    }

    /// The field names a law reads, for reports (`actor.hunger`, `actor.inv[cloak]`, `night`).
    pub fn describe(&self) -> Vec<String> {
        if *self == Plan::all() {
            return vec!["*".into()];
        }
        let mut out = Vec::new();
        let keys = |k: &Keys| match k {
            Keys::All => "[*]".to_string(),
            Keys::Only(v) => format!("[{}]", v.join(",")),
        };
        for (i, t) in TOP.iter().enumerate() {
            if self.top & (1 << i) == 0 {
                continue;
            }
            match *t {
                "actor" => out.extend(ACTOR.iter().enumerate().filter(|(j, _)| self.actor & (1 << j) != 0).map(|(_, f)| match *f {
                    "inv" => format!("actor.inv{}", keys(&self.actor_inv)),
                    "sensed" => format!("actor.sensed{}", keys(&self.actor_sensed)),
                    f => format!("actor.{f}"),
                })),
                "target" => out.extend(TARGET.iter().enumerate().filter(|(j, _)| self.target & (1 << j) != 0).map(|(_, f)| if *f == "inv" { format!("target.inv{}", keys(&self.target_inv)) } else { format!("target.{f}") })),
                "routine" => out.extend(ROUTINE.iter().enumerate().filter(|(j, _)| self.routine & (1 << j) != 0).map(|(_, f)| format!("routine.{f}"))),
                t => out.push(t.to_string()),
            }
        }
        out
    }
}

/// One field's value.
enum Val<'a> {
    Str(&'a str),
    F(f32),
    I(i64),
    B(bool),
    Ago(Option<f32>),
    List(&'a [String]),
    Inv(&'a [(String, u32)], &'a Keys),
    Records(&'a [crate::records::RecordFacts]),
    Record(Option<&'a crate::records::RecordFacts>),
}

/// A record as the rules see it: `#{ id, kind, status, open, terms, parties, me, by, age_s,
/// due_s }` (`due_s` is `()` when it never falls due).
pub(crate) fn record_map(r: &crate::records::RecordFacts) -> Dynamic {
    let mut m = Map::new();
    m.insert("id".into(), Dynamic::from_int(r.id as i64));
    m.insert("kind".into(), r.kind.clone().into());
    m.insert("status".into(), r.status.clone().into());
    m.insert("open".into(), r.open.into());
    let mut t = Map::new();
    for (k, v) in &r.terms {
        let d = match v {
            serde_json::Value::String(s) => s.clone().into(),
            serde_json::Value::Bool(b) => (*b).into(),
            serde_json::Value::Number(n) => match n.as_i64() {
                Some(i) => Dynamic::from_int(i),
                None => Dynamic::from_float(n.as_f64().unwrap_or(0.0)),
            },
            _ => Dynamic::UNIT,
        };
        t.insert(k.as_str().into(), d);
    }
    m.insert("terms".into(), t.into());
    let mut p = Map::new();
    for (role, id) in &r.parties {
        p.insert(role.as_str().into(), Dynamic::from_int(*id as i64));
    }
    m.insert("parties".into(), p.into());
    m.insert("me".into(), r.me.clone().into());
    m.insert("by".into(), Dynamic::from_int(r.by as i64));
    m.insert("age_s".into(), Dynamic::from_float(r.age_s as f64));
    m.insert("due_s".into(), r.due_s.map_or(Dynamic::UNIT, |x| Dynamic::from_float(x as f64)));
    m.into()
}

/// A record's bytes for a memo key: its id and every value the rules can read.
fn record_key(r: &crate::records::RecordFacts, out: &mut Vec<u8>) {
    out.extend(r.id.to_le_bytes());
    let text = serde_json::to_string(&(&r.kind, &r.status, r.open, &r.terms, &r.parties, &r.me, r.by, r.age_s.to_bits(), r.due_s.map(f32::to_bits))).unwrap_or_default();
    out.extend((text.len() as u32).to_le_bytes());
    out.extend(text.as_bytes());
}

impl Val<'_> {
    fn dynamic(&self) -> Dynamic {
        match self {
            Val::Str(s) => (*s).into(),
            Val::F(v) => Dynamic::from_float(*v as f64),
            Val::I(v) => Dynamic::from_int(*v),
            Val::B(v) => (*v).into(),
            Val::Ago(v) => v.map_or(Dynamic::UNIT, |x| Dynamic::from_float(x as f64)),
            Val::List(v) => v.iter().map(|k| Dynamic::from(k.clone())).collect::<Array>().into(),
            Val::Inv(v, keys) => {
                let mut m = Map::new();
                for (k, n) in v.iter().filter(|(k, _)| keys.has(k)) {
                    m.insert(k.as_str().into(), Dynamic::from_int(*n as i64));
                }
                m.into()
            },
            Val::Records(v) => v.iter().map(record_map).collect::<Array>().into(),
            Val::Record(r) => r.map_or(Dynamic::UNIT, record_map),
        }
    }

    fn key(&self, out: &mut Vec<u8>) {
        let s = |out: &mut Vec<u8>, s: &str| {
            out.extend((s.len() as u32).to_le_bytes());
            out.extend(s.as_bytes());
        };
        match self {
            Val::Str(v) => s(out, v),
            Val::F(v) => out.extend(v.to_bits().to_le_bytes()),
            Val::I(v) => out.extend(v.to_le_bytes()),
            Val::B(v) => out.push(*v as u8),
            Val::Ago(v) => out.extend(v.map_or(u64::MAX, |x| x.to_bits() as u64).to_le_bytes()),
            Val::List(v) => {
                out.extend((v.len() as u32).to_le_bytes());
                for k in v.iter() {
                    s(out, k);
                }
            },
            Val::Inv(v, keys) => {
                // Duplicate items in a list are folded by the map: the last count wins.
                let mut m: Vec<(&str, u32)> = Vec::new();
                for (k, n) in v.iter().filter(|(k, _)| keys.has(k)) {
                    match m.iter_mut().find(|(x, _)| x == k) {
                        Some(e) => e.1 = *n,
                        None => m.push((k, *n)),
                    }
                }
                m.sort();
                out.extend((m.len() as u32).to_le_bytes());
                for (k, n) in m {
                    s(out, k);
                    out.extend(n.to_le_bytes());
                }
            },
            Val::Records(v) => {
                out.extend((v.len() as u32).to_le_bytes());
                for r in v.iter() {
                    record_key(r, out);
                }
            },
            Val::Record(r) => match r {
                Some(r) => record_key(r, out),
                None => out.push(0),
            },
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Level {
    Top,
    Actor,
    Target,
    Routine,
}

/// Every field the plan includes, in a fixed order.
fn visit(c: &SkillCtx, knack: &str, p: &Plan, mut f: impl FnMut(Level, &'static str, Val)) {
    let a = &c.actor;
    let has = |mask: u32, i: usize| mask & (1 << i) != 0;
    for (i, name) in ACTOR.iter().enumerate() {
        if p.top & 1 == 0 || !has(p.actor, i) {
            continue;
        }
        let v = match *name {
            "id" => Val::I(a.id as i64),
            "kind" => Val::Str(&a.kind),
            "hp" => Val::F(a.hp),
            "hunger" => Val::F(a.hunger),
            "energy" => Val::F(a.energy),
            "near_fire" => Val::B(a.near_fire),
            "near_shelter" => Val::B(a.near_shelter),
            "terrain" => Val::Str(&a.terrain),
            "activity" => Val::Str(&a.activity),
            "age" => Val::F(a.age),
            "stage" => Val::Str(&a.stage),
            "life" => Val::F(a.life),
            "knows" => Val::List(&a.knows),
            "inv" => Val::Inv(&a.inv, &p.actor_inv),
            "kin_near" => Val::I(a.kin_near as i64),
            "pasture" => Val::F(a.pasture),
            "hurt_by" => Val::I(a.hurt_by as i64),
            "hurt_ago" => Val::Ago(a.hurt_ago),
            "yielded_ago" => Val::Ago(a.yielded_ago),
            "sensed" => Val::Inv(&a.sensed, &p.actor_sensed),
            "bold" => Val::B(a.bold),
            "room" => Val::I(a.room as i64),
            "community" => Val::I(a.community as i64),
            "home" => Val::Str(&a.home),
            "lit" => Val::B(a.lit),
            // How good the actor is at the skill being performed (knack × practice).
            "factor" => Val::F(crate::genes::skill_factor(&a.genes, &a.practice, &c.skill, knack)),
            gene => Val::F(crate::genes::gene(&a.genes, gene)),
        };
        f(Level::Actor, name, v);
    }
    let t = &c.target;
    for (i, name) in TARGET.iter().enumerate() {
        if p.top & 2 == 0 || !has(p.target, i) {
            continue;
        }
        let v = match *name {
            "class" => Val::Str(&t.class),
            "id" => Val::I(t.id as i64),
            "kind" => Val::Str(&t.kind),
            "name" => Val::Str(&t.name),
            "amount" => Val::F(t.amount),
            "hp" => Val::F(t.hp),
            "max_hp" => Val::F(t.max_hp),
            "stage" => Val::Str(&t.stage),
            "hurt_ago" => Val::F(t.hurt_ago),
            "alive" => Val::B(t.alive),
            "dist" => Val::F(t.dist),
            "inv" => Val::Inv(&t.inv, &p.target_inv),
            "knows" => Val::List(&t.knows),
            "activity" => Val::Str(&t.activity),
            "yielded_ago" => Val::Ago(t.yielded_ago),
            "near_fire" => Val::B(t.near_fire),
            "company" => Val::I(t.company as i64),
            "bearing" => Val::F(t.bearing),
            "community" => Val::I(t.community as i64),
            "owner" => Val::I(t.owner as i64),
            "home" => Val::Str(&t.home),
            "hosts" => Val::B(t.hosts),
            "lit" => Val::B(t.lit),
            "fuel" => Val::F(t.fuel),
            _ => Val::F(t.closing),
        };
        f(Level::Target, name, v);
    }
    let r = &c.routine;
    for (i, name) in ROUTINE.iter().enumerate() {
        if p.top & 4 == 0 || p.routine & (1 << i) == 0 {
            continue;
        }
        let v = match *name {
            "exists" => Val::B(r.exists),
            "ok" => Val::I(r.ok as i64),
            "failed" => Val::I(r.failed as i64),
            _ => Val::F(r.changed_s),
        };
        f(Level::Routine, name, v);
    }
    for (i, name) in TOP.iter().enumerate().skip(3) {
        if p.top & (1 << i) == 0 {
            continue;
        }
        let v = match *name {
            "item" => Val::Str(&c.item),
            "qty" => Val::I(c.qty as i64),
            "night" => Val::B(c.night),
            "hour" => Val::F(c.hour),
            "season" => Val::Str(&c.season),
            "text" => Val::Str(&c.text),
            "topic" => Val::Str(&c.topic),
            "roll" => Val::F(c.roll),
            "raining" => Val::B(c.raining),
            "want" => Val::Str(&c.want),
            "want_qty" => Val::I(c.want_qty as i64),
            "records" => Val::Records(&c.records),
            "record" => Val::Record(c.record.as_ref()),
            "daylight" => Val::F(1.0 - c.dark),
            _ => Val::Str(&c.skill),
        };
        f(Level::Top, name, v);
    }
}

/// The context map for a law with this plan.
pub fn map(c: &SkillCtx, knack: &str, p: &Plan) -> Map {
    let (mut top, mut actor, mut target, mut routine) = (Map::new(), Map::new(), Map::new(), Map::new());
    visit(c, knack, p, |level, name, v| {
        let m = match level {
            Level::Top => &mut top,
            Level::Actor => &mut actor,
            Level::Target => &mut target,
            Level::Routine => &mut routine,
        };
        m.insert(name.into(), v.dynamic());
    });
    if p.top & 1 != 0 {
        top.insert("actor".into(), actor.into());
    }
    if p.top & 2 != 0 {
        top.insert("target".into(), target.into());
    }
    if p.top & 4 != 0 {
        top.insert("routine".into(), routine.into());
    }
    top
}

/// The values of the fields a law reads, as bytes: two contexts with the same key give the law
/// the same input.
pub fn key(c: &SkillCtx, knack: &str, p: &Plan, out: &mut Vec<u8>) {
    out.clear();
    visit(c, knack, p, |_, _, v| v.key(out));
}
