//! Look-dev mode (`LIVING_GAME_LOOKDEV=1`): a small fixed scene for judging the look without
//! the server. Every glTF/GLB in `living/game/assets/lookdev/` is loaded and laid out in an arc
//! on a patch of ground, beside a 1.75 m reference figure; each model is converted to the shared
//! toon material and outlined. The game camera works as in play (`[` `]` rotate); the sun's
//! hour is a slider (F1 → Look dev). With `LIVING_GAME_DEMO=<dir>` it photographs the scene from
//! four sides, at sunset, and without the toon look, then quits.

use crate::camera::Cam;
use crate::style::{outline, Outlined, Style, Toon};
use crate::world::{rgb, MeshBuf, Palette};
use bevy::prelude::*;
use bevy::render::view::screenshot::{save_to_disk, Screenshot};
use bevy::world_serialization::WorldAssetRoot;
use bevy_mod_outline::{OutlineMeshExt, OutlineStencil};
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
    /// Height to scale the model to (m), and the ground level it stands on.
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
#[derive(Component)]
pub struct Fitted {
    pub y_off: f32,
}

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
    commands.insert_resource(Lookdev { hour: 15.0, act: Act::Idle, models, demo, focus: None });
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
    commands.spawn((crate::envs::EnvPart, Mesh3d(meshes.add(g.build())), MeshMaterial3d(palette.vertex.clone()), Transform::default(), OutlineStencil::default()));
    // The reference figure at the centre, facing the camera's side (+Z is south); it is the
    // character you walk around with here.
    let figure = crate::bodies::spawn(commands, meshes, palette, style, "person", 1, false, Transform::from_rotation(Quat::from_rotation_y(-std::f32::consts::FRAC_PI_2)), Vec2::ZERO);
    commands.entity(figure).insert((crate::envs::EnvPart, crate::envs::Player::Figure));
    let n = models.len().max(1) as f32;
    for (i, name) in models.iter().enumerate() {
        let a = std::f32::consts::PI * (1.1 + 0.8 * (i as f32 + 0.5) / n);
        let r = 5.0 + 1.5 * (i % 2) as f32;
        let at = Vec3::new(r * a.cos(), 0.0, r * a.sin());
        let handle = assets.load(GltfAssetLabel::Scene(0).from_asset(format!("{FOLDER}/{name}")));
        // glTF models face +Z, toward the camera's default side (south); VRM models face −Z.
        let vrm = name.starts_with("vroid-") || name.ends_with(".vrm");
        let turn = Quat::from_rotation_y(if vrm { std::f32::consts::PI } else { 0.0 });
        commands.spawn((crate::envs::EnvPart, Model::character(format!("{FOLDER}/{name}"), vrm), WorldAssetRoot(handle), Transform::from_translation(at).with_rotation(turn), Visibility::Hidden));
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
    q: Query<(Entity, &MeshMaterial3d<StandardMaterial>, &Mesh3d, Option<&bevy::gltf::GltfMaterialName>), Without<Converted>>,
    parents: Query<&ChildOf>,
    models: Query<&Model>,
    mut done: Local<(HashMap<(AssetId<StandardMaterial>, u32), Handle<Toon>>, HashSet<AssetId<Mesh>>)>,
) {
    for (e, mat, mesh, name) in &q {
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
        let Some(owner) = owner else { continue };
        let glow = owner.glow;
        let glow_key = glow.map_or(0, |g| (g[0] * 255.0) as u32 | ((g[1] * 255.0) as u32) << 8 | ((g[2] * 255.0) as u32) << 16 | 1 << 24);
        let Some(base) = standards.get(&mat.0) else { continue };
        // VRoid names materials …_SKIN, …_FACE, …_EYE, …_HAIR, …_CLOTH.
        let skin = name.is_some_and(|n| n.0.ends_with("_SKIN") || n.0.contains("Skin") || n.0.contains("skin"));
        let toon = done
            .0
            .entry((mat.0.id(), glow_key))
            .or_insert_with(|| {
                let mut b = base.clone();
                if let Some([r, g, bl]) = glow {
                    let c = b.base_color.to_linear();
                    b.emissive = LinearRgba::new(c.red * r, c.green * g, c.blue * bl, 1.0) * 8.0 + LinearRgba::new(r, g, bl, 1.0) * 2.0;
                }
                toons.add(if skin { style.skin(b) } else { style.toon(b) })
            })
            .clone();
        if done.1.insert(mesh.0.id()) {
            if let Some(mut m) = meshes.get_mut(&mesh.0) {
                let _ = m.generate_outline_normals(&Default::default());
            }
        }
        commands.entity(e).remove::<MeshMaterial3d<StandardMaterial>>().insert((MeshMaterial3d(toon), Converted, outline(Outlined::Thing, &style)));
    }
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
        let height = (hi.y - lo.y).max(0.01);
        let k = model.height / height;
        tf.scale = Vec3::splat(k);
        tf.translation.y = model.ground_y - lo.y * k;
        *vis = Visibility::Inherited;
        debug!("look-dev: fitted {} ({height:.2} units) to {:.2} m (×{k:.2})", model.file, model.height);
        commands.entity(e).insert(Fitted { y_off: -lo.y * k });
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
        commands.entity(e).insert(Rig { bones, arm_side, face, seed: (e.index_u32() % 97) as f32 * 0.37 });
    }
}

