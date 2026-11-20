//! Cover geometry: the private `cover_ground` bands that cover sight compiles its mask from
//! (docs/COVER_SIGHT.md, "Cover geometry").
//!
//! **Only where cover is on.** Sampling the ground at every tile centre is the cost: about
//! 4 × 10³ WASM instructions a tile on the island and up to 10⁴ in a dense city, so 17.5 × 10⁹
//! of the island's `init` and 130 × 10⁹ for the 4096 m megacity, more than one reducer's whole
//! budget. A world whose cover law is on when it is created keeps its bands then (`island::build`
//! in one call; `floor`'s band steps when staged). Any other world keeps none, and pays nothing.
//!
//! **Derived when switched on.** When cover goes on later (`set_world_law`, `install_script`, the
//! end of a staged creation whose law went on meanwhile), [`ensure`] starts `cover_step`, a
//! one-shot scheduled reducer that does one bounded step per call and schedules the next, as
//! staged creation does (`floor.rs`): the land generated again from the `land` row's seed and the
//! full parameters (`land_plan`) in `living_rules::land::Gen`'s steps, then the hosted tiles,
//! checked against the `land` row's tile and height digests (a module whose generator differs
//! refuses, rather than keep other heights), then the bands in batches of
//! [`BANDS_PER_STEP`]. The rows are the ones creation would have kept: the same samples
//! (`cover::ground_range`) and candidates of the same hosted tiles.
//!
//! **In force only when complete.** Until every band is kept, the cover in force is off: the
//! `cover_law` row says so (`common::publish_cover_law`), the map compiles no mask and Shade
//! builds none, so players, minds and clients agree. The last step writes a new law revision, so
//! every cached map compiles its mask, and publishes the row as on.
//!
//! **Where the work lives between steps** is the instance's memory, a cache only (the reducers
//! docs, "Global and Static Variables Are Undefined Behavior"): the `cover_derivation` row and the
//! bands kept are the truth, and a cache that is not this land's or not as far as the row says
//! starts generation again from its first step (deterministic; kept bands are kept).
//!
//! **What it costs a running world.** Each step blocks the module while it runs: land steps up to
//! about 29 × 10⁹ (about 2 s) on the 4096 m megacity, a few × 10⁹ on the island; band steps up to
//! about 11 × 10⁹. Steps are [`STEP_GAP_MS`] apart so ticks run between them. The generation's
//! peak raises the instance's linear memory, which never shrinks (about 60 MB on the island,
//! 210 MB at 4096 m).

use crate::common;
use crate::floor::genesis;
use crate::tables::*;
use living_rules::land::{Gen, Land, LandParams};
use spacetimedb::{ReducerContext, ScheduleAt, Table};
use std::cell::RefCell;

/// Bands (16,384 tiles each) sampled per step: at most about 11 × 10⁹ fuel in the 4096 m
/// megacity's densest rows (measured: 22.1 × 10⁹ for 128 of them), 4.4 × 10⁹ on the island.
pub const BANDS_PER_STEP: usize = 64;
/// Time between a derivation's steps on a running world, so its ticks run between them.
const STEP_GAP_MS: u64 = 100;

/// How far a derivation of this world's cover geometry is (private, one row, `id` 0). Written
/// only when cover is switched on in a world that has no geometry.
#[spacetimedb::table(accessor = cover_derivation)]
pub struct CoverDerivation {
    #[primary_key]
    pub id: u8,
    /// Steps done.
    pub step: u32,
    /// What the last step did; why it stopped (`stopped: …`); `done`.
    pub label: String,
    /// Steps of generation and hosting done in this instance's memory (see the module notes).
    pub generated: u32,
    /// Times generation started over because the instance's memory was lost.
    pub restarts: u32,
    pub started_ms: u64,
    pub updated_ms: u64,
    pub done: bool,
}

#[spacetimedb::table(accessor = cover_timer, scheduled(cover_step))]
pub struct CoverTimer {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}

