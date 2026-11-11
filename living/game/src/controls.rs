//! Player input → the authority's player reducers.
//!
//! - WASD (Shift to run) moves relative to the camera through `human_move`. Only changes of
//!   intent are sent: the authority keeps steering until told otherwise, and rate-limits
//!   intent changes (`input_hz`/`input_burst` laws).
//! - The mouse buttons and Q/E/R/Shift are the skill bar (`combat.rs`); scripts can still walk
//!   to a point with `goto`.
//! - Enter opens proximity chat (`human_say`); only characters within earshot hear it. It is
//!   addressed to the person pointed at, or the nearest within earshot (`talk.rs`).
//! - F3 switches the control scheme ([`Control`]): facing the cursor while you walk, or facing
//!   where you walk and turning to the cursor only to aim, strike or guard.
//!   `LIVING_GAME_CONTROL=cursor|travel` sets the starting one. A short note names the key and
//!   the scheme on arrival (the first-time hints, `ui/tips.rs`) and at each switch.

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

/// How my character faces while it moves (F3, `LIVING_GAME_CONTROL`). Presentation and aim only:
/// the authority has no look (`human_move` carries a direction and a gait), so either way the
/// rules see the body's heading as its travel and each move's aim as the point it was sent with.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum Control {
    /// Facing the cursor: WASD moves and the body looks where the mouse points.
    Cursor,
    /// Facing where you walk; the body turns to the cursor while aiming, striking or guarding
    /// (the skill bar's held and aimed moves) and back to its travel after.
    #[default]
    Travel,
}

impl Control {
    pub fn from_env() -> Option<Self> {
        match std::env::var("LIVING_GAME_CONTROL").ok()?.trim() {
            "cursor" => Some(Self::Cursor),
            "travel" => Some(Self::Travel),
            other => {
                warn!("LIVING_GAME_CONTROL={other}: wants cursor or travel");
                None
            }
        }
    }

    pub fn next(self) -> Self {
        match self {
            Self::Cursor => Self::Travel,
            Self::Travel => Self::Cursor,
        }
    }

    /// The note naming the key and this scheme.
    pub fn hint(self) -> &'static str {
        match self {
            Self::Cursor => "F3: controls (facing the cursor)",
            Self::Travel => "F3: controls (facing where you walk)",
        }
    }
}

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
    /// Keep the words already in the box when it opens ("Introduce yourself" puts a line in).
    pub keep_words: bool,
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
    /// The control scheme (F3).
    pub control: Control,
    /// Where my character's upper body faces as drawn (sim direction; `live.rs`).
    pub face: Option<Vec2>,
    /// The scheme's note was shown on arrival.
    hinted: bool,
    /// What [`look`] sent to the authority, and its refusals.
    pub looks: LookSend,
}

/// The look's sends (`human_face`): the last look sent (`Some(None)`: released), when, and the
/// latest one the input bucket refused (retried as soon as it allows, as a move is).
#[derive(Default)]
pub struct LookSend {
    pub last: Option<Option<Vec2>>,
    pub at: f64,
    pub sends: u64,
    pub refused: std::sync::Arc<std::sync::atomic::AtomicU64>,
    /// A refusal other than the bucket's: not retried (the same look would be refused again).
    pub failed: std::sync::Arc<std::sync::atomic::AtomicU64>,
    retry_at: Option<f64>,
}

impl Input {
    /// You face the cursor by default (mouse look); a demo scripts its own look and cursor.
    pub fn new(demo: bool) -> Self {
        Self { mouse_look: !demo, demo, control: Control::from_env().unwrap_or_default(), ..Default::default() }
    }

    /// Whether my body faces the cursor now: always in [`Control::Cursor`]; in
    /// [`Control::Travel`] only while a move is aimed (`aiming`: a skill key held or a guard up;
    /// a move under way faces its own aim, `live.rs`).
    pub fn faces_cursor(&self, aiming: bool) -> bool {
        self.control == Control::Cursor || aiming
    }

    /// Where I face as the screen shows it: the cursor, or the body as drawn (the compass, the
    /// view's align, a dodge or jump with no direction held).
    pub fn facing(&self) -> Option<Vec2> {
        match self.control {
            Control::Cursor => self.look.or(self.face),
            Control::Travel => self.face.or(self.look),
        }
    }
}

