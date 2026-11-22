//! E2 prototype, branch `attention-e2` only (docs/ATTENTION_E2_COST.md, after ATTENTION_BUDGET v2):
//! a player perceives at most its capacity of others as individuals, the rest of those in sight
//! as crowd rows per 6 m cell (`attend_on`; capacity `attend_ceiling`, or `attend_burst_cap`).
//! Built only to measure what that costs (docs/ATTENTION_BUDGET.md §5.2); it never goes to main.
//! Every law here is off by default, and off it changes nothing: the sweep reads none of this
//! module and no row is written.
//!
//! - **Who is attended** (`choose`), by `attend_policy`: 0 the engaged (past capacity) then the
//!   nearest (a distance rule, low churn); 1 the engaged then a rank drawn afresh every
//!   `attend_reorder_ms` (high churn: a stand-in for a policy that reorders its picks); 2 the
//!   person instinct's ranked order over per-creature features, bounded by capacity (v2).
//! - **Copy grace** (`attend_grace_ms`): a creature the policy drops stays delivered that long
//!   (beyond N) before its copies go; a promotion meanwhile ends its grace.
//! - **Crowd rows** (`attend_crowd_on`): everyone else in sight, binned into world-aligned 6 m
//!   cells at 1 Hz per viewer, at most 48 cells (farther cells merged 2x2, then again), each a
//!   keyed row written only when its quantized content changed.
//!
//! Not computed in the prototype (zero in every row): `moving` and `fallen` (they would need
//! each member's body or the remains nearby; the cost would add to the crowd's).
use std::cell::RefCell;
use std::collections::{HashMap, HashSet};

use spacetimedb::{Identity, ReducerContext, Table};

use crate::common;
use crate::tables::vitals as _;

/// The crowd as one viewer receives it: one row per cell with members in sight that it does not
/// attend. `id` is the viewer's character (high 32 bits), the merge level (bits 30-31) and the
/// cell (`cx`, `cy`), so a change is one update in place.
#[spacetimedb::table(accessor = seen_crowd, public)]
pub struct SeenCrowd {
    #[primary_key]
    pub id: u64,
    #[index(btree)]
    pub viewer: Identity,
    pub cx: i16,
    pub cy: i16,
    pub count: u16,
    pub x: f32,
    pub y: f32,
    pub spread: f32,
    pub heading: u8,
    pub moving: u8,
    pub fighting: u16,
    pub fallen: u16,
    pub kinds: u8,
}

#[spacetimedb::client_visibility_filter]
const SEEN_CROWD_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM seen_crowd WHERE viewer = :sender");

const CELL_M: f32 = 6.0;
const CROWD_MS: u64 = 1_000;
const CELLS_MAX: usize = 48;
const QUANT_M: f32 = 0.5;

#[derive(Default)]
struct Attending {
    /// Attended now (policy-chosen, engaged or in grace).
    now: HashSet<u32>,
    /// Dropped by the policy at this time, still delivered while in grace.
    grace: HashMap<u32, u64>,
    /// Policy 2's features kept between passes: each one's distance at the last pass (closing
    /// speed) and when it came into sight (`new`).
    last: HashMap<u32, (f32, u64)>,
    first_seen: HashMap<u32, u64>,
    /// In sight at the last pass, and the visible-churn counts (`attend_vis_on`).
    seen_prev: HashSet<u32>,
    vis: Vis,
    /// Crowd at the last pass, and when each was last tested by the sight rule, with the result
    /// (`attend_throng_sight_ms`).
    crowd_prev: HashSet<u32>,
    throng: HashMap<u32, (u64, bool)>,
    /// Policies 3 and 4 (heed): each heeded one's rule and when it last had its place on merit,
    /// and since when it is heeded.
    heed: HashMap<u32, (usize, u64)>,
    heeded_since: HashMap<u32, u64>,
}

