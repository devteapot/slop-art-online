//! The learned-body pilot's plumbing (docs/NEURAL_BODY.md, "Built (pilot plumbing)"), behind the
//! value-only law `body_delegate_on` (off as shipped; with it off nothing here writes a row and a
//! `delegate` leaf is refused at install).
//!
//! - **Delegation.** A graph's `delegate` leaf, while it runs (`brain.rs`), stands in `body_slot`:
//!   its goal, target and skill scope. Its character's movement and combat inputs then come from a
//!   body controller through the player input reducers (`human_move`, `human_face`, `use_skill`,
//!   `release_skill`) and their checks, budgets and outcomes; the graph keeps everything else.
//! - **Sessions.** The character's controller (the mind service) opens a session for an identity
//!   of the body controller's own (`body_open`): one writer per character, a controller epoch and
//!   a short lease the controller renews (`body_beat`, or any accepted input). The session identity
//!   is a player-equivalent viewer: the sweep, the combat feed and frames serve it the character's
//!   own perceptions (`combat::viewers`), and the player views (`my_body`, `my_readiness`, …) answer
//!   it with its character (`perception::current`). A new `body_open` raises the epoch and replaces
//!   the identity, so the old identity's packets are refused.
//! - **Stall.** A session not renewed for `body_lease_ms` lapses (`tick`): its held inputs are let
//!   go as a key release would (the held direction stops, a held guard is let go, a movement waiting
//!   on a rooted move is dropped), and its perception rows go. The delegated leaf keeps running: no
//!   graph takeover, so the character stands until a new session (a new epoch) sends inputs.
//! - **Brief.** `mind_body_brief` replaces or clears the character's one brief (`body_brief`),
//!   checked against its controller, life, the revision the writer read, the schema, finite bounded
//!   values, its lifetime and whether its target is perceived now. A refusal is the reducer's error,
//!   in the mind's terms; the earlier accepted brief stays.
//!
//! SpacetimeDB (docs read 2026-11-26, labelled 2.0.0; the module pins 2.14.1): private tables are
//! read by reducers and the owner only ([tables](https://spacetimedb.com/docs/tables/),
//! [access permissions](https://spacetimedb.com/docs/tables/access-permissions/)); a reducer's `Err`
//! rolls back every write ([reducers](https://spacetimedb.com/docs/functions/reducers/)); a primary
//! key and a unique column are both indexes, and a btree takes range filters
//! ([indexes](https://spacetimedb.com/docs/tables/indexes/)); adding tables is an automatic migration
//! that keeps clients connected ([automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations));
//! a client that connects with no token is issued a new identity
//! ([Rust client](https://spacetimedb.com/docs/clients/rust)).

use crate::common;
use crate::tables::*;
use living_rules::graph::Node;
use spacetimedb::{Identity, ReducerContext, Table};

/// Not pending (a lapsed or closed session's `lease_ms`).
const NEVER: u64 = u64::MAX;

/// The source a body controller's skill uses are recorded under (`skill_use.source`).
pub const SOURCE: &str = "body";

pub fn on(ctx: &ReducerContext) -> bool {
    common::laws(ctx).body_delegate_on
}

fn lease(ctx: &ReducerContext) -> u64 {
    common::laws(ctx).body_lease_ms as u64
}

/// Why a graph holding a `delegate` leaf cannot be installed for `actor`, if it cannot.
pub fn refuse_delegate(ctx: &ReducerContext, actor: u32, root: &Node) -> Option<String> {
    if !living_rules::graph::delegates(root) {
        return None;
    }
    if !on(ctx) {
        return Some("a `delegate` leaf cannot be installed: in this world a plan carries out its own steps (the body_delegate_on law is off)".into());
    }
    if ctx.db.character().id().find(actor).is_some_and(|c| !c.ai) {
        return Some("a `delegate` leaf cannot be installed for a character a person plays: its movement and fighting are its person's".into());
    }
    None
}

// ---- the active delegated leaf ------------------------------------------------------------------

