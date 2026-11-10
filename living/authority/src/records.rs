//! Records: durable social state the world's rules define (docs/WORLD_RULES.md). The rules
//! make, amend and close records through effects (`record`, `amend`, `close`), read the actor's
//! own in their laws (`a.records`), and are told when one falls due (`on_expire`). The engine
//! keeps them, indexed by party, bounds them, and drops them when their time has run out.
//!
//! A record is audit truth. Who knows of it is perception's: the rules tell parties (`tell`),
//! onlookers see it made (`witness`), and a player reads only their own characters' records
//! (`my_records`).
//!
//! Data paths (rows read and written, by index):
//! - a law that reads `a.records`: `record_party.party` for the actor and its community, then
//!   `record.id` per row (at most a few dozen);
//! - a record effect: inserts or updates one `record` and its 1–4 `record_party` rows;
//! - housekeeping (1 Hz): `record.due_ms` range up to now, at most `DUE_PER_PASS` rows;
//! - relation filters: the stance cache, rebuilt from `record_party.role = holder` rows when a
//!   stance record changed (`record_clock`).

use crate::common::{self, pos};
use crate::tables::*;
use living_rules::records::{RecordFacts, COMMUNITY, MAX_OPEN};
use living_rules::script::{Effect, SkillCtx};
use spacetimedb::{ReducerContext, Table, ViewContext};
use std::cell::RefCell;
use std::collections::HashMap;

/// A record the rules keep (private; parties read theirs through `my_records`).
#[spacetimedb::table(accessor = record)]
#[derive(Clone, Debug)]
pub struct Record {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub kind: String,
    pub status: String,
    pub open: bool,
    /// The terms: a JSON object of strings, numbers and booleans (the rules').
    pub terms: String,
    /// Who made it (0: the seed).
    pub by: u32,
    pub made_ms: u64,
    pub changed_ms: u64,
    /// When it falls due (`on_expire` for an open record; a closed one is then dropped);
    /// `u64::MAX`: never.
    #[index(btree)]
    pub due_ms: u64,
}

/// A party to a record: a character, or `COMMUNITY | community id`, in a role.
#[spacetimedb::table(accessor = record_party)]
#[derive(Clone, Debug)]
pub struct RecordParty {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub record: u64,
    #[index(btree)]
    pub party: u64,
    pub role: String,
}

/// A record as a player's view shows it: one row per record and party of mine.
#[derive(spacetimedb::SpacetimeType, Clone, Debug)]
pub struct MyRecord {
    pub id: u64,
    /// My character the record is about (directly or through its community).
    pub actor: u32,
    pub role: String,
    pub kind: String,
    pub status: String,
    pub open: bool,
    pub terms: String,
    /// The other parties: `role=id` (a community as `c<id>`), comma-separated.
    pub others: String,
    pub made_ms: u64,
    pub due_ms: u64,
}

/// Changes to stance records (one row): the stance cache is rebuilt when it moves.
#[spacetimedb::table(accessor = record_clock)]
pub struct RecordClock {
    #[primary_key]
    pub id: u8,
    pub stances: u64,
}

/// Due records handled per housekeeping pass; the rest wait for the next second.
const DUE_PER_PASS: usize = 64;

/// A character's own party, and its community's.
pub fn parties_of(ctx: &ReducerContext, id: u32) -> (u64, u64) {
    (id as u64, community_party(ctx, id))
}

pub fn community_party(ctx: &ReducerContext, id: u32) -> u64 {
    ctx.db.membership().member().find(id).map_or(0, |m| COMMUNITY | m.community as u64)
}

/// Where a character's household lives, as the rules see it (`"x,y"`; empty: none).
pub fn home_of(ctx: &ReducerContext, id: u32) -> String {
    ctx.db.character().id().find(id).filter(|c| c.home_x != 0.0 || c.home_y != 0.0).map(|c| format!("{:.0},{:.0}", c.home_x.floor(), c.home_y.floor())).unwrap_or_default()
}

fn hour_ms(ctx: &ReducerContext) -> f64 {
    common::world(ctx).day_ms as f64 / 24.0
}

fn due_after(ctx: &ReducerContext, now: u64, hours: Option<f32>) -> u64 {
    hours.map_or(u64::MAX, |h| now + (h as f64 * hour_ms(ctx)) as u64)
}

