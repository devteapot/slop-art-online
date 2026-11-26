//! Settings (interface D): a wide window in the centre, opened from Menu (or Menu after Esc with
//! nothing open).
//!
//! - **Play:** the interface's theme (Glass, Clear, Night, Linen, Walnut; F4 cycles it), the control scheme (facing the cursor, or where you walk; F3 switches it too),
//!   how the body looks aside while walking (a look-walk preset, `twist.rs`),
//!   how the edge of sight is drawn (not seen now, limited view, fade; F2 cycles it too), how
//!   unseen ground looks (memory by default, grey, wash, lantern, shadows, hatch), facing sight
//!   (on/off, its five values and its switch where the launcher allows it: `ui/facing.rs`), the
//!   film (soft by default, full as before film-1, or none: `post::Film`), the hair shine (crown
//!   by default, soft, or today's ring: `style::HAIR_SHINES`), the
//!   weapon drawing itself when something attacks you, and key hints and first-time tips (with
//!   "Show tips again").
//! - **Controls:** the skill-key preset ("Q E R, plus 1–9", "1–9 only", "My own") and every
//!   binding (`keys.rs`). Click a key, then press the new one (or a mouse button); Esc cancels.
//!   A key already in use is swapped.
//!
//! Every change is saved to the viewer's settings file at once (`keys::save`).

use super::hit::{Tag, UiPointer};
use super::kit::{self, Lit};
use super::theme::Fonts;
use super::win::{Win, WinBody};
use super::{set_text, show, wood};
use crate::keys::{Act, Bind, Binds, Prefs, Preset};
use bevy::prelude::*;

/// A binding waiting for its new key (Settings › Controls).
#[derive(Resource, Default)]
pub struct Capture {
    pub waiting: Option<(Act, usize)>,
    /// Frames to wait before listening (the click that started it must not be its new key).
    arm: u8,
}

impl Capture {
    pub fn listening(&self) -> bool {
        self.waiting.is_some()
    }
}

#[derive(Resource, Default, Clone, Copy, PartialEq, Eq, Debug)]
pub enum Page {
    #[default]
    Play,
    Controls,
    Camera,
    CameraTuning,
}

#[derive(Component)]
pub struct PageBody(Page);
/// Where Settings › Play shows facing sight (`ui/facing.rs` fills it).
#[derive(Component)]
pub struct FacingSight;
/// A binding's chip: its act and which of its keys.
#[derive(Component)]
pub struct BindChip(Act, usize);
/// A Settings row or heading for heed for players (the throng's switch, the keeping-track
/// keys), with its display when shown: shown only while the world's laws let players heed ([`heed_only`]).
#[derive(Component)]
pub struct HeedOnly(Display);
#[derive(Component)]
pub struct BindText(Act, usize);
#[derive(Component)]
pub struct BindName(Act);

/// What each binding is called, by the bar's skill where the rules give one.
fn act_label(a: Act, names: &SkillNames) -> String {
    let skill = |s: &Option<String>, fallback: &str| s.clone().map_or_else(|| fallback.to_string(), |n| super::label(&n));
    match a {
        Act::Forward => "Move forward".into(),
        Act::Back => "Move back".into(),
        Act::Left => "Move left".into(),
        Act::Right => "Move right".into(),
        Act::Run => "Run (hold)".into(),
        Act::Jump => skill(&names.jump, "Jump"),
        Act::Dodge => skill(&names.dodge, "Dodge"),
        Act::Weapon => "Draw or sheathe".into(),
        Act::Primary => skill(&names.slots[0], "Mouse skill"),
        Act::Secondary => skill(&names.slots[1], "Second mouse skill"),
        Act::Skill1 => skill(&names.slots[2], "Skill 1"),
        Act::Skill2 => skill(&names.slots[3], "Skill 2"),
        Act::Skill3 => skill(&names.slots[4], "Skill 3"),
        Act::Extra(i) => names.extra.get(i as usize).cloned().flatten().map_or_else(|| format!("Skill {}", i + 4), |n| super::label(&n)),
        Act::Interact => "Act on what you point at".into(),
        Act::Talk => "Talk".into(),
        Act::Address => "Change whom you speak to".into(),
        Act::Way => "Change how you speak".into(),
        Act::Wave => "Wave".into(),
        Act::Nod => "Nod".into(),
        Act::LookOver => "Look someone over".into(),
        Act::Pack => "Pack".into(),
        Act::Character => "Character".into(),
        Act::Skills => "Skills and know-how".into(),
        Act::Log => "Log and people".into(),
        Act::NorthUp => "Snap camera north".into(),
        Act::Glance => "Glance with the camera (hold)".into(),
        Act::Pin => "Keep track of whoever you point at (again: stop)".into(),
        Act::ClearPins => "Stop keeping track of everyone".into(),
    }
}

