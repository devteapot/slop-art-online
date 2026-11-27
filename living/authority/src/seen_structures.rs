//! Durable structure recognition. A look reads each block once and flushes its changes together.

use crate::tables::{seen_structures, SeenStructures};
use living_rules::{known, map};
use spacetimedb::{ReducerContext, Table};
use std::cell::RefCell;
use std::collections::BTreeMap;

/// Run exact compaction once a block exceeds this many disjoint pairs (or `seen_ranges_max_pairs`
/// when that world law is set lower).
const COMPACT_AFTER: usize = 64;
/// While a block stays above the compaction trigger after compaction (either under the cap or due
/// to permanent intervals), wait for this many new pairs before walking the 64 chunks again.
const COMPACT_STEP: usize = 16;

/// Target pair count when trimming fragmented remains-only intervals above `max_pairs`: 3/4 of
/// the cap (default `128` -> `96`), buying at least a quarter of the cap before the next trim.
fn trim_to(max_pairs: usize) -> usize {
    ((max_pairs * 3) / 4).max(1).min(max_pairs)
}

fn compact_trigger(max_pairs: usize) -> usize {
    if max_pairs == 0 { COMPACT_AFTER } else { COMPACT_AFTER.min(max_pairs) }
}

thread_local! {
    /// Minimum pair count before a block that stayed above `compact_trigger` may compact again.
    /// `BTreeMap` (no `RandomState`) so module-memory order cannot perturb `det_compare`.
    static NEXT_COMPACT: RefCell<BTreeMap<(u32, u32), usize>> = const { RefCell::new(BTreeMap::new()) };
}

/// Drop an actor's per-block compaction cooldowns on death (`act::forget_dead`).
pub(crate) fn forget(actor: u32) {
    NEXT_COMPACT.with(|m| {
        let mut m = m.borrow_mut();
        let keys: Vec<(u32, u32)> = m.range((actor, 0)..=(actor, u32::MAX)).map(|(&k, _)| k).collect();
        for k in keys {
            m.remove(&k);
        }
    });
}

fn should_compact(actor: u32, block: u32, pairs: usize, trigger: usize) -> bool {
    if pairs <= trigger {
        return false;
    }
    let floor = NEXT_COMPACT.with(|m| m.borrow().get(&(actor, block)).copied().unwrap_or(0));
    pairs >= floor
}

fn record_compacted(actor: u32, block: u32, pairs_after: usize, trigger: usize) {
    NEXT_COMPACT.with(|m| {
        let mut m = m.borrow_mut();
        if pairs_after <= trigger {
            m.remove(&(actor, block));
        } else {
            m.insert((actor, block), pairs_after.saturating_add(COMPACT_STEP));
        }
    });
}

#[derive(Default)]
pub(crate) struct Look(BTreeMap<u32, Block>);

struct Block {
    row: SeenStructures,
    added: Vec<u64>,
}

impl Look {
    fn block(&mut self, ctx: &ReducerContext, actor: u32, block: u32) -> &mut Block {
        self.0.entry(block).or_insert_with(|| Block {
            row: ctx
                .db
                .seen_structures()
                .by_actor_block()
                .filter((actor, block))
                .next()
                .unwrap_or_else(|| SeenStructures {
                    id: 0,
                    actor,
                    block,
                    ranges: Vec::new(),
                }),
            added: Vec::new(),
        })
    }

    pub(crate) fn seen(&mut self, ctx: &ReducerContext, actor: u32, chunk: u32, id: u64) -> bool {
        contains(
            &self.block(ctx, actor, known::block_of(chunk).0).row.ranges,
            id,
        )
    }

    pub(crate) fn add(&mut self, ctx: &ReducerContext, actor: u32, chunk: u32, id: u64) {
        self.block(ctx, actor, known::block_of(chunk).0)
            .added
            .push(id);
    }

    pub(crate) fn write(self, ctx: &ReducerContext) {
        let max_pairs = crate::common::laws(ctx).seen_ranges_max_pairs.round().max(0.0) as usize;
        let trigger = compact_trigger(max_pairs);
        for (_, Block { mut row, added }) in self.0 {
            if added.is_empty() {
                continue;
            }
            row.ranges = merge(&row.ranges, added);
            if should_compact(row.actor, row.block, row.ranges.len() / 2, trigger) {
                let (bx, by) = map::chunk_xy(row.block);
                let mut live = Vec::new();
                for dy in 0..known::BLOCK {
                    for dx in 0..known::BLOCK {
                        let chunk = map::chunk_id(bx * known::BLOCK + dx, by * known::BLOCK + dy);
                        let structures = crate::common::chunk_structures(ctx, chunk);
                        live.extend(structures.iter().map(|s| (s.id, s.kind != "remains")));
                    }
                }
                row.ranges = compact_live(&row.ranges, live, max_pairs);
                record_compacted(row.actor, row.block, row.ranges.len() / 2, trigger);
                crate::common::diag(|| "seen_structures:compacted", 1);
            }
            if row.ranges.is_empty() {
                if row.id != 0 {
                    ctx.db.seen_structures().id().delete(row.id);
                }
            } else if row.id == 0 {
                ctx.db.seen_structures().insert(row);
            } else {
                ctx.db.seen_structures().id().update(row);
            }
        }
    }
}

