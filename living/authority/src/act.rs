//! Activities: starting skills, approaching targets, completing with Rhai effects,
//! damage, death and remains. Every outcome is reported back to the behavior node that
//! requested it (`mind_state.last`) and to perceiving witnesses.

use crate::motion::{self, Event, Goal, IDLE};
use crate::perceive::{self, percept, witnessed};
use crate::tables::*;
use crate::common::{self, dist, pos};
use living_rules::catalog;
use living_rules::combat::{Aim, Shape};
use living_rules::map::chunk_of;
use living_rules::script::{ActorFacts, Effect, SkillCtx, TargetFacts};
use spacetimedb::rand::Rng;
use spacetimedb::{ReducerContext, Table};

pub const ORPHAN: u16 = u16::MAX;
/// Node of a deliberate act (decided by a mind or a player, outside the graph; see `acts.rs`).
pub const ACT: u16 = u16::MAX - 1;
/// Node of a player's direct skill input (`combat::use_skill`): held like an act against the
/// graph, but never walks into reach (out of reach is refused) and reports to no node.
pub const PLAYER: u16 = u16::MAX - 2;

/// Whether an activity holds the body against the behavior graph (a deliberate act or a
/// player's own move).
pub fn held(node: u16) -> bool {
    node == ACT || node == PLAYER
}
/// What a combat skill is, as the rules declare it (`<skill>_combat()`); `None` for others.
fn shape_of<'a>(sc: &'a living_rules::script::Scripts, skill: &str) -> Option<&'a Shape> {
    sc.combat(skill)
}

/// How a skill is aimed (`Aim::None` for anything that is not a combat skill).
fn aim_of(sc: &living_rules::script::Scripts, skill: &str) -> Aim {
    shape_of(sc, skill).map_or(Aim::None, |s| s.aim)
}

/// A trait of a combat skill (false for any other skill).
fn has(sc: &living_rules::script::Scripts, skill: &str, t: impl Fn(&Shape) -> bool) -> bool {
    shape_of(sc, skill).is_some_and(t)
}

/// How long a `follow` walks alongside its target.
const FOLLOW_MS: u64 = 12_000;
/// Mark (in `mind_state.marks`, kept across plan installs) holding when a character last yielded.
pub const YIELD_MARK: u16 = 0xD400;
/// Mark spacing the story's record of an animal holding back from attacking a person.
const BALK_MARK: u16 = 0xD401;

/// How long ago a character yielded (ms), if it has.
pub fn yielded_ago(ctx: &ReducerContext, id: u32, now: u64) -> Option<f32> {
    ctx.db.mind_state().id().find(id)?.marks.iter().find(|m| m.node == YIELD_MARK).map(|m| now.saturating_sub(m.at_ms) as f32)
}

/// Whether a character's yield still holds (the rules' `yield_ms`).
pub fn yielding(ctx: &ReducerContext, id: u32, kind: &str, now: u64) -> bool {
    yielded_ago(ctx, id, now).is_some_and(|ago| ago < common::scripts(ctx).num_of("yield_ms", kind, 20_000.0) as f32)
}

fn set_mark(ctx: &ReducerContext, id: u32, node: u16, now: u64) {
    if let Some(mut st) = ctx.db.mind_state().id().find(id) {
        st.marks.retain(|m| m.node != node);
        st.marks.push(Mark { node, at_ms: now });
        while st.marks.len() > 24 {
            st.marks.remove(0);
        }
        ctx.db.mind_state().id().update(st);
    }
}

/// An animal's attack on a person refused by the rules goes into the story (at most once a
/// minute per animal), so how often predators hold back can be counted.
fn balked(ctx: &ReducerContext, id: u32, target: &Resolved, why: &str, now: u64) {
    if target.class != 3 || target.kind != "person" || ctx.db.character().id().find(id).map_or(true, |c| c.kind == "person") {
        return;
    }
    if ctx.db.mind_state().id().find(id).map_or(true, |st| st.marks.iter().any(|m| m.node == BALK_MARK && now.saturating_sub(m.at_ms) < 60_000)) {
        return;
    }
    set_mark(ctx, id, BALK_MARK, now);
    let at = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    common::chronicle(ctx, now, "balk", id, target.id as u32, at, format!("{} held back from attacking {} ({why})", common::display(ctx, id), common::name_of(ctx, target.id as u32)));
}

/// Skills done while the body keeps whatever motion it has (a glide to a stop, a player's
/// walk); every other skill stands still to perform.
fn rooted(skill: &str) -> bool {
    !matches!(skill, "wait" | "eat" | "signal")
}

/// A resolved target at the moment an action starts.
#[derive(Clone, Debug)]
pub struct Resolved {
    pub class: u8,
    pub id: u64,
    pub at: (f32, f32),
    pub kind: String,
    pub name: String,
}

impl Resolved {
    pub fn point(at: (f32, f32)) -> Self {
        Self { class: 4, id: 0, at, kind: "place".into(), name: String::new() }
    }
    pub fn none() -> Self {
        Self { class: 0, id: 0, at: (0.0, 0.0), kind: String::new(), name: String::new() }
    }
    fn to_ref(&self) -> TargetRef {
        TargetRef { class: self.class, id: self.id, x: self.at.0, y: self.at.1 }
    }
}

/// Whether a spot is near a fire and near a shelter (a house is both: a roof and a hearth).
pub fn warmth(ctx: &ReducerContext, at: (f32, f32)) -> (bool, bool) {
    let mut near_fire = false;
    let mut near_shelter = false;
    let laws = common::laws(ctx);
    for (s, d) in common::structures_near(ctx, at, laws.fire_warmth.max(laws.shelter_warmth)) {
        if s.kind == "campfire" && d <= laws.fire_warmth {
            near_fire = true;
        }
        if s.kind == "shelter" && d <= laws.shelter_warmth {
            near_shelter = true;
        }
        // Houses, halls and inns have a roof and a hearth; a workshop has a roof.
        if matches!(s.kind.as_str(), "house" | "hall" | "inn") && d <= laws.shelter_warmth {
            near_shelter = true;
            near_fire = true;
        }
        if s.kind == "workshop" && d <= laws.shelter_warmth {
            near_shelter = true;
        }
    }
    (near_fire, near_shelter)
}

pub fn facts(ctx: &ReducerContext, id: u32, now: u64) -> ActorFacts {
    let w = common::world(ctx);
    let ch = ctx.db.character().id().find(id);
    let kind = ch.as_ref().map(|c| c.kind.clone()).unwrap_or_default();
    let age = ch.as_ref().map(|c| common::age_days(c, &w, now)).unwrap_or(20.0);
    let at = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let (hp, hunger, energy, hurt_by, hurt_ago) = ctx.db.vitals().id().find(id).map(|v| {
        let n = common::needs(&v, now);
        (n.hp, n.hunger, n.energy, v.hurt_by, (v.hurt_ms != 0).then(|| now.saturating_sub(v.hurt_ms) as f32))
    }).unwrap_or((0.0, 0.0, 0.0, 0, None));
    let (near_fire, near_shelter) = warmth(ctx, at);
    ActorFacts {
        id,
        kind,
        age,
        hp,
        hunger,
        energy,
        near_fire,
        near_shelter,
        terrain: common::map(ctx).at(at.0, at.1).name().into(),
        activity: ctx.db.activity().id().find(id).filter(|a| a.phase == 1).map(|a| a.skill).unwrap_or_default(),
        inv: common::inv_list(ctx, id as u64),
        knows: common::knows(ctx, id),
        stage: ch.as_ref().map(|c| common::stage_of(c, &w, now).name().to_string()).unwrap_or_else(|| "adult".into()),
        life: ch.as_ref().map(|c| common::life_of(&c.kind).fraction(age, common::pace(&w))).unwrap_or(0.3),
        genes: (*common::genes_of(ctx, id)).clone(),
        practice: Default::default(),
        kin_near: 0,
        pasture: 0.0,
        hurt_by,
        hurt_ago,
        yielded_ago: None,
        sensed: Vec::new(),
        bold: false,
        room: 0,
        community: 0,
        home: String::new(),
    }
}

pub fn body_state(ctx: &ReducerContext, id: u32, now: u64) -> Result<living_rules::script::BodyState, String> {
    common::scripts(ctx).body_state(&living_rules::script::SkillCtx {
        actor: facts(ctx, id, now),
        night: common::night(&common::world(ctx), now),
        ..Default::default()
    })
}

fn target_facts(ctx: &ReducerContext, t: &TargetRef, from: (f32, f32), now: u64) -> TargetFacts {
    let mut f = TargetFacts { class: "none".into(), ..Default::default() };
    match t.class {
        1 => {
            if let Some(n) = ctx.db.resource_node().id().find(t.id) {
                f.class = "resource".into();
                f.id = n.id;
                f.amount = common::amount_now(ctx, &n, now);
                f.dist = dist(from, (n.x, n.y));
                f.kind = n.kind;
            }
        }
        2 => {
            if let Some(s) = ctx.db.structure().id().find(t.id) {
                if s.kind == "trap" {
                    common::trap_catch(ctx, &s, now);
                }
                f.class = "structure".into();
                f.id = s.id;
                f.dist = dist(from, (s.x, s.y));
                f.inv = common::inv_list(ctx, STRUCTURE_BIT | s.id);
                f.kind = s.kind;
            }
        }
        3 => {
            if let Some(c) = ctx.db.character().id().find(t.id as u32) {
                f.class = "creature".into();
                f.id = c.id as u64;
                f.alive = c.alive;
                f.kind = c.kind.clone();
                f.stage = common::stage_of(&c, &common::world(ctx), now).name().to_string();
                f.name = c.name;
                if let Some(b) = ctx.db.body().id().find(c.id) {
                    f.dist = dist(from, pos(&b, now));
                }
                if let Some(v) = ctx.db.vitals().id().find(c.id) {
                    f.hp = common::needs(&v, now).hp;
                    f.max_hp = v.max_hp;
                    f.hurt_ago = if v.hurt_ms == 0 { 1e9 } else { now.saturating_sub(v.hurt_ms) as f32 };
                }
                f.knows = common::knows(ctx, c.id);
                f.activity = ctx.db.activity().id().find(c.id).filter(|a| a.phase == 1).map(|a| a.skill).unwrap_or_default();
                // What they carry (armor softens blows).
                f.inv = common::inv_list(ctx, c.id as u64);
            }
        }
        4 => {
            f.class = "place".into();
            f.dist = dist(from, (t.x, t.y));
        }
        _ => {}
    }
    f
}

fn skill_ctx(ctx: &ReducerContext, id: u32, a: &Activity, now: u64) -> SkillCtx {
    let w = common::world(ctx);
    let mut actor = facts(ctx, id, now);
    actor.practice = common::practice_of(ctx, id);
    let from = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    actor.kin_near = common::creatures_near(ctx, from, 4.0, now).iter().filter(|c| c.id != id && *c.kind == *actor.kind).count() as u32;
    if a.skill == "graze" {
        actor.pasture = common::pasture_now(ctx, chunk_of(from.0, from.1), now);
    }
    let hour = common::hour(&w, now);
    let roll: f32 = ctx.rng().gen_range(0.0..1.0);
    let routine = if a.skill == "rework" { crate::mind::routine_facts(ctx, id, &a.item, now) } else { Default::default() };
    let mut target = target_facts(ctx, &a.target, from, now);
    // Force: whether either side has yielded, and what a predator weighs before daring a person.
    let sc = common::scripts(ctx);
    // Where the target is from where the actor faces, and whether it comes at the actor.
    if let (Some(b), Some(tp)) = (ctx.db.body().id().find(id), target_pos(ctx, &a.target, now)) {
        target.bearing = living_rules::social::bearing(from, crate::town::motion_of(&b, now).0, tp);
        if a.target.class == 3 && a.target.id as u32 != id {
            if let Some(tb) = ctx.db.body().id().find(a.target.id as u32) {
                target.closing = living_rules::social::closing(from, tp, crate::town::motion_of(&tb, now).1);
            }
        }
    }
    if sc.shows().aside(&a.skill) {
        actor.room = crate::town::room(ctx, from);
    }
    if has(&sc, &a.skill, |s| s.force) {
        actor.yielded_ago = yielded_ago(ctx, id, now);
    }
    if has(&sc, &a.skill, |s| s.dares) && target.class == "creature" {
        target.yielded_ago = yielded_ago(ctx, target.id as u32, now);
        if actor.kind != "person" && target.kind == "person" {
            let sight = common::sight_for(ctx, id, &w, now);
            let mut sensed: Vec<(String, u32)> = Vec::new();
            // Itself among them, as before; others when seen (a clear sight line) or smelled.
            let map = common::map(ctx);
            let seen = common::creatures_near(ctx, from, sight, now).into_iter().filter(|c| c.id == id || map.sight_clear(from, c.pos));
            for c in seen.chain(common::smelled_near(ctx, &actor.kind, from, sight, now)) {
                match sensed.iter_mut().find(|(k, _)| *k == *c.kind) {
                    Some(e) => e.1 += 1,
                    None => sensed.push((c.kind.to_string(), 1)),
                }
            }
            actor.sensed = sensed;
            // A seed's hostile pack has no fear of people (its background says so).
            actor.bold = ctx.db.background().id().find(id).is_some_and(|b| b.text.contains("\"bold\":true"));
            if let Some(tp) = target_pos(ctx, &a.target, now) {
                target.near_fire = warmth(ctx, tp).0;
                let (me, them) = (id, target.id as u32);
                target.company = common::creatures_near(ctx, tp, common::laws(ctx).alone_within, now).iter().filter(|c| &*c.kind == "person" && c.id != me && c.id != them).count() as u32;
            }
        }
    }
    // Where each side belongs and lives, for the rules on dealings (docs/WORLD_RULES.md).
    actor.community = crate::records::community_party(ctx, id);
    actor.home = crate::records::home_of(ctx, id);
    match a.target.class {
        3 => {
            target.community = crate::records::community_party(ctx, a.target.id as u32);
            target.home = crate::records::home_of(ctx, a.target.id as u32);
        }
        2 => {
            target.owner = ctx.db.structure().id().find(a.target.id).map_or(0, |s| s.owner);
            if target.owner != 0 {
                target.home = crate::records::home_of(ctx, target.owner);
            }
        }
        _ => {}
    }
    let records = if sc.skill_reads_records(&a.skill, a.phase == 1) { crate::records::of(ctx, id, now) } else { Vec::new() };
    SkillCtx {
        records,
        want: a.want.clone(),
        want_qty: a.want_qty,
        actor,
        target,
        item: a.item.clone(),
        qty: a.qty,
        night: living_rules::is_night(hour),
        hour,
        season: common::season(ctx, now).into(),
        text: a.text.clone(),
        topic: a.topic.clone(),
        roll,
        skill: a.skill.clone(),
        routine,
        raining: crate::town::raining(ctx),
        record: None,
    }
}

