use bevy::prelude::*;
use std::collections::HashMap;
use std::f32::consts::TAU;

use shared::module_bindings::drop_item_reducer::drop_item;
use shared::module_bindings::pickup_item_reducer::pickup_item;

use crate::constants::PICKUP_RANGE;
use crate::network::{
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

// --- Sync systems ---

pub fn sync_item_defs(
    queue: Res<ItemDefEventQueue>,
    mut item_map: ResMut<ItemDefMap>,
    mut rarity_map: ResMut<ItemRarityMap>,
) {
    let mut events = queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            ItemDefEvent::Inserted(def) => {
                item_map.0.insert(def.id, def.name.clone());
                let rarity_name = format!("{:?}", def.rarity);
                rarity_map.0.insert(def.id, rarity_name);
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

pub fn toggle_inventory(keys: Res<ButtonInput<KeyCode>>, mut open: ResMut<InventoryOpen>) {
    if keys.just_pressed(KeyCode::Tab) {
        open.0 = !open.0;
    }
}

pub fn pickup_nearest_item(
    keys: Res<ButtonInput<KeyCode>>,
    conn: Option<Res<SpacetimeDb>>,
    local_player: Query<&Transform, With<LocalPlayer>>,
    ground_items: Query<(&Transform, &GroundItemMarker), Without<LocalPlayer>>,
) {
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
                    left: Val::Px(-170.0),
                    top: Val::Px(-230.0),
                    ..default()
                },
                width: Val::Px(340.0),
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
                        TextFont {
                            font_size: 16.0,
                            ..default()
                        },
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
                            TextFont {
                                font_size: 13.0,
                                ..default()
                            },
                            TextColor(Color::WHITE),
                        ));
                    });
                });

            // 5x4 grid
            panel
                .spawn(Node {
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
                                TextFont {
                                    font_size: 9.0,
                                    ..default()
                                },
                                TextColor(Color::srgb(0.85, 0.85, 0.85)),
                            ));
                        });
                    }
                });
        });
}

pub fn update_inventory_panel(
    open: Res<InventoryOpen>,
    local_inv: Res<LocalInventory>,
    item_map: Res<ItemDefMap>,
    rarity_map: Res<ItemRarityMap>,
    mut panel: Query<&mut Visibility, With<InventoryPanel>>,
    mut labels: Query<(&InventorySlotLabel, &mut Text)>,
    mut slot_bgs: Query<(&InventorySlotNode, &mut BackgroundColor)>,
) {
    let Ok(mut vis) = panel.single_mut() else {
        return;
    };
    *vis = if open.0 {
        Visibility::Inherited
    } else {
        Visibility::Hidden
    };

    for (label, mut text) in labels.iter_mut() {
        if let Some((_, item_def_id, qty)) = local_inv.0.get(&label.0) {
            let name = item_map.0.get(item_def_id).map(|s| s.as_str()).unwrap_or("???");
            if *qty > 1 {
                text.0 = format!("{name}\nx{qty}");
            } else {
                text.0 = name.to_string();
            }
        } else {
            text.0 = String::new();
        }
    }

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
    conn: Option<Res<SpacetimeDb>>,
) {
    let Some(conn) = conn else { return };
    for (interaction, slot) in &slots {
        if *interaction == Interaction::Pressed && mouse.pressed(MouseButton::Right) {
            if let Some((inv_item_id, _, _)) = local_inv.0.get(&slot.0) {
                let _ = conn.0.reducers.drop_item(*inv_item_id);
            }
        }
    }
}