/// What a derivation holds in memory between steps.
struct Work {
    /// The land it regenerates: seed, side and full parameters.
    key: (u64, u32, String),
    gen: Option<Gen>,
    land: Option<Land>,
    candidates: Vec<u32>,
    /// Steps of generation and hosting done here (the row's `generated` must match).
    generated: u32,
}

thread_local! {
    static WORK: RefCell<Option<Work>> = const { RefCell::new(None) };
}

/// Every band of this land's cover geometry is kept. False for a world that is not a land.
pub fn ready(ctx: &ReducerContext) -> bool {
    ctx.db.land().id().find(0).is_some_and(|l| ctx.db.cover_ground().count() as usize >= crate::island::cover_bands(l.size))
}

/// Start (or carry on) deriving the geometry when the world's cover law is on (`cover_on`, the
/// laws the caller has in hand: reading them again after an install would compile the script)
/// and the world, a made land, does not have it. Nothing otherwise: cover off, not a land (or
/// not made yet), geometry complete, a creation still in steps (it keeps the bands itself, and
/// calls this at its end), or a derivation step already scheduled.
pub fn ensure(ctx: &ReducerContext, cover_on: bool) {
    if !cover_on || ctx.db.land().id().find(0).is_none() || ready(ctx) {
        return;
    }
    if ctx.db.genesis().id().find(0).is_some_and(|g| !g.done) || ctx.db.cover_timer().iter().next().is_some() {
        return;
    }
    let now = common::now_ms(ctx);
    match ctx.db.cover_derivation().id().find(0) {
        Some(mut d) => {
            log::info!("cover geometry: resumed at step {} ({})", d.step, d.label);
            d.label = format!("resumed: {}", d.label.trim_start_matches("resumed: "));
            d.done = false;
            d.updated_ms = now;
            ctx.db.cover_derivation().id().update(d);
        }
        None => {
            log::info!("cover geometry: this land has none; deriving it in steps");
            ctx.db.cover_derivation().insert(CoverDerivation { id: 0, step: 0, label: "starting: the land generated again".into(), generated: 0, restarts: 0, started_ms: now, updated_ms: now, done: false });
        }
    }
    schedule(ctx, 0);
}

fn schedule(ctx: &ReducerContext, after_ms: u64) {
    ctx.db.cover_timer().insert(CoverTimer { scheduled_id: 0, scheduled_at: ScheduleAt::Time(ctx.timestamp + std::time::Duration::from_millis(after_ms)) });
}

/// One step of a derivation (scheduled only). A step that fails keeps its reason in the
/// `cover_derivation` label and schedules nothing; switching cover on again carries on.
#[spacetimedb::reducer]
pub fn cover_step(ctx: &ReducerContext, _t: CoverTimer) -> Result<(), String> {
    if ctx.sender() != ctx.database_identity() {
        return Err("cover_step is scheduled only".into());
    }
    if common::schema_moved("cover_step") {
        return Ok(());
    }
    if let Err(e) = step(ctx) {
        log::error!("cover geometry: step failed: {e}");
        WORK.with(|w| *w.borrow_mut() = None);
        if let Some(mut d) = ctx.db.cover_derivation().id().find(0) {
            // Its memory dropped on purpose: carrying on starts generation again (not a restart).
            d.generated = 0;
            d.label = format!("stopped: {e} (switching cover_sight_on on again carries on)");
            d.updated_ms = common::now_ms(ctx);
            ctx.db.cover_derivation().id().update(d);
        }
    }
    Ok(())
}

