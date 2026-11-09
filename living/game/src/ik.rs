//! Foot IK: planted feet rest on the ground under them and stay where they came down.
//!
//! Clips are made on flat ground at the character's origin. On a slope, stairs, a terrace edge
//! or a bank the ground under each foot differs from the ground under the body, and a blend of
//! two gaits (`anim.rs`) mixes joint rotations, not foot positions, so a planted foot drifts by
//! up to a tenth of the body's speed. Each frame, after the pose is sampled and before transforms
//! propagate, for each person within [`IK_FAR`] of the camera:
//!
//! - **Contact** comes from the clips' foot-down markers (`Anim::feet`, 0–1, easing in at
//!   touchdown and out at lift-off), times how much of the legs' pose comes from clips where IK
//!   applies (`Anim::ik`: not sitting or lying), times the distance fade.
//! - **Height:** a planted foot's ankle moves by the ground under it minus the ground under the
//!   body: `Island::foot_height`, the island's ground (terraces, banks) except on a flight of
//!   stairs, where it is the tread under the foot (the ground there is the flight's ramp, up to
//!   a riser below a tread); the look-dev ground elsewhere. A foot in the air is only kept out of
//!   the ground.
//! - **Hips** follow the lower planted foot, eased: down by the deepest reach (to [`DROP_MAX`]),
//!   so the lower leg can reach the lower ground and the other knee bends more, or up (to
//!   [`RISE_MAX`]) when both feet stand higher than the ground under the body (treads).
//! - **Lock:** at touchdown the foot's pivot is kept where it came down (the heel while it is
//!   down, the ball once the heel rises more than the toe, as `animate.py`'s `plant_feet` pins
//!   them); while planted the foot is held there, up to [`LOCK_MAX`] from where the clip has it
//!   (further, the lock lets go). Standing
//!   still, a lock follows the clip at [`LOCK_FOLLOW`], so an idle's weight shifts keep their
//!   feet but a stance never stays wrong.
//! - **Legs:** analytic two-bone IK from the hip to the ankle target, the knee bending in the
//!   plane the clip's knee shows. The foot keeps its clip orientation, tilted to the ground's
//!   slope within [`TILT_MAX`] in proportion to contact.
//!
//! **Rotations** (also the rule for any custom pose blending in this client): Bevy's own blending
//! slerps the shortest way between whole local rotations, which is right for poses near each
//! other. Corrections here are computed as world-space deltas (`Quat::from_rotation_arc`) applied
//! to the clip's rotations, then made local again; where a correction is faded in by weight it is
//! faded as a rotation from identity. Any sum or weighted blend of local rotations goes through
//! [`rest_relative`] first: each quaternion is flipped onto the hemisphere of the joint's rest
//! rotation (VRoid's J_Bip rest rotations are identity), so `q` and `−q`, which are the same
//! rotation, can't cancel or take the long way round.
//!
//! Characters only; the wolf keeps its clips' feet.

use crate::anim::Anim;
use bevy::prelude::*;

/// IK applies fully within this distance (m) of the camera and fades out by [`IK_FAR`].
pub const IK_NEAR: f32 = 25.0;
pub const IK_FAR: f32 = 30.0;
/// How far (m) a lock may hold a foot from the clip's, and how fast (m/s) it follows the clip
/// while standing.
const LOCK_MAX: f32 = 0.22;
const LOCK_FOLLOW: f32 = 0.3;
/// The most the feet tilt to the ground (radians) and the most the hips come down (m, at the
/// base's size).
const TILT_MAX: f32 = 0.45;
const DROP_MAX: f32 = 0.35;
const RISE_MAX: f32 = 0.18;
/// How fast the hips' drop follows its target (1/s).
const DROP_RATE: f32 = 14.0;

pub struct IkPlugin;

