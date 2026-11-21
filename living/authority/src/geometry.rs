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
//! one-shot scheduled reducer that does one short step per call and schedules the next. Each
//! step is short because SpacetimeDB runs one reducer at a time per database, in the order they
//! are queued (2.14.1 `host/module_host.rs`: "Reducers are not executed concurrently"; WASM
//! procedures share that one thread too): a long step delays every tick behind it. The
//! cover-stall fix (docs/COVER_SIGHT.md) keeps every step to a few ms:
//! - **From the ground source** (a land made with cover off since cover-stall): the
//!   `cover_source` rows a few at a time ([`SOURCE_ROWS_PER_STEP`]), decoded a part per step
//!   (`living_rules::land::GroundDecode`), checked against the `land` row's heights digest a few
//!   lattice rows per step ([`HEIGHTS_PER_STEP`]; a module whose ground differs stops with that
//!   reason), then the ground sampled half a band per step ([`TILES_PER_STEP`]), each band's
//!   row written once complete. These steps follow one another at once; a tick queued meanwhile
//!   waits for one step at most.
//! - **Without a ground source** (a land made before cover-stall): the land generated again
//!   from the `land` row's seed and the full parameters (`land_plan`) in `Gen`'s steps, its tile
//!   rows in short steps ([`REGEN_BAND_TILES`]), then the hosted tiles checked against the
//!   `land` row's tile and height digests, then the same half-band sampling. Generation's other
//!   steps are not split (the island's longest, the planner's lots, about 0.5 s): [`STEP_GAP_MS`]
//!   after each lets the world tick between them.
//!
//! The rows are the ones creation would have kept: the same samples (`cover::ground_range`) and
//! candidates of the same hosted tiles (byte-identical, sha256 over the rows).
//!
//! **In force only when complete.** Until every band is kept, the cover in force is off: the
//! `cover_law` row says so (`common::publish_cover_law`), the map compiles no mask and Shade
//! builds none, so players, minds and clients agree. The last step hands what it sampled to the
//! map's cover cache (`common::keep_cover_geometry`, so the mask compiles without reading every
//! band back), writes a new law revision, so every cached map compiles its mask, and publishes
//! the row as on. A later value-only cover edit (eye height, brush, cliff step) never derives
//! anything: the mask compiles again from that cache at the next map read.
//!
//! **Where the work lives between steps** is the instance's memory, a cache only (the reducers
//! docs, "Global and Static Variables Are Undefined Behavior"): the `cover_derivation` row and the
//! bands kept are the truth, and a cache that is not this land's or not as far as the row says
//! starts again from its first step (deterministic; kept bands are kept; a band half sampled is
//! sampled again). The decoded ground source is about 30 MB at 4096 m; a generation's peak raises
//! the instance's linear memory, which never shrinks (about 60 MB on the island, 210 MB at 4096 m).

use crate::common;
use crate::floor::genesis;
use crate::tables::*;
use living_rules::land::{Gen, GroundDecode, Land, LandParams};
use spacetimedb::{ReducerContext, ScheduleAt, Table};
use std::cell::RefCell;

/// Tiles sampled per step of a derivation on a running world: half a band (`island::COVER_BAND`,
/// 16,384 tiles), about 1.3 ms on the island and up to about 5 ms in the 4096 m megacity's
/// densest rows (a whole band measured 9.3 ms there, p50, on a loaded Spark), so no step holds the
/// database thread for long. A band's row is written once all its tiles are sampled.
const TILES_PER_STEP: usize = crate::island::COVER_BAND / 2;
/// Bands per step of a staged creation: no world ticks yet, so its steps may be long (at most
/// about 11 × 10⁹ fuel in the 4096 m megacity's densest rows, 4.4 × 10⁹ on the island).
pub const CREATION_BANDS_PER_STEP: usize = 64;
/// Lattice points per step of the source check (the land row's heights digest, a height and a
/// water level at each): about 4–6 ms in the 4096 m megacity (16,384 took 10–15 ms there).
const HEIGHTS_PER_STEP: u32 = 6_144;
/// Tiles classified per tile step when the land is generated again (`Gen::with_band_tiles`):
/// about 0.2 × 10⁹ fuel on the island, instead of one 24 × 10⁹ step.
const REGEN_BAND_TILES: usize = 1 << 15;
/// Time after a generation step before the next (only a land without a ground source generates
/// again): some of those steps are long, and the ticks queued meanwhile run between them. The
/// short steps (the source read, its check, the bands) schedule the next at once: SpacetimeDB
/// runs one reducer at a time per database, in the order they are queued, so a tick waits at
/// most one short step.
const STEP_GAP_MS: u64 = 100;
/// Bytes per `cover_source` row.
pub const SOURCE_CHUNK: usize = 256 << 10;
/// `cover_source` rows read per step (512 KiB).
const SOURCE_ROWS_PER_STEP: u32 = 2;
/// The framing of a `cover_source` blob: format, then the ground source, then the candidates.
const SOURCE_FORMAT: u8 = 1;

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
    /// Steps of generation and hosting done in this instance's memory (see the module notes);
    /// with a ground source, the steps of reading and checking it.
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

