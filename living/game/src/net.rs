//! Player connection: a persistent identity (token kept on disk), the player's own rows and a
//! moving window of world chunks around the player.
//!
//! Subscriptions follow the SpacetimeDB subscription guidance (docs/ISLAND_AUTHORITY.md,
//! "SpacetimeDB documentation consulted"): small static tables whole, everything else by a
//! window of 16×16-tile chunks around the player, grouped by lifetime, and the next window
//! subscribed before the previous one is dropped. What my character perceives and its own
//! state come from per-sender views on the authority, which enforces the perception boundary
//! (docs/PERCEPTION.md): nothing of a creature beyond my sight or behind a wall reaches me.
//!
//! 1. On connect: `cover_law`, `world`, `land`, `settlement` and `feed_scope` (1, 1, about 6 rows,
//!    and one or none: its stage chooses where structures, gates and resources come from, `feed.rs`).
//! 2. Then, for the connection's lifetime (so the death screen keeps its rows):
//!    - what I perceive: `seen_characters` (mine too), and the others' motion, fighter and
//!      doing rows as a set of their own, chosen by the world's delivery laws once the installed
//!      script is compiled (`perception_law`): the near and far tier views and their cue tables,
//!      or, while `cue_transport_on` and `near_tier_on` are both off, `seen_bodies`,
//!      `seen_fighters` and `seen_doing` as on main;
//!    - my own state: my body, fighter and doing rows (`my_body`, `my_fighter`, `my_doing`),
//!      `my_characters` (the one I play, kept after its death until I join again),
//!      `my_vitals`, `my_experience`, `my_places`, `my_inventory`, `my_know_how`, my combat
//!      feed and timing (`my_combat`, `my_readiness`) and the skill bar's `skill_card` (docs/COMBAT.md); the visible skills'
//!      `act_card` and the one `weather` row (docs/TOWN_LIFE.md), both small and nearly static;
//!      the world's installed skill script (`script`, the `skills` row: about 70 kB, sent again
//!      only when a script is installed), from which `verbs.rs` offers acts, and the world's own
//!      law values laid over it (`law_override`: a value-only law changes there alone);
//!    - by the world's kind ([`Mode`]): **land** (a `land` row exists; the island): terrain
//!      comes from regenerating the land (`live.rs`), so `terrain_chunk` is only subscribed in
//!      the window, for edits; **tiles** (the lab worlds): `terrain_chunk` whole.
//! 3. Windows of static data round me:
//!    - land, near: `terrain_chunk` within [`TERRAIN_CHUNKS`] (only edits since world creation
//!      matter there), and the `resource_node` and `structure` rows there (what F can act on:
//!      bushes, hearths, stores, signs; about 4 resources a chunk on the island), re-centred
//!      when I walk [`RECENTRE`] chunks from its centre;
//!    - land, far: `lot` within [`LOT_CHUNKS`] (buildings show to the island's draw distance),
//!      re-centred after [`LOT_RECENTRE`] chunks. Lots never change, so this window has its own,
//!      longer lifetime: re-sending it with every near move cost about 130 kB a move.
//!
//!    Subscription SQL has no `IN`, so a window is one id range per row of chunks (`id = (cy <<
//!    16) | cx`), joined by `OR`;
//!    - tiles: `resource_node` and `structure` per chunk within [`REGION_R`].
//! 4. Public-feed scoping (docs/FEED_SCOPING.md, `feed.rs`): those are the legacy feed's, at
//!    `feed_scope.stage` 0 (`gate` whole in the base on land worlds). At stage ≥ 1 the base holds
//!    `my_things`, `my_remembered_things`, `my_owners`, `my_stock` and `my_fuel_seen` instead, and
//!    the near window `map_resource` and `map_structure` over the same chunks. A crossing of 0 ↔ 1
//!    subscribes a whole new base and the near window beside the old ones and drops the old ones
//!    once both are in (`Net::switch_feed`), independent of the perception set's switch.
//!
//! Latency (docs/LATENCY.md, steps 1–3): the game reads unconfirmed (`with_confirmed_reads(false)`,
//! SpacetimeDB's advice for real-time games: a delivery does not wait for the commit's fsync;
//! after a server crash a client may have seen up to one batch the world no longer has, and a
//! reconnect brings the durable state); [`flush`] sends what the input systems called in the
//! same frame; the display clock learns its delay only from bodies whose segment changed
//! (`body_t`), not from bodies entering view with old segments.

use bevy::prelude::*;
use living_bindings::*;
use living_rules::map::{chunk_id, chunk_xy, CHUNK};
use living_rules::sight::GazeBand;
use spacetimedb_sdk::{DbContext, EventTable, Identity, SubscriptionHandle as _, Table, TableWithPrimaryKey};
use std::collections::HashMap;
use std::ops::Deref;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// Half-size (tiles) of the square of chunks kept subscribed around the player (tile worlds).
pub const REGION_R: f32 = 40.0;
/// Land worlds: chunks each side of the window's centre for terrain edits (3 → a 7 × 7 square),
/// and for lots (11 → 23 × 23, ±184 m, past the island's 170 m draw distance).
pub const TERRAIN_CHUNKS: i32 = 3;
pub const LOT_CHUNKS: i32 = 11;
/// Re-centre a window once I am this many chunks from its centre (either axis).
pub const RECENTRE: i32 = 2;
pub const LOT_RECENTRE: i32 = 5;

/// The world's one `feed_scope` row is among them: its stage chooses where structures, gates and
/// resources come from (`feed.rs`) before the base is subscribed.
const STATIC: &[&str] = &["SELECT * FROM cover_law", "SELECT * FROM world", "SELECT * FROM land", "SELECT * FROM settlement", "SELECT * FROM feed_scope"];
/// What my character perceives and its own state (per-sender views, docs/PERCEPTION.md), and
/// the rules' cards, for the connection's lifetime.
const PERCEIVED: &[&str] = &[
    "SELECT * FROM seen_characters",
    // My own body, move and act, apart from my scene's: my own changes re-run one row.
    "SELECT * FROM my_body",
    "SELECT * FROM my_fighter",
    "SELECT * FROM my_doing",
    "SELECT * FROM my_characters",
    "SELECT * FROM my_vitals",
    "SELECT * FROM my_experience",
    "SELECT * FROM my_places",
    "SELECT * FROM my_inventory",
    "SELECT * FROM my_know_how",
    "SELECT * FROM my_combat",
    "SELECT * FROM my_readiness",
    // Offers to me and mine (a few rows, each gone when taken, withdrawn or out of time), and my
    // records (an agreement proposed to me changes what Accept does): `ui/people.rs`.
    "SELECT * FROM my_offers",
    // Whom my character knows by name (owner-known): a house is "{name}'s house" only then.
    "SELECT * FROM my_known_names",
    // Who would hear me now at each way, and its sentence (the `earshot` law; no row while it
    // is off): `talk.rs`, the box's hint line.
    "SELECT * FROM my_earshot",
    // The world's ways of speaking (label, order, whether a line needs someone, reach, limits):
    // the talk box's way chip (`talk.rs`).
    "SELECT * FROM speech_card",
    "SELECT * FROM my_records",
    // What I hear but don't see (rows only while the world's `fov_on` law is on): `heardmark.rs`.
    "SELECT * FROM heard_sounds",
    // My senses as the authority reckons them (one row; written when a value changes): the
    // edge of sight and its field draw from it (`sightedge.rs`).
    "SELECT * FROM my_senses",
    // My acts' outcomes, structured (one row per outcome line, its id the line's): `verbs.rs`
    // notes and the death screen read them instead of parsing the line.
    "SELECT * FROM my_act_outcomes",
    "SELECT * FROM skill_card",
    // What residents are seen doing is named by `act_card` (17 rows); `weather` is one row.
    "SELECT * FROM act_card",
    "SELECT * FROM weather",
    // The rules themselves, for offering acts (`verbs.rs`): one row, changed only by installs.
    "SELECT * FROM script WHERE name = 'skills'",
    // The world's own law values (tens of rows, one per law ever set; written by `set_world_law`
    // and a seed's `rules`), laid over the compiled script (`verbs::Rules`, docs/LAW_OVERRIDE.md):
    // a value-only law (the delivery, cover and gaze laws) changes here alone, with the script
    // row and its revision untouched. Beside `script` in one set, so the first result after a
    // connect or reconnect holds both, and the laws are in force before a law is read.
    "SELECT * FROM law_override",
];

/// Bumped by every `law_override` insert, update and delete this process's connections see, and
/// once when a connection's base set is applied (a world whose rows all went while I was away
/// sends no delete): `verbs::Rules` lays the rows over again when it moves.
static LAW_ROWS: AtomicU64 = AtomicU64::new(0);

/// How many times the `law_override` rows have changed here (`LAW_ROWS`).
pub fn law_rows() -> u64 {
    LAW_ROWS.load(Ordering::Acquire)
}

fn law_rows_moved() {
    LAW_ROWS.fetch_add(1, Ordering::AcqRel);
}

enum Signal {
    Connection(Result<PlayerConnection, String>),
    Identity(Identity, String),
    Static,
    Base,
    GazeReply(GazeBand, GazeReply),
    Disconnected(String),
    Error(String),
}

const GAZE_INTERVAL: Duration = Duration::from_millis(250);

enum GazeReply {
    Accepted,
    Retry,
    Refused,
}