impl Plugin for IkPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<IkStats>().add_systems(
            PostUpdate,
            (rig, solve)
                .chain()
                .after(bevy::app::AnimationSystems)
                .after(crate::characters::hips)
                .before(bevy::transform::TransformSystems::Propagate),
        );
    }
}

/// Bones of one person's legs, and the IK state.
#[derive(Component)]
pub struct Legs {
    /// From the root's child down to the hips (the root's own transform comes first).
    chain: Vec<Entity>,
    hips: Entity,
    /// Per side (L, R): upper leg, lower leg, foot, toe.
    legs: [[Entity; 4]; 2],
    /// Where each planted foot is held (world x, z), if it is.
    lock: [Option<(Vec2, bool)>; 2],
    /// The hips' drop now (world m, ≤ 0).
    drop: f32,
    /// The lowest ankle height above its ground seen while planted (world m): the sole's depth.
    ankle_h: f32,
    /// The same for the ball of the foot (the toe joint).
    toe_h: f32,
    /// The hips translation this module last wrote, and the drop it added (local), so a frame
    /// whose clips didn't rewrite the hips isn't lowered twice.
    written: Vec3,
    applied: Vec3,
}

/// Frame counts for the cost report (`LIVING_GAME_PERF=diag`).
#[derive(Resource, Default)]
pub struct IkStats {
    pub solved: usize,
    pub micros: f32,
}

/// Find each new person's leg bones once its rig is in (`Anim` exists).
fn rig(mut commands: Commands, new: Query<(Entity, &Anim), (With<crate::characters::Character>, Without<Legs>)>, children: Query<&Children>, names: Query<&Name>, parents: Query<&ChildOf>) {
    for (e, _) in &new {
        let find = |n: &str| children.iter_descendants(e).find(|d| names.get(*d).is_ok_and(|x| x.as_str() == n));
        let Some(hips) = find("J_Bip_C_Hips") else { continue };
        let side = |s: &str| -> Option<[Entity; 4]> { Some([find(&format!("J_Bip_{s}_UpperLeg"))?, find(&format!("J_Bip_{s}_LowerLeg"))?, find(&format!("J_Bip_{s}_Foot"))?, find(&format!("J_Bip_{s}_ToeBase"))?]) };
        let (Some(l), Some(r)) = (side("L"), side("R")) else { continue };
        // The chain from below the root to the hips.
        let mut chain = vec![];
        let mut at = hips;
        while at != e {
            chain.push(at);
            match parents.get(at) {
                Ok(p) => at = p.parent(),
                Err(_) => break,
            }
        }
        if at != e {
            continue;
        }
        chain.reverse();
        commands.entity(e).insert(Legs { chain, hips, legs: [l, r], lock: [None; 2], drop: 0.0, ankle_h: f32::NAN, toe_h: f32::NAN, written: Vec3::NAN, applied: Vec3::ZERO });
    }
}

/// Flip `q` onto the hemisphere of the joint's rest rotation, so sums and weighted blends of
/// rotations agree in sign (see the module notes).
pub fn rest_relative(q: Quat, rest: Quat) -> Quat {
    if q.dot(rest) < 0.0 {
        -q
    } else {
        q
    }
}

/// Two-bone IK: hip `u`, knee `k`, ankle `f` (world), ankle target `a`. Returns the world
/// rotation deltas for the upper and lower leg and the ankle position reached.
pub fn two_bone(u: Vec3, k: Vec3, f: Vec3, a: Vec3, fallback_bend: Vec3) -> (Quat, Quat, Vec3) {
    let (l1, l2) = ((k - u).length(), (f - k).length());
    let d = a - u;
    let len = d.length();
    if len < 1e-5 || l1 < 1e-5 || l2 < 1e-5 {
        return (Quat::IDENTITY, Quat::IDENTITY, f);
    }
    let dir = d / len;
    let dist = len.clamp((l1 - l2).abs() + 1e-4, (l1 + l2) * 0.999);
    // The knee bends where the clip's knee points, off the hip–target line.
    let off = (k - u) - dir * (k - u).dot(dir);
    let bend = if off.length_squared() > 1e-8 { off.normalize() } else { (fallback_bend - dir * fallback_bend.dot(dir)).normalize_or(Vec3::Z) };
    let cos_a = ((l1 * l1 + dist * dist - l2 * l2) / (2.0 * l1 * dist)).clamp(-1.0, 1.0);
    let sin_a = (1.0 - cos_a * cos_a).sqrt();
    let knee = u + l1 * (cos_a * dir + sin_a * bend);
    let reach = u + dir * dist;
    let q1 = Quat::from_rotation_arc((k - u) / l1, (knee - u) / l1);
    let shin = q1 * (f - k);
    let q2 = Quat::from_rotation_arc(shin.normalize(), (reach - knee).normalize());
    (q1, q2, reach)
}

