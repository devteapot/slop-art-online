//! Heed for AI characters (docs/ATTENTION_BUDGET.md v2.1, point 3; docs/ATTENTION_E4.md): whom a
//! character the authority runs keeps track of as individuals. Everyone else it sees is a
//! **throng**: counted and placed, never named.
//!
//! Behind the law `heed_on` (off by default: then nothing here runs and every reader is as
//! before). Players perceive through heed only with the value-only law `heed_players` too (off by
//! default): then a played character's committed `perceived` set is its individuals
//! (`perception::sweep_one` takes [`split`] in place of `far_cap`'s trim), the rest of its sight is
//! counted in `seen_throng` (`throng.rs`), and its pins and focus (`human_heed`, the `heed_choice`
//! row) weigh in its picks. For a played character [`individual`] reads that committed set, so
//! nothing but `perceived` decides who receives what (docs/ATTENTION_BUDGET.md, "Player-side
//! interface").
//!
//! **The set.** Kept per character in module memory ([`HEED`]): the selector's picks
//! (`living_rules::heed::select`, the same code the E3 replay runs), each pick's last time on
//! merit (for its rule's hold), how long each has been heeded and in sight. A full pass runs at
//! most once per [`PASS_MS`] per character, from its behaviour evaluation (or from any reader that
//! finds the set older than [`STALE_MS`]); between passes the event pass (`heed::admit`) takes a
//! windup aimed at it, words to it and a cue's match (contact is forced). Coming into sight and
//! moving are not events: E2 measured that re-rank too costly in a battle.
//!
//! **Forced, outside the capacity, whatever the policy:** whoever the character acts on (its
//! activity's or move's target) and whoever made contact with it within `heed_contact_s` (a blow
//! of theirs that reached it: landed, blocked or dodged; [`contact`]). They are worked out when a
//! reader asks, not kept, so they are never stale.
//!
//! **Capacity:** the world's `heed_capacity(a)` law over the character's own facts, clamped by
//! `heed_ceiling` (`Scripts::heed_capacity`), asked at each full pass.
//!
//! **Module memory and rollback** (docs/PERCEPTION.md, "Module memory and rollback"): the set is a
//! working cache of a selection, not a record. A transaction that rolls back may leave a pass or a
//! contact in memory; the next pass re-derives the picks from what the body perceives, and a
//! contact mark lapses within `heed_contact_s`. A fresh instance starts with no set: each reader
//! asks for a pass. Nothing here is written to a table.
//!
//! **Instrumentation (E4).** With the diagnostic law `heed_trace` on (off in play), for every
//! character the authority runs (with the heed law off too, then everyone counts as heeded), each
//! windup aimed at it
//! and each blow that reaches it is logged (`heed windup …`, `heed blow …`), with whether its maker
//! was an individual to it when the windup began, and each full pass (`heed pass …`: capacity,
//! health, how many it sees, how many places its rules filled). A blow whose maker made contact within the window before the windup began and
//! yet was not an individual then would be an invisible repeated blow, which forced contact rules
//! out by construction: it is logged as an error (`heed invariant: …`).

use crate::common::{self, NearCreature};
use crate::tables::*;
use living_rules::heed::{self as h, Candidate, ClosingTracker, Held, Limits, Pick, Place, Policy, SelfState, Visible};
use spacetimedb::ReducerContext;
use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

/// A full pass at most this often per character (an AI's evaluation slot, docs/ATTENTION_BUDGET.md §2.3).
pub const PASS_MS: u64 = 1_000;
/// A reader that finds the set older than this asks for a pass afresh.
pub const STALE_MS: u64 = 3_000;
/// A blow from the same attacker after this long is the first of a new engagement (pack_arena's
/// 20 s episode).
const ENGAGEMENT_MS: u64 = 20_000;
/// A cue's match marks its subject `cued` for this long.
const CUED_MS: u64 = 5_000;
/// A player pins at most this many creatures (`human_heed`); more is refused with a reason.
pub const MAX_PINS: usize = 4;
/// A player's `human_heed` calls are at least this far apart (ms).
pub const CHOICE_FLOOR_MS: u64 = 250;
/// What a player's focus and each of its pins weigh in its candidate's `chosen`.
const FOCUS_WEIGHT: f32 = 1.0;
const PIN_WEIGHT: f32 = 0.75;

#[derive(Default)]
struct State {
    /// The last selection: every pick in rank order (forced ones included, as they were then).
    picks: Vec<Pick>,
    /// Per creature heeded by a rule: that rule, and when it last took it on its own merit.
    merit: HashMap<u32, (usize, u64)>,
    /// Since when each creature has been heeded (ms).
    since: HashMap<u32, u64>,
    /// Since when each creature has been in sight (ms), as passes saw it.
    in_sight: HashMap<u32, u64>,
    /// The last full pass (ms); 0: none.
    pass_ms: u64,
    /// The capacity the last pass used.
    capacity: usize,
    /// The last pass's field, for the event pass's `count` gates.
    cands: Vec<Candidate>,
    /// Cue matches: creature -> when.
    cued: HashMap<u32, u64>,
    /// Closing speed per creature, smoothed over `heed_closing_s` (the selector's tracker, one per
    /// observer, observed at each pass; an event between passes reads its last answer).
    /// With the time its clock starts (ms), so seconds stay small enough for f32.
    closing: Option<(u64, ClosingTracker)>,
}

impl State {
    fn has(&self, id: u32) -> bool {
        self.picks.iter().any(|p| p.id == id)
    }
}

thread_local! {
    static HEED: RefCell<HashMap<u32, State>> = RefCell::new(HashMap::new());
    /// Contact: victim -> (attacker, when), the latest per attacker.
    static CONTACT: RefCell<HashMap<u32, Vec<(u32, u64)>>> = RefCell::new(HashMap::new());
    /// Windups aimed at a character with a mind: (attacker, victim) -> what held when it began.
    static WINDUPS: RefCell<HashMap<(u32, u32), Windup>> = RefCell::new(HashMap::new());
    /// The species' instincts, parsed once per kind.
    static INSTINCTS: RefCell<HashMap<String, Rc<Policy>>> = RefCell::new(HashMap::new());
    /// Minds' own policies, parsed once per write: actor -> (the row's `written_ms`, the policy).
    /// A hint checked against the `heed_policy` row at every read (docs: reducers, global state).
    static OWN: RefCell<HashMap<u32, (u64, Rc<Policy>)>> = RefCell::new(HashMap::new());
}