#[derive(Default)]
struct GazeInput {
    desired: GazeBand,
    owner: Option<u32>,
    applied: Option<GazeBand>,
    pending: Option<GazeBand>,
    accepted: Option<GazeBand>,
    refused: Option<GazeBand>,
    retry_at: Option<Instant>,
}

impl GazeInput {
    fn next(&self, now: Instant) -> Option<GazeBand> {
        let applied = self.applied?;
        (self.pending.is_none()
            && self.retry_at.is_none_or(|at| now >= at)
            && self.desired != self.accepted.unwrap_or(applied)
            && self.refused != Some(self.desired))
            .then_some(self.desired)
    }

    fn reply(&mut self, band: GazeBand, reply: GazeReply, now: Instant) {
        if self.pending != Some(band) {
            return;
        }
        self.pending = None;
        self.retry_at = Some(now + GAZE_INTERVAL);
        match reply {
            GazeReply::Accepted => self.accepted = (self.applied != Some(band)).then_some(band),
            GazeReply::Retry => {}
            GazeReply::Refused => self.refused = Some(band),
        }
    }

    fn reset_owner(&mut self) {
        *self = Self { desired: self.desired, ..Self::default() };
    }
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
    pub conn: Option<PlayerConnection>,
    pub status: Status,
    pub mode: Mode,
    pub detail: String,
    pub me: Option<Identity>,
    /// My living character, once the authority has one for my identity.
    pub my_id: Option<u32>,
    pub errors: Arc<Mutex<Vec<String>>>,
    /// Latest `t_ms` among body rows whose segment changed since the display clock last looked.
    pub body_t: Arc<AtomicU64>,
    /// The same over every row inserted or updated (the feed before 2026-11-10), for a shadow
    /// clock that `bodies.rs` logs beside the real one.
    pub body_t_all: Arc<AtomicU64>,
    /// Window moves (re-subscriptions) since connecting, for measurements.
    pub window_moves: u32,
    inbox: Arc<Mutex<Vec<Signal>>>,
    connecting: bool,
    /// When the next attempt goes (elapsed s), how many have gone, and whether one ever got
    /// through (the first load's cover says what is wrong until then: `loading.rs`).
    pub retry_at: f64,
    pub attempts: u32,
    pub ever_live: bool,
    join_sent: bool,
    /// The call `on_reply` just logged, for `report` (`actions.rs`).
    last_call: std::cell::Cell<Option<crate::actions::Sent>>,
    /// The base subscription (the perceived set, the world kind's tables and the feed's base
    /// queries) and the feed it carries.
    base: Option<(crate::feed::Feed, SubscriptionHandle)>,
    /// A base for the other feed, subscribed when `feed_scope.stage` crossed 0 ↔ 1, replacing
    /// `base` once it and the near window for its feed are applied (`switch_feed`), and when it
    /// was asked for (elapsed s).
    base_next: Option<(crate::feed::Feed, SubscriptionHandle)>,
    feed_asked: f64,
    gaze_view: Option<SubscriptionHandle>,
    gaze: GazeInput,
    near: Window,
    far: Window,
    /// The perception streams' set: key [`TIERED`] or [`UNTIERED`] (`perception_law`).
    perception: Window,
    /// When the set being subscribed was asked for (elapsed s), for the switch's log line.
    perception_asked: f64,
}

/// The perception sets' keys in [`Net::perception`].
const TIERED: u32 = 0;
const UNTIERED: u32 = 1;

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
            body_t_all: Arc::default(),
            window_moves: 0,
            inbox: Arc::default(),
            connecting: false,
            retry_at: 0.0,
            attempts: 0,
            ever_live: false,
            join_sent: false,
            last_call: Default::default(),
            base: None,
            base_next: None,
            feed_asked: 0.0,
            gaze_view: None,
            gaze: GazeInput::default(),
            near: Window::default(),
            far: Window::default(),
            perception: Window::default(),
            perception_asked: 0.0,
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

type Overlay<T> = Arc<Mutex<HashMap<u32, T>>>;

#[derive(Default)]
struct Cues {
    motion: Overlay<Moving>,
    fighter: Overlay<Option<Fighter>>,
    doing: Overlay<Option<Doing>>,
    /// The world's `cue_transport_on` law, as the installed `skills` script last compiled here
    /// says (`perception_law`); unknown until then, when cues are taken (the authority writes none
    /// while the law is off). Off: overlays are cleared and no cue is taken.
    off: AtomicBool,
    /// Reads take the untiered views (`seen_bodies`, `seen_fighters`, `seen_doing`): the set in
    /// place is the untiered one (`Perception`). Else the tiers and the overlays.
    untiered: AtomicBool,
}

/// The player's SDK connection and its transient cue state. Each reconnect gets fresh overlays.
pub struct PlayerConnection {
    sdk: DbConnection,
    cues: Arc<Cues>,
}

impl PlayerConnection {
    /// How many creatures each overlay holds (motion, fighter, doing), for the live report.
    pub fn cue_counts(&self) -> (usize, usize, usize) {
        self.cues.counts()
    }

    /// Whether reads take the untiered views (the untiered set is in place).
    pub fn untiered(&self) -> bool {
        self.cues.untiered.load(Ordering::Relaxed)
    }

    /// The others I perceive by the set in place (id, segment `t_ms`), for the seen log.
    fn perceived_rows(&self, untiered: bool) -> Vec<(u32, u64)> {
        if untiered {
            motion::all(&self.db).iter().map(|m| (m.id, m.t_ms)).collect()
        } else {
            let o = self.cues.motion.lock().unwrap();
            motion::near(&self.db).iter().chain(motion::far(&self.db).iter()).map(|m| (m.id, o.get(&m.id).map_or(m.t_ms, |c| c.t_ms))).collect()
        }
    }
}

impl Deref for PlayerConnection {
    type Target = DbConnection;

    fn deref(&self) -> &DbConnection {
        &self.sdk
    }
}

// Keep the SQL names and generated SDK accessors for each stream together. The
// reads and callbacks below use these adapters so a tier rename has one edit point.
// Two sets of queries: the tiered set (each stream's near and far tier and its cue table) and,
// while both of the world's delivery laws are off, the untiered set (each stream's one view, as
// main's client subscribes): `Perception`, `perception_law`.
macro_rules! perception_streams {
    ($($stream:ident {
        all: $all:ident => $all_handle:ident,
        near: $near:ident => $near_handle:ident,
        far: $far:ident => $far_handle:ident,
        cue: $cue:ident => $cue_handle:ident, $cue_row:ty => $overlay:ty,
        |$row:ident| $key:expr, $value:expr
    }),+ $(,)?) => {
        const TIERED_STREAMS: &[&str] = &[
            $(concat!("SELECT * FROM ", stringify!($near)),
              concat!("SELECT * FROM ", stringify!($far)),
              concat!("SELECT * FROM ", stringify!($cue)),)+
        ];
        const UNTIERED_STREAMS: &[&str] = &[$(concat!("SELECT * FROM ", stringify!($all)),)+];

        $(
            pub(crate) mod $stream {
                use super::*;

                pub(crate) fn all(db: &RemoteTables) -> $all_handle<'_> {
                    db.$all()
                }

                pub(crate) fn near(db: &RemoteTables) -> $near_handle<'_> {
                    db.$near()
                }

                pub(crate) fn far(db: &RemoteTables) -> $far_handle<'_> {
                    db.$far()
                }

                pub(super) fn cue(db: &RemoteTables) -> $cue_handle<'_> {
                    db.$cue()
                }

                pub(super) fn cue_value($row: &$cue_row) -> (u32, &$overlay) {
                    ($key, $value)
                }
            }
        )+
    };
}

perception_streams! {
    motion {
        all: seen_bodies => SeenBodiesTableHandle,
        near: seen_bodies_near => SeenBodiesNearTableHandle,
        far: seen_bodies_far => SeenBodiesFarTableHandle,
        cue: seen_body_cue => SeenBodyCueTableHandle, SeenBodyCue => Moving,
        |row| row.motion.id, &row.motion
    },
    fighting {
        all: seen_fighters => SeenFightersTableHandle,
        near: seen_fighters_near => SeenFightersNearTableHandle,
        far: seen_fighters_far => SeenFightersFarTableHandle,
        cue: seen_fighter_cue => SeenFighterCueTableHandle, SeenFighterCue => Option<Fighter>,
        |row| row.body, &row.fighter
    },
    activity {
        all: seen_doing => SeenDoingTableHandle,
        near: seen_doing_near => SeenDoingNearTableHandle,
        far: seen_doing_far => SeenDoingFarTableHandle,
        cue: seen_doing_cue => SeenDoingCueTableHandle, SeenDoingCue => Option<Doing>,
        |row| row.body, &row.doing
    },
}

fn motion_tier(db: &RemoteTables, id: u32) -> Option<Moving> {
    motion::near(db).id().find(&id).or_else(|| motion::far(db).id().find(&id))
}

fn clear_on_tier_change<R: 'static, T, H>(tier: H, overlay: &Overlay<T>, id: fn(&R) -> u32)
where
    T: Send + 'static,
    H: TableWithPrimaryKey<Row = R>,
{
    let inserts = overlay.clone();
    let updates = overlay.clone();
    let deletes = overlay.clone();
    tier.on_insert(move |_, row| { inserts.lock().unwrap().remove(&id(row)); });
    tier.on_update(move |_, _, row| { updates.lock().unwrap().remove(&id(row)); });
    tier.on_delete(move |_, row| { deletes.lock().unwrap().remove(&id(row)); });
}

