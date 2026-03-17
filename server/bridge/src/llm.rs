/// Mock LLM: returns a hardcoded behaviour graph regardless of context.
/// Replace this function body with a real Claude API call when ready.
pub fn generate_behaviour_graph(_context: &str) -> String {
    serde_json::json!({
        "initial_node": "idle",
        "nodes": {
            "idle": {
                "action": "wander",
                "transitions": [
                    { "condition": "in_range", "next": "attacking" },
                    { "condition": "target_out_of_range", "next": "chasing" }
                ]
            },
            "chasing": {
                "action": "move_toward_target",
                "transitions": [
                    { "condition": "in_range", "next": "attacking" },
                    { "condition": "no_target", "next": "idle" }
                ]
            },
            "attacking": {
                "action": "attack_target",
                "transitions": [
                    { "condition": "target_out_of_range", "next": "chasing" },
                    { "condition": "no_target", "next": "idle" }
                ]
            }
        }
    })
    .to_string()
}
