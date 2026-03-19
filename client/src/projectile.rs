use bevy::prelude::*;
use spacetimedb_sdk::Timestamp;

use crate::network::{AoeZoneEvent, AoeZoneEventQueue, ProjectileEvent, ProjectileEventQueue};

/// Visual marker for a server-tracked projectile.
#[derive(Component)]
pub struct ProjectileVisual {
    pub scheduled_id: u64,
    pub start: Vec3,
    pub dir: Vec3,
    pub speed: f32,
    pub started_at: u64,
}

/// Visual marker for a server-tracked AoE zone.
#[derive(Component)]
pub struct AoeZoneVisual {
    pub scheduled_id: u64,
}

pub fn sync_projectiles(
    mut commands: Commands,
    queue: Res<ProjectileEventQueue>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    visuals: Query<(Entity, &ProjectileVisual)>,
) {
    let mut events = queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            ProjectileEvent::Inserted(proj) => {
                let start = Vec3::new(proj.start_x, proj.start_y, proj.start_z);
                let dir = Vec3::new(proj.dir_x, 0.0, proj.dir_z);

                // Extrapolate to current position
                let now_ms = Timestamp::now().to_micros_since_unix_epoch() as u64 / 1000;
                let elapsed_s = now_ms.saturating_sub(proj.started_at) as f32 / 1000.0;
                let current_pos = start + dir * proj.speed * elapsed_s;

                commands.spawn((
                    Mesh3d(meshes.add(Sphere::new(0.3))),
                    MeshMaterial3d(materials.add(StandardMaterial {
                        base_color: Color::srgb(1.0, 0.4, 0.0),
                        emissive: LinearRgba::new(5.0, 2.0, 0.0, 1.0),
                        ..default()
                    })),
                    Transform::from_translation(current_pos),
                    ProjectileVisual {
                        scheduled_id: proj.scheduled_id,
                        start,
                        dir,
                        speed: proj.speed,
                        started_at: proj.started_at,
                    },
                ));
            }
            ProjectileEvent::Deleted(proj) => {
                for (entity, visual) in visuals.iter() {
                    if visual.scheduled_id == proj.scheduled_id {
                        commands.entity(entity).despawn();
                    }
                }
            }
        }
    }
}

pub fn move_projectiles(mut query: Query<(&mut Transform, &ProjectileVisual)>) {
    let now_ms = Timestamp::now().to_micros_since_unix_epoch() as u64 / 1000;
    for (mut transform, visual) in query.iter_mut() {
        let elapsed_s = now_ms.saturating_sub(visual.started_at) as f32 / 1000.0;
        transform.translation = visual.start + visual.dir * visual.speed * elapsed_s;
    }
}

pub fn sync_aoe_zones(
    mut commands: Commands,
    queue: Res<AoeZoneEventQueue>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    visuals: Query<(Entity, &AoeZoneVisual)>,
) {
    let mut events = queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            AoeZoneEvent::Inserted(zone) => {
                // Flat circle on the ground
                commands.spawn((
                    Mesh3d(meshes.add(Circle::new(zone.radius))),
                    MeshMaterial3d(materials.add(StandardMaterial {
                        base_color: Color::srgba(1.0, 0.2, 0.0, 0.3),
                        emissive: LinearRgba::new(2.0, 0.3, 0.0, 1.0),
                        alpha_mode: AlphaMode::Blend,
                        double_sided: true,
                        cull_mode: None,
                        ..default()
                    })),
                    Transform::from_xyz(zone.center_x, 0.1, zone.center_z)
                        .with_rotation(Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2)),
                    AoeZoneVisual {
                        scheduled_id: zone.scheduled_id,
                    },
                ));
            }
            AoeZoneEvent::Deleted(zone) => {
                for (entity, visual) in visuals.iter() {
                    if visual.scheduled_id == zone.scheduled_id {
                        commands.entity(entity).despawn();
                    }
                }
            }
        }
    }
}
