//! Behavior graph evaluation. Each character is evaluated about once per second (its
//! slot) and immediately after salient events. Evaluation reads only what the character
//! can perceive (sight radius), its own state and its mind's projections (relations,
//! places, judgments). Conditions and targets never consult observer truth beyond that.

use crate::act::{self, Resolved};
use crate::perceive::{self, percept};
use crate::tables::*;
use crate::common::{self, dist, direction, pos, Compiled, Needs, NearCreature};
use living_rules::graph::{self, Cond, Filter, Node, Target};
use spacetimedb::rand::Rng;
use spacetimedb::{ReducerContext, Table};
use std::rc::Rc;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum St {
    Ok,
    Fail,
    Run,
}

const MAX_VISITS: u32 = 160;
const ROOT_MARK: u16 = u16::MAX - 1;
const FAIL_MARK: u16 = u16::MAX - 2;
pub(crate) const REFLECT_MARK: u16 = u16::MAX - 3;
thread_local! {
    /// What each character looked at lately (docs/BATTLE_SCALE.md, fix 1): the fast path in front
    /// of `familiar`, keyed as `recently_seen` keys things (a creature's id, `0x4000_0000 | a
    /// structure`, `0x8000_0000 | a region`, `FAR_MARK | a figure too far to make out`), with when.
    /// Sized to what it sees, not capped at 96 (it thrashed in a battle), and kept off `mind_state`
    /// so the row is not rewritten with it at every evaluation. Lost on a module update: then the
    /// durable `familiar` rows answer.
    static SEEN: std::cell::RefCell<std::collections::HashMap<u32, std::collections::HashMap<u32, u64>>> = std::cell::RefCell::new(std::collections::HashMap::new());
    /// Familiarity rows each character has added since its count was last checked.
    static FAMILIAR_NEW: std::cell::RefCell<std::collections::HashMap<u32, u32>> = std::cell::RefCell::new(std::collections::HashMap::new());
    /// When each character last looked for what is new to it (`noticed`, fix 2).
    static NOTICED_AT: std::cell::RefCell<std::collections::HashMap<u32, u64>> = std::cell::RefCell::new(std::collections::HashMap::new());
    /// When each character last looked at the ground (`known::mark`), at the noticing cadence.
    static LOOKED_AT: std::cell::RefCell<std::collections::HashMap<u32, u64>> = std::cell::RefCell::new(std::collections::HashMap::new());
    /// Attention cues (`Ev::cues`), per character: when its cues were last checked, and the
    /// (cue, thing) pairs that have fired or were held back by the cooldown and have matched at
    /// every check since, so a cue fires when a thing begins to match, not while it goes on
    /// matching. Lost on a module update: the durable cooldown (`Cue::fired`) then holds.
    static CUE_HELD: std::cell::RefCell<std::collections::HashMap<u32, (u64, Vec<(u64, u64)>)>> = std::cell::RefCell::new(std::collections::HashMap::new());
    /// The hunger and energy levels where each body's need rates change, from the law's last
    /// answer for it (`NeedLaw::cuts`).
    static NEED_CUTS: std::cell::RefCell<std::collections::HashMap<u32, [f32; 4]>> = std::cell::RefCell::new(std::collections::HashMap::new());
    /// When each person last checked for, and last felt, knowing something alone (kept here:
    /// evaluator marks are reset when a new plan is installed).
    static LEGACY: std::cell::RefCell<std::collections::HashMap<u32, (u64, u64)>> = std::cell::RefCell::new(std::collections::HashMap::new());
    /// First sights that ask for a thought (`first_sight_thinks`, docs/FIRST_SIGHT.md), per
    /// character: when one last brought it to think (its gap), and what is still owed. Lost on
    /// a module update: the first-sight lines themselves are durable.
    static FIRST_SIGHT: std::cell::RefCell<std::collections::HashMap<u32, FirstSightAsk>> = std::cell::RefCell::new(std::collections::HashMap::new());
}

/// A character's first sights of people it cannot place that have yet to bring it to think.
#[derive(Clone, Debug, Default, PartialEq)]
struct FirstSightAsk {
    /// When a first sight last brought it to think (`first_sight_gap_s`), 0 never.
    last_ms: u64,
    /// The unplaced people of first sights not yet thought over, with their part of the line
    /// ("a stranger, 7 tiles east, wait"), and since when the oldest is owed (0: none).
    owed: Vec<(u32, String)>,
    since_ms: u64,
}

/// A refused first-sight request is tried again at later looks for at most this long, while
/// the person stays in sight and still cannot be placed.
const FIRST_SIGHT_OWED_MS: u64 = 60_000;
/// The body's alarms before the `status_of` law gave them (bits 1, 2, 4, 8 and 64): cleared.
const OLD_BODY_ALARMS: u32 = 1 | 2 | 4 | 8 | 64;
/// The `status_of` law's alarms, one bit each by its words (`alarm_bit`).
const LAW_ALARMS: u32 = 0xFFFF_0000;

/// An alarm's bit among `LAW_ALARMS`: by its words, so two statuses with the same alarm (badly
/// hurt, barely alive) are one episode.
fn alarm_bit(text: &str) -> u32 {
    let h = text.bytes().fold(2166136261u32, |h, b| (h ^ b as u32).wrapping_mul(16777619));
    1 << (16 + h % 16)
}

/// Alert bits for ongoing situations (bits 16..31 are the body's alarms; 16, 32 and 128 drives).
const IN_CROWD: u32 = 1 << 8;
const WOLF_NEAR: u32 = 1 << 9;
/// Something heard near and out of sight (only while sight has a field).
const SOUND_NEAR: u32 = 1 << 10;
/// Familiarity rows kept per character (docs/BATTLE_SCALE.md, fix 1): above what can be in sight
/// in the densest place (a 200-character battle among its remains), so it is never what is in
/// view that is forgotten. Over it, the oldest unseen rows go: never one seen within
/// `FAMILIAR_KEEP_MS`, nor one whose thing is in the character's seen set (in view lately).
const FAMILIAR_LIMIT: usize = 2_048;
/// A familiarity row touched this recently is not pruned (twice its 30 s touch period).
const FAMILIAR_KEEP_MS: u64 = 60_000;
/// Something looked at within this long counts as still in view (the seen set's horizon).
const SEEN_MS: u64 = 90_000;
/// What is new to a character is looked for about once a second (fix 2): at most once per this,
/// a little under the 1 Hz slot, since a slot can come a tick early (a strict 1,000 ms skipped
/// every other second).
const NOTICE_MS: u64 = 900;
/// Marks at 0xC000 | node: when a desire last began to act.
const DESIRE_MARK: u16 = 0xC000;
/// Set when the current plan's routine completes; cleared by the next install.
const PLAN_DONE_MARK: u16 = 0xCFFF;
/// How long an animal's impulse keeps any pull.
const IMPULSE_MS: f32 = 60_000.0;
/// How long being greeted weighs on the `hailed` desire signal.
const HAILED_MS: u64 = 6_000;

struct Scene {
    creatures: Vec<NearCreature>,
    /// Heard and not seen (only while sight depends on facing), nearest first.
    heard: Vec<NearCreature>,
    resources: Vec<(ResourceNode, f32)>,
    /// Built when first asked for (`Ev::structures`): an evaluation that reads no structure (a
    /// fighter's at combat cadence) does not gather every remains in sight. The same set either way.
    structures: Option<Vec<(Structure, f32)>>,
}

struct Ev<'a> {
    ctx: &'a ReducerContext,
    now: u64,
    w: World,
    me: Character,
    at: (f32, f32),
    needs: Needs,
    vit: Vitals,
    st: MindState,
    orig: MindState,
    g: Rc<Compiled>,
    scene: Option<Scene>,
    /// Creatures smelled beyond sight (built on first use).
    smelled: Option<Vec<NearCreature>>,
    /// While resolving a target the body acts on: smelled creatures count (see `sensed`).
    smell: bool,
    running: Option<u16>,
    path: Vec<u16>,
    status: String,
    visits: u32,
    last_fail: String,
    want: (String, u32),
    /// What a graph leaf's answer (accept, decline) names: a trade offer, a record (0: none).
    answers: (u64, u64),
    /// The `run` of the action being started (a `Do` node's).
    run: Option<bool>,
    /// The distances of a movement intent being started (a `Do` node's).
    spacing: living_rules::steer::Spacing,
    /// Node of the activity in progress if it is work that completes on its own (see `latches`).
    latched: Option<u16>,
    /// A deliberate act holds the body: graph leaves wait, except reflexes (see `acts.rs`).
    acting: bool,
}

/// Work that, once begun under an `if`, is finished even after the `if`'s condition stops
/// holding (sleeping until rested, not until barely awake). Movement and combat stay reactive.

pub fn evaluate(ctx: &ReducerContext, id: u32, now: u64) {
    let load = common::detail_span("brain.load");
    let Some(me) = ctx.db.character().id().find(id) else { return };
    if !me.alive {
        return;
    }
    let (Some(st), Some(body), Some(vit)) = (ctx.db.mind_state().id().find(id), ctx.db.body().id().find(id), ctx.db.vitals().id().find(id)) else { return };
    common::count(|k| k.evals += 1);
    let w = common::world(ctx);
    let at = pos(&body, now);
    let mut cur = ctx.db.activity().id().find(id);
    let Some(vit) = settle_needs(ctx, &me, vit, at, &w, cur.as_ref(), now) else { return };
    perceive::infant_distress(ctx, &me, at, now);
    let needs = common::needs(&vit, now);
    let Some(g) = common::compiled(ctx, id, st.revision) else {
        log::warn!("character {id} has no valid graph at revision {}", st.revision);
        return;
    };
    // A deliberate act that cannot reach its target gives up after a while (and the next
    // one waiting may start in its place).
    if let Some(a) = cur.clone().filter(|a| crate::acts::overdue(ctx, a, now)) {
        act::cancel(ctx, a, now, Some("you could not get to it in time"));
        cur = ctx.db.activity().id().find(id);
    }
    let acting = cur.as_ref().map_or(false, |a| act::held(a.node));
    let mut ev = Ev { ctx, now, w, me, at, needs, vit, orig: st.clone(), st, g, scene: None, smelled: None, smell: false, running: None, path: Vec::new(), status: String::new(), visits: 0, last_fail: String::new(), want: (String::new(), 0), answers: (0, 0), run: None, spacing: Default::default(), latched: None, acting };
    // A pace aside (an `aside` skill in the script) is a short walk that finishes on its own too.
    let sc = common::scripts(ctx);
    ev.latched = cur.filter(|a| a.revision == ev.st.revision && (sc.skills().get(&a.skill).is_some_and(|k| k.latch) || sc.shows().aside(&a.skill))).map(|a| a.node);
    drop(load);
    let alerts = common::detail_span("brain.alerts");
    ev.alerts();
    drop(alerts);
    let root = ev.g.clone();
    let played = !ev.me.ai;
    let result = {
        let _span = common::span("brain.graph");
        ev.run(&root.root, 0)
    };
    let _span = common::span("brain.after");
    ev.after(result, &root.root);
    drop(_span);
    let _span = common::detail_span("brain.slept");
    // Fell asleep, or woke (and thinks on what waited): perceive::slept.
    if let Some(me) = ctx.db.character().id().find(id) {
        perceive::slept(ctx, &me, now);
    }
    if played && result != St::Run {
        crate::command_done(ctx, id, now);
    }
}

/// Resolve a target for a deliberate act exactly as a graph leaf would (only what the
/// character perceives, sight or smell, its own places and remembered people).
pub fn resolve_for(ctx: &ReducerContext, id: u32, t: &Target, now: u64) -> Option<Resolved> {
    let me = ctx.db.character().id().find(id)?;
    let st = ctx.db.mind_state().id().find(id)?;
    let body = ctx.db.body().id().find(id)?;
    let vit = ctx.db.vitals().id().find(id)?;
    let g = common::compiled(ctx, id, st.revision)?;
    let at = pos(&body, now);
    let needs = common::needs(&vit, now);
    let mut ev = Ev { ctx, now, w: common::world(ctx), me, at, needs, vit, orig: st.clone(), st, g, scene: None, smelled: None, smell: false, running: None, path: Vec::new(), status: String::new(), visits: 0, last_fail: String::new(), want: (String::new(), 0), answers: (0, 0), run: None, spacing: Default::default(), latched: None, acting: false };
    ev.sensed(t)
}

/// Re-anchor needs when their rate inputs change; handles death from needs. `cur` is the
/// character's activity. The rate key is computed from the few facts the rates depend on;
/// the full facts are gathered only when it changes.
fn settle_needs(ctx: &ReducerContext, me: &Character, mut v: Vitals, at: (f32, f32), w: &World, cur: Option<&Activity>, now: u64) -> Option<Vitals> {
    let n = common::needs(&v, now);
    if n.hp <= 0.0 {
        use living_rules::outcome::death;
        let (cause, code) = if n.hunger >= 100.0 {
            ("starvation", death::STARVED)
        } else if common::night(ctx, w, now) && me.kind == "person" {
            ("cold and exposure", death::COLD)
        } else {
            ("exhaustion", death::EXHAUSTED)
        };
        act::die(ctx, me.id, cause, now, 0, code);
        return None;
    }
    let night = common::night(ctx, w, now);
    // How dark it is matters to the key only when the rates law reads it (an eased dusk).
    let dark = if common::scripts(ctx).reads("rates", "daylight") { common::dark(ctx, w, now) } else if night { 1.0 } else { 0.0 };
    // A fire that goes out changes this on the next look (its `lit_until_ms` passes): nothing
    // has to be told when it burns down.
    let warm = act::warmth(ctx, at, now);
    let (near_fire, near_shelter) = (warm.fire, warm.shelter);
    let cloak = common::inv_count(ctx, me.id as u64, "cloak") > 0;
    let season = common::season(ctx, now);
    let activity = cur.filter(|a| a.phase == 1).map_or("", |a| a.skill.as_str());
    // The levels where the state's rates change are the law's (`starving_at`, `fed_below`,
    // `rested_above`, `spent_at`), as it last answered for this body. Unknown (a fresh module
    // instance): ask the law again.
    let cuts = NEED_CUTS.with(|c| c.borrow().get(&me.id).copied());
    let [starving_at, fed_below, rested_above, spent_at] = cuts.unwrap_or([f32::NAN; 4]);
    let key = (cuts.is_some() as u32)
        | (night as u32) << 1
        | ((n.hunger >= starving_at) as u32) << 2
        | ((n.hunger < fed_below) as u32) << 3
        | ((n.energy > rested_above) as u32) << 4
        | ((n.energy <= spent_at) as u32) << 5
        | (near_fire as u32) << 6
        | (near_shelter as u32) << 7
        | ((activity == "sleep") as u32) << 8
        | ((activity == "rest") as u32) << 9
        | (cloak as u32) << 10
        | ((season == "winter") as u32) << 11
        | (crate::town::raining(ctx) as u32) << 12
        | ((dark * 20.0).round() as u32) << 13;
    if cuts.is_some() && key == v.rate_key {
        return Some(v);
    }
    // Profiled: what a recompute costs (the facts and the law), and how many there are.
    let _timer = common::span("needs.rates");
    let facts = act::facts(ctx, me.id, now);
    let sc = common::scripts(ctx);
    let hour = common::hour(w, now);
    let sctx = living_rules::script::SkillCtx { actor: facts, night, dark, hour, season: season.into(), raining: crate::town::raining(ctx), ..Default::default() };
    let _ = at;
    // Profiled apart: the law itself, asked only for a state no body has been in since the
    // script revision (the rest are answers kept per state, finished per body).
    let _law_timer = if common::profiling() && !sc.need_law_kept(&sctx) { common::span("needs.rates.law") } else { None };
    let law = sc.need_law(&sctx);
    drop(_law_timer);
    let mut key = key;
    if let Ok(c) = law.as_ref().map(|l| l.cuts().unwrap_or([f32::INFINITY, f32::NEG_INFINITY, f32::INFINITY, f32::NEG_INFINITY])) {
        NEED_CUTS.with(|m| m.borrow_mut().insert(me.id, c));
        // The key as the new thresholds read it, so the next look does not ask again.
        key = (key & !0b11_1101) | 1 | ((n.hunger >= c[0]) as u32) << 2 | ((n.hunger < c[1]) as u32) << 3 | ((n.energy > c[2]) as u32) << 4 | ((n.energy <= c[3]) as u32) << 5;
    }
    if let Ok(r) = law.map(|l| l.rates(&sctx.actor)) {
        common::settle(ctx, &mut v, now);
        v.hp_rate = r.hp_per_min;
        v.hunger_rate = r.hunger_per_min;
        v.energy_rate = r.energy_per_min;
        v.rate_key = key;
        ctx.db.vitals().id().update(v.clone());
    }
    Some(v)
}

