use bevy::prelude::*;

use crate::constants::{HEALTH_BAR_HEIGHT, HEALTH_BAR_WIDTH, HEALTH_BAR_Y_OFFSET};
use crate::world::MainCamera;

#[derive(Component)]
pub struct Health {
    pub current: i32,
    pub max: i32,
}

/// Marker on the fill mesh entity of a health bar.
#[derive(Component)]
pub struct HealthBarFill;

/// Marker on the root entity of a health bar (the billboard container).
#[derive(Component)]
pub struct HealthBarRoot;

/// Stored on character entities; points to their fill mesh entity.
#[derive(Component)]
pub struct HealthBarFillRef(pub Entity);

pub fn spawn_health_bar(
    commands: &mut Commands,
    meshes: &mut Assets<Mesh>,
    materials: &mut Assets<StandardMaterial>,
) -> (Entity, Entity) {
    let fill_mat = materials.add(StandardMaterial {
        base_color: Color::srgb(0.1, 0.85, 0.1),
        unlit: true,
        ..default()
    });
    let bg_mat = materials.add(StandardMaterial {
        base_color: Color::srgb(0.15, 0.15, 0.15),
        unlit: true,
        ..default()
    });

    let fill_id = commands.spawn((
        HealthBarFill,
        Mesh3d(meshes.add(Rectangle::new(HEALTH_BAR_WIDTH, HEALTH_BAR_HEIGHT))),
        MeshMaterial3d(fill_mat),
        Transform::default(),
    )).id();

    let bg_id = commands.spawn((
        Mesh3d(meshes.add(Rectangle::new(HEALTH_BAR_WIDTH, HEALTH_BAR_HEIGHT))),
        MeshMaterial3d(bg_mat),
        Transform::from_xyz(0.0, 0.0, -0.001),
    )).id();

    let root_id = commands.spawn((
        HealthBarRoot,
        Transform::from_xyz(0.0, HEALTH_BAR_Y_OFFSET, 0.0),
        Visibility::default(),
    )).add_children(&[bg_id, fill_id]).id();

    (root_id, fill_id)
}

pub fn update_health_bars(
    characters: Query<(&Health, &HealthBarFillRef)>,
    mut fills: Query<&mut Transform, With<HealthBarFill>>,
) {
    for (health, fill_ref) in &characters {
        if let Ok(mut transform) = fills.get_mut(fill_ref.0) {
            let ratio = (health.current as f32 / health.max.max(1) as f32).clamp(0.0, 1.0);
            transform.scale.x = ratio;
            transform.translation.x = -HEALTH_BAR_WIDTH * (1.0 - ratio) / 2.0;
        }
    }
}

pub fn billboard_health_bars(
    camera: Query<&GlobalTransform, With<MainCamera>>,
    mut bars: Query<&mut Transform, With<HealthBarRoot>>,
) {
    let Ok(cam_gt) = camera.single() else { return };
    let (_, cam_rot, _) = cam_gt.to_scale_rotation_translation();

    for mut bar_lt in &mut bars {
        bar_lt.rotation = cam_rot;
    }
}
