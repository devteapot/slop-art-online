//! Deterministic, realistic inputs: actors with a full gene set (body, a knack per skilled
//! skill, temperament), practice, know-how and a pack, in the mix of states the authority sees.

use crate::{ActorFacts, SkillCtx, TargetFacts};
use living_rules::genes::Genes;

pub struct Fixtures {
    /// Contexts for `rates(a)` (no skill, no target, as the authority calls it).
    pub rates: Vec<SkillCtx>,
    /// Contexts for a strike at a target.
    pub strike: Vec<SkillCtx>,
    /// Skill names for `combat_cooldown(skill)`.
    pub skills: &'static [&'static str],
    /// Observers looking at targets, for `perceived_of(p)`.
    pub perceived: Vec<living_rules::script::RegardIn>,
    /// Gives by a party to an agreement, a demand and a regard, for `on_give(a)`.
    pub hooks: Vec<SkillCtx>,
}

/// A giver's records: an agreement it is delivering on (as `from` or `to`), a demand made of it
/// and its community's regard, the kinds the shipped rules make (docs/WORLD_RULES.md).
fn records(r: &mut Rng, giver: u32, other: u32) -> Vec<living_rules::records::RecordFacts> {
    use living_rules::records::{RecordFacts, COMMUNITY};
    let t = |v: serde_json::Value| v.as_object().cloned().unwrap_or_default();
    let me = if r.chance(0.5) { "from" } else { "to" };
    let (from, to) = if me == "from" { (giver, other) } else { (other, giver) };
    let done = r.n(0, 9) as i64;
    vec![
        RecordFacts { id: 1, kind: "agreement".into(), status: "agreed".into(), open: true, terms: t(serde_json::json!({"from_gives": "wood", "from_qty": 10, "to_gives": "wood", "to_qty": 10, "from_done": done, "to_done": done, "from_home": "10,10", "to_home": "40,12", "words": "stack it at my store"})), parties: vec![("from".into(), from as u64), ("to".into(), to as u64)], me: me.into(), by: from, age_s: 60.0, due_s: Some(300.0) },
        RecordFacts { id: 2, kind: "demand".into(), status: "open".into(), open: true, terms: t(serde_json::json!({"item": "wood", "qty": 3, "done": 0, "words": "the gate-due"})), parties: vec![("by".into(), other as u64), ("of".into(), giver as u64)], me: "of".into(), by: other, age_s: 30.0, due_s: Some(60.0) },
        RecordFacts { id: 3, kind: "regard".into(), status: "held".into(), open: true, terms: t(serde_json::json!({"label": "rival town", "value": -35, "why": "the broken match"})), parties: vec![("holder".into(), COMMUNITY | 2), ("toward".into(), COMMUNITY | 3)], me: "holder".into(), by: 0, age_s: 9_000.0, due_s: None },
    ]
}

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        // xorshift64*
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545F4914F6CDD1D)
    }
    fn f(&mut self) -> f32 {
        (self.next() >> 40) as f32 / (1u64 << 24) as f32
    }
    fn range(&mut self, lo: f32, hi: f32) -> f32 {
        lo + (hi - lo) * self.f()
    }
    fn chance(&mut self, p: f32) -> bool {
        self.f() < p
    }
    fn pick<'a>(&mut self, xs: &[&'a str]) -> &'a str {
        xs[(self.next() % xs.len() as u64) as usize]
    }
    fn n(&mut self, lo: u32, hi: u32) -> u32 {
        lo + (self.next() % (hi - lo + 1) as u64) as u32
    }
}

