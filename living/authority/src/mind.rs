//! Reducers used by LLM mind services. A mind may act only for characters it controls.
//! Graphs are validated here; untrusted model output never changes world facts directly.

use crate::act::{ACT, ORPHAN};
use crate::tables::*;
use crate::{common, perceive};
use spacetimedb::{ReducerContext, SpacetimeType, Table};

#[derive(SpacetimeType, Clone, Debug)]
pub struct ThoughtIn {
    pub kind: String,
    pub summary: String,
    pub detail: String,
    pub latency_ms: u32,
    pub tokens: u32,
    pub model: String,
    pub reference: String,
}

#[derive(SpacetimeType, Clone, Debug)]
pub struct PersonaIn {
    pub narrative: String,
    pub values: Vec<String>,
    pub goals: Vec<String>,
    pub traits: String,
    pub mood: String,
    /// Empty (no pastimes and no calling): the ones it had are kept.
    pub pastimes: Vec<String>,
    pub calling: String,
}

#[derive(SpacetimeType, Clone, Debug)]
pub struct RelationIn {
    pub other: u32,
    pub trust: f32,
    pub affinity: f32,
    pub label: String,
    pub note: String,
}

#[derive(SpacetimeType, Clone, Debug)]
pub struct BeliefIn {
    pub about: String,
    pub text: String,
    pub confidence: f32,
}

#[derive(SpacetimeType, Clone, Debug)]
pub struct JudgmentIn {
    pub key: String,
    pub value: f32,
    pub why: String,
}

/// One typed judgment from the mind service (see `Judged`).
#[derive(SpacetimeType, Clone, Debug)]
pub struct JudgedIn {
    pub q: String,
    pub value: f32,
    pub choice: String,
    /// How long it holds from now, in milliseconds (at most ten minutes).
    pub ttl_ms: u64,
}

#[derive(SpacetimeType, Clone, Debug)]
pub struct PlaceIn {
    pub name: String,
    pub x: f32,
    pub y: f32,
}

/// One attention cue as the mind projects it (docs/ATTENTION.md; the `Cue` table).
#[derive(SpacetimeType, Clone, Debug)]
pub struct CueIn {
    /// `stance:<key>`, `project:<key>` or `goal:<key>`: what it serves.
    pub for_key: String,
    pub why: String,
    pub who_id: u32,
    pub who: String,
    pub doing: String,
    /// The phase of a move (`winding up`, …): refused until the authority perceives phases.
    pub phase: String,
    pub thing: String,
    pub at: String,
    pub within: f32,
    pub near_me: f32,
    /// The thought that wrote it (its journal reference).
    pub source: String,
}

#[derive(SpacetimeType, Clone, Debug)]
pub struct MindUpdate {
    pub persona: Option<PersonaIn>,
    pub relations: Vec<RelationIn>,
    /// Replaces the belief projection when present.
    pub beliefs: Option<Vec<BeliefIn>>,
    pub judgments: Vec<JudgmentIn>,
    pub places: Vec<PlaceIn>,
    pub thought: Option<ThoughtIn>,
    /// The relations, judgments and places given are the complete current set (projected
    /// from the mind); rows not among them are removed.
    pub replace: bool,
    /// The complete set of attention cues (docs/ATTENTION.md), replacing the actor's when
    /// present; `None` leaves them as they are.
    pub cues: Option<Vec<CueIn>>,
}

const MAX_THOUGHTS: usize = 60;

fn authorize(ctx: &ReducerContext, actor: u32) -> Result<Character, String> {
    let c = ctx.db.character().id().find(actor).ok_or("no such character")?;
    if c.controller != ctx.sender() {
        return Err("not your character".into());
    }
    Ok(c)
}

/// Projections of a mind: by the character's controller, or by the world's mind service
/// (the admin) for a character a person plays, whose lived experience it internalizes
/// (docs/PLAYER_MEMORY.md): its relations, judgments, places and beliefs, and the identity
/// the service infers from what it lived.
fn authorize_projection(ctx: &ReducerContext, actor: u32) -> Result<Character, String> {
    let c = ctx.db.character().id().find(actor).ok_or("no such character")?;
    if c.controller == ctx.sender() {
        return Ok(c);
    }
    let human = (!c.ai && c.controller != ctx.database_identity()) || crate::presence::played(ctx, actor);
    if human && ctx.sender() == common::world(ctx).admin {
        return Ok(c);
    }
    Err("not your character".into())
}

