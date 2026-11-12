//! Rhai skill runtime with a typed boundary.
//!
//! Scripts are functions only. For a skill `x` the runtime calls, when defined:
//! `x_check(a) -> ""|reason`, `x_duration(a) -> ms`, `x_done(a) -> [effect maps]`.
//! `rates(a)` returns the need rates for the actor's state as parameters the engine finishes per
//! body ([`NeedLaw`]); `move_speed(a)` tiles/second.
//!
//! The context map `a` is built directly from typed facts (no JSON), with only the fields each
//! law reads ([`fields`], [`context`]), and effects are validated and applied by the authority.
//! What does not change per call is read once when the script compiles: the laws, the combat
//! shapes, and the numbers looked up by a name (`combat_cooldown("strike")`, `lunge("wolf")`).
//! [`Scripts::validate`] runs every function on sample inputs before an install is accepted.

use rhai::packages::Package;
use rhai::{Array, Dynamic, Engine, Map, Scope, AST};
use std::cell::RefCell;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::rc::Rc;

pub mod body;
mod check;
#[cfg(test)]
mod seed_check;
pub mod context;
pub mod fields;
pub mod speech;
mod ui;
pub use ui::UiWork;
pub use check::Report;
pub use body::{Alarm, BodyFacts, Meter, MeterMax, Status, Think};

#[derive(Clone, Debug, Default)]
pub struct ActorFacts {
    pub id: u32,
    pub kind: String,
    pub hp: f32,
    pub hunger: f32,
    pub energy: f32,
    pub near_fire: bool,
    pub near_shelter: bool,
    pub terrain: String,
    pub activity: String,
    pub inv: Vec<(String, u32)>,
    /// Age in in-world days.
    pub age: f32,
    /// Life stage: infant, child, adult or elder.
    pub stage: String,
    /// Fraction of the lifespan lived (0..1).
    pub life: f32,
    /// Techniques this character knows how to do.
    pub knows: Vec<String>,
    /// Inborn genes (see `genes`): body factors, knacks and temperament.
    pub genes: crate::genes::Genes,
    /// Successful uses per skill (practice).
    pub practice: std::collections::BTreeMap<String, u32>,
    /// Others of one's own kind within 4 tiles (filled for actions: crowding).
    pub kin_near: u32,
    /// Grazing left where one stands (filled for actions).
    pub pasture: f32,
    /// Who last hurt the actor, and how long ago (ms; none when never).
    pub hurt_by: u32,
    pub hurt_ago: Option<f32>,
    /// How long ago the actor yielded (ms; none when it has not).
    pub yielded_ago: Option<f32>,
    /// Creatures the actor senses (in sight, or smelled for a species with a scent) by kind;
    /// filled for an animal's attack on a person.
    pub sensed: Vec<(String, u32)>,
    /// A creature bold enough to attack people without the predator's usual fear (a seed's
    /// hostile pack; read from its background for an animal's attack on a person).
    pub bold: bool,
    /// Walkable tiles in the 5x5 square around the actor (25 in the open, fewer in a narrow
    /// street or a doorway); filled for a skill whose `_shows()` steps aside.
    pub room: u32,
    /// The actor's community as a party (`records::COMMUNITY | id`; 0: none).
    pub community: u64,
    /// Where the actor's household lives (`"x,y"`, whole tiles; empty: no home).
    pub home: String,
    /// The actor stands in lamplight: within the `lights` radius of a structure that gives
    /// light (its traits in `structures()`), or within the light of a fire that burns fuel while
    /// it is lit.
    pub lit: bool,
    /// Breath (`stamina`) and the non-bodily pool (`focus`) now, as the `pools(a)` law and the
    /// vitals row give them (docs/STAMINA_PROPOSAL.md).
    pub stamina: f32,
    pub focus: f32,
}

#[derive(Clone, Debug, Default)]
pub struct TargetFacts {
    /// `resource`, `structure`, `creature`, `place` or `none`.
    pub class: String,
    pub id: u64,
    pub kind: String,
    pub name: String,
    pub amount: f32,
    pub hp: f32,
    pub max_hp: f32,
    /// Life stage of a creature target.
    pub stage: String,
    /// Milliseconds since the creature was last hurt (large when never).
    pub hurt_ago: f32,
    pub alive: bool,
    pub dist: f32,
    pub inv: Vec<(String, u32)>,
    pub knows: Vec<String>,
    /// What a creature target is doing (its action under way, e.g. `sleep`).
    pub activity: String,
    /// How long ago a creature target yielded (ms; none when it has not).
    pub yielded_ago: Option<f32>,
    /// Filled for attacks: whether the target is near a fire, and how many other people
    /// (not the target, not the actor) are within the `alone_within` law of it.
    pub near_fire: bool,
    pub company: u32,
    /// For a creature or a place: how far the actor would have to turn to face it (radians,
    /// 0 straight ahead .. pi behind), and how fast a creature is coming toward the actor
    /// (tiles/s; negative when moving away).
    pub bearing: f32,
    pub closing: f32,
    /// A creature's community as a party (`records::COMMUNITY | id`; 0: none).
    pub community: u64,
    /// A structure's owner (0: none).
    pub owner: u32,
    /// The actor is a guest of this creature, or of this structure's owner (`host`).
    pub hosts: bool,
    /// Where a creature's household lives, or a structure's owner's (`"x,y"`; empty: none).
    pub home: String,
    /// A structure that is a fire: whether it burns now (one that needs no feeding always
    /// does), and the fuel a fire that burns fuel still holds (units of its kind's fuel).
    pub lit: bool,
    pub fuel: f32,
}

#[derive(Clone, Debug, Default)]
pub struct SkillCtx {
    pub actor: ActorFacts,
    pub target: TargetFacts,
    pub item: String,
    pub qty: u32,
    /// It is night: the `daylight` law below one half (`Scripts::is_night`).
    pub night: bool,
    /// How dark it is, 0 (full day) to 1 (full night): one minus the `daylight` law, in steps
    /// of 1/20 so that laws kept per state share answers (`a.daylight` in the script).
    pub dark: f32,
    pub hour: f32,
    pub season: String,
    pub text: String,
    pub topic: String,
    /// A fresh random number in [0, 1) from the authority (for chances).
    pub roll: f32,
    /// The skill being performed (empty for rates and speed).
    pub skill: String,
    /// The routine being reworked (rework only).
    pub routine: RoutineFacts,
    /// It is raining (the world's weather).
    pub raining: bool,
    /// What a trade or terms ask in return (`offer`, `offer_terms`).
    pub want: String,
    pub want_qty: u32,
    /// The records the actor is a party to, itself or through its community (filled only for a
    /// law that reads them).
    pub records: Vec<crate::records::RecordFacts>,
    /// The record at hand: the one falling due (`on_expire`).
    pub record: Option<crate::records::RecordFacts>,
    /// What an answer (accept, decline) names: a trade offer's id, a record's id (0: none).
    pub offer_id: u64,
    pub record_id: u64,
    /// The trade offer at hand (filled only for a law that reads it): the one the act names, or,
    /// when that one is gone or none is named, the target's standing offer to the actor.
    pub offer: Option<OfferFacts>,
}

/// A trade offer as the rules see it (`a.offer`): `#{ id, from, to, give, give_qty, want,
/// want_qty, open, left_s }`. `open` is false once it can no longer be accepted.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct OfferFacts {
    pub id: u64,
    pub from: u32,
    pub to: u32,
    pub give: String,
    pub give_qty: u32,
    pub want: String,
    pub want_qty: u32,
    pub open: bool,
    pub left_s: f32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub enum Wound {
    #[default]
    None,
    Hurt,
    BadlyWounded,
    BarelyAlive,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct BodyState {
    pub cold: bool,
    pub hungry: bool,
    pub starving: bool,
    pub wound: Wound,
}

impl BodyState {
    pub fn looks(&self) -> String {
        let mut parts = vec![if self.cold { "cold" } else { "warm" }];
        parts.push(if self.starving { "starving" } else if self.hungry { "hungry" } else { "fed" });
        match self.wound {
            Wound::None => {},
            Wound::Hurt => parts.push("hurt"),
            Wound::BadlyWounded => parts.push("badly wounded"),
            Wound::BarelyAlive => parts.push("barely alive"),
        }
        parts.join(", ")
    }
}

/// How the actor's current version of a routine has gone (for `rework`).
#[derive(Clone, Debug, Default)]
pub struct RoutineFacts {
    pub exists: bool,
    /// Its actions that finished well and that failed, since it was last changed.
    pub ok: u32,
    pub failed: u32,
    /// Seconds since it was last changed.
    pub changed_s: f32,
}

/// What the `perceived_of` law is told about an observer looking at a target. It holds only
/// what the law may decide on, so its value is the cache key for the law's answer.
#[derive(Clone, Debug, Default, PartialEq, Eq, Hash)]
pub struct RegardIn {
    pub observer_kind: String,
    /// Techniques the observer knows how to do (sorted).
    pub knows: Vec<String>,
    pub target_kind: String,
    /// The observer knows the target's name (itself, family, its community, someone it has
    /// feelings about, or someone who told it their name).
    pub known: bool,
    /// Fields a skill use revealed to the observer and that still hold (sorted).
    pub revealed: Vec<String>,
    /// The observer is looking at itself.
    pub own: bool,
    pub night: bool,
    /// How far the target is, in whole metres (rounded up); 0 unless the law reads `p.dist`
    /// (`Scripts::regard_reads_dist`), so the key stays small for a law that does not.
    pub dist: u16,
}

/// How precisely a field is perceived.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub enum Precision {
    None,
    #[default]
    Band,
    Exact,
}

/// The `perceived_of` law's answer: which fields of the target the observer gets.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct Regard {
    /// Its name; otherwise a label (`a stranger`, `a wolf`).
    pub name: bool,
    pub health: Precision,
}

impl Regard {
    /// The rule without a `perceived_of` law: names when known (animals know their own kind's),
    /// health as a band, exactly for oneself or while revealed.
    pub fn default_for(p: &RegardIn) -> Self {
        let name = p.own || p.known || (p.observer_kind != "person" && p.observer_kind == p.target_kind);
        let health = if p.own || p.revealed.iter().any(|r| r == "health") { Precision::Exact } else { Precision::Band };
        Self { name, health }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Effect {
    /// Add items to the actor.
    Add { item: String, qty: u32 },
    /// Remove items from the actor (fails the action if missing).
    Remove { item: String, qty: u32 },
    /// Take units from the target resource.
    Harvest { qty: f32 },
    /// Change the actor's needs.
    Vitals { hp: f32, hunger: f32, energy: f32 },
    /// Spend from one of the actor's short pools (`stamina` or `focus`, the `pools(a)` law):
    /// its refill starts after the pool's delay.
    Spend { pool: String, amount: f32 },
    /// Eat the grass where the actor stands (the chunk's pasture).
    Graze,
    /// Damage the target creature.
    Damage { amount: f32 },
    /// Restore the target creature's health (tending wounds).
    Heal { amount: f32 },
    /// Open or close the target gate (its community decides who may).
    Gate { open: bool },
    /// Move items from the actor to the target creature.
    Give { item: String, qty: u32 },
    /// Move items from the target creature to the actor, against their will.
    Seize { item: String, qty: u32 },
    /// Move items from the actor into the target structure.
    Store { item: String, qty: u32 },
    /// Move items from the target structure to the actor.
    Take { item: String, qty: u32 },
    /// Put items from the actor's pack on the target fire as fuel (each worth its `burns.fuel`
    /// trait in units): an out fire is lit, a lit one burns longer.
    Fuel { item: String, qty: u32 },
    /// Draw `units` of fuel from the target fire (the heat a recipe takes): it burns down sooner.
    Burn { units: f32 },
    /// Replace (or retire) one of the actor's routines, or its top level, with the reworked
    /// version the act carries.
    Rework,
    /// Create a structure at the actor's position.
    Build { kind: String },
    /// Offer (or accept) starting a family with the target person.
    Bond,
    /// Make the species signal named by the action's item.
    Signal,
    /// The actor stops resisting (to the target creature, or whoever last hurt it).
    Yield,
    /// The target person learns a technique from the actor.
    Teach { technique: String },
    /// The actor works out a technique.
    Learn { technique: String },
    /// Create the tablet or sign described by the action.
    Write,
    /// Read the tablet or sign the action resolved.
    Read,
    /// Grow a new berry bush where the actor stands.
    Plant,
    /// Propose a trade to the target.
    Offer,
    /// Accept the target's trade offer to the actor: the one with this id, or (0) the one
    /// standing.
    Accept { offer: u64 },
    /// End the target's trade offer to the actor without a trade: the one with this id, or (0)
    /// the one standing.
    Decline { offer: u64 },
    Found,
    Join,
    Welcome,
    Leave,
    /// The target person becomes the actor's household's guest until the next `until_hour`
    /// of the world's day (a bed in its house, food from its store).
    Host { until_hour: f32 },
    /// Loose the skill's missile (`<skill>_missile(a)`) toward the action's target point.
    Launch,
    /// The target creature is greeted: it sees the gesture made at it (`hailed`, `hailer`).
    Hail,
    /// The actor perceives more of the target creature for `secs` seconds: `what` names the
    /// field the `perceived_of` law then sees as revealed (e.g. `health`).
    Reveal { what: String, secs: f32 },
    /// Make a record: its kind, status, parties by role and terms, falling due after `due_h`
    /// world hours (none: never). The actor must be one of its parties.
    Record { kind: String, status: String, parties: Vec<(String, u64)>, terms: serde_json::Map<String, serde_json::Value>, due_h: Option<f32> },
    /// Change a record the actor is party to (or the one at hand): its status, some of its
    /// terms, when it falls due.
    Amend { id: u64, status: Option<String>, terms: serde_json::Map<String, serde_json::Value>, due_h: Option<f32> },
    /// Close such a record with a status; it is kept `keep_h` world hours more, then dropped.
    Close { id: u64, status: String, keep_h: f32 },
    /// Tell a character something in the rules' words. `{actor}`, `{target}` and `{id:N}` in
    /// the text become how the one told refers to them; `ask` has its mind think about it.
    Tell { to: u64, text: String, salience: f32, ask: bool },
    /// Everyone who can see the actor perceives this (`{a}`: the actor, `{b}`: the target).
    Witness { text: String, salience: f32 },
}

impl Effect {
    /// The effects an event hook (`on_<event>`) may return: records and what is told and seen.
    /// A hook notices and tells; it does not move goods or bodies.
    pub fn of_a_hook(&self) -> bool {
        matches!(self, Effect::Record { .. } | Effect::Amend { .. } | Effect::Close { .. } | Effect::Tell { .. } | Effect::Witness { .. })
    }
}

/// World laws that parameterize the engine. Read once per script revision (the `laws()`
/// function), so they cost nothing per tick; defaults apply to anything a script omits.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Laws {
    pub fire_warmth: f32,
    pub shelter_warmth: f32,
    pub gestation_days: f32,
    pub bond_window_s: f32,
    pub crowd: f32,
    pub danger_near: f32,
    pub danger_far: f32,
    pub repeat_failure_s: f32,
    /// Every blow, shot or bolt a character makes is told to it with how it came out, as far as
    /// it sees (docs/COMBAT_MIND.md §3.1). Off: only notable skills and failures, as before.
    pub force_outcomes: bool,
    /// Walking speed multiplier on road tiles.
    pub road_speed: f32,
    // ---- steering (see `steer.rs`; how each creature turns and keeps apart is its `motion`) ----
    /// Distance from a destination where walkers start slowing down, tiles.
    pub slow_radius: f32,
    /// Distance from a path corner where steering already aims past it, tiles.
    pub corner_radius: f32,
    /// Longest a walker goes without looking again when alone, seconds.
    pub steer_s: f32,
    /// Steering rate among other bodies, while chasing or following, and in a fight (Hz).
    pub crowd_hz: f32,
    pub chase_hz: f32,
    pub combat_hz: f32,
    /// How often a body smells afresh (Hz): between reads it keeps what it last smelled while
    /// it has moved less than a few tiles. Scent is coarse (rough direction, distance to 10
    /// tiles), and a fresh read sweeps every chunk within the scent radius.
    pub scent_hz: f32,
    /// Movement input a player may send per second (sustained) and in a burst.
    pub input_hz: f32,
    pub input_burst: f32,
    /// Grass regrowth per grassy tile per minute of growing time (grazing units): it sets how
    /// many grazers the land feeds.
    pub pasture_regen: f32,
    /// Someone with no other person within this many tiles is alone (for predators' daring).
    pub alone_within: f32,
    /// A body within this angle of facing something already faces it (radians).
    pub face_slack: f32,
    /// A flight ends this many tiles farther from the threat than where it began.
    pub flee_clear: f32,
    /// How long a played character stands without any connection of its person before the
    /// world's minds take it over (seconds; docs/PLAYER_MEMORY.md).
    pub takeover_s: f32,
    /// How long one `follow` lasts before the follower looks again, seconds.
    pub follow_s: f32,
    /// `read` with nothing named reads the nearest sign within this many metres.
    pub read_sign_m: f32,
    /// Others of one's own kind within this many metres count as kin near (`a.actor.kin_near`).
    pub kin_near_m: f32,
    /// A trade offer can be accepted for this many seconds.
    pub trade_window_s: f32,
    /// A request to join a community stands this many seconds.
    pub join_window_s: f32,
    /// Speech to no one in particular is taken as addressed to the only listener within this many metres.
    pub address_m: f32,
    /// A creature already in a player's sight stays seen until this many metres beyond the player's sight.
    pub keep_seen_m: f32,
    /// A chased creature is lost from sight beyond this share of the chaser's sight (or its scent, if farther).
    pub chase_lost_share: f32,
    /// Hunger of a body that comes into the world.
    pub spawn_hunger: f32,
    /// Energy of a body that comes into the world.
    pub spawn_energy: f32,
    /// Grazing each grassy or forest tile holds (grazing units).
    pub pasture_per_tile: f32,
    /// A crying infant makes its carers think about it; false: the cry is only heard.
    pub cry_prompts_carers: bool,
    /// Speech records who heard each line and how they stood toward the speaker (the private
    /// `audience` table), for the mind service's conversation rules (on since 2026-11-11, when
    /// `LIVING_GREET=nearest` became the minds' default).
    pub speech_audience: bool,
    /// A line to someone tells the speaker the truth when they could not have heard it ("Bram
    /// is too far away: they could not have heard you."), and a plan's queued line is not said
    /// into the air: dropped once the conversation has moved past it, and when its addressee is
    /// beyond the way's reach as it comes due, told to the speaker instead (docs/COMMUNICATION.md
    /// §15). Off: `speech-2`'s words ("No answer from …" when the addressee is not seen), and a
    /// queued line is said whenever it comes due.
    pub speech_truth: bool,
    /// Real minutes after one's own birth, or one's youngest child's, before a grown person
    /// feels the longing for a child; the most nurturing feel it sooner ([`longing_wait_ms`]).
    pub longing_after_min: f32,
    /// Food one must carry for that longing to be felt (0: it does not depend on food).
    pub longing_food: f32,
    /// Sight depends on facing (the `field` of `senses(a)`; the geometry is the `fov_*` laws,
    /// read by the script).
    pub fov_on: bool,
    /// A sound heard but not seen is near within this, close within the next (metres), and
    /// lingers this long after it was last heard (seconds).
    pub heard_near_m: f32,
    pub heard_close_m: f32,
    pub heard_linger_s: f32,
    /// A held look (`human_face`): a change within this many degrees is the same look; walking,
    /// the body's facing (not its travel) turns toward the look at most this many degrees off its
    /// way (`steer::walk_face`).
    pub look_slack_deg: f32,
    pub look_walk_deg: f32,
}

/// How long after one's own birth, or one's youngest child's, a grown person waits before
/// longing for a child: `after_min` real minutes, shortened by nurture (0..100) to a sixth of
/// it at most nurturing. With the shipped 20 minutes this is the old `20 - nurture / 6`.
pub fn longing_wait_ms(after_min: f32, nurture: f32) -> f32 {
    60_000.0 * after_min.max(0.0) * (1.0 - nurture.clamp(0.0, 100.0) / 120.0)
}


impl Default for Laws {
    fn default() -> Self {
        Self {
            fire_warmth: 3.5,
            shelter_warmth: 2.5,
            gestation_days: 1.0,
            bond_window_s: 120.0,
            crowd: 6.0,
            danger_near: 8.0,
            danger_far: 12.0,
            repeat_failure_s: 120.0,
            force_outcomes: true,
            road_speed: 1.4,
            slow_radius: 1.2,
            corner_radius: 0.9,
            steer_s: 2.0,
            crowd_hz: 3.0,
            chase_hz: 4.0,
            combat_hz: 8.0,
            scent_hz: 1.0,
            input_hz: 30.0,
            input_burst: 15.0,
            pasture_regen: 0.006,
            alone_within: 6.0,
            face_slack: 0.35,
            flee_clear: 9.0,
            takeover_s: 30.0,
            follow_s: 12.0,
            read_sign_m: 8.0,
            kin_near_m: 4.0,
            trade_window_s: 180.0,
            join_window_s: 300.0,
            address_m: 6.0,
            keep_seen_m: 1.0,
            chase_lost_share: 1.4,
            spawn_hunger: 25.0,
            spawn_energy: 85.0,
            pasture_per_tile: 0.02,
            cry_prompts_carers: true,
            speech_audience: true,
            speech_truth: true,
            longing_after_min: 20.0,
            longing_food: 0.0,
            fov_on: false,
            heard_near_m: 5.0,
            heard_close_m: 15.0,
            heard_linger_s: 2.0,
            look_slack_deg: 10.0,
            look_walk_deg: 75.0,
        }
    }
}

/// What a creature senses now (`senses(a)`): how far it sees and hears, and how its view
/// narrows away from facing (the one sight rule, [`crate::sight`]).
pub use crate::sight::{Field, Senses};

/// The farthest anyone's senses reach (`reach` in `senses_law()`): by day and by night, and
/// hearing; and `glow`, the farthest anyone is seen by a light on them (the `glow` law; 0 when
/// the script has none). The engine gathers onlookers and listeners within these before testing
/// each one's own senses, and holds every answer of the laws to them.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Reach {
    pub day: f32,
    pub night: f32,
    pub hearing: f32,
    pub glow: f32,
}

impl Reach {
    /// The farthest anyone sees at darkness `dark` (0 day, 1 night; in twilight the wider of
    /// the two, since a law may ease between them).
    pub fn sight(&self, dark: f32) -> f32 {
        if dark <= 0.0 {
            self.day
        } else if dark >= 1.0 {
            self.night
        } else {
            self.day.max(self.night)
        }
    }

    /// The farthest anything is seen at darkness `dark`: by an eye, or by a light on it.
    pub fn seen(&self, dark: f32) -> f32 {
        self.sight(dark).max(self.glow)
    }
}

/// How a creature moves besides its walking pace (`motion(a)`): shares of its walk for a run,
/// a flight and stepping aside; its turning; how far it keeps from other bodies.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Moves {
    pub run: f32,
    pub flee: f32,
    pub aside: f32,
    /// Turn rate while moving, rad/s.
    pub turn_rate: f32,
    /// Share of speed kept in the sharpest turns.
    pub turn_slow: f32,
    /// Keep this far from other bodies when it can (metres), and how strongly that bends the
    /// way (relative to the goal direction).
    pub separation: f32,
    pub separation_weight: f32,
    /// A wander keeps within `wander_turn` radians of the body's heading while it moves or
    /// after it has stood less than `wander_keep_s` seconds (0: only while moving), so a
    /// search keeps a direction; otherwise it picks one at random.
    pub wander_turn: f32,
    pub wander_keep_s: f32,
    /// The fastest a road takes a body (m/s): the road's bonus stops here, though a body that
    /// is faster on its own keeps its speed (infinite: no cap; a law without `top`).
    pub top: f32,
    /// The approach to a blow (a `closes_in` skill at a creature) runs unless the act says
    /// walk: a predator's charge (false: it walks unless the act says run).
    pub charge: bool,
}

impl Moves {
    /// Steering constants for [`crate::steer::plan`] (the road's speed is the world's).
    pub fn tuning(&self, road_speed: f32) -> crate::steer::Tuning {
        crate::steer::Tuning { turn_rate: self.turn_rate, turn_slow: self.turn_slow, road_speed, top: self.top, ..Default::default() }
    }
}

/// How often the engine runs a law, which decides how it is cached.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Cadence {
    /// Read once when the script compiles (constants, tables, descriptions).
    Compile,
    /// Run when something happens: an act starts or ends, a hook, a record falls due.
    Event,
    /// Asked for a creature on the hot path (every look, every step), and kept for every
    /// creature in the same state: the key is only the fields the law reads.
    Hot,
}

impl Cadence {
    fn parse(s: &str) -> Option<Cadence> {
        match s {
            "compile" => Some(Cadence::Compile),
            "event" => Some(Cadence::Event),
            "hot" => Some(Cadence::Hot),
            _ => None,
        }
    }
}

/// A law's declaration (`<law>_law()`): what it is, for models, and how the engine runs it.
#[derive(Clone, Debug, PartialEq)]
pub struct LawSpec {
    pub name: String,
    /// What the law says, written for a mind; the minds' world text is built from these.
    pub about: String,
    pub cadence: Cadence,
    /// The section of the minds' world text it belongs to (empty: not part of it).
    pub topic: String,
    /// The functions it declares besides its own name (`max_hp`, `lunge` under one law).
    pub covers: Vec<String>,
}

/// The traits of a law's declaration.
pub const LAW_TRAITS: &[&str] = &["about", "cadence", "topic", "reach", "covers"];

/// Laws the engine asks for that a script installed before they existed may lack: such a script
/// runs with the shipped script's functions underneath its own until its next install, and an
/// install without them is refused.
pub const REQUIRED_LAWS: &[&str] = &["senses", "motion", "items", "structures", "resources", "know_how"];

/// The world's data tables (read once when the script compiles): each a list of maps with a
/// `name`, in the script's order. `items`, `structures`, `resources` and `know_how` are
/// required; `recipes` is the world's own (none when the script has no `recipes()`).
pub const TABLES: &[&str] = &["items", "structures", "resources", "know_how", "recipes"];
/// An item's traits a client draws it by (data only: no rule reads them; docs/WORLD_RULES.md,
/// "What a client shows").
pub const ITEM_LOOK: [&str; 3] = ["icon", "label", "group"];

/// The data tables as the rules read them through the engine's primitives: `entry_of(table,
/// name)` (the entry's map, or `()`), `names_of(table)` (its names, in order) and
/// `having(table, trait)` (the names whose entry has the trait, neither `()` nor false). The
/// rules match by traits (food is what has nutrition, fuel what has the fire's fuel trait), and
/// these lookups cost one operation each instead of rebuilding a list per question.
#[derive(Clone, Debug, Default)]
pub struct Tables {
    by: HashMap<String, (Vec<String>, HashMap<String, Map>)>,
    /// The world constants in force (`laws()` with the world's own values over them, from the
    /// script's `world_law_values()`), read by laws through `law(name)`.
    laws: Map,
}

impl Tables {
    pub fn entry(&self, table: &str, name: &str) -> Option<&Map> {
        self.by.get(table).and_then(|(_, m)| m.get(name))
    }

    pub fn names(&self, table: &str) -> &[String] {
        self.by.get(table).map_or(&[], |(n, _)| n.as_slice())
    }

    /// A trait of an entry that is a number.
    pub fn number(&self, table: &str, name: &str, t: &str) -> Option<f64> {
        self.entry(table, name).and_then(|m| m.get(t)).and_then(number)
    }

    /// A trait of an entry that is a list of words (`ground: ["sand"]`).
    pub fn words(&self, table: &str, name: &str, t: &str) -> Vec<String> {
        let Some(v) = self.entry(table, name).and_then(|m| m.get(t)) else { return Vec::new() };
        v.clone().try_cast::<Array>().unwrap_or_default().into_iter().filter_map(|w| w.into_string().ok()).collect()
    }

    /// A trait of an entry that is true.
    pub fn flag(&self, table: &str, name: &str, t: &str) -> bool {
        self.entry(table, name).and_then(|m| m.get(t)).is_some_and(|v| v.as_bool() == Ok(true))
    }

    pub fn having(&self, table: &str, t: &str) -> Vec<String> {
        let Some((names, m)) = self.by.get(table) else { return Vec::new() };
        names.iter().filter(|n| m.get(n.as_str()).and_then(|e| e.get(t)).is_some_and(|v| !v.is_unit() && v.as_bool() != Ok(false))).cloned().collect()
    }

    /// The entries, in order, whose trait `t` is the text `value`; an entry without it counts as
    /// `absent` (`entries_where("recipes", "by", "make", "make")`: a recipe names its way, or is
    /// made by `make`).
    pub fn entries_where(&self, table: &str, t: &str, value: &str, absent: &str) -> Vec<&Map> {
        let Some((names, m)) = self.by.get(table) else { return Vec::new() };
        names.iter().filter_map(|n| m.get(n.as_str())).filter(|e| match e.get(t) {
            None => absent == value,
            Some(v) if v.is_unit() => absent == value,
            Some(v) => v.clone().into_string().is_ok_and(|s| s == value),
        }).collect()
    }
}

/// The engine's primitives over the data tables (see [`Tables`]).
fn register_tables(e: &mut Engine, t: &Rc<RefCell<Tables>>) {
    let t1 = t.clone();
    e.register_fn("entry_of", move |table: &str, name: &str| -> Dynamic { t1.borrow().entry(table, name).map_or(Dynamic::UNIT, |m| m.clone().into()) });
    let t2 = t.clone();
    e.register_fn("names_of", move |table: &str| -> Array { t2.borrow().names(table).iter().map(|n| Dynamic::from(n.clone())).collect() });
    let t3 = t.clone();
    e.register_fn("having", move |table: &str, tr: &str| -> Array { t3.borrow().having(table, tr).into_iter().map(Dynamic::from).collect() });
    // A world constant in force: the script's `laws()` value, or the world's own
    // (`world_law_values()`, which `set_world_law` and a seed's `rules` write). Unit when no
    // such law.
    let t5 = t.clone();
    e.register_fn("entries_where", move |table: &str, tr: &str, value: &str, absent: &str| -> Array { t5.borrow().entries_where(table, tr, value, absent).into_iter().map(|m| m.clone().into()).collect() });
    let t4 = t.clone();
    e.register_fn("law", move |name: &str| -> Dynamic { t4.borrow().laws.get(name).cloned().unwrap_or(Dynamic::UNIT) });
}

/// Distinct states whose senses or moves are kept before the memo starts over.
const CREATURE_MEMO: usize = 1_024;

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Rates {
    pub hunger_per_min: f32,
    pub energy_per_min: f32,
    pub hp_per_min: f32,
}

/// What `rates(a)` returns for a body's state: the state's rates, and the numbers by which the
/// engine finishes them for each body's own levels and genes ([`NeedLaw::rates`]). The script
/// decides every condition that has a name (sleeping, sheltered, elder, wet, cold); the
/// engine applies the thresholds on the body's hunger and energy and its genes, which differ
/// from one body to the next.
#[derive(Clone, Debug, PartialEq)]
pub enum NeedLaw {
    /// The parameters (see `living/scripts/skills.rhai`, `rates`).
    Params {
        hunger: f64,
        energy: f64,
        starving_at: f64,
        starving_hp: f64,
        fed_below: f64,
        rested_above: f64,
        healing_hp: f64,
        spent_at: f64,
        spent_hp: f64,
        healing: f64,
        tiring_gene: String,
        healing_gene: String,
        wet_energy: f64,
        cold_hp: f64,
        /// Genes (optional, empty: none) by which hunger grows faster, and by which exposure
        /// (`wet_energy`, `cold_hp`) is divided.
        appetite_gene: String,
        hardiness_gene: String,
        /// Real minutes' worth of the law's unit: the law writes its rates per game hour
        /// (`per: "hour"`) and the engine turns them into rates per real minute for the world's
        /// day length (60,000 ms over the real ms of a game hour); 1 for a law written per real
        /// minute (`per: "minute"`, or no `per`, as scripts were before day lengths varied).
        per_min: f64,
    },
    /// A script whose `rates(a)` returns the finished rates (`hunger`, `energy`, `hp`).
    Final(Rates),
}

impl NeedLaw {
    /// The hunger and energy levels where the rates change (starving at, fed below, rested
    /// above, spent at): crossing one needs the law asked again. None for finished rates.
    pub fn cuts(&self) -> Option<[f32; 4]> {
        match self {
            NeedLaw::Params { starving_at, fed_below, rested_above, spent_at, .. } => Some([*starving_at as f32, *fed_below as f32, *rested_above as f32, *spent_at as f32]),
            NeedLaw::Final(_) => None,
        }
    }

    /// The body's rates: health from its hunger and energy (starving drains it; fed and rested,
    /// it heals by the state's share of healing), tiring divided by the tiring gene, healing
    /// multiplied by the healing gene, and exposure added last.
    pub fn rates(&self, a: &ActorFacts) -> Rates {
        match self {
            NeedLaw::Final(r) => *r,
            NeedLaw::Params { hunger, energy, starving_at, starving_hp, fed_below, rested_above, healing_hp, spent_at, spent_hp, healing, tiring_gene, healing_gene, wet_energy, cold_hp, appetite_gene, hardiness_gene, per_min } => {
                let (h, e) = (a.hunger as f64, a.energy as f64);
                let mut hp = 0.0f64;
                if h >= *starving_at {
                    hp += starving_hp;
                } else if h < *fed_below && e > *rested_above {
                    hp += healing_hp;
                }
                if e <= *spent_at {
                    hp += spent_hp;
                }
                if hp > 0.0 {
                    hp *= healing;
                }
                let mut energy = *energy;
                if energy < 0.0 {
                    energy /= crate::genes::gene(&a.genes, tiring_gene) as f64;
                }
                if hp > 0.0 {
                    hp *= crate::genes::gene(&a.genes, healing_gene) as f64;
                }
                let gene = |name: &String| if name.is_empty() { 1.0 } else { crate::genes::gene(&a.genes, name) as f64 };
                let hardy = gene(hardiness_gene).max(0.1);
                energy += wet_energy / hardy;
                hp += cold_hp / hardy;
                // Into the engine's unit, a real minute, last: on the 12-minute day a game hour
                // is half a real minute, a factor of exactly 2, so the rates are the same numbers
                // as when the law was written per real minute.
                let k = *per_min;
                Rates { hunger_per_min: (*hunger * gene(appetite_gene) * k) as f32, energy_per_min: (energy * k) as f32, hp_per_min: (hp * k) as f32 }
            },
        }
    }
}

