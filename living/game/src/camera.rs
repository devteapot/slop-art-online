//! The game camera (one camera for every character; docs/GAME_BRIEF.md):
//!
//! - **View:** mid-way between a tactical view and the ground, about 40° down and 16 m away for an
//!   ordinary adult, fixed (no zoom). Distance and focus height scale with the character's size.
//! - **Facing:** you face the cursor. The view only turns when you turn it (below); turning by
//!   pointing toward a screen side is an option, off by default.
//! - **Rotation:** hold `[` or `]`, or drag with the middle button; the view stays where you leave
//!   it. Alt + mouse glances around and springs back.
//! - **Align (on request only):** press `R` or tap the middle button, and the view turns until
//!   the direction you face is straight ahead. The mouse cursor moves with the ground meanwhile,
//!   so you keep facing the same spot (a fixed cursor would make the view keep turning).
//! - **Context:** conversations frame both speakers, until you rotate or the talk ends.
//! - **Sight bound:** the view never pulls back further than about 1.5 × the sight radius, so
//!   less sight (night) brings it in, along the same tilt toward the ground.

use crate::controls::Input;
use crate::net::Net;
use crate::world::{Draw, Scene};
use bevy::input::mouse::AccumulatedMouseMotion;
use bevy::pbr::{DistanceFog, FogFalloff};
use bevy::prelude::*;
use living_bindings::*;

pub const SKY: Color = Color::srgb(0.62, 0.74, 0.86);

#[derive(Clone, Copy, PartialEq, Debug, Default)]
pub struct View {
    /// Angle above the ground plane, degrees (90 = straight down).
    pub pitch: f32,
    /// Distance from the focus, metres (for an ordinary adult).
    pub distance: f32,
    /// Vertical field of view, degrees.
    pub fov: f32,
}

impl View {
    fn lerp(self, o: View, t: f32) -> View {
        View { pitch: self.pitch + (o.pitch - self.pitch) * t, distance: self.distance + (o.distance - self.distance) * t, fov: self.fov + (o.fov - self.fov) * t }
    }
}

/// Tunable camera parameters (F1).
#[derive(Clone, Copy, PartialEq, Debug)]
pub struct Rig {
    pub view: View,
    /// Where the view goes when it has to come in (sight bound): low and close.
    pub close: View,
    /// Turn the view while the cursor sits toward a side of the screen (off by default: the user
    /// found it unpleasant, 2026-11-08). Outside `steer_zone` of the half-screen it turns.
    pub steer: bool,
    pub steer_zone: f32,
    /// Fastest the view turns by pointing, and by `[` `]` (degrees per second).
    pub steer_rate: f32,
    pub rotate_rate: f32,
    /// Most the view centre leans toward the cursor (metres), past a deadzone.
    pub lead: f32,
    pub frame_talk: bool,
    pub sight_bound: bool,
}

impl Default for Rig {
    fn default() -> Self {
        Self {
            view: View { pitch: 40.0, distance: 16.0, fov: 44.0 },
            close: View { pitch: 24.0, distance: 7.5, fov: 52.0 },
            steer: false,
            steer_zone: 0.45,
            steer_rate: 90.0,
            rotate_rate: 90.0,
            lead: 2.5,
            frame_talk: true,
            sight_bound: true,
        }
    }
}

#[derive(Resource, Default)]
pub struct Cam {
    pub rig: Rig,
    /// Yaw shown (degrees, 0 = north up) and where it is going.
    pub shown_yaw: f32,
    yaw: f32,
    /// Yaw the movement keys are relative to; it lags a turning camera while keys are held.
    control_yaw: f32,
    focus: Vec3,
    talk: f32,
    talk_dismissed: Option<u32>,
    pub talk_partner: Option<u32>,
    pub cursor_ground: Option<Vec3>,
    pub shown: View,
    /// Temporary look-around offset while Alt is held; eases back after.
    pub glance: f32,
    pub scripted_glance: Option<f32>,
    /// Align in progress: the yaw to reach, and the ground point the cursor stays on.
    align: Option<(f32, Option<Vec3>)>,
    /// Middle-button movement since it was pressed (a tap aligns, a drag rotates).
    middle_moved: f32,
    /// Request an align (the demo; keys and the middle button set it too).
    pub align_request: bool,
}

