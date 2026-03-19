use bevy::prelude::*;
use std::collections::HashMap;
use std::f32::consts::TAU;

use shared::module_bindings::drop_item_reducer::drop_item;
use shared::module_bindings::equip_item_reducer::equip_item;
use shared::module_bindings::unequip_item_reducer::unequip_item;
use shared::module_bindings::drop_equipped_item_reducer::drop_equipped_item;
use shared::module_bindings::pickup_item_reducer::pickup_item;
use shared::module_bindings::use_item_reducer::use_item;
use shared::module_bindings::EquipSlot;

use crate::constants::PICKUP_RANGE;
use crate::chat::ChatInputActive;
use crate::network::{
    ConsumableDefEvent, EquipmentDefEvent, EquippedItemEvent, ExtraEventQueues,
    GroundItemEvent, GroundItemEventQueue, InventoryItemEvent, InventoryItemEventQueue,
    ItemDefEvent, ItemDefEventQueue, LocalIdentity, SpacetimeDb,
};
use crate::player::LocalPlayer;

// --- Resources ---

#[derive(Resource, Default)]
pub struct ItemDefMap(pub HashMap<u64, String>);

#[derive(Resource, Default)]
pub struct ItemRarityMap(pub HashMap<u64, String>);

/// slot → (inv_item_id, item_def_id, quantity)
#[derive(Resource, Default)]
pub struct LocalInventory(pub HashMap<i32, (u64, u64, i32)>);

#[derive(Resource, Default)]
pub struct InventoryOpen(pub bool);

pub struct EquipmentDefData {
    pub max_durability: i32,
    pub bonus_health: i32,
    pub bonus_mana: i32,
    pub bonus_stamina: i32,
    pub bonus_attack: i32,
    pub bonus_defense: i32,
}

#[derive(Resource, Default)]
pub struct EquipmentDefMap(pub HashMap<u64, EquipmentDefData>);

/// Maps equip slot index (0-5) -> (equipped_item_id, item_def_id, durability, max_durability)
#[derive(Resource, Default)]
pub struct LocalEquipment(pub HashMap<i32, (u64, u64, i32, i32)>);

/// Maps item_def_id -> item_type name for identifying equipment in inventory
#[derive(Resource, Default)]
pub struct ItemTypeMap(pub HashMap<u64, String>);

pub struct ConsumableDefData {
    pub power: i32,
    pub effect_label: String,
}

#[derive(Resource, Default)]
pub struct ConsumableDefMap(pub HashMap<u64, ConsumableDefData>);

// --- Components ---

#[derive(Component)]
pub struct GroundItemMarker(pub u64);

#[derive(Component)]
pub struct InventoryPanel;

#[derive(Component)]
pub struct InventorySlotNode(pub i32);

#[derive(Component)]
pub struct InventorySlotLabel(pub i32);

#[derive(Component)]
pub struct InventoryCloseButton;

#[derive(Component)]
pub struct EquipmentSlotNode(pub i32);

#[derive(Component)]
pub struct EquipmentSlotLabel(pub i32);

#[derive(Component)]
pub struct DurabilityBar(pub i32);

// --- Sync systems ---

pub fn sync_item_defs(
    queue: Res<ItemDefEventQueue>,
    mut item_map: ResMut<ItemDefMap>,
    mut rarity_map: ResMut<ItemRarityMap>,
    mut type_map: ResMut<ItemTypeMap>,
) {
    let mut events = queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            ItemDefEvent::Inserted(def) => {
                item_map.0.insert(def.id, def.name.clone());
                let rarity_name = format!("{:?}", def.rarity);
                rarity_map.0.insert(def.id, rarity_name);
                let type_name = format!("{:?}", def.item_type);
                type_map.0.insert(def.id, type_name);
            }
        }
    }
}

