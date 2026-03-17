use spacetimedb::{Identity, ReducerContext, ScheduleAt, SpacetimeType, Table};
use spacetimedb::rand::Rng;
use std::time::Duration;

const WORLD_MIN: f32 = -500.0;
const WORLD_MAX: f32 = 500.0;
const NPC_MOVE_RANGE: f32 = 50.0;
const NPC_TICK_MS: u64 = 500;
const MAX_HEALTH: i32 = 100;
const ATTACK_DAMAGE: i32 = 10;
const ATTACK_RANGE: f32 = 100.0;

#[derive(SpacetimeType, Clone, Debug)]
pub struct Position {
    pub x: f32,
    pub y: f32,
}

impl Position {
    fn distance_to(&self, other: &Position) -> f32 {
        let dx = self.x - other.x;
        let dy = self.y - other.y;
        (dx * dx + dy * dy).sqrt()
    }
}

#[spacetimedb::table(accessor = player, public)]
pub struct Player {
    #[primary_key]
    pub identity: Identity,
    pub position: Position,
    pub health: i32,
}

#[spacetimedb::table(accessor = npc, public)]
pub struct Npc {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub position: Position,
    pub health: i32,
}

#[spacetimedb::table(accessor = npc_tick_schedule, scheduled(tick_npcs))]
pub struct NpcTickSchedule {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}

#[spacetimedb::reducer(init)]
pub fn init(ctx: &ReducerContext) {
    schedule_next_npc_tick(ctx);
}

#[spacetimedb::reducer]
pub fn start_npc_ticker(ctx: &ReducerContext) {
    for s in ctx.db.npc_tick_schedule().iter() {
        ctx.db.npc_tick_schedule().scheduled_id().delete(&s.scheduled_id);
    }
    schedule_next_npc_tick(ctx);
}

fn schedule_next_npc_tick(ctx: &ReducerContext) {
    let next = ctx.timestamp + Duration::from_millis(NPC_TICK_MS);
    ctx.db.npc_tick_schedule().insert(NpcTickSchedule {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(next),
    });
}

#[spacetimedb::reducer]
pub fn tick_npcs(ctx: &ReducerContext, _schedule: NpcTickSchedule) {
    for npc in ctx.db.npc().iter() {
        let dx = (ctx.rng().gen::<f32>() * 2.0 - 1.0) * NPC_MOVE_RANGE;
        let dy = (ctx.rng().gen::<f32>() * 2.0 - 1.0) * NPC_MOVE_RANGE;
        let new_x = (npc.position.x + dx).clamp(WORLD_MIN, WORLD_MAX);
        let new_y = (npc.position.y + dy).clamp(WORLD_MIN, WORLD_MAX);
        ctx.db.npc().id().update(Npc {
            position: Position { x: new_x, y: new_y },
            ..npc
        });
    }
    schedule_next_npc_tick(ctx);
}

#[spacetimedb::reducer]
pub fn spawn_npc(ctx: &ReducerContext, x: f32, y: f32) {
    ctx.db.npc().insert(Npc {
        id: 0,
        position: Position { x: x.clamp(WORLD_MIN, WORLD_MAX), y: y.clamp(WORLD_MIN, WORLD_MAX) },
        health: MAX_HEALTH,
    });
}

#[spacetimedb::reducer(client_connected)]
pub fn identity_connected(ctx: &ReducerContext) {
    ctx.db.player().insert(Player {
        identity: ctx.sender(),
        position: Position { x: 0.0, y: 0.0 },
        health: MAX_HEALTH,
    });
}

#[spacetimedb::reducer(client_disconnected)]
pub fn identity_disconnected(ctx: &ReducerContext) {
    ctx.db.player().identity().delete(&ctx.sender());
}

#[spacetimedb::reducer]
pub fn move_player(ctx: &ReducerContext, x: f32, y: f32) -> Result<(), String> {
    let player = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Player not found")?;
    ctx.db.player().identity().update(Player {
        position: Position {
            x: x.clamp(WORLD_MIN, WORLD_MAX),
            y: y.clamp(WORLD_MIN, WORLD_MAX),
        },
        ..player
    });
    Ok(())
}

#[spacetimedb::reducer]
pub fn attack_player(ctx: &ReducerContext, target: Identity) -> Result<(), String> {
    let attacker = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Attacker not found")?;
    let mut target_player = ctx.db.player().identity().find(&target)
        .ok_or("Target not found")?;

    if attacker.position.distance_to(&target_player.position) > ATTACK_RANGE {
        return Err("Target out of range".to_string());
    }

    target_player.health -= ATTACK_DAMAGE;

    if target_player.health <= 0 {
        // Respawn at origin with full health
        ctx.db.player().identity().update(Player {
            position: Position { x: 0.0, y: 0.0 },
            health: MAX_HEALTH,
            ..target_player
        });
    } else {
        ctx.db.player().identity().update(target_player);
    }

    Ok(())
}

#[spacetimedb::reducer]
pub fn attack_npc(ctx: &ReducerContext, target_id: u64) -> Result<(), String> {
    let attacker = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Attacker not found")?;
    let target_npc = ctx.db.npc().id().find(&target_id)
        .ok_or("NPC not found")?;

    if attacker.position.distance_to(&target_npc.position) > ATTACK_RANGE {
        return Err("Target out of range".to_string());
    }

    let new_health = target_npc.health - ATTACK_DAMAGE;

    if new_health <= 0 {
        ctx.db.npc().id().delete(&target_id);
    } else {
        ctx.db.npc().id().update(Npc {
            health: new_health,
            ..target_npc
        });
    }

    Ok(())
}
