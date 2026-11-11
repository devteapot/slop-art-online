//! Typed tables grouped by access pattern. Hot rows (body, vitals, activity, mind_state)
//! are small and written only when their state changes; cold rows (character, brain,
//! persona) change rarely.
//!
//! Who may read what is set per table (docs/PERCEPTION.md): static world data is public;
//! developer audit truth (minds' state, thoughts, beliefs, personas, the chronicle) is private,
//! read by the database owner (the mind service and the lab observer); what a player perceives
//! and its own state reach it through the per-sender views in `perception.rs` and
//! `combat.rs`. The tables today's game client reads directly stay public while the build's
//! `LIVING_PERCEPTION` is `open` (the default; `cfg(open_tables)`), and are private when it is
//! `scoped`.

use spacetimedb::{ConnectionId, Identity, ScheduleAt, SpacetimeType};

#[derive(Clone)]
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

/// A character's own named behavior (a routine), called from its graph by name and edited
/// by its mind one at a time, so behavior compounds instead of being rewritten each time.
/// Written only when a mind (or teaching) changes it.
#[spacetimedb::table(accessor = routine)]
pub struct Routine {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub name: String,
    pub graph: String,
    pub revision: u32,
    /// "mind", "habit", "taught by <name>", "read <tablet>".
    pub source: String,
    pub updated_ms: u64,
}

/// How a routine has gone in practice (updated as its actions finish; split from the
/// routine row because it changes far more often).
#[spacetimedb::table(accessor = routine_stat)]
pub struct RoutineStat {
    #[primary_key]
    pub id: u64,
    pub ok: u32,
    pub failed: u32,
    pub last_fail: String,
    pub last_ms: u64,
}

/// Where a seeded character comes from (town, household, occupation, history) as JSON.
/// World fact, not identity: the character's mind builds its identity from it.
#[spacetimedb::table(accessor = background)]
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