impl<'a> Ev<'a> {
    fn scene(&mut self) -> &Scene {
        if self.scene.is_none() {
            let _span = common::span("brain.scene");
            let r = common::sight_for(self.ctx, self.me.id, &self.w, self.now);
            // What the body sees: within its sight and with a clear sight line (the rule every
            // observer perceives by, `perception::in_sight`).
            let (creatures, heard) = crate::perception::sensed(self.ctx, self.me.id, self.at, r, self.now);
            common::note_scene(creatures.len());
            let resources = common::resources_near(self.ctx, self.at, r);
            self.scene = Some(Scene { creatures, heard, resources, structures: None });
        }
        self.scene.as_ref().unwrap()
    }

    /// The structures in sight, nearest first (the scene's, gathered when first asked for).
    fn structures(&mut self) -> &[(Structure, f32)] {
        self.scene();
        if self.scene.as_ref().is_some_and(|s| s.structures.is_none()) {
            let _span = common::detail_span("brain.scene.structures");
            let r = common::sight_for(self.ctx, self.me.id, &self.w, self.now);
            let v = common::structures_near(self.ctx, self.at, r);
            self.scene.as_mut().unwrap().structures = Some(v);
        }
        self.scene.as_ref().and_then(|s| s.structures.as_deref()).unwrap_or(&[])
    }

    fn smelled(&mut self) -> &[NearCreature] {
        if self.smelled.is_none() {
            let r = common::sight_for(self.ctx, self.me.id, &self.w, self.now);
            let me = self.me.id;
            let v = common::smelled_near(self.ctx, me, &self.me.kind, self.at, r, self.now);
            self.smelled = Some(v);
        }
        self.smelled.as_deref().unwrap()
    }

    fn mark_recent(&self, node: u16, within_ms: u64) -> bool {
        self.st.marks.iter().any(|m| m.node == node && self.now.saturating_sub(m.at_ms) < within_ms)
    }

    fn set_mark(&mut self, node: u16) {
        self.st.marks.retain(|m| m.node != node);
        self.st.marks.push(Mark { node, at_ms: self.now });
        if self.st.marks.len() > 24 {
            self.st.marks.remove(0);
        }
    }

    /// Weighted desires: score each from the body's state and the character's stances, try
    /// the strongest first (the one already acting gets a small bonus, so choices do not
    /// flicker), and remember when each last acted (for "longing").
    fn desires(&mut self, ds: &[graph::Desire], id: u16) -> St {
        let mut ids = Vec::with_capacity(ds.len());
        let mut next = id + 1;
        for _ in ds {
            ids.push(next);
            next += self.g.sizes.get(next as usize).copied().unwrap_or(1);
        }
        let current = self.cursor(id) as usize;
        let hunger = (self.needs.hunger / 100.0).clamp(0.0, 1.0);
        let tired = ((100.0 - self.needs.energy) / 100.0).clamp(0.0, 1.0);
        let hurt = (1.0 - self.needs.hp / self.vit.max_hp.max(1.0)).clamp(0.0, 1.0);
        // Sleepiness follows the dark: 1 at night, 0 by day, and between them through an eased
        // dusk or dawn (the `daylight` law), so it does not flip in the tick the light does.
        let night = common::dark(self.ctx, &self.w, self.now);
        let me = self.me.id;
        let now = self.now;
        // The body's own day (its rhythm): its bedtime, its evening and its working hours.
        let (bedtime, evening, work_hours) = if ds.iter().any(|d| d.weight.bedtime != 0.0 || d.weight.evening != 0.0 || d.weight.work_hours != 0.0) {
            let p = common::day_phase(self.ctx, me, common::hour(&self.w, now));
            let one = |b: bool| if b { 1.0 } else { 0.0 };
            (one(p.bedtime), one(p.evening), one(p.work))
        } else {
            (0.0, 0.0, 0.0)
        };
        // An attack or a threat aimed at me right now.
        let threatened = if self.ctx.db.activity().victim().filter(me).any(|a| a.phase == 1 && a.ends_ms > now) { 1.0 } else { 0.0 };
        // Company is one's own kind (people for a person, the herd or pack for an animal).
        let kind = self.me.kind.clone();
        let people = self.scene().creatures.iter().filter(|c| *c.kind == *kind).count() as f32;
        let alone = if people == 0.0 { 1.0 } else { 0.0 };
        let company = (people / 5.0).min(1.0);
        let winter = if common::season(self.ctx, now) == "winter" { 1.0 } else { 0.0 };
        let starving = if self.needs.hunger >= 90.0 { 1.0 } else { 0.0 };
        let exhausted = if self.needs.energy <= 10.0 { 1.0 } else { 0.0 };
        let rain = if ds.iter().any(|d| d.weight.rain != 0.0) && crate::town::raining(self.ctx) { 1.0 } else { 0.0 };
        let hailed = if self.hailed(HAILED_MS) { 1.0 } else { 0.0 };
        let commotion = if ds.iter().any(|d| d.weight.commotion != 0.0) && self.resolve(&graph::Target::Commotion).is_some() { 1.0 } else { 0.0 };
        let courted = if ds.iter().any(|d| d.weight.courted != 0.0) && self.resolve(&graph::Target::Suitor).is_some() { 1.0 } else { 0.0 };
        let judgments: Vec<(String, f32)> = if ds.iter().any(|d| !d.weight.believes.is_empty()) {
            self.ctx.db.judgment().actor().filter(me).map(|j| (j.key.to_lowercase(), j.value)).collect()
        } else {
            Vec::new()
        };
        // An animal's impulse is brief: its pull fades over about a minute after it arises, and
        // the animal's standing drives (feeding, mating, its herd or pack) take over again.
        let impulse = if self.me.kind != "person" {
            let age = self.ctx.db.brain().id().find(self.me.id).map_or(0, |b| self.now.saturating_sub(b.installed_ms));
            (1.0 - age as f32 / IMPULSE_MS).max(0.0)
        } else {
            1.0
        };
        let plan_label = format!("routine:{}", graph::PLAN_ROUTINE);
        let is_plan = |n: &Node| matches!(n, Node::First(c) if c.label.as_deref().is_some_and(|l| l.eq_ignore_ascii_case(&plan_label)));
        let mut order: Vec<(f32, usize)> = ds
            .iter()
            .enumerate()
            .map(|(i, d)| {
                let w = &d.weight;
                let last = self.st.marks.iter().find(|m| m.node == DESIRE_MARK | ids[i]).map(|m| m.at_ms);
                let longing = last.map_or(1.0, |t| (now.saturating_sub(t) as f32 / 3_600_000.0).min(1.0));
                let mut s = w.base + w.hunger * hunger + w.tired * tired + w.hurt * hurt + w.night * night + w.day * (1.0 - night) + w.threatened * threatened + w.alone * alone + w.company * company + w.winter * winter + w.longing * longing + w.courted * courted + w.starving * starving + w.exhausted * exhausted + w.rain * rain + w.hailed * hailed + w.commotion * commotion + w.bedtime * bedtime + w.evening * evening + w.work_hours * work_hours;
                for (k, v) in &w.believes {
                    let j = judgments.iter().find(|(key, _)| key == &k.to_lowercase()).map(|(_, x)| *x).unwrap_or(0.5);
                    s += v * j;
                }
                if is_plan(&d.body) {
                    s *= impulse;
                }
                if current == i + 1 {
                    s += 0.1;
                }
                (s, i)
            })
            .collect();
        order.sort_by(|a, b| b.0.total_cmp(&a.0));
        // A plan that has been carried out is done: it stops competing until the mind makes a new one.
        let plan_done = self.st.marks.iter().any(|m| m.node == PLAN_DONE_MARK);

        for (score, i) in order {
            if score <= 0.0 {
                break;
            }
            let plan = is_plan(&ds[i].body);
            if plan && (plan_done || impulse <= 0.0) {
                continue;
            }
            let r = self.run(&ds[i].body, ids[i]);
            if plan && r == St::Ok {
                self.set_mark(PLAN_DONE_MARK);
                self.deliberate("I finished my plan.");
            }
            if r != St::Fail {
                if current != i + 1 {
                    self.set_cursor(id, i as u16 + 1);
                    self.set_mark(DESIRE_MARK | ids[i]);
                }
                return r;
            }
        }
        self.set_cursor(id, 0);
        St::Fail
    }

    /// Someone greeted me within `ms` (an answer to my own greeting does not count).
    fn hailed(&self, ms: u64) -> bool {
        self.st.hailer != 0 && self.st.hailed_ms != 0 && self.now.saturating_sub(self.st.hailed_ms) <= ms
    }

    fn cursor(&self, node: u16) -> u16 {
        self.st.cursors.iter().find(|c| c.node == node).map(|c| c.idx).unwrap_or(0)
    }

    fn set_cursor(&mut self, node: u16, idx: u16) {
        self.st.cursors.retain(|c| c.node != node);
        if idx != 0 {
            self.st.cursors.push(Cursor { node, idx });
        }
    }

    fn deliberate(&mut self, reason: &str) {
        if self.me.ai {
            perceive::request_deliberation(self.ctx, self.me.id, reason, self.now);
        }
    }

    fn run(&mut self, n: &Node, id: u16) -> St {
        self.visits += 1;
        if self.visits > MAX_VISITS {
            return St::Fail;
        }
        self.path.push(id);
        let r = self.run_inner(n, id);
        if r != St::Run {
            self.path.pop();
        }
        r
    }

    fn child_ids(&self, id: u16, count: usize) -> Vec<u16> {
        let mut out = Vec::with_capacity(count);
        let mut next = id + 1;
        for _ in 0..count {
            out.push(next);
            next += self.g.sizes.get(next as usize).copied().unwrap_or(1);
        }
        out
    }

