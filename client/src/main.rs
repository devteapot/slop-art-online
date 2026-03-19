mod constants;
mod network;
mod world;
mod health_bar;
mod player;
mod npc;
mod skills;
mod hud;

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
        .add_systems(Startup, (setup, connect_spacetimedb, setup_hud))
        .add_systems(Update, (
            tick_spacetimedb,
            sync_players,
            sync_npcs,
            sync_player_skills,
            sync_skill_defs,
            sync_skill_attrs,
            sync_skill_cooldowns,
            move_local_player,
            update_grounded,
            use_skill_input,
            mobility_input,
            apply_dash,
            follow_camera,
            face_cursor,
            attack,
            update_health_bars,
            billboard_health_bars,
            update_hud,
            handle_skill_slot_clicks,
            handle_allocate_clicks,
        ).chain())
        .add_systems(Update, (
            add_chunk_colliders,
            handle_close_click,
            update_skill_detail_panel,
            apply_remote_player_facing,
            setup_player_animations,
            drive_player_animations,
        ))
        .run();
}
