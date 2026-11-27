//! What a body controller observes and how it is encoded (docs/NEURAL_BODY.md §1, "Built (pilot
//! plumbing)").
//!
//! [`Observation`] is built only from the rows a player's client is delivered for its own character:
//! `my_body`, `my_fighter`, `my_vitals`, `my_readiness`, `seen_bodies`, `seen_characters`,
//! `seen_fighters`, `my_combat` and the public `skill_card`. The encoder reads nothing else, and
//! drops on purpose:
//! - creatures not in the delivered scene (`seen_bodies`): a fighter, a projection or a cue naming
//!   someone without a delivered body contributes no live features;
//! - other creatures' `vitals` or `own_fighter` rows: only `id == o.me` is read (defence in depth;
//!   `my_vitals` and `my_fighter` already deliver the character's own row only);
//! - other creatures' `release_ms` (a future time from the authority's schedule): only how long a
//!   visible move has been under way (`now - act_ms`) and what it is;
//! - raw identity: ids and names only match the delegated target, never enter the vector;
//! - feed rows addressed to another viewer (defence in depth; the view already filters them).
//!
//! Slots are bounded: the character itself, the target, [`OTHERS`] nearest others, [`CUES`] recent
//! cues and the brief's typed values, in a fixed-length vector ([`LEN`]).

use std::collections::HashMap;

/// Nearest others encoded beside the target.
pub const OTHERS: usize = 3;
/// Recent cues from the combat feed.
pub const CUES: usize = 4;
/// Skills in the delegated scope whose readiness and affordability are encoded.
pub const SKILLS: usize = 4;
/// A creature slot's features.
pub const SLOT: usize = 12;
/// The character's own features: hp, vx, vy, own_act, own_release_rem_s, busy_rem_s,
/// stamina_frac, stamina_rate_norm, focus_frac, guard_active, guard_elapsed_s,
/// skill_ready_rem_s[SKILLS], skill_usable[SKILLS].
pub const OWN: usize = 11 + 2 * SKILLS;
/// Names of the character's own features, recorded in capture layout records.
pub const OWN_FIELDS: [&str; OWN] = [
    "hp_frac",
    "vx",
    "vy",
    "own_act",
    "own_release_rem_s",
    "busy_rem_s",
    "stamina_frac",
    "stamina_rate_norm",
    "focus_frac",
    "guard_active",
    "guard_elapsed_s",
    "skill0_ready_s",
    "skill1_ready_s",
    "skill2_ready_s",
    "skill3_ready_s",
    "skill0_usable",
    "skill1_usable",
    "skill2_usable",
    "skill3_usable",
];
/// A cue's features.
pub const CUE: usize = 6;
/// The brief's features: goal (3), stance (3), risk, style, present, then its traits (the
/// character's individuality; `living_rules::body::MAX_TRAITS`, zero-padded).
pub const BRIEF: usize = 9 + living_rules::body::MAX_TRAITS;
/// The vector's length.
pub const LEN: usize = OWN + SLOT * (1 + OTHERS) + CUE * CUES + BRIEF;
/// Distances are told in units of this many metres.
const METRES: f32 = 10.0;
/// Reference stamina refill rate (points/s) for normalizing `stamina_rate`.
const STAMINA_RATE_REF: f32 = 25.0;

/// One creature's body as delivered (`Moving`).
#[derive(Clone, Debug, PartialEq, Default)]
pub struct BodyRow {
    pub id: u32,
    pub x: f32,
    pub y: f32,
    pub t_ms: u64,
    pub vx: f32,
    pub vy: f32,
    pub heading: f32,
}

/// What the character perceives of a creature (`SeenCharacter`): its kind, its life stage and its
/// health as the character can tell it (255: it cannot).
#[derive(Clone, Debug, PartialEq, Default)]
pub struct SeenRow {
    pub id: u32,
    pub kind: String,
    pub own: bool,
    pub band: u8,
    pub hp: f32,
    pub max_hp: f32,
}

