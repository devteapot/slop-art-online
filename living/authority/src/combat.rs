//! Combat on the authority (docs/COMBAT.md): the timing every combat move shares, what a use
//! was meant, accepted and did (`skill_use`), what others can see of a fighter (`fighter`),
//! what each human player perceived (`combat_seen`, through `my_combat`), and missiles.
//!
//! The rules themselves stay where they were: checks, windups and effects in the Rhai skill
//! script, starting, approaching and completing in `act.rs`, blows and defenses in
//! `act::damage`. Players and behavior graphs reach the same `act::begin`; a player's direct
//! input runs as the `act::PLAYER` node (no walking into reach: out of reach is refused).

use crate::act::{self, Resolved};
use crate::common::{self, dist, pos};
use crate::tables::*;
use living_rules::combat::{self as rules, seen, Aim};
use spacetimedb::{Identity, ReducerContext, Table, ViewContext};
use std::cell::RefCell;
use std::collections::HashMap;

/// Uses of combat skills kept per character in `skill_use`.
pub const USES_KEPT: usize = 24;
/// How long a perceived event stays in `combat_seen` (ms); a death and its witnesses longer,
/// for the death screen.
const SEEN_MS: u64 = 4_000;
const DEATH_SEEN_MS: u64 = 120_000;

thread_local! {
    /// Living characters a person controls (not a mind, not the database), by id: the only
    /// viewers `combat_seen` is written for. Rebuilt after a join or a death.
    static HUMANS: RefCell<Option<HashMap<u32, Identity>>> = const { RefCell::new(None) };
}

pub fn invalidate_humans() {
    HUMANS.with(|h| *h.borrow_mut() = None);
}

fn human(ctx: &ReducerContext, id: u32) -> Option<Identity> {
    HUMANS.with(|h| {
        let mut h = h.borrow_mut();
        let map = h.get_or_insert_with(|| {
            let db = ctx.database_identity();
            let admin = common::world(ctx).admin;
            ctx.db.character().iter().filter(|c| c.alive && !c.ai && c.controller != db && c.controller != admin).map(|c| (c.id, c.controller)).collect()
        });
        map.get(&id).copied()
    })
}

/// The living characters people control, with their players' identities.
pub fn humans(ctx: &ReducerContext) -> Vec<(u32, Identity)> {
    human(ctx, 0);
    HUMANS.with(|h| h.borrow().as_ref().map(|m| m.iter().map(|(id, who)| (*id, *who)).collect()).unwrap_or_default())
}

fn any_humans(ctx: &ReducerContext) -> bool {
    human(ctx, 0);
    HUMANS.with(|h| h.borrow().as_ref().is_some_and(|m| !m.is_empty()))
}

// ---- what players perceive ------------------------------------------------------------

/// One perceived event (see `living_rules::combat::seen`).
#[derive(Clone, Default)]
pub struct Seen {
    pub kind: u8,
    pub actor: u32,
    pub target: u32,
    pub skill: u8,
    pub at: (f32, f32),
    pub dir: (f32, f32),
    pub amount: f32,
    pub ms: u32,
    pub note: String,
}

fn insert(ctx: &ReducerContext, viewer: Identity, now: u64, ev: &Seen, amount: f32, keep_ms: u64) {
    ctx.db.combat_seen().insert(CombatSeen {
        id: 0,
        viewer,
        expires_ms: now + keep_ms,
        at_ms: now,
        kind: ev.kind,
        actor: ev.actor,
        target: ev.target,
        skill: ev.skill,
        x: ev.at.0,
        y: ev.at.1,
        dx: ev.dir.0,
        dy: ev.dir.1,
        amount,
        ms: ev.ms,
        note: ev.note.clone(),
    });
}

