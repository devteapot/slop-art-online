//! A recipe grid (docs/INTERFACE.md example 4; recipes-1): a way of making whose `_ui()` says
//! `choose: "grid"` from `products` (make, craft, cook, smoke) opens it from the wheel's section
//! or the list. One cell per product, in the recipes' order; a cell the rules' check refuses is
//! greyed with the check's own words. Every row of a cell comes from `recipe_parts`: what it
//! takes (an item, or a trait any of several items satisfies), what it holds (tools), where
//! (a structure kind or any fire, burning, with fuel from it), knowing what, how long. No way or
//! item is named here.
//!
//! A click on a cell (or its number) sends the way's act with `making_item` toward the target;
//! a greyed cell is sent all the same (grey is a hint: the authority decides, its note says why).

use super::hit::{Hot, Tag, UiPointer};
use super::icons::{item_mark, Glyph, Icons};
use super::kit::{self, Lit};
use super::theme::Fonts;
use super::{set_text, show, wood, HudRoot};
use crate::verbs::Verbs;
use bevy::prelude::*;
use bevy::ui::BackgroundGradient;

/// Cells at most (a world with more shows the first; the list keeps every one).
pub const CELLS: usize = 12;
const COLS: usize = 4;
const CELL: f32 = 74.0;
const ROWS_SHOWN: usize = 6;

/// A product's cell.
#[derive(Clone, Debug)]
pub struct GridCell {
    pub product: String,
    /// What the act names as its item (`making_item`).
    pub item: String,
    pub label: String,
    pub icon: String,
    pub makes: u32,
    pub allowed: bool,
    /// The rules' refusal when greyed (its `_check` text).
    pub reason: String,
    /// The way's `detail` (`made_how`) for it.
    pub detail: String,
    /// The recipe as rows: (what, words).
    pub rows: Vec<(String, String)>,
}

/// An open grid toward one target, for one way of making.
#[derive(Clone, Debug)]
pub struct GridOpen {
    pub aim: crate::verbs::Aim,
    pub skill: String,
    pub title: String,
    pub cells: Vec<GridCell>,
    /// The cell whose rows show (hovered, else the first).
    pub sel: usize,
}

#[derive(Component)]
pub struct GridRoot;
#[derive(Component)]
pub struct GridTitle;
#[derive(Component)]
pub struct GridCellNode(usize);
#[derive(Component)]
pub struct GridIcon(usize);
#[derive(Component)]
pub struct GridLabel(usize);
#[derive(Component)]
pub struct GridHead;
#[derive(Component)]
pub struct GridRow(usize);
#[derive(Component)]
pub struct GridRowText(usize);

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = &*fonts;
    let th = wood::t();
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(110.0), justify_content: JustifyContent::Center, ..default() }, Pickable::IGNORE))
        .with_children(|r| {
            r.spawn((GridRoot, super::hit::Block, Node { flex_direction: FlexDirection::Column, row_gap: Val::Px(10.0), padding: UiRect::all(Val::Px(14.0)), border: wood::b(2.0), border_radius: wood::r(12.0), width: Val::Px(COLS as f32 * (CELL + 8.0) + 260.0), display: Display::None, ..default() }, BackgroundColor(th.surface), BorderColor::all(th.edge), wood::shadow(4.0, 1.0), GlobalZIndex(55)))
                .with_children(|g| {
                    g.spawn((GridTitle, Text::new(""), wood::title(f, 16.0), Pickable::IGNORE));
                    g.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(14.0), ..default() }, Pickable::IGNORE)).with_children(|row| {
                        row.spawn((Node { width: Val::Px(COLS as f32 * (CELL + 8.0)), flex_direction: FlexDirection::Row, flex_wrap: FlexWrap::Wrap, column_gap: Val::Px(8.0), row_gap: Val::Px(8.0), ..default() }, Pickable::IGNORE)).with_children(|cells| {
                            for i in 0..CELLS {
                                cells
                                    .spawn((GridCellNode(i), Hot, Tag(format!("grid:cell:{i}")), kit::Paint::Row, Lit(false), Node { width: Val::Px(CELL), height: Val::Px(CELL), flex_direction: FlexDirection::Column, align_items: AlignItems::Center, justify_content: JustifyContent::Center, row_gap: Val::Px(4.0), border: wood::b(2.0), border_radius: wood::r(10.0), display: Display::None, ..default() }, BackgroundGradient::default(), BorderColor::all(th.edge)))
                                    .with_children(|c| {
                                        c.spawn((GridIcon(i), Node { width: Val::Px(30.0), height: Val::Px(30.0), ..default() }, ImageNode::default(), Pickable::IGNORE));
                                        c.spawn((GridLabel(i), Text::new(""), f.body(10.5, 800), TextColor(th.text), TextLayout::new(Justify::Center, LineBreak::WordBoundary), Pickable::IGNORE));
                                    });
                            }
                        });
                        // The selected cell: its name, the rules' words, its recipe as rows.
                        row.spawn((Node { flex_grow: 1.0, flex_direction: FlexDirection::Column, row_gap: Val::Px(5.0), ..default() }, Pickable::IGNORE)).with_children(|d| {
                            d.spawn((GridHead, Text::new(""), wood::ink(f, 13.5, 800), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                            for i in 0..ROWS_SHOWN {
                                d.spawn((GridRow(i), Node { display: Display::None, ..default() }, Pickable::IGNORE)).with_child((GridRowText(i), Text::new(""), f.body(11.5, 600), TextColor(th.muted), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                            }
                        });
                    });
                });
        });
}

