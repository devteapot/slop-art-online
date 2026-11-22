//! NPC-MEASURE (branch npc-measure only; docs/NPC_CLIENT_SERVICE.md): the authority's side of an NPC
//! body service, the smallest prototype that measures it. Behind the `npc_external_on` law (off):
//!
//! - `npc_external_set` (admin) lists the characters a service drives (`npc_external`);
//! - their graphs are then not evaluated (`brain::evaluate` returns at once);
//! - `npc_intents` (admin, standing in for the service's own identity) takes one batch of intents
//!   for many characters in one transaction, and applies each through the same functions as a
//!   player's `human_move`, `use_skill` and `release_skill`: the same checks, rates, costs and
//!   effects. A refused intent is recorded and told as a player's is; the batch goes on.
//!
//! Not measured here and needed for real use: a service identity of its own instead of the admin,
//! per-intent rollback (a player's failed call rolls its own writes back; here an intent that fails
//! after writing keeps what it wrote), and the NPCs' perceived sets (the relay's).

use crate::common;
use crate::tables::*;
use spacetimedb::{ReducerContext, SpacetimeType, Table};

/// One intent for one character: `kind` 0 a move (`x`, `y` a direction, 0,0 to stop; `run`), 1 a
/// skill on the bar (`skill`, `target`, aim `x`, `y`), 2 letting go of a held skill (`skill`).
#[derive(SpacetimeType, Clone, Debug)]
pub struct NpcIntent {
    pub character: u32,
    pub kind: u8,
    pub skill: String,
    pub target: u32,
    pub x: f32,
    pub y: f32,
    pub run: bool,
}

/// Whether `id` is driven from outside now: the law holds and the character is listed.
pub fn external(ctx: &ReducerContext, id: u32) -> bool {
    common::laws(ctx).npc_external_on && ctx.db.npc_external().id().find(id).is_some()
}

/// List (`on`) or unlist characters as driven by the NPC body service.
#[spacetimedb::reducer]
pub fn npc_external_set(ctx: &ReducerContext, ids: Vec<u32>, on: bool) -> Result<(), String> {
    crate::require_admin(ctx)?;
    for id in ids {
        let listed = ctx.db.npc_external().id().find(id).is_some();
        if on && !listed && ctx.db.character().id().find(id).is_some_and(|c| c.alive) {
            ctx.db.npc_external().insert(NpcExternal { id });
        } else if !on && listed {
            ctx.db.npc_external().id().delete(id);
        }
    }
    Ok(())
}

/// One batch of intents from the NPC body service: one transaction for many characters, as a
/// tick's worth of players' keys would be many. Each goes through the player's own input path.
#[spacetimedb::reducer]
pub fn npc_intents(ctx: &ReducerContext, batch: Vec<NpcIntent>) -> Result<(), String> {
    let _span = common::span("npc_intents");
    crate::require_admin(ctx)?;
    crate::floor::ready(ctx)?;
    if !common::laws(ctx).npc_external_on {
        return Err("no NPC body service in this world (npc_external_on is off)".into());
    }
    common::diag(|| "npc:batches", 1);
    common::diag(|| "npc:intents", batch.len() as u64);
    for i in batch {
        let Some(me) = ctx.db.character().id().find(i.character).filter(|c| c.alive && ctx.db.npc_external().id().find(c.id).is_some()) else {
            common::diag(|| "npc:not_driven", 1);
            continue;
        };
        let done = match i.kind {
            0 => crate::human_move_as(ctx, me, i.x, i.y, i.run),
            1 => crate::combat::use_skill_as(ctx, me, i.skill, i.target, i.x, i.y, "npc"),
            2 => crate::combat::release_skill_as(ctx, me, i.skill),
            _ => Err("unknown intent".into()),
        };
        if done.is_err() {
            common::diag(|| "npc:refused", 1);
        }
    }
    Ok(())
}
