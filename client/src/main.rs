mod module_bindings;

use bevy::prelude::*;
use module_bindings::{DbConnection, Npc, NpcTableAccess, Player, PlayerTableAccess};
use module_bindings::move_player_reducer::move_player;
use module_bindings::attack_player_reducer::attack_player;
use module_bindings::attack_npc_reducer::attack_npc;
use spacetimedb_sdk::{DbContext, Identity, Table, TableWithPrimaryKey};
use std::sync::{Arc, Mutex};

const HOST: &str = "http://localhost:3000";
const DB_NAME: &str = "slop-art-online";
const MOVE_SPEED: f32 = 200.0;
const ATTACK_RANGE: f32 = 100.0;
const MAX_HEALTH: i32 = 100;
const HEALTH_BAR_WIDTH: f32 = 40.0;
const HEALTH_BAR_HEIGHT: f32 = 5.0;
const HEALTH_BAR_OFFSET_Y: f32 = 28.0;

fn main() {
    App::new()
        .add_plugins(DefaultPlugins)
        .init_resource::<PlayerEventQueue>()
        .init_resource::<NpcEventQueue>()
        .init_resource::<LocalIdentity>()
        .add_systems(Startup, (setup_camera, connect_spacetimedb))
        .add_systems(Update, (
            tick_spacetimedb,
            sync_players,
            sync_npcs,
            update_health_bars,
            move_local_player,
            attack,
        ).chain())
        .run();
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
            ctx.subscription_builder()
                .on_applied(|_| info!("Subscribed"))
                .subscribe(["SELECT * FROM player", "SELECT * FROM npc"]);
        })
        .on_connect_error(|_, err| error!("SpacetimeDB connect error: {err}"))
        .on_disconnect(|_, err| {
            if let Some(e) = err {
                error!("SpacetimeDB disconnected: {e}")
            }
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

// --- Health bar ---

#[derive(Component)]
struct Health(i32);

#[derive(Component)]
struct HealthBarFill(Entity);

fn spawn_health_bar(commands: &mut Commands, parent: Entity, offset_y: f32) -> Entity {
    let fill = commands.spawn((
        Sprite {
            color: Color::srgb(0.2, 0.8, 0.2),
            custom_size: Some(Vec2::new(HEALTH_BAR_WIDTH, HEALTH_BAR_HEIGHT)),
            ..default()
        },
        Transform::from_xyz(0.0, offset_y, 1.0),
    )).id();

    let background = commands.spawn((
        Sprite {
            color: Color::srgb(0.2, 0.2, 0.2),
            custom_size: Some(Vec2::new(HEALTH_BAR_WIDTH, HEALTH_BAR_HEIGHT)),
            ..default()
        },
        Transform::from_xyz(0.0, offset_y, 0.9),
    )).id();

    commands.entity(parent).add_children(&[background, fill]);
    fill
}

fn update_health_bars(
    query: Query<(&Health, &HealthBarFill), Changed<Health>>,
    mut fills: Query<&mut Transform>,
) {
    for (health, bar) in query.iter() {
        if let Ok(mut transform) = fills.get_mut(bar.0) {
            let ratio = (health.0 as f32 / MAX_HEALTH as f32).clamp(0.0, 1.0);
            // Scale from left: adjust x so the bar shrinks rightward
            transform.scale.x = ratio;
            transform.translation.x = -HEALTH_BAR_WIDTH / 2.0 + (HEALTH_BAR_WIDTH * ratio) / 2.0;
        }
    }
}

// --- Players ---

#[derive(Component)]
struct PlayerId(Identity);

#[derive(Component)]
struct LocalPlayer;

fn sync_players(
    mut commands: Commands,
    queue: Res<PlayerEventQueue>,
    local_identity: Res<LocalIdentity>,
    mut players: Query<(Entity, &PlayerId, &mut Transform, &mut Health)>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            PlayerEvent::Inserted(player) => {
                let is_local = local_id.as_ref() == Some(&player.identity);
                let mut entity_cmd = commands.spawn((
                    PlayerId(player.identity),
                    Health(player.health),
                    Sprite {
                        color: if is_local { Color::srgb(0.4, 0.8, 1.0) } else { Color::WHITE },
                        custom_size: Some(Vec2::splat(32.0)),
                        ..default()
                    },
                    Transform::from_xyz(player.position.x, player.position.y, 0.0),
                ));
                if is_local {
                    entity_cmd.insert(LocalPlayer);
                }
                let entity = entity_cmd.id();
                let fill = spawn_health_bar(&mut commands, entity, HEALTH_BAR_OFFSET_Y);
                commands.entity(entity).insert(HealthBarFill(fill));
            }
            PlayerEvent::Updated(player) => {
                for (_, id, mut transform, mut health) in players.iter_mut() {
                    if id.0 == player.identity {
                        transform.translation.x = player.position.x;
                        transform.translation.y = player.position.y;
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
    mut materials: ResMut<Assets<ColorMaterial>>,
    mut npcs: Query<(Entity, &NpcId, &mut Transform, &mut Health)>,
) {
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            NpcEvent::Inserted(npc) => {
                let entity = commands.spawn((
                    NpcId(npc.id),
                    Health(npc.health),
                    Mesh2d(meshes.add(Circle::new(16.0))),
                    MeshMaterial2d(materials.add(Color::srgb(1.0, 0.5, 0.2))),
                    Transform::from_xyz(npc.position.x, npc.position.y, 0.0),
                )).id();
                let fill = spawn_health_bar(&mut commands, entity, HEALTH_BAR_OFFSET_Y);
                commands.entity(entity).insert(HealthBarFill(fill));
            }
            NpcEvent::Updated(npc) => {
                for (_, id, mut transform, mut health) in npcs.iter_mut() {
                    if id.0 == npc.id {
                        transform.translation.x = npc.position.x;
                        transform.translation.y = npc.position.y;
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

// --- Movement ---

fn move_local_player(
    conn: Res<SpacetimeDb>,
    keys: Res<ButtonInput<KeyCode>>,
    time: Res<Time>,
    player: Query<&Transform, With<LocalPlayer>>,
) {
    let Ok(transform) = player.single() else { return };

    let mut dir = Vec2::ZERO;
    if keys.pressed(KeyCode::KeyW) || keys.pressed(KeyCode::ArrowUp)    { dir.y += 1.0; }
    if keys.pressed(KeyCode::KeyS) || keys.pressed(KeyCode::ArrowDown)  { dir.y -= 1.0; }
    if keys.pressed(KeyCode::KeyA) || keys.pressed(KeyCode::ArrowLeft)  { dir.x -= 1.0; }
    if keys.pressed(KeyCode::KeyD) || keys.pressed(KeyCode::ArrowRight) { dir.x += 1.0; }

    if dir == Vec2::ZERO { return }

    let delta = dir.normalize() * MOVE_SPEED * time.delta_secs();
    let new_x = transform.translation.x + delta.x;
    let new_y = transform.translation.y + delta.y;

    if let Err(e) = conn.0.reducers.move_player(new_x, new_y) {
        error!("move_player failed: {e}");
    }
}

// --- Attack ---

fn attack(
    conn: Res<SpacetimeDb>,
    keys: Res<ButtonInput<KeyCode>>,
    local_player: Query<(&Transform, &PlayerId), With<LocalPlayer>>,
    players: Query<(&Transform, &PlayerId), Without<LocalPlayer>>,
    npcs: Query<(&Transform, &NpcId)>,
) {
    if !keys.just_pressed(KeyCode::Space) { return }
    let Ok((local_transform, _)) = local_player.single() else { return };

    let local_pos = local_transform.translation.truncate();

    // Find nearest target within range across both players and NPCs
    let nearest_player = players.iter()
        .map(|(t, id)| (t.translation.truncate().distance(local_pos), id.0, true))
        .filter(|(dist, _, _)| *dist <= ATTACK_RANGE)
        .min_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

    let nearest_npc = npcs.iter()
        .map(|(t, id)| (t.translation.truncate().distance(local_pos), id.0))
        .filter(|(dist, _)| *dist <= ATTACK_RANGE)
        .min_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

    match (nearest_player, nearest_npc) {
        (Some((pd, pid, _)), Some((nd, nid))) => {
            if pd <= nd {
                let _ = conn.0.reducers.attack_player(pid);
            } else {
                let _ = conn.0.reducers.attack_npc(nid);
            }
        }
        (Some((_, pid, _)), None) => { let _ = conn.0.reducers.attack_player(pid); }
        (None, Some((_, nid))) => { let _ = conn.0.reducers.attack_npc(nid); }
        (None, None) => {}
    }
}

// --- Camera ---

fn setup_camera(mut commands: Commands) {
    commands.spawn(Camera2d::default());
}
