//! Test environments (look-dev mode): places with contrasting moods and scales, to judge the
//! shared look and the camera before real content exists (docs/GAME_BRIEF.md).
//!
//! Each environment is a data file, `assets/envs/<id>.json`:
//! - **mood:** sun hour, colour and strength, sky and fog, and gentle style shifts (shadow hue,
//!   saturation, film gradient, brightness). Mood never changes how things are drawn;
//! - **ground:** colour, relief, and `open`, `paved` or `cave`;
//! - **slots:** what stands where, by kind (`tree`, `house`, `glow_mushroom`, `neon_sign`…),
//!   with a placement rule (`scatter` in a disc, a `grid` of blocks, a `ring` round the edge), a
//!   height range in metres, and an optional glow colour;
//! - **atmosphere** (optional; the island's): a day curve, regional and weather shifts of the
//!   mood (daylight.rs, weather.rs). With it the time of day, region and weather drive light, sky,
//!   fog and grading; without it the mood above stays fixed.
//!
//! Assets plug in by folder: any GLB/glTF in `assets/envs/<id>/<kind>/` (or `assets/envs/shared/
//! <kind>/`) is used for that kind, scaled to the slot's height, so a pack's own units don't
//! matter. Without files, a placeholder shape stands in. Environment 0 is the character line-up.
//!
//! You walk around with WASD (Shift to run) using the game camera, as a VRoid character from the
//! look-dev folder if there is one.
//!
//! `LIVING_GAME_TOUR=<dir>` photographs environments headless (no window) and quits:
//! - `LIVING_GAME_TOUR_ONLY=<id>[,<id>…]` limits it to those environments (`lineup` is the
//!   line-up); default all.
//! - `LIVING_GAME_TOUR_SHOTS=<shot>[,<shot>…]`: `default` (the game camera), `close` (low and
//!   near), or `YAW:PITCH:DISTANCE[:FOV]` in degrees and metres, yaw 0 looking north; default
//!   `default,close`. Each lands in `env-<id>-<shot>.png`.

use crate::camera::{Cam, SKY};
use crate::lookdev::{Fitted, Lookdev, Model};
use crate::style::{outline, Outlined, Style};
use crate::world::{hash, rgb, scale, MeshBuf, Palette};
use bevy::prelude::*;
use bevy::world_serialization::WorldAssetRoot;
use bevy_mod_outline::OutlineMeshExt;
use serde::Deserialize;
use std::collections::HashMap;
use std::f32::consts::{PI, TAU};
use std::sync::{Arc, Mutex};

/// Everything spawned for the current environment (despawned on a switch).
#[derive(Component)]
pub struct EnvPart;

/// A tall thing the camera cuts away when it stands between the camera and you.
#[derive(Component)]
pub struct Occluder {
    pub height: f32,
}

/// A building the camera may not enter (`camera::follow` pulls the eye in front of it).
#[derive(Component)]
pub struct Solid;

/// A fitted thing's box: its centre, half extents and rotation (world).
pub fn fitted_box(t: &Transform, f: &Fitted) -> (Vec3, Vec3, Quat) {
    (t.translation + t.rotation * f.center, f.size * 0.5, t.rotation)
}

/// Where the segment from `a` to `b` (box space) enters and leaves the box of half extents `h`
/// round the origin, as fractions of the segment; None when it misses.
pub fn segment_box(a: Vec3, b: Vec3, h: Vec3) -> Option<(f32, f32)> {
    let d = b - a;
    let (mut t0, mut t1) = (f32::NEG_INFINITY, f32::INFINITY);
    for i in 0..3 {
        if d[i].abs() < 1e-6 {
            if a[i].abs() > h[i] {
                return None;
            }
            continue;
        }
        let (mut lo, mut hi) = ((-h[i] - a[i]) / d[i], (h[i] - a[i]) / d[i]);
        if lo > hi {
            std::mem::swap(&mut lo, &mut hi);
        }
        t0 = t0.max(lo);
        t1 = t1.min(hi);
    }
    (t0 <= t1).then_some((t0, t1))
}

/// The character you walk around with.
#[derive(Component, Clone, Copy)]
pub enum Player {
    /// The procedural reference figure (faces +X).
    Figure,
    /// A loaded model: VRM models face −Z, glTF models +Z.
    Model { vrm: bool },
}

#[derive(Deserialize, Clone, Debug)]
pub struct Mood {
    pub hour: f32,
    pub sun: [f32; 3],
    pub lux: f32,
    pub sky: [f32; 3],
    pub fog: [f32; 3],
    pub fog_start: f32,
    pub fog_end: f32,
    pub shadow_hue: f32,
    #[serde(default = "default_hue_shift")]
    pub hue_shift: f32,
    pub saturation: f32,
    pub grade: [f32; 3],
    pub grade_strength: f32,
    pub exposure: f32,
    /// Lifts shadows a little in dark places (style ambient).
    #[serde(default)]
    pub ambient: f32,
    /// Bloom strength; glowing places want more (default 0.12).
    #[serde(default = "default_bloom")]
    pub bloom: f32,
}

fn default_bloom() -> f32 {
    0.12
}

fn default_hue_shift() -> f32 {
    0.18
}

#[derive(Deserialize, Clone, Debug)]
pub struct GroundDef {
    pub surface: String,
    pub color: [u8; 3],
    pub radius: f32,
    pub relief: f32,
}

#[derive(Deserialize, Clone, Debug)]
pub struct Slot {
    pub kind: String,
    pub rule: String,
    #[serde(default)]
    pub count: u32,
    #[serde(default)]
    pub radius: f32,
    #[serde(default)]
    pub clear: f32,
    pub height: [f32; 2],
    #[serde(default)]
    pub spacing: f32,
    #[serde(default)]
    pub rows: u32,
    #[serde(default)]
    pub cols: u32,
    #[serde(default)]
    pub offset: [f32; 2],
    pub glow: Option<[f32; 3]>,
    /// `ring` only: `"in"` turns fronts toward the centre (default: outward).
    #[serde(default)]
    pub face: String,
}

#[derive(Deserialize, Clone, Debug)]
pub struct EnvDef {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub note: String,
    pub mood: Mood,
    pub ground: GroundDef,
    pub slots: Vec<Slot>,
    /// A generated world instead of a ground disc and slots (`island.rs`).
    #[serde(default)]
    pub world: Option<crate::island::WorldDef>,
    /// The time of day, regional moods and weather (daylight.rs); without it the mood is fixed.
    #[serde(default)]
    pub atmosphere: Option<crate::daylight::AtmoDef>,
}

