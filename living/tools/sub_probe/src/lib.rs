//! Subscription-cost probe (docs/VIEWER_FLOOR.md, M1; branch `viewer-floor` only, never published
//! to a world). What does SpacetimeDB 2.14.1's database thread pay per written row, and how does
//! that grow with the number of subscribers, for the four ways a per-viewer row can reach its
//! viewer:
//!
//! - mode 1 `ri`: a public table with row-level security `viewer = :sender`, `viewer` indexed
//!   (as the game's copy tables);
//! - mode 2 `ru`: the same rule on an unindexed `viewer`;
//! - mode 3 `pb`: a public table without a rule, every subscriber receives every row;
//! - mode 4 `pv` through the per-user view `my_pv` (a btree point read on `viewer`).
//!
//! Every connecting client is a subscriber (`client_connected`). `setup` gives each subscriber
//! `rows` rows in every table. Each tick (60 Hz) updates `k` rows of the mode's table, each for a
//! random subscriber and slot. Mode 0 writes nothing; mode 5 reads the subscriber list only (the
//! tick's own baseline). The driver (`sub_probe.py`) reads the server's metrics around a window.

use spacetimedb::rand::Rng;
use spacetimedb::{Identity, ReducerContext, ScheduleAt, Table, TimeDuration, ViewContext};

#[spacetimedb::table(accessor = sub, public)]
pub struct Sub {
    #[primary_key]
    pub identity: Identity,
}

#[spacetimedb::table(accessor = cfg, public)]
pub struct Cfg {
    #[primary_key]
    pub id: u8,
    pub mode: u8,
    pub k: u32,
    pub rows: u32,
    pub ticks: u64,
    pub writes: u64,
}

#[spacetimedb::table(accessor = timer, scheduled(tick))]
pub struct Timer {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}

/// The row each mode writes: about a motion copy's size (an id, a viewer, a segment).
macro_rules! probe_row {
    ($name:ident, $acc:ident, $($attr:tt)*) => {
        #[spacetimedb::table(accessor = $acc, public)]
        pub struct $name {
            #[primary_key]
            pub id: u64,
            $($attr)*
            pub viewer: Identity,
            pub v: u64,
            pub t_ms: u64,
            pub x: f32,
            pub y: f32,
            pub vx: f32,
            pub vy: f32,
            pub heading: f32,
            pub turn: f32,
        }
    };
}

