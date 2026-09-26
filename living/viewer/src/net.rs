//! Anonymous read-only connection to the living authority. The connection is advanced
//! once per frame (`frame_tick`) on the main thread, natively and in the browser.

use bevy::prelude::*;
use living_bindings::*;
use spacetimedb_sdk::{DbContext, SubscriptionHandle as _, Table, TableWithPrimaryKey};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};

/// Public tables the observer needs (all small at the current scale).
const QUERIES: &[&str] = &[
    "SELECT * FROM world",
    "SELECT * FROM terrain_chunk",
    "SELECT * FROM character",
    "SELECT * FROM body",
    "SELECT * FROM vitals",
    "SELECT * FROM activity",
    "SELECT * FROM inventory",
    "SELECT * FROM resource_node",
    "SELECT * FROM structure",
    "SELECT * FROM brain",
    "SELECT * FROM mind_state",
    "SELECT * FROM persona",
    "SELECT * FROM relation",
    "SELECT * FROM belief",
    "SELECT * FROM judgment",
    "SELECT * FROM place",
    "SELECT * FROM thought",
    "SELECT * FROM chronicle",
    "SELECT * FROM stats",
    "SELECT * FROM bond_offer",
    "SELECT * FROM expecting",
    "SELECT * FROM mind_cursor",
    "SELECT * FROM know_how",
    "SELECT * FROM artifact",
    "SELECT * FROM trade_offer",
    "SELECT * FROM background",
    "SELECT * FROM gate",
];

/// A per-character experience subscription (only the inspected character's rows).
struct ExpSub {
    actor: u32,
    handle: SubscriptionHandle,
}

/// Change generations for rows the viewer derives caches from.
#[derive(Clone, Default)]
pub struct Generations {
    pub resources: Arc<AtomicU32>,
    /// New thought/chronicle rows, applied incrementally (a full rebuild happens only on
    /// deletes, updates and resubscription).
    pub fresh_thoughts: Arc<Mutex<Vec<Thought>>>,
    pub fresh_chronicle: Arc<Mutex<Vec<Chronicle>>>,
    pub terrain: Arc<AtomicU32>,
    pub chronicle: Arc<AtomicU32>,
    pub thought: Arc<AtomicU32>,
    pub background: Arc<AtomicU32>,
}

impl Generations {
    pub fn get(&self) -> (u32, u32, u32, u32) {
        (
            self.terrain.load(Ordering::Relaxed),
            self.chronicle.load(Ordering::Relaxed),
            self.thought.load(Ordering::Relaxed),
            self.background.load(Ordering::Relaxed),
        )
    }
}

enum Signal {
    Connection(Result<DbConnection, String>),
    Applied,
    Disconnected(String),
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Connecting,
    Syncing,
    Live,
    Offline,
}

pub struct Net {
    pub server: String,
    pub db: String,
    pub conn: Option<DbConnection>,
    pub status: Status,
    pub detail: String,
    pub gens: Generations,
    inbox: Arc<Mutex<Vec<Signal>>>,
    connecting: bool,
    retry_at: f64,
    exp_live: Option<ExpSub>,
    exp_pending: Option<ExpSub>,
    /// Resource rows (thousands on a realm) are copied only when the table changes.
    pub resource_cache: std::cell::RefCell<(u32, Arc<Vec<ResourceNode>>)>,
}

impl Default for Net {
    fn default() -> Self {
        let (server, db) = crate::clock::endpoint();
        Self {
            server,
            db,
            conn: None,
            status: Status::Connecting,
            detail: String::new(),
            gens: Generations::default(),
            inbox: Arc::default(),
            connecting: false,
            retry_at: 0.0,
            exp_live: None,
            exp_pending: None,
            resource_cache: std::cell::RefCell::new((u32::MAX, Arc::new(Vec::new()))),
        }
    }
}

fn bump(g: &Arc<AtomicU32>) {
    g.fetch_add(1, Ordering::Relaxed);
}

impl Net {
    /// Keep exactly the selected character's experiences subscribed. The new query is
    /// applied before the old one is dropped so the tab never flashes empty.
    pub fn watch_experiences(&mut self, want: Option<u32>) {
        let Some(conn) = &self.conn else {
            self.exp_live = None;
            self.exp_pending = None;
            return;
        };
        if let Some(p) = &self.exp_pending {
            if p.handle.is_ended() {
                self.exp_pending = None;
            } else if p.handle.is_active() {
                let p = self.exp_pending.take().unwrap();
                if let Some(old) = self.exp_live.take() {
                    if old.handle.is_active() {
                        let _ = old.handle.unsubscribe();
                    }
                }
                self.exp_live = Some(p);
            } else {
                return; // wait for it to apply before changing again
            }
        }
        let live = self.exp_live.as_ref().map(|s| s.actor);
        if live == want {
            return;
        }
        match want {
            Some(actor) => {
                let handle = conn
                    .subscription_builder()
                    .on_error(|_, e| warn!("experience subscription failed: {e}"))
                    .subscribe([
                        format!("SELECT * FROM experience WHERE observer = {actor}"),
                        // Its routines and how each has gone (two-table join on primary keys).
                        format!("SELECT * FROM routine WHERE actor = {actor}"),
                        format!("SELECT s.* FROM routine_stat s JOIN routine r ON s.id = r.id WHERE r.actor = {actor}"),
                    ]);
                self.exp_pending = Some(ExpSub { actor, handle });
            }
            None => {
                if let Some(old) = self.exp_live.take() {
                    if old.handle.is_active() {
                        let _ = old.handle.unsubscribe();
                    }
                }
            }
        }
    }

