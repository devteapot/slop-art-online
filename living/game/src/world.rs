//! The authority's flat tile world drawn in 3D, at one metre per tile. Simulation (x, y) maps
//! to Bevy (x, height, y): +X east, +Z south, +Y up. The ground comes from the shared
//! `living_rules::height::Ground` (hills, valleys and mountains derived from the tile map), so
//! characters stand on the drawn surface. Each 16×16 chunk gets a ground mesh (two samples per
//! metre, colours blended between tile kinds, bare rock on slopes), a props mesh (bushes,
//! boulders, built walls) and a water plane. Trees are entities sharing two meshes, so the
//! ones between the camera and the player can fade. Resources and structures mirror their rows;
//! creatures live in `bodies.rs`.

use crate::net::Net;
use crate::style::{outline, Outlined, Style, Toon};
use bevy_mod_outline::OutlineMeshExt;
use crate::sync::{ServerClock, Tracks};
use bevy::asset::RenderAssetUsages;
use bevy::mesh::{Indices, PrimitiveTopology};
use bevy::prelude::*;
use living_bindings::*;
use living_rules::height::{self, Ground, WATER_LEVEL};
use living_rules::map::{chunk_xy, Map, Terrain, CHUNK};
use spacetimedb_sdk::Table;
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, OnceLock};

const CHUNKS_PER_FRAME: usize = 3;
/// Ground samples per metre.
const RES: u32 = 2;

/// How far (metres) terrain is drawn on a tile world, and the current environment's fog.
#[derive(Resource)]
pub struct Draw {
    pub radius: f32,
    /// The current environment's mood fog (start, end), metres for an ordinary adult: the camera
    /// fogs by it (`camera::follow`), and landmarks and the ground under them are drawn out to its
    /// end ([`Draw::landmark_reach`]). None (tile worlds, the character line-up): the camera's own
    /// fog round its draw radius.
    pub fog: Option<(f32, f32)>,
}

impl Default for Draw {
    fn default() -> Self {
        Self { radius: 110.0, fog: None }
    }
}

impl Draw {
    /// Take an environment's mood: its fog distances.
    pub fn mood(&mut self, md: &crate::envs::Mood) {
        self.fog = Some((md.fog_start.max(0.0), md.fog_end.max(md.fog_start + 1.0)));
    }

    /// How far landmarks, and the coarse ground and sea under them, are drawn (m): where the
    /// mood's fog is complete, so nothing appears at that distance. 0 without a mood.
    pub fn landmark_reach(&self) -> f32 {
        self.fog.map_or(0.0, |f| f.1)
    }
}

#[derive(Resource, Default)]
pub struct Palette {
    terrain: Handle<Toon>,
    /// The toon water (water.rs), shared by every water surface.
    pub water: Handle<crate::water::Water>,
    pub vertex: Handle<Toon>,
    pub tree: Handle<Toon>,
    pub tree_faded: Handle<Toon>,
    /// Trees outside sight: remembered, and never seen (perception mock).
    pub tree_dim: [Handle<Toon>; 2],
    trees: [Handle<Mesh>; 2],
    colors: HashMap<u32, Handle<Toon>>,
    /// Resource and structure models by kind: the mesh, and a glowing part with its colour.
    things: HashMap<String, (Handle<Mesh>, Option<(Handle<Mesh>, [u8; 3])>)>,
}

impl Palette {
    pub fn color(&mut self, mats: &mut Assets<Toon>, style: &Style, c: [u8; 3], emissive: bool) -> Handle<Toon> {
        let key = (c[0] as u32) << 16 | (c[1] as u32) << 8 | c[2] as u32 | (emissive as u32) << 24;
        self.colors
            .entry(key)
            .or_insert_with(|| {
                let base = Color::srgb_u8(c[0], c[1], c[2]);
                mats.add(style.toon(StandardMaterial {
                    base_color: base,
                    perceptual_roughness: 0.85,
                    emissive: if emissive { LinearRgba::from(base) * 6.0 } else { LinearRgba::BLACK },
                    ..default()
                }))
            })
            .clone()
    }
}

struct ChunkParts {
    entities: Vec<Entity>,
}

/// Input → drawn, in this client: each movement input paired with my next new segment, and the
/// local ms until it is drawn with my own clock (`mine`) and until the old display time would
/// have reached it (`old`).
#[derive(Default)]
pub struct Latency {
    pub pending: Vec<(u64, std::time::Instant, bool, bool)>,
    pub last_seg: u64,
    pub paired: Option<std::time::Instant>,
    pub mine: Vec<f64>,
    pub old: Vec<f64>,
    /// Display delay behind the newest fresh row, sampled per frame: real clock and shadow.
    pub behind: Vec<f64>,
    pub behind_old: Vec<f64>,
    pub logged_s: f64,
}