fn clip(s: &str, n: usize) -> String {
    if s.len() <= n {
        return s.to_string();
    }
    let mut end = n;
    while !s.is_char_boundary(end) {
        end -= 1;
    }
    s[..end].to_string()
}

pub fn add_thought(ctx: &ReducerContext, actor: u32, t: ThoughtIn, now: u64) {
    ctx.db.thought().insert(Thought {
        id: 0,
        actor,
        at_ms: now,
        kind: clip(&t.kind, 32),
        summary: clip(&t.summary, 600),
        detail: clip(&t.detail, 16_000),
        latency_ms: t.latency_ms,
        tokens: t.tokens,
        model: clip(&t.model, 64),
        reference: clip(&t.reference, 64),
    });
    let mut ids: Vec<u64> = ctx.db.thought().actor().filter(actor).map(|t| t.id).collect();
    if ids.len() > MAX_THOUGHTS {
        ids.sort_unstable();
        for id in &ids[..ids.len() - MAX_THOUGHTS] {
            ctx.db.thought().id().delete(*id);
        }
    }
}

/// Install a validated graph; the current activity is kept as an orphan the new graph may adopt.
/// A routine as a mind sends it: its name and graph (empty graph = retire it).
#[derive(SpacetimeType, Clone, Debug)]
pub struct RoutineIn {
    pub name: String,
    pub graph: String,
}

/// Most routines a character keeps.
pub const MAX_ROUTINES: usize = 40;

/// Add, change or retire routines; the character's graph is recompiled with them.
pub fn set_routines(ctx: &ReducerContext, actor: u32, routines: &[RoutineIn], source: &str, now: u64) -> Result<Vec<String>, String> {
    let kind = ctx.db.character().id().find(actor).map(|c| c.kind).unwrap_or_default();
    let sp = common::species(&kind);
    let mut notes = Vec::new();
    for r in routines {
        let name = living_rules::normalize::routine_name(&r.name);
        if name.is_empty() {
            continue;
        }
        let existing = ctx.db.routine().actor().filter(actor).find(|x| living_rules::normalize::routine_name(&x.name) == name);
        if r.graph.trim().is_empty() {
            if let Some(x) = existing {
                ctx.db.routine_stat().id().delete(x.id);
                ctx.db.routine().id().delete(x.id);
                notes.push(format!("retired {name}"));
            }
            continue;
        }
        let g = match living_rules::graph::parse(&r.graph) {
            Ok(g) => g,
            Err(e) => {
                notes.push(format!("{name}: {e}"));
                continue;
            }
        };
        if let Some(sp) = &sp {
            if let Some(bad) = living_rules::graph::skills_used(&g.root).into_iter().find(|s| if s == "say" { !sp.speaks } else { !sp.allows(s) }) {
                notes.push(format!("{name}: a {kind} cannot {bad}"));
                continue;
            }
        }
        match existing {
            Some(mut x) => {
                // How a routine has gone describes this version: a new one starts afresh.
                ctx.db.routine_stat().id().delete(x.id);
                x.name = name.clone();
                x.graph = g.to_json();
                x.revision += 1;
                x.source = source.into();
                x.updated_ms = now;
                ctx.db.routine().id().update(x);
                notes.push(format!("revised {name}"));
            }
            None => {
                if ctx.db.routine().actor().filter(actor).count() >= MAX_ROUTINES {
                    notes.push(format!("{name}: already {MAX_ROUTINES} routines; retire one first"));
                    continue;
                }
                ctx.db.routine().insert(Routine { id: 0, actor, name: name.clone(), graph: g.to_json(), revision: 1, source: source.into(), updated_ms: now });
                notes.push(format!("new {name}"));
            }
        }
    }
    // Recompile the character's graph with its routines.
    if let Some(b) = ctx.db.brain().id().find(actor) {
        let _ = set_graph(ctx, actor, &b.graph, &b.plan, &b.source, now);
    }
    Ok(notes)
}

