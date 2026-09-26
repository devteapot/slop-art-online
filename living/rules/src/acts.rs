//! Deliberate acts: one-off interactions a controller decides on and the body carries out
//! once, outside the behavior graph (conceiving a child, trading, giving, teaching, writing,
//! reading, joining a community...). The behavior graph stays the real-time layer (moving,
//! fleeing, fighting, feeding, sleeping, work loops); an act holds the body until it is done,
//! and only a reflex in the graph (flee, dodge, block, attack, throw) takes the body back.
//!
//! An act is written exactly like a graph `do` leaf (`{"do": "conceive", "target": {"id": 6}}`)
//! and runs through the same skill rules (checks, durations, effects, walking into reach).

use crate::graph::{self, Action, Node};
use serde_json::Value;

/// Skills that are ongoing or real-time: they belong in the behavior graph, not in an act.
/// A single walk (`goto`) may be an act: minds use it as the step before an interaction
/// ("go to the child, then teach"); in the first lab minutes 16 of 29 acts were such walks.
pub const REAL_TIME: &[&str] = &["wander", "flee", "follow", "dodge", "block", "attack", "throw", "wait", "sleep", "rest", "graze"];

/// Graph skills that interrupt an act in progress: reflexes win over deliberate acts.
pub const REFLEXES: &[&str] = &["flee", "dodge", "block", "attack", "throw"];

/// Most acts waiting for one body at a time.
pub const MAX_QUEUED: usize = 4;
/// An act that has not reached its target after this long gives up.
pub const APPROACH_MS: u64 = 90_000;
/// An act still waiting for the body after this long is dropped.
pub const QUEUE_MS: u64 = 120_000;

/// Why a skill cannot be a deliberate act, if it cannot.
pub fn not_an_act(skill: &str) -> Option<String> {
    REAL_TIME.contains(&skill).then(|| format!("`{skill}` is ongoing or real-time behavior: it belongs in your behavior graph, not in a one-off act"))
}

/// A model-written act (flat `{"do": "give", ...}` or canonical form) as an action, normalized
/// like a graph leaf (for a particular body, when given).
pub fn parse(v: Value, body: Option<&crate::species::Species>) -> Result<Action, String> {
    let (g, _) = match body {
        Some(sp) => graph::from_value_for(v, sp)?,
        None => graph::from_value_lenient(v)?,
    };
    let a = match g.root {
        Node::Do(a) => a,
        _ => return Err("an act is a single {\"do\": skill, ...} node".into()),
    };
    if let Some(why) = not_an_act(&a.skill) {
        return Err(why);
    }
    Ok(a)
}

/// The canonical JSON of an act (a `do` node).
pub fn to_json(a: &Action) -> String {
    serde_json::to_string(&Node::Do(a.clone())).unwrap_or_default()
}

/// Parse a stored act.
pub fn from_json(s: &str) -> Result<Action, String> {
    match serde_json::from_str::<Node>(s).map_err(|e| format!("act: {e}"))? {
        Node::Do(a) => Ok(a),
        _ => Err("not an act".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn acts_are_single_do_nodes() {
        let a = parse(json!({"do": "conceive", "target": {"id": 6}}), None).unwrap();
        assert_eq!(a.skill, "conceive");
        let t = parse(json!({"do": "offer", "target": {"id": 4}, "item": "fish", "qty": 2, "want": "wood", "want_qty": 3}), None).unwrap();
        assert_eq!(t.want.as_deref(), Some("wood"));
        assert_eq!(from_json(&to_json(&t)).unwrap(), t);
        assert!(parse(json!({"do": "flee", "target": {"nearest": "wolf"}}), None).unwrap_err().contains("behavior graph"));
        assert!(parse(json!({"do": "goto", "target": {"place": "camp"}}), None).is_ok());
        assert!(parse(json!({"first": [{"do": "eat", "item": "food"}]}), None).is_err());
    }
}
