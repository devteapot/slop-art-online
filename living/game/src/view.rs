//! Asset view (`LIVING_GAME_VIEW=<files or folders, comma-separated>`): models shown through
//! the game's own renderer (toon material, outlines, finishing pass, bloom), on a 1 m checker,
//! so an asset is judged as the game will draw it.
//!
//! - `LIVING_GAME_VIEW_OUT=<dir>`: batch mode, headless (no window; `LIVING_GAME_WINDOW=1`
//!   shows it). For each model, take the shots, write `report.json` with measured size,
//!   triangles, materials, vertex colours, glow and clips, then quit.
//!   `living/tools/view_assets.sh` wraps this and makes one contact sheet per model.
//! - `LIVING_GAME_VIEW_SHOTS=<shot>[,<shot>…]` picks the shots (default `views,clips`):
//!   - a view: `front`, `three-quarter`, `side`, `back`, `above`, `game` (the default game
//!     camera, 28° down, 22 m) or `YAW:PITCH[:ZOOM[:AIM]]` (degrees; yaw 0 faces the model's
//!     front; zoom 1 frames the model, 0.5 is twice as close; aim is the height looked at as a
//!     fraction of the model's, 0.92 for a character's face);
//!   - `views`: the five angles and `game`;
//!   - `<clip>`: six frames of that clip from the side; `<clip>/<view>` from that view;
//!     `<clip>@<seconds>` or `<clip>@<seconds>/<view>`: one frame;
//!   - `clips`: six frames of each clip in `LIVING_GAME_VIEW_CLIP`.
//! - Without it: interactive. Left-drag orbits, the wheel zooms, `,` `.` change model, space
//!   pauses clips.
//! - `LIVING_GAME_VIEW_HEIGHT=<m>` scales every model to that height (default: the file's own
//!   size, which is real size for our generated assets).
//! - `LIVING_GAME_VIEW_ENV=<environment id>` lights the view with that environment's mood.
//! - `LIVING_GAME_HOUR=<h>` puts the sun at that hour's place (east at 6, west at 18).
//! - `LIVING_GAME_VIEW_ATMO=1` lights the view by the environments' day curve at that hour, as
//!   the game does (daylight.rs): light, sky, fog, grading and glow, so a night shot is night.
//!   Without it the view keeps its fixed mood and the hour only moves the sun.
//! - `LIVING_GAME_VIEW_CLIP=<name>[,<name>…]`: the clips to play and photograph (default: the
//!   first four).
//!
//! - `recipe:<name>` or `recipe:<folk>:<seed>` in `LIVING_GAME_VIEW` shows a character recipe
//!   (`assets/characters/recipes.json`; folks `adult`, `giant`, `small`) at its own height.
//!
//! Files outside the asset folder are copied into `assets/view/` (git-ignored) first, since the
//! asset server reads only under its root.

use crate::lookdev::{asset_root, glb_json, has_glow, Fitted, Lookdev, Model};
use crate::style::Style;
use crate::world::{rgb, MeshBuf, Palette};
use bevy::input::mouse::{AccumulatedMouseMotion, AccumulatedMouseScroll};
use bevy::prelude::*;
use std::path::{Path, PathBuf};

pub fn enabled() -> bool {
    std::env::var("LIVING_GAME_VIEW").is_ok_and(|v| !v.is_empty())
}

/// Whether the view is lit by the day curve (`LIVING_GAME_VIEW_ATMO=1`, with the asset view on).
pub fn day_curve() -> bool {
    use std::sync::OnceLock;
    static ON: OnceLock<bool> = OnceLock::new();
    *ON.get_or_init(|| enabled() && std::env::var("LIVING_GAME_VIEW_ATMO").is_ok_and(|v| v == "1"))
}