pub struct Scripts {
    engine: Engine,
    ast: AST,
    fns: HashSet<String>,
    /// Functions of one parameter: the ones the engine can call with a context.
    unary: HashSet<String>,
    shapes: crate::combat::Shapes,
    shows: crate::social::Shows,
    /// Every skill the script declares (`<skill>_spec()`).
    skills: std::sync::Arc<crate::catalog::Skills>,
    /// The ways of speaking (`<way>_speech()`), in their order.
    ways: Vec<speech::WaySpec>,
    /// Functions of no parameter.
    nullary: HashSet<String>,
    /// What each function reads of its parameters.
    fields: fields::Fields,
    /// The context fields each law is called with, by law.
    plans: RefCell<HashMap<String, Rc<context::Plan>>>,
    /// Numbers looked up by a name (`combat_cooldown("strike")`), read at compile for every name
    /// the engine asks and kept for any other the first time it is asked.
    names: RefCell<HashMap<String, HashMap<String, Option<f64>>>>,
    /// Item lists from one-argument laws (`carcass(kind)`), by law and argument.
    lists: RefCell<HashMap<String, HashMap<String, Vec<(String, u32)>>>>,
    /// `rates(a)` by the values of the fields it reads: bodies in the same state share it.
    needs: RefCell<HashMap<Vec<u8>, NeedLaw>>,
    /// `senses(a)` and `motion(a)` the same way.
    senses: RefCell<HashMap<Vec<u8>, Senses>>,
    moves: RefCell<HashMap<Vec<u8>, Moves>>,
    pools: RefCell<HashMap<Vec<u8>, crate::pools::Pools>>,
    /// `glow(a)` the same way.
    glows: RefCell<HashMap<Vec<u8>, f32>>,
    /// Life tables under the `life_years` law, by species.
    lives: RefCell<HashMap<String, crate::life::Life>>,
    /// The world's game hour in real milliseconds (its day length over 24).
    hour_ms: f64,
    /// `daylight(hour)` by game minute of the day (NaN: not asked yet).
    daylight: RefCell<Vec<f32>>,
    /// Every law the script declares (`<law>_law()`), by name.
    laws: std::collections::BTreeMap<String, LawSpec>,
    /// The farthest senses reach (from `senses_law()`).
    reach: Reach,
    /// Required laws the script lacks, taken from the shipped script (an install refuses them).
    borrowed: Vec<String>,
    /// The script's source (for the order of its declarations).
    source: String,
    /// Law declarations that failed when read (an install refuses them).
    law_errors: RefCell<Vec<String>>,
    /// What each kind of structure does for those near it (its traits in `structures()`).
    structures: HashMap<String, StructureTraits>,
    /// Resource kinds' shares of their regrowth by season (`regrow_by_season`), when not the
    /// shipped ones.
    seasons: HashMap<String, [f32; 4]>,
    /// The data tables, shared with the engine's primitives.
    tables: Rc<RefCell<Tables>>,
    /// How each skill is presented (`<name>_ui()` over its defaults), and what was wrong with
    /// the declarations (an install refuses them; a client plays on with the defaults).
    ui: ui::UiRead,
    /// What each way of making makes (a skill with `<skill>_making()`), in the script's order:
    /// each product's recipe as data (`recipe_parts`).
    makings: BTreeMap<String, Vec<RecipeParts>>,
    /// The body's meters and the memo of its statuses (`meters()`, `status_of(a)`).
    body: body::Body,
}

/// What a kind of structure does for those near it (its traits in `structures()`).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct StructureTraits {
    /// A fire that needs no feeding (a campfire): near it counts as near a fire, within the
    /// `fire_warmth` law (a building that warms: within `shelter_warmth`).
    pub warms: bool,
    /// A roof: near it counts as sheltered.
    pub roof: bool,
    /// It gives light: those within this many metres stand in lamplight (`a.actor.lit`; 0: none).
    /// A kind that `burns` gives it only while lit.
    pub lights: f32,
    /// A fire that burns fuel (a hearth, an oven, a furnace, a lamp): it warms and lights only
    /// while lit.
    pub burns: Option<Burns>,
    /// A store: the most things it holds in all (`holds`; none: not a store). One stores into
    /// and takes from a kind that has it.
    pub holds: Option<f32>,
    /// The kind it counts as wherever a kind is asked by name (`like: "storage"`: a graph's
    /// `nearest storage` finds it too); empty: only its own name.
    pub like: String,
}

/// One product of a way of making, as a recipe grid lays it out (`Scripts::recipe_parts`): the
/// script's `recipe_parts(skill, way, product)`, read once at install, with each name's look.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecipeParts {
    /// The skill whose grid it is in (`make`, `craft`, `cook`, `smoke`, or a world's own way).
    pub skill: String,
    /// What is made, and how it looks (`recipe_look`).
    pub product: String,
    pub look: ItemLook,
    /// How many one act makes.
    pub makes: u32,
    /// What the act names as its item (`human_act`'s `item`): the product, or for a way whose item
    /// is what is used (`cook`, `smoke`), the item it is made from.
    pub item: String,
    /// Used up from the pack.
    pub takes: Vec<RecipePart>,
    /// Held and not used up (none yet: goods-3 adds the recipes' `tools`).
    pub tools: Vec<RecipePart>,
    /// The structure kind it is made at, `"fire"` for any fire, or empty: anywhere.
    pub at: String,
    /// The fire there must be burning.
    pub lit: bool,
    /// Units of fuel it draws from that fire (0: none).
    pub fuel: f32,
    /// The technique it needs (empty: none).
    pub knows: String,
    /// How long one act takes.
    pub ms: u64,
}

/// A name a recipe asks for and how many: an item, or a trait that any item carrying it
/// satisfies (`alkali`: ash, or a world's soda).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecipePart {
    pub name: String,
    pub qty: u32,
    /// The items that satisfy it, in the items' order: the item itself, or every item with the
    /// trait.
    pub any_of: Vec<String>,
    /// How it looks: the item's look; for a trait, the look of the trait's name (its name as the
    /// icon and the label), which a client may draw as its first item's.
    pub look: ItemLook,
}

/// What a client shows of an item or of what a recipe makes (`Scripts::item_look_of`).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ItemLook {
    /// A short stable id the client draws it by (docs/WORLD_RULES.md lists them).
    pub icon: String,
    /// Its name for players, lower case as in a sentence.
    pub label: String,
    /// Where a pack or a recipe grid sorts it (empty: none).
    pub group: String,
}

/// A fire that eats fuel (`burns: #{ fuel, rate, warmth, light, holds }`).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Burns {
    /// The item trait that makes something its fuel; the trait's number is the units one item
    /// gives (`fuel: 1.0` on peat).
    pub fuel: String,
    /// Units burnt per game hour while lit.
    pub rate: f32,
    /// How far it warms and lights while lit (metres; the kind's `lights` counts too).
    pub warmth: f32,
    pub light: f32,
    /// The most fuel it holds (units; none: no limit).
    pub holds: Option<f32>,
}

impl StructureTraits {
    /// Whether this kind is a fire at all (one that needs no feeding, or one that burns fuel).
    pub fn fire(&self) -> bool {
        self.burns.is_some() || (self.warms && !self.roof)
    }

    /// How far it lights the dark when it burns (its `lights`, or its fire's `burns.light`).
    pub fn light(&self) -> f32 {
        self.lights.max(self.burns.as_ref().map_or(0.0, |b| b.light))
    }

    /// A structure of this kind as the rules' checks see it (`a.target.lit`, `a.target.fuel`):
    /// a fire that burns fuel is lit while `lit_until_ms` (the `structure` row's) is ahead of
    /// `now`, holding what is left at its rate on a day of `day_ms` (the `world` row's); a fire
    /// that needs no feeding is always lit and holds none; anything else is neither. The
    /// authority and a client computing the same facts call this.
    pub fn fire_state(&self, lit_until_ms: u64, now: u64, day_ms: u64) -> (bool, f32) {
        match &self.burns {
            Some(b) => (crate::fire::lit(lit_until_ms, now), crate::fire::fuel_left(lit_until_ms, now, b.rate, day_ms)),
            None => (self.fire(), 0.0),
        }
    }
}

/// Largest script source accepted. `skills.rhai` is about 56 KB; compile time and memory grow
/// about linearly (5 ms and 1.3 MB in the module for 55 KB, docs/SCRIPT_ENGINES.md).
pub const MAX_SOURCE: usize = 256 * 1024;
/// Rhai operations one call may take: about 2× the heaviest function measured on the install
/// samples (`skill_io`, 864; the heaviest law, `teach_check`, 635; docs/SCRIPT_ENGINES.md).
/// At about 600 WASM instructions per operation, a call that runs into it costs about 1.2 M
/// instructions (about 0.1 ms in the module).
pub const MAX_OPERATIONS: u64 = 2_000;
/// The most operations a function read once when the script compiles may take (its data tables,
/// skills' specs, ways, laws' descriptions and the interface's declarations): they grow with a
/// world's content (a description lists every recipe) and run once per install, not while the
/// world runs; the engine's calls keep [`MAX_OPERATIONS`] (goods-3).
pub const COMPILE_OPERATIONS: u64 = 20_000;
/// Distinct states whose rates are kept before the memo starts over.
const NEEDS_MEMO: usize = 4_096;
/// Minutes in a game day: `daylight` is read at each.
const DAY_MINUTES: usize = 24 * 60;

/// The engine's limits on one call (Rhai's sandbox): operations, call depth, expression depth
/// (outside and inside functions) and the size of strings, arrays and maps a script makes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Limits {
    pub operations: u64,
    pub call_levels: usize,
    pub expr_depth: (usize, usize),
    pub string: usize,
    pub array: usize,
    pub map: usize,
}

/// About 2–4× what the rules use on the install samples (`measure_limits`, 2026-11-09): call
/// depth 3, expression depth 19 in and out of functions, strings 570 characters. The string
/// limit bounds what a script builds, not the text it is handed (a reworked routine arrives as
/// up to 32,000 characters). Rhai counts the entries of arrays and maps nested in a value
/// together, so the world's data tables (`items()`, `resources()`, each a list of maps) set the
/// array and map limits: Cullet's goods over the shipped ones hold about 110 map entries in
/// `resources()` and 60 array entries (2026-11-11); the limits leave room for a world about
/// four times that. Rhai counts the strings of a map together too: `laws_about(l)`, the words
/// for every world constant, held 1,959 characters before the field of view's laws (`fov-1`,
/// 2026-11-11) and 2,373 after. `stamina-1` (2026-11-11) added 38 constants for breath, focus,
/// costs, health and blows: their words bring it past 4,096 (about 4,200 with the numbers), so the
/// string limit is 6,144; their numbers are written as they are (`${l.x}`, not `short`), since a
/// call each took `laws_about` past its operations.
pub const LIMITS: Limits = Limits { operations: MAX_OPERATIONS, call_levels: 8, expr_depth: (40, 40), string: 6_144, array: 256, map: 512 };

/// Rhai's hashing keys, the same in every build of every program that runs the laws: the
/// authority, the game client and the mind service (docs/LIVING_CORE.md, "One hashing seed").
///
/// Rhai hashes function names, call signatures and `switch` cases with `ahash`, and turns on
/// `ahash`'s `compile-time-rng`. Unless a seed is set, the keys are random numbers drawn each
/// time `ahash` compiles (a new target folder, a cache miss, a toolchain update), and they
/// decide where entries land in Rhai's tables and in which order it hands back a script's
/// functions. So the same source cost a different fuel per call from build to build (`tool-8`),
/// and a rule that followed that order (`fov-1`'s field analysis) decided differently by build.
/// Fixed keys make both a function of the code alone.
///
/// The value is the fuel bench's key set 0 since `tool-8` (`sb_bench::hashing_seed(0)`), so the
/// gate's history at that set is the game's; nothing else about it matters but that it is not
/// zero (Rhai takes zero keys as no seed) and never changes: changing it moves every law's fuel.
/// It was not chosen for a law's fuel. Fixed keys are public, so whoever chooses a string that
/// Rhai hashes could look for collisions: to slow the engine (hash flooding) or to take a wrong
/// `switch` branch (Rhai matches a case by its hash alone). Acceptable while scripts come from a
/// world's seed and admin installs; the docs list where a player's words reach a hashed
/// position today (an act's item) and when to revisit.
pub const HASHING_SEED: [u64; 4] = [0x5eed_0000_0000_0001, 0x5eed_0000_0000_0002, 0x5eed_0000_0000_0003, 0x5eed_0000_0000_0004];

/// Fix Rhai's hashing keys to [`HASHING_SEED`] (`rhai::config::hashing::set_hashing_seed`) and
/// return the keys in force. Rhai reads them once per process (a module instance), so this must
/// run before anything touches Rhai: every engine of this crate is made by [`new_engine`], which
/// calls it. Keys set earlier by someone else stay in force (the fuel bench's other key sets).
pub fn fix_hashing() -> [u64; 4] {
    #[cfg(test)]
    if let Some(k) = test_seed() {
        let _ = rhai::config::hashing::set_hashing_seed(k);
        return k.unwrap_or_default();
    }
    let _ = rhai::config::hashing::set_hashing_seed(Some(HASHING_SEED));
    rhai::config::hashing::get_hashing_seed().unwrap_or_default()
}

/// Tests only: other keys for this process (`LIVING_RHAI_TEST_SEED`: four numbers, or `build`
/// for the keys this build of `ahash` drew), for the check that no rule depends on them.
#[cfg(test)]
fn test_seed() -> Option<Option<[u64; 4]>> {
    let v = std::env::var("LIVING_RHAI_TEST_SEED").ok()?;
    if v == "build" {
        return Some(None);
    }
    let k: Vec<u64> = v.split(',').map(|w| w.trim().parse().expect("LIVING_RHAI_TEST_SEED: four numbers or `build`")).collect();
    Some(Some(k.try_into().expect("LIVING_RHAI_TEST_SEED: four numbers")))
}

/// A bare Rhai engine, after [`fix_hashing`]. The only way this crate makes one.
pub fn new_engine() -> Engine {
    fix_hashing();
    Engine::new_raw()
}

fn engine(t: &Rc<RefCell<Tables>>) -> Engine {
    engine_with(LIMITS, t)
}

fn engine_with(l: Limits, t: &Rc<RefCell<Tables>>) -> Engine {
    let mut e = new_engine();
    register_tables(&mut e, t);
    rhai::packages::StandardPackage::new().register_into_engine(&mut e);
    e.set_max_operations(l.operations);
    e.set_max_call_levels(l.call_levels);
    e.set_max_expr_depths(l.expr_depth.0, l.expr_depth.1);
    e.set_max_string_size(l.string);
    e.set_max_array_size(l.array);
    e.set_max_map_size(l.map);
    for symbol in ["eval", "import", "print", "debug"] {
        e.disable_symbol(symbol);
    }
    e
}

/// The world's day for its laws: `hour_ms()`, real milliseconds in a game hour, and
/// `day_minutes()`, real minutes in a game day.
fn register_day(e: &mut Engine, hour_ms: f64) {
    e.register_fn("hour_ms", move || hour_ms);
    e.register_fn("day_minutes", move || hour_ms * 24.0 / 60_000.0);
}

/// Constant laws the engine looks up by a name, and the names it asks them for.
fn name_laws(s: &Scripts) -> Vec<(String, Vec<String>)> {
    let skills: Vec<String> = s.shapes.names().map(String::from).chain(s.skills.names().map(String::from)).collect();
    let kinds: Vec<String> = crate::catalog::CREATURES.iter().map(|k| k.to_string()).collect();
    let items: Vec<String> = s.skills.items.iter().map(|i| i.name.clone()).collect();
    let structures: Vec<String> = s.skills.structures.iter().map(|k| k.name.clone()).collect();
    let resources: Vec<String> = s.skills.resources.iter().map(|k| k.name.clone()).collect();
    let mut out = Vec::new();
    let mut add = |f: &str, d: &[String]| {
        if s.has(f) {
            let mut d = d.to_vec();
            d.sort();
            d.dedup();
            out.push((f.to_string(), d));
        }
    };
    for f in ["combat_cooldown", "combat_recover", "combat_cost"] {
        add(f, &skills);
    }
    // Rates and durations in game time (`_per_h`, `_h`), and the same in real time as scripts
    // before rates-2 wrote them (`spoil_rate`, `regrow`, `remains_s`, `trap_every_s`).
    for f in ["lunge", "max_hp", "yield_ms", "carry_limit", "carried_spoil", "remains_h", "remains_s"] {
        add(f, &kinds);
    }
    add("spoil_per_h", &items);
    add("spoil_rate", &items);
    add("nutrition", &items);
    add("carry_of", &items);
    add("regrow_per_h", &resources);
    add("regrow", &resources);
    add("planted_max", &resources);
    add("kept_spoil", &structures);
    for f in ["trap_every_h", "trap_every_s", "trap_holds"] {
        add(f, &["meat".to_string()]);
    }
    // A dash's and a step's distance and speed by kind.
    let moves: Vec<String> = s.fns.iter().filter(|f| f.ends_with("_dist") || f.ends_with("_speed")).filter(|f| *f != "move_speed").cloned().collect();
    for f in moves {
        add(&f, &kinds);
    }
    out
}

impl Scripts {
    /// The script for a world with the shipped day length ([`crate::DEFAULT_DAY_MS`]).
    pub fn new(source: &str) -> Result<Self, String> {
        Self::with_day(source, crate::DEFAULT_DAY_MS)
    }

    /// The script for a world whose day lasts `day_ms` real milliseconds. Laws written per game
    /// hour (`rates` with `per: "hour"`) are turned into real time by it, and a law may read it:
    /// `hour_ms()` (real milliseconds in a game hour) and `day_minutes()` (real minutes in a day).
    pub fn with_day(source: &str, day_ms: u64) -> Result<Self, String> {
        if source.len() > MAX_SOURCE {
            return Err(format!("script source exceeds {} KiB", MAX_SOURCE / 1024));
        }
        let day_ms = day_ms.max(24);
        let hour_ms = day_ms as f64 / 24.0;
        let tables: Rc<RefCell<Tables>> = Default::default();
        let mut engine = engine(&tables);
        register_day(&mut engine, hour_ms);
        let mut ast = engine.compile(source).map_err(|e| format!("script compile: {e}"))?.clone_functions_only();
        // A script from before a required law existed runs on the shipped script's functions,
        // with its own on top, until it is installed again.
        let borrowed: Vec<String> = REQUIRED_LAWS.iter().filter(|f| !ast.iter_functions().any(|d| d.name == **f)).map(|f| f.to_string()).collect();
        // What each function reads, from its own source: the field analysis places statements by
        // line and column, which two sources share, so a merged script is analysed source by
        // source, the script's own functions over the shipped ones.
        let mut fields = None;
        if !borrowed.is_empty() {
            const SHIPPED: &str = include_str!("../../scripts/skills.rhai");
            let base = engine.compile(SHIPPED).map_err(|e| format!("shipped script compile: {e}"))?.clone_functions_only();
            fields = Some(fields::Fields::analyze(&base).under(fields::Fields::analyze(&ast)));
            ast = base.merge(&ast);
        }
        // A floor's overlay keeps each base function it replaces as `base_NAME` (`floors::compose`):
        // only the overlay calls those, so the engine never takes one for a law, a skill's part or
        // a declaration of its own (`base_sleep_duration` is not the rules of a skill `base_sleep`).
        let own = |name: &str| !name.starts_with("base_");
        let fns = ast.iter_functions().filter(|f| own(f.name)).map(|f| f.name.to_string()).collect();
        let unary = ast.iter_functions().filter(|f| own(f.name) && f.params.len() == 1).map(|f| f.name.to_string()).collect();
        let nullary = ast.iter_functions().filter(|f| own(f.name) && f.params.is_empty()).map(|f| f.name.to_string()).collect();
        let fields = fields.unwrap_or_else(|| fields::Fields::analyze(&ast));
        let reach = Reach { day: 0.0, night: 0.0, hearing: 0.0, glow: 0.0 };
        let mut s = Self { engine, ast, fns, unary, nullary, shapes: Default::default(), shows: Default::default(), skills: Default::default(), ways: Vec::new(), fields, plans: Default::default(), names: Default::default(), lists: Default::default(), needs: Default::default(), senses: Default::default(), moves: Default::default(), pools: Default::default(), glows: Default::default(), lives: Default::default(), hour_ms, daylight: Default::default(), laws: Default::default(), reach, borrowed, structures: Default::default(), seasons: Default::default(), tables, source: source.to_string(), law_errors: Default::default(), ui: Default::default(), body: Default::default(), makings: Default::default() };
        // Skills in the order the source declares them (the last declaration of a name counts).
        let declared = |name: &str| source.rfind(&format!("fn {name}_spec(")).unwrap_or(usize::MAX);
        // Required entry points.
        for f in ["rates", "move_speed"] {
            if !s.fns.contains(f) {
                return Err(format!("script must define `{f}(a)`"));
            }
        }
        // What is read once here may take more than a call of the running world (above).
        s.engine.set_max_operations(COMPILE_OPERATIONS);
        // The world constants in force, for `law(name)`.
        let laws = s.laws_map();
        s.tables.borrow_mut().laws = laws;
        // The data tables first: specs and laws may read them (`names_of("recipes")`).
        s.read_tables()?;
        s.shapes = s.read_shapes()?;
        s.shows = s.read_shows()?;
        let mut skills = s.read_specs(&declared)?;
        skills.items = s.read_items()?;
        skills.resources = s.kinds_of("resources");
        skills.structures = s.kinds_of("structures");
        skills.techniques = s.read_know_how()?;
        s.skills = std::sync::Arc::new(skills);
        s.makings = s.read_makings()?;
        s.ways = s.read_ways()?;
        s.structures = s.read_structures()?;
        s.seasons = s.read_seasons()?;
        s.laws = s.read_laws()?;
        s.reach = s.read_reach()?;
        for (f, names) in name_laws(&s) {
            for n in names {
                s.num_of(&f, &n, 0.0);
            }
        }
        // Presentation last: it reads the skills, shapes, shows and tables, and never fails the
        // compile (`ui_errors`).
        s.ui = s.read_ui();
        // The body's meters: never fail the compile either (`meter_errors`, refused at install).
        s.body = s.read_body();
        s.engine.set_max_operations(LIMITS.operations);
        Ok(s)
    }

    /// Call every law and skill function on sample inputs, the way the engine calls them, and
    /// refuse the script if any fails, returns the wrong shape, reads a field the engine does
    /// not provide or exceeds the engine's limits. Returns the operations each function took.
    pub fn validate(&self) -> Result<Report, String> {
        check::validate(self, LIMITS)
    }

