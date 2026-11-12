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

mod cluster;
mod death;
mod facing;
mod frame;
pub mod hit;
pub mod icons;
pub mod kit;
mod link;
mod live;
pub mod model;
mod numbers;
mod overhead;
mod pack;
pub mod prim;
pub mod people;
mod prompt;
mod sample;
pub mod say;
pub mod settings;
mod theme;
pub mod tips;
pub mod wheel;
pub mod grid;
mod top;
mod verbs;
pub mod win;
pub mod wood;

use bevy::prelude::*;
use bevy::ui::UiSystems;

pub struct UiPlugin;

/// The live source and the widgets (timed with `LIVING_GAME_PERF=ui`).
#[derive(SystemSet, Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct UiWork;

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
            .init_resource::<people::Hints>()
            .init_resource::<prompt::Tip>()
            .init_resource::<pack::Carrying>()
            .init_resource::<prim::Slots>()
            .configure_sets(Update, UiInput.in_set(crate::phase::Phase::Input).before(crate::controls::movement))
            .add_systems(PreStartup, (theme::load_fonts, icons::build))
            .init_resource::<ThemeState>()
            // The UI's trees are spawned once the theme is known, and again on each new theme.
            .add_systems(PostUpdate, (theme, sweep.run_if(rebuilding), (frame::spawn, cluster::spawn, prim::spawn_tooltip, wheel::spawn, grid::spawn, overhead::spawn, numbers::spawn, say::spawn, prompt::spawn, top::spawn, win::spawn_anchors, death::spawn, verbs::spawn, link::spawn, tips::spawn).run_if(rebuilding), rebuilt).chain().before(UiSystems::Prepare).before(win::apply))
            .add_systems(Update, (default_camera, scale))
            .add_systems(PostUpdate, tips::update.before(UiSystems::Prepare));
        let widgets = ((cluster::extras, cluster::fill, prim::paint, prim::tooltip).chain(), cluster::update, frame::target, frame::vignette, overhead::plates, overhead::bubbles, numbers::update, top::update, death::update, link::update, verbs::menu, verbs::toasts, visibility);
        let windows = (people::update, people::hints, people::offers, prompt::update, say::update, pack::update, wheel::update, grid::update);
        if lookdev {
            app.add_systems(PostUpdate, (sample::fill, widgets).chain().before(UiSystems::Prepare))
                .add_systems(PostUpdate, wood::shade_text.after(rebuilt).after(sample::fill).before(UiSystems::Prepare));
        } else {
            // Connected play: the game UI's input, its windows and the live source.
            app.add_systems(Update, ((hit::hit, win::esc, win::keys, win::pointer, top::clicks, settings::update, facing::update, settings::apply_prefs, people::clicks, prompt::clicks, verbs::clicks, grid::clicks, pack::clicks, their_window).chain().in_set(UiInput), say::keys.in_set(crate::phase::Phase::Input).after(UiInput).before(crate::controls::movement)))
                .add_systems(Update, (people::ingest, say::follow).in_set(crate::phase::Phase::Present))
                .add_systems(PostUpdate, (win::apply, win::place, settings::spawn, facing::spawn, facing::pill_spawn, people::spawn, pack::spawn, kit::paint).chain().before(UiSystems::Prepare))
                .add_systems(PostUpdate, dump.after(UiSystems::Layout))
                .add_systems(PostUpdate, (live::fill, verbs::fill, widgets, windows, facing::pill).chain().in_set(UiWork).before(UiSystems::Prepare))
                // Light text gets the theme's drop the frame it is spawned (Glass).
                .add_systems(PostUpdate, wood::shade_text.after(rebuilt).after(kit::paint).after(UiWork).before(UiSystems::Prepare));
            if perf_on() {
                app.init_resource::<UiPerf>()
                    .add_systems(Update, (perf_begin::<0>.before(UiInput).in_set(crate::phase::Phase::Input), perf_end::<0>.after(UiInput).in_set(crate::phase::Phase::Input)))
                    .add_systems(PostUpdate, (perf_begin::<1>.before(UiWork), perf_end::<1>.after(UiWork).before(UiSystems::Prepare)))
                    .add_systems(PostUpdate, (perf_begin::<2>.after(UiSystems::Prepare).before(UiSystems::Layout), perf_end::<2>.after(UiSystems::Layout), perf_report.after(UiSystems::Layout)));
            }
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
    // Introduce yourself from the list: their window, with the line in its box.
    if let Some(id) = verbs.introduce.take() {
        ws.open(win::Win::Person(id));
        verbs.want_intro = Some(id);
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

/// The interface's theme in force, and a change asked for this frame (F4, Settings › Play).
#[derive(Resource, Default)]
pub struct ThemeState {
    pub name: wood::Name,
    pub want: Option<wood::Name>,
    rebuild: bool,
    started: bool,
}

/// The theme: from the settings file (or `LIVING_GAME_THEME`, for captures) at start; F4 cycles
/// it; a change is saved, named on screen, and rebuilds the UI.
fn theme(mut looks: ResMut<ThemeState>, keys: Res<ButtonInput<KeyCode>>, input: Res<crate::controls::Input>, mut prefs: ResMut<crate::keys::Prefs>, mut verbs: Option<ResMut<crate::verbs::Verbs>>, mut tips: ResMut<tips::Tips>, mut ws: ResMut<win::Windows>, time: Res<Time>) {
    if !looks.started {
        looks.started = true;
        let n = std::env::var("LIVING_GAME_THEME").ok().and_then(|v| wood::Name::parse(&v)).or_else(|| prefs.theme.as_deref().and_then(wood::Name::parse)).unwrap_or_default();
        looks.name = n;
        wood::set(n);
        looks.rebuild = true;
        info!("ui: theme {}", n.label());
        return;
    }
    if keys.just_pressed(KeyCode::F4) && !input.chat_open {
        looks.want = Some(looks.name.next());
    }
    if let Some(n) = looks.want.take().filter(|n| *n != looks.name) {
        looks.name = n;
        wood::set(n);
        looks.rebuild = true;
        ws.respawn = true;
        prefs.theme = Some(n.key().into());
        prefs.dirty = true;
        let text = format!("Theme: {}  ·  F4 changes it", n.label());
        info!("ui: {text}");
        match verbs.as_mut() {
            Some(v) => v.toasts.push(crate::verbs::Toast { text, ok: None, at: time.elapsed_secs_f64() }),
            None => tips.show(&text, time.elapsed_secs_f64()),
        }
    }
}

fn rebuilding(looks: Res<ThemeState>) -> bool {
    looks.rebuild
}

/// A new theme: every UI tree goes, to be spawned again in the new look.
fn sweep(mut commands: Commands, roots: Query<Entity, With<HudRoot>>) {
    for e in &roots {
        commands.entity(e).despawn();
    }
}

fn rebuilt(mut looks: ResMut<ThemeState>) {
    looks.rebuild = false;
}

/// A script's request for the game UI's state (`dump:NAME` in the live script; `verify-ui`).
#[derive(Resource, Default)]
pub struct Dump(pub Option<std::path::PathBuf>);

/// Write the game UI's state: open windows (top last) with their anchors and rectangles (UI px
/// and fractions of the picture), the Menu list, the list of acts, the words being typed and to
/// whom, the notes shown, the weapon, and every tagged node shown.
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
    (extra, model, pick): (DumpExtra, Res<model::HudModel>, Option<Res<crate::pick::Pick>>),
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
        "typing": input.chat_open.then(|| serde_json::json!({"words": input.chat, "window": typing.window.map(|w| w.name()), "to": talk.as_ref().and_then(|t| t.to), "label": talk.as_ref().map(|t| t.label.clone()), "earshot": talk.as_ref().map(|t| t.earshot.clone()), "tab": talk.as_ref().and_then(|t| t.tabbed.as_ref().map(|(p, e, c)| serde_json::json!({"prev": p, "earshot": e, "chose": c})))})),
        "pointer_over_ui": ui.over_ui,
        "notes": verbs.toasts.iter().map(|t| t.text.clone()).collect::<Vec<_>>(),
        // The pack's load and limit as its header shows them (while the pack is open).
        "pack": model.verbs.inventory.as_ref().map(|i| serde_json::json!({"carried": i.carried, "limit": i.limit, "items": i.rows.iter().map(|r| (r.0.clone(), r.1)).collect::<Vec<_>>()})),
        // My bars (`meters()`) and pills (`status_of`) as drawn.
        "me": model.me.as_ref().map(|m| serde_json::json!({"meters": m.meters.iter().map(|x| serde_json::json!({"name": x.name, "label": x.label, "value": x.value, "max": x.max})).collect::<Vec<_>>(), "statuses": m.statuses.iter().map(|x| serde_json::json!({"name": x.name, "tone": format!("{:?}", x.tone), "text": x.text})).collect::<Vec<_>>()})),
        // Who is under the cursor (`pick.rs`), whose nameplates show as hovered, and the target plate.
        "under": pick.as_ref().and_then(|p| p.under),
        // `holds`: the cursor is inside its outline as `pick.rs` draws it (its own test).
        "seen": pick.as_ref().map(|p| p.seen.iter().map(|s| serde_json::json!({"id": s.id, "feet": [s.feet.x, s.feet.y], "head": [s.head.x, s.head.y], "depth": s.depth, "ground": s.ground, "holds": extra.pointer.pos.is_some_and(|c| s.contains(c))})).collect::<Vec<_>>()),
        "hovered": model.actors.iter().filter(|a| a.hovered).map(|a| serde_json::json!({"id": a.id, "label": a.name})).collect::<Vec<_>>(),
        "targeted": model.actors.iter().find(|a| a.targeted).map(|a| a.id),
        // The notes on screen now (the facing-sight readout among them).
        "toasts": model.verbs.toasts.iter().map(|(t, _, _)| t.clone()).collect::<Vec<_>>(),
        "extra": extra.json(),
        // The open wheel: whom, how it opened, its sections, the one selected, what is behind More.
        "wheel": verbs.wheel.as_ref().map(|w| serde_json::json!({"title": w.title, "held": w.held, "sel": w.sel.map(|d| d.as_str()), "vec": [w.vec.x, w.vec.y], "at": [w.at.x, w.at.y],
            "sections": w.layout.sections.iter().map(|s| serde_json::json!({"dir": s.dir.as_str(), "what": s.what.name(), "label": w.labels.get(&s.what), "allowed": s.allowed, "pinned": s.pinned, "sub": s.sub, "reason": w.reasons.get(&s.what)})).collect::<Vec<_>>(),
            "more": w.layout.more.iter().map(|p| p.name()).collect::<Vec<_>>()})),
        // The open recipe grid: its way, its cells (live or greyed, with the rules' reason) and rows.
        "grid": verbs.grid.as_ref().map(|g| serde_json::json!({"skill": g.skill, "title": g.title, "sel": g.sel,
            "cells": g.cells.iter().map(|c| serde_json::json!({"product": c.product, "item": c.item, "label": c.label, "allowed": c.allowed, "reason": c.reason, "detail": c.detail, "rows": c.rows})).collect::<Vec<_>>()})),
        "tags": ui.tags.iter().map(|(k, v)| (k.clone(), serde_json::json!([v.x, v.y]))).collect::<serde_json::Map<_, _>>(),
    });
    match std::fs::write(&path, serde_json::to_string_pretty(&v).unwrap_or_default()) {
        Ok(()) => info!("ui: state written to {}", path.display()),
        Err(e) => warn!("ui: could not write {}: {e}", path.display()),
    }
}

