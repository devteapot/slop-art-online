//! The player's in-game UI in Bevy UI (docs/GAME_BRIEF.md, HUD decided 2026-11-09). The egui
//! panels in `hud.rs` are developer tools behind F1.
//!
//! - `model.rs`: the view-model the widgets draw;
//! - `live.rs`: fills it from the authority's rows (connected play);
//! - `sample.rs`: fills it with sample values in look-dev (`LIVING_GAME_HUD`);
//! - widgets: `frame.rs` (health, energy, status, skill bar, hint, target frame),
//!   `overhead.rs` (nameplates and speech bubbles), `chat.rs`, `death.rs`, `compass.rs`,
//!   `link.rs` (offline and reconnecting),
//!   `verbs.rs` (the F hint's acts, the list of acts, notes of outcomes, inventory and know-how);
//! - `theme.rs` (colours, type, panels) and `icons.rs` (procedural glyphs).
//!
//! Layout is designed at 1080p and scaled with the window's height (`UiScale`).

mod chat;
mod compass;
mod death;
mod frame;
mod icons;
mod link;
mod live;
pub mod model;
mod numbers;
mod overhead;
mod sample;
mod theme;
mod verbs;

use bevy::prelude::*;
use bevy::ui::UiSystems;

pub struct UiPlugin;

/// Whether the look-dev scene gets the sample UI (`LIVING_GAME_HUD`).
fn sample_on() -> bool {
    sample::states().is_some()
}

impl Plugin for UiPlugin {
    fn build(&self, app: &mut App) {
        // Look-dev photographs and frame-time runs stay free of the UI unless it is asked for.
        let lookdev = crate::lookdev::enabled();
        if lookdev && !sample_on() {
            return;
        }
        app.init_resource::<model::HudModel>()
            .init_resource::<model::Outbox>()
            .init_resource::<overhead::Stack>()
            .add_systems(PreStartup, (theme::load_fonts, icons::build))
            .add_systems(Startup, (frame::spawn, overhead::spawn, numbers::spawn, chat::spawn, compass::spawn, death::spawn, verbs::spawn, link::spawn))
            .add_systems(Update, (default_camera, scale, chat::keys.in_set(crate::phase::Phase::Input).before(crate::controls::movement)));
        let widgets = (frame::vitals, frame::status, frame::skills, frame::hint, frame::target, frame::vignette, overhead::plates, overhead::bubbles, numbers::update, chat::update, compass::update, death::update, link::update, verbs::menu, verbs::toasts, verbs::panels, visibility);
        if lookdev {
            app.add_systems(PostUpdate, (sample::fill, widgets).chain().before(UiSystems::Prepare));
        } else {
            app.add_systems(PostUpdate, (live::fill, verbs::fill, widgets).chain().before(UiSystems::Prepare));
        }
    }
}

/// Every top-level UI tree of the game UI (hidden when no source fills the model).
#[derive(Component)]
pub struct HudRoot;

/// The UI shows while a source fills it; the death screen hides everything else.
fn visibility(model: Res<model::HudModel>, mut q: Query<(&mut Visibility, Has<death::DeathRoot>), With<HudRoot>>) {
    for (mut v, is_death) in &mut q {
        let on = model.shown && (is_death || model.death.is_none());
        v.set_if_neq(if on { Visibility::Inherited } else { Visibility::Hidden });
    }
}

/// The game camera draws the UI, also when it renders into an image (headless photographs).
fn default_camera(mut commands: Commands, cams: Query<Entity, Added<Camera3d>>) {
    for e in &cams {
        commands.entity(e).insert(bevy::ui::IsDefaultUiCamera);
    }
}

/// Designed at 1080p; scales with the target's height (1600×900 → 0.83, 2560×1440 → 1.33).
fn scale(mut ui: ResMut<UiScale>, cams: Query<&Camera, With<Camera3d>>) {
    let h = cams.iter().find_map(|c| c.logical_viewport_size()).map_or(1080.0, |s| s.y);
    // Designed at 1080p, drawn 10% larger and never under 0.9 of it: at 720p it was 0.67, and
    // its 9–12 px type read as 6–8 px (play-test 1).
    let s = (h / 1080.0 * 1.1).clamp(0.9, 2.5);
    if (ui.0 - s).abs() > 1e-3 {
        ui.0 = s;
    }
}

// ---- small helpers shared by the widgets --------------------------------------------------

pub(crate) fn set_text(t: &mut Text, s: &str) {
    if t.0 != s {
        t.0 = s.to_string();
    }
}

pub(crate) fn show(n: &mut Node, on: bool) {
    let d = if on { Display::Flex } else { Display::None };
    if n.display != d {
        n.display = d;
    }
}

pub(crate) fn set_color(c: &mut TextColor, col: Color) {
    if c.0 != col {
        c.0 = col;
    }
}

pub(crate) fn set_bg(c: &mut BackgroundColor, col: Color) {
    if c.0 != col {
        c.0 = col;
    }
}

pub(crate) fn set_width(n: &mut Node, w: Val) {
    if n.width != w {
        n.width = w;
    }
}