/// A world's own value of a law (a seed's `rules`: `minds`, `fire_warmth`, …), over the
/// script's `laws()`. Written when the world is created; read with the laws, once per script
/// revision (docs/WORLD_RULES.md, "A world's own laws").
#[spacetimedb::table(accessor = world_law)]
pub struct WorldLaw {
    #[primary_key]
    pub name: String,
    /// The value as JSON: a number, or true or false.
    pub value: String,
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

/// The generated land a `map.kind = "land"` world is built from (one row, id 0; absent for
/// other map kinds). A client regenerates the same `living_rules::land::Land` from `seed`,
/// `size` and `params` for ground height, water and roads, and checks it against the digests
/// (`living_rules::host::digests`) before trusting it. The tiles in `terrain_chunk` stay the
/// truth for walking. Written once, at world creation.
#[derive(Clone)]
#[spacetimedb::table(accessor = land, public)]
pub struct LandInfo {
    #[primary_key]
    pub id: u8,
    pub seed: u64,
    /// Side in metres (= tiles).
    pub size: u32,
    /// The seed's partial `LandParams` override, as JSON (`{}` for the defaults).
    pub params: String,
    pub tiles_digest: u64,
    pub heights_digest: u64,
    pub layout_digest: u64,
    /// Where newcomers arrive: on the first town's square (`living_rules::host::arrival`).
    pub arrive_x: f32,
    pub arrive_y: f32,
}

/// A settlement of a land world (one row per `Land::settlements` entry, same index). Static
/// after world creation.
#[spacetimedb::table(accessor = settlement, public)]
pub struct Settlement {
    #[primary_key]
    pub id: u16,
    /// `town`, `village`, `giants`, `small_folk`.
    pub kind: String,
    /// The `buildings.py` style its models come from.
    pub style: String,
    pub x: f32,
    pub y: f32,
    pub radius_m: f32,
    /// Its folk's height relative to a 1.75 m adult (the rules do not size bodies yet).
    pub scale: f32,
    /// The community its residents belong to (0: none seeded).
    pub community: u32,
}

/// A building lot of a land world (one row per `Land::lots` entry, same index): what stands
/// there and the authority entity at its door. Buildings block movement through `Wall` tiles
/// under their footprint (`living_rules::host::footprint_tiles`). Static after world creation
/// except through its structure.
#[spacetimedb::table(accessor = lot, public)]
pub struct Lot {
    #[primary_key]
    pub id: u32,
    pub settlement: u16,
    /// `living_rules::settle::LotKind::id()`.
    pub kind: String,
    pub x: f32,
    pub y: f32,
    pub width_m: f32,
    pub depth_m: f32,
    /// `Quat::from_rotation_y(yaw)` turns a model's front to the street (game x = x, z = y).
    pub yaw: f32,
    pub floor_m: f32,
    pub height_m: f32,
    /// The model's file under the client's `envs/` ("" for gardens and fields).
    pub model: String,
    pub door_x: f32,
    pub door_y: f32,
    /// The structure at its door (a house, inn, hall, workshop or storage; 0 for none).
    pub structure: u64,
    #[index(btree)]
    pub chunk: u32,
}

#[cfg_attr(open_tables, spacetimedb::table(accessor = character, public))]
#[cfg_attr(not(open_tables), spacetimedb::table(accessor = character))]
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
    #[index(btree)]
    pub parent_a: u32,
    #[default(0u32)]
    #[index(btree)]
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
#[cfg_attr(open_tables, spacetimedb::table(accessor = body, public))]
#[cfg_attr(not(open_tables), spacetimedb::table(accessor = body))]
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

/// A walk's route over areas, kept between its legs (`living_rules::nav::Walk`, as one list):
/// one row per body walking to a place (private; written when a leg is planned, deleted when
/// the walk ends or another goal starts). A table of its own because a column added to
/// `steer` would need a constant default, which a list cannot have in 2.14.1.
#[derive(Clone, Debug)]
#[spacetimedb::table(accessor = walk_route)]
pub struct WalkRoute {
    #[primary_key]
    pub id: u32,
    pub route: Vec<u32>,
}

/// Needs anchored at `at_ms` with per-minute rates.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(open_tables, spacetimedb::table(accessor = vitals, public))]
#[cfg_attr(not(open_tables), spacetimedb::table(accessor = vitals))]
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
#[spacetimedb::table(accessor = activity)]
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
#[cfg_attr(open_tables, spacetimedb::table(accessor = inventory, public,
    index(accessor = by_owner_item, btree(columns = [owner, item]))))]
#[cfg_attr(not(open_tables), spacetimedb::table(accessor = inventory,
    index(accessor = by_owner_item, btree(columns = [owner, item]))))]
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

#[derive(Clone)]
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

#[derive(Clone)]
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

/// When a creature's remains (a `remains` structure) are gone: `due_ms` is its `built_ms` plus
/// the `remains_s` law for the dead one's kind. Private; housekeeping reads only the rows due.
#[spacetimedb::table(accessor = rot)]
pub struct Rot {
    #[primary_key]
    pub structure: u64,
    #[index(btree)]
    pub due_ms: u64,
}

/// Installed behavior graph (cold).
#[spacetimedb::table(accessor = brain)]
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
#[spacetimedb::table(accessor = mind_state)]
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
    /// When someone last greeted this character with a gesture made at it (a skill whose
    /// effects `hail`), and who (`hailed`, `hailer` in graphs).
    #[default(0u64)]
    pub hailed_ms: u64,
    #[default(0u32)]
    pub hailer: u32,
}

