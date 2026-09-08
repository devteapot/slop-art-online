//! Disposable parse caches, keyed by complete authoritative row contents.
//! Values contain no table loaders or transaction state. Copy-on-write detaches
//! mutations, and a miss always reads the supplied row rather than cached truth.
use simulation::{deferred::Deferred, scripting::Registry, Scenario};
use std::cell::RefCell;
use std::thread::LocalKey;
use sha2::{Digest, Sha256};

const MAX_BYTES: usize = 1_048_576;
type Entry<T> = RefCell<Option<(String, Deferred<T>)>>;
thread_local! {
    static INITIAL: Entry<Scenario> = const { RefCell::new(None) };
    static ADMISSION: Entry<Scenario> = const { RefCell::new(None) };
    static SCRIPTS: Entry<Registry> = const { RefCell::new(None) };
}

fn get<T: serde::de::DeserializeOwned>(cache: &Entry<T>, body: &str) -> Result<Deferred<T>, String> {
    if let Some((key, value)) = cache.borrow().as_ref() {
        if key == body { return Ok(value.clone()); }
    }
    let value: Deferred<T> = serde_json::from_str(body)
        .map_err(|e| format!("invalid native component: {e}"))?;
    if body.len() <= MAX_BYTES {
        *cache.borrow_mut() = Some((body.to_owned(), value.clone()));
    }
    Ok(value)
}

pub(super) fn initial(body: &str) -> Result<Deferred<Scenario>, String> {
    INITIAL.with(|cache| get(cache, body))
}
pub(super) fn scripts(body: &str) -> Result<Deferred<Registry>, String> {
    SCRIPTS.with(|cache| get(cache, body))
}

fn versioned<T: serde::de::DeserializeOwned>(cache: &Entry<T>, digest: Option<&str>,
    read: impl FnOnce() -> Result<String, String>) -> Result<Deferred<T>, String> {
    let Some(digest) = digest else { return get(cache, &read()?); };
    let key = digest_key(digest)?;
    if let Some((previous, value)) = cache.borrow().as_ref() {
        if previous == &key { return Ok(value.clone()); }
    }
    let body = read()?;
    if format!("{:x}", Sha256::digest(body.as_bytes())) != digest {
        return Err("definition digest mismatch".into());
    }
    let value: Deferred<T> = serde_json::from_str(&body).map_err(|e| format!("invalid native component: {e}"))?;
    if body.len() <= MAX_BYTES { *cache.borrow_mut() = Some((key, value.clone())); }
    Ok(value)
}
fn digest_key(digest: &str) -> Result<String, String> {
    if digest.len() != 64 || !digest.bytes().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()) {
        return Err("invalid definition digest".into());
    }
    Ok(format!("sha256:{digest}"))
}
pub(super) fn initial_versioned(digest: Option<&str>, read: impl FnOnce() -> Result<String, String>) -> Result<Deferred<Scenario>, String> {
    super::measured("definition.initial", || INITIAL.with(|cache| versioned(cache, digest, read)))
}
pub(super) fn scripts_versioned(digest: Option<&str>, read: impl FnOnce() -> Result<String, String>) -> Result<Deferred<Registry>, String> {
    super::measured("definition.scripts", || SCRIPTS.with(|cache| versioned(cache, digest, read)))
}

