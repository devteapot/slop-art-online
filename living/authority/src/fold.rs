//! Folding what onlookers see of fights (docs/BATTLE_SCALE.md, fix 4).
//!
//! Each blow (landed, blocked, dodged, missed) is written once, to a private `fight_seen` row
//! holding everyone who could see it under the sight rule at that instant: `witnessed`'s own test,
//! facing and walls included, the two in it excepted. Each onlooker is then told what it saw as one
//! line per `witness_fold_ms`, every blow in it ("Grim attacked Ada: 3 blows (2 landed, 1
//! blocked), and Ada fell."): `living_rules::fold`. A blow at the onlooker or by it is never
//! folded; it is told at once, as before (`act::damage`'s own percepts).
//!
//! Timing and waking are unchanged. A fight's first blow wakes its onlookers when it lands, as a
//! bystander (`common::wake_bystander`), as its line did before; the folded line itself wakes no
//! one. A death is still told at once on its own line as well (`act::die`).
//!
//! Each onlooker's windows end at its own phase (`phase`), so the lines of a crowd are spread
//! over the window's ticks rather than all written in one. The pending blows are rows, not module
//! memory: SpacetimeDB does not keep a module's memory between reducer calls
//! (https://spacetimedb.com/docs/functions/reducers/, "Global and Static Variables Are Undefined
//! Behavior").

use crate::common::{self, pos};
use crate::tables::*;
use spacetimedb::{ReducerContext, Table};
use std::collections::HashMap;

/// Set on an onlooker in `fight_seen.onlookers` that saw where a missile struck but not its
/// shooter. Character ids stay far below it.
pub const UNSEEN_SHOOTER: u32 = 1 << 31;

/// Whether fights are folded (`witness_fold_ms` above 0).
pub fn on(ctx: &ReducerContext) -> bool {
    common::laws(ctx).witness_fold_ms > 0.0
}

/// Where in the window an onlooker's windows end (ms), spread by its id.
fn phase(id: u32, fold: u64) -> u64 {
    (id as u64).wrapping_mul(2_654_435_761) % fold
}

/// The end of `id`'s window holding a blow at `at_ms`: the first boundary after it.
fn window_end(id: u32, at_ms: u64, fold: u64) -> u64 {
    let p = phase(id, fold);
    // Boundaries are the times t with (t + p) % fold == 0.
    let next = (at_ms + p) / fold * fold + fold;
    next - p
}

/// A blow landed, was blocked, dodged or missed: written once, with who could see it. `wake`: it
/// wakes its onlookers as bystanders, as a fight's first landed blow did with its own line (a
/// person or animal; an animal not for a shot, as `witnessed_shot` weighed it).
#[allow(clippy::too_many_arguments)]
pub fn blow(ctx: &ReducerContext, now: u64, attacker: u32, victim: u32, outcome: u8, start: bool, fell: bool, wake: bool, missile: Option<&str>, at: (f32, f32)) {
    if !on(ctx) {
        return;
    }
    let _span = common::span("fold.blow");
    let w = common::world(ctx);
    let map = common::map(ctx);
    let r = crate::perception::widest_sight(ctx, &w, now);
    let mut onlookers = Vec::new();
    for (c, d) in crate::perceive::minds_near(ctx, at, r, now, &[attacker, victim]) {
        // As `perceive::percept_seen`: only minds and players read it.
        if !c.alive || c.stage == 0 {
            continue;
        }
        let Some((eye, heading)) = ctx.db.body().id().find(c.id).map(|b| (pos(&b, now), common::facing_at(&b, now))) else { continue };
        // A shot is seen where it struck (`witnessed_shot`), a blow by who struck it (`witnessed`).
        let seen_by = if missile.is_some() { victim } else { attacker };
        if !crate::perception::in_sight(ctx, &map, c.id, eye, heading, seen_by, at, d, &w, now, false) {
            continue;
        }
        let sees_shooter = missile.is_none() || crate::perception::sees_creature(ctx, c.id, attacker, now);
        onlookers.push(if sees_shooter { c.id } else { c.id | UNSEEN_SHOOTER });
        if wake && (missile.is_none() || &*c.kind == "person") {
            common::diag(|| "woke:fight", 1);
            common::wake_bystander(ctx, c.id, now);
        }
    }
    common::diag(|| "fold:blow", 1);
    common::diag(|| "fold:onlookers", onlookers.len() as u64);
    if onlookers.is_empty() {
        return;
    }
    ctx.db.fight_seen().insert(FightSeen { id: 0, at_ms: now, attacker, victim, outcome, start, fell, missile: missile.unwrap_or("").to_string(), x: at.0, y: at.1, onlookers });
}