/// The environments, the current one and the one asked for.
#[derive(Resource)]
pub struct Envs {
    pub defs: Vec<EnvDef>,
    pub current: Option<usize>,
    pub want: usize,
    /// Ground shape of the current environment.
    pub ground: GroundShape,
    tour: Option<Tour>,
    /// The island's land, generating on a worker thread (`Island::generate`).
    land: Option<LandSlot>,
}

/// Where the worker thread leaves the generated land and its seconds.
type LandSlot = Arc<Mutex<Option<crate::island::Generated>>>;

/// The current environment's ground: gentle relief from value noise, flat when paved.
#[derive(Clone, Copy, Default)]
pub struct GroundShape {
    pub relief: f32,
    pub radius: f32,
    pub seed: u32,
}

impl GroundShape {
    pub fn height(&self, x: f32, z: f32) -> f32 {
        if self.relief <= 0.0 {
            return 0.0;
        }
        let n = |x: f32, z: f32, f: f32, s: u32| {
            let (xf, zf) = (x * f, z * f);
            let (x0, z0) = (xf.floor(), zf.floor());
            let (tx, tz) = (xf - x0, zf - z0);
            let (tx, tz) = (tx * tx * (3.0 - 2.0 * tx), tz * tz * (3.0 - 2.0 * tz));
            let h = |i: f32, j: f32| hash((i as i32 as u32).wrapping_add(s), (j as i32 as u32).wrapping_mul(31).wrapping_add(s));
            let a = h(x0, z0) + (h(x0 + 1.0, z0) - h(x0, z0)) * tx;
            let b = h(x0, z0 + 1.0) + (h(x0 + 1.0, z0 + 1.0) - h(x0, z0 + 1.0)) * tx;
            (a + (b - a) * tz) * 2.0 - 1.0
        };
        // Flat where you start, rising gently outward.
        let near = (Vec2::new(x, z).length() / 10.0).clamp(0.0, 1.0);
        (n(x, z, 1.0 / 18.0, self.seed) * 0.7 + n(x, z, 1.0 / 7.0, self.seed + 9) * 0.3) * self.relief * near
    }
}

/// A mood: light, sky, fog and gentle style shifts only.
pub fn apply_mood(md: &Mood, style: &mut Style, look: &mut Lookdev, lights: &mut Query<&mut DirectionalLight>, cams: &mut Query<&mut DistanceFog, With<Camera3d>>, clear: &mut ClearColor) {
    let base = Style::default();
    look.hour = md.hour;
    for mut l in lights.iter_mut() {
        l.color = Color::srgb(md.sun[0], md.sun[1], md.sun[2]);
        l.illuminance = md.lux;
    }
    let sky = Color::srgb(md.sky[0], md.sky[1], md.sky[2]);
    clear.0 = sky;
    for mut f in cams.iter_mut() {
        f.color = Color::srgb(md.fog[0], md.fog[1], md.fog[2]);
    }
    *style = Style {
        enabled: style.enabled,
        shadow_hue: md.shadow_hue,
        hue_shift: md.hue_shift,
        saturation: md.saturation,
        grade_color: md.grade,
        grade: md.grade_strength,
        exposure: md.exposure,
        ambient: md.ambient,
        bloom: md.bloom,
        // Edge lines end where the fog has mostly swallowed things (as outlines do), so no bare
        // line drawings show through the fog.
        line_fade: [md.fog_start * 0.5, md.fog_start + (md.fog_end - md.fog_start) * 0.45],
        ..base
    };
}

/// You: a VRoid character from the look-dev folder if there is one, else the figure; or a rigged
/// animal with `LIVING_GAME_PLAYER=beast:<kind>` (`wolf`, `deer`), for measuring its gaits.
fn spawn_player(commands: &mut Commands, meshes: &mut Assets<Mesh>, palette: &Palette, style: &Style, look: &Lookdev, assets: &AssetServer) {
    if let Some(kind) = std::env::var("LIVING_GAME_PLAYER").ok().and_then(|r| r.strip_prefix("beast:").map(str::to_string)) {
        if let Some(e) = crate::bodies::spawn_beast(commands, assets, &kind, Vec3::ZERO, 0.0, 1.0) {
            commands.entity(e).insert((EnvPart, Player::Model { vrm: false }, Visibility::Inherited));
            return;
        }
        warn!("look-dev: no rigged {kind} on disk; you are the usual character");
    }
    let vroid = look.models.iter().find(|m| m.starts_with("vroid-")).cloned();
    match vroid {
        Some(name) => {
            // `LIVING_GAME_PLAYER=<recipe>` (a name or `<folk>:<seed>`); default: the base's own look.
            let recipe = std::env::var("LIVING_GAME_PLAYER").ok().and_then(|r| crate::characters::Recipe::parse(&r)).unwrap_or_else(|| crate::characters::Recipe::default_for(&format!("lookdev/{name}")));
            let e = crate::characters::spawn(commands, assets, &recipe, Vec3::ZERO, 0.0);
            commands.entity(e).insert((EnvPart, Player::Model { vrm: true }));
        }
        None => {
            let e = crate::bodies::spawn(commands, meshes, palette, style, "person", 1, false, Transform::default(), Vec2::ZERO);
            commands.entity(e).insert((EnvPart, Player::Figure));
        }
    }
}

/// Free walking: position, facing and whether you are moving.
#[derive(Resource, Default)]
pub struct Roam {
    pub pos: Vec2,
    pub facing: Vec2,
    pub moving: bool,
    pub running: bool,
    /// Current speed, m/s.
    pub speed: f32,
}

pub fn load_defs() -> Vec<EnvDef> {
    let dir = std::path::Path::new(&crate::lookdev::asset_root()).join("envs");
    let mut files: Vec<_> = std::fs::read_dir(&dir).map(|r| r.filter_map(|e| e.ok()).map(|e| e.path()).filter(|p| p.extension().is_some_and(|x| x == "json")).collect()).unwrap_or_default();
    files.sort();
    let mut defs = Vec::new();
    for f in files {
        match std::fs::read_to_string(&f).map_err(|e| e.to_string()).and_then(|s| serde_json::from_str::<EnvDef>(&s).map_err(|e| e.to_string())) {
            Ok(d) => defs.push(d),
            Err(e) => warn!("environment {}: {e}", f.display()),
        }
    }
    defs
}

