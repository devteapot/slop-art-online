//! Grounded contact shadows under 3D characters (look-dev step 2.1).
//!
//! Only active with [`crate::style::Look::Lookdev`]. In Classic, no shadow entities exist and
//! nothing is allocated, so Classic stays identical to main.
//!
//! Each fitted 3D character gets a standalone sibling decal quad (not a child of the model, so
//! `lookdev::fit`, `lookdev::convert`, `lookdev::far_models`, `lookdev::character_shadows`, and
//! `fade::adopt` never see it). The quad uses `StandardMaterial` with `AlphaMode::Multiply`,
//! `NotShadowCaster`, and `StopPropagateOutline`: Bevy's `BLEND_MULTIPLY` computes
//! `dst * mix(1, tint, alpha)` with no depth write and no prepass, so edges never outline it and
//! shaded ground is darkened gently without turning into a harsh black disc. All grounded
//! characters share one material handle (one draw batch); airborne and fading characters step
//! across 8 shared opacity buckets.

use crate::anim::{Anim, Motion};
use crate::characters::Character;
use crate::daylight::Atmo;
use crate::fade::Fade;
use crate::island::Island;
use crate::lookdev::{Fitted, Model};
use crate::style::{Look, Style};
use bevy::asset::RenderAssetUsages;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
use std::collections::HashMap;

/// Opacity buckets for shared multiply materials (index 7 = full grounded strength).
const LEVELS: usize = 8;
/// Lift above the ground (m) to clear sloped cobbles and flagstones without clipping toes.
const LIFT_Y: f32 = 0.018;
/// Base oval semi-axes (m) for a standing 1.75 m character: wider across the stance than front-to-back.
const STAND_RX: f32 = 0.36;
const STAND_RZ: f32 = 0.28;
/// Seat shift behind the character root while sitting on the ground (`live.rs` `SEAT_BEHIND`).
const SEAT_SHIFT: f32 = 0.28;

pub struct ContactShadowPlugin;

impl Plugin for ContactShadowPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Shadows>().add_systems(
            PostUpdate,
            update
                .after(bevy::app::AnimationSystems)
                .before(bevy::transform::TransformSystems::Propagate),
        );
    }
}

/// Marker on each spawned contact shadow entity, pointing to its character.
#[derive(Component, Clone, Copy)]
struct ShadowOf(Entity);

/// Shared mesh, material buckets, and live character -> shadow map.
#[derive(Resource, Default)]
struct Shadows {
    mesh: Option<Handle<Mesh>>,
    mats: Vec<Handle<StandardMaterial>>,
    /// Last applied (tint_srgb, strength) to avoid dirtying materials each frame.
    applied: Option<([f32; 3], f32)>,
    /// Character root entity -> shadow quad entity.
    by_char: HashMap<Entity, Entity>,
}

/// Radial falloff texture (white RGB, soft + core alpha): `AlphaMode::Multiply` mixes dst toward
/// the material's `base_color` by this alpha, so the edge blends seamlessly to 1.0.
fn blob_texture() -> Image {
    const N: u32 = 64;
    let mut px = Vec::with_capacity((N * N * 4) as usize);
    for y in 0..N {
        for x in 0..N {
            let u = (x as f32 + 0.5) / N as f32;
            let v = (y as f32 + 0.5) / N as f32;
            let r = (Vec2::new(u - 0.5, v - 0.5).length() * 2.0).clamp(0.0, 1.0);
            let inv = 1.0 - r;
            let soft = inv * inv * (3.0 - 2.0 * inv);
            let core = inv.powf(2.4);
            let a = (0.62 * soft + 0.38 * core).clamp(0.0, 1.0);
            px.extend_from_slice(&[255, 255, 255, (a * 255.0).round() as u8]);
        }
    }
    Image::new(
        Extent3d { width: N, height: N, depth_or_array_layers: 1 },
        TextureDimension::D2,
        px,
        TextureFormat::Rgba8UnormSrgb,
        RenderAssetUsages::default(),
    )
}