fn label(skill: &str, item: &str, t: &Resolved) -> String {
    // Others see someone reworking their ways only as someone deep in thought.
    if skill == "rework" {
        return "sitting deep in thought".into();
    }
    let mut s = skill.to_string();
    if !item.is_empty() {
        s.push(' ');
        s.push_str(item);
    }
    match t.class {
        1 | 2 => s.push_str(&format!(" → {}", t.kind)),
        // A creature by its kind: the label is what anyone sees of the activity (its doer's
        // feedback, onlookers' scenes), and a name is known only to who knows it
        // (docs/PERCEPTION.md); the outcome names the target as the doer perceives it.
        3 => s.push_str(&format!(" → {}", t.kind)),
        4 if skill == "goto" => s.push_str(&format!(" → ({:.0},{:.0})", t.at.0, t.at.1)),
        _ => {}
    }
    s
}

/// Target position now (creatures move).
fn target_pos(ctx: &ReducerContext, t: &TargetRef, now: u64) -> Option<(f32, f32)> {
    match t.class {
        3 => ctx.db.body().id().find(t.id as u32).map(|b| pos(&b, now)),
        1 => ctx.db.resource_node().id().find(t.id).map(|n| (n.x, n.y)),
        2 => ctx.db.structure().id().find(t.id).map(|s| (s.x, s.y)),
        4 | 5 => Some((t.x, t.y)),
        _ => None,
    }
}

/// How close a skill is done from (its spec's `reach`).
fn reach(ctx: &ReducerContext, skill: &str) -> f32 {
    common::scripts(ctx).skills().get(skill).map_or(0.0, |s| s.reach)
}

/// Walking speed from the rules (species, age, tiredness).
pub fn walk_speed(ctx: &ReducerContext, id: u32, now: u64) -> f32 {
    speed(ctx, id, now)
}

fn speed(ctx: &ReducerContext, id: u32, now: u64) -> f32 {
    let sc = common::scripts(ctx);
    let c = SkillCtx { actor: facts(ctx, id, now), ..Default::default() };
    sc.move_speed(&c).unwrap_or(2.5)
}

/// Start an action for behavior node `node`. `cur` is the current activity, if any.
#[allow(clippy::too_many_arguments)]
/// Whether the rules would let a skill go ahead now (the `can` condition): the check an action
/// passes when it starts, without starting it.
pub fn can(ctx: &ReducerContext, id: u32, skill: &str, target: Resolved, item: &str, qty: u32, now: u64) -> bool {
    let item = match (skill, item) {
        ("take", "food") if target.class == 2 => common::best_food(ctx, STRUCTURE_BIT | target.id),
        (_, "food") => common::best_food(ctx, id as u64),
        (_, i) => Some(i.to_string()),
    };
    let Some(item) = item else { return false };
    let act = Activity {
        id,
        skill: skill.into(),
        phase: 0,
        node: 0,
        revision: 0,
        target: target.to_ref(),
        item,
        qty,
        started_ms: now,
        ends_ms: IDLE,
        label: String::new(),
        text: String::new(),
        topic: String::new(),
        victim: 0,
        want: String::new(),
        want_qty: 0,
    };
    common::scripts(ctx).check(skill, &skill_ctx(ctx, id, &act, now)).is_ok()
}

pub fn begin(ctx: &ReducerContext, id: u32, node: u16, revision: u32, skill: &str, target: Resolved, item: &str, qty: u32, text: &str, topic: &str, want: (&str, u32), now: u64) -> Result<(), String> {
    let sc = common::scripts(ctx);
    let shape = shape_of(&sc, skill);
    let aim = shape.map_or(Aim::None, |s| s.aim);
    let melee = shape.is_some_and(|s| s.melee);
    // A blow has no mode: a "hurt" or "kill" left on a skill that takes no item (a graph
    // stored before normalization dropped the word) means nothing and is not carried.
    let item = if sc.skills().get(skill).is_some_and(|k| !k.needs_item) && living_rules::normalize::force_word(item) { "" } else { item };
    let cur = ctx.db.activity().id().find(id);
    if let Some(a) = &cur {
        // A new graph may continue what the character was already doing (the same amount
        // too: a 4 s wait does not carry on a 30 s one).
        if a.node == ORPHAN && a.skill == skill && a.target.class == target.class && a.target.id == target.id && a.item == item && a.qty == qty {
            let mut a = a.clone();
            a.node = node;
            a.revision = revision;
            ctx.db.activity().id().update(a);
            return Ok(());
        }
    }
    // Combat timing (cooldowns, recovery, one windup at a time) holds for every controller.
    crate::combat::gate(ctx, id, skill, cur.as_ref(), now)?;
    // Work out whether the new action can start at all before abandoning the current one:
    // a higher-priority option that cannot start (e.g. taking food from an empty store) must
    // not cancel the lower-priority work that is actually happening.
    let me = ctx.db.body().id().find(id).ok_or("no body")?;
    let here = pos(&me, now);
    let mut target = target;
    let mut item = item.to_string();
    let aside = sc.shows().aside(skill);
    // Making way: the rules weigh whom it is for; the walk goes to a point beside their path.
    let mut aside_from: Option<Resolved> = None;
    match skill {
        _ if aside => {
            if target.class != 3 || target.id as u32 == id {
                return Err("no one to make way for".into());
            }
            let tb = ctx.db.body().id().find(target.id as u32).ok_or("they are gone")?;
            let v = crate::town::motion_of(&tb, now).1;
            if living_rules::social::closing(here, target.at, v) <= 0.0 {
                return Err("no one is coming your way".into());
            }
            let kind = ctx.db.character().id().find(id).map(|c| c.kind).unwrap_or_default();
            let len = sc.num_of(&format!("{skill}_dist"), &kind, 1.2) as f32;
            let map = common::map(ctx);
            let spot = living_rules::social::aside_point(here, target.at, v, len).into_iter().find(|p| map.free(p.0, p.1) && map.line_clear(here, *p)).ok_or("no room to step aside")?;
            aside_from = Some(target.clone());
            target = Resolved::point(spot);
        }
        _ if aim == Aim::Dash && target.class == 4 => {
            // Aimed (a player's dodge): dash that way, as far as there is room.
            let kind = ctx.db.character().id().find(id).map(|c| c.kind).unwrap_or_default();
            let len = sc.num_of(&format!("{skill}_dist"), &kind, 2.4) as f32;
            let d = living_rules::combat::unit(target.at.0 - here.0, target.at.1 - here.1).ok_or("no way to dodge")?;
            let map = common::map(ctx);
            let pick = [1.0f32, 0.75, 0.5, 0.3].into_iter().map(|k| (here.0 + d.0 * len * k, here.1 + d.1 * len * k)).find(|p| map.free(p.0, p.1) && map.line_clear(here, *p));
            target = Resolved::point(pick.ok_or_else(|| format!("no room to {skill}"))?);
        }
        _ if aim == Aim::Facing => {
            // The guard faces where it is aimed (a player), else what threatens: a windup
            // aimed at me, else whoever last hurt me, else the way the body faces.
            let face = if target.class == 4 {
                living_rules::combat::unit(target.at.0 - here.0, target.at.1 - here.1)
            } else {
                let threat = ctx.db.activity().victim().filter(id).find(|a| a.phase == 1).map(|a| a.id).or_else(|| ctx.db.vitals().id().find(id).filter(|v| v.hurt_by != 0 && now.saturating_sub(v.hurt_ms) < 10_000).map(|v| v.hurt_by));
                threat.and_then(|t| ctx.db.body().id().find(t)).and_then(|b| {
                    let p = pos(&b, now);
                    living_rules::combat::unit(p.0 - here.0, p.1 - here.1)
                })
            };
            let f = face.unwrap_or((me.heading.cos(), me.heading.sin()));
            target = Resolved::point((here.0 + f.0, here.1 + f.1));
        }
        _ if aim == Aim::Dash => {
            // Dash sideways/away from whatever is coming, else backwards.
            let len = sc.num_of(&format!("{skill}_dist"), &ctx.db.character().id().find(id).map(|c| c.kind).unwrap_or_default(), 2.4) as f32;
            let threat = ctx
                .db
                .activity()
                .victim()
                .filter(id)
                .find(|a| a.phase == 1)
                .and_then(|a| ctx.db.body().id().find(a.id))
                .map(|b| pos(&b, now));
            let from = threat.unwrap_or((here.0 - 1.0, here.1));
            let away = (here.1 - from.1).atan2(here.0 - from.0);
            let map = common::map(ctx);
            let side: f32 = if ctx.rng().gen_range(0..2) == 0 { 1.2 } else { -1.2 };
            let mut pick = None;
            for spread in [side, -side, 0.0, side * 2.0] {
                let ang = away + spread;
                let p = (here.0 + ang.cos() * len, here.1 + ang.sin() * len);
                if map.free(p.0, p.1) {
                    pick = Some(p);
                    break;
                }
            }
            target = Resolved::point(pick.ok_or_else(|| format!("no room to {skill}"))?);
        }
        "wander" => {
            let map = common::map(ctx);
            let mut pick = None;
            // A stroll carries on roughly the way it was going, when it was going anywhere.
            let moving = me.vx != 0.0 || me.vy != 0.0;
            for k in 0..12 {
                let ang: f32 = if moving && k < 6 { me.heading + ctx.rng().gen_range(-1.2f32..1.2) } else { ctx.rng().gen_range(0.0..std::f32::consts::TAU) };
                let r: f32 = ctx.rng().gen_range(3.0..9.0);
                let p = (here.0 + ang.cos() * r, here.1 + ang.sin() * r);
                if map.free(p.0, p.1) {
                    pick = Some(p);
                    break;
                }
            }
            target = Resolved::point(pick.ok_or("nowhere to wander")?);
        }
        // The target stays the threat: steering runs from it (a creature as it moves). The
        // ground away from it only decides whether there is anywhere to run.
        "flee" => {
            let from = target.at;
            let clear = common::laws(ctx).flee_clear;
            let map = common::map(ctx);
            let open = [0.0f32, 0.6, -0.6, 1.2, -1.2].into_iter().any(|spread| {
                let base = (here.1 - from.1).atan2(here.0 - from.0) + spread;
                map.free(here.0 + base.cos() * clear, here.1 + base.sin() * clear)
            });
            if !open {
                return Err("cornered".into());
            }
        }
        "eat" | "give" | "store" if item == "food" => {
            item = common::best_food(ctx, id as u64).ok_or("no food in your pack (food: gather berries at a berry_bush or fish at a fishing_spot, take food from a storage, or hunt)")?;
        }
        "take" if item == "food" && target.class == 2 => {
            item = common::best_food(ctx, STRUCTURE_BIT | target.id).ok_or("no food in there")?;
        }
        // Reading without a target means a tablet you carry (one you have not read first).
        "read" if target.class == 0 => {
            let mine: Vec<Artifact> = ctx.db.artifact().holder().filter(id as u64).collect();
            let unread = mine.iter().find(|a| ctx.db.familiar().by_actor_thing().filter((id, FAM_ARTIFACT | a.id)).next().is_none());
            match unread.or(mine.first()) {
                Some(pick) => target = Resolved { class: 5, id: pick.id, at: here, kind: "tablet".into(), name: pick.author_name.clone() },
                // Carrying nothing, "read" means the sign right here (the nearest within 8 tiles).
                None => {
                    let sign = living_rules::map::chunks_around(here.0, here.1, 8.0)
                        .into_iter()
                        .flat_map(|c| ctx.db.structure().chunk().filter(c).collect::<Vec<_>>())
                        .filter(|s| s.kind == "sign" && dist(here, (s.x, s.y)) <= 8.0)
                        .min_by(|a, b| dist(here, (a.x, a.y)).total_cmp(&dist(here, (b.x, b.y))))
                        .ok_or("you carry nothing to read and there is no sign here")?;
                    target = Resolved { class: 2, id: sign.id, at: (sign.x, sign.y), kind: "sign".into(), name: String::new() };
                }
            }
        }
        _ => {}
    }
    // A turn and nothing else: already facing its target, there is nothing to do.
    if sc.shows().get(skill).is_some_and(|s| s.turn) && target.class != 0 && !(target.class == 3 && target.id as u32 == id) {
        if living_rules::social::bearing(here, crate::town::motion_of(&me, now).0, target.at) < common::laws(ctx).face_slack {
            return Err("you already face it".into());
        }
    }
    let r = reach(ctx, skill);
    let moving_skill = matches!(skill, "goto" | "wander" | "flee" | "follow") || aim == Aim::Dash || aside;
    // A skillshot at a point and a guard turn toward their point; they never walk to it.
    let in_place = target.class == 4 && matches!(aim, Aim::Point | Aim::Facing);
    let mut needs_approach = !in_place && target.class != 0 && target.class != 5 && (moving_skill || dist(here, target.at) > r);
    if node == PLAYER && needs_approach && !moving_skill {
        // A player's move does not walk into reach: a blow carries its lunge, no further.
        let lunge = if melee { sc.num_of("lunge", &ctx.db.character().id().find(id).map(|c| c.kind).unwrap_or_default(), 0.6) as f32 } else { 0.0 };
        if dist(here, target.at) > r + lunge {
            return Err("out of reach".into());
        }
        needs_approach = false;
    }
    if node == PLAYER && target.class == 3 && target.id as u32 != id {
        let w = common::world(ctx);
        if !crate::perception::in_sight(&common::map(ctx), here, target.at, dist(here, target.at), common::sight_for(ctx, id, &w, now)) {
            return Err("you cannot see them".into());
        }
    }
    let mut act = Activity {
        id,
        skill: skill.into(),
        phase: 0,
        node,
        revision,
        target: target.to_ref(),
        item: item.clone(),
        qty,
        started_ms: now,
        ends_ms: IDLE,
        label: label(skill, &item, &target),
        // A rework carries a whole graph; other texts are a sign's or tablet's words.
        text: text.chars().take(if skill == "rework" { 32_000 } else { 400 }).collect(),
        topic: topic.to_string(),
        want: want.0.to_string(),
        want_qty: want.1,
        victim: if shape.is_some_and(|s| s.hostile) && target.class == 3 && target.id as u32 != id { target.id as u32 } else { 0 },
    };
    // A threat is made once: menacing the same person again within 30 s is refused (a
    // routine that repeats it every second otherwise floods them with threats).
    if shape.is_some_and(|s| s.menace) && act.victim != 0 {
        if let Some(mut st) = ctx.db.mind_state().id().find(id) {
            let key = 0xF000 | (act.victim % 0x100) as u16; // 0xF000-0xF0FF: threats (failures use 0xE000-0xEFFF)
            if st.marks.iter().any(|m| m.node == key && now.saturating_sub(m.at_ms) < 30_000) {
                return Err("you are already threatening them; to ask or urge someone, speak (say)".into());
            }
            st.marks.retain(|m| m.node != key);
            st.marks.push(Mark { node: key, at_ms: now });
            if st.marks.len() > 24 {
                st.marks.remove(0);
            }
            ctx.db.mind_state().id().update(st);
        }
    }
    // An action that would start right here must pass its rules first, too; so must force
    // against someone farther off (no closing in on someone the rules won't let you strike).
    if !needs_approach || shape.is_some_and(|s| s.closes_in) || aside_from.is_some() {
        let probe = match &aside_from {
            Some(t) => Activity { target: t.to_ref(), ..act.clone() },
            None => act.clone(),
        };
        if let Err(why) = sc.check(&act.skill, &skill_ctx(ctx, id, &probe, now)) {
            if melee {
                balked(ctx, id, &target, &why, now);
            }
            return Err(why);
        }
    }
    if let Some(a) = cur {
        if matches!(a.skill.as_str(), "goto" | "follow") && matches!(skill, "goto" | "follow") && now.saturating_sub(a.started_ms) < 3_000 && a.label != act.label {
            turned_back(ctx, id, &a.label, &act.label, now);
        }
        cancel(ctx, a, now, None);
    }
    if needs_approach {
        let sp = speed(ctx, id, now);
        let creature = target.class == 3;
        let goal = match skill {
            _ if aim == Aim::Dash => Goal::point(target.at, sc.num_of(&format!("{skill}_speed"), &ctx.db.character().id().find(id).map(|c| c.kind).unwrap_or_default(), 9.0) as f32, motion::FLAG_AGILE),
            "flee" => Goal {
                kind: motion::GOAL_FLEE,
                target: if creature { target.id as u32 } else { 0 },
                at: target.at,
                keep: dist(here, target.at) + common::laws(ctx).flee_clear,
                speed: sp * 1.15,
                flags: 0,
            },
            "follow" if creature => Goal::creature(target.id as u32, r, sp, 0),
            "goto" if creature => Goal::creature(target.id as u32, r, sp, motion::FLAG_EARLY),
            "goto" | "wander" | "follow" => Goal::point(target.at, sp, motion::FLAG_EARLY),
            _ if aside => Goal::point(target.at, sp * 0.8, 0),
            // Closing in on a creature: every look checks whether it is within reach.
            _ if creature => Goal::creature(target.id as u32, (r - 0.25).max(0.4), sp, motion::FLAG_EACH),
            _ => {
                // Aimed work (building beside, gathering from, reading a sign) stops at the
                // edge of reach instead of walking onto the spot.
                let aimed = r >= 1.0;
                let at = if aimed {
                    let d = dist(here, target.at).max(0.01);
                    let k = (r * 0.7).min(d) / d;
                    let p = (target.at.0 + (here.0 - target.at.0) * k, target.at.1 + (here.1 - target.at.1) * k);
                    if common::map(ctx).free(p.0, p.1) { p } else { target.at }
                } else {
                    target.at
                };
                Goal::point(at, sp, 0)
            }
        };
        if skill == "follow" {
            act.ends_ms = now + FOLLOW_MS;
        }
        if let Some(first) = motion::start(ctx, id, goal, now)? {
            if aim == Aim::Dash {
                dashed(ctx, &act, now);
            }
            if aside {
                if let Some(t) = &aside_from {
                    act.target = t.to_ref();
                    let at = Some(target.at);
                    if sc.shows().record(skill) {
                        crate::combat::accepted(ctx, &act, now);
                    }
                    crate::town::shown(ctx, &sc, &act, at, now);
                    act.target = target.to_ref();
                }
            }
            ctx.db.activity().insert(act);
            if let Some(ev) = first {
                on_motion(ctx, id, ev, now);
            }
            return Ok(());
        }
        if moving_skill {
            // Already there: done at the next tick.
            act.ends_ms = now;
            ctx.db.activity().insert(act);
            return Ok(());
        }
    }
    if moving_skill {
        return Err("already there".into());
    }
    perform(ctx, act, now)
}