/// Named camera angles for photographs: (name, yaw°, pitch°). Yaw 0 looks at a model's front
/// (glTF models face +Z).
const ANGLES: [(&str, f32, f32); 5] = [("front", 0.0, 8.0), ("three-quarter", 40.0, 18.0), ("side", 90.0, 8.0), ("back", 180.0, 8.0), ("above", 30.0, 62.0)];
const CLIP_FRAMES: usize = 6;

#[derive(Clone, Copy, Debug)]
enum Pose {
    /// `aim`: the height looked at, as a fraction of the model's height (default its middle).
    Orbit { yaw: f32, pitch: f32, zoom: f32, aim: Option<f32> },
    Game,
}

/// One photograph: a name, a camera pose, and optionally a clip held at a time (seconds).
#[derive(Clone, Debug)]
struct Shot {
    name: String,
    pose: Pose,
    clip: Option<(usize, f32)>,
}

fn parse_view(s: &str) -> Option<(String, Pose)> {
    if s == "game" {
        return Some(("game".into(), Pose::Game));
    }
    if let Some((n, yaw, pitch)) = ANGLES.iter().find(|a| a.0 == s) {
        return Some((n.to_string(), Pose::Orbit { yaw: *yaw, pitch: *pitch, zoom: 1.0, aim: None }));
    }
    let n: Vec<f32> = s.split(':').map(|x| x.parse().ok()).collect::<Option<_>>()?;
    (n.len() >= 2).then(|| (s.replace(':', "_"), Pose::Orbit { yaw: n[0], pitch: n[1], zoom: n.get(2).copied().unwrap_or(1.0), aim: n.get(3).copied() }))
}

/// The shots for a model with these clips (see the module docs for the grammar).
fn parse_shots(spec: &str, clips: &[(String, f32)], default_clips: &[usize], file: &str) -> Vec<Shot> {
    let side = Pose::Orbit { yaw: 90.0, pitch: 8.0, zoom: 1.0, aim: None };
    let film = |c: usize, view: &str, pose: Pose| -> Vec<Shot> {
        (0..CLIP_FRAMES).map(|f| Shot { name: format!("{}-{f}{}", sanitize(&clips[c].0), view), pose, clip: Some((c, clips[c].1 * f as f32 / CLIP_FRAMES as f32)) }).collect()
    };
    let mut shots = Vec::new();
    for tok in spec.split(',').map(str::trim).filter(|t| !t.is_empty()) {
        if tok == "views" {
            shots.extend(ANGLES.iter().map(|a| a.0).chain(["game"]).filter_map(parse_view).map(|(name, pose)| Shot { name, pose, clip: None }));
        } else if tok == "clips" {
            for &c in default_clips {
                shots.extend(film(c, "", side));
            }
        } else if let Some((name, pose)) = parse_view(tok) {
            shots.push(Shot { name, pose, clip: None });
        } else {
            let (clip_part, view) = tok.split_once('/').map_or((tok, None), |(a, b)| (a, Some(b)));
            let (cname, at) = clip_part.split_once('@').map_or((clip_part, None), |(a, b)| (a, b.parse::<f32>().ok()));
            let Some(c) = clips.iter().position(|x| x.0 == cname) else {
                if !clips.is_empty() || !cname.is_empty() {
                    warn!("view: {file}: no clip or view {tok}");
                }
                continue;
            };
            let (vname, pose) = match view.map(parse_view) {
                Some(Some((n, p))) => (format!("-{n}"), p),
                Some(None) => {
                    warn!("view: bad view in {tok}");
                    continue;
                }
                None => (String::new(), side),
            };
            match at {
                Some(t) => shots.push(Shot { name: format!("{}@{t}{vname}", sanitize(cname)), pose, clip: Some((c, t)) }),
                None => shots.extend(film(c, &vname, pose)),
            }
        }
    }
    shots
}

