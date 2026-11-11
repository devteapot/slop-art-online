//! The upper body turns toward where a person looks while the legs keep to their travel.
//!
//! A body that faces the cursor while it walks another way has no strafe clips: the legs walk
//! the way the body goes (forward, or backward with the gaits reversed, `anim.rs`), and the
//! spine, chest, neck and head turn the rest of the way ([`Motion::twist`], set by `live.rs`).
//! Feet stay planted because the legs always step along their travel.
//!
//! The turn is a rotation about each bone's own long axis (VRoid's spine bones point up their
//! local +Y, rest rotations identity), applied after the clips are sampled and before transforms
//! propagate, shared out by [`SHARE`]. A bone no clip wrote this frame still holds last frame's
//! turn, so it is taken off before the new one goes on.

use crate::anim::{Anim, Motion};
use bevy::prelude::*;

/// The spine bones and their share of the turn (they add up to 1): at a 90° strafe the spine
/// turns 52° and the neck and head 38°. Before feel pass 5 the neck and head took 25° and the
/// chest the rest, which looked wrung out; a person looking aside turns the head most. (A share
/// on the pelvis, with the thighs turned back, moved the planted feet under foot IK: ±7 cm as
/// the cursor swayed ±25°, so the hips stay with the legs.)
const SHARE: [(&str, f32); 5] = [("J_Bip_C_Spine", 0.18), ("J_Bip_C_Chest", 0.18), ("J_Bip_C_UpperChest", 0.22), ("J_Bip_C_Neck", 0.20), ("J_Bip_C_Head", 0.22)];

pub struct TwistPlugin;

impl Plugin for TwistPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(PostUpdate, (rig, apply).chain().after(bevy::app::AnimationSystems).before(bevy::transform::TransformSystems::Propagate));
    }
}

/// One person's spine bones, their shares, and the rotation each was last left at.
#[derive(Component)]
pub struct Spine {
    bones: Vec<(Entity, f32, Option<(Quat, Quat)>)>,
}

fn rig(mut commands: Commands, new: Query<Entity, (With<Anim>, With<crate::characters::Character>, Without<Spine>)>, children: Query<&Children>, names: Query<&Name>) {
    for e in &new {
        let bones: Vec<(Entity, f32, Option<(Quat, Quat)>)> = SHARE.iter().filter_map(|(n, k)| children.iter_descendants(e).find(|d| names.get(*d).is_ok_and(|x| x.as_str() == *n)).map(|b| (b, *k, None))).collect();
        if !bones.is_empty() {
            commands.entity(e).insert(Spine { bones });
        }
    }
}

fn apply(mut people: Query<(&Motion, &mut Spine)>, mut bones: Query<&mut Transform, Without<Spine>>) {
    for (m, mut spine) in &mut people {
        // Sim angles turn counter-clockwise seen from above; Bevy's +Y turn does the same seen
        // from above with x east and z south, which is the opposite sense.
        let angle = -m.twist;
        for (bone, share, last) in spine.bones.iter_mut() {
            let Ok(mut tf) = bones.get_mut(*bone) else { continue };
            // Not rewritten by a clip this frame: take last frame's turn off first.
            let base = match *last {
                Some((written, turn)) if tf.rotation == written => written * turn.inverse(),
                _ => tf.rotation,
            };
            if angle.abs() < 1e-4 {
                if last.is_some() {
                    tf.rotation = base;
                    *last = None;
                }
                continue;
            }
            let turn = Quat::from_rotation_y(angle * *share);
            tf.rotation = base * turn;
            *last = Some((tf.rotation, turn));
        }
    }
}