pub fn sync_inventory(
    queue: Res<InventoryItemEventQueue>,
    local_identity: Res<LocalIdentity>,
    mut local_inv: ResMut<LocalInventory>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let mut events = queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            InventoryItemEvent::Inserted(inv) => {
                if local_id.as_ref() == Some(&inv.player_identity) {
                    local_inv.0.insert(inv.slot, (inv.id, inv.item_def_id, inv.quantity));
                }
            }
            InventoryItemEvent::Updated(inv) => {
                if local_id.as_ref() == Some(&inv.player_identity) {
                    local_inv.0.insert(inv.slot, (inv.id, inv.item_def_id, inv.quantity));
                }
            }
            InventoryItemEvent::Deleted(inv) => {
                if local_id.as_ref() == Some(&inv.player_identity) {
                    local_inv.0.remove(&inv.slot);
                }
            }
        }
    }
}

pub fn sync_equipment_defs(
    queues: Res<ExtraEventQueues>,
    mut equip_map: ResMut<EquipmentDefMap>,
) {
    let mut events = queues.equipment_defs.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            EquipmentDefEvent::Inserted(def) => {
                equip_map.0.insert(def.item_def_id, EquipmentDefData {
                    max_durability: def.max_durability,
                    bonus_health: def.bonus_health,
                    bonus_mana: def.bonus_mana,
                    bonus_stamina: def.bonus_stamina,
                    bonus_attack: def.bonus_attack,
                    bonus_defense: def.bonus_defense,
                });
            }
        }
    }
}

pub fn sync_consumable_defs(
    queues: Res<ExtraEventQueues>,
    mut consumable_map: ResMut<ConsumableDefMap>,
) {
    let mut events = queues.consumable_defs.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            ConsumableDefEvent::Inserted(def) => {
                let effect_label = match format!("{:?}", def.effect).as_str() {
                    "RestoreHealth" => "HP",
                    "RestoreMana" => "MP",
                    "RestoreStamina" => "SP",
                    _ => "?",
                }.to_string();
                consumable_map.0.insert(def.item_def_id, ConsumableDefData {
                    power: def.power,
                    effect_label,
                });
            }
        }
    }
}

fn equip_slot_index(slot: &EquipSlot) -> i32 {
    match slot {
        EquipSlot::Weapon => 0,
        EquipSlot::Helmet => 1,
        EquipSlot::Chest => 2,
        EquipSlot::Legs => 3,
        EquipSlot::Boots => 4,
        EquipSlot::Accessory => 5,
    }
}

pub fn sync_equipped_items(
    queues: Res<ExtraEventQueues>,
    local_identity: Res<LocalIdentity>,
    equip_def_map: Res<EquipmentDefMap>,
    mut local_equip: ResMut<LocalEquipment>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let mut events = queues.equipped_items.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            EquippedItemEvent::Inserted(eq) => {
                if local_id.as_ref() == Some(&eq.player_identity) {
                    let slot_idx = equip_slot_index(&eq.equip_slot);
                    let max_dur = equip_def_map.0.get(&eq.item_def_id)
                        .map(|d| d.max_durability).unwrap_or(eq.durability);
                    local_equip.0.insert(slot_idx, (eq.id, eq.item_def_id, eq.durability, max_dur));
                }
            }
            EquippedItemEvent::Updated(eq) => {
                if local_id.as_ref() == Some(&eq.player_identity) {
                    let slot_idx = equip_slot_index(&eq.equip_slot);
                    let max_dur = equip_def_map.0.get(&eq.item_def_id)
                        .map(|d| d.max_durability).unwrap_or(eq.durability);
                    local_equip.0.insert(slot_idx, (eq.id, eq.item_def_id, eq.durability, max_dur));
                }
            }
            EquippedItemEvent::Deleted(eq) => {
                if local_id.as_ref() == Some(&eq.player_identity) {
                    let slot_idx = equip_slot_index(&eq.equip_slot);
                    local_equip.0.remove(&slot_idx);
                }
            }
        }
    }
}

fn equipment_stat_line(data: &EquipmentDefData) -> String {
    let mut parts = Vec::new();
    if data.bonus_health != 0 { parts.push(format!("+{} HP", data.bonus_health)); }
    if data.bonus_mana != 0 { parts.push(format!("+{} MP", data.bonus_mana)); }
    if data.bonus_stamina != 0 { parts.push(format!("+{} SP", data.bonus_stamina)); }
    if data.bonus_attack != 0 { parts.push(format!("+{} ATK", data.bonus_attack)); }
    if data.bonus_defense != 0 { parts.push(format!("+{} DEF", data.bonus_defense)); }
    parts.join(" ")
}

