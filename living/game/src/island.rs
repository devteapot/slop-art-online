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
/// Past [`FAR`], out to where the mood's fog is complete (`world::Draw::landmark_reach`: 600 m
/// on Cullet, where landmarks are drawn), the ground and the sea are drawn coarse: a vertex
/// every [`COARSE_STEP`] m, with no scatter or props, a few chunks a frame.
const COARSE_STEP: usize = 4;
const COARSE_PER_FRAME: usize = 8;
/// Things drawn to a distance (`envs::Reach`) fade out over this band before it (m).
pub const REACH_BAND: f32 = 25.0;
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
    /// A person: recipe seed, folk and style preset ([`person_recipe`]).
    person: Option<(u64, &'static str, String)>,
    /// A plain box (width, height, depth) instead of a model: a lot or a planned settlement's
    /// stair tread or retaining wall whose model is not on disk ([`GreyBox`]).
    size: Option<Vec3>,
    /// A box that is a building: the camera keeps out of it (`envs::Solid`).
    solid: bool,
    /// A box that marks an open lot's footprint ([`MARKER`]) rather than a grey building.
    marker: bool,
    /// A kit's fixture: the camera keeps out of it once fitted, if it is large
    /// (`envs::SolidIfLarge`).
    fixture: bool,
    /// A landmark lot (`Lot::landmark`): it never fades for hiding you (`envs::Landmark`).
    landmark: bool,
    /// A building's or a fixture's glow is people's light, out by day (`lookdev::NightGlow`).
    night_glow: bool,
    /// Stands on the ground (no `floor`) leaning with its slope: a fixture with no floor.
    lean: bool,
}

/// A planned settlement's open lot of no height (steps, a slip, a yard, root plots) with no
/// model on disk: a slab of its footprint this high (m), in a muted stone, so the plan reads in
/// the grey city. Buildings' boxes are [`GREY`].
pub const MARKER_H: f32 = 0.025;
const MARKER: [u8; 3] = [132, 128, 120];
const GREY: [u8; 3] = [168, 168, 172];

/// A plain box standing for a model not on disk yet (a hand-authored settlement before its
/// kit, docs/AUTHORED_PLANS.md): its footprint × its height, in one pale stone grey, or an open
/// lot's footprint slab in a darker stone ([`MARKER_H`]). The mesh and material are added by
/// [`grey_boxes`]; the entity's scale is the box's size. It carries its box as `Fitted`, as a
/// fitted model does, so the camera's "keep out of buildings" and the cut-away see it.
#[derive(Component)]
pub struct GreyBox(pub [u8; 3]);

/// Give new grey boxes the shared unit cube and their toon material.
pub fn grey_boxes(mut commands: Commands, q: Query<(Entity, &GreyBox), Without<Mesh3d>>, mut meshes: ResMut<Assets<Mesh>>, mut palette: ResMut<Palette>, mut toons: ResMut<Assets<crate::style::Toon>>, style: Res<crate::style::Style>, mut unit: Local<Option<Handle<Mesh>>>) {
    for (e, b) in &q {
        let mesh = unit.get_or_insert_with(|| meshes.add(Cuboid::new(1.0, 1.0, 1.0))).clone();
        let mat = palette.color(&mut toons, &style, b.0, false);
        commands.entity(e).insert((Mesh3d(mesh), MeshMaterial3d(mat)));
    }
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
    /// Coarse far chunks (ground and sea only), and whether the sea round the map is placed.
    coarse: HashMap<(i32, i32), Vec<Entity>>,
    ocean: Vec<Entity>,
    /// Things waiting to spawn, by chunk and tier ([`SPAWN_BUDGET`]).
    queue: Vec<Queued>,
    /// The files of a loaded chunk's small things and people, held from its ground's build.
    prefetch: HashMap<(i32, i32), Vec<UntypedHandle>>,
    pub start: Vec2,
    /// Every chunk in reach has its ground and things, and nothing waits to spawn.
    settled: bool,
    /// Flights of stairs, by 16 m cell, for where feet stand ([`Island::foot_height`]).
    flights: HashMap<(i32, i32), Vec<Flight>>,
    /// The current environment's ground map (`ground.rs`); empty on the island.
    surfaces: Arc<crate::ground::Ground>,
}

/// A flight of stairs: `treads` treads rising `rise` m over `run` m from its front (down the
/// stairs, at the lower level's floor) to its back, `width` m wide. A modelled flight is
/// `buildings.py`'s `prop_stairs` ([`TREADS`] treads rising [`RISE`] m over [`RUN`] m, [`TREAD_W`]
/// m wide, inside its footprint); a flight without a model (a planned settlement's, drawn as grey
/// treads) takes its footprint from the prop and its rise from the ground at its head.
#[derive(Clone, Copy)]
struct Flight {
    centre: Vec2,
    down: Vec2,
    floor: f32,
    run: f32,
    width: f32,
    rise: f32,
    treads: f32,
}

const TREADS: f32 = 17.0;
const RISE: f32 = 3.0;
const RUN: f32 = 5.0;
const TREAD_W: f32 = 2.4;
/// A tread's rise on a flight without a model (SMALL_CITY: steps of 0.18 m).
const TREAD_RISE: f32 = 0.18;
const FLIGHT_CELL: f32 = 16.0;

impl Flight {
    fn of(land: &Land, pr: &living_rules::settle::Prop) -> Self {
        let (centre, down) = (Vec2::new(pr.centre.0, pr.centre.1), Vec2::new(pr.front.0, pr.front.1).normalize_or(Vec2::X));
        if pr.model_file.is_some() {
            return Self { centre, down, floor: pr.floor_m, run: RUN, width: TREAD_W, rise: RISE, treads: TREADS };
        }
        let head = centre - down * (pr.depth_m * 0.5 - 0.05);
        let rise = (land.height(head.x, head.y) - pr.floor_m).max(0.1);
        Self { centre, down, floor: pr.floor_m, run: pr.depth_m, width: pr.width_m, rise, treads: (rise / TREAD_RISE).round().max(1.0) }
    }

