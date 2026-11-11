//! The locomotion one-shots from the clip lab (clips 2, 2026-11-11; `docs/GAME_BRIEF.md`,
//! "Locomotion clips"): turning on the spot, setting off and jumping, in both control schemes.
//! `live.rs` decides when one plays and draws the body by it; `anim.rs` plays it as any
//! whole-body one-shot. A file without a take keeps what was there before for that move.
//! Starts and stops are not played: the authority starts a body at full speed and stops it where
//! it is, so a take that speeds up or slows down along its own track left the drawn body 0.6 to
//! 0.9 m behind the authority's (then catching up, sliding the feet), or would carry it 0.8 to
//! 1.6 m past its stop. The gait's mid-stance fade-in and its run-on to double support stay
//! (`anim.rs`).
//!
//! - **Turns.** Standing, when the legs would have to swivel more than [`TURN_ON`] to face where
//!   they should (the cursor, a standing body's own heading), the take for the nearest quarter or
//!   half turn plays and the drawn body turns along the take's own curve ([`ClipInfo::turned`]:
//!   `animate.py` took the turn out of the clip, so the clip steps and the body turns, and both
//!   end facing the new way in the neutral pose). Up to 45° can be left over: the upper body takes
//!   it (scheme "cursor") or the legs swivel it as before.
//! - **Jumps.** The rules' jump is a hop of `jump_dist` tiles at `jump_speed` (a person: 1.6 at
//!   3.6 a second, about 0.44 s, [`crate::jump::AIR_S`]) the way the body moves or faces. The take
//!   for that way plays, timed so its flight (the path's `hop`, else the longest time both feet
//!   are up) is the hop's, from just before take-off: standing, `jump_stand`; sideways (scheme
//!   "cursor"), `jump_left` or `jump_right`. A jump while moving along the legs keeps the
//!   procedural jump (`jump.rs`) over the gait: `jump_forward` lands into a 1.9 m/s walk, and at
//!   the rules' 3.6–5.7 m/s its landing slid 0.5–3 m/s, against 0.03–0.9 for the arc (a retake).
//!   So does a backward one (`jump_back` is a retake).
//!
//! `LIVING_GAME_TAKES=off` plays none of these, nor the directional loops (`gait.rs`): the client
//! as it was before them, for comparisons.

use crate::combat::Action;
use crate::gait::Gaits;
use std::f32::consts::PI;

/// Whether the clip lab's takes play (`LIVING_GAME_TAKES=off` turns them off).
pub fn enabled() -> bool {
    static ON: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ON.get_or_init(|| std::env::var("LIVING_GAME_TAKES").map_or(true, |v| v != "off" && v != "0"))
}

/// Standing, the legs turn by a take only when they would swivel more than this (radians).
pub const TURN_ON: f32 = 55.0 * PI / 180.0;
/// The turn takes by angle (degrees, the game's sense: -90 a quarter turn left).
const TURNS: [(&str, f32); 4] = [("turn_left_90", -90.0), ("turn_right_90", 90.0), ("turn_left_180", -180.0), ("turn_right_180", 180.0)];
/// Turns play this much faster than the take (its 90° takes 1.47 s, its 180° 2 s; the cursor's
/// upper body leads, so the legs may take their time, but not that long).
pub const TURN_RATE: f32 = 1.3;
/// The jump takes the clip lab's verdicts accepted: standing, left and right. `jump_forward`
/// (its landing) and `jump_back` (through the floor) are retakes.
const JUMP_STAND: &str = "jump_stand";
const JUMP_SIDES: [(&str, f32); 2] = [("jump_left", -90.0), ("jump_right", 90.0)];
/// A take's flight plays at most this much faster or slower than the take.
const RATE: (f32, f32) = (0.6, 1.6);
/// After landing, a jump plays this long (take seconds) before it fades out: standing, into the
/// idle; moving, into the gait stepping on under it from just before touchdown, since the takes
/// land into a walk or the neutral pose while the body goes on at its own speed (held for 0.3 s
/// after landing, a running jump's landing slid 4.2 m/s).
const LAND_S: f32 = 0.3;
const LAND_MOVING_S: f32 = -0.08;

/// A one-shot of this module playing on a drawn body: the take, when it started (display ms),
/// its rate, where in it it started and where its fade out begins (s), and the legs' facing when
/// it started (sim angle).
#[derive(Clone, Copy, Debug)]
pub struct Playing {
    pub clip: &'static str,
    pub start_ms: f64,
    pub rate: f32,
    pub from: f32,
    pub cut: Option<f32>,
    pub yaw0: f32,
    /// The gait steps on under it (a moving jump).
    pub gait: bool,
}

impl Playing {
    /// Take time now (s).
    pub fn t(&self, now_ms: f64) -> f32 {
        self.from + (((now_ms - self.start_ms) / 1000.0) as f32 * self.rate).max(0.0)
    }