const ITEMS: [&str; 10] = ["berries", "wood", "cloak", "spear", "armor", "arrow", "bow", "basket", "fiber", "hide"];
const TECHNIQUES: [&str; 8] = ["fire", "cooking", "shelter", "tanning", "wound_tending", "fire_bolt", "carpentry", "smoking"];
const ACTIVITIES: [&str; 8] = ["", "", "sleep", "rest", "block", "gather", "walk", "craft"];
const SEASONS: [&str; 4] = ["spring", "summer", "autumn", "winter"];
/// The skills the Rust catalog listed before skills were declared in the script (2026-11-10),
/// in its order: the fixtures' knacks stay what they were.
const KNACK_SKILLS: [&str; 57] = ["goto", "wander", "gather", "eat", "sleep", "rest", "build", "pave", "open", "close", "craft", "cook", "smoke", "clear", "give", "store", "drop", "take", "attack", "seize", "threaten", "yield", "offer", "accept", "found", "join", "welcome", "host", "leave", "dodge", "block", "strike", "bowshot", "firebolt", "heal", "throw", "shoot", "follow", "flee", "wait", "conceive", "teach", "experiment", "write", "tend", "read", "plant", "signal", "rework", "wave", "appraise", "nod", "face", "step_aside", "keep", "play", "graze"];
const COOLDOWN_SKILLS: [&str; 8] = ["strike", "bowshot", "firebolt", "heal", "dodge", "block", "attack", "gather"];

fn genes(r: &mut Rng) -> Genes {
    let mut g = Genes::new();
    for b in living_rules::genes::BODY {
        g.insert(b.to_string(), r.range(0.8, 1.25));
    }
    // A knack for every skilled skill in the catalog, as `genes::founder` gives a person.
    for sk in KNACK_SKILLS {
        if !matches!(sk, "wait" | "sleep" | "rest" | "eat" | "signal" | "goto" | "follow" | "wander" | "flee") {
            g.insert(format!("knack:{sk}"), r.range(0.85, 1.15));
        }
    }
    for t in living_rules::genes::PERSON_TRAITS {
        g.insert(format!("trait:{t}"), r.range(10.0, 90.0).round());
    }
    g
}

fn pack(r: &mut Rng, lo: u32, hi: u32) -> Vec<(String, u32)> {
    let mut items: Vec<&str> = ITEMS.to_vec();
    let n = r.n(lo, hi) as usize;
    let mut out = Vec::new();
    for _ in 0..n.min(items.len()) {
        let i = (r.next() % items.len() as u64) as usize;
        out.push((items.remove(i).to_string(), r.n(1, 12)));
    }
    out
}

fn actor(r: &mut Rng, id: u32) -> ActorFacts {
    let kind = match r.n(0, 9) {
        0..=6 => "person",
        7 | 8 => "wolf",
        _ => "deer",
    };
    let stage = match r.n(0, 19) {
        0 => "infant",
        1 => "child",
        2 | 3 => "elder",
        _ => "adult",
    };
    let person = kind == "person";
    let mut practice = std::collections::BTreeMap::new();
    for sk in ["strike", "gather", "craft", "build", "cook", "attack", "tend", "teach"] {
        if r.chance(0.7) {
            practice.insert(sk.to_string(), r.n(0, 200));
        }
    }
    let mut knows = Vec::new();
    if person {
        for t in TECHNIQUES {
            if r.chance(0.5) {
                knows.push(t.to_string());
            }
        }
    }
    let sensed = if kind == "wolf" && r.chance(0.5) { vec![("deer".to_string(), r.n(1, 3)), ("person".to_string(), r.n(0, 2))] } else { Vec::new() };
    let hurt = r.chance(0.3);
    ActorFacts {
        id,
        kind: kind.into(),
        hp: r.range(10.0, 100.0),
        hunger: r.range(0.0, 110.0).min(100.0),
        energy: r.range(-5.0, 100.0).max(0.0),
        near_fire: r.chance(0.3),
        near_shelter: r.chance(0.3),
        terrain: r.pick(&["grass", "forest", "road", "sand"]).into(),
        activity: r.pick(&ACTIVITIES).into(),
        inv: if person { pack(r, 2, 6) } else { Vec::new() },
        age: r.range(0.5, 60.0),
        stage: stage.into(),
        life: r.f(),
        knows,
        genes: genes(r),
        practice,
        kin_near: r.n(0, 4),
        pasture: r.range(0.0, 3.0),
        hurt_by: if hurt { r.n(1, 40) } else { 0 },
        hurt_ago: hurt.then(|| r.range(0.0, 20_000.0)),
        hurt_by_near: hurt && r.range(0.0, 1.0) < 0.5,
        yielded_ago: r.chance(0.1).then(|| r.range(0.0, 30_000.0)),
        sensed,
        bold: r.chance(0.05),
        room: r.n(8, 25),
        community: 0,
        home: String::new(),
        lit: false,
        // Rested breath and focus (no extra draws, so the samples before stamina-1 stay the same).
        stamina: 100.0,
        focus: 100.0,
        sex: String::new(),
    }
}