impl Cues {
    fn counts(&self) -> (usize, usize, usize) {
        (
            self.motion.lock().unwrap().len(),
            self.fighter.lock().unwrap().len(),
            self.doing.lock().unwrap().len(),
        )
    }

    /// Cues are taken while the law is on (or not yet known) and reads are on the tiers.
    fn taking(&self) -> bool {
        !self.off.load(Ordering::Relaxed) && !self.untiered.load(Ordering::Relaxed)
    }

    fn clear(&self) {
        self.motion.lock().unwrap().clear();
        self.fighter.lock().unwrap().clear();
        self.doing.lock().unwrap().clear();
    }

    /// The `cue_transport_on` law's value: turning off clears every overlay, since a creature's
    /// last cue would otherwise be shown until its next tier row (docs/TICK_RATE.md).
    fn set_transport(&self, on: bool) {
        if !on && !self.off.swap(true, Ordering::Relaxed) {
            debug!("cue_transport_on off: clearing cue overlays (motion, fighter, doing): {:?}", self.counts());
            self.clear();
        } else if on {
            self.off.store(false, Ordering::Relaxed);
        }
    }

    fn listen(self: &Arc<Self>, conn: &DbConnection, latest: &Arc<AtomicU64>, latest_all: &Arc<AtomicU64>) {
        let near = motion::near(&conn.db);
        let far = motion::far(&conn.db);
        clear_on_tier_change(motion::near(&conn.db), &self.motion, |row| row.id);
        clear_on_tier_change(motion::far(&conn.db), &self.motion, |row| row.id);
        clear_on_tier_change(fighting::near(&conn.db), &self.fighter, |row| row.id);
        clear_on_tier_change(fighting::far(&conn.db), &self.fighter, |row| row.id);
        clear_on_tier_change(activity::near(&conn.db), &self.doing, |row| row.id);
        clear_on_tier_change(activity::far(&conn.db), &self.doing, |row| row.id);

        track_motion_time(&near, latest, latest_all);
        track_motion_time(&far, latest, latest_all);
        track_motion_time(&motion::all(&conn.db), latest, latest_all);
        let cues = self.clone();
        near.on_delete(move |ctx, row| cues.forget_hidden(&ctx.db, row.id));
        let cues = self.clone();
        far.on_delete(move |ctx, row| cues.forget_hidden(&ctx.db, row.id));

        let (cues, latest, latest_all) = (self.clone(), latest.clone(), latest_all.clone());
        motion::cue(&conn.db).on_insert(move |ctx, cue| {
            if !cues.taking() {
                return;
            }
            let motion = &cues.motion;
            let (id, row) = motion::cue_value(cue);
            let Some(tier) = motion_tier(&ctx.db, id) else { return };
            let mut motion = motion.lock().unwrap();
            let previous = motion.get(&id).unwrap_or(&tier);
            latest_all.fetch_max(row.t_ms, Ordering::Relaxed);
            if row.t_ms > previous.t_ms {
                latest.fetch_max(row.t_ms, Ordering::Relaxed);
            }
            motion.insert(id, row.clone());
            trace!(id, "accepted motion cue");
        });

        let cues = self.clone();
        fighting::cue(&conn.db).on_insert(move |ctx, cue| {
            let (id, row) = fighting::cue_value(cue);
            if cues.taking() && motion_tier(&ctx.db, id).is_some() {
                cues.fighter.lock().unwrap().insert(id, row.clone());
                trace!(id, "accepted fighter cue");
            }
        });

        let cues = self.clone();
        activity::cue(&conn.db).on_insert(move |ctx, cue| {
            let (id, row) = activity::cue_value(cue);
            if cues.taking() && motion_tier(&ctx.db, id).is_some() {
                cues.doing.lock().unwrap().insert(id, row.clone());
                trace!(id, "accepted doing cue");
            }
        });
    }

    fn forget_hidden(&self, db: &RemoteTables, id: u32) {
        // SDK callbacks see both tiers after the transaction, including tier migrations.
        if motion_tier(db, id).is_none() {
            self.fighter.lock().unwrap().remove(&id);
            self.doing.lock().unwrap().remove(&id);
        }
    }
}

fn track_motion_time(
    tier: &impl TableWithPrimaryKey<Row = Moving>,
    latest: &Arc<AtomicU64>,
    latest_all: &Arc<AtomicU64>,
) {
    let first = latest_all.clone();
    tier.on_insert(move |_, new| {
        first.fetch_max(new.t_ms, Ordering::Relaxed);
    });
    let (latest, latest_all) = (latest.clone(), latest_all.clone());
    tier.on_update(move |_, old, new| {
        latest_all.fetch_max(new.t_ms, Ordering::Relaxed);
        if new.t_ms != old.t_ms {
            latest.fetch_max(new.t_ms, Ordering::Relaxed);
        }
    });
}

/// The two laws as a compiled script gives them: (`cue_transport_on`, `near_tier_on`).
fn delivery_laws(l: &living_rules::script::Laws) -> (bool, bool) {
    (l.cue_transport_on, l.near_tier_on)
}

/// The laws taken while the world's script does not compile here and none was read before: the
/// rules' defaults, as a fresh world starts (both on since frame-views' acceptance).
fn delivery_fallback() -> (bool, bool) {
    delivery_laws(&living_rules::script::Laws::default())
}

/// The perception set the two laws choose: the untiered set only while both are off.
fn perception_set(cues_on: bool, tiers_on: bool) -> u32 {
    if !cues_on && !tiers_on { UNTIERED } else { TIERED }
}

/// The world's delivery laws, `cue_transport_on` and `near_tier_on`, read from the installed
/// `skills` script the client already compiles with the world's `law_override` rows laid over it
/// (`verbs::Rules`, docs/LAW_OVERRIDE.md), again whenever the laws in force change
/// (`Rules::laws_key`: a compile, or a value-only edit laid over in place with the script
/// revision unchanged, `Applied::delivery`). They choose the perception set: both off, the
/// untiered views as main's client subscribes them (`UNTIERED_STREAMS`: on the authority both off
/// is main's delivery, and a client on the tiers then pays for twice the views, docs/TICK_RATE.md
/// "Short series"); either on, the tiers and the cue tables (`TIERED_STREAMS`). A script that
/// does not compile here keeps the last values, or before any the rules' defaults
/// (`delivery_fallback`: both on, so the tiers with cues). The new set is subscribed beside the
/// old, the old dropped once the new one is applied (no frame without the others), and then
/// reads move to it and the overlays are cleared. Each frame the cue law is passed to the
/// connection's overlays, so a fresh connection takes it at once.
pub fn perception_law(mut net: NonSendMut<Net>, rules: Option<NonSend<crate::verbs::Rules>>, time: Res<Time>, mut law: Local<Option<(u64, bool, bool)>>) {
    let Some(rules) = rules else { return };
    if let Some(sc) = rules.scripts.as_ref() {
        if law.is_none_or(|(key, _, _)| key != rules.laws_key) {
            let (c, t) = delivery_laws(&sc.laws());
            if law.is_none_or(|(_, oc, ot)| (oc, ot) != (c, t)) {
                info!("rules: cue_transport_on {c} near_tier_on {t} (script revision {}, laws {})", rules.revision, rules.laws_key);
            }
            *law = Some((rules.laws_key, c, t));
        }
    }
    let (cues_on, tiers_on) = match *law {
        Some((_, c, t)) => (c, t),
        None if rules.error.is_some() => delivery_fallback(),
        None => return,
    };
    if net.status != Status::Live || net.conn.is_none() {
        return;
    }
    if let Some(conn) = net.conn.as_ref() {
        conn.cues.set_transport(cues_on);
    }
    let want = perception_set(cues_on, tiers_on);
    let now = time.elapsed_secs_f64();
    if net.perception.wanted() != Some(&vec![want]) {
        let set = if want == UNTIERED { UNTIERED_STREAMS } else { TIERED_STREAMS };
        info!("perception: subscribing the {} set ({} queries; cue_transport_on {cues_on}, near_tier_on {tiers_on})", if want == UNTIERED { "untiered" } else { "tiered" }, set.len());
        let sub = net.subscribe(set.iter().map(|q| q.to_string()).collect(), vec![want]);
        net.perception.replace(sub);
        net.perception_asked = now;
    }
    let before = net.perception.current.as_ref().map(|s| s.key[0]);
    let old_rows = if before.is_some() && net.perception.next.as_ref().is_some_and(|s| s.handle.is_active()) {
        net.conn.as_ref().map(|c| c.perceived_rows(c.untiered()))
    } else {
        None
    };
    net.perception.settle();
    let after = net.perception.current.as_ref().map(|s| s.key[0]);
    if after != before {
        let untiered = after == Some(UNTIERED);
        let asked = net.perception_asked;
        let Some(conn) = net.conn.as_ref() else { return };
        let counts = conn.cues.counts();
        conn.cues.clear();
        conn.cues.untiered.store(untiered, Ordering::Relaxed);
        let new: std::collections::HashSet<u32> = conn.perceived_rows(untiered).into_iter().map(|(id, _)| id).collect();
        let old: std::collections::HashSet<u32> = old_rows.unwrap_or_default().into_iter().map(|(id, _)| id).collect();
        let mut missing: Vec<u32> = old.difference(&new).copied().collect();
        missing.sort_unstable();
        info!(
            "perception: on the {} set after {:.0} ms ({} others; {} were in the old set, missing now {:?}); overlays cleared (motion, fighter, doing): {:?}",
            if untiered { "untiered" } else { "tiered" },
            (now - asked) * 1000.0,
            new.len(),
            old.len(),
            missing,
            counts
        );
    }
}