/// Cool-tinted multiply colour and base opacity for the current light.
/// Stronger at noon (where overhead sun hides cast shadows under feet), subtler at dusk and night
/// so shadowed areas and building shade stay deliberate rather than double-crushed.
pub(crate) fn shadow_tint(atmo: Option<&Atmo>, style: &Style) -> ([f32; 3], f32) {
    let (hue, day) = match atmo.filter(|a| a.active) {
        Some(a) => {
            let h = Color::LinearRgba(LinearRgba::new(a.fill.x, a.fill.y, a.fill.z, 1.0)).to_hsva().hue / 360.0;
            let d = (a.lux / 9000.0).clamp(0.0, 1.0);
            (h, d)
        }
        None => (style.shadow_hue, 1.0),
    };
    // Cool slate tinted softly toward the atmosphere's shadow hue.
    let c = Color::hsv(hue * 360.0, 0.38, 0.34).to_srgba();
    let tint = [c.red.clamp(0.16, 0.38), c.green.clamp(0.18, 0.38), c.blue.clamp(0.28, 0.48)];
    // Noon ~0.54, dusk ~0.44, night ~0.34: multiply by mix(1, linear(tint), strength) gives
    // ~0.50x under boots at noon, ~0.58x in dusk shade, ~0.68x under moonlight.
    let strength = 0.30 + 0.24 * day;
    (tint, strength)
}

/// Airborne fraction (0 grounded, 1 peak flight) from procedural jumps or baked jump takes.
pub(crate) fn airborne_of(motion: Option<&Motion>, lift_m: f32) -> f32 {
    let proc_air = motion.map_or(0.0, crate::jump::airborne);
    let take_air = motion
        .and_then(|m| {
            let a = m.action?;
            if !a.clip.starts_with("jump_") {
                return None;
            }
            let t = ((m.now_ms - a.start_ms) / 1000.0) as f32;
            let u = ((t - 0.08) / 0.48).clamp(0.0, 1.0);
            Some((std::f32::consts::PI * u).sin())
        })
        .unwrap_or(0.0);
    let lift_air = (lift_m / 0.55).clamp(0.0, 1.0);
    proc_air.max(take_air).max(lift_air)
}

/// Ground-plane semi-axes (rx, rz) and backward offset along facing for the character's stance.
pub(crate) fn stance_footprint(height: f32, build: f32, speed: f32, seat: f32, dead: bool, air: f32) -> (f32, f32, f32) {
    let h_scale = (height / 1.75).clamp(0.45, 2.2);
    let b_scale = (0.65 + 0.35 * build).clamp(0.75, 1.35);
    let mut rx = STAND_RX * h_scale * b_scale;
    let mut rz = STAND_RZ * h_scale * b_scale;
    // Stride elongates the contact footprint slightly along travel.
    let stride = ((speed - 0.25) / 3.5).clamp(0.0, 1.0);
    rz *= 1.0 + 0.24 * stride;
    // Sitting on the ground broadens the pool and shifts it back under the hips.
    let seat = seat.clamp(0.0, 1.0);
    rx *= 1.0 + 0.30 * seat;
    rz *= 1.0 + 0.45 * seat;
    let back = SEAT_SHIFT * h_scale * seat;
    if dead {
        rx *= 1.35;
        rz *= 1.75;
    }
    // Airborne softens and spreads slightly as feet leave the ground.
    let spread = 1.0 + 0.16 * air;
    (rx * spread, rz * spread, back)
}

