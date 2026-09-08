//! Private immutable last-observed catalogs. References belong to controller
//! rows; personal evidence and exports retain their original JSON values.
use super::*;

const PREFIX: &str = "sao-controller-catalog-v1:";

#[derive(Clone, PartialEq)]
#[spacetimedb::table(accessor = sim_native_controller_catalog)]
pub struct SimNativeControllerCatalog {
    #[primary_key]
    pub key: String,
    #[index(btree)]
    pub run: String,
    pub references: u64,
    pub body: String,
}

fn identity(run: &str, body: &str) -> String {
    super::super::storage_codec::blob_key(run, None, "controller-catalog-v1", body)
}

fn reference(value: &str) -> Option<&str> { value.strip_prefix(PREFIX) }

fn validated_body(run: &str, expected: &str, row: SimNativeControllerCatalog) -> Result<String, String> {
    if row.run != run || row.key != expected || row.references == 0
        || identity(run, &row.body) != expected {
        return Err("controller catalog identity mismatch".into());
    }
    Ok(row.body)
}

pub(super) fn resolve(run: &str, value: &str,
    fetch: impl FnOnce(&str) -> Result<SimNativeControllerCatalog, String>)
    -> Result<Option<simulation::participant::ExperienceData>, String> {
    match reference(value) {
        Some(id) => parse(&validated_body(run, id, fetch(id)?)?),
        None => parse(value), // Existing databases upgrade individual rows on save.
    }
}

pub(super) fn valid_reference(value: &str) -> bool {
    reference(value).is_some_and(|id| id.len() == 64 && id.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)))
}