#[derive(Clone, Copy)]
struct Windup {
    at_ms: u64,
    /// The maker was in the victim's sight when it began.
    seen: bool,
    /// The maker was an individual to the victim when it began (after the event pass).
    heeded: bool,
    /// The maker had made contact with the victim within the window then.
    contact: bool,
}

/// Whether the heed law is on in this world.
pub fn on(ctx: &ReducerContext) -> bool {
    common::laws(ctx).heed_on
}

/// Whether character `id` perceives through heed: the law is on and no person plays it, or one
/// does and `heed_players` holds too.
pub fn applies(ctx: &ReducerContext, id: u32) -> bool {
    on(ctx) && (common::laws(ctx).heed_players || crate::combat::human(ctx, id).is_none())
}

/// Whether heed applies to players in this world: `heed_on` and `heed_players` both hold.
pub fn applies_player(ctx: &ReducerContext) -> bool {
    let l = common::laws(ctx);
    l.heed_on && l.heed_players
}

/// Whether `other` is in the committed `perceived` set of the player `viewer` (its individuals
/// while heed applies to it).
pub fn perceives(ctx: &ReducerContext, viewer: spacetimedb::Identity, other: u32) -> bool {
    ctx.db.perceived().viewer().filter(viewer).any(|p| p.body == other)
}

/// Whether `other` must stay anonymous to `observer` (a throng member to it): the law applies to
/// the observer and `other` is someone else it does not perceive individually now.
pub fn masked(ctx: &ReducerContext, observer: &Character, other: u32, now: u64) -> bool {
    other != 0 && other != observer.id && !crate::far::is_handle(other) && applies(ctx, observer.id) && !individual(ctx, observer.id, other, now)
}

/// Whether `me` perceives `other` as an individual now: always when heed does not apply to it;
/// for a played character, `other` is in its committed `perceived` set (contact puts the attacker
/// there in the blow's own transaction, [`contact`]); else forced (acted on, contact) or in its
/// heeded set (a pass first when its set is missing or older than [`STALE_MS`]). Says nothing
/// about sight: callers ask it of creatures in sight.
pub fn individual(ctx: &ReducerContext, me: u32, other: u32, now: u64) -> bool {
    if other == me || !applies(ctx, me) {
        return true;
    }
    if let Some(viewer) = crate::combat::human(ctx, me) {
        return perceives(ctx, viewer, other);
    }
    if forced(ctx, me, other, now).is_some() {
        return true;
    }
    fresh(ctx, me, now);
    HEED.with(|m| m.borrow().get(&me).is_some_and(|s| s.has(other)))
}

/// A pass for `me` when its set is missing or stale.
fn fresh(ctx: &ReducerContext, me: u32, now: u64) {
    let due = HEED.with(|m| m.borrow().get(&me).map_or(true, |s| s.pass_ms == 0 || now.saturating_sub(s.pass_ms) >= STALE_MS));
    if !due {
        return;
    }
    let Some(ch) = ctx.db.character().id().find(me) else { return };
    let Some(b) = ctx.db.body().id().find(me) else { return };
    let at = common::pos(&b, now);
    let (seen, _) = crate::perception::sensed(ctx, me, at, now);
    pass(ctx, &ch, at, &seen, now);
}

/// The forced place of `other` for `me` now, if any: the target of its own act or move, or contact
/// within `heed_contact_s`.
fn forced(ctx: &ReducerContext, me: u32, other: u32, now: u64) -> Option<Place> {
    if acting_on(ctx, me) == Some(other) {
        return Some(Place::Acting);
    }
    let window = (common::laws(ctx).heed_contact_s * 1000.0) as u64;
    contact_at(me, other).filter(|t| now.saturating_sub(*t) <= window).map(|_| Place::Contact)
}

/// Whom `me` is acting on: its activity's creature target, else its move's target.
fn acting_on(ctx: &ReducerContext, me: u32) -> Option<u32> {
    if let Some(a) = ctx.db.activity().id().find(me).filter(|a| a.target.class == 3 && a.target.id as u32 != me && a.target.id != 0) {
        return Some(a.target.id as u32);
    }
    ctx.db.fighter().id().find(me).filter(|f| f.act != 0 && f.target != 0 && f.target != me).map(|f| f.target)
}

fn contact_at(victim: u32, attacker: u32) -> Option<u64> {
    CONTACT.with(|c| c.borrow().get(&victim).and_then(|v| v.iter().find(|(a, _)| *a == attacker).map(|(_, t)| *t)))
}

/// A character's heed policy: the one its mind wrote and the authority accepted (`heed_policy`),
/// else its species' instinct (seed content, `living/seeds/heed.json`).
fn policy(ctx: &ReducerContext, me: &Character) -> Rc<Policy> {
    if let Some(row) = ctx.db.heed_policy().actor().find(me.id).filter(|r| !r.policy.is_empty()) {
        let cached = OWN.with(|m| m.borrow().get(&me.id).filter(|(t, _)| *t == row.written_ms).map(|(_, p)| p.clone()));
        if let Some(p) = cached {
            return p;
        }
        // Validated when written; read back with any id and kind (one met then may be gone now).
        match serde_json::from_str::<serde_json::Value>(&row.policy).map_err(|e| e.to_string()).and_then(|v| h::parse_value(&v, &h::Known::any())) {
            Ok(p) => {
                let p = Rc::new(p);
                OWN.with(|m| m.borrow_mut().insert(me.id, (row.written_ms, p.clone())));
                return p;
            }
            Err(e) => log::warn!("heed: #{}'s stored policy does not parse ({e}); its instinct holds", me.id),
        }
    }
    instinct(&me.kind)
}

fn instinct(kind: &str) -> Rc<Policy> {
    INSTINCTS.with(|m| m.borrow_mut().entry(kind.to_string()).or_insert_with(|| Rc::new(h::instinct(kind))).clone())
}