/// A local transaction may never consume the authored seed. Keep its body read,
/// digest verification and decoding inside that transaction's first use. Only
/// fully parsed, loader-free values enter the disposable bounded cache.
pub(super) fn initial_deferred(digest: Option<String>,
    read: impl Fn() -> Result<String, String> + Send + Sync + 'static,
) -> Result<Deferred<Scenario>, String> {
    deferred_initial(&INITIAL, "definition.initial", digest, read)
}
pub(super) fn admission_deferred(digest: String,
    read: impl Fn() -> Result<String, String> + Send + Sync + 'static,
) -> Result<Deferred<Scenario>, String> {
    deferred_initial(&ADMISSION, "definition.admission", Some(digest), read)
}
fn deferred_initial(cache: &'static LocalKey<Entry<Scenario>>, span: &'static str, digest: Option<String>,
    read: impl Fn() -> Result<String, String> + Send + Sync + 'static,
) -> Result<Deferred<Scenario>, String> {
    let key = digest.as_deref().map(digest_key).transpose()?;
    if let Some(key) = &key {
        if let Some(value) = cache.with(|cache| cache.borrow().as_ref()
            .filter(|(previous, _)| previous == key).map(|(_, value)| value.clone())) {
            return Ok(value);
        }
    }
    #[cfg(feature = "clock-profile")]
    log::info!("definition-deferred {span}");
    Ok(Deferred::load_with(move || super::measured(span, || {
        let body = read()?;
        if digest.as_ref().is_some_and(|digest| format!("{:x}", Sha256::digest(body.as_bytes())) != *digest) {
            return Err("definition digest mismatch".into());
        }
        let value: Scenario = serde_json::from_str(&body)
            .map_err(|e| format!("invalid native component: {e}"))?;
        if body.len() <= MAX_BYTES {
            // The bounded cold miss copies parsed data once. Never cache the
            // Deferred cell whose loader captures a database transaction.
            cache.with(|cache| *cache.borrow_mut() = Some((key.clone().unwrap_or(body), value.clone().into())));
        }
        Ok(value)
    })))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};
    use std::sync::{Arc, atomic::{AtomicUsize, Ordering}};

    fn seed_body() -> String {
        include_str!("../../../../../scenarios/survival.json").into()
    }
    #[test]
    fn admission_and_full_definitions_do_not_evict_each_other() {
        INITIAL.with(|cache| *cache.borrow_mut() = None);
        ADMISSION.with(|cache| *cache.borrow_mut() = None);
        let body = seed_body();
        let full_digest = format!("{:x}", Sha256::digest(body.as_bytes()));
        let full = initial_deferred(Some(full_digest.clone()), move || Ok(body.clone())).unwrap();
        let projection = simulation::participant_transaction::action_admission_initial(&full);
        let body = serde_json::to_string(&projection).unwrap();
        let projected_digest = format!("{:x}", Sha256::digest(body.as_bytes()));
        let projected = admission_deferred(projected_digest.clone(), move || Ok(body.clone())).unwrap();
        assert!(projected.players.is_empty());
        assert_eq!(initial_deferred(Some(full_digest), || panic!("admission evicted full seed")).unwrap().players.len(), 3);
        assert!(admission_deferred(projected_digest, || panic!("full seed evicted admission")).unwrap().players.is_empty());
    }
    #[test]
    fn unused_large_initial_definition_is_not_read_or_cached() {
        INITIAL.with(|cache| *cache.borrow_mut() = None);
        let mut seed: Scenario = serde_json::from_str(&seed_body()).unwrap();
        seed.name = "x".repeat(MAX_BYTES);
        let body = serde_json::to_string(&seed).unwrap();
        let digest = format!("{:x}", Sha256::digest(body.as_bytes()));
        let reads = Arc::new(AtomicUsize::new(0));
        let count = reads.clone();
        let lazy = initial_deferred(Some(digest), move || {
            count.fetch_add(1, Ordering::Relaxed); Ok(body.clone())
        }).unwrap();
        let snapshot = lazy.clone();
        assert_eq!(reads.load(Ordering::Relaxed), 0);
        assert!(!lazy.is_loaded());
        assert_eq!(serde_json::to_value(&lazy).unwrap(), serde_json::to_value(&seed).unwrap());
        assert_eq!(snapshot.name.len(), MAX_BYTES);
        assert_eq!(reads.load(Ordering::Relaxed), 1);
        INITIAL.with(|cache| assert!(cache.borrow().is_none()));
    }
    #[test]
    fn initial_cache_keeps_parsed_data_without_transaction_loader() {
        INITIAL.with(|cache| *cache.borrow_mut() = None);
        let body = seed_body();
        let digest = format!("{:x}", Sha256::digest(body.as_bytes()));
        let owner = Arc::new(());
        let weak = Arc::downgrade(&owner);
        let lazy = initial_deferred(Some(digest.clone()), move || {
            let _ = &owner; Ok(body.clone())
        }).unwrap();
        let name = lazy.name.clone();
        let mut cached = initial_deferred(Some(digest.clone()), || panic!("cache hit read the table")).unwrap();
        assert_eq!(cached.name, name);
        cached.name = "changed locally".into();
        assert_eq!(initial_deferred(Some(digest), || panic!("cache hit read the table")).unwrap().name, name);
        drop(lazy);
        assert!(weak.upgrade().is_none(), "cache must not retain a transaction loader");
    }
    #[test]
    fn deferred_initial_validates_consumed_rows_and_preserves_failures() {
        INITIAL.with(|cache| *cache.borrow_mut() = None);
        assert!(initial_deferred(Some("bad".into()), || panic!("invalid key read a table")).is_err());
        let digest = format!("{:x}", Sha256::digest(seed_body()));
        let wrong = initial_deferred(Some(digest), || Ok("{}".into())).unwrap();
        assert_eq!(wrong.try_get().unwrap_err(), "definition digest mismatch");
        assert!(serde_json::to_string(&wrong).is_err(), "export cannot omit invalid deferred data");
        let missing = initial_deferred(None, || Err("native initial missing".into())).unwrap();
        assert_eq!(missing.try_get().unwrap_err(), "native initial missing");
        let invalid = initial_deferred(None, || Ok("not JSON".into())).unwrap();
        assert!(invalid.try_get().is_err());
        let legacy = initial_deferred(None, || Ok(seed_body())).unwrap();
        assert_eq!(legacy.players.len(), 3);
        INITIAL.with(|cache| assert!(cache.borrow().as_ref().unwrap().0.starts_with('{')));
    }

    #[test]
    fn exact_content_and_copy_on_write_preserve_authority() {
        let cache: Entry<Value> = RefCell::new(None);
        let first = get(&cache, r#"{"v":[1]}"#).unwrap();
        let mut transaction = get(&cache, r#"{"v":[1]}"#).unwrap();
        assert!(first.same_snapshot(&transaction));
        transaction["v"][0] = json!(9);
        assert_eq!(*get(&cache, r#"{"v":[1]}"#).unwrap(), json!({"v":[1]}));
        assert_eq!(*get(&cache, r#"{"v":[2]}"#).unwrap(), json!({"v":[2]}));
        assert_eq!(*first, json!({"v":[1]}));
        assert!(get(&cache, "invalid").is_err());
        assert_eq!(*get(&cache, r#"{"v":[2]}"#).unwrap(), json!({"v":[2]}));
    }

    #[test]
    fn oversized_definitions_are_valid_but_not_retained() {
        let cache: Entry<String> = RefCell::new(None);
        get(&cache, "\"small\"").unwrap();
        let body = serde_json::to_string(&"x".repeat(MAX_BYTES)).unwrap();
        assert_eq!(get(&cache, &body).unwrap().len(), MAX_BYTES);
        assert_eq!(cache.borrow().as_ref().unwrap().0, "\"small\"");
    }
    #[test]
    fn versioned_reads_validate_misses_and_never_reload_matching_content() {
        let cache: Entry<Value> = RefCell::new(None);
        let body = "[1]";
        let digest = format!("{:x}", Sha256::digest(body));
        let original = versioned(&cache, Some(&digest), || Ok(body.into())).unwrap();
        let mut transaction = versioned(&cache, Some(&digest), || panic!("cache hit read a body")).unwrap();
        transaction[0] = json!(2);
        assert_eq!(*original, json!([1]));
        let changed = format!("{:x}", Sha256::digest("[3]"));
        assert!(versioned(&cache, Some(&changed), || Ok(body.into())).is_err());
        assert_eq!(*versioned(&cache, Some(&changed), || Ok("[3]".into())).unwrap(), json!([3]));
        assert_eq!(*versioned(&cache, None, || Ok("[4]".into())).unwrap(), json!([4]));
        assert!(versioned(&cache, Some("bad"), || Ok(body.into())).is_err());
    }
}
