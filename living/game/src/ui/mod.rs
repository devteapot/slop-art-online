//! The player's in-game UI in Bevy UI (docs/GAME_BRIEF.md, HUD decided 2026-11-09). The egui
//! panels in `hud.rs` are developer tools behind F1.
//!
//! - `model.rs`: the view-model the widgets draw;
//! - `live.rs`: fills it from the authority's rows (connected play);
//! - `sample.rs`: fills it with sample values in look-dev (`LIVING_GAME_HUD`);
//! - widgets: `frame.rs` (health, energy, status, skill bar, hint, target frame),
//!   `overhead.rs` (nameplates and speech bubbles), `chat.rs`, `death.rs`, `compass.rs`,
//!   `link.rs` (offline and reconnecting), `tips.rs` (first-time hints),
//!   `verbs.rs` (the F hint's acts, the list of acts, notes of outcomes, inventory and know-how);
//! - `theme.rs` (colours, type, panels) and `icons.rs` (procedural glyphs).
//!
//! Interface D (2026-11-11, the owner's choice; `wood.rs`, `win.rs`, `top.rs`, `hit.rs`) is
//! replacing these widgets step by step. Its layout is the mock-up's, drawn at 1600×900, scaled
//! with the window's height (`UiScale`).

mod death;
mod frame;
pub mod hit;
mod icons;
pub mod kit;
mod link;
mod live;
pub mod model;
mod numbers;
mod overhead;
mod pack;
pub mod people;
mod prompt;
mod sample;
pub mod say;
pub mod settings;
mod theme;
pub mod tips;
mod top;
mod verbs;
pub mod win;
pub mod wood;

use bevy::prelude::*;
use bevy::ui::UiSystems;

pub struct UiPlugin;

/// The game UI's input this frame (pointer, Esc, window keys), before anything else reads keys
/// and the mouse: a click on a window is not a strike, and Esc is spent once.
#[derive(SystemSet, Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct UiInput;

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
        win::plugin(app);
        app.init_resource::<model::HudModel>()
            .init_resource::<model::Outbox>()
            .init_resource::<overhead::Stack>()
            .init_resource::<tips::Tips>()
            .init_resource::<hit::UiPointer>()
            .init_resource::<say::Typing>()
            .init_resource::<settings::Capture>()
            .init_resource::<Dump>()
            .init_resource::<settings::Page>()
            .init_resource::<settings::SkillNames>()
            .init_resource::<people::Talks>()
            .init_resource::<people::LogPage>()
            .init_resource::<prompt::Tip>()
            .init_resource::<pack::Carrying>()
            .configure_sets(Update, UiInput.in_set(crate::phase::Phase::Input).before(crate::controls::movement))
            .add_systems(PreStartup, (theme::load_fonts, icons::build))
            .add_systems(Startup, (frame::spawn, overhead::spawn, numbers::spawn, say::spawn, prompt::spawn, top::spawn, win::spawn_anchors, death::spawn, verbs::spawn, link::spawn, tips::spawn))
            .add_systems(Update, (default_camera, scale))
            .add_systems(PostUpdate, tips::update.before(UiSystems::Prepare));
        let widgets = (frame::vitals, frame::status, frame::skills, frame::target, frame::vignette, overhead::plates, overhead::bubbles, numbers::update, top::update, death::update, link::update, verbs::menu, verbs::toasts, visibility);
        let windows = (people::update, prompt::update, say::update, pack::update);
        if lookdev {
            app.add_systems(PostUpdate, (sample::fill, widgets).chain().before(UiSystems::Prepare));
        } else {
            // Connected play: the game UI's input, its windows and the live source.
            app.add_systems(Update, ((hit::hit, win::esc, win::keys, win::pointer, top::clicks, settings::update, settings::apply_prefs, people::clicks, prompt::clicks, verbs::clicks, pack::clicks, their_window).chain().in_set(UiInput), say::keys.in_set(crate::phase::Phase::Input).after(UiInput).before(crate::controls::movement)))
                .add_systems(Update, (people::ingest, say::follow).in_set(crate::phase::Phase::Present))
                .add_systems(PostUpdate, (win::apply, win::place, settings::spawn, people::spawn, pack::spawn, kit::paint).chain().before(UiSystems::Prepare))
                .add_systems(PostUpdate, dump.after(UiSystems::Layout))
                .add_systems(PostUpdate, (live::fill, verbs::fill, widgets, windows).chain().before(UiSystems::Prepare));
        }
    }
}

/// Every top-level UI tree of the game UI (hidden when no source fills the model).
#[derive(Component)]
pub struct HudRoot;

/// The list of acts asked for a person's window ("Their window").
/// And a script's `panel:` steps: the pack and know-how are windows since interface D.
fn their_window(mut verbs: ResMut<crate::verbs::Verbs>, mut ws: ResMut<win::Windows>) {
    if let Some(id) = verbs.open_window.take() {
        ws.open(win::Win::Person(id));
    }
    if std::mem::take(&mut verbs.inventory) {
        ws.open(win::Win::Pack);
    }
    if std::mem::take(&mut verbs.know_how) {
        ws.open(win::Win::Skills);
    }
    if std::mem::take(&mut verbs.close_panels) {
        ws.close(win::Win::Pack);
        ws.close(win::Win::Skills);
    }
}

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

/// Interface D was drawn at 1600×900: the UI scales with the target's height over 900
/// (1600×900 → 1, 2560×1440 → 1.6), and never under 0.9 (at 720p the old HUD's 9–12 px type
/// read as 6–8 px, play-test 1).
fn scale(mut ui: ResMut<UiScale>, cams: Query<&Camera, With<Camera3d>>) {
    let h = cams.iter().find_map(|c| c.logical_viewport_size()).map_or(900.0, |s| s.y);
    let s = (h / 900.0).clamp(0.9, 2.5);
    if (ui.0 - s).abs() > 1e-3 {
        ui.0 = s;
    }
}

