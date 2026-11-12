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
/// The land's full parameters (the seed's `map.params`, with every name its people use), kept
/// by the authority for minds and records (owner-known, 2026-11-12). The public `land` row
/// carries `living_rules::land::public_params` of them: the same land, no names. One row, id 0.
#[spacetimedb::table(accessor = land_plan)]
pub struct LandPlan {
    #[primary_key]
    pub id: u8,
    pub params: String,
}

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
    /// Facing (head and chest; what facing sight and a guard read) as an offset from the travel
    /// heading, radians at `t_ms`, turning at `face_turn` rad/s for the first `face_turn_s`
    /// seconds, then held (`living_rules::steer::facing`; `common::facing_at`). 0 for a body
    /// with no held look: it faces its heading. Written with the segment, never on its own.
    #[default(0.0f32)]
    pub face_off: f32,
    #[default(0.0f32)]
    pub face_turn: f32,
    #[default(0.0f32)]
    pub face_turn_s: f32,
    /// Running now (docs/STAMINA.md): a run under way with breath, for every controller (a
    /// player's run key, a graph's or a mind's `run`, a flight, a wolf's charge); false walking,
    /// out of breath, standing, or dashing. Written with the motion, so a client draws the gait
    /// the rules move (a run is not inferred from speed: walks differ by world and setting).
    #[default(false)]
    pub running: bool,
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
    /// A held look (`human_face`): held while `look_on`, the direction (radians, the same
    /// angle as `body.heading`) the body faces. It is an input, like the movement direction in
    /// `gx`/`gy`; what the body does with it is its facing, `body.face_*`.
    #[default(false)]
    pub look_on: bool,
    #[default(0.0f32)]
    pub look: f32,
    /// A goal that runs (`FLAG_RUN`): its speed walking (out of breath) and running (m/s).
    #[default(0.0f32)]
    pub pace: f32,
    #[default(0.0f32)]
    pub run_pace: f32,
    /// A movement intent's second distance: the far edge of a band (`GOAL_BAND`, `keep` the
    /// near one), the side a circle goes round (`GOAL_ORBIT`, +1 left as one faces it; `keep`
    /// its radius).
    #[default(0.0f32)]
    pub far: f32,
    /// A goal held to a creature by sight (`FLAG_SIGHT`): when its steering first found it out
    /// of sight (0 while it is in sight); `gx`/`gy` where it was last seen.
    #[default(0u64)]
    pub unseen_ms: u64,
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
    /// Breath (`stamina`) and focus: each its level at `at_ms`, its cap (tiredness caps breath),
    /// its signed rate per real second, and when that rate starts (`*_from_ms`, never before
    /// `at_ms`): negative from `at_ms` while a run or a held guard drains it, the refill from the
    /// last spend plus the pool's delay otherwise (`living_rules::pools::level`). Written when a
    /// drain starts or stops and when something is spent, never per tick: a reader projects
    /// `value + rate * (now - max(at_ms, from_ms)) / 1000` within 0..cap.
    #[default(100.0f32)]
    pub stamina: f32,
    #[default(100.0f32)]
    pub stamina_max: f32,
    #[default(0.0f32)]
    pub stamina_rate: f32,
    #[default(0u64)]
    pub stamina_from_ms: u64,
    #[default(100.0f32)]
    pub focus: f32,
    #[default(100.0f32)]
    pub focus_max: f32,
    #[default(0.0f32)]
    pub focus_rate: f32,
    #[default(0u64)]
    pub focus_from_ms: u64,
}

impl Vitals {
    /// The row's columns (a world's `meters()` may name any of them). A column added to this
    /// table is added here and in [`Vitals::fields`], and nowhere else: the rules read the body
    /// by field name (`living_rules::script::BodyFacts`).
    pub const FIELDS: [&'static str; 20] = [
        "id", "hp", "max_hp", "hunger", "energy", "at_ms", "hp_rate", "hunger_rate", "energy_rate", "rate_key", "hurt_ms", "hurt_by",
        "stamina", "stamina_max", "stamina_rate", "stamina_from_ms", "focus", "focus_max", "focus_rate", "focus_from_ms",
    ];

