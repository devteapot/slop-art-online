//! The first world: the generic km-scale island from `living_rules::land` (docs/FIRST_WORLD.md),
//! walkable with the game camera. Two sources build it:
//! - **look-dev** ([`Island::new`]): the client generates the land itself and places the
//!   planner's buildings and people;
//! - **connected** ([`Island::hosted`], `live.rs`): the authority hosts the land (docs/
//!   ISLAND_AUTHORITY.md). The client regenerates the same `Land` from the `land` row for heights,
//!   water, roads and walls, draws buildings from the authority's `lot` rows ([`Island::spawn_lot`])
//!   and characters from its bodies; it places none of its own.
//!
//! An environment whose JSON has a `world` section (`assets/envs/island.json`) is the island:
//! its mood lights it, and instead of a ground disc and slots, this module streams the island
//! around you in 64 m chunks:
//! - ground meshes from the island's heights and terrain, vertex-coloured and painted with the
//!   ground's detail layers (`terrain.rs`), with water surfaces at the water's level (the sea at
//!   0, lakes level, rivers sloping);
//! - each region dressed with its environment's assets at that environment's scatter
//!   densities, small things only near you: `RegionKind::env` on a temperate land, and on an arid
//!   one ([`Climate`]) the dry country's `wastes`, `scrubland` and `badlands`, with ground layers
//!   of its own (dry earth, cracked mud, gravel, sand);
//! - each settlement's wall pieces along town walls, and in look-dev a building on every lot at
//!   its levelled floor, facing its street, and people (character recipes for the settlement's
//!   folk) at house fronts and in the square.
//!
//! `LIVING_GAME_START=x,z` starts you at a point (metres) instead of the town (look-dev).
//!
//! `LIVING_GAME_SEED=<seed.json>` (look-dev) draws a seed's land instead of the environment's
//! `world`: its `seed`, `map.size` and `map.params`, as the authority builds it from that file
//! (`living/seeds/floor-megacity.json`, for example). Without it the island is the environment's
//! seed and size on the default parameters.

use crate::envs::{EnvDef, EnvPart, Occluder};
use crate::lookdev::Model;
use crate::terrain::{Blend, GroundMat, Layer};
use crate::world::{hash, rgb, scale, Palette};
use bevy::asset::RenderAssetUsages;
use bevy::mesh::{Indices, PrimitiveTopology};
use bevy::prelude::*;
use bevy::world_serialization::{WorldAsset, WorldAssetRoot};
use living_rules::land::{Land, LandParams, RegionKind, SiteKind};
use living_rules::settle::LotKind;
use living_rules::map::Terrain;
use serde::Deserialize;
use std::collections::HashMap;
use std::sync::Arc;

/// Chunk size (m), how far ground and big things stream, and how far small things do.
const CHUNK: i32 = 64;
const FAR: f32 = 170.0;
const NEAR: f32 = 60.0;
/// Things at most this tall count as small.
const SMALL: f32 = 1.6;
/// Chunk builds per frame, so walking doesn't hitch.
const BUILDS_PER_FRAME: usize = 2;
/// Things spawned per frame, in cost units: a model costs 1, a person [`PERSON_COST`]. A
/// settlement chunk holds 70 or more models; spawned at once they made the expedition's worst
/// frames (docs/FIRST_WORLD.md, "Expedition"). Queued things spawn nearest first, and only once
/// their file has loaded: the files are fetched when the chunk's ground is built, 110 m before
/// its small things are wanted, so the queue rarely waits.
const SPAWN_BUDGET: f32 = 12.0;
const PERSON_COST: f32 = 6.0;

/// An environment's `world` section.
#[derive(Deserialize, Clone, Copy, Debug)]
pub struct WorldDef {
    pub seed: u64,
    pub size: u32,
}

/// One placed thing: an asset file of a kind at a point, or a person.
#[derive(Clone, Default)]
struct Item {
    kind: String,
    file: String,
    at: Vec2,
    yaw: f32,
    /// Height for streaming tiers, occlusion and lights; the model keeps its own size if `native`.
    height: f32,
    glow: Option<[f32; 3]>,
    k: usize,
    /// Where the model's origin stands (a lot's levelled floor), else the ground.
    floor: Option<f32>,
    native: bool,
    /// A person: recipe seed, folk and style preset (`characters::Recipe::random_in`).
    person: Option<(u64, &'static str, String)>,
}

/// How a land's open country is drawn: the temperate island's meadows and forests, or dry
/// country (dry earth, cracked mud, gravel and sand; dry grass, scrub, dead trees, rocks and
/// rubble), each by the region kinds the generator emits.
///
/// Seeds don't name a look per region yet (`KindLook` has no environment field; that is the
/// rules' data, see docs/FLOORS.md), so the client reads it from the land's parameters: a land
/// whose rivers run dry (`water.dry_rivers`, the megacity floor's wastes) is arid.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Climate {
    #[default]
    Temperate,
    Arid,
}

impl Climate {
    pub fn of(params: &LandParams) -> Self {
        if params.water.dry_rivers {
            Self::Arid
        } else {
            Self::Temperate
        }
    }

    /// The environment (`assets/envs/<id>.json`) whose scatter dresses a region kind.
    pub fn env(self, kind: RegionKind) -> Option<&'static str> {
        match self {
            Self::Temperate => kind.env(),
            Self::Arid => match kind {
                RegionKind::Sea => None,
                RegionKind::Meadow | RegionKind::Beach | RegionKind::Wetland => Some("wastes"),
                RegionKind::Forest | RegionKind::OldForest | RegionKind::SpiritGrove => Some("scrubland"),
                RegionKind::Highland | RegionKind::Peaks => Some("badlands"),
            },
        }
    }
}

#[derive(Resource)]
pub struct Island {
    pub land: Arc<Land>,
    pub climate: Climate,
    /// Environments by id, for region and site dressing.
    envs: HashMap<String, EnvDef>,
    /// Settlement things, by chunk.
    site_items: HashMap<(i32, i32), Vec<Item>>,
    /// Loaded chunks: ground (with water) and big things; small things separately.
    ground: HashMap<(i32, i32), Vec<Entity>>,
    small: HashMap<(i32, i32), Vec<Entity>>,
    /// Things waiting to spawn, by chunk and tier ([`SPAWN_BUDGET`]).
    queue: Vec<Queued>,
    /// The files of a loaded chunk's small things and people, held from its ground's build.
    prefetch: HashMap<(i32, i32), Vec<UntypedHandle>>,
    pub start: Vec2,
    /// Every chunk in reach has its ground and things, and nothing waits to spawn.
    settled: bool,
    /// Flights of stairs, by 16 m cell, for where feet stand ([`Island::foot_height`]).
    flights: HashMap<(i32, i32), Vec<Flight>>,
}