/// Display-side state: the authority clock as shown, body tracks, the ground and entities.
#[derive(Default)]
pub struct Scene {
    pub clock: ServerClock,
    /// The display clock fed as before 2026-11-10 (every row, entering bodies included), only
    /// to log beside the real one.
    pub shadow: ServerClock,
    /// Input → my new segment first drawn, measured in this client (`bodies.rs`).
    pub lat: Latency,
    pub tracks: Tracks,
    /// Displayed position (sim metres) and heading of every subscribed body.
    pub shown: HashMap<u32, (Vec2, Option<f32>)>,
    /// Each shown body's speed on its displayed segment (sim m/s, 0 standing).
    pub speeds: HashMap<u32, f32>,
    pub now_ms: f64,
    /// The authority time my own body is drawn at, and my body's newest segment then (`t_ms`,
    /// `next_ms`, speed in m/s), for the feet log (`gait.rs`).
    pub mine_ms: f64,
    pub mine_seg: (u64, u64, f32),
    ground: Option<Arc<Ground>>,
    map_rows: usize,
    seed: u64,
    chunks: HashMap<u32, ChunkParts>,
    pub creatures: HashMap<u32, Entity>,
    things: HashMap<(u8, u64), Entity>,
}

impl Scene {
    /// Drawn ground height at a simulation point (0 before the map is known).
    pub fn ground(&self, x: f32, y: f32) -> f32 {
        self.ground.as_ref().map_or(0.0, |g| g.height(x, y))
    }

    pub fn at3(&self, x: f32, y: f32) -> Vec3 {
        Vec3::new(x, self.ground(x, y), y)
    }

    pub fn ready(&self) -> bool {
        self.ground.is_some()
    }