    /// The row's numeric fields by name, in [`Vitals::FIELDS`]'s order.
    pub fn fields(&self) -> Vec<(String, f64)> {
        let v = [
            self.id as f64, self.hp as f64, self.max_hp as f64, self.hunger as f64, self.energy as f64, self.at_ms as f64, self.hp_rate as f64, self.hunger_rate as f64, self.energy_rate as f64, self.rate_key as f64, self.hurt_ms as f64, self.hurt_by as f64,
            self.stamina as f64, self.stamina_max as f64, self.stamina_rate as f64, self.stamina_from_ms as f64, self.focus as f64, self.focus_max as f64, self.focus_rate as f64, self.focus_from_ms as f64,
        ];
        Self::FIELDS.iter().zip(v).map(|(k, v)| (k.to_string(), v)).collect()
    }
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
    /// An answer (accept, decline): the trade offer or the record it names (0: none, the rules
    /// take what stands). Added at the end with defaults, so the table migrates in place.
    #[default(0u64)]
    pub offer: u64,
    #[default(0u64)]
    pub record: u64,
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
    /// A spot that draws on another node's stock (a fishing ground's shared limit): the id of
    /// the node holding it, whose amount, max and regrowth count for both (0: its own).
    #[default(0u64)]
    pub pool: u64,
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
    /// A fire that burns fuel (its kind `burns`): the moment its fuel runs out at its kind's
    /// rate. Lit while this is in the future; the fuel left is the time left times the rate
    /// (living_rules::fire). Written only when it is fed or drawn on. 0: out, or not such a fire.
    #[default(0u64)]
    pub lit_until_ms: u64,
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

/// One person who heard a line: how far from the speaker, and how far off the speaker's
/// facing they stood (radians, 0 = straight ahead, up to pi = behind).
#[derive(SpacetimeType, Clone, Copy, Debug, PartialEq)]
pub struct Hearer {
    pub id: u32,
    pub d: f32,
    pub off: f32,
}

/// Who heard a line and how they stood toward the speaker. Written by `speak` only when the
/// world's `speech_audience` law is on (on by default since 2026-11-11), one row per line, deleted after 60 s.
/// Private: the mind service reads it as the database owner to tell, for a line said to no
/// one in particular, which hearer was nearest or faced (talk.rs, `LIVING_GREET`).
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(open_tables, spacetimedb::table(accessor = audience, public))]
#[cfg_attr(not(open_tables), spacetimedb::table(accessor = audience))]
pub struct Audience {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub speaker: u32,
    pub to: u32,
    #[index(btree)]
    pub at_ms: u64,
    pub hearers: Vec<Hearer>,
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

/// Who heard a line (docs/COMMUNICATION.md §6; `heard` is fov-1's heard-not-seen sounds): for each line a speaker said (its own `said`
/// experience row, `line`), the people who received the words and whom the speaker perceived
/// at that moment (in its sight, by the sight rule). Private: the speaker's person reads its
/// own through `my_heard`, the mind service as the owner. Written in the same transaction as
/// the `said` row, and gone with it (the window's trim, consolidation, death), so a speaker
/// keeps at most its window's own lines. A separate table, not a column on `experience`:
/// `line_seen.line` embeds `Experience`, and automatic migration cannot change that type.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = line_heard)]
pub struct LineHeard {
    /// The speaker's `said` experience id.
    #[primary_key]
    pub line: u64,
    #[index(btree)]
    pub speaker: u32,
    /// The way it was said (`say`, …).
    pub way: String,
    /// Those who received the words and whom the speaker saw, nearest first.
    pub hearers: Vec<u32>,
    pub at_ms: u64,
}

/// Each way of speaking as the rules state it (one row per `<way>_speech()` in the script),
/// rewritten whenever a skill script is installed, so a client builds its talk box (the chips,
/// what each needs) without running the rules (public, static, like `skill_card`). The
/// client's greying is a hint; the authority decides.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = speech_card, public)]
pub struct SpeechCard {
    #[primary_key]
    pub name: String,
    pub label: String,
    /// Where it comes among the ways (chip order, smallest first).
    pub order: i32,
    /// What it is (for the box's hint).
    pub about: String,
    /// A line needs someone to be said to (`to` != 0).
    pub needs_to: bool,
    /// The addressee must be within this many metres (0: wherever the words carry).
    pub reach_m: f32,
    /// How far the words go for a person with the world's ordinary hearing (metres).
    pub carry_m: f32,
    /// A technique the speaker must know ("" none), as in `my_know_how`.
    pub requires: String,
    /// The addressee must be in the speaker's sight.
    pub needs_sight: bool,
    /// Only the addressee receives the words.
    pub private: bool,
    /// Longest line (characters; longer is cut).
    pub max_chars: u16,
    /// Shortest time between two lines of this way (ms).
    pub gap_ms: u32,
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
    /// When each line of `reason` arrived, in milliseconds separated by spaces and aligned with
    /// its lines: a deliberation consumes the lines its prompt contained (living_rules::reasons).
    /// A string because a column default must be a constant.
    #[default("")]
    pub arrived: String,
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
    /// What they enjoy doing for its own sake (pastimes), and the work they love or long for
    /// (`calling`): wants beyond getting by (docs/SEEDED_LIVES.md, "Wants beyond survival").
    pub pastimes: Vec<String>,
    pub calling: String,
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

/// What a mind wrote should bring it to think (docs/ATTENTION.md): one attention cue, tied to
/// the stance, project or goal it serves (`for_key`), matched by type against what its
/// character perceives (`brain.rs` `cues`). Private: written only by `mind_update` (the
/// projection of the mind's memory, which replaces the set) and read once a second per
/// character with cues while the `cues_on` law holds. At most `CUES_PER_ACTOR` per character.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = cue)]
pub struct Cue {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    /// `stance:<key>`, `project:<key>` or `goal:<key>`.
    pub for_key: String,
    /// The mind's own words for why it watches (quoted in the line a match gives).
    pub why: String,
    /// A person or creature by id (0: any).
    pub who_id: u32,
    /// `unknown` (a person whose name one does not know), a creature kind, or empty.
    pub who: String,
    /// What the matched creature is visibly doing (`perception::visibly`: a skill's name, its
    /// label, or a kind word such as `melee`), or empty.
    pub doing: String,
    /// The phase it is visibly in (`living_rules::doing::Phase`'s words), or empty.
    pub phase: String,
    /// A resource or structure kind, or empty.
    pub thing: String,
    /// One of the actor's own places the match must be within `within` metres of, or empty.
    pub at: String,
    pub within: f32,
    /// The match must be within this many metres of the actor (0: anywhere in sight).
    pub near_me: f32,
    /// Why the authority does not watch for it (empty: it is watched).
    pub refused: String,
    /// The things it fired on lately (at most `CUE_FIRED`) and when.
    pub fired: Vec<CueFire>,
    pub fires: u32,
    pub set_ms: u64,
    /// The mind's thought that wrote it (its journal reference), for the inspector.
    pub source: String,
}

#[derive(SpacetimeType, Clone, Copy, Debug, PartialEq)]
pub struct CueFire {
    /// A creature id, or `CUE_RESOURCE | id`, `CUE_STRUCTURE | id` or `CUE_PLACE | id`.
    pub subject: u64,
    pub at_ms: u64,
}

pub const CUES_PER_ACTOR: usize = 8;
pub const CUE_FIRED: usize = 8;
pub const CUE_RESOURCE: u64 = 1 << 62;
pub const CUE_STRUCTURE: u64 = 1 << 61;
pub const CUE_PLACE: u64 = 1 << 60;

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
    /// A world fact rather than a mind's: written at world creation (work, square, inn,
    /// evening spot, the stages of a known way) or by a rule (a guest's lodging). Starting
    /// ways walk to it, so a mind's projection never drops it; the mind may move it by naming it.
    pub given: bool,
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

/// A standing trade proposal: `from` gives `give_qty` `give_item` to `to` for `want_qty`
/// `want_item`. It can be accepted until `until_ms` (`at_ms` plus the `trade_window_s` law
/// when it was made); 0 on rows made before the column, which use the law's window.
/// Indexed by `to` for `my_offers` (a point read per player) and the addressee's mind.
#[spacetimedb::table(accessor = trade_offer)]
pub struct TradeOffer {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub from: u32,
    #[index(btree)]
    pub to: u32,
    pub give_item: String,
    pub give_qty: u32,
    pub want_item: String,
    pub want_qty: u32,
    pub at_ms: u64,
    #[default(0u64)]
    pub until_ms: u64,
}

impl TradeOffer {
    /// When the offer can no longer be accepted (the stored end, or for an older row the
    /// law's window from when it was made).
    pub fn ends_ms(&self, window_s: f32) -> u64 {
        if self.until_ms != 0 {
            self.until_ms
        } else {
            self.at_ms + (window_s * 1000.0) as u64
        }
    }
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
    /// The pool `cost` is taken from (`combat_pool`): "stamina" or "focus" (`vitals`' columns
    /// of that name), so the bar greys a slot without knowing skill names.
    #[default("stamina")]
    pub pool: String,
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

/// What a player's character senses now (private; its client reads its own through the
/// `my_senses` view): the world's `senses(a)` law for the character with all its facts, so a
/// client draws its sight and hearing from the rules' answer instead of running the law on
/// the few facts it has. Written at the character's frames only when a value changed
/// (`frame::show_senses`): nightfall, dawn, a torch picked up or put away. `field` is whether
/// sight depends on facing (the world's `fov_on` law); its five numbers are 0 while it does
/// not. One row per character a person plays now; it goes when the character dies.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = character_senses)]
pub struct CharacterSenses {
    #[primary_key]
    pub id: u32,
    /// Metres seen and heard (one tile is one metre).
    pub sight: f32,
    pub hearing: f32,
    /// Sight narrows away from facing (`living_rules::sight::Field`).
    pub field: bool,
    pub focal_deg: f32,
    pub side_deg: f32,
    pub side_share: f32,
    pub near_m: f32,
    pub margin_deg: f32,
    /// When a value last changed (authority ms).
    pub at_ms: u64,
}

impl CharacterSenses {
    /// The row for character `id` from the law's answer (`at_ms` 0: stamped when written).
    pub fn of(id: u32, s: &living_rules::script::Senses) -> Self {
        let f = s.field.unwrap_or(living_rules::sight::Field { focal_deg: 0.0, side_deg: 0.0, side_share: 0.0, near_m: 0.0, margin_deg: 0.0 });
        Self { id, sight: s.sight, hearing: s.hearing, field: s.field.is_some(), focal_deg: f.focal_deg, side_deg: f.side_deg, side_share: f.side_share, near_m: f.near_m, margin_deg: f.margin_deg, at_ms: 0 }
    }

