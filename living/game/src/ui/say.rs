//! Talking in interface D: the words you type live in the window of whom you address, not in a
//! chat box (the box of play-test 2 is gone).
//!
//! - **Enter** opens the box (`talk.rs`, the owner's rule): to the person under the cursor,
//!   whose window opens with the box in it ("To a child in red"); with nobody under the cursor,
//!   to the room, in Log and people ("To the room").
//! - **Tab** goes to the next person within earshot, nearest first, then back to the room; the
//!   window follows.
//! - **Enter** says it (`human_say` with `to`), the window stays with the conversation; **Esc**
//!   closes the box and its window (`win.rs`'s Esc order).
//! - A click in a window's box types to whom it names; a tap on a peaceful person opens the box
//!   to them (`combat.rs`), as F on them does (`verbs.rs`).
//! - Words an act asks for (write, found) are typed in a small bar over the cluster.

use super::model::{HudModel, Outbox};
use super::theme::Fonts;
use super::win::{Win, Windows};
use super::{set_text, show, wood, HudRoot};
use crate::controls::Input;
use bevy::input::keyboard::{Key as LogicalKey, KeyboardInput};
use bevy::input::ButtonState;
use bevy::prelude::*;

const MAX_CHARS: usize = 400;

/// Where the words being typed are shown.
#[derive(Resource, Default)]
pub struct Typing {
    /// The window holding the box while it is open.
    pub window: Option<Win>,
}

/// Enter opens the box; typing edits it; Tab speaks to someone else; Enter says it to whom it
/// addresses (`talk.rs`). Esc is `win.rs`'s.
#[allow(clippy::too_many_arguments)]
pub fn keys(mut input: ResMut<Input>, keys: Res<ButtonInput<KeyCode>>, binds: Res<crate::keys::Binds>, mut events: MessageReader<KeyboardInput>, mut out: ResMut<Outbox>, wants: Option<Res<crate::hud::UiWants>>, model: Res<HudModel>, mut talk: Option<ResMut<crate::talk::Talk>>, (ws, pick): (Res<Windows>, Res<crate::pick::Pick>)) {
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
        if binds.just_pressed(crate::keys::Act::Talk, &keys) && !egui_typing {
            input.chat_open = true;
            input.chat.clear();
            // The person under the cursor is whom Enter speaks to; nobody there, the room. The
            // same pick as the hover and the nameplate (`pick.rs`), so Enter never speaks to
            // someone other than the one named under the cursor.
            if let Some(t) = talk.as_mut() {
                t.prefer = pick.under.filter(|id| model.actors.iter().any(|a| a.id == *id as u64 && a.kind_person));
            }
            let _ = &ws;
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
                    out.say.push((line.trim().to_string(), talk.as_ref().and_then(|t| t.to).unwrap_or(0)));
                }
                input.chat_open = false;
                return;
            }
            LogicalKey::Backspace => {
                input.chat.pop();
            }
            LogicalKey::Tab => {
                if let Some(t) = talk.as_mut() {
                    t.cycle = true;
                }
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

/// The box lives in its addressee's window: open it there, and follow Tab.
pub fn follow(input: Res<Input>, talk: Option<Res<crate::talk::Talk>>, mut ws: ResMut<Windows>, mut typing: ResMut<Typing>) {
    if !input.chat_open || input.compose.is_some() {
        typing.window = None;
        return;
    }
    let Some(talk) = talk else { return };
    if !talk.resolved {
        return;
    }
    let want = talk.to.map_or(Win::Log, Win::Person);
    if typing.window != Some(want) || !ws.is_open(want) {
        ws.open(want);
        typing.window = Some(want);
    }
}

#[derive(Component)]
pub struct ComposeBar;
#[derive(Component)]
pub struct ComposeLabel;
#[derive(Component)]
pub struct ComposeText;

/// The small bar for an act's words, over the cluster.
pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = &*fonts;
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), bottom: Val::Px(170.0), justify_content: JustifyContent::Center, ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            root.spawn((ComposeBar, super::hit::Block, Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(10.0), padding: UiRect::axes(Val::Px(12.0), Val::Px(8.0)), border: wood::b(3.0), border_radius: wood::r(12.0), min_width: Val::Px(420.0), display: Display::None, ..default() }, wood::wood()))
                .with_children(|b| {
                    b.spawn(wood::rim(9.0));
                    b.spawn((ComposeLabel, Text::new(""), wood::title(f, 16.0), Pickable::IGNORE));
                    b.spawn((Node { flex_grow: 1.0, padding: UiRect::axes(Val::Px(8.0), Val::Px(4.0)), border: wood::b(2.0), border_radius: wood::r(8.0), ..default() }, BackgroundColor(wood::field()), BorderColor::all(wood::edge()), Pickable::IGNORE))
                        .with_child((ComposeText, Text::new(""), wood::ink(f, 14.0, 650), Pickable::IGNORE));
                    wood::chip(b, f, "Enter", ());
                });
        });
}

pub fn update(input: Res<Input>, time: Res<Time>, mut bar: Query<&mut Node, With<ComposeBar>>, mut label: Query<&mut Text, (With<ComposeLabel>, Without<ComposeText>)>, mut text: Query<&mut Text, (With<ComposeText>, Without<ComposeLabel>)>) {
    let on = input.chat_open && input.compose.is_some();
    for mut n in &mut bar {
        show(&mut n, on);
    }
    if let Some(c) = input.compose.as_deref() {
        for mut t in &mut label {
            set_text(&mut t, &super::label(c));
        }
        let caret = if crate::capture::scripted() || (time.elapsed_secs() * 1.8).fract() < 0.6 { "|" } else { " " };
        for mut t in &mut text {
            set_text(&mut t, &format!("{}{caret}", input.chat));
        }
    }
}