/// The hot row establishes which non-null catalog is retained. Body identity is
/// checked on first use, like the other transaction-local cold evidence paths.
/// Serialization and physics cannot consume a missing or corrupt body.
pub(super) fn deferred(run: &str, value: &str,
    fetch: impl Fn(&str) -> Result<SimNativeControllerCatalog, String> + Send + Sync + 'static)
    -> Result<Option<simulation::participant::ExperienceData>, String> {
    let Some(id) = reference(value) else { return parse(value); };
    if !valid_reference(value) { return Err("invalid controller catalog reference".into()); }
    let (run, id) = (run.to_owned(), id.to_owned());
    Ok(Some(simulation::participant::ExperienceData::load_with(move || {
        let body = validated_body(&run, &id, fetch(&id)?)?;
        let raw = serde_json::value::RawValue::from_string(body).map_err(|e|e.to_string())?;
        if raw.get().trim() == "null" { return Err("null controller catalog reference".into()); }
        Ok(raw)
    })))
}

/// Accumulate reference changes across a transaction. A crowd switching to the
/// same catalog reads/writes each immutable row once, rather than once per actor.
#[derive(Default)]
pub(super) struct Writes {
    changes: BTreeMap<String, i64>,
    // Both maps own the same immutable allocation. One transaction retains at
    // most one body per distinct run/byte string, as the writer already did.
    bodies: BTreeMap<String, Arc<String>>,
    identities: BTreeMap<String, BTreeMap<Arc<String>, String>>,
    #[cfg(feature = "clock-profile")]
    identity_counts: [usize; 4], // calls, hashes, input bytes, hashed bytes
}
impl Writes {
    pub(super) fn replace(&mut self, run: &str, old: Option<&str>, body: String) -> String {
        let value = if body == "null" { body } else {
            #[cfg(feature = "clock-profile")]
            { self.identity_counts[0] += 1; self.identity_counts[2] += body.len(); }
            let entries = self.identities.entry(run.into()).or_default();
            let id = match entries.get(&body) {
                Some(id) => id.clone(),
                None => {
                    let id = identity(run, &body);
                    #[cfg(feature = "clock-profile")]
                    { self.identity_counts[1] += 1; self.identity_counts[3] += body.len(); }
                    let body = Arc::new(body);
                    entries.insert(body.clone(), id.clone());
                    self.bodies.entry(id.clone()).or_insert(body);
                    id
                }
            };
            format!("{PREFIX}{id}")
        };
        if old != Some(value.as_str()) {
            if let Some(id) = old.and_then(reference) { *self.changes.entry(id.into()).or_default() -= 1; }
            if let Some(id) = reference(&value) { *self.changes.entry(id.into()).or_default() += 1; }
        }
        value
    }

    pub(super) fn finish(self, ctx: &ReducerContext, run: &str) {
        #[cfg(feature = "clock-profile")]
        log::info!("catalog-save-identities {}", json(&self.identity_counts));
        for (id, delta) in self.changes {
            if delta == 0 { continue; }
            let old = ctx.db.sim_native_controller_catalog().key().find(&id);
            let existed = old.is_some();
            let row = reconcile(run, &id, old, self.bodies.get(&id).map(Arc::as_ref), delta)
                .expect("validated controller catalog references");
            match row {
                Some(row) if existed => { ctx.db.sim_native_controller_catalog().key().update(row); }
                Some(row) => { ctx.db.sim_native_controller_catalog().insert(row); }
                None => { ctx.db.sim_native_controller_catalog().key().delete(id); }
            }
        }
    }
}

fn reconcile(run: &str, id: &str, old: Option<SimNativeControllerCatalog>,
    body: Option<&String>, delta: i64) -> Result<Option<SimNativeControllerCatalog>, String> {
    let mut row = match old {
        Some(row) => {
            if row.run != run || row.key != id || identity(run, &row.body) != id
                || body.is_some_and(|body| body != &row.body) {
                return Err("controller catalog write identity mismatch".into());
            }
            row
        }
        None => SimNativeControllerCatalog { key: id.into(), run: run.into(), references: 0,
            body: body.cloned().ok_or("missing new controller catalog")? },
    };
    row.references = row.references.checked_add_signed(delta).ok_or("controller catalog reference overflow")?;
    Ok((row.references != 0).then_some(row))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deferred_catalog_fetches_once_on_use_and_preserves_failures() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        let body = "{\"people\":[{\"id\":1}]}";
        let id = identity("run", body);
        let reference = format!("{PREFIX}{id}");
        let row = SimNativeControllerCatalog {key:id,run:"run".into(),references:2,body:body.into()};
        let calls = Arc::new(AtomicUsize::new(0));
        let seen = calls.clone();
        let source = row.clone();
        let payload = deferred("run", &reference, move |_| {
            seen.fetch_add(1,Ordering::SeqCst); Ok(source.clone())
        }).unwrap().unwrap();
        let snapshot = payload.clone();
        assert!(payload.same_snapshot(&snapshot));
        assert_eq!(calls.load(Ordering::SeqCst),0);
        assert_eq!(json(&payload),body);
        assert_eq!(json(&snapshot),body);
        assert_eq!(calls.load(Ordering::SeqCst),1);
        for kind in ["missing","wrong run","changed body","zero references","null"] {
            let mut corrupt = row.clone();
            match kind {
                "wrong run" => corrupt.run = "other".into(),
                "changed body" => corrupt.body.push(' '),
                "zero references" => corrupt.references = 0,
                "null" => { corrupt.body="null".into();corrupt.key=identity("run","null"); },
                _ => (),
            }
            let reference = format!("{PREFIX}{}",corrupt.key);
            let payload = deferred("run", &reference, move |_| {
                if kind=="missing" {Err("missing body".into())} else {Ok(corrupt.clone())}
            }).unwrap().unwrap();
            assert!(serde_json::to_string(&payload).is_err(),"{kind} cannot serialize as an authoritative value");
            assert!(serde_json::to_string(&payload.clone()).is_err(),"{kind} failure remains retained");
        }
        assert!(deferred("run", &format!("{PREFIX}bad"), |_|panic!("invalid reference is not fetched")).is_err());
        assert!(deferred("run", "null", |_|panic!("inline null is not fetched")).unwrap().is_none());
        let inline=deferred("run", body, |_|panic!("inline value is not fetched")).unwrap().unwrap();
        assert_eq!(json(&inline),body);
    }

    #[test]
    fn repeated_catalog_saves_preserve_scoped_identity_and_net_references() {
        let body = format!("{{\"people\":\"{}\"}}", "catalog".repeat(3000));
        let variants = [body.clone(), format!(" {body} "), "null".into(), "{\"people\":[]}".into()];
        let mut writes = Writes::default();
        let mut expected = BTreeMap::<String, i64>::new();
        let mut current = BTreeMap::<(String, usize), String>::new();
        for turn in 0..1200 {
            let run = if turn % 5 == 0 { "other" } else { "run" };
            let actor = turn % 200;
            let body = &variants[(turn / 200) % variants.len()];
            let old = current.get(&(run.into(), actor));
            let value = writes.replace(run, old.map(String::as_str), body.clone());
            let reference_value = if body == "null" { body.clone() }
                else { format!("{PREFIX}{}", identity(run, body)) };
            assert_eq!(value, reference_value);
            if old != Some(&reference_value) {
                if let Some(id) = old.and_then(|s|reference(s)) { *expected.entry(id.into()).or_default() -= 1; }
                if let Some(id) = reference(&reference_value) { *expected.entry(id.into()).or_default() += 1; }
            }
            current.insert((run.into(), actor), reference_value);
        }
        assert_eq!(writes.changes, expected);
        let mut actual_owners = BTreeMap::<String, u64>::new();
        for value in current.values() {
            if let Some(id) = reference(value) { *actual_owners.entry(id.into()).or_default() += 1; }
        }
        for (id, delta) in &writes.changes {
            assert_eq!(*delta as u64, actual_owners.get(id).copied().unwrap_or(0));
        }
        assert_eq!(writes.bodies.len(), 6); // Three non-null byte strings in two runs.
        assert_eq!(writes.identities.len(), 2);
        for (run, entries) in &writes.identities {
            assert_eq!(entries.len(), 3);
            for (body, id) in entries {
                assert_eq!(*id, identity(run, body));
                assert!(Arc::ptr_eq(body, &writes.bodies[id]));
            }
        }
        assert!(Writes::default().identities.is_empty());
    }

    #[test]
    fn references_retain_exact_bytes_and_release_last_owner() {
        let mut writes = Writes::default();
        let first = writes.replace("run", Some("null"), "{\"people\":[1,2]}".into());
        assert_eq!(first, writes.replace("run", None, "{\"people\":[1,2]}".into()));
        let id = reference(&first).unwrap();
        let row = reconcile("run", id, None, writes.bodies.get(id).map(Arc::as_ref), writes.changes[id]).unwrap().unwrap();
        assert_eq!(row.references, 2);
        assert_eq!(json(&resolve("run", &first, |_| Ok(row.clone())).unwrap().unwrap()), row.body);
        assert!(resolve("other", &first, |_| Ok(row.clone())).is_err());
        let mut corrupt = row.clone(); corrupt.body.push(' ');
        assert!(resolve("run", &first, |_| Ok(corrupt)).is_err());
        assert!(resolve("run", &first, |_| Err("missing".into())).is_err());
        let row = reconcile("run", id, Some(row), None, -1).unwrap().unwrap();
        assert_eq!(row.references, 1);
        assert!(reconcile("run", id, Some(row.clone()), None, -1).unwrap().is_none());
        assert!(reconcile("run", id, Some(row), None, -2).is_err());
        assert!(resolve("run", "null", |_| panic!("inline read")).unwrap().is_none());
        assert!(resolve("run", "{\"legacy\":true}", |_| panic!("inline read")).unwrap().is_some());
        assert_ne!(first, writes.replace("run", None, "{ \"people\": [1,2] }".into()));
        assert_ne!(first, writes.replace("other", None, "{\"people\":[1,2]}".into()));
    }
}
