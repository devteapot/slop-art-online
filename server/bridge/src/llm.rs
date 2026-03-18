use serde::{Deserialize, Serialize};

const DEFAULT_GRAPH: &str = r#"{
    "initial_node": "idle",
    "nodes": {
        "idle":      { "action": "wander",             "transitions": [{ "condition": "in_range",            "next": "attacking" }, { "condition": "target_out_of_range", "next": "chasing"   }] },
        "chasing":   { "action": "move_toward_target",  "transitions": [{ "condition": "in_range",            "next": "attacking" }, { "condition": "no_target",           "next": "idle"      }] },
        "attacking": { "action": "attack_target",        "transitions": [{ "condition": "target_out_of_range", "next": "chasing"   }, { "condition": "no_target",           "next": "idle"      }] }
    }
}"#;

const SYSTEM_PROMPT: &str = r#"You are an NPC behaviour designer for an MMORPG.
Given a JSON context describing the NPC's situation, return a behaviour graph as JSON.

The graph must follow this exact schema:
{
  "initial_node": "<node_name>",
  "nodes": {
    "<node_name>": {
      "action": "<action>",
      "transitions": [
        { "condition": "<condition>", "next": "<node_name>" }
      ]
    }
  }
}

Available actions:
- "wander"              — move randomly (use when no player is detected)
- "move_toward_target"  — chase the nearest player (use when player is detected but out of attack range)
- "attack_target"       — attack the nearest player (use when player is within attack range)
- "flee_from_target"    — run away from the nearest player

Available conditions (mutually exclusive, evaluated in order):
- "in_range"            — a player is detected AND within attack range
- "target_out_of_range" — a player is detected BUT out of attack range
- "no_target"           — no player is detected at all

Condition logic rules — follow these exactly:
- "no_target" means NO player is visible — never transition to attack or chase on "no_target"
- "in_range" means a player IS close — this is when attacking makes sense
- "target_out_of_range" means a player IS visible but far — this is when chasing makes sense
- A wander node should only leave wander when a player is detected: use "in_range" or "target_out_of_range"
- A wander node should NOT transition on "no_target" — that means nothing changed

Example of a correct aggressive graph:
{
  "initial_node": "idle",
  "nodes": {
    "idle":      { "action": "wander",            "transitions": [{ "condition": "in_range",            "next": "attacking" }, { "condition": "target_out_of_range", "next": "chasing"  }] },
    "chasing":   { "action": "move_toward_target", "transitions": [{ "condition": "in_range",            "next": "attacking" }, { "condition": "no_target",           "next": "idle"     }] },
    "attacking": { "action": "attack_target",      "transitions": [{ "condition": "target_out_of_range", "next": "chasing"  }, { "condition": "no_target",           "next": "idle"     }] }
  }
}

Design a strategy appropriate for the NPC's situation. Return only valid JSON, no explanation."#;

#[derive(Serialize)]
struct ChatRequest {
    model: String,
    messages: Vec<Message>,
    stream: bool,
    format: String,
}

#[derive(Serialize, Deserialize)]
struct Message {
    role: String,
    content: String,
}

#[derive(Deserialize)]
struct ChatResponse {
    message: Message,
}

pub async fn generate_behaviour_graph(context: &str) -> String {
    let ollama_url = std::env::var("OLLAMA_URL")
        .unwrap_or_else(|_| "http://localhost:11434".to_string());
    let model = std::env::var("OLLAMA_MODEL")
        .unwrap_or_else(|_| "qwen2.5:7b".to_string());

    let request = ChatRequest {
        model,
        messages: vec![
            Message { role: "system".to_string(), content: SYSTEM_PROMPT.to_string() },
            Message { role: "user".to_string(),   content: context.to_string() },
        ],
        stream: false,
        format: "json".to_string(),
    };

    let client = reqwest::Client::new();
    let result = client
        .post(format!("{ollama_url}/api/chat"))
        .json(&request)
        .send()
        .await;

    match result {
        Err(e) => {
            log::error!("Ollama request failed: {e} — using default graph");
            DEFAULT_GRAPH.to_string()
        }
        Ok(resp) => match resp.json::<ChatResponse>().await {
            Err(e) => {
                log::error!("Failed to parse Ollama response: {e} — using default graph");
                DEFAULT_GRAPH.to_string()
            }
            Ok(chat) => {
                // Validate it's parseable JSON before sending to the reducer
                if serde_json::from_str::<serde_json::Value>(&chat.message.content).is_err() {
                    log::error!("Ollama returned invalid JSON — using default graph");
                    return DEFAULT_GRAPH.to_string();
                }
                chat.message.content
            }
        },
    }
}
