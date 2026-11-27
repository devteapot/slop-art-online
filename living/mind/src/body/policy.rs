//! Body controller policies (docs/NEURAL_BODY.md, "Built (pilot plumbing)").
//!
//! - **One policy per role, shared.** A policy serves every delegated character of its role (its
//!   kind: people, wolves); no character has weights of its own. Its individuality comes in the
//!   brief's typed values and `traits` (the encoded vector), never in the policy.
//! - **Memory per character.** The worker carries a small [`Memory`] for each character between
//!   decisions: a fixed recurrent state the policy may write ([`STATE`] values) and the last
//!   [`HISTORY`] intents it sent, encoded. It is reset on a new controller epoch and on a new
//!   brief revision, so nothing carries across a stall or a changed instruction. A feedforward net
//!   forgets a target that leaves its local view; this is where a small recurrent net keeps it.
//! - The pilot ships a scripted placeholder, [`HoldDistance`], not a trained net.
//!
//! A policy decides from one character's observation and memory alone: no state is shared
//! between characters, and nothing of one reaches another's decision.

use super::encode::{BriefView, Observation, SlotView};
use std::collections::VecDeque;

/// The recurrent state's size.
pub const STATE: usize = 16;
/// Intents kept in the history.
pub const HISTORY: usize = 4;
/// An encoded intent: moving (0/1), direction x, y (unit), run, pressed (0/1), the pressed skill's
/// place in the delegated scope (0..1), released (0/1), looked (0/1).
pub const INTENT: usize = 8;
/// A memory flattened: the state, then the history (newest first, zero-padded).
pub const MEMORY: usize = STATE + HISTORY * INTENT;

/// What a decision sends through the player input reducers. `None`: nothing new.
#[derive(Clone, Debug, PartialEq, Default, serde::Serialize)]
pub struct Intent {
    /// `human_move(dx, dy, run)`; `Some((0, 0, false))` stops.
    pub moving: Option<(f32, f32, bool)>,
    /// `human_face(dx, dy)`.
    pub face: Option<(f32, f32)>,
    /// `use_skill(skill, target, x, y)`.
    pub press: Option<(String, u32, f32, f32)>,
    /// `release_skill(skill)`.
    pub release: Option<String>,
}

impl Intent {
    /// The intent as [`INTENT`] numbers (no ids: the target is the slot's own).
    pub fn encode(&self, slot: &SlotView) -> [f32; INTENT] {
        let mut v = [0.0; INTENT];
        if let Some((x, y, run)) = self.moving {
            let n = x.hypot(y);
            if n > 1e-3 {
                v[0] = 1.0;
                v[1] = x / n;
                v[2] = y / n;
            }
            v[3] = if run { 1.0 } else { 0.0 };
        }
        if let Some((skill, ..)) = &self.press {
            v[4] = 1.0;
            let at = slot.skills.iter().position(|s| s == skill).unwrap_or(0);
            v[5] = (at + 1) as f32 / living_rules::graph::MAX_DELEGATE_SKILLS as f32;
        }
        v[6] = if self.release.is_some() { 1.0 } else { 0.0 };
        v[7] = if self.face.is_some() { 1.0 } else { 0.0 };
        v
    }
}

/// One character's memory between decisions.
#[derive(Clone, Debug, PartialEq)]
pub struct Memory {
    pub state: [f32; STATE],
    /// Newest first.
    pub history: VecDeque<[f32; INTENT]>,
    /// What it was last reset for: the controller epoch and the brief revision (0: none).
    pub epoch: u32,
    pub brief: u32,
    /// The observation clock at the first decision since the reset (ms; 0: none yet): times in the
    /// state are seconds since it, small enough for an f32 to hold exactly.
    pub t0_ms: u64,
}

impl Memory {
    pub fn new(epoch: u32, brief: u32) -> Self {
        Self { state: [0.0; STATE], history: VecDeque::with_capacity(HISTORY), epoch, brief, t0_ms: 0 }
    }

