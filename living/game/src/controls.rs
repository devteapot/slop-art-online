//! Player input → the authority's player reducers.
//!
//! - WASD (Shift to run) moves relative to the camera through `human_move`. Only changes of
//!   intent are sent: the authority keeps steering until told otherwise, and rate-limits
//!   intent changes (`input_hz`/`input_burst` laws).
//! - Right click walks to a ground point through `human_act` with the `goto` skill.
//! - Enter opens proximity chat (`human_say`); only characters within earshot hear it.

use crate::camera::Cam;
use crate::net::Net;
use crate::world::Scene;
use bevy::prelude::*;
use living_bindings::*;

/// My character's displayed position (Bevy world space), for the camera and HUD.
#[derive(Resource, Default)]
pub struct Target(pub Option<Vec3>);

#[derive(Resource, Default)]
pub struct Input {
    /// Last intent sent: quantized direction (sim axes) and gait.
    sent: Option<(i32, i32, bool)>,
    pub chat_open: bool,
    pub chat: String,
    /// Where the last click-to-move was sent, and when (seconds), for the marker.
    pub goto: Option<(Vec3, f32)>,
    /// Scripted input (demo): a direction in sim axes and gait that overrides the keys.
    pub scripted: Option<(Vec2, bool)>,
    /// My own lines (authority ms, text): a speaker gets no percept of their own words.
    pub said: Vec<(u64, String)>,
    /// Whether a movement direction is held (the camera keeps the keys' frame meanwhile).
    pub moving: bool,
    /// Face the cursor: you move with WASD and look where the mouse points.
    pub mouse_look: bool,
    /// Where I look (sim direction), with mouse look on.
    pub look: Option<Vec2>,
    /// Scripted look direction (demo), overriding the mouse.
    pub scripted_look: Option<Vec2>,
    /// Scripted cursor (demo), as -1..1 screen offsets from the centre (+x right, +y down);
    /// with a demo running the real mouse never steers.
    pub scripted_cursor: Option<Vec2>,
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
    let Some(conn) = &net.conn else { return };
    if net.my_id.is_none() {
        return;
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
    let (qx, qy) = quantize(dir);
    let intent = (qx, qy, run && (qx, qy) != (0, 0));
    // Release of all keys sends one stop; idle frames send nothing.
    let changed = input.sent != Some(intent) && !(input.sent.is_none() && intent.0 == 0 && intent.1 == 0);
    if changed {
        input.sent = Some(intent);
        let r = conn.reducers.human_move_then(qx as f32 / 1000.0, qy as f32 / 1000.0, intent.2, net.on_reply("move"));
        net.report("move", r);
    }
    if mouse.just_pressed(MouseButton::Right) && !ui.pointer {
        if let Some(p) = cam.cursor_ground {
            let node = serde_json::json!({"do": {"skill": "goto", "target": {"at": [p.x, p.z]}}}).to_string();
            let r = conn.reducers.human_act_then(node, net.on_reply("goto"));
            net.report("goto", r);
            input.goto = Some((p, time.elapsed_secs()));
            // A held key resumes direct control on its next change.
            input.sent = None;
        }
    }
}

/// Send a chat line to whoever is in earshot. Returns whether it was sent.
pub fn say(net: &Net, text: &str) -> bool {
    let text = text.trim();
    let Some(conn) = net.conn.as_ref().filter(|_| !text.is_empty()) else { return false };
    let r = conn.reducers.human_say_then(text.to_string(), 0, net.on_reply("say"));
    let ok = r.is_ok();
    net.report("say", r);
    ok
}

/// An aim line from the player toward the cursor (the shape a skillshot would take) and the
/// click-to-move marker.
pub fn gizmos(mut g: Gizmos, cam: Res<Cam>, target: Res<Target>, input: Res<Input>, time: Res<Time>) {
    if let (Some(me), Some(c)) = (target.0, cam.cursor_ground) {
        let lift = Vec3::Y * 0.05;
        let to = me + (c - me).clamp_length_max(8.0);
        g.line(me + lift, to + lift, Color::srgba(1.0, 0.95, 0.6, 0.6));
        g.circle(Isometry3d::new(c + lift, Quat::from_rotation_x(std::f32::consts::FRAC_PI_2)), 0.3, Color::srgba(1.0, 1.0, 1.0, 0.7));
    }
    if let Some((p, t)) = input.goto {
        let age = time.elapsed_secs() - t;
        if age < 1.0 {
            g.circle(Isometry3d::new(p + Vec3::Y * 0.05, Quat::from_rotation_x(std::f32::consts::FRAC_PI_2)), 0.2 + age * 0.6, Color::srgba(0.4, 1.0, 0.5, 1.0 - age));
        }
    }
}