/// One model on view.
#[derive(Component)]
pub struct Item {
    index: usize,
    /// Animation clips in file order, with names, and the graph nodes playing them.
    clips: Vec<(String, f32)>,
    /// What to photograph.
    shots: Vec<Shot>,
    /// The clip to play while not photographing a clip.
    first_clip: usize,
    graph: Option<(Handle<Gltf>, Vec<AnimationNodeIndex>, Entity)>,
    /// The model's own turn to face the camera (VRM 0.x models face −Z).
    turn: Quat,
}

#[derive(Resource)]
pub struct ViewState {
    files: Vec<String>,
    out: Option<PathBuf>,
    focus: usize,
    yaw: f32,
    pitch: f32,
    zoom: f32,
    paused: bool,
    /// Batch progress: model index, step within its shots, time the step began.
    batch: (usize, usize, f32),
    reports: Vec<serde_json::Value>,
    started: f32,
    /// Batch: how the model in focus is turned (radians about +Y) and moved (m) for the frame
    /// photographed, as the game moves a body for its clip: a turn take turns along its curve,
    /// a take with its own track moves along it, a gait on its belt moves at its speed.
    shift: (f32, Vec3),
    /// The mood's fog distances: the day curve scales them every frame, and in the game the
    /// camera resets them first (camera::follow), so the view does that here.
    fog: Option<bevy::pbr::FogFalloff>,
}

/// Resolve the requested files to paths under the asset folder.
fn requested() -> Vec<String> {
    let root = PathBuf::from(asset_root());
    let mut files = Vec::new();
    for part in std::env::var("LIVING_GAME_VIEW").unwrap_or_default().split(',').map(str::trim).filter(|p| !p.is_empty()) {
        // A character recipe (characters.rs): `recipe:<name>` or `recipe:<folk>:<seed>`.
        if part.starts_with("recipe:") {
            files.push(part.to_string());
            continue;
        }
        let p = PathBuf::from(part);
        let abs = if p.is_absolute() { p } else if root.join(&p).exists() { root.join(&p) } else { std::env::current_dir().unwrap_or_default().join(&p) };
        let mut found = Vec::new();
        collect(&abs, &mut found);
        found.sort();
        for f in found {
            let rel = match f.strip_prefix(&root) {
                Ok(r) => r.to_string_lossy().to_string(),
                Err(_) => {
                    // Outside the asset folder: copy it in.
                    let name = f.file_name().unwrap_or_default().to_string_lossy().to_string();
                    let dst = root.join("view").join(&name);
                    let _ = std::fs::create_dir_all(root.join("view"));
                    if let Err(e) = std::fs::copy(&f, &dst) {
                        warn!("view: cannot copy {}: {e}", f.display());
                        continue;
                    }
                    format!("view/{name}")
                }
            };
            files.push(rel);
        }
    }
    files
}

fn collect(p: &Path, out: &mut Vec<PathBuf>) {
    if p.is_dir() {
        for e in std::fs::read_dir(p).into_iter().flatten().flatten() {
            collect(&e.path(), out);
        }
    } else if p.extension().is_some_and(|x| x == "glb" || x == "gltf" || x == "vrm") {
        out.push(p.to_path_buf());
    }
}

/// Clip names and durations from the file's JSON (the largest sampler input time per animation).
fn clip_list(json: &serde_json::Value) -> Vec<(String, f32)> {
    let Some(anims) = json["animations"].as_array() else { return vec![] };
    anims
        .iter()
        .enumerate()
        .map(|(i, a)| {
            let name = a["name"].as_str().map(String::from).unwrap_or_else(|| format!("clip{i}"));
            let dur = a["samplers"].as_array().into_iter().flatten().filter_map(|s| json["accessors"][s["input"].as_u64()? as usize]["max"][0].as_f64()).fold(0.0, f64::max);
            (name, dur as f32)
        })
        .collect()
}

