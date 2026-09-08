//! Personal evidence retains its ordinary ordered JSON array. An append/prune
//! journal proves a narrow change relative to a strongly owned snapshot; general
//! mutable access invalidates that proof before exposing the records.
use super::Experience;
use crate::deferred::Deferred;
use serde::{Deserialize, Serialize};
use std::{fmt, ops::{Deref, DerefMut}, sync::Arc};

#[derive(Clone)]
struct State {
    records: Deferred<Vec<Experience>>,
    append: Option<Append>,
}
#[derive(Clone)]
struct Append {
    before: Arc<State>,
    removed: usize,
    original_len: usize,
}
#[derive(Clone)]
pub struct Trace(Arc<State>);

pub struct AppendDelta<'a> {
    pub removed: usize,
    pub appended: &'a [Experience],
}
impl Trace {
    pub fn load_with(read: impl Fn() -> Result<Vec<Experience>, String> + Send + Sync + 'static) -> Self {
        Deferred::load_with(read).into()
    }
    pub fn try_get(&self) -> Result<&Vec<Experience>, String> { self.0.records.try_get() }
    pub fn is_loaded(&self) -> bool { self.0.records.is_loaded() }
    pub fn same_snapshot(&self, other: &Self) -> bool { Arc::ptr_eq(&self.0, &other.0) }

    /// Preserve the historical append-then-remove-one rule, including an
    /// oversized imported trace. The journal never retains discarded new data.
    pub fn append_retaining_one(&mut self, record: Experience, limit: usize) {
        if self.0.append.is_none() {
            let original_len = self.len();
            let before = self.0.clone();
            Arc::make_mut(&mut self.0).append = Some(Append { before, removed: 0, original_len });
        }
        let state = Arc::make_mut(&mut self.0);
        state.records.push(record);
        if state.records.len() > limit {
            state.records.remove(0);
            let append = state.append.as_mut().unwrap();
            if append.removed < append.original_len { append.removed += 1; }
        }
    }