    /// The operations a function of no arguments takes (a law's description, a spec), with no
    /// limit, for measuring (goods-3).
    #[cfg(test)]
    pub(crate) fn ops_of(&self, f: &str) -> u64 {
        let count = Rc::new(std::cell::Cell::new(0u64));
        let mut engine = engine_with(Limits { operations: 10_000_000, ..LIMITS }, &self.tables);
        register_day(&mut engine, self.hour_ms);
        let c2 = count.clone();
        engine.on_progress(move |n| {
            c2.set(n);
            None
        });
        let _ = engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, ());
        count.get()
    }

    /// The fields a law is called with (all of them when the analysis cannot say).
    fn plan(&self, f: &str) -> Rc<context::Plan> {
        if let Some(p) = self.plans.borrow().get(f) {
            return p.clone();
        }
        let p = Rc::new(context::Plan::of(f, self.fields.of(f, 1).and_then(|u| u.first()), false).unwrap_or_else(|_| context::Plan::all()));
        self.plans.borrow_mut().insert(f.to_string(), p.clone());
        p
    }

    /// The laws the engine calls with a context, by name.
    fn ctx_laws(&self) -> Vec<String> {
        let mut v: Vec<String> = self.unary.iter().filter(|f| check::CTX_LAWS.contains(&f.as_str()) || check::SKILL_PARTS.iter().any(|x| f.ends_with(x)) || f.starts_with("on_")).cloned().collect();
        v.sort();
        v
    }

    /// What each law reads of its context, for reports.
    pub fn law_fields(&self) -> Vec<(String, Vec<String>)> {
        self.ctx_laws().into_iter().map(|f| (f.clone(), self.plan(&f).describe())).collect()
    }

    /// What each combat skill is (`<skill>_combat()`) and the skill bar (`skill_bar()`), read
    /// once here so the authority never asks the script per tick.
    fn read_shapes(&self) -> Result<crate::combat::Shapes, String> {
        use crate::combat::{Aim, Shape};
        let mut shapes = std::collections::BTreeMap::new();
        for f in self.fns.iter().filter(|f| f.ends_with("_combat")) {
            let skill = f.trim_end_matches("_combat");
            if skill.is_empty() {
                continue;
            }
            let m = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, ()).map_err(|e| format!("{f}: {e}"))?.try_cast::<Map>().ok_or_else(|| format!("{f} must return a map"))?;
            const KNOWN: &[&str] = &["aim", "timed", "rooted", "hostile", "reflex", "evades", "real_time", "melee", "closes_in", "menace", "force", "dares", "hold_ms", "arc", "takes", "knack", "needs", "knows"];
            if let Some(k) = m.keys().find(|k| !KNOWN.contains(&k.as_str())) {
                return Err(format!("{f}: unknown trait `{k}` (traits are {})", KNOWN.join(", ")));
            }
            let flag = |k: &str| m.get(k).map_or(Ok(false), |v| v.as_bool().map_err(|_| format!("{f}: `{k}` must be true or false")));
            let num = |k: &str| m.get(k).map_or(Ok(0.0), |v| number(v).ok_or_else(|| format!("{f}: `{k}` must be a number")));
            let text = |k: &str| m.get(k).map_or(Ok(String::new()), |v| v.clone().into_string().map_err(|_| format!("{f}: `{k}` must be a string")));
            let list = |k: &str| -> Result<Vec<String>, String> {
                let Some(v) = m.get(k) else { return Ok(Vec::new()) };
                let a = v.clone().try_cast::<Array>().ok_or_else(|| format!("{f}: `{k}` must be a list of names"))?;
                a.into_iter().map(|x| x.into_string().map_err(|_| format!("{f}: `{k}` must be a list of names"))).collect()
            };
            let aim = Aim::parse(&text("aim")?).ok_or_else(|| format!("{f}: aim is one of none, creature, self_or_ally, point, facing, dash"))?;
            let missile = self.has(&format!("{skill}_missile"));
            if aim == Aim::Point && !missile {
                return Err(format!("{f}: a skill aimed at a point is a skillshot and needs `{skill}_missile(a)`"));
            }
            let shape = Shape {
                code: 0,
                aim,
                timed: flag("timed")?,
                rooted: flag("rooted")?,
                hostile: flag("hostile")?,
                reflex: flag("reflex")?,
                // A dash evades unless it says otherwise; nothing else does.
                evades: aim == Aim::Dash && m.get("evades").map_or(Ok(true), |v| v.as_bool().map_err(|_| format!("{f}: `evades` must be true or false")))?,
                real_time: flag("real_time")?,
                melee: flag("melee")?,
                closes_in: flag("closes_in")?,
                menace: flag("menace")?,
                force: flag("force")?,
                dares: flag("dares")?,
                missile,
                hold_ms: num("hold_ms")?.clamp(0.0, 600_000.0) as u32,
                arc: num("arc")?.clamp(0.0, 180.0) as f32,
                takes: num("takes")?.clamp(0.0, 1.0) as f32,
                knack: text("knack")?,
                needs: list("needs")?,
                knows: list("knows")?,
            };
            shapes.insert(skill.to_string(), shape);
        }
        let bar = if self.has("skill_bar") {
            let a = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "skill_bar", ()).map_err(|e| format!("skill_bar: {e}"))?.try_cast::<Array>().ok_or("skill_bar must return a list of skills")?;
            a.into_iter().map(|x| x.into_string().map_err(|_| "skill_bar must return a list of skills".to_string())).collect::<Result<Vec<_>, _>>()?
        } else {
            Vec::new()
        };
        crate::combat::Shapes::new(shapes, bar)
    }

    /// What each skill is (`<skill>_spec()`): its arguments, reach and description, read once
    /// here. A script that declares no skill at all (one installed before skills were declared
    /// in the script, 2026-11-10) is given the shipped script's, so its world keeps its skills
    /// until the next install.
    fn read_specs(&self, declared: &dyn Fn(&str) -> usize) -> Result<crate::catalog::Skills, String> {
        let mut list = Vec::new();
        for f in self.nullary.iter().filter(|f| f.ends_with("_spec")) {
            let skill = f.trim_end_matches("_spec");
            if skill.is_empty() {
                continue;
            }
            let m = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, ()).map_err(|e| format!("{f}: {e}"))?.try_cast::<Map>().ok_or_else(|| format!("{f} must return a map"))?;
            list.push(spec_of(skill, &m)?);
        }
        // The shipped script's, unless it is this one or declares none either (no recursion).
        const SHIPPED: &str = include_str!("../../scripts/skills.rhai");
        if list.is_empty() && SHIPPED.contains("_spec() {") && !self.nullary.is_empty() {
            return Self::new(SHIPPED).map(|s| (*s.skills).clone());
        }
        list.sort_by_key(|k: &crate::catalog::SkillSpec| (declared(&k.name), k.name.clone()));
        Ok(crate::catalog::Skills::new(list))
    }

    /// The ways of speaking (`<way>_speech()`), read once here, in their `order` (then the
    /// source's). A script that declares none speaks by the shipped `say` (today's speech), so a
    /// world installed before ways were declared keeps speaking until its next install.
    fn read_ways(&self) -> Result<Vec<speech::WaySpec>, String> {
        let mut ways = Vec::new();
        for f in self.nullary.iter().filter(|f| f.ends_with("_speech")) {
            let way = f.trim_end_matches("_speech");
            if way.is_empty() {
                continue;
            }
            if !way.chars().all(|c| c.is_ascii_lowercase() || c == '_') {
                return Err(format!("{f}: a way's name is lowercase letters and _"));
            }
            if self.skills.get(way).is_some() || self.shapes.get(way).is_some() {
                return Err(format!("{f}: `{way}` is a skill already; a way of speaking needs a name of its own"));
            }
            let m = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, ()).map_err(|e| format!("{f}: {e}"))?.try_cast::<Map>().ok_or_else(|| format!("{f} must return a map"))?;
            let w = speech::way_of(way, &m)?;
            if !w.needs.is_empty() && !self.skills.techniques.iter().any(|t| t.name == w.needs) {
                return Err(format!("{f}: `needs` names a technique of `know_how()`, not `{}`", w.needs));
            }
            ways.push(w);
        }
        if ways.is_empty() {
            ways.push(speech::WaySpec::say());
        }
        if !ways.iter().any(|w| w.name == speech::SAY) {
            return Err("the script's ways of speaking need `say_speech()` (every line said without a way is said by it)".into());
        }
        ways.sort_by_key(|w| (w.order, self.source_at(&format!("fn {}_speech(", w.name)), w.name.clone()));
        Ok(ways)
    }

    /// The ways of speaking, in their order.
    pub fn ways(&self) -> &[speech::WaySpec] {
        &self.ways
    }

    /// A way of speaking by name.
    pub fn way(&self, name: &str) -> Option<&speech::WaySpec> {
        self.ways.iter().find(|w| w.name == name)
    }

    /// Every skill the script declares.
    pub fn skills(&self) -> &std::sync::Arc<crate::catalog::Skills> {
        &self.skills
    }

    /// The data tables (`items()`, `structures()`, `resources()`, `know_how()`, `recipes()`):
    /// each a list of maps with a distinct `name`, read once.
    fn read_tables(&self) -> Result<(), String> {
        let mut t = Tables::default();
        for f in TABLES {
            if !self.has(f) {
                if REQUIRED_LAWS.contains(f) {
                    return Err(format!("script must define `{f}()`"));
                }
                continue;
            }
            let a = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, ()).map_err(|e| format!("{f}: {e}"))?.try_cast::<Array>().ok_or_else(|| format!("{f} must return a list of maps"))?;
            let (mut names, mut by) = (Vec::new(), HashMap::new());
            for d in a {
                let m = d.try_cast::<Map>().ok_or_else(|| format!("{f}: each entry is a map with a name"))?;
                let name = m.get("name").and_then(|v| v.clone().into_string().ok()).filter(|n| !n.is_empty()).ok_or_else(|| format!("{f}: each entry has a name"))?;
                if by.contains_key(&name) {
                    return Err(format!("{f}: `{name}` twice"));
                }
                names.push(name.clone());
                by.insert(name, m);
            }
            t.by.insert(f.to_string(), (names, by));
        }
        t.laws = std::mem::take(&mut self.tables.borrow_mut().laws);
        *self.tables.borrow_mut() = t;
        Ok(())
    }

    /// The data tables, as the rules read them.
    pub fn tables(&self) -> std::cell::Ref<'_, Tables> {
        self.tables.borrow()
    }

    /// The entries of a table with their traits as words (a trait that is true reads "true").
    fn kinds_of(&self, table: &str) -> Vec<crate::catalog::KindSpec> {
        let t = self.tables.borrow();
        t.names(table)
            .iter()
            .map(|n| {
                let traits = t.entry(table, n).map(|m| m.iter().filter(|(k, _)| k.as_str() != "name").map(|(k, v)| (k.to_string(), v.to_string())).collect()).unwrap_or_default();
                crate::catalog::KindSpec { name: n.clone(), traits }
            })
            .collect()
    }

    /// The world's items and their traits (`items()`), read once.
    /// An item's `icon`, `label` and `group` (what a client shows of it) must be texts.
    fn read_items(&self) -> Result<Vec<crate::catalog::ItemSpec>, String> {
        let t = self.tables.borrow();
        for n in t.names("items") {
            let m = t.entry("items", n).expect("listed");
            for k in ITEM_LOOK {
                if m.get(k).is_some_and(|v| !v.is_string()) {
                    return Err(format!("items: the {k} of `{n}` must be a text"));
                }
            }
        }
        drop(t);
        Ok(self.kinds_of("items").into_iter().map(|k| crate::catalog::ItemSpec { name: k.name, traits: k.traits }).collect())
    }

    /// The world's techniques (`know_how()`: a `name` and a `help`, what one is told it is).
    fn read_know_how(&self) -> Result<Vec<crate::catalog::TechniqueSpec>, String> {
        let t = self.tables.borrow();
        let mut out = Vec::new();
        for n in t.names("know_how") {
            let m = t.entry("know_how", n).expect("listed");
            let help = match m.get("help") {
                None => String::new(),
                Some(v) => v.clone().into_string().map_err(|_| format!("know_how: the help of `{n}` must be a text"))?,
            };
            out.push(crate::catalog::TechniqueSpec { name: n.clone(), help });
        }
        Ok(out)
    }

    /// What each kind of structure does for those near it (its traits in `structures()`), read
    /// once. A script from before structures were listed (2026-11-11) also has
    /// `structure_traits()`: its `warms` and `roof` stand over the listed kinds'.
    fn read_structures(&self) -> Result<HashMap<String, StructureTraits>, String> {
        let t = self.tables.borrow();
        let mut out = HashMap::new();
        for k in t.names("structures") {
            let m = t.entry("structures", k).expect("listed");
            let flag = |x: &str| -> Result<bool, String> { m.get(x).map_or(Ok(false), |v| v.as_bool().map_err(|_| format!("structures: `{x}` of `{k}` must be true or false"))) };
            let lights = match m.get("lights") {
                None => 0.0,
                Some(v) => number(v).ok_or_else(|| format!("structures: `lights` of `{k}` must be a number of metres"))?.clamp(0.0, 64.0) as f32,
            };
            let burns = match m.get("burns") {
                None => None,
                Some(v) => Some(burns_of(k, v)?),
            };
            let holds = match m.get("holds") {
                None => None,
                Some(v) => Some(number(v).filter(|n| *n >= 0.0 && n.is_finite()).ok_or_else(|| format!("structures: `holds` of `{k}` is the most things it holds in all (a number of at least 0)"))? as f32),
            };
            let like = match m.get("like") {
                None => String::new(),
                Some(v) => {
                    let l = v.clone().into_string().map_err(|_| format!("structures: `like` of `{k}` names the kind it counts as"))?;
                    if l == *k || t.entry("structures", &l).is_none() {
                        return Err(format!("structures: `like` of `{k}` is `{l}`, which is not another kind of the table"));
                    }
                    l
                }
            };
            out.insert(k.clone(), StructureTraits { warms: flag("warms")?, roof: flag("roof")?, lights, burns, holds, like });
        }
        if self.has("structure_traits") {
            let legacy = self.law_map("structure_traits")?;
            for (k, v) in legacy {
                let m = v.try_cast::<Map>().ok_or_else(|| format!("structure_traits: `{k}` must be a map of traits"))?;
                if let Some(x) = m.keys().find(|x| !["warms", "roof", "lights"].contains(&x.as_str())) {
                    return Err(format!("structure_traits: unknown trait `{x}` of `{k}` (traits are warms, roof, lights)"));
                }
                let flag = |x: &str| m.get(x).is_some_and(|v| v.as_bool().unwrap_or(false));
                let e = out.entry(k.to_string()).or_default();
                (e.warms, e.roof) = (flag("warms"), flag("roof"));
                if let Some(v) = m.get("lights") {
                    e.lights = number(v).ok_or_else(|| format!("structure_traits: `{k}.lights` must be a number of metres"))?.clamp(0.0, 64.0) as f32;
                }
            }
        }
        Ok(out)
    }

    /// What a kind of structure does for those near it.
    pub fn structure(&self, kind: &str) -> &StructureTraits {
        static NONE: StructureTraits = StructureTraits { warms: false, roof: false, lights: 0.0, burns: None, holds: None, like: String::new() };
        self.structures.get(kind).unwrap_or(&NONE)
    }

    /// Whether a structure of `kind` is what a rule or a graph asks for by `name`: that kind, or
    /// one `like` it (Cullet's `store` is `like: "storage"`).
    pub fn is_kind(&self, kind: &str, name: &str) -> bool {
        kind == name || (!name.is_empty() && self.structure(kind).like == name)
    }

    /// The share of a resource kind's regrowth rate in each season (spring, summer, autumn,
    /// winter): its `regrow_by_season` in `resources()`, any season it leaves out at the
    /// shipped share ([`crate::GROWING`]: full, and none in winter).
    pub fn regrow_seasons(&self, kind: &str) -> [f32; 4] {
        self.seasons.get(kind).copied().unwrap_or(crate::GROWING)
    }

    /// What minds are told the seasons do to the land, after the calendar: the script's
    /// `seasons_text()` (built from the resource kinds' `regrow_by_season`), or, for a script
    /// without it, the words every world was told before (2026-11-11).
    pub fn seasons_words(&self) -> String {
        const BEFORE: &str = "In winter nothing regrows and nights are colder: store food before it.";
        if !self.has("seasons_text") {
            return BEFORE.into();
        }
        self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "seasons_text", ()).ok().and_then(|d| d.into_string().ok()).unwrap_or_else(|| BEFORE.into())
    }

    /// Every resource kind's `regrow_by_season`, read once (only kinds that have it).
    fn read_seasons(&self) -> Result<HashMap<String, [f32; 4]>, String> {
        let t = self.tables.borrow();
        let mut out = HashMap::new();
        for k in t.names("resources") {
            let Some(v) = t.entry("resources", k).and_then(|m| m.get("regrow_by_season")) else { continue };
            let m = v.clone().try_cast::<Map>().ok_or_else(|| format!("resources: `regrow_by_season` of `{k}` is a map of seasons (spring, summer, autumn, winter) to shares of its rate"))?;
            let mut by = crate::GROWING;
            for (season, share) in m {
                let i = crate::SEASONS.iter().position(|x| *x == season.as_str()).ok_or_else(|| format!("resources: `regrow_by_season` of `{k}` names `{season}`, which is no season (spring, summer, autumn, winter)"))?;
                by[i] = number(&share).filter(|n| *n >= 0.0 && *n <= 16.0).ok_or_else(|| format!("resources: `regrow_by_season.{season}` of `{k}` is a share of its rate (0 to 16)"))? as f32;
            }
            out.insert(k.clone(), by);
        }
        Ok(out)
    }

    /// How far any structure warms or shelters (the farthest the engine looks for one).
    pub fn warmth_reach(&self, laws: &Laws) -> f32 {
        self.structures.values().fold(laws.fire_warmth.max(laws.shelter_warmth), |r, t| r.max(t.burns.as_ref().map_or(0.0, |b| b.warmth)))
    }

    /// The farthest any kind of structure gives light (0: none does): its `lights`, or a fire's
    /// `burns.light`.
    pub fn widest_light(&self) -> f32 {
        self.structures.values().map(|t| t.light()).fold(0.0, f32::max)
    }

    /// A list of words a law of one name gives (`occupation_knows("fisher")`); empty when the
    /// script has no such law or it gives something else.
    pub fn words_of(&self, f: &str, arg: &str) -> Vec<String> {
        if !self.has(f) {
            return Vec::new();
        }
        let Ok(d) = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (arg.to_string(),)) else { return Vec::new() };
        d.try_cast::<Array>().unwrap_or_default().into_iter().filter_map(|x| x.into_string().ok()).collect()
    }

    /// The text a law of one name gives (`source_of("food")`).
    pub fn text_of(&self, f: &str, arg: &str) -> Option<String> {
        if !self.has(f) {
            return None;
        }
        self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (arg.to_string(),)).ok()?.into_string().ok()
    }

    /// What a way of making makes (`craft`, `cook`, `smoke`, `make`, or a world's own: a skill
    /// with `<skill>_making()`), in the script's order: a recipe grid's cells. Empty for a skill
    /// that is no way of making, or that makes nothing in this world.
    pub fn products_of(&self, skill: &str) -> Vec<&str> {
        self.makings.get(skill).map(|v| v.iter().map(|p| p.product.as_str()).collect()).unwrap_or_default()
    }

    /// What an act of a way of making names as its item to make `product`: the product itself,
    /// or for a way whose item is what is used (`cook`, `smoke`), the item it is made from
    /// (`cooked_fish` → `fish`). None when the way does not make it.
    pub fn making_item(&self, skill: &str, product: &str) -> Option<&str> {
        self.recipe_parts(skill, product).map(|p| p.item.as_str())
    }

    /// A product of a way of making as data, for a recipe grid's cell: what it takes and holds,
    /// where, with what heat and knowing, how long; each name with its look. None when the way
    /// does not make it. `made_how(product)` is the same recipe in words.
    pub fn recipe_parts(&self, skill: &str, product: &str) -> Option<&RecipeParts> {
        self.makings.get(skill)?.iter().find(|p| p.product == product)
    }

    /// The ways of making and what they make (`products_of`, `making_item`), read once: for each
    /// skill with `<skill>_making()`, the script's `products_of(skill)` and, for each product,
    /// `making_item(skill, way, product)`. A script without them (from before recipes-1) has none.
    fn read_makings(&self) -> Result<BTreeMap<String, Vec<RecipeParts>>, String> {
        let mut out = BTreeMap::new();
        if !self.unary.contains("products_of") || !self.fns.contains("recipe_parts") {
            return Ok(out);
        }
        let mut ways: Vec<&String> = self.nullary.iter().filter(|f| f.ends_with("_making")).collect();
        ways.sort();
        for f in ways {
            let skill = f.trim_end_matches("_making");
            if self.skills.get(skill).is_none() {
                return Err(format!("{f}: `{skill}` is not a skill (no `{skill}_spec()`): a way of making is a skill's"));
            }
            let way = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, ()).map_err(|e| format!("{f}: {e}"))?;
            if !way.is_map() {
                return Err(format!("{f} must return a map"));
            }
            let products = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "products_of", (skill.to_string(),)).map_err(|e| format!("products_of(\"{skill}\"): {e}"))?;
            let products = products.try_cast::<Array>().ok_or_else(|| format!("products_of(\"{skill}\") must return a list of names"))?;
            let mut made: Vec<RecipeParts> = Vec::new();
            for p in products {
                let p = p.into_string().map_err(|_| format!("products_of(\"{skill}\") must return a list of names"))?;
                if made.iter().any(|q| q.product == p) {
                    continue;
                }
                let bad = |what: &str| format!("recipe_parts(\"{skill}\", \"{p}\"): {what}");
                let m = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "recipe_parts", (skill.to_string(), way.clone(), p.clone())).map_err(|e| bad(&e.to_string()))?;
                let Some(m) = m.try_cast::<Map>() else { return Err(bad("must return a map")) };
                let text = |k: &str| m.get(k).and_then(|v| v.clone().into_string().ok()).unwrap_or_default();
                let num = |k: &str| m.get(k).and_then(|v| v.as_float().ok().or_else(|| v.as_int().ok().map(|n| n as f64))).unwrap_or(0.0);
                let parts = |k: &str| -> Result<Vec<RecipePart>, String> {
                    let Some(t) = m.get(k).and_then(|v| v.clone().try_cast::<Map>()) else { return Ok(Vec::new()) };
                    let mut out = Vec::new();
                    for (name, n) in t {
                        let qty = n.as_int().map_err(|_| bad(&format!("`{k}.{name}` must be a whole number")))?.max(0) as u32;
                        let name = name.to_string();
                        let tables = self.tables.borrow();
                        let any_of = if tables.entry("items", &name).is_some() { vec![name.clone()] } else { tables.having("items", &name) };
                        drop(tables);
                        out.push(RecipePart { look: self.item_look_of("item_look", &name).unwrap_or_default(), name, qty, any_of });
                    }
                    Ok(out)
                };
                made.push(RecipeParts {
                    skill: skill.to_string(),
                    look: self.item_look_of("recipe_look", &p).unwrap_or_default(),
                    makes: num("makes").max(0.0) as u32,
                    item: text("item"),
                    takes: parts("takes")?,
                    tools: parts("tools")?,
                    at: text("at"),
                    lit: m.get("lit").and_then(|v| v.as_bool().ok()).unwrap_or(false),
                    fuel: num("fuel") as f32,
                    knows: text("knows"),
                    ms: num("ms").max(0.0) as u64,
                    product: p,
                });
            }
            out.insert(skill.to_string(), made);
        }
        Ok(out)
    }

    /// How an item looks in a client (`item_look`), or what a recipe makes (`recipe_look`: its
    /// product's look under the recipe's own `icon` and `label`). None when the script has no
    /// such function or it fails (a script from before 2026-11-11's looks).
    pub fn item_look_of(&self, f: &str, name: &str) -> Option<ItemLook> {
        if !self.has(f) {
            return None;
        }
        let m = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (name.to_string(),)).ok()?.try_cast::<Map>()?;
        let text = |k: &str| m.get(k).and_then(|v| v.clone().into_string().ok()).unwrap_or_default();
        Some(ItemLook { icon: text("icon"), label: text("label"), group: text("group") })
    }

    /// A yes-or-no law of one name (`fire_kind("hearth")`); false when the script has none, it
    /// fails or it is not a yes or no.
    pub fn yes_of(&self, f: &str, arg: &str) -> bool {
        self.unary.contains(f) && self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (arg.to_string(),)).ok().and_then(|d| d.as_bool().ok()).unwrap_or(false)
    }

    /// A yes-or-no law of a context (`theft(a)`); false when the script has none or it fails.
    pub fn holds(&self, f: &str, ctx: &SkillCtx) -> bool {
        self.has(f) && self.call(f, ctx).ok().and_then(|d| d.as_bool().ok()).unwrap_or(false)
    }

    /// Whether a skill's rules read a field of the actor (its check, duration or effects), so the
    /// engine works it out only for skills that read it (`pasture`).
    pub fn skill_reads_actor(&self, skill: &str, field: &str) -> bool {
        let Some(i) = context::ACTOR.iter().position(|f| *f == field) else { return false };
        ["_check", "_duration", "_done"].iter().any(|p| {
            let f = format!("{skill}{p}");
            self.has(&f) && self.plan(&f).actor & (1 << i) != 0
        })
    }

    /// What each law is (`<law>_law()`), read once here.
    fn read_laws(&self) -> Result<std::collections::BTreeMap<String, LawSpec>, String> {
        let mut out = std::collections::BTreeMap::new();
        for f in self.nullary.iter().filter(|f| f.ends_with("_law")) {
            let law = f.trim_end_matches("_law");
            if law.is_empty() {
                continue;
            }
            // A description built from laws that fail is refused by an install, after the laws
            // themselves are checked (their own failure says more).
            let m = match self.law_map(f) {
                Ok(m) => m,
                Err(e) => {
                    self.law_errors.borrow_mut().push(e);
                    continue;
                }
            };
            if let Some(k) = m.keys().find(|k| !LAW_TRAITS.contains(&k.as_str())) {
                return Err(format!("{f}: unknown trait `{k}` (traits are {})", LAW_TRAITS.join(", ")));
            }
            let text = |k: &str| m.get(k).map_or(Ok(String::new()), |v| v.clone().into_string().map_err(|_| format!("{f}: `{k}` must be a string")));
            let about = self.timed_words(f, &text("about")?)?;
            if about.trim().is_empty() {
                return Err(format!("{f}: `about` says what the law is, for a mind (in the world's units: one tile is one metre)"));
            }
            let cadence = Cadence::parse(&text("cadence")?).ok_or_else(|| format!("{f}: `cadence` is compile, event or hot"))?;
            let covers = match m.get("covers") {
                None => Vec::new(),
                Some(v) => v.clone().try_cast::<Array>().ok_or_else(|| format!("{f}: `covers` is a list of function names"))?.into_iter().map(|x| x.into_string().map_err(|_| format!("{f}: `covers` is a list of function names"))).collect::<Result<_, _>>()?,
            };
            out.insert(law.to_string(), LawSpec { name: law.to_string(), about, cadence, topic: text("topic")?, covers });
        }
        Ok(out)
    }

    /// A law's words with each `{windup:<skill>}` replaced by that combat skill's windup as the
    /// skill cards show it (`timing`, a person's), so a description follows the laws in force
    /// (a law changed on a running world installs the script again). A token naming no timed
    /// skill is refused at install.
    fn timed_words(&self, f: &str, about: &str) -> Result<String, String> {
        let mut out = String::new();
        let mut rest = about;
        while let Some(i) = rest.find("{windup:") {
            out.push_str(&rest[..i]);
            let tail = &rest[i + "{windup:".len()..];
            let end = tail.find('}').ok_or_else(|| format!("{f}: an unclosed `{{windup:` in `about`"))?;
            let skill = &tail[..end];
            let t = self.timing(skill).filter(|t| t.windup_ms > 0).ok_or_else(|| format!("{f}: `{{windup:{skill}}}` names no combat skill with a windup"))?;
            out.push_str(&seconds(t.windup_ms));
            rest = &tail[end + 1..];
        }
        out.push_str(rest);
        Ok(out)
    }

    fn law_map(&self, f: &str) -> Result<Map, String> {
        self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, ()).map_err(|e| format!("{f}: {e}"))?.try_cast::<Map>().ok_or_else(|| format!("{f} must return a map"))
    }

    /// The farthest senses reach, from `senses_law()`.
    fn read_reach(&self) -> Result<Reach, String> {
        let m = self.law_map("senses_law")?;
        let r = m.get("reach").and_then(|r| r.clone().try_cast::<Map>()).ok_or("senses_law: `reach` is a map of day, night and hearing (metres)")?;
        let g = |k: &str| r.get(k).and_then(number).map(|v| (v as f32).clamp(0.0, 256.0)).ok_or_else(|| format!("senses_law: `reach.{k}` must be a number of metres"));
        // `glow` bounds the `glow` law, and is needed only with one.
        let glow = if self.has("glow") { g("glow").map_err(|e| format!("{e} (the script has a `glow` law)"))? } else { 0.0 };
        Ok(Reach { day: g("day")?, night: g("night")?, hearing: g("hearing")?, glow })
    }

    /// Every law the script declares, by name.
    pub fn law_specs(&self) -> &std::collections::BTreeMap<String, LawSpec> {
        &self.laws
    }

    /// What each world constant is (`laws_about(laws())`), by name: the script's words for the
    /// values in force. Empty when the script does not say.
    pub fn laws_about(&self) -> Vec<(String, String)> {
        if !self.has("laws_about") {
            return Vec::new();
        }
        let m = self.laws_map();
        let Ok(d) = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "laws_about", (m,)) else { return Vec::new() };
        d.try_cast::<Map>().unwrap_or_default().into_iter().map(|(k, v)| (k.to_string(), v.into_string().unwrap_or_default())).collect()
    }

    /// The world's rules as minds are told them, built from the laws' descriptions: one line per
    /// section of `world_topics()`, its laws' `about` in the order the source declares them.
    /// `world` gives the sections that are the world's own (`seasons`, `life`). It changes only
    /// when the script does, so a prompt's static prefix that holds it stays cached.
    pub fn world_text(&self, world: &[(&str, String)]) -> String {
        let topics: Vec<(String, String)> = if self.has("world_topics") {
            let a = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "world_topics", ()).ok().and_then(|d| d.try_cast::<Array>()).unwrap_or_default();
            a.into_iter()
                .filter_map(|p| {
                    let p = p.try_cast::<Array>()?;
                    Some((p.first()?.clone().into_string().ok()?, p.get(1)?.clone().into_string().ok()?))
                })
                .collect()
        } else {
            Vec::new()
        };
        let mut laws: Vec<&LawSpec> = self.laws.values().filter(|l| !l.topic.is_empty()).collect();
        laws.sort_by_key(|l| (self.source_at(&format!("fn {}_law(", l.name)), l.name.clone()));
        let mut lines = Vec::new();
        for (topic, heading) in &topics {
            let mut parts: Vec<String> = laws.iter().filter(|l| &l.topic == topic).map(|l| l.about.trim().to_string()).collect();
            if let Some((_, t)) = world.iter().find(|(k, _)| k == topic) {
                parts.push(t.trim().to_string());
            }
            // The ways of speaking, each in its own words and with its reach in metres (from its
            // spec and the world's hearing, as `speech_card` gives them), in their order.
            if topic == "speech" {
                parts.extend(self.ways.iter().map(|w| format!("{} ({}) = {}", w.name, w.reach_words(self.reach.hearing), w.about.trim())));
            }
            if parts.is_empty() {
                continue;
            }
            let body = parts.join(" ");
            lines.push(if heading.is_empty() { body } else { format!("{heading}: {body}") });
        }
        lines.join("\n")
    }

    /// Where a declaration starts in the script (for the source's order).
    fn source_at(&self, needle: &str) -> usize {
        self.source.find(needle).unwrap_or(usize::MAX)
    }

    /// The farthest anyone's senses reach.
    pub fn reach(&self) -> Reach {
        self.reach
    }

    /// Required laws this script lacks and runs with from the shipped script.
    pub fn borrowed(&self) -> &[String] {
        &self.borrowed
    }

    /// The fields of its context a law reads (the engine gathers only these for a hot law).
    pub fn law_plan(&self, f: &str) -> Rc<context::Plan> {
        self.plan(f)
    }

    /// A hot law's answer for a creature, kept per state: by the values of the fields the law
    /// reads, so creatures in the same state share one call.
    fn per_state<T: Copy>(&self, law: &str, memo: &RefCell<HashMap<Vec<u8>, T>>, ctx: &SkillCtx, ask: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
        let plan = self.plan(law);
        let mut key = Vec::with_capacity(16);
        context::key(ctx, "", &plan, &mut key);
        if let Some(v) = memo.borrow().get(&key) {
            return Ok(*v);
        }
        let v = ask()?;
        let mut m = memo.borrow_mut();
        if m.len() >= CREATURE_MEMO {
            m.clear();
        }
        m.insert(key, v);
        Ok(v)
    }

    /// A creature's senses (`senses(a)`), kept per state and held to the reach.
    pub fn senses(&self, ctx: &SkillCtx) -> Result<Senses, String> {
        self.per_state("senses", &self.senses, ctx, || self.senses_unshared(ctx))
    }

    /// How a creature moves (`motion(a)`), kept per state.
    pub fn moves(&self, ctx: &SkillCtx) -> Result<Moves, String> {
        self.per_state("motion", &self.moves, ctx, || self.moves_unshared(ctx))
    }

    /// The same, asking the law every time.
    #[doc(hidden)]
    pub fn moves_unshared(&self, ctx: &SkillCtx) -> Result<Moves, String> {
        decode_moves(self.call("motion", ctx)?)
    }

    /// Why a body walks slower than its pace (`slowed(a)`), in words its status and its mind
    /// share; empty when it is not, or the script has no such law.
    pub fn slowed(&self, ctx: &SkillCtx) -> String {
        if !self.has("slowed") {
            return String::new();
        }
        self.call("slowed", ctx).ok().and_then(|d| d.into_string().ok()).unwrap_or_default()
    }

    /// A creature's short pools (`pools(a)`), kept per state; the shipped numbers when the
    /// script has no such law. The engine finishes the cap and the refill for the body's
    /// tiredness (`crate::pools::PoolLaw::cap`, `regen`).
    pub fn pools(&self, ctx: &SkillCtx) -> Result<crate::pools::Pools, String> {
        if !self.has("pools") {
            return Ok(crate::pools::Pools::default());
        }
        self.per_state("pools", &self.pools, ctx, || decode_pools(self.call("pools", ctx)?))
    }

    /// The same, asking the law every time (benchmarks and install checks).
    #[doc(hidden)]
    pub fn senses_unshared(&self, ctx: &SkillCtx) -> Result<Senses, String> {
        let m = context::map(ctx, "", &self.plan("senses"));
        let d = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "senses", (m,)).map_err(|e| format!("senses: {e}"))?;
        decode_senses(d, &self.reach, ctx.dark)
    }

    /// How far a creature is seen from by a light on it (`glow(a)`, kept per state like
    /// senses; 0 when the script has no such law): an onlooker sees it within the wider of its
    /// own sight and this.
    pub fn glow(&self, ctx: &SkillCtx) -> Result<f32, String> {
        if !self.has("glow") {
            return Ok(0.0);
        }
        self.per_state("glow", &self.glows, ctx, || self.glow_unshared(ctx))
    }

    /// The same, asking the law every time.
    #[doc(hidden)]
    pub fn glow_unshared(&self, ctx: &SkillCtx) -> Result<f32, String> {
        decode_glow(self.call("glow", ctx)?, &self.reach)
    }

    /// The length of this world's game hour, in real milliseconds (its day over 24).
    pub fn hour_ms(&self) -> f64 {
        self.hour_ms
    }

    /// How light it is at `hour` (0..24): the `daylight(hour)` law, 0 (night) to 1 (day), read
    /// once per game minute of the day and kept for the script revision, so asking it costs a
    /// lookup. A script without the law has the shipped day: light from 06:00 to 20:00.
    pub fn daylight(&self, hour: f32) -> f32 {
        let minute = ((hour.rem_euclid(24.0) * 60.0) as usize).min(DAY_MINUTES - 1);
        if let Some(v) = self.daylight.borrow().get(minute).copied().filter(|v| !v.is_nan()) {
            return v;
        }
        let h = minute as f64 / 60.0;
        let v = if self.has("daylight") {
            self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "daylight", (h,)).ok().and_then(|d| number(&d)).map(|v| (v as f32).clamp(0.0, 1.0))
        } else {
            None
        }
        .unwrap_or(if (6.0..20.0).contains(&h) { 1.0 } else { 0.0 });
        let mut t = self.daylight.borrow_mut();
        if t.is_empty() {
            t.resize(DAY_MINUTES, f32::NAN);
        }
        t[minute] = v;
        v
    }

    /// A species' life table under the world's rules: the `life_years(t)` law, given the
    /// species' table in years (`kind`, `lifespan`, and the ages `infant`, `child`, `elder` and
    /// `old_age` where those stages end or begin, `gestation`, `interbirth`), returns it with any
    /// of them changed. An age it leaves alone keeps its years under a new lifespan. A script
    /// without the law (the shipped one) has the species' table exactly as `species.json` gives
    /// it. Read once per species and kept for the script revision; a table the law gets wrong
    /// (an install refuses it: `life_law`) leaves the species' own.
    pub fn life(&self, kind: &str, base: crate::life::Life) -> crate::life::Life {
        if !self.has("life_years") {
            return base;
        }
        if let Some(l) = self.lives.borrow().get(kind) {
            return *l;
        }
        let l = self.life_law(kind, base).unwrap_or(base);
        self.lives.borrow_mut().insert(kind.to_string(), l);
        l
    }

    /// The `life_years` law's table for a species, or what is wrong with it.
    pub fn life_law(&self, kind: &str, base: crate::life::Life) -> Result<crate::life::Life, String> {
        if !self.has("life_years") {
            return Ok(base);
        }
        let y = base.years as f64;
        let ages = [("infant", base.infant), ("child", base.child), ("elder", base.elder), ("old_age", base.old_age), ("gestation", base.gestation), ("interbirth", base.interbirth)];
        let mut t = rhai::Map::new();
        t.insert("kind".into(), Dynamic::from(kind.to_string()));
        t.insert("lifespan".into(), Dynamic::from_float(y));
        for (k, f) in ages {
            t.insert(k.into(), Dynamic::from_float(f as f64 * y));
        }
        let out = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "life_years", (t.clone(),)).map_err(|e| format!("life_years: {e}"))?;
        let out = out.try_cast::<rhai::Map>().ok_or("life_years must return the table it is given (a map)")?;
        let get = |k: &str| -> Result<f64, String> { out.get(k).map(|d| number(d).ok_or(format!("life_years: {k} must be a number of years"))).unwrap_or_else(|| Ok(number(&t[k]).unwrap_or(0.0))) };
        let span = get("lifespan")?;
        if !(span > 0.0) {
            return Err(format!("life_years: {kind}'s lifespan must be more than 0 years, not {span}"));
        }
        let mut l = base;
        l.years = span as f32;
        let mut last = 0.0;
        for (k, f) in ages {
            let given = get(k)?;
            // An age left as it was keeps its fraction when the lifespan is the same (no rounding).
            let frac = if given == f as f64 * y && span == y { f } else { (given / span) as f32 };
            match k {
                "infant" => l.infant = frac,
                "child" => l.child = frac,
                "elder" => l.elder = frac,
                "old_age" => l.old_age = frac,
                "gestation" => l.gestation = frac,
                _ => l.interbirth = frac,
            }
            if matches!(k, "infant" | "child" | "elder" | "old_age") {
                if given < last || given > span {
                    return Err(format!("life_years: {kind}'s ages must run infant <= child <= elder <= old_age <= lifespan ({span}); {k} is {given}"));
                }
                last = given;
            }
        }
        Ok(l)
    }

    /// How dark it is at `hour`, in the steps laws see it (`SkillCtx::dark`).
    pub fn dark(&self, hour: f32) -> f32 {
        ((1.0 - self.daylight(hour)) * 20.0).round() / 20.0
    }

    /// Whether it is night at `hour`: less than half light.
    pub fn is_night(&self, hour: f32) -> bool {
        self.daylight(hour) < 0.5
    }

    /// Whether `perceived_of` reads how far the target is (`p.dist`): only then does the engine
    /// give it the distance, and project a target again as it comes nearer or goes farther.
    pub fn regard_reads_dist(&self) -> bool {
        self.has("perceived_of") && self.fields.of("perceived_of", 1).and_then(|u| u.first()).is_none_or(|u| u.all || !u.by_param.is_empty() || u.keys.contains_key("dist"))
    }

    /// What others see of a skill and what it means to them (`<skill>_shows()`), read once
    /// here like the combat shapes.
    fn read_shows(&self) -> Result<crate::social::Shows, String> {
        let mut shows = std::collections::BTreeMap::new();
        for f in self.fns.iter().filter(|f| f.ends_with("_shows")) {
            let skill = f.trim_end_matches("_shows");
            if skill.is_empty() {
                continue;
            }
            let m = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, ()).map_err(|e| format!("{f}: {e}"))?.try_cast::<Map>().ok_or_else(|| format!("{f} must return a map"))?;
            if let Some(k) = m.keys().find(|k| !crate::social::TRAITS.contains(&k.as_str())) {
                return Err(format!("{f}: unknown trait `{k}` (traits are {})", crate::social::TRAITS.join(", ")));
            }
            let flag = |k: &str| m.get(k).map_or(Ok(false), |v| v.as_bool().map_err(|_| format!("{f}: `{k}` must be true or false")));
            let look = m.get("look").map_or(Ok(String::new()), |v| v.clone().into_string().map_err(|_| format!("{f}: `look` must be a string")))?;
            if look.is_empty() {
                return Err(format!("{f}: `look` names how it looks (e.g. \"gesture\", \"work\", \"sleep\")"));
            }
            let aside = flag("aside")?;
            if aside && !self.has(&format!("{skill}_dist")) {
                return Err(format!("{f}: a skill that steps aside needs `{skill}_dist(kind)`"));
            }
            let turn = flag("turn")?;
            if turn && !flag("faces")? {
                return Err(format!("{f}: a skill that is only a turn must face its target (`faces: true`)"));
            }
            shows.insert(skill.to_string(), crate::social::Show { code: 0, look, faces: flag("faces")?, turn, aside, record: flag("record")? });
        }
        Ok(crate::social::Shows::new(shows))
    }

    /// What others see of each skill that declares it.
    pub fn shows(&self) -> &crate::social::Shows {
        &self.shows
    }

    /// What each combat skill is, and the skill bar.
    pub fn shapes(&self) -> &crate::combat::Shapes {
        &self.shapes
    }

    /// Replace the presentation codes with the authority's stable ones (combat skills, shown
    /// skills).
    pub fn set_codes(&mut self, combat: &std::collections::BTreeMap<String, u8>, shown: &std::collections::BTreeMap<String, u8>) {
        self.shapes.set_codes(combat);
        self.shows.set_codes(shown);
    }

    /// A combat skill's shape (None for any other skill).
    pub fn combat(&self, skill: &str) -> Option<&crate::combat::Shape> {
        self.shapes.get(skill)
    }

    pub fn has(&self, f: &str) -> bool {
        self.fns.contains(f)
    }

    fn call(&self, f: &str, ctx: &SkillCtx) -> Result<Dynamic, String> {
        let m = context::map(ctx, self.shapes.knack(&ctx.skill), &self.plan(f));
        self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (m,)).map_err(|e| format!("{f}: {e}"))
    }

    pub fn check(&self, skill: &str, ctx: &SkillCtx) -> Result<(), String> {
        let f = format!("{skill}_check");
        if !self.has(&f) {
            return Ok(());
        }
        let r = self.call(&f, ctx)?;
        let s = r.into_string().map_err(|t| format!("{f} must return a string, got {t}"))?;
        if s.is_empty() {
            Ok(())
        } else {
            Err(s)
        }
    }

    pub fn duration_ms(&self, skill: &str, ctx: &SkillCtx) -> Result<u64, String> {
        let f = format!("{skill}_duration");
        if !self.has(&f) {
            return Ok(1_000);
        }
        let v = number(&self.call(&f, ctx)?).ok_or_else(|| format!("{f} must return a number"))?;
        // A knack and practice make skilled work quicker.
        // Combat moves are not: their timing is the other side's chance to react, so skill
        // makes them hit harder (in the scripts), not faster.
        let paced = crate::genes::is_skilled(skill) && !self.shapes.timed(skill);
        let v = if paced { v / crate::genes::skill_factor(&ctx.actor.genes, &ctx.actor.practice, skill, self.shapes.knack(skill)) as f64 } else { v };
        Ok(v.clamp(0.0, 600_000.0) as u64)
    }

    pub fn done(&self, skill: &str, ctx: &SkillCtx) -> Result<Vec<Effect>, String> {
        self.effects(&format!("{skill}_done"), ctx)
    }

    /// What a skill's missile does to the creature it strikes (`<skill>_hit(a)`, with that
    /// creature as the target).
    pub fn hit(&self, skill: &str, ctx: &SkillCtx) -> Result<Vec<Effect>, String> {
        self.effects(&format!("{skill}_hit"), ctx)
    }

    /// A combat skill's timing as a person has it (`skill_card`'s numbers, and the minds' skill
    /// reference): its windup (`<skill>_duration`; none for a dash or a guard), recovery
    /// (`combat_recover`), cooldown (`combat_cooldown`), a guard's hold and a missile's speed.
    pub fn timing(&self, skill: &str) -> Option<crate::combat::Timing> {
        use crate::combat::Aim;
        let shape = self.shapes().get(skill)?;
        let c = SkillCtx { actor: ActorFacts { kind: "person".into(), ..Default::default() }, skill: skill.to_string(), qty: shape.hold_ms, ..Default::default() };
        let windup_ms = if matches!(shape.aim, Aim::Dash | Aim::Facing) { 0 } else { self.duration_ms(skill, &c).unwrap_or(0) as u32 };
        let speed = if shape.missile { self.missile(skill, &c).map_or(0.0, |m| m.speed) } else { 0.0 };
        Some(crate::combat::Timing {
            aim: shape.aim,
            windup_ms,
            recover_ms: self.num_of("combat_recover", skill, 0.0) as u32,
            cooldown_ms: self.num_of("combat_cooldown", skill, 0.0) as u32,
            hold_ms: if shape.aim == Aim::Facing { shape.hold_ms } else { 0 },
            speed,
        })
    }

    /// A skill's missile (`<skill>_missile(a)`: a map of speed, range and radius).
    pub fn missile(&self, skill: &str, ctx: &SkillCtx) -> Result<crate::combat::MissileSpec, String> {
        let f = format!("{skill}_missile");
        if !self.has(&f) {
            return Err(format!("{skill} has no missile"));
        }
        decode_missile(&f, self.call(&f, ctx)?)
    }

    /// What the rules make of an event (`on_<event>(a)`: `on_give`, `on_store`, `on_host` after
    /// that skill was done, `on_expire` when a record falls due, `on_death`): effects on records,
    /// and what is told and seen. None when the script has no such hook.
    pub fn hook(&self, event: &str, ctx: &SkillCtx) -> Result<Vec<Effect>, String> {
        let f = format!("on_{event}");
        let fx = self.effects(&f, ctx)?;
        if let Some(e) = fx.iter().find(|e| !e.of_a_hook()) {
            return Err(format!("{f}: a hook only makes, amends and closes records, tells and is seen ({e:?} is not one of these)"));
        }
        Ok(fx)
    }

    /// How a party reads one of its records (`record_text(r)`), for minds and players. None
    /// when the script does not say.
    pub fn record_text(&self, r: &crate::records::RecordFacts) -> Option<String> {
        if !self.has("record_text") {
            return None;
        }
        self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "record_text", (context::record_map(r),)).ok()?.into_string().ok()
    }

    /// Whether the script has a hook for an event.
    pub fn has_hook(&self, event: &str) -> bool {
        self.unary.contains(&format!("on_{event}"))
    }

    /// Whether a function reads a top-level field of its context (`records`, `record`), so the
    /// engine fills it only for laws that read it.
    pub fn reads(&self, f: &str, field: &str) -> bool {
        if !self.has(f) {
            return false;
        }
        let i = context::TOP.iter().position(|t| *t == field).expect("a top-level field");
        self.plan(f).top & (1 << i) != 0
    }

    /// Whether a skill's rules read the actor's records: on its way (`performing` false) its
    /// check and duration; once performed, its check, effects and hook too.
    pub fn skill_reads_records(&self, skill: &str, performing: bool) -> bool {
        self.skill_reads(skill, "records", performing)
    }

    /// Whether a skill's rules read a top-level field of the context (`records`, `offer`): on its
    /// way its check and duration; once performed, its check, effects and hook too.
    pub fn skill_reads(&self, skill: &str, field: &str, performing: bool) -> bool {
        let parts: &[&str] = if performing { &["_check", "_duration", "_done"] } else { &["_check", "_duration"] };
        parts.iter().any(|p| self.reads(&format!("{skill}{p}"), field)) || (performing && self.reads(&format!("on_{skill}"), field))
    }

    fn effects(&self, f: &str, ctx: &SkillCtx) -> Result<Vec<Effect>, String> {
        if !self.has(f) {
            return Ok(Vec::new());
        }
        decode_effects(f, self.call(f, ctx)?)
    }

    /// The actor's need rates: `rates(a)` for its state (shared by every body in the same
    /// state), finished for its own levels and genes.
    pub fn rates(&self, ctx: &SkillCtx) -> Result<Rates, String> {
        Ok(self.need_law(ctx)?.rates(&ctx.actor))
    }

    /// The same rates, asking the law every time (benchmarks: what one call of the law costs).
    #[doc(hidden)]
    pub fn rates_unshared(&self, ctx: &SkillCtx) -> Result<Rates, String> {
        let m = context::map(ctx, self.shapes.knack(&ctx.skill), &self.plan("rates"));
        let d = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "rates", (m,)).map_err(|e| format!("rates: {e}"))?;
        Ok(NeedLaw::from_dynamic(d, self.hour_ms)?.rates(&ctx.actor))
    }

    /// Whether `rates(a)`'s answer for the actor's state is already kept, so [`Self::need_law`]
    /// will not ask the law (for profiling how often the law itself runs).
    pub fn need_law_kept(&self, ctx: &SkillCtx) -> bool {
        let mut key = Vec::with_capacity(64);
        context::key(ctx, self.shapes.knack(&ctx.skill), &self.plan("rates"), &mut key);
        self.needs.borrow().contains_key(&key)
    }

    /// What `rates(a)` says for the actor's state.
    pub fn need_law(&self, ctx: &SkillCtx) -> Result<NeedLaw, String> {
        let plan = self.plan("rates");
        let mut key = Vec::with_capacity(64);
        context::key(ctx, self.shapes.knack(&ctx.skill), &plan, &mut key);
        if let Some(l) = self.needs.borrow().get(&key) {
            return Ok(l.clone());
        }
        let m = context::map(ctx, self.shapes.knack(&ctx.skill), &plan);
        let law = NeedLaw::from_dynamic(self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "rates", (m,)).map_err(|e| format!("rates: {e}"))?, self.hour_ms)?;
        let mut memo = self.needs.borrow_mut();
        if memo.len() >= NEEDS_MEMO {
            memo.clear();
        }
        memo.insert(key, law.clone());
        Ok(law)
    }

    pub fn body_state(&self, ctx: &SkillCtx) -> Result<BodyState, String> {
        decode_body(self.call("body_state", ctx)?)
    }

    pub fn move_speed(&self, ctx: &SkillCtx) -> Result<f32, String> {
        let v = number(&self.call("move_speed", ctx)?).ok_or("move_speed must return a number")?;
        Ok((v as f32).clamp(0.2, 12.0))
    }

    /// The world constants (`laws()`).
    pub fn laws(&self) -> Laws {
        self.laws_with(&[]).unwrap_or_default()
    }

    /// The names of the world constants (`laws()`'s keys).
    pub fn law_names(&self) -> Vec<String> {
        self.laws_map().keys().map(|k| k.to_string()).collect()
    }

    /// `laws()`, with the world's own values over it (`world_law_values()`, the block
    /// [`with_world_laws`] writes at the end of a world's script; a key that is not a law, or of
    /// another kind, is left out).
    fn laws_map(&self) -> Map {
        if !self.has("laws") {
            return Map::new();
        }
        let mut m = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "laws", ()).ok().and_then(|d| d.try_cast::<Map>()).unwrap_or_default();
        if self.has(WORLD_LAW_VALUES) {
            let over = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, WORLD_LAW_VALUES, ()).ok().and_then(|d| d.try_cast::<Map>()).unwrap_or_default();
            for (k, v) in over {
                let fits = m.get(&k).is_some_and(|cur| cur.is_bool() == v.is_bool() && (cur.is_bool() || number(&v).is_some()));
                if fits {
                    let v = if v.is_bool() { v } else { Dynamic::from(number(&v).unwrap_or(0.0)) };
                    m.insert(k, v);
                }
            }
        }
        m
    }

    /// What a creature of `kind` sounds like to a listener who cannot see it (`heard_as(kind)`):
    /// "person", "deer", "wolf", or "creature" where the rules cannot tell. Without the law,
    /// those three kinds by name and "creature" for any other.
    pub fn heard_as(&self, kind: &str) -> String {
        if self.has("heard_as") {
            if let Ok(d) = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "heard_as", (kind.to_string(),)) {
                if let Ok(s) = d.into_string() {
                    if !s.is_empty() {
                        return s;
                    }
                }
            }
        }
        if matches!(kind, "person" | "deer" | "wolf") { kind.to_string() } else { "creature".to_string() }
    }

    /// The world constants in force, as the script's laws read them (`law(name)`).
    pub fn law_value(&self, name: &str) -> Option<serde_json::Value> {
        let t = self.tables.borrow();
        let v = t.laws.get(name)?;
        if let Ok(b) = v.as_bool() {
            return Some(serde_json::Value::Bool(b));
        }
        number(v).and_then(serde_json::Number::from_f64).map(serde_json::Value::Number)
    }

    /// The world constants with a world's own values over the script's (a seed's `rules`: a
    /// number or true/false by law name). A name that is not a law, or a value of another
    /// kind than the law's, is refused.
    pub fn laws_with(&self, over: &[(String, serde_json::Value)]) -> Result<Laws, String> {
        let mut m = self.laws_map();
        for (k, v) in over {
            let Some(cur) = m.get(k.as_str()) else {
                let mut names: Vec<String> = m.keys().map(|k| k.to_string()).collect();
                names.sort();
                return Err(format!("`{k}` is not a law of this world (laws are {})", names.join(", ")));
            };
            let d = match v {
                serde_json::Value::Bool(b) if cur.is_bool() => Dynamic::from(*b),
                serde_json::Value::Number(n) if number(cur).is_some() => Dynamic::from(n.as_f64().unwrap_or(0.0)),
                _ => return Err(format!("law `{k}` takes {}, not {v}", if cur.is_bool() { "true or false" } else { "a number" })),
            };
            m.insert(k.as_str().into(), d);
        }
        let l = Laws::default();
        let g = |k: &str, d: f32| m.get(k).and_then(number).map(|v| v as f32).unwrap_or(d);
        let flag = |k: &str, d: bool| m.get(k).and_then(|v| v.as_bool().ok()).unwrap_or(d);
        let l = Laws {
            fire_warmth: g("fire_warmth", l.fire_warmth),
            shelter_warmth: g("shelter_warmth", l.shelter_warmth),
            gestation_days: g("gestation_days", l.gestation_days),
            bond_window_s: g("bond_window_s", l.bond_window_s),
            crowd: g("crowd", l.crowd),
            danger_near: g("danger_near", l.danger_near),
            danger_far: g("danger_far", l.danger_far),
            repeat_failure_s: g("repeat_failure_s", l.repeat_failure_s),
            force_outcomes: flag("force_outcomes", l.force_outcomes),
            road_speed: g("road_speed", l.road_speed),
            slow_radius: g("slow_radius", l.slow_radius).clamp(0.0, 8.0),
            corner_radius: g("corner_radius", l.corner_radius).clamp(0.0, 4.0),
            steer_s: g("steer_s", l.steer_s).clamp(0.1, 10.0),
            crowd_hz: g("crowd_hz", l.crowd_hz).clamp(0.5, 30.0),
            chase_hz: g("chase_hz", l.chase_hz).clamp(0.5, 30.0),
            combat_hz: g("combat_hz", l.combat_hz).clamp(0.5, 30.0),
            scent_hz: g("scent_hz", l.scent_hz).clamp(0.1, 60.0),
            input_hz: g("input_hz", l.input_hz).clamp(1.0, 120.0),
            input_burst: g("input_burst", l.input_burst).clamp(1.0, 240.0),
            // Per game hour (`pasture_regen_per_h`), or per real minute in a script that still
            // writes `pasture_regen`; the engine keeps it per real minute.
            pasture_regen: if m.contains_key("pasture_regen") || !m.contains_key("pasture_regen_per_h") { g("pasture_regen", l.pasture_regen) } else { m.get("pasture_regen_per_h").and_then(number).map_or(l.pasture_regen, |v| (v * self.per_minute()) as f32) }.clamp(0.0, 1.0),
            alone_within: g("alone_within", l.alone_within).clamp(0.0, 40.0),
            face_slack: g("face_slack", l.face_slack).clamp(0.0, 3.0),
            flee_clear: g("flee_clear", l.flee_clear).clamp(1.0, 60.0),
            takeover_s: g("takeover_s", l.takeover_s).clamp(0.0, 3_600.0),
            follow_s: g("follow_s", l.follow_s).clamp(0.5, 600.0),
            read_sign_m: g("read_sign_m", l.read_sign_m).clamp(0.0, 64.0),
            kin_near_m: g("kin_near_m", l.kin_near_m).clamp(0.0, 32.0),
            trade_window_s: g("trade_window_s", l.trade_window_s).clamp(1.0, 3_600.0),
            join_window_s: g("join_window_s", l.join_window_s).clamp(1.0, 7_200.0),
            address_m: g("address_m", l.address_m).clamp(0.0, 64.0),
            keep_seen_m: g("keep_seen_m", l.keep_seen_m).clamp(0.0, 8.0),
            chase_lost_share: g("chase_lost_share", l.chase_lost_share).clamp(1.0, 8.0),
            spawn_hunger: g("spawn_hunger", l.spawn_hunger).clamp(0.0, 100.0),
            spawn_energy: g("spawn_energy", l.spawn_energy).clamp(0.0, 100.0),
            pasture_per_tile: g("pasture_per_tile", l.pasture_per_tile).clamp(0.0, 10.0),
            cry_prompts_carers: flag("cry_prompts_carers", l.cry_prompts_carers),
            speech_audience: flag("speech_audience", l.speech_audience),
            speech_truth: flag("speech_truth", l.speech_truth),
            longing_after_min: g("longing_after_min", l.longing_after_min).clamp(0.0, 100_000.0),
            longing_food: g("longing_food", l.longing_food).clamp(0.0, 1_000.0),
            fov_on: flag("fov_on", l.fov_on),
            heard_near_m: g("heard_near_m", l.heard_near_m).clamp(0.0, 256.0),
            heard_close_m: g("heard_close_m", l.heard_close_m).clamp(0.0, 256.0),
            heard_linger_s: g("heard_linger_s", l.heard_linger_s).clamp(0.0, 60.0),
            look_slack_deg: g("look_slack_deg", l.look_slack_deg).clamp(0.0, 90.0),
            look_walk_deg: g("look_walk_deg", l.look_walk_deg).clamp(0.0, 180.0),
        };
        Ok(l)
    }

    /// What an observer perceives of a target (`perceived_of(p)`, docs/PERCEPTION.md): which
    /// fields it gets and how precisely. The answer depends only on [`RegardIn`], so callers
    /// cache it by that value; without the law the defaults of [`Regard::default_for`] hold.
    pub fn perceived_of(&self, p: &RegardIn) -> Regard {
        if !self.has("perceived_of") {
            return Regard::default_for(p);
        }
        let Ok(r) = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "perceived_of", (regard_map(p),)) else { return Regard::default_for(p) };
        decode_regard(r, p).unwrap_or_else(|_| Regard::default_for(p))
    }

    /// Numeric function of one string argument, e.g. `max_hp("deer")`. A function of a name
    /// depends on nothing else, so each answer is read once and kept (the names the engine
    /// asks are all read when the script compiles).
    pub fn num_of(&self, f: &str, arg: &str, default: f64) -> f64 {
        if let Some(v) = self.names.borrow().get(f).and_then(|t| t.get(arg)) {
            return v.unwrap_or(default);
        }
        if !self.has(f) {
            return default;
        }
        let v = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (arg.to_string(),)).ok().and_then(|d| number(&d));
        self.names.borrow_mut().entry(f.to_string()).or_default().insert(arg.to_string(), v);
        v.unwrap_or(default)
    }

    /// Game hours in a real minute on this world's day (2 on the shipped 12-minute day, ½ on a
    /// 48-minute one): what a rate written per game hour is multiplied by to be per real minute.
    pub fn per_minute(&self) -> f64 {
        60_000.0 / self.hour_ms
    }

    /// A rate of a name (spoiling of an item, regrowth of a resource) per real minute on this
    /// world's day. The script writes it per game hour in `per_h` (`spoil_per_h`); a script that
    /// still defines the real-minute law `per_min` (`spoil_rate`, every script before rates-2,
    /// or an overlay written in real time) is taken as it is. `default` is per real minute.
    pub fn per_real_minute(&self, per_h: &str, per_min: &str, arg: &str, default: f64) -> f64 {
        if !self.has(per_min) && self.has(per_h) {
            let v = self.num_of(per_h, arg, f64::NAN);
            return if v.is_nan() { default } else { v * self.per_minute() };
        }
        self.num_of(per_min, arg, default)
    }

    /// A duration of a name (how long remains lie, how often a trap catches) in real
    /// milliseconds on this world's day: written in game hours in `hours` (`remains_h`), or in
    /// real seconds in `seconds` (`remains_s`) by a script that still defines that law, which is
    /// taken as it is. `default_ms` is real milliseconds.
    pub fn real_ms(&self, hours: &str, seconds: &str, arg: &str, default_ms: f64) -> f64 {
        if !self.has(seconds) && self.has(hours) {
            let v = self.num_of(hours, arg, f64::NAN);
            return if v.is_nan() { default_ms } else { v * self.hour_ms };
        }
        self.num_of(seconds, arg, default_ms / 1000.0) * 1000.0
    }

    /// Share of an item that spoils in a real minute (`spoil_per_h`, a game hour's share).
    pub fn spoil_per_min(&self, item: &str) -> f64 {
        self.per_real_minute("spoil_per_h", "spoil_rate", item, 0.0)
    }

    /// Units a resource of a kind regrows in a real minute of growing time (`regrow_per_h`).
    pub fn regrow_per_min(&self, kind: &str, default: f64) -> f64 {
        self.per_real_minute("regrow_per_h", "regrow", kind, default)
    }

    /// Real milliseconds a creature's remains lie (`remains_h`, game hours).
    pub fn remains_ms(&self, kind: &str) -> f64 {
        self.real_ms("remains_h", "remains_s", kind, 1_800_000.0)
    }

    /// Real milliseconds between a trap's catches (`trap_every_h`, game hours).
    pub fn trap_every_ms(&self) -> f64 {
        self.real_ms("trap_every_h", "trap_every_s", "meat", 240_000.0)
    }

    /// Items a one-argument law gives as a map (`fn carcass(kind) { #{ meat: 5, hide: 1 } }`),
    /// with whole positive amounts; empty without the law or for anything else it returns.
    /// Cached by argument, like [`Self::num_of`].
    pub fn items_of(&self, f: &str, arg: &str) -> Vec<(String, u32)> {
        if let Some(v) = self.lists.borrow().get(f).and_then(|t| t.get(arg)) {
            return v.clone();
        }
        let mut out: Vec<(String, u32)> = Vec::new();
        if self.has(f) {
            if let Some(m) = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (arg.to_string(),)).ok().and_then(|d| d.try_cast::<rhai::Map>()) {
                for (k, v) in m {
                    if let Some(n) = number(&v).filter(|n| *n >= 1.0) {
                        out.push((k.to_string(), n as u32));
                    }
                }
            }
        }
        out.sort();
        self.lists.borrow_mut().entry(f.to_string()).or_default().insert(arg.to_string(), out.clone());
        out
    }

    /// What a skill takes and gives, as its spec says (`<skill>_spec()`), for minds composing
    /// routines. None when it says neither.
    pub fn skill_io(&self, skill: &str) -> Option<(String, String)> {
        let s = self.skills.get(skill)?;
        (!s.takes.is_empty() || !s.gives.is_empty()).then(|| (s.takes.clone(), s.gives.clone()))
    }

    /// Generic numeric query, e.g. `attack_cooldown`.
    pub fn number(&self, f: &str, ctx: &SkillCtx, default: f64) -> f64 {
        if !self.has(f) {
            return default;
        }
        self.call(f, ctx).ok().and_then(|d| number(&d)).unwrap_or(default)
    }
}