/// A flight of stairs as `buildings.py`'s `prop_stairs` makes it: [`TREADS`] treads rising
/// [`RISE`] m over [`RUN`] m from its front (down the stairs, at the lower terrace's floor) to its
/// back, [`TREAD_W`] m wide.
#[derive(Clone, Copy)]
struct Flight {
    centre: Vec2,
    down: Vec2,
    floor: f32,
}

const TREADS: f32 = 17.0;
const RISE: f32 = 3.0;
const RUN: f32 = 5.0;
const TREAD_W: f32 = 2.4;
const FLIGHT_CELL: f32 = 16.0;

impl Flight {
    /// The tread top under a point, if it is on this flight.
    fn tread(&self, p: Vec2) -> Option<f32> {
        let d = p - self.centre;
        let side = Vec2::new(-self.down.y, self.down.x);
        // From the front edge (u = 0) up to the back (u = RUN).
        let u = RUN * 0.5 - d.dot(self.down);
        (d.dot(side).abs() <= TREAD_W * 0.5 && (0.0..RUN).contains(&u)).then(|| self.floor + ((u * TREADS / RUN).floor() + 1.0) * RISE / TREADS)
    }
}

/// A thing waiting to spawn into a chunk's ground tier or its small tier.
struct Queued {
    chunk: (i32, i32),
    small: bool,
    item: Item,
    /// Its scene file, which must have loaded first.
    scene: Handle<WorldAsset>,
}

impl Island {
    /// Look-dev: generate the land (seconds of work: run it off the main thread, as connected
    /// mode does, so no frame waits for it): `LIVING_GAME_SEED`'s land if set and readable, else
    /// the environment's `world` on the default parameters.
    pub fn generate(world: WorldDef) -> Generated {
        let t0 = std::time::Instant::now();
        let (seed, size, params, from) = match std::env::var("LIVING_GAME_SEED").ok().filter(|p| !p.is_empty()) {
            Some(path) => match seed_land(&path) {
                Ok((seed, size, params)) => (seed, size, params, path),
                Err(e) => {
                    error!("island: LIVING_GAME_SEED={path}: {e}; drawing the environment's world instead");
                    (world.seed, world.size, LandParams::default(), "the environment (default parameters)".into())
                }
            },
            None => (world.seed, world.size, LandParams::default(), "the environment (default parameters)".into()),
        };
        let land = Arc::new(living_rules::land::generate(seed, size, &params));
        Generated { land, secs: t0.elapsed().as_secs_f32(), params, from }
    }

    /// Look-dev: place the planner's buildings and people on a generated land.
    pub fn new(generated: Generated, defs: &[EnvDef]) -> Self {
        let Generated { land, secs: generated_s, params, from } = generated;
        let t0 = std::time::Instant::now();
        let world = WorldDef { seed: land.seed, size: land.size };
        let town = land.settlements.iter().find(|s| s.kind == SiteKind::Town).map(|s| Vec2::new(s.plaza.centre.0, s.plaza.centre.1)).or_else(|| land.sites.iter().find(|s| s.kind == SiteKind::Town).map(|s| Vec2::new(s.x, s.y)));
        let start = std::env::var("LIVING_GAME_START")
            .ok()
            .and_then(|s| {
                let (x, z) = s.split_once(',')?;
                Some(Vec2::new(x.trim().parse().ok()?, z.trim().parse().ok()?))
            })
            .or(town)
            .unwrap_or(Vec2::splat(world.size as f32 / 2.0));
        let island = Self::build(land, defs, start, true, &params);
        info!(
            "island: seed {} {} m from {from} ({:?}): land in {generated_s:.2} s (worker thread), placed in {:.3} s; {} regions, {} sites, start ({:.0}, {:.0})",
            world.seed,
            world.size,
            island.climate,
            t0.elapsed().as_secs_f32(),
            island.land.regions.len(),
            island.land.sites.len(),
            start.x,
            start.y
        );
        island
    }

    /// Connected: the land the authority hosts, regenerated from its `land` row. Buildings come
    /// from `lot` rows ([`Island::spawn_lot`]) and people from bodies, so none are planned here.
    pub fn hosted(land: Arc<Land>, defs: &[EnvDef], arrive: Vec2, params: &LandParams) -> Self {
        Self::build(land, defs, arrive, false, params)
    }

