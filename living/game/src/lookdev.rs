//! Look-dev mode (`LIVING_GAME_LOOKDEV=1`): a small fixed scene for judging the look without
//! the server. Every glTF/GLB in `living/game/assets/lookdev/` is loaded and laid out in an arc
//! on a patch of ground, beside a 1.75 m reference figure; each model is converted to the shared
//! toon material and outlined. The game camera works as in play (`[` `]` rotate); the sun's
//! hour is a slider (F1 → Look dev). With `LIVING_GAME_DEMO=<dir>` it photographs the scene from
//! four sides, at sunset, and without the toon look, then quits.

use crate::camera::Cam;
use crate::controls::Target;
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

#[derive(Resource)]
pub struct Lookdev {
    /// Sun hour (6 = sunrise, 12 = noon, 18 = sunset).
    pub hour: f32,
    pub models: Vec<String>,
    demo: Option<(std::path::PathBuf, usize, f32)>,
}

/// A loaded look-dev model's root.
#[derive(Component)]
pub struct Model;

/// A mesh entity already given the toon material and outline.
#[derive(Component)]
pub struct Converted;

pub fn asset_root() -> String {
    format!("{}/assets", env!("CARGO_MANIFEST_DIR"))
}

pub fn setup(mut commands: Commands, mut meshes: ResMut<Assets<Mesh>>, palette: Res<Palette>, style: Res<Style>, assets: Res<AssetServer>, mut target: ResMut<Target>) {
    // Ground: a disc of grass with a few low mounds, as a stencil for outlines.
    let mut g = MeshBuf::default();
    let ring = |r: f32, a: f32| Vec3::new(r * a.cos(), 0.0, r * a.sin());
    for i in 0..64 {
        let (a0, a1) = (i as f32 / 64.0 * std::f32::consts::TAU, (i + 1) as f32 / 64.0 * std::f32::consts::TAU);
        g.tri([Vec3::ZERO, ring(30.0, a1), ring(30.0, a0)], rgb(112, 160, 74));
    }
    commands.spawn((Mesh3d(meshes.add(g.build())), MeshMaterial3d(palette.vertex.clone()), Transform::default(), OutlineStencil::default()));
    // The reference figure at the centre, facing the camera's side (+Z is south).
    crate::bodies::spawn(&mut commands, &mut meshes, &palette, &style, "person", 1, false, Transform::from_rotation(Quat::from_rotation_y(-std::f32::consts::FRAC_PI_2)), Vec2::ZERO);
    target.0 = Some(Vec3::ZERO);

    // Every model in the folder, in an arc behind and beside the figure.
    let dir = std::path::Path::new(&asset_root()).join(FOLDER);
    let mut models: Vec<String> = std::fs::read_dir(&dir)
        .map(|r| r.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().to_string()).filter(|n| n.ends_with(".glb") || n.ends_with(".gltf")).collect())
        .unwrap_or_default();
    models.sort();
    info!("look-dev: {} model(s) in {}", models.len(), dir.display());
    let n = models.len().max(1) as f32;
    for (i, name) in models.iter().enumerate() {
        let a = std::f32::consts::PI * (1.1 + 0.8 * (i as f32 + 0.5) / n);
        let r = 5.0 + 1.5 * (i % 2) as f32;
        let at = Vec3::new(r * a.cos(), 0.0, r * a.sin());
        let handle = assets.load(GltfAssetLabel::Scene(0).from_asset(format!("{FOLDER}/{name}")));
        commands.spawn((Model, WorldAssetRoot(handle), Transform::from_translation(at).looking_at(Vec3::new(0.0, 0.0, 6.0), Vec3::Y)));
    }
    let demo = std::env::var("LIVING_GAME_DEMO").ok().filter(|d| !d.is_empty()).map(|d| {
        let _ = std::fs::create_dir_all(&d);
        (std::path::PathBuf::from(d), 0usize, 0.0)
    });
    commands.insert_resource(Lookdev { hour: 15.0, models, demo });
}

/// Give every mesh of a loaded model the shared toon material and an outline.
#[allow(clippy::type_complexity)]
pub fn convert(
    mut commands: Commands,
    style: Res<Style>,
    mut toons: ResMut<Assets<Toon>>,
    standards: Res<Assets<StandardMaterial>>,
    mut meshes: ResMut<Assets<Mesh>>,
    q: Query<(Entity, &MeshMaterial3d<StandardMaterial>, &Mesh3d), Without<Converted>>,
    parents: Query<&ChildOf>,
    models: Query<(), With<Model>>,
    mut done: Local<(HashMap<AssetId<StandardMaterial>, Handle<Toon>>, HashSet<AssetId<Mesh>>)>,
) {
    for (e, mat, mesh) in &q {
        // Only meshes under a look-dev model.
        let mut cur = e;
        let mut under = false;
        while let Ok(p) = parents.get(cur) {
            cur = p.parent();
            if models.contains(cur) {
                under = true;
                break;
            }
        }
        if !under {
            continue;
        }
        let Some(base) = standards.get(&mat.0) else { continue };
        let toon = done.0.entry(mat.0.id()).or_insert_with(|| toons.add(style.toon(base.clone()))).clone();
        if done.1.insert(mesh.0.id()) {
            if let Some(mut m) = meshes.get_mut(&mesh.0) {
                let _ = m.generate_outline_normals(&Default::default());
            }
        }
        commands.entity(e).remove::<MeshMaterial3d<StandardMaterial>>().insert((MeshMaterial3d(toon), Converted, outline(Outlined::Thing, &style)));
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
pub fn demo(mut commands: Commands, mut look: ResMut<Lookdev>, mut cam: ResMut<Cam>, mut style: ResMut<Style>, time: Res<Time>, mut exit: MessageWriter<AppExit>) {
    let Some((dir, step, at)) = look.demo.clone() else { return };
    let now = time.elapsed_secs();
    // (wait before, action)
    let steps: [(f32, &str); 10] = [(5.0, "yaw0"), (2.0, "shot:lookdev-north"), (0.2, "yaw90"), (2.0, "shot:lookdev-east"), (0.2, "yaw180"), (2.0, "shot:lookdev-south"), (0.2, "sunset"), (2.0, "shot:lookdev-sunset"), (0.2, "plain"), (1.5, "shot:lookdev-plain")];
    let Some((wait, act)) = steps.get(step).copied() else {
        exit.write(AppExit::Success);
        return;
    };
    if now - at < wait {
        return;
    }
    match act {
        "yaw0" => cam.set_yaw(0.0),
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