fn decode_moves(d: Dynamic) -> Result<Moves, String> {
    let m = d.try_cast::<Map>().ok_or("motion must return a map")?;
    let g = |k: &str, lo: f32, hi: f32| m.get(k).and_then(number).map(|v| (v as f32).clamp(lo, hi)).ok_or_else(|| format!("motion: `{k}` must be a number"));
    Ok(Moves {
        run: g("run", 1.0, 4.0)?,
        flee: g("flee", 0.5, 4.0)?,
        aside: g("aside", 0.2, 2.0)?,
        turn_rate: g("turn_rate", 0.5, 50.0)?,
        turn_slow: g("turn_slow", 0.05, 1.0)?,
        separation: g("separation", 0.0, 4.0)?,
        separation_weight: g("separation_weight", 0.0, 5.0)?,
        wander_turn: g("wander_turn", 0.0, std::f32::consts::PI)?,
        wander_keep_s: g("wander_keep_s", 0.0, 3_600.0)?,
        top: if m.contains_key("top") { g("top", 0.5, 50.0)? } else { f32::INFINITY },
        charge: match m.get("charge") {
            None => false,
            Some(v) => v.as_bool().map_err(|_| "motion: `charge` must be true or false".to_string())?,
        },
    })
}

/// `pools(a)`: `#{ stamina: #{ max, regen_per_s, delay_ms, run_per_s, guard_per_s, resume,
/// tires_per_point, rested_at, spent_share, exhausted_below, exhausted_regen }, focus: #{ max,
/// regen_per_s, delay_ms } }`; a field left out keeps the shipped number.
fn decode_pools(d: Dynamic) -> Result<crate::pools::Pools, String> {
    let m = d.try_cast::<Map>().ok_or("pools must return a map with stamina and focus")?;
    let base = crate::pools::Pools::default();
    let sub = |k: &str| -> Result<Map, String> { m.get(k).map(|v| v.clone().try_cast::<Map>().ok_or_else(|| format!("pools: `{k}` must be a map"))).unwrap_or_else(|| Ok(Map::new())) };
    let (st, fo) = (sub("stamina")?, sub("focus")?);
    let g = |m: &Map, k: &str, d: f32, lo: f32, hi: f32| -> Result<f32, String> {
        match m.get(k) {
            None => Ok(d),
            Some(v) => number(v).map(|v| (v as f32).clamp(lo, hi)).ok_or_else(|| format!("pools: `{k}` must be a number")),
        }
    };
    let pool = |m: &Map, b: crate::pools::PoolLaw| -> Result<crate::pools::PoolLaw, String> {
        Ok(crate::pools::PoolLaw {
            max: g(m, "max", b.max, 0.0, 10_000.0)?,
            regen_per_s: g(m, "regen_per_s", b.regen_per_s, 0.0, 10_000.0)?,
            delay_ms: g(m, "delay_ms", b.delay_ms as f32, 0.0, 600_000.0)? as u32,
            rested_at: g(m, "rested_at", b.rested_at, 0.0, 100.0)?,
            spent_share: g(m, "spent_share", b.spent_share, 0.0, 1.0)?,
            exhausted_below: g(m, "exhausted_below", b.exhausted_below, 0.0, 100.0)?,
            exhausted_regen: g(m, "exhausted_regen", b.exhausted_regen, 0.0, 10.0)?,
        })
    };
    // Focus does not depend on tiredness unless the law says so.
    let unbound = crate::pools::PoolLaw { rested_at: 0.0, spent_share: 1.0, exhausted_below: 0.0, exhausted_regen: 1.0, ..base.focus };
    Ok(crate::pools::Pools {
        stamina: pool(&st, base.stamina)?,
        breath: crate::pools::Breath {
            run_per_s: g(&st, "run_per_s", base.breath.run_per_s, 0.0, 10_000.0)?,
            guard_per_s: g(&st, "guard_per_s", base.breath.guard_per_s, 0.0, 10_000.0)?,
            resume: g(&st, "resume", base.breath.resume, 0.0, 10_000.0)?,
            tires_per_point: g(&st, "tires_per_point", base.breath.tires_per_point, 0.0, 10.0)?,
        },
        focus: pool(&fo, unbound)?,
    })
}

fn decode_senses(d: Dynamic, reach: &Reach, dark: f32) -> Result<Senses, String> {
    let m = d.try_cast::<Map>().ok_or("senses must return a map of sight and hearing")?;
    let g = |k: &str| m.get(k).and_then(number).map(|v| v as f32).ok_or_else(|| format!("senses: `{k}` must be a number of metres"));
    let field = match m.get("field") {
        None => None,
        Some(f) if f.is_unit() => None,
        Some(f) => {
            let f = f.clone().try_cast::<Map>().ok_or("senses: `field` is a map of focal_deg, side_deg, side_share, near_m and margin_deg")?;
            let n = |k: &str, lo: f32, hi: f32| f.get(k).and_then(number).map(|v| (v as f32).clamp(lo, hi)).ok_or_else(|| format!("senses: `field.{k}` must be a number"));
            let focal_deg = n("focal_deg", 0.0, 180.0)?;
            Some(Field { focal_deg, side_deg: n("side_deg", 0.0, 180.0)?.max(focal_deg), side_share: n("side_share", 0.0, 1.0)?, near_m: n("near_m", 0.0, 256.0)?, margin_deg: n("margin_deg", 0.0, 90.0)? })
        }
    };
    Ok(Senses { sight: g("sight")?.clamp(0.0, reach.sight(dark)), hearing: g("hearing")?.clamp(0.0, reach.hearing), field })
}

/// The function a world's own law values are written as at the end of its script.
pub const WORLD_LAW_VALUES: &str = "world_law_values";
/// The line that starts that block.
const WORLD_LAW_MARK: &str = "// ---- this world's own law values (written by the authority: a seed's `rules`, `set_world_law`) ----";

/// A world's script with its own law values written at its end as `world_law_values()`, which
/// the laws read through `law(name)` and the engine reads over `laws()`. Any earlier such block
/// is replaced; no values leave the script without one. Every client that compiles the
/// world's `script` row then has the values in force (docs/PERCEPTION.md, "Changing a law on a
/// running world").
pub fn with_world_laws(source: &str, values: &[(String, serde_json::Value)]) -> String {
    let base = match source.find(WORLD_LAW_MARK) {
        Some(i) => source[..i].trim_end_matches('\n'),
        None => source,
    };
    if values.is_empty() {
        return if base.len() == source.len() { source.to_string() } else { format!("{base}\n") };
    }
    let mut v: Vec<&(String, serde_json::Value)> = values.iter().collect();
    v.sort_by(|a, b| a.0.cmp(&b.0));
    let body: Vec<String> = v
        .iter()
        .filter(|(k, _)| !k.is_empty() && k.chars().all(|c| c.is_ascii_alphanumeric() || c == '_'))
        .map(|(k, val)| {
            let val = match val {
                serde_json::Value::Bool(b) => b.to_string(),
                serde_json::Value::Number(n) => {
                    let f = n.as_f64().unwrap_or(0.0);
                    if f.fract() == 0.0 && f.abs() < 1e15 { format!("{f:.1}") } else { format!("{f}") }
                }
                _ => "()".to_string(),
            };
            format!("{k}: {val}")
        })
        .collect();
    format!("{base}\n\n{WORLD_LAW_MARK}\nfn {WORLD_LAW_VALUES}() {{ #{{ {} }} }}\n", body.join(", "))
}

/// The script without a world's own law values (what was installed).
pub fn without_world_laws(source: &str) -> &str {
    match source.find(WORLD_LAW_MARK) {
        Some(i) => source[..i].trim_end_matches('\n'),
        None => source,
    }
}

fn decode_glow(d: Dynamic, reach: &Reach) -> Result<f32, String> {
    Ok((number(&d).ok_or("glow must return a number of metres")? as f32).clamp(0.0, reach.glow))
}

fn number(d: &Dynamic) -> Option<f64> {
    if let Ok(i) = d.as_int() {
        return Some(i as f64);
    }
    d.as_float().ok()
}

/// The traits a skill's spec may have.
pub const SPEC_TRAITS: &[&str] = &["target", "item", "args", "reach", "about", "takes", "gives", "listed", "talk", "items", "latch", "notable", "moving", "moment", "reflex", "target_class"];

/// A skill's spec from what `<skill>_spec()` returned.
/// A kind's `burns` trait: `#{ fuel: "<item trait>", rate: <units a game hour>, warmth: <m>,
/// light: <m>, holds: <units> }` (warmth, light and holds optional).
fn burns_of(kind: &str, v: &Dynamic) -> Result<Burns, String> {
    let m = v.clone().try_cast::<Map>().ok_or_else(|| format!("structures: `burns` of `{kind}` is a map (fuel, rate, warmth, light, holds)"))?;
    if let Some(x) = m.keys().find(|x| !["fuel", "rate", "warmth", "light", "holds"].contains(&x.as_str())) {
        return Err(format!("structures: unknown `burns` trait `{x}` of `{kind}` (they are fuel, rate, warmth, light, holds)"));
    }
    let fuel = m.get("fuel").and_then(|v| v.clone().into_string().ok()).filter(|f| !f.is_empty()).ok_or_else(|| format!("structures: `burns.fuel` of `{kind}` names the item trait it burns"))?;
    let rate = m.get("rate").and_then(number).filter(|r| *r > 0.0 && r.is_finite()).ok_or_else(|| format!("structures: `burns.rate` of `{kind}` is the fuel units it burns a game hour (> 0)"))? as f32;
    let metres = |x: &str| -> Result<f32, String> { m.get(x).map_or(Ok(0.0), |v| number(v).filter(|n| *n >= 0.0 && *n <= 64.0).map(|n| n as f32).ok_or_else(|| format!("structures: `burns.{x}` of `{kind}` is metres (0..64)"))) };
    let holds = match m.get("holds") {
        None => None,
        Some(v) => Some(number(v).filter(|n| *n > 0.0).ok_or_else(|| format!("structures: `burns.holds` of `{kind}` is the most units it holds (> 0)"))? as f32),
    };
    Ok(Burns { fuel, rate, warmth: metres("warmth")?, light: metres("light")?, holds })
}

fn spec_of(skill: &str, m: &Map) -> Result<crate::catalog::SkillSpec, String> {
    let f = format!("{skill}_spec");
    if let Some(k) = m.keys().find(|k| !SPEC_TRAITS.contains(&k.as_str())) {
        return Err(format!("{f}: unknown trait `{k}` (traits are {})", SPEC_TRAITS.join(", ")));
    }
    let flag = |k: &str, d: bool| m.get(k).map_or(Ok(d), |v| v.as_bool().map_err(|_| format!("{f}: `{k}` must be true or false")));
    let text = |k: &str| m.get(k).map_or(Ok(String::new()), |v| v.clone().into_string().map_err(|_| format!("{f}: `{k}` must be a string")));
    let list = |k: &str| -> Result<Vec<String>, String> {
        let Some(v) = m.get(k) else { return Ok(Vec::new()) };
        let a = v.clone().try_cast::<Array>().ok_or_else(|| format!("{f}: `{k}` must be a list of words"))?;
        a.into_iter().map(|x| x.into_string().map_err(|_| format!("{f}: `{k}` must be a list of words"))).collect()
    };
    // `item: true`, or a word for what the item names (`"technique"`).
    let (needs_item, item_arg) = match m.get("item") {
        None => (false, String::new()),
        Some(v) if v.is_bool() => (v.as_bool().unwrap_or(false), String::new()),
        Some(v) => (true, v.clone().into_string().map_err(|_| format!("{f}: `item` is true, false or what the item names"))?),
    };
    let about = text("about")?;
    if about.trim().is_empty() {
        return Err(format!("{f}: `about` describes the skill for a mind: what it does, when it is useful, what it is not"));
    }
    let reach = m.get("reach").map_or(Ok(0.0), |v| number(v).ok_or_else(|| format!("{f}: `reach` must be a number")))?;
    // What the target may be: a class or a list of them.
    let target_class = match m.get("target_class") {
        None => Vec::new(),
        Some(v) if v.is_string() => vec![v.clone().into_string().unwrap_or_default()],
        Some(_) => list("target_class")?,
    };
    let classes = crate::catalog::TARGET_CLASSES;
    if let Some(c) = target_class.iter().find(|c| !classes.contains(&c.as_str())) {
        return Err(format!("{f}: `target_class` '{c}' is not a target class ({})", classes.join(", ")));
    }
    if !target_class.is_empty() && !flag("target", false)? {
        return Err(format!("{f}: `target_class` needs `target: true`"));
    }
    Ok(crate::catalog::SkillSpec {
        name: skill.to_string(),
        needs_target: flag("target", false)?,
        needs_item,
        item_arg,
        args: list("args")?,
        reach: (reach as f32).clamp(0.0, 64.0),
        about,
        takes: text("takes")?,
        gives: text("gives")?,
        listed: flag("listed", true)?,
        talk: flag("talk", false)?,
        items: list("items")?,
        latch: flag("latch", false)?,
        notable: flag("notable", false)?,
        moving: flag("moving", false)?,
        moment: flag("moment", false)?,
        reflex: flag("reflex", false)?,
        target_class,
    })
}

/// Milliseconds as a mind reads them: "0.65 s", "1 s", "1.5 s".
fn seconds(ms: u32) -> String {
    let s = format!("{:.2}", ms as f64 / 1000.0);
    format!("{} s", s.trim_end_matches('0').trim_end_matches('.'))
}

fn decode_missile(f: &str, d: Dynamic) -> Result<crate::combat::MissileSpec, String> {
    let m = d.try_cast::<Map>().ok_or_else(|| format!("{f} must return a map"))?;
    let g = |k: &str| m.get(k).and_then(number).map(|v| v as f32).ok_or_else(|| format!("{f} missing {k}"));
    Ok(crate::combat::MissileSpec { speed: g("speed")?.clamp(1.0, 120.0), range: g("range")?.clamp(0.5, 80.0), radius: g("radius")?.clamp(0.05, 3.0) })
}

fn decode_effects(f: &str, d: Dynamic) -> Result<Vec<Effect>, String> {
    let arr: Array = d.try_cast::<Array>().ok_or_else(|| format!("{f} must return an array"))?;
    arr.into_iter().map(effect).collect()
}

