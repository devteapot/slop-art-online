//! Player connection: a persistent identity (token kept on disk), the player's own rows and a
//! moving window of world chunks around the player.
//!
//! Subscriptions follow the SpacetimeDB subscription guidance (docs/ISLAND_AUTHORITY.md,
//! "SpacetimeDB documentation consulted"): small static tables whole, everything else by a
//! window of 16×16-tile chunks around the player, grouped by lifetime, and the next window
//! subscribed before the previous one is dropped. Fog of war is NOT enforced: the authority
//! still publishes these tables to anyone (docs/GAME_BRIEF.md).
//!
//! 1. On connect: `world`, `land` and `settlement` (1, 1 and about 6 rows).
//! 2. Then by the world's kind ([`Mode`]):
//!    - **land** (a `land` row exists; the island): my characters (`character.controller =
//!      :sender`, indexed). Terrain comes from regenerating the land (`live.rs`), so
//!      `terrain_chunk` is only subscribed in the window, for edits.
//!    - **tiles** (the lab worlds): `terrain_chunk` and `character` whole, as before.
//! 3. My rows: `body`, `vitals`, `experience`, `place`, `inventory` and `know_how` of my
//!    character; for the connection, my combat feed and timing (`my_combat`, `my_readiness`:
//!    per-sender views) and the skill bar's `skill_card` (docs/COMBAT.md).
//! 4. Windows round me:
//!    - land, near: `body` and the characters on those bodies (a join on `body.id`) within
//!      [`BODY_CHUNKS`], and `terrain_chunk` within [`TERRAIN_CHUNKS`] (only edits since world
//!      creation matter there), and the `fighter` rows on those bodies (a join, as for
//!      characters), re-centred when I walk [`RECENTRE`] chunks from its centre;
//!    - land, far: `lot` within [`LOT_CHUNKS`] (buildings show to the island's draw distance),
//!      re-centred after [`LOT_RECENTRE`] chunks. Lots never change, so this window has its own,
//!      longer lifetime: re-sending it with every near move cost about 130 kB a move.
//!
//!    Subscription SQL has no `IN`, so a window is one id range per row of chunks (`id = (cy <<
//!    16) | cx`), joined by `OR`;
//!    - tiles: `body`, `resource_node` and `structure` per chunk within [`REGION_R`].

use bevy::prelude::*;
use living_bindings::*;
use living_rules::map::{chunk_id, chunk_xy, CHUNK};
use spacetimedb_sdk::{DbContext, Identity, SubscriptionHandle as _, Table, TableWithPrimaryKey};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

/// Half-size (tiles) of the square of chunks kept subscribed around the player (tile worlds).
pub const REGION_R: f32 = 40.0;
/// Land worlds: chunks each side of the window's centre for bodies, their characters and
/// terrain edits (5 → an 11 × 11 square, ±88 m), and for lots (11 → 23 × 23, ±184 m, past the
/// island's 170 m draw distance).
pub const BODY_CHUNKS: i32 = 5;
pub const TERRAIN_CHUNKS: i32 = 3;
pub const LOT_CHUNKS: i32 = 11;
/// Re-centre a window once I am this many chunks from its centre (either axis).
pub const RECENTRE: i32 = 2;
pub const LOT_RECENTRE: i32 = 5;

const STATIC: &[&str] = &["SELECT * FROM world", "SELECT * FROM land", "SELECT * FROM settlement"];

enum Signal {
    Connection(Result<DbConnection, String>),
    Identity(Identity, String),
    Static,
    Base,
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

/// The two windows of a land world.
#[derive(Clone, Copy)]
enum Which {
    Near,
    Lots,
}

/// What kind of world the server hosts, known once the static tables are in.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Mode {
    #[default]
    Unknown,
    /// A land world (`land` row): the island, drawn by `island.rs` and `live.rs`.
    Land,
    /// A tile world (lab seeds): drawn by `world.rs` and `bodies.rs`.
    Tiles,
}

struct Sub {
    key: Vec<u32>,
    handle: SubscriptionHandle,
}

/// A moving window: the subscription in place and the one replacing it. The next is subscribed
/// before the current is dropped (SpacetimeDB subscription guidance).
#[derive(Default)]
struct Window {
    current: Option<Sub>,
    next: Option<Sub>,
}

impl Window {
    /// The window subscribed or being subscribed.
    fn wanted(&self) -> Option<&Vec<u32>> {
        self.next.as_ref().or(self.current.as_ref()).map(|s| &s.key)
    }

