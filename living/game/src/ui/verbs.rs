//! The verbs' UI (`verbs.rs`): the F hint, the list of acts, the notes of what the authority
//! said, and the inventory (I) and know-how (K) panels. All hidden until they matter
//! (docs/GAME_BRIEF.md, HUD: only relevant information on screen).
//!
//! - The list sits over the bar, numbered 1–9 and 0; a click picks any row.
//! - Notes rise just over the hint and fade, edged green when done, red when refused (the
//!   authority's reason), grey when begun.
//! - The inventory lists what I carry; clicking an item lists what I can do with it myself.
//! - Know-how: the techniques I know (and how I came by them), then every skill in the rules,
//!   with what the selected one takes and gives (the world's `skill_io`). Up/Down or a click
//!   selects.

use super::model::*;
use super::theme::{self, Fonts};
use super::{label, set_bg, set_color, set_text, show, HudRoot};
use crate::net::Net;
use crate::verbs::{Row, Rules, Verbs};
use bevy::picking::events::{PointerClick, PointerOver};
use bevy::prelude::*;
use living_bindings::*;
use spacetimedb_sdk::Table;

const MENU_ROWS: usize = 16;
const TOASTS: usize = 3;
const INV_ROWS: usize = 18;
const SKILL_ROWS: usize = 14;

#[derive(Component)]
pub struct MenuRoot;
#[derive(Component)]
pub struct MenuTitle;
#[derive(Component)]
pub struct MenuRow(usize);
#[derive(Component)]
pub struct MenuText(usize);
#[derive(Component)]
pub struct ToastRow(usize);
#[derive(Component)]
pub struct ToastText(usize);
#[derive(Component)]
pub struct InvRoot;
#[derive(Component)]
pub struct InvHead;
#[derive(Component)]
pub struct InvRow(usize);
#[derive(Component)]
pub struct InvText(usize);
/// A pack row's count and its worth as food, right-aligned beside the name.
#[derive(Component)]
pub struct InvQty(usize);
#[derive(Component)]
pub struct InvNote(usize);
/// How much of what I can carry I carry.
#[derive(Component)]
pub struct InvCarry;
#[derive(Component)]
pub struct KnowRoot;
#[derive(Component)]
pub struct KnowTech;
#[derive(Component)]
pub struct KnowRow(usize);
#[derive(Component)]
pub struct KnowText(usize);
#[derive(Component)]
pub struct KnowDetail(u8);

