//! The keeping-track strip (heed for players, `heed.rs`): a compact top-left pill naming whom I
//! keep track of (my pins, out of [`crate::heed::MAX_PINS`]) and my focus, and the keys. Only
//! while the world's laws let players heed: off, nothing is spawned.
//!
//! Layout: at most 2 tidy lines (1 line when no focus is set: pins + key hint; 2 lines when a
//! focus is set: pins on line 1, amber focus + non-wrapping key hint on line 2), so it never
//! grows into a 3-line block or orphans a single word.

use super::theme::Fonts;
use super::wood;
use bevy::prelude::*;

#[derive(Component)]
pub struct Strip;

#[derive(Component)]
pub struct StripText;

#[derive(Component)]
pub struct StripFocus;

#[derive(Component)]
pub struct StripHint;

/// Warm amber matching the focus ground ring (`throng::kit` `focus_mat`).
const FOCUS_INK: Color = Color::srgb(0.98, 0.78, 0.28);

/// Spawn the strip when heed comes on, take it away when it goes, and keep its words.
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn strip(
    mut commands: Commands,
    mut heed: Option<ResMut<crate::heed::Heed>>,
    fonts: Option<Res<Fonts>>,
    looks: Res<crate::looks::Looks>,
    binds: Res<crate::keys::Binds>,
    death: Res<super::model::HudModel>,
    roots: Query<Entity, With<Strip>>,
    mut texts: Query<(&mut Text, &mut TextColor), (With<StripText>, Without<StripFocus>, Without<StripHint>)>,
    mut focuses: Query<(&mut Text, &mut TextColor, &mut Node), (With<StripFocus>, Without<StripText>, Without<StripHint>)>,
    mut hints: Query<(&mut Text, &mut TextColor), (With<StripHint>, Without<StripText>, Without<StripFocus>)>,
    mut bgs: Query<(&mut BackgroundColor, &mut Node), (With<Strip>, Without<StripFocus>)>,
) {
    let on = heed.as_ref().is_some_and(|h| h.on);
    if !on {
        for e in &roots {
            commands.entity(e).despawn();
        }
        return;
    }
    let (Some(h), Some(f)) = (heed.as_deref_mut(), fonts) else { return };
    h.sync_pin_labels(&looks);
    if roots.is_empty() {
        commands
            .spawn((
                Strip,
                Node {
                    position_type: PositionType::Absolute,
                    left: Val::Px(16.0),
                    top: Val::Px(16.0),
                    max_width: Val::Px(960.0),
                    flex_direction: FlexDirection::Column,
                    align_items: AlignItems::FlexStart,
                    row_gap: Val::Px(3.0),
                    padding: UiRect::axes(Val::Px(12.0), Val::Px(7.0)),
                    border: wood::b(2.0),
                    border_radius: wood::r(8.0),
                    ..default()
                },
                BackgroundColor(wood::alpha(wood::float_or(wood::surface()), 0.9)),
                BorderColor::all(wood::edge()),
                GlobalZIndex(4),
                Pickable::IGNORE,
            ))
            .with_children(|p| {
                // Row 1: pins (single clean line; wraps only in extreme cases with wide 960 px cap).
                p.spawn((StripText, Text::new(""), f.body(13.0, 700), TextColor(wood::text()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                // Row 2: amber focus (when set) + non-wrapping key hint on one compact sub-line.
                p.spawn((
                    Node {
                        flex_direction: FlexDirection::Row,
                        flex_wrap: FlexWrap::NoWrap,
                        align_items: AlignItems::Baseline,
                        column_gap: Val::Px(14.0),
                        ..default()
                    },
                    Pickable::IGNORE,
                ))
                .with_children(|row| {
                    row.spawn((StripFocus, Text::new(""), f.body(12.5, 700), TextColor(FOCUS_INK), TextLayout::new(Justify::Left, LineBreak::NoWrap), Pickable::IGNORE));
                    row.spawn((StripHint, Text::new(""), f.body(11.5, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::NoWrap), Pickable::IGNORE));
                });
            });
        return;
    }
    let pin_name = |id: u32| h.pin_label(id, &looks).map(super::label).unwrap_or_else(|| format!("#{id}"));
    let focus_name = |id: u32| looks.short(id).map(super::label).unwrap_or_else(|| format!("#{id}"));
    let pins: Vec<String> = h.pins.iter().map(|p| pin_name(*p)).collect();
    let mut s = format!("Keeping track {}/{}", h.pins.len(), crate::heed::MAX_PINS);
    if !pins.is_empty() {
        s += ": ";
        s += &pins.join(" · ");
    }
    let focus_str = h.focus.map(|fo| format!("Focus: {}", focus_name(fo)));
    let hint = format!("{} pin or unpin · {} clear", binds.first(crate::keys::Act::Pin), binds.first(crate::keys::Act::ClearPins));
    for (mut t, mut c) in &mut texts {
        super::set_text(&mut t, &s);
        super::set_color(&mut c, wood::text());
    }
    for (mut t, mut c, mut n) in &mut focuses {
        match &focus_str {
            Some(fs) => {
                super::set_text(&mut t, fs);
                super::set_color(&mut c, FOCUS_INK);
                super::show(&mut n, true);
            }
            None => {
                super::set_text(&mut t, "");
                super::show(&mut n, false);
            }
        }
    }
    for (mut t, mut c) in &mut hints {
        super::set_text(&mut t, &hint);
        super::set_color(&mut c, wood::muted());
    }
    for (mut bg, mut n) in &mut bgs {
        super::set_bg(&mut bg, wood::alpha(wood::float_or(wood::surface()), 0.9));
        super::show(&mut n, death.death.is_none());
    }
}
