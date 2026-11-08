//! The authority's flat tile world drawn in 3D. Simulation (x, y) in tiles maps to Bevy
//! (x, height, y): +X east, +Z south, +Y up. The ground is a heightfield from the shared
//! `living_rules::height::ground` function, so characters stand on the drawn surface; each
//! 16×16 chunk gets a ground mesh (two samples per tile, colours blended between tile kinds
//! and darkened on slopes), a props mesh (boulders on rock, built walls) and a water plane.
//! Trees are entities sharing two meshes, so the ones between the camera and the player can
//! fade. Creatures, resources and structures mirror the subscribed rows.

use crate::net::Net;
use crate::sync::{ServerClock, Tracks};
use bevy::asset::RenderAssetUsages;
use bevy::mesh::{Indices, PrimitiveTopology};
use bevy::prelude::*;
use living_bindings::*;
use living_rules::height::{self, WATER_LEVEL};
use living_rules::map::{chunk_xy, Map, Terrain, CHUNK};
use spacetimedb_sdk::Table;
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, OnceLock};

const CHUNKS_PER_FRAME: usize = 3;
/// Ground samples per tile edge.
const RES: u32 = 2;

/// How far (tiles) terrain is drawn; the camera widens it when it comes down toward the horizon.
#[derive(Resource)]
pub struct Draw {
    pub radius: f32,
}

impl Default for Draw {
    fn default() -> Self {
        Self { radius: 56.0 }
    }
}

#[derive(Resource, Default)]
pub struct Palette {
    terrain: Handle<StandardMaterial>,
    water: Handle<StandardMaterial>,
    pub tree: Handle<StandardMaterial>,
    pub tree_faded: Handle<StandardMaterial>,
    trees: [Handle<Mesh>; 2],
    colors: HashMap<u32, Handle<StandardMaterial>>,
    meshes: HashMap<&'static str, Handle<Mesh>>,
}

impl Palette {
    pub fn color(&mut self, mats: &mut Assets<StandardMaterial>, c: [u8; 3], emissive: bool) -> Handle<StandardMaterial> {
        let key = (c[0] as u32) << 16 | (c[1] as u32) << 8 | c[2] as u32 | (emissive as u32) << 24;
        self.colors
            .entry(key)
            .or_insert_with(|| {
                let base = Color::srgb_u8(c[0], c[1], c[2]);
                mats.add(StandardMaterial {
                    base_color: base,
                    perceptual_roughness: 0.85,
                    emissive: if emissive { LinearRgba::from(base) * 4.0 } else { LinearRgba::BLACK },
                    ..default()
                })
            })
            .clone()
    }

    fn mesh(&mut self, meshes: &mut Assets<Mesh>, name: &'static str, make: impl FnOnce() -> Mesh) -> Handle<Mesh> {
        self.meshes.entry(name).or_insert_with(|| meshes.add(make())).clone()
    }
}

struct ChunkParts {
    entities: Vec<Entity>,
}

/// Display-side state: the authority clock as shown, body tracks, the map and spawned entities.
#[derive(Default)]
pub struct Scene {
    pub clock: ServerClock,
    pub tracks: Tracks,
    /// Displayed position (sim tiles) and heading of every subscribed body.
    pub shown: HashMap<u32, (Vec2, Option<f32>)>,
    pub now_ms: f64,
    map: Option<Arc<Map>>,
    map_rows: usize,
    seed: u64,
    chunks: HashMap<u32, ChunkParts>,
    creatures: HashMap<u32, Entity>,
    things: HashMap<(u8, u64), Entity>,
}

impl Scene {
    /// Drawn ground height at a simulation point (0 before the map is known).
    pub fn ground(&self, x: f32, y: f32) -> f32 {
        self.map.as_ref().map_or(0.0, |m| height::ground(m, self.seed, x, y))
    }

    pub fn at3(&self, x: f32, y: f32) -> Vec3 {
        Vec3::new(x, self.ground(x, y), y)
    }

    /// First point where a ray meets the ground (marching, then refining), if any.
    pub fn ray_ground(&self, origin: Vec3, dir: Vec3) -> Option<Vec3> {
        let (step, max) = (0.25, 400.0);
        let mut prev = origin;
        let mut t = 0.0;
        while t < max {
            t += step;
            let p = origin + dir * t;
            if p.y <= self.ground(p.x, p.z) {
                let (mut lo, mut hi) = (prev, p);
                for _ in 0..12 {
                    let mid = (lo + hi) * 0.5;
                    if mid.y <= self.ground(mid.x, mid.z) {
                        hi = mid;
                    } else {
                        lo = mid;
                    }
                }
                return Some(hi);
            }
            prev = p;
        }
        None
    }
}