/// `LIVING_GAME_SEEN_LOG=<file>`: every frame, the others as the reads see them then (the set in
/// place, its rows' segment `t_ms`, the overlays' sizes) and the wall clock (`wall_ms`, to line
/// frames up with an outside driver's calls), one JSON line, for checking a switch of perception
/// sets frame by frame.
pub fn seen_log(net: NonSend<Net>, time: Res<Time>, mut out: Local<Option<Option<std::io::BufWriter<std::fs::File>>>>) {
    use std::io::Write;
    let w = out.get_or_insert_with(|| std::env::var("LIVING_GAME_SEEN_LOG").ok().filter(|p| !p.is_empty()).and_then(|p| std::fs::File::create(p).ok()).map(std::io::BufWriter::new));
    let (Some(w), Some(conn)) = (w.as_mut(), net.conn.as_ref()) else { return };
    let untiered = conn.untiered();
    let wall_ms = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_millis() as u64);
    let line = serde_json::json!({
        "t": time.elapsed_secs_f64(),
        "wall_ms": wall_ms,
        "set": net.perception.current.as_ref().map(|s| if s.key[0] == UNTIERED { "untiered" } else { "tiered" }),
        "reads": if untiered { "untiered" } else { "tiered" },
        "rows": conn.perceived_rows(untiered),
        "overlays": conn.cues.counts(),
    });
    let _ = writeln!(w, "{line}");
    let _ = w.flush();
}

/// `LIVING_GAME_FEED_LOG=<file>`: one JSON line whenever the things the feed reads give change
/// (and every second), for checking a feed switch frame by frame: the stage, the base in place and
/// the one being subscribed, the near window's feed, the reads, the things by source, and the keys
/// added and gone since the last line (verify-ui's `feed-scope`).
#[allow(clippy::type_complexity)]
pub fn feed_log(
    net: NonSend<Net>,
    scene: NonSend<crate::world::Scene>,
    time: Res<Time>,
    mut out: Local<Option<Option<std::io::BufWriter<std::fs::File>>>>,
    mut last: Local<(std::collections::BTreeMap<(u8, u64), &'static str>, std::collections::BTreeSet<(u8, u64)>, String, f64)>,
) {
    use std::io::Write;
    let w = out.get_or_insert_with(|| std::env::var("LIVING_GAME_FEED_LOG").ok().filter(|p| !p.is_empty()).and_then(|p| std::fs::File::create(p).ok()).map(std::io::BufWriter::new));
    let (Some(w), Some(conn)) = (w.as_mut(), net.conn.as_ref()) else { return };
    let now = time.elapsed_secs_f64();
    let things: std::collections::BTreeMap<(u8, u64), &'static str> = crate::feed::things(&conn.db, 0.0, &|_| None).into_iter().map(|t| (t.key(), crate::feed::source_name(t.source))).collect();
    // What is drawn (`world::things`' entities: on a land world without what the island draws).
    let drawn: std::collections::BTreeSet<(u8, u64)> = scene.thing_keys().collect();
    let state = format!(
        "{:?} {:?} {:?} {:?} {:?} {} {}",
        net.base_feed(),
        net.base_next.as_ref().map(|(f, h)| (*f, h.is_active())),
        net.near.current.as_ref().map(|s| window_feed(&s.key)),
        net.near.next.as_ref().map(|s| (window_feed(&s.key), s.handle.is_active())),
        crate::feed::reads(),
        crate::feed::stage(&conn.db),
        crate::feed::switching()
    );
    if things == last.0 && drawn == last.1 && state == last.2 && now - last.3 < 1.0 {
        return;
    }
    let added: Vec<(u8, u64)> = things.keys().filter(|k| !last.0.contains_key(k)).copied().collect();
    let gone: Vec<(u8, u64)> = last.0.keys().filter(|k| !things.contains_key(k)).copied().collect();
    let drawn_added: Vec<(u8, u64)> = drawn.difference(&last.1).copied().collect();
    let drawn_gone: Vec<(u8, u64)> = last.1.difference(&drawn).copied().collect();
    let mut counts: std::collections::BTreeMap<&str, usize> = Default::default();
    for s in things.values() {
        *counts.entry(s).or_default() += 1;
    }
    let wall_ms = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_millis() as u64);
    let line = serde_json::json!({
        "t": now,
        "wall_ms": wall_ms,
        "status": format!("{:?}", net.status),
        "stage": crate::feed::stage(&conn.db),
        "base": net.base_feed().map(|f| f.name()),
        "base_next": net.base_next.as_ref().map(|(f, h)| serde_json::json!({"set": f.name(), "applied": h.is_active()})),
        "near": net.near.current.as_ref().map(|s| window_feed(&s.key).name()),
        "near_next": net.near.next.as_ref().map(|s| serde_json::json!({"set": window_feed(&s.key).name(), "applied": s.handle.is_active()})),
        "reads": crate::feed::reads().name(),
        "settled": crate::feed::settled(),
        "counts": counts,
        "switching": crate::feed::switching(),
        "added": added,
        "gone": gone,
        "drawn": drawn.len(),
        "drawn_added": drawn_added,
        "drawn_gone": drawn_gone,
        "legacy_rows": [conn.db.structure().count(), conn.db.resource_node().count(), conn.db.gate().count()],
        "scoped_rows": [conn.db.map_structure().count(), conn.db.map_resource().count(), conn.db.my_things().count(), conn.db.my_remembered_things().count()],
    });
    let _ = writeln!(w, "{line}");
    let _ = w.flush();
    *last = (things, drawn, state, now);
}

/// A perceived body as the drawing code takes it: its motion row (which carries
/// no path, chunk or kind), with the creature's kind from its `seen_characters` row (both views
/// hold the same creatures).
pub fn body_of(conn: &DbConnection, m: Moving) -> Body {
    let kind = conn.db.seen_characters().id().find(&m.id).map(|c| c.kind).unwrap_or_default();
    Body {
        id: m.id,
        kind,
        x: m.x,
        y: m.y,
        t_ms: m.t_ms,
        vx: m.vx,
        vy: m.vy,
        path: Vec::new(),
        speed: m.speed,
        chunk: living_rules::map::chunk_of(m.x, m.y),
        next_ms: m.next_ms,
        heading: m.heading,
        turn: m.turn,
        turn_s: m.turn_s,
        face_off: m.face_off,
        face_turn: m.face_turn,
        face_turn_s: m.face_turn_s,
        running: m.running,
    }
}

/// Every body my character perceives, mine included.
pub fn bodies(conn: &PlayerConnection) -> impl Iterator<Item = Body> + '_ {
    if conn.untiered() {
        let rows: Vec<Moving> = conn.db.my_body().iter().chain(motion::all(&conn.db).iter()).collect();
        return Box::new(rows.into_iter().map(move |m| body_of(conn, m))) as Box<dyn Iterator<Item = Body> + '_>;
    }
    let motion = conn.cues.motion.lock().unwrap();
    let rows: Vec<_> = conn.db.my_body().iter().chain(motion::near(&conn.db).iter()
        .chain(motion::far(&conn.db).iter())
        .map(|row| motion.get(&row.id).cloned().unwrap_or(row)))
        .collect();
    Box::new(rows.into_iter().map(move |m| body_of(conn, m)))
}

pub fn find_body(conn: &PlayerConnection, id: u32) -> Option<Body> {
    find_motion(conn, id).map(|m| body_of(conn, m))
}

/// A perceived body's motion row, mine included.
pub fn find_motion(conn: &PlayerConnection, id: u32) -> Option<Moving> {
    if conn.untiered() {
        return conn.db.my_body().id().find(&id).or_else(|| motion::all(&conn.db).id().find(&id));
    }
    conn.db.my_body().id().find(&id)
        .or_else(|| conn.cues.motion.lock().unwrap().get(&id).cloned())
        .or_else(|| motion_tier(&conn.db, id))
}

/// A perceived fighter's row, mine included.
pub fn find_fighter(conn: &PlayerConnection, id: u32) -> Option<Fighter> {
    if let Some(mine) = conn.db.my_fighter().id().find(&id) {
        return Some(mine);
    }
    if conn.untiered() {
        return fighting::all(&conn.db).id().find(&id);
    }
    if let Some(cue) = conn.cues.fighter.lock().unwrap().get(&id) {
        return cue.clone();
    }
    fighting::near(&conn.db).id().find(&id).or_else(|| fighting::far(&conn.db).id().find(&id))
}

/// Every perceived fighter's row, mine included.
pub fn fighters(conn: &PlayerConnection) -> Vec<Fighter> {
    if conn.untiered() {
        return conn.db.my_fighter().iter().chain(fighting::all(&conn.db).iter()).collect();
    }
    let fighter = conn.cues.fighter.lock().unwrap();
    conn.db.my_fighter().iter()
        .chain(fighting::near(&conn.db).iter()
            .chain(fighting::far(&conn.db).iter())
            .filter(|row| !fighter.contains_key(&row.id)))
        .chain(fighter.values().filter_map(|cue| cue.clone()))
        .collect()
}

/// What a perceived creature is visibly doing, mine included.
pub fn find_doing(conn: &PlayerConnection, id: u32) -> Option<Doing> {
    if let Some(mine) = conn.db.my_doing().id().find(&id) {
        return Some(mine);
    }
    if conn.untiered() {
        return activity::all(&conn.db).id().find(&id);
    }
    if let Some(cue) = conn.cues.doing.lock().unwrap().get(&id) {
        return cue.clone();
    }
    activity::near(&conn.db).id().find(&id).or_else(|| activity::far(&conn.db).id().find(&id))
}

