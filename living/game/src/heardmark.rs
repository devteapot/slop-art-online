//! Heard, not seen (docs/PERCEPTION.md, "The field of view"): while the world's `fov_on` law is
//! on, the authority tells me of creatures I hear but don't see, in the `heard_sounds` view:
//! what they sound like (`kind`), one of eight compass ways (`bearing`, 0 north, clockwise) and a
//! rough distance (`band`: 0 near, 1 close, 2 far), under a key of its own per listener (salted;
//! never the character's id). Each becomes a soft, fading mark on the ground that way, about as
//! far as its band says, bigger and fainter the farther it is. Visual only: no sound, no name,
//! nothing to click. A row's mark fades in, stays while the row does (the authority keeps a row
//! about two seconds past the last hearing) and fades out after it goes.
//!
//! The mark is placed from where my character is drawn now, so it keeps its way as I walk; it
//! eases there rather than jumping when the bearing or band changes.

use crate::net::Net;
use bevy::asset::RenderAssetUsages;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
use living_bindings::*;
use spacetimedb_sdk::Table;
use std::collections::HashMap;

/// How long a mark takes to fade in, and out after its row goes (s).
const FADE_IN: f32 = 0.4;
const FADE_OUT: f32 = 1.5;
/// The strongest a mark gets (alpha).
const ALPHA: f32 = 0.42;
/// The mark eases toward its place at this rate (1/s).
const EASE: f32 = 4.0;

/// One heard sound's mark.
pub struct Mark {
    pub kind: String,
    pub bearing: u8,
    pub band: u8,
    /// Where it is drawn (sim metres) and its strength now (0..1 of [`ALPHA`]).
    pub at: Vec2,
    pub level: f32,
    /// Its row is still there.
    pub live: bool,
    entity: Entity,
    material: Handle<StandardMaterial>,
}

#[derive(Resource, Default)]
pub struct HeardMarks {
    pub marks: HashMap<u64, Mark>,
    mesh: Handle<Mesh>,
    texture: Handle<Image>,
}

pub struct HeardMarksPlugin;

impl Plugin for HeardMarksPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<HeardMarks>().add_systems(Startup, setup).add_systems(Update, update.in_set(crate::phase::Phase::Camera).after(crate::camera::follow));
    }
}

fn setup(mut marks: ResMut<HeardMarks>, mut meshes: ResMut<Assets<Mesh>>, mut images: ResMut<Assets<Image>>) {
    marks.mesh = meshes.add(Circle::new(1.0));
    // A soft disc: full in the middle, nothing at the rim.
    const N: u32 = 64;
    let mut px = Vec::with_capacity((N * N * 4) as usize);
    for j in 0..N {
        for i in 0..N {
            let d = Vec2::new(i as f32 + 0.5 - N as f32 / 2.0, j as f32 + 0.5 - N as f32 / 2.0).length() / (N as f32 / 2.0);
            let a = (1.0 - d).clamp(0.0, 1.0);
            let a = a * a * (3.0 - 2.0 * a);
            px.extend_from_slice(&[255, 255, 255, (a * 255.0) as u8]);
        }
    }
    marks.texture = images.add(Image::new(Extent3d { width: N, height: N, depth_or_array_layers: 1 }, TextureDimension::D2, px, TextureFormat::Rgba8UnormSrgb, RenderAssetUsages::default()));
}

/// Where a band's mark goes (m from me) and how wide it is (radius, m), by the world's
/// `heard_near_m`/`heard_close_m` laws and my hearing.
pub fn band_place(band: u8, near_m: f32, close_m: f32, hearing: f32) -> (f32, f32) {
    let far_end = hearing.max(close_m + 2.0);
    match band {
        0 => (near_m * 0.6, 0.9),
        1 => ((near_m + close_m) * 0.5, 1.6),
        _ => ((close_m + far_end) * 0.5, 2.4),
    }
}

/// The ground direction (sim: +x east, +y south) of a compass way (0 north, clockwise).
pub fn bearing_dir(bearing: u8) -> Vec2 {
    let a = (bearing % 8) as f32 * std::f32::consts::FRAC_PI_4;
    Vec2::new(a.sin(), -a.cos())
}