/// The top level (the desires that call routines) as a rework's item.
pub const TOP_LEVEL: &str = "top level";

/// How the current version of a routine (or the top level) has gone, for the rework rules.
pub fn routine_facts(ctx: &ReducerContext, actor: u32, name: &str, now: u64) -> living_rules::script::RoutineFacts {
    let name = living_rules::normalize::routine_name(name);
    if name == TOP_LEVEL {
        return match ctx.db.brain().id().find(actor) {
            Some(b) => living_rules::script::RoutineFacts { exists: true, ok: 0, failed: 0, changed_s: now.saturating_sub(b.installed_ms) as f32 / 1000.0 },
            None => Default::default(),
        };
    }
    match ctx.db.routine().actor().filter(actor).find(|r| living_rules::normalize::routine_name(&r.name) == name) {
        Some(r) => {
            let st = ctx.db.routine_stat().id().find(r.id);
            living_rules::script::RoutineFacts {
                exists: true,
                ok: st.as_ref().map_or(0, |s| s.ok),
                failed: st.as_ref().map_or(0, |s| s.failed),
                changed_s: now.saturating_sub(r.updated_ms) as f32 / 1000.0,
            }
        }
        None => Default::default(),
    }
}

/// Carry out a finished rework: the routine (or the top level) becomes the new version, or
/// is retired. Returns what the person feels came of it.
pub fn rework(ctx: &ReducerContext, actor: u32, name: &str, graph: &str, now: u64) -> String {
    let name = living_rules::normalize::routine_name(name);
    if name == living_rules::normalize::routine_name(living_rules::graph::PLAN_ROUTINE) {
        return "Your plan is what you decide, not a habit to rework.".into();
    }
    if name == TOP_LEVEL {
        if graph == "retire" {
            return "You cannot live without any ways at all.".into();
        }
        let person = ctx.db.character().id().find(actor).map_or(false, |c| c.kind == "person");
        if person && !graph.trim_start().starts_with("{\"desires\"") {
            return "You could not settle on a new way of living: your top level has to weigh desires.".into();
        }
        let plan = ctx.db.brain().id().find(actor).map(|b| b.plan).unwrap_or_default();
        return match set_graph(ctx, actor, graph, &plan, "mind", now) {
            Ok(_) => "You reworked how you live: what you weigh and how.".into(),
            Err(e) => format!("You could not settle on a new way of living: {e}"),
        };
    }
    let edit = RoutineIn { name: name.clone(), graph: if graph == "retire" { String::new() } else { graph.to_string() } };
    match set_routines(ctx, actor, &[edit], "mind", now) {
        Ok(notes) => match notes.first() {
            Some(n) if n.contains(": ") => format!("You could not rework \"{name}\": {}", n.split_once(": ").map(|x| x.1).unwrap_or(n)),
            Some(n) if n.starts_with("revised") => format!("You reworked \"{name}\": now see how the new way goes."),
            Some(n) if n.starts_with("retired") => format!("You gave up \"{name}\"."),
            Some(_) => format!("You worked out a new way: \"{name}\"."),
            None => format!("There was no \"{name}\" to give up."),
        },
        Err(e) => format!("You could not rework \"{name}\": {e}"),
    }
}

/// A mind edits its character's routines (one or a few at a time).
#[spacetimedb::reducer]
pub fn mind_routines(ctx: &ReducerContext, actor: u32, routines: Vec<RoutineIn>) -> Result<(), String> {
    authorize(ctx, actor)?;
    let now = common::now_ms(ctx);
    let notes = set_routines(ctx, actor, &routines, "mind", now)?;
    let rejected: Vec<&String> = notes.iter().filter(|n| n.contains(": ")).collect();
    if !rejected.is_empty() {
        if let Some(c) = ctx.db.character().id().find(actor) {
            let at = ctx.db.body().id().find(actor).map(|b| common::pos(&b, now)).unwrap_or((0.0, 0.0));
            perceive::percept(ctx, &c, now, "self", actor, 0, at, format!("Some of your routines could not be kept: {}", rejected.iter().map(|s| s.as_str()).collect::<Vec<_>>().join("; ")), 0.5);
        }
    }
    Ok(())
}

