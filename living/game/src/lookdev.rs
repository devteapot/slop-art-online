//! Look-dev mode (`LIVING_GAME_LOOKDEV=1`): a small fixed scene for judging the look without
//! the server. Every glTF/GLB in `living/game/assets/lookdev/` is loaded and laid out in an arc
//! on a patch of ground, beside a 1.75 m reference figure; each model is converted to the shared
//! toon material and outlined. The game camera works as in play (`[` `]` rotate); the sun's
//! hour is a slider (F1 → Look dev). With `LIVING_GAME_DEMO=<dir>` it photographs the scene from
//! four sides, at sunset, and without the toon look, then quits.

use crate::camera::Cam;
use crate::style::{outline, Kind, Outlined, Style, Toon};
use crate::world::{rgb, MeshBuf, Palette};
use bevy::prelude::*;
use bevy::render::view::screenshot::{save_to_disk, Screenshot};
use std::collections::{HashMap, HashSet};

pub fn enabled() -> bool {
    std::env::var("LIVING_GAME_LOOKDEV").is_ok_and(|v| !v.is_empty() && v != "0")
}

/// Where look-dev models are read from (under the asset folder).
const FOLDER: &str = "lookdev";

/// What look-dev characters do.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Act {
    Idle,
    Walk,
    Talk,
}

#[derive(Resource)]
pub struct Lookdev {
    /// Sun hour (6 = sunrise, 12 = noon, 18 = sunset).
    pub hour: f32,
    pub act: Act,
    /// The speed the line-up and crowds walk at in place (m/s; `LIVING_GAME_ACT=walk@2.6`): it
    /// picks their clip and cadence as it would for a body moving that fast (`gait.rs`).
    pub walk_speed: f32,
    pub models: Vec<String>,
    demo: Option<(std::path::PathBuf, usize, f32)>,
    /// Where the camera looks instead of the player (scripted close-ups).
    pub focus: Option<Vec3>,
}

/// A loaded look-dev model's root; `vrm` models face −Z (Unity convention) and get turned.
#[derive(Component)]
pub struct Model {
    pub vrm: bool,
    /// Path under the asset folder.
    pub file: String,
    /// Height to scale the model to (m; 0 keeps the file's own size), and the ground level it
    /// stands on.
    pub height: f32,
    pub ground_y: f32,
    /// Emissive colour for glowing things (multiplies the base colour).
    pub glow: Option<[f32; 3]>,
}

impl Model {
    pub fn character(file: String, vrm: bool) -> Self {
        Self { vrm, file, height: 1.75, ground_y: 0.0, glow: None }
    }
}

/// A model already scaled to its height; `y_off` lifts its lowest point onto the ground.
/// `size` and `center` are its bounds in metres, `center` relative to the root's origin before
/// its rotation.
#[derive(Component)]
pub struct Fitted {
    pub y_off: f32,
    pub size: Vec3,
    pub center: Vec3,
}

/// On a model's root: its glow (lit panes, a furnace's mouth, a lamp's glass) is people's light,
/// damped by daylight by the world's `daylight` law ([`night_glow`]): it shows at dusk and by
/// night and is out by day, so a lit window is not paler than its neighbours at noon. Lots and
/// a kit's fixtures carry it; glowing plants and crystals shine by day too.
#[derive(Component)]
pub struct NightGlow;

/// On a model's root: a fire that is out (`world::things`): its glowing materials don't glow.
#[derive(Component)]
pub struct Unlit;

/// The toon materials of [`NightGlow`] models that glow, with their glow as authored, and the
/// daylight share last applied to them.
#[derive(Resource, Default)]
pub struct NightGlows {
    mats: HashMap<AssetId<Toon>, LinearRgba>,
    applied: Option<f32>,
}

/// How dark it is at an hour (0 day to 1 night, in steps of 0.05): the world's `daylight` law
/// when connected (`verbs::Rules`), else the shipped script's (look-dev), read once per minute
/// of the day.
fn darkness(rules: Option<&crate::verbs::Rules>, hour: f32) -> f32 {
    if let Some(sc) = rules.and_then(|r| r.scripts.as_ref()) {
        return sc.dark(hour);
    }
    static SHIPPED: std::sync::OnceLock<Vec<f32>> = std::sync::OnceLock::new();
    let day = SHIPPED.get_or_init(|| match living_rules::script::Scripts::new(include_str!("../../scripts/skills.rhai")) {
        Ok(sc) => (0..24 * 60).map(|m| sc.dark(m as f32 / 60.0)).collect(),
        Err(e) => {
            warn!("night glow: the shipped script does not compile ({e}); glow stays as authored");
            Vec::new()
        }
    });
    day.get(((hour.rem_euclid(24.0) * 60.0) as usize).min(24 * 60 - 1)).copied().unwrap_or(1.0)
}

/// Damp the glow of [`NightGlow`] models' materials by daylight; written only when the
/// darkness changes (at most 20 steps a dusk) or a new glowing material appears.
pub fn night_glow(clock: Res<crate::daylight::Clock>, rules: Option<NonSend<crate::verbs::Rules>>, mut glows: ResMut<NightGlows>, mut toons: ResMut<Assets<Toon>>) {
    if glows.mats.is_empty() {
        return;
    }
    let dark = darkness(rules.as_deref(), clock.hour());
    if glows.applied == Some(dark) {
        return;
    }
    glows.applied = Some(dark);
    for (id, glow) in &glows.mats {
        if let Some(mut m) = toons.get_mut(*id) {
            m.base.emissive = *glow * dark;
        }
    }
    debug!("night glow: {} materials at {dark:.2} of their glow (hour {:.2})", glows.mats.len(), clock.hour());
}

/// On a model's root: its meshes cast no shadow (grass, flowers, small props: many, and their
/// shadows barely read).
#[derive(Component)]
pub struct NoShadow;

/// A character's face mesh: never casts a shadow (see `convert`, `character_shadows`).
#[derive(Component)]
pub struct FacePart;

/// Characters cast shadows only near the camera: a VRoid body is ~95 meshes drawn into every
/// shadow cascade, the largest single cost on the island (≈5.7 ms for a dozen people), and a far
/// character's shadow is a few pixels.
pub fn character_shadows(
    mut commands: Commands,
    cams: Query<&GlobalTransform, With<Camera3d>>,
    mut chars: Query<(Entity, &GlobalTransform, &mut CastsShadow), (With<crate::characters::Character>, With<Fitted>)>,
    children: Query<&Children>,
    meshes: Query<(), (With<Mesh3d>, Without<FacePart>)>,
) {
    const NEAR: f32 = 26.0;
    let Ok(cam) = cams.single() else { return };
    for (e, g, mut casts) in &mut chars {
        let want = g.translation().distance(cam.translation()) < NEAR;
        if casts.0 == Some(want) {
            continue;
        }
        casts.0 = Some(want);
        for d in children.iter_descendants(e) {
            if meshes.contains(d) {
                if want {
                    commands.entity(d).remove::<bevy::light::NotShadowCaster>();
                } else {
                    commands.entity(d).insert(bevy::light::NotShadowCaster);
                }
            }
        }
    }
}

