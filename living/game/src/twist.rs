//! Looking one way while walking another: the head turns first, then the chest, each up to its
//! limit, and past them the body comes round on an eased curve (play-test 5, the owner: "rotating
//! the head with that movement, and only when you get past some degrees start to rotate the body
//! … like an exponential curve to reach the angle of the pointer").
//!
//! **Where the legs face** (`live.rs`, walking with a look): an eased angle, not the look and not
//! the travel. Its goal is the travel turned toward the look by whatever the head and chest can't
//! take ([`LookWalk::upper`]), at most [`LookWalk::body_deg`]; past [`LookWalk::back_deg`] off the
//! travel it is the travel's reverse (walking backwards), turned the same way. The legs approach the goal exponentially
//! in time ([`LookWalk::body_s`]), no faster than [`LookWalk::body_dps`]. The gait is always the
//! file's directional takes for the travel as seen from where the legs face now
//! (`gait::Gaits::blend_toward`): steady, that is the forward or backward walk or a diagonal (≤ 45°
//! from either), whose feet don't cross. Right after a sudden turn of the travel with the look held, the legs still
//! face the old way, so a real sidestep plays (the crossover strafe at 90°) until the body has come
//! round: crossing is brief and deliberate, never the steady state of a glance aside. Before this
//! (feel pass 5) the legs faced the look whenever the file had a take for the travel from it, so a
//! glance 90° aside crossed the legs and stepped twice as often for as long as it lasted.
//!
//! **The upper body** turns the rest of the way ([`Motion::twist`], set by `live.rs`), shared out
//! head first ([`Motion::neck`], up to [`LookWalk::head_deg`] over the neck and head), then the
//! spine and chest (up to [`LookWalk::chest_deg`]); the eyes take a little more
//! ([`Motion::eyes`], up to [`LookWalk::eyes_deg`]) where the file has eye bones. The turn is a
//! rotation about each bone's own long axis (VRoid's spine bones point up their local +Y, rest
//! rotations identity), applied after the clips are sampled and before transforms propagate. A bone
//! no clip wrote this frame still holds last frame's turn, so it is taken off before the new one
//! goes on. (A share on the pelvis, with the thighs turned back, moved the planted feet under foot
//! IK: ±7 cm as the cursor swayed ±25°, so the hips stay with the legs.)
//!
//! **Tuning** ([`LookWalk`]): three named presets (Settings › Play › "Looking aside",
//! `LIVING_GAME_LOOK_WALK=<preset>[,key=value…]`, the live script's `lookwalk:` step), each value
//! overridable by name for exploring.

use crate::anim::{Anim, Motion};
use bevy::prelude::*;
use std::f32::consts::PI;

/// The spine bones that share the chest's turn, and the neck bones that share the head's, by
/// weight within each group. Eye bones take [`Motion::eyes`] whole.
const CHEST: [(&str, f32); 3] = [("J_Bip_C_Spine", 0.30), ("J_Bip_C_Chest", 0.30), ("J_Bip_C_UpperChest", 0.40)];
const NECK: [(&str, f32); 2] = [("J_Bip_C_Neck", 0.45), ("J_Bip_C_Head", 0.55)];
const EYES: [&str; 2] = ["J_Adj_L_FaceEye", "J_Adj_R_FaceEye"];

/// How a body looks aside while it walks: the limits (degrees) and the body's curve.
#[derive(Resource, Clone, Debug, PartialEq)]
pub struct LookWalk {
    /// The preset this started from (`head`, `chest`, `loose`), with `*` once a value is changed.
    pub name: String,
    /// The neck and head turn at most this far from the chest.
    pub head_deg: f32,
    /// The spine and chest turn at most this far from the hips.
    pub chest_deg: f32,
    /// The legs turn at most this far off the travel (or its reverse, walking backwards) toward
    /// the look (the files' diagonal takes are at 45° and 135°: further, the steady walk would be
    /// a crossover).
    pub body_deg: f32,
    /// The legs approach their goal by `1 - exp(-dt / body_s)` a frame (s): about 63% in
    /// `body_s`, 95% in three times it.
    pub body_s: f32,
    /// …and never faster than this (degrees a second), so a sudden goal (a flip to walking
    /// backwards) is a turn, not a jump.
    pub body_dps: f32,
    /// Looking more than this far from the travel, the legs walk backwards; forward again under
    /// `back_deg - 25`.
    pub back_deg: f32,
    /// The eyes take up to this much of what the head and chest leave.
    pub eyes_deg: f32,
}