/// Visible churn (the coordinator, 2026-11-22): per viewer, a creature in sight that goes from
/// individual to crowd and back (or back the other way) within 2 s and within 5 s, as the
/// viewer would see a figure flip. Counted only with `attend_vis_on`; logged once per 10 s
/// bucket per viewer as an `attend-vis` line.
#[derive(Default, Debug)]
pub struct Vis {
    /// Each creature's last change of grain while in sight: when, and whether to individual.
    last: HashMap<u32, (u64, bool)>,
    bucket: u64,
    pub flips: u32,
    pub back2: u32,
    pub back5: u32,
    pub affected: HashSet<u32>,
    pub attended: HashSet<u32>,
}

impl Vis {
    /// Creature `body`, in sight before and now, changed grain at `now` (to individual or not).
    pub fn change(&mut self, body: u32, to_individual: bool, now: u64) {
        self.flips += 1;
        if let Some((t, dir)) = self.last.get(&body) {
            if *dir != to_individual {
                let dt = now.saturating_sub(*t);
                if dt <= 2_000 {
                    self.back2 += 1;
                }
                if dt <= 5_000 {
                    self.back5 += 1;
                    self.affected.insert(body);
                }
            }
        }
        self.last.insert(body, (now, to_individual));
    }

    /// Creature `body` left sight: its history ends (coming back into sight is not a flip).
    pub fn gone(&mut self, body: u32) {
        self.last.remove(&body);
    }

    /// The bucket's summary when `now` starts a new 10 s bucket (then reset), else None.
    pub fn roll(&mut self, now: u64) -> Option<(u64, u32, u32, u32, usize, usize)> {
        let b = now / 10_000;
        if self.bucket == 0 {
            self.bucket = b;
            return None;
        }
        if b == self.bucket {
            return None;
        }
        let out = (self.bucket, self.flips, self.back2, self.back5, self.affected.len(), self.attended.len());
        self.bucket = b;
        self.flips = 0;
        self.back2 = 0;
        self.back5 = 0;
        self.affected.clear();
        self.attended.clear();
        Some(out)
    }
}

#[derive(Default)]
struct Crowd {
    last_ms: u64,
    /// What each written row holds, quantized (the change test without reading rows).
    rows: HashMap<u64, (u16, i32, i32, i32, u8, u16, u8)>,
    seeded: bool,
}

thread_local! {
    /// The person instinct of the shared selector (`living_rules::heed`, copied from attention-exp
    /// c18ca061), with its holds (policy 3) and without (policy 4).
    static HEED: (living_rules::heed::Policy, living_rules::heed::Policy) = {
        let p = living_rules::heed::instinct("person");
        let bare = living_rules::heed::without_holds(&p);
        (p, bare)
    };
    static ATT: RefCell<HashMap<u32, Attending>> = RefCell::new(HashMap::new());
    static CROWD: RefCell<HashMap<u32, Crowd>> = RefCell::new(HashMap::new());
}