/// Enter the performing phase (checks and duration from scripts).
fn perform(ctx: &ReducerContext, mut act: Activity, now: u64) -> Result<(), String> {
    let sc = common::scripts(ctx);
    act.phase = 1;
    let sctx = skill_ctx(ctx, act.id, &act, now);
    sc.check(&act.skill, &sctx)?;
    let dur = sc.duration_ms(&act.skill, &sctx)?;
    if rooted(&act.skill) {
        motion::stop(ctx, act.id, now);
    }
    act.ends_ms = now + dur.max(100);
    let id = act.id;
    // An act aimed at someone engages them as it starts (a lesson, a trade, a blow): an
    // instinct-only resident may wake into a mind (the `wakes` law).
    if act.target.class == 3 && act.target.id as u32 != id {
        crate::woken::engage(ctx, act.target.id as u32, id, &act.skill, act.node == ACT || act.node == PLAYER, now);
    }
    let shape = shape_of(&sc, &act.skill);
    if shape.is_some_and(|s| s.timed) {
        // The windup starts: the cooldown runs, others see it coming, the use is accepted.
        crate::combat::started(ctx, id, &act.skill, now);
        let here = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
        let at = target_pos(ctx, &act.target, now).unwrap_or(here);
        let aim = living_rules::combat::unit(at.0 - here.0, at.1 - here.1).unwrap_or((0.0, 0.0));
        let until = if shape.is_some_and(|s| s.aim == Aim::Facing) { act.ends_ms } else { act.ends_ms + sc.num_of("combat_recover", &act.skill, 0.0) as u64 };
        crate::combat::set_act(ctx, id, &act.skill, now, act.ends_ms, until, act.victim, aim);
        crate::combat::accepted(ctx, &act, now);
    }
    if act.victim != 0 {
        engage(ctx, id, now);
        engage(ctx, act.victim, now);
        common::wake(ctx, act.victim);
    }
    // What others see: the body turns to its target, the use is kept, the doing is shown.
    if let Some(s) = sc.shows().get(&act.skill) {
        let at = target_pos(ctx, &act.target, now);
        if s.faces && !(act.target.class == 3 && act.target.id as u32 == id) {
            if let Some(p) = at {
                motion::face(ctx, id, p, now);
            }
        }
        if s.record {
            crate::combat::accepted(ctx, &act, now);
        }
        crate::town::shown(ctx, &sc, &act, at, now);
    }
    let menace = shape.is_some_and(|s| s.menace).then_some(act.victim).filter(|v| *v != 0);
    if ctx.db.activity().id().find(id).is_some() {
        ctx.db.activity().id().update(act);
    } else {
        ctx.db.activity().insert(act);
    }
    if let Some(victim) = menace {
        threatened(ctx, id, victim, now);
    }
    refresh_rates(ctx, id);
    Ok(())
}

pub fn refresh_rates(ctx: &ReducerContext, id: u32) {
    if let Some(mut v) = ctx.db.vitals().id().find(id) {
        if v.rate_key != 0 {
            v.rate_key = 0;
            ctx.db.vitals().id().update(v);
        }
    }
}

/// Cancel an activity; `why` reports an interruption to the owning node.
pub fn cancel(ctx: &ReducerContext, a: Activity, now: u64, why: Option<&str>) {
    let id = a.id;
    ctx.db.activity().id().delete(id);
    let sc = common::scripts(ctx);
    crate::town::unshown(ctx, &sc, id, &a.skill);
    let timed = sc.shapes().timed(&a.skill);
    // A combat move's or a recorded gesture's use is kept to its outcome.
    if timed || sc.shows().record(&a.skill) {
        crate::combat::outcome(ctx, id, &a.skill, &format!("broken off{}", why.map(|w| format!(": {w}")).unwrap_or_default()), now);
    }
    if timed {
        crate::combat::act_until(ctx, id, now);
        if a.node == PLAYER {
            crate::combat::resume_move(ctx, id, now);
        }
    }
    if a.phase == 0 {
        // Keep momentum: a movement that replaces this one takes over from the glide.
        motion::brake(ctx, id, now);
    }
    if a.skill == "sleep" || a.skill == "rest" {
        refresh_rates(ctx, id);
    }
    if let Some(why) = why {
        report(ctx, &a, false, why, now);
    }
}

fn report(ctx: &ReducerContext, a: &Activity, ok: bool, why: &str, now: u64) {
    if let Some(mut st) = ctx.db.mind_state().id().find(a.id) {
        if a.node != ORPHAN && !held(a.node) {
            st.last = Some(LeafResult { node: a.node, revision: a.revision, ok, why: why.into() });
        }
        st.fails = if ok { 0 } else { st.fails.saturating_add(1) };
        ctx.db.mind_state().id().update(st);
    }
    let repeat = !ok && !news(ctx, a.id, &a.label, why, now);
    // A player's own move is reported to the player (`skill_use`, `my_combat`), not the graph.
    if a.node == PLAYER {
        common::wake(ctx, a.id);
        return;
    }
    // A deliberate act always reports back how it went, and the next one waiting starts.
    if a.node == ACT {
        crate::acts::outcome(ctx, a, ok, why, now);
        common::wake(ctx, a.id);
        crate::acts::next(ctx, a.id, now);
        return;
    }
    // Routine successes (gathering a berry, arriving somewhere) are not experiences worth
    // recording; failures and meaningful acts are.
    if !repeat && (!ok || matches!(a.skill.as_str(), "build" | "craft" | "cook" | "give" | "store" | "take" | "attack" | "conceive" | "threaten" | "yield")) {
        tell(ctx, a.id, ok, &a.label, why, now);
    }
    common::wake(ctx, a.id);
}

/// Tell a character how its graph's action went, as an experience in its own log. A mind is
/// told; so is a person playing the character when it failed (their command, refused or
/// broken off), in the same words. Instinct-only creatures are not.
fn tell(ctx: &ReducerContext, id: u32, ok: bool, what: &str, why: &str, now: u64) {
    let Some(c) = ctx.db.character().id().find(id) else { return };
    if !c.ai && (ok || !crate::presence::played(ctx, id)) {
        return;
    }
    let at = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let text = if ok { format!("You finished: {what}. {why}") } else { format!("You failed to {what}: {why}") };
    percept(ctx, &c, now, "own", id, 0, at, text.trim().to_string(), if ok { 0.08 } else { 0.35 });
}

/// A failure is news unless an identical one (`what` and `why`) came in the last
/// `repeat_failure_s`; news is marked so its repeats are not.
fn news(ctx: &ReducerContext, id: u32, what: &str, why: &str, now: u64) -> bool {
    let Some(mut st) = ctx.db.mind_state().id().find(id) else { return false };
    let key = failure_mark(what, why);
    if st.marks.iter().any(|m| m.node == key && (now.saturating_sub(m.at_ms) as f32) < common::laws(ctx).repeat_failure_s * 1000.0) {
        return false;
    }
    st.marks.retain(|m| m.node != key);
    st.marks.push(Mark { node: key, at_ms: now });
    if st.marks.len() > 24 {
        st.marks.remove(0);
    }
    ctx.db.mind_state().id().update(st);
    true
}

/// A graph's action refused as it would start (`begin` said why). It is a failure like one
/// after starting: counted against its routine and told to the controller, once per
/// `repeat_failure_s` for the same action and reason, as failures are told (`tell`). A guard's first
/// choice refused on every look while a fallback runs counts once a window, not every look.
/// Returns whether it was news (the evaluator then counts it in `fails`).
pub fn refused(ctx: &ReducerContext, id: u32, node: u16, revision: u32, what: &str, why: &str, now: u64) -> bool {
    if !news(ctx, id, what, why, now) {
        return false;
    }
    routine_outcome(ctx, id, revision, node, false, why, now);
    tell(ctx, id, false, what, why, now);
    true
}