impl NeedLaw {
    /// Decode what `rates(a)` returned, in a world whose game hour lasts `hour_ms` real
    /// milliseconds (its `per` says whether the law writes per game hour or per real minute).
    pub fn from_dynamic(d: Dynamic, hour_ms: f64) -> Result<NeedLaw, String> {
        let m = d.try_cast::<Map>().ok_or("rates must return a map")?;
        let per_min = match m.get("per").map(|v| v.clone().into_string()) {
            None => 1.0,
            Some(Ok(u)) if u == "minute" => 1.0,
            Some(Ok(u)) if u == "hour" => 60_000.0 / hour_ms.max(1.0),
            Some(_) => return Err("rates: `per` is \"hour\" (a game hour) or \"minute\" (a real minute)".into()),
        };
        if !m.contains_key("starving_at") {
            let g = |k: &str| (m.get(k).and_then(number).unwrap_or(0.0) * per_min) as f32;
            return Ok(NeedLaw::Final(Rates { hunger_per_min: g("hunger"), energy_per_min: g("energy"), hp_per_min: g("hp") }));
        }
        let n = |k: &str| m.get(k).and_then(number).ok_or_else(|| format!("rates: `{k}` must be a number"));
        let gene = |k: &str| m.get(k).and_then(|v| v.clone().into_string().ok()).ok_or_else(|| format!("rates: `{k}` must name a gene"));
        Ok(NeedLaw::Params {
            hunger: n("hunger")?,
            energy: n("energy")?,
            starving_at: n("starving_at")?,
            starving_hp: n("starving_hp")?,
            fed_below: n("fed_below")?,
            rested_above: n("rested_above")?,
            healing_hp: n("healing_hp")?,
            spent_at: n("spent_at")?,
            spent_hp: n("spent_hp")?,
            healing: n("healing")?,
            tiring_gene: gene("tiring_gene")?,
            healing_gene: gene("healing_gene")?,
            wet_energy: n("wet_energy")?,
            cold_hp: n("cold_hp")?,
            appetite_gene: m.get("appetite_gene").and_then(|v| v.clone().into_string().ok()).unwrap_or_default(),
            hardiness_gene: m.get("hardiness_gene").and_then(|v| v.clone().into_string().ok()).unwrap_or_default(),
            per_min,
        })
    }
}

fn decode_body(d: Dynamic) -> Result<BodyState, String> {
    let m = d.try_cast::<Map>().ok_or("body_state must return a map")?;
    let flag = |k: &str| m.get(k).and_then(|v| v.clone().try_cast::<bool>()).ok_or_else(|| format!("body_state missing {k}"));
    let wound = match m.get("wound").and_then(|v| v.clone().into_string().ok()).as_deref() {
        Some("") => Wound::None,
        Some("hurt") => Wound::Hurt,
        Some("badly wounded") => Wound::BadlyWounded,
        Some("barely alive") => Wound::BarelyAlive,
        _ => return Err("body_state invalid wound".into()),
    };
    Ok(BodyState { cold: flag("cold")?, hungry: flag("hungry")?, starving: flag("starving")?, wound })
}

/// The map `perceived_of(p)` is called with.
fn regard_map(p: &RegardIn) -> Map {
    let mut o = Map::new();
    o.insert("kind".into(), p.observer_kind.clone().into());
    o.insert("knows".into(), p.knows.iter().map(|k| Dynamic::from(k.clone())).collect::<Array>().into());
    let mut t = Map::new();
    t.insert("kind".into(), p.target_kind.clone().into());
    t.insert("known".into(), p.known.into());
    t.insert("revealed".into(), p.revealed.iter().map(|k| Dynamic::from(k.clone())).collect::<Array>().into());
    let mut m = Map::new();
    m.insert("observer".into(), o.into());
    m.insert("target".into(), t.into());
    m.insert("self".into(), p.own.into());
    m.insert("night".into(), p.night.into());
    m.insert("dist".into(), Dynamic::from_float(p.dist as f64));
    m
}

/// The law's answer; a field it leaves out keeps the default.
fn decode_regard(r: Dynamic, p: &RegardIn) -> Result<Regard, String> {
    let r = r.try_cast::<Map>().ok_or("perceived_of must return a map")?;
    let d = Regard::default_for(p);
    let name = match r.get("name") {
        None => d.name,
        Some(v) => v.as_bool().map_err(|_| "perceived_of: `name` must be true or false")?,
    };
    let health = match r.get("health").map(|v| v.clone().into_string()) {
        None => d.health,
        Some(Ok(h)) if h == "exact" => Precision::Exact,
        Some(Ok(h)) if h == "band" => Precision::Band,
        Some(Ok(h)) if h == "none" => Precision::None,
        Some(_) => return Err("perceived_of: `health` is \"exact\", \"band\" or \"none\"".into()),
    };
    Ok(Regard { name, health })
}

/// A record's parties: a map of role → character id (or community party).
fn parties_of(d: Option<&Dynamic>) -> Result<Vec<(String, u64)>, String> {
    let Some(m) = d.and_then(|d| d.clone().try_cast::<Map>()) else { return Ok(Vec::new()) };
    let mut v = Vec::new();
    for (role, id) in m {
        let id = number(&id).filter(|x| *x >= 1.0).ok_or_else(|| format!("party `{role}` must be an id"))?;
        v.push((role.to_string(), id as u64));
    }
    Ok(v)
}

/// A record's terms from a script map (strings, numbers, booleans).
fn terms_of(d: Option<&Dynamic>) -> Result<serde_json::Map<String, serde_json::Value>, String> {
    let Some(m) = d.and_then(|d| d.clone().try_cast::<Map>()) else { return Ok(Default::default()) };
    let mut t = serde_json::Map::new();
    for (k, v) in m {
        let j = if let Ok(s) = v.clone().into_string() {
            serde_json::Value::String(s)
        } else if let Ok(b) = v.as_bool() {
            serde_json::Value::Bool(b)
        } else if let Ok(i) = v.as_int() {
            serde_json::Value::from(i)
        } else if let Ok(f) = v.as_float() {
            serde_json::Value::from(f)
        } else {
            return Err(format!("term `{k}` must be a string, a number or true/false"));
        };
        t.insert(k.to_string(), j);
    }
    crate::records::check_terms(&t)?;
    Ok(t)
}

/// World hours, within what a record may stand.
fn hours(d: Option<&Dynamic>) -> Result<Option<f32>, String> {
    match d {
        None => Ok(None),
        Some(d) if d.is_unit() => Ok(None),
        Some(d) => number(d).map(|h| Some((h as f32).clamp(0.0, crate::records::MAX_DUE_H))).ok_or_else(|| "hours must be a number".to_string()),
    }
}

