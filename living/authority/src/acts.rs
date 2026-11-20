//! Deliberate acts (see `living_rules::acts`): one-off `do` nodes a mind (deliberation or
//! conversation turn) or a player decides on, carried out once each, in order, through the
//! same skill rules as graph leaves (`act::begin` with the `ACT` node). While an act runs the
//! behavior graph is still evaluated, but only its reflexes (flee, dodge, block, attack,
//! throw) may take the body back; its other work waits until the act is done. The outcome,
//! success or failure with the reason, comes back to the actor as an experience.

use crate::act::{self, ACT};
use crate::outcomes::{self, Told};
use living_rules::outcome::{act as code, kind};
use crate::perceive::{self, percept};
use crate::tables::*;
use crate::{brain, common};
use living_rules::acts as rules;
use living_rules::graph;
use spacetimedb::{ReducerContext, Table};

/// Tell the actor how an act went (an `act` line), with its outcome row for a person's client.
fn feedback(ctx: &ReducerContext, actor: u32, now: u64, text: String, salience: f32, think: bool, told: Told) {
    let Some(c) = ctx.db.character().id().find(actor) else { return };
    let at = ctx.db.body().id().find(actor).map(|b| common::pos(&b, now)).unwrap_or((0.0, 0.0));
    if let Some(line) = percept(ctx, &c, now, "act", actor, 0, at, text.clone(), salience) {
        outcomes::write(ctx, actor, line, now, &told, false);
    }
    if think {
        perceive::request_deliberation(ctx, actor, &text, now);
    }
}

/// Queue acts for `actor`; each is validated for the body first (a rejected one is told back).
/// `replace` drops what was waiting and stops the act in progress (a player's new command).
pub fn submit(ctx: &ReducerContext, actor: u32, acts: &[String], source: &str, replace: bool, now: u64) {
    submit_inner(ctx, actor, acts, source, replace, now, false);
}

/// Return ordered, synchronous refusals for this batch. Later activity outcomes remain
/// experiences, since a queued interaction may start or fail well after this turn ends.
pub fn submit_checked(ctx: &ReducerContext, actor: u32, acts: &[String], source: &str, now: u64) -> Vec<Option<String>> {
    submit_inner(ctx, actor, acts, source, false, now, true)
}

