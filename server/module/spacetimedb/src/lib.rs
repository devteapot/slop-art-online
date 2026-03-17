use spacetimedb::{Identity, ReducerContext, SpacetimeType, Table};

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

#[spacetimedb::reducer(init)]
pub fn init(_ctx: &ReducerContext) {}

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
        position: Position { x, y },
        ..player
    });
    Ok(())
}
