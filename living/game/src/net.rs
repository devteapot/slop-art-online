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
//! 1. On connect: `world`, `land` and `settlement` (1, 1 and about 6 rows), and beside them, as
//!    a subscription of its own, the one `genesis` row (staged genesis, `genesis.rs`): a world
//!    still being made holds what follows, `join` among it, until the row says `done`. A module
//!    without the table fails only that subscription, and its world counts as ready.
//! 2. Then, for the connection's lifetime (so the death screen keeps its rows):
//!    - what I perceive: the characters I perceive (mine too), and the others' motion, fighter
//!      and doing rows, as a set of their own ([`Feed`]), chosen by the world's delivery laws
//!      once the installed script is compiled (`perception_law`): the near and far tier views and
//!      their cue tables, or, while `cue_transport_on` and `near_tier_on` are both off,
//!      `seen_bodies`, `seen_fighters` and `seen_doing` as on main; the bodies from the public
//!      `seen_body_copy` table instead of the motion views while `motion_tables_on` is on, and
//!      the characters from `seen_character_copy` instead of `seen_characters` while
//!      `characters_table_on` is on, the fighters from `seen_fighter_copy` instead of the fighter
//!      views while `fighter_tables_on` is on (battle-views, docs/BATTLE_VIEWERS.md: rows only I
//!      can read, by row-level security, so no per-viewer view re-runs); and my combat feed,
//!      `my_combat`, or the `combat_feed` event table while `combat_feed_on` is on (addendum 4;
//!      `my_combat` read once at connect then, so a death screen survives a reconnect);
//!    - my own state: my body, fighter and doing rows (`my_body`, `my_fighter`, `my_doing`),
//!      `my_characters` (the one I play, kept after its death until I join again),
//!      `my_vitals`, `my_experience`, `my_places`, `my_inventory`, `my_know_how`, my combat
//!      timing (`my_readiness`) and the skill bar's `skill_card` (docs/COMBAT.md); the visible skills'
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

const STATIC: &[&str] = &["SELECT * FROM cover_law", "SELECT * FROM world", "SELECT * FROM land", "SELECT * FROM settlement"];
/// What my character perceives and its own state (per-sender views, docs/PERCEPTION.md), and
/// the rules' cards, for the connection's lifetime.
const PERCEIVED: &[&str] = &[
    // The characters I perceive are in the perception set ([`Feed`]): `seen_characters`, or
    // `seen_character_copy` while `characters_table_on` is on.
    // My own body, move and act, apart from my scene's: my own changes re-run one row.
    "SELECT * FROM my_body",
    "SELECT * FROM my_fighter",
    "SELECT * FROM my_doing",
    "SELECT * FROM my_characters",
    "SELECT * FROM my_vitals",
    // My lines are in the perception set ([`Feed`]): `my_experience`, or `experience_copy` while
    // `lines_table_on` is on.
    "SELECT * FROM my_places",
    "SELECT * FROM my_inventory",
    "SELECT * FROM my_know_how",
    // My combat feed is in the perception set ([`Feed`]): `my_combat`, or `combat_feed` while
    // `combat_feed_on` is on.
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
    /// The `genesis` subscription is in (its row, if any, is in the cache).
    GenesisApplied,
    /// The `genesis` subscription failed: a module from before staged genesis.
    GenesisMissing(String),
    /// A call refused with `world_preparing` (`join` or `join_as` when `join`).
    Preparing { join: bool, err: String },
    /// The `genesis` subscription's handle, kept for the connection's lifetime.
    GenesisSub(SubscriptionHandle),
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
    /// The character I played died and I have not asked to arrive again (`rejoin`): a reconnect
    /// then joins no new character, so the death screen stays (its rows are kept two minutes,
    /// and a join would clear them: `combat::clear_feed`). Kept across reconnects.
    died: bool,
    /// Whether the world is made yet, and the join retry while it is not (`genesis.rs`).
    pub genesis: crate::genesis::Wait,
    genesis_sub: Option<SubscriptionHandle>,
    genesis_applied: bool,
    /// The static set is in; the base waits for the world to be ready.
    static_in: bool,
    /// The call `on_reply` just logged, for `report` (`actions.rs`).
    last_call: std::cell::Cell<Option<crate::actions::Sent>>,
    base: Option<SubscriptionHandle>,
    gaze_view: Option<SubscriptionHandle>,
    gaze: GazeInput,
    near: Window,
    far: Window,
    /// The perception set: keyed by its [`Feed::key`] (`perception_law`).
    perception: Window,
    /// When the set being subscribed was asked for (elapsed s), for the switch's log line.
    perception_asked: f64,
    /// Whether the wait for my copies to reach the tables was logged for the set being subscribed.
    perception_waited: bool,
    /// The one read of `my_combat` when a connection's first set takes the combat feed from
    /// `combat_feed` (its rows copied out when applied, then unsubscribed), and whether it was
    /// asked on this connection.
    combat_once: Option<SubscriptionHandle>,
    combat_once_asked: bool,
}

/// What the perception set reads, as the world's delivery laws choose it ([`Delivery::feed`]).
/// Every switch of the set is a change of this, made in one place (`perception_law`), before
/// broken.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub(crate) struct Feed {
    /// The near and far tier views and their cue tables (`cue_transport_on` or `near_tier_on`
    /// on), else each stream's one untiered view, as main's client subscribes them.
    pub tiered: bool,
    /// `motion_tables_on`: the others' bodies from `seen_body_copy` in place of the motion views
    /// (`seen_bodies`, or `seen_bodies_near` and `_far`). The motion cue table stays with the
    /// tiers (a cue stands until that creature's next copy row).
    pub motion_table: bool,
    /// `characters_table_on`: the characters from `seen_character_copy` in place of
    /// `seen_characters`.
    pub characters_table: bool,
    /// `fighter_tables_on`: the others' fighter rows from `seen_fighter_copy` in place of the
    /// fighter views (`seen_fighters`, or `seen_fighters_near` and `_far`). The fighter cue table
    /// stays with the tiers (a cue stands until that creature's next copy row).
    pub fighter_table: bool,
    /// `combat_feed_on`: my combat feed from the `combat_feed` event table in place of the
    /// `my_combat` view (read once at connect instead, [`Net::combat_once`]).
    pub combat_feed: bool,
    /// `lines_table_on`: my lines from `experience_copy` in place of the `my_experience` view
    /// (experience-incremental; [`my_lines`] reads either).
    pub lines_table: bool,
    /// `heed_on` and `heed_players` both on: my throng, `seen_throng` (docs/ATTENTION_BUDGET.md,
    /// "Built: the player side"), added beside the rest; nothing replaces it. Off, the set is
    /// exactly what it was before heed (the same queries, the same key).
    pub throng: bool,
}

const CHARACTERS_VIEW: &str = "SELECT * FROM seen_characters";
const CHARACTERS_TABLE: &str = "SELECT * FROM seen_character_copy";
const MOTION_TABLE: &str = "SELECT * FROM seen_body_copy";
const FIGHTER_TABLE: &str = "SELECT * FROM seen_fighter_copy";
const COMBAT_VIEW: &str = "SELECT * FROM my_combat";
const COMBAT_FEED: &str = "SELECT * FROM combat_feed";
const LINES_VIEW: &str = "SELECT * FROM my_experience";
const LINES_TABLE: &str = "SELECT * FROM experience_copy";
/// My throng: per-viewer rows by row-level security (`viewer = :sender`), at most 48.
const THRONG_TABLE: &str = "SELECT * FROM seen_throng";

impl Feed {
    /// Its key in [`Net::perception`].
    fn key(self) -> u32 {
        self.tiered as u32 | (self.motion_table as u32) << 1 | (self.characters_table as u32) << 2 | (self.fighter_table as u32) << 3 | (self.combat_feed as u32) << 4 | (self.lines_table as u32) << 5 | (self.throng as u32) << 6
    }

    fn of_key(k: u32) -> Self {
        Self { tiered: k & 1 != 0, motion_table: k & 2 != 0, characters_table: k & 4 != 0, fighter_table: k & 8 != 0, combat_feed: k & 16 != 0, lines_table: k & 32 != 0, throng: k & 64 != 0 }
    }

    /// Its queries: the characters, my combat feed, then the streams (the motion and fighter
    /// views replaced by their tables).
    pub(crate) fn queries(self) -> Vec<&'static str> {
        let mut q = vec![
            if self.characters_table { CHARACTERS_TABLE } else { CHARACTERS_VIEW },
            if self.combat_feed { COMBAT_FEED } else { COMBAT_VIEW },
            if self.lines_table { LINES_TABLE } else { LINES_VIEW },
        ];
        let streams = if self.tiered { TIERED_STREAMS } else { UNTIERED_STREAMS };
        if self.motion_table {
            q.push(MOTION_TABLE);
        }
        if self.fighter_table {
            q.push(FIGHTER_TABLE);
        }
        q.extend(streams.iter().copied().filter(|s| !(self.motion_table && MOTION_VIEWS.contains(s)) && !(self.fighter_table && FIGHTER_VIEWS.contains(s))));
        if self.throng {
            q.push(THRONG_TABLE);
        }
        q
    }

    /// `tiered` or `untiered`, as the log lines and the seen log name the set.
    fn tier(self) -> &'static str {
        if self.tiered { "tiered" } else { "untiered" }
    }

    /// Which tables it reads, for the log lines.
    fn tables(self) -> String {
        let t = format!("tables: motion {} characters {} fighters {} combat_feed {} lines {}", self.motion_table, self.characters_table, self.fighter_table, self.combat_feed, self.lines_table);
        // Named only while on, so the lines with heed off read as before it.
        if self.throng { t + " throng true" } else { t }
    }
}

/// The world's six delivery laws, as a compiled script gives them.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(crate) struct Delivery {
    pub cues: bool,
    pub tiers: bool,
    pub motion_tables: bool,
    pub characters_table: bool,
    pub fighter_tables: bool,
    pub combat_feed: bool,
    pub lines_table: bool,
    /// Heed for players: `heed_on` and `heed_players` both on.
    pub throng: bool,
}