    fn build(land: Arc<Land>, defs: &[EnvDef], start: Vec2, planned: bool, params: &LandParams) -> Self {
        let climate = Climate::of(params);
        let world = WorldDef { seed: land.seed, size: land.size };
        let envs: HashMap<String, EnvDef> = defs.iter().map(|d| (d.id.clone(), d.clone())).collect();
        let mut site_items: HashMap<(i32, i32), Vec<Item>> = HashMap::new();
        let mut put = |it: Item| site_items.entry(chunk_of(it.at)).or_default().push(it);
        let pick = |files: &[String], n: usize, salt: u32| files[(hash(n as u32, salt) * files.len() as f32) as usize % files.len()].clone();
        // Buildings on the planner's lots.
        for (li, lot) in land.lots.iter().enumerate().filter(|_| planned) {
            let st = &land.settlements[lot.settlement as usize];
            let Some(kind) = lot.kind.model() else { continue };
            // By style (a steampunk town is steampunk_city), and the kind folder its model is in.
            let env = living_rules::settle::env_of(&st.style);
            let kind = lot.model_file.as_deref().and_then(living_rules::settle::asset_kind).unwrap_or(kind);
            let files = crate::envs::assets_for(env, kind);
            if files.is_empty() {
                continue;
            }
            let slot = envs.get(env).and_then(|d| d.slots.iter().find(|s| s.kind == kind));
            // The exact model the planner sized the lot for, when it is on disk.
            let exact = lot.model_file.as_ref().map(|f| format!("envs/{f}")).filter(|f| files.contains(f));
            let height = if exact.is_some() { lot.height_m } else { slot.map_or(6.0, |s| s.height[1]) };
            put(Item {
                kind: kind.to_string(),
                file: exact.unwrap_or_else(|| pick(&files, li, 11)),
                at: Vec2::new(lot.centre.0, lot.centre.1),
                yaw: lot.yaw,
                height,
                glow: slot.and_then(|s| s.glow),
                k: li,
                floor: Some(lot.floor_m),
                native: true,
                person: None,
            });
        }
        // Street props, stairs and retaining walls: derived from the layout on both sides, not
        // stored by the authority, so connected mode places them too.
        for (pi, pr) in land.props.iter().enumerate() {
            let env = living_rules::settle::env_of(&land.settlements[pr.settlement as usize].style);
            let files = crate::envs::assets_for(env, pr.kind.id());
            let exact = pr.model_file.as_ref().map(|f| format!("envs/{f}")).filter(|f| files.contains(f));
            let Some(file) = exact.or_else(|| (!files.is_empty()).then(|| pick(&files, pi, 17))) else { continue };
            put(Item { kind: pr.kind.id().to_string(), file, at: Vec2::new(pr.centre.0, pr.centre.1), yaw: pr.yaw, height: pr.height_m, k: pi, floor: Some(pr.floor_m), native: true, ..default() });
        }
        for (si, st) in land.settlements.iter().enumerate() {
            let env = living_rules::settle::env_of(&st.style);
            // Wall pieces along town walls.
            if let Some(wall) = &st.wall {
                let files = crate::envs::assets_for(env, "wall");
                if !files.is_empty() {
                    for (k, piece) in wall.pieces(5.0, st.centre).iter().enumerate() {
                        let at = Vec2::new(piece.centre.0, piece.centre.1);
                        put(Item { kind: "wall".into(), file: pick(&files, k, 13 + si as u32), at, yaw: piece.yaw, height: wall.height_m, k, native: true, ..default() });
                    }
                }
            }
            if !planned {
                continue;
            }
            // People: at house fronts, and some in the square.
            let folk = match st.kind {
                SiteKind::Giants => "giant",
                SiteKind::SmallFolk => "small",
                SiteKind::Cave => continue,
                _ => "adult",
            };
            let mut n = 0u32;
            // Up to 16 at house fronts (about 60% of houses) and 8 in the square, twice the first
            // cap. Characters share materials and batch, so crowds cost little on the development
            // Mac: this cap adds about 0.5 ms over the old one, and 3× it about 2 ms (performance
            // pass 2, docs/GAME_BRIEF.md).
            // `LIVING_GAME_PERF=people=K` multiplies it (measurement only).
            let crowd = crate::perf::value("people").unwrap_or(1.0);
            for li in st.lots.0..st.lots.1 {
                let lot = &land.lots[li as usize];
                if !matches!(lot.kind.id(), "house" | "townhouse") || hash(li, 20) > (0.6 * crowd).min(1.0) || n >= (16.0 * crowd) as u32 {
                    continue;
                }
                let (f, side) = (Vec2::new(lot.front.0, lot.front.1), Vec2::new(-lot.front.1, lot.front.0));
                let at = Vec2::new(lot.centre.0, lot.centre.1) + f * (lot.depth_m * 0.5 + 1.2 * st.scale) + side * (hash(li, 21) - 0.5) * lot.width_m * 0.6;
                put(Item { kind: "person".into(), at, yaw: hash(li, 22) * std::f32::consts::TAU, k: n as usize, person: Some((world.seed * 7919 + li as u64, folk, st.style.clone())), ..default() });
                n += 1;
            }
            let plaza = Vec2::new(st.plaza.centre.0, st.plaza.centre.1);
            for k in 0..(8.0 * crowd) as u32 {
                let a = hash(si as u32 * 97 + k, 31) * std::f32::consts::TAU;
                let at = plaza + Vec2::new(a.cos(), a.sin()) * (2.0 + 6.0 * hash(si as u32 * 97 + k, 32)) * st.scale;
                put(Item { kind: "person".into(), at, yaw: hash(k, 33) * std::f32::consts::TAU, k: k as usize, person: Some((world.seed * 104_729 + (si as u64) * 31 + k as u64, folk, st.style.clone())), ..default() });
            }
        }
        let mut flights: HashMap<(i32, i32), Vec<Flight>> = HashMap::new();
        for pr in land.props.iter().filter(|p| p.kind == living_rules::settle::PropKind::Stairs) {
            let f = Flight { centre: Vec2::new(pr.centre.0, pr.centre.1), down: Vec2::new(pr.front.0, pr.front.1).normalize_or(Vec2::X), floor: pr.floor_m };
            // Every cell the flight's footprint touches.
            let r = RUN.max(TREAD_W) * 0.5 + 0.5;
            let (lo, hi) = ((f.centre - r) / FLIGHT_CELL, (f.centre + r) / FLIGHT_CELL);
            for cx in lo.x.floor() as i32..=hi.x.floor() as i32 {
                for cz in lo.y.floor() as i32..=hi.y.floor() as i32 {
                    flights.entry((cx, cz)).or_default().push(f);
                }
            }
        }
        Self { land, climate, envs, site_items, ground: HashMap::new(), small: HashMap::new(), queue: Vec::new(), prefetch: HashMap::new(), start, settled: false, flights }
    }

