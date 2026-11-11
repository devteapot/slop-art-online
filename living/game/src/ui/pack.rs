//! The pack (I, or the Pack button), on the right anchor, and the skills and know-how window (K).
//!
//! - **The pack:** what I carry, one cell per item with its count, and how much of what I can
//!   carry I carry (the rules' `carry_limit`). A click on an item lists what I can do with it
//!   myself (the rules' acts with that item: eat, plant, write, …), beside the cell.
//! - **Items on people:** hold the click on an item and slide it (a three-finger drag is the
//!   same) onto a person in the world or onto their window, and let go: the rules' act that
//!   hands that item to them (`verbs.rs` picks the choice the rules allow toward them with that
//!   item and nothing asked back: today `give`). While it is carried, a ghost of the item says
//!   what letting go will do. Hold F on someone → Give › does the same from a list.
//! - **Skills and know-how:** the techniques I know (and from whom), and every skill in the
//!   rules with what the chosen one takes and gives (the world's `skill_io`). A port of the old
//!   panel into the wide window; the window of step 6 replaces it.

use super::hit::{Hot, Tag, UiPointer};
use super::icons::{item_mark, Glyph, Icons};
use super::kit::{self, Lit};
use super::model::HudModel;
use super::theme::Fonts;
use super::win::{Win, WinBody, WinFrame, Windows, Z_DRAG};
use super::{label, set_text, show, wood, HudRoot};
use bevy::prelude::*;
use bevy::ui::{BackgroundGradient, GlobalZIndex, ScrollPosition};

const CELLS: usize = 30;
const SKILL_ROWS: usize = 60;

#[derive(Component)]
pub struct Cell(usize);
#[derive(Component)]
pub struct CellIcon(usize);
#[derive(Component)]
pub struct CellCount(usize);
#[derive(Component)]
pub struct Carry;
#[derive(Component)]
pub struct PackHint;
#[derive(Component)]
pub struct Ghost;
#[derive(Component)]
pub struct GhostIcon;
#[derive(Component)]
pub struct GhostLabel;
#[derive(Component)]
pub struct GhostLabelBox;
#[derive(Component)]
pub struct KnowTech;
#[derive(Component)]
pub struct KnowRow(usize);
#[derive(Component)]
pub struct KnowRowText(usize);
#[derive(Component)]
pub struct KnowDetail(u8);

/// An item being carried out of the pack, and onto whom it would go.
#[derive(Resource, Default)]
pub struct Carrying {
    pub item: Option<String>,
    pub onto: Option<u32>,
    /// An item has been clicked or carried: the pack's hint has done its work.
    pub used: bool,
}

