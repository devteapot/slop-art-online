//! Perception: what witnesses experience, speech, and requests for the mind to deliberate.
//! Only characters within sight/hearing of an event receive a percept; the mind never
//! reads world tables for its characters' context.

use crate::tables::*;
use crate::common::{self, dist, direction, pos};
use serde_json::{json, Map as JMap, Value};
use spacetimedb::{ReducerContext, Table};

/// Experiences kept per character (older ones leave the hot window).
const WINDOW: usize = 400;

/// Write an experience row for `observer`; its id, or `None` when nobody would read it.
pub fn percept(ctx: &ReducerContext, observer: &Character, now: u64, kind: &str, subject: u32, object: u32, at: (f32, f32), text: String, salience: f32) -> Option<u64> {
    // Only minds and human players consume percepts. Infants have no mind yet to form
    // memories; a benchmark crowd's bodies (`common::instinct_only`) have no reader.
    if !observer.alive || observer.stage == 0 || common::instinct_only(ctx, observer) {
        return None;
    }
    let row = ctx.db.experience().insert(Experience {
        id: 0,
        observer: observer.id,
        controller: observer.controller,
        at_ms: now,
        kind: kind.into(),
        subject,
        object,
        x: at.0,
        y: at.1,
        text,
        salience,
    });
    common::count(|k| k.percepts += 1);
    // A player's line reaches its client at the character's next frame (`frame.rs`).
    if crate::combat::human(ctx, observer.id).is_some() {
        crate::frame::line(ctx, &row);
    }
    // Bound the per-character window (checked periodically, not on every insert).
    if row.id % 32 == 0 {
        let mut ids: Vec<u64> = ctx.db.experience().observer().filter(observer.id).map(|p| p.id).collect();
        if ids.len() > WINDOW {
            ids.sort_unstable();
            for id in &ids[..ids.len() - WINDOW] {
                ctx.db.experience().id().delete(*id);
                crate::speech::forget_line(ctx, *id);
            }
        }
    }
    if salience >= 0.6 {
        common::wake(ctx, observer.id);
    }
    Some(row.id)
}

/// People within `r` of `at` (excluding `exclude`).
pub fn people_near(ctx: &ReducerContext, at: (f32, f32), r: f32, now: u64, exclude: &[u32]) -> Vec<(Character, f32)> {
    common::creatures_near(ctx, at, r, now)
        .into_iter()
        .filter(|c| &*c.kind == "person" && !exclude.contains(&c.id))
        .filter_map(|c| ctx.db.character().id().find(c.id).map(|ch| (ch, c.dist)))
        .collect()
}

/// Minds (people and animals) and players within `r` of `at`.
pub fn minds_near(ctx: &ReducerContext, at: (f32, f32), r: f32, now: u64, exclude: &[u32]) -> Vec<(Character, f32)> {
    common::creatures_near(ctx, at, r, now)
        .into_iter()
        .filter(|c| !exclude.contains(&c.id))
        .filter_map(|c| ctx.db.character().id().find(c.id).map(|ch| (ch, c.dist)))
        .filter(|(ch, _)| !common::instinct_only(ctx, ch))
        .collect()
}

/// Everyone who can see `at` receives a percept: within their own sight, with a clear sight
/// line (`perception::in_sight`, the rule players' perceived sets use). `{a}` and `{b}` in
/// `template` become how each observer refers to `subject` and `object` (its projection's
/// label: the name when it knows it).
pub fn witnessed(ctx: &ReducerContext, now: u64, at: (f32, f32), kind: &str, subject: u32, object: u32, template: &str, salience: f32, exclude: &[u32]) {
    let w = common::world(ctx);
    let map = common::map(ctx);
    let r = crate::perception::widest_sight(ctx, &w, now);
    for (c, d) in minds_near(ctx, at, r, now, exclude) {
        let Some((eye, heading)) = ctx.db.body().id().find(c.id).map(|b| (pos(&b, now), common::facing_at(&b, now))) else { continue };
        if !crate::perception::in_sight(ctx, &map, c.id, eye, heading, subject, at, d, &w, now, false) {
            continue;
        }
        // How this onlooker refers to the two (each projected once; the template's first `{a}`
        // capitalized when it begins the sentence).
        let ids: Vec<u32> = if template.contains("{b}") { vec![subject, object] } else { vec![subject] };
        let mut named = crate::perception::labels(ctx, &c, &ids, now).into_iter();
        let a = named.next().unwrap_or_default();
        let b = named.next().unwrap_or_default();
        let text = rendered(template, &a, &b, object != 0 && c.id == object);
        // Animals notice people's and other species' affairs less keenly than their own kind's.
        let sal = if &*c.kind != "person" && !template.contains("{a}") { salience * 0.5 } else { salience };
        percept(ctx, &c, now, kind, subject, object, at, text, sal);
    }
}