    fn run_inner(&mut self, n: &Node, id: u16) -> St {
        match n {
            Node::Desires(ds) => self.desires(ds, id),
            // Routines are inlined when the graph is compiled; a stray call does nothing.
            Node::Routine(_) => St::Fail,
            Node::First(c) => {
                let ids = self.child_ids(id, c.children.len());
                for (ch, cid) in c.children.iter().zip(ids) {
                    let s = self.run(ch, cid);
                    if s != St::Fail {
                        return s;
                    }
                }
                St::Fail
            }
            Node::Seq(c) => {
                let ids = self.child_ids(id, c.children.len());
                let mut i = self.cursor(id) as usize;
                while i < c.children.len() {
                    match self.run(&c.children[i], ids[i]) {
                        St::Run => {
                            self.set_cursor(id, i as u16);
                            return St::Run;
                        }
                        St::Fail => {
                            self.set_cursor(id, 0);
                            return St::Fail;
                        }
                        St::Ok => i += 1,
                    }
                    if self.visits > MAX_VISITS {
                        self.set_cursor(id, i as u16);
                        return St::Run;
                    }
                }
                self.set_cursor(id, 0);
                St::Ok
            }
            Node::If(i) => {
                let then_id = id + 1;
                let then_end = then_id + self.g.sizes.get(then_id as usize).copied().unwrap_or(1);
                let latched = self.latched.map_or(false, |n| n >= then_id && n < then_end);
                let holds = latched || {
                    let _span = common::detail_span("brain.cond");
                    self.cond(&i.cond)
                };
                if holds {
                    self.run(&i.then, then_id)
                } else if let Some(e) = &i.otherwise {
                    let else_id = then_id + self.g.sizes.get(then_id as usize).copied().unwrap_or(1);
                    self.run(e, else_id)
                } else {
                    St::Fail
                }
            }
            Node::Do(a) => {
                // A leaf that has finished is done, whether or not its target is still in sight
                // (a back_off or a flight that took it out of sight succeeded all the same).
                if let Some(done) = self.finished(id) {
                    return done;
                }
                let sensed = a.target.as_ref().map(|t| {
                    let _span = common::detail_span("brain.target");
                    self.sensed(t)
                });
                let target = match &a.target {
                    Some(t) => match sensed.flatten() {
                        Some(r) => r,
                        None => {
                            // Movement under way toward or away from a creature (an intent, a
                            // flight, a `goto` to someone, an approach to act on them) goes by where
                            // it was last seen until steering loses it (`motion::held`: a pursuit
                            // goes to the last-seen place, a flight runs from it): one rule for a
                            // graph's and an act's, not the next evaluation.
                            if living_rules::steer::INTENTS.contains(&a.skill.as_str()) || matches!(a.skill.as_str(), "flee" | "goto") || self.approaching(id) {
                                if let Some(act) = self.ctx.db.activity().id().find(self.me.id).filter(|x| x.node == id && x.revision == self.st.revision) {
                                    self.running = Some(id);
                                    self.status = act.label;
                                    return St::Run;
                                }
                            }
                            return self.leaf_fail(id, &format!("{}: no {} in sight", a.skill, graph::describe_target(t)));
                        }
                    },
                    None => Resolved::none(),
                };
                self.want = (a.want.clone().unwrap_or_default(), a.want_qty.unwrap_or(0));
                self.answers = (a.offer.unwrap_or(0), a.record.unwrap_or(0));
                self.run = a.run;
                self.spacing = a.spacing();
                self.leaf(id, &a.skill, target, a.item.as_deref().unwrap_or(""), a.qty.unwrap_or(0), a.text.as_deref().unwrap_or(""), a.topic.as_deref().unwrap_or(""), graph::describe(n))
            }
            Node::Wait(s) => self.leaf(id, "wait", Resolved::none(), "", s.round().max(1.0) as u32, "", "", graph::describe(n)),
            Node::Say(s) => {
                // Pacing: a say node speaks at most once per 45 s, so a looping graph does not
                // chatter. The mark is set only when the line is actually spoken.
                if self.mark_recent(id, 45_000) {
                    return St::Ok;
                }
                let to = match &s.to {
                    Some(t) => match self.resolve(t) {
                        Some(r) if r.class == 3 => r.id as u32,
                        Some(_) => return self.say_failed(id, n, &format!("{} is not someone to speak to", graph::describe_target(t))),
                        None => return self.say_failed(id, n, &format!("no {} in sight", graph::describe_target(t))),
                    },
                    None => 0,
                };
                // Said already (say-once): a mind's plan does not say again nearly the line it said
                // to the same person within 45 s. A plan's install clears the node's own mark, so a
                // plan whose routine already spoke its first line before the install would say it
                // twice (ew2: Mirren Quill, 2.9 s apart); the chronicle keeps what was said across
                // the install. Only that: a line to the room (its hearers are whoever is near when
                // it is said: a crier's "Fresh bread!"), a graph the admin or a scene installed,
                // a player's lines, a deliberation's own line and talk turns are never held back.
                if to != 0 && self.from_mind() && crate::speech::said_to_recently(self.ctx, self.me.id, to, &s.text, self.now) {
                    self.set_mark(id);
                    self.status = format!("already said: {}", graph::describe(n));
                    return St::Ok;
                }
                // Within the speaking limit the line waits its turn (a second line right after
                // the first, or a graph installed just after one spoke) instead of being lost.
                let way = s.way.as_deref().unwrap_or("say");
                if crate::speech::too_soon_to_speak(self.ctx, self.me.id, way, self.now) {
                    self.status = format!("about to {}", graph::describe(n));
                    return St::Run;
                }
                // A queued line to someone is not said into the air (`speech_truth`): one the
                // conversation has moved past is dropped, and one whose addressee is beyond what
                // the way carries as it comes due is told to the speaker instead of said. (A way
                // with a reach of its own, a whisper, refuses that in its check's words.)
                if to != 0 && common::laws(self.ctx).speech_truth {
                    if self.line_overtaken(id, to) {
                        self.set_mark(id);
                        self.status = format!("let go of {} (the talk moved on)", graph::describe(n));
                        return St::Ok;
                    }
                    // Someone else addressed them since this plan was installed (or since this
                    // node last spoke), and I heard it: under `heard_first_rethinks` the line waits
                    // while my mind thinks again with that line in front of it. Only a mind's plan.
                    if let Some(heard) = self.heard_first(id, to) {
                        self.set_mark(id);
                        crate::speech::held_for_another(self.ctx, self.me.id, to, &s.text, &heard, self.now);
                        self.status = format!("held {} (another spoke to them first)", graph::describe(n));
                        return St::Ok;
                    }
                    let sc = common::scripts(self.ctx);
                    if let Some(w) = sc.way(way).filter(|w| w.reach <= 0.0) {
                        if !crate::speech::within_reach(self.ctx, w, self.at, to, self.now) {
                            return match crate::speech::unsaid(self.ctx, self.me.id, to, way, &s.text, self.now) {
                                Ok(()) => {
                                    self.set_mark(id);
                                    St::Ok
                                }
                                Err(why) => self.say_failed(id, n, &why),
                            };
                        }
                    }
                }
                match crate::speech::speak(self.ctx, self.me.id, &s.text, to, way, self.now) {
                    Ok(()) => {
                        self.set_mark(id);
                        St::Ok
                    }
                    Err(why) => self.say_failed(id, n, &why),
                }
            }
            Node::Think(reason) => {
                // A fresh decision is not immediately second-guessed.
                let settled = self.now.saturating_sub(self.st.deliberated_ms) > 45_000;
                if settled && !self.mark_recent(id, 90_000) {
                    self.set_mark(id);
                    let r = reason.clone();
                    self.deliberate(&r);
                }
                St::Ok
            }
        }
    }

    /// When the decision that installed this mind's plan perceived what it decided on: its install
    /// thought's time less the model's time (`mind::decided_since`, from the thought row the
    /// install wrote at `installed_ms`). Before talk-turns the windows below began at the install,
    /// so what happened while the model thought (a reply already given in conversation) was not
    /// "since" and the plan's line was said anyway (play-test 6).
    fn decided_ms(&self, brain: &Brain) -> u64 {
        self.ctx
            .db
            .thought()
            .actor()
            .filter(self.me.id)
            .filter(|t| t.at_ms == brain.installed_ms && t.kind != "error")
            .map(|t| brain.installed_ms.saturating_sub(t.latency_ms as u64))
            .min()
            .unwrap_or(brain.installed_ms)
    }

    /// Whether the graph running is a mind's plan (`brain.source = "mind"`), not one the admin,
    /// a scene, a player's command or the battle harness installed.
    fn from_mind(&self) -> bool {
        self.ctx.db.brain().id().find(self.me.id).is_some_and(|b| b.source == "mind")
    }

    /// Whether a mind's plan's queued line to `to` (say node `id`) has been overtaken by the
    /// conversation (`speech_truth`): since the decision that installed the plan perceived its
    /// scene (`decided_ms`), or since this node last
    /// spoke, `to` spoke to me (a line to me, or to no one in particular that the authority
    /// marked as for me, salience 0.8 and above), or I spoke to them other than by this plan's
    /// own say nodes (a conversation turn's reply). The plan's line was meant for a
    /// conversation that has moved on; saying it now answers twice. Lines said in the plan's
    /// own install (its deliberation's `say`) are not after it. Only a mind's plan: a routine's
    /// or an instinct's say is the body's habit, not a line queued for one conversation.
    fn line_overtaken(&self, id: u16, to: u32) -> bool {
        let Some(brain) = self.ctx.db.brain().id().find(self.me.id).filter(|b| b.source == "mind") else { return false };
        let own_mark = self.st.marks.iter().find(|m| m.node == id).map_or(0, |m| m.at_ms);
        let since = self.decided_ms(&brain).max(own_mark);
        // The times this plan's own say nodes spoke (their marks; a line is written at the
        // moment its node is marked).
        let own: Vec<u64> = self.st.marks.iter().filter(|m| m.node < DESIRE_MARK).map(|m| m.at_ms).collect();
        let sc = common::scripts(self.ctx);
        let words: Vec<&str> = sc.ways().iter().map(|w| w.kind.as_str()).collect();
        // The install's own line (said in its transaction, at `installed_ms`) is the plan's first
        // words, not a reply that overtook them.
        self.ctx.db.experience().observer().filter(self.me.id).filter(|e| e.at_ms > since).any(|e| {
            (e.kind == "said" && e.object == to && !own.contains(&e.at_ms) && e.at_ms != brain.installed_ms)
                || (e.subject == to && words.contains(&e.kind.as_str()) && (e.object == self.me.id || e.object == 0 && e.salience >= 0.8))
        })
    }

    /// Under `heard_first_rethinks`: a line another said to `to` that I heard since this mind's
    /// plan's decision perceived its scene (`decided_ms`), or since say node `id` last spoke
    /// (first-sight-crowd).
    fn heard_first(&self, id: u16, to: u32) -> Option<Experience> {
        if !common::laws(self.ctx).heard_first_rethinks {
            return None;
        }
        let brain = self.ctx.db.brain().id().find(self.me.id).filter(|b| b.source == "mind")?;
        let own_mark = self.st.marks.iter().find(|m| m.node == id).map_or(0, |m| m.at_ms);
        crate::speech::addressed_by_another(self.ctx, self.me.id, to, self.decided_ms(&brain).max(own_mark))
    }

    /// A say that cannot be spoken is a failure the body is told about, like a refused leaf
    /// (once per repeat window for the same line and reason), not a silent skip.
    fn say_failed(&mut self, id: u16, n: &Node, why: &str) -> St {
        let desc = graph::describe(n);
        if act::refused(self.ctx, self.me.id, id, self.st.revision, "say", &desc, why, self.now) {
            self.st.fails = self.st.fails.saturating_add(1);
        }
        self.last_fail = format!("say: {why}");
        St::Fail
    }

    fn leaf_fail(&mut self, id: u16, why: &str) -> St {
        let _ = id;
        self.last_fail = why.to_string();
        St::Fail
    }

    /// The outcome of leaf `id`'s activity that has ended since it was last visited (read once),
    /// unless that activity is still under way.
    fn finished(&mut self, id: u16) -> Option<St> {
        let rev = self.st.revision;
        let l = self.st.last.clone().filter(|l| l.node == id && l.revision == rev)?;
        if self.ctx.db.activity().id().find(self.me.id).is_some_and(|a| a.node == id && a.revision == rev) {
            return None;
        }
        self.st.last = None;
        if l.ok {
            return Some(St::Ok);
        }
        self.last_fail = l.why.clone();
        Some(St::Fail)
    }

    #[allow(clippy::too_many_arguments)]
    fn leaf(&mut self, id: u16, skill: &str, target: Resolved, item: &str, qty: u32, text: &str, topic: &str, desc: String) -> St {
        // A committed move under way holds the body until it has run its course (a dash may cut
        // in on a windup): the graph waits on it, as a player's keys do (`combat::held_by`).
        if let Some(a) = self.ctx.db.activity().id().find(self.me.id) {
            let own = a.node == id && a.revision == self.st.revision;
            if !own && crate::combat::held_by(&common::scripts(self.ctx), &a, skill).is_err() {
                self.status = a.label;
                return St::Run;
            }
        }
        if self.acting {
            // A deliberate act holds the body: the graph's work waits for it, but a reflex
            // (flee, dodge, block, attack, throw) takes the body back at once.
            match self.ctx.db.activity().id().find(self.me.id).filter(|a| act::held(a.node)) {
                Some(a) if common::scripts(self.ctx).shapes().reflex(skill) => {
                    crate::acts::interrupt(self.ctx, a, skill, self.now);
                    self.acting = false;
                }
                Some(_) => return St::Run,
                None => self.acting = false,
            }
        }
        let rev = self.st.revision;
        if let Some(a) = self.ctx.db.activity().id().find(self.me.id) {
            if a.node == id && a.revision == rev {
                self.running = Some(id);
                self.status = a.label;
                return St::Run;
            }
        }
        if let Some(done) = self.finished(id) {
            return done;
        }
        let want = std::mem::take(&mut self.want);
        let answers = std::mem::take(&mut self.answers);
        let run = self.run.take();
        let spacing = std::mem::take(&mut self.spacing);
        let _span = common::detail_span("brain.begin");
        match act::begin(self.ctx, self.me.id, id, rev, skill, target, item, qty, text, topic, (&want.0, want.1), answers, run, spacing, self.now) {
            Ok(()) => {
                common::diag(|| format!("begin:ok:{skill}"), 1);
                self.running = Some(id);
                self.status = self.ctx.db.activity().id().find(self.me.id).map(|a| a.label).unwrap_or(desc);
                St::Run
            }
            Err(why) => {
                // While profiling: what refused it, the reason's words without its numbers.
                common::diag(|| format!("begin:refused:{skill}:{}", why.chars().filter(|c| !c.is_ascii_digit() && *c != '.').take(48).collect::<String>()), 1);
                // Refused at the start: a failure like any other, not an unseen retry.
                let _refused = common::detail_span("begin.refused");
                if act::refused(self.ctx, self.me.id, id, rev, skill, &desc, &why, self.now) {
                    self.st.fails = self.st.fails.saturating_add(1);
                }
                self.last_fail = format!("{skill}: {why}");
                St::Fail
            }
        }
    }

    // ---- targets ---------------------------------------------------------------

    fn relation(&self, other: u32) -> Option<Relation> {
        self.ctx.db.relation().by_pair().filter((self.me.id, other)).next()
    }

    fn relation_ok(&self, other: u32, want: &str) -> bool {
        relation_ok(self.ctx, self.me.id, other, want)
    }

    fn visible_creature(&mut self, id: u32) -> Option<Resolved> {
        let c = self.scene().creatures.iter().find(|c| c.id == id)?.clone();
        let ch = self.ctx.db.character().id().find(id)?;
        Some(Resolved { class: 3, id: id as u64, at: c.pos, kind: c.kind.to_string(), name: ch.name })
    }

    /// A structure or resource in sight by its id.
    fn visible_thing(&mut self, id: u64) -> Option<Resolved> {
        if let Some((s, _)) = self.structures().iter().find(|(s, _)| s.id == id) {
            return Some(Resolved { class: 2, id: s.id, at: (s.x, s.y), kind: s.kind.clone(), name: String::new() });
        }
        self.scene().resources.iter().find(|(n, _)| n.id == id).map(|(n, _)| Resolved { class: 1, id: n.id, at: (n.x, n.y), kind: n.kind.clone(), name: String::new() })
    }

    fn smelled_creature(&mut self, id: u32) -> Option<Resolved> {
        let c = self.smelled().iter().find(|c| c.id == id)?.clone();
        let ch = self.ctx.db.character().id().find(id)?;
        Some(Resolved { class: 3, id: id as u64, at: c.pos, kind: c.kind.to_string(), name: ch.name })
    }

    /// Resolve a target the body acts on (a skill's, an act's, `can`, `smells`): what it sees,
    /// and failing that a creature it smells. Other conditions (`sees`, `near`, `count`,
    /// `health_of`) and speech stay with sight.
    fn sensed(&mut self, t: &Target) -> Option<Resolved> {
        self.smell = true;
        let r = self.resolve(t);
        self.smell = false;
        r
    }