fn facts(r: &Record, parties: Vec<(String, u64)>, me: String, now: u64) -> RecordFacts {
    RecordFacts {
        id: r.id,
        kind: r.kind.clone(),
        status: r.status.clone(),
        open: r.open,
        terms: serde_json::from_str(&r.terms).unwrap_or_default(),
        parties,
        me,
        by: r.by,
        age_s: now.saturating_sub(r.made_ms) as f32 / 1000.0,
        due_s: (r.due_ms != u64::MAX).then(|| (r.due_ms as i64 - now as i64) as f32 / 1000.0),
    }
}

fn parties(ctx: &ReducerContext, record: u64) -> Vec<(String, u64)> {
    let mut v: Vec<(String, u64)> = ctx.db.record_party().record().filter(record).map(|p| (p.role, p.party)).collect();
    v.sort();
    v
}

/// The records a character is a party to, itself or through its community (as `a.records`).
pub fn of(ctx: &ReducerContext, id: u32, now: u64) -> Vec<RecordFacts> {
    let (me, community) = parties_of(ctx, id);
    let mut out: Vec<RecordFacts> = Vec::new();
    for party in [me, community].into_iter().filter(|p| *p != 0) {
        for p in ctx.db.record_party().party().filter(party) {
            if out.iter().any(|r| r.id == p.record) {
                continue;
            }
            if let Some(r) = ctx.db.record().id().find(p.record) {
                out.push(facts(&r, parties(ctx, r.id), p.role, now));
            }
        }
    }
    out.sort_by_key(|r| r.id);
    out
}

/// One record as a party (or no one, `me` empty) sees it.
pub fn one(ctx: &ReducerContext, id: u64, reader: u32, now: u64) -> Option<RecordFacts> {
    let r = ctx.db.record().id().find(id)?;
    let ps = parties(ctx, id);
    let (mine, community) = parties_of(ctx, reader);
    let me = ps.iter().find(|(_, p)| *p == mine).or_else(|| ps.iter().find(|(_, p)| community != 0 && *p == community)).map(|(r, _)| r.clone()).unwrap_or_default();
    Some(facts(&r, ps, me, now))
}

/// Open records a party holds now.
fn open_count(ctx: &ReducerContext, party: u64) -> usize {
    ctx.db.record_party().party().filter(party).filter(|p| ctx.db.record().id().find(p.record).is_some_and(|r| r.open)).count()
}

fn stance_changed(ctx: &ReducerContext, roles: &[(String, u64)]) {
    if !roles.iter().any(|(r, _)| r == living_rules::records::HOLDER) {
        return;
    }
    let mut c = ctx.db.record_clock().id().find(0).unwrap_or(RecordClock { id: 0, stances: 0 });
    c.stances += 1;
    if ctx.db.record_clock().id().find(0).is_some() {
        ctx.db.record_clock().id().update(c);
    } else {
        ctx.db.record_clock().insert(c);
    }
}

/// Make a record (the seed's, or a rule's after its checks).
pub fn make(ctx: &ReducerContext, kind: &str, status: &str, by: u32, parties: &[(String, u64)], terms: &serde_json::Map<String, serde_json::Value>, due_ms: u64, now: u64) -> u64 {
    let r = ctx.db.record().insert(Record { id: 0, kind: kind.into(), status: status.into(), open: true, terms: serde_json::to_string(terms).unwrap_or_else(|_| "{}".into()), by, made_ms: now, changed_ms: now, due_ms });
    for (role, party) in parties {
        ctx.db.record_party().insert(RecordParty { id: 0, record: r.id, party: *party, role: role.clone() });
    }
    stance_changed(ctx, parties);
    r.id
}

fn drop_record(ctx: &ReducerContext, id: u64) {
    let ps: Vec<RecordParty> = ctx.db.record_party().record().filter(id).collect();
    stance_changed(ctx, &ps.iter().map(|p| (p.role.clone(), p.party)).collect::<Vec<_>>());
    for p in ps {
        ctx.db.record_party().id().delete(p.id);
    }
    ctx.db.record().id().delete(id);
}

