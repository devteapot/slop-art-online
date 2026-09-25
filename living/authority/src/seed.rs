//! World creation: terrain, resources, people and animals.

use crate::motion;
use crate::tables::*;
use crate::common;
use living_rules::map::{chunk_of, Terrain, CHUNKS_X, CHUNKS_Y, MAP_H, MAP_W};
use serde::Deserialize;
use spacetimedb::rand::Rng;
use spacetimedb::{Identity, ReducerContext, Table};

pub const VALLEY: &str = include_str!("../../seeds/valley.json");
pub const INSTINCTS: &str = include_str!("../../seeds/instincts.json");
pub const SKILLS: &str = include_str!("../../scripts/skills.rhai");

#[derive(Deserialize)]
pub struct Seed {
    pub run: String,
    pub seed: u64,
    pub people: Vec<SeedPerson>,
    pub animals: SeedAnimals,
}

#[derive(Deserialize)]
pub struct SeedPerson {
    pub name: String,
    pub at: [f32; 2],
}

#[derive(Deserialize)]
pub struct SeedAnimals {
    pub deer: u32,
    pub wolf: u32,
}

pub fn instinct(kind: &str) -> String {
    let all: serde_json::Value = serde_json::from_str(INSTINCTS).expect("instincts json");
    all.get(kind).or_else(|| all.get("person")).map(|v| v.to_string()).unwrap_or_default()
}

pub fn seed(ctx: &ReducerContext, now: u64) {
    let s: Seed = serde_json::from_str(VALLEY).expect("valley seed");
    let map = living_rules::map::generate(s.seed);
    for id in 0..CHUNKS_X * CHUNKS_Y {
        ctx.db.terrain_chunk().insert(TerrainChunk { id, tiles: map.chunk_bytes(id) });
    }
    common::invalidate_map();
    if let Some(mut w) = ctx.db.world().id().find(0) {
        w.run = s.run.clone();
        w.seed = s.seed;
        ctx.db.world().id().update(w);
    }
    spawn_resources(ctx, &map, now);
    let admin = common::world(ctx).admin;
    for p in &s.people {
        let at = map.nearest_walkable(p.at[0], p.at[1]).unwrap_or((48.0, 48.0));
        let id = spawn_creature(ctx, &p.name, "person", admin, true, at, now);
        common::inv_add(ctx, id as u64, "berries", 3);
        crate::perceive::request_deliberation(ctx, id, "You have just arrived in the valley and are taking in your surroundings.", now);
    }
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
    let names = common::species(kind).map(|s| s.names).unwrap_or_default();
    let used: Vec<String> = ctx.db.character().kind().filter(kind).map(|c| c.name).collect();
    let name = names
        .iter()
        .find(|n| !used.contains(n))
        .cloned()
        .unwrap_or_else(|| format!("{} {}", names.get(used.len() % names.len().max(1)).cloned().unwrap_or_else(|| kind.to_string()), used.len() / names.len().max(1) + 1));
    let admin = common::world(ctx).admin;
    spawn_creature(ctx, &name, kind, admin, true, at, now)
}

pub fn animal_spot(ctx: &ReducerContext, map: &living_rules::map::Map, kind: &str) -> Option<(f32, f32)> {
    for _ in 0..200 {
        let x = ctx.rng().gen_range(4..MAP_W as i32 - 4);
        let y = ctx.rng().gen_range(4..MAP_H as i32 - 4);
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

pub fn spawn_creature(ctx: &ReducerContext, name: &str, kind: &str, controller: Identity, ai: bool, at: (f32, f32), now: u64) -> u32 {
    spawn_with(ctx, name, kind, controller, ai, at, now, if kind == "person" { 18.0 } else { 3.0 }, (0, 0))
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
    ctx.db.brain().insert(Brain { id, graph: instinct(kind), revision: 1, plan: "instinct".into(), source: "instinct".into(), installed_ms: now });
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
    });
    if kind == "person" && parents.0 == 0 {
        common::chronicle(ctx, now, "arrival", id, 0, at, format!("{name} arrived in the valley"));
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
    let mut placed: Vec<(f32, f32)> = Vec::new();
    let place = |ctx: &ReducerContext, kind: &str, x: i32, y: i32, max: f32, spacing: f32, placed: &mut Vec<(f32, f32)>| {
        let p = (x as f32 + 0.5, y as f32 + 0.5);
        if placed.iter().any(|q| common::dist(*q, p) < spacing) {
            return;
        }
        placed.push(p);
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
    };
    let mut rng_tiles: Vec<(i32, i32)> = (0..MAP_H as i32).flat_map(|y| (0..MAP_W as i32).map(move |x| (x, y))).collect();
    // Deterministic shuffle from the reducer RNG.
    for i in (1..rng_tiles.len()).rev() {
        let j = ctx.rng().gen_range(0..=i);
        rng_tiles.swap(i, j);
    }
    let mut counts = std::collections::HashMap::<&str, u32>::new();
    for (x, y) in rng_tiles {
        let t = map.get(x, y);
        let (kind, max, spacing, cap) = match t {
            Terrain::Forest if near(x, y, Terrain::Grass, 2) => ("tree", 8.0, 2.5, 70),
            Terrain::Forest => ("tree", 8.0, 4.0, 90),
            Terrain::Grass if near(x, y, Terrain::Forest, 3) => ("berry_bush", 5.0, 3.0, 60),
            Terrain::Grass if near(x, y, Terrain::Rock, 2) => ("boulder", 6.0, 4.0, 25),
            Terrain::Sand if near(x, y, Terrain::Water, 1) => {
                if counts.get("fishing_spot").copied().unwrap_or(0) < 20 && (x + y) % 3 == 0 {
                    ("fishing_spot", 5.0, 5.0, 20)
                } else {
                    ("reeds", 4.0, 3.5, 30)
                }
            }
            Terrain::Dirt => ("boulder", 6.0, 5.0, 25),
            _ => continue,
        };
        let n = counts.entry(kind).or_insert(0);
        if *n >= cap {
            continue;
        }
        let before = placed.len();
        place(ctx, kind, x, y, max, spacing, &mut placed);
        if placed.len() > before {
            *n += 1;
        }
    }
    // Sparse berry bushes in open grassland too.
    for _ in 0..25 {
        let x = ctx.rng().gen_range(4..MAP_W as i32 - 4);
        let y = ctx.rng().gen_range(4..MAP_H as i32 - 4);
        if map.get(x, y) == Terrain::Grass {
            place(ctx, "berry_bush", x, y, 5.0, 3.0, &mut placed);
        }
    }
}