    fn resolve(&mut self, t: &Target) -> Option<Resolved> {
        let now = self.now;
        match t {
            // Oneself is a creature like any other (one can tend one's own wounds).
            Target::Me => Some(Resolved { class: 3, id: self.me.id as u64, at: self.at, kind: self.me.kind.to_string(), name: self.me.name.clone() }),
            Target::Attacker => {
                if self.vit.hurt_by != 0 && now.saturating_sub(self.vit.hurt_ms) < 60_000 {
                    self.visible_creature(self.vit.hurt_by)
                } else {
                    None
                }
            }
            Target::Speaker => {
                if self.st.speaker != 0 && now.saturating_sub(self.st.heard_ms) < 60_000 {
                    let sp = self.st.speaker;
                    // Unseen but heard (sight has a field): for a target the body acts on (turning
                    // to it), toward where the voice is.
                    self.visible_creature(sp).or_else(|| {
                        if !self.smell {
                            return None;
                        }
                        self.scene().heard.iter().find(|c| c.id == sp).map(|c| Resolved::point(c.pos))
                    })
                } else {
                    None
                }
            }
            Target::Suitor => {
                let window = (common::laws(self.ctx).bond_window_s * 1000.0) as u64;
                let offer = self.ctx.db.bond_offer().to().filter(self.me.id).filter(|o| now.saturating_sub(o.at_ms) <= window).max_by_key(|o| o.at_ms)?;
                self.visible_creature(offer.from)
            }
            Target::Partner => {
                let me = self.me.id;
                let db = &self.ctx.db;
                let youngest = db.character().parent_a().filter(me).chain(db.character().parent_b().filter(me)).max_by_key(|c| c.born_ms)?;
                let other = if youngest.parent_a == me { youngest.parent_b } else { youngest.parent_a };
                if other == 0 {
                    return None;
                }
                self.visible_creature(other)
            }
            Target::Parent => {
                let (a, b) = (self.me.parent_a, self.me.parent_b);
                let pa = if a != 0 { self.visible_creature(a) } else { None };
                let pb = if b != 0 { self.visible_creature(b) } else { None };
                match (pa, pb) {
                    (Some(x), Some(y)) => Some(if dist(self.at, x.at) <= dist(self.at, y.at) { x } else { y }),
                    (x, y) => x.or(y),
                }
            }
            Target::Hailer => {
                if self.hailed(60_000) {
                    self.visible_creature(self.st.hailer)
                } else {
                    None
                }
            }
            // Toward the nearest thing heard and not seen (a point: the body does not know who).
            Target::Sound => self.scene().heard.first().map(|c| Resolved::point(c.pos)),
            Target::Commotion => {
                let sight = common::sight_for(self.ctx, self.me.id, &self.w, now);
                crate::town::commotion(self.ctx, self.at, sight, now).map(Resolved::point)
            }
            Target::Home => {
                if let Some(p) = self.place("home") {
                    return Some(p);
                }
                Some(Resolved::point((self.me.home_x, self.me.home_y)))
            }
            Target::Wander => Some(Resolved::point(self.at)),
            Target::Place(name) => self.place(name),
            Target::At([x, y]) => Some(Resolved::point((*x, *y))),
            // An id is whatever the scene listed under it: a creature first, else a structure or
            // a resource in sight (a depleted bush still resolves, so its own rule says it is bare
            // instead of the body being told it is not there).
            Target::Id(id) => {
                // A mind names a figure it cannot make out by its sighting's handle (far-handle).
                let id = &crate::far::resolve(self.ctx, self.me.id, *id);
                self.visible_creature(*id).or_else(|| if self.smell { self.smelled_creature(*id) } else { None }).or_else(|| self.visible_thing(*id as u64))
            }
            Target::Named(name) => {
                let ids: Vec<u32> = self.scene().creatures.iter().filter(|c| &*c.kind == "person").map(|c| c.id).collect();
                // Only someone whose name this character perceives now: a figure too far away to
                // make out is not found by a name (it would tell who they are; far-handle).
                let (ctx, me, now) = (self.ctx, &self.me, self.now);
                let id = ids.into_iter().find(|id| ctx.db.character().id().find(*id).is_some_and(|c| c.name.eq_ignore_ascii_case(name) && crate::perception::regard(ctx, me, &c, now).name))?;
                self.visible_creature(id)
            }
            Target::Nearest(f) => self.nearest(f),
        }
    }

    fn place(&self, name: &str) -> Option<Resolved> {
        self.ctx
            .db
            .place()
            .actor()
            .filter(self.me.id)
            .find(|p| p.name.eq_ignore_ascii_case(name))
            .map(|p| Resolved { class: 4, id: p.id, at: (p.x, p.y), kind: "place".into(), name: p.name })
    }

    fn nearest(&mut self, f: &Filter) -> Option<Resolved> {
        match living_rules::catalog::kind_class(&f.kind)? {
            living_rules::catalog::KindClass::Creature => {
                // Seen first; a creature smelled farther away only for a target the body acts on.
                let seen: Vec<(u32, Rc<str>, f32)> = self.scene().creatures.iter().map(|c| (c.id, c.kind.clone(), c.dist)).collect();
                let scent = if self.smell { common::scent_of(&self.me.kind) } else { None };
                let (ctx, me) = (self.ctx, self.me.id);
                let ok = |id: u32| f.relation.as_deref().map_or(true, |rel| relation_ok(ctx, me, id, rel)) && ctx.db.character().id().find(id).is_some();
                let smelled = || self.smelled().iter().map(|c| (c.id, c.kind.clone(), c.dist)).collect();
                match living_rules::species::pick_nearest(&f.kind, &seen, scent.as_ref(), smelled, ok)? {
                    (id, false) => self.visible_creature(id),
                    (id, true) => self.smelled_creature(id),
                }
            }
            living_rules::catalog::KindClass::Resource => {
                let now = self.now;
                let ctx = self.ctx;
                self.scene()
                    .resources
                    .iter()
                    .find(|(n, _)| n.kind == f.kind && common::amount_now(ctx, n, now) >= 1.0)
                    .map(|(n, _)| Resolved { class: 1, id: n.id, at: (n.x, n.y), kind: n.kind.clone(), name: String::new() })
            }
            living_rules::catalog::KindClass::Terrain => {
                // The nearest tile of that ground within sight.
                let map = common::map(self.ctx);
                let sight = common::sight_for(self.ctx, self.me.id, &self.w, self.now);
                let r = sight as i32;
                let (cx, cy) = (self.at.0.floor() as i32, self.at.1.floor() as i32);
                let mut best: Option<((f32, f32), f32)> = None;
                // Grazed-bare ground doesn't count as grass to go to.
                let mut bare: std::collections::HashMap<u32, bool> = std::collections::HashMap::new();
                for dy in -r..=r {
                    for dx in -r..=r {
                        if map.get(cx + dx, cy + dy).name() != f.kind {
                            continue;
                        }
                        let chunk = living_rules::map::chunk_of((cx + dx) as f32, (cy + dy) as f32);
                        let (ctx, now) = (self.ctx, self.now);
                        if *bare.entry(chunk).or_insert_with(|| common::pasture_now(ctx, chunk, now) < 1.0) {
                            continue;
                        }
                        let p = ((cx + dx) as f32 + 0.5, (cy + dy) as f32 + 0.5);
                        let d = dist(self.at, p);
                        if d <= sight && best.map_or(true, |(_, bd)| d < bd) {
                            best = Some((p, d));
                        }
                    }
                }
                best.map(|(p, _)| Resolved { class: 4, id: 0, at: p, kind: f.kind.clone(), name: String::new() })
            }
            living_rules::catalog::KindClass::Structure => {
                let (me, ctx) = (self.me.id, self.ctx);
                let holds = |id: u64| f.holds.as_deref().map_or(true, |item| common::inv_count(ctx, STRUCTURE_BIT | id, item) >= 1);
                // A kind `like` the one asked for counts as it (a world's `store` is a storage).
                let sc = common::scripts(ctx);
                self.structures()
                    .iter()
                    .find(|(s, _)| sc.is_kind(&s.kind, &f.kind) && (!f.mine || s.owner == me) && holds(s.id))
                    .map(|(s, _)| Resolved { class: 2, id: s.id, at: (s.x, s.y), kind: s.kind.clone(), name: String::new() })
            }
        }
    }

    // ---- conditions ------------------------------------------------------------

    fn cond(&mut self, c: &Cond) -> bool {
        match c {
            Cond::Hunger(x) => x.test(self.needs.hunger),
            Cond::Energy(x) => x.test(self.needs.energy),
            Cond::Health(x) => x.test(self.needs.hp),
            Cond::Stamina(x) => x.test(crate::breath::levels(&self.vit, self.now).0),
            Cond::Has(h) => {
                let n = if h.item == "food" { common::food_count(self.ctx, self.me.id as u64) } else { common::inv_count(self.ctx, self.me.id as u64, &h.item) };
                n >= h.at_least
            }
            Cond::Sees(t) => match t {
                Target::Place(_) | Target::At(_) | Target::Home => {
                    let r = common::sight_for(self.ctx, self.me.id, &self.w, self.now);
                    self.resolve(t).map_or(false, |p| dist(self.at, p.at) <= r)
                }
                _ => self.resolve(t).is_some(),
            },
            Cond::Near(n) => self.resolve(&n.target).map_or(false, |p| dist(self.at, p.at) <= n.within),
            // A creature within the body's scent (seen or not); never true without a scent.
            Cond::Smells(t) => {
                let Some(scent) = common::scent_of(&self.me.kind) else { return false };
                let (at, me) = (self.at, self.me.id as u64);
                self.sensed(t).is_some_and(|r| r.class == 3 && r.id != me && scent.reaches(&r.kind, dist(at, r.at)))
            }
            Cond::Count(c) => {
                let at = self.at;
                self.scene();
                let scene = self.scene.as_ref().expect("scene built");
                let mut n = 0u32;
                for x in &scene.creatures {
                    if c.within.is_some_and(|w| dist(at, x.pos) > w) || (c.of.kind != "creature" && *x.kind != *c.of.kind) {
                        continue;
                    }
                    if let Some(rel) = &c.of.relation {
                        if !self.relation_ok(x.id, rel) {
                            continue;
                        }
                    }
                    n += 1;
                }
                c.at_least.map_or(true, |a| n >= a) && c.at_most.map_or(true, |b| n <= b)
            }
            // What someone in sight is visibly doing (docs/PERCEPTION.md, "What someone is visibly
            // doing"): over the scene this evaluation already gathered (sight, field, sight line),
            // two point lookups per creature that fits `who` and `within`; nothing else is read.
            Cond::Doing(d) => {
                let _span = common::span("brain.doing");
                let (me, at, now) = (self.me.id, self.at, self.now);
                let sc = common::scripts(self.ctx);
                let want = d.phase.as_deref().and_then(living_rules::doing::Phase::parse);
                self.scene();
                let scene = self.scene.as_ref().expect("scene built");
                for x in &scene.creatures {
                    if d.within.is_some_and(|w| dist(at, x.pos) > w) {
                        continue;
                    }
                    if let Some(f) = &d.who {
                        if (f.kind != "creature" && *x.kind != *f.kind) || f.relation.as_deref().is_some_and(|rel| !self.relation_ok(x.id, rel)) {
                            continue;
                        }
                    }
                    let Some(v) = crate::perception::visibly(self.ctx, &sc, x.id, now) else { continue };
                    if want.is_some_and(|p| !v.phase.fits(p)) || d.is.as_deref().is_some_and(|i| !v.is(&sc, i)) || d.at_me.is_some_and(|m| v.at(me, at, x.pos) != m) {
                        continue;
                    }
                    return true;
                }
                false
            }
            Cond::HealthOf(h) => {
                let Some(r) = self.resolve(&h.target).filter(|r| r.class == 3) else { return false };
                // As this character perceives it (its own exactly, another's band unless
                // appraised), never the target's `vitals`; nothing when the law hides it.
                let Some(t) = self.ctx.db.character().id().find(r.id as u32) else { return false };
                let Some(seen) = crate::perception::health_seen(self.ctx, &self.me, &t, self.now) else { return false };
                let pct = seen.percent();
                h.above.map_or(true, |a| pct > a) && h.below.map_or(true, |b| pct < b)
            }
            Cond::HurtWithin(s) => self.vit.hurt_ms != 0 && self.now.saturating_sub(self.vit.hurt_ms) as f32 <= s * 1000.0,
            Cond::HeardWithin(s) => self.st.heard_ms != 0 && self.now.saturating_sub(self.st.heard_ms) as f32 <= s * 1000.0,
            Cond::Night(b) => common::night(self.ctx, &self.w, self.now) == *b,
            Cond::Bedtime(b) => common::day_phase(self.ctx, self.me.id, common::hour(&self.w, self.now)).bedtime == *b,
            Cond::Evening(b) => common::day_phase(self.ctx, self.me.id, common::hour(&self.w, self.now)).evening == *b,
            Cond::WorkHours(b) => common::day_phase(self.ctx, self.me.id, common::hour(&self.w, self.now)).work == *b,
            Cond::Raining(b) => crate::town::raining(self.ctx) == *b,
            Cond::Hailed(s) => self.hailed((s * 1000.0) as u64),
            Cond::Moving(b) => {
                let moving = self.ctx.db.body().id().find(self.me.id).is_some_and(|body| crate::town::motion_of(&body, self.now).1 != (0.0, 0.0));
                moving == *b
            }
            Cond::Hour(x) => x.test(common::hour(&self.w, self.now)),
            Cond::Threatened(b) => {
                let me = self.me.id;
                let now = self.now;
                // Only a hostile move (its `<skill>_combat()` says so) names a victim.
                let coming: Vec<u32> = self.ctx.db.activity().victim().filter(me).filter(|a| a.phase == 1 && a.ends_ms > now).map(|a| a.id).collect();
                // While sight depends on facing (the `fov_on` law), a windup is a threat only when
                // its maker is seen: one from behind is not seen coming (docs/COMBAT.md). Without a
                // field, as before: any windup aimed at me.
                let seen = coming.is_empty() || common::senses_of(self.ctx, me, &self.w, now).field.is_none() || {
                    let sc = self.scene();
                    coming.iter().any(|id| sc.creatures.iter().any(|c| c.id == *id))
                };
                (!coming.is_empty() && seen) == *b
            }
            Cond::Believes(b) => self
                .ctx
                .db
                .judgment()
                .actor()
                .filter(self.me.id)
                .find(|j| j.key.eq_ignore_ascii_case(&b.key))
                .map_or(false, |j| j.value > b.above),
            Cond::Judged(j) => {
                let now = self.now;
                let row = self.ctx.db.judged().actor().filter(self.me.id).find(|x| x.q.eq_ignore_ascii_case(&j.q) && x.expires_ms > now);
                j.test(row.as_ref().map(|r| (r.value, r.choice.as_str())))
            }
            Cond::Can(a) => {
                let target = match &a.target {
                    Some(t) => match self.sensed(t) {
                        Some(r) => r,
                        None => return false,
                    },
                    None => act::Resolved::none(),
                };
                act::can(self.ctx, self.me.id, &a.skill, target, a.item.as_deref().unwrap_or(""), a.qty.unwrap_or(0), self.now)
            }
            Cond::Chance(p) => self.ctx.rng().gen_range(0.0f32..1.0) < *p,
            Cond::All(v) => v.iter().all(|x| self.cond(x)),
            Cond::Any(v) => v.iter().any(|x| self.cond(x)),
            Cond::Not(x) => !self.cond(x),
        }
    }

