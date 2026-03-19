use avian3d::prelude::*;
use bevy::prelude::*;
use spacetimedb_sdk::Identity;
use std::collections::VecDeque;
use std::time::Duration;

use shared::module_bindings::attack_npc_reducer::attack_npc;
use shared::module_bindings::attack_player_reducer::attack_player;
use shared::module_bindings::move_player_reducer::move_player;
use shared::module_bindings::rotate_player_reducer::rotate_player;

use crate::constants::{
    ATTACK_RANGE, CAPSULE_HALF_LEN, CAPSULE_RADIUS, MAX_LOOK_AHEAD, MOVE_SPEED,
    PLAYER_GRAVITY_SCALE,
};
use crate::interpolation::InterpolationBuffer;
use crate::network::{LocalIdentity, PlayerEvent, PlayerEventQueue, SpacetimeDb, to_world_pos};
use crate::npc::NpcId;
use crate::world::MainCamera;

#[derive(Component)]
pub struct PlayerId(pub Identity);

#[derive(Component)]
pub struct LocalPlayer;

/// Marks the child entity that holds the visible model for a player.
#[derive(Component)]
pub struct PlayerVisual;

/// Marks the local player's visual child specifically, so `face_cursor` can target it uniquely.
#[derive(Component)]
pub struct LocalPlayerVisual;

/// Server-authoritative facing angle (Y-axis radians) for remote players.
#[derive(Component, Default)]
pub struct FacingAngle(pub f32);

/// Velocity derived from interpolation position deltas (for remote players).
#[derive(Component, Default)]
pub struct RemoteVelocity(pub Vec3);

/// Last facing angle sent to the server; avoids spamming `rotate_player` every frame.
#[derive(Resource, Default)]
pub struct LastSentFacingAngle(pub f32);

#[derive(Resource)]
pub struct MoveThrottle {
    pub last_sent_pos: Vec3,
    pub last_pos_time: f64,
    pub last_rot_time: f64,
}

impl Default for MoveThrottle {
    fn default() -> Self {
        Self {
            last_sent_pos: Vec3::ZERO,
            last_pos_time: 0.0,
            last_rot_time: 0.0,
        }
    }
}

const MOVE_SEND_INTERVAL: f64 = 1.0 / 20.0;
const ROTATION_SEND_INTERVAL: f64 = 1.0 / 10.0;
const MOVE_DEAD_ZONE: f32 = 0.01;
const RECONCILIATION_THRESHOLD: f32 = 2.0;
const CORRECTION_DECAY_RATE: f32 = 10.0;

#[derive(Resource, Default)]
pub struct MoveSequence(pub u32);

pub struct PredictedMove {
    pub seq: u32,
    pub position_after: Vec3,
}

#[derive(Resource, Default)]
pub struct PredictionBuffer {
    pub moves: VecDeque<PredictedMove>,
}

#[derive(Resource, Default)]
pub struct PredictionCorrection {
    pub offset: Vec3,
}

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

#[derive(Component)]
pub(crate) struct PlayerAnimNodes {
    idle: AnimationNodeIndex,
    walk: AnimationNodeIndex,
    walk_back: AnimationNodeIndex,
    run: AnimationNodeIndex,
    jump: AnimationNodeIndex,
    strafe_left: AnimationNodeIndex,
    strafe_right: AnimationNodeIndex,
    current: Option<AnimationNodeIndex>,
}

#[derive(Component)]
pub(crate) struct AnimBodyRef(Entity);

#[derive(Component)]
pub(crate) struct AnimVisualRef(Entity);