impl Default for LookWalk {
    fn default() -> Self {
        Self::preset(DEFAULT).unwrap()
    }
}

/// The preset a new viewer starts with (the recommendation for play-test 6).
pub const DEFAULT: &str = "chest";
/// The presets as Settings shows them: label, name.
pub const PRESETS: [(&str, &str); 3] = [("Head to 60°", "head"), ("Head and chest to 90°", "chest"), ("Loose", "loose")];
/// Back to forward walking this far (degrees) under [`LookWalk::back_deg`].
const BACK_HYSTERESIS: f32 = 25.0;

impl LookWalk {
    pub fn preset(name: &str) -> Option<Self> {
        let (head_deg, chest_deg, body_deg, body_s, body_dps, back_deg, eyes_deg) = match name {
            // The head alone takes a glance: up to 60°, and the body comes round briskly past it.
            "head" => (60.0, 0.0, 45.0, 0.22, 540.0, 130.0, 12.0),
            // The head to 50°, the chest 40° more: a look up to 90° off the travel leaves the legs
            // on it; past that the body follows on a moderate curve.
            "chest" => (50.0, 40.0, 45.0, 0.35, 450.0, 135.0, 12.0),
            // A supple, lazy turn: more twist, the body slow to follow, backwards only well behind.
            "loose" => (60.0, 55.0, 45.0, 0.6, 300.0, 155.0, 15.0),
            _ => return None,
        };
        Some(Self { name: name.into(), head_deg, chest_deg, body_deg, body_s, body_dps, back_deg, eyes_deg })
    }

    /// `<preset>[,key=value…]` (keys are the field names without `_deg`/`_s`/`_dps`: `head`,
    /// `chest`, `body`, `body_s`, `body_dps`, `back`, `eyes`). An unknown preset or key is an error.
    pub fn parse(spec: &str) -> Result<Self, String> {
        let mut parts = spec.split(',').map(str::trim).filter(|p| !p.is_empty());
        let first = parts.next().unwrap_or(DEFAULT);
        let (mut lw, rest): (Self, Vec<&str>) = match Self::preset(first) {
            Some(p) => (p, parts.collect()),
            None if first.contains('=') => (Self::default(), std::iter::once(first).chain(parts).collect()),
            None => return Err(format!("no look-walk preset {first} (head, chest, loose)")),
        };
        for kv in rest {
            let (k, v) = kv.split_once('=').ok_or_else(|| format!("{kv}: want key=value"))?;
            let v: f32 = v.trim().parse().map_err(|_| format!("{kv}: not a number"))?;
            let slot = match k.trim() {
                "head" => &mut lw.head_deg,
                "chest" => &mut lw.chest_deg,
                "body" => &mut lw.body_deg,
                "body_s" => &mut lw.body_s,
                "body_dps" => &mut lw.body_dps,
                "back" => &mut lw.back_deg,
                "eyes" => &mut lw.eyes_deg,
                other => return Err(format!("no look-walk value {other}")),
            };
            *slot = v;
            if !lw.name.ends_with('*') {
                lw.name.push('*');
            }
        }
        lw.head_deg = lw.head_deg.clamp(0.0, 90.0);
        lw.chest_deg = lw.chest_deg.clamp(0.0, 90.0);
        lw.body_deg = lw.body_deg.clamp(0.0, 90.0);
        lw.body_s = lw.body_s.max(0.02);
        lw.body_dps = lw.body_dps.max(30.0);
        lw.back_deg = lw.back_deg.clamp(90.0, 181.0);
        lw.eyes_deg = lw.eyes_deg.clamp(0.0, 30.0);
        Ok(lw)
    }