    // ---- bookkeeping -----------------------------------------------------------

    /// Bodily alerts become percepts once per episode.
    fn alerts(&mut self) {
        if !self.me.ai {
            return;
        }
        let night = common::night(self.ctx, &self.w, self.now);
        // The body's alarms are the `status_of` law's (one set of thresholds with the players'
        // screens and the minds' body words).
        let sc = common::scripts(self.ctx);
        let span = common::span("brain.status");
        let statuses = alarm_statuses(self.ctx, &sc, &self.me, &self.vit, night, self.now);
        let checks: Vec<living_rules::script::Alarm> = statuses.iter().filter_map(|s| s.alarm.clone()).collect();
        drop(span);
        // Psychological drives: an uneventful stretch makes curious people restless; time without
        // company makes sociable people lonely. They are felt, not prescribed: the mind decides.
        let traits = common::traits_of(self.ctx, self.me.id);
        let trait_of = |k: &str| match k {
            "curiosity" => traits[0],
            "sociability" => traits[1],
            _ => traits[2],
        };
        let calm = self.needs.hunger < 60.0 && self.needs.energy > 35.0 && self.needs.hp > 60.0;
        let quiet_ms = self.now.saturating_sub(self.st.deliberated_ms);
        let restless_after = 60_000.0 * (12.0 - trait_of("curiosity") / 12.0);
        let lonely_after = 60_000.0 * (14.0 - trait_of("sociability") / 10.0);
        let alone_ms = self.now.saturating_sub(self.st.heard_ms.max(self.st.spoke_ms));
        // Grown people long for a child of their own, sooner the more nurturing they were born
        // (the laws `longing_after_min` and `longing_food`: how long after one's own birth or
        // one's youngest child's, and how much food one must carry for it to be felt).
        let broody = self.me.kind == "person" && self.me.stage == 2 && calm && !common::night(self.ctx, &self.w, self.now) && {
            let me = self.me.id;
            let db = &self.ctx.db;
            let laws = common::laws(self.ctx);
            let expecting = db.expecting().iter().any(|e| e.a == me || e.b == me);
            let rearing = db.rearing().id().find(me).map_or(false, |r| r.until_ms > self.now);
            let last = db.character().parent_a().filter(me).chain(db.character().parent_b().filter(me)).map(|c| c.born_ms).max().unwrap_or(self.me.born_ms);
            let wait = living_rules::script::longing_wait_ms(laws.longing_after_min, trait_of("nurture"));
            let provided = laws.longing_food <= 0.0 || common::food_count(self.ctx, me as u64) as f32 >= laws.longing_food;
            !expecting && !rearing && self.now.saturating_sub(last) as f32 > wait && provided
        };
        // Who one would have a child with, when there is someone: the other parent of one's youngest.
        let longing = if broody {
            let me = self.me.id;
            let db = &self.ctx.db;
            let partner = db.character().parent_a().filter(me).chain(db.character().parent_b().filter(me)).max_by_key(|c| c.born_ms).map(|c| if c.parent_a == me { c.parent_b } else { c.parent_a }).filter(|p| *p != 0 && db.character().id().find(*p).map_or(false, |c| c.alive));
            // Without a child yet, whoever one calls one's partner.
            let named = partner.map(|p| (p, true)).or_else(|| {
                db.relation().actor().filter(me).find(|r| r.label.to_lowercase().contains("partner") && db.character().id().find(r.other).map_or(false, |c| c.alive)).map(|r| (r.other, false))
            });
            match named {
                Some((p, true)) => format!("You long for another child with {} (#{p}).", common::name_of(self.ctx, p)),
                Some((p, false)) => format!("You long for a child with {} (#{p}).", common::name_of(self.ctx, p)),
                None => "You long for a child of your own.".to_string(),
            }
        } else {
            String::new()
        };
        // Knowing something no one else alive knows weighs on a grown person now and then
        // (checked about once a minute): it dies with them unless they pass it on.
        let mut sole = String::new();
        let (checked, felt) = LEGACY.with(|l| l.borrow().get(&self.me.id).copied().unwrap_or((0, 0)));
        if self.me.kind == "person" && self.me.stage >= 2 && calm && self.now.saturating_sub(checked) >= 60_000 {
            LEGACY.with(|l| l.borrow_mut().insert(self.me.id, (self.now, felt)));
            let me = self.me.id;
            let db = &self.ctx.db;
            let mine: Vec<String> = db.know_how().actor().filter(me).map(|k| k.technique).collect();
            let alone: Vec<String> = mine
                .into_iter()
                .filter(|t| !db.know_how().iter().any(|k| k.actor != me && &k.technique == t && db.character().id().find(k.actor).map_or(false, |c| c.alive)))
                .collect();
            if !alone.is_empty() {
                sole = format!("You alone know how to {}: when you are gone, it goes with you.", alone.join(" and "));
            }
        }
        // Felt again at most every 15 minutes while it stays true.
        if !sole.is_empty() && self.now.saturating_sub(felt) >= 15 * 60_000 {
            let now = self.now;
            LEGACY.with(|l| l.borrow_mut().insert(self.me.id, (now, now)));
            percept(self.ctx, &self.me, self.now, "feeling", self.me.id, 0, self.at, sole.clone(), 0.5);
            self.deliberate(&format!("You feel something: {sole}"));
        }
        // A person's new day begins at its own rising (its rhythm), once a day: its mind is
        // asked to think about the day ahead, each at their own hour.
        if self.me.kind == "person" && self.me.stage >= 1 {
            if let Some(mut r) = self.ctx.db.rhythm().id().find(self.me.id) {
                let hour = common::hour(&self.w, self.now);
                let since = (hour - r.rise_h).rem_euclid(24.0);
                let day = living_rules::day_of(self.now, self.w.epoch_ms, self.w.day_ms) as u32;
                if since < 3.0 && r.last_day < day && !common::day_phase(self.ctx, self.me.id, hour).bedtime {
                    r.last_day = day;
                    self.ctx.db.rhythm().id().update(r);
                    let season = common::season(self.ctx, self.now);
                    let text = format!("A new day begins for you: day {day} ({season}).");
                    percept(self.ctx, &self.me, self.now, "feeling", self.me.id, 0, self.at, text.clone(), 0.3);
                    self.deliberate(&text);
                }
            }
        }
        let drives: [(u32, bool, String); 3] = [
            (16, calm && quiet_ms as f32 > restless_after, "You feel restless: your days have been the same for a while.".into()),
            (32, calm && self.st.heard_ms > 0 && alone_ms as f32 > lonely_after, "You feel lonely: it has been a long time since you spoke with anyone.".into()),
            (128, broody, longing),
        ];
        for (bit, on, text) in drives {
            let was = self.st.alerts & bit != 0;
            if on && !was {
                self.st.alerts |= bit;
                percept(self.ctx, &self.me, self.now, "feeling", self.me.id, 0, self.at, text.clone(), 0.5);
                self.deliberate(&format!("You feel something: {text}"));
            } else if !on && was {
                self.st.alerts &= !bit;
            }
        }
        self.st.alerts &= !OLD_BODY_ALARMS;
        let mut felt_now = 0u32;
        for al in checks {
            let bit = alarm_bit(&al.text);
            felt_now |= bit;
            let text = al.text.as_str();
            if self.st.alerts & bit == 0 {
                self.st.alerts |= bit;
                percept(self.ctx, &self.me, self.now, "body", self.me.id, 0, self.at, text.into(), al.salience);
                let urgent = match al.think {
                    living_rules::script::Think::Always => true,
                    living_rules::script::Think::NoFood => common::food_count(self.ctx, self.me.id as u64) == 0,
                    living_rules::script::Think::Never => false,
                };
                if urgent {
                    let mut why = format!("Your body: {text}");
                    // Show what the want's routine actually runs (starving: one's food desire), so
                    // a way of eating that cannot feed (e.g. one that only waits) can be seen and
                    // changed.
                    if !al.routine.is_empty() {
                        let want = al.routine.as_str();
                        // The routine the desire for it calls (food: seeded as "find food and eat").
                        let food_routine = self.ctx.db.brain().id().find(self.me.id).and_then(|b| living_rules::graph::parse(&b.graph).ok()).and_then(|g| match g.root {
                            Node::Desires(ds) => ds.iter().find(|d| d.want.eq_ignore_ascii_case(want)).and_then(|d| match &*d.body {
                                Node::Routine(r) => Some(r.clone()),
                                _ => None,
                            }),
                            _ => None,
                        });
                        let name = food_routine.unwrap_or_else(|| if want.eq_ignore_ascii_case("food") { "eat".to_string() } else { want.to_string() });
                        if let Some(r) = self.ctx.db.routine().actor().filter(self.me.id).find(|r| crate::common::same_routine(&r.name, &name)) {
                            if let Ok(g) = living_rules::graph::parse(&r.graph) {
                                let how: String = living_rules::graph::outline(&g.root).lines().map(|l| l.trim()).collect::<Vec<_>>().join("; ");
                                why.push_str(&format!(" Your hunger runs your routine \"{}\", which does: {}. It has not fed you.", r.name, how.chars().take(300).collect::<String>()));
                            }
                        }
                    }
                    // A bodily alarm wakes a sleeper, whoever plays it (a mind thinks on it).
                    perceive::request_waking(self.ctx, self.me.id, &why, self.now, perceive::Wake::Body);
                    if self.ctx.db.activity().id().find(self.me.id).is_none() {
                        self.latched = None;
                    }
                }
            }
        }
        // An alarm no longer felt ends its episode: felt again, it is told again.
        self.st.alerts = (self.st.alerts & !LAW_ALARMS) | felt_now;
    }

