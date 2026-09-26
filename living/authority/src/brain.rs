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
const REFLECT_MARK: u16 = u16::MAX - 3;
/// Alert bits for ongoing situations (bits 1..8 are bodily alarms).
const IN_CROWD: u32 = 1 << 8;
const WOLF_NEAR: u32 = 1 << 9;
const FAMILIAR_LIMIT: usize = 256;
/// Marks at 0xC000 | node: when a desire last began to act.
const DESIRE_MARK: u16 = 0xC000;
/// Set when the current plan's routine completes; cleared by the next install.
const PLAN_DONE_MARK: u16 = 0xCFFF;

struct Scene {
    creatures: Vec<NearCreature>,
    resources: Vec<(ResourceNode, f32)>,
    structures: Vec<(Structure, f32)>,
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
    running: Option<u16>,
    path: Vec<u16>,
    status: String,
    visits: u32,
    last_fail: String,
    want: (String, u32),
    /// Node of the activity in progress if it is work that completes on its own (see `latches`).
    latched: Option<u16>,
}

/// Work that, once begun under an `if`, is finished even after the `if`'s condition stops
/// holding (sleeping until rested, not until barely awake). Movement and combat stay reactive.
const LATCHES: &[&str] = &["sleep", "rest", "eat", "gather", "build", "craft", "cook", "teach", "experiment", "write", "read", "plant", "store", "take", "give"];

pub fn evaluate(ctx: &ReducerContext, id: u32, now: u64) {
    let Some(me) = ctx.db.character().id().find(id) else { return };
    if !me.alive {
        return;
    }
    let (Some(st), Some(body), Some(vit)) = (ctx.db.mind_state().id().find(id), ctx.db.body().id().find(id), ctx.db.vitals().id().find(id)) else { return };
    if let Some(mut k) = ctx.db.clock().id().find(0) {
        k.evals += 1;
        ctx.db.clock().id().update(k);
    }
    let w = common::world(ctx);
    let at = pos(&body, now);
    let Some(vit) = settle_needs(ctx, &me, vit, at, &w, now) else { return };
    let needs = common::needs(&vit, now);
    let Some(g) = common::compiled(ctx, id, st.revision) else {
        log::warn!("character {id} has no valid graph at revision {}", st.revision);
        return;
    };
    let mut ev = Ev { ctx, now, w, me, at, needs, vit, orig: st.clone(), st, g, scene: None, running: None, path: Vec::new(), status: String::new(), visits: 0, last_fail: String::new(), want: (String::new(), 0), latched: None };
    ev.latched = ctx.db.activity().id().find(id).filter(|a| a.revision == ev.st.revision && LATCHES.contains(&a.skill.as_str())).map(|a| a.node);
    ev.alerts();
    let root = ev.g.clone();
    let result = ev.run(&root.root, 0);
    ev.after(result, &root.root);
}