/// Tell every human player whose character can see `ev.at` (within its sight) what
/// happened. The two involved (actor and target) always learn of it, with the amount;
/// onlookers see that it happened, not the numbers.
pub fn show(ctx: &ReducerContext, now: u64, ev: Seen) {
    if !any_humans(ctx) {
        return;
    }
    let keep = if ev.kind == seen::DEATH { DEATH_SEEN_MS } else { SEEN_MS };
    let w = common::world(ctx);
    let mut told: Vec<u32> = Vec::new();
    for id in [ev.actor, ev.target] {
        if id != 0 && !told.contains(&id) {
            if let Some(viewer) = human(ctx, id) {
                insert(ctx, viewer, now, &ev, ev.amount, keep);
            }
            told.push(id);
        }
    }
    let reach = common::sight(ctx, &w, now).max(living_rules::TORCH_SIGHT);
    for c in common::creatures_near(ctx, ev.at, reach, now) {
        if told.contains(&c.id) {
            continue;
        }
        let Some(viewer) = human(ctx, c.id) else { continue };
        if c.dist > common::sight_for(ctx, c.id, &w, now) {
            continue;
        }
        told.push(c.id);
        let amount = if ev.kind == seen::LAUNCH { ev.amount } else { 0.0 };
        insert(ctx, viewer, now, &ev, amount, keep);
    }
}

/// Tell one character's player only (a refusal, a witness of their own death).
pub fn show_to(ctx: &ReducerContext, id: u32, now: u64, ev: Seen) {
    if let Some(viewer) = human(ctx, id) {
        let keep = if ev.kind == seen::WITNESS { DEATH_SEEN_MS } else { SEEN_MS };
        insert(ctx, viewer, now, &ev, ev.amount, keep);
    }
}

/// Perceived events older than their time are dropped (every tick; index range).
pub fn expire(ctx: &ReducerContext, now: u64) {
    let old: Vec<u64> = ctx.db.combat_seen().expires_ms().filter(..=now).map(|r| r.id).collect();
    for id in old {
        ctx.db.combat_seen().id().delete(id);
    }
}

// ---- timing ---------------------------------------------------------------------------

fn readiness(ctx: &ReducerContext, id: u32) -> Readiness {
    ctx.db.readiness().id().find(id).unwrap_or(Readiness { id, ready: Vec::new(), busy_until: 0, move_pending: false, move_dx: 0.0, move_dy: 0.0, move_run: false })
}

fn save(ctx: &ReducerContext, r: Readiness) {
    if ctx.db.readiness().id().find(r.id).is_some() {
        ctx.db.readiness().id().update(r);
    } else {
        ctx.db.readiness().insert(r);
    }
}

/// Whether a combat move may start now: not while another one winds up (a dodge excepted),
/// not during the recovery after a release (a dodge excepted), not before its cooldown ends.
pub fn gate(ctx: &ReducerContext, id: u32, skill: &str, cur: Option<&Activity>, now: u64) -> Result<(), String> {
    let sc = common::scripts(ctx);
    let shapes = sc.shapes();
    let Some(shape) = shapes.get(skill).filter(|s| s.timed) else { return Ok(()) };
    // A dash may cut in anywhere; a raised guard does not hold up the next move.
    let dash = shape.aim == Aim::Dash;
    if !dash {
        if let Some(a) = cur.filter(|a| a.phase == 1 && shapes.get(&a.skill).is_some_and(|s| s.timed && s.aim != Aim::Facing)) {
            return Err(format!("already in the middle of a {}", a.skill));
        }
    }
    let Some(r) = ctx.db.readiness().id().find(id) else { return Ok(()) };
    if !dash && r.busy_until > now {
        return Err("still recovering from your last move".into());
    }
    if let Some(t) = r.ready.iter().find(|t| t.skill == skill).filter(|t| t.at_ms > now) {
        return Err(format!("{skill} is not ready yet ({:.1} s)", (t.at_ms - now) as f32 / 1000.0));
    }
    Ok(())
}

/// A move started: its cooldown runs from now.
pub fn started(ctx: &ReducerContext, id: u32, skill: &str, now: u64) {
    let cd = common::scripts(ctx).num_of("combat_cooldown", skill, 0.0).max(0.0) as u64;
    let mut r = readiness(ctx, id);
    r.ready.retain(|t| t.skill != skill && t.at_ms > now);
    if cd > 0 {
        r.ready.push(Ready { skill: skill.into(), from_ms: now, at_ms: now + cd });
    }
    save(ctx, r);
}

