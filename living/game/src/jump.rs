//! How a jump looks (the rules' `jump`: a hop of 1.6 tiles in about 0.45 s, `skills.rhai`).
//!
//! The rules are flat, so the height is presentation only. Where the body's file has a jump take
//! for the hop's way (`takes.rs`: standing, forward, sideways), `live.rs` plays that instead.
//! Otherwise (a backward hop, a file without takes) the jump is drawn here over whatever the
//! body plays (its gait while running, its idle standing): a short crouch, an arc of [`HEIGHT`] m
//! over [`AIR_S`], the legs drawn up in the air, and a dip on landing. Foot IK lets go while the feet are off the ground
//! (`ik.rs`, [`airborne`]). Its timing comes from the move's start on the display clock, like
//! any one-shot (`Motion::action` with the clip name [`CLIP`]).

use crate::anim::Motion;
use bevy::prelude::*;

/// The clip name the jump's move asks for (`combat::look`); no file has it, so `anim.rs` leaves
/// it to this module.
pub const CLIP: &str = "jump";
/// Crouch before leaving the ground, time in the air, and the landing (s); the arc's peak (m).
pub const CROUCH_S: f32 = 0.06;
pub const AIR_S: f32 = 0.44;
const LAND_S: f32 = 0.14;
const HEIGHT: f32 = 0.45;
/// The share of the flight over which the feet leave and meet the ground (foot IK eases).
const EASE: f32 = 0.2;
/// How far the hips dip at the crouch and the landing (m), and how far the legs draw up in the
/// air (radians: the thigh forward, the shin back).
const DIP: f32 = 0.07;
const THIGH: f32 = 0.55;
const SHIN: f32 = 0.95;

pub struct JumpPlugin;

impl Plugin for JumpPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(PostUpdate, (rig, apply).chain().after(bevy::app::AnimationSystems).before(bevy::transform::TransformSystems::Propagate));
    }
}

/// Seconds into a jump, if the body is jumping.
fn into(m: &Motion) -> Option<f32> {
    let a = m.action.filter(|a| a.clip == CLIP)?;
    let t = ((m.now_ms - a.start_ms) / 1000.0) as f32;
    (0.0..CROUCH_S + AIR_S + LAND_S).contains(&t).then_some(t)
}

/// How far off the ground the feet are now (0–1), for foot IK.
pub fn airborne(m: &Motion) -> f32 {
    into(m).map_or(0.0, |t| {
        // Eased over the first and last fifth of the flight: letting go at once (it reached
        // 0.6 within 5% of the flight) snapped the planted foot up to 17 cm in a frame at
        // take-off and at landing.
        let u = ((t - CROUCH_S) / AIR_S).clamp(0.0, 1.0);
        let ease = |x: f32| {
            let x = (x / EASE).clamp(0.0, 1.0);
            x * x * (3.0 - 2.0 * x)
        };
        ease(u) * ease(1.0 - u)
    })
}

/// A person's leg bones (thigh, shin) per side.
#[derive(Component)]
pub struct JumpLegs([(Entity, Entity); 2]);

fn rig(mut commands: Commands, new: Query<Entity, (With<crate::anim::Anim>, With<crate::characters::Character>, Without<JumpLegs>)>, children: Query<&Children>, names: Query<&Name>) {
    for e in &new {
        let find = |n: &str| children.iter_descendants(e).find(|d| names.get(*d).is_ok_and(|x| x.as_str() == n));
        if let (Some(lu), Some(ll), Some(ru), Some(rl)) = (find("J_Bip_L_UpperLeg"), find("J_Bip_L_LowerLeg"), find("J_Bip_R_UpperLeg"), find("J_Bip_R_LowerLeg")) {
            commands.entity(e).insert(JumpLegs([(lu, ll), (ru, rl)]));
        }
    }
}

fn apply(mut q: Query<(&Motion, &mut Transform, Option<&JumpLegs>)>, mut bones: Query<&mut Transform, Without<Motion>>) {
    for (m, mut tf, legs) in &mut q {
        let Some(t) = into(m) else { continue };
        let scale = tf.scale.y;
        // The body's height: a dip, the arc, a dip.
        let (lift, tuck) = if t < CROUCH_S {
            (-DIP * (t / CROUCH_S), 0.0)
        } else if t < CROUCH_S + AIR_S {
            let u = (t - CROUCH_S) / AIR_S;
            (4.0 * HEIGHT * u * (1.0 - u) - DIP * (1.0 - u).powi(4), (std::f32::consts::PI * u).sin())
        } else {
            let u = (t - CROUCH_S - AIR_S) / LAND_S;
            (-DIP * (std::f32::consts::PI * u).sin(), 0.0)
        };
        tf.translation.y += lift * scale;
        // The legs draw up in the air: the thigh forward (the model faces −Z), the shin back.
        if let (Some(legs), true) = (legs, tuck > 0.0) {
            for &(thigh, shin) in &legs.0 {
                if let Ok(mut b) = bones.get_mut(thigh) {
                    b.rotation *= Quat::from_rotation_x(THIGH * tuck);
                }
                if let Ok(mut b) = bones.get_mut(shin) {
                    b.rotation *= Quat::from_rotation_x(-SHIN * tuck);
                }
            }
        }
    }
}