/// Immediate re-evaluation requests (consumed by the next tick).
#[spacetimedb::table(accessor = wake)]
pub struct Wake {
    #[primary_key]
    pub id: u32,
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub enum InfantNeed {
    Hungry,
    Starving,
    Cold,
    Hurt,
    BadlyWounded,
    BarelyAlive,
    Unsettled,
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub struct CryPrompt {
    pub carer: u32,
    pub at_ms: u64,
}

/// Signal and prompt cadence, bounded to the current episode and nearby carers.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = infant_cry)]
pub struct InfantCry {
    #[primary_key]
    pub infant: u32,
    pub needs: Vec<InfantNeed>,
    pub heard_ms: u64,
    pub prompted: Vec<CryPrompt>,
}

/// What reached a character's senses (sights, speech, what happened to them, their own
/// results). Game state, not knowledge: written only by the authority, never edited, kept
/// in a bounded per-character window. Minds read it and record how far they consolidated.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(open_tables, spacetimedb::table(accessor = experience, public))]
#[cfg_attr(not(open_tables), spacetimedb::table(accessor = experience))]
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
#[cfg_attr(open_tables, spacetimedb::table(accessor = know_how, public,
    index(accessor = by_actor_technique, btree(columns = [actor, technique]))))]
#[cfg_attr(not(open_tables), spacetimedb::table(accessor = know_how,
    index(accessor = by_actor_technique, btree(columns = [actor, technique]))))]
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
#[spacetimedb::table(accessor = artifact)]
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
#[spacetimedb::table(accessor = mind_cursor)]
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

#[spacetimedb::table(accessor = persona)]
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

#[spacetimedb::table(accessor = relation,
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

#[spacetimedb::table(accessor = belief)]
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

/// Typed judgments a character's mind refreshes in the background (Jev; docs/MIND_HARNESS.md,
/// item 4), read by the graph's `judged` condition: never waited on, private to the module.
/// At most `JUDGED_PER_ACTOR` per character; an expired one reads as absent.
#[spacetimedb::table(accessor = judged)]
pub struct Judged {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub q: String,
    /// The yes probability, or a score's expected level, or the chosen option's probability.
    pub value: f32,
    /// The chosen option of a choice (empty otherwise).
    pub choice: String,
    pub expires_ms: u64,
    pub updated_ms: u64,
}

pub const JUDGED_PER_ACTOR: usize = 8;

#[spacetimedb::table(accessor = judgment)]
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

#[cfg_attr(open_tables, spacetimedb::table(accessor = place, public))]
#[cfg_attr(not(open_tables), spacetimedb::table(accessor = place))]
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

#[spacetimedb::table(accessor = thought)]
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

#[spacetimedb::table(accessor = chronicle)]
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
#[spacetimedb::table(accessor = stats)]
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
#[spacetimedb::table(accessor = bond_offer)]
pub struct BondOffer {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub from: u32,
    #[index(btree)]
    pub to: u32,
    pub at_ms: u64,
}

/// A community: a named group with a home, founded and joined by consent. A social fact,
/// not an assigned role: what it means is up to its members.
#[spacetimedb::table(accessor = community)]
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

#[spacetimedb::table(accessor = membership)]
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
#[spacetimedb::table(accessor = join_request)]
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
#[spacetimedb::table(accessor = trade_offer)]
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
#[spacetimedb::table(accessor = expecting)]
pub struct Expecting {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub a: u32,
    pub b: u32,
    #[index(btree)]
    pub due_ms: u64,
}

/// Parents raising a recent birth: no new conception until `until_ms`.
#[spacetimedb::table(accessor = rearing)]
pub struct Rearing {
    #[primary_key]
    pub id: u32,
    pub until_ms: u64,
}

/// Deliberate acts a controller decided on (a mind's deliberation or conversation turn, a
/// player's command) waiting for the body: one `do` node each, carried out once, in order,
/// one at a time, outside the behavior graph (see `acts.rs`). Private: only the authority
/// reads it; the outcome reaches the actor as an experience.
#[spacetimedb::table(accessor = act_queue)]
pub struct PlannedAct {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    /// The act as a canonical `do` node (JSON).
    pub node: String,
    /// Where it was decided ("deliberate", "talk", "human").
    pub source: String,
    pub at_ms: u64,
}

