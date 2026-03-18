use avian3d::prelude::*;
use bevy::prelude::*;
use spacetimedb_sdk::Identity;

use shared::module_bindings::attack_npc_reducer::attack_npc;
use shared::module_bindings::attack_player_reducer::attack_player;
use shared::module_bindings::move_player_reducer::move_player;

use crate::constants::{
    ATTACK_RANGE, CAPSULE_HALF_LEN, CAPSULE_RADIUS, MAX_LOOK_AHEAD, MOVE_SPEED, PLAYER_GRAVITY_SCALE,
};
use crate::network::{LocalIdentity, PlayerEvent, PlayerEventQueue, SpacetimeDb, to_world_pos};
use crate::npc::NpcId;
use crate::world::MainCamera;

#[derive(Component)]
pub struct PlayerId(pub Identity);

#[derive(Component)]
pub struct LocalPlayer;

/// Marks the child entity that holds the visible model for the local player.
/// avian3d does not control this entity, so we can freely rotate it for cursor facing.
#[derive(Component)]
pub struct PlayerVisual;

/// Whether the local player is currently on the ground.
#[derive(Component, Default)]
pub struct Grounded(pub bool);

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

                let server_pos = to_world_pos(&player.position);

                if is_local {
                    // Spawn physics body at capsule-center height above the ground.
                    // The visible model is a child entity offset downward so its feet
                    // align with the bottom of the capsule.
                    let spawn_y = 50.0;
                    let body = commands.spawn((
                        PlayerId(player.identity),
                        LocalPlayer,
                        Transform::from_xyz(server_pos.x, spawn_y, server_pos.z),
                        Visibility::default(),
                        RigidBody::Dynamic,
                        Collider::capsule(CAPSULE_HALF_LEN, CAPSULE_RADIUS),
                        LockedAxes::ROTATION_LOCKED,
                        LinearVelocity::default(),
                        GravityScale(PLAYER_GRAVITY_SCALE),
                        Grounded::default(),
                    )).id();

                    let model_offset_y = -(CAPSULE_HALF_LEN + CAPSULE_RADIUS);
                    commands.entity(body).with_child((
                        PlayerVisual,
                        SceneRoot(asset_server.load("test.glb#Scene0")),
                        Transform::from_xyz(0.0, model_offset_y, 0.0),
                    ));
                } else {
                    commands.spawn((
                        PlayerId(player.identity),
                        Mesh3d(meshes.add(Capsule3d::new(0.4, 1.0))),
                        MeshMaterial3d(materials.add(StandardMaterial {
                            base_color: Color::WHITE,
                            ..default()
                        })),
                        Transform::from_translation(server_pos),
                    ));
                }
            }
            PlayerEvent::Updated(player) => {
                let is_local = local_id.as_ref() == Some(&player.identity);
                // Physics owns the local player's position — only update remote players.
                if !is_local {
                    for (_, id, mut transform) in players.iter_mut() {
                        if id.0 == player.identity {
                            transform.translation = to_world_pos(&player.position);
                        }
                    }
                }
                if is_local {
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
    mut player: Query<(&Transform, &mut LinearVelocity), With<LocalPlayer>>,
    mut facing: ResMut<PlayerFacing>,
) {
    let Some(conn) = conn else { return };
    let Ok((transform, mut velocity)) = player.single_mut() else { return };

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

    if dir != Vec2::ZERO {
        let dir_norm = dir.normalize();
        facing.0 = dir_norm;
        velocity.x = dir_norm.x * MOVE_SPEED;
        velocity.z = dir_norm.y * MOVE_SPEED;

        let pos = transform.translation;
        if let Err(e) = conn.0.reducers.move_player(pos.x, pos.y, pos.z) {
            error!("move_player failed: {e}");
        }
    } else {
        velocity.x = 0.0;
        velocity.z = 0.0;
    }
}

/// Update `Grounded` based on vertical velocity: near-zero Y means on the ground.
pub fn update_grounded(
    mut query: Query<(&LinearVelocity, &mut Grounded), With<LocalPlayer>>,
) {
    for (velocity, mut grounded) in query.iter_mut() {
        // Positive Y = jumping, large negative Y = falling.
        // Small Y (landing or resting) = grounded.
        grounded.0 = velocity.y < 1.0 && velocity.y > -4.0;
    }
}

pub fn follow_camera(
    windows: Query<&Window>,
    local_player: Query<&Transform, With<LocalPlayer>>,
    mut camera: Query<&mut Transform, (With<MainCamera>, Without<LocalPlayer>)>,
) {
    let Ok(player) = local_player.single() else { return };
    let Ok(ref mut cam) = camera.single_mut() else { return };
    let Ok(window) = windows.single() else { return };

    let look_ahead = if let Some(cursor) = window.cursor_position() {
        let half = Vec2::new(window.width(), window.height()) * 0.5;
        let norm = ((cursor - half) / half).clamp(Vec2::splat(-1.0), Vec2::splat(1.0));
        Vec3::new(norm.x * MAX_LOOK_AHEAD, 0.0, norm.y * MAX_LOOK_AHEAD)
    } else {
        Vec3::ZERO
    };

    let target = player.translation + Vec3::new(0.0, 30.0, 40.0) + look_ahead;
    cam.translation = cam.translation.lerp(target, 0.1);
}

/// Rotate the player's visual model to face the cursor.
/// Targets the `PlayerVisual` child so avian3d's locked-rotation body is unaffected.
pub fn face_cursor(
    windows: Query<&Window>,
    camera: Query<(&Camera, &GlobalTransform), With<MainCamera>>,
    local_player: Query<&GlobalTransform, With<LocalPlayer>>,
    mut visual: Query<&mut Transform, With<PlayerVisual>>,
) {
    let Ok(window) = windows.single() else { return };
    let Ok((cam, cam_transform)) = camera.single() else { return };
    let Ok(player_gtransform) = local_player.single() else { return };
    let Ok(mut visual_transform) = visual.single_mut() else { return };
    let Some(cursor) = window.cursor_position() else { return };

    let Ok(ray) = cam.viewport_to_world(cam_transform, cursor) else { return };

    let plane_y = player_gtransform.translation().y;
    let denom = ray.direction.y;
    if denom.abs() < 1e-5 {
        return;
    }
    let t = (plane_y - ray.origin.y) / denom;
    if t < 0.0 {
        return;
    }
    let world_pos = ray.origin + ray.direction * t;

    let diff = world_pos - player_gtransform.translation();
    if diff.xz().length_squared() < 0.01 {
        return;
    }

    visual_transform.rotation = Quat::from_rotation_y((-diff.x).atan2(-diff.z));
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
    let Ok((local_transform, _)) = local_player.single() else { return };

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