/// A mark slot (above behavior node ids, below the evaluator's reserved marks) per failure kind.
fn failure_mark(label: &str, why: &str) -> u16 {
    let mut h: u32 = 2166136261;
    for b in label.bytes().chain(why.bytes()) {
        h = (h ^ b as u32).wrapping_mul(16777619);
    }
    0xE000 + (h % 0x1000) as u16
}

/// Record how a routine's action went (the routine owning the action's node, if any).
fn routine_outcome(ctx: &ReducerContext, id: u32, revision: u32, node: u16, ok: bool, why: &str, now: u64) {
    let Some(g) = common::compiled(ctx, id, revision) else { return };
    let Some(Some(rid)) = g.routine_of.get(node as usize).copied() else { return };
    let mut s = ctx.db.routine_stat().id().find(rid).unwrap_or(RoutineStat { id: rid, ok: 0, failed: 0, last_fail: String::new(), last_ms: 0 });
    if ok {
        s.ok += 1;
    } else {
        s.failed += 1;
        s.last_fail = why.chars().take(160).collect();
    }
    s.last_ms = now;
    if ctx.db.routine_stat().id().find(rid).is_some() {
        ctx.db.routine_stat().id().update(s);
    } else {
        ctx.db.routine_stat().insert(s);
    }
}

fn finish(ctx: &ReducerContext, a: Activity, ok: bool, why: &str, now: u64) {
    let sc = common::scripts(ctx);
    crate::town::unshown(ctx, &sc, a.id, &a.skill);
    let timed = sc.shapes().timed(&a.skill);
    if timed || sc.shows().record(&a.skill) {
        let what = if ok { why.to_string() } else { format!("failed: {why}") };
        crate::combat::outcome(ctx, a.id, &a.skill, &what, now);
    }
    if timed {
        // A dash or a guard has no release: its recovery starts when it ends.
        if matches!(aim_of(&sc, &a.skill), Aim::Dash | Aim::Facing) {
            let until = crate::combat::recovering(ctx, a.id, &a.skill, now);
            crate::combat::act_until(ctx, a.id, until);
        }
        if a.node == PLAYER {
            crate::combat::resume_move(ctx, a.id, now);
        }
    }
    if ok {
        common::practise(ctx, a.id, &a.skill);
        // Grazing eats the grass where it happens.
        if a.skill == "graze" {
            if let Some(b) = ctx.db.body().id().find(a.id) {
                let p = pos(&b, now);
                common::graze_pasture(ctx, chunk_of(p.0, p.1), now);
            }
        }
    }
    if a.node != ORPHAN && !held(a.node) {
        routine_outcome(ctx, a.id, a.revision, a.node, ok, why, now);
    }
    ctx.db.activity().id().delete(a.id);
    if a.skill == "sleep" || a.skill == "rest" {
        refresh_rates(ctx, a.id);
    }
    common::count(|k| k.completions += 1);
    report(ctx, &a, ok, why, now);
}

/// Advance an activity whose timer is due.
pub fn progress(ctx: &ReducerContext, a: Activity, now: u64) {
    if ctx.db.character().id().find(a.id).map_or(true, |c| !c.alive) {
        ctx.db.activity().id().delete(a.id);
        return;
    }
    if a.phase == 1 {
        return complete(ctx, a, now);
    }
    match a.skill.as_str() {
        "follow" => {
            motion::brake(ctx, a.id, now);
            finish(ctx, a, true, "", now);
        }
        // A movement that found itself already there.
        "goto" | "wander" | "flee" => finish(ctx, a, true, "", now),
        s if aim_of(&common::scripts(ctx), s) == Aim::Dash || common::scripts(ctx).shows().aside(s) => finish(ctx, a, true, "", now),
        // Approaches are driven by steering events.
        _ => {
            let mut a = a;
            a.ends_ms = IDLE;
            ctx.db.activity().id().update(a);
        }
    }
}

