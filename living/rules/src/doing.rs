//! What anyone looking sees someone doing, and how far into it (docs/PERCEPTION.md, "What
//! someone is visibly doing"). The authority reads it from the rows a player's client draws
//! from (`fighter` for a combat move, `doing` for a skill with an act card), so a mind's scene
//! and a graph's `doing` condition get the same fact a player gets from the animation, and no
//! more: no timing beyond what the drawn motion shows, no intent.
//!
//! How the phases map to the drawing. The client plays a move's clip so that its peak (the
//! blow, the loosing) lands at the rules' release (`living/game/src/combat.rs`, `timing`): the
//! windup is the clip's run-up, its second half the last approach to the peak; the peak to the
//! clip's settle is about a tenth to a fifth of a second; the recovery plays on until the
//! row's end. A held guard is one held pose. A gesture, work, a meal or a rest (an act card) is
//! one pose or one gesture for as long as its row stands. So:
//!
//! | phase | from the row | what the animation shows |
//! |---|---|---|
//! | `winding up` | the first half of the windup | the run-up begins |
//! | `about to release` | the second half of the windup | the swing or draw nearing its peak |
//! | `releasing` | the release, for [`RELEASING_MS`] | the peak: the blow lands, the shot leaves |
//! | `recovering` | after that, until the row's end | the follow-through settling |
//! | `holding` | a held guard (a `facing` skill), all of it | the guard held up |
//! | `under way` | an act card's row (a wave, work, eating, resting) | its pose or gesture |
//!
//! `winding up` in a condition matches the whole windup (both halves); the scene names the
//! half it is in.

use crate::combat::{Aim, Shape};
use crate::social::Show;

/// The part of the windup from which a move reads as about to release (a fraction of it).
pub const LATE_WINDUP: f32 = 0.5;
/// How long the release itself is seen (ms): the clip's peak to its settle at the rates it is
/// played at (0.17 clip seconds for a slash, at 1–2× speed).
pub const RELEASING_MS: u64 = 150;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    WindingUp,
    AboutToRelease,
    Releasing,
    Recovering,
    Holding,
    UnderWay,
}

impl Phase {
    pub const ALL: [Phase; 6] = [Phase::WindingUp, Phase::AboutToRelease, Phase::Releasing, Phase::Recovering, Phase::Holding, Phase::UnderWay];

    pub fn word(self) -> &'static str {
        match self {
            Phase::WindingUp => "winding up",
            Phase::AboutToRelease => "about to release",
            Phase::Releasing => "releasing",
            Phase::Recovering => "recovering",
            Phase::Holding => "holding",
            Phase::UnderWay => "under way",
        }
    }

    /// A phase as written in a graph: its word, with spaces or underscores.
    pub fn parse(s: &str) -> Option<Phase> {
        let s = squash(s);
        Phase::ALL.into_iter().find(|p| squash(p.word()) == s)
    }

    /// Whether what is seen (`self`) fits a phase a condition asks for: `winding up` covers the
    /// whole windup.
    pub fn fits(self, want: Phase) -> bool {
        self == want || (want == Phase::WindingUp && self == Phase::AboutToRelease)
    }
}

/// The phase of a combat move as its `fighter` row shows it at `now`: started at `act_ms`,
/// released at `release_ms`, over at `until_ms`. `held`: a held guard. None once it is over,
/// or when a move broken off before its release (its end before its release) has ended.
pub fn move_phase(act_ms: u64, release_ms: u64, until_ms: u64, held: bool, now: u64) -> Option<Phase> {
    if act_ms == 0 || now < act_ms {
        return None;
    }
    if held {
        return (now < until_ms).then_some(Phase::Holding);
    }
    let cut_short = until_ms < release_ms;
    if cut_short && now >= until_ms {
        return None;
    }
    if now < release_ms {
        let windup = (release_ms - act_ms).max(1) as f32;
        let f = (now - act_ms) as f32 / windup;
        return Some(if f >= LATE_WINDUP { Phase::AboutToRelease } else { Phase::WindingUp });
    }
    if now < release_ms + RELEASING_MS {
        return Some(Phase::Releasing);
    }
    (now < until_ms).then_some(Phase::Recovering)
}

/// The phase of an act card's row (a gesture, work, a meal, a rest): under way while it stands.
pub fn act_phase(since_ms: u64, until_ms: u64, now: u64) -> Option<Phase> {
    (now >= since_ms && (until_ms == 0 || now < until_ms)).then_some(Phase::UnderWay)
}