/// Where characters change to their far model (`person.py --lod both`: the far model's meshes
/// are nodes named `Far*` on the same skeleton as the full model's). `LIVING_GAME_FAR=<m>`
/// (default 10; `0` never changes to it), for a 1.75 m character and in proportion to height,
/// as the spring bones' distance is; `LIVING_GAME_FAR_BAND=<m>` (default 1.5) is how much nearer
/// a far character must come before it changes back, so one at the edge doesn't flicker.
#[derive(Resource, Clone, Copy, Debug)]
pub struct FarModels {
    pub at: f32,
    pub band: f32,
}

impl FarModels {
    pub fn from_env() -> Self {
        let num = |k: &str, d: f32| std::env::var(k).ok().and_then(|v| v.parse::<f32>().ok()).unwrap_or(d);
        Self { at: num("LIVING_GAME_FAR", 10.0).max(0.0), band: num("LIVING_GAME_FAR_BAND", 1.5).max(0.0) }
    }

    /// Whether a character `d` m from the camera, `height` m tall, shows its far model, given
    /// what it shows now (None: not decided yet).
    pub fn far(&self, d: f32, height: f32, now: Option<bool>) -> bool {
        if self.at <= 0.0 {
            return false;
        }
        let d = d * 1.75 / height.max(0.3);
        match now {
            Some(true) => d > self.at - self.band,
            _ => d > self.at,
        }
    }
}

/// A character's full and far meshes (empty `far`: its file has no far model), and which shows.
#[derive(Component)]
pub struct Lod {
    near: Vec<Entity>,
    far: Vec<Entity>,
    pub far_now: Option<bool>,
}

impl Lod {
    /// Whether this character can change to a far model.
    pub fn has_far(&self) -> bool {
        !self.far.is_empty()
    }
}

/// Show each character's far model beyond [`FarModels`]'s distance and its full model nearer.
/// Both are skinned to the same bones, so one animation player, one set of spring bones and one
/// shaped skeleton serve both; the far model has no morph targets (blinking and the mouth stop
/// beyond the change). Hidden meshes draw in no view: neither shadows (`character_shadows`) nor
/// outlines. The animation runs on whichever shows. A mesh is far when it or a node above it
/// below the character is named `Far*`; meshes that join a character later (an outfit piece, a
/// style) join its lists and take the side it shows.
#[allow(clippy::type_complexity)]
pub fn far_models(
    mut commands: Commands,
    settings: Res<FarModels>,
    cams: Query<&GlobalTransform, With<Camera3d>>,
    new: Query<(Entity, &GlobalTransform, &Model), (With<crate::characters::Character>, Without<Lod>)>,
    mut chars: Query<(&GlobalTransform, &Model, &mut Lod)>,
    added: Query<Entity, Added<Mesh3d>>,
    children: Query<&Children>,
    parents: Query<&ChildOf>,
    names: Query<&Name>,
    meshes: Query<(), With<Mesh3d>>,
    mut vis: Query<&mut Visibility>,
) {
    let cam = cams.single().ok().map(|c| c.translation());
    let show = |lod: &Lod, far: bool, vis: &mut Query<&mut Visibility>| {
        let (show, hide) = if far { (&lod.far, &lod.near) } else { (&lod.near, &lod.far) };
        for (list, v) in [(show, Visibility::Inherited), (hide, Visibility::Hidden)] {
            for m in list {
                if let Ok(mut x) = vis.get_mut(*m) {
                    *x = v;
                }
            }
        }
    };
    // Far when it or a node above it (below the character) is named Far*.
    let is_far = |d: Entity, e: Entity| {
        let mut at = d;
        loop {
            if names.get(at).is_ok_and(|n| n.as_str().starts_with("Far")) {
                return true;
            }
            match parents.get(at) {
                Ok(p) if p.parent() != e => at = p.parent(),
                _ => return false,
            }
        }
    };
    // Decided as soon as the scene is in, before the model is first shown (`fit`), so the two
    // never draw together.
    let mut fresh = Vec::new();
    for (e, g, model) in &new {
        if !children.iter_descendants(e).any(|d| meshes.contains(d)) {
            continue;
        }
        fresh.push(e);
        let (mut near, mut far) = (vec![], vec![]);
        for d in children.iter_descendants(e).filter(|d| meshes.contains(*d)) {
            if is_far(d, e) {
                far.push(d);
            } else {
                near.push(d);
            }
        }
        let mut lod = Lod { near, far, far_now: None };
        if lod.has_far() {
            debug!("far models: {} has {} full and {} far meshes", model.file, lod.near.len(), lod.far.len());
            let far = cam.is_some_and(|c| settings.far(g.translation().distance(c), model.height, None));
            show(&lod, far, &mut vis);
            lod.far_now = Some(far);
        }
        commands.entity(e).insert(lod);
    }
    // Meshes that joined a character already listed (outfit pieces, styles).
    for d in &added {
        let mut at = d;
        while let Ok(p) = parents.get(at) {
            at = p.parent();
            if fresh.contains(&at) {
                break;
            }
            if let Ok((_, _, mut lod)) = chars.get_mut(at) {
                if lod.near.contains(&d) || lod.far.contains(&d) {
                    break;
                }
                let far = is_far(d, at);
                if far { lod.far.push(d) } else { lod.near.push(d) }
                if let Some(now) = lod.far_now.filter(|_| lod.has_far()) {
                    if let Ok(mut x) = vis.get_mut(d) {
                        *x = if far == now { Visibility::Inherited } else { Visibility::Hidden };
                    }
                }
                break;
            }
        }
    }
    let Some(cam) = cam else { return };
    for (g, model, mut lod) in &mut chars {
        if !lod.has_far() {
            continue;
        }
        let want = settings.far(g.translation().distance(cam), model.height, lod.far_now);
        if lod.far_now != Some(want) {
            lod.far_now = Some(want);
            show(&lod, want, &mut vis);
        }
    }
}