#[allow(clippy::type_complexity, clippy::too_many_arguments)]
fn solve(
    mut people: Query<(&Transform, &Anim, &mut Legs, Option<&mut crate::characters::Shaped>)>,
    mut bones: Query<&mut Transform, Without<Legs>>,
    island: Option<Res<crate::island::Island>>,
    envs: Option<Res<crate::envs::Envs>>,
    cams: Query<&GlobalTransform, With<Camera3d>>,
    time: Res<Time>,
    mut stats: ResMut<IkStats>,
) {
    if crate::perf::has("noik") {
        return;
    }
    let t0 = std::time::Instant::now();
    let dt = time.delta_secs().min(0.1);
    // Where feet stand (treads on stairs), and the ground the body itself is placed on.
    let ground = |x: f32, z: f32| match (&island, &envs) {
        (Some(i), _) => i.foot_height(x, z),
        (None, Some(e)) => e.ground.height(x, z),
        _ => 0.0,
    };
    let body_ground = |x: f32, z: f32| match (&island, &envs) {
        (Some(i), _) => i.height(x, z),
        (None, Some(e)) => e.ground.height(x, z),
        _ => 0.0,
    };
    let eye = cams.iter().next().map(|c| c.translation());
    let mut solved = 0;
    for (root, anim, mut legs, shaped) in &mut people {
        let near = eye.map_or(1.0, |e| 1.0 - ((e.distance(root.translation) - IK_NEAR) / (IK_FAR - IK_NEAR)).clamp(0.0, 1.0));
        let w = near * anim.ik;
        if w <= 0.0 {
            legs.lock = [None; 2];
            legs.drop = 0.0;
            legs.written = Vec3::NAN;
            continue;
        }
        // World transforms down the chain to the hips (the root's own transform is this frame's).
        let mut parent = root.compute_affine();
        let mut ok = true;
        for &b in &legs.chain[..legs.chain.len() - 1] {
            match bones.get(b) {
                Ok(tf) => parent *= tf.compute_affine(),
                Err(_) => ok = false,
            }
        }
        let Ok(hips_tf) = bones.get(legs.hips).map(|t| *t) else { continue };
        if !ok {
            continue;
        }
        let hips_parent = parent;
        let hips = hips_parent * hips_tf.compute_affine();
        let scale = root.scale.x.max(1e-3);
        let floor = body_ground(root.translation.x, root.translation.z);
        // Each leg as the clip has it: hip, knee, ankle, toe (world) and the rotations.
        let mut pose = [[Vec3::ZERO; 4]; 2];
        let mut rot = [[Quat::IDENTITY; 3]; 2];
        let mut locals = [[Transform::IDENTITY; 4]; 2];
        for s in 0..2 {
            let mut m = hips;
            for (j, &b) in legs.legs[s].iter().enumerate() {
                let Ok(tf) = bones.get(b) else { ok = false; break };
                locals[s][j] = *tf;
                m *= tf.compute_affine();
                pose[s][j] = m.translation.into();
                if j < 3 {
                    rot[s][j] = m.to_scale_rotation_translation().1;
                }
            }
        }
        if !ok {
            continue;
        }
        // Where each foot wants to be: on its own ground while planted, held where it came down.
        let mut target = [Vec3::ZERO; 2];
        let mut low = f32::INFINITY;
        let mut tilt = [Quat::IDENTITY; 2];
        for s in 0..2 {
            let c = (anim.feet[s] * w).clamp(0.0, 1.0);
            let f = pose[s][2];
            let toe = pose[s][3];
            let gf = ground(f.x, f.z);
            let above = f.y - floor;
            if c > 0.9 {
                legs.ankle_h = if legs.ankle_h.is_nan() { above } else { legs.ankle_h.min(above) + dt * 0.02 };
            }
            let ankle_h = if legs.ankle_h.is_nan() { 0.09 * scale } else { legs.ankle_h };
            let toe_above = toe.y - floor;
            if c > 0.9 {
                legs.toe_h = if legs.toe_h.is_nan() { toe_above } else { legs.toe_h.min(toe_above) + dt * 0.02 };
            }
            let toe_h = if legs.toe_h.is_nan() { 0.03 * scale } else { legs.toe_h };
            // Lock: the foot's pivot (the heel while it is down, the ball once the heel has risen
            // more than the toe) is held where it came down while planted, and let go when the
            // clip's is far. Changing pivot re-anchors at the same offset, so nothing jumps.
            let at = Vec2::new(f.x, f.z);
            let ball = Vec2::new(toe.x, toe.z);
            let on_ball = above - ankle_h > toe_above - toe_h + 0.01 * scale;
            let pivot = |b: bool| if b { ball } else { at };
            let lock = match legs.lock[s] {
                Some((l, was)) if c > 0.0 && l.distance(pivot(was)) < LOCK_MAX * scale => {
                    let l = if was == on_ball { l } else { pivot(on_ball) + (l - pivot(was)) };
                    // Standing, the lock drifts toward the clip's foot.
                    let follow = LOCK_FOLLOW * scale * dt * (1.0 - anim.moving);
                    let d = pivot(on_ball) - l;
                    Some((if d.length() <= follow { pivot(on_ball) } else { l + d / d.length() * follow }, on_ball))
                }
                _ if c > 0.5 => Some((pivot(on_ball), on_ball)),
                _ => None,
            };
            legs.lock[s] = lock;
            let xz = lock.map_or(at, |(l, b)| at + (l - pivot(b)) * c);
            let g = if lock.is_some() { ground(xz.x, xz.y) } else { gf };
            let dy = c * (g - floor);
            // A foot in the air stays above the ground under it.
            let lift = (g + ankle_h - (f.y + dy)).max(0.0) * (1.0 - c);
            target[s] = Vec3::new(xz.x, f.y + dy + lift, xz.y);
            low = low.min(dy);
            // Slope under the foot, from the ground ahead and to the side.
            let fwd = Vec2::new(toe.x - f.x, toe.z - f.z).normalize_or(Vec2::X);
            let side = Vec2::new(-fwd.y, fwd.x);
            let e = 0.12 * scale;
            let (p0, p1, p2) = (Vec2::new(xz.x, xz.y), Vec2::new(xz.x, xz.y) + fwd * e, Vec2::new(xz.x, xz.y) + side * e);
            let (h0, h1, h2) = (g, ground(p1.x, p1.y), ground(p2.x, p2.y));
            let n = Vec3::new(p1.x - p0.x, h1 - h0, p1.y - p0.y).cross(Vec3::new(p2.x - p0.x, h2 - h0, p2.y - p0.y)).normalize_or(Vec3::Y);
            let n = if n.y < 0.0 { -n } else { n };
            let q = Quat::from_rotation_arc(Vec3::Y, n);
            let (axis, angle) = q.to_axis_angle();
            tilt[s] = Quat::from_axis_angle(axis, angle.min(TILT_MAX) * c);
        }
        // The hips follow the lower planted foot, eased.
        let want = if low.is_finite() { low.clamp(-DROP_MAX * scale, RISE_MAX * scale) } else { 0.0 };
        legs.drop += (want - legs.drop) * (1.0 - (-dt * DROP_RATE).exp());
        let drop = Vec3::Y * legs.drop;
        if let Ok(mut h) = bones.get_mut(legs.hips) {
            let local = hips_parent.inverse().transform_vector3(drop);
            let base = if h.translation == legs.written { h.translation - legs.applied } else { h.translation };
            h.translation = base + local;
            legs.written = h.translation;
            legs.applied = local;
            // `characters::hips` scales a freshly animated hips translation; this one isn't.
            if let Some(mut sh) = shaped {
                sh.wrote(h.translation);
            }
        }
        let hips_rot = hips.to_scale_rotation_translation().1;
        for s in 0..2 {
            let [u, k, f, _] = pose[s].map(|p| p + drop);
            let fwd = root.rotation * Vec3::NEG_Z;
            let (q1, q2, _) = two_bone(u, k, f, target[s], fwd);
            let upper = q1 * rot[s][0];
            let lower = q2 * q1 * rot[s][1];
            let foot = tilt[s] * rot[s][2];
            let rest = Quat::IDENTITY;
            let set = |b: Entity, q: Quat, bones: &mut Query<&mut Transform, Without<Legs>>| {
                if let Ok(mut tf) = bones.get_mut(b) {
                    tf.rotation = rest_relative(q.normalize(), rest);
                }
            };
            set(legs.legs[s][0], hips_rot.inverse() * upper, &mut bones);
            set(legs.legs[s][1], upper.inverse() * lower, &mut bones);
            set(legs.legs[s][2], lower.inverse() * foot, &mut bones);
        }
        solved += 1;
    }
    stats.solved = solved;
    stats.micros = t0.elapsed().as_secs_f32() * 1e6;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn two_bone_reaches_a_target_in_reach_and_keeps_its_lengths() {
        let (u, k, f) = (Vec3::new(0.0, 1.0, 0.0), Vec3::new(0.0, 0.55, -0.05), Vec3::new(0.0, 0.1, 0.0));
        for a in [Vec3::new(0.0, 0.2, 0.1), Vec3::new(0.05, 0.25, -0.15), Vec3::new(0.0, 0.15, 0.02)] {
            let (q1, q2, reach) = two_bone(u, k, f, a, Vec3::NEG_Z);
            let knee = u + q1 * (k - u);
            let ankle = knee + q2 * q1 * (f - k);
            assert!((ankle - a).length() < 1e-3, "reached {ankle} for {a}");
            assert!((reach - a).length() < 1e-3);
            assert!(((knee - u).length() - (k - u).length()).abs() < 1e-4);
            // The knee still bends the way the clip's did, off the hip–target line.
            let dir = (a - u).normalize();
            let off = |p: Vec3| (p - u) - dir * (p - u).dot(dir);
            assert!(off(knee).dot(off(k)) > 0.0, "knee {knee} bends against the clip's {k}");
        }
        // Out of reach: the leg straightens toward it.
        let (q1, q2, reach) = two_bone(u, k, f, Vec3::new(0.0, -1.0, 0.0), Vec3::NEG_Z);
        let ankle = u + q1 * (k - u) + q2 * q1 * (f - k);
        assert!((ankle - reach).length() < 1e-3 && reach.y > -0.01);
    }

    #[test]
    fn rest_relative_blending_never_takes_the_long_way() {
        let a = Quat::from_rotation_x(0.3);
        // The same rotation with the opposite sign: a naive lerp would pass through zero.
        let b = -Quat::from_rotation_x(0.5);
        let naive = (a + b) * 0.5;
        assert!(naive.length() < 0.1, "summed as they are, they nearly cancel");
        let m = (rest_relative(a, Quat::IDENTITY) + rest_relative(b, Quat::IDENTITY)).normalize();
        assert!((m.angle_between(Quat::from_rotation_x(0.4))).abs() < 1e-3);
        assert!(rest_relative(b, Quat::IDENTITY).w > 0.0);
    }
}