/// A witnessed event's words for one onlooker: `{a}` and `{b}` become `a` and `b` (the first
/// `{a}` capitalized when it begins the sentence). The one it was done to reads it as done to
/// them: "was killed by you", "from your storage", not their own name in the third person.
fn rendered(template: &str, a: &str, b: &str, to_object: bool) -> String {
    let t = if to_object { template.replace("{b}'s", "your").replace("{b}", "you") } else { template.to_string() };
    let first = if t.starts_with("{a}") { common::capitalized(a) } else { a.to_string() };
    t.replacen("{a}", &first, 1).replace("{a}", a).replace("{b}", b)
}

/// A species signal: heard by every mind within the signal's range.
pub fn signal(ctx: &ReducerContext, from: u32, name: &str, now: u64) -> Result<String, String> {
    let me = ctx.db.character().id().find(from).ok_or("no body")?;
    let sp = common::species(&me.kind).ok_or("unknown species")?;
    let sig = sp.signals.get(name).ok_or_else(|| format!("a {} has no `{name}` signal", me.kind))?;
    let at = ctx.db.body().id().find(from).map(|b| pos(&b, now)).ok_or("no body")?;
    if name == "cry" && me.kind == "person" && me.stage == 0 && common::scripts(ctx).has("body_state") {
        return infant_cry(ctx, &me, at, sig.range, now);
    }
    // Calling the same call again within 45 s is still the same call, not news.
    if let Some(mut st) = ctx.db.mind_state().id().find(from) {
        let key = 0xD000 + (name.bytes().fold(7u32, |h, b| h.wrapping_mul(31) ^ b as u32) % 0x1000) as u16;
        if st.marks.iter().any(|m| m.node == key && now.saturating_sub(m.at_ms) < 45_000) {
            return Ok(format!("kept making {}", sig.sound));
        }
        st.marks.retain(|m| m.node != key);
        st.marks.push(Mark { node: key, at_ms: now });
        if st.marks.len() > 24 {
            st.marks.remove(0);
        }
        ctx.db.mind_state().id().update(st);
    }
    let heard = if sig.heard.is_empty() { format!("{} makes {}", me.name, sig.sound) } else { sig.heard.replace("{name}", &me.name) };
    // Who cares about the signaller: its parents, its siblings, anyone with feelings about it.
    let cares = |c: &Character| {
        me.parent_a == c.id
            || me.parent_b == c.id
            || (me.parent_a != 0 && (c.parent_a == me.parent_a || c.parent_b == me.parent_a))
            || ctx.db.relation().by_pair().filter((c.id, from)).next().is_some()
    };
    for (c, _) in minds_near(ctx, at, sig.range, now, &[from]) {
        let dir = ctx.db.body().id().find(c.id).map(|b| direction(pos(&b, now), at)).unwrap_or("nearby");
        let (text, sal) = if c.kind == me.kind {
            (format!("{heard} ({name}), {dir}."), sig.salience)
        } else {
            (format!("You hear {} from a {}, {dir}.", sig.sound, me.kind), (sig.salience * 0.8).min(0.7))
        };
        percept(ctx, &c, now, "signal", from, 0, at, text, sal);
        if c.kind == me.kind && sig.salience >= 0.7 && c.ai && (!sig.kin_only || cares(&c)) {
            request_deliberation(ctx, c.id, &format!("{heard} ({name}), {dir}."), now);
        }
    }
    Ok(format!("made {}", sig.sound))
}

const CRY_REMINDER_MS: u64 = 120_000;

fn infant_needs(state: living_rules::script::BodyState) -> Vec<InfantNeed> {
    let mut needs = Vec::new();
    if state.starving { needs.push(InfantNeed::Starving); }
    else if state.hungry { needs.push(InfantNeed::Hungry); }
    if state.cold { needs.push(InfantNeed::Cold); }
    match state.wound {
        living_rules::script::Wound::None => {},
        living_rules::script::Wound::Hurt => needs.push(InfantNeed::Hurt),
        living_rules::script::Wound::BadlyWounded => needs.push(InfantNeed::BadlyWounded),
        living_rules::script::Wound::BarelyAlive => needs.push(InfantNeed::BarelyAlive),
    }
    if needs.is_empty() { needs.push(InfantNeed::Unsettled); }
    needs
}

fn cry_carers(nearby: &[(u32, f32, bool, bool)]) -> Vec<u32> {
    let parents: Vec<_> = nearby.iter().filter(|c| c.2).map(|c| c.0).collect();
    if !parents.is_empty() { return parents; }
    nearby.iter().filter(|c| c.3).min_by(|a, b| a.1.total_cmp(&b.1).then(a.0.cmp(&b.0)))
        .map(|c| vec![c.0]).unwrap_or_default()
}

fn pending_infant_cry(reason: &str, name: &str) -> bool {
    reason.contains(&format!("{name}, a baby, is crying and looks "))
        || reason.contains(&format!("You hear {name} crying."))
}

fn cry_prompt_due(state: &InfantCry, carer: u32, now: u64, pending_cry: bool) -> bool {
    match state.prompted.iter().find(|p| p.carer == carer) {
        None => true,
        Some(p) => !pending_cry && now.saturating_sub(p.at_ms) >= CRY_REMINDER_MS,
    }
}

