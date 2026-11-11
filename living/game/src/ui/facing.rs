//! Settings › Play: the world's laws a play scene may change (`crate::facing`).
//! - **Facing sight:** shown at all times as "Facing sight: on" or "off"; while on, with the
//!   field's five values (focal, side, side share, near, margin).
//! - **Walk speed:** the world's walk law (`facing::WALK_LAW`) as the installed script has it,
//!   with a choice of 2.6, 3.0 or 3.4 m/s.
//!
//! The switch, F5 and the choices work only when the play launcher gave this client the admin
//! link for its scratch world (`facing::set_law`); otherwise the lines are read-only.
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
/// The walk speed's choices are tagged `settings:walk:<m/s>`.
pub const WALK_TAG: &str = "settings:walk";

/// The walk-speed row's state line.
#[derive(Component)]
pub struct WalkLine;
/// The walk-speed choices' row (hidden without the admin link).
#[derive(Component)]
pub struct WalkChoices;

/// The lines: 0 the state, 1 the five values.
#[derive(Component)]
pub struct Line(u8);

pub fn spawn(mut commands: Commands, places: Query<Entity, Added<FacingSight>>, fonts: Res<Fonts>) {
    let f = &*fonts;
    for e in &places {
        commands.entity(e).insert(Node { display: Display::Flex, flex_direction: FlexDirection::Column, ..default() });
        commands.entity(e).with_children(|pg| {
            super::settings::row(pg, f, "Facing sight", "The world's law: you see less to the sides and behind you (F5)", |c| {
                kit::toggle(c, TAG);
                c.spawn((Line(0), Text::new("Facing sight: off"), wood::ink(f, 13.5, 800), Pickable::IGNORE));
            });
            super::settings::row(pg, f, "Walk speed", "The world's law: how fast everyone walks", |c| {
                c.spawn((WalkChoices, Node { flex_direction: FlexDirection::Row, ..default() }, Pickable::IGNORE)).with_children(|w| {
                    let opts: Vec<(String, String)> = crate::facing::WALK_CHOICES.iter().map(|v| (format!("{v:.1} m/s"), format!("{v:.1}"))).collect();
                    let refs: Vec<(&str, &str)> = opts.iter().map(|(a, b)| (a.as_str(), b.as_str())).collect();
                    kit::seg(w, f, WALK_TAG, &refs);
                });
                c.spawn((WalkLine, Text::new(""), wood::ink(f, 13.0, 700), Pickable::IGNORE));
            });
            pg.spawn((Line(1), Text::new(""), f.body(12.5, 700), TextColor(wood::text()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { margin: UiRect::new(Val::Px(232.0), Val::Px(0.0), Val::Px(4.0), Val::Px(0.0)), display: Display::None, ..default() }, Pickable::IGNORE));
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
    mut lines: Query<(&Line, &mut Text, &mut Node), (Without<Tag>, Without<WalkLine>, Without<WalkChoices>)>,
    mut switches: Query<(&Tag, &mut Node), (With<kit::Paint>, Without<Line>, Without<WalkChoices>)>,
    mut walk_line: Query<&mut Text, (With<WalkLine>, Without<Line>)>,
    mut walk_choices: Query<&mut Node, (With<WalkChoices>, Without<Tag>, Without<Line>)>,
) {
    let Some(mut st) = st else { return };
    match kit::clicked(&ui, &tags) {
        Some(TAG) => {
            let want = !st.on();
            crate::facing::ask(&mut st, want);
        }
        Some(t) if t.starts_with(WALK_TAG) => {
            if let Some(v) = t.rsplit_once(':').map(|x| x.1.to_string()) {
                crate::facing::set_law(&mut st, crate::facing::WALK_LAW, &v);
            }
        }
        _ => {}
    }
    let on = st.on();
    let walk = st.walk;
    kit::light(&mut lit, |t| {
        if t == TAG {
            return Some(on);
        }
        let v = t.strip_prefix(WALK_TAG)?.strip_prefix(':')?.parse::<f32>().ok()?;
        Some(walk.is_some_and(|w| (w - v).abs() < 0.05))
    });
    for mut n in &mut walk_choices {
        show(&mut n, st.can_switch && walk.is_some());
    }
    for mut text in &mut walk_line {
        let law = crate::facing::WALK_LAW;
        let s = match (walk, st.can_switch) {
            (Some(w), true) => format!("{w:.1} m/s"),
            (Some(w), false) => format!("{w:.1} m/s (read-only)"),
            (None, _) => format!("not in this world's laws ({law})"),
        };
        set_text(&mut text, &s);
    }
    for (t, mut n) in &mut switches {
        if t.0 == TAG {
            show(&mut n, st.can_switch);
        }
    }
    for (l, mut text, mut n) in &mut lines {
        match l.0 {
            0 => {
                let state = if !st.known { "Facing sight: not known yet" } else if on { "Facing sight: on" } else { "Facing sight: off" };
                let s = if st.can_switch { state.to_string() } else { format!("{state} (read-only)") };
                set_text(&mut text, &s);
            }
            _ => {
                show(&mut n, on);
                if let Some(f) = st.field {
                    set_text(&mut text, &crate::facing::values(&f));
                }
            }
        }
    }
}