/// Further state the dump reports, from the widgets of later steps.
#[derive(bevy::ecs::system::SystemParam)]
pub struct DumpExtra<'w, 's> {
    prefs: Res<'w, crate::keys::Prefs>,
    binds: Res<'w, crate::keys::Binds>,
    theme: Res<'w, ThemeState>,
    weapon: Res<'w, crate::weapon::Weapon>,
    slots: Res<'w, prim::Slots>,
    talks: Res<'w, people::Talks>,
    tip: Query<'w, 's, &'static Node, With<prim::Tooltip>>,
    tip_title: Query<'w, 's, &'static Text, (With<prim::TooltipTitle>, Without<prim::TooltipText>)>,
    tip_text: Query<'w, 's, &'static Text, (With<prim::TooltipText>, Without<prim::TooltipTitle>)>,
    pointer: Res<'w, crate::pointer::Pointer>,
    cam: Res<'w, crate::camera::Cam>,
    fov: Option<Res<'w, crate::facing::FovState>>,
    heard: Option<Res<'w, crate::heardmark::HeardMarks>>,
    edge: Option<Res<'w, crate::sightedge::SightEdge>>,
    mouths: Option<Res<'w, crate::mouth::Mouths>>,
    film: Res<'w, crate::post::Film>,
}

impl DumpExtra<'_, '_> {
    fn json(&self) -> serde_json::Value {
        // The bar's slots as drawn: what each is, why it is greyed, held, refused just now.
        let slots: serde_json::Map<_, _> = self.slots.0.iter().map(|(k, v)| (k.0.clone(), serde_json::json!({"label": v.label, "key": v.key, "off": v.off, "held": v.held, "refused": v.refused.is_some(), "count": v.count, "caption": v.caption}))).collect();
        let tip = self.tip.iter().any(|n| n.display != Display::None).then(|| serde_json::json!({"title": self.tip_title.iter().next().map(|t| t.0.clone()), "text": self.tip_text.iter().next().map(|t| t.0.clone())}));
        // The game's cursor (logical px in the window, and fractions of the picture), the view's
        // yaw and zoom, and the ground point under the cursor (x, height, y): what a view turn or
        // a zoom keeps or changes.
        let size = crate::capture::size().as_vec2();
        let cursor = self.pointer.pos.map(|p| serde_json::json!({"x": p.x, "y": p.y, "fx": p.x / size.x, "fy": p.y / size.y}));
        let ground = self.cam.cursor_ground.map(|g| serde_json::json!([g.x, g.y, g.z]));
        // Facing sight: whether it is on, the field's five values, whether this client can switch
        // it, and the heard marks (`facing.rs`, `heardmark.rs`).
        let fov = self.fov.as_ref().map(|f| {
            serde_json::json!({"known": f.known, "on": f.on(), "changes": f.changes, "can_switch": f.can_switch, "last": f.last, "walk": f.walk,
                "sight": self.edge.as_ref().and_then(|e| e.senses.map(|s| s.sight)), "source": self.edge.as_ref().and_then(|e| e.source.map(|s| format!("{s:?}"))),
                "field": f.field.map(|v| serde_json::json!({"focal_deg": v.focal_deg, "side_deg": v.side_deg, "side_share": v.side_share, "near_m": v.near_m, "margin_deg": v.margin_deg}))})
        });
        serde_json::json!({"preset": self.binds.preset.name(), "control": format!("{:?}", self.prefs.control), "tips": self.prefs.tips, "auto_draw": self.prefs.auto_draw, "theme": self.theme.name.key(),
            "drawn": self.weapon.drawn, "slots": slots, "tooltip": tip,
            "events": self.talks.events.iter().rev().take(12).rev().map(|(_, t)| t.clone()).collect::<Vec<_>>(),
            "cards": self.talks.cards.iter().map(|(who, i, text)| serde_json::json!({"with": who, "card": i, "text": text})).collect::<Vec<_>>(),
            "cursor": cursor, "view": {"yaw": self.cam.shown_yaw, "zoom": self.cam.zoom}, "cursor_ground": ground,
            "facing_sight": fov, "facing_note": self.fov.as_ref().and_then(|f| f.note.clone()).map(|(t, _)| t), "heard": self.heard.as_ref().map(|h| h.json()), "sight_look": self.edge.as_ref().map(|e| e.look.name()), "sight_edge": self.edge.as_ref().map(|e| e.mode.name()), "film": self.film.name(), "film_saved": self.prefs.film,
            // Each speaking body's mouth now (`mouth.rs`), by character id.
            "mouths": self.mouths.as_ref().map(|m| m.by_id.iter().map(|(id, w)| (id.to_string(), serde_json::json!(w))).collect::<serde_json::Map<_, _>>())})
    }
}