fn rank(viewer: u32, body: u32, epoch: u64) -> u64 {
    // A fixed mix (splitmix64) of viewer, body and the reorder epoch: a fresh order each epoch.
    let mut z = (viewer as u64) << 32 ^ body as u64 ^ epoch.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

/// The prototype's capacity: the ceiling, or the burst cap when that is set and lower.
pub fn capacity(laws: &living_rules::script::Laws) -> usize {
    let c = if laws.attend_burst_cap > 0.0 { laws.attend_burst_cap.min(laws.attend_ceiling) } else { laws.attend_ceiling };
    c.max(0.0) as usize
}

/// Policy 2: the person instinct's order (docs/ATTENTION_BUDGET.md v2 §2.4), over features
/// computed once per creature a pass. In the fixture nobody speaks, is cued, chosen or family, so
/// those rules are not evaluated: whoever is going for me (the engagement set), my own target,
/// the 6 nearest within 8 m, then a score (closing over 1 m/s 3, acting on someone I attend 3,
/// fighting 2, a wolf 2, in sight under 5 s 1), nearer first on ties.
fn instinct(id: u32, seen: &HashSet<u32>, near: &HashMap<u32, f32>, kinds: &HashMap<u32, &str>, engaged: &HashSet<u32>, st: &mut Attending, cap: usize, now: u64) -> HashSet<u32> {
    let _span = common::detail_span("attend.features");
    struct F {
        b: u32,
        dist: f32,
        closing: f32,
        target: Option<u32>,
        fighting: bool,
        wolf: bool,
        new: bool,
    }
    let feats: Vec<F> = seen
        .iter()
        .map(|&b| {
            let dist = near.get(&b).copied().unwrap_or(f32::MAX);
            let closing = st.last.get(&b).map_or(0.0, |(d, t)| if now > *t { (d - dist) / ((now - t) as f32 / 1000.0) } else { 0.0 });
            let first = *st.first_seen.entry(b).or_insert(now);
            F { b, dist, closing, target: crate::frame::target_of(b), fighting: crate::frame::aiming(b), wolf: kinds.get(&b) == Some(&"wolf"), new: now.saturating_sub(first) < 5_000 }
        })
        .collect();
    st.last = feats.iter().map(|f| (f.b, (f.dist, now))).collect();
    st.first_seen.retain(|b, _| seen.contains(b));
    let _rank = common::detail_span("attend.rules");
    let mut keep: HashSet<u32> = HashSet::new();
    let take = |keep: &mut HashSet<u32>, mut c: Vec<&F>, n: usize, by_score: Option<&dyn Fn(&F) -> f32>| {
        match by_score {
            Some(sc) => c.sort_by(|x, y| sc(y).total_cmp(&sc(x)).then(x.dist.total_cmp(&y.dist))),
            None => c.sort_by(|x, y| x.dist.total_cmp(&y.dist)),
        }
        for f in c.into_iter().take(n) {
            if keep.len() >= cap {
                break;
            }
            keep.insert(f.b);
        }
    };
    let mine = crate::frame::target_of(id);
    take(&mut keep, feats.iter().filter(|f| engaged.contains(&f.b)).collect(), usize::MAX, None);
    let c: Vec<&F> = feats.iter().filter(|f| !keep.contains(&f.b) && Some(f.b) == mine).collect();
    take(&mut keep, c, usize::MAX, None);
    let c: Vec<&F> = feats.iter().filter(|f| !keep.contains(&f.b) && f.dist <= 8.0).collect();
    take(&mut keep, c, 6, None);
    let attended: HashSet<u32> = keep.clone();
    let score = |f: &F| {
        let mut s = 0.0;
        if f.closing > 1.0 {
            s += 3.0;
        }
        if f.target.is_some_and(|t| t == id || attended.contains(&t)) {
            s += 3.0;
        }
        if f.fighting {
            s += 2.0;
        }
        if f.wolf {
            s += 2.0;
        }
        if f.new {
            s += 1.0;
        }
        s
    };
    let c: Vec<&F> = feats.iter().filter(|f| !keep.contains(&f.b)).collect();
    take(&mut keep, c, usize::MAX, Some(&score));
    keep
}

/// Policies 3 and 4: the shared selector `living_rules::heed::select` over candidates built from
/// what the sweep knows. Simplified, as the fixture needs: `threatening` is a move aimed at me,
/// `contact_ago_s` and `hurt_me_ago_s` come from my own last hurt (blocks and dodges are not
/// kept per viewer), `doing`, `addressed`, `cued`, `chosen`, `fallen`, `loud` and `lit` are
/// empty, relations none, everyone made out, and closing is the raw change of distance between
/// two sweeps (not smoothed). The own state is a rested, unhurt adult's.
#[allow(clippy::too_many_arguments)]
fn heed_pass(ctx: &ReducerContext, id: u32, seen: &HashSet<u32>, near: &HashMap<u32, f32>, kinds: &HashMap<u32, &str>, engaged: &HashSet<u32>, st: &mut Attending, cap: usize, holds: bool, now: u64) -> HashSet<u32> {
    use living_rules::heed;
    let _span = common::detail_span("attend.features");
    let mine = crate::frame::target_of(id);
    let hurt = ctx.db.vitals().id().find(id).filter(|v| v.hurt_by != 0).map(|v| (v.hurt_by, now.saturating_sub(v.hurt_ms) as f32 / 1000.0));
    let all: Vec<heed::Candidate> = seen
        .iter()
        .map(|&b| {
            let dist = near.get(&b).copied().unwrap_or(f32::MAX);
            let closing = st.last.get(&b).map_or(0.0, |(d, t)| if now > *t { (d - dist) / ((now - t) as f32 / 1000.0) } else { 0.0 });
            let first = *st.first_seen.entry(b).or_insert(now);
            let target = crate::frame::target_of(b);
            let hurt_me = hurt.filter(|(by, _)| *by == b).map(|(_, ago)| ago);
            heed::Candidate {
                id: b,
                kind: kinds.get(&b).map_or_else(String::new, |k| k.to_string()),
                dist,
                closing,
                made_out: true,
                threatening: engaged.contains(&b) && target == Some(id),
                hurt_me_ago_s: hurt_me,
                acted_on: mine == Some(b),
                contact_ago_s: hurt_me,
                heeded_s: st.heeded_since.get(&b).map(|t| now.saturating_sub(*t) as f32 / 1000.0),
                in_sight_s: now.saturating_sub(first) as f32 / 1000.0,
                fighting: crate::frame::aiming(b),
                acting_on_heeded: target.is_some_and(|t| st.now.contains(&t)),
                ..Default::default()
            }
        })
        .collect();
    st.last = all.iter().map(|c| (c.id, (c.dist, now))).collect();
    st.first_seen.retain(|b, _| seen.contains(b));
    let held: Vec<heed::Held> = st
        .heed
        .iter()
        .filter(|(b, _)| seen.contains(b))
        .map(|(b, (rule, merit))| heed::Held { id: *b, rule: *rule, lapsed_s: now.saturating_sub(*merit) as f32 / 1000.0 })
        .collect();
    let me = heed::SelfState { health: 100.0, energy: 100.0, hunger: 0.0, stamina: 100.0, night: false, hurt_ago_s: hurt.map(|(_, a)| a) };
    let _rules = common::detail_span("attend.rules");
    let picks = HEED.with(|(with, bare)| heed::select(if holds { with } else { bare }, &me, &all, &heed::Limits::new(cap), if holds { &held } else { &[] }));
    drop(_rules);
    let mut next: HashMap<u32, (usize, u64)> = HashMap::new();
    for p in &picks {
        if let Some(r) = p.place.rule() {
            let merit = if p.held { st.heed.get(&p.id).map_or(now, |(_, m)| *m) } else { now };
            next.insert(p.id, (r, merit));
        }
    }
    st.heed = next;
    let keep: HashSet<u32> = picks.iter().map(|p| p.id).collect();
    for b in &keep {
        st.heeded_since.entry(*b).or_insert(now);
    }
    st.heeded_since.retain(|b, _| keep.contains(b));
    common::diag(|| "attend:held", picks.iter().filter(|p| p.held).count() as u64);
    keep
}

/// The creatures viewer `id` attends among `seen` (with their distances in `near`; `crowd` is the
/// sweep's gather, for kinds). Policies 0 and 1: the engaged always, past capacity (v1's rule);
/// then the places left. Policy 2: the instinct's ranked order, bounded by capacity (v2: no
/// overflow). Then any in grace.
pub fn choose(ctx: &ReducerContext, id: u32, seen: &HashSet<u32>, near: &HashMap<u32, f32>, crowd: &[(common::NearCreature, u32)], now: u64) -> HashSet<u32> {
    let laws = common::laws(ctx);
    let n = capacity(&laws);
    let engaged = crate::frame::engaged_with(id);
    let grace_ms = laws.attend_grace_ms.max(0.0) as u64;
    ATT.with(|a| {
        let mut a = a.borrow_mut();
        let st = a.entry(id).or_default();
        let mut keep: HashSet<u32>;
        if laws.attend_policy >= 3.0 {
            let kinds: HashMap<u32, &str> = crowd.iter().filter(|(c, _)| seen.contains(&c.id)).map(|(c, _)| (c.id, &*c.kind)).collect();
            keep = heed_pass(ctx, id, seen, near, &kinds, &engaged, st, n, laws.attend_policy < 4.0, now);
        } else if laws.attend_policy >= 2.0 {
            let kinds: HashMap<u32, &str> = crowd.iter().filter(|(c, _)| seen.contains(&c.id)).map(|(c, _)| (c.id, &*c.kind)).collect();
            keep = instinct(id, seen, near, &kinds, &engaged, st, n, now);
        } else {
            keep = seen.iter().copied().filter(|b| engaged.contains(b)).collect();
            let mut rest: Vec<(u64, u32)> = seen
                .iter()
                .copied()
                .filter(|b| !keep.contains(b))
                .map(|b| {
                    let key = if laws.attend_policy >= 1.0 {
                        rank(id, b, now / (laws.attend_reorder_ms.max(50.0) as u64))
                    } else {
                        (near.get(&b).copied().unwrap_or(f32::MAX) * 1000.0) as u64
                    };
                    (key, b)
                })
                .collect();
            rest.sort();
            let room = n.saturating_sub(keep.len());
            keep.extend(rest.iter().take(room).map(|(_, b)| *b));
        }
        let mut promoted = 0u64;
        let mut demoted = 0u64;
        for b in &keep {
            st.grace.remove(b);
            if !st.now.contains(b) {
                promoted += 1;
            }
        }
        // Dropped by the policy: into grace (still delivered) or out at once.
        for b in st.now.iter().copied().collect::<Vec<_>>() {
            if keep.contains(&b) || !seen.contains(&b) {
                continue;
            }
            if grace_ms > 0 {
                st.grace.entry(b).or_insert(now);
            } else {
                demoted += 1;
            }
        }
        st.grace.retain(|b, since| {
            let stay = seen.contains(b) && now.saturating_sub(*since) < grace_ms;
            if !stay && seen.contains(b) {
                demoted += 1;
            }
            stay
        });
        let graced = st.grace.len() as u64;
        keep.extend(st.grace.keys().copied());
        if laws.attend_vis_on {
            // A change of grain counts only for a creature in sight at both passes.
            for &b in seen.iter() {
                if !st.seen_prev.contains(&b) {
                    continue;
                }
                let (was, is) = (st.now.contains(&b), keep.contains(&b));
                if was != is {
                    st.vis.change(b, is, now);
                }
            }
            for b in st.seen_prev.iter().copied().filter(|b| !seen.contains(b)).collect::<Vec<_>>() {
                st.vis.gone(b);
            }
            st.vis.attended.extend(keep.iter().copied());
            if let Some((bucket, flips, back2, back5, affected, attended)) = st.vis.roll(now) {
                log::info!("attend-vis {{\"viewer\":{id},\"bucket\":{bucket},\"flips\":{flips},\"back2\":{back2},\"back5\":{back5},\"affected\":{affected},\"attended\":{attended}}}");
            }
            st.seen_prev = seen.clone();
        }
        if laws.attend_throng_sight_ms > 0.0 {
            st.crowd_prev = seen.iter().copied().filter(|b| !keep.contains(b)).collect();
            let crowd = &st.crowd_prev;
            st.throng.retain(|b, _| crowd.contains(b));
        }
        st.now = keep.clone();
        common::diag(|| "attend:promoted", promoted);
        common::diag(|| "attend:demoted", demoted);
        common::diag(|| "attend:grace", graced);
        common::diag(|| "attend:kept", keep.len() as u64);
        keep
    })
}

fn kind_bit(kind: &str) -> u8 {
    match kind {
        "person" => 1,
        "wolf" => 2,
        "deer" => 4,
        _ => 128,
    }
}

/// The crowd rows of viewer `id` (character) / `viewer` (identity), from the creatures in sight
/// it does not attend (`members`), once a second.
pub fn crowd(ctx: &ReducerContext, id: u32, viewer: Identity, here: (f32, f32), members: &[(u32, (f32, f32), f32, &str)], now: u64) {
    let due = CROWD.with(|c| c.borrow().get(&id).is_none_or(|s| now.saturating_sub(s.last_ms) >= CROWD_MS));
    if !due {
        return;
    }
    let _span = common::detail_span("attend.crowd");
    // Bin: (level, cx, cy) -> members.
    #[derive(Default)]
    struct Cell {
        n: u32,
        sx: f32,
        sy: f32,
        hx: f32,
        hy: f32,
        fighting: u32,
        kinds: u8,
        pts: Vec<(f32, f32)>,
    }
    let mut cells: HashMap<(u8, i16, i16), Cell> = HashMap::new();
    for (b, p, facing, kind) in members {
        let key = (0u8, (p.0 / CELL_M).floor() as i16, (p.1 / CELL_M).floor() as i16);
        let c = cells.entry(key).or_default();
        c.n += 1;
        c.sx += p.0;
        c.sy += p.1;
        c.hx += facing.cos();
        c.hy += facing.sin();
        c.fighting += crate::frame::aiming(*b) as u32;
        c.kinds |= kind_bit(kind);
        c.pts.push(*p);
    }
    // At most CELLS_MAX: the farthest cells merge 2x2 (one level up), as often as needed.
    let dist = |k: &(u8, i16, i16), c: &Cell| {
        let (x, y) = (c.sx / c.n as f32, c.sy / c.n as f32);
        let _ = k;
        ((x - here.0).powi(2) + (y - here.1).powi(2)).sqrt()
    };
    let mut level = 0u8;
    while cells.len() > CELLS_MAX && level < 3 {
        let mut order: Vec<((u8, i16, i16), f32)> = cells.iter().map(|(k, c)| (*k, dist(k, c))).collect();
        order.sort_by(|a, b| a.1.total_cmp(&b.1));
        let keep_n = CELLS_MAX / 2;
        for (k, _) in order.into_iter().skip(keep_n) {
            if k.0 != level {
                continue;
            }
            let c = cells.remove(&k).unwrap();
            let up = (level + 1, k.1.div_euclid(2), k.2.div_euclid(2));
            let u = cells.entry(up).or_default();
            u.n += c.n;
            u.sx += c.sx;
            u.sy += c.sy;
            u.hx += c.hx;
            u.hy += c.hy;
            u.fighting += c.fighting;
            u.kinds |= c.kinds;
            u.pts.extend(c.pts);
        }
        level += 1;
    }
    let rows = ctx.db.seen_crowd();
    CROWD.with(|cr| {
        let mut cr = cr.borrow_mut();
        let st = cr.entry(id).or_default();
        st.last_ms = now;
        if !st.seeded {
            // A fresh instance: what this viewer already has (module memory is not kept).
            for r in rows.viewer().filter(viewer) {
                st.rows.insert(r.id, (u16::MAX, 0, 0, 0, 0, 0, 0));
            }
            st.seeded = true;
        }
        let mut live: HashSet<u64> = HashSet::new();
        let (mut ins, mut upd) = (0u64, 0u64);
        for ((lv, cx, cy), c) in &cells {
            let key = ((id as u64) << 32) | ((*lv as u64) << 30) | (((*cx as u16) as u64 & 0x7FFF) << 15) | ((*cy as u16) as u64 & 0x7FFF);
            live.insert(key);
            let (x, y) = (c.sx / c.n as f32, c.sy / c.n as f32);
            let spread = (c.pts.iter().map(|p| (p.0 - x).powi(2) + (p.1 - y).powi(2)).sum::<f32>() / c.n as f32).sqrt();
            let heading = ((c.hy.atan2(c.hx).rem_euclid(std::f32::consts::TAU) / std::f32::consts::TAU * 16.0).round() as u8) % 16;
            let q = |v: f32| (v / QUANT_M).round() as i32;
            let count = c.n.min(u16::MAX as u32) as u16;
            let fighting = c.fighting.min(u16::MAX as u32) as u16;
            let sig = (count, q(x), q(y), q(spread), heading, fighting, c.kinds);
            if st.rows.get(&key) == Some(&sig) {
                continue;
            }
            let row = SeenCrowd { id: key, viewer, cx: *cx, cy: *cy, count, x, y, spread, heading, moving: 0, fighting, fallen: 0, kinds: c.kinds };
            if st.rows.contains_key(&key) {
                rows.id().update(row);
                upd += 1;
            } else {
                rows.insert(row);
                ins += 1;
            }
            st.rows.insert(key, sig);
        }
        let gone: Vec<u64> = st.rows.keys().copied().filter(|k| !live.contains(k)).collect();
        for k in &gone {
            rows.id().delete(*k);
            st.rows.remove(k);
        }
        common::diag(|| "crowd:cells", cells.len() as u64);
        common::diag(|| "crowd:insert", ins);
        common::diag(|| "crowd:update", upd);
        common::diag(|| "crowd:delete", gone.len() as u64);
    });
}

/// Viewer `id` no longer attends (the law went off, or it left): its attended set and its crowd
/// rows go.
pub fn clear(ctx: &ReducerContext, id: u32, viewer: Identity) {
    ATT.with(|a| a.borrow_mut().remove(&id));
    clear_crowd(ctx, id, viewer);
}

/// Viewer `id`'s crowd rows go (the crowd law went off).
pub fn clear_crowd(ctx: &ReducerContext, id: u32, viewer: Identity) {
    let had = CROWD.with(|c| c.borrow_mut().remove(&id).is_some());
    if had {
        let rows = ctx.db.seen_crowd();
        for r in rows.viewer().filter(viewer).collect::<Vec<_>>() {
            rows.id().delete(r.id);
        }
    }
}

/// Whether viewer `id` holds any attention state (so the sweep clears it when the law goes off).
pub fn active(id: u32) -> bool {
    ATT.with(|a| a.borrow().contains_key(&id)) || CROWD.with(|c| c.borrow().contains_key(&id))
}

#[cfg(test)]
mod tests {
    use super::Vis;

    #[test]
    fn flip_backs_are_counted_within_2_and_5_seconds() {
        let mut v = Vis::default();
        let t = 1_700_000_000_000u64;
        v.roll(t + 1_000);
        // Creature 1: individual -> crowd at 1.0 s, back at 2.5 s (1.5 s: both windows), then
        // crowd again at 6.0 s (3.5 s: the 5 s window only).
        v.change(1, false, t + 1_000);
        v.change(1, true, t + 2_500);
        v.change(1, false, t + 6_000);
        // Creature 2: to crowd at 1.0 s, back at 7.5 s (6.5 s: neither).
        v.change(2, false, t + 1_000);
        v.change(2, true, t + 7_500);
        // Creature 3: leaves sight in between, so its return is not a flip-back.
        v.change(3, false, t + 1_000);
        v.gone(3);
        v.change(3, true, t + 1_500);
        v.attended.extend([1, 2, 3, 4]);
        assert_eq!((v.flips, v.back2, v.back5), (7, 1, 2));
        assert_eq!(v.affected.len(), 1);
        let rolled = v.roll(t + 12_000).unwrap();
        assert_eq!(rolled, ((t + 1_000) / 10_000, 7, 1, 2, 1, 4));
        assert_eq!((v.flips, v.back2, v.back5, v.affected.len(), v.attended.len()), (0, 0, 0, 0, 0));
        assert_eq!(v.roll(t + 15_000), None);
    }
}

/// `attend_throng_sight_ms`: the last sight result for `body`, when it was crowd at viewer `id`'s
/// last pass and was tested less than `ms` ago (else None: test it).
pub fn throng_cached(id: u32, body: u32, now: u64, ms: u64) -> Option<bool> {
    ATT.with(|a| {
        let a = a.borrow();
        let st = a.get(&id)?;
        if !st.crowd_prev.contains(&body) {
            return None;
        }
        st.throng.get(&body).filter(|(t, _)| now.saturating_sub(*t) < ms).map(|(_, r)| *r)
    })
}

/// `attend_throng_sight_ms`: `body` was just tested by viewer `id`'s sweep.
pub fn throng_tested(id: u32, body: u32, now: u64, saw: bool) {
    ATT.with(|a| {
        if let Some(st) = a.borrow_mut().get_mut(&id) {
            if st.crowd_prev.contains(&body) {
                st.throng.insert(body, (now, saw));
            }
        }
    })
}