pub fn sync_players(
    mut commands: Commands,
    queue: Res<PlayerEventQueue>,
    local_identity: Res<LocalIdentity>,
    asset_server: Res<AssetServer>,
    time: Res<Time>,
    mut players: Query<(Entity, &PlayerId, &mut Transform, Option<&mut FacingAngle>, Option<&mut InterpolationBuffer>)>,
    mut local_stats: ResMut<LocalPlayerStats>,
    mut pred_buffer: ResMut<PredictionBuffer>,
    mut pred_correction: ResMut<PredictionCorrection>,
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
                    // Spawn a few units above ground so chunks have time to generate
                    // colliders before the player arrives. Low enough that impact
                    // velocity stays well under the capsule radius per physics step.
                    let spawn_y = 5.0;
                    let body = commands
                        .spawn((
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
                            SpeculativeMargin(0.0),
                        ))
                        .id();

                    let model_offset_y = -(CAPSULE_HALF_LEN + CAPSULE_RADIUS);
                    commands.entity(body).with_child((
                        PlayerVisual,
                        LocalPlayerVisual,
                        SceneRoot(asset_server.load("player.glb#Scene0")),
                        Transform::from_xyz(0.0, model_offset_y, 0.0),
                    ));
                } else {
                    let model_offset_y = -(CAPSULE_HALF_LEN + CAPSULE_RADIUS);
                    let mut buffer = InterpolationBuffer::default();
                    buffer.push(server_pos, player.facing_angle, time.elapsed_secs_f64());
                    let body = commands
                        .spawn((
                            PlayerId(player.identity),
                            FacingAngle(player.facing_angle),
                            RemoteVelocity::default(),
                            Transform::from_translation(server_pos),
                            Visibility::default(),
                            buffer,
                        ))
                        .id();
                    commands.entity(body).with_child((
                        PlayerVisual,
                        SceneRoot(asset_server.load("player.glb#Scene0")),
                        Transform::from_xyz(0.0, model_offset_y, 0.0),
                    ));
                }
            }
            PlayerEvent::Updated(player) => {
                let is_local = local_id.as_ref() == Some(&player.identity);
                if !is_local {
                    let now = time.elapsed_secs_f64();
                    for (_, id, _, _, interp_buffer) in players.iter_mut() {
                        if id.0 == player.identity {
                            if let Some(mut buffer) = interp_buffer {
                                buffer.push(
                                    to_world_pos(&player.position),
                                    player.facing_angle,
                                    now,
                                );
                            }
                        }
                    }
                }
                if is_local {
                    local_stats.health = player.health;
                    local_stats.mana = player.mana;
                    local_stats.stamina = player.stamina;

                    // Phase 5: Server reconciliation
                    let server_seq = player.last_seq;
                    let server_pos = to_world_pos(&player.position);

                    let predicted_pos = pred_buffer
                        .moves
                        .iter()
                        .find(|m| m.seq == server_seq)
                        .map(|m| m.position_after);

                    pred_buffer.moves.retain(|m| m.seq > server_seq);

                    if let Some(predicted) = predicted_pos {
                        let error = Vec3::new(
                            server_pos.x - predicted.x,
                            0.0,
                            server_pos.z - predicted.z,
                        );
                        if error.length() > RECONCILIATION_THRESHOLD {
                            for (_, id, mut transform, _, _) in players.iter_mut() {
                                if id.0 == player.identity {
                                    pred_correction.offset =
                                        Vec3::new(
                                            transform.translation.x - server_pos.x,
                                            0.0,
                                            transform.translation.z - server_pos.z,
                                        );
                                    transform.translation.x = server_pos.x;
                                    transform.translation.z = server_pos.z;
                                }
                            }
                        }
                    }
                }
            }
            PlayerEvent::Deleted(player) => {
                for (entity, id, _, _, _) in players.iter() {
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
    mut player: Query<(&Transform, &mut LinearVelocity), With<LocalPlayer>>,
    mut facing: ResMut<PlayerFacing>,
    mut throttle: ResMut<MoveThrottle>,
    mut move_seq: ResMut<MoveSequence>,
    mut pred_buffer: ResMut<PredictionBuffer>,
) {
    let Some(conn) = conn else { return };
    let Ok((transform, mut velocity)) = player.single_mut() else {
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

    if dir != Vec2::ZERO {
        let dir_norm = dir.normalize();
        facing.0 = dir_norm;
        velocity.x = dir_norm.x * MOVE_SPEED;
        velocity.z = dir_norm.y * MOVE_SPEED;

        let pos = transform.translation;
        let now = time.elapsed_secs_f64();
        if now - throttle.last_pos_time >= MOVE_SEND_INTERVAL
            && (pos - throttle.last_sent_pos).length() > MOVE_DEAD_ZONE
        {
            move_seq.0 = move_seq.0.wrapping_add(1);
            let seq = move_seq.0;

            throttle.last_sent_pos = pos;
            throttle.last_pos_time = now;
            if let Err(e) = conn.0.reducers.move_player(pos.x, pos.y, pos.z, seq) {
                error!("move_player failed: {e}");
            }

            pred_buffer.moves.push_back(PredictedMove {
                seq,
                position_after: pos,
            });
            if pred_buffer.moves.len() > 128 {
                pred_buffer.moves.pop_front();
            }
        }
    } else {
        velocity.x = 0.0;
        velocity.z = 0.0;
    }
}

/// Update `Grounded` based on vertical velocity: near-zero Y means on the ground.
pub fn update_grounded(mut query: Query<(&LinearVelocity, &mut Grounded), With<LocalPlayer>>) {
    for (velocity, mut grounded) in query.iter_mut() {
        grounded.0 = velocity.y < 1.0 && velocity.y > -4.0;
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

/// Rotate the player's visual model to face the cursor and sync the angle to the server.
/// Targets the `PlayerVisual` child so avian3d's locked-rotation body is unaffected.
pub fn face_cursor(
    conn: Option<Res<SpacetimeDb>>,
    windows: Query<&Window>,
    camera: Query<(&Camera, &GlobalTransform), With<MainCamera>>,
    local_player: Query<&GlobalTransform, With<LocalPlayer>>,
    mut visual: Query<&mut Transform, With<LocalPlayerVisual>>,
    mut last_sent: ResMut<LastSentFacingAngle>,
    time: Res<Time>,
    mut throttle: ResMut<MoveThrottle>,
) {
    let Ok(window) = windows.single() else { return };
    let Ok((cam, cam_transform)) = camera.single() else {
        return;
    };
    let Ok(player_gtransform) = local_player.single() else {
        return;
    };
    let Ok(mut visual_transform) = visual.single_mut() else {
        return;
    };
    let Some(cursor) = window.cursor_position() else {
        return;
    };

    let Ok(ray) = cam.viewport_to_world(cam_transform, cursor) else {
        return;
    };

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

    let angle = (-diff.x).atan2(-diff.z);
    visual_transform.rotation = Quat::from_rotation_y(angle);

    if (angle - last_sent.0).abs() > 0.05 {
        let now = time.elapsed_secs_f64();
        if now - throttle.last_rot_time >= ROTATION_SEND_INTERVAL {
            last_sent.0 = angle;
            throttle.last_rot_time = now;
            if let Some(conn) = conn {
                if let Err(e) = conn.0.reducers.rotate_player(angle) {
                    error!("rotate_player failed: {e}");
                }
            }
        }
    }
}

/// Apply the server-authoritative facing angle to each remote player's visual child.
pub fn apply_remote_player_facing(
    remote_players: Query<(&FacingAngle, &Children), Without<LocalPlayer>>,
    mut visuals: Query<&mut Transform, With<PlayerVisual>>,
) {
    for (facing, children) in remote_players.iter() {
        for child in children.iter() {
            if let Ok(mut transform) = visuals.get_mut(child) {
                transform.rotation = Quat::from_rotation_y(facing.0);
            }
        }
    }
}

/// When a player scene loads, find the `AnimationPlayer` entity and wire up the animation graph.
/// Animations in player.glb (by index): 0=jump, 1=run, 2=strafe_left, 3=strafe_right, 4=walk, 5=idle
pub fn setup_player_animations(
    mut commands: Commands,
    mut new_players: Query<(Entity, &mut AnimationPlayer), Added<AnimationPlayer>>,
    parents: Query<&ChildOf>,
    player_visuals: Query<(), With<PlayerVisual>>,
    mut graphs: ResMut<Assets<AnimationGraph>>,
    asset_server: Res<AssetServer>,
) {
    for (entity, _player) in new_players.iter_mut() {
        // Walk up the hierarchy to find the PlayerVisual ancestor.
        let mut is_player = false;
        let mut body_entity = None;
        let mut visual_entity = None;
        let mut current = entity;

        for _ in 0..8 {
            let Ok(child_of) = parents.get(current) else {
                break;
            };
            current = child_of.0;
            if player_visuals.contains(current) {
                is_player = true;
                visual_entity = Some(current);
                if let Ok(body_child_of) = parents.get(current) {
                    body_entity = Some(body_child_of.0);
                }
                break;
            }
        }

        if !is_player {
            continue;
        }

        let mut graph = AnimationGraph::new();
        let jump = graph.add_clip(asset_server.load("player.glb#Animation0"), 1.0, graph.root);
        let run = graph.add_clip(asset_server.load("player.glb#Animation1"), 1.0, graph.root);
        let strafe_left = graph.add_clip(asset_server.load("player.glb#Animation2"), 1.0, graph.root);
        let strafe_right = graph.add_clip(asset_server.load("player.glb#Animation3"), 1.0, graph.root);
        let walk = graph.add_clip(asset_server.load("player.glb#Animation4"), 1.0, graph.root);
        let walk_back = graph.add_clip(asset_server.load("player.glb#Animation4"), 1.0, graph.root);
        let idle = graph.add_clip(asset_server.load("player.glb#Animation5"), 1.0, graph.root);
        let graph_handle = graphs.add(graph);

        let mut entity_cmds = commands.entity(entity);
        entity_cmds.insert((
            AnimationGraphHandle(graph_handle),
            AnimationTransitions::new(),
            PlayerAnimNodes {
                idle,
                walk,
                walk_back,
                run,
                jump,
                strafe_left,
                strafe_right,
                current: None,
            },
        ));
        if let Some(body) = body_entity {
            entity_cmds.insert(AnimBodyRef(body));
        }
        if let Some(visual) = visual_entity {
            entity_cmds.insert(AnimVisualRef(visual));
        }
    }
}

/// Switch the playing animation based on the player body's horizontal speed.
pub fn drive_player_animations(
    mut query: Query<(
        &mut AnimationPlayer,
        &mut AnimationTransitions,
        &mut PlayerAnimNodes,
        &AnimBodyRef,
        Option<&AnimVisualRef>,
    )>,
    bodies: Query<(Option<&LinearVelocity>, Option<&Grounded>, Option<&RemoteVelocity>)>,
    visuals: Query<&GlobalTransform, With<PlayerVisual>>,
) {
    for (mut player, mut transitions, mut nodes, body_ref, visual_ref) in query.iter_mut() {
        let (velocity, grounded) = bodies
            .get(body_ref.0)
            .map(|(lin_vel, grounded, remote_vel)| {
                let vel = if let Some(v) = lin_vel {
                    Vec2::new(v.x, v.z)
                } else if let Some(rv) = remote_vel {
                    Vec2::new(rv.0.x, rv.0.z)
                } else {
                    Vec2::ZERO
                };
                (vel, grounded.map(|g| g.0))
            })
            .unwrap_or((Vec2::ZERO, Some(true)));
        let speed = velocity.length();
        let airborne = grounded == Some(false);

        let facing_dir = visual_ref
            .and_then(|visual_ref| visuals.get(visual_ref.0).ok())
            .map(|gt| {
                let forward = gt.compute_transform().forward().as_vec3();
                Vec2::new(forward.x, forward.z)
            })
            .unwrap_or(Vec2::new(0.0, -1.0));
        let facing_dir = if facing_dir.length_squared() > 1e-4 {
            facing_dir.normalize()
        } else {
            Vec2::new(0.0, -1.0)
        };
        let move_dir = if speed > 1e-4 {
            velocity / speed
        } else {
            Vec2::ZERO
        };
        let forwardness = facing_dir.dot(move_dir);
        let rightness = facing_dir.perp_dot(move_dir);

        let target = if airborne {
            nodes.jump
        } else if speed <= 0.5 {
            nodes.idle
        } else if forwardness > 0.5 {
            if speed > 5.0 { nodes.run } else { nodes.walk }
        } else if forwardness < -0.5 {
            nodes.walk_back
        } else if rightness >= 0.0 {
            nodes.strafe_right
        } else {
            nodes.strafe_left
        };

        let playback_speed = if target == nodes.walk_back { -1.0 } else { 1.0 };

        if Some(target) != nodes.current {
            nodes.current = Some(target);
            transitions
                .play(&mut player, target, Duration::from_millis(200))
                .set_speed(playback_speed);
        }
        // Re-enforce repeat and speed every frame — repeat() can be dropped
        // after a transition completes, which causes the animation to freeze.
        if let Some(active) = player.animation_mut(target) {
            active.repeat().set_speed(playback_speed);
        }
    }
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

/// Decay the visual correction offset so server reconciliation snaps are hidden.
/// Shifts the visual child by the remaining offset; as offset → 0 the visual
/// returns to being centered on the physics body.
pub fn smooth_prediction_correction(
    time: Res<Time>,
    mut correction: ResMut<PredictionCorrection>,
    player: Query<&Children, With<LocalPlayer>>,
    mut visuals: Query<&mut Transform, With<LocalPlayerVisual>>,
) {
    let decay = (-CORRECTION_DECAY_RATE * time.delta_secs()).exp();
    correction.offset *= decay;
    if correction.offset.length_squared() < 0.0001 {
        correction.offset = Vec3::ZERO;
    }

    let Ok(children) = player.single() else { return };
    for child in children.iter() {
        if let Ok(mut transform) = visuals.get_mut(child) {
            let model_offset_y = -(CAPSULE_HALF_LEN + CAPSULE_RADIUS);
            transform.translation = Vec3::new(
                correction.offset.x,
                model_offset_y,
                correction.offset.z,
            );
        }
    }
}