/// What an effect list from the rules does to records and who is told, for one actor (and the
/// record at hand, when the rules were asked about it). Returns the note for the actor's own
/// outcome: what the rules told the actor itself.
pub fn apply(ctx: &ReducerContext, sctx: &SkillCtx, e: Effect, now: u64) -> Result<Option<String>, String> {
    let me = sctx.actor.id;
    let mine = |party: u64| party == me as u64 || (sctx.actor.community != 0 && party == sctx.actor.community);
    let may_change = |id: u64| sctx.record.as_ref().is_some_and(|r| r.id == id) || ctx.db.record_party().record().filter(id).any(|p| mine(p.party));
    match e {
        Effect::Record { kind, status, parties, terms, due_h } => {
            if !parties.iter().any(|(_, p)| mine(*p)) {
                return Err("a record must have the one who makes it among its parties".into());
            }
            for (_, p) in &parties {
                if *p < COMMUNITY && ctx.db.character().id().find(*p as u32).is_none_or(|c| !c.alive) {
                    return Err("one of its parties is not there".into());
                }
                if *p < COMMUNITY && open_count(ctx, *p) >= MAX_OPEN {
                    return Err(format!("{} has too many dealings in hand already", if *p == me as u64 { "you".to_string() } else { common::name_of(ctx, *p as u32) }));
                }
            }
            make(ctx, &kind, if status.is_empty() { "open" } else { &status }, me, &parties, &terms, due_after(ctx, now, due_h), now);
            Ok(None)
        },
        Effect::Amend { id, status, terms, due_h } => {
            if !may_change(id) {
                return Err("no such record of yours".into());
            }
            let Some(mut r) = ctx.db.record().id().find(id) else { return Err("no such record of yours".into()) };
            if let Some(s) = status {
                r.status = s;
            }
            if !terms.is_empty() {
                let mut t: serde_json::Map<String, serde_json::Value> = serde_json::from_str(&r.terms).unwrap_or_default();
                t.extend(terms);
                living_rules::records::check_terms(&t)?;
                r.terms = serde_json::to_string(&t).unwrap_or_else(|_| "{}".into());
            }
            if due_h.is_some() {
                r.due_ms = due_after(ctx, now, due_h);
            }
            r.changed_ms = now;
            ctx.db.record().id().update(r);
            stance_changed(ctx, &parties(ctx, id));
            Ok(None)
        },
        Effect::Close { id, status, keep_h } => {
            if !may_change(id) {
                return Err("no such record of yours".into());
            }
            let Some(mut r) = ctx.db.record().id().find(id) else { return Err("no such record of yours".into()) };
            r.open = false;
            if !status.is_empty() {
                r.status = status;
            }
            r.due_ms = due_after(ctx, now, Some(keep_h));
            r.changed_ms = now;
            ctx.db.record().id().update(r);
            stance_changed(ctx, &parties(ctx, id));
            Ok(None)
        },
        Effect::Tell { to, text, salience, ask } => {
            let Some(c) = (to < COMMUNITY).then(|| ctx.db.character().id().find(to as u32)).flatten().filter(|c| c.alive) else { return Ok(None) };
            let text = words_for(ctx, &c, &text, sctx);
            // Told to the actor of a skill, it is that act's outcome.
            if c.id == me && sctx.record.is_none() && !sctx.skill.is_empty() {
                return Ok(Some(text));
            }
            let at = ctx.db.body().id().find(c.id).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
            let other = if c.id == me { sctx.target.id as u32 } else { me };
            crate::perceive::percept(ctx, &c, now, "record", other, c.id, at, text.clone(), salience);
            if ask && c.ai {
                crate::perceive::request_deliberation(ctx, c.id, &text, now);
            }
            Ok(None)
        },
        Effect::Witness { text, salience } => {
            let at = ctx.db.body().id().find(me).map(|b| pos(&b, now)).unwrap_or((0.0, 0.0));
            let other = if sctx.target.class == "creature" { sctx.target.id as u32 } else { 0 };
            crate::perceive::witnessed(ctx, now, at, "record", me, other, &text, salience, &[me, other]);
            Ok(None)
        },
        other => Err(format!("{other:?} is not a record effect")),
    }
}

/// The rules' words with `{actor}`, `{target}` and `{id:N}` as the one told refers to them.
fn words_for(ctx: &ReducerContext, told: &Character, text: &str, sctx: &SkillCtx) -> String {
    let mut out = String::with_capacity(text.len() + 16);
    let mut rest = text;
    while let Some(i) = rest.find('{') {
        out.push_str(&rest[..i]);
        let Some(j) = rest[i..].find('}') else {
            out.push_str(&rest[i..]);
            rest = "";
            break;
        };
        let key = &rest[i + 1..i + j];
        let n = key.strip_prefix("id:").and_then(|n| n.trim().parse::<u64>().ok());
        // A community by its name (everyone knows the names of places).
        if let Some(c) = n.filter(|n| *n >= COMMUNITY).and_then(|n| ctx.db.community().id().find((n - COMMUNITY) as u32)) {
            out.push_str(&c.name);
            rest = &rest[i + j + 1..];
            continue;
        }
        let id = match key {
            "actor" => Some(sctx.actor.id),
            "target" if sctx.target.class == "creature" => Some(sctx.target.id as u32),
            _ => n.filter(|n| *n < COMMUNITY).map(|n| n as u32),
        };
        match id {
            Some(id) if id == told.id => out.push_str(if out.trim_end().is_empty() || out.trim_end().ends_with('.') { "You" } else { "you" }),
            Some(id) if out.trim_end().is_empty() || out.trim_end().ends_with('.') => out.push_str(&common::label_cap(ctx, told, id)),
            Some(id) => out.push_str(&common::label_for(ctx, told, id)),
            None => out.push_str(&rest[i..i + j + 1]),
        }
        rest = &rest[i + j + 1..];
    }
    out.push_str(rest);
    let mut c = out.chars();
    match c.next() {
        Some(f) => f.to_uppercase().chain(c).collect(),
        None => out,
    }
}

