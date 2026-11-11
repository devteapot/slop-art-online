//! Player input → the authority's player reducers.
//!
//! - WASD (Shift to run) moves relative to the camera through `human_move`. Only changes of
//!   intent are sent: the authority keeps steering until told otherwise, and rate-limits
//!   intent changes (`input_hz`/`input_burst` laws).
//! - The mouse buttons and Q/E/R/Shift are the skill bar (`combat.rs`); scripts can still walk
//!   to a point with `goto`.
//! - Enter opens proximity chat (`human_say`); only characters within earshot hear it. It is
//!   addressed to the person pointed at, or the nearest within earshot (`talk.rs`).

use crate::camera::Cam;
use crate::net::Net;
use crate::world::Scene;
use bevy::prelude::*;
use living_bindings::*;

/// My character's displayed position (Bevy world space), for the camera and HUD.
#[derive(Resource, Default)]
pub struct Target(pub Option<Vec3>);

/// An intent no key gives: set as the last one sent, it makes the next frame send what the keys
/// hold, a stop included.
const RESEND: (i32, i32, bool) = (i32::MIN, i32::MIN, false);
/// After a refused move (the authority's input bucket is empty, `input_hz`), wait this long (s)
/// before sending the held intent again: about one token at 30 Hz.
const RETRY_S: f64 = 0.04;

#[derive(Resource, Default)]
pub struct Input {
    /// Last intent sent: quantized direction (sim axes) and gait.
    sent: Option<(i32, i32, bool)>,
    /// Movement intents sent, and the latest of them the authority refused (set from the
    /// reply, which `frame_tick` runs): a refused intent is sent again.
    sends: u64,
    refused: std::sync::Arc<std::sync::atomic::AtomicU64>,
    retry_at: Option<f64>,
    /// The character the last intent was sent for: a new one (a rejoin, a reconnect) starts
    /// from what the keys hold, since the authority may still be steering the old intent.
    sent_for: Option<u32>,
    pub chat_open: bool,
    pub chat: String,
    /// Where the last click-to-move was sent, and when (seconds), for the marker.
    pub goto: Option<(Vec3, f32)>,
    /// Scripted input (demo): a direction in sim axes and gait that overrides the keys.
    pub scripted: Option<(Vec2, bool)>,
    /// My own lines (authority ms, text): a speaker gets no percept of their own words.
    pub said: Vec<(u64, String)>,
    /// The text box collects words for an act instead of speech (`verbs.rs`): its label
    /// ("write tablet"), and the words once entered.
    pub compose: Option<String>,
    pub composed: Option<String>,
    /// When the last movement intent was sent (input → drawn, `bodies.rs`).
    pub moved_at: Option<std::time::Instant>,
    /// Whether a movement direction is held (the camera keeps the keys' frame meanwhile).
    pub moving: bool,
    /// When a direction was last held (`Time` seconds), so my body is carried on a moment
    /// after the keys are let go (`bodies.rs`).
    pub held_s: f64,
    /// The direction held (sim axes, unit or zero): a dodge goes this way.
    pub dir: Vec2,
    /// Face the cursor: you move with WASD and look where the mouse points.
    pub mouse_look: bool,
    /// Where I look (sim direction), with mouse look on.
    pub look: Option<Vec2>,
    /// Scripted look direction (demo), overriding the mouse.
    pub scripted_look: Option<Vec2>,
    /// Scripted cursor (demo), as -1..1 screen offsets from the centre (+x right, +y down);
    /// with a demo running the real mouse never steers.
    pub scripted_cursor: Option<Vec2>,
    /// Scripted manual rotation (demo), degrees per second.
    pub scripted_turn: Option<f32>,
    pub demo: bool,
}

impl Input {
    /// You face the cursor by default (mouse look); a demo scripts its own look and cursor.
    pub fn new(demo: bool) -> Self {
        Self { mouse_look: !demo, demo, ..Default::default() }
    }
}

pub fn target(net: NonSend<Net>, scene: NonSend<Scene>, mut target: ResMut<Target>) {
    target.0 = net.my_id.and_then(|id| scene.shown.get(&id)).map(|(p, _)| scene.at3(p.x, p.y));
}

/// Quantize to 16 directions so tiny camera eases don't resend.
fn quantize(d: Vec2) -> (i32, i32) {
    if d == Vec2::ZERO {
        return (0, 0);
    }
    let a = d.y.atan2(d.x);
    let step = std::f32::consts::TAU / 16.0;
    let q = (a / step).round() * step;
    ((q.cos() * 1000.0).round() as i32, (q.sin() * 1000.0).round() as i32)
}