impl Net {
    /// After a reducer call: the SDK's own refusal to queue it (it was not sent), for the HUD
    /// and the action log. Every call goes out as `on_reply` then the call then this.
    pub fn report(&self, what: &str, r: Result<(), spacetimedb_sdk::Error>) {
        let sent = self.last_call.take();
        if let Err(e) = r {
            if let Some(s) = sent {
                crate::actions::not_sent(s, e.to_string());
            }
            self.errors.lock().unwrap().push(format!("{what}: {e}"));
        }
    }

    /// The callback for a reducer call about to go out: `reducer` by its name, `args` by the
    /// bindings' argument names (built only while the action log is on, `actions.rs`), `what`
    /// the feature sending it. It logs the call and its reply (`actions.rs`), records the reply
    /// for the session report (`record.rs`) and a refusal (the authority's error text) for the
    /// HUD. Every reducer call this client sends goes through here.
    pub fn on_reply(
        &self,
        what: &'static str,
        reducer: &'static str,
        args: impl FnOnce() -> serde_json::Value,
    ) -> impl FnOnce(&ReducerEventContext, Result<Result<(), String>, spacetimedb_sdk::__codegen::InternalError>) + Send + 'static {
        let errors = self.errors.clone();
        let sent = crate::actions::sent(reducer, what, args);
        self.last_call.set(sent);
        move |ctx, r| {
            if let Some(s) = sent {
                let reply = match &r {
                    Ok(Ok(())) => crate::actions::Reply::Ok,
                    Ok(Err(e)) => crate::actions::Reply::Refused(e.clone()),
                    Err(e) => crate::actions::Reply::Failed(e.to_string()),
                };
                crate::actions::replied(s, reply, Some(ctx.event.timestamp.to_micros_since_unix_epoch()));
            }
            if let Ok(o) = &r {
                crate::record::reply(what, &ctx.event.reducer, o.clone(), ctx.event.timestamp.to_micros_since_unix_epoch());
            }
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
        self.attempts += 1;
        self.status = Status::Connecting;
        let path = token_path(&self.db);
        let token = std::fs::read_to_string(&path).ok().map(|t| t.trim().to_string()).filter(|t| !t.is_empty());
        let (inbox, applied, gone, failed) = (self.inbox.clone(), self.inbox.clone(), self.inbox.clone(), self.inbox.clone());
        let body_t = self.body_t.clone();
        let body_t_all = self.body_t_all.clone();
        let cues = Arc::new(Cues::default());
        let listen = cues.clone();
        let builder = DbConnection::builder()
            .with_uri(self.server.clone())
            .with_database_name(self.db.clone())
            .with_token(token)
            // Deliveries need not wait for the commit's fsync (docs/LATENCY.md, step 2).
            .with_confirmed_reads(false)
            .on_connect(move |conn, identity, token| {
                applied.lock().unwrap().push(Signal::Identity(identity, token.to_string()));
                // Only a new segment says how late rows arrive: a body entering view brings a
                // segment that may have started minutes ago (docs/LATENCY.md, step 3).
                debug!("new connection cue overlays (motion, fighter, doing): {:?}", listen.counts());
                listen.listen(conn, &body_t, &body_t_all);
                track_motion_time(&conn.db.my_body(), &body_t, &body_t_all);
                // The world's own law values: `verbs::Rules` lays them over on its next refresh.
                conn.db.law_override().on_insert(|_, _| law_rows_moved());
                conn.db.law_override().on_update(|_, _, _| law_rows_moved());
                conn.db.law_override().on_delete(|_, _| law_rows_moved());
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
            let r = builder.build().map(|sdk| PlayerConnection { sdk, cues }).map_err(|e| e.to_string());
            inbox.lock().unwrap().push(Signal::Connection(r));
        });
    }

    /// The static tables are in: pick the mode and the feed (`feed_scope.stage`), and subscribe
    /// what they need before playing, in one set: the perceived set and the feed's base views
    /// apply together (docs/FEED_SCOPING.md "Reconnect").
    fn subscribe_base(&mut self) {
        let Some(conn) = self.conn.as_ref() else { return };
        self.mode = if conn.db.land().count() > 0 { Mode::Land } else { Mode::Tiles };
        let stage = crate::feed::stage(&conn.db);
        let feed = crate::feed::Feed::of_stage(stage);
        let queries = base_set(self.mode, feed);
        info!("world kind: {:?}; feed: {} (feed_scope stage {stage})", self.mode, feed.name());
        crate::feed::reset();
        crate::feed::set_reads(feed);
        let (ok, err) = (self.inbox.clone(), self.inbox.clone());
        self.base = Some((
            feed,
            conn.subscription_builder()
                .on_applied(move |_| ok.lock().unwrap().push(Signal::Base))
                .on_error(move |_, e| err.lock().unwrap().push(Signal::Error(format!("subscription error: {e}"))))
                .subscribe(queries),
        ));
        self.base_next = None;
    }

    /// The feed the world's stage asks for now.
    fn feed_wanted(&self) -> Option<crate::feed::Feed> {
        self.conn.as_ref().map(|c| crate::feed::Feed::of_stage(crate::feed::stage(&c.db)))
    }

    /// The feed of the base in place.
    fn base_feed(&self) -> Option<crate::feed::Feed> {
        self.base.as_ref().map(|(f, _)| *f)
    }

    /// Follow `feed_scope.stage` across 0 ↔ 1 (docs/FEED_SCOPING.md "Client subscriptions"),
    /// make-before-break: subscribe a base for the new feed beside the old (the near window
    /// follows in `land_window`/`tile_window`, its key carrying the feed); once the new base and
    /// a near window for its feed are both applied, drop the old base, move the reads and let the
    /// near window settle. Until then everything is read and drawn from the old rows. A stage
    /// that goes back before the switch is done cancels it.
    fn switch_feed(&mut self, now: f64) {
        let (Some(want), Some(have)) = (self.feed_wanted(), self.base_feed()) else { return };
        let next = self.base_next.as_ref().map(|(f, _)| *f);
        if want == have {
            if let Some((f, h)) = self.base_next.take() {
                info!("feed: the stage went back; the {} set is dropped before it was in", f.name());
                let _ = h.unsubscribe();
            }
            crate::feed::set_switching(false);
            return;
        }
        crate::feed::set_switching(true);
        if next != Some(want) {
            let Some(conn) = self.conn.as_ref() else { return };
            let queries = base_set(self.mode, want);
            info!("feed: subscribing the {} set beside the {} one ({} base queries; feed_scope stage {})", want.name(), have.name(), queries.len(), crate::feed::stage(&conn.db));
            let inbox = self.inbox.clone();
            let h = conn.subscription_builder().on_error(move |_, e| inbox.lock().unwrap().push(Signal::Error(format!("subscription error: {e}")))).subscribe(queries);
            if let Some((_, old)) = self.base_next.replace((want, h)) {
                let _ = old.unsubscribe();
            }
            self.feed_asked = now;
        }
        let base_in = self.base_next.as_ref().is_some_and(|(_, h)| h.is_active());
        // No body yet (no window to wait for), or the near window for the new feed is in.
        let window_in = self.near.wanted().is_none() || window_serves(&self.near, want);
        if !(base_in && window_in) {
            return;
        }
        let before: std::collections::HashSet<(u8, u64)> = self.feed_keys();
        let (f, h) = self.base_next.take().expect("checked above");
        if let Some((_, old)) = self.base.replace((f, h)) {
            let _ = old.unsubscribe();
        }
        crate::feed::set_reads(f);
        crate::feed::set_switching(false);
        self.near.settle();
        let after: std::collections::HashSet<(u8, u64)> = self.feed_keys();
        let mut missing: Vec<(u8, u64)> = before.difference(&after).copied().collect();
        missing.sort_unstable();
        info!(
            "feed: on the {} set after {:.0} ms ({} things; {} before, missing now {} {:?})",
            f.name(),
            (now - self.feed_asked) * 1000.0,
            after.len(),
            before.len(),
            missing.len(),
            &missing[..missing.len().min(24)]
        );
    }

    /// The keys of every thing the feed reads give now (for the switch's log line).
    fn feed_keys(&self) -> std::collections::HashSet<(u8, u64)> {
        let Some(conn) = self.conn.as_ref() else { return Default::default() };
        crate::feed::things(&conn.db, 0.0, &|_| None).into_iter().map(|t| t.key()).collect()
    }

    /// The sweep publishes at most one row to the player's connection. A separate
    /// subscription leaves the base playable on servers predating the view.
    pub fn gaze_view_ready(&self) -> bool {
        self.gaze_view.as_ref().is_some_and(|view| view.is_active())
    }

    pub fn applied_gaze(&self) -> Option<AppliedGaze> {
        let conn = self.conn.as_ref()?;
        if !self.gaze_view_ready() {
            return None;
        }
        conn.db.my_senses_v_2().id().find(&self.my_id?)
    }