#[allow(clippy::too_many_arguments)]
pub fn setup(
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    palette: Res<Palette>,
    mut style: ResMut<Style>,
    mut look: ResMut<Lookdev>,
    assets: Res<AssetServer>,
    mut lights: Query<&mut DirectionalLight>,
    mut cams: Query<&mut DistanceFog, With<Camera3d>>,
    mut clear: ResMut<ClearColor>,
    mut clock: Option<ResMut<crate::daylight::Clock>>,
) {
    let files = requested();
    let height: f32 = std::env::var("LIVING_GAME_VIEW_HEIGHT").ok().and_then(|h| h.parse().ok()).unwrap_or(0.0);
    let out = std::env::var("LIVING_GAME_VIEW_OUT").ok().filter(|d| !d.is_empty()).map(PathBuf::from);
    info!("view: {} model(s){}", files.len(), out.as_ref().map(|o| format!(", photographs to {}", o.display())).unwrap_or_default());
    // Mood: an environment's, or the look-dev default.
    let mut ground = [108u8, 128, 96];
    if let Some(id) = std::env::var("LIVING_GAME_VIEW_ENV").ok().filter(|i| !i.is_empty()) {
        match crate::envs::load_defs().into_iter().find(|d| d.id == id) {
            Some(def) => {
                crate::envs::apply_mood(&def.mood, &mut style, &mut look, &mut lights, &mut cams, &mut clear);
                ground = def.ground.color;
            }
            None => warn!("view: no environment {id}"),
        }
    }
    // `LIVING_GAME_HOUR` moves the sun (east at 6, overhead at 12, west at 18), to light a
    // model from other angles.
    // The day clock (daylight.rs) writes the hour every frame, so it is set and stopped there.
    if let Some(h) = std::env::var("LIVING_GAME_HOUR").ok().and_then(|h| h.parse::<f32>().ok()) {
        look.hour = h;
        if let Some(clock) = clock.as_mut() {
            clock.hours = h as f64;
            clock.day_minutes = 0.0;
        }
    }
    // A 1 m checker, as an outline stencil.
    let mut g = MeshBuf::default();
    let r: i32 = 40;
    for j in -r..r {
        for i in -r..r {
            let (x, z) = (i as f32, j as f32);
            if Vec2::new(x + 0.5, z + 0.5).length() > r as f32 {
                continue;
            }
            let k = if (i + j).rem_euclid(2) == 0 { 1.0 } else { 0.9 };
            let c = rgb((ground[0] as f32 * k) as u8, (ground[1] as f32 * k) as u8, (ground[2] as f32 * k) as u8);
            g.quad([Vec3::new(x, 0.0, z), Vec3::new(x, 0.0, z + 1.0), Vec3::new(x + 1.0, 0.0, z + 1.0), Vec3::new(x + 1.0, 0.0, z)], c);
        }
    }
    commands.spawn((Mesh3d(meshes.add(g.build())), MeshMaterial3d(palette.vertex.clone()), Transform::default(), crate::style::ground_stencil()));
    for (index, token) in files.iter().enumerate() {
        let recipe = token.strip_prefix("recipe:").map(|r| {
            crate::characters::Recipe::parse(r).unwrap_or_else(|| {
                warn!("view: no recipe {r}");
                crate::characters::Recipe::random(0, "adult")
            })
        });
        let file = &recipe.as_ref().map_or(token.clone(), |r| crate::lookdev::animated(&r.base));
        let json = glb_json(file);
        // A generated person's clips may come from the shared clip file (`anim::clip_file`).
        let clip_src = crate::anim::clip_file(file);
        let clips = if clip_src == *file { json.as_ref().map(clip_list) } else { glb_json(&clip_src).as_ref().map(clip_list) }.unwrap_or_default();
        let is_vrm = file.ends_with(".vrm") || file.contains("vroid-") || json.as_ref().is_some_and(|j| j["extensions"]["VRM"].is_object() || j["extensions"]["VRMC_vrm"].is_object());
        // VRM 0.x models face −Z; turn them to face the camera. Models with clips aren't given
        // the procedural rig (`vrm: false`), so their own animation plays.
        let turn = Quat::from_rotation_y(if is_vrm && !file.contains("VRMC") { std::f32::consts::PI } else { 0.0 });
        let model = Model { vrm: is_vrm && (clips.is_empty() || recipe.is_some()), file: file.clone(), height: recipe.as_ref().map_or(height, |r| r.height), ground_y: 0.0, glow: None };
        // The root alone: the clips' load of it below must not read the file a second time
        // (`characters::SceneOf`).
        let handle = assets.load::<Gltf>(file.clone());
        let wanted: Vec<String> = std::env::var("LIVING_GAME_VIEW_CLIP").unwrap_or_default().split(',').map(|c| c.trim().to_string()).filter(|c| !c.is_empty()).collect();
        let shown: Vec<usize> = if wanted.is_empty() { (0..clips.len().min(4)).collect() } else { clips.iter().enumerate().filter(|(_, c)| wanted.contains(&c.0)).map(|(i, _)| i).collect() };
        let spec = std::env::var("LIVING_GAME_VIEW_SHOTS").ok().filter(|s| !s.is_empty()).unwrap_or_else(|| "views,clips".into());
        let shots = parse_shots(&spec, &clips, &shown, file);
        let first_clip = shown.first().copied().unwrap_or(0);
        let graph = (!clips.is_empty()).then(|| (assets.load::<Gltf>(clip_src.clone()), vec![], Entity::PLACEHOLDER));
        let mut e = commands.spawn((model, Item { index, clips, shots, first_clip, graph, turn }, crate::characters::SceneOf(handle), Transform::from_rotation(turn), Visibility::Hidden));
        if let Some(r) = recipe {
            // A recipe's character: rigged for its face, shaped, recoloured and sprung.
            e.insert(crate::characters::Character { recipe: r, stride: 1.0 });
        }
    }
    commands.insert_resource(ViewState {
        files,
        out,
        focus: 0,
        yaw: 30.0,
        pitch: 15.0,
        zoom: 1.0,
        paused: false,
        batch: (0, 0, 0.0),
        reports: vec![],
        started: 0.0,
        shift: (0.0, Vec3::ZERO),
        fog: cams.iter().next().map(|f| f.falloff.clone()),
    });
}