    /// A building on an authority `lot` row (connected): the row's model file when it is on
    /// disk, else one of its kind from the settlement's environment. The model's origin stands
    /// on the lot's floor, facing its yaw. Returns the entities to despawn with it.
    pub fn spawn_lot(&self, commands: &mut Commands, assets: &AssetServer, lot: &LotRow) -> Vec<Entity> {
        let Some(kind) = lot.kind.model() else { return Vec::new() };
        // The row's model names its folder (`steampunk_city/clocktower/...`): a town in its own
        // style uses its own assets.
        let env = lot.model.split('/').next().filter(|_| !lot.model.is_empty()).unwrap_or(lot.site.env());
        let kind = living_rules::settle::asset_kind(&lot.model).unwrap_or(kind);
        let files = crate::envs::assets_for(env, kind);
        let exact = Some(format!("envs/{}", lot.model)).filter(|f| !lot.model.is_empty() && files.contains(f));
        if exact.is_none() && files.is_empty() {
            return Vec::new();
        }
        if exact.is_none() && !lot.model.is_empty() {
            warn!("lot {}: model {} is not on disk; using another {kind}", lot.id, lot.model);
        }
        let slot = self.envs.get(env).and_then(|d| d.slots.iter().find(|s| s.kind == kind));
        let height = if exact.is_some() { lot.height_m } else { slot.map_or(6.0, |s| s.height[1]) };
        let file = exact.unwrap_or_else(|| files[(hash(lot.id, 11) * files.len() as f32) as usize % files.len()].clone());
        let it = Item { kind: kind.to_string(), file, at: lot.at, yaw: lot.yaw, height, glow: slot.and_then(|s| s.glow), k: lot.id as usize, floor: Some(lot.floor_m), native: true, person: None };
        spawn_item(commands, assets, &self.land, &it)
    }

    /// Whether everything in reach is in: ground and things, nothing queued (`loading.rs`).
    pub fn settled(&self) -> bool {
        self.settled
    }

    /// Height of the ground (game x, z).
    pub fn height(&self, x: f32, z: f32) -> f32 {
        self.land.height(x, z)
    }

    /// Where a foot stands (game x, z): the ground, or on a flight of stairs the tread over it
    /// (the ground there is the flight's ramp, which meets each tread only at its back edge).
    pub fn foot_height(&self, x: f32, z: f32) -> f32 {
        let cell = ((x / FLIGHT_CELL).floor() as i32, (z / FLIGHT_CELL).floor() as i32);
        let p = Vec2::new(x, z);
        self.flights.get(&cell).and_then(|fs| fs.iter().find_map(|f| f.tread(p))).unwrap_or_else(|| self.height(x, z))
    }

    /// Whether you can stand at a point.
    pub fn walkable(&self, x: f32, z: f32) -> bool {
        let s = self.land.size as f32;
        x > 0.5 && z > 0.5 && x < s - 0.5 && z < s - 0.5 && self.land.map.at(x, z).walkable()
    }

    /// Inside a settlement (no wild scatter there).
    fn in_site(&self, p: Vec2) -> bool {
        self.land.sites.iter().any(|s| s.kind != SiteKind::Cave && p.distance(Vec2::new(s.x, s.y)) < s.radius_m * 1.05)
    }

    /// Wild things for a chunk: every scatter slot of every region environment, at its density,
    /// kept where the region there uses that environment.
    fn wild_items(&self, c: (i32, i32)) -> Vec<Item> {
        let mut out = Vec::new();
        let origin = Vec2::new((c.0 * CHUNK) as f32, (c.1 * CHUNK) as f32);
        let area = (CHUNK * CHUNK) as f32;
        let mut ids: Vec<&str> = RegionKind::ALL.iter().filter_map(|k| self.climate.env(*k)).collect();
        ids.sort();
        ids.dedup();
        for (ei, id) in ids.iter().enumerate() {
            let Some(def) = self.envs.get(*id) else { continue };
            let disc = std::f32::consts::PI * def.ground.radius.max(10.0).powi(2);
            for (si, slot) in def.slots.iter().enumerate() {
                if slot.rule == "grid" || slot.rule == "ring" || slot.kind == "person" {
                    continue;
                }
                let files = crate::envs::assets_for(id, &slot.kind);
                if files.is_empty() {
                    continue;
                }
                let r = if slot.radius > 0.0 { slot.radius } else { def.ground.radius };
                let density = slot.count as f32 / (std::f32::consts::PI * r * r).min(disc).max(1.0);
                let n = density * area;
                let whole = n.floor() as u32 + u32::from(hash(c.0 as u32 ^ 0x9e37, (c.1 as u32).wrapping_mul(31) ^ (ei * 97 + si) as u32) < n.fract());
                for k in 0..whole {
                    let seed = (c.0 as u32).wrapping_mul(73_856_093) ^ (c.1 as u32).wrapping_mul(19_349_663) ^ ((ei * 131 + si) as u32) << 20;
                    let at = origin + Vec2::new(hash(seed, k * 3 + 1), hash(seed, k * 3 + 2)) * CHUNK as f32;
                    let kind = self.land.kind_at(at.x, at.y);
                    let tile = self.land.map.at(at.x, at.y);
                    if self.climate.env(kind) != Some(*id) || !tile.walkable() || tile == Terrain::Road || self.in_site(at) {
                        continue;
                    }
                    // Sparser where the region is not the environment's own kind.
                    let keep = match kind {
                        RegionKind::Beach => 0.15,
                        RegionKind::Peaks => 0.12,
                        RegionKind::Highland => 0.45,
                        RegionKind::Wetland => 0.6,
                        _ => 1.0,
                    };
                    // Tall things gather into stands with glades between (a slow density field);
                    // ground cover stays everywhere.
                    let tall = slot.height[1] > 4.0;
                    let stand = if tall { (grove(self.land.seed, at) * 1.9).clamp(0.0, 1.7) } else { 1.0 };
                    if hash(seed ^ 0xabc, k) > keep * stand {
                        continue;
                    }
                    let height = slot.height[0] + (slot.height[1] - slot.height[0]) * hash(seed ^ 0x51, k);
                    let file = files[(hash(seed ^ 0x77, k) * files.len() as f32) as usize % files.len()].clone();
                    out.push(Item { kind: slot.kind.clone(), file, at, yaw: hash(seed ^ 0x33, k) * std::f32::consts::TAU, height, glow: slot.glow, k: k as usize, ..default() });
                }
            }
        }
        out
    }
}

/// A look-dev land from its worker thread ([`Island::generate`]): the land, its seconds, the
/// parameters it was made with and where they came from.
pub struct Generated {
    pub land: Arc<Land>,
    pub secs: f32,
    pub params: LandParams,
    pub from: String,
}

