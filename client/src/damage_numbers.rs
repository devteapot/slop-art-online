use bevy::prelude::*;

use crate::health_bar::Health;
use crate::player::{LocalPlayer, LocalPlayerStats};
use crate::world::MainCamera;

/// Tracks the previous frame's health for change detection on NPCs/remote players.
#[derive(Component)]
pub struct PreviousHealth(pub i32);

/// Tracks the previous frame's health for the local player (uses `LocalPlayerStats` resource).
#[derive(Resource, Default)]
pub struct PreviousLocalHealth(pub i32);

/// A floating damage/healing number. Attached to a UI `Node` entity.
#[derive(Component)]
pub struct DamageNumber {
    pub lifetime: Timer,
    /// World-space origin where the number was spawned.
    pub world_pos: Vec3,
}

/// Attach `PreviousHealth` to any entity that has `Health` but not yet `PreviousHealth`.
pub fn attach_previous_health(
    mut commands: Commands,
    query: Query<(Entity, &Health), Without<PreviousHealth>>,
) {
    for (entity, health) in &query {
        commands.entity(entity).insert(PreviousHealth(health.current));
    }
}

/// Detect health changes on NPCs and remote players, spawn floating numbers.
pub fn detect_damage(
    mut commands: Commands,
    mut query: Query<(&Health, &mut PreviousHealth, &GlobalTransform), Without<LocalPlayer>>,
) {
    for (health, mut prev, gt) in query.iter_mut() {
        let diff = health.current - prev.0;
        if diff != 0 {
            prev.0 = health.current;
            spawn_damage_number(&mut commands, gt.translation(), diff);
        }
    }
}

/// Detect health changes on the local player via `LocalPlayerStats`.
pub fn detect_local_damage(
    mut commands: Commands,
    local_stats: Res<LocalPlayerStats>,
    mut prev: ResMut<PreviousLocalHealth>,
    local_player: Query<&GlobalTransform, With<LocalPlayer>>,
) {
    let diff = local_stats.health - prev.0;
    if diff != 0 {
        prev.0 = local_stats.health;
        if let Ok(gt) = local_player.single() {
            spawn_damage_number(&mut commands, gt.translation(), diff);
        }
    }
}

fn spawn_damage_number(commands: &mut Commands, pos: Vec3, amount: i32) {
    let color = if amount < 0 {
        Color::srgb(1.0, 0.2, 0.2)
    } else {
        Color::srgb(0.2, 1.0, 0.2)
    };

    let display = if amount < 0 {
        format!("{}", amount)
    } else {
        format!("+{}", amount)
    };

    commands.spawn((
        DamageNumber {
            lifetime: Timer::from_seconds(1.0, TimerMode::Once),
            world_pos: Vec3::new(pos.x, pos.y + 2.2, pos.z),
        },
        Text::new(display),
        TextFont {
            font_size: 24.0,
            ..default()
        },
        TextColor(color),
        TextLayout::new_with_justify(Justify::Center),
        Node {
            position_type: PositionType::Absolute,
            ..default()
        },
    ));
}

/// Project damage numbers to screen space, float upward, fade, and despawn when expired.
pub fn animate_damage_numbers(
    mut commands: Commands,
    time: Res<Time>,
    camera: Query<(&Camera, &GlobalTransform), With<MainCamera>>,
    mut query: Query<(Entity, &mut DamageNumber, &mut Node, &mut TextColor)>,
) {
    let Ok((cam, cam_gt)) = camera.single() else { return };

    for (entity, mut dmg, mut node, mut text_color) in query.iter_mut() {
        dmg.lifetime.tick(time.delta());
        let frac = dmg.lifetime.fraction();

        // Float upward in world space
        let world = dmg.world_pos + Vec3::Y * frac * 1.5;

        // Project to screen
        if let Ok(ndc) = cam.world_to_viewport(cam_gt, world) {
            node.left = Val::Px(ndc.x - 30.0);
            node.top = Val::Px(ndc.y - 12.0);
        }

        // Fade out
        let alpha = 1.0 - frac;
        text_color.0 = text_color.0.with_alpha(alpha);

        if frac >= 1.0 {
            commands.entity(entity).despawn();
        }
    }
}
