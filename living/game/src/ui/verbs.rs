//! The verbs' UI in interface D (`verbs.rs` decides what is offered; this draws it): the list of
//! acts and the notes of what the authority said of my acts.
//!
//! - **The list** (hold F on something, C on oneself, a click on a pack item) sits beside its
//!   target's head, or beside the pack cell it was opened from: a walnut frame with the target's
//!   name over parchment rows, each with its icon and key. Toward a person it starts with Talk
//!   and Their window. A skill with many items ("Give ›") opens its own list beside
//!   it ("from your pack"). A click or 1–9 picks a row; Esc closes the sub-list, then the list.
//! - **Notes** rise over the cluster and fade: parchment, marked green when done, red when
//!   refused (the authority's reason), plain when begun.

use super::hit::{Block, Hot, Tag, UiPointer};
use super::icons::{Glyph, Icons, Mark};
use super::kit::{self, Lit};
use super::model::*;
use super::theme::Fonts;
use super::win::Z_LIST;
use super::{label, set_text, show, wood, HudRoot};
use crate::net::Net;
use crate::verbs::{Row, Rules, Verbs};
use bevy::prelude::*;
use bevy::ui::{BackgroundGradient, GlobalZIndex};
use living_bindings::*;
use spacetimedb_sdk::Table;

const ROWS: usize = 18;
const TOASTS: usize = 3;

#[derive(Component)]
pub struct ListRoot(u8);
#[derive(Component)]
pub struct ListTitle(u8);
#[derive(Component)]
pub struct ListNote(u8);
#[derive(Component)]
pub struct ListRow(u8, usize);
#[derive(Component)]
pub struct ListIcon(u8, usize);
#[derive(Component)]
pub struct ListText(u8, usize);
#[derive(Component)]
pub struct ListKey(u8, usize);
#[derive(Component)]
pub struct ListKeyText(u8, usize);
#[derive(Component)]
pub struct ListMore(u8, usize);
#[derive(Component)]
pub struct ToastRow(usize);
#[derive(Component)]
pub struct ToastMark(usize);
#[derive(Component)]
pub struct ToastText(usize);

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>, icons: Res<Icons>) {
    let f = &*fonts;
    // The list (0) and its sub-list (1).
    for k in 0..2u8 {
        commands
            .spawn((HudRoot, ListRoot(k), Block, Node { position_type: PositionType::Absolute, width: Val::Px(if k == 0 { 250.0 } else { 196.0 }), flex_direction: FlexDirection::Column, padding: UiRect::bottom(Val::Px(6.0)), border: wood::b(3.0), border_radius: wood::r(12.0), display: Display::None, ..default() }, wood::wood(), GlobalZIndex(Z_LIST)))
            .with_children(|m| {
                m.spawn(wood::rim(9.0));
                m.spawn((Node { flex_direction: FlexDirection::Row, justify_content: JustifyContent::SpaceBetween, align_items: AlignItems::Baseline, padding: UiRect::new(Val::Px(12.0), Val::Px(10.0), Val::Px(6.0), Val::Px(5.0)), column_gap: Val::Px(8.0), ..default() }, Pickable::IGNORE)).with_children(|h| {
                    h.spawn((ListTitle(k), Text::new(""), wood::title(f, 17.0), TextLayout::new(Justify::Left, LineBreak::NoWrap), Pickable::IGNORE));
                    h.spawn((ListNote(k), Text::new(""), wood::on_wood(f, 11.0, 700), Pickable::IGNORE));
                });
                m.spawn((Node { flex_direction: FlexDirection::Column, margin: UiRect::horizontal(Val::Px(6.0)), border: wood::b(2.0), border_radius: wood::r(8.0), overflow: Overflow::clip(), ..default() }, BackgroundColor(wood::surface()), BorderColor::all(wood::edge()), Pickable::IGNORE)).with_children(|list| {
                    for i in 0..ROWS {
                        list.spawn((ListRow(k, i), Hot, Tag(format!("acts:{k}:{i}")), kit::Paint::Row, Lit(false), Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(9.0), padding: UiRect::axes(Val::Px(10.0), Val::Px(6.0)), display: Display::None, ..default() }, BackgroundGradient::default()))
                            .with_children(|r| {
                                r.spawn((ListIcon(k, i), Node { width: Val::Px(16.0), height: Val::Px(16.0), flex_shrink: 0.0, ..default() }, ImageNode::new(icons.get(Glyph::Ui(Mark::Dots))).with_color(wood::glyph_tint()), Pickable::IGNORE));
                                r.spawn((ListText(k, i), Text::new(""), wood::ink(f, 15.0, 800), Node { flex_grow: 1.0, ..default() }, TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                                r.spawn((ListMore(k, i), Text::new(""), f.body(13.0, 700), TextColor(wood::muted()), Pickable::IGNORE));
                                r.spawn((ListKey(k, i), Node { padding: UiRect::axes(Val::Px(5.0), Val::Px(0.0)), min_width: Val::Px(22.0), height: Val::Px(20.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: wood::b(2.0), border_radius: wood::r(6.0), flex_shrink: 0.0, ..default() }, BackgroundColor(wood::surface()), BorderColor::all(wood::edge()), wood::hard_shadow(2.0, 0.5), Pickable::IGNORE))
                                    .with_child((ListKeyText(k, i), Text::new(""), f.body(11.0, 900), TextColor(wood::text()), Pickable::IGNORE));
                            });
                    }
                });
            });
    }
    // Notes, over the cluster.
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), bottom: Val::Px(196.0), flex_direction: FlexDirection::ColumnReverse, align_items: AlignItems::Center, row_gap: Val::Px(6.0), ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            for i in 0..TOASTS {
                root.spawn((ToastRow(i), Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(8.0), padding: UiRect::new(Val::Px(8.0), Val::Px(12.0), Val::Px(5.0), Val::Px(6.0)), border: wood::b(2.0), border_radius: wood::r(10.0), max_width: Val::Px(600.0), display: Display::None, ..default() }, BackgroundColor(wood::float_or(wood::surface())), BorderColor::all(wood::edge()), wood::hard_shadow(3.0, 0.45), Pickable::IGNORE))
                    .with_children(|t| {
                        t.spawn((ToastMark(i), Node { width: Val::Px(8.0), height: Val::Px(8.0), border_radius: BorderRadius::all(Val::Percent(50.0)), flex_shrink: 0.0, ..default() }, BackgroundColor(wood::muted()), Pickable::IGNORE));
                        t.spawn((ToastText(i), Text::new(""), wood::ink(f, 14.0, 800), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                    });
            }
        });
}

