mod combat;
mod constants;
mod consumable;
mod equipment;
mod loot;
mod npc_ai;
mod skill;
mod tables;

use spacetimedb::{Identity, ReducerContext, ScheduleAt, Table};
use std::time::Duration;

use crate::combat::*;
use crate::constants::*;
use crate::equipment::*;
use crate::npc_ai::*;
use crate::skill::*;
use crate::tables::*;

// --- NPC tick schedule (must live here alongside tick_npcs reducer) ---

#[spacetimedb::table(accessor = npc_tick_schedule, scheduled(tick_npcs))]
pub struct NpcTickSchedule {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = active_skill, public, scheduled(expire_active_skill))]
pub struct ActiveSkill {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub player_identity: Identity,
    pub skill_id: u64,
    pub started_at: u64,
    pub target_x: f32,
    pub target_y: f32,
    pub target_z: f32,
    pub dir_x: f32,
    pub dir_z: f32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = projectile, public, scheduled(expire_projectile))]
pub struct Projectile {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub owner: Identity,
    pub skill_id: u64,
    pub start_x: f32,
    pub start_y: f32,
    pub start_z: f32,
    pub dir_x: f32,
    pub dir_z: f32,
    pub speed: f32,
    pub max_range: f32,
    pub power: i32,
    pub knockback: f32,
    pub hit_radius: f32,
    pub started_at: u64,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = ground_item, public, scheduled(expire_ground_item))]
pub struct GroundItem {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub item_def_id: u64,
    pub quantity: i32,
    pub position: Position,
    pub owner: Identity,
    pub free_for_all_at: u64,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = aoe_zone, public, scheduled(expire_aoe_zone))]
pub struct AoeZone {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub owner: Identity,
    pub skill_id: u64,
    pub center_x: f32,
    pub center_y: f32,
    pub center_z: f32,
    pub radius: f32,
    pub power: i32,
    pub knockback: f32,
    pub tick_interval_ms: u64,
    pub last_tick_at: u64,
    pub started_at: u64,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = status_effect, public, scheduled(expire_status_effect))]
pub struct StatusEffect {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub effect_type: StatusEffectType,
    pub target_identity: Identity,
    pub target_npc_id: u64,
    pub power: i32,
    pub source: Identity,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = npc_chat_message, public, scheduled(expire_npc_chat_message))]
pub struct NpcChatMessage {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub npc_id: u64,
    pub text: String,
    pub position: Position,
}

#[spacetimedb::table(accessor = npc_event_log, public, scheduled(expire_npc_event))]
pub struct NpcEventLog {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub npc_id: u64,
    pub event: String,
    pub detail: String,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = chat_message, public, scheduled(expire_chat_message))]
pub struct ChatMessage {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub sender: Identity,
    pub sender_name: String,
    pub text: String,
    pub position: Position,
}

#[spacetimedb::table(accessor = projectile_tick_schedule, scheduled(tick_projectiles))]
pub struct ProjectileTickSchedule {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}

// --- Status effect helpers ---

fn effect_for_skill(name: &str, duration_ms: u64) -> Option<(StatusEffectType, i32, u64)> {
    match name {
        "Fireball" => Some((
            StatusEffectType::Poison,
            EFFECT_POISON_POWER,
            duration_ms.max(EFFECT_DEFAULT_DURATION_MS),
        )),
        "Shockwave" => Some((
            StatusEffectType::Slow,
            0,
            duration_ms.max(EFFECT_DEFAULT_DURATION_MS),
        )),
        _ => None,
    }
}

// --- Scheduler helper ---

fn schedule_next_npc_tick(ctx: &ReducerContext) {
    let next = ctx.timestamp + Duration::from_millis(NPC_TICK_MS);
    ctx.db.npc_tick_schedule().insert(NpcTickSchedule {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(next),
    });
}

fn schedule_next_projectile_tick(ctx: &ReducerContext) {
    let next = ctx.timestamp + Duration::from_millis(PROJECTILE_TICK_MS);
    ctx.db
        .projectile_tick_schedule()
        .insert(ProjectileTickSchedule {
            scheduled_id: 0,
            scheduled_at: ScheduleAt::Time(next),
        });
}

// --- Reducers ---