/// Tell each onlooker whose window ended since the last tick (`prev`, exclusive, to `now`) what
/// it saw in it, as one line; then drop the rows every onlooker has been told.
pub fn flush(ctx: &ReducerContext, prev: u64, now: u64) {
    let fold = (common::laws(ctx).witness_fold_ms as u64).max(1);
    let rows: Vec<FightSeen> = ctx.db.fight_seen().at_ms().filter(..now).collect();
    if rows.is_empty() {
        return;
    }
    let _span = common::span("fold.flush");
    // Folding switched off (`witness_fold_ms` 0) with blows still held: told now.
    let off = !on(ctx);
    let scan = common::detail_span("fold.scan");
    let mut due: HashMap<u32, Vec<(usize, bool)>> = HashMap::new();
    for (i, r) in rows.iter().enumerate() {
        for &o in &r.onlookers {
            let id = o & !UNSEEN_SHOOTER;
            let end = window_end(id, r.at_ms, fold);
            if off || (end > prev && end <= now) {
                due.entry(id).or_default().push((i, o & UNSEEN_SHOOTER != 0));
            }
        }
    }
    drop(scan);
    let mut ids: Vec<u32> = due.keys().copied().collect();
    ids.sort_unstable();
    for id in ids {
        let Some(c) = ctx.db.character().id().find(id) else { continue };
        if !c.alive {
            continue;
        }
        let seen_rows = &due[&id];
        let blows: Vec<living_rules::fold::Blow> = seen_rows
            .iter()
            .map(|&(i, unseen)| {
                let r = &rows[i];
                living_rules::fold::Blow { attacker: if unseen { 0 } else { r.attacker }, victim: r.victim, outcome: r.outcome, start: r.start, fell: r.fell, missile: r.missile.clone() }
            })
            .collect();
        // Each one as this onlooker refers to them (its own labels, projected once each).
        let mut who: Vec<u32> = blows.iter().flat_map(|b| [b.attacker, b.victim]).filter(|x| *x != 0).collect();
        who.sort_unstable();
        who.dedup();
        // A mind's line anchors each one it cannot name by the id its scene knows them by (a far
        // figure by its sighting's handle), "a stranger (#412)", as other lines naming several
        // people do: a line can hold many strangers' fights, and the line's own subject and object
        // anchor only one pair. A player's line reads as the screen shows it.
        let named = common::detail_span("fold.labels");
        let player = crate::combat::human(ctx, c.id).is_some();
        let labels: HashMap<u32, String> = who
            .iter()
            .copied()
            .zip(crate::perception::labels(ctx, &c, &who, now))
            .map(|(x, label)| match ctx.db.character().id().find(x) {
                Some(t) if !player && label != t.name => (x, format!("{label} (#{})", crate::far::id_for(ctx, &c, &t, now))),
                _ => (x, label),
            })
            .collect();
        drop(named);
        let _write = common::detail_span("fold.write");
        let text = living_rules::fold::line(&blows, &|x| labels.get(&x).cloned().unwrap_or_else(|| "someone".into()));
        let salient = blows.iter().any(|b| b.start || b.fell);
        let first = &rows[seen_rows[0].0];
        let (a, v) = (if seen_rows[0].1 { 0 } else { first.attacker }, first.victim);
        // Its first blow woke it when it landed; the line itself wakes no one.
        crate::perceive::percept_quiet(ctx, &c, now, "fight", a, v, (first.x, first.y), text, if salient { 0.7 } else { 0.5 });
        common::diag(|| "fold:line", 1);
        common::diag(|| "fold:line_blows", blows.len() as u64);
    }
    // A row is told to everyone once its last onlooker's window has ended: at most `fold` after it.
    for r in rows.iter().filter(|r| off || r.at_ms + fold <= now) {
        ctx.db.fight_seen().id().delete(r.id);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_blow_falls_in_exactly_one_window_of_each_onlooker() {
        let fold = 1000;
        for id in [1u32, 7, 268, 4_000_000] {
            for at in [0u64, 1, 999, 1000, 12_345, 99_999] {
                let end = window_end(id, at, fold);
                assert!(end > at && end <= at + fold, "id {id} at {at}: end {end}");
                assert_eq!((end + phase(id, fold)) % fold, 0, "a boundary");
            }
        }
        // Ticks of any length (a pause included) tell each blow once: in the tick whose
        // (prev, now] holds its window's end.
        let (id, at) = (268u32, 5_432u64);
        let end = window_end(id, at, fold);
        let ticks = [5_432u64, 5_449, 5_466, 7_000, 9_000];
        let told: Vec<_> = ticks.windows(2).filter(|t| end > t[0] && end <= t[1]).collect();
        assert_eq!(told.len(), 1);
    }
}
