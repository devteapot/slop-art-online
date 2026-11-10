//! Proximity chat: the log of what you heard (bottom left) and the input Enter opens.
//!
//! The log holds only lines your character heard, plus your own; the authority decides who is
//! within earshot (`perceive::speak`). Lines fade after a while unless the chat is open.

use super::model::*;
use super::theme::{self, Fonts};
use super::{set_bg, set_color, set_text, show, HudRoot};
use crate::controls::Input;
use bevy::input::keyboard::{Key as LogicalKey, KeyboardInput};
use bevy::input::ButtonState;
use bevy::prelude::*;
use bevy::ui::BoxShadow;

const ROWS: usize = 8;
const MAX_CHARS: usize = 400;

#[derive(Component)]
pub struct ChatPanel;
#[derive(Component)]
pub struct LogRow(usize);
#[derive(Component)]
pub struct LogWho(usize);
#[derive(Component)]
pub struct LogMsg(usize);
#[derive(Component)]
pub struct InputRow;
#[derive(Component)]
pub struct InputText;
#[derive(Component)]
pub struct InputLabel;

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = fonts.clone();
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(20.0), bottom: Val::Px(20.0), width: Val::Px(430.0), flex_direction: FlexDirection::Column, ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            root.spawn((
                ChatPanel,
                Node { flex_direction: FlexDirection::Column, row_gap: Val::Px(3.0), padding: UiRect::new(Val::Px(12.0), Val::Px(12.0), Val::Px(8.0), Val::Px(9.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(12.0)), ..default() },
                BackgroundColor(theme::INK),
                BorderColor::all(theme::EDGE),
            ))
            .with_children(|p| {
                for i in 0..ROWS {
                    p.spawn((LogRow(i), Text::new(""), f.body(14.0, 600), TextColor(theme::TEXT), theme::text_shadow(), TextLayout::new(Justify::Left, LineBreak::WordBoundary)))
                        .with_children(|t| {
                            t.spawn((LogWho(i), TextSpan::new(""), f.body(14.0, 800), TextColor(theme::TALK)));
                            t.spawn((LogMsg(i), TextSpan::new(""), f.body(14.0, 550), TextColor(theme::TEXT)));
                        });
                }
            });
            root.spawn((
                InputRow,
                Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(8.0), margin: UiRect::top(Val::Px(6.0)), padding: UiRect::new(Val::Px(6.0), Val::Px(12.0), Val::Px(6.0), Val::Px(6.0)), border: UiRect::all(Val::Px(1.5)), border_radius: BorderRadius::all(Val::Px(11.0)), display: Display::None, ..default() },
                BackgroundColor(theme::INK_SOLID),
                BorderColor::all(theme::GOLD_DIM),
                BoxShadow::new(theme::SHADOW, Val::ZERO, Val::Px(3.0), Val::ZERO, Val::Px(12.0)),
            ))
            .with_children(|r| {
                r.spawn((Node { padding: UiRect::axes(Val::Px(8.0), Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(7.0)), ..default() }, BackgroundColor(theme::with_alpha(theme::GOLD, 0.18))))
                    .with_child((InputLabel, Text::new("Say"), f.body(13.0, 800), TextColor(theme::GOLD)));
                r.spawn((InputText, Text::new(""), f.body(15.0, 600), TextColor(theme::TEXT), Node { flex_grow: 1.0, ..default() }));
            });
        });
}

/// Enter opens the input; typing edits it; Enter says it, Esc cancels.
pub fn keys(mut input: ResMut<Input>, keys: Res<ButtonInput<KeyCode>>, mut events: MessageReader<KeyboardInput>, mut out: ResMut<Outbox>, wants: Option<Res<crate::hud::UiWants>>, model: Res<HudModel>) {
    if model.death.is_some() {
        events.clear();
        return;
    }
    if !input.chat_open {
        // An act asks for words (`verbs.rs`): open for them, without the key that chose it.
        if input.compose.is_some() {
            input.chat_open = true;
            input.chat.clear();
            events.clear();
            return;
        }
        // egui (F1 panels) may hold the keyboard.
        let egui_typing = wants.is_some_and(|w| w.keyboard);
        if keys.just_pressed(KeyCode::Enter) && !egui_typing {
            input.chat_open = true;
            input.chat.clear();
        }
        events.clear();
        return;
    }
    for ev in events.read() {
        if ev.state != ButtonState::Pressed {
            continue;
        }
        match &ev.logical_key {
            LogicalKey::Enter => {
                let line = std::mem::take(&mut input.chat);
                // Words for an act (`verbs.rs`), else speech.
                if input.compose.take().is_some() {
                    input.composed = Some(line.trim().to_string());
                } else if !line.trim().is_empty() {
                    out.say.push(line.trim().to_string());
                }
                input.chat_open = false;
                return;
            }
            LogicalKey::Escape => {
                input.chat.clear();
                input.chat_open = false;
                input.compose = None;
                return;
            }
            LogicalKey::Backspace => {
                input.chat.pop();
            }
            LogicalKey::Space => {
                if input.chat.chars().count() < MAX_CHARS {
                    input.chat.push(' ');
                }
            }
            LogicalKey::Character(s) => {
                for c in s.chars().filter(|c| !c.is_control()) {
                    if input.chat.chars().count() < MAX_CHARS {
                        input.chat.push(c);
                    }
                }
            }
            _ => {}
        }
    }
}