#[spacetimedb::reducer(init)]
pub fn init(ctx: &ReducerContext) {
    ctx.db.skill_def().insert(SkillDef {
        id: 0,
        name: "Strike".to_string(),
        behavior_type: BehaviorType::Melee,
        resource_type: ResourceType::Stamina,
    });
    ctx.db.skill_def().insert(SkillDef {
        id: 0,
        name: "Fireball".to_string(),
        behavior_type: BehaviorType::Projectile,
        resource_type: ResourceType::Mana,
    });
    ctx.db.skill_def().insert(SkillDef {
        id: 0,
        name: "Shockwave".to_string(),
        behavior_type: BehaviorType::GroundAoe,
        resource_type: ResourceType::Mana,
    });
    ctx.db.skill_def().insert(SkillDef {
        id: 0,
        name: "Heal".to_string(),
        behavior_type: BehaviorType::Buff,
        resource_type: ResourceType::Mana,
    });
    ctx.db.skill_def().insert(SkillDef {
        id: 0,
        name: "Jump".to_string(),
        behavior_type: BehaviorType::Mobility,
        resource_type: ResourceType::Stamina,
    });
    ctx.db.skill_def().insert(SkillDef {
        id: 0,
        name: "Dash".to_string(),
        behavior_type: BehaviorType::Mobility,
        resource_type: ResourceType::Stamina,
    });

    // Item definitions
    ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Bone Fragment".into(),
        item_type: ItemType::Material,
        rarity: ItemRarity::Common,
        max_stack: 20,
    });
    ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Iron Ore".into(),
        item_type: ItemType::Material,
        rarity: ItemRarity::Common,
        max_stack: 20,
    });
    ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Health Potion".into(),
        item_type: ItemType::Consumable,
        rarity: ItemRarity::Common,
        max_stack: 10,
    });
    ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Enchanted Dust".into(),
        item_type: ItemType::Material,
        rarity: ItemRarity::Uncommon,
        max_stack: 10,
    });
    ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Dragon Scale".into(),
        item_type: ItemType::Material,
        rarity: ItemRarity::Rare,
        max_stack: 5,
    });
    ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Crystal Core".into(),
        item_type: ItemType::Material,
        rarity: ItemRarity::Epic,
        max_stack: 1,
    });

    // New consumable item definitions (item_def_ids 7-8 from auto_inc order)
    let mana_potion = ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Mana Potion".into(),
        item_type: ItemType::Consumable,
        rarity: ItemRarity::Common,
        max_stack: 10,
    });
    let stamina_tonic = ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Stamina Tonic".into(),
        item_type: ItemType::Consumable,
        rarity: ItemRarity::Uncommon,
        max_stack: 10,
    });

    // Consumable definitions
    ctx.db.consumable_def().insert(ConsumableDef {
        item_def_id: 3,
        effect: ConsumableEffect::RestoreHealth,
        power: 50,
    });
    ctx.db.consumable_def().insert(ConsumableDef {
        item_def_id: mana_potion.id,
        effect: ConsumableEffect::RestoreMana,
        power: 40,
    });
    ctx.db.consumable_def().insert(ConsumableDef {
        item_def_id: stamina_tonic.id,
        effect: ConsumableEffect::RestoreStamina,
        power: 40,
    });

    // Loot table entries (item_def_ids 1-6 from auto_inc order)
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: 1,
        min_npc_level: 1,
        max_npc_level: 99,
        weight: 40,
        min_quantity: 1,
        max_quantity: 3,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: 2,
        min_npc_level: 1,
        max_npc_level: 99,
        weight: 30,
        min_quantity: 1,
        max_quantity: 2,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: 3,
        min_npc_level: 1,
        max_npc_level: 99,
        weight: 25,
        min_quantity: 1,
        max_quantity: 2,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: 4,
        min_npc_level: 3,
        max_npc_level: 99,
        weight: 15,
        min_quantity: 1,
        max_quantity: 1,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: 5,
        min_npc_level: 5,
        max_npc_level: 99,
        weight: 5,
        min_quantity: 1,
        max_quantity: 1,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: 6,
        min_npc_level: 8,
        max_npc_level: 99,
        weight: 1,
        min_quantity: 1,
        max_quantity: 1,
    });

    // Loot table entries for new consumables
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: mana_potion.id,
        min_npc_level: 1,
        max_npc_level: 99,
        weight: 20,
        min_quantity: 1,
        max_quantity: 2,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: stamina_tonic.id,
        min_npc_level: 2,
        max_npc_level: 99,
        weight: 15,
        min_quantity: 1,
        max_quantity: 1,
    });

    // Equipment item definitions (item_def_ids 9-14 from auto_inc order)
    let iron_sword = ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Iron Sword".into(),
        item_type: ItemType::Equipment,
        rarity: ItemRarity::Common,
        max_stack: 1,
    });
    let leather_cap = ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Leather Cap".into(),
        item_type: ItemType::Equipment,
        rarity: ItemRarity::Common,
        max_stack: 1,
    });
    let iron_chestplate = ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Iron Chestplate".into(),
        item_type: ItemType::Equipment,
        rarity: ItemRarity::Uncommon,
        max_stack: 1,
    });
    let cloth_pants = ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Cloth Pants".into(),
        item_type: ItemType::Equipment,
        rarity: ItemRarity::Common,
        max_stack: 1,
    });
    let traveler_boots = ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Traveler Boots".into(),
        item_type: ItemType::Equipment,
        rarity: ItemRarity::Common,
        max_stack: 1,
    });
    let copper_ring = ctx.db.item_def().insert(ItemDef {
        id: 0,
        name: "Copper Ring".into(),
        item_type: ItemType::Equipment,
        rarity: ItemRarity::Uncommon,
        max_stack: 1,
    });

    // Equipment definitions
    ctx.db.equipment_def().insert(EquipmentDef {
        item_def_id: iron_sword.id,
        equip_slot: EquipSlot::Weapon,
        required_level: 1,
        max_durability: 50,
        bonus_health: 0,
        bonus_mana: 0,
        bonus_stamina: 0,
        bonus_attack: 5,
        bonus_defense: 0,
    });
    ctx.db.equipment_def().insert(EquipmentDef {
        item_def_id: leather_cap.id,
        equip_slot: EquipSlot::Helmet,
        required_level: 1,
        max_durability: 40,
        bonus_health: 10,
        bonus_mana: 0,
        bonus_stamina: 0,
        bonus_attack: 0,
        bonus_defense: 0,
    });
    ctx.db.equipment_def().insert(EquipmentDef {
        item_def_id: iron_chestplate.id,
        equip_slot: EquipSlot::Chest,
        required_level: 3,
        max_durability: 60,
        bonus_health: 20,
        bonus_mana: 0,
        bonus_stamina: 0,
        bonus_attack: 0,
        bonus_defense: 3,
    });
    ctx.db.equipment_def().insert(EquipmentDef {
        item_def_id: cloth_pants.id,
        equip_slot: EquipSlot::Legs,
        required_level: 1,
        max_durability: 40,
        bonus_health: 0,
        bonus_mana: 5,
        bonus_stamina: 0,
        bonus_attack: 0,
        bonus_defense: 0,
    });
    ctx.db.equipment_def().insert(EquipmentDef {
        item_def_id: traveler_boots.id,
        equip_slot: EquipSlot::Boots,
        required_level: 1,
        max_durability: 40,
        bonus_health: 0,
        bonus_mana: 0,
        bonus_stamina: 5,
        bonus_attack: 0,
        bonus_defense: 0,
    });
    ctx.db.equipment_def().insert(EquipmentDef {
        item_def_id: copper_ring.id,
        equip_slot: EquipSlot::Accessory,
        required_level: 2,
        max_durability: 80,
        bonus_health: 5,
        bonus_mana: 0,
        bonus_stamina: 0,
        bonus_attack: 3,
        bonus_defense: 0,
    });

    // Loot table entries for equipment
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: iron_sword.id,
        min_npc_level: 1,
        max_npc_level: 99,
        weight: 8,
        min_quantity: 1,
        max_quantity: 1,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: leather_cap.id,
        min_npc_level: 1,
        max_npc_level: 99,
        weight: 8,
        min_quantity: 1,
        max_quantity: 1,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: iron_chestplate.id,
        min_npc_level: 3,
        max_npc_level: 99,
        weight: 5,
        min_quantity: 1,
        max_quantity: 1,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: cloth_pants.id,
        min_npc_level: 1,
        max_npc_level: 99,
        weight: 8,
        min_quantity: 1,
        max_quantity: 1,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: traveler_boots.id,
        min_npc_level: 1,
        max_npc_level: 99,
        weight: 8,
        min_quantity: 1,
        max_quantity: 1,
    });
    ctx.db.loot_table_entry().insert(LootTableEntry {
        id: 0,
        item_def_id: copper_ring.id,
        min_npc_level: 2,
        max_npc_level: 99,
        weight: 5,
        min_quantity: 1,
        max_quantity: 1,
    });

    // Seed WorldState singleton
    let now_us = ctx
        .timestamp
        .to_duration_since_unix_epoch()
        .unwrap_or_default()
        .as_micros() as u64;
    ctx.db.world_state().insert(WorldState {
        id: 0,
        cycle_start_us: now_us,
        is_night: false,
    });

    // Seed Points of Interest
    ctx.db.point_of_interest().insert(PointOfInterest {
        id: 0,
        name: "Market Square".into(),
        poi_type: "market".into(),
        x: 50.0,
        z: 0.0,
        radius: 15.0,
    });
    ctx.db.point_of_interest().insert(PointOfInterest {
        id: 0,
        name: "North Gate".into(),
        poi_type: "gate".into(),
        x: -20.0,
        z: 30.0,
        radius: 10.0,
    });
    ctx.db.point_of_interest().insert(PointOfInterest {
        id: 0,
        name: "Town Library".into(),
        poi_type: "inn".into(),
        x: 0.0,
        z: -40.0,
        radius: 10.0,
    });
    ctx.db.point_of_interest().insert(PointOfInterest {
        id: 0,
        name: "Wilderness Trail".into(),
        poi_type: "wilderness".into(),
        x: 30.0,
        z: -20.0,
        radius: 20.0,
    });
    ctx.db.point_of_interest().insert(PointOfInterest {
        id: 0,
        name: "Chapel".into(),
        poi_type: "inn".into(),
        x: 40.0,
        z: 40.0,
        radius: 10.0,
    });
    ctx.db.point_of_interest().insert(PointOfInterest {
        id: 0,
        name: "Dark Forest".into(),
        poi_type: "wilderness".into(),
        x: 10.0,
        z: 10.0,
        radius: 20.0,
    });

    // Spawn only the trader for debugging conversation flow
    spawn_npc(
        ctx,
        50.0,
        0.0,
        1,
        "trader".into(),
        "Merchant Ava".into(),
        100,
        "A merchant seeking profit through fair trade.".into(),
    );
    spawn_npc(
        ctx,
        10.0,
        10.0,
        3,
        "hostile".into(),
        "Skeleton Warrior".into(),
        0,
        "A restless undead warrior bound to guard the dark forest.".into(),
    );
    spawn_npc(
        ctx,
        -20.0,
        30.0,
        2,
        "guard".into(),
        "Town Guard".into(),
        10,
        "A dutiful guard protecting the town gate.".into(),
    );
    spawn_npc(
        ctx,
        0.0,
        -40.0,
        1,
        "historian".into(),
        "Elder Tome".into(),
        5,
        "A wise scholar preserving the town's history.".into(),
    );
    spawn_npc(
        ctx,
        30.0,
        -20.0,
        2,
        "traveller".into(),
        "Wandering Bard".into(),
        20,
        "A traveling bard collecting stories and songs.".into(),
    );
    spawn_npc(
        ctx,
        -10.0,
        50.0,
        3,
        "adventurer".into(),
        "Kira the Bold".into(),
        30,
        "A fearless adventurer seeking glory and treasure.".into(),
    );
    spawn_npc(
        ctx,
        40.0,
        40.0,
        1,
        "healer".into(),
        "Sister Mercy".into(),
        15,
        "A devoted healer offering aid to all who need it.".into(),
    );

    // Give trader starting inventory (health potions to sell)
    // item_def_id 3 = Health Potion from the auto_inc order above
    for npc in ctx.db.npc().iter() {
        if npc.role == "trader" {
            ctx.db.npc_inventory_item().insert(NpcInventoryItem {
                id: 0,
                npc_id: npc.id,
                slot: 0,
                item_def_id: 3,
                quantity: 5,
            });
            ctx.db.npc_inventory_item().insert(NpcInventoryItem {
                id: 0,
                npc_id: npc.id,
                slot: 1,
                item_def_id: mana_potion.id,
                quantity: 3,
            });
        }
    }

    schedule_next_npc_tick(ctx);
    schedule_next_projectile_tick(ctx);
}

#[spacetimedb::reducer]
pub fn start_npc_ticker(ctx: &ReducerContext) {
    for s in ctx.db.npc_tick_schedule().iter() {
        ctx.db
            .npc_tick_schedule()
            .scheduled_id()
            .delete(&s.scheduled_id);
    }
    schedule_next_npc_tick(ctx);
}