/// Inborn genes (JSON: name → value; see `living_rules::genes`) and, for the young, the ways
/// of life they grow into (a top level from a parent, varied). Written once at birth.
#[spacetimedb::table(accessor = genome)]
pub struct Genome {
    #[primary_key]
    pub id: u32,
    pub genes: String,
    pub ways: String,
}

/// Successful uses of a skill (practice makes one better at it).
#[spacetimedb::table(accessor = practice,
    index(accessor = by_actor_skill, btree(columns = [actor, skill])))]
pub struct Practice {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub skill: String,
    pub uses: u32,
}

/// Grass left to graze in a map chunk: grazing eats it, it regrows outside winter
/// (a herd's carrying capacity). Rows appear when a chunk is first grazed.
#[spacetimedb::table(accessor = pasture)]
pub struct Pasture {
    #[primary_key]
    pub chunk: u32,
    pub amount: f32,
    pub max: f32,
    /// Regrowth per minute of growing time.
    pub regen: f32,
    pub at_ms: u64,
}

// ---- combat (docs/COMBAT.md) ---------------------------------------------------

/// Each combat skill as the rules state it (one row per skill with a `<skill>_combat()` in the
/// script), rewritten whenever a skill script is installed, so clients show the bar, costs,
/// cooldowns and aim, and name the codes in `fighter.act` and `combat_seen.skill`, without
/// running the rules (public, static).
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = skill_card, public)]
pub struct SkillCard {
    #[primary_key]
    pub skill: String,
    /// Place on the bar (the rules' `skill_bar()` order); 255 (`combat::NOT_ON_BAR`) for a
    /// skill that is not on it.
    pub slot: u8,
    /// Energy it takes; its windup, recovery and cooldown (ms); how far it reaches or flies.
    pub cost: f32,
    pub windup_ms: u32,
    pub recover_ms: u32,
    pub cooldown_ms: u32,
    pub reach: f32,
    /// Its presentation code (`fighter.act`, `combat_seen.skill`; `Shapes::code`).
    #[default(0)]
    pub code: u8,
    /// How a player aims it: creature, self_or_ally, point (a skillshot), facing (a held
    /// guard) or dash.
    #[default("")]
    pub aim: String,
    /// A skillshot's missile radius; a guard's arc either side of where it faces (degrees).
    #[default(0.0)]
    pub radius: f32,
    #[default(0.0)]
    pub arc: f32,
    /// What the bar shows as missing before the rules are asked, comma-separated: items to
    /// carry, techniques to know (the skill's check stays the rule). Plain strings, because a
    /// column added to a live table needs a constant default.
    #[default("")]
    pub needs: String,
    #[default("")]
    pub knows: String,
}

/// What others can see of a character in a fight: the health band at a glance and the move
/// under way, with its timing. Written when a move starts, releases or ends and when the band
/// changes; clients receive it through their body window (a join on `body.id`). It holds
/// what anyone looking at the body would see, nothing more (no exact health, no cooldowns).
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(open_tables, spacetimedb::table(accessor = fighter, public))]
#[cfg_attr(not(open_tables), spacetimedb::table(accessor = fighter))]
pub struct Fighter {
    #[primary_key]
    pub id: u32,
    /// `living_rules::combat::band`: 4 unhurt … 0 barely standing.
    pub band: u8,
    /// The move under way (its `skill_card.code`), 0 for none.
    pub act: u8,
    /// When it started, when its windup releases, and when its recovery (or a held guard)
    /// ends (authority ms).
    pub act_ms: u64,
    pub release_ms: u64,
    pub until_ms: u64,
    /// Whom it is aimed at (0 for a point or nobody), and the direction it faces (unit).
    pub target: u32,
    pub aim_x: f32,
    pub aim_y: f32,
}

