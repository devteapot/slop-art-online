use spacetimedb::ReducerContext;

use crate::tables::*;

#[spacetimedb::reducer]
pub fn use_item(ctx: &ReducerContext, inventory_item_id: u64) -> Result<(), String> {
    let inv = ctx.db.inventory_item().id().find(&inventory_item_id)
        .ok_or("Inventory item not found")?;
    if inv.player_identity != ctx.sender() {
        return Err("Not your item".to_string());
    }

    let item_def = ctx.db.item_def().id().find(&inv.item_def_id)
        .ok_or("Item definition not found")?;
    if item_def.item_type != ItemType::Consumable {
        return Err("Item is not consumable".to_string());
    }

    let consumable = ctx.db.consumable_def().item_def_id().find(&inv.item_def_id)
        .ok_or("Consumable definition not found")?;

    let player = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Player not found")?;

    match consumable.effect {
        ConsumableEffect::RestoreHealth => {
            if player.health >= player.max_health {
                return Err("Already at full health".to_string());
            }
            let new_health = (player.health + consumable.power).min(player.max_health);
            ctx.db.player().identity().update(Player { health: new_health, ..player });
        }
        ConsumableEffect::RestoreMana => {
            if player.mana >= player.max_mana {
                return Err("Already at full mana".to_string());
            }
            let new_mana = (player.mana + consumable.power).min(player.max_mana);
            ctx.db.player().identity().update(Player { mana: new_mana, ..player });
        }
        ConsumableEffect::RestoreStamina => {
            if player.stamina >= player.max_stamina {
                return Err("Already at full stamina".to_string());
            }
            let new_stamina = (player.stamina + consumable.power).min(player.max_stamina);
            ctx.db.player().identity().update(Player { stamina: new_stamina, ..player });
        }
    }

    // Reduce quantity or delete
    if inv.quantity > 1 {
        ctx.db.inventory_item().id().update(InventoryItem {
            quantity: inv.quantity - 1,
            ..inv
        });
    } else {
        ctx.db.inventory_item().id().delete(&inv.id);
    }

    Ok(())
}