    /// Attention cues (docs/ATTENTION.md): what this character's mind wrote should bring it to
    /// think, matched by type against what it perceives now (the scene this evaluation built),
    /// at most once per `cue_check_s` (a second by default), while the `cues_on` law holds. A thing that begins to match a cue
    /// becomes one `noticed` experience quoting the mind's own reason, and a request to think;
    /// once per thing per `cue_cooldown_s`, and once per character per `cue_gap_s` (things that
    /// begin to match together are told in one line). A person too far away to make out matches
    /// nothing, as they are no one in particular to the scene.
    fn cues(&mut self) {
        let laws = common::laws(self.ctx);
        if !laws.cues_on {
            return;
        }
        let (me, now) = (self.me.id, self.now);
        let every = (laws.cue_check_s * 1000.0) as u64;
        let due = CUE_HELD.with(|m| m.borrow().get(&me).map_or(true, |(t, _)| now.saturating_sub(*t) >= every));
        if !due {
            return;
        }
        // The scene `noticed` builds anyway, built first so the span times the cues' own work.
        self.scene();
        let _span = common::span("brain.cues");
        let cues: Vec<Cue> = self.ctx.db.cue().actor().filter(me).filter(|c| c.refused.is_empty()).collect();
        if cues.is_empty() {
            CUE_HELD.with(|m| m.borrow_mut().insert(me, (now, Vec::new())));
            return;
        }
        let ctx = self.ctx;
        let at = self.at;
        let places: Vec<Place> = if cues.iter().any(|c| !c.at.is_empty()) { ctx.db.place().actor().filter(me).collect() } else { Vec::new() };
        let place_of = |name: &str| places.iter().find(|p| p.name.eq_ignore_ascii_case(name)).map(|p| (p.id, (p.x, p.y)));
        let creatures: Vec<NearCreature> = self.scene().creatures.clone();
        let things: Vec<(u64, String, (f32, f32), f32)> = {
            let mut v: Vec<(u64, String, (f32, f32), f32)> = self.scene().resources.iter().map(|(r, d)| (CUE_RESOURCE | r.id, r.kind.clone(), (r.x, r.y), *d)).collect();
            v.extend(self.structures().iter().map(|(s, d)| (CUE_STRUCTURE | s.id, s.kind.clone(), (s.x, s.y), *d)));
            v
        };
        let scripts = common::scripts(ctx);
        // Who each person in sight is to me, worked out only once and only if a cue asks.
        let mut who_cache: Vec<(u32, bool, bool)> = Vec::new();
        let mut matched: Vec<(usize, u64, String)> = Vec::new();
        for (i, c) in cues.iter().enumerate() {
            let near_place = |p: (f32, f32)| -> bool {
                if c.at.is_empty() {
                    return true;
                }
                place_of(&c.at).is_some_and(|(_, q)| dist(p, q) <= c.within)
            };
            let near_me = |d: f32| c.near_me <= 0.0 || d <= c.near_me;
            if c.who_id != 0 || !c.who.is_empty() {
                for n in &creatures {
                    if n.id == me || (c.who_id != 0 && n.id != c.who_id) || !near_me(n.dist) || !near_place(n.pos) {
                        continue;
                    }
                    let kind_ok = match c.who.as_str() {
                        "" | "unknown" => true,
                        k => &*n.kind == k,
                    };
                    if !kind_ok || (c.who == "unknown" && &*n.kind != "person") {
                        continue;
                    }
                    if &*n.kind == "person" {
                        let (named, far) = match who_cache.iter().find(|w| w.0 == n.id) {
                            Some(w) => (w.1, w.2),
                            None => {
                                let Some(ch) = ctx.db.character().id().find(n.id) else { continue };
                                let w = (n.id, crate::perception::knows_name(ctx, &self.me, &ch), crate::perception::regard(ctx, &self.me, &ch, now).far);
                                who_cache.push(w);
                                (w.1, w.2)
                            }
                        };
                        if far || (c.who == "unknown" && named) {
                            continue;
                        }
                    }
                    // What it is visibly doing, and in which phase: what COMBAT_MIND 3.2's `doing`
                    // condition reads (`perception::visibly`), under the same sight.
                    let mut seen_doing = String::new();
                    if !c.doing.is_empty() || !c.phase.is_empty() {
                        let Some(v) = crate::perception::visibly(ctx, &scripts, n.id, now) else { continue };
                        let want = living_rules::doing::Phase::parse(&c.phase);
                        if (!c.doing.is_empty() && !v.is(&scripts, &c.doing)) || want.is_some_and(|p| !v.phase.fits(p)) {
                            continue;
                        }
                        seen_doing = format!(", {} ({})", v.skill.replace('_', " "), v.phase.word());
                    }
                    let who = common::label_for(ctx, &self.me, n.id);
                    let doing = seen_doing;
                    matched.push((i, n.id as u64, format!("{who}, {:.0} tiles {}{doing}", n.dist, direction(at, n.pos))));
                }
            } else if !c.thing.is_empty() {
                for (id, kind, pos, d) in &things {
                    if (kind == &c.thing || (*id & CUE_STRUCTURE != 0 && scripts.is_kind(kind, &c.thing))) && near_me(*d) && near_place(*pos) {
                        matched.push((i, *id, format!("{} {}, {:.0} tiles {}", article(kind), kind.replace('_', " "), d, direction(at, *pos))));
                    }
                }
            } else if let Some((pid, p)) = place_of(&c.at) {
                // Only a place: being there.
                if dist(at, p) <= c.within {
                    matched.push((i, CUE_PLACE | pid, format!("that you are at {}", c.at)));
                }
            }
        }
        let cooldown = (laws.cue_cooldown_s * 1000.0) as u64;
        let gap = (laws.cue_gap_s * 1000.0) as u64;
        let last_fire = cues.iter().flat_map(|c| c.fired.iter().map(|f| f.at_ms)).max().unwrap_or(0);
        let mut held = CUE_HELD.with(|m| m.borrow().get(&me).map(|(_, h)| h.clone()).unwrap_or_default());
        held.retain(|(cue, subj)| matched.iter().any(|(i, s, _)| cues[*i].id == *cue && s == subj));
        let mut fire: Vec<(usize, u64, String)> = Vec::new();
        for (i, subj, text) in matched {
            let c = &cues[i];
            if held.contains(&(c.id, subj)) || fire.iter().any(|f| f.0 == i && f.1 == subj) {
                continue;
            }
            if c.fired.iter().any(|f| f.subject == subj && now.saturating_sub(f.at_ms) < cooldown) {
                held.push((c.id, subj));
                continue;
            }
            fire.push((i, subj, text));
        }
        let gap_ok = last_fire == 0 || now.saturating_sub(last_fire) >= gap;
        if !fire.is_empty() && gap_ok {
            let mut lines: Vec<String> = Vec::new();
            let mut updates: Vec<Cue> = Vec::new();
            let mut newly: Vec<(u64, u64)> = Vec::new();
            for (i, c) in cues.iter().enumerate() {
                let parts: Vec<&str> = fire.iter().filter(|f| f.0 == i).map(|f| f.2.as_str()).collect();
                if parts.is_empty() {
                    continue;
                }
                let why = if c.why.trim().is_empty() { c.for_key.split_once(':').map_or(c.for_key.as_str(), |(_, k)| k).replace('_', " ") } else { c.why.trim().to_string() };
                lines.push(format!("You notice {}: you watch for this (\"{why}\").", parts.join("; ")));
                let mut row = c.clone();
                for f in fire.iter().filter(|f| f.0 == i) {
                    row.fired.retain(|x| x.subject != f.1);
                    row.fired.push(CueFire { subject: f.1, at_ms: now });
                    row.fires += 1;
                    newly.push((c.id, f.1));
                }
                if row.fired.len() > CUE_FIRED {
                    let cut = row.fired.len() - CUE_FIRED;
                    row.fired.drain(..cut);
                }
                updates.push(row);
            }
            let text = lines.join(" ");
            // A cue fires only when its request to think is taken: one asked too soon after the
            // last thought (the species' `think_min_s`) is tried again at the next check, so what
            // the mind watched for is not told without the thought it asked for.
            if crate::perceive::ask_to_think(ctx, me, &text, now) {
                for row in updates {
                    ctx.db.cue().id().update(row);
                }
                held.extend(newly);
                let creatures_fired: Vec<u32> = fire.iter().filter(|f| f.1 >> 32 == 0).map(|f| f.1 as u32).collect();
                let (subject, object) = (creatures_fired.first().copied().unwrap_or(0), creatures_fired.get(1).copied().unwrap_or(0));
                percept(ctx, &self.me, now, "noticed", subject, object, at, text, 0.65);
            }
        }
        CUE_HELD.with(|m| m.borrow_mut().insert(me, (now, held)));
    }

    /// Whether this node's act is under way and still approaching its target (phase 0).
    fn approaching(&self, id: u16) -> bool {
        self.ctx.db.activity().id().find(self.me.id).is_some_and(|x| x.node == id && x.revision == self.st.revision && x.phase == 0)
    }

    /// Over `FAMILIAR_LIMIT`, forget the oldest familiarity by age only (fix 1): never a row
    /// touched within `FAMILIAR_KEEP_MS`, nor one whose thing is in the seen set (in view lately:
    /// its row is touched only every 30 s, so its `last_ms` can trail while it stays in view).
    fn prune_familiar(&mut self) {
        let (me, now) = (self.me.id, self.now);
        let mut all: Vec<(u64, u64, u64)> = self.ctx.db.familiar().actor().filter(me).map(|f| (f.last_ms, f.id, f.thing)).collect();
        if all.len() <= FAMILIAR_LIMIT {
            return;
        }
        all.sort_unstable();
        let mut over = all.len() - FAMILIAR_LIMIT;
        for (last, id, thing) in all {
            if over == 0 {
                break;
            }
            if now.saturating_sub(last) < FAMILIAR_KEEP_MS || self.seen_key(thing).and_then(|k| self.seen_at(k)).is_some_and(|t| now.saturating_sub(t) < SEEN_MS) {
                continue;
            }
            common::diag(|| "familiar:evict", 1);
            self.ctx.db.familiar().id().delete(id);
            over -= 1;
        }
    }

    /// The seen-set key of a familiarity row's thing (as `noticed` looks things up), if any.
    fn seen_key(&self, thing: u64) -> Option<u32> {
        let id = (thing & ((1 << 40) - 1)) as u32;
        match thing & !((1 << 40) - 1) {
            FAM_CREATURE => Some(id),
            FAM_STRUCTURE => Some(0x4000_0000 | (id & 0x3fff_ffff)),
            FAM_REGION => Some(0x8000_0000 | id),
            _ => None,
        }
    }

    /// Look up (and refresh) bodily familiarity; returns the previous record, if any.
    fn familiarity(&mut self, thing: u64) -> Option<Familiar> {
        common::diag(|| "familiar:lookup", 1);
        let prev = self.ctx.db.familiar().by_actor_thing().filter((self.me.id, thing)).next();
        match prev.clone() {
            Some(mut f) => {
                if self.now.saturating_sub(f.last_ms) > 30_000 {
                    f.last_ms = self.now;
                    f.times += 1;
                    self.ctx.db.familiar().id().update(f);
                }
            }
            None => {
                common::diag(|| "familiar:insert", 1);
                self.ctx.db.familiar().insert(Familiar { id: 0, actor: self.me.id, thing, first_ms: self.now, last_ms: self.now, times: 1 });
                // Every 64 new rows of this character, its count is checked against the limit.
                let me = self.me.id;
                let check = FAMILIAR_NEW.with(|n| {
                    let mut n = n.borrow_mut();
                    let c = n.entry(me).or_insert(0);
                    *c += 1;
                    *c % 64 == 0
                });
                if check {
                    self.prune_familiar();
                }
            }
        }
        prev
    }

    /// Seen too far away to make out less than `FAR_RECHECK_MS` ago (its mark is dropped once due).
    fn far_wait(&mut self, id: u32) -> bool {
        let now = self.now;
        let Some(at) = self.seen_at(FAR_MARK | id) else { return false };
        if now.saturating_sub(at) < FAR_RECHECK_MS {
            return true;
        }
        self.seen_drop(FAR_MARK | id);
        false
    }

    /// When this character last looked at `key` (its seen set), if lately.
    fn seen_at(&self, key: u32) -> Option<u64> {
        let me = self.me.id;
        SEEN.with(|s| s.borrow().get(&me).and_then(|m| m.get(&key).copied()))
    }

    fn seen_set(&mut self, key: u32, at: u64) {
        let me = self.me.id;
        SEEN.with(|s| {
            s.borrow_mut().entry(me).or_default().insert(key, at);
        });
    }

    fn seen_drop(&mut self, key: u32) {
        let me = self.me.id;
        SEEN.with(|s| {
            if let Some(m) = s.borrow_mut().get_mut(&me) {
                m.remove(&key);
            }
        });
    }

    /// A figure not to be looked at again for `FAR_RECHECK_MS`: too far away to make out, or
    /// unplaced by a sleeper (its own mark, since a seen mark stays alive while it is in sight).
    fn far_mark(&mut self, id: u32) {
        self.seen_drop(id);
        let now = self.now;
        self.seen_set(FAR_MARK | id, now);
    }

    /// Recently checked (fast path that avoids familiarity lookups every second).
    fn recently_seen(&mut self, key: u32) -> bool {
        common::diag(|| "seen:check", 1);
        let now = self.now;
        if let Some(at) = self.seen_at(key) {
            if now.saturating_sub(at) < SEEN_MS {
                if now.saturating_sub(at) > SEEN_MS / 2 {
                    self.seen_set(key, now);
                }
                return true;
            }
            self.seen_set(key, now);
            return false;
        }
        common::diag(|| "seen:miss", 1);
        self.seen_set(key, now);
        false
    }

    /// Turn what is new to this character into experiences: unfamiliar regions, first
    /// encounters, long-absent faces, nearby danger and newly noticed structures. Routine
    /// re-perception only refreshes familiarity, so experience volume follows novelty.
    /// A first sight of someone one cannot place asks for one thought (`first_sight_thinks`,
    /// docs/FIRST_SIGHT.md). `fresh` holds this look's first sights of people it cannot place:
    /// their label is not their name, by the shared answer `perception::regard` gives every
    /// asker in the transaction (cue-cache), so never someone known by name, and far figures
    /// never get a first sight. The reason is their part of the first-sight
    /// line, word for word, through `ask_to_think` (the species' `think_min_s`, merged into a
    /// pending request). A refused request is owed: tried again at later looks for at most
    /// `FIRST_SIGHT_OWED_MS` while the person is in sight and still cannot be placed, and
    /// settled by any thought made since. First sights bring one to think at most once per
    /// `first_sight_gap_s`; within the gap they only merge into a request already pending. A
    /// sleeper is asked nothing.
    fn first_sight_asks(&mut self, fresh: Vec<(u32, String)>, cands: &[NearCreature], asleep: &mut Option<bool>) {
        let (ctx, me, now) = (self.ctx, self.me.id, self.now);
        let mut st = FIRST_SIGHT.with(|m| m.borrow().get(&me).cloned()).unwrap_or_default();
        if fresh.is_empty() && st.owed.is_empty() {
            return;
        }
        let before = st.clone();
        let gap = (common::laws(ctx).first_sight_gap_s * 1000.0) as u64;
        if *asleep.get_or_insert_with(|| crate::perceive::asleep(ctx, me)) {
            st.owed.clear();
        }
        if !st.owed.is_empty() {
            let thought_since = ctx.db.mind_state().id().find(me).is_some_and(|m| m.deliberated_ms > st.since_ms);
            if thought_since || now.saturating_sub(st.since_ms) >= FIRST_SIGHT_OWED_MS {
                st.owed.clear();
            } else {
                // Still in sight and still unplaced: the shared answer (`perception::regard`,
                // once per observer and target per transaction, cue-cache) that names people in
                // the look's labels: not named (unknown, or too far away to make out) and not far.
                st.owed.retain(|(id, _)| {
                    cands.iter().any(|c| c.id == *id)
                        && ctx.db.character().id().find(*id).is_some_and(|t| {
                            let r = crate::perception::regard(ctx, &self.me, &t, now);
                            !r.name && !r.far
                        })
                });
            }
        }
        let gap_ok = st.last_ms == 0 || now.saturating_sub(st.last_ms) >= gap;
        if !fresh.is_empty() && !asleep.unwrap_or(false) {
            if gap_ok {
                for f in fresh {
                    if !st.owed.iter().any(|o| o.0 == f.0) {
                        st.owed.push(f);
                    }
                }
            } else if ctx.db.deliberation().actor().find(me).is_some() {
                // Within the gap: only joins a thought already asked for.
                let parts: Vec<String> = fresh.into_iter().map(|f| f.1).collect();
                crate::perceive::ask_to_think(ctx, me, &first_sight_text(&parts), now);
            }
        }
        if st.owed.is_empty() {
            st.since_ms = 0;
        } else {
            if st.since_ms == 0 {
                st.since_ms = now;
            }
            if gap_ok {
                let parts: Vec<String> = st.owed.iter().map(|o| o.1.clone()).collect();
                if crate::perceive::ask_to_think(ctx, me, &first_sight_text(&parts), now) {
                    st.last_ms = now;
                    st.owed.clear();
                    st.since_ms = 0;
                }
            }
        }
        if st != before {
            FIRST_SIGHT.with(|m| {
                let mut m = m.borrow_mut();
                if st == FirstSightAsk::default() {
                    m.remove(&me);
                } else {
                    m.insert(me, st);
                }
            });
        }
    }