/// A timed move goes off: the recovery starts, and those who can see it see the move go off
/// (a missile shows its own launch instead).
fn release(ctx: &ReducerContext, sc: &living_rules::script::Scripts, a: &Activity, now: u64) {
    let shape = shape_of(sc, &a.skill);
    if shape.is_some_and(|s| s.timed && s.aim != Aim::Facing) {
        crate::combat::released(ctx, a.id, &a.skill, now);
        let until = crate::combat::recovering(ctx, a.id, &a.skill, now);
        crate::combat::act_until(ctx, a.id, until);
        let here = ctx.db.body().id().find(a.id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
        let at = target_pos(ctx, &a.target, now).unwrap_or(here);
        let dir = living_rules::combat::unit(at.0 - here.0, at.1 - here.1).unwrap_or((0.0, 0.0));
        if shape.is_some_and(|s| !s.missile) {
            crate::combat::show(ctx, now, crate::combat::Seen { kind: living_rules::combat::seen::RELEASE, actor: a.id, target: a.victim, skill: sc.shapes().code(&a.skill), at: here, dir, ..Default::default() });
        }
    }
}

/// Whether `victim` is getting away from a move begun at `since` by a dash that evades (the
/// rules' combat shape: `aim: "dash"` and `evades`): one under way, or one started since then
/// (its cooldown's start).
fn evaded_since(ctx: &ReducerContext, victim: u32, since: u64) -> bool {
    let sc = common::scripts(ctx);
    let evades = |skill: &str| shape_of(&sc, skill).is_some_and(|s| s.aim == Aim::Dash && s.evades);
    ctx.db.activity().id().find(victim).is_some_and(|v| evades(&v.skill))
        || ctx.db.readiness().id().find(victim).is_some_and(|r| r.ready.iter().any(|t| t.from_ms >= since && evades(&t.skill)))
}

/// A blow dodged: both sides perceive it, it is shown as DODGED to them and to those who see
/// it, and the fight stays engaged. Returns what came of it.
fn dodged(ctx: &ReducerContext, attacker: u32, vc: &Character, skill: &str, from: (f32, f32), at_v: (f32, f32), now: u64) -> String {
    let victim = vc.id;
    percept(ctx, vc, now, "combat", attacker, victim, at_v, format!("You dodged {}'s attack.", common::label_for(ctx, vc, attacker)), 0.6);
    if let Some(ac) = ctx.db.character().id().find(attacker) {
        percept(ctx, &ac, now, "combat", victim, attacker, at_v, format!("{} dodged your attack.", common::label_cap(ctx, &ac, victim)), 0.6);
    }
    common::wake(ctx, victim);
    fight_report(ctx, victim, attacker, now);
    fight_report(ctx, attacker, victim, now);
    let code = common::scripts(ctx).shapes().code(skill);
    crate::combat::show(ctx, now, crate::combat::Seen { kind: living_rules::combat::seen::DODGED, actor: attacker, target: victim, skill: code, at: at_v, dir: living_rules::combat::unit(at_v.0 - from.0, at_v.1 - from.1).unwrap_or((0.0, 0.0)), ..Default::default() });
    "dodged".into()
}

/// Steering reports on the movement of an activity that is still on its way.
pub fn on_motion(ctx: &ReducerContext, id: u32, ev: Event, now: u64) {
    let Some(a) = ctx.db.activity().id().find(id) else { return };
    if a.phase != 0 {
        return;
    }
    if ctx.db.character().id().find(id).map_or(true, |c| !c.alive) {
        ctx.db.activity().id().delete(id);
        return;
    }
    match ev {
        Event::Lost(why) => {
            let why = match a.skill.as_str() {
                "follow" => "lost them".to_string(),
                "goto" | "wander" if why == "the way is blocked" => "could not get there".to_string(),
                _ => why,
            };
            finish(ctx, a, false, &why, now)
        }
        Event::Arrived => match a.skill.as_str() {
            "goto" | "wander" | "flee" => finish(ctx, a, true, "", now),
            s if aim_of(&common::scripts(ctx), s) == Aim::Dash || common::scripts(ctx).shows().aside(s) => finish(ctx, a, true, "made way", now),
            "follow" => {}
            _ => {
                let here = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
                let Some(tp) = target_pos(ctx, &a.target, now) else {
                    motion::stop(ctx, id, now);
                    return finish(ctx, a, false, "it is gone", now);
                };
                let r = reach(ctx, &a.skill);
                let d = dist(here, tp);
                // A creature's reach is checked on every look; a place's once the walk ends.
                let close = if a.target.class == 3 { d <= r + 0.25 } else { d <= r + 1.2 };
                if close {
                    let act = Activity { phase: 1, ..a.clone() };
                    if let Err(why) = perform(ctx, act, now) {
                        motion::stop(ctx, id, now);
                        finish(ctx, a, false, &why, now);
                    }
                } else if a.target.class != 3 {
                    finish(ctx, a, false, "could not get there", now);
                }
            }
        },
    }
}

fn complete(ctx: &ReducerContext, a: Activity, now: u64) {
    let sc = common::scripts(ctx);
    let sctx = skill_ctx(ctx, a.id, &a, now);
    // Targets can change or leave while the action runs. One that got away by a dash that
    // evades (its `<skill>_combat()` shape) dodged the move, and everyone who sees it sees a
    // dodge, as within reach; one that walked out of reach did not.
    if a.target.class == 3 && sctx.target.dist > reach(ctx, &a.skill) + 1.0 {
        if a.victim != 0 && evaded_since(ctx, a.victim, a.started_ms) {
            release(ctx, &sc, &a, now);
            let from = ctx.db.body().id().find(a.id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
            crate::woken::engage(ctx, a.victim, a.id, "hurt", true, now);
            engage(ctx, a.id, now);
            engage(ctx, a.victim, now);
            common::count(|k| k.dodged += 1);
            if let Some(vc) = ctx.db.character().id().find(a.victim) {
                let at_v = ctx.db.body().id().find(a.victim).map(|b| pos(&b, now)).unwrap_or(from);
                let summary = dodged(ctx, a.id, &vc, &a.skill, from, at_v, now);
                return finish(ctx, a, true, &summary, now);
            }
        }
        return finish(ctx, a, false, "they moved away", now);
    }
    if let Err(why) = sc.check(&a.skill, &sctx) {
        return finish(ctx, a, false, &why, now);
    }
    let effects = match sc.done(&a.skill, &sctx) {
        Ok(e) => e,
        Err(e) => {
            log::warn!("skill {} script error: {e}", a.skill);
            return finish(ctx, a, false, "something went wrong", now);
        }
    };
    release(ctx, &sc, &a, now);
    match apply(ctx, &a, &sctx, effects, now) {
        Ok(summary) => {
            // What the rules make of it having been done (`on_<skill>`).
            crate::records::after_skill(ctx, &sctx, now);
            finish(ctx, a, true, &summary, now)
        },
        Err(why) => finish(ctx, a, false, &why, now),
    }
}

fn apply(ctx: &ReducerContext, a: &Activity, sctx: &SkillCtx, effects: Vec<Effect>, now: u64) -> Result<String, String> {
    let me = a.id;
    let at = ctx.db.body().id().find(me).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let my_name = common::name_of(ctx, me);
    // How the actor refers to others in what it is told of its own acts (the chronicle, the
    // developers' record, keeps names).
    let me_c = ctx.db.character().id().find(me);
    let seen_as = |id: u32| me_c.as_ref().map(|c| common::label_for(ctx, c, id)).unwrap_or_else(|| common::name_of(ctx, id));
    let mut notes = Vec::new();
    for e in effects {
        match e {
            Effect::Add { item, qty } => {
                if catalog::item(&item).is_none() {
                    return Err(format!("unknown item {item}"));
                }
                common::inv_add(ctx, me as u64, &item, qty);
                notes.push(format!("+{qty} {item}"));
                if a.skill == "craft" || a.skill == "cook" {
                    let verb = if a.skill == "craft" { "made" } else { "cooked" };
                    witnessed(ctx, now, at, "craft", me, 0, &format!("{{a}} {verb} {} {}", if qty == 1 { "a" } else { "some" }, item.replace('_', " ")), 0.3, &[me]);
                }
            }
            Effect::Remove { item, qty } => common::inv_remove(ctx, me as u64, &item, qty)?,
            Effect::Harvest { qty } => {
                let mut n = ctx.db.resource_node().id().find(a.target.id).ok_or("resource gone")?;
                let have = common::amount_now(ctx, &n, now);
                if have < qty {
                    return Err(format!("the {} is depleted", n.kind));
                }
                n.amount = have - qty;
                n.at_ms = now;
                common::invalidate_resources(ctx, Some(n.chunk));
                ctx.db.resource_node().id().update(n);
            }
            Effect::Vitals { hp, hunger, energy } => {
                if let Some(mut v) = ctx.db.vitals().id().find(me) {
                    common::settle(&mut v, now);
                    v.hp = (v.hp + hp).clamp(0.0, v.max_hp);
                    v.hunger = (v.hunger + hunger).clamp(0.0, 100.0);
                    v.energy = (v.energy + energy).clamp(0.0, 100.0);
                    v.rate_key = 0;
                    ctx.db.vitals().id().update(v);
                }
            }
            Effect::Heal { amount } => {
                let patient = a.target.id as u32;
                if let Some(mut v) = ctx.db.vitals().id().find(patient) {
                    common::settle(&mut v, now);
                    v.hp = (v.hp + amount).min(v.max_hp);
                    v.rate_key = 0;
                    ctx.db.vitals().id().update(v);
                }
                if patient != me {
                    if let Some(pc) = ctx.db.character().id().find(patient) {
                        percept(ctx, &pc, now, "care", me, patient, at, format!("{} tended your wounds.", common::label_cap(ctx, &pc, me)), 0.6);
                    }
                    witnessed(ctx, now, at, "care", me, patient, "{a} tended {b}'s wounds", 0.3, &[me, patient]);
                }
                crate::combat::refresh_band(ctx, patient, now);
                // Players see a heal by a combat skill (one the rules give a combat shape).
                let code = common::scripts(ctx).shapes().code(&a.skill);
                if code != 0 {
                    let pp = ctx.db.body().id().find(patient).map(|b| pos(&b, now)).unwrap_or(at);
                    crate::combat::show(ctx, now, crate::combat::Seen { kind: living_rules::combat::seen::HEALED, actor: me, target: patient, skill: code, at: pp, amount, ..Default::default() });
                }
                notes.push(format!("healed {amount:.0}"));
            }
            Effect::Damage { amount } => {
                let victim = a.target.id as u32;
                let melee = has(&common::scripts(ctx), &a.skill, |s| s.melee);
                // A melee blow lands only on someone still within reach when the windup ends:
                // stepping back or running during a telegraphed swing makes it miss.
                if melee {
                    let p = |id: u32| ctx.db.body().id().find(id).map(|b| pos(&b, now));
                    if let (Some(pa), Some(pv)) = (p(me), p(victim)) {
                        let kind = ctx.db.character().id().find(me).map(|c| c.kind).unwrap_or_default();
                        if dist(pa, pv) > reach(ctx, &a.skill) + common::scripts(ctx).num_of("lunge", &kind, 0.6) as f32 {
                            missed(ctx, me, victim, pv, &a.skill, now);
                            notes.push("missed".into());
                            continue;
                        }
                    }
                }
                notes.push(damage(ctx, me, victim, amount, &a.skill, at, now));
            }
            Effect::Give { item, qty } => {
                let to = a.target.id as u32;
                common::inv_remove(ctx, me as u64, &item, qty)?;
                common::inv_add(ctx, to as u64, &item, qty);
                move_tablets(ctx, &item, me as u64, to as u64, qty);
                let to_name = common::name_of(ctx, to);
                common::chronicle(ctx, now, "give", me, to, at, format!("{my_name} gave {qty} {item} to {to_name}"));
                if let Some(c) = ctx.db.character().id().find(to) {
                    percept(ctx, &c, now, "gift", me, to, at, format!("{} gave you {qty} {item}", common::label_cap(ctx, &c, me)), 0.8);
                }
                witnessed(ctx, now, at, "gift", me, to, &format!("{{a}} gave {qty} {item} to {{b}}"), 0.35, &[me, to]);
                notes.push(format!("gave {qty} {item} to {}", seen_as(to)));
            }
            Effect::Seize { item, qty } => {
                let from = a.target.id as u32;
                common::inv_remove(ctx, from as u64, &item, qty)?;
                common::inv_add(ctx, me as u64, &item, qty);
                move_tablets(ctx, &item, from as u64, me as u64, qty);
                let from_name = common::name_of(ctx, from);
                common::chronicle(ctx, now, "seize", me, from, at, format!("{my_name} seized {qty} {item} from {from_name}"));
                if let Some(c) = ctx.db.character().id().find(from) {
                    percept(ctx, &c, now, "seize", me, from, at, format!("{} took {qty} {item} from you by force", common::label_cap(ctx, &c, me)), 0.95);
                }
                witnessed(ctx, now, at, "seize", me, from, &format!("{{a}} took {qty} {item} from {{b}} by force"), 0.8, &[me, from]);
                notes.push(format!("seized {qty} {item} from {}", seen_as(from)));
            }
            Effect::Store { item, qty } => {
                common::inv_remove(ctx, me as u64, &item, qty)?;
                common::inv_add(ctx, STRUCTURE_BIT | a.target.id, &item, qty);
                move_tablets(ctx, &item, me as u64, STRUCTURE_BIT | a.target.id, qty);
                notes.push(format!("stored {qty} {item}"));
            }
            Effect::Take { item, qty } => {
                common::inv_remove(ctx, STRUCTURE_BIT | a.target.id, &item, qty)?;
                common::inv_add(ctx, me as u64, &item, qty);
                move_tablets(ctx, &item, STRUCTURE_BIT | a.target.id, me as u64, qty);
                notes.push(format!("took {qty} {item}"));
                if let Some(s) = ctx.db.structure().id().find(a.target.id) {
                    let same_people = |x: u32, y: u32| match (ctx.db.membership().member().find(x), ctx.db.membership().member().find(y)) {
                        (Some(p), Some(q)) => p.community == q.community,
                        _ => false,
                    };
                    if s.owner != 0 && s.owner != me && !same_people(s.owner, me) && !crate::town::guest_of(ctx, me, s.owner, now) {
                        let owner_sees = ctx.db.body().id().find(s.owner).is_some_and(|b| crate::perception::sees(ctx, s.owner, pos(&b, now), at, &common::world(ctx), &common::map(ctx), now));
                        if owner_sees {
                            crate::woken::engage(ctx, s.owner, me, "theft", true, now);
                        }
                        witnessed(ctx, now, at, "took", me, s.owner, &format!("{{a}} took {qty} {item} from {{b}}'s {}", s.kind), 0.5, &[me]);
                        if let Some(owner) = ctx.db.character().id().find(s.owner) {
                            if owner.alive && ctx.db.body().id().find(owner.id).map_or(false, |b| dist(pos(&b, now), at) <= living_rules::SIGHT) {
                                // The owner sees it happen (already included in witnesses).
                            }
                        }
                    }
                }
            }
            Effect::Bond => {
                notes.push(bond(ctx, me, a.target.id as u32, at, now)?);
            }
            Effect::Signal => {
                notes.push(perceive::signal(ctx, me, &a.item, now)?);
            }
            Effect::Yield => notes.push(give_in(ctx, me, a, at, now)),
            Effect::Hail => notes.push(crate::town::hail(ctx, me, a, at, now)?),
            Effect::Host { until_hour } => notes.push(crate::town::host(ctx, me, a, at, until_hour, now)?),
            Effect::Reveal { what, secs } => {
                if a.target.class != 3 {
                    return Err("no one to look over".into());
                }
                let target = a.target.id as u32;
                crate::perception::reveal(ctx, me, target, &what, secs, now);
                // What the look shows, as the observer now perceives it (the same projection
                // its scene and a player's view carry).
                if let (Some(c), Some(t)) = (ctx.db.character().id().find(me), ctx.db.character().id().find(target)) {
                    let p = crate::perception::project(ctx, &c, &t, now);
                    let seen = if p.hp >= 0.0 { format!("{:.0} of {:.0} health", p.hp, p.max_hp) } else { living_rules::combat::band_words(p.band).to_string() };
                    percept(ctx, &c, now, "appraise", target, 0, at, format!("You look {} over: {seen}.", p.label), 0.3);
                    notes.push(format!("{} has {seen}", p.label));
                }
            }
            Effect::Launch => {
                let sc = common::scripts(ctx);
                let spec = sc.missile(&a.skill, &skill_ctx(ctx, me, a, now))?;
                let to = target_pos(ctx, &a.target, now).unwrap_or(at);
                let dir = living_rules::combat::unit(to.0 - at.0, to.1 - at.1).ok_or("nowhere to aim")?;
                crate::combat::launch(ctx, me, &a.skill, at, dir, spec, now);
                notes.push("loosed".into());
            }
            Effect::Teach { technique } => {
                let learner = a.target.id as u32;
                if living_rules::catalog::technique(&technique).is_none() {
                    return Err(format!("{technique} is not a technique"));
                }
                if !common::learn(ctx, learner, &technique, &format!("taught by {my_name}"), now) {
                    return Err("they already knew it".into());
                }
                let ln = common::name_of(ctx, learner);
                if let Some(c) = ctx.db.character().id().find(learner) {
                    percept(ctx, &c, now, "learned", me, learner, at, format!("{} taught you {technique} ({}).", common::label_cap(ctx, &c, me), technique_help(&technique)), 0.85);
                }
                common::chronicle(ctx, now, "learn", me, learner, at, format!("{my_name} taught {ln} {technique}"));
                witnessed(ctx, now, at, "taught", me, learner, &format!("{{a}} taught {{b}} {technique}"), 0.4, &[me, learner]);
                notes.push(format!("taught {} {technique}", seen_as(learner)));
            }
            Effect::Learn { technique } => {
                if living_rules::catalog::technique(&technique).is_some() && common::learn(ctx, me, &technique, "worked it out", now) {
                    if let Some(c) = ctx.db.character().id().find(me) {
                        percept(ctx, &c, now, "learned", me, 0, at, format!("While tinkering you worked out {technique}: {}.", technique_help(&technique)), 0.9);
                    }
                    common::chronicle(ctx, now, "learn", me, 0, at, format!("{my_name} worked out {technique}"));
                    notes.push(format!("worked out {technique}"));
                } else {
                    notes.push("learned nothing new".into());
                }
            }
            Effect::Rework => {
                let note = crate::mind::rework(ctx, me, &a.item, &a.text, now);
                if let Some(c) = ctx.db.character().id().find(me) {
                    percept(ctx, &c, now, "self", me, 0, at, note.clone(), 0.6);
                }
                notes.push(note);
            }
            Effect::Write => {
                let w = common::world(ctx);
                let _ = w;
                let holder = if a.item == "sign" {
                    common::invalidate_structures(ctx);
                    let s = ctx.db.structure().insert(Structure { id: 0, kind: "sign".into(), x: at.0, y: at.1, chunk: chunk_of(at.0, at.1), owner: me, built_ms: now });
                    STRUCTURE_BIT | s.id
                } else {
                    common::inv_add(ctx, me as u64, "tablet", 1);
                    me as u64
                };
                ctx.db.artifact().insert(Artifact { id: 0, kind: a.item.clone(), holder, author: me, author_name: my_name.clone(), written_ms: now, topic: a.topic.clone(), text: a.text.clone() });
                let what = if a.item == "sign" { "put up a sign" } else { "wrote a tablet" };
                common::chronicle(ctx, now, "write", me, 0, at, format!("{my_name} {what}: “{}”", a.text.chars().take(120).collect::<String>()));
                witnessed(ctx, now, at, "wrote", me, 0, &format!("{{a}} {what}"), 0.35, &[me]);
                notes.push(what.into());
            }
            Effect::Read => {
                let art = match a.target.class {
                    5 => ctx.db.artifact().id().find(a.target.id),
                    2 => ctx.db.artifact().holder().filter(STRUCTURE_BIT | a.target.id).next(),
                    _ => None,
                }
                .ok_or("there is nothing written here")?;
                let (epoch, day) = common::epoch_day(ctx);
                let written = if art.written_ms == 0 { "long ago".to_string() } else { format!("on day {}", living_rules::day_of(art.written_ms, epoch, day)) };
                let mut text = format!("You read {}'s {} (written {written}): “{}”", art.author_name, art.kind, art.text);
                if !art.topic.is_empty() && living_rules::catalog::technique(&art.topic).is_some() {
                    if common::learn(ctx, me, &art.topic, &format!("read {}'s {}", art.author_name, art.kind), now) {
                        text.push_str(&format!(" From it you learn {}: {}.", art.topic, technique_help(&art.topic)));
                        common::chronicle(ctx, now, "learn", me, art.author, at, format!("{my_name} learned {} from {}'s {}", art.topic, art.author_name, art.kind));
                    }
                }
                if ctx.db.familiar().by_actor_thing().filter((me, FAM_ARTIFACT | art.id)).next().is_none() {
                    ctx.db.familiar().insert(Familiar { id: 0, actor: me, thing: FAM_ARTIFACT | art.id, first_ms: now, last_ms: now, times: 1 });
                }
                if let Some(c) = ctx.db.character().id().find(me) {
                    percept(ctx, &c, now, "read", art.author, me, at, text, 0.8);
                }
                notes.push(format!("read {}'s {}", art.author_name, art.kind));
            }
            Effect::Offer => {
                let to = a.target.id as u32;
                if a.want.is_empty() || living_rules::catalog::item(&a.want).is_none() {
                    return Err("say what you want in return".into());
                }
                let give_qty = a.qty.max(1);
                for o in ctx.db.trade_offer().from().filter(me).map(|o| o.id).collect::<Vec<_>>() {
                    ctx.db.trade_offer().id().delete(o);
                }
                ctx.db.trade_offer().insert(TradeOffer { id: 0, from: me, to, give_item: a.item.clone(), give_qty, want_item: a.want.clone(), want_qty: a.want_qty.max(1), at_ms: now });
                if let Some(c) = ctx.db.character().id().find(to) {
                    let text = format!("{} offers you {give_qty} {} for {} {}.", common::label_cap(ctx, &c, me), a.item, a.want_qty.max(1), a.want);
                    percept(ctx, &c, now, "offer", me, to, at, text.clone(), 0.85);
                    if c.ai {
                        perceive::request_deliberation(ctx, to, &format!("{text} You may accept or not."), now);
                    }
                }
                notes.push(format!("offered {give_qty} {} for {} {}", a.item, a.want_qty.max(1), a.want));
            }
            Effect::Accept => {
                let from = a.target.id as u32;
                let offer = ctx
                    .db
                    .trade_offer()
                    .from()
                    .filter(from)
                    .find(|o| o.to == me && now.saturating_sub(o.at_ms) <= 180_000)
                    .ok_or("they have no standing offer for you")?;
                if common::inv_count(ctx, from as u64, &offer.give_item) < offer.give_qty {
                    return Err(format!("they no longer have {} {}", offer.give_qty, offer.give_item));
                }
                if common::inv_count(ctx, me as u64, &offer.want_item) < offer.want_qty {
                    return Err(format!("you don't have {} {}", offer.want_qty, offer.want_item));
                }
                common::inv_remove(ctx, from as u64, &offer.give_item, offer.give_qty)?;
                common::inv_add(ctx, me as u64, &offer.give_item, offer.give_qty);
                common::inv_remove(ctx, me as u64, &offer.want_item, offer.want_qty)?;
                common::inv_add(ctx, from as u64, &offer.want_item, offer.want_qty);
                move_tablets(ctx, &offer.give_item, from as u64, me as u64, offer.give_qty);
                move_tablets(ctx, &offer.want_item, me as u64, from as u64, offer.want_qty);
                ctx.db.trade_offer().id().delete(offer.id);
                let fname = common::name_of(ctx, from);
                let deal = format!("{} {} for {} {}", offer.give_qty, offer.give_item, offer.want_qty, offer.want_item);
                common::chronicle(ctx, now, "trade", from, me, at, format!("{fname} and {my_name} traded {deal}"));
                if let Some(c) = ctx.db.character().id().find(from) {
                    percept(ctx, &c, now, "trade", me, from, at, format!("{} accepted your trade: {deal}.", common::label_cap(ctx, &c, me)), 0.8);
                }
                witnessed(ctx, now, at, "trade", from, me, &format!("{{a}} and {{b}} traded {deal}"), 0.4, &[me, from]);
                notes.push(format!("traded with {}: {deal}", seen_as(from)));
            }
            Effect::Found => {
                if ctx.db.membership().member().find(me).is_some() {
                    return Err("leave your community first".into());
                }
                let name: String = a.text.trim().chars().take(40).collect();
                if ctx.db.community().iter().any(|c| c.name.eq_ignore_ascii_case(&name)) {
                    return Err(format!("{name} already exists"));
                }
                let c = ctx.db.community().insert(Community { id: 0, name: name.clone(), founder: me, founded_ms: now, home_x: at.0, home_y: at.1 });
                ctx.db.membership().insert(Membership { id: 0, community: c.id, member: me, since_ms: now });
                crate::perception::knowledge_changed(None);
                common::chronicle(ctx, now, "community", me, 0, at, format!("{my_name} founded {name}"));
                witnessed(ctx, now, at, "community", me, 0, &format!("{{a}} founded a community called {name}"), 0.6, &[me]);
                notes.push(format!("founded {name}"));
            }
            Effect::Join => {
                let other = a.target.id as u32;
                let m = ctx.db.membership().member().find(other).ok_or("they belong to no community")?;
                if ctx.db.membership().member().find(me).map_or(false, |x| x.community == m.community) {
                    return Err("you already belong to it".into());
                }
                for r in ctx.db.join_request().asker().filter(me).map(|r| r.id).collect::<Vec<_>>() {
                    ctx.db.join_request().id().delete(r);
                }
                ctx.db.join_request().insert(JoinRequest { id: 0, asker: me, community: m.community, at_ms: now });
                let cname = ctx.db.community().id().find(m.community).map(|c| c.name).unwrap_or_default();
                if let Some(c) = ctx.db.character().id().find(other) {
                    percept(ctx, &c, now, "community", me, other, at, format!("{} asks to join {cname}.", common::label_cap(ctx, &c, me)), 0.85);
                    if c.ai {
                        perceive::request_deliberation(ctx, other, &format!("{my_name} asks to join {cname}. You may welcome them or not."), now);
                    }
                }
                notes.push(format!("asked to join {cname}"));
            }
            Effect::Welcome => {
                let asker = a.target.id as u32;
                let mine = ctx.db.membership().member().find(me).ok_or("you belong to no community")?;
                let req = ctx
                    .db
                    .join_request()
                    .asker()
                    .filter(asker)
                    .find(|r| r.community == mine.community && now.saturating_sub(r.at_ms) <= 300_000)
                    .ok_or("they have not asked to join")?;
                ctx.db.join_request().id().delete(req.id);
                if let Some(old) = ctx.db.membership().member().find(asker) {
                    ctx.db.membership().id().delete(old.id);
                }
                ctx.db.membership().insert(Membership { id: 0, community: mine.community, member: asker, since_ms: now });
                crate::perception::knowledge_changed(None);
                let cname = ctx.db.community().id().find(mine.community).map(|c| c.name).unwrap_or_default();
                let an = common::name_of(ctx, asker);
                common::chronicle(ctx, now, "community", asker, me, at, format!("{an} joined {cname}, welcomed by {my_name}"));
                if let Some(c) = ctx.db.character().id().find(asker) {
                    percept(ctx, &c, now, "community", me, asker, at, format!("{} welcomed you into {cname}.", common::label_cap(ctx, &c, me)), 0.9);
                }
                witnessed(ctx, now, at, "community", asker, me, &format!("{{a}} joined {cname}, welcomed by {{b}}"), 0.5, &[me, asker]);
                notes.push(format!("welcomed {} into {cname}", seen_as(asker)));
            }
            Effect::Leave => {
                let m = ctx.db.membership().member().find(me).ok_or("you belong to no community")?;
                let cname = ctx.db.community().id().find(m.community).map(|c| c.name).unwrap_or_default();
                ctx.db.membership().id().delete(m.id);
                crate::perception::knowledge_changed(None);
                common::chronicle(ctx, now, "community", me, 0, at, format!("{my_name} left {cname}"));
                witnessed(ctx, now, at, "community", me, 0, &format!("{{a}} left {cname}"), 0.6, &[me]);
                notes.push(format!("left {cname}"));
            }
            Effect::Plant => {
                let sc = common::scripts(ctx);
                common::invalidate_resources(ctx, None);
                ctx.db.resource_node().insert(ResourceNode {
                    id: 0,
                    kind: "berry_bush".into(),
                    x: at.0,
                    y: at.1,
                    chunk: chunk_of(at.0, at.1),
                    amount: 0.0,
                    max: 5.0,
                    regen: sc.num_of("regrow", "berry_bush", 1.0) as f32,
                    at_ms: now,
                });
                common::chronicle(ctx, now, "plant", me, 0, at, format!("{my_name} planted a berry bush"));
                notes.push("planted a berry bush".into());
            }
            Effect::Build { kind } if kind == "road" => {
                common::set_tile(ctx, at.0.floor() as i32, at.1.floor() as i32, living_rules::map::Terrain::Road)?;
                notes.push("laid road".into());
            }
            Effect::Build { kind } if kind == "clearing" => {
                let (x, y) = (at.0.floor() as i32, at.1.floor() as i32);
                if common::map(ctx).get(x, y) != living_rules::map::Terrain::Forest {
                    return Err("there is no forest here any more".into());
                }
                common::set_tile(ctx, x, y, living_rules::map::Terrain::Grass)?;
                notes.push("cleared the forest here".into());
            }
            Effect::Build { kind } if kind == "bridge" => {
                let (tx, ty) = (a.target.x.floor() as i32, a.target.y.floor() as i32);
                if (at.0.floor() as i32, at.1.floor() as i32) == (tx, ty) {
                    return Err("stand beside the water where the bridge goes".into());
                }
                if common::map(ctx).get(tx, ty) != living_rules::map::Terrain::Water {
                    return Err("a bridge goes on water".into());
                }
                common::set_tile(ctx, tx, ty, living_rules::map::Terrain::Road)?;
                let p = (tx as f32 + 0.5, ty as f32 + 0.5);
                common::chronicle(ctx, now, "build", me, 0, p, format!("{my_name} built a bridge"));
                witnessed(ctx, now, p, "built", me, 0, &format!("{{a}} built a bridge at ({tx},{ty})"), 0.4, &[me]);
                notes.push(format!("built bridge at ({tx},{ty})"));
            }
            Effect::Build { kind } if kind == "wall" || kind == "gate" => {
                let (tx, ty) = (a.target.x.floor() as i32, a.target.y.floor() as i32);
                if (at.0.floor() as i32, at.1.floor() as i32) == (tx, ty) {
                    return Err(format!("stand beside the tile where the {kind} goes"));
                }
                let map = common::map(ctx);
                if !map.walkable(tx, ty) {
                    return Err(format!("cannot build a {kind} there"));
                }
                if kind == "wall" {
                    let occupied = ctx.db.body().chunk().filter(chunk_of(tx as f32, ty as f32)).any(|b| {
                        let p = pos(&b, now);
                        (p.0.floor() as i32, p.1.floor() as i32) == (tx, ty)
                    });
                    if occupied {
                        return Err("someone is standing there".into());
                    }
                    common::set_tile(ctx, tx, ty, living_rules::map::Terrain::Wall)?;
                    motion::resteer_near(ctx, (tx as f32 + 0.5, ty as f32 + 0.5), 6.0, now);
                    notes.push(format!("built wall at ({tx},{ty})"));
                } else {
                    let p = (tx as f32 + 0.5, ty as f32 + 0.5);
                    common::invalidate_structures(ctx);
                    let s = ctx.db.structure().insert(Structure { id: 0, kind: "gate".into(), x: p.0, y: p.1, chunk: chunk_of(p.0, p.1), owner: me, built_ms: now });
                    let community = ctx.db.membership().member().find(me).map(|m| m.community).unwrap_or(0);
                    ctx.db.gate().insert(Gate { id: s.id, x: tx, y: ty, open: true, community, changed_ms: now, changed_by: me });
                    common::chronicle(ctx, now, "build", me, 0, p, format!("{my_name} built a gate"));
                    witnessed(ctx, now, p, "built", me, 0, &format!("{{a}} built a gate at ({tx},{ty})"), 0.4, &[me]);
                    notes.push(format!("built gate #{}", s.id));
                }
            }
            Effect::Gate { open } => {
                let mut g = ctx.db.gate().id().find(a.target.id).ok_or("that is not a gate")?;
                if g.community != 0 && ctx.db.membership().member().find(me).map_or(true, |m| m.community != g.community) {
                    let keepers = ctx.db.community().id().find(g.community).map(|c| c.name).unwrap_or_else(|| "its community".into());
                    return Err(format!("only {keepers} may open or close this gate"));
                }
                if g.open == open {
                    return Err(format!("the gate is already {}", if open { "open" } else { "shut" }));
                }
                g.open = open;
                g.changed_ms = now;
                g.changed_by = me;
                let p = (g.x as f32 + 0.5, g.y as f32 + 0.5);
                ctx.db.gate().id().update(g);
                common::invalidate_gates(ctx);
                if !open {
                    motion::resteer_near(ctx, p, 6.0, now);
                }
                witnessed(ctx, now, p, "gate", me, 0, if open { "{a} opened the gate" } else { "{a} shut the gate" }, 0.3, &[me]);
                notes.push(if open { "opened the gate".into() } else { "shut the gate".into() });
            }
            e @ (Effect::Record { .. } | Effect::Amend { .. } | Effect::Close { .. } | Effect::Tell { .. } | Effect::Witness { .. }) => {
                if let Some(note) = crate::records::apply(ctx, sctx, e, now)? {
                    notes.push(note);
                }
            }
            Effect::Build { kind } => {
                if !catalog::STRUCTURES.contains(&kind.as_str()) {
                    return Err(format!("cannot build {kind}"));
                }
                common::invalidate_structures(ctx);
                let s = ctx.db.structure().insert(Structure { id: 0, kind: kind.clone(), x: at.0, y: at.1, chunk: chunk_of(at.0, at.1), owner: me, built_ms: now });
                common::chronicle(ctx, now, "build", me, 0, at, format!("{my_name} built a {kind}"));
                witnessed(ctx, now, at, "built", me, 0, &format!("{{a}} built a {kind} at ({:.0},{:.0})", at.0, at.1), 0.4, &[me]);
                notes.push(format!("built {kind} #{}", s.id));
            }
        }
    }
    Ok(notes.join(", "))
}

/// Tablets are both an inventory count (for rules) and individual artifacts (for text).
fn move_tablets(ctx: &ReducerContext, item: &str, from: u64, to: u64, qty: u32) {
    if item != "tablet" {
        return;
    }
    for mut t in ctx.db.artifact().holder().filter(from).take(qty as usize).collect::<Vec<_>>() {
        t.holder = to;
        ctx.db.artifact().id().update(t);
    }
}

fn technique_help(t: &str) -> &'static str {
    living_rules::catalog::technique(t).map(|t| t.help).unwrap_or("")
}


/// Offer to start a family, or accept a standing offer from the target.
fn bond(ctx: &ReducerContext, me: u32, other: u32, at: (f32, f32), now: u64) -> Result<String, String> {
    let my_name = common::name_of(ctx, me);
    let other_name = common::name_of(ctx, other);
    let busy = |id: u32| ctx.db.expecting().iter().any(|e| e.a == id || e.b == id);
    if busy(me) || busy(other) {
        return Err("a child is already on the way".into());
    }
    let rearing = |id: u32| ctx.db.rearing().id().find(id).map_or(false, |r| r.until_ms > now);
    if rearing(me) || rearing(other) {
        return Err(if rearing(me) { "you are still raising your young".into() } else { format!("{other_name} is still raising their young") });
    }
    // In a pack only one pair breeds: none while another pair nearby is expecting or raising young.
    let kind = ctx.db.character().id().find(me).map(|c| c.kind).unwrap_or_default();
    let radius = common::life_of(&kind).breeding_radius;
    if radius > 0.0 {
        let breeding = |id: u32| id != me && id != other && (ctx.db.expecting().iter().any(|e| e.a == id || e.b == id) || rearing(id));
        if common::creatures_near(ctx, at, radius, now).iter().any(|c| *c.kind == *kind && breeding(c.id)) {
            return Err("another pair here is raising young".into());
        }
    }
    let window = (common::laws(ctx).bond_window_s * 1000.0) as u64;
    let accepted = ctx.db.bond_offer().from().filter(other).find(|o| o.to == me && now.saturating_sub(o.at_ms) <= window);
    if let Some(o) = accepted {
        ctx.db.bond_offer().id().delete(o.id);
        for mine in ctx.db.bond_offer().from().filter(me).map(|o| o.id).collect::<Vec<_>>() {
            ctx.db.bond_offer().id().delete(mine);
        }
        let w = common::world(ctx);
        let kind = ctx.db.character().id().find(me).map(|c| c.kind).unwrap_or_default();
        let days = common::life_of(&kind).gestation_days(common::pace(&w));
        let gestation = (days * w.day_ms as f32) as u64;
        ctx.db.expecting().insert(Expecting { id: 0, a: other, b: me, due_ms: now + gestation });
        common::chronicle(ctx, now, "family", other, me, at, format!("{other_name} and {my_name} are expecting a child"));
        for (who, partner) in [(me, &other_name), (other, &my_name)] {
            if let Some(c) = ctx.db.character().id().find(who) {
                percept(ctx, &c, now, "family", who, 0, at, format!("You and {partner} are expecting a child. It will be born in about {}.", living_rules::describe_days(days)), 1.0);
            }
        }
        witnessed(ctx, now, at, "family", other, me, "{a} and {b} decided to start a family", 0.5, &[me, other]);
        return Ok(format!("{other_name} and I are expecting a child"));
    }
    for mine in ctx.db.bond_offer().from().filter(me).map(|o| o.id).collect::<Vec<_>>() {
        ctx.db.bond_offer().id().delete(mine);
    }
    ctx.db.bond_offer().insert(BondOffer { id: 0, from: me, to: other, at_ms: now });
    if let Some(c) = ctx.db.character().id().find(other) {
        percept(ctx, &c, now, "family", me, other, at, format!("{} wants to start a family with you (you would both have to choose it within two minutes).", common::label_cap(ctx, &c, me)), 0.9);
        // Being asked is worth a thought (an animal answers by its instincts).
        if c.kind == "person" {
            crate::perceive::request_deliberation(ctx, other, &format!("{my_name} (#{me}) asks to start a family with you; it happens if you choose it toward them within two minutes."), now);
        }
        if c.ai {
            perceive::request_deliberation(ctx, other, &format!("{my_name} asked to start a family with you."), now);
        }
    }
    Ok(format!("asked {other_name} to start a family"))
}

/// Put a creature on combat cadence for the next few seconds.
pub fn engage(ctx: &ReducerContext, id: u32, now: u64) {
    if let Some(mut st) = ctx.db.mind_state().id().find(id) {
        if st.fast_until < now + 6_000 {
            st.fast_until = now + 8_000;
            ctx.db.mind_state().id().update(st);
        }
    }
}

/// Marks counting walks abandoned for another walk (0xD300 + count, at the window start).
const TURN_MARK: u16 = 0xD300;

/// Nothing stops a character from changing its mind every second, but it notices when it
/// keeps turning back and forth, and that is worth a thought.
fn turned_back(ctx: &ReducerContext, id: u32, from: &str, to: &str, now: u64) {
    let Some(mut st) = ctx.db.mind_state().id().find(id) else { return };
    let (count, start) = st.marks.iter().find(|m| (TURN_MARK..TURN_MARK + 16).contains(&m.node)).map(|m| (m.node - TURN_MARK, m.at_ms)).unwrap_or((0, now));
    let (count, start) = if now.saturating_sub(start) > 20_000 { (0, now) } else { (count, start) };
    st.marks.retain(|m| !(TURN_MARK..TURN_MARK + 16).contains(&m.node));
    let count = count + 1;
    if count >= 6 {
        ctx.db.mind_state().id().update(st);
        if let Some(c) = ctx.db.character().id().find(id) {
            let text = format!("You keep turning back and forth ({from}, then {to}, over and over) without getting anywhere.");
            let at = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
            percept(ctx, &c, now, "self", id, 0, at, text.clone(), 0.5);
            perceive::request_deliberation(ctx, id, &text, now);
        }
        return;
    }
    st.marks.push(Mark { node: TURN_MARK + count, at_ms: start });
    while st.marks.len() > 24 {
        st.marks.remove(0);
    }
    ctx.db.mind_state().id().update(st);
}

/// Marks remembering the last fight report and the health quarter it reported.
const REPORT_MARK: u16 = 0xD200;
const BAND_MARK: u16 = 0xD210;

/// While people fight, their minds hear how the exchange is going when something changes:
/// their health drops into a new quarter, three of their blows are blocked, dodged or miss,
/// they take three hits, or their own defense works three times; otherwise after 12 s of
/// fighting. At least 3 s apart, and never while a thought is already pending.
pub fn fight_report(ctx: &ReducerContext, id: u32, other: u32, now: u64) {
    let Some(c) = ctx.db.character().id().find(id) else { return };
    if !c.ai || !c.alive || c.kind != "person" || ctx.db.deliberation().actor().find(id).is_some() {
        return;
    }
    let Some(mut st) = ctx.db.mind_state().id().find(id) else { return };
    let last = st.marks.iter().find(|m| m.node == REPORT_MARK).map(|m| m.at_ms).unwrap_or(0);
    let last = if now.saturating_sub(last) > 30_000 { 0 } else { last };
    if now.saturating_sub(last) < 3_000 || now.saturating_sub(st.deliberated_ms) < 3_000 {
        return;
    }
    let since = if last == 0 { now.saturating_sub(20_000) } else { last };
    let (mut hit, mut blocked, mut dodged, mut evaded, mut they_blocked, mut they_dodged, mut whiffed, mut first) = (0, 0, 0, 0, 0, 0, 0, now);
    for e in ctx.db.experience().observer().filter(id) {
        if e.at_ms <= since || (e.kind != "attacked" && e.kind != "combat") {
            continue;
        }
        first = first.min(e.at_ms);
        let t = e.text.as_str();
        if e.kind == "attacked" {
            hit += 1;
        } else if t.starts_with("You blocked") {
            blocked += 1;
        } else if t.starts_with("You dodged") {
            dodged += 1;
        } else if t.contains("missed: you were out of reach") {
            evaded += 1;
        } else if t.contains("blocked your blow") {
            they_blocked += 1;
        } else if t.contains("dodged your attack") {
            they_dodged += 1;
        } else if t.starts_with("Your blow missed") {
            whiffed += 1;
        }
    }
    let Some(v) = ctx.db.vitals().id().find(id) else { return };
    let hp = common::needs(&v, now).hp;
    let band = ((hp / v.max_hp.max(1.0)) * 4.0).floor().clamp(0.0, 3.0) as u16;
    let last_band = st.marks.iter().find(|m| (BAND_MARK..BAND_MARK + 5).contains(&m.node)).map(|m| m.node - BAND_MARK).unwrap_or(4);
    let their_defense = they_blocked + they_dodged + whiffed;
    let my_defense = blocked + dodged + evaded;
    let mut what = Vec::new();
    if band < last_band {
        what.push(format!("your health has fallen to {hp:.0}"));
    }
    if their_defense >= 3 {
        what.push(format!("{their_defense} of your blows came to nothing (they blocked {they_blocked}, dodged {they_dodged}, {whiffed} found only air)"));
    }
    if hit >= 3 {
        what.push(format!("you have been hit {hit} times"));
    }
    if my_defense >= 3 {
        what.push(format!("your defense is working (blocked {blocked}, dodged {dodged}, stepped out of reach {evaded})"));
    }
    let long = now.saturating_sub(if last == 0 { first } else { last }) >= 12_000 && hit + my_defense + their_defense > 0;
    if what.is_empty() && !long {
        return;
    }
    let label = common::label_for(ctx, &c, other);
    let their_hp = ctx.db.vitals().id().find(other).map(|o| (common::needs(&o, now).hp / o.max_hp * 100.0).round()).unwrap_or(0.0);
    let change = if what.is_empty() {
        format!("since then you were hit {hit}×, defended {my_defense}×, and {their_defense} of your blows came to nothing")
    } else {
        what.join("; ")
    };
    let text = format!(
        "The fight with {label}: {change}. Your health {hp:.0}; theirs looks about {their_hp:.0}%."
    );
    st.marks.retain(|m| m.node != REPORT_MARK && !(BAND_MARK..BAND_MARK + 5).contains(&m.node));
    st.marks.push(Mark { node: REPORT_MARK, at_ms: now });
    st.marks.push(Mark { node: BAND_MARK + band, at_ms: now });
    while st.marks.len() > 24 {
        st.marks.remove(0);
    }
    ctx.db.mind_state().id().update(st);
    perceive::request_deliberation(ctx, id, &text, now);
}

/// A blow that found only air: both sides perceive it, and the fight stays engaged.
fn missed(ctx: &ReducerContext, attacker: u32, victim: u32, at_v: (f32, f32), skill: &str, now: u64) {
    engage(ctx, attacker, now);
    engage(ctx, victim, now);
    common::count(|k| k.missed += 1);
    crate::combat::show(ctx, now, crate::combat::Seen { kind: living_rules::combat::seen::MISS, actor: attacker, target: victim, skill: common::scripts(ctx).shapes().code(skill), at: at_v, ..Default::default() });
    if let Some(vc) = ctx.db.character().id().find(victim) {
        percept(ctx, &vc, now, "combat", attacker, victim, at_v, format!("{}'s blow missed: you were out of reach.", common::label_cap(ctx, &vc, attacker)), 0.6);
        common::wake(ctx, victim);
    }
    if let Some(ac) = ctx.db.character().id().find(attacker) {
        percept(ctx, &ac, now, "combat", victim, attacker, at_v, format!("Your blow missed: {} was out of reach.", common::label_for(ctx, &ac, victim)), 0.6);
    }
    fight_report(ctx, victim, attacker, now);
    fight_report(ctx, attacker, victim, now);
}

/// Drop what only served a living mind: familiarity, undelivered experiences, the places and
/// stances the body read, the inbox cursor. Identity, thoughts, relations and beliefs stay
/// (bounded per character) for the record; the mind's graph in Neo4j keeps its history.
pub fn forget_dead(ctx: &ReducerContext, id: u32) {
    ctx.db.familiar().actor().delete(id);
    ctx.db.experience().observer().delete(id);
    ctx.db.place().actor().delete(id);
    ctx.db.judgment().actor().delete(id);
    ctx.db.judged().actor().delete(id);
    ctx.db.mind_cursor().actor().delete(id);
    ctx.db.act_queue().actor().delete(id);
    crate::woken::forget_dead(ctx, id);
    crate::town::forget_guest(ctx, id);
    for a in ctx.db.acquaintance().observer().filter(id).map(|a| a.id).collect::<Vec<_>>() {
        ctx.db.acquaintance().id().delete(a);
    }
    for r in ctx.db.reveal().observer().filter(id).map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.reveal().id().delete(r);
    }
}