/// A seed file's land: its `seed`, `map.size` and `map.params` (the authority reads the same
/// fields; a seed without `map.params` uses the defaults).
fn seed_land(path: &str) -> Result<(u64, u32, LandParams), String> {
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let v: serde_json::Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let map = &v["map"];
    if map["kind"].as_str().is_some_and(|k| k != "land") {
        return Err(format!("map.kind is {}, not land", map["kind"]));
    }
    let seed = v["seed"].as_u64().ok_or("no seed")?;
    let size = map["size"].as_u64().ok_or("no map.size")? as u32;
    if !(256..=8192).contains(&size) {
        return Err(format!("map.size {size} m"));
    }
    let params = match map.get("params") {
        Some(p) if !p.is_null() => serde_json::from_value(p.clone()).map_err(|e| format!("map.params: {e}"))?,
        _ => LandParams::default(),
    };
    Ok((seed, size, params))
}

/// What the client draws of an authority `lot` row (connected mode).
#[derive(Clone, Debug)]
pub struct LotRow {
    pub id: u32,
    /// The settlement's kind (its environment's assets).
    pub site: SiteKind,
    pub kind: LotKind,
    pub at: Vec2,
    pub yaw: f32,
    pub floor_m: f32,
    pub height_m: f32,
    /// Path under `assets/envs/`, empty when the planner had no exact model.
    pub model: String,
}

/// A settlement kind from its id (`settlement.kind`).
pub fn site_kind(id: &str) -> Option<SiteKind> {
    [SiteKind::Town, SiteKind::Village, SiteKind::Giants, SiteKind::SmallFolk, SiteKind::Cave].into_iter().find(|k| k.id() == id)
}

/// Smooth value noise in 0..1 over about `scale` metres.
fn noise(seed: u32, p: Vec2, scale: f32) -> f32 {
    let q = p / scale;
    let (i, f) = (q.floor(), q.fract());
    let s = f * f * (Vec2::splat(3.0) - 2.0 * f);
    let h = |x: f32, y: f32| hash((x as i32 as u32).wrapping_add(seed), (y as i32 as u32).wrapping_mul(7919).wrapping_add(seed));
    let a = h(i.x, i.y) + (h(i.x + 1.0, i.y) - h(i.x, i.y)) * s.x;
    let b = h(i.x, i.y + 1.0) + (h(i.x + 1.0, i.y + 1.0) - h(i.x, i.y + 1.0)) * s.x;
    a + (b - a) * s.y
}

/// How strongly tall things gather here: dense stands (above 0.6) and open glades (near 0).
fn grove(seed: u64, p: Vec2) -> f32 {
    let n = 0.65 * noise(seed as u32 ^ 0x6a09, p, 70.0) + 0.35 * noise(seed as u32 ^ 0xbb67, p, 23.0);
    ((n - 0.32) / 0.4).clamp(0.0, 1.0).powf(1.3)
}

fn chunk_of(p: Vec2) -> (i32, i32) {
    ((p.x / CHUNK as f32).floor() as i32, (p.y / CHUNK as f32).floor() as i32)
}

fn chunk_distance(c: (i32, i32), p: Vec2) -> f32 {
    let lo = Vec2::new((c.0 * CHUNK) as f32, (c.1 * CHUNK) as f32);
    let hi = lo + Vec2::splat(CHUNK as f32);
    p.clamp(lo, hi).distance(p)
}

/// Ground colour from the terrain class and the region.
fn ground_colour(t: Terrain, kind: RegionKind, v: f32, climate: Climate) -> [f32; 4] {
    if climate == Climate::Arid {
        return scale(arid_colour(t, kind), 0.94 + 0.12 * v);
    }
    let base = match t {
        Terrain::Water => rgb(70, 92, 96),
        Terrain::Sand => rgb(214, 196, 146),
        Terrain::Rock => rgb(128, 122, 116),
        Terrain::Dirt => rgb(132, 112, 80),
        Terrain::Road => rgb(178, 160, 120),
        Terrain::Wall => rgb(110, 100, 90),
        Terrain::Forest => match kind {
            RegionKind::SpiritGrove => rgb(40, 70, 80),
            RegionKind::OldForest => rgb(62, 98, 56),
            _ => rgb(80, 118, 62),
        },
        Terrain::Grass => match kind {
            RegionKind::SpiritGrove => rgb(52, 92, 100),
            RegionKind::Wetland => rgb(96, 132, 84),
            RegionKind::Highland => rgb(132, 140, 92),
            RegionKind::Peaks => rgb(140, 138, 120),
            RegionKind::Beach => rgb(170, 176, 112),
            _ => rgb(112, 160, 74),
        },
    };
    scale(base, 0.94 + 0.12 * v)
}

/// Dry country's ground colours: straw and ochre plains, olive-brown scrub, warm stone, pale
/// sand in the dry riverbeds and a salt-pale pan where the land would be wet.
fn arid_colour(t: Terrain, kind: RegionKind) -> [f32; 4] {
    match t {
        Terrain::Water => rgb(70, 92, 96),
        Terrain::Sand => rgb(212, 194, 152),
        Terrain::Rock => rgb(148, 130, 114),
        Terrain::Dirt => rgb(164, 140, 108),
        Terrain::Road => rgb(168, 152, 124),
        Terrain::Wall => rgb(110, 100, 90),
        Terrain::Forest => rgb(130, 124, 92),
        Terrain::Grass => match kind {
            RegionKind::Forest | RegionKind::OldForest | RegionKind::SpiritGrove => rgb(156, 146, 108),
            RegionKind::Highland => rgb(162, 142, 116),
            RegionKind::Peaks => rgb(156, 138, 120),
            RegionKind::Beach => rgb(204, 188, 148),
            RegionKind::Wetland => rgb(196, 186, 162),
            _ => rgb(178, 160, 120),
        },
    }
}