/// A policy a mind sent for `me`, validated as the authority reads it: ids it may name are those
/// it sees now or has a relation with; kinds are the world's (people and its species). The notes
/// say what was accepted with a change; an `Err` is the refusal, in words for the mind.
pub fn validate(ctx: &ReducerContext, me: &Character, v: &serde_json::Value, now: u64) -> Result<(Policy, Vec<String>), String> {
    let seen: std::collections::HashSet<u32> = match ctx.db.body().id().find(me.id) {
        Some(b) => crate::perception::sensed(ctx, me.id, common::pos(&b, now), now).0.iter().map(|c| c.id).collect(),
        None => Default::default(),
    };
    let met = |id: u32| seen.contains(&id) || ctx.db.relation().by_pair().filter((me.id, id)).next().is_some();
    let kind = |k: &str| k == "person" || common::species(k).is_some();
    h::parse_value_notes(v, &h::Known { met: &met, kind: &kind })
}

/// What a mind's scene says about its own heed (`_heed`, which the mind service renders as its
/// own prompt section and strips from the scene): its capacity now, whether it keeps track by its
/// own policy or its instinct, each rule's `why`, the notes on its own policy, and the last refusal
/// while no newer policy has been accepted. `None` when heed does not apply.
pub fn scene_note(ctx: &ReducerContext, me: &Character, now: u64) -> Option<serde_json::Value> {
    if !applies(ctx, me.id) {
        return None;
    }
    fresh(ctx, me.id, now);
    let cap = HEED.with(|m| m.borrow().get(&me.id).map(|s| s.capacity)).unwrap_or_else(|| capacity(ctx, me, now));
    let row = ctx.db.heed_policy().actor().find(me.id);
    let own = row.as_ref().is_some_and(|r| !r.policy.is_empty());
    let pol = policy(ctx, me);
    let whys: Vec<&str> = pol.rules.iter().map(|r| r.why()).filter(|w| !w.is_empty()).collect();
    let mut note = serde_json::json!({"capacity": cap, "by": if own { "your own policy" } else { "your instinct" }, "rules": whys});
    if let Some(r) = &row {
        if own && !r.notes.is_empty() {
            note["notes"] = serde_json::from_str(&r.notes).unwrap_or(serde_json::Value::Null);
        }
        if !r.refusal.is_empty() {
            note["refused"] = serde_json::json!(r.refusal);
        }
    }
    Some(note)
}

/// What a policy's conditions read beyond the cheap facts, so a pass gathers only that.
#[derive(Default, Clone, Copy)]
struct Reads {
    relation: bool,
    stranger: bool,
    community: bool,
    made_out: bool,
}

fn reads(p: &Policy) -> Reads {
    fn cond(c: &h::Cond, r: &mut Reads) {
        let rel = |x: &Option<h::Relation>, r: &mut Reads| match x {
            Some(h::Relation::Friend | h::Relation::Enemy) => r.relation = true,
            Some(h::Relation::Stranger) => r.stranger = true,
            Some(h::Relation::Community) => r.community = true,
            _ => {}
        };
        match c {
            h::Cond::Who(h::Who::Id(_)) => r.made_out = true,
            h::Cond::Who(h::Who::Filter { relation, .. }) => {
                r.made_out = true;
                rel(relation, r);
            }
            h::Cond::SelfGate(h::SelfCond::Count { relation, .. }) => {
                r.made_out = true;
                rel(relation, r);
            }
            h::Cond::All(v) | h::Cond::Any(v) => v.iter().for_each(|x| cond(x, r)),
            h::Cond::Not(x) => cond(x, r),
            _ => {}
        }
    }
    let mut r = Reads::default();
    for rule in &p.rules {
        match rule {
            h::Rule::If { cond: c, .. } => cond(c, &mut r),
            h::Rule::Score { weights, .. } => weights.iter().for_each(|(c, _)| cond(c, &mut r)),
        }
    }
    r
}

/// The capacity now: the world's `heed_capacity(a)` law over the character's own facts, clamped
/// by `heed_ceiling`. A script without the law (or one that fails) heeds no one by rule: only the
/// forced ones are individuals, and the failure is logged once per pass.
pub fn capacity(ctx: &ReducerContext, me: &Character, now: u64) -> usize {
    let sc = common::scripts(ctx);
    let w = common::world(ctx);
    let mut actor = crate::act::facts(ctx, me.id, now);
    actor.practice = common::practice_of(ctx, me.id);
    if actor.genes.is_empty() {
        actor.genes = (*common::genes_of(ctx, me.id)).clone();
    }
    let sctx = living_rules::script::SkillCtx { actor, night: common::night(ctx, &w, now), dark: common::dark(ctx, &w, now), ..Default::default() };
    match sc.heed_capacity(&sctx, common::laws(ctx).heed_ceiling) {
        Ok(n) => n,
        Err(e) => {
            log::warn!("heed: #{}'s capacity: {e}", me.id);
            0
        }
    }
}

