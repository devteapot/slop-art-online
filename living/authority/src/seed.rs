//! World creation: terrain, resources, people and animals.

use crate::motion;
use crate::tables::*;
use crate::common;
use living_rules::map::{chunk_of, Terrain};
use serde::Deserialize;
use spacetimedb::rand::Rng;
use spacetimedb::{Identity, ReducerContext, Table};

/// The seed compiled into this module: `seeds/world.json` (the active world; `just living-seed
/// <name>` copies one there) or, for lab scenarios, `seeds/$LIVING_SEED.json` (see build.rs).
pub const VALLEY: &str = include_str!(concat!(env!("OUT_DIR"), "/seed.json"));
pub const INSTINCTS: &str = include_str!("../../seeds/instincts.json");
pub const REPERTOIRE: &str = include_str!("../../seeds/repertoire.json");

thread_local! {
    /// The seed's resource abundance while the land is generated.
    static RESOURCE_SCALE: std::cell::RefCell<std::collections::BTreeMap<String, f32>> = const { std::cell::RefCell::new(std::collections::BTreeMap::new()) };
}

/// A person's starting way of life: common routines, one for their work, and weighted desires
/// that call them. It is theirs: the mind keeps, changes or drops any of it.
pub fn give_repertoire(ctx: &ReducerContext, id: u32, occupation: &str, now: u64) {
    let r: serde_json::Value = serde_json::from_str(REPERTOIRE).expect("repertoire json");
    let occ = r["occupations"].get(occupation).or_else(|| r["occupations"].get("forager")).cloned().unwrap_or_default();
    let work = occ["routine"].as_str().unwrap_or("forage").to_string();
    let mut routines: Vec<crate::mind::RoutineIn> = r["common"].as_object().map(|m| m.iter().map(|(k, g)| crate::mind::RoutineIn { name: k.clone(), graph: g.to_string() }).collect()).unwrap_or_default();
    routines.push(crate::mind::RoutineIn { name: work.clone(), graph: occ["graph"].to_string() });
    let _ = crate::mind::set_routines(ctx, id, &routines, &format!("habit ({occupation})"), now);
    let top = r["top"].to_string().replace("\"WORK\"", &serde_json::to_string(&work).unwrap_or_default());
    if let Ok(g) = living_rules::graph::parse(&top) {
        let _ = crate::mind::set_graph(ctx, id, &g.to_json(), &format!("my way of life ({occupation})"), "habit", now);
    }
}

/// A grown animal's way of life: its species' routines and the desires that weigh them
/// (its to change, like a person's habits).
pub fn give_ways(ctx: &ReducerContext, id: u32, kind: &str, now: u64) {
    let r: serde_json::Value = serde_json::from_str(REPERTOIRE).expect("repertoire json");
    let Some(ways) = r["species"].get(kind) else { return };
    let routines: Vec<crate::mind::RoutineIn> = ways["routines"].as_object().map(|m| m.iter().map(|(k, g)| crate::mind::RoutineIn { name: k.clone(), graph: g.to_string() }).collect()).unwrap_or_default();
    let _ = crate::mind::set_routines(ctx, id, &routines, &format!("{kind} instinct"), now);
    if let Ok(g) = living_rules::graph::parse(&ways["top"].to_string()) {
        let _ = crate::mind::set_graph(ctx, id, &g.to_json(), &format!("the ways of a {kind}"), "instinct", now);
    }
}
pub const SKILLS: &str = include_str!("../../scripts/skills.rhai");

#[derive(Deserialize)]
pub struct SeedMap {
    /// `valley` (96×96 classic) or `realm` (any size, coast/rivers/towns/wilds).
    pub kind: String,
    #[serde(default)]
    pub w: u32,
    #[serde(default)]
    pub h: u32,
}

/// An established town, laid out around one of the realm's proposed town sites.
#[derive(Deserialize)]
pub struct SeedTown {
    pub name: String,
    /// What the town is known for (goes into residents' backgrounds).
    #[serde(default)]
    pub character: String,
    /// Occupation → number of residents (history, not assignment).
    pub occupations: std::collections::BTreeMap<String, u32>,
    #[serde(default)]
    pub stores: std::collections::BTreeMap<String, u32>,
    #[serde(default)]
    pub ledger: String,
    /// A walled city (wall ring, gates) or an open village.
    #[serde(default = "yes")]
    pub walled: bool,
}

fn yes() -> bool {
    true
}

fn one_f() -> f32 {
    1.0
}

fn eight() -> u32 {
    living_rules::YEAR_DAYS as u32
}

impl SeedTown {
    fn households(&self) -> usize {
        (self.occupations.values().sum::<u32>() as usize).div_ceil(3).max(1)
    }
}

