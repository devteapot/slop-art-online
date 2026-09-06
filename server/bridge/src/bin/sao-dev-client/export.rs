//! Incremental local audit export from explicit owner snapshots and SQL audit
//! reads; exports never advance the world or supply participant observations.
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::value::RawValue;
use std::{
    fs::File,
    io::{BufWriter, Write},
    path::Path,
};

#[derive(Deserialize)]
struct SqlResult<T> {
    rows: Vec<T>,
}

/// Decode the SQL envelope once, directly into the requested row shape. Large
/// JSON strings inside rows remain strings instead of being cloned via Value.
pub(super) fn rows<T: DeserializeOwned>(text: &str) -> Result<Vec<T>, String> {
    let mut results: Vec<SqlResult<T>> =
        serde_json::from_str(text).map_err(|_| "invalid database reply")?;
    if results.len() != 1 {
        return Err("expected one SQL result".into());
    }
    Ok(results.pop().unwrap().rows)
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
struct Revision {
    run: String,
    next_event: u64,
    timing: Timing,
    stopped: bool,
}
#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
struct Timing {
    updates: u64,
}
#[derive(Deserialize)]
struct EventHeader {
    id: u64,
    run: String,
}

#[derive(Default)]
pub(super) struct Export {
    world: Option<simulation::World>,
    revision: Option<Revision>,
    published: Option<Revision>,
    // Events are immutable authority JSON. Retaining their original encoding
    // avoids reparsing and expanding the entire history on every export.
    events: Vec<Box<RawValue>>,
    next_event: u64,
}
impl Export {
    /// Parse only the revision header on unchanged reads; parse the actual World
    /// once when it changes. Keep the last World available for enrollment retries.
    pub(super) fn prepare(&mut self, run: &str, text: &str) -> Result<(), String> {
        let revision: Revision = serde_json::from_str(text).map_err(|_| "invalid world header")?;
        if revision.run != run || revision.next_event == 0 {
            return Err("world identity or event cursor invalid".into());
        }
        if self.next_event > revision.next_event {
            return Err("authority event history moved backwards".into());
        }
        if self.revision.as_ref() != Some(&revision) {
            let world = serde_json::from_str(text).map_err(|_| "invalid world")?;
            self.world = Some(world);
            self.revision = Some(revision);
        }
        Ok(())
    }
    pub(super) fn world(&self) -> &simulation::World {
        self.world.as_ref().unwrap()
    }
    pub(super) fn pending(&self) -> bool {
        self.revision != self.published
    }
    pub(super) fn audit_query(&self) -> Option<String> {
        let world = self.world();
        let start = self.next_event.max(1);
        (start < world.next_event).then(|| format!(
            "SELECT event_id, json FROM sim_audit WHERE run = '{}' AND event_id >= {} AND event_id < {}",
            world.run, start, world.next_event))
    }
    pub(super) fn append(&mut self, reply: &str) -> Result<(), String> {
        let mut batch: Vec<(u64, String)> = rows(reply)?;
        batch.sort_by_key(|(id, _)| *id);
        let world = self.world();
        let mut expected = self.next_event.max(1);
        let mut encoded = Vec::with_capacity(batch.len());
        for (id, body) in batch {
            let header: EventHeader =
                serde_json::from_str(&body).map_err(|_| "invalid audit event")?;
            if id != expected
                || id >= world.next_event
                || header.id != id
                || header.run != world.run
            {
                return Err("audit event gap, duplicate, identity mismatch or future event".into());
            }
            encoded.push(RawValue::from_string(body).map_err(|_| "invalid audit JSON")?);
            expected += 1;
        }
        if expected != world.next_event {
            return Err("audit reply missing captured events".into());
        }
        // Commit only after validating the entire batch; a failed read cannot
        // advance the cursor and silently drop part of the retained history.
        self.events.extend(encoded);
        self.next_event = expected;
        Ok(())
    }
    pub(super) fn write(&mut self, path: &Path) -> Result<(), String> {
        if self.next_event.max(1) != self.world().next_event {
            return Err("audit incomplete for captured world".into());
        }
        #[derive(Serialize)]
        struct Snapshot<'a> {
            world: &'a simulation::World,
            events: &'a [Box<RawValue>],
        }
        let temporary = path.with_extension("json.tmp");
        let result = (|| {
            let file =
                File::create(&temporary).map_err(|_| "snapshot temporary file unavailable")?;
            let mut output = BufWriter::new(file);
            serde_json::to_writer(
                &mut output,
                &Snapshot {
                    world: self.world(),
                    events: &self.events,
                },
            )
            .map_err(|_| "snapshot serialization failed")?;
            output.flush().map_err(|_| "snapshot flush failed")?;
            drop(output);
            std::fs::rename(&temporary, path).map_err(|_| "snapshot replacement failed")?;
            Ok(())
        })();
        if result.is_ok() {
            self.published = self.revision.clone();
        } else {
            let _ = std::fs::remove_file(&temporary);
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};
    fn world() -> simulation::World {
        let seed =
            serde_json::from_str(include_str!("../../../../../scenarios/survival.json")).unwrap();
        simulation::World::new("sim-export-test".into(), seed).unwrap()
    }
    fn reply(events: &[simulation::Event]) -> String {
        json!([{"schema":{"ignored":"SQL metadata"},"rows":events.iter().rev()
            .map(|e|(e.id,serde_json::to_string(e).unwrap())).collect::<Vec<_>>()}])
        .to_string()
    }
    fn path() -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "sao-export-test-{:032x}.json",
            rand::random::<u128>()
        ))
    }
    #[test]
    fn incremental_and_restart_exports_equal_full_authority_history() {
        let mut world = world();
        let mut export = Export::default();
        let path = path();
        let first = world.events.len();
        export
            .prepare(&world.run, &serde_json::to_string(&world).unwrap())
            .unwrap();
        export.append(&reply(&world.events)).unwrap();
        export.write(&path).unwrap();
        assert!(!export.pending());
        assert!(export.audit_query().is_none());
        world.event(
            None,
            "export_unicode",
            vec![],
            json!({"text":"snow 雪 \\\"","nested":[1,{"ok":true}]}),
        );
        world.advance_ms(50);
        export
            .prepare(&world.run, &serde_json::to_string(&world).unwrap())
            .unwrap();
        let query = export.audit_query().unwrap();
        assert!(query.contains(&format!("event_id >= {}", first + 1)));
        assert!(query.contains(&format!("event_id < {}", world.next_event)));
        export.append(&reply(&world.events[first..])).unwrap();
        export.write(&path).unwrap();
        let actual: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        assert_eq!(actual, json!({"world":world,"events":world.events}));
        // Restart performs one complete bootstrap, never assumes disk history is
        // complete or advances a cursor from an unverified prior file.
        let mut restarted = Export::default();
        restarted
            .prepare(&world.run, &serde_json::to_string(&world).unwrap())
            .unwrap();
        restarted.append(&reply(&world.events)).unwrap();
        restarted.write(&path).unwrap();
        assert_eq!(
            actual,
            serde_json::from_slice::<Value>(&std::fs::read(&path).unwrap()).unwrap()
        );
        std::fs::remove_file(path).unwrap();
    }
    #[test]
    fn malformed_or_incomplete_delta_never_advances_cursor_or_replaces_snapshot() {
        let mut world = world();
        let mut export = Export::default();
        let path = path();
        export
            .prepare(&world.run, &serde_json::to_string(&world).unwrap())
            .unwrap();
        export.append(&reply(&world.events)).unwrap();
        export.write(&path).unwrap();
        let previous = std::fs::read(&path).unwrap();
        let start = world.events.len();
        world.event(None, "one", vec![], json!({}));
        world.event(None, "two", vec![], json!({}));
        export
            .prepare(&world.run, &serde_json::to_string(&world).unwrap())
            .unwrap();
        let query = export.audit_query();
        for bad in [
            reply(&world.events[start + 1..]),
            reply(&world.events[start..start + 1]),
            json!([{"rows":[[world.events[start].id,"invalid JSON"]]}]).to_string(),
            reply(&[world.events[start].clone(), world.events[start].clone()]),
        ] {
            assert!(export.append(&bad).is_err());
            assert_eq!(export.audit_query(), query);
            assert!(export.write(&path).is_err());
            assert_eq!(std::fs::read(&path).unwrap(), previous);
        }
        export.append(&reply(&world.events[start..])).unwrap();
        // Failed replacement also remains pending and can retry without fetching
        // or duplicating the already validated event delta.
        let missing = path.with_extension("missing-parent").join("snapshot.json");
        assert!(export.write(&missing).is_err());
        assert!(export.pending());
        assert!(export.audit_query().is_none());
        export.write(&path).unwrap();
        assert!(!export.pending());
        std::fs::remove_file(path).unwrap();
    }
    #[test]
    fn unchanged_header_reuses_world_and_tick_only_update_reuses_audit() {
        let mut world = world();
        let mut export = Export::default();
        let path = path();
        let text = serde_json::to_string(&world).unwrap();
        export.prepare(&world.run, &text).unwrap();
        export.append(&reply(&world.events)).unwrap();
        export.write(&path).unwrap();
        // Reusing the World is observable through an immutable allocation that
        // would be replaced by a second deserialize even with the same content.
        let name = export.world().run.as_ptr();
        export.prepare(&world.run, &text).unwrap();
        assert_eq!(name, export.world().run.as_ptr());
        assert!(!export.pending());
        world.timing.updates += 1;
        export
            .prepare(&world.run, &serde_json::to_string(&world).unwrap())
            .unwrap();
        assert!(export.pending());
        assert!(export.audit_query().is_none());
        export.write(&path).unwrap();
        let mut wrong = world.clone();
        wrong.next_event = 1;
        assert!(export
            .prepare(&wrong.run, &serde_json::to_string(&wrong).unwrap())
            .is_err());
        assert!(export.prepare("sim-other", &text).is_err());
        std::fs::remove_file(path).unwrap();
    }
}