/// What one human player's character perceived of a fight, for that player only (private;
/// delivered through the per-sender `my_combat` view). Rows are transient: each expires a
/// few seconds after it happened (`expires_ms`), so the table holds only what is current.
/// Minds perceive fights through `experience`, as before.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = combat_seen)]
pub struct CombatSeen {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub viewer: Identity,
    #[index(btree)]
    pub expires_ms: u64,
    pub at_ms: u64,
    /// `living_rules::combat::seen`.
    pub kind: u8,
    pub actor: u32,
    pub target: u32,
    /// The skill (its `skill_card.code`; 0 for none).
    pub skill: u8,
    pub x: f32,
    pub y: f32,
    pub dx: f32,
    pub dy: f32,
    /// Damage or healing, filled only for the two involved; a missile's speed.
    pub amount: f32,
    /// A missile's longest flight, a windup (ms).
    pub ms: u32,
    /// Why an attempt was refused (for the actor only).
    pub note: String,
}

/// A missile in flight (private: clients draw it from its `LAUNCH` and `IMPACT` events).
/// Swept along its path every tick (`next_ms`) against bodies and walls.
#[derive(Clone, Debug)]
#[spacetimedb::table(accessor = missile)]
pub struct Missile {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub owner: u32,
    pub skill: String,
    /// Where it was at `t_ms`, its direction (unit), speed (tiles/s), the distance it may
    /// still fly, its radius.
    pub x: f32,
    pub y: f32,
    pub t_ms: u64,
    pub dx: f32,
    pub dy: f32,
    pub speed: f32,
    pub left: f32,
    pub radius: f32,
    #[index(btree)]
    pub next_ms: u64,
    /// The `skill_use` it belongs to.
    pub use_id: u64,
}

/// One use of a combat skill, from the intention to what actually happened (private; kept
/// for the last [`crate::combat::USES_KEPT`] uses per character). `accepted_ms` is 0 for an
/// attempt the rules refused, with `outcome` saying why.
#[derive(Clone, Debug)]
#[spacetimedb::table(accessor = skill_use)]
pub struct SkillUse {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub skill: String,
    /// Who decided it: `player` (a person's input), `graph` (a behavior graph), `act`.
    pub source: String,
    pub at_ms: u64,
    /// What it was aimed at: a creature (0 for none) and/or a point.
    pub target: u32,
    pub aim_x: f32,
    pub aim_y: f32,
    pub accepted_ms: u64,
    pub released_ms: u64,
    pub outcome: String,
    pub outcome_ms: u64,
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub struct Ready {
    pub skill: String,
    /// When its cooldown started and ends (authority ms).
    pub from_ms: u64,
    pub at_ms: u64,
}

/// A character's combat timing (private; the controller reads its own through the
/// `my_readiness` view): cooldowns per skill, the recovery after the last release, and a
/// movement a player asked for while rooted, applied once the move ends.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = readiness)]
pub struct Readiness {
    #[primary_key]
    pub id: u32,
    pub ready: Vec<Ready>,
    pub busy_until: u64,
    pub move_pending: bool,
    pub move_dx: f32,
    pub move_dy: f32,
    pub move_run: bool,
}

// ---- town life (docs/TOWN_LIFE.md) ------------------------------------------------

/// The world's weather (one row, id 0): whether it is raining, since when and until when the
/// current spell lasts. Drawn per spell from the world's seed and its climate (`weather` in the
/// seed: `spell_s`, `rain_share`; a seed without one never rains),
/// or set for a while by an admin scene (`set_weather`). Written by housekeeping only when it
/// changes; clients draw the sky from it.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = weather, public)]
pub struct Weather {
    #[primary_key]
    pub id: u8,
    pub raining: bool,
    pub since_ms: u64,
    pub until_ms: u64,
    /// An admin scene holds the weather until this time (0: the seed's own weather).
    pub forced_until_ms: u64,
}

/// The presentation code each skill was given, per code space (`codes.rs`): kept across
/// script installs and never reused, so `fighter.act`, `combat_seen.skill` and `doing.code`
/// name the same skill before and after an install (private; clients read codes from
/// `skill_card` and `act_card`).
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = skill_code)]
pub struct SkillCode {
    /// `<space>:<skill>`, e.g. `combat:strike`, `shown:wave`.
    #[primary_key]
    pub key: String,
    pub code: u8,
}