fn effect(d: Dynamic) -> Result<Effect, String> {
    let m = d.try_cast::<Map>().ok_or("effect must be a map")?;
    let s = |k: &str| m.get(k).and_then(|v| v.clone().into_string().ok()).unwrap_or_default();
    let n = |k: &str| m.get(k).and_then(number).unwrap_or(0.0);
    let qty = || {
        let q = n("qty");
        if q < 1.0 {
            Err("effect qty must be >= 1".to_string())
        } else {
            Ok(q as u32)
        }
    };
    Ok(match s("op").as_str() {
        "add" => Effect::Add { item: s("item"), qty: qty()? },
        "remove" => Effect::Remove { item: s("item"), qty: qty()? },
        "harvest" => Effect::Harvest { qty: n("qty") as f32 },
        "vitals" => Effect::Vitals { hp: n("hp") as f32, hunger: n("hunger") as f32, energy: n("energy") as f32 },
        "spend" => match s("pool").as_str() {
            p @ ("stamina" | "focus") => Effect::Spend { pool: p.into(), amount: (n("amount") as f32).max(0.0) },
            p => return Err(format!("spend: pool `{p}` is not stamina or focus")),
        },
        "graze" => Effect::Graze,
        "damage" => Effect::Damage { amount: n("amount") as f32 },
        "heal" => Effect::Heal { amount: n("amount") as f32 },
        "gate" => Effect::Gate { open: n("open") > 0.0 },
        "give" => Effect::Give { item: s("item"), qty: qty()? },
        "seize" => Effect::Seize { item: s("item"), qty: qty()? },
        "store" => Effect::Store { item: s("item"), qty: qty()? },
        "take" => Effect::Take { item: s("item"), qty: qty()? },
        "fuel" => Effect::Fuel { item: s("item"), qty: qty()? },
        "burn" => {
            let u = n("units");
            if !(u > 0.0 && u.is_finite()) {
                return Err("burn needs units > 0".into());
            }
            Effect::Burn { units: u as f32 }
        },
        "build" => Effect::Build { kind: s("kind") },
        "bond" => Effect::Bond,
        "signal" => Effect::Signal,
        "yield" => Effect::Yield,
        "teach" => Effect::Teach { technique: s("technique") },
        "learn" => Effect::Learn { technique: s("technique") },
        "write" => Effect::Write,
        "rework" => Effect::Rework,
        "read" => Effect::Read,
        "plant" => Effect::Plant,
        "offer" => Effect::Offer,
        "accept" => Effect::Accept { offer: n("offer").max(0.0) as u64 },
        "decline" => Effect::Decline { offer: n("offer").max(0.0) as u64 },
        "found" => Effect::Found,
        "join" => Effect::Join,
        "welcome" => Effect::Welcome,
        "leave" => Effect::Leave,
        "host" => Effect::Host { until_hour: (n("until_hour") as f32).rem_euclid(24.0) },
        "launch" => Effect::Launch,
        "hail" => Effect::Hail,
        "reveal" => Effect::Reveal { what: s("what"), secs: (n("secs") as f32).clamp(0.0, 600.0) },
        "record" => {
            let parties = parties_of(m.get("parties"))?;
            if parties.is_empty() || parties.len() > crate::records::MAX_PARTIES {
                return Err(format!("a record has 1..{} parties", crate::records::MAX_PARTIES));
            }
            if s("kind").is_empty() {
                return Err("a record needs a kind".into());
            }
            Effect::Record { kind: s("kind"), status: s("status"), parties, terms: terms_of(m.get("terms"))?, due_h: hours(m.get("due_h"))? }
        },
        "amend" => Effect::Amend { id: n("id").max(0.0) as u64, status: m.get("status").and_then(|v| v.clone().into_string().ok()), terms: terms_of(m.get("terms"))?, due_h: hours(m.get("due_h"))? },
        "close" => Effect::Close { id: n("id").max(0.0) as u64, status: s("status"), keep_h: hours(m.get("keep_h"))?.unwrap_or(0.0) },
        "tell" => {
            if s("text").trim().is_empty() {
                return Err("tell needs a text".into());
            }
            Effect::Tell { to: n("to").max(0.0) as u64, text: s("text"), salience: m.get("salience").and_then(number).unwrap_or(0.7).clamp(0.0, 1.0) as f32, ask: m.get("ask").and_then(|v| v.as_bool().ok()).unwrap_or(false) }
        },
        "witness" => Effect::Witness { text: s("text"), salience: m.get("salience").and_then(number).unwrap_or(0.4).clamp(0.0, 1.0) as f32 },
        other => return Err(format!("unknown effect op `{other}`")),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_combat_law_tells_the_attack_windup_the_cards_show() {
        let src = include_str!("../../scripts/skills.rhai");
        let s = Scripts::new(src).unwrap();
        let about = &s.law_specs()["combat"].about;
        assert_eq!(s.timing("attack").unwrap().windup_ms, 650);
        assert!(about.contains("A person's attack winds up for 0.65 s before it lands") && !about.contains("{windup"), "{about}");
        // A world whose attack winds up longer is told so: the words follow the laws.
        let slow = src.replace("if inv(a, \"spear\") > 0 { 750 } else { 650 }", "if inv(a, \"spear\") > 0 { 750 } else { 900 }");
        assert_ne!(slow, src, "attack_duration's shape changed: update this test");
        let about = Scripts::new(&slow).unwrap().law_specs()["combat"].about.clone();
        assert!(about.contains("winds up for 0.9 s before it lands"), "{about}");
        // A token that names no combat skill with a windup is refused at install.
        let odd = src.replace("{windup:attack}", "{windup:gather}");
        assert!(Scripts::new(&odd).err().unwrap_or_default().contains("{windup:gather}"));
        assert_eq!(seconds(1000), "1 s");
        assert_eq!(seconds(1500), "1.5 s");
    }

    fn scripts() -> Scripts {
        Scripts::new(include_str!("../../scripts/skills.rhai")).expect("skills compile")
    }

    fn creature(night: bool, torch: bool) -> SkillCtx {
        let inv = if torch { vec![("torch".to_string(), 1)] } else { Vec::new() };
        SkillCtx { actor: ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), inv, ..Default::default() }, night, ..Default::default() }
    }

    /// The minds' world text is built from the laws' descriptions, in the sections the script
    /// orders, with the world's own sections (seasons, life) where they belong; every law the
    /// engine asks and every world constant must be described, or an install is refused.
    #[test]
    fn ways_of_speaking_are_read_from_the_script() {
        let s = scripts();
        let names: Vec<&str> = s.ways().iter().map(|w| w.name.as_str()).collect();
        assert_eq!(names, ["say", "whisper", "call"]);
        let whisper = s.way("whisper").unwrap();
        assert_eq!((whisper.carry, whisper.only_to, whisper.reach, whisper.kind.as_str(), whisper.names, whisper.animals.as_str()), (speech::Carry::Within(1.5), true, 1.5, "whisper", false, ""));
        let noticed = whisper.noticed.as_ref().unwrap();
        assert_eq!((noticed.within_m, noticed.seen, noticed.kind.as_str(), noticed.text.as_str()), (6.0, true, "whispered", "{a} whispers something to {b}."));
        let call = s.way("call").unwrap();
        assert_eq!((call.carry_for(9.0), call.max_chars, call.gap_s, call.animals.as_str(), call.public()), (22.5, 80, 6.0, "a person shouting", true));
        assert!(call.about.contains("within 22.5 m"), "{}", call.about);
        // The shipped `say` is today's speech, field for field (the regression baseline).
        let mut say = s.way("say").unwrap().clone();
        assert_eq!(say.about, speech::WaySpec::say().about);
        say.about = speech::WaySpec::say().about;
        assert_eq!(say, speech::WaySpec::say());
        // Each way with its reach in metres, from its spec and the world's hearing (9 m here).
        let t = s.world_text(&[]);
        assert!(t.contains("SPEAKING: say (carries 9 m) = Speak aloud."), "{t}");
        assert!(t.contains(" whisper (to someone within 1.5 m) = Whisper") && t.contains(" call (carries 22.5 m) = Call out"), "{t}");
        assert_eq!((say.reach_words(12.0), whisper.reach_words(12.0), call.reach_words(12.0)), ("carries 12 m".into(), "to someone within 1.5 m".into(), "carries 30 m".into()));
        let src = include_str!("../../scripts/skills.rhai");
        let with = |overlay: &str| Scripts::new(&crate::floors::compose(src, overlay).unwrap());
        // A way the engine cannot keep is refused, naming the key.
        let e = with("fn shout_speech() { #{ about: \"x\", cost: #{ energy: 2.0 } } }").err().unwrap();
        assert!(e.contains("unknown trait `cost`"), "{e}");
        let e = with("fn hush_speech() { #{ about: \"x\", words: #{ within_m: 1.5, only_to: true } } }").err().unwrap();
        assert!(e.contains("need `to: \"required\"`"), "{e}");
        let e = with("fn wave_speech() { #{ about: \"x\" } }").err().unwrap();
        assert!(e.contains("is a skill already"), "{e}");
        let e = with("fn say_speech() { #{ about: \"x\", needs: \"telepathy\" } }").err().unwrap();
        assert!(e.contains("names a technique"), "{e}");
        // A second way comes in its order, and its words for one ear reach no animal.
        let two = with("fn hush_speech() { #{ about: \"Hush.\", order: 1, to: \"required\", words: #{ within_m: 1.5, only_to: true }, heard_to_you: \"{a} hushes to you\" } }").unwrap();
        let w = two.way("hush").unwrap();
        assert_eq!(two.ways().iter().map(|w| w.name.as_str()).collect::<Vec<_>>(), ["say", "whisper", "hush", "call"]);
        assert_eq!((w.carry, w.only_to, w.animals.as_str(), w.label.as_str()), (speech::Carry::Within(1.5), true, "", "Hush"));
        assert_eq!((w.carry_for(9.0), w.widest(9.0)), (1.5, 1.5));
        assert!(two.world_text(&[]).contains("say (carries 9 m) = Speak aloud. Everyone within earshot hears you, also when you speak to one person. whisper (to someone within 1.5 m) = Whisper to someone beside you (within 1.5 m)."));
        // A script with no ways at all speaks by today's `say`.
        let none = Scripts::new(&src.replace("_speech()", "_speech_old()")).unwrap();
        assert_eq!(none.way("say"), Some(&speech::WaySpec::say()));
    }

    #[test]
    fn ways_refuse_in_their_checks_words() {
        use speech::check_way;
        let s = scripts();
        let me = ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), ..Default::default() };
        let them = |dist: f32, alive: bool| Some(TargetFacts { class: "creature".into(), id: 2, kind: "person".into(), alive, dist, ..Default::default() });
        let check = |way: &str, to, since| check_way(&s, way, me.clone(), to, "hello", since);
        // The words a client shows before sending are the reducer's (both call `check_way`).
        assert_eq!(check("whisper", None, None), Err("a whisper needs someone to whisper to".into()));
        assert_eq!(check("whisper", them(3.0, true), None), Err("too far to whisper: step closer".into()));
        assert_eq!(check("whisper", them(1.0, false), None), Err("too far to whisper: step closer".into()), "absent or dead reads as too far: ids cannot be probed");
        assert_eq!(check("whisper", them(1.0, true), None), Ok(()));
        assert_eq!(check("call", None, Some(3_000)), Err("too soon to call out again: wait a few seconds".into()));
        assert_eq!(check("call", None, Some(6_000)), Ok(()));
        assert_eq!(check("call", None, None), Ok(()));
        assert_eq!(check("say", them(30.0, true), Some(0)), Ok(()), "say has no check of its own");
        assert_eq!(check("", None, None), Ok(()), "no way named is say");
        assert_eq!(check("shout", None, None), Err("no way of speaking called `shout`".into()), "the engine's own refusal, in the reducer's words");
        // A way whose spec requires something must refuse it in its check, or the install is refused.
        let src = include_str!("../../scripts/skills.rhai");
        let install = |overlay: &str| Scripts::new(&crate::floors::compose(src, overlay).unwrap()).and_then(|s| s.validate().map(|_| ()));
        let e = install("fn hush_speech() { #{ about: \"Hush.\", to: \"required\", reach: 1.0, words: #{ within_m: 1.0, only_to: true } } }").unwrap_err();
        assert!(e.contains("has no `hush_check(a)`"), "{e}");
        let e = install("fn hush_speech() { #{ about: \"Hush.\", to: \"required\", reach: 1.0, words: #{ within_m: 1.0, only_to: true } } }\nfn hush_check(a) { if a.target.class == \"none\" { return \"hush to whom?\"; } \"\" }").unwrap_err();
        assert!(e.contains("accepts a line to someone 1.5 m away"), "{e}");
        let e = install("fn whisper_check(a) { \"\" }").unwrap_err();
        assert!(e.contains("accepts a line to no one"), "{e}");
        let e = install("fn call_check(a) { \"\" }").unwrap_err();
        assert!(e.contains("a second line 5000 ms after the first"), "{e}");
        let e = install("fn say_check(a) { \"no\" }").unwrap_err();
        assert!(e.contains("refuses a line that breaks nothing"), "{e}");
        // A check reads only what `check_way` gives, which a client can give too.
        let e = install("fn say_check(a) { if a.hour > 30.0 { return \"never\"; } \"\" }").unwrap_err();
        assert!(e.contains("`say_check` reads `a.hour`"), "{e}");
        let e = Scripts::new(&crate::floors::compose(src, "fn sign_speech() { #{ about: \"Sign.\", needs_sight: true } }").unwrap()).err().unwrap();
        assert!(e.contains("`needs_sight` is not built yet"), "{e}");
    }

    #[test]
    fn world_text_is_built_from_the_laws() {
        let s = scripts();
        let t = s.world_text(&[("seasons", "a year is 8 days.".into()), ("life", "a person lives about 70 years.".into())]);
        let heads: Vec<&str> = t.lines().map(|l| l.split(':').next().unwrap_or("")).collect();
        assert_eq!(heads[1..].join(" "), "SENSES SPEAKING MOVING SEASONS BODY KNOW-HOW FOOD MAKING SETTLEMENTS LIFE COMBAT FORCE COMMUNITIES TIME OTHERS", "{t}");
        assert!(t.starts_with("One day lasts 12 real minutes; night is 20:00-06:00.\nSENSES: How far a creature sees and hears, in metres (one tile is one metre). By day one sees 11 m; at night 6 m, or 9 m carrying a torch."), "{t}");
        assert!(t.contains("FOOD: berries 12, fish 16, meat 20, cooked_fish 34, cooked_meat 42, smoked_fish 24, smoked_meat 30 (hunger points). Cook raw fish or meat at a campfire"), "{t}");
        assert!(t.contains("BODY: hunger rises ~1.2/min (100 = starving") && t.contains("within reach (about 2 m; a wolf's leap about 3.2)") && t.contains("for 20 s you do not strike back") && t.contains("Deer can be hunted (5 meat)"), "{t}");
        assert!(t.contains("SETTLEMENTS: walls block the way;") && t.contains("Taking from someone else's store"), "{t}");
        assert_eq!(t, s.world_text(&[("seasons", "a year is 8 days.".into()), ("life", "a person lives about 70 years.".into())]), "the same rules give the same text");
        // A floor that changes a law changes what minds are told.
        let src = include_str!("../../scripts/skills.rhai");
        let dim = Scripts::new(&crate::floors::compose(src, "fn sight_in(light) { if light == \"day\" { 7.0 } else { base_sight_in(light) } }").unwrap()).unwrap();
        assert!(dim.world_text(&[]).contains("By day one sees 7 m"));
        // Undescribed laws are refused.
        let bare = Scripts::new(&src.replace("fn theft_law()", "fn theft_old_law()")).unwrap();
        assert!(bare.validate().unwrap_err().contains("the law `theft` has no description"));
        let mute = Scripts::new(&src.replace("        follow_s: `one follow lasts", "        follow_z: `one follow lasts")).unwrap();
        assert!(mute.validate().unwrap_err().contains("the world constant `follow_s` has no description"));
        assert!(s.validate().is_ok());
    }

    /// The minds' world text the shipped rules give:
    /// `cargo test -p living-rules --lib print_world_text -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn print_world_text() {
        println!("{}", scripts().world_text(&[("seasons", "(the world's calendar)".into()), ("life", "(the world's life table)".into())]));
    }

    /// Items, kinds and skills are declared with traits, and the rules read the traits: the
    /// lists the engine had (catalog::ITEMS, LATCHES, the notable skills, MOVES, the skills done
    /// moving) come out of the script unchanged, and a new item or kind is a line of script.
    #[test]
    fn rules_read_traits_not_lists() {
        let s = scripts();
        let names: Vec<String> = s.skills().items.iter().map(|i| i.name.clone()).collect();
        assert_eq!(names.join(" "), "berries fish meat cooked_fish cooked_meat wood stone fiber spear hide cloak torch tablet clay axe pick smoked_fish smoked_meat net basket bow arrow salve leather armor mark");
        let with = |f: fn(&crate::catalog::SkillSpec) -> bool| s.skills().iter().filter(|k| f(k)).map(|k| k.name.clone()).collect::<std::collections::BTreeSet<_>>().into_iter().collect::<Vec<_>>().join(" ");
        // `feed` and `make` (2026-11-11) are there for a world with fires that burn fuel and recipes.
        assert_eq!(with(|k| k.latch), "build cook craft eat experiment feed gather give make plant read rest sleep store take teach write");
        assert_eq!(with(|k| k.notable), "attack build conceive cook craft feed give make store take threaten yield");
        assert_eq!(with(|k| k.moving), "eat signal wait");
        assert_eq!(with(|k| k.moment), "flee follow graze rest sleep wait wander");
        assert_eq!(with(|k| k.reflex), "flee");
        assert_eq!((s.structure("house"), s.structure("campfire"), s.structure("workshop"), s.structure("storage")), (&StructureTraits { warms: true, roof: true, ..Default::default() }, &StructureTraits { warms: true, ..Default::default() }, &StructureTraits { roof: true, ..Default::default() }, &StructureTraits { holds: Some(120.0), ..Default::default() }));
        assert_eq!(s.words_of("occupation_knows", "fisher"), vec!["spear", "cooking", "fishing"]);
        assert_eq!((s.num_of("kept_spoil", "storage", 0.0), s.num_of("planted_max", "berry_bush", 0.0)), (1.0 / 3.0, 5.0));
        assert_eq!((s.num_of("max_hp", "wolf", 0.0), s.num_of("lunge", "wolf", 0.0), s.remains_ms("deer"), s.num_of("dodge_speed", "person", 0.0)), (s.law_value("hp_wolf").and_then(|v| v.as_f64()).unwrap(), 1.8, 1_800_000.0, 5.2), "a wolf's health is the hp_wolf law");
        // The words minds and players read are the ones the lists gave.
        assert_eq!(s.text_of("source_of", "food").unwrap(), "gather berries at a berry_bush or fish at a fishing_spot, take food from a storage, or hunt");
        let cook = |s: &Scripts, item: &str| {
            let c = SkillCtx { actor: ActorFacts { kind: "person".into(), stage: "adult".into(), knows: vec!["cooking".into()], inv: vec![(item.to_string(), 1)], ..Default::default() }, target: TargetFacts { class: "structure".into(), kind: "campfire".into(), ..Default::default() }, item: item.into(), skill: "cook".into(), ..Default::default() };
            s.check("cook", &c).and_then(|_| s.done("cook", &c))
        };
        assert_eq!(cook(&s, "berries").unwrap_err(), "only raw fish or meat can be cooked");
        assert!(matches!(&cook(&s, "fish").unwrap()[1], Effect::Add { item, .. } if item == "cooked_fish"));
        // A world with roots that bake: one item line, no rule changed.
        let src = include_str!("../../scripts/skills.rhai").replace("fn items() {", "fn base_items() {");
        let roots = Scripts::new(&format!("{src}\nfn items() {{ base_items() + [#{{ name: \"roots\", cooks_to: \"baked_roots\" }}, #{{ name: \"baked_roots\" }}] }}")).unwrap();
        assert!(matches!(&cook(&roots, "roots").unwrap()[1], Effect::Add { item, .. } if item == "baked_roots"));
        assert_eq!(cook(&roots, "berries").unwrap_err(), "only raw fish, meat or roots can be cooked");
        assert!(crate::catalog::scoped(roots.skills().clone(), || crate::catalog::item("roots").is_some()) && crate::catalog::item("roots").is_none());
        // Who grazes is a trait of the kind.
        let graze = |kind: &str| {
            let c = SkillCtx { actor: ActorFacts { kind: kind.into(), stage: "adult".into(), terrain: "grass".into(), pasture: 5.0, ..Default::default() }, skill: "graze".into(), ..Default::default() };
            s.check("graze", &c)
        };
        assert!(graze("deer").is_ok() && graze("wolf").unwrap_err() == "only grazing animals graze");
        assert!(s.done("graze", &SkillCtx::default()).unwrap().contains(&Effect::Graze));
    }

    /// How a creature moves besides its walk is a law per creature: a person runs `run_share`
    /// times its walk (a world law), animals 1.5 times (charging at a hunt's approach), a flight
    /// 1.15, stepping aside 0.8, turning 6 rad/s keeping 0.4 of its speed in the sharpest turns,
    /// keeping 0.8 m from others at weight 0.9; no road takes anyone past `run_top`.
    #[test]
    fn moves_are_a_law_per_creature() {
        let s = scripts();
        let mut person = creature(false, false);
        person.actor.kind = "person".into();
        let m = s.moves(&person).unwrap();
        let share = s.law_value("run_share").and_then(|v| v.as_f64()).unwrap() as f32;
        let top = s.law_value("run_top").and_then(|v| v.as_f64()).unwrap() as f32;
        assert_eq!(m, Moves { run: share, flee: 1.15, aside: 0.8, turn_rate: 6.0, turn_slow: 0.4, separation: 0.8, separation_weight: 0.9, wander_turn: 1.2, wander_keep_s: 60.0, top, charge: false });
        assert_eq!(s.law_plan("motion").describe(), vec!["actor.kind".to_string()], "the shipped law reads only the kind");
        let mut wolf = creature(false, false);
        wolf.actor.kind = "wolf".into();
        let w = s.moves(&wolf).unwrap();
        assert_eq!((w.run, w.charge, w.top), (1.5, true, top));
        let spec = &s.law_specs()["motion"];
        assert_eq!(spec.cadence, Cadence::Hot);
        assert!(spec.about.contains("Grown people walk 2.6, wolves 3.4, deer 3.7") && spec.about.contains(&format!("A person runs {} times its walk", share)) && spec.about.contains(&format!("past {} m/s", top)), "{}", spec.about);
        // A floor where wolves run harder: the law reads the kind, and only wolves change.
        let src = include_str!("../../scripts/skills.rhai").replace("fn motion(a)", "fn base_motion(a)");
        let f = Scripts::new(&format!("{src}\nfn motion(a) {{ let m = base_motion(a); if a.actor.kind == \"wolf\" {{ m.run = 2.0; }} m }}")).unwrap();
        assert_eq!((f.moves(&wolf).unwrap().run, f.moves(&person).unwrap().run), (2.0, share));
        if let Err(e) = f.validate() { panic!("{e}"); }
        // A law without `top` or `charge` (an older floor's): no cap, no charge.
        let old = Scripts::new(&format!("{src}\nfn motion(a) {{ #{{ run: 1.5, flee: 1.15, aside: 0.8, turn_rate: 6.0, turn_slow: 0.4, separation: 0.8, separation_weight: 0.9, wander_turn: 1.2, wander_keep_s: 60.0 }} }}")).unwrap();
        let o = old.moves(&wolf).unwrap();
        assert_eq!((o.top, o.charge), (f32::INFINITY, false));
    }

    /// Sight and hearing are a law per creature in the script, with the values the engine had
    /// as constants (11 m by day, 6 at night, 9 with a torch; hearing 9), shared by every
    /// creature in the same state and held to the law's reach.
    #[test]
    fn sight_depends_on_facing_only_when_the_world_s_law_says() {
        let src = include_str!("../../scripts/skills.rhai");
        let off = Scripts::new(src).unwrap();
        // Off (the shipped script): no field in any state, and the law reads what it read before.
        for (n, t) in [(false, false), (true, false), (true, true)] {
            assert_eq!(off.senses(&creature(n, t)).unwrap().field, None);
        }
        assert_eq!(off.law_plan("senses").describe(), vec!["actor.inv[torch]".to_string(), "night".to_string()]);
        assert_eq!(off.law_value("fov_on"), Some(serde_json::json!(false)));
        assert!(!off.law_specs()["senses"].about.contains("degrees"));
        assert!(!off.laws().fov_on);
        // A world's own values (`set_world_law`, a seed's `rules`) written into its script.
        let on_src = with_world_laws(src, &[("fov_on".into(), serde_json::json!(true))]);
        let on = Scripts::new(&on_src).unwrap();
        on.validate().unwrap();
        assert!(on.laws().fov_on);
        let day = on.senses(&creature(false, false)).unwrap();
        assert_eq!(day.field, Some(crate::sight::Field { focal_deg: 70.0, side_deg: 110.0, side_share: 0.3333, near_m: 3.0, margin_deg: 10.0 }));
        assert_eq!((day.sight, day.hearing), (11.0, 9.0));
        assert_eq!(on.senses(&creature(true, false)).unwrap().field.unwrap().near_m, 2.0, "less all round in the dark");
        assert_eq!(on.senses(&creature(true, true)).unwrap().field.unwrap().near_m, 3.0, "a torch lights the near ring");
        assert!(on.law_specs()["senses"].about.contains("70 degrees"), "{}", on.law_specs()["senses"].about);
        // Writing again replaces the block; no values give back the installed script.
        let twice = with_world_laws(&on_src, &[("fov_on".into(), serde_json::json!(true)), ("fov_focal_deg".into(), serde_json::json!(60))]);
        assert_eq!(twice.matches("fn world_law_values()").count(), 1);
        assert_eq!(Scripts::new(&twice).unwrap().senses(&creature(false, false)).unwrap().field.unwrap().focal_deg, 60.0);
        assert_eq!(without_world_laws(&twice).trim_end(), src.trim_end());
        assert_eq!(with_world_laws(src, &[]), src);
        // A value of the wrong kind, or a name that is no law, is not taken from the block.
        let odd = Scripts::new(&with_world_laws(src, &[("fov_on".into(), serde_json::json!(2)), ("no_such".into(), serde_json::json!(1))])).unwrap();
        assert!(!odd.laws().fov_on && odd.law_value("no_such").is_none());
        // What a sound out of sight is told as.
        assert_eq!((on.heard_as("person"), on.heard_as("wolf"), on.heard_as("hare")), ("person".into(), "wolf".into(), "creature".into()));
    }

    /// How far a walker's facing may turn from its way toward a held look is the world's law:
    /// 75 degrees shipped, a world's own value taken (and kept within 0..180).
    #[test]
    fn the_walking_look_limit_is_the_world_s_law() {
        let src = include_str!("../../scripts/skills.rhai");
        let shipped = Scripts::new(src).unwrap();
        assert_eq!(shipped.laws().look_walk_deg, 75.0);
        assert_eq!(shipped.law_value("look_walk_deg"), Some(serde_json::json!(75.0)));
        let about = shipped.laws_about().into_iter().find(|(k, _)| k == "look_walk_deg").map(|(_, t)| t).unwrap_or_default();
        assert!(about.contains("75 degrees"), "{about}");
        let tuned = Scripts::new(&with_world_laws(src, &[("look_walk_deg".into(), serde_json::json!(40))])).unwrap();
        tuned.validate().unwrap();
        assert_eq!(tuned.laws().look_walk_deg, 40.0);
        let wild = Scripts::new(&with_world_laws(src, &[("look_walk_deg".into(), serde_json::json!(400))])).unwrap();
        assert_eq!(wild.laws().look_walk_deg, 180.0);
        // Cullet's laws leave it alone: a Cullet world takes the shipped value.
        assert!(!include_str!("../../seeds/worlds/cullet/laws.rhai").contains("look_walk_deg"));
    }

    /// A script from before a required law runs with the shipped one merged under it. The two
    /// sources share line numbers, so the field analysis must not attribute one's statements to
    /// the other's functions: the borrowed law reads what it reads, every time.
    #[test]
    fn a_borrowed_law_reads_its_own_fields_every_time() {
        let src = include_str!("../../scripts/skills.rhai");
        let old_src = src.replace("fn senses(a)", "fn senses_gone(a)");
        for _ in 0..40 {
            let old = Scripts::new(&old_src).unwrap();
            assert_eq!(old.law_plan("senses").describe(), vec!["actor.inv[torch]".to_string(), "night".to_string()]);
            assert_eq!(old.senses(&creature(true, false)).unwrap().sight, 6.0);
        }
    }

    #[test]
    fn senses_are_a_law_per_creature() {
        let s = scripts();
        let got: Vec<(f32, f32)> = [(false, false), (true, false), (true, true), (false, true)].iter().map(|(n, t)| {
            let v = s.senses(&creature(*n, *t)).unwrap();
            (v.sight, v.hearing)
        }).collect();
        assert_eq!(got, vec![(11.0, 9.0), (6.0, 9.0), (9.0, 9.0), (11.0, 9.0)]);
        assert_eq!(s.reach(), Reach { day: 11.0, night: 9.0, hearing: 9.0, glow: 0.0 });
        assert_eq!(s.law_plan("senses").describe(), vec!["actor.inv[torch]".to_string(), "night".to_string()], "the key is what the law reads");
        let spec = &s.law_specs()["senses"];
        assert_eq!((spec.cadence, spec.topic.as_str()), (Cadence::Hot, "senses"));
        assert!(spec.about.contains("By day one sees 11 m; at night 6 m, or 9 m carrying a torch") && spec.about.contains("Speech carries 9 m"), "{}", spec.about);
        // A passive that extends sight is a line of script; past the reach it is refused.
        let src = include_str!("../../scripts/skills.rhai");
        let keen = format!("{}\nfn senses(a) {{ #{{ sight: sight_in(light_of(a)) + if knows(a, \"torch\") {{ 2.0 }} else {{ 0.0 }}, hearing: 9.0 }} }}", src.replace("fn senses(a)", "fn senses_base(a)"));
        let k = Scripts::new(&keen).unwrap();
        let mut c = creature(true, false);
        c.actor.knows = vec!["torch".into()];
        assert_eq!(k.senses(&c).unwrap().sight, 8.0);
        let err = k.validate().unwrap_err();
        assert!(err.contains("beyond senses_law's reach"), "{err}");
        // A script from before the law runs with the shipped one, and an install refuses it.
        let old = Scripts::new(&src.replace("fn senses(a)", "fn senses_gone(a)")).unwrap();
        assert_eq!(old.borrowed(), ["senses".to_string()]);
        assert_eq!(old.senses(&creature(false, false)).unwrap().sight, 11.0);
        assert!(old.validate().unwrap_err().contains("has no `senses` law"));
        // A law declared without a description is refused.
        assert!(Scripts::new(&format!("{src}\nfn odd_law() {{ #{{ cadence: \"event\" }} }}")).err().unwrap().contains("odd_law: `about`"));
    }

    #[test]
    fn a_body_s_remains_hold_what_the_carcass_law_gives_and_last_by_kind() {
        let sc = scripts();
        assert_eq!(sc.items_of("carcass", "deer"), vec![("hide".to_string(), 1), ("meat".to_string(), 5)]);
        assert_eq!(sc.items_of("carcass", "wolf"), vec![("hide".to_string(), 1), ("meat".to_string(), 2)]);
        assert!(sc.items_of("carcass", "person").is_empty());
        assert!(sc.items_of("no_such_law", "deer").is_empty());
        // A law that gives something other than a map, or no whole amounts, gives nothing.
        let odd = Scripts::new(&format!("{}\nfn odd(k) {{ if k == \"a\" {{ 3 }} else {{ #{{ meat: 0.5, hide: -1, bone: 2 }} }} }}", include_str!("../../scripts/skills.rhai"))).unwrap();
        assert!(odd.items_of("odd", "a").is_empty());
        assert_eq!(odd.items_of("odd", "b"), vec![("bone".to_string(), 2)]);
        assert_eq!((sc.remains_ms("deer"), sc.remains_ms("person")), (1_800_000.0, 3_600_000.0));
    }

    /// Spoiling, regrowth, grass, traps and remains are written in game time and turned into
    /// real time for the world's day; a script that still writes them in real time (a law of
    /// the old name) is taken as it is, whatever the day.
    #[test]
    fn game_time_rates_follow_the_day_and_real_time_laws_stay_real() {
        let src = include_str!("../../scripts/skills.rhai");
        let lab = Scripts::new(src).unwrap();
        let long = Scripts::with_day(src, 48 * 60_000).unwrap();
        // The shipped numbers on the 12-minute day: what they were per real minute and second.
        assert_eq!((lab.spoil_per_min("fish"), lab.spoil_per_min("smoked_fish"), lab.spoil_per_min("berries")), (0.05, 0.002, 0.02));
        assert_eq!((lab.regrow_per_min("fishing_spot", 0.0), lab.regrow_per_min("berry_bush", 0.0), lab.regrow_per_min("no_such", 0.5)), (1.4, 1.2, 0.0));
        assert_eq!((lab.trap_every_ms(), lab.remains_ms("wolf"), lab.laws().pasture_regen), (240_000.0, 1_800_000.0, 0.0015));
        // A four-times-longer day: a quarter of the rate per real minute, four times the time.
        assert_eq!((long.spoil_per_min("fish"), long.regrow_per_min("fishing_spot", 0.0)), (0.0125, 0.35));
        assert_eq!((long.trap_every_ms(), long.remains_ms("person"), long.laws().pasture_regen), (960_000.0, 14_400_000.0, 0.000375));
        // An overlay in real time keeps its numbers on any day.
        let old = format!("{src}\nfn spoil_rate(item) {{ 0.05 }}\nfn remains_s(kind) {{ 90 }}\nfn trap_every_s(x) {{ 60.0 }}\nfn regrow(kind) {{ 2.0 }}");
        let old = Scripts::with_day(&old, 48 * 60_000).unwrap();
        assert_eq!((old.spoil_per_min("fish"), old.remains_ms("deer"), old.trap_every_ms(), old.regrow_per_min("tree", 0.0)), (0.05, 90_000.0, 60_000.0, 2.0));
    }

    #[test]
    fn what_one_perceives_of_another_is_the_law_s() {
        let sc = scripts();
        let base = RegardIn { observer_kind: "person".into(), target_kind: "person".into(), ..Default::default() };
        // A stranger: a label, and health only as a band.
        assert_eq!(sc.perceived_of(&base), Regard { name: false, health: Precision::Band });
        // Known by name; an appraisal shows exact health while it holds.
        assert_eq!(sc.perceived_of(&RegardIn { known: true, ..base.clone() }), Regard { name: true, health: Precision::Band });
        assert_eq!(sc.perceived_of(&RegardIn { revealed: vec!["health".into()], ..base.clone() }), Regard { name: false, health: Precision::Exact });
        // Oneself: everything. Animals know their own kind by name, and not people's.
        assert_eq!(sc.perceived_of(&RegardIn { own: true, ..base.clone() }), Regard { name: true, health: Precision::Exact });
        let wolf = RegardIn { observer_kind: "wolf".into(), target_kind: "wolf".into(), ..Default::default() };
        assert!(sc.perceived_of(&wolf).name);
        assert!(!sc.perceived_of(&RegardIn { target_kind: "person".into(), ..wolf }).name);
        // The script's law and the engine's default agree; a script may decide otherwise.
        for p in [base.clone(), RegardIn { known: true, revealed: vec!["health".into()], ..base.clone() }] {
            assert_eq!(sc.perceived_of(&p), Regard::default_for(&p));
        }
        let blind = Scripts::new(&format!("{}\nfn perceived_of(p) {{ #{{ name: true, health: \"none\" }} }}", include_str!("../../scripts/skills.rhai").replace("fn perceived_of(p)", "fn perceived_of_old(p)"))).unwrap();
        assert_eq!(blind.perceived_of(&base), Regard { name: true, health: Precision::None });
    }

    #[test]
    fn appraising_reveals_health_for_a_while() {
        let sc = scripts();
        let mut c = ctx();
        c.target = TargetFacts { class: "creature".into(), id: 9, kind: "person".into(), alive: true, dist: 3.0, ..Default::default() };
        assert_eq!(sc.check("appraise", &c), Ok(()));
        assert_eq!(sc.done("appraise", &c).unwrap(), vec![Effect::Reveal { what: "health".into(), secs: 20.0 }]);
        c.target.dist = 9.0;
        assert!(sc.check("appraise", &c).is_err());
        assert_eq!(sc.laws().takeover_s, 30.0);
        // A world's own values (a seed's `rules`) over the script's: names and kinds are the laws'.
        let over = |k: &str, v: serde_json::Value| sc.laws_with(&[(k.to_string(), v)]);
        assert!(!over("cry_prompts_carers", serde_json::json!(false)).unwrap().cry_prompts_carers && sc.laws().cry_prompts_carers);
        // Every person has a mind: there is no law to turn minds off, so a seed asking for one is refused.
        assert!(over("minds", serde_json::json!(false)).unwrap_err().starts_with("`minds` is not a law of this world"));
        assert_eq!(over("fire_warmth", serde_json::json!(5)).unwrap().fire_warmth, 5.0);
        assert!(over("mindz", serde_json::json!(false)).unwrap_err().starts_with("`mindz` is not a law of this world"));
        assert!(over("cry_prompts_carers", serde_json::json!(0)).unwrap_err().contains("takes true or false"));
        // Who heard a line is kept by default (the minds' `LIVING_GREET=nearest` reads it); a world may turn it off.
        assert!(sc.laws().speech_audience && !over("speech_audience", serde_json::json!(false)).unwrap().speech_audience);
        // A speaker is told the truth about a line no one addressed could hear (on by default); a world may turn it off.
        assert!(sc.laws().speech_truth && !over("speech_truth", serde_json::json!(false)).unwrap().speech_truth);
        // Rule numbers that were Rust constants, with their values.
        let l = sc.laws();
        assert_eq!((l.follow_s, l.read_sign_m, l.kin_near_m, l.trade_window_s, l.join_window_s, l.address_m), (12.0, 8.0, 4.0, 180.0, 300.0, 6.0));
        assert_eq!((l.keep_seen_m, l.chase_lost_share, l.spawn_hunger, l.spawn_energy, l.pasture_per_tile), (1.0, 1.4, 25.0, 85.0, 0.02));
        // The longing for a child: shipped values keep the old wait (20 − nurture/6 minutes, any food).
        assert_eq!((l.longing_after_min, l.longing_food), (20.0, 0.0));
        for n in [0.0, 30.0, 60.0, 100.0] {
            assert!((longing_wait_ms(l.longing_after_min, n) - 60_000.0 * (20.0 - n / 6.0)).abs() < 0.5);
        }
        let w = over("longing_after_min", serde_json::json!(90)).unwrap();
        assert_eq!((w.longing_after_min, over("longing_food", serde_json::json!(4)).unwrap().longing_food), (90.0, 4.0));
        assert!((longing_wait_ms(90.0, 60.0) - 60_000.0 * 45.0).abs() < 0.5);
    }

    fn ctx() -> SkillCtx {
        SkillCtx {
            actor: ActorFacts { id: 1, kind: "person".into(), hp: 100.0, hunger: 50.0, energy: 80.0, terrain: "grass".into(), stamina: 100.0, focus: 100.0, ..Default::default() },
            ..Default::default()
        }
    }

    #[test]
    fn skills_say_what_they_take_and_give() {
        let s = scripts();
        let (takes, gives) = s.skill_io("eat").unwrap();
        assert!(takes.contains("food") && gives.contains("berries 12"), "{takes} / {gives}");
        assert!(s.skill_io("build").unwrap().0.contains("campfire 3 wood"));
        // Every skill says what it is, and what it takes or gives.
        for sk in s.skills().iter() {
            assert!(sk.about.len() > 20, "{} undescribed", sk.name);
            assert!(s.skill_io(&sk.name).is_some(), "{} says neither what it takes nor what it gives", sk.name);
        }
        let mut c = ctx();
        c.item = "berries".into();
        let err = s.check("eat", &c).unwrap_err();
        assert!(err.contains("berry_bush"), "{err}");
    }

    /// `cargo test -p living-rules --lib print_skill_reference -- --ignored --nocapture`
    #[test]
    #[ignore]
    fn print_skill_reference() {
        let s = scripts();
        let text = crate::catalog::skills_help_of(s.skills());
        println!("{text}\n({} chars)", text.len());
    }

    /// Breath and focus (docs/STAMINA.md): every move's cost and pool, refused with too little,
    /// the pools law's numbers, a guard as long as breath lasts, and nothing of it from energy.
    #[test]
    fn moves_cost_breath_or_focus_and_too_little_refuses_them() {
        let s = scripts();
        for (skill, pool) in [("strike", "stamina"), ("bowshot", "stamina"), ("dodge", "stamina"), ("jump", "stamina"), ("block", "stamina"), ("attack", "stamina"), ("throw", "stamina"), ("shoot", "stamina"), ("threaten", "stamina"), ("firebolt", "focus"), ("heal", "focus")] {
            let cost = s.law_value(&format!("cost_{skill}")).and_then(|v| v.as_f64()).unwrap();
            assert_eq!(s.num_of("combat_cost", skill, -1.0), cost, "{skill}: its cost is its law");
            assert_eq!(s.text_of("combat_pool", skill).as_deref(), Some(pool), "{skill}");
        }
        assert_eq!(s.text_of("pool_word", "focus").as_deref(), Some("mana"), "the screen word is the world's");
        let mut c = ctx();
        c.actor.knows = vec!["fire_bolt".into(), "wound_tending".into()];
        c.actor.inv = vec![("bow".into(), 1), ("arrow".into(), 3), ("spear".into(), 1)];
        // Out of breath: the body's moves are refused; focus is apart.
        c.actor.stamina = 4.0;
        for skill in ["dodge", "jump", "block"] {
            c.skill = skill.into();
            assert_eq!(s.check(skill, &c).unwrap_err(), "out of breath", "{skill}");
        }
        c.actor.stamina = 20.0;
        c.skill = "dodge".into();
        assert!(s.check("dodge", &c).is_ok(), "a dodge with exactly its breath");
        assert!(s.done("dodge", &c).unwrap().contains(&Effect::Spend { pool: "stamina".into(), amount: 20.0 }));
        c.skill = "jump".into();
        assert_eq!(s.done("jump", &c).unwrap(), vec![Effect::Spend { pool: "stamina".into(), amount: 10.0 }]);
        // Fire takes mana, and too little is the world's word for it; breath does not help.
        c.skill = "firebolt".into();
        c.target = TargetFacts { class: "point".into(), ..Default::default() };
        c.actor.focus = 29.0;
        c.actor.stamina = 100.0;
        assert_eq!(s.check("firebolt", &c).unwrap_err(), "not enough mana");
        c.actor.focus = 30.0;
        assert!(s.check("firebolt", &c).is_ok());
        assert!(s.done("firebolt", &c).unwrap().contains(&Effect::Spend { pool: "focus".into(), amount: 30.0 }));
        // A guard lasts as long as its breath: (breath - its cost) / 4 a second, at most its hold.
        c.skill = "block".into();
        c.qty = 8000;
        c.actor.stamina = 100.0;
        assert_eq!(s.duration_ms("block", &c).unwrap(), 8000);
        c.actor.stamina = 25.0;
        assert_eq!(s.duration_ms("block", &c).unwrap(), 5000);
        c.actor.stamina = 5.0;
        assert_eq!(s.duration_ms("block", &c).unwrap(), 200, "the briefest guard");
        assert_eq!(s.done("block", &c).unwrap(), vec![Effect::Spend { pool: "stamina".into(), amount: 5.0 }]);
        // An animal's bite takes breath too: a wolf out of breath waits for it.
        let mut w = ctx();
        w.actor.kind = "wolf".into();
        w.actor.hunger = 90.0;
        w.skill = "attack".into();
        w.target = TargetFacts { class: "creature".into(), id: 2, kind: "deer".into(), alive: true, hp: 40.0, max_hp: 40.0, dist: 1.0, ..Default::default() };
        assert!(s.check("attack", &w).is_ok());
        let bite = s.law_value("cost_attack").and_then(|v| v.as_f64()).unwrap() as f32;
        assert!(s.done("attack", &w).unwrap().contains(&Effect::Spend { pool: "stamina".into(), amount: bite }));
        w.actor.stamina = bite - 1.0;
        assert_eq!(s.check("attack", &w).unwrap_err(), "out of breath");
        // Holding a guard no longer tires (the rates of a guard are those of being awake).
        let mut g = ctx();
        g.actor.activity = "block".into();
        let mut a = ctx();
        a.actor.activity = String::new();
        assert_eq!(s.rates(&g).unwrap().energy_per_min, s.rates(&a).unwrap().energy_per_min);
    }

    /// The pools law: the shipped numbers, deer with more breath, elders' slower back, tiredness
    /// capping breath (50 at energy 0, 75 at 17.5, full from 35) and halving its refill below 10.
    #[test]
    fn the_pools_law_gives_breath_and_focus_in_real_seconds() {
        let s = scripts();
        let mut c = ctx();
        c.actor.stage = "adult".into();
        let p = s.pools(&c).unwrap();
        assert_eq!(p, crate::pools::Pools::default(), "the shipped law is the default");
        assert_eq!((p.stamina.max, p.stamina.regen_per_s, p.stamina.delay_ms, p.breath.run_per_s, p.breath.guard_per_s, p.breath.resume, p.breath.tires_per_point), (100.0, 25.0, 1000, 4.0, 4.0, 30.0, 0.02));
        assert_eq!((p.focus.max, p.focus.regen_per_s, p.focus.delay_ms), (100.0, 3.0, 2000));
        assert_eq!((p.stamina.cap(0.0), p.stamina.cap(17.5), p.stamina.cap(35.0)), (50.0, 75.0, 100.0));
        assert_eq!((p.stamina.regen(9.9), p.stamina.regen(10.0)), (12.5, 25.0));
        c.actor.stage = "elder".into();
        assert!((s.pools(&c).unwrap().stamina.regen_per_s - 17.5).abs() < 1e-4);
        c.actor.stage = "adult".into();
        c.actor.kind = "deer".into();
        assert_eq!(s.pools(&c).unwrap().stamina.max, 120.0);
        assert_eq!(s.law_plan("pools").describe(), vec!["actor.kind".to_string(), "actor.stage".to_string()], "kept per kind and stage");
        // Each number is a world law, changed on a running world with `set_world_law`.
        let src = include_str!("../../scripts/skills.rhai");
        let w = Scripts::new(&with_world_laws(src, &[("stamina_regen".into(), serde_json::json!(40)), ("cost_dodge".into(), serde_json::json!(15)), ("run_top".into(), serde_json::json!(6))])).unwrap();
        c.actor.kind = "person".into();
        assert_eq!(w.pools(&c).unwrap().stamina.regen_per_s, 40.0);
        assert_eq!(w.num_of("combat_cost", "dodge", 0.0), 15.0);
        assert_eq!(w.moves(&c).unwrap().top, 6.0);
        // A law that leaves a number out keeps the shipped one; a wrong one is refused.
        assert_eq!(decode_pools(Dynamic::from(Map::new())).unwrap(), crate::pools::Pools::default());
        let mut bad = Map::new();
        bad.insert("stamina".into(), Dynamic::from(3_i64));
        assert!(decode_pools(Dynamic::from(bad)).is_err());
    }

    /// The walk: 2.6 m/s from the narrow `walk_base` law (a player's setting changes it with
    /// `set_world_law`, and Cullet's overlay reads it too), times 0.8 when exhausted (it was 0.6),
    /// and every slowdown says why in the words a status and a mind share.
    #[test]
    fn the_walk_is_the_walk_base_law_and_a_slowed_body_says_why() {
        let src = include_str!("../../scripts/skills.rhai");
        let cullet_src = crate::floors::compose(src, include_str!("../../seeds/worlds/cullet/laws.rhai")).unwrap();
        let walk = |s: &Scripts, energy: f32| {
            let mut c = ctx();
            c.actor.stage = "adult".into();
            c.actor.energy = energy;
            c.actor.genes = Default::default();
            (s.move_speed(&c).unwrap(), s.slowed(&c))
        };
        let close = |a: f32, b: f32| (a - b).abs() < 1e-4;
        let island = Scripts::new(src).unwrap();
        let (w, why) = walk(&island, 80.0);
        assert!(close(w, 2.6) && why.is_empty(), "{w} {why}");
        let (w, why) = walk(&island, 20.0);
        assert!(close(w, 2.6) && why.is_empty(), "tired on the island: the walk is the walk");
        let (w, why) = walk(&island, 5.0);
        assert!(close(w, 2.08) && why == "exhausted, so you walk slower", "{w} {why}");
        let cullet = Scripts::new(&cullet_src).unwrap();
        let (w, why) = walk(&cullet, 20.0);
        assert!(close(w, 2.08) && why == "tired, so you walk slower", "{w} {why}");
        let (w, why) = walk(&cullet, 5.0);
        assert!(close(w, 2.08) && why == "exhausted, so you walk slower", "{w} {why}");
        // A setting of 3.0: both worlds walk faster, with the same slowdowns.
        let set = [("walk_base".to_string(), serde_json::json!(3.0))];
        assert!(close(walk(&Scripts::new(&with_world_laws(src, &set)).unwrap(), 80.0).0, 3.0));
        assert!(close(walk(&Scripts::new(&with_world_laws(&cullet_src, &set)).unwrap(), 20.0).0, 2.4));
        // The run: the `run_share` law times the walk, capped on a road at `run_top`
        // (steer::road_pace); a setting of the share changes it on a running world.
        let mut c = ctx();
        c.actor.stage = "adult".into();
        let m = island.moves(&c).unwrap();
        let share = island.law_value("run_share").and_then(|v| v.as_f64()).unwrap() as f32;
        assert!(close(m.run, share));
        let run = 2.6 * m.run;
        assert_eq!(crate::steer::road_pace(run, 1.0, &m.tuning(1.4)), (run * 1.4).min(m.top).max(run));
        // A wolf runs past the top on its own (5.1 against 4.6): a road does not slow it, and no
        // person outruns it, even on a road (intended).
        let mut w = ctx();
        w.actor.kind = "wolf".into();
        let wm = island.moves(&w).unwrap();
        let wolf = 3.4 * wm.run;
        assert!(wolf > m.top && crate::steer::road_pace(wolf, 1.0, &wm.tuning(1.4)) == wolf && crate::steer::road_pace(run, 1.0, &m.tuning(1.4)) < wolf);
        let slower = Scripts::new(&with_world_laws(src, &[("run_share".into(), serde_json::json!(1.65))])).unwrap();
        assert!(close(slower.moves(&c).unwrap().run, 1.65));
        assert!(close(crate::steer::road_pace(2.6, 1.0, &m.tuning(1.4)), 3.64), "a road walk is as fast as before");
    }

    #[test]
    fn starter_combat_skills_follow_the_rules() {
        let s = scripts();
        let mut c = ctx();
        let foe = TargetFacts { class: "creature".into(), id: 2, kind: "wolf".into(), alive: true, hp: 55.0, max_hp: 55.0, dist: 1.2, ..Default::default() };
        // A strike: a short windup, a blow and its breath (no tiredness: combat does not spend
        // energy, docs/STAMINA.md).
        c.skill = "strike".into();
        c.target = foe.clone();
        assert!(s.check("strike", &c).is_ok());
        assert_eq!(s.duration_ms("strike", &c).unwrap(), 350);
        let fx = s.done("strike", &c).unwrap();
        let (dmg, cost) = (s.law_value("dmg_strike").and_then(|v| v.as_f64()).unwrap() as f32, s.law_value("cost_strike").and_then(|v| v.as_f64()).unwrap() as f32);
        assert!(fx.iter().any(|e| matches!(e, Effect::Damage { amount } if (*amount - dmg).abs() < 1e-3)), "{fx:?}");
        assert!(fx.contains(&Effect::Spend { pool: "stamina".into(), amount: cost }), "{fx:?}");
        assert!(!fx.iter().any(|e| matches!(e, Effect::Vitals { .. })), "{fx:?}");
        // Tiredness does not refuse a blow; breath does.
        c.actor.energy = 1.0;
        assert!(s.check("strike", &c).is_ok());
        c.actor.stamina = cost - 0.1;
        assert_eq!(s.check("strike", &c).unwrap_err(), "out of breath");
        c.actor.stamina = cost;
        assert!(s.check("strike", &c).is_ok());
        c.actor.energy = 80.0;
        c.actor.stamina = 100.0;
        // A bow shot needs a bow and an arrow, launches a missile, and its hit is damage.
        c.skill = "bowshot".into();
        c.target = TargetFacts { class: "place".into(), ..Default::default() };
        assert!(s.check("bowshot", &c).unwrap_err().contains("no bow"));
        c.actor.inv = vec![("bow".into(), 1), ("arrow".into(), 2)];
        assert!(s.check("bowshot", &c).is_ok());
        assert!(s.done("bowshot", &c).unwrap().contains(&Effect::Launch));
        let m = s.missile("bowshot", &c).unwrap();
        assert!(m.speed > 10.0 && m.range >= 20.0 && m.radius > 0.0, "{m:?}");
        c.target = foe.clone();
        assert!(s.hit("bowshot", &c).unwrap().iter().any(|e| matches!(e, Effect::Damage { .. })));
        // A fire bolt needs its technique.
        c.skill = "firebolt".into();
        assert!(s.check("firebolt", &c).unwrap_err().contains("hurl fire"));
        c.actor.knows = vec!["fire".into(), "fire_bolt".into()];
        assert!(s.check("firebolt", &c).is_ok());
        // A heal: yourself or an ally, not someone fighting you, and only when hurt.
        c.skill = "heal".into();
        c.actor.knows.push("wound_tending".into());
        c.target = TargetFacts { class: "creature".into(), id: 1, kind: "person".into(), alive: true, hp: 100.0, max_hp: 100.0, ..Default::default() };
        assert_eq!(s.check("heal", &c).unwrap_err(), "you are not hurt");
        c.target.hp = 40.0;
        assert!(s.check("heal", &c).is_ok());
        c.target.id = 3;
        c.actor.hurt_by = 3;
        c.actor.hurt_ago = Some(2_000.0);
        assert_eq!(s.check("heal", &c).unwrap_err(), "they are fighting you");
        // A held guard lasts as long as it is held, up to 8 s; a graph's guard a moment.
        c.skill = "block".into();
        c.qty = 20_000;
        assert_eq!(s.duration_ms("block", &c).unwrap(), 8_000);
        c.qty = 0;
        assert_eq!(s.duration_ms("block", &c).unwrap(), 1_200);
        // Timing numbers are the rules' own.
        assert_eq!(s.shapes().bar(), ["strike", "bowshot", "firebolt", "block", "heal", "dodge", "jump"]);
        for sk in s.shapes().bar() {
            assert!(s.num_of("combat_cooldown", sk, -1.0) > 0.0, "{sk}");
        }
    }

    /// The shapes the script declares classify the existing skills exactly as the name lists
    /// they replaced (2026-11-09) did.
    #[test]
    fn combat_shapes_classify_the_existing_skills_as_before() {
        use crate::combat::Aim;
        let s = scripts();
        let sh = s.shapes();
        let names: Vec<&str> = sh.iter().map(|(n, _)| n).collect();
        let with = |t: fn(&crate::combat::Shape) -> bool| -> Vec<&str> { sh.iter().filter(|(_, x)| t(x)).map(|(n, _)| n).collect() };
        let sorted = |mut v: Vec<&'static str>| {
            v.sort();
            v
        };
        assert_eq!(with(|x| x.timed), sorted(vec!["strike", "bowshot", "firebolt", "block", "heal", "dodge", "jump", "attack", "shoot", "throw"]));
        assert_eq!(with(|x| x.missile), sorted(vec!["bowshot", "firebolt"]));
        assert_eq!(with(|x| x.aim == Aim::Point), sorted(vec!["bowshot", "firebolt"]));
        assert_eq!(with(|x| x.rooted), sorted(vec!["strike", "bowshot", "firebolt", "heal", "attack", "shoot"]));
        assert_eq!(with(|x| x.hostile), sorted(vec!["attack", "throw", "shoot", "threaten", "strike", "bowshot", "firebolt"]));
        assert_eq!(with(|x| x.force), sorted(vec!["attack", "throw", "shoot", "yield", "strike", "bowshot", "firebolt"]));
        assert_eq!(with(|x| x.dares), sorted(vec!["attack", "seize", "strike"]));
        assert_eq!(with(|x| x.melee), sorted(vec!["attack", "strike"]));
        assert_eq!(with(|x| x.closes_in), sorted(vec!["attack", "threaten", "strike"]));
        assert_eq!(with(|x| x.menace), vec!["threaten"]);
        assert_eq!(with(|x| x.aim == Aim::Dash), vec!["dodge", "jump"]);
        // A dash evades unless it says not to: the jump doesn't.
        assert_eq!(with(|x| x.evades), vec!["dodge"]);
        assert_eq!(with(|x| x.aim == Aim::Facing), vec!["block"]);
        assert_eq!(with(|x| x.aim == Aim::SelfOrAlly), vec!["heal"]);
        // Real-time behavior and reflexes, with the walking and resting skills.
        let real: Vec<&str> = s.skills().names().filter(|n| sh.real_time(n)).collect();
        let mut real = real;
        real.sort();
        assert_eq!(real, sorted(vec!["wander", "flee", "follow", "dodge", "jump", "block", "attack", "throw", "shoot", "strike", "bowshot", "firebolt", "wait", "sleep", "rest", "graze"]));
        let mut reflex: Vec<&str> = s.skills().names().filter(|n| sh.reflex(n)).collect();
        reflex.sort();
        assert_eq!(reflex, sorted(vec!["flee", "dodge", "jump", "block", "attack", "throw", "shoot", "strike", "bowshot", "firebolt", "heal", "yield"]));
        // Knacks: the starter skills share the older skills' genes.
        for (sk, k) in [("strike", "attack"), ("bowshot", "shoot"), ("firebolt", "throw"), ("heal", "tend"), ("attack", "attack"), ("gather", "gather")] {
            assert_eq!(sh.knack(sk), k);
        }
        // The guard's numbers, once in the script.
        let g = sh.get("block").unwrap();
        assert_eq!((g.hold_ms, g.arc, g.takes), (8_000, 75.0, 0.25));
        // Every combat skill has a code; codes name their skills.
        for n in &names {
            assert_eq!(sh.name(sh.code(n)), *n);
        }
        assert_eq!(names.len(), 14);
    }

    /// A combat skill the authority has never heard of works from its script alone: its
    /// shape, its missile, its check and its hit.
    #[test]
    fn a_new_skill_needs_only_the_script() {
        let src = format!(
            "{}\n{}",
            include_str!("../../scripts/skills.rhai"),
            r#"
fn icebolt_combat() { #{ aim: "point", timed: true, rooted: true, hostile: true, reflex: true, real_time: true, force: true, knack: "throw" } }
fn icebolt_check(a) { aim_check(a) }
fn icebolt_duration(a) { 400 }
fn icebolt_done(a) { [#{ op: "launch" }] + spent("icebolt") }
fn icebolt_missile(a) { #{ speed: 20.0, range: 12.0, radius: 0.3 } }
fn icebolt_hit(a) { [#{ op: "damage", amount: 9.0 * armor(a) }] }
"#
        );
        let s = Scripts::new(&src).unwrap();
        let ice = s.combat("icebolt").unwrap();
        assert!(ice.missile && ice.timed && s.shapes().real_time("icebolt") && s.shapes().reflex("icebolt"));
        assert_eq!(s.shapes().name(ice.code), "icebolt");
        assert_eq!(s.missile("icebolt", &ctx()).unwrap().range, 12.0);
        // A point skill without a missile, or a trait the engine does not know, is refused.
        let refused = |extra: &str| Scripts::new(&format!("{}\n{extra}", include_str!("../../scripts/skills.rhai"))).err().unwrap_or_default();
        assert!(refused(r#"fn zap_combat() { #{ aim: "point" } }"#).contains("zap_missile"));
        assert!(refused(r#"fn zap_combat() { #{ aim: "creature", flying: true } }"#).contains("unknown trait `flying`"));
    }

    /// Cullet's laws, goods among them (`seeds/worlds/cullet/laws.rhai`), over the shipped rules.
    fn cullet() -> Scripts {
        let src = crate::floors::compose(include_str!("../../scripts/skills.rhai"), include_str!("../../seeds/worlds/cullet/laws.rhai")).unwrap();
        Scripts::new(&src).expect("cullet laws compile")
    }

    /// A person at a structure, carrying `inv` and knowing `knows`; the structure lit with
    /// `fuel` units left (a campfire's facts say nothing of fuel).
    fn at_fire(kind: &str, lit: bool, fuel: f32, inv: &[(&str, u32)], knows: &[&str], skill: &str, item: &str, qty: u32) -> SkillCtx {
        SkillCtx {
            actor: ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), hunger: 40.0, energy: 80.0, inv: inv.iter().map(|(k, n)| (k.to_string(), *n)).collect(), knows: knows.iter().map(|k| k.to_string()).collect(), ..Default::default() },
            target: TargetFacts { class: "structure".into(), id: 7, kind: kind.into(), dist: 1.0, lit, fuel, ..Default::default() },
            item: item.into(),
            qty,
            skill: skill.into(),
            ..Default::default()
        }
    }

    /// A store holds what its kind `holds` (rules-3): the shipped storage 120 things, refused
    /// past that with the same words as before; a world's own kind of store holds its own and is
    /// found wherever a storage is asked for by name (`like`). Cullet's four stores hold theirs,
    /// and a crate anyone builds there is the shipped storage again.
    #[test]
    fn a_store_holds_what_its_kind_holds() {
        let shipped = scripts();
        let at = |kind: &str, held: u32, qty: u32| SkillCtx {
            actor: ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), inv: vec![("wood".into(), 500)], ..Default::default() },
            target: TargetFacts { class: "structure".into(), id: 7, kind: kind.into(), dist: 1.0, inv: vec![("stone".into(), held)], ..Default::default() },
            item: "wood".into(),
            qty,
            skill: "store".into(),
            ..Default::default()
        };
        let take = |kind: &str| {
            let mut c = at(kind, 3, 1);
            (c.item, c.skill, c.actor.inv) = ("stone".into(), "take".into(), Vec::new());
            c
        };
        assert_eq!(shipped.structure("storage").holds, Some(120.0));
        assert!(shipped.check("store", &at("storage", 100, 20)).is_ok());
        assert_eq!(shipped.check("store", &at("storage", 100, 21)).unwrap_err(), "the storage is full (it holds 100 of 120 things)");
        assert_eq!(shipped.check("store", &at("house", 0, 1)).unwrap_err(), "can only store in a storage");
        assert!(shipped.check("take", &take("storage")).is_ok());
        assert_eq!(shipped.check("take", &take("house")).unwrap_err(), "nothing to take from");
        assert!(shipped.skills().get("store").unwrap().takes.contains("(a storage holds 120 things in all)"));
        // A world's own store: its size, and a storage wherever one is asked for by name.
        let src = crate::floors::compose(include_str!("../../scripts/skills.rhai"), r#"fn structures() { base_structures() + [#{ name: "barn", like: "storage", holds: 500 }] }"#).unwrap();
        let w = Scripts::new(&src).unwrap();
        w.validate().unwrap();
        assert!(w.check("store", &at("barn", 400, 100)).is_ok() && w.check("store", &at("storage", 100, 21)).is_err());
        assert_eq!(w.check("store", &at("barn", 400, 101)).unwrap_err(), "the storage is full (it holds 400 of 500 things)");
        assert!(w.check("take", &take("barn")).is_ok());
        assert!(w.is_kind("barn", "storage") && w.is_kind("storage", "storage") && !w.is_kind("storage", "barn") && !w.is_kind("house", "storage") && !shipped.is_kind("barn", "storage"));
        assert!(w.skills().get("store").unwrap().takes.contains("(a storage holds 120 things in all; a barn 500)"));
        let refused = |extra: &str| Scripts::new(&crate::floors::compose(include_str!("../../scripts/skills.rhai"), extra).unwrap()).err().unwrap_or_default();
        assert!(refused(r#"fn structures() { base_structures() + [#{ name: "barn", like: "silo", holds: 5 }] }"#).contains("`like` of `barn` is `silo`"));
        assert!(refused(r#"fn structures() { base_structures() + [#{ name: "barn", holds: -1 }] }"#).contains("`holds` of `barn`"));
        // Cullet's stores.
        let c = cullet();
        let holds: Vec<(&str, Option<f32>, bool)> = ["store", "peat_barn", "yard_store", "house_store", "storage"].iter().map(|k| (*k, c.structure(k).holds, c.is_kind(k, "storage"))).collect();
        assert_eq!(holds, vec![("store", Some(1200.0), true), ("peat_barn", Some(1000.0), true), ("yard_store", Some(900.0), true), ("house_store", Some(150.0), true), ("storage", Some(120.0), true)]);
        assert!(!c.has("storage_holds") && !shipped.has("storage_holds"));
        assert_eq!(c.check("store", &at("house_store", 100, 51)).unwrap_err(), "the storage is full (it holds 100 of 150 things)");
    }

    /// Regrowth by season is a value on each resource kind (rules-3): the shipped kinds have
    /// none, so they regrow fully outside winter and not at all in it, as before; a kind's
    /// `regrow_by_season` changes the seasons it names. Cullet's fish keep regrowing in winter,
    /// its root plots rest; and minds are told what winter does from the same table.
    #[test]
    fn regrowth_by_season_is_a_value_on_each_kind() {
        let shipped = scripts();
        for k in shipped.tables().names("resources") {
            assert_eq!(shipped.regrow_seasons(k), crate::GROWING, "{k}");
        }
        assert_eq!(shipped.regrow_seasons("no_such_kind"), crate::GROWING);
        assert_eq!(shipped.seasons_words(), "In winter nothing regrows and nights are colder: store food before it.");
        let c = cullet();
        let by = |k: &str| c.regrow_seasons(k);
        assert_eq!((by("fishing_spot"), by("weir"), by("kelp_bed"), by("greens_bed")), ([1.0, 1.0, 1.0, 0.75], [1.0, 1.0, 1.0, 0.75], [1.0, 1.0, 1.0, 1.25], [1.0, 1.0, 1.0, 0.5]));
        assert_eq!((by("root_plot"), by("sand_bank"), by("peat_bank"), by("tree"), by("berry_bush")), (crate::GROWING, [1.0; 4], crate::GROWING, crate::GROWING, crate::GROWING));
        assert_eq!(c.seasons_words(), "In winter kelp_bed and sand_bank regrow as in the other seasons or more, fishing_spot, greens_bed and weir more slowly, and berry_bush, tree, boulder, reeds, clay_bank, peat_bank and root_plot not at all. Nights are colder: store food before it.");
        c.validate().unwrap();
        // A season named wrong, or a share that is no number, is refused.
        let refused = |extra: &str| Scripts::new(&crate::floors::compose(include_str!("../../scripts/skills.rhai"), extra).unwrap()).err().unwrap_or_default();
        assert!(refused(r#"fn resources() { base_resources() + [#{ name: "kelp_bed", yields: "fish", regrow_per_h: 0.1, max: 2.0, regrow_by_season: #{ monsoon: 1.0 } }] }"#).contains("`monsoon`, which is no season"));
        assert!(refused(r#"fn resources() { base_resources() + [#{ name: "kelp_bed", yields: "fish", regrow_per_h: 0.1, max: 2.0, regrow_by_season: #{ winter: "lots" } }] }"#).contains("regrow_by_season.winter"));
        // A Cullet winter's day: a fishing ground regrows three quarters of a day's rate, a root
        // plot nothing (the regrowth the authority applies, `common::amount_now`).
        let (day, epoch) = (crate::cullet_check::CULLET_DAY_MS, 1_000_000u64);
        let w0 = epoch + day * 6 - day * 7 / 24;
        let grown = |k: &str| crate::regrowth_ms(w0, w0 + day, epoch, day, crate::YEAR_DAYS, &c.regrow_seasons(k)) as f64 / day as f64;
        assert_eq!((grown("fishing_spot"), grown("root_plot"), grown("kelp_bed")), (0.75, 0.0, 1.25));
    }

    /// Goods are data with traits, and the rules match by trait: a fire burns whatever has its
    /// fuel trait, glass takes any alkali, food is what has nutrition. A fire is lit only while
    /// it holds fuel; feeding an out one takes knowing fire; recipes needing heat need it burning
    /// and draw their fuel from it. The shipped world offers neither feeding nor making (it has
    /// no such fires or recipes), and installs with Cullet's goods pass the install checks.
    #[test]
    fn goods_are_data_matched_by_trait_and_fires_eat_fuel() {
        let shipped = scripts();
        let s = cullet();
        let r = s.validate().unwrap();
        let (f, n) = r.heaviest().unwrap();
        assert!(n * 2 <= LIMITS.operations, "{f} takes {n} operations; the limit is {}", LIMITS.operations);
        // `--nocapture` prints what the goods' laws cost (docs/WORLD_RULES.md, "Goods, recipes and fuel").
        let base = shipped.validate().unwrap();
        for k in ["feed_check", "feed_done", "make_check", "make_done", "make_duration", "cook_check", "smoke_check", "gather_duration", "store_check", "eat_check", "source_of"] {
            eprintln!("ops {k:16} shipped {:>5} cullet {:>5}", base.ops.get(k).copied().unwrap_or(0), r.ops.get(k).copied().unwrap_or(0));
        }
        eprintln!("heaviest: shipped {:?}, cullet {:?}; calls {} / {}", base.heaviest(), r.heaviest(), base.calls, r.calls);
        let listed = |s: &Scripts, k: &str| s.skills().get(k).unwrap().listed;
        assert!(!listed(&shipped, "feed") && !listed(&shipped, "make") && listed(&s, "feed") && listed(&s, "make"));
        assert_eq!(s.skills().get("make").unwrap().items, ["ash", "glass", "pane", "float", "bottle", "mark", "pot", "crucible", "mould", "smoked_fish", "smoked_meat", "baked_roots", "lamp_oil"]);
        assert!(s.skills().resources.iter().any(|k| k.name == "peat_bank" && k.traits["yields"] == "peat"));
        assert_eq!(s.structure("furnace").burns.as_ref().map(|b| (b.fuel.as_str(), b.rate, b.holds)), Some(("fuel", 3.0, Some(40.0))));
        assert!(s.structure("hearth").fire() && s.structure("campfire").fire() && !s.structure("house").fire() && !s.structure("storage").fire());
        let go = |c: &SkillCtx| s.check(&c.skill, c).and_then(|_| s.done(&c.skill, c));
        // Feeding: peat and wood both burn in a hearth (each has the `fuel` trait); oil does not.
        assert_eq!(go(&at_fire("hearth", false, 0.0, &[("peat", 3)], &["fire"], "feed", "peat", 3)).unwrap(), vec![Effect::Fuel { item: "peat".into(), qty: 3 }]);
        assert_eq!(go(&at_fire("hearth", true, 2.0, &[("wood", 2), ("kelp", 1)], &[], "feed", "fuel", 1)).unwrap(), vec![Effect::Fuel { item: "wood".into(), qty: 1 }]);
        assert!(go(&at_fire("hearth", true, 2.0, &[("lamp_oil", 1)], &[], "feed", "lamp_oil", 1)).unwrap_err().contains("not fuel for the hearth (it burns wood or peat)"));
        assert_eq!(go(&at_fire("lamp", false, 0.0, &[("lamp_oil", 1)], &["fire"], "feed", "fuel", 1)).unwrap(), vec![Effect::Fuel { item: "lamp_oil".into(), qty: 1 }]);
        // An out fire is lit again only by someone who knows fire; a lit one by anyone; a fire
        // holds what it holds; a campfire burns no fuel.
        assert!(go(&at_fire("hearth", false, 0.0, &[("peat", 3)], &[], "feed", "peat", 1)).unwrap_err().contains("is out, and you don't know how to light a fire"));
        assert!(go(&at_fire("hearth", true, 1.0, &[("peat", 3)], &[], "feed", "peat", 1)).is_ok());
        assert!(go(&at_fire("hearth", true, 11.0, &[("peat", 3)], &["fire"], "feed", "peat", 2)).unwrap_err().contains("holds at most 12 units"));
        assert_eq!(go(&at_fire("campfire", true, 0.0, &[("wood", 3)], &["fire"], "feed", "wood", 1)).unwrap_err(), "the campfire burns no fuel");
        // Kelp burnt to ash at any burning fire, a campfire too, not at an out hearth.
        let ash = vec![Effect::Remove { item: "kelp".into(), qty: 4 }, Effect::Add { item: "ash".into(), qty: 1 }, Effect::Vitals { hp: 0.0, hunger: 0.0, energy: -1.0 }];
        assert_eq!(go(&at_fire("hearth", true, 3.0, &[("kelp", 5)], &[], "make", "ash", 0)).unwrap(), ash);
        assert_eq!(go(&at_fire("campfire", false, 0.0, &[("kelp", 4)], &[], "make", "ash", 0)).unwrap(), ash);
        assert!(go(&at_fire("hearth", false, 0.0, &[("kelp", 4)], &[], "make", "ash", 0)).unwrap_err().contains("is out: feed it first"));
        assert!(go(&at_fire("hearth", true, 3.0, &[("kelp", 3)], &[], "make", "ash", 0)).unwrap_err().starts_with("ash takes 4 kelp (kelp: gather it at a kelp_bed"));
        // Glass: an alkali and sand at a burning furnace, with a unit of its fuel, by those who
        // know glassmaking, melted in a crucible they keep (goods-3).
        let glass = at_fire("furnace", true, 3.0, &[("ash", 1), ("sand", 3), ("crucible", 1)], &["glassmaking"], "make", "glass", 0);
        assert_eq!(go(&glass).unwrap(), vec![Effect::Remove { item: "ash".into(), qty: 1 }, Effect::Remove { item: "sand".into(), qty: 2 }, Effect::Burn { units: 1.0 }, Effect::Add { item: "glass".into(), qty: 1 }, Effect::Vitals { hp: 0.0, hunger: 0.0, energy: -1.0 }]);
        assert!(go(&SkillCtx { target: TargetFacts { fuel: 0.5, ..glass.target.clone() }, ..glass.clone() }).unwrap_err().contains("too little fuel left"));
        assert!(go(&SkillCtx { target: TargetFacts { lit: false, fuel: 0.0, ..glass.target.clone() }, ..glass.clone() }).unwrap_err().contains("is out"));
        assert_eq!(go(&SkillCtx { target: TargetFacts { kind: "hearth".into(), ..glass.target.clone() }, ..glass.clone() }).unwrap_err(), "glass is made at a furnace");
        assert!(go(&SkillCtx { actor: ActorFacts { knows: vec![], ..glass.actor.clone() }, ..glass.clone() }).unwrap_err().starts_with("you don't know how to make glass"));
        assert_eq!(s.text_of("source_of", "glass").unwrap(), "make it at a furnace from 1 alkali, 2 sand and 1 fuel from it, using a crucible (knowing glassmaking)");
        // Without the crucible, refused naming it and how one is come by.
        assert_eq!(go(&SkillCtx { actor: ActorFacts { inv: vec![("ash".into(), 1), ("sand".into(), 3)], ..glass.actor.clone() }, ..glass.clone() }).unwrap_err(), "glass is made with a crucible in your pack, not used up (crucible: make it at an oven from 3 clay and 0.5 fuel from it (knowing toolmaking))");
        // Any alkali serves: a world's soda is used like ash, by the trait alone.
        let overlay = include_str!("../../seeds/worlds/cullet/laws.rhai").replace("#{ name: \"sand\", icon: \"sand\", label: \"sand\", group: \"material\" },", "#{ name: \"sand\", icon: \"sand\", label: \"sand\", group: \"material\" }, #{ name: \"soda\", alkali: true },");
        let soda = Scripts::new(&crate::floors::compose(include_str!("../../scripts/skills.rhai"), &overlay).unwrap()).unwrap();
        let c = at_fire("furnace", true, 3.0, &[("soda", 2), ("sand", 2), ("crucible", 1)], &["glassmaking"], "make", "glass", 0);
        assert_eq!(soda.check("make", &c).and_then(|_| soda.done("make", &c)).unwrap()[0], Effect::Remove { item: "soda".into(), qty: 1 });
        // Turning an item by its trait: fish smoked over peat at a smokehouse, roots baked.
        assert_eq!(go(&at_fire("smokehouse", true, 4.0, &[("fish", 2)], &["smoking"], "make", "smoked_fish", 0)).unwrap()[..3], [Effect::Remove { item: "fish".into(), qty: 1 }, Effect::Burn { units: 0.5 }, Effect::Add { item: "smoked_fish".into(), qty: 1 }]);
        assert_eq!(go(&at_fire("oven", true, 4.0, &[("roots", 1)], &[], "make", "baked_roots", 0)).unwrap()[..3], [Effect::Remove { item: "roots".into(), qty: 1 }, Effect::Burn { units: 0.25 }, Effect::Add { item: "baked_roots".into(), qty: 1 }]);
        assert_eq!(go(&at_fire("oven", true, 4.0, &[("roots", 1)], &[], "make", "glass_beads", 0)).unwrap_err(), "no one makes glass_beads at a workplace");
        assert_eq!(go(&at_fire("oven", true, 4.0, &[("roots", 1)], &[], "make", "spear", 0)).unwrap_err(), "no one makes spear at a workplace (spear: craft it (1 stone, 2 wood))");
        // A lamp burns oil for light and is no fire to cook at (goods-3).
        assert_eq!(go(&at_fire("lamp", true, 4.0, &[("fish", 1)], &["cooking"], "cook", "fish", 1)).unwrap_err(), "cooking needs a campfire");
        // Cooking works at a burning hearth as at a campfire, not at an out one.
        assert!(go(&at_fire("hearth", true, 1.0, &[("fish", 1)], &["cooking"], "cook", "fish", 1)).is_ok());
        assert!(go(&at_fire("hearth", false, 0.0, &[("fish", 1)], &["cooking"], "cook", "fish", 1)).unwrap_err().contains("is out"));
        // Food is what has nutrition: roots feed, peat does not.
        assert!(go(&at_fire("hearth", true, 1.0, &[("roots", 1)], &[], "eat", "roots", 1)).is_ok());
        assert_eq!(go(&at_fire("hearth", true, 1.0, &[("peat", 1)], &[], "eat", "peat", 1)).unwrap_err(), "peat is not food");
        // The minds' world text names the fires and the recipes; the shipped world's does not.
        let text = s.world_text(&[]);
        assert!(text.contains("a furnace burns 3 fuel a game hour (wood or peat)") && text.contains("glass: make it at a furnace"), "{text}");
        assert!(!shipped.world_text(&[]).contains("Fires that burn fuel"));
    }

    /// Everything made is a recipe in one table, made by one mechanism through four ways in
    /// (recipes-1): craft, cook and smoke keep their names, items and words; a recipe grid reads
    /// what each way makes as data; a cell greys with the rules' own words when only its inputs
    /// are missing; and a world whose recipes leave the shipped ones out offers no cooking.
    #[test]
    fn making_is_one_mechanism_through_four_ways() {
        let (island, c) = (scripts(), cullet());
        // What each way makes, and what its acts name.
        assert_eq!(island.products_of("craft"), ["spear", "cloak", "torch", "axe", "pick", "net", "basket", "bow", "arrow", "salve", "leather", "armor"]);
        assert_eq!(island.products_of("cook"), ["cooked_fish", "cooked_meat"]);
        assert_eq!(island.products_of("smoke"), ["smoked_fish", "smoked_meat"]);
        assert!(island.products_of("make").is_empty() && island.products_of("eat").is_empty());
        assert_eq!(c.products_of("make"), ["ash", "glass", "pane", "float", "bottle", "mark", "pot", "crucible", "mould", "smoked_fish", "smoked_meat", "baked_roots", "lamp_oil"]);
        assert_eq!(c.products_of("cook"), island.products_of("cook"), "Cullet's people cook as the island's do");
        assert_eq!((island.making_item("cook", "cooked_meat"), island.making_item("craft", "arrow"), c.making_item("make", "smoked_fish")), (Some("meat"), Some("arrow"), Some("smoked_fish")));
        assert_eq!(island.making_item("cook", "spear"), None);
        // A grid cell's parts, as data.
        let glass = c.recipe_parts("make", "glass").unwrap();
        fn part(p: &RecipePart) -> (&str, u32, Vec<String>) {
            (p.name.as_str(), p.qty, p.any_of.clone())
        }
        assert_eq!(glass.takes.iter().map(part).collect::<Vec<_>>(), [("alkali", 1, vec!["ash".to_string()]), ("sand", 2, vec!["sand".to_string()])]);
        assert_eq!((glass.at.as_str(), glass.lit, glass.fuel, glass.knows.as_str(), glass.ms, glass.makes), ("furnace", true, 1.0, "glassmaking", 15000, 1));
        // What it is made with and keeps (goods-3): by name, or by trait (any vessel).
        assert_eq!(glass.tools.iter().map(part).collect::<Vec<_>>(), [("crucible", 1, vec!["crucible".to_string()])]);
        let oil = c.recipe_parts("make", "lamp_oil").unwrap();
        assert_eq!(oil.tools.iter().map(part).collect::<Vec<_>>(), [("vessel", 1, vec!["bottle".to_string(), "pot".to_string()])]);
        assert_eq!((oil.tools[0].look.label.as_str(), c.recipe_parts("make", "float").unwrap().tools[0].look.label.as_str()), ("vessel", "blowpipe"));
        assert_eq!((glass.look.label.as_str(), glass.takes[1].look.label.as_str()), ("glass", "sand"));
        let cook = island.recipe_parts("cook", "cooked_fish").unwrap();
        assert_eq!((cook.item.as_str(), cook.takes.iter().map(part).collect::<Vec<_>>(), cook.at.as_str(), cook.lit, cook.knows.as_str(), cook.ms), ("fish", vec![("fish", 1, vec!["fish".to_string()])], "fire", true, "cooking", 4000));
        let arrow = island.recipe_parts("craft", "arrow").unwrap();
        assert_eq!((arrow.makes, arrow.at.as_str(), arrow.lit, arrow.ms, arrow.look.group.as_str()), (3, "", false, 8000, "weapon"));
        assert_eq!(island.text_of("made_how", "cooked_fish").unwrap(), "cook it at a fire from 1 fish (knowing cooking)");
        assert_eq!(island.text_of("made_how", "spear").unwrap(), "craft it from 1 stone, 2 wood (knowing spear)");
        assert_eq!(c.text_of("made_how", "glass").unwrap(), "make it at a furnace from 1 alkali, 2 sand and 1 fuel from it, using a crucible (knowing glassmaking)");
        assert_eq!(c.text_of("made_how", "lamp_oil").unwrap(), "make it at a fire from 2 fish, using a vessel");
        // The grids are declared: each way's cells are its products, described in its words.
        for (w, s) in [("island", &island), ("cullet", &c)] {
            for skill in ["craft", "cook", "smoke"] {
                let u = s.ui(skill).unwrap();
                assert_eq!((u.choose, u.source, u.detail.as_deref()), (crate::ui::Choose::Grid, Some(crate::ui::ItemSource::Products), Some("made_how")), "{w} {skill}");
            }
        }
        // A cell greys with the check's own words when only its inputs are missing, and the act
        // passes once the pack holds them: for every product of every way, in both worlds.
        for (w, s) in [("island", &island), ("cullet", &c)] {
            let names = s.tables().names("know_how").to_vec();
            let know: Vec<&str> = names.iter().map(|k| k.as_str()).collect();
            for skill in ["craft", "cook", "smoke", "make"] {
                for p in s.products_of(skill) {
                    let r = s.recipe_parts(skill, p).unwrap();
                    let at = match r.at.as_str() { "" | "fire" => "campfire", k => k };
                    let takes: Vec<(&str, u32)> = r.takes.iter().map(|t| (t.any_of[0].as_str(), t.qty)).collect();
                    let have: Vec<(&str, u32)> = takes.iter().cloned().chain(r.tools.iter().map(|t| (t.any_of[0].as_str(), t.qty))).collect();
                    let without = s.check(skill, &at_fire(at, true, 6.0, &[], &know, skill, &r.item, 1)).unwrap_err();
                    assert!(!without.is_empty() && !without.contains("{"), "{w}: {skill} {p} without its inputs: {without:?}");
                    // Without its tools, refused in the way's words naming the tool (goods-3).
                    if let Some(t) = r.tools.first() {
                        let no_tool = s.check(skill, &at_fire(at, true, 6.0, &takes, &know, skill, &r.item, 1)).unwrap_err();
                        assert!(no_tool.contains(&format!("a {}", t.name)) && !no_tool.contains("{"), "{w}: {skill} {p} without its tool: {no_tool:?}");
                    }
                    s.check(skill, &at_fire(at, true, 6.0, &have, &know, skill, &r.item, 1)).unwrap_or_else(|e| panic!("{w}: {skill} {p} with its inputs: {e}"));
                }
            }
        }
        assert_eq!(island.check("cook", &at_fire("campfire", true, 0.0, &[], &["cooking"], "cook", "fish", 1)).unwrap_err(), "no fish in your pack (fish: gather it at a fishing_spot, or take it from a storage)");
        assert_eq!(island.check("craft", &at_fire("campfire", true, 0.0, &[("wood", 2)], &["spear"], "craft", "spear", 1)).unwrap_err(), "need 1 stone for a spear (stone: gather it at a boulder, or take it from a storage)");
        // A world whose recipes leave out the shipped ones makes nothing by them, and is not
        // offered crafting, cooking or smoking (its own overlay must add `base_recipes()`).
        let bare = Scripts::new(&crate::floors::compose(include_str!("../../scripts/skills.rhai"), "fn recipes() { [#{ name: \"ash\", at: \"fire\", lit: true, takes: #{ wood: 2 } }] }").unwrap()).unwrap();
        assert!(bare.products_of("cook").is_empty() && !bare.skills().get("cook").unwrap().listed && !bare.skills().get("craft").unwrap().listed);
        assert_eq!(bare.products_of("make"), ["ash"]);
        // Building is recipes too (goods-3): such a world builds nothing either.
        assert!(!bare.skills().get("build").unwrap().listed);
    }

    /// Every item says how a client shows it (`icon`, `label`, `group`), as data no rule reads;
    /// what a recipe makes looks like its product unless the recipe says otherwise; a look that
    /// is not text is refused at install.
    #[test]
    fn items_and_recipes_say_how_they_look() {
        let look = |icon: &str, label: &str, group: &str| Some(ItemLook { icon: icon.into(), label: label.into(), group: group.into() });
        for s in [scripts(), cullet()] {
            let t = s.tables();
            for n in t.names("items") {
                let e = t.entry("items", n).unwrap();
                for k in ITEM_LOOK {
                    assert!(e.get(k).and_then(|v| v.clone().into_string().ok()).is_some_and(|v| !v.is_empty()), "item {n} has no {k}");
                }
                // Within the interface's vocabulary (`living_rules::ui`).
                let text = |k: &str| e[k].clone().into_string().unwrap();
                assert!(crate::ui::ITEM_ICONS.contains(&text("icon").as_str()), "item {n}: icon {} is not in ui::ITEM_ICONS", text("icon"));
                assert!(crate::ui::ITEM_GROUPS.contains(&text("group").as_str()), "item {n}: group {} is not in ui::ITEM_GROUPS", text("group"));
            }
        }
        let (shipped, s) = (scripts(), cullet());
        assert_eq!(shipped.item_look_of("item_look", "cooked_fish"), look("cooked_fish", "cooked fish", "food"));
        assert_eq!(s.item_look_of("item_look", "lamp_oil"), look("lamp_oil", "lamp oil", "fuel"));
        assert_eq!(s.item_look_of("item_look", "glass"), look("glass", "glass", "glass"));
        // An item without looks (a world's own, from before): its name, spaced; no group.
        assert_eq!(s.item_look_of("item_look", "glass_beads"), look("glass_beads", "glass beads", ""));
        // A recipe looks like its product, a recipe that turns items like each product.
        assert_eq!(s.item_look_of("recipe_look", "glass"), s.item_look_of("item_look", "glass"));
        assert_eq!(s.item_look_of("recipe_look", "smoked_meat"), look("smoked_meat", "smoked meat", "food"));
        let over = include_str!("../../seeds/worlds/cullet/laws.rhai").replace("#{ name: \"lamp_oil\", at: \"fire\",", "#{ name: \"lamp_oil\", label: \"rendered oil\", icon: \"oil_jar\", at: \"fire\",");
        let over = Scripts::new(&crate::floors::compose(include_str!("../../scripts/skills.rhai"), &over).unwrap()).unwrap();
        assert_eq!(over.item_look_of("recipe_look", "lamp_oil"), look("oil_jar", "rendered oil", "fuel"));
        assert_eq!(over.item_look_of("item_look", "lamp_oil"), look("lamp_oil", "lamp oil", "fuel"));
        let bad = include_str!("../../scripts/skills.rhai").replace("#{ name: \"berries\", icon: \"berries\",", "#{ name: \"berries\", icon: 3,");
        assert_eq!(Scripts::new(&bad).err().unwrap(), "items: the icon of `berries` must be a text");
    }

    /// Teaching takes the world's know-how table, not only what experimenting can reveal, so
    /// Cullet's glassmaking and the shipped fire_bolt and wound_tending can be taught. Every
    /// technique the old list had answers as before; the minds are told every technique.
    #[test]
    fn teaching_takes_the_worlds_know_how() {
        let (shipped, s) = (scripts(), cullet());
        let teach = |s: &Scripts, item: &str, knows: &[&str], theirs: &[&str]| {
            let mut c = ctx();
            c.skill = "teach".into();
            c.item = item.into();
            c.actor.knows = knows.iter().map(|k| k.to_string()).collect();
            c.target = TargetFacts { class: "creature".into(), kind: "person".into(), id: 9, alive: true, stage: "adult".into(), knows: theirs.iter().map(|k| k.to_string()).collect(), ..Default::default() };
            s.check("teach", &c)
        };
        assert_eq!(teach(&s, "glassmaking", &["glassmaking"], &["fire"]), Ok(()));
        assert_eq!(teach(&s, "glassmaking", &["glassmaking"], &[]).unwrap_err(), "they must first learn fire");
        assert_eq!(teach(&s, "glassmaking", &[], &["fire"]).unwrap_err(), "you don't know glassmaking yourself");
        assert_eq!(teach(&shipped, "glassmaking", &["glassmaking"], &["fire"]).unwrap_err().split(" (").next(), Some("there is no technique called glassmaking"));
        for t in ["fire_bolt", "wound_tending"] {
            assert_eq!(teach(&shipped, t, &[t], &[]), Ok(()));
        }
        assert!(teach(&s, "glass", &[], &[]).unwrap_err().contains("there is no technique called glass (the techniques are: fire, cooking"));
        // The minds' world text names every technique of the table, with its brief.
        let about = |s: &Scripts| s.law_specs()["know_how"].about.clone();
        let (a, b) = (about(&shipped), about(&s));
        assert!(a.starts_with("you can only do techniques you know: fire (campfire), cooking, spear, shelter, storage, cloak (2 hides from hunted deer + 1 fiber; keeps you warm at night), torch (lights the night, you see farther), planting (grow new berry bushes), writing (write and read tablets and signs), masonry (walls), carpentry (houses and gates; needs shelter), fishing,"), "{a}");
        for t in s.skills().techniques.iter() {
            assert!(b.contains(&t.name), "{} is not in {b}", t.name);
        }
        assert!(b.contains("toolmaking (axe, pick; pots, crucibles and drop moulds of fired clay), glassmaking (glass from ash and sand at the furnace, and panes, floats, bottles and drops). Others may know"), "{b}");
    }

    /// Others see someone making at a workplace or feeding a fire, players and minds alike;
    /// the authority and a client read a fire's state through one primitive.
    #[test]
    fn making_and_feeding_are_seen_and_a_fire_state_is_shared() {
        let s = cullet();
        for k in ["make", "feed"] {
            assert_eq!(s.shows().get(k).map(|x| x.look.as_str()), Some("work"));
        }
        let day = 48 * 60_000;
        let furnace = s.structure("furnace");
        // 3 units a game hour on a 48-minute day: a unit lasts 40 s.
        assert_eq!(furnace.fire_state(140_000, 100_000, day), (true, 1.0));
        assert_eq!(furnace.fire_state(100_000, 100_000, day), (false, 0.0));
        assert_eq!(s.structure("campfire").fire_state(0, 100_000, day), (true, 0.0));
        assert_eq!(s.structure("house").fire_state(0, 100_000, day), (false, 0.0));
    }

    /// A skill added only in the script (its spec and rules) is one a graph, an act and a
    /// mind's prompt take, with no Rust change; without a spec an install refuses it.
    #[test]
    fn a_skill_added_only_in_the_script_is_everyones() {
        let shipped = include_str!("../../scripts/skills.rhai");
        let whittle = r#"
fn whittle_spec() { #{ item: true, items: ["wood"], reach: 0.0, about: "Carve a piece of wood into a peg while you sit.", takes: "1 wood", gives: "a peg (nothing yet uses it)" } }
fn whittle_check(a) { if inv(a, "wood") < 1 { return "no wood to whittle"; } "" }
fn whittle_duration(a) { 3000 }
fn whittle_done(a) { [#{ op: "remove", item: "wood", qty: 1 }] }
"#;
        let s = Scripts::new(&format!("{shipped}
{whittle}")).unwrap();
        let spec = s.skills().get("whittle").expect("declared");
        assert!(spec.needs_item && !spec.needs_target && spec.items == ["wood"]);
        crate::catalog::scoped(s.skills().clone(), || {
            // A graph leaf and a deliberate act.
            let (g, _) = crate::normalize::graph(serde_json::json!({"do": "whittle", "item": "wood"})).unwrap();
            crate::graph::from_value(g).unwrap();
            let a = crate::acts::parse(serde_json::json!({"do": "whittle", "item": "wood"}), None, s.shapes()).unwrap();
            assert_eq!(a.skill, "whittle");
            // A mind's skill reference.
            assert!(crate::catalog::skills_help().contains("- whittle(item: wood): Carve a piece of wood"), "{}", crate::catalog::skills_help());
        });
        // Under the shipped skills it is unknown.
        crate::catalog::scoped(scripts().skills().clone(), || assert!(crate::normalize::graph(serde_json::json!({"do": "whittle", "item": "wood"})).is_err()));
        // Rules without a spec are refused at install; a spec without a description too.
        let bare = Scripts::new(&format!("{shipped}
{}", whittle.lines().filter(|l| !l.contains("whittle_spec")).collect::<Vec<_>>().join("\n"))).unwrap();
        assert!(bare.validate().unwrap_err().contains("`whittle` has rules but no `whittle_spec()`"));
        let mute = Scripts::new(&format!("{shipped}
fn hum_spec() {{ #{{ target: false }} }}")).err().unwrap_or_default();
        assert!(mute.contains("`about` describes the skill"), "{mute}");
    }

    /// Agreements and demands are content on records: made by a skill, settled by hooks and
    /// by their falling due, each side told in its own terms.
    #[test]
    fn agreements_and_demands_are_rules_on_records() {
        use crate::records::RecordFacts;
        let s = scripts();
        let person = |id: u64, home: &str| TargetFacts { class: "creature".into(), id, kind: "person".into(), alive: true, dist: 1.0, stage: "adult".into(), home: home.into(), ..Default::default() };
        let me = |id: u32, home: &str| ActorFacts { id, kind: "person".into(), stage: "adult".into(), hp: 100.0, energy: 80.0, home: home.into(), ..Default::default() };
        let tells = |fx: &[Effect]| fx.iter().filter_map(|e| if let Effect::Tell { to, text, .. } = e { Some((*to, text.clone())) } else { None }).collect::<Vec<_>>();
        // A resident (1, home 10,10) offers 3 berries for 10 wood stacked at its store.
        let mut c = SkillCtx { actor: me(1, "10,10"), target: person(9, "40,12"), item: "berries".into(), qty: 3, want: "wood".into(), want_qty: 10, text: "stack it at my store".into(), hour: 14.0, skill: "offer_terms".into(), ..Default::default() };
        assert_eq!(s.check("offer_terms", &c), Ok(()));
        let fx = s.done("offer_terms", &c).unwrap();
        let Some(Effect::Record { kind, status, parties, terms, due_h }) = fx.first().cloned() else { panic!("{fx:?}") };
        assert_eq!((kind.as_str(), status.as_str(), parties.clone()), ("agreement", "offered", vec![("from".to_string(), 1), ("to".to_string(), 9)]));
        assert_eq!(terms["to_home"], "40,12");
        assert!(due_h.is_some_and(|h| h > 0.0));
        assert!(tells(&fx).iter().any(|(to, t)| *to == 9 && t.contains("you give 10 wood, they give 3 berries")), "{fx:?}");
        let rec = |status: &str, me: &str, from_done: i64, to_done: i64| RecordFacts { id: 5, kind: "agreement".into(), status: status.into(), open: true, terms: { let mut t = terms.clone(); t.insert("from_done".into(), from_done.into()); t.insert("to_done".into(), to_done.into()); t }, parties: parties.clone(), me: me.into(), by: 1, ..Default::default() };
        // The newcomer (9) accepts: the record is agreed, due at the first dusk at least
        // `agreement_min_h` (12) hours away: accepted at 7:00, tonight's (13 h); at 14:00,
        // tomorrow's (30 h), told as such.
        c = SkillCtx { actor: me(9, "40,12"), target: person(1, "10,10"), hour: 7.0, skill: "accept".into(), records: vec![rec("offered", "to", 0, 0)], ..Default::default() };
        let fx = s.done("accept", &c).unwrap();
        assert!(matches!(&fx[0], Effect::Amend { id: 5, status: Some(st), due_h: Some(h), .. } if st == "agreed" && (*h - 13.0).abs() < 1e-3), "{fx:?}");
        assert!(tells(&fx).iter().any(|(to, t)| *to == 1 && t.ends_with("by dusk today.")), "{fx:?}");
        c.hour = 14.0;
        let fx = s.done("accept", &c).unwrap();
        assert!(matches!(&fx[0], Effect::Amend { id: 5, status: Some(st), due_h: Some(h), .. } if st == "agreed" && (*h - 30.0).abs() < 1e-3), "{fx:?}");
        assert!(tells(&fx).iter().any(|(to, t)| *to == 1 && t.ends_with("by dusk tomorrow.")), "{fx:?}");
        // Without terms standing it is an ordinary trade's accept.
        assert_eq!(s.done("accept", &SkillCtx { records: vec![], ..c.clone() }).unwrap(), vec![Effect::Accept { offer: 0 }]);
        // The newcomer stores 10 wood in the resident's household store: its part is done and the
        // resident is told what it owes.
        let store = TargetFacts { class: "structure".into(), kind: "storage".into(), id: 77, owner: 3, home: "10,10".into(), dist: 1.0, ..Default::default() };
        c = SkillCtx { actor: me(9, "40,12"), target: store.clone(), item: "wood".into(), qty: 10, skill: "store".into(), records: vec![rec("agreed", "to", 0, 0)], ..Default::default() };
        let fx = s.hook("store", &c).unwrap();
        assert!(fx.iter().any(|e| matches!(e, Effect::Amend { terms, .. } if terms["to_done"] == 10)), "{fx:?}");
        assert!(tells(&fx).iter().any(|(to, t)| *to == 1 && t.contains("You owe them 3 berries")), "{fx:?}");
        // Wood stored somewhere else counts for nothing.
        assert!(s.hook("store", &SkillCtx { target: TargetFacts { home: "99,99".into(), owner: 4, ..store }, ..c.clone() }).unwrap().is_empty());
        // The resident pays: kept on both sides.
        c = SkillCtx { actor: me(1, "10,10"), target: person(9, "40,12"), item: "berries".into(), qty: 3, skill: "give".into(), records: vec![rec("agreed", "from", 0, 10)], ..Default::default() };
        let fx = s.hook("give", &c).unwrap();
        assert!(fx.iter().any(|e| matches!(e, Effect::Close { status, .. } if status == "kept")), "{fx:?}");
        // Due with the wood stacked and nothing paid: the resident broke it, and both are told.
        c = SkillCtx { actor: me(1, "10,10"), record: Some(rec("agreed", "from", 0, 10)), ..Default::default() };
        let fx = s.hook("expire", &c).unwrap();
        assert!(fx.iter().any(|e| matches!(e, Effect::Close { status, .. } if status == "broken")), "{fx:?}");
        let t = tells(&fx);
        assert!(t.iter().any(|(to, x)| *to == 9 && x.contains("they broke your agreement")) && t.iter().any(|(to, x)| *to == 1 && x.contains("you broke your agreement")), "{t:?}");
        // Not taken: the proposer hears it lapsed; neither delivered: lapsed for both.
        assert!(tells(&s.hook("expire", &SkillCtx { record: Some(rec("offered", "from", 0, 0)), ..c.clone() }).unwrap()).iter().any(|(to, x)| *to == 1 && x.contains("did not take up")));
        assert!(s.hook("expire", &SkillCtx { record: Some(rec("agreed", "from", 1, 2)), ..c.clone() }).unwrap().iter().any(|e| matches!(e, Effect::Close { status, .. } if status == "lapsed")));
        // A demand: made, paid by a give, or unpaid when it falls due. Refusing is not an act.
        c = SkillCtx { actor: me(1, "10,10"), target: person(9, ""), item: "berries".into(), qty: 2, text: "the gate-due".into(), skill: "demand".into(), ..Default::default() };
        let fx = s.done("demand", &c).unwrap();
        assert!(matches!(&fx[0], Effect::Record { kind, parties, .. } if kind == "demand" && parties.contains(&("of".to_string(), 9))), "{fx:?}");
        assert!(tells(&fx).iter().any(|(to, t)| *to == 9 && t.contains("demands 2 berries of you (\"the gate-due\")")), "{fx:?}");
        let demand = |me: &str| RecordFacts { id: 6, kind: "demand".into(), status: "open".into(), open: true, terms: serde_json::json!({"item": "berries", "qty": 2, "done": 0, "words": "the gate-due"}).as_object().unwrap().clone(), parties: vec![("by".into(), 1), ("of".into(), 9)], me: me.into(), by: 1, ..Default::default() };
        assert_eq!(s.check("demand", &SkillCtx { records: vec![demand("by")], ..c.clone() }).unwrap_err(), "you already have a demand of them standing");
        let paid = s.hook("give", &SkillCtx { actor: me(9, ""), target: person(1, "10,10"), item: "berries".into(), qty: 2, skill: "give".into(), records: vec![demand("of")], ..Default::default() }).unwrap();
        assert!(paid.iter().any(|e| matches!(e, Effect::Close { status, .. } if status == "met")) && tells(&paid).iter().any(|(to, t)| *to == 1 && t.contains("paid the 2 berries")), "{paid:?}");
        let unpaid = s.hook("expire", &SkillCtx { actor: me(1, "10,10"), record: Some(demand("by")), ..Default::default() }).unwrap();
        assert!(unpaid.iter().any(|e| matches!(e, Effect::Close { status, .. } if status == "unpaid")));
        // A hook may not move goods: an install refuses one that tries.
        assert!(Scripts::new(&format!("{}\nfn on_give(a) {{ [#{{ op: \"add\", item: \"berries\", qty: 1 }}] }}", include_str!("../../scripts/skills.rhai").replace("fn on_give(a)", "fn old_on_give(a)"))).unwrap().validate().unwrap_err().contains("a hook only makes, amends and closes records"));
        // How a party reads its records.
        let regard = RecordFacts { kind: "regard".into(), parties: vec![("holder".into(), crate::records::COMMUNITY | 2), ("toward".into(), crate::records::COMMUNITY | 3)], me: "holder".into(), terms: serde_json::json!({"label": "rival town", "value": -35, "why": "the broken match"}).as_object().unwrap().clone(), ..Default::default() };
        assert_eq!(s.record_text(&regard).unwrap(), format!("your people hold {{id:{}}} as rival town (the broken match)", crate::records::COMMUNITY | 3));
    }

    /// An answer (accept, decline) takes exactly what it names, a trade offer or a proposal, or
    /// is refused with the reason; without a name, accept takes what it always took (terms
    /// first, then the trade) and decline ends that same one. The maker is told of a decline.
    #[test]
    fn answers_take_what_they_name() {
        use crate::records::RecordFacts;
        let s = scripts();
        let person = |id: u64| TargetFacts { class: "creature".into(), id, kind: "person".into(), alive: true, dist: 1.0, stage: "adult".into(), ..Default::default() };
        let tells = |fx: &[Effect]| fx.iter().filter_map(|e| if let Effect::Tell { to, text, .. } = e { Some((*to, text.clone())) } else { None }).collect::<Vec<_>>();
        let terms = serde_json::json!({"from_gives": "berries", "from_qty": 3, "to_gives": "wood", "to_qty": 10, "from_done": 0, "to_done": 0, "from_home": "", "to_home": "", "words": ""}).as_object().unwrap().clone();
        let proposal = |id: u64, status: &str, open: bool, from: u64, me: &str| RecordFacts { id, kind: "agreement".into(), status: status.into(), open, terms: terms.clone(), parties: vec![("from".into(), from), ("to".into(), if me == "to" { 9 } else { 1 })], me: me.into(), by: from as u32, ..Default::default() };
        let offer = |id: u64, to: u32, open: bool| Some(OfferFacts { id, from: 1, to, give: "fish".into(), give_qty: 2, want: "hide".into(), want_qty: 1, open, left_s: 60.0 });
        // 9 is asked by 1: terms (record 5) and a trade (offer 41).
        let base = SkillCtx { actor: ActorFacts { id: 9, kind: "person".into(), stage: "adult".into(), ..Default::default() }, target: person(1), hour: 7.0, records: vec![proposal(5, "offered", true, 1, "to")], offer: offer(41, 9, true), ..Default::default() };
        for skill in ["accept", "decline"] {
            let c = SkillCtx { skill: skill.into(), ..base.clone() };
            let refused = |offer_id: u64, record_id: u64, records: Vec<RecordFacts>, at_hand: Option<OfferFacts>| s.check(skill, &SkillCtx { offer_id, record_id, records, offer: at_hand, ..c.clone() }).err().unwrap_or_default();
            assert_eq!(s.check(skill, &c), Ok(()), "{skill} with no name");
            assert_eq!(refused(41, 0, c.records.clone(), c.offer.clone()), "", "{skill} offer 41");
            assert_eq!(refused(0, 5, c.records.clone(), None), "", "{skill} record 5");
            // Refusals: gone, changed, not addressed to you, expired, already agreed, both named.
            assert_eq!(refused(41, 0, vec![], None), "that offer is gone");
            assert_eq!(refused(41, 0, vec![], offer(42, 9, true)), "they have changed their offer: now their 2 fish for your 1 hide");
            assert_eq!(refused(41, 0, vec![], offer(41, 7, true)), "that offer is not addressed to you");
            assert_eq!(refused(41, 0, vec![], offer(41, 9, false)), "that offer has expired");
            assert_eq!(refused(0, 6, vec![], None), "that proposal is gone");
            assert_eq!(refused(0, 6, vec![proposal(5, "offered", true, 1, "to")], None), "they have changed their terms: now you give 10 wood, they give 3 berries");
            assert_eq!(refused(0, 5, vec![proposal(5, "offered", true, 1, "from")], None), "that proposal is not addressed to you");
            assert_eq!(refused(0, 5, vec![proposal(5, "offered", true, 4, "to")], None), "that proposal is not addressed to you");
            assert_eq!(refused(0, 5, vec![proposal(5, "agreed", true, 1, "to")], None), "you have already agreed to it");
            assert_eq!(refused(0, 5, vec![proposal(5, "not taken", false, 1, "to")], None), "that proposal has expired");
            assert_eq!(refused(0, 5, vec![proposal(5, "declined", false, 1, "to")], None), "that proposal was declined");
            assert_eq!(refused(41, 5, c.records.clone(), c.offer.clone()), "name one thing to answer: the offer or the proposal");
        }
        // accept: the named offer is taken even with terms standing (before, the terms won).
        let acc = SkillCtx { skill: "accept".into(), ..base.clone() };
        assert_eq!(s.done("accept", &SkillCtx { offer_id: 41, ..acc.clone() }).unwrap(), vec![Effect::Accept { offer: 41 }]);
        assert!(matches!(&s.done("accept", &SkillCtx { record_id: 5, ..acc.clone() }).unwrap()[0], Effect::Amend { id: 5, status: Some(st), .. } if st == "agreed"));
        // Without a name, as before: the terms, then (none standing) the trade.
        assert!(matches!(&s.done("accept", &acc).unwrap()[0], Effect::Amend { id: 5, .. }));
        assert_eq!(s.done("accept", &SkillCtx { records: vec![], ..acc.clone() }).unwrap(), vec![Effect::Accept { offer: 0 }]);
        // decline: a proposal is closed as declined and its maker told; onlookers see it.
        let dec = SkillCtx { skill: "decline".into(), ..base.clone() };
        for c in [SkillCtx { record_id: 5, ..dec.clone() }, dec.clone()] {
            let fx = s.done("decline", &c).unwrap();
            assert!(matches!(&fx[0], Effect::Close { id: 5, status, .. } if status == "declined"), "{fx:?}");
            assert!(tells(&fx).iter().any(|(to, t)| *to == 1 && t == "{actor} declined your terms: you give 3 berries, they give 10 wood."), "{fx:?}");
            assert!(fx.iter().any(|e| matches!(e, Effect::Witness { .. })), "{fx:?}");
        }
        // ... a trade offer is ended, its maker told what was declined.
        for c in [SkillCtx { offer_id: 41, ..dec.clone() }, SkillCtx { records: vec![], ..dec.clone() }] {
            let fx = s.done("decline", &c).unwrap();
            assert_eq!(fx[0], Effect::Decline { offer: 41 }, "{fx:?}");
            assert!(tells(&fx).iter().any(|(to, t)| *to == 1 && t == "{actor} declined your offer of 2 fish for 1 hide."), "{fx:?}");
        }
        // ... and with nothing standing the engine is asked, and refuses.
        assert_eq!(s.done("decline", &SkillCtx { records: vec![], offer: None, ..dec.clone() }).unwrap(), vec![Effect::Decline { offer: 0 }]);
        // The rules read the offer only for the skills that answer.
        assert!(s.skill_reads("accept", "offer", false) && s.skill_reads("decline", "offer", true) && !s.skill_reads("give", "offer", true));
        // A proposal to the reader names its id, for the answer.
        assert!(s.record_text(&proposal(5, "offered", true, 1, "to")).unwrap().ends_with("accept or decline (toward them, record 5)"));
    }

    #[test]
    fn gather_berries_yields_items() {
        let s = scripts();
        let mut c = ctx();
        c.target = TargetFacts { class: "resource".into(), kind: "berry_bush".into(), amount: 3.0, ..Default::default() };
        assert!(s.check("gather", &c).is_ok());
        assert!(s.duration_ms("gather", &c).unwrap() > 0);
        let fx = s.done("gather", &c).unwrap();
        assert!(fx.contains(&Effect::Add { item: "berries".into(), qty: 1 }));
        c.target.amount = 0.0;
        assert!(s.check("gather", &c).is_err());
    }

    #[test]
    fn missing_know_how_says_how_to_learn_it() {
        let s = scripts();
        let mut c = ctx();
        c.item = "cloak".into();
        let why = s.check("craft", &c).unwrap_err();
        assert!(why.contains("don't know how to make a cloak") && why.contains("experimenting with fiber or hide"), "{why}");
        c.item = "storage".into();
        let why = s.check("build", &c).unwrap_err();
        assert!(why.contains("from someone who knows it") && why.contains("experimenting with wood"), "{why}");
    }

    #[test]
    fn teaching_names_real_techniques() {
        let s = scripts();
        let mut c = ctx();
        c.item = "leather".into();
        let why = s.check("teach", &c).unwrap_err();
        assert!(why.contains("made with tanning"), "{why}");
        c.item = "hide_preservation".into();
        let why = s.check("teach", &c).unwrap_err();
        assert!(why.contains("no technique called hide_preservation") && why.contains("tanning") && why.contains("cloak"), "{why}");
        c.item = "cloak".into();
        assert!(s.check("teach", &c).unwrap_err().contains("don't know cloak yourself"));
    }

    /// Every know-how can be taught, not only what experimenting can reveal: fire_bolt and
    /// wound_tending (learned only from someone or from writing) were refused as "no technique".
    #[test]
    fn every_know_how_can_be_taught() {
        let s = scripts();
        let names: Vec<String> = s.tables().names("know_how").to_vec();
        assert!(names.iter().any(|n| n == "fire_bolt") && names.iter().any(|n| n == "wound_tending"), "{names:?}");
        for t in &names {
            let mut c = ctx();
            c.item = t.clone();
            c.actor.knows = names.clone();
            c.target = TargetFacts { class: "creature".into(), kind: "person".into(), id: 9, alive: true, stage: "adult".into(), knows: s.tables().words("know_how", t, "requires"), ..Default::default() };
            assert_eq!(s.check("teach", &c), Ok(()), "teach {t}");
        }
    }

    #[test]
    fn gifts_must_fit_the_receivers_pack() {
        let s = scripts();
        let mut c = ctx();
        c.item = "berries".into();
        c.qty = 5;
        c.actor.inv = vec![("berries".into(), 20)];
        c.target = TargetFacts { class: "creature".into(), kind: "person".into(), id: 9, alive: true, stage: "adult".into(), inv: vec![("wood".into(), 30)], ..Default::default() };
        assert!(s.check("give", &c).is_ok());
        c.target.inv = vec![("wood".into(), 38)];
        assert!(s.check("give", &c).unwrap_err().contains("pack is full"));
        c.target.inv.push(("basket".into(), 1));
        assert!(s.check("give", &c).is_ok());
        c.target = TargetFacts { class: "creature".into(), kind: "person".into(), id: 9, alive: true, stage: "infant".into(), ..Default::default() };
        assert!(s.check("give", &c).unwrap_err().contains("a baby can hold only"));
        c.qty = 3;
        assert!(s.check("give", &c).is_ok());
    }

    fn person(id: u64, hp: f32) -> TargetFacts {
        TargetFacts { class: "creature".into(), kind: "person".into(), name: "Grim".into(), id, alive: true, stage: "adult".into(), hp, max_hp: 100.0, company: 2, ..Default::default() }
    }

    fn damage(fx: &[Effect]) -> f32 {
        fx.iter().find_map(|e| if let Effect::Damage { amount } = e { Some(*amount) } else { None }).unwrap()
    }

    #[test]
    fn a_blow_does_its_damage_and_a_yield_holds_back_only_the_yielder() {
        let s = scripts();
        let mut c = ctx();
        c.skill = "attack".into();
        c.target = person(9, 100.0);
        c.actor.inv = vec![("spear".into(), 1)];
        // One rule for every blow: its full damage, between people as with animals, however
        // badly hurt the target already is.
        assert!(s.check("attack", &c).is_ok());
        let full = damage(&s.done("attack", &c).unwrap());
        let spear = s.law_value("dmg_spear").and_then(|v| v.as_f64()).unwrap() as f32;
        assert!((full - spear).abs() < 1e-3, "a spear blow is the dmg_spear law: {full}");
        c.target.hp = 5.0;
        assert!(s.check("attack", &c).is_ok(), "no beating stops short of the badly hurt");
        assert_eq!(damage(&s.done("attack", &c).unwrap()), full, "a blow that exceeds health is not held back");
        c.skill = "strike".into();
        assert!(s.check("strike", &c).is_ok());
        let spear_strike = s.law_value("dmg_strike_spear").and_then(|v| v.as_f64()).unwrap() as f32;
        assert!((damage(&s.done("strike", &c).unwrap()) - spear_strike).abs() < 1e-3, "the starter strike too");
        c.skill = "attack".into();
        // A word about force on the item changes nothing.
        for word in ["hurt", "kill"] {
            c.item = word.into();
            assert_eq!(damage(&s.done("attack", &c).unwrap()), full, "item {word}");
        }
        c.item = String::new();
        // Someone who has yielded can still be struck (that is news, told by the authority);
        // the one who yielded does not strike back.
        c.target.hp = 80.0;
        c.target.yielded_ago = Some(3000.0);
        assert!(s.check("attack", &c).is_ok());
        assert_eq!(damage(&s.done("attack", &c).unwrap()), full);
        c.actor.yielded_ago = Some(1000.0);
        assert!(s.check("attack", &c).unwrap_err().contains("you have yielded"));
        assert!(s.check("yield", &c).unwrap_err().contains("already yielded"));
        c.actor.yielded_ago = None;
        assert!(s.check("yield", &c).is_ok());
        assert_eq!(s.done("yield", &c).unwrap(), vec![Effect::Yield]);
        let io = s.skill_io("yield").unwrap().1;
        assert!(io.contains("do not strike back") && !io.contains("meant only to hurt"), "{io}");
        // Threatening does no harm: it is how to intimidate without hurting anyone.
        assert!(s.check("threaten", &c).is_ok());
        assert!(!s.done("threaten", &c).unwrap().iter().any(|e| matches!(e, Effect::Damage { .. })));
    }

    #[test]
    fn wolves_fear_people_unless_desperate_or_the_chance_is_easy() {
        let s = scripts();
        let mut c = ctx();
        c.skill = "attack".into();
        c.actor.kind = "wolf".into();
        c.actor.hunger = 60.0;
        c.target = person(9, 100.0);
        let refused = |c: &SkillCtx| s.check("attack", c).is_err_and(|w| w.contains("do not dare"));
        assert!(refused(&c), "a healthy adult among others by day");
        c.night = true;
        assert!(refused(&c), "at night, among others");
        c.target.company = 0;
        assert!(!refused(&c), "alone at night");
        c.target.near_fire = true;
        assert!(refused(&c), "alone at night, but by a fire");
        c.night = false;
        c.target.near_fire = false;
        c.target.activity = "sleep".into();
        assert!(!refused(&c), "asleep away from a fire");
        c.target.activity = String::new();
        c.target.company = 2;
        c.target.stage = "child".into();
        assert!(!refused(&c), "a child");
        c.target.stage = "adult".into();
        c.target.hp = 30.0;
        assert!(!refused(&c), "badly hurt");
        c.target.hp = 100.0;
        c.actor.hunger = 90.0;
        assert!(!refused(&c), "starving, no prey sensed");
        c.actor.sensed = vec![("deer".into(), 1)];
        assert!(refused(&c), "starving, but a deer is near");
        c.actor.hurt_by = 9;
        c.actor.hurt_ago = Some(2000.0);
        assert!(!refused(&c), "fighting back");
        c.actor.hurt_ago = None;
        c.target.kind = "deer".into();
        assert!(s.check("attack", &c).is_ok(), "prey is prey");
    }

    #[test]
    fn seizing_needs_a_yield_or_a_beaten_person() {
        let s = scripts();
        let mut c = ctx();
        c.item = "hide".into();
        c.qty = 2;
        c.target = TargetFacts { class: "creature".into(), kind: "person".into(), id: 9, alive: true, stage: "adult".into(), hp: 90.0, max_hp: 100.0, inv: vec![("hide".into(), 3)], ..Default::default() };
        assert!(s.check("seize", &c).unwrap_err().contains("has not given in"));
        c.target.yielded_ago = Some(5_000.0);
        assert!(s.check("seize", &c).is_ok());
        let fx = s.done("seize", &c).unwrap();
        assert!(fx.contains(&Effect::Seize { item: "hide".into(), qty: 2 }));
        c.target.yielded_ago = None;
        c.target.hp = 20.0;
        assert!(s.check("seize", &c).is_ok());
        c.qty = 5;
        assert!(s.check("seize", &c).unwrap_err().contains("does not have"));
    }

    #[test]
    fn eat_requires_item_and_reduces_hunger() {
        let s = scripts();
        let mut c = ctx();
        c.item = "berries".into();
        assert!(s.check("eat", &c).is_err());
        c.actor.inv = vec![("berries".into(), 2)];
        assert!(s.check("eat", &c).is_ok());
        let fx = s.done("eat", &c).unwrap();
        assert!(fx.iter().any(|e| matches!(e, Effect::Vitals { hunger, .. } if *hunger < 0.0)));
    }

    #[test]
    fn rates_depend_on_activity_and_night() {
        let s = scripts();
        let mut c = ctx();
        let day = s.rates(&c).unwrap();
        assert!(day.hunger_per_min > 0.0);
        c.actor.activity = "sleep".into();
        assert!(s.rates(&c).unwrap().energy_per_min > 0.0);
        c.actor.activity = String::new();
        c.actor.hunger = 80.0; // no regeneration, so the cold alone shows
        c.night = true;
        let night = s.rates(&c).unwrap();
        assert_eq!(night.hp_per_min, 0.0, "an ordinary cold night does not hurt");
        assert!(night.energy_per_min < day.energy_per_min, "it tires");
        c.season = "winter".into();
        assert!(s.rates(&c).unwrap().hp_per_min < 0.0, "winter nights hurt without fire or shelter");
        c.actor.near_fire = true;
        assert!(s.rates(&c).unwrap().hp_per_min >= 0.0);
    }

    #[test]
    fn infant_appearance_agrees_with_cold_damage() {
        let s = scripts();
        for night in [false, true] {
            for fire in [false, true] {
                for shelter in [false, true] {
                    for cloak in [false, true] {
                        for winter in [false, true] {
                            let mut c = ctx();
                            c.actor.stage = "infant".into();
                            c.actor.hunger = 80.0;
                            c.actor.near_fire = fire;
                            c.actor.near_shelter = shelter;
                            c.actor.inv = if cloak { vec![("cloak".into(), 1)] } else { vec![] };
                            c.night = night;
                            c.season = if winter { "winter" } else { "summer" }.into();
                            let state = s.body_state(&c).unwrap();
                            let damage = s.rates(&c).unwrap().hp_per_min;
                            assert_eq!(state.cold, night && !fire && !shelter && !cloak);
                            assert!(state.looks().starts_with(if state.cold { "cold" } else { "warm" }));
                            // Cold hurts only in winter (or in the rain): an ordinary night tires
                            // (a person's rates are paced to real time: `person_pace`, 0.3).
                            assert!((damage - if state.cold && winter { -3.0 * 0.3 } else { 0.0 }).abs() < 1e-5, "{damage}");
                        }
                    }
                }
            }
        }
    }

    /// `rates(a)` as it was before it returned parameters (2026-11-09, 9ea831f): the whole
    /// computation in the script, with the numbers of 2026-11-11 (survival made secondary).
    const RATES_BEFORE: &str = r#"
fn rates(a) {
    let hunger = switch a.actor.kind { "deer" => 6.0, "wolf" => 1.5, _ => 4.0 };
    let energy = -3.0;
    let hp = 0.0;
    let act = a.actor.activity;
    if act == "sleep" {
        energy = if a.actor.near_shelter { 26.0 } else { 16.0 };
        hunger *= 0.5;
    } else if act == "rest" {
        energy = 6.0;
    }
    if a.actor.hunger >= 100.0 {
        hp -= 4.0;
    } else if a.actor.hunger < 70.0 && a.actor.energy > 15.0 {
        hp += 3.0;
    }
    if a.actor.energy <= 0.0 {
        hp -= 2.0;
    }
    if a.actor.stage == "elder" {
        if hp > 0.0 { hp *= 0.5; }
        energy *= 1.3;
    }
    if a.actor.stage == "infant" { hunger *= if a.actor.kind == "person" { 0.6 } else { 0.3 }; }
    if energy < 0.0 { energy /= a.actor.endurance; }
    if hp > 0.0 { hp *= a.actor.vitality; }
    energy += (if wet(a) { if inv(a, "cloak") > 0 { -1.0 } else { -2.5 } } else { 0.0 }) + (if cold(a) { -1.5 } else { 0.0 });
    hp += if cold(a) && freezing(a) { if a.season == "winter" { -3.0 } else { -1.5 } } else { 0.0 };
    #{ hunger: hunger, energy: energy, hp: hp }
}
"#;

    fn with_rates(rates: &str) -> String {
        let src = include_str!("../../scripts/skills.rhai");
        let (a, b) = (src.find("fn rates(a) {").unwrap(), src.find("fn move_speed(a) {").unwrap());
        let start = src[..a].rfind("\n\n").unwrap();
        format!("{}\n{rates}\n{}", &src[..start], &src[b..])
    }

    /// The need rates are the same, to the bit, whether the script computes them whole (as
    /// before) or supplies the numbers the engine finishes per body.
    #[test]
    fn need_rates_match_the_whole_script_computation() {
        let before = Scripts::new(&with_rates(RATES_BEFORE)).unwrap();
        let now = scripts();
        let mut n = 0;
        for kind in ["person", "deer", "wolf"] {
            for stage in ["infant", "child", "adult", "elder"] {
                for activity in ["", "sleep", "rest", "block"] {
                    for hunger in [0.0, 69.9, 70.0, 100.0] {
                        for energy in [0.0, 15.0, 15.1, 80.0] {
                            for bits in 0..64u32 {
                                for (endurance, vitality) in [(1.0, 1.0), (0.83, 1.21)] {
                                    let mut c = ctx();
                                    let a = &mut c.actor;
                                    (a.kind, a.stage, a.activity, a.hunger, a.energy) = (kind.into(), stage.into(), activity.into(), hunger, energy);
                                    a.genes = [("endurance".to_string(), endurance), ("vitality".to_string(), vitality)].into();
                                    a.near_fire = bits & 1 != 0;
                                    a.near_shelter = bits & 2 != 0;
                                    a.inv = if bits & 4 != 0 { vec![("cloak".into(), 1), ("wood".into(), 2)] } else { vec![("wood".into(), 2)] };
                                    c.night = bits & 8 != 0;
                                    c.raining = bits & 16 != 0;
                                    c.season = if bits & 32 != 0 { "winter" } else { "summer" }.into();
                                    let (mut x, y) = (before.rates(&c).unwrap(), now.rates(&c).unwrap());
                                    // Since iter-11 every person rate is the old one times `person_pace`
                                    // (0.3); animals keep theirs.
                                    if kind == "person" {
                                        // Scaled inside the law, not after: equal within rounding.
                                        let k = now.num_of("person_pace", "", 0.0) as f32;
                                        (x.hunger_per_min, x.energy_per_min, x.hp_per_min) = (x.hunger_per_min * k, x.energy_per_min * k, x.hp_per_min * k);
                                        let close = |a: f32, b: f32| (a - b).abs() < 1e-5;
                                        assert!(close(x.hunger_per_min, y.hunger_per_min) && close(x.energy_per_min, y.energy_per_min) && close(x.hp_per_min, y.hp_per_min),
                                            "{kind} {stage} {activity:?} hunger {hunger} energy {energy} bits {bits:06b} genes {endurance}/{vitality}: {x:?} vs {y:?}");
                                    } else {
                                        assert_eq!(
                                            (x.hunger_per_min.to_bits(), x.energy_per_min.to_bits(), x.hp_per_min.to_bits()),
                                            (y.hunger_per_min.to_bits(), y.energy_per_min.to_bits(), y.hp_per_min.to_bits()),
                                            "{kind} {stage} {activity:?} hunger {hunger} energy {energy} bits {bits:06b} genes {endurance}/{vitality}: {x:?} vs {y:?}"
                                        );
                                    }
                                    n += 1;
                                }
                            }
                        }
                    }
                }
            }
        }
        assert_eq!(n, 3 * 4 * 4 * 4 * 4 * 64 * 2);
        // Bodies in the same state share one call of the law: the genes and levels are the
        // engine's part.
        assert!(now.needs.borrow().len() <= 3 * 4 * 4 * 64, "{} states", now.needs.borrow().len());
    }

    /// A number looked up by a name is read once; the table answers as the script does.
    #[test]
    fn numbers_by_name_are_tables_read_once() {
        let s = scripts();
        let src = include_str!("../../scripts/skills.rhai");
        let fresh = Scripts::new(src).unwrap();
        for (f, names) in name_laws(&s) {
            for n in names {
                let direct = fresh.engine.call_fn::<Dynamic>(&mut Scope::new(), &fresh.ast, &f, (n.clone(),)).ok().and_then(|d| number(&d));
                assert_eq!(s.names.borrow().get(&f).and_then(|t| t.get(&n)).copied(), Some(direct), "{f}({n})");
                assert_eq!(s.num_of(&f, &n, -1.0), direct.unwrap_or(-1.0));
            }
        }
        assert_eq!(s.num_of("combat_cooldown", "strike", 0.0), 650.0);
        assert_eq!(s.num_of("lunge", "wolf", 0.0), 1.8);
        // A name the engine was not expected to ask is read the first time, then kept.
        assert_eq!(s.num_of("carry_limit", "giant", 0.0), 6.0);
        assert_eq!(s.names.borrow()["carry_limit"]["giant"], Some(6.0));
        assert_eq!(s.num_of("no_such_law", "x", 7.0), 7.0);
    }

    #[test]
    fn infant_appearance_reports_food_and_injury_separately() {
        let s = scripts();
        let mut c = ctx();
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, fed");
        c.actor.hunger = 51.0;
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, hungry");
        c.actor.hunger = 100.0;
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, starving");
        assert_eq!(s.rates(&c).unwrap().hp_per_min, -4.0 * 0.3);
        c.actor.hunger = 20.0;
        c.actor.hurt_ago = Some(1000.0);
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, fed, hurt");
        c.actor.hp = 30.0;
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, fed, badly wounded");
        c.actor.hp = 10.0;
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, fed, barely alive");
    }
}
