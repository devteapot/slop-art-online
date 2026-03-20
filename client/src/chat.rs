use bevy::ecs::message::MessageReader;
use bevy::input::keyboard::{Key, KeyboardInput};
use bevy::prelude::*;
use shared::module_bindings::send_chat_message_reducer::send_chat_message;

use crate::constants::CHAT_PROXIMITY_RANGE;
use crate::nameplate::NpcInfo;
use crate::network::{ChatMessageEvent, ExtraEventQueues, NpcChatEvent, SpacetimeDb};
use crate::npc::NpcId;
use crate::player::LocalPlayer;

// --- Resources ---

#[derive(Resource, Default)]
pub struct ChatInputActive(pub bool);

#[derive(Resource, Default)]
pub struct ChatInputBuffer(pub String);

// --- Components ---

#[derive(Component)]
pub struct ChatPanel;

#[derive(Component)]
pub struct ChatLogContainer;

#[derive(Component)]
pub struct ChatInputBar;

#[derive(Component)]
pub struct ChatInputText;

/// Tags a UI text node in the chat log with its server scheduled_id.
#[derive(Component)]
pub struct ChatLogLine(pub u64);

// --- Systems ---

pub fn sync_chat_messages(
    mut commands: Commands,
    extra_queues: Res<ExtraEventQueues>,
    local_player: Query<&Transform, With<LocalPlayer>>,
    container: Query<Entity, With<ChatLogContainer>>,
    log_lines: Query<(Entity, &ChatLogLine)>,
    npcs: Query<(&NpcId, &NpcInfo)>,
) {
    let local_pos = local_player.single().ok().map(|t| t.translation);

    // Player chat messages
    let mut player_events = extra_queues.chat_messages.0.lock().unwrap();
    for event in player_events.drain(..) {
        match event {
            ChatMessageEvent::Inserted(msg) => {
                let msg_pos = Vec3::new(msg.position.x, msg.position.y, msg.position.z);

                let in_range = local_pos
                    .map(|lp| lp.distance(msg_pos) <= CHAT_PROXIMITY_RANGE)
                    .unwrap_or(false);

                if in_range {
                    let name = if msg.sender_name.is_empty() {
                        "Player"
                    } else {
                        &msg.sender_name
                    };
                    if let Ok(container_entity) = container.single() {
                        let child = commands.spawn((
                            ChatLogLine(msg.scheduled_id),
                            Text::new(format!("{}: {}", name, msg.text)),
                            TextFont { font_size: 13.0, ..default() },
                            TextColor(Color::srgba(0.9, 0.9, 0.9, 0.9)),
                        )).id();
                        commands.entity(container_entity).add_child(child);
                    }
                }
            }
            ChatMessageEvent::Deleted(scheduled_id) => {
                for (entity, line) in log_lines.iter() {
                    if line.0 == scheduled_id {
                        commands.entity(entity).despawn();
                    }
                }
            }
        }
    }
    drop(player_events);

    // NPC chat messages (same UI, proximity filtered)
    let mut npc_events = extra_queues.npc_chat_messages.0.lock().unwrap();
    for event in npc_events.drain(..) {
        match event {
            NpcChatEvent::Inserted(msg) => {
                let msg_pos = Vec3::new(msg.position.x, msg.position.y, msg.position.z);

                let in_range = local_pos
                    .map(|lp| lp.distance(msg_pos) <= CHAT_PROXIMITY_RANGE)
                    .unwrap_or(false);

                if in_range {
                    // Look up NPC name from entities
                    let npc_name = npcs.iter()
                        .find(|(id, _)| id.0 == msg.npc_id)
                        .map(|(_, info)| info.name.as_str())
                        .unwrap_or("NPC");

                    if let Ok(container_entity) = container.single() {
                        let child = commands.spawn((
                            ChatLogLine(msg.scheduled_id),
                            Text::new(format!("{}: {}", npc_name, msg.text)),
                            TextFont { font_size: 13.0, ..default() },
                            TextColor(Color::srgba(0.7, 0.9, 1.0, 0.9)),
                        )).id();
                        commands.entity(container_entity).add_child(child);
                    }
                }
            }
            NpcChatEvent::Deleted(scheduled_id) => {
                for (entity, line) in log_lines.iter() {
                    if line.0 == scheduled_id {
                        commands.entity(entity).despawn();
                    }
                }
            }
        }
    }
}

