use avian3d::prelude::*;
use bevy::prelude::*;
use spacetimedb_sdk::Identity;
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use shared::module_bindings::move_player_reducer::move_player;
use shared::module_bindings::rotate_player_reducer::rotate_player;

use crate::constants::{
    AIR_CONTROL_FACTOR, CAM_SMOOTH_SPEED, CAPSULE_HALF_LEN, CAPSULE_RADIUS, GROUND_ACCEL,
    GROUND_DECEL, JUMP_IMPULSE, MAX_LOOK_AHEAD, MOVE_SPEED, PLAYER_GRAVITY_SCALE,
};
use crate::interpolation::InterpolationBuffer;
use crate::network::{ActiveSkillEvent, ActiveSkillEventQueue, LocalIdentity, PlayerEvent, PlayerEventQueue, SpacetimeDb, to_world_pos};
use crate::chat::ChatInputActive;
use crate::skills::SkillNameMap;
use crate::status_effects::{speed_multiplier, LocalStatusEffects};
use crate::health_bar::{spawn_health_bar, Health, HealthBarFillRef};
use crate::world::MainCamera;

/// When true, camera stays centered on the player (no cursor look-ahead).
/// Toggle with Y key.
#[derive(Resource)]
pub struct CameraLocked(pub bool);

impl Default for CameraLocked {
    fn default() -> Self {
        Self(true)
    }
}

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
    pub level: i32,
    pub xp: i32,
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
            level: 1,
            xp: 0,
        }
    }
}

/// XZ facing direction from last movement input, used for dash direction.
#[derive(Resource, Default)]
pub struct PlayerFacing(pub Vec2);

/// World-space position where the cursor ray hits the player's Y plane.
#[derive(Resource, Default)]
pub struct CursorGroundPos(pub Option<Vec3>);

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

/// Fired when a skill animation should begin (local or remote).
pub struct AbilityAnimTrigger {
    pub identity: Identity,
    pub skill_id: u64,
}

#[derive(Resource, Default, Clone)]
pub struct AbilityAnimTriggerQueue(pub Arc<Mutex<Vec<AbilityAnimTrigger>>>);

/// Active ability animation on a player's AnimationPlayer entity.
#[derive(Component)]
pub struct ActiveAbilityAnim {
    pub skill_id: u64,
    pub started_at: f64,
    pub duration: f32,
    pub anim_node: AnimationNodeIndex,
}

fn ability_anim_for_skill(skill_name: &str, nodes: &PlayerAnimNodes) -> (AnimationNodeIndex, f32) {
    match skill_name {
        "Jump" => (nodes.jump, 0.8),
        "Dash" => (nodes.run, 0.2),
        _ => (nodes.jump, 0.5),
    }
}

