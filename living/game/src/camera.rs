//! ARPG-style camera rig. No free orbit: it follows the player from a fixed angle, or with the
//! zoom-tilt preset one zoom axis eases pitch, distance and FOV together from a tactical high
//! view down toward the ground (Nesky, "50 Camera Mistakes" #14–16). Options from the camera
//! research (docs/GAME_BRIEF.md): conversation framing, an opt-in yaw that follows the heading
//! while the controls keep their frame, and a cursor lean with a deadzone.

use crate::controls::Input;
use crate::net::Net;
use crate::world::{Draw, Scene};
use bevy::input::mouse::AccumulatedMouseScroll;
use bevy::pbr::{DistanceFog, FogFalloff};
use bevy::prelude::*;
use living_bindings::*;

pub const SKY: Color = Color::srgb(0.62, 0.74, 0.86);

#[derive(Clone, Copy, PartialEq, Debug)]
pub struct View {
    /// Angle above the ground plane, degrees (90 = straight down).
    pub pitch: f32,
    /// Distance from the focus, tiles.
    pub distance: f32,
    /// Vertical field of view, degrees.
    pub fov: f32,
}

impl View {
    fn lerp(self, o: View, t: f32) -> View {
        View { pitch: self.pitch + (o.pitch - self.pitch) * t, distance: self.distance + (o.distance - self.distance) * t, fov: self.fov + (o.fov - self.fov) * t }
    }
}

#[derive(Clone, Copy, PartialEq, Debug)]
pub struct Rig {
    /// The view zoomed all the way out.
    pub far: View,
    /// With `tilt`, the view zoomed all the way in; zoom eases every parameter between them.
    /// Without it, zoom only scales the distance.
    pub near: View,
    pub tilt: bool,
    /// Rotation around the vertical, degrees (0 = north up).
    pub yaw: f32,
    pub ortho: bool,
    /// Most the view centre leans toward the cursor (tiles), past a deadzone.
    pub lead: f32,
    /// Q/E rotate in 45° steps.
    pub rotate_steps: bool,
    /// Ease the yaw toward the way the character walks (opt-in).
    pub follow_heading: bool,
    /// Come in and frame both speakers during a conversation.
    pub frame_talk: bool,
}

pub struct Preset {
    pub name: &'static str,
    pub like: &'static str,
    pub rig: Rig,
}

const fn view(pitch: f32, distance: f32, fov: f32) -> View {
    View { pitch, distance, fov }
}

const fn fixed(pitch: f32, distance: f32, fov: f32, lead: f32) -> Rig {
    Rig { far: view(pitch, distance, fov), near: view(pitch, distance, fov), tilt: false, yaw: 0.0, ortho: false, lead, rotate_steps: false, follow_heading: false, frame_talk: false }
}

pub const PRESETS: [Preset; 4] = [
    Preset { name: "ARPG", like: "Path of Exile, Diablo: north up, about 52° down, medium lens", rig: fixed(52.0, 24.0, 35.0, 3.0) },
    Preset { name: "MOBA north-up", like: "League of Legends: north up, about 56° down, narrow lens", rig: fixed(56.0, 32.0, 28.0, 2.0) },
    Preset { name: "Top-down action", like: "Supervive: high angle, wider lens, more pan toward the cursor", rig: fixed(64.0, 26.0, 40.0, 6.0) },
    Preset {
        name: "Zoom-tilt",
        like: "Baldur's Gate 3, Manor Lords, Diablo IV towns: scroll in to come down toward the ground; conversations frame both speakers",
        rig: Rig {
            far: view(60.0, 26.0, 35.0),
            near: view(24.0, 7.5, 52.0),
            tilt: true,
            yaw: 0.0,
            ortho: false,
            lead: 3.0,
            rotate_steps: true,
            follow_heading: false,
            frame_talk: true,
        },
    },
];

#[derive(Resource)]
pub struct Cam {
    pub preset: usize,
    pub rig: Rig,
    /// Zoom: 0 = all the way out, 1 = all the way in.
    pub zoom: f32,
    shown_zoom: f32,
    /// Yaw actually shown (eases toward `rig.yaw`).
    shown_yaw: f32,
    /// Yaw the movement keys are relative to; it lags a turning camera while keys are held.
    control_yaw: f32,
    focus: Vec3,
    /// How far into conversation framing the view is (0..1), and whether the player zoomed it away.
    talk: f32,
    talk_dismissed: Option<u32>,
    pub talk_partner: Option<u32>,
    pub cursor_ground: Option<Vec3>,
    pub shown: View,
}