/// The rules' skills on the bar's places (filled by the cluster from `combat::Roles`).
#[derive(Resource, Default, Clone, PartialEq)]
pub struct SkillNames {
    pub slots: [Option<String>; 5],
    pub extra: Vec<Option<String>>,
    pub jump: Option<String>,
    pub dodge: Option<String>,
}

pub fn spawn(mut commands: Commands, bodies: Query<(Entity, &WinBody), Added<WinBody>>, fonts: Res<Fonts>, binds: Res<Binds>, names: Res<SkillNames>) {
    let f = &*fonts;
    for (e, b) in &bodies {
        if b.0 != Win::Settings {
            continue;
        }
        commands.entity(e).insert(Node { margin: wood::body_frame().0, border: wood::body_frame().1, border_radius: wood::r(8.0), padding: UiRect::all(Val::Px(14.0)), flex_direction: FlexDirection::Row, column_gap: Val::Px(18.0), overflow: Overflow::clip(), ..default() });
        commands.entity(e).with_children(|body| {
            // Pages.
            body.spawn((Node { width: Val::Px(150.0), flex_direction: FlexDirection::Column, row_gap: Val::Px(6.0), flex_shrink: 0.0, ..default() }, Pickable::IGNORE)).with_children(|tabs| {
                for (label, page) in [("Play", "play"), ("Controls", "controls"), ("Camera", "rotation"), ("Camera tuning", "camera")].into_iter().filter(|&(_, page)| page != "camera" || camera_dev()) {
                    tabs.spawn((super::hit::Hot, Tag(format!("settings:page:{page}")), kit::Paint::Choice, Lit(false), Node { padding: UiRect::axes(Val::Px(12.0), Val::Px(8.0)), border: wood::b(2.0), border_radius: wood::r(8.0), ..default() }, bevy::ui::BackgroundGradient::default(), BorderColor::all(wood::edge())))
                        .with_child((Text::new(label), wood::ink(f, 14.0, 800), Pickable::IGNORE));
                }
                tabs.spawn((Text::new("Opened from Menu, or Esc with no window open. That also frees the cursor; click the world to take it back."), f.body(12.5, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { margin: UiRect::top(Val::Px(14.0)), ..default() }, Pickable::IGNORE));
            });
            // Play.
            body.spawn((PageBody(Page::Play), Node { flex_grow: 1.0, flex_direction: FlexDirection::Column, ..default() }, Pickable::IGNORE)).with_children(|pg| {
                row(pg, f, "Look", "The interface's theme (F4)", |c| kit::seg(c, f, "settings:theme", &super::wood::Name::ALL.map(|n| (n.label(), n.key()))));
                row(pg, f, "Camera", "Choose how the camera follows your character", |c| kit::seg(c, f, "settings:camera", &[("Top-down (default)", "top-down"), ("Orbit (old)", "orbit")]));
                row(pg, f, "Facing", "", |c| kit::seg(c, f, "settings:facing", &crate::controls::Facing::CHOICES));
                row(pg, f, "Movement look", "When to follow the mouse (F3)", |c| kit::seg(c, f, "settings:control", &[("Face where you walk", "travel"), ("Face the cursor", "cursor")]));
                row(pg, f, "Looking aside", "Walking one way and looking another: how far the head and chest turn before the body follows", |c| kit::seg(c, f, "settings:look_walk", &crate::twist::PRESETS));
                row(pg, f, "Edge of sight", "How what you can't see now is drawn (F2)", |c| kit::seg(c, f, "settings:sight", &[("Not seen now", "unseen"), ("Limited view", "limited"), ("Fade", "fade")]));
                row(pg, f, "Unseen ground", "How ground you don't see now looks, with \"not seen now\"", |c| kit::seg(c, f, "settings:look", &crate::sightedge::Look::ALL.map(|l| (l.label(), l.name()))));
                row(pg, f, "Film", "The warm haze from the top of the screen. Soft keeps dark colours; Full lifts them too", |c| kit::seg(c, f, "settings:film", &crate::post::Film::ALL.map(|m| (m.label(), m.name()))));
                row(pg, f, "Hair shine", "The highlight on hair. Crown lies over the crown and stays off a fringe", |c| kit::seg(c, f, "settings:hair", &crate::style::HairShine::choices()));
                row(pg, f, "Weapon", "Draw it by itself when something attacks you", |c| kit::toggle(c, "settings:auto_draw"));
                // Heed for players (`heed.rs`): shown only while the world's laws let players
                // heed, so a world without it shows the page as before.
                let r = row_entity(pg, f, "The throng", "Those you see but don't keep track of, drawn as simple figures", |c| kit::toggle(c, "settings:throng"));
                pg.commands().entity(r).insert(HeedOnly(Display::Grid));
                // Facing sight: on/off, the switch where the launcher allows it, and the field's
                // five values (filled by `ui/facing.rs`).
                pg.spawn((FacingSight, Node { display: Display::None, flex_direction: FlexDirection::Column, ..default() }, Pickable::IGNORE));
                row(pg, f, "Key hints and first-time tips", "", |c| {
                    kit::toggle(c, "settings:tips");
                    kit::button(c, f, "Show tips again", "settings:tips_again", true);
                });
            });
            body.spawn((PageBody(Page::Camera), Node { flex_grow: 1.0, flex_direction: FlexDirection::Column, display: Display::None, ..default() }, Pickable::IGNORE)).with_children(|pg| {
                row(pg, f, "Top-down rotation", "Middle drag or twist two fingers. Middle tap snaps north.", |c| kit::toggle(c, "settings:camera_rotate"));
                row(pg, f, "Rotation speed", "", |c| kit::seg(c, f, "settings:camera_rotate_speed", &[("Slow", "0.5"), ("Normal", "1"), ("Fast", "2")]));
                row(pg, f, "Invert rotation", "", |c| kit::toggle(c, "settings:camera_rotate_invert"));
            });
            if camera_dev() {
                body.spawn((PageBody(Page::CameraTuning), Node { flex_grow: 1.0, flex_direction: FlexDirection::Column, display: Display::None, ..default() }, Pickable::IGNORE))
                    .with_children(|pg| camera_panel(pg, f));
            }
            // Controls.
            body.spawn((PageBody(Page::Controls), Node { flex_grow: 1.0, flex_direction: FlexDirection::Column, display: Display::None, ..default() }, Pickable::IGNORE)).with_children(|pg| {
                row(pg, f, "Skill keys", "Mouse buttons stay the basic attacks", |c| kit::seg(c, f, "settings:preset", &[("Q E R, plus 1–9", "letters"), ("1–9 only", "numbers"), ("My own", "own")]));
                pg.spawn((Node { display: Display::Grid, grid_template_columns: RepeatedGridTrack::fr(2, 1.0), column_gap: Val::Px(26.0), ..default() }, Pickable::IGNORE)).with_children(|grid| {
                    let groups: [(&str, Vec<Act>); 4] = [
                        ("Moving", vec![Act::Forward, Act::Back, Act::Left, Act::Right, Act::Run, Act::Jump, Act::Dodge, Act::Glance, Act::NorthUp]),
                        ("Fighting", { let mut v = vec![Act::Weapon, Act::Primary, Act::Secondary, Act::Skill1, Act::Skill2, Act::Skill3]; v.extend((0..crate::keys::EXTRA).map(Act::Extra)); v }),
                        ("People and things", vec![Act::Interact, Act::Talk, Act::Address, Act::Way, Act::Wave, Act::Nod, Act::LookOver, Act::Pack, Act::Character, Act::Skills, Act::Log]),
                        // Heed for players: shown only while the world's laws let players heed.
                        ("Keeping track", vec![Act::Pin, Act::ClearPins]),
                    ];
                    for (head, acts) in groups {
                        let heed = head == "Keeping track";
                        let h = grid.spawn((Node { grid_column: GridPlacement::span(2), margin: UiRect::new(Val::Px(0.0), Val::Px(0.0), Val::Px(8.0), Val::Px(2.0)), ..default() }, Text::new(head), wood::tface(&f, 16.0), TextColor(wood::heading()), Pickable::IGNORE)).id();
                        if heed {
                            grid.commands().entity(h).insert(HeedOnly(Display::Flex));
                        }
                        for a in acts {
                            let row_e = grid.spawn((Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, justify_content: JustifyContent::SpaceBetween, column_gap: Val::Px(8.0), padding: UiRect::vertical(Val::Px(3.0)), border: UiRect::bottom(Val::Px(1.5)), ..default() }, BorderColor::all(wood::line()), Pickable::IGNORE)).with_children(|r| {
                                r.spawn((BindName(a), Text::new(act_label(a, &names)), wood::ink(f, 13.5, 700), Pickable::IGNORE));
                                r.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(4.0), ..default() }, Pickable::IGNORE)).with_children(|ks| {
                                    for slot in 0..2 {
                                        let shown = slot < binds.get(a).len().max(1);
                                        ks.spawn((
                                            BindChip(a, slot),
                                            super::hit::Hot,
                                            Tag(format!("bind:{}:{slot}", a.name())),
                                            Node { min_width: Val::Px(34.0), height: Val::Px(24.0), padding: UiRect::axes(Val::Px(6.0), Val::Px(0.0)), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: wood::b(2.0), border_radius: wood::r(6.0), display: if shown { Display::Flex } else { Display::None }, ..default() },
                                            BackgroundColor(wood::surface()),
                                            BorderColor::all(wood::edge()),
                                            wood::hard_shadow(2.0, 0.5),
                                        ))
                                        .with_child((BindText(a, slot), Text::new(""), f.body(12.0, 900), TextColor(wood::text()), Pickable::IGNORE));
                                    }
                                });
                            }).id();
                            if heed {
                                grid.commands().entity(row_e).insert(HeedOnly(Display::Flex));
                            }
                        }
                    }
                });
                pg.spawn((Text::new("Click a key, then press the new one (or a mouse button). Esc cancels. A key already in use is swapped. A second key slot takes a twin (Q and 1)."), f.body(12.5, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { margin: UiRect::top(Val::Px(8.0)), ..default() }, Pickable::IGNORE));
            });
        });
    }
}

