use bevy::prelude::*;

use crate::health_bar::{spawn_health_bar, Health, HealthBarFillRef};
use crate::network::{to_world_pos, NpcEvent, NpcEventQueue};

#[derive(Component)]
pub struct NpcId(pub u64);

pub fn sync_npcs(
    mut commands: Commands,
    queue: Res<NpcEventQueue>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    mut npcs: Query<(Entity, &NpcId, &mut Transform, &mut Health)>,
) {
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            NpcEvent::Inserted(npc) => {
                let (bar_root, fill_id) = spawn_health_bar(&mut commands, &mut meshes, &mut materials);
                let mut entity_cmd = commands.spawn((
                    NpcId(npc.id),
                    Mesh3d(meshes.add(Capsule3d::new(0.4, 1.0))),
                    MeshMaterial3d(materials.add(StandardMaterial {
                        base_color: Color::srgb(1.0, 0.5, 0.2),
                        ..default()
                    })),
                    Transform::from_translation(to_world_pos(&npc.position)),
                    Health(npc.health),
                    HealthBarFillRef(fill_id),
                ));
                entity_cmd.add_child(bar_root);
            }
            NpcEvent::Updated(npc) => {
                for (_, id, mut transform, mut health) in npcs.iter_mut() {
                    if id.0 == npc.id {
                        transform.translation = to_world_pos(&npc.position);
                        health.0 = npc.health;
                    }
                }
            }
            NpcEvent::Deleted(npc) => {
                for (entity, id, _, _) in npcs.iter() {
                    if id.0 == npc.id {
                        commands.entity(entity).despawn();
                    }
                }
            }
        }
    }
}
