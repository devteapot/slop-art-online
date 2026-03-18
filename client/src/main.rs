use bevy::dev_tools::fps_overlay::{FpsOverlayConfig, FpsOverlayPlugin};
use bevy::prelude::*;
use bevy_voxel_world::prelude::*;
use shared::module_bindings::attack_npc_reducer::attack_npc;
use shared::module_bindings::attack_player_reducer::attack_player;
use shared::module_bindings::join_game_reducer::join_game;
use shared::module_bindings::move_player_reducer::move_player;
use shared::module_bindings::allocate_skill_point_reducer::allocate_skill_point;
use shared::module_bindings::use_skill_reducer::use_skill;
use shared::module_bindings::{
    DbConnection, Npc, NpcTableAccess, Player, PlayerSkill, PlayerSkillTableAccess,
    PlayerTableAccess, SkillAttributes, SkillAttributesTableAccess, SkillCooldown,
    SkillCooldownTableAccess, SkillDef, SkillDefTableAccess,
};
use spacetimedb_sdk::{DbContext, Identity, Table, TableWithPrimaryKey, Timestamp};
use std::sync::{Arc, Mutex};

const HOST: &str = "http://localhost:3000";
const DB_NAME: &str = "slop-art-online";
const POINTS_PER_LEVEL: i32 = 5;

