//! Transaction-local, copy-on-write values. Storage may supply an exact loader;
//! the simulation sees the same typed value and serialized shape as eager input.
//! Never retain a storage-backed value beyond its owning transaction.
use serde::{Deserialize, Serialize};
use std::{fmt, ops::{Deref, DerefMut}, sync::{Arc, OnceLock}};

type Loader<T> = Box<dyn Fn() -> Result<T, String> + Send + Sync>;
struct Inner<T> {
    value: OnceLock<Result<T, String>>,
    loader: Option<Loader<T>>,
}
pub struct Deferred<T>(Arc<Inner<T>>);

impl<T> Clone for Deferred<T> {
    fn clone(&self) -> Self { Self(self.0.clone()) }
}
impl<T> Deferred<T> {
    pub fn load_with(loader: impl Fn() -> Result<T, String> + Send + Sync + 'static) -> Self {
        Self(Arc::new(Inner { value: OnceLock::new(), loader: Some(Box::new(loader)) }))
    }
    pub fn try_get(&self) -> Result<&T, String> {
        self.0.value.get_or_init(|| (self.0.loader.as_ref().expect("deferred loader"))())
            .as_ref().map_err(Clone::clone)
    }
    /// Equality of retained values within one transaction, not a durable key.
    pub fn same_snapshot(&self, other: &Self) -> bool { Arc::ptr_eq(&self.0, &other.0) }
    pub fn is_loaded(&self) -> bool { self.0.value.get().is_some() }
}
impl<T> From<T> for Deferred<T> {
    fn from(value: T) -> Self {
        Self(Arc::new(Inner { value: OnceLock::from(Ok(value)), loader: None }))
    }
}
impl<T: Default> Default for Deferred<T> {
    fn default() -> Self { T::default().into() }
}
impl<T> Deref for Deferred<T> {
    type Target = T;
    fn deref(&self) -> &T { self.try_get().expect("invalid deferred authoritative state") }
}
impl<T: Clone> DerefMut for Deferred<T> {
    fn deref_mut(&mut self) -> &mut T {
        // Resolve before replacing the cell, and detach before any mutation.
        // A retained pre-action snapshot must continue to see its original value.
        if Arc::strong_count(&self.0) != 1 || self.0.loader.is_some() {
            let value: T = self.try_get().expect("invalid deferred authoritative state").clone();
            *self = Self::from(value);
        }
        Arc::get_mut(&mut self.0).unwrap().value.get_mut().unwrap().as_mut()
            .expect("invalid deferred authoritative state")
    }
}
impl<T: fmt::Debug> fmt::Debug for Deferred<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.0.value.get() {
            Some(value) => value.fmt(f),
            None => f.write_str("<deferred>"),
        }
    }
}
impl<T: PartialEq> PartialEq for Deferred<T> {
    fn eq(&self, other: &Self) -> bool { self.same_snapshot(other) || **self == **other }
}
impl<T: Eq> Eq for Deferred<T> {}
impl<T: Serialize> Serialize for Deferred<T> {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        self.try_get().map_err(serde::ser::Error::custom)?.serialize(serializer)
    }
}
impl<'de, T: Deserialize<'de>> Deserialize<'de> for Deferred<T> {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        T::deserialize(deserializer).map(Self::from)
    }
}
impl<'a, T> IntoIterator for &'a Deferred<T> where &'a T: IntoIterator {
    type Item = <&'a T as IntoIterator>::Item;
    type IntoIter = <&'a T as IntoIterator>::IntoIter;
    fn into_iter(self) -> Self::IntoIter { self.deref().into_iter() }
}
impl<'a, T: Clone> IntoIterator for &'a mut Deferred<T> where &'a mut T: IntoIterator {
    type Item = <&'a mut T as IntoIterator>::Item;
    type IntoIter = <&'a mut T as IntoIterator>::IntoIter;
    fn into_iter(self) -> Self::IntoIter { self.deref_mut().into_iter() }
}
impl<T: Clone + IntoIterator> IntoIterator for Deferred<T> {
    type Item = T::Item;
    type IntoIter = T::IntoIter;
    fn into_iter(self) -> Self::IntoIter { self.deref().clone().into_iter() }
}
impl<A, T: FromIterator<A>> FromIterator<A> for Deferred<T> {
    fn from_iter<I: IntoIterator<Item = A>>(iter: I) -> Self { T::from_iter(iter).into() }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn lazy_load_is_shared_but_mutation_and_failures_are_isolated() {
        let calls = Arc::new(AtomicUsize::new(0));
        let seen = calls.clone();
        let original = Deferred::load_with(move || {
            seen.fetch_add(1, Ordering::SeqCst);
            Ok(vec![1, 2])
        });
        let mut candidate = original.clone();
        assert!(!original.is_loaded());
        assert!(candidate.same_snapshot(&original));
        candidate.push(3);
        assert_eq!(*original, vec![1, 2]);
        assert_eq!(*candidate, vec![1, 2, 3]);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(serde_json::to_string(&original).unwrap(), "[1,2]");
        let missing = Deferred::<Vec<u32>>::load_with(|| Err("missing scoped record".into()));
        assert!(serde_json::to_value(&missing).is_err());
        assert!(missing.try_get().is_err());
    }
}