pub fn chat_input(
    mut chat_active: ResMut<ChatInputActive>,
    mut chat_buffer: ResMut<ChatInputBuffer>,
    conn: Option<Res<SpacetimeDb>>,
    mut key_events: MessageReader<KeyboardInput>,
) {
    if !chat_active.0 {
        for ev in key_events.read() {
            if ev.state.is_pressed() && ev.key_code == KeyCode::Enter {
                chat_active.0 = true;
                chat_buffer.0.clear();
                return;
            }
        }
        return;
    }

    for ev in key_events.read() {
        if !ev.state.is_pressed() {
            continue;
        }
        match &ev.logical_key {
            Key::Escape => {
                chat_active.0 = false;
                chat_buffer.0.clear();
                return;
            }
            Key::Enter => {
                let text = chat_buffer.0.trim().to_string();
                if !text.is_empty() {
                    if let Some(conn) = &conn {
                        let _ = conn.0.reducers.send_chat_message(text);
                    }
                }
                chat_active.0 = false;
                chat_buffer.0.clear();
                return;
            }
            Key::Backspace => {
                chat_buffer.0.pop();
            }
            Key::Space => {
                chat_buffer.0.push(' ');
            }
            Key::Character(s) => {
                chat_buffer.0.push_str(s.as_str());
            }
            _ => {}
        }
    }
}

// --- UI ---

pub fn setup_chat_panel(mut commands: Commands) {
    commands
        .spawn((
            ChatPanel,
            Node {
                position_type: PositionType::Absolute,
                bottom: Val::Px(250.0),
                left: Val::Px(16.0),
                width: Val::Px(400.0),
                max_height: Val::Px(220.0),
                flex_direction: FlexDirection::Column,
                padding: UiRect::all(Val::Px(8.0)),
                ..default()
            },
            BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.4)),
        ))
        .with_children(|panel| {
            // Scrollable chat log
            panel.spawn((
                ChatLogContainer,
                Node {
                    flex_direction: FlexDirection::Column,
                    row_gap: Val::Px(1.0),
                    flex_grow: 1.0,
                    overflow: Overflow::scroll_y(),
                    ..default()
                },
            ));

            // Input bar
            panel.spawn((
                ChatInputBar,
                Node {
                    margin: UiRect::top(Val::Px(4.0)),
                    padding: UiRect::all(Val::Px(4.0)),
                    ..default()
                },
                BackgroundColor(Color::srgba(0.1, 0.1, 0.1, 0.6)),
            )).with_children(|bar| {
                bar.spawn((
                    ChatInputText,
                    Text::new("Press Enter to chat"),
                    TextFont { font_size: 13.0, ..default() },
                    TextColor(Color::srgba(0.6, 0.6, 0.6, 0.8)),
                ));
            });
        });
}

pub fn update_chat_panel(
    chat_active: Res<ChatInputActive>,
    chat_buffer: Res<ChatInputBuffer>,
    mut input_text: Query<(&mut Text, &mut TextColor), With<ChatInputText>>,
) {
    if let Ok((mut text, mut color)) = input_text.single_mut() {
        if chat_active.0 {
            if chat_buffer.0.is_empty() {
                text.0 = "|".to_string();
            } else {
                text.0 = format!("{}|", chat_buffer.0);
            }
            *color = TextColor(Color::WHITE);
        } else {
            text.0 = "Press Enter to chat".to_string();
            *color = TextColor(Color::srgba(0.6, 0.6, 0.6, 0.8));
        }
    }
}
