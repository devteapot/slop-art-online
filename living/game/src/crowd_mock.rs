//! MOCK, dev only, never merged (branch `attention-e1`, from `battle-stills`'s mock): a picture
//! of the crowd rows of docs/ATTENTION_BUDGET.md §2.2 for the owner's attention-budget decision
//! (experiment E1, §5.1). Nothing here is the design of the real crowd renderer; it fakes what
//! per-cell crowd rows could look like, from developer truth.
//!
//! `LIVING_GAME_DEV_CROWD_MOCK=<file>` names a JSON file the harness writes (owner SQL of `body`
//! positions while the world is paused; `attention_stills.py`):
//!
//! ```json
//! {"seq": 3, "mode": "figures", "cell": 6.0,
//!  "bodies": [{"id": 12, "x": 401.2, "y": 255.0, "fighting": true}, …]}
//! ```
//!
//! (sim metres; `mode` is `figures`, `discs` or `off`). The bodies are the creatures within the
//! player's sight radius and field (cover ignored). Every one of them this client does not
//! perceive (`far_cap` left it out) is a crowd member. Crowd members are binned into
//! world-aligned square cells of `cell` metres, each with its count, centroid and spread, as a
//! `seen_crowd` row would carry them. Then:
//!
//! - `figures`: `count` generic figure cards per cell (flat, unlit, turned to the camera, no
//!   name, no pick), laid out round the cell's centroid in its spread ellipse on a sunflower
//!   spiral; a fighting pose when the member was fighting (the harness: within 2 m of a fighter
//!   of the other side), else standing;
//! - `discs`: one translucent disc per cell at its centroid, its area proportional to the count.
//!
//! After each change the mock writes `<file>.status.json` (the feed's `seq`, mode, cell, the
//! members and cells drawn, the perceived count), which the harness records per still. Off (no
//! systems at all) unless the variable is set.

use bevy::asset::RenderAssetUsages;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
use std::collections::{BTreeMap, HashSet};

/// How often the file is read again (s).
const POLL_S: f32 = 0.25;
/// The figure card's size (m).
const CARD: (f32, f32) = (0.9, 1.8);
/// The figures' and discs' tint (one generic colour: a crowd row carries no side).
const TINT: [f32; 3] = [0.42, 0.45, 0.58];
/// A disc's radius (m) for one member; the area grows with the count.
const DISC_R1: f32 = 0.55;

#[derive(Clone)]
struct Member {
    id: u32,
    at: Vec2,
    fighting: bool,
}

#[derive(Default, Clone, PartialEq)]
struct Feed {
    seq: u64,
    mode: String,
    cell: f32,
    /// A ground point (sim xy) the camera is moved over, keeping its height, pitch and field of
    /// view (the band's): the battle framed from a player standing beyond the picture's edge.
    focus: Option<Vec2>,
    /// The game UI hidden (every `HudRoot` tree), nameplates kept: the stills' "UI hidden but the
    /// nameplates".
    hide_ui: bool,
    /// With a focus: the screen fraction from the top (0..1) where the focus's ground point is
    /// put, on the picture's vertical centre line (0.5: the middle).
    focus_at: f32,
    bodies: Vec<(u32, Vec2, bool)>,
}

#[derive(Resource)]
struct Mock {
    file: String,
    since: f32,
    stamp: Option<std::time::SystemTime>,
    feed: Feed,
    /// What was last built: the feed's seq and the crowd's ids, to rebuild only on a change.
    built: Option<(u64, Vec<u32>)>,
    drawn: Vec<Entity>,
    /// Anchors (sim xy) of the figures drawn, to turn them to the camera each frame.
    cards: Vec<(Entity, Vec3)>,
    card: Handle<Mesh>,
    disc: Handle<Mesh>,
    stand_mat: Handle<StandardMaterial>,
    fight_mat: Handle<StandardMaterial>,
    disc_mat: Handle<StandardMaterial>,
    blob: Handle<Mesh>,
    blob_mat: Handle<StandardMaterial>,
}

