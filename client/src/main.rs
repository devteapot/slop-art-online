mod module_bindings;

use bevy::prelude::*;
use module_bindings::{DbConnection, Player, PlayerTableAccess};
use spacetimedb_sdk::{DbContext, Identity, Table, TableWithPrimaryKey};
use std::sync::{Arc, Mutex};

const HOST: &str = "http://localhost:3000";
const DB_NAME: &str = "slop-art-online";

fn main() {
    App::new()
        .add_plugins(DefaultPlugins)
        .init_resource::<PlayerEventQueue>()
        .add_systems(Startup, (setup_camera, connect_spacetimedb))
        .add_systems(Update, (tick_spacetimedb, sync_players).chain())
        .run();
}

// --- SpacetimeDB ---

#[derive(Resource, Default, Clone)]
struct PlayerEventQueue(Arc<Mutex<Vec<PlayerEvent>>>);

enum PlayerEvent {
    Inserted(Player),
    Updated(Player),
    Deleted(Player),
}

fn connect_spacetimedb(mut commands: Commands, queue: Res<PlayerEventQueue>) {
    let q_insert = queue.clone();
    let q_update = queue.clone();
    let q_delete = queue.clone();

    let conn = DbConnection::builder()
        .with_uri(HOST)
        .with_database_name(DB_NAME)
        .on_connect(|ctx: &DbConnection, _identity, _token| {
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
        q_insert
            .0
            .lock()
            .unwrap()
            .push(PlayerEvent::Inserted(row.clone()));
    });
    conn.db
        .player()
        .on_update(move |_, _old: &Player, new: &Player| {
            q_update
                .0
                .lock()
                .unwrap()
                .push(PlayerEvent::Updated(new.clone()));
        });
    conn.db.player().on_delete(move |_, row: &Player| {
        q_delete
            .0
            .lock()
            .unwrap()
            .push(PlayerEvent::Deleted(row.clone()));
    });

    commands.insert_resource(SpacetimeDb(conn));
}

fn tick_spacetimedb(conn: Res<SpacetimeDb>) {
    if let Err(e) = conn.0.frame_tick() {
        error!("SpacetimeDB tick error: {e}");
    }
}

// --- Players ---

#[derive(Resource)]
struct SpacetimeDb(DbConnection);

#[derive(Component)]
struct PlayerId(Identity);

fn sync_players(
    mut commands: Commands,
    queue: Res<PlayerEventQueue>,
    mut players: Query<(Entity, &PlayerId, &mut Transform)>,
) {
    let mut events = queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            PlayerEvent::Inserted(player) => {
                commands.spawn((
                    PlayerId(player.identity),
                    Sprite {
                        color: Color::WHITE,
                        custom_size: Some(Vec2::splat(32.0)),
                        ..default()
                    },
                    Transform::from_xyz(player.position.x, player.position.y, 0.0),
                ));
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

// --- Camera ---

fn setup_camera(mut commands: Commands) {
    commands.spawn(Camera2d::default());
}
