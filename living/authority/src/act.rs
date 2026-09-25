//! Activities: starting skills, approaching targets, completing with Rhai effects,
//! damage, death and remains. Every outcome is reported back to the behavior node that
//! requested it (`mind_state.last`) and to perceiving witnesses.

use crate::motion::{self, IDLE};
use crate::perceive::{self, percept, witnessed};
use crate::tables::*;
use crate::common::{self, dist, pos};
use living_rules::catalog;
use living_rules::map::chunk_of;
use living_rules::script::{ActorFacts, Effect, SkillCtx, TargetFacts};
use spacetimedb::rand::Rng;
use spacetimedb::{ReducerContext, Table};

pub const ORPHAN: u16 = u16::MAX;
const CHASE_REPATH_MS: u64 = 1_200;

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

pub fn facts(ctx: &ReducerContext, id: u32, now: u64) -> ActorFacts {
    let w = common::world(ctx);
    let ch = ctx.db.character().id().find(id);
    let kind = ch.as_ref().map(|c| c.kind.clone()).unwrap_or_default();
    let age = ch.as_ref().map(|c| common::age_days(c, &w, now)).unwrap_or(20.0);
    let at = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let (hp, hunger, energy) = ctx.db.vitals().id().find(id).map(|v| {
        let n = common::needs(&v, now);
        (n.hp, n.hunger, n.energy)
    }).unwrap_or((0.0, 0.0, 0.0));
    let mut near_fire = false;
    let mut near_shelter = false;
    for (s, d) in common::structures_near(ctx, at, 4.0) {
        if s.kind == "campfire" && d <= 3.5 {
            near_fire = true;
        }
        if s.kind == "shelter" && d <= 2.5 {
            near_shelter = true;
        }
    }
    let _ = w;
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
    }
}

