//! MOCK, dev only, never merged (branch `battle-stills`): a picture of "aggregated far crowds"
//! (docs/BATTLE_LAWS.md, option (a)'s better form) for the owner's battle-scale decision. Nothing
//! here is a design for the real thing; it fakes what crowd rows could look like.
//!
//! `LIVING_GAME_DEV_CROWD_MOCK=<file>` names a JSON file a harness rewrites about twice a second
//! from the authority's developer truth (owner SQL of every body in the battle):
//! `{"wall_ms": …, "bodies": [{"id": 12, "x": 401.2, "y": 255.0, "side": 0}, …]}` (sim metres).
//! Every body in the file that this client does not perceive (the creatures `far_cap` left out of
//! my set) is drawn as a cheap impostor at its position: a flat, unlit silhouette card turned to
//! the camera, over a soft ground blob, tinted by side. Positions only: no name, no pick, no
//! animation. Off (no systems at all) unless the variable is set.

use bevy::asset::RenderAssetUsages;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
use std::collections::HashMap;

/// How often the file is read again (s).
const POLL_S: f32 = 0.5;
/// An impostor eases toward its newest position at this rate (1/s): the feed is 1–2 Hz.
const EASE: f32 = 3.0;
/// The card's size (m) and its tints by side.
const CARD: (f32, f32) = (0.75, 1.75);
const TINTS: [[f32; 3]; 2] = [[0.42, 0.48, 0.60], [0.66, 0.40, 0.34]];

struct Imp {
    at: Vec2,
    want: Vec2,
    card: Entity,
    blob: Entity,
}

#[derive(Resource)]
struct Mock {
    file: String,
    since: f32,
    stamp: Option<std::time::SystemTime>,
    feed: Vec<(u32, Vec2, usize)>,
    imps: HashMap<u32, Imp>,
    card: Handle<Mesh>,
    blob: Handle<Mesh>,
    card_mats: Vec<Handle<StandardMaterial>>,
    blob_mat: Handle<StandardMaterial>,
    said: f32,
}

pub struct CrowdMockPlugin;

impl Plugin for CrowdMockPlugin {
    fn build(&self, app: &mut App) {
        let Some(file) = std::env::var("LIVING_GAME_DEV_CROWD_MOCK").ok().filter(|f| !f.trim().is_empty()) else { return };
        info!("crowd mock: ON, feed {file} (dev only; impostors for bodies I do not perceive)");
        app.insert_resource(MockFile(file)).add_systems(Startup, setup).add_systems(Update, update.in_set(crate::phase::Phase::Camera).after(crate::camera::follow));
    }
}

#[derive(Resource)]
struct MockFile(String);

fn soft_image(w: u32, h: u32, alpha: impl Fn(f32, f32) -> f32) -> Image {
    let mut px = Vec::with_capacity((w * h * 4) as usize);
    for j in 0..h {
        for i in 0..w {
            // u across 0..1, v up 0..1.
            let a = alpha((i as f32 + 0.5) / w as f32, 1.0 - (j as f32 + 0.5) / h as f32).clamp(0.0, 1.0);
            px.extend_from_slice(&[255, 255, 255, (a * 255.0) as u8]);
        }
    }
    Image::new(Extent3d { width: w, height: h, depth_or_array_layers: 1 }, TextureDimension::D2, px, TextureFormat::Rgba8UnormSrgb, RenderAssetUsages::default())
}

/// A person's silhouette on a card (u 0..1 across, v 0..1 up): a head, shoulders and a body
/// narrowing to two legs, with soft edges.
fn silhouette(u: f32, v: f32) -> f32 {
    let x = (u - 0.5) * CARD.0;
    let y = v * CARD.1;
    let edge = |d: f32| (0.5 - d / 0.035).clamp(0.0, 1.0);
    // Head.
    let head = Vec2::new(x, y - 1.58).length() - 0.12;
    // Torso: a rounded box from the hips (0.85) to the shoulders (1.42), 0.21 m half-width at the
    // shoulders and 0.16 at the hips.
    let t = ((y - 0.85) / 0.57).clamp(0.0, 1.0);
    let half = 0.16 + 0.05 * t;
    let torso = if (0.85..=1.42).contains(&y) { x.abs() - half } else { (y - 1.42).max(0.85 - y).max(x.abs() - half) + 0.02 };
    // Legs: two strips from the feet to the hips.
    let leg = if y <= 0.9 { (x.abs() - 0.08).abs() - 0.065 } else { 1.0 };
    edge(head.min(torso).min(leg))
}

