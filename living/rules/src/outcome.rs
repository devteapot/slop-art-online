//! How an act or a death came out, as stable codes (`act_outcome`, read through
//! `my_act_outcomes`; docs/PERCEPTION.md, "Act outcomes"). A client draws a refused act's note,
//! and the death screen, from these codes and the row's words, never by parsing an experience
//! line's English. Every list is append-only (test `the_codes_only_grow`): a code a client knows
//! keeps its meaning in every later world.

/// What kind of outcome a row is: the code's vocabulary.
pub mod kind {
    /// A deliberate act's (a player's command or a mind's decision): `ACT_CODES`.
    pub const ACT: &str = "act";
    /// A behaviour graph's action told to a person playing the character (it failed or was
    /// refused): `ACT_CODES`.
    pub const OWN: &str = "own";
    /// The character's own death: `DEATH_CODES`.
    pub const DEATH: &str = "death";
    pub const ALL: &[&str] = &[ACT, OWN, DEATH];
}

/// At which point an act's outcome was decided.
pub mod act {
    /// It was done (`ok`).
    pub const DONE: &str = "done";
    /// The act could not be read (not JSON, an unknown skill, a missing argument).
    pub const UNREADABLE: &str = "unreadable";
    /// Too much was waiting already (`acts::MAX_QUEUED`).
    pub const BUSY: &str = "busy";
    /// It waited too long to start (`acts::QUEUE_MS`).
    pub const EXPIRED: &str = "expired";
    /// Its target was not in sight when it was to start, or could not be seen.
    pub const UNSEEN: &str = "unseen";
    /// The skill's own rule (`<skill>_check`) refused it.
    pub const CHECK: &str = "check";
    /// Combat timing refused it: a cooldown, recovery, or another windup under way.
    pub const TIMING: &str = "timing";
    /// The target was out of reach (a player's move does not walk into reach).
    pub const REACH: &str = "reach";
    /// The engine refused it as it would start, for another reason (nowhere to go, cornered,
    /// already there, already facing it, a threat already made).
    pub const REFUSED: &str = "refused";
    /// It started and then failed (its completion said no).
    pub const FAILED: &str = "failed";
    /// It was broken off: a reflex took the body back, a new command replaced it.
    pub const BROKEN_OFF: &str = "broken_off";
    /// It was broken off because its maker moved before it was done (a player's move; a skill
    /// whose spec says `on_the_move` is not). Its words are the rules' `moved_off(skill)`.
    pub const MOVED: &str = "moved";
    /// Acts still waiting were dropped when a reflex took the body back (no skill).
    pub const SET_ASIDE: &str = "set_aside";
}

/// How a death happened.
pub mod death {
    pub const STARVED: &str = "starved";
    /// Cold and exposure at night.
    pub const COLD: &str = "cold";
    pub const EXHAUSTED: &str = "exhausted";
    pub const OLD_AGE: &str = "old_age";
    /// Killed by someone (the row's `other`).
    pub const KILLED: &str = "killed";
    /// Killed by someone after yielding to them.
    pub const KILLED_YIELDING: &str = "killed_yielding";
    /// Any other cause (an admin's `kill` with its own words).
    pub const OTHER: &str = "other";
}

pub const ACT_CODES: &[&str] = &[act::DONE, act::UNREADABLE, act::BUSY, act::EXPIRED, act::UNSEEN, act::CHECK, act::TIMING, act::REACH, act::REFUSED, act::FAILED, act::BROKEN_OFF, act::SET_ASIDE, act::MOVED];
pub const DEATH_CODES: &[&str] = &[death::STARVED, death::COLD, death::EXHAUSTED, death::OLD_AGE, death::KILLED, death::KILLED_YIELDING, death::OTHER];

/// A death's words for the one who died, by its code: `by` is how they knew their killer (a
/// label, or a name they knew), `cause` the cause's own words for `OTHER`.
pub fn death_words(code: &str, by: &str, cause: &str) -> String {
    match code {
        death::STARVED => "You starved.".into(),
        death::COLD => "You died of cold and exposure.".into(),
        death::EXHAUSTED => "You died of exhaustion.".into(),
        death::OLD_AGE => "You died of old age.".into(),
        death::KILLED => format!("You were killed by {by}."),
        death::KILLED_YIELDING => format!("You were killed by {by} after yielding."),
        _ => format!("You died ({cause})."),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The codes as first shipped, in order. Append new ones at the end of a list; never
    /// rename, reorder or remove one.
    #[test]
    fn the_codes_only_grow() {
        let acts = ["done", "unreadable", "busy", "expired", "unseen", "check", "timing", "reach", "refused", "failed", "broken_off", "set_aside"];
        let deaths = ["starved", "cold", "exhausted", "old_age", "killed", "killed_yielding", "other"];
        let kinds = ["act", "own", "death"];
        assert_eq!(&ACT_CODES[..acts.len()], &acts[..]);
        assert_eq!(&DEATH_CODES[..deaths.len()], &deaths[..]);
        assert_eq!(&kind::ALL[..kinds.len()], &kinds[..]);
        for list in [ACT_CODES, DEATH_CODES, kind::ALL] {
            let mut v = list.to_vec();
            v.sort_unstable();
            v.dedup();
            assert_eq!(v.len(), list.len(), "a code appears twice");
        }
    }

    #[test]
    fn a_death_names_the_killer_as_the_dead_knew_them() {
        assert_eq!(death_words(death::KILLED, "a stranger in orange", "killed by Varek"), "You were killed by a stranger in orange.");
        assert_eq!(death_words(death::OTHER, "", "a falling tree"), "You died (a falling tree).");
    }
}