/// A small band starting from almost nothing in the wilds.
#[derive(Deserialize)]
pub struct SeedBand {
    pub name: String,
    #[serde(default)]
    pub size: u32,
    #[serde(default)]
    pub history: String,
    /// Know-how of the band's first member (or of every adult, with `family`).
    #[serde(default)]
    pub knows: Vec<String>,
    /// A family of all ages instead of `size` adults: each member's stage
    /// (elder, adult, child, infant) and trade; the young are children of the first two adults.
    #[serde(default)]
    pub family: Vec<SeedMember>,
}

#[derive(Deserialize)]
pub struct SeedMember {
    pub stage: String,
    #[serde(default)]
    pub occupation: String,
}

#[derive(Deserialize)]
pub struct Seed {
    pub run: String,
    pub seed: u64,
    #[serde(default)]
    pub map: Option<SeedMap>,
    /// Lifespans are multiplied by this (1 = a world for play; labs compress lives).
    #[serde(default = "one_f")]
    pub life_pace: f32,
    /// Days in the calendar year (lifespans are counted in years).
    #[serde(default = "eight")]
    pub year_days: u32,
    #[serde(default)]
    pub towns: Vec<SeedTown>,
    /// Multiplies how many of each resource kind the land grows (1 = normal).
    #[serde(default)]
    pub resource_scale: std::collections::BTreeMap<String, f32>,
    /// Open villages at the realm's village sites.
    #[serde(default)]
    pub villages: Vec<SeedTown>,
    #[serde(default)]
    pub bands: Vec<SeedBand>,
    #[serde(default)]
    pub people: Vec<SeedPerson>,
    pub animals: SeedAnimals,
    #[serde(default)]
    pub artifacts: Vec<SeedArtifact>,
    #[serde(default)]
    pub structures: Vec<SeedStructure>,
    #[serde(default)]
    pub communities: Vec<SeedCommunity>,
}

pub fn communities(ctx: &ReducerContext, now: u64) {
    let Ok(s) = serde_json::from_str::<Seed>(VALLEY) else { return };
    for sc in &s.communities {
        if ctx.db.community().iter().any(|c| c.name == sc.name) {
            continue;
        }
        let ids: Vec<u32> = sc.members.iter().filter_map(|n| ctx.db.character().iter().find(|c| &c.name == n && c.alive).map(|c| c.id)).collect();
        let founder = ids.first().copied().unwrap_or(0);
        let c = ctx.db.community().insert(Community { id: 0, name: sc.name.clone(), founder, founded_ms: 0, home_x: sc.home[0], home_y: sc.home[1] });
        for id in ids {
            if ctx.db.membership().member().find(id).is_none() {
                ctx.db.membership().insert(Membership { id: 0, community: c.id, member: id, since_ms: now });
            }
        }
    }
}

#[derive(Deserialize)]
pub struct SeedPerson {
    pub name: String,
    pub at: [f32; 2],
    #[serde(default)]
    pub knows: Vec<String>,
}

#[derive(Deserialize)]
pub struct SeedCommunity {
    pub name: String,
    pub home: [f32; 2],
    pub members: Vec<String>,
}

#[derive(Deserialize)]
pub struct SeedStructure {
    pub kind: String,
    pub at: [f32; 2],
    #[serde(default)]
    pub owner: String,
    #[serde(default)]
    pub contents: std::collections::BTreeMap<String, u32>,
}

#[derive(Deserialize)]
pub struct SeedArtifact {
    pub kind: String,
    pub at: [f32; 2],
    pub author_name: String,
    #[serde(default)]
    pub topic: String,
    pub text: String,
}

#[derive(Deserialize)]
pub struct SeedAnimals {
    pub deer: u32,
    pub wolf: u32,
}

pub fn young_instinct(kind: &str) -> String {
    let all: serde_json::Value = serde_json::from_str(INSTINCTS).expect("instincts json");
    all.get(format!("{kind}_young").as_str()).map(|v| v.to_string()).unwrap_or_else(|| instinct(kind))
}

pub fn instinct(kind: &str) -> String {
    let all: serde_json::Value = serde_json::from_str(INSTINCTS).expect("instincts json");
    all.get(kind).or_else(|| all.get("person")).map(|v| v.to_string()).unwrap_or_default()
}