/// What a running `delegate` leaf hands the body (`brain.rs` fills it each evaluation it runs).
#[derive(Clone, Debug, PartialEq)]
pub struct Delegated {
    pub node: u16,
    /// The character's kind: the role whose shared policy serves it.
    pub role: String,
    pub goal: String,
    pub target: u32,
    pub skills: Vec<String>,
    pub label: String,
}

/// After an evaluation: the slot follows the leaf that ran (`Some`) or ends (`None`). Writes only on
/// a change. Nothing is read while the law is off (its rows are cleared by `tick`).
pub fn sync_slot(ctx: &ReducerContext, actor: u32, revision: u32, running: Option<&Delegated>, now: u64) {
    if !on(ctx) {
        return;
    }
    let row = ctx.db.body_slot().actor().find(actor);
    match (running, row) {
        (Some(d), Some(r)) => {
            if r.revision != revision || r.node != d.node || r.role != d.role || r.goal != d.goal || r.target != d.target || r.skills != d.skills || r.label != d.label {
                let since_ms = if r.revision == revision && r.node == d.node { r.since_ms } else { now };
                ctx.db.body_slot().actor().update(BodySlot { actor, revision, node: d.node, role: d.role.clone(), goal: d.goal.clone(), target: d.target, skills: d.skills.clone(), label: d.label.clone(), since_ms });
            }
        }
        (Some(d), None) => {
            ctx.db.body_slot().insert(BodySlot { actor, revision, node: d.node, role: d.role.clone(), goal: d.goal.clone(), target: d.target, skills: d.skills.clone(), label: d.label.clone(), since_ms: now });
        }
        (None, Some(_)) => {
            ctx.db.body_slot().actor().delete(actor);
            end_delegation(ctx, actor, now);
        }
        (None, None) => {}
    }
}

/// A delegation ended: what the body held under it is let go (the held direction, a held guard
/// not committed, a movement waiting on a rooted move); a committed move runs its course. The graph's
/// next leaf then has the body.
fn end_delegation(ctx: &ReducerContext, actor: u32, now: u64) {
    let_go_inputs(ctx, actor, now);
}

/// What a key release does for each held input of a body controller: movement stops, a guard is
/// let go, a deferred movement is dropped. Committed moves and windups settle under their rules.
fn let_go_inputs(ctx: &ReducerContext, actor: u32, now: u64) {
    if ctx.db.steer().id().find(actor).is_some_and(|s| s.goal == crate::motion::GOAL_DIRECTION) {
        crate::motion::brake(ctx, actor, now);
    }
    if let Some(mut r) = ctx.db.readiness().id().find(actor).filter(|r| r.move_pending) {
        r.move_pending = false;
        ctx.db.readiness().id().update(r);
    }
    let sc = common::scripts(ctx);
    if let Some(a) = ctx.db.activity().id().find(actor).filter(|a| a.node == crate::act::PLAYER && !crate::combat::committed(&sc, a)) {
        crate::act::let_go(ctx, a, now);
    }
}

// ---- sessions ---------------------------------------------------------------------------------------

/// The live session of `actor`, if its law holds.
fn live(ctx: &ReducerContext, actor: u32) -> Option<BodySession> {
    if !on(ctx) {
        return None;
    }
    ctx.db.body_session().actor().find(actor).filter(|s| s.live)
}

/// The identity a live body session of `actor` perceives as (`combat::viewer`).
pub fn viewer(ctx: &ReducerContext, actor: u32) -> Option<Identity> {
    live(ctx, actor).map(|s| s.identity)
}

/// Every live session: (character, identity). A handful of rows; read while the law holds.
pub fn viewers(ctx: &ReducerContext) -> Vec<(u32, Identity)> {
    if !on(ctx) {
        return Vec::new();
    }
    let mut v: Vec<(u32, Identity)> = ctx.db.body_session().iter().filter(|s| s.live).map(|s| (s.actor, s.identity)).collect();
    v.sort_unstable_by_key(|(id, _)| *id);
    v
}