/// Whether a character's body currently casts shadows (None until first decided).
#[derive(Component, Default)]
pub struct CastsShadow(Option<bool>);

/// A mesh entity already given the toon material and outline.
#[derive(Component)]
pub struct Converted;

pub fn asset_root() -> String {
    format!("{}/assets", env!("CARGO_MANIFEST_DIR"))
}

/// The models in the look-dev folder.
pub fn lookdev_models() -> Vec<String> {
    let dir = std::path::Path::new(&asset_root()).join(FOLDER);
    let mut models: Vec<String> = std::fs::read_dir(&dir)
        .map(|r| r.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().to_string()).filter(|n| n.ends_with(".glb") || n.ends_with(".gltf")).collect())
        .unwrap_or_default();
    models.sort();
    models
}

pub fn setup(mut commands: Commands) {
    let models = lookdev_models();
    info!("look-dev: {} model(s) in {FOLDER}", models.len());
    let demo = std::env::var("LIVING_GAME_DEMO").ok().filter(|d| !d.is_empty() && std::env::var("LIVING_GAME_TOUR").is_err()).map(|d| {
        let _ = std::fs::create_dir_all(&d);
        (std::path::PathBuf::from(d), 0usize, 0.0)
    });
    // What the line-up does at the start (`LIVING_GAME_ACT=idle|walk[@<m/s>]|talk`; F1 → Look
    // dev too).
    let spec = std::env::var("LIVING_GAME_ACT").unwrap_or_default();
    let (act, walk_speed) = spec.split_once('@').map_or((spec.as_str(), WALK_SPEED), |(a, v)| (a, v.parse().unwrap_or(WALK_SPEED)));
    let act = match act {
        "walk" => Act::Walk,
        "talk" => Act::Talk,
        _ => Act::Idle,
    };
    commands.insert_resource(Lookdev { hour: 15.0, act, walk_speed, models, demo, focus: None });
}

/// The character line-up: every look-dev model in an arc beside the reference figure.
pub fn build_lineup(commands: &mut Commands, meshes: &mut Assets<Mesh>, palette: &Palette, style: &Style, assets: &AssetServer, models: &[String]) {
    // Ground: a disc of grass, as a stencil for outlines.
    let mut g = MeshBuf::default();
    let ring = |r: f32, a: f32| Vec3::new(r * a.cos(), 0.0, r * a.sin());
    for i in 0..64 {
        let (a0, a1) = (i as f32 / 64.0 * std::f32::consts::TAU, (i + 1) as f32 / 64.0 * std::f32::consts::TAU);
        g.tri([Vec3::ZERO, ring(30.0, a1), ring(30.0, a0)], rgb(112, 160, 74));
    }
    commands.spawn((crate::envs::EnvPart, Mesh3d(meshes.add(g.build())), MeshMaterial3d(palette.vertex.clone()), Transform::default(), crate::style::ground_stencil()));
    // The reference figure at the centre, facing the camera's side (+Z is south); it is the
    // character you walk around with here.
    let figure = crate::bodies::spawn(commands, meshes, palette, style, "person", 1, false, Transform::from_rotation(Quat::from_rotation_y(-std::f32::consts::FRAC_PI_2)), Vec2::ZERO);
    commands.entity(figure).insert((crate::envs::EnvPart, crate::envs::Player::Figure));
    let n = models.len().max(1) as f32;
    for (i, name) in models.iter().enumerate() {
        let a = std::f32::consts::PI * (1.1 + 0.8 * (i as f32 + 0.5) / n);
        let r = 5.0 + 1.5 * (i % 2) as f32;
        let at = Vec3::new(r * a.cos(), 0.0, r * a.sin());
        // VRoid characters come from recipes (their own look by default).
        if name.starts_with("vroid-") {
            let recipe = crate::characters::Recipe::default_for(&format!("{FOLDER}/{name}"));
            let e = crate::characters::spawn(commands, assets, &recipe, at, 0.0);
            commands.entity(e).insert(crate::envs::EnvPart);
            continue;
        }
        let file = animated(&format!("{FOLDER}/{name}"));
        // The root alone, so a character of the same file spawned while it loads does not read
        // it a second time (`characters::SceneOf`).
        let handle = assets.load::<bevy::gltf::Gltf>(file.clone());
        // glTF models face +Z, toward the camera's default side (south); VRM models face −Z.
        let vrm = name.ends_with(".vrm");
        let turn = Quat::from_rotation_y(if vrm { std::f32::consts::PI } else { 0.0 });
        commands.spawn((crate::envs::EnvPart, Model::character(file, vrm), crate::characters::SceneOf(handle), Transform::from_translation(at).with_rotation(turn), Visibility::Hidden));
    }
    // `LIVING_GAME_CROWD=N[:seed][:style]`: N seeded random characters in rows south of the
    // line-up, facing the default camera (shots from yaw 0 at about 35 m see them from the front).
    if let Some((n, seed, look)) = crate::characters::crowd_from_env() {
        let look = look.unwrap_or_else(|| crate::characters::DEFAULT_STYLE.into());
        for e in crate::characters::spawn_crowd(commands, assets, n, seed, &look, Vec3::new(0.0, 0.0, 22.0), &|_, _| 0.0) {
            commands.entity(e).insert(crate::envs::EnvPart);
        }
    }
}