/// The kind words a move or an act shows besides its name: for a combat move `hostile` (aimed
/// against a creature), `melee` (a blow in reach), `missile` (it looses one), `guard` (a held
/// guard) or `dash`; for an act card its look (`gesture`, `work`, `eat`, `sleep`, `rest`, ...).
pub fn kinds<'a>(shape: Option<&'a Shape>, show: Option<&'a Show>) -> Vec<&'a str> {
    let mut k = Vec::new();
    if let Some(s) = shape {
        if s.hostile {
            k.push("hostile");
        }
        if s.melee {
            k.push("melee");
        }
        if s.missile {
            k.push("missile");
        }
        match s.aim {
            Aim::Facing => k.push("guard"),
            Aim::Dash => k.push("dash"),
            _ => {}
        }
    }
    if let Some(s) = show {
        if !s.look.is_empty() {
            k.push(s.look.as_str());
        }
    }
    k
}

/// Whether `want` (a graph's `is`) names what is seen: the skill's name, its presentation label
/// ("Bow shot" for `bowshot`) or one of its kind words, in any case, with or without spaces.
pub fn is(want: &str, skill: &str, label: Option<&str>, kinds: &[&str]) -> bool {
    let w = squash(want);
    !w.is_empty() && (squash(skill) == w || label.is_some_and(|l| squash(l) == w) || kinds.iter().any(|k| squash(k) == w))
}

fn squash(s: &str) -> String {
    s.chars().filter(|c| c.is_alphanumeric()).flat_map(|c| c.to_lowercase()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_move_reads_by_its_drawn_phases() {
        // A 650 ms windup from t=1000, a 300 ms recovery.
        let p = |now| move_phase(1000, 1650, 1950, false, now);
        assert_eq!(p(999), None);
        assert_eq!(p(1000), Some(Phase::WindingUp));
        assert_eq!(p(1324), Some(Phase::WindingUp));
        assert_eq!(p(1325), Some(Phase::AboutToRelease));
        assert_eq!(p(1649), Some(Phase::AboutToRelease));
        assert_eq!(p(1650), Some(Phase::Releasing));
        assert_eq!(p(1799), Some(Phase::Releasing));
        assert_eq!(p(1800), Some(Phase::Recovering));
        assert_eq!(p(1950), None);
        // No row (act_ms 0) is nothing.
        assert_eq!(move_phase(0, 0, 0, false, 5), None);
    }

    #[test]
    fn a_move_broken_off_ends_when_it_ended() {
        // Its end moved before its release (`act_until`): nothing after it.
        assert_eq!(move_phase(1000, 1650, 1200, false, 1100), Some(Phase::WindingUp));
        assert_eq!(move_phase(1000, 1650, 1200, false, 1200), None);
    }

    #[test]
    fn a_guard_is_held_and_an_act_is_under_way() {
        assert_eq!(move_phase(1000, 9000, 9000, true, 1000), Some(Phase::Holding));
        assert_eq!(move_phase(1000, 9000, 9000, true, 8999), Some(Phase::Holding));
        assert_eq!(move_phase(1000, 9000, 9000, true, 9000), None);
        assert_eq!(act_phase(1000, 3000, 2000), Some(Phase::UnderWay));
        assert_eq!(act_phase(1000, 3000, 3000), None);
    }

    #[test]
    fn winding_up_covers_the_whole_windup() {
        assert!(Phase::AboutToRelease.fits(Phase::WindingUp));
        assert!(Phase::WindingUp.fits(Phase::WindingUp));
        assert!(!Phase::WindingUp.fits(Phase::AboutToRelease));
        assert!(!Phase::Releasing.fits(Phase::WindingUp));
        for p in Phase::ALL {
            assert_eq!(Phase::parse(p.word()), Some(p));
            assert_eq!(Phase::parse(&p.word().replace(' ', "_")), Some(p));
        }
        assert_eq!(Phase::parse("charging"), None);
    }

    #[test]
    fn a_move_is_named_by_its_name_label_or_kind() {
        let bow = Shape { aim: Aim::Point, hostile: true, missile: true, ..Default::default() };
        let k = kinds(Some(&bow), None);
        assert_eq!(k, ["hostile", "missile"]);
        assert!(is("bowshot", "bowshot", Some("Bow shot"), &k));
        assert!(is("bow shot", "bowshot", Some("Bow shot"), &k));
        assert!(is("Missile", "bowshot", Some("Bow shot"), &k));
        assert!(!is("melee", "bowshot", Some("Bow shot"), &k));
        assert!(!is("", "bowshot", None, &k));
        let guard = Shape { aim: Aim::Facing, ..Default::default() };
        assert_eq!(kinds(Some(&guard), None), ["guard"]);
        let wave = Show { look: "gesture".into(), ..Default::default() };
        assert_eq!(kinds(None, Some(&wave)), ["gesture"]);
    }
}