    /// A newer window replaces one still being applied.
    fn replace(&mut self, next: Option<Sub>) {
        if let Some(old) = self.next.take() {
            let _ = old.handle.unsubscribe();
        }
        self.next = next;
    }

    /// Drop the previous window only once the next one is in.
    fn settle(&mut self) {
        if self.next.as_ref().is_some_and(|s| s.handle.is_active()) {
            if let Some(old) = self.current.take() {
                let _ = old.handle.unsubscribe();
            }
            self.current = self.next.take();
        }
    }
}

pub struct Net {
    pub server: String,
    pub db: String,
    pub name: String,
    pub conn: Option<DbConnection>,
    pub status: Status,
    pub mode: Mode,
    pub detail: String,
    pub me: Option<Identity>,
    /// My living character, once the authority has one for my identity.
    pub my_id: Option<u32>,
    pub errors: Arc<Mutex<Vec<String>>>,
    /// Latest `t_ms` among body rows updated since the display clock last looked.
    pub body_t: Arc<AtomicU64>,
    /// Window moves (re-subscriptions) since connecting, for measurements.
    pub window_moves: u32,
    inbox: Arc<Mutex<Vec<Signal>>>,
    connecting: bool,
    retry_at: f64,
    join_sent: bool,
    base: Option<SubscriptionHandle>,
    mine: Option<Sub>,
    near: Window,
    far: Window,
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
            mode: Mode::Unknown,
            detail: String::new(),
            me: None,
            my_id: None,
            errors: Arc::default(),
            body_t: Arc::default(),
            window_moves: 0,
            inbox: Arc::default(),
            connecting: false,
            retry_at: 0.0,
            join_sent: false,
            base: None,
            mine: None,
            near: Window::default(),
            far: Window::default(),
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

/// `(col >= a AND col <= b) OR …`: one id range per row of chunks of the square `cx0..=cx1` ×
/// `cy0..=cy1` (chunk ids are `(cy << 16) | cx`, so a row is contiguous).
pub fn chunk_ranges(col: &str, (cx0, cx1): (u32, u32), (cy0, cy1): (u32, u32)) -> String {
    (cy0..=cy1).map(|cy| format!("({col} >= {} AND {col} <= {})", chunk_id(cx0, cy), chunk_id(cx1, cy))).collect::<Vec<_>>().join(" OR ")
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
                    .on_applied(move |_| ok.lock().unwrap().push(Signal::Static))
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

    /// The static tables are in: pick the mode and subscribe what it needs before playing.
    fn subscribe_base(&mut self) {
        let Some(conn) = self.conn.as_ref() else { return };
        self.mode = if conn.db.land().count() > 0 { Mode::Land } else { Mode::Tiles };
        let queries: &[&str] = match self.mode {
            // My combat feed and timing (per-sender views: only my identity's rows) for the
            // connection's lifetime, so the death screen keeps them after my character dies;
            // the rules' numbers for the skill bar (`skill_card`, 6 rows; docs/COMBAT.md).
            Mode::Land => &["SELECT * FROM character WHERE controller = :sender", "SELECT * FROM my_combat", "SELECT * FROM my_readiness", "SELECT * FROM skill_card"],
            _ => &["SELECT * FROM terrain_chunk", "SELECT * FROM character"],
        };
        info!("world kind: {:?}", self.mode);
        let (ok, err) = (self.inbox.clone(), self.inbox.clone());
        self.base = Some(
            conn.subscription_builder()
                .on_applied(move |_| ok.lock().unwrap().push(Signal::Base))
                .on_error(move |_, e| err.lock().unwrap().push(Signal::Error(format!("subscription error: {e}"))))
                .subscribe(queries),
        );
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

    /// The land world's row, if this is one.
    pub fn land(&self) -> Option<LandInfo> {
        self.conn.as_ref()?.db.land().iter().next()
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
            self.near = Window::default();
            self.far = Window::default();
            if let Some(id) = found {
                info!("playing character #{id}");
                let q = vec![
                    format!("SELECT * FROM body WHERE id = {id}"),
                    format!("SELECT * FROM vitals WHERE id = {id}"),
                    format!("SELECT * FROM experience WHERE observer = {id}"),
                    // My character's known places, for the compass (`place.actor` is indexed).
                    format!("SELECT * FROM place WHERE actor = {id}"),
                    // What my skills need: arrows and a bow, and know-how (both indexed).
                    format!("SELECT * FROM inventory WHERE owner = {id}"),
                    format!("SELECT * FROM know_how WHERE actor = {id}"),
                ];
                self.mine = self.subscribe(q, vec![id]);
            }
        }
        let Some(body) = self.my_body() else { return };
        let (near, far) = match self.mode {
            Mode::Land => (self.land_window(&body, Which::Near), self.land_window(&body, Which::Lots)),
            _ => (self.tile_window(&body), None),
        };
        if let Some((key, q)) = near {
            self.window_moves += 1;
            let sub = self.subscribe(q, key);
            self.near.replace(sub);
        }
        if let Some((key, q)) = far {
            let sub = self.subscribe(q, key);
            self.far.replace(sub);
        }
        self.near.settle();
        self.far.settle();
    }

    /// Tile worlds: one query per chunk and table, when the set of chunks changes.
    fn tile_window(&self, body: &Body) -> Option<(Vec<u32>, Vec<String>)> {
        let (w, h) = self.map_size();
        let mut chunks: Vec<u32> = living_rules::map::chunks_around(body.x, body.y, REGION_R)
            .into_iter()
            .filter(|c| {
                let (cx, cy) = chunk_xy(*c);
                cx * CHUNK < w && cy * CHUNK < h
            })
            .collect();
        chunks.sort_unstable();
        if self.near.wanted() == Some(&chunks) {
            return None;
        }
        let mut q = Vec::with_capacity(chunks.len() * 3);
        for c in &chunks {
            q.push(format!("SELECT * FROM body WHERE chunk = {c}"));
            q.push(format!("SELECT * FROM resource_node WHERE chunk = {c}"));
            q.push(format!("SELECT * FROM structure WHERE chunk = {c}"));
        }
        Some((chunks, q))
    }

    /// Land worlds: a square window of chunk ranges around a centre chunk, kept until I am
    /// far enough from it. The key is the centre chunk.
    fn land_window(&self, body: &Body, which: Which) -> Option<(Vec<u32>, Vec<String>)> {
        let (w, h) = self.map_size();
        let (nx, ny) = ((w / CHUNK) as i32, (h / CHUNK) as i32);
        let here = ((body.x / CHUNK as f32).floor() as i32, (body.y / CHUNK as f32).floor() as i32);
        let (window, recentre, r) = match which {
            Which::Near => (&self.near, RECENTRE, BODY_CHUNKS),
            Which::Lots => (&self.far, LOT_RECENTRE, LOT_CHUNKS),
        };
        if let Some(key) = window.wanted() {
            let (cx, cy) = chunk_xy(key[0]);
            if (here.0 - cx as i32).abs() < recentre && (here.1 - cy as i32).abs() < recentre {
                return None;
            }
        }
        let (cx, cy) = (here.0.clamp(0, nx - 1), here.1.clamp(0, ny - 1));
        let span = |c: i32, n: i32, r: i32| ((c - r).max(0) as u32, (c + r).min(n - 1) as u32);
        let (xs, ys) = (span(cx, nx, r), span(cy, ny, r));
        let (tx, ty) = (span(cx, nx, TERRAIN_CHUNKS), span(cy, ny, TERRAIN_CHUNKS));
        let q = match which {
            Which::Near => vec![
                format!("SELECT * FROM body WHERE {}", chunk_ranges("chunk", xs, ys)),
                // The characters standing in the window (names, kind, life stage, home), through
                // their bodies: both join columns are primary keys.
                format!("SELECT character.* FROM character JOIN body ON character.id = body.id WHERE {}", chunk_ranges("body.chunk", xs, ys)),
                // How the fighters in the window look: health band and the move under way.
                format!("SELECT fighter.* FROM fighter JOIN body ON fighter.id = body.id WHERE {}", chunk_ranges("body.chunk", xs, ys)),
                format!("SELECT * FROM terrain_chunk WHERE {}", chunk_ranges("id", tx, ty)),
            ],
            Which::Lots => vec![format!("SELECT * FROM lot WHERE {}", chunk_ranges("chunk", xs, ys))],
        };
        Some((vec![chunk_id(cx as u32, cy as u32)], q))
    }

    /// Ask for a new character after my death (the death screen's "Arrive as a new stranger"):
    /// the next `maintain` joins again.
    pub fn rejoin(&mut self) {
        self.join_sent = false;
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
            Signal::Static => net.subscribe_base(),
            Signal::Base => {
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
                net.base = None;
                net.mine = None;
                net.near = Window::default();
                net.far = Window::default();
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
