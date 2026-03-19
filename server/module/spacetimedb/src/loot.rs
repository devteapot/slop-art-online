use spacetimedb::rand::Rng;
use spacetimedb::{Identity, ReducerContext, ScheduleAt, Table};
use std::time::Duration;

use crate::constants::*;
use crate::tables::*;
use crate::{ground_item, GroundItem, equipped_item};

/// Drop every inventory item for `player` onto the ground at their current position.
pub fn drop_all_inventory(ctx: &ReducerContext, player: &Player) {
    let items: Vec<InventoryItem> = ctx
        .db
        .inventory_item()
        .iter()
        .filter(|inv| inv.player_identity == player.identity)
        .collect();

    for inv in items {
        let scatter_x: f32 = (ctx.rng().gen_range(0..100) as f32 / 100.0) - 0.5;
        let scatter_z: f32 = (ctx.rng().gen_range(0..100) as f32 / 100.0) - 0.5;

        ctx.db.ground_item().insert(GroundItem {
            scheduled_id: 0,
            scheduled_at: ScheduleAt::Time(
                ctx.timestamp + Duration::from_millis(GROUND_ITEM_DESPAWN_MS),
            ),
            item_def_id: inv.item_def_id,
            quantity: inv.quantity,
            position: Position {
                x: player.position.x + scatter_x,
                y: player.position.y,
                z: player.position.z + scatter_z,
            },
            owner: player.identity,
            free_for_all_at: 0, // FFA immediately on death
        });

        ctx.db.inventory_item().id().delete(&inv.id);
    }

    // Drop all equipped items
    let equipped: Vec<EquippedItem> = ctx
        .db
        .equipped_item()
        .iter()
        .filter(|eq| eq.player_identity == player.identity)
        .collect();

    for eq in equipped {
        let scatter_x: f32 = (ctx.rng().gen_range(0..100) as f32 / 100.0) - 0.5;
        let scatter_z: f32 = (ctx.rng().gen_range(0..100) as f32 / 100.0) - 0.5;

        ctx.db.ground_item().insert(GroundItem {
            scheduled_id: 0,
            scheduled_at: ScheduleAt::Time(
                ctx.timestamp + Duration::from_millis(GROUND_ITEM_DESPAWN_MS),
            ),
            item_def_id: eq.item_def_id,
            quantity: 1,
            position: Position {
                x: player.position.x + scatter_x,
                y: player.position.y,
                z: player.position.z + scatter_z,
            },
            owner: player.identity,
            free_for_all_at: 0,
        });

        ctx.db.equipped_item().id().delete(&eq.id);
    }
}

pub fn generate_loot(ctx: &ReducerContext, npc: &Npc, attacker: Identity) {
    let entries: Vec<LootTableEntry> = ctx
        .db
        .loot_table_entry()
        .iter()
        .filter(|e| npc.level >= e.min_npc_level && npc.level <= e.max_npc_level)
        .collect();

    if entries.is_empty() {
        return;
    }

    let total_weight: i32 = entries.iter().map(|e| e.weight).sum();
    if total_weight <= 0 {
        return;
    }

    let now_us = ctx
        .timestamp
        .to_duration_since_unix_epoch()
        .unwrap_or_default()
        .as_micros() as u64;
    let ffa_at = now_us + GROUND_ITEM_FFA_DELAY_MS * 1000;

    for _ in 0..LOOT_ROLLS_PER_KILL {
        let roll = ctx.rng().gen_range(0..100);
        if roll >= LOOT_DROP_CHANCE_PCT {
            continue;
        }

        let mut pick = ctx.rng().gen_range(0..total_weight);
        let mut winner: Option<&LootTableEntry> = None;
        for entry in &entries {
            pick -= entry.weight;
            if pick < 0 {
                winner = Some(entry);
                break;
            }
        }
        let Some(entry) = winner else { continue };

        let quantity = if entry.min_quantity >= entry.max_quantity {
            entry.min_quantity
        } else {
            ctx.rng().gen_range(entry.min_quantity..=entry.max_quantity)
        };

        let scatter_x: f32 = (ctx.rng().gen_range(0..100) as f32 / 100.0) - 0.5;
        let scatter_z: f32 = (ctx.rng().gen_range(0..100) as f32 / 100.0) - 0.5;

        ctx.db.ground_item().insert(GroundItem {
            scheduled_id: 0,
            scheduled_at: ScheduleAt::Time(
                ctx.timestamp + Duration::from_millis(GROUND_ITEM_DESPAWN_MS),
            ),
            item_def_id: entry.item_def_id,
            quantity,
            position: Position {
                x: npc.position.x + scatter_x,
                y: npc.position.y,
                z: npc.position.z + scatter_z,
            },
            owner: attacker,
            free_for_all_at: ffa_at,
        });
    }
}