/// A move released: the recovery after it. Returns when it ends.
pub fn recovering(ctx: &ReducerContext, id: u32, skill: &str, now: u64) -> u64 {
    let rec = common::scripts(ctx).num_of("combat_recover", skill, 0.0).max(0.0) as u64;
    let until = now + rec;
    if rec > 0 {
        let mut r = readiness(ctx, id);
        r.busy_until = r.busy_until.max(until);
        save(ctx, r);
    }
    until
}

/// A player moved while rooted in a move: the movement waits until the move ends.
pub fn defer_move(ctx: &ReducerContext, id: u32, dx: f32, dy: f32, run: bool) {
    let mut r = readiness(ctx, id);
    r.move_pending = true;
    r.move_dx = dx;
    r.move_dy = dy;
    r.move_run = run;
    save(ctx, r);
}

/// The movement a player asked for while rooted, once the move is over.
pub fn resume_move(ctx: &ReducerContext, id: u32, now: u64) {
    let Some(mut r) = ctx.db.readiness().id().find(id).filter(|r| r.move_pending) else { return };
    r.move_pending = false;
    let (dx, dy, run) = (r.move_dx, r.move_dy, r.move_run);
    ctx.db.readiness().id().update(r);
    let dir = (dx != 0.0 || dy != 0.0).then_some((dx, dy));
    if let Err(e) = crate::motion::intent(ctx, id, dir, run, || act::walk_speed(ctx, id, now), now) {
        log::debug!("resume move {id}: {e}");
    }
}

/// Whether a player's movement must wait: a rooted move winds up, or a dodge dashes.
pub fn rooted_now(ctx: &ReducerContext, id: u32) -> bool {
    let Some(a) = ctx.db.activity().id().find(id).filter(|a| a.node == act::PLAYER) else { return false };
    common::scripts(ctx).combat(&a.skill).is_some_and(|s| (a.phase == 1 && s.rooted) || s.aim == Aim::Dash)
}

// ---- what others see of a fighter ---------------------------------------------------------

fn fighter(ctx: &ReducerContext, id: u32, now: u64) -> Fighter {
    ctx.db.fighter().id().find(id).unwrap_or_else(|| Fighter { id, band: band_now(ctx, id, now), act: 0, act_ms: 0, release_ms: 0, until_ms: 0, target: 0, aim_x: 0.0, aim_y: 0.0 })
}

fn put_fighter(ctx: &ReducerContext, f: Fighter) {
    match ctx.db.fighter().id().find(f.id) {
        Some(old) if old == f => {}
        Some(_) => {
            ctx.db.fighter().id().update(f);
        }
        None => {
            ctx.db.fighter().insert(f);
        }
    }
}

fn band_now(ctx: &ReducerContext, id: u32, now: u64) -> u8 {
    ctx.db.vitals().id().find(id).map_or(4, |v| rules::band(common::needs(&v, now).hp, v.max_hp))
}

/// A move under way: what it is, its timing and where it faces.
#[allow(clippy::too_many_arguments)]
pub fn set_act(ctx: &ReducerContext, id: u32, skill: &str, now: u64, release_ms: u64, until_ms: u64, target: u32, aim: (f32, f32)) {
    let mut f = fighter(ctx, id, now);
    f.act = common::scripts(ctx).shapes().code(skill);
    f.act_ms = now;
    f.release_ms = release_ms;
    f.until_ms = until_ms;
    f.target = target;
    f.aim_x = aim.0;
    f.aim_y = aim.1;
    put_fighter(ctx, f);
}

/// The move ends (or its recovery is now known) at `until`.
pub fn act_until(ctx: &ReducerContext, id: u32, until: u64) {
    if let Some(mut f) = ctx.db.fighter().id().find(id) {
        if f.until_ms != until {
            f.until_ms = until;
            ctx.db.fighter().id().update(f);
        }
    }
}

/// Health changed (a blow, a heal): the band others see follows, written only when it moves;
/// a first blow gives the character its `fighter` row.
pub fn refresh_band(ctx: &ReducerContext, id: u32, now: u64) {
    let b = band_now(ctx, id, now);
    match ctx.db.fighter().id().find(id) {
        Some(mut f) if f.band != b => {
            f.band = b;
            ctx.db.fighter().id().update(f);
        }
        Some(_) => {}
        None => {
            let mut f = fighter(ctx, id, now);
            f.band = b;
            ctx.db.fighter().insert(f);
        }
    }
}

