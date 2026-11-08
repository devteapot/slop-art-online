//! Player connection: a persistent identity (token kept on disk), the player's own rows and a
//! moving window of world chunks around the player.
//!
//! Subscriptions follow the region-based design in the SpacetimeDB views/subscriptions docs:
//! world rows are subscribed by 16×16-tile chunk (`body`, `resource_node` and `structure`
//! are indexed by `chunk`), and the next window is subscribed before the previous one is
//! dropped. Fog of war is NOT enforced: the authority still publishes these tables to anyone,
//! and `character` and `terrain_chunk` are subscribed whole (see docs/GAME_BRIEF.md).

use bevy::prelude::*;
use living_bindings::*;
use spacetimedb_sdk::{DbContext, Identity, SubscriptionHandle as _, Table, TableWithPrimaryKey};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

/// Half-size (tiles) of the square of chunks kept subscribed around the player.
pub const REGION_R: f32 = 40.0;

const STATIC: &[&str] = &["SELECT * FROM world", "SELECT * FROM terrain_chunk", "SELECT * FROM character"];

enum Signal {
    Connection(Result<DbConnection, String>),
    Identity(Identity, String),
    Applied,
    Disconnected(String),
    Error(String),
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Status {
    Connecting,
    Syncing,
    Live,
    Offline,
}

struct Sub {
    key: Vec<u32>,
    handle: SubscriptionHandle,
}

pub struct Net {
    pub server: String,
    pub db: String,
    pub name: String,
    pub conn: Option<DbConnection>,
    pub status: Status,
    pub detail: String,
    pub me: Option<Identity>,
    /// My living character, once the authority has one for my identity.
    pub my_id: Option<u32>,
    pub errors: Arc<Mutex<Vec<String>>>,
    /// Latest `t_ms` among body rows updated since the display clock last looked.
    pub body_t: Arc<AtomicU64>,
    inbox: Arc<Mutex<Vec<Signal>>>,
    connecting: bool,
    retry_at: f64,
    join_sent: bool,
    mine: Option<Sub>,
    region: Option<Sub>,
    region_next: Option<Sub>,
}

impl Default for Net {
    fn default() -> Self {
        let (server, db) = crate::clock::endpoint();
        let name = std::env::var("LIVING_GAME_NAME").unwrap_or_else(|_| "Wanderer".into());
        Self {
            server,
            db,
            name,
            conn: None,
            status: Status::Connecting,
            detail: String::new(),
            me: None,
            my_id: None,
            errors: Arc::default(),
            body_t: Arc::default(),
            inbox: Arc::default(),
            connecting: false,
            retry_at: 0.0,
            join_sent: false,
            mine: None,
            region: None,
            region_next: None,
        }
    }
}

/// Where this database's player token is kept: `LIVING_GAME_TOKEN`, else
/// `.local/living/game/<db>.token` under the working directory (git-ignored).
fn token_path(db: &str) -> PathBuf {
    std::env::var("LIVING_GAME_TOKEN")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(format!(".local/living/game/{db}.token")))
}

impl Net {
    pub fn report(&self, what: &str, r: Result<(), spacetimedb_sdk::Error>) {
        if let Err(e) = r {
            self.errors.lock().unwrap().push(format!("{what}: {e}"));
        }
    }