fn record_cry_prompt(cry: &mut InfantCry, carer: u32, now: u64) {
    if let Some(p) = cry.prompted.iter_mut().find(|p| p.carer == carer) { p.at_ms = now; }
    else { cry.prompted.push(CryPrompt { carer, at_ms: now }); }
}

fn cry_state(old: Option<&InfantCry>, infant: u32, needs: Vec<InfantNeed>) -> InfantCry {
    old.filter(|r| r.needs == needs).cloned().unwrap_or(InfantCry {
        infant, needs, heard_ms: 0, prompted: Vec::new(),
    })
}

pub fn infant_distress(ctx: &ReducerContext, baby: &Character, at: (f32, f32), now: u64) {
    if baby.kind != "person" || baby.stage != 0 { return; }
    let Ok(state) = crate::act::body_state(ctx, baby.id, now) else { return };
    if state.cold || state.starving || state.wound != living_rules::script::Wound::None {
        if let Some(sig) = common::species(&baby.kind).and_then(|s| s.signals.get("cry").cloned()) {
            let _ = infant_cry(ctx, baby, at, sig.range, now);
        }
    } else if ctx.db.infant_cry().infant().find(baby.id).is_some_and(|r| r.needs != infant_needs(state)) {
        ctx.db.infant_cry().infant().delete(baby.id);
    }
}

fn infant_cry(ctx: &ReducerContext, baby: &Character, at: (f32, f32), range: f32, now: u64) -> Result<String, String> {
    let state = crate::act::body_state(ctx, baby.id, now)?;
    let needs = infant_needs(state);
    let old = ctx.db.infant_cry().infant().find(baby.id);
    let mut cry = cry_state(old.as_ref(), baby.id, needs);
    let heard = format!("{}, a baby, is crying and looks {}", baby.name, state.looks());
    let nearby = people_near(ctx, at, range, now, &[baby.id]);
    let carers = cry_carers(&nearby.iter().filter(|(c, _)| c.stage >= 2).map(|(c, d)| {
        let parent = baby.parent_a == c.id || baby.parent_b == c.id;
        let caring = (baby.parent_a != 0 && (c.parent_a == baby.parent_a || c.parent_b == baby.parent_a))
            || ctx.db.relation().by_pair().filter((c.id, baby.id)).any(|r| r.affinity > 0.0);
        (c.id, *d, parent, caring)
    }).collect::<Vec<_>>());
    let emit = cry.heard_ms == 0 || now.saturating_sub(cry.heard_ms) >= 45_000;
    if emit {
        cry.heard_ms = now;
        for (c, _) in minds_near(ctx, at, range, now, &[baby.id]) {
            let dir = ctx.db.body().id().find(c.id).map(|b| direction(pos(&b, now), at)).unwrap_or("nearby");
            let text = if c.kind == "person" {
                let visible = ctx.db.body().id().find(c.id).is_some_and(|b| crate::perception::sees(ctx, c.id, &b, at, &common::world(ctx), &common::map(ctx), now));
                if visible { format!("{heard}, {dir}.") }
                else { format!("You hear {} crying, {dir}.", baby.name) }
            } else { format!("You hear a baby crying, {dir}.") };
            percept(ctx, &c, now, "signal", baby.id, 0, at, text, if c.kind == "person" { 0.8 } else { 0.64 });
        }
    }
    if !common::laws(ctx).cry_prompts_carers {
        // The cry is only a percept (above): no mind is made to think about it, and
        // whether a culture attends to its infants is left to the minds themselves.
        if old.as_ref() != Some(&cry) {
            if old.is_some() { ctx.db.infant_cry().infant().update(cry); }
            else { ctx.db.infant_cry().insert(cry); }
        }
        return Ok("made a baby crying".into());
    }
    cry.prompted.retain(|p| carers.contains(&p.carer) || now.saturating_sub(p.at_ms) < CRY_REMINDER_MS);
    for carer in carers {
        let pending = ctx.db.deliberation().actor().find(carer);
        let pending_cry = pending.as_ref().is_some_and(|d| pending_infant_cry(&d.reason, &baby.name));
        if cry_prompt_due(&cry, carer, now, pending_cry) {
            let visible = ctx.db.body().id().find(carer).is_some_and(|b| crate::perception::sees(ctx, carer, &b, at, &common::world(ctx), &common::map(ctx), now));
            let reason = if visible { heard.clone() } else { format!("You hear {} crying.", baby.name) };
            if pending.as_ref().is_some_and(|d| d.reason.contains(&reason)) { continue; }
            let urgent = state.cold || state.starving || state.wound != living_rules::script::Wound::None;
            if request(ctx, carer, &reason, now, urgent) {
                record_cry_prompt(&mut cry, carer, now);
            }
        }
    }
    if old.as_ref() != Some(&cry) {
        if old.is_some() { ctx.db.infant_cry().infant().update(cry); }
        else { ctx.db.infant_cry().insert(cry); }
    }
    Ok("made a baby crying".into())
}

