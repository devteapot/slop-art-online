//! The keys of `mind_state.marks`: every range in one place, so no two uses share a key.
//!
//! A mark is `Mark { node: u16, at_ms }` in the character's `mind_state` row (at most 24, the
//! oldest dropped first). Each use owns a key or a band of keys below; a use that reads a band
//! (the turn counter reads 16 keys) must own all of it. The behavior evaluator writes its own copy
//! of the keys below 0xD000 and from `REFLECT_MARK` up (`brain::Ev::after`); the keys between are
//! written straight to the row (speech, signals, acts, the fast lane) and kept when a new plan is
//! installed (`mind::set_graph`), so their windows run across plans.
//!
//! | Keys | Use | Window | Where |
//! | --- | --- | --- | --- |
//! | 0x0000–0xBFFF | a behavior node's own mark, by node id (a say's 45 s pacing) | per node | `brain` |
//! | 0xC000–0xCFFE | `DESIRE_MARK \| node`: when a desire last began to act | per desire | `brain` |
//! | 0xCFFF | `PLAN_DONE_MARK`: the plan's routine completed | until the next install | `brain` |
//! | 0xD000–0xD1FF | free | | |
//! | 0xD200 | `REPORT_MARK`: the last fight report | 3 s / 30 s | `act::fight_report` |
//! | 0xD210–0xD214 | `BAND_MARK + quarter`: the health quarter last reported | with the report | `act::fight_report` |
//! | 0xD215–0xD3FF | free (0xD300–0xD30F held the turn counter until 2026-11-26) | | |
//! | 0xD400 | `YIELD_MARK`: when the character last yielded | the rules' `yield_ms` | `act` |
//! | 0xD401 | `BALK_MARK`: an animal holding back from a person, in the story | | `act` |
//! | 0xD402 | `YIELD_STRUCK_MARK`: a blow landed while it had yielded | the yield | `act` |
//! | 0xD403–0xD4FF | free | | |
//! | 0xD500 | `FAST_MARK`: the fast lane last changed the plan | | `mind` |
//! | 0xD501–0xD7FF | free | | |
//! | 0xD800–0xDFFF | `signal_key(name)`: a species signal made (a howl, a cry) | 45 s, the same call | `perceive::signal` |
//! | 0xE000–0xEFFF | `act::failure_mark(label, why)`: a failure told | `repeat_failure_s` | `act` |
//! | 0xF000–0xF0FF | `threat_key(victim)`: a threat made to someone | 30 s | `act::begin_with` |
//! | 0xF100–0xF10F | `TURN_MARK + count`: walks turned back, at the window's start | 20 s | `act::turned_back` |
//! | 0xF110–0xFFFB | free | | |
//! | 0xFFFC | `REFLECT_MARK`: the last reflection | per species | `brain` |
//! | 0xFFFD | `FAIL_MARK`: "my actions keep failing" | 30 s | `brain` |
//! | 0xFFFE | `ROOT_MARK`: the plan failed or finished | 8–60 s | `brain` |
//!
//! Hashed bands (signals, failures) spread over their own band only. Until 2026-11-26
//! (turn-mark-band) a signal spread over all of 0xD000–0xDFFF, so the wolf's `howl` (0xD305) was
//! read by the turn counter as "turned back 5 times" (a false "You keep turning back and forth"
//! line, and the howl's own mark consumed). A legacy signal mark below 0xD800 is read by nothing
//! now and is trimmed with the oldest marks. No table changed: the keys are values in a row.

use std::ops::Range;

/// Keys a behavior node's own mark can take (by node id).
pub const NODES: Range<u16> = 0x0000..0xC000;
/// When a desire last began to act: `DESIRE_MARK | node`.
pub const DESIRE_MARK: u16 = 0xC000;
/// Set when the current plan's routine completes; cleared by the next install.
pub const PLAN_DONE_MARK: u16 = 0xCFFF;
/// The first key kept across plan installs and written straight to the row.
pub const KEPT_FROM: u16 = 0xD000;
/// The last fight report.
pub const REPORT_MARK: u16 = 0xD200;
/// The health quarter last reported: `BAND_MARK + quarter` (0–3; 4 means none).
pub const BAND_MARK: u16 = 0xD210;
pub const BANDS: Range<u16> = BAND_MARK..BAND_MARK + 5;
/// When a character last yielded (kept across plan installs).
pub const YIELD_MARK: u16 = 0xD400;
/// Spacing the story's record of an animal holding back from attacking a person.
pub const BALK_MARK: u16 = 0xD401;
/// When a blow last landed on a character while it had yielded.
pub const YIELD_STRUCK_MARK: u16 = 0xD402;
/// When the fast lane last changed the character's plan.
pub const FAST_MARK: u16 = 0xD500;
/// A species signal made: `signal_key`.
pub const SIGNALS: Range<u16> = 0xD800..0xE000;
/// A failure told: `act::failure_mark`.
pub const FAILURES: Range<u16> = 0xE000..0xF000;
/// A threat made to someone: `threat_key`.
pub const THREATS: Range<u16> = 0xF000..0xF100;
/// Walks turned back for another walk: `TURN_MARK + count`, at the window's start.
pub const TURN_MARK: u16 = 0xF100;
pub const TURNS: Range<u16> = TURN_MARK..TURN_MARK + 16;
/// The evaluator's timers, from here up (its own copy, `brain::Ev::after`).
pub const REFLECT_MARK: u16 = u16::MAX - 3;
pub const FAIL_MARK: u16 = u16::MAX - 2;
pub const ROOT_MARK: u16 = u16::MAX - 1;

