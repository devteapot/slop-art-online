use spacetimedb::{Identity, ReducerContext, ScheduleAt, SpacetimeType, Table};
use spacetimedb::rand::Rng;
use std::time::Duration;

const WORLD_MIN: f32 = -500.0;
const WORLD_MAX: f32 = 500.0;
const NPC_MOVE_RANGE: f32 = 50.0;
const NPC_TICK_MS: u64 = 500;

#[derive(SpacetimeType, Clone, Debug)]
pub struct Position {
    pub x: f32,
    pub y: f32,
}

#[spacetimedb::table(accessor = player, public)]
pub struct Player {
    #[primary_key]
    pub identity: Identity,
    pub position: Position,
}

#[spacetimedb::table(accessor = npc, public)]
pub struct Npc {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub position: Position,
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
    // Cancel any existing schedules to avoid duplicates
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
    });
}

#[spacetimedb::reducer(client_connected)]
pub fn identity_connected(ctx: &ReducerContext) {
    ctx.db.player().insert(Player {
        identity: ctx.sender(),
        position: Position { x: 0.0, y: 0.0 },
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
