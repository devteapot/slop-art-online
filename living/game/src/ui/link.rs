//! The connection notice: while a connection that was live is lost and being restored, a small
//! pill at the top centre says so. No one is drawn meanwhile (`bodies.rs`, `live.rs`), so the
//! empty street reads as being offline, not as a world where everyone stood still.

use super::model::*;
use super::theme::{self, Fonts};
use super::{set_text, show, HudRoot};
use bevy::prelude::*;

#[derive(Component)]
pub struct LinkRoot;
#[derive(Component)]
pub struct LinkText;

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = fonts.clone();
    commands
        .spawn((
            HudRoot,
            Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(22.0), justify_content: JustifyContent::Center, display: Display::None, ..default() },
            LinkRoot,
            Pickable::IGNORE,
        ))
        .with_children(|root| {
            root.spawn((
                Node { padding: UiRect::axes(Val::Px(18.0), Val::Px(8.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(999.0)), ..default() },
                BackgroundColor(theme::INK_SOLID),
                BorderColor::all(theme::with_alpha(theme::HOSTILE, 0.55)),
            ))
            .with_child((LinkText, Text::new(""), f.body(15.0, 700), TextColor(theme::TEXT), theme::text_shadow()));
        });
}

pub fn update(model: Res<HudModel>, mut root: Query<&mut Node, With<LinkRoot>>, mut text: Query<&mut Text, With<LinkText>>) {
    for mut n in &mut root {
        show(&mut n, model.link.is_some());
    }
    if let Some(l) = &model.link {
        for mut t in &mut text {
            set_text(&mut t, l);
        }
    }
}