impl Default for Cam {
    fn default() -> Self {
        let rig = PRESETS[0].rig;
        Self {
            preset: 0,
            rig,
            zoom: 0.0,
            shown_zoom: 0.0,
            shown_yaw: 0.0,
            control_yaw: 0.0,
            focus: Vec3::ZERO,
            talk: 0.0,
            talk_dismissed: None,
            talk_partner: None,
            cursor_ground: None,
            shown: rig.far,
        }
    }
}

fn axes(yaw_deg: f32) -> (Vec2, Vec2) {
    let y = yaw_deg.to_radians();
    // Yaw 0 looks north (−Z); positive yaw turns the view clockwise seen from above.
    (Vec2::new(y.sin(), -y.cos()), Vec2::new(y.cos(), y.sin()))
}

impl Cam {
    pub fn set_preset(&mut self, i: usize) {
        self.preset = i;
        self.rig = PRESETS[i].rig;
        self.zoom = if self.rig.tilt { 0.35 } else { 0.5 };
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
        DistanceFog { color: SKY, falloff: FogFalloff::Linear { start: 40.0, end: 90.0 }, ..default() },
    ));
}

/// Who I am talking with: the latest speaker I heard in the last 8 s within 8 tiles, else (while
/// typing) the nearest person within 6 tiles.
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