fn contains(ranges: &[u64], id: u64) -> bool {
    let mut low = 0;
    let mut high = ranges.len() / 2;
    while low < high {
        let mid = low + (high - low) / 2;
        if ranges[2 * mid + 1] < id {
            low = mid + 1;
        } else {
            high = mid;
        }
    }
    ranges.get(2 * low).is_some_and(|&start| start <= id)
}

fn merge(ranges: &[u64], added: Vec<u64>) -> Vec<u64> {
    let mut pairs: Vec<_> = ranges
        .chunks_exact(2)
        .map(|p| (p[0], p[1]))
        .chain(added.into_iter().map(|id| (id, id)))
        .collect();
    pairs.sort_unstable();
    let mut merged: Vec<u64> = Vec::new();
    for (start, end) in pairs {
        if let Some(last) = merged
            .last_mut()
            .filter(|last| start <= last.saturating_add(1))
        {
            *last = (*last).max(end);
        } else {
            merged.extend([start, end]);
        }
    }
    merged
}

/// Compact `ranges` against all live `(id, is_permanent)` structures in this 128 m block:
/// 1. Exact gap-bridging: drop expired ids and merge consecutive seen live ids whenever no
///    unseen live structure lies strictly between them (structure ids are `#[auto_inc]`, so no
///    future structure in this block can fall inside a bridged gap).
/// 2. Bound fragmented remains: when `max_pairs > 0` (the `seen_ranges_max_pairs` law, default 128)
///    and the block still exceeds `max_pairs`, drop the oldest remains-only intervals down to
///    `trim_to(max_pairs)` (3/4, default 96) while sparing every interval holding a permanent structure.
fn compact_live(ranges: &[u64], mut live: Vec<(u64, bool)>, max_pairs: usize) -> Vec<u64> {
    live.sort_unstable_by_key(|&(id, _)| id);
    let mut intervals: Vec<(u64, u64, bool)> = Vec::new();
    let mut open: Option<(u64, u64, bool)> = None;
    for (id, perm) in live {
        if contains(ranges, id) {
            match &mut open {
                Some((_, end, has_perm)) => {
                    *end = id;
                    *has_perm |= perm;
                }
                None => open = Some((id, id, perm)),
            }
        } else if let Some(iv) = open.take() {
            intervals.push(iv);
        }
    }
    if let Some(iv) = open {
        intervals.push(iv);
    }
    if max_pairs > 0 && intervals.len() > max_pairs {
        let mut drop_n = intervals.len() - trim_to(max_pairs);
        intervals.retain(|&(_, _, has_perm)| {
            if !has_perm && drop_n > 0 {
                drop_n -= 1;
                false
            } else {
                true
            }
        });
    }
    let mut out = Vec::with_capacity(intervals.len() * 2);
    for (start, end, _) in intervals {
        out.extend([start, end]);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    const DEFAULT_MAX: usize = 128;

    #[test]
    fn ranges_match_a_set_through_insertion_and_compaction() {
        let mut ranges = Vec::new();
        let mut set = BTreeSet::new();
        for round in 0..20 {
            let added: Vec<_> = (0..77).map(|i| (i * 97 + round * 331) % 2048).collect();
            set.extend(added.iter().copied());
            ranges = merge(&ranges, added);
            if ranges.len() / 2 > COMPACT_AFTER {
                // Every id is permanent here, so exact compaction must preserve exact membership
                // for all live structures in the block.
                let live: Vec<_> = (0..2048).filter(|id| id % 3 != round % 3).map(|id| (id, true)).collect();
                ranges = compact_live(&ranges, live.clone(), DEFAULT_MAX);
                set.retain(|id| id % 3 != round % 3);
                for &(id, _) in &live {
                    assert_eq!(
                        contains(&ranges, id),
                        set.contains(&id),
                        "live id {id} in round {round}"
                    );
                }
                // Future auto-inc ids are strictly greater than every existing id.
                assert!(!contains(&ranges, 2048));
            }
            assert!(ranges.chunks_exact(2).all(|pair| pair[0] <= pair[1]));
            assert!(ranges
                .chunks_exact(2)
                .zip(ranges.chunks_exact(2).skip(1))
                .all(|(left, right)| left[1] + 1 < right[0]));
        }
        assert_eq!(
            merge(&[u64::MAX - 2, u64::MAX - 1], vec![u64::MAX, u64::MAX]),
            vec![u64::MAX - 2, u64::MAX]
        );
    }

    #[test]
    fn exact_compaction_bridges_gaps_without_unseen_live_structures() {
        // Seen ids 10, 14, 100 (gaps at 11..13 and 15..99 are dead/other-block/sequence-skip).
        // Live unseen structure at 50 prevents bridging 14..100, while 10..14 bridges cleanly.
        let ranges = merge(&[], vec![10, 14, 100, 105]);
        let live = vec![
            (10, true),
            (14, false),
            (50, false),  // unseen live remains
            (100, false),
            (105, false),
            (200, true),  // unseen live permanent
        ];
        let compacted = compact_live(&ranges, live.clone(), DEFAULT_MAX);
        assert_eq!(compacted, vec![10, 14, 100, 105]);
        for &(id, _) in &live {
            assert_eq!(contains(&compacted, id), contains(&ranges, id), "id {id}");
        }
        assert!(!contains(&compacted, 50));
        assert!(!contains(&compacted, 200));
        assert!(!contains(&compacted, 201));
    }

    #[test]
    fn compaction_caps_remains_intervals_and_protects_permanent_structures() {
        // 5 permanent structures at low ids + 160 disjoint seen/unseen remains pairs.
        let mut live = Vec::new();
        let mut seen = Vec::new();
        for i in 0..5u64 {
            live.push((i * 10 + 1, true));
            live.push((i * 10 + 5, true)); // unseen permanent between them
            seen.push(i * 10 + 1);
        }
        for i in 0..160u64 {
            let base = 1000 + i * 2;
            live.push((base, false));     // seen remains
            live.push((base + 1, false)); // unseen remains
            seen.push(base);
        }
        let ranges = merge(&[], seen);
        assert_eq!(ranges.len() / 2, 165);
        // Default law value (128 -> 96).
        let compacted = compact_live(&ranges, live.clone(), DEFAULT_MAX);
        assert_eq!(trim_to(DEFAULT_MAX), 96);
        assert_eq!(compacted.len() / 2, 96);
        for i in 0..5u64 {
            assert!(contains(&compacted, i * 10 + 1), "permanent {i} kept");
            assert!(!contains(&compacted, i * 10 + 5), "unseen permanent {i} stays unseen");
        }
        for i in (160 - (96u64 - 5))..160 {
            assert!(contains(&compacted, 1000 + i * 2), "recent remains {i} kept");
        }
        for i in 0..160u64 {
            assert!(!contains(&compacted, 1000 + i * 2 + 1), "unseen remains {i} stays unseen");
        }
        // Tuned law value (64 -> 48) and uncapped (0 -> keeps all 165).
        assert_eq!(compact_live(&ranges, live.clone(), 64).len() / 2, 48);
        assert_eq!(compact_live(&ranges, live, 0).len() / 2, 165);
    }

    #[test]
    fn compaction_rate_limit_prevents_repeated_walks_above_cap() {
        let (actor, block) = (999_001, 42);
        let trigger = compact_trigger(DEFAULT_MAX);
        assert_eq!(trigger, COMPACT_AFTER);
        assert_eq!(compact_trigger(32), 32);
        assert_eq!(compact_trigger(0), COMPACT_AFTER);
        forget(actor);
        assert!(!should_compact(actor, block, trigger, trigger));
        assert!(should_compact(actor, block, trigger + 1, trigger));
        // Compaction back under trigger clears the floor.
        record_compacted(actor, block, 40, trigger);
        assert!(!should_compact(actor, block, trigger, trigger));
        assert!(should_compact(actor, block, trigger + 1, trigger));
        // Staying above trigger (e.g. 96 after trim) waits COMPACT_STEP.
        let kept = trim_to(DEFAULT_MAX);
        record_compacted(actor, block, kept, trigger);
        assert!(!should_compact(actor, block, kept + 1, trigger));
        assert!(!should_compact(actor, block, kept + COMPACT_STEP - 1, trigger));
        assert!(should_compact(actor, block, kept + COMPACT_STEP, trigger));
        forget(actor);
        assert!(should_compact(actor, block, kept + 1, trigger));
    }
}
