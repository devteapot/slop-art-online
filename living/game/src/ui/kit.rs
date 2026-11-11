//! Interface D's small controls: buttons, segmented choices, toggles and list rows, all taking
//! clicks through the game's cursor (`hit.rs`) and naming what they do with a [`Tag`]. A page
//! sets [`Lit`] on what is chosen; [`paint`] draws every control from its kind, whether it is lit
//! and whether the cursor is over it.

use super::hit::{Hot, Tag, UiPointer};
use super::theme::Fonts;
use super::wood;
use bevy::prelude::*;
use bevy::ui::BackgroundGradient;

#[derive(Component, Clone, Copy, PartialEq, Eq, Debug)]
pub enum Paint {
    /// Gold, ghost (cream) when not lit.
    Button,
    /// Cream, gold when lit (a segmented choice, a tab).
    Choice,
    /// A list row: clear, gold when lit or under the cursor.
    Row,
    /// A toggle's pill: green when lit.
    Toggle,
}

/// Chosen, on, or (for a button) live.
#[derive(Component, Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Lit(pub bool);

fn flat(c: Color) -> BackgroundGradient {
    BackgroundGradient::from(bevy::ui::LinearGradient::to_bottom(vec![bevy::ui::ColorStop::percent(c, 0.0), bevy::ui::ColorStop::percent(c, 100.0)]))
}

/// A button: gold, or cream (`ghost`). Returns its entity.
pub fn button(p: &mut ChildSpawnerCommands, f: &Fonts, label: &str, tag: &str, ghost: bool) -> Entity {
    button_with(p, f, label, tag, ghost, (), ())
}

/// A button whose node and label carry more components (a widget that changes them later).
pub fn button_with(p: &mut ChildSpawnerCommands, f: &Fonts, label: &str, tag: &str, ghost: bool, on_button: impl Bundle, on_label: impl Bundle) -> Entity {
    p.spawn((
        on_button,
        Hot,
        Tag(tag.into()),
        Paint::Button,
        Lit(!ghost),
        Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(7.0), padding: UiRect::axes(Val::Px(12.0), Val::Px(6.0)), border: wood::b(2.0), border_radius: wood::r(9.0), flex_shrink: 0.0, ..default() },
        wood::gold(),
        BorderColor::all(wood::edge()),
        wood::hard_shadow(3.0, 0.55),
    ))
    .with_child((Text::new(label), wood::ink(f, 14.0, 800), Pickable::IGNORE, on_label))
    .id()
}

/// A segmented choice: one cell per option, each tagged `tag_prefix:value`.
pub fn seg(p: &mut ChildSpawnerCommands, f: &Fonts, tag_prefix: &str, options: &[(&str, &str)]) {
    p.spawn((Node { flex_direction: FlexDirection::Row, border: wood::b(2.0), border_radius: wood::r(9.0), overflow: Overflow::clip(), flex_shrink: 0.0, align_self: AlignSelf::FlexStart, ..default() }, BorderColor::all(wood::edge()), wood::hard_shadow(2.0, 0.4), Pickable::IGNORE)).with_children(|s| {
        for (i, (label, value)) in options.iter().enumerate() {
            let mut node = Node { padding: UiRect::axes(Val::Px(12.0), Val::Px(5.0)), ..default() };
            if i + 1 < options.len() {
                node.border = UiRect::right(Val::Px(2.0));
            }
            s.spawn((Hot, Tag(format!("{tag_prefix}:{value}")), Paint::Choice, Lit(false), node, flat(wood::plain()), BorderColor::all(wood::edge()))).with_child((Text::new(*label), wood::ink(f, 13.0, 800), Pickable::IGNORE));
        }
    });
}

/// A toggle (a pill with a knob).
pub fn toggle(p: &mut ChildSpawnerCommands, tag: &str) {
    p.spawn((
        Hot,
        Tag(tag.into()),
        Paint::Toggle,
        Lit(false),
        Node { width: Val::Px(44.0), height: Val::Px(24.0), padding: UiRect::all(Val::Px(2.0)), border: wood::b(2.0), border_radius: wood::r(12.0), justify_content: JustifyContent::FlexStart, align_items: AlignItems::Center, flex_shrink: 0.0, ..default() },
        flat(Color::srgb_u8(0xb9, 0xa5, 0x85)),
        BorderColor::all(wood::edge()),
    ))
    .with_child((Node { width: Val::Px(16.0), height: Val::Px(16.0), border: wood::b(2.0), border_radius: BorderRadius::all(Val::Percent(50.0)), ..default() }, BackgroundColor(Color::WHITE), BorderColor::all(wood::edge()), Pickable::IGNORE));
}

/// Draw every control by its kind, lit state and the cursor.
/// Only what changed is repainted (lit, or the cursor arrived or left): building gradients for
/// every control every frame is waste.
pub fn paint(ui: Res<UiPointer>, mut q: Query<(Entity, &Paint, &Lit, &mut BackgroundGradient, &mut Node, Option<&Children>)>, added: Query<(), Added<Paint>>, mut texts: Query<&mut TextColor>, mut last: Local<std::collections::HashMap<Entity, (bool, bool)>>) {
    if last.len() > 4096 {
        last.clear();
    }
    for (e, paint, lit, mut g, mut node, children) in &mut q {
        let over = ui.is_over(e);
        if !added.contains(e) && last.get(&e) == Some(&(lit.0, over)) {
            continue;
        }
        last.insert(e, (lit.0, over));
        let want = match (paint, lit.0) {
            (Paint::Button, true) => {
                if over {
                    flat(wood::t().accent.0)
                } else {
                    wood::gold()
                }
            }
            (Paint::Button, false) | (Paint::Choice, false) => flat(if over { wood::surface() } else { wood::plain() }),
            (Paint::Choice, true) => wood::gold(),
            (Paint::Row, l) => {
                if l || over {
                    wood::hot_row()
                } else {
                    BackgroundGradient::default()
                }
            }
            (Paint::Toggle, l) => flat(if l { Color::srgb_u8(0x8f, 0xc4, 0x6b) } else { Color::srgb_u8(0xb9, 0xa5, 0x85) }),
        };
        if *g != want {
            *g = want;
        }
        // Text on a lit button or choice is the accent's (white on a flat theme's blue).
        if matches!(paint, Paint::Button | Paint::Choice) {
            let c = if lit.0 { wood::accent_text() } else { wood::text() };
            for ch in children.into_iter().flatten() {
                if let Ok(mut t) = texts.get_mut(*ch) {
                    if t.0 != c {
                        t.0 = c;
                    }
                }
            }
        }
        if *paint == Paint::Toggle {
            let j = if lit.0 { JustifyContent::FlexEnd } else { JustifyContent::FlexStart };
            if node.justify_content != j {
                node.justify_content = j;
            }
        }
    }
}

/// The tag clicked this frame, if a tagged control was clicked.
pub fn clicked<'a>(ui: &UiPointer, tags: &'a Query<&Tag>) -> Option<&'a str> {
    ui.clicked.and_then(|e| tags.get(e).ok()).map(|t| t.0.as_str())
}

/// Light the controls whose tag `lit` says.
pub fn light(q: &mut Query<(&Tag, &mut Lit)>, lit: impl Fn(&str) -> Option<bool>) {
    for (t, mut l) in q.iter_mut() {
        if let Some(on) = lit(&t.0) {
            if l.0 != on {
                l.0 = on;
            }
        }
    }
}