/// (server_key, display_label)  — server_key must match allocate_skill_point reducer
const ATTRS: &[(&str, &str)] = &[
    ("damage",           "Damage"),
    ("cooldown",         "Cooldown"),
    ("aoe",              "AOE"),
    ("range",            "Range"),
    ("duration",         "Duration"),
    ("projectile_count", "Projectiles"),
    ("knockback",        "Knockback"),
    ("resource_cost",    "Resource Cost"),
    ("cast_speed",       "Cast Speed"),
];
const MOVE_SPEED: f32 = 20.0;
const ATTACK_RANGE: f32 = 3.0;
const PLAYER_Y: f32 = 1.0; // height above terrain
const MAX_HEALTH: f32 = 100.0;
const HEALTH_BAR_WIDTH: f32 = 1.0;
const HEALTH_BAR_HEIGHT: f32 = 0.1;
const HEALTH_BAR_Y_OFFSET: f32 = 1.8; // above capsule top
const JUMP_HEIGHT: f32 = 3.0;
const JUMP_DURATION: f32 = 0.55;
const DASH_DISTANCE: f32 = 8.0;

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
        .init_resource::<PlayerSkillEventQueue>()
        .init_resource::<SkillDefEventQueue>()
        .init_resource::<SkillAttributesEventQueue>()
        .init_resource::<SkillCooldownEventQueue>()
        .init_resource::<LocalSkills>()
        .init_resource::<LocalPlayerStats>()
        .init_resource::<LocalSkillData>()
        .init_resource::<LocalCooldowns>()
        .init_resource::<SelectedSkill>()
        .init_resource::<SkillNameMap>()
        .init_resource::<MobilitySkillIds>()
        .init_resource::<PlayerFacing>()
        .init_resource::<JumpState>()
        .init_resource::<LocalIdentity>()
        .add_systems(Startup, (setup, connect_spacetimedb, setup_hud))
        .add_systems(Update, (
            tick_spacetimedb,
            sync_players,
            sync_npcs,
            sync_player_skills,
            sync_skill_defs,
            sync_skill_attrs,
            sync_skill_cooldowns,
            move_local_player,
            use_skill_input,
            mobility_input,
            apply_jump_anim,
            follow_camera,
            attack,
            update_health_bars,
            billboard_health_bars,
            update_hud,
            handle_skill_slot_clicks,
            handle_allocate_clicks,
            handle_close_click,
            update_skill_detail_panel,
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

enum PlayerSkillEvent {
    Inserted(PlayerSkill),
    Updated(PlayerSkill),
    Deleted(PlayerSkill),
}

enum SkillAttributesEvent {
    Inserted(SkillAttributes),
    Updated(SkillAttributes),
}

#[derive(Resource, Default, Clone)]
struct SkillAttributesEventQueue(Arc<Mutex<Vec<SkillAttributesEvent>>>);

#[derive(Resource, Default)]
struct LocalSkillData {
    levels: std::collections::HashMap<u64, i32>,
    attrs:  std::collections::HashMap<u64, SkillAttributes>,
}

#[derive(Resource, Default)]
struct SelectedSkill(Option<u64>);

#[derive(Resource, Default, Clone)]
struct PlayerSkillEventQueue(Arc<Mutex<Vec<PlayerSkillEvent>>>);

/// Ordered list of skill IDs the local player has (sorted by skill_id -> maps to keys 1–4).
#[derive(Resource, Default)]
struct LocalSkills(Vec<u64>);

enum SkillDefEvent { Inserted(SkillDef) }

enum SkillCooldownEvent {
    Inserted(SkillCooldown),
    Deleted(SkillCooldown),
}

#[derive(Resource, Default, Clone)]
struct SkillCooldownEventQueue(Arc<Mutex<Vec<SkillCooldownEvent>>>);

/// skill_id → ready_at (micros since unix epoch)
#[derive(Resource, Default)]
struct LocalCooldowns(std::collections::HashMap<u64, i64>);

#[derive(Resource, Default)]
struct MobilitySkillIds {
    jump: Option<u64>,
    dash: Option<u64>,
}

/// XZ facing direction from last movement input, used for dash direction.
#[derive(Resource, Default)]
struct PlayerFacing(Vec2);

#[derive(Resource, Default, Clone)]
struct SkillDefEventQueue(Arc<Mutex<Vec<SkillDefEvent>>>);

#[derive(Resource, Default)]
struct SkillNameMap(std::collections::HashMap<u64, String>);

#[derive(Resource)]
struct LocalPlayerStats {
    health: i32, max_health: i32,
    mana: i32,   max_mana: i32,
    stamina: i32, max_stamina: i32,
}

impl Default for LocalPlayerStats {
    fn default() -> Self {
        Self { health: 0, max_health: 100, mana: 0, max_mana: 100, stamina: 0, max_stamina: 100 }
    }
}

#[derive(Clone, Copy)]
enum StatKind { Health, Mana, Stamina }

#[derive(Component)]
struct StatBarFill(StatKind);

#[derive(Component)]
struct SkillSlotLabel(usize);

#[derive(Component)]
struct SkillSlotButton(usize);

#[derive(Component)]
struct SkillDetailPanel;

#[derive(Component)]
struct SkillDetailTitle;

#[derive(Component)]
struct SkillDetailPoints;

#[derive(Component)]
struct SkillAttrRow(usize);

#[derive(Component)]
struct AllocateButton(usize);

#[derive(Component)]
struct SkillDetailClose;

#[derive(Component)]
struct MobilitySlotLabel(usize); // 0 = Jump, 1 = Dash

#[derive(Resource, Default)]
struct JumpState {
    elapsed: f32,
    active: bool,
}

fn connect_spacetimedb(
    mut commands: Commands,
    player_queue: Res<PlayerEventQueue>,
    npc_queue: Res<NpcEventQueue>,
    skill_queue: Res<PlayerSkillEventQueue>,
    skill_def_queue: Res<SkillDefEventQueue>,
    skill_attrs_queue: Res<SkillAttributesEventQueue>,
    skill_cd_queue: Res<SkillCooldownEventQueue>,
    local_identity: Res<LocalIdentity>,
) {
    let q_insert = player_queue.clone();
    let q_update = player_queue.clone();
    let q_delete = player_queue.clone();
    let nq_insert = npc_queue.clone();
    let nq_update = npc_queue.clone();
    let nq_delete = npc_queue.clone();
    let sq_insert = skill_queue.clone();
    let sq_update = skill_queue.clone();
    let sq_delete = skill_queue.clone();
    let sd_insert = skill_def_queue.clone();
    let sa_insert = skill_attrs_queue.clone();
    let sa_update = skill_attrs_queue.clone();
    let sc_insert = skill_cd_queue.clone();
    let sc_update = skill_cd_queue.clone();
    let sc_delete = skill_cd_queue.clone();
    let identity_store = local_identity.clone();

    let conn = DbConnection::builder()
        .with_uri(HOST)
        .with_database_name(DB_NAME)
        .on_connect(move |ctx: &DbConnection, identity, _token| {
            *identity_store.0.lock().unwrap() = Some(identity);
            let _ = ctx.reducers.join_game();
            ctx.subscription_builder()
                .on_applied(|_| info!("Subscribed"))
                .subscribe([
                    "SELECT * FROM player",
                    "SELECT * FROM npc",
                    "SELECT * FROM skill_def",
                    "SELECT * FROM player_skill",
                    "SELECT * FROM skill_attributes",
                    "SELECT * FROM skill_cooldown",
                ]);
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
    conn.db.player_skill().on_insert(move |_, row: &PlayerSkill| {
        sq_insert.0.lock().unwrap().push(PlayerSkillEvent::Inserted(row.clone()));
    });
    conn.db.player_skill().on_update(move |_, _old: &PlayerSkill, new: &PlayerSkill| {
        sq_update.0.lock().unwrap().push(PlayerSkillEvent::Updated(new.clone()));
    });
    conn.db.player_skill().on_delete(move |_, row: &PlayerSkill| {
        sq_delete.0.lock().unwrap().push(PlayerSkillEvent::Deleted(row.clone()));
    });
    conn.db.skill_def().on_insert(move |_, row: &SkillDef| {
        sd_insert.0.lock().unwrap().push(SkillDefEvent::Inserted(row.clone()));
    });
    conn.db.skill_attributes().on_insert(move |_, row: &SkillAttributes| {
        sa_insert.0.lock().unwrap().push(SkillAttributesEvent::Inserted(row.clone()));
    });
    conn.db.skill_attributes().on_update(move |_, _old: &SkillAttributes, new: &SkillAttributes| {
        sa_update.0.lock().unwrap().push(SkillAttributesEvent::Updated(new.clone()));
    });
    conn.db.skill_cooldown().on_insert(move |_, row: &SkillCooldown| {
        sc_insert.0.lock().unwrap().push(SkillCooldownEvent::Inserted(row.clone()));
    });
    conn.db.skill_cooldown().on_update(move |_, _old: &SkillCooldown, new: &SkillCooldown| {
        // Server UPDATEs the row on every use after the first, so treat it as Inserted.
        sc_update.0.lock().unwrap().push(SkillCooldownEvent::Inserted(new.clone()));
    });
    conn.db.skill_cooldown().on_delete(move |_, row: &SkillCooldown| {
        sc_delete.0.lock().unwrap().push(SkillCooldownEvent::Deleted(row.clone()));
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
                let color = if is_local { Color::srgb(0.4, 0.8, 1.0) } else { Color::WHITE };
                let mut entity_cmd = commands.spawn((
                    PlayerId(player.identity),
                    Mesh3d(meshes.add(Capsule3d::new(0.4, 1.0))),
                    MeshMaterial3d(materials.add(StandardMaterial {
                        base_color: color,
                        ..default()
                    })),
                    Transform::from_translation(to_world_pos(&player.position)),
                ));
                if is_local {
                    entity_cmd.insert(LocalPlayer);
                }
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

// --- HUD ---

fn setup_hud(mut commands: Commands) {
    commands.spawn(Node {
        position_type: PositionType::Absolute,
        bottom: Val::Px(16.0),
        left: Val::Px(16.0),
        flex_direction: FlexDirection::Column,
        row_gap: Val::Px(4.0),
        ..default()
    }).with_children(|col| {
        spawn_stat_bar(col, "HP", Color::srgb(0.8, 0.15, 0.15), StatKind::Health);
        spawn_stat_bar(col, "MP", Color::srgb(0.2, 0.45, 0.9),  StatKind::Mana);
        spawn_stat_bar(col, "SP", Color::srgb(0.2, 0.75, 0.35), StatKind::Stamina);

        // Combat skill bar
        col.spawn(Node {
            flex_direction: FlexDirection::Row,
            column_gap: Val::Px(4.0),
            margin: UiRect::top(Val::Px(10.0)),
            ..default()
        }).with_children(|row| {
            for i in 0..4 {
                row.spawn((
                    Button,
                    SkillSlotButton(i),
                    Node {
                        width: Val::Px(90.0),
                        height: Val::Px(30.0),
                        justify_content: JustifyContent::Center,
                        align_items: AlignItems::Center,
                        ..default()
                    },
                    BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.65)),
                )).with_children(|slot| {
                    slot.spawn((
                        SkillSlotLabel(i),
                        Text::new(format!("[{}] ---", i + 1)),
                        TextFont { font_size: 11.0, ..default() },
                        TextColor(Color::srgb(0.75, 0.75, 0.75)),
                    ));
                });
            }
        });

        // Mobility skill bar
        col.spawn(Node {
            flex_direction: FlexDirection::Row,
            column_gap: Val::Px(4.0),
            margin: UiRect::top(Val::Px(2.0)),
            ..default()
        }).with_children(|row| {
            for (i, key_label) in ["[Space]", "[Shift]"].iter().enumerate() {
                row.spawn((
                    Node {
                        width: Val::Px(90.0),
                        height: Val::Px(26.0),
                        justify_content: JustifyContent::Center,
                        align_items: AlignItems::Center,
                        ..default()
                    },
                    BackgroundColor(Color::srgba(0.0, 0.1, 0.2, 0.65)),
                )).with_children(|slot| {
                    slot.spawn((
                        MobilitySlotLabel(i),
                        Text::new(format!("{key_label} ---")),
                        TextFont { font_size: 10.0, ..default() },
                        TextColor(Color::srgb(0.6, 0.85, 1.0)),
                    ));
                });
            }
        });
    });

    // --- Skill detail panel (hidden by default) ---
    commands.spawn((
        SkillDetailPanel,
        Visibility::Hidden,
        Node {
            position_type: PositionType::Absolute,
            right: Val::Px(20.0),
            top: Val::Px(20.0),
            width: Val::Px(320.0),
            flex_direction: FlexDirection::Column,
            row_gap: Val::Px(6.0),
            padding: UiRect::all(Val::Px(12.0)),
            ..default()
        },
        BackgroundColor(Color::srgba(0.05, 0.05, 0.08, 0.92)),
    )).with_children(|panel| {
        // Header row: title + close
        panel.spawn(Node {
            flex_direction: FlexDirection::Row,
            justify_content: JustifyContent::SpaceBetween,
            align_items: AlignItems::Center,
            ..default()
        }).with_children(|hdr| {
            hdr.spawn((
                SkillDetailTitle,
                Text::new("Skill"),
                TextFont { font_size: 16.0, ..default() },
                TextColor(Color::WHITE),
            ));
            hdr.spawn((
                Button,
                SkillDetailClose,
                Node {
                    width: Val::Px(22.0),
                    height: Val::Px(22.0),
                    justify_content: JustifyContent::Center,
                    align_items: AlignItems::Center,
                    ..default()
                },
                BackgroundColor(Color::srgba(0.5, 0.1, 0.1, 0.8)),
            )).with_children(|btn| {
                btn.spawn((
                    Text::new("X"),
                    TextFont { font_size: 13.0, ..default() },
                    TextColor(Color::WHITE),
                ));
            });
        });

        // Points available
        panel.spawn((
            SkillDetailPoints,
            Text::new("Points: 0 / 0"),
            TextFont { font_size: 12.0, ..default() },
            TextColor(Color::srgb(0.8, 0.8, 0.4)),
        ));

        // Separator
        panel.spawn((
            Node {
                width: Val::Percent(100.0),
                height: Val::Px(1.0),
                ..default()
            },
            BackgroundColor(Color::srgba(1.0, 1.0, 1.0, 0.15)),
        ));

        // Attribute rows
        for (i, &(_, label)) in ATTRS.iter().enumerate() {
            panel.spawn(Node {
                flex_direction: FlexDirection::Row,
                justify_content: JustifyContent::SpaceBetween,
                align_items: AlignItems::Center,
                ..default()
            }).with_children(|row| {
                row.spawn((
                    SkillAttrRow(i),
                    Text::new(format!("{label}: 0")),
                    TextFont { font_size: 11.0, ..default() },
                    TextColor(Color::srgb(0.85, 0.85, 0.85)),
                    Node { width: Val::Px(240.0), ..default() },
                ));
                row.spawn((
                    Button,
                    AllocateButton(i),
                    Node {
                        width: Val::Px(26.0),
                        height: Val::Px(20.0),
                        justify_content: JustifyContent::Center,
                        align_items: AlignItems::Center,
                        ..default()
                    },
                    BackgroundColor(Color::srgba(0.2, 0.5, 0.2, 0.85)),
                )).with_children(|btn| {
                    btn.spawn((
                        Text::new("+"),
                        TextFont { font_size: 13.0, ..default() },
                        TextColor(Color::WHITE),
                    ));
                });
            });
        }
    });
}

fn spawn_stat_bar(parent: &mut ChildSpawnerCommands, label: &str, color: Color, kind: StatKind) {
    parent.spawn(Node {
        flex_direction: FlexDirection::Row,
        align_items: AlignItems::Center,
        column_gap: Val::Px(6.0),
        ..default()
    }).with_children(|row: &mut ChildSpawnerCommands| {
        row.spawn((
            Text::new(label),
            TextFont { font_size: 11.0, ..default() },
            TextColor(Color::WHITE),
            Node { width: Val::Px(20.0), ..default() },
        ));
        row.spawn((
            Node {
                width: Val::Px(180.0),
                height: Val::Px(12.0),
                ..default()
            },
            BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.5)),
        )).with_children(|bar: &mut ChildSpawnerCommands| {
            bar.spawn((
                StatBarFill(kind),
                Node {
                    width: Val::Percent(100.0),
                    height: Val::Percent(100.0),
                    ..default()
                },
                BackgroundColor(color),
            ));
        });
    });
}

fn sync_skill_defs(
    queue: Res<SkillDefEventQueue>,
    mut skill_name_map: ResMut<SkillNameMap>,
    mut mobility_ids: ResMut<MobilitySkillIds>,
) {
    let mut events = queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            SkillDefEvent::Inserted(def) => {
                match def.name.as_str() {
                    "Jump" => mobility_ids.jump = Some(def.id),
                    "Dash" => mobility_ids.dash = Some(def.id),
                    _ => {}
                }
                skill_name_map.0.insert(def.id, def.name);
            }
        }
    }
}

fn cooldown_remaining(cooldowns: &LocalCooldowns, skill_id: u64) -> f32 {
    let Some(&ready_at) = cooldowns.0.get(&skill_id) else { return 0.0 };
    let now = Timestamp::now().to_micros_since_unix_epoch();
    ((ready_at - now) as f32 / 1_000_000.0).max(0.0)
}

fn update_hud(
    local_stats: Res<LocalPlayerStats>,
    local_skills: Res<LocalSkills>,
    skill_name_map: Res<SkillNameMap>,
    local_cooldowns: Res<LocalCooldowns>,
    mobility_ids: Res<MobilitySkillIds>,
    mut stat_fills: Query<(&StatBarFill, &mut Node)>,
    mut skill_labels: Query<(&SkillSlotLabel, &mut Text), Without<MobilitySlotLabel>>,
    mut mobility_labels: Query<(&MobilitySlotLabel, &mut Text), Without<SkillSlotLabel>>,
) {
    for (fill, mut node) in &mut stat_fills {
        let ratio = match fill.0 {
            StatKind::Health  => local_stats.health  as f32 / local_stats.max_health.max(1)  as f32,
            StatKind::Mana    => local_stats.mana    as f32 / local_stats.max_mana.max(1)    as f32,
            StatKind::Stamina => local_stats.stamina as f32 / local_stats.max_stamina.max(1) as f32,
        };
        node.width = Val::Percent(ratio.clamp(0.0, 1.0) * 100.0);
    }

    for (slot, mut text) in &mut skill_labels {
        let skill_id = local_skills.0.get(slot.0).copied();
        let name = skill_id
            .and_then(|id| skill_name_map.0.get(&id))
            .map(|s| s.as_str())
            .unwrap_or("---");
        let cd = skill_id.map(|id| cooldown_remaining(&local_cooldowns, id)).unwrap_or(0.0);
        if cd > 0.1 {
            text.0 = format!("[{}] {:.1}s", slot.0 + 1, cd);
        } else {
            text.0 = format!("[{}] {}", slot.0 + 1, name);
        }
    }

    let mob_ids = [mobility_ids.jump, mobility_ids.dash];
    let mob_keys = ["[Space]", "[Shift]"];
    let mob_names = ["Jump", "Dash"];
    for (slot, mut text) in &mut mobility_labels {
        let name = mob_names[slot.0];
        let cd = mob_ids[slot.0].map(|id| cooldown_remaining(&local_cooldowns, id)).unwrap_or(0.0);
        if cd > 0.1 {
            text.0 = format!("{} {:.1}s", mob_keys[slot.0], cd);
        } else {
            text.0 = format!("{} {}", mob_keys[slot.0], name);
        }
    }
}

// --- Skills ---

fn sync_player_skills(
    queue: Res<PlayerSkillEventQueue>,
    local_identity: Res<LocalIdentity>,
    mut local_skills: ResMut<LocalSkills>,
    mut local_skill_data: ResMut<LocalSkillData>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let Some(ref id) = local_id else { return };
    let mut events = queue.0.lock().unwrap();
    let mut changed = false;

    for event in events.drain(..) {
        match event {
            PlayerSkillEvent::Inserted(ps) if &ps.player_identity == id => {
                local_skill_data.levels.insert(ps.skill_id, ps.level);
                if !local_skills.0.contains(&ps.skill_id) {
                    local_skills.0.push(ps.skill_id);
                    changed = true;
                }
            }
            PlayerSkillEvent::Updated(ps) if &ps.player_identity == id => {
                local_skill_data.levels.insert(ps.skill_id, ps.level);
            }
            PlayerSkillEvent::Deleted(ps) if &ps.player_identity == id => {
                local_skill_data.levels.remove(&ps.skill_id);
                local_skills.0.retain(|&s| s != ps.skill_id);
                changed = true;
            }
            _ => {}
        }
    }
    if changed {
        local_skills.0.sort();
    }
}

fn use_skill_input(
    conn: Option<Res<SpacetimeDb>>,
    keys: Res<ButtonInput<KeyCode>>,
    local_player: Query<&Transform, With<LocalPlayer>>,
    local_skills: Res<LocalSkills>,
) {
    let Some(conn) = conn else { return };
    let Ok(transform) = local_player.single() else { return };

    let slot = if keys.just_pressed(KeyCode::Digit1) { Some(0) }
        else if keys.just_pressed(KeyCode::Digit2) { Some(1) }
        else if keys.just_pressed(KeyCode::Digit3) { Some(2) }
        else if keys.just_pressed(KeyCode::Digit4) { Some(3) }
        else { None };

    if let Some(idx) = slot {
        if let Some(&skill_id) = local_skills.0.get(idx) {
            let pos = transform.translation;
            let _ = conn.0.reducers.use_skill(skill_id, pos.x, pos.y, pos.z);
        }
    }
}

// --- Movement ---

fn move_local_player(
    conn: Option<Res<SpacetimeDb>>,
    keys: Res<ButtonInput<KeyCode>>,
    time: Res<Time>,
    player: Query<&Transform, With<LocalPlayer>>,
    mut facing: ResMut<PlayerFacing>,
) {
    let Some(conn) = conn else { return };
    let Ok(transform) = player.single() else { return };

    let mut dir = Vec2::ZERO;
    if keys.pressed(KeyCode::KeyW) || keys.pressed(KeyCode::ArrowUp)    { dir.y -= 1.0; }
    if keys.pressed(KeyCode::KeyS) || keys.pressed(KeyCode::ArrowDown)  { dir.y += 1.0; }
    if keys.pressed(KeyCode::KeyA) || keys.pressed(KeyCode::ArrowLeft)  { dir.x -= 1.0; }
    if keys.pressed(KeyCode::KeyD) || keys.pressed(KeyCode::ArrowRight) { dir.x += 1.0; }

    if dir == Vec2::ZERO { return }

    let dir_norm = dir.normalize();
    facing.0 = dir_norm;

    let delta = dir_norm * MOVE_SPEED * time.delta_secs();
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
    if !keys.just_pressed(KeyCode::KeyE) { return }
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

// --- Skill attributes sync ---

fn sync_skill_attrs(
    queue: Res<SkillAttributesEventQueue>,
    local_identity: Res<LocalIdentity>,
    mut local_skill_data: ResMut<LocalSkillData>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let Some(ref id) = local_id else { return };
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            SkillAttributesEvent::Inserted(attrs) if &attrs.player_identity == id => {
                local_skill_data.attrs.insert(attrs.skill_id, attrs);
            }
            SkillAttributesEvent::Updated(attrs) if &attrs.player_identity == id => {
                local_skill_data.attrs.insert(attrs.skill_id, attrs);
            }
            _ => {}
        }
    }
}

