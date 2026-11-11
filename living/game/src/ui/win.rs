//! Interface D's floating windows: the walnut frame, two anchors, dragging and snapping, closing
//! and the Esc order (`.local/living/ui-designs/`, design D; docs/GAME_BRIEF.md, "Interface D").
//!
//! - **Two anchors.** The left anchor holds a person, the log and people, or (later) the
//!   character; the right anchor holds the pack. One window per anchor, so at most two narrow
//!   windows are open and the middle of the screen stays clear. Opening a window takes its home
//!   anchor and replaces what is there. Skills and Settings are wide: they sit in the centre and
//!   close the others.
//! - **Moving.** Hold the click on the title bar and slide (a three-finger drag is the same
//!   press and move). Let go and the window snaps to the nearer anchor; if another window holds
//!   it, the two change places. A wide window goes back to the centre.
//! - **Closing.** ✕, the window's own key, or Esc for the top window. A click in a window raises
//!   it.
//! - **The Esc order:** a list of acts (its sub-list first), the Menu list, the words being
//!   typed (with their window), the top window. With nothing open, Esc opens Menu and frees the
//!   system cursor; a click on the world captures it again (`pointer.rs`).
//!
//! Everything goes through the game's cursor (`hit.rs`), so it works the same with the system
//! cursor, with the drawn one while it is captured, and in headless scripts.
//!
//! A window's content is built by its module when its body appears ([`WinBody`], `Added`) and
//! is despawned with it.

use super::hit::{Block, Hot, UiPointer};
use super::icons::{Glyph, Icons, Mark};
use super::theme::Fonts;
use super::wood;
use super::HudRoot;
use bevy::prelude::*;
use bevy::ui::GlobalZIndex;

/// Narrow and wide windows' widths, and the anchors' places (mock-up px at 1600×900).
pub const NARROW_W: f32 = 426.0;
pub const WIDE_W: f32 = 1076.0;
const MARGIN: f32 = 26.0;
/// The right anchor sits under the compass and the two buttons.
const RIGHT_TOP: f32 = 252.0;
const CENTRE_TOP: f32 = 42.0;
/// The column the compass and buttons take on the right; a wide window centres left of it.
const RIGHT_COLUMN: f32 = 190.0;
/// The cluster's height at the bottom centre: a wide window ends above it.
const CLUSTER_H: f32 = 150.0;
const Z_WINDOWS: i32 = 30;
pub const Z_MENU: i32 = 60;
pub const Z_LIST: i32 = 70;
pub const Z_DRAG: i32 = 90;

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Win {
    /// A person, by character id.
    Person(u32),
    Log,
    Pack,
    Skills,
    Settings,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Anchor {
    Left,
    Right,
    Centre,
}

impl Win {
    pub fn wide(self) -> bool {
        matches!(self, Win::Skills | Win::Settings)
    }

    pub fn home(self) -> Anchor {
        match self {
            Win::Pack => Anchor::Right,
            Win::Skills | Win::Settings => Anchor::Centre,
            Win::Person(_) | Win::Log => Anchor::Left,
        }
    }

    /// The window's own key, shown beside its ✕.
    pub fn key(self) -> Option<&'static str> {
        match self {
            Win::Pack => Some("I"),
            Win::Log => Some("L"),
            Win::Skills => Some("K"),
            Win::Settings | Win::Person(_) => None,
        }
    }

    /// Its name in tags and dumps: `Pack`, `Log`, `Person7`.
    pub fn name(self) -> String {
        match self {
            Win::Person(id) => format!("Person{id}"),
            w => format!("{w:?}"),
        }
    }

    fn title(self) -> &'static str {
        match self {
            Win::Person(_) => "",
            Win::Log => "Log and people",
            Win::Pack => "Pack",
            Win::Skills => "Skills and know-how",
            Win::Settings => "Settings",
        }
    }
}

/// A window's frame (the walnut panel).
#[derive(Component)]
pub struct WinFrame(pub Win);
/// Where its content goes: the parchment body.
#[derive(Component)]
pub struct WinBody(pub Win);
/// Its title bar (drag handle) and ✕.
#[derive(Component)]
pub struct WinHead(pub Win);
#[derive(Component)]
pub struct WinClose(pub Win);
/// Its title's text, for windows whose title changes (a person's label).
#[derive(Component)]
pub struct WinTitle(pub Win);
#[derive(Component)]
pub struct AnchorMark(Anchor);