#[derive(Component)]
pub struct Creature;

/// A tree that fades when it stands between the camera and the player.
#[derive(Component)]
pub struct Tree;

pub fn setup(mut commands: Commands, mut mats: ResMut<Assets<StandardMaterial>>, mut meshes: ResMut<Assets<Mesh>>, mut palette: ResMut<Palette>) {
    palette.terrain = mats.add(StandardMaterial { base_color: Color::WHITE, perceptual_roughness: 0.95, ..default() });
    palette.water = mats.add(StandardMaterial {
        base_color: Color::srgba(0.18, 0.42, 0.62, 0.72),
        alpha_mode: AlphaMode::Blend,
        perceptual_roughness: 0.08,
        reflectance: 0.6,
        ..default()
    });
    palette.tree = mats.add(StandardMaterial { base_color: Color::WHITE, perceptual_roughness: 0.9, ..default() });
    palette.tree_faded = mats.add(StandardMaterial { base_color: Color::srgba(1.0, 1.0, 1.0, 0.22), alpha_mode: AlphaMode::Blend, perceptual_roughness: 0.9, ..default() });
    palette.trees = [meshes.add(tree_mesh(false)), meshes.add(tree_mesh(true))];
    commands.insert_resource(GlobalAmbientLight { color: Color::srgb(0.75, 0.8, 0.95), brightness: 420.0, ..default() });
    commands.spawn((
        DirectionalLight { illuminance: 9_000.0, shadow_maps_enabled: true, ..default() },
        Transform::from_xyz(-30.0, 60.0, 20.0).looking_at(Vec3::ZERO, Vec3::Y),
        bevy::light::CascadeShadowConfigBuilder { first_cascade_far_bound: 25.0, maximum_distance: 140.0, ..default() }.build(),
    ));
}

/// Keep the map in step with the terrain rows, build chunks near the player, drop far ones.
pub fn terrain(mut commands: Commands, net: NonSend<Net>, mut scene: NonSendMut<Scene>, mut meshes: ResMut<Assets<Mesh>>, palette: Res<Palette>, draw: Res<Draw>) {
    let Some(conn) = &net.conn else { return };
    let rows = conn.db.terrain_chunk().count() as usize;
    let seed = conn.db.world().iter().next().map_or(0, |w| w.seed);
    if rows != scene.map_rows || seed != scene.seed {
        let (w, h) = net.map_size();
        scene.map = Some(Arc::new(Map::from_chunks(w, h, conn.db.terrain_chunk().iter().map(|c| (c.id, c.tiles)))));
        scene.map_rows = rows;
        scene.seed = seed;
        for (_, parts) in scene.chunks.drain() {
            for e in parts.entities {
                commands.entity(e).despawn();
            }
        }
    }
    let Some(map) = scene.map.clone() else { return };
    let center = net.my_id.and_then(|id| scene.shown.get(&id)).map(|(p, _)| *p);
    let Some(center) = center else { return };
    let dist = |id: u32| {
        let (cx, cy) = chunk_xy(id);
        Vec2::new((cx * CHUNK) as f32 + 8.0, (cy * CHUNK) as f32 + 8.0).distance(center)
    };
    let radius = draw.radius;
    scene.chunks.retain(|id, parts| {
        let keep = dist(*id) < radius * 1.3 + 12.0;
        if !keep {
            for e in &parts.entities {
                commands.entity(*e).despawn();
            }
        }
        keep
    });
    let mut todo: Vec<(f32, u32)> = map.chunks().filter(|id| !scene.chunks.contains_key(id)).map(|id| (dist(id), id)).filter(|(d, _)| *d < radius).collect();
    todo.sort_by(|a, b| a.0.total_cmp(&b.0));
    for (_, id) in todo.into_iter().take(CHUNKS_PER_FRAME) {
        let parts = build_chunk(&mut commands, &mut meshes, &palette, &map, scene.seed, id);
        scene.chunks.insert(id, parts);
    }
}

