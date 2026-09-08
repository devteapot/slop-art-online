//! Incremental persistence for a proven append/prune since this transaction's
//! retained kernel snapshot. General edits keep the complete reconciliation path.
use super::*;

struct AppendPlan {
    pages: PagePlan,
    changes: BTreeMap<u64, i64>,
    reads: usize,
}

/// Previous metadata was validated when the retained kernel trace was loaded.
/// Its page layout must still match the addressed head. Unusual appended cursor
/// order falls back to the general writer, preserving its existing semantics.
fn eligible(head: &SimNativeTraceHead, previous: &[Experience], appended: &[Experience]) -> bool {
    let mut firsts = vec![];
    let mut bucket = None;
    let mut maximum = None;
    for e in previous {
        let next = e.cursor / PAGE_CURSORS;
        if bucket != Some(next) { firsts.push(e.cursor); bucket = Some(next); }
        maximum = Some(maximum.map_or(e.cursor, |old: u64| old.max(e.cursor)));
    }
    if firsts != head.pages { return false; }
    for e in appended {
        if maximum.is_some_and(|old| e.cursor <= old) { return false; }
        maximum = Some(e.cursor);
    }
    true
}

/// Read only pages from which old references are removed and the existing tail
/// if a new record shares its cursor bucket. Untouched pages retain their keys,
/// metadata and body references without being fetched or rewritten here.
fn plan(run: &str, actor: u32, mut head: SimNativeTraceHead, mut removed: usize,
    appended: &[ResolvedEntry<'_>], mut read: impl FnMut(u64) -> Result<SimNativeTracePage, String>,
) -> Result<AppendPlan, String> {
    if head.key != key(run, actor) || head.run != run || head.actor != actor {
        return Err("native append head scope mismatch".into());
    }
    let old_page_count = head.pages.len();
    let mut changed: BTreeMap<u64, (bool, SimNativeTracePage)> = BTreeMap::new();
    let mut deleted = vec![];
    let mut changes = BTreeMap::new();
    let mut reads = 0;
    let mut page = |first| {
        let row = read(first)?;
        let one = SimNativeTraceHead {key: key(run, actor), run: run.into(), actor, pages: vec![first]};
        walk_pages(run, actor, &one, std::slice::from_ref(&row), |_| {})?;
        reads += 1;
        Ok::<_, String>(row)
    };
    while removed > 0 {
        let first = *head.pages.first().ok_or("native append removes missing evidence")?;
        let mut old = page(first)?;
        let count = removed.min(old.entries.len());
        for entry in old.entries.drain(..count) { reference_change(&mut changes, Some(entry.body), None); }
        removed -= count;
        deleted.push(old.key);
        head.pages.remove(0);
        if let Some(entry) = old.entries.first() {
            let first = entry.metadata.cursor;
            old.first = first;old.key = page_key(run, actor, first);
            head.pages.insert(0, first);
            changed.insert(first, (false, old));
        }
    }
    for entry in appended {
        if entry.body == 0 { return Err("native append body missing".into()); }
        let first = match head.pages.last().copied() {
            Some(first) if first / PAGE_CURSORS == entry.experience.cursor / PAGE_CURSORS => {
                if !changed.contains_key(&first) { changed.insert(first, (true, page(first)?)); }
                first
            }
            _ => {
                let first = entry.experience.cursor;
                if changed.contains_key(&first) || head.pages.contains(&first) {
                    return Err("native append repeats page key".into());
                }
                head.pages.push(first);
                changed.insert(first, (false, SimNativeTracePage {key: page_key(run, actor, first),
                    run: run.into(), actor, first, entries: vec![]}));
                first
            }
        };
        let target = &mut changed.get_mut(&first).unwrap().1;
        if target.entries.len() >= PAGE_CURSORS as usize { return Err("native append page overflow".into()); }
        target.entries.push(entry.materialize());
        reference_change(&mut changes, None, Some(entry.body));
    }
    let reused = old_page_count.checked_sub(deleted.len() + changed.values().filter(|(exists, _)| *exists).count())
        .ok_or("native append page accounting")?;
    Ok(AppendPlan {pages: PagePlan {head, writes: changed.into_values().collect(), removed: deleted, reused}, changes, reads})
}

impl Writes {
    pub(super) fn append_delta(&mut self, ctx: &ReducerContext, run: &str, actor: u32,
        state: &ParticipantState, previous: Option<&ParticipantState>, sampled: bool,
        profile: &mut super::super::super::evidence_profile::SaveScope,
    ) -> bool {
        let Some(previous) = previous else { return false; };
        let Some(delta) = state.experiences.appended_since(&previous.experiences) else { return false; };
        let head = ctx.db.sim_native_trace_head().key().find(key(run, actor)).expect("native trace head exists");
        if !eligible(&head, &previous.experiences, delta.appended) { return false; }
        profile.phase(sampled, "participant.save.rows");
        let current: Vec<_> = delta.appended.iter().map(|experience| ResolvedEntry {
            experience, body: self.body(ctx, run, json(&experience.data)),
        }).collect();
        profile.phase(sampled, "participant.save.index");
        let plan = plan(run, actor, head, delta.removed, &current, |first|
            ctx.db.sim_native_trace_page().key().find(page_key(run, actor, first)).ok_or("native append page missing".into()))
            .expect("validated append/prune trace");
        #[cfg(feature = "clock-profile")]
        if sampled { log::info!("trace-append-plan {}", json(&[actor as usize, delta.removed, current.len(), plan.reads,
            plan.pages.writes.len(), plan.pages.removed.len()])); }
        let _ = plan.reads;
        for (id, change) in plan.changes { *self.changes.entry(id).or_default() += change; }
        for key in plan.pages.removed { ctx.db.sim_native_trace_page().key().delete(key); }
        for (exists, page) in plan.pages.writes {
            if exists { ctx.db.sim_native_trace_page().key().update(page); }
            else { ctx.db.sim_native_trace_page().insert(page); }
        }
        upsert!(ctx, sim_native_trace_head, key, plan.pages.head);
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn entry(cursor: u64) -> SimNativePagedTraceEntry {
        SimNativePagedTraceEntry {metadata: SimNativeTraceEntry {cursor, source: cursor + 700, tick: 2,
            location: 9, kind: "perception".into(), parents: vec![1, 1]}, body: cursor % 5 + 1}
    }
    fn experiences(entries: &[SimNativePagedTraceEntry]) -> Vec<Experience> {
        entries.iter().map(|e| {
            let m = &e.metadata;
            ExperienceRecord {cursor: m.cursor, source: m.source, tick: m.tick, location: m.location,
                kind: m.kind.clone(), parents: m.parents.clone(), data: simulation::participant::ExperienceData::load_with(
                    || Err("append planning must not read payloads".into()))}.into()
        }).collect()
    }
    fn compare(old: Vec<SimNativePagedTraceEntry>, remove: usize, new: Vec<SimNativePagedTraceEntry>) -> AppendPlan {
        let (head, old_pages) = pack("run", 4, old.clone());
        let previous = experiences(&old);let added = experiences(&new);
        assert!(eligible(&head, &previous, &added));
        let expected: Vec<_> = old[remove..].iter().chain(&new).cloned().collect();
        let current: Vec<_> = added.iter().zip(&new).map(|(experience, e)| ResolvedEntry {experience, body: e.body}).collect();
        let mut rows: BTreeMap<_, _> = old_pages.into_iter().map(|p| (p.first, p)).collect();
        let result = plan("run", 4, head, remove, &current, |first| rows.get(&first).cloned().ok_or("missing page".into())).unwrap();
        for key in &result.pages.removed {
            let first = rows.iter().find(|(_, p)| p.key == *key).unwrap().0.to_owned();rows.remove(&first);
        }
        for (exists, page) in &result.pages.writes {
            assert_eq!(*exists, rows.contains_key(&page.first));
            assert!(rows.get(&page.first) != Some(page), "no unchanged page writes");
            rows.insert(page.first, page.clone());
        }
        let (expected_head, expected_pages) = pack("run", 4, expected.clone());
        assert!(result.pages.head == expected_head);
        assert!(rows == expected_pages.into_iter().map(|p| (p.first, p)).collect());
        let mut counts = BTreeMap::new();
        for e in old { *counts.entry(e.body).or_default() -= 1i64; }
        for e in expected { *counts.entry(e.body).or_default() += 1i64; }
        counts.retain(|_, v| *v != 0);
        let mut actual = result.changes.clone();actual.retain(|_, v| *v != 0);assert_eq!(actual, counts);
        result
    }
    #[test]
    fn append_prune_matches_complete_page_and_reference_reconciliation() {
        for length in [0u64, 1, 31, 32, 255, 256, 300] {
            for added in [0u64, 1, 31, 32, 100, 256, 350] {
                let old: Vec<_> = (10..10 + length).map(entry).collect();
                let mut current = old.clone();let mut removed = 0usize;
                for cursor in 10 + length..10 + length + added {
                    current.push(entry(cursor));
                    if current.len() > 256 { current.remove(0);removed += 1; }
                }
                let remove = removed.min(old.len());
                let kept_new = current[old.len() - remove..].to_vec();
                compare(old, remove, kept_new);
            }
        }
        compare([65, 67, 2, 5, 34, 35].into_iter().map(entry).collect(), 3, vec![entry(99), entry(100)]);
    }
    #[test]
    fn single_append_and_prune_reads_only_boundary_pages() {
        let result = compare((10..266).map(entry).collect(), 1, vec![entry(266)]);
        assert_eq!(result.reads, 2);assert_eq!(result.pages.writes.len(), 2);assert_eq!(result.pages.removed.len(), 1);
        let result = compare((0..256).map(entry).collect(), 0, vec![entry(256)]);
        assert_eq!(result.reads, 0);assert_eq!(result.pages.writes.len(), 1);assert!(result.pages.removed.is_empty());
    }
    #[test]
    fn unusual_appends_fall_back_and_touched_corruption_fails() {
        let old: Vec<_> = (0..40).map(entry).collect();let (head, pages) = pack("run", 4, old.clone());
        let previous = experiences(&old);
        assert!(!eligible(&head, &previous, &experiences(&[entry(2)])));
        assert!(!eligible(&head, &previous, &experiences(&[entry(41), entry(40)])));
        let mut wrong = head.clone();wrong.pages.reverse();assert!(!eligible(&wrong, &previous, &[]));
        let mut bad = pages[0].clone();bad.actor = 99;
        assert!(plan("run", 4, head.clone(), 1, &[], |_| Ok(bad.clone())).is_err());
        assert!(plan("run", 4, head, 1, &[], |_| Err("missing page".into())).is_err());
    }
}
