//! Gaze intent and sweep-confirmed owner projection.

use crate::common;
use crate::tables::CharacterSenses;
use living_rules::sight::{GazeBand, Senses};
use spacetimedb::{ReducerContext, Table, ViewContext};

const CHANGE_INTERVAL_MS: u64 = 250;

#[spacetimedb::table(accessor = attention)]
pub struct Attention {
    #[primary_key]
    pub id: u32,
    pub band: u8,
    pub accepted_ms: u64,
}

/// The caller has resolved and authorized the living character.
pub fn set(ctx: &ReducerContext, id: u32, band: GazeBand, now: u64) -> Result<(), String> {
    if !common::laws(ctx).gaze_on {
        return Err("gaze is disabled in this world".into());
    }
    let current = ctx.db.attention().id().find(id);
    let band = band as u8;
    if current.as_ref().map_or(GazeBand::Middle as u8, |row| row.band) == band {
        return Ok(());
    }
    if current.as_ref().is_some_and(|row| now.saturating_sub(row.accepted_ms) < CHANGE_INTERVAL_MS) {
        return Err("gaze changed less than 250 ms ago".into());
    }
    let row = Attention { id, band, accepted_ms: now };
    if current.is_some() {
        ctx.db.attention().id().update(row);
    } else {
        ctx.db.attention().insert(row);
    }
    common::invalidate_senses(id);
    Ok(())
}

pub fn band(ctx: &ReducerContext, id: u32) -> GazeBand {
    ctx.db.attention().id().find(id).and_then(|r| GazeBand::try_from(r.band).ok()).unwrap_or_default()
}

#[derive(Clone, Debug)]
#[spacetimedb::table(accessor = applied_gaze)]
pub struct AppliedGaze {
    #[primary_key]
    pub id: u32,
    pub band: u8,
    pub ceiling: f32,
    pub ground: f32,
    pub senses: CharacterSenses,
}

pub fn project(ctx: &ReducerContext, id: u32, senses: &Senses, now: u64) {
    let rows = ctx.db.applied_gaze();
    let Some(gaze) = senses.gaze else { return };
    let current = rows.id().find(id);
    let mut senses = CharacterSenses::of(id, senses);
    let band = gaze.band as u8;
    if current.as_ref().is_some_and(|r| r.band == band && r.ceiling == gaze.ceiling && r.ground == gaze.ground && r.senses.same(&senses)) {
        return;
    }
    senses.at_ms = now;
    let row = AppliedGaze { id, band, ceiling: gaze.ceiling, ground: gaze.ground, senses };
    if current.is_some() {
        rows.id().update(row);
    } else {
        rows.insert(row);
    }
}

// Installs are rare; disabling gaze revokes old sweep confirmations together.
pub fn clear_projection(ctx: &ReducerContext) {
    for id in ctx.db.applied_gaze().iter().map(|row| row.id).collect::<Vec<_>>() {
        ctx.db.applied_gaze().id().delete(id);
    }
}

pub fn forget(ctx: &ReducerContext, id: u32) {
    ctx.db.attention().id().delete(id);
    ctx.db.applied_gaze().id().delete(id);
    common::invalidate_senses(id);
}

/// Sweep-confirmed senses in gaze-enabled worlds. Existing my_senses subscribers retain
/// their original row shape. The sender can only see their own character's projection.
#[spacetimedb::view(accessor = my_senses_v2, public, primary_key = id)]
pub fn my_senses_v2(ctx: &ViewContext) -> Vec<AppliedGaze> {
    crate::perception::living(ctx).and_then(|c| ctx.db.applied_gaze().id().find(c.id)).into_iter().collect()
}
