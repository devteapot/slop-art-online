use spacetimedb::rand::Rng;
use spacetimedb::{Identity, ReducerContext, ScheduleAt, Table};
use std::time::Duration;

use crate::constants::*;
use crate::skill::*;
use crate::tables::*;
use crate::{ground_item, GroundItem};

pub struct EquipmentBonuses {
    pub health: i32,
    pub mana: i32,
    pub stamina: i32,
    pub attack: i32,
    pub defense: i32,
}

impl Default for EquipmentBonuses {
    fn default() -> Self {
        Self { health: 0, mana: 0, stamina: 0, attack: 0, defense: 0 }
    }
}

pub fn equipment_bonuses(ctx: &ReducerContext, identity: &Identity) -> EquipmentBonuses {
    let mut bonuses = EquipmentBonuses::default();
    for eq in ctx.db.equipped_item().iter() {
        if eq.player_identity != *identity || eq.durability <= 0 {
            continue;
        }
        if let Some(def) = ctx.db.equipment_def().item_def_id().find(&eq.item_def_id) {
            bonuses.health += def.bonus_health;
            bonuses.mana += def.bonus_mana;
            bonuses.stamina += def.bonus_stamina;
            bonuses.attack += def.bonus_attack;
            bonuses.defense += def.bonus_defense;
        }
    }
    bonuses
}

pub fn recalculate_max_stats(ctx: &ReducerContext, player_identity: &Identity) {
    let Some(player) = ctx.db.player().identity().find(player_identity) else { return };
    let bonuses = equipment_bonuses(ctx, player_identity);
    let base_health = player_max_health(player.level);
    let base_mana = player_max_mana(player.level);
    let base_stamina = player_max_stamina(player.level);
    let new_max_health = base_health + bonuses.health;
    let new_max_mana = base_mana + bonuses.mana;
    let new_max_stamina = base_stamina + bonuses.stamina;
    ctx.db.player().identity().update(Player {
        max_health: new_max_health,
        max_mana: new_max_mana,
        max_stamina: new_max_stamina,
        health: player.health.min(new_max_health),
        mana: player.mana.min(new_max_mana),
        stamina: player.stamina.min(new_max_stamina),
        ..player
    });
}

pub fn degrade_weapon(ctx: &ReducerContext, identity: &Identity) {
    for eq in ctx.db.equipped_item().iter().collect::<Vec<_>>() {
        if eq.player_identity == *identity && eq.equip_slot == EquipSlot::Weapon && eq.durability > 0 {
            ctx.db.equipped_item().id().update(EquippedItem {
                durability: eq.durability - 1,
                ..eq
            });
            return;
        }
    }
}

pub fn degrade_armor(ctx: &ReducerContext, identity: &Identity) {
    let armor_pieces: Vec<EquippedItem> = ctx.db.equipped_item().iter()
        .filter(|eq| {
            eq.player_identity == *identity
                && eq.durability > 0
                && matches!(eq.equip_slot, EquipSlot::Helmet | EquipSlot::Chest | EquipSlot::Legs | EquipSlot::Boots)
        })
        .collect();
    if armor_pieces.is_empty() { return; }
    let idx = ctx.rng().gen_range(0..armor_pieces.len());
    let piece = &armor_pieces[idx];
    ctx.db.equipped_item().id().update(EquippedItem {
        durability: piece.durability - 1,
        ..piece.clone()
    });
}

#[spacetimedb::reducer]
pub fn equip_item(ctx: &ReducerContext, inventory_item_id: u64) -> Result<(), String> {
    let inv = ctx.db.inventory_item().id().find(&inventory_item_id)
        .ok_or("Inventory item not found")?;
    if inv.player_identity != ctx.sender() {
        return Err("Not your item".to_string());
    }

    let item_def = ctx.db.item_def().id().find(&inv.item_def_id)
        .ok_or("Item definition not found")?;
    if item_def.item_type != ItemType::Equipment {
        return Err("Item is not equipment".to_string());
    }

    let equip_def = ctx.db.equipment_def().item_def_id().find(&inv.item_def_id)
        .ok_or("Equipment definition not found")?;

    let player = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Player not found")?;
    if player.level < equip_def.required_level {
        return Err(format!("Requires level {}", equip_def.required_level));
    }

    // Check slot not occupied
    let occupied = ctx.db.equipped_item().iter()
        .any(|eq| eq.player_identity == ctx.sender() && eq.equip_slot == equip_def.equip_slot);
    if occupied {
        return Err("Equipment slot already occupied — unequip first".to_string());
    }

    // Remove from inventory
    ctx.db.inventory_item().id().delete(&inv.id);

    // Insert equipped item
    ctx.db.equipped_item().insert(EquippedItem {
        id: 0,
        player_identity: ctx.sender(),
        equip_slot: equip_def.equip_slot.clone(),
        item_def_id: inv.item_def_id,
        durability: equip_def.max_durability,
    });

    recalculate_max_stats(ctx, &ctx.sender());
    Ok(())
}

#[spacetimedb::reducer]
pub fn unequip_item(ctx: &ReducerContext, equipped_item_id: u64) -> Result<(), String> {
    let eq = ctx.db.equipped_item().id().find(&equipped_item_id)
        .ok_or("Equipped item not found")?;
    if eq.player_identity != ctx.sender() {
        return Err("Not your item".to_string());
    }

    // Find free inventory slot
    let occupied: Vec<i32> = ctx.db.inventory_item().iter()
        .filter(|inv| inv.player_identity == ctx.sender())
        .map(|inv| inv.slot)
        .collect();
    let free_slot = (0..INVENTORY_SLOTS)
        .find(|s| !occupied.contains(s))
        .ok_or("Inventory full")?;

    ctx.db.equipped_item().id().delete(&eq.id);

    ctx.db.inventory_item().insert(InventoryItem {
        id: 0,
        player_identity: ctx.sender(),
        slot: free_slot,
        item_def_id: eq.item_def_id,
        quantity: 1,
    });

    recalculate_max_stats(ctx, &ctx.sender());
    Ok(())
}

#[spacetimedb::reducer]
pub fn drop_equipped_item(ctx: &ReducerContext, equipped_item_id: u64) -> Result<(), String> {
    let eq = ctx.db.equipped_item().id().find(&equipped_item_id)
        .ok_or("Equipped item not found")?;
    if eq.player_identity != ctx.sender() {
        return Err("Not your item".to_string());
    }

    let player = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Player not found")?;

    ctx.db.equipped_item().id().delete(&eq.id);

    ctx.db.ground_item().insert(GroundItem {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(GROUND_ITEM_DESPAWN_MS)),
        item_def_id: eq.item_def_id,
        quantity: 1,
        position: player.position.clone(),
        owner: ctx.sender(),
        free_for_all_at: 0,
    });

    recalculate_max_stats(ctx, &ctx.sender());
    Ok(())
}