/// The full pass for `me` at `at` over `seen` (everything it sees, nearest first): candidates from
/// what it perceives, its capacity, its policy with each rule's hold, the selection kept.
pub fn pass(ctx: &ReducerContext, me: &Character, at: (f32, f32), seen: &[NearCreature], now: u64) {
    let _span = common::span("heed.pass");
    let pol = policy(ctx, me);
    let r = reads(&pol);
    let cap = capacity(ctx, me, now);
    let limits = Limits { capacity: cap, contact_s: common::laws(ctx).heed_contact_s };
    let mine = self_state(ctx, me, now);
    let (prev_picks, merit, since, in_sight, cued, prev_cap, tracker) = HEED.with(|m| {
        let mut m = m.borrow_mut();
        match m.get_mut(&me.id) {
            Some(s) => (s.picks.clone(), s.merit.clone(), s.since.clone(), s.in_sight.clone(), s.cued.clone(), Some(s.capacity), s.closing.take()),
            None => (Vec::new(), HashMap::new(), HashMap::new(), HashMap::new(), HashMap::new(), None, None),
        }
    });
    let window = common::laws(ctx).heed_closing_s;
    let (base_ms, mut tracker) = tracker.unwrap_or_else(|| (now, ClosingTracker::new(window)));
    let t_s = now.saturating_sub(base_ms) as f32 / 1000.0;
    let heeded_now: Vec<u32> = prev_picks.iter().map(|p| p.id).collect();
    let mut in_sight2: HashMap<u32, u64> = HashMap::with_capacity(seen.len());
    for c in seen {
        in_sight2.insert(c.id, in_sight.get(&c.id).copied().unwrap_or(now));
    }
    let field = Field::new(ctx, me, at, &heeded_now, &since, &in_sight2, &cued, r, now);
    let mut cands: Vec<Candidate> = seen.iter().map(|c| field.candidate(ctx, c)).collect();
    for c in &mut cands {
        c.closing = tracker.observe(c.id, t_s, c.dist);
    }
    tracker.forget_before(t_s);
    let held: Vec<Held> = prev_picks
        .iter()
        .filter_map(|p| {
            let rule = p.place.rule()?;
            let (mr, t) = merit.get(&p.id).copied()?;
            (mr == rule).then(|| Held { id: p.id, rule, lapsed_s: now.saturating_sub(t) as f32 / 1000.0 })
        })
        .collect();
    let picks = h::select(&pol, &mine, &cands, &limits, &held);
    let mut merit2 = HashMap::with_capacity(picks.len());
    let mut since2 = HashMap::with_capacity(picks.len());
    for p in &picks {
        if let Some(rule) = p.place.rule() {
            let t = if p.held { merit.get(&p.id).filter(|(r, _)| *r == rule).map_or(now, |(_, t)| *t) } else { now };
            merit2.insert(p.id, (rule, t));
        }
        since2.insert(p.id, since.get(&p.id).copied().unwrap_or(now));
    }
    let cued2: HashMap<u32, u64> = cued.into_iter().filter(|(_, t)| now.saturating_sub(*t) < CUED_MS).collect();
    common::diag(|| "heed:passes", 1);
    common::diag(|| "heed:in_sight", seen.len() as u64);
    common::diag(|| "heed:picked", picks.len() as u64);
    if common::laws(ctx).heed_trace {
        // E4: every pass of a character with a mind (about one a second): its capacity, health,
        // how many it sees and how many places its rules filled, and the forced ones.
        let hp = ctx.db.vitals().id().find(me.id).map(|v| common::needs(&v, now).hp / v.max_hp.max(1.0)).unwrap_or(0.0);
        let by_rule = picks.iter().filter(|p| !p.place.forced()).count();
        log::info!("heed pass id={} cap={cap} health={hp:.3} in_sight={} picked={by_rule} forced={} changed={}", me.id, seen.len(), picks.len() - by_rule, (prev_cap != Some(cap)) as u8);
    }
    HEED.with(|m| {
        m.borrow_mut().insert(me.id, State { picks, merit: merit2, since: since2, in_sight: in_sight2, pass_ms: now, capacity: cap, cands, cued: cued2, closing: Some((base_ms, tracker)) });
    });
}

/// When `me`'s last full pass ran (ms; 0: none in this instance).
pub fn last_pass(me: u32) -> u64 {
    HEED.with(|m| m.borrow().get(&me).map_or(0, |s| s.pass_ms))
}

/// `seen` split into the individuals and the throng for `me` (both nearest first, as given): a
/// full pass when one is due ([`PASS_MS`]). Unchanged (all individuals) when heed does not apply.
pub fn split(ctx: &ReducerContext, me: &Character, at: (f32, f32), seen: Vec<NearCreature>, now: u64) -> (Vec<NearCreature>, Vec<NearCreature>) {
    if !applies(ctx, me.id) {
        return (seen, Vec::new());
    }
    let due = HEED.with(|m| m.borrow().get(&me.id).map_or(true, |s| s.pass_ms == 0 || now.saturating_sub(s.pass_ms) >= PASS_MS));
    // Between passes no re-ranking for whoever came into sight or moved: dev-box's E2 (docs/
    // ATTENTION_E2_COST.md, Q10) measured a per-move re-rank at 0.6-0.9 s/s of the database thread
    // in a battle. Only the one aiming at the character, contact, words to it and a cue's match
    // are events; everyone else waits for the 1 Hz pass.
    if due {
        pass(ctx, me, at, &seen, now);
    }
    let (mut ind, mut thr) = (Vec::with_capacity(seen.len()), Vec::new());
    HEED.with(|m| {
        let m = m.borrow();
        let s = m.get(&me.id);
        for c in seen {
            if s.is_some_and(|s| s.has(c.id)) || forced(ctx, me.id, c.id, now).is_some() {
                ind.push(c);
            } else {
                thr.push(c);
            }
        }
    });
    common::diag(|| "heed:split_throng", thr.len() as u64);
    (ind, thr)
}

