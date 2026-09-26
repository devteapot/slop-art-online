//! Deliberate acts (see `living_rules::acts`): one-off `do` nodes a mind (deliberation or
//! conversation turn) or a player decides on, carried out once each, in order, through the
//! same skill rules as graph leaves (`act::begin` with the `ACT` node). While an act runs the
//! behavior graph is still evaluated, but only its reflexes (flee, dodge, block, attack,
//! throw) may take the body back; its other work waits until the act is done. The outcome,
//! success or failure with the reason, comes back to the actor as an experience.

use crate::act::{self, ACT};
use crate::perceive::{self, percept};
use crate::tables::*;
use crate::{brain, common};
use living_rules::acts as rules;
use living_rules::graph;
use spacetimedb::{ReducerContext, Table};

fn feedback(ctx: &ReducerContext, actor: u32, now: u64, text: String, salience: f32, think: bool) {
    let Some(c) = ctx.db.character().id().find(actor) else { return };
    let at = ctx.db.body().id().find(actor).map(|b| common::pos(&b, now)).unwrap_or((0.0, 0.0));
    percept(ctx, &c, now, "act", actor, 0, at, text.clone(), salience);
    if think {
        perceive::request_deliberation(ctx, actor, &text, now);
    }
}

/// Queue acts for `actor`; each is validated for the body first (a rejected one is told back).
/// `replace` drops what was waiting and stops the act in progress (a player's new command).
pub fn submit(ctx: &ReducerContext, actor: u32, acts: &[String], source: &str, replace: bool, now: u64) -> Vec<String> {
    let kind = ctx.db.character().id().find(actor).map(|c| c.kind).unwrap_or_default();
    let sp = common::species(&kind);
    if replace {
        ctx.db.act_queue().actor().delete(actor);
        if let Some(a) = ctx.db.activity().id().find(actor).filter(|a| a.node == ACT) {
            act::cancel(ctx, a, now, None);
        }
    }
    let mut notes = Vec::new();
    for raw in acts.iter().take(rules::MAX_QUEUED) {
        let parsed = serde_json::from_str::<serde_json::Value>(raw).map_err(|e| format!("not JSON: {e}")).and_then(|v| rules::parse(v, sp.as_ref()));
        let a = match parsed {
            Ok(a) => a,
            Err(why) => {
                feedback(ctx, actor, now, format!("You could not act on what you decided ({}): {why}", raw.chars().take(120).collect::<String>()), 0.4, false);
                notes.push(format!("rejected: {why}"));
                continue;
            }
        };
        if ctx.db.act_queue().actor().filter(actor).count() >= rules::MAX_QUEUED {
            feedback(ctx, actor, now, format!("You have too much in mind already to also {}.", graph::describe(&graph::Node::Do(a.clone()))), 0.3, false);
            notes.push("queue full".into());
            continue;
        }
        notes.push(graph::describe(&graph::Node::Do(a.clone())));
        ctx.db.act_queue().insert(PlannedAct { id: 0, actor, node: rules::to_json(&a), source: source.chars().take(32).collect(), at_ms: now });
    }
    next(ctx, actor, now);
    notes
}

/// Start the next waiting act unless one is in progress.
pub fn next(ctx: &ReducerContext, actor: u32, now: u64) {
    loop {
        if ctx.db.activity().id().find(actor).map_or(false, |a| a.node == ACT) {
            return;
        }
        if !ctx.db.character().id().find(actor).map_or(false, |c| c.alive) {
            ctx.db.act_queue().actor().delete(actor);
            return;
        }
        let Some(p) = ctx.db.act_queue().actor().filter(actor).min_by_key(|p| p.id) else { return };
        ctx.db.act_queue().id().delete(p.id);
        let Ok(a) = rules::from_json(&p.node) else { continue };
        let what = graph::describe(&graph::Node::Do(a.clone()));
        if now.saturating_sub(p.at_ms) > rules::QUEUE_MS {
            feedback(ctx, actor, now, format!("You never got to {what}; the moment passed."), 0.3, false);
            continue;
        }
        let target = match &a.target {
            Some(t) => match brain::resolve_for(ctx, actor, t, now) {
                Some(r) => r,
                None => {
                    feedback(ctx, actor, now, format!("What you had decided did not work out: {what}: no {} in sight.", graph::describe_target(t)), 0.5, true);
                    continue;
                }
            },
            None => act::Resolved::none(),
        };
        let revision = ctx.db.mind_state().id().find(actor).map(|s| s.revision).unwrap_or(0);
        let want = (a.want.clone().unwrap_or_default(), a.want_qty.unwrap_or(0));
        match act::begin(ctx, actor, ACT, revision, &a.skill, target, a.item.as_deref().unwrap_or(""), a.qty.unwrap_or(0), a.text.as_deref().unwrap_or(""), a.topic.as_deref().unwrap_or(""), (&want.0, want.1), now) {
            Ok(()) => {
                common::wake(ctx, actor);
                return;
            }
            Err(why) => feedback(ctx, actor, now, format!("What you had decided did not work out: {what}: {why}."), 0.5, true),
        }
    }
}

/// How an act went, told to the actor (called when an `ACT` activity ends).
pub fn outcome(ctx: &ReducerContext, a: &Activity, ok: bool, why: &str, now: u64) {
    let text = if ok {
        let why = why.trim();
        format!("You did what you had decided: {}{}", a.label, if why.is_empty() { ".".to_string() } else { format!(" ({why}).") })
    } else {
        format!("What you had decided did not work out: {}: {why}.", a.label)
    };
    feedback(ctx, a.id, now, text, if ok { 0.35 } else { 0.55 }, !ok);
}

/// A reflex takes the body back: the act in progress stops, and what was waiting is dropped
/// (the moment for it has changed).
pub fn interrupt(ctx: &ReducerContext, a: Activity, reflex: &str, now: u64) {
    let id = a.id;
    let dropped: Vec<String> = ctx.db.act_queue().actor().filter(id).filter_map(|p| rules::from_json(&p.node).ok()).map(|x| graph::describe(&graph::Node::Do(x))).collect();
    ctx.db.act_queue().actor().delete(id);
    act::cancel(ctx, a, now, Some(&format!("you broke off to {reflex}")));
    if !dropped.is_empty() {
        feedback(ctx, id, now, format!("You set aside what you still meant to do: {}.", dropped.join("; ")), 0.3, false);
    }
}

/// The act in progress has been approaching its target for too long.
pub fn overdue(a: &Activity, now: u64) -> bool {
    a.node == ACT && a.phase == 0 && now.saturating_sub(a.started_ms) > rules::APPROACH_MS
}