/// Start each model's clips once the file and its animation player are loaded.
#[allow(clippy::type_complexity)]
pub fn clips(
    mut commands: Commands,
    state: Res<ViewState>,
    gltfs: Res<Assets<Gltf>>,
    mut graphs: ResMut<Assets<AnimationGraph>>,
    mut items: Query<(Entity, &mut Item), With<Fitted>>,
    children: Query<&Children>,
    mut players: Query<&mut AnimationPlayer>,
) {
    for (e, mut item) in &mut items {
        let clip_names: Vec<String> = item.clips.iter().map(|c| c.0.clone()).collect();
        let pick = item.first_clip;
        let Some((handle, nodes, player)) = item.graph.as_mut() else { continue };
        if !nodes.is_empty() {
            continue;
        }
        let Some(gltf) = gltfs.get(handle.id()) else { continue };
        let Some(p) = children.iter_descendants(e).find(|d| players.contains(*d)) else { continue };
        let (graph, idx) = AnimationGraph::from_clips(gltf.animations.iter().cloned());
        *nodes = idx;
        *player = p;
        commands.entity(p).insert(AnimationGraphHandle(graphs.add(graph)));
        if let (Ok(mut pl), Some(n)) = (players.get_mut(p), nodes.get(pick)) {
            pl.play(*n).repeat();
        }
        info!("view: {} plays {:?}", state.files[item.index], clip_names.get(pick));
    }
}