pub fn setup(mut commands: Commands) {
    let defs = load_defs();
    info!("environments: line-up + {} ({})", defs.len(), defs.iter().map(|d| d.id.as_str()).collect::<Vec<_>>().join(", "));
    let tour = std::env::var("LIVING_GAME_TOUR").ok().filter(|d| !d.is_empty()).map(|d| Tour::from_env(d, &defs));
    let want = std::env::var("LIVING_GAME_ENV").ok().and_then(|id| defs.iter().position(|d| d.id == id).map(|i| i + 1)).unwrap_or(0);
    commands.insert_resource(Envs { defs, current: None, want, ground: GroundShape::default(), tour, land: None });
    commands.insert_resource(Roam { facing: Vec2::new(0.0, 1.0), ..default() });
}

/// Model files for a kind in this environment (its own folder, then the shared one).
pub(crate) fn assets_for(env: &str, kind: &str) -> Vec<String> {
    // Listed once per session: the island asks per lot, prop and streamed chunk.
    type Listed = HashMap<(String, String), Vec<String>>;
    static CACHE: std::sync::OnceLock<Mutex<Listed>> = std::sync::OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    let key = (env.to_string(), kind.to_string());
    if let Some(v) = cache.lock().unwrap().get(&key) {
        return v.clone();
    }
    let out = list_assets(env, kind);
    cache.lock().unwrap().insert(key, out.clone());
    out
}

fn list_assets(env: &str, kind: &str) -> Vec<String> {
    let root = std::path::Path::new(&crate::lookdev::asset_root()).to_path_buf();
    let mut out = Vec::new();
    for sub in [format!("envs/{env}/{kind}"), format!("envs/shared/{kind}")] {
        if let Ok(r) = std::fs::read_dir(root.join(&sub)) {
            let mut files: Vec<String> = r.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().to_string()).filter(|n| n.ends_with(".glb") || n.ends_with(".gltf")).map(|n| format!("{sub}/{n}")).collect();
            files.sort();
            out.extend(files);
        }
        if !out.is_empty() {
            break;
        }
    }
    out
}

/// One placed thing.
pub(crate) struct Place {
    pub at: Vec2,
    pub yaw: f32,
    pub height: f32,
}

/// Where a slot's things go: deterministic, kept clear of the start, spaced apart.
pub(crate) fn place(slot: &Slot, si: usize, taken: &mut Vec<(Vec2, f32)>, limit: f32) -> Vec<Place> {
    let r = |i: u32, k: u32| hash(si as u32 * 7919 + i, k);
    let height = |i: u32| slot.height[0] + (slot.height[1] - slot.height[0]) * r(i, 3);
    let mut out = Vec::new();
    let room = |h: f32| if slot.spacing > 0.0 { slot.spacing * 0.5 } else { (h * 0.18).clamp(0.3, 10.0) };
    let free = |taken: &Vec<(Vec2, f32)>, p: Vec2, rad: f32| p.length() >= slot.clear && p.length() <= limit && taken.iter().all(|(q, qr)| p.distance(*q) >= rad + qr);
    match slot.rule.as_str() {
        "grid" => {
            let (rows, cols) = (slot.rows.max(1), slot.cols.max(1));
            for j in 0..rows {
                for i in 0..cols {
                    let k = j * cols + i;
                    let base = Vec2::new((i as f32 - (cols - 1) as f32 / 2.0) * slot.spacing, (j as f32 - (rows - 1) as f32 / 2.0) * slot.spacing) + Vec2::from(slot.offset);
                    let at = base + Vec2::new(r(k, 1) - 0.5, r(k, 2) - 0.5) * slot.spacing * 0.15;
                    let h = height(k);
                    let rad = (h * 0.3).min(slot.spacing * 0.45);
                    if free(taken, at, rad) {
                        taken.push((at, rad));
                        out.push(Place { at, yaw: (r(k, 4) * 4.0).floor() * PI / 2.0, height: h });
                    }
                }
            }
        }
        "ring" => {
            for k in 0..slot.count {
                let a = k as f32 / slot.count.max(1) as f32 * TAU + r(k, 1) * 0.05;
                let rr = slot.radius - r(k, 2) * 2.0;
                let at = Vec2::new(a.cos(), a.sin()) * rr;
                let inward = if slot.face == "in" { PI } else { 0.0 };
                out.push(Place { at, yaw: -a + PI / 2.0 + inward, height: height(k) });
                taken.push((at, 1.0));
            }
        }
        _ => {
            let mut tries = 0;
            let mut k = 0u32;
            while (out.len() as u32) < slot.count && tries < slot.count * 30 {
                tries += 1;
                k += 1;
                let (a, d) = (r(k, 1) * TAU, r(k, 2).sqrt() * slot.radius);
                let at = Vec2::new(a.cos(), a.sin()) * d;
                let h = height(k);
                let rad = room(h);
                if free(taken, at, rad) {
                    taken.push((at, rad));
                    out.push(Place { at, yaw: r(k, 4) * TAU, height: h });
                }
            }
        }
    }
    out
}