#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn update(
    mut commands: Commands,
    look: Res<Look>,
    style: Res<Style>,
    atmo: Option<Res<Atmo>>,
    island: Option<Res<Island>>,
    mut shadows: ResMut<Shadows>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut images: ResMut<Assets<Image>>,
    mut mats: ResMut<Assets<StandardMaterial>>,
    chars: Query<
        (
            Entity,
            &Transform,
            &Model,
            &Fitted,
            &Visibility,
            &InheritedVisibility,
            Option<&Character>,
            Option<&Motion>,
            Option<&Anim>,
            Option<&Fade>,
        ),
        Without<ShadowOf>,
    >,
    mut decals: Query<(&mut Transform, &mut Visibility, &mut MeshMaterial3d<StandardMaterial>), With<ShadowOf>>,
) {
    if *look != Look::Lookdev || !style.enabled {
        if !shadows.by_char.is_empty() {
            for (_, e) in shadows.by_char.drain() {
                commands.entity(e).despawn();
            }
        }
        return;
    }

    // Lazily create shared quad mesh and 8 stepped multiply materials once Look-dev is active.
    if shadows.mesh.is_none() {
        let tex = images.add(blob_texture());
        shadows.mesh = Some(meshes.add(Circle::new(1.0)));
        shadows.mats = (0..LEVELS)
            .map(|i| {
                let frac = (i + 1) as f32 / LEVELS as f32;
                mats.add(StandardMaterial {
                    base_color: Color::srgba(0.24, 0.27, 0.42, 0.50 * frac),
                    base_color_texture: Some(tex.clone()),
                    unlit: true,
                    alpha_mode: AlphaMode::Multiply,
                    depth_bias: 20.0,
                    ..default()
                })
            })
            .collect();
        shadows.applied = None;
    }

    // Refresh the 8 shared materials only when ambient tint or daylight level changes meaningfully.
    let (tint, strength) = shadow_tint(atmo.as_deref(), &style);
    let dirty = shadows.applied.is_none_or(|(t, s)| {
        (s - strength).abs() > 0.015
            || (t[0] - tint[0]).abs() > 0.015
            || (t[1] - tint[1]).abs() > 0.015
            || (t[2] - tint[2]).abs() > 0.015
    });
    if dirty {
        shadows.applied = Some((tint, strength));
        for (i, h) in shadows.mats.iter().enumerate() {
            let frac = (i + 1) as f32 / LEVELS as f32;
            if let Some(m) = mats.get_mut(h) {
                m.base_color = Color::srgba(tint[0], tint[1], tint[2], strength * frac);
            }
        }
    }

    // Remove shadows whose character despawned.
    shadows.by_char.retain(|char_e, shadow_e| {
        let alive = chars.contains(*char_e);
        if !alive {
            commands.entity(*shadow_e).despawn();
        }
        alive
    });

    let mesh = shadows.mesh.clone().unwrap();
    let base_rot = Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2);

    for (e, tf, model, fit, raw_vis, inh_vis, ch, motion, anim, fade) in &chars {
        let is_character = ch.is_some() || model.vrm || crate::handmade::of(&model.file).is_some();
        if !is_character {
            continue;
        }
        let fade_vis = fade.map_or(1.0, |f| (1.0 - f.level).clamp(0.0, 1.0));
        let shown = *raw_vis != Visibility::Hidden && inh_vis.get() && fade_vis > 0.02;

        let pos = tf.translation;
        let ground = island.as_ref().map_or(model.ground_y, |isl| isl.foot_height(pos.x, pos.z));
        let lift = (pos.y - fit.y_off - ground).max(0.0);
        let air = airborne_of(motion, lift);
        let opacity = fade_vis * (1.0 - 0.78 * air).clamp(0.0, 1.0);

        let height = if model.height > 0.0 { model.height } else { fit.size.y.max(0.4) };
        let build = ch.map_or(1.0, |c| c.recipe.proportions.build);
        let speed = motion.map_or(0.0, |m| m.speed);
        let seat = anim.map_or_else(
            || if motion.is_some_and(|m| m.stand == "sit_ground") { 1.0 } else { 0.0 },
            |a| a.ground_seat(),
        );
        let dead = motion.is_some_and(|m| m.action.is_some_and(|a| a.clip == "death"));
        let (rx, rz, back) = stance_footprint(height, build, speed, seat, dead, air);

        // Character forward on XZ (VRM/composed face local -Z, glTF +Z).
        let local_fwd = if model.vrm { Vec3::NEG_Z } else { Vec3::Z };
        let fwd = (tf.rotation * local_fwd).with_y(0.0).normalize_or(Vec3::Z);
        let yaw = fwd.x.atan2(fwd.z);
        let center_xz = Vec2::new(pos.x, pos.z) - Vec2::new(fwd.x, fwd.z) * back;
        let gy = island.as_ref().map_or(model.ground_y, |isl| isl.foot_height(center_xz.x, center_xz.y));

        // Gently tilt to match sloped terrain so the decal hugs hills without clipping.
        let tilt = if let Some(isl) = island.as_deref() {
            let d = 0.25;
            let hx = (isl.height(center_xz.x + d, center_xz.y) - isl.height(center_xz.x - d, center_xz.y)) / (2.0 * d);
            let hz = (isl.height(center_xz.x, center_xz.y + d) - isl.height(center_xz.x, center_xz.y - d)) / (2.0 * d);
            // Clamp steep stair edges so the decal stays level on treads.
            let n = Vec3::new(-hx.clamp(-0.45, 0.45), 1.0, -hz.clamp(-0.45, 0.45)).normalize();
            Quat::from_rotation_arc(Vec3::Y, n)
        } else {
            Quat::IDENTITY
        };

        let decal_tf = Transform::from_translation(Vec3::new(center_xz.x, gy + LIFT_Y, center_xz.y))
            .with_rotation(tilt * Quat::from_rotation_y(yaw) * base_rot)
            .with_scale(Vec3::new(rx, rz, 1.0));
        let bucket = ((opacity * (LEVELS - 1) as f32).round() as usize).clamp(0, LEVELS - 1);
        let mat = shadows.mats[bucket].clone();
        let want_vis = if shown && opacity > 0.04 { Visibility::Visible } else { Visibility::Hidden };

        if let Some(&se) = shadows.by_char.get(&e) {
            if let Ok((mut stf, mut svis, mut smat)) = decals.get_mut(se) {
                *stf = decal_tf;
                if *svis != want_vis {
                    *svis = want_vis;
                }
                if smat.0 != mat {
                    smat.0 = mat;
                }
            }
        } else {
            let se = commands
                .spawn((
                    ShadowOf(e),
                    Mesh3d(mesh.clone()),
                    MeshMaterial3d(mat),
                    decal_tf,
                    want_vis,
                    bevy::light::NotShadowCaster,
                    bevy_mod_outline::StopPropagateOutline,
                    Name::new("contact shadow"),
                ))
                .id();
            shadows.by_char.insert(e, se);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stance_and_airborne_shape_the_contact_shadow() {
        let (rx0, rz0, back0) = stance_footprint(1.75, 1.0, 0.0, 0.0, false, 0.0);
        assert_eq!(back0, 0.0);
        assert!(rx0 > rz0, "standing oval is wider across the feet than front-to-back");

        let (_, rz_walk, _) = stance_footprint(1.75, 1.0, 2.6, 0.0, false, 0.0);
        assert!(rz_walk > rz0, "walking elongates along the stride");

        let (rx_sit, rz_sit, back_sit) = stance_footprint(1.75, 1.0, 0.0, 1.0, false, 0.0);
        assert!(rx_sit > rx0 && rz_sit > rz0 && back_sit > 0.2, "sitting broadens and shifts behind root");

        let (rx_air, rz_air, _) = stance_footprint(1.75, 1.0, 0.0, 0.0, false, 1.0);
        assert!(rx_air > rx0 && rz_air > rz0, "airborne spreads slightly as it fades");
    }

    #[test]
    fn shadow_tint_is_subtler_at_night_and_cool_tinted() {
        let style = Style::default();
        let noon = Atmo { active: true, lux: 9000.0, fill: Vec3::new(0.01, 0.01, 0.025), ..default() };
        let night = Atmo { active: true, lux: 2800.0, fill: Vec3::new(0.01, 0.015, 0.03), ..default() };
        let (t_noon, s_noon) = shadow_tint(Some(&noon), &style);
        let (t_night, s_night) = shadow_tint(Some(&night), &style);
        assert!(t_noon[2] > t_noon[0], "contact shadow carries a cool blue tint");
        assert!(s_noon > s_night, "night contact shadow is gentler so it does not double-crush");
    }

    #[test]
    fn airborne_detects_lift_and_jump_clips() {
        assert_eq!(airborne_of(None, 0.0), 0.0);
        assert!(airborne_of(None, 0.35) > 0.5);
        let m = Motion {
            now_ms: 280.0,
            action: Some(crate::combat::Action { clip: crate::jump::CLIP, start_ms: 0.0, rate: 1.0, ..default() }),
            ..default()
        };
        assert!(airborne_of(Some(&m), 0.0) > 0.8, "procedural jump mid-flight is airborne");
    }
}