/// Once a second: bands follow healing and wasting between blows.
pub fn housekeeping(ctx: &ReducerContext, now: u64) {
    let rows: Vec<Fighter> = ctx.db.fighter().iter().collect();
    for f in rows {
        let b = band_now(ctx, f.id, now);
        if b != f.band {
            ctx.db.fighter().id().update(Fighter { band: b, ..f });
        }
    }
}

// ---- what a use was meant, accepted and did ---------------------------------------------

/// An attempt: what was asked, before the rules weigh it.
pub fn attempt(ctx: &ReducerContext, actor: u32, skill: &str, source: &str, target: u32, aim: (f32, f32), now: u64) -> u64 {
    let row = ctx.db.skill_use().insert(SkillUse { id: 0, actor, skill: skill.into(), source: source.into(), at_ms: now, target, aim_x: aim.0, aim_y: aim.1, accepted_ms: 0, released_ms: 0, outcome: String::new(), outcome_ms: 0 });
    let mut ids: Vec<u64> = ctx.db.skill_use().actor().filter(actor).map(|u| u.id).collect();
    if ids.len() > USES_KEPT {
        ids.sort_unstable();
        for id in &ids[..ids.len() - USES_KEPT] {
            ctx.db.skill_use().id().delete(*id);
        }
    }
    row.id
}

fn open_use(ctx: &ReducerContext, actor: u32, skill: &str) -> Option<SkillUse> {
    ctx.db.skill_use().actor().filter(actor).filter(|u| u.skill == skill && u.outcome.is_empty()).max_by_key(|u| u.id)
}

/// The rules accepted it: the windup (or dash) starts. A graph's or act's use is recorded
/// from here (its refusals go back to its graph leaf or act, as before).
pub fn accepted(ctx: &ReducerContext, a: &Activity, now: u64) {
    let source = match a.node {
        act::PLAYER => "player",
        act::ACT => "act",
        _ => "graph",
    };
    let mut u = match open_use(ctx, a.id, &a.skill).filter(|u| u.accepted_ms == 0) {
        Some(u) => u,
        None => {
            let creature = if a.target.class == 3 { a.target.id as u32 } else { 0 };
            let id = attempt(ctx, a.id, &a.skill, source, creature, (a.target.x, a.target.y), now);
            match ctx.db.skill_use().id().find(id) {
                Some(u) => u,
                None => return,
            }
        }
    };
    u.accepted_ms = now;
    ctx.db.skill_use().id().update(u);
}

pub fn released(ctx: &ReducerContext, actor: u32, skill: &str, now: u64) {
    if let Some(mut u) = open_use(ctx, actor, skill) {
        u.released_ms = now;
        ctx.db.skill_use().id().update(u);
    }
}

/// What happened (or why it was refused or broken off).
pub fn outcome(ctx: &ReducerContext, actor: u32, skill: &str, text: &str, now: u64) {
    if let Some(mut u) = open_use(ctx, actor, skill) {
        u.outcome = if text.is_empty() { "done".into() } else { text.chars().take(200).collect() };
        u.outcome_ms = now;
        ctx.db.skill_use().id().update(u);
    }
}

fn outcome_of(ctx: &ReducerContext, use_id: u64, text: &str, now: u64) {
    if let Some(mut u) = ctx.db.skill_use().id().find(use_id) {
        u.outcome = text.chars().take(200).collect();
        u.outcome_ms = now;
        ctx.db.skill_use().id().update(u);
    }
}

// ---- missiles ------------------------------------------------------------------------------

/// Sweep cadence: every tick (the performance contract's 60 Hz combat).
const SWEEP_MS: u64 = 16;

