//! Disposable parse caches, keyed by complete authoritative row contents.
//! Values contain no table loaders or transaction state. Copy-on-write detaches
//! mutations, and a miss always reads the supplied row rather than cached truth.
use simulation::{deferred::Deferred, scripting::Registry, Scenario};
use std::cell::RefCell;
use sha2::{Digest, Sha256};

const MAX_BYTES: usize = 1_048_576;
type Entry<T> = RefCell<Option<(String, Deferred<T>)>>;
thread_local! {
    static INITIAL: Entry<Scenario> = const { RefCell::new(None) };
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
    if digest.len() != 64 || !digest.bytes().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()) {
        return Err("invalid definition digest".into());
    }
    let key = format!("sha256:{digest}");
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
pub(super) fn initial_versioned(digest: Option<&str>, read: impl FnOnce() -> Result<String, String>) -> Result<Deferred<Scenario>, String> {
    INITIAL.with(|cache| versioned(cache, digest, read))
}
pub(super) fn scripts_versioned(digest: Option<&str>, read: impl FnOnce() -> Result<String, String>) -> Result<Deferred<Registry>, String> {
    SCRIPTS.with(|cache| versioned(cache, digest, read))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};

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
