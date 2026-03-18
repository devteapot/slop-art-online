use bevy::dev_tools::fps_overlay::{FpsOverlayConfig, FpsOverlayPlugin};
use bevy::prelude::*;
use bevy_voxel_world::prelude::*;
use shared::module_bindings::attack_npc_reducer::attack_npc;
use shared::module_bindings::attack_player_reducer::attack_player;
use shared::module_bindings::join_game_reducer::join_game;
use shared::module_bindings::move_player_reducer::move_player;
use shared::module_bindings::{DbConnection, Npc, NpcTableAccess, Player, PlayerTableAccess};
use spacetimedb_sdk::{DbContext, Identity, Table, TableWithPrimaryKey};
use std::sync::{Arc, Mutex};

const HOST: &str = "http://localhost:3000";
const DB_NAME: &str = "slop-art-online";
const MOVE_SPEED: f32 = 20.0;
const ATTACK_RANGE: f32 = 3.0;
const PLAYER_Y: f32 = 1.0; // height above terrain
const MAX_HEALTH: f32 = 100.0;
const HEALTH_BAR_WIDTH: f32 = 1.0;
const HEALTH_BAR_HEIGHT: f32 = 0.1;
const HEALTH_BAR_Y_OFFSET: f32 = 1.8; // above capsule top

fn main() {
    App::new()
        .add_plugins(DefaultPlugins)
        .add_plugins(FpsOverlayPlugin {
            config: FpsOverlayConfig {
                text_config: TextFont { font_size: 14.0, ..default() },
                ..default()
            },
        })
        .add_plugins(VoxelWorldPlugin::with_config(GameWorld))
        .init_resource::<PlayerEventQueue>()
        .init_resource::<NpcEventQueue>()
        .init_resource::<LocalIdentity>()
        .add_systems(Startup, (setup, connect_spacetimedb))
        .add_systems(Update, (
            tick_spacetimedb,
            sync_players,
            sync_npcs,
            move_local_player,
            follow_camera,
            attack,
            update_health_bars,
            billboard_health_bars,
        ).chain())
        .run();
}

// --- Voxel World ---

#[derive(Resource, Clone, Default)]
struct GameWorld;

impl VoxelWorldConfig for GameWorld {
    type MaterialIndex = u8;
    type ChunkUserBundle = ();

    fn spawning_distance(&self) -> u32 { 16 }

    fn voxel_lookup_delegate(&self) -> VoxelLookupDelegate<Self::MaterialIndex> {
        Box::new(move |_chunk_pos, _lod, _previous| {
            Box::new(move |pos: IVec3, _prev: Option<WorldVoxel>| {
                if pos.y < 0 {
                    WorldVoxel::Solid(0)
                } else {
                    WorldVoxel::Air
                }
            })
        })
    }
}

// --- Setup ---

fn setup(mut commands: Commands) {
    commands.spawn((
        Camera3d::default(),
        Transform::from_xyz(0.0, 30.0, 40.0).looking_at(Vec3::ZERO, Vec3::Y),
        VoxelWorldCamera::<GameWorld>::default(),
        MainCamera,
    ));

    commands.spawn((
        DirectionalLight {
            illuminance: 10_000.0,
            shadows_enabled: true,
            ..default()
        },
        Transform::from_rotation(Quat::from_euler(EulerRot::XYZ, -1.0, 0.4, 0.0)),
    ));

    commands.spawn(AmbientLight {
        color: Color::WHITE,
        brightness: 200.0,
        ..default()
    });
}

// --- SpacetimeDB ---

#[derive(Resource)]
struct SpacetimeDb(DbConnection);

#[derive(Resource, Default, Clone)]
struct PlayerEventQueue(Arc<Mutex<Vec<PlayerEvent>>>);

#[derive(Resource, Default, Clone)]
struct NpcEventQueue(Arc<Mutex<Vec<NpcEvent>>>);

#[derive(Resource, Default, Clone)]
struct LocalIdentity(Arc<Mutex<Option<Identity>>>);

enum PlayerEvent {
    Inserted(Player),
    Updated(Player),
    Deleted(Player),
}

enum NpcEvent {
    Inserted(Npc),
    Updated(Npc),
    Deleted(Npc),
}

