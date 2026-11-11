//! Interface D's corner, top right: the compass with the place's name, and the two labelled
//! buttons, Pack (I) and Menu (Esc), with the Menu list under its button. Menu lists every
//! window: Character, Skills and know-how, Log and people, Settings, and Leave the world.
//!
//! - The compass turns with the view: its needle points north, the dots are the places my
//!   character knows, and the place's name under it is the nearest of those within
//!   [`PLACE_M`] (`my_places`: the rules' own record of what my character knows). With none,
//!   no name shows: the client never names a place the rules have not given.
//! - Character opens the list of acts on oneself until the character window is built (step 6).
//! - Leave the world asks once ("Leave? Click again"), then quits; the character stays in the
//!   world and is taken over by its mind after the takeover delay (docs/LIVING_CORE.md).

use super::hit::{Block, Hot, UiPointer};
use super::icons::{Glyph, Icons, Mark};
use super::model::HudModel;
use super::theme::Fonts;
use super::win::{Win, Windows, Z_MENU};
use super::{set_text, show, wood, HudRoot};
use bevy::prelude::*;
use bevy::ui::{BackgroundGradient, ColorStop, GlobalZIndex, Gradient, RadialGradient, RadialGradientShape, UiPosition, UiTransform};

/// A known place within this distance names where I am (m).
pub const PLACE_M: f32 = 90.0;
const SIZE: f32 = 128.0;
const DOTS: usize = 6;
/// Known places this far away (m) sit on the face's edge.
const RANGE: f32 = 320.0;

