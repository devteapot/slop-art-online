use serde_json::{json, Value};

/// NPC state snapshot used to build tools. Populated from bridge's table cache.
pub struct NpcState {
    pub npc_id: u64,
    pub level: u32,
    // Phase 2 additions:
    // pub skills: Vec<NpcSkillInfo>,
    // pub inventory: Vec<NpcInventoryInfo>,
    // pub unspent_points: u32,
}

/// Build the complete tools array for a specific NPC.
/// Phase 1: returns core tools only.
/// Phase 2: will add skill_tools(state) + inventory_tools(state) + ...
pub fn build_tools_for_npc(_state: &NpcState) -> Vec<Value> {
    let tools = core_tools();
    // Phase 2: let mut tools = core_tools();
    // Phase 2: tools.extend(skill_tools(&state.skills));
    // Phase 2: tools.extend(inventory_tools(&state.inventory));
    // Phase 2: if state.unspent_points > 0 { tools.extend(levelup_tools()); }
    tools
}

/// The 5 always-available tools in Ollama function-calling format.
fn core_tools() -> Vec<Value> {
    vec![
        json!({
            "type": "function",
            "function": {
                "name": "move_to",
                "description": "Move to a specific position in the world.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": { "type": "number", "description": "Target X coordinate" },
                        "z": { "type": "number", "description": "Target Z coordinate" }
                    },
                    "required": ["x", "z"]
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "attack",
                "description": "Attack a nearby target. Must be within attack range.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_type": {
                            "type": "string",
                            "enum": ["player", "npc"],
                            "description": "Type of target to attack"
                        },
                        "target_id": {
                            "type": "string",
                            "description": "ID of the target (player identity hex or NPC id)"
                        }
                    },
                    "required": ["target_type", "target_id"]
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "say",
                "description": "Say something out loud. Other players nearby will see your message.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": { "type": "string", "description": "What to say" }
                    },
                    "required": ["message"]
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "wander",
                "description": "Wander around randomly. Use when there is nothing interesting to do.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "look_around",
                "description": "Look around to observe nearby players, NPCs, and items. Returns observation data.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }),
    ]
}

/// Parsed tool call from Ollama response.
#[derive(Debug)]
pub struct ParsedToolCall {
    pub name: String,
    pub arguments: Value,
}

/// Parse tool_calls from an Ollama response message.
pub fn parse_ollama_tool_calls(message: &Value) -> Vec<ParsedToolCall> {
    let Some(tool_calls) = message.get("tool_calls").and_then(|v| v.as_array()) else {
        return Vec::new();
    };

    tool_calls
        .iter()
        .filter_map(|tc| {
            let func = tc.get("function")?;
            let name = func.get("name")?.as_str()?.to_string();
            let arguments = func.get("arguments").cloned().unwrap_or(json!({}));
            Some(ParsedToolCall { name, arguments })
        })
        .collect()
}

/// Convert parsed tool calls to NpcAction JSON values for the server reducer.
/// Filters out look_around (bridge-only).
pub fn to_npc_actions(calls: &[ParsedToolCall]) -> Vec<Value> {
    calls
        .iter()
        .filter_map(|call| match call.name.as_str() {
            "move_to" => {
                let x = call.arguments.get("x").and_then(|v| v.as_f64())? as f32;
                let z = call.arguments.get("z").and_then(|v| v.as_f64())? as f32;
                Some(json!({ "action": "move_to", "x": x, "z": z }))
            }
            "attack" => {
                let target_type = call.arguments.get("target_type").and_then(|v| v.as_str())?;
                let target_id = call.arguments.get("target_id").and_then(|v| v.as_str())?;
                Some(json!({ "action": "attack", "target_type": target_type, "target_id": target_id }))
            }
            "say" => {
                let message = call.arguments.get("message").and_then(|v| v.as_str())?;
                Some(json!({ "action": "say", "message": message }))
            }
            "wander" => Some(json!({ "action": "wander" })),
            "look_around" => None, // Bridge-only, handled in llm.rs
            _ => None,
        })
        .collect()
}