fn row_view(r: &Row) -> MenuRowView {
    match r {
        Row::Pick(c) => MenuRowView { label: label(&wood::readable(&c.label)), skill: c.skill.clone(), group: false, have: c.have },
        Row::Group { name, label: l, .. } => MenuRowView { label: label(l.trim_end_matches(" ›")), skill: name.clone(), group: true, have: 0 },
        Row::Talk => MenuRowView { label: "Talk".into(), skill: "talk".into(), group: false, have: 0 },
        Row::Window => MenuRowView { label: "Their window".into(), skill: "window".into(), group: false, have: 0 },
        Row::Introduce => MenuRowView { label: "Introduce yourself".into(), skill: "introduce".into(), group: false, have: 0 },
        Row::More => MenuRowView { label: "More…".into(), skill: "more".into(), group: false, have: 0 },
    }
}

/// Fill the verbs' part of the model: the list, the notes, and the pack's and know-how's views
/// while their windows are open.
pub fn fill(mut model: ResMut<HudModel>, v: Res<Verbs>, rules: NonSend<Rules>, net: NonSend<Net>, time: Res<Time>, ws: Res<super::win::Windows>) {
    let now = time.elapsed_secs_f64();
    model.verbs.toasts = v.toasts.iter().rev().map(|t| (wood::readable(&t.text), t.ok, (now - t.at) as f32)).collect();
    model.verbs.menu = v.menu.as_ref().map(|m| {
        let main = crate::verbs::Menu { group: None, ..m.clone() };
        let rows = main.rows().iter().take(ROWS).map(row_view).collect();
        let sub = m.group.as_ref().map(|g| {
            let title = if g == "offer" { "Trade".to_string() } else { label(g) };
            (title, m.rows().iter().take(ROWS).map(row_view).collect())
        });
        // One line: a long label is shortened rather than wrapped.
        let title = wood::fit(&match &m.item {
            Some(i) => label(&i.replace('_', " ")),
            None => label(&m.title),
        }, 24);
        let person = match m.aim {
            crate::verbs::Aim::Creature { id } => Some(id),
            _ => None,
        };
        MenuView { title, rows, sub, person, at: m.at }
    });
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else {
        model.verbs.inventory = None;
        model.verbs.know_how = None;
        return;
    };
    let sc = rules.scripts.as_ref();
    model.verbs.inventory = ws.is_open(super::win::Win::Pack).then(|| {
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
        // As the rules count a load (goods-3): each item by its `carry_of` (arrows and marks 0.1),
        // the limit the body's `carry_limit` plus the largest `room` of what I carry (a basket).
        let carried = rows.iter().map(|r| r.1 as f32 * sc.map_or(1.0, |s| s.num_of("carry_of", &r.0, 1.0)) as f32).sum::<f32>();
        let kind = conn.db.my_characters().id().find(&me).map_or("person".to_string(), |c| c.kind);
        let room = sc.map_or(0.0, |s| rows.iter().filter_map(|r| s.tables().number("items", &r.0, "room")).fold(0.0, f64::max)) as f32;
        let limit = sc.map_or(0.0, |s| s.num_of("carry_limit", &kind, 0.0)) as f32 + room;
        InventoryView { rows, carried, limit }
    });
    model.verbs.know_how = ws.is_open(super::win::Win::Skills).then(|| {
        let techniques = conn.db.my_know_how().iter().filter(|k| k.actor == me).map(|k| (k.technique, k.source)).collect();
        let all = &rules.skills;
        let n = all.len();
        let selected = v.selected.min(n.saturating_sub(1));
        let skills = all.iter().map(|s| label(&s.name)).collect();
        let detail = all.get(selected).map_or_else(SkillDetail::default, |spec| {
            let (takes, gives) = sc.and_then(|s| s.skill_io(&spec.name)).unwrap_or_default();
            SkillDetail { name: label(&spec.name), help: spec.help.clone(), takes, gives }
        });
        KnowHowView { techniques, skills, selected, start: 0, detail }
    });
}