/// What only a living body uses goes with it, so active tables stay proportional to the
/// living: routines and how they went, practice, the installed graph, genes, rearing and the
/// mind's projections (animals' personas and thoughts too; people's stay for the story). A
/// parent of a child still expected keeps what the child inherits until the birth.
pub fn retire(ctx: &ReducerContext, id: u32) {
    if ctx.db.expecting().iter().any(|e| e.a == id || e.b == id) {
        return;
    }
    for r in ctx.db.routine().actor().filter(id).map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.routine_stat().id().delete(r);
        ctx.db.routine().id().delete(r);
    }
    ctx.db.practice().actor().delete(id);
    ctx.db.brain().id().delete(id);
    ctx.db.genome().id().delete(id);
    ctx.db.rearing().id().delete(id);
    ctx.db.relation().actor().delete(id);
    ctx.db.belief().actor().delete(id);
    if ctx.db.character().id().find(id).is_some_and(|c| c.kind != "person") {
        common::invalidate_traits(ctx, id);
        ctx.db.persona().id().delete(id);
        ctx.db.thought().actor().delete(id);
    }
    common::forget_cached(id);
}

/// A blow lands, from `from` (the attacker, or behind a missile), and does its damage: at 0
/// health the victim dies. `skill` is the move that dealt it. Returns what came of it, in
/// words.
pub fn damage(ctx: &ReducerContext, attacker: u32, victim: u32, amount: f32, skill: &str, from: (f32, f32), now: u64) -> String {
    crate::woken::engage(ctx, victim, attacker, "hurt", true, now);
    let Some(mut v) = ctx.db.vitals().id().find(victim) else { return "they are gone".into() };
    let Some(vc) = ctx.db.character().id().find(victim) else { return "they are gone".into() };
    if !vc.alive {
        return "they are already dead".into();
    }
    engage(ctx, attacker, now);
    engage(ctx, victim, now);
    // Defense in progress: a dodge makes the blow miss, a raised guard facing the blow takes
    // most of it (from behind, a guard does not help).
    let guard = ctx.db.activity().id().find(victim);
    let at_v = ctx.db.body().id().find(victim).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    // What the victim is doing defends it if it is a dash or a raised guard (its shape says).
    let sc = common::scripts(ctx);
    let held = guard.as_ref().and_then(|a| shape_of(&sc, &a.skill));
    // A dash defends only if it evades (a dodge, not a jump).
    let mut defense = held.map_or(Aim::None, |s| if s.aim == Aim::Dash && !s.evades { Aim::None } else { s.aim });
    let takes = held.map_or(1.0, |s| s.takes);
    let mut turned = false;
    if defense == Aim::Facing {
        let g = guard.as_ref().map(|a| (a.target.x - at_v.0, a.target.y - at_v.1)).and_then(|(x, y)| living_rules::combat::unit(x, y));
        let came = living_rules::combat::unit(from.0 - at_v.0, from.1 - at_v.1);
        let arc = held.map_or(0.0, |s| s.arc);
        if let (Some(g), Some(c)) = (g, came) {
            if !living_rules::combat::guarded(g, c, arc) {
                defense = Aim::None;
                turned = true;
            }
        }
    }
    let code = sc.shapes().code(skill);
    let shown = |kind: u8, amount: f32| crate::combat::show(ctx, now, crate::combat::Seen { kind, actor: attacker, target: victim, skill: code, at: at_v, dir: living_rules::combat::unit(at_v.0 - from.0, at_v.1 - from.1).unwrap_or((0.0, 0.0)), amount, ..Default::default() });
    common::count(|k| match defense {
        Aim::Dash => k.dodged += 1,
        Aim::Facing => k.blocked += 1,
        _ => k.hits += 1,
    });
    if defense == Aim::Dash {
        return dodged(ctx, attacker, &vc, skill, from, at_v, now);
    }
    if turned {
        percept(ctx, &vc, now, "combat", attacker, victim, at_v, format!("Your guard faced the wrong way: {}'s blow came from the side.", common::label_for(ctx, &vc, attacker)), 0.5);
    }
    let amount = if defense == Aim::Facing {
        if let Some(ac) = ctx.db.character().id().find(attacker) {
            percept(ctx, &ac, now, "combat", victim, attacker, at_v, format!("{} blocked your blow.", common::label_cap(ctx, &ac, victim)), 0.5);
        }
        percept(ctx, &vc, now, "combat", attacker, victim, at_v, format!("You blocked {}'s blow.", common::label_for(ctx, &vc, attacker)), 0.5);
        amount * takes
    } else {
        amount
    };
    // Striking someone who has given in: the first such blow is news to everyone.
    let yielded = vc.kind == "person" && yielding(ctx, victim, &vc.kind, now);
    let struck_since_yield = yielded && yielded_ago(ctx, victim, now).is_some_and(|ago| v.hurt_ms >= now.saturating_sub(ago as u64) && v.hurt_by == attacker);
    let first_blow = now.saturating_sub(v.hurt_ms) > 30_000 || v.hurt_by != attacker;
    common::settle(&mut v, now);
    v.hp = (v.hp - amount).max(0.0);
    v.hurt_ms = now;
    v.hurt_by = attacker;
    v.rate_key = 0;
    let dead = v.hp <= 0.0;
    ctx.db.vitals().id().update(v);
    shown(if defense == Aim::Facing { living_rules::combat::seen::BLOCKED } else { living_rules::combat::seen::HIT }, amount);
    crate::combat::refresh_band(ctx, victim, now);
    let at = ctx.db.body().id().find(victim).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let an = common::display(ctx, attacker);
    let vn = common::display(ctx, victim);
    let by_person = ctx.db.character().id().find(attacker).map_or(false, |c| c.kind == "person");
    common::wake(ctx, victim);
    let label = common::label_cap(ctx, &vc, attacker);
    let felt = if yielded { format!("{label} struck you though you had yielded ({amount:.0} damage)") } else { format!("{label} attacked you ({amount:.0} damage)") };
    percept(ctx, &vc, now, "attacked", attacker, victim, at, felt, 1.0);
    if yielded && !struck_since_yield {
        common::chronicle(ctx, now, "attack", attacker, victim, at, format!("{an} struck {vn}, though {vn} had yielded"));
        witnessed(ctx, now, at, "fight", attacker, victim, "{a} struck {b}, though {b} had yielded", 0.95, &[attacker, victim]);
        if vc.ai {
            perceive::request_deliberation(ctx, victim, &format!("{label} is attacking you, though you yielded!"), now);
        }
    } else if first_blow {
        if vc.kind == "person" || by_person {
            common::chronicle(ctx, now, "attack", attacker, victim, at, format!("{an} attacked {vn}"));
        }
        witnessed(ctx, now, at, "fight", attacker, victim, "{a} attacked {b}", 0.7, &[attacker, victim]);
        if vc.ai {
            perceive::request_deliberation(ctx, victim, &format!("{label} is attacking you!"), now);
        }
    } else if !dead {
        fight_report(ctx, victim, attacker, now);
        fight_report(ctx, attacker, victim, now);
    }
    if dead {
        // The killer takes what it can carry; the rest is left to rot.
        let sc = common::scripts(ctx);
        let killer_kind = ctx.db.character().id().find(attacker).map(|c| c.kind).unwrap_or_default();
        let limit = sc.num_of("carry_limit", &killer_kind, 40.0) as u32;
        let mut room = limit.saturating_sub(common::inv_list(ctx, attacker as u64).iter().map(|(_, q)| *q).sum::<u32>());
        let mut left = 0;
        for (item, n) in [("meat", sc.num_of("carcass_meat", &vc.kind, 0.0) as u32), ("hide", sc.num_of("carcass_hide", &vc.kind, 0.0) as u32)] {
            let take = n.min(room);
            room -= take;
            left += n - take;
            if take > 0 {
                common::inv_add(ctx, attacker as u64, item, take);
            }
        }
        if left > 0 {
            if let Some(ac) = ctx.db.character().id().find(attacker) {
                percept(ctx, &ac, now, "body", victim, attacker, at, format!("You could not carry all of the {} (your pack is full); the rest is left to rot.", vc.kind), 0.3);
            }
        }
        // A person killed by a person: a killing, counted apart from deaths to animals.
        if by_person && vc.kind == "person" {
            common::chronicle(ctx, now, "killing", attacker, victim, at, if yielded { format!("{an} killed {vn}, who had yielded") } else { format!("{an} killed {vn}") });
        }
        // The death record names the killer as the victim knew them (`perceived_of`): "killed
        // by a stranger" unless the name was known. The chronicle above keeps the real names.
        let by = common::label_for(ctx, &vc, attacker);
        die(ctx, victim, &if yielded { format!("killed by {by}, after yielding") } else { format!("killed by {by}") }, now, attacker);
        return format!("killed {vn} ({amount:.0})");
    }
    if defense == Aim::Facing {
        format!("blocked, {amount:.0} got through")
    } else {
        format!("hit for {amount:.0}")
    }
}