fn setup(mut commands: Commands, file: Res<MockFile>, mut meshes: ResMut<Assets<Mesh>>, mut images: ResMut<Assets<Image>>, mut mats: ResMut<Assets<StandardMaterial>>) {
    let card_tex = images.add(soft_image(48, 112, silhouette));
    let blob_tex = images.add(soft_image(48, 48, |u, v| {
        let d = Vec2::new(u - 0.5, v - 0.5).length() * 2.0;
        let a = (1.0 - d).clamp(0.0, 1.0);
        a * a * (3.0 - 2.0 * a)
    }));
    let card_mats = TINTS
        .iter()
        .map(|t| mats.add(StandardMaterial { base_color: Color::srgba(t[0], t[1], t[2], 0.92), base_color_texture: Some(card_tex.clone()), unlit: true, alpha_mode: AlphaMode::Blend, cull_mode: None, ..default() }))
        .collect();
    let blob_mat = mats.add(StandardMaterial { base_color: Color::srgba(0.08, 0.08, 0.12, 0.35), base_color_texture: Some(blob_tex), unlit: true, alpha_mode: AlphaMode::Blend, depth_bias: 40.0, ..default() });
    commands.insert_resource(Mock {
        file: file.0.clone(),
        since: POLL_S,
        stamp: None,
        feed: Vec::new(),
        imps: HashMap::new(),
        card: meshes.add(Rectangle::new(CARD.0, CARD.1)),
        blob: meshes.add(Circle::new(0.55)),
        card_mats,
        blob_mat,
        said: 0.0,
    });
}

fn read_feed(file: &str) -> Option<Vec<(u32, Vec2, usize)>> {
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(file).ok()?).ok()?;
    Some(
        v.get("bodies")?
            .as_array()?
            .iter()
            .filter_map(|b| Some((b.get("id")?.as_u64()? as u32, Vec2::new(b.get("x")?.as_f64()? as f32, b.get("y")?.as_f64()? as f32), b.get("side").and_then(|s| s.as_u64()).unwrap_or(0) as usize % TINTS.len())))
            .collect(),
    )
}

#[allow(clippy::too_many_arguments)]
fn update(
    mut commands: Commands,
    mock: Option<ResMut<Mock>>,
    net: NonSend<crate::net::Net>,
    island: Option<Res<crate::island::Island>>,
    cams: Query<&GlobalTransform, With<Camera3d>>,
    mut tfs: Query<&mut Transform>,
    time: Res<Time>,
) {
    let Some(mut mock) = mock else { return };
    let dt = time.delta_secs();
    mock.since += dt;
    if mock.since >= POLL_S {
        mock.since = 0.0;
        let stamp = std::fs::metadata(&mock.file).and_then(|m| m.modified()).ok();
        if stamp.is_none() {
            // No file: nothing to fake.
            mock.feed.clear();
        } else if stamp != mock.stamp {
            if let Some(feed) = read_feed(&mock.file) {
                mock.feed = feed;
            }
        }
        mock.stamp = stamp;
    }
    let perceived: std::collections::HashSet<u32> = crate::looks::perceived_ids(&net).into_iter().collect();
    let mut keep: std::collections::HashSet<u32> = std::collections::HashSet::new();
    let (card, blob, blob_mat) = (mock.card.clone(), mock.blob.clone(), mock.blob_mat.clone());
    let feed = mock.feed.clone();
    for (id, at, side) in feed {
        if perceived.contains(&id) {
            continue;
        }
        keep.insert(id);
        let mat = mock.card_mats[side].clone();
        mock.imps
            .entry(id)
            .and_modify(|i| i.want = at)
            .or_insert_with(|| {
                let card = commands.spawn((Mesh3d(card.clone()), MeshMaterial3d(mat), Transform::default(), Visibility::Visible, bevy::light::NotShadowCaster)).id();
                let blob = commands.spawn((Mesh3d(blob.clone()), MeshMaterial3d(blob_mat.clone()), Transform::default(), Visibility::Visible, bevy::light::NotShadowCaster)).id();
                Imp { at, want: at, card, blob }
            });
    }
    let gone: Vec<u32> = mock.imps.keys().filter(|id| !keep.contains(id)).copied().collect();
    for id in &gone {
        if let Some(i) = mock.imps.remove(id) {
            commands.entity(i.card).despawn();
            commands.entity(i.blob).despawn();
        }
    }
    let cam = cams.iter().next().map(|g| g.translation());
    for i in mock.imps.values_mut() {
        i.at += (i.want - i.at) * (1.0 - (-dt * EASE).exp());
        let ground = island.as_deref().map_or(0.0, |s| s.height(i.at.x, i.at.y));
        let base = Vec3::new(i.at.x, ground, i.at.y);
        // A cylindrical billboard: upright, turned about the vertical to face the camera.
        let yaw = cam.map_or(0.0, |c| (c.x - base.x).atan2(c.z - base.z));
        if let Ok(mut tf) = tfs.get_mut(i.card) {
            *tf = Transform::from_translation(base + Vec3::Y * (CARD.1 * 0.5)).with_rotation(Quat::from_rotation_y(yaw));
        }
        if let Ok(mut tf) = tfs.get_mut(i.blob) {
            *tf = Transform::from_translation(base + Vec3::Y * 0.05).with_rotation(Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2));
        }
    }
    mock.said += dt;
    if mock.said >= 1.0 {
        mock.said = 0.0;
        info!("crowd mock: {} impostors (feed {}, perceived {})", mock.imps.len(), mock.feed.len(), perceived.len());
    }
}
