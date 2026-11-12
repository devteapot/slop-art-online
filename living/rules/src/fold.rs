//! What an onlooker saw of fights it was not party to, folded into one line (docs/BATTLE_SCALE.md,
//! fix 4). Every blow it could see is in the line: who struck whom, in the order each pair was
//! first seen, how many blows and how each ended (landed, blocked, dodged, missed), and who fell.
//! The authority gathers the blows (`fight_seen`) and names the people as the onlooker perceives
//! them; this module only words them, so the same blows always read the same.

use crate::combat::seen;

/// One blow as an onlooker saw it.
#[derive(Clone, Debug, PartialEq)]
pub struct Blow {
    /// Who struck (or shot), 0 when the onlooker could not see the shooter.
    pub attacker: u32,
    pub victim: u32,
    /// `combat::seen::HIT`, `BLOCKED`, `DODGED` or `MISS`.
    pub outcome: u8,
    /// The first blow of a fight (the authority's `first_blow`): "attacked", not "kept on at".
    pub start: bool,
    /// The blow killed its victim.
    pub fell: bool,
    /// The missile ("an arrow", "a spear"), empty for a blow in reach.
    pub missile: String,
}

/// Counts of one pair's blows, in the order the pair was first seen.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Pair {
    pub attacker: u32,
    pub victim: u32,
    pub missile: String,
    pub start: bool,
    pub landed: u32,
    pub blocked: u32,
    pub dodged: u32,
    pub missed: u32,
    pub fell: bool,
}

impl Pair {
    pub fn blows(&self) -> u32 {
        self.landed + self.blocked + self.dodged + self.missed
    }
}

/// The blows grouped by who struck whom (and with what), in the order each pair was first seen.
pub fn pairs(blows: &[Blow]) -> Vec<Pair> {
    let mut out: Vec<Pair> = Vec::new();
    for b in blows {
        let i = match out.iter().position(|p| p.attacker == b.attacker && p.victim == b.victim && p.missile == b.missile) {
            Some(i) => i,
            None => {
                out.push(Pair { attacker: b.attacker, victim: b.victim, missile: b.missile.clone(), start: b.start, ..Default::default() });
                out.len() - 1
            }
        };
        let p = &mut out[i];
        match b.outcome {
            seen::HIT => p.landed += 1,
            seen::BLOCKED => p.blocked += 1,
            seen::DODGED => p.dodged += 1,
            _ => p.missed += 1,
        }
        p.fell |= b.fell;
    }
    out
}

fn cap(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(f) => f.to_uppercase().chain(c).collect(),
        None => String::new(),
    }
}

/// The folded line: one sentence a pair, e.g. "Grim attacked Ada: 3 blows (2 landed, 1 blocked),
/// and Ada fell. A stranger kept on at Bram: 1 blow (1 dodged)." `name` gives how the onlooker
/// refers to each one (its own labels); an attacker of 0 is a shooter it could not see.
pub fn line(blows: &[Blow], name: &dyn Fn(u32) -> String) -> String {
    let mut out = Vec::new();
    for p in pairs(blows) {
        let b = name(p.victim);
        let n = p.blows();
        let head = if p.missile.is_empty() {
            let a = name(p.attacker);
            if p.start { format!("{a} attacked {b}") } else { format!("{a} kept on at {b}") }
        } else if p.attacker == 0 {
            format!("someone you could not see shot at {b} with {}", p.missile)
        } else {
            format!("{} shot at {b} with {}", name(p.attacker), p.missile)
        };
        let unit = if p.missile.is_empty() { "blow" } else { "shot" };
        let parts: Vec<String> = [(p.landed, "landed"), (p.blocked, "blocked"), (p.dodged, "dodged"), (p.missed, "missed")]
            .iter()
            .filter(|(k, _)| *k > 0)
            .map(|(k, w)| format!("{k} {w}"))
            .collect();
        let fell = if p.fell { format!(", and {b} fell") } else { String::new() };
        out.push(format!("{}: {n} {unit}{} ({}){fell}.", cap(&head), if n == 1 { "" } else { "s" }, parts.join(", ")));
    }
    out.join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn blow(a: u32, v: u32, outcome: u8, start: bool, fell: bool) -> Blow {
        Blow { attacker: a, victim: v, outcome, start, fell, missile: String::new() }
    }

    fn names(id: u32) -> String {
        match id {
            1 => "Grim".into(),
            2 => "Ada".into(),
            3 => "a stranger".into(),
            4 => "Bram".into(),
            _ => "someone".into(),
        }
    }

    #[test]
    fn every_blow_seen_is_in_the_line_with_counts_outcomes_and_who_fell() {
        let blows = vec![
            blow(1, 2, seen::HIT, true, false),
            blow(3, 4, seen::DODGED, false, false),
            blow(1, 2, seen::BLOCKED, false, false),
            blow(2, 1, seen::MISS, true, false),
            blow(1, 2, seen::HIT, false, true),
        ];
        let l = line(&blows, &names);
        assert_eq!(
            l,
            "Grim attacked Ada: 3 blows (2 landed, 1 blocked), and Ada fell. A stranger kept on at Bram: 1 blow (1 dodged). Ada attacked Grim: 1 blow (1 missed)."
        );
        let ps = pairs(&blows);
        assert_eq!(ps.iter().map(|p| p.blows()).sum::<u32>(), blows.len() as u32, "no blow is dropped");
        assert_eq!((ps[0].attacker, ps[1].attacker, ps[2].attacker), (1, 3, 2), "pairs in the order first seen");
    }

    #[test]
    fn a_shot_names_the_shooter_only_when_seen() {
        let mut seen_shot = blow(1, 2, seen::HIT, true, false);
        seen_shot.missile = "an arrow".into();
        let mut unseen = blow(0, 4, seen::BLOCKED, true, false);
        unseen.missile = "an arrow".into();
        assert_eq!(
            line(&[seen_shot.clone(), unseen.clone(), unseen], &names),
            "Grim shot at Ada with an arrow: 1 shot (1 landed). Someone you could not see shot at Bram with an arrow: 2 shots (2 blocked)."
        );
    }
}
