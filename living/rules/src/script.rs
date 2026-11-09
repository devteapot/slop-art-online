//! Rhai skill runtime with a typed boundary.
//!
//! Scripts are functions only. For a skill `x` the runtime calls, when defined:
//! `x_check(a) -> ""|reason`, `x_duration(a) -> ms`, `x_done(a) -> [effect maps]`.
//! `rates(a)` returns need rates for the actor's current state; `move_speed(a)` tiles/second.
//! The context map `a` is built directly from typed facts (no JSON), and effects are
//! validated and applied by the authority.

use rhai::packages::Package;
use rhai::{Array, Dynamic, Engine, Map, Scope, AST};
use std::collections::HashSet;

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
    /// Loose the skill's missile (`<skill>_missile(a)`) toward the action's target point.
    Launch,
    /// The target creature is greeted: it sees the gesture made at it (`hailed`, `hailer`).
    Hail,
    /// The actor perceives more of the target creature for `secs` seconds: `what` names the
    /// field the `perceived_of` law then sees as revealed (e.g. `health`).
    Reveal { what: String, secs: f32 },
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

pub struct Scripts {
    engine: Engine,
    ast: AST,
    fns: HashSet<String>,
    shapes: crate::combat::Shapes,
    shows: crate::social::Shows,
}

pub const MAX_SOURCE: usize = 64 * 1024;

fn engine() -> Engine {
    let mut e = Engine::new_raw();
    rhai::packages::StandardPackage::new().register_into_engine(&mut e);
    e.set_max_operations(20_000);
    e.set_max_call_levels(16);
    e.set_max_expr_depths(32, 24);
    e.set_max_string_size(4_096);
    e.set_max_array_size(256);
    e.set_max_map_size(256);
    for symbol in ["eval", "import", "print", "debug"] {
        e.disable_symbol(symbol);
    }
    e
}

impl Scripts {
    pub fn new(source: &str) -> Result<Self, String> {
        if source.len() > MAX_SOURCE {
            return Err("script source exceeds 64 KiB".into());
        }
        let engine = engine();
        let ast = engine.compile(source).map_err(|e| format!("script compile: {e}"))?.clone_functions_only();
        let fns = ast.iter_functions().map(|f| f.name.to_string()).collect();
        let mut s = Self { engine, ast, fns, shapes: Default::default(), shows: Default::default() };
        // Required entry points.
        for f in ["rates", "move_speed"] {
            if !s.fns.contains(f) {
                return Err(format!("script must define `{f}(a)`"));
            }
        }
        s.shapes = s.read_shapes()?;
        s.shows = s.read_shows()?;
        Ok(s)
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
        self.engine
            .call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (to_map(ctx, self.shapes.knack(&ctx.skill)),))
            .map_err(|e| format!("{f}: {e}"))
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
        let m = self.call(&f, ctx)?.try_cast::<Map>().ok_or_else(|| format!("{f} must return a map"))?;
        let g = |k: &str| m.get(k).and_then(number).map(|v| v as f32).ok_or_else(|| format!("{f} missing {k}"));
        Ok(crate::combat::MissileSpec { speed: g("speed")?.clamp(1.0, 120.0), range: g("range")?.clamp(0.5, 80.0), radius: g("radius")?.clamp(0.05, 3.0) })
    }

    fn effects(&self, f: &str, ctx: &SkillCtx) -> Result<Vec<Effect>, String> {
        if !self.has(f) {
            return Ok(Vec::new());
        }
        let r = self.call(&f, ctx)?;
        let arr: Array = r.try_cast::<Array>().ok_or_else(|| format!("{f} must return an array"))?;
        arr.into_iter().map(effect).collect()
    }

    pub fn rates(&self, ctx: &SkillCtx) -> Result<Rates, String> {
        let m = self.call("rates", ctx)?.try_cast::<Map>().ok_or("rates must return a map")?;
        let g = |k: &str| m.get(k).and_then(number).unwrap_or(0.0) as f32;
        Ok(Rates { hunger_per_min: g("hunger"), energy_per_min: g("energy"), hp_per_min: g("hp") })
    }

    pub fn body_state(&self, ctx: &SkillCtx) -> Result<BodyState, String> {
        let m = self.call("body_state", ctx)?.try_cast::<Map>().ok_or("body_state must return a map")?;
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
        let Ok(r) = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "perceived_of", (m,)) else { return Regard::default_for(p) };
        let Some(r) = r.try_cast::<Map>() else { return Regard::default_for(p) };
        let d = Regard::default_for(p);
        let name = r.get("name").and_then(|v| v.as_bool().ok()).unwrap_or(d.name);
        let health = match r.get("health").and_then(|v| v.clone().into_string().ok()).as_deref() {
            Some("exact") => Precision::Exact,
            Some("band") => Precision::Band,
            Some("none") => Precision::None,
            _ => d.health,
        };
        Regard { name, health }
    }

    /// Numeric function of one string argument, e.g. `max_hp("deer")`.
    pub fn num_of(&self, f: &str, arg: &str, default: f64) -> f64 {
        if !self.has(f) {
            return default;
        }
        self.engine
            .call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, (arg.to_string(),))
            .ok()
            .and_then(|d| number(&d))
            .unwrap_or(default)
    }

    /// What a skill takes and gives, as the rules describe it (`skill_io(name)`), for minds
    /// composing routines. None when the script does not describe it.
    pub fn skill_io(&self, skill: &str) -> Option<(String, String)> {
        if !self.has("skill_io") {
            return None;
        }
        let m = self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, "skill_io", (skill.to_string(),)).ok()?.try_cast::<Map>()?;
        let text = |k: &str| m.get(k).and_then(|v| v.clone().into_string().ok()).unwrap_or_default();
        let (takes, gives) = (text("takes"), text("gives"));
        (!takes.is_empty() || !gives.is_empty()).then_some((takes, gives))
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