/// Each skill the rules say others can see (`<skill>_shows()` in the script), rewritten
/// whenever a skill script is installed, so clients name the codes in `doing` and know how
/// an unfamiliar skill looks (public, static).
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = act_card, public)]
pub struct ActCard {
    #[primary_key]
    pub skill: String,
    /// Its presentation code (`doing.code`; `living_rules::social::Shows::code`).
    pub code: u8,
    /// How it looks: gesture, turn, step, play, work, eat, sleep, rest.
    pub look: String,
    /// The body turns to face its target when it starts.
    pub faces: bool,
    /// It is a pace to the side, out of someone's way.
    pub aside: bool,
}

/// What a character is visibly doing right now, for a skill with an `act_card`: written when
/// it starts being performed, deleted when it ends. Clients receive it through their body
/// window (a join on `body.id`), like `fighter`. It holds what anyone looking would see.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(open_tables, spacetimedb::table(accessor = doing, public))]
#[cfg_attr(not(open_tables), spacetimedb::table(accessor = doing))]
pub struct Doing {
    #[primary_key]
    pub id: u32,
    /// Its `act_card.code`.
    pub code: u8,
    /// Whom it is aimed at (0 for nobody), and where its target is (a bush, a hearth, a person).
    pub target: u32,
    pub x: f32,
    pub y: f32,
    pub since_ms: u64,
    pub until_ms: u64,
    /// A rest taken at home: indoors, out of sight of the street.
    #[default(false)]
    pub indoors: bool,
}

// ---- perception (docs/PERCEPTION.md) -------------------------------------------------

/// Who a human player's character perceives right now (private): one row per creature in its
/// sight with a clear sight line, kept by the perception sweep (`perception.rs`, every 200 ms
/// per player) and read by the `seen_*` views through the indexed `viewer`. Rows are written
/// only when a creature comes into or goes out of sight, and go when the character dies.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = perceived)]
pub struct Perceived {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub viewer: Identity,
    pub body: u32,
    pub since_ms: u64,
}

/// What a human player perceives of each creature in its scene, its own character included
/// (private): the `perceived_of` law's projection of the creature's record for this viewer.
/// The perception sweep writes a row when a creature comes into sight and rewrites it only
/// when the projection changes (whom the viewer knows, a reveal, a health band); it goes with
/// the creature's `perceived` row. Kept apart from `perceived` so a projection change re-runs
/// only the views that show it (`seen_characters`, `seen_fighters`), not `seen_bodies`.
///
/// Frames (`frame.rs`): for others than the viewer's own character, the band and exact health
/// are written at the viewer's frames (at most every `frame::BAND_MS`), not at each blow, so
/// `seen_characters` re-runs at most that often however busy the fight. The viewer's own row
/// follows at once.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = projected, index(accessor = by_viewer_body, btree(columns = [viewer, body])))]
pub struct Projected {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub viewer: Identity,
    #[index(btree)]
    pub body: u32,
    /// The viewer's own character.
    pub own: bool,
    /// Its name when the viewer knows it, else empty.
    pub name: String,
    /// How the viewer refers to it: the name when known, else `a stranger`, `a child`, `a wolf`.
    pub label: String,
    pub kind: String,
    pub stage: u8,
    /// Its build and dress, from the settlement it lives in (`giants`, `small_folk` or empty;
    /// the settlement's style), as anyone looking would see.
    pub folk: String,
    pub style: String,
    /// `living_rules::combat::band` (4 unhurt … 0 barely standing), 255 when not perceived.
    pub band: u8,
    /// Exact health when the law grants it (oneself, or revealed), else -1.
    pub hp: f32,
    pub max_hp: f32,
}