/// Give every mesh of a loaded model the shared toon material and an outline.
#[allow(clippy::type_complexity)]
pub fn convert(
    mut commands: Commands,
    style: Res<Style>,
    mut toons: ResMut<Assets<Toon>>,
    standards: Res<Assets<StandardMaterial>>,
    mut meshes: ResMut<Assets<Mesh>>,
    assets: Res<AssetServer>,
    q: Query<(Entity, &MeshMaterial3d<StandardMaterial>, &Mesh3d, Option<&bevy::gltf::GltfMaterialName>, Option<&bevy::gltf::GltfMaterialExtras>), Without<Converted>>,
    parents: Query<&ChildOf>,
    models: Query<(&Model, Has<NoShadow>, Has<crate::bodies::Beast>, Has<NightGlow>, Has<Unlit>)>,
    mut glows: ResMut<NightGlows>,
    detail: Option<Res<crate::style::DetailLayers>>,
    palette: Res<Palette>,
    mut done: Local<(HashMap<(AssetId<StandardMaterial>, u32), AssetId<Toon>>, HashSet<AssetId<Mesh>>, HashMap<String, AssetId<Toon>>)>,
) {
    for (e, mat, mesh, name, extras) in &q {
        // Only meshes under a look-dev model.
        let mut cur = e;
        let mut owner = None;
        while let Ok(p) = parents.get(cur) {
            cur = p.parent();
            if let Ok(m) = models.get(cur) {
                owner = Some(m);
                break;
            }
        }
        let Some((owner, no_shadow, beast, night, unlit)) = owner else { continue };
        if no_shadow {
            commands.entity(e).insert(bevy::light::NotShadowCaster);
        }
        // A rigged creature (the wolf) is vertex-coloured on a white material: it wears the
        // shared vertex-colour toon the box creatures wear, so a pack adds no material.
        if beast {
            if done.1.insert(mesh.0.id()) {
                if let Some(mut m) = meshes.get_mut(&mesh.0) {
                    crate::style::outline_normals(&mut m);
                }
            }
            commands.entity(e).remove::<MeshMaterial3d<StandardMaterial>>().insert((MeshMaterial3d(palette.vertex.clone()), Converted, outline(Outlined::Person, &style)));
            continue;
        }
        // A slot's glow lights up models with no glow of their own (kits without emissive
        // materials); models that carry emissive materials keep exactly those.
        let glow = owner.glow.filter(|_| !has_glow(&owner.file));
        let glow_key = glow.map_or(0, |g| (g[0] * 255.0) as u32 | ((g[1] * 255.0) as u32) << 8 | ((g[2] * 255.0) as u32) << 16 | 1 << 24) | u32::from(night) << 25 | u32::from(unlit) << 26;
        let Some(base) = standards.get(&mat.0) else { continue };
        // VRoid names materials …_SKIN, …_FACE, …_EYE, …_HAIR, …_CLOTH; the face's own skin is
        // `…Face_00_SKIN`.
        let n = name.map_or("", |n| n.0.as_str());
        let skin = n.ends_with("_SKIN") || n.contains("Skin") || n.contains("skin");
        let kind = match () {
            _ if owner.vrm && n.contains("_HAIR") => Kind::Hair,
            _ if owner.vrm && skin && n.contains("Face") => Kind::Face,
            _ if skin => Kind::Skin,
            _ if owner.vrm && (n.contains("_FACE") || n.contains("_EYE")) => Kind::FacePart,
            _ => Kind::Plain,
        };
        // A face's shadow map (living/tools/face_normals.py, run by gen_anim.sh and
        // gen_person.sh) sits beside its file, or, for a town's faces on shared pages, is the
        // page's map that the face material's extras name (`face_map`, a path under the asset
        // folder: share.py `pages`), so every face on a page is one material. Without one the
        // face shades as skin.
        let face_map = (kind == Kind::Face)
            .then(|| {
                let own = owner.file.trim_end_matches(".glb").to_string() + ".face.png";
                std::iter::once(own).chain(extras.and_then(|x| face_map_of(&x.value))).find(|f| std::path::Path::new(&asset_root()).join(f).exists())
            })
            .flatten();
        let kind = if kind == Kind::Face && face_map.is_none() { Kind::Skin } else { kind };
        // Face parts (eyes, lashes, brows, mouth, the face itself) are many small morphing
        // meshes whose shadows never read: they never cast one.
        if owner.vrm && name.is_some_and(|n| n.0.contains("_FACE") || n.0.contains("_EYE") || n.0.contains("Face")) {
            commands.entity(e).insert((bevy::light::NotShadowCaster, FacePart));
        }
        // Generated scenery (untextured, vertex-coloured, not a character) takes the painted
        // surfaces its vertex colours' alpha names (style.rs `Surface`). It is one flag for all
        // of it, so scenery keeps sharing its few materials.
        let painted = detail.as_deref().filter(|_| !owner.vrm && kind == Kind::Plain && base.base_color_texture.is_none());
        // The caches hold ids, not handles: a material lives while some mesh wears it (a
        // town's outfit pieces go when its people do, and the first load's prewarm leaves none
        // behind, `loading.rs`), and is made again when needed.
        let (by_source, _, by_content) = &mut *done;
        let cached = by_source.get(&(mat.0.id(), glow_key)).and_then(|id| toons.get_strong_handle(*id));
        let toon = match cached {
            Some(h) => h,
            None => {
                let mut b = base.clone();
                if owner.vrm && crate::perf::has("charopaque") && matches!(b.alpha_mode, AlphaMode::Mask(_)) {
                    b.alpha_mode = AlphaMode::Opaque;
                }
                if let Some([r, g, bl]) = glow {
                    let c = b.base_color.to_linear();
                    b.emissive = LinearRgba::new(c.red * r, c.green * g, c.blue * bl, 1.0) * 8.0 + LinearRgba::new(r, g, bl, 1.0) * 2.0;
                }
                // A fire that is out: its flame's materials as they are, unlit.
                if unlit {
                    b.emissive = LinearRgba::BLACK;
                }
                // Every model file brings its own copies of the same few materials (the
                // environment kits share 14 between about a thousand). One toon material per
                // distinct content lets their meshes share bind groups and batches; each extra
                // material costs every view and pass a batch set and its per-frame buffer writes.
                // People's light is its own material: its glow follows the daylight.
                let night = night && b.emissive != LinearRgba::BLACK;
                let authored = b.emissive;
                let content = format!("{kind:?} {face_map:?} {} {night} {b:?}", painted.is_some());
                let h = by_content.get(&content).and_then(|id| toons.get_strong_handle(*id)).unwrap_or_else(|| {
                    let map = face_map.as_ref().map(|f| assets.load_builder().with_settings(|s: &mut bevy::image::ImageLoaderSettings| s.is_srgb = false).load(f.clone()));
                    let mut toon = style.kind(b, kind, map);
                    if let Some(layers) = painted {
                        crate::style::with_detail(&mut toon, layers);
                    }
                    toons.add(toon)
                });
                by_content.insert(content, h.id());
                by_source.insert((mat.0.id(), glow_key), h.id());
                if night && !glows.mats.contains_key(&h.id()) {
                    glows.mats.insert(h.id(), authored);
                    glows.applied = None;
                }
                h
            }
        };
        // Only meshes with an outline volume need outline normals. Scenery takes part only as a
        // stencil at zero offset, which never reads them; generating them anyway rewrote every
        // new scenery mesh (another attribute, so another upload in another vertex layout), and a
        // first-seen model's meshes made a 150 ms frame on the development Mac.
        let volume = owner.vrm || owner.file.starts_with("lookdev/") || owner.file.starts_with("view/");
        if volume && done.1.insert(mesh.0.id()) {
            if let Some(mut m) = meshes.get_mut(&mesh.0) {
                crate::style::outline_normals(&mut m);
            }
        }
        // Characters get shell outlines. Environment models only take part as stencils (they hide
        // outlines behind them); their lines come from the finishing pass, which respects what is
        // actually visible. Shell outlines on buildings drew their buried bases through hillsides.
        let mut ec = commands.entity(e);
        if owner.vrm && crate::perf::has("nohair") && name.is_some_and(|n| n.0.contains("_HAIR")) {
            ec.insert(Visibility::Hidden);
        }
        ec.remove::<MeshMaterial3d<StandardMaterial>>().insert((MeshMaterial3d(toon), Converted));
        if owner.vrm {
            ec.insert(outline(Outlined::Person, &style));
        } else if owner.file.starts_with("lookdev/") || owner.file.starts_with("view/") {
            ec.insert(outline(Outlined::Thing, &style));
        } else if !crate::perf::has("nostencil") {
            ec.insert(crate::style::stencil());
        }
    }
}

