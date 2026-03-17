mod module_bindings;

use bevy::prelude::*;
use module_bindings::{DbConnection, Player, PlayerTableAccess};
use module_bindings::move_player_reducer::move_player;
use spacetimedb_sdk::{DbContext, Identity, Table, TableWithPrimaryKey};
use std::sync::{Arc, Mutex};

const HOST: &str = "http://localhost:3000";
const DB_NAME: &str = "slop-art-online";
const MOVE_SPEED: f32 = 200.0;

fn main() {
    App::new()
        .add_plugins(DefaultPlugins)
        .init_resource::<PlayerEventQueue>()
        .init_resource::<LocalIdentity>()
        .add_systems(Startup, (setup_camera, connect_spacetimedb))
        .add_systems(Update, (tick_spacetimedb, sync_players, move_local_player).chain())
        .run();
}

// --- SpacetimeDB ---

#[derive(Resource)]
struct SpacetimeDb(DbConnection);

#[derive(Resource, Default, Clone)]
struct PlayerEventQueue(Arc<Mutex<Vec<PlayerEvent>>>);

#[derive(Resource, Default, Clone)]
struct LocalIdentity(Arc<Mutex<Option<Identity>>>);

enum PlayerEvent {
    Inserted(Player),
    Updated(Player),
    Deleted(Player),
}

fn connect_spacetimedb(
    mut commands: Commands,
    queue: Res<PlayerEventQueue>,
    local_identity: Res<LocalIdentity>,
) {
    let q_insert = queue.clone();
    let q_update = queue.clone();
    let q_delete = queue.clone();
    let identity_store = local_identity.clone();

    let conn = DbConnection::builder()
        .with_uri(HOST)
        .with_database_name(DB_NAME)
        .on_connect(move |ctx: &DbConnection, identity, _token| {
            *identity_store.0.lock().unwrap() = Some(identity);
            ctx.subscription_builder()
                .on_applied(|_| info!("Subscribed to player table"))
                .subscribe(["SELECT * FROM player"]);
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

    commands.insert_resource(SpacetimeDb(conn));
}

fn tick_spacetimedb(conn: Res<SpacetimeDb>) {
    if let Err(e) = conn.0.frame_tick() {
        error!("SpacetimeDB tick error: {e}");
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
    mut players: Query<(Entity, &PlayerId, &mut Transform)>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            PlayerEvent::Inserted(player) => {
                let is_local = local_id.as_ref() == Some(&player.identity);
                let mut entity = commands.spawn((
                    PlayerId(player.identity),
                    Sprite {
                        color: if is_local { Color::srgb(0.4, 0.8, 1.0) } else { Color::WHITE },
                        custom_size: Some(Vec2::splat(32.0)),
                        ..default()
                    },
                    Transform::from_xyz(player.position.x, player.position.y, 0.0),
                ));
                if is_local {
                    entity.insert(LocalPlayer);
                }
            }
            PlayerEvent::Updated(player) => {
                for (_, id, mut transform) in players.iter_mut() {
                    if id.0 == player.identity {
                        transform.translation.x = player.position.x;
                        transform.translation.y = player.position.y;
                    }
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

// --- Camera ---

fn setup_camera(mut commands: Commands) {
    commands.spawn(Camera2d::default());
}