/// Records whose time has run out: an open one is the rules' to settle (`on_expire`), and
/// dropped unless they gave it more time; a closed one is dropped.
pub fn housekeeping(ctx: &ReducerContext, now: u64) {
    let due: Vec<Record> = ctx.db.record().due_ms().filter(..=now).take(DUE_PER_PASS).collect();
    if due.is_empty() {
        return;
    }
    let _t = common::span("records.due");
    let sc = common::scripts(ctx);
    for r in due {
        if r.open && sc.has_hook("expire") {
            let ps = parties(ctx, r.id);
            // The rules are asked as its maker, or else its first character party.
            let actor = Some(r.by).filter(|b| *b != 0 && ctx.db.character().id().find(*b).is_some()).or_else(|| ps.iter().map(|(_, p)| *p).find(|p| *p < COMMUNITY).map(|p| p as u32)).unwrap_or(0);
            let other = ps.iter().map(|(_, p)| *p).find(|p| *p < COMMUNITY && *p != actor as u64).unwrap_or(0) as u32;
            let mut c = SkillCtx { actor: crate::act::facts(ctx, actor, now), night: common::night(&common::world(ctx), now), hour: common::hour(&common::world(ctx), now), ..Default::default() };
            c.actor.community = community_party(ctx, actor);
            c.records = of(ctx, actor, now);
            c.record = one(ctx, r.id, actor, now);
            if other != 0 {
                c.target = living_rules::script::TargetFacts { class: "creature".into(), id: other as u64, kind: ctx.db.character().id().find(other).map(|o| o.kind).unwrap_or_default(), alive: true, ..Default::default() };
            }
            match sc.hook("expire", &c) {
                Ok(fx) => {
                    for e in fx {
                        if let Err(why) = apply(ctx, &c, e, now) {
                            log::warn!("on_expire for record {}: {why}", r.id);
                        }
                    }
                },
                Err(e) => log::warn!("on_expire for record {}: {e}", r.id),
            }
        }
        // Still due: the rules let it run out.
        if ctx.db.record().id().find(r.id).is_some_and(|x| x.due_ms <= now) {
            drop_record(ctx, r.id);
        }
    }
}

/// What the rules make of a skill done (`on_<skill>`), applied as the actor. A hook that fails
/// is logged; the act it follows stands.
pub fn after_skill(ctx: &ReducerContext, sctx: &SkillCtx, now: u64) {
    let sc = common::scripts(ctx);
    if !sc.has_hook(&sctx.skill) {
        return;
    }
    match sc.hook(&sctx.skill, sctx) {
        Ok(fx) => {
            for e in fx {
                if let Err(why) = apply(ctx, &SkillCtx { skill: String::new(), ..sctx.clone() }, e, now) {
                    log::warn!("on_{} for {}: {why}", sctx.skill, sctx.actor.id);
                }
            }
        },
        Err(e) => log::warn!("on_{} for {}: {e}", sctx.skill, sctx.actor.id),
    }
}

/// What the rules make of a death (`on_death`), asked before the dead's things are gone.
pub fn on_death(ctx: &ReducerContext, id: u32, now: u64) {
    let sc = common::scripts(ctx);
    if !sc.has_hook("death") {
        return;
    }
    let mut c = SkillCtx { actor: crate::act::facts(ctx, id, now), hour: common::hour(&common::world(ctx), now), ..Default::default() };
    c.actor.community = community_party(ctx, id);
    if sc.reads("on_death", "records") {
        c.records = of(ctx, id, now);
    }
    match sc.hook("death", &c) {
        Ok(fx) => {
            for e in fx {
                if let Err(why) = apply(ctx, &c, e, now) {
                    log::warn!("on_death for {id}: {why}");
                }
            }
        },
        Err(e) => log::warn!("on_death for {id}: {e}"),
    }
}