pub fn seed(ctx: &ReducerContext, now: u64) {
    let s: Seed = serde_json::from_str(VALLEY).expect("seed json");
    let (mut map, realm) = match &s.map {
        Some(m) if m.kind == "realm" => {
            let r = living_rules::realm::generate(s.seed, m.w.max(64), m.h.max(64));
            (r.to_map(), Some(r))
        }
        _ => (living_rules::map::generate(s.seed), None),
    };
    // Settlements are laid out first: their walls and roads are part of the terrain.
    let mut settlements: Vec<(&SeedTown, living_rules::city::Layout)> = Vec::new();
    if let Some(r) = &realm {
        for (t, site) in s.towns.iter().zip(r.towns.iter()).chain(s.villages.iter().zip(r.villages.iter())) {
            let n = t.households();
            let radius = if t.walled { (3 + n as i32).clamp(9, 16) } else { 5 };
            let layout = living_rules::city::lay_out(&mut map, *site, n, radius, t.walled);
            settlements.push((t, layout));
        }
    }
    let map = map;
    for id in map.chunks().collect::<Vec<_>>() {
        ctx.db.terrain_chunk().insert(TerrainChunk { id, tiles: map.chunk_bytes(id) });
    }
    if let Some(mut w) = ctx.db.world().id().find(0) {
        w.run = s.run.clone();
        w.seed = s.seed;
        w.width = map.w;
        w.height = map.h;
        w.life_pace = s.life_pace;
        w.year_days = s.year_days;
        ctx.db.world().id().update(w);
        common::invalidate_calendar();
    }
    common::invalidate_map();
    RESOURCE_SCALE.with(|r| *r.borrow_mut() = s.resource_scale.clone());
    spawn_resources(ctx, &map, now);
    let admin = common::world(ctx).admin;
    for p in &s.people {
        let at = map.nearest_walkable(p.at[0], p.at[1]).unwrap_or((48.0, 48.0));
        let id = spawn_creature(ctx, &p.name, "person", admin, true, at, now);
        common::inv_add(ctx, id as u64, "berries", 5);
        for t in &p.knows {
            common::learn(ctx, id, t, "seed", now);
        }
        crate::perceive::request_deliberation(ctx, id, "You are taking in your surroundings.", now);
    }
    for st in &s.structures {
        let at = map.nearest_walkable(st.at[0], st.at[1]).unwrap_or((48.0, 48.0));
        let owner = ctx.db.character().iter().find(|c| c.name == st.owner).map(|c| c.id).unwrap_or(0);
        let row = ctx.db.structure().insert(Structure { id: 0, kind: st.kind.clone(), x: at.0, y: at.1, chunk: chunk_of(at.0, at.1), owner, built_ms: now });
        for (item, q) in &st.contents {
            common::inv_add(ctx, STRUCTURE_BIT | row.id, item, *q);
        }
    }
    for a in &s.artifacts {
        let at = map.nearest_walkable(a.at[0], a.at[1]).unwrap_or((48.0, 48.0));
        let st = ctx.db.structure().insert(Structure { id: 0, kind: a.kind.clone(), x: at.0, y: at.1, chunk: chunk_of(at.0, at.1), owner: 0, built_ms: 0 });
        ctx.db.artifact().insert(Artifact { id: 0, kind: a.kind.clone(), holder: STRUCTURE_BIT | st.id, author: 0, author_name: a.author_name.clone(), written_ms: 0, topic: a.topic.clone(), text: a.text.clone() });
    }
    for (t, layout) in &settlements {
        town(ctx, &map, t, layout, now);
    }
    if let Some(r) = &realm {
        for (i, b) in s.bands.iter().enumerate() {
            if let Some(site) = r.wilds.get(i) {
                band(ctx, &map, b, *site, now);
            }
        }
    } else {
        // Without a realm's wild sites, families live where people would: on open
        // ground with berries and water within reach.
        let mut taken: Vec<(f32, f32)> = Vec::new();
        for b in &s.bands {
            let site = homestead(ctx, &map, &taken);
            taken.push(site);
            band(ctx, &map, b, site, now);
        }
    }
    communities(ctx, now);
    for (kind, count) in [("deer", s.animals.deer), ("wolf", s.animals.wolf)] {
        for _ in 0..count {
            if let Some(at) = animal_spot(ctx, &map, kind) {
                spawn_animal(ctx, kind, at, now);
            }
        }
    }
}

/// An animal is a character like any other: its own name, an LLM mind (via the admin
/// controller) and a species body. Names come from the species list, then numbered.
pub fn spawn_animal(ctx: &ReducerContext, kind: &str, at: (f32, f32), now: u64) -> u32 {
    let name = animal_name(ctx, kind);
    let admin = common::world(ctx).admin;
    // Seeded wildlife spans all ages (fractions of the lifespan).
    let w = common::world(ctx);
    let f = ctx.rng().gen_range(0.1f32..0.8);
    let age = common::life_of(kind).age_at(f, common::pace(&w));
    spawn_with(ctx, &name, kind, admin, true, at, now, age, (0, 0))
}

/// A newborn animal: named from its species' list, beside its mother.
pub fn spawn_young(ctx: &ReducerContext, kind: &str, at: (f32, f32), now: u64, parents: (u32, u32)) -> u32 {
    let name = animal_name(ctx, kind);
    let admin = common::world(ctx).admin;
    spawn_with(ctx, &name, kind, admin, true, at, now, 0.0, parents)
}

