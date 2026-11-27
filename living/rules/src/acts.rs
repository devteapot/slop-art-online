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
///
/// What is not an act is refused naming what it was (truthful-refusals): speech, a
/// behavior-graph node, a skill that does not exist, or keys that are neither.
pub fn parse(v: Value, body: Option<&crate::species::Species>, shapes: &crate::combat::Shapes) -> Result<Action, String> {
    if let Some(why) = not_a_do(&v) {
        return Err(why);
    }
    let parsed = match body {
        Some(sp) => graph::from_value_for(v, sp),
        None => graph::from_value_lenient(v),
    };
    let (g, _) = parsed.map_err(|e| unknown_skill(&e).unwrap_or(e))?;
    let a = match g.root {
        Node::Do(a) => a,
        Node::Say(_) => return Err(SPEECH.into()),
        other => return Err(graph_node(node_name(&other))),
    };
    if let Some(why) = not_an_act(&a.skill, shapes) {
        return Err(why);
    }
    Ok(a)
}

const SPEECH: &str = "`say` is speech, not an act: speak it instead";
const ONE_ACT: &str = "an act is one {\"do\": skill, ...}";
/// The graph's node keys (`normalize`'s `NODES`), and the words some replies use for speech.
const NODE_KEYS: &[&str] = &["first", "seq", "if", "wait", "think", "routine", "desires", "wants"];
const SPEECH_KEYS: &[&str] = &["say", "speech", "speak", "talk"];

fn graph_node(name: &str) -> String {
    format!("`{name}` is a behavior-graph node, not a one-off act: {ONE_ACT}")
}

fn node_name(n: &Node) -> &'static str {
    match n {
        Node::First(_) => "first",
        Node::Seq(_) => "seq",
        Node::If(_) => "if",
        Node::Do(_) => "do",
        Node::Say(_) => "say",
        Node::Wait(_) => "wait",
        Node::Think(_) => "think",
        Node::Routine(_) => "routine",
        Node::Desires(_) => "desires",
    }
}

/// A reply object without `do`: speech, a graph node, or keys that are neither, named.
fn not_a_do(v: &Value) -> Option<String> {
    let o = v.as_object()?;
    if o.contains_key("do") {
        return None;
    }
    if let Some(k) = NODE_KEYS.iter().find(|k| o.contains_key(**k)) {
        return Some(graph_node(k));
    }
    if SPEECH_KEYS.iter().any(|k| o.contains_key(*k)) {
        return Some(SPEECH.into());
    }
    let keys = o.keys().map(|k| format!("`{k}`")).collect::<Vec<_>>().join(", ");
    Some(if keys.is_empty() { format!("an empty object is not an act: {ONE_ACT}") } else { format!("{keys}: neither a skill nor a behavior-graph node, so not an act: {ONE_ACT}") })
}

/// The graph's "unknown skill `x`" error, said as what it was: no such skill.
fn unknown_skill(e: &str) -> Option<String> {
    let rest = e.split_once("unknown skill `")?.1;
    let name = rest.split('`').next()?;
    Some(format!("`{name}` is not a skill, so not an act"))
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
        // What is not an act is refused naming what it was (truthful-refusals).
        let d = &Default::default();
        assert_eq!(parse(json!({"say": "Stop!"}), None, d).unwrap_err(), SPEECH);
        assert!(parse(json!({"do": "say", "text": "Stop!"}), None, d).unwrap_err().starts_with("`say` is speech"));
        assert!(parse(json!({"wait": 20}), None, d).unwrap_err().starts_with("`wait` is a behavior-graph node"));
        assert!(parse(json!({"seq": [{"do": "eat", "item": "food"}]}), None, d).unwrap_err().starts_with("`seq` is a behavior-graph node"));
        assert!(parse(json!({"do": "think", "reason": "x"}), None, d).unwrap_err().starts_with("`think` is a behavior-graph node"));
        assert_eq!(parse(json!({"do": "call", "speech": "Stop!"}), None, d).unwrap_err(), "`call` is not a skill, so not an act");
        assert!(parse(json!({"act": {"do": "back_off"}}), None, d).unwrap_err().starts_with("`act`: neither a skill nor a behavior-graph node"));
        assert!(parse(json!({}), None, d).unwrap_err().starts_with("an empty object is not an act"));
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
        assert_eq!((d.skill.as_str(), d.offer, d.record, d.bond), ("decline", None, Some(12), None));
        let b = parse(json!({"do": "decline", "target": {"id": 4}, "bond": 7}), None, &shapes).unwrap();
        assert_eq!((b.skill.as_str(), b.offer, b.record, b.bond), ("decline", None, None, Some(7)));
        assert_eq!(from_json(&to_json(&b)).unwrap(), b);
        let b2 = parse(json!({"do": "decline", "target": {"id": 4}, "bond_id": "#8"}), None, &shapes).unwrap();
        assert_eq!(b2.bond, Some(8));
        assert_eq!(parse(json!({"do": "decline", "target": {"id": 4}, "bond": 0}), None, &shapes).unwrap().bond, None);
        assert!(parse(json!({"do": "decline", "target": {"id": 4}, "bond": "yes"}), None, &shapes).unwrap_err().contains("the id of the family offer"));
        assert_eq!(parse(json!({"do": "accept", "target": {"id": 4}, "bond": 7}), None, &shapes).unwrap().bond, None);
        assert_eq!(parse(json!({"do": "decline", "target": {"id": 4}, "offer": 0}), None, &shapes).unwrap().offer, None);
        assert!(parse(json!({"do": "accept", "target": {"id": 4}, "offer": "the fish"}), None, &shapes).unwrap_err().contains("the id of the trade offer"));
        // A skill that answers nothing ignores the words, as it did.
        assert_eq!(parse(json!({"do": "give", "target": {"id": 4}, "item": "fish", "offer": "the fish"}), None, &shapes).unwrap().offer, None);
    }
}