#[spacetimedb::reducer]
pub fn tick_npcs(ctx: &ReducerContext, _schedule: NpcTickSchedule) {
    // Regen player resources
    for player in ctx.db.player().iter().collect::<Vec<_>>() {
        let new_mana = (player.mana + MANA_REGEN_PER_TICK).min(player.max_mana);
        let new_stamina = (player.stamina + STAMINA_REGEN_PER_TICK).min(player.max_stamina);
        if new_mana != player.mana || new_stamina != player.stamina {
            ctx.db.player().identity().update(Player {
                mana: new_mana,
                stamina: new_stamina,
                ..player
            });
        }
    }

    // Tick status effects (DoT / HoT)
    for effect in ctx.db.status_effect().iter().collect::<Vec<_>>() {
        match effect.effect_type {
            StatusEffectType::Poison => {
                if effect.target_npc_id > 0 {
                    if let Some(npc) = ctx.db.npc().id().find(&effect.target_npc_id) {
                        let new_health = npc.health - effect.power;
                        if new_health <= 0 {
                            kill_npc(ctx, &npc, effect.source);
                        } else {
                            ctx.db.npc().id().update(Npc {
                                health: new_health,
                                ..npc
                            });
                        }
                    }
                } else if let Some(player) =
                    ctx.db.player().identity().find(&effect.target_identity)
                {
                    let new_health = player.health - effect.power;
                    if new_health <= 0 {
                        respawn_player(ctx, &player);
                    } else {
                        ctx.db.player().identity().update(Player {
                            health: new_health,
                            ..player
                        });
                    }
                }
            }
            StatusEffectType::Regen => {
                if let Some(player) = ctx.db.player().identity().find(&effect.target_identity) {
                    let new_health = (player.health + effect.power).min(player.max_health);
                    if new_health != player.health {
                        ctx.db.player().identity().update(Player {
                            health: new_health,
                            ..player
                        });
                    }
                }
            }
            StatusEffectType::Slow | StatusEffectType::Haste => {} // passive modifiers
        }
    }

    // Day/night cycle
    let is_night = update_day_night_cycle(ctx);
    // Track tick count for periodic checks
    static TICK_COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let tick_num = TICK_COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);

    // Track tree exhaustion — use tick counter + event log instead of static state
    // (WASM reducers are stateless; we use the event log to detect exhaustion)

    for npc in ctx.db.npc().iter() {
        // 1. Emotion decay
        apply_emotion_decay(ctx, npc.id);

        // 2. Night regen: if nighttime and NPC is at home, apply 5% regen
        if is_night {
            let dx = npc.position.x - npc.home_x;
            let dz = npc.position.z - npc.home_z;
            if (dx * dx + dz * dz).sqrt() <= 5.0 {
                let regen_hp = (npc.max_health * NPC_SLEEP_REGEN_PCT / 100).max(1);
                let regen_mp = (npc.max_mana * NPC_SLEEP_REGEN_PCT / 100).max(1);
                let regen_sp = (npc.max_stamina * NPC_SLEEP_REGEN_PCT / 100).max(1);
                let new_hp = (npc.health + regen_hp).min(npc.max_health);
                let new_mp = (npc.mana + regen_mp).min(npc.max_mana);
                let new_sp = (npc.stamina + regen_sp).min(npc.max_stamina);
                if new_hp != npc.health || new_mp != npc.mana || new_sp != npc.stamina {
                    ctx.db.npc().id().update(Npc {
                        health: new_hp, mana: new_mp, stamina: new_sp, ..npc.clone()
                    });
                }
            }
        }

        // 3. Load and evaluate unified tree
        let target = find_nearest_player(ctx, &npc.position)
            .filter(|(_, d)| *d <= NPC_DETECTION_RANGE)
            .map(|(p, _)| p);

        let tree = ctx.db.npc_behavior().npc_id().find(&npc.id)
            .and_then(|b| serde_json::from_str::<bonsai_bt::Behavior<NpcBtAction>>(&b.current_tree).ok())
            .unwrap_or_else(|| default_unified_tree(&npc.role));

        let nearby_npcs = find_nearby_npcs(ctx, &npc);
        let nearby_pois = find_nearby_pois(ctx, &npc);
        let eval_ctx = TreeEvalContext { is_night, nearby_npcs: &nearby_npcs, nearby_pois: &nearby_pois };

        let action = evaluate_tree(ctx, &tree, &npc, target.as_ref(), &eval_ctx);

        // 4. Execute action
        if let Some(ref action) = action {
            execute_bt_action(ctx, &npc, action, target.as_ref());
        }

        // 5. Follow destination (if set by TravelTo/TravelToPoi/GoHome actions)
        if let Some(dest) = ctx.db.npc_destination().npc_id().find(&npc.id) {
            // Re-fetch NPC in case position changed from action execution
            if let Some(cur_npc) = ctx.db.npc().id().find(&npc.id) {
                let dx = dest.target_x - cur_npc.position.x;
                let dz = dest.target_z - cur_npc.position.z;
                let dist = (dx * dx + dz * dz).sqrt();
                if dist <= NPC_CHASE_STEP {
                    ctx.db.npc().id().update(Npc {
                        position: Position { x: dest.target_x, y: NPC_GROUND_Y, z: dest.target_z },
                        ..cur_npc
                    });
                    ctx.db.npc_destination().npc_id().delete(&npc.id);
                } else {
                    let dir_x = dx / dist;
                    let dir_z = dz / dist;
                    let new_x = (cur_npc.position.x + dir_x * NPC_CHASE_STEP).clamp(WORLD_MIN, WORLD_MAX);
                    let new_z = (cur_npc.position.z + dir_z * NPC_CHASE_STEP).clamp(WORLD_MIN, WORLD_MAX);
                    ctx.db.npc().id().update(Npc {
                        position: Position { x: new_x, y: NPC_GROUND_Y, z: new_z },
                        ..cur_npc
                    });
                }
            }
        }

        // 6. Periodic checks (every 5 ticks ~2.5s)
        if tick_num % 5 == 0 {
            check_goal_conditions(ctx, &npc);
        }

        // 7. Tree regen on goal completion (detected in check_goal_conditions via event log)
        if has_recent_event(ctx, npc.id, "goal_completed", 2000) && !has_pending_decision(ctx, npc.id) {
            trigger_decision_enriched(ctx, &npc, "tree_generation", target.as_ref(), is_night);
        }

        // 8. Near-death experience trigger
        if npc.health > 0 && npc.health < npc.max_health / 10
            && has_recent_event(ctx, npc.id, "took_damage", 5000)
            && !has_pending_decision(ctx, npc.id)
        {
            log::info!("[NPC {}] near-death experience, triggering evaluation", npc.id);
            trigger_decision_enriched(ctx, &npc, "experience", target.as_ref(), is_night);
        }
    }

    // Belief/knowledge propagation between nearby NPCs (every 10 ticks ~5s)
    if tick_num % 10 == 0 {
        propagate_beliefs_and_knowledge(ctx);
    }

    schedule_next_npc_tick(ctx);
}

/// v2: Submit a unified behavior tree for an NPC
#[spacetimedb::reducer]
pub fn submit_npc_tree(ctx: &ReducerContext, npc_id: u64, tree_json: String) {
    if ctx.db.npc().id().find(&npc_id).is_none() {
        log::warn!("[NPC {}] submit_npc_tree: NPC not found", npc_id);
        ctx.db.npc_pending_decision().npc_id().delete(&npc_id);
        return;
    }
    match serde_json::from_str::<bonsai_bt::Behavior<NpcBtAction>>(&tree_json) {
        Ok(_) => {
            log::info!("[NPC {}] received new unified tree from LLM", npc_id);
            if ctx.db.npc_behavior().npc_id().find(&npc_id).is_some() {
                ctx.db.npc_behavior().npc_id().update(NpcBehavior {
                    npc_id, current_tree: tree_json,
                });
            } else {
                ctx.db.npc_behavior().insert(NpcBehavior {
                    npc_id, current_tree: tree_json,
                });
            }
        }
        Err(e) => {
            log::warn!("[NPC {}] invalid tree from LLM, keeping current: {e}", npc_id);
        }
    }
    ctx.db.npc_pending_decision().npc_id().delete(&npc_id);
}

/// v2: Submit identity deltas from experience evaluation
#[spacetimedb::reducer]
pub fn submit_npc_identity_update(
    ctx: &ReducerContext, npc_id: u64, json: String,
) -> Result<(), String> {
    ctx.db.npc().id().find(&npc_id).ok_or("NPC not found")?;
    let v: serde_json::Value = serde_json::from_str(&json)
        .map_err(|e| format!("Invalid JSON: {e}"))?;

    // Apply personality deltas
    if let Some(deltas) = v.get("personality_deltas").and_then(|d| d.as_object()) {
        if let Some(mut personality) = ctx.db.npc_personality().npc_id().find(&npc_id) {
            for (trait_name, delta) in deltas {
                let d = delta.as_f64().unwrap_or(0.0) as f32;
                match trait_name.as_str() {
                    "aggression" => personality.aggression = (personality.aggression + d).clamp(0.0, 1.0),
                    "sociability" => personality.sociability = (personality.sociability + d).clamp(0.0, 1.0),
                    "curiosity" => personality.curiosity = (personality.curiosity + d).clamp(0.0, 1.0),
                    "courage" => personality.courage = (personality.courage + d).clamp(0.0, 1.0),
                    "empathy" => personality.empathy = (personality.empathy + d).clamp(0.0, 1.0),
                    "discipline" => personality.discipline = (personality.discipline + d).clamp(0.0, 1.0),
                    _ => {}
                }
            }
            ctx.db.npc_personality().npc_id().update(personality);
        }
    }

    // Apply emotion adjustments
    if let Some(emotions) = v.get("emotion_adjustments").and_then(|e| e.as_object()) {
        for (emotion, delta) in emotions {
            let d = delta.as_f64().unwrap_or(0.0) as f32;
            trigger_emotion(ctx, npc_id, emotion, d);
        }
    }

    // Apply beliefs
    if let Some(beliefs) = v.get("beliefs").and_then(|b| b.as_array()) {
        let beliefs_json = serde_json::to_string(beliefs).unwrap_or_default();
        let _ = submit_npc_beliefs(ctx, npc_id, beliefs_json);
    }

    // Apply knowledge
    if let Some(knowledge) = v.get("knowledge").and_then(|k| k.as_array()) {
        for k in knowledge {
            let category = k.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
            let fact = k.get("fact").and_then(|f| f.as_str()).unwrap_or("").to_string();
            let confidence = k.get("confidence").and_then(|c| c.as_f64()).unwrap_or(0.8) as f32;
            if !category.is_empty() && !fact.is_empty() {
                let _ = submit_npc_knowledge(ctx, npc_id, category, fact, "llm_evaluation".to_string(), confidence);
            }
        }
    }

    // Apply relationship updates
    if let Some(rels) = v.get("relationship_updates").and_then(|r| r.as_array()) {
        let now_us = ctx.timestamp.to_duration_since_unix_epoch().unwrap_or_default().as_micros() as u64;
        for r in rels {
            let target_type = r.get("target_type").and_then(|t| t.as_str()).unwrap_or("").to_string();
            let target_id = r.get("target_id").and_then(|t| t.as_str()).unwrap_or("").to_string();
            let delta = r.get("delta").and_then(|d| d.as_i64()).unwrap_or(0) as i32;
            if !target_type.is_empty() && !target_id.is_empty() && delta != 0 {
                let existing = ctx.db.npc_relationship().iter()
                    .find(|rel| rel.npc_id == npc_id && rel.target_type == target_type && rel.target_id == target_id);
                if let Some(existing) = existing {
                    ctx.db.npc_relationship().id().update(NpcRelationship {
                        disposition: (existing.disposition + delta).clamp(-100, 100),
                        updated_at: now_us,
                        ..existing
                    });
                } else {
                    ctx.db.npc_relationship().insert(NpcRelationship {
                        id: 0, npc_id, target_type, target_id,
                        disposition: delta.clamp(-100, 100),
                        context: String::new(), updated_at: now_us,
                    });
                }
            }
        }
    }

    // Apply memories
    if let Some(memories) = v.get("memories").and_then(|m| m.as_array()) {
        for m in memories {
            if let Some(text) = m.as_str() {
                if !text.is_empty() {
                    let _ = submit_npc_memory(ctx, npc_id, text.to_string());
                }
            }
        }
    }

    log::info!("[NPC {}] identity update applied", npc_id);
    ctx.db.npc_pending_decision().npc_id().delete(&npc_id);
    Ok(())
}

/// v2: Submit a speech response for a conversation
#[spacetimedb::reducer]
pub fn submit_npc_speech(ctx: &ReducerContext, npc_id: u64, message: String) {
    if let Some(npc) = ctx.db.npc().id().find(&npc_id) {
        let text = message.chars().take(NPC_CHAT_MAX_LENGTH).collect::<String>();
        if !text.is_empty() {
            ctx.db.npc_chat_message().insert(NpcChatMessage {
                scheduled_id: 0,
                scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(NPC_CHAT_MESSAGE_EXPIRE_MS)),
                npc_id,
                text,
                position: npc.position.clone(),
            });
            log_npc_event(ctx, npc_id, "responded_to_chat", "{}");
        }
    }
    ctx.db.npc_pending_decision().npc_id().delete(&npc_id);
}