    /// The same senses, whenever they were stamped.
    pub fn same(&self, o: &Self) -> bool {
        Self { at_ms: 0, ..self.clone() } == Self { at_ms: 0, ..o.clone() }
    }
}

/// How an act or a death came out, for a person's client (private; read through
/// `my_act_outcomes`): one row per experience line that tells it, keyed by that line's id and
/// written in the same transaction (`outcomes::write`). `kind` picks the vocabulary of `code`
/// (`living_rules::outcome`): `act` (a deliberate act: a player's command or a mind's decision)
/// and `own` (a graph's action, told when it failed) take an act code; `death` (the
/// character's own) a death code, with the killer in `other`. `what` is the act as described,
/// `why` the rules' words for a refusal or a failure (empty when done). Written only for a
/// character a person plays now, and kept as long as its line is in `my_experience` (the newest
/// `frame::LINES_SHOWN`); a person's rows go when they play another character.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = act_outcome)]
pub struct ActOutcome {
    /// The experience line's id.
    #[primary_key]
    pub id: u64,
    #[index(btree)]
    pub observer: u32,
    pub at_ms: u64,
    pub kind: String,
    pub ok: bool,
    pub skill: String,
    pub code: String,
    pub what: String,
    pub why: String,
    pub other: u32,
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

/// What a human player hears but does not see (private; docs/PERCEPTION.md, "Heard, not
/// seen"): one row per creature within the player's hearing and outside its field, written at
/// the perception sweep when one starts to be heard or its bearing or band changes, and gone
/// about `heard_linger_s` after it was last heard (or at once when it comes into sight). Only
/// while the world's `fov_on` law gives the player a field. The `heard_sounds` view returns
/// `key`, `kind`, `bearing` and `band`, never `target`: `key` is derived from the listener,
/// the target and a salt that rotates every few minutes (`hear_salt`), so it cannot be traced to
/// a character, and stays the same while the sound lasts.
#[derive(Clone, Debug, PartialEq)]
#[spacetimedb::table(accessor = heard)]
pub struct Heard {
    #[primary_key]
    pub key: u64,
    #[index(btree)]
    pub viewer: Identity,
    /// The listener's character.
    pub listener: u32,
    /// Who is heard (never sent to the player).
    pub target: u32,
    /// What it sounds like: "person", "deer", "wolf" or "creature" (the `heard_as` law).
    pub kind: String,
    /// One of eight compass ways from the listener, 0 north, clockwise.
    pub bearing: u8,
    /// 0 near, 1 close, 2 far (the `heard_near_m`, `heard_close_m` laws).
    pub band: u8,
    pub since_ms: u64,
}

/// The secret salt behind heard keys (private; one row, drawn from the module's random source
/// at the first sound).
#[spacetimedb::table(accessor = hear_salt)]
pub struct HearSalt {
    #[primary_key]
    pub id: u8,
    pub salt: u64,
}

/// Every change of a world law on a running world (`set_world_law`), kept for good (private;
/// read by the owner, a run's evidence): which law, its value before and after (JSON; before:
/// the value in force then), when, and who asked.
#[spacetimedb::table(accessor = law_change)]
pub struct LawChange {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub name: String,
    pub old: String,
    pub new: String,
    pub at_ms: u64,
    pub by: Identity,
    /// The script revision the change installed (`script.revision`).
    pub revision: u32,
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
    /// The body's facing segment (`body.face_*`), appended beside `motion` (whose type stays
    /// as stored); `seen_bodies` returns both as one `Moving` row.
    #[default(0.0f32)]
    pub face_off: f32,
    #[default(0.0f32)]
    pub face_turn: f32,
    #[default(0.0f32)]
    pub face_turn_s: f32,
    /// `body.running`, appended as the facing was.
    #[default(false)]
    pub running: bool,
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

/// A person's daily rhythm (private; seed content or drawn at birth, docs/SEEDED_LIVES.md):
/// when it rises and goes to bed (hours of the day; `bed_h` may pass 24, e.g. 24.5 is 00:30,
/// and lies 8 to 22 hours after `rise_h`, which may be any hour), how many hours before bed it
/// keeps as its evening, its working hours and a second sleep (spans whose end may pass 24; an
/// end not after its start is none). Graphs read it as `bedtime`, `evening` and `work_hours`
/// (`living_rules::rhythm`); its new day starts at `rise_h`. Without a row: the world's night,
/// and 18–22.
#[spacetimedb::table(accessor = rhythm)]
pub struct Rhythm {
    #[primary_key]
    pub id: u32,
    pub rise_h: f32,
    pub bed_h: f32,
    pub evening_h: f32,
    /// The world day whose new day it last began (`living_rules::day_of`); the day it is
    /// born into counts as begun, so a world's people do not all begin one at its creation.
    pub last_day: u32,
    /// Working hours (none: 0 and 0, so any waking hour outside the evening is work's).
    #[default(0.0f32)]
    pub work_from_h: f32,
    #[default(0.0f32)]
    pub work_to_h: f32,
    /// A second sleep in the day (none: 0 and 0), e.g. a baker's afternoon.
    #[default(0.0f32)]
    pub nap_from_h: f32,
    #[default(0.0f32)]
    pub nap_to_h: f32,
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