/// Morph target names of the mesh on node `node`, from a GLB file's JSON (mesh or primitive extras).
fn target_names(file: &str, node: &str) -> Option<Vec<String>> {
    let bytes = std::fs::read(std::path::Path::new(&asset_root()).join(file)).ok()?;
    if bytes.len() < 20 || &bytes[0..4] != b"glTF" {
        return None;
    }
    let len = u32::from_le_bytes(bytes[12..16].try_into().ok()?) as usize;
    let json: serde_json::Value = serde_json::from_slice(bytes.get(20..20 + len)?).ok()?;
    let mesh = json["nodes"].as_array()?.iter().find(|n| n["name"] == node)?["mesh"].as_u64()? as usize;
    let m = &json["meshes"][mesh];
    let names = if m["extras"]["targetNames"].is_array() { &m["extras"]["targetNames"] } else { &m["primitives"][0]["extras"]["targetNames"] };
    Some(names.as_array()?.iter().filter_map(|v| v.as_str().map(String::from)).collect())
}

/// Procedural motion for VRoid characters: arms down, breathing, a walk cycle in place,
/// blinking, and the mouth moving while talking.
pub fn animate(look: Res<Lookdev>, roam: Res<crate::envs::Roam>, rigs: Query<(&Rig, Has<crate::envs::Player>)>, mut transforms: Query<&mut Transform>, mut morphs: Query<&mut MorphWeights>, time: Res<Time>) {
    let t = time.elapsed_secs();
    for (rig, is_player) in &rigs {
        let t = t + rig.seed;
        let mut set = |bone: &str, q: Quat| {
            if let Some(mut tf) = rig.bones.get(bone).and_then(|b| transforms.get_mut(*b).ok()) {
                tf.rotation = q;
            }
        };
        let walk = look.act == Act::Walk || (is_player && roam.moving);
        let phase = t * 6.0;
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
        // Blink every few seconds; mouth moves while talking.
        if let Some((face, blink, mouth)) = rig.face {
            if let Ok(mut w) = morphs.get_mut(face) {
                let cycle = (t % 3.7) / 3.7;
                let close = if cycle > 0.96 { ((cycle - 0.96) / 0.04 * std::f32::consts::PI).sin() } else { 0.0 };
                let talk = if look.act == Act::Talk { ((t * 11.0).sin() * 0.5 + 0.5) * ((t * 2.3).sin() * 0.3 + 0.7) } else { 0.0 };
                let ws = w.weights_mut();
                if blink < ws.len() {
                    ws[blink] = close;
                }
                if mouth < ws.len() {
                    ws[mouth] = talk * 0.8;
                }
            }
        }
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