#[derive(Component)]
pub struct Needle;
#[derive(Component)]
pub struct North;
#[derive(Component)]
pub struct Dot(usize);
#[derive(Component)]
pub struct PlaceLabel;
#[derive(Component)]
pub struct PlaceText;
#[derive(Component)]
pub struct PackButton;
#[derive(Component)]
pub struct MenuButton;
#[derive(Component)]
pub struct ButtonTile(bool);
#[derive(Component)]
pub struct MenuList;
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Row {
    Character,
    Skills,
    Log,
    Settings,
    Leave,
}
#[derive(Component)]
pub struct MenuRow(Row);
#[derive(Component)]
pub struct LeaveText;

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>, icons: Res<Icons>) {
    let f = fonts.clone();
    // The compass.
    commands
        .spawn((
            HudRoot,
            Block,
            Node { position_type: PositionType::Absolute, right: Val::Px(26.0), top: Val::Px(18.0), width: Val::Px(SIZE), height: Val::Px(SIZE), border: UiRect::all(Val::Px(3.0)), border_radius: BorderRadius::all(Val::Percent(50.0)), ..default() },
            BackgroundGradient::from(Gradient::Radial(RadialGradient {
                position: UiPosition::CENTER,
                shape: RadialGradientShape::ClosestSide,
                stops: vec![ColorStop::percent(Color::srgb_u8(0xfb, 0xef, 0xcf), 0.0), ColorStop::percent(Color::srgb_u8(0xfb, 0xef, 0xcf), 74.0), ColorStop::percent(Color::srgb_u8(0xea, 0xd7, 0xab), 75.0), ColorStop::percent(Color::srgb_u8(0xea, 0xd7, 0xab), 88.0), ColorStop::percent(wood::WAL, 89.0), ColorStop::percent(wood::WAL2, 100.0)],
                color_space: default(),
            })),
            BorderColor::all(wood::INK),
            wood::hard_shadow(5.0, 0.45),
            GlobalZIndex(20),
        ))
        .with_children(|c| {
            let inner = SIZE - 6.0;
            c.spawn((Node { position_type: PositionType::Absolute, left: Val::Px(9.0), top: Val::Px(9.0), width: Val::Px(inner - 18.0), height: Val::Px(inner - 18.0), border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Percent(50.0)), ..default() }, BorderColor::all(wood::BRASS), Pickable::IGNORE));
            for i in 0..DOTS {
                c.spawn((Dot(i), Node { position_type: PositionType::Absolute, width: Val::Px(9.0), height: Val::Px(9.0), border: UiRect::all(Val::Px(1.5)), border_radius: BorderRadius::all(Val::Percent(50.0)), display: Display::None, ..default() }, BackgroundColor(Color::srgb_u8(0x5f, 0xa8, 0x4a)), BorderColor::all(wood::INK), Pickable::IGNORE));
            }
            c.spawn((Needle, Node { position_type: PositionType::Absolute, left: Val::Px(inner / 2.0 - 22.0), top: Val::Px(inner / 2.0 - 44.0), width: Val::Px(44.0), height: Val::Px(88.0), ..default() }, UiTransform::default(), Pickable::IGNORE)).with_children(|n| {
                // An ink shape a little larger, then the north half red and the south half cream.
                for (mark, col, inset) in [(Mark::Needle, wood::INK, 0.0), (Mark::NeedleS, wood::INK, 0.0), (Mark::Needle, wood::HOSTILE, 4.0), (Mark::NeedleS, wood::CREAM, 4.0)] {
                    n.spawn((Node { position_type: PositionType::Absolute, left: Val::Px(inset), top: Val::Px(inset), width: Val::Px(44.0 - 2.0 * inset), height: Val::Px(88.0 - 2.0 * inset), ..default() }, ImageNode::new(icons.get(Glyph::Ui(mark))).with_color(col), Pickable::IGNORE));
                }
                n.spawn((Node { position_type: PositionType::Absolute, left: Val::Px(18.5), top: Val::Px(40.5), width: Val::Px(7.0), height: Val::Px(7.0), border_radius: BorderRadius::all(Val::Percent(50.0)), ..default() }, BackgroundColor(wood::INK), Pickable::IGNORE));
            });
            c.spawn((North, Node { position_type: PositionType::Absolute, width: Val::Px(16.0), height: Val::Px(16.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, ..default() }, Pickable::IGNORE))
                .with_child((Text::new("N"), f.title(13.0), TextColor(wood::INK), Pickable::IGNORE));
        });
    // The place's name.
    commands
        .spawn((
            HudRoot,
            PlaceLabel,
            Block,
            Node { position_type: PositionType::Absolute, right: Val::Px(22.0), top: Val::Px(152.0), width: Val::Px(136.0), padding: UiRect::new(Val::Px(4.0), Val::Px(4.0), Val::Px(2.0), Val::Px(3.0)), justify_content: JustifyContent::Center, border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(8.0)), display: Display::None, ..default() },
            BackgroundColor(wood::PARCH),
            BorderColor::all(wood::INK),
            wood::hard_shadow(3.0, 0.4),
            GlobalZIndex(20),
        ))
        .with_child((PlaceText, Text::new(""), f.title(14.0), TextColor(wood::INK), TextLayout::justify(Justify::Center), Pickable::IGNORE));
    // Pack and Menu.
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, right: Val::Px(22.0), top: Val::Px(186.0), flex_direction: FlexDirection::Row, column_gap: Val::Px(8.0), ..default() }, GlobalZIndex(20), Pickable::IGNORE))
        .with_children(|row| {
            button(row, &f, &icons, Mark::Pack, "Pack", "I", (PackButton, super::hit::Tag("pack".into())));
            button(row, &f, &icons, Mark::Dots, "Menu", "Esc", (MenuButton, super::hit::Tag("menu".into())));
        });
    // The Menu list.
    commands
        .spawn((
            HudRoot,
            MenuList,
            Block,
            Node { position_type: PositionType::Absolute, right: Val::Px(22.0), top: Val::Px(238.0), width: Val::Px(220.0), flex_direction: FlexDirection::Column, padding: UiRect::new(Val::Px(0.0), Val::Px(0.0), Val::Px(4.0), Val::Px(8.0)), border: UiRect::all(Val::Px(3.0)), border_radius: BorderRadius::all(Val::Px(12.0)), display: Display::None, ..default() },
            wood::wood(),
            GlobalZIndex(Z_MENU),
        ))
        .with_children(|m| {
            m.spawn(wood::rim(9.0));
            m.spawn((Node { flex_direction: FlexDirection::Row, justify_content: JustifyContent::SpaceBetween, align_items: AlignItems::Center, padding: UiRect::new(Val::Px(12.0), Val::Px(10.0), Val::Px(4.0), Val::Px(5.0)), ..default() }, Pickable::IGNORE)).with_children(|h| {
                h.spawn((Text::new("Menu"), wood::title(&f, 17.0), Pickable::IGNORE));
                h.spawn((Text::new("Esc"), wood::on_wood(&f, 11.0, 700), Pickable::IGNORE));
            });
            let rows: [(Row, Mark, &str, Option<&str>); 5] = [(Row::Character, Mark::Person, "Character", Some("C")), (Row::Skills, Mark::Book, "Skills and know-how", Some("K")), (Row::Log, Mark::Scroll, "Log and people", Some("L")), (Row::Settings, Mark::Gear, "Settings", None), (Row::Leave, Mark::Leave, "Leave the world", None)];
            m.spawn((Node { flex_direction: FlexDirection::Column, margin: UiRect::horizontal(Val::Px(6.0)), border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(8.0)), overflow: Overflow::clip(), ..default() }, BackgroundColor(wood::PARCH), BorderColor::all(wood::INK), Pickable::IGNORE)).with_children(|list| {
                for (r, mark, label, key) in rows {
                    list.spawn((MenuRow(r), Hot, super::hit::Tag(format!("menu:{r:?}")), Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(10.0), padding: UiRect::axes(Val::Px(10.0), Val::Px(6.0)), ..default() }, BackgroundGradient::default())).with_children(|row| {
                        row.spawn(wood::icon(&icons, Glyph::Ui(mark), 16.0, Color::srgb_u8(0xb9, 0x7b, 0x35)));
                        let mut t = row.spawn((Text::new(label), wood::ink(&f, 15.0, 800), Node { flex_grow: 1.0, ..default() }, Pickable::IGNORE));
                        if r == Row::Leave {
                            t.insert(LeaveText);
                        }
                        if let Some(k) = key {
                            wood::chip(row, &f, k, ());
                        }
                    });
                }
            });
        });
}