/// Loose a missile from `from` along `dir` (unit).
pub fn launch(ctx: &ReducerContext, owner: u32, skill: &str, from: (f32, f32), dir: (f32, f32), spec: rules::MissileSpec, now: u64) {
    let use_id = open_use(ctx, owner, skill).map_or(0, |u| u.id);
    // It leaves from just in front of the body, so it does not strike its owner.
    let start = (from.0 + dir.0 * 0.5, from.1 + dir.1 * 0.5);
    ctx.db.missile().insert(Missile { id: 0, owner, skill: skill.into(), x: start.0, y: start.1, t_ms: now, dx: dir.0, dy: dir.1, speed: spec.speed, left: spec.range - 0.5, radius: spec.radius, next_ms: now + SWEEP_MS, use_id });
    show(ctx, now, Seen { kind: seen::LAUNCH, actor: owner, skill: common::scripts(ctx).shapes().code(skill), at: start, dir, amount: spec.speed, ms: ((spec.range - 0.5) / spec.speed * 1000.0) as u32, ..Default::default() });
    if use_id != 0 {
        outcome_of(ctx, use_id, "", now);
        if let Some(mut u) = ctx.db.skill_use().id().find(use_id) {
            u.outcome = "in flight".into();
            ctx.db.skill_use().id().update(u);
        }
    }
}

/// Move every due missile along its path since its last sweep and strike the first body
/// (or wall) it meets.
pub fn missiles(ctx: &ReducerContext, now: u64) {
    let due: Vec<Missile> = ctx.db.missile().next_ms().filter(..=now).collect();
    if due.is_empty() {
        return;
    }
    let map = common::map(ctx);
    let sc = common::scripts(ctx);
    for mut m in due {
        let step = (m.speed * now.saturating_sub(m.t_ms) as f32 / 1000.0).min(m.left);
        let a = (m.x, m.y);
        let b = (m.x + m.dx * step, m.y + m.dy * step);
        // The first creature along the step (its body radius added to the missile's).
        let mid = ((a.0 + b.0) * 0.5, (a.1 + b.1) * 0.5);
        let mut first: Option<(f32, u32, (f32, f32))> = None;
        for c in common::creatures_near(ctx, mid, step * 0.5 + m.radius + 1.0, now) {
            if c.id == m.owner {
                continue;
            }
            if let Some(t) = rules::sweep(a, b, c.pos, m.radius + rules::body_radius(&c.kind)) {
                if first.is_none_or(|(ft, _, _)| t < ft) {
                    first = Some((t, c.id, c.pos));
                }
            }
        }
        // A wall, rock or shut gate before it stops the missile there.
        let wall = wall_along(&map, a, b);
        match (first, wall) {
            (Some((t, victim, _)), w) if w.is_none_or(|wt| t <= wt) => {
                let at = (a.0 + (b.0 - a.0) * t, a.1 + (b.1 - a.1) * t);
                ctx.db.missile().id().delete(m.id);
                strike(ctx, &m, victim, at, now);
            }
            (_, Some(wt)) => {
                let at = (a.0 + (b.0 - a.0) * wt, a.1 + (b.1 - a.1) * wt);
                ctx.db.missile().id().delete(m.id);
                show(ctx, now, Seen { kind: seen::IMPACT, actor: m.owner, skill: sc.shapes().code(&m.skill), at, dir: (m.dx, m.dy), ..Default::default() });
                outcome_of(ctx, m.use_id, "struck a wall", now);
            }
            _ => {
                m.left -= step;
                if m.left <= 0.01 {
                    ctx.db.missile().id().delete(m.id);
                    show(ctx, now, Seen { kind: seen::IMPACT, actor: m.owner, skill: sc.shapes().code(&m.skill), at: b, dir: (m.dx, m.dy), ..Default::default() });
                    outcome_of(ctx, m.use_id, "hit nothing", now);
                } else {
                    m.x = b.0;
                    m.y = b.1;
                    m.t_ms = now;
                    m.next_ms = now + SWEEP_MS;
                    ctx.db.missile().id().update(m);
                }
            }
        }
    }
}

/// Where along `a → b` (fraction) a missile first meets a tile it cannot fly through.
fn wall_along(map: &living_rules::map::Map, a: (f32, f32), b: (f32, f32)) -> Option<f32> {
    let len = dist(a, b);
    let n = (len / 0.25).ceil().max(1.0) as u32;
    (1..=n).map(|i| i as f32 / n as f32).find(|t| {
        let p = (a.0 + (b.0 - a.0) * t, a.1 + (b.1 - a.1) * t);
        !map.passable_missile(p.0, p.1)
    })
}