/// A creature's visible fight move (`Fighter`). `release_ms` is carried as delivered and never
/// encoded for anyone but the character itself.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct FighterRow {
    pub id: u32,
    pub act: u8,
    pub act_ms: u64,
    pub release_ms: u64,
    pub until_ms: u64,
    pub target: u32,
}

/// A combat feed row (`CombatSeen`) addressed to `viewer`.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct CueRow {
    pub viewer: [u8; 32],
    pub at_ms: u64,
    pub kind: u8,
    pub actor: u32,
    pub target: u32,
    pub skill: u8,
    pub amount: f32,
}

/// A skill's card and its readiness for the character.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct SkillRow {
    pub skill: String,
    pub code: u8,
    pub reach: f32,
    /// When it is ready again (0: ready).
    pub ready_ms: u64,
    /// Pool cost (`skill_card.cost`).
    pub cost: f32,
    /// Pool spent (`skill_card.pool`: `"stamina"` or `"focus"`).
    pub pool: String,
    /// How the skill is aimed (`skill_card.aim`: `"facing"` for a held guard, `"dash"`, ...).
    pub aim: String,
}

/// The character's own vitals as delivered (`my_vitals`). Only the row with `id == o.me` is read.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct VitalsRow {
    pub id: u32,
    pub hp: f32,
    pub max_hp: f32,
    pub stamina: f32,
    pub stamina_max: f32,
    pub stamina_rate: f32,
    pub stamina_from_ms: u64,
    pub focus: f32,
    pub focus_max: f32,
    pub focus_rate: f32,
    pub focus_from_ms: u64,
    pub at_ms: u64,
}

impl VitalsRow {
    /// Projected stamina at `now_ms`, using the shared `living_rules::pools::level` formula.
    pub fn stamina_at(&self, now_ms: u64) -> f32 {
        living_rules::pools::level(self.stamina, self.stamina_rate, self.stamina_from_ms, self.at_ms, self.stamina_max, now_ms)
    }

    /// Projected focus at `now_ms`, using the shared `living_rules::pools::level` formula.
    pub fn focus_at(&self, now_ms: u64) -> f32 {
        living_rules::pools::level(self.focus, self.focus_rate, self.focus_from_ms, self.at_ms, self.focus_max, now_ms)
    }

    /// Effective stamina change rate (points/s) active at `now_ms`: negative while draining,
    /// positive once past the post-spend delay and below cap, zero while paused in delay or full/empty.
    pub fn effective_stamina_rate(&self, now_ms: u64) -> f32 {
        let cur = self.stamina_at(now_ms);
        if self.stamina_rate < 0.0 && cur > 0.0 {
            self.stamina_rate
        } else if self.stamina_rate > 0.0 && now_ms >= self.at_ms.max(self.stamina_from_ms) && cur < self.stamina_max {
            self.stamina_rate
        } else {
            0.0
        }
    }
}

/// The brief as the controller reads it: typed values only (no rationale).
#[derive(Clone, Debug, PartialEq, Default)]
pub struct BriefView {
    pub revision: u32,
    pub goal: String,
    pub target: u32,
    pub stance: String,
    pub risk: f32,
    pub style: f32,
    /// The individuality the role's shared net is conditioned on (at most `MAX_TRAITS`).
    pub traits: Vec<f32>,
    pub expires_ms: u64,
}

/// The delegated leaf as the controller reads it.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct SlotView {
    pub revision: u32,
    pub node: u16,
    pub goal: String,
    pub target: u32,
    pub skills: Vec<String>,
}

/// One decision's inputs, from the delivered rows only.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Observation {
    /// The authority time the newest delivered row speaks of (the decision's clock).
    pub now_ms: u64,
    pub me: u32,
    pub viewer: [u8; 32],
    pub body: Option<BodyRow>,
    pub own_fighter: Option<FighterRow>,
    /// Delivered `my_vitals` rows (only `id == me` is ever read).
    pub vitals: Vec<VitalsRow>,
    pub busy_until: u64,
    pub others: Vec<BodyRow>,
    pub seen: Vec<SeenRow>,
    pub fighters: Vec<FighterRow>,
    pub cues: Vec<CueRow>,
    pub skills: Vec<SkillRow>,
}