pub struct Open {
    pub win: Win,
    pub anchor: Anchor,
    pub frame: Entity,
}

struct Drag {
    win: Win,
    /// Cursor minus the frame's top-left when the drag began (logical px).
    grab: Vec2,
    /// The frame's top-left now (logical px).
    at: Vec2,
}

enum Want {
    Open(Win),
    Toggle(Win),
    Close(Win),
}

#[derive(Resource, Default)]
pub struct Windows {
    /// Open windows, bottom to top.
    pub open: Vec<Open>,
    /// The Menu list under its button.
    pub menu: bool,
    /// "Leave the world" was clicked once; the next click leaves.
    pub leaving: bool,
    drag: Option<Drag>,
    want: Vec<Want>,
    /// The screen in UI units (logical px over the UI scale).
    screen: Vec2,
}

impl Windows {
    pub fn open(&mut self, w: Win) {
        self.want.push(Want::Open(w));
    }

    pub fn toggle(&mut self, w: Win) {
        self.want.push(Want::Toggle(w));
    }

    pub fn close(&mut self, w: Win) {
        self.want.push(Want::Close(w));
    }

    pub fn is_open(&self, w: Win) -> bool {
        self.open.iter().any(|o| o.win == w)
    }

    pub fn top(&self) -> Option<Win> {
        self.open.last().map(|o| o.win)
    }

    pub fn at(&self, a: Anchor) -> Option<Win> {
        self.open.iter().find(|o| o.anchor == a).map(|o| o.win)
    }

    pub fn anchor_of(&self, w: Win) -> Option<Anchor> {
        self.open.iter().find(|o| o.win == w).map(|o| o.anchor)
    }

    /// The person whose window is open (the topmost one if two are).
    pub fn person(&self) -> Option<u32> {
        self.open.iter().rev().find_map(|o| match o.win {
            Win::Person(id) => Some(id),
            _ => None,
        })
    }

    pub fn dragging(&self) -> Option<Win> {
        self.drag.as_ref().map(|d| d.win)
    }

    fn raise(&mut self, w: Win) {
        if let Some(i) = self.open.iter().position(|o| o.win == w) {
            let o = self.open.remove(i);
            self.open.push(o);
        }
    }
}

pub fn plugin(app: &mut App) {
    app.init_resource::<Windows>();
}

/// Open and close what was asked this frame: spawn and despawn frames.
pub fn apply(mut commands: Commands, mut ws: ResMut<Windows>, fonts: Res<Fonts>, icons: Res<Icons>) {
    for want in std::mem::take(&mut ws.want) {
        let (w, toggle) = match want {
            Want::Close(w) => {
                close(&mut commands, &mut ws, w);
                continue;
            }
            Want::Open(w) => (w, false),
            Want::Toggle(w) => (w, true),
        };
        if ws.is_open(w) {
            if toggle {
                close(&mut commands, &mut ws, w);
            } else {
                ws.raise(w);
            }
            continue;
        }
        let anchor = w.home();
        // A wide window closes the others; a narrow one closes a wide one and whatever holds its
        // anchor.
        let gone: Vec<Win> = ws.open.iter().filter(|o| w.wide() || o.win.wide() || o.anchor == anchor).map(|o| o.win).collect();
        for g in gone {
            close(&mut commands, &mut ws, g);
        }
        let frame = spawn_frame(&mut commands, &fonts, &icons, w);
        ws.open.push(Open { win: w, anchor, frame });
        info!("ui: window {w:?} opened at {anchor:?}");
    }
}

fn close(commands: &mut Commands, ws: &mut Windows, w: Win) {
    if let Some(i) = ws.open.iter().position(|o| o.win == w) {
        let o = ws.open.remove(i);
        commands.entity(o.frame).despawn();
        if ws.drag.as_ref().is_some_and(|d| d.win == w) {
            ws.drag = None;
        }
        info!("ui: window {w:?} closed");
    }
}