// --- Skill detail panel helpers ---

fn get_attr_pts(attrs: &SkillAttributes, idx: usize) -> i32 {
    match idx {
        0 => attrs.damage_points,
        1 => attrs.cooldown_points,
        2 => attrs.aoe_points,
        3 => attrs.range_points,
        4 => attrs.duration_points,
        5 => attrs.projectile_count_points,
        6 => attrs.knockback_points,
        7 => attrs.resource_cost_points,
        8 => attrs.cast_speed_points,
        _ => 0,
    }
}

fn points_allocated_client(attrs: &SkillAttributes) -> i32 {
    attrs.damage_points + attrs.cooldown_points + attrs.aoe_points + attrs.range_points
        + attrs.duration_points + attrs.projectile_count_points + attrs.knockback_points
        + attrs.resource_cost_points + attrs.cast_speed_points
}

fn attr_display(attr_idx: usize, pts: i32) -> String {
    match attr_idx {
        0 => format!("{} pts -> {} dmg",     pts, 15 + pts * 5),
        1 => format!("{} pts -> {}ms cd",    pts, (3000 - pts * 150).max(500)),
        2 => format!("{} pts -> {:.1} aoe",  pts, pts as f32 * 0.8),
        3 => format!("{} pts -> {:.1} rng",  pts, 5.0 + pts as f32 * 1.5),
        4 => format!("{} pts -> {:.1}s dur", pts, 2.0 + pts as f32 * 0.5),
        5 => format!("{} pts -> {} proj",    pts, 1 + pts),
        6 => format!("{} pts -> {:.1} kb",   pts, pts as f32 * 2.0),
        7 => format!("{} pts -> {} cost",    pts, (20 - pts * 2).max(5)),
        8 => format!("{} pts -> {:.1}x spd", pts, 1.0 + pts as f32 * 0.1),
        _ => String::new(),
    }
}