/// Dry country's painted detail by terrain class and region, mirroring [`arid_colour`].
fn arid_layers(t: Terrain, kind: RegionKind) -> [(Layer, f32); 2] {
    let one = |l: Layer| [(l, 1.0), (l, 0.0)];
    match t {
        // An oasis's bed is mud; the sea's floor and shallows are sand.
        Terrain::Water => one(if matches!(kind, RegionKind::Sea | RegionKind::Beach) { Layer::Sand } else { Layer::Mud }),
        Terrain::Sand => one(Layer::Sand),
        Terrain::Rock | Terrain::Wall => one(Layer::Rock),
        Terrain::Dirt => match kind {
            RegionKind::Highland | RegionKind::Peaks => one(Layer::Gravel),
            RegionKind::Wetland | RegionKind::Beach => one(Layer::CrackedMud),
            _ => [(Layer::CrackedMud, 0.55), (Layer::DryEarth, 0.45)],
        },
        Terrain::Road => one(Layer::Gravel),
        // Scrub thickets: dry grass over bare earth.
        Terrain::Forest => [(Layer::DryGrass, 0.5), (Layer::DryEarth, 0.5)],
        Terrain::Grass => match kind {
            RegionKind::Forest | RegionKind::OldForest | RegionKind::SpiritGrove => [(Layer::DryGrass, 0.7), (Layer::DryEarth, 0.3)],
            RegionKind::Highland => [(Layer::Gravel, 0.5), (Layer::DryEarth, 0.5)],
            RegionKind::Peaks => [(Layer::Gravel, 0.6), (Layer::Rock, 0.4)],
            RegionKind::Beach => [(Layer::Sand, 0.7), (Layer::DryEarth, 0.3)],
            RegionKind::Wetland => [(Layer::CrackedMud, 0.7), (Layer::DryEarth, 0.3)],
            _ => [(Layer::DryEarth, 0.55), (Layer::DryGrass, 0.45)],
        },
    }
}

/// The ground's painted detail (`terrain.rs`) by terrain class and region, mirroring
/// [`ground_colour`]: up to two layers and their shares. Roads are [`road_layer`].
fn ground_layers(t: Terrain, kind: RegionKind, climate: Climate) -> [(Layer, f32); 2] {
    if climate == Climate::Arid {
        return arid_layers(t, kind);
    }
    let one = |l: Layer| [(l, 1.0), (l, 0.0)];
    match t {
        // Lake and river beds are mud; the sea's floor and shallows are sand.
        Terrain::Water => one(if matches!(kind, RegionKind::Sea | RegionKind::Beach) { Layer::Sand } else { Layer::Mud }),
        Terrain::Sand => one(Layer::Sand),
        Terrain::Rock | Terrain::Wall => one(Layer::Rock),
        Terrain::Dirt => one(Layer::Dirt),
        Terrain::Road => one(Layer::Cobble),
        Terrain::Forest => one(if kind == RegionKind::SpiritGrove { Layer::SpiritMoss } else { Layer::ForestFloor }),
        Terrain::Grass => match kind {
            RegionKind::SpiritGrove => one(Layer::SpiritMoss),
            RegionKind::Wetland => [(Layer::LushGrass, 0.6), (Layer::Mud, 0.4)],
            RegionKind::Forest | RegionKind::OldForest => one(Layer::LushGrass),
            RegionKind::Highland | RegionKind::Peaks | RegionKind::Beach => one(Layer::DryGrass),
            _ => one(Layer::Grass),
        },
    }
}

/// A road's surface, by the settlement's style (zones differ by their contents): a steampunk
/// town is all setts, a cyberpunk town's and the megacity's paved wards' streets and squares
/// are large panels, its slums' lanes earth, the wastes' camps, outposts and ruins gravel, and
/// elsewhere a paved square is flagstones and streets are cobbled. Between settlements, a packed
/// earth track (gravel in dry country).
fn road_layer(land: &Land, x: f32, z: f32, climate: Climate) -> Layer {
    let earth = if climate == Climate::Arid { Layer::DryEarth } else { Layer::Dirt };
    for st in &land.settlements {
        let (dx, dz) = (x - st.centre.0, z - st.centre.1);
        if dx * dx + dz * dz > (st.radius_m * 1.15).powi(2) {
            continue;
        }
        return match st.style.as_str() {
            "steampunk" => Layer::Cobble,
            "cyberpunk" | "metro" | "works" => Layer::Pavers,
            "slum" => earth,
            "outpost" | "salvage" | "ruin" => Layer::Gravel,
            _ if st.plaza.paved && st.in_plaza((x, z)) => Layer::Flagstone,
            _ => Layer::Cobble,
        };
    }
    if climate == Climate::Arid {
        Layer::Gravel
    } else {
        Layer::Dirt
    }
}

/// Ground colour and detail layers averaged over a few metres, so region borders and single
/// tiles blend instead of switching along straight polygon edges.
fn blended_ground(land: &Land, x: f32, z: f32, v: f32, climate: Climate) -> ([f32; 4], Blend) {
    // Roads and paved squares stay crisp, and don't bleed into the blend around them.
    let here = land.map.at(x + 0.01, z + 0.01);
    if here == Terrain::Road {
        return (ground_colour(here, land.kind_at(x, z), v, climate), Blend::one(road_layer(land, x, z, climate)));
    }
    const RING: [(f32, f32); 9] = [(0.0, 0.0), (6.0, 0.0), (-6.0, 0.0), (0.0, 6.0), (0.0, -6.0), (13.0, 9.0), (-13.0, -9.0), (9.0, -13.0), (-9.0, 13.0)];
    let mut acc = [0.0f32; 4];
    let mut blend = Blend::default();
    for (k, (dx, dz)) in RING.iter().enumerate() {
        // The centre sample counts most; the ring spreads the change over about 25 m.
        let w = if k == 0 { 3.0 } else { 1.0 };
        let (px, pz) = (x + dx, z + dz);
        let t = match land.map.at(px + 0.01, pz + 0.01) {
            Terrain::Road => Terrain::Grass,
            t => t,
        };
        let kind = land.kind_at(px, pz);
        let c = ground_colour(t, kind, v, climate);
        for i in 0..4 {
            acc[i] += c[i] * w;
        }
        for (layer, share) in ground_layers(t, kind, climate) {
            blend.add(layer, share * w);
        }
    }
    (acc.map(|c| c / 11.0), blend)
}