#[spacetimedb::reducer]
pub fn spawn_npc(
    ctx: &ReducerContext,
    x: f32,
    z: f32,
    level: i32,
    role: String,
    name: String,
    gold: i32,
    persona: String,
) {
    let hp = npc_max_health(level);
    let mp = npc_max_mana(level);
    let sp = npc_max_stamina(level);
    let npc = ctx.db.npc().insert(Npc {
        id: 0,
        position: Position {
            x: x.clamp(WORLD_MIN, WORLD_MAX),
            y: NPC_GROUND_Y,
            z: z.clamp(WORLD_MIN, WORLD_MAX),
        },
        health: hp,
        max_health: hp,
        level,
        role,
        name,
        gold,
        mana: mp,
        max_mana: mp,
        stamina: sp,
        max_stamina: sp,
        xp: 0,
        home_x: x.clamp(WORLD_MIN, WORLD_MAX),
        home_z: z.clamp(WORLD_MIN, WORLD_MAX),
        persona,
    });
    let tree = default_unified_tree(&npc.role);
    let tree_json = serde_json::to_string(&tree).unwrap_or_default();
    ctx.db.npc_behavior().insert(NpcBehavior {
        npc_id: npc.id,
        current_tree: tree_json,
    });
    let mut personality = default_personality_for_role(&npc.role);
    personality.npc_id = npc.id;
    ctx.db.npc_personality().insert(personality);
    ctx.db.npc_emotion().insert(NpcEmotion {
        npc_id: npc.id,
        anger: 0.0, fear: 0.0, joy: 0.0, sadness: 0.0, surprise: 0.0, disgust: 0.0,
    });
}

#[spacetimedb::reducer]
pub fn join_game(ctx: &ReducerContext) {
    if let Some(existing) = ctx.db.player().identity().find(&ctx.sender()) {
        let bonuses = equipment_bonuses(ctx, &ctx.sender());
        let mh = player_max_health(existing.level) + bonuses.health;
        let mm = player_max_mana(existing.level) + bonuses.mana;
        let ms = player_max_stamina(existing.level) + bonuses.stamina;
        ctx.db.player().identity().update(Player {
            position: Position {
                x: 0.0,
                y: 1.0,
                z: 0.0,
            },
            health: mh,
            max_health: mh,
            mana: mm,
            max_mana: mm,
            stamina: ms,
            max_stamina: ms,
            ..existing
        });
    } else {
        let mh = player_max_health(1);
        let mm = player_max_mana(1);
        let ms = player_max_stamina(1);
        ctx.db.player().insert(Player {
            identity: ctx.sender(),
            position: Position {
                x: 0.0,
                y: 1.0,
                z: 0.0,
            },
            health: mh,
            max_health: mh,
            level: 1,
            xp: 0,
            mana: mm,
            max_mana: mm,
            stamina: ms,
            max_stamina: ms,
            facing_angle: 0.0,
            last_seq: 0,
        });
        give_all_skills(ctx, ctx.sender());
    }
}

#[spacetimedb::reducer(client_disconnected)]
pub fn identity_disconnected(ctx: &ReducerContext) {
    ctx.db.player().identity().delete(&ctx.sender());
}

#[spacetimedb::reducer]
pub fn move_player(ctx: &ReducerContext, x: f32, y: f32, z: f32, seq: u32) -> Result<(), String> {
    let player = ctx
        .db
        .player()
        .identity()
        .find(&ctx.sender())
        .ok_or("Player not found")?;

    // Determine max move distance based on active speed effects
    let mut max_dist = MAX_MOVE_DIST;
    for effect in ctx.db.status_effect().iter() {
        if effect.target_identity == ctx.sender() && effect.target_npc_id == 0 {
            match effect.effect_type {
                StatusEffectType::Slow => {
                    max_dist = max_dist.min(MAX_MOVE_DIST_SLOW);
                }
                StatusEffectType::Haste => {
                    max_dist = max_dist.max(MAX_MOVE_DIST_HASTE);
                }
                _ => {}
            }
        }
    }

    // Simple anti-teleport: reject moves beyond max_dist on the XZ plane.
    let dx = x - player.position.x;
    let dz = z - player.position.z;
    if (dx * dx + dz * dz).sqrt() > max_dist {
        return Err("Moved too far".to_string());
    }

    ctx.db.player().identity().update(Player {
        position: Position {
            x: x.clamp(WORLD_MIN, WORLD_MAX),
            y,
            z: z.clamp(WORLD_MIN, WORLD_MAX),
        },
        last_seq: seq,
        ..player
    });
    Ok(())
}

#[spacetimedb::reducer]
pub fn rotate_player(ctx: &ReducerContext, angle: f32) -> Result<(), String> {
    let player = ctx
        .db
        .player()
        .identity()
        .find(&ctx.sender())
        .ok_or("Player not found")?;
    ctx.db.player().identity().update(Player {
        facing_angle: angle,
        ..player
    });
    Ok(())
}

#[spacetimedb::reducer]
pub fn use_skill(
    ctx: &ReducerContext,
    skill_id: u64,
    target_x: f32,
    target_y: f32,
    target_z: f32,
) -> Result<(), String> {
    let player = ctx
        .db
        .player()
        .identity()
        .find(&ctx.sender())
        .ok_or("Player not found")?;
    let skill_def = ctx
        .db
        .skill_def()
        .id()
        .find(&skill_id)
        .ok_or("Skill not found")?;

    let _ = ctx
        .db
        .player_skill()
        .iter()
        .find(|ps| ps.player_identity == ctx.sender() && ps.skill_id == skill_id)
        .ok_or("Skill not available")?;

    let attrs = ctx
        .db
        .skill_attributes()
        .iter()
        .find(|a| a.player_identity == ctx.sender() && a.skill_id == skill_id)
        .ok_or("Skill attributes not found")?;

    let stats = compute_stats(&attrs);

    // Check cooldown
    let now_us = ctx
        .timestamp
        .to_duration_since_unix_epoch()
        .unwrap_or_default()
        .as_micros();
    if let Some(cd) = ctx
        .db
        .skill_cooldown()
        .iter()
        .find(|cd| cd.player_identity == ctx.sender() && cd.skill_id == skill_id)
    {
        let ready_us = cd
            .ready_at
            .to_duration_since_unix_epoch()
            .unwrap_or_default()
            .as_micros();
        if now_us < ready_us {
            return Err("Skill on cooldown".to_string());
        }
    }

    // Check and deduct resource
    match skill_def.resource_type {
        ResourceType::Mana => {
            if player.mana < stats.resource_cost {
                return Err("Not enough mana".to_string());
            }
            ctx.db.player().identity().update(Player {
                mana: player.mana - stats.resource_cost,
                ..player.clone()
            });
        }
        ResourceType::Stamina => {
            if player.stamina < stats.resource_cost {
                return Err("Not enough stamina".to_string());
            }
            ctx.db.player().identity().update(Player {
                stamina: player.stamina - stats.resource_cost,
                ..player.clone()
            });
        }
    }

    // Set cooldown
    let ready_at = ctx.timestamp + Duration::from_millis(stats.cooldown_ms);
    if let Some(cd) = ctx
        .db
        .skill_cooldown()
        .iter()
        .find(|cd| cd.player_identity == ctx.sender() && cd.skill_id == skill_id)
    {
        ctx.db
            .skill_cooldown()
            .id()
            .update(SkillCooldown { ready_at, ..cd });
    } else {
        ctx.db.skill_cooldown().insert(SkillCooldown {
            id: 0,
            player_identity: ctx.sender(),
            skill_id,
            ready_at,
        });
    }

    let target_pos = Position {
        x: target_x,
        y: target_y,
        z: target_z,
    };
    let skill_effect = effect_for_skill(&skill_def.name, stats.duration_ms);
    let atk_bonus = equipment_bonuses(ctx, &ctx.sender()).attack;
    let skill_power = stats.power + atk_bonus;

    match skill_def.behavior_type {
        BehaviorType::Melee => {
            let nearest_npc = ctx
                .db
                .npc()
                .iter()
                .filter(|n| n.position.distance_to(&player.position) <= stats.range)
                .min_by(|a, b| {
                    a.position
                        .distance_to(&player.position)
                        .partial_cmp(&b.position.distance_to(&player.position))
                        .unwrap()
                });
            let nearest_player = ctx
                .db
                .player()
                .iter()
                .filter(|p| p.identity != ctx.sender())
                .filter(|p| p.position.distance_to(&player.position) <= stats.range)
                .min_by(|a, b| {
                    a.position
                        .distance_to(&player.position)
                        .partial_cmp(&b.position.distance_to(&player.position))
                        .unwrap()
                });
            match (nearest_npc, nearest_player) {
                (Some(n), Some(p)) => {
                    if n.position.distance_to(&player.position)
                        <= p.position.distance_to(&player.position)
                    {
                        hit_npc(
                            ctx,
                            &n,
                            skill_power,
                            stats.knockback,
                            &player.position,
                            ctx.sender(),
                            skill_id,
                            SKILL_XP_PER_HIT,
                            skill_effect.clone(),
                        );
                    } else {
                        hit_player(
                            ctx,
                            &p,
                            skill_power,
                            stats.knockback,
                            &player.position,
                            ctx.sender(),
                            skill_id,
                            SKILL_XP_PER_HIT,
                            skill_effect.clone(),
                        );
                    }
                }
                (Some(n), None) => hit_npc(
                    ctx,
                    &n,
                    skill_power,
                    stats.knockback,
                    &player.position,
                    ctx.sender(),
                    skill_id,
                    SKILL_XP_PER_HIT,
                    skill_effect.clone(),
                ),
                (None, Some(p)) => hit_player(
                    ctx,
                    &p,
                    skill_power,
                    stats.knockback,
                    &player.position,
                    ctx.sender(),
                    skill_id,
                    SKILL_XP_PER_HIT,
                    skill_effect.clone(),
                ),
                (None, None) => {}
            }
        }
        BehaviorType::Projectile => {
            // Compute direction from player toward cursor target on XZ plane
            let dx = target_pos.x - player.position.x;
            let dz = target_pos.z - player.position.z;
            let len = (dx * dx + dz * dz).sqrt();
            let (dir_x, dir_z) = if len > 0.001 {
                (dx / len, dz / len)
            } else {
                (0.0, -1.0)
            };

            let now_ms = (now_us / 1000) as u64;
            ctx.db.projectile().insert(Projectile {
                scheduled_id: 0,
                scheduled_at: ScheduleAt::Time(
                    ctx.timestamp + Duration::from_millis(PROJECTILE_MAX_LIFETIME_MS),
                ),
                owner: ctx.sender(),
                skill_id,
                start_x: player.position.x,
                start_y: player.position.y,
                start_z: player.position.z,
                dir_x,
                dir_z,
                speed: PROJECTILE_SPEED,
                max_range: stats.range,
                power: skill_power,
                knockback: stats.knockback,
                hit_radius: PROJECTILE_HIT_RADIUS,
                started_at: now_ms,
            });
        }
        BehaviorType::GroundAoe => {
            if player.position.distance_to(&target_pos) > stats.range {
                return Err("Target out of range".to_string());
            }
            let radius = if stats.aoe_radius > 0.0 {
                stats.aoe_radius
            } else {
                5.0
            };
            let now_ms = (now_us / 1000) as u64;

            // Apply first tick immediately so the skill doesn't feel delayed
            for npc in ctx.db.npc().iter().collect::<Vec<_>>() {
                if npc.position.distance_to(&target_pos) <= radius {
                    hit_npc(
                        ctx,
                        &npc,
                        skill_power,
                        stats.knockback,
                        &target_pos,
                        ctx.sender(),
                        skill_id,
                        SKILL_XP_PER_HIT,
                        skill_effect.clone(),
                    );
                }
            }
            for p in ctx.db.player().iter().collect::<Vec<_>>() {
                if p.identity != ctx.sender() && p.position.distance_to(&target_pos) <= radius {
                    hit_player(
                        ctx,
                        &p,
                        skill_power,
                        stats.knockback,
                        &target_pos,
                        ctx.sender(),
                        skill_id,
                        SKILL_XP_PER_HIT,
                        skill_effect.clone(),
                    );
                }
            }

            // Insert lingering zone for periodic damage
            ctx.db.aoe_zone().insert(AoeZone {
                scheduled_id: 0,
                scheduled_at: ScheduleAt::Time(
                    ctx.timestamp + Duration::from_millis(AOE_DEFAULT_DURATION_MS),
                ),
                owner: ctx.sender(),
                skill_id,
                center_x: target_pos.x,
                center_y: target_pos.y,
                center_z: target_pos.z,
                radius,
                power: skill_power,
                knockback: stats.knockback,
                tick_interval_ms: AOE_TICK_INTERVAL_MS,
                last_tick_at: now_ms,
                started_at: now_ms,
            });
        }
        BehaviorType::Buff => {
            let player = ctx
                .db
                .player()
                .identity()
                .find(&ctx.sender())
                .ok_or("Player not found")?;
            let new_health = (player.health + stats.power).min(player.max_health);
            let healed = new_health - player.health;
            ctx.db.player().identity().update(Player {
                health: new_health,
                ..player
            });
            if healed > 0 {
                award_skill_xp(ctx, ctx.sender(), skill_id, healed);
            }
            apply_status_effect(
                ctx,
                StatusEffectType::Regen,
                ctx.sender(),
                0,
                EFFECT_REGEN_POWER,
                stats.duration_ms.max(EFFECT_DEFAULT_DURATION_MS),
                ctx.sender(),
            );
        }
        BehaviorType::Mobility => {
            // Cooldown and resource already consumed above.
            // Client handles the visual effect (jump arc, dash movement, etc.).
        }
        BehaviorType::Targeted => {
            // Targeted skills use use_targeted_skill reducer instead.
            return Err("Targeted skills must use use_targeted_skill".to_string());
        }
    }

    // Mobility skills get XP on cast; damage skills get XP from hit_npc/hit_player; buff XP handled inline
    if skill_def.behavior_type == BehaviorType::Mobility {
        award_skill_xp(ctx, ctx.sender(), skill_id, SKILL_XP_PER_USE);
    }

    // Compute direction from player toward target for animations
    let dx = target_pos.x - player.position.x;
    let dz = target_pos.z - player.position.z;
    let len = (dx * dx + dz * dz).sqrt();
    let (anim_dir_x, anim_dir_z) = if len > 0.001 {
        (dx / len, dz / len)
    } else {
        (0.0, -1.0)
    };

    // Broadcast ability usage to all clients via ActiveSkill table.
    let anim_duration_ms: u64 = match skill_def.behavior_type {
        BehaviorType::Mobility => 800,
        BehaviorType::Melee => 500,
        BehaviorType::Projectile => 600,
        BehaviorType::GroundAoe => 700,
        BehaviorType::Buff => 500,
        BehaviorType::Targeted => 500,
    };
    ctx.db.active_skill().insert(ActiveSkill {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(anim_duration_ms)),
        player_identity: ctx.sender(),
        skill_id,
        started_at: now_us as u64,
        target_x: target_pos.x,
        target_y: target_pos.y,
        target_z: target_pos.z,
        dir_x: anim_dir_x,
        dir_z: anim_dir_z,
    });

    // Degrade weapon after any skill use
    degrade_weapon(ctx, &ctx.sender());

    Ok(())
}