pub(super) fn row(p: &mut ChildSpawnerCommands, f: &Fonts, label: &str, help: &str, control: impl FnOnce(&mut ChildSpawnerCommands)) {
    row_entity(p, f, label, help, control);
}

fn row_entity(p: &mut ChildSpawnerCommands, f: &Fonts, label: &str, help: &str, control: impl FnOnce(&mut ChildSpawnerCommands)) -> Entity {
    p.spawn((Node { display: Display::Grid, grid_template_columns: vec![GridTrack::px(220.0), GridTrack::fr(1.0)], column_gap: Val::Px(12.0), align_items: AlignItems::Center, padding: UiRect::vertical(Val::Px(9.0)), border: UiRect::bottom(Val::Px(1.5)), ..default() }, BorderColor::all(wood::line()), Pickable::IGNORE)).with_children(|r| {
        r.spawn((Node { flex_direction: FlexDirection::Column, ..default() }, Pickable::IGNORE)).with_children(|l| {
            l.spawn((Text::new(label), wood::ink(f, 14.0, 800), Pickable::IGNORE));
            if !help.is_empty() {
                l.spawn((Text::new(help), f.body(12.0, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
            }
        });
        r.spawn((Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(10.0), ..default() }, Pickable::IGNORE)).with_children(control);
    }).id()
}

/// Clicks on the pages' controls, a binding's new key, and the pages' state.
#[allow(clippy::too_many_arguments)]
pub fn update(
    ui: Res<UiPointer>,
    tags: Query<&Tag>,
    mut lit: Query<(&Tag, &mut Lit)>,
    mut page: ResMut<Page>,
    mut pages: Query<(&PageBody, &mut Node), Without<BindChip>>,
    mut chips: Query<(&BindChip, &mut Node, &mut BackgroundColor), Without<PageBody>>,
    mut texts: Query<(&BindText, &mut Text), Without<BindName>>,
    mut names_q: Query<(&BindName, &mut Text), Without<BindText>>,
    names: Res<SkillNames>,
    (mut binds, mut prefs, mut cap): (ResMut<Binds>, ResMut<Prefs>, ResMut<Capture>),
    (mut input, mut edge, mut tips, mut lw): (ResMut<crate::controls::Input>, Option<ResMut<crate::sightedge::SightEdge>>, ResMut<super::tips::Tips>, ResMut<crate::twist::LookWalk>),
    (keys, mouse, time): (Res<ButtonInput<KeyCode>>, Res<ButtonInput<MouseButton>>, Res<Time>),
    open: Res<super::win::Windows>,
    (mut theme, mut film, mut shine): (ResMut<super::ThemeState>, ResMut<crate::post::Film>, ResMut<crate::style::HairShine>),
) {
    let mut changed = false;
    if !open.is_open(Win::Settings) {
        cap.waiting = None;
    }
    // A binding waiting for its key: the next key or mouse button (not the click that began it).
    if let Some((a, slot)) = cap.waiting {
        if cap.arm > 0 {
            cap.arm -= 1;
        } else if keys.just_pressed(KeyCode::Escape) {
            cap.waiting = None;
        } else {
            let got = crate::keys::all_keys().find(|k| *k != KeyCode::Escape && keys.just_pressed(*k)).map(Bind::Key).or_else(|| [MouseButton::Left, MouseButton::Right, MouseButton::Middle].into_iter().find(|m| mouse.just_pressed(*m)).map(Bind::Mouse));
            if let Some(b) = got {
                info!("settings: {} key {slot} → {}", a.name(), Binds::label(b));
                binds.rebind(a, slot, b);
                cap.waiting = None;
                changed = true;
            }
        }
    }
    if let Some(t) = kit::clicked(&ui, &tags) {
        let (what, value) = t.rsplit_once(':').unwrap_or((t, ""));
        match what {
            "settings:page" => *page = match value {
                "controls" => Page::Controls,
                "rotation" => Page::Camera,
                "camera" if camera_dev() => Page::CameraTuning,
                _ => Page::Play,
            },
            "settings:facing" => {
                prefs.facing = Some(if value == "cursor" {
                    input.control = crate::controls::Control::Cursor;
                    crate::controls::Facing::Cursor
                } else {
                    crate::controls::Facing::Natural
                });
                changed = true;
            }
            "settings:camera_preset" if camera_dev() => {
                if let Some(tuning) = crate::camera::Tuning::preset(value) {
                    prefs.camera_tuning = tuning;
                    changed = true;
                }
            }
            "settings:camera_pitch" if camera_dev() => {
                let tuning = &mut prefs.camera_tuning;
                match value {
                    "late" => {
                        tuning.fixed_pitch.get_or_insert(tuning.stops[1].pitch);
                        tuning.late_tilt.get_or_insert(crate::camera::LateTilt {
                            tilt_start: 0.8,
                            near_pitch: tuning.stops[2].pitch,
                        });
                    }
                    "fixed" => {
                        tuning.fixed_pitch.get_or_insert(tuning.stops[1].pitch);
                        tuning.late_tilt = None;
                    }
                    _ => {
                        tuning.fixed_pitch = None;
                        tuning.late_tilt = None;
                        tuning.keep_fov_curve = false;
                    }
                }
                changed = true;
            }
            "settings:camera" => {
                prefs.camera = if value == "orbit" { crate::camera::Mode::Orbit } else { crate::camera::Mode::TopDown };
                changed = true;
            }
            "settings:camera_rotate_speed" => {
                if let Ok(speed) = value.parse::<f32>() {
                    prefs.camera_rotate_speed = speed.clamp(0.5, 2.0);
                    changed = true;
                }
            }
            "settings:control" => {
                input.control = if value == "cursor" { crate::controls::Control::Cursor } else { crate::controls::Control::Travel };
                changed = true;
            }
            "settings:theme" => theme.want = super::wood::Name::parse(value),
            "settings:look_walk" => {
                if let Some(p) = crate::twist::LookWalk::preset(value) {
                    info!("settings: looking aside: {value}");
                    *lw = p;
                    prefs.look_walk = Some(value.into());
                    changed = true;
                }
            }
            "settings:sight" => {
                if let (Some(e), Some(m)) = (edge.as_mut(), crate::sightedge::Mode::parse(value)) {
                    e.mode = m;
                    changed = true;
                }
            }
            "settings:look" => {
                if let (Some(e), Some(l)) = (edge.as_mut(), crate::sightedge::Look::parse(value)) {
                    e.look = l;
                    changed = true;
                }
            }
            "settings:film" => {
                if let Some(m) = crate::post::Film::parse(value) {
                    info!("settings: film: {value}");
                    *film = m;
                    prefs.film = Some(value.into());
                    changed = true;
                }
            }
            "settings:hair" => {
                if let Some(s) = crate::style::HairShine::parse(value) {
                    info!("settings: hair shine: {value}");
                    *shine = s;
                    prefs.hair_shine = Some(value.into());
                    changed = true;
                }
            }
            "settings:preset" if value != "own" => {
                *binds = Binds::preset(if value == "numbers" { Preset::Numbers } else { Preset::Letters });
                changed = true;
            }
            _ => match t {
                "settings:camera_rotate" => {
                    prefs.camera_rotate = !prefs.camera_rotate;
                    changed = true;
                }
                "settings:camera_rotate_invert" => {
                    prefs.camera_rotate_invert = !prefs.camera_rotate_invert;
                    changed = true;
                }
                "settings:auto_draw" => {
                    prefs.auto_draw = !prefs.auto_draw;
                    changed = true;
                }
                "settings:throng" => {
                    prefs.throng = !prefs.throng;
                    info!("settings: the throng drawn {}", prefs.throng);
                    changed = true;
                }
                "settings:tips" => {
                    prefs.tips = !prefs.tips;
                    changed = true;
                }
                "settings:tips_again" => tips.again(time.elapsed_secs_f64()),
                _ => {
                    if let Some(rest) = t.strip_prefix("bind:") {
                        if let Some((name, slot)) = rest.rsplit_once(':') {
                            if let (Some(a), Ok(slot)) = (Act::all().into_iter().find(|a| a.name() == name), slot.parse::<usize>()) {
                                cap.waiting = Some((a, slot));
                                cap.arm = 1;
                                info!("settings: waiting for a key for {} {slot}", a.name());
                            }
                        }
                    }
                }
            },
        }
    }
    if std::mem::take(&mut prefs.dirty) {
        changed = true;
    }
    if changed {
        prefs.control = input.control;
        if let Some(e) = edge.as_ref() {
            prefs.sight_edge = Some(e.mode.name().into());
            prefs.sight_look = Some(e.look.name().into());
        }
        crate::keys::save(&binds, &prefs);
    }
    let sight = edge.as_ref().map(|e| e.mode.name());
    let look = edge.as_ref().map(|e| e.look.name());
    let control = if input.control == crate::controls::Control::Cursor { "cursor" } else { "travel" };
    let (pg, preset, theme_now, look_walk, film_now) = (*page, binds.preset.name(), theme.name.key(), lw.base().to_string(), film.name());
    let shine_now = shine.name();
    kit::light(&mut lit, |t| {
        let (what, value) = t.rsplit_once(':').unwrap_or((t, ""));
        match what {
            "settings:page" => Some(value == match pg { Page::Play => "play", Page::Controls => "controls", Page::Camera => "rotation", Page::CameraTuning => "camera" }),
            "settings:facing" => Some(value == prefs.facing().name()),
            "settings:camera_pitch" => Some(value == match (prefs.camera_tuning.fixed_pitch, prefs.camera_tuning.late_tilt) {
                (None, _) => "curve",
                (_, Some(_)) => "late",
                _ => "fixed",
            }),
            "settings:camera_rotate_speed" => Some(value.parse::<f32>() == Ok(prefs.camera_rotate_speed)),
            "settings:camera" => Some(value == prefs.camera.name()),
            "settings:control" => Some(value == control),
            "settings:sight" => Some(Some(value) == sight),
            "settings:look" => Some(Some(value) == look),
            "settings:preset" => Some(value == preset),
            "settings:theme" => Some(value == theme_now),
            "settings:look_walk" => Some(value == look_walk),
            "settings:film" => Some(value == film_now),
            "settings:hair" => Some(value == shine_now),
            _ => match t {
                "settings:camera_rotate" => Some(prefs.camera_rotate),
                "settings:camera_rotate_invert" => Some(prefs.camera_rotate_invert),
                "settings:auto_draw" => Some(prefs.auto_draw),
                "settings:throng" => Some(prefs.throng),
                "settings:tips" => Some(prefs.tips),
                _ => None,
            },
        }
    });
    for (p, mut n) in &mut pages {
        show(&mut n, p.0 == *page);
    }
    for (c, mut n, mut bg) in &mut chips {
        let have = binds.get(c.0).len();
        // A second slot shows for keys that have a twin, or as an empty slot to add one.
        let shown = c.1 < have.max(1) || (c.1 == 1 && !matches!(c.0, Act::Dodge | Act::Primary | Act::Secondary));
        show(&mut n, shown);
        let waiting = cap.waiting == Some((c.0, c.1));
        let col = if waiting { Color::srgb_u8(0xff, 0xcf, 0x5c) } else if c.1 >= have { wood::plain() } else { wood::surface() };
        if bg.0 != col {
            bg.0 = col;
        }
    }
    for (t, mut text) in &mut texts {
        let s = if cap.waiting == Some((t.0, t.1)) { "press a key…".to_string() } else { binds.get(t.0).get(t.1).map(|b| Binds::label(*b)).unwrap_or_else(|| "+".into()) };
        set_text(&mut text, &s);
    }
    for (n, mut text) in &mut names_q {
        set_text(&mut text, &act_label(n.0, &names));
    }
}

fn camera_dev() -> bool {
    std::env::var("LIVING_GAME_DEV").as_deref() == Ok("1")
}

#[derive(Component, Clone, Copy)]
pub(super) enum CameraSlider {
    Height(usize),
    Pitch(usize),
    Fov(usize),
    FixedPitch,
    TiltStart,
    NearPitch,
    Wheel,
    Easing,
}

impl CameraSlider {
    fn range(self) -> (f32, f32, f32) {
        match self {
            Self::Height(_) => (2.0, 50.0, 0.1),
            Self::Pitch(_) | Self::FixedPitch | Self::NearPitch => (15.0, 89.0, 0.1),
            Self::Fov(_) => (15.0, 90.0, 0.1),
            Self::TiltStart => (0.0, 1.0, 0.01),
            Self::Wheel => (0.005, 0.25, 0.001),
            Self::Easing => (1.0, 40.0, 0.1),
        }
    }

    fn value(self, t: &mut crate::camera::Tuning) -> Option<&mut f32> {
        match self {
            Self::Height(i) => Some(&mut t.stops[i].distance),
            Self::Pitch(i) if t.fixed_pitch.is_none() => Some(&mut t.stops[i].pitch),
            Self::Fov(i) if t.fixed_pitch.is_none() || t.keep_fov_curve || i == 1 => Some(&mut t.stops[i].fov),
            Self::FixedPitch => t.fixed_pitch.as_mut(),
            Self::TiltStart => t.late_tilt.as_mut().map(|tilt| &mut tilt.tilt_start),
            Self::NearPitch => t.late_tilt.as_mut().map(|tilt| &mut tilt.near_pitch),
            Self::Wheel => Some(&mut t.wheel_step),
            Self::Easing => Some(&mut t.easing_rate),
            _ => None,
        }
    }
}

#[derive(Component)]
pub(super) struct CameraSliderFill;
#[derive(Component)]
pub(super) struct CameraSliderText;
#[derive(Component)]
pub(super) struct LateTiltRow;

fn slider(parent: &mut ChildSpawnerCommands, f: &Fonts, key: &str, control: CameraSlider) {
    parent.spawn((control, super::hit::Hot, Tag(format!("settings:camera_slider:{key}")),
        Node { width: Val::Px(112.0), height: Val::Px(24.0), align_items: AlignItems::Center, justify_content: JustifyContent::Center, overflow: Overflow::clip(), border_radius: wood::r(5.0), ..default() },
        BackgroundColor(wood::surface())))
        .with_children(|s| {
            s.spawn((CameraSliderFill, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), height: Val::Percent(100.0), ..default() },
                BackgroundColor(wood::line()), Pickable::IGNORE));
            s.spawn((CameraSliderText, Text::new(""), wood::ink(f, 13.0, 800), Pickable::IGNORE));
        });
}