    /// A new epoch or a new brief revision starts it afresh; returns whether it was reset.
    pub fn follow(&mut self, epoch: u32, brief: u32) -> bool {
        if self.epoch != epoch || self.brief != brief {
            *self = Memory::new(epoch, brief);
            return true;
        }
        false
    }

    /// The intent just sent joins the history (the oldest goes).
    pub fn remember(&mut self, intent: [f32; INTENT]) {
        self.history.push_front(intent);
        self.history.truncate(HISTORY);
    }

    /// The memory as [`MEMORY`] numbers, as a recurrent net reads it and the capture keeps it.
    pub fn flat(&self) -> Vec<f32> {
        let mut out = Vec::with_capacity(MEMORY);
        out.extend_from_slice(&self.state);
        for i in 0..HISTORY {
            out.extend_from_slice(&self.history.get(i).copied().unwrap_or([0.0; INTENT]));
        }
        out
    }
}

pub trait Policy: Send {
    fn name(&self) -> &str;
    /// The policy's version (a net's weights hash; the placeholder's own number): captured with
    /// every decision.
    fn version(&self) -> String;
    /// One decision for one character: its observation, `encoded` (`encode::encode` of the same
    /// inputs) and its own memory, which the policy may update. Shared by every character of a role.
    fn decide(&self, o: &Observation, encoded: &[f32], memory: &mut Memory, brief: Option<&BriefView>, slot: &SlotView) -> Intent;
}

/// The policy serving `role` (a character's kind). When `LIVING_BODY_WEIGHTS` points to a trained
/// `RoleNet` file (or `LIVING_BODY_WEIGHTS_RANDOM=1` for Step 1 throughput testing), the `"person"`
/// role uses that one shared `RoleNet`; otherwise it falls back to the scripted `HoldDistance`.
pub fn for_role(role: &str, distance: Option<f32>) -> Box<dyn Policy> {
    if role == "person" {
        if let Ok(path) = std::env::var("LIVING_BODY_WEIGHTS") {
            let trimmed = path.trim();
            if !trimmed.is_empty() {
                match super::net::RoleNet::load(std::path::Path::new(trimmed)) {
                    Ok(net) => return Box::new(net),
                    Err(e) => {
                        log::error!("body worker: failed to load LIVING_BODY_WEIGHTS={trimmed}: {e:#}");
                        std::process::exit(3);
                    }
                }
            }
        }
        if std::env::var("LIVING_BODY_WEIGHTS_RANDOM").ok().as_deref() == Some("1") {
            let w = super::net::RoleNetWeights::seeded_init("person", 20261127);
            return Box::new(super::net::RoleNet::new(w).expect("seeded RoleNet"));
        }
    }
    Box::new(HoldDistance::new(distance))
}

/// The placeholder: hold a distance from the target, closing or backing off at a walk, and, under an
/// engage goal, press the first skill in scope that is ready while the target is within its reach.
/// Its memory: where it last saw its target (state 0..3: x, y, when, seen) and when it last pressed
/// (state 4), so a target that leaves sight is sought where it was for a few seconds.
pub struct HoldDistance {
    /// The distance to hold (m); `None`: by the goal (engage: the first skill's reach less a margin;
    /// hold: 3 m; withdraw: 10 m).
    pub distance: Option<f32>,
    /// Within this of the distance it stands.
    pub band: f32,
    /// At least this long between presses (ms).
    pub press_gap_ms: u64,
    /// How long a target out of sight is sought where it was last seen (ms).
    pub seek_ms: u64,
}

impl HoldDistance {
    pub fn new(distance: Option<f32>) -> Self {
        Self { distance, band: 0.4, press_gap_ms: 400, seek_ms: 4_000 }
    }
}

/// Seconds since the memory's clock base (`Memory::t0_ms`).
fn secs(ms: u64, base: u64) -> f32 {
    ms.saturating_sub(base) as f32 / 1000.0
}