#[spacetimedb::reducer]
pub fn allocate_skill_point(
    ctx: &ReducerContext,
    skill_id: u64,
    attribute: String,
) -> Result<(), String> {
    let ps = ctx
        .db
        .player_skill()
        .iter()
        .find(|ps| ps.player_identity == ctx.sender() && ps.skill_id == skill_id)
        .ok_or("Skill not found")?;

    let attrs = ctx
        .db
        .skill_attributes()
        .iter()
        .find(|a| a.player_identity == ctx.sender() && a.skill_id == skill_id)
        .ok_or("Skill attributes not found")?;

    if points_allocated(&attrs) >= total_skill_points(ps.level) {
        return Err("No unspent points".to_string());
    }

    let mut new_attrs = attrs.clone();
    match attribute.as_str() {
        "damage" => new_attrs.damage_points += 1,
        "cooldown" => new_attrs.cooldown_points += 1,
        "aoe" => new_attrs.aoe_points += 1,
        "range" => new_attrs.range_points += 1,
        "duration" => new_attrs.duration_points += 1,
        "projectile_count" => new_attrs.projectile_count_points += 1,
        "knockback" => new_attrs.knockback_points += 1,
        "resource_cost" => new_attrs.resource_cost_points += 1,
        "cast_speed" => new_attrs.cast_speed_points += 1,
        _ => return Err(format!("Unknown attribute: {attribute}")),
    }
    ctx.db.skill_attributes().id().update(new_attrs);
    Ok(())
}

#[spacetimedb::reducer]
pub fn expire_active_skill(_ctx: &ReducerContext, _row: ActiveSkill) {
    // Row auto-deletes after this reducer completes.
}

#[spacetimedb::reducer]
pub fn expire_projectile(_ctx: &ReducerContext, _row: Projectile) {
    // Row auto-deletes after this reducer completes.
}

#[spacetimedb::reducer]
pub fn expire_aoe_zone(_ctx: &ReducerContext, _row: AoeZone) {
    // Row auto-deletes after this reducer completes.
}

#[spacetimedb::reducer]
pub fn expire_ground_item(_ctx: &ReducerContext, _row: GroundItem) {
    // Row auto-deletes after this reducer completes.
}

#[spacetimedb::reducer]
pub fn expire_status_effect(_ctx: &ReducerContext, _row: StatusEffect) {
    // Row auto-deletes after this reducer completes.
}

#[spacetimedb::reducer]
pub fn send_chat_message(ctx: &ReducerContext, text: String) -> Result<(), String> {
    let player = ctx
        .db
        .player()
        .identity()
        .find(&ctx.sender())
        .ok_or("Player not found")?;
    let text = text.trim().to_string();
    if text.is_empty() {
        return Err("Empty message".into());
    }
    if text.len() > CHAT_MAX_LENGTH {
        return Err("Message too long".into());
    }
    ctx.db.chat_message().insert(ChatMessage {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(
            ctx.timestamp + Duration::from_millis(CHAT_MESSAGE_EXPIRE_MS),
        ),
        sender: ctx.sender(),
        sender_name: String::new(),
        text: text.clone(),
        position: player.position.clone(),
    });

    // Notify nearby NPCs with engagement-based confidence
    log::info!(
        "[CHAT] Player said: \"{}\" at ({:.1}, {:.1}, {:.1})",
        text, player.position.x, player.position.y, player.position.z
    );
    let now_us = ctx.timestamp.to_duration_since_unix_epoch()
        .unwrap_or_default().as_micros() as u64;
    let player_hex = ctx.sender().to_hex().to_string();

    for npc in ctx.db.npc().iter() {
        let dist = npc.position.distance_to(&player.position);
        if dist > NPC_DETECTION_RANGE { continue; }

        // Calculate engagement level based on distance and NPC state
        let engagement = if dist <= ATTACK_RANGE {
            // Very close — focused
            1.0_f32
        } else if dist <= NPC_DETECTION_RANGE * 0.5 {
            // Mid-range — attentive
            0.5
        } else {
            // Far — overhearing
            0.2
        };

        // Topic relevance: check if any word in the message matches NPC's role or active goals
        let text_lower = text.to_lowercase();
        let role_relevant = match npc.role.as_str() {
            "guard" => text_lower.contains("danger") || text_lower.contains("bandit")
                || text_lower.contains("attack") || text_lower.contains("threat")
                || text_lower.contains("help") || text_lower.contains("guard"),
            "trader" | "merchant" => text_lower.contains("buy") || text_lower.contains("sell")
                || text_lower.contains("price") || text_lower.contains("trade")
                || text_lower.contains("potion") || text_lower.contains("item"),
            "healer" => text_lower.contains("heal") || text_lower.contains("hurt")
                || text_lower.contains("potion") || text_lower.contains("health"),
            _ => false,
        };
        let topic_relevance: f32 = if role_relevant { 1.0 } else { 0.5 };
        let confidence = engagement * topic_relevance;

        // Log detailed heard_speech event
        let escaped_text = text.replace('\\', "\\\\").replace('"', "\\\"");
        let engagement_label = if engagement >= 1.0 { "focused" }
            else if engagement >= 0.5 { "attentive" }
            else { "overhearing" };

        log_npc_event(ctx, npc.id, "heard_chat", &format!(
            r#"{{"player":"{}","text":"{}","distance":{:.1},"engagement":"{}","confidence":{:.2},"topic_relevance":{:.1}}}"#,
            player_hex, escaped_text, dist, engagement_label, confidence, topic_relevance
        ));

        // Auto-create belief from overheard speech (at scaled confidence)
        if confidence >= 0.3 && !text.is_empty() {
            let existing = ctx.db.npc_belief().iter()
                .find(|b| b.npc_id == npc.id && b.subject == format!("player:{}", player_hex)
                    && b.predicate == "said");
            if let Some(existing) = existing {
                ctx.db.npc_belief().id().update(NpcBelief {
                    object: text.chars().take(100).collect(),
                    confidence,
                    updated_at: now_us,
                    ..existing
                });
            } else {
                let count = ctx.db.npc_belief().iter().filter(|b| b.npc_id == npc.id).count();
                if count < MAX_NPC_BELIEFS {
                    ctx.db.npc_belief().insert(NpcBelief {
                        id: 0, npc_id: npc.id,
                        subject: format!("player:{}", player_hex),
                        predicate: "said".to_string(),
                        object: text.chars().take(100).collect(),
                        confidence,
                        updated_at: now_us,
                    });
                }
            }
        }

        log::info!(
            "[CHAT] NPC {} ({}) heard chat (dist={:.1}, engagement={}, confidence={:.2})",
            npc.id, npc.name, dist, engagement_label, confidence
        );
    }
    Ok(())
}

