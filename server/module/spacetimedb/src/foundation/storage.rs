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
#[spacetimedb::table(accessor=sim_world_blob)]
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
struct Reader<'a> {
    ctx: &'a ViewContext,
    catalog: Catalog,
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
        cached(&mut self.catalog, run, actor, kind, id, || {
            self.ctx.db.sim_world_blob().id().find(id)
        })
    }
}
struct Writer<'a> {
    ctx: &'a ReducerContext,
    catalog: &'a mut Catalog,
}
impl Blobs for Writer<'_> {
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
        cached(self.catalog, run, actor, kind, id, || {
            self.ctx.db.sim_world_blob().id().find(id)
        })
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
    };
    let state = loaded.row.state.clone();
    let world = codec::decode(
        &state,
        &mut Writer {
            ctx,
            catalog: &mut loaded.catalog,
        },
    )?;
    if world.run != loaded.row.id {
        return Err("stored run identity differs from World".into());
    }
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
    codec::encode(
        world,
        &mut Writer {
            ctx,
            catalog: &mut row.catalog,
        },
    )
}
pub(super) fn commit(ctx: &ReducerContext, mut row: LoadedRun, encoded: Encoded) {
    // Remove only this run's no-longer-referenced private payloads. This follows
    // the kernel's existing trace/lease eviction; authority audit is untouched.
    for id in row
        .catalog
        .blobs
        .keys()
        .filter(|id| !row.catalog.live.contains(id))
    {
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
    let world = codec::decode(
        &row.state,
        &mut Reader {
            ctx,
            catalog: Catalog::default(),
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