impl Policy for HoldDistance {
    fn name(&self) -> &str {
        "hold-distance"
    }

    fn version(&self) -> String {
        "hold-distance-1".into()
    }

    fn decide(&self, o: &Observation, _encoded: &[f32], m: &mut Memory, brief: Option<&BriefView>, slot: &SlotView) -> Intent {
        let mut out = Intent::default();
        let Some(here) = o.here() else { return out };
        // The memory's clock: the decision's own, relative to the first decision since its reset.
        if m.t0_ms == 0 {
            m.t0_ms = o.now_ms;
        }
        let now = secs(o.now_ms, m.t0_ms);
        let goal = brief.filter(|b| !b.goal.is_empty() && b.expires_ms > o.now_ms).map_or(slot.goal.as_str(), |b| b.goal.as_str());
        let target = if slot.target != 0 { slot.target } else { brief.map_or(0, |b| b.target) };
        let first = slot.skills.iter().find_map(|s| o.skills.iter().find(|k| &k.skill == s));
        let want = self.distance.unwrap_or(match goal {
            "engage" => first.map_or(1.5, |k| (k.reach - 0.3).max(0.8)),
            "withdraw" => 10.0,
            _ => 3.0,
        });
        let seen = o.other(target).map(|t| (t.id, Observation::at(t, o.now_ms)));
        let at = match seen {
            Some((_, at)) => {
                m.state[0] = at.0;
                m.state[1] = at.1;
                m.state[2] = now;
                m.state[3] = 1.0;
                at
            }
            // Out of sight: where it was last seen, for a while.
            None if m.state[3] > 0.0 && (now - m.state[2]) * 1000.0 <= self.seek_ms as f32 => (m.state[0], m.state[1]),
            None => {
                m.state[3] = 0.0;
                out.moving = Some((0.0, 0.0, false));
                return out;
            }
        };
        let (dx, dy) = (at.0 - here.0, at.1 - here.1);
        let dist = dx.hypot(dy);
        let seeking = seen.is_none();
        out.moving = Some(if dist > want + self.band || (seeking && dist > self.band) {
            (dx, dy, false)
        } else if dist < want - self.band && !seeking {
            (-dx, -dy, false)
        } else {
            (0.0, 0.0, false)
        });
        if dist > 1e-3 {
            out.face = Some((dx, dy));
        }
        let last_press = m.state[4];
        if let Some((id, _)) = seen.filter(|_| goal == "engage" && (m.state[5] == 0.0 || (now - last_press) * 1000.0 >= self.press_gap_ms as f32) && o.busy_until <= o.now_ms) {
            if let Some(k) = slot.skills.iter().filter_map(|s| o.skills.iter().find(|k| &k.skill == s)).find(|k| k.ready_ms <= o.now_ms && k.reach > 0.0 && dist <= k.reach) {
                m.state[4] = now;
                m.state[5] = 1.0;
                out.press = Some((k.skill.clone(), id, at.0, at.1));
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::super::encode::*;
    use super::*;

    fn obs(dist: f32, now: u64) -> Observation {
        Observation {
            now_ms: now,
            me: 1,
            body: Some(BodyRow { id: 1, x: 0.0, y: 0.0, t_ms: now, ..Default::default() }),
            others: vec![BodyRow { id: 2, x: dist, y: 0.0, t_ms: now, ..Default::default() }],
            skills: vec![SkillRow { skill: "strike".into(), code: 1, reach: 1.6, ready_ms: 0 }],
            ..Default::default()
        }
    }

    fn slot() -> SlotView {
        SlotView { revision: 1, node: 1, goal: "engage".into(), target: 2, skills: vec!["strike".into()] }
    }

    #[test]
    fn it_closes_holds_and_backs_off_around_its_distance() {
        let p = HoldDistance::new(Some(3.0));
        let mut m = Memory::new(1, 0);
        assert!(p.decide(&obs(8.0, 5_000), &[], &mut m, None, &slot()).moving.unwrap().0 > 0.0);
        assert_eq!(p.decide(&obs(3.0, 5_100), &[], &mut m, None, &slot()).moving.unwrap(), (0.0, 0.0, false));
        assert!(p.decide(&obs(1.0, 5_200), &[], &mut m, None, &slot()).moving.unwrap().0 < 0.0);
    }

    #[test]
    fn it_presses_only_skills_in_scope_within_reach_and_not_too_often() {
        let p = HoldDistance::new(None);
        let mut m = Memory::new(1, 0);
        assert_eq!(p.decide(&obs(1.2, 5_000), &[], &mut m, None, &slot()).press.as_ref().map(|p| p.0.as_str()), Some("strike"));
        // The memory holds the press: not again within its gap, again after it.
        assert!(p.decide(&obs(1.2, 5_100), &[], &mut m, None, &slot()).press.is_none());
        assert!(p.decide(&obs(1.2, 5_500), &[], &mut m, None, &slot()).press.is_some());
        let mut fresh = Memory::new(1, 0);
        assert!(p.decide(&obs(4.0, 5_000), &[], &mut fresh, None, &slot()).press.is_none());
        let mut fresh = Memory::new(1, 0);
        assert!(p.decide(&obs(1.2, 5_000), &[], &mut fresh, None, &SlotView { skills: vec![], ..slot() }).press.is_none());
    }

    #[test]
    fn a_target_out_of_sight_is_sought_where_it_was_then_given_up() {
        let p = HoldDistance::new(None);
        let mut m = Memory::new(1, 0);
        p.decide(&obs(6.0, 5_000), &[], &mut m, None, &slot());
        let mut gone = obs(6.0, 6_000);
        gone.others.clear();
        // Remembered: it walks to where the target was, and presses nothing (it sees no one).
        let i = p.decide(&gone, &[], &mut m, None, &slot());
        assert!(i.moving.unwrap().0 > 0.0 && i.press.is_none(), "{i:?}");
        // Past the seek time: it stands. Without memory (a fresh one): it stands at once.
        gone.now_ms = 10_500;
        assert_eq!(p.decide(&gone, &[], &mut m, None, &slot()).moving, Some((0.0, 0.0, false)));
        let mut fresh = Memory::new(1, 0);
        gone.now_ms = 6_000;
        assert_eq!(p.decide(&gone, &[], &mut fresh, None, &slot()).moving, Some((0.0, 0.0, false)));
    }

    #[test]
    fn the_memory_clock_holds_at_the_real_clock_s_size() {
        // Milliseconds since 1970 (about 1.8e12): the press gap still counts in milliseconds.
        let p = HoldDistance::new(None);
        let mut m = Memory::new(1, 0);
        let t = 1_795_735_000_123;
        assert!(p.decide(&obs(1.2, t), &[], &mut m, None, &slot()).press.is_some());
        assert!(p.decide(&obs(1.2, t + 100), &[], &mut m, None, &slot()).press.is_none());
        assert!(p.decide(&obs(1.2, t + 450), &[], &mut m, None, &slot()).press.is_some());
    }

    #[test]
    fn memory_resets_on_a_new_epoch_or_brief_and_flattens_to_its_size() {
        let mut m = Memory::new(3, 1);
        m.state[0] = 2.0;
        m.remember(Intent { moving: Some((1.0, 0.0, true)), ..Default::default() }.encode(&slot()));
        assert_eq!(m.flat().len(), MEMORY);
        assert!(!m.follow(3, 1) && m.state[0] == 2.0 && m.history.len() == 1);
        assert!(m.follow(4, 1) && m.state[0] == 0.0 && m.history.is_empty());
        m.state[0] = 2.0;
        assert!(m.follow(4, 2) && m.state[0] == 0.0);
        for _ in 0..10 {
            m.remember([1.0; INTENT]);
        }
        assert_eq!(m.history.len(), HISTORY);
    }
}