/// Lay the models out in a row by their measured widths, and show only the one in focus in batch
/// mode.
pub fn layout(state: Res<ViewState>, mut items: Query<(&Item, &Fitted, &mut Transform, &mut Visibility)>, mut fogs: Query<&mut bevy::pbr::DistanceFog, With<Camera3d>>) {
    if let (true, Some(base)) = (day_curve(), state.fog.as_ref()) {
        for mut f in &mut fogs {
            f.falloff = base.clone();
        }
    }
    let mut order: Vec<_> = items.iter_mut().collect();
    order.sort_by_key(|(it, ..)| it.index);
    let batch = state.out.is_some();
    let mut x = 0.0;
    for (item, fit, tf, vis) in order {
        let tf = tf.into_inner();
        let w = fit.size.x.max(fit.size.z) + 1.5;
        let at = if batch { 0.0 } else { x + w / 2.0 };
        x += w;
        let (yaw, off) = if batch && item.index == state.focus { state.shift } else { (0.0, Vec3::ZERO) };
        tf.rotation = Quat::from_rotation_y(yaw) * item.turn;
        let c = item.turn * fit.center;
        tf.translation.x = at - c.x + off.x;
        tf.translation.z = -c.z + off.z;
        *vis.into_inner() = if !batch || item.index == state.focus { Visibility::Inherited } else { Visibility::Hidden };
    }
}

/// Bounds of the model in focus, for framing: (centre, half extents), down to the ground.
fn framing(state: &ViewState, items: &Query<(&Item, &Fitted, &GlobalTransform)>) -> Option<(Vec3, Vec3)> {
    let (_, fit, g) = items.iter().find(|(it, ..)| it.index == state.focus)?;
    let c = g.translation() + g.rotation() * fit.center;
    let half = Vec3::new(fit.size.x.max(fit.size.z), fit.size.y, fit.size.x.max(fit.size.z)) * 0.5;
    let lo = (c - half).min(Vec3::new(c.x, 0.0, c.z));
    let hi = c + half;
    Some(((lo + hi) * 0.5, (hi - lo) * 0.5))
}

fn place_camera(tf: &mut Transform, proj: &mut Projection, centre: Vec3, half: Vec3, yaw: f32, pitch: f32, zoom: f32) {
    let fov = 35f32;
    if let Projection::Perspective(p) = proj {
        p.fov = fov.to_radians();
    }
    let radius = half.length().max(0.5);
    let dist = radius / (fov.to_radians() * 0.5).tan() * 1.05 * zoom;
    let (y, p) = (yaw.to_radians(), pitch.to_radians());
    let dir = Vec3::new(y.sin() * p.cos(), p.sin(), y.cos() * p.cos());
    *tf = Transform::from_translation(centre + dir * dist).looking_at(centre, Vec3::Y);
}

/// The game's default camera, looking at a model's foot from the south.
fn game_camera(tf: &mut Transform, proj: &mut Projection, at: Vec3) {
    let v = crate::camera::Rig::default().view;
    if let Projection::Perspective(p) = proj {
        p.fov = v.fov.to_radians();
    }
    let p = v.pitch.to_radians();
    let target = at + Vec3::Y * 1.0;
    *tf = Transform::from_translation(target + Vec3::new(0.0, p.sin(), p.cos()) * v.distance).looking_at(target, Vec3::Y);
}