/// Cheap deterministic hash for per-object variation.
fn hash(x: u32, y: u32) -> f32 {
    let mut h = x.wrapping_mul(0x9E37_79B1) ^ y.wrapping_mul(0x85EB_CA77);
    h ^= h >> 15;
    h = h.wrapping_mul(0x2C1B_3C6D);
    h ^= h >> 12;
    (h & 0xFFFF) as f32 / 65535.0
}

#[derive(Default)]
struct MeshBuf {
    pos: Vec<[f32; 3]>,
    nrm: Vec<[f32; 3]>,
    col: Vec<[f32; 4]>,
    idx: Vec<u32>,
}

impl MeshBuf {
    fn tri(&mut self, v: [Vec3; 3], c: [f32; 4]) {
        let n = (v[1] - v[0]).cross(v[2] - v[0]).normalize_or_zero();
        let b = self.pos.len() as u32;
        for p in v {
            self.pos.push(p.into());
            self.nrm.push(n.into());
            self.col.push(c);
        }
        self.idx.extend_from_slice(&[b, b + 1, b + 2]);
    }

    fn quad(&mut self, v: [Vec3; 4], c: [f32; 4]) {
        self.tri([v[0], v[1], v[2]], c);
        self.tri([v[0], v[2], v[3]], c);
    }

    /// An axis-aligned box from `lo` to `hi` (no bottom face).
    fn block(&mut self, a: Vec3, b: Vec3, top: [f32; 4], side: [f32; 4]) {
        self.quad([Vec3::new(a.x, b.y, a.z), Vec3::new(a.x, b.y, b.z), Vec3::new(b.x, b.y, b.z), Vec3::new(b.x, b.y, a.z)], top);
        self.quad([Vec3::new(a.x, a.y, b.z), Vec3::new(b.x, a.y, b.z), Vec3::new(b.x, b.y, b.z), Vec3::new(a.x, b.y, b.z)], side);
        self.quad([Vec3::new(b.x, a.y, a.z), Vec3::new(a.x, a.y, a.z), Vec3::new(a.x, b.y, a.z), Vec3::new(b.x, b.y, a.z)], side);
        self.quad([Vec3::new(b.x, a.y, b.z), Vec3::new(b.x, a.y, a.z), Vec3::new(b.x, b.y, a.z), Vec3::new(b.x, b.y, b.z)], side);
        self.quad([Vec3::new(a.x, a.y, a.z), Vec3::new(a.x, a.y, b.z), Vec3::new(a.x, b.y, b.z), Vec3::new(a.x, b.y, a.z)], side);
    }

    /// A cone-ish crown: `sides`-gon base at `y0` of radius `r`, apex at `y1`.
    fn cone(&mut self, c: Vec3, r: f32, y0: f32, y1: f32, sides: u32, col: [f32; 4]) {
        let apex = Vec3::new(c.x, y1, c.z);
        for i in 0..sides {
            let a0 = i as f32 / sides as f32 * std::f32::consts::TAU;
            let a1 = (i + 1) as f32 / sides as f32 * std::f32::consts::TAU;
            let p0 = Vec3::new(c.x + r * a0.cos(), y0, c.z + r * a0.sin());
            let p1 = Vec3::new(c.x + r * a1.cos(), y0, c.z + r * a1.sin());
            self.tri([p1, p0, apex], scale(col, 0.85 + 0.15 * (a0 + 0.8).sin()));
            self.tri([p0, p1, c + Vec3::Y * y0], scale(col, 0.6));
        }
    }

    /// A lumpy low-poly boulder: an icosphere with each vertex pushed in or out.
    fn boulder(&mut self, c: Vec3, r: f32, seed: u32, col: [f32; 4]) {
        let (verts, tris) = ico();
        let moved: Vec<Vec3> = verts
            .iter()
            .enumerate()
            .map(|(i, v)| {
                let k = 0.75 + 0.5 * hash(seed, i as u32);
                c + Vec3::new(v.x * r * k, v.y * r * 0.7 * k, v.z * r * k)
            })
            .collect();
        for t in tris {
            let shade = 0.85 + 0.2 * hash(seed + t[0], t[1]);
            self.tri([moved[t[0] as usize], moved[t[1] as usize], moved[t[2] as usize]], scale(col, shade));
        }
    }

    fn build(self) -> Mesh {
        Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::default())
            .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, self.pos)
            .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, self.nrm)
            .with_inserted_attribute(Mesh::ATTRIBUTE_COLOR, self.col)
            .with_inserted_indices(Indices::U32(self.idx))
    }
}