pub fn set_graph(ctx: &ReducerContext, actor: u32, graph: &str, plan: &str, source: &str, now: u64) -> Result<u32, String> {
    let g = living_rules::graph::parse(graph)?;
    let kind = ctx.db.character().id().find(actor).map(|c| c.kind).unwrap_or_default();
    // The body decides what a graph may ask of it.
    if let Some(sp) = common::species(&kind) {
        for skill in living_rules::graph::skills_used(&g.root) {
            if skill == "say" && !sp.speaks || skill != "say" && !sp.allows(&skill) {
                return Err(format!("a {kind} cannot {skill}"));
            }
        }
    }
    let revision = ctx.db.brain().id().find(actor).map(|b| b.revision + 1).unwrap_or(1);
    let row = Brain { id: actor, graph: g.to_json(), revision, plan: clip(plan, 600), source: source.into(), installed_ms: now };
    if ctx.db.brain().id().find(actor).is_some() {
        ctx.db.brain().id().update(row);
    } else {
        ctx.db.brain().insert(row);
    }
    if let Some(mut st) = ctx.db.mind_state().id().find(actor) {
        st.revision = revision;
        st.cursors.clear();
        st.marks.retain(|m| m.node >= 0xD000 && m.node < crate::brain::REFLECT_MARK);
        st.last = None;
        st.active.clear();
        st.fails = 0;
        if source == "mind" {
            st.deliberated_ms = now;
        }
        ctx.db.mind_state().id().update(st);
    }
    if let Some(mut a) = ctx.db.activity().id().find(actor) {
        // A deliberate act in progress stays the act it is; graph work becomes an orphan the
        // new graph may adopt.
        if a.node != ACT {
            a.node = ORPHAN;
        }
        a.revision = revision;
        ctx.db.activity().id().update(a);
    }
    common::wake(ctx, actor);
    Ok(revision)
}

/// Remove what the deliberation that read the request as of `seen_ms` considered. Reasons
/// that arrived later stay pending, except, when a new plan is installed (`new_plan`), those
/// about the old plan failing that piled up while the mind was thinking (they re-triggered
/// thinking at once, every few seconds). A reason the prompt contained never stays: before
/// 2026-11-11 it did whenever anything arrived during the call, and plan-finished churn kept
/// one feeling the reason of dozens of thoughts.
fn clear_deliberation(ctx: &ReducerContext, actor: u32, seen_ms: u64, new_plan: bool) {
    if let Some(mut d) = ctx.db.deliberation().actor().find(actor) {
        let rest = if d.updated_ms <= seen_ms { None } else { living_rules::reasons::consume(&d.reason, &d.arrived, seen_ms, new_plan) };
        match rest {
            None => {
                ctx.db.deliberation().actor().delete(actor);
            }
            Some((reason, arrived)) => {
                d.reason = reason;
                d.arrived = arrived;
                ctx.db.deliberation().actor().update(d);
            }
        }
    }
}

/// Deliver a deliberation result: a new behavior graph, optional speech and a thought log entry.
#[spacetimedb::reducer]
pub fn mind_install(ctx: &ReducerContext, actor: u32, graph: String, plan: String, say: String, say_to: u32, seen_ms: u64, thought: ThoughtIn) -> Result<(), String> {
    let c = authorize(ctx, actor)?;
    if !c.alive {
        ctx.db.deliberation().actor().delete(actor);
        return Err("character is dead".into());
    }
    let now = common::now_ms(ctx);
    clear_deliberation(ctx, actor, seen_ms, true);
    if let Err(e) = set_graph(ctx, actor, &graph, &plan, "mind", now) {
        add_thought(ctx, actor, ThoughtIn { kind: "error".into(), summary: format!("rejected graph: {e}"), ..thought }, now);
        return Err(e);
    }
    add_thought(ctx, actor, thought, now);
    if !say.trim().is_empty() {
        let _ = crate::speech::speak(ctx, actor, &say, say_to, "say", now);
    }
    Ok(())
}