pub fn spawn(mut commands: Commands, bodies: Query<(Entity, &WinBody), Added<WinBody>>, fonts: Res<Fonts>, icons: Res<Icons>, ghost: Query<(), With<Ghost>>) {
    let f = &*fonts;
    if ghost.is_empty() {
        commands
            .spawn((HudRoot, Ghost, Node { position_type: PositionType::Absolute, width: Val::Px(58.0), height: Val::Px(58.0), border: wood::b(3.0), border_radius: wood::r(10.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, display: Display::None, ..default() }, BackgroundColor(wood::surface_hi()), BorderColor::all(wood::edge()), wood::hard_shadow(6.0, 0.4), bevy::ui::UiTransform::from_rotation(Rot2::degrees(-6.0)), GlobalZIndex(Z_DRAG), Pickable::IGNORE))
            .with_children(|g| {
                g.spawn((GhostIcon, Node { width: Val::Px(38.0), height: Val::Px(38.0), ..default() }, ImageNode::new(Handle::default()).with_color(wood::heading()), Pickable::IGNORE));
                g.spawn((GhostLabelBox, Node { position_type: PositionType::Absolute, left: Val::Px(62.0), top: Val::Px(12.0), padding: UiRect::axes(Val::Px(8.0), Val::Px(2.0)), border: wood::b(2.0), border_radius: wood::r(8.0), ..default() }, BackgroundColor(wood::talk_ink()), BorderColor::all(wood::edge()), bevy::ui::UiTransform::from_rotation(Rot2::degrees(6.0)), Pickable::IGNORE))
                    .with_child((GhostLabel, Text::new(""), f.body(13.0, 900), TextColor(Color::WHITE), TextLayout::new(Justify::Left, LineBreak::NoWrap), Pickable::IGNORE));
            });
    }
    for (e, b) in &bodies {
        match b.0 {
            Win::Pack => {
                commands.entity(e).with_children(|body| {
                    // How much I carry, right; no tabs (there is one page).
                    body.spawn((Node { flex_direction: FlexDirection::Row, justify_content: JustifyContent::FlexEnd, align_items: AlignItems::Center, flex_shrink: 0.0, ..default() }, Pickable::IGNORE)).with_children(|h| {
                        h.spawn((Carry, Text::new(""), f.body(13.0, 700), TextColor(wood::muted()), Pickable::IGNORE));
                    });
                    body.spawn((Node { display: Display::Grid, grid_template_columns: RepeatedGridTrack::px(5, 62.0), row_gap: Val::Px(7.0), column_gap: Val::Px(7.0), overflow: Overflow::scroll_y(), flex_shrink: 1.0, min_height: Val::Px(0.0), ..default() }, ScrollPosition::default(), super::hit::Block)).with_children(|g| {
                        for i in 0..CELLS {
                            g.spawn((Cell(i), Hot, Tag(format!("pack::{i}")), Node { width: Val::Px(62.0), height: Val::Px(62.0), border: wood::b(2.0), border_radius: wood::r(9.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, ..default() }, BackgroundColor(wood::surface_lo()), BorderColor::all(wood::edge()), bevy::ui::Outline { width: Val::Px(0.0), offset: Val::Px(1.0), color: Color::srgb_u8(0xff, 0xcf, 0x5c) }))
                                .with_children(|c| {
                                    c.spawn((CellIcon(i), Node { width: Val::Px(36.0), height: Val::Px(36.0), display: Display::None, ..default() }, ImageNode::new(Handle::default()).with_color(wood::heading()), Pickable::IGNORE));
                                    c.spawn((CellCount(i), Text::new(""), f.body(13.0, 900), TextColor(wood::text()), Node { position_type: PositionType::Absolute, right: Val::Px(4.0), bottom: Val::Px(1.0), ..default() }, Pickable::IGNORE));
                                });
                        }
                    });
                    // Shown until an item is clicked or carried once (always in a dense theme).
                    body.spawn((PackHint, Text::new("Click an item to use it; drag it onto someone to give it."), f.body(12.5, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::NoWrap), Pickable::IGNORE));
                });
            }
            Win::Skills => {
                commands.entity(e).with_children(|body| {
                    body.spawn((KnowTech, Text::new(""), f.body(13.5, 650), TextColor(wood::text()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                    body.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(16.0), flex_grow: 1.0, min_height: Val::Px(0.0), ..default() }, Pickable::IGNORE)).with_children(|cols| {
                        cols.spawn((Node { width: Val::Px(240.0), flex_direction: FlexDirection::Column, overflow: Overflow::scroll_y(), max_height: Val::Px(480.0), flex_shrink: 0.0, ..default() }, ScrollPosition::default(), super::hit::Block)).with_children(|list| {
                            for i in 0..SKILL_ROWS {
                                list.spawn((KnowRow(i), Hot, Tag(format!("skill:{i}")), kit::Paint::Row, Lit(false), Node { padding: UiRect::axes(Val::Px(8.0), Val::Px(2.0)), border_radius: wood::r(5.0), display: Display::None, flex_shrink: 0.0, ..default() }, BackgroundGradient::default()))
                                    .with_child((KnowRowText(i), Text::new(""), wood::ink(f, 13.5, 700), Pickable::IGNORE));
                            }
                        });
                        cols.spawn((Node { flex_direction: FlexDirection::Column, row_gap: Val::Px(8.0), flex_grow: 1.0, ..default() }, Pickable::IGNORE)).with_children(|d| {
                            d.spawn((KnowDetail(0), Text::new(""), wood::tface(&f, 20.0), TextColor(wood::heading()), Pickable::IGNORE));
                            for k in 1..4u8 {
                                d.spawn((KnowDetail(k), Text::new(""), f.body(14.0, 600), TextColor(wood::text()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                            }
                        });
                    });
                });
            }
            _ => {}
        }
    }
}

/// Item clicks (their acts), drags onto people, and skills chosen in the know-how list.
#[allow(clippy::too_many_arguments)]
pub fn clicks(ui: Res<UiPointer>, tags: Query<&Tag>, model: Res<HudModel>, mut v: ResMut<crate::verbs::Verbs>, mut carrying: ResMut<Carrying>, frames: Query<(&WinFrame, &bevy::ui::ComputedNode, &bevy::ui::UiGlobalTransform)>, cells: Query<(&Cell, &bevy::ui::ComputedNode, &bevy::ui::UiGlobalTransform)>, cams: Query<(&Camera, &GlobalTransform), With<Camera3d>>) {
    let item_of = |i: usize| model.verbs.inventory.as_ref().and_then(|inv| inv.rows.get(i)).map(|r| r.0.clone());
    // `pack:ITEM:I` (ITEM names it for scripts; empty for an empty cell).
    let cell_of = |e: Entity| tags.get(e).ok().and_then(|t| t.0.strip_prefix("pack:")).and_then(|r| r.rsplit(':').next()).and_then(|i| i.parse::<usize>().ok());
    if let Some(i) = ui.clicked.and_then(cell_of) {
        if let Some(item) = item_of(i) {
            carrying.used = true;
            // The item's acts, beside its cell (to its left: the pack is on the right).
            let at = cells.iter().find(|(c, _, _)| c.0 == i).map(|(_, n, t)| (t.affine().translation - n.size() / 2.0) * n.inverse_scale_factor());
            v.place_next = at.map(|p| p - Vec2::new(236.0, 10.0));
            v.clicked_item = Some(item);
        }
    }
    if let Some(i) = ui.clicked.and_then(|e| tags.get(e).ok()).and_then(|t| t.0.strip_prefix("skill:")).and_then(|i| i.parse::<usize>().ok()) {
        v.selected = i;
    }
    // Carrying an item: onto whom it would go (their window, else them in the world).
    carrying.item = None;
    carrying.onto = None;
    let from = ui.down.or(ui.dropped.map(|(e, p)| (e, p))).map(|(e, _)| e);
    if let Some(i) = from.and_then(cell_of).filter(|_| ui.dragging || ui.dropped.is_some()) {
        carrying.item = item_of(i);
        if let Some(p) = ui.pos {
            let phys = p * ui.scale;
            let window = frames.iter().filter(|(_, n, t)| n.contains_point(**t, phys)).find_map(|(f, _, _)| match f.0 {
                Win::Person(id) => Some(id),
                _ => None,
            });
            // A person on screen: the one hovered, else the nearest head within 70 px.
            let world = model.actors.iter().filter(|a| a.kind_person).filter_map(|a| cams.iter().find_map(|(c, t)| c.world_to_viewport(t, a.head).ok()).map(|s| (a, s))).map(|(a, s)| (a.id as u32, a.hovered, (s + Vec2::new(0.0, 40.0)).distance(p))).filter(|(_, h, d)| *h || *d < 70.0).min_by(|a, b| a.2.total_cmp(&b.2)).map(|(id, _, _)| id);
            carrying.onto = window.or(if ui.over_ui { None } else { world });
        }
    }
    if let (Some((e, _)), Some(item)) = (ui.dropped, carrying.item.clone()) {
        if cell_of(e).is_some() {
            carrying.used = true;
            match carrying.onto {
                Some(id) => {
                    info!("ui: {item} let go on #{id}");
                    v.drop_item = Some((id, item));
                }
                None => info!("ui: {item} let go on no one"),
            }
        }
    }
}

#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn update(
    model: Res<HudModel>,
    icons: Res<Icons>,
    ui: Res<UiPointer>,
    carrying: Res<Carrying>,
    looks: Res<crate::looks::Looks>,
    mut cells: Query<(Entity, &Cell, &mut BackgroundColor, &mut BorderColor, &mut bevy::ui::Outline, &mut Tag), (Without<Ghost>, Without<Lit>)>,
    mut cell_icons: Query<(&CellIcon, &mut Node, &mut ImageNode), (Without<Ghost>, Without<GhostIcon>)>,
    mut texts: ParamSet<(Query<(&CellCount, &mut Text)>, Query<&mut Text, With<Carry>>, Query<&mut Text, With<GhostLabel>>, Query<&mut Text, With<KnowTech>>, Query<(&KnowRowText, &mut Text)>, Query<(&KnowDetail, &mut Text)>)>,
    mut ghost: Query<&mut Node, (With<Ghost>, Without<CellIcon>, Without<KnowRow>, Without<GhostLabelBox>)>,
    mut ghost_icon: Query<&mut ImageNode, (With<GhostIcon>, Without<CellIcon>)>,
    mut ghost_box: Query<&mut Node, (With<GhostLabelBox>, Without<Ghost>, Without<CellIcon>, Without<KnowRow>)>,
    mut rows: Query<(&KnowRow, &mut Node), (Without<Ghost>, Without<CellIcon>, Without<GhostLabelBox>)>,
    mut lit: Query<(&Tag, &mut Lit)>,
    (mut cell_nodes, mut hint): (Query<(&Cell, &mut Node), (Without<Ghost>, Without<CellIcon>, Without<KnowRow>, Without<GhostLabelBox>, Without<PackHint>)>, Query<&mut Node, (With<PackHint>, Without<Cell>, Without<Ghost>, Without<CellIcon>, Without<KnowRow>, Without<GhostLabelBox>)>),
) {
    for mut n in &mut hint {
        show(&mut n, wood::t().help || !carrying.used);
    }
    if let Some(inv) = &model.verbs.inventory {
        let need = (inv.rows.len() / 5 + 1).max(1) * 5;
        for (c, mut n) in &mut cell_nodes {
            show(&mut n, c.0 < need);
        }
        for (e, c, mut bg, mut border, mut outline, mut tag) in &mut cells {
            let full = c.0 < inv.rows.len();
            let want = format!("pack:{}:{}", inv.rows.get(c.0).map_or("", |r| r.0.as_str()), c.0);
            if tag.0 != want {
                tag.0 = want;
            }
            let col = if full { wood::surface_hi() } else { wood::surface_lo() };
            if bg.0 != col {
                bg.0 = col;
            }
            let b = if full { wood::edge() } else { wood::alpha(wood::edge(), 0.5) };
            if border.top != b {
                *border = BorderColor::all(b);
            }
            let over = full && ui.is_over(e);
            let w = if over { Val::Px(3.0) } else { Val::Px(0.0) };
            if outline.width != w {
                outline.width = w;
                outline.color = Color::srgb_u8(0xff, 0xcf, 0x5c);
            }
        }
        for (c, mut n, mut img) in &mut cell_icons {
            let item = inv.rows.get(c.0).map(|r| r.0.as_str());
            show(&mut n, item.is_some());
            if let Some(it) = item {
                let h = icons.get(Glyph::Item(item_mark(it)));
                if img.image != h {
                    img.image = h;
                }
            }
        }
        for (c, mut t) in &mut texts.p0() {
            let s = inv.rows.get(c.0).filter(|r| r.1 > 1).map_or(String::new(), |r| r.1.to_string());
            set_text(&mut t, &s);
        }
        for mut t in &mut texts.p1() {
            let s = if inv.limit > 0 { format!("{} / {}", inv.carried, inv.limit) } else { inv.carried.to_string() };
            set_text(&mut t, &s);
        }
    }
    // The ghost of a carried item.
    let on = carrying.item.is_some() && ui.dragging;
    for mut n in &mut ghost {
        show(&mut n, on);
        if let (true, Some(p)) = (on, ui.pos) {
            let v = ui.val(p) - Vec2::new(20.0, 24.0);
            n.left = Val::Px(v.x.round());
            n.top = Val::Px(v.y.round());
        }
    }
    if let Some(item) = &carrying.item {
        for mut img in &mut ghost_icon {
            let h = icons.get(Glyph::Item(item_mark(item)));
            if img.image != h {
                img.image = h;
            }
        }
        for mut n in &mut ghost_box {
            show(&mut n, carrying.onto.is_some());
        }
        if let Some(id) = carrying.onto {
            for mut t in &mut texts.p2() {
                set_text(&mut t, &format!("Give {} to {}", item.replace('_', " "), looks.of(id).unwrap_or("them")));
            }
        }
    }
    // Know-how.
    if let Some(k) = &model.verbs.know_how {
        for mut t in &mut texts.p3() {
            let s = if k.techniques.is_empty() { "You know no techniques yet.".to_string() } else { format!("You know  {}", k.techniques.iter().map(|(t, src)| if src.is_empty() || src == "seed" || src.contains("newcomer") { label(t) } else { format!("{} ({src})", label(t)) }).collect::<Vec<_>>().join(" · ")) };
            set_text(&mut t, &s);
        }
        for (r, mut n) in &mut rows {
            show(&mut n, r.0 < k.skills.len());
        }
        for (r, mut t) in &mut texts.p4() {
            if let Some(s) = k.skills.get(r.0) {
                set_text(&mut t, s);
            }
        }
        for (d, mut t) in &mut texts.p5() {
            let s = match d.0 {
                0 => k.detail.name.clone(),
                1 => k.detail.help.clone(),
                2 => if k.detail.takes.is_empty() { String::new() } else { format!("Takes: {}", k.detail.takes) },
                _ => if k.detail.gives.is_empty() { String::new() } else { format!("Gives: {}", k.detail.gives) },
            };
            set_text(&mut t, &s);
        }
        let sel = k.selected;
        kit::light(&mut lit, |t| t.strip_prefix("skill:").map(|i| i.parse::<usize>().ok() == Some(sel)));
    }
}