/// Interactive view: orbit, zoom, change model, pause clips.
#[allow(clippy::too_many_arguments)]
pub fn interact(
    mut state: ResMut<ViewState>,
    keys: Res<ButtonInput<KeyCode>>,
    buttons: Res<ButtonInput<MouseButton>>,
    motion: Res<AccumulatedMouseMotion>,
    scroll: Res<AccumulatedMouseScroll>,
    items: Query<(&Item, &Fitted, &GlobalTransform)>,
    mut cam: Query<(&mut Transform, &mut Projection), With<Camera3d>>,
    mut players: Query<&mut AnimationPlayer>,
) {
    if state.out.is_some() {
        return;
    }
    let n = state.files.len().max(1);
    if keys.just_pressed(KeyCode::Period) {
        state.focus = (state.focus + 1) % n;
    }
    if keys.just_pressed(KeyCode::Comma) {
        state.focus = (state.focus + n - 1) % n;
    }
    if keys.just_pressed(KeyCode::Space) {
        state.paused = !state.paused;
        for mut p in &mut players {
            if state.paused {
                p.pause_all();
            } else {
                p.resume_all();
            }
        }
    }
    if buttons.pressed(MouseButton::Left) {
        state.yaw -= motion.delta.x * 0.3;
        state.pitch = (state.pitch + motion.delta.y * 0.3).clamp(-10.0, 89.0);
    }
    state.zoom = (state.zoom * (1.0 - scroll.delta.y * 0.08)).clamp(0.2, 4.0);
    let Some((c, h)) = framing(&state, &items) else { return };
    if let Ok((mut tf, mut proj)) = cam.single_mut() {
        place_camera(&mut tf, &mut proj, c, h, state.yaw, state.pitch, state.zoom);
    }
}