#[spacetimedb::reducer]
pub fn pickup_item(ctx: &ReducerContext, ground_item_id: u64) -> Result<(), String> {
    let ground = ctx
        .db
        .ground_item()
        .scheduled_id()
        .find(&ground_item_id)
        .ok_or("Ground item not found")?;

    let player = ctx
        .db
        .player()
        .identity()
        .find(&ctx.sender())
        .ok_or("Player not found")?;

    if player.position.distance_to(&ground.position) > PICKUP_RANGE {
        return Err("Too far away".to_string());
    }

    let now_us = ctx
        .timestamp
        .to_duration_since_unix_epoch()
        .unwrap_or_default()
        .as_micros() as u64;
    if ground.owner != ctx.sender() && now_us < ground.free_for_all_at {
        return Err("This loot belongs to another player".to_string());
    }

    let item_def = ctx
        .db
        .item_def()
        .id()
        .find(&ground.item_def_id)
        .ok_or("Item definition not found")?;

    let mut remaining = ground.quantity;

    // Try to stack into existing inventory slots
    let existing: Vec<InventoryItem> = ctx
        .db
        .inventory_item()
        .iter()
        .filter(|inv| {
            inv.player_identity == ctx.sender()
                && inv.item_def_id == ground.item_def_id
                && inv.quantity < item_def.max_stack
        })
        .collect();

    for inv in existing {
        if remaining <= 0 {
            break;
        }
        let space = item_def.max_stack - inv.quantity;
        let add = remaining.min(space);
        ctx.db.inventory_item().id().update(InventoryItem {
            quantity: inv.quantity + add,
            ..inv
        });
        remaining -= add;
    }

    // Place remaining into empty slots
    if remaining > 0 {
        let occupied: Vec<i32> = ctx
            .db
            .inventory_item()
            .iter()
            .filter(|inv| inv.player_identity == ctx.sender())
            .map(|inv| inv.slot)
            .collect();

        for slot in 0..INVENTORY_SLOTS {
            if remaining <= 0 {
                break;
            }
            if occupied.contains(&slot) {
                continue;
            }
            let stack = remaining.min(item_def.max_stack);
            ctx.db.inventory_item().insert(InventoryItem {
                id: 0,
                player_identity: ctx.sender(),
                slot,
                item_def_id: ground.item_def_id,
                quantity: stack,
            });
            remaining -= stack;
        }
    }

    if remaining > 0 {
        return Err("Inventory full".to_string());
    }

    ctx.db
        .ground_item()
        .scheduled_id()
        .delete(&ground.scheduled_id);
    Ok(())
}

#[spacetimedb::reducer]
pub fn drop_item(ctx: &ReducerContext, inventory_item_id: u64) -> Result<(), String> {
    let inv = ctx
        .db
        .inventory_item()
        .id()
        .find(&inventory_item_id)
        .ok_or("Inventory item not found")?;

    if inv.player_identity != ctx.sender() {
        return Err("Not your item".to_string());
    }

    let player = ctx
        .db
        .player()
        .identity()
        .find(&ctx.sender())
        .ok_or("Player not found")?;

    ctx.db.ground_item().insert(GroundItem {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(
            ctx.timestamp + Duration::from_millis(GROUND_ITEM_DESPAWN_MS),
        ),
        item_def_id: inv.item_def_id,
        quantity: inv.quantity,
        position: player.position.clone(),
        owner: ctx.sender(),
        free_for_all_at: 0,
    });

    ctx.db.inventory_item().id().delete(&inv.id);
    Ok(())
}