pub struct CrowdMockPlugin;

impl Plugin for CrowdMockPlugin {
    fn build(&self, app: &mut App) {
        let Some(file) = std::env::var("LIVING_GAME_DEV_CROWD_MOCK").ok().filter(|f| !f.trim().is_empty()) else { return };
        info!("crowd mock: ON, feed {file} (dev only; per-cell crowd rows mocked for bodies I do not perceive)");
        app.insert_resource(MockFile(file)).add_systems(Startup, setup).add_systems(Update, update.in_set(crate::phase::Phase::Camera).after(crate::camera::follow))
            .add_systems(PostUpdate, hide_ui.after(crate::ui::UiWork).before(bevy::camera::visibility::VisibilitySystems::VisibilityPropagate));
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

fn edge(d: f32) -> f32 {
    (0.5 - d / 0.03).clamp(0.0, 1.0)
}

/// Distance from a point to a segment (m).
fn seg(p: Vec2, a: Vec2, b: Vec2, r: f32) -> f32 {
    let ab = b - a;
    let t = ((p - a).dot(ab) / ab.length_squared()).clamp(0.0, 1.0);
    (p - (a + ab * t)).length() - r
}

/// A standing person on a card (u 0..1 across, v 0..1 up): head, torso, arms down, two legs.
fn standing(u: f32, v: f32) -> f32 {
    let p = Vec2::new((u - 0.5) * CARD.0, v * CARD.1);
    let head = (p - Vec2::new(0.0, 1.58)).length() - 0.12;
    let torso = seg(p, Vec2::new(0.0, 0.92), Vec2::new(0.0, 1.36), 0.17);
    let arms = seg(p, Vec2::new(-0.2, 1.36), Vec2::new(-0.24, 0.9), 0.05).min(seg(p, Vec2::new(0.2, 1.36), Vec2::new(0.24, 0.9), 0.05));
    let legs = seg(p, Vec2::new(-0.08, 0.9), Vec2::new(-0.1, 0.04), 0.065).min(seg(p, Vec2::new(0.08, 0.9), Vec2::new(0.1, 0.04), 0.065));
    edge(head.min(torso).min(arms).min(legs))
}

/// A fighting person: wide stance, leaning, a spear held forward and up.
fn fighting(u: f32, v: f32) -> f32 {
    let p = Vec2::new((u - 0.5) * CARD.0, v * CARD.1);
    let head = (p - Vec2::new(0.06, 1.5)).length() - 0.12;
    let torso = seg(p, Vec2::new(-0.02, 0.88), Vec2::new(0.04, 1.3), 0.17);
    let arms = seg(p, Vec2::new(0.16, 1.28), Vec2::new(0.34, 1.12), 0.05).min(seg(p, Vec2::new(-0.16, 1.28), Vec2::new(-0.3, 1.02), 0.05));
    let legs = seg(p, Vec2::new(-0.08, 0.88), Vec2::new(-0.3, 0.04), 0.065).min(seg(p, Vec2::new(0.08, 0.88), Vec2::new(0.28, 0.04), 0.065));
    let spear = seg(p, Vec2::new(-0.4, 0.75), Vec2::new(0.44, 1.72), 0.022);
    edge(head.min(torso).min(arms).min(legs).min(spear))
}

fn setup(mut commands: Commands, file: Res<MockFile>, mut meshes: ResMut<Assets<Mesh>>, mut images: ResMut<Assets<Image>>, mut mats: ResMut<Assets<StandardMaterial>>) {
    let stand_tex = images.add(soft_image(54, 108, standing));
    let fight_tex = images.add(soft_image(54, 108, fighting));
    let blob_tex = images.add(soft_image(48, 48, |u, v| {
        let d = Vec2::new(u - 0.5, v - 0.5).length() * 2.0;
        let a = (1.0 - d).clamp(0.0, 1.0);
        a * a * (3.0 - 2.0 * a)
    }));
    // A disc: an even fill with a brighter rim, so overlapping cells still read as separate.
    let disc_tex = images.add(soft_image(96, 96, |u, v| {
        let d = Vec2::new(u - 0.5, v - 0.5).length() * 2.0;
        if d > 1.0 {
            0.0
        } else if d > 0.9 {
            1.0
        } else {
            0.55
        }
    }));
    let card_mat = |tex: Handle<Image>, mats: &mut Assets<StandardMaterial>| {
        mats.add(StandardMaterial { base_color: Color::srgba(TINT[0], TINT[1], TINT[2], 0.95), base_color_texture: Some(tex), unlit: true, alpha_mode: AlphaMode::Blend, cull_mode: None, ..default() })
    };
    let stand_mat = card_mat(stand_tex, &mut mats);
    let fight_mat = card_mat(fight_tex, &mut mats);
    let disc_mat = mats.add(StandardMaterial { base_color: Color::srgba(0.78, 0.30, 0.22, 0.6), base_color_texture: Some(disc_tex), unlit: true, alpha_mode: AlphaMode::Blend, depth_bias: 40.0, ..default() });
    let blob_mat = mats.add(StandardMaterial { base_color: Color::srgba(0.08, 0.08, 0.12, 0.35), base_color_texture: Some(blob_tex), unlit: true, alpha_mode: AlphaMode::Blend, depth_bias: 40.0, ..default() });
    commands.insert_resource(Mock {
        file: file.0.clone(),
        since: POLL_S,
        stamp: None,
        feed: Feed::default(),
        built: None,
        drawn: Vec::new(),
        cards: Vec::new(),
        card: meshes.add(Rectangle::new(CARD.0, CARD.1)),
        disc: meshes.add(Circle::new(1.0)),
        stand_mat,
        fight_mat,
        disc_mat,
        blob: meshes.add(Circle::new(0.5)),
        blob_mat,
    });
}

fn read_feed(file: &str) -> Option<Feed> {
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(file).ok()?).ok()?;
    Some(Feed {
        seq: v.get("seq").and_then(|s| s.as_u64()).unwrap_or(0),
        mode: v.get("mode").and_then(|s| s.as_str()).unwrap_or("figures").to_string(),
        cell: v.get("cell").and_then(|s| s.as_f64()).unwrap_or(6.0).max(0.5) as f32,
        focus_at: v.get("focus_at").and_then(|f| f.as_f64()).unwrap_or(0.5) as f32,
        hide_ui: v.get("hide_ui").and_then(|h| h.as_bool()).unwrap_or(false),
        focus: v.get("focus").and_then(|f| Some(Vec2::new(f.get(0)?.as_f64()? as f32, f.get(1)?.as_f64()? as f32))),
        bodies: v
            .get("bodies")?
            .as_array()?
            .iter()
            .filter_map(|b| Some((b.get("id")?.as_u64()? as u32, Vec2::new(b.get("x")?.as_f64()? as f32, b.get("y")?.as_f64()? as f32), b.get("fighting").and_then(|f| f.as_bool()).unwrap_or(false))))
            .collect(),
    })
}

/// One cell's crowd row: its members, centroid and spread (standard deviation per axis, m).
struct Row {
    cell: (i32, i32),
    members: Vec<Member>,
    centroid: Vec2,
    spread: Vec2,
}

fn rows(members: &[Member], cell: f32) -> Vec<Row> {
    let mut by: BTreeMap<(i32, i32), Vec<Member>> = BTreeMap::new();
    for m in members {
        by.entry(((m.at.x / cell).floor() as i32, (m.at.y / cell).floor() as i32)).or_default().push(m.clone());
    }
    by.into_iter()
        .map(|(cell, members)| {
            let n = members.len() as f32;
            let centroid = members.iter().map(|m| m.at).sum::<Vec2>() / n;
            let var = members.iter().map(|m| (m.at - centroid) * (m.at - centroid)).sum::<Vec2>() / n;
            Row { cell, members, centroid, spread: Vec2::new(var.x.sqrt(), var.y.sqrt()) }
        })
        .collect()
}

#[allow(clippy::too_many_arguments)]
fn update(
    mut commands: Commands,
    mock: Option<ResMut<Mock>>,
    mut cam: ResMut<crate::camera::Cam>,
    mut eyes: Query<(&mut Transform, &Projection), With<Camera3d>>,
    net: NonSend<crate::net::Net>,
    island: Option<Res<crate::island::Island>>,
    cams: Query<&GlobalTransform, With<Camera3d>>,
    mut tfs: Query<&mut Transform, Without<Camera3d>>,
    time: Res<Time>,
) {
    let Some(mut mock) = mock else { return };
    mock.since += time.delta_secs();
    if mock.since >= POLL_S {
        mock.since = 0.0;
        let stamp = std::fs::metadata(&mock.file).and_then(|m| m.modified()).ok();
        if stamp.is_none() {
            mock.feed = Feed::default();
        } else if stamp != mock.stamp {
            if let Some(feed) = read_feed(&mock.file) {
                mock.feed = feed;
            }
        }
        mock.stamp = stamp;
    }
    let perceived: HashSet<u32> = crate::looks::perceived_ids(&net).into_iter().collect();
    let mut crowd: Vec<Member> = mock.feed.bodies.iter().filter(|(id, _, _)| !perceived.contains(id)).map(|&(id, at, fighting)| Member { id, at, fighting }).collect();
    crowd.sort_by_key(|m| m.id);
    let ids: Vec<u32> = crowd.iter().map(|m| m.id).collect();
    let height = |p: Vec2| island.as_deref().map_or(0.0, |s| s.height(p.x, p.y));
    if mock.built.as_ref() != Some(&(mock.feed.seq, ids.clone())) {
        for e in std::mem::take(&mut mock.drawn) {
            commands.entity(e).despawn();
        }
        mock.cards.clear();
        let mode = mock.feed.mode.clone();
        let cell = mock.feed.cell;
        let crowd_rows = if mode == "off" { Vec::new() } else { rows(&crowd, cell) };
        let mut drawn = Vec::new();
        let mut cards = Vec::new();
        for r in &crowd_rows {
            let n = r.members.len();
            if mode == "discs" {
                let rad = DISC_R1 * (n as f32).sqrt();
                let at = Vec3::new(r.centroid.x, height(r.centroid) + 0.06, r.centroid.y);
                let mat = mock.disc_mat.clone();
                drawn.push(
                    commands
                        .spawn((Mesh3d(mock.disc.clone()), MeshMaterial3d(mat), Transform::from_translation(at).with_rotation(Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2)).with_scale(Vec3::splat(rad)), Visibility::Visible, bevy::light::NotShadowCaster))
                        .id(),
                );
                continue;
            }
            // Figures: the row's count, round its centroid in its spread ellipse (2σ, at least
            // 0.7 m and at most half a cell), on a sunflower spiral; fighting first, so the
            // share fighting reads as the cell's share.
            let ell = (r.spread * 2.0).clamp(Vec2::splat(0.7), Vec2::splat(cell * 0.5));
            let fighting = r.members.iter().filter(|m| m.fighting).count();
            for k in 0..n {
                let t = ((k as f32 + 0.5) / n as f32).sqrt();
                let a = k as f32 * 2.399_963 + (r.cell.0 * 7 + r.cell.1 * 13) as f32;
                let p = r.centroid + Vec2::new(a.cos() * ell.x, a.sin() * ell.y) * t;
                let base = Vec3::new(p.x, height(p), p.y);
                let mat = if k < fighting { mock.fight_mat.clone() } else { mock.stand_mat.clone() };
                let card = commands.spawn((Mesh3d(mock.card.clone()), MeshMaterial3d(mat), Transform::from_translation(base + Vec3::Y * (CARD.1 * 0.5)), Visibility::Visible, bevy::light::NotShadowCaster)).id();
                let blob = commands
                    .spawn((Mesh3d(mock.blob.clone()), MeshMaterial3d(mock.blob_mat.clone()), Transform::from_translation(base + Vec3::Y * 0.05).with_rotation(Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2)), Visibility::Visible, bevy::light::NotShadowCaster))
                    .id();
                cards.push((card, base));
                drawn.push(card);
                drawn.push(blob);
            }
        }
        mock.drawn = drawn;
        mock.cards = cards;
        mock.built = Some((mock.feed.seq, ids));
        let status = serde_json::json!({
            "seq": mock.feed.seq, "mode": mode, "cell": cell,
            "feed": mock.feed.bodies.len(), "perceived": perceived.len(),
            "members": crowd.len(), "cells": crowd_rows.len(),
            "rows": crowd_rows.iter().map(|r| serde_json::json!({"cell": [r.cell.0, r.cell.1], "count": r.members.len(), "x": r.centroid.x, "y": r.centroid.y, "spread": [r.spread.x, r.spread.y], "fighting": r.members.iter().filter(|m| m.fighting).count()})).collect::<Vec<_>>(),
        });
        let _ = std::fs::write(format!("{}.status.json", mock.file), serde_json::to_string_pretty(&status).unwrap_or_default());
        info!("crowd mock: seq {} {mode} cell {cell} m: {} members in {} cells (feed {}, perceived {})", mock.feed.seq, crowd.len(), crowd_rows.len(), mock.feed.bodies.len(), perceived.len());
    }
    // The battle framed: the eye moved sideways by the focus's offset from where `camera::follow`
    // aimed it (the ground point straight ahead of the eye at its pitch), height, pitch and field
    // kept; `cam.pose` with it, so names on screen and picks stay in step this frame.
    let mut eye_at = cams.iter().next().map(|g| g.translation());
    if let (Some(focus), Ok((mut tf, proj))) = (mock.feed.focus, eyes.single_mut()) {
        // The ray through the picture's centre line at `focus_at` from the top.
        let half = match proj {
            Projection::Perspective(p) => (p.fov * 0.5).tan(),
            _ => 0.0,
        };
        let ndc_y = 1.0 - 2.0 * mock.feed.focus_at.clamp(0.0, 1.0);
        let fwd = (tf.rotation * Vec3::new(0.0, ndc_y * half, -1.0)).normalize();
        if fwd.y < -0.05 {
            let ground = height(focus);
            let t = (tf.translation.y - ground) / -fwd.y;
            let aimed = tf.translation + fwd * t;
            let shift = Vec3::new(focus.x - aimed.x, 0.0, focus.y - aimed.z);
            tf.translation += shift;
            cam.pose = GlobalTransform::from(*tf);
            eye_at = Some(tf.translation);
        }
    }
    // A cylindrical billboard: upright, turned about the vertical to face the camera.
    let cam = eye_at;
    for (card, base) in &mock.cards {
        let yaw = cam.map_or(0.0, |c| (c.x - base.x).atan2(c.z - base.z));
        if let Ok(mut tf) = tfs.get_mut(*card) {
            *tf = Transform::from_translation(*base + Vec3::Y * (CARD.1 * 0.5)).with_rotation(Quat::from_rotation_y(yaw));
        }
    }
}

/// The game UI's trees hidden while the feed asks (after the UI's own visibility, in `Update`).
/// The nameplates' layer (`ui/overhead.rs`, private) is the one `HudRoot` at `GlobalZIndex(-5)`
/// and is kept.
fn hide_ui(mock: Option<Res<Mock>>, mut q: Query<(&mut Visibility, Option<&GlobalZIndex>), With<crate::ui::HudRoot>>) {
    if mock.is_some_and(|m| m.feed.hide_ui) {
        for (mut v, z) in &mut q {
            if z.is_some_and(|z| z.0 == -5) {
                continue;
            }
            *v = Visibility::Hidden;
        }
    }
}