pub fn movement(
    net: NonSend<Net>,
    cam: Res<Cam>,
    keys: Res<ButtonInput<KeyCode>>,
    mouse: Res<ButtonInput<MouseButton>>,
    mut input: ResMut<Input>,
    target: Res<Target>,
    ui: Res<crate::hud::UiWants>,
    time: Res<Time>,
) {
    if net.my_id != input.sent_for {
        input.sent_for = net.my_id;
        input.sent = Some(RESEND);
        input.retry_at = None;
    }
    let Some(conn) = &net.conn else { return };
    if net.my_id.is_none() {
        return;
    }
    let now = time.elapsed_secs_f64();
    // The latest intent was refused ("too many movement inputs"): send what is held again soon.
    if input.sends > 0 && input.refused.load(std::sync::atomic::Ordering::Relaxed) == input.sends && input.retry_at.is_none() {
        input.retry_at = Some(now + RETRY_S);
    }
    if input.retry_at.is_some_and(|t| now >= t) {
        input.retry_at = None;
        input.sent = Some(RESEND);
    }
    input.look = input.scripted_look.or_else(|| {
        let me = target.0?;
        let c = cam.cursor_ground?;
        input.mouse_look.then(|| Vec2::new(c.x - me.x, c.z - me.z)).filter(|d| d.length() > 0.3)
    });
    let (up, right) = cam.control_axes();
    let (dir, run) = if let Some((d, run)) = input.scripted {
        (d, run)
    } else if input.chat_open || ui.keyboard {
        (Vec2::ZERO, false)
    } else {
        let mut d = Vec2::ZERO;
        if keys.pressed(KeyCode::KeyW) {
            d += up;
        }
        if keys.pressed(KeyCode::KeyS) {
            d -= up;
        }
        if keys.pressed(KeyCode::KeyD) {
            d += right;
        }
        if keys.pressed(KeyCode::KeyA) {
            d -= right;
        }
        (d.normalize_or_zero(), keys.pressed(KeyCode::ShiftLeft) || keys.pressed(KeyCode::ShiftRight))
    };
    input.moving = dir != Vec2::ZERO;
    if input.moving {
        input.held_s = time.elapsed_secs_f64();
    }
    input.dir = dir;
    let (qx, qy) = quantize(dir);
    let intent = (qx, qy, run && (qx, qy) != (0, 0));
    // Release of all keys sends one stop; idle frames send nothing.
    let changed = input.sent != Some(intent) && !(input.sent.is_none() && intent.0 == 0 && intent.1 == 0);
    if changed && input.retry_at.is_none() {
        input.sent = Some(intent);
        input.sends += 1;
        let (seq, refused, report) = (input.sends, input.refused.clone(), net.on_reply("move"));
        let r = conn.reducers.human_move_then(qx as f32 / 1000.0, qy as f32 / 1000.0, intent.2, move |ctx, r| {
            if matches!(r, Ok(Err(_))) {
                refused.fetch_max(seq, std::sync::atomic::Ordering::Relaxed);
            }
            report(ctx, r);
        });
        net.report("move", r);
        input.moved_at = Some(std::time::Instant::now());
    }
    // A move the authority held back while I was rooted is re-sent by the authority itself
    // (`combat::resume_move`); RMB is the bow shot (combat.rs), so there is no click-to-move.
    let _ = (&mouse, &ui, &time);
}

/// Send a chat line to whoever is in earshot, addressed to `to` (0: no one in particular).
/// Returns whether it was sent.
pub fn say(net: &Net, text: &str, to: u32) -> bool {
    let text = text.trim();
    let Some(conn) = net.conn.as_ref().filter(|_| !text.is_empty()) else { return false };
    info!("say: \"{text}\" to {}", if to == 0 { "no one in particular".to_string() } else { format!("#{to}") });
    let r = conn.reducers.human_say_then(text.to_string(), to, net.on_reply("say"));
    let ok = r.is_ok();
    net.report("say", r);
    ok
}

/// The marker of a scripted walk to a point (aim indicators are `combat.rs`'s, shown only
/// while aiming).
pub fn gizmos(mut g: Gizmos, input: Res<Input>, time: Res<Time>) {
    if let Some((p, t)) = input.goto {
        let age = time.elapsed_secs() - t;
        if age < 1.0 {
            g.circle(Isometry3d::new(p + Vec3::Y * 0.05, Quat::from_rotation_x(std::f32::consts::FRAC_PI_2)), 0.2 + age * 0.6, Color::srgba(0.4, 1.0, 0.5, 1.0 - age));
        }
    }
}
