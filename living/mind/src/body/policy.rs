//! Body controller policies (docs/NEURAL_BODY.md, "Built (pilot plumbing)"). A policy maps one
//! decision's observation (and its encoded vector) to player intents: a direction or a stop, a
//! look, a skill press within the delegated scope, a release. It is pluggable: the pilot ships a
//! scripted placeholder, [`HoldDistance`], and no trained net. A policy holds no state shared
//! between characters.

use super::encode::{BriefView, Observation, SlotView};

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

pub trait Policy: Send {
    fn name(&self) -> &str;
    /// One decision. `encoded` is `encode::encode`'s vector for the same inputs.
    fn decide(&mut self, o: &Observation, encoded: &[f32], brief: Option<&BriefView>, slot: &SlotView) -> Intent;
}

/// The placeholder: hold a distance from the target, closing or backing off at a walk, and, under an
/// engage goal, press the first skill in scope that is ready while the target is within its reach.
/// It reads only the observation; it knows nothing of anyone's schedule.
pub struct HoldDistance {
    /// The distance to hold (m); `None`: by the goal (engage: the first skill's reach less a margin;
    /// hold: 3 m; withdraw: 10 m).
    pub distance: Option<f32>,
    /// Within this of the distance it stands.
    pub band: f32,
    /// At least this long between presses (ms).
    pub press_gap_ms: u64,
    last_press: u64,
}

impl HoldDistance {
    pub fn new(distance: Option<f32>) -> Self {
        Self { distance, band: 0.4, press_gap_ms: 400, last_press: 0 }
    }
}

impl Policy for HoldDistance {
    fn name(&self) -> &str {
        "hold-distance"
    }

    fn decide(&mut self, o: &Observation, _encoded: &[f32], brief: Option<&BriefView>, slot: &SlotView) -> Intent {
        let mut out = Intent::default();
        let Some(here) = o.here() else { return out };
        let goal = brief.filter(|b| !b.goal.is_empty() && b.expires_ms > o.now_ms).map_or(slot.goal.as_str(), |b| b.goal.as_str());
        let target = if slot.target != 0 { slot.target } else { brief.map_or(0, |b| b.target) };
        let Some(t) = o.other(target) else {
            // No target in sight: stand.
            out.moving = Some((0.0, 0.0, false));
            return out;
        };
        let at = Observation::at(t, o.now_ms);
        let (dx, dy) = (at.0 - here.0, at.1 - here.1);
        let dist = dx.hypot(dy);
        let first = slot.skills.iter().find_map(|s| o.skills.iter().find(|k| &k.skill == s));
        let want = self.distance.unwrap_or(match goal {
            "engage" => first.map_or(1.5, |k| (k.reach - 0.3).max(0.8)),
            "withdraw" => 10.0,
            _ => 3.0,
        });
        out.moving = Some(if dist > want + self.band {
            (dx, dy, false)
        } else if dist < want - self.band {
            (-dx, -dy, false)
        } else {
            (0.0, 0.0, false)
        });
        if dist > 1e-3 {
            out.face = Some((dx, dy));
        }
        if goal == "engage" && o.now_ms.saturating_sub(self.last_press) >= self.press_gap_ms && o.busy_until <= o.now_ms {
            if let Some(k) = slot.skills.iter().filter_map(|s| o.skills.iter().find(|k| &k.skill == s)).find(|k| k.ready_ms <= o.now_ms && k.reach > 0.0 && dist <= k.reach) {
                self.last_press = o.now_ms;
                out.press = Some((k.skill.clone(), t.id, at.0, at.1));
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::super::encode::*;
    use super::*;

    fn obs(dist: f32) -> Observation {
        Observation {
            now_ms: 5_000,
            me: 1,
            body: Some(BodyRow { id: 1, x: 0.0, y: 0.0, t_ms: 5_000, ..Default::default() }),
            others: vec![BodyRow { id: 2, x: dist, y: 0.0, t_ms: 5_000, ..Default::default() }],
            skills: vec![SkillRow { skill: "strike".into(), code: 1, reach: 1.6, ready_ms: 0 }],
            ..Default::default()
        }
    }

    fn slot() -> SlotView {
        SlotView { revision: 1, node: 1, goal: "engage".into(), target: 2, skills: vec!["strike".into()] }
    }

    #[test]
    fn it_closes_holds_and_backs_off_around_its_distance() {
        let mut p = HoldDistance::new(Some(3.0));
        assert!(p.decide(&obs(8.0), &[], None, &slot()).moving.unwrap().0 > 0.0);
        assert_eq!(p.decide(&obs(3.0), &[], None, &slot()).moving.unwrap(), (0.0, 0.0, false));
        assert!(p.decide(&obs(1.0), &[], None, &slot()).moving.unwrap().0 < 0.0);
    }

    #[test]
    fn it_presses_only_skills_in_scope_within_reach() {
        let mut p = HoldDistance::new(None);
        let i = p.decide(&obs(1.2), &[], None, &slot());
        assert_eq!(i.press.as_ref().map(|p| p.0.as_str()), Some("strike"));
        // Out of reach, or a skill outside the scope: no press.
        let mut p = HoldDistance::new(None);
        assert!(p.decide(&obs(4.0), &[], None, &slot()).press.is_none());
        let mut p = HoldDistance::new(None);
        assert!(p.decide(&obs(1.2), &[], None, &SlotView { skills: vec![], ..slot() }).press.is_none());
    }

    #[test]
    fn with_no_target_in_sight_it_stands() {
        let mut p = HoldDistance::new(None);
        let mut o = obs(2.0);
        o.others.clear();
        assert_eq!(p.decide(&o, &[], None, &slot()), Intent { moving: Some((0.0, 0.0, false)), ..Default::default() });
    }
}
