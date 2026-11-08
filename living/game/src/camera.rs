//! ARPG-style camera rig: follows the player from a fixed angle (no free orbit), optional
//! rotation in 45° steps, scroll zoom within limits, and a slight lead toward the cursor.
//! Presets are starting points; every parameter can be tuned live (F1).

use bevy::input::mouse::AccumulatedMouseScroll;
use bevy::prelude::*;

#[derive(Clone, Copy, PartialEq, Debug)]
pub struct Rig {
    /// Angle above the ground plane, degrees (90 = straight down).
    pub pitch: f32,
    /// Rotation around the vertical, degrees (0 = north up).
    pub yaw: f32,
    /// Distance from the target (perspective), tiles.
    pub distance: f32,
    /// Vertical field of view, degrees (perspective).
    pub fov: f32,
    pub ortho: bool,
    /// Visible height of the view (orthographic), tiles.
    pub ortho_height: f32,
    /// Share of the way toward the cursor the view centre leans (0 = locked on the player).
    pub lead: f32,
    /// Whether Q/E rotate the view in 45° steps.
    pub rotate_steps: bool,
}

pub struct Preset {
    pub name: &'static str,
    pub like: &'static str,
    pub rig: Rig,
}

pub const PRESETS: [Preset; 4] = [
    Preset {
        name: "ARPG",
        like: "Path of Exile, Diablo: north up, about 52° down, medium lens",
        rig: Rig { pitch: 52.0, yaw: 0.0, distance: 24.0, fov: 35.0, ortho: false, ortho_height: 20.0, lead: 0.12, rotate_steps: false },
    },
    Preset {
        name: "MOBA north-up",
        like: "League of Legends: north up, about 56° down, narrow lens",
        rig: Rig { pitch: 56.0, yaw: 0.0, distance: 32.0, fov: 28.0, ortho: false, ortho_height: 20.0, lead: 0.08, rotate_steps: false },
    },
    Preset {
        name: "Top-down action",
        like: "Supervive: high angle, wider lens, more lead toward the cursor",
        rig: Rig { pitch: 64.0, yaw: 0.0, distance: 26.0, fov: 40.0, ortho: false, ortho_height: 20.0, lead: 0.2, rotate_steps: false },
    },
    Preset {
        name: "Isometric (ortho)",
        like: "classic isometric: orthographic, 45° yaw, rotate in 45° steps with Q/E",
        rig: Rig { pitch: 35.26, yaw: 45.0, distance: 60.0, fov: 35.0, ortho: true, ortho_height: 22.0, lead: 0.1, rotate_steps: true },
    },
];

#[derive(Resource)]
pub struct Cam {
    pub preset: usize,
    pub rig: Rig,
    /// Scroll zoom multiplier (0.5 = closer, 2 = further).
    pub zoom: f32,
    /// Yaw actually shown (eases toward `rig.yaw`).
    shown_yaw: f32,
    focus: Vec3,
    pub cursor_ground: Option<Vec3>,
}

impl Default for Cam {
    fn default() -> Self {
        let rig = PRESETS[0].rig;
        Self { preset: 0, rig, zoom: 1.0, shown_yaw: rig.yaw, focus: Vec3::ZERO, cursor_ground: None }
    }
}

impl Cam {
    pub fn set_preset(&mut self, i: usize) {
        self.preset = i;
        self.rig = PRESETS[i].rig;
        self.zoom = 1.0;
    }

    /// Ground-plane unit vectors for "screen up" and "screen right" at the shown yaw.
    pub fn ground_axes(&self) -> (Vec2, Vec2) {
        let y = self.shown_yaw.to_radians();
        // Yaw 0 looks north (−Z); positive yaw turns the view clockwise seen from above.
        let up = Vec2::new(y.sin(), -y.cos());
        let right = Vec2::new(y.cos(), y.sin());
        (up, right)
    }
}

pub fn spawn(mut commands: Commands) {
    commands.spawn((Camera3d::default(), Projection::from(PerspectiveProjection::default()), Transform::from_xyz(0.0, 20.0, 20.0)));
}

/// Place the camera behind the focus point and keep the projection in step with the rig.
pub fn follow(
    mut cam: ResMut<Cam>,
    keys: Res<ButtonInput<KeyCode>>,
    scroll: Res<AccumulatedMouseScroll>,
    target: Res<crate::controls::Target>,
    mut q: Query<(&mut Transform, &mut Projection, &Camera, &GlobalTransform), With<Camera3d>>,
    windows: Query<&Window>,
    ui: Res<crate::hud::UiWants>,
    time: Res<Time>,
) {
    let Ok((mut tf, mut proj, camera, gtf)) = q.single_mut() else { return };
    let dt = time.delta_secs();
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
    if !ui.pointer && scroll.delta.y != 0.0 {
        cam.zoom = (cam.zoom * (1.0 - scroll.delta.y * 0.08)).clamp(0.5, 2.0);
    }
    let k = 1.0 - (-dt * 10.0).exp();
    cam.shown_yaw += (cam.rig.yaw - cam.shown_yaw) * k;

    // Where the cursor meets the ground (y = 0), from the current camera.
    cam.cursor_ground = windows.single().ok().and_then(|w| w.cursor_position()).and_then(|c| {
        let ray = camera.viewport_to_world(gtf, c).ok()?;
        (ray.direction.y < -1e-4).then(|| {
            let t = -ray.origin.y / ray.direction.y;
            ray.origin + *ray.direction * t
        })
    });

    if let Some(me) = target.0 {
        let lead = cam.cursor_ground.map_or(Vec3::ZERO, |c| (c - me).clamp_length_max(12.0) * cam.rig.lead);
        let want = me + lead;
        let snap = cam.focus.distance(want) > 30.0;
        cam.focus = if snap { want } else { cam.focus + (want - cam.focus) * (1.0 - (-dt * 8.0).exp()) };
    }
    let r = cam.rig;
    let pitch = r.pitch.to_radians();
    let dist = if r.ortho { r.distance } else { r.distance * cam.zoom };
    let (up, _) = cam.ground_axes();
    // The camera sits "below" the focus on screen (opposite of screen up) and above it.
    let back = Vec3::new(-up.x, 0.0, -up.y) * pitch.cos() * dist;
    tf.translation = cam.focus + back + Vec3::Y * pitch.sin() * dist;
    tf.look_at(cam.focus, Vec3::Y);
    match (&mut *proj, r.ortho) {
        (Projection::Perspective(p), false) => p.fov = r.fov.to_radians(),
        (Projection::Orthographic(o), true) => {
            o.scaling_mode = bevy::camera::ScalingMode::FixedVertical { viewport_height: r.ortho_height * cam.zoom };
        }
        (_, false) => *proj = Projection::from(PerspectiveProjection { fov: r.fov.to_radians(), ..default() }),
        (_, true) => {
            *proj = Projection::from(OrthographicProjection {
                scaling_mode: bevy::camera::ScalingMode::FixedVertical { viewport_height: r.ortho_height * cam.zoom },
                ..OrthographicProjection::default_3d()
            })
        }
    }
}