    /// The one-shot `anim.rs` plays for it.
    pub fn action(&self) -> Action {
        Action { clip: self.clip, rate: self.rate, start_ms: self.start_ms, from: self.from, cut: self.cut, gait: self.gait, ..Default::default() }
    }
}

/// The turn take for turning the legs by `off` (radians, the game's sense), if the file has one
/// and the turn is past [`TURN_ON`]: the quarter turn up to 135°, the half turn beyond.
pub fn turn_for(g: &Gaits, off: f32) -> Option<&'static str> {
    if off.abs() <= TURN_ON {
        return None;
    }
    let want = if off.abs() < 135f32.to_radians() { 90.0 } else { 180.0 } * off.signum();
    TURNS.iter().find(|(_, d)| *d == want).map(|(c, _)| *c).filter(|c| g.info(c).is_some_and(|i| i.turn.is_some()))
}

/// How far a turn take playing has turned the legs (radians, the game's sense), and whether it
/// has ended.
pub fn turned(g: &Gaits, p: &Playing, now_ms: f64) -> (f32, bool) {
    let Some(info) = g.info(p.clip) else { return (0.0, true) };
    let len = info.seconds.max(1e-3);
    let t = p.t(now_ms);
    (info.turned(t / len), t >= len)
}

/// The jump take for a hop `rel` radians from where the legs face (the game's sense), standing or
/// moving, timed to the rules' hop: its rate, where in the take it starts (s) and where it starts
/// fading out (s). None: no take for it (the procedural jump plays).
pub fn jump_for(g: &Gaits, moving: bool, rel: f32) -> Option<(&'static str, f32, f32, f32)> {
    let deg = rel.to_degrees();
    let clip = if deg.abs() <= 50.0 {
        if moving {
            return None;
        }
        JUMP_STAND
    } else {
        JUMP_SIDES.iter().find(|(_, d)| (deg - d).abs() < 40.0).map(|(c, _)| *c)?
    };
    let info = g.info(clip)?;
    let len = info.seconds;
    // The take's own flight (both feet up), else its path's hop window.
    let (a, b) = info.flight().map(|(a, b)| (a * len, b * len)).filter(|(a, b)| b - a >= 0.15).or(info.hop)?;
    if b - a < 0.1 || len <= 0.0 {
        return None;
    }
    let rate = ((b - a) / crate::jump::AIR_S).clamp(RATE.0, RATE.1);
    // Take-off when the rules' hop starts (after the procedural jump's crouch).
    let from = (a - crate::jump::CROUCH_S * rate).max(0.0);
    let cut = (b + if moving { LAND_MOVING_S } else { LAND_S }).min(len);
    Some((clip, rate, from, cut))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn gaits() -> std::sync::Arc<Gaits> {
        std::sync::Arc::new(crate::gait::tests::with_takes())
    }

    #[test]
    fn turns_past_the_threshold_pick_the_nearest_take() {
        let g = gaits();
        assert_eq!(turn_for(&g, 40f32.to_radians()), None, "small looks turn the upper body");
        assert_eq!(turn_for(&g, 70f32.to_radians()), Some("turn_right_90"));
        assert_eq!(turn_for(&g, -100f32.to_radians()), Some("turn_left_90"));
        assert_eq!(turn_for(&g, -150f32.to_radians()), Some("turn_left_180"));
        // The body turns along the take's curve and ends at its turn.
        let p = Playing { clip: "turn_right_90", start_ms: 0.0, rate: 1.0, from: 0.0, cut: None, yaw0: 0.0, gait: false };
        let (half, done) = turned(&g, &p, 500.0);
        assert!(!done && half > 0.0 && half < PI / 2.0, "part-way: {half}");
        let (end, done) = turned(&g, &p, 2000.0);
        assert!(done && (end - PI / 2.0).abs() < 1e-3);
    }

    #[test]
    fn a_jump_takes_off_with_the_rules_hop_and_lasts_as_long() {
        let g = gaits();
        let (clip, rate, from, cut) = jump_for(&g, false, 0.1).unwrap();
        assert_eq!(clip, "jump_stand");
        // Its flight (both feet up 0.37–0.65 of 1.7 s, 0.48 s) is brought to the rules' 0.44 s
        // hop, from just before take-off; standing, it lands and settles before fading.
        let flight = (0.65 - 0.37) * 1.7;
        assert!((rate - flight / crate::jump::AIR_S).abs() < 0.02, "rate {rate}");
        assert!((from - (0.37 * 1.7 - crate::jump::CROUCH_S * rate)).abs() < 0.02 && (cut - (0.65 * 1.7 + 0.3)).abs() < 0.02, "{from} {cut}");
        assert_eq!(jump_for(&g, true, 0.0), None, "moving forward: the procedural jump");
        assert_eq!(jump_for(&g, true, 1.6).map(|j| j.0), Some("jump_right"));
        assert_eq!(jump_for(&g, true, PI), None, "no backward take: the procedural jump");
    }
}