/// A land's ground source (private): what its ground heights are computed from
/// (`Land::ground_source`) and the tree and cliff candidates of its hosted tiles, kept at
/// creation by a land made with cover off, in rows of [`SOURCE_CHUNK`] bytes (`id` 0..`chunks`).
/// Switching cover on samples the ground from it in short steps instead of generating the land
/// again. Island about 3.5 MB, the 4096 m megacity about 9 MB. Never written again.
#[spacetimedb::table(accessor = cover_source)]
pub struct CoverSource {
    #[primary_key]
    pub id: u32,
    /// Rows in all: the source is complete when the table has this many.
    pub chunks: u32,
    pub bytes: Vec<u8>,
}

/// The `cover_source` blob of a land and the candidates of its hosted tiles.
pub fn source_of(land: &Land, candidates: &[u32]) -> Vec<u8> {
    let ground = land.ground_source();
    let mut b = Vec::with_capacity(9 + ground.len() + 4 * candidates.len());
    b.push(SOURCE_FORMAT);
    b.extend_from_slice(&(ground.len() as u64).to_le_bytes());
    b.extend_from_slice(&ground);
    for c in candidates {
        b.extend_from_slice(&c.to_le_bytes());
    }
    b
}

/// A `cover_source` blob's ground source (still to decode) and candidates.
fn read_source(b: &[u8]) -> Result<(Vec<u8>, Vec<u32>), String> {
    if b.first() != Some(&SOURCE_FORMAT) || b.len() < 9 {
        return Err(format!("its ground source is of another format ({:?})", b.first()));
    }
    let n = u64::from_le_bytes(b[1..9].try_into().expect("8 bytes")) as usize;
    let rest = &b[9..];
    if n > rest.len() || (rest.len() - n) % 4 != 0 {
        return Err("its ground source is cut short".into());
    }
    let candidates = rest[n..].chunks_exact(4).map(|c| u32::from_le_bytes(c.try_into().expect("4 bytes"))).collect();
    Ok((rest[..n].to_vec(), candidates))
}

/// Keep a land's ground source (a creation with cover off, after hosting); a source already kept
/// (a creation step repeated after a lost instance) is kept as it is.
pub fn keep_source(ctx: &ReducerContext, land: &Land, candidates: &[u32]) {
    if ctx.db.cover_source().iter().next().is_some() {
        return;
    }
    let _t = spacetimedb::log_stopwatch::LogStopwatch::new("cover.source");
    let b = source_of(land, candidates);
    let chunks = b.len().div_ceil(SOURCE_CHUNK) as u32;
    for (i, part) in b.chunks(SOURCE_CHUNK).enumerate() {
        ctx.db.cover_source().insert(CoverSource { id: i as u32, chunks, bytes: part.to_vec() });
    }
    log::info!("cover geometry: the land's ground source kept ({} bytes in {chunks} rows) for a later switch-on", b.len());
}

/// The ground source is complete: every row of its count is kept.
fn source_kept(ctx: &ReducerContext) -> bool {
    ctx.db.cover_source().id().find(0).is_some_and(|r| r.chunks > 0 && ctx.db.cover_source().count() == r.chunks as u64)
}