// --- Skill panel interaction systems ---

fn handle_skill_slot_clicks(
    slots: Query<(&Interaction, &SkillSlotButton), Changed<Interaction>>,
    local_skills: Res<LocalSkills>,
    mut selected: ResMut<SelectedSkill>,
) {
    for (interaction, slot) in &slots {
        if *interaction == Interaction::Pressed {
            selected.0 = local_skills.0.get(slot.0).copied();
        }
    }
}

fn handle_close_click(
    close_btns: Query<&Interaction, (Changed<Interaction>, With<SkillDetailClose>)>,
    mut selected: ResMut<SelectedSkill>,
) {
    for interaction in &close_btns {
        if *interaction == Interaction::Pressed {
            selected.0 = None;
        }
    }
}

fn handle_allocate_clicks(
    alloc_btns: Query<(&Interaction, &AllocateButton), Changed<Interaction>>,
    selected: Res<SelectedSkill>,
    conn: Option<Res<SpacetimeDb>>,
) {
    let Some(conn) = conn else { return };
    let Some(skill_id) = selected.0 else { return };

    for (interaction, btn) in &alloc_btns {
        if *interaction == Interaction::Pressed {
            let attr_key = ATTRS[btn.0].0.to_string();
            let _ = conn.0.reducers.allocate_skill_point(skill_id, attr_key);
        }
    }
}