/// Whether a body controller drives `actor` now (a live session and a delegated leaf): its deferred
/// movement resumes as a player's does (`combat::resume_move`).
pub fn driving(ctx: &ReducerContext, actor: u32) -> bool {
    live(ctx, actor).is_some() && ctx.db.body_slot().actor().find(actor).is_some()
}

/// The character a session lapses or closes for: its held inputs let go, its perception rows gone.
fn lapse(ctx: &ReducerContext, mut s: BodySession, now: u64, why: &str) {
    let (actor, who) = (s.actor, s.identity);
    s.live = false;
    s.lease_ms = NEVER;
    ctx.db.body_session().actor().update(s);
    let_go_inputs(ctx, actor, now);
    crate::perception::forget(ctx, actor, who);
    crate::combat::clear_feed(ctx, who);
    log::info!("body session of #{actor} ended: {why}");
}

/// The caller is the living, mind-driven character's controller.
fn controlled_by_caller(ctx: &ReducerContext, actor: u32) -> Result<Character, String> {
    let c = ctx.db.character().id().find(actor).ok_or("no such character")?;
    if c.controller != ctx.sender() {
        return Err("not your character".into());
    }
    if !c.alive {
        return Err(format!("#{actor} is dead"));
    }
    if !c.ai {
        return Err(format!("#{actor} is played by a person: its movement and fighting are its person's"));
    }
    Ok(c)
}

/// The controller of `actor` opens a body session for `body`, the identity its body controller
/// connects with (a fresh one per session). The epoch rises; a session still live is fenced first.
#[spacetimedb::reducer]
pub fn body_open(ctx: &ReducerContext, actor: u32, body: Identity) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    if !on(ctx) {
        return Err("this world's bodies take no delegated steps (the body_delegate_on law is off)".into());
    }
    controlled_by_caller(ctx, actor)?;
    let now = common::now_ms(ctx);
    if body == ctx.sender() || body == ctx.database_identity() || body == common::world(ctx).admin {
        return Err("a body session needs an identity of its own".into());
    }
    if ctx.db.player().identity().find(body).is_some() || ctx.db.character().controller().filter(body).next().is_some() {
        return Err("that identity plays or controls a character".into());
    }
    if ctx.db.body_session().identity().find(body).is_some_and(|s| s.actor != actor) {
        return Err("that identity holds another character's body session".into());
    }
    let old = ctx.db.body_session().actor().find(actor);
    if let Some(s) = old.clone().filter(|s| s.live) {
        lapse(ctx, s, now, "replaced by a new epoch");
    }
    let epoch = old.as_ref().map_or(1, |s| s.epoch.saturating_add(1));
    let row = BodySession { actor, identity: body, controller: ctx.sender(), epoch, live: true, lease_ms: now + lease(ctx), opened_ms: now, beat_ms: now };
    if old.is_some() {
        ctx.db.body_session().actor().update(row);
    } else {
        ctx.db.body_session().insert(row);
    }
    // What the body perceives is there from its first frame, not after a sweep.
    crate::perception::sweep_viewer_now(ctx, actor, body, now);
    log::info!("body session of #{actor} opened, epoch {epoch}");
    Ok(())
}

/// The controller ends `actor`'s body session (the character stands; the delegated leaf stays).
#[spacetimedb::reducer]
pub fn body_close(ctx: &ReducerContext, actor: u32) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    let c = ctx.db.character().id().find(actor).ok_or("no such character")?;
    if c.controller != ctx.sender() {
        return Err("not your character".into());
    }
    if let Some(s) = ctx.db.body_session().actor().find(actor).filter(|s| s.live) {
        lapse(ctx, s, common::now_ms(ctx), "closed by its controller");
    }
    Ok(())
}

/// The body controller renews its session's lease (`epoch`: the session it holds).
#[spacetimedb::reducer]
pub fn body_beat(ctx: &ReducerContext, epoch: u32) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    let now = common::now_ms(ctx);
    let mut s = session_of_caller(ctx, now)?;
    if s.epoch != epoch {
        return Err(format!("this body session is epoch {}, not {epoch}", s.epoch));
    }
    s.lease_ms = now + lease(ctx);
    s.beat_ms = now;
    ctx.db.body_session().actor().update(s);
    Ok(())
}