/// A placeholder model for a kind, one unit tall (scaled to the slot's height), and its glowing
/// part if any.
fn placeholder(kind: &str, seed: u32) -> (Mesh, Option<Mesh>) {
    let mut m = MeshBuf::default();
    let mut g = MeshBuf::default();
    let white = [1.0, 1.0, 1.0, 1.0];
    match kind {
        "tree" => {
            let trunk = rgb(96, 70, 46);
            m.block(Vec3::new(-0.025, 0.0, -0.025), Vec3::new(0.025, 0.35, 0.025), trunk, scale(trunk, 0.85));
            m.cone(Vec3::ZERO, 0.24, 0.22, 0.62, 7, rgb(44, 96, 54));
            m.cone(Vec3::ZERO, 0.18, 0.45, 0.82, 7, rgb(48, 104, 58));
            m.cone(Vec3::ZERO, 0.12, 0.65, 1.0, 7, rgb(52, 110, 60));
        }
        "bush" => m.boulder(Vec3::Y * 0.45, 0.6, 0.8, seed, rgb(70, 116, 54)),
        "flower" => {
            m.block(Vec3::new(-0.04, 0.0, -0.04), Vec3::new(0.04, 0.75, 0.04), rgb(70, 120, 50), rgb(60, 104, 44));
            let c = [rgb(240, 120, 150), rgb(250, 220, 90), rgb(160, 140, 240), rgb(250, 250, 250)][(seed % 4) as usize];
            m.boulder(Vec3::Y * 0.85, 0.18, 0.6, seed, c);
        }
        "rock" => m.boulder(Vec3::Y * 0.4, 0.55, 0.75, seed, rgb(130, 126, 120)),
        "stalagmite" => m.cone(Vec3::ZERO, 0.22, 0.0, 1.0, 6, rgb(120, 112, 104)),
        "cave_wall" => {
            m.boulder(Vec3::Y * 0.45, 0.5, 1.0, seed, rgb(86, 80, 76));
            m.boulder(Vec3::new(0.15, 0.75, 0.1), 0.35, 1.0, seed + 1, rgb(96, 90, 84));
        }
        "log" => m.block(Vec3::new(-1.6, 0.0, -0.45), Vec3::new(1.6, 1.0, 0.45), rgb(110, 80, 52), rgb(96, 70, 46)),
        "glow_mushroom" => {
            m.block(Vec3::new(-0.08, 0.0, -0.08), Vec3::new(0.08, 0.6, 0.08), rgb(220, 210, 190), rgb(200, 190, 170));
            g.boulder(Vec3::Y * 0.7, 0.4, 0.45, seed, white);
        }
        "glow_plant" => {
            for k in 0..5u32 {
                let a = k as f32 * 1.3;
                g.cone(Vec3::new(0.15 * a.cos(), 0.0, 0.15 * a.sin()), 0.05, 0.0, 0.7 + 0.3 * hash(seed, k), 4, white);
            }
        }
        "crystal" => {
            for k in 0..4u32 {
                let a = k as f32 * 1.7;
                g.cone(Vec3::new(0.12 * a.cos(), 0.0, 0.12 * a.sin()), 0.12, 0.0, 0.55 + 0.45 * hash(seed, k), 5, white);
            }
        }
        "house" | "market_stall" => {
            let wall = if kind == "house" { rgb(170, 128, 86) } else { rgb(190, 150, 100) };
            m.block(Vec3::new(-0.45, 0.0, -0.4), Vec3::new(0.45, 0.6, 0.4), wall, scale(wall, 0.88));
            m.roof(Vec3::new(-0.45, 0.6, -0.4), Vec3::new(0.45, 0.6, 0.4), 0.06, 0.4, if kind == "house" { rgb(150, 80, 60) } else { rgb(200, 60, 60) });
        }
        "tower" => {
            m.block(Vec3::new(-0.12, 0.0, -0.12), Vec3::new(0.12, 0.85, 0.12), rgb(150, 150, 160), rgb(130, 130, 140));
            m.cone(Vec3::Y * 0.85, 0.16, 0.0, 0.15, 6, rgb(90, 90, 120));
        }
        "factory" => {
            m.block(Vec3::new(-0.5, 0.0, -0.35), Vec3::new(0.5, 0.55, 0.35), rgb(130, 90, 64), rgb(110, 76, 54));
            m.roof(Vec3::new(-0.5, 0.55, -0.35), Vec3::new(0.5, 0.55, 0.35), 0.03, 0.2, rgb(90, 80, 70));
            m.block(Vec3::new(0.25, 0.55, -0.1), Vec3::new(0.35, 1.0, 0.0), rgb(110, 100, 90), rgb(96, 86, 78));
        }
        "chimney" => m.block(Vec3::new(-0.06, 0.0, -0.06), Vec3::new(0.06, 1.0, 0.06), rgb(140, 90, 70), rgb(120, 76, 60)),
        "pipe" => {
            m.block(Vec3::new(-0.5, 0.35, -0.08), Vec3::new(0.5, 0.5, 0.08), rgb(180, 140, 70), rgb(150, 116, 58));
            m.block(Vec3::new(-0.45, 0.0, -0.06), Vec3::new(-0.35, 0.4, 0.06), rgb(150, 116, 58), rgb(130, 100, 50));
            m.block(Vec3::new(0.35, 0.0, -0.06), Vec3::new(0.45, 0.4, 0.06), rgb(150, 116, 58), rgb(130, 100, 50));
        }
        "wall" => m.block(Vec3::new(-0.6, 0.0, -0.15), Vec3::new(0.6, 1.0, 0.15), rgb(160, 150, 134), rgb(136, 128, 114)),
        "lamp" => {
            m.block(Vec3::new(-0.02, 0.0, -0.02), Vec3::new(0.02, 0.9, 0.02), rgb(60, 60, 64), rgb(50, 50, 54));
            g.boulder(Vec3::Y * 0.93, 0.07, 1.0, seed, white);
        }
        "neon_sign" => {
            m.block(Vec3::new(-0.04, 0.0, -0.04), Vec3::new(0.04, 0.55, 0.04), rgb(50, 50, 56), rgb(40, 40, 46));
            g.block(Vec3::new(-0.35, 0.55, -0.04), Vec3::new(0.35, 1.0, 0.04), white, white);
        }
        "crate" => m.block(Vec3::new(-0.5, 0.0, -0.5), Vec3::new(0.5, 1.0, 0.5), rgb(150, 112, 70), rgb(130, 96, 60)),
        _ => m.boulder(Vec3::Y * 0.5, 0.5, 1.0, seed, rgb(200, 200, 200)),
    }
    let glow = (!g.is_empty()).then(|| g.build());
    (m.build(), glow)
}

/// A point light for a glowing thing (lamps, signs, crystals, some mushrooms), at ~90% of its
/// height, no shadows. With the atmosphere, only the nearest few are lit, lamps only at night
/// (daylight.rs `lamps`).
pub(crate) fn local_light(kind: &str, glow: Option<[f32; 3]>, height: f32, k: usize) -> Option<((PointLight, crate::daylight::Lamp), Transform)> {
    let [r, g, b] = glow?;
    let (lumens, range) = match kind {
        "lamp" => (60_000.0, 12.0),
        "neon_sign" => (25_000.0, 8.0),
        "crystal" => (18_000.0, 7.0),
        "glow_mushroom" if k % 3 == 0 => (8_000.0, 5.0),
        _ => return None,
    };
    let light = PointLight { color: Color::srgb(r, g, b), intensity: lumens, range, shadow_maps_enabled: false, ..default() };
    let lamp = crate::daylight::Lamp { lumens, lit_at_night: matches!(kind, "lamp" | "neon_sign") };
    Some(((light, lamp), Transform::from_xyz(0.0, height * 0.9, 0.0)))
}