/// What a derivation holds in memory between steps.
struct Work {
    /// The land it derives for: seed, side and full parameters.
    key: (u64, u32, String),
    gen: Option<Gen>,
    land: Option<Land>,
    candidates: Vec<u32>,
    /// Steps of generation and hosting (or of reading and checking the source) done here (the
    /// row's `generated` must match).
    generated: u32,
    /// From the ground source: its bytes read so far (rows `0..read`), then the heights digest
    /// so far, over lattice rows `0..rows`; then checked against the land row.
    from_source: bool,
    bytes: Vec<u8>,
    read: u32,
    decode: Option<GroundDecode>,
    rows: u32,
    digest: u64,
    checked: bool,
    /// The bands sampled here, in order from `first` (handed to the map's cover cache at the
    /// end, so the first mask compiles without reading every band back).
    first: usize,
    ground: Vec<i16>,
    /// The band being sampled (`band`, the count kept when it began) and its samples so far.
    band: usize,
    partial: Vec<i16>,
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
            let how = if source_kept(ctx) { "sampling the ground source kept at creation" } else { "the land generated again (no ground source)" };
            log::info!("cover geometry: this land has none; deriving it in steps: {how}");
            ctx.db.cover_derivation().insert(CoverDerivation { id: 0, step: 0, label: format!("starting: {how}"), generated: 0, restarts: 0, started_ms: now, updated_ms: now, done: false });
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
    let _t = spacetimedb::log_stopwatch::LogStopwatch::new("cover_step");
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

/// What a step did: the derivation is complete, or the next step's delay.
enum Next {
    Done,
    After(u64),
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
    let key = (land_row.seed, land_row.size, plan);
    let total = crate::island::cover_bands(land_row.size);
    let next = WORK.with(|cell| -> Result<Next, String> {
        let mut cell = cell.borrow_mut();
        let fresh = !matches!(&*cell, Some(w) if w.key == key && w.generated == d.generated);
        if fresh {
            if d.generated > 0 {
                d.restarts += 1;
                log::warn!("cover geometry: this instance lost its work at step {} of generation or the source check; starting it again", d.generated);
            }
            d.generated = 0;
            if source_kept(ctx) {
                *cell = Some(Work { key: key.clone(), gen: None, land: None, candidates: Vec::new(), generated: 0, from_source: true, bytes: Vec::new(), read: 0, decode: None, rows: 0, digest: living_rules::det::FNV_OFFSET, checked: false, first: 0, ground: Vec::new(), band: usize::MAX, partial: Vec::new() });
            } else {
                let params: LandParams = serde_json::from_str(&key.2).map_err(|e| format!("the land's parameters: {e}"))?;
                let gen = Gen::new(land_row.seed, land_row.size, params).with_band_tiles(REGEN_BAND_TILES);
                *cell = Some(Work { key: key.clone(), gen: Some(gen), land: None, candidates: Vec::new(), generated: 0, from_source: false, bytes: Vec::new(), read: 0, decode: None, rows: 0, digest: 0, checked: false, first: 0, ground: Vec::new(), band: usize::MAX, partial: Vec::new() });
            }
        }
        let w = cell.as_mut().expect("work");
        if w.from_source && w.land.is_none() {
            // The land's ground as it was made: its rows a few at a time, then decoded.
            let chunks = ctx.db.cover_source().id().find(0).map_or(0, |r| r.chunks);
            if w.read < chunks {
                let b = (w.read + SOURCE_ROWS_PER_STEP).min(chunks);
                d.label = format!("source: rows {}..{b} of {chunks} read", w.read);
                let _t = spacetimedb::log_stopwatch::LogStopwatch::new("cover.source_read");
                for id in w.read..b {
                    let row = ctx.db.cover_source().id().find(id).ok_or_else(|| format!("its ground source lost row {id}"))?;
                    w.bytes.extend_from_slice(&row.bytes);
                }
                w.read = b;
            } else if w.decode.is_none() {
                d.label = "source: framing and candidates read".into();
                let (ground, candidates) = read_source(&std::mem::take(&mut w.bytes))?;
                w.decode = Some(GroundDecode::new(ground));
                w.candidates = candidates;
            } else {
                // Decoded a part per step (the 4096 m megacity's whole decode is about 22 ms).
                d.label = "source: decoding".into();
                let _t = spacetimedb::log_stopwatch::LogStopwatch::new("cover.source_decode");
                if w.decode.as_mut().expect("decode").step()? {
                    let land = w.decode.take().expect("decode").into_land()?;
                    if (land.seed, land.size) != (land_row.seed, land_row.size) {
                        return Err(format!("its ground source is of another land (seed {}, {} m)", land.seed, land.size));
                    }
                    w.land = Some(land);
                }
            }
            (w.generated, d.generated) = (w.generated + 1, d.generated + 1);
            return Ok(Next::After(0));
        }
        if w.from_source && !w.checked {
            // The source answers the heights the land was made with: the land row's heights
            // digest, a few lattice rows per step (a module whose ground differs stops here).
            let land = w.land.as_ref().expect("source land");
            let all = living_rules::host::height_rows(land);
            let per = (HEIGHTS_PER_STEP / land.size.div_ceil(living_rules::host::HEIGHT_STEP_M).max(1)).max(1);
            let b = (w.rows + per).min(all);
            d.label = format!("source: heights digest rows {}..{b} of {all}", w.rows);
            let _t = spacetimedb::log_stopwatch::LogStopwatch::new("cover.source_check");
            w.digest = living_rules::host::heights_digest_rows(land, w.digest, w.rows..b);
            w.rows = b;
            if b >= all {
                if w.digest != land_row.heights_digest {
                    return Err(format!(
                        "the ground source's heights are not this world's (digest {:016x}; the land row has {:016x}): this module's ground differs from the one that made it",
                        w.digest, land_row.heights_digest
                    ));
                }
                w.checked = true;
            }
            (w.generated, d.generated) = (w.generated + 1, d.generated + 1);
            return Ok(Next::After(0));
        }
        if let Some(gen) = w.gen.as_mut().filter(|g| !g.is_done()) {
            d.label = gen.label();
            // The tile steps are short (`REGEN_BAND_TILES`); the others may not be.
            let short = d.label.starts_with("tiles");
            let _t = spacetimedb::log_stopwatch::LogStopwatch::new("cover.generate");
            gen.step();
            (w.generated, d.generated) = (w.generated + 1, d.generated + 1);
            return Ok(Next::After(if short { 0 } else { STEP_GAP_MS }));
        }
        if w.land.is_none() {
            d.label = "hosting: the tiles, checked against the land row's digests".into();
            let _t = spacetimedb::log_stopwatch::LogStopwatch::new("cover.host");
            let params: LandParams = serde_json::from_str(&key.2).map_err(|e| format!("the land's parameters: {e}"))?;
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
            return Ok(Next::After(STEP_GAP_MS));
        }
        // Bands are kept in order, so the next one is the count kept; it is sampled half a band
        // per step and written whole.
        let a = ctx.db.cover_ground().count() as usize;
        if a >= total {
            *cell = None;
            return Ok(Next::Done);
        }
        if w.band != a {
            w.band = a;
            w.partial.clear();
        }
        let tiles = (land_row.size as usize).pow(2);
        let from = a * crate::island::COVER_BAND + w.partial.len();
        let to = (from + TILES_PER_STEP).min((a + 1) * crate::island::COVER_BAND).min(tiles);
        d.label = format!("ground band {a} of {total}: tiles {from}..{to}");
        let _t = spacetimedb::log_stopwatch::LogStopwatch::new("cover.ground");
        w.partial.extend(living_rules::cover::ground_range(w.land.as_ref().expect("land"), from..to));
        if to < ((a + 1) * crate::island::COVER_BAND).min(tiles) {
            return Ok(Next::After(0));
        }
        let heights = std::mem::take(&mut w.partial);
        w.band = usize::MAX;
        if w.ground.is_empty() {
            w.first = a;
        }
        if w.first != usize::MAX && w.first + w.ground.len() / crate::island::COVER_BAND != a {
            // Not this instance's run of bands from the first: none handed over.
            w.first = usize::MAX;
        }
        if w.first != usize::MAX {
            w.ground.extend_from_slice(&heights);
        }
        ctx.db.cover_ground().insert(crate::island::cover_row(a, &w.candidates, heights));
        if a + 1 >= total {
            let w = cell.take().expect("work");
            if w.first == 0 && w.ground.len() == tiles {
                // Every band sampled here: the map's first mask compiles from them.
                common::keep_cover_geometry(w.ground.into(), w.candidates.into());
            }
            return Ok(Next::Done);
        }
        Ok(Next::After(0))
    })?;
    d.step += 1;
    d.updated_ms = now;
    match next {
        Next::Done => {
            log::info!("cover geometry: derived ({} steps, {} ms); cover sight is in force", d.step, now.saturating_sub(d.started_ms));
            d.done = true;
            d.label = "done".into();
            ctx.db.cover_derivation().id().update(d);
            // A new law revision: every cached map compares the cover in force again and compiles
            // its mask (`common::map`); then the public row says cover is on.
            common::bump_law_rev(ctx);
            common::publish_cover_law(ctx, common::laws(ctx));
        }
        Next::After(ms) => {
            ctx.db.cover_derivation().id().update(d);
            schedule(ctx, ms);
        }
    }
    Ok(())
}