impl Delivery {
    /// The perception set they choose: the untiered streams only while both frame laws are off;
    /// each copy table, and the combat feed's event table, while its law is on.
    pub(crate) fn feed(self) -> Feed {
        Feed { tiered: self.cues || self.tiers, motion_table: self.motion_tables, characters_table: self.characters_table, fighter_table: self.fighter_tables, combat_feed: self.combat_feed, lines_table: self.lines_table, throng: self.throng }
    }
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
            body_t_all: Arc::default(),
            window_moves: 0,
            inbox: Arc::default(),
            connecting: false,
            retry_at: 0.0,
            attempts: 0,
            ever_live: false,
            join_sent: false,
            died: false,
            genesis: Default::default(),
            genesis_sub: None,
            genesis_applied: false,
            static_in: false,
            last_call: Default::default(),
            base: None,
            gaze_view: None,
            gaze: GazeInput::default(),
            near: Window::default(),
            far: Window::default(),
            perception: Window::default(),
            perception_asked: 0.0,
            perception_waited: false,
            combat_once: None,
            combat_once_asked: false,
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
    /// The copy tables (battle-views), as this connection holds them.
    copies: Copies,
    /// Combat feed rows not yet taken by `combat::ingest` ([`take_combat`]): each `combat_feed`
    /// event row as it arrives (event rows are never kept in the client cache), and the rows of
    /// the one read of `my_combat` at connect. Bounded by [`COMBAT_PENDING_MAX`].
    combat: Mutex<Vec<CombatSeen>>,
    /// The set in place takes the combat feed from `combat_feed` (for the log lines and the seen
    /// log; the reads take both sources, merged by id).
    combat_feed: AtomicBool,
    /// The set in place takes my lines from `experience_copy` (for the log lines and the switch;
    /// the reads take both sources, merged by id: [`my_lines`]).
    lines_table: AtomicBool,
    /// The set in place has `seen_throng` ([`throng`] reads it only then).
    throng: AtomicBool,
}

/// My lines (what `my_experience` returns): from `my_experience` or `experience_copy`, whichever the
/// set in place subscribes, merged by id while a switch holds both (experience-incremental).
pub fn my_lines(db: &RemoteTables) -> Vec<Experience> {
    let mut rows: Vec<Experience> = db.my_experience().iter().collect();
    let ids: std::collections::HashSet<u64> = rows.iter().map(|e| e.id).collect();
    rows.extend(db.experience_copy().iter().map(|c| c.row).filter(|e| !ids.contains(&e.id)));
    rows
}

/// The most combat feed rows kept for `combat::ingest` between two frames (the oldest go first);
/// far above a frame's worth in a dense battle (about 25 a second per viewer at 216 viewers).
const COMBAT_PENDING_MAX: usize = 4096;

/// The copy tables' rows (battle-views), indexed for the readers: `seen_body_copy` has no key
/// (a client finds its row of a creature by `body`, and sees a change as an insert and a delete),
/// `seen_character_copy` is keyed by the projected row's id, not the creature's, and
/// `seen_fighter_copy` by the private copy's key (a change is one update). Kept by the tables'
/// callbacks, whichever set is in place; read only while the set in place reads the table
/// (`motion`, `characters_on`, `fighters_on`).
#[derive(Default)]
struct Copies {
    /// My copy of each creature's motion, by creature.
    bodies: Mutex<HashMap<u32, SeenBodyCopy>>,
    /// My mirror of each creature's projection, by creature.
    characters: Mutex<HashMap<u32, SeenCharacterCopy>>,
    /// My copy of each creature's fighter row, by creature.
    fighters: Mutex<HashMap<u32, SeenFighterCopy>>,
    /// Reads take the bodies from `bodies` (the set in place has `seen_body_copy`).
    motion: AtomicBool,
    /// Reads take the characters from `characters` (the set in place has `seen_character_copy`).
    characters_on: AtomicBool,
    /// Reads take the others' fighter rows from `fighters` (the set in place has `seen_fighter_copy`).
    fighters_on: AtomicBool,
    /// The set being subscribed leaves a table the reads are on: its deletes are not taken
    /// (the kill switch empties a table in one tick) until the reads move to the views.
    leaving_motion: AtomicBool,
    leaving_characters: AtomicBool,
    leaving_fighters: AtomicBool,
}

/// A body's motion as the views give it, from its copy row: the segment with the creature's id
/// (`Segment::moving` on the authority).
pub(crate) fn moving_of(c: &SeenBodyCopy) -> Moving {
    let s = &c.seg;
    Moving {
        id: c.body,
        x: s.x,
        y: s.y,
        t_ms: s.t_ms,
        vx: s.vx,
        vy: s.vy,
        heading: s.heading,
        turn: s.turn,
        turn_s: s.turn_s,
        next_ms: s.next_ms,
        speed: s.speed,
        face_off: s.face_off,
        face_turn: s.face_turn,
        face_turn_s: s.face_turn_s,
        running: s.running,
    }
}

/// A `combat_feed` event row as the `my_combat` view gives the same row (the same id and columns,
/// in `combat_seen`'s order: `CombatFeed::of` on the authority).
pub(crate) fn combat_of(e: &CombatFeed) -> CombatSeen {
    CombatSeen {
        id: e.id,
        viewer: e.viewer,
        expires_ms: e.expires_ms,
        at_ms: e.at_ms,
        kind: e.kind,
        actor: e.actor,
        target: e.target,
        skill: e.skill,
        x: e.x,
        y: e.y,
        dx: e.dx,
        dy: e.dy,
        amount: e.amount,
        ms: e.ms,
        note: e.note.clone(),
    }
}

/// Whether the world's `law_override` row for `law` holds `false` now. The kill switch's deletes
/// come in a tick after that row's change, so a delete callback that sees it can keep the rows
/// for the frames until the views are in, even when both arrive in one frame.
fn law_row_off(db: &RemoteTables, law: &str) -> bool {
    db.law_override().name().find(&law.to_string()).is_some_and(|r| serde_json::from_str::<bool>(r.value.trim()).ok() == Some(false))
}

impl Copies {
    fn motion_frozen(&self, db: &RemoteTables) -> bool {
        self.leaving_motion.load(Ordering::Relaxed) || law_row_off(db, "motion_tables_on")
    }

    fn characters_frozen(&self, db: &RemoteTables) -> bool {
        self.leaving_characters.load(Ordering::Relaxed) || law_row_off(db, "characters_table_on")
    }

    fn fighters_frozen(&self, db: &RemoteTables) -> bool {
        self.leaving_fighters.load(Ordering::Relaxed) || law_row_off(db, "fighter_tables_on")
    }

    /// A fighter copy row came (an insert, or an update in place): it replaces what I had of
    /// that creature.
    fn put_fighter(&self, row: &SeenFighterCopy) {
        self.fighters.lock().unwrap().insert(row.body, row.clone());
    }

    /// As `drop_body`: only the copy row I hold of that creature (by its key), and not while the
    /// rows are kept.
    fn drop_fighter(&self, row: &SeenFighterCopy, frozen: bool) {
        if frozen {
            return;
        }
        let mut f = self.fighters.lock().unwrap();
        if f.get(&row.body).is_some_and(|h| h.id == row.id) {
            f.remove(&row.body);
        }
    }

    /// A body's copy row came: it replaces what I had of that creature. Returns the row it
    /// replaced (a change arrives as this insert, then the old row's delete).
    fn put_body(&self, row: &SeenBodyCopy) -> Option<SeenBodyCopy> {
        self.bodies.lock().unwrap().insert(row.body, row.clone())
    }

    /// A body's copy row went: forgotten only if it is still the row I hold (not one its
    /// replacement's insert already took the place of), and not while the rows are kept.
    fn drop_body(&self, row: &SeenBodyCopy, frozen: bool) {
        if frozen {
            return;
        }
        let mut b = self.bodies.lock().unwrap();
        if b.get(&row.body) == Some(row) {
            b.remove(&row.body);
        }
    }

    fn put_character(&self, row: &SeenCharacterCopy) {
        self.characters.lock().unwrap().insert(row.row.id, row.clone());
    }

    /// As `drop_body`: only the mirror row I hold of that creature (its projected row's id).
    fn drop_character(&self, row: &SeenCharacterCopy, frozen: bool) {
        if frozen {
            return;
        }
        let mut c = self.characters.lock().unwrap();
        if c.get(&row.row.id).is_some_and(|h| h.id == row.id) {
            c.remove(&row.row.id);
        }
    }

    /// The indexes again from the client cache, while the rows are not kept and they differ in
    /// size (a delete missed while kept, or a switch back before the views were in).
    fn resync(&self, db: &RemoteTables) {
        if !self.motion_frozen(db) && self.bodies.lock().unwrap().len() as u64 != db.seen_body_copy().count() {
            let rows: HashMap<u32, SeenBodyCopy> = db.seen_body_copy().iter().map(|r| (r.body, r)).collect();
            debug!("seen_body_copy: index rebuilt from the cache ({} rows)", rows.len());
            *self.bodies.lock().unwrap() = rows;
        }
        if !self.characters_frozen(db) && self.characters.lock().unwrap().len() as u64 != db.seen_character_copy().count() {
            let rows: HashMap<u32, SeenCharacterCopy> = db.seen_character_copy().iter().map(|r| (r.row.id, r)).collect();
            debug!("seen_character_copy: index rebuilt from the cache ({} rows)", rows.len());
            *self.characters.lock().unwrap() = rows;
        }
        if !self.fighters_frozen(db) && self.fighters.lock().unwrap().len() as u64 != db.seen_fighter_copy().count() {
            let rows: HashMap<u32, SeenFighterCopy> = db.seen_fighter_copy().iter().map(|r| (r.body, r)).collect();
            debug!("seen_fighter_copy: index rebuilt from the cache ({} rows)", rows.len());
            *self.fighters.lock().unwrap() = rows;
        }
    }
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

    /// Whether reads take the bodies from `seen_body_copy`.
    pub fn motion_table(&self) -> bool {
        self.cues.copies.motion.load(Ordering::Relaxed)
    }

    /// Whether reads take the characters from `seen_character_copy`.
    pub fn characters_table(&self) -> bool {
        self.cues.copies.characters_on.load(Ordering::Relaxed)
    }

    /// Whether reads take the others' fighter rows from `seen_fighter_copy`.
    pub fn fighter_table(&self) -> bool {
        self.cues.copies.fighters_on.load(Ordering::Relaxed)
    }

    /// Whether the set in place takes my combat feed from `combat_feed`.
    pub fn combat_feed(&self) -> bool {
        self.cues.combat_feed.load(Ordering::Relaxed)
    }

    /// Whether the set in place takes my lines from `experience_copy`.
    pub fn lines_table(&self) -> bool {
        self.cues.lines_table.load(Ordering::Relaxed)
    }

    /// Whether the set in place has my throng (`seen_throng`; heed for players on).
    pub fn throng_table(&self) -> bool {
        self.cues.throng.load(Ordering::Relaxed)
    }

