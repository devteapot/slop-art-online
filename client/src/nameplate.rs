use bevy::prelude::*;

use crate::constants::HEALTH_BAR_Y_OFFSET;
use crate::npc::NpcId;
use crate::world::MainCamera;

/// Stored on the NPC entity; holds display info.
#[derive(Component)]
pub struct NpcInfo {
    pub name: String,
    pub level: i32,
}

/// Stored on the NPC entity; points to the UI nameplate entity.
#[derive(Component)]
#[allow(dead_code)]
pub struct NpcNameplateRef(pub Entity);

/// Marker on the UI nameplate node.
#[derive(Component)]
pub struct NpcNameplate {
    pub npc_entity: Entity,
}

/// Spawn a screen-space nameplate UI node for any NPC that has `NpcInfo` but no `NpcNameplateRef`.
pub fn spawn_nameplates(
    mut commands: Commands,
    npcs: Query<(Entity, &NpcInfo), (With<NpcId>, Without<NpcNameplateRef>)>,
) {
    for (entity, info) in &npcs {
        let label = format!("{} [Lv{}]", info.name, info.level);
        let ui_entity = commands.spawn((
            NpcNameplate { npc_entity: entity },
            Text::new(label),
            TextFont {
                font_size: 14.0,
                ..default()
            },
            TextColor(Color::WHITE),
            TextLayout::new_with_justify(Justify::Center),
            Node {
                position_type: PositionType::Absolute,
                ..default()
            },
        )).id();
        commands.entity(entity).insert(NpcNameplateRef(ui_entity));
    }
}

/// Project nameplates to screen space above the health bar.
pub fn update_nameplates(
    mut commands: Commands,
    camera: Query<(&Camera, &GlobalTransform), With<MainCamera>>,
    npcs: Query<(&GlobalTransform, &NpcNameplateRef)>,
    mut nameplates: Query<(Entity, &NpcNameplate, &mut Node, &mut Visibility)>,
) {
    let Ok((cam, cam_gt)) = camera.single() else { return };

    for (entity, nameplate, mut node, mut vis) in nameplates.iter_mut() {
        let Ok((npc_gt, _)) = npcs.get(nameplate.npc_entity) else {
            // NPC despawned — clean up nameplate
            commands.entity(entity).despawn();
            continue;
        };

        // Position text above the health bar (health bar is at HEALTH_BAR_Y_OFFSET)
        let world_pos = npc_gt.translation() + Vec3::Y * (HEALTH_BAR_Y_OFFSET + 0.15);

        if let Ok(vp) = cam.world_to_viewport(cam_gt, world_pos) {
            node.left = Val::Px(vp.x - 60.0);
            node.top = Val::Px(vp.y - 16.0);
            *vis = Visibility::Inherited;
        } else {
            *vis = Visibility::Hidden;
        }
    }
}

/// Clean up nameplate UI entities when NPC entities are despawned.
pub fn cleanup_nameplates(
    mut commands: Commands,
    nameplates: Query<(Entity, &NpcNameplate)>,
    npcs: Query<&NpcId>,
) {
    for (entity, nameplate) in &nameplates {
        if npcs.get(nameplate.npc_entity).is_err() {
            commands.entity(entity).despawn();
        }
    }
}