    /// First point where a ray meets the ground (marching, then refining), if any.
    pub fn ray_ground(&self, origin: Vec3, dir: Vec3) -> Option<Vec3> {
        let (step, max) = (0.5, 600.0);
        let mut prev = origin;
        let mut t = 0.0;
        while t < max {
            t += step;
            let p = origin + dir * t;
            if p.y <= self.ground(p.x, p.z) {
                let (mut lo, mut hi) = (prev, p);
                for _ in 0..14 {
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

/// A resource or structure at a simulation point.
#[derive(Component)]
pub struct Thing(pub Vec2);

/// A tree that fades when it stands between the camera and the player.
#[derive(Component)]
pub struct Tree;

pub fn setup(mut commands: Commands, mut waters: ResMut<Assets<crate::water::Water>>, mut toons: ResMut<Assets<Toon>>, mut meshes: ResMut<Assets<Mesh>>, mut palette: ResMut<Palette>, style: Res<Style>) {
    let white = |r: f32| StandardMaterial { base_color: Color::WHITE, perceptual_roughness: r, ..default() };
    palette.terrain = toons.add(style.toon(white(0.95)));
    palette.vertex = toons.add(style.toon(white(0.85)));
    palette.water = waters.add(crate::water::Water::default());
    palette.tree = toons.add(style.toon(white(0.9)));
    palette.tree_faded = toons.add(style.toon(StandardMaterial { base_color: Color::srgba(1.0, 1.0, 1.0, 0.2), alpha_mode: AlphaMode::Blend, ..white(0.9) }));
    palette.trees = [meshes.add(tree_mesh(false)), meshes.add(tree_mesh(true))];
    palette.tree_dim = [
        toons.add(style.toon(StandardMaterial { base_color: Color::srgb(0.5, 0.5, 0.55), ..white(0.9) })),
        toons.add(style.toon(StandardMaterial { base_color: Color::srgb(0.12, 0.13, 0.16), ..white(1.0) })),
    ];
    // The atmosphere (daylight.rs) sets the ambient light as the sky's fill; its alpha 0 means
    // none, and the toon shader then ignores it.
    commands.insert_resource(GlobalAmbientLight { color: Color::srgba(0.75, 0.8, 0.95, 0.0), brightness: 420.0, ..default() });
    commands.spawn((
        DirectionalLight { color: Color::srgb(1.0, 0.96, 0.88), illuminance: 9_000.0, shadow_maps_enabled: true, ..default() },
        Transform::from_xyz(-30.0, 60.0, 20.0).looking_at(Vec3::ZERO, Vec3::Y),
        // Shadows were the largest single cost (12–18 ms of 19–29 ms on the island): three
        // cascades to 90 m, where the fog has mostly taken over, instead of four to 160 m.
        bevy::light::CascadeShadowConfigBuilder { num_cascades: crate::perf::value("cascades").map_or(3, |n| n as usize), first_cascade_far_bound: 18.0, maximum_distance: crate::perf::value("shadowfar").unwrap_or(90.0), ..default() }.build(),
    ));
}

/// Keep the ground in step with the terrain rows, build chunks near the player, drop far ones.
pub fn terrain(mut commands: Commands, net: NonSend<Net>, mut scene: NonSendMut<Scene>, mut meshes: ResMut<Assets<Mesh>>, palette: Res<Palette>, draw: Res<Draw>) {
    let Some(conn) = &net.conn else { return };
    let rows = conn.db.terrain_chunk().count() as usize;
    let seed = conn.db.world().iter().next().map_or(0, |w| w.seed);
    if rows > 0 && (rows != scene.map_rows || seed != scene.seed) {
        let (w, h) = net.map_size();
        let map = Map::from_chunks(w, h, conn.db.terrain_chunk().iter().map(|c| (c.id, c.tiles)));
        let t0 = std::time::Instant::now();
        scene.ground = Some(Arc::new(Ground::new(&map, seed)));
        info!("ground for a {w}×{h} m map prepared in {:.0} ms", t0.elapsed().as_secs_f32() * 1000.0);
        scene.map_rows = rows;
        scene.seed = seed;
        for (_, parts) in scene.chunks.drain() {
            for e in parts.entities {
                commands.entity(e).despawn();
            }
        }
    }
    let Some(ground) = scene.ground.clone() else { return };
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
    let mut todo: Vec<(f32, u32)> = ground.map().chunks().filter(|id| !scene.chunks.contains_key(id)).map(|id| (dist(id), id)).filter(|(d, _)| *d < radius).collect();
    todo.sort_by(|a, b| a.0.total_cmp(&b.0));
    for (_, id) in todo.into_iter().take(CHUNKS_PER_FRAME) {
        let parts = build_chunk(&mut commands, &mut meshes, &palette, &ground, id);
        scene.chunks.insert(id, parts);
    }
}

/// Cheap deterministic hash for per-object variation.
pub fn hash(x: u32, y: u32) -> f32 {
    let mut h = x.wrapping_mul(0x9E37_79B1) ^ y.wrapping_mul(0x85EB_CA77);
    h ^= h >> 15;
    h = h.wrapping_mul(0x2C1B_3C6D);
    h ^= h >> 12;
    (h & 0xFFFF) as f32 / 65535.0
}

/// Vertex-coloured, flat-shaded mesh building.
#[derive(Default)]
pub struct MeshBuf {
    pos: Vec<[f32; 3]>,
    nrm: Vec<[f32; 3]>,
    col: Vec<[f32; 4]>,
    idx: Vec<u32>,
}

impl MeshBuf {
    pub fn tri(&mut self, v: [Vec3; 3], c: [f32; 4]) {
        let n = (v[1] - v[0]).cross(v[2] - v[0]).normalize_or_zero();
        let b = self.pos.len() as u32;
        for p in v {
            self.pos.push(p.into());
            self.nrm.push(n.into());
            self.col.push(c);
        }
        self.idx.extend_from_slice(&[b, b + 1, b + 2]);
    }

    pub fn quad(&mut self, v: [Vec3; 4], c: [f32; 4]) {
        self.tri([v[0], v[1], v[2]], c);
        self.tri([v[0], v[2], v[3]], c);
    }

    /// An axis-aligned box from `a` to `b` (no bottom face).
    pub fn block(&mut self, a: Vec3, b: Vec3, top: [f32; 4], side: [f32; 4]) {
        self.quad([Vec3::new(a.x, b.y, a.z), Vec3::new(a.x, b.y, b.z), Vec3::new(b.x, b.y, b.z), Vec3::new(b.x, b.y, a.z)], top);
        self.quad([Vec3::new(a.x, a.y, b.z), Vec3::new(b.x, a.y, b.z), Vec3::new(b.x, b.y, b.z), Vec3::new(a.x, b.y, b.z)], side);
        self.quad([Vec3::new(b.x, a.y, a.z), Vec3::new(a.x, a.y, a.z), Vec3::new(a.x, b.y, a.z), Vec3::new(b.x, b.y, a.z)], side);
        self.quad([Vec3::new(b.x, a.y, b.z), Vec3::new(b.x, a.y, a.z), Vec3::new(b.x, b.y, a.z), Vec3::new(b.x, b.y, b.z)], side);
        self.quad([Vec3::new(a.x, a.y, a.z), Vec3::new(a.x, a.y, b.z), Vec3::new(a.x, b.y, b.z), Vec3::new(a.x, b.y, a.z)], side);
    }

    /// A box centred on `c` with half-sizes `h` (all faces).
    pub fn cube(&mut self, c: Vec3, h: Vec3, col: [f32; 4]) {
        self.block(c - h, c + h, col, scale(col, 0.82));
        let (a, b) = (c - h, c + h);
        self.quad([Vec3::new(a.x, a.y, a.z), Vec3::new(b.x, a.y, a.z), Vec3::new(b.x, a.y, b.z), Vec3::new(a.x, a.y, b.z)], scale(col, 0.6));
    }

    /// A cone-ish crown: `sides`-gon base at `y0` of radius `r`, apex at `y1`.
    pub fn cone(&mut self, c: Vec3, r: f32, y0: f32, y1: f32, sides: u32, col: [f32; 4]) {
        let apex = Vec3::new(c.x, y1, c.z);
        for i in 0..sides {
            let a0 = i as f32 / sides as f32 * std::f32::consts::TAU;
            let a1 = (i + 1) as f32 / sides as f32 * std::f32::consts::TAU;
            let p0 = Vec3::new(c.x + r * a0.cos(), y0, c.z + r * a0.sin());
            let p1 = Vec3::new(c.x + r * a1.cos(), y0, c.z + r * a1.sin());
            self.tri([p1, p0, apex], scale(col, 0.85 + 0.15 * (a0 + 0.8).sin()));
            self.tri([p0, p1, Vec3::new(c.x, y0, c.z)], scale(col, 0.6));
        }
    }

    /// A lumpy low-poly blob: an icosphere with each vertex pushed in or out; `flat` squashes it.
    pub fn boulder(&mut self, c: Vec3, r: f32, flat: f32, seed: u32, col: [f32; 4]) {
        let (verts, tris) = ico();
        let moved: Vec<Vec3> = verts
            .iter()
            .enumerate()
            .map(|(i, v)| {
                let k = 0.75 + 0.5 * hash(seed, i as u32);
                c + Vec3::new(v.x * r * k, v.y * r * flat * k, v.z * r * k)
            })
            .collect();
        for t in tris {
            let shade = 0.85 + 0.2 * hash(seed + t[0], t[1]);
            self.tri([moved[t[0] as usize], moved[t[1] as usize], moved[t[2] as usize]], scale(col, shade));
        }
    }

    /// A four-sided roof from the top of walls `a`..`b` (at `a.y`) to a ridge `rise` higher.
    pub fn roof(&mut self, a: Vec3, b: Vec3, overhang: f32, rise: f32, col: [f32; 4]) {
        let (x0, x1, z0, z1, y) = (a.x - overhang, b.x + overhang, a.z - overhang, b.z + overhang, a.y);
        let zm = (z0 + z1) / 2.0;
        let inset = ((x1 - x0) * 0.2).min((z1 - z0) / 2.0);
        let (r0, r1) = (Vec3::new(x0 + inset, y + rise, zm), Vec3::new(x1 - inset, y + rise, zm));
        let (c00, c10, c11, c01) = (Vec3::new(x0, y, z0), Vec3::new(x1, y, z0), Vec3::new(x1, y, z1), Vec3::new(x0, y, z1));
        self.quad([c00, r0, r1, c10], scale(col, 0.95));
        self.quad([c11, r1, r0, c01], scale(col, 0.8));
        self.tri([c01, r0, c00], scale(col, 0.7));
        self.tri([c10, r1, c11], scale(col, 0.88));
    }

    pub fn build(self) -> Mesh {
        Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::default())
            .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, self.pos)
            .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, self.nrm)
            .with_inserted_attribute(Mesh::ATTRIBUTE_COLOR, self.col)
            .with_inserted_indices(Indices::U32(self.idx))
    }

    pub fn is_empty(&self) -> bool {
        self.pos.is_empty()
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

pub fn rgb(r: u8, g: u8, b: u8) -> [f32; 4] {
    let l = |c: u8| Color::srgb_u8(c, c, c).to_linear().red;
    [l(r), l(g), l(b), 1.0]
}

pub fn scale(c: [f32; 4], k: f32) -> [f32; 4] {
    [c[0] * k, c[1] * k, c[2] * k, c[3]]
}

fn mix(a: [f32; 4], b: [f32; 4], t: f32) -> [f32; 4] {
    [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, 1.0]
}

fn ground_color(t: Terrain) -> [f32; 4] {
    match t {
        Terrain::Grass => rgb(112, 160, 74),
        Terrain::Forest => rgb(78, 116, 56),
        Terrain::Water => rgb(150, 140, 100),
        Terrain::Sand => rgb(214, 196, 140),
        Terrain::Rock => rgb(132, 128, 120),
        Terrain::Dirt => rgb(150, 118, 82),
        Terrain::Road => rgb(176, 156, 120),
        Terrain::Wall => rgb(140, 120, 90),
        // A drop between levels: a bank, open to the eye (no block is raised on it).
        Terrain::Drop => rgb(132, 112, 84),
        // Under a low thing (a cart, a low well): drawn as wall ground, with no block raised.
        Terrain::Low => rgb(140, 120, 90),
    }
}

/// Two tree shapes along +Y from the origin, about 2.2 units tall: a pine (stacked cones)
/// and a broadleaf. Instances are scaled 4–6.5×, so trees stand 8–15 m.
fn tree_mesh(broadleaf: bool) -> Mesh {
    let mut m = MeshBuf::default();
    let trunk = rgb(96, 70, 46);
    m.block(Vec3::new(-0.06, 0.0, -0.06), Vec3::new(0.06, 0.8, 0.06), trunk, scale(trunk, 0.85));
    if broadleaf {
        m.boulder(Vec3::Y * 1.35, 0.6, 0.85, 11, rgb(74, 128, 58));
        m.boulder(Vec3::new(0.28, 1.1, 0.15), 0.4, 0.85, 23, rgb(66, 118, 52));
        m.boulder(Vec3::new(-0.2, 1.15, -0.2), 0.38, 0.85, 37, rgb(70, 122, 54));
    } else {
        let green = rgb(44, 96, 54);
        m.cone(Vec3::ZERO, 0.5, 0.5, 1.3, 7, green);
        m.cone(Vec3::ZERO, 0.4, 0.95, 1.75, 7, scale(green, 1.06));
        m.cone(Vec3::ZERO, 0.27, 1.4, 2.2, 7, scale(green, 1.12));
    }
    m.build()
}

fn build_chunk(commands: &mut Commands, meshes: &mut Assets<Mesh>, palette: &Palette, ground: &Ground, id: u32) -> ChunkParts {
    let map = ground.map();
    let (cx, cy) = chunk_xy(id);
    let (x0, y0) = ((cx * CHUNK) as f32, (cy * CHUNK) as f32);
    let tiles_w = CHUNK.min(map.w - cx * CHUNK);
    let tiles_h = CHUNK.min(map.h - cy * CHUNK);
    let (nx, ny) = (tiles_w * RES + 1, tiles_h * RES + 1);
    let step = 1.0 / RES as f32;
    let g = |x: f32, y: f32| ground.height(x, y);
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
    let mut mesh = MeshBuf::default();
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
            // Steep ground shows bare rock, high ground turns stony and snowy; ground under
            // water darkens with depth.
            let steep = ((0.85 - n.y) / 0.25).clamp(0.0, 1.0);
            c = mix(c, rgb(118, 112, 104), steep);
            c = mix(c, rgb(128, 124, 116), ((h - 22.0) / 14.0).clamp(0.0, 0.8));
            c = mix(c, rgb(236, 238, 242), ((h - 42.0) / 8.0).clamp(0.0, 1.0) * n.y.clamp(0.0, 1.0));
            if h < WATER_LEVEL {
                c = mix(c, rgb(60, 80, 90), ((WATER_LEVEL - h) / 1.0).clamp(0.0, 0.7));
            }
            c = scale(c, 0.94 + 0.1 * hash(x.to_bits(), y.to_bits()));
            mesh.pos.push([x, h, y]);
            mesh.nrm.push(n.into());
            mesh.col.push(c);
        }
    }
    for j in 0..ny - 1 {
        for i in 0..nx - 1 {
            let a = j * nx + i;
            let (b, c, d) = (a + 1, a + nx, a + nx + 1);
            mesh.idx.extend_from_slice(&[a, c, b, b, c, d]);
        }
    }
    // Ground, props and trees are outline stencils: they hide outlines behind them.
    let mut entities = vec![commands.spawn((Mesh3d(meshes.add(mesh.build())), MeshMaterial3d(palette.terrain.clone()), Transform::default(), crate::style::ground_stencil())).id()];

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
                // A real forest: a tree on about one forest tile in ten (3–4 m apart, crowns
                // 4–7 m wide), bushes and undergrowth between.
                Terrain::Forest if v < 0.1 => {
                    let p = Vec3::new(px, g(px, py) - 0.1, py);
                    let size = 4.0 + 2.5 * hash(tx + 7, ty + 3);
                    let broad = hash(tx + 1, ty + 9) < 0.3;
                    let tf = Transform::from_translation(p).with_rotation(Quat::from_rotation_y(v * 37.0)).with_scale(Vec3::splat(size));
                    entities.push(commands.spawn((Tree, Mesh3d(palette.trees[broad as usize].clone()), MeshMaterial3d(palette.tree.clone()), tf, crate::style::stencil())).id());
                }
                Terrain::Forest if v < 0.45 => {
                    let r = 0.35 + 0.45 * hash(tx + 5, ty + 2);
                    props.boulder(Vec3::new(px, g(px, py) + r * 0.3, py), r, 0.7, tx * 13 + ty, rgb(62, 104, 48));
                }
                Terrain::Grass if v < 0.025 => {
                    let r = 0.3 + 0.3 * hash(tx + 5, ty + 2);
                    props.boulder(Vec3::new(px, g(px, py) + r * 0.3, py), r, 0.7, tx * 13 + ty, rgb(86, 132, 60));
                }
                // Boulders only inside rock (all eight neighbours rock), so they never stand
                // on or overhang ground a character can walk on.
                Terrain::Rock if v < 0.35 && rock_inside(map, tx as i32, ty as i32) => {
                    let r = 0.7 + 0.7 * hash(tx + 3, ty + 1);
                    let (bx, by) = (tx as f32 + 0.5 + (v - 0.5) * 0.2, ty as f32 + 0.5 + (hash(ty, tx) - 0.5) * 0.2);
                    props.boulder(Vec3::new(bx, g(bx, by) + r * 0.1, by), r, 0.7, tx * 31 + ty, rgb(128, 124, 116));
                }
                Terrain::Wall => {
                    let (fx, fy) = (tx as f32, ty as f32);
                    let base = g(fx + 0.5, fy + 0.5);
                    props.block(Vec3::new(fx, base - 0.5, fy), Vec3::new(fx + 1.0, base + 2.6, fy + 1.0), rgb(150, 140, 124), rgb(124, 116, 102));
                }
                _ => {}
            }
        }
    }
    if !props.is_empty() {
        entities.push(commands.spawn((Mesh3d(meshes.add(props.build())), MeshMaterial3d(palette.terrain.clone()), Transform::default(), crate::style::stencil())).id());
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

/// A resource or structure model, at real size (metres), vertex-coloured; glowing parts apart.
fn thing_mesh(kind: &str) -> (Mesh, Option<(Mesh, [u8; 3])>) {
    let mut m = MeshBuf::default();
    let mut glow = None;
    match kind {
        "berry_bush" => {
            m.boulder(Vec3::Y * 0.5, 0.6, 0.85, 3, rgb(70, 116, 54));
            for k in 0..7u32 {
                let a = k as f32 * 0.9;
                m.boulder(Vec3::new(0.5 * a.cos(), 0.45 + 0.08 * (k % 3) as f32, 0.5 * a.sin()), 0.07, 1.0, k, rgb(170, 40, 70));
            }
        }
        "fish" | "fishing_spot" => m.boulder(Vec3::Y * 0.02, 0.45, 0.1, 5, rgb(150, 200, 230)),
        "flint" | "stone" | "rock" => m.boulder(Vec3::Y * 0.15, 0.3, 0.7, 9, rgb(150, 150, 160)),
        "boulder" => {
            m.boulder(Vec3::Y * 0.35, 0.65, 0.75, 9, rgb(146, 144, 150));
            m.boulder(Vec3::new(0.55, 0.15, 0.2), 0.3, 0.7, 4, rgb(132, 130, 138));
        }
        "reeds" => {
            for k in 0..9u32 {
                let a = k as f32 * 2.4;
                let r = 0.12 + 0.05 * (k % 3) as f32;
                m.cone(Vec3::new(r * a.cos(), 0.0, r * a.sin()), 0.035, 0.01, 1.1 + 0.12 * (k % 4) as f32, 4, [0.47, 0.6, 0.27, 1.0]);
            }
        }
        "clay_bank" => m.boulder(Vec3::Y * 0.05, 0.7, 0.25, 6, rgb(168, 112, 82)),
        "sign" => {
            m.block(Vec3::new(-0.05, 0.0, -0.05), Vec3::new(0.05, 1.3, 0.05), rgb(96, 70, 44), rgb(86, 62, 40));
            m.block(Vec3::new(-0.45, 0.9, -0.04), Vec3::new(0.45, 1.35, 0.04), rgb(176, 140, 96), rgb(160, 126, 86));
        }
        "remains" => m.boulder(Vec3::Y * 0.05, 0.4, 0.3, 2, rgb(96, 70, 62)),
        "trap" => m.block(Vec3::new(-0.3, 0.0, -0.3), Vec3::new(0.3, 0.25, 0.3), rgb(120, 92, 60), rgb(104, 80, 52)),
        "campfire" | "fire" | "hearth" | "smoking_fire" => {
            for k in 0..8u32 {
                let a = k as f32 / 8.0 * std::f32::consts::TAU;
                m.boulder(Vec3::new(0.45 * a.cos(), 0.08, 0.45 * a.sin()), 0.12, 0.8, k, rgb(110, 106, 100));
            }
            m.block(Vec3::new(-0.3, 0.0, -0.05), Vec3::new(0.3, 0.12, 0.05), rgb(90, 62, 40), rgb(80, 54, 34));
            let mut f = MeshBuf::default();
            f.cone(Vec3::ZERO, 0.28, 0.05, 0.75, 6, [1.0, 1.0, 1.0, 1.0]);
            glow = Some((f.build(), [255, 140, 40]));
        }
        "shelter" | "house" | "hut" => {
            let (a, b) = (Vec3::new(-1.6, 0.0, -1.4), Vec3::new(1.6, 2.2, 1.4));
            m.block(Vec3::new(a.x, -0.3, a.z), b, rgb(150, 112, 74), rgb(136, 100, 66));
            m.block(Vec3::new(1.55, 0.0, -0.45), Vec3::new(1.65, 1.8, 0.45), rgb(70, 50, 34), rgb(70, 50, 34));
            m.roof(Vec3::new(a.x, b.y, a.z), b, 0.35, 1.5, rgb(122, 96, 60));
        }
        "hall" | "workshop" | "market" | "inn" | "smokehouse" => {
            let (a, b) = (Vec3::new(-3.0, 0.0, -2.4), Vec3::new(3.0, 3.0, 2.4));
            m.block(Vec3::new(a.x, -0.3, a.z), b, rgb(170, 128, 86), rgb(152, 112, 76));
            m.block(Vec3::new(2.95, 0.0, -0.6), Vec3::new(3.05, 2.2, 0.6), rgb(70, 50, 34), rgb(70, 50, 34));
            m.roof(Vec3::new(a.x, b.y, a.z), b, 0.4, 2.0, rgb(110, 70, 52));
        }
        "storage" | "store" | "storehouse" => {
            m.block(Vec3::new(-0.9, -0.2, -0.9), Vec3::new(0.9, 1.6, 0.9), rgb(128, 96, 64), rgb(112, 84, 56));
            m.roof(Vec3::new(-0.9, 1.6, -0.9), Vec3::new(0.9, 1.6, 0.9), 0.2, 0.7, rgb(100, 80, 54));
        }
        "gate" => m.block(Vec3::new(-0.5, -0.2, -0.15), Vec3::new(0.5, 2.4, 0.15), rgb(110, 80, 50), rgb(96, 70, 44)),
        _ => m.boulder(Vec3::Y * 0.25, 0.25, 1.0, 1, rgb(200, 200, 200)),
    }
    (m.build(), glow)
}

/// On a land world the island draws these itself: buildings as lots, gates in its walls, and
/// trees as its forest (an act names a tree by kind, the nearest one).
const LAND_DRAWS: &[&str] = &["tree", "house", "hall", "inn", "workshop", "market", "gate"];

/// Mirror subscribed resources and structures as entities (static, spawned once per row once the
/// ground under them is known): on tile worlds all of them; on a land world (the island) what it
/// does not draw itself, standing on its ground (what `verbs.rs` lets F act on).
#[allow(clippy::too_many_arguments)]
pub fn things(mut commands: Commands, net: NonSend<Net>, mut scene: NonSendMut<Scene>, mut meshes: ResMut<Assets<Mesh>>, mut mats: ResMut<Assets<Toon>>, mut palette: ResMut<Palette>, style: Res<Style>, island: Option<Res<crate::island::Island>>) {
    let Some(conn) = &net.conn else { return };
    let mut seen: HashSet<(u8, u64)> = HashSet::new();
    let (resources, structures) = (conn.db.resource_node(), conn.db.structure());
    let rows = resources
        .iter()
        .map(|r| ((0u8, r.id), r.kind, r.x, r.y, (r.amount / r.max.max(1.0)).clamp(0.4, 1.0)))
        .chain(structures.iter().map(|s| ((1u8, s.id), s.kind, s.x, s.y, 1.0)))
        .filter(|r| island.is_none() || !LAND_DRAWS.contains(&r.1.as_str()));
    let ready = scene.ready() || island.is_some();
    let scene = &mut *scene;
    for (key, kind, x, y, fill) in rows {
        seen.insert(key);
        if !ready || scene.things.contains_key(&key) {
            continue;
        }
        let (mesh, glow) = palette
            .things
            .entry(kind.clone())
            .or_insert_with(|| {
                let (mut m, g) = thing_mesh(&kind);
                let _ = m.generate_outline_normals(&Default::default());
                (meshes.add(m), g.map(|(g, c)| (meshes.add(g), c)))
            })
            .clone();
        let at = island.as_ref().map_or_else(|| scene.at3(x, y), |i| Vec3::new(x, i.height(x, y), y));
        let turn = Quat::from_rotation_y(hash(x.to_bits(), y.to_bits()) * std::f32::consts::TAU);
        let e = commands
            .spawn((Thing(Vec2::new(x, y)), Mesh3d(mesh), MeshMaterial3d(palette.vertex.clone()), Transform::from_translation(at).with_rotation(turn).with_scale(Vec3::splat(fill)), crate::style::stencil()))
            .id();
        // Outlines on structures only; small resources stay unlined so the scene stays calm.
        if key.0 == 1 {
            commands.entity(e).insert(outline(Outlined::Thing, &style));
        }
        if let Some((g, color)) = glow {
            let mat = palette.color(&mut mats, &style, color, true);
            commands.entity(e).with_children(|c| {
                c.spawn((Mesh3d(g), MeshMaterial3d(mat), Transform::default()));
            });
        }
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

/// Cut away trees between the camera and the player: hide those whose crowns block the line
/// from the camera to the player's head, or stand close to the player on the camera's side, and
/// fade a band around them. With the perception mock, dim trees outside sight (remembered) or
/// darken them (never seen).
#[allow(clippy::type_complexity)]
pub fn fade_trees(
    target: Res<crate::controls::Target>,
    palette: Res<Palette>,
    sight: Res<crate::sight::Sight>,
    me_size: Res<crate::bodies::MySize>,
    cam: Query<&Transform, (With<Camera3d>, Without<Tree>)>,
    mut trees: Query<(&Transform, &mut MeshMaterial3d<Toon>, &mut Visibility), With<Tree>>,
) {
    let (Some(me), Ok(cam)) = (target.0, cam.single()) else { return };
    let head = me + Vec3::Y * 1.6 * me_size.0;
    let (a, b) = (cam.translation, head);
    let ab = b - a;
    let len2 = ab.length_squared().max(1e-4);
    let me2 = Vec2::new(me.x, me.z);
    // The camera's side of the player, on the ground.
    let toward_cam = Vec2::new(a.x - me.x, a.z - me.z).normalize_or_zero();
    let cut_r = 5.0 * me_size.0.max(0.6);
    for (t, mut mat, mut vis) in &mut trees {
        let state = sight.state_at(me2, Vec2::new(t.translation.x, t.translation.z));
        let crown = t.translation + Vec3::Y * 1.3 * t.scale.y;
        let reach = 0.55 * t.scale.x + 0.5;
        let flat = Vec2::new(t.translation.x - me.x, t.translation.z - me.z);
        // 0 = drawn, 1 = faded, 2 = hidden.
        let mut cut = 0u8;
        if flat.length() < 40.0 {
            let s = ((crown - a).dot(ab) / len2).clamp(0.0, 1.0);
            let off = (a + ab * s).distance(crown);
            let near_side = flat.length() < cut_r + reach && flat.dot(toward_cam) > -1.0;
            cut = if (off < reach && s < 0.97) || near_side { 2 } else if off < reach + 2.5 && s < 0.97 { 1 } else { 0 };
        }
        let want_vis = if cut == 2 { Visibility::Hidden } else { Visibility::Inherited };
        if *vis != want_vis {
            *vis = want_vis;
        }
        let want = if state > 0 { &palette.tree_dim[state as usize - 1] } else if cut == 1 { &palette.tree_faded } else { &palette.tree };
        if &mat.0 != want {
            mat.0 = want.clone();
        }
    }
}