fn animal_name(ctx: &ReducerContext, kind: &str) -> String {
    let names = common::species(kind).map(|s| s.names).unwrap_or_default();
    let used: Vec<String> = ctx.db.character().kind().filter(kind).map(|c| c.name).collect();
    let name = names
        .iter()
        .find(|n| !used.contains(n))
        .cloned()
        .unwrap_or_else(|| format!("{} {}", names.get(used.len() % names.len().max(1)).cloned().unwrap_or_else(|| kind.to_string()), used.len() / names.len().max(1) + 1));
    name
}

pub fn animal_spot(ctx: &ReducerContext, map: &living_rules::map::Map, kind: &str) -> Option<(f32, f32)> {
    for _ in 0..200 {
        let x = ctx.rng().gen_range(4..map.w as i32 - 4);
        let y = ctx.rng().gen_range(4..map.h as i32 - 4);
        let t = map.get(x, y);
        let ok = match kind {
            "wolf" => t == Terrain::Forest,
            _ => t == Terrain::Grass,
        };
        if ok {
            return Some((x as f32 + 0.5, y as f32 + 0.5));
        }
    }
    None
}

/// A grown creature (a quarter of the way through life) with no known parents.
pub fn spawn_creature(ctx: &ReducerContext, name: &str, kind: &str, controller: Identity, ai: bool, at: (f32, f32), now: u64) -> u32 {
    let w = common::world(ctx);
    let age = common::life_of(kind).age_at(0.25, common::pace(&w));
    spawn_with(ctx, name, kind, controller, ai, at, now, age, (0, 0))
}

#[allow(clippy::too_many_arguments)]
pub fn spawn_with(ctx: &ReducerContext, name: &str, kind: &str, controller: Identity, ai: bool, at: (f32, f32), now: u64, age: f32, parents: (u32, u32)) -> u32 {
    let c = ctx.db.character().insert(Character {
        id: 0,
        name: name.into(),
        kind: kind.into(),
        controller,
        ai,
        alive: true,
        born_ms: now,
        died_ms: 0,
        cause: String::new(),
        home_x: at.0,
        home_y: at.1,
        birth_age_days: age,
        parent_a: parents.0,
        parent_b: parents.1,
        stage: {
            let w = common::world(ctx);
            common::stage_code(common::life_of(kind).stage(age, common::pace(&w)))
        },
    });
    let id = c.id;
    motion::spawn_body(ctx, id, kind, at, now);
    let max_hp = common::scripts(ctx).num_of("max_hp", kind, 100.0) as f32;
    ctx.db.vitals().insert(Vitals {
        id,
        hp: max_hp,
        max_hp,
        hunger: 25.0,
        energy: 85.0,
        at_ms: now,
        hp_rate: 0.0,
        hunger_rate: 0.0,
        energy_rate: 0.0,
        rate_key: 0,
        hurt_ms: 0,
        hurt_by: 0,
    });
    // The young start from their species' young instinct (a baby cries and follows a parent).
    let graph = if c.stage == 0 { young_instinct(kind) } else { instinct(kind) };
    ctx.db.brain().insert(Brain { id, graph, revision: 1, plan: "instinct".into(), source: "instinct".into(), installed_ms: now });
    ctx.db.mind_state().insert(MindState {
        id,
        slot: (id % 60) as u8,
        revision: 1,
        cursors: Vec::new(),
        marks: Vec::new(),
        last: None,
        active: Vec::new(),
        status: String::new(),
        fails: 0,
        heard_ms: 0,
        speaker: 0,
        spoke_ms: 0,
        deliberated_ms: now,
        seen: Vec::new(),
        alerts: 0,
        fast_until: 0,
    });
    if kind == "person" && parents.0 == 0 {
        common::chronicle(ctx, now, "arrival", id, 0, at, format!("{name} arrived"));
    }
    if kind != "person" && c.stage >= 2 {
        give_ways(ctx, id, kind, now);
    }
    id
}