pub fn sync_players(
    mut commands: Commands,
    queue: Res<PlayerEventQueue>,
    local_identity: Res<LocalIdentity>,
    asset_server: Res<AssetServer>,
    time: Res<Time>,
    mut players: Query<(Entity, &PlayerId, &mut Transform, Option<&mut FacingAngle>, Option<&mut InterpolationBuffer>, Option<&mut Health>)>,
    mut local_stats: ResMut<LocalPlayerStats>,
    mut pred_buffer: ResMut<PredictionBuffer>,
    mut pred_correction: ResMut<PredictionCorrection>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            PlayerEvent::Inserted(player) => {
                let is_local = local_id.as_ref() == Some(&player.identity);
                if is_local {
                    local_stats.health = player.health;
                    local_stats.max_health = player.max_health;
                    local_stats.mana = player.mana;
                    local_stats.max_mana = player.max_mana;
                    local_stats.stamina = player.stamina;
                    local_stats.max_stamina = player.max_stamina;
                    local_stats.level = player.level;
                    local_stats.xp = player.xp;
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
                            Friction {
                                dynamic_coefficient: 0.0,
                                static_coefficient: 0.0,
                                combine_rule: CoefficientCombine::Min,
                            },
                            SpeculativeMargin(0.1),
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
                    let (bar_root, fill_id) = spawn_health_bar(&mut commands, &mut meshes, &mut materials);
                    let body = commands
                        .spawn((
                            PlayerId(player.identity),
                            FacingAngle(player.facing_angle),
                            RemoteVelocity::default(),
                            Transform::from_translation(server_pos),
                            Visibility::default(),
                            buffer,
                            Health { current: player.health, max: player.max_health },
                            HealthBarFillRef(fill_id),
                        ))
                        .id();
                    commands.entity(body).with_child((
                        PlayerVisual,
                        SceneRoot(asset_server.load("player.glb#Scene0")),
                        Transform::from_xyz(0.0, model_offset_y, 0.0),
                    ));
                    commands.entity(body).add_child(bar_root);
                }
            }
            PlayerEvent::Updated(player) => {
                let is_local = local_id.as_ref() == Some(&player.identity);
                if !is_local {
                    let now = time.elapsed_secs_f64();
                    for (_, id, _, _, interp_buffer, health) in players.iter_mut() {
                        if id.0 == player.identity {
                            if let Some(mut buffer) = interp_buffer {
                                buffer.push(
                                    to_world_pos(&player.position),
                                    player.facing_angle,
                                    now,
                                );
                            }
                            if let Some(mut h) = health {
                                h.current = player.health;
                                h.max = player.max_health;
                            }
                        }
                    }
                }
                if is_local {
                    local_stats.health = player.health;
                    local_stats.max_health = player.max_health;
                    local_stats.mana = player.mana;
                    local_stats.max_mana = player.max_mana;
                    local_stats.stamina = player.stamina;
                    local_stats.max_stamina = player.max_stamina;
                    local_stats.level = player.level;
                    local_stats.xp = player.xp;

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
                            for (_, id, mut transform, _, _, _) in players.iter_mut() {
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
                for (entity, id, _, _, _, _) in players.iter() {
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
    mut player: Query<(&Transform, &mut LinearVelocity, &Grounded), With<LocalPlayer>>,
    mut facing: ResMut<PlayerFacing>,
    mut throttle: ResMut<MoveThrottle>,
    mut move_seq: ResMut<MoveSequence>,
    mut pred_buffer: ResMut<PredictionBuffer>,
    chat_active: Res<ChatInputActive>,
    local_effects: Res<LocalStatusEffects>,
) {
    if chat_active.0 { return; }
    let Some(conn) = conn else { return };
    let Ok((transform, mut velocity, grounded)) = player.single_mut() else {
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

    // Update facing even when airborne (so dash direction works)
    if dir != Vec2::ZERO {
        facing.0 = dir.normalize();
    }

    // Skip XZ application while Y velocity is high (just jumped) so the player
    // clears the wall-ground corner before horizontal velocity is re-applied.
    let rising_from_jump = velocity.y > JUMP_IMPULSE * 0.5;

    let dt = time.delta_secs();

    if grounded.0 && !rising_from_jump {
        // Full ground control with acceleration ramp.
        let effective_speed = MOVE_SPEED * speed_multiplier(&local_effects);
        if dir != Vec2::ZERO {
            let dir_norm = dir.normalize();
            let target_x = dir_norm.x * effective_speed;
            let target_z = dir_norm.y * effective_speed;
            velocity.x = move_toward(velocity.x, target_x, GROUND_ACCEL * dt);
            velocity.z = move_toward(velocity.z, target_z, GROUND_ACCEL * dt);
        } else {
            velocity.x = move_toward(velocity.x, 0.0, GROUND_DECEL * dt);
            velocity.z = move_toward(velocity.z, 0.0, GROUND_DECEL * dt);
        }
    } else {
        // Airborne: reduced continuous control.
        if dir != Vec2::ZERO {
            let dir_norm = dir.normalize();
            let air_speed = MOVE_SPEED * AIR_CONTROL_FACTOR;
            let target_x = dir_norm.x * air_speed;
            let target_z = dir_norm.y * air_speed;
            let accel = GROUND_ACCEL * AIR_CONTROL_FACTOR * dt;
            velocity.x = move_toward(velocity.x, target_x, accel);
            velocity.z = move_toward(velocity.z, target_z, accel);
        }
    }

    // Send position updates when XZ movement or Y change (jump/fall) exceeds dead zone.
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
}

/// Update `Grounded` by casting a short ray downward from the capsule bottom.
pub fn update_grounded(
    spatial: SpatialQuery,
    mut query: Query<(Entity, &Transform, &mut Grounded), With<LocalPlayer>>,
) {
    for (entity, transform, mut grounded) in query.iter_mut() {
        // Cast from capsule centre downward; max distance = half-height + small skin.
        let capsule_half_height = CAPSULE_HALF_LEN + CAPSULE_RADIUS;
        let skin = 0.3;
        let hit = spatial.cast_ray(
            transform.translation,
            Dir3::NEG_Y,
            capsule_half_height + skin,
            true,
            &SpatialQueryFilter::default().with_excluded_entities([entity]),
        );
        grounded.0 = hit.is_some();
    }
}

pub fn toggle_camera_lock(
    input: Res<ButtonInput<KeyCode>>,
    mut locked: ResMut<CameraLocked>,
) {
    if input.just_pressed(KeyCode::KeyY) {
        locked.0 = !locked.0;
    }
}

pub fn follow_camera(
    windows: Query<&Window>,
    local_player: Query<&Transform, With<LocalPlayer>>,
    mut camera: Query<&mut Transform, (With<MainCamera>, Without<LocalPlayer>)>,
    locked: Res<CameraLocked>,
    time: Res<Time>,
) {
    let Ok(player) = local_player.single() else {
        return;
    };
    let Ok(ref mut cam) = camera.single_mut() else {
        return;
    };

    let look_ahead = if locked.0 {
        Vec3::ZERO
    } else {
        let Ok(window) = windows.single() else {
            return;
        };
        if let Some(cursor) = window.cursor_position() {
            let half = Vec2::new(window.width(), window.height()) * 0.5;
            let norm = ((cursor - half) / half).clamp(Vec2::splat(-1.0), Vec2::splat(1.0));
            Vec3::new(norm.x * MAX_LOOK_AHEAD, 0.0, norm.y * MAX_LOOK_AHEAD)
        } else {
            Vec3::ZERO
        }
    };

    let target = player.translation + Vec3::new(0.0, 30.0, 40.0) + look_ahead;
    let t = 1.0 - (-CAM_SMOOTH_SPEED * time.delta_secs()).exp();
    cam.translation = cam.translation.lerp(target, t);
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
    mut cursor_ground: ResMut<CursorGroundPos>,
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
    cursor_ground.0 = Some(world_pos);

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
        Option<&ActiveAbilityAnim>,
    )>,
    bodies: Query<(Option<&LinearVelocity>, Option<&Grounded>, Option<&RemoteVelocity>)>,
    visuals: Query<&GlobalTransform, With<PlayerVisual>>,
) {
    const IDLE_ENTER_SPEED: f32 = 0.3;
    const IDLE_EXIT_SPEED: f32 = 0.7;

    for (mut player, mut transitions, mut nodes, body_ref, visual_ref, active_ability) in query.iter_mut() {
        // Highest priority: active ability animation overrides everything.
        if let Some(ability) = active_ability {
            let target = ability.anim_node;
            if Some(target) != nodes.current {
                nodes.current = Some(target);
                transitions
                    .play(&mut player, target, Duration::from_millis(100))
                    .set_speed(1.0);
            }
            continue;
        }

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
                // Derive grounded for remote players from vertical velocity.
                // Local player uses physics Grounded component.
                // Remote player: derive from snapshot Y velocity. Thresholds
                // are wider than the local physics check because snapshot
                // velocity is averaged over ~50ms and slope movement adds a
                // large Y component (speed 20 on a 20° slope ≈ ±6.8).
                let grounded_val = if let Some(g) = grounded {
                    g.0
                } else if let Some(rv) = remote_vel {
                    rv.0.y < 8.0 && rv.0.y > -8.0
                } else {
                    true
                };
                (vel, grounded_val)
            })
            .unwrap_or((Vec2::ZERO, true));
        let speed = velocity.length();
        let airborne = !grounded;

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

        let is_idle = nodes.current == Some(nodes.idle) || nodes.current.is_none();
        let idle_threshold = if is_idle { IDLE_EXIT_SPEED } else { IDLE_ENTER_SPEED };

        let target = if airborne {
            nodes.jump
        } else if speed <= idle_threshold {
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

fn move_toward(current: f32, target: f32, max_delta: f32) -> f32 {
    if (target - current).abs() <= max_delta {
        target
    } else {
        current + (target - current).signum() * max_delta
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

/// Drain ActiveSkill insert events from remote players and fire AbilityAnimTrigger.
pub fn sync_active_skills(
    mut commands: Commands,
    queue: Res<ActiveSkillEventQueue>,
    local_identity: Res<LocalIdentity>,
    ability_queue: Res<AbilityAnimTriggerQueue>,
    anim_query: Query<(Entity, &AnimBodyRef, &ActiveAbilityAnim)>,
    bodies: Query<&PlayerId>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let mut events = queue.0.lock().unwrap();
    let mut triggers = ability_queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            ActiveSkillEvent::Inserted(active) => {
                let is_local = local_id.as_ref() == Some(&active.player_identity);
                if !is_local {
                    triggers.push(AbilityAnimTrigger {
                        identity: active.player_identity,
                        skill_id: active.skill_id,
                    });
                }
            }
            ActiveSkillEvent::Deleted(active) => {
                // Server cancelled the ability early (e.g. silence) — remove
                // the animation component so it doesn't play to completion.
                for (entity, body_ref, anim) in anim_query.iter() {
                    if anim.skill_id == active.skill_id {
                        if let Ok(pid) = bodies.get(body_ref.0) {
                            if pid.0 == active.player_identity {
                                commands.entity(entity).remove::<ActiveAbilityAnim>();
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Read AbilityAnimTrigger events, find the matching player's animation entity,
/// and insert an ActiveAbilityAnim component.
pub fn trigger_ability_animations(
    mut commands: Commands,
    ability_queue: Res<AbilityAnimTriggerQueue>,
    skill_names: Res<SkillNameMap>,
    time: Res<Time>,
    anim_query: Query<(Entity, &AnimBodyRef, &PlayerAnimNodes)>,
    bodies: Query<&PlayerId>,
) {
    let mut triggers = ability_queue.0.lock().unwrap();
    for trigger in triggers.drain(..) {
        let skill_name = skill_names.0.get(&trigger.skill_id).map(|s| s.as_str()).unwrap_or("");
        for (entity, body_ref, nodes) in anim_query.iter() {
            if let Ok(pid) = bodies.get(body_ref.0) {
                if pid.0 == trigger.identity {
                    let (anim_node, duration) = ability_anim_for_skill(skill_name, nodes);
                    commands.entity(entity).insert(ActiveAbilityAnim {
                        skill_id: trigger.skill_id,
                        started_at: time.elapsed_secs_f64(),
                        duration,
                        anim_node,
                    });
                }
            }
        }
    }
}

/// Remove ActiveAbilityAnim when its duration has elapsed.
pub fn expire_ability_animations(
    mut commands: Commands,
    time: Res<Time>,
    query: Query<(Entity, &ActiveAbilityAnim)>,
) {
    let now = time.elapsed_secs_f64();
    for (entity, anim) in query.iter() {
        if now - anim.started_at >= anim.duration as f64 {
            commands.entity(entity).remove::<ActiveAbilityAnim>();
        }
    }
}
