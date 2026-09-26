//! Reducers used by LLM mind services. A mind may act only for characters it controls.
//! Graphs are validated here; untrusted model output never changes world facts directly.

use crate::act::ORPHAN;
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

#[derive(SpacetimeType, Clone, Debug)]
pub struct PlaceIn {
    pub name: String,
    pub x: f32,
    pub y: f32,
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
}

const MAX_THOUGHTS: usize = 60;

fn authorize(ctx: &ReducerContext, actor: u32) -> Result<Character, String> {
    let c = ctx.db.character().id().find(actor).ok_or("no such character")?;
    if c.controller != ctx.sender() {
        return Err("not your character".into());
    }
    Ok(c)
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
/// Body reflexes placed ahead of every mind-written graph for people. They keep a
/// character alive when its plan neglects the body; the mind sees them in its outline.
pub const REFLEXES: &str = r#"[
  {"if": {"cond": {"all": [{"health": {"below": 30}}, {"hurt_within": 5}]}, "then": {"do": {"skill": "flee", "target": "attacker"}}}},
  {"if": {"cond": {"all": [{"hunger": {"above": 65}}, {"has": {"item": "food"}}, {"not": {"threatened": true}}, {"not": {"hurt_within": 8}}]}, "then": {"do": {"skill": "eat", "item": "food"}}}},
  {"if": {"cond": {"hunger": {"above": 88}}, "then": {"first": [
    {"do": {"skill": "take", "target": {"nearest": "storage"}, "item": "food"}},
    {"do": {"skill": "gather", "target": {"nearest": "berry_bush"}}},
    {"do": {"skill": "goto", "target": "home"}}
  ]}}},
  {"if": {"cond": {"all": [{"energy": {"below": 12}}, {"not": {"threatened": true}}, {"not": {"hurt_within": 10}}]}, "then": {"do": {"skill": "sleep"}}}},
  {"if": {"cond": {"all": [{"night": true}, {"energy": {"below": 35}}, {"not": {"hurt_within": 10}},
      {"any": [{"near": {"target": {"nearest": "campfire"}, "within": 3}}, {"near": {"target": {"nearest": "shelter"}, "within": 2}}]}]},
    "then": {"do": {"skill": "sleep"}}}}
]"#;

/// Wrap a graph with its species' reflex layer (idempotent: an existing layer is replaced).
fn with_reflexes(g: living_rules::graph::Graph, kind: &str) -> Result<living_rules::graph::Graph, String> {
    use living_rules::graph::{Composite, Node};
    let inner = match g.root {
        Node::First(c) if c.label.as_deref() == Some("reflexes") => c.children.into_iter().last().ok_or("empty reflex layer")?,
        other => other,
    };
    let reflexes = match common::species(kind) {
        Some(sp) if !sp.reflexes.is_empty() => serde_json::Value::Array(sp.reflexes),
        _ => serde_json::from_str(REFLEXES).map_err(|e| e.to_string())?,
    };
    let mut children: Vec<Node> = serde_json::from_value(reflexes).map_err(|e| e.to_string())?;
    children.push(inner);
    living_rules::graph::validate(Node::First(Composite { label: Some("reflexes".into()), children }))
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
    let g = if source == "mind" { with_reflexes(g, &kind)? } else { g };
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
        st.marks.retain(|m| m.node >= 0xD000);
        st.last = None;
        st.active.clear();
        st.fails = 0;
        if source == "mind" {
            st.deliberated_ms = now;
        }
        ctx.db.mind_state().id().update(st);
    }
    if let Some(mut a) = ctx.db.activity().id().find(actor) {
        a.node = ORPHAN;
        a.revision = revision;
        ctx.db.activity().id().update(a);
    }
    common::wake(ctx, actor);
    Ok(revision)
}