fn connect_spacetimedb(
    mut commands: Commands,
    player_queue: Res<PlayerEventQueue>,
    npc_queue: Res<NpcEventQueue>,
    local_identity: Res<LocalIdentity>,
) {
    let q_insert = player_queue.clone();
    let q_update = player_queue.clone();
    let q_delete = player_queue.clone();
    let nq_insert = npc_queue.clone();
    let nq_update = npc_queue.clone();
    let nq_delete = npc_queue.clone();
    let identity_store = local_identity.clone();

    let conn = DbConnection::builder()
        .with_uri(HOST)
        .with_database_name(DB_NAME)
        .on_connect(move |ctx: &DbConnection, identity, _token| {
            *identity_store.0.lock().unwrap() = Some(identity);
            let _ = ctx.reducers.join_game();
            ctx.subscription_builder()
                .on_applied(|_| info!("Subscribed"))
                .subscribe(["SELECT * FROM player", "SELECT * FROM npc"]);
        })
        .on_connect_error(|_, err| error!("SpacetimeDB connect error: {err}"))
        .on_disconnect(|_, err| {
            if let Some(e) = err { error!("SpacetimeDB disconnected: {e}") }
        })
        .build()
        .expect("Failed to connect to SpacetimeDB");

    conn.db.player().on_insert(move |_, row: &Player| {
        q_insert.0.lock().unwrap().push(PlayerEvent::Inserted(row.clone()));
    });
    conn.db.player().on_update(move |_, _old: &Player, new: &Player| {
        q_update.0.lock().unwrap().push(PlayerEvent::Updated(new.clone()));
    });
    conn.db.player().on_delete(move |_, row: &Player| {
        q_delete.0.lock().unwrap().push(PlayerEvent::Deleted(row.clone()));
    });
    conn.db.npc().on_insert(move |_, row: &Npc| {
        nq_insert.0.lock().unwrap().push(NpcEvent::Inserted(row.clone()));
    });
    conn.db.npc().on_update(move |_, _old: &Npc, new: &Npc| {
        nq_update.0.lock().unwrap().push(NpcEvent::Updated(new.clone()));
    });
    conn.db.npc().on_delete(move |_, row: &Npc| {
        nq_delete.0.lock().unwrap().push(NpcEvent::Deleted(row.clone()));
    });

    commands.insert_resource(SpacetimeDb(conn));
}

fn tick_spacetimedb(conn: Res<SpacetimeDb>) {
    if let Err(e) = conn.0.frame_tick() {
        error!("SpacetimeDB tick error: {e}");
    }
}

fn to_world_pos(pos: &shared::module_bindings::Position) -> Vec3 {
    Vec3::new(pos.x, pos.y, pos.z)
}

// --- Health bar components ---

#[derive(Component)]
struct Health(i32);

/// Marker on the fill mesh entity of a health bar.
#[derive(Component)]
struct HealthBarFill;

/// Marker on the root entity of a health bar (the billboard container).
#[derive(Component)]
struct HealthBarRoot;

/// Stored on character entities; points to their fill mesh entity.
#[derive(Component)]
struct HealthBarFillRef(Entity);

fn spawn_health_bar(
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

// --- Players ---

#[derive(Component)]
struct PlayerId(Identity);

#[derive(Component)]
struct LocalPlayer;

#[derive(Component)]
struct MainCamera;

fn sync_players(
    mut commands: Commands,
    queue: Res<PlayerEventQueue>,
    local_identity: Res<LocalIdentity>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    mut players: Query<(Entity, &PlayerId, &mut Transform, &mut Health)>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            PlayerEvent::Inserted(player) => {
                let is_local = local_id.as_ref() == Some(&player.identity);
                let color = if is_local {
                    Color::srgb(0.4, 0.8, 1.0)
                } else {
                    Color::WHITE
                };
                let (bar_root, fill_id) = spawn_health_bar(&mut commands, &mut meshes, &mut materials);
                let mut entity_cmd = commands.spawn((
                    PlayerId(player.identity),
                    Mesh3d(meshes.add(Capsule3d::new(0.4, 1.0))),
                    MeshMaterial3d(materials.add(StandardMaterial {
                        base_color: color,
                        ..default()
                    })),
                    Transform::from_translation(to_world_pos(&player.position)),
                    Health(player.health),
                    HealthBarFillRef(fill_id),
                ));
                entity_cmd.add_child(bar_root);
                if is_local {
                    entity_cmd.insert(LocalPlayer);
                }
            }
            PlayerEvent::Updated(player) => {
                for (_, id, mut transform, mut health) in players.iter_mut() {
                    if id.0 == player.identity {
                        transform.translation = to_world_pos(&player.position);
                        health.0 = player.health;
                    }
                }
            }
            PlayerEvent::Deleted(player) => {
                for (entity, id, _, _) in players.iter() {
                    if id.0 == player.identity {
                        commands.entity(entity).despawn();
                    }
                }
            }
        }
    }
}