    pub fn update_gaze(&mut self, zoom: f32) {
        let desired = self.gaze.desired.at_zoom(zoom);
        if desired != self.gaze.desired {
            self.gaze.desired = desired;
            self.gaze.refused = None;
        }
        let Some(row) = self.applied_gaze().filter(|_| self.status == Status::Live) else {
            self.gaze.reset_owner();
            return;
        };
        let Ok(band) = GazeBand::try_from(row.band) else { return };
        if self.gaze.owner != Some(row.id) {
            self.gaze.reset_owner();
            self.gaze.owner = Some(row.id);
        }
        if self.gaze.applied != Some(band) {
            debug!("gaze owner applied band={} sight={} focal={} side={}", row.band, row.senses.sight, row.senses.focal_deg, row.senses.side_deg);
            self.gaze.applied = Some(band);
        }
        if self.gaze.accepted == Some(band) {
            self.gaze.accepted = None;
        }
        let now = Instant::now();
        let Some(band) = self.gaze.next(now) else { return };
        let Some(conn) = &self.conn else { return };
        let inbox = self.inbox.clone();
        let result = conn.reducers.human_gaze_then(band as u8, move |ctx, result| {
            let reply = match result {
                Ok(Ok(())) => {
                    debug!("gaze accepted band={} at_us={}", band as u8, ctx.event.timestamp.to_micros_since_unix_epoch());
                    GazeReply::Accepted
                }
                Ok(Err(reason)) => {
                    debug!("gaze refused band={}: {reason}", band as u8);
                    // A new connection can recover a sweep before the last acceptance cools.
                    if reason == "gaze changed less than 250 ms ago" { GazeReply::Retry } else { GazeReply::Refused }
                }
                Err(_) => GazeReply::Retry,
            };
            inbox.lock().unwrap().push(Signal::GazeReply(band, reply));
        });
        self.gaze.pending = Some(band);
        if result.is_ok() {
            debug!("gaze sent band={}", band as u8);
        } else {
            self.gaze.reply(band, GazeReply::Retry, now);
        }
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

    /// My character: alive, not AI-driven, controlled by my identity (`my_characters` holds
    /// only mine).
    fn find_me(&self) -> Option<u32> {
        self.conn.as_ref()?.db.my_characters().iter().find(|c| c.alive && !c.ai).map(|c| c.id)
    }

    pub fn my_body(&self) -> Option<Body> {
        find_body(self.conn.as_ref()?, self.my_id?)
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
                let name = self.name.clone();
                // Join (or a reclaim from the minds) sweeps my sight in its own transaction: until
                // its result is in, an empty `my_things` is not "nothing in sight" (`feed.rs`).
                crate::feed::joining(true);
                let reply = self.on_reply("join", "join", || serde_json::json!({ "name": name }));
                let r = conn.reducers.join_then(self.name.clone(), move |ctx, r| {
                    reply(ctx, r);
                    crate::feed::joining(false);
                });
                if r.is_err() {
                    crate::feed::joining(false);
                }
                self.report("join", r);
            }
        }
        if found != self.my_id {
            self.my_id = found;
            self.near = Window::default();
            self.far = Window::default();
            if let Some(id) = found {
                info!("playing character #{id}");
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
        // A near window for the other feed waits for the feed switch, which settles it with the
        // base (`switch_feed`); a re-centre on the same feed settles here.
        if self.near.next.as_ref().is_none_or(|n| window_feed(&n.key) == crate::feed::reads()) {
            self.near.settle();
        }
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
        // The key: the chunks, then the feed's tag (a stage switch re-subscribes the window).
        let feed = self.feed_wanted().unwrap_or_default();
        let (resources, structures) = crate::feed::window_tables(feed);
        chunks.push(feed.tag());
        if self.near.wanted() == Some(&chunks) {
            return None;
        }
        let mut q = Vec::with_capacity(chunks.len() * 2);
        for c in &chunks[..chunks.len() - 1] {
            q.push(format!("SELECT * FROM {resources} WHERE chunk = {c}"));
            q.push(format!("SELECT * FROM {structures} WHERE chunk = {c}"));
        }
        Some((chunks, q))
    }

    /// Land worlds: a square window of chunk ranges around a centre chunk, kept until I am
    /// far enough from it. The key is the centre chunk, and for the near window the feed's tag:
    /// a stage switch re-subscribes it over the same chunks.
    fn land_window(&self, body: &Body, which: Which) -> Option<(Vec<u32>, Vec<String>)> {
        let (w, h) = self.map_size();
        let (nx, ny) = ((w / CHUNK) as i32, (h / CHUNK) as i32);
        let here = ((body.x / CHUNK as f32).floor() as i32, (body.y / CHUNK as f32).floor() as i32);
        let (window, recentre, r) = match which {
            Which::Near => (&self.near, RECENTRE, TERRAIN_CHUNKS),
            Which::Lots => (&self.far, LOT_RECENTRE, LOT_CHUNKS),
        };
        let feed = self.feed_wanted().unwrap_or_default();
        if let Some(key) = window.wanted() {
            let (cx, cy) = chunk_xy(key[0]);
            let same_feed = matches!(which, Which::Lots) || window_feed(key) == feed;
            if same_feed && (here.0 - cx as i32).abs() < recentre && (here.1 - cy as i32).abs() < recentre {
                // A stage switch keeps the window's centre: the same chunks, the other tables.
                return None;
            }
        }
        let (cx, cy) = match (which, window.wanted()) {
            (Which::Near, Some(key)) if window_feed(key) != feed && {
                let (kx, ky) = chunk_xy(key[0]);
                (here.0 - kx as i32).abs() < recentre && (here.1 - ky as i32).abs() < recentre
            } => {
                let (kx, ky) = chunk_xy(key[0]);
                (kx as i32, ky as i32)
            }
            _ => (here.0.clamp(0, nx - 1), here.1.clamp(0, ny - 1)),
        };
        let span = |c: i32, n: i32, r: i32| ((c - r).max(0) as u32, (c + r).min(n - 1) as u32);
        let (xs, ys) = (span(cx, nx, r), span(cy, ny, r));
        let (resources, structures) = crate::feed::window_tables(feed);
        let (q, key) = match which {
            Which::Near => (
                vec![
                    format!("SELECT * FROM terrain_chunk WHERE {}", chunk_ranges("id", xs, ys)),
                    format!("SELECT * FROM {resources} WHERE {}", chunk_ranges("chunk", xs, ys)),
                    format!("SELECT * FROM {structures} WHERE {}", chunk_ranges("chunk", xs, ys)),
                ],
                vec![chunk_id(cx as u32, cy as u32), feed.tag()],
            ),
            Which::Lots => (vec![format!("SELECT * FROM lot WHERE {}", chunk_ranges("chunk", xs, ys))], vec![chunk_id(cx as u32, cy as u32)]),
        };
        Some((key, q))
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

/// Send what the input systems called this frame (docs/LATENCY.md, step 1): the SDK queues a
/// reducer call until the next `frame_tick`, which [`pump`] runs at the start of a frame, so
/// without this a key pressed in frame k left at the start of frame k + 1. Incoming messages it
/// applies are drawn next frame, as before. SDK behaviour (2.14.1): check again on upgrades.
pub fn flush(net: NonSend<Net>) {
    if let Some(conn) = &net.conn {
        if let Err(e) = conn.frame_tick() {
            net.inbox.lock().unwrap().push(Signal::Disconnected(e.to_string()));
        }
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
                info!("world subscribed after {now:.1} s ({} law overrides)", net.conn.as_ref().map_or(0, |c| c.db.law_override().count()));
                // The rows are this connection's now: laid over before a law is read this frame
                // (`verbs::refresh_rules` runs before `perception_law`), so a reconnect never
                // chooses its set by the last connection's values.
                law_rows_moved();
                crate::feed::base_applied();
                net.status = Status::Live;
                net.ever_live = true;
                net.gaze_view = net.conn.as_ref().map(|conn| {
                    conn.subscription_builder()
                        .on_error(|_, e| debug!("gaze owner view unavailable: {e}"))
                        .subscribe(["SELECT * FROM my_senses_v_2"])
                });
            }
            Signal::Error(e) => {
                warn!("{e}");
                net.errors.lock().unwrap().push(e);
            }
            Signal::GazeReply(band, reply) => net.gaze.reply(band, reply, Instant::now()),
            Signal::Disconnected(e) => {
                warn!("offline: {e}");
                // Calls still waiting will not be answered (the SDK drops their callbacks).
                crate::actions::lost();
                if let Some(c) = net.conn.take() {
                    debug!("dropping connection cue overlays (motion, fighter, doing): {:?}", c.cues.counts());
                    let _ = c.disconnect();
                }
                net.base = None;
                net.base_next = None;
                crate::feed::reset();
                net.gaze_view = None;
                net.gaze.reset_owner();
                net.near = Window::default();
                net.far = Window::default();
                net.perception = Window::default();
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
    if net.status == Status::Live {
        net.switch_feed(now);
    }
}

/// The base set for a world kind and feed: the perceived set (the perception streams are a set of
/// their own, `perception_law`), the world kind's own (`terrain_chunk` whole on tile worlds) and
/// the feed's base queries (`feed::base_queries`: `gate` on legacy land worlds, the scoped views).
fn base_set(mode: Mode, feed: crate::feed::Feed) -> Vec<&'static str> {
    let mut queries: Vec<&'static str> = PERCEIVED.to_vec();
    if mode == Mode::Tiles {
        queries.push("SELECT * FROM terrain_chunk");
    }
    queries.extend(crate::feed::base_queries(feed, mode != Mode::Tiles));
    queries
}

/// The feed a near window's key carries (its last element; land: `[centre, tag]`, tiles:
/// `[chunks…, tag]`). The lots window has none and reads as legacy, which it never switches.
fn window_feed(key: &[u32]) -> crate::feed::Feed {
    match key {
        [_, .., tag] => crate::feed::Feed::of_tag(*tag),
        _ => crate::feed::Feed::Legacy,
    }
}

/// Whether the near window serves `feed` now: its newest applied subscription is for it.
fn window_serves(w: &Window, feed: crate::feed::Feed) -> bool {
    if let Some(n) = &w.next {
        if n.handle.is_active() {
            return window_feed(&n.key) == feed;
        }
    }
    w.current.as_ref().is_some_and(|c| window_feed(&c.key) == feed)
}

#[cfg(test)]
mod cue_tests {
    use super::*;

    fn moving(id: u32) -> Moving {
        Moving { id, x: 0.0, y: 0.0, t_ms: 1, vx: 0.0, vy: 0.0, heading: 0.0, turn: 0.0, turn_s: 0.0, next_ms: 0, speed: 0.0, face_off: 0.0, face_turn: 0.0, face_turn_s: 0.0, running: false }
    }

    #[test]
    fn the_untiered_set_is_main_s_three_views_and_the_base_holds_no_stream() {
        // Both laws off: the client subscribes exactly main's perception queries.
        assert_eq!(UNTIERED_STREAMS, ["SELECT * FROM seen_bodies", "SELECT * FROM seen_fighters", "SELECT * FROM seen_doing"]);
        assert_eq!(TIERED_STREAMS.len(), 9);
        for q in UNTIERED_STREAMS.iter().chain(TIERED_STREAMS) {
            assert!(!PERCEIVED.contains(q), "{q} is in the base set too");
        }
    }

    #[test]
    fn both_delivery_laws_are_read_beside_the_seen_ranges_laws_and_choose_the_set() {
        use living_rules::script::{with_world_laws, Scripts};
        let shipped = include_str!("../../scripts/skills.rhai");
        let sc = Scripts::new(shipped).unwrap();
        // The shipped script: both laws found (both on, cues too, since frame-views' acceptance),
        // beside main's seen_ranges laws, and the tiered set.
        assert_eq!(delivery_laws(&sc.laws()), (true, true));
        assert!(sc.laws().seen_ranges && !sc.laws().seen_ranges_check, "the seen_ranges laws read as shipped");
        assert_eq!(perception_set(true, true), TIERED);
        // A world's own values, as the authority writes them after `set_world_law`: each of the
        // four states, with the seen_ranges laws changed beside them so a neighbour cannot mask
        // a law that was not found.
        for (cues, tiers, set) in [(true, true, TIERED), (true, false, TIERED), (false, true, TIERED), (false, false, UNTIERED)] {
            let values = [
                ("seen_ranges".to_string(), serde_json::json!(false)),
                ("cue_transport_on".to_string(), serde_json::json!(cues)),
                ("seen_ranges_check".to_string(), serde_json::json!(true)),
                ("near_tier_on".to_string(), serde_json::json!(tiers)),
            ];
            let l = Scripts::new(&with_world_laws(shipped, &values)).unwrap().laws();
            assert_eq!(delivery_laws(&l), (cues, tiers), "cue_transport_on {cues} near_tier_on {tiers}");
            assert!(!l.seen_ranges && l.seen_ranges_check);
            assert_eq!(perception_set(cues, tiers), set);
        }
        // A script that does not compile, with no law read before: the rules' defaults, as a fresh
        // world starts, and so the tiered set with cues taken.
        assert_eq!(delivery_fallback(), (true, true));
        assert_eq!(delivery_fallback(), delivery_laws(&sc.laws()));
        assert_eq!(perception_set(delivery_fallback().0, delivery_fallback().1), TIERED);
    }

    /// `law_override` rows as the bindings deliver them.
    fn rows(of: &[(&str, &str)]) -> Vec<LawOverride> {
        of.iter().enumerate().map(|(i, (name, value))| LawOverride { name: name.to_string(), value: value.to_string(), revision: i as u32 + 1 }).collect()
    }

    fn set_of(rules: &crate::verbs::Rules) -> u32 {
        let (c, t) = delivery_laws(&rules.scripts.as_ref().expect("compiled").laws());
        perception_set(c, t)
    }

    const SHIPPED: &str = include_str!("../../scripts/skills.rhai");

    #[test]
    fn law_override_rows_decode_as_the_authority_decodes_them() {
        let r = rows(&[("near_tier_on", "false"), ("cover_eye_height_m", " 1.25 "), ("not_json", "{oops"), ("cue_transport_on", "true"), ("near_tier_on", "true")]);
        let over = crate::verbs::overrides_of_rows(&r);
        // By name, the last of a name kept, a value that is not JSON left out: the same as
        // `overrides_of` on the same (name, value) pairs, which the authority runs.
        assert_eq!(over, vec![
            ("cover_eye_height_m".to_string(), serde_json::json!(1.25)),
            ("cue_transport_on".to_string(), serde_json::json!(true)),
            ("near_tier_on".to_string(), serde_json::json!(true)),
        ]);
        assert_eq!(over, living_rules::script::overrides_of(r.iter().map(|r| (r.name.as_str(), r.value.as_str()))));
        assert!(crate::verbs::overrides_of_rows(&[]).is_empty());
    }

    #[test]
    fn a_delivery_override_flips_the_set_in_place_with_the_script_revision_kept() {
        let mut rules = crate::verbs::Rules::default();
        rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &[], 1);
        assert_eq!((rules.revision, rules.applied.as_ref()), (7, None), "a compile");
        assert_eq!(set_of(&rules), TIERED);
        let key = rules.laws_key;
        // Both delivery laws off by `law_override` alone, the script row unchanged.
        let off = crate::verbs::overrides_of_rows(&rows(&[("cue_transport_on", "false"), ("near_tier_on", "false")]));
        rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &off, 2);
        let a = rules.applied.clone().expect("laid over in place, not compiled");
        assert!(a.delivery && !a.cover && !a.gaze, "{a:?}");
        assert_eq!(a.changed, ["cue_transport_on", "near_tier_on"]);
        assert_eq!(rules.revision, 7);
        assert!(rules.laws_key > key, "the laws' readers see a change");
        assert_eq!(set_of(&rules), UNTIERED, "both off: main's untiered set");
        // One back on: the tiers again.
        let one = crate::verbs::overrides_of_rows(&rows(&[("cue_transport_on", "false"), ("near_tier_on", "true")]));
        let key = rules.laws_key;
        rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &one, 3);
        assert_eq!(rules.applied.as_ref().map(|a| a.changed.clone()), Some(vec!["near_tier_on".to_string()]));
        assert!(rules.laws_key > key);
        assert_eq!(set_of(&rules), TIERED);
        // The same rows again (a row rewritten with its value): nothing in force changed, so
        // nothing that reads the laws reads them again.
        let key = rules.laws_key;
        rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &one, 4);
        assert_eq!(rules.laws_key, key);
    }

    #[test]
    fn cover_and_gaze_overrides_change_the_sight_laws_in_place() {
        let mut rules = crate::verbs::Rules::default();
        rules.take(3, SHIPPED, living_rules::DEFAULT_DAY_MS, &[], 1);
        let sc = rules.scripts.as_ref().unwrap();
        let (l, gaze) = (sc.laws(), sc.gaze_enabled());
        assert!(!l.cover_sight_on && !l.gaze_on && !gaze, "the island's laws as shipped: cover and gaze off");
        let over = crate::verbs::overrides_of_rows(&rows(&[("cover_sight_on", "true"), ("cover_eye_height_m", "1.25"), ("cover_brush_on", "true")]));
        rules.take(3, SHIPPED, living_rules::DEFAULT_DAY_MS, &over, 2);
        let a = rules.applied.clone().expect("in place");
        assert!(a.cover && !a.delivery && !a.gaze, "{a:?}");
        let sc = rules.scripts.as_ref().unwrap();
        let l = sc.laws();
        assert!(l.cover_sight_on && l.cover_brush_on);
        assert!((l.cover_eye_height_m - 1.25).abs() < 1e-6);
        assert_eq!(sc.law_value("cover_sight_on"), Some(serde_json::json!(true)), "Rhai's law(name) reads it too");
        // Gaze on, in place: the senses the edge of sight asks follow it (the ceilings and the
        // senses memo refreshed by `apply_overrides`), the same as a fresh compile under it.
        let ctx = living_rules::script::SkillCtx::default();
        let mut gaze = over.clone();
        gaze.push(("gaze_on".to_string(), serde_json::json!(true)));
        rules.take(3, SHIPPED, living_rules::DEFAULT_DAY_MS, &gaze, 3);
        let a = rules.applied.clone().expect("in place");
        assert!(a.gaze && !a.cover, "{a:?}");
        let sc = rules.scripts.as_ref().unwrap();
        assert!(sc.gaze_enabled() && sc.laws().gaze_on);
        let fresh = living_rules::script::Scripts::with_overrides(SHIPPED, living_rules::DEFAULT_DAY_MS, &gaze).unwrap();
        assert_eq!(format!("{:?}", sc.senses(&ctx)), format!("{:?}", fresh.senses(&ctx)));
        assert_eq!(sc.laws(), fresh.laws());
    }

    #[test]
    fn a_reconnect_lays_the_rows_it_finds_over_before_a_law_is_read() {
        // A client started on a world whose delivery laws were set off since the last install:
        // the first result holds the rows beside the script, so the first compile takes them and
        // the first set chosen is the untiered one (no tiered set first).
        let off = crate::verbs::overrides_of_rows(&rows(&[("cue_transport_on", "false"), ("near_tier_on", "false"), ("walk_base", "2.8")]));
        let mut rules = crate::verbs::Rules::default();
        rules.take(9, SHIPPED, living_rules::DEFAULT_DAY_MS, &off, 1);
        assert!(rules.applied.is_none(), "compiled with them");
        assert_eq!(set_of(&rules), UNTIERED);
        assert_eq!(rules.scripts.as_ref().unwrap().law_value("walk_base"), Some(serde_json::json!(2.8)));
        // A reconnect to the same world, the rows as they were: nothing changed in force.
        let key = rules.laws_key;
        rules.take(9, SHIPPED, living_rules::DEFAULT_DAY_MS, &off, 2);
        assert_eq!(rules.laws_key, key);
        // A reconnect after the delivery rows went (a world reset in place): the last
        // connection's values are not kept; the shipped laws are in force again, in place.
        let rest = crate::verbs::overrides_of_rows(&rows(&[("walk_base", "2.8")]));
        rules.take(9, SHIPPED, living_rules::DEFAULT_DAY_MS, &rest, 3);
        assert!(rules.applied.as_ref().is_some_and(|a| a.delivery));
        assert_eq!(set_of(&rules), TIERED);
    }

    #[test]
    fn an_override_of_an_ordinary_law_at_the_same_revision_compiles_again() {
        // `walk_base` is not value-only: laid over in place it is refused, and the script is
        // compiled with the rows instead (as after an install that has not reached me yet).
        let mut rules = crate::verbs::Rules::default();
        rules.take(4, SHIPPED, living_rules::DEFAULT_DAY_MS, &[], 1);
        let key = rules.laws_key;
        let over = crate::verbs::overrides_of_rows(&rows(&[("walk_base", "3.0")]));
        rules.take(4, SHIPPED, living_rules::DEFAULT_DAY_MS, &over, 2);
        assert!(rules.applied.is_none(), "compiled, not laid over");
        assert!(rules.laws_key > key);
        assert_eq!(rules.revision, 4);
        assert_eq!(rules.scripts.as_ref().unwrap().law_value("walk_base"), Some(serde_json::json!(3.0)));
        // A new revision (a full install) compiles with the rows too.
        rules.take(5, SHIPPED, living_rules::DEFAULT_DAY_MS, &over, 3);
        assert_eq!((rules.revision, rules.applied.as_ref()), (5, None));
        assert_eq!(rules.scripts.as_ref().unwrap().law_value("walk_base"), Some(serde_json::json!(3.0)));
    }

    #[test]
    fn cue_transport_off_clears_every_overlay_and_on_takes_cues_again() {
        let cues = Cues::default();
        assert!(!cues.off.load(Ordering::Relaxed), "cues are taken until the law is known");
        cues.motion.lock().unwrap().insert(7, moving(7));
        cues.fighter.lock().unwrap().insert(7, None);
        cues.doing.lock().unwrap().insert(8, None);
        cues.set_transport(true);
        assert_eq!(cues.counts(), (1, 1, 1), "on keeps what is shown");
        cues.set_transport(false);
        assert_eq!(cues.counts(), (0, 0, 0), "off clears all");
        assert!(cues.off.load(Ordering::Relaxed));
        cues.set_transport(true);
        assert!(!cues.off.load(Ordering::Relaxed), "on again takes cues");
    }
}