    fn noticed(&mut self) {
        if !self.me.ai {
            return;
        }
        let _span = common::span("brain.noticed");
        common::diag(|| "noticed", 1);
        // The seen set keeps what was looked at within its horizon (and far marks), no more.
        let (me, now) = (self.me.id, self.now);
        SEEN.with(|s| {
            if let Some(m) = s.borrow_mut().get_mut(&me) {
                m.retain(|_, at| now.saturating_sub(*at) < SEEN_MS + 30_000);
            }
        });
        let now = self.now;
        let at = self.at;
        let day = self.w.day_ms.max(1);

        // Regions.
        let chunk = living_rules::map::chunk_of(at.0, at.1);
        if !self.recently_seen(0x8000_0000 | chunk) && self.familiarity(FAM_REGION | chunk as u64).is_none() {
            let text = self.region_summary();
            percept(self.ctx, &self.me, now, "discovered", 0, 0, at, text, 0.5);
        }

        // Creatures.
        let me_kind = self.me.kind.clone();
        let cands: Vec<NearCreature> = self.scene().creatures.iter().filter(|c| &*c.kind != "deer" || me_kind != "person").cloned().collect();
        let people = cands.iter().filter(|c| &*c.kind == "person").count();
        let laws = common::laws(self.ctx);
        let crowded = people as f32 > laws.crowd;
        // Crowds and nearby danger are noticed when they begin, not re-announced while they last.
        if crowded && self.st.alerts & IN_CROWD == 0 {
            percept(self.ctx, &self.me, now, "saw", 0, 0, at, format!("You are among a crowd of about {people} people."), 0.3);
        }
        self.st.alerts = if crowded { self.st.alerts | IN_CROWD } else { self.st.alerts & !IN_CROWD };
        // Hysteresis: danger begins inside 8 tiles and ends beyond 12.
        let was_near = self.st.alerts & WOLF_NEAR != 0;
        let wolf_near = cands.iter().any(|c| &*c.kind == "wolf" && c.dist <= if was_near { laws.danger_far } else { laws.danger_near });
        let wolf_arrived = wolf_near && self.st.alerts & WOLF_NEAR == 0;
        self.st.alerts = if wolf_near { self.st.alerts | WOLF_NEAR } else { self.st.alerts & !WOLF_NEAR };
        // Everyone in sight is perceived (docs/STRANGERS.md): each person (or one of one's own
        // kind) seen for the first time is told, in a crowd too. First sights of one look go in
        // one line, at most FIRST_SIGHTS_PER_LINE of them (more wait for the next look, unmarked);
        // people whose names one does not know first, then the nearest. Other news (a wolf, someone
        // again after a long time, danger close) stays at two lines a look.
        let mut announced = 0;
        let mut firsts: Vec<(u32, (f32, f32), String, bool)> = Vec::new();
        // Whether this body sleeps, read only when a first sight needs it.
        let mut asleep: Option<bool> = None;
        for c in &cands {
            let kin = &*c.kind == "person" || *c.kind == *me_kind;
            if announced >= 2 || (kin && firsts.len() >= FIRST_SIGHTS_PER_LINE) {
                // Only a first sight that still fits this look's line goes on; the rest are left
                // for the next look, untouched (neither marked seen nor made familiar).
                let fits = kin && firsts.len() < FIRST_SIGHTS_PER_LINE;
                let recent = self.seen_at(c.id).is_some_and(|t| now.saturating_sub(t) < SEEN_MS);
                if !fits || recent || self.ctx.db.familiar().by_actor_thing().filter((self.me.id, FAM_CREATURE | c.id as u64)).next().is_some() {
                    continue;
                }
            }
            let danger = wolf_arrived && &*c.kind == "wolf" && c.dist <= laws.danger_near;
            // Seen too far away to make out within the last 5 s: not looked at again yet.
            if &*c.kind == "person" && self.far_wait(c.id) {
                continue;
            }
            if self.recently_seen(c.id) && !danger {
                continue;
            }
            let Some(ch) = self.ctx.db.character().id().find(c.id) else { continue };
            // A person too far away to make out (the `perceived_of` law's `far`) is not yet a
            // first sight, nor someone seen again: who they are cannot be told. They stay in the
            // scene as a figure; the look is retried in 5 s and told once they can be made out,
            // and no `familiar` row is written from afar (far-label, docs/STRANGERS.md).
            if ch.kind == "person" {
                let due = self.ctx.db.familiar().by_actor_thing().filter((self.me.id, FAM_CREATURE | c.id as u64)).next().map_or(true, |f| now.saturating_sub(f.last_ms) > day);
                if due && crate::perception::regard(self.ctx, &self.me, &ch, now).far {
                    // Not "seen": a far figure is looked at again in 5 s (its own mark, since
                    // `recently_seen` keeps a mark alive while someone stays in sight).
                    self.far_mark(c.id);
                    continue;
                }
            }
            let who = common::label_for(self.ctx, &self.me, c.id);
            // Under `first_sight_thinks` a sleeper does not see someone it cannot place for the
            // first time (a sleeping body is not watching, docs/FIRST_SIGHT.md): no line and no
            // `familiar` row; it is looked at again in 5 s, as a far figure is, and the first
            // look after waking is the first sight.
            if laws.first_sight_thinks
                && (ch.kind == "person" || ch.kind == self.me.kind)
                && who != ch.name
                && self.ctx.db.familiar().by_actor_thing().filter((self.me.id, FAM_CREATURE | c.id as u64)).next().is_none()
                && *asleep.get_or_insert_with(|| crate::perceive::asleep(self.ctx, self.me.id))
            {
                self.far_mark(c.id);
                continue;
            }
            let prev = self.familiarity(FAM_CREATURE | c.id as u64);
            let doing = crate::perception::doing_of(self.ctx, c.id, (self.me.id, &me_kind, at), &cands, now).map(|d| format!(", {d}")).unwrap_or_default();
            let place = format!("{:.0} tiles {}{doing}", c.dist, direction(at, c.pos));
            let (text, sal) = match prev {
                None if ch.kind == "person" || ch.kind == self.me.kind => {
                    let named = who == ch.name;
                    firsts.push((c.id, c.pos, format!("{who}, {place}"), named));
                    continue;
                }
                None => (format!("You see {who} {place}."), 0.65),
                Some(f) if now.saturating_sub(f.last_ms) > day => (format!("You see {who} again after a long time, {place}."), 0.25),
                Some(_) if danger => {
                    (format!("{} is close: {place}.", if who.starts_with("a ") { format!("A{}", &who[1..]) } else { who.clone() }), 0.6)
                }
                Some(_) => continue,
            };
            announced += 1;
            percept(self.ctx, &self.me, now, "saw", c.id, 0, c.pos, text, sal);
        }
        if !firsts.is_empty() {
            // Unnamed first (a stable sort keeps the nearest first within each).
            firsts.sort_by_key(|f| f.3);
            let (subject, object) = (firsts[0].0, firsts.get(1).map_or(0, |f| f.0));
            let pos = firsts[0].1;
            let unplaced: Vec<(u32, String)> = firsts.iter().filter(|f| !f.3).map(|f| (f.0, f.2.clone())).collect();
            let parts: Vec<String> = firsts.into_iter().map(|f| f.2).collect();
            percept(self.ctx, &self.me, now, "saw", subject, object, pos, first_sight_text(&parts), 0.45);
            if laws.first_sight_thinks {
                self.first_sight_asks(unplaced, &cands, &mut asleep);
            }
        } else if laws.first_sight_thinks {
            self.first_sight_asks(Vec::new(), &cands, &mut asleep);
        }

        // Sounds out of sight (only while sight depends on facing): someone or something heard
        // near is noticed when it begins, as a person would ("You hear a person near, behind
        // you, to the south-west."), never who it is. Its percept names no one and is placed
        // where the listener stands.
        let near = self.scene().heard.iter().find(|c| c.dist <= laws.heard_near_m).cloned();
        if let Some(c) = near.as_ref().filter(|_| self.st.alerts & SOUND_NEAR == 0) {
            let heading = self.ctx.db.body().id().find(self.me.id).map_or(0.0, |b| common::facing_at(&b, now));
            let (what, wh, far) = living_rules::sight::heard_words(&crate::perception::heard_kind(self.ctx, &c.kind), at, heading, c.pos, 0);
            percept(self.ctx, &self.me, now, "signal", 0, 0, at, format!("You hear {what} {far}, {wh}."), 0.3);
        }
        self.st.alerts = if near.is_some() { self.st.alerts | SOUND_NEAR } else { self.st.alerts & !SOUND_NEAR };

        // Structures. One made of several tiles (a town gate is a block of gate tiles) is noticed
        // once: new tiles touching others of the same kind and owner are one thing, and nothing
        // is said when any part of it was already familiar.
        // Remains and every other structure lie still: one looked at lately is in the seen set,
        // so a look costs one check of its id, and their details are copied only when something
        // in sight is new.
        let ids: Vec<u64> = self.structures().iter().map(|(s, _)| s.id).collect();
        let mut new: Vec<usize> = Vec::new();
        for (i, id) in ids.iter().enumerate() {
            if !self.recently_seen(0x4000_0000 | (*id as u32 & 0x3fff_ffff)) && self.familiarity(FAM_STRUCTURE | id).is_none() {
                new.push(i);
            }
        }
        if new.is_empty() {
            return;
        }
        let structures: Vec<(u64, String, u32, (f32, f32), f32)> = self.structures().iter().map(|(s, d)| (s.id, s.kind.clone(), s.owner, (s.x, s.y), *d)).collect();
        let mut told = vec![false; structures.len()];
        for &i in &new {
            if told[i] {
                continue;
            }
            let part = joined_tiles(&structures, i);
            for &k in &part {
                told[k] = true;
            }
            let (_, kind, owner, _, _) = &structures[i];
            if *owner == self.me.id || part.iter().any(|k| !new.contains(k)) {
                continue;
            }
            let nearest = *part.iter().min_by(|a, b| structures[**a].4.total_cmp(&structures[**b].4)).unwrap_or(&i);
            let (_, _, _, pos, dist) = structures[nearest];
            let whose = if *owner != 0 && kind != "remains" { common::owner_label(self.ctx, &self.me, *owner, kind) } else { None };
            let by = if let Some(w) = &whose { format!(" built by {w}") } else if kind == "remains" { format!(" — the remains of {}", common::label_for(self.ctx, &self.me, *owner)) } else { String::new() };
            // Its extent as it lies on the ground (a town gate is a block of gate tiles).
            let wide = if part.len() > 1 {
                let (xs, ys): (Vec<f32>, Vec<f32>) = part.iter().map(|k| structures[*k].3).unzip();
                let span = |v: &[f32]| (v.iter().cloned().fold(f32::MIN, f32::max) - v.iter().cloned().fold(f32::MAX, f32::min)).round() as i32 + 1;
                format!(" about {} by {} tiles", span(&xs), span(&ys))
            } else {
                String::new()
            };
            let text = format!("You notice a {kind}{wide}{by}, {dist:.0} tiles {}.", direction(at, pos));
            if kind == "remains" {
                // Remains are a death seen again, as what it left: their observer is a bystander
                // of it (woken at most once per `witness_wake_ms`, docs/BATTLE_SCALE.md), told at once.
                crate::perceive::percept_seen(self.ctx, &self.me, now, "saw", *owner, 0, pos, text, 0.8, false);
            } else {
                // Whose it is, only as the line names them (house-owner-label).
                crate::perceive::percept_owned(self.ctx, &self.me, now, "saw", if whose.is_some() { *owner } else { 0 }, 0, pos, text, 0.35);
            }
        }
    }

    /// One-line description of the surroundings when a region is first discovered.
    fn region_summary(&mut self) -> String {
        let at = self.at;
        let now = self.now;
        let mut kinds: Vec<(String, u32)> = Vec::new();
        let ctx = self.ctx;
        for (n, _) in &self.scene().resources {
            if common::amount_now(ctx, n, now) < 0.0 {
                continue;
            }
            match kinds.iter_mut().find(|k| k.0 == n.kind) {
                Some(k) => k.1 += 1,
                None => kinds.push((n.kind.clone(), 1)),
            }
        }
        kinds.sort_by(|a, b| b.1.cmp(&a.1));
        let res = kinds.iter().map(|(k, n)| format!("{n} {}", k.replace('_', " "))).collect::<Vec<_>>().join(", ");
        let ctx = self.ctx;
        let near: Vec<(u32, String)> = self.structures().iter().take(4).map(|(s, _)| (s.owner, s.kind.clone())).collect();
        let structures: Vec<String> = near
            .into_iter()
            .map(|(owner, kind)| match common::owner_label(ctx, &self.me, owner, &kind) {
                Some(_) if owner == self.me.id => format!("your {kind}"),
                Some(w) => format!("{w}'s {kind}"),
                None => kind,
            })
            .collect();
        let map = common::map(self.ctx);
        let mut terrain = Vec::new();
        for (t, word) in [(living_rules::map::Terrain::Water, "water"), (living_rules::map::Terrain::Forest, "forest")] {
            let mut best: Option<(f32, (f32, f32))> = None;
            for dy in -8i32..=8 {
                for dx in -8i32..=8 {
                    if map.get(at.0 as i32 + dx, at.1 as i32 + dy) == t {
                        let p = (at.0.floor() + dx as f32 + 0.5, at.1.floor() + dy as f32 + 0.5);
                        let d = dist(at, p);
                        if best.map_or(true, |b| d < b.0) {
                            best = Some((d, p));
                        }
                    }
                }
            }
            if let Some((_, p)) = best {
                terrain.push(format!("{word} to the {}", direction(at, p)));
            }
        }
        let mut parts = vec![format!("You come to a place new to you, around ({:.0}, {:.0})", at.0, at.1)];
        if !res.is_empty() {
            parts.push(format!("here: {res}"));
        }
        if !terrain.is_empty() {
            parts.push(terrain.join(", "));
        }
        if !structures.is_empty() {
            parts.push(format!("you see {}", structures.join(", ")));
        }
        parts.join("; ") + "."
    }

