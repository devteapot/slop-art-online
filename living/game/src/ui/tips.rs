//! First-time hints: one short line each, shown for a few seconds and then faded (play-test 2:
//! the only "Enter: talk" was in the hidden F1 panel, and a key nobody explains is a feature
//! nobody finds). A hint shows once per session ([`Tips::once`]); [`Tips::show`] shows it again.
//! Lines stack, newest at the bottom, under the target frame at the top of the screen. Any part of the client
//! may add one: `tips.once(TEXT, now)`, with `now` in `Time` seconds.

use super::theme::{self, Fonts};
use super::{set_bg, set_color, set_text, show, HudRoot};
use bevy::prelude::*;
use std::collections::HashSet;

/// Talking (`talk.rs`): on arrival, and again the first time someone speaks to me.
pub const TALK: &str = "Enter — talk to the person you point at, or to the room";
/// How long a hint shows, and the fade at its end (s).
const SHOW_S: f64 = 6.0;
const FADE_S: f64 = 1.5;
const ROWS: usize = 3;

#[derive(Resource, Default)]
pub struct Tips {
    /// Hints showing: text, since when (s).
    lines: Vec<(String, f64)>,
    shown: HashSet<String>,
}

impl Tips {
    /// Show a hint unless it was shown this session.
    pub fn once(&mut self, text: &str, now: f64) {
        if self.shown.insert(text.to_string()) {
            self.show(text, now);
        }
    }

    /// Every hint may show again (Settings › Play, "Show tips again").
    pub fn again(&mut self, now: f64) {
        self.shown.clear();
        self.show(TALK, now);
    }

    /// Show a hint now (again).
    pub fn show(&mut self, text: &str, now: f64) {
        self.shown.insert(text.to_string());
        self.lines.retain(|(t, _)| t != text);
        self.lines.push((text.to_string(), now));
        if self.lines.len() > ROWS {
            self.lines.remove(0);
        }
    }
}

#[derive(Component)]
pub struct TipRow(usize);
#[derive(Component)]
pub struct TipText(usize);

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = fonts.clone();
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(88.0), flex_direction: FlexDirection::Column, align_items: AlignItems::Center, row_gap: Val::Px(4.0), ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            for i in 0..ROWS {
                root.spawn((TipRow(i), Node { padding: UiRect::axes(Val::Px(14.0), Val::Px(5.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(999.0)), display: Display::None, ..default() }, theme::panel(999.0), Pickable::IGNORE))
                    .with_child((TipText(i), Text::new(""), f.body(15.0, 700), TextColor(theme::GOLD), Pickable::IGNORE));
            }
        });
}

/// Hints fade out after [`SHOW_S`]; none while the text box is open or on the death screen.
#[allow(clippy::type_complexity)]
pub fn update(
    mut tips: ResMut<Tips>,
    time: Res<Time>,
    input: Res<crate::controls::Input>,
    model: Res<super::model::HudModel>,
    mut rows: Query<(&TipRow, &mut Node, &mut BackgroundColor, &mut BorderColor)>,
    mut texts: Query<(&TipText, &mut Text, &mut TextColor)>,
) {
    let now = time.elapsed_secs_f64();
    tips.lines.retain(|(_, at)| now - at < SHOW_S);
    let hidden = input.chat_open || model.death.is_some();
    let alpha = |at: f64| ((SHOW_S - (now - at)) / FADE_S).clamp(0.0, 1.0) as f32;
    for (r, mut n, mut bg, mut border) in &mut rows {
        let line = tips.lines.get(r.0).filter(|_| !hidden);
        show(&mut n, line.is_some());
        if let Some((_, at)) = line {
            set_bg(&mut bg, theme::with_alpha(theme::INK, 0.85 * alpha(*at)));
            let c = theme::with_alpha(theme::GOLD_DIM, alpha(*at));
            if border.top != c {
                *border = BorderColor::all(c);
            }
        }
    }
    for (r, mut t, mut c) in &mut texts {
        if let Some((text, at)) = tips.lines.get(r.0) {
            set_text(&mut t, text);
            set_color(&mut c, theme::with_alpha(theme::GOLD, alpha(*at)));
        }
    }
}