    /// `LIVING_GAME_LOOK_WALK`, when set (it wins over the settings file).
    pub fn from_env() -> Option<Self> {
        let spec = std::env::var("LIVING_GAME_LOOK_WALK").ok().filter(|s| !s.trim().is_empty())?;
        match Self::parse(&spec) {
            Ok(lw) => Some(lw),
            Err(e) => {
                warn!("LIVING_GAME_LOOK_WALK={spec}: {e}");
                None
            }
        }
    }

    /// The base preset's name (without a `*`).
    pub fn base(&self) -> &str {
        self.name.trim_end_matches('*')
    }

    /// How far the head and chest together turn from the hips (radians).
    pub fn upper(&self) -> f32 {
        (self.head_deg + self.chest_deg).to_radians()
    }

    /// Where the legs aim walking along `travel` while looking `look` (sim radians), and whether
    /// that is walking backwards (`back`: last frame's, for the hysteresis). `turns`: the file can
    /// step the diagonal there (else the legs keep to the travel or its reverse).
    pub fn legs_goal(&self, travel: f32, look: f32, back: bool, turns: impl Fn(f32) -> bool) -> (f32, bool) {
        let off = wrap(look - travel).abs().to_degrees();
        let back = if back { off > self.back_deg - BACK_HYSTERESIS } else { off > self.back_deg };
        let base = if back { wrap(travel + PI) } else { travel };
        let rest = wrap(look - base);
        // Backwards too, up to the back diagonals (clips 3's `walk_diag_bl`/`_br`); a file without
        // them keeps the legs on the reverse (`turns`).
        let most = self.body_deg.to_radians();
        let by = (rest.abs() - self.upper()).clamp(0.0, most) * rest.signum();
        let goal = wrap(base + by);
        if by != 0.0 && !turns(goal) {
            return (base, back);
        }
        (goal, back)
    }

    /// One frame of the legs' approach to `goal` from `yaw` (radians).
    pub fn ease(&self, yaw: f32, goal: f32, dt: f32) -> f32 {
        let d = wrap(goal - yaw);
        let cap = self.body_dps.to_radians() * dt;
        wrap(yaw + (d * (1.0 - (-dt / self.body_s).exp())).clamp(-cap, cap))
    }

    /// The upper body's turn from the legs toward `off` (radians, sim sense), head first: (all of
    /// it, the neck and head's part of it, the eyes' extra).
    pub fn split(&self, off: f32) -> (f32, f32, f32) {
        let total = off.clamp(-self.upper(), self.upper());
        let head = self.head_deg.to_radians();
        let neck = total.clamp(-head, head);
        let eyes = (off - total).clamp(-self.eyes_deg.to_radians(), self.eyes_deg.to_radians());
        (total, neck, eyes)
    }
}

fn wrap(a: f32) -> f32 {
    living_rules::steer::wrap(a)
}

pub struct TwistPlugin;

impl Plugin for TwistPlugin {
    fn build(&self, app: &mut App) {
        let lw = LookWalk::from_env().unwrap_or_default();
        info!("look-walk: {} (head {}°, chest {}°, body {}° over {} s, backwards past {}°)", lw.name, lw.head_deg, lw.chest_deg, lw.body_deg, lw.body_s, lw.back_deg);
        app.insert_resource(lw).add_systems(PostUpdate, (rig, apply).chain().after(bevy::app::AnimationSystems).before(bevy::transform::TransformSystems::Propagate));
    }
}

/// Which part of the turn a bone takes.
#[derive(Clone, Copy)]
enum Part {
    Chest(f32),
    Neck(f32),
    Eye,
}