#[allow(clippy::too_many_arguments)]
fn update(
    mut commands: Commands,
    mut marks: ResMut<HeardMarks>,
    net: NonSend<Net>,
    rules: NonSend<crate::verbs::Rules>,
    edge: Res<crate::sightedge::SightEdge>,
    target: Res<crate::controls::Target>,
    island: Option<Res<crate::island::Island>>,
    mut mats: ResMut<Assets<StandardMaterial>>,
    mut tfs: Query<&mut Transform>,
    (time, mut laws): (Res<Time>, Local<Option<(u32, f32, f32)>>),
) {
    let dt = time.delta_secs();
    let rows: Vec<HeardSound> = net.conn.as_ref().map(|c| c.db.heard_sounds().iter().collect()).unwrap_or_default();
    if rows.is_empty() && marks.marks.is_empty() {
        return;
    }
    // The bands' distances are laws of the world, read once per script revision.
    if laws.is_none_or(|(rev, _, _)| rev != rules.revision) {
        if let Some(sc) = rules.scripts.as_ref() {
            let l = sc.laws();
            *laws = Some((rules.revision, l.heard_near_m, l.heard_close_m));
        }
    }
    let (near_m, close_m) = laws.map_or((5.0, 15.0), |(_, n, c)| (n, c));
    let hearing = edge.senses.map_or(9.0, |s| s.hearing);
    let Some(me) = target.0.map(|t| Vec2::new(t.x, t.z)) else { return };
    let (mesh, texture) = (marks.mesh.clone(), marks.texture.clone());
    for m in marks.marks.values_mut() {
        m.live = false;
    }
    for r in &rows {
        let (d, _) = band_place(r.band, near_m, close_m, hearing);
        let want = me + bearing_dir(r.bearing) * d;
        match marks.marks.get_mut(&r.key) {
            Some(m) => {
                if m.bearing != r.bearing || m.band != r.band {
                    info!("heard: mark {:016x} ({}) now {} band {}", r.key, r.kind, living_rules::sight::COMPASS8[(r.bearing % 8) as usize], r.band);
                }
                m.live = true;
                m.bearing = r.bearing;
                m.band = r.band;
            }
            None => {
                let material = mats.add(StandardMaterial { base_color: Color::srgba(1.0, 0.97, 0.9, 0.0), base_color_texture: Some(texture.clone()), unlit: true, alpha_mode: AlphaMode::Blend, depth_bias: 50.0, ..default() });
                let entity = commands.spawn((Mesh3d(mesh.clone()), MeshMaterial3d(material.clone()), Transform::from_xyz(want.x, 0.0, want.y), Visibility::Visible, bevy::light::NotShadowCaster)).id();
                info!("heard: mark {:016x} ({}) to the {}, band {} (~{d:.0} m)", r.key, r.kind, living_rules::sight::COMPASS8[(r.bearing % 8) as usize], r.band);
                marks.marks.insert(r.key, Mark { kind: r.kind.clone(), bearing: r.bearing, band: r.band, at: want, level: 0.0, live: true, entity, material });
            }
        }
    }
    let mut gone = Vec::new();
    for (key, m) in marks.marks.iter_mut() {
        let (d, size) = band_place(m.band, near_m, close_m, hearing);
        let want = me + bearing_dir(m.bearing) * d;
        if m.live {
            m.at += (want - m.at) * (1.0 - (-dt * EASE).exp());
            m.level = (m.level + dt / FADE_IN).min(1.0);
        } else {
            m.level -= dt / FADE_OUT;
        }
        if m.level <= 0.0 && !m.live {
            commands.entity(m.entity).despawn();
            info!("heard: mark {key:016x} ({}) faded", m.kind);
            gone.push(*key);
            continue;
        }
        let ground = island.as_deref().map_or(0.0, |i| i.height(m.at.x, m.at.y));
        if let Ok(mut tf) = tfs.get_mut(m.entity) {
            *tf = Transform::from_xyz(m.at.x, ground + 0.06, m.at.y).with_rotation(Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2)).with_scale(Vec3::splat(size));
        }
        if let Some(mut mat) = mats.get_mut(&m.material) {
            // Farther, fainter.
            let a = ALPHA * m.level * [1.0, 0.8, 0.6][m.band.min(2) as usize];
            mat.base_color = Color::srgba(1.0, 0.97, 0.9, a);
        }
    }
    for k in gone {
        if let Some(m) = marks.marks.remove(&k) {
            mats.remove(&m.material);
        }
    }
}

impl HeardMarks {
    /// The marks for a dump: key, kind, way, band, where (sim m) and strength.
    pub fn json(&self) -> serde_json::Value {
        serde_json::Value::from(
            self.marks
                .iter()
                .map(|(k, m)| serde_json::json!({"key": format!("{k:016x}"), "kind": m.kind, "bearing": m.bearing, "band": m.band, "at": [m.at.x, m.at.y], "level": m.level, "live": m.live}))
                .collect::<Vec<_>>(),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bearings_and_bands() {
        // North is -y on the map; east +x.
        assert!((bearing_dir(0) - Vec2::new(0.0, -1.0)).length() < 1e-5);
        assert!((bearing_dir(2) - Vec2::new(1.0, 0.0)).length() < 1e-5);
        assert!((bearing_dir(4) - Vec2::new(0.0, 1.0)).length() < 1e-5);
        // The rules' compass agrees: a mark placed that way is in that way.
        for b in 0..8u8 {
            let to = Vec2::new(10.0, 10.0) + bearing_dir(b) * 6.0;
            assert_eq!(living_rules::sight::compass8((10.0, 10.0), (to.x, to.y)), b);
        }
        let (n, c, f) = (band_place(0, 5.0, 15.0, 9.0).0, band_place(1, 5.0, 15.0, 9.0).0, band_place(2, 5.0, 15.0, 9.0).0);
        assert!(n <= 5.0 && (5.0..=15.0).contains(&c) && f > 15.0, "{n} {c} {f}");
    }
}