fn axes(yaw_deg: f32) -> (Vec2, Vec2) {
    let y = yaw_deg.to_radians();
    // Yaw 0 looks north (−Z); positive yaw turns the view clockwise seen from above.
    (Vec2::new(y.sin(), -y.cos()), Vec2::new(y.cos(), y.sin()))
}

impl Cam {
    /// Turn the view to a yaw (degrees); it eases there.
    pub fn set_yaw(&mut self, yaw: f32) {
        self.yaw = yaw;
    }

    /// Ground-plane unit vectors for "screen up" and "screen right" of the movement keys.
    pub fn control_axes(&self) -> (Vec2, Vec2) {
        axes(self.control_yaw)
    }
}

pub fn spawn(mut commands: Commands) {
    commands.spawn((
        Camera3d::default(),
        Projection::from(PerspectiveProjection::default()),
        Transform::from_xyz(0.0, 20.0, 20.0),
        DistanceFog { color: SKY, falloff: FogFalloff::Linear { start: 60.0, end: 110.0 }, ..default() },
        // The finishing pass reads depth and normals; it needs single-sample prepasses, so
        // anti-aliasing is SMAA rather than MSAA.
        bevy::core_pipeline::prepass::DepthPrepass,
        bevy::core_pipeline::prepass::NormalPrepass,
        Msaa::Off,
        bevy::anti_alias::smaa::Smaa::default(),
        bevy::render::view::ColorGrading::default(),
        crate::post::Edges::default(),
    ));
}

/// Who I am talking with: the latest speaker I heard in the last 8 s within 8 m, else (while
/// typing) the nearest person within 6 m.
fn talk_partner(net: &Net, scene: &Scene, input: &Input) -> Option<u32> {
    let (conn, me) = (net.conn.as_ref()?, net.my_id?);
    let (mine, _) = scene.shown.get(&me)?;
    let near = |id: u32, r: f32| scene.shown.get(&id).is_some_and(|(p, _)| p.distance(*mine) < r);
    use spacetimedb_sdk::Table;
    let heard = conn
        .db
        .experience()
        .iter()
        .filter(|e| e.observer == me && e.kind == "speech" && scene.now_ms - (e.at_ms as f64) < 8_000.0 && near(e.subject, 8.0))
        .max_by_key(|e| e.at_ms)
        .map(|e| e.subject);
    let typing = (input.chat_open || input.said.last().is_some_and(|(t, _)| scene.now_ms - (*t as f64) < 6_000.0))
        .then(|| {
            conn.db
                .body()
                .iter()
                .filter(|b| b.id != me && b.kind == "person")
                .filter_map(|b| scene.shown.get(&b.id).map(|(p, _)| (b.id, p.distance(*mine))))
                .filter(|(_, d)| *d < 6.0)
                .min_by(|a, b| a.1.total_cmp(&b.1))
                .map(|(id, _)| id)
        })
        .flatten();
    heard.or(typing)
}

fn diff(want: f32, from: f32) -> f32 {
    (want - from + 540.0).rem_euclid(360.0) - 180.0
}

