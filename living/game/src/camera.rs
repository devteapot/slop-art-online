//! North-up follow camera and the legacy orbit rig for comparison.

use crate::controls::Input;
use crate::net::Net;
use crate::world::{Draw, Scene};
use bevy::camera::CameraProjection;
use bevy::input::mouse::AccumulatedMouseMotion;
use bevy::pbr::{DistanceFog, FogFalloff};
use bevy::prelude::*;
use living_bindings::*;

pub const SKY: Color = Color::srgb(0.62, 0.74, 0.86);

#[derive(Clone, Copy, PartialEq, Debug, Default, serde::Serialize, serde::Deserialize)]
pub struct View {
    /// Angle above the ground plane, degrees (90 = straight down).
    pub pitch: f32,
    /// Orbit distance from focus, or vertical height in the top-down stops (metres).
    #[serde(rename = "height")]
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
    /// Frame conversations, greetings and fights ([`Context`]).
    pub frame: bool,
    pub sight_bound: bool,
}

impl Default for Rig {
    fn default() -> Self {
        Self {
            view: View { pitch: 28.0, distance: 22.0, fov: 50.0 },
            close: View { pitch: 24.0, distance: 7.5, fov: 52.0 },
            steer: false,
            steer_zone: 0.45,
            steer_rate: 90.0,
            rotate_rate: 90.0,
            lead: 2.5,
            frame: true,
            sight_bound: true,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mode {
    #[default]
    TopDown,
    Orbit,
}

impl Mode {
    pub fn name(self) -> &'static str {
        match self {
            Self::TopDown => "top-down",
            Self::Orbit => "orbit",
        }
    }
}

/// The north-up camera's persisted tuning. Distances in the stops are vertical heights.
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct Tuning {
    pub stops: [View; 3],
    pub wheel_step: f32,
    pub easing_rate: f32,
    pub fixed_pitch: Option<f32>,
    pub late_tilt: Option<LateTilt>,
    pub keep_fov_curve: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct LateTilt {
    pub tilt_start: f32,
    pub near_pitch: f32,
}

const MIDDLE: f32 = 0.55;
const CHEST_FRACTION: f32 = 0.60;

const fn stop(height: f32, pitch: f32, fov: f32) -> View {
    View { distance: height, pitch, fov }
}

fn smooth(t: f32) -> f32 {
    let t = t.clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

impl Default for Tuning {
    fn default() -> Self {
        Self::OURS_FIXED
    }
}

impl Tuning {
    const OURS: Self = Self {
        stops: [stop(19.0, 65.0, 46.0), stop(12.0, 58.0, 44.0), stop(8.0, 48.0, 42.0)],
        wheel_step: 0.05,
        easing_rate: 12.0,
        fixed_pitch: None,
        late_tilt: None,
        keep_fov_curve: false,
    };

    const OURS_FIXED: Self = Self {
        stops: [stop(19.0, 58.0, 46.0), stop(12.0, 58.0, 44.0), stop(8.0, 58.0, 42.0)],
        fixed_pitch: Some(58.0),
        keep_fov_curve: true,
        ..Self::OURS
    };

    // Exact play-test inputs from camera-ref, docs/CAMERA.md §6 (cd53b289).
    pub const PRESETS: [(&str, &str, Self); 5] = [
        ("Ours, fixed 58°", "ours-fixed", Self::OURS_FIXED),
        ("Ours (current)", "ours", Self::OURS),
        ("SUPERVIVE", "supervive", Self {
            stops: [stop(28.0, 59.0, 31.0), stop(23.0, 59.0, 31.0), stop(18.0, 59.0, 31.0)],
            fixed_pitch: Some(59.0),
            ..Self::OURS
        }),
        ("LoL", "lol", Self {
            stops: [stop(11.2, 56.0, 40.0), stop(11.2, 56.0, 40.0), stop(4.8, 56.0, 40.0)],
            fixed_pitch: Some(56.0),
            ..Self::OURS
        }),
        ("Corepunk", "corepunk", Self {
            stops: [stop(15.0, 60.0, 49.0), stop(12.0, 60.0, 49.0), stop(7.0, 54.0, 49.0)],
            ..Self::OURS
        }),
    ];

    pub fn preset(name: &str) -> Option<Self> {
        Self::PRESETS.iter().find(|(_, key, _)| *key == name).map(|(_, _, tuning)| *tuning)
    }

    pub fn view(&self, zoom: f32) -> View {
        let [wide, mid, tight] = self.stops;
        let (lo, hi, a, b) = if zoom <= MIDDLE {
            (0.0, MIDDLE, wide, mid)
        } else {
            (MIDDLE, 1.0, mid, tight)
        };
        let mut view = a.lerp(b, smooth((zoom - lo) / (hi - lo)));
        if let Some(pitch) = self.fixed_pitch {
            view.pitch = if let Some(tilt) = self.late_tilt {
                let start = tilt.tilt_start.clamp(0.0, 1.0);
                let blend = if zoom >= 1.0 { 1.0 } else { smooth((zoom - start) / (1.0 - start).max(f32::EPSILON)) };
                pitch + (tilt.near_pitch - pitch) * blend
            } else {
                pitch
            };
            if !self.keep_fov_curve {
                view.fov = mid.fov;
            }
        }
        view
    }
}

pub struct Zoom {
    target: f32,
    pub shown: f32,
}

impl Default for Zoom {
    fn default() -> Self {
        Self { target: MIDDLE, shown: MIDDLE }
    }
}

#[derive(Resource, Default)]
pub struct Cam {
    pub rig: Rig,
    pub mode: Mode,
    pub top_zoom: Zoom,
    pub eye_height: f32,
    pub ground_clearance: f32,
    pub pose: GlobalTransform,
    pub look_dir: Option<Vec2>,
    look_pointer: Option<Vec2>,
    /// Yaw shown (degrees, 0 = north up) and where it is going.
    pub shown_yaw: f32,
    yaw: f32,
    /// Yaw the movement keys are relative to; it lags a turning camera while keys are held.
    control_yaw: f32,
    focus: Vec3,
    /// What the view frames now, and a context the player dismissed by turning the view.
    pub context: Option<Context>,
    dismissed: Option<Context>,
    /// How long the current context has had no evidence (s).
    lapsed: f32,
    /// How far the view is framing (0–1), the framed view, and where the framed group's centre
    /// is from my focus (both eased, so a change of context never cuts).
    frame: f32,
    frame_view: View,
    frame_off: Vec3,
    /// My opponents now, and when each last exchanged a blow or a move with me (display ms).
    pub opponents: Vec<u32>,
    fought: std::collections::HashMap<u32, f64>,
    /// Whom I talk with or greet (the framed one), for the HUD.
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
    /// How far the eye is raised over rising ground behind it (m), eased ([`CLEARANCE`]).
    lift: f32,
    /// Zoom: a factor on the view's distance (pinch or wheel, `pointer.rs`), and the one shown.
    pub zoom: f32,
    zoom_shown: f32,
    /// How far out the eye is (a share of the view's distance) while a building would hold it.
    pull: f32,
}

/// The eye stays this far above the ground under it (m); it is lifted there smoothly, and
/// never closer than [`CLEARANCE_MIN`].
const CLEARANCE: f32 = 1.0;
const CLEARANCE_MIN: f32 = 0.3;
/// The eye keeps this far outside a building (m), comes in no closer than this share of its
/// distance, and goes back out at this rate (1/s).
const EYE_CLEAR: f32 = 0.6;
const PULL_MIN: f32 = 0.2;
const PULL_OUT: f32 = 3.0;
/// How fast the lift rises over a hill behind and settles again once past it (1/s).
const LIFT_UP: f32 = 10.0;
const LIFT_DOWN: f32 = 2.5;

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
        axes(if self.mode == Mode::TopDown { 0.0 } else { self.control_yaw })
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

/// What the view frames besides me.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Context {
    /// A fight I am in: me and [`Cam::opponents`].
    Fight,
    /// A conversation with someone.
    Talk(u32),
    /// A gesture exchange with someone: my greeting and its answer, or theirs at me.
    Greet(u32),
}

/// A fight lasts this long after the last blow or move between me and an opponent (ms).
pub const FIGHT_HOLD_MS: f64 = 4000.0;
/// Opponents further than this (m) are left out of the frame.
const FIGHT_REACH_M: f32 = 20.0;
/// Framing eases in and out at these rates (1/s): about 1.5 s in, 2.5 s out.
const FRAME_IN: f32 = 2.0;
const FRAME_OUT: f32 = 1.2;
/// A context outlasts its evidence by this (s), so a wave and its answer a moment later are one
/// framing, not two.
const CONTEXT_HOLD_S: f32 = 1.2;

/// My opponents: whoever's move under way is aimed at me, whom mine is aimed at, and anyone I
/// traded blows with (hit, missed, blocked, dodged) in the last [`FIGHT_HOLD_MS`]; alive, drawn
/// and within [`FIGHT_REACH_M`].
fn opponents(net: &Net, scene: &Scene, combat: &crate::combat::Combat, fought: &mut std::collections::HashMap<u32, f64>) -> Vec<u32> {
    use living_rules::combat::seen;
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else {
        fought.clear();
        return vec![];
    };
    let now = scene.now_ms;
    let mut saw = |id: u32, t: f64| {
        if id != 0 && id != me {
            let e = fought.entry(id).or_insert(t);
            *e = e.max(t);
        }
    };
    for e in &combat.recent {
        if matches!(e.row.kind, seen::HIT | seen::MISS | seen::BLOCKED | seen::DODGED | seen::RELEASE) {
            if e.row.actor == me {
                saw(e.row.target, e.seen_ms);
            } else if e.row.target == me {
                saw(e.row.actor, e.seen_ms);
            }
        }
    }
    for f in crate::net::fighters(conn).into_iter().filter(|f| f.act != 0 && (now as u64) < f.until_ms.max(f.release_ms) + 120) {
        if f.target == me {
            saw(f.id, now);
        } else if f.id == me {
            saw(f.target, now);
        }
    }
    let at = |id: u32| scene.shown.get(&id).map(|s| s.0);
    let mine = at(me);
    fought.retain(|id, t| now - *t < FIGHT_HOLD_MS && !combat.deaths.contains_key(id) && at(*id).zip(mine).is_some_and(|(p, m)| p.distance(m) < FIGHT_REACH_M));
    let mut ids: Vec<u32> = fought.keys().copied().collect();
    ids.sort_unstable();
    ids
}

/// Whom I am in a gesture exchange with: whom I just greeted, who answered me, or who greeted me,
/// latest first, within 12 m.
fn greet_partner(net: &Net, scene: &Scene, town: Option<&crate::town::Town>) -> Option<u32> {
    let (town, me) = (town?, net.my_id?);
    let (mine, _) = scene.shown.get(&me)?;
    let near = |id: u32| scene.shown.get(&id).is_some_and(|(p, _)| p.distance(*mine) < 12.0);
    town.answered.iter().chain(town.greeted_by.iter()).map(|(id, at)| (*id, *at)).chain(town.greeting).filter(|(id, _)| near(*id)).max_by(|a, b| a.1.total_cmp(&b.1)).map(|(id, _)| id)
}

/// Who I am talking with: the latest speaker I heard in the last 8 s within 8 m.
fn talk_partner(net: &Net, scene: &Scene, input: &Input) -> Option<u32> {
    let (conn, me) = (net.conn.as_ref()?, net.my_id?);
    let (mine, _) = scene.shown.get(&me)?;
    let near = |id: u32, r: f32| scene.shown.get(&id).is_some_and(|(p, _)| p.distance(*mine) < r);
    use spacetimedb_sdk::Table;
    let heard = conn
        .db
        .my_experience()
        .iter()
        .filter(|e| e.observer == me && e.kind == "speech" && scene.now_ms - (e.at_ms as f64) < 8_000.0 && near(e.subject, 8.0))
        .max_by_key(|e| e.at_ms)
        .map(|e| e.subject);
    // Opening the text box (or having just spoken) no longer frames the nearest person: the view
    // jumped in to 8 m whenever a player started typing (play-test 1). An answer does.
    let _ = input;
    heard
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
    mut q: Query<(&mut Transform, &mut Projection, &mut Camera, &GlobalTransform, &mut DistanceFog), With<Camera3d>>,
    windows: Query<&Window>,
    ui: Res<crate::hud::UiWants>,
    (town, combat, island, mut pointer, solids): (Option<Res<crate::town::Town>>, Option<Res<crate::combat::Combat>>, Option<Res<crate::island::Island>>, ResMut<crate::pointer::Pointer>, Query<(&Transform, &crate::lookdev::Fitted), (With<crate::envs::Solid>, Without<Camera3d>)>),
    (time, binds, prefs, live): (Res<Time>, Option<Res<crate::keys::Binds>>, Option<Res<crate::keys::Prefs>>, Option<Res<crate::live::Live>>),
) {
    let Ok((mut tf, mut proj, mut camera, gtf, mut fog)) = q.single_mut() else { return };
    let dt = time.delta_secs();
    let ease = |rate: f32| 1.0 - (-dt * rate).exp();
    let r = cam.rig;
    let s = size.0;
    let mode = if live.is_some() { prefs.as_ref().map_or(Mode::TopDown, |p| p.camera) } else { Mode::Orbit };
    if cam.mode != mode {
        cam.look_pointer = None;
        cam.align = None;
        cam.dismissed = None;
        cam.lift = 0.0;
    }
    cam.mode = mode;
    let top_down = mode == Mode::TopDown;
    let tuning = prefs.as_ref().map_or_else(Tuning::default, |p| p.camera_tuning);

    // Where the cursor meets the ground, from the current camera (the game's cursor: `pointer.rs`).
    let window = windows.single().ok();
    let screen_size = window.as_ref().map_or(crate::capture::size().as_vec2(), |w| Vec2::new(w.width(), w.height()));
    let cursor = pointer.pos.map(|c| (c, screen_size));

    // Turn by pointing: outside the middle zone of the screen the view turns toward the cursor's
    // side, faster further out; never while the cursor is below your character.
    let screen = window.as_ref().map(|w| Vec2::new(w.width(), w.height()));
    let steer_cursor = match (input.demo, input.scripted_cursor, screen) {
        (true, Some(n), Some(size)) => Some(((n + Vec2::ONE) * size / 2.0, size)),
        (true, _, _) => None,
        (false, _, _) => cursor,
    };
    let mut manual = 0.0;
    if !top_down {
        let mut turn = 0.0;
        if r.steer && !ui.over() && !input.chat_open {
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
        if !ui.over() && !input.demo && mouse.pressed(MouseButton::Middle) {
            manual += motion.delta.x * 0.3;
            cam.middle_moved += motion.delta.length();
        }
        // A left drag or a two-finger pan (`pointer.rs`), at the middle drag's rate.
        if !ui.over() && !input.demo {
            manual += pointer.turn_px * 0.3;
        }
        if pointer.align {
            cam.align_request = true;
        }
        // Zoom by pinch or wheel, within a band round the view's own distance.
        if cam.zoom == 0.0 {
            cam.zoom = 1.0;
            cam.zoom_shown = 1.0;
        }
        cam.zoom = (cam.zoom * pointer.zoom).clamp(crate::pointer::ZOOM_MIN, crate::pointer::ZOOM_MAX);
        cam.zoom_shown += (cam.zoom - cam.zoom_shown) * ease(12.0);
        // Align on request: a middle-button tap (released having moved under 6 px). R is a skill key.
        let tapped = mouse.just_released(MouseButton::Middle) && cam.middle_moved < 6.0 && !ui.over();
        if tapped || std::mem::take(&mut cam.align_request) {
            if let Some(l) = input.facing().filter(|l| l.length_squared() > 1e-4) {
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
        let holding = !ui.over() && binds.as_ref().is_some_and(|b| b.pressed(crate::keys::Act::Glance, &keys));
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

    } else {
        cam.shown_yaw = 0.0;
        cam.align_request = false;
        cam.top_zoom.target = (cam.top_zoom.target + tuning.wheel_step * pointer.wheel_notches + 1.0 - pointer.pinch_factor).clamp(0.0, 1.0);
        cam.top_zoom.shown += (cam.top_zoom.target - cam.top_zoom.shown) * ease(tuning.easing_rate);
    }

    // Context: a fight I am in, else a conversation, else a gesture exchange. Turning the view
    // dismisses it until that context ends.
    let mut fought = std::mem::take(&mut cam.fought);
    cam.opponents = match combat.as_deref() {
        Some(c) if r.frame => opponents(&net, &scene, c, &mut fought),
        _ => vec![],
    };
    cam.fought = fought;
    let context = if !r.frame {
        None
    } else if !cam.opponents.is_empty() {
        Some(Context::Fight)
    } else if let Some(id) = talk_partner(&net, &scene, &input) {
        Some(Context::Talk(id))
    } else {
        greet_partner(&net, &scene, town.as_deref()).map(Context::Greet)
    };
    // A context with no evidence lasts a moment longer (unless another takes its place).
    cam.lapsed = if context.is_none() && cam.context.is_some() { cam.lapsed + dt } else { 0.0 };
    let context = if context.is_none() && cam.lapsed < CONTEXT_HOLD_S { cam.context } else { context };
    if context != cam.context {
        debug!("camera: context {:?} -> {:?} (opponents {:?})", cam.context, context, cam.opponents);
        cam.context = context;
        if context.is_none() || context != cam.dismissed {
            cam.dismissed = None;
        }
    }
    if manual != 0.0 && context.is_some() {
        cam.dismissed = context;
    }
    let framing = context.filter(|c| cam.dismissed != Some(*c));
    cam.talk_partner = match framing {
        Some(Context::Talk(id) | Context::Greet(id)) => Some(id),
        _ => None,
    };
    let v;
    if top_down {
        v = tuning.view(cam.top_zoom.shown);
        if let Some(me) = target.0 {
            let height = net.my_id.and_then(|id| live.as_ref()?.heights.get(&id).copied()).unwrap_or(1.75 * s);
            cam.focus = me + Vec3::Y * height * CHEST_FRACTION;
        }
        let back = v.distance / v.pitch.to_radians().tan();
        tf.translation = cam.focus + Vec3::new(0.0, v.distance, back);
    } else {
        // The view, brought in along the tilt toward the ground when sight is short.
        let mut orbit_view = r.view;
        orbit_view.distance *= cam.zoom_shown;
        if r.sight_bound {
            let allowed = (sight.radius * 2.0).max(r.close.distance);
            if allowed < r.view.distance {
                let t = ((r.view.distance - allowed) / (r.view.distance - r.close.distance).max(0.01)).clamp(0.0, 1.0);
                orbit_view = r.view.lerp(r.close, t);
            }
        }
        // Who is framed with me (sim positions), and the view that holds us.
        let me_at = net.my_id.and_then(|id| scene.shown.get(&id)).map(|s| s.0);
        let group: Vec<Vec2> = match framing {
            Some(Context::Fight) => cam.opponents.iter().filter_map(|id| scene.shown.get(id).map(|s| s.0)).collect(),
            Some(Context::Talk(id) | Context::Greet(id)) => scene.shown.get(&id).map(|s| s.0).into_iter().collect(),
            None => vec![],
        };
        // Framing needs someone drawn to frame with me.
        let to = (framing.is_some() && me_at.is_some() && !group.is_empty()) as u8 as f32;
        cam.frame += (to - cam.frame) * ease(if to > cam.frame { FRAME_IN } else { FRAME_OUT });
        if let (Some(m), false) = (me_at, group.is_empty()) {
            let all = || group.iter().copied().chain(std::iter::once(m));
            let (lo, hi) = all().fold((m, m), |(lo, hi), p| (lo.min(p), hi.max(p)));
            let centre = (lo + hi) * 0.5;
            let spread = all().map(|p| p.distance(centre)).fold(0.0, f32::max);
            let want = match framing {
                Some(Context::Fight) => View { pitch: 34.0, distance: (8.0 + 1.8 * spread).clamp(10.0, 18.0), fov: 50.0 },
                Some(Context::Greet(_)) => View { pitch: 32.0, distance: (7.5 + 0.9 * 2.0 * spread).clamp(9.0, 15.0), fov: 48.0 },
                _ => View { pitch: 36.0, distance: 8.0, fov: 45.0 },
            };
            // A new context starts from its own view; one under way eases toward the new spread.
            if cam.frame < 0.02 {
                cam.frame_view = want;
            } else {
                cam.frame_view = cam.frame_view.lerp(want, ease(2.5));
            }
            let off = Vec3::new(centre.x - m.x, 0.0, centre.y - m.y);
            cam.frame_off = if cam.frame < 0.02 { off } else { cam.frame_off + (off - cam.frame_off) * ease(3.0) };
        }
        // Framing only ever brings the view in (never further than sight allows).
        let base = orbit_view;
        let mut framed = base.lerp(cam.frame_view, cam.frame);
        framed.distance = framed.distance.min(base.distance);
        v = framed;

        if let Some(me) = target.0 {
            // Cursor lean: nothing inside 30% of the half-screen, full lean at 80%.
            let (up, right) = axes(cam.shown_yaw);
            let lean = cursor.filter(|_| !input.demo).map_or(Vec3::ZERO, |(c, size2)| {
                let n = (c - size2 / 2.0) / (size2 / 2.0);
                let k = ((n.length() - 0.3) / 0.5).clamp(0.0, 1.0);
                let dir = (right * n.x - up * n.y).normalize_or_zero();
                Vec3::new(dir.x, 0.0, dir.y) * k * k * (3.0 - 2.0 * k) * r.lead * s * (1.0 - cam.frame)
            });
            // Look at about chest height, toward the framed group's centre as far as framing goes
            // (at my height: the others stand within a few metres).
            let want = me + lean + Vec3::Y * 1.2 * s + cam.frame_off * cam.frame;
            let snap = cam.focus.distance(want) > 40.0;
            cam.focus = if snap { want } else { cam.focus + (want - cam.focus) * ease(8.0) };
        }
        let pitch = v.pitch.to_radians();
        let dist = v.distance * s.max(0.4);
        let (up, _) = axes(cam.shown_yaw);
        let back = Vec3::new(-up.x, 0.0, -up.y) * pitch.cos() * dist;
        let mut eye = cam.focus + back + Vec3::Y * pitch.sin() * dist;
        // Never inside a building: where the eye would be within one, it comes in along its line to
        // the focus until it is clear of it (at once), and goes back out eased. A building merely in
        // the way fades instead (`envs::cutaway`), so the distance doesn't change for it.
        let mut pull = 1.0f32;
        let reach = (eye - cam.focus).length().max(0.1);
        for (t, f) in &solids {
            if f.size.x <= 0.0 || t.translation.xz().distance(eye.xz()) > reach + 40.0 {
                continue;
            }
            let (centre, half, rot) = crate::envs::fitted_box(t, f);
            let inv = rot.inverse();
            let pad = Vec3::splat(EYE_CLEAR);
            if let Some((enter, exit)) = crate::envs::segment_box(inv * (cam.focus - centre), inv * (eye - centre), half + pad) {
                if enter > 0.05 && enter < 1.0 && exit >= 1.0 {
                    pull = pull.min((enter - 0.02).max(PULL_MIN));
                }
            }
        }
        cam.pull = if pull < cam.pull || cam.pull == 0.0 { pull } else { cam.pull + (pull - cam.pull) * ease(PULL_OUT) };
        eye = cam.focus + (eye - cam.focus) * cam.pull;
        tf.translation = eye;
    }
    let mut eye = tf.translation;
    // Above the ground behind: the island's on a land world, else the tiles'. Rising ground lifts
    // the eye smoothly and the view re-aims at the focus, rather than the eye popping up a hill
    // after it was aimed (and the view tilting off me).
    let ground = island.as_ref().map_or_else(|| scene.ground(eye.x, eye.z), |i| i.height(eye.x, eye.z));
    let want = (ground + CLEARANCE - eye.y).max(0.0);
    cam.lift += (want - cam.lift) * ease(if want > cam.lift { LIFT_UP } else { LIFT_DOWN });
    eye.y = (eye.y + cam.lift).max(ground + CLEARANCE_MIN);
    tf.translation = eye;
    let focus_point = cam.focus;
    tf.look_at(focus_point, Vec3::Y);
    cam.pose = GlobalTransform::from(*tf);
    cam.eye_height = eye.y - focus_point.y;
    cam.ground_clearance = eye.y - ground;
    cam.shown = View { pitch: (-tf.forward().y).asin().to_degrees(), ..v };
    if let Projection::Perspective(p) = &mut *proj {
        p.fov = v.fov.to_radians();
        if let Some(size) = camera.logical_viewport_size() {
            p.aspect_ratio = size.x / size.y;
        }
        camera.computed.clip_from_view = p.get_clip_from_view();
    }

    // While aligning, keep the cursor on the same ground point, so your facing doesn't change and
    // the align ends with that point straight ahead (a cursor fixed on the screen would keep the
    // view turning after your facing). A turn or a zoom by hand (a pan, a drag, `[` `]`, a pinch,
    // the wheel) leaves the cursor at its screen position, and what it points at follows the view.
    let place = |p: Vec3| camera.world_to_viewport(&GlobalTransform::from(*tf), p).ok().filter(|s| s.x >= 0.0 && s.y >= 0.0 && s.x < screen_size.x && s.y < screen_size.y);
    if let Some((want, lock)) = cam.align.filter(|_| !top_down) {
        if let Some(screen) = lock.and_then(place) {
            pointer.place = Some(screen);
        }
        if diff(want, cam.shown_yaw).abs() < 0.5 {
            cam.align = None;
        }
    }

    // Draw out toward the horizon and fade it into the sky: by the environment's mood where
    // there is one (the island's, Cullet's), else round the tile world's draw radius. The
    // atmosphere scales it after (`daylight::apply`: night and weather close it in), and the
    // sight edge's limited view fogs from my sight on top of it (`sightedge.rs`).
    draw.radius = 110.0 * s.max(0.7);
    let (start, end) = match draw.fog {
        Some((a, b)) => (a * s.max(0.7), b * s.max(0.7)),
        None => (draw.radius * 0.45, draw.radius * 0.95),
    };
    fog.falloff = FogFalloff::Linear { start, end };
}

/// Use the camera currently on screen for input, or the new camera for rendering the next frame.
pub fn cursor_hit(
    mut cam: ResMut<Cam>,
    pointer: Res<crate::pointer::Pointer>,
    q: Query<&Camera, With<Camera3d>>,
    target: Res<crate::controls::Target>,
    scene: NonSend<Scene>,
    island: Option<Res<crate::island::Island>>,
) {
    cam.cursor_ground = pointer.pos.and_then(|pos| {
        let ray = q.single().ok()?.viewport_to_world(&cam.pose, pos).ok()?;
        match island.as_deref() {
            Some(island) => crate::live::ray_ground(island, ray.origin, *ray.direction),
            None if scene.ready() => scene.ray_ground(ray.origin, *ray.direction),
            None => None,
        }
    });
    if cam.mode == Mode::Orbit || cam.look_pointer != pointer.pos || pointer.tapped || cam.cursor_ground.is_none() || cam.look_dir.is_none() {
        cam.look_dir = cam.cursor_ground.zip(target.0).map(|(hit, me)| (hit - me).xz()).filter(|d| d.length_squared() > 0.09);
        cam.look_pointer = pointer.pos;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn top_down_curve_hits_the_knots_and_clamps() {
        assert_eq!(Zoom::default().shown, 0.55);
        let tuning = Tuning::preset("ours").unwrap();
        for (z, knot) in [0.0, MIDDLE, 1.0].into_iter().zip(tuning.stops) {
            assert_eq!(tuning.view(z), knot);
        }
        assert_eq!(tuning.view(-1.0), tuning.view(0.0));
        assert_eq!(tuning.view(2.0), tuning.view(1.0));
        assert_eq!(tuning.view(0.275).distance, 15.5);
    }

    #[test]
    fn fixed_pitch_only_zooms_by_height() {
        let tuning = Tuning { fixed_pitch: Some(55.0), ..Tuning::OURS };
        for (z, stop) in [0.0, MIDDLE, 1.0].into_iter().zip(tuning.stops) {
            assert_eq!(tuning.view(z), View { pitch: 55.0, fov: 44.0, distance: stop.distance });
        }
        let saved = serde_json::to_string(&tuning).unwrap();
        assert_eq!(serde_json::from_str::<Tuning>(&saved).unwrap(), tuning);
    }


    #[test]
    fn play_default_holds_pitch_and_keeps_the_lens_curve() {
        let tuning = Tuning::default();
        for (z, expected_fov) in [0.0, MIDDLE, 1.0].into_iter().zip([46.0, 44.0, 42.0]) {
            assert_eq!(tuning.view(z).pitch, 58.0);
            assert_eq!(tuning.view(z).fov, expected_fov);
        }
    }

    #[test]
    fn late_tilt_stays_flat_until_its_start_then_eases_to_the_near_pitch() {
        let tuning = Tuning {
            late_tilt: Some(LateTilt { tilt_start: 0.8, near_pitch: 48.0 }),
            ..Tuning::default()
        };
        for zoom in [0.0, 0.55, 0.8] {
            assert_eq!(tuning.view(zoom).pitch, 58.0);
        }
        assert!((tuning.view(0.9).pitch - 53.0).abs() < 0.001);
        assert_eq!(tuning.view(1.0).pitch, 48.0);
    }

}