/// One person's turned bones, their parts, and the rotation each was last left at; how far the
/// neck and head hold the look over the clip's own turn of them ([`Motion::aim`], eased).
#[derive(Component)]
pub struct Spine {
    bones: Vec<(Entity, Part, Option<(Quat, Quat)>)>,
    hold: f32,
}

/// [`Spine::hold`] eases in and out at this rate (1/s): about 95% in 0.2 s.
const HOLD_RATE: f32 = 15.0;

fn rig(mut commands: Commands, new: Query<Entity, (With<Anim>, With<crate::characters::Character>, Without<Spine>)>, children: Query<&Children>, names: Query<&Name>) {
    for e in &new {
        let find = |n: &str| children.iter_descendants(e).find(|d| names.get(*d).is_ok_and(|x| x.as_str() == n));
        let mut bones: Vec<(Entity, Part, Option<(Quat, Quat)>)> = vec![];
        bones.extend(CHEST.iter().filter_map(|(n, k)| find(n).map(|b| (b, Part::Chest(*k), None))));
        bones.extend(NECK.iter().filter_map(|(n, k)| find(n).map(|b| (b, Part::Neck(*k), None))));
        bones.extend(EYES.iter().filter_map(|n| find(n).map(|b| (b, Part::Eye, None))));
        if !bones.is_empty() {
            commands.entity(e).insert(Spine { bones, hold: 0.0 });
        }
    }
}

/// The turn about local +Y in a bone's rotation (its swing-twist decomposition's twist), radians.
fn yaw_in(q: Quat) -> f32 {
    2.0 * q.y.atan2(q.w)
}