fn inv_map(inv: &[(String, u32)]) -> Map {
    let mut m = Map::new();
    for (k, v) in inv {
        m.insert(k.as_str().into(), Dynamic::from_int(*v as i64));
    }
    m
}

fn to_map(c: &SkillCtx, knack: &str) -> Map {
    let f = |v: f32| Dynamic::from_float(v as f64);
    let mut a = Map::new();
    a.insert("id".into(), Dynamic::from_int(c.actor.id as i64));
    a.insert("kind".into(), c.actor.kind.clone().into());
    a.insert("hp".into(), f(c.actor.hp));
    a.insert("hunger".into(), f(c.actor.hunger));
    a.insert("energy".into(), f(c.actor.energy));
    a.insert("near_fire".into(), c.actor.near_fire.into());
    a.insert("near_shelter".into(), c.actor.near_shelter.into());
    a.insert("terrain".into(), c.actor.terrain.clone().into());
    a.insert("activity".into(), c.actor.activity.clone().into());
    a.insert("age".into(), f(c.actor.age));
    a.insert("stage".into(), c.actor.stage.clone().into());
    a.insert("life".into(), f(c.actor.life));
    a.insert("knows".into(), c.actor.knows.iter().map(|k| Dynamic::from(k.clone())).collect::<Array>().into());
    a.insert("inv".into(), inv_map(&c.actor.inv).into());
    a.insert("kin_near".into(), Dynamic::from_int(c.actor.kin_near as i64));
    a.insert("pasture".into(), f(c.actor.pasture));
    let ago = |v: Option<f32>| v.map_or(Dynamic::UNIT, |x| Dynamic::from_float(x as f64));
    a.insert("hurt_by".into(), Dynamic::from_int(c.actor.hurt_by as i64));
    a.insert("hurt_ago".into(), ago(c.actor.hurt_ago));
    a.insert("yielded_ago".into(), ago(c.actor.yielded_ago));
    a.insert("sensed".into(), inv_map(&c.actor.sensed).into());
    a.insert("bold".into(), c.actor.bold.into());
    a.insert("room".into(), Dynamic::from_int(c.actor.room as i64));
    for g in crate::genes::BODY {
        a.insert(g.into(), f(crate::genes::gene(&c.actor.genes, g)));
    }
    // How good the actor is at the skill being performed (knack × practice).
    a.insert("factor".into(), f(crate::genes::skill_factor(&c.actor.genes, &c.actor.practice, &c.skill, knack)));
    let mut t = Map::new();
    t.insert("class".into(), c.target.class.clone().into());
    t.insert("id".into(), Dynamic::from_int(c.target.id as i64));
    t.insert("kind".into(), c.target.kind.clone().into());
    t.insert("name".into(), c.target.name.clone().into());
    t.insert("amount".into(), f(c.target.amount));
    t.insert("hp".into(), f(c.target.hp));
    t.insert("max_hp".into(), f(c.target.max_hp));
    t.insert("stage".into(), c.target.stage.clone().into());
    t.insert("hurt_ago".into(), f(c.target.hurt_ago));
    t.insert("alive".into(), c.target.alive.into());
    t.insert("dist".into(), f(c.target.dist));
    t.insert("inv".into(), inv_map(&c.target.inv).into());
    t.insert("knows".into(), c.target.knows.iter().map(|k| Dynamic::from(k.clone())).collect::<Array>().into());
    t.insert("activity".into(), c.target.activity.clone().into());
    t.insert("yielded_ago".into(), ago(c.target.yielded_ago));
    t.insert("near_fire".into(), c.target.near_fire.into());
    t.insert("company".into(), Dynamic::from_int(c.target.company as i64));
    t.insert("bearing".into(), f(c.target.bearing));
    t.insert("closing".into(), f(c.target.closing));
    let mut r = Map::new();
    r.insert("exists".into(), c.routine.exists.into());
    r.insert("ok".into(), Dynamic::from_int(c.routine.ok as i64));
    r.insert("failed".into(), Dynamic::from_int(c.routine.failed as i64));
    r.insert("changed_s".into(), f(c.routine.changed_s));
    let mut m = Map::new();
    m.insert("actor".into(), a.into());
    m.insert("target".into(), t.into());
    m.insert("routine".into(), r.into());
    m.insert("item".into(), c.item.clone().into());
    m.insert("qty".into(), Dynamic::from_int(c.qty as i64));
    m.insert("night".into(), c.night.into());
    m.insert("hour".into(), f(c.hour));
    m.insert("season".into(), c.season.clone().into());
    m.insert("text".into(), c.text.clone().into());
    m.insert("topic".into(), c.topic.clone().into());
    m.insert("roll".into(), f(c.roll));
    m.insert("raining".into(), c.raining.into());
    m.insert("skill".into(), c.skill.clone().into());
    m
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
        "launch" => Effect::Launch,
        "hail" => Effect::Hail,
        "reveal" => Effect::Reveal { what: s("what"), secs: (n("secs") as f32).clamp(0.0, 600.0) },
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
        for sk in crate::catalog::SKILLS {
            if !matches!(sk.name, "open" | "close" | "found" | "join" | "welcome" | "leave" | "dodge" | "block" | "follow" | "flee" | "offer" | "accept" | "signal") {
                assert!(s.skill_io(sk.name).is_some(), "{} undescribed", sk.name);
            }
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
        let text = crate::catalog::skills_help_io(&|n| s.skill_io(n));
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
        c.actor.knows.push("mending".into());
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
        let real: Vec<&str> = crate::catalog::SKILLS.iter().map(|k| k.name).filter(|n| sh.real_time(n)).collect();
        let mut real = real;
        real.sort();
        assert_eq!(real, sorted(vec!["wander", "flee", "follow", "dodge", "block", "attack", "throw", "shoot", "strike", "bowshot", "firebolt", "wait", "sleep", "rest", "graze"]));
        let mut reflex: Vec<&str> = crate::catalog::SKILLS.iter().map(|k| k.name).filter(|n| sh.reflex(n)).collect();
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