/// Where to photograph feet on uneven ground: `cargo test --release -p living-game -- --ignored
/// uneven_ground_spots --nocapture` lists the look-dev island's stairs and retaining walls near the
/// town and its steepest walkable slope there.
#[cfg(test)]
mod spots {
    #[test]
    #[ignore]
    fn uneven_ground_spots() {
        let land = living_rules::land::generate(7, 2048, &living_rules::land::LandParams::default());
        let town = land.settlements.iter().find(|s| s.kind == living_rules::land::SiteKind::Town).unwrap();
        let c = town.plaza.centre;
        let near = |p: (f32, f32)| ((p.0 - c.0).powi(2) + (p.1 - c.1).powi(2)).sqrt();
        let mut props: Vec<_> = land.props.iter().filter(|p| p.kind.id() == "stairs").collect();
        props.sort_by(|a, b| near(a.centre).total_cmp(&near(b.centre)));
        let walls = land.props.iter().filter(|p| p.kind.id() == "retaining_wall").min_by(|a, b| near(a.centre).total_cmp(&near(b.centre)));
        for p in props.iter().take(6).copied().chain(walls) {
            let (x, z) = p.centre;
            let (f0, f1) = ((x - p.front.0 * 2.0, z - p.front.1 * 2.0), (x + p.front.0 * 2.0, z + p.front.1 * 2.0));
            println!("{} floor {:.3} at ({x:.1}, {z:.1}) front ({:.2}, {:.2}) {}x{} m, height {:.2} m, ground behind {:.2} ahead {:.2}, {:.0} m from the plaza", p.kind.id(), p.floor_m, p.front.0, p.front.1, p.width_m, p.depth_m, p.height_m, land.height(f0.0, f0.1), land.height(f1.0, f1.1), near(p.centre));
        }
        let mut best = (0.0f32, 0.0f32, 0.0f32);
        for i in -60..60 {
            for j in -60..60 {
                let (x, z) = (c.0 + i as f32 * 2.0, c.1 + j as f32 * 2.0);
                if !land.map.at(x, z).walkable() {
                    continue;
                }
                let g = ((land.height(x + 0.5, z) - land.height(x - 0.5, z)).powi(2) + (land.height(x, z + 0.5) - land.height(x, z - 0.5)).powi(2)).sqrt();
                if g > best.0 && g < 0.35 {
                    best = (g, x, z);
                }
            }
        }
        let (_, x, z) = best;
        let (gx, gz) = (land.height(x + 0.5, z) - land.height(x - 0.5, z), land.height(x, z + 0.5) - land.height(x, z - 0.5));
        println!("steepest walkable slope under 0.35 near the town: grade {:.2} at ({x:.1}, {z:.1}), uphill ({gx:.2}, {gz:.2})", best.0);
        // Along the nearest retaining wall's top, 0.6 m back from its face.
        if let Some(w) = walls {
            let (fx, fz) = w.front;
            for k in -8..=8 {
                let d = k as f32 * 0.25;
                let (x, z) = (w.centre.0 + fx * d, w.centre.1 + fz * d);
                println!("across the wall {d:+.2} m: ({x:.2}, {z:.2}) ground {:.2} walkable {}", land.height(x, z), land.map.at(x, z).walkable());
            }
            for k in -6..=6 {
                let (x, z) = (w.centre.0 - fx * (w.depth_m * 0.5 + 0.6) + fz * k as f32, w.centre.1 - fz * (w.depth_m * 0.5 + 0.6) - fx * k as f32);
                println!("wall top {k:+}: ({x:.1}, {z:.1}) ground {:.2} walkable {}", land.height(x, z), land.map.at(x, z).walkable());
            }
        }
    }
}