impl Observation {
    /// Where a delivered body is at `now` (its segment's start plus its velocity since).
    pub fn at(b: &BodyRow, now: u64) -> (f32, f32) {
        let dt = now.saturating_sub(b.t_ms) as f32 / 1000.0;
        (b.x + b.vx * dt, b.y + b.vy * dt)
    }

    /// The character's own place now.
    pub fn here(&self) -> Option<(f32, f32)> {
        self.body.as_ref().map(|b| Self::at(b, self.now_ms))
    }

    /// A delivered creature's body (only the scene: someone not delivered is not there).
    pub fn other(&self, id: u32) -> Option<&BodyRow> {
        self.others.iter().find(|b| b.id == id && id != self.me)
    }
}

fn one_hot(out: &mut Vec<f32>, words: &[&str], w: &str) {
    for x in words {
        out.push(if *x == w { 1.0 } else { 0.0 });
    }
}

/// A creature slot: present, where it is relative to me (units of 10 m), how it moves, whether it
/// faces me, its health as I can tell it, what visible move it is in and for how long, whether that
/// move is aimed at me, and how old its delivered row is.
fn creature(out: &mut Vec<f32>, o: &Observation, b: Option<&BodyRow>, seen: &HashMap<u32, &SeenRow>, fighters: &HashMap<u32, &FighterRow>) {
    let start = out.len();
    let (Some(b), Some(here)) = (b, o.here()) else {
        out.extend(std::iter::repeat_n(0.0, SLOT));
        return;
    };
    let at = Observation::at(b, o.now_ms);
    let (dx, dy) = (at.0 - here.0, at.1 - here.1);
    let dist = dx.hypot(dy).max(1e-3);
    out.push(1.0);
    out.push(dx / METRES);
    out.push(dy / METRES);
    out.push(dist / METRES);
    out.push(b.vx / METRES);
    out.push(b.vy / METRES);
    // Facing me: the cosine between its heading and the way to me.
    out.push((b.heading.cos() * -dx + b.heading.sin() * -dy) / dist);
    let health = seen.get(&b.id).filter(|s| s.band != 255 && s.max_hp > 0.0).map_or(-1.0, |s| (s.hp / s.max_hp).clamp(0.0, 1.0));
    out.push(health);
    let f = fighters.get(&b.id).filter(|f| f.act != 0 && f.until_ms > o.now_ms);
    out.push(f.map_or(0.0, |f| f.act as f32 / 16.0));
    // How long its visible move has been under way: never when it will be released.
    out.push(f.map_or(0.0, |f| o.now_ms.saturating_sub(f.act_ms) as f32 / 1000.0));
    out.push(f.map_or(0.0, |f| if f.target == o.me { 1.0 } else { 0.0 }));
    out.push((o.now_ms.saturating_sub(b.t_ms) as f32 / 1000.0).min(10.0));
    debug_assert_eq!(out.len() - start, SLOT);
}