/// Fade out tall things that stand between the camera and you, or around the camera (`fade.rs`;
/// play-test 1: whole houses popped on and off as the view turned, from a rule that hid
/// anything tall within 5 m of you on the camera's side, and the eye sometimes sat inside a
/// wall the rule missed).
///
/// A thing's box is its fitted bounds turned with it (else a guess from its height). It fades to
/// [`SEE_THROUGH`] while the sight lines from the eye to my head, chest and feet pass through it,
/// and fully while the eye is inside it; it comes back [`CUT_HOLD_S`] after the last frame it
/// was in the way, so a line grazing a corner doesn't flicker.
pub fn cutaway(
    target: Res<crate::controls::Target>,
    time: Res<Time>,
    cam: Query<&Transform, (With<Camera3d>, Without<Occluder>)>,
    mut q: Query<(Entity, &Transform, &Occluder, &mut crate::fade::Fade, Option<&Model>, Option<&Fitted>)>,
    mut held: Local<std::collections::HashMap<Entity, f32>>,
) {
    let (Some(me), Ok(cam)) = (target.0, cam.single()) else { return };
    if crate::perf::has("nocutaway") {
        return;
    }
    let now = time.elapsed_secs();
    let eye = cam.translation;
    let points = [me + Vec3::Y * 1.6, me + Vec3::Y * 1.05, me + Vec3::Y * 0.25];
    for (e, t, o, mut fade, model, fitted) in &mut q {
        // Models stay hidden until fitted (look-dev fit shows them).
        if model.is_some() && fitted.is_none() {
            continue;
        }
        let (half, centre) = match fitted {
            Some(f) if f.size.x > 0.0 => (f.size * 0.5, t.translation + t.rotation * f.center),
            _ => {
                let r = (o.height * 0.25 + 0.6).min(5.0);
                (Vec3::new(r, o.height * 0.5, r), t.translation + Vec3::Y * o.height * 0.5)
            }
        };
        // Into the box's own frame.
        let inv = t.rotation.inverse();
        let local = |p: Vec3| inv * (p - centre);
        let inside = { let l = local(eye).abs(); l.x < half.x + 0.6 && l.y < half.y + 0.6 && l.z < half.z + 0.6 };
        let pad = Vec3::splat(0.25);
        let blocks = points.iter().any(|p| segment_hits_box(local(eye), local(*p), half + pad, 0.35));
        let want = if inside {
            1.0
        } else if blocks {
            SEE_THROUGH
        } else {
            0.0
        };
        if want > 0.0 {
            held.insert(e, now);
        }
        let keep = held.get(&e).is_some_and(|t| now - t < CUT_HOLD_S);
        let to = if want > 0.0 { want } else if keep { fade.target } else { 0.0 };
        if fade.target != to {
            fade.target = to;
        }
    }
    if held.len() > 4096 {
        held.retain(|_, t| now - *t < CUT_HOLD_S);
    }
}

/// Drawn only out to this distance from me (m, on the ground): a thing fades out, dithered,
/// over the last [`crate::island::REACH_BAND`] metres before it ([`reach`]), so the edge of
/// the draw distance never pops, also where the mood's fog starts farther out than it.
#[derive(Component, Clone, Copy, Debug)]
pub struct Reach(pub f32);

impl Reach {
    /// How far out of view a thing at distance `d` is (0 drawn, 1 gone).
    pub fn out(r: f32, d: f32) -> f32 {
        let band = crate::island::REACH_BAND;
        let t = ((d - (r - band)) / band).clamp(0.0, 1.0);
        t * t * (3.0 - 2.0 * t)
    }

    /// The fade for a thing spawned at distance `d`: drawn at once well inside its reach, else
    /// fading in from nothing (or staying out).
    pub fn fade_at(r: f32, d: f32) -> crate::fade::Fade {
        if Self::out(r, d) > 0.0 {
            crate::fade::Fade::appearing()
        } else {
            crate::fade::Fade::shown()
        }
    }
}

/// Fade things toward the edge of their reach (after [`cutaway`], which sets what is in the way).
pub fn reach(target: Res<crate::controls::Target>, mut q: Query<(&Transform, &Reach, &mut crate::fade::Fade, Has<Occluder>)>) {
    let Some(me) = target.0 else { return };
    for (t, r, mut fade, cut) in &mut q {
        let out = Reach::out(r.0, t.translation.xz().distance(me.xz()));
        // What is in the way keeps its cut-away; anything else is only as far out as its reach.
        let to = if cut { fade.target.max(out) } else { out };
        if fade.target != to {
            fade.target = to;
        }
    }
}

/// How far a thing in the way fades (it stays faintly there, so you see what hides you), and how
/// long it stays faded after it was last in the way (s).
pub const SEE_THROUGH: f32 = 0.8;
const CUT_HOLD_S: f32 = 0.35;

/// Whether the segment from `a` to `b` (box space) passes through the box of half extents `h`
/// round the origin, leaving out its last `tail` metres at `b` (what stands right behind me
/// doesn't hide me).
pub fn segment_hits_box(a: Vec3, b: Vec3, h: Vec3, tail: f32) -> bool {
    let d = b - a;
    let len = d.length();
    if len < 1e-4 {
        return false;
    }
    let end = ((len - tail) / len).max(0.0);
    let (mut t0, mut t1) = (0.0f32, end);
    for i in 0..3 {
        if d[i].abs() < 1e-6 {
            if a[i].abs() > h[i] {
                return false;
            }
            continue;
        }
        let (mut lo, mut hi) = ((-h[i] - a[i]) / d[i], (h[i] - a[i]) / d[i]);
        if lo > hi {
            std::mem::swap(&mut lo, &mut hi);
        }
        t0 = t0.max(lo);
        t1 = t1.min(hi);
        if t0 > t1 {
            return false;
        }
    }
    true
}