/// A labelled button on walnut: an icon tile, its word and its key.
fn button(p: &mut ChildSpawnerCommands, f: &Fonts, icons: &Icons, mark: Mark, label: &str, key: &str, marker: impl Bundle) {
    p.spawn((marker, Hot, Block, Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(7.0), padding: UiRect::new(Val::Px(6.0), Val::Px(10.0), Val::Px(5.0), Val::Px(5.0)), border: UiRect::all(Val::Px(3.0)), border_radius: BorderRadius::all(Val::Px(10.0)), ..default() }, wood::wood()))
        .with_children(|b| {
            b.spawn(wood::rim(7.0));
            b.spawn((ButtonTile(mark == Mark::Pack), Node { width: Val::Px(30.0), height: Val::Px(30.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(8.0)), ..default() }, wood::tile(false), BorderColor::all(wood::INK), Pickable::IGNORE))
                .with_child(wood::icon(icons, Glyph::Ui(mark), 18.0, Color::srgb_u8(0xc9, 0x8b, 0x3c)));
            b.spawn((Text::new(label), f.body(14.0, 800), TextColor(wood::PARCH), Pickable::IGNORE));
            wood::chip(b, f, key, ());
        });
}

/// Clicks on the buttons and the Menu's rows.
#[allow(clippy::too_many_arguments)]
pub fn clicks(ui: Res<UiPointer>, mut ws: ResMut<Windows>, pack: Query<(), With<PackButton>>, menu: Query<(), With<MenuButton>>, rows: Query<&MenuRow>, lists: Query<(), With<MenuList>>, mut verbs: ResMut<crate::verbs::Verbs>, mut exit: MessageWriter<AppExit>) {
    if let Some(e) = ui.clicked {
        if pack.contains(e) {
            ws.toggle(Win::Pack);
        } else if menu.contains(e) {
            ws.menu = !ws.menu;
            ws.leaving = false;
        } else if let Ok(r) = rows.get(e) {
            match r.0 {
                Row::Leave if ws.leaving => {
                    info!("ui: leaving the world");
                    exit.write(AppExit::Success);
                }
                Row::Leave => ws.leaving = true,
                other => {
                    ws.menu = false;
                    ws.leaving = false;
                    match other {
                        Row::Character => verbs.open_self = true,
                        Row::Skills => ws.open(Win::Skills),
                        Row::Log => ws.open(Win::Log),
                        Row::Settings => ws.open(Win::Settings),
                        Row::Leave => {}
                    }
                }
            }
        }
    }
    // A press anywhere else closes the Menu list.
    if ws.menu && ui.pressed_elsewhere {
        ws.menu = false;
        ws.leaving = false;
    }
    if ws.menu {
        if let Some((e, _)) = ui.down {
            if !menu.contains(e) && !rows.contains(e) && !lists.contains(e) {
                ws.menu = false;
                ws.leaving = false;
            }
        }
    }
}