/// The observation as the fixed-length vector a policy reads ([`LEN`] values, all finite).
pub fn encode(o: &Observation, brief: Option<&BriefView>, slot: &SlotView) -> Vec<f32> {
    let mut out = Vec::with_capacity(LEN);
    // Only creatures delivered in the scene, never the character itself among the others.
    let delivered: HashMap<u32, &BodyRow> = o.others.iter().filter(|b| b.id != o.me).map(|b| (b.id, b)).collect();
    let seen: HashMap<u32, &SeenRow> = o.seen.iter().filter(|s| delivered.contains_key(&s.id) || s.id == o.me).map(|s| (s.id, s)).collect();
    let fighters: HashMap<u32, &FighterRow> = o.fighters.iter().filter(|f| delivered.contains_key(&f.id)).map(|f| (f.id, f)).collect();
    // Own: health, motion, own move and windup release (0 for a held guard, which has no scheduled
    // release), recovery busy time, own vitals (`my_vitals`, filtered to `id == o.me`), guard hold
    // state & elapsed duration, and per-skill cooldown + readiness/affordability.
    let own_vitals = o.vitals.iter().find(|v| v.id == o.me);
    let own_seen = o.seen.iter().find(|s| s.id == o.me);
    let hp_frac = own_vitals
        .filter(|v| v.max_hp > 0.0)
        .map(|v| (v.hp / v.max_hp).clamp(0.0, 1.0))
        .or_else(|| own_seen.filter(|s| s.max_hp > 0.0).map(|s| (s.hp / s.max_hp).clamp(0.0, 1.0)))
        .unwrap_or(-1.0);
    out.push(hp_frac);
    out.push(o.body.as_ref().map_or(0.0, |b| b.vx / METRES));
    out.push(o.body.as_ref().map_or(0.0, |b| b.vy / METRES));
    let own = o.own_fighter.as_ref().filter(|f| f.id == o.me && f.act != 0 && f.until_ms > o.now_ms);
    let is_guard = own.is_some_and(|f| o.skills.iter().any(|k| k.code == f.act && k.aim == "facing"));
    out.push(own.map_or(0.0, |f| f.act as f32 / 16.0));
    out.push(if is_guard { 0.0 } else { own.map_or(0.0, |f| f.release_ms.saturating_sub(o.now_ms) as f32 / 1000.0) });
    out.push(o.busy_until.saturating_sub(o.now_ms) as f32 / 1000.0);
    let stamina_now = own_vitals.map(|v| v.stamina_at(o.now_ms));
    let focus_now = own_vitals.map(|v| v.focus_at(o.now_ms));
    out.push(own_vitals.filter(|v| v.stamina_max > 0.0).map_or(-1.0, |v| (stamina_now.unwrap_or(0.0) / v.stamina_max).clamp(0.0, 1.0)));
    out.push(own_vitals.map_or(0.0, |v| (v.effective_stamina_rate(o.now_ms) / STAMINA_RATE_REF).clamp(-1.0, 1.0)));
    out.push(own_vitals.filter(|v| v.focus_max > 0.0).map_or(-1.0, |v| (focus_now.unwrap_or(0.0) / v.focus_max).clamp(0.0, 1.0)));
    out.push(if is_guard { 1.0 } else { 0.0 });
    out.push(if is_guard { own.map_or(0.0, |f| (o.now_ms.saturating_sub(f.act_ms) as f32 / 1000.0).min(10.0)) } else { 0.0 });
    for i in 0..SKILLS {
        let k = slot.skills.get(i).and_then(|s| o.skills.iter().find(|r| &r.skill == s));
        out.push(k.map_or(-1.0, |k| k.ready_ms.saturating_sub(o.now_ms) as f32 / 1000.0));
    }
    for i in 0..SKILLS {
        let k = slot.skills.get(i).and_then(|s| o.skills.iter().find(|r| &r.skill == s));
        let usable = k.map_or(-1.0, |k| {
            let ready = k.ready_ms <= o.now_ms;
            let not_busy = o.busy_until <= o.now_ms || k.aim == "dash";
            let affordable = match (own_vitals, k.pool.as_str()) {
                (Some(_), "focus") => focus_now.unwrap_or(0.0) >= k.cost,
                (Some(_), _) => stamina_now.unwrap_or(0.0) >= k.cost,
                (None, _) => true,
            };
            if ready && not_busy && affordable { 1.0 } else { 0.0 }
        });
        out.push(usable);
    }
    // The target: the delegated leaf's, else the brief's.
    let target = if slot.target != 0 { slot.target } else { brief.map_or(0, |b| b.target) };
    creature(&mut out, o, delivered.get(&target).copied(), &seen, &fighters);
    // The nearest others (by distance now; ties by delivery order, never by id).
    let mut rest: Vec<&BodyRow> = o.others.iter().filter(|b| b.id != o.me && b.id != target).collect();
    if let Some(here) = o.here() {
        rest.sort_by(|a, b| {
            let (pa, pb) = (Observation::at(a, o.now_ms), Observation::at(b, o.now_ms));
            (pa.0 - here.0).hypot(pa.1 - here.1).total_cmp(&(pb.0 - here.0).hypot(pb.1 - here.1))
        });
    }
    for i in 0..OTHERS {
        creature(&mut out, o, rest.get(i).copied(), &seen, &fighters);
    }
    // Recent cues addressed to me: what kind, whether I was its actor or target, its skill, its size
    // and its age. A party not delivered is told only as "someone".
    let mut cues: Vec<&CueRow> = o.cues.iter().filter(|c| c.viewer == o.viewer && c.at_ms <= o.now_ms).collect();
    cues.sort_by_key(|c| std::cmp::Reverse(c.at_ms));
    for i in 0..CUES {
        match cues.get(i) {
            Some(c) => {
                out.push(1.0);
                out.push(c.kind as f32 / 16.0);
                out.push(if c.actor == o.me { 1.0 } else if c.target == o.me { -1.0 } else { 0.0 });
                out.push(c.skill as f32 / 16.0);
                out.push(c.amount.clamp(-100.0, 100.0) / 100.0);
                out.push((o.now_ms - c.at_ms) as f32 / 1000.0);
            }
            None => out.extend(std::iter::repeat_n(0.0, CUE)),
        }
    }
    // The brief's typed values (an expired brief is none).
    let b = brief.filter(|b| !b.goal.is_empty() && b.expires_ms > o.now_ms);
    one_hot(&mut out, living_rules::graph::DELEGATE_GOALS, b.map_or(slot.goal.as_str(), |b| b.goal.as_str()));
    one_hot(&mut out, living_rules::body::STANCES, b.map_or("", |b| b.stance.as_str()));
    out.push(b.map_or(0.5, |b| b.risk));
    out.push(b.map_or(0.5, |b| b.style));
    out.push(if b.is_some() { 1.0 } else { 0.0 });
    for i in 0..living_rules::body::MAX_TRAITS {
        out.push(b.and_then(|b| b.traits.get(i).copied()).unwrap_or(0.0).clamp(-1.0, 1.0));
    }
    debug_assert_eq!(out.len(), LEN);
    for v in out.iter_mut() {
        if !v.is_finite() {
            *v = 0.0;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    const ME: u32 = 7;
    const VIEWER: [u8; 32] = [1; 32];

    fn base() -> Observation {
        Observation {
            now_ms: 10_000,
            me: ME,
            viewer: VIEWER,
            body: Some(BodyRow { id: ME, x: 10.0, y: 10.0, t_ms: 9_900, ..Default::default() }),
            own_fighter: None,
            vitals: vec![VitalsRow {
                id: ME,
                hp: 80.0,
                max_hp: 100.0,
                stamina: 60.0,
                stamina_max: 100.0,
                stamina_rate: 25.0,
                stamina_from_ms: 9_600,
                focus: 90.0,
                focus_max: 100.0,
                focus_rate: 3.0,
                focus_from_ms: 9_800,
                at_ms: 9_600,
            }],
            busy_until: 0,
            others: vec![BodyRow { id: 21, x: 12.0, y: 10.0, t_ms: 9_950, heading: std::f32::consts::PI, ..Default::default() }, BodyRow { id: 30, x: 20.0, y: 4.0, t_ms: 9_900, ..Default::default() }],
            seen: vec![
                SeenRow { id: ME, kind: "person".into(), own: true, band: 0, hp: 80.0, max_hp: 100.0 },
                SeenRow { id: 21, kind: "person".into(), own: false, band: 1, hp: 60.0, max_hp: 100.0 },
                SeenRow { id: 30, kind: "person".into(), own: false, band: 255, hp: 0.0, max_hp: 0.0 },
            ],
            fighters: vec![FighterRow { id: 21, act: 3, act_ms: 9_700, release_ms: 10_450, until_ms: 11_000, target: ME }],
            cues: vec![CueRow { viewer: VIEWER, at_ms: 9_700, kind: 1, actor: 21, target: ME, skill: 3, amount: 0.0 }],
            skills: vec![
                SkillRow { skill: "strike".into(), code: 1, reach: 1.6, ready_ms: 0, cost: 20.0, pool: "stamina".into(), aim: "creature".into() },
                SkillRow { skill: "block".into(), code: 4, reach: 0.0, ready_ms: 0, cost: 5.0, pool: "stamina".into(), aim: "facing".into() },
            ],
        }
    }

    fn slot() -> SlotView {
        SlotView { revision: 3, node: 2, goal: "engage".into(), target: 21, skills: vec!["strike".into(), "block".into()] }
    }

    #[test]
    fn the_vector_has_its_fixed_length_and_finite_values() {
        let v = encode(&base(), None, &slot());
        assert_eq!(v.len(), LEN);
        assert!(v.iter().all(|x| x.is_finite()));
        // The target slot is present and holds the windup's elapsed time, aimed at me.
        let t = &v[OWN..OWN + SLOT];
        assert_eq!(t[0], 1.0);
        assert!((t[9] - 0.3).abs() < 1e-4, "elapsed {}", t[9]);
        assert_eq!(t[10], 1.0);
    }

    #[test]
    fn another_creatures_release_time_never_reaches_the_vector() {
        // The authority's schedule for someone else's blow: any future release reads the same.
        let a = encode(&base(), None, &slot());
        let mut o = base();
        o.fighters[0].release_ms = 99_999;
        assert_eq!(a, encode(&o, None, &slot()));
        o.fighters[0].release_ms = 10_001;
        assert_eq!(a, encode(&o, None, &slot()));
    }

    #[test]
    fn someone_not_delivered_in_the_scene_contributes_nothing() {
        // A hidden creature (#44): a fighter row, a projection and a cue naming it, but no delivered
        // body. The vector is the one without any of them.
        let a = encode(&base(), None, &slot());
        let mut o = base();
        o.fighters.push(FighterRow { id: 44, act: 3, act_ms: 9_900, release_ms: 10_200, until_ms: 12_000, target: ME });
        o.seen.push(SeenRow { id: 44, kind: "person".into(), own: false, band: 0, hp: 5.0, max_hp: 100.0 });
        assert_eq!(a, encode(&o, None, &slot()));
        // As the delegated target, a hidden creature is an empty slot, not a live one.
        let hidden = SlotView { target: 44, ..slot() };
        let v = encode(&o, None, &hidden);
        assert!(v[OWN..OWN + SLOT].iter().all(|x| *x == 0.0));
    }

    #[test]
    fn another_creatures_vitals_and_fighter_never_reach_the_vector() {
        // Another creature's vitals row (e.g. target #21 or hidden #44) and another creature's
        // fighter row in `own_fighter` never alter any feature of the encoded vector.
        let a = encode(&base(), None, &slot());
        let mut o = base();
        o.vitals.push(VitalsRow {
            id: 21,
            hp: 1.0,
            max_hp: 100.0,
            stamina: 0.0,
            stamina_max: 100.0,
            stamina_rate: -4.0,
            stamina_from_ms: 9_000,
            focus: 0.0,
            focus_max: 100.0,
            focus_rate: 0.0,
            focus_from_ms: 9_000,
            at_ms: 9_000,
        });
        o.vitals.push(VitalsRow { id: 44, hp: 50.0, max_hp: 50.0, stamina: 10.0, stamina_max: 100.0, at_ms: 9_900, ..Default::default() });
        o.own_fighter = Some(FighterRow { id: 21, act: 4, act_ms: 9_500, release_ms: 17_500, until_ms: 17_500, target: 0 });
        assert_eq!(a, encode(&o, None, &slot()));

        // Own vitals and own guard state DO reach the vector cleanly, and a held guard never
        // encodes `release_ms` (so graph `qty=800` and player `hold_ms=8000` encode identically).
        let mut g_short = base();
        g_short.vitals[0].stamina = 15.0;
        g_short.vitals[0].stamina_rate = -4.0;
        g_short.vitals[0].at_ms = 9_500;
        g_short.vitals[0].stamina_from_ms = 9_500;
        g_short.own_fighter = Some(FighterRow { id: ME, act: 4, act_ms: 9_500, release_ms: 10_300, until_ms: 10_300, target: 0 });
        let mut g_long = g_short.clone();
        g_long.own_fighter.as_mut().unwrap().release_ms = 17_500;
        g_long.own_fighter.as_mut().unwrap().until_ms = 17_500;
        let vs = encode(&g_short, None, &slot());
        let vl = encode(&g_long, None, &slot());
        assert_eq!(vs, vl, "held guard must not depend on release_ms ceiling");
        // Projected stamina: 15 - 4 * 0.5 = 13 -> 0.13; draining -> -4/25 = -0.16; guard active=1, elapsed=0.5s.
        assert!((vs[6] - 0.13).abs() < 1e-4, "stamina_frac {}", vs[6]);
        assert!((vs[7] - (-4.0 / 25.0)).abs() < 1e-4, "stamina_rate_norm {}", vs[7]);
        assert_eq!(vs[4], 0.0, "held guard release_rem must be 0");
        assert_eq!(vs[9], 1.0, "guard_active");
        assert!((vs[10] - 0.5).abs() < 1e-4, "guard_elapsed_s {}", vs[10]);
        // At 13 stamina: strike (cost 20) is NOT usable (0.0), block (cost 5) IS usable (1.0).
        assert_eq!(vs[15], 0.0, "strike unusable at 13 stamina");
        assert_eq!(vs[16], 1.0, "block usable at 13 stamina");
    }

    #[test]
    fn rows_for_another_viewer_are_dropped() {
        // Another character's feed row (another viewer's identity) changes nothing.
        let a = encode(&base(), None, &slot());
        let mut o = base();
        o.cues.push(CueRow { viewer: [9; 32], at_ms: 9_990, kind: 2, actor: 30, target: 21, skill: 1, amount: 12.0 });
        assert_eq!(a, encode(&o, None, &slot()));
    }

    #[test]
    fn identities_are_not_features() {
        // Renaming every other creature consistently (ids) changes nothing.
        let a = encode(&base(), None, &slot());
        let mut o = base();
        let map = |id: u32| match id {
            21 => 1021,
            30 => 1030,
            x => x,
        };
        for b in o.others.iter_mut() {
            b.id = map(b.id);
        }
        for s in o.seen.iter_mut() {
            s.id = map(s.id);
        }
        for f in o.fighters.iter_mut() {
            f.id = map(f.id);
        }
        for c in o.cues.iter_mut() {
            c.actor = map(c.actor);
        }
        assert_eq!(a, encode(&o, None, &SlotView { target: 1021, ..slot() }));
    }

    #[test]
    fn the_brief_conditions_by_typed_values_and_an_expired_one_is_none() {
        let b = BriefView { revision: 2, goal: "withdraw".into(), target: 0, stance: "guarded".into(), risk: 0.2, style: 0.9, traits: vec![0.5, -1.0], expires_ms: 20_000 };
        let with = encode(&base(), Some(&b), &slot());
        let tail = &with[LEN - BRIEF..];
        assert_eq!(tail, &[0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.2, 0.9, 1.0, 0.5, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]);
        let expired = BriefView { expires_ms: 9_000, ..b };
        assert_eq!(encode(&base(), Some(&expired), &slot()), encode(&base(), None, &slot()));
    }
}