    fn after(mut self, result: St, root: &Node) {
        let ctx = self.ctx;
        let id = self.me.id;
        // Interrupt an activity no running leaf owns anymore (the branch lost priority);
        // a deliberate act is not the graph's to interrupt (only a reflex does, in `leaf`).
        if let Some(a) = ctx.db.activity().id().find(id) {
            if act::held(a.node) {
                self.running = Some(a.node);
                self.status = format!("{} (decided)", a.label);
                self.path.clear();
            } else if (self.running != Some(a.node) || a.revision != self.st.revision) && !crate::combat::committed(&common::scripts(ctx), &a) {
                // A committed move (a dodge, a windup) runs its course though the branch that
                // started it no longer holds (combat minds §3.2, committed-moves).
                act::cancel(ctx, a, self.now, None);
            }
        }
        if self.me.ai {
            match result {
                // A plan with nothing applicable backs off longer than one that hit a concrete
                // obstacle, so an all-guards graph doesn't re-think several times a minute.
                St::Fail if !self.mark_recent(ROOT_MARK, if self.last_fail.is_empty() { 60_000 } else { 40_000 }) => {
                    self.set_mark(ROOT_MARK);
                    let why = if self.last_fail.is_empty() { "no branch applies".to_string() } else { self.last_fail.clone() };
                    self.deliberate(&format!("Nothing in my current plan works right now ({why})."));
                }
                St::Ok if matches!(root, Node::Seq(_)) && !self.mark_recent(ROOT_MARK, 8_000) => {
                    self.set_mark(ROOT_MARK);
                    self.deliberate("I finished my plan.");
                }
                _ => {}
            }
            if self.st.fails >= 4 && !self.mark_recent(FAIL_MARK, 30_000) {
                self.set_mark(FAIL_MARK);
                self.st.fails = 0;
                let why = if self.last_fail.is_empty() { "things keep going wrong".to_string() } else { self.last_fail.clone() };
                self.deliberate(&format!("My actions keep failing ({why})."));
            }
            let base = common::species(&self.me.kind).map(|s| s.cognition.reflect_s * 1000).unwrap_or(150_000);
            let period = base + (id as u64 % 7) * 20_000;
            if self.now.saturating_sub(self.st.deliberated_ms) > period && !self.mark_recent(REFLECT_MARK, period) {
                self.set_mark(REFLECT_MARK);
                self.deliberate("A quiet moment to take stock of how things are going.");
            }
            // Cues keep their own interval (`cue_check_s`); what is new is looked for at most
            // once a second per character (fix 2), not at every woken or combat evaluation.
            self.cues();
            let (me, now) = (self.me.id, self.now);
            if NOTICED_AT.with(|n| n.borrow().get(&me).map_or(true, |t| now.saturating_sub(*t) >= NOTICE_MS)) {
                NOTICED_AT.with(|n| n.borrow_mut().insert(me, now));
                self.noticed();
            }
        }
        // Known ground (docs/MOVEMENT_MIND.md, step 3): every character, a person's too, marks
        // the ground it sees at the noticing cadence; a walk planned over what it had seen is
        // planned again when it now sees its way blocked.
        let (me, now) = (self.me.id, self.now);
        if LOOKED_AT.with(|n| n.borrow().get(&me).map_or(true, |t| now.saturating_sub(*t) >= NOTICE_MS)) {
            LOOKED_AT.with(|n| n.borrow_mut().insert(me, now));
            if let Some(b) = ctx.db.body().id().find(me) {
                let marked = crate::known::mark(ctx, me, self.at, common::facing_at(&b, now), now);
                if marked > 0 && common::laws(ctx).nav_belief {
                    crate::motion::replan_if_blocked(ctx, me, now);
                }
            }
        }
        if result != St::Run && !self.running.is_some_and(act::held) {
            self.status = match result {
                St::Ok => "done".into(),
                _ => {
                    if self.last_fail.is_empty() {
                        "idle".into()
                    } else {
                        format!("stuck: {}", self.last_fail)
                    }
                }
            };
            self.path.clear();
        }
        // Merge the fields evaluation owns into the current row (actions and speech may
        // have updated others during this evaluation).
        let Some(mut cur) = ctx.db.mind_state().id().find(id) else { return };
        let before = cur.clone();
        cur.active = self.path.clone();
        cur.status = self.status.clone();
        cur.cursors = self.st.cursors.clone();
        // Speech and signal marks may be written during evaluation; keep their stored
        // values. The top three marks are evaluator timers, despite sharing the high range.
        let mut marks: Vec<Mark> = self.st.marks.iter().filter(|m| m.node < 0xD000 || m.node >= REFLECT_MARK).cloned().collect();
        marks.extend(cur.marks.iter().filter(|m| m.node >= 0xD000 && m.node < REFLECT_MARK).cloned());
        cur.marks = marks;
        // The seen marks live in the per-character seen set now (`SEEN`); the row's own list
        // stays empty, so it is not rewritten at every evaluation.
        cur.seen = Vec::new();
        cur.alerts = self.st.alerts;
        if self.st.last != self.orig.last && cur.last == self.orig.last {
            cur.last = self.st.last.clone();
        }
        // Refused starts counted here add to the row's fails; a deliberation about them
        // resets it (unless a failure was reported meanwhile).
        if self.st.fails == 0 && cur.fails == self.orig.fails {
            cur.fails = 0;
        } else if self.st.fails > self.orig.fails {
            cur.fails = cur.fails.saturating_add(self.st.fails - self.orig.fails);
        }
        if cur != before {
            ctx.db.mind_state().id().update(cur);
        }
    }
}

/// A person seen too far away to make out is looked at again after this long (`noticed`,
/// `far_wait`), under a mark of their own in `seen` (`FAR_MARK | id`).
const FAR_RECHECK_MS: u64 = 5_000;
const FAR_MARK: u32 = 0x2000_0000;

/// First sights of one look that share one line (`noticed`).
const FIRST_SIGHTS_PER_LINE: usize = 8;

/// "a" or "an" before a kind's words.
thread_local! {
    /// Each character's last `status_of` answer and until when it stands (docs/BATTLE_SCALE.md,
    /// battle-cheap path 2): the script revision, its body row, stage and night it was asked for,
    /// and the first moment a fact the law reads can change with that row. A cache of the law's
    /// answer: lost, the law is asked again.
    static ALARM_CELLS: std::cell::RefCell<std::collections::HashMap<u32, AlarmCell>> = std::cell::RefCell::new(std::collections::HashMap::new());
}

struct AlarmCell {
    rev: u32,
    row: [u64; 20],
    stage: u8,
    night: bool,
    until: u64,
    statuses: Rc<Vec<living_rules::script::Status>>,
}

/// The body's statuses by the `status_of` law: from the character's cell while its row, stage
/// and night are unchanged and no fact the law reads has moved (the `alarm_cells` law), else
/// asked. The same statuses at the same moments: `alarm_cells_check` compares each.
fn alarm_statuses(ctx: &ReducerContext, sc: &living_rules::script::Scripts, me: &Character, vit: &Vitals, night: bool, now: u64) -> Rc<Vec<living_rules::script::Status>> {
    let laws = common::laws(ctx);
    let ask = || {
        let facts = living_rules::script::BodyFacts::of(&me.kind, crate::common::stage_name(me.stage), night, &vit.fields(), sc.meters(), now);
        sc.status_of(&facts).unwrap_or_else(|e| {
            log::warn!("status_of for {}: {e}", me.id);
            Rc::new(Vec::new())
        })
    };
    if !laws.alarm_cells {
        return ask();
    }
    let (rev, row) = (common::scripts_rev(ctx), vit.bits());
    let kept = ALARM_CELLS.with(|c| c.borrow().get(&me.id).filter(|e| e.rev == rev && e.row == row && e.stage == me.stage && e.night == night && now < e.until).map(|e| e.statuses.clone()));
    if let Some(s) = kept {
        common::diag(|| "alarm:kept", 1);
        if laws.alarm_cells_check {
            let fresh = ask();
            common::diag(|| "alarm:checked", 1);
            if fresh != s {
                common::diag(|| "alarm:differed", 1);
                log::error!("alarm cell of {}: kept {:?} differs from the law's {:?}", me.id, s.iter().map(|x| &x.name).collect::<Vec<_>>(), fresh.iter().map(|x| &x.name).collect::<Vec<_>>());
                return fresh;
            }
        }
        return s;
    }
    common::diag(|| "alarm:asked", 1);
    let statuses = ask();
    let reads = sc.status_reads();
    let until = living_rules::script::BodyFacts::next_change_ms(&vit.fields(), sc.meters(), now, reads.as_deref());
    ALARM_CELLS.with(|c| {
        let mut c = c.borrow_mut();
        if c.len() > 8192 {
            c.clear();
        }
        c.insert(me.id, AlarmCell { rev, row, stage: me.stage, night, until, statuses: statuses.clone() });
    });
    statuses
}

fn article(kind: &str) -> &'static str {
    if kind.starts_with(['a', 'e', 'i', 'o', 'u']) { "an" } else { "a" }
}

/// "For the first time you see Bram, 3 tiles north, wait." One line for several seen together:
/// "For the first time you see a stranger, 9 tiles west, wait; Bram, 3 tiles north; and Edda,
/// 5 tiles east." Its experience's subject and object are the first two named in it. Under
/// `first_sight_thinks` the same words over the unplaced parts alone are the reason a first
/// sight asks for a thought (`first_sight_asks`).
fn first_sight_text(parts: &[String]) -> String {
    match parts {
        [] => String::new(),
        [one] => format!("For the first time you see {one}."),
        [init @ .., last] => format!("For the first time you see {}; and {last}.", init.join("; ")),
    }
}

/// Whether `me`'s relationship to `other` fits a selector's relation filter. Every creature
/// filter of a graph goes through here: `sees`, `near`, `nearest` targets, `count` and
/// `health_of`.
fn relation_ok(ctx: &ReducerContext, me: u32, other: u32, want: &str) -> bool {
    // With the world's `stranger_by_name` law, "stranger" is what the scene's word means:
    // someone whose name I do not know (docs/STRANGERS.md). A relation row or its label does
    // not count: feelings about someone are not knowing their name.
    if want == "stranger" && common::laws(ctx).stranger_by_name {
        return match (ctx.db.character().id().find(me), ctx.db.character().id().find(other)) {
            (Some(a), Some(b)) => !crate::perception::knows_name(ctx, &a, &b),
            _ => false,
        };
    }
    let r = ctx.db.relation().by_pair().filter((me, other)).next();
    let label = r.as_ref().map(|r| r.label.to_lowercase()).unwrap_or_default();
    let trust = r.as_ref().map(|r| r.trust).unwrap_or(0.0);
    let fits = match want {
        "friend" => r.is_some() && (trust >= 25.0 || ["friend", "family", "partner", "ally", "kin"].iter().any(|l| label.contains(l))),
        "enemy" => r.is_some() && (trust <= -25.0 || ["enemy", "rival", "threat", "thief"].iter().any(|l| label.contains(l))),
        "family" => ["family", "partner", "kin", "child", "parent", "sibling"].iter().any(|l| label.contains(l)),
        "stranger" => r.is_none() || label.contains("stranger"),
        // Not of my community (everyone, when I belong to none).
        "outsider" => match (ctx.db.membership().member().find(me), ctx.db.membership().member().find(other)) {
            (Some(a), Some(b)) => a.community != b.community,
            (Some(_), None) | (None, _) => true,
        },
        "any" | "" => true,
        other => label.contains(&other.to_lowercase()),
    };
    fits || (r.is_none() && stance_fits(ctx, me, other, want))
}

/// Without a personal relation: how my community regards theirs, when a stance record says
/// (`friend`, `enemy` or a word of its label; docs/WORLD_RULES.md, "Standing").
fn stance_fits(ctx: &ReducerContext, me: u32, other: u32, want: &str) -> bool {
    if matches!(want, "family" | "stranger" | "outsider" | "any" | "") {
        return false;
    }
    let (a, b) = (crate::records::community_party(ctx, me), crate::records::community_party(ctx, other));
    crate::records::stance(ctx, a, b).is_some_and(|(label, value)| living_rules::records::stance_fits(&label, value, want))
}

/// The tiles of one structure in a scene list (id, kind, owner, position, distance): those
/// reached from `start` through neighbours (within 1.5 tiles) of the same kind and owner.
fn joined_tiles(all: &[(u64, String, u32, (f32, f32), f32)], start: usize) -> Vec<usize> {
    let (_, kind, owner, _, _) = &all[start];
    let mut part = vec![start];
    let mut k = 0;
    while k < part.len() {
        let p = all[part[k]].3;
        for (j, (_, kd, ow, q, _)) in all.iter().enumerate() {
            if kd == kind && ow == owner && !part.contains(&j) && (q.0 - p.0).powi(2) + (q.1 - p.1).powi(2) <= 2.25 {
                part.push(j);
            }
        }
        k += 1;
    }
    part
}

#[cfg(test)]
mod tests {
    #[test]
    fn first_sights_of_one_look_share_one_line() {
        let p = |v: &[&str]| super::first_sight_text(&v.iter().map(|s| s.to_string()).collect::<Vec<_>>());
        assert_eq!(p(&["a stranger, 9 tiles west, wait"]), "For the first time you see a stranger, 9 tiles west, wait.");
        assert_eq!(p(&["a stranger, 9 tiles west", "Bram, 3 tiles north"]), "For the first time you see a stranger, 9 tiles west; and Bram, 3 tiles north.");
        assert_eq!(p(&["a", "b", "c"]), "For the first time you see a; b; and c.");
    }

    /// A first sight's reason for a thought (`first_sight_asks`) is the line's own words over
    /// its unplaced parts: no advice, no role, no place (docs/FIRST_SIGHT.md, against the
    /// rejected newcomer laws).
    #[test]
    fn a_first_sight_asks_in_the_line_s_own_words() {
        let reason = super::first_sight_text(&["a stranger, 7 tiles east, goto → (490,779)".to_string()]);
        assert_eq!(reason, "For the first time you see a stranger, 7 tiles east, goto → (490,779).");
        let two = super::first_sight_text(&["a stranger, 9 tiles west, wait".to_string(), "a child, 3 tiles north".to_string()]);
        assert_eq!(two, "For the first time you see a stranger, 9 tiles west, wait; and a child, 3 tiles north.");
        for r in [&reason, &two] {
            let low = r.to_lowercase();
            for w in ["newcomer", "visitor", "arriv", "new to you", "near your home", "worth", "wonder", "should", "duty"] {
                assert!(!low.contains(w), "{w} in {r}");
            }
        }
    }

    #[test]
    fn a_row_of_gate_tiles_is_one_gate() {
        let t = |id: u64, kind: &str, owner: u32, x: f32, y: f32| (id, kind.to_string(), owner, (x, y), 0.0f32);
        // A town gate three tiles wide, a second gate further along the wall, two campfires
        // side by side by different builders.
        let all = vec![t(1, "gate", 0, 10.5, 4.5), t(2, "gate", 0, 11.5, 4.5), t(3, "gate", 0, 12.5, 4.5), t(4, "gate", 0, 30.5, 4.5), t(5, "campfire", 7, 2.5, 2.5), t(6, "campfire", 8, 3.5, 2.5)];
        let mut first = super::joined_tiles(&all, 0);
        first.sort();
        assert_eq!(first, vec![0, 1, 2]);
        assert_eq!(super::joined_tiles(&all, 3), vec![3]);
        assert_eq!(super::joined_tiles(&all, 4), vec![4]);
        // The island's first gate (verify-trial-fbbase, 24 tiles in a block about 7 by 8).
        let block: Vec<(f32, f32)> = vec![(503.5, 177.5), (504.5, 178.5), (505.5, 177.5), (505.5, 178.5), (505.5, 179.5), (505.5, 180.5), (506.5, 175.5), (506.5, 176.5), (506.5, 177.5), (506.5, 178.5), (506.5, 179.5), (506.5, 180.5), (506.5, 181.5), (507.5, 177.5), (507.5, 178.5), (507.5, 179.5), (507.5, 180.5), (507.5, 181.5), (507.5, 182.5), (508.5, 178.5), (508.5, 179.5), (508.5, 180.5), (509.5, 179.5), (509.5, 180.5)];
        let gate: Vec<_> = block.iter().enumerate().map(|(i, p)| t(100 + i as u64, "gate", 0, p.0, p.1)).collect();
        assert_eq!(super::joined_tiles(&gate, 7).len(), 24);
    }
}
