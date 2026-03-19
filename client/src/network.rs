use bevy::prelude::*;
use shared::module_bindings::join_game_reducer::join_game;
use shared::module_bindings::{
    ActiveSkill, ActiveSkillTableAccess, DbConnection, Npc, NpcTableAccess, Player, PlayerSkill,
    PlayerSkillTableAccess, PlayerTableAccess, SkillAttributes, SkillAttributesTableAccess,
    SkillCooldown, SkillCooldownTableAccess, SkillDef, SkillDefTableAccess,
};
use spacetimedb_sdk::{DbContext, Identity, Table, TableWithPrimaryKey};
use std::sync::{Arc, Mutex};

use crate::constants::{DB_NAME, HOST};

// --- Connection resource ---

#[derive(Resource)]
pub struct SpacetimeDb(pub DbConnection);

// --- Local identity ---

#[derive(Resource, Default, Clone)]
pub struct LocalIdentity(pub Arc<Mutex<Option<Identity>>>);

// --- Event types ---

pub enum PlayerEvent {
    Inserted(Player),
    Updated(Player),
    Deleted(Player),
}

pub enum NpcEvent {
    Inserted(Npc),
    Updated(Npc),
    Deleted(Npc),
}

pub enum PlayerSkillEvent {
    Inserted(PlayerSkill),
    Updated(PlayerSkill),
    Deleted(PlayerSkill),
}

pub enum SkillDefEvent {
    Inserted(SkillDef),
}

pub enum SkillAttributesEvent {
    Inserted(SkillAttributes),
    Updated(SkillAttributes),
}

pub enum SkillCooldownEvent {
    Inserted(SkillCooldown),
    Deleted(SkillCooldown),
}

pub enum ActiveSkillEvent {
    Inserted(ActiveSkill),
    Deleted(ActiveSkill),
}

// --- Event queues ---

#[derive(Resource, Default, Clone)]
pub struct PlayerEventQueue(pub Arc<Mutex<Vec<PlayerEvent>>>);

#[derive(Resource, Default, Clone)]
pub struct NpcEventQueue(pub Arc<Mutex<Vec<NpcEvent>>>);

#[derive(Resource, Default, Clone)]
pub struct PlayerSkillEventQueue(pub Arc<Mutex<Vec<PlayerSkillEvent>>>);

#[derive(Resource, Default, Clone)]
pub struct SkillDefEventQueue(pub Arc<Mutex<Vec<SkillDefEvent>>>);

#[derive(Resource, Default, Clone)]
pub struct SkillAttributesEventQueue(pub Arc<Mutex<Vec<SkillAttributesEvent>>>);

#[derive(Resource, Default, Clone)]
pub struct SkillCooldownEventQueue(pub Arc<Mutex<Vec<SkillCooldownEvent>>>);

#[derive(Resource, Default, Clone)]
pub struct ActiveSkillEventQueue(pub Arc<Mutex<Vec<ActiveSkillEvent>>>);

// --- Systems ---

pub fn connect_spacetimedb(
    mut commands: Commands,
    player_queue: Res<PlayerEventQueue>,
    npc_queue: Res<NpcEventQueue>,
    skill_queue: Res<PlayerSkillEventQueue>,
    skill_def_queue: Res<SkillDefEventQueue>,
    skill_attrs_queue: Res<SkillAttributesEventQueue>,
    skill_cd_queue: Res<SkillCooldownEventQueue>,
    active_skill_queue: Res<ActiveSkillEventQueue>,
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
    let as_insert = active_skill_queue.clone();
    let as_delete = active_skill_queue.clone();
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
                    "SELECT * FROM active_skill",
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
    conn.db.active_skill().on_insert(move |_, row: &ActiveSkill| {
        as_insert.0.lock().unwrap().push(ActiveSkillEvent::Inserted(row.clone()));
    });
    conn.db.active_skill().on_delete(move |_, row: &ActiveSkill| {
        as_delete.0.lock().unwrap().push(ActiveSkillEvent::Deleted(row.clone()));
    });

    commands.insert_resource(SpacetimeDb(conn));
}

pub fn tick_spacetimedb(conn: Res<SpacetimeDb>) {
    if let Err(e) = conn.0.frame_tick() {
        error!("SpacetimeDB tick error: {e}");
    }
}

pub fn to_world_pos(pos: &shared::module_bindings::Position) -> bevy::math::Vec3 {
    bevy::math::Vec3::new(pos.x, pos.y, pos.z)
}