/// The shadow map a face material's glTF extras name (`{"face_map": "lookdev/pages/…face.png"}`).
fn face_map_of(extras: &str) -> Option<String> {
    serde_json::from_str::<serde_json::Value>(extras).ok()?["face_map"].as_str().map(String::from)
}

/// Scale each model to a 1.75 m character once its meshes have bounds, then show it.
#[allow(clippy::type_complexity)]
pub fn fit(
    mut roots: Query<(Entity, &Model, &mut Transform, &mut Visibility), Without<Fitted>>,
    children: Query<&Children>,
    meshes: Query<(&bevy::camera::primitives::Aabb, &GlobalTransform), With<Mesh3d>>,
    root_gtf: Query<&GlobalTransform>,
    mut commands: Commands,
) {
    for (e, model, mut tf, mut vis) in &mut roots {
        let Ok(rg) = root_gtf.get(e) else { continue };
        let inv = rg.affine().inverse();
        let (mut lo, mut hi, mut any) = (Vec3::splat(f32::MAX), Vec3::splat(f32::MIN), false);
        for d in children.iter_descendants(e) {
            if let Ok((aabb, g)) = meshes.get(d) {
                let (c, h) = (Vec3::from(aabb.center), Vec3::from(aabb.half_extents));
                for k in 0..8 {
                    let s = Vec3::new(if k & 1 == 0 { -1.0 } else { 1.0 }, if k & 2 == 0 { -1.0 } else { 1.0 }, if k & 4 == 0 { -1.0 } else { 1.0 });
                    // Into the root's own space, so its current scale doesn't count.
                    let p = inv.transform_point3(g.transform_point(c + h * s));
                    lo = lo.min(p);
                    hi = hi.max(p);
                }
                any = true;
            }
        }
        if !any {
            continue;
        }
        let span = (hi.y - lo.y).max(0.01);
        // Models built with a foundation below their floor (buildings.py) stand on their origin
        // and are measured above it; everything else stands on its lowest point.
        let founded = lo.y < -0.05 * span && hi.y > 0.0;
        let (base, height) = if founded { (0.0, hi.y.max(0.01)) } else { (lo.y, span) };
        let k = if model.height > 0.0 { model.height / height } else { 1.0 };
        tf.scale = Vec3::splat(k);
        tf.translation.y = model.ground_y - base * k;
        *vis = Visibility::Inherited;
        debug!("look-dev: fitted {} ({height:.2} units) to {:.2} m (×{k:.2})", model.file, model.height);
        let y_off = -base * k;
        // The box's middle from the root's origin, as `size` measures it: foundation included (a
        // quay's wall stands mostly below its floor; the box used to be centred half its height
        // above the floor, so it stood above the wall).
        let center = (lo + hi) * 0.5 * k;
        commands.entity(e).insert(Fitted { y_off, size: (hi - lo) * k, center });
    }
}

/// A VRoid humanoid's bones (VRoid's `J_Bip_*` names; rest rotations are identity) and the face's
/// blink and mouth blend shapes.
#[derive(Component)]
pub struct Rig {
    bones: HashMap<&'static str, Entity>,
    /// Which way each arm points at rest (+1 or −1 along X), to lower it out of the T-pose.
    arm_side: [f32; 2],
    face: Option<(Entity, usize, usize)>,
    seed: f32,
    /// The file carries animation clips: the body plays them (`clips`), and only the face is
    /// moved here.
    clips: bool,
}

const BONES: [&str; 13] = [
    "J_Bip_C_Hips", "J_Bip_C_Spine", "J_Bip_C_Chest", "J_Bip_C_Neck", "J_Bip_C_Head",
    "J_Bip_L_UpperArm", "J_Bip_R_UpperArm", "J_Bip_L_LowerArm", "J_Bip_R_LowerArm",
    "J_Bip_L_UpperLeg", "J_Bip_R_UpperLeg", "J_Bip_L_LowerLeg", "J_Bip_R_LowerLeg",
];

/// Find the rig of each fitted VRoid model.
pub fn rig(
    mut commands: Commands,
    models: Query<(Entity, &Model), (With<Fitted>, Without<Rig>)>,
    children: Query<&Children>,
    names: Query<&Name>,
    transforms: Query<&Transform>,
    morphs: Query<&MorphWeights>,
    meshes: Res<Assets<Mesh>>,
) {
    for (e, model) in &models {
        if !model.vrm {
            continue;
        }
        let mut bones = HashMap::new();
        let mut face = None;
        for d in children.iter_descendants(e) {
            if let Ok(n) = names.get(d) {
                if let Some(b) = BONES.iter().find(|b| n.as_str() == **b) {
                    bones.insert(*b, d);
                }
            }
            if let Ok(w) = morphs.get(d) {
                // Bevy reads target names from mesh extras; VRoid stores them on the primitive, so
                // fall back to reading the file's glTF JSON.
                let node = names.get(d).map(|n| n.as_str().to_string()).unwrap_or_default();
                let targets = w
                    .first_mesh()
                    .and_then(|m| meshes.get(m))
                    .and_then(|m| m.morph_target_names().map(|t| t.to_vec()))
                    .filter(|t| !t.is_empty())
                    .or_else(|| target_names(&model.file, &node));
                if let Some(t) = targets {
                    let find = |suffix: &str| t.iter().position(|n| n.ends_with(suffix));
                    if let (Some(blink), Some(mouth)) = (find("Fcl_EYE_Close"), find("Fcl_MTH_A")) {
                        face = Some((d, blink, mouth));
                    }
                }
            }
        }
        if bones.len() < BONES.len() {
            continue;
        }
        let side = |lower: &str| bones.get(lower).and_then(|b| transforms.get(*b).ok()).map_or(1.0, |t| t.translation.x.signum());
        let arm_side = [side("J_Bip_L_LowerArm"), side("J_Bip_R_LowerArm")];
        info!("look-dev: rigged a VRoid model ({} bones, face {})", bones.len(), if face.is_some() { "found" } else { "missing" });
        let clips = crate::anim::has_clips(&model.file);
        commands.entity(e).insert(Rig { bones, arm_side, face, seed: (e.index_u32() % 97) as f32 * 0.37, clips });
    }
}