#[spacetimedb::reducer]
pub fn expire_chat_message(_ctx: &ReducerContext, _row: ChatMessage) {
    // Row auto-deletes after this reducer completes.
}

#[spacetimedb::reducer]
pub fn expire_npc_chat_message(_ctx: &ReducerContext, _row: NpcChatMessage) {
    // Row auto-deletes after this reducer completes.
}

#[spacetimedb::reducer]
pub fn expire_npc_event(_ctx: &ReducerContext, _row: NpcEventLog) {
    // Row auto-deletes after this reducer completes.
}

const MAX_NPC_MEMORIES: usize = 10;

#[spacetimedb::reducer]
pub fn submit_npc_memory(ctx: &ReducerContext, npc_id: u64, text: String) -> Result<(), String> {
    ctx.db.npc().id().find(&npc_id).ok_or("NPC not found")?;
    let now_us = ctx
        .timestamp
        .to_duration_since_unix_epoch()
        .unwrap_or_default()
        .as_micros() as u64;

    // Prune oldest memories if at limit
    let mut existing: Vec<_> = ctx
        .db
        .npc_memory()
        .iter()
        .filter(|m| m.npc_id == npc_id)
        .collect();
    existing.sort_by_key(|m| m.created_at);
    while existing.len() >= MAX_NPC_MEMORIES {
        if let Some(oldest) = existing.first() {
            ctx.db.npc_memory().id().delete(&oldest.id);
            existing.remove(0);
        }
    }

    ctx.db.npc_memory().insert(NpcMemory {
        id: 0,
        npc_id,
        text,
        created_at: now_us,
    });
    Ok(())
}

#[spacetimedb::reducer]
pub fn submit_npc_actions(
    ctx: &ReducerContext,
    npc_id: u64,
    actions_json: String,
) -> Result<(), String> {
    log::info!(
        "[NPC {}] submit_npc_actions called with: {}",
        npc_id,
        actions_json
    );

    let _npc = match ctx.db.npc().id().find(&npc_id) {
        Some(n) => n,
        None => {
            log::warn!("[NPC {}] not found, clearing pending decision", npc_id);
            ctx.db.npc_pending_decision().npc_id().delete(&npc_id);
            return Err("NPC not found".to_string());
        }
    };

    let actions: Vec<npc_ai::NpcAction> = serde_json::from_str(&actions_json).map_err(|e| {
        log::error!("[NPC {}] failed to parse actions: {}", npc_id, e);
        format!("Invalid actions JSON: {e}")
    })?;

    log::info!("[NPC {}] executing {} action(s)", npc_id, actions.len());

    for action in actions {
        // Re-fetch NPC each iteration in case it died from a previous action
        let Some(npc) = ctx.db.npc().id().find(&npc_id) else {
            log::warn!("[NPC {}] died mid-execution, stopping", npc_id);
            break;
        };

        match action {
            npc_ai::NpcAction::MoveTo { x, z } => {
                let clamped_x = x.clamp(WORLD_MIN, WORLD_MAX);
                let clamped_z = z.clamp(WORLD_MIN, WORLD_MAX);
                log::info!(
                    "[NPC {}] move_to ({:.1}, {:.1}) from ({:.1}, {:.1})",
                    npc_id,
                    clamped_x,
                    clamped_z,
                    npc.position.x,
                    npc.position.z
                );
                if ctx.db.npc_destination().npc_id().find(&npc_id).is_some() {
                    ctx.db.npc_destination().npc_id().update(NpcDestination {
                        npc_id,
                        target_x: clamped_x,
                        target_z: clamped_z,
                    });
                } else {
                    ctx.db.npc_destination().insert(NpcDestination {
                        npc_id,
                        target_x: clamped_x,
                        target_z: clamped_z,
                    });
                }
            }
            npc_ai::NpcAction::Attack {
                target_type,
                target_id,
            } => {
                let dmg = crate::skill::npc_damage(npc.level);
                log::info!(
                    "[NPC {}] attack {} {} (dmg={})",
                    npc_id,
                    target_type,
                    target_id,
                    dmg
                );
                match target_type.as_str() {
                    "player" => {
                        if let Ok(identity) = spacetimedb::Identity::from_hex(&target_id) {
                            if let Some(player) = ctx.db.player().identity().find(&identity) {
                                let dist = npc.position.distance_to(&player.position);
                                if dist <= ATTACK_RANGE {
                                    let new_health = player.health - dmg;
                                    log::info!(
                                        "[NPC {}] hit player {} for {} dmg (hp: {} → {})",
                                        npc_id,
                                        target_id,
                                        dmg,
                                        player.health,
                                        new_health
                                    );
                                    if new_health <= 0 {
                                        log::info!("[NPC {}] killed player {}", npc_id, target_id);
                                        respawn_player(ctx, &player);
                                    } else {
                                        ctx.db.player().identity().update(Player {
                                            health: new_health,
                                            ..player
                                        });
                                    }
                                } else {
                                    log::warn!(
                                        "[NPC {}] attack out of range: dist={:.1} > range={:.1}",
                                        npc_id,
                                        dist,
                                        ATTACK_RANGE
                                    );
                                }
                            } else {
                                log::warn!(
                                    "[NPC {}] attack target player {} not found",
                                    npc_id,
                                    target_id
                                );
                            }
                        } else {
                            log::warn!(
                                "[NPC {}] invalid player identity hex: {}",
                                npc_id,
                                target_id
                            );
                        }
                    }
                    "npc" => {
                        if let Ok(target_npc_id) = target_id.parse::<u64>() {
                            if target_npc_id != npc_id {
                                if let Some(target_npc) = ctx.db.npc().id().find(&target_npc_id) {
                                    let dist = npc.position.distance_to(&target_npc.position);
                                    if dist <= ATTACK_RANGE {
                                        let new_health = target_npc.health - dmg;
                                        log::info!(
                                            "[NPC {}] hit NPC {} for {} dmg (hp: {} → {})",
                                            npc_id,
                                            target_npc_id,
                                            dmg,
                                            target_npc.health,
                                            new_health
                                        );
                                        if new_health <= 0 {
                                            log::info!(
                                                "[NPC {}] killed NPC {}",
                                                npc_id,
                                                target_npc_id
                                            );
                                            kill_npc(ctx, &target_npc, ctx.sender());
                                        } else {
                                            ctx.db.npc().id().update(Npc {
                                                health: new_health,
                                                ..target_npc
                                            });
                                        }
                                    } else {
                                        log::warn!(
                                            "[NPC {}] attack NPC {} out of range: dist={:.1}",
                                            npc_id,
                                            target_npc_id,
                                            dist
                                        );
                                    }
                                } else {
                                    log::warn!(
                                        "[NPC {}] attack target NPC {} not found",
                                        npc_id,
                                        target_npc_id
                                    );
                                }
                            } else {
                                log::warn!("[NPC {}] tried to attack self", npc_id);
                            }
                        }
                    }
                    other => {
                        log::warn!("[NPC {}] unknown attack target_type: {}", npc_id, other);
                    }
                }
            }
            npc_ai::NpcAction::Say { message } => {
                let text = message
                    .chars()
                    .take(NPC_CHAT_MAX_LENGTH)
                    .collect::<String>();
                log::info!("[NPC {}] say: \"{}\"", npc_id, text);
                if !text.is_empty() {
                    ctx.db.npc_chat_message().insert(NpcChatMessage {
                        scheduled_id: 0,
                        scheduled_at: ScheduleAt::Time(
                            ctx.timestamp + Duration::from_millis(NPC_CHAT_MESSAGE_EXPIRE_MS),
                        ),
                        npc_id,
                        text,
                        position: npc.position.clone(),
                    });
                }
            }
            npc_ai::NpcAction::Wander => {
                log::info!("[NPC {}] wander (clearing destination)", npc_id);
                ctx.db.npc_destination().npc_id().delete(&npc_id);
            }
        }
    }

    // Always clear pending decision to prevent infinite retry
    ctx.db.npc_pending_decision().npc_id().delete(&npc_id);
    log::info!("[NPC {}] pending decision cleared", npc_id);
    Ok(())
}