/// Unit icosphere (one subdivision) as vertices and triangles, built once.
fn ico() -> &'static (Vec<Vec3>, Vec<[u32; 3]>) {
    static ICO: OnceLock<(Vec<Vec3>, Vec<[u32; 3]>)> = OnceLock::new();
    ICO.get_or_init(|| {
        let m = Sphere::new(1.0).mesh().ico(1).unwrap();
        let pos: Vec<Vec3> = m.attribute(Mesh::ATTRIBUTE_POSITION).and_then(|a| a.as_float3()).unwrap_or(&[]).iter().map(|p| Vec3::from(*p)).collect();
        let idx: Vec<u32> = match m.indices() {
            Some(Indices::U32(v)) => v.clone(),
            Some(Indices::U16(v)) => v.iter().map(|i| *i as u32).collect(),
            None => Vec::new(),
        };
        (pos, idx.chunks(3).map(|t| [t[0], t[1], t[2]]).collect())
    })
}

fn rgb(r: u8, g: u8, b: u8) -> [f32; 4] {
    let l = |c: u8| Color::srgb_u8(c, c, c).to_linear().red;
    [l(r), l(g), l(b), 1.0]
}

fn scale(c: [f32; 4], k: f32) -> [f32; 4] {
    [c[0] * k, c[1] * k, c[2] * k, c[3]]
}

fn mix(a: [f32; 4], b: [f32; 4], t: f32) -> [f32; 4] {
    [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, 1.0]
}

fn ground_color(t: Terrain) -> [f32; 4] {
    match t {
        Terrain::Grass => rgb(112, 160, 74),
        Terrain::Forest => rgb(70, 112, 52),
        Terrain::Water => rgb(150, 140, 100),
        Terrain::Sand => rgb(214, 196, 140),
        Terrain::Rock => rgb(130, 126, 118),
        Terrain::Dirt => rgb(150, 118, 82),
        Terrain::Road => rgb(176, 156, 120),
        Terrain::Wall => rgb(140, 120, 90),
    }
}

/// Two tree shapes along +Y from the origin: a pine (stacked cones) and a broadleaf.
fn tree_mesh(broadleaf: bool) -> Mesh {
    let mut m = MeshBuf::default();
    let trunk = rgb(96, 70, 46);
    m.block(Vec3::new(-0.07, 0.0, -0.07), Vec3::new(0.07, 0.7, 0.07), trunk, scale(trunk, 0.85));
    if broadleaf {
        m.boulder(Vec3::Y * 1.25, 0.62, 11, rgb(74, 128, 58));
        m.boulder(Vec3::new(0.25, 1.0, 0.15), 0.42, 23, rgb(66, 118, 52));
    } else {
        let green = rgb(44, 96, 54);
        m.cone(Vec3::ZERO, 0.55, 0.45, 1.35, 7, green);
        m.cone(Vec3::ZERO, 0.42, 0.95, 1.8, 7, scale(green, 1.06));
        m.cone(Vec3::ZERO, 0.28, 1.4, 2.2, 7, scale(green, 1.12));
    }
    m.build()
}