/// A missile reached a creature: the skill's `_hit` effects apply to it, through the same
/// blow and defense rules as any other (a dodge lets it pass, a guard in front takes most).
fn strike(ctx: &ReducerContext, m: &Missile, victim: u32, at: (f32, f32), now: u64) {
    let sc = common::scripts(ctx);
    let code = sc.shapes().code(&m.skill);
    // A dash in progress lets it pass through, but it is spent all the same.
    if ctx.db.activity().id().find(victim).is_some_and(|a| sc.combat(&a.skill).is_some_and(|s| s.aim == Aim::Dash)) {
        show(ctx, now, Seen { kind: seen::DODGED, actor: m.owner, target: victim, skill: code, at, dir: (m.dx, m.dy), ..Default::default() });
        show(ctx, now, Seen { kind: seen::IMPACT, actor: m.owner, target: 0, skill: code, at, dir: (m.dx, m.dy), ..Default::default() });
        outcome_of(ctx, m.use_id, "dodged", now);
        return;
    }
    let effects = match act::missile_effects(ctx, m.owner, &m.skill, victim, now) {
        Ok(e) => e,
        Err(why) => {
            show(ctx, now, Seen { kind: seen::IMPACT, actor: m.owner, target: victim, skill: code, at, dir: (m.dx, m.dy), ..Default::default() });
            outcome_of(ctx, m.use_id, &why, now);
            return;
        }
    };
    show(ctx, now, Seen { kind: seen::IMPACT, actor: m.owner, target: victim, skill: code, at, dir: (m.dx, m.dy), ..Default::default() });
    // The blow comes from behind the missile's path.
    let from = (at.0 - m.dx * 2.0, at.1 - m.dy * 2.0);
    let mut dealt = String::new();
    for e in effects {
        if let living_rules::script::Effect::Damage { amount } = e {
            dealt = act::damage(ctx, m.owner, victim, amount, "kill", &m.skill, from, now);
        }
    }
    outcome_of(ctx, m.use_id, &format!("struck {}: {dealt}", common::display(ctx, victim)), now);
}

/// A death: everyone who could see it is told, and the one who died learns who saw it.
pub fn died(ctx: &ReducerContext, id: u32, killer: u32, at: (f32, f32), now: u64) {
    show(ctx, now, Seen { kind: seen::DEATH, actor: id, target: killer, at, ..Default::default() });
    if human(ctx, id).is_some() {
        let w = common::world(ctx);
        let r = common::sight(ctx, &w, now).max(living_rules::TORCH_SIGHT);
        for c in common::creatures_near(ctx, at, r, now) {
            if c.id == id || c.dist > common::sight_for(ctx, c.id, &w, now) {
                continue;
            }
            show_to(ctx, id, now, Seen { kind: seen::WITNESS, actor: c.id, target: id, at: c.pos, ..Default::default() });
        }
    }
    ctx.db.fighter().id().delete(id);
    ctx.db.readiness().id().delete(id);
    for m in ctx.db.missile().iter().filter(|m| m.owner == id).map(|m| m.id).collect::<Vec<_>>() {
        ctx.db.missile().id().delete(m);
    }
    if let Some(viewer) = human(ctx, id) {
        crate::perception::forget(ctx, viewer);
    }
    invalidate_humans();
}

// ---- the rules' numbers for clients ------------------------------------------------------

