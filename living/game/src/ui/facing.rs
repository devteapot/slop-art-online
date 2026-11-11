//! Settings › Play: facing sight (`crate::facing`). Shown at all times as "Facing sight: on" or
//! "off"; while on, with the field's five values (focal, side, side share, near, margin). The
//! switch (and F5) works only when the play launcher gave this client the admin link for its
//! scratch world; otherwise the line is read-only. In "face the cursor", until the rules take a
//! look input (`human_face`), the field follows the body's heading, not the cursor: the line says
//! so.
//!
//! Its own module, filling the place `settings.rs` keeps for it ([`super::settings::FacingSight`]),
//! so the Settings page itself changes by one node.

use super::hit::{Tag, UiPointer};
use super::kit::{self, Lit};
use super::settings::FacingSight;
use super::theme::Fonts;
use super::{set_text, show, wood};
use crate::facing::FovState;
use bevy::prelude::*;

/// The tag of the switch.
pub const TAG: &str = "settings:facing_sight";

/// The lines: 0 the state, 1 the five values, 2 the note on facing the cursor.
#[derive(Component)]
pub struct Line(u8);
/// The switch's node (hidden when read-only).
#[derive(Component)]
pub struct Switch;

pub fn spawn(mut commands: Commands, places: Query<Entity, Added<FacingSight>>, fonts: Res<Fonts>) {
    let f = &*fonts;
    for e in &places {
        commands.entity(e).insert(Node { display: Display::Flex, flex_direction: FlexDirection::Column, ..default() });
        commands.entity(e).with_children(|pg| {
            super::settings::row(pg, f, "Facing sight", "The world's law: you see less to the sides and behind you (F5)", |c| {
                kit::toggle(c, TAG);
                c.spawn((Line(0), Text::new("Facing sight: off"), wood::ink(f, 13.5, 800), Pickable::IGNORE));
            });
            pg.spawn((Line(1), Text::new(""), f.body(12.5, 700), TextColor(wood::text()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { margin: UiRect::new(Val::Px(232.0), Val::Px(0.0), Val::Px(4.0), Val::Px(0.0)), display: Display::None, ..default() }, Pickable::IGNORE));
            pg.spawn((Line(2), Text::new(""), f.body(12.0, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { margin: UiRect::new(Val::Px(232.0), Val::Px(0.0), Val::Px(2.0), Val::Px(6.0)), display: Display::None, ..default() }, Pickable::IGNORE));
        });
    }
}

/// The switch's clicks, and the lines from the field.
#[allow(clippy::too_many_arguments)]
pub fn update(
    ui: Res<UiPointer>,
    tags: Query<&Tag>,
    mut lit: Query<(&Tag, &mut Lit)>,
    st: Option<ResMut<FovState>>,
    input: Res<crate::controls::Input>,
    mut lines: Query<(&Line, &mut Text, &mut Node), Without<Tag>>,
    mut switches: Query<(&Tag, &mut Node), (With<kit::Paint>, Without<Line>)>,
) {
    let Some(mut st) = st else { return };
    if kit::clicked(&ui, &tags) == Some(TAG) {
        let want = !st.on();
        crate::facing::ask(&mut st, want);
    }
    let on = st.on();
    kit::light(&mut lit, |t| (t == TAG).then_some(on));
    for (t, mut n) in &mut switches {
        if t.0 == TAG {
            show(&mut n, st.can_switch);
        }
    }
    let cursor = input.control == crate::controls::Control::Cursor;
    for (l, mut text, mut n) in &mut lines {
        match l.0 {
            0 => {
                let state = if !st.known { "Facing sight: not known yet" } else if on { "Facing sight: on" } else { "Facing sight: off" };
                let s = if st.can_switch { state.to_string() } else { format!("{state} (read-only)") };
                set_text(&mut text, &s);
            }
            1 => {
                show(&mut n, on);
                if let Some(f) = st.field {
                    set_text(&mut text, &crate::facing::values(&f));
                }
            }
            _ => {
                show(&mut n, on && cursor);
                set_text(&mut text, "Facing the cursor: your sight follows the way your body faces (where you walk), not the cursor, until the world takes a look input.");
            }
        }
    }
}