/// A row's icon and key, by what it does.
fn icon_key(skill: &str, binds: &crate::keys::Binds) -> (Option<Mark>, String) {
    use crate::keys::Act;
    match skill {
        "talk" => (Some(Mark::Talk), binds.first(Act::Interact)),
        "window" => (Some(Mark::People), String::new()),
        "give" => (Some(Mark::Give), String::new()),
        "offer" | "offer_terms" | "accept" => (Some(Mark::Trade), String::new()),
        "wave" => (Some(Mark::Wave), binds.first(Act::Wave)),
        "nod" => (Some(Mark::Wave), binds.first(Act::Nod)),
        "appraise" => (Some(Mark::Eye), binds.first(Act::LookOver)),
        "teach" | "ask" | "read" | "write" => (Some(Mark::Book), String::new()),
        "introduce" => (Some(Mark::Person), String::new()),
        _ => (None, String::new()),
    }
}

/// Clicks on the list's rows: the list's own pick (a row of the sub-list, or of the list with
/// the sub-list closed first), through `verbs.rs`'s path.
pub fn clicks(ui: Res<UiPointer>, tags: Query<&Tag>, mut v: ResMut<Verbs>) {
    let Some(t) = kit::clicked(&ui, &tags) else {
        // A press elsewhere closes the list.
        if ui.pressed_elsewhere && v.menu.is_some() {
            v.menu = None;
        }
        return;
    };
    // `acts:K:WHAT:I`: list K (0 the list, 1 its sub-list), row I (WHAT names it for scripts).
    let Some(rest) = t.strip_prefix("acts:") else { return };
    let parts: Vec<&str> = rest.split(':').collect();
    let (Some(k), Some(i)) = (parts.first().and_then(|k| k.parse::<u8>().ok()), parts.last().and_then(|i| i.parse::<usize>().ok())) else { return };
    if k == 0 {
        if let Some(m) = v.menu.as_mut() {
            m.group = None;
        }
    }
    v.clicked = Some(i);
}

