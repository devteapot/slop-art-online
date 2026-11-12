//! Who would hear a line said now, at each way of speaking (earshot; docs/COMMUNICATION.md §17).
//!
//! The same rule [`crate::speech::speak`] gives the words by: one gather of creatures within the
//! widest carry of the ways, then each person within `carry_for(their own hearing)` of the way.
//! Only people the speaker perceives are listed: someone out of sight who would hear the words
//! cannot be known to be there, so they are left out (they still hear a line that reaches them).
//! A fact of distance and sight, with no advice and nothing about whether anyone is listening.
//!
//! A mind's deliberation scene carries it as words (`perceive::scene_json`, key `speech::EARSHOT`, "who would hear you now"); a
//! player's client reads the same words and the ids by way in `character_earshot`
//! (`my_earshot`, written at the player's frames by `frame::show_earshot`).

use crate::common;
use crate::tables::EarshotWay;
use living_rules::script::speech::SAY;
use spacetimedb::ReducerContext;

/// At most this many people are named for a way; the rest are counted.
pub const NAMED: usize = 8;

/// For each way in the rules' order, the people `speaker` at `at` perceives (`perceived`) whom a
/// line in it would reach if said now, nearest first.
pub fn reach(ctx: &ReducerContext, speaker: u32, at: (f32, f32), perceived: impl Fn(u32) -> bool, now: u64) -> Vec<EarshotWay> {
    let sc = common::scripts(ctx);
    let ways = sc.ways();
    let widest_hearing = common::widest_hearing(ctx);
    let gather = ways.iter().map(|w| w.widest(widest_hearing)).fold(0.0_f32, f32::max);
    if gather <= 0.0 {
        return Vec::new();
    }
    let world = common::world(ctx);
    let people: Vec<(u32, f32, f32)> = common::creatures_near(ctx, at, gather, now)
        .into_iter()
        .filter(|c| c.id != speaker && &*c.kind == "person" && perceived(c.id))
        .map(|c| (c.id, c.dist, common::hearing_for(ctx, c.id, &world, now)))
        .collect();
    ways.iter().map(|w| EarshotWay { way: w.name.clone(), hearers: people.iter().filter(|(_, d, h)| *d <= w.carry_for(*h)).map(|(id, _, _)| *id).collect() }).collect()
}

/// The fact in words, each person by `label`: "Within earshot if you say it: Ife Okoro, a
/// stranger; a call would also reach: Edda Hollin; a whisper would reach no one." A way that
/// reaches everyone a said line does says only whom it adds ("also", or "no one more").
pub fn words(reach: &[EarshotWay], label: impl Fn(u32) -> String) -> String {
    let say = reach.iter().find(|r| r.way == SAY);
    let mut parts = Vec::new();
    if let Some(s) = say {
        parts.push(format!("Within earshot if you say it: {}", names(&s.hearers, &label).unwrap_or_else(|| "no one you see".into())));
    }
    for r in reach.iter().filter(|r| r.way != SAY) {
        let also = say.filter(|s| !s.hearers.is_empty() && s.hearers.iter().all(|id| r.hearers.contains(id)));
        let part = match also {
            Some(s) => {
                let more: Vec<u32> = r.hearers.iter().copied().filter(|id| !s.hearers.contains(id)).collect();
                match names(&more, &label) {
                    Some(n) => format!("a {} would also reach: {n}", r.way),
                    None => format!("a {} would reach no one more", r.way),
                }
            }
            None => match names(&r.hearers, &label) {
                Some(n) => format!("a {} would reach: {n}", r.way),
                None => format!("a {} would reach no one", r.way),
            },
        };
        parts.push(part);
    }
    if parts.is_empty() {
        return String::new();
    }
    let mut out = parts.join("; ");
    out.push('.');
    out
}

/// "Ife Okoro, a stranger, another stranger and 2 more", or `None` for no one.
fn names(ids: &[u32], label: &impl Fn(u32) -> String) -> Option<String> {
    if ids.is_empty() {
        return None;
    }
    let mut seen: Vec<String> = Vec::new();
    let mut out: Vec<String> = Vec::new();
    for id in ids.iter().take(NAMED) {
        let l = label(*id);
        let again = seen.iter().any(|s| *s == l);
        seen.push(l.clone());
        out.push(match (again, l.strip_prefix("a ").or_else(|| l.strip_prefix("an "))) {
            (true, Some(rest)) => format!("another {rest}"),
            _ => l,
        });
    }
    if ids.len() > NAMED {
        out.push(format!("{} more", ids.len() - NAMED));
    }
    Some(out.join(", "))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn way(w: &str, ids: &[u32]) -> EarshotWay {
        EarshotWay { way: w.into(), hearers: ids.to_vec() }
    }

    #[test]
    fn earshot_says_whom_each_way_reaches_and_what_a_wider_one_adds() {
        let label = |id: u32| match id {
            1 => "Ife Okoro".to_string(),
            7 => "Edda Hollin".to_string(),
            _ => "a stranger".to_string(),
        };
        assert_eq!(
            words(&[way("say", &[1, 40]), way("whisper", &[1]), way("call", &[1, 40, 7])], label),
            "Within earshot if you say it: Ife Okoro, a stranger; a whisper would reach: Ife Okoro; a call would also reach: Edda Hollin."
        );
        assert_eq!(words(&[way("say", &[]), way("whisper", &[]), way("call", &[])], label), "Within earshot if you say it: no one you see; a whisper would reach no one; a call would reach no one.");
        assert_eq!(words(&[way("say", &[40, 41]), way("call", &[40, 41])], label), "Within earshot if you say it: a stranger, another stranger; a call would reach no one more.");
        let many: Vec<u32> = (100..111).collect();
        assert_eq!(words(&[way("say", &many)], label), "Within earshot if you say it: a stranger, another stranger, another stranger, another stranger, another stranger, another stranger, another stranger, another stranger, 3 more.");
        assert_eq!(words(&[way("say", &[]), way("call", &[7])], label), "Within earshot if you say it: no one you see; a call would reach: Edda Hollin.");
        assert_eq!(words(&[], label), "");
    }
}