/// What a player's client was last shown of a perceived creature's `fighter` row (private;
/// frames, `frame.rs`): its move columns as they are, its band as this viewer perceives it
/// (the projection's; 255 when not perceived). One row per creature in the player's scene that
/// has a fighter row, keyed like `motion_seen`, written when it comes into sight and at the
/// viewer's frames when its move or health changed. `seen_fighters` reads these rather than
/// `fighter`, so a move re-runs no one's view until their frame.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = fighter_seen)]
pub struct FighterSeen {
    #[primary_key]
    pub id: u64,
    #[index(btree)]
    pub viewer: Identity,
    pub fighter: Fighter,
}

/// A person's current character (private): the one they play, or the one that died last until
/// they join again. Written at `join` and when the world's minds hand a character back
/// (`presence`). The views and the player reducers read this one row instead of every
/// character the identity ever controlled (`character.controller`), which grows with each
/// death and rejoin.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = player)]
pub struct Player {
    #[primary_key]
    pub identity: Identity,
    pub character: u32,
}

/// How a perceived creature moves, as its viewer was last shown it (private; frames,
/// `frame.rs`): one row per creature in a player's perceived set, keyed
/// `frame::key(viewer's character, creature)`, written when it comes into sight and then at
/// the viewer's frames when the creature's motion changed; it goes with the `perceived` row.
/// `seen_bodies` reads these rather than `body`, so a body's steering update re-runs no one's
/// view until their frame.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = motion_seen)]
pub struct MotionSeen {
    #[primary_key]
    pub id: u64,
    #[index(btree)]
    pub viewer: Identity,
    pub motion: crate::perception::Motion,
}

/// An experience line of a player's character released to its client (private; frames,
/// `frame.rs`): `id` is the `experience` row's, `line` a copy of it (rows are never edited). A
/// line is staged (`shown` false) when it is written and released at the character's next
/// frame; the newest `frame::LINES_SHOWN` stay released. `my_experience` reads the released ones
/// by `(observer, true)`, one point lookup, so neither a staged line nor any other `experience`
/// write re-runs it, and its read set is one key, not one per line (2.14.1 scans every view's
/// read set when a refreshed view commits).
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = line_seen, index(accessor = by_observer_shown, btree(columns = [observer, shown])))]
pub struct LineSeen {
    #[primary_key]
    pub id: u64,
    pub observer: u32,
    pub shown: bool,
    pub line: Experience,
}

/// What a player's client was last shown of what a perceived creature is visibly doing (private;
/// frames, `frame.rs`): a copy of its `doing` row, keyed like `motion_seen`, written when it comes
/// into sight and at the viewer's frames when the row changed. `seen_doing` reads these rather
/// than one `doing` row per creature in the scene.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = doing_seen)]
pub struct DoingSeen {
    #[primary_key]
    pub id: u64,
    #[index(btree)]
    pub viewer: Identity,
    pub doing: Doing,
}

/// What a skill use revealed to an observer about a target, until `until_ms` (private): the
/// `perceived_of` law sees `what` among the target's `revealed` fields while it holds.
#[spacetimedb::table(accessor = reveal)]
pub struct Reveal {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub observer: u32,
    pub target: u32,
    pub what: String,
    #[index(btree)]
    pub until_ms: u64,
}

/// Whose name a character has learned (private): someone told it their name. Family,
/// community and the people a mind has feelings about are known without a row.
#[spacetimedb::table(accessor = acquaintance, index(accessor = by_pair, btree(columns = [observer, known])))]
pub struct Acquaintance {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub observer: u32,
    pub known: u32,
    pub since_ms: u64,
}

// ---- presence (docs/PLAYER_MEMORY.md) --------------------------------------------------

/// One open client connection (private), kept by the `client_connected` and
/// `client_disconnected` lifecycle reducers. The host runs `client_disconnected` for every
/// connection still recorded when it restarts, so a crash leaves no row behind.
#[spacetimedb::table(accessor = connection)]
pub struct Connection {
    #[primary_key]
    pub id: ConnectionId,
    #[index(btree)]
    pub identity: Identity,
    pub since_ms: u64,
}