/// The caller's live session, its law holding and its lease running.
fn session_of_caller(ctx: &ReducerContext, now: u64) -> Result<BodySession, String> {
    if !on(ctx) {
        return Err("this world's bodies take no delegated steps (the body_delegate_on law is off)".into());
    }
    let s = ctx.db.body_session().identity().find(ctx.sender()).ok_or("you hold no body session")?;
    if !s.live || s.lease_ms < now {
        return Err("this body session has lapsed: its controller opens a new one".into());
    }
    if !ctx.db.character().id().find(s.actor).is_some_and(|c| c.alive && c.ai && c.controller == s.controller) {
        return Err("this body session's character is no longer its controller's to delegate".into());
    }
    Ok(s)
}

/// Who sends a player input (`human_move`, `human_face`, `use_skill`, `release_skill`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Driver {
    /// A person playing their character.
    Player,
    /// A body controller under a delegated leaf.
    Body,
}

/// The character a player input is for, and who sends it: the caller's played character, else the
/// character of the caller's live body session while a leaf is delegated to it, `skill` (when one is
/// pressed) within the leaf's scope. An accepted body input renews the lease. Refusals are told in
/// the controller's terms.
pub fn input_for(ctx: &ReducerContext, skill: Option<&str>) -> Result<(Character, Driver), String> {
    if let Some(c) = crate::perception::player_character(ctx) {
        return Ok((c, Driver::Player));
    }
    if !on(ctx) || ctx.db.body_session().identity().find(ctx.sender()).is_none() {
        return Err("you have no living character".into());
    }
    let now = common::now_ms(ctx);
    let mut s = session_of_caller(ctx, now)?;
    let slot = ctx.db.body_slot().actor().find(s.actor).ok_or("no step of the plan is delegated to the body now")?;
    if let Some(k) = skill {
        if !slot.skills.iter().any(|x| x == k) {
            return Err(format!("{k} is not among the skills the plan delegated to the body ({})", if slot.skills.is_empty() { "movement only".to_string() } else { slot.skills.join(", ") }));
        }
    }
    let c = ctx.db.character().id().find(s.actor).ok_or("no such character")?;
    s.lease_ms = now + lease(ctx);
    s.beat_ms = now;
    ctx.db.body_session().actor().update(s);
    Ok((c, Driver::Body))
}

/// A session does not end with its connection: every HTTP call is a connection of its own, so the
/// lease alone decides (a controller whose connection is gone sends no beat and lapses within it).

/// Every tick: sessions whose lease ran out lapse (an index range of the due rows only). With the law
/// off, rows left from when it held are ended once (two counts while none exist).
pub fn tick(ctx: &ReducerContext, now: u64) {
    if !on(ctx) {
        if ctx.db.body_session().count() == 0 && ctx.db.body_slot().count() == 0 {
            return;
        }
        for s in ctx.db.body_session().iter().filter(|s| s.live).collect::<Vec<_>>() {
            lapse(ctx, s, now, "the body_delegate_on law is off");
        }
        for slot in ctx.db.body_slot().iter().collect::<Vec<_>>() {
            ctx.db.body_slot().actor().delete(slot.actor);
            end_delegation(ctx, slot.actor, now);
        }
        return;
    }
    let due: Vec<BodySession> = ctx.db.body_session().lease_ms().filter(..now).collect();
    for s in due {
        lapse(ctx, s, now, "its lease ran out");
    }
}

/// A character died: its brief, slot and session go.
pub fn forget(ctx: &ReducerContext, actor: u32, now: u64) {
    ctx.db.body_brief().actor().delete(actor);
    ctx.db.body_slot().actor().delete(actor);
    if let Some(s) = ctx.db.body_session().actor().find(actor) {
        if s.live {
            crate::perception::forget(ctx, actor, s.identity);
            crate::combat::clear_feed(ctx, s.identity);
        }
        ctx.db.body_session().actor().delete(actor);
    }
    let _ = now;
}