fn build_chunk(commands: &mut Commands, meshes: &mut Assets<Mesh>, palette: &Palette, map: &Map, seed: u64, id: u32) -> ChunkParts {
    let (cx, cy) = chunk_xy(id);
    let (x0, y0) = ((cx * CHUNK) as f32, (cy * CHUNK) as f32);
    let tiles_w = CHUNK.min(map.w - cx * CHUNK);
    let tiles_h = CHUNK.min(map.h - cy * CHUNK);
    let (nx, ny) = (tiles_w * RES + 1, tiles_h * RES + 1);
    let step = 1.0 / RES as f32;
    let g = |x: f32, y: f32| height::ground(map, seed, x, y);
    // Heights with a one-sample border for normals.
    let (bw, bh) = (nx + 2, ny + 2);
    let mut hs = Vec::with_capacity((bw * bh) as usize);
    for j in 0..bh {
        for i in 0..bw {
            hs.push(g(x0 + (i as f32 - 1.0) * step, y0 + (j as f32 - 1.0) * step));
        }
    }
    let at = |i: u32, j: u32| hs[((j + 1) * bw + i + 1) as usize];
    let hb = |i: i32, j: i32| hs[((j + 1) as u32 * bw + (i + 1) as u32) as usize];
    let mut ground = MeshBuf::default();
    for j in 0..ny {
        for i in 0..nx {
            let (x, y) = (x0 + i as f32 * step, y0 + j as f32 * step);
            let h = at(i, j);
            let (ii, jj) = (i as i32, j as i32);
            let dx = (hb(ii + 1, jj) - hb(ii - 1, jj)) / (2.0 * step);
            let dz = (hb(ii, jj + 1) - hb(ii, jj - 1)) / (2.0 * step);
            let n = Vec3::new(-dx, 1.0, -dz).normalize();
            let mut c = [0.0, 0.0, 0.0, 1.0];
            height::blend(map, x, y, |t, w| {
                let tc = ground_color(t);
                for k in 0..3 {
                    c[k] += tc[k] * w;
                }
            });
            // Steep ground shows bare rock; ground under water darkens with depth.
            let steep = ((0.9 - n.y) / 0.25).clamp(0.0, 1.0);
            c = mix(c, rgb(118, 112, 104), steep);
            if h < WATER_LEVEL {
                c = mix(c, rgb(60, 80, 90), ((WATER_LEVEL - h) / 1.0).clamp(0.0, 0.7));
            }
            c = scale(c, 0.94 + 0.1 * hash(x.to_bits(), y.to_bits()));
            ground.pos.push([x, h, y]);
            ground.nrm.push(n.into());
            ground.col.push(c);
        }
    }
    for j in 0..ny - 1 {
        for i in 0..nx - 1 {
            let a = j * nx + i;
            let (b, c, d) = (a + 1, a + nx, a + nx + 1);
            ground.idx.extend_from_slice(&[a, c, b, b, c, d]);
        }
    }
    let mut entities = vec![commands.spawn((Mesh3d(meshes.add(ground.build())), MeshMaterial3d(palette.terrain.clone()), Transform::default())).id()];

    let mut props = MeshBuf::default();
    let mut water = false;
    for j in 0..tiles_h {
        for i in 0..tiles_w {
            let (tx, ty) = (cx * CHUNK + i, cy * CHUNK + j);
            let t = map.get(tx as i32, ty as i32);
            let v = hash(tx, ty);
            let (px, py) = (tx as f32 + 0.25 + 0.5 * v, ty as f32 + 0.25 + 0.5 * hash(ty, tx));
            match t {
                Terrain::Water => water = true,
                Terrain::Forest => {
                    let p = Vec3::new(px, g(px, py) - 0.05, py);
                    let size = 0.8 + 0.5 * hash(tx + 7, ty + 3);
                    let broad = hash(tx + 1, ty + 9) < 0.3;
                    let tf = Transform::from_translation(p).with_rotation(Quat::from_rotation_y(v * 6.28)).with_scale(Vec3::splat(size));
                    entities.push(commands.spawn((Tree, Mesh3d(palette.trees[broad as usize].clone()), MeshMaterial3d(palette.tree.clone()), tf)).id());
                }
                // Boulders only inside rock (all eight neighbours rock) and within their own
                // tile, so they never stand on or overhang ground a character can walk on.
                Terrain::Rock if v < 0.6 && rock_inside(map, tx as i32, ty as i32) => {
                    let r = 0.35 + 0.2 * hash(tx + 3, ty + 1);
                    let (bx, by) = (tx as f32 + 0.5 + (v - 0.5) * 0.2, ty as f32 + 0.5 + (hash(ty, tx) - 0.5) * 0.2);
                    props.boulder(Vec3::new(bx, g(bx, by) + r * 0.1, by), r, tx * 31 + ty, rgb(128, 124, 116));
                }
                Terrain::Wall => {
                    let (fx, fy) = (tx as f32, ty as f32);
                    let base = g(fx + 0.5, fy + 0.5);
                    props.block(Vec3::new(fx, base - 0.4, fy), Vec3::new(fx + 1.0, base + 1.4, fy + 1.0), rgb(120, 92, 64), rgb(104, 80, 56));
                }
                _ => {}
            }
        }
    }
    if !props.pos.is_empty() {
        entities.push(commands.spawn((Mesh3d(meshes.add(props.build())), MeshMaterial3d(palette.terrain.clone()), Transform::default())).id());
    }
    if water {
        let (w, h) = (tiles_w as f32, tiles_h as f32);
        let plane = Plane3d::default().mesh().size(w, h).build().translated_by(Vec3::new(x0 + w / 2.0, WATER_LEVEL, y0 + h / 2.0));
        entities.push(commands.spawn((Mesh3d(meshes.add(plane)), MeshMaterial3d(palette.water.clone()), Transform::default())).id());
    }
    ChunkParts { entities }
}

