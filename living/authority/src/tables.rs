//! Typed tables grouped by access pattern. Hot rows (body, vitals, activity, mind_state)
//! are small and written only when their state changes; cold rows (character, brain,
//! persona) change rarely. Percepts and deliberations are private and delivered to
//! their controller through per-sender views.

use spacetimedb::{Identity, ScheduleAt, SpacetimeType};

#[spacetimedb::table(accessor = world, public)]
pub struct World {
    #[primary_key]
    pub id: u8,
    pub run: String,
    pub seed: u64,
    pub epoch_ms: u64,
    pub day_ms: u64,
    /// Publisher; also the default mind controller for AI characters.
    pub admin: Identity,
    pub paused: bool,
    /// Map size in tiles.
    #[default(96u32)]
    pub width: u32,
    #[default(96u32)]
    pub height: u32,
    /// How fast lives run: lifespans are multiplied by this (1 = a world for play; a lab
    /// scenario compresses lives to watch generations in an evening).
    #[default(1.0f32)]
    pub life_pace: f32,
    /// Days in the calendar year (four equal seasons; lifespans are counted in years).
    #[default(8u32)]
    pub year_days: u32,
}

/// A gate's state, apart from its structure row (which rarely changes): open or shut, and the
/// community whose members may open and close it (0 = anyone).
#[spacetimedb::table(accessor = gate, public)]
pub struct Gate {
    #[primary_key]
    pub id: u64,
    pub x: i32,
    pub y: i32,
    pub open: bool,
    pub community: u32,
    pub changed_ms: u64,
    pub changed_by: u32,
}

/// Where a seeded character comes from (town, household, occupation, history) as JSON.
/// World fact, not identity: the character's mind builds its identity from it.
#[spacetimedb::table(accessor = background, public)]
pub struct Background {
    #[primary_key]
    pub id: u32,
    pub text: String,
}

/// Private tick bookkeeping (not broadcast).
#[spacetimedb::table(accessor = clock)]
pub struct Clock {
    #[primary_key]
    pub id: u8,
    pub tick: u64,
    pub last_ms: u64,
    pub last_hour: u8,
    pub scripts_rev: u32,
    pub max_gap_ms: u32,
    pub evals: u64,
    pub motions: u64,
    pub completions: u64,
    pub percepts: u64,
    pub deliberations: u64,
    /// When set, every tick logs its duration (LogStopwatch) for benchmarking.
    #[default(false)]
    pub profile: bool,
    #[default(0u64)]
    pub hits: u64,
    #[default(0u64)]
    pub dodged: u64,
    #[default(0u64)]
    pub blocked: u64,
    /// Blows that landed on air: the target got out of reach during the windup.
    #[default(0u64)]
    pub missed: u64,
}

#[spacetimedb::table(accessor = script, public)]
pub struct Script {
    #[primary_key]
    pub name: String,
    pub source: String,
    pub revision: u32,
    pub updated_ms: u64,
}

#[spacetimedb::table(accessor = terrain_chunk, public)]
pub struct TerrainChunk {
    #[primary_key]
    pub id: u32,
    pub tiles: Vec<u8>,
}

#[spacetimedb::table(accessor = character, public)]
pub struct Character {
    #[primary_key]
    #[auto_inc]
    pub id: u32,
    pub name: String,
    /// `person`, `deer`, `wolf`.
    #[index(btree)]
    pub kind: String,
    #[index(btree)]
    pub controller: Identity,
    /// Driven by an LLM mind (deliberations and percepts are produced).
    pub ai: bool,
    pub alive: bool,
    pub born_ms: u64,
    pub died_ms: u64,
    pub cause: String,
    pub home_x: f32,
    pub home_y: f32,
    /// Age in days at `born_ms` (seed adults start grown; newborns at 0).
    #[default(18.0)]
    pub birth_age_days: f32,
    #[default(0u32)]
    pub parent_a: u32,
    #[default(0u32)]
    pub parent_b: u32,
    /// Life stage, kept current by housekeeping: 0 infant, 1 child, 2 adult, 3 elder.
    #[default(2u8)]
    pub stage: u8,
}

#[derive(SpacetimeType, Clone, Copy, Debug, PartialEq)]
pub struct Waypoint {
    pub x: f32,
    pub y: f32,
}

