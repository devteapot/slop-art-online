//! The keeping-track strip (heed for players, `heed.rs`): a line at the top left naming whom I
//! keep track of (my pins, out of [`crate::heed::MAX_PINS`]) and my focus, and the keys. Only
//! while the world's laws let players heed: off, nothing is spawned.

use super::theme::Fonts;
use super::wood;
use bevy::prelude::*;

#[derive(Component)]
pub struct Strip;

#[derive(Component)]
pub struct StripText;

#[derive(Component)]
pub struct StripHint;

/// Spawn the strip when heed comes on, take it away when it goes, and keep its words.
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn strip(
    mut commands: Commands,
    heed: Option<Res<crate::heed::Heed>>,
    fonts: Option<Res<Fonts>>,
    looks: Res<crate::looks::Looks>,
    binds: Res<crate::keys::Binds>,
    death: Res<super::model::HudModel>,
    roots: Query<Entity, With<Strip>>,
    mut texts: Query<(&mut Text, &mut TextColor), (With<StripText>, Without<StripHint>)>,
    mut hints: Query<(&mut Text, &mut TextColor), (With<StripHint>, Without<StripText>)>,
    mut bgs: Query<(&mut BackgroundColor, &mut Node), With<Strip>>,
) {
    let on = heed.as_ref().is_some_and(|h| h.on);
    if !on {
        for e in &roots {
            commands.entity(e).despawn();
        }
        return;
    }
    let (Some(h), Some(f)) = (heed, fonts) else { return };
    if roots.is_empty() {
        commands
            .spawn((
                Strip,
                Node {
                    position_type: PositionType::Absolute,
                    left: Val::Px(16.0),
                    top: Val::Px(16.0),
                    max_width: Val::Px(840.0),
                    flex_direction: FlexDirection::Row,
                    flex_wrap: FlexWrap::Wrap,
                    align_items: AlignItems::Baseline,
                    column_gap: Val::Px(12.0),
                    row_gap: Val::Px(2.0),
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
                p.spawn((StripText, Text::new(""), f.body(13.0, 700), TextColor(wood::text()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                p.spawn((StripHint, Text::new(""), f.body(12.0, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::NoWrap), Pickable::IGNORE));
            });
        return;
    }
    let name = |id: u32| looks.short(id).map(|s| super::label(s)).unwrap_or_else(|| format!("#{id}"));
    let pins: Vec<String> = h.pins.iter().map(|p| name(*p)).collect();
    let mut s = format!("Keeping track {}/{}", h.pins.len(), crate::heed::MAX_PINS);
    if !pins.is_empty() {
        s += ": ";
        s += &pins.join(" · ");
    }
    if let Some(fo) = h.focus {
        s += &format!("  —  focus: {}", name(fo));
    }
    let hint = format!("{} pin or unpin · {} clear", binds.first(crate::keys::Act::Pin), binds.first(crate::keys::Act::ClearPins));
    for (mut t, mut c) in &mut texts {
        super::set_text(&mut t, &s);
        super::set_color(&mut c, wood::text());
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