fn rock_inside(map: &Map, x: i32, y: i32) -> bool {
    (-1..=1).all(|j| (-1..=1).all(|i| map.get(x + i, y + j) == Terrain::Rock))
}

/// What a resource or structure row looks like: mesh name, size, colour, glow.
fn look(kind: &str) -> (&'static str, Vec3, [u8; 3], bool) {
    match kind {
        "berry_bush" => ("ball", Vec3::splat(0.55), [150, 60, 90], false),
        "fish" | "fishing_spot" => ("disc", Vec3::new(0.7, 0.05, 0.7), [150, 200, 230], false),
        "tree" | "wood" => ("ball", Vec3::splat(0.4), [90, 70, 40], false),
        "flint" | "stone" | "rock" => ("ball", Vec3::splat(0.35), [160, 160, 170], false),
        "campfire" | "fire" | "hearth" | "smoking_fire" => ("box", Vec3::new(0.5, 0.35, 0.5), [255, 140, 40], true),
        "shelter" | "house" | "hut" => ("box", Vec3::new(1.6, 1.1, 1.6), [150, 110, 70], false),
        "hall" | "workshop" | "market" | "inn" | "smokehouse" => ("box", Vec3::new(2.4, 1.4, 2.0), [170, 120, 80], false),
        "storage" | "store" | "storehouse" => ("box", Vec3::new(1.2, 0.9, 1.2), [120, 90, 60], false),
        "gate" => ("box", Vec3::new(1.0, 1.3, 0.3), [110, 80, 50], false),
        _ => ("box", Vec3::splat(0.5), [200, 200, 200], false),
    }
}

fn creature_look(kind: &str, mine: bool) -> (&'static str, Vec3, [u8; 3]) {
    match kind {
        "person" if mine => ("person", Vec3::ONE, [240, 196, 64]),
        "person" => ("person", Vec3::ONE, [210, 140, 110]),
        "deer" => ("animal", Vec3::new(1.0, 0.9, 0.8), [160, 110, 60]),
        "wolf" => ("animal", Vec3::new(0.9, 0.8, 0.7), [110, 110, 120]),
        _ => ("animal", Vec3::splat(0.7), [200, 200, 200]),
    }
}

fn shape(name: &'static str) -> Mesh {
    match name {
        "person" => Capsule3d::new(0.22, 0.55).mesh().build().translated_by(Vec3::Y * 0.5),
        // Body along +X (the facing direction) with a head in front.
        "animal" => {
            let mut body = Cuboid::new(0.8, 0.35, 0.3).mesh().build().translated_by(Vec3::Y * 0.45);
            body.merge(&Cuboid::new(0.25, 0.25, 0.22).mesh().build().translated_by(Vec3::new(0.48, 0.65, 0.0))).ok();
            body
        }
        "ball" => Sphere::new(0.5).mesh().ico(2).unwrap().translated_by(Vec3::Y * 0.5),
        "disc" => Cylinder::new(0.5, 1.0).mesh().build().translated_by(Vec3::Y * 0.5),
        _ => Cuboid::new(1.0, 1.0, 1.0).mesh().build().translated_by(Vec3::Y * 0.5),
    }
}