/// A character file's figure height (file units): the vertical span of its meshes' bounds at
/// rest (glTF accessor `min`/`max` through the node transforms), the far model's (`Far*` nodes)
/// left out. What `animate.py` measures the figure by; None without meshes.
pub fn figure_height(file: &str) -> Option<f32> {
    let corners = figure_corners(file);
    let (lo, hi) = corners.iter().fold((f32::MAX, f32::MIN), |(lo, hi), c| (lo.min(c.y), hi.max(c.y)));
    (hi > lo).then_some(hi - lo)
}

/// The corners of each near mesh's bounds at rest in a character file (file units, cached):
/// what [`figure_height`] spans, and what a composed person's figure is put together from
/// (`characters::compose::figure_height`, a style file's through its type's `hair_fit`).
pub fn figure_corners(file: &str) -> std::sync::Arc<Vec<Vec3>> {
    use std::sync::{Arc, Mutex, OnceLock};
    static CACHE: OnceLock<Mutex<HashMap<String, Arc<Vec<Vec3>>>>> = OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    if let Some(v) = cache.lock().unwrap().get(file) {
        return v.clone();
    }
    let v = (|| {
        let j = glb_json(file)?;
        let nodes = j["nodes"].as_array()?;
        let f = |v: &serde_json::Value, i: usize, d: f32| v.get(i).and_then(|x| x.as_f64()).map_or(d, |x| x as f32);
        let local = |n: &serde_json::Value| {
            let (t, r, s) = (&n["translation"], &n["rotation"], &n["scale"]);
            Mat4::from_scale_rotation_translation(Vec3::new(f(s, 0, 1.0), f(s, 1, 1.0), f(s, 2, 1.0)), Quat::from_xyzw(f(r, 0, 0.0), f(r, 1, 0.0), f(r, 2, 0.0), f(r, 3, 1.0)), Vec3::new(f(t, 0, 0.0), f(t, 1, 0.0), f(t, 2, 0.0)))
        };
        let mut parent = HashMap::new();
        for (i, n) in nodes.iter().enumerate() {
            for c in n["children"].as_array().into_iter().flatten().filter_map(|c| c.as_u64()) {
                parent.insert(c as usize, i);
            }
        }
        let mut out = Vec::new();
        for (i, n) in nodes.iter().enumerate() {
            let Some(mesh) = n["mesh"].as_u64() else { continue };
            if n["name"].as_str().is_some_and(|s| s.starts_with("Far")) {
                continue;
            }
            let mut m = local(n);
            let mut at = i;
            while let Some(&p) = parent.get(&at) {
                m = local(&nodes[p]) * m;
                at = p;
            }
            for prim in j["meshes"][mesh as usize]["primitives"].as_array().into_iter().flatten() {
                let a = &j["accessors"][prim["attributes"]["POSITION"].as_u64()? as usize];
                let (amin, amax) = (&a["min"], &a["max"]);
                for k in 0..8 {
                    let pick = |axis: usize| if k >> axis & 1 == 0 { f(amin, axis, 0.0) } else { f(amax, axis, 0.0) };
                    out.push(m.transform_point3(Vec3::new(pick(0), pick(1), pick(2))));
                }
            }
        }
        Some(out)
    })()
    .unwrap_or_default();
    let v = Arc::new(v);
    cache.lock().unwrap().insert(file.to_string(), v.clone());
    v
}

/// Whether a GLB file has any emissive material (cached per file).
pub fn has_glow(file: &str) -> bool {
    use std::sync::{Mutex, OnceLock};
    static CACHE: OnceLock<Mutex<HashMap<String, bool>>> = OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    if let Some(v) = cache.lock().unwrap().get(file) {
        return *v;
    }
    let v = (|| {
        let json = glb_json(file)?;
        Some(json["materials"].as_array()?.iter().any(|m| {
            m["emissiveFactor"].as_array().is_some_and(|f| f.iter().any(|x| x.as_f64().unwrap_or(0.0) > 0.01)) || m["name"].as_str().is_some_and(|n| n.contains("Glow"))
        }))
    })()
    .unwrap_or(false);
    cache.lock().unwrap().insert(file.to_string(), v);
    v
}

/// The JSON chunk of a GLB file under the asset folder.
pub fn glb_json(file: &str) -> Option<serde_json::Value> {
    use std::io::Read;
    // Only the header and the JSON chunk: character files are tens of MB of buffers.
    let mut f = std::fs::File::open(std::path::Path::new(&asset_root()).join(file)).ok()?;
    let mut head = [0u8; 20];
    f.read_exact(&mut head).ok()?;
    if &head[0..4] != b"glTF" {
        return None;
    }
    let len = u32::from_le_bytes(head[12..16].try_into().ok()?) as usize;
    let mut json = vec![0u8; len];
    f.read_exact(&mut json).ok()?;
    serde_json::from_slice(&json).ok()
}

/// Morph target names of the mesh on node `node`, from a GLB file's JSON (mesh or primitive extras).
fn target_names(file: &str, node: &str) -> Option<Vec<String>> {
    let json = glb_json(file)?;
    let mesh = json["nodes"].as_array()?.iter().find(|n| n["name"] == node)?["mesh"].as_u64()? as usize;
    let m = &json["meshes"][mesh];
    let names = if m["extras"]["targetNames"].is_array() { &m["extras"]["targetNames"] } else { &m["primitives"][0]["extras"]["targetNames"] };
    Some(names.as_array()?.iter().filter_map(|v| v.as_str().map(String::from)).collect())
}

/// Blink every few seconds; the mouth moves while talking: look-dev's Talk act, or the line
/// this body is speaking in a world (`mouth.rs`, `speaking`).
fn face(rig: &Rig, look: &Lookdev, morphs: &mut Query<&mut MorphWeights>, t: f32, speaking: Option<f32>) {
    let Some((face, blink, mouth)) = rig.face else { return };
    let Ok(mut w) = morphs.get_mut(face) else { return };
    let cycle = (t % 3.7) / 3.7;
    let close = if cycle > 0.96 { ((cycle - 0.96) / 0.04 * std::f32::consts::PI).sin() } else { 0.0 };
    let talk = if look.act == Act::Talk { ((t * 11.0).sin() * 0.5 + 0.5) * ((t * 2.3).sin() * 0.3 + 0.7) } else { 0.0 };
    let ws = w.weights_mut();
    if blink < ws.len() {
        ws[blink] = close;
    }
    if mouth < ws.len() {
        ws[mouth] = speaking.unwrap_or(talk * 0.8);
    }
}

