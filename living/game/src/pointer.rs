//! The game's cursor and pointer gestures (play-test 1: the owner, on a laptop trackpad, could
//! not turn the view, and the cursor left the window).
//!
//! - **Capture.** A click in the window captures the cursor: the system cursor is locked and
//!   hidden, and the game draws its own, moved by the mouse's or trackpad's motion. Esc gives it
//!   back once nothing else is open (a list, the pack or know-how, the text box close first, by
//!   their own Esc), and so does the window losing focus. On macOS only `Locked` grabs
//!   (`Confined` is unsupported), and a locked cursor reports a frozen position, so the game's
//!   cursor is virtual: [`Pointer::pos`] is what every reader uses (the camera's ground ray,
//!   facing, the aim), and the UI's picking is fed from it while captured.
//! - **Turning the view without turning you.** Dragging with the left button (press and move,
//!   on a trackpad too), a two-finger pan, or the middle button turns the view; while it turns,
//!   the cursor stays on the ground point it was over (`camera.rs`), so where you face doesn't
//!   change. A left press that doesn't move is the strike: on release when it was a tap, or once
//!   held [`HOLD_S`] (aiming, as before). A tap therefore fires on release, a click's length
//!   later than a press would. A tap is marked ([`Pointer::tapped`]): on a peaceful person it
//!   talks instead of striking (`combat.rs`).
//! - **Zoom:** a pinch, or a notched mouse wheel, within a band round the current distance.
//! - **Align:** a two-finger double tap turns the view to where you face (the middle tap too).
//!
//! A trackpad pan arrives as `MouseWheel { unit: Pixel }` with touch phases; a notched wheel as
//! `Line` (winit, `hasPreciseScrollingDeltas`). The coast after a flick arrives as a second
//! `Started…Ended` right after the first `Ended`; it is left out ([`COAST_GAP_S`]).
//!
//! Headless runs have no window: a script places the cursor (`cursor:X,Y`) and pans or drags
//! through the same paths (`live.rs`).

use bevy::input::gestures::{DoubleTapGesture, PinchGesture};
use bevy::input::mouse::{AccumulatedMouseMotion, MouseButtonInput, MouseScrollUnit, MouseWheel};
use bevy::input::touch::TouchPhase;
use bevy::input::ButtonState;
use bevy::picking::pointer::{Location, PointerAction, PointerButton, PointerId, PointerInput};
use bevy::prelude::*;
use bevy::window::{CursorGrabMode, CursorOptions, PrimaryWindow, WindowFocused};

/// A left press moving this far (logical px) before it is released or held is a drag.
const DRAG_PX: f32 = 6.0;
/// A left press held this long without moving is the strike, held (aiming) as before.
const HOLD_S: f64 = 0.22;
/// A pan gesture starting within this of the last one's end is its coast (s).
const COAST_GAP_S: f64 = 0.05;
/// Pixels of pan per pixel of drag (a pan's deltas are physical pixels and quick).
const PAN_GAIN: f32 = 0.6;
/// The zoom band, as a factor of the view's distance, and a wheel notch's step.
pub const ZOOM_MIN: f32 = 0.6;
pub const ZOOM_MAX: f32 = 1.4;
const WHEEL_STEP: f32 = 0.08;

#[derive(Clone, Copy, PartialEq, Debug, Default)]
enum Left {
    #[default]
    Up,
    /// Pressed, not yet a tap, a hold or a drag: since when, how far it has moved.
    Pending { since: f64, moved: f32 },
    /// Held as the strike (the button shows pressed to the game).
    Held,
    /// Turning the view.
    Dragging,
    /// The click that captured the cursor: swallowed until it is let go.
    Swallowed,
}

#[derive(Resource, Default)]
pub struct Pointer {
    /// Where the cursor is (logical px in the window); the game's own while captured.
    pub pos: Option<Vec2>,
    pub captured: bool,
    /// The view turn asked for this frame (drag px, positive turns as a rightward drag).
    pub turn_px: f32,
    /// Zoom asked for this frame (a factor on the distance; 1 none).
    pub zoom: f32,
    /// A double tap: align the view to where I face.
    pub align: bool,
    /// The left button is turning the view now (the cursor is placed by the camera, not moved).
    pub dragging: bool,
    /// Where the camera wants the cursor (keeping it on a ground point while the view turns).
    pub place: Option<Vec2>,
    /// A script's cursor (fractions of the window) and pans and drags (headless).
    pub scripted: Option<Vec2>,
    pub scripted_turn: f32,
    pub scripted_zoom: f32,
    /// The left press this frame is a tap (released before it was held or dragged), not a hold.
    pub tapped: bool,
    /// A script's tap (headless), through the same path.
    pub scripted_tap: bool,
    left: Left,
    /// A tap's strike was pressed this frame; let go of it next frame.
    release_next: bool,
    /// The pan gesture under way, and when the last one ended (s).
    panning: bool,
    coasting: bool,
    pan_ended: f64,
}

pub struct PointerPlugin;