fn rarity_color(rarity: &str) -> Color {
    match rarity {
        "Uncommon" => Color::srgb(0.2, 0.8, 0.2),
        "Rare" => Color::srgb(0.3, 0.5, 1.0),
        "Epic" => Color::srgb(0.7, 0.2, 0.9),
        _ => Color::srgb(0.8, 0.8, 0.8), // Common
    }
}

fn rarity_emissive(rarity: &str) -> LinearRgba {
    match rarity {
        "Uncommon" => LinearRgba::new(0.2, 0.8, 0.2, 1.0),
        "Rare" => LinearRgba::new(0.3, 0.5, 1.0, 1.0),
        "Epic" => LinearRgba::new(0.7, 0.2, 0.9, 1.0),
        _ => LinearRgba::new(0.8, 0.8, 0.8, 1.0),
    }
}

pub fn sync_ground_items(
    mut commands: Commands,
    queue: Res<GroundItemEventQueue>,
    rarity_map: Res<ItemRarityMap>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    existing: Query<(Entity, &GroundItemMarker)>,
) {
    let mut events = queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            GroundItemEvent::Inserted(gi) => {
                let rarity = rarity_map
                    .0
                    .get(&gi.item_def_id)
                    .map(|s| s.as_str())
                    .unwrap_or("Common");
                let emissive = rarity_emissive(rarity);
                let base = rarity_color(rarity);
                commands.spawn((
                    GroundItemMarker(gi.scheduled_id),
                    Mesh3d(meshes.add(Cuboid::new(0.3, 0.3, 0.3))),
                    MeshMaterial3d(materials.add(StandardMaterial {
                        base_color: base,
                        emissive: emissive,
                        ..default()
                    })),
                    Transform::from_xyz(gi.position.x, gi.position.y + 0.3, gi.position.z),
                ));
            }
            GroundItemEvent::Deleted(gi) => {
                for (entity, marker) in existing.iter() {
                    if marker.0 == gi.scheduled_id {
                        commands.entity(entity).despawn();
                    }
                }
            }
        }
    }
}

pub fn animate_ground_items(time: Res<Time>, mut query: Query<&mut Transform, With<GroundItemMarker>>) {
    let t = time.elapsed_secs();
    for mut transform in query.iter_mut() {
        transform.rotate_y(0.5 * time.delta_secs());
        let bob = (t * TAU * 0.5).sin() * 0.1;
        transform.translation.y = transform.translation.y * 0.95 + (0.3 + bob) * 0.05;
    }
}

// --- Input systems ---

pub fn toggle_inventory(keys: Res<ButtonInput<KeyCode>>, mut open: ResMut<InventoryOpen>, chat_active: Res<ChatInputActive>) {
    if chat_active.0 { return; }
    if keys.just_pressed(KeyCode::Tab) {
        open.0 = !open.0;
    }
}

pub fn pickup_nearest_item(
    keys: Res<ButtonInput<KeyCode>>,
    conn: Option<Res<SpacetimeDb>>,
    local_player: Query<&Transform, With<LocalPlayer>>,
    ground_items: Query<(&Transform, &GroundItemMarker), Without<LocalPlayer>>,
    chat_active: Res<ChatInputActive>,
) {
    if chat_active.0 { return; }
    if !keys.just_pressed(KeyCode::KeyF) {
        return;
    }
    let Some(conn) = conn else { return };
    let Ok(player_tf) = local_player.single() else { return };

    let nearest = ground_items
        .iter()
        .map(|(tf, marker)| (tf.translation.distance(player_tf.translation), marker.0))
        .filter(|(dist, _)| *dist <= PICKUP_RANGE)
        .min_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

    if let Some((_, scheduled_id)) = nearest {
        let _ = conn.0.reducers.pickup_item(scheduled_id);
    }
}

// --- Inventory UI ---