/// A body's current motion segment: from `(x, y)` facing `heading` at `t_ms`, moving at
/// speed `|(vx, vy)|` (tiles/s; `(vx, vy)` is the velocity at `t_ms`), turning at `turn`
/// rad/s for the first `turn_s` seconds (a circular arc) and straight afterwards, until
/// `next_ms`, when steering looks again (see `living_rules::steer::pose`). Clients
/// extrapolate between writes; the row changes only at steering updates.
#[spacetimedb::table(accessor = body, public)]
pub struct Body {
    #[primary_key]
    pub id: u32,
    /// Denormalized creature kind for spatial queries.
    pub kind: String,
    pub x: f32,
    pub y: f32,
    pub t_ms: u64,
    pub vx: f32,
    pub vy: f32,
    /// Remaining corners of the coarse path being followed (empty when steering directly).
    pub path: Vec<Waypoint>,
    /// Desired (cruising) speed of the current movement, before roads.
    pub speed: f32,
    #[index(btree)]
    pub chunk: u32,
    #[index(btree)]
    pub next_ms: u64,
    /// Facing at `t_ms`, radians (+x east, +y south); kept while standing.
    #[default(0.0f32)]
    pub heading: f32,
    /// Turn rate at the start of the segment, rad/s.
    #[default(0.0f32)]
    pub turn: f32,
    /// How long the turn lasts from `t_ms`, seconds (then straight on).
    #[default(0.0f32)]
    pub turn_s: f32,
}

/// What a body is steering for (private; written when the goal changes, not per update).
#[derive(Clone, Debug)]
#[spacetimedb::table(accessor = steer)]
pub struct Steer {
    #[primary_key]
    pub id: u32,
    /// `GOAL_*` in motion.rs: none, a point, a creature, a direction, away from something.
    pub goal: u8,
    /// Creature pursued, followed or fled from.
    pub target: u32,
    /// Destination; unit direction; or the point fled from.
    pub gx: f32,
    pub gy: f32,
    /// Distance to keep from a creature, or the distance at which a flight is safe.
    pub keep: f32,
    /// `FLAG_*` in motion.rs.
    pub flags: u8,
    /// Arrival already reported to the activity.
    pub reported: bool,
    /// Last coarse path plan (re-planning is throttled).
    pub plan_ms: u64,
    /// Movement input bucket of a player (tokens refill at the `input_hz` law).
    pub tokens: f32,
    pub input_ms: u64,
}

/// Needs anchored at `at_ms` with per-minute rates.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = vitals, public)]
pub struct Vitals {
    #[primary_key]
    pub id: u32,
    pub hp: f32,
    pub max_hp: f32,
    pub hunger: f32,
    pub energy: f32,
    pub at_ms: u64,
    pub hp_rate: f32,
    pub hunger_rate: f32,
    pub energy_rate: f32,
    pub rate_key: u32,
    pub hurt_ms: u64,
    pub hurt_by: u32,
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub struct TargetRef {
    /// 0 none, 1 resource, 2 structure, 3 creature, 4 point.
    pub class: u8,
    pub id: u64,
    pub x: f32,
    pub y: f32,
}

#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = activity, public)]
pub struct Activity {
    #[primary_key]
    pub id: u32,
    pub skill: String,
    /// 0 approaching the target, 1 performing.
    pub phase: u8,
    /// Behavior node that owns this activity (u16::MAX when orphaned by a new graph).
    pub node: u16,
    pub revision: u32,
    pub target: TargetRef,
    pub item: String,
    pub qty: u32,
    pub started_ms: u64,
    #[index(btree)]
    pub ends_ms: u64,
    pub label: String,
    /// Words to write (write) and the technique a text describes.
    pub text: String,
    pub topic: String,
    /// The creature an attack or throw is aimed at (0 if none), for `threatened`.
    #[index(btree)]
    #[default(0u32)]
    pub victim: u32,
    /// Trade offers: what is asked in return.
    #[default("")]
    pub want: String,
    #[default(0u32)]
    pub want_qty: u32,
}

/// Items held by a creature (`owner = id`) or a structure (`owner = STRUCTURE_BIT | id`).
#[spacetimedb::table(accessor = inventory, public,
    index(accessor = by_owner_item, btree(columns = [owner, item])))]
pub struct Inventory {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub owner: u64,
    pub item: String,
    pub qty: u32,
}

pub const STRUCTURE_BIT: u64 = 1 << 40;

#[spacetimedb::table(accessor = resource_node, public)]
pub struct ResourceNode {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub kind: String,
    pub x: f32,
    pub y: f32,
    #[index(btree)]
    pub chunk: u32,
    /// Amount at `at_ms`; regrows at `regen` per minute up to `max`.
    pub amount: f32,
    pub max: f32,
    pub regen: f32,
    pub at_ms: u64,
}

#[spacetimedb::table(accessor = structure, public)]
pub struct Structure {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub kind: String,
    pub x: f32,
    pub y: f32,
    #[index(btree)]
    pub chunk: u32,
    pub owner: u32,
    pub built_ms: u64,
}

/// Installed behavior graph (cold).
#[spacetimedb::table(accessor = brain, public)]
pub struct Brain {
    #[primary_key]
    pub id: u32,
    pub graph: String,
    pub revision: u32,
    pub plan: String,
    /// `instinct`, `mind` or `human`.
    pub source: String,
    pub installed_ms: u64,
}

