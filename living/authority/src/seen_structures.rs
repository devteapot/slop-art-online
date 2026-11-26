//! Durable structure recognition. A look reads each block once and flushes its changes together.

use crate::tables::{seen_structures, SeenStructures};
use living_rules::{known, map};
use spacetimedb::{ReducerContext, Table};
use std::cell::RefCell;
use std::collections::BTreeMap;

/// Run exact compaction once a block exceeds this many disjoint pairs.
const COMPACT_AFTER: usize = 64;
/// Hard ceiling on disjoint pairs kept in one 128 m block when live fragmented remains alone
/// defeat exact compaction: above `MAX_PAIRS` (2 KiB of `ranges`), drop the oldest remains-only
/// intervals down to `TRIM_TO` while sparing every interval that holds a permanent structure.
/// Keeping `MAX_PAIRS` above `COMPACT_AFTER` lets transient partial views of a large field merge
/// cleanly without losing live remains, while still bounding per-row bytes in long battles.
const MAX_PAIRS: usize = 128;
const TRIM_TO: usize = 96;
/// While a block stays above `COMPACT_AFTER` after compaction (either under `MAX_PAIRS` or due
/// to >`MAX_PAIRS` permanent intervals), wait for this many new pairs before walking the 64 chunks
/// again instead of compacting on every look.
const COMPACT_STEP: usize = 16;

thread_local! {
    /// Minimum pair count before a block that stayed above `COMPACT_AFTER` may compact again.
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

fn should_compact(actor: u32, block: u32, pairs: usize) -> bool {
    if pairs <= COMPACT_AFTER {
        return false;
    }
    let floor = NEXT_COMPACT.with(|m| m.borrow().get(&(actor, block)).copied().unwrap_or(0));
    pairs >= floor
}

fn record_compacted(actor: u32, block: u32, pairs_after: usize) {
    NEXT_COMPACT.with(|m| {
        let mut m = m.borrow_mut();
        if pairs_after <= COMPACT_AFTER {
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
        for (_, Block { mut row, added }) in self.0 {
            if added.is_empty() {
                continue;
            }
            row.ranges = merge(&row.ranges, added);
            if should_compact(row.actor, row.block, row.ranges.len() / 2) {
                let (bx, by) = map::chunk_xy(row.block);
                let mut live = Vec::new();
                for dy in 0..known::BLOCK {
                    for dx in 0..known::BLOCK {
                        let chunk = map::chunk_id(bx * known::BLOCK + dx, by * known::BLOCK + dy);
                        let structures = crate::common::chunk_structures(ctx, chunk);
                        live.extend(structures.iter().map(|s| (s.id, s.kind != "remains")));
                    }
                }
                row.ranges = compact_live(&row.ranges, live);
                record_compacted(row.actor, row.block, row.ranges.len() / 2);
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
/// 2. Bound fragmented remains: if the block still has more than `COMPACT_AFTER` disjoint pairs
///    (from interleaved seen and unseen live remains), drop the oldest remains-only intervals down
///    to `TRIM_TO` pairs while sparing every interval that holds a permanent structure.
fn compact_live(ranges: &[u64], mut live: Vec<(u64, bool)>) -> Vec<u64> {
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
    if intervals.len() > MAX_PAIRS {
        let mut drop_n = intervals.len() - TRIM_TO;
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
                ranges = compact_live(&ranges, live.clone());
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
        let compacted = compact_live(&ranges, live.clone());
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
        // 5 permanent structures at low ids + 160 disjoint seen/unseen remains pairs (> MAX_PAIRS).
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
        let compacted = compact_live(&ranges, live.clone());
        assert_eq!(compacted.len() / 2, TRIM_TO);
        // Every permanent structure stays seen.
        for i in 0..5u64 {
            assert!(contains(&compacted, i * 10 + 1), "permanent {i} kept");
            assert!(!contains(&compacted, i * 10 + 5), "unseen permanent {i} stays unseen");
        }
        // Newest remains stay seen; no unseen remains becomes falsely seen.
        for i in (160 - (TRIM_TO as u64 - 5))..160 {
            assert!(contains(&compacted, 1000 + i * 2), "recent remains {i} kept");
        }
        for i in 0..160u64 {
            assert!(!contains(&compacted, 1000 + i * 2 + 1), "unseen remains {i} stays unseen");
        }
    }

    #[test]
    fn compaction_rate_limit_prevents_repeated_walks_above_cap() {
        let (actor, block) = (999_001, 42);
        forget(actor);
        assert!(!should_compact(actor, block, COMPACT_AFTER));
        assert!(should_compact(actor, block, COMPACT_AFTER + 1));
        // Compaction back under COMPACT_AFTER clears the floor.
        record_compacted(actor, block, 40);
        assert!(!should_compact(actor, block, COMPACT_AFTER));
        assert!(should_compact(actor, block, COMPACT_AFTER + 1));
        // Staying above COMPACT_AFTER (e.g. 96 after trim or 140 permanent intervals) waits COMPACT_STEP.
        record_compacted(actor, block, TRIM_TO);
        assert!(!should_compact(actor, block, TRIM_TO + 1));
        assert!(!should_compact(actor, block, TRIM_TO + COMPACT_STEP - 1));
        assert!(should_compact(actor, block, TRIM_TO + COMPACT_STEP));
        forget(actor);
        assert!(should_compact(actor, block, TRIM_TO + 1));
    }
}
