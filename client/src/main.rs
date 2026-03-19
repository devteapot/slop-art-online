mod constants;
mod network;
mod world;
mod health_bar;
mod player;
mod npc;
mod skills;
mod hud;
mod interpolation;
mod projectile;
mod inventory;
mod chat;
mod status_effects;
mod damage_numbers;

use avian3d::prelude::*;
use bevy::dev_tools::fps_overlay::{FpsOverlayConfig, FpsOverlayPlugin};
use bevy::prelude::*;
use bevy_voxel_world::prelude::*;

use network::*;
use world::*;
use health_bar::*;
use player::*;
use npc::*;
use skills::*;
use hud::*;
use interpolation::*;
use projectile::*;
use inventory::*;
use chat::*;
use status_effects::*;
use damage_numbers::*;

fn main() {
    App::new()
        .add_plugins(DefaultPlugins)
        .add_plugins(FpsOverlayPlugin {
            config: FpsOverlayConfig {
                text_config: TextFont { font_size: 14.0, ..default() },
                ..default()
            },
        })
        .add_plugins(PhysicsPlugins::default())
        .add_plugins(VoxelWorldPlugin::with_config(GameWorld))
        .init_resource::<PlayerEventQueue>()
        .init_resource::<NpcEventQueue>()
        .init_resource::<PlayerSkillEventQueue>()
        .init_resource::<SkillDefEventQueue>()
        .init_resource::<SkillAttributesEventQueue>()
        .init_resource::<SkillCooldownEventQueue>()
        .init_resource::<ActiveSkillEventQueue>()
        .init_resource::<LocalSkills>()
        .init_resource::<LocalPlayerStats>()
        .init_resource::<LocalSkillData>()
        .init_resource::<LocalCooldowns>()
        .init_resource::<SelectedSkill>()
        .init_resource::<SkillNameMap>()
        .init_resource::<MobilitySkillIds>()
        .init_resource::<PlayerFacing>()
        .init_resource::<LastSentFacingAngle>()
        .init_resource::<DashState>()
        .init_resource::<LocalIdentity>()
        .init_resource::<MoveThrottle>()
        .init_resource::<MoveSequence>()
        .init_resource::<PredictionBuffer>()
        .init_resource::<PredictionCorrection>()
        .init_resource::<AbilityAnimTriggerQueue>()
        .init_resource::<CursorGroundPos>()
        .init_resource::<ProjectileEventQueue>()
        .init_resource::<AoeZoneEventQueue>()
        .init_resource::<ItemDefEventQueue>()
        .init_resource::<GroundItemEventQueue>()
        .init_resource::<InventoryItemEventQueue>()
        .init_resource::<ItemDefMap>()
        .init_resource::<ItemRarityMap>()
        .init_resource::<LocalInventory>()
        .init_resource::<InventoryOpen>()
        .init_resource::<EquipmentDefMap>()
        .init_resource::<LocalEquipment>()
        .init_resource::<ItemTypeMap>()
        .init_resource::<ConsumableDefMap>()
        .init_resource::<ExtraEventQueues>()
        .init_resource::<ChatInputActive>()
        .init_resource::<ChatInputBuffer>()
        .init_resource::<LocalStatusEffects>()
        .init_resource::<PreviousLocalHealth>()
        .add_systems(Startup, (setup, connect_spacetimedb, setup_hud, setup_inventory_panel, setup_chat_panel))
        .add_systems(FixedUpdate, (
            move_local_player,
            update_grounded,
            mobility_input,
            apply_dash,
        ).chain())
        .add_systems(Update, (
            tick_spacetimedb,
            sync_players,
            sync_npcs,
            interpolate_remote_entities,
            sync_player_skills,
            sync_skill_defs,
            sync_skill_attrs,
            sync_skill_cooldowns,
            sync_active_skills,
            trigger_ability_animations,
            use_skill_input,
            follow_camera,
            face_cursor,
            update_health_bars,
            billboard_health_bars,
            update_hud,
            handle_skill_slot_clicks,
            handle_allocate_clicks,
        ).chain())
        .add_systems(Update, (
            sync_item_defs,
            sync_inventory,
            sync_equipment_defs,
            sync_equipped_items,
            sync_consumable_defs,
            sync_ground_items,
            toggle_inventory,
            pickup_nearest_item,
            animate_ground_items,
            update_inventory_panel,
            handle_inventory_close,
            handle_inventory_slot_click,
            handle_equipment_slot_click,
        ))
        .add_systems(Update, (
            add_chunk_colliders,
            handle_close_click,
            update_skill_detail_panel,
            apply_remote_player_facing,
            setup_player_animations,
            expire_ability_animations,
            drive_player_animations,
            smooth_prediction_correction,
            sync_projectiles,
            move_projectiles,
            sync_aoe_zones,
            use_targeted_skill_input,
        ))
        .add_systems(Update, (
            sync_chat_messages,
            chat_input,
            update_chat_panel,
        ))
        .add_systems(Update, (
            sync_status_effects,
            update_status_effects_hud,
        ))
        .add_systems(Update, (
            attach_previous_health,
            detect_damage,
            detect_local_damage,
            animate_damage_numbers,
        ))
        .run();
}