/// Rewrite `skill_card` from a skill script: one row per combat skill (a person's numbers,
/// as a newcomer has them), with its code, its place on the bar and how it is aimed. Rows of
/// skills the script no longer has go.
pub fn cards(ctx: &ReducerContext, sc: &living_rules::script::Scripts) {
    let shapes = sc.shapes();
    for old in ctx.db.skill_card().iter().filter(|c| shapes.get(&c.skill).is_none()).map(|c| c.skill).collect::<Vec<_>>() {
        ctx.db.skill_card().skill().delete(old);
    }
    for (skill, shape) in shapes.iter() {
        let c = living_rules::script::SkillCtx { actor: living_rules::script::ActorFacts { kind: "person".into(), ..Default::default() }, skill: skill.to_string(), qty: shape.hold_ms, ..Default::default() };
        let missile = if shape.missile { sc.missile(skill, &c).ok() } else { None };
        let reach = match (missile, shape.aim) {
            (Some(m), _) => m.range,
            (None, Aim::Dash) => sc.num_of(&format!("{skill}_dist"), "person", 0.0) as f32,
            _ => living_rules::catalog::skill(skill).map_or(0.0, |k| k.reach) + if shape.melee { sc.num_of("lunge", "person", 0.0) as f32 } else { 0.0 },
        };
        let card = SkillCard {
            skill: skill.to_string(),
            slot: shapes.bar().iter().position(|b| b == skill).map_or(NOT_ON_BAR, |i| i as u8),
            cost: sc.num_of("combat_cost", skill, 0.0) as f32,
            windup_ms: if matches!(shape.aim, Aim::Dash | Aim::Facing) { 0 } else { sc.duration_ms(skill, &c).unwrap_or(0) as u32 },
            recover_ms: sc.num_of("combat_recover", skill, 0.0) as u32,
            cooldown_ms: sc.num_of("combat_cooldown", skill, 0.0) as u32,
            reach,
            code: shape.code,
            aim: shape.aim.as_str().into(),
            radius: missile.map_or(0.0, |m| m.radius),
            arc: shape.arc,
            needs: shape.needs.join(","),
            knows: shape.knows.join(","),
        };
        if ctx.db.skill_card().skill().find(card.skill.clone()).is_some() {
            ctx.db.skill_card().skill().update(card);
        } else {
            ctx.db.skill_card().insert(card);
        }
    }
}

/// `skill_card.slot` of a combat skill that is not on the bar.
pub const NOT_ON_BAR: u8 = u8::MAX;

// ---- the player's skill input ------------------------------------------------------------

fn my_character(ctx: &ReducerContext) -> Result<Character, String> {
    ctx.db.character().controller().filter(ctx.sender()).find(|c| c.alive && !c.ai).ok_or_else(|| "you have no living character".into())
}

/// Use a skill on the bar (the rules' `skill_bar()`; `skill_card.slot`): `target` is the creature
/// aimed at (0 for none: a heal then means yourself), `(x, y)` the ground point aimed at
/// (tiles; skillshots fly that way, a dodge dashes that way, a guard faces it). The attempt,
/// whether the rules accepted it, and what happened are recorded in `skill_use`; a refusal is
/// told back through `my_combat` (`REFUSED`), so the reducer itself succeeds.
#[spacetimedb::reducer]
pub fn use_skill(ctx: &ReducerContext, skill: String, target: u32, x: f32, y: f32) -> Result<(), String> {
    let me = my_character(ctx)?;
    let sc = common::scripts(ctx);
    let Some(shape) = sc.combat(&skill).filter(|_| sc.shapes().on_bar(&skill)) else {
        return Err(format!("{skill} is not on the skill bar"));
    };
    if !x.is_finite() || !y.is_finite() {
        return Err("aim must be finite".into());
    }
    let now = common::now_ms(ctx);
    if !crate::motion::spend_input(ctx, me.id, now) {
        return Err("too many inputs".into());
    }
    let use_id = attempt(ctx, me.id, &skill, "player", target, (x, y), now);
    let refuse = |why: String| {
        outcome_of(ctx, use_id, &format!("refused: {why}"), now);
        let at = ctx.db.body().id().find(me.id).map(|b| pos(&b, now)).unwrap_or((x, y));
        show_to(ctx, me.id, now, Seen { kind: seen::REFUSED, actor: me.id, target, skill: shape.code, at, note: why.chars().take(120).collect(), ..Default::default() });
        Ok(())
    };
    let Some(body) = ctx.db.body().id().find(me.id) else { return refuse("you have no body".into()) };
    let here = pos(&body, now);
    let aim = rules::unit(x - here.0, y - here.1);
    // How the rules say the skill is aimed (its `<skill>_combat()`), not which skill it is.
    let resolved = match shape.aim {
        Aim::Creature => match creature(ctx, target, now) {
            Some(t) => t,
            None => return refuse(format!("no one there to {skill}")),
        },
        Aim::SelfOrAlly => match if target == 0 { creature(ctx, me.id, now) } else { creature(ctx, target, now) } {
            Some(t) => t,
            None => return refuse(format!("no one there to {skill}")),
        },
        Aim::Point => {
            let Some(d) = aim.or_else(|| creature(ctx, target, now).and_then(|t| rules::unit(t.at.0 - here.0, t.at.1 - here.1))) else { return refuse("aim somewhere".into()) };
            Resolved::point((here.0 + d.0 * 4.0, here.1 + d.1 * 4.0))
        }
        Aim::Facing => Resolved::point(aim.map_or((here.0 + body.heading.cos(), here.1 + body.heading.sin()), |d| (here.0 + d.0, here.1 + d.1))),
        // A dash goes the way it is aimed, else away from what is coming.
        Aim::Dash | Aim::None => aim.map_or_else(Resolved::none, |d| Resolved::point((here.0 + d.0, here.1 + d.1))),
    };
    // Taking the controls: the plan becomes waiting, as for movement. A walk under way
    // resumes once a rooting move or a dash is over.
    crate::player_controls(ctx, me.id, now)?;
    let mut deferred = false;
    if (shape.rooted || shape.aim == Aim::Dash) && !rooted_now(ctx, me.id) {
        if let Some(st) = ctx.db.steer().id().find(me.id).filter(|st| st.goal == crate::motion::GOAL_DIRECTION) {
            defer_move(ctx, me.id, st.gx, st.gy, st.flags & crate::motion::FLAG_RUN != 0);
            deferred = true;
        }
    }
    // A guard is held until let go, at most as long as the rules allow.
    let qty = shape.hold_ms;
    match act::begin(ctx, me.id, act::PLAYER, 0, &skill, resolved, "", qty, "", "", ("", 0), now) {
        Ok(()) => Ok(()),
        Err(why) => {
            // Nothing started, so the walk under way simply goes on.
            if let Some(mut r) = ctx.db.readiness().id().find(me.id).filter(|r| deferred && r.move_pending) {
                r.move_pending = false;
                ctx.db.readiness().id().update(r);
            }
            refuse(why)
        }
    }
}

