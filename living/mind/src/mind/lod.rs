//! Level of detail for people's minds (opt-in: `LIVING_LOD=1`; off by default).
//!
//! Animals already think only near people (the authority's `request_deliberation`). For a
//! world of thousands of people the same idea applies to people, with human players as the
//! audience: a person is **on stage** while a human player is in their scene or has been part
//! of what they experienced within the last `LIVING_LOD_STICKY_S` (default 600 s); everyone
//! else is **off stage**. On stage nothing changes. Off stage, the mind is consulted less often
//! while the body keeps living by its own graph:
//!
//! - a pending deliberation waits until `LIVING_LOD_THINK_S` (600 s) after the person's last
//!   one, collecting the reasons that arrive meanwhile (the authority merges them into the
//!   one pending request); bodily alarms other than starving or being badly hurt, and calls
//!   of one's own kind, wait `LIVING_LOD_PROMPT_S` (120 s); being attacked, a fight, starving,
//!   being badly hurt and what others ask of the person (a trade, a family, joining) are
//!   taken at once, as is the first deliberation after the service starts;
//! - consolidation waits at least `LIVING_LOD_CONSOLIDATE_S` (900 s) between integrations
//!   (the 120-experience backlog still forces one);
//! - a person takes at most one conversation turn per `LIVING_LOD_TALK_S` (120 s); a request
//!   being held back does not keep them from talking (a deliberation under way still does).
//!
//! Animals' requests (which the authority already makes only near a person) wait the same way:
//! near off-stage people an animal lives by instinct and impulse between thoughts.
//!
//! What a mind decides when it does think is unchanged: the same prompts, models and
//! context (the reasons that waited are all in the request). Only how often it is asked
//! changes, like a person nobody is watching living by habit.

use std::time::{Duration, Instant};

#[derive(Clone, Debug)]
pub struct Lod {
    pub on: bool,
    pub think: Duration,
    pub prompt: Duration,
    pub consolidate: Duration,
    pub talk: Duration,
    pub sticky: Duration,
}

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub enum Urgency {
    Routine,
    Prompt,
    Now,
}

/// Whether the level of detail is switched on (`LIVING_LOD=1`).
pub fn enabled() -> bool {
    matches!(std::env::var("LIVING_LOD").as_deref(), Ok("1") | Ok("on") | Ok("true"))
}

fn secs(var: &str, default: u64) -> Duration {
    Duration::from_secs(std::env::var(var).ok().and_then(|v| v.parse().ok()).unwrap_or(default))
}

impl Lod {
    pub fn from_env() -> Self {
        Self {
            on: enabled(),
            think: secs("LIVING_LOD_THINK_S", 600),
            prompt: secs("LIVING_LOD_PROMPT_S", 120),
            consolidate: secs("LIVING_LOD_CONSOLIDATE_S", 900),
            talk: secs("LIVING_LOD_TALK_S", 120),
            sticky: secs("LIVING_LOD_STICKY_S", 600),
        }
    }

    /// How much longer an off-stage person's pending deliberation waits, given its reasons and
    /// how long ago they last deliberated (`None`: take it now).
    pub fn wait(&self, reason: &str, onstage: bool, last: Option<Instant>) -> Option<Duration> {
        if !self.on || onstage {
            return None;
        }
        let last = last?;
        let gap = match urgency(reason) {
            Urgency::Now => return None,
            Urgency::Prompt => self.prompt,
            Urgency::Routine => self.think,
        };
        gap.checked_sub(last.elapsed()).filter(|d| !d.is_zero())
    }
}

/// The most pressing of a request's reasons (one per line, as the authority merges them).
pub fn urgency(reason: &str) -> Urgency {
    reason.lines().map(line_urgency).max().unwrap_or(Urgency::Routine)
}

/// Reasons are written by the authority (`perceive::request_deliberation` callers).
fn line_urgency(line: &str) -> Urgency {
    let l = line.trim();
    const NOW: &[&str] = &[
        "is attacking you",
        "The fight with",
        "Your body: You are starving",
        "Your body: You are badly hurt",
        "offers you",
        "asks to join",
        "asks to start a family with you",
        "asked to start a family with you",
    ];
    if NOW.iter().any(|p| l.contains(p)) {
        return Urgency::Now;
    }
    // Other bodily alarms (freezing, very hungry with no food) and calls of one's own kind
    // ("Mira gave a baby crying (cry).").
    if l.starts_with("Your body:") || (l.contains(" gave ") && l.ends_with(").")) {
        return Urgency::Prompt;
    }
    Urgency::Routine
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lod() -> Lod {
        Lod { on: true, think: Duration::from_secs(600), prompt: Duration::from_secs(120), consolidate: Duration::from_secs(900), talk: Duration::from_secs(120), sticky: Duration::from_secs(600) }
    }

    #[test]
    fn reasons_are_graded() {
        assert_eq!(urgency("A quiet moment to take stock of how things are going."), Urgency::Routine);
        assert_eq!(urgency("Dawn of day 3 (winter). A new day.\nI finished my plan."), Urgency::Routine);
        assert_eq!(urgency("I finished my plan.\nYour body: You are freezing in the night air; you need a fire or shelter."), Urgency::Prompt);
        assert_eq!(urgency("Vale gave a baby crying (cry)."), Urgency::Prompt);
        assert_eq!(urgency("I finished my plan.\nWolf is attacking you!"), Urgency::Now);
        assert_eq!(urgency("Mira (#4) asks to start a family with you; it happens if you choose it toward them within two minutes."), Urgency::Now);
        assert_eq!(urgency("Your body: You are starving: your body is wasting away."), Urgency::Now);
        assert_eq!(urgency("Ivo offers you 2 fish for 3 berries. You may accept or not."), Urgency::Now);
    }

    #[test]
    fn off_stage_waits_on_stage_does_not() {
        let l = lod();
        let just = Some(Instant::now());
        assert!(l.wait("I finished my plan.", false, just).is_some_and(|d| d > Duration::from_secs(590)));
        assert!(l.wait("Your body: You are very hungry.", false, just).is_some_and(|d| d <= Duration::from_secs(120)));
        assert_eq!(l.wait("I finished my plan.", true, just), None);
        assert_eq!(l.wait("I finished my plan.", false, None), None, "the first thought is never held back");
        assert_eq!(l.wait("Wolf is attacking you!", false, just), None);
        assert_eq!(Lod { on: false, ..l }.wait("I finished my plan.", false, just), None);
    }
}
