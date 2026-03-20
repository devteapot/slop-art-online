use bevy::prelude::*;

use crate::health_bar::{spawn_health_bar, Health, HealthBarFillRef};
use crate::interpolation::InterpolationBuffer;
use crate::nameplate::NpcInfo;
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
                let npc_color = match npc.role.as_str() {
                    "hostile" | "hostile_defensive" => Color::srgb(1.0, 0.3, 0.2),
                    "trader" => Color::srgb(0.2, 0.8, 0.3),
                    "guard" => Color::srgb(0.3, 0.5, 1.0),
                    "historian" => Color::srgb(0.8, 0.6, 1.0),
                    "healer" => Color::srgb(1.0, 1.0, 0.4),
                    "adventurer" => Color::srgb(1.0, 0.7, 0.2),
                    "traveller" => Color::srgb(0.6, 0.9, 0.9),
                    _ => Color::srgb(1.0, 0.5, 0.2),
                };
                let mut entity_cmd = commands.spawn((
                    NpcId(npc.id),
                    NpcInfo { name: npc.name.clone(), level: npc.level },
                    Mesh3d(meshes.add(Capsule3d::new(0.4, 1.0))),
                    MeshMaterial3d(materials.add(StandardMaterial {
                        base_color: npc_color,
                        ..default()
                    })),
                    Transform::from_translation(pos),
                    Health { current: npc.health, max: npc.max_health },
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
                        health.current = npc.health;
                        health.max = npc.max_health;
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
