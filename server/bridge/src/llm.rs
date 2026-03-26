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
                    if serde_json::from_str::<Value>(&chat.message.content).is_err() {
                        log::error!("[{label}] Ollama returned invalid JSON");
                        return None;
                    }
                    log::info!("[{label}] response: {}", &chat.message.content[..chat.message.content.len().min(300)]);
                    Some(chat.message.content)
                }
            }
        }
    }
}

/// Generate a unified behavior tree.
pub async fn generate_tree(npc_id: u64, context: &str) -> Option<String> {
    let label = format!("NPC {npc_id} tree_generation");
    let user_prompt = prompt::build_tree_generation_prompt(context);
    call_ollama(prompt::TREE_GENERATION_SYSTEM_PROMPT, &user_prompt, &label).await
}

/// Generate an experience evaluation (identity deltas).
pub async fn generate_experience_eval(npc_id: u64, context: &str) -> Option<String> {
    let label = format!("NPC {npc_id} experience");
    let user_prompt = prompt::build_experience_prompt(context);
    call_ollama(prompt::EXPERIENCE_SYSTEM_PROMPT, &user_prompt, &label).await
}

/// Generate a conversation response.
pub async fn generate_conversation(npc_id: u64, context: &str) -> Option<String> {
    let label = format!("NPC {npc_id} conversation");
    let user_prompt = prompt::build_conversation_prompt(context);
    call_ollama(prompt::CONVERSATION_SYSTEM_PROMPT, &user_prompt, &label).await
}

/// Extract message text from a conversation response.
pub fn parse_conversation_response(raw: &str) -> Option<String> {
    let v: Value = serde_json::from_str(raw).ok()?;
    v.get("message").and_then(|m| m.as_str()).map(String::from)
}