/// Answer without changing behavior: speak, log the thought, clear what was considered.
/// A conversation turn (`thought.kind == "talk"`) is not a deliberation: it leaves pending
/// deliberation reasons and the deliberation clock alone, so talking never displaces or
/// postpones thinking about what to do.
#[spacetimedb::reducer]
pub fn mind_say(ctx: &ReducerContext, actor: u32, say: String, say_to: u32, way: String, seen_ms: u64, thought: ThoughtIn) -> Result<(), String> {
    let c = authorize(ctx, actor)?;
    if !c.alive {
        return Err("character is dead".into());
    }
    let now = common::now_ms(ctx);
    if thought.kind != "talk" {
        clear_deliberation(ctx, actor, seen_ms, true);
        if let Some(mut st) = ctx.db.mind_state().id().find(actor) {
            st.deliberated_ms = now;
            ctx.db.mind_state().id().update(st);
        }
    }
    add_thought(ctx, actor, thought, now);
    if !say.trim().is_empty() {
        crate::speech::speak(ctx, actor, &say, say_to, &way, now)?;
    }
    Ok(())
}

/// Deliberate acts decided by a mind (in a deliberation or a conversation turn): each a
/// `do` node (`{"do": "conceive", "target": {"id": 6}}`), carried out once, in order, by the
/// same skill rules as graph leaves, outside the behavior graph. The outcome of each comes
/// back as an experience. `source` says where it was decided (e.g. "deliberate", "talk").
#[spacetimedb::reducer]
pub fn mind_act(ctx: &ReducerContext, actor: u32, acts: Vec<String>, source: String) -> Result<(), String> {
    let c = authorize(ctx, actor)?;
    if !c.alive {
        return Err("character is dead".into());
    }
    let now = common::now_ms(ctx);
    let notes = crate::acts::submit(ctx, actor, &acts, &source, false, now);
    log::debug!("{} decides: {}", c.name, notes.join("; "));
    Ok(())
}

/// Give up on a pending deliberation (e.g. model failure), logging why.
#[spacetimedb::reducer]
pub fn mind_skip(ctx: &ReducerContext, actor: u32, seen_ms: u64, thought: ThoughtIn) -> Result<(), String> {
    authorize(ctx, actor)?;
    let now = common::now_ms(ctx);
    clear_deliberation(ctx, actor, seen_ms, false);
    if let Some(mut st) = ctx.db.mind_state().id().find(actor) {
        st.deliberated_ms = now;
        ctx.db.mind_state().id().update(st);
    }
    add_thought(ctx, actor, thought, now);
    Ok(())
}

/// Cache judgments the character's mind refreshed (Jev). Upserted by question; a character
/// holds at most `JUDGED_PER_ACTOR`. Only the character's controller may write them.
#[spacetimedb::reducer]
pub fn mind_judged(ctx: &ReducerContext, actor: u32, items: Vec<JudgedIn>) -> Result<(), String> {
    authorize(ctx, actor)?;
    let now = common::now_ms(ctx);
    for j in items.into_iter().take(JUDGED_PER_ACTOR) {
        let q = j.q.trim().to_lowercase();
        if q.is_empty() || q.len() > 64 || !j.value.is_finite() {
            return Err("judged: q must be 1..=64 bytes and value finite".into());
        }
        let expires_ms = now + j.ttl_ms.min(600_000);
        let choice: String = j.choice.chars().take(64).collect();
        match ctx.db.judged().actor().filter(actor).find(|x| x.q == q) {
            Some(mut row) => {
                row.value = j.value;
                row.choice = choice;
                row.expires_ms = expires_ms;
                row.updated_ms = now;
                ctx.db.judged().id().update(row);
            }
            None => {
                if ctx.db.judged().actor().filter(actor).count() >= JUDGED_PER_ACTOR {
                    return Err(format!("judged: at most {JUDGED_PER_ACTOR} per character"));
                }
                ctx.db.judged().insert(Judged { id: 0, actor, q, value: j.value, choice, expires_ms, updated_ms: now });
            }
        }
    }
    Ok(())
}

