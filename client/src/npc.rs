use bevy::prelude::*;

use crate::health_bar::{spawn_health_bar, Health, HealthBarFillRef};
use crate::interpolation::InterpolationBuffer;
use crate::network::{to_world_pos, NpcEvent, NpcEventQueue};

#[derive(Component)]
pub struct NpcId(pub u64);

pub fn sync_npcs(
    mut commands: Commands,
    queue: Res<NpcEventQueue>,
    time: Res<Time>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    mut npcs: Query<(Entity, &NpcId, &mut Health, Option<&mut InterpolationBuffer>)>,
) {
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            NpcEvent::Inserted(npc) => {
                let pos = to_world_pos(&npc.position);
                let mut buffer = InterpolationBuffer::default();
                buffer.push(pos, 0.0, time.elapsed_secs_f64());
                let (bar_root, fill_id) = spawn_health_bar(&mut commands, &mut meshes, &mut materials);
                let mut entity_cmd = commands.spawn((
                    NpcId(npc.id),
                    Mesh3d(meshes.add(Capsule3d::new(0.4, 1.0))),
                    MeshMaterial3d(materials.add(StandardMaterial {
                        base_color: Color::srgb(1.0, 0.5, 0.2),
                        ..default()
                    })),
                    Transform::from_translation(pos),
                    Health(npc.health),
                    HealthBarFillRef(fill_id),
                    buffer,
                ));
                entity_cmd.add_child(bar_root);
            }
            NpcEvent::Updated(npc) => {
                let now = time.elapsed_secs_f64();
                for (_, id, mut health, interp_buffer) in npcs.iter_mut() {
                    if id.0 == npc.id {
                        if let Some(mut buffer) = interp_buffer {
                            buffer.push(to_world_pos(&npc.position), 0.0, now);
                        }
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