/// A chunk's ground (indexed 1 m grid, smooth normals) and its water surface.
fn chunk_meshes(land: &Land, c: (i32, i32), climate: Climate) -> (Mesh, Option<Mesh>) {
    let n = CHUNK as usize;
    let (x0, z0) = (c.0 * CHUNK, c.1 * CHUNK);
    let mut pos = Vec::with_capacity((n + 1) * (n + 1));
    let mut col = Vec::with_capacity((n + 1) * (n + 1));
    let mut blends = Vec::with_capacity((n + 1) * (n + 1));
    for j in 0..=n {
        for i in 0..=n {
            let (x, z) = ((x0 + i as i32) as f32, (z0 + j as i32) as f32);
            pos.push([x, land.height(x, z), z]);
            let v = hash((x0 + i as i32) as u32, (z0 + j as i32) as u32);
            let (mut c, b) = blended_ground(land, x, z, v, climate);
            // The rules' blocking rock, crisp per tile (not blended): the share of the four tiles
            // round this vertex, for the shader's cliff (terrain.rs `BLOCKED_ALPHA`).
            let rock = [(-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5)].iter().filter(|(dx, dz)| land.map.at(x + dx, z + dz) == Terrain::Rock).count();
            c[3] = 1.0 - (1.0 - crate::terrain::BLOCKED_ALPHA) * rock as f32 / 4.0;
            col.push(c);
            blends.push(b);
        }
    }
    let mut idx = Vec::with_capacity(n * n * 6);
    for j in 0..n {
        for i in 0..n {
            let a = (j * (n + 1) + i) as u32;
            let (b, cc, d) = (a + 1, a + (n + 1) as u32, a + (n + 2) as u32);
            idx.extend_from_slice(&[a, cc, b, b, cc, d]);
        }
    }
    let mut ground = Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::default())
        .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, pos)
        .with_inserted_attribute(Mesh::ATTRIBUTE_COLOR, col)
        .with_inserted_indices(Indices::U32(idx));
    ground.compute_smooth_normals();
    crate::terrain::insert_blend(&mut ground, &blends);
    // Water: a quad per metre on water tiles and the tiles touching them (so banks meet it),
    // at the water's level. The level alone is not enough: the nearest water's surface can stand
    // above dry ground well away from it.
    let mut wpos: Vec<[f32; 3]> = Vec::new();
    let mut widx: Vec<u32> = Vec::new();
    for j in 0..n {
        for i in 0..n {
            let (x, z) = ((x0 + i as i32) as f32, (z0 + j as i32) as f32);
            let corners = [(x, z), (x + 1.0, z), (x, z + 1.0), (x + 1.0, z + 1.0)];
            let water = |dx: f32, dz: f32| land.map.at(x + 0.5 + dx, z + 0.5 + dz) == Terrain::Water;
            let wet = water(0.0, 0.0) || water(1.0, 0.0) || water(-1.0, 0.0) || water(0.0, 1.0) || water(0.0, -1.0);
            if !wet {
                continue;
            }
            let b = wpos.len() as u32;
            for (cx, cz) in corners {
                wpos.push([cx, land.water_level(cx, cz) - 0.05, cz]);
            }
            widx.extend_from_slice(&[b, b + 2, b + 1, b + 1, b + 2, b + 3]);
        }
    }
    let water = (!wpos.is_empty()).then(|| {
        let count = wpos.len();
        Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::default())
            .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, wpos)
            .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, vec![[0.0, 1.0, 0.0]; count])
            .with_inserted_indices(Indices::U32(widx))
    });
    (ground, water)
}

/// The scene file a thing spawns from (a person's: its recipe's animated base).
fn scene_of(assets: &AssetServer, it: &Item) -> Handle<WorldAsset> {
    let file = match &it.person {
        Some((seed, folk, style)) => crate::lookdev::animated(&crate::characters::Recipe::random_in(*seed, folk, style).base),
        None => it.file.clone(),
    };
    assets.load(GltfAssetLabel::Scene(0).from_asset(file))
}

/// Whether a thing's scene can spawn now: loaded with its dependencies, or failed (it then spawns
/// as it always did, and logs its error).
fn ready(assets: &AssetServer, scene: &Handle<WorldAsset>) -> bool {
    use bevy::asset::RecursiveDependencyLoadState as S;
    matches!(assets.recursive_dependency_load_state(scene), S::Loaded | S::Failed(_))
}

fn spawn_item(commands: &mut Commands, assets: &AssetServer, land: &Land, it: &Item) -> Vec<Entity> {
    let y = it.floor.unwrap_or_else(|| land.height(it.at.x, it.at.y));
    let at = Vec3::new(it.at.x, y, it.at.y);
    if let Some((seed, folk, style)) = &it.person {
        // Settlements dress their people in their style (fantasy where it has no preset).
        let recipe = crate::characters::Recipe::random_in(*seed, folk, style);
        let e = crate::characters::spawn(commands, assets, &recipe, at, it.yaw);
        commands.entity(e).insert(EnvPart);
        return vec![e];
    }
    let vrm = it.file.contains("vroid-");
    let model = Model { vrm, file: it.file.clone(), height: if it.native { 0.0 } else { it.height }, ground_y: y, glow: it.glow };
    let handle = assets.load(GltfAssetLabel::Scene(0).from_asset(it.file.clone()));
    let mut e = commands.spawn((EnvPart, model, WorldAssetRoot(handle), Transform::from_translation(at).with_rotation(Quat::from_rotation_y(it.yaw)), Visibility::Hidden));
    if it.height >= 3.0 {
        e.insert(Occluder { height: it.height });
    }
    if it.height <= SMALL {
        e.insert(crate::lookdev::NoShadow);
    }
    let mut out = vec![e.id()];
    if let Some((light, tf)) = crate::envs::local_light(&it.kind, it.glow, it.height, it.k) {
        out.push(commands.spawn((EnvPart, light, Transform::from_translation(at + tf.translation))).id());
    }
    out
}

/// Every 2 s: frame times (mean and worst), what is loaded, and where you are.
pub fn report(island: Option<Res<Island>>, time: Res<Time>, roam: Res<crate::envs::Roam>, models: Query<(), With<Model>>, meshes: Query<(), With<Mesh3d>>, mut acc: Local<(f32, f32, u32, f32)>) {
    let Some(island) = island else { return };
    let dt = time.delta_secs();
    acc.0 += dt;
    acc.1 = acc.1.max(dt);
    acc.2 += 1;
    acc.3 += dt;
    if acc.3 < 2.0 {
        return;
    }
    let small: usize = island.small.values().map(Vec::len).sum();
    info!(
        "island perf: mean {:.1} ms ({:.0} fps), worst {:.1} ms; chunks {} ground / {} near ({} small things); {} models, {} meshes; at ({:.0}, {:.0}) {}",
        acc.0 / acc.2 as f32 * 1000.0,
        acc.2 as f32 / acc.0,
        acc.1 * 1000.0,
        island.ground.len(),
        island.small.len(),
        small,
        models.iter().count(),
        meshes.iter().count(),
        roam.pos.x,
        roam.pos.y,
        island.land.kind_at(roam.pos.x, roam.pos.y).id()
    );
    *acc = (0.0, 0.0, 0, 0.0);
}

