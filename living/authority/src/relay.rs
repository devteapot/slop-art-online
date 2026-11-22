//! RELAY_PROTOTYPE (branch `relay-proto` only, never for main; docs/RELAY_PROTOTYPE.md): with
//! the `relay_on` law, a fight event is written once here, a private event table read by the
//! delivery relay (the owner's trusted connection), in place of each onlooker's feed rows.

use spacetimedb::{ReducerContext, Table};

/// One fight event as `combat::show` sees it (`combat::Seen` less its free text): the relay shows
/// it to each viewer whose perceived set holds the actor or the target.
#[spacetimedb::table(accessor = relay_event, event)]
pub struct RelayEvent {
    pub kind: u8,
    pub actor: u32,
    pub target: u32,
    pub skill: u8,
    pub x: f32,
    pub y: f32,
    pub amount: f32,
    pub ms: u32,
}

pub fn event(ctx: &ReducerContext, ev: &crate::combat::Seen) {
    ctx.db.relay_event().insert(RelayEvent { kind: ev.kind, actor: ev.actor, target: ev.target, skill: ev.skill, x: ev.at.0, y: ev.at.1, amount: ev.amount, ms: ev.ms });
}
