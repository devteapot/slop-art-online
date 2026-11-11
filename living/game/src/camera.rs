//! The game camera (one camera for every character; docs/GAME_BRIEF.md):
//!
//! - **View:** about 28° down and 22 m away for an ordinary adult, with a 50° field of view, fixed
//!   (no zoom). Flatter and further than the first 40°/16 m, so the land ahead and rising ground
//!   show (user, 2026-11-09). Distance and focus height scale with the character's size.
//! - **Facing:** you face the cursor. The view only turns when you turn it (below); turning by
//!   pointing toward a screen side is an option, off by default.
//! - **Rotation:** hold `[` or `]`, or drag with the middle button; the view stays where you leave
//!   it. Alt + mouse glances around and springs back.
//! - **Align (on request only):** tap the middle button, and the view turns until
//!   the direction you face is straight ahead. The mouse cursor moves with the ground meanwhile,
//!   so you keep facing the same spot (a fixed cursor would make the view keep turning).
//! - **Context** ([`Context`]): the view eases in and frames you with whoever you are dealing
//!   with, without turning, and eases back out when it is over:
//!   - a fight you are in: you and your opponents (anyone whose blow or move was aimed at you, or
//!     yours at them, in the last [`FIGHT_HOLD_MS`]), closer the tighter the fight;
//!   - a conversation: both speakers, close;
//!   - a gesture exchange (`town.rs`: my wave or nod and the answer, or someone's at me): both of
//!     you, for a few seconds.
//!
//!   Turning the view yourself dismisses the framing until that context ends: your own camera
//!   input always wins. It eases in over about 1.5 s and out over about 2.5 s; there are no cuts.
//! - **Sight bound:** the view never pulls back further than about 2 × the sight radius, so
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

#[derive(Resource, Default)]
pub struct Cam {
    pub rig: Rig,
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
    /// The ground point the cursor stays on while the view is turned by hand, so where I face
    /// doesn't change with the view.
    turn_lock: Option<Vec3>,
}

/// The eye stays this far above the ground under it (m); it is lifted there smoothly, and
/// never closer than [`CLEARANCE_MIN`].
const CLEARANCE: f32 = 1.0;
const CLEARANCE_MIN: f32 = 0.3;
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

/// Who I am talking with: the latest speaker I heard in the last 8 s within 8 m, else (while
/// typing) the nearest person within 6 m.
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
    let typing = (input.chat_open || input.said.last().is_some_and(|(t, _)| scene.now_ms - (*t as f64) < 6_000.0))
        .then(|| {
            conn.db
                .seen_characters()
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
    windows: Query<&Window>,
    ui: Res<crate::hud::UiWants>,
    (town, combat, island, mut pointer): (Option<Res<crate::town::Town>>, Option<Res<crate::combat::Combat>>, Option<Res<crate::island::Island>>, ResMut<crate::pointer::Pointer>),
    time: Res<Time>,
) {
    let Ok((mut tf, mut proj, camera, gtf, mut fog)) = q.single_mut() else { return };
    let dt = time.delta_secs();
    let ease = |rate: f32| 1.0 - (-dt * rate).exp();
    let r = cam.rig;
    let s = size.0;

    // Where the cursor meets the ground, from the current camera (the game's cursor: `pointer.rs`).
    let window = windows.single().ok();
    let screen_size = window.as_ref().map_or(crate::capture::size().as_vec2(), |w| Vec2::new(w.width(), w.height()));
    let cursor = pointer.pos.map(|c| (c, screen_size));
    // Last frame's cursor ground point, on the island's own ground where there is one
    // (`live::ground_cursor` corrects the tile-ground ray below): what a turn keeps under the cursor.
    let last_ground = cam.cursor_ground;
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
    // A left drag or a two-finger pan (`pointer.rs`), at the middle drag's rate.
    if !ui.pointer && !input.demo {
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
    let tapped = mouse.just_released(MouseButton::Middle) && cam.middle_moved < 6.0 && !ui.pointer;
    if tapped || std::mem::take(&mut cam.align_request) {
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
    // The view, brought in along the tilt toward the ground when sight is short.
    let mut v = r.view;
    v.distance *= cam.zoom_shown;
    if r.sight_bound {
        let allowed = (sight.radius * 2.0).max(r.close.distance);
        if allowed < r.view.distance {
            let t = ((r.view.distance - allowed) / (r.view.distance - r.close.distance).max(0.01)).clamp(0.0, 1.0);
            v = r.view.lerp(r.close, t);
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
    let base = v;
    let mut v = base.lerp(cam.frame_view, cam.frame);
    v.distance = v.distance.min(base.distance);
    cam.shown = v;

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
    // Above the ground behind: the island's on a land world, else the tiles'. Rising ground lifts
    // the eye smoothly and the view re-aims at the focus, rather than the eye popping up a hill
    // after it was aimed (and the view tilting off me).
    let ground = island.as_ref().map_or_else(|| scene.ground(eye.x, eye.z), |i| i.height(eye.x, eye.z));
    let want = (ground + CLEARANCE - eye.y).max(0.0);
    cam.lift += (want - cam.lift) * ease(if want > cam.lift { LIFT_UP } else { LIFT_DOWN });
    eye.y = (eye.y + cam.lift).max(ground + CLEARANCE_MIN);
    tf.translation = eye;
    tf.look_at(cam.focus, Vec3::Y);

    // While aligning, or turning the view by hand, keep the cursor on the same ground point, so
    // your facing doesn't change (and an align ends with that point straight ahead).
    let place = |p: Vec3| camera.world_to_viewport(&GlobalTransform::from(*tf), p).ok().filter(|s| s.x >= 0.0 && s.y >= 0.0 && s.x < screen_size.x && s.y < screen_size.y);
    let zooming = (cam.zoom - cam.zoom_shown).abs() > 0.002;
    let turning = manual != 0.0 || d.abs() > 0.05 || zooming;
    if (manual != 0.0 || zooming) && cam.turn_lock.is_none() {
        cam.turn_lock = last_ground;
    } else if !turning {
        cam.turn_lock = None;
    }
    if let Some((want, lock)) = cam.align {
        if let Some(screen) = lock.and_then(place) {
            pointer.place = Some(screen);
        }
        if diff(want, cam.shown_yaw).abs() < 0.5 {
            cam.align = None;
        }
    } else if let Some(screen) = cam.turn_lock.and_then(place) {
        pointer.place = Some(screen);
    }

    // Draw out toward the horizon and fade it into the sky.
    draw.radius = 110.0 * s.max(0.7);
    fog.falloff = FogFalloff::Linear { start: draw.radius * 0.45, end: draw.radius * 0.95 };
    if let Projection::Perspective(p) = &mut *proj {
        p.fov = v.fov.to_radians();
    }
}