/// A record the seed makes: parties by role, each a character's name or a community's
/// (docs/WORLD_RULES.md, "Seeded records").
#[derive(serde::Deserialize, Clone, Debug, Default)]
pub struct SeedRecord {
    pub kind: String,
    #[serde(default)]
    pub status: String,
    pub parties: std::collections::BTreeMap<String, SeedParty>,
    #[serde(default)]
    pub terms: serde_json::Map<String, serde_json::Value>,
}

#[derive(serde::Deserialize, Clone, Debug)]
#[serde(rename_all = "lowercase")]
pub enum SeedParty {
    Community(String),
    Person(String),
}

/// Make the seed's records once its people and communities exist. A record naming a party that
/// is not there is skipped and logged.
pub fn seed(ctx: &ReducerContext, records: &[SeedRecord], now: u64) {
    let mut made = 0;
    for r in records {
        let mut parties = Vec::new();
        for (role, p) in &r.parties {
            let id = match p {
                SeedParty::Community(n) => ctx.db.community().iter().find(|c| c.name.eq_ignore_ascii_case(n)).map(|c| COMMUNITY | c.id as u64),
                SeedParty::Person(n) => ctx.db.character().iter().find(|c| c.alive && c.name.eq_ignore_ascii_case(n)).map(|c| c.id as u64),
            };
            match id {
                Some(id) => parties.push((role.clone(), id)),
                None => {
                    log::warn!("seed record {}: no party {p:?} for {role}", r.kind);
                    parties.clear();
                    break;
                },
            }
        }
        if parties.is_empty() || living_rules::records::check_terms(&r.terms).is_err() {
            continue;
        }
        make(ctx, &r.kind, if r.status.is_empty() { "held" } else { &r.status }, 0, &parties, &r.terms, u64::MAX, now);
        made += 1;
    }
    if made > 0 {
        log::info!("seed: {made} records");
    }
}

thread_local! {
    /// Stances by (holder, toward) party: label and value, at a `record_clock.stances` count.
    static STANCES: RefCell<Option<(u64, HashMap<(u64, u64), (String, f32)>)>> = const { RefCell::new(None) };
}

/// How one side regards another, when a stance record says (docs/WORLD_RULES.md, "Standing").
pub fn stance(ctx: &ReducerContext, holder: u64, toward: u64) -> Option<(String, f32)> {
    if holder == 0 || toward == 0 {
        return None;
    }
    let rev = ctx.db.record_clock().id().find(0).map_or(0, |c| c.stances);
    STANCES.with(|s| {
        let fresh = s.borrow().as_ref().is_some_and(|(r, _)| *r == rev);
        if !fresh {
            let mut m = HashMap::new();
            let now = common::now_ms(ctx);
            for p in ctx.db.record_party().iter().filter(|p| p.role == living_rules::records::HOLDER) {
                if let Some(r) = ctx.db.record().id().find(p.record).filter(|r| r.open) {
                    if let Some((h, t, label, value)) = living_rules::records::stance(&facts(&r, parties(ctx, r.id), String::new(), now)) {
                        m.insert((h, t), (label, value));
                    }
                }
            }
            *s.borrow_mut() = Some((rev, m));
        }
        s.borrow().as_ref().and_then(|(_, m)| m.get(&(holder, toward)).cloned())
    })
}

/// My characters' records: one row per record and character of mine that is a party to it
/// (itself or through its community).
#[spacetimedb::view(accessor = my_records, public)]
pub fn my_records(ctx: &ViewContext) -> Vec<MyRecord> {
    let mut out = Vec::new();
    for c in ctx.db.character().controller().filter(ctx.sender()).filter(|c| c.alive) {
        let community = ctx.db.membership().member().find(c.id).map_or(0, |m| COMMUNITY | m.community as u64);
        for party in [c.id as u64, community].into_iter().filter(|p| *p != 0) {
            for p in ctx.db.record_party().party().filter(party) {
                let Some(r) = ctx.db.record().id().find(p.record) else { continue };
                let others: Vec<String> = ctx
                    .db
                    .record_party()
                    .record()
                    .filter(r.id)
                    .filter(|o| o.party != party)
                    .map(|o| if o.party >= COMMUNITY { format!("{}=c{}", o.role, o.party - COMMUNITY) } else { format!("{}={}", o.role, o.party) })
                    .collect();
                out.push(MyRecord { id: r.id, actor: c.id, role: p.role, kind: r.kind, status: r.status, open: r.open, terms: r.terms, others: others.join(","), made_ms: r.made_ms, due_ms: r.due_ms });
            }
        }
    }
    out
}