/// A dodge sets off: its cooldown runs, others see it, its energy is spent.
fn dashed(ctx: &ReducerContext, act: &Activity, now: u64) {
    let sc = common::scripts(ctx);
    let skill = act.skill.as_str();
    crate::combat::started(ctx, act.id, skill, now);
    let here = ctx.db.body().id().find(act.id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let kind = ctx.db.character().id().find(act.id).map(|c| c.kind).unwrap_or_default();
    let speed = sc.num_of(&format!("{skill}_speed"), &kind, 9.0).max(1.0) as f32;
    let len = dist(here, (act.target.x, act.target.y));
    let aim = living_rules::combat::unit(act.target.x - here.0, act.target.y - here.1).unwrap_or((0.0, 0.0));
    let ends = now + (len / speed * 1000.0) as u64;
    crate::combat::set_act(ctx, act.id, skill, now, ends, ends + sc.num_of("combat_recover", skill, 0.0) as u64, 0, aim);
    crate::combat::accepted(ctx, act, now);
    let sctx = skill_ctx(ctx, act.id, act, now);
    if let Ok(fx) = sc.done(skill, &sctx) {
        let _ = apply(ctx, act, &sctx, fx, now);
    }
}

/// A held move let go of (a player's guard): it ends as done.
pub fn let_go(ctx: &ReducerContext, a: Activity, now: u64) {
    if a.phase == 1 {
        complete(ctx, a, now);
    } else {
        cancel(ctx, a, now, None);
    }
}

/// What a missile of `skill` loosed by `owner` does to `victim` (the skill's `_hit` effects,
/// weighed with the victim as the target).
pub fn missile_effects(ctx: &ReducerContext, owner: u32, skill: &str, victim: u32, now: u64) -> Result<Vec<Effect>, String> {
    let at = ctx.db.body().id().find(owner).map(|b| pos(&b, now)).or_else(|| ctx.db.body().id().find(victim).map(|b| pos(&b, now))).unwrap_or((0.0, 0.0));
    let a = Activity {
        id: owner,
        skill: skill.into(),
        phase: 1,
        node: ORPHAN,
        revision: 0,
        target: TargetRef { class: 3, id: victim as u64, x: at.0, y: at.1 },
        item: String::new(),
        qty: 0,
        started_ms: now,
        ends_ms: now,
        label: String::new(),
        text: String::new(),
        topic: String::new(),
        victim,
        want: String::new(),
        want_qty: 0,
    };
    let sctx = if ctx.db.character().id().find(owner).is_some_and(|c| c.alive) {
        skill_ctx(ctx, owner, &a, now)
    } else {
        // Its archer is dead: the missile still flies and strikes as an ordinary one.
        SkillCtx { actor: ActorFacts { id: owner, ..Default::default() }, target: target_facts(ctx, &a.target, at, now), skill: skill.into(), ..Default::default() }
    };
    common::scripts(ctx).hit(skill, &sctx)
}

/// A menace: the target sees it coming (it counts as being threatened while it lasts), and so
/// does anyone watching.
fn threatened(ctx: &ReducerContext, me: u32, victim: u32, now: u64) {
    let Some(vc) = ctx.db.character().id().find(victim) else { return };
    let with = if common::inv_count(ctx, me as u64, "spear") > 0 {
        "spear raised"
    } else if common::inv_count(ctx, me as u64, "bow") > 0 {
        "bow drawn"
    } else {
        "fists raised"
    };
    let at = ctx.db.body().id().find(victim).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let label = common::label_for(ctx, &vc, me);
    percept(ctx, &vc, now, "threat", me, victim, at, format!("{label} threatens you, {with}."), 0.9);
    witnessed(ctx, now, at, "threat", me, victim, &format!("{{a}} threatens {{b}}, {with}"), 0.5, &[me, victim]);
    common::chronicle(ctx, now, "threat", me, victim, at, format!("{} threatened {}", common::display(ctx, me), common::display(ctx, victim)));
    if vc.ai {
        perceive::request_deliberation(ctx, victim, &format!("{label} is threatening you, {with}!"), now);
    }
}

/// Giving in: to the target, else to whoever last hurt the yielder (within half a minute).
fn give_in(ctx: &ReducerContext, me: u32, a: &Activity, at: (f32, f32), now: u64) -> String {
    let to = if a.target.class == 3 && a.target.id as u32 != me {
        a.target.id as u32
    } else {
        ctx.db.vitals().id().find(me).filter(|v| v.hurt_ms != 0 && now.saturating_sub(v.hurt_ms) < 30_000).map_or(0, |v| v.hurt_by)
    };
    set_mark(ctx, me, YIELD_MARK, now);
    let my_name = common::name_of(ctx, me);
    let secs = common::scripts(ctx).num_of("yield_ms", "person", 20_000.0) / 1000.0;
    if to == 0 {
        common::chronicle(ctx, now, "yield", me, 0, at, format!("{my_name} yielded"));
        witnessed(ctx, now, at, "yield", me, 0, "{a} gives in, guard down and hands raised", 0.6, &[me]);
        return format!("you gave in; for {secs:.0} seconds you do not strike back");
    }
    common::chronicle(ctx, now, "yield", me, to, at, format!("{my_name} yielded to {}", common::display(ctx, to)));
    if let Some(tc) = ctx.db.character().id().find(to) {
        percept(ctx, &tc, now, "yield", me, to, at, format!("{} yields to you: guard down, hands raised.", common::label_cap(ctx, &tc, me)), 0.9);
        common::wake(ctx, to);
    }
    witnessed(ctx, now, at, "yield", me, to, "{a} yields to {b}, guard down and hands raised", 0.6, &[me, to]);
    let to_seen = ctx.db.character().id().find(me).map(|c| common::label_for(ctx, &c, to)).unwrap_or_else(|| common::name_of(ctx, to));
    format!("you yielded to {to_seen}; for {secs:.0} seconds you do not strike back")
}

pub fn die(ctx: &ReducerContext, id: u32, cause: &str, now: u64, killer: u32) {
    let Some(mut c) = ctx.db.character().id().find(id) else { return };
    if !c.alive {
        return;
    }
    let at = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((c.home_x, c.home_y));
    // What the rules make of it, while the dead's records and things are still there.
    crate::records::on_death(ctx, id, now);
    c.alive = false;
    c.died_ms = now;
    c.cause = cause.into();
    // A played character that dies under the minds is its person's again (the death screen).
    crate::presence::died(ctx, &mut c);
    let name = c.name.clone();
    let kind = c.kind.clone();
    ctx.db.character().id().update(c);
    let items = common::inv_list(ctx, id as u64);
    for r in ctx.db.inventory().owner().filter(id as u64).collect::<Vec<_>>() {
        ctx.db.inventory().id().delete(r.id);
    }
    if let Some(m) = ctx.db.membership().member().find(id) {
        ctx.db.membership().id().delete(m.id);
        crate::perception::knowledge_changed(None);
    }
    // What only this person knew how to do is gone unless they taught or wrote it down.
    for k in ctx.db.know_how().actor().filter(id).map(|k| k.id).collect::<Vec<_>>() {
        ctx.db.know_how().id().delete(k);
    }
    if kind == "person" {
        common::invalidate_structures(ctx);
        let s = ctx.db.structure().insert(Structure { id: 0, kind: "remains".into(), x: at.0, y: at.1, chunk: chunk_of(at.0, at.1), owner: id, built_ms: now });
        for (item, q) in items {
            common::inv_add(ctx, STRUCTURE_BIT | s.id, &item, q);
        }
        for mut t in ctx.db.artifact().holder().filter(id as u64).collect::<Vec<_>>() {
            t.holder = STRUCTURE_BIT | s.id;
            ctx.db.artifact().id().update(t);
        }
        common::chronicle(ctx, now, "death", id, killer, at, format!("{name} died ({cause})"));
    }
    ctx.db.body().id().delete(id);
    motion::remove(ctx, id);
    common::invalidate_bodies();
    ctx.db.activity().id().delete(id);
    ctx.db.doing().id().delete(id);
    ctx.db.mind_state().id().delete(id);
    ctx.db.infant_cry().infant().delete(id);
    ctx.db.vitals().id().delete(id);
    ctx.db.wake().id().delete(id);
    ctx.db.deliberation().actor().delete(id);
    forget_dead(ctx, id);
    retire(ctx, id);
    let text = if killer != 0 && cause.ends_with("after yielding") {
        "{a} was killed by {b} after yielding".to_string()
    } else if killer != 0 {
        "{a} was killed by {b}".to_string()
    } else {
        format!("{{a}} died ({cause})")
    };
    witnessed(ctx, now, at, "death", id, killer, &text, if kind == "person" { 1.0 } else { 0.5 }, &[id]);
    crate::combat::died(ctx, id, killer, at, now);
}
