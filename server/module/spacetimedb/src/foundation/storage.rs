//! Fresh-schema durable tables and SQL compatibility boundary. Private compact
//! rows never masquerade as World JSON; the owner view always hydrates it fully.
use super::storage_codec::{self as codec, Blobs, Encoded};
use simulation::World;
use spacetimedb::{Identity, ReducerContext, SpacetimeType, Table, ViewContext};
use std::{
    collections::{BTreeMap, BTreeSet},
    ops::{Deref, DerefMut},
};

#[spacetimedb::table(accessor=sim_run_store)]
pub struct SimRunStore {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub owner: Identity,
    pub state: String,
    pub last_advanced_at: spacetimedb::Timestamp,
}
#[derive(Clone)]
#[spacetimedb::table(accessor = sim_world_blob,
    index(accessor = run_and_kind, btree(columns = [run, kind])))]
pub struct SimWorldBlob {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[unique]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub actor: Option<u32>,
    pub kind: String,
    pub body: String,
}
/// Keeps existing operator SQL and self-contained final snapshot consumers on
/// the same column/JSON contract. The corresponding stored table is private.
#[derive(SpacetimeType)]
pub struct SimRun {
    pub id: String,
    pub owner: Identity,
    pub state: String,
    pub last_advanced_at: spacetimedb::Timestamp,
}
#[derive(Default)]
struct Catalog {
    blobs: BTreeMap<u64, SimWorldBlob>,
    keys: BTreeMap<String, u64>,
    live: BTreeSet<u64>,
}
pub(crate) struct LoadedRun {
    row: SimRunStore,
    catalog: Catalog,
    previous_layout: Option<codec::Layout>,
    lease_reuse: Option<codec::LeaseReuse>,
}
impl Deref for LoadedRun {
    type Target = SimRunStore;
    fn deref(&self) -> &Self::Target {
        &self.row
    }
}
impl DerefMut for LoadedRun {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.row
    }
}
fn validate(
    blob: &SimWorldBlob,
    run: &str,
    actor: Option<u32>,
    kind: &str,
    id: u64,
) -> Result<(), String> {
    if id == 0 || blob.id != id || blob.run != run || blob.actor != actor || blob.kind != kind {
        return Err("immutable reference identity or scope mismatch".into());
    }
    if blob.key != codec::blob_key(run, actor, kind, &blob.body) {
        return Err("immutable payload identity mismatch".into());
    }
    Ok(())
}
fn cached(
    catalog: &mut Catalog,
    run: &str,
    actor: Option<u32>,
    kind: &str,
    id: u64,
    fetch: impl FnOnce() -> Option<SimWorldBlob>,
) -> Result<String, String> {
    if let Some(blob) = catalog.blobs.get(&id) {
        if blob.id != id || blob.run != run || blob.actor != actor || blob.kind != kind {
            return Err("cached immutable reference scope mismatch".into());
        }
        return Ok(blob.body.clone());
    }
    let blob = fetch().ok_or("missing immutable payload")?;
    validate(&blob, run, actor, kind, id)?;
    if catalog.keys.get(&blob.key).is_some_and(|old| *old != id) {
        return Err("immutable key aliases numeric identities".into());
    }
    let body = blob.body.clone();
    catalog.keys.insert(blob.key.clone(), id);
    catalog.blobs.insert(id, blob);
    Ok(body)
}
// Prefetched rows are untrusted staging, not validated Catalog entries. Move a
// requested row through the same first-read scope/hash/key-alias checks; rows
// never requested do not become eligible for retention or garbage collection.
fn staged_cached(
    catalog: &mut Catalog,
    staged: &mut BTreeMap<u64, SimWorldBlob>,
    run: &str,
    actor: Option<u32>,
    kind: &str,
    id: u64,
    fetch: impl FnOnce() -> Option<SimWorldBlob>,
) -> Result<String, String> {
    cached(catalog, run, actor, kind, id, || {
        staged.remove(&id).or_else(fetch)
    })
}
// Batch only these small canonical payload kinds during full hydration. Each
// lookup remains scoped by run and kind; observations and derived bodies keep
// their existing point-read paths. Returned rows are still untrusted staging.
const PREFETCH_KINDS: [&str; 4] = ["experience", "memory", "activity", "receipt"];
fn prefetch_selected_blobs<I>(
    rows_for_kind: impl FnMut(&'static str) -> I,
) -> BTreeMap<u64, SimWorldBlob>
where
    I: IntoIterator<Item = SimWorldBlob>,
{
    PREFETCH_KINDS
        .into_iter()
        .flat_map(rows_for_kind)
        .map(|blob| (blob.id, blob))
        .collect()
}
fn retain_validated(
    catalog: &mut Catalog,
    run: &str,
    actor: Option<u32>,
    kind: &str,
    id: u64,
) -> Result<(), String> {
    // Only a content-validated load or an exactly checked intern grants this
    // transaction permission to retain a row. Raw staging grants no permission.
    let blob = catalog
        .blobs
        .get(&id)
        .ok_or("immutable reference was not validated in this transaction")?;
    if id == 0 || blob.id != id || blob.run != run || blob.actor != actor || blob.kind != kind {
        return Err("retained immutable reference scope mismatch".into());
    }
    catalog.live.insert(id);
    Ok(())
}
struct Reader<'a> {
    ctx: &'a ViewContext,
    catalog: Catalog,
    staged_blobs: BTreeMap<u64, SimWorldBlob>,
}
impl Blobs for Reader<'_> {
    fn intern(&mut self, _: &str, _: Option<u32>, _: &str, _: String) -> Result<u64, String> {
        Err("read-only storage adapter".into())
    }
    fn get(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<String, String> {
        staged_cached(
            &mut self.catalog,
            &mut self.staged_blobs,
            run,
            actor,
            kind,
            id,
            || self.ctx.db.sim_world_blob().id().find(id),
        )
    }
}
struct Writer<'a> {
    ctx: &'a ReducerContext,
    catalog: &'a mut Catalog,
    staged_blobs: BTreeMap<u64, SimWorldBlob>,
}
impl Blobs for Writer<'_> {
    fn retain_validated(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<(), String> {
        retain_validated(self.catalog, run, actor, kind, id)
    }

    fn intern(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        body: String,
    ) -> Result<u64, String> {
        let key = codec::blob_key(run, actor, kind, &body);
        let blob = if let Some(id) = self.catalog.keys.get(&key) {
            let blob = self
                .catalog
                .blobs
                .get(id)
                .ok_or("immutable catalog is inconsistent")?;
            if blob.run != run || blob.actor != actor || blob.kind != kind || blob.body != body {
                return Err("immutable hash collision or scope mismatch".into());
            }
            self.catalog.live.insert(*id);
            return Ok(*id);
        } else if let Some(blob) = self.ctx.db.sim_world_blob().key().find(&key) {
            validate(&blob, run, actor, kind, blob.id)?;
            if blob.body != body {
                return Err("immutable hash collision".into());
            }
            blob
        } else {
            self.ctx.db.sim_world_blob().insert(SimWorldBlob {
                id: 0,
                key,
                run: run.into(),
                actor,
                kind: kind.into(),
                body,
            })
        };
        let id = blob.id;
        if id == 0 || self.catalog.blobs.contains_key(&id) {
            return Err("immutable numeric identity collision".into());
        }
        self.catalog.keys.insert(blob.key.clone(), id);
        self.catalog.blobs.insert(id, blob);
        self.catalog.live.insert(id);
        Ok(id)
    }
    fn get(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<String, String> {
        staged_cached(
            self.catalog,
            &mut self.staged_blobs,
            run,
            actor,
            kind,
            id,
            || self.ctx.db.sim_world_blob().id().find(id),
        )
    }
}
pub(super) fn load(ctx: &ReducerContext, run: &str) -> Result<(LoadedRun, World), String> {
    let row = ctx
        .db
        .sim_run_store()
        .id()
        .find(run.to_string())
        .ok_or("run not found")?;
    hydrate(ctx, row)
}
pub(super) fn load_owned(ctx: &ReducerContext, run: &str) -> Result<(LoadedRun, World), String> {
    let row = ctx
        .db
        .sim_run_store()
        .id()
        .find(run.to_string())
        .ok_or("run not found")?;
    if row.owner != ctx.sender() {
        return Err("only this run's operator may mutate or submit model results".into());
    }
    hydrate(ctx, row)
}
fn hydrate(ctx: &ReducerContext, row: SimRunStore) -> Result<(LoadedRun, World), String> {
    let mut loaded = LoadedRun {
        row,
        catalog: Catalog::default(),
        previous_layout: None,
        lease_reuse: None,
    };
    let state = loaded.row.state.clone();
    let staged_blobs = prefetch_selected_blobs(|kind| {
        ctx.db
            .sim_world_blob()
            .run_and_kind()
            .filter((loaded.row.id.as_str(), kind))
    });
    let (world, layout, reuse) = codec::decode_for_save(
        &state,
        &mut Writer {
            ctx,
            catalog: &mut loaded.catalog,
            staged_blobs,
        },
    )?;
    if world.run != loaded.row.id {
        return Err("stored run identity differs from World".into());
    }
    loaded.previous_layout = Some(layout);
    loaded.lease_reuse = Some(reuse);
    Ok((loaded, world))
}
pub(super) fn exists(ctx: &ReducerContext, run: &str) -> bool {
    ctx.db.sim_run_store().id().find(run.to_string()).is_some()
}
pub(super) fn create(ctx: &ReducerContext, run: String) -> LoadedRun {
    LoadedRun {
        row: ctx.db.sim_run_store().insert(SimRunStore {
            id: run,
            owner: ctx.sender(),
            state: String::new(),
            last_advanced_at: ctx.timestamp,
        }),
        catalog: Catalog::default(),
        previous_layout: None,
        lease_reuse: None,
    }
}
pub(super) fn encode(
    ctx: &ReducerContext,
    row: &mut LoadedRun,
    world: &World,
) -> Result<Encoded, String> {
    if row.row.id != world.run {
        return Err("stored run identity differs from World".into());
    }
    row.catalog.live.clear();
    codec::encode_with_reuse(
        world,
        &mut Writer {
            ctx,
            catalog: &mut row.catalog,
            staged_blobs: BTreeMap::new(),
        },
        row.previous_layout.as_ref(),
        row.lease_reuse.as_ref(),
    )
}
pub(super) fn commit(ctx: &ReducerContext, mut row: LoadedRun, encoded: Encoded) {
    // Remove only this run's no-longer-referenced private payloads. This follows
    // the kernel's existing trace/lease eviction; authority audit is untouched.
    // Reused derived fragments are deliberately not read or interned during a
    // save. Preserve their references, and collect evicted fragments even when
    // their bodies were never hydrated into the canonical World catalog.
    row.catalog
        .live
        .extend(codec::derived_fragment_ids(&encoded.layout));
    let mut previous_ids: BTreeSet<u64> = row.catalog.blobs.keys().copied().collect();
    if let Some(layout) = &row.previous_layout {
        for (id, actor) in codec::derived_fragment_owners(layout) {
            if !row.catalog.live.contains(&id) {
                // A retained reference never authorizes deleting an arbitrary
                // numeric row. Validate only evicted fragments here; unchanged
                // saves still avoid fetching/hashing every retained body.
                let blob = ctx
                    .db
                    .sim_world_blob()
                    .id()
                    .find(id)
                    .expect("evicted captured read exists");
                validate(&blob, &row.id, Some(actor), "captured_read_v1", id)
                    .expect("valid evicted captured read scope and content");
            }
            previous_ids.insert(id);
        }
    }
    for id in previous_ids.difference(&row.catalog.live) {
        ctx.db.sim_world_blob().id().delete(*id);
    }
    row.row.state = encoded.state;
    ctx.db.sim_run_store().id().update(row.row);
}
pub(super) fn world_for_view(ctx: &ViewContext, run: &str) -> Option<World> {
    let row = ctx.db.sim_run_store().id().find(run.to_string())?;
    let world = decode_view(ctx, &row);
    Some(world)
}
fn decode_view(ctx: &ViewContext, row: &SimRunStore) -> World {
    // Full World hydration batches selected canonical payload kinds. The
    // small participant-status reader below keeps empty staging.
    let staged_blobs = prefetch_selected_blobs(|kind| {
        ctx.db
            .sim_world_blob()
            .run_and_kind()
            .filter((row.id.as_str(), kind))
    });
    let world = codec::decode(
        &row.state,
        &mut Reader {
            ctx,
            catalog: Catalog::default(),
            staged_blobs,
        },
    )
    .unwrap_or_else(|error| panic!("corrupt normalized run: {error}"));
    assert_eq!(row.id, world.run, "stored run identity differs from World");
    world
}
pub(super) fn status_for_view(ctx: &ViewContext, run: &str, actor: u32, body: &str) -> String {
    codec::expand_status(
        run,
        actor,
        body,
        &mut Reader {
            ctx,
            catalog: Catalog::default(),
            staged_blobs: BTreeMap::new(),
        },
    )
    .unwrap_or_else(|error| panic!("corrupt normalized participant status: {error}"))
}
#[spacetimedb::view(accessor=sim_run,public)]
pub fn sim_run(ctx: &ViewContext) -> Vec<SimRun> {
    // Filter by each row's owner before hydration. Database ownership is not a
    // substitute for run ownership, and participants get an empty result.
    ctx.db
        .sim_run_store()
        .owner()
        .filter(ctx.sender())
        .map(|row| {
            let world = decode_view(ctx, &row);
            SimRun {
                id: row.id,
                owner: row.owner,
                state: serde_json::to_string(&world).expect("World serializes"),
                last_advanced_at: row.last_advanced_at,
            }
        })
        .collect()
}

// Explicit one-shot owner exports. Their private-row reads do not invoke or
// materialize compatibility views, and no adapter operation can write rows.
struct OwnerExportReader<'a> {
    ctx: &'a ReducerContext,
    catalog: Catalog,
    staged_blobs: BTreeMap<u64, SimWorldBlob>,
}
impl Blobs for OwnerExportReader<'_> {
    fn intern(&mut self, _: &str, _: Option<u32>, _: &str, _: String) -> Result<u64, String> {
        Err("read-only storage adapter".into())
    }
    fn get(
        &mut self,
        run: &str,
        actor: Option<u32>,
        kind: &str,
        id: u64,
    ) -> Result<String, String> {
        staged_cached(
            &mut self.catalog,
            &mut self.staged_blobs,
            run,
            actor,
            kind,
            id,
            || self.ctx.db.sim_world_blob().id().find(id),
        )
    }
}
fn decode_owned_export<B: Blobs>(
    row: Option<SimRunStore>,
    caller: Identity,
    reader: impl FnOnce(&str) -> B,
) -> Result<World, String> {
    let row = row
        .filter(|row| row.owner == caller)
        .ok_or("run unavailable")?;
    // Ownership precedes even reader construction, which prefetches blobs.
    let world =
        codec::decode(&row.state, &mut reader(&row.id)).map_err(|_| "stored run invalid")?;
    if world.run != row.id {
        return Err("stored run invalid".into());
    }
    Ok(world)
}
fn export_owned_world(ctx: &ReducerContext, run: &str) -> Result<World, String> {
    let row = ctx.db.sim_run_store().id().find(run.to_owned());
    decode_owned_export(row, ctx.sender(), |run| OwnerExportReader {
        ctx,
        catalog: Catalog::default(),
        staged_blobs: prefetch_selected_blobs(|kind| {
            ctx.db.sim_world_blob().run_and_kind().filter((run, kind))
        }),
    })
}
#[spacetimedb::procedure]
pub fn sim_owned_run_ids(ctx: &mut spacetimedb::ProcedureContext) -> Result<Vec<String>, String> {
    let mut ids: Vec<String> = ctx.with_tx(|tx| {
        tx.db
            .sim_run_store()
            .owner()
            .filter(tx.sender())
            .map(|row| row.id)
            .collect()
    });
    ids.sort();
    Ok(ids)
}
#[spacetimedb::procedure]
pub fn sim_export_owned_run(
    ctx: &mut spacetimedb::ProcedureContext,
    run: String,
) -> Result<String, String> {
    // Closure-local reads only: the SDK may retry this transaction once.
    let world = ctx.try_with_tx(|tx| export_owned_world(tx, &run))?;
    // This owned World is the coherent transaction snapshot. Serialization
    // happens after the transaction completes and performs no database reads.
    serde_json::to_string(&world).map_err(|_| "world serialization failed".into())
}

#[cfg(test)]
#[path = "storage_tests.rs"]
mod tests;