    /// What the reads take now.
    fn reads(&self) -> Feed {
        Feed { tiered: !self.untiered(), motion_table: self.motion_table(), characters_table: self.characters_table(), fighter_table: self.fighter_table(), combat_feed: self.combat_feed(), lines_table: self.lines_table(), throng: self.throng_table() }
    }

    /// The others whose fighter rows I read by the set in place (ids), for the seen log and the
    /// switch (my own row is `my_fighter`, in the base set).
    fn perceived_fighters(&self) -> Vec<u32> {
        if self.fighter_table() {
            return self.cues.copies.fighters.lock().unwrap().keys().copied().collect();
        }
        if self.untiered() {
            fighting::all(&self.db).iter().map(|f| f.id).collect()
        } else {
            fighting::near(&self.db).iter().chain(fighting::far(&self.db).iter()).map(|f| f.id).collect()
        }
    }

    /// The others I perceive by the set in place (id, segment `t_ms`), for the seen log.
    fn perceived_rows(&self) -> Vec<(u32, u64)> {
        if self.motion_table() {
            let b = self.cues.copies.bodies.lock().unwrap();
            if self.untiered() {
                return b.values().map(|c| (c.body, c.seg.t_ms)).collect();
            }
            let o = self.cues.motion.lock().unwrap();
            return b.values().map(|c| (c.body, o.get(&c.body).map_or(c.seg.t_ms, |m| m.t_ms))).collect();
        }
        if self.untiered() {
            motion::all(&self.db).iter().map(|m| (m.id, m.t_ms)).collect()
        } else {
            let o = self.cues.motion.lock().unwrap();
            motion::near(&self.db).iter().chain(motion::far(&self.db).iter()).map(|m| (m.id, o.get(&m.id).map_or(m.t_ms, |c| c.t_ms))).collect()
        }
    }

    /// The characters I perceive by the set in place (ids), for the seen log and the switch.
    fn perceived_characters(&self) -> Vec<u32> {
        if self.characters_table() {
            self.cues.copies.characters.lock().unwrap().keys().copied().collect()
        } else {
            self.db.seen_characters().iter().map(|c| c.id).collect()
        }
    }