/// Draw the open grid: cells (live or greyed), the hovered (else first) cell's words and rows.
#[allow(clippy::type_complexity)]
pub fn update(
    mut v: ResMut<Verbs>,
    ui: Res<UiPointer>,
    icons: Res<Icons>,
    tags: Query<(Entity, &Tag)>,
    mut root: Query<&mut Node, (With<GridRoot>, Without<GridCellNode>, Without<GridRow>)>,
    mut cells: Query<(&GridCellNode, &mut Node, &mut Lit), (Without<GridRoot>, Without<GridRow>)>,
    mut imgs: Query<(&GridIcon, &mut ImageNode)>,
    mut texts: ParamSet<(Query<(&GridLabel, &mut Text, &mut TextColor)>, Query<&mut Text, With<GridTitle>>, Query<&mut Text, With<GridHead>>, Query<(&GridRowText, &mut Text)>)>,
    mut rows: Query<(&GridRow, &mut Node), (Without<GridRoot>, Without<GridCellNode>)>,
) {
    let open = v.grid.is_some();
    for mut n in &mut root {
        show(&mut n, open);
    }
    // The hovered cell is the one whose rows show.
    if let Some(i) = ui.over.and_then(|e| tags.get(e).ok()).and_then(|(_, t)| t.0.strip_prefix("grid:cell:").and_then(|n| n.parse::<usize>().ok())) {
        if let Some(g) = v.grid.as_mut() {
            if i < g.cells.len() {
                g.sel = i;
            }
        }
    }
    let Some(g) = v.grid.as_ref() else { return };
    let th = wood::t();
    for (c, mut n, mut lit) in &mut cells {
        show(&mut n, c.0 < g.cells.len());
        let on = c.0 == g.sel;
        if lit.0 != on {
            lit.0 = on;
        }
    }
    for (i, mut img) in &mut imgs {
        if let Some(c) = g.cells.get(i.0) {
            let h = icons.get(Glyph::Item(item_mark(&c.icon)));
            if img.image != h {
                img.image = h;
            }
            img.color = if c.allowed { Color::WHITE } else { Color::srgba(1.0, 1.0, 1.0, 0.35) };
        }
    }
    for (l, mut t, mut col) in &mut texts.p0() {
        if let Some(c) = g.cells.get(l.0) {
            set_text(&mut t, &if c.makes > 1 { format!("{} ×{}", super::label(&c.label), c.makes) } else { super::label(&c.label) });
            let want = if c.allowed { th.text } else { wood::alpha(th.muted, 0.7) };
            if col.0 != want {
                col.0 = want;
            }
        }
    }
    for mut t in &mut texts.p1() {
        set_text(&mut t, &g.title);
    }
    let sel = g.cells.get(g.sel);
    for mut t in &mut texts.p2() {
        let words = sel.map_or(String::new(), |c| {
            let why = if c.allowed { String::new() } else { format!("\n{}", super::label(c.reason.trim_end_matches('.'))) };
            format!("{}{why}", super::label(&c.detail))
        });
        set_text(&mut t, &wood::readable(&words));
    }
    let lines: Vec<String> = sel.map_or(Vec::new(), |c| c.rows.iter().map(|(k, w)| format!("{k}: {w}")).collect());
    for (r, mut n) in &mut rows {
        show(&mut n, r.0 < lines.len());
    }
    for (r, mut t) in &mut texts.p3() {
        if let Some(l) = lines.get(r.0) {
            set_text(&mut t, &wood::readable(l));
        }
    }
}

/// A click on a cell: the way's act for it (`verbs.rs` sends it).
pub fn clicks(ui: Res<UiPointer>, tags: Query<&Tag>, mut v: ResMut<Verbs>) {
    let Some(t) = kit::clicked(&ui, &tags) else {
        if ui.pressed_elsewhere && v.grid.is_some() {
            v.grid = None;
        }
        return;
    };
    if let Some(i) = t.strip_prefix("grid:cell:").and_then(|n| n.parse::<usize>().ok()) {
        v.grid_pick = Some(i);
    }
}
