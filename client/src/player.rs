use bevy::prelude::*;
use spacetimedb_sdk::Identity;

use shared::module_bindings::attack_npc_reducer::attack_npc;
use shared::module_bindings::attack_player_reducer::attack_player;
use shared::module_bindings::move_player_reducer::move_player;

use crate::constants::{ATTACK_RANGE, MAX_LOOK_AHEAD, MOVE_SPEED, PLAYER_Y};
use crate::network::{LocalIdentity, PlayerEvent, PlayerEventQueue, SpacetimeDb, to_world_pos};
use crate::npc::NpcId;
use crate::world::MainCamera;

#[derive(Component)]
pub struct PlayerId(pub Identity);

#[derive(Component)]
pub struct LocalPlayer;

#[derive(Resource)]
pub struct LocalPlayerStats {
    pub health: i32,
    pub max_health: i32,
    pub mana: i32,
    pub max_mana: i32,
    pub stamina: i32,
    pub max_stamina: i32,
}

impl Default for LocalPlayerStats {
    fn default() -> Self {
        Self {
            health: 0,
            max_health: 100,
            mana: 0,
            max_mana: 100,
            stamina: 0,
            max_stamina: 100,
        }
    }
}

/// XZ facing direction from last movement input, used for dash direction.
#[derive(Resource, Default)]
pub struct PlayerFacing(pub Vec2);

pub fn sync_players(
    mut commands: Commands,
    queue: Res<PlayerEventQueue>,
    local_identity: Res<LocalIdentity>,
    asset_server: Res<AssetServer>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    mut players: Query<(Entity, &PlayerId, &mut Transform)>,
    mut local_stats: ResMut<LocalPlayerStats>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            PlayerEvent::Inserted(player) => {
                let is_local = local_id.as_ref() == Some(&player.identity);
                if is_local {
                    local_stats.health = player.health;
                    local_stats.max_health = 100;
                    local_stats.mana = player.mana;
                    local_stats.max_mana = player.max_mana;
                    local_stats.stamina = player.stamina;
                    local_stats.max_stamina = player.max_stamina;
                }

                let transform = Transform::from_translation(to_world_pos(&player.position));

                let entity_cmd = if is_local {
                    commands.spawn((
                        PlayerId(player.identity),
                        LocalPlayer,
                        SceneRoot(asset_server.load("test.glb#Scene0")),
                        transform,
                    ))
                } else {
                    commands.spawn((
                        PlayerId(player.identity),
                        Mesh3d(meshes.add(Capsule3d::new(0.4, 1.0))),
                        MeshMaterial3d(materials.add(StandardMaterial {
                            base_color: Color::WHITE,
                            ..default()
                        })),
                        transform,
                    ))
                };
                let _ = entity_cmd;
            }
            PlayerEvent::Updated(player) => {
                for (_, id, mut transform) in players.iter_mut() {
                    if id.0 == player.identity {
                        transform.translation = to_world_pos(&player.position);
                    }
                }
                if local_id.as_ref() == Some(&player.identity) {
                    local_stats.health = player.health;
                    local_stats.mana = player.mana;
                    local_stats.stamina = player.stamina;
                }
            }
            PlayerEvent::Deleted(player) => {
                for (entity, id, _) in players.iter() {
                    if id.0 == player.identity {
                        commands.entity(entity).despawn();
                    }
                }
            }
        }
    }
}

pub fn move_local_player(
    conn: Option<Res<SpacetimeDb>>,
    keys: Res<ButtonInput<KeyCode>>,
    time: Res<Time>,
    player: Query<&Transform, With<LocalPlayer>>,
    mut facing: ResMut<PlayerFacing>,
) {
    let Some(conn) = conn else { return };
    let Ok(transform) = player.single() else {
        return;
    };

    let mut dir = Vec2::ZERO;
    if keys.pressed(KeyCode::KeyW) || keys.pressed(KeyCode::ArrowUp) {
        dir.y -= 1.0;
    }
    if keys.pressed(KeyCode::KeyS) || keys.pressed(KeyCode::ArrowDown) {
        dir.y += 1.0;
    }
    if keys.pressed(KeyCode::KeyA) || keys.pressed(KeyCode::ArrowLeft) {
        dir.x -= 1.0;
    }
    if keys.pressed(KeyCode::KeyD) || keys.pressed(KeyCode::ArrowRight) {
        dir.x += 1.0;
    }

    if dir == Vec2::ZERO {
        return;
    }

    let dir_norm = dir.normalize();
    facing.0 = dir_norm;

    let delta = dir_norm * MOVE_SPEED * time.delta_secs();
    let new_x = transform.translation.x + delta.x;
    let new_z = transform.translation.z + delta.y;

    if let Err(e) = conn.0.reducers.move_player(new_x, PLAYER_Y, new_z) {
        error!("move_player failed: {e}");
    }
}