/// Record that the mind has integrated this character's experiences up to `upto`; the
/// integrated experiences are removed (the inbox is transactional).
#[spacetimedb::reducer]
pub fn mind_consolidated(ctx: &ReducerContext, actor: u32, upto: u64) -> Result<(), String> {
    authorize(ctx, actor)?;
    let now = common::now_ms(ctx);
    // A character a person plays keeps its rows: the person sees what it lived while they
    // were away (its window still holds only the last 400).
    if !crate::presence::played(ctx, actor) {
        let done: Vec<u64> = ctx.db.experience().observer().filter(actor).filter(|e| e.id <= upto).map(|e| e.id).collect();
        for id in done {
            ctx.db.experience().id().delete(id);
        }
        // Who heard the lines it integrated goes with them.
        for line in ctx.db.line_heard().speaker().filter(actor).filter(|h| h.line <= upto).map(|h| h.line).collect::<Vec<_>>() {
            crate::speech::forget_line(ctx, line);
        }
    }
    let row = MindCursor { actor, upto, updated_ms: now };
    match ctx.db.mind_cursor().actor().find(actor) {
        Some(c) if c.upto >= upto => {}
        Some(_) => {
            ctx.db.mind_cursor().actor().update(row);
        }
        None => {
            ctx.db.mind_cursor().insert(row);
        }
    }
    Ok(())
}