#[allow(clippy::type_complexity)]
pub fn update(
    model: Res<HudModel>,
    input: Res<Input>,
    time: Res<Time>,
    mut panel: Query<(&mut BackgroundColor, &mut BorderColor), With<ChatPanel>>,
    mut rows: Query<(&LogRow, &mut Node), Without<InputRow>>,
    mut who: Query<(&LogWho, &mut TextSpan, &mut TextColor), Without<LogMsg>>,
    mut msg: Query<(&LogMsg, &mut TextSpan, &mut TextColor), Without<LogWho>>,
    mut input_row: Query<&mut Node, (With<InputRow>, Without<LogRow>)>,
    mut input_text: Query<(&mut Text, &mut TextColor), (With<InputText>, Without<LogWho>, Without<LogMsg>, Without<InputLabel>)>,
    mut input_label: Query<&mut Text, (With<InputLabel>, Without<InputText>)>,
) {
    let open = input.chat_open && model.death.is_none();
    let now = model.now;
    let start = model.log.len().saturating_sub(ROWS);
    let lines = &model.log[start..];
    // New speech shows for 10 s, fading over its last 3; the log stays while the input is open.
    let alpha = |at: f64| if open { 1.0 } else { (1.0 - ((now - at) as f32 - 7.0) / 3.0).clamp(0.0, 1.0) };
    let newest = lines.last().map_or(0.0, |l| alpha(l.at));
    let panel_a = if model.death.is_some() { 0.0 } else if open { 1.0 } else { newest };
    for (mut bg, mut border) in &mut panel {
        set_bg(&mut bg, theme::with_alpha(theme::INK, panel_a * 0.7));
        let c = theme::with_alpha(theme::EDGE, panel_a);
        if border.top != c {
            *border = BorderColor::all(c);
        }
    }
    for (r, mut n) in &mut rows {
        show(&mut n, r.0 < lines.len() && alpha(lines[r.0].at) > 0.01 && model.death.is_none());
    }
    for (w, mut span, mut c) in &mut who {
        let Some(l) = lines.get(w.0) else { continue };
        let text = match l.kind {
            LogKind::ToMe => format!("{} (to you): ", l.who),
            _ => format!("{}: ", l.who),
        };
        if span.0 != text {
            span.0 = text;
        }
        let col = match l.kind {
            LogKind::Mine => theme::GOLD,
            LogKind::ToMe => Color::srgb(0.78, 0.9, 1.0),
            LogKind::Heard => theme::TALK,
        };
        set_color(&mut c, theme::with_alpha(col, alpha(l.at)));
    }
    for (m, mut span, mut c) in &mut msg {
        let Some(l) = lines.get(m.0) else { continue };
        if span.0 != l.text {
            span.0 = l.text.clone();
        }
        set_color(&mut c, theme::with_alpha(theme::TEXT, alpha(l.at)));
    }
    for mut n in &mut input_row {
        show(&mut n, open);
    }
    for mut t in &mut input_label {
        set_text(&mut t, input.compose.as_deref().map_or("Say", |c| c));
    }
    if open {
        let caret = if crate::capture::scripted() || (time.elapsed_secs() * 1.8).fract() < 0.6 { "|" } else { " " };
        for (mut t, mut c) in &mut input_text {
            set_text(&mut t, &format!("{}{caret}", input.chat));
            set_color(&mut c, theme::TEXT);
        }
    }
}