#[derive(SpacetimeType, Clone, Copy, Debug, PartialEq)]
pub struct Cursor {
    pub node: u16,
    pub idx: u16,
}

#[derive(SpacetimeType, Clone, Copy, Debug, PartialEq)]
pub struct Mark {
    pub node: u16,
    pub at_ms: u64,
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub struct LeafResult {
    pub node: u16,
    pub revision: u32,
    pub ok: bool,
    pub why: String,
}

#[derive(SpacetimeType, Clone, Copy, Debug, PartialEq)]
pub struct Seen {
    pub id: u32,
    pub at_ms: u64,
}

/// Behavior runtime state (warm). Evaluated in slot `id % 60` every second.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = mind_state, public)]
pub struct MindState {
    #[primary_key]
    pub id: u32,
    #[index(btree)]
    pub slot: u8,
    pub revision: u32,
    pub cursors: Vec<Cursor>,
    pub marks: Vec<Mark>,
    pub last: Option<LeafResult>,
    /// Preorder ids of the currently running branch.
    pub active: Vec<u16>,
    pub status: String,
    pub fails: u16,
    pub heard_ms: u64,
    pub speaker: u32,
    pub spoke_ms: u64,
    pub deliberated_ms: u64,
    pub seen: Vec<Seen>,
    pub alerts: u32,
    /// While in a fight, evaluated at combat cadence (about 15 Hz) until this time.
    #[index(btree)]
    #[default(0u64)]
    pub fast_until: u64,
}

/// Immediate re-evaluation requests (consumed by the next tick).
#[spacetimedb::table(accessor = wake)]
pub struct Wake {
    #[primary_key]
    pub id: u32,
}

/// What reached a character's senses (sights, speech, what happened to them, their own
/// results). Game state, not knowledge: written only by the authority, never edited, kept
/// in a bounded per-character window. Minds read it and record how far they consolidated.
#[spacetimedb::table(accessor = experience, public)]
pub struct Experience {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub observer: u32,
    #[index(btree)]
    pub controller: Identity,
    pub at_ms: u64,
    pub kind: String,
    pub subject: u32,
    pub object: u32,
    pub x: f32,
    pub y: f32,
    pub text: String,
    pub salience: f32,
}

/// Practical know-how: a technique this character can perform. World state (a capability),
/// not belief; it dies with the character unless taught or written down first.
#[spacetimedb::table(accessor = know_how, public,
    index(accessor = by_actor_technique, btree(columns = [actor, technique])))]
pub struct KnowHow {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub technique: String,
    /// How it was acquired: `seed`, `taught by X`, `worked out`, `read X's tablet`.
    pub source: String,
    pub since_ms: u64,
}

/// A written thing in the world: a tablet (held by a creature or structure) or a sign
/// (held by its `sign` structure). Its text is the author's, true or not.
#[spacetimedb::table(accessor = artifact, public)]
pub struct Artifact {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub kind: String,
    /// Creature id, or STRUCTURE_BIT | structure id.
    #[index(btree)]
    pub holder: u64,
    pub author: u32,
    pub author_name: String,
    pub written_ms: u64,
    pub topic: String,
    pub text: String,
}

pub const FAM_ARTIFACT: u64 = 4 << 40;

/// Bodily familiarity: regions, creatures and structures a character has encountered.
/// Recognition, not knowledge: it decides what is new enough to become an experience.
/// `thing` = FAM_REGION | chunk, FAM_CREATURE | id, or FAM_STRUCTURE | id. Bounded per actor.
#[derive(Clone, Debug)]
#[spacetimedb::table(accessor = familiar,
    index(accessor = by_actor_thing, btree(columns = [actor, thing])))]
pub struct Familiar {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub thing: u64,
    pub first_ms: u64,
    pub last_ms: u64,
    pub times: u32,
}

pub const FAM_REGION: u64 = 1 << 40;
pub const FAM_CREATURE: u64 = 2 << 40;
pub const FAM_STRUCTURE: u64 = 3 << 40;

/// How far a character's mind has integrated its experiences (ids <= `upto`).
#[spacetimedb::table(accessor = mind_cursor, public)]
pub struct MindCursor {
    #[primary_key]
    pub actor: u32,
    pub upto: u64,
    pub updated_ms: u64,
}

/// A pending request for the mind to reconsider, with a perceived scene snapshot (JSON).
#[spacetimedb::table(accessor = deliberation)]
pub struct Deliberation {
    #[primary_key]
    pub actor: u32,
    #[index(btree)]
    pub controller: Identity,
    pub reason: String,
    pub requested_ms: u64,
    /// Last time a reason was added (a mind clears only what it has seen).
    pub updated_ms: u64,
    pub scene: String,
    pub revision: u32,
}