// --- NPCs ---

#[derive(Component)]
struct NpcId(u64);

fn sync_npcs(
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

// --- Health bar update ---

fn update_health_bars(
    characters: Query<(&Health, &HealthBarFillRef)>,
    mut fills: Query<&mut Transform, With<HealthBarFill>>,
) {
    for (health, fill_ref) in &characters {
        if let Ok(mut transform) = fills.get_mut(fill_ref.0) {
            let ratio = (health.0 as f32 / MAX_HEALTH).clamp(0.0, 1.0);
            transform.scale.x = ratio;
            // Anchor the fill to the left edge so it depletes right-to-left
            transform.translation.x = -HEALTH_BAR_WIDTH * (1.0 - ratio) / 2.0;
        }
    }
}

// --- Billboard: health bars always face the camera ---

fn billboard_health_bars(
    camera: Query<&GlobalTransform, With<MainCamera>>,
    mut bars: Query<&mut Transform, With<HealthBarRoot>>,
) {
    let Ok(cam_gt) = camera.single() else { return };
    let (_, cam_rot, _) = cam_gt.to_scale_rotation_translation();

    for mut bar_lt in &mut bars {
        bar_lt.rotation = cam_rot;
    }
}

// --- Movement ---

fn move_local_player(
    conn: Option<Res<SpacetimeDb>>,
    keys: Res<ButtonInput<KeyCode>>,
    time: Res<Time>,
    player: Query<&Transform, With<LocalPlayer>>,
) {
    let Some(conn) = conn else { return };
    let Ok(transform) = player.single() else { return };

    let mut dir = Vec2::ZERO;
    if keys.pressed(KeyCode::KeyW) || keys.pressed(KeyCode::ArrowUp)    { dir.y -= 1.0; }
    if keys.pressed(KeyCode::KeyS) || keys.pressed(KeyCode::ArrowDown)  { dir.y += 1.0; }
    if keys.pressed(KeyCode::KeyA) || keys.pressed(KeyCode::ArrowLeft)  { dir.x -= 1.0; }
    if keys.pressed(KeyCode::KeyD) || keys.pressed(KeyCode::ArrowRight) { dir.x += 1.0; }

    if dir == Vec2::ZERO { return }

    let delta = dir.normalize() * MOVE_SPEED * time.delta_secs();
    let new_x = transform.translation.x + delta.x;
    let new_z = transform.translation.z + delta.y;

    if let Err(e) = conn.0.reducers.move_player(new_x, PLAYER_Y, new_z) {
        error!("move_player failed: {e}");
    }
}

// --- Camera follow ---

fn follow_camera(
    local_player: Query<&Transform, With<LocalPlayer>>,
    mut camera: Query<&mut Transform, (With<MainCamera>, Without<LocalPlayer>)>,
) {
    let Ok(player) = local_player.single() else { return };
    let Ok(ref mut cam) = camera.single_mut() else { return };

    let target = player.translation + Vec3::new(0.0, 30.0, 40.0);
    cam.translation = cam.translation.lerp(target, 0.1);
    cam.look_at(player.translation, Vec3::Y);
}

// --- Attack ---

fn attack(
    conn: Option<Res<SpacetimeDb>>,
    keys: Res<ButtonInput<KeyCode>>,
    local_player: Query<(&Transform, &PlayerId), With<LocalPlayer>>,
    players: Query<(&Transform, &PlayerId), Without<LocalPlayer>>,
    npcs: Query<(&Transform, &NpcId)>,
) {
    if !keys.just_pressed(KeyCode::Space) { return }
    let Some(conn) = conn else { return };
    let Ok((local_transform, _)) = local_player.single() else { return };

    let local_pos = local_transform.translation;

    let nearest_player = players.iter()
        .map(|(t, id)| (t.translation.distance(local_pos), id.0))
        .filter(|(dist, _)| *dist <= ATTACK_RANGE)
        .min_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

    let nearest_npc = npcs.iter()
        .map(|(t, id)| (t.translation.distance(local_pos), id.0))
        .filter(|(dist, _)| *dist <= ATTACK_RANGE)
        .min_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

    match (nearest_player, nearest_npc) {
        (Some((pd, pid)), Some((nd, nid))) => {
            if pd <= nd { let _ = conn.0.reducers.attack_player(pid); }
            else        { let _ = conn.0.reducers.attack_npc(nid); }
        }
        (Some((_, pid)), None) => { let _ = conn.0.reducers.attack_player(pid); }
        (None, Some((_, nid))) => { let _ = conn.0.reducers.attack_npc(nid); }
        (None, None) => {}
    }
}