    /// A storage writer may use this only with the snapshot it loaded in the
    /// current transaction. Serialization or a general edit cannot forge it.
    pub fn appended_since(&self, previous: &Self) -> Option<AppendDelta<'_>> {
        let append = self.0.append.as_ref()?;
        if !Arc::ptr_eq(&append.before, &previous.0) { return None; }
        let start = append.original_len.checked_sub(append.removed)?;
        Some(AppendDelta { removed: append.removed, appended: self.try_get().ok()?.get(start..)? })
    }
}
impl From<Vec<Experience>> for Trace {
    fn from(records: Vec<Experience>) -> Self { Deferred::from(records).into() }
}
impl From<Deferred<Vec<Experience>>> for Trace {
    fn from(records: Deferred<Vec<Experience>>) -> Self { Self(Arc::new(State { records, append: None })) }
}
impl Default for Trace { fn default() -> Self { Vec::new().into() } }
impl Deref for Trace {
    type Target = Vec<Experience>;
    fn deref(&self) -> &Self::Target { self.try_get().expect("invalid deferred authoritative trace") }
}
impl DerefMut for Trace {
    fn deref_mut(&mut self) -> &mut Self::Target {
        let state = Arc::make_mut(&mut self.0);
        state.append = None;
        &mut state.records
    }
}
impl fmt::Debug for Trace {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { self.0.records.fmt(f) }
}
impl Serialize for Trace {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        self.0.records.serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for Trace {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Vec::<Experience>::deserialize(deserializer).map(Into::into)
    }
}
impl<'a> IntoIterator for &'a Trace {
    type Item = &'a Experience;
    type IntoIter = std::slice::Iter<'a, Experience>;
    fn into_iter(self) -> Self::IntoIter { self.iter() }
}
impl<'a> IntoIterator for &'a mut Trace {
    type Item = &'a mut Experience;
    type IntoIter = std::slice::IterMut<'a, Experience>;
    fn into_iter(self) -> Self::IntoIter { self.iter_mut() }
}
impl IntoIterator for Trace {
    type Item = Experience;
    type IntoIter = std::vec::IntoIter<Experience>;
    fn into_iter(self) -> Self::IntoIter { self.deref().clone().into_iter() }
}
impl FromIterator<Experience> for Trace {
    fn from_iter<I: IntoIterator<Item = Experience>>(iter: I) -> Self { Vec::from_iter(iter).into() }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::participant::{ExperienceRecord, ExperienceData};
    use std::sync::atomic::{AtomicUsize, Ordering};
    fn record(cursor: u64) -> Experience {
        ExperienceRecord {cursor, source: cursor + 10, tick: 1, location: 0,
            kind: "perception".into(), parents: vec![3, 3],
            data: serde_json::json!({"n": cursor}).into()}.into()
    }
    fn equal(a: &Trace, b: &[Experience]) {
        assert_eq!(serde_json::to_value(a).unwrap(), serde_json::to_value(b).unwrap());
    }
    #[test]
    fn append_journal_matches_original_retention_and_preserves_snapshots() {
        for length in [0, 1, 31, 32, 255, 256, 300] {
            let original: Vec<_> = (0..length).map(record).collect();
            let before: Trace = original.clone().into();
            let mut current = before.clone();
            let mut reference = original.clone();
            for n in 0..350 {
                let next = record(length + n);
                reference.push(next.clone());
                if reference.len() > 256 { reference.remove(0); }
                current.append_retaining_one(next, 256);
                equal(&current, &reference);
                equal(&before, &original);
                let delta = current.appended_since(&before).unwrap();
                let reconstructed: Vec<_> = original[delta.removed..].iter().chain(delta.appended).cloned().collect();
                equal(&current, &reconstructed);
                assert_eq!(current.len(), length.max(256).min(length + n + 1) as usize);
            }
            let roundtrip: Trace = serde_json::from_value(serde_json::to_value(&current).unwrap()).unwrap();
            assert!(roundtrip.appended_since(&before).is_none());
        }
    }
    #[test]
    fn general_edits_revoke_append_proof_before_detaching_records() {
        let before: Trace = (0..40).map(record).collect();
        let mut appended = before.clone();
        appended.append_retaining_one(record(40), 256);
        assert!(appended.appended_since(&before).is_some());
        for edit in 0..6 {
            let mut changed = appended.clone();
            match edit {
                0 => changed[0].source = 900,
                1 => changed[1].parents.push(42),
                2 => changed[2].data = serde_json::json!({"edited":true}).into(),
                3 => changed.swap(0, 20),
                4 => { changed.remove(0); },
                _ => changed.clear(),
            }
            assert!(changed.appended_since(&before).is_none());
            changed.append_retaining_one(record(901), 256);
            assert!(changed.appended_since(&before).is_none());
            equal(&before, &(0..40).map(record).collect::<Vec<_>>());
            equal(&appended, &(0..41).map(record).collect::<Vec<_>>());
        }
    }
    #[test]
    fn journal_does_not_load_payloads_or_retain_a_reader_cycle() {
        let owner = Arc::new(());let weak = Arc::downgrade(&owner);
        let reads = Arc::new(AtomicUsize::new(0));let seen = reads.clone();
        let before = Trace::load_with(move || {
            let _ = &owner;seen.fetch_add(1, Ordering::SeqCst);
            let mut item = record(1);
            item.data = ExperienceData::load_with(|| Err("unconsumed historical payload".into()));
            Ok(vec![item])
        });
        let mut current = before.clone();assert!(!current.is_loaded());
        current.append_retaining_one(record(2), 1);
        assert_eq!(reads.load(Ordering::SeqCst), 1);
        let delta = current.appended_since(&before).unwrap();
        assert_eq!(delta.removed, 1);assert_eq!(delta.appended.len(), 1);
        assert!(serde_json::to_value(&before).is_err());
        equal(&current, &[record(2)]);
        drop(before);drop(current);assert!(weak.upgrade().is_none());
    }
}
