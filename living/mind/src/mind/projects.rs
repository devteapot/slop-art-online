//! Projects (experiment, `LIVING_PROJECTS=1`; off by default): what a person has set out to
//! achieve over days, in the mind's own words, kept in its graph as
//! `self -PURSUES {since, progress, next_step, because, thought, confidence}-> project:<slug>`
//! (the aim is the project concept's name).
//!
//! - Consolidation and the nightly reorganization add, revise and end projects with a
//!   `projects` array (`memory::projects_into`); an ended one is closed with its `outcome`
//!   (`done`, `dropped`), a forgotten one fades like any belief (`retracted_by = 'faded'`).
//! - Every deliberation's think step sees the open ones (at most [`SHOWN`], strongest first) as
//!   their own section and may name the one its decision `serves`; a served project is
//!   reinforced (its fading restarts) and the thought row records which it was.
//! - Nothing proposes, seeds, scores or ranks aims: the prompts say what a project is, never what
//!   to want.

use crate::memory::{self, Project};
use serde_json::{json, Value};

/// Open projects a prompt shows.
pub const SHOWN: usize = 3;

pub fn enabled() -> bool {
    matches!(std::env::var("LIVING_PROJECTS").as_deref(), Ok("1") | Ok("on") | Ok("true"))
}

/// The prompt section's lines: one per open project, then how many more are open.
pub fn lines(open: &[Project], total: usize, time: &dyn Fn(u64) -> String) -> String {
    if open.is_empty() {
        return "(none)\n".into();
    }
    let mut out = String::new();
    for p in open {
        let mut parts = vec![format!("since {}", time(p.since))];
        if !p.progress.is_empty() {
            parts.push(format!("so far: {}", p.progress));
        }
        if !p.next_step.is_empty() {
            parts.push(format!("next: {}", p.next_step));
        }
        let aim = if p.aim.is_empty() || p.aim == p.key { String::new() } else { format!(" {}", p.aim) };
        out.push_str(&format!("- {}:{aim} ({})\n", p.key, parts.join("; ")));
    }
    if total > open.len() {
        out.push_str(&format!("({} other projects you took up are not on your mind now)\n", total - open.len()));
    }
    out
}

/// Which open project a reply says its decision serves: its key (with or without `project:`)
/// or its aim; a list gives its first. `None` for null, "none" or a project that is not open.
pub fn serves(v: &Value, open: &[Project]) -> Option<String> {
    let said = match v {
        Value::String(s) => s.clone(),
        Value::Object(o) => o.get("key").or_else(|| o.get("project")).and_then(|x| x.as_str()).unwrap_or_default().to_string(),
        Value::Array(a) => return a.first().and_then(|x| serves(x, open)),
        _ => return None,
    };
    let said = said.trim().trim_start_matches('#').trim();
    if said.is_empty() || matches!(said.to_lowercase().as_str(), "null" | "none" | "nothing" | "no") {
        return None;
    }
    let k = memory::key(said)?;
    let bare = |key: &str| key.split_once(':').map_or(key.to_string(), |(_, t)| t.to_string());
    open.iter()
        .find(|p| p.key == k || p.key == format!("project:{k}") || bare(&p.key) == bare(&k))
        .or_else(|| open.iter().find(|p| !p.aim.is_empty() && p.aim.trim().eq_ignore_ascii_case(said)))
        .map(|p| p.key.clone())
}