#[spacetimedb::reducer]
pub fn tick_projectiles(ctx: &ReducerContext, _schedule: ProjectileTickSchedule) {
    let now_us = ctx
        .timestamp
        .to_duration_since_unix_epoch()
        .unwrap_or_default()
        .as_micros();
    let now_ms = (now_us / 1000) as u64;

    // Tick projectiles
    for proj in ctx.db.projectile().iter().collect::<Vec<_>>() {
        let elapsed_s = (now_ms.saturating_sub(proj.started_at)) as f32 / 1000.0;
        let dist = proj.speed * elapsed_s;

        // Current position
        let px = proj.start_x + proj.dir_x * dist;
        let pz = proj.start_z + proj.dir_z * dist;
        let proj_pos = Position {
            x: px,
            y: proj.start_y,
            z: pz,
        };

        // Check if exceeded max range
        if dist > proj.max_range {
            ctx.db
                .projectile()
                .scheduled_id()
                .delete(&proj.scheduled_id);
            continue;
        }

        // Look up skill def to determine status effect at impact
        let proj_effect = ctx.db.skill_def().id().find(&proj.skill_id).and_then(|sd| {
            // We need duration from the attacker's skill attributes
            let dur = ctx
                .db
                .skill_attributes()
                .iter()
                .find(|a| a.player_identity == proj.owner && a.skill_id == proj.skill_id)
                .map(|a| compute_stats(&a).duration_ms)
                .unwrap_or(EFFECT_DEFAULT_DURATION_MS);
            effect_for_skill(&sd.name, dur)
        });

        // Check collision against NPCs
        let mut hit = false;
        for npc in ctx.db.npc().iter().collect::<Vec<_>>() {
            if proj_pos.distance_to(&npc.position) <= proj.hit_radius {
                hit_npc(
                    ctx,
                    &npc,
                    proj.power,
                    proj.knockback,
                    &proj_pos,
                    proj.owner,
                    proj.skill_id,
                    SKILL_XP_PER_HIT,
                    proj_effect.clone(),
                );
                hit = true;
                break;
            }
        }
        if hit {
            ctx.db
                .projectile()
                .scheduled_id()
                .delete(&proj.scheduled_id);
            continue;
        }

        // Check collision against players (excluding owner)
        for p in ctx.db.player().iter().collect::<Vec<_>>() {
            if p.identity != proj.owner && proj_pos.distance_to(&p.position) <= proj.hit_radius {
                hit_player(
                    ctx,
                    &p,
                    proj.power,
                    proj.knockback,
                    &proj_pos,
                    proj.owner,
                    proj.skill_id,
                    SKILL_XP_PER_HIT,
                    proj_effect.clone(),
                );
                hit = true;
                break;
            }
        }
        if hit {
            ctx.db
                .projectile()
                .scheduled_id()
                .delete(&proj.scheduled_id);
        }
    }

    // Tick AoE zones
    for zone in ctx.db.aoe_zone().iter().collect::<Vec<_>>() {
        if now_ms.saturating_sub(zone.last_tick_at) >= zone.tick_interval_ms {
            let center = Position {
                x: zone.center_x,
                y: zone.center_y,
                z: zone.center_z,
            };
            let zone_effect = ctx.db.skill_def().id().find(&zone.skill_id).and_then(|sd| {
                let dur = ctx
                    .db
                    .skill_attributes()
                    .iter()
                    .find(|a| a.player_identity == zone.owner && a.skill_id == zone.skill_id)
                    .map(|a| compute_stats(&a).duration_ms)
                    .unwrap_or(EFFECT_DEFAULT_DURATION_MS);
                effect_for_skill(&sd.name, dur)
            });
            for npc in ctx.db.npc().iter().collect::<Vec<_>>() {
                if npc.position.distance_to(&center) <= zone.radius {
                    hit_npc(
                        ctx,
                        &npc,
                        zone.power,
                        zone.knockback,
                        &center,
                        zone.owner,
                        zone.skill_id,
                        SKILL_XP_PER_AOE_TICK,
                        zone_effect.clone(),
                    );
                }
            }
            for p in ctx.db.player().iter().collect::<Vec<_>>() {
                if p.identity != zone.owner && p.position.distance_to(&center) <= zone.radius {
                    hit_player(
                        ctx,
                        &p,
                        zone.power,
                        zone.knockback,
                        &center,
                        zone.owner,
                        zone.skill_id,
                        SKILL_XP_PER_AOE_TICK,
                        zone_effect.clone(),
                    );
                }
            }
            ctx.db.aoe_zone().scheduled_id().update(AoeZone {
                last_tick_at: now_ms,
                ..zone
            });
        }
    }

    schedule_next_projectile_tick(ctx);
}

#[spacetimedb::reducer]
pub fn start_projectile_ticker(ctx: &ReducerContext) {
    for s in ctx.db.projectile_tick_schedule().iter() {
        ctx.db
            .projectile_tick_schedule()
            .scheduled_id()
            .delete(&s.scheduled_id);
    }
    schedule_next_projectile_tick(ctx);
}

#[spacetimedb::reducer]
pub fn use_targeted_skill(
    ctx: &ReducerContext,
    skill_id: u64,
    target_kind: String,
    target_npc_id: u64,
    target_player_hex: String,
) -> Result<(), String> {
    let player = ctx
        .db
        .player()
        .identity()
        .find(&ctx.sender())
        .ok_or("Player not found")?;
    let skill_def = ctx
        .db
        .skill_def()
        .id()
        .find(&skill_id)
        .ok_or("Skill not found")?;

    let _ = ctx
        .db
        .player_skill()
        .iter()
        .find(|ps| ps.player_identity == ctx.sender() && ps.skill_id == skill_id)
        .ok_or("Skill not available")?;

    let attrs = ctx
        .db
        .skill_attributes()
        .iter()
        .find(|a| a.player_identity == ctx.sender() && a.skill_id == skill_id)
        .ok_or("Skill attributes not found")?;

    let stats = compute_stats(&attrs);

    // Check cooldown
    let now_us = ctx
        .timestamp
        .to_duration_since_unix_epoch()
        .unwrap_or_default()
        .as_micros();
    if let Some(cd) = ctx
        .db
        .skill_cooldown()
        .iter()
        .find(|cd| cd.player_identity == ctx.sender() && cd.skill_id == skill_id)
    {
        let ready_us = cd
            .ready_at
            .to_duration_since_unix_epoch()
            .unwrap_or_default()
            .as_micros();
        if now_us < ready_us {
            return Err("Skill on cooldown".to_string());
        }
    }

    // Check and deduct resource
    match skill_def.resource_type {
        ResourceType::Mana => {
            if player.mana < stats.resource_cost {
                return Err("Not enough mana".to_string());
            }
            ctx.db.player().identity().update(Player {
                mana: player.mana - stats.resource_cost,
                ..player.clone()
            });
        }
        ResourceType::Stamina => {
            if player.stamina < stats.resource_cost {
                return Err("Not enough stamina".to_string());
            }
            ctx.db.player().identity().update(Player {
                stamina: player.stamina - stats.resource_cost,
                ..player.clone()
            });
        }
    }

    // Set cooldown
    let ready_at = ctx.timestamp + Duration::from_millis(stats.cooldown_ms);
    if let Some(cd) = ctx
        .db
        .skill_cooldown()
        .iter()
        .find(|cd| cd.player_identity == ctx.sender() && cd.skill_id == skill_id)
    {
        ctx.db
            .skill_cooldown()
            .id()
            .update(SkillCooldown { ready_at, ..cd });
    } else {
        ctx.db.skill_cooldown().insert(SkillCooldown {
            id: 0,
            player_identity: ctx.sender(),
            skill_id,
            ready_at,
        });
    }

    let targeted_effect = effect_for_skill(&skill_def.name, stats.duration_ms);

    let (target_x, target_y, target_z) = match target_kind.as_str() {
        "self" => {
            let current = ctx
                .db
                .player()
                .identity()
                .find(&ctx.sender())
                .ok_or("Player not found")?;
            let new_health = (player.health + stats.power).min(current.max_health);
            let healed = new_health - current.health;
            ctx.db.player().identity().update(Player {
                health: new_health,
                ..current
            });
            if healed > 0 {
                award_skill_xp(ctx, ctx.sender(), skill_id, healed);
            }
            (player.position.x, player.position.y, player.position.z)
        }
        "npc" => {
            let npc = ctx
                .db
                .npc()
                .id()
                .find(&target_npc_id)
                .ok_or("NPC not found")?;
            if player.position.distance_to(&npc.position) > stats.range {
                return Err("Target out of range".to_string());
            }
            let pos = (npc.position.x, npc.position.y, npc.position.z);
            hit_npc(
                ctx,
                &npc,
                stats.power,
                stats.knockback,
                &player.position,
                ctx.sender(),
                skill_id,
                SKILL_XP_PER_HIT,
                targeted_effect.clone(),
            );
            pos
        }
        "player" => {
            let target_identity = Identity::from_hex(&target_player_hex)
                .map_err(|_| "Invalid player identity".to_string())?;
            let target_player = ctx
                .db
                .player()
                .identity()
                .find(&target_identity)
                .ok_or("Target player not found")?;
            if player.position.distance_to(&target_player.position) > stats.range {
                return Err("Target out of range".to_string());
            }
            let pos = (
                target_player.position.x,
                target_player.position.y,
                target_player.position.z,
            );
            hit_player(
                ctx,
                &target_player,
                stats.power,
                stats.knockback,
                &player.position,
                ctx.sender(),
                skill_id,
                SKILL_XP_PER_HIT,
                targeted_effect.clone(),
            );
            pos
        }
        _ => return Err(format!("Unknown target_kind: {target_kind}")),
    };

    let dx = target_x - player.position.x;
    let dz = target_z - player.position.z;
    let len = (dx * dx + dz * dz).sqrt();
    let (dir_x, dir_z) = if len > 0.001 {
        (dx / len, dz / len)
    } else {
        (0.0, -1.0)
    };

    ctx.db.active_skill().insert(ActiveSkill {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(500)),
        player_identity: ctx.sender(),
        skill_id,
        started_at: now_us as u64,
        target_x,
        target_y,
        target_z,
        dir_x,
        dir_z,
    });

    Ok(())
}

// --- BDI Reducers ---