/// Re-anchor needs when their rate inputs change; handles death from needs.
fn settle_needs(ctx: &ReducerContext, me: &Character, mut v: Vitals, at: (f32, f32), w: &World, now: u64) -> Option<Vitals> {
    let n = common::needs(&v, now);
    if n.hp <= 0.0 {
        let cause = if n.hunger >= 100.0 {
            "starvation"
        } else if common::night(w, now) && me.kind == "person" {
            "cold and exposure"
        } else {
            "exhaustion"
        };
        act::die(ctx, me.id, cause, now, 0);
        return None;
    }
    let facts = act::facts(ctx, me.id, now);
    let night = common::night(w, now);
    let key = 1
        | (night as u32) << 1
        | ((n.hunger >= 100.0) as u32) << 2
        | ((n.hunger < 70.0) as u32) << 3
        | ((n.energy > 15.0) as u32) << 4
        | ((n.energy <= 0.0) as u32) << 5
        | (facts.near_fire as u32) << 6
        | (facts.near_shelter as u32) << 7
        | ((facts.activity == "sleep") as u32) << 8
        | ((facts.activity == "rest") as u32) << 9;
    if key == v.rate_key {
        return Some(v);
    }
    let sc = common::scripts(ctx);
    let hour = common::hour(w, now);
    let sctx = living_rules::script::SkillCtx { actor: facts, night, hour, ..Default::default() };
    let _ = at;
    if let Ok(r) = sc.rates(&sctx) {
        common::settle(&mut v, now);
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
            let r = common::sight_for(self.ctx, self.me.id, &self.w, self.now);
            let creatures = common::creatures_near(self.ctx, self.at, r, self.now).into_iter().filter(|c| c.id != self.me.id).collect();
            let resources = common::resources_near(self.ctx, self.at, r);
            let structures = common::structures_near(self.ctx, self.at, r);
            self.scene = Some(Scene { creatures, resources, structures });
        }
        self.scene.as_ref().unwrap()
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
        let night = if common::night(&self.w, self.now) { 1.0 } else { 0.0 };
        let me = self.me.id;
        let now = self.now;
        let threatened = if self.ctx.db.activity().victim().filter(me).any(|a| a.phase == 1 && a.ends_ms > now) { 1.0 } else { 0.0 };
        // Company is one's own kind (people for a person, the herd or pack for an animal).
        let kind = self.me.kind.clone();
        let people = self.scene().creatures.iter().filter(|c| *c.kind == *kind).count() as f32;
        let alone = if people == 0.0 { 1.0 } else { 0.0 };
        let company = (people / 5.0).min(1.0);
        let winter = if common::season(self.ctx, now) == "winter" { 1.0 } else { 0.0 };
        let courted = if ds.iter().any(|d| d.weight.courted != 0.0) && self.resolve(&graph::Target::Suitor).is_some() { 1.0 } else { 0.0 };
        let judgments: Vec<(String, f32)> = if ds.iter().any(|d| !d.weight.believes.is_empty()) {
            self.ctx.db.judgment().actor().filter(me).map(|j| (j.key.to_lowercase(), j.value)).collect()
        } else {
            Vec::new()
        };
        let mut order: Vec<(f32, usize)> = ds
            .iter()
            .enumerate()
            .map(|(i, d)| {
                let w = &d.weight;
                let last = self.st.marks.iter().find(|m| m.node == DESIRE_MARK | ids[i]).map(|m| m.at_ms);
                let longing = last.map_or(1.0, |t| (now.saturating_sub(t) as f32 / 3_600_000.0).min(1.0));
                let mut s = w.base + w.hunger * hunger + w.tired * tired + w.hurt * hurt + w.night * night + w.day * (1.0 - night) + w.threatened * threatened + w.alone * alone + w.company * company + w.winter * winter + w.longing * longing + w.courted * courted;
                for (k, v) in &w.believes {
                    let j = judgments.iter().find(|(key, _)| key == &k.to_lowercase()).map(|(_, x)| *x).unwrap_or(0.5);
                    s += v * j;
                }
                if current == i + 1 {
                    s += 0.1;
                }
                (s, i)
            })
            .collect();
        order.sort_by(|a, b| b.0.total_cmp(&a.0));
        // A plan that has been carried out is done: it stops competing until the mind makes a new one.
        let plan_label = format!("routine:{}", graph::PLAN_ROUTINE);
        let is_plan = |n: &Node| matches!(n, Node::First(c) if c.label.as_deref().is_some_and(|l| l.eq_ignore_ascii_case(&plan_label)));
        let plan_done = self.st.marks.iter().any(|m| m.node == PLAN_DONE_MARK);
        for (score, i) in order {
            if score <= 0.0 {
                break;
            }
            let plan = is_plan(&ds[i].body);
            if plan && plan_done {
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
                let holds = latched || self.cond(&i.cond);
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
                let target = match &a.target {
                    Some(t) => match self.resolve(t) {
                        Some(r) => r,
                        None => return self.leaf_fail(id, &format!("{}: no {} in sight", a.skill, graph::describe_target(t))),
                    },
                    None => Resolved::none(),
                };
                self.want = (a.want.clone().unwrap_or_default(), a.want_qty.unwrap_or(0));
                self.leaf(id, &a.skill, target, a.item.as_deref().unwrap_or(""), a.qty.unwrap_or(0), a.text.as_deref().unwrap_or(""), a.topic.as_deref().unwrap_or(""), graph::describe(n))
            }
            Node::Wait(s) => self.leaf(id, "wait", Resolved::none(), "", s.round().max(1.0) as u32, "", "", graph::describe(n)),
            Node::Say(s) => {
                if self.mark_recent(id, 45_000) {
                    return St::Ok;
                }
                let to = match &s.to {
                    Some(t) => match self.resolve(t) {
                        Some(r) if r.class == 3 => r.id as u32,
                        _ => return St::Fail,
                    },
                    None => 0,
                };
                self.set_mark(id);
                match perceive::speak(self.ctx, self.me.id, &s.text, to, self.now) {
                    Ok(()) => St::Ok,
                    Err(_) => St::Fail,
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

    fn leaf_fail(&mut self, id: u16, why: &str) -> St {
        let _ = id;
        self.last_fail = why.to_string();
        St::Fail
    }

    #[allow(clippy::too_many_arguments)]
    fn leaf(&mut self, id: u16, skill: &str, target: Resolved, item: &str, qty: u32, text: &str, topic: &str, desc: String) -> St {
        let rev = self.st.revision;
        if let Some(a) = self.ctx.db.activity().id().find(self.me.id) {
            if a.node == id && a.revision == rev {
                self.running = Some(id);
                self.status = a.label;
                return St::Run;
            }
        }
        if let Some(l) = self.st.last.clone() {
            if l.node == id && l.revision == rev {
                self.st.last = None;
                if l.ok {
                    return St::Ok;
                }
                self.last_fail = l.why.clone();
                return St::Fail;
            }
        }
        let want = std::mem::take(&mut self.want);
        match act::begin(self.ctx, self.me.id, id, rev, skill, target, item, qty, text, topic, (&want.0, want.1), self.now) {
            Ok(()) => {
                self.running = Some(id);
                self.status = self.ctx.db.activity().id().find(self.me.id).map(|a| a.label).unwrap_or(desc);
                St::Run
            }
            Err(why) => {
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
        let r = self.relation(other);
        let label = r.as_ref().map(|r| r.label.to_lowercase()).unwrap_or_default();
        let trust = r.as_ref().map(|r| r.trust).unwrap_or(0.0);
        match want {
            "friend" => r.is_some() && (trust >= 25.0 || ["friend", "family", "partner", "ally", "kin"].iter().any(|l| label.contains(l))),
            "enemy" => r.is_some() && (trust <= -25.0 || ["enemy", "rival", "threat", "thief"].iter().any(|l| label.contains(l))),
            "family" => ["family", "partner", "kin", "child", "parent", "sibling"].iter().any(|l| label.contains(l)),
            "stranger" => r.is_none() || label.contains("stranger"),
            "any" | "" => true,
            other => label.contains(&other.to_lowercase()),
        }
    }

    fn visible_creature(&mut self, id: u32) -> Option<Resolved> {
        let c = self.scene().creatures.iter().find(|c| c.id == id)?.clone();
        let ch = self.ctx.db.character().id().find(id)?;
        Some(Resolved { class: 3, id: id as u64, at: c.pos, kind: c.kind.to_string(), name: ch.name })
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
                    self.visible_creature(self.st.speaker)
                } else {
                    None
                }
            }
            Target::Suitor => {
                let window = (common::laws(self.ctx).bond_window_s * 1000.0) as u64;
                let offer = self.ctx.db.bond_offer().to().filter(self.me.id).filter(|o| now.saturating_sub(o.at_ms) <= window).max_by_key(|o| o.at_ms)?;
                self.visible_creature(offer.from)
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
            Target::Home => {
                if let Some(p) = self.place("home") {
                    return Some(p);
                }
                Some(Resolved::point((self.me.home_x, self.me.home_y)))
            }
            Target::Wander => Some(Resolved::point(self.at)),
            Target::Place(name) => self.place(name),
            Target::At([x, y]) => Some(Resolved::point((*x, *y))),
            Target::Id(id) => self.visible_creature(*id),
            Target::Named(name) => {
                let ids: Vec<u32> = self.scene().creatures.iter().filter(|c| &*c.kind == "person").map(|c| c.id).collect();
                let id = ids.into_iter().find(|id| self.ctx.db.character().id().find(*id).map_or(false, |c| c.name.eq_ignore_ascii_case(name)))?;
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
                let cands: Vec<NearCreature> = self.scene().creatures.clone();
                for c in cands {
                    if f.kind != "creature" && *c.kind != *f.kind {
                        continue;
                    }
                    if let Some(rel) = &f.relation {
                        if !self.relation_ok(c.id, rel) {
                            continue;
                        }
                    }
                    if let Some(r) = self.visible_creature(c.id) {
                        return Some(r);
                    }
                }
                None
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
            living_rules::catalog::KindClass::Structure => {
                let me = self.me.id;
                self.scene()
                    .structures
                    .iter()
                    .find(|(s, _)| s.kind == f.kind && (!f.mine || s.owner == me))
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
            Cond::Has(h) => {
                let n = if h.item == "food" { common::food_count(self.ctx, self.me.id as u64) } else { common::inv_count(self.ctx, self.me.id as u64, &h.item) };
                n >= h.at_least
            }
            Cond::Sees(t) => match t {
                Target::Place(_) | Target::At(_) | Target::Home => {
                    let r = common::sight(self.ctx, &self.w, self.now);
                    self.resolve(t).map_or(false, |p| dist(self.at, p.at) <= r)
                }
                _ => self.resolve(t).is_some(),
            },
            Cond::Near(n) => self.resolve(&n.target).map_or(false, |p| dist(self.at, p.at) <= n.within),
            Cond::HurtWithin(s) => self.vit.hurt_ms != 0 && self.now.saturating_sub(self.vit.hurt_ms) as f32 <= s * 1000.0,
            Cond::HeardWithin(s) => self.st.heard_ms != 0 && self.now.saturating_sub(self.st.heard_ms) as f32 <= s * 1000.0,
            Cond::Night(b) => common::night(&self.w, self.now) == *b,
            Cond::Hour(x) => x.test(common::hour(&self.w, self.now)),
            Cond::Threatened(b) => {
                let me = self.me.id;
                let now = self.now;
                let coming = self.ctx.db.activity().victim().filter(me).any(|a| a.phase == 1 && a.ends_ms > now && (a.skill == "attack" || a.skill == "throw"));
                coming == *b
            }
            Cond::Believes(b) => self
                .ctx
                .db
                .judgment()
                .actor()
                .filter(self.me.id)
                .find(|j| j.key.eq_ignore_ascii_case(&b.key))
                .map_or(false, |j| j.value > b.above),
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
        let night = common::night(&self.w, self.now);
        let facts_fire = self.vit.hp_rate < 0.0 && night && self.needs.hunger < 100.0;
        let checks: [(u32, bool, &str, f32); 5] = [
            (1, self.needs.hunger >= 80.0, "You are very hungry.", 0.5),
            (64, self.needs.hunger >= 97.0, "You are starving: your body is wasting away.", 0.8),
            (2, self.needs.hp < 40.0, "You are badly hurt.", 0.7),
            (4, facts_fire, "You are freezing in the night air; you need a fire or shelter.", 0.6),
            (8, self.needs.energy < 12.0, "You are exhausted.", 0.4),
        ];
        // Psychological drives: an uneventful stretch makes curious people restless; time without
        // company makes sociable people lonely. They are felt, not prescribed: the mind decides.
        let traits: serde_json::Value = self.ctx.db.persona().id().find(self.me.id).and_then(|p| serde_json::from_str(&p.traits).ok()).unwrap_or_default();
        let trait_of = |k: &str| traits[k].as_f64().unwrap_or(50.0) as f32;
        let calm = self.needs.hunger < 60.0 && self.needs.energy > 35.0 && self.needs.hp > 60.0;
        let quiet_ms = self.now.saturating_sub(self.st.deliberated_ms);
        let restless_after = 60_000.0 * (12.0 - trait_of("curiosity") / 12.0);
        let lonely_after = 60_000.0 * (14.0 - trait_of("sociability") / 10.0);
        let alone_ms = self.now.saturating_sub(self.st.heard_ms.max(self.st.spoke_ms));
        let drives: [(u32, bool, &str); 2] = [
            (16, calm && quiet_ms as f32 > restless_after, "You feel restless: your days have been the same for a while."),
            (32, calm && self.st.heard_ms > 0 && alone_ms as f32 > lonely_after, "You feel lonely: it has been a long time since you spoke with anyone."),
        ];
        for (bit, on, text) in drives {
            let was = self.st.alerts & bit != 0;
            if on && !was {
                self.st.alerts |= bit;
                percept(self.ctx, &self.me, self.now, "feeling", self.me.id, 0, self.at, text.into(), 0.5);
                self.deliberate(&format!("You feel something: {text}"));
            } else if !on && was {
                self.st.alerts &= !bit;
            }
        }
        for (bit, on, text, sal) in checks {
            let was = self.st.alerts & bit != 0;
            if on && !was {
                self.st.alerts |= bit;
                percept(self.ctx, &self.me, self.now, "body", self.me.id, 0, self.at, text.into(), sal);
                let urgent = match bit {
                    1 => common::food_count(self.ctx, self.me.id as u64) == 0,
                    2 | 4 | 64 => true,
                    _ => false,
                };
                if urgent {
                    self.deliberate(&format!("Your body: {text}"));
                }
            } else if !on && was {
                self.st.alerts &= !bit;
            }
        }
    }

    /// Look up (and refresh) bodily familiarity; returns the previous record, if any.
    fn familiarity(&mut self, thing: u64) -> Option<Familiar> {
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
                let row = self.ctx.db.familiar().insert(Familiar { id: 0, actor: self.me.id, thing, first_ms: self.now, last_ms: self.now, times: 1 });
                if row.id % 16 == 0 {
                    let mut all: Vec<(u64, u64)> = self.ctx.db.familiar().actor().filter(self.me.id).map(|f| (f.last_ms, f.id)).collect();
                    if all.len() > FAMILIAR_LIMIT {
                        all.sort_unstable();
                        for (_, id) in &all[..all.len() - FAMILIAR_LIMIT] {
                            self.ctx.db.familiar().id().delete(*id);
                        }
                    }
                }
            }
        }
        prev
    }

    /// Recently checked (fast path that avoids familiarity lookups every second).
    fn recently_seen(&mut self, key: u32) -> bool {
        let now = self.now;
        if let Some(s) = self.st.seen.iter_mut().find(|s| s.id == key) {
            if now.saturating_sub(s.at_ms) < 90_000 {
                if now.saturating_sub(s.at_ms) > 45_000 {
                    s.at_ms = now;
                }
                return true;
            }
            s.at_ms = now;
            return false;
        }
        self.st.seen.push(Seen { id: key, at_ms: now });
        if self.st.seen.len() > 96 {
            self.st.seen.remove(0);
        }
        false
    }

    /// Turn what is new to this character into experiences: unfamiliar regions, first
    /// encounters, long-absent faces, nearby danger and newly noticed structures. Routine
    /// re-perception only refreshes familiarity, so experience volume follows novelty.
    fn noticed(&mut self) {
        if !self.me.ai {
            return;
        }
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
        let mut announced = 0;
        for c in cands {
            if announced >= 2 {
                break;
            }
            if crowded && &*c.kind == "person" && self.relation(c.id).is_none() {
                continue;
            }
            let danger = wolf_arrived && &*c.kind == "wolf" && c.dist <= laws.danger_near;
            if self.recently_seen(c.id) && !danger {
                continue;
            }
            let prev = self.familiarity(FAM_CREATURE | c.id as u64);
            let Some(ch) = self.ctx.db.character().id().find(c.id) else { continue };
            let who = common::label_for(self.ctx, &self.me, c.id);
            let doing = self.ctx.db.activity().id().find(c.id).map(|a| format!(", {}", a.label)).unwrap_or_default();
            let place = format!("{:.0} tiles {}{doing}", c.dist, direction(at, c.pos));
            let (text, sal) = match prev {
                None if ch.kind == "person" || ch.kind == self.me.kind => (format!("For the first time you see {who}, {place}."), 0.45),
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

        // Structures.
        let structures: Vec<(u64, String, u32, (f32, f32), f32)> = self.scene().structures.iter().map(|(s, d)| (s.id, s.kind.clone(), s.owner, (s.x, s.y), *d)).collect();
        for (id, kind, owner, pos, dist) in structures {
            if self.recently_seen(0x4000_0000 | (id as u32 & 0x3fff_ffff)) || self.familiarity(FAM_STRUCTURE | id).is_some() {
                continue;
            }
            if owner == self.me.id {
                continue;
            }
            let by = if owner != 0 && kind != "remains" { format!(" built by {}", common::name_of(self.ctx, owner)) } else if kind == "remains" { format!(" — the remains of {}", common::name_of(self.ctx, owner)) } else { String::new() };
            let text = format!("You notice a {kind}{by}, {dist:.0} tiles {}.", direction(at, pos));
            percept(self.ctx, &self.me, now, "saw", owner, 0, pos, text, if kind == "remains" { 0.8 } else { 0.35 });
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
        let structures: Vec<String> = self
            .scene()
            .structures
            .iter()
            .take(4)
            .map(|(s, _)| if s.owner != 0 { format!("{}'s {}", common::name_of(ctx, s.owner), s.kind) } else { s.kind.clone() })
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
        // Interrupt an activity no running leaf owns anymore (the branch lost priority).
        if let Some(a) = ctx.db.activity().id().find(id) {
            if self.running != Some(a.node) || a.revision != self.st.revision {
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
            self.noticed();
        }
        if result != St::Run {
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
        // Marks at 0xD000 and above are written by speech, signals and failures (possibly during
        // this evaluation); keep those from the stored row, the rest are the evaluator's.
        let mut marks: Vec<Mark> = self.st.marks.iter().filter(|m| m.node < 0xD000).cloned().collect();
        marks.extend(cur.marks.iter().filter(|m| m.node >= 0xD000).cloned());
        cur.marks = marks;
        cur.seen = self.st.seen.clone();
        cur.alerts = self.st.alerts;
        if self.st.last != self.orig.last && cur.last == self.orig.last {
            cur.last = self.st.last.clone();
        }
        if self.st.fails == 0 && self.orig.fails > 0 && cur.fails == self.orig.fails {
            cur.fails = 0;
        }
        if cur != before {
            ctx.db.mind_state().id().update(cur);
        }
    }
}
