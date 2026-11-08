//! The first world in the look-dev client: the generic km-scale island from
//! `living_rules::land` (docs/FIRST_WORLD.md), walkable with the game camera. Client only; the
//! authority does not host it yet.
//!
//! An environment whose JSON has a `world` section (`assets/envs/island.json`) is the island:
//! its mood lights it, and instead of a ground disc and slots, this module streams the island
//! around you in 64 m chunks:
//! - ground meshes from the island's heights and terrain, with water surfaces at the water's
//!   level (the sea at 0, lakes level, rivers sloping);
//! - each region dressed with its environment's assets (`RegionKind::env`) at that environment's
//!   scatter densities, small things only near you;
//! - each settlement laid out with its environment's slots (`SiteKind::env`) round its centre.
//!
//! `LIVING_GAME_START=x,z` starts you at a point (metres) instead of the town.

use crate::envs::{EnvDef, EnvPart, Occluder};
use crate::lookdev::Model;
use crate::world::{hash, rgb, scale, Palette};
use bevy::asset::RenderAssetUsages;
use bevy::mesh::{Indices, PrimitiveTopology};
use bevy::prelude::*;
use bevy::world_serialization::WorldAssetRoot;
use bevy_mod_outline::OutlineStencil;
use living_rules::land::{Land, RegionKind, SiteKind};
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

/// An environment's `world` section.
#[derive(Deserialize, Clone, Copy, Debug)]
pub struct WorldDef {
    pub seed: u64,
    pub size: u32,
}

/// One placed thing: an asset file (or none) of a kind at a point.
#[derive(Clone)]
struct Item {
    kind: String,
    file: String,
    at: Vec2,
    yaw: f32,
    height: f32,
    glow: Option<[f32; 3]>,
    k: usize,
}

#[derive(Resource)]
pub struct Island {
    pub land: Arc<Land>,
    /// Environments by id, for region and site dressing.
    envs: HashMap<String, EnvDef>,
    /// Settlement things, by chunk.
    site_items: HashMap<(i32, i32), Vec<Item>>,
    /// Loaded chunks: ground (with water) and big things; small things separately.
    ground: HashMap<(i32, i32), Vec<Entity>>,
    small: HashMap<(i32, i32), Vec<Entity>>,
    pub start: Vec2,
}

impl Island {
    pub fn new(world: WorldDef, defs: &[EnvDef]) -> Self {
        let t0 = std::time::Instant::now();
        let land = Arc::new(living_rules::land::generate_default(world.seed, world.size));
        let envs: HashMap<String, EnvDef> = defs.iter().map(|d| (d.id.clone(), d.clone())).collect();
        let town = land.sites.iter().find(|s| s.kind == SiteKind::Town).map(|s| Vec2::new(s.x, s.y));
        let start = std::env::var("LIVING_GAME_START")
            .ok()
            .and_then(|s| {
                let (x, z) = s.split_once(',')?;
                Some(Vec2::new(x.trim().parse().ok()?, z.trim().parse().ok()?))
            })
            .or(town)
            .unwrap_or(Vec2::splat(world.size as f32 / 2.0));
        let mut site_items: HashMap<(i32, i32), Vec<Item>> = HashMap::new();
        for (n, site) in land.sites.iter().enumerate() {
            if site.kind == SiteKind::Cave {
                continue;
            }
            let Some(def) = envs.get(site.kind.env()) else { continue };
            let centre = Vec2::new(site.x, site.y);
            let limit = site.radius_m.min(def.ground.radius).max(8.0);
            let mut taken = vec![(Vec2::ZERO, 2.0)];
            for (si, slot) in def.slots.iter().enumerate() {
                let files = crate::envs::assets_for(&def.id, &slot.kind);
                if files.is_empty() {
                    continue;
                }
                for (k, pl) in crate::envs::place(slot, si + n * 31, &mut taken, limit).iter().enumerate() {
                    let at = centre + pl.at;
                    if !land.map.at(at.x, at.y).walkable() {
                        continue;
                    }
                    let file = files[(hash(si as u32 * 31 + k as u32, 5 + n as u32) * files.len() as f32) as usize % files.len()].clone();
                    let item = Item { kind: slot.kind.clone(), file, at, yaw: pl.yaw, height: pl.height, glow: slot.glow, k };
                    site_items.entry(chunk_of(at)).or_default().push(item);
                }
            }
        }
        info!(
            "island: seed {} {} m in {:.2} s, {} regions, {} sites, start ({:.0}, {:.0})",
            world.seed,
            world.size,
            t0.elapsed().as_secs_f32(),
            land.regions.len(),
            land.sites.len(),
            start.x,
            start.y
        );
        Self { land, envs, site_items, ground: HashMap::new(), small: HashMap::new(), start }
    }