fn spawn_resources(ctx: &ReducerContext, map: &living_rules::map::Map, now: u64) {
    let sc = common::scripts(ctx);
    let near = |x: i32, y: i32, t: Terrain, r: i32| {
        for dy in -r..=r {
            for dx in -r..=r {
                if map.get(x + dx, y + dy) == t {
                    return true;
                }
            }
        }
        false
    };
    // Spacing via a coarse grid (cheap on large maps).
    let mut placed: std::collections::HashMap<(i32, i32), Vec<(f32, f32)>> = std::collections::HashMap::new();
    let place = |ctx: &ReducerContext, kind: &str, x: i32, y: i32, max: f32, spacing: f32, placed: &mut std::collections::HashMap<(i32, i32), Vec<(f32, f32)>>| -> bool {
        let p = (x as f32 + 0.5, y as f32 + 0.5);
        let cell = (x / 8, y / 8);
        for dy in -1..=1 {
            for dx in -1..=1 {
                if let Some(v) = placed.get(&(cell.0 + dx, cell.1 + dy)) {
                    if v.iter().any(|q| common::dist(*q, p) < spacing) {
                        return false;
                    }
                }
            }
        }
        placed.entry(cell).or_default().push(p);
        ctx.db.resource_node().insert(ResourceNode {
            id: 0,
            kind: kind.into(),
            x: p.0,
            y: p.1,
            chunk: chunk_of(p.0, p.1),
            amount: max,
            max,
            regen: sc.num_of("regrow", kind, 0.5) as f32,
            at_ms: now,
        });
        true
    };
    let scale = ((map.w * map.h) as f32 / (96.0 * 96.0)).max(1.0);
    let abundance = |kind: &str| RESOURCE_SCALE.with(|r| r.borrow().get(kind).copied().unwrap_or(1.0));
    let cap = |n: u32| (n as f32 * scale) as u32;
    let mut rng_tiles: Vec<(i32, i32)> = (0..map.h as i32).flat_map(|y| (0..map.w as i32).map(move |x| (x, y))).collect();
    // Deterministic shuffle from the reducer RNG.
    for i in (1..rng_tiles.len()).rev() {
        let j = ctx.rng().gen_range(0..=i);
        rng_tiles.swap(i, j);
    }
    let mut counts = std::collections::HashMap::<&str, u32>::new();
    for (x, y) in rng_tiles {
        let t = map.get(x, y);
        let (kind, max, spacing, cap) = match t {
            Terrain::Forest if near(x, y, Terrain::Grass, 2) => ("tree", 8.0, 2.5, cap(70)),
            Terrain::Forest => ("tree", 8.0, 4.0, cap(90)),
            Terrain::Grass if near(x, y, Terrain::Water, 1) && (x * 7 + y * 3) % 5 == 0 => ("clay_bank", 6.0, 6.0, cap(25)),
            Terrain::Grass if near(x, y, Terrain::Forest, 3) => ("berry_bush", 5.0, 3.0, cap(60)),
            Terrain::Grass if near(x, y, Terrain::Rock, 2) => ("boulder", 6.0, 4.0, cap(25)),
            Terrain::Sand if near(x, y, Terrain::Water, 1) => {
                if counts.get("fishing_spot").copied().unwrap_or(0) < cap(20) && (x + y) % 3 == 0 {
                    ("fishing_spot", 5.0, 5.0, cap(20))
                } else {
                    ("reeds", 4.0, 3.5, cap(30))
                }
            }
            Terrain::Dirt => ("boulder", 6.0, 5.0, cap(25)),
            _ => continue,
        };
        let cap = (cap as f32 * abundance(kind)) as u32;
        let n = counts.entry(kind).or_insert(0);
        if *n >= cap {
            continue;
        }
        if place(ctx, kind, x, y, max, spacing, &mut placed) {
            *n += 1;
        }
    }
    // Sparse berry bushes in open grassland too.
    for _ in 0..(cap(25) as f32 * abundance("berry_bush")) as u32 {
        let x = ctx.rng().gen_range(4..map.w as i32 - 4);
        let y = ctx.rng().gen_range(4..map.h as i32 - 4);
        if map.get(x, y) == Terrain::Grass {
            place(ctx, "berry_bush", x, y, 5.0, 3.0, &mut placed);
        }
    }
}

// ---- realm: towns and bands --------------------------------------------------------

const SYLLABLES: [&str; 40] = [
    "ba", "ren", "ta", "li", "mo", "sa", "ve", "no", "ka", "del", "wen", "ro", "tha", "mi", "gar", "lo", "fe", "nia", "bor", "ya",
    "cor", "el", "sun", "da", "vik", "ma", "tor", "ise", "han", "ru", "pe", "ly", "os", "bri", "ga", "ne", "tu", "ari", "kel", "zo",
];

/// A pronounceable, unused name (deterministic from the reducer RNG).
fn fresh_name(ctx: &ReducerContext) -> String {
    let used: std::collections::HashSet<String> = ctx.db.character().kind().filter("person").map(|c| c.name).collect();
    loop {
        let n = ctx.rng().gen_range(2..=3);
        let mut name = String::new();
        for _ in 0..n {
            name.push_str(SYLLABLES[ctx.rng().gen_range(0..SYLLABLES.len())]);
        }
        let mut c = name.chars();
        let name = c.next().map(|f| f.to_ascii_uppercase().to_string() + c.as_str()).unwrap_or_default();
        if name.len() >= 3 && name.len() <= 9 && !used.contains(&name) {
            return name;
        }
    }
}