/// `LIVING_GAME_PERF=ui`: what the game UI costs a frame, timed round its own work (input; the
/// live source and the widgets; Bevy's UI layout of every node), logged every 10 s as means
/// and worsts in µs, with the number of UI nodes. Whole-frame time on a shared, loaded machine
/// is too noisy to see a fraction of a millisecond.
#[derive(Resource, Default)]
pub struct UiPerf {
    t0: [Option<std::time::Instant>; 3],
    sum: [f64; 3],
    worst: [f64; 3],
    frames: u32,
    next: f64,
}

pub fn perf_on() -> bool {
    std::env::var("LIVING_GAME_PERF").is_ok_and(|v| v.split(',').any(|f| f.trim() == "ui"))
}

fn perf_begin<const K: usize>(mut p: ResMut<UiPerf>) {
    p.t0[K] = Some(std::time::Instant::now());
}

fn perf_end<const K: usize>(mut p: ResMut<UiPerf>) {
    if let Some(t) = p.t0[K].take() {
        let us = t.elapsed().as_secs_f64() * 1e6;
        p.sum[K] += us;
        p.worst[K] = p.worst[K].max(us);
    }
}

fn perf_report(mut p: ResMut<UiPerf>, time: Res<Time>, nodes: Query<(), With<Node>>) {
    p.frames += 1;
    let now = time.elapsed_secs_f64();
    if now < p.next {
        return;
    }
    if p.next > 0.0 && p.frames > 0 {
        let n = p.frames as f64;
        info!("ui perf: input {:.0} µs (worst {:.0}), fill+widgets {:.0} µs (worst {:.0}), layout {:.0} µs (worst {:.0}) over {} frames; {} UI nodes", p.sum[0] / n, p.worst[0], p.sum[1] / n, p.worst[1], p.sum[2] / n, p.worst[2], p.frames, nodes.iter().count());
    }
    *p = UiPerf { next: now + 10.0, ..default() };
}