/// Place the camera, keep the projection, fog and draw distance in step with the rig.
#[allow(clippy::too_many_arguments)]
pub fn follow(
    mut cam: ResMut<Cam>,
    mut draw: ResMut<Draw>,
    keys: Res<ButtonInput<KeyCode>>,
    scroll: Res<AccumulatedMouseScroll>,
    target: Res<crate::controls::Target>,
    input: Res<Input>,
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    mut q: Query<(&mut Transform, &mut Projection, &Camera, &GlobalTransform, &mut DistanceFog), With<Camera3d>>,
    windows: Query<&Window>,
    ui: Res<crate::hud::UiWants>,
    time: Res<Time>,
) {
    let Ok((mut tf, mut proj, camera, gtf, mut fog)) = q.single_mut() else { return };
    let dt = time.delta_secs();
    let ease = |rate: f32| 1.0 - (-dt * rate).exp();
    if !ui.keyboard {
        for (i, k) in [KeyCode::Digit1, KeyCode::Digit2, KeyCode::Digit3, KeyCode::Digit4].iter().enumerate() {
            if keys.just_pressed(*k) {
                cam.set_preset(i);
            }
        }
        if cam.rig.rotate_steps {
            if keys.just_pressed(KeyCode::KeyQ) {
                cam.rig.yaw -= 45.0;
            }
            if keys.just_pressed(KeyCode::KeyE) {
                cam.rig.yaw += 45.0;
            }
        }
    }
    let partner = if cam.rig.frame_talk { talk_partner(&net, &scene, &input) } else { None };
    if partner != cam.talk_partner {
        cam.talk_partner = partner;
        if partner.is_none() {
            cam.talk_dismissed = None;
        }
    }
    if !ui.pointer && scroll.delta.y != 0.0 {
        cam.zoom = (cam.zoom + scroll.delta.y * 0.06).clamp(0.0, 1.0);
        // A manual zoom during a conversation overrides the framing until it ends.
        if partner.is_some() {
            cam.talk_dismissed = partner;
        }
    }
    let framing = partner.is_some() && cam.talk_dismissed != partner;
    cam.talk += ((framing as u8 as f32) - cam.talk) * ease(3.0);
    cam.shown_zoom += (cam.zoom - cam.shown_zoom) * ease(8.0);

    // Opt-in: ease the yaw toward the way I walk (deadband ±20°, at most 35°/s).
    if cam.rig.follow_heading && input.moving {
        if let Some(h) = net.my_id.and_then(|id| scene.shown.get(&id)).and_then(|(_, h)| *h) {
            let want = h.to_degrees() + 90.0;
            let diff = (want - cam.rig.yaw + 540.0).rem_euclid(360.0) - 180.0;
            if diff.abs() > 20.0 {
                cam.rig.yaw += diff.signum() * (35.0 * dt).min(diff.abs() - 20.0);
            }
        }
    }
    let k = ease(10.0);
    cam.shown_yaw += (cam.rig.yaw - cam.shown_yaw) * k;
    // The movement keys keep their frame while held and catch up over about half a second
    // (Haigh-Hutchinson: never change the control reference instantly).
    cam.control_yaw = if input.moving { cam.control_yaw + (cam.shown_yaw - cam.control_yaw) * ease(2.0) } else { cam.shown_yaw };

    // Where the cursor meets the ground, from the current camera.
    let window = windows.single().ok();
    let cursor = window.and_then(|w| w.cursor_position().map(|c| (c, Vec2::new(w.width(), w.height()))));
    cam.cursor_ground = cursor.and_then(|(c, _)| {
        let ray = camera.viewport_to_world(gtf, c).ok()?;
        scene.ray_ground(ray.origin, *ray.direction)
    });

    let r = cam.rig;
    let base = if r.tilt { r.far.lerp(r.near, cam.shown_zoom) } else { View { distance: r.far.distance * (1.5 - cam.shown_zoom), ..r.far } };
    let talk_view = View { pitch: 38.0, distance: 8.0, fov: 45.0 };
    let v = base.lerp(talk_view, cam.talk * if r.tilt { 1.0 } else { 0.6 });
    cam.shown = v;

    if let Some(me) = target.0 {
        // Cursor lean: nothing inside 30% of the half-screen, full lean at 80%.
        let (up, right) = axes(cam.shown_yaw);
        let lean = cursor.map_or(Vec3::ZERO, |(c, size)| {
            let n = (c - size / 2.0) / (size / 2.0);
            let len = n.length();
            let s = ((len - 0.3) / 0.5).clamp(0.0, 1.0);
            let s = s * s * (3.0 - 2.0 * s);
            let dir = (right * n.x - up * n.y).normalize_or_zero();
            Vec3::new(dir.x, 0.0, dir.y) * s * r.lead * (1.0 - cam.talk)
        });
        // Head height comes into play as the view lowers, so the horizon shows.
        let lift = Vec3::Y * (1.0 - (v.pitch - 20.0) / 45.0).clamp(0.0, 1.0) * 1.1;
        let mut want = me + lean + lift;
        if let Some(p) = cam.talk_partner.and_then(|id| scene.shown.get(&id)).map(|(p, _)| scene.at3(p.x, p.y)) {
            want = want.lerp((me + p) * 0.5 + Vec3::Y * 1.0, cam.talk);
        }
        let snap = cam.focus.distance(want) > 30.0;
        cam.focus = if snap { want } else { cam.focus + (want - cam.focus) * ease(8.0) };
    }
    let pitch = v.pitch.to_radians();
    let (up, _) = axes(cam.shown_yaw);
    let back = Vec3::new(-up.x, 0.0, -up.y) * pitch.cos() * v.distance;
    let mut eye = cam.focus + back + Vec3::Y * pitch.sin() * v.distance;
    // Never under a hill.
    eye.y = eye.y.max(scene.ground(eye.x, eye.z) + 0.8);
    tf.translation = eye;
    tf.look_at(cam.focus, Vec3::Y);

    // Lower views see further: draw terrain out toward the horizon and fade it into the sky.
    let low = (1.0 - (v.pitch - 25.0) / 35.0).clamp(0.0, 1.0);
    draw.radius = 56.0 + 64.0 * low;
    fog.falloff = FogFalloff::Linear { start: draw.radius * 0.5, end: draw.radius * 0.95 };
    match (&mut *proj, r.ortho) {
        (Projection::Perspective(p), false) => p.fov = v.fov.to_radians(),
        (Projection::Orthographic(o), true) => {
            o.scaling_mode = bevy::camera::ScalingMode::FixedVertical { viewport_height: v.distance * 0.9 };
        }
        (_, false) => *proj = Projection::from(PerspectiveProjection { fov: v.fov.to_radians(), ..default() }),
        (_, true) => {
            *proj = Projection::from(OrthographicProjection {
                scaling_mode: bevy::camera::ScalingMode::FixedVertical { viewport_height: v.distance * 0.9 },
                ..OrthographicProjection::default_3d()
            })
        }
    }
}
