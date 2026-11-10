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
use std::collections::{HashMap, HashSet};
use std::rc::Rc;

mod check;
pub mod context;
pub mod fields;
pub use check::Report;

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
    /// Where a creature's household lives, or a structure's owner's (`"x,y"`; empty: none).
    pub home: String,
}

#[derive(Clone, Debug, Default)]
pub struct SkillCtx {
    pub actor: ActorFacts,
    pub target: TargetFacts,
    pub item: String,
    pub qty: u32,
    pub night: bool,
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
    /// Accept the target's standing offer.
    Accept,
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
    pub sight_day: f32,
    pub sight_night: f32,
    pub sight_torch: f32,
    pub hearing: f32,
    pub fire_warmth: f32,
    pub shelter_warmth: f32,
    pub gestation_days: f32,
    pub bond_window_s: f32,
    pub crowd: f32,
    pub danger_near: f32,
    pub danger_far: f32,
    pub repeat_failure_s: f32,
    /// Walking speed multiplier on road tiles.
    pub road_speed: f32,
    // ---- steering (see `steer.rs`) ----
    /// Turn rate while moving, rad/s.
    pub turn_rate: f32,
    /// Share of speed kept in the sharpest turns.
    pub turn_slow: f32,
    /// Distance from a destination where walkers start slowing down, tiles.
    pub slow_radius: f32,
    /// Distance from a path corner where steering already aims past it, tiles.
    pub corner_radius: f32,
    /// Walkers keep this far from other bodies when they can, tiles.
    pub separation: f32,
    /// How strongly separation bends the way (relative to the goal direction).
    pub separation_weight: f32,
    /// Longest a walker goes without looking again when alone, seconds.
    pub steer_s: f32,
    /// Steering rate among other bodies, while chasing or following, and in a fight (Hz).
    pub crowd_hz: f32,
    pub chase_hz: f32,
    pub combat_hz: f32,
    /// Running speed multiplier (a player's run, a flight).
    pub run_speed: f32,
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
}

impl Laws {
    /// Steering constants for [`crate::steer::plan`].
    pub fn tuning(&self) -> crate::steer::Tuning {
        crate::steer::Tuning { turn_rate: self.turn_rate, turn_slow: self.turn_slow, road_speed: self.road_speed, ..Default::default() }
    }
}

impl Default for Laws {
    fn default() -> Self {
        Self {
            sight_day: crate::SIGHT,
            sight_night: crate::NIGHT_SIGHT,
            sight_torch: crate::TORCH_SIGHT,
            hearing: crate::HEARING,
            fire_warmth: 3.5,
            shelter_warmth: 2.5,
            gestation_days: 1.0,
            bond_window_s: 120.0,
            crowd: 6.0,
            danger_near: 8.0,
            danger_far: 12.0,
            repeat_failure_s: 120.0,
            road_speed: 1.4,
            turn_rate: 6.0,
            turn_slow: 0.4,
            slow_radius: 1.2,
            corner_radius: 0.9,
            separation: 0.8,
            separation_weight: 0.9,
            steer_s: 2.0,
            crowd_hz: 3.0,
            chase_hz: 4.0,
            combat_hz: 8.0,
            run_speed: 1.5,
            input_hz: 30.0,
            input_burst: 15.0,
            pasture_regen: 0.006,
            alone_within: 6.0,
            face_slack: 0.35,
            flee_clear: 9.0,
            takeover_s: 30.0,
        }
    }
}

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
    },
    /// A script whose `rates(a)` returns the finished rates (`hunger`, `energy`, `hp`).
    Final(Rates),
}