/// Stream the island around you: build near chunks (nearest first, a few per frame), drop far
/// ones; small things only within `NEAR`.
pub fn stream(
    mut commands: Commands,
    island: Option<ResMut<Island>>,
    roam: Res<crate::envs::Roam>,
    palette: Res<Palette>,
    ground_mat: Res<GroundMat>,
    assets: Res<AssetServer>,
    mut meshes: ResMut<Assets<Mesh>>,
    alive: Query<(), With<EnvPart>>,
) {
    let Some(mut island) = island else { return };
    let me = roam.pos;
    let size = island.land.size as i32 / CHUNK;
    let r = (FAR / CHUNK as f32).ceil() as i32 + 1;
    let (cx, cz) = chunk_of(me);
    // Drop chunks the environment switch already despawned, then far ones.
    island.ground.retain(|_, es| es.first().is_some_and(|e| alive.contains(*e)));
    island.small.retain(|_, es| es.iter().all(|e| alive.contains(*e)) || es.is_empty());
    let far: Vec<_> = island.ground.keys().copied().filter(|c| chunk_distance(*c, me) > FAR + 32.0).collect();
    for c in far {
        for e in island.ground.remove(&c).unwrap_or_default() {
            commands.entity(e).despawn();
        }
    }
    let far_small: Vec<_> = island.small.keys().copied().filter(|c| chunk_distance(*c, me) > NEAR + 16.0).collect();
    for c in far_small {
        for e in island.small.remove(&c).unwrap_or_default() {
            commands.entity(e).despawn();
        }
    }
    let mut want: Vec<((i32, i32), f32)> = Vec::new();
    for j in (cz - r).max(0)..=(cz + r).min(size - 1) {
        for i in (cx - r).max(0)..=(cx + r).min(size - 1) {
            let d = chunk_distance((i, j), me);
            if d <= FAR {
                want.push(((i, j), d));
            }
        }
    }
    want.sort_by(|a, b| a.1.total_cmp(&b.1));
    let land = island.land.clone();
    let mut built = 0;
    for &(c, d) in &want {
        if built >= BUILDS_PER_FRAME {
            break;
        }
        if !island.ground.contains_key(&c) {
            let (g, w) = chunk_meshes(&land, c, island.climate);
            // The painted ground material (terrain.rs); `noterrain` for A/B with the plain toon.
            let mut ground = commands.spawn((EnvPart, Mesh3d(meshes.add(g)), Transform::default()));
            if crate::perf::has("noterrain") {
                ground.insert(MeshMaterial3d(palette.vertex.clone()));
            } else {
                ground.insert(MeshMaterial3d(ground_mat.0.clone()));
            }
            let mut es = vec![ground.id()];
            if !crate::perf::has("nostencil") {
                commands.entity(es[0]).insert(crate::style::ground_stencil());
            }
            if let Some(w) = w {
                es.push(commands.spawn((EnvPart, Mesh3d(meshes.add(w)), MeshMaterial3d(palette.water.clone()), Transform::default())).id());
            }
            // Big things queue now; the small things' and people's files start loading.
            let (big, small): (Vec<Item>, Vec<Item>) = island.site_items.get(&c).cloned().unwrap_or_default().into_iter().chain(island.wild_items(c)).partition(|it| it.height > SMALL && it.person.is_none());
            let fetch = small.iter().map(|it| scene_of(&assets, it).untyped()).collect();
            island.prefetch.insert(c, fetch);
            for item in big {
                let scene = scene_of(&assets, &item);
                island.queue.push(Queued { chunk: c, small: false, item, scene });
            }
            island.ground.insert(c, es);
            built += 1;
        }
        if d <= NEAR && !island.small.contains_key(&c) && island.ground.contains_key(&c) {
            let items: Vec<Item> = island.site_items.get(&c).cloned().unwrap_or_default().into_iter().chain(island.wild_items(c)).collect();
            let items: Vec<Item> = items.into_iter().filter(|it| !(crate::perf::has("nopeople") && it.person.is_some()) && !(crate::perf::has("nosmall") && it.person.is_none())).collect();
            for item in items.into_iter().filter(|it| it.height <= SMALL || it.person.is_some()) {
                let scene = scene_of(&assets, &item);
                island.queue.push(Queued { chunk: c, small: true, item, scene });
            }
            island.small.insert(c, Vec::new());
            built += 1;
        }
    }
    spawn_queued(&mut commands, &assets, &mut island, me);
    island.settled = built == 0 && island.queue.is_empty();
}

/// Spawn queued things, nearest first, within [`SPAWN_BUDGET`]; drop those whose chunk went.
fn spawn_queued(commands: &mut Commands, assets: &AssetServer, island: &mut Island, me: Vec2) {
    let Island { queue, ground, small, prefetch, land, .. } = island;
    prefetch.retain(|c, _| ground.contains_key(c));
    queue.retain(|q| if q.small { small.contains_key(&q.chunk) } else { ground.contains_key(&q.chunk) });
    if queue.is_empty() {
        return;
    }
    // Farthest first in the list, so the nearest pop off its end.
    queue.sort_by(|a, b| b.item.at.distance_squared(me).total_cmp(&a.item.at.distance_squared(me)));
    let unlimited = crate::perf::has("nobudget");
    let mut spent = 0.0;
    let mut waiting = Vec::new();
    while let Some(q) = queue.pop() {
        let cost = if q.item.person.is_some() { PERSON_COST } else { 1.0 };
        if !unlimited && spent > 0.0 && spent + cost > SPAWN_BUDGET {
            queue.push(q);
            break;
        }
        if !ready(assets, &q.scene) {
            waiting.push(q);
            continue;
        }
        let es = spawn_item(commands, assets, land, &q.item);
        let list = if q.small { small.get_mut(&q.chunk) } else { ground.get_mut(&q.chunk) };
        if let Some(list) = list {
            list.extend(es);
        }
        spent += cost;
    }
    queue.extend(waiting);
}