/// Know-how that goes with a history in an occupation (plus fire for everyone in a town).
fn occupation_know_how(occ: &str) -> &'static [&'static str] {
    match occ {
        "fisher" => &["spear", "cooking"],
        "farmer" => &["planting", "storage"],
        "builder" => &["shelter", "storage", "carpentry", "masonry"],
        "mason" => &["masonry", "toolmaking"],
        "carpenter" => &["shelter", "carpentry", "toolmaking"],
        "guard" => &["spear", "torch"],
        "hunter" => &["spear", "cloak", "torch"],
        "cook" => &["cooking", "storage"],
        "scribe" => &["writing"],
        "healer" => &["cooking", "planting"],
        "trader" => &["writing", "storage"],
        _ => &[],
    }
}

/// A place a family would choose to live: grass with the most berry bushes within 10
/// tiles, fish within 14, not on top of another family, nearer the middle on ties.
fn homestead(ctx: &ReducerContext, map: &living_rules::map::Map, taken: &[(f32, f32)]) -> (f32, f32) {
    let food: Vec<(String, f32, f32)> = ctx.db.resource_node().iter().filter(|r| r.kind == "berry_bush" || r.kind == "fishing_spot").map(|r| (r.kind, r.x, r.y)).collect();
    let (cx, cy) = (map.w as f32 / 2.0, map.h as f32 / 2.0);
    let mut best = ((cx, cy), f32::MIN);
    for y in (6..map.h as i32 - 6).step_by(2) {
        for x in (6..map.w as i32 - 6).step_by(2) {
            if map.get(x, y) != Terrain::Grass {
                continue;
            }
            let p = (x as f32 + 0.5, y as f32 + 0.5);
            if taken.iter().any(|q| (q.0 - p.0).hypot(q.1 - p.1) < 24.0) {
                continue;
            }
            let d = |r: &(String, f32, f32)| (r.1 - p.0).hypot(r.2 - p.1);
            let berries = food.iter().filter(|r| r.0 == "berry_bush" && d(r) < 10.0).count() as f32;
            let fish = food.iter().any(|r| r.0 == "fishing_spot" && d(r) < 14.0);
            let score = berries.min(6.0) + if fish { 3.0 } else { 0.0 } - (p.0 - cx).hypot(p.1 - cy) / 40.0;
            if score > best.1 {
                best = (p, score);
            }
        }
    }
    best.0
}

fn walkable_near(map: &living_rules::map::Map, at: (f32, f32)) -> (f32, f32) {
    map.nearest_walkable(at.0, at.1).unwrap_or(at)
}

fn put(ctx: &ReducerContext, map: &living_rules::map::Map, kind: &str, at: (f32, f32), owner: u32, now: u64) -> u64 {
    let at = walkable_near(map, at);
    ctx.db.structure().insert(Structure { id: 0, kind: kind.into(), x: at.0, y: at.1, chunk: chunk_of(at.0, at.1), owner, built_ms: now }).id
}