/// Mirror subscribed bodies, resources and structures as entities, with smoothed motion.
#[allow(clippy::too_many_arguments)]
pub fn entities(
    mut commands: Commands,
    net: NonSend<Net>,
    mut scene: NonSendMut<Scene>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut mats: ResMut<Assets<StandardMaterial>>,
    mut palette: ResMut<Palette>,
    mut q: Query<&mut Transform, With<Creature>>,
    time: Res<Time>,
) {
    let Some(conn) = &net.conn else { return };
    let now = scene.clock.frame(net.body_t.swap(0, std::sync::atomic::Ordering::Relaxed));
    scene.now_ms = now;
    let bodies: HashMap<u32, Body> = conn.db.body().iter().map(|b| (b.id, b)).collect();
    let chars: HashMap<u32, Character> = conn.db.character().iter().filter(|c| bodies.contains_key(&c.id)).map(|c| (c.id, c)).collect();
    let scene = &mut *scene;
    scene.tracks.retain(|id| bodies.contains_key(&id));
    scene.shown.retain(|id, _| bodies.contains_key(id));
    let shown = &mut scene.shown;
    scene.tracks.update(bodies.values(), now, time.delta_secs(), |id, p, heading| {
        let prev = shown.get(&id).and_then(|(_, h)| *h);
        shown.insert(id, (Vec2::new(p.x, p.y), heading.or(prev)));
    });
    scene.creatures.retain(|id, e| {
        let keep = bodies.contains_key(id);
        if !keep {
            commands.entity(*e).despawn();
        }
        keep
    });
    for (id, b) in &bodies {
        let Some((p, heading)) = scene.shown.get(id).copied() else { continue };
        let alive = chars.get(id).is_none_or(|c| c.alive);
        // Facing: heading is radians with +x east, +y south; the models face local +X.
        let mut rot = Quat::from_rotation_y(-heading.unwrap_or(b.heading));
        if !alive {
            rot *= Quat::from_rotation_x(std::f32::consts::FRAC_PI_2);
        }
        let at = scene.at3(p.x, p.y);
        if let Some(e) = scene.creatures.get(id) {
            if let Ok(mut t) = q.get_mut(*e) {
                t.translation = at;
                t.rotation = rot;
            }
            continue;
        }
        let (mesh, size, color) = creature_look(&b.kind, Some(*id) == net.my_id);
        let mesh = palette.mesh(&mut meshes, mesh, || shape(mesh));
        let mat = palette.color(&mut mats, color, false);
        let e = commands.spawn((Creature, Mesh3d(mesh), MeshMaterial3d(mat), Transform::from_translation(at).with_rotation(rot).with_scale(size))).id();
        scene.creatures.insert(*id, e);
    }
    // Resources (tag 0) and structures (tag 1): static, spawned once per row (re-placed when
    // the ground under them is first known).
    let mut seen: HashSet<(u8, u64)> = HashSet::new();
    let (resources, structures) = (conn.db.resource_node(), conn.db.structure());
    let rows = resources
        .iter()
        .map(|r| ((0u8, r.id), r.kind, r.x, r.y, (r.amount / r.max.max(1.0)).clamp(0.3, 1.0)))
        .chain(structures.iter().map(|s| ((1u8, s.id), s.kind, s.x, s.y, 1.0)));
    let ready = scene.map.is_some();
    for (key, kind, x, y, fill) in rows {
        seen.insert(key);
        if !ready || scene.things.contains_key(&key) {
            continue;
        }
        let (mesh, size, color, glow) = look(&kind);
        let mesh = palette.mesh(&mut meshes, mesh, || shape(mesh));
        let mat = palette.color(&mut mats, color, glow);
        let at = scene.at3(x, y);
        let e = commands.spawn((Mesh3d(mesh), MeshMaterial3d(mat), Transform::from_translation(at).with_scale(size * fill))).id();
        scene.things.insert(key, e);
    }
    scene.things.retain(|k, e| {
        let keep = seen.contains(k);
        if !keep {
            commands.entity(*e).despawn();
        }
        keep
    });
}

/// Fade trees that stand between the camera and the player's head.
pub fn fade_trees(
    target: Res<crate::controls::Target>,
    palette: Res<Palette>,
    cam: Query<&Transform, (With<Camera3d>, Without<Tree>)>,
    mut trees: Query<(&Transform, &mut MeshMaterial3d<StandardMaterial>), With<Tree>>,
) {
    let (Some(me), Ok(cam)) = (target.0, cam.single()) else { return };
    let head = me + Vec3::Y * 1.0;
    let (a, b) = (cam.translation, head);
    let ab = b - a;
    let len2 = ab.length_squared().max(1e-4);
    for (t, mut mat) in &mut trees {
        let p = t.translation + Vec3::Y * 1.2 * t.scale.y;
        if p.distance_squared(head) > 400.0 {
            if mat.0 != palette.tree {
                mat.0 = palette.tree.clone();
            }
            continue;
        }
        let s = ((p - a).dot(ab) / len2).clamp(0.0, 1.0);
        let near_line = (a + ab * s).distance(p) < 1.3 && s > 0.05 && s < 0.98;
        // Also anything right around the player that rises above them.
        let close = Vec2::new(p.x - me.x, p.z - me.z).length() < 1.4 && t.translation.z > me.z - 0.5;
        let want = if near_line || close { &palette.tree_faded } else { &palette.tree };
        if &mat.0 != want {
            mat.0 = want.clone();
        }
    }
}