/// The first skill shown in the know-how list (a window round the selected one).
fn window_start(selected: usize, n: usize) -> usize {
    selected.saturating_sub(SKILL_ROWS / 2).min(n.saturating_sub(SKILL_ROWS))
}

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = fonts.clone();
    // The list, over the bar.
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), bottom: Val::Px(262.0), justify_content: JustifyContent::Center, ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            root.spawn((MenuRoot, Node { min_width: Val::Px(240.0), max_width: Val::Px(380.0), flex_direction: FlexDirection::Column, row_gap: Val::Px(2.0), padding: UiRect::new(Val::Px(8.0), Val::Px(8.0), Val::Px(7.0), Val::Px(8.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(12.0)), display: Display::None, ..default() }, theme::panel(12.0)))
                .with_children(|m| {
                    m.spawn((MenuTitle, Text::new(""), f.title(17.0), TextColor(theme::GOLD), Node { margin: UiRect::new(Val::Px(6.0), Val::Px(6.0), Val::Px(1.0), Val::Px(4.0)), ..default() }, Pickable::IGNORE));
                    m.spawn((Node { height: Val::Px(1.0), margin: UiRect::new(Val::Px(6.0), Val::Px(6.0), Val::Px(0.0), Val::Px(4.0)), ..default() }, BackgroundColor(theme::GOLD_DIM), Pickable::IGNORE));
                    for i in 0..MENU_ROWS {
                        m.spawn((MenuRow(i), Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(9.0), padding: UiRect::axes(Val::Px(6.0), Val::Px(3.0)), border_radius: BorderRadius::all(Val::Px(7.0)), ..default() }, BackgroundColor(Color::NONE)))
                            .with_children(|r| {
                                r.spawn((Node { width: Val::Px(18.0), height: Val::Px(18.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(5.0)), ..default() }, BackgroundColor(theme::INK_SOLID), BorderColor::all(theme::EDGE_STRONG), Pickable::IGNORE))
                                    .with_child((Text::new(if i < 9 { format!("{}", i + 1) } else if i == 9 { "0".into() } else { String::new() }), f.body(11.0, 800), TextColor(theme::TEXT), Pickable::IGNORE));
                                r.spawn((MenuText(i), Text::new(""), f.body(15.0, 650), TextColor(theme::TEXT), Pickable::IGNORE));
                            })
                            .observe(move |_: On<PointerClick>, mut v: ResMut<Verbs>| v.clicked = Some(i))
                            .observe(move |_: On<PointerOver>, mut q: Query<(&MenuRow, &mut BackgroundColor)>| {
                                for (r, mut bg) in &mut q {
                                    set_bg(&mut bg, if r.0 == i { theme::with_alpha(theme::GOLD, 0.16) } else { Color::NONE });
                                }
                            });
                    }
                });
        });
    // Notes, just over the hint.
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), bottom: Val::Px(214.0), flex_direction: FlexDirection::ColumnReverse, align_items: AlignItems::Center, row_gap: Val::Px(4.0), ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            for i in 0..TOASTS {
                root.spawn((ToastRow(i), Node { padding: UiRect::axes(Val::Px(12.0), Val::Px(4.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(999.0)), max_width: Val::Px(560.0), display: Display::None, ..default() }, theme::panel(999.0), Pickable::IGNORE))
                    .with_child((ToastText(i), Text::new(""), f.body(14.0, 650), TextColor(theme::TEXT), Pickable::IGNORE));
            }
        });
    // Inventory, right.
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, right: Val::Px(22.0), top: Val::Percent(24.0), ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            root.spawn((InvRoot, Node { width: Val::Px(230.0), flex_direction: FlexDirection::Column, row_gap: Val::Px(1.0), padding: UiRect::new(Val::Px(10.0), Val::Px(10.0), Val::Px(8.0), Val::Px(9.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(12.0)), display: Display::None, ..default() }, theme::panel(12.0)))
                .with_children(|p| {
                    p.spawn((InvHead, Text::new("Pack"), f.title(17.0), TextColor(theme::GOLD), Node { margin: UiRect::bottom(Val::Px(4.0)), ..default() }, Pickable::IGNORE));
                    p.spawn((Node { height: Val::Px(4.0), margin: UiRect::bottom(Val::Px(6.0)), border_radius: BorderRadius::all(Val::Px(2.0)), overflow: Overflow::clip(), ..default() }, BackgroundColor(theme::TRACK), Pickable::IGNORE))
                        .with_child((InvCarry, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(0.0), ..default() }, BackgroundColor(theme::GOLD_DIM), Pickable::IGNORE));
                    for i in 0..INV_ROWS {
                        p.spawn((InvRow(i), Node { padding: UiRect::axes(Val::Px(5.0), Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(6.0)), justify_content: JustifyContent::SpaceBetween, align_items: AlignItems::Center, column_gap: Val::Px(8.0), ..default() }, BackgroundColor(Color::NONE)))
                            .with_children(|r| {
                                r.spawn((InvText(i), Text::new(""), f.body(14.0, 600), TextColor(theme::TEXT), Pickable::IGNORE));
                                r.spawn((Node { column_gap: Val::Px(8.0), align_items: AlignItems::Center, ..default() }, Pickable::IGNORE)).with_children(|right| {
                                    right.spawn((InvNote(i), Text::new(""), f.body(12.0, 600), TextColor(theme::MUTED), Pickable::IGNORE));
                                    right.spawn((InvQty(i), Text::new(""), f.body(14.0, 800), TextColor(theme::GOLD), Pickable::IGNORE));
                                });
                            })
                            .observe(move |_: On<PointerClick>, model: Res<HudModel>, mut v: ResMut<Verbs>| {
                                if let Some(r) = model.verbs.inventory.as_ref().and_then(|inv| inv.rows.get(i)) {
                                    v.clicked_item = Some(r.0.clone());
                                }
                            });
                    }
                });
        });
    // Know-how, left.
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(22.0), top: Val::Percent(14.0), ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            root.spawn((KnowRoot, Node { width: Val::Px(420.0), flex_direction: FlexDirection::Column, row_gap: Val::Px(1.0), padding: UiRect::new(Val::Px(12.0), Val::Px(12.0), Val::Px(9.0), Val::Px(11.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(12.0)), display: Display::None, ..default() }, theme::panel(12.0)))
                .with_children(|p| {
                    p.spawn((Text::new("Know-how"), f.title(17.0), TextColor(theme::GOLD), Pickable::IGNORE));
                    p.spawn((KnowTech, Text::new(""), f.body(13.0, 600), TextColor(theme::MUTED), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { margin: UiRect::vertical(Val::Px(4.0)), ..default() }, Pickable::IGNORE));
                    p.spawn(Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(12.0), ..default() }).with_children(|cols| {
                        cols.spawn(Node { width: Val::Px(120.0), flex_direction: FlexDirection::Column, ..default() }).with_children(|list| {
                            for i in 0..SKILL_ROWS {
                                list.spawn((KnowRow(i), Node { padding: UiRect::axes(Val::Px(5.0), Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(5.0)), ..default() }, BackgroundColor(Color::NONE)))
                                    .with_child((KnowText(i), Text::new(""), f.body(13.0, 650), TextColor(theme::TEXT), Pickable::IGNORE))
                                    .observe(move |_: On<PointerClick>, model: Res<HudModel>, mut v: ResMut<Verbs>| {
                                        if let Some(k) = model.verbs.know_how.as_ref() {
                                            v.selected = k.start + i;
                                        }
                                    });
                            }
                        });
                        cols.spawn(Node { flex_grow: 1.0, flex_basis: Val::Px(0.0), flex_direction: FlexDirection::Column, row_gap: Val::Px(5.0), ..default() }).with_children(|d| {
                            d.spawn((KnowDetail(0), Text::new(""), f.body(16.0, 800), TextColor(theme::TEXT), Pickable::IGNORE));
                            d.spawn((KnowDetail(1), Text::new(""), f.body(13.0, 550), TextColor(theme::MUTED), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                            d.spawn((KnowDetail(2), Text::new(""), f.body(13.0, 600), TextColor(theme::TEXT), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                            d.spawn((KnowDetail(3), Text::new(""), f.body(13.0, 600), TextColor(theme::FRIENDLY), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                        });
                    });
                });
        });
}

/// Fill the verbs' part of the model: the hint, the list, the notes and the panels.
pub fn fill(mut model: ResMut<HudModel>, v: Res<Verbs>, rules: NonSend<Rules>, net: NonSend<Net>, time: Res<Time>) {
    let now = time.elapsed_secs_f64();
    model.verbs.toasts = v.toasts.iter().rev().map(|t| (t.text.clone(), t.ok, (now - t.at) as f32)).collect();
    model.verbs.menu = v.menu.as_ref().map(|m| {
        let rows = m.rows().into_iter().take(MENU_ROWS).map(|r| match r {
            Row::Pick(c) => label(&c.label),
            Row::Group { label: l, .. } => label(&l),
        });
        let title = match (&m.group, &m.item) {
            (Some(g), _) => format!("{} · {}", label(&m.title), label(g)),
            (None, Some(i)) => format!("{} · {}", label(&m.title), label(i)),
            _ => label(&m.title),
        };
        MenuView { title, rows: rows.collect() }
    });
    if model.death.is_none() && v.menu.is_none() && v.compose.is_none() {
        if let Some(c) = &v.likely {
            model.hint = Some(Hint { key: "F".into(), label: label(&c.label) });
        } else if v.aim.is_some() && v.has_options {
            model.hint = Some(Hint { key: "F".into(), label: format!("{} ▸", label(&v.aim_name)) });
        }
    }
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else {
        model.verbs.inventory = None;
        model.verbs.know_how = None;
        return;
    };
    let sc = rules.scripts.as_ref();
    model.verbs.inventory = v.inventory.then(|| {
        let mut rows: Vec<(String, u32, String)> = Vec::new();
        for r in conn.db.my_inventory().iter().filter(|r| r.owner == me as u64 && r.qty > 0) {
            match rows.iter_mut().find(|(k, _, _)| *k == r.item) {
                Some((_, n, _)) => *n += r.qty,
                None => rows.push((r.item.clone(), r.qty, String::new())),
            }
        }
        rows.sort_by(|a, b| a.0.cmp(&b.0));
        for r in &mut rows {
            // What the rules say it is worth as food.
            let food = sc.map_or(0.0, |s| s.num_of("nutrition", &r.0, 0.0));
            if food > 0.0 {
                r.2 = format!("food {food:.0}");
            }
        }
        let carried = rows.iter().map(|r| r.1).sum();
        let kind = conn.db.my_characters().id().find(&me).map_or("person".to_string(), |c| c.kind);
        let limit = sc.map_or(0.0, |s| s.num_of("carry_limit", &kind, 0.0)) as u32;
        InventoryView { rows, carried, limit }
    });
    model.verbs.know_how = v.know_how.then(|| {
        let techniques = conn.db.my_know_how().iter().filter(|k| k.actor == me).map(|k| (k.technique, k.source)).collect();
        // Every skill the world's rules have.
        let all = &rules.skills;
        let n = all.len();
        let selected = v.selected.min(n.saturating_sub(1));
        let start = window_start(selected, n);
        let skills = all.iter().skip(start).take(SKILL_ROWS).map(|s| label(&s.name)).collect();
        let detail = all.get(selected).map_or_else(SkillDetail::default, |spec| {
            let (takes, gives) = sc.and_then(|s| s.skill_io(&spec.name)).unwrap_or_default();
            SkillDetail { name: label(&spec.name), help: spec.help.clone(), takes, gives }
        });
        KnowHowView { techniques, skills, selected, start, detail }
    });
}

#[allow(clippy::type_complexity)]
pub fn menu(
    model: Res<HudModel>,
    mut root: Query<&mut Node, (With<MenuRoot>, Without<MenuRow>)>,
    mut title: Query<&mut Text, (With<MenuTitle>, Without<MenuText>)>,
    mut rows: Query<(&MenuRow, &mut Node), Without<MenuRoot>>,
    mut texts: Query<(&MenuText, &mut Text), Without<MenuTitle>>,
) {
    let m = model.verbs.menu.as_ref().filter(|_| model.death.is_none());
    for mut n in &mut root {
        show(&mut n, m.is_some());
    }
    let Some(m) = m else { return };
    for mut t in &mut title {
        set_text(&mut t, &m.title);
    }
    for (r, mut n) in &mut rows {
        show(&mut n, r.0 < m.rows.len());
    }
    for (r, mut t) in &mut texts {
        if let Some(s) = m.rows.get(r.0) {
            set_text(&mut t, s);
        }
    }
}

#[allow(clippy::type_complexity)]
pub fn toasts(model: Res<HudModel>, mut rows: Query<(&ToastRow, &mut Node, &mut BackgroundColor, &mut BorderColor)>, mut texts: Query<(&ToastText, &mut Text, &mut TextColor)>) {
    let t = &model.verbs.toasts;
    // Fade over the last second.
    let alpha = |age: f32| (4.5 - age).clamp(0.0, 1.0);
    for (r, mut n, mut bg, mut border) in &mut rows {
        let on = r.0 < t.len() && model.death.is_none();
        show(&mut n, on);
        if let Some((_, ok, age)) = t.get(r.0) {
            set_bg(&mut bg, theme::with_alpha(theme::INK, alpha(*age)));
            let edge = match ok {
                Some(true) => theme::FRIENDLY,
                Some(false) => theme::HOSTILE,
                None => theme::EDGE_STRONG,
            };
            let c = theme::with_alpha(edge, 0.7 * alpha(*age));
            if border.top != c {
                *border = BorderColor::all(c);
            }
        }
    }
    for (r, mut text, mut color) in &mut texts {
        if let Some((s, ok, age)) = t.get(r.0) {
            // Done or refused shows in the edge's colour; the words are the authority's.
            let _ = ok;
            set_text(&mut text, s);
            set_color(&mut color, theme::with_alpha(theme::TEXT, alpha(*age)));
        }
    }
}

#[allow(clippy::type_complexity)]
pub fn panels(
    model: Res<HudModel>,
    mut nodes: ParamSet<(Query<&mut Node, With<InvRoot>>, Query<(&InvRow, &mut Node)>, Query<&mut Node, With<KnowRoot>>, Query<(&KnowRow, &mut Node, &mut BackgroundColor)>)>,
    mut texts: ParamSet<(Query<&mut Text, With<InvHead>>, Query<(&InvText, &mut Text)>, Query<&mut Text, With<KnowTech>>, Query<(&KnowText, &mut Text)>, Query<(&KnowDetail, &mut Text)>, Query<(&InvQty, &mut Text)>, Query<(&InvNote, &mut Text)>)>,
    mut carry: Query<&mut Node, (With<InvCarry>, Without<InvRoot>, Without<InvRow>, Without<KnowRoot>, Without<KnowRow>)>,
) {
    let alive = model.death.is_none();
    let inv = model.verbs.inventory.as_ref().filter(|_| alive);
    for mut n in &mut nodes.p0() {
        show(&mut n, inv.is_some());
    }
    if let Some(inv) = inv {
        for (r, mut n) in &mut nodes.p1() {
            show(&mut n, r.0 < inv.rows.len().max(1));
        }
        for mut t in &mut texts.p0() {
            let head = if inv.limit > 0 { format!("Pack  {} / {}", inv.carried, inv.limit) } else { format!("Pack  {}", inv.carried) };
            set_text(&mut t, &head);
        }
        for mut n in &mut carry {
            super::set_width(&mut n, Val::Percent(if inv.limit > 0 { (inv.carried as f32 / inv.limit as f32).clamp(0.0, 1.0) * 100.0 } else { 0.0 }));
        }
        for (r, mut t) in &mut texts.p1() {
            let s = match inv.rows.get(r.0) {
                Some((item, _, _)) => label(item),
                None if r.0 == 0 => "Nothing".to_string(),
                None => String::new(),
            };
            set_text(&mut t, &s);
        }
        for (r, mut t) in &mut texts.p5() {
            set_text(&mut t, &inv.rows.get(r.0).map_or(String::new(), |(_, n, _)| format!("×{n}")));
        }
        for (r, mut t) in &mut texts.p6() {
            set_text(&mut t, &inv.rows.get(r.0).map_or(String::new(), |(_, _, note)| note.clone()));
        }
    }
    let know = model.verbs.know_how.as_ref().filter(|_| alive);
    for mut n in &mut nodes.p2() {
        show(&mut n, know.is_some());
    }
    let Some(k) = know else { return };
    let start = k.start;
    for (r, mut n, mut bg) in &mut nodes.p3() {
        show(&mut n, r.0 < k.skills.len());
        set_bg(&mut bg, if start + r.0 == k.selected { theme::with_alpha(theme::GOLD, 0.18) } else { Color::NONE });
    }
    for mut t in &mut texts.p2() {
        // How a newcomer's own techniques came is no news; a technique learnt says from whom.
        let s = if k.techniques.is_empty() { "You know no techniques yet.".to_string() } else { format!("You know  {}", k.techniques.iter().map(|(t, src)| if src.is_empty() || src == "seed" || src.contains("newcomer") { label(t) } else { format!("{} ({src})", label(t)) }).collect::<Vec<_>>().join(" · ")) };
        set_text(&mut t, &s);
    }
    for (r, mut t) in &mut texts.p3() {
        if let Some(s) = k.skills.get(r.0) {
            set_text(&mut t, s);
        }
    }
    for (d, mut t) in &mut texts.p4() {
        let s = match d.0 {
            0 => k.detail.name.clone(),
            1 => k.detail.help.clone(),
            2 => if k.detail.takes.is_empty() { String::new() } else { format!("Takes: {}", k.detail.takes) },
            _ => if k.detail.gives.is_empty() { String::new() } else { format!("Gives: {}", k.detail.gives) },
        };
        set_text(&mut t, &s);
    }
}
