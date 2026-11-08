//! The authority's flat tile world drawn in 3D. Simulation (x, y) in tiles maps to Bevy
//! (x, 0, y): +X east, +Z south, +Y up. Terrain is one vertex-coloured mesh per 16×16 chunk,
//! built near the player under a per-frame budget; creatures, resources and structures are
//! entities mirrored from the subscribed rows.

use crate::net::Net;
use crate::sync::{ServerClock, Tracks};
use bevy::asset::RenderAssetUsages;
use bevy::mesh::{Indices, PrimitiveTopology};
use bevy::prelude::*;
use living_bindings::*;
use living_rules::map::{chunk_xy, Terrain, CHUNK};
use spacetimedb_sdk::Table;
use std::collections::{HashMap, HashSet};

/// Chunks within this distance (tiles) of the player are built; beyond 1.5× they are dropped.
const BUILD_R: f32 = 56.0;
const CHUNKS_PER_FRAME: usize = 6;

pub fn to3(x: f32, y: f32) -> Vec3 {
    Vec3::new(x, 0.0, y)
}

#[derive(Resource, Default)]
pub struct Palette {
    terrain: Handle<StandardMaterial>,
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

/// Display-side state: the authority clock as shown, body tracks and spawned entities.
#[derive(Default)]
pub struct Scene {
    pub clock: ServerClock,
    pub tracks: Tracks,
    /// Displayed position (sim tiles) and heading of every subscribed body.
    pub shown: HashMap<u32, (Vec2, Option<f32>)>,
    pub now_ms: f64,
    chunks: HashMap<u32, Entity>,
    creatures: HashMap<u32, Entity>,
    things: HashMap<(u8, u64), Entity>,
}

#[derive(Component)]
pub struct Creature;

pub fn setup(mut commands: Commands, mut mats: ResMut<Assets<StandardMaterial>>, mut palette: ResMut<Palette>) {
    palette.terrain = mats.add(StandardMaterial { base_color: Color::WHITE, perceptual_roughness: 0.95, ..default() });
    commands.insert_resource(GlobalAmbientLight { color: Color::srgb(0.75, 0.8, 0.95), brightness: 350.0, ..default() });
    commands.spawn((
        DirectionalLight { illuminance: 9_000.0, shadow_maps_enabled: true, ..default() },
        Transform::from_xyz(-30.0, 60.0, 20.0).looking_at(Vec3::ZERO, Vec3::Y),
        bevy::light::CascadeShadowConfigBuilder { first_cascade_far_bound: 25.0, maximum_distance: 120.0, ..default() }.build(),
    ));
}

/// Build terrain chunks near the player and drop far ones.
pub fn terrain(mut commands: Commands, net: NonSend<Net>, mut scene: NonSendMut<Scene>, mut meshes: ResMut<Assets<Mesh>>, palette: Res<Palette>) {
    let Some(conn) = &net.conn else { return };
    let center = net.my_id.and_then(|id| scene.shown.get(&id)).map(|(p, _)| *p);
    let Some(center) = center else { return };
    let (w, h) = net.map_size();
    let dist = |id: u32| {
        let (cx, cy) = chunk_xy(id);
        let c = Vec2::new((cx * CHUNK) as f32 + 8.0, (cy * CHUNK) as f32 + 8.0);
        c.distance(center)
    };
    scene.chunks.retain(|id, e| {
        let keep = dist(*id) < BUILD_R * 1.5;
        if !keep {
            commands.entity(*e).despawn();
        }
        keep
    });
    let mut todo: Vec<(f32, TerrainChunk)> = conn
        .db
        .terrain_chunk()
        .iter()
        .filter(|c| !scene.chunks.contains_key(&c.id))
        .map(|c| (dist(c.id), c))
        .filter(|(d, _)| *d < BUILD_R)
        .collect();
    todo.sort_by(|a, b| a.0.total_cmp(&b.0));
    for (_, chunk) in todo.into_iter().take(CHUNKS_PER_FRAME) {
        let mesh = meshes.add(chunk_mesh(chunk.id, &chunk.tiles, w, h));
        let e = commands.spawn((Mesh3d(mesh), MeshMaterial3d(palette.terrain.clone()), Transform::default())).id();
        scene.chunks.insert(chunk.id, e);
    }
}

/// Cheap deterministic hash for per-tile variation.
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
    fn quad(&mut self, v: [Vec3; 4], n: Vec3, c: [f32; 4]) {
        let b = self.pos.len() as u32;
        for p in v {
            self.pos.push(p.into());
            self.nrm.push(n.into());
            self.col.push(c);
        }
        self.idx.extend_from_slice(&[b, b + 1, b + 2, b, b + 2, b + 3]);
    }

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