#[allow(clippy::type_complexity)]
pub fn update(
    model: Res<HudModel>,
    ws: Res<Windows>,
    ui: Res<UiPointer>,
    mut needle: Query<&mut UiTransform, With<Needle>>,
    mut north: Query<&mut Node, (With<North>, Without<Dot>, Without<PlaceLabel>, Without<MenuList>)>,
    mut dots: Query<(&Dot, &mut Node), (Without<North>, Without<PlaceLabel>, Without<MenuList>)>,
    mut label: Query<&mut Node, (With<PlaceLabel>, Without<North>, Without<Dot>, Without<MenuList>)>,
    mut place: Query<&mut Text, (With<PlaceText>, Without<LeaveText>)>,
    mut list: Query<&mut Node, (With<MenuList>, Without<North>, Without<Dot>, Without<PlaceLabel>)>,
    mut tiles: Query<(&ButtonTile, &mut BackgroundGradient), Without<MenuRow>>,
    mut rows: Query<(Entity, &mut BackgroundGradient), (With<MenuRow>, Without<ButtonTile>)>,
    mut leave: Query<&mut Text, (With<LeaveText>, Without<PlaceText>)>,
) {
    let m = &model.map;
    let y = m.yaw.to_radians();
    let (up, right) = (Vec2::new(y.sin(), -y.cos()), Vec2::new(y.cos(), y.sin()));
    let to_screen = |d: Vec2| Vec2::new(d.dot(right), -d.dot(up));
    let n = to_screen(Vec2::new(0.0, -1.0));
    let rot = Rot2::radians(n.x.atan2(-n.y));
    for mut t in &mut needle {
        if t.rotation != rot {
            t.rotation = rot;
        }
    }
    let c = (SIZE - 6.0) / 2.0;
    let put = |node: &mut Node, p: Vec2, half: f32| {
        let (l, t) = (Val::Px((c + p.x - half).round()), Val::Px((c + p.y - half).round()));
        if node.left != l {
            node.left = l;
        }
        if node.top != t {
            node.top = t;
        }
    };
    for mut node in &mut north {
        put(&mut node, n * 47.0, 8.0);
    }
    let me = m.me.unwrap_or_default();
    let mut near: Vec<(Vec2, f32)> = m.pois.iter().map(|p| (p.at, p.at.distance(me))).collect();
    near.sort_by(|a, b| a.1.total_cmp(&b.1));
    for (d, mut node) in &mut dots {
        let Some((at, dist)) = near.get(d.0).filter(|_| m.me.is_some()) else {
            show(&mut node, false);
            continue;
        };
        show(&mut node, true);
        let r = (dist / RANGE).min(1.0) * 38.0;
        put(&mut node, to_screen((*at - me).normalize_or_zero()) * r, 4.5);
    }
    for mut node in &mut label {
        show(&mut node, m.place.is_some());
    }
    if let Some(p) = &m.place {
        for mut t in &mut place {
            set_text(&mut t, p);
        }
    }
    for mut node in &mut list {
        show(&mut node, ws.menu);
    }
    for (b, mut g) in &mut tiles {
        let on = if b.0 { ws.is_open(Win::Pack) } else { ws.menu };
        let want = wood::tile(on);
        if *g != want {
            *g = want;
        }
    }
    for (e, mut g) in &mut rows {
        // A hot row is a gradient; a plain one has none (cheap to compare).
        let over = ui.is_over(e);
        if over == g.0.is_empty() {
            *g = if over { wood::hot_row() } else { BackgroundGradient::default() };
        }
    }
    for mut t in &mut leave {
        set_text(&mut t, if ws.leaving { "Leave? Click again" } else { "Leave the world" });
    }
}