    /// Whether `feed`'s tables hold my scene, so reads can move to them: a viewer's motion
    /// copies move to `seen_body_copy` whole, in one transaction, at its next frame after the law
    /// goes on, and its mirror fills whole at its next frame (the authority's `to_public`,
    /// `fill_mirror`); until then the views hold it. A scene that is empty in the reads now is
    /// lost by none.
    ///
    /// The fighter copies move to `seen_fighter_copy` whole at the viewer's next frame too
    /// (`fighters_to_public`). The combat feed has nothing to wait for: an event table holds no
    /// rows, and its rows share `my_combat`'s ids, so both sources are read while both are in.
    fn tables_hold(&self, feed: Feed) -> bool {
        let motion = !feed.motion_table || self.motion_table() || self.db.seen_body_copy().count() > 0 || self.perceived_rows().is_empty();
        let characters = !feed.characters_table || self.characters_table() || self.db.seen_character_copy().count() > 0 || self.perceived_characters().is_empty();
        let fighters = !feed.fighter_table || self.fighter_table() || self.db.seen_fighter_copy().count() > 0 || self.perceived_fighters().is_empty();
        // My lines: their copies have come, or there are none to wait for.
        let lines = !feed.lines_table || self.lines_table() || self.db.experience_copy().count() > 0 || self.db.my_experience().count() == 0;
        motion && characters && fighters && lines
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

/// The motion views `seen_body_copy` replaces while `motion_tables_on` is on ([`Feed::queries`]).
const MOTION_VIEWS: &[&str] = &["SELECT * FROM seen_bodies", "SELECT * FROM seen_bodies_near", "SELECT * FROM seen_bodies_far"];
/// The fighter views `seen_fighter_copy` replaces while `fighter_tables_on` is on.
const FIGHTER_VIEWS: &[&str] = &["SELECT * FROM seen_fighters", "SELECT * FROM seen_fighters_near", "SELECT * FROM seen_fighters_far"];

fn motion_tier(db: &RemoteTables, id: u32) -> Option<Moving> {
    motion::near(db).id().find(&id).or_else(|| motion::far(db).id().find(&id))
}

impl Cues {
    /// A perceived creature's motion row as the tiers hold it (without its cue), from the table
    /// the reads take bodies from.
    fn motion_row(&self, db: &RemoteTables, id: u32) -> Option<Moving> {
        if self.copies.motion.load(Ordering::Relaxed) {
            return self.copies.bodies.lock().unwrap().get(&id).map(moving_of);
        }
        motion_tier(db, id)
    }
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
    /// Combat feed rows for `combat::ingest`, the oldest dropped past [`COMBAT_PENDING_MAX`].
    fn pend_combat(&self, rows: impl IntoIterator<Item = CombatSeen>) {
        let mut p = self.combat.lock().unwrap();
        p.extend(rows);
        if p.len() > COMBAT_PENDING_MAX {
            let over = p.len() - COMBAT_PENDING_MAX;
            warn!("combat feed: {over} rows dropped untaken (more than {COMBAT_PENDING_MAX} since the last frame)");
            p.drain(..over);
        }
    }

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

        // battle-views: the copy tables, indexed whichever set is in place. A body's copy row is
        // its tier row while the table is read: a change of it ends its motion cue, as a tier
        // row's change does, and only a changed segment tells the display clock how late rows
        // arrive (`track_motion_time`); a change comes as the new row's insert, then the old's
        // delete.
        let (cues, segment, any) = (self.clone(), latest.clone(), latest_all.clone());
        conn.db.seen_body_copy().on_insert(move |_, row| {
            let old = cues.copies.put_body(row);
            any.fetch_max(row.seg.t_ms, Ordering::Relaxed);
            if old.is_some_and(|o| o.seg.t_ms != row.seg.t_ms) {
                segment.fetch_max(row.seg.t_ms, Ordering::Relaxed);
            }
            cues.motion.lock().unwrap().remove(&row.body);
        });
        let cues = self.clone();
        conn.db.seen_body_copy().on_delete(move |ctx, row| {
            let frozen = cues.copies.motion_frozen(&ctx.db);
            cues.copies.drop_body(row, frozen);
            cues.motion.lock().unwrap().remove(&row.body);
            if !frozen && cues.copies.motion.load(Ordering::Relaxed) {
                cues.forget_hidden(&ctx.db, row.body);
            }
        });
        let cues = self.clone();
        conn.db.seen_character_copy().on_insert(move |_, row| cues.copies.put_character(row));
        let cues = self.clone();
        conn.db.seen_character_copy().on_update(move |_, _, row| cues.copies.put_character(row));
        let cues = self.clone();
        conn.db.seen_character_copy().on_delete(move |ctx, row| {
            let frozen = cues.copies.characters_frozen(&ctx.db);
            cues.copies.drop_character(row, frozen);
        });
        // views step 3: the fighter copies, keyed, so a change is one update. A copy row of a
        // creature ends its fighter cue, as a tier row's change does.
        let cues = self.clone();
        conn.db.seen_fighter_copy().on_insert(move |_, row| {
            cues.copies.put_fighter(row);
            cues.fighter.lock().unwrap().remove(&row.body);
        });
        let cues = self.clone();
        conn.db.seen_fighter_copy().on_update(move |_, _, row| {
            cues.copies.put_fighter(row);
            cues.fighter.lock().unwrap().remove(&row.body);
        });
        let cues = self.clone();
        conn.db.seen_fighter_copy().on_delete(move |ctx, row| {
            let frozen = cues.copies.fighters_frozen(&ctx.db);
            cues.copies.drop_fighter(row, frozen);
            if !frozen {
                cues.fighter.lock().unwrap().remove(&row.body);
            }
        });
        // views step 2: my combat feed as event rows (on insert only; never in the cache), kept
        // for `combat::ingest`, which merges them with `my_combat`'s by id.
        let cues = self.clone();
        conn.db.combat_feed().on_insert(move |_, row| cues.pend_combat([combat_of(row)]));

        let (cues, latest, latest_all) = (self.clone(), latest.clone(), latest_all.clone());
        motion::cue(&conn.db).on_insert(move |ctx, cue| {
            if !cues.taking() {
                return;
            }
            let motion = &cues.motion;
            let (id, row) = motion::cue_value(cue);
            let Some(tier) = cues.motion_row(&ctx.db, id) else { return };
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
            if cues.taking() && cues.motion_row(&ctx.db, id).is_some() {
                cues.fighter.lock().unwrap().insert(id, row.clone());
                trace!(id, "accepted fighter cue");
            }
        });

        let cues = self.clone();
        activity::cue(&conn.db).on_insert(move |ctx, cue| {
            let (id, row) = activity::cue_value(cue);
            if cues.taking() && cues.motion_row(&ctx.db, id).is_some() {
                cues.doing.lock().unwrap().insert(id, row.clone());
                trace!(id, "accepted doing cue");
            }
        });
    }

    fn forget_hidden(&self, db: &RemoteTables, id: u32) {
        // SDK callbacks see both tiers after the transaction, including tier migrations.
        if self.motion_row(db, id).is_none() {
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

/// The six delivery laws as a compiled script gives them.
fn delivery_laws(l: &living_rules::script::Laws) -> Delivery {
    Delivery {
        cues: l.cue_transport_on,
        tiers: l.near_tier_on,
        motion_tables: l.motion_tables_on,
        characters_table: l.characters_table_on,
        fighter_tables: l.fighter_tables_on,
        combat_feed: l.combat_feed_on,
        lines_table: l.lines_table_on,
        // Players perceive through heed only when both hold (`heed::applies_player`).
        throng: l.heed_on && l.heed_players,
    }
}

/// The laws taken while the world's script does not compile here and none was read before: the
/// rules' defaults, as a fresh world starts.
fn delivery_fallback() -> Delivery {
    delivery_laws(&living_rules::script::Laws::default())
}

/// The world's delivery laws, `cue_transport_on`, `near_tier_on`, `motion_tables_on`,
/// `characters_table_on`, `fighter_tables_on` and `combat_feed_on`, read from the installed `skills` script the client already compiles
/// with the world's `law_override` rows laid over it (`verbs::Rules`, docs/LAW_OVERRIDE.md), again
/// whenever the laws in force change (`Rules::laws_key`: a compile, or a value-only edit laid
/// over in place with the script revision unchanged, `Applied::delivery`). They choose the
/// perception set ([`Delivery::feed`]): both frame laws off, the untiered views as main's client
/// subscribes them (`UNTIERED_STREAMS`: on the authority both off is main's delivery, and a client
/// on the tiers then pays for twice the views, docs/TICK_RATE.md "Short series"); either on, the
/// tiers and the cue tables (`TIERED_STREAMS`); and with them, the bodies from `seen_body_copy`
/// while `motion_tables_on` is on, the characters from `seen_character_copy` while
/// `characters_table_on` is on, the fighters from `seen_fighter_copy` while `fighter_tables_on`
/// is on, and my combat feed from the `combat_feed` event table while `combat_feed_on` is on
/// (docs/BATTLE_VIEWERS.md, addenda 4 and 5). A script that does not compile here keeps the last
/// values, or before any the rules' defaults (`delivery_fallback`).
///
/// Every switch is made here, before broken: the new set is subscribed beside the old, and the
/// old dropped once the new one is applied and holds my scene (`tables_hold`: a viewer's copies
/// reach a table at its next frame after the law goes on, while the views hold them meanwhile);
/// then reads move to it and the overlays are cleared. Leaving a table (its law off, the kill
/// switch), its rows are kept for the reads until the views are in, though the authority empties
/// it in one tick (`Copies::leaving_*`, `law_row_off`). The combat feed needs neither: the reads
/// take `my_combat`'s rows and the event rows alike while both are in, merged by id
/// (`take_combat`); a connection whose first set takes the event table reads `my_combat` once
/// (`combat_once`), so the death screen survives a reconnect. Each frame the cue law is passed
/// to the connection's overlays, so a fresh connection takes it at once.
pub fn perception_law(mut net: NonSendMut<Net>, rules: Option<NonSend<crate::verbs::Rules>>, time: Res<Time>, mut law: Local<Option<(u64, Delivery)>>) {
    let Some(rules) = rules else { return };
    if let Some(sc) = rules.scripts.as_ref() {
        if law.is_none_or(|(key, _)| key != rules.laws_key) {
            let d = delivery_laws(&sc.laws());
            if law.is_none_or(|(_, old)| old != d) {
                info!(
                    "rules: cue_transport_on {} near_tier_on {} motion_tables_on {} characters_table_on {} fighter_tables_on {} combat_feed_on {} (script revision {}, laws {})",
                    d.cues, d.tiers, d.motion_tables, d.characters_table, d.fighter_tables, d.combat_feed, rules.revision, rules.laws_key
                );
            }
            if law.is_none_or(|(_, old)| old.throng != d.throng) && (d.throng || law.is_some()) {
                info!("rules: heed for players {} (heed_on and heed_players; script revision {}, laws {})", d.throng, rules.revision, rules.laws_key);
            }
            *law = Some((rules.laws_key, d));
        }
    }
    let d = match *law {
        Some((_, d)) => d,
        None if rules.error.is_some() => delivery_fallback(),
        None => return,
    };
    if net.status != Status::Live || net.conn.is_none() {
        return;
    }
    if let Some(conn) = net.conn.as_ref() {
        conn.cues.set_transport(d.cues);
    }
    let want = d.feed();
    let now = time.elapsed_secs_f64();
    if net.perception.wanted() != Some(&vec![want.key()]) {
        let set = want.queries();
        info!(
            "perception: subscribing the {} set ({} queries; {}; cue_transport_on {} near_tier_on {})",
            want.tier(),
            set.len(),
            want.tables(),
            d.cues,
            d.tiers
        );
        let sub = net.subscribe(set.iter().map(|q| q.to_string()).collect(), vec![want.key()]);
        net.perception.replace(sub);
        net.perception_asked = now;
        net.perception_waited = false;
        if let Some(conn) = net.conn.as_ref() {
            let c = &conn.cues.copies;
            c.leaving_motion.store(conn.motion_table() && !want.motion_table, Ordering::Relaxed);
            c.leaving_characters.store(conn.characters_table() && !want.characters_table, Ordering::Relaxed);
            c.leaving_fighters.store(conn.fighter_table() && !want.fighter_table, Ordering::Relaxed);
        }
        // This connection's first set takes the event table: `my_combat` once (subscribe, copy its
        // rows out when applied, unsubscribe), so what it holds (a death screen's rows, kept two
        // minutes) is not lost to a reconnect or a fresh start.
        if want.combat_feed && net.perception.current.is_none() && !net.combat_once_asked {
            net.combat_once_asked = true;
            net.combat_once = net.conn.as_ref().map(|conn| {
                let cues = conn.cues.clone();
                conn.subscription_builder()
                    .on_applied(move |ctx| {
                        let rows: Vec<CombatSeen> = ctx.db.my_combat().iter().collect();
                        info!("combat feed: my_combat read once ({} rows)", rows.len());
                        cues.pend_combat(rows);
                    })
                    .on_error(|_, e| warn!("combat feed: the one read of my_combat failed: {e}"))
                    .subscribe([COMBAT_VIEW])
            });
        }
    }
    if net.combat_once.as_ref().is_some_and(|h| h.is_active()) {
        if let Some(h) = net.combat_once.take() {
            let _ = h.unsubscribe();
        }
    }
    let Some(conn) = net.conn.as_ref() else { return };
    conn.cues.copies.resync(&conn.db);
    let Some(next) = net.perception.next.as_ref().filter(|s| s.handle.is_active()).map(|s| Feed::of_key(s.key[0])) else { return };
    if !conn.tables_hold(next) {
        if !net.perception_waited && now - net.perception_asked > 2.0 {
            info!(
                "perception: the {} set is in, waiting for my copies to reach the tables ({}; seen_body_copy {} rows, seen_character_copy {} rows, seen_fighter_copy {} rows)",
                next.tier(),
                next.tables(),
                conn.db.seen_body_copy().count(),
                conn.db.seen_character_copy().count(),
                conn.db.seen_fighter_copy().count()
            );
            net.perception_waited = true;
        }
        return;
    }
    let had = net.perception.current.is_some();
    let old_rows: Vec<(u32, u64)> = if had { conn.perceived_rows() } else { Vec::new() };
    let old_chars: Vec<u32> = if had { conn.perceived_characters() } else { Vec::new() };
    let old_fighters: Vec<u32> = if had { conn.perceived_fighters() } else { Vec::new() };
    net.perception.settle();
    let asked = net.perception_asked;
    let Some(conn) = net.conn.as_ref() else { return };
    let counts = conn.cues.counts();
    conn.cues.clear();
    let c = &conn.cues.copies;
    // Into a table: its index from the cache as it stands; out of one: nothing kept.
    c.leaving_motion.store(false, Ordering::Relaxed);
    c.leaving_characters.store(false, Ordering::Relaxed);
    c.leaving_fighters.store(false, Ordering::Relaxed);
    if next.motion_table != conn.motion_table() {
        c.bodies.lock().unwrap().clear();
    }
    if next.characters_table != conn.characters_table() {
        c.characters.lock().unwrap().clear();
    }
    if next.fighter_table != conn.fighter_table() {
        c.fighters.lock().unwrap().clear();
    }
    conn.cues.untiered.store(!next.tiered, Ordering::Relaxed);
    c.motion.store(next.motion_table, Ordering::Relaxed);
    c.characters_on.store(next.characters_table, Ordering::Relaxed);
    c.fighters_on.store(next.fighter_table, Ordering::Relaxed);
    conn.cues.combat_feed.store(next.combat_feed, Ordering::Relaxed);
    conn.cues.lines_table.store(next.lines_table, Ordering::Relaxed);
    conn.cues.throng.store(next.throng, Ordering::Relaxed);
    c.resync(&conn.db);
    let new: std::collections::HashSet<u32> = conn.perceived_rows().into_iter().map(|(id, _)| id).collect();
    let old: std::collections::HashSet<u32> = old_rows.into_iter().map(|(id, _)| id).collect();
    let mut missing: Vec<u32> = old.difference(&new).copied().collect();
    missing.sort_unstable();
    let new_chars: std::collections::HashSet<u32> = conn.perceived_characters().into_iter().collect();
    let mut missing_chars: Vec<u32> = old_chars.into_iter().filter(|id| !new_chars.contains(id)).collect();
    missing_chars.sort_unstable();
    let new_fighters: std::collections::HashSet<u32> = conn.perceived_fighters().into_iter().collect();
    let mut missing_fighters: Vec<u32> = old_fighters.into_iter().filter(|id| !new_fighters.contains(id)).collect();
    missing_fighters.sort_unstable();
    info!(
        "perception: on the {} set after {:.0} ms ({}; {} others; {} were in the old set, missing now {:?}; {} characters, missing now {:?}; {} fighters, missing now {:?}); overlays cleared (motion, fighter, doing): {:?}",
        next.tier(),
        (now - asked) * 1000.0,
        next.tables(),
        new.len(),
        old.len(),
        missing,
        new_chars.len(),
        missing_chars,
        new_fighters.len(),
        missing_fighters,
        counts
    );
}

/// My throng's rows (`seen_throng`), while the set in place has the table (heed for players on);
/// none otherwise. Row-level security sends only my own rows; `viewer` is checked again so a row
/// of an identity I no longer play is never drawn.
pub fn throng(conn: &PlayerConnection) -> Vec<SeenThrong> {
    if !conn.throng_table() {
        return Vec::new();
    }
    let me = conn.try_identity();
    conn.db.seen_throng().iter().filter(|r| me.is_none_or(|i| r.viewer == i)).collect()
}

/// Whether the seen log is on (`LIVING_GAME_SEEN_LOG` names a file): `combat::ingest` then keeps
/// the ids it took for it.
pub fn seen_logging() -> bool {
    static ON: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ON.get_or_init(|| std::env::var("LIVING_GAME_SEEN_LOG").is_ok_and(|p| !p.is_empty()))
}

/// `LIVING_GAME_SEEN_LOG=<file>`: every frame, the others as the reads see them then (the set in
/// place, its rows' segment `t_ms`, the overlays' sizes), the characters' and the fighters' ids,
/// the combat feed rows taken since the last line (`combat`: their ids, from either source) and
/// the wall clock (`wall_ms`, to line frames up with an outside driver's calls), one JSON line,
/// for checking a switch of perception sets frame by frame.
pub fn seen_log(net: NonSend<Net>, time: Res<Time>, combat: Option<ResMut<crate::combat::Combat>>, mut out: Local<Option<Option<std::io::BufWriter<std::fs::File>>>>) {
    use std::io::Write;
    let w = out.get_or_insert_with(|| std::env::var("LIVING_GAME_SEEN_LOG").ok().filter(|p| !p.is_empty()).and_then(|p| std::fs::File::create(p).ok()).map(std::io::BufWriter::new));
    let (Some(w), Some(conn)) = (w.as_mut(), net.conn.as_ref()) else { return };
    let reads = conn.reads();
    let set = net.perception.current.as_ref().map(|s| Feed::of_key(s.key[0]));
    let wall_ms = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_millis() as u64);
    let mut chars = conn.perceived_characters();
    chars.sort_unstable();
    let mut fighters = conn.perceived_fighters();
    fighters.sort_unstable();
    let taken: Vec<u64> = combat.map(|mut c| std::mem::take(&mut c.logged)).unwrap_or_default();
    let line = serde_json::json!({
        "t": time.elapsed_secs_f64(),
        "wall_ms": wall_ms,
        "set": set.map(|f| f.tier()),
        "reads": reads.tier(),
        "tables": {"motion": reads.motion_table, "characters": reads.characters_table, "fighters": reads.fighter_table, "combat_feed": reads.combat_feed, "lines": reads.lines_table},
        "rows": conn.perceived_rows(),
        "characters": chars,
        "fighters": fighters,
        "combat": taken,
        "overlays": conn.cues.counts(),
    });
    let _ = writeln!(w, "{line}");
    let _ = w.flush();
}

/// A perceived body as the drawing code takes it: its motion row (which carries
/// no path, chunk or kind), with the creature's kind from its character row (both sources hold
/// the same creatures).
pub fn body_of(conn: &PlayerConnection, m: Moving) -> Body {
    let kind = find_character(conn, m.id).map(|c| c.kind).unwrap_or_default();
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

/// Every character my character perceives, mine included: `seen_characters`, or its mirror
/// `seen_character_copy` while the set in place reads it.
pub fn characters(conn: &PlayerConnection) -> Vec<SeenCharacter> {
    if conn.characters_table() {
        return conn.cues.copies.characters.lock().unwrap().values().map(|c| c.row.clone()).collect();
    }
    conn.db.seen_characters().iter().collect()
}

/// A perceived character's row by its creature id, mine included (as [`characters`]).
pub fn find_character(conn: &PlayerConnection, id: u32) -> Option<SeenCharacter> {
    if conn.characters_table() {
        return conn.cues.copies.characters.lock().unwrap().get(&id).map(|c| c.row.clone());
    }
    conn.db.seen_characters().id().find(&id)
}

/// How many characters I perceive (as [`characters`]).
pub fn character_count(conn: &PlayerConnection) -> usize {
    if conn.characters_table() {
        return conn.cues.copies.characters.lock().unwrap().len();
    }
    conn.db.seen_characters().count() as usize
}

/// How many others' motion rows the set in place holds (the live report).
pub fn motion_count(conn: &PlayerConnection) -> usize {
    if conn.motion_table() {
        return conn.cues.copies.bodies.lock().unwrap().len();
    }
    (motion::all(&conn.db).count() + motion::near(&conn.db).count() + motion::far(&conn.db).count()) as usize
}

/// The others' motion rows by the set in place, each with its cue laid over (tiers only).
fn others_motion(conn: &PlayerConnection) -> Vec<Moving> {
    let untiered = conn.untiered();
    if conn.motion_table() {
        let b = conn.cues.copies.bodies.lock().unwrap();
        if untiered {
            return b.values().map(moving_of).collect();
        }
        let motion = conn.cues.motion.lock().unwrap();
        return b.values().map(|c| motion.get(&c.body).cloned().unwrap_or_else(|| moving_of(c))).collect();
    }
    if untiered {
        return motion::all(&conn.db).iter().collect();
    }
    let motion = conn.cues.motion.lock().unwrap();
    motion::near(&conn.db).iter().chain(motion::far(&conn.db).iter()).map(|row| motion.get(&row.id).cloned().unwrap_or(row)).collect()
}

/// Every body my character perceives, mine included.
pub fn bodies(conn: &PlayerConnection) -> impl Iterator<Item = Body> + '_ {
    let rows: Vec<Moving> = conn.db.my_body().iter().chain(others_motion(conn)).collect();
    rows.into_iter().map(move |m| body_of(conn, m))
}

pub fn find_body(conn: &PlayerConnection, id: u32) -> Option<Body> {
    find_motion(conn, id).map(|m| body_of(conn, m))
}

/// A perceived body's motion row, mine included.
pub fn find_motion(conn: &PlayerConnection, id: u32) -> Option<Moving> {
    if let Some(mine) = conn.db.my_body().id().find(&id) {
        return Some(mine);
    }
    if conn.untiered() {
        return if conn.motion_table() { conn.cues.motion_row(&conn.db, id) } else { motion::all(&conn.db).id().find(&id) };
    }
    conn.cues.motion.lock().unwrap().get(&id).cloned().or_else(|| conn.cues.motion_row(&conn.db, id))
}

/// A perceived fighter's row, mine included: my own from `my_fighter`; the others' from the
/// fighter views of the set in place, or `seen_fighter_copy` while the set reads it (its row's
/// `fighter` is the view's row); with the tiers, a fighter cue laid over either.
pub fn find_fighter(conn: &PlayerConnection, id: u32) -> Option<Fighter> {
    if let Some(mine) = conn.db.my_fighter().id().find(&id) {
        return Some(mine);
    }
    if !conn.untiered() {
        if let Some(cue) = conn.cues.fighter.lock().unwrap().get(&id) {
            return cue.clone();
        }
    }
    if conn.fighter_table() {
        return conn.cues.copies.fighters.lock().unwrap().get(&id).map(|c| c.fighter.clone());
    }
    if conn.untiered() {
        return fighting::all(&conn.db).id().find(&id);
    }
    fighting::near(&conn.db).id().find(&id).or_else(|| fighting::far(&conn.db).id().find(&id))
}

/// The others' fighter rows by the set in place, without cues: the fighter views, or the copy
/// table's rows.
fn others_fighters(conn: &PlayerConnection) -> Vec<Fighter> {
    if conn.fighter_table() {
        return conn.cues.copies.fighters.lock().unwrap().values().map(|c| c.fighter.clone()).collect();
    }
    if conn.untiered() {
        return fighting::all(&conn.db).iter().collect();
    }
    fighting::near(&conn.db).iter().chain(fighting::far(&conn.db).iter()).collect()
}

/// Every perceived fighter's row, mine included (as [`find_fighter`]).
pub fn fighters(conn: &PlayerConnection) -> Vec<Fighter> {
    let mine: Vec<Fighter> = conn.db.my_fighter().iter().collect();
    if conn.untiered() {
        return mine.into_iter().chain(others_fighters(conn)).collect();
    }
    let fighter = conn.cues.fighter.lock().unwrap();
    mine.into_iter().chain(others_fighters(conn).into_iter().filter(|row| !fighter.contains_key(&row.id)))
        .chain(fighter.values().filter_map(|cue| cue.clone()))
        .collect()
}

/// My combat feed rows as they stand for `combat::ingest`, its one reader: the `my_combat` rows
/// in the cache (while a set or the connect's one read holds the view), then every row that
/// came since the last call from the `combat_feed` event table or the one read (taken: each
/// comes once). Both sources share `combat_seen`'s ids, so the reader merges them by id
/// (`Combat::seen_ids`); whichever is in use, the same rows reach it.
pub fn take_combat(conn: &PlayerConnection) -> Vec<CombatSeen> {
    let pending = std::mem::take(&mut *conn.cues.combat.lock().unwrap());
    conn.db.my_combat().iter().chain(pending).collect()
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
        let inbox = self.inbox.clone();
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
                // The world is still being made: never a failure the player sees; `pump` holds
                // it and sends `join` again when the world is ready (`genesis.rs`).
                Ok(Err(e)) if crate::genesis::is_preparing(&e) => {
                    debug!("{what} held: {e}");
                    inbox.lock().unwrap().push(Signal::Preparing { join: matches!(reducer, "join" | "join_as"), err: e });
                    return;
                }
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
                // Whether the world is made yet: its own subscription, so a module without the
                // table fails only this one (`genesis.rs`). Asked first, so it answers first.
                let (g_ok, g_err) = (applied.clone(), applied.clone());
                let genesis = conn
                    .subscription_builder()
                    .on_applied(move |_| g_ok.lock().unwrap().push(Signal::GenesisApplied))
                    .on_error(move |_, e| g_err.lock().unwrap().push(Signal::GenesisMissing(e.to_string())))
                    .subscribe(["SELECT * FROM genesis"]);
                applied.lock().unwrap().push(Signal::GenesisSub(genesis));
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

    /// The static tables are in: pick the mode and subscribe what it needs before playing.
    fn subscribe_base(&mut self) {
        let Some(conn) = self.conn.as_ref() else { return };
        self.mode = if conn.db.land().count() > 0 { Mode::Land } else { Mode::Tiles };
        // The perception streams are a set of their own (`perception_law`), chosen by the
        // world's delivery laws once the installed script is compiled.
        let mut queries: Vec<&str> = PERCEIVED.to_vec();
        if self.mode == Mode::Tiles {
            queries.push("SELECT * FROM terrain_chunk");
        } else {
            // Gates shut and opened (about a hundred rows on a town, changed rarely): a shut gate
            // blocks sight, which the edge of sight draws (`sightfield.rs`).
            queries.push("SELECT * FROM gate");
        }
        info!("world kind: {:?}", self.mode);
        let (ok, err) = (self.inbox.clone(), self.inbox.clone());
        self.base = Some(
            conn.subscription_builder()
                .on_applied(move |_| ok.lock().unwrap().push(Signal::Base))
                .on_error(move |_, e| err.lock().unwrap().push(Signal::Error(format!("subscription error: {e}"))))
                .subscribe(queries),
        );
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
    fn maintain(&mut self, now: f64) {
        if self.status != Status::Live {
            return;
        }
        let found = self.find_me();
        if found.is_none() && !self.join_sent {
            self.join_sent = true;
            if let Some(conn) = &self.conn {
                info!("joining as {}", self.name);
                let name = self.name.clone();
                let r = conn.reducers.join_then(self.name.clone(), self.on_reply("join", "join", || serde_json::json!({ "name": name })));
                self.report("join", r);
            }
        }
        if found != self.my_id {
            if found.is_none() && self.my_id.is_some_and(|id| self.conn.as_ref().is_some_and(|c| c.db.my_characters().id().find(&id).is_some_and(|ch| !ch.alive))) {
                info!("my character died: no new one until I ask to arrive again");
                self.died = true;
            }
            self.my_id = found;
            self.near = Window::default();
            self.far = Window::default();
            if let Some(id) = found {
                info!("playing character #{id}");
                if let Some(done) = self.genesis.done_at.take() {
                    info!("genesis: joined {:.2} s after the world was ready", now - done);
                }
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
        let mut q = Vec::with_capacity(chunks.len() * 2);
        for c in &chunks {
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
            Which::Near => (&self.near, RECENTRE, TERRAIN_CHUNKS),
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
        let q = match which {
            Which::Near => vec![
                format!("SELECT * FROM terrain_chunk WHERE {}", chunk_ranges("id", xs, ys)),
                format!("SELECT * FROM resource_node WHERE {}", chunk_ranges("chunk", xs, ys)),
                format!("SELECT * FROM structure WHERE {}", chunk_ranges("chunk", xs, ys)),
            ],
            Which::Lots => vec![format!("SELECT * FROM lot WHERE {}", chunk_ranges("chunk", xs, ys))],
        };
        Some((vec![chunk_id(cx as u32, cy as u32)], q))
    }

    /// Staged genesis (`genesis.rs`): read the `genesis` row, subscribe the base once the world is
    /// ready, and send a held `join` again when it turns ready or its backoff runs out.
    fn watch_genesis(&mut self, now: f64) {
        if self.genesis_applied {
            let row = self.conn.as_ref().and_then(|c| c.db.genesis().id().find(&0));
            let was = self.genesis.gate;
            let before = self.genesis.progress.clone();
            self.genesis.row(row.as_ref().map(crate::genesis::Progress::of_row), row.as_ref().is_some_and(|g| g.done), now);
            match (was, self.genesis.gate) {
                (crate::genesis::Gate::Preparing, crate::genesis::Gate::Ready) => {
                    info!("genesis: the world is ready after {:.1} s preparing", now - self.genesis.since.unwrap_or(now));
                }
                (_, crate::genesis::Gate::Preparing) if self.genesis.progress != before => {
                    info!("genesis: preparing {}", self.genesis.progress.as_ref().map(|p| p.line()).unwrap_or_default());
                }
                _ => {}
            }
        }
        if self.genesis.long(now) && !self.genesis.told_long {
            self.genesis.told_long = true;
            warn!("genesis: still preparing after {:.0} s; waiting on", crate::genesis::TIMEOUT_S);
        }
        if self.static_in && self.base.is_none() && self.genesis.ready() {
            self.subscribe_base();
        }
        if self.genesis.poll(now) == crate::genesis::Retry::Join && self.my_id.is_none() {
            info!("genesis: joining again ({})", if self.genesis.ready() { "the world is ready" } else { "after a wait" });
            self.join_sent = false;
        }
    }

    /// Ask for a new character after my death (the death screen's "Arrive as a new stranger"):
    /// the next `maintain` joins again.
    pub fn rejoin(&mut self) {
        self.join_sent = false;
        self.died = false;
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
            // The base waits for the world to be made (below).
            Signal::Static => net.static_in = true,
            Signal::GenesisSub(h) => net.genesis_sub = Some(h),
            Signal::GenesisApplied => net.genesis_applied = true,
            Signal::GenesisMissing(e) => {
                // A module from before staged genesis: its worlds are made inline, so ready.
                info!("genesis: no `genesis` table on this world ({e}); it counts as ready");
                net.genesis.no_table(now);
            }
            Signal::Preparing { join, err } => {
                let was = net.genesis.gate;
                net.genesis.refused(&err, join, now);
                if was != crate::genesis::Gate::Preparing {
                    info!("genesis: the world is being made: {}", net.genesis.progress.as_ref().map(|p| p.line()).unwrap_or_default());
                }
            }
            Signal::Base => {
                info!("world subscribed after {now:.1} s ({} law overrides)", net.conn.as_ref().map_or(0, |c| c.db.law_override().count()));
                // The rows are this connection's now: laid over before a law is read this frame
                // (`verbs::refresh_rules` runs before `perception_law`), so a reconnect never
                // chooses its set by the last connection's values.
                law_rows_moved();
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
                net.gaze_view = None;
                net.gaze.reset_owner();
                net.near = Window::default();
                net.far = Window::default();
                net.perception = Window::default();
                net.combat_once = None;
                net.combat_once_asked = false;
                net.my_id = None;
                // Dead and not yet asked to arrive again: the reconnect joins no one.
                net.join_sent = net.died;
                net.genesis = Default::default();
                net.genesis_sub = None;
                net.genesis_applied = false;
                net.static_in = false;
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
    net.watch_genesis(now);
    net.maintain(now);
}

#[cfg(test)]
mod cue_tests {
    use super::*;

    fn moving(id: u32) -> Moving {
        Moving { id, x: 0.0, y: 0.0, t_ms: 1, vx: 0.0, vy: 0.0, heading: 0.0, turn: 0.0, turn_s: 0.0, next_ms: 0, speed: 0.0, face_off: 0.0, face_turn: 0.0, face_turn_s: 0.0, running: false }
    }

    const TIERED: Feed = Feed { tiered: true, motion_table: false, characters_table: false, fighter_table: false, combat_feed: false, lines_table: false, throng: false };
    const UNTIERED: Feed = Feed { tiered: false, motion_table: false, characters_table: false, fighter_table: false, combat_feed: false, lines_table: false, throng: false };
    // The shipped laws since bv-defaults-on: both copy tables on (motion_tables_on,
    // characters_table_on). `fighter_tables_on` and `combat_feed_on` as the shipped script has
    // them (dev-box flips their defaults in the client's change set): read, so a flip breaks no test.
    const SHIPPED_TIERED: Feed = Feed { tiered: true, motion_table: true, characters_table: true, fighter_table: false, combat_feed: false, lines_table: false, throng: false };
    const SHIPPED_UNTIERED: Feed = Feed { tiered: false, motion_table: true, characters_table: true, fighter_table: false, combat_feed: false, lines_table: false, throng: false };

    /// A shipped set (`SHIPPED_TIERED` or `SHIPPED_UNTIERED`) with the two new laws as shipped.
    fn shipped(f: Feed) -> Feed {
        let l = living_rules::script::Scripts::new(SHIPPED).unwrap().laws();
        Feed { fighter_table: l.fighter_tables_on, combat_feed: l.combat_feed_on, lines_table: l.lines_table_on, ..f }
    }

    fn feed_of(cues: bool, tiers: bool, motion_tables: bool, characters_table: bool) -> Feed {
        Delivery { cues, tiers, motion_tables, characters_table, fighter_tables: false, combat_feed: false, lines_table: true, throng: false }.feed()
    }

    #[test]
    fn the_lines_table_takes_experience_copy_in_place_of_my_experience() {
        // experience-incremental: one query swapped, the key round trip, and the shipped laws on it.
        let off = Feed { lines_table: false, ..SHIPPED_TIERED };
        let on = Feed { lines_table: true, ..SHIPPED_TIERED };
        assert!(off.queries().contains(&LINES_VIEW) && !off.queries().contains(&LINES_TABLE));
        assert!(on.queries().contains(&LINES_TABLE) && !on.queries().contains(&LINES_VIEW));
        assert_eq!(on.queries().len(), off.queries().len());
        assert_eq!(Feed::of_key(on.key()), on);
        assert_ne!(on.key(), off.key());
        let l = living_rules::script::Scripts::new(SHIPPED).unwrap().laws();
        assert!(l.lines_table_on, "the lines table is on as shipped");
        assert!(delivery_laws(&l).feed().lines_table);
    }

    fn feed_of6(k: u32) -> (Delivery, Feed) {
        let b = |i: u32| k & (1 << i) != 0;
        let d = Delivery { cues: b(0), tiers: b(1), motion_tables: b(2), characters_table: b(3), fighter_tables: b(4), combat_feed: b(5), lines_table: true, throng: false };
        (d, Feed { tiered: b(0) || b(1), motion_table: b(2), characters_table: b(3), fighter_table: b(4), combat_feed: b(5), lines_table: true, throng: false })
    }

    #[test]
    fn the_untiered_set_is_main_s_three_views_and_the_base_holds_no_stream() {
        // Both frame laws off and both table laws off: the client subscribes exactly main's
        // perception queries (main had `seen_characters` in its base set; it is in the
        // perception set here, so the table law can replace it).
        assert_eq!(UNTIERED_STREAMS, ["SELECT * FROM seen_bodies", "SELECT * FROM seen_fighters", "SELECT * FROM seen_doing"]);
        assert_eq!(TIERED_STREAMS.len(), 9);
        // My combat feed moved from the base set to this one (`my_combat`, as main subscribed it),
        // so its law can replace it.
        // So did my lines (`my_experience`, experience-incremental), so the lines law can replace it.
        assert_eq!(UNTIERED.queries(), ["SELECT * FROM seen_characters", "SELECT * FROM my_combat", "SELECT * FROM my_experience", "SELECT * FROM seen_bodies", "SELECT * FROM seen_fighters", "SELECT * FROM seen_doing"]);
        let mut tiered = vec![CHARACTERS_VIEW, COMBAT_VIEW, LINES_VIEW];
        tiered.extend(TIERED_STREAMS);
        assert_eq!(TIERED.queries(), tiered);
        for q in UNTIERED_STREAMS.iter().chain(TIERED_STREAMS).chain([&CHARACTERS_VIEW, &CHARACTERS_TABLE, &MOTION_TABLE, &FIGHTER_TABLE, &COMBAT_VIEW, &COMBAT_FEED, &LINES_VIEW, &LINES_TABLE]) {
            assert!(!PERCEIVED.contains(q), "{q} is in the base set too");
        }
        for v in MOTION_VIEWS {
            assert!(UNTIERED_STREAMS.contains(v) || TIERED_STREAMS.contains(v), "{v} is not a motion stream");
        }
        for v in FIGHTER_VIEWS {
            assert!(UNTIERED_STREAMS.contains(v) || TIERED_STREAMS.contains(v), "{v} is not a fighter stream");
        }
        assert!(FIGHTER_VIEWS.iter().all(|v| !MOTION_VIEWS.contains(v)));
    }

    #[test]
    fn each_table_law_replaces_exactly_its_views_in_every_frame_tier_state() {
        for k in 0..32 {
            let f = Feed::of_key(k);
            assert_eq!(f.key(), k, "the key round-trips");
            let q = f.queries();
            let has = |x: &str| q.contains(&x);
            let mut sorted = q.clone();
            sorted.sort_unstable();
            sorted.dedup();
            assert_eq!(sorted.len(), q.len(), "{f:?}: a query twice: {q:?}");
            // The characters: the view or the mirror, never both; my combat feed likewise.
            assert_eq!((has(CHARACTERS_VIEW), has(CHARACTERS_TABLE)), (!f.characters_table, f.characters_table), "{f:?}");
            assert_eq!((has(COMBAT_VIEW), has(COMBAT_FEED)), (!f.combat_feed, f.combat_feed), "{f:?}");
            // The bodies and the fighters: the views of the tier state, or the table in their place.
            for (views, table, on, all) in [(MOTION_VIEWS, MOTION_TABLE, f.motion_table, "seen_bodies"), (FIGHTER_VIEWS, FIGHTER_TABLE, f.fighter_table, "seen_fighters")] {
                for v in views {
                    assert!(!(on && has(v)), "{f:?} keeps {v} beside the table");
                }
                assert_eq!(has(table), on, "{f:?}");
                if !on {
                    let (all, near, far) = (format!("SELECT * FROM {all}"), format!("SELECT * FROM {all}_near"), format!("SELECT * FROM {all}_far"));
                    if f.tiered {
                        assert!(has(&near) && has(&far) && !has(&all), "{f:?}");
                    } else {
                        assert!(has(&all) && !has(&near), "{f:?}");
                    }
                }
            }
            // The other streams follow the tier state alone; the cue tables stay with the tiers
            // (a cue stands until that creature's next copy row).
            let rest: Vec<&str> = if f.tiered { TIERED_STREAMS.to_vec() } else { UNTIERED_STREAMS.to_vec() };
            for s in rest.iter().filter(|s| !MOTION_VIEWS.contains(s) && !FIGHTER_VIEWS.contains(s)) {
                assert!(has(s), "{f:?} lacks {s}");
            }
            assert_eq!(has("SELECT * FROM seen_body_cue"), f.tiered, "{f:?}");
            assert_eq!(has("SELECT * FROM seen_fighter_cue"), f.tiered, "{f:?}");
            let per = if f.tiered { 2 } else { 1 };
            let n = 3 + rest.len() - if f.motion_table { per - 1 } else { 0 } - if f.fighter_table { per - 1 } else { 0 };
            assert_eq!(q.len(), n, "{f:?}: {q:?}");
        }
    }

    #[test]
    fn heed_off_leaves_every_set_as_it_was_and_on_adds_only_the_throng() {
        // The laws-off path: for every one of the 64 sets the delivery laws can choose, the throng
        // bit off is the set before heed (the same key, the same queries in the same order).
        for k in 0..64u32 {
            let f = Feed::of_key(k);
            assert!(!f.throng);
            assert_eq!(f.key(), k);
            assert!(!f.queries().contains(&THRONG_TABLE));
            assert!(!f.tables().contains("throng"), "{}", f.tables());
            // On: exactly one query more, the throng's, last; a key of its own.
            let on = Feed { throng: true, ..f };
            let mut q = f.queries();
            q.push(THRONG_TABLE);
            assert_eq!(on.queries(), q);
            assert_eq!(Feed::of_key(on.key()), on);
            assert_ne!(on.key(), f.key());
        }
        assert!(!PERCEIVED.contains(&THRONG_TABLE));
        // The two laws: only both on choose it; shipped, both are off.
        use living_rules::script::{with_world_laws, Scripts};
        let shipped = include_str!("../../scripts/skills.rhai");
        assert!(!delivery_laws(&Scripts::new(shipped).unwrap().laws()).throng);
        assert!(!delivery_fallback().throng);
        for (on, players, want) in [(false, false, false), (true, false, false), (false, true, false), (true, true, true)] {
            let values = [("heed_on".to_string(), serde_json::json!(on)), ("heed_players".to_string(), serde_json::json!(players))];
            let d = delivery_laws(&Scripts::new(&with_world_laws(shipped, &values)).unwrap().laws());
            assert_eq!((d.throng, d.feed().throng), (want, want), "heed_on {on} heed_players {players}");
        }
    }

    #[test]
    fn the_four_delivery_laws_are_read_beside_the_seen_ranges_laws_and_choose_the_set() {
        use living_rules::script::{with_world_laws, Scripts};
        let shipped = include_str!("../../scripts/skills.rhai");
        let sc = Scripts::new(shipped).unwrap();
        // The shipped script as this branch finds it: both frame laws on, the table laws as
        // shipped (dev-box flips the defaults; nothing here depends on them), beside main's
        // seen_ranges laws.
        let d = delivery_laws(&sc.laws());
        assert!(d.cues && d.tiers, "{d:?}");
        assert!(sc.laws().seen_ranges && !sc.laws().seen_ranges_check, "the seen_ranges laws read as shipped");
        assert_eq!(d.feed().tiered, true);
        assert_eq!((d.feed().motion_table, d.feed().characters_table, d.feed().fighter_table, d.feed().combat_feed), (d.motion_tables, d.characters_table, d.fighter_tables, d.combat_feed));
        // A world's own values, as the authority writes them after `set_world_law`: each of the
        // sixty-four states, with the seen_ranges laws changed beside them so a neighbour cannot
        // mask a law that was not found.
        for k in 0..64u32 {
            let (want_d, want_f) = feed_of6(k);
            let values = [
                ("seen_ranges".to_string(), serde_json::json!(false)),
                ("cue_transport_on".to_string(), serde_json::json!(want_d.cues)),
                ("seen_ranges_check".to_string(), serde_json::json!(true)),
                ("near_tier_on".to_string(), serde_json::json!(want_d.tiers)),
                ("motion_tables_on".to_string(), serde_json::json!(want_d.motion_tables)),
                ("characters_table_on".to_string(), serde_json::json!(want_d.characters_table)),
                ("fighter_tables_on".to_string(), serde_json::json!(want_d.fighter_tables)),
                ("combat_feed_on".to_string(), serde_json::json!(want_d.combat_feed)),
            ];
            let l = Scripts::new(&with_world_laws(shipped, &values)).unwrap().laws();
            let d = delivery_laws(&l);
            assert_eq!(d, want_d);
            assert!(!l.seen_ranges && l.seen_ranges_check);
            assert_eq!(d.feed(), want_f, "{d:?}");
            if !d.fighter_tables && !d.combat_feed {
                assert_eq!(d.feed(), feed_of(d.cues, d.tiers, d.motion_tables, d.characters_table));
            }
        }
        // A script that does not compile, with no law read before: the rules' defaults, as a fresh
        // world starts.
        assert_eq!(delivery_fallback(), delivery_laws(&living_rules::script::Laws::default()));
        assert!(delivery_fallback().feed().tiered);
    }

    #[test]
    fn copy_rows_map_to_the_views_rows() {
        // `seen_body_copy`: the segment and the creature, as `seen_bodies` gives it (every field
        // distinct, so a swapped pair fails).
        let seg = Segment { x: 1.5, y: 2.5, t_ms: 3, vx: 4.5, vy: 5.5, heading: 6.5, turn: 7.5, turn_s: 8.5, next_ms: 9, speed: 10.5, face_off: 11.5, face_turn: 12.5, face_turn_s: 13.5, running: true };
        let row = SeenBodyCopy { viewer: Identity::ZERO, body: 42, near: true, seg };
        let m = Moving { id: 42, x: 1.5, y: 2.5, t_ms: 3, vx: 4.5, vy: 5.5, heading: 6.5, turn: 7.5, turn_s: 8.5, next_ms: 9, speed: 10.5, face_off: 11.5, face_turn: 12.5, face_turn_s: 13.5, running: true };
        assert_eq!(moving_of(&row), m);
        // `seen_character_copy`: the row is the view's row, keyed by the creature, not the
        // projected row's id.
        let c = Copies::default();
        let ch = SeenCharacterCopy { id: 900, viewer: Identity::ZERO, row: character(7) };
        c.put_character(&ch);
        assert_eq!(c.characters.lock().unwrap().get(&7).map(|c| c.row.clone()), Some(character(7)));
        assert!(!c.characters.lock().unwrap().contains_key(&900));
        // `seen_fighter_copy`: the row is the view's row, by the creature, not the copy's key.
        let f = fighter_copy(77, 12, 3);
        c.put_fighter(&f);
        assert_eq!(c.fighters.lock().unwrap().get(&12).map(|x| x.fighter.clone()), Some(fighter(12, 3)));
        assert!(!c.fighters.lock().unwrap().contains_key(&77));
        // `combat_feed`: the event row is the `my_combat` row with the same id, every field (each
        // distinct, so a swapped pair fails).
        let e = CombatFeed { id: 31, viewer: Identity::ONE, expires_ms: 2, at_ms: 3, kind: 4, actor: 5, target: 6, skill: 7, x: 8.5, y: 9.5, dx: 10.5, dy: 11.5, amount: 12.5, ms: 13, note: "n".into() };
        let v = CombatSeen { id: 31, viewer: Identity::ONE, expires_ms: 2, at_ms: 3, kind: 4, actor: 5, target: 6, skill: 7, x: 8.5, y: 9.5, dx: 10.5, dy: 11.5, amount: 12.5, ms: 13, note: "n".into() };
        assert_eq!(combat_of(&e), v);
    }

    fn fighter(id: u32, band: u8) -> Fighter {
        Fighter { id, band, act: 1, act_ms: 2, release_ms: 3, until_ms: 4, target: 5, aim_x: 6.5, aim_y: 7.5 }
    }

    fn fighter_copy(key: u64, body: u32, band: u8) -> SeenFighterCopy {
        SeenFighterCopy { id: key, viewer: Identity::ZERO, body, near: false, fighter: fighter(body, band) }
    }

    #[test]
    fn a_fighter_copy_change_replaces_the_row_and_the_kill_switch_keeps_rows() {
        let c = Copies::default();
        // An update in place (the table is keyed): the new row replaces the old.
        c.put_fighter(&fighter_copy(1, 5, 4));
        c.put_fighter(&fighter_copy(1, 5, 2));
        assert_eq!(c.fighters.lock().unwrap().get(&5).map(|x| x.fighter.band), Some(2));
        // A delete of another key for the same creature (a viewer's former character's copy)
        // leaves the row I hold.
        c.drop_fighter(&fighter_copy(9, 5, 4), false);
        assert!(c.fighters.lock().unwrap().contains_key(&5));
        // The kill switch moves every public copy back in one tick: while the rows are kept
        // (leaving, or the law's row reads off), its deletes leave them for the reads.
        c.drop_fighter(&fighter_copy(1, 5, 2), true);
        assert!(c.fighters.lock().unwrap().contains_key(&5));
        // Not kept: the creature's copy goes.
        c.drop_fighter(&fighter_copy(1, 5, 2), false);
        assert!(c.fighters.lock().unwrap().is_empty());
    }

    #[test]
    fn combat_feed_rows_wait_for_the_reader_and_stay_bounded() {
        let cues = Cues::default();
        let r = |id: u64| CombatSeen { id, viewer: Identity::ZERO, expires_ms: 0, at_ms: 0, kind: 1, actor: 1, target: 0, skill: 0, x: 0.0, y: 0.0, dx: 0.0, dy: 0.0, amount: 0.0, ms: 0, note: String::new() };
        cues.pend_combat((0..10).map(r));
        cues.pend_combat([r(10)]);
        assert_eq!(cues.combat.lock().unwrap().iter().map(|x| x.id).collect::<Vec<_>>(), (0..11).collect::<Vec<_>>(), "kept in arrival order");
        cues.pend_combat((11..COMBAT_PENDING_MAX as u64 + 20).map(r));
        let p = cues.combat.lock().unwrap();
        assert_eq!(p.len(), COMBAT_PENDING_MAX);
        assert_eq!(p.first().map(|x| x.id), Some(20), "the oldest go first");
    }

    fn character(id: u32) -> SeenCharacter {
        SeenCharacter { id, name: "Ash".into(), label: "a woman".into(), kind: "person".into(), stage: 2, folk: "f".into(), style: "s".into(), own: false, band: 1, hp: 9.0, max_hp: 10.0, look: "k".into() }
    }

    fn copy(body: u32, t_ms: u64) -> SeenBodyCopy {
        let m = moving(body);
        let seg = Segment { x: m.x, y: m.y, t_ms, vx: m.vx, vy: m.vy, heading: m.heading, turn: m.turn, turn_s: m.turn_s, next_ms: m.next_ms, speed: m.speed, face_off: m.face_off, face_turn: m.face_turn, face_turn_s: m.face_turn_s, running: m.running };
        SeenBodyCopy { viewer: Identity::ZERO, body, near: false, seg }
    }

    #[test]
    fn a_copy_change_replaces_the_row_in_either_callback_order_and_the_kill_switch_keeps_rows() {
        let c = Copies::default();
        // A change comes as the new row's insert, then the old row's delete (the SDK fires inserts
        // first): the new row stays.
        assert!(c.put_body(&copy(5, 1)).is_none());
        let old = c.put_body(&copy(5, 2));
        assert_eq!(old, Some(copy(5, 1)), "the replaced row is told (the display clock's segment change)");
        c.drop_body(&copy(5, 1), false);
        assert_eq!(c.bodies.lock().unwrap().get(&5), Some(&copy(5, 2)));
        // A creature that left: its row goes.
        c.drop_body(&copy(5, 2), false);
        assert!(c.bodies.lock().unwrap().is_empty());
        // The kill switch empties the table in one tick: while the rows are kept (leaving, or
        // the law's row reads off), its deletes leave them for the reads until the views are in.
        c.put_body(&copy(6, 1));
        c.drop_body(&copy(6, 1), true);
        assert!(c.bodies.lock().unwrap().contains_key(&6));
        // The mirror: a projected row replaced under a new id (insert first) keeps the new one;
        // kept rows stay through the kill switch's deletes.
        let a = SeenCharacterCopy { id: 1, viewer: Identity::ZERO, row: character(7) };
        let b = SeenCharacterCopy { id: 2, viewer: Identity::ZERO, row: character(7) };
        c.put_character(&a);
        c.put_character(&b);
        c.drop_character(&a, false);
        assert_eq!(c.characters.lock().unwrap().get(&7).map(|x| x.id), Some(2));
        c.drop_character(&b, true);
        assert!(c.characters.lock().unwrap().contains_key(&7));
        c.drop_character(&b, false);
        assert!(c.characters.lock().unwrap().is_empty());
    }

    /// `law_override` rows as the bindings deliver them.
    fn rows(of: &[(&str, &str)]) -> Vec<LawOverride> {
        of.iter().enumerate().map(|(i, (name, value))| LawOverride { name: name.to_string(), value: value.to_string(), revision: i as u32 + 1 }).collect()
    }

    fn set_of(rules: &crate::verbs::Rules) -> Feed {
        delivery_laws(&rules.scripts.as_ref().expect("compiled").laws()).feed()
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
        assert_eq!(set_of(&rules), shipped(SHIPPED_TIERED));
        let key = rules.laws_key;
        // Both delivery laws off by `law_override` alone, the script row unchanged.
        let off = crate::verbs::overrides_of_rows(&rows(&[("cue_transport_on", "false"), ("near_tier_on", "false")]));
        rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &off, 2);
        let a = rules.applied.clone().expect("laid over in place, not compiled");
        assert!(a.delivery && !a.cover && !a.gaze, "{a:?}");
        assert_eq!(a.changed, ["cue_transport_on", "near_tier_on"]);
        assert_eq!(rules.revision, 7);
        assert!(rules.laws_key > key, "the laws' readers see a change");
        assert_eq!(set_of(&rules), shipped(SHIPPED_UNTIERED), "both tier laws off: the untiered set, the copy tables still on");
        // One back on: the tiers again.
        let one = crate::verbs::overrides_of_rows(&rows(&[("cue_transport_on", "false"), ("near_tier_on", "true")]));
        let key = rules.laws_key;
        rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &one, 3);
        assert_eq!(rules.applied.as_ref().map(|a| a.changed.clone()), Some(vec!["near_tier_on".to_string()]));
        assert!(rules.laws_key > key);
        assert_eq!(set_of(&rules), shipped(SHIPPED_TIERED));
        // The same rows again (a row rewritten with its value): nothing in force changed, so
        // nothing that reads the laws reads them again.
        let key = rules.laws_key;
        rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &one, 4);
        assert_eq!(rules.laws_key, key);
    }

    #[test]
    fn the_table_laws_flip_the_set_in_place_as_delivery_laws_in_every_combination() {
        let mut rules = crate::verbs::Rules::default();
        rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &[], 1);
        let start = set_of(&rules);
        let mut n = 2;
        // Each table law alone, both, and back, under each frame state the doc allows, and the
        // fighter and combat feed laws in each of their four states over those: every change is
        // laid over in place as the delivery class (`Applied::delivery`, the subscription switch),
        // with the script revision kept and the laws' key moved.
        let tf = |b: bool| if b { "true" } else { "false" };
        for (fighters, feed) in [(false, false), (true, false), (false, true), (true, true)] {
            for (cues, tiers) in [("true", "true"), ("true", "false"), ("false", "true"), ("false", "false")] {
                for (motion, chars) in [("true", "false"), ("false", "true"), ("true", "true"), ("false", "false")] {
                    let key = rules.laws_key;
                    let before = set_of(&rules);
                    let over = crate::verbs::overrides_of_rows(&rows(&[
                        ("cue_transport_on", cues),
                        ("near_tier_on", tiers),
                        ("motion_tables_on", motion),
                        ("characters_table_on", chars),
                        ("fighter_tables_on", tf(fighters)),
                        ("combat_feed_on", tf(feed)),
                    ]));
                    rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &over, n);
                    n += 1;
                    let want = Feed { fighter_table: fighters, combat_feed: feed, ..feed_of(cues == "true", tiers == "true", motion == "true", chars == "true") };
                    assert_eq!(set_of(&rules), want);
                    assert_eq!(rules.revision, 7);
                    if want != before {
                        let a = rules.applied.clone().expect("laid over in place, not compiled");
                        assert!(a.delivery && !a.cover && !a.gaze, "{a:?}");
                        assert!(rules.laws_key > key, "the set's reader sees the change");
                    }
                }
            }
        }
        // Each of the two alone flips only its own flag, in place, from the shipped set.
        for law in ["fighter_tables_on", "combat_feed_on"] {
            for value in ["true", "false"] {
                let before = set_of(&rules);
                rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &crate::verbs::overrides_of_rows(&rows(&[(law, value)])), n);
                n += 1;
                let on = value == "true";
                let want = if law == "fighter_tables_on" { Feed { fighter_table: on, ..shipped(start) } } else { Feed { combat_feed: on, ..shipped(start) } };
                assert_eq!(set_of(&rules), want, "{law} {value}");
                if want != before {
                    assert_eq!(rules.applied.as_ref().map(|a| a.delivery), Some(true), "{law} {value}: laid over in place as delivery");
                }
            }
        }
        // The rows gone: the shipped values again, in place.
        rules.take(7, SHIPPED, living_rules::DEFAULT_DAY_MS, &[], n);
        assert_eq!(set_of(&rules), start);
    }

    #[test]
    fn a_reconnect_with_the_table_laws_on_chooses_the_tables_first() {
        // A fresh compile with the rows (a reconnect, or a client started on the world): the
        // first set chosen reads every table its law names, so no view set comes first.
        let on = crate::verbs::overrides_of_rows(&rows(&[("motion_tables_on", "true"), ("characters_table_on", "true"), ("fighter_tables_on", "true"), ("combat_feed_on", "true")]));
        let mut rules = crate::verbs::Rules::default();
        rules.take(9, SHIPPED, living_rules::DEFAULT_DAY_MS, &on, 1);
        assert!(rules.applied.is_none(), "compiled with them");
        assert_eq!(set_of(&rules), Feed { tiered: true, motion_table: true, characters_table: true, fighter_table: true, combat_feed: true, lines_table: true, throng: false });
        let off = crate::verbs::overrides_of_rows(&rows(&[("cue_transport_on", "false"), ("near_tier_on", "false"), ("motion_tables_on", "true"), ("characters_table_on", "true"), ("fighter_tables_on", "true"), ("combat_feed_on", "false")]));
        let mut rules = crate::verbs::Rules::default();
        rules.take(9, SHIPPED, living_rules::DEFAULT_DAY_MS, &off, 1);
        assert_eq!(set_of(&rules), Feed { tiered: false, motion_table: true, characters_table: true, fighter_table: true, combat_feed: false, lines_table: true, throng: false });
        // The two new laws off by row on a world whose script has them on: the views first.
        let script_on = SHIPPED.replace("fighter_tables_on: false,", "fighter_tables_on: true,").replace("combat_feed_on: false,", "combat_feed_on: true,");
        let off = crate::verbs::overrides_of_rows(&rows(&[("fighter_tables_on", "false"), ("combat_feed_on", "false")]));
        let mut rules = crate::verbs::Rules::default();
        rules.take(9, &script_on, living_rules::DEFAULT_DAY_MS, &off, 1);
        let f = set_of(&rules);
        assert!(!f.fighter_table && !f.combat_feed, "{f:?}");
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
        assert_eq!(set_of(&rules), shipped(SHIPPED_UNTIERED));
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
        assert_eq!(set_of(&rules), shipped(SHIPPED_TIERED));
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