/// Remove the pending deliberation unless reasons arrived after `seen_ms`.
fn clear_deliberation(ctx: &ReducerContext, actor: u32, seen_ms: u64) {
    if let Some(d) = ctx.db.deliberation().actor().find(actor) {
        if d.updated_ms <= seen_ms {
            ctx.db.deliberation().actor().delete(actor);
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
    clear_deliberation(ctx, actor, seen_ms);
    if let Err(e) = set_graph(ctx, actor, &graph, &plan, "mind", now) {
        add_thought(ctx, actor, ThoughtIn { kind: "error".into(), summary: format!("rejected graph: {e}"), ..thought }, now);
        return Err(e);
    }
    add_thought(ctx, actor, thought, now);
    if !say.trim().is_empty() {
        let _ = perceive::speak(ctx, actor, &say, say_to, now);
    }
    Ok(())
}

/// Answer without changing behavior: speak, log the thought, clear what was considered.
#[spacetimedb::reducer]
pub fn mind_say(ctx: &ReducerContext, actor: u32, say: String, say_to: u32, seen_ms: u64, thought: ThoughtIn) -> Result<(), String> {
    let c = authorize(ctx, actor)?;
    if !c.alive {
        return Err("character is dead".into());
    }
    let now = common::now_ms(ctx);
    clear_deliberation(ctx, actor, seen_ms);
    if let Some(mut st) = ctx.db.mind_state().id().find(actor) {
        st.deliberated_ms = now;
        ctx.db.mind_state().id().update(st);
    }
    add_thought(ctx, actor, thought, now);
    if !say.trim().is_empty() {
        perceive::speak(ctx, actor, &say, say_to, now)?;
    }
    Ok(())
}

/// Give up on a pending deliberation (e.g. model failure), logging why.
#[spacetimedb::reducer]
pub fn mind_skip(ctx: &ReducerContext, actor: u32, seen_ms: u64, thought: ThoughtIn) -> Result<(), String> {
    authorize(ctx, actor)?;
    let now = common::now_ms(ctx);
    clear_deliberation(ctx, actor, seen_ms);
    if let Some(mut st) = ctx.db.mind_state().id().find(actor) {
        st.deliberated_ms = now;
        ctx.db.mind_state().id().update(st);
    }
    add_thought(ctx, actor, thought, now);
    Ok(())
}

/// Record that the mind has integrated this character's experiences up to `upto`; the
/// integrated experiences are removed (the inbox is transactional).
#[spacetimedb::reducer]
pub fn mind_consolidated(ctx: &ReducerContext, actor: u32, upto: u64) -> Result<(), String> {
    authorize(ctx, actor)?;
    let now = common::now_ms(ctx);
    let done: Vec<u64> = ctx.db.experience().observer().filter(actor).filter(|e| e.id <= upto).map(|e| e.id).collect();
    for id in done {
        ctx.db.experience().id().delete(id);
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
    authorize(ctx, actor)?;
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
        let keep: Vec<String> = update.places.iter().map(|p| p.name.trim().to_lowercase()).collect();
        for p in ctx.db.place().actor().filter(actor).filter(|p| !keep.contains(&p.name.to_lowercase())).map(|p| p.id).collect::<Vec<_>>() {
            ctx.db.place().id().delete(p);
        }
    }
    if let Some(p) = update.persona {
        let version = ctx.db.persona().id().find(actor).map(|p| p.version + 1).unwrap_or(1);
        let row = Persona {
            id: actor,
            narrative: clip(&p.narrative, 2_000),
            values: p.values.iter().take(8).map(|v| clip(v, 120)).collect(),
            goals: p.goals.iter().take(8).map(|v| clip(v, 200)).collect(),
            traits: clip(&p.traits, 1_000),
            mood: clip(&p.mood, 120),
            version,
            updated_ms: now,
        };
        if ctx.db.persona().id().find(actor).is_some() {
            ctx.db.persona().id().update(row);
        } else {
            ctx.db.persona().insert(row);
        }
    }
    for r in update.relations.into_iter().take(32) {
        if r.other == actor || ctx.db.character().id().find(r.other).is_none() {
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
        let row = Place { id: existing.as_ref().map(|e| e.id).unwrap_or(0), actor, name, x: p.x, y: p.y };
        if existing.is_some() {
            ctx.db.place().id().update(row);
        } else {
            ctx.db.place().insert(row);
        }
    }
    if ctx.db.place().actor().filter(actor).count() > 24 {
        let mut ids: Vec<u64> = ctx.db.place().actor().filter(actor).map(|p| p.id).collect();
        ids.sort_unstable();
        for id in &ids[..ids.len() - 24] {
            ctx.db.place().id().delete(*id);
        }
    }
    if let Some(t) = update.thought {
        add_thought(ctx, actor, t, now);
    }
    Ok(())
}