/// Ask the mind to reconsider. Reasons merge while a request is pending.
pub fn request_deliberation(ctx: &ReducerContext, id: u32, reason: &str, now: u64) {
    request(ctx, id, reason, now, false);
}

fn request(ctx: &ReducerContext, id: u32, reason: &str, now: u64, urgent: bool) -> bool {
    let Some(c) = ctx.db.character().id().find(id) else { return false };
    // Infants run on their instincts; they get a mind when they become children.
    if !c.ai || !c.alive || c.stage == 0 {
        return false;
    }
    // Minds of other species think less often; being attacked is always worth a thought.
    let urgent = urgent || reason.contains("attacking you") || reason.starts_with("The fight with");
    // Away from people an animal lives by its instincts: its mind is for encounters
    // (and for being attacked). Keeps thinking where the world is being lived and watched.
    if c.kind != "person" && !urgent {
        let at = ctx.db.body().id().find(id).map(|b| common::pos(&b, now)).unwrap_or((0.0, 0.0));
        if !common::creatures_near(ctx, at, 25.0, now).iter().any(|x| &*x.kind == "person") {
            return false;
        }
    }
    if let Some(sp) = common::species(&c.kind) {
        let min = sp.cognition.think_min_s * 1000;
        let recent = ctx.db.mind_state().id().find(id).map_or(false, |s| now.saturating_sub(s.deliberated_ms) < min);
        if min > 0 && recent && !urgent && ctx.db.deliberation().actor().find(id).is_none() {
            return false;
        }
    }
    let revision = ctx.db.brain().id().find(id).map(|b| b.revision).unwrap_or(0);
    let scene = scene_json(ctx, id, now);
    if let Some(mut d) = ctx.db.deliberation().actor().find(id) {
        living_rules::reasons::add(&mut d.reason, &mut d.arrived, reason, now);
        d.scene = scene;
        d.revision = revision;
        d.updated_ms = now;
        ctx.db.deliberation().actor().update(d);
    } else {
        ctx.db.deliberation().insert(Deliberation { actor: id, controller: c.controller, reason: reason.into(), requested_ms: now, updated_ms: now, scene, revision, arrived: living_rules::reasons::first(reason, now) });
        common::count(|k| k.deliberations += 1);
    }
    true
}

fn round(v: f32) -> f64 {
    (v as f64 * 10.0).round() / 10.0
}

