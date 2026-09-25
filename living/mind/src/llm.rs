//! OpenAI-compatible chat client with per-character model profiles and a JSONL journal
//! of every exchange (exact prompts, raw replies, latency, failures).

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;
use std::time::{Duration, Instant};
use tokio::io::AsyncWriteExt;

#[derive(Clone, Debug, Deserialize)]
pub struct Profile {
    pub base_url: String,
    pub model: String,
    pub key_env: String,
    #[serde(default)]
    pub reasoning_effort: HashMap<String, String>,
    #[serde(default = "yes")]
    pub json_mode: bool,
}

fn yes() -> bool {
    true
}

#[derive(Clone, Debug, Deserialize)]
pub struct ModelsFile {
    pub default: String,
    pub profiles: HashMap<String, Profile>,
    #[serde(default)]
    pub assign: HashMap<String, String>,
    /// Optional rotation of profile names assigned to people by id.
    #[serde(default)]
    pub rotate: Vec<String>,
    /// Per-species minds: `think` (impulses), `remember` (consolidation) and `compile`
    /// (turning impulses into behavior graphs) may use different models.
    #[serde(default)]
    pub species: HashMap<String, HashMap<String, String>>,
}

pub struct Llm {
    http: reqwest::Client,
    models: ModelsFile,
    keys: HashMap<String, String>,
    journal: PathBuf,
}

pub struct Reply {
    pub content: String,
    pub tokens: u32,
    pub latency_ms: u32,
    pub model: String,
}

pub struct Msg {
    pub role: &'static str,
    pub content: String,
}

impl Llm {
    pub fn new(models: ModelsFile, journal: PathBuf) -> Result<Self> {
        let mut keys = HashMap::new();
        for (name, p) in &models.profiles {
            match std::env::var(&p.key_env) {
                Ok(k) if !k.trim().is_empty() => {
                    keys.insert(name.clone(), k.trim().to_string());
                }
                _ => log::warn!("model profile `{name}` disabled: {} is not set", p.key_env),
            }
        }
        if !keys.contains_key(&models.default) {
            return Err(anyhow!("default model profile `{}` has no API key", models.default));
        }
        std::fs::create_dir_all(&journal)?;
        let http = reqwest::Client::builder().timeout(Duration::from_secs(180)).user_agent("sao-living-mind/0.1").build()?;
        Ok(Self { http, models, keys, journal })
    }

    /// Profile for a character: explicit assignment, then rotation, then default.
    pub fn profile_for(&self, id: u32, name: &str) -> String {
        let pick = self
            .models
            .assign
            .get(name)
            .cloned()
            .or_else(|| (!self.models.rotate.is_empty()).then(|| self.models.rotate[id as usize % self.models.rotate.len()].clone()))
            .unwrap_or_else(|| self.models.default.clone());
        if self.keys.contains_key(&pick) {
            pick
        } else {
            self.models.default.clone()
        }
    }

    /// Profile for a species role (`think`, `remember`, `compile`), when configured.
    pub fn species_profile(&self, kind: &str, role: &str) -> Option<String> {
        self.models.species.get(kind).and_then(|m| m.get(role)).filter(|p| self.keys.contains_key(*p)).cloned()
    }

    pub fn model_name(&self, profile: &str) -> String {
        self.models.profiles.get(profile).map(|p| p.model.clone()).unwrap_or_default()
    }

    /// Call the character's model; if it fails, retry once on the default model so a provider
    /// outage does not stall minds (both attempts are journaled).
    pub async fn chat(&self, profile: &str, purpose: &str, actor: &str, messages: &[Msg]) -> Result<Reply> {
        match self.chat_once(profile, purpose, actor, messages).await {
            Ok(r) => Ok(r),
            Err(e) if profile != self.models.default => {
                log::warn!("{actor}: {profile} failed ({e:#}); falling back to {}", self.models.default);
                self.chat_once(&self.models.default.clone(), purpose, actor, messages).await
            }
            Err(e) => Err(e),
        }
    }