fn camera_panel(pg: &mut ChildSpawnerCommands, f: &Fonts) {
    let presets = &crate::camera::Tuning::PRESETS;
    for (label, choices) in [("Our presets", &presets[..2]), ("Reference presets", &presets[2..])] {
        row(pg, f, label, "", |c| {
            for &(name, key, _) in choices {
                kit::button(c, f, name, &format!("settings:camera_preset:{key}"), true);
            }
        });
    }
    row(pg, f, "Pitch mode", "", |c| kit::seg(c, f, "settings:camera_pitch", &[
        ("Tilt curve", "curve"), ("Fixed pitch", "fixed"), ("Tilt near", "late"),
    ]));
    row(pg, f, "Zoom stops", "", |c| {
        for label in ["Far", "Middle", "Near"] {
            c.spawn((Text::new(label), wood::ink(f, 13.0, 800), Node { width: Val::Px(112.0), ..default() }, Pickable::IGNORE));
        }
    });
    for (label, key, field) in [
        ("Height (m)", "height", CameraSlider::Height as fn(usize) -> CameraSlider),
        ("Pitch (°)", "pitch", CameraSlider::Pitch),
        ("Vertical FOV (°)", "fov", CameraSlider::Fov),
    ] {
        row(pg, f, label, "", |c| {
            for (i, stop) in ["far", "middle", "near"].into_iter().enumerate() {
                slider(c, f, &format!("{key}:{stop}"), field(i));
            }
            if key == "pitch" {
                slider(c, f, "pitch:fixed", CameraSlider::FixedPitch);
            }
        });
    }
    for (label, key, slider_kind) in [
        ("Tilt start z", "tilt_start", CameraSlider::TiltStart),
        ("Near pitch (°)", "near_pitch", CameraSlider::NearPitch),
    ] {
        let entity = row_entity(pg, f, label, "", |c| slider(c, f, key, slider_kind));
        pg.commands().entity(entity).insert(LateTiltRow);
    }
    row(pg, f, "Wheel step", "", |c| slider(c, f, "wheel", CameraSlider::Wheel));
    row(pg, f, "Easing (per second)", "", |c| slider(c, f, "easing", CameraSlider::Easing));
    row(pg, f, "Export", "Writes camera-tuning.json beside the settings file", |c| {
        kit::button(c, f, "Copy values", "settings:camera_copy", true);
    });
}