impl Plugin for PointerPlugin {
    fn build(&self, app: &mut App) {
        app.insert_resource(Pointer { zoom: 1.0, scripted_zoom: 1.0, ..default() })
            .add_systems(Startup, spawn_cursor)
            .add_systems(PreUpdate, update.after(bevy::input::InputSystems))
            .add_systems(PostUpdate, draw_cursor);
    }
}

#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn update(
    mut p: ResMut<Pointer>,
    mut windows: Query<(Entity, &mut Window, &mut CursorOptions), With<PrimaryWindow>>,
    motion: Res<AccumulatedMouseMotion>,
    mut buttons: ResMut<ButtonInput<MouseButton>>,
    keys: Res<ButtonInput<KeyCode>>,
    (mut raw, mut wheel, mut pinch, mut taps, mut focus): (MessageReader<MouseButtonInput>, MessageReader<MouseWheel>, MessageReader<PinchGesture>, MessageReader<DoubleTapGesture>, MessageReader<WindowFocused>),
    mut picks: MessageWriter<PointerInput>,
    settings: Option<ResMut<bevy::picking::input::PointerInputSettings>>,
    ui: Res<crate::hud::UiWants>,
    input: Res<crate::controls::Input>,
    time: Res<Time>,
) {
    let now = time.elapsed_secs_f64();
    p.turn_px = std::mem::take(&mut p.scripted_turn);
    p.zoom = std::mem::replace(&mut p.scripted_zoom, 1.0);
    p.align = false;
    p.tapped = false;
    if p.release_next {
        buttons.release(MouseButton::Left);
        p.release_next = false;
    }
    let window = windows.single_mut().ok();
    let Some((win_e, mut win, mut cursor)) = window else {
        // Headless: the script's cursor and taps, if any.
        p.pos = p.scripted.map(|f| f * crate::capture::size().as_vec2());
        if std::mem::take(&mut p.scripted_tap) {
            buttons.press(MouseButton::Left);
            p.release_next = true;
            p.tapped = true;
        }
        if let Some(at) = p.place.take() {
            let size = crate::capture::size().as_vec2();
            p.scripted = Some(at / size);
            p.pos = Some(at);
        }
        return;
    };
    let size = Vec2::new(win.width(), win.height());
    let lost = focus.read().any(|f| !f.focused);
    let mut capture = p.captured;
    if lost {
        capture = false;
    }
    // Esc: the text box, a list and the panels close first, by their own Esc; then the cursor goes.
    if keys.just_pressed(KeyCode::Escape) && !input.chat_open && !ui.menu && !ui.keyboard {
        capture = false;
    }
    // The left button: a tap, a hold or a drag (lists and panels take clicks as they are).
    let free = !ui.pointer && !ui.menu;
    for e in raw.read() {
        let pick_button = match e.button {
            MouseButton::Left => Some(PointerButton::Primary),
            MouseButton::Right => Some(PointerButton::Secondary),
            MouseButton::Middle => Some(PointerButton::Middle),
            _ => None,
        };
        if p.captured {
            if let (Some(b), Some(pos)) = (pick_button, p.pos) {
                let action = if e.state == ButtonState::Pressed { PointerAction::Press(b) } else { PointerAction::Release(b) };
                if let Some(target) = bevy::camera::RenderTarget::Window(bevy::window::WindowRef::Entity(win_e)).normalize(Some(win_e)) {
                    picks.write(PointerInput::new(PointerId::Mouse, Location { target, position: pos }, action));
                }
            }
        }
        if e.button != MouseButton::Left {
            continue;
        }
        match e.state {
            ButtonState::Pressed if !p.captured && !ui.pointer => {
                // The click that takes the cursor does nothing else.
                capture = true;
                buttons.reset(MouseButton::Left);
                p.left = Left::Swallowed;
            }
            ButtonState::Pressed if free => {
                buttons.reset(MouseButton::Left);
                p.left = Left::Pending { since: now, moved: 0.0 };
            }
            ButtonState::Pressed => p.left = Left::Held,
            ButtonState::Released => {
                if let Left::Pending { .. } = p.left {
                    // A tap: the strike, pressed now and let go next frame.
                    buttons.press(MouseButton::Left);
                    p.release_next = true;
                    p.tapped = true;
                }
                p.left = Left::Up;
            }
        }
    }
    let delta = motion.delta;
    match p.left {
        Left::Pending { since, moved } => {
            let moved = moved + delta.length();
            if moved > DRAG_PX {
                p.left = Left::Dragging;
            } else if now - since >= HOLD_S {
                buttons.press(MouseButton::Left);
                p.left = Left::Held;
            } else {
                p.left = Left::Pending { since, moved };
            }
        }
        Left::Dragging => p.turn_px += delta.x,
        _ => {}
    }
    p.dragging = p.left == Left::Dragging;
    // Two-finger pans turn the view; a notched wheel zooms.
    for e in wheel.read() {
        match e.unit {
            MouseScrollUnit::Pixel => {
                match e.phase {
                    TouchPhase::Started => {
                        p.coasting = !p.panning && now - p.pan_ended < COAST_GAP_S;
                        p.panning = true;
                    }
                    TouchPhase::Ended | TouchPhase::Canceled => {
                        p.panning = false;
                        p.pan_ended = now;
                    }
                    TouchPhase::Moved => {}
                }
                if !p.coasting {
                    p.turn_px += e.x / win.scale_factor() * PAN_GAIN;
                }
                if matches!(e.phase, TouchPhase::Ended | TouchPhase::Canceled) {
                    p.coasting = false;
                }
            }
            MouseScrollUnit::Line => p.zoom *= 1.0 - WHEEL_STEP * e.y.clamp(-3.0, 3.0),
        }
    }
    for g in pinch.read() {
        p.zoom *= 1.0 - g.0.clamp(-0.5, 0.5);
    }
    if taps.read().count() > 0 {
        p.align = true;
    }
    // Where the cursor is.
    if p.captured {
        let moving = if p.dragging { Vec2::ZERO } else { delta };
        p.pos = Some((p.pos.unwrap_or(size / 2.0) + moving).clamp(Vec2::ZERO, size));
        if moving != Vec2::ZERO {
            if let (Some(pos), Some(target)) = (p.pos, bevy::camera::RenderTarget::Window(bevy::window::WindowRef::Entity(win_e)).normalize(Some(win_e))) {
                picks.write(PointerInput::new(PointerId::Mouse, Location { target, position: pos }, PointerAction::Move { delta: moving }));
            }
        }
    } else {
        p.pos = win.cursor_position();
    }
    if let Some(at) = p.place.take() {
        let at = at.clamp(Vec2::ZERO, size);
        p.pos = Some(at);
        if !p.captured {
            win.set_cursor_position(Some(at));
        }
    }
    // Capture or give back.
    if capture != p.captured {
        p.captured = capture;
        if capture {
            cursor.grab_mode = CursorGrabMode::Locked;
            cursor.visible = false;
            p.pos = p.pos.or(Some(size / 2.0));
        } else {
            cursor.grab_mode = CursorGrabMode::None;
            cursor.visible = true;
            // The system cursor comes back where the game's was.
            if let Some(at) = p.pos {
                win.set_cursor_position(Some(at));
            }
            if p.left != Left::Up {
                buttons.reset(MouseButton::Left);
                p.left = Left::Up;
            }
        }
        if let Some(mut s) = settings {
            s.is_mouse_enabled = !capture;
        }
    }
}