    /// Record a reducer's refusal (the authority's error text) for the HUD.
    pub fn on_reply(&self, what: &'static str) -> impl FnOnce(&ReducerEventContext, Result<Result<(), String>, spacetimedb_sdk::__codegen::InternalError>) + Send + 'static {
        let errors = self.errors.clone();
        move |_, r| {
            let msg = match r {
                Ok(Ok(())) => return,
                Ok(Err(e)) => format!("{what} refused: {e}"),
                Err(e) => format!("{what} failed: {e}"),
            };
            warn!("{msg}");
            errors.lock().unwrap().push(msg);
        }
    }

    fn connect(&mut self) {
        self.connecting = true;
        self.status = Status::Connecting;
        let path = token_path(&self.db);
        let token = std::fs::read_to_string(&path).ok().map(|t| t.trim().to_string()).filter(|t| !t.is_empty());
        let (inbox, applied, gone, failed) = (self.inbox.clone(), self.inbox.clone(), self.inbox.clone(), self.inbox.clone());
        let body_t = self.body_t.clone();
        let builder = DbConnection::builder()
            .with_uri(self.server.clone())
            .with_database_name(self.db.clone())
            .with_token(token)
            .on_connect(move |conn, identity, token| {
                applied.lock().unwrap().push(Signal::Identity(identity, token.to_string()));
                conn.db.body().on_update(move |_, _, new| {
                    body_t.fetch_max(new.t_ms, Ordering::Relaxed);
                });
                let ok = applied.clone();
                let err = applied.clone();
                conn.subscription_builder()
                    .on_applied(move |_| ok.lock().unwrap().push(Signal::Applied))
                    .on_error(move |_, e| err.lock().unwrap().push(Signal::Error(format!("subscription error: {e}"))))
                    .subscribe(STATIC);
            })
            .on_disconnect(move |_, e| {
                let why = e.map(|e| e.to_string()).unwrap_or_else(|| "connection closed".into());
                gone.lock().unwrap().push(Signal::Disconnected(why));
            })
            .on_connect_error(move |_, e| failed.lock().unwrap().push(Signal::Disconnected(format!("connect failed: {e}"))));
        std::thread::spawn(move || {
            let r = builder.build().map_err(|e| e.to_string());
            inbox.lock().unwrap().push(Signal::Connection(r));
        });
    }

    fn subscribe(&self, queries: Vec<String>, key: Vec<u32>) -> Option<Sub> {
        let conn = self.conn.as_ref()?;
        let inbox = self.inbox.clone();
        let handle = conn
            .subscription_builder()
            .on_error(move |_, e| inbox.lock().unwrap().push(Signal::Error(format!("subscription error: {e}"))))
            .subscribe(queries);
        Some(Sub { key, handle })
    }

    /// My character: alive, not AI-driven, controlled by my identity.
    fn find_me(&self) -> Option<u32> {
        let (conn, me) = (self.conn.as_ref()?, self.me?);
        conn.db.character().iter().find(|c| c.controller == me && c.alive && !c.ai).map(|c| c.id)
    }

    pub fn my_body(&self) -> Option<Body> {
        self.conn.as_ref()?.db.body().id().find(&self.my_id?)
    }

    /// Keep my own rows and the chunk window around me subscribed.
    fn maintain(&mut self) {
        if self.status != Status::Live {
            return;
        }
        let found = self.find_me();
        if found.is_none() && !self.join_sent {
            self.join_sent = true;
            if let Some(conn) = &self.conn {
                info!("joining as {}", self.name);
                let r = conn.reducers.join_then(self.name.clone(), self.on_reply("join"));
                self.report("join", r);
            }
        }
        if found != self.my_id {
            self.my_id = found;
            self.mine = None;
            self.region = None;
            self.region_next = None;
            if let Some(id) = found {
                info!("playing character #{id}");
                let q = vec![
                    format!("SELECT * FROM body WHERE id = {id}"),
                    format!("SELECT * FROM vitals WHERE id = {id}"),
                    format!("SELECT * FROM experience WHERE observer = {id}"),
                ];
                self.mine = self.subscribe(q, vec![id]);
            }
        }
        let Some(body) = self.my_body() else { return };
        let (w, h) = self.map_size();
        let mut chunks: Vec<u32> = living_rules::map::chunks_around(body.x, body.y, REGION_R)
            .into_iter()
            .filter(|c| {
                let (cx, cy) = living_rules::map::chunk_xy(*c);
                cx * living_rules::map::CHUNK < w && cy * living_rules::map::CHUNK < h
            })
            .collect();
        chunks.sort_unstable();
        let wanted = self.region_next.as_ref().or(self.region.as_ref()).map(|s| &s.key);
        if wanted != Some(&chunks) {
            let mut q = Vec::with_capacity(chunks.len() * 3);
            for c in &chunks {
                q.push(format!("SELECT * FROM body WHERE chunk = {c}"));
                q.push(format!("SELECT * FROM resource_node WHERE chunk = {c}"));
                q.push(format!("SELECT * FROM structure WHERE chunk = {c}"));
            }
            // A newer window replaces one still being applied.
            if let Some(old) = self.region_next.take() {
                let _ = old.handle.unsubscribe();
            }
            self.region_next = self.subscribe(q, chunks);
        }
        // Drop the previous window only once the next one is in.
        if self.region_next.as_ref().is_some_and(|s| s.handle.is_active()) {
            if let Some(old) = self.region.take() {
                let _ = old.handle.unsubscribe();
            }
            self.region = self.region_next.take();
        }
    }

    pub fn map_size(&self) -> (u32, u32) {
        self.conn.as_ref().and_then(|c| c.db.world().iter().next()).map_or((96, 96), |w| (w.width, w.height))
    }
}

/// Advance the connection, handle lifecycle signals (reconnect after 3 s), keep subscriptions.
pub fn pump(mut net: NonSendMut<Net>, time: Res<Time>) {
    if let Some(conn) = &net.conn {
        if let Err(e) = conn.frame_tick() {
            net.inbox.lock().unwrap().push(Signal::Disconnected(e.to_string()));
        }
    }
    let now = time.elapsed_secs_f64();
    let signals = std::mem::take(&mut *net.inbox.lock().unwrap());
    for s in signals {
        match s {
            Signal::Connection(Ok(conn)) => {
                net.conn = Some(conn);
                net.connecting = false;
                net.status = Status::Syncing;
                net.detail.clear();
            }
            Signal::Identity(identity, token) => {
                net.me = Some(identity);
                let path = token_path(&net.db);
                if let Some(dir) = path.parent() {
                    let _ = std::fs::create_dir_all(dir);
                }
                if let Err(e) = std::fs::write(&path, token) {
                    warn!("could not keep the player token at {}: {e}", path.display());
                }
                info!("connected as {identity}");
            }
            Signal::Applied => {
                info!("world subscribed after {now:.1} s");
                net.status = Status::Live;
            }
            Signal::Error(e) => {
                warn!("{e}");
                net.errors.lock().unwrap().push(e);
            }
            Signal::Disconnected(e) => {
                warn!("offline: {e}");
                if let Some(c) = net.conn.take() {
                    let _ = c.disconnect();
                }
                net.mine = None;
                net.region = None;
                net.region_next = None;
                net.my_id = None;
                net.join_sent = false;
                net.connecting = false;
                net.status = Status::Offline;
                net.detail = e;
                net.retry_at = now + 3.0;
            }
            Signal::Connection(Err(e)) => {
                net.connecting = false;
                net.status = Status::Offline;
                net.detail = e;
                net.retry_at = now + 3.0;
            }
        }
    }
    if net.conn.is_none() && !net.connecting && now >= net.retry_at {
        net.connect();
    }
    net.maintain();
}