/// What the character currently perceives, as compact JSON for the mind.
pub fn scene_json(ctx: &ReducerContext, id: u32, now: u64) -> String {
    let w = common::world(ctx);
    let Some(me) = ctx.db.character().id().find(id) else { return "{}".into() };
    let Some(b) = ctx.db.body().id().find(id) else { return "{}".into() };
    let at = pos(&b, now);
    let map = common::map(ctx);
    let mut you = JMap::new();
    you.insert("id".into(), json!(id));
    you.insert("name".into(), json!(me.name));
    you.insert("kind".into(), json!(me.kind));
    you.insert("at".into(), json!([round(at.0), round(at.1)]));
    you.insert("terrain".into(), json!(map.at(at.0, at.1).name()));
    if let Some(sp) = common::species(&me.kind).filter(|s| !s.eats.is_empty()) {
        you.insert("you eat".into(), json!(sp.eats));
    }
    {
        let w = common::world(ctx);
        let life = common::life_of(ctx, &me.kind);
        let years = life.years_old(common::age_days(&me, &w, now), common::pace(&w));
        you.insert("age".into(), json!(format!("{:.0} years ({})", years.floor(), common::stage_of(ctx, &me, &w, now).name())));
    }
    // What one knows of one's own body and skill (inborn and practised).
    let body = living_rules::genes::notable(&common::genes_of(ctx, id));
    if !body.is_empty() {
        you.insert("your body".into(), json!(body.join(", ")));
    }
    let skills: JMap<String, Value> = common::practice_of(ctx, id).into_iter().filter(|(_, n)| *n >= 10).map(|(s, n)| (s, json!(living_rules::genes::practised(n)))).collect();
    if !skills.is_empty() {
        you.insert("your skills".into(), Value::Object(skills));
    }
    let partner = ctx
        .db
        .character()
        .parent_a()
        .filter(id)
        .chain(ctx.db.character().parent_b().filter(id))
        .max_by_key(|c| c.born_ms)
        .map(|c| if c.parent_a == id { c.parent_b } else { c.parent_a })
        .filter(|p| *p != 0);
    if let Some(v) = ctx.db.vitals().id().find(id) {
        let n = common::needs(&v, now);
        you.insert("health".into(), json!(n.hp.round()));
        you.insert("hunger".into(), json!(n.hunger.round()));
        you.insert("energy".into(), json!(n.energy.round()));
    }
    let pack: JMap<String, Value> = common::inv_list(ctx, id as u64).into_iter().map(|(k, q)| (k, json!(q))).collect();
    you.insert("pack".into(), Value::Object(pack));
    let my_community = ctx.db.membership().member().find(id).map(|m| m.community);
    if let Some(c) = my_community.and_then(|c| ctx.db.community().id().find(c)) {
        you.insert("community".into(), json!({"name": c.name, "home": [round(c.home_x), round(c.home_y)]}));
    }
    if me.kind == "person" {
        you.insert("knows_how_to".into(), json!(common::knows(ctx, id)));
        let tablets: Vec<Value> = ctx.db.artifact().holder().filter(id as u64).map(|a| json!({"by": a.author_name, "topic": a.topic})).collect();
        if !tablets.is_empty() {
            you.insert("tablets".into(), Value::Array(tablets));
        }
    }
    if let Some(a) = ctx.db.activity().id().find(id) {
        let decided = if a.node == crate::act::ACT { " (as you decided)" } else { "" };
        you.insert("doing".into(), json!(format!("{}{decided}", a.label)));
    }
    // Having given in is a social fact both sides know.
    let hold = common::scripts(ctx).num_of("yield_ms", "person", 20_000.0) as f32;
    let gave_in = |who: u32| crate::act::yielded_ago(ctx, who, now).filter(|ago| *ago < hold).map(|ago| (ago / 1000.0).round());
    if let Some(s) = gave_in(id) {
        you.insert("yielded".into(), json!(format!("you gave in {s:.0}s ago: while it holds ({:.0}s) you do not strike back", hold / 1000.0)));
    }
    let waiting: Vec<String> = ctx.db.act_queue().actor().filter(id).filter_map(|p| living_rules::acts::from_json(&p.node).ok()).map(|a| living_rules::graph::describe(&living_rules::graph::Node::Do(a))).collect();
    if !waiting.is_empty() {
        you.insert("decided, not yet done".into(), json!(waiting));
    }
    // Standing proposals between you and others (social facts both sides know).
    let ago = |t: u64| format!("{}s ago", now.saturating_sub(t) / 1000);
    let window = (common::laws(ctx).bond_window_s * 1000.0) as u64;
    let mut asked = Vec::new();
    for o in ctx.db.bond_offer().to().filter(id).filter(|o| now.saturating_sub(o.at_ms) <= window) {
        asked.push(json!({"from": o.from, "name": common::label_for(ctx, &me, o.from), "asks": "to start a family with you (it happens if you also choose conceive toward them in time)", "when": ago(o.at_ms)}));
    }
    let laws = common::laws(ctx);
    let join_ms = (laws.join_window_s * 1000.0) as u64;
    for o in ctx.db.trade_offer().to().filter(id).filter(|o| now <= o.ends_ms(laws.trade_window_s)) {
        asked.push(json!({"from": o.from, "name": common::label_for(ctx, &me, o.from), "asks": format!("a trade: their {} {} for your {} {} (accept to exchange, or decline)", o.give_qty, o.give_item, o.want_qty, o.want_item), "offer": o.id, "when": ago(o.at_ms)}));
    }
    if let Some(m) = ctx.db.membership().member().find(id) {
        for r in ctx.db.join_request().iter().filter(|r| r.community == m.community && now.saturating_sub(r.at_ms) <= join_ms) {
            asked.push(json!({"from": r.asker, "name": common::label_for(ctx, &me, r.asker), "asks": "to join your community (welcome them to let them in)", "when": ago(r.at_ms)}));
        }
    }
    if !asked.is_empty() {
        you.insert("asked of you".into(), Value::Array(asked));
    }
    let mut mine = Vec::new();
    for o in ctx.db.bond_offer().from().filter(id).filter(|o| now.saturating_sub(o.at_ms) <= window) {
        mine.push(json!({"to": o.to, "name": common::label_for(ctx, &me, o.to), "you asked": "to start a family", "when": ago(o.at_ms)}));
    }
    for o in ctx.db.trade_offer().from().filter(id).filter(|o| now <= o.ends_ms(laws.trade_window_s)) {
        mine.push(json!({"to": o.to, "name": common::label_for(ctx, &me, o.to), "you asked": format!("a trade: your {} {} for their {} {}", o.give_qty, o.give_item, o.want_qty, o.want_item), "offer": o.id, "when": ago(o.at_ms)}));
    }
    if !mine.is_empty() {
        you.insert("you are waiting on".into(), Value::Array(mine));
    }
    let hour = common::hour(&w, now);
    let r = common::sight_for(ctx, id, &w, now);
    let time = json!({"day": living_rules::day_of(now, w.epoch_ms, w.day_ms), "hour": round(hour), "night": common::scripts(ctx).is_night(hour), "season": common::season(ctx, now), "sight": r});

    let mut creatures = Vec::new();
    // What the character sees (sight and a clear sight line), each as it perceives them (the
    // `perceived_of` projection a player's view carries too).
    let (in_sight, heard_now) = crate::perception::sensed(ctx, id, at, r, now);
    for c in &in_sight {
        let Some(ch) = ctx.db.character().id().find(c.id) else { continue };
        let seen = crate::perception::project(ctx, &me, &ch, now);
        let mut o = JMap::new();
        o.insert("id".into(), json!(c.id));
        if !seen.name.is_empty() {
            o.insert("name".into(), json!(seen.name));
        } else if ch.kind == "person" {
            o.insert("who".into(), json!(seen.label));
        }
        if my_community.is_some() && ctx.db.membership().member().find(c.id).map(|m| m.community) == my_community {
            o.insert("community".into(), json!("yours"));
        }
        o.insert("kind".into(), json!(ch.kind));
        match ch.stage {
            0 => {
                o.insert("age".into(), json!(if ch.kind == "person" { "baby" } else { "newborn" }));
            }
            1 => {
                o.insert("age".into(), json!(if ch.kind == "person" { "child" } else { "young" }));
            }
            3 => {
                o.insert("age".into(), json!("old"));
            }
            _ => {}
        }
        if ch.parent_a == id || ch.parent_b == id {
            o.insert("family".into(), json!("your child"));
        } else if me.parent_a == ch.id || me.parent_b == ch.id {
            o.insert("family".into(), json!("your parent"));
        } else if partner == Some(ch.id) {
            o.insert("family".into(), json!("your partner (you have children together)"));
        }
        o.insert("dist".into(), json!(round(c.dist)));
        o.insert("dir".into(), json!(direction(at, c.pos)));
        if let Some(doing) = crate::perception::doing_of(ctx, c.id, (id, &me.kind, at), &in_sight, now) {
            o.insert("doing".into(), json!(doing));
        }
        if ch.kind == "person" {
            if let Some(s) = gave_in(c.id) {
                o.insert("yielded".into(), json!(format!("gave in {s:.0}s ago")));
            }
        }
        if seen.hp >= 0.0 {
            o.insert("health".into(), json!(format!("{:.0} of {:.0}", seen.hp, seen.max_hp)));
        }
        if let Some(v) = ctx.db.vitals().id().find(c.id) {
            let n = common::needs(&v, now);
            // The wound one can tell: the projection's band (none when the law hides health).
            let wound = match seen.band {
                0 => "barely alive",
                1 => "badly wounded",
                2 => "hurt",
                _ => "",
            };
            // Hunger shows too: anyone looks starved near the end, and a baby or child cries
            // and fusses when hungry.
            let hunger = if n.hunger >= 85.0 { "starving" } else if n.hunger >= 60.0 && ch.stage <= 1 { "hungry" } else { "" };
            let looks = [wound, hunger].into_iter().filter(|s| !s.is_empty()).collect::<Vec<_>>().join(", ");
            if !looks.is_empty() {
                o.insert("looks".into(), json!(looks));
            }
            if ch.kind == "person" && ch.stage == 0 {
                if let Ok(state) = crate::act::body_state(ctx, ch.id, now) {
                    o.insert("looks".into(), json!(state.looks()));
                }
            }
        }
        creatures.push(Value::Object(o));
        if creatures.len() >= 14 {
            break;
        }
    }

    // Creatures smelled beyond sight: only kind, rough direction and distance (and an id to
    // go after), at most the 3 nearest of each kind.
    let mut smelled = Vec::new();
    let mut per_kind: Vec<(std::rc::Rc<str>, u32)> = Vec::new();
    for c in common::smelled_near(ctx, id, &me.kind, at, r, now) {
        if c.id == id {
            continue;
        }
        let n = match per_kind.iter_mut().find(|k| k.0 == c.kind) {
            Some(k) => {
                k.1 += 1;
                k.1
            }
            None => {
                per_kind.push((c.kind.clone(), 1));
                1
            }
        };
        if n <= 3 {
            let far = if c.dist < 25.0 { "not far" } else if c.dist < 45.0 { "far" } else { "very far" };
            smelled.push(json!({"kind": &*c.kind, "id": c.id, "dir": direction(at, c.pos), "dist": format!("{far}, about {:.0} tiles", (c.dist / 10.0).round() * 10.0)}));
        }
    }

    let mut groups: Vec<(String, u32, Value)> = Vec::new();
    for (n, d) in common::resources_near(ctx, at, r) {
        let amount = common::amount_now(ctx, &common::stock_of(ctx, &n), now).floor();
        if let Some(g) = groups.iter_mut().find(|g| g.0 == n.kind) {
            g.1 += 1;
            continue;
        }
        groups.push((n.kind.clone(), 1, json!({"id": n.id, "at": [round(n.x), round(n.y)], "dist": round(d), "dir": direction(at, (n.x, n.y)), "amount": amount})));
    }
    let resources: Vec<Value> = groups.into_iter().map(|(k, n, near)| json!({"kind": k, "count": n, "nearest": near})).collect();

    let mut structures = Vec::new();
    for (s, d) in common::structures_near(ctx, at, r) {
        let mut o = json!({"id": s.id, "kind": s.kind, "at": [round(s.x), round(s.y)], "dist": round(d), "dir": direction(at, (s.x, s.y))});
        if s.owner != 0 {
            o["by"] = json!(common::label_for(ctx, &me, s.owner));
        }
        // A fire that needs no feeding burns; one that burns fuel burns while it has fuel (what
        // anyone near it sees: the flames, and roughly how much is left on it).
        let sc = common::scripts(ctx);
        let t = sc.structure(&s.kind);
        if let Some(b) = &t.burns {
            let (lit, fuel) = crate::act::fire_state(ctx, &s, now);
            o["state"] = json!(if lit { format!("burning, about {:.0} hours of {} left on it", (fuel / b.rate).max(0.5), b.fuel) } else { "out".to_string() });
        } else if t.fire() {
            o["state"] = json!("burning");
        }
        if s.kind == "sign" {
            if let Some(a) = ctx.db.artifact().holder().filter(STRUCTURE_BIT | s.id).next() {
                o["by"] = json!(a.author_name);
                o["note"] = json!("a written sign; read it to know what it says");
            }
        }
        if s.kind == "gate" {
            if let Some(g) = ctx.db.gate().id().find(s.id) {
                o["state"] = json!(if g.open { "open" } else { "shut" });
                if let Some(c) = ctx.db.community().id().find(g.community) {
                    o["kept_by"] = json!(c.name);
                }
            }
        }
        if s.kind == "house" && s.owner != 0 {
            o["home_of"] = json!(common::label_for(ctx, &me, s.owner));
        }
        if s.kind == "storage" || s.kind == "remains" {
            let inv: JMap<String, Value> = common::inv_list(ctx, STRUCTURE_BIT | s.id).into_iter().map(|(k, q)| (k, json!(q))).collect();
            o["contents"] = Value::Object(inv);
        }
        structures.push(o);
        if structures.len() >= 10 {
            break;
        }
    }

    // Nearest notable terrain within sight.
    let mut terrain = JMap::new();
    let (tx, ty) = (at.0.floor() as i32, at.1.floor() as i32);
    let ri = r as i32;
    use living_rules::map::Terrain;
    for kind in [Terrain::Water, Terrain::Forest, Terrain::Rock, Terrain::Road, Terrain::Wall, Terrain::Drop, Terrain::Low] {
        let mut best: Option<(f32, (f32, f32))> = None;
        for dy in -ri..=ri {
            for dx in -ri..=ri {
                if map.get(tx + dx, ty + dy) == kind {
                    let p = ((tx + dx) as f32 + 0.5, (ty + dy) as f32 + 0.5);
                    let d = dist(at, p);
                    if d <= r && best.map_or(true, |b| d < b.0) {
                        best = Some((d, p));
                    }
                }
            }
        }
        if let Some((d, p)) = best {
            // A class whose name does not say what it does is told in words, with how it meets
            // the foot and the eye ("south 5, a drop to ground at another level (...): you can
            // see past it but not walk through it").
            let said = match kind.words() {
                Some(w) => format!("{} {:.0}, {w}: {}", direction(at, p), d, kind.passage()),
                None => format!("{} {:.0}", direction(at, p), d),
            };
            terrain.insert(kind.name().into(), json!(said));
        }
    }

    let mut scene = json!({"you": you, "time": time, "creatures": creatures, "resources": resources, "structures": structures, "terrain_near": terrain});
    if !smelled.is_empty() {
        scene[living_rules::species::SMELLED] = Value::Array(smelled);
    }
    // While sight has a field (the `fov_on` law): which way one faces, and what one hears but
    // cannot see, in a person's words (what it sounds like, where from the way one faces and by
    // the compass, how far), never who it is.
    if common::senses_of(ctx, id, &w, now).field.is_some() {
        let heading = ctx.db.body().id().find(id).map_or(0.0, |b| common::facing_at(&b, now));
        scene["you"]["facing"] = json!(living_rules::sight::COMPASS8[living_rules::sight::compass8(at, (at.0 + heading.cos(), at.1 + heading.sin())) as usize]);
        let laws = common::laws(ctx);
        let heard: Vec<Value> = heard_now
            .iter()
            .take(8)
            .map(|c| {
                let band = living_rules::sight::heard_band(c.dist, laws.heard_near_m, laws.heard_close_m);
                let (what, wh, far) = living_rules::sight::heard_words(&crate::perception::heard_kind(ctx, &c.kind), at, heading, c.pos, band);
                json!({"what": what, "where": wh, "how far": far})
            })
            .collect();
        if !heard.is_empty() {
            scene[living_rules::sight::HEARD] = Value::Array(heard);
        }
    }
    scene.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cries_prompt_parents_then_one_nearest_caring_adult() {
        let adults = [(1, 4.0, true, true), (2, 5.0, true, true), (3, 1.0, false, true), (4, 0.5, false, false)];
        assert_eq!(cry_carers(&adults), vec![1, 2]);
        assert_eq!(cry_carers(&adults[2..]), vec![3]);
        assert!(cry_carers(&adults[3..]).is_empty());
        assert_eq!(cry_carers(&[(4, 2.0, false, true), (3, 2.0, false, true)]), vec![3]);
    }

    #[test]
    fn same_cause_merges_pending_and_limits_completed_reminders() {
        let mut cry = cry_state(None, 9, vec![InfantNeed::Hungry]);
        assert!(cry_prompt_due(&cry, 1, 10_000, true), "an unrelated pending reason still receives the cry");
        cry.prompted.push(CryPrompt { carer: 1, at_ms: 10_000 });
        assert!(!cry_prompt_due(&cry, 1, 55_000, false));
        assert!(!cry_prompt_due(&cry, 1, 130_000, true), "pending cry never retriggers");
        assert!(cry_prompt_due(&cry, 1, 130_000, false));
        assert!(cry_prompt_due(&cry, 2, 11_000, false), "a newly responsible parent can respond");
        let changed = cry_state(Some(&cry), 9, vec![InfantNeed::Hungry, InfantNeed::Cold]);
        assert!(cry_prompt_due(&changed, 1, 11_000, true), "new distress merges immediately");
        let starving = cry_state(Some(&cry), 9, vec![InfantNeed::Starving]);
        assert!(cry_prompt_due(&starving, 1, 11_000, false));
        let wounded = cry_state(Some(&cry), 9, vec![InfantNeed::Hungry, InfantNeed::BadlyWounded]);
        let critical = cry_state(Some(&wounded), 9, vec![InfantNeed::Hungry, InfantNeed::BarelyAlive]);
        assert!(cry_prompt_due(&critical, 1, 11_000, true));
        assert_eq!(cry_state(Some(&cry), 9, vec![InfantNeed::Hungry]), cry);
    }

    #[test]
    fn cries_keep_each_physical_cause() {
        use living_rules::script::BodyState;
        assert_eq!(infant_needs(BodyState::default()), vec![InfantNeed::Unsettled]);
        assert_eq!(infant_needs(BodyState { hungry: true, cold: true, wound: living_rules::script::Wound::Hurt, starving: false }),
            vec![InfantNeed::Hungry, InfantNeed::Cold, InfantNeed::Hurt]);
        assert_eq!(infant_needs(BodyState { hungry: true, starving: true, ..Default::default() }), vec![InfantNeed::Starving]);
    }

    #[test]
    fn due_reminder_merges_unrelated_pending_reason_but_preserves_pending_cry() {
        let mut cry = cry_state(None, 9, vec![InfantNeed::Hungry]);
        record_cry_prompt(&mut cry, 1, 10_000);
        for (reason, due) in [
            ("A new day. You long for another child.", true),
            ("A new day.\nMira, a baby, is crying and looks hungry, cold", false),
            ("A new day.\nYou hear Mira crying.", false),
            ("Nora, a baby, is crying and looks hungry", true),
            ("You hear Nora crying.", true),
        ] {
            let pending = Some(reason);
            let pending_cry = pending.is_some_and(|reason| pending_infant_cry(reason, "Mira"));
            assert_eq!(cry_prompt_due(&cry, 1, 130_000, pending_cry), due, "{reason}");
        }
    }

    #[test]
    fn one_parents_reminder_preserves_the_others_pending_cry() {
        let mut cry = cry_state(None, 9, vec![InfantNeed::Hungry]);
        record_cry_prompt(&mut cry, 1, 10_000);
        record_cry_prompt(&mut cry, 2, 10_000);
        assert!(cry_prompt_due(&cry, 1, 130_000, false));
        record_cry_prompt(&mut cry, 1, 130_000);
        assert!(!cry_prompt_due(&cry, 2, 130_000, true));
        assert!(!cry_prompt_due(&cry, 2, 250_000, true));
        assert!(cry_prompt_due(&cry, 2, 130_000, false));
    }

    #[test]
    fn the_one_an_event_was_done_to_reads_it_as_done_to_them() {
        let death = "{a} was killed by {b} after yielding";
        assert_eq!(rendered(death, "a stranger", "Bram", false), "A stranger was killed by Bram after yielding");
        assert_eq!(rendered(death, "Edda", "a stranger", false), "Edda was killed by a stranger after yielding");
        assert_eq!(rendered(death, "a stranger", "Bram", true), "A stranger was killed by you after yielding");
        assert_eq!(rendered("{a} was killed by {b}", "Edda", "Bram", true), "Edda was killed by you");
        let took = "{a} took 4 berries from {b}'s storage";
        assert_eq!(rendered(took, "a stranger", "Bortha", false), "A stranger took 4 berries from Bortha's storage");
        assert_eq!(rendered(took, "a stranger", "Bortha", true), "A stranger took 4 berries from your storage");
        assert_eq!(rendered("{a} gives in, guard down and hands raised", "a child", "", false), "A child gives in, guard down and hands raised");
    }
}