/// Tear down the current environment and build the one asked for.
#[allow(clippy::too_many_arguments)]
pub fn switch(
    mut commands: Commands,
    mut envs: ResMut<Envs>,
    parts: Query<Entity, With<EnvPart>>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut toons: ResMut<Assets<crate::style::Toon>>,
    mut palette: ResMut<Palette>,
    mut style: ResMut<Style>,
    mut look: ResMut<Lookdev>,
    mut roam: ResMut<Roam>,
    assets: Res<AssetServer>,
    mut lights: Query<&mut DirectionalLight>,
    mut cams: Query<&mut DistanceFog, With<Camera3d>>,
    mut clear: ResMut<ClearColor>,
    ground_mat: Res<crate::terrain::GroundMat>,
    mut draw: ResMut<crate::world::Draw>,
) {
    // The island's land arrives from its worker thread: place it and you.
    if envs.current == Some(envs.want) {
        let done = envs.land.as_ref().and_then(|slot| slot.lock().unwrap().take());
        if let Some(generated) = done {
            envs.land = None;
            let island = crate::island::Island::new(generated, &envs.defs);
            roam.pos = island.start;
            commands.insert_resource(island);
            spawn_player(&mut commands, &mut meshes, &palette, &style, &look, &assets);
        }
        return;
    }
    envs.land = None;
    for e in &parts {
        commands.entity(e).despawn();
    }
    let want = envs.want;
    envs.current = Some(want);
    *roam = Roam { facing: Vec2::new(0.0, 1.0), ..default() };
    let base = Style::default();
    commands.remove_resource::<crate::island::Island>();
    if want == 0 || want > envs.defs.len() {
        // The character line-up, in the default mood.
        envs.ground = GroundShape::default();
        let (s, m) = (style.enabled, look.models.clone());
        *style = Style { enabled: s, ..base };
        look.hour = 15.0;
        for mut l in &mut lights {
            l.color = Color::srgb(1.0, 0.96, 0.88);
            l.illuminance = 9_000.0;
        }
        clear.0 = SKY;
        for mut f in &mut cams {
            f.color = SKY;
        }
        draw.fog = None;
        crate::lookdev::build_lineup(&mut commands, &mut meshes, &palette, &style, &assets, &m);
        return;
    }
    let def = envs.defs[want - 1].clone();
    info!("environment: {} — {}", def.name, def.note);
    apply_mood(&def.mood, &mut *style, &mut *look, &mut lights, &mut cams, &mut *clear);
    draw.mood(&def.mood);
    if let Some(world) = def.world {
        // The island streams itself in (island.rs); you start at its town. Its land generates
        // on a worker thread (most of a second), placed when it arrives (above).
        let slot: LandSlot = Arc::default();
        envs.land = Some(slot.clone());
        std::thread::spawn(move || {
            *slot.lock().unwrap() = Some(crate::island::Island::generate(world));
        });
        envs.ground = GroundShape::default();
        return;
    }
    // Ground.
    let g = &def.ground;
    let shape = GroundShape { relief: g.relief, radius: g.radius, seed: def.id.len() as u32 * 131 };
    envs.ground = shape;
    let mut mesh = MeshBuf::default();
    let r = g.radius;
    let n = (r * 2.0 / 1.5).ceil() as i32;
    let step = r * 2.0 / n as f32;
    let col = rgb(g.color[0], g.color[1], g.color[2]);
    let paved = g.surface == "paved";
    for j in 0..n {
        for i in 0..n {
            let (x0, z0) = (-r + i as f32 * step, -r + j as f32 * step);
            if Vec2::new(x0 + step / 2.0, z0 + step / 2.0).length() > r + step {
                continue;
            }
            let p = |x: f32, z: f32| Vec3::new(x, shape.height(x, z), z);
            let v = hash(i as u32 + 1000, j as u32 + 2000);
            let c = if paved && ((x0 / 2.0).floor() as i32 + (z0 / 2.0).floor() as i32) % 2 == 0 { scale(col, 0.92) } else { scale(col, 0.95 + 0.1 * v) };
            mesh.quad([p(x0, z0), p(x0, z0 + step), p(x0 + step, z0 + step), p(x0 + step, z0)], c);
        }
    }
    // Painted with the environment's ground layer (terrain.rs).
    let mut disc = mesh.build();
    let blend = crate::terrain::Blend::one(crate::terrain::disc_layer(&def.id, &g.surface));
    let count = disc.count_vertices();
    crate::terrain::insert_blend(&mut disc, &vec![blend; count]);
    commands.spawn((EnvPart, Mesh3d(meshes.add(disc)), MeshMaterial3d(ground_mat.0.clone()), Transform::default(), crate::style::ground_stencil()));
    // Slots: real models where the folders have them, placeholders otherwise.
    let mut taken: Vec<(Vec2, f32)> = vec![(Vec2::ZERO, 2.0)];
    let limit = r - 1.0;
    let mut placeholders = std::collections::HashMap::<(String, u32), (Handle<Mesh>, Option<Handle<Mesh>>)>::new();
    let mut counts = Vec::new();
    for (si, slot) in def.slots.iter().enumerate() {
        let files = assets_for(&def.id, &slot.kind);
        let places = place(slot, si, &mut taken, limit);
        let source = if !files.is_empty() {
            "assets"
        } else if slot.kind == "person" && crate::characters::available() {
            "recipes"
        } else {
            "placeholder"
        };
        counts.push(format!("{} {} ({source})", places.len(), slot.kind));
        for (k, pl) in places.iter().enumerate() {
            let y = shape.height(pl.at.x, pl.at.y);
            let at = Vec3::new(pl.at.x, y, pl.at.y);
            if slot.kind == "person" && files.is_empty() && crate::characters::available() {
                // People from seeded random recipes of the slot's height, in the place's style.
                let recipe = crate::characters::Recipe::for_height_in(si as u64 * 1000 + k as u64, pl.height, crate::characters::place_style(&def.id));
                let e = crate::characters::spawn(&mut commands, &assets, &recipe, at, pl.yaw);
                commands.entity(e).insert(EnvPart);
                if pl.height >= 3.0 {
                    commands.entity(e).insert((Occluder { height: pl.height }, crate::fade::Fade::shown()));
                }
                continue;
            }
            if slot.kind == "person" && files.is_empty() {
                let tf = Transform::from_translation(at).with_rotation(Quat::from_rotation_y(pl.yaw)).with_scale(Vec3::splat(pl.height / 1.75));
                let e = crate::bodies::spawn(&mut commands, &mut meshes, &palette, &style, "person", 100 + k as u32 + si as u32 * 100, false, tf, pl.at);
                commands.entity(e).insert(EnvPart);
                continue;
            }
            if !files.is_empty() {
                let file = &files[(hash(si as u32 * 31 + k as u32, 5) * files.len() as f32) as usize % files.len()];
                let vrm = file.contains("vroid-") || file.ends_with(".vrm");
                let model = Model { vrm, file: file.clone(), height: pl.height, ground_y: y, glow: slot.glow };
                let handle = assets.load(GltfAssetLabel::Scene(0).from_asset(file.clone()));
                let mut e = commands.spawn((EnvPart, model, WorldAssetRoot(handle), Transform::from_translation(at).with_rotation(Quat::from_rotation_y(pl.yaw)), Visibility::Hidden));
                if pl.height <= 1.6 {
                    e.insert(crate::lookdev::NoShadow);
                }
                if pl.height >= 3.0 {
                    e.insert((Occluder { height: pl.height }, crate::fade::Fade::shown()));
                }
                drop(e);
                if let Some((light, l_tf)) = local_light(&slot.kind, slot.glow, pl.height, k) {
                    commands.spawn((EnvPart, light, Transform::from_translation(at + l_tf.translation)));
                }
                continue;
            }
            let variant = (k % 3) as u32;
            let (body, glow) = placeholders
                .entry((slot.kind.clone(), variant))
                .or_insert_with(|| {
                    let (mut b, g) = placeholder(&slot.kind, variant * 17 + si as u32);
                    let _ = b.generate_outline_normals(&Default::default());
                    (meshes.add(b), g.map(|g| meshes.add(g)))
                })
                .clone();
            let tf = Transform::from_translation(at).with_rotation(Quat::from_rotation_y(pl.yaw)).with_scale(Vec3::splat(pl.height));
            let mut e = commands.spawn((EnvPart, Mesh3d(body), MeshMaterial3d(palette.vertex.clone()), tf, crate::style::stencil()));
            if pl.height >= 3.0 {
                e.insert((Occluder { height: pl.height }, crate::fade::Fade::shown()));
            }
            let light = local_light(&slot.kind, slot.glow, pl.height, k);
            if slot.height[1] > 1.5 && !matches!(slot.kind.as_str(), "cave_wall" | "tree") {
                e.insert(outline(Outlined::Thing, &style));
            }
            if let (Some(gm), Some([cr, cg, cb])) = (glow, slot.glow) {
                let c = [(cr * 255.0) as u8, (cg * 255.0) as u8, (cb * 255.0) as u8];
                let mat = palette.color(&mut toons, &style, c, true);
                e.with_children(|p| {
                    p.spawn((Mesh3d(gm), MeshMaterial3d(mat), Transform::default()));
                });
            }
            if let Some((l, l_tf)) = light {
                commands.spawn((EnvPart, l, Transform::from_translation(at + l_tf.translation)));
            }
        }
    }
    // `LIVING_GAME_CROWD`: a crowd in rows north of the centre too (measurement and photographs).
    for e in crate::characters::env_crowd(&mut commands, &assets, &def.id, Vec3::new(0.0, 0.0, -4.0), &|x, z| shape.height(x, z)) {
        commands.entity(e).insert(EnvPart);
    }
    info!("environment {}: {}", def.id, counts.join(", "));
    spawn_player(&mut commands, &mut meshes, &palette, &style, &look, &assets);
}