fn update_skill_detail_panel(
    selected: Res<SelectedSkill>,
    local_skill_data: Res<LocalSkillData>,
    skill_name_map: Res<SkillNameMap>,
    mut panel: Query<&mut Visibility, With<SkillDetailPanel>>,
    mut title: Query<&mut Text, (With<SkillDetailTitle>, Without<SkillDetailPoints>, Without<SkillAttrRow>)>,
    mut points_text: Query<&mut Text, (With<SkillDetailPoints>, Without<SkillDetailTitle>, Without<SkillAttrRow>)>,
    mut attr_rows: Query<(&SkillAttrRow, &mut Text), (Without<SkillDetailTitle>, Without<SkillDetailPoints>)>,
) {
    let Ok(mut vis) = panel.single_mut() else { return };

    let Some(skill_id) = selected.0 else {
        *vis = Visibility::Hidden;
        return;
    };

    *vis = Visibility::Inherited;

    let name = skill_name_map.0.get(&skill_id).map(|s| s.as_str()).unwrap_or("???");
    if let Ok(mut t) = title.single_mut() { t.0 = name.to_string(); }

    let level = local_skill_data.levels.get(&skill_id).copied().unwrap_or(1);
    let total_pts = level * POINTS_PER_LEVEL;

    if let Some(attrs) = local_skill_data.attrs.get(&skill_id) {
        let used = points_allocated_client(attrs);
        let avail = (total_pts - used).max(0);

        if let Ok(mut t) = points_text.single_mut() {
            t.0 = format!("Points: {avail} free / {total_pts} total (lv{level})");
        }

        for (row, mut text) in &mut attr_rows {
            let pts = get_attr_pts(attrs, row.0);
            let label = ATTRS[row.0].1;
            text.0 = format!("{label}: {}", attr_display(row.0, pts));
        }
    } else {
        if let Ok(mut t) = points_text.single_mut() {
            t.0 = format!("Points: {total_pts} total (lv{level})");
        }
    }
}