/// Batch photographs and the report, one model at a time.
#[allow(clippy::too_many_arguments)]
pub fn batch(
    mut commands: Commands,
    mut state: ResMut<ViewState>,
    time: Res<Time>,
    all: Query<(&Item, Option<&Fitted>)>,
    items: Query<(&Item, &Fitted, &GlobalTransform)>,
    roots: Query<(Entity, &Item)>,
    mut cam: Query<(&mut Transform, &mut Projection), With<Camera3d>>,
    mut players: Query<&mut AnimationPlayer>,
    children: Query<&Children>,
    mesh_q: Query<(&Mesh3d, Option<&bevy::gltf::GltfMaterialName>)>,
    meshes: Res<Assets<Mesh>>,
    target: Option<Res<crate::capture::Target>>,
    mut exit: MessageWriter<AppExit>,
) {
    let Some(out) = state.out.clone() else { return };
    let now = time.elapsed_secs();
    if state.started == 0.0 {
        state.started = now.max(1e-3);
    }
    let (i, step, at) = state.batch;
    if i >= state.files.len() {
        let _ = std::fs::write(out.join("report.json"), serde_json::to_string_pretty(&state.reports).unwrap_or_default());
        info!("view: done, {} model(s)", state.files.len());
        exit.write(AppExit::Success);
        return;
    }
    state.focus = i;
    let file = state.files[i].clone();
    let stem = Path::new(&file).file_stem().unwrap_or_default().to_string_lossy().to_string();
    let dir = out.join(&stem);
    let Some((item, fitted)) = all.iter().find(|(it, _)| it.index == i) else { return };
    // Wait for the model to load (it is fitted once its meshes have bounds), up to 30 s.
    if fitted.is_none() || (item.graph.as_ref().is_some_and(|g| g.1.is_empty()) && now - state.started < 30.0) {
        if now - state.started > 30.0 {
            warn!("view: {file} did not load");
            state.reports.push(serde_json::json!({ "file": file, "error": "did not load within 30 s" }));
            // As after a finished model: the next one starts at its own first step (which
            // makes its folder).
            state.batch = (i + 1, 0, 0.0);
            state.started = now;
        }
        return;
    }
    if step == 0 && at == 0.0 {
        let _ = std::fs::create_dir_all(&dir);
        state.batch = (i, 0, now);
        return;
    }
    let Some((c, h)) = framing(&state, &items) else { return };
    let Ok((mut tf, mut proj)) = cam.single_mut() else { return };
    // Each shot: pose the camera (and clip), let the frame settle, photograph, move on.
    let settle = if step == 0 { 1.5 } else { 0.6 };
    let name = if let Some(shot) = item.shots.get(step) {
        match shot.pose {
            Pose::Orbit { yaw, pitch, zoom, aim } => place_camera(&mut tf, &mut proj, aim.map_or(c, |a| Vec3::new(c.x, c.y - h.y + 2.0 * h.y * a, c.z)), h, yaw, pitch, zoom),
            Pose::Game => game_camera(&mut tf, &mut proj, Vec3::new(c.x, 0.0, c.z)),
        }
        if let (Some((clip, t)), Some((_, nodes, p))) = (shot.clip, &item.graph) {
            if let (Ok(mut pl), Some(node)) = (players.get_mut(*p), nodes.get(clip)) {
                pl.stop_all();
                pl.play(*node).seek_to(t).pause();
            }
            state.shift = shift_of(&file, &item.clips[clip].0, t);
        } else {
            state.shift = (0.0, Vec3::ZERO);
        }
        if shot.clip.is_some() { format!("clip-{}", shot.name) } else { shot.name.clone() }
    } else {
        // Report, then the next model (after the last photograph has been saved).
        if now - at < 0.8 {
            return;
        }
        let root = roots.iter().find(|(_, it)| it.index == i).map(|(e, _)| e);
        let (mut tris, mut verts, mut colours, mut mats) = (0usize, 0usize, true, Vec::<String>::new());
        let mut n_meshes = 0;
        if let Some(root) = root {
            for d in children.iter_descendants(root) {
                if let Ok((m, mn)) = mesh_q.get(d) {
                    if let Some(mesh) = meshes.get(&m.0) {
                        n_meshes += 1;
                        verts += mesh.count_vertices();
                        tris += mesh.indices().map_or(mesh.count_vertices(), |ix| ix.len()) / 3;
                        colours &= mesh.attribute(Mesh::ATTRIBUTE_COLOR).is_some();
                    }
                    if let Some(n) = mn {
                        if !mats.contains(&n.0) {
                            mats.push(n.0.clone());
                        }
                    }
                }
            }
        }
        let (_, fit, _) = items.iter().find(|(it, ..)| it.index == i).unwrap();
        let report = serde_json::json!({
            "file": file,
            "size_m": [fit.size.x, fit.size.y, fit.size.z],
            "meshes": n_meshes,
            "triangles": tris,
            "vertices": verts,
            "vertex_colours": colours && n_meshes > 0,
            "materials": mats,
            "glow": has_glow(&file),
            "clips": item.clips.iter().map(|(n, d)| serde_json::json!({ "name": n, "seconds": d })).collect::<Vec<_>>(),
            "photos": dir.display().to_string(),
        });
        let _ = std::fs::write(dir.join("report.json"), serde_json::to_string_pretty(&report).unwrap_or_default());
        state.reports.push(report);
        info!("view: {file} done");
        state.batch = (i + 1, 0, 0.0);
        state.started = now;
        return;
    };
    if now - at > settle {
        crate::capture::shot(&mut commands, target.as_deref(), dir.join(format!("{step:02}-{name}.png")));
        state.batch = (i, step + 1, now + 0.3);
    }
}

/// How the game turns and moves a body for `clip` at `t` s (see [`ViewState::shift`]), facing
/// +Z: its left is +X, and a turn to the right (the game's sense) turns it clockwise from above.
fn shift_of(file: &str, clip: &str, t: f32) -> (f32, Vec3) {
    let file = &crate::anim::clip_file(file);
    let gaits = crate::gait::of(file);
    let Some(info) = gaits.info(clip) else { return (0.0, Vec3::ZERO) };
    let len = info.seconds.max(1e-3);
    let yaw = -info.turned(t / len);
    let o = info.path_at(t);
    let mut off = Vec3::new(o.x, 0.0, o.y);
    if let Some((speed, deg)) = crate::gait::belt(file, clip) {
        let d = deg.to_radians();
        off += Vec3::new(-d.sin(), 0.0, d.cos()) * speed * t;
    }
    (yaw, off)
}

fn sanitize(s: &str) -> String {
    s.chars().map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' }).collect()
}