pub(super) fn camera_controls(
    ui: Res<UiPointer>,
    tags: Query<&Tag>,
    mut prefs: ResMut<Prefs>,
    cam: Res<crate::camera::Cam>,
    mut clipboard: ResMut<bevy::clipboard::Clipboard>,
    mut sliders: Query<(Entity, &CameraSlider, &ComputedNode, &bevy::ui::UiGlobalTransform, &Children, &mut Node), Without<CameraSliderFill>>,
    mut fills: Query<&mut Node, (With<CameraSliderFill>, Without<LateTiltRow>)>,
    mut tilt_rows: Query<&mut Node, (With<LateTiltRow>, Without<CameraSlider>)>,
    mut texts: Query<&mut Text, With<CameraSliderText>>,
) {
    if sliders.is_empty() { return; }
    let active = ui.dropped.or_else(|| ui.down.zip(ui.pos).map(|((entity, _), pos)| (entity, pos)))
        .or_else(|| ui.clicked.zip(ui.pos));
    let mut tuning = prefs.camera_tuning;
    for mut node in &mut tilt_rows {
        let display = if tuning.late_tilt.is_some() { Display::Grid } else { Display::None };
        if node.display != display {
            node.display = display;
        }
    }
    for (entity, slider, measured, tf, children, mut node) in &mut sliders {
        let value = slider.value(&mut tuning);
        show(&mut node, value.is_some());
        let Some(value) = value else { continue };
        let (min, max, step) = slider.range();
        if let Some((_, pos)) = active.filter(|(e, _)| *e == entity && measured.size().x > 0.0) {
            let centre = tf.affine().translation.x;
            let t = ((pos.x * ui.scale - centre) / measured.size().x + 0.5).clamp(0.0, 1.0);
            *value = (((min + t * (max - min)) / step).round() * step).clamp(min, max);
        }
        for child in children.iter() {
            if let Ok(mut fill) = fills.get_mut(child) {
                fill.width = Val::Percent(100.0 * ((*value - min) / (max - min)).clamp(0.0, 1.0));
            }
            if let Ok(mut text) = texts.get_mut(child) {
                let digits = match slider {
                    CameraSlider::Wheel => 3,
                    CameraSlider::TiltStart => 2,
                    _ => 1,
                };
                set_text(&mut text, &format!("{value:.digits$}"));
            }
        }
    }
    if tuning != prefs.camera_tuning {
        prefs.camera_tuning = tuning;
        prefs.dirty = true;
    }
    if kit::clicked(&ui, &tags) == Some("settings:camera_copy") {
        let mut values = serde_json::json!(tuning);
        values["bearing"] = serde_json::json!(cam.shown_yaw.rem_euclid(360.0));
        let json = serde_json::to_string_pretty(&values).expect("camera tuning is serializable");
        if !crate::capture::headless() {
            if let Err(e) = clipboard.set_text(json.as_str()) {
                warn!("settings: could not copy camera values: {e}");
            }
        }
        let path = crate::keys::path().with_file_name("camera-tuning.json");
        let result = std::fs::create_dir_all(path.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(std::path::Path::new(".")))
            .and_then(|_| std::fs::write(&path, json));
        match result {
            Ok(()) => info!("settings: wrote camera values to {}", path.display()),
            Err(e) => warn!("settings: could not write {}: {e}", path.display()),
        }
    }
}