probe_row!(Ri, ri, #[index(btree)]);
probe_row!(Ru, ru,);
probe_row!(Pb, pb,);

/// Private: reached only through `my_pv`.
#[spacetimedb::table(accessor = pv)]
pub struct Pv {
    #[primary_key]
    pub id: u64,
    #[index(btree)]
    pub viewer: Identity,
    pub v: u64,
    pub t_ms: u64,
    pub x: f32,
    pub y: f32,
    pub vx: f32,
    pub vy: f32,
    pub heading: f32,
    pub turn: f32,
}

#[spacetimedb::client_visibility_filter]
const RI_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM ri WHERE viewer = :sender");

#[spacetimedb::client_visibility_filter]
const RU_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM ru WHERE viewer = :sender");

/// My rows of `pv` (one btree point read, so it re-runs only when one of my rows is written).
#[spacetimedb::view(accessor = my_pv, public, primary_key = id)]
pub fn my_pv(ctx: &ViewContext) -> Vec<Pv> {
    ctx.db.pv().viewer().filter(ctx.sender()).collect()
}

#[spacetimedb::reducer(init)]
pub fn init(ctx: &ReducerContext) {
    ctx.db.cfg().insert(Cfg { id: 0, mode: 0, k: 0, rows: 0, ticks: 0, writes: 0 });
    ctx.db.timer().insert(Timer { scheduled_id: 0, scheduled_at: ScheduleAt::Interval(TimeDuration::from_micros(16_667)) });
}

#[spacetimedb::reducer(client_connected)]
pub fn connected(ctx: &ReducerContext) {
    if ctx.db.sub().identity().find(ctx.sender()).is_none() {
        ctx.db.sub().insert(Sub { identity: ctx.sender() });
    }
}

#[spacetimedb::reducer(client_disconnected)]
pub fn disconnected(ctx: &ReducerContext) {
    ctx.db.sub().identity().delete(ctx.sender());
}

fn key(n: usize, slot: u32) -> u64 {
    (n as u64) << 16 | slot as u64
}

/// Every subscriber gets `rows` rows in each table (all four rewritten from scratch). Only the
/// module's owner may call it.
#[spacetimedb::reducer]
pub fn setup(ctx: &ReducerContext, rows: u32) -> Result<(), String> {
    if ctx.sender() != ctx.database_identity() && ctx.db.sub().identity().find(ctx.sender()).is_some() {
        return Err("setup is the owner's".into());
    }
    for r in ctx.db.ri().iter().collect::<Vec<_>>() {
        ctx.db.ri().delete(r);
    }
    for r in ctx.db.ru().iter().collect::<Vec<_>>() {
        ctx.db.ru().delete(r);
    }
    for r in ctx.db.pb().iter().collect::<Vec<_>>() {
        ctx.db.pb().delete(r);
    }
    for r in ctx.db.pv().iter().collect::<Vec<_>>() {
        ctx.db.pv().delete(r);
    }
    let subs: Vec<Identity> = ctx.db.sub().iter().map(|s| s.identity).collect();
    for (n, viewer) in subs.iter().enumerate() {
        for slot in 0..rows {
            let id = key(n, slot);
            ctx.db.ri().insert(Ri { id, viewer: *viewer, v: 0, t_ms: 0, x: 0.0, y: 0.0, vx: 0.0, vy: 0.0, heading: 0.0, turn: 0.0 });
            ctx.db.ru().insert(Ru { id, viewer: *viewer, v: 0, t_ms: 0, x: 0.0, y: 0.0, vx: 0.0, vy: 0.0, heading: 0.0, turn: 0.0 });
            ctx.db.pb().insert(Pb { id, viewer: *viewer, v: 0, t_ms: 0, x: 0.0, y: 0.0, vx: 0.0, vy: 0.0, heading: 0.0, turn: 0.0 });
            ctx.db.pv().insert(Pv { id, viewer: *viewer, v: 0, t_ms: 0, x: 0.0, y: 0.0, vx: 0.0, vy: 0.0, heading: 0.0, turn: 0.0 });
        }
    }
    let mut c = ctx.db.cfg().id().find(0).unwrap();
    c.rows = rows;
    c.mode = 0;
    ctx.db.cfg().id().update(c);
    log::info!("sub_probe setup: {} subscribers x {rows} rows", subs.len());
    Ok(())
}

/// Which table the tick writes and how many rows a tick (`mode` as in the module's doc).
#[spacetimedb::reducer]
pub fn set(ctx: &ReducerContext, mode: u8, k: u32) -> Result<(), String> {
    if ctx.sender() != ctx.database_identity() && ctx.db.sub().identity().find(ctx.sender()).is_some() {
        return Err("set is the owner's".into());
    }
    let mut c = ctx.db.cfg().id().find(0).unwrap();
    c.mode = mode;
    c.k = k;
    ctx.db.cfg().id().update(c);
    Ok(())
}

#[spacetimedb::reducer]
pub fn tick(ctx: &ReducerContext, _t: Timer) -> Result<(), String> {
    if ctx.sender() != ctx.database_identity() {
        return Err("scheduled only".into());
    }
    let Some(mut c) = ctx.db.cfg().id().find(0) else { return Ok(()) };
    if c.mode == 0 {
        return Ok(());
    }
    let n = ctx.db.sub().count() as usize;
    c.ticks += 1;
    if c.mode == 5 || n == 0 || c.rows == 0 {
        ctx.db.cfg().id().update(c);
        return Ok(());
    }
    let now = ctx.timestamp.to_micros_since_unix_epoch() as u64 / 1000;
    let mut rng = ctx.rng();
    for _ in 0..c.k {
        let id = key(rng.gen_range(0..n), rng.gen_range(0..c.rows));
        let x = rng.gen::<f32>();
        match c.mode {
            1 => {
                if let Some(r) = ctx.db.ri().id().find(id) {
                    ctx.db.ri().id().update(Ri { v: r.v + 1, t_ms: now, x, ..r });
                }
            }
            2 => {
                if let Some(r) = ctx.db.ru().id().find(id) {
                    ctx.db.ru().id().update(Ru { v: r.v + 1, t_ms: now, x, ..r });
                }
            }
            3 => {
                if let Some(r) = ctx.db.pb().id().find(id) {
                    ctx.db.pb().id().update(Pb { v: r.v + 1, t_ms: now, x, ..r });
                }
            }
            4 => {
                if let Some(r) = ctx.db.pv().id().find(id) {
                    ctx.db.pv().id().update(Pv { v: r.v + 1, t_ms: now, x, ..r });
                }
            }
            _ => {}
        }
        c.writes += 1;
    }
    ctx.db.cfg().id().update(c);
    Ok(())
}
