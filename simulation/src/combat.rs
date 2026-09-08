//! Classification of already-authorized personal facts for optional client
//! reactions. This creates no observations, memory, behavior or physical effects.
use serde_json::Value;

pub fn is_combat_event(kind: &str, data: &Value) -> bool {
    match kind {
        "skill_attempt" | "skill_progress" | "skill_result" => data["skill"] == "attack",
        "perception" => data["kind"] == "death"
            || (data["kind"] == "danger" && data["content"]["cause"] == "attack"),
        // An interrupted action is relevant even when that action was fleeing,
        // healing or gathering. Keep its actual reason; do not label it damage.
        "action_interrupted" | "behavior_interrupted" | "death" => true,
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn combat_channel_preserves_fact_types_without_promoting_other_perceptions() {
        assert!(is_combat_event("skill_attempt",&json!({"skill":"attack"})));
        assert!(is_combat_event("skill_result",&json!({"skill":"attack","status":"failure"})));
        assert!(is_combat_event("perception",&json!({"kind":"danger","content":{"cause":"attack"}})));
        assert!(is_combat_event("perception",&json!({"kind":"death"})));
        assert!(is_combat_event("action_interrupted",&json!({"reason":"action replaced"})));
        for data in [json!({"kind":"speech","content":{"text":"I attacked someone"}}),
            json!({"kind":"seen_player"}),json!({"kind":"danger","content":{"cause":"weather"}})] {
            assert!(!is_combat_event("perception",&data));
        }
        assert!(!is_combat_event("skill_result",&json!({"skill":"move"})));
        assert!(!is_combat_event("damage",&json!({"cause_kind":"attack"})),"raw audit is not personal evidence");
    }
}
