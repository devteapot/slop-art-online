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
    let laws = common::laws(ctx);
    for (s, d) in common::structures_near(ctx, at, laws.fire_warmth.max(laws.shelter_warmth)) {
        if s.kind == "campfire" && d <= laws.fire_warmth {
            near_fire = true;
        }
        if s.kind == "shelter" && d <= laws.shelter_warmth {
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
        knows: common::knows(ctx, id),
    }
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
                f.knows = common::knows(ctx, c.id);
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
    let roll: f32 = ctx.rng().gen_range(0.0..1.0);
    SkillCtx {
        actor,
        target: target_facts(ctx, &a.target, from, now),
        item: a.item.clone(),
        qty: a.qty,
        night: living_rules::is_night(hour),
        hour,
        season: common::season(ctx, now).into(),
        text: a.text.clone(),
        topic: a.topic.clone(),
        roll,
    }
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
        4 | 5 => Some((t.x, t.y)),
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
#[allow(clippy::too_many_arguments)]
pub fn begin(ctx: &ReducerContext, id: u32, node: u16, revision: u32, skill: &str, target: Resolved, item: &str, qty: u32, text: &str, topic: &str, want: (&str, u32), now: u64) -> Result<(), String> {
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
        "dodge" => {
            // Dash sideways/away from whatever is coming, else backwards.
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
                let p = (here.0 + ang.cos() * 2.4, here.1 + ang.sin() * 2.4);
                if map.at(p.0, p.1).walkable() {
                    pick = Some(p);
                    break;
                }
            }
            target = Resolved::point(pick.ok_or("no room to dodge")?);
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
        "take" if item == "food" && target.class == 2 => {
            item = common::best_food(ctx, STRUCTURE_BIT | target.id).ok_or("no food in there")?;
        }
        // Reading without a target means a tablet you carry (one you have not read first).
        "read" if target.class == 0 => {
            let mine: Vec<Artifact> = ctx.db.artifact().holder().filter(id as u64).collect();
            let unread = mine.iter().find(|a| ctx.db.familiar().by_actor_thing().filter((id, FAM_ARTIFACT | a.id)).next().is_none());
            let pick = unread.or(mine.first()).ok_or("you carry nothing to read")?;
            target = Resolved { class: 5, id: pick.id, at: here, kind: "tablet".into(), name: pick.author_name.clone() };
        }
        _ => {}
    }
    let r = reach(skill);
    let moving_skill = matches!(skill, "goto" | "wander" | "flee" | "follow" | "dodge");
    let needs_approach = target.class != 0 && target.class != 5 && (moving_skill || dist(here, target.at) > r);
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
        text: text.chars().take(400).collect(),
        topic: topic.to_string(),
        want: want.0.to_string(),
        want_qty: want.1,
        victim: if matches!(skill, "attack" | "throw") && target.class == 3 { target.id as u32 } else { 0 },
    };
    if needs_approach && !(skill == "follow" && dist(here, target.at) <= r) {
        let sp = speed(ctx, id, now);
        let sp = match skill {
            "flee" => sp * 1.15,
            "dodge" => 9.0,
            _ => sp,
        };
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
    if act.victim != 0 {
        engage(ctx, id, now);
        engage(ctx, act.victim, now);
        common::wake(ctx, act.victim);
    }
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
    let repeat = !ok && ctx.db.mind_state().id().find(a.id).map_or(false, |st| st.marks.iter().any(|m| m.node == failure_mark(&a.label, why) && (now.saturating_sub(m.at_ms) as f32) < common::laws(ctx).repeat_failure_s * 1000.0));
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
        "goto" | "wander" | "flee" | "dodge" => {
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
        if d > common::sight(ctx, &w, now) * 1.4 {
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
                // A melee blow lands only on someone still within reach when the windup ends:
                // stepping back or running during a telegraphed swing makes it miss.
                if a.skill == "attack" {
                    let p = |id: u32| ctx.db.body().id().find(id).map(|b| pos(&b, now));
                    if let (Some(pa), Some(pv)) = (p(me), p(victim)) {
                        let kind = ctx.db.character().id().find(me).map(|c| c.kind).unwrap_or_default();
                        if dist(pa, pv) > reach("attack") + common::scripts(ctx).num_of("lunge", &kind, 0.6) as f32 {
                            missed(ctx, me, victim, pv, now);
                            notes.push("missed".into());
                            continue;
                        }
                    }
                }
                damage(ctx, me, victim, amount, now);
                notes.push(format!("hit for {amount:.0}"));
            }
            Effect::Give { item, qty } => {
                let to = a.target.id as u32;
                common::inv_remove(ctx, me as u64, &item, qty)?;
                common::inv_add(ctx, to as u64, &item, qty);
                move_tablets(ctx, &item, me as u64, to as u64, qty);
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
                    if s.owner != 0 && s.owner != me && !same_people(s.owner, me) {
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
                    percept(ctx, &c, now, "learned", me, learner, at, format!("{my_name} taught you {technique} ({}).", technique_help(&technique)), 0.85);
                }
                common::chronicle(ctx, now, "learn", me, learner, at, format!("{my_name} taught {ln} {technique}"));
                witnessed(ctx, now, at, "taught", me, learner, &format!("{{a}} taught {{b}} {technique}"), 0.4, &[me, learner]);
                notes.push(format!("taught {ln} {technique}"));
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
            Effect::Write => {
                let w = common::world(ctx);
                let _ = w;
                let holder = if a.item == "sign" {
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
                let text = format!("{my_name} offers you {give_qty} {} for {} {}.", a.item, a.want_qty.max(1), a.want);
                if let Some(c) = ctx.db.character().id().find(to) {
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
                    percept(ctx, &c, now, "trade", me, from, at, format!("{my_name} accepted your trade: {deal}."), 0.8);
                }
                witnessed(ctx, now, at, "trade", from, me, &format!("{{a}} and {{b}} traded {deal}"), 0.4, &[me, from]);
                notes.push(format!("traded with {fname}: {deal}"));
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
                    percept(ctx, &c, now, "community", me, other, at, format!("{my_name} asks to join {cname}."), 0.85);
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
                let cname = ctx.db.community().id().find(mine.community).map(|c| c.name).unwrap_or_default();
                let an = common::name_of(ctx, asker);
                common::chronicle(ctx, now, "community", asker, me, at, format!("{an} joined {cname}, welcomed by {my_name}"));
                if let Some(c) = ctx.db.character().id().find(asker) {
                    percept(ctx, &c, now, "community", me, asker, at, format!("{my_name} welcomed you into {cname}."), 0.9);
                }
                witnessed(ctx, now, at, "community", asker, me, &format!("{{a}} joined {cname}, welcomed by {{b}}"), 0.5, &[me, asker]);
                notes.push(format!("welcomed {an} into {cname}"));
            }
            Effect::Leave => {
                let m = ctx.db.membership().member().find(me).ok_or("you belong to no community")?;
                let cname = ctx.db.community().id().find(m.community).map(|c| c.name).unwrap_or_default();
                ctx.db.membership().id().delete(m.id);
                common::chronicle(ctx, now, "community", me, 0, at, format!("{my_name} left {cname}"));
                witnessed(ctx, now, at, "community", me, 0, &format!("{{a}} left {cname}"), 0.6, &[me]);
                notes.push(format!("left {cname}"));
            }
            Effect::Plant => {
                let sc = common::scripts(ctx);
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
    let window = (common::laws(ctx).bond_window_s * 1000.0) as u64;
    let accepted = ctx.db.bond_offer().from().filter(other).find(|o| o.to == me && now.saturating_sub(o.at_ms) <= window);
    if let Some(o) = accepted {
        ctx.db.bond_offer().id().delete(o.id);
        for mine in ctx.db.bond_offer().from().filter(me).map(|o| o.id).collect::<Vec<_>>() {
            ctx.db.bond_offer().id().delete(mine);
        }
        let w = common::world(ctx);
        let gestation = (common::laws(ctx).gestation_days * w.day_ms as f32) as u64;
        ctx.db.expecting().insert(Expecting { id: 0, a: other, b: me, due_ms: now + gestation });
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

/// Put a creature on combat cadence for the next few seconds.
pub fn engage(ctx: &ReducerContext, id: u32, now: u64) {
    if let Some(mut st) = ctx.db.mind_state().id().find(id) {
        if st.fast_until < now + 6_000 {
            st.fast_until = now + 8_000;
            ctx.db.mind_state().id().update(st);
        }
    }
}

/// While people fight, their minds get a short account of the exchange every few seconds
/// (only when no thought is pending and the last one is at least 7 s old), so tactics can be
/// patched mid-fight from what actually happened rather than decided once at the first blow.
pub fn fight_report(ctx: &ReducerContext, id: u32, other: u32, now: u64) {
    let Some(c) = ctx.db.character().id().find(id) else { return };
    if !c.ai || !c.alive || c.kind != "person" || ctx.db.deliberation().actor().find(id).is_some() {
        return;
    }
    if ctx.db.mind_state().id().find(id).map_or(true, |s| now.saturating_sub(s.deliberated_ms) < 7_000) {
        return;
    }
    let (mut hit, mut blocked, mut dodged, mut evaded, mut they_blocked, mut they_dodged, mut whiffed) = (0, 0, 0, 0, 0, 0, 0);
    for e in ctx.db.experience().observer().filter(id) {
        if now.saturating_sub(e.at_ms) > 20_000 || (e.kind != "attacked" && e.kind != "combat") {
            continue;
        }
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
    let label = common::label_for(ctx, &c, other);
    let hp = ctx.db.vitals().id().find(id).map(|v| common::needs(&v, now).hp).unwrap_or(0.0);
    let their_hp = ctx.db.vitals().id().find(other).map(|v| (common::needs(&v, now).hp / v.max_hp * 100.0).round()).unwrap_or(0.0);
    let text = format!(
        "The fight with {label} goes on (your health {hp:.0}, theirs looks about {their_hp:.0}%). In the last 20 s: you were hit {hit}×, blocked {blocked}, dodged {dodged}, stepped out of reach {evaded}; they blocked {they_blocked} and dodged {they_dodged} of your blows, {whiffed} of yours found only air. \
If your way of fighting isn't working, patch your \"combat\" branch now; otherwise keep it."
    );
    perceive::request_deliberation(ctx, id, &text, now);
}

/// A blow that found only air: both sides perceive it, and the fight stays engaged.
fn missed(ctx: &ReducerContext, attacker: u32, victim: u32, at_v: (f32, f32), now: u64) {
    engage(ctx, attacker, now);
    engage(ctx, victim, now);
    if let Some(mut k) = ctx.db.clock().id().find(0) {
        k.missed += 1;
        ctx.db.clock().id().update(k);
    }
    if let Some(vc) = ctx.db.character().id().find(victim) {
        percept(ctx, &vc, now, "combat", attacker, victim, at_v, format!("{}'s blow missed: you were out of reach.", common::label_for(ctx, &vc, attacker)), 0.6);
        common::wake(ctx, victim);
    }
    if let Some(ac) = ctx.db.character().id().find(attacker) {
        percept(ctx, &ac, now, "combat", victim, attacker, at_v, format!("Your blow missed: {} was out of reach.", common::label_for(ctx, &ac, victim)), 0.6);
    }
    fight_report(ctx, victim, attacker, now);
    fight_report(ctx, attacker, victim, now);
}

pub fn damage(ctx: &ReducerContext, attacker: u32, victim: u32, amount: f32, now: u64) {
    let Some(mut v) = ctx.db.vitals().id().find(victim) else { return };
    let Some(vc) = ctx.db.character().id().find(victim) else { return };
    if !vc.alive {
        return;
    }
    engage(ctx, attacker, now);
    engage(ctx, victim, now);
    // Defense in progress: a dodge makes the blow miss, a raised guard takes most of it.
    let defense = ctx.db.activity().id().find(victim).map(|a| a.skill).unwrap_or_default();
    let at_v = ctx.db.body().id().find(victim).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
    if let Some(mut k) = ctx.db.clock().id().find(0) {
        match defense.as_str() {
            "dodge" => k.dodged += 1,
            "block" => k.blocked += 1,
            _ => k.hits += 1,
        }
        ctx.db.clock().id().update(k);
    }
    if defense == "dodge" {
        let attacker_c = ctx.db.character().id().find(attacker);
        percept(ctx, &vc, now, "combat", attacker, victim, at_v, format!("You dodged {}'s attack.", common::label_for(ctx, &vc, attacker)), 0.6);
        if let Some(ac) = attacker_c {
            percept(ctx, &ac, now, "combat", victim, attacker, at_v, format!("{} dodged your attack.", common::label_for(ctx, &ac, victim)), 0.6);
        }
        common::wake(ctx, victim);
        fight_report(ctx, victim, attacker, now);
        fight_report(ctx, attacker, victim, now);
        return;
    }
    let amount = if defense == "block" {
        if let Some(ac) = ctx.db.character().id().find(attacker) {
            percept(ctx, &ac, now, "combat", victim, attacker, at_v, format!("{} blocked your blow.", common::label_for(ctx, &ac, victim)), 0.5);
        }
        percept(ctx, &vc, now, "combat", attacker, victim, at_v, format!("You blocked {}'s blow.", common::label_for(ctx, &vc, attacker)), 0.5);
        amount * 0.25
    } else {
        amount
    };
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
    } else if !dead {
        fight_report(ctx, victim, attacker, now);
        fight_report(ctx, attacker, victim, now);
    }
    if dead {
        let meat = common::scripts(ctx).num_of("carcass_meat", &vc.kind, 0.0) as u32;
        let hide = common::scripts(ctx).num_of("carcass_hide", &vc.kind, 0.0) as u32;
        if hide > 0 {
            common::inv_add(ctx, attacker as u64, "hide", hide);
        }
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
    if let Some(m) = ctx.db.membership().member().find(id) {
        ctx.db.membership().id().delete(m.id);
    }
    // What only this person knew how to do is gone unless they taught or wrote it down.
    for k in ctx.db.know_how().actor().filter(id).map(|k| k.id).collect::<Vec<_>>() {
        ctx.db.know_how().id().delete(k);
    }
    if kind == "person" {
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
    common::invalidate_bodies();
    ctx.db.activity().id().delete(id);
    ctx.db.mind_state().id().delete(id);
    ctx.db.vitals().id().delete(id);
    ctx.db.wake().id().delete(id);
    ctx.db.deliberation().actor().delete(id);
    let text = if killer != 0 { "{a} was killed by {b}".to_string() } else { format!("{{a}} died ({cause})") };
    witnessed(ctx, now, at, "death", id, killer, &text, if kind == "person" { 1.0 } else { 0.5 }, &[id]);
}