/// F3 switches the control scheme. The note naming the key and the scheme shows on arrival on
/// the line of first-time hints (`ui/tips.rs`, with the edge of sight's and the talk hint), and
/// at each switch among the verbs' notes, as F2's does.
pub fn scheme(
    keys: Res<ButtonInput<KeyCode>>,
    mut input: ResMut<Input>,
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    loading: Option<Res<crate::loading::Loading>>,
    verbs: Option<ResMut<crate::verbs::Verbs>>,
    tips: Option<ResMut<crate::ui::tips::Tips>>,
    (time, prefs): (Res<Time>, Option<ResMut<crate::keys::Prefs>>),
) {
    let switched = keys.just_pressed(KeyCode::F3) && !input.chat_open;
    if switched {
        // Settings › Play shows the scheme; the settings file keeps it.
        if let Some(mut p) = prefs {
            p.control = input.control.next();
            p.dirty = true;
        }
    }
    if switched {
        input.control = input.control.next();
        info!("controls: {:?}", input.control);
    }
    let text = input.control.hint();
    let now = time.elapsed_secs_f64();
    if switched {
        input.hinted = true;
        if let Some(mut v) = verbs {
            info!("controls: note \"{text}\"");
            v.toasts.retain(|t| !t.text.starts_with("F3: "));
            v.toasts.push(crate::verbs::Toast { text: text.into(), ok: None, at: now });
        }
    } else if !input.hinted && net.my_id.is_some_and(|id| scene.shown.contains_key(&id)) && crate::loading::Loading::clear(loading.as_deref()) {
        if let Some(mut t) = tips {
            input.hinted = true;
            info!("controls: arrival note \"{text}\"");
            t.once(text, now);
        }
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
    combat: Option<Res<crate::combat::Combat>>,
) {
    if net.my_id != input.sent_for {
        input.sent_for = net.my_id;
        input.sent = Some(RESEND);
        input.retry_at = None;
        input.looks = LookSend::default();
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
    // My look, to the authority (`human_face`): facing the cursor, its direction, standing and
    // walking; facing where I walk, the cursor's only while a move is aimed (a skill key held,
    // a guard up), then released (the body faces its travel again).
    let aims = combat.as_deref().is_some_and(|c| c.aims);
    let dir = match input.control {
        Control::Cursor => input.look,
        Control::Travel if aims => input.look,
        Control::Travel => None,
    };
    // While moving, the look is released unless [`FACE_WHILE_MOVING`] (see there). It goes
    // before this frame's move, so a walk that starts reaches the authority after the release,
    // while the body still stands: a release then keeps the facing and the walk turns on its
    // eased curve, where a release mid-walk snaps the heading to the travel (a leg jump).
    let dir = dir.filter(|_| FACE_WHILE_MOVING || !input.moving);
    let mut looks = std::mem::take(&mut input.looks);
    look(&net, dir, &mut looks, now);
    input.looks = looks;
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

/// Where my character looks, toward the authority: the one place the client's look direction
/// goes (interface D, agreed 2026-11-11). The reducer is `human_face(dx, dy)` (dev-box's fov-1,
/// on main at d0918462): screen axes as `human_move` (+x east, +y south, any length), `(0, 0)`
/// releases the look. It turns `body.heading`, the one facing the authority's sight (`fov_on`)
/// and everyone else's see: standing, the body turns in place; walking, the walk bends toward
/// the look by at most the `look_walk_deg` law and holds there; a release while walking snaps
/// back to the travel. A look within `look_slack_deg` (10°) of the held one writes nothing and
/// spends no input token, so this sends on any change over [`LOOK_DEG`], at most every
/// [`LOOK_S`]; a look the input bucket refused ("too many movement inputs") goes again as soon
/// as it allows ([`RETRY_S`]), any other refusal is not retried. The field of view follows the
/// authority's heading on my motion row (`sightfield::my_heading`, by `steer::pose`), so it never
/// runs ahead of what the authority sees.
pub fn look(net: &Net, dir: Option<Vec2>, st: &mut LookSend, now: f64) {
    use std::sync::atomic::Ordering::Relaxed;
    let dir = dir.filter(|d| d.length_squared() > 1e-6).map(|d| d.normalize());
    let Some(conn) = net.conn.as_ref().filter(|_| net.my_id.is_some()) else { return };
    // The latest look was refused by the bucket: send what is wanted again soon.
    if st.sends > 0 && st.refused.load(Relaxed) == st.sends && st.retry_at.is_none() {
        st.retry_at = Some(now + RETRY_S);
        st.refused.store(0, Relaxed);
        st.last = None;
    }
    if st.retry_at.is_some_and(|t| now < t) {
        return;
    }
    st.retry_at = None;
    let same = match (st.last, dir) {
        (Some(None), None) => true,
        (Some(Some(a)), Some(b)) => a.dot(b) > LOOK_DEG.to_radians().cos(),
        _ => false,
    };
    if same || (now - st.at < LOOK_S && dir.is_some()) {
        return;
    }
    // Nothing was ever looked: no release to send.
    if st.last.is_none() && dir.is_none() && st.sends == 0 {
        st.last = Some(None);
        return;
    }
    st.last = Some(dir);
    st.at = now;
    st.sends += 1;
    let d = dir.unwrap_or(Vec2::ZERO);
    debug!("look: human_face({:.3}, {:.3})", d.x, d.y);
    let (seq, refused, failed, report) = (st.sends, st.refused.clone(), st.failed.clone(), net.on_reply("face"));
    let r = conn.reducers.human_face_then(d.x, d.y, move |ctx, r| {
        if let Ok(Err(e)) = &r {
            if e.contains("too many movement inputs") {
                refused.fetch_max(seq, Relaxed);
            } else {
                failed.fetch_max(seq, Relaxed);
            }
        }
        report(ctx, r);
    });
    net.report("face", r);
}

/// Whether a look is sent while a direction is held. Off until dev-box's look-2 is on main: on
/// main a look while walking bends the travel itself up to 30° toward it (`look_walk_deg`), so
/// the owner walked at 0.87× speed with a sideways drift (play-test 5). look-2 makes the velocity
/// follow the keys and turns only the facing; then this is the one line to change. Off, a look
/// is sent standing and released (`human_face(0, 0)`) as soon as a direction is held.
pub const FACE_WHILE_MOVING: bool = false;

/// A look is sent again when it turns this far (degrees; the authority's own slack is 10°)…
pub const LOOK_DEG: f32 = 4.0;
/// …and at most this often (s), except a release.
pub const LOOK_S: f64 = 0.1;

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