/// Project consolidated mind state: persona, relations, beliefs, judgments, places.
#[spacetimedb::reducer]
pub fn mind_update(ctx: &ReducerContext, actor: u32, update: MindUpdate) -> Result<(), String> {
    let who = authorize_projection(ctx, actor)?;
    let now = common::now_ms(ctx);
    if update.replace {
        let keep: Vec<u32> = update.relations.iter().map(|r| r.other).collect();
        for r in ctx.db.relation().actor().filter(actor).filter(|r| !keep.contains(&r.other)).map(|r| r.id).collect::<Vec<_>>() {
            ctx.db.relation().id().delete(r);
        }
        let keep: Vec<String> = update.judgments.iter().map(|j| j.key.trim().to_lowercase()).collect();
        for j in ctx.db.judgment().actor().filter(actor).filter(|j| !keep.contains(&j.key.to_lowercase())).map(|j| j.id).collect::<Vec<_>>() {
            ctx.db.judgment().id().delete(j);
        }
        // Given places (world facts its starting ways walk to: work, square, a known way's
        // stages) stay whether or not the mind names them.
        let keep: Vec<String> = update.places.iter().map(|p| p.name.trim().to_lowercase()).collect();
        for p in ctx.db.place().actor().filter(actor).filter(|p| !p.given && !keep.contains(&p.name.to_lowercase())).map(|p| p.id).collect::<Vec<_>>() {
            ctx.db.place().id().delete(p);
        }
    }
    if let Some(p) = update.persona {
        let old = ctx.db.persona().id().find(actor);
        let version = old.as_ref().map(|p| p.version + 1).unwrap_or(1);
        let keep = p.pastimes.is_empty() && p.calling.trim().is_empty();
        let (pastimes, calling) = match (&old, keep) {
            (Some(o), true) => (o.pastimes.clone(), o.calling.clone()),
            _ => (p.pastimes.iter().take(6).map(|v| clip(v, 120)).collect(), clip(&p.calling, 200)),
        };
        let row = Persona {
            id: actor,
            narrative: clip(&p.narrative, 2_000),
            values: p.values.iter().take(8).map(|v| clip(v, 120)).collect(),
            goals: p.goals.iter().take(8).map(|v| clip(v, 200)).collect(),
            traits: clip(&p.traits, 1_000),
            mood: clip(&p.mood, 120),
            version,
            updated_ms: now,
            pastimes,
            calling,
        };
        common::invalidate_traits(ctx, actor);
        if ctx.db.persona().id().find(actor).is_some() {
            ctx.db.persona().id().update(row);
        } else {
            ctx.db.persona().insert(row);
        }
    }
    let me = ctx.db.character().id().find(actor);
    for r in update.relations.into_iter().take(32) {
        let Some(other) = ctx.db.character().id().find(r.other).filter(|_| r.other != actor) else { continue };
        // "Stranger" is not a feeling about someone whose name one knows (family, one's
        // community, an introduction: `perception::knows_name`): a mind that took a neighbour
        // too far away to make out for a stranger does not write it (far-label, docs/STRANGERS.md).
        if r.label.to_lowercase().contains("stranger") && me.as_ref().is_some_and(|m| crate::perception::knows_name(ctx, m, &other)) {
            log::info!("mind_update #{actor}: relation \"{}\" to #{} not written: #{actor} knows their name", r.label, r.other);
            continue;
        }
        let existing = ctx.db.relation().by_pair().filter((actor, r.other)).next();
        let row = Relation {
            id: existing.as_ref().map(|e| e.id).unwrap_or(0),
            actor,
            other: r.other,
            trust: r.trust.clamp(-100.0, 100.0),
            affinity: r.affinity.clamp(-100.0, 100.0),
            label: clip(&r.label, 60),
            note: clip(&r.note, 300),
            updated_ms: now,
        };
        if existing.is_some() {
            ctx.db.relation().id().update(row);
        } else {
            ctx.db.relation().insert(row);
        }
    }
    if let Some(beliefs) = update.beliefs {
        for id in ctx.db.belief().actor().filter(actor).map(|b| b.id).collect::<Vec<_>>() {
            ctx.db.belief().id().delete(id);
        }
        for b in beliefs.into_iter().take(40) {
            ctx.db.belief().insert(Belief { id: 0, actor, about: clip(&b.about, 80), text: clip(&b.text, 300), confidence: b.confidence.clamp(0.0, 1.0), updated_ms: now });
        }
    }
    for j in update.judgments.into_iter().take(32) {
        let key = clip(j.key.trim(), 64);
        if key.is_empty() {
            continue;
        }
        let existing = ctx.db.judgment().actor().filter(actor).find(|x| x.key.eq_ignore_ascii_case(&key));
        let row = Judgment { id: existing.as_ref().map(|e| e.id).unwrap_or(0), actor, key, value: j.value.clamp(0.0, 1.0), why: clip(&j.why, 300), updated_ms: now };
        if existing.is_some() {
            ctx.db.judgment().id().update(row);
        } else {
            ctx.db.judgment().insert(row);
        }
    }
    for p in update.places.into_iter().take(16) {
        let name = clip(p.name.trim(), 48);
        let w = common::world(ctx);
        if name.is_empty() || !(0.0..w.width as f32).contains(&p.x) || !(0.0..w.height as f32).contains(&p.y) {
            continue;
        }
        let existing = ctx.db.place().actor().filter(actor).find(|x| x.name.eq_ignore_ascii_case(&name));
        let row = Place { id: existing.as_ref().map(|e| e.id).unwrap_or(0), actor, name, x: p.x, y: p.y, given: existing.as_ref().is_some_and(|e| e.given) };
        if existing.is_some() {
            ctx.db.place().id().update(row);
        } else {
            ctx.db.place().insert(row);
        }
    }
    // A mind keeps at most 24 places of its own, beside the given ones.
    if ctx.db.place().actor().filter(actor).filter(|p| !p.given).count() > 24 {
        let mut ids: Vec<u64> = ctx.db.place().actor().filter(actor).filter(|p| !p.given).map(|p| p.id).collect();
        ids.sort_unstable();
        for id in &ids[..ids.len() - 24] {
            ctx.db.place().id().delete(*id);
        }
    }
    // Only a mind keeps attention cues: a character a person plays sees with the player's eyes,
    // so cues written for one (its player memory, or the player's own call) are not kept.
    if let Some(cues) = update.cues {
        let played = !who.ai || crate::presence::played(ctx, actor);
        set_cues(ctx, actor, if played { Vec::new() } else { cues }, now);
    }
    if let Some(t) = update.thought {
        add_thought(ctx, actor, t, now);
    }
    Ok(())
}