/// The event pass for one creature `c` in `me`'s sight (`living_rules::heed::admit`): forced, a
/// free place, a displacement, or nothing. `tweak` sets what the event itself says (a windup at
/// me, a cue's match) on its candidate. Returns whether it is an individual afterwards.
fn event(ctx: &ReducerContext, me: &Character, at: (f32, f32), c: &NearCreature, now: u64, tweak: impl FnOnce(&mut Candidate)) -> bool {
    let _span = common::detail_span("heed.event");
    let pol = policy(ctx, me);
    let r = reads(&pol);
    let mine = self_state(ctx, me, now);
    let contact_s = common::laws(ctx).heed_contact_s;
    let got = HEED.with(|m| {
        let m = m.borrow();
        let s = m.get(&me.id)?;
        let heeded: Vec<u32> = s.picks.iter().map(|p| p.id).collect();
        let mut in_sight = s.in_sight.clone();
        in_sight.entry(c.id).or_insert(now);
        let field = Field::new(ctx, me, at, &heeded, &s.since, &in_sight, &s.cued, r, now);
        let mut cand = field.candidate(ctx, c);
        // Closing speed as the last pass measured it (0 for one not seen at a pass yet).
        cand.closing = s.closing.as_ref().and_then(|(_, t)| t.last(c.id)).unwrap_or(0.0);
        tweak(&mut cand);
        let limits = Limits { capacity: s.capacity, contact_s };
        Some((h::admit(&pol, &cand, &mine, &s.cands, &s.picks, &limits), cand))
    });
    let Some((admit, cand)) = got else { return false };
    common::diag(|| "heed:events", 1);
    let taken = !matches!(admit, h::Admit::No);
    let now_individual = HEED.with(|m| {
        let mut m = m.borrow_mut();
        let Some(s) = m.get_mut(&me.id) else { return false };
        s.in_sight.entry(c.id).or_insert(now);
        if let Some(old) = s.cands.iter_mut().find(|x| x.id == cand.id) {
            *old = cand.clone();
        } else {
            s.cands.push(cand.clone());
        }
        match admit {
            h::Admit::No => s.has(c.id),
            h::Admit::Forced(place) => {
                s.picks.retain(|p| p.id != c.id);
                s.picks.insert(0, Pick::new(c.id, place));
                s.merit.remove(&c.id);
                s.since.entry(c.id).or_insert(now);
                common::diag(|| "heed:event_forced", 1);
                true
            }
            h::Admit::Take { rule } => {
                s.picks.push(Pick::new(c.id, Place::Rule(rule)));
                s.merit.insert(c.id, (rule, now));
                s.since.insert(c.id, now);
                common::diag(|| "heed:event_take", 1);
                true
            }
            h::Admit::Replace { rule, drop } => {
                s.picks.retain(|p| p.id != drop);
                s.merit.remove(&drop);
                s.since.remove(&drop);
                s.picks.push(Pick::new(c.id, Place::Rule(rule)));
                s.merit.insert(c.id, (rule, now));
                s.since.insert(c.id, now);
                common::diag(|| "heed:event_replace", 1);
                true
            }
        }
    });
    // A played character's individuals are its committed `perceived` set: one taken by an event
    // joins it in this transaction (a displaced one goes at its next sweep).
    if taken && now_individual {
        if let Some(viewer) = crate::combat::human(ctx, me.id) {
            crate::perception::admit(ctx, me.id, viewer, c.id, now);
        }
    }
    now_individual
}

/// A windup aimed at `victim` began, by `attacker` (`act::begin`): the event pass for the victim,
/// if heed applies to it and it sees the attacker; and, for a victim with a mind, what held then
/// (for [`contact`]'s log).
pub fn windup(ctx: &ReducerContext, attacker: u32, victim: u32, now: u64) {
    let trace = common::laws(ctx).heed_trace;
    if !applies(ctx, victim) {
        // With the law off (or a player), everyone in sight is an individual: traced as such,
        // for an arm without heed to be measured the same way (E4).
        if trace && crate::combat::human(ctx, victim).is_none() {
            let seen = crate::perception::sees_creature(ctx, victim, attacker, now);
            log::info!("heed windup a={attacker} v={victim} seen={} heeded={} contact=0 cap=0", seen as u8, seen as u8);
            WINDUPS.with(|w| w.borrow_mut().insert((attacker, victim), Windup { at_ms: now, seen, heeded: seen, contact: false }));
        }
        return;
    }
    let Some(vc) = ctx.db.character().id().find(victim) else { return };
    let (Some(vb), Some(ab)) = (ctx.db.body().id().find(victim), ctx.db.body().id().find(attacker)) else { return };
    let at = common::pos(&vb, now);
    let ap = common::pos(&ab, now);
    fresh(ctx, victim, now);
    let seen = crate::perception::sees_creature(ctx, victim, attacker, now);
    let mut heeded = forced(ctx, victim, attacker, now).is_some() || HEED.with(|m| m.borrow().get(&victim).is_some_and(|s| s.has(attacker)));
    if seen && !heeded {
        let kind = ctx.db.character().id().find(attacker).map(|c| c.kind).unwrap_or_default();
        let c = NearCreature { id: attacker, kind: kind.as_str().into(), pos: ap, dist: common::dist(at, ap), facing: common::facing_at(&ab, now) };
        heeded = event(ctx, &vc, at, &c, now, |cand| cand.threatening = true);
    }
    let window = (common::laws(ctx).heed_contact_s * 1000.0) as u64;
    let contact = contact_at(victim, attacker).is_some_and(|t| now.saturating_sub(t) <= window);
    common::diag(|| if heeded { "heed:windup_heeded" } else if seen { "heed:windup_throng" } else { "heed:windup_unseen" }, 1);
    if contact && !heeded {
        // Contact within the window forces the attacker: this cannot happen (an invisible
        // repeated blow). Kept as an error line, counted by the E4 report.
        log::error!("heed invariant: windup by #{attacker} at #{victim} after contact within the window, yet not an individual");
    }
    if trace {
        let cap = HEED.with(|m| m.borrow().get(&victim).map_or(0, |s| s.capacity));
        log::info!("heed windup a={attacker} v={victim} seen={} heeded={} contact={} cap={cap}", seen as u8, heeded as u8, contact as u8);
        WINDUPS.with(|w| w.borrow_mut().insert((attacker, victim), Windup { at_ms: now, seen, heeded, contact }));
    }
}