fn apply(mut people: Query<(&Motion, &mut Spine)>, mut bones: Query<&mut Transform, Without<Spine>>, time: Res<Time>) {
    let k = 1.0 - (-time.delta_secs() * HOLD_RATE).exp();
    for (m, mut spine) in &mut people {
        // Sim angles turn counter-clockwise seen from above; Bevy's +Y turn does the same seen
        // from above with x east and z south, which is the opposite sense.
        let (chest, neck, eyes) = (-(m.twist - m.neck), -m.neck, -m.eyes);
        spine.hold += (if m.aim { 1.0 } else { 0.0 } - spine.hold) * k;
        let hold = spine.hold;
        for (bone, part, last) in spine.bones.iter_mut() {
            let Ok(mut tf) = bones.get_mut(*bone) else { continue };
            // Not rewritten by a clip this frame: take last frame's turn off first.
            let base = match *last {
                Some((written, turn)) if tf.rotation == written => written * turn.inverse(),
                _ => tf.rotation,
            };
            // Holding a look, the neck and head lose the clip's own turn about their axis, so the
            // head ends where it was asked to.
            let held = match *part {
                Part::Neck(_) if hold > 1e-3 => -yaw_in(base) * hold,
                _ => 0.0,
            };
            let angle = held
                + match *part {
                    Part::Chest(k) => chest * k,
                    Part::Neck(k) => neck * k,
                    Part::Eye => eyes,
                };
            if angle.abs() < 1e-4 {
                if last.is_some() {
                    tf.rotation = base;
                    *last = None;
                }
                continue;
            }
            let turn = Quat::from_rotation_y(angle);
            tf.rotation = base * turn;
            *last = Some((tf.rotation, turn));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn deg(r: f32) -> f32 {
        r.to_degrees()
    }

    #[test]
    fn the_head_turns_first_then_the_chest_then_the_eyes() {
        let lw = LookWalk::preset("chest").unwrap();
        let (t, n, e) = lw.split(30f32.to_radians());
        assert!((deg(t) - 30.0).abs() < 1e-3 && (deg(n) - 30.0).abs() < 1e-3 && e == 0.0);
        let (t, n, e) = lw.split(70f32.to_radians());
        assert!((deg(t) - 70.0).abs() < 1e-3 && (deg(n) - 50.0).abs() < 1e-3 && e == 0.0, "chest takes 20°");
        let (t, n, e) = lw.split(-120f32.to_radians());
        assert!((deg(t) + 90.0).abs() < 1e-3 && (deg(n) + 50.0).abs() < 1e-3 && (deg(e) + 12.0).abs() < 1e-3);
    }

    #[test]
    fn the_legs_keep_to_the_travel_within_the_upper_limit_and_turn_past_it() {
        let lw = LookWalk::preset("chest").unwrap();
        let yes = |_| true;
        for look in [0.0f32, 45.0, -45.0, 90.0, -90.0] {
            let (g, b) = lw.legs_goal(0.3, 0.3 + look.to_radians(), false, yes);
            assert!(!b && (g - 0.3).abs() < 1e-5, "{look}: {}", deg(g));
        }
        let (g, b) = lw.legs_goal(0.0, 120f32.to_radians(), false, yes);
        assert!(!b && (deg(g) - 30.0).abs() < 1e-3, "120° leaves 30° for the body: {}", deg(g));
        let (g, b) = lw.legs_goal(0.0, 134f32.to_radians(), false, yes);
        assert!(!b && (deg(g) - 44.0).abs() < 1e-3);
        // Past the back limit: backwards, the upper body taking the rest; forward again 25° under.
        let (g, b) = lw.legs_goal(0.0, 150f32.to_radians(), false, yes);
        assert!(b && (deg(wrap(g)).abs() - 180.0).abs() < 1e-3);
        // Backwards past the head and chest, the legs turn toward the look on the back diagonal.
        let lw2 = LookWalk::parse("head,back=95").unwrap();
        let (g, b) = lw2.legs_goal(0.0, 100f32.to_radians(), false, yes);
        assert!(b && (deg(g) - 160.0).abs() < 1e-3, "{}", deg(g));
        assert!(lw.legs_goal(0.0, 115f32.to_radians(), true, yes).1);
        assert!(!lw.legs_goal(0.0, 105f32.to_radians(), true, yes).1);
        // A file without the diagonal keeps the legs on the travel.
        let (g, _) = lw.legs_goal(0.0, 120f32.to_radians(), false, |_| false);
        assert!(g.abs() < 1e-6);
    }

    #[test]
    fn the_body_comes_round_on_an_exponential_curve_never_faster_than_its_cap() {
        let lw = LookWalk::preset("chest").unwrap();
        let dt = 1.0 / 60.0;
        let (mut y, goal) = (0.0f32, 40f32.to_radians());
        let mut t = 0.0;
        while wrap(goal - y).abs() > 40f32.to_radians() * (1.0 - 0.632) {
            let n = lw.ease(y, goal, dt);
            assert!(wrap(n - y).abs() <= lw.body_dps.to_radians() * dt + 1e-6);
            y = n;
            t += dt;
        }
        assert!((t - lw.body_s).abs() < 2.0 * dt, "63% in body_s: {t}");
        // A flip is capped: 180° takes at least 180 / body_dps.
        let mut y = 0.0f32;
        let mut steps = 0;
        while wrap(PI - y).abs() > 0.01 && steps < 1000 {
            y = lw.ease(y, PI - 1e-3, dt);
            steps += 1;
        }
        assert!(steps as f32 * dt >= 180.0 / lw.body_dps - dt);
    }

    #[test]
    fn presets_parse_with_overrides() {
        let lw = LookWalk::parse("loose,head=40,body_s=0.5").unwrap();
        assert_eq!((lw.name.as_str(), lw.head_deg, lw.body_s, lw.chest_deg), ("loose*", 40.0, 0.5, 55.0));
        assert_eq!(LookWalk::parse("head").unwrap(), LookWalk::preset("head").unwrap());
        assert!(LookWalk::parse("tight").is_err() && LookWalk::parse("chest,nose=3").is_err());
        assert_eq!(LookWalk::parse("body_s=0.9").unwrap().base(), DEFAULT);
    }
}