/// The step itself. Its errors come before it writes anything.
fn step(ctx: &ReducerContext) -> Result<(), String> {
    let Some(mut d) = ctx.db.cover_derivation().id().find(0) else { return Ok(()) };
    if d.done {
        return Ok(());
    }
    let now = common::now_ms(ctx);
    if !common::laws(ctx).cover_sight_on {
        // Not worth a running world's time any more; switching cover on again carries on.
        WORK.with(|w| *w.borrow_mut() = None);
        d.generated = 0;
        d.label = "stopped: cover sight was switched off (switching it on again carries on)".into();
        d.updated_ms = now;
        ctx.db.cover_derivation().id().update(d);
        return Ok(());
    }
    let land_row = ctx.db.land().id().find(0).ok_or("this world has no land")?;
    let plan = ctx.db.land_plan().id().find(0).map_or_else(|| land_row.params.clone(), |p| p.params);
    let params: LandParams = serde_json::from_str(&plan).map_err(|e| format!("the land's parameters: {e}"))?;
    let key = (land_row.seed, land_row.size, plan);
    let total = crate::island::cover_bands(land_row.size);
    let done = WORK.with(|cell| -> Result<bool, String> {
        let mut cell = cell.borrow_mut();
        let fresh = !matches!(&*cell, Some(w) if w.key == key && w.generated == d.generated);
        if fresh {
            if d.generated > 0 {
                d.restarts += 1;
                log::warn!("cover geometry: this instance lost the land at step {} of generation; generating again from the start", d.generated);
            }
            *cell = Some(Work { key: key.clone(), gen: Some(Gen::new(land_row.seed, land_row.size, params.clone())), land: None, candidates: Vec::new(), generated: 0 });
            d.generated = 0;
        }
        let w = cell.as_mut().expect("work");
        if let Some(gen) = w.gen.as_mut().filter(|g| !g.is_done()) {
            d.label = gen.label();
            let _t = spacetimedb::log_stopwatch::LogStopwatch::new("cover.generate");
            gen.step();
            (w.generated, d.generated) = (w.generated + 1, d.generated + 1);
            return Ok(false);
        }
        if w.land.is_none() {
            d.label = "hosting: the tiles, checked against the land row's digests".into();
            let _t = spacetimedb::log_stopwatch::LogStopwatch::new("cover.host");
            let land = w.gen.take().expect("generated land").into_land();
            let (map, _) = living_rules::host::hosted_map(&land, &params);
            let dg = living_rules::host::digests(&land, &map);
            if (dg.tiles, dg.heights) != (land_row.tiles_digest, land_row.heights_digest) {
                return Err(format!(
                    "the land generated again is not this world's (tiles {:016x}, heights {:016x}; the land row has {:016x}, {:016x}): this module's generator differs from the one that made it",
                    dg.tiles, dg.heights, land_row.tiles_digest, land_row.heights_digest
                ));
            }
            w.candidates = living_rules::cover::candidates(&map);
            w.land = Some(land);
            (w.generated, d.generated) = (w.generated + 1, d.generated + 1);
            return Ok(false);
        }
        // Bands are kept in order, so the next one is the count kept.
        let a = ctx.db.cover_ground().count() as usize;
        let b = (a + BANDS_PER_STEP).min(total);
        d.label = format!("ground bands {a}..{b} of {total}");
        crate::island::keep_cover_bands_of(ctx, w.land.as_ref().expect("land"), &w.candidates, a..b);
        if b >= total {
            *cell = None;
            return Ok(true);
        }
        Ok(false)
    })?;
    d.step += 1;
    d.updated_ms = now;
    if done {
        log::info!("cover geometry: derived ({} steps, {} s); cover sight is in force", d.step, now.saturating_sub(d.started_ms) / 1000);
        d.done = true;
        d.label = "done".into();
        ctx.db.cover_derivation().id().update(d);
        // A new law revision: every cached map compares the cover in force again and compiles
        // its mask (`common::map`); then the public row says cover is on.
        common::bump_law_rev(ctx);
        common::publish_cover_law(ctx, common::laws(ctx));
    } else {
        ctx.db.cover_derivation().id().update(d);
        schedule(ctx, STEP_GAP_MS);
    }
    Ok(())
}