/// The key of species signal `name` (the same call within 45 s is not news again).
pub fn signal_key(name: &str) -> u16 {
    let h = name.bytes().fold(7u32, |h, b| h.wrapping_mul(31) ^ b as u32);
    SIGNALS.start + (h % (SIGNALS.end - SIGNALS.start) as u32) as u16
}

/// The key of a threat made to `victim`.
pub fn threat_key(victim: u32) -> u16 {
    THREATS.start | (victim % 0x100) as u16
}

/// How many walks the marks say were turned back, and since when (`turned_back`); none when no
/// turn mark is held. Reads only the turn band.
pub fn turns(marks: &[crate::tables::Mark]) -> Option<(u16, u64)> {
    marks.iter().find(|m| TURNS.contains(&m.node)).map(|m| (m.node - TURN_MARK, m.at_ms))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tables::Mark;

    /// Every fixed key and band, in key order, with its name.
    fn fixed() -> Vec<(&'static str, Range<u16>)> {
        let one = |k: u16| k..k + 1;
        vec![
            ("nodes", NODES),
            ("desire", DESIRE_MARK..PLAN_DONE_MARK),
            ("plan done", one(PLAN_DONE_MARK)),
            ("report", one(REPORT_MARK)),
            ("bands", BANDS),
            ("yield", one(YIELD_MARK)),
            ("balk", one(BALK_MARK)),
            ("yield struck", one(YIELD_STRUCK_MARK)),
            ("fast", one(FAST_MARK)),
            ("signals", SIGNALS),
            ("failures", FAILURES),
            ("threats", THREATS),
            ("turns", TURNS),
            ("reflect", one(REFLECT_MARK)),
            ("fail", one(FAIL_MARK)),
            ("root", one(ROOT_MARK)),
        ]
    }

    #[test]
    fn no_two_uses_share_a_key() {
        let all = fixed();
        for w in all.windows(2) {
            assert!(w[0].1.end <= w[1].1.start, "{} {:x?} overlaps {} {:x?}", w[0].0, w[0].1, w[1].0, w[1].1);
        }
        // What `set_graph` keeps and the evaluator leaves to the row: 0xD000 up to its timers.
        assert!(all.iter().filter(|(n, _)| matches!(*n, "report" | "bands" | "yield" | "fast" | "signals" | "failures" | "threats" | "turns")).all(|(_, r)| r.start >= KEPT_FROM && r.end <= REFLECT_MARK));
        assert!(PLAN_DONE_MARK < KEPT_FROM);
    }

    /// turn-mark-band: a howl's mark (0xD305 before) and the turn counter do not meet, whatever
    /// a signal is called, the shipped species' signals among them.
    #[test]
    fn a_howl_is_not_a_turn() {
        let species = living_rules::species::parse(include_str!("../../seeds/species.json")).unwrap();
        let names: Vec<String> = species.values().flat_map(|s| s.signals.keys().cloned()).collect();
        assert!(names.iter().any(|n| n == "howl"));
        for n in names.iter().map(String::as_str).chain(["x", "yowl", "a much longer call than any"]) {
            let k = signal_key(n);
            assert!(SIGNALS.contains(&k), "{n}: {k:#x}");
            for (name, r) in fixed().into_iter().filter(|(name, _)| *name != "signals") {
                assert!(!r.contains(&k), "{n}: {k:#x} is a {name} key");
            }
        }
        assert_eq!(signal_key("howl"), 0xDB05);
        // A howler that walks: its howl is not counted as turns, and its count as no howl.
        let howled = vec![Mark { node: signal_key("howl"), at_ms: 1_000 }];
        assert_eq!(turns(&howled), None);
        let both = vec![Mark { node: signal_key("howl"), at_ms: 1_000 }, Mark { node: TURN_MARK + 2, at_ms: 900 }];
        assert_eq!(turns(&both), Some((2, 900)));
        assert!(!TURNS.contains(&0xD305), "the old howl key is no turn");
        assert_eq!(threat_key(0x1_2345), 0xF045);
    }
}