fn target(r: &mut Rng, actor_id: u32) -> TargetFacts {
    let kind = r.pick(&["wolf", "deer", "person", "person"]);
    let max_hp = match kind {
        "deer" => 40.0,
        "wolf" => 55.0,
        _ => 100.0,
    };
    TargetFacts {
        class: if r.chance(0.92) { "creature" } else { "resource" }.into(),
        id: if r.chance(0.04) { actor_id as u64 } else { r.n(1, 40) as u64 },
        kind: kind.into(),
        name: if kind == "person" { r.pick(&["Grim", "Asha", "Toli"]).into() } else { String::new() },
        amount: 0.0,
        hp: r.range(5.0, max_hp),
        max_hp,
        stage: r.pick(&["adult", "adult", "adult", "child", "elder"]).into(),
        hurt_ago: r.range(0.0, 60_000.0),
        alive: r.chance(0.95),
        dist: r.range(0.5, 1.5),
        inv: if kind == "person" { pack(r, 1, 4) } else { Vec::new() },
        knows: Vec::new(),
        activity: r.pick(&ACTIVITIES).into(),
        yielded_ago: None,
        near_fire: r.chance(0.3),
        company: r.n(0, 3),
        bearing: r.range(0.0, 3.1),
        closing: r.range(-2.0, 2.0),
        community: 0,
        owner: 0,
        home: String::new(),
        hosts: false,
        lit: false,
        fuel: 0.0,
        sex: String::new(),
    }
}

fn world(r: &mut Rng, c: &mut SkillCtx) {
    c.night = r.chance(0.4);
    c.hour = r.range(0.0, 24.0);
    c.season = r.pick(&SEASONS).into();
    c.raining = r.chance(0.25);
    c.roll = r.f();
}

pub fn build() -> Fixtures {
    let mut r = Rng(0x5eed_1234_abcd_0001);
    let mut rates = Vec::new();
    for i in 0..64 {
        let mut c = SkillCtx { actor: actor(&mut r, 100 + i), ..Default::default() };
        world(&mut r, &mut c);
        rates.push(c);
    }
    let mut strike = Vec::new();
    for i in 0..64 {
        let id = 100 + i;
        let mut a = actor(&mut r, id);
        // Most strikes are fighters' (an adult with energy) so the full path runs.
        if r.chance(0.8) {
            a.stage = "adult".into();
            a.energy = a.energy.max(20.0);
            a.yielded_ago = None;
        }
        let mut c = SkillCtx { target: target(&mut r, id), actor: a, skill: "strike".into(), ..Default::default() };
        world(&mut r, &mut c);
        strike.push(c);
    }
    let mut perceived = Vec::new();
    for i in 0..16u32 {
        let (observer, target) = [("person", "person"), ("person", "wolf"), ("wolf", "wolf"), ("wolf", "person")][(i % 4) as usize];
        let knows = TECHNIQUES.iter().filter(|_| r.chance(0.5)).map(|t| t.to_string()).collect();
        perceived.push(living_rules::script::RegardIn {
            observer_kind: observer.into(),
            knows,
            target_kind: target.into(),
            known: r.chance(0.5),
            revealed: if r.chance(0.3) { vec!["health".into()] } else { vec![] },
            own: i == 5,
            night: r.chance(0.4),
            dist: 0,
        });
    }
    let mut hooks = Vec::new();
    for i in 0..16u32 {
        let (giver, other) = (1 + i, 100 + i);
        let mut c = SkillCtx { skill: "give".into(), item: "wood".into(), qty: r.n(1, 4), ..Default::default() };
        c.actor.id = giver;
        c.actor.kind = "person".into();
        c.target = TargetFacts { class: "creature".into(), id: other as u64, kind: "person".into(), alive: true, dist: 1.0, ..Default::default() };
        c.records = records(&mut r, giver, other);
        hooks.push(c);
    }
    Fixtures { rates, strike, skills: &COOLDOWN_SKILLS, perceived, hooks }
}