// ---- mind projections (observer and behavior inputs) ----------------------

#[spacetimedb::table(accessor = persona, public)]
pub struct Persona {
    #[primary_key]
    pub id: u32,
    pub narrative: String,
    pub values: Vec<String>,
    pub goals: Vec<String>,
    /// JSON object of trait → 0..100.
    pub traits: String,
    pub mood: String,
    pub version: u32,
    pub updated_ms: u64,
}

#[spacetimedb::table(accessor = relation, public,
    index(accessor = by_pair, btree(columns = [actor, other])))]
pub struct Relation {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub other: u32,
    pub trust: f32,
    pub affinity: f32,
    pub label: String,
    pub note: String,
    pub updated_ms: u64,
}

#[spacetimedb::table(accessor = belief, public)]
pub struct Belief {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub about: String,
    pub text: String,
    pub confidence: f32,
    pub updated_ms: u64,
}

#[spacetimedb::table(accessor = judgment, public)]
pub struct Judgment {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub key: String,
    pub value: f32,
    pub why: String,
    pub updated_ms: u64,
}

#[spacetimedb::table(accessor = place, public)]
pub struct Place {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub name: String,
    pub x: f32,
    pub y: f32,
}

#[spacetimedb::table(accessor = thought, public)]
pub struct Thought {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub at_ms: u64,
    /// `deliberate`, `consolidate`, `error`.
    pub kind: String,
    pub summary: String,
    pub detail: String,
    pub latency_ms: u32,
    pub tokens: u32,
    pub model: String,
    /// The mind's id for this reasoning episode; knowledge it produced points back to it.
    pub reference: String,
}

#[spacetimedb::table(accessor = chronicle, public)]
pub struct Chronicle {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub at_ms: u64,
    pub kind: String,
    pub a: u32,
    pub b: u32,
    pub x: f32,
    pub y: f32,
    pub text: String,
}

/// Rolling counters for load measurement (one row, updated by housekeeping).
#[spacetimedb::table(accessor = stats, public)]
pub struct Stats {
    #[primary_key]
    pub id: u8,
    pub at_ms: u64,
    pub ticks: u64,
    pub evals: u64,
    pub motions: u64,
    pub completions: u64,
    pub percepts: u64,
    pub deliberations: u64,
    pub alive_people: u32,
    pub alive_animals: u32,
    pub births: u32,
    pub deaths: u32,
    /// Largest observed gap between consecutive ticks in the last window (ms).
    pub max_tick_gap_ms: u32,
    #[default(0u64)]
    pub hits: u64,
    #[default(0u64)]
    pub dodged: u64,
    #[default(0u64)]
    pub blocked: u64,
    /// Blows that landed on air: the target got out of reach during the windup.
    #[default(0u64)]
    pub missed: u64,
}

/// A standing wish to start a family with someone (expires after two minutes).
#[spacetimedb::table(accessor = bond_offer, public)]
pub struct BondOffer {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub from: u32,
    pub to: u32,
    pub at_ms: u64,
}

/// A community: a named group with a home, founded and joined by consent. A social fact,
/// not an assigned role: what it means is up to its members.
#[spacetimedb::table(accessor = community, public)]
pub struct Community {
    #[primary_key]
    #[auto_inc]
    pub id: u32,
    pub name: String,
    pub founder: u32,
    pub founded_ms: u64,
    pub home_x: f32,
    pub home_y: f32,
}

#[spacetimedb::table(accessor = membership, public)]
pub struct Membership {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub community: u32,
    #[unique]
    pub member: u32,
    pub since_ms: u64,
}

/// A request to join a community, granted when a member welcomes the asker.
#[spacetimedb::table(accessor = join_request, public)]
pub struct JoinRequest {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub asker: u32,
    pub community: u32,
    pub at_ms: u64,
}

/// A standing trade proposal (expires after three minutes).
#[spacetimedb::table(accessor = trade_offer, public)]
pub struct TradeOffer {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub from: u32,
    pub to: u32,
    pub give_item: String,
    pub give_qty: u32,
    pub want_item: String,
    pub want_qty: u32,
    pub at_ms: u64,
}

/// A couple expecting a child, born at `due_ms`.
#[spacetimedb::table(accessor = expecting, public)]
pub struct Expecting {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub a: u32,
    pub b: u32,
    #[index(btree)]
    pub due_ms: u64,
}

// ---- schedules ---------------------------------------------------------------

#[spacetimedb::table(accessor = tick_timer, scheduled(crate::tick::tick))]
pub struct TickTimer {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}

#[spacetimedb::table(accessor = slow_timer, scheduled(crate::tick::housekeeping))]
pub struct SlowTimer {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}