// --- Skill cooldown sync ---

fn sync_skill_cooldowns(
    queue: Res<SkillCooldownEventQueue>,
    local_identity: Res<LocalIdentity>,
    mobility_ids: Res<MobilitySkillIds>,
    mut local_cooldowns: ResMut<LocalCooldowns>,
    mut jump_state: ResMut<JumpState>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let Some(ref id) = local_id else { return };
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            SkillCooldownEvent::Inserted(cd) if &cd.player_identity == id => {
                if mobility_ids.jump == Some(cd.skill_id) && !jump_state.active {
                    jump_state.active = true;
                    jump_state.elapsed = 0.0;
                }
                local_cooldowns.0.insert(cd.skill_id, cd.ready_at.to_micros_since_unix_epoch());
            }
            SkillCooldownEvent::Deleted(cd) if &cd.player_identity == id => {
                local_cooldowns.0.remove(&cd.skill_id);
            }
            _ => {}
        }
    }
}

// --- Mobility skills ---

fn mobility_input(
    conn: Option<Res<SpacetimeDb>>,
    keys: Res<ButtonInput<KeyCode>>,
    local_player: Query<&Transform, With<LocalPlayer>>,
    mobility_ids: Res<MobilitySkillIds>,
    local_cooldowns: Res<LocalCooldowns>,
    facing: Res<PlayerFacing>,
    jump_state: Res<JumpState>,
) {
    let Some(conn) = conn else { return };
    let Ok(transform) = local_player.single() else { return };
    let pos = transform.translation;

    // Jump — Space (animation starts in sync_skill_cooldowns when server confirms)
    if keys.just_pressed(KeyCode::Space) {
        if let Some(jump_id) = mobility_ids.jump {
            if cooldown_remaining(&local_cooldowns, jump_id) <= 0.0 && !jump_state.active {
                let _ = conn.0.reducers.use_skill(jump_id, pos.x, pos.y, pos.z);
            }
        }
    }

    // Dash — Shift
    let shift = keys.just_pressed(KeyCode::ShiftLeft) || keys.just_pressed(KeyCode::ShiftRight);
    if shift {
        if let Some(dash_id) = mobility_ids.dash {
            if cooldown_remaining(&local_cooldowns, dash_id) <= 0.0 {
                let dir = if facing.0 != Vec2::ZERO { facing.0 } else { Vec2::new(0.0, -1.0) };
                let new_x = pos.x + dir.x * DASH_DISTANCE;
                let new_z = pos.z + dir.y * DASH_DISTANCE;
                let _ = conn.0.reducers.use_skill(dash_id, pos.x, pos.y, pos.z);
                let _ = conn.0.reducers.move_player(new_x, PLAYER_Y, new_z);
            }
        }
    }
}

fn apply_jump_anim(
    time: Res<Time>,
    mut jump_state: ResMut<JumpState>,
    mut players: Query<&mut Transform, With<LocalPlayer>>,
) {
    if !jump_state.active { return }
    let Ok(mut transform) = players.single_mut() else { return };

    jump_state.elapsed += time.delta_secs();
    if jump_state.elapsed >= JUMP_DURATION {
        jump_state.active = false;
        transform.translation.y = PLAYER_Y;
    } else {
        let t = jump_state.elapsed / JUMP_DURATION;
        transform.translation.y = PLAYER_Y + JUMP_HEIGHT * (t * std::f32::consts::PI).sin();
    }
}