/// Let go of a held skill (the guard).
#[spacetimedb::reducer]
pub fn release_skill(ctx: &ReducerContext, skill: String) -> Result<(), String> {
    let me = my_character(ctx)?;
    let now = common::now_ms(ctx);
    if let Some(a) = ctx.db.activity().id().find(me.id).filter(|a| a.skill == skill && a.node == act::PLAYER) {
        act::let_go(ctx, a, now);
    }
    Ok(())
}

/// A creature as a target, if it has a body.
fn creature(ctx: &ReducerContext, id: u32, now: u64) -> Option<Resolved> {
    if id == 0 {
        return None;
    }
    let c = ctx.db.character().id().find(id).filter(|c| c.alive)?;
    let b = ctx.db.body().id().find(id)?;
    Some(Resolved { class: 3, id: id as u64, at: pos(&b, now), kind: c.kind, name: c.name })
}

// ---- views for the controller -------------------------------------------------------------

/// What my character perceived of fights, for the next few seconds (my viewer rows only).
#[spacetimedb::view(accessor = my_combat, public)]
pub fn my_combat(ctx: &ViewContext) -> Vec<CombatSeen> {
    ctx.db.combat_seen().viewer().filter(ctx.sender()).collect()
}

/// My characters' cooldowns and recovery.
#[spacetimedb::view(accessor = my_readiness, public)]
pub fn my_readiness(ctx: &ViewContext) -> Vec<Readiness> {
    ctx.db.character().controller().filter(ctx.sender()).filter(|c| c.alive).filter_map(|c| ctx.db.readiness().id().find(c.id)).collect()
}

/// My characters' recent combat skill uses: what I tried, what the rules accepted and what
/// happened.
#[spacetimedb::view(accessor = my_skill_uses, public)]
pub fn my_skill_uses(ctx: &ViewContext) -> Vec<SkillUse> {
    ctx.db.character().controller().filter(ctx.sender()).filter(|c| c.alive).flat_map(|c| ctx.db.skill_use().actor().filter(c.id).collect::<Vec<_>>()).collect()
}