/// An established settlement laid out by `living_rules::city`: a hearth, stores and a sign on
/// the market square, a house per household along the streets, gates in the wall kept by the
/// settlement's community, planted fields outside; residents with histories.
fn town(ctx: &ReducerContext, map: &living_rules::map::Map, t: &SeedTown, layout: &living_rules::city::Layout, now: u64) {
    let admin = common::world(ctx).admin;
    let center = layout.center;
    let c = ctx.db.community().insert(Community { id: 0, name: t.name.clone(), founder: 0, founded_ms: 0, home_x: center.0, home_y: center.1 });
    put(ctx, map, "campfire", layout.market[0], 0, now);
    for &(gx, gy) in &layout.gates {
        let p = (gx as f32 + 0.5, gy as f32 + 0.5);
        let sid = ctx.db.structure().insert(Structure { id: 0, kind: "gate".into(), x: p.0, y: p.1, chunk: chunk_of(p.0, p.1), owner: 0, built_ms: 0 }).id;
        ctx.db.gate().insert(Gate { id: sid, x: gx, y: gy, open: true, community: c.id, changed_ms: now, changed_by: 0 });
    }
    // Residents by occupation, grouped into households of 2-4.
    let mut roles: Vec<String> = t.occupations.iter().flat_map(|(o, n)| std::iter::repeat(o.clone()).take(*n as usize)).collect();
    for i in (1..roles.len()).rev() {
        let j = ctx.rng().gen_range(0..=i);
        roles.swap(i, j);
    }
    let mut households: Vec<Vec<String>> = Vec::new();
    while !roles.is_empty() {
        let n = ctx.rng().gen_range(2..=4).min(roles.len());
        households.push(roles.drain(..n).collect());
    }
    let mut ids = Vec::new();
    for (h, members) in households.iter().enumerate() {
        let home = layout.houses.get(h % layout.houses.len().max(1)).copied().unwrap_or(center);
        let names: Vec<String> = members.iter().map(|_| fresh_name(ctx)).collect();
        let mut household_ids = Vec::new();
        let (life, pace) = (common::life_of("person"), common::pace(&common::world(ctx)));
        for (k, occ) in members.iter().enumerate() {
            let at = (home.0 + (k as f32 - 1.0) * 0.5, home.1 + 0.6);
            // Working adults of all ages; sometimes a grandparent who still keeps a trade.
            let f = if k >= 2 && ctx.rng().gen_range(0.0f32..1.0) < 0.4 { ctx.rng().gen_range(0.76f32..0.9) } else { ctx.rng().gen_range(0.18f32..0.6) };
            let id = spawn_with(ctx, &names[k], "person", admin, true, walkable_near(map, at), now, life.age_at(f, pace), (0, 0));
            common::inv_add(ctx, id as u64, "berries", 4);
            common::learn(ctx, id, "fire", "seed", now);
            for tech in occupation_know_how(occ) {
                common::learn(ctx, id, tech, "seed", now);
            }
            give_repertoire(ctx, id, occ, now);
            if let Some(mut ch) = ctx.db.character().id().find(id) {
                ch.home_x = home.0;
                ch.home_y = home.1;
                ctx.db.character().id().update(ch);
            }
            household_ids.push((id, occ.clone()));
        }
        // Children of the household's first two adults: often a child, sometimes a baby.
        if household_ids.len() >= 2 {
            let (pa, pb) = (household_ids[0].0, household_ids[1].0);
            let mut young = Vec::new();
            if ctx.rng().gen_range(0.0f32..1.0) < 0.55 {
                young.push(ctx.rng().gen_range(life.infant * 1.5..life.child * 0.9));
            }
            if ctx.rng().gen_range(0.0f32..1.0) < 0.2 {
                young.push(ctx.rng().gen_range(0.0..life.infant * 0.7));
            }
            for f in young {
                let name = fresh_name(ctx);
                let at = walkable_near(map, (home.0 + 0.4, home.1 + 0.9));
                let id = spawn_with(ctx, &name, "person", admin, true, at, now, life.age_at(f, pace), (pa, pb));
                if let Some(mut ch) = ctx.db.character().id().find(id) {
                    ch.home_x = home.0;
                    ch.home_y = home.1;
                    ctx.db.character().id().update(ch);
                }
                if ctx.db.character().id().find(id).map_or(false, |c| c.stage >= 1) {
                    give_repertoire(ctx, id, "child", now);
                }
                household_ids.push((id, "child".into()));
            }
        }
        if h < layout.houses.len() {
            put(ctx, map, "house", home, household_ids[0].0, now);
        }
        for (id, occ) in &household_ids {
            let kin: Vec<serde_json::Value> = household_ids.iter().filter(|(o, _)| o != id).map(|(o, oc)| serde_json::json!({"id": o, "name": common::name_of(ctx, *o), "occupation": oc})).collect();
            let text = serde_json::json!({
                "origin": if t.walled { "town" } else { "village" },
                "town": t.name,
                "town_character": t.character,
                "walled": t.walled,
                "occupation": occ,
                "household": kin,
                "home": [home.0.round(), home.1.round()],
                "town_center": [center.0.round(), center.1.round()],
            });
            ctx.db.background().insert(Background { id: *id, text: text.to_string() });
            ids.push(*id);
        }
    }
    // Stores on the market square.
    let stores = if t.walled { 2 } else { 1 };
    for k in 0..stores {
        let at = layout.market.get(2 + k).copied().unwrap_or(center);
        let sid = put(ctx, map, "storage", at, ids.get(k).copied().unwrap_or(0), now);
        for (item, q) in &t.stores {
            common::inv_add(ctx, STRUCTURE_BIT | sid, item, (*q).div_ceil(stores as u32));
        }
    }
    let sc = common::scripts(ctx);
    for p in &layout.fields {
        ctx.db.resource_node().insert(ResourceNode {
            id: 0,
            kind: "berry_bush".into(),
            x: p.0,
            y: p.1,
            chunk: chunk_of(p.0, p.1),
            amount: 5.0,
            max: 5.0,
            regen: sc.num_of("regrow", "berry_bush", 1.0) as f32,
            at_ms: now,
        });
    }
    if !t.ledger.is_empty() {
        let at = layout.market.get(1).copied().unwrap_or(center);
        let sid = put(ctx, map, "sign", at, 0, now);
        ctx.db.artifact().insert(Artifact { id: 0, kind: "sign".into(), holder: STRUCTURE_BIT | sid, author: 0, author_name: format!("the elders of {}", t.name), written_ms: 0, topic: String::new(), text: t.ledger.clone() });
    }
    if let Some(mut com) = ctx.db.community().id().find(c.id) {
        com.founder = ids.first().copied().unwrap_or(0);
        ctx.db.community().id().update(com);
    }
    for id in &ids {
        ctx.db.membership().insert(Membership { id: 0, community: c.id, member: *id, since_ms: now });
    }
    let what = if t.walled { format!("{} stands walled at ({:.0}, {:.0}) with {} people and {} gates", t.name, center.0, center.1, ids.len(), layout.gates.len()) } else { format!("the village of {} lies at ({:.0}, {:.0}) with {} people", t.name, center.0, center.1, ids.len()) };
    common::chronicle(ctx, now, "arrival", 0, 0, center, what);
}

