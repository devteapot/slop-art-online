//! Durable structure recognition. A look reads each block once and flushes its changes together.

use crate::tables::{seen_structures, SeenStructures};
use living_rules::{known, map};
use spacetimedb::{ReducerContext, Table};
use std::collections::BTreeMap;

const COMPACT_AFTER: usize = 64;

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
            if row.ranges.len() / 2 > COMPACT_AFTER {
                let (bx, by) = map::chunk_xy(row.block);
                let mut live = Vec::new();
                for dy in 0..known::BLOCK {
                    for dx in 0..known::BLOCK {
                        let chunk = map::chunk_id(bx * known::BLOCK + dx, by * known::BLOCK + dy);
                        let structures = crate::common::chunk_structures(ctx, chunk);
                        live.extend(structures.iter().map(|s| s.id));
                    }
                }
                row.ranges = compact(&row.ranges, live);
            }
            if row.id == 0 {
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

fn compact(ranges: &[u64], mut live: Vec<u64>) -> Vec<u64> {
    live.retain(|&id| contains(ranges, id));
    merge(&[], live)
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
                let live: Vec<_> = (0..2048).filter(|id| id % 3 != round % 3).collect();
                ranges = compact(&ranges, live);
                set.retain(|id| id % 3 != round % 3);
            }
            for id in 0..2048 {
                assert_eq!(
                    contains(&ranges, id),
                    set.contains(&id),
                    "id {id} in round {round}"
                );
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
}