fn target_facts(ctx: &ReducerContext, t: &TargetRef, from: (f32, f32), now: u64) -> TargetFacts {
    let mut f = TargetFacts { class: "none".into(), ..Default::default() };
    match t.class {
        1 => {
            if let Some(n) = ctx.db.resource_node().id().find(t.id) {
                f.class = "resource".into();
                f.id = n.id;
                f.amount = common::amount_now(&n, now);
                f.dist = dist(from, (n.x, n.y));
                f.kind = n.kind;
            }
        }
        2 => {
            if let Some(s) = ctx.db.structure().id().find(t.id) {
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
                f.name = c.name;
                if let Some(b) = ctx.db.body().id().find(c.id) {
                    f.dist = dist(from, pos(&b, now));
                }
                if let Some(v) = ctx.db.vitals().id().find(c.id) {
                    f.hp = common::needs(&v, now).hp;
                }
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
    let actor = facts(ctx, id, now);
    let from = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let hour = common::hour(&w, now);
    SkillCtx { actor, target: target_facts(ctx, &a.target, from, now), item: a.item.clone(), qty: a.qty, night: living_rules::is_night(hour), hour }
}

fn label(skill: &str, item: &str, t: &Resolved) -> String {
    let mut s = skill.to_string();
    if !item.is_empty() {
        s.push(' ');
        s.push_str(item);
    }
    match t.class {
        1 | 2 => s.push_str(&format!(" → {}", t.kind)),
        3 => s.push_str(&format!(" → {}", if t.name.is_empty() { t.kind.clone() } else { t.name.clone() })),
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
        4 => Some((t.x, t.y)),
        _ => None,
    }
}

fn reach(skill: &str) -> f32 {
    catalog::skill(skill).map(|s| s.reach).unwrap_or(0.0)
}

fn speed(ctx: &ReducerContext, id: u32, now: u64) -> f32 {
    let sc = common::scripts(ctx);
    let c = SkillCtx { actor: facts(ctx, id, now), ..Default::default() };
    sc.move_speed(&c).unwrap_or(2.5)
}

/// Start an action for behavior node `node`. `cur` is the current activity, if any.
pub fn begin(ctx: &ReducerContext, id: u32, node: u16, revision: u32, skill: &str, target: Resolved, item: &str, qty: u32, now: u64) -> Result<(), String> {
    let cur = ctx.db.activity().id().find(id);
    if let Some(a) = &cur {
        // A new graph may continue what the character was already doing.
        if a.node == ORPHAN && a.skill == skill && a.target.class == target.class && a.target.id == target.id && a.item == item {
            let mut a = a.clone();
            a.node = node;
            a.revision = revision;
            ctx.db.activity().id().update(a);
            return Ok(());
        }
    }
    if let Some(a) = cur {
        cancel(ctx, a, now, None);
    }
    let me = ctx.db.body().id().find(id).ok_or("no body")?;
    let here = pos(&me, now);
    let mut target = target;
    let mut item = item.to_string();
    match skill {
        "wander" => {
            let map = common::map(ctx);
            let mut pick = None;
            for _ in 0..12 {
                let ang: f32 = ctx.rng().gen_range(0.0..std::f32::consts::TAU);
                let r: f32 = ctx.rng().gen_range(3.0..9.0);
                let p = (here.0 + ang.cos() * r, here.1 + ang.sin() * r);
                if map.at(p.0, p.1).walkable() {
                    pick = Some(p);
                    break;
                }
            }
            target = Resolved::point(pick.ok_or("nowhere to wander")?);
        }
        "flee" => {
            let from = target.at;
            let d = dist(here, from).max(0.1);
            let map = common::map(ctx);
            let mut pick = None;
            for spread in [0.0f32, 0.6, -0.6, 1.2, -1.2] {
                let base = (here.1 - from.1).atan2(here.0 - from.0) + spread;
                let p = (here.0 + base.cos() * 9.0, here.1 + base.sin() * 9.0);
                if map.at(p.0, p.1).walkable() {
                    pick = Some(p);
                    break;
                }
            }
            let _ = d;
            target = Resolved { class: 4, id: target.id, at: pick.ok_or("cornered")?, kind: target.kind, name: target.name };
        }
        "eat" | "give" | "store" if item == "food" => {
            item = common::best_food(ctx, id as u64).ok_or("no food in pack")?;
        }
        _ => {}
    }
    let r = reach(skill);
    let moving_skill = matches!(skill, "goto" | "wander" | "flee" | "follow");
    let needs_approach = target.class != 0 && (moving_skill || dist(here, target.at) > r);
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
    };
    if needs_approach && !(skill == "follow" && dist(here, target.at) <= r) {
        let sp = speed(ctx, id, now);
        let sp = if skill == "flee" { sp * 1.15 } else { sp };
        motion::start_move(ctx, id, target.at, sp, now)?;
        if target.class == 3 {
            act.ends_ms = now + CHASE_REPATH_MS;
        }
        if skill == "follow" {
            act.ends_ms = now + CHASE_REPATH_MS;
        }
        ctx.db.activity().insert(act);
        return Ok(());
    }
    if skill == "follow" {
        act.ends_ms = now + CHASE_REPATH_MS;
        ctx.db.activity().insert(act);
        return Ok(());
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
    motion::stop(ctx, act.id, now);
    act.ends_ms = now + dur.max(100);
    let id = act.id;
    if ctx.db.activity().id().find(id).is_some() {
        ctx.db.activity().id().update(act);
    } else {
        ctx.db.activity().insert(act);
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
    if a.phase == 0 {
        motion::stop(ctx, id, now);
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
        if a.node != ORPHAN {
            st.last = Some(LeafResult { node: a.node, revision: a.revision, ok, why: why.into() });
        }
        st.fails = if ok { 0 } else { st.fails.saturating_add(1) };
        ctx.db.mind_state().id().update(st);
    }
    // A failure identical to one in the last two minutes is not news.
    let repeat = !ok && ctx.db.mind_state().id().find(a.id).map_or(false, |st| st.marks.iter().any(|m| m.node == failure_mark(&a.label, why) && now.saturating_sub(m.at_ms) < 120_000));
    if !ok && !repeat {
        if let Some(mut st) = ctx.db.mind_state().id().find(a.id) {
            let key = failure_mark(&a.label, why);
            st.marks.retain(|m| m.node != key);
            st.marks.push(Mark { node: key, at_ms: now });
            if st.marks.len() > 24 {
                st.marks.remove(0);
            }
            ctx.db.mind_state().id().update(st);
        }
    }
    if let Some(c) = ctx.db.character().id().find(a.id).filter(|_| !repeat) {
        // Routine successes (gathering a berry, arriving somewhere) are not experiences worth
        // recording; failures and meaningful acts are.
        let notable = !ok || matches!(a.skill.as_str(), "build" | "craft" | "cook" | "give" | "store" | "take" | "attack" | "conceive");
        if c.ai && notable {
            let at = ctx.db.body().id().find(a.id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
            let text = if ok { format!("You finished: {}. {}", a.label, why) } else { format!("You failed to {}: {}", a.label, why) };
            percept(ctx, &c, now, "own", a.id, 0, at, text.trim().to_string(), if ok { 0.08 } else { 0.35 });
        }
    }
    common::wake(ctx, a.id);
}

/// A mark slot (above behavior node ids, below the evaluator's reserved marks) per failure kind.
fn failure_mark(label: &str, why: &str) -> u16 {
    let mut h: u32 = 2166136261;
    for b in label.bytes().chain(why.bytes()) {
        h = (h ^ b as u32).wrapping_mul(16777619);
    }
    0xE000 + (h % 0x1000) as u16
}

fn finish(ctx: &ReducerContext, a: Activity, ok: bool, why: &str, now: u64) {
    ctx.db.activity().id().delete(a.id);
    if a.skill == "sleep" || a.skill == "rest" {
        refresh_rates(ctx, a.id);
    }
    if let Some(mut k) = ctx.db.clock().id().find(0) {
        k.completions += 1;
        ctx.db.clock().id().update(k);
    }
    report(ctx, &a, ok, why, now);
}

/// Advance an activity that is due (timer) or whose approach arrived.
pub fn progress(ctx: &ReducerContext, a: Activity, now: u64) {
    if ctx.db.character().id().find(a.id).map_or(true, |c| !c.alive) {
        ctx.db.activity().id().delete(a.id);
        return;
    }
    if a.phase == 1 {
        return complete(ctx, a, now);
    }
    let here = ctx.db.body().id().find(a.id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let moving = ctx.db.body().id().find(a.id).map_or(false, |b| b.next_ms != IDLE);
    match a.skill.as_str() {
        "goto" | "wander" | "flee" => {
            if !moving {
                finish(ctx, a, true, "", now);
            }
            return;
        }
        "follow" => {
            if now.saturating_sub(a.started_ms) > 12_000 {
                motion::stop(ctx, a.id, now);
                return finish(ctx, a, true, "", now);
            }
            let Some(tp) = target_pos(ctx, &a.target, now) else { return finish(ctx, a, false, "lost them", now) };
            let mut a = a;
            if dist(here, tp) > reach("follow") {
                let sp = speed(ctx, a.id, now);
                if motion::start_move(ctx, a.id, tp, sp, now).is_err() {
                    return finish(ctx, a, false, "cannot keep up", now);
                }
            } else {
                motion::stop(ctx, a.id, now);
            }
            a.ends_ms = now + CHASE_REPATH_MS;
            ctx.db.activity().id().update(a);
            return;
        }
        _ => {}
    }
    let Some(tp) = target_pos(ctx, &a.target, now) else { return finish(ctx, a, false, "it is gone", now) };
    if a.target.class == 3 && ctx.db.character().id().find(a.target.id as u32).map_or(true, |c| !c.alive) {
        motion::stop(ctx, a.id, now);
        return finish(ctx, a, false, "they are dead", now);
    }
    let r = reach(&a.skill);
    let d = dist(here, tp);
    if d <= r + 0.25 {
        let act = Activity { phase: 1, ..a.clone() };
        if let Err(why) = perform(ctx, act, now) {
            motion::stop(ctx, a.id, now);
            finish(ctx, a, false, &why, now);
        }
        return;
    }
    if a.target.class == 3 {
        // Chasing: re-path toward where the target is now, if still perceivable.
        let w = common::world(ctx);
        if d > common::sight(&w, now) * 1.4 {
            motion::stop(ctx, a.id, now);
            return finish(ctx, a, false, "lost sight of them", now);
        }
        let sp = speed(ctx, a.id, now);
        if motion::start_move(ctx, a.id, tp, sp, now).is_err() {
            return finish(ctx, a, false, "cannot reach them", now);
        }
        let mut a = a;
        a.ends_ms = now + CHASE_REPATH_MS;
        ctx.db.activity().id().update(a);
        return;
    }
    if !moving {
        if d <= r + 1.2 {
            let act = Activity { phase: 1, ..a.clone() };
            if let Err(why) = perform(ctx, act, now) {
                finish(ctx, a, false, &why, now);
            }
        } else {
            finish(ctx, a, false, "could not get there", now);
        }
    }
}

fn complete(ctx: &ReducerContext, a: Activity, now: u64) {
    let sc = common::scripts(ctx);
    let sctx = skill_ctx(ctx, a.id, &a, now);
    // Targets can change or leave while the action runs.
    if a.target.class == 3 && sctx.target.dist > reach(&a.skill) + 1.0 {
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
    match apply(ctx, &a, effects, now) {
        Ok(summary) => finish(ctx, a, true, &summary, now),
        Err(why) => finish(ctx, a, false, &why, now),
    }
}

fn apply(ctx: &ReducerContext, a: &Activity, effects: Vec<Effect>, now: u64) -> Result<String, String> {
    let me = a.id;
    let at = ctx.db.body().id().find(me).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let my_name = common::name_of(ctx, me);
    let mut notes = Vec::new();
    for e in effects {
        match e {
            Effect::Add { item, qty } => {
                if catalog::item(&item).is_none() {
                    return Err(format!("unknown item {item}"));
                }
                common::inv_add(ctx, me as u64, &item, qty);
                notes.push(format!("+{qty} {item}"));
            }
            Effect::Remove { item, qty } => common::inv_remove(ctx, me as u64, &item, qty)?,
            Effect::Harvest { qty } => {
                let mut n = ctx.db.resource_node().id().find(a.target.id).ok_or("resource gone")?;
                let have = common::amount_now(&n, now);
                if have < qty {
                    return Err(format!("the {} is depleted", n.kind));
                }
                n.amount = have - qty;
                n.at_ms = now;
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
            Effect::Damage { amount } => {
                let victim = a.target.id as u32;
                damage(ctx, me, victim, amount, now);
                notes.push(format!("hit for {amount:.0}"));
            }
            Effect::Give { item, qty } => {
                let to = a.target.id as u32;
                common::inv_remove(ctx, me as u64, &item, qty)?;
                common::inv_add(ctx, to as u64, &item, qty);
                let to_name = common::name_of(ctx, to);
                common::chronicle(ctx, now, "give", me, to, at, format!("{my_name} gave {qty} {item} to {to_name}"));
                if let Some(c) = ctx.db.character().id().find(to) {
                    percept(ctx, &c, now, "gift", me, to, at, format!("{my_name} gave you {qty} {item}"), 0.8);
                }
                witnessed(ctx, now, at, "gift", me, to, &format!("{{a}} gave {qty} {item} to {{b}}"), 0.35, &[me, to]);
                notes.push(format!("gave {qty} {item} to {to_name}"));
            }
            Effect::Store { item, qty } => {
                common::inv_remove(ctx, me as u64, &item, qty)?;
                common::inv_add(ctx, STRUCTURE_BIT | a.target.id, &item, qty);
                notes.push(format!("stored {qty} {item}"));
            }
            Effect::Take { item, qty } => {
                common::inv_remove(ctx, STRUCTURE_BIT | a.target.id, &item, qty)?;
                common::inv_add(ctx, me as u64, &item, qty);
                notes.push(format!("took {qty} {item}"));
                if let Some(s) = ctx.db.structure().id().find(a.target.id) {
                    if s.owner != 0 && s.owner != me {
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
            Effect::Build { kind } => {
                if !catalog::STRUCTURES.contains(&kind.as_str()) {
                    return Err(format!("cannot build {kind}"));
                }
                let s = ctx.db.structure().insert(Structure { id: 0, kind: kind.clone(), x: at.0, y: at.1, chunk: chunk_of(at.0, at.1), owner: me, built_ms: now });
                common::chronicle(ctx, now, "build", me, 0, at, format!("{my_name} built a {kind}"));
                witnessed(ctx, now, at, "built", me, 0, &format!("{{a}} built a {kind} at ({:.0},{:.0})", at.0, at.1), 0.4, &[me]);
                notes.push(format!("built {kind} #{}", s.id));
            }
        }
    }
    Ok(notes.join(", "))
}

const OFFER_MS: u64 = 120_000;

/// Offer to start a family, or accept a standing offer from the target.
fn bond(ctx: &ReducerContext, me: u32, other: u32, at: (f32, f32), now: u64) -> Result<String, String> {
    let my_name = common::name_of(ctx, me);
    let other_name = common::name_of(ctx, other);
    let busy = |id: u32| ctx.db.expecting().iter().any(|e| e.a == id || e.b == id);
    if busy(me) || busy(other) {
        return Err("a child is already on the way".into());
    }
    let accepted = ctx.db.bond_offer().from().filter(other).find(|o| o.to == me && now.saturating_sub(o.at_ms) <= OFFER_MS);
    if let Some(o) = accepted {
        ctx.db.bond_offer().id().delete(o.id);
        for mine in ctx.db.bond_offer().from().filter(me).map(|o| o.id).collect::<Vec<_>>() {
            ctx.db.bond_offer().id().delete(mine);
        }
        let w = common::world(ctx);
        ctx.db.expecting().insert(Expecting { id: 0, a: other, b: me, due_ms: now + w.day_ms });
        common::chronicle(ctx, now, "family", other, me, at, format!("{other_name} and {my_name} are expecting a child"));
        for (who, partner) in [(me, &other_name), (other, &my_name)] {
            if let Some(c) = ctx.db.character().id().find(who) {
                percept(ctx, &c, now, "family", who, 0, at, format!("You and {partner} are expecting a child. It will be born in about a day."), 1.0);
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
        percept(ctx, &c, now, "family", me, other, at, format!("{my_name} wants to start a family with you (you would both have to choose it within two minutes)."), 0.9);
        if c.ai {
            perceive::request_deliberation(ctx, other, &format!("{my_name} asked to start a family with you."), now);
        }
    }
    Ok(format!("asked {other_name} to start a family"))
}

pub fn damage(ctx: &ReducerContext, attacker: u32, victim: u32, amount: f32, now: u64) {
    let Some(mut v) = ctx.db.vitals().id().find(victim) else { return };
    let Some(vc) = ctx.db.character().id().find(victim) else { return };
    if !vc.alive {
        return;
    }
    let first_blow = now.saturating_sub(v.hurt_ms) > 30_000 || v.hurt_by != attacker;
    common::settle(&mut v, now);
    v.hp = (v.hp - amount).max(0.0);
    v.hurt_ms = now;
    v.hurt_by = attacker;
    v.rate_key = 0;
    let dead = v.hp <= 0.0;
    ctx.db.vitals().id().update(v);
    let at = ctx.db.body().id().find(victim).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    let an = common::display(ctx, attacker);
    let vn = common::display(ctx, victim);
    common::wake(ctx, victim);
    let label = common::label_for(ctx, &vc, attacker);
    percept(ctx, &vc, now, "attacked", attacker, victim, at, format!("{label} attacked you ({amount:.0} damage)"), 1.0);
    if first_blow {
        if vc.kind == "person" || ctx.db.character().id().find(attacker).map_or(false, |c| c.kind == "person") {
            common::chronicle(ctx, now, "attack", attacker, victim, at, format!("{an} attacked {vn}"));
        }
        witnessed(ctx, now, at, "fight", attacker, victim, "{a} attacked {b}", 0.7, &[attacker, victim]);
        if vc.ai {
            perceive::request_deliberation(ctx, victim, &format!("{label} is attacking you!"), now);
        }
    }
    if dead {
        let meat = common::scripts(ctx).num_of("carcass_meat", &vc.kind, 0.0) as u32;
        if meat > 0 {
            common::inv_add(ctx, attacker as u64, "meat", meat);
        }
        die(ctx, victim, &format!("killed by {an}"), now, attacker);
    }
}

pub fn die(ctx: &ReducerContext, id: u32, cause: &str, now: u64, killer: u32) {
    let Some(mut c) = ctx.db.character().id().find(id) else { return };
    if !c.alive {
        return;
    }
    let at = ctx.db.body().id().find(id).map(|b| pos(&b, now)).unwrap_or((c.home_x, c.home_y));
    c.alive = false;
    c.died_ms = now;
    c.cause = cause.into();
    let name = c.name.clone();
    let kind = c.kind.clone();
    ctx.db.character().id().update(c);
    let items = common::inv_list(ctx, id as u64);
    for r in ctx.db.inventory().owner().filter(id as u64).collect::<Vec<_>>() {
        ctx.db.inventory().id().delete(r.id);
    }
    if kind == "person" {
        let s = ctx.db.structure().insert(Structure { id: 0, kind: "remains".into(), x: at.0, y: at.1, chunk: chunk_of(at.0, at.1), owner: id, built_ms: now });
        for (item, q) in items {
            common::inv_add(ctx, STRUCTURE_BIT | s.id, &item, q);
        }
        common::chronicle(ctx, now, "death", id, killer, at, format!("{name} died ({cause})"));
    }
    ctx.db.body().id().delete(id);
    ctx.db.activity().id().delete(id);
    ctx.db.mind_state().id().delete(id);
    ctx.db.vitals().id().delete(id);
    ctx.db.wake().id().delete(id);
    ctx.db.deliberation().actor().delete(id);
    let text = if killer != 0 { "{a} was killed by {b}".to_string() } else { format!("{{a}} died ({cause})") };
    witnessed(ctx, now, at, "death", id, killer, &text, if kind == "person" { 1.0 } else { 0.5 }, &[id]);
}