/// A band of survivors with almost nothing: no structures, a little food, little know-how.
fn band(ctx: &ReducerContext, map: &living_rules::map::Map, b: &SeedBand, site: (f32, f32), now: u64) {
    let admin = common::world(ctx).admin;
    let at = walkable_near(map, site);
    let (life, pace) = (common::life_of("person"), common::pace(&common::world(ctx)));
    let mut ids = Vec::new();
    if !b.family.is_empty() {
        // A family of all ages; the young are children of the first two adults.
        let mut adults: Vec<u32> = Vec::new();
        for (k, m) in b.family.iter().enumerate() {
            let p = walkable_near(map, (at.0 + (k % 4) as f32 * 0.8, at.1 + (k / 4) as f32 * 0.8));
            let f = match m.stage.as_str() {
                "elder" => ctx.rng().gen_range(life.elder + 0.01..life.old_age),
                "child" => ctx.rng().gen_range(life.infant * 1.5..life.child * 0.9),
                "infant" => ctx.rng().gen_range(0.0..life.infant * 0.6),
                _ => ctx.rng().gen_range(life.child + 0.02..0.55),
            };
            let young = matches!(m.stage.as_str(), "child" | "infant");
            let parents = if young && adults.len() >= 2 { (adults[0], adults[1]) } else { (0, 0) };
            let id = spawn_with(ctx, &fresh_name(ctx), "person", admin, true, p, now, life.age_at(f, pace), parents);
            common::inv_add(ctx, id as u64, "berries", if young { 1 } else { 3 });
            if !young {
                // Parents of the young are the family's (non-elder) adults.
                if m.stage != "elder" {
                    adults.push(id);
                }
                for tech in &b.knows {
                    common::learn(ctx, id, tech, "seed", now);
                }
            }
            let stage = ctx.db.character().id().find(id).map(|c| c.stage).unwrap_or(2);
            if stage >= 1 {
                let occ = if stage == 1 { "child".to_string() } else if m.occupation.is_empty() { "forager".to_string() } else { m.occupation.clone() };
                give_repertoire(ctx, id, &occ, now);
            }
            ids.push(id);
        }
    } else {
        let names: Vec<String> = (0..b.size).map(|_| fresh_name(ctx)).collect();
        for (k, name) in names.iter().enumerate() {
            let p = walkable_near(map, (at.0 + k as f32 * 0.8, at.1 + (k % 2) as f32));
            let id = if b.size >= 4 && k as u32 == b.size - 1 && ids.len() >= 2 {
                // Larger bands carry a child of the first two.
                spawn_with(ctx, name, "person", admin, true, p, now, life.age_at(ctx.rng().gen_range(life.infant * 2.0..life.child * 0.8), pace), (ids[0], ids[1]))
            } else {
                spawn_with(ctx, name, "person", admin, true, p, now, life.age_at(ctx.rng().gen_range(0.18f32..0.7), pace), (0, 0))
            };
            common::inv_add(ctx, id as u64, "berries", 3);
            let stage = ctx.db.character().id().find(id).map(|c| c.stage).unwrap_or(2);
            if stage >= 1 {
                give_repertoire(ctx, id, if stage == 1 { "child" } else { "forager" }, now);
            }
            if k == 0 {
                for tech in &b.knows {
                    common::learn(ctx, id, tech, "seed", now);
                }
            }
            ids.push(id);
        }
    }
    for id in &ids {
        let kin: Vec<serde_json::Value> = ids.iter().filter(|o| *o != id).map(|o| serde_json::json!({"id": o, "name": common::name_of(ctx, *o)})).collect();
        let text = serde_json::json!({"origin": "band", "band": b.name, "history": b.history, "companions": kin, "camp": [at.0.round(), at.1.round()]});
        ctx.db.background().insert(Background { id: *id, text: text.to_string() });
    }
    common::chronicle(ctx, now, "arrival", 0, 0, at, format!("{} ({} people) came to the wilds at ({:.0}, {:.0})", b.name, ids.len(), at.0, at.1));
}