/// Replace `actor`'s attention cues with `cues` (at most `CUES_PER_ACTOR`, the first ones kept).
/// A cue the world cannot watch for is kept with its reason in `refused` and never matched, so
/// the mind is told why (its prompt lists the set) and the inspector shows it. A cue that is
/// unchanged keeps its row, its fires and its cooldowns.
pub fn set_cues(ctx: &ReducerContext, actor: u32, cues: Vec<CueIn>, now: u64) {
    let old: Vec<Cue> = ctx.db.cue().actor().filter(actor).collect();
    let mut kept: Vec<u64> = Vec::new();
    for c in cues.into_iter().take(CUES_PER_ACTOR) {
        let row = Cue {
            id: 0,
            actor,
            for_key: clip(c.for_key.trim(), 80),
            why: clip(c.why.trim(), 160),
            who_id: c.who_id,
            who: clip(c.who.trim(), 40).to_lowercase(),
            doing: clip(c.doing.trim(), 40).to_lowercase(),
            thing: clip(c.thing.trim(), 40).to_lowercase(),
            at: clip(c.at.trim(), 48),
            within: if c.within > 0.0 { c.within.min(48.0) } else { 20.0 },
            near_me: c.near_me.clamp(0.0, 256.0),
            refused: String::new(),
            fired: Vec::new(),
            fires: 0,
            set_ms: now,
            source: clip(&c.source, 120),
        };
        let refused = cue_refusal(ctx, actor, &row, c.phase.trim());
        let row = Cue { refused, ..row };
        let same = |o: &Cue| o.for_key == row.for_key && o.who_id == row.who_id && o.who == row.who && o.doing == row.doing && o.thing == row.thing && o.at.eq_ignore_ascii_case(&row.at) && o.within == row.within && o.near_me == row.near_me;
        match old.iter().find(|o| same(o) && !kept.contains(&o.id)) {
            Some(o) => {
                kept.push(o.id);
                if o.why != row.why || o.refused != row.refused || o.source != row.source {
                    ctx.db.cue().id().update(Cue { id: o.id, fired: o.fired.clone(), fires: o.fires, set_ms: o.set_ms, ..row });
                }
            }
            None => {
                let r = ctx.db.cue().insert(row);
                kept.push(r.id);
            }
        }
    }
    for o in old.into_iter().filter(|o| !kept.contains(&o.id)) {
        ctx.db.cue().id().delete(o.id);
    }
}

/// Why the world cannot watch for this cue (empty: it can). Only what perception reports can
/// be watched for, by type: a person or creature, what it is doing, a resource or structure,
/// near one of one's own places.
fn cue_refusal(ctx: &ReducerContext, actor: u32, c: &Cue, phase: &str) -> String {
    let sc = common::scripts(ctx);
    let creature = c.who_id != 0 || !c.who.is_empty();
    if !phase.is_empty() {
        return format!("the phase of a move (\"{phase}\") is not something one can make out yet");
    }
    if !c.for_key.starts_with("stance:") && !c.for_key.starts_with("project:") && !c.for_key.starts_with("goal:") {
        return "it serves no stance, project or goal".into();
    }
    if creature && !c.thing.is_empty() {
        return "it watches for a creature and a thing at once".into();
    }
    if !creature && c.thing.is_empty() && c.at.is_empty() {
        return "it names nothing to watch for".into();
    }
    if !c.doing.is_empty() && !creature {
        return "what is being done needs someone doing it".into();
    }
    if c.who_id != 0 {
        if c.who_id == actor {
            return "one does not watch for oneself".into();
        }
        let Some(other) = ctx.db.character().id().find(c.who_id) else { return format!("there is no one #{}", c.who_id) };
        let met = ctx.db.familiar().by_actor_thing().filter((actor, FAM_CREATURE | c.who_id as u64)).next().is_some()
            || ctx.db.relation().by_pair().filter((actor, c.who_id)).next().is_some()
            || ctx.db.character().id().find(actor).is_some_and(|me| crate::perception::knows_name(ctx, &me, &other));
        if !met {
            return format!("you have never seen #{}", c.who_id);
        }
    }
    if !c.who.is_empty() && c.who != "unknown" && !living_rules::catalog::CREATURES.iter().any(|k| *k == c.who) {
        return format!("\"{}\" is not a kind of creature", c.who);
    }
    if !c.doing.is_empty() && !sc.skills().has(&c.doing) {
        return format!("\"{}\" is not something one does", c.doing);
    }
    if !c.thing.is_empty() && !sc.skills().resources.iter().chain(sc.skills().structures.iter()).any(|k| k.name == c.thing) {
        return format!("\"{}\" is not a kind of thing one sees", c.thing);
    }
    if !c.at.is_empty() && !ctx.db.place().actor().filter(actor).any(|p| p.name.eq_ignore_ascii_case(&c.at)) {
        return format!("you know no place called \"{}\"", c.at);
    }
    String::new()
}