/// Place the camera; keep the projection, fog and draw distance in step.
#[allow(clippy::too_many_arguments)]
pub fn follow(
    mut cam: ResMut<Cam>,
    mut draw: ResMut<Draw>,
    keys: Res<ButtonInput<KeyCode>>,
    motion: Res<AccumulatedMouseMotion>,
    mouse: Res<ButtonInput<MouseButton>>,
    target: Res<crate::controls::Target>,
    input: Res<Input>,
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    sight: Res<crate::sight::Sight>,
    size: Res<crate::bodies::MySize>,
    mut q: Query<(&mut Transform, &mut Projection, &Camera, &GlobalTransform, &mut DistanceFog), With<Camera3d>>,
    mut windows: Query<&mut Window>,
    ui: Res<crate::hud::UiWants>,
    time: Res<Time>,
) {
    let Ok((mut tf, mut proj, camera, gtf, mut fog)) = q.single_mut() else { return };
    let dt = time.delta_secs();
    let ease = |rate: f32| 1.0 - (-dt * rate).exp();
    let r = cam.rig;
    let s = size.0;

    // Where the cursor meets the ground, from the current camera.
    let window = windows.single().ok();
    let cursor = window.as_ref().and_then(|w| w.cursor_position().map(|c| (c, Vec2::new(w.width(), w.height()))));
    cam.cursor_ground = cursor.and_then(|(c, _)| {
        let ray = camera.viewport_to_world(gtf, c).ok()?;
        scene.ray_ground(ray.origin, *ray.direction)
    });

    // Turn by pointing: outside the middle zone of the screen the view turns toward the cursor's
    // side, faster further out; never while the cursor is below your character.
    let screen = window.as_ref().map(|w| Vec2::new(w.width(), w.height()));
    let steer_cursor = match (input.demo, input.scripted_cursor, screen) {
        (true, Some(n), Some(size)) => Some(((n + Vec2::ONE) * size / 2.0, size)),
        (true, _, _) => None,
        (false, _, _) => cursor,
    };
    let mut turn = 0.0;
    if r.steer && !ui.pointer && !input.chat_open {
        if let (Some((c, size2)), Some(me)) = (steer_cursor, target.0) {
            let nx = (c.x - size2.x / 2.0) / (size2.x / 2.0);
            let me_y = camera.world_to_viewport(gtf, me).map(|p| p.y).unwrap_or(size2.y / 2.0);
            let behind = c.y > me_y + size2.y * 0.08;
            let over = ((nx.abs() - r.steer_zone) / (1.0 - r.steer_zone).max(0.05)).clamp(0.0, 1.0);
            if !behind {
                turn += nx.signum() * over * over * r.steer_rate * dt;
            }
        }
    }
    // Manual rotation, kept where you leave it: hold [ or ], or drag with the middle button.
    let mut manual = 0.0;
    if !ui.keyboard {
        if keys.pressed(KeyCode::BracketLeft) {
            manual -= r.rotate_rate * dt;
        }
        if keys.pressed(KeyCode::BracketRight) {
            manual += r.rotate_rate * dt;
        }
    }
    if mouse.just_pressed(MouseButton::Middle) {
        cam.middle_moved = 0.0;
    }
    if !ui.pointer && !input.demo && mouse.pressed(MouseButton::Middle) {
        manual += motion.delta.x * 0.3;
        cam.middle_moved += motion.delta.length();
    }
    // Align on request: R, or a middle-button tap (released having moved under 6 px).
    let tapped = mouse.just_released(MouseButton::Middle) && cam.middle_moved < 6.0 && !ui.pointer;
    let pressed_r = !ui.keyboard && !input.chat_open && keys.just_pressed(KeyCode::KeyR);
    if tapped || pressed_r || std::mem::take(&mut cam.align_request) {
        if let Some(l) = input.look.filter(|l| l.length_squared() > 1e-4) {
            let face = l.y.atan2(l.x).to_degrees() + 90.0;
            let lock = cam.cursor_ground.filter(|_| !input.demo);
            cam.align = Some((cam.yaw + diff(face, cam.yaw), lock));
        }
    }
    // A manual turn cancels an align in progress.
    if manual != 0.0 {
        cam.align = None;
    }
    if let Some((want, _)) = cam.align {
        let left = diff(want, cam.yaw);
        let step = left * ease(9.0);
        cam.yaw += if left.abs() < 0.3 { left } else { step };
    }
    if let Some(rate) = input.scripted_turn {
        manual += rate * dt;
    }
    cam.yaw += turn + manual;
    // Glance: hold Alt and move the mouse; let go and it eases back.
    let holding = !ui.pointer && (keys.pressed(KeyCode::AltLeft) || keys.pressed(KeyCode::AltRight));
    if let Some(g) = cam.scripted_glance {
        cam.glance += (g - cam.glance) * ease(6.0);
    } else if holding {
        cam.glance = (cam.glance + motion.delta.x * 0.3).clamp(-150.0, 150.0);
    } else {
        cam.glance -= cam.glance * ease(5.0);
    }
    let target_yaw = cam.yaw + cam.glance;
    let d = diff(target_yaw, cam.shown_yaw);
    cam.shown_yaw += d * ease(10.0);
    // The movement keys keep their frame while held and catch up over about half a second
    // (Haigh-Hutchinson: never change the control reference instantly).
    cam.control_yaw = if input.moving { cam.control_yaw + diff(cam.shown_yaw, cam.control_yaw) * ease(2.0) } else { cam.shown_yaw };

    // Conversations: frame both speakers; rotating dismisses the framing until the talk ends.
    let partner = if r.frame_talk { talk_partner(&net, &scene, &input) } else { None };
    if partner != cam.talk_partner {
        cam.talk_partner = partner;
        if partner.is_none() {
            cam.talk_dismissed = None;
        }
    }
    if manual != 0.0 && partner.is_some() {
        cam.talk_dismissed = partner;
    }
    let framing = partner.is_some() && cam.talk_dismissed != partner;
    cam.talk += ((framing as u8 as f32) - cam.talk) * ease(3.0);

    // The view, brought in along the tilt toward the ground when sight is short.
    let mut v = r.view;
    if r.sight_bound {
        let allowed = (sight.radius * 1.5).max(r.close.distance);
        if allowed < r.view.distance {
            let t = ((r.view.distance - allowed) / (r.view.distance - r.close.distance).max(0.01)).clamp(0.0, 1.0);
            v = r.view.lerp(r.close, t);
        }
    }
    let v = v.lerp(View { pitch: 36.0, distance: 8.0, fov: 45.0 }, cam.talk);
    cam.shown = v;

    if let Some(me) = target.0 {
        // Cursor lean: nothing inside 30% of the half-screen, full lean at 80%.
        let (up, right) = axes(cam.shown_yaw);
        let lean = cursor.filter(|_| !input.demo).map_or(Vec3::ZERO, |(c, size2)| {
            let n = (c - size2 / 2.0) / (size2 / 2.0);
            let k = ((n.length() - 0.3) / 0.5).clamp(0.0, 1.0);
            let dir = (right * n.x - up * n.y).normalize_or_zero();
            Vec3::new(dir.x, 0.0, dir.y) * k * k * (3.0 - 2.0 * k) * r.lead * s * (1.0 - cam.talk)
        });
        // Look at about chest height.
        let mut want = me + lean + Vec3::Y * 1.2 * s;
        if let Some(p) = cam.talk_partner.and_then(|id| scene.shown.get(&id)).map(|(p, _)| scene.at3(p.x, p.y)) {
            want = want.lerp((me + p) * 0.5 + Vec3::Y * 1.3, cam.talk);
        }
        let snap = cam.focus.distance(want) > 40.0;
        cam.focus = if snap { want } else { cam.focus + (want - cam.focus) * ease(8.0) };
    }
    let pitch = v.pitch.to_radians();
    let dist = v.distance * s.max(0.4);
    let (up, _) = axes(cam.shown_yaw);
    let back = Vec3::new(-up.x, 0.0, -up.y) * pitch.cos() * dist;
    let mut eye = cam.focus + back + Vec3::Y * pitch.sin() * dist;
    // Never under the ground.
    eye.y = eye.y.max(scene.ground(eye.x, eye.z) + 1.0);
    tf.translation = eye;
    tf.look_at(cam.focus, Vec3::Y);

    // While aligning, keep the cursor on the same ground point, so your facing doesn't change
    // and the turn ends with that point straight ahead.
    if let Some((want, lock)) = cam.align {
        if let (Some(p), Ok(mut w)) = (lock, windows.single_mut()) {
            if let Ok(screen) = camera.world_to_viewport(&GlobalTransform::from(*tf), p) {
                let size = Vec2::new(w.width(), w.height());
                if screen.x >= 0.0 && screen.y >= 0.0 && screen.x < size.x && screen.y < size.y {
                    w.set_cursor_position(Some(screen));
                }
            }
        }
        if diff(want, cam.shown_yaw).abs() < 0.5 {
            cam.align = None;
        }
    }

    // Draw out toward the horizon and fade it into the sky.
    draw.radius = 110.0 * s.max(0.7);
    fog.falloff = FogFalloff::Linear { start: draw.radius * 0.45, end: draw.radius * 0.95 };
    if let Projection::Perspective(p) = &mut *proj {
        p.fov = v.fov.to_radians();
    }
}