const EQUIP_SLOT_LABELS: [&str; 6] = ["WPN", "HLM", "CHT", "LEG", "BOT", "ACC"];

pub fn setup_inventory_panel(mut commands: Commands) {
    commands
        .spawn((
            InventoryPanel,
            Visibility::Hidden,
            Node {
                position_type: PositionType::Absolute,
                left: Val::Percent(50.0),
                top: Val::Percent(50.0),
                margin: UiRect {
                    left: Val::Px(-270.0),
                    top: Val::Px(-230.0),
                    ..default()
                },
                width: Val::Px(540.0),
                flex_direction: FlexDirection::Column,
                row_gap: Val::Px(6.0),
                padding: UiRect::all(Val::Px(12.0)),
                ..default()
            },
            BackgroundColor(Color::srgba(0.05, 0.05, 0.08, 0.92)),
        ))
        .with_children(|panel| {
            // Header
            panel
                .spawn(Node {
                    flex_direction: FlexDirection::Row,
                    justify_content: JustifyContent::SpaceBetween,
                    align_items: AlignItems::Center,
                    ..default()
                })
                .with_children(|hdr| {
                    hdr.spawn((
                        Text::new("Inventory"),
                        TextFont { font_size: 16.0, ..default() },
                        TextColor(Color::WHITE),
                    ));
                    hdr.spawn((
                        Button,
                        InventoryCloseButton,
                        Node {
                            width: Val::Px(22.0),
                            height: Val::Px(22.0),
                            justify_content: JustifyContent::Center,
                            align_items: AlignItems::Center,
                            ..default()
                        },
                        BackgroundColor(Color::srgba(0.5, 0.1, 0.1, 0.8)),
                    ))
                    .with_children(|btn| {
                        btn.spawn((
                            Text::new("X"),
                            TextFont { font_size: 13.0, ..default() },
                            TextColor(Color::WHITE),
                        ));
                    });
                });

            // Body: equipment + inventory side by side
            panel
                .spawn(Node {
                    flex_direction: FlexDirection::Row,
                    column_gap: Val::Px(12.0),
                    ..default()
                })
                .with_children(|body| {
                    // Equipment section (2x3 grid)
                    body.spawn(Node {
                        flex_direction: FlexDirection::Row,
                        flex_wrap: FlexWrap::Wrap,
                        column_gap: Val::Px(4.0),
                        row_gap: Val::Px(4.0),
                        width: Val::Px(134.0),
                        ..default()
                    })
                    .with_children(|equip_grid| {
                        for i in 0..6i32 {
                            equip_grid
                                .spawn((
                                    Button,
                                    EquipmentSlotNode(i),
                                    Node {
                                        width: Val::Px(65.0),
                                        height: Val::Px(65.0),
                                        justify_content: JustifyContent::Center,
                                        align_items: AlignItems::Center,
                                        flex_direction: FlexDirection::Column,
                                        ..default()
                                    },
                                    BackgroundColor(Color::srgba(0.08, 0.1, 0.18, 0.9)),
                                ))
                                .with_children(|slot| {
                                    slot.spawn((
                                        EquipmentSlotLabel(i),
                                        Text::new(EQUIP_SLOT_LABELS[i as usize]),
                                        TextFont { font_size: 9.0, ..default() },
                                        TextColor(Color::srgb(0.5, 0.5, 0.6)),
                                    ));
                                    // Durability bar container
                                    slot.spawn(Node {
                                        width: Val::Px(55.0),
                                        height: Val::Px(4.0),
                                        margin: UiRect::top(Val::Px(2.0)),
                                        ..default()
                                    })
                                    .with_children(|bar_bg| {
                                        bar_bg.spawn((
                                            DurabilityBar(i),
                                            Node {
                                                width: Val::Percent(100.0),
                                                height: Val::Px(4.0),
                                                ..default()
                                            },
                                            BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.0)),
                                        ));
                                    });
                                });
                        }
                    });

                    // Inventory grid (5x4)
                    body.spawn(Node {
                        flex_direction: FlexDirection::Row,
                        flex_wrap: FlexWrap::Wrap,
                        column_gap: Val::Px(4.0),
                        row_gap: Val::Px(4.0),
                        ..default()
                    })
                    .with_children(|grid| {
                        for i in 0..20i32 {
                            grid.spawn((
                                Button,
                                InventorySlotNode(i),
                                Node {
                                    width: Val::Px(60.0),
                                    height: Val::Px(60.0),
                                    justify_content: JustifyContent::Center,
                                    align_items: AlignItems::Center,
                                    ..default()
                                },
                                BackgroundColor(Color::srgba(0.15, 0.15, 0.18, 0.9)),
                            ))
                            .with_children(|slot| {
                                slot.spawn((
                                    InventorySlotLabel(i),
                                    Text::new(""),
                                    TextFont { font_size: 9.0, ..default() },
                                    TextColor(Color::srgb(0.85, 0.85, 0.85)),
                                ));
                            });
                        }
                    });
                });
        });
}