/// `attacker`'s blow reached `victim` (`act::damage`, a dodge by evasion): contact, which forces the
/// attacker for `heed_contact_s`. `outcome`: "hit", "blocked" or "dodged". Logged for a victim
/// with a mind (E4): whether it is the attacker's first in an engagement, and what held when its
/// windup began.
pub fn contact(ctx: &ReducerContext, attacker: u32, victim: u32, outcome: &str, now: u64) {
    let trace = common::laws(ctx).heed_trace;
    if !(on(ctx) || trace) || attacker == 0 || attacker == victim {
        return;
    }
    let before = contact_at(victim, attacker);
    CONTACT.with(|c| {
        let mut c = c.borrow_mut();
        let v = c.entry(victim).or_default();
        v.retain(|(a, t)| *a != attacker && now.saturating_sub(*t) <= ENGAGEMENT_MS);
        v.push((attacker, now));
    });
    if let Some(viewer) = crate::combat::human(ctx, victim) {
        // A played victim: with heed on for players, the attacker joins its committed
        // `perceived` set here, in the blow's own transaction (when it sees it), so `masked` and
        // `perceived` never disagree on who receives what (docs/ATTENTION_BUDGET.md, "Player-side
        // interface"); its set in memory takes it as forced too, like a mind's.
        if applies(ctx, victim) {
            HEED.with(|m| {
                if let Some(s) = m.borrow_mut().get_mut(&victim) {
                    s.picks.retain(|p| p.id != attacker);
                    s.picks.insert(0, Pick::new(attacker, Place::Contact));
                    s.merit.remove(&attacker);
                    s.since.entry(attacker).or_insert(now);
                }
            });
            if crate::perception::sees_creature(ctx, victim, attacker, now) {
                crate::perception::admit(ctx, victim, viewer, attacker, now);
            }
        }
        return;
    }
    if applies(ctx, victim) {
        // The attacker is an individual from now on (forced), in this transaction: its place in the
        // set changes too, so every line this blow writes already names it.
        HEED.with(|m| {
            if let Some(s) = m.borrow_mut().get_mut(&victim) {
                s.picks.retain(|p| p.id != attacker);
                s.picks.insert(0, Pick::new(attacker, Place::Contact));
                s.merit.remove(&attacker);
                s.since.entry(attacker).or_insert(now);
            }
        });
    }
    if !trace {
        return;
    }
    let first = before.map_or(true, |t| now.saturating_sub(t) > ENGAGEMENT_MS);
    let w = WINDUPS.with(|w| w.borrow_mut().remove(&(attacker, victim)));
    let window = (common::laws(ctx).heed_contact_s * 1000.0) as u64;
    // Contact within the window before the windup began (the forced rule's own test then).
    let repeat_in_window = w.is_some_and(|w| w.contact) || w.is_none() && before.is_some_and(|t| now.saturating_sub(t) <= window);
    let (seen, heeded, ago) = match w {
        Some(w) => (w.seen as i8, w.heeded as i8, now.saturating_sub(w.at_ms) as i64),
        None => (-1, -1, -1),
    };
    if repeat_in_window && heeded == 0 {
        log::error!("heed invariant: a blow by #{attacker} reached #{victim} after contact within the window, from someone not an individual at its windup");
    }
    let (cap, hp) = (
        HEED.with(|m| m.borrow().get(&victim).map_or(0, |s| s.capacity)),
        ctx.db.vitals().id().find(victim).map(|v| common::needs(&v, now).hp / v.max_hp.max(1.0)).unwrap_or(0.0),
    );
    log::info!("heed blow a={attacker} v={victim} out={outcome} first={} repeat_in_window={} seen_at_windup={seen} heeded_at_windup={heeded} windup_ms={ago} cap={cap} health={hp:.3}", first as u8, repeat_in_window as u8);
}

/// A cue of `me`'s matched `other`, who is in its sight: it is `cued` for a while, and the event
/// pass decides whether it becomes an individual now. Returns whether it is one.
pub fn cued(ctx: &ReducerContext, me: &Character, at: (f32, f32), other: &NearCreature, now: u64) -> bool {
    if !applies(ctx, me.id) {
        return true;
    }
    HEED.with(|m| {
        if let Some(s) = m.borrow_mut().get_mut(&me.id) {
            s.cued.insert(other.id, now);
        }
    });
    if individual(ctx, me.id, other.id, now) {
        return true;
    }
    event(ctx, me, at, other, now, |c| c.cued = true)
}

/// `speaker` spoke to `me` (words to it, in its sight or not): the event pass with the speaker
/// `addressing` it. Returns whether the speaker is an individual to it afterwards.
pub fn addressed(ctx: &ReducerContext, me: &Character, speaker: u32, now: u64) -> bool {
    if !applies(ctx, me.id) || individual(ctx, me.id, speaker, now) {
        return true;
    }
    let (Some(mb), Some(sb)) = (ctx.db.body().id().find(me.id), ctx.db.body().id().find(speaker)) else { return false };
    let (at, sp) = (common::pos(&mb, now), common::pos(&sb, now));
    if !crate::perception::sees_creature(ctx, me.id, speaker, now) {
        return false;
    }
    let kind = ctx.db.character().id().find(speaker).map(|c| c.kind).unwrap_or_default();
    let c = NearCreature { id: speaker, kind: kind.as_str().into(), pos: sp, dist: common::dist(at, sp), facing: common::facing_at(&sb, now) };
    event(ctx, me, at, &c, now, |cand| cand.addressed_me_ago_s = Some(0.0))
}

/// The body is gone: its set, its contacts and its windups.
pub fn forget(id: u32) {
    OWN.with(|m| m.borrow_mut().remove(&id));
    HEED.with(|m| m.borrow_mut().remove(&id));
    CONTACT.with(|c| c.borrow_mut().remove(&id));
    WINDUPS.with(|w| w.borrow_mut().retain(|(a, v), _| *a != id && *v != id));
}

/// How many of `me`'s throng are players (for the mind service's level of detail: a player in a
/// mind's throng keeps it on stage; never shown to the model).
pub fn players_in(ctx: &ReducerContext, throng: &[NearCreature]) -> usize {
    throng.iter().filter(|c| crate::combat::human(ctx, c.id).is_some()).count()
}

fn self_state(ctx: &ReducerContext, me: &Character, now: u64) -> SelfState {
    let w = common::world(ctx);
    let v = ctx.db.vitals().id().find(me.id);
    let (health, hunger, energy, stamina, hurt) = v.map_or((100.0, 0.0, 100.0, 100.0, None), |v| {
        let n = common::needs(&v, now);
        (100.0 * n.hp / v.max_hp.max(1.0), n.hunger, n.energy, crate::breath::levels(&v, now).0, (v.hurt_ms != 0).then(|| now.saturating_sub(v.hurt_ms) as f32 / 1000.0))
    });
    SelfState { health, energy, hunger, stamina, night: common::night(ctx, &w, now), hurt_ago_s: hurt }
}