fn spawn_frame(commands: &mut Commands, f: &Fonts, icons: &Icons, w: Win) -> Entity {
    let width = if w.wide() { WIDE_W } else { NARROW_W };
    commands
        .spawn((
            HudRoot,
            WinFrame(w),
            Block,
            Node { position_type: PositionType::Absolute, width: Val::Px(width), flex_direction: FlexDirection::Column, border: UiRect::all(Val::Px(3.0)), border_radius: BorderRadius::all(Val::Px(12.0)), ..default() },
            wood::wood(),
            GlobalZIndex(Z_WINDOWS),
        ))
        .with_children(|fr| {
            fr.spawn(wood::rim(9.0));
            // Title bar: grip, title, the window's key, ✕. Holding it moves the window.
            fr.spawn((WinHead(w), Hot, super::hit::Tag(format!("win:{}:head", w.name())), Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, justify_content: JustifyContent::SpaceBetween, padding: UiRect::new(Val::Px(16.0), Val::Px(12.0), Val::Px(8.0), Val::Px(6.0)), ..default() }))
                .with_children(|h| {
                    h.spawn((Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(10.0), ..default() }, Pickable::IGNORE)).with_children(|l| {
                        grip(l);
                        l.spawn((WinTitle(w), Text::new(w.title()), wood::title(f, 22.0), Pickable::IGNORE));
                    });
                    h.spawn((Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(6.0), ..default() }, Pickable::IGNORE)).with_children(|r| {
                        if let Some(k) = w.key() {
                            wood::chip(r, f, k, ());
                            r.spawn((Text::new("or"), wood::on_wood(f, 12.0, 700), Pickable::IGNORE));
                        }
                        wood::chip(r, f, "Esc", ());
                        r.spawn((
                            WinClose(w),
                            Hot,
                            super::hit::Tag(format!("win:{}:close", w.name())),
                            Node { width: Val::Px(28.0), height: Val::Px(28.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(8.0)), margin: UiRect::left(Val::Px(2.0)), ..default() },
                            BackgroundColor(wood::X_RED),
                            BorderColor::all(wood::INK),
                            wood::hard_shadow(2.0, 0.4),
                        ))
                        .with_child(wood::icon(icons, Glyph::Ui(Mark::Close), 14.0, Color::WHITE));
                    });
                });
            fr.spawn((
                WinBody(w),
                Node { margin: UiRect::new(Val::Px(9.0), Val::Px(9.0), Val::Px(0.0), Val::Px(9.0)), border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(8.0)), padding: UiRect::all(Val::Px(14.0)), flex_direction: FlexDirection::Column, row_gap: Val::Px(8.0), overflow: Overflow::clip(), flex_shrink: 1.0, min_height: Val::Px(0.0), ..default() },
                wood::parch(),
            ));
        })
        .id()
}

/// The six dots of a title bar's grip.
pub fn grip(p: &mut ChildSpawnerCommands) {
    p.spawn((Node { display: Display::Grid, grid_template_columns: RepeatedGridTrack::px(3, 4.0), row_gap: Val::Px(3.0), column_gap: Val::Px(3.0), ..default() }, Pickable::IGNORE)).with_children(|g| {
        for _ in 0..6 {
            g.spawn((Node { width: Val::Px(4.0), height: Val::Px(4.0), border_radius: BorderRadius::all(Val::Percent(50.0)), ..default() }, BackgroundColor(wood::alpha(wood::BRASS2, 0.7)), Pickable::IGNORE));
        }
    });
}

/// The two anchors, outlined only while a window is dragged.
pub fn spawn_anchors(mut commands: Commands, fonts: Res<Fonts>) {
    for (a, label) in [(Anchor::Left, "left anchor: people, log, character"), (Anchor::Right, "right anchor: the pack")] {
        let mut node = Node { position_type: PositionType::Absolute, top: Val::Px(if a == Anchor::Left { MARGIN } else { RIGHT_TOP }), width: Val::Px(NARROW_W), height: Val::Px(560.0), border: UiRect::all(Val::Px(3.0)), border_radius: BorderRadius::all(Val::Px(14.0)), display: Display::None, ..default() };
        if a == Anchor::Left {
            node.left = Val::Px(MARGIN);
        } else {
            node.right = Val::Px(MARGIN);
        }
        commands.spawn((HudRoot, AnchorMark(a), node, BackgroundColor(wood::alpha(wood::ANCHOR, 0.12)), BorderColor::all(wood::alpha(wood::ANCHOR, 0.85)), GlobalZIndex(Z_WINDOWS - 1), Pickable::IGNORE)).with_child((
            Node { position_type: PositionType::Absolute, left: Val::Px(12.0), top: Val::Px(10.0), ..default() },
            Text::new(label),
            fonts.body(13.0, 900),
            TextColor(wood::ANCHOR),
            bevy::ui::widget::TextShadow { offset: Vec2::new(0.0, 1.0), color: wood::INK },
            Pickable::IGNORE,
        ));
    }
}