#[cfg(test)]
mod gaze_tests {
    use super::*;
    use GazeBand::{Far, Middle, Near};

    #[test]
    fn gaze_waits_for_owner_and_keeps_only_the_latest_zoom() {
        let now = Instant::now();
        let mut gaze = GazeInput { desired: Far, ..Default::default() };
        assert_eq!(gaze.next(now), None);
        gaze.applied = Some(Middle);
        assert_eq!(gaze.next(now), Some(Far));
        gaze.pending = Some(Far);
        gaze.desired = Near;
        assert_eq!(gaze.next(now), None);
        gaze.desired = Middle;
        gaze.reply(Far, GazeReply::Accepted, now);
        assert_eq!(gaze.next(now + Duration::from_millis(249)), None);
        // The sweep may still show Middle. The successful Far reply means Middle must be sent.
        assert_eq!(gaze.next(now + GAZE_INTERVAL), Some(Middle));
        gaze.reset_owner();
        assert_eq!(gaze.next(now + GAZE_INTERVAL), None);
        gaze.applied = Some(Far);
        assert_eq!(gaze.next(now + GAZE_INTERVAL), Some(Middle));
    }

    #[test]
    fn refused_gaze_does_not_change_the_applied_band_or_repeat() {
        let now = Instant::now();
        let mut gaze = GazeInput { desired: Near, applied: Some(Far), pending: Some(Near), ..Default::default() };
        gaze.reply(Near, GazeReply::Refused, now);
        assert_eq!(gaze.applied, Some(Far));
        assert_eq!(gaze.next(now + GAZE_INTERVAL), None);
        gaze.desired = Middle;
        assert_eq!(gaze.next(now + GAZE_INTERVAL), Some(Middle));
    }