#[allow(clippy::type_complexity, clippy::too_many_arguments)]
pub fn menu(
    model: Res<HudModel>,
    icons: Res<Icons>,
    binds: Res<crate::keys::Binds>,
    cams: Query<(&Camera, &GlobalTransform), With<Camera3d>>,
    ui: Res<UiPointer>,
    mut roots: Query<(&ListRoot, &mut Node), Without<ListRow>>,
    mut rows: Query<(&ListRow, &mut Node, &mut Tag), (Without<ListRoot>, Without<ListKey>)>,
    mut keys: Query<(&ListKey, &mut Node), (Without<ListRoot>, Without<ListRow>, Without<ListIcon>)>,
    mut iconq: Query<(&ListIcon, &mut Node, &mut ImageNode), (Without<ListRoot>, Without<ListRow>, Without<ListKey>)>,
    mut texts: ParamSet<(Query<(&ListTitle, &mut Text)>, Query<(&ListNote, &mut Text)>, Query<(&ListText, &mut Text)>, Query<(&ListKeyText, &mut Text)>, Query<(&ListMore, &mut Text)>)>,
    roots_size: Query<(&ListRoot, &bevy::ui::ComputedNode)>,
) {
    let m = model.verbs.menu.as_ref().filter(|_| model.death.is_none());
    let lists: [Option<(String, String, &Vec<MenuRowView>)>; 2] = match m {
        Some(m) => {
            let note = if m.person.is_some() && wood::t().chips { format!("hold {}", binds.first(crate::keys::Act::Interact)) } else { String::new() };
            [Some((m.title.clone(), note, &m.rows)), m.sub.as_ref().map(|(t, r)| (t.clone(), if m.sub.as_ref().is_some_and(|s| s.1.iter().any(|r| r.have > 0)) { "from your pack".to_string() } else { String::new() }, r))]
        }
        None => [None, None],
    };
    // Beside the person's head, else where the UI put it, else over the cluster.
    let screen = cams.iter().find_map(|(c, _)| c.logical_viewport_size()).unwrap_or(Vec2::new(1600.0, 900.0)) / ui.ui_scale.max(0.01);
    let head = m.and_then(|m| m.person).and_then(|id| model.actors.iter().find(|a| a.id == id as u64)).and_then(|a| cams.iter().find_map(|(c, t)| c.world_to_viewport(t, a.head).ok())).map(|p| ui.val(p) + Vec2::new(40.0, -20.0));
    let base = m.and_then(|m| m.at).or(head).unwrap_or(Vec2::new(screen.x / 2.0 - 112.0, screen.y - 520.0));
    // Sizes in UI units (physical px times the node's inverse scale).
    let size0 = roots_size.iter().find(|(r, _)| r.0 == 0).map_or(Vec2::new(224.0, 300.0), |(_, n)| n.size() * n.inverse_scale_factor());
    let (w0, h0) = (size0.x, size0.y);
    let x0 = base.x.clamp(10.0, (screen.x - w0 - 200.0).max(10.0));
    let y0 = base.y.clamp(10.0, (screen.y - h0 - 160.0).max(10.0));
    for (r, mut n) in &mut roots {
        let on = lists[r.0 as usize].is_some();
        show(&mut n, on);
        let (x, y) = if r.0 == 0 { (x0, y0) } else { (x0 + w0 + 8.0, y0 + 110.0) };
        let (l, t) = (Val::Px(x.round()), Val::Px(y.round()));
        if n.left != l {
            n.left = l;
        }
        if n.top != t {
            n.top = t;
        }
    }
    let row = |k: u8, i: usize| lists[k as usize].as_ref().and_then(|l| l.2.get(i));
    for (r, mut n, mut tag) in &mut rows {
        let v = row(r.0, r.1);
        show(&mut n, v.is_some());
        // Named for scripts by what it does: `acts:0:give:2`, `acts:1:berries:0`.
        let what = v.map(|v| if r.0 == 1 { v.label.split_once(' ').map_or(v.label.clone(), |(_, it)| it.split(" ×").next().unwrap_or(it).to_lowercase().replace(' ', "_")) } else { v.skill.clone() }).unwrap_or_default();
        let want = format!("acts:{}:{what}:{}", r.0, r.1);
        if tag.0 != want {
            tag.0 = want;
        }
    }
    for (t, mut text) in &mut texts.p0() {
        if let Some(l) = &lists[t.0 as usize] {
            set_text(&mut text, &l.0);
        }
    }
    for (t, mut text) in &mut texts.p1() {
        if let Some(l) = &lists[t.0 as usize] {
            set_text(&mut text, &l.1);
        }
    }
    for (t, mut text) in &mut texts.p2() {
        if let Some(r) = row(t.0, t.1) {
            // In the sub-list, the item alone (its skill is the list's title).
            let s = if t.0 == 1 { r.label.split_once(' ').map_or(r.label.clone(), |(_, rest)| label(rest.split(" ×").next().unwrap_or(rest))) } else { r.label.clone() };
            set_text(&mut text, &s);
        }
    }
    for (t, mut text) in &mut texts.p4() {
        if let Some(r) = row(t.0, t.1) {
            let s = if r.group { "›".to_string() } else if t.0 == 1 && r.have > 0 { format!("×{}", r.have) } else { String::new() };
            set_text(&mut text, &s);
        }
    }
    for (t, mut text) in &mut texts.p3() {
        if let Some(r) = row(t.0, t.1) {
            set_text(&mut text, &icon_key(&r.skill, &binds).1);
        }
    }
    for (k, mut n) in &mut keys {
        show(&mut n, row(k.0, k.1).is_some_and(|r| !icon_key(&r.skill, &binds).1.is_empty()));
    }
    for (k, mut n, mut img) in &mut iconq {
        let Some(r) = row(k.0, k.1) else { continue };
        let g = if k.0 == 1 { r.label.split_once(' ').map(|(_, it)| Glyph::Item(super::icons::item_mark(&it.to_lowercase().replace(' ', "_")))) } else { icon_key(&r.skill, &binds).0.map(Glyph::Ui) };
        show(&mut n, g.is_some());
        if let Some(g) = g {
            let h = icons.get(g);
            if img.image != h {
                img.image = h;
            }
        }
    }
}