/// Whether the person who plays a character is there (private: the database owner reads it;
/// no other client). One row per living character a person plays.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = presence)]
pub struct Presence {
    /// The character.
    #[primary_key]
    pub id: u32,
    /// The person who plays it (its controller while they are in control).
    #[index(btree)]
    pub player: Identity,
    /// The person's open connections now.
    pub connections: u32,
    /// At least one connection is open.
    pub present: bool,
    /// When `present` last changed.
    pub changed_ms: u64,
    /// The world's minds control the character (the person left, `takeover_s` ago or more).
    pub ai: bool,
    /// When control last passed (to the minds, or back to the person).
    pub control_ms: u64,
    /// When the minds take over if no connection opens (u64::MAX: not pending).
    #[index(btree)]
    pub takeover_ms: u64,
    /// The behaviour the minds installed, kept while the person plays (it stays the
    /// character's and is installed again at the next takeover).
    pub ai_graph: String,
    pub ai_plan: String,
}

/// A resident someone engaged, who has had a mind since (private: the database owner reads
/// it; no client does). One row per living resident woken from instinct only
/// (`crate::woken`); a resident never goes back to instinct only.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = woken)]
pub struct Woken {
    #[primary_key]
    pub id: u32,
    /// Its settlement (`settlement.id`; `u16::MAX`: none), for a per-settlement stage cap.
    #[index(btree)]
    pub settlement: u16,
    pub woken_ms: u64,
    /// Who woke it, and with what (`speech`, the skill aimed at it such as `teach`, `hurt`,
    /// `theft`: the `wakes` law's engagement).
    pub by: u32,
    pub why: String,
    /// The last engagement by someone with a mind, and who.
    pub engaged_ms: u64,
    pub engaged_by: u32,
    pub engagements: u32,
    /// How many perceptions its ring had taken in before it woke (`prior.seq` up to this;
    /// the last `woken_ring("slots")` are kept).
    pub prior: u32,
    /// The places it knew before waking (world facts its starting ways go to); its mind's
    /// projection keeps them unless the mind names them itself.
    pub places: Vec<String>,
}

/// What an instinct-only resident perceived, kept for the mind it may get (private). A fixed
/// ring of `woken_ring("slots")` slots per resident (a law, at most 256), updated in place:
/// `key` is the resident's id shifted left 8 bits plus the slot.
#[spacetimedb::table(accessor = prior)]
pub struct Prior {
    #[primary_key]
    pub key: u64,
    #[index(btree)]
    pub resident: u32,
    /// The resident's nth perception (1-based; the newest has the highest).
    pub seq: u32,
    pub at_ms: u64,
    /// As an experience's kind (`speech`, `gesture`, `gift`, `sighted`, …).
    pub kind: String,
    pub subject: u32,
    pub object: u32,
    pub x: f32,
    pub y: f32,
    /// As the resident perceived it (names only where it knew them).
    pub text: String,
    pub salience: f32,
    /// The same perception again within `woken_ring("repeat_s")` is counted here.
    pub times: u16,
}

/// A guest of a household (private; the database owner reads it): `guest` may sleep in the
/// `house` and take from its household's store until `until_ms` (the `host` skill).
#[spacetimedb::table(accessor = guest)]
pub struct Guest {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub guest: u32,
    pub host: u32,
    pub house: u64,
    pub x: f32,
    pub y: f32,
    pub since_ms: u64,
    #[index(btree)]
    pub until_ms: u64,
}

/// How many perceptions a resident's ring has taken in (private; the next slot is
/// `seq % woken_ring("slots")`).
#[spacetimedb::table(accessor = prior_head)]
pub struct PriorHead {
    #[primary_key]
    pub id: u32,
    pub seq: u32,
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