/// Clicks on ✕ and in windows, title-bar drags and their snapping.
pub fn pointer(mut ws: ResMut<Windows>, ui: Res<UiPointer>, heads: Query<&WinHead>, closes: Query<&WinClose>, frames: Query<(&WinFrame, &bevy::ui::ComputedNode, &bevy::ui::UiGlobalTransform)>) {
    if let Some(c) = ui.clicked.and_then(|e| closes.get(e).ok()) {
        ws.close(c.0);
    }
    // A press in a window raises it.
    if let (Some(p), true) = (ui.pos, ui.down.is_some() && ui.moved() == 0.0) {
        let phys = p * ui.scale;
        if let Some(w) = frames.iter().filter(|(_, n, t)| n.contains_point(**t, phys)).map(|(f, _, _)| f.0).last() {
            if ws.top() != Some(w) && ws.drag.is_none() {
                ws.raise(w);
            }
        }
    }
    // A drag from a title bar moves its window.
    if ws.drag.is_none() && ui.dragging {
        if let (Some((from, at)), Some(_)) = (ui.down, ui.pos) {
            if let Ok(h) = heads.get(from) {
                let top_left = frames.iter().find(|(f, _, _)| f.0 == h.0).map(|(_, n, t)| (t.affine().translation - n.size() / 2.0) / ui.scale);
                if let Some(tl) = top_left {
                    ws.drag = Some(Drag { win: h.0, grab: at - tl, at: tl });
                    ws.raise(h.0);
                    info!("ui: dragging {:?}", h.0);
                }
            }
        }
    }
    if let Some(d) = ws.drag.as_mut() {
        if let Some(p) = ui.pos {
            d.at = p - d.grab;
        }
    }
    let let_go = ui.dropped.is_some() || (ui.down.is_none() && !ui.dragging);
    if let_go {
        if let Some(d) = ws.drag.take() {
            let screen_w = ws.screen.x * ui.ui_scale;
            let width = if d.win.wide() { WIDE_W } else { NARROW_W } * ui.ui_scale;
            let centre = d.at.x + width / 2.0;
            let to = if d.win.wide() {
                Anchor::Centre
            } else if centre < screen_w / 2.0 {
                Anchor::Left
            } else {
                Anchor::Right
            };
            let from = ws.anchor_of(d.win).unwrap_or(to);
            // The window there, if any, takes this one's old place.
            if let Some(other) = ws.open.iter_mut().find(|o| o.anchor == to && o.win != d.win) {
                other.anchor = from;
            }
            if let Some(o) = ws.open.iter_mut().find(|o| o.win == d.win) {
                o.anchor = to;
            }
            info!("ui: {:?} snapped to {to:?}", d.win);
        }
    }
}