/// Walk with WASD (Shift to run) relative to the camera; the camera follows you.
#[allow(clippy::too_many_arguments)]
pub fn walk(
    mut roam: ResMut<Roam>,
    envs: Res<Envs>,
    look: Res<Lookdev>,
    cam: Res<Cam>,
    keys: Res<ButtonInput<KeyCode>>,
    ui: Res<crate::hud::UiWants>,
    mut input: ResMut<crate::controls::Input>,
    mut target: ResMut<crate::controls::Target>,
    mut players: Query<(&Player, &mut Transform, Option<&Fitted>, Option<&crate::lookdev::Model>, Has<crate::bodies::Beast>)>,
    island: Option<Res<crate::island::Island>>,
    time: Res<Time>,
    route: Option<Res<crate::route::Steer>>,
    probe: Option<Res<crate::probe::Probe>>,
    mut tilt: Local<Quat>,
) {
    let dt = time.delta_secs();
    let (up, right) = cam.control_axes();
    let mut d = Vec2::ZERO;
    if !ui.keyboard && !input.chat_open {
        for (k, v) in [(KeyCode::KeyW, up), (KeyCode::KeyS, -up), (KeyCode::KeyD, right), (KeyCode::KeyA, -right)] {
            if keys.pressed(k) {
                d += v;
            }
        }
    }
    // Scripted walking for measurements: `LIVING_GAME_AUTOWALK=<degrees>` (0 = north, 90 = east;
    // append `run` to run).
    let auto = std::env::var("LIVING_GAME_AUTOWALK").ok();
    let d = match auto.as_deref().and_then(|a| a.trim_end_matches("run").trim().parse::<f32>().ok()) {
        Some(deg) => Vec2::new(deg.to_radians().sin(), -deg.to_radians().cos()),
        // A scripted route (route.rs) sets the direction and speed.
        None => route.as_ref().and_then(|r| r.0).map_or(d.normalize_or_zero(), |r| r.0),
    };
    let run = keys.pressed(KeyCode::ShiftLeft) || keys.pressed(KeyCode::ShiftRight) || auto.as_deref().is_some_and(|a| a.ends_with("run")) || route.as_ref().and_then(|r| r.0).is_some_and(|r| r.1);
    // A speed ramp for measurements (`LIVING_GAME_RAMP`, probe.rs); standing at its ends.
    let ramp = probe.as_ref().and_then(|p| p.ramp_speed(time.elapsed_secs()));
    let d = if ramp.is_some_and(|s| s <= 0.0) { Vec2::ZERO } else { d };
    roam.moving = d != Vec2::ZERO;
    if ramp.is_some() && !roam.moving {
        roam.speed = 0.0;
    }
    roam.running = run;
    input.moving = roam.moving;
    if roam.moving {
        // Walking and running at the speeds the authored clips were made for.
        let speed = route.as_ref().and_then(|r| r.0).map_or(if run { crate::lookdev::RUN_SPEED } else { crate::lookdev::WALK_SPEED }, |r| r.2);
        let speed = ramp.unwrap_or(speed);
        roam.speed = speed;
        match &island {
            // On the island, water and rock stop you; slide along them.
            Some(i) => {
                let step = d * speed * dt;
                for s in [step, Vec2::new(step.x, 0.0), Vec2::new(0.0, step.y)] {
                    let next = roam.pos + s;
                    if s != Vec2::ZERO && i.walkable(next.x, next.y) {
                        roam.pos = next;
                        break;
                    }
                }
            }
            None => {
                let limit = if envs.ground.radius > 0.0 { envs.ground.radius - 2.0 } else { 28.0 };
                roam.pos = (roam.pos + d * speed * dt).clamp_length_max(limit);
            }
        }
        roam.facing = d;
    }
    let y = island.as_ref().map_or_else(|| envs.ground.height(roam.pos.x, roam.pos.y), |i| i.height(roam.pos.x, roam.pos.y));
    let f = roam.facing;
    for (p, mut tf, fitted, model, beast) in &mut players {
        tf.translation.x = roam.pos.x;
        tf.translation.z = roam.pos.y;
        tf.rotation = match p {
            // The figure faces +X; glTF models +Z; VRM models −Z.
            Player::Figure => Quat::from_rotation_y(-f.y.atan2(f.x)),
            Player::Model { vrm } => Quat::from_rotation_y(f.x.atan2(f.y) + if *vrm { PI } else { 0.0 }),
        };
        // An animal you walk as lies on the ground under its paws, as connected animals do.
        let mut y = y;
        if beast {
            let kind = model.map_or("wolf", |m| if m.file.contains("deer") { "deer" } else { "wolf" });
            let ground = |x: f32, z: f32| island.as_ref().map_or_else(|| envs.ground.height(x, z), |i| i.height(x, z));
            let (want, at) = crate::bodies::lie_on(kind, ground, roam.pos, f, 1.0);
            *tilt = tilt.slerp(want, 1.0 - (-dt * crate::bodies::TILT_RATE).exp());
            tf.rotation = *tilt * tf.rotation;
            y = at;
        }
        match (p, fitted) {
            (Player::Figure, _) => tf.translation.y = y,
            (_, Some(fit)) => tf.translation.y = y + fit.y_off,
            _ => {}
        }
    }
    target.0 = Some(look.focus.unwrap_or(Vec3::new(roam.pos.x, y, roam.pos.y)));
}