    /// Height of the ground (game x, z).
    pub fn height(&self, x: f32, z: f32) -> f32 {
        self.land.height(x, z)
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
        let mut ids: Vec<&str> = RegionKind::ALL.iter().filter_map(|k| k.env()).collect();
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
                    if kind.env() != Some(*id) || !self.land.map.at(at.x, at.y).walkable() || self.in_site(at) {
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
                    out.push(Item { kind: slot.kind.clone(), file, at, yaw: hash(seed ^ 0x33, k) * std::f32::consts::TAU, height, glow: slot.glow, k: k as usize });
                }
            }
        }
        out
    }
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
fn ground_colour(t: Terrain, kind: RegionKind, v: f32) -> [f32; 4] {
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

/// Ground colour averaged over a few metres, so region borders and single tiles blend instead
/// of switching along straight polygon edges.
fn blended_colour(land: &Land, x: f32, z: f32, v: f32) -> [f32; 4] {
    const RING: [(f32, f32); 9] = [(0.0, 0.0), (6.0, 0.0), (-6.0, 0.0), (0.0, 6.0), (0.0, -6.0), (13.0, 9.0), (-13.0, -9.0), (9.0, -13.0), (-9.0, 13.0)];
    let mut acc = [0.0f32; 4];
    for (k, (dx, dz)) in RING.iter().enumerate() {
        // The centre sample counts most; the ring spreads the change over about 25 m.
        let w = if k == 0 { 3.0 } else { 1.0 };
        let (px, pz) = (x + dx, z + dz);
        let c = ground_colour(land.map.at(px + 0.01, pz + 0.01), land.kind_at(px, pz), v);
        for i in 0..4 {
            acc[i] += c[i] * w;
        }
    }
    acc.map(|c| c / 11.0)
}

/// A chunk's ground (indexed 1 m grid, smooth normals) and its water surface.
fn chunk_meshes(land: &Land, c: (i32, i32)) -> (Mesh, Option<Mesh>) {
    let n = CHUNK as usize;
    let (x0, z0) = (c.0 * CHUNK, c.1 * CHUNK);
    let mut pos = Vec::with_capacity((n + 1) * (n + 1));
    let mut col = Vec::with_capacity((n + 1) * (n + 1));
    for j in 0..=n {
        for i in 0..=n {
            let (x, z) = ((x0 + i as i32) as f32, (z0 + j as i32) as f32);
            pos.push([x, land.height(x, z), z]);
            let v = hash((x0 + i as i32) as u32, (z0 + j as i32) as u32);
            col.push(blended_colour(land, x, z, v));
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

fn spawn_item(commands: &mut Commands, assets: &AssetServer, land: &Land, it: &Item) -> Vec<Entity> {
    let y = land.height(it.at.x, it.at.y);
    let at = Vec3::new(it.at.x, y, it.at.y);
    let vrm = it.file.contains("vroid-");
    let model = Model { vrm, file: it.file.clone(), height: it.height, ground_y: y, glow: it.glow };
    let handle = assets.load(GltfAssetLabel::Scene(0).from_asset(it.file.clone()));
    let mut e = commands.spawn((EnvPart, model, WorldAssetRoot(handle), Transform::from_translation(at).with_rotation(Quat::from_rotation_y(it.yaw)), Visibility::Hidden));
    if it.height >= 3.0 {
        e.insert(Occluder { height: it.height });
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
            let (g, w) = chunk_meshes(&land, c);
            let mut es = vec![commands.spawn((EnvPart, Mesh3d(meshes.add(g)), MeshMaterial3d(palette.vertex.clone()), Transform::default(), OutlineStencil::default())).id()];
            if let Some(w) = w {
                es.push(commands.spawn((EnvPart, Mesh3d(meshes.add(w)), MeshMaterial3d(palette.water.clone()), Transform::default())).id());
            }
            let items: Vec<Item> = island.site_items.get(&c).cloned().unwrap_or_default().into_iter().chain(island.wild_items(c)).collect();
            for it in items.iter().filter(|it| it.height > SMALL) {
                es.extend(spawn_item(&mut commands, &assets, &land, it));
            }
            island.ground.insert(c, es);
            built += 1;
        }
        if d <= NEAR && !island.small.contains_key(&c) && island.ground.contains_key(&c) {
            let items: Vec<Item> = island.site_items.get(&c).cloned().unwrap_or_default().into_iter().chain(island.wild_items(c)).collect();
            let es: Vec<Entity> = items.iter().filter(|it| it.height <= SMALL).flat_map(|it| spawn_item(&mut commands, &assets, &land, it)).collect();
            island.small.insert(c, es);
            built += 1;
        }
    }
}