#[spacetimedb::reducer]
pub fn submit_npc_reflection(
    ctx: &ReducerContext,
    npc_id: u64,
    json: String,
) -> Result<(), String> {
    let npc = ctx.db.npc().id().find(&npc_id).ok_or("NPC not found")?;
    let v: serde_json::Value =
        serde_json::from_str(&json).map_err(|e| format!("Invalid reflection JSON: {e}"))?;
    let now_us = ctx
        .timestamp
        .to_duration_since_unix_epoch()
        .unwrap_or_default()
        .as_micros() as u64;

    // Store memories
    if let Some(memories) = v.get("memories").and_then(|m| m.as_array()) {
        for mem in memories {
            if let Some(text) = mem.as_str() {
                let _ = submit_npc_memory(ctx, npc_id, text.to_string());
            }
        }
    }

    // Upsert goals (capped at MAX_NPC_GOALS)
    if let Some(goals) = v.get("goals").and_then(|g| g.as_array()) {
        let existing_count = ctx
            .db
            .npc_goal()
            .iter()
            .filter(|g| g.npc_id == npc_id)
            .count();
        for (i, goal) in goals.iter().enumerate() {
            if existing_count + i >= MAX_NPC_GOALS {
                break;
            }
            let desc = goal
                .get("description")
                .and_then(|d| d.as_str())
                .unwrap_or("")
                .to_string();
            if desc.is_empty() {
                continue;
            }
            let priority_str = goal
                .get("priority")
                .and_then(|p| p.as_str())
                .unwrap_or("ambition");
            let priority = match priority_str {
                "survival" => GoalPriority::Survival,
                "duty" => GoalPriority::Duty,
                "social" => GoalPriority::Social,
                "leisure" => GoalPriority::Leisure,
                _ => GoalPriority::Ambition,
            };
            let condition = goal
                .get("success_condition")
                .map(|c| serde_json::to_string(c).unwrap_or_default())
                .unwrap_or_default();
            ctx.db.npc_goal().insert(NpcGoal {
                id: 0,
                npc_id,
                parent_goal_id: 0,
                priority,
                status: GoalStatus::Active,
                description: desc,
                success_condition: condition,
                created_at: now_us,
                completed_at: 0,
            });
        }
    }

    // Upsert beliefs (by subject+predicate, capped at MAX_NPC_BELIEFS)
    if let Some(beliefs) = v.get("beliefs").and_then(|b| b.as_array()) {
        for belief in beliefs {
            let subject = belief
                .get("subject")
                .and_then(|s| s.as_str())
                .unwrap_or("")
                .to_string();
            let predicate = belief
                .get("predicate")
                .and_then(|p| p.as_str())
                .unwrap_or("")
                .to_string();
            let object = belief
                .get("object")
                .and_then(|o| o.as_str())
                .unwrap_or("")
                .to_string();
            let confidence = belief
                .get("confidence")
                .and_then(|c| c.as_f64())
                .unwrap_or(0.8) as f32;
            if subject.is_empty() || predicate.is_empty() {
                continue;
            }

            // Find existing belief with same subject+predicate
            let existing =
                ctx.db.npc_belief().iter().find(|b| {
                    b.npc_id == npc_id && b.subject == subject && b.predicate == predicate
                });

            if let Some(existing) = existing {
                ctx.db.npc_belief().id().update(NpcBelief {
                    object,
                    confidence,
                    updated_at: now_us,
                    ..existing
                });
            } else {
                let count = ctx
                    .db
                    .npc_belief()
                    .iter()
                    .filter(|b| b.npc_id == npc_id)
                    .count();
                if count < MAX_NPC_BELIEFS {
                    ctx.db.npc_belief().insert(NpcBelief {
                        id: 0,
                        npc_id,
                        subject,
                        predicate,
                        object,
                        confidence,
                        updated_at: now_us,
                    });
                }
            }
        }
    }

    // Apply relationship deltas
    if let Some(rel_updates) = v.get("relationship_updates").and_then(|r| r.as_array()) {
        for update in rel_updates {
            let target_type = update
                .get("target_type")
                .and_then(|t| t.as_str())
                .unwrap_or("")
                .to_string();
            let target_id = update
                .get("target_id")
                .and_then(|t| t.as_str())
                .unwrap_or("")
                .to_string();
            let delta = update.get("delta").and_then(|d| d.as_i64()).unwrap_or(0) as i32;
            let context = update
                .get("context")
                .and_then(|c| c.as_str())
                .unwrap_or("")
                .to_string();
            if target_type.is_empty() || target_id.is_empty() {
                continue;
            }

            let existing = ctx.db.npc_relationship().iter().find(|r| {
                r.npc_id == npc_id && r.target_type == target_type && r.target_id == target_id
            });

            if let Some(existing) = existing {
                let new_disp = (existing.disposition + delta).clamp(-100, 100);
                ctx.db.npc_relationship().id().update(NpcRelationship {
                    disposition: new_disp,
                    context,
                    updated_at: now_us,
                    ..existing
                });
            } else {
                ctx.db.npc_relationship().insert(NpcRelationship {
                    id: 0,
                    npc_id,
                    target_type,
                    target_id,
                    disposition: delta.clamp(-100, 100),
                    context,
                    updated_at: now_us,
                });
            }
        }
    }

    // Update persona if LLM expanded it
    if let Some(persona) = v.get("persona").and_then(|p| p.as_str()) {
        if !persona.is_empty() {
            ctx.db.npc().id().update(Npc {
                persona: persona.to_string(),
                ..npc
            });
        }
    }

    ctx.db.npc_pending_decision().npc_id().delete(&npc_id);
    log::info!("[NPC {}] reflection processed", npc_id);
    Ok(())
}

#[spacetimedb::reducer]
pub fn submit_npc_goals(
    ctx: &ReducerContext,
    npc_id: u64,
    goals_json: String,
) -> Result<(), String> {
    ctx.db.npc().id().find(&npc_id).ok_or("NPC not found")?;
    let goals: Vec<serde_json::Value> =
        serde_json::from_str(&goals_json).map_err(|e| format!("Invalid goals JSON: {e}"))?;
    let now_us = ctx
        .timestamp
        .to_duration_since_unix_epoch()
        .unwrap_or_default()
        .as_micros() as u64;
    let existing_count = ctx
        .db
        .npc_goal()
        .iter()
        .filter(|g| g.npc_id == npc_id)
        .count();

    for (i, goal) in goals.iter().enumerate() {
        if existing_count + i >= MAX_NPC_GOALS {
            break;
        }
        let desc = goal
            .get("description")
            .and_then(|d| d.as_str())
            .unwrap_or("")
            .to_string();
        if desc.is_empty() {
            continue;
        }
        let priority_str = goal
            .get("priority")
            .and_then(|p| p.as_str())
            .unwrap_or("ambition");
        let priority = match priority_str {
            "survival" => GoalPriority::Survival,
            "duty" => GoalPriority::Duty,
            "social" => GoalPriority::Social,
            "leisure" => GoalPriority::Leisure,
            _ => GoalPriority::Ambition,
        };
        let condition = goal
            .get("success_condition")
            .map(|c| serde_json::to_string(c).unwrap_or_default())
            .unwrap_or_default();
        ctx.db.npc_goal().insert(NpcGoal {
            id: 0,
            npc_id,
            parent_goal_id: 0,
            priority,
            status: GoalStatus::Active,
            description: desc,
            success_condition: condition,
            created_at: now_us,
            completed_at: 0,
        });
    }
    log::info!("[NPC {}] {} goals submitted", npc_id, goals.len());
    Ok(())
}

#[spacetimedb::reducer]
pub fn submit_npc_beliefs(
    ctx: &ReducerContext,
    npc_id: u64,
    beliefs_json: String,
) -> Result<(), String> {
    ctx.db.npc().id().find(&npc_id).ok_or("NPC not found")?;
    let beliefs: Vec<serde_json::Value> =
        serde_json::from_str(&beliefs_json).map_err(|e| format!("Invalid beliefs JSON: {e}"))?;
    let now_us = ctx
        .timestamp
        .to_duration_since_unix_epoch()
        .unwrap_or_default()
        .as_micros() as u64;

    for belief in &beliefs {
        let subject = belief
            .get("subject")
            .and_then(|s| s.as_str())
            .unwrap_or("")
            .to_string();
        let predicate = belief
            .get("predicate")
            .and_then(|p| p.as_str())
            .unwrap_or("")
            .to_string();
        let object = belief
            .get("object")
            .and_then(|o| o.as_str())
            .unwrap_or("")
            .to_string();
        let confidence = belief
            .get("confidence")
            .and_then(|c| c.as_f64())
            .unwrap_or(0.8) as f32;
        if subject.is_empty() || predicate.is_empty() {
            continue;
        }

        let existing = ctx
            .db
            .npc_belief()
            .iter()
            .find(|b| b.npc_id == npc_id && b.subject == subject && b.predicate == predicate);

        if let Some(existing) = existing {
            ctx.db.npc_belief().id().update(NpcBelief {
                object,
                confidence,
                updated_at: now_us,
                ..existing
            });
        } else {
            let count = ctx
                .db
                .npc_belief()
                .iter()
                .filter(|b| b.npc_id == npc_id)
                .count();
            if count < MAX_NPC_BELIEFS {
                ctx.db.npc_belief().insert(NpcBelief {
                    id: 0,
                    npc_id,
                    subject,
                    predicate,
                    object,
                    confidence,
                    updated_at: now_us,
                });
            }
        }
    }
    log::info!("[NPC {}] {} beliefs submitted", npc_id, beliefs.len());
    Ok(())
}

#[spacetimedb::reducer]
pub fn submit_npc_knowledge(
    ctx: &ReducerContext,
    npc_id: u64,
    category: String,
    fact: String,
    learned_from: String,
    confidence: f32,
) -> Result<(), String> {
    ctx.db.npc().id().find(&npc_id).ok_or("NPC not found")?;
    let confidence = confidence.clamp(0.0, 1.0);
    if category.is_empty() || fact.is_empty() {
        return Err("Category and fact must not be empty".to_string());
    }

    // Check for existing knowledge with same category+fact — update if higher confidence
    let existing = ctx.db.npc_knowledge().iter().find(|k| {
        k.npc_id == npc_id && k.category == category && k.fact == fact
    });

    let now_us = ctx.timestamp.to_duration_since_unix_epoch()
        .unwrap_or_default().as_micros() as u64;

    if let Some(existing) = existing {
        if confidence > existing.confidence {
            ctx.db.npc_knowledge().id().update(NpcKnowledge {
                confidence,
                created_at: now_us,
                ..existing
            });
        }
    } else {
        let count = ctx.db.npc_knowledge().iter()
            .filter(|k| k.npc_id == npc_id).count();
        if count < MAX_NPC_KNOWLEDGE {
            ctx.db.npc_knowledge().insert(NpcKnowledge {
                id: 0,
                npc_id,
                category,
                fact,
                learned_from,
                confidence,
                created_at: now_us,
            });
        }
    }
    Ok(())
}
