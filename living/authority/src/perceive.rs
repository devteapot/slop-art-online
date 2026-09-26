//! Perception: what witnesses experience, speech, and requests for the mind to deliberate.
//! Only characters within sight/hearing of an event receive a percept; the mind never
//! reads world tables for its characters' context.

use crate::tables::*;
use crate::common::{self, dist, direction, pos};
use serde_json::{json, Map as JMap, Value};
use spacetimedb::{ReducerContext, Table};

/// Experiences kept per character (older ones leave the hot window).
const WINDOW: usize = 400;

pub fn percept(ctx: &ReducerContext, observer: &Character, now: u64, kind: &str, subject: u32, object: u32, at: (f32, f32), text: String, salience: f32) {
    // Only minds and human players consume percepts; instinct-only characters have no reader.
    if !observer.alive || (!observer.ai && observer.controller == ctx.database_identity()) {
        return;
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
    if let Some(mut c) = ctx.db.clock().id().find(0) {
        c.percepts += 1;
        ctx.db.clock().id().update(c);
    }
    // Bound the per-character window (checked periodically, not on every insert).
    if row.id % 32 == 0 {
        let mut ids: Vec<u64> = ctx.db.experience().observer().filter(observer.id).map(|p| p.id).collect();
        if ids.len() > WINDOW {
            ids.sort_unstable();
            for id in &ids[..ids.len() - WINDOW] {
                ctx.db.experience().id().delete(*id);
            }
        }
    }
    if salience >= 0.6 {
        common::wake(ctx, observer.id);
    }
}

/// People within `r` of `at` (excluding `exclude`).
pub fn people_near(ctx: &ReducerContext, at: (f32, f32), r: f32, now: u64, exclude: &[u32]) -> Vec<(Character, f32)> {
    common::creatures_near(ctx, at, r, now)
        .into_iter()
        .filter(|c| &*c.kind == "person" && !exclude.contains(&c.id))
        .filter_map(|c| ctx.db.character().id().find(c.id).map(|ch| (ch, c.dist)))
        .collect()
}

/// Minds (people and animals) within `r` of `at`.
pub fn minds_near(ctx: &ReducerContext, at: (f32, f32), r: f32, now: u64, exclude: &[u32]) -> Vec<(Character, f32)> {
    common::creatures_near(ctx, at, r, now)
        .into_iter()
        .filter(|c| !exclude.contains(&c.id))
        .filter_map(|c| ctx.db.character().id().find(c.id).map(|ch| (ch, c.dist)))
        .filter(|(ch, _)| ch.ai || ch.controller != ctx.database_identity())
        .collect()
}

/// Everyone who can see `at` receives a percept. `{a}` and `{b}` in `template` become how
/// each observer refers to `subject` and `object` (names for people and their own kind).
pub fn witnessed(ctx: &ReducerContext, now: u64, at: (f32, f32), kind: &str, subject: u32, object: u32, template: &str, salience: f32, exclude: &[u32]) {
    let w = common::world(ctx);
    let r = common::sight(ctx, &w, now);
    for (c, _) in minds_near(ctx, at, r, now, exclude) {
        let text = template.replace("{a}", &common::label_for(ctx, &c, subject)).replace("{b}", &common::label_for(ctx, &c, object));
        // Animals notice people's and other species' affairs less keenly than their own kind's.
        let sal = if &*c.kind != "person" && !template.contains("{a}") { salience * 0.5 } else { salience };
        percept(ctx, &c, now, kind, subject, object, at, text, sal);
    }
}

/// A species signal: heard by every mind within the signal's range.
pub fn signal(ctx: &ReducerContext, from: u32, name: &str, now: u64) -> Result<String, String> {
    let me = ctx.db.character().id().find(from).ok_or("no body")?;
    let sp = common::species(&me.kind).ok_or("unknown species")?;
    let sig = sp.signals.get(name).ok_or_else(|| format!("a {} has no `{name}` signal", me.kind))?;
    let at = ctx.db.body().id().find(from).map(|b| pos(&b, now)).ok_or("no body")?;
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
    for (c, _) in minds_near(ctx, at, sig.range, now, &[from]) {
        let dir = ctx.db.body().id().find(c.id).map(|b| direction(pos(&b, now), at)).unwrap_or("nearby");
        let (text, sal) = if c.kind == me.kind {
            (format!("{} makes {} ({name}), {dir}.", me.name, sig.sound), sig.salience)
        } else {
            (format!("You hear {} from a {}, {dir}.", sig.sound, me.kind), (sig.salience * 0.8).min(0.7))
        };
        percept(ctx, &c, now, "signal", from, 0, at, text, sal);
        if c.kind == me.kind && sig.salience >= 0.7 && c.ai {
            request_deliberation(ctx, c.id, &format!("{} gave {} ({name}).", me.name, sig.sound), now);
        }
    }
    Ok(format!("made {}", sig.sound))
}

pub fn speak(ctx: &ReducerContext, speaker: u32, text: &str, to: u32, now: u64) -> Result<(), String> {
    let text = text.trim();
    if text.is_empty() {
        return Ok(());
    }
    let text: String = text.chars().take(400).collect();
    let Some(me) = ctx.db.character().id().find(speaker) else { return Err("no speaker".into()) };
    let Some(b) = ctx.db.body().id().find(speaker) else { return Err("no body".into()) };
    if let Some(mut st) = ctx.db.mind_state().id().find(speaker) {
        if now.saturating_sub(st.spoke_ms) < 2_000 {
            return Err("speaking too fast".into());
        }
        st.spoke_ms = now;
        ctx.db.mind_state().id().update(st);
    }
    // Saying nearly the same thing again is still spoken and heard; the speaker notices it
    // (feedback, not suppression).
    let echo = said_recently(ctx, speaker, &text, now);
    let at = pos(&b, now);
    let to_name = if to != 0 { common::name_of(ctx, to) } else { String::new() };
    let line = if to != 0 { format!("{} to {}: “{}”", me.name, to_name, text) } else { format!("{}: “{}”", me.name, text) };
    common::chronicle(ctx, now, "speech", speaker, to, at, line);
    if let Some((ago_s, said)) = echo {
        let when = if ago_s < 5 { "just now".to_string() } else { format!("{ago_s} s ago") };
        percept(ctx, &me, now, "repeat", speaker, to, at, format!("You said almost the same thing {when}: “{said}”."), 0.3);
    }
    // Animals hear a voice, not words.
    for (c, _) in minds_near(ctx, at, common::laws(ctx).hearing, now, &[speaker]).into_iter().filter(|(c, _)| &*c.kind != "person") {
        let dir = ctx.db.body().id().find(c.id).map(|b| direction(pos(&b, now), at)).unwrap_or("nearby");
        percept(ctx, &c, now, "signal", speaker, 0, at, format!("You hear a person's voice, {dir}."), 0.25);
    }
    let hearers = people_near(ctx, at, common::laws(ctx).hearing, now, &[speaker]);
    // Silence is information: calling someone out of earshot (far away, or dead) gets no answer.
    if to != 0 && !hearers.iter().any(|(c, _)| c.id == to) {
        let who = common::label_for(ctx, &me, to);
        percept(ctx, &me, now, "silence", to, speaker, at, format!("No answer from {who}; they don't seem to be within earshot."), 0.35);
    }
    let close = hearers.iter().filter(|(_, d)| *d <= 6.0).count();
    for (c, d) in hearers {
        let addressed = to == c.id || (to == 0 && (close == 1 && d <= 6.0 || mentions(&text, &c.name)));
        let heard = if to == c.id {
            format!("{} said to you: “{}”", me.name, text)
        } else if to != 0 {
            format!("{} said to {}: “{}”", me.name, to_name, text)
        } else {
            format!("{} said: “{}”", me.name, text)
        };
        percept(ctx, &c, now, "speech", speaker, to, at, heard, if addressed { 0.9 } else { 0.45 });
        if let Some(mut st) = ctx.db.mind_state().id().find(c.id) {
            st.heard_ms = now;
            st.speaker = speaker;
            ctx.db.mind_state().id().update(st);
        }
        // Whether and how to answer is the listener's mind's affair: its service sees this
        // experience and gives the listener a conversation turn. Speech no longer requests a
        // full deliberation.
    }
    Ok(())
}

/// The most similar line this speaker said within the last 90 s, when nearly the same
/// (word-set Jaccard >= 0.6): seconds ago and the words.
fn said_recently(ctx: &ReducerContext, speaker: u32, text: &str, now: u64) -> Option<(u64, String)> {
    let words = |t: &str| -> std::collections::HashSet<String> {
        t.to_lowercase().split(|c: char| !c.is_alphanumeric()).filter(|w| w.len() > 2).map(String::from).collect()
    };
    let mine = words(text);
    let mut latest: Option<(u64, String)> = None;
    for c in ctx.db.chronicle().at_ms().filter(now.saturating_sub(90_000)..).filter(|c| c.kind == "speech" && c.a == speaker) {
        // Chronicle rows count exact repeats as "… (×n)".
        let base = c.text.rsplit_once(" (×").map_or(c.text.as_str(), |(b, _)| b);
        let said = base.split_once('“').map(|(_, t)| t.trim_end_matches('”')).unwrap_or(base);
        let theirs = words(said);
        let same = if mine.is_empty() || theirs.is_empty() {
            said.trim().eq_ignore_ascii_case(text.trim())
        } else {
            mine.intersection(&theirs).count() as f32 / mine.union(&theirs).count() as f32 >= 0.6
        };
        if same && latest.as_ref().map_or(true, |l| c.at_ms >= l.0) {
            latest = Some((c.at_ms, said.to_string()));
        }
    }
    latest.map(|(at, said)| (now.saturating_sub(at) / 1000, said))
}

fn mentions(text: &str, name: &str) -> bool {
    let t = text.to_lowercase();
    let n = name.to_lowercase();
    t.split(|ch: char| !ch.is_alphanumeric()).any(|w| w == n)
}

/// Ask the mind to reconsider. Reasons merge while a request is pending.
pub fn request_deliberation(ctx: &ReducerContext, id: u32, reason: &str, now: u64) {
    let Some(c) = ctx.db.character().id().find(id) else { return };
    if !c.ai || !c.alive {
        return;
    }
    // Minds of other species think less often; being attacked is always worth a thought.
    if let Some(sp) = common::species(&c.kind) {
        let min = sp.cognition.think_min_s * 1000;
        let recent = ctx.db.mind_state().id().find(id).map_or(false, |s| now.saturating_sub(s.deliberated_ms) < min);
        let urgent = reason.contains("attacking you") || reason.starts_with("The fight with") || reason.starts_with("Dawn of day");
        if min > 0 && recent && !urgent && ctx.db.deliberation().actor().find(id).is_none() {
            return;
        }
    }
    let revision = ctx.db.brain().id().find(id).map(|b| b.revision).unwrap_or(0);
    let scene = scene_json(ctx, id, now);
    if let Some(mut d) = ctx.db.deliberation().actor().find(id) {
        if !d.reason.contains(reason) && d.reason.len() < 900 {
            d.reason.push_str("\n");
            d.reason.push_str(reason);
        }
        d.scene = scene;
        d.revision = revision;
        d.updated_ms = now;
        ctx.db.deliberation().actor().update(d);
    } else {
        ctx.db.deliberation().insert(Deliberation { actor: id, controller: c.controller, reason: reason.into(), requested_ms: now, updated_ms: now, scene, revision });
        if let Some(mut k) = ctx.db.clock().id().find(0) {
            k.deliberations += 1;
            ctx.db.clock().id().update(k);
        }
    }
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
        you.insert("doing".into(), json!(a.label));
    }
    let hour = common::hour(&w, now);
    let r = common::sight_for(ctx, id, &w, now);
    let time = json!({"day": living_rules::day_of(now, w.epoch_ms, w.day_ms), "hour": round(hour), "night": living_rules::is_night(hour), "season": common::season(ctx, now), "sight": r});

    let mut creatures = Vec::new();
    for c in common::creatures_near(ctx, at, r, now) {
        if c.id == id {
            continue;
        }
        let Some(ch) = ctx.db.character().id().find(c.id) else { continue };
        let mut o = JMap::new();
        o.insert("id".into(), json!(c.id));
        if ch.kind == "person" || ch.kind == me.kind {
            o.insert("name".into(), json!(ch.name));
        }
        if my_community.is_some() && ctx.db.membership().member().find(c.id).map(|m| m.community) == my_community {
            o.insert("community".into(), json!("yours"));
        }
        o.insert("kind".into(), json!(ch.kind));
        o.insert("dist".into(), json!(round(c.dist)));
        o.insert("dir".into(), json!(direction(at, c.pos)));
        if let Some(a) = ctx.db.activity().id().find(c.id) {
            o.insert("doing".into(), json!(a.label));
        }
        if let Some(v) = ctx.db.vitals().id().find(c.id) {
            let n = common::needs(&v, now);
            if n.hp < v.max_hp * 0.6 {
                o.insert("looks".into(), json!("hurt"));
            }
        }
        creatures.push(Value::Object(o));
        if creatures.len() >= 14 {
            break;
        }
    }

    let mut groups: Vec<(String, u32, Value)> = Vec::new();
    for (n, d) in common::resources_near(ctx, at, r) {
        let amount = common::amount_now(ctx, &n, now).floor();
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
            o["by"] = json!(common::name_of(ctx, s.owner));
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
            o["home_of"] = json!(common::name_of(ctx, s.owner));
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
    for kind in [living_rules::map::Terrain::Water, living_rules::map::Terrain::Forest, living_rules::map::Terrain::Rock, living_rules::map::Terrain::Road, living_rules::map::Terrain::Wall] {
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
            terrain.insert(kind.name().into(), json!(format!("{} {:.0}", direction(at, p), d)));
        }
    }

    json!({"you": you, "time": time, "creatures": creatures, "resources": resources, "structures": structures, "terrain_near": terrain}).to_string()
}