// ---- small helpers shared by the widgets --------------------------------------------------

/// A rules name as the UI shows it: words, the first capitalised ("berry_bush" → "Berry bush").
/// The rules' own names read as code in a list (play-test 1).
pub(crate) fn label(s: &str) -> String {
    let s = s.replace('_', " ");
    let mut c = s.chars();
    match c.next() {
        Some(f) => f.to_uppercase().chain(c).collect(),
        None => s,
    }
}

/// Health as the bars read it: both figures rounded alike, so a full bar never reads more than
/// its maximum (the authority's 109.48 of 109.48 read "110 / 109": `ceil` against `round`), and
/// a living character never reads 0.
pub(crate) fn hp_text(hp: f32, max: f32) -> String {
    let max = max.round().max(1.0);
    let hp = if hp > 0.0 { hp.round().clamp(1.0, max) } else { 0.0 };
    format!("{hp:.0} / {max:.0}")
}

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

#[cfg(test)]
mod tests {
    #[test]
    fn rules_names_and_labels_read_as_words() {
        assert_eq!(super::label("berry_bush"), "Berry bush");
        assert_eq!(super::label("a stranger"), "A stranger");
        assert_eq!(super::label("Old Hale"), "Old Hale");
        assert_eq!(super::label(""), "");
    }

    #[test]
    fn health_never_reads_over_its_maximum() {
        assert_eq!(super::hp_text(109.48073, 109.48073), "109 / 109");
        assert_eq!(super::hp_text(110.6, 110.6), "111 / 111");
        assert_eq!(super::hp_text(0.3, 110.0), "1 / 110");
        assert_eq!(super::hp_text(0.0, 110.0), "0 / 110");
    }
}

/// A script's request for the game UI's state (`dump:NAME` in the live script; `verify-ui`).
#[derive(Resource, Default)]
pub struct Dump(pub Option<std::path::PathBuf>);

/// Write the game UI's state: open windows (top last) with their anchors and rectangles (UI px
/// and fractions of the picture), the Menu list, the list of acts, the words being typed and to
/// whom, the weapon, and every tagged node shown.
#[allow(clippy::too_many_arguments)]
fn dump(
    mut d: ResMut<Dump>,
    ws: Res<win::Windows>,
    ui: Res<hit::UiPointer>,
    frames: Query<(&win::WinFrame, &bevy::ui::ComputedNode, &bevy::ui::UiGlobalTransform)>,
    cams: Query<&Camera, With<Camera3d>>,
    verbs: Res<crate::verbs::Verbs>,
    input: Res<crate::controls::Input>,
    typing: Res<say::Typing>,
    talk: Option<Res<crate::talk::Talk>>,
    extra: DumpExtra,
) {
    let Some(path) = d.0.take() else { return };
    let size = cams.iter().find_map(|c| c.physical_viewport_size()).map_or(Vec2::new(1600.0, 900.0), |s| s.as_vec2());
    let k = ui.scale * ui.ui_scale.max(0.01);
    let windows: Vec<serde_json::Value> = ws
        .open
        .iter()
        .map(|o| {
            let r = frames.iter().find(|(f, _, _)| f.0 == o.win).map(|(_, n, t)| {
                let c = t.affine().translation;
                let (tl, sz) = (c - n.size() / 2.0, n.size());
                serde_json::json!({"x": tl.x / k, "y": tl.y / k, "w": sz.x / k, "h": sz.y / k, "fx": tl.x / size.x, "fy": tl.y / size.y, "fw": sz.x / size.x, "fh": sz.y / size.y})
            });
            serde_json::json!({"win": o.win.name(), "anchor": format!("{:?}", o.anchor), "rect": r})
        })
        .collect();
    let v = serde_json::json!({
        "windows": windows,
        "top": ws.top().map(|w| w.name()),
        "menu": ws.menu,
        "acts": verbs.menu.as_ref().map(|m| serde_json::json!({"title": m.title, "group": m.group, "rows": m.rows().iter().map(|r| r.label()).collect::<Vec<_>>()})),
        "typing": input.chat_open.then(|| serde_json::json!({"words": input.chat, "window": typing.window.map(|w| w.name()), "to": talk.as_ref().and_then(|t| t.to), "label": talk.as_ref().map(|t| t.label.clone())})),
        "pointer_over_ui": ui.over_ui,
        "extra": extra.json(),
        "tags": ui.tags.iter().map(|(k, v)| (k.clone(), serde_json::json!([v.x, v.y]))).collect::<serde_json::Map<_, _>>(),
    });
    match std::fs::write(&path, serde_json::to_string_pretty(&v).unwrap_or_default()) {
        Ok(()) => info!("ui: state written to {}", path.display()),
        Err(e) => warn!("ui: could not write {}: {e}", path.display()),
    }
}

/// Further state the dump reports, from the widgets of later steps.
#[derive(bevy::ecs::system::SystemParam)]
pub struct DumpExtra<'w> {
    prefs: Res<'w, crate::keys::Prefs>,
    binds: Res<'w, crate::keys::Binds>,
}

impl DumpExtra<'_> {
    fn json(&self) -> serde_json::Value {
        serde_json::json!({"preset": self.binds.preset.name(), "control": format!("{:?}", self.prefs.control), "tips": self.prefs.tips, "auto_draw": self.prefs.auto_draw})
    }
}