pub fn follow_camera(
    windows: Query<&Window>,
    local_player: Query<&Transform, With<LocalPlayer>>,
    mut camera: Query<&mut Transform, (With<MainCamera>, Without<LocalPlayer>)>,
) {
    let Ok(player) = local_player.single() else {
        return;
    };
    let Ok(ref mut cam) = camera.single_mut() else {
        return;
    };
    let Ok(window) = windows.single() else { return };

    // Offset camera based on cursor distance from window center.
    // Cursor at center = no offset; cursor at edge = MAX_LOOK_AHEAD offset.
    let look_ahead = if let Some(cursor) = window.cursor_position() {
        let half = Vec2::new(window.width(), window.height()) * 0.5;
        let norm = ((cursor - half) / half).clamp(Vec2::splat(-1.0), Vec2::splat(1.0));
        // Screen X → world X, screen Y (down=positive) → world Z
        Vec3::new(norm.x * MAX_LOOK_AHEAD, 0.0, norm.y * MAX_LOOK_AHEAD)
    } else {
        Vec3::ZERO
    };

    // Shift camera position only — rotation stays fixed from setup, preserving the constant angle
    let target = player.translation + Vec3::new(0.0, 30.0, 40.0) + look_ahead;
    cam.translation = cam.translation.lerp(target, 0.1);
}

pub fn face_cursor(
    windows: Query<&Window>,
    camera: Query<(&Camera, &GlobalTransform), With<MainCamera>>,
    mut player: Query<&mut Transform, With<LocalPlayer>>,
) {
    let Ok(window) = windows.single() else { return };
    let Ok((cam, cam_transform)) = camera.single() else { return };
    let Ok(mut player_transform) = player.single_mut() else { return };
    let Some(cursor) = window.cursor_position() else { return };

    let Ok(ray) = cam.viewport_to_world(cam_transform, cursor) else { return };

    // Intersect ray with the Y = PLAYER_Y plane
    let plane_y = player_transform.translation.y;
    let denom = ray.direction.y;
    if denom.abs() < 1e-5 {
        return;
    }
    let t = (plane_y - ray.origin.y) / denom;
    if t < 0.0 {
        return;
    }
    let world_pos = ray.origin + ray.direction * t;

    let diff = world_pos - player_transform.translation;
    if diff.xz().length_squared() < 0.01 {
        return;
    }

    player_transform.rotation = Quat::from_rotation_y((-diff.x).atan2(-diff.z));
}

pub fn attack(
    conn: Option<Res<SpacetimeDb>>,
    keys: Res<ButtonInput<KeyCode>>,
    local_player: Query<(&Transform, &PlayerId), With<LocalPlayer>>,
    players: Query<(&Transform, &PlayerId), Without<LocalPlayer>>,
    npcs: Query<(&Transform, &NpcId)>,
) {
    if !keys.just_pressed(KeyCode::KeyE) {
        return;
    }
    let Some(conn) = conn else { return };
    let Ok((local_transform, _)) = local_player.single() else {
        return;
    };

    let local_pos = local_transform.translation;

    let nearest_player = players
        .iter()
        .map(|(t, id)| (t.translation.distance(local_pos), id.0))
        .filter(|(dist, _)| *dist <= ATTACK_RANGE)
        .min_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

    let nearest_npc = npcs
        .iter()
        .map(|(t, id)| (t.translation.distance(local_pos), id.0))
        .filter(|(dist, _)| *dist <= ATTACK_RANGE)
        .min_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

    match (nearest_player, nearest_npc) {
        (Some((pd, pid)), Some((nd, nid))) => {
            if pd <= nd {
                let _ = conn.0.reducers.attack_player(pid);
            } else {
                let _ = conn.0.reducers.attack_npc(nid);
            }
        }
        (Some((_, pid)), None) => {
            let _ = conn.0.reducers.attack_player(pid);
        }
        (None, Some((_, nid))) => {
            let _ = conn.0.reducers.attack_npc(nid);
        }
        (None, None) => {}
    }
}