pub fn update_inventory_panel(
    open: Res<InventoryOpen>,
    local_inv: Res<LocalInventory>,
    local_equip: Res<LocalEquipment>,
    item_map: Res<ItemDefMap>,
    rarity_map: Res<ItemRarityMap>,
    consumable_map: Res<ConsumableDefMap>,
    equip_def_map: Res<EquipmentDefMap>,
    mut panel: Query<&mut Visibility, With<InventoryPanel>>,
    mut labels: Query<(&InventorySlotLabel, &mut Text), Without<EquipmentSlotLabel>>,
    mut slot_bgs: Query<(&InventorySlotNode, &mut BackgroundColor), Without<EquipmentSlotNode>>,
    mut equip_labels: Query<(&EquipmentSlotLabel, &mut Text), Without<InventorySlotLabel>>,
    mut equip_bgs: Query<(&EquipmentSlotNode, &mut BackgroundColor), Without<InventorySlotNode>>,
    mut durability_bars: Query<(&DurabilityBar, &mut Node, &mut BackgroundColor), (Without<EquipmentSlotNode>, Without<InventorySlotNode>)>,
) {
    let Ok(mut vis) = panel.single_mut() else {
        return;
    };
    *vis = if open.0 {
        Visibility::Inherited
    } else {
        Visibility::Hidden
    };

    // Update inventory slot labels
    for (label, mut text) in labels.iter_mut() {
        if let Some((_, item_def_id, qty)) = local_inv.0.get(&label.0) {
            let name = item_map.0.get(item_def_id).map(|s| s.as_str()).unwrap_or("???");
            let mut parts = vec![name.to_string()];
            if *qty > 1 {
                parts.push(format!("x{qty}"));
            }
            if let Some(cdata) = consumable_map.0.get(item_def_id) {
                parts.push(format!("+{} {}", cdata.power, cdata.effect_label));
            } else if let Some(edata) = equip_def_map.0.get(item_def_id) {
                let stats = equipment_stat_line(edata);
                if !stats.is_empty() {
                    parts.push(stats);
                }
            }
            text.0 = parts.join("\n");
        } else {
            text.0 = String::new();
        }
    }

    // Update inventory slot backgrounds
    for (slot_node, mut bg) in slot_bgs.iter_mut() {
        if let Some((_, item_def_id, _)) = local_inv.0.get(&slot_node.0) {
            let rarity = rarity_map
                .0
                .get(item_def_id)
                .map(|s| s.as_str())
                .unwrap_or("Common");
            let c = rarity_color(rarity);
            let r = c.to_srgba();
            *bg = BackgroundColor(Color::srgba(r.red * 0.3, r.green * 0.3, r.blue * 0.3, 0.9));
        } else {
            *bg = BackgroundColor(Color::srgba(0.15, 0.15, 0.18, 0.9));
        }
    }

    // Update equipment slot labels
    for (label, mut text) in equip_labels.iter_mut() {
        if let Some((_, item_def_id, durability, _)) = local_equip.0.get(&label.0) {
            let name = item_map.0.get(item_def_id).map(|s| s.as_str()).unwrap_or("???");
            let stats = equip_def_map.0.get(item_def_id)
                .map(|d| equipment_stat_line(d))
                .unwrap_or_default();
            if *durability <= 0 {
                text.0 = format!("{name}\n(Broken)");
            } else if !stats.is_empty() {
                text.0 = format!("{name}\n{stats}");
            } else {
                text.0 = name.to_string();
            }
        } else {
            text.0 = EQUIP_SLOT_LABELS[label.0 as usize].to_string();
        }
    }

    // Update equipment slot backgrounds
    for (slot_node, mut bg) in equip_bgs.iter_mut() {
        if let Some((_, item_def_id, _, _)) = local_equip.0.get(&slot_node.0) {
            let rarity = rarity_map
                .0
                .get(item_def_id)
                .map(|s| s.as_str())
                .unwrap_or("Common");
            let c = rarity_color(rarity);
            let r = c.to_srgba();
            *bg = BackgroundColor(Color::srgba(r.red * 0.2, r.green * 0.2, r.blue * 0.3, 0.9));
        } else {
            *bg = BackgroundColor(Color::srgba(0.08, 0.1, 0.18, 0.9));
        }
    }

    // Update durability bars
    for (bar, mut node, mut bg) in durability_bars.iter_mut() {
        if let Some((_, _, durability, max_dur)) = local_equip.0.get(&bar.0) {
            if *max_dur > 0 {
                let pct = (*durability as f32 / *max_dur as f32) * 100.0;
                node.width = Val::Percent(pct);
                let color = if *durability <= 0 {
                    Color::srgb(0.6, 0.1, 0.1)
                } else if pct < 25.0 {
                    Color::srgb(0.8, 0.7, 0.1)
                } else {
                    Color::srgb(0.2, 0.7, 0.2)
                };
                *bg = BackgroundColor(color);
            }
        } else {
            node.width = Val::Percent(0.0);
            *bg = BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.0));
        }
    }
}