fn submit_inner(ctx: &ReducerContext, actor: u32, acts: &[String], source: &str, replace: bool, now: u64, checked: bool) -> Vec<Option<String>> {
    let kind = ctx.db.character().id().find(actor).map(|c| c.kind).unwrap_or_default();
    let sp = common::species(&kind);
    if replace {
        ctx.db.act_queue().actor().delete(actor);
        // A committed move under way runs its course (`combat::committed`).
        if let Some(a) = ctx.db.activity().id().find(actor).filter(|a| a.node == ACT && !crate::combat::committed(&common::scripts(ctx), a)) {
            act::cancel(ctx, a, now, None);
        }
    }
    let mut results = Vec::new();
    for raw in acts.iter().take(rules::MAX_QUEUED) {
        let parsed = serde_json::from_str::<serde_json::Value>(raw).map_err(|e| format!("not JSON: {e}"));
        if let Ok(v) = &parsed {
            if !replace && v["do"] == "gaze" {
                let band = match v["band"].as_str() {
                    Some("middle") => Ok(living_rules::sight::GazeBand::Middle),
                    Some("far") => Ok(living_rules::sight::GazeBand::Far),
                    Some("near") => Ok(living_rules::sight::GazeBand::Near),
                    _ => Err("gaze band must be middle, far or near".to_owned()),
                };
                let refusal = band.and_then(|band| crate::attention::set(ctx, actor, band, now)).err();
                if let Some(why) = refusal.as_deref() {
                    let told = Told { kind: kind::ACT, ok: false, skill: "gaze", code: code::REFUSED, what: "change gaze", why, other: 0 };
                    feedback(ctx, actor, now, format!("You could not change gaze: {why}."), 0.4, false, told);
                }
                results.push((None, refusal));
                continue;
            }
        }
        let parsed = parsed.and_then(|v| rules::parse(v, sp.as_ref(), common::scripts(ctx).shapes()));
        let a = match parsed {
            Ok(a) => a,
            Err(why) => {
                let what: String = raw.chars().take(120).collect();
                let skill = serde_json::from_str::<serde_json::Value>(raw).ok().and_then(|v| v["do"].as_str().or_else(|| v["do"]["skill"].as_str()).or_else(|| v["skill"].as_str()).map(String::from)).unwrap_or_default();
                let told = Told { kind: kind::ACT, ok: false, skill: &skill, code: code::UNREADABLE, what: &what, why: &why, other: 0 };
                feedback(ctx, actor, now, format!("You could not act on what you decided ({what}): {why}"), 0.4, false, told);
                results.push((None, Some(why)));
                continue;
            }
        };
        if ctx.db.act_queue().actor().filter(actor).count() >= rules::MAX_QUEUED {
            let what = graph::describe(&graph::Node::Do(a.clone()));
            let told = Told { kind: kind::ACT, ok: false, skill: &a.skill, code: code::BUSY, what: &what, why: "too much in mind already", other: 0 };
            feedback(ctx, actor, now, format!("You have too much in mind already to also {what}."), 0.3, false, told);
            results.push((None, Some("too much in mind already".into())));
            continue;
        }
        let queued = ctx.db.act_queue().insert(PlannedAct { id: 0, actor, node: rules::to_json(&a), source: source.chars().take(32).collect(), at_ms: now });
        crate::latency::nav(ctx, actor, "act_queued", queued.id, format_args!("{source} {}", a.skill));
        results.push((Some(queued.id), None));
    }
    if !checked {
        next(ctx, actor, now);
        return Vec::new();
    }
    next_reporting(ctx, actor, now, |id, why| {
        if let Some((_, refusal)) = results.iter_mut().find(|(queued, _)| *queued == Some(id)) {
            *refusal = Some(why.to_owned());
            true
        } else {
            false
        }
    });
    results.into_iter().map(|(_, refusal)| refusal.map(|why| refusal_with_names(ctx, &why))).collect()
}

fn refusal_with_names(ctx: &ReducerContext, why: &str) -> String {
    let scripts = common::scripts(ctx);
    let mut names = scripts.skills().iter()
        .filter(|s| rules::not_an_act(&s.name, scripts.shapes()).is_none())
        .map(|s| s.name.as_str()).collect::<Vec<_>>().join(", ");
    if scripts.gaze_enabled() {
        names.push_str(", gaze");
    }
    format!("{why}\nValid one-off act names: {names}.")
}

/// Start the next waiting act unless one is in progress.
pub fn next(ctx: &ReducerContext, actor: u32, now: u64) {
    next_reporting(ctx, actor, now, |_, _| false);
}