/// What one pass reads once for the character: its own state toward everyone it perceives.
struct Field<'a> {
    me: &'a Character,
    at: (f32, f32),
    heeded: &'a [u32],
    since: &'a HashMap<u32, u64>,
    in_sight: &'a HashMap<u32, u64>,
    cued: &'a HashMap<u32, u64>,
    reads: Reads,
    now: u64,
    sc: Rc<living_rules::script::Scripts>,
    /// Windups aimed at me now, by maker.
    winding: Vec<u32>,
    /// Who hurt me last, and how long ago (s).
    hurt: Option<(u32, f32)>,
    /// Who spoke or waved to me last, and how long ago (s).
    spoke: Vec<(u32, f32)>,
    acting: Option<u32>,
    contacts: Vec<(u32, u64)>,
    community: Option<u32>,
    /// A player's pins and focus (`heed_choice`), as weights for `chosen`.
    chosen: Vec<(u32, f32)>,
}

impl<'a> Field<'a> {
    #[allow(clippy::too_many_arguments)]
    fn new(ctx: &ReducerContext, me: &'a Character, at: (f32, f32), heeded: &'a [u32], since: &'a HashMap<u32, u64>, in_sight: &'a HashMap<u32, u64>, cued: &'a HashMap<u32, u64>, reads: Reads, now: u64) -> Field<'a> {
        let winding = ctx.db.activity().victim().filter(me.id).filter(|a| a.phase == 1 && a.ends_ms > now).map(|a| a.id).collect();
        let hurt = ctx.db.vitals().id().find(me.id).filter(|v| v.hurt_by != 0 && v.hurt_ms != 0).map(|v| (v.hurt_by, now.saturating_sub(v.hurt_ms) as f32 / 1000.0));
        let mut spoke = Vec::new();
        if let Some(st) = ctx.db.mind_state().id().find(me.id) {
            if st.speaker != 0 && st.heard_ms != 0 {
                spoke.push((st.speaker, now.saturating_sub(st.heard_ms) as f32 / 1000.0));
            }
            if st.hailer != 0 && st.hailed_ms != 0 {
                spoke.push((st.hailer, now.saturating_sub(st.hailed_ms) as f32 / 1000.0));
            }
        }
        let contacts = CONTACT.with(|c| c.borrow().get(&me.id).cloned().unwrap_or_default());
        let community = if reads.community { ctx.db.membership().member().find(me.id).map(|m| m.community) } else { None };
        // A player's pins and focus, while a person plays it (minds holding it read none).
        let chosen = if crate::combat::human(ctx, me.id).is_some() { ctx.db.heed_choice().actor().find(me.id).map(|c| chosen_weights(&c)).unwrap_or_default() } else { Vec::new() };
        Field { me, at, heeded, since, in_sight, cued, reads, now, sc: common::scripts(ctx), winding, hurt, spoke, acting: acting_on(ctx, me.id), contacts, community, chosen }
    }

    fn candidate(&self, ctx: &ReducerContext, c: &NearCreature) -> Candidate {
        let now = self.now;
        let id = c.id;
        let ch = ctx.db.character().id().find(id);
        // Coming toward me (m/s): set by the caller from the observer's `ClosingTracker`.
        let closing = 0.0;
        let person = &*c.kind == "person";
        let made_out = !(person && self.reads.made_out) || ch.as_ref().map_or(true, |t| !crate::perception::regard(ctx, self.me, t, now).far);
        let mut relations = 0u8;
        if let Some(t) = &ch {
            let me = self.me;
            if t.parent_a == me.id || t.parent_b == me.id || me.parent_a == t.id || me.parent_b == t.id || (t.parent_a != 0 && (t.parent_a == me.parent_a || t.parent_b == me.parent_b) && me.parent_a != 0) {
                relations |= h::rel::FAMILY;
            }
            if self.reads.relation {
                if crate::brain::relation_ok(ctx, me.id, id, "friend") {
                    relations |= h::rel::FRIEND;
                }
                if crate::brain::relation_ok(ctx, me.id, id, "enemy") {
                    relations |= h::rel::ENEMY;
                }
            }
            if self.reads.stranger && person && !crate::perception::knows_name(ctx, me, t) {
                relations |= h::rel::STRANGER;
            }
            if self.reads.community && self.community.is_some() && ctx.db.membership().member().find(id).map(|m| m.community) == self.community {
                relations |= h::rel::COMMUNITY;
            }
        }
        let v = crate::perception::visibly(ctx, &self.sc, id, now);
        let doing = v.as_ref().map(|v| {
            let shape = if v.combat { self.sc.shapes().get(&v.skill) } else { None };
            let mut is: Vec<String> = living_rules::doing::kinds(shape, self.sc.shows().get(&v.skill)).into_iter().map(str::to_string).collect();
            is.push(v.skill.clone());
            if let Some(u) = self.sc.ui(&v.skill) {
                is.push(u.label.clone());
            }
            Visible { is, phase: Some(v.phase), at_me: v.at(self.me.id, self.at, c.pos) }
        });
        let fighting = v.as_ref().is_some_and(|v| v.combat);
        let acting_on_heeded = v.as_ref().is_some_and(|v| v.target != 0 && v.target != self.me.id && self.heeded.contains(&v.target));
        // The age one sees (a scene's "a child", "an old stranger"), when made out.
        let stage = ch.as_ref().filter(|_| made_out).map(|t| match t.stage {
            0 => h::Stage::Infant,
            1 => h::Stage::Child,
            3 => h::Stage::Elder,
            _ => h::Stage::Adult,
        });
        Candidate {
            id,
            kind: c.kind.to_string(),
            stage,
            dist: c.dist,
            closing,
            made_out,
            relations,
            threatening: self.winding.contains(&id),
            doing,
            hurt_me_ago_s: self.hurt.filter(|(who, _)| *who == id).map(|(_, a)| a),
            addressed_me_ago_s: self.spoke.iter().filter(|(who, _)| *who == id).map(|(_, a)| *a).reduce(f32::min),
            acted_on: self.acting == Some(id),
            contact_ago_s: self.contacts.iter().find(|(a, _)| *a == id).map(|(_, t)| now.saturating_sub(*t) as f32 / 1000.0),
            cued: self.cued.get(&id).is_some_and(|t| now.saturating_sub(*t) < CUED_MS),
            chosen: self.chosen.iter().find(|(who, _)| *who == id).map(|(_, w)| *w),
            heeded_s: self.heeded.contains(&id).then(|| self.since.get(&id).map_or(0.0, |t| now.saturating_sub(*t) as f32 / 1000.0)),
            in_sight_s: self.in_sight.get(&id).map_or(0.0, |t| now.saturating_sub(*t) as f32 / 1000.0),
            fighting,
            fallen: false,
            acting_on_heeded,
            loud: false,
            lit: false,
        }
    }
}

/// A player's choice as weights: its focus [`FOCUS_WEIGHT`], each pin [`PIN_WEIGHT`] (a pinned
/// focus counts once, as the focus).
fn chosen_weights(c: &HeedChoice) -> Vec<(u32, f32)> {
    let mut out: Vec<(u32, f32)> = c.focus.map(|f| vec![(f, FOCUS_WEIGHT)]).unwrap_or_default();
    for &p in &c.pins {
        if !out.iter().any(|(id, _)| *id == p) {
            out.push((p, PIN_WEIGHT));
        }
    }
    out
}

/// Why `human_heed` refuses `input` from the played character `me` (its player `viewer`) now, if
/// it does: more than [`MAX_PINS`] pins, or a pin or the focus on a creature it does not perceive
/// now (its committed `perceived` set). The words for an unperceived id are the same whether or
/// not the id exists, so the refusal tells nothing of who is where.
pub fn refuse_choice(ctx: &ReducerContext, viewer: spacetimedb::Identity, input: &HeedInput) -> Option<String> {
    if input.pins.len() > MAX_PINS {
        return Some(format!("You can keep at most {MAX_PINS} others pinned at once."));
    }
    let set: std::collections::HashSet<u32> = ctx.db.perceived().viewer().filter(viewer).map(|p| p.body).collect();
    if input.pins.iter().chain(input.focus.iter()).any(|id| !set.contains(id)) {
        return Some(UNSEEN.to_string());
    }
    None
}

/// `human_heed`'s words for a pin or focus on someone the character does not perceive now.
pub const UNSEEN: &str = "You can only keep track of someone you can see now.";

/// The throng as a mind's scene tells it (docs/ATTENTION_BUDGET.md §5.1): one line per direction
/// and distance band, with no ids: about how many, how widely spread, which way they move, what
/// they visibly do, and their kinds.
pub fn throng_lines(ctx: &ReducerContext, me: u32, at: (f32, f32), throng: &[NearCreature], now: u64) -> Vec<serde_json::Value> {
    use serde_json::json;
    let sc = common::scripts(ctx);
    let band = |d: f32| if d < 8.0 { "close by" } else if d < 20.0 { "a stone's throw away" } else { "farther off" };
    let mut groups: Vec<((&'static str, &'static str), Vec<&NearCreature>)> = Vec::new();
    for c in throng {
        let key = (common::direction(at, c.pos), band(c.dist));
        match groups.iter_mut().find(|g| g.0 == key) {
            Some(g) => g.1.push(c),
            None => groups.push((key, vec![c])),
        }
    }
    groups
        .into_iter()
        .map(|((dir, dist), cs)| {
            let n = cs.len();
            let about = if n <= 5 { n } else { (n + 2) / 5 * 5 };
            let (cx, cy) = (cs.iter().map(|c| c.pos.0).sum::<f32>() / n as f32, cs.iter().map(|c| c.pos.1).sum::<f32>() / n as f32);
            let spread = cs.iter().map(|c| (c.pos.0 - cx).hypot(c.pos.1 - cy)).fold(0.0f32, f32::max) * 2.0;
            let across = if spread < 3.0 { "a few metres".to_string() } else { format!("about {:.0} m", (spread / 5.0).round().max(1.0) * 5.0) };
            // Which way they move, relative to me: the mean velocity along the line to me.
            let (mut toward, mut moving) = (0.0f32, 0usize);
            let mut fighting = 0usize;
            for c in &cs {
                if let Some(b) = ctx.db.body().id().find(c.id).filter(|b| now < b.next_ms && (b.vx != 0.0 || b.vy != 0.0)) {
                    moving += 1;
                    let (dx, dy) = (at.0 - c.pos.0, at.1 - c.pos.1);
                    toward += (b.vx * dx + b.vy * dy) / dx.hypot(dy).max(0.01);
                }
                if crate::perception::visibly(ctx, &sc, c.id, now).is_some_and(|v| v.combat) {
                    fighting += 1;
                }
            }
            let heading = if moving * 2 < n {
                "mostly still"
            } else if (toward / moving as f32) > 0.5 {
                "coming toward you"
            } else if (toward / moving as f32) < -0.5 {
                "moving away"
            } else {
                "moving about"
            };
            let visibly = match fighting {
                0 => "none fighting".to_string(),
                f if f == n => "all fighting".to_string(),
                f if f * 2 > n => "most fighting".to_string(),
                f => format!("{f} fighting"),
            };
            let mut kinds: Vec<&str> = Vec::new();
            for c in &cs {
                let k = &*c.kind;
                let word = match k {
                    "person" => "people",
                    "wolf" => "wolves",
                    "deer" => "deer",
                    _ => "creatures",
                };
                if !kinds.contains(&word) {
                    kinds.push(word);
                }
            }
            let _ = me;
            json!({"dir": dir, "dist": dist, "about": about, "across": across, "moving": heading, "visibly": visibly, "kinds": kinds.join(" and ")})
        })
        .collect()
}

/// How someone in a throng is referred to in a line ("someone in the throng to the east").
pub fn throng_label(ctx: &ReducerContext, observer: u32, other: u32, now: u64) -> String {
    let p = |id: u32| ctx.db.body().id().find(id).map(|b| common::pos(&b, now));
    match (p(observer), p(other)) {
        (Some(a), Some(b)) => format!("someone in the throng to the {}", common::direction(a, b)),
        _ => "someone in the throng".to_string(),
    }
}