    async fn chat_once(&self, profile: &str, purpose: &str, actor: &str, messages: &[Msg]) -> Result<Reply> {
        let p = self.models.profiles.get(profile).ok_or_else(|| anyhow!("no profile {profile}"))?;
        let key = self.keys.get(profile).ok_or_else(|| anyhow!("profile {profile} has no key"))?;
        let mut body = json!({
            "model": p.model,
            "messages": messages.iter().map(|m| json!({"role": m.role, "content": m.content})).collect::<Vec<_>>(),
        });
        if p.json_mode {
            body["response_format"] = json!({"type": "json_object"});
        }
        if let Some(e) = p.reasoning_effort.get(purpose) {
            body["reasoning_effort"] = json!(e);
        }
        let started = Instant::now();
        let url = format!("{}/chat/completions", p.base_url.trim_end_matches('/'));
        let result = async {
            let resp = self.http.post(&url).bearer_auth(key).json(&body).send().await.context("request")?;
            let status = resp.status();
            let text = resp.text().await.context("body")?;
            if !status.is_success() {
                return Err(anyhow!("HTTP {status}: {}", text.chars().take(400).collect::<String>()));
            }
            let v: Value = serde_json::from_str(&text).context("response json")?;
            let content = content_text(&v["choices"][0]["message"]["content"]);
            let tokens = v["usage"]["total_tokens"].as_u64().unwrap_or(0) as u32;
            Ok((content, tokens))
        }
        .await;
        let latency_ms = started.elapsed().as_millis() as u32;
        let entry = json!({
            "at_ms": now_ms(),
            "actor": actor,
            "purpose": purpose,
            "profile": profile,
            "model": p.model,
            "latency_ms": latency_ms,
            "request": body,
            "reply": result.as_ref().map(|(c, _)| c.clone()).ok(),
            "tokens": result.as_ref().map(|(_, t)| *t).ok(),
            "error": result.as_ref().err().map(|e| format!("{e:#}")),
        });
        self.journal(actor, &entry).await;
        let (content, tokens) = result?;
        Ok(Reply { content, tokens, latency_ms, model: p.model.clone() })
    }

    async fn journal(&self, actor: &str, entry: &Value) {
        let path = self.journal.join(format!("{}.jsonl", actor.replace(|c: char| !c.is_alphanumeric(), "_")));
        if let Ok(mut f) = tokio::fs::OpenOptions::new().create(true).append(true).open(&path).await {
            let mut line = entry.to_string();
            line.push('\n');
            let _ = f.write_all(line.as_bytes()).await;
        }
    }
}

/// Message content as text: a plain string, or the text parts of a content array
/// (some providers return `[{"type":"thinking",...},{"type":"text","text":...}]`).
fn content_text(c: &Value) -> String {
    match c {
        Value::String(s) => s.clone(),
        Value::Array(parts) => parts
            .iter()
            .filter(|p| p["type"].as_str() == Some("text"))
            .filter_map(|p| p["text"].as_str())
            .collect::<Vec<_>>()
            .join(""),
        _ => String::new(),
    }
}

pub fn now_ms() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis() as u64).unwrap_or(0)
}

/// Parse a model reply as a JSON object, tolerating fences or surrounding prose.
pub fn parse_json(s: &str) -> Result<Value> {
    if let Ok(v) = serde_json::from_str::<Value>(s.trim()) {
        if v.is_object() {
            return Ok(v);
        }
    }
    let start = s.find('{').ok_or_else(|| anyhow!("no JSON object in reply"))?;
    let end = s.rfind('}').ok_or_else(|| anyhow!("no JSON object in reply"))?;
    let v: Value = serde_json::from_str(&s[start..=end]).context("reply JSON")?;
    if !v.is_object() {
        return Err(anyhow!("reply is not a JSON object"));
    }
    Ok(v)
}