// ---- the brief ---------------------------------------------------------------------------------------

/// A mind replaces (`Some`) or clears (`None`) its character's body brief (docs/NEURAL_BODY.md §2).
/// `expected` is the revision the writer read (0 before any). Checked: the law, the caller's control
/// of a living mind-driven character, the revision, the schema and finite bounded values, the
/// lifetime (`body_brief_max_s`) and the target, which must be someone the character perceives now
/// (the same words whether or not the id exists). A refusal is this reducer's error and leaves the
/// earlier brief as it was (a failed transaction writes nothing; the mind service journals the reply).
#[spacetimedb::reducer]
pub fn mind_body_brief(ctx: &ReducerContext, actor: u32, expected: u32, brief: Option<BodyBriefIn>) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    if !on(ctx) {
        return Err("this world's bodies take no delegated steps (the body_delegate_on law is off)".into());
    }
    controlled_by_caller(ctx, actor)?;
    let now = common::now_ms(ctx);
    let row = ctx.db.body_brief().actor().find(actor);
    let current = row.as_ref().map_or(0, |r| r.revision);
    if expected != current {
        return Err(format!("the brief is at revision {current}, not {expected}: read it again"));
    }
    let next = match brief {
        None => BodyBrief { actor, revision: current + 1, goal: String::new(), target: 0, stance: String::new(), risk: 0.0, style: 0.0, traits: Vec::new(), rationale: String::new(), written_ms: now, expires_ms: now },
        Some(b) => {
            let max = common::laws(ctx).body_brief_max_s;
            living_rules::body::check(&living_rules::body::Brief { goal: &b.goal, target: b.target, stance: &b.stance, risk: b.risk, style: b.style, ttl_s: b.ttl_s, rationale: &b.rationale, traits: &b.traits }, max)?;
            if b.target != 0 {
                if b.target == actor {
                    return Err("a brief's target is someone else".into());
                }
                let seen = crate::brain::resolve_for(ctx, actor, &living_rules::graph::Target::Id(b.target), now);
                if !seen.is_ok_and(|r| r.class == 3) {
                    return Err(living_rules::body::unseen_target(b.target));
                }
            }
            BodyBrief { actor, revision: current + 1, goal: b.goal, target: b.target, stance: b.stance, risk: b.risk, style: b.style, traits: b.traits, rationale: b.rationale, written_ms: now, expires_ms: now + (b.ttl_s * 1000.0) as u64 }
        }
    };
    if row.is_some() {
        ctx.db.body_brief().actor().update(next);
    } else {
        ctx.db.body_brief().insert(next);
    }
    Ok(())
}

/// What the owning mind reads of its body (`_body` in its scene, rendered by the mind service as its
/// own prompt section): the accepted brief and its remaining time, the delegated leaf, and whether a
/// body controller holds the character now. `None` while the character has neither brief nor slot
/// (always, with the law off).
pub fn scene_note(ctx: &ReducerContext, actor: u32, now: u64) -> Option<serde_json::Value> {
    if !on(ctx) {
        return None;
    }
    let brief = ctx.db.body_brief().actor().find(actor).filter(|b| !b.goal.is_empty());
    let slot = ctx.db.body_slot().actor().find(actor);
    if brief.is_none() && slot.is_none() {
        return None;
    }
    let mut v = serde_json::json!({});
    if let Some(b) = brief {
        let left = b.expires_ms.saturating_sub(now);
        v["brief"] = serde_json::json!({
            "revision": b.revision,
            "goal": b.goal,
            "target": b.target,
            "stance": b.stance,
            "risk": b.risk,
            "style": b.style,
            "traits": b.traits,
            "rationale": b.rationale,
            "left_s": (left as f64 / 1000.0).round(),
            "expired": left == 0,
        });
    }
    if let Some(s) = slot {
        v["leaf"] = serde_json::json!({"node": s.node, "label": s.label, "since_s": (now.saturating_sub(s.since_ms) as f64 / 1000.0).round()});
    }
    v["controlled"] = serde_json::json!(live(ctx, actor).is_some());
    Some(v)
}