/// Glow needs HDR and bloom; `,` and `.` step through the environments.
pub fn hdr(mut commands: Commands, cams: Query<Entity, Added<Camera3d>>) {
    for e in &cams {
        commands.entity(e).insert((bevy::camera::Hdr, bevy::post_process::bloom::Bloom { intensity: 0.12, ..bevy::post_process::bloom::Bloom::NATURAL }));
    }
}

pub fn keys(keys: Res<ButtonInput<KeyCode>>, ui: Res<crate::hud::UiWants>, mut envs: ResMut<Envs>) {
    if ui.keyboard {
        return;
    }
    let n = envs.defs.len() + 1;
    if keys.just_pressed(KeyCode::Period) {
        envs.want = (envs.want + 1) % n;
    }
    if keys.just_pressed(KeyCode::Comma) {
        envs.want = (envs.want + n - 1) % n;
    }
}

/// A scripted tour: which environments, which shots, and progress.
#[derive(Clone)]
pub struct Tour {
    dir: std::path::PathBuf,
    /// Environment indices (0 = line-up).
    envs: Vec<usize>,
    shots: Vec<(String, crate::camera::View, f32)>,
    /// Environment, shot and stage within the shot, and when the stage began.
    at: (usize, usize, u8, f32),
}

impl Tour {
    fn from_env(dir: String, defs: &[EnvDef]) -> Self {
        let _ = std::fs::create_dir_all(&dir);
        let list = |k: &str| std::env::var(k).ok().filter(|v| !v.is_empty()).map(|v| v.split(',').map(|x| x.trim().to_string()).collect::<Vec<_>>());
        let envs = match list("LIVING_GAME_TOUR_ONLY") {
            Some(ids) => ids
                .iter()
                .filter_map(|id| {
                    let i = if id == "lineup" { Some(0) } else { defs.iter().position(|d| &d.id == id).map(|i| i + 1) };
                    if i.is_none() {
                        warn!("tour: no environment {id}");
                    }
                    i
                })
                .collect(),
            None => (0..=defs.len()).collect(),
        };
        let rig = crate::camera::Rig::default();
        let shots = list("LIVING_GAME_TOUR_SHOTS")
            .unwrap_or_else(|| vec!["default".into(), "close".into()])
            .into_iter()
            .filter_map(|s| {
                let v = match s.as_str() {
                    "default" => (rig.view, 0.0),
                    "close" => (crate::camera::View { pitch: 24.0, distance: 9.0, fov: 44.0 }, 0.0),
                    _ => {
                        let n: Vec<f32> = s.split(':').filter_map(|x| x.parse().ok()).collect();
                        if n.len() < 3 {
                            warn!("tour: bad shot {s} (want default, close or YAW:PITCH:DISTANCE[:FOV])");
                            return None;
                        }
                        (crate::camera::View { pitch: n[1], distance: n[2], fov: n.get(3).copied().unwrap_or(rig.view.fov) }, n[0])
                    }
                };
                Some((s.replace(':', "_"), v.0, v.1))
            })
            .collect();
        Self { dir: std::path::PathBuf::from(dir), envs, shots, at: (0, 0, 0, 0.0) }
    }
}

/// Run the tour: switch environment, wait for it to load, then pose and photograph each shot.
pub fn tour(mut commands: Commands, mut envs: ResMut<Envs>, mut cam: ResMut<Cam>, time: Res<Time>, target: Option<Res<crate::capture::Target>>, loading: Option<Res<crate::loading::Loading>>, mut exit: MessageWriter<AppExit>) {
    let Some(mut t) = envs.tour.clone() else { return };
    // Photographs wait for the first load's cover to lift (loading.rs).
    if !crate::loading::Loading::clear(loading.as_deref()) && t.at.2 == 1 {
        t.at.3 = time.elapsed_secs();
        envs.tour = Some(t);
        return;
    }
    let now = time.elapsed_secs();
    let (e, k, stage, since) = t.at;
    let Some(&env) = t.envs.get(e) else {
        if now - since > 0.8 {
            exit.write(AppExit::Success);
        }
        return;
    };
    let id = if env == 0 { "lineup".to_string() } else { envs.defs[env - 1].id.clone() };
    let Some((name, view, yaw)) = t.shots.get(k).cloned() else {
        t.at = (e + 1, 0, 0, now);
        envs.tour = Some(t);
        return;
    };
    // The first shot of an environment waits for its models to load; later ones only for the
    // camera to ease into place.
    let wait = if k == 0 { 6.0 } else { 2.0 };
    t.at = match stage {
        0 => {
            envs.want = env;
            // Shots wider than the default view may pull back past sight (vistas).
            cam.rig.sight_bound = view.distance <= crate::camera::Rig::default().view.distance;
            cam.rig.view = view;
            cam.set_yaw(yaw);
            (e, k, 1, now)
        }
        1 if now - since > wait => {
            crate::capture::shot(&mut commands, target.as_deref(), t.dir.join(format!("env-{id}-{name}.png")));
            info!("tour: {id} {name}");
            (e, k + 1, 0, now + 0.3)
        }
        _ => return,
    };
    envs.tour = Some(t);
}