    /// The tread top under a point, if it is on this flight.
    fn tread(&self, p: Vec2) -> Option<f32> {
        let d = p - self.centre;
        let side = Vec2::new(-self.down.y, self.down.x);
        // From the front edge (u = 0) up to the back (u = run).
        let u = self.run * 0.5 - d.dot(self.down);
        (d.dot(side).abs() <= self.width * 0.5 && (0.0..self.run).contains(&u)).then(|| self.floor + ((u * self.treads / self.run).floor() + 1.0) * self.rise / self.treads)
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
    pub fn new(generated: Generated, defs: &[EnvDef], env: Option<&EnvDef>) -> Self {
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
        let island = Self::build(land, defs, env, start, true, &params);
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
    /// `env` is the environment whose mood lights it, and whose ground map paints it.
    pub fn hosted(land: Arc<Land>, defs: &[EnvDef], env: Option<&EnvDef>, arrive: Vec2, params: &LandParams) -> Self {
        Self::build(land, defs, env, arrive, false, params)
    }

    fn build(land: Arc<Land>, defs: &[EnvDef], env: Option<&EnvDef>, start: Vec2, planned: bool, params: &LandParams) -> Self {
        let climate = Climate::of(params);
        let surfaces = Arc::new(env.map_or_else(crate::ground::Ground::default, |d| crate::ground::Ground::new(&d.id, crate::ground::GroundMap::parse(&d.id, &d.ground.keys), &land, params)));
        let world = WorldDef { seed: land.seed, size: land.size };
        let envs: HashMap<String, EnvDef> = defs.iter().map(|d| (d.id.clone(), d.clone())).collect();
        let mut site_items: HashMap<(i32, i32), Vec<Item>> = HashMap::new();
        let mut put = |it: Item| site_items.entry(chunk_of(it.at)).or_default().push(it);
        let pick = |files: &[String], n: usize, salt: u32| files[(hash(n as u32, salt) * files.len() as f32) as usize % files.len()].clone();
        // Buildings on the planner's lots, by the same rule as the authority's lot rows.
        for li in (0..land.lots.len()).filter(|_| planned) {
            if let Some(it) = LotRow::of_land(&land, li as u32).and_then(|row| lot_item(&envs, &land, &row)) {
                put(it);
            }
        }
        // Street props, stairs and retaining walls: derived from the layout on both sides, not
        // stored by the authority, so connected mode places them too.
        for (pi, pr) in land.props.iter().enumerate() {
            // A prop's model names its folder, as a lot's does; else its settlement's style.
            let env = pr.model_file.as_deref().and_then(|f| f.split('/').next()).filter(|e| !e.is_empty()).unwrap_or(living_rules::settle::env_of(&land.settlements[pr.settlement as usize].style));
            let files = crate::envs::assets_for(env, pr.kind.id());
            let exact = pr.model_file.as_ref().map(|f| format!("envs/{f}")).filter(|f| files.contains(f));
            // A planned settlement's kit that lists fixtures of this kind brings its own (a flight
            // per stair, a wall per drop, each where the plan has it): a prop without a model of
            // its own is not given one of them at random (a Store Wynd flight stood at the Ladder
            // Wynd's foot, on top of the Ladder Wynd's own).
            let kit_brings = land.settlements[pr.settlement as usize].planned && crate::envs::fixtures(env).iter().any(|fx| fx.kind == pr.kind.id());
            let Some(file) = prop_file(&files, exact, kit_brings, pi) else {
                // A planned settlement's stairs and retaining walls without models: grey
                // treads and walls, so the grey city can be walked and read.
                // A kit that lists its fixtures (below) brings its own flights and walls.
                use living_rules::settle::PropKind;
                if pr.model_file.is_none() && land.settlements[pr.settlement as usize].planned && crate::envs::fixtures(env).is_empty() {
                    let (c, f) = (Vec2::new(pr.centre.0, pr.centre.1), Vec2::new(pr.front.0, pr.front.1).normalize_or(Vec2::X));
                    match pr.kind {
                        PropKind::Stairs => {
                            let fl = Flight::of(&land, pr);
                            let step = fl.run / fl.treads;
                            for i in 0..fl.treads as usize {
                                let at = c + f * (fl.run * 0.5 - (i as f32 + 0.5) * step);
                                let h = (i as f32 + 1.0) * fl.rise / fl.treads;
                                put(Item { kind: "stairs".into(), at, yaw: pr.yaw, height: h, k: pi * 64 + i, floor: Some(pr.floor_m), size: Some(Vec3::new(fl.width, h, step)), ..default() });
                            }
                        }
                        PropKind::RetainingWall => put(Item { kind: "retaining_wall".into(), at: c, yaw: pr.yaw, height: pr.height_m, k: pi, floor: Some(pr.floor_m), size: Some(Vec3::new(pr.width_m, pr.height_m, pr.depth_m)), ..default() }),
                        _ => {}
                    }
                }
                continue;
            };
            put(Item { kind: pr.kind.id().to_string(), file, at: Vec2::new(pr.centre.0, pr.centre.1), yaw: pr.yaw, height: pr.height_m, k: pi, floor: Some(pr.floor_m), native: true, ..default() });
        }
        // A planned settlement's fixtures: what its kit builds for places that are not lots (a
        // quay's wall, the walls and flights of its drops, street dressing), listed by the kit's
        // generator in `envs/<env>/fixtures.json` (docs/AUTHORED_PLANS.md). Presentation only:
        // the rules know none of them. They replace the grey stand-ins above.
        let mut kits: Vec<&str> = land.settlements.iter().filter(|s| s.planned).map(|s| living_rules::settle::env_of(&s.style)).collect();
        kits.sort_unstable();
        kits.dedup();
        for env in kits {
            for (fi, fx) in crate::envs::fixtures(env).iter().enumerate() {
                let kind = fx.light.clone().unwrap_or_else(|| fx.kind.clone());
                // Flights are walked over, not walled: their box is not one the eye must leave.
                let fixture = fx.kind != living_rules::settle::PropKind::Stairs.id();
                put(Item { kind, file: fx.file.clone(), at: Vec2::new(fx.at[0], fx.at[1]), yaw: fx.front[0].atan2(fx.front[1]), height: fx.height, glow: fx.glow, k: 100_000 + fi, floor: fx.floor, lean: fx.floor.is_none(), native: true, fixture, night_glow: true, ..default() });
            }
        }
        // A planned settlement's authored resources (`plans[].resources`, on the land as its laid
        // plan) whose kind its environment draws with the kit (`EnvDef::resources`): each on the
        // ground at its place, a model of that folder picked by its index. Presentation only, as
        // the island's forest is: a land world's tree rows are not drawn one by one.
        for laid in &land.plans {
            let env = living_rules::settle::env_of(&land.settlements[laid.settlement as usize].style);
            let Some(def) = envs.get(env) else { continue };
            for (ri, r) in laid.resources.iter().enumerate() {
                let Some(folder) = def.resources.get(&r.kind) else { continue };
                let files = crate::envs::assets_for(env, folder);
                if let Some(file) = resource_file(&files, ri) {
                    let at = Vec2::new(r.at.0, r.at.1);
                    put(Item { kind: folder.clone(), file, at, yaw: hash(ri as u32, 0x7e5) * std::f32::consts::TAU, height: 6.0, k: 200_000 + ri, native: true, ..default() });
                }
            }
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
            let f = Flight::of(&land, pr);
            // Every cell the flight's footprint touches.
            let r = f.run.max(f.width) * 0.5 + 0.5;
            let (lo, hi) = ((f.centre - r) / FLIGHT_CELL, (f.centre + r) / FLIGHT_CELL);
            for cx in lo.x.floor() as i32..=hi.x.floor() as i32 {
                for cz in lo.y.floor() as i32..=hi.y.floor() as i32 {
                    flights.entry((cx, cz)).or_default().push(f);
                }
            }
        }
        Self { land, climate, envs, site_items, ground: HashMap::new(), small: HashMap::new(), coarse: HashMap::new(), ocean: Vec::new(), queue: Vec::new(), prefetch: HashMap::new(), start, settled: false, flights, surfaces }
    }

    /// A building on an authority `lot` row (connected), by [`lot_item`]: its model, a grey
    /// box, or an open lot's footprint marker. Returns the entities to despawn with it.
    pub fn spawn_lot(&self, commands: &mut Commands, assets: &AssetServer, lot: &LotRow) -> Vec<Entity> {
        let Some(it) = lot_item(&self.envs, &self.land, lot) else { return Vec::new() };
        let es = spawn_item(commands, assets, &self.land, &it);
        if let (Some(&root), true) = (es.first(), it.size.is_none()) {
            // Low buildings too (market stalls, wells): a newcomer arrives among the stalls, and
            // their awnings hid them (play-test 1). Taller ones are occluders already.
            if it.height < 3.0 {
                commands.entity(root).insert((crate::envs::Occluder { height: it.height.max(1.0), open: false }, crate::fade::Fade::shown()));
            }
        }
        es
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

/// A street prop's model (`Island::build`): the file its plan names when the kit has it, else one
/// of its kind's files picked by its index, unless the kit brings that kind as fixtures (then
/// none: the fixture stands where the plan has it).
fn prop_file(files: &[String], exact: Option<String>, kit_brings: bool, index: usize) -> Option<String> {
    exact.or_else(|| (!kit_brings && !files.is_empty()).then(|| files[(hash(index as u32, 17) * files.len() as f32) as usize % files.len()].clone()))
}

/// The planned lot whose building a point stands inside: on a tile of the hosted map (`map`:
/// the authority's tiles, `host::hosted_map`, where a building's footprint is blocked) that no
/// one can stand on, within the footprint of a lot that has a building (a height). A household's own hearth and store
/// stand there since `hearth-1` (docs/AUTHORED_PLANS.md, "A household's own things stand inside
/// its lot"); `world::things` hides such a structure while its house is drawn closed.
pub fn indoors_of(land: &Land, map: &living_rules::map::Map, at: Vec2) -> Option<u32> {
    if map.at(at.x, at.y).walkable() {
        return None;
    }
    land.lots
        .iter()
        .enumerate()
        .find(|(_, l)| {
            let (c, f) = (Vec2::new(l.centre.0, l.centre.1), Vec2::new(l.front.0, l.front.1).normalize_or(Vec2::Y));
            let d = at - c;
            l.height_m > 0.0 && land.settlements.get(l.settlement as usize).is_some_and(|s| s.planned) && d.dot(f).abs() <= l.depth_m * 0.5 && d.dot(f.perp()).abs() <= l.width_m * 0.5
        })
        .map(|(i, _)| i as u32)
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

/// A structure's model (`world::things`, connected): from the kit of the planned settlement it
/// stands in (`envs/<env>/<kind>/`, the environment `settle::env_of` names for the settlement's
/// style, the folder alone, not `shared/`), at its real size, with its origin on the ground and its
/// front (+Z) toward the street; a sign's front faces away from the lot at whose door it stands.
/// None elsewhere (generated towns' structures keep their drawn shapes: their environments'
/// models are sized for look-dev slots, not to real size), or when the kit has no such model.
pub fn structure_model(land: &Land, kind: &str, at: Vec2) -> Option<(String, f32)> {
    let env = structure_env(land, at)?;
    let own = format!("envs/{env}/{kind}/");
    let files: Vec<String> = crate::envs::assets_for(env, kind).into_iter().filter(|f| f.starts_with(&own)).collect();
    if files.is_empty() {
        return None;
    }
    let file = files[(hash(at.x.to_bits(), at.y.to_bits()) * files.len() as f32) as usize % files.len()].clone();
    let yaw = structure_front(land, kind, at).map_or_else(|| hash(at.x.to_bits(), at.y.to_bits()) * std::f32::consts::TAU, |f| f.x.atan2(f.y));
    Some((file, yaw))
}

/// The environment of the planned settlement a point is in (within 1.15 of its radius, the
/// nearest such settlement).
fn structure_env(land: &Land, at: Vec2) -> Option<&'static str> {
    land.settlements
        .iter()
        .filter(|s| s.planned)
        .map(|s| (Vec2::new(s.centre.0, s.centre.1).distance(at), s))
        .filter(|(d, s)| *d <= s.radius_m * 1.15)
        .min_by(|a, b| a.0.total_cmp(&b.0))
        .map(|(_, s)| living_rules::settle::env_of(&s.style))
}

/// Which way a structure's front faces on the land: a sign away from the nearest lot within
/// [`SIGN_LOT`] (it stands at its door); anything else toward the nearest street point within
/// [`STRUCTURE_STREET`].
fn structure_front(land: &Land, kind: &str, at: Vec2) -> Option<Vec2> {
    if kind == "sign" {
        let lot = land.lots.iter().map(|l| Vec2::new(l.centre.0, l.centre.1)).filter(|c| c.distance(at) <= SIGN_LOT).min_by(|a, b| a.distance(at).total_cmp(&b.distance(at)));
        if let Some(c) = lot {
            return (at - c).try_normalize();
        }
    }
    let mut best: Option<(f32, Vec2)> = None;
    for r in &land.roads {
        for w in r.points.windows(2) {
            let (a, b) = (Vec2::new(w[0].0, w[0].1), Vec2::new(w[1].0, w[1].1));
            let d = b - a;
            let t = if d.length_squared() > 1e-9 { ((at - a).dot(d) / d.length_squared()).clamp(0.0, 1.0) } else { 0.0 };
            let q = a + d * t;
            let dist = q.distance(at);
            if dist <= STRUCTURE_STREET && best.is_none_or(|(bd, _)| dist < bd) {
                best = Some((dist, q));
            }
        }
    }
    best.and_then(|(_, q)| (q - at).try_normalize())
}

/// A sign stands at a lot's door: the lot it belongs to is within this (m, to its centre).
const SIGN_LOT: f32 = 14.0;
/// How far a structure looks for its street (m).
const STRUCTURE_STREET: f32 = 40.0;

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
    /// Its footprint: along the front and front to back (the `lot` row's), for a box when no
    /// model is on disk.
    pub width_m: f32,
    pub depth_m: f32,
    /// Path under `assets/envs/`, empty when the planner had no exact model.
    pub model: String,
    /// The environment of its settlement's style (`living_rules::settle::env_of`), for lots
    /// without a model path.
    pub env: &'static str,
}

impl LotRow {
    /// A lot of the regenerated land (the same as the authority's `lot` row of that id: the
    /// authority writes the land's lots in order).
    pub fn of_land(land: &Land, id: u32) -> Option<Self> {
        let l = land.lots.get(id as usize)?;
        let st = land.settlements.get(l.settlement as usize)?;
        Some(Self {
            id,
            site: st.kind,
            kind: l.kind,
            at: Vec2::new(l.centre.0, l.centre.1),
            yaw: l.yaw,
            floor_m: l.floor_m,
            height_m: l.height_m,
            width_m: l.width_m,
            depth_m: l.depth_m,
            model: l.model_file.clone().unwrap_or_default(),
            env: living_rules::settle::env_of(&st.style),
        })
    }
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

/// A model for a plan's authored resource from its kit folder's files, by the resource's index.
fn resource_file(files: &[String], index: usize) -> Option<String> {
    (!files.is_empty()).then(|| files[(hash(index as u32, 0x7e7) * files.len() as f32) as usize % files.len()].clone())
}

/// How a thing with no floor stands on the land at `at` (game x, z), turned to `yaw`: its
/// origin's height on the ground, and its turn leaning with the slope there (its up along the
/// ground's normal, from the land's heights a metre either way).
pub fn on_slope(land: &Land, at: Vec2, yaw: f32) -> (f32, Quat) {
    let h = |x: f32, z: f32| land.height(x, z);
    let d = 1.0;
    let n = Vec3::new(h(at.x - d, at.y) - h(at.x + d, at.y), 2.0 * d, h(at.x, at.y - d) - h(at.x, at.y + d)).normalize_or(Vec3::Y);
    (h(at.x, at.y), Quat::from_rotation_arc(Vec3::Y, n) * Quat::from_rotation_y(yaw))
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
        // A drop is drawn as its wall was: the bank under a retaining wall.
        Terrain::Wall | Terrain::Drop | Terrain::Low => rgb(110, 100, 90),
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
        Terrain::Wall | Terrain::Drop | Terrain::Low => rgb(110, 100, 90),
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
        Terrain::Rock | Terrain::Wall | Terrain::Drop | Terrain::Low => one(Layer::Rock),
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
        Terrain::Rock | Terrain::Wall | Terrain::Drop | Terrain::Low => one(Layer::Rock),
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
        // The rules name each style's paving (`settle::road_surface`), so new district styles
        // need no change here.
        return match living_rules::settle::road_surface(&st.style) {
            Some("pavers") => Layer::Pavers,
            Some("setts") => Layer::Cobble,
            Some("earth") => earth,
            Some("gravel") => Layer::Gravel,
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
/// tiles blend instead of switching along straight polygon edges. Where the environment's ground
/// map (`ground.rs`) has a key for a sample, it gives that sample's colour and layer.
fn blended_ground(land: &Land, x: f32, z: f32, v: f32, climate: Climate, map: &crate::ground::Ground) -> ([f32; 4], Blend) {
    let mapped = !map.is_empty();
    let p = Vec2::new(x, z);
    // Roads and paved squares stay crisp, and don't bleed into the blend around them.
    let here = land.map.at(x + 0.01, z + 0.01);
    if here == Terrain::Road {
        if let Some(s) = map.road(p + 0.01, land.kind_at(x, z)).filter(|_| mapped) {
            return (s.colour_at(p, v), Blend::one(s.layer));
        }
        return (ground_colour(here, land.kind_at(x, z), v, climate), Blend::one(road_layer(land, x, z, climate)));
    }
    // So do a map's areas (a yard of cinders, a quay's flags).
    if let Some(s) = map.area(p + 0.01).filter(|_| mapped) {
        return (s.colour_at(p, v), Blend::one(s.layer));
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
        if let Some(s) = map.open(Vec2::new(px, pz) + 0.01, t, kind).filter(|_| mapped) {
            let c = s.colour_at(Vec2::new(px, pz), v);
            for i in 0..4 {
                acc[i] += c[i] * w;
            }
            blend.add(s.layer, w);
            continue;
        }
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

/// A chunk's ground (an indexed grid, a vertex every `step` m: 1 near, [`COARSE_STEP`] far;
/// smooth normals) and its water surface.
fn chunk_meshes(land: &Land, c: (i32, i32), climate: Climate, step: usize, map: &crate::ground::Ground) -> (Mesh, Option<Mesh>) {
    let n = CHUNK as usize / step;
    let st = step as i32;
    let (x0, z0) = (c.0 * CHUNK, c.1 * CHUNK);
    let mut pos = Vec::with_capacity((n + 1) * (n + 1));
    let mut col = Vec::with_capacity((n + 1) * (n + 1));
    let mut blends = Vec::with_capacity((n + 1) * (n + 1));
    for j in 0..=n {
        for i in 0..=n {
            let (x, z) = ((x0 + i as i32 * st) as f32, (z0 + j as i32 * st) as f32);
            pos.push([x, land.height(x, z), z]);
            let v = hash((x0 + i as i32 * st) as u32, (z0 + j as i32 * st) as u32);
            let (mut c, b) = blended_ground(land, x, z, v, climate, map);
            // A face: the ground steps more than about a metre per metre to a neighbour (a quay
            // standing out of the sea, an authored drop). The mesh's smoothed normals round such
            // a step into a slope that the shader's slope test leaves as grass, so the stone is
            // chosen here from the heights themselves ([`face_share`]).
            let face = face_share(land, x, z, step as f32);
            let b = if face > 0.0 { b.toward(Layer::Rock, face) } else { b };
            if face > 0.0 {
                let stone = ground_colour(Terrain::Rock, RegionKind::Meadow, v, climate);
                for k in 0..3 {
                    c[k] += (stone[k] - c[k]) * face;
                }
            }
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
    let k = step as f32;
    for j in 0..n {
        for i in 0..n {
            let (x, z) = ((x0 + i as i32 * st) as f32, (z0 + j as i32 * st) as f32);
            let corners = [(x, z), (x + k, z), (x, z + k), (x + k, z + k)];
            let water = |dx: f32, dz: f32| land.map.at(x + 0.5 * k + dx, z + 0.5 * k + dz) == Terrain::Water;
            let h = 0.5 * k;
            let wet = water(0.0, 0.0) || water(k, 0.0) || water(-k, 0.0) || water(0.0, k) || water(0.0, -k) || (step > 1 && (water(-h, -h) || water(h, -h) || water(-h, h) || water(h, h)));
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

/// How much of a face the ground is at a vertex (0–1): its steepest step to a neighbour `step`
/// m away, from about 45° (a rise of 0.9 m per metre: stairs climb 0.55, generated hills
/// rarely more) to 1.6 m per metre.
fn face_share(land: &Land, x: f32, z: f32, step: f32) -> f32 {
    let y = land.height(x, z);
    let drop = [(step, 0.0), (-step, 0.0), (0.0, step), (0.0, -step)].iter().map(|(dx, dz)| (land.height(x + dx, z + dz) - y).abs()).fold(0.0f32, f32::max) / step;
    let t = ((drop - 0.9) / 0.7).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

/// A background person's recipe, for both their preload ([`scene_of`]) and their spawn
/// ([`spawn_item`]), so the two never disagree: a grown person's line from the look book's
/// `decor` pool by their own seed (a pool apart from newcomers', so an extra is never a real
/// newcomer's twin), else, and for giants and small folk, a random recipe dressed in their
/// settlement's style (fantasy where it has no preset).
fn person_recipe(it: &Item) -> Option<crate::characters::Recipe> {
    let (seed, folk, style) = it.person.as_ref()?;
    let book = crate::characters::book::book().filter(|_| *folk == "adult" && crate::characters::compose::enabled());
    let decor = book.and_then(|b| b.decor(*seed, crate::characters::book::ADULT).and_then(|(key, _)| b.recipe(key).ok()));
    Some(decor.unwrap_or_else(|| crate::characters::Recipe::random_in(*seed, folk, style)))
}

/// The scene file a thing spawns from (a person's: its recipe's animated base).
fn scene_of(assets: &AssetServer, it: &Item) -> Handle<WorldAsset> {
    if it.size.is_some() {
        return Handle::default();
    }
    let file = match person_recipe(it) {
        Some(r) => crate::lookdev::animated(&r.base),
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

/// What is drawn on a lot, connected or in look-dev:
/// - its model file (`model`, under `envs/`) when it is on disk;
/// - in a **planned** settlement (an authored plan, docs/AUTHORED_PLANS.md), otherwise a grey box
///   of its footprint and height, or for an open lot of no height a footprint marker
///   ([`MARKER_H`]), unless a fixture of its kit stands on it (since layout-2: a court or a plot
///   is an open lot, and its enclosure draws it). A planned lot is never given another lot's model: its plan sized it for its
///   own, and a terrace of borrowed houses would overlap. Its environment's folder may be empty
///   or missing (Cullet's before its kit is generated);
/// - elsewhere, a model of its kind from its environment (a generated town's buildings are
///   sampled, `settle::env_of`), else a grey box when it has height; gardens and fields nothing.
fn lot_item(envs: &HashMap<String, EnvDef>, land: &Land, lot: &LotRow) -> Option<Item> {
    let planned = land.lots.get(lot.id as usize).and_then(|l| land.settlements.get(l.settlement as usize)).is_some_and(|s| s.planned);
    let landmark = land.lots.get(lot.id as usize).is_some_and(|l| l.landmark);
    let base = Item { kind: lot.kind.id().to_string(), at: lot.at, yaw: lot.yaw, height: lot.height_m, k: lot.id as usize, floor: Some(lot.floor_m), solid: true, landmark, night_glow: true, ..default() };
    // The row's model names its folder (`steampunk_city/clocktower/...`): a town in its own
    // style uses its own assets.
    let env = lot.model.split('/').next().filter(|_| !lot.model.is_empty()).unwrap_or(lot.env);
    let kind = living_rules::settle::asset_kind(&lot.model).or(lot.kind.model());
    let files = kind.map(|k| crate::envs::assets_for(env, k)).unwrap_or_default();
    let exact = Some(format!("envs/{}", lot.model)).filter(|f| !lot.model.is_empty() && files.contains(f));
    let slot = kind.and_then(|k| envs.get(env).and_then(|d| d.slots.iter().find(|s| s.kind == k)));
    if let Some(file) = exact {
        return Some(Item { kind: kind.unwrap_or("").to_string(), file, glow: slot.and_then(|s| s.glow), native: true, ..base });
    }
    if planned || files.is_empty() {
        let (w, d) = (lot.width_m.max(0.1), lot.depth_m.max(0.1));
        if lot.height_m > 0.0 {
            return Some(Item { size: Some(Vec3::new(w, lot.height_m, d)), ..base });
        }
        // An open lot a fixture of the kit stands on (a court's walls, a plot's beds, a
        // graveyard's rows) is drawn by that fixture: no slab under it.
        if crate::envs::fixtures(lot.env).iter().any(|f| f.covers(lot.at)) {
            return None;
        }
        return planned.then(|| Item { size: Some(Vec3::new(w, MARKER_H, d)), height: MARKER_H, marker: true, solid: false, ..base });
    }
    if !lot.model.is_empty() {
        warn!("lot {}: model {} is not on disk; using another {}", lot.id, lot.model, kind.unwrap_or(""));
    }
    let height = slot.map_or(6.0, |s| s.height[1]);
    let file = files[(hash(lot.id, 11) * files.len() as f32) as usize % files.len()].clone();
    Some(Item { kind: kind.unwrap_or("").to_string(), file, height, glow: slot.and_then(|s| s.glow), native: true, ..base })
}

fn spawn_item(commands: &mut Commands, assets: &AssetServer, land: &Land, it: &Item) -> Vec<Entity> {
    let y = it.floor.unwrap_or_else(|| land.height(it.at.x, it.at.y));
    let at = Vec3::new(it.at.x, y, it.at.y);
    if let Some(recipe) = person_recipe(it) {
        let e = crate::characters::spawn(commands, assets, &recipe, at, it.yaw);
        commands.entity(e).insert(EnvPart);
        return vec![e];
    }
    if let Some(size) = it.size {
        let c = at + Vec3::Y * size.y * 0.5;
        let colour = if it.marker { MARKER } else { GREY };
        let fitted = crate::lookdev::Fitted { y_off: 0.0, size, center: Vec3::ZERO };
        let mut e = commands.spawn((EnvPart, GreyBox(colour), fitted, Transform::from_translation(c).with_rotation(Quat::from_rotation_y(it.yaw)).with_scale(size)));
        if it.height >= 3.0 {
            e.insert((Occluder { height: it.height, open: false }, crate::fade::Fade::shown()));
        }
        if it.solid {
            e.insert(crate::envs::Solid);
        }
        if it.landmark {
            e.insert(crate::envs::Landmark);
        }
        if it.marker {
            e.insert(bevy::light::NotShadowCaster);
        }
        return vec![e.id()];
    }
    let vrm = it.file.contains("vroid-");
    let turn = if it.lean { on_slope(land, it.at, it.yaw).1 } else { Quat::from_rotation_y(it.yaw) };
    let model = Model { vrm, file: it.file.clone(), height: if it.native { 0.0 } else { it.height }, ground_y: y, glow: it.glow };
    let handle = assets.load(GltfAssetLabel::Scene(0).from_asset(it.file.clone()));
    let mut e = commands.spawn((EnvPart, model, WorldAssetRoot(handle), Transform::from_translation(at).with_rotation(turn), Visibility::Hidden));
    if it.height >= 3.0 {
        e.insert((Occluder { height: it.height, open: false }, crate::fade::Fade::shown()));
    }
    if it.height <= SMALL {
        e.insert(crate::lookdev::NoShadow);
    }
    if it.solid {
        e.insert(crate::envs::Solid);
    }
    if it.fixture {
        e.insert(crate::envs::SolidIfLarge);
    }
    if it.night_glow {
        e.insert(crate::lookdev::NightGlow);
    }
    if it.landmark {
        e.insert(crate::envs::Landmark);
    }
    let mut out = vec![e.id()];
    if let Some((light, tf)) = crate::envs::local_light(&it.kind, it.glow, it.height, it.k) {
        out.push(commands.spawn((EnvPart, light, Transform::from_translation(at + tf.translation))).id());
    }
    out
}

/// Every 2 s: frame times (mean and worst), what is loaded, the ground meshes' size, and where
/// you are.
#[allow(clippy::too_many_arguments)]
pub fn report(island: Option<Res<Island>>, time: Res<Time>, roam: Res<crate::envs::Roam>, models: Query<(), With<Model>>, meshes: Query<(), With<Mesh3d>>, handles: Query<&Mesh3d>, assets: Res<Assets<Mesh>>, mut acc: Local<(f32, f32, u32, f32)>) {
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
    // The ground meshes' vertex and index data (each chunk's first entity is its ground).
    let (mut bytes, mut vertex) = (0usize, 0usize);
    for es in island.ground.values().chain(island.coarse.values()) {
        if let Some(m) = es.first().and_then(|e| handles.get(*e).ok()).and_then(|h| assets.get(&h.0)) {
            vertex = m.get_vertex_size() as usize;
            bytes += m.count_vertices() * vertex + m.indices().map_or(0, |i| i.len() * 4);
        }
    }
    info!(
        "island perf: mean {:.1} ms ({:.0} fps), worst {:.1} ms; chunks {} ground / {} coarse / {} near ({} small things); {} models, {} meshes; ground meshes {:.2} MB ({vertex} B a vertex); at ({:.0}, {:.0}) {}",
        acc.0 / acc.2 as f32 * 1000.0,
        acc.2 as f32 / acc.0,
        acc.1 * 1000.0,
        island.ground.len(),
        island.coarse.len(),
        island.small.len(),
        small,
        models.iter().count(),
        meshes.iter().count(),
        bytes as f32 / 1e6,
        roam.pos.x,
        roam.pos.y,
        island.land.kind_at(roam.pos.x, roam.pos.y).id()
    );
    *acc = (0.0, 0.0, 0, 0.0);
}

/// A chunk's ground and water entities, a vertex every `step` m.
#[allow(clippy::too_many_arguments)]
fn spawn_ground(commands: &mut Commands, meshes: &mut Assets<Mesh>, palette: &Palette, ground_mat: &GroundMat, land: &Land, c: (i32, i32), climate: Climate, step: usize, map: &crate::ground::Ground) -> Vec<Entity> {
    let (g, w) = chunk_meshes(land, c, climate, step, map);
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
    es
}

/// The sea beyond the land's square, at sea level, out past `reach`: four quads round the map,
/// so a long view over the water ends in fog, not at the map's edge.
fn spawn_ocean(commands: &mut Commands, meshes: &mut Assets<Mesh>, palette: &Palette, size: f32, reach: f32) -> Vec<Entity> {
    let (lo, hi) = (-reach - 200.0, size + reach + 200.0);
    let quads = [(lo, lo, hi, 0.0), (lo, size, hi, hi), (lo, 0.0, 0.0, size), (size, 0.0, hi, size)];
    quads
        .iter()
        .map(|&(x0, z0, x1, z1)| {
            let pos = vec![[x0, -0.05, z0], [x1, -0.05, z0], [x0, -0.05, z1], [x1, -0.05, z1]];
            let mesh = Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::default())
                .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, pos)
                .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, vec![[0.0, 1.0, 0.0]; 4])
                .with_inserted_indices(Indices::U32(vec![0, 2, 1, 1, 2, 3]));
            commands.spawn((EnvPart, Mesh3d(meshes.add(mesh)), MeshMaterial3d(palette.water.clone()), Transform::default())).id()
        })
        .collect()
}

/// Stream the island around you: build near chunks (nearest first, a few per frame), drop far
/// ones; small things only within `NEAR`. Past [`FAR`], out to the mood's landmark reach, coarse
/// chunks of ground and sea, and the sea round the map.
#[allow(clippy::too_many_arguments)]
pub fn stream(
    mut commands: Commands,
    island: Option<ResMut<Island>>,
    roam: Res<crate::envs::Roam>,
    palette: Res<Palette>,
    ground_mat: Res<GroundMat>,
    assets: Res<AssetServer>,
    mut meshes: ResMut<Assets<Mesh>>,
    alive: Query<(), With<EnvPart>>,
    draw: Res<crate::world::Draw>,
) {
    let Some(mut island) = island else { return };
    let me = roam.pos;
    let size = island.land.size as i32 / CHUNK;
    // How far coarse ground goes: where the mood's fog is complete, if that is past FAR.
    // `LIVING_GAME_PERF=nofar` leaves the coarse ring and the far landmarks out (measurement only).
    let reach = if crate::perf::has("nofar") { FAR } else { draw.landmark_reach().max(FAR) };
    let coarse_on = reach > FAR + 1.0;
    let r = (reach / CHUNK as f32).ceil() as i32 + 1;
    let (cx, cz) = chunk_of(me);
    // Drop chunks the environment switch already despawned, then far ones. A detailed chunk
    // going out of FAR stays until its coarse one is built, so no hole opens.
    island.ground.retain(|_, es| es.first().is_some_and(|e| alive.contains(*e)));
    island.coarse.retain(|_, es| es.first().is_some_and(|e| alive.contains(*e)));
    island.small.retain(|_, es| es.iter().all(|e| alive.contains(*e)) || es.is_empty());
    let far: Vec<_> = island.ground.keys().copied().filter(|c| {
        let d = chunk_distance(*c, me);
        d > FAR + 32.0 && (!coarse_on || d > reach + 32.0 || island.coarse.contains_key(c))
    }).collect();
    for c in far {
        for e in island.ground.remove(&c).unwrap_or_default() {
            commands.entity(e).despawn();
        }
    }
    // A coarse chunk goes past the reach, or where the detailed one stays (within FAR + 32 m).
    let gone: Vec<_> = island.coarse.keys().copied().filter(|c| {
        let d = chunk_distance(*c, me);
        !coarse_on || d > reach + 32.0 || (d <= FAR + 32.0 && island.ground.contains_key(c))
    }).collect();
    for c in gone {
        for e in island.coarse.remove(&c).unwrap_or_default() {
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
            if d <= reach {
                want.push(((i, j), d));
            }
        }
    }
    want.sort_by(|a, b| a.1.total_cmp(&b.1));
    let land = island.land.clone();
    let climate = island.climate;
    let surfaces = island.surfaces.clone();
    let mut built = 0;
    let mut coarse_built = 0;
    for &(c, d) in &want {
        if d > FAR {
            // Coarse: ground and sea only, a few a frame.
            // A detailed chunk in the band just past FAR stays; farther out its coarse one replaces it.
            let detailed = island.ground.contains_key(&c) && d <= FAR + 32.0;
            if coarse_built < COARSE_PER_FRAME && !detailed && !island.coarse.contains_key(&c) {
                let es = spawn_ground(&mut commands, &mut meshes, &palette, &ground_mat, &land, c, climate, COARSE_STEP, &surfaces);
                island.coarse.insert(c, es);
                coarse_built += 1;
            }
            continue;
        }
        if built >= BUILDS_PER_FRAME {
            continue;
        }
        if !island.ground.contains_key(&c) {
            let es = spawn_ground(&mut commands, &mut meshes, &palette, &ground_mat, &land, c, climate, 1, &surfaces);
            // Big things queue now; the small things' and people's files start loading.
            let (big, small): (Vec<Item>, Vec<Item>) = island.site_items.get(&c).cloned().unwrap_or_default().into_iter().chain(island.wild_items(c)).partition(|it| it.height > SMALL && it.person.is_none());
            let fetch = small.iter().map(|it| scene_of(&assets, it).untyped()).collect();
            island.prefetch.insert(c, fetch);
            for item in big {
                let scene = scene_of(&assets, &item);
                island.queue.push(Queued { chunk: c, small: false, item, scene });
            }
            island.ground.insert(c, es);
            // Its coarse stand-in goes now that the detailed ground is there.
            for e in island.coarse.remove(&c).unwrap_or_default() {
                commands.entity(e).despawn();
            }
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
    if coarse_on && island.ocean.is_empty() {
        island.ocean = spawn_ocean(&mut commands, &mut meshes, &palette, land.size as f32, reach);
    } else if !coarse_on && !island.ocean.is_empty() {
        for e in std::mem::take(&mut island.ocean) {
            commands.entity(e).despawn();
        }
    }
    spawn_queued(&mut commands, &assets, &mut island, me);
    island.settled = built == 0 && coarse_built == 0 && island.queue.is_empty();
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
        if q.item.size.is_none() && !ready(assets, &q.scene) {
            waiting.push(q);
            continue;
        }
        let es = spawn_item(commands, assets, land, &q.item);
        // Drawn out to its tier's distance, fading over the last few metres (`envs::reach`):
        // past the mood's fog start (Cullet's 180 m) the fog no longer hides where streaming stops.
        if let (Some(&root), None) = (es.first(), &q.item.person) {
            let r = if q.small { NEAR } else { FAR };
            commands.entity(root).insert((crate::envs::Reach(r), crate::envs::Reach::fade_at(r, q.item.at.distance(me))));
        }
        let list = if q.small { small.get_mut(&q.chunk) } else { ground.get_mut(&q.chunk) };
        if let Some(list) = list {
            list.extend(es);
        }
        spent += cost;
    }
    queue.extend(waiting);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ground::{Areas, Ground, GroundMap, Streets, Surface};

    /// `blended_ground` as it was before environments had ground maps (ground-1), verbatim.
    fn legacy_blended_ground(land: &Land, x: f32, z: f32, v: f32, climate: Climate) -> ([f32; 4], Blend) {
        let here = land.map.at(x + 0.01, z + 0.01);
        if here == Terrain::Road {
            return (ground_colour(here, land.kind_at(x, z), v, climate), Blend::one(road_layer(land, x, z, climate)));
        }
        const RING: [(f32, f32); 9] = [(0.0, 0.0), (6.0, 0.0), (-6.0, 0.0), (0.0, 6.0), (0.0, -6.0), (13.0, 9.0), (-13.0, -9.0), (9.0, -13.0), (-9.0, 13.0)];
        let mut acc = [0.0f32; 4];
        let mut blend = Blend::default();
        for (k, (dx, dz)) in RING.iter().enumerate() {
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

    fn cullet() -> (Land, LandParams) {
        let (seed, size, params) = seed_land(concat!(env!("CARGO_MANIFEST_DIR"), "/../seeds/cullet.json")).expect("the Cullet seed");
        (living_rules::land::generate(seed, size, &params), params)
    }

    fn top(b: &Blend) -> Layer {
        let k = b.0.iter().enumerate().max_by(|a, b| a.1.total_cmp(b.1)).unwrap().0;
        Layer::ALL[k]
    }

    #[test]
    fn structures_take_their_planned_settlements_kit_and_face_the_street() {
        let (land, _) = cullet();
        let town = land.settlements.iter().find(|s| s.planned).expect("Cullet is planned");
        let c = Vec2::new(town.centre.0, town.centre.1);
        assert_eq!(structure_env(&land, c), Some("cullet"));
        assert_eq!(structure_env(&land, Vec2::new(5.0, 5.0)), None, "outside any settlement");
        // A sign at a lot's door faces away from the lot, out of its front.
        let centre = |l: &living_rules::settle::Lot| Vec2::new(l.centre.0, l.centre.1);
        let mut tried = 0;
        for lot in &land.lots {
            let (lc, lf) = (centre(lot), Vec2::new(lot.front.0, lot.front.1));
            let sign = lc + lf * (lot.depth_m * 0.5 + 0.6);
            let nearest = land.lots.iter().map(|l| centre(l).distance(sign)).fold(f32::MAX, f32::min);
            if nearest < lc.distance(sign) || lc.distance(sign) > SIGN_LOT {
                continue;
            }
            let f = structure_front(&land, "sign", sign).expect("a front");
            assert!(f.dot(lf) > 0.99, "sign at {sign} faces {f}, its lot's front {lf}");
            tried += 1;
        }
        assert!(tried > 20, "{tried} lots");
        // Anything else turns toward the nearest street within reach.
        let road = land.roads.iter().find(|r| r.points.len() >= 2).expect("a street");
        let (a, b) = (Vec2::new(road.points[0].0, road.points[0].1), Vec2::new(road.points[1].0, road.points[1].1));
        let side = (b - a).perp().normalize() * 0.5;
        let near = (a + b) * 0.5 + side;
        let f = structure_front(&land, "storage", near).expect("a street nearby");
        assert!(f.dot(-side.normalize()) > 0.99, "faces {f}, the street is toward {}", -side);
        // A generated land's towns are not planned: their structures keep their drawn shapes.
        let gen = living_rules::land::generate(7, 512, &LandParams::default());
        for s in &gen.settlements {
            assert_eq!(structure_model(&gen, "sign", Vec2::new(s.centre.0, s.centre.1)), None);
        }
    }

    /// A plan's stairs and retaining walls without a model of their own take none of the kit's
    /// files at random when the kit brings that kind as fixtures (stairs-place: a Store Wynd
    /// flight was drawn at the Ladder Wynd's foot); a named model, and a kit without such
    /// fixtures, are as before.
    #[test]
    fn a_kit_that_brings_a_kind_as_fixtures_is_not_sampled_for_plan_props() {
        let files: Vec<String> = ["envs/k/stairs/a.glb", "envs/k/stairs/b.glb"].iter().map(|s| s.to_string()).collect();
        for i in 0..40 {
            assert_eq!(prop_file(&files, None, true, i), None, "prop {i}");
            assert!(prop_file(&files, None, false, i).is_some_and(|f| files.contains(&f)));
            assert_eq!(prop_file(&files, Some(files[1].clone()), true, i).as_deref(), Some("envs/k/stairs/b.glb"));
        }
        assert_eq!(prop_file(&[], None, false, 3), None);
        // Cullet's kit, when it is on disk: it lists stairs and retaining walls as fixtures, so
        // none of the plan's props of those kinds is given a kit file at random.
        let fx = crate::envs::fixtures("cullet");
        if !fx.is_empty() {
            let (land, _) = cullet();
            let kinds: std::collections::HashSet<&str> = fx.iter().map(|f| f.kind.as_str()).collect();
            let mut covered = 0;
            for (pi, pr) in land.props.iter().enumerate() {
                let env = living_rules::settle::env_of(&land.settlements[pr.settlement as usize].style);
                if env != "cullet" || pr.model_file.is_some() || !kinds.contains(pr.kind.id()) {
                    continue;
                }
                covered += 1;
                assert_eq!(prop_file(&crate::envs::assets_for(env, pr.kind.id()), None, true, pi), None);
            }
            assert!(covered > 0, "Cullet's plan has stairs and walls its kit brings");
        }
    }

    #[test]
    fn without_a_map_the_ground_is_drawn_as_before() {
        let (land, params) = cullet();
        // An environment with no map (the island's, and Cullet's until kit-2 writes one) builds an
        // empty ground: no areas, streets or stamps are even gathered.
        let none = Ground::new("cullet", GroundMap::default(), &land, &params);
        assert!(none.is_empty());
        let mut n = 0;
        for climate in [Climate::Temperate, Climate::Arid] {
            for j in (0..land.size).step_by(3) {
                for i in (0..land.size).step_by(3) {
                    let (x, z) = (i as f32, j as f32);
                    let v = hash(i, j);
                    let (c0, b0) = legacy_blended_ground(&land, x, z, v, climate);
                    let (c1, b1) = blended_ground(&land, x, z, v, climate, &none);
                    assert_eq!(c0.map(f32::to_bits), c1.map(f32::to_bits), "colour at {x}, {z}");
                    assert_eq!(b0.0.map(f32::to_bits), b1.0.map(f32::to_bits), "blend at {x}, {z}");
                    // The old layers keep the first four attributes' bytes; the new two are zero.
                    assert_eq!(b1.pack()[4..], [[0u8; 4]; 2]);
                    n += 1;
                }
            }
        }
        assert!(n > 200_000);
        // A whole chunk's mesh, quay faces and blocking rock included.
        let (g, _) = chunk_meshes(&land, (7, 12), Climate::Temperate, 1, &none);
        assert_eq!(g.attribute(crate::terrain::ATTRIBUTE_BLEND[5].id).map(|a| a.len()), Some(65 * 65));
    }

    #[test]
    fn a_map_paints_streets_areas_stamps_classes_and_regions() {
        let (land, params) = cullet();
        let mut map = GroundMap::default();
        let key = |m: &mut GroundMap, k: &str, l: Layer| m.insert(k, Surface::new(l, [100, 100, 100], None)).unwrap();
        key(&mut map, "street:quay_flags", Layer::QuayFlags);
        key(&mut map, "street:setts", Layer::SlateSetts);
        key(&mut map, "street:cinders", Layer::Cinders);
        key(&mut map, "class:Road", Layer::Flagstone);
        key(&mut map, "stamp:sand", Layer::WetSand);
        key(&mut map, "region:meadow", Layer::ThinTurf);
        key(&mut map, "area:worked_soil", Layer::WorkedSoil);
        // The root plots, as kit-2's ground.json would draw them.
        let (areas, _) = Areas::parse(r#"[{"id": "roots", "surface": "worked_soil", "area": [[268, 618], [330, 618], [330, 645], [268, 645]]}]"#).unwrap();
        let g = Ground::of(map, areas, &land, &params);
        let streets = Streets::of_land(&land);
        let mut seen: HashMap<&str, usize> = HashMap::new();
        for j in 600..800 {
            for i in 250..720 {
                let (x, z) = (i as f32, j as f32);
                let tile = land.map.at(x + 0.01, z + 0.01);
                let (_, b) = blended_ground(&land, x, z, 0.5, Climate::Temperate, &g);
                let p = Vec2::new(x, z) + 0.01;
                let want = if tile == Terrain::Road {
                    match streets.at(p) {
                        Some("quay_flags") => Some((Layer::QuayFlags, "street:quay_flags")),
                        Some("setts") => Some((Layer::SlateSetts, "street:setts")),
                        Some("cinders") => Some((Layer::Cinders, "street:cinders")),
                        _ => Some((Layer::Flagstone, "class:Road")),
                    }
                } else if (268.5..329.5).contains(&p.x) && (618.5..644.5).contains(&p.y) {
                    Some((Layer::WorkedSoil, "area:worked_soil"))
                } else {
                    None
                };
                if let Some((layer, k)) = want {
                    // Roads and areas are crisp: one layer alone.
                    assert_eq!(b.0.iter().filter(|w| **w > 0.0).count(), 1, "{k} at {x}, {z}: {b:?}");
                    assert_eq!(top(&b), layer, "{k} at {x}, {z}");
                    *seen.entry(k).or_default() += 1;
                }
            }
        }
        for k in ["street:quay_flags", "street:setts", "street:cinders", "class:Road", "area:worked_soil"] {
            assert!(seen.get(k).is_some_and(|n| *n > 20), "{k}: {seen:?}");
        }
        // The Wrack Strand's sand stamp, and the moor's meadow, blend in from their tiles.
        let (mut stamp, mut meadow) = (0, 0);
        for j in (0..land.size).step_by(4) {
            for i in (0..land.size).step_by(4) {
                let (x, z) = (i as f32, j as f32);
                let (_, b) = blended_ground(&land, x, z, 0.5, Climate::Temperate, &g);
                stamp += usize::from(b.0[Layer::WetSand as usize] > 0.0);
                meadow += usize::from(b.0[Layer::ThinTurf as usize] > 0.0);
                // Whatever the map leaves unmapped keeps the island's own layers.
                assert_eq!(b.0[Layer::Heather as usize], 0.0);
            }
        }
        assert!(stamp > 50 && meadow > 1000, "stamp {stamp}, meadow {meadow}");
    }

    /// Kit-2's client needs, from data only: a fixture with no `floor` stands on the land's
    /// ground leaning with the slope there; an environment's `resources` names the kit folder a
    /// planned settlement's authored resources of a kind are drawn from (Cullet: `tree` →
    /// `hanger_tree`).
    #[test]
    fn a_fixture_without_a_floor_leans_with_the_ground_and_plan_resources_take_their_kits_folder() {
        let fx: crate::envs::Fixture = serde_json::from_str(r#"{"file": "envs/k/stump/stump_1.glb", "kind": "stump", "at": [1.0, 2.0], "front": [0.0, 1.0], "height": 0.6}"#).unwrap();
        assert_eq!(fx.floor, None);
        let fx: crate::envs::Fixture = serde_json::from_str(r#"{"file": "envs/k/quay/q.glb", "kind": "quay", "at": [1.0, 2.0], "front": [0.0, 1.0], "floor": 2.0, "height": 0.3}"#).unwrap();
        assert_eq!(fx.floor, Some(2.0));
        // On the slope, the origin is on the ground and its up is the ground's normal.
        let (land, _) = cullet();
        let slope = |x: f32, z: f32| ((land.height(x + 1.0, z) - land.height(x - 1.0, z)).abs() + (land.height(x, z + 1.0) - land.height(x, z - 1.0)).abs()) / 2.0;
        let mut steep = (Vec2::ZERO, 0.0);
        for j in (40..land.size - 40).step_by(7) {
            for i in (40..land.size - 40).step_by(7) {
                let (x, z) = (i as f32, j as f32);
                let s = slope(x, z);
                if s > steep.1 && s < 1.0 && land.height(x, z) > 1.0 {
                    steep = (Vec2::new(x, z), s);
                }
            }
        }
        assert!(steep.1 > 0.2, "Cullet has slopes ({})", steep.1);
        let at = steep.0;
        let (y, turn) = on_slope(&land, at, 0.7);
        assert!((y - land.height(at.x, at.y)).abs() < 1e-4);
        let up = turn * Vec3::Y;
        let (hx, hz) = ((land.height(at.x + 1.0, at.y) - land.height(at.x - 1.0, at.y)) / 2.0, (land.height(at.x, at.y + 1.0) - land.height(at.x, at.y - 1.0)) / 2.0);
        let n = Vec3::new(-hx, 1.0, -hz).normalize();
        assert!(up.dot(n) > 0.9999, "up {up} along the normal {n}");
        assert!(up.y < 0.99, "it leans ({up})");
        // Its front keeps its yaw, as far as the slope allows.
        let front = turn * Vec3::Z;
        let want = Quat::from_rotation_y(0.7) * Vec3::Z;
        assert!(Vec2::new(front.x, front.z).normalize().dot(Vec2::new(want.x, want.z)) > 0.95);
        // On level ground (a plan's level) it stands straight.
        let mut level = None;
        'find: for j in (40..land.size - 40).step_by(3) {
            for i in (40..land.size - 40).step_by(3) {
                let (x, z) = (i as f32, j as f32);
                if land.height(x, z) > 1.0 && slope(x, z) < 1e-6 {
                    level = Some(Vec2::new(x, z));
                    break 'find;
                }
            }
        }
        let (_, t) = on_slope(&land, level.expect("level ground on Cullet"), 0.3);
        assert!((t * Vec3::Y).abs_diff_eq(Vec3::Y, 1e-5) && (t * Vec3::Z).abs_diff_eq(Quat::from_rotation_y(0.3) * Vec3::Z, 1e-5));
        // Cullet's environment draws its plan's trees from the Hanger's folder; nothing else.
        let def: crate::envs::EnvDef = serde_json::from_str(include_str!("../assets/envs/cullet.json")).unwrap();
        assert_eq!(def.resources.get("tree").map(String::as_str), Some("hanger_tree"));
        assert_eq!(def.resources.len(), 1);
        assert!(land.plans.iter().flat_map(|p| p.resources.iter()).filter(|r| r.kind == "tree").count() >= 50, "the Hanger's trees are laid on the land");
        let files: Vec<String> = (1..=6).map(|i| format!("envs/cullet/hanger_tree/hanger_tree_{i}.glb")).collect();
        let picked: std::collections::HashSet<String> = (0..70).filter_map(|i| resource_file(&files, i)).collect();
        assert!(picked.len() >= 4 && picked.iter().all(|f| files.contains(f)), "{picked:?}");
        assert_eq!(resource_file(&files, 5), resource_file(&files, 5));
        assert_eq!(resource_file(&[], 5), None);
    }

    /// A structure on a planned lot building's own blocked floor (since `hearth-1`, a household's
    /// hearth and store, about 0.5 m behind the front wall) is indoors of that lot; the street in
    /// front of it, and open lots, are not.
    #[test]
    fn a_point_on_a_buildings_own_blocked_floor_is_indoors_of_its_lot() {
        let (land, params) = cullet();
        let (map, _) = living_rules::host::hosted_map(&land, &params);
        let mut houses = 0;
        for (i, l) in land.lots.iter().enumerate() {
            if !land.settlements[l.settlement as usize].planned {
                continue;
            }
            let (c, f) = (Vec2::new(l.centre.0, l.centre.1), Vec2::new(l.front.0, l.front.1).normalize_or(Vec2::Y));
            // Behind the front wall's face, on the lot's own floor.
            let inside = c + f * (l.depth_m * 0.5 - 0.5);
            let street = c + f * (l.depth_m * 0.5 + 1.5);
            if l.height_m > 0.0 {
                if !map.at(inside.x, inside.y).walkable() {
                    assert_eq!(indoors_of(&land, &map, inside), Some(i as u32), "lot {i}: behind its front wall");
                    houses += 1;
                }
                assert_ne!(indoors_of(&land, &map, street), Some(i as u32), "lot {i}: its street is not inside it");
            } else {
                assert_eq!(indoors_of(&land, &map, c), None, "open lot {i}");
            }
        }
        assert!(houses >= 40, "{houses} buildings");
        // A land without plans has no lot buildings to be inside.
        let gen = living_rules::land::generate(7, 512, &LandParams::default());
        let (gmap, _) = living_rules::host::hosted_map(&gen, &LandParams::default());
        for l in &gen.lots {
            assert_eq!(indoors_of(&gen, &gmap, Vec2::new(l.centre.0, l.centre.1)), None);
        }
    }
}