/// What a deliberation's thought row records: the projects it saw, what it said it serves
/// and the open project that resolved to (null when none).
pub fn detail(open: &[Project], said: &Value, served: Option<&str>) -> Value {
    json!({"open": open.iter().map(|p| &p.key).collect::<Vec<_>>(), "said": said, "serves": served})
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::memory::{projects_into, Patch};

    fn project(key: &str, aim: &str) -> Project {
        Project { key: key.into(), aim: aim.into(), progress: "two logs cut".into(), next_step: "find vines".into(), since: 1, t: 2, strength: 0.9, served: 0 }
    }

    #[test]
    fn a_consolidation_adds_revises_and_ends_projects_in_its_own_words() {
        let v = json!({"projects": [
            {"key": "project:raft", "aim": "Build a raft to reach the islet", "progress": "two logs cut", "next_step": "find vines", "because": [5, 99]},
            {"aim": "Learn to smoke fish from Mira"},
            {"key": "project:old_camp", "ended": "given up", "why": "the wolves took the clearing"},
            {"key": "project:hut", "status": "completed", "why": "it stands"},
            {"key": "project:well", "status": "in progress", "progress": "dug knee-deep"},
            {"key": "self", "aim": "be me"},
            {"key": "project:seventh", "aim": "a reply carries at most six"}
        ]});
        let (mut patch, mut notes) = (Patch::default(), Vec::new());
        projects_into(&v, &mut patch, &[5], &mut notes);
        let keys: Vec<&str> = patch.edges.iter().map(|e| e.to.as_str()).collect();
        assert_eq!(keys, vec!["project:raft", "project:learn_to_smoke_fish_from_mira", "project:well"]);
        let raft = &patch.edges[0];
        assert_eq!((raft.from.as_str(), raft.rel.as_str()), ("self", "PURSUES"));
        assert_eq!(raft.because, vec![5], "only known experiences are cited");
        assert!(raft.firsthand, "a project is one's own, not hearsay");
        assert_eq!(raft.props["progress"], "two logs cut");
        assert_eq!(raft.props["next_step"], "find vines");
        let node = patch.nodes.iter().find(|n| n.key == "project:raft").unwrap();
        assert_eq!((node.labels.clone(), node.name.as_deref()), (vec!["Project".to_string()], Some("Build a raft to reach the islet")));
        assert_eq!(patch.nodes.iter().find(|n| n.key == "project:well").unwrap().name, None, "a revision without an aim keeps the name");
        assert_eq!(patch.ended, vec![("project:old_camp".into(), "dropped".into(), "the wolves took the clearing".into()), ("project:hut".into(), "done".into(), "it stands".into())]);
        assert_eq!(notes.len(), 1, "oneself is not a project: {notes:?}");
        let (mut patch, mut notes) = (Patch::default(), Vec::new());
        projects_into(&json!({"projects": [{"key": "person:7", "aim": "Mira"}, {"key": "exp:12", "aim": "that night"}]}), &mut patch, &[], &mut notes);
        assert!(patch.edges.is_empty() && notes.len() == 2, "people and kept memories are not projects: {notes:?}");
    }

    #[test]
    fn nothing_is_written_without_a_projects_array() {
        let (mut patch, mut notes) = (Patch::default(), Vec::new());
        projects_into(&json!({"summary": "x", "projects": null}), &mut patch, &[], &mut notes);
        assert!(patch.edges.is_empty() && patch.nodes.is_empty() && patch.ended.is_empty() && notes.is_empty());
    }

    #[test]
    fn the_section_lists_open_projects_and_counts_the_rest() {
        let t = |ms: u64| format!("day {ms}");
        assert_eq!(lines(&[], 0, &t), "(none)\n");
        let open = vec![project("project:raft", "Build a raft"), Project { progress: String::new(), next_step: String::new(), ..project("plan:river_camp", "plan:river_camp") }];
        assert_eq!(
            lines(&open, 4, &t),
            "- project:raft: Build a raft (since day 1; so far: two logs cut; next: find vines)\n- plan:river_camp: (since day 1)\n(2 other projects you took up are not on your mind now)\n"
        );
    }

    #[test]
    fn a_decision_names_the_project_it_serves_by_key_or_aim() {
        let open = vec![project("project:raft", "Build a raft"), project("plan:river_camp", "Camp by the river")];
        assert_eq!(serves(&json!("project:raft"), &open).as_deref(), Some("project:raft"));
        assert_eq!(serves(&json!("raft"), &open).as_deref(), Some("project:raft"));
        assert_eq!(serves(&json!("Project:Raft "), &open).as_deref(), Some("project:raft"));
        assert_eq!(serves(&json!("river_camp"), &open).as_deref(), Some("plan:river_camp"));
        assert_eq!(serves(&json!("camp by the river"), &open).as_deref(), Some("plan:river_camp"));
        assert_eq!(serves(&json!({"key": "project:raft"}), &open).as_deref(), Some("project:raft"));
        assert_eq!(serves(&json!(["raft", "river_camp"]), &open).as_deref(), Some("project:raft"));
        for none in [json!(null), json!("none"), json!(""), json!("project:boat"), json!(3)] {
            assert_eq!(serves(&none, &open), None, "{none}");
        }
        let d = detail(&open, &json!("raft"), Some("project:raft"));
        assert_eq!(d, json!({"open": ["project:raft", "plan:river_camp"], "said": "raft", "serves": "project:raft"}));
    }

    #[test]
    fn outcomes_read_done_dropped_or_still_open() {
        use crate::memory::project_outcome;
        assert_eq!(project_outcome(&json!("achieved"), true), Some("done"));
        assert_eq!(project_outcome(&json!(true), false), Some("done"));
        assert_eq!(project_outcome(&json!("gave_up"), false), Some("dropped"));
        assert_eq!(project_outcome(&json!("no longer wanted"), true), Some("dropped"));
        assert_eq!(project_outcome(&json!("no longer wanted"), false), None);
        assert_eq!(project_outcome(&json!("ongoing"), true), None);
        assert_eq!(project_outcome(&Value::Null, true), None);
    }
}
