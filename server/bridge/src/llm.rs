use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::prompt;

#[derive(Serialize)]
struct ChatRequest {
    model: String,
    messages: Vec<ChatMessage>,
    stream: bool,
    format: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct ChatMessage {
    role: String,
    content: String,
}

#[derive(Deserialize)]
struct ChatResponse {
    message: ChatMessage,
}

fn ollama_config() -> (String, String) {
    let url = std::env::var("OLLAMA_URL")
        .unwrap_or_else(|_| "http://localhost:11434".to_string());
    let model = std::env::var("OLLAMA_MODEL")
        .unwrap_or_else(|_| "qwen2.5:7b".to_string());
    (url, model)
}

async fn call_ollama(system_prompt: &str, user_prompt: &str, label: &str) -> Option<String> {
    let (ollama_url, model) = ollama_config();
    let client = reqwest::Client::new();

    log::info!("[{label}] sending Ollama request (model={model})");
    log::debug!("[{label}] user_prompt: {user_prompt}");

    let request = ChatRequest {
        model,
        messages: vec![
            ChatMessage { role: "system".into(), content: system_prompt.into() },
            ChatMessage { role: "user".into(), content: user_prompt.into() },
        ],
        stream: false,
        format: "json".to_string(),
    };

    let start = std::time::Instant::now();
    let result = client
        .post(format!("{ollama_url}/api/chat"))
        .json(&request)
        .send()
        .await;
    let elapsed = start.elapsed();

    match result {
        Err(e) => {
            log::error!("[{label}] Ollama request failed ({:.1}s): {e}", elapsed.as_secs_f64());
            None
        }
        Ok(resp) => {
            log::info!("[{label}] Ollama responded in {:.1}s (status={})", elapsed.as_secs_f64(), resp.status());
            match resp.json::<ChatResponse>().await {
                Err(e) => {
                    log::error!("[{label}] failed to parse response: {e}");
                    None
                }
                Ok(chat) => {
                    // Validate it's valid JSON
                    if serde_json::from_str::<Value>(&chat.message.content).is_err() {
                        log::error!("[{label}] Ollama returned invalid JSON");
                        return None;
                    }
                    log::info!("[{label}] response: {}", &chat.message.content[..chat.message.content.len().min(200)]);
                    Some(chat.message.content)
                }
            }
        }
    }
}

/// Generate a combat behavior tree JSON string.
/// Returns None on failure (caller should keep the default tree).
pub async fn generate_combat_tree(npc_id: u64, context: &str) -> Option<String> {
    let label = format!("NPC {npc_id} combat_tree");
    let user_prompt = prompt::build_combat_user_prompt(context);
    call_ollama(prompt::COMBAT_TREE_SYSTEM_PROMPT, &user_prompt, &label).await
}

/// Generate a plan (JSON array of NpcBtAction steps).
/// Returns None on failure.
pub async fn generate_plan(npc_id: u64, context: &str) -> Option<String> {
    let label = format!("NPC {npc_id} plan");
    let user_prompt = prompt::build_plan_user_prompt(context);
    call_ollama(prompt::PLAN_SYSTEM_PROMPT, &user_prompt, &label).await
}

/// Generate a post-combat plan.
/// Returns None on failure.
pub async fn generate_post_combat(npc_id: u64, context: &str) -> Option<String> {
    let label = format!("NPC {npc_id} post_combat");
    let user_prompt = prompt::build_post_combat_user_prompt(context);
    call_ollama(prompt::POST_COMBAT_SYSTEM_PROMPT, &user_prompt, &label).await
}

/// Generate a social interaction plan.
/// Returns None on failure.
pub async fn generate_social(npc_id: u64, context: &str) -> Option<String> {
    let label = format!("NPC {npc_id} social");
    let user_prompt = prompt::build_social_user_prompt(context);
    call_ollama(prompt::SOCIAL_SYSTEM_PROMPT, &user_prompt, &label).await
}

/// Generate a nightly reflection (goals, beliefs, memories, persona).
pub async fn generate_reflection(npc_id: u64, context: &str) -> Option<String> {
    let label = format!("NPC {npc_id} reflection");
    let user_prompt = prompt::build_reflection_user_prompt(context);
    call_ollama(prompt::REFLECTION_SYSTEM_PROMPT, &user_prompt, &label).await
}

/// Generate a dawn life tree (daily routine behavior tree).
pub async fn generate_dawn(npc_id: u64, context: &str) -> Option<String> {
    let label = format!("NPC {npc_id} dawn");
    let user_prompt = prompt::build_dawn_user_prompt(context);
    call_ollama(prompt::DAWN_SYSTEM_PROMPT, &user_prompt, &label).await
}

/// Generate a significant event response.
pub async fn generate_significant(npc_id: u64, context: &str) -> Option<String> {
    let label = format!("NPC {npc_id} significant");
    let user_prompt = prompt::build_significant_user_prompt(context);
    call_ollama(prompt::SIGNIFICANT_SYSTEM_PROMPT, &user_prompt, &label).await
}

/// Response with steps and optional memories.
pub struct LlmResponse {
    pub steps_json: String,
    pub memories: Vec<String>,
}

/// Parse an LLM response that may contain either:
/// - A plain JSON array of steps: [...]
/// - A JSON object with "steps" and optional "memories": {"steps": [...], "memories": [...]}
/// Also checks combat tree responses for a "memories" field.
pub fn parse_response_with_memories(raw: &str) -> Option<LlmResponse> {
    let v: Value = serde_json::from_str(raw).ok()?;
    if let Some(obj) = v.as_object() {
        // Object format: {"steps": [...], "memories": [...]}
        // Also handle combat tree format: {"tree": {...}, "memories": [...]}
        let memories = obj.get("memories")
            .and_then(|m| m.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
            .unwrap_or_default();

        if let Some(steps) = obj.get("steps") {
            return Some(LlmResponse {
                steps_json: serde_json::to_string(steps).ok()?,
                memories,
            });
        }
        // If it's a combat tree or other object, return as-is
        return Some(LlmResponse {
            steps_json: raw.to_string(),
            memories,
        });
    }
    // Plain array
    Some(LlmResponse {
        steps_json: raw.to_string(),
        memories: Vec::new(),
    })
}