pub fn handle_inventory_close(
    close_btns: Query<&Interaction, (Changed<Interaction>, With<InventoryCloseButton>)>,
    mut open: ResMut<InventoryOpen>,
) {
    for interaction in &close_btns {
        if *interaction == Interaction::Pressed {
            open.0 = false;
        }
    }
}

pub fn handle_inventory_slot_click(
    slots: Query<(&Interaction, &InventorySlotNode), Changed<Interaction>>,
    mouse: Res<ButtonInput<MouseButton>>,
    local_inv: Res<LocalInventory>,
    type_map: Res<ItemTypeMap>,
    conn: Option<Res<SpacetimeDb>>,
) {
    let Some(conn) = conn else { return };
    for (interaction, slot) in &slots {
        if *interaction != Interaction::Pressed { continue; }
        let Some((inv_item_id, item_def_id, _)) = local_inv.0.get(&slot.0) else { continue };
        if mouse.pressed(MouseButton::Right) {
            let _ = conn.0.reducers.drop_item(*inv_item_id);
        } else if mouse.pressed(MouseButton::Left) {
            let item_type = type_map.0.get(item_def_id).map(|t| t.as_str()).unwrap_or("");
            match item_type {
                "Equipment" => { let _ = conn.0.reducers.equip_item(*inv_item_id); }
                "Consumable" => { let _ = conn.0.reducers.use_item(*inv_item_id); }
                _ => {}
            }
        }
    }
}

pub fn handle_equipment_slot_click(
    slots: Query<(&Interaction, &EquipmentSlotNode), Changed<Interaction>>,
    mouse: Res<ButtonInput<MouseButton>>,
    local_equip: Res<LocalEquipment>,
    conn: Option<Res<SpacetimeDb>>,
) {
    let Some(conn) = conn else { return };
    for (interaction, slot) in &slots {
        if *interaction != Interaction::Pressed { continue; }
        let Some((equipped_item_id, _, _, _)) = local_equip.0.get(&slot.0) else { continue };
        if mouse.pressed(MouseButton::Right) {
            let _ = conn.0.reducers.drop_equipped_item(*equipped_item_id);
        } else if mouse.pressed(MouseButton::Left) {
            let _ = conn.0.reducers.unequip_item(*equipped_item_id);
        }
    }
}