#[derive(Component)]
struct GameCursor;

/// A small ring with a dot, drawn over everything while the cursor is captured.
fn spawn_cursor(mut commands: Commands, mut images: ResMut<Assets<Image>>) {
    let n = 32u32;
    let mut data = vec![0u8; (n * n * 4) as usize];
    for y in 0..n {
        for x in 0..n {
            let d = Vec2::new(x as f32 + 0.5 - n as f32 / 2.0, y as f32 + 0.5 - n as f32 / 2.0).length();
            let ring = (1.0 - ((d - 9.5).abs() - 1.2).max(0.0)).clamp(0.0, 1.0);
            let edge = (1.0 - ((d - 9.5).abs() - 2.4).max(0.0)).clamp(0.0, 1.0);
            let dot = (2.6 - d).clamp(0.0, 1.0);
            let white = ring.max(dot);
            let a = edge.max(dot).max(white);
            let i = ((y * n + x) * 4) as usize;
            let v = (white * 255.0) as u8;
            data[i..i + 4].copy_from_slice(&[v, v, v, (a * 230.0) as u8]);
        }
    }
    let image = Image::new(
        bevy::render::render_resource::Extent3d { width: n, height: n, depth_or_array_layers: 1 },
        bevy::render::render_resource::TextureDimension::D2,
        data,
        bevy::render::render_resource::TextureFormat::Rgba8UnormSrgb,
        bevy::asset::RenderAssetUsages::RENDER_WORLD,
    );
    commands.spawn((
        GameCursor,
        ImageNode::new(images.add(image)),
        Node { position_type: PositionType::Absolute, width: Val::Px(24.0), height: Val::Px(24.0), display: Display::None, ..default() },
        GlobalZIndex(i32::MAX),
        Pickable::IGNORE,
    ));
}

fn draw_cursor(p: Res<Pointer>, mut q: Query<&mut Node, With<GameCursor>>, scale: Option<Res<UiScale>>, windows: Query<(), With<PrimaryWindow>>) {
    let k = scale.map_or(1.0, |s| s.0);
    let headless_shown = windows.is_empty() && p.scripted.is_some();
    for mut n in &mut q {
        let show = (p.captured || headless_shown) && p.pos.is_some();
        let want = if show { Display::Flex } else { Display::None };
        if n.display != want {
            n.display = want;
        }
        if let (true, Some(pos)) = (show, p.pos) {
            // UI values are scaled by `UiScale`; the cursor sits on its centre.
            let (l, t) = (Val::Px(pos.x / k - 12.0), Val::Px(pos.y / k - 12.0));
            if n.left != l {
                n.left = l;
            }
            if n.top != t {
                n.top = t;
            }
        }
    }
}