/// The settings file's Play settings, once at start, unless the environment sets them
/// (`LIVING_GAME_CONTROL`, `LIVING_SIGHT_EDGE`, `LIVING_GAME_LOOK_WALK`, `LIVING_GAME_FILM`,
/// `LIVING_GAME_HAIR_SHINE`, used by
/// headless captures).
pub fn apply_prefs(prefs: Res<Prefs>, mut input: ResMut<crate::controls::Input>, edge: Option<ResMut<crate::sightedge::SightEdge>>, mut lw: ResMut<crate::twist::LookWalk>, mut film: ResMut<crate::post::Film>, mut shine: ResMut<crate::style::HairShine>, mut done: Local<bool>) {
    if *done {
        return;
    }
    *done = true;
    if let (Some(p), true) = (prefs.look_walk.as_deref().and_then(|p| crate::twist::LookWalk::parse(p).ok()), std::env::var("LIVING_GAME_LOOK_WALK").is_err()) {
        *lw = p;
    }
    if std::env::var("LIVING_GAME_CONTROL").is_err() {
        input.control = prefs.control;
    }
    if let (Some(m), None) = (prefs.film.as_deref().and_then(crate::post::Film::parse), crate::post::Film::from_env()) {
        *film = m;
    }
    if let (Some(s), None) = (prefs.hair_shine.as_deref().and_then(crate::style::HairShine::parse), crate::style::HairShine::from_env()) {
        *shine = s;
    }
    let Some(mut e) = edge else { return };
    if let (Some(m), true) = (prefs.sight_edge.as_deref().and_then(crate::sightedge::Mode::parse), std::env::var("LIVING_SIGHT_EDGE").is_err()) {
        e.mode = m;
    }
    if let (Some(l), true) = (prefs.sight_look.as_deref().and_then(crate::sightedge::Look::parse), std::env::var("LIVING_SIGHT_LOOK").is_err()) {
        e.look = l;
    }
}

/// Heed's rows shown only while the world's laws let players heed (`heed::Heed::on`); right after
/// `spawn`, so a world without heed never draws them for a frame.
pub fn heed_only(heed: Option<Res<crate::heed::Heed>>, mut q: Query<(&mut Node, &HeedOnly)>) {
    let on = heed.is_some_and(|h| h.on);
    for (mut n, h) in &mut q {
        let d = if on { h.0 } else { Display::None };
        if n.display != d {
            n.display = d;
        }
    }
}
