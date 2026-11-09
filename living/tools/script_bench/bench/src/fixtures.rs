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
const TECHNIQUES: [&str; 8] = ["fire", "cooking", "shelter", "tanning", "mending", "fire_bolt", "carpentry", "smoking"];
const ACTIVITIES: [&str; 8] = ["", "", "sleep", "rest", "block", "gather", "walk", "craft"];
const SEASONS: [&str; 4] = ["spring", "summer", "autumn", "winter"];
const COOLDOWN_SKILLS: [&str; 8] = ["strike", "bowshot", "firebolt", "heal", "dodge", "block", "attack", "gather"];

fn genes(r: &mut Rng) -> Genes {
    let mut g = Genes::new();
    for b in living_rules::genes::BODY {
        g.insert(b.to_string(), r.range(0.8, 1.25));
    }
    // A knack for every skilled skill in the catalog, as `genes::founder` gives a person.
    for sk in living_rules::catalog::SKILLS {
        if !matches!(sk.name, "wait" | "sleep" | "rest" | "eat" | "signal" | "goto" | "follow" | "wander" | "flee") {
            g.insert(format!("knack:{}", sk.name), r.range(0.85, 1.15));
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
        yielded_ago: r.chance(0.1).then(|| r.range(0.0, 30_000.0)),
        sensed,
        bold: r.chance(0.05),
        room: r.n(8, 25),
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
        });
    }
    Fixtures { rates, strike, skills: &COOLDOWN_SKILLS, perceived }
}