    /// An axis-aligned box from `lo` to `hi` (no bottom face).
    fn block(&mut self, lo: Vec3, hi: Vec3, top: [f32; 4], side: [f32; 4]) {
        let (a, b) = (lo, hi);
        self.quad([Vec3::new(a.x, b.y, a.z), Vec3::new(a.x, b.y, b.z), Vec3::new(b.x, b.y, b.z), Vec3::new(b.x, b.y, a.z)], Vec3::Y, top);
        self.quad([Vec3::new(a.x, a.y, b.z), Vec3::new(b.x, a.y, b.z), Vec3::new(b.x, b.y, b.z), Vec3::new(a.x, b.y, b.z)], Vec3::Z, side);
        self.quad([Vec3::new(b.x, a.y, a.z), Vec3::new(a.x, a.y, a.z), Vec3::new(a.x, b.y, a.z), Vec3::new(b.x, b.y, a.z)], -Vec3::Z, side);
        self.quad([Vec3::new(b.x, a.y, b.z), Vec3::new(b.x, a.y, a.z), Vec3::new(b.x, b.y, a.z), Vec3::new(b.x, b.y, b.z)], Vec3::X, side);
        self.quad([Vec3::new(a.x, a.y, a.z), Vec3::new(a.x, a.y, b.z), Vec3::new(a.x, b.y, b.z), Vec3::new(a.x, b.y, a.z)], -Vec3::X, side);
    }

    /// A pyramid (tree crown): `sides`-gon base at `y0` of radius `r`, apex at `y1`.
    fn cone(&mut self, c: Vec3, r: f32, y0: f32, y1: f32, sides: u32, col: [f32; 4]) {
        let apex = Vec3::new(c.x, y1, c.z);
        for i in 0..sides {
            let a0 = i as f32 / sides as f32 * std::f32::consts::TAU;
            let a1 = (i + 1) as f32 / sides as f32 * std::f32::consts::TAU;
            let p0 = Vec3::new(c.x + r * a0.cos(), y0, c.z + r * a0.sin());
            let p1 = Vec3::new(c.x + r * a1.cos(), y0, c.z + r * a1.sin());
            let shade = 0.85 + 0.15 * (a0 + 0.8).sin();
            self.tri([p1, p0, apex], scale(col, shade));
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

fn rgb(r: u8, g: u8, b: u8) -> [f32; 4] {
    let l = |c: u8| Color::srgb_u8(c, c, c).to_linear().red;
    [l(r), l(g), l(b), 1.0]
}

fn scale(c: [f32; 4], k: f32) -> [f32; 4] {
    [c[0] * k, c[1] * k, c[2] * k, c[3]]
}

/// Ground top height and colour per terrain kind.
fn ground(t: Terrain) -> (f32, [f32; 4]) {
    match t {
        Terrain::Grass => (0.0, rgb(112, 160, 74)),
        Terrain::Forest => (0.0, rgb(78, 122, 58)),
        Terrain::Water => (-0.28, rgb(52, 108, 156)),
        Terrain::Sand => (0.0, rgb(214, 196, 140)),
        Terrain::Rock => (0.9, rgb(126, 124, 120)),
        Terrain::Dirt => (0.0, rgb(150, 118, 82)),
        Terrain::Road => (0.03, rgb(176, 156, 120)),
        Terrain::Wall => (1.4, rgb(120, 92, 64)),
    }
}

fn chunk_mesh(id: u32, tiles: &[u8], w: u32, h: u32) -> Mesh {
    let (cx, cy) = chunk_xy(id);
    let mut m = MeshBuf::default();
    for (k, b) in tiles.iter().enumerate() {
        let (i, j) = (k as u32 % CHUNK, k as u32 / CHUNK);
        let (x, y) = (cx * CHUNK + i, cy * CHUNK + j);
        if x >= w || y >= h {
            continue;
        }
        let t = Terrain::from_u8(*b);
        let (top, col) = ground(t);
        let v = hash(x, y);
        let col = scale(col, 0.92 + 0.12 * v);
        let (x0, z0) = (x as f32, y as f32);
        // Every tile is a block down to the water bed, so shores and cliffs get sides.
        m.block(Vec3::new(x0, -0.35, z0), Vec3::new(x0 + 1.0, top, z0 + 1.0), col, scale(col, 0.7));
        if t == Terrain::Forest {
            let c = Vec3::new(x0 + 0.3 + 0.4 * v, 0.0, z0 + 0.3 + 0.4 * hash(y, x));
            let tall = 1.3 + 0.8 * hash(x + 7, y + 3);
            m.block(c - Vec3::new(0.07, 0.0, 0.07), c + Vec3::new(0.07, 0.5, 0.07), rgb(96, 70, 46), rgb(86, 62, 40));
            m.cone(c, 0.48, 0.35, 0.35 + tall, 6, scale(rgb(46, 98, 52), 0.85 + 0.25 * v));
        }
    }
    m.build()
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
        let at = to3(p.x, p.y);
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
    // Resources (tag 0) and structures (tag 1): static, spawned once per row.
    let mut seen: HashSet<(u8, u64)> = HashSet::new();
    let (resources, structures) = (conn.db.resource_node(), conn.db.structure());
    let rows = resources
        .iter()
        .map(|r| ((0u8, r.id), r.kind, r.x, r.y, (r.amount / r.max.max(1.0)).clamp(0.3, 1.0)))
        .chain(structures.iter().map(|s| ((1u8, s.id), s.kind, s.x, s.y, 1.0)));
    for (key, kind, x, y, fill) in rows {
        seen.insert(key);
        if scene.things.contains_key(&key) {
            continue;
        }
        let (mesh, size, color, glow) = look(&kind);
        let mesh = palette.mesh(&mut meshes, mesh, || shape(mesh));
        let mat = palette.color(&mut mats, color, glow);
        let e = commands.spawn((Mesh3d(mesh), MeshMaterial3d(mat), Transform::from_translation(to3(x, y)).with_scale(size * fill))).id();
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