/// Where each window sits, its height limit and its order; the anchors' outlines while dragging.
#[allow(clippy::type_complexity)]
pub fn place(mut ws: ResMut<Windows>, cams: Query<&Camera, With<Camera3d>>, ui_scale: Res<UiScale>, mut frames: Query<(&WinFrame, &mut Node, &mut GlobalZIndex), Without<AnchorMark>>, mut marks: Query<(&AnchorMark, &mut Node), Without<WinFrame>>) {
    let logical = cams.iter().find_map(|c| c.logical_viewport_size()).unwrap_or(Vec2::new(1600.0, 900.0));
    let k = ui_scale.0.max(0.01);
    let screen = logical / k;
    ws.screen = screen;
    let dragging = ws.drag.as_ref().map(|d| (d.win, d.at / k));
    for (i, o) in ws.open.iter().enumerate() {
        let Ok((_, mut n, mut z)) = frames.iter_mut().find(|(f, _, _)| f.0 == o.win).ok_or(()) else { continue };
        let width = if o.win.wide() { WIDE_W } else { NARROW_W };
        let (left, right, top) = match (dragging.filter(|d| d.0 == o.win), o.anchor) {
            (Some((_, at)), _) => (Val::Px(at.x), Val::Auto, Val::Px(at.y)),
            (None, Anchor::Left) => (Val::Px(MARGIN), Val::Auto, Val::Px(MARGIN)),
            (None, Anchor::Right) => (Val::Auto, Val::Px(MARGIN), Val::Px(RIGHT_TOP)),
            (None, Anchor::Centre) => (Val::Px(((screen.x - RIGHT_COLUMN - width) / 2.0).max(MARGIN)), Val::Auto, Val::Px(CENTRE_TOP)),
        };
        let anchor_top = match o.anchor {
            Anchor::Left => MARGIN,
            Anchor::Right => RIGHT_TOP,
            Anchor::Centre => CENTRE_TOP,
        };
        let bottom = if o.anchor == Anchor::Centre { CLUSTER_H + 16.0 } else { MARGIN };
        let max_h = Val::Px((screen.y - anchor_top - bottom).max(160.0));
        if n.left != left {
            n.left = left;
        }
        if n.right != right {
            n.right = right;
        }
        if n.top != top {
            n.top = top;
        }
        if n.max_height != max_h {
            n.max_height = max_h;
        }
        let want = GlobalZIndex(Z_WINDOWS + 1 + i as i32 * 2 + if dragging.is_some_and(|d| d.0 == o.win) { 20 } else { 0 });
        if *z != want {
            *z = want;
        }
    }
    let narrow_drag = dragging.is_some_and(|d| !d.0.wide());
    for (m, mut n) in &mut marks {
        super::show(&mut n, narrow_drag);
        let h = Val::Px(match m.0 {
            Anchor::Left => screen.y - 2.0 * MARGIN - 300.0,
            _ => screen.y - RIGHT_TOP - MARGIN - 200.0,
        }
        .max(200.0));
        if n.height != h {
            n.height = h;
        }
    }
}

/// Esc, in order: a list of acts (its sub-list first), the Menu list, the words being typed
/// (and the window they are typed in), the top window; with nothing open, Menu opens and the
/// system cursor is given back. Esc is then spent for every other reader this frame.
#[allow(clippy::too_many_arguments)]
pub fn esc(mut keys: ResMut<ButtonInput<KeyCode>>, mut ws: ResMut<Windows>, mut verbs: ResMut<crate::verbs::Verbs>, mut input: ResMut<crate::controls::Input>, mut pointer: ResMut<crate::pointer::Pointer>, model: Res<super::model::HudModel>, mut typing: ResMut<super::say::Typing>, capture: Res<super::settings::Capture>) {
    if !keys.just_pressed(KeyCode::Escape) || model.death.is_some() || capture.listening() {
        return;
    }
    keys.clear_just_pressed(KeyCode::Escape);
    if let Some(m) = verbs.menu.as_mut() {
        if m.group.is_some() {
            m.group = None;
        } else {
            verbs.menu = None;
        }
        return;
    }
    if ws.menu {
        ws.menu = false;
        ws.leaving = false;
        return;
    }
    if input.compose.is_some() {
        input.compose = None;
        input.chat_open = false;
        input.chat.clear();
        return;
    }
    if input.chat_open {
        input.chat_open = false;
        input.chat.clear();
        if let Some(w) = typing.window.take() {
            ws.close(w);
        }
        return;
    }
    if let Some(w) = ws.top() {
        ws.close(w);
        return;
    }
    ws.menu = true;
    pointer.release = true;
    info!("ui: Esc with nothing open: Menu, cursor freed");
}

/// The windows' own keys: I the pack, L the log and people, K skills and know-how.
pub fn keys(keys: Res<ButtonInput<KeyCode>>, binds: Res<crate::keys::Binds>, mut ws: ResMut<Windows>, input: Res<crate::controls::Input>, wants: Res<crate::hud::UiWants>, model: Res<super::model::HudModel>, capture: Res<super::settings::Capture>) {
    if input.chat_open || wants.keyboard || model.death.is_some() || capture.listening() {
        return;
    }
    use crate::keys::Act;
    for (act, w) in [(Act::Pack, Win::Pack), (Act::Log, Win::Log), (Act::Skills, Win::Skills)] {
        if binds.just_pressed(act, &keys) {
            ws.toggle(w);
        }
    }
}
