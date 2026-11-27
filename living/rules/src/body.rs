//! The body brief (docs/NEURAL_BODY.md §2, "Built (pilot plumbing)"): what a mind asks of its
//! character's body controller while a delegated graph leaf runs. Typed values only: a goal, an
//! optional target, a stance and two scalars, with a bounded lifetime. A brief authorizes no new
//! action and binds no skill timing or reaction to a cue: the controller acts only through the
//! player input path, within the active leaf's skill scope. The mind's own rationale is kept as
//! text for its next deliberation; the controller never receives it.
//!
//! Individuality travels here, not in per-character weights (docs/NEURAL_BODY.md, "Design input:
//! one body net per role"): `traits`, a short vector of the mind's own conditioning values, is the
//! character's identity as the shared net of its role reads it.
//!
//! Shared by the authority (`mind_body_brief`'s checks) and the mind service (the body worker reads
//! the accepted values back as typed fields).

use crate::graph::DELEGATE_GOALS;

/// The stances a brief may name: how much to give to defending against pressing. Mechanics words.
pub const STANCES: &[&str] = &["guarded", "even", "pressing"];
/// A brief's rationale (the mind's own words, for its next deliberation) is at most this long.
pub const MAX_RATIONALE: usize = 400;
/// A brief lives at least this long (seconds).
pub const MIN_TTL_S: f32 = 1.0;
/// At most this many trait values in a brief, each in -1 ..= 1.
pub const MAX_TRAITS: usize = 8;

/// A brief as a mind writes it (the authority's `BodyBriefIn` carries the same fields).
#[derive(Clone, Debug, PartialEq)]
pub struct Brief<'a> {
    pub goal: &'a str,
    /// 0: none.
    pub target: u32,
    pub stance: &'a str,
    /// How much harm the body may take to pursue the goal, 0 (none) ..= 1.
    pub risk: f32,
    /// How the body goes about it, 0 (measured) ..= 1 (quick).
    pub style: f32,
    /// How long it holds (seconds), `MIN_TTL_S ..= max_ttl_s` (the `body_brief_max_s` law).
    pub ttl_s: f32,
    pub rationale: &'a str,
    /// The character's individuality as its role's shared net reads it: at most [`MAX_TRAITS`]
    /// values, each -1 ..= 1 (what each means is the mind's and the net's convention, never a
    /// cue or a reaction).
    pub traits: &'a [f32],
}

/// The schema and value checks of a brief, before anything about the world (who the caller is,
/// whether the target is perceived): the first failing check, in the words the mind is told.
pub fn check(b: &Brief, max_ttl_s: f32) -> Result<(), String> {
    if !DELEGATE_GOALS.contains(&b.goal) {
        return Err(format!("a brief's goal is one of {}, not {:?}", DELEGATE_GOALS.join(", "), b.goal));
    }
    if !STANCES.contains(&b.stance) {
        return Err(format!("a brief's stance is one of {}, not {:?}", STANCES.join(", "), b.stance));
    }
    for (name, v) in [("risk", b.risk), ("style", b.style)] {
        if !v.is_finite() || !(0.0..=1.0).contains(&v) {
            return Err(format!("a brief's {name} is a number from 0 to 1"));
        }
    }
    let max = max_ttl_s.max(MIN_TTL_S);
    if !b.ttl_s.is_finite() || !(MIN_TTL_S..=max).contains(&b.ttl_s) {
        return Err(format!("a brief lasts from {MIN_TTL_S} to {max} seconds"));
    }
    if b.traits.len() > MAX_TRAITS {
        return Err(format!("a brief has at most {MAX_TRAITS} traits"));
    }
    if b.traits.iter().any(|t| !t.is_finite() || !(-1.0..=1.0).contains(t)) {
        return Err("a brief's traits are numbers from -1 to 1".into());
    }
    if b.rationale.len() > MAX_RATIONALE {
        return Err(format!("a brief's rationale is at most {MAX_RATIONALE} bytes"));
    }
    Ok(())
}

/// The words a brief's target gets when the character does not perceive it now, whether or not
/// it exists (the same refusal for unseen and nonexistent targets).
pub fn unseen_target(id: u32) -> String {
    format!("#{id} is not someone you perceive now")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ok() -> Brief<'static> {
        Brief { goal: "engage", target: 0, stance: "even", risk: 0.5, style: 0.5, ttl_s: 30.0, rationale: "", traits: &[0.2, -0.4] }
    }

    #[test]
    fn a_brief_takes_known_words_and_bounded_finite_values() {
        assert!(check(&ok(), 300.0).is_ok());
        assert!(check(&Brief { goal: "dance", ..ok() }, 300.0).unwrap_err().contains("goal"));
        assert!(check(&Brief { stance: "berserk", ..ok() }, 300.0).unwrap_err().contains("stance"));
        assert!(check(&Brief { risk: f32::NAN, ..ok() }, 300.0).unwrap_err().contains("risk"));
        assert!(check(&Brief { style: 1.5, ..ok() }, 300.0).unwrap_err().contains("style"));
        assert!(check(&Brief { ttl_s: f32::INFINITY, ..ok() }, 300.0).unwrap_err().contains("seconds"));
        assert!(check(&Brief { ttl_s: 301.0, ..ok() }, 300.0).unwrap_err().contains("300"));
        assert!(check(&Brief { ttl_s: 0.5, ..ok() }, 300.0).is_err());
        assert!(check(&Brief { traits: &[0.0; 9], ..ok() }, 300.0).unwrap_err().contains("at most 8 traits"));
        assert!(check(&Brief { traits: &[1.5], ..ok() }, 300.0).unwrap_err().contains("traits"));
        assert!(check(&Brief { traits: &[f32::NAN], ..ok() }, 300.0).unwrap_err().contains("traits"));
        let long = "x".repeat(MAX_RATIONALE + 1);
        assert!(check(&Brief { rationale: &long, ..ok() }, 300.0).unwrap_err().contains("rationale"));
    }

    #[test]
    fn unseen_and_nonexistent_targets_read_the_same() {
        // The words carry the id given and nothing about whether it exists.
        assert_eq!(unseen_target(7), "#7 is not someone you perceive now");
    }
}