fn next_reporting(ctx: &ReducerContext, actor: u32, now: u64, mut report_refusal: impl FnMut(u64, &str) -> bool) {
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
            let told = Told { kind: kind::ACT, ok: false, skill: &a.skill, code: code::EXPIRED, what: &what, why: "the moment passed", other: 0 };
            feedback(ctx, actor, now, format!("You never got to {what}; the moment passed."), 0.3, false, told);
            continue;
        }
        let target = match &a.target {
            Some(t) => match brain::resolve_for(ctx, actor, t, now) {
                Some(r) => r,
                None => {
                    let why = format!("no {} in sight", graph::describe_target(t));
                    let told = Told { kind: kind::ACT, ok: false, skill: &a.skill, code: code::UNSEEN, what: &what, why: &why, other: 0 };
                    feedback(ctx, actor, now, format!("What you had decided did not work out: {what}: {why}."), 0.5, !report_refusal(p.id, &why), told);
                    continue;
                }
            },
            None => act::Resolved::none(),
        };
        let revision = ctx.db.mind_state().id().find(actor).map(|s| s.revision).unwrap_or(0);
        let want = (a.want.clone().unwrap_or_default(), a.want_qty.unwrap_or(0));
        match act::begin(ctx, actor, ACT, revision, &a.skill, target, a.item.as_deref().unwrap_or(""), a.qty.unwrap_or(0), a.text.as_deref().unwrap_or(""), a.topic.as_deref().unwrap_or(""), (&want.0, want.1), (a.offer.unwrap_or(0), a.record.unwrap_or(0)), a.run, a.spacing(), now) {
            Ok(()) => {
                crate::latency::nav(ctx, actor, "act_started", p.id, format_args!("{}", a.skill));
                common::wake(ctx, actor);
                return;
            }
            Err(why) => {
                let told = Told { kind: kind::ACT, ok: false, skill: &a.skill, code: act::refusal(), what: &what, why: &why, other: 0 };
                feedback(ctx, actor, now, format!("What you had decided did not work out: {what}: {why}."), 0.5, !report_refusal(p.id, &why), told)
            }
        }
    }
}

/// How an act went, told to the actor (called when an `ACT` activity ends); `code` says at
/// which point it was decided (`living_rules::outcome::act`).
pub fn outcome(ctx: &ReducerContext, a: &Activity, ok: bool, why: &str, now: u64, code: &'static str) {
    let text = if ok {
        let why = why.trim();
        format!("You did what you had decided: {}{}", a.label, if why.is_empty() { ".".to_string() } else { format!(" ({why}).") })
    } else if code == living_rules::outcome::act::MOVED {
        // Broken off by moving: the rules' sentence says it whole ("The wave stopped: you moved
        // off before it was done.").
        let mut c = why.trim().trim_end_matches('.').chars();
        c.next().map_or(String::new(), |f| f.to_uppercase().collect::<String>() + c.as_str() + ".")
    } else {
        format!("What you had decided did not work out: {}: {why}.", a.label)
    };
    let told = Told { kind: kind::ACT, ok, skill: &a.skill, code, what: &a.label, why: if ok { "" } else { why }, other: 0 };
    feedback(ctx, a.id, now, text, if ok { 0.35 } else { 0.55 }, !ok, told);
}

/// A reflex takes the body back: the act in progress stops, and what was waiting is dropped
/// (the moment for it has changed).
pub fn interrupt(ctx: &ReducerContext, a: Activity, reflex: &str, now: u64) {
    let id = a.id;
    let dropped: Vec<String> = ctx.db.act_queue().actor().filter(id).filter_map(|p| rules::from_json(&p.node).ok()).map(|x| graph::describe(&graph::Node::Do(x))).collect();
    ctx.db.act_queue().actor().delete(id);
    act::cancel(ctx, a, now, Some(&format!("you broke off to {reflex}")));
    if !dropped.is_empty() {
        let what = dropped.join("; ");
        let told = Told { kind: kind::ACT, ok: false, skill: "", code: code::SET_ASIDE, what: &what, why: reflex, other: 0 };
        feedback(ctx, id, now, format!("You set aside what you still meant to do: {what}."), 0.3, false, told);
    }
}

/// The act in progress has been approaching its target for too long. A walk to a place that is
/// still under way is not: its route can take many minutes, and steering ends it on arrival or
/// when the way is blocked. An approach to a creature, which can keep moving away, is.
pub fn overdue(ctx: &ReducerContext, a: &Activity, now: u64) -> bool {
    if a.node != ACT || a.phase != 0 || now.saturating_sub(a.started_ms) <= rules::APPROACH_MS {
        return false;
    }
    let walking_to_a_place = ctx.db.steer().id().find(a.id).is_some_and(|s| s.goal == crate::motion::GOAL_POINT) && ctx.db.body().id().find(a.id).is_some_and(|b| b.next_ms != crate::motion::IDLE);
    !walking_to_a_place
}