impl NeedLaw {
    /// The body's rates: health from its hunger and energy (starving drains it; fed and rested,
    /// it heals by the state's share of healing), tiring divided by the tiring gene, healing
    /// multiplied by the healing gene, and exposure added last.
    pub fn rates(&self, a: &ActorFacts) -> Rates {
        match self {
            NeedLaw::Final(r) => *r,
            NeedLaw::Params { hunger, energy, starving_at, starving_hp, fed_below, rested_above, healing_hp, spent_at, spent_hp, healing, tiring_gene, healing_gene, wet_energy, cold_hp } => {
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
                energy += wet_energy;
                hp += cold_hp;
                Rates { hunger_per_min: *hunger as f32, energy_per_min: energy as f32, hp_per_min: hp as f32 }
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
    /// Functions of no parameter.
    nullary: HashSet<String>,
    /// What each function reads of its parameters.
    fields: fields::Fields,
    /// The context fields each law is called with, by law.
    plans: RefCell<HashMap<String, Rc<context::Plan>>>,
    /// Numbers looked up by a name (`combat_cooldown("strike")`), read at compile for every name
    /// the engine asks and kept for any other the first time it is asked.
    names: RefCell<HashMap<String, HashMap<String, Option<f64>>>>,
    /// `rates(a)` by the values of the fields it reads: bodies in the same state share it.
    needs: RefCell<HashMap<Vec<u8>, NeedLaw>>,
}

/// Largest script source accepted. `skills.rhai` is about 56 KB; compile time and memory grow
/// about linearly (5 ms and 1.3 MB in the module for 55 KB, docs/SCRIPT_ENGINES.md).
pub const MAX_SOURCE: usize = 256 * 1024;
/// Rhai operations one call may take: about 2× the heaviest function measured on the install
/// samples (`skill_io`, 864; the heaviest law, `teach_check`, 635; docs/SCRIPT_ENGINES.md).
/// At about 600 WASM instructions per operation, a call that runs into it costs about 1.2 M
/// instructions (about 0.1 ms in the module).
pub const MAX_OPERATIONS: u64 = 2_000;
/// Distinct states whose rates are kept before the memo starts over.
const NEEDS_MEMO: usize = 4_096;

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
/// depth 3, expression depth 19 in and out of functions, strings 570 characters, arrays 26
/// entries, maps 30 entries (`laws()` has 29). The string limit bounds what a script builds,
/// not the text it is handed (a reworked routine arrives as up to 32,000 characters).
pub const LIMITS: Limits = Limits { operations: MAX_OPERATIONS, call_levels: 8, expr_depth: (40, 40), string: 2_048, array: 64, map: 64 };

fn engine() -> Engine {
    engine_with(LIMITS)
}

fn engine_with(l: Limits) -> Engine {
    let mut e = Engine::new_raw();
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

/// Constant laws the engine looks up by a name, and the names it asks them for.
fn name_laws(s: &Scripts) -> Vec<(String, Vec<String>)> {
    let skills: Vec<String> = s.shapes.names().map(String::from).chain(s.skills.names().map(String::from)).collect();
    let kinds: Vec<String> = crate::catalog::CREATURES.iter().map(|k| k.to_string()).collect();
    let items: Vec<String> = crate::catalog::ITEMS.iter().map(|i| i.name.to_string()).collect();
    let resources: Vec<String> = crate::catalog::RESOURCES.iter().map(|(k, _)| k.to_string()).collect();
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
    for f in ["lunge", "max_hp", "yield_ms", "carry_limit", "carried_spoil", "carcass_meat", "carcass_hide"] {
        add(f, &kinds);
    }
    add("spoil_rate", &items);
    add("nutrition", &items);
    add("regrow", &resources);
    for f in ["trap_every_s", "trap_holds"] {
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
    pub fn new(source: &str) -> Result<Self, String> {
        if source.len() > MAX_SOURCE {
            return Err(format!("script source exceeds {} KiB", MAX_SOURCE / 1024));
        }
        let engine = engine();
        let ast = engine.compile(source).map_err(|e| format!("script compile: {e}"))?.clone_functions_only();
        let fns = ast.iter_functions().map(|f| f.name.to_string()).collect();
        let unary = ast.iter_functions().filter(|f| f.params.len() == 1).map(|f| f.name.to_string()).collect();
        let nullary = ast.iter_functions().filter(|f| f.params.is_empty()).map(|f| f.name.to_string()).collect();
        let fields = fields::Fields::analyze(&ast);
        let mut s = Self { engine, ast, fns, unary, nullary, shapes: Default::default(), shows: Default::default(), skills: Default::default(), fields, plans: Default::default(), names: Default::default(), needs: Default::default() };
        // Skills in the order the source declares them (the last declaration of a name counts).
        let declared = |name: &str| source.rfind(&format!("fn {name}_spec(")).unwrap_or(usize::MAX);
        // Required entry points.
        for f in ["rates", "move_speed"] {
            if !s.fns.contains(f) {
                return Err(format!("script must define `{f}(a)`"));
            }
        }
        s.shapes = s.read_shapes()?;
        s.shows = s.read_shows()?;
        s.skills = std::sync::Arc::new(s.read_specs(&declared)?);
        for (f, names) in name_laws(&s) {
            for n in names {
                s.num_of(&f, &n, 0.0);
            }
        }
        Ok(s)
    }

    /// Call every law and skill function on sample inputs, the way the engine calls them, and
    /// refuse the script if any fails, returns the wrong shape, reads a field the engine does
    /// not provide or exceeds the engine's limits. Returns the operations each function took.
    pub fn validate(&self) -> Result<Report, String> {
        check::validate(self, LIMITS)
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
            const KNOWN: &[&str] = &["aim", "timed", "rooted", "hostile", "reflex", "real_time", "melee", "closes_in", "menace", "force", "dares", "hold_ms", "arc", "takes", "knack", "needs", "knows"];
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

    /// Every skill the script declares.
    pub fn skills(&self) -> &std::sync::Arc<crate::catalog::Skills> {
        &self.skills
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
        let parts: &[&str] = if performing { &["_check", "_duration", "_done"] } else { &["_check", "_duration"] };
        parts.iter().any(|p| self.reads(&format!("{skill}{p}"), "records")) || (performing && self.reads(&format!("on_{skill}"), "records"))
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
        Ok(NeedLaw::from_dynamic(d)?.rates(&ctx.actor))
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
        let law = NeedLaw::from_dynamic(self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "rates", (m,)).map_err(|e| format!("rates: {e}"))?)?;
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

    pub fn laws(&self) -> Laws {
        let mut l = Laws::default();
        if !self.has("laws") {
            return l;
        }
        let Ok(m) = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "laws", ()).map(|d| d.try_cast::<Map>().unwrap_or_default()) else { return l };
        let g = |k: &str, d: f32| m.get(k).and_then(number).map(|v| v as f32).unwrap_or(d);
        l = Laws {
            sight_day: g("sight_day", l.sight_day),
            sight_night: g("sight_night", l.sight_night),
            sight_torch: g("sight_torch", l.sight_torch),
            hearing: g("hearing", l.hearing),
            fire_warmth: g("fire_warmth", l.fire_warmth),
            shelter_warmth: g("shelter_warmth", l.shelter_warmth),
            gestation_days: g("gestation_days", l.gestation_days),
            bond_window_s: g("bond_window_s", l.bond_window_s),
            crowd: g("crowd", l.crowd),
            danger_near: g("danger_near", l.danger_near),
            danger_far: g("danger_far", l.danger_far),
            repeat_failure_s: g("repeat_failure_s", l.repeat_failure_s),
            road_speed: g("road_speed", l.road_speed),
            turn_rate: g("turn_rate", l.turn_rate).clamp(0.5, 50.0),
            turn_slow: g("turn_slow", l.turn_slow).clamp(0.05, 1.0),
            slow_radius: g("slow_radius", l.slow_radius).clamp(0.0, 8.0),
            corner_radius: g("corner_radius", l.corner_radius).clamp(0.0, 4.0),
            separation: g("separation", l.separation).clamp(0.0, 4.0),
            separation_weight: g("separation_weight", l.separation_weight).clamp(0.0, 5.0),
            steer_s: g("steer_s", l.steer_s).clamp(0.1, 10.0),
            crowd_hz: g("crowd_hz", l.crowd_hz).clamp(0.5, 30.0),
            chase_hz: g("chase_hz", l.chase_hz).clamp(0.5, 30.0),
            combat_hz: g("combat_hz", l.combat_hz).clamp(0.5, 30.0),
            run_speed: g("run_speed", l.run_speed).clamp(1.0, 4.0),
            input_hz: g("input_hz", l.input_hz).clamp(1.0, 120.0),
            input_burst: g("input_burst", l.input_burst).clamp(1.0, 240.0),
            pasture_regen: g("pasture_regen", l.pasture_regen).clamp(0.0, 1.0),
            alone_within: g("alone_within", l.alone_within).clamp(0.0, 40.0),
            face_slack: g("face_slack", l.face_slack).clamp(0.0, 3.0),
            flee_clear: g("flee_clear", l.flee_clear).clamp(1.0, 60.0),
            takeover_s: g("takeover_s", l.takeover_s).clamp(0.0, 3_600.0),
        };
        l
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

fn number(d: &Dynamic) -> Option<f64> {
    if let Ok(i) = d.as_int() {
        return Some(i as f64);
    }
    d.as_float().ok()
}

/// The traits a skill's spec may have.
pub const SPEC_TRAITS: &[&str] = &["target", "item", "args", "reach", "about", "takes", "gives", "listed", "talk", "items"];

/// A skill's spec from what `<skill>_spec()` returned.
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
    })
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
    /// Decode what `rates(a)` returned.
    pub fn from_dynamic(d: Dynamic) -> Result<NeedLaw, String> {
        let m = d.try_cast::<Map>().ok_or("rates must return a map")?;
        if !m.contains_key("starving_at") {
            let g = |k: &str| m.get(k).and_then(number).unwrap_or(0.0) as f32;
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
        "damage" => Effect::Damage { amount: n("amount") as f32 },
        "heal" => Effect::Heal { amount: n("amount") as f32 },
        "gate" => Effect::Gate { open: n("open") > 0.0 },
        "give" => Effect::Give { item: s("item"), qty: qty()? },
        "seize" => Effect::Seize { item: s("item"), qty: qty()? },
        "store" => Effect::Store { item: s("item"), qty: qty()? },
        "take" => Effect::Take { item: s("item"), qty: qty()? },
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
        "accept" => Effect::Accept,
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

    fn scripts() -> Scripts {
        Scripts::new(include_str!("../../scripts/skills.rhai")).expect("skills compile")
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
    }

    fn ctx() -> SkillCtx {
        SkillCtx {
            actor: ActorFacts { id: 1, kind: "person".into(), hp: 100.0, hunger: 50.0, energy: 80.0, terrain: "grass".into(), ..Default::default() },
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

    #[test]
    fn starter_combat_skills_follow_the_rules() {
        let s = scripts();
        let mut c = ctx();
        let foe = TargetFacts { class: "creature".into(), id: 2, kind: "wolf".into(), alive: true, hp: 55.0, max_hp: 55.0, dist: 1.2, ..Default::default() };
        // A strike: a short windup, a blow and its energy.
        c.skill = "strike".into();
        c.target = foe.clone();
        assert!(s.check("strike", &c).is_ok());
        assert_eq!(s.duration_ms("strike", &c).unwrap(), 350);
        let fx = s.done("strike", &c).unwrap();
        assert!(fx.iter().any(|e| matches!(e, Effect::Damage { amount } if *amount > 5.0)), "{fx:?}");
        assert!(fx.iter().any(|e| matches!(e, Effect::Vitals { energy, .. } if *energy < 0.0)), "{fx:?}");
        c.actor.energy = 1.0;
        assert_eq!(s.check("strike", &c).unwrap_err(), "too tired");
        c.actor.energy = 80.0;
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
        assert_eq!(s.shapes().bar(), ["strike", "bowshot", "firebolt", "block", "heal", "dodge"]);
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
        assert_eq!(with(|x| x.timed), sorted(vec!["strike", "bowshot", "firebolt", "block", "heal", "dodge", "attack", "shoot", "throw"]));
        assert_eq!(with(|x| x.missile), sorted(vec!["bowshot", "firebolt"]));
        assert_eq!(with(|x| x.aim == Aim::Point), sorted(vec!["bowshot", "firebolt"]));
        assert_eq!(with(|x| x.rooted), sorted(vec!["strike", "bowshot", "firebolt", "heal", "attack", "shoot"]));
        assert_eq!(with(|x| x.hostile), sorted(vec!["attack", "throw", "shoot", "threaten", "strike", "bowshot", "firebolt"]));
        assert_eq!(with(|x| x.force), sorted(vec!["attack", "throw", "shoot", "yield", "strike", "bowshot", "firebolt"]));
        assert_eq!(with(|x| x.dares), sorted(vec!["attack", "seize", "strike"]));
        assert_eq!(with(|x| x.melee), sorted(vec!["attack", "strike"]));
        assert_eq!(with(|x| x.closes_in), sorted(vec!["attack", "threaten", "strike"]));
        assert_eq!(with(|x| x.menace), vec!["threaten"]);
        assert_eq!(with(|x| x.aim == Aim::Dash), vec!["dodge"]);
        assert_eq!(with(|x| x.aim == Aim::Facing), vec!["block"]);
        assert_eq!(with(|x| x.aim == Aim::SelfOrAlly), vec!["heal"]);
        // Real-time behavior and reflexes, with the walking and resting skills.
        let real: Vec<&str> = s.skills().names().filter(|n| sh.real_time(n)).collect();
        let mut real = real;
        real.sort();
        assert_eq!(real, sorted(vec!["wander", "flee", "follow", "dodge", "block", "attack", "throw", "shoot", "strike", "bowshot", "firebolt", "wait", "sleep", "rest", "graze"]));
        let mut reflex: Vec<&str> = s.skills().names().filter(|n| sh.reflex(n)).collect();
        reflex.sort();
        assert_eq!(reflex, sorted(vec!["flee", "dodge", "block", "attack", "throw", "shoot", "strike", "bowshot", "firebolt", "heal", "yield"]));
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
        assert_eq!(names.len(), 13);
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
        assert_eq!(s.done("accept", &SkillCtx { records: vec![], ..c.clone() }).unwrap(), vec![Effect::Accept]);
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
        assert!(Scripts::new(&format!("{}\nfn on_give(a) {{ [#{{ op: \"add\", item: \"berries\", qty: 1 }}] }}", include_str!("../../scripts/skills.rhai").replace("fn on_give(a)", "fn on_give_old(a)"))).unwrap().validate().unwrap_err().contains("a hook only makes, amends and closes records"));
        // How a party reads its records.
        let regard = RecordFacts { kind: "regard".into(), parties: vec![("holder".into(), crate::records::COMMUNITY | 2), ("toward".into(), crate::records::COMMUNITY | 3)], me: "holder".into(), terms: serde_json::json!({"label": "rival town", "value": -35, "why": "the broken match"}).as_object().unwrap().clone(), ..Default::default() };
        assert_eq!(s.record_text(&regard).unwrap(), format!("your people hold {{id:{}}} as rival town (the broken match)", crate::records::COMMUNITY | 3));
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
        assert!((full - 18.0).abs() < 1e-3, "a spear blow: {full}");
        c.target.hp = 5.0;
        assert!(s.check("attack", &c).is_ok(), "no beating stops short of the badly hurt");
        assert_eq!(damage(&s.done("attack", &c).unwrap()), full, "a blow that exceeds health is not held back");
        c.skill = "strike".into();
        assert!(s.check("strike", &c).is_ok());
        assert!((damage(&s.done("strike", &c).unwrap()) - 15.0).abs() < 1e-3, "the starter strike too");
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
        assert!(s.rates(&c).unwrap().hp_per_min < 0.0, "cold nights hurt without fire or shelter");
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
                            assert_eq!(state.cold, damage < 0.0);
                            assert!(state.looks().starts_with(if damage < 0.0 { "cold" } else { "warm" }));
                            assert_eq!(damage, if state.cold { if winter { -5.0 } else { -2.0 } } else { 0.0 });
                        }
                    }
                }
            }
        }
    }

    /// `rates(a)` as it was before it returned parameters (2026-11-09, 9ea831f): the whole
    /// computation in the script.
    const RATES_BEFORE: &str = r#"
fn rates(a) {
    let hunger = switch a.actor.kind { "deer" => 6.0, "wolf" => 1.5, _ => 5.0 };
    let energy = -3.0;
    let hp = 0.0;
    let act = a.actor.activity;
    if act == "sleep" {
        energy = if a.actor.near_shelter { 26.0 } else { 16.0 };
        hunger *= 0.5;
    } else if act == "rest" {
        energy = 6.0;
    } else if act == "block" {
        energy = -12.0;
    }
    if a.actor.hunger >= 100.0 {
        hp -= 6.0;
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
    if wet(a) {
        energy -= if inv(a, "cloak") > 0 { 1.0 } else { 2.5 };
    }
    if cold(a) {
        hp -= if a.season == "winter" { 5.0 } else { 2.0 };
    }
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
                                    let (x, y) = (before.rates(&c).unwrap(), now.rates(&c).unwrap());
                                    assert_eq!(
                                        (x.hunger_per_min.to_bits(), x.energy_per_min.to_bits(), x.hp_per_min.to_bits()),
                                        (y.hunger_per_min.to_bits(), y.energy_per_min.to_bits(), y.hp_per_min.to_bits()),
                                        "{kind} {stage} {activity:?} hunger {hunger} energy {energy} bits {bits:06b} genes {endurance}/{vitality}: {x:?} vs {y:?}"
                                    );
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
        c.actor.hunger = 56.0;
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, hungry");
        c.actor.hunger = 100.0;
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, starving");
        assert_eq!(s.rates(&c).unwrap().hp_per_min, -6.0);
        c.actor.hunger = 20.0;
        c.actor.hurt_ago = Some(1000.0);
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, fed, hurt");
        c.actor.hp = 30.0;
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, fed, badly wounded");
        c.actor.hp = 10.0;
        assert_eq!(s.body_state(&c).unwrap().looks(), "warm, fed, barely alive");
    }
}