#[allow(clippy::type_complexity)]
pub fn toasts(model: Res<HudModel>, mut rows: Query<(&ToastRow, &mut Node, &mut BackgroundColor, &mut BorderColor), Without<ToastMark>>, mut marks: Query<(&ToastMark, &mut BackgroundColor), Without<ToastRow>>, mut texts: Query<(&ToastText, &mut Text, &mut TextColor)>) {
    let t = &model.verbs.toasts;
    // Fade over the last second.
    let alpha = |age: f32| (4.5 - age).clamp(0.0, 1.0);
    for (r, mut n, mut bg, mut border) in &mut rows {
        show(&mut n, r.0 < t.len() && model.death.is_none());
        if let Some((_, _, age)) = t.get(r.0) {
            super::set_bg(&mut bg, wood::alpha(wood::float_or(wood::surface()), alpha(*age)));
            let c = wood::alpha(wood::edge(), alpha(*age));
            if border.top != c {
                *border = BorderColor::all(c);
            }
        }
    }
    for (r, mut bg) in &mut marks {
        if let Some((_, ok, age)) = t.get(r.0) {
            let c = match ok {
                Some(true) => Color::srgb_u8(0x5f, 0xa8, 0x4a),
                Some(false) => wood::HOSTILE,
                None => wood::muted(),
            };
            super::set_bg(&mut bg, wood::alpha(c, alpha(*age)));
        }
    }
    for (r, mut text, mut color) in &mut texts {
        if let Some((s, _, age)) = t.get(r.0) {
            set_text(&mut text, s);
            super::set_color(&mut color, wood::alpha(wood::text(), alpha(*age)));
        }
    }
}