/// Look-dev's walking and running speeds (m/s), the ones `animate.py` scales `walk` and `run` to
/// by default. Clips and their rates come from the actual speed (`gait.rs`).
pub const WALK_SPEED: f32 = 1.4;
pub const RUN_SPEED: f32 = 3.6;

/// Look-dev has no world laws: people's walk/run split is the clips' own
/// ([`crate::gait::Family::Clips`]) unless `LIVING_GAME_SPLIT=<m/s>` gives the one a world's laws
/// would (the geometric mean of its walk and run, `live.rs`), to measure walks past the clips'.
fn split_family() -> crate::gait::Family {
    static SPLIT: std::sync::OnceLock<Option<f32>> = std::sync::OnceLock::new();
    SPLIT.get_or_init(|| std::env::var("LIVING_GAME_SPLIT").ok().and_then(|v| v.parse().ok())).map_or(crate::gait::Family::Clips, crate::gait::Family::Split)
}

/// What models whose files carry clips (`assets/lookdev/anim/`, from
/// `living/tools/blender/animate.py`) do (`anim.rs` plays it): you walk or run by how you move;
/// the line-up and crowds stand, talk or walk in place at `walk_speed` (`LIVING_GAME_ACT`). Your
/// character also plays the probe's one-shots (`LIVING_GAME_ONESHOT`, probe.rs).
#[allow(clippy::type_complexity)]
pub fn clips(
    mut commands: Commands,
    look: Res<Lookdev>,
    roam: Res<crate::envs::Roam>,
    mut models: Query<(Entity, &Rig, Option<&mut crate::anim::Motion>, Has<crate::envs::Player>, Option<&crate::characters::Character>)>,
    mut beasts: Query<(Entity, Option<&mut crate::anim::Motion>), (With<crate::bodies::Beast>, With<crate::envs::Player>, Without<Rig>)>,
    probe: Option<Res<crate::probe::Probe>>,
    time: Res<Time>,
) {
    let now = time.elapsed_secs();
    // An animal you walk as (`LIVING_GAME_PLAYER=beast:<kind>`): its gaits by your speed.
    for (e, motion) in &mut beasts {
        let m = crate::anim::Motion { speed: if roam.moving { roam.speed } else { 0.0 }, now_ms: now as f64 * 1000.0, ..default() };
        match motion {
            Some(mut x) => *x = m,
            None => {
                commands.entity(e).insert(m);
            }
        }
    }
    for (e, rig, motion, is_player, ch) in &mut models {
        if !rig.clips {
            continue;
        }
        let mut m = crate::anim::Motion { stride: ch.map_or(1.0, |c| c.stride), now_ms: now as f64 * 1000.0, family: split_family(), ..default() };
        if is_player {
            m.speed = if roam.moving { roam.speed } else { 0.0 };
            m.action = probe.as_ref().and_then(|p| p.oneshot(now)).map(|(clip, rate, start)| crate::combat::Action {
                clip: crate::anim::intern(clip),
                rate,
                start_ms: start as f64 * 1000.0,
                hold: None,
                face: None,
                ..Default::default()
            });
        } else {
            match look.act {
                Act::Walk => m.speed = look.walk_speed,
                Act::Talk => m.stand = "talk",
                _ => {}
            }
        }
        match motion {
            Some(mut x) => *x = m,
            None => {
                commands.entity(e).insert(m);
            }
        }
    }
}

/// The animated version of a look-dev model, if `animate.py` has made one.
pub fn animated(file: &str) -> String {
    let p = std::path::Path::new(file);
    let alt = p.parent().unwrap_or(std::path::Path::new("")).join("anim").join(p.file_name().unwrap_or_default());
    if std::path::Path::new(&asset_root()).join(&alt).exists() {
        alt.to_string_lossy().to_string()
    } else {
        file.to_string()
    }
}

/// Procedural motion for VRoid characters: arms down, breathing, a walk cycle in place,
/// blinking, and the mouth moving while talking.
#[allow(clippy::too_many_arguments)]
pub fn animate(look: Res<Lookdev>, roam: Res<crate::envs::Roam>, rigs: Query<(Entity, &Rig, Has<crate::envs::Player>)>, mut transforms: Query<&mut Transform>, mut morphs: Query<&mut MorphWeights>, time: Res<Time>, mouths: Option<Res<crate::mouth::Mouths>>) {
    let t = time.elapsed_secs();
    for (e, rig, is_player) in &rigs {
        // In a world, a body's mouth is shut unless it is saying a line.
        let speaking = mouths.as_ref().map(|m| m.open.get(&e).copied().unwrap_or(0.0));
        let t = t + rig.seed;
        let mut set = |bone: &str, q: Quat| {
            if let Some(mut tf) = rig.bones.get(bone).and_then(|b| transforms.get_mut(*b).ok()) {
                tf.rotation = q;
            }
        };
        let walk = look.act == Act::Walk || (is_player && roam.moving);
        let phase = t * 6.0;
        if rig.clips {
            face(rig, &look, &mut morphs, t, speaking);
            continue;
        }
        let breathe = (t * 1.6).sin();
        // Arms down along the body (about 72° from the T-pose), swinging when walking; elbows
        // slightly bent.
        for (i, (upper, lower)) in [("J_Bip_L_UpperArm", "J_Bip_L_LowerArm"), ("J_Bip_R_UpperArm", "J_Bip_R_LowerArm")].iter().enumerate() {
            let s = rig.arm_side[i];
            let swing = if walk { (phase + i as f32 * std::f32::consts::PI).sin() * 0.45 } else { breathe * 0.02 };
            set(upper, Quat::from_rotation_z(-s * 1.25) * Quat::from_rotation_x(swing));
            set(lower, Quat::from_rotation_y(s * 0.25));
        }
        // Legs: stride and knee bend when walking.
        for (i, (upper, lower)) in [("J_Bip_L_UpperLeg", "J_Bip_L_LowerLeg"), ("J_Bip_R_UpperLeg", "J_Bip_R_LowerLeg")].iter().enumerate() {
            let p = phase + i as f32 * std::f32::consts::PI;
            let (hip, knee) = if walk { (p.sin() * 0.45, -(p + 1.2).sin().max(0.0) * 0.8) } else { (0.0, 0.0) };
            set(upper, Quat::from_rotation_x(hip));
            set(lower, Quat::from_rotation_x(knee));
        }
        // Breathing in the chest, a little sway and head movement.
        set("J_Bip_C_Chest", Quat::from_rotation_x(breathe * 0.025));
        set("J_Bip_C_Spine", Quat::from_rotation_y(if walk { phase.sin() * 0.08 } else { (t * 0.4).sin() * 0.03 }));
        set("J_Bip_C_Head", Quat::from_rotation_y((t * 0.5).sin() * 0.15) * Quat::from_rotation_x((t * 0.33).sin() * 0.05));
        if let Some(mut hips) = rig.bones.get("J_Bip_C_Hips").and_then(|b| transforms.get_mut(*b).ok()) {
            hips.rotation = Quat::from_rotation_z(if walk { phase.sin() * 0.04 } else { 0.0 });
        }
        face(rig, &look, &mut morphs, t, speaking);
    }
}