    #[test]
    fn target_zoom_holds_each_band_through_the_dead_zone() {
        assert_eq!(Middle.at_zoom(0.55), Middle);
        assert_eq!(Middle.at_zoom(0.26), Middle);
        assert_eq!(Middle.at_zoom(0.24), Far);
        assert_eq!(Far.at_zoom(0.29), Far);
        assert_eq!(Far.at_zoom(0.31), Middle);
        assert_eq!(Middle.at_zoom(0.79), Middle);
        assert_eq!(Middle.at_zoom(0.81), Near);
        assert_eq!(Near.at_zoom(0.76), Near);
        assert_eq!(Near.at_zoom(0.74), Middle);
        assert_eq!(Far.at_zoom(1.0), Near);
        assert_eq!(Near.at_zoom(0.0), Far);
    }
}

#[cfg(test)]
mod feed_switch_tests {
    use super::*;
    use crate::feed::Feed;

    /// Every query a connection holds once settled, for a stage, the two delivery laws and a
    /// world kind: the static set, the base (perceived, the kind's own, the feed's base), the
    /// perception set and the near window's tables (by name).
    fn held(stage: u8, cues: bool, tiers: bool, mode: Mode) -> Vec<String> {
        let feed = Feed::of_stage(stage);
        let perception = if perception_set(cues, tiers) == UNTIERED { UNTIERED_STREAMS } else { TIERED_STREAMS };
        let (r, s) = crate::feed::window_tables(feed);
        STATIC.iter().chain(base_set(mode, feed).iter()).chain(perception.iter()).map(|q| q.to_string()).chain([format!("SELECT * FROM {r}"), format!("SELECT * FROM {s}")]).collect()
    }

    #[test]
    fn the_feed_and_perception_sets_combine_in_every_state() {
        for mode in [Mode::Land, Mode::Tiles] {
            for (cues, tiers) in [(false, false), (true, false), (false, true), (true, true)] {
                let perception = if perception_set(cues, tiers) == UNTIERED { UNTIERED_STREAMS } else { TIERED_STREAMS };
                for stage in [0u8, 1, 2] {
                    let q = held(stage, cues, tiers, mode);
                    let mut sorted = q.clone();
                    sorted.sort();
                    sorted.dedup();
                    assert_eq!(sorted.len(), q.len(), "a query twice at stage {stage} ({cues}, {tiers}, {mode:?})");
                    let has = |t: &str| q.iter().any(|x| x == &format!("SELECT * FROM {t}"));
                    // The perception streams follow the laws alone, whatever the stage.
                    for p in perception {
                        assert!(q.iter().any(|x| x == p), "{p} at stage {stage}");
                    }
                    assert!(has("feed_scope"), "the stage itself is static");
                    let legacy = stage == 0;
                    assert_eq!(has("structure") && has("resource_node"), legacy, "legacy windows at stage {stage}");
                    assert_eq!(has("gate"), legacy && mode == Mode::Land, "gate at stage {stage} {mode:?}");
                    for v in ["my_things", "my_remembered_things", "my_owners", "my_stock", "my_fuel_seen", "map_structure", "map_resource"] {
                        assert_eq!(has(v), !legacy, "{v} at stage {stage}");
                    }
                }
                // Stage 1 and 2 hold the same set: the cut is the authority's.
                assert_eq!(held(1, cues, tiers, mode), held(2, cues, tiers, mode));
            }
        }
        // Stage 0 with both laws off is main's land set plus the static `feed_scope`.
        let main: Vec<String> = held(0, false, false, Mode::Land).into_iter().filter(|q| q != "SELECT * FROM feed_scope").collect();
        assert!(main.contains(&"SELECT * FROM gate".to_string()) && main.contains(&"SELECT * FROM seen_bodies".to_string()));
    }

    #[test]
    fn a_window_key_carries_its_feed_and_the_lots_window_none() {
        assert_eq!(window_feed(&[chunk_id(3, 4), Feed::Scoped.tag()]), Feed::Scoped);
        assert_eq!(window_feed(&[chunk_id(3, 4), Feed::Legacy.tag()]), Feed::Legacy);
        assert_eq!(window_feed(&[chunk_id(3, 4)]), Feed::Legacy);
        // Tiles: the chunks, then the tag.
        assert_eq!(window_feed(&[1, 2, 3, Feed::Scoped.tag()]), Feed::Scoped);
        assert_eq!(window_feed(&[]), Feed::Legacy);
    }
}
