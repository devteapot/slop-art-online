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

// Which skills are ongoing or real-time (they belong in the behavior graph, not in an act)
// and which are reflexes (they take the body back from an act) is
// `living_rules::combat::Shapes::real_time` / `reflex`: the walking and resting skills
// (skills whose spec says `moment`), and each combat skill as its script declares. A single walk (`goto`) may
// be an act: minds use it as the step before an interaction ("go to the child, then teach");
// in the first lab minutes 16 of 29 acts were such walks.

/// Most acts waiting for one body at a time.
pub const MAX_QUEUED: usize = 4;
/// An act that has not reached its target after this long gives up, unless it is walking to a
/// place: such a walk lasts as long as its route, and steering ends it on arrival or when the
/// way is blocked (docs/PATHS.md).
pub const APPROACH_MS: u64 = 90_000;
/// An act still waiting for the body after this long is dropped.
pub const QUEUE_MS: u64 = 120_000;

/// Why a skill cannot be a deliberate act, if it cannot.
pub fn not_an_act(skill: &str, shapes: &crate::combat::Shapes) -> Option<String> {
    shapes.real_time(skill).then(|| format!("`{skill}` is ongoing or real-time behavior: it belongs in your behavior graph, not in a one-off act"))
}

/// A model-written act (flat `{"do": "give", ...}` or canonical form) as an action, normalized
/// like a graph leaf (for a particular body, when given), under the rules' combat shapes.
pub fn parse(v: Value, body: Option<&crate::species::Species>, shapes: &crate::combat::Shapes) -> Result<Action, String> {
    let (g, _) = match body {
        Some(sp) => graph::from_value_for(v, sp)?,
        None => graph::from_value_lenient(v)?,
    };
    let a = match g.root {
        Node::Do(a) => a,
        _ => return Err("an act is a single {\"do\": skill, ...} node".into()),
    };
    if let Some(why) = not_an_act(&a.skill, shapes) {
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
        let a = parse(json!({"do": "conceive", "target": {"id": 6}}), None, &Default::default()).unwrap();
        assert_eq!(a.skill, "conceive");
        let t = parse(json!({"do": "offer", "target": {"id": 4}, "item": "fish", "qty": 2, "want": "wood", "want_qty": 3}), None, &Default::default()).unwrap();
        assert_eq!(t.want.as_deref(), Some("wood"));
        assert_eq!(from_json(&to_json(&t)).unwrap(), t);
        assert!(parse(json!({"do": "flee", "target": {"nearest": "wolf"}}), None, &Default::default()).unwrap_err().contains("behavior graph"));
        assert!(parse(json!({"do": "goto", "target": {"place": "camp"}}), None, &Default::default()).is_ok());
        assert!(parse(json!({"first": [{"do": "eat", "item": "food"}]}), None, &Default::default()).is_err());
        // Movement intents that end on their own may be acts; those held over time belong in a graph.
        let shapes = crate::combat::Shapes::default();
        let b = parse(json!({"do": "back_off", "target": {"id": 4}, "distance": 6}), None, &shapes).unwrap();
        assert_eq!(b.distance, Some(6.0));
        assert!(parse(json!({"do": "close_in", "target": {"id": 4}, "distance": 2}), None, &shapes).is_ok());
        for held in ["keep_distance", "circle", "follow"] {
            assert!(parse(json!({"do": held, "target": {"id": 4}}), None, &shapes).unwrap_err().contains("behavior graph"), "{held}");
        }
    }

    /// An answer names the offer or proposal it answers; without one it is the act it always
    /// was, stored the same.
    #[test]
    fn answers_carry_what_they_name() {
        let shapes = Default::default();
        let plain = parse(json!({"do": "accept", "target": {"id": 4}}), None, &shapes).unwrap();
        assert_eq!((plain.offer, plain.record), (None, None));
        assert_eq!(to_json(&plain), r#"{"do":{"skill":"accept","target":{"id":4}}}"#);
        let a = parse(json!({"do": "accept", "target": {"id": 4}, "offer": 17}), None, &shapes).unwrap();
        assert_eq!(a.offer, Some(17));
        assert_eq!(from_json(&to_json(&a)).unwrap(), a);
        let d = parse(json!({"do": "decline", "target": {"id": 4}, "record_id": "12"}), None, &shapes).unwrap();
        assert_eq!((d.skill.as_str(), d.offer, d.record), ("decline", None, Some(12)));
        assert_eq!(parse(json!({"do": "decline", "target": {"id": 4}, "offer": 0}), None, &shapes).unwrap().offer, None);
        assert!(parse(json!({"do": "accept", "target": {"id": 4}, "offer": "the fish"}), None, &shapes).unwrap_err().contains("the id of the trade offer"));
        // A skill that answers nothing ignores the words, as it did.
        assert_eq!(parse(json!({"do": "give", "target": {"id": 4}, "item": "fish", "offer": "the fish"}), None, &shapes).unwrap().offer, None);
    }
}