/// Move the sun with the hour: east at 6, high at noon, west at 18.
pub fn sun(look: Res<Lookdev>, mut lights: Query<&mut Transform, With<DirectionalLight>>) {
    let t = ((look.hour - 6.0) / 12.0).clamp(0.0, 1.0) * std::f32::consts::PI;
    let dir = Vec3::new(t.cos(), t.sin().max(0.08) * 1.2, 0.35).normalize();
    for mut tf in &mut lights {
        *tf = Transform::from_translation(dir * 60.0).looking_at(Vec3::ZERO, Vec3::Y);
    }
}

/// The scripted look-dev photographs.
#[allow(clippy::too_many_arguments)]
pub fn demo(
    mut commands: Commands,
    mut look: ResMut<Lookdev>,
    mut cam: ResMut<Cam>,
    mut style: ResMut<Style>,
    models: Query<(&Model, &Transform)>,
    time: Res<Time>,
    mut exit: MessageWriter<AppExit>,
) {
    let Some((dir, step, at)) = look.demo.clone() else { return };
    let now = time.elapsed_secs();
    // (wait before, action)
    let steps: [(f32, &str); 23] = [
        (6.0, "yaw0"),
        (2.0, "shot:lookdev-north"),
        (0.2, "close8"),
        (2.0, "shot:lookdev-8m"),
        (0.2, "close4"),
        (2.0, "shot:lookdev-4m"),
        (0.1, "walk"),
        (1.3, "shot:lookdev-4m-walking"),
        (0.1, "talk"),
        (1.0, "shot:lookdev-4m-talking"),
        (0.1, "idle"),
        (0.2, "far"),
        (0.2, "yaw90"),
        (2.0, "shot:lookdev-east"),
        (0.2, "yaw180"),
        (2.0, "shot:lookdev-south"),
        (0.2, "sunset"),
        (2.0, "shot:lookdev-sunset"),
        (0.2, "close8"),
        (2.0, "shot:lookdev-sunset-8m"),
        (0.2, "plain"),
        (1.5, "shot:lookdev-plain-8m"),
        (0.2, "far"),
    ];
    let Some((wait, act)) = steps.get(step).copied() else {
        exit.write(AppExit::Success);
        return;
    };
    if now - at < wait {
        return;
    }
    match act {
        "yaw0" => cam.set_yaw(0.0),
        // Conversation and close-up distances, aimed at the row of models behind the figure.
        "close8" => {
            cam.rig.view = crate::camera::View { pitch: 22.0, distance: 8.0, fov: 40.0 };
            cam.rig.sight_bound = false;
            // Close-ups frame the first anime (VRM) character, else the row's middle.
            look.focus = Some(models.iter().find(|(m, _)| m.vrm).map_or(Vec3::new(0.0, 0.0, -5.0), |(_, t)| Vec3::new(t.translation.x, 0.0, t.translation.z)));
        }
        "close4" => cam.rig.view = crate::camera::View { pitch: 15.0, distance: 4.5, fov: 40.0 },
        "walk" => look.act = Act::Walk,
        "talk" => look.act = Act::Talk,
        "idle" => look.act = Act::Idle,
        "far" => {
            cam.rig.view = crate::camera::Rig::default().view;
            look.focus = None;
        }
        "yaw90" => cam.set_yaw(90.0),
        "yaw180" => cam.set_yaw(180.0),
        "sunset" => {
            cam.set_yaw(0.0);
            look.hour = 17.6;
        }
        "plain" => {
            look.hour = 15.0;
            style.enabled = false;
        }
        s if s.starts_with("shot:") => {
            let path = dir.join(format!("{}.png", &s[5..]));
            info!("look-dev: screenshot {}", path.display());
            commands.spawn(Screenshot::primary_window()).observe(save_to_disk(path));
        }
        _ => {}
    }
    look.demo = Some((dir, step + 1, now));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_far_model_changes_with_a_band_so_the_edge_does_not_flicker() {
        let f = FarModels { at: 10.0, band: 1.5 };
        // Undecided: the distance alone.
        assert!(!f.far(9.9, 1.75, None) && f.far(10.1, 1.75, None));
        // Near stays near up to the distance; far stays far down to the band.
        assert!(!f.far(10.0, 1.75, Some(false)));
        assert!(f.far(8.6, 1.75, Some(true)) && !f.far(8.4, 1.75, Some(true)));
        // Walking back and forth across 10 m by less than the band changes once.
        let (mut now, mut changes) = (None, 0);
        for i in 0..200 {
            let d = 10.0 + 0.7 * (i as f32 * 0.3).sin();
            let want = f.far(d, 1.75, now);
            if now.is_some() && now != Some(want) {
                changes += 1;
            }
            now = Some(want);
        }
        assert!(changes <= 1, "{changes} changes");
        // In proportion to height: a giant twice as tall changes at twice the distance.
        assert!(!f.far(19.0, 3.5, None) && f.far(21.0, 3.5, None));
        // 0 never changes.
        assert!(!FarModels { at: 0.0, band: 1.5 }.far(100.0, 1.75, None));
    }

    #[test]
    fn a_paged_face_names_its_map_in_its_extras() {
        assert_eq!(face_map_of(r#"{"face_map": "lookdev/pages/cullet-0.face.png"}"#).as_deref(), Some("lookdev/pages/cullet-0.face.png"));
        assert_eq!(face_map_of("{}"), None);
        assert_eq!(face_map_of("not json"), None);
    }
}
