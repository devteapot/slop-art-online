//! Records: durable social state the world's rules define (docs/WORLD_RULES.md). The engine
//! keeps a record's kind, status, parties, terms and due time, indexes it by party and asks the
//! rules what happens when it falls due; what a kind means (an agreement, a demand, a regard) is
//! the script's. A record is audit truth: who knows of it is decided by perception (the parties
//! are told, onlookers see it made), not by reading this table.

use serde_json::{Map, Value};

/// A community as a party: `COMMUNITY | community id` (a character is its own id).
pub const COMMUNITY: u64 = 1 << 40;
/// Open records one party may hold at once; a rule that would make one more is refused.
pub const MAX_OPEN: usize = 12;
/// Parties one record may have.
pub const MAX_PARTIES: usize = 4;
/// Terms one record may hold, and the size of their JSON.
pub const MAX_TERMS: usize = 16;
pub const MAX_TERMS_BYTES: usize = 1_024;
/// Longest a record may stand before it falls due, in world hours (about 30 days).
pub const MAX_DUE_H: f32 = 720.0;
/// Roles and stance terms the engine reads of a stance record: a record between `holder` and
/// `toward` whose terms carry a `label` (and a `value`, -100..100) says how the holder regards the
/// other side, for relation filters and minds (docs/WORLD_RULES.md, "Standing").
pub const HOLDER: &str = "holder";
pub const TOWARD: &str = "toward";

/// What the rules see of a record (`a.records`, `a.record`).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecordFacts {
    pub id: u64,
    pub kind: String,
    pub status: String,
    pub open: bool,
    /// Strings, numbers and booleans by name.
    pub terms: Map<String, Value>,
    /// Who holds which role: a character id, or `COMMUNITY | community id`.
    pub parties: Vec<(String, u64)>,
    /// The role the one reading it holds (empty when it is not a party).
    pub me: String,
    /// Who made it (0: the seed or a rule).
    pub by: u32,
    /// Seconds since it was made; seconds until it falls due (none: never).
    pub age_s: f32,
    pub due_s: Option<f32>,
}

impl RecordFacts {
    pub fn party(&self, role: &str) -> Option<u64> {
        self.parties.iter().find(|(r, _)| r == role).map(|(_, p)| *p)
    }
}

/// Terms as the rules may give them: a map of strings, numbers and booleans, at most
/// [`MAX_TERMS`] of them and [`MAX_TERMS_BYTES`] as JSON.
pub fn check_terms(t: &Map<String, Value>) -> Result<(), String> {
    if t.len() > MAX_TERMS {
        return Err(format!("a record holds at most {MAX_TERMS} terms"));
    }
    if let Some((k, _)) = t.iter().find(|(_, v)| !(v.is_string() || v.is_number() || v.is_boolean())) {
        return Err(format!("term `{k}` must be a string, a number or true/false"));
    }
    if serde_json::to_string(t).map_or(0, |s| s.len()) > MAX_TERMS_BYTES {
        return Err(format!("a record's terms are at most {MAX_TERMS_BYTES} bytes"));
    }
    Ok(())
}

/// A stance a record states: the holder's label and value toward the other side.
pub fn stance(r: &RecordFacts) -> Option<(u64, u64, String, f32)> {
    let (h, t) = (r.party(HOLDER)?, r.party(TOWARD)?);
    let label = r.terms.get("label").and_then(|v| v.as_str()).unwrap_or_default().to_string();
    let value = r.terms.get("value").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32;
    (!label.is_empty() || value != 0.0).then_some((h, t, label, value))
}

/// Whether a stance label and value fit a relation filter word (`enemy`, `friend` or a word of
/// the label), as a personal relation's label and trust do.
pub fn stance_fits(label: &str, value: f32, want: &str) -> bool {
    let label = label.to_lowercase();
    match want {
        "friend" => value >= 25.0 || ["friend", "ally", "kin"].iter().any(|l| label.contains(l)),
        "enemy" => value <= -25.0 || ["enemy", "rival", "threat", "foe"].iter().any(|l| label.contains(l)),
        w => !w.is_empty() && label.contains(&w.to_lowercase()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn terms_are_small_maps_of_plain_values() {
        let ok = json!({"from_gives": "berries", "from_qty": 3, "done": false}).as_object().unwrap().clone();
        assert!(check_terms(&ok).is_ok());
        let nested = json!({"x": {"y": 1}}).as_object().unwrap().clone();
        assert!(check_terms(&nested).unwrap_err().contains("`x`"));
        let big = json!({"words": "w".repeat(2_000)}).as_object().unwrap().clone();
        assert!(check_terms(&big).is_err());
    }

    #[test]
    fn a_stance_is_a_holder_toward_record_with_a_label() {
        let r = RecordFacts { kind: "regard".into(), parties: vec![("holder".into(), COMMUNITY | 2), ("toward".into(), COMMUNITY | 3)], terms: json!({"label": "rival town", "value": -40}).as_object().unwrap().clone(), ..Default::default() };
        let (h, t, label, value) = stance(&r).unwrap();
        assert_eq!((h, t, label.as_str(), value), (COMMUNITY | 2, COMMUNITY | 3, "rival town", -40.0));
        assert!(stance_fits(&label, value, "enemy") && stance_fits(&label, value, "rival") && !stance_fits(&label, value, "friend"));
        assert!(stance(&RecordFacts { kind: "agreement".into(), ..Default::default() }).is_none());
    }
}