    /// Whether the given character's experiences are loaded.
    pub fn experiences_ready(&self, actor: u32) -> bool {
        self.exp_live.as_ref().is_some_and(|s| s.actor == actor && s.handle.is_active())
    }

    fn connect(&mut self) {
        self.connecting = true;
        self.status = Status::Connecting;
        let inbox = self.inbox.clone();
        let applied = inbox.clone();
        let gone = inbox.clone();
        let failed = inbox.clone();
        let gens = self.gens.clone();
        let builder = DbConnection::builder()
            .with_uri(self.server.clone())
            .with_database_name(self.db.clone())
            .on_connect(move |conn, _identity, _token| {
                macro_rules! watch {
                    ($table:ident, $gen:ident) => {{
                        let g = gens.$gen.clone();
                        conn.db.$table().on_insert(move |_, _| bump(&g));
                        let g = gens.$gen.clone();
                        conn.db.$table().on_delete(move |_, _| bump(&g));
                        let g = gens.$gen.clone();
                        conn.db.$table().on_update(move |_, _, _| bump(&g));
                    }};
                }
                watch!(terrain_chunk, terrain);
                watch!(resource_node, resources);
                macro_rules! incremental {
                    ($table:ident, $gen:ident, $queue:ident) => {{
                        let q = gens.$queue.clone();
                        conn.db.$table().on_insert(move |_, r| q.lock().unwrap().push(r.clone()));
                        let g = gens.$gen.clone();
                        conn.db.$table().on_delete(move |_, _| bump(&g));
                        let g = gens.$gen.clone();
                        conn.db.$table().on_update(move |_, _, _| bump(&g));
                    }};
                }
                incremental!(chronicle, chronicle, fresh_chronicle);
                incremental!(thought, thought, fresh_thoughts);
                watch!(background, background);
                let inbox = applied.clone();
                let err = applied.clone();
                conn.subscription_builder()
                    .on_applied(move |_| inbox.lock().unwrap().push(Signal::Applied))
                    .on_error(move |_, e| {
                        err.lock().unwrap().push(Signal::Disconnected(format!("subscription error: {e}")))
                    })
                    .subscribe(QUERIES);
            })
            .on_disconnect(move |_, e| {
                let why = e.map(|e| e.to_string()).unwrap_or_else(|| "connection closed".into());
                gone.lock().unwrap().push(Signal::Disconnected(why));
            })
            .on_connect_error(move |_, e| {
                failed.lock().unwrap().push(Signal::Disconnected(format!("connect failed: {e}")));
            });
        #[cfg(target_arch = "wasm32")]
        wasm_bindgen_futures::spawn_local(async move {
            let r = builder.build().await.map_err(|e| e.to_string());
            inbox.lock().unwrap().push(Signal::Connection(r));
        });
        #[cfg(not(target_arch = "wasm32"))]
        std::thread::spawn(move || {
            let r = builder.build().map_err(|e| e.to_string());
            inbox.lock().unwrap().push(Signal::Connection(r));
        });
    }
}

/// Advance the connection and handle lifecycle signals (reconnects after 3 s).
pub fn pump(mut net: NonSendMut<Net>, time: Res<Time>) {
    if let Some(conn) = &net.conn {
        if let Err(e) = conn.frame_tick() {
            let why = e.to_string();
            net.inbox.lock().unwrap().push(Signal::Disconnected(why));
        }
    }
    let signals = std::mem::take(&mut *net.inbox.lock().unwrap());
    let now = time.elapsed_secs_f64();
    for s in signals {
        match s {
            Signal::Connection(Ok(conn)) => {
                net.conn = Some(conn);
                net.connecting = false;
                net.status = Status::Syncing;
                net.detail.clear();
            }
            Signal::Connection(Err(e)) | Signal::Disconnected(e) => {
                if let Some(c) = net.conn.take() {
                    let _ = c.disconnect();
                }
                net.exp_live = None;
                net.exp_pending = None;
                net.connecting = false;
                net.status = Status::Offline;
                net.detail = e;
                net.retry_at = now + 3.0;
                bump(&net.gens.terrain);
                bump(&net.gens.chronicle);
                bump(&net.gens.thought);
                bump(&net.gens.background);
                bump(&net.gens.resources);
            }
            Signal::Applied => {
                info!("world subscribed after {:.1} s", now);
                net.status = Status::Live;
                bump(&net.gens.terrain);
                bump(&net.gens.chronicle);
                bump(&net.gens.thought);
                bump(&net.gens.background);
                bump(&net.gens.resources);
            }
        }
    }
    if net.conn.is_none() && !net.connecting && now >= net.retry_at {
        net.connect();
    }
}
