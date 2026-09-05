//! Provider protocols only. This module has no dependency on simulation action types.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::Duration;
use tokio::{sync::watch, time::Instant};
mod sse;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum BackendConfig {
    OpenaiCompatible {
        model: String,
        base_url: String,
        auth: ChatAuth,
        capabilities: ChatCapabilities,
        #[serde(default)]
        reasoning_effort: Option<Effort>,
        #[serde(default)]
        stream: bool,
    },
    #[serde(rename = "openrouter")]
    OpenRouter {
        model: String,
        provider: String,
        #[serde(default = "key_env")]
        credential_env: String,
        #[serde(default)]
        reasoning: Option<ReasoningBudget>,
    },
    Ollama {
        model: String,
        #[serde(default = "ollama_url")]
        endpoint: String,
        #[serde(default = "context_size")]
        num_ctx: u32,
        #[serde(default = "keep_alive")]
        keep_alive: String,
    },
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ChatAuth {
    BearerEnv { credential_env: String },
    None,
}
/// Operator-declared endpoint support, not a claim of remote discovery.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChatCapabilities {
    pub response_modes: Vec<StructuredOutput>,
    #[serde(default)]
    pub reasoning_efforts: Vec<Effort>,
    pub token_limit_field: TokenLimitField,
    #[serde(default)]
    pub temperature: bool,
    #[serde(default)]
    pub seed: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TokenLimitField {
    MaxTokens,
    MaxCompletionTokens,
    Unsupported,
}

fn credential_name(name: &str) -> Result<(), String> {
    if name.is_empty()
        || name.len() > 200
        || !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
    {
        return Err("credential_env must be an environment variable name, never a key".into());
    }
    Ok(())
}
fn credential(name: &str) -> Result<String, String> {
    std::env::var(name).ok().filter(|s| !s.trim().is_empty())
        .ok_or_else(||format!("set the credential environment variable {name}; do not put keys in run configuration"))
}
fn chat_base(base: &str) -> Result<String, String> {
    let u = reqwest::Url::parse(base).map_err(|_| "invalid Chat Completions base URL")?;
    if !matches!(u.scheme(), "http" | "https")
        || u.host_str().is_none()
        || !u.username().is_empty()
        || u.password().is_some()
        || u.query().is_some()
        || u.fragment().is_some()
    {
        return Err(
            "base_url must be an HTTP(S) API base without credentials, query or fragment".into(),
        );
    }
    if u.path()
        .trim_end_matches('/')
        .ends_with("/chat/completions")
    {
        return Err(
            "base_url must be the API base, not the full /chat/completions endpoint".into(),
        );
    }
    // Append to the complete normalized prefix, never replace its final segment.
    Ok(u.as_str().trim_end_matches('/').into())
}
fn key_env() -> String {
    "OPENROUTER_API_KEY".into()
}
fn ollama_url() -> String {
    "http://127.0.0.1:11434".into()
}
fn context_size() -> u32 {
    16384
}
fn keep_alive() -> String {
    "5m".into()
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "mode", rename_all = "snake_case", deny_unknown_fields)]
pub enum ReasoningBudget {
    Effort { effort: Effort },
    Tokens { max_tokens: u32 },
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Effort {
    None,
    Minimal,
    Low,
    Medium,
    High,
    Xhigh,
    Max,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StructuredOutput {
    JsonSchema,
    JsonObject,
    PromptJson,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub backend: BackendConfig,
    #[serde(default = "format")]
    pub structured_output: StructuredOutput,
    #[serde(default = "deadline")]
    pub deadline_ms: u64,
    #[serde(default = "attempts")]
    pub max_attempts: u8,
    #[serde(default = "backoff")]
    pub retry_backoff_ms: u64,
    #[serde(default = "tokens")]
    pub max_output_tokens: Option<u32>,
    #[serde(default)]
    pub temperature: Option<f64>,
    #[serde(default)]
    pub seed: Option<u64>,
}
fn format() -> StructuredOutput {
    StructuredOutput::JsonSchema
}
fn deadline() -> u64 {
    90_000
}
fn attempts() -> u8 {
    1
}
fn backoff() -> u64 {
    500
}
fn tokens() -> Option<u32> {
    Some(6000)
}
impl Config {
    pub fn ollama(model: String, endpoint: String, seed: u64) -> Self {
        Self {
            backend: BackendConfig::Ollama {
                model,
                endpoint,
                num_ctx: context_size(),
                keep_alive: keep_alive(),
            },
            structured_output: format(),
            deadline_ms: deadline(),
            max_attempts: 1,
            retry_backoff_ms: backoff(),
            max_output_tokens: tokens(),
            temperature: Some(0.6),
            seed: Some(seed),
        }
    }
    pub fn model(&self) -> &str {
        match &self.backend {
            BackendConfig::Ollama { model, .. }
            | BackendConfig::OpenRouter { model, .. }
            | BackendConfig::OpenaiCompatible { model, .. } => model,
        }
    }
    pub fn kind(&self) -> &'static str {
        match self.backend {
            BackendConfig::Ollama { .. } => "ollama",
            BackendConfig::OpenRouter { .. } => "openrouter",
            BackendConfig::OpenaiCompatible { .. } => "openai_compatible",
        }
    }
    pub fn validate(&self) -> Result<(), String> {
        if self.model().trim().is_empty()
            || self.model().len() > 200
            || self.model().contains(char::is_whitespace)
        {
            return Err("an explicit model ID is required".into());
        }
        if !(1..=300_000).contains(&self.deadline_ms)
            || !(1..=2).contains(&self.max_attempts)
            || self.retry_backoff_ms > 30_000
            || self
                .max_output_tokens
                .is_some_and(|n| !(1..=8192).contains(&n))
            || self
                .temperature
                .is_some_and(|t| !t.is_finite() || !(0.0..=2.0).contains(&t))
        {
            return Err(
                "invalid deadline, attempts, backoff, output-token limit or temperature".into(),
            );
        }
        let unsupported = matches!(
            &self.backend,
            BackendConfig::OpenaiCompatible {
                capabilities: ChatCapabilities {
                    token_limit_field: TokenLimitField::Unsupported,
                    ..
                },
                ..
            }
        );
        if unsupported != self.max_output_tokens.is_none() {
            return Err("max_output_tokens must be explicit null only when token_limit_field is unsupported; supported backends require a numeric cap".into());
        }
        match &self.backend {
            BackendConfig::OpenaiCompatible {
                base_url,
                auth,
                capabilities,
                reasoning_effort,
                ..
            } => {
                chat_base(base_url)?;
                if reasoning_effort.as_ref().is_some_and(|effort| !capabilities.reasoning_efforts.contains(effort)) {
                    return Err("reasoning effort was requested but is not declared supported by this endpoint".into());
                }
                if let ChatAuth::BearerEnv { credential_env } = auth {
                    credential_name(credential_env)?;
                }
                if !capabilities
                    .response_modes
                    .contains(&self.structured_output)
                {
                    return Err(
                        "selected response mode is not declared supported by this endpoint".into(),
                    );
                }
                if self.temperature.is_some() && !capabilities.temperature {
                    return Err("temperature was requested but is not declared supported".into());
                }
                if self.seed.is_some() && !capabilities.seed {
                    return Err("seed was requested but is not declared supported".into());
                }
            }
            BackendConfig::OpenRouter {
                model,
                provider,
                credential_env,
                reasoning,
            } => {
                if self.structured_output != StructuredOutput::JsonSchema {
                    return Err("OpenRouter specialization requires json_schema mode".into());
                }
                if !model.contains('/')
                    || model.starts_with("openrouter/")
                    || model.contains(':')
                    || !model
                        .chars()
                        .all(|c| c.is_ascii_alphanumeric() || "-._/".contains(c))
                {
                    return Err("OpenRouter requires an explicit model slug without automatic routing variants".into());
                }
                if provider.is_empty()
                    || !provider
                        .chars()
                        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || "-._/".contains(c))
                {
                    return Err("OpenRouter requires an explicit provider/endpoint slug".into());
                }
                if credential_env.is_empty()
                    || !credential_env
                        .chars()
                        .all(|c| c.is_ascii_alphanumeric() || c == '_')
                {
                    return Err(
                        "credential_env must be an environment variable name, never a key".into(),
                    );
                }
                if matches!(reasoning,Some(ReasoningBudget::Tokens{max_tokens}) if *max_tokens==0 || Some(*max_tokens)>=self.max_output_tokens)
                {
                    return Err("reasoning token budget must be positive and smaller than max_output_tokens".into());
                }
            }
            BackendConfig::Ollama {
                endpoint,
                num_ctx,
                keep_alive,
                ..
            } => {
                if self.structured_output != StructuredOutput::JsonSchema {
                    return Err("native Ollama adapter requires json_schema mode".into());
                }
                let u = reqwest::Url::parse(endpoint).map_err(|_| "invalid Ollama endpoint")?;
                if u.scheme() != "http"
                    || !matches!(u.host_str(), Some("localhost" | "127.0.0.1" | "[::1]"))
                    || !u.username().is_empty()
                    || u.password().is_some()
                    || u.query().is_some()
                    || u.fragment().is_some()
                    || u.path() != "/"
                {
                    return Err(
                        "Ollama adapter requires a credential-free local HTTP origin".into(),
                    );
                }
                if !(1024..=131072).contains(num_ctx)
                    || keep_alive.len() > 20
                    || keep_alive.is_empty()
                {
                    return Err("invalid Ollama context/keep_alive settings".into());
                }
            }
        }
        Ok(())
    }
}

#[derive(Clone)]
pub struct Backend {
    pub config: Config,
    client: reqwest::Client,
    secret: Option<String>,
    base: String,
}
// Never derive Debug/Serialize: the credential exists only in this transport object.
#[derive(Clone, Debug, Serialize)]
pub struct Reply {
    pub status: Option<u16>,
    pub response_body: String,
    pub response_bytes_hex: Option<String>,
    pub stream: Value,
    pub raw_output: String,
    pub served_model: Option<String>,
    pub served_provider: Option<String>,
    pub usage: Value,
    pub finish_reason: Option<String>,
    pub error: Option<String>,
    pub retryable: bool,
    pub retry_after_ms: Option<u64>,
    pub body_truncated: bool,
    pub body_redacted: bool,
}
impl Reply {
    pub fn failure(error: &str) -> Self {
        Self {
            status: None,
            response_body: String::new(),
            response_bytes_hex: None,
            stream: Value::Null,
            raw_output: String::new(),
            served_model: None,
            served_provider: None,
            usage: Value::Null,
            finish_reason: None,
            error: Some(error.into()),
            retryable: false,
            retry_after_ms: None,
            body_truncated: false,
            body_redacted: false,
        }
    }
}
impl Backend {
    pub fn new(config: Config) -> Result<Self, String> {
        config.validate()?;
        let (base, secret) = match &config.backend {
            BackendConfig::OpenaiCompatible { base_url, auth, .. } => (
                chat_base(base_url)?,
                match auth {
                    ChatAuth::None => None,
                    ChatAuth::BearerEnv { credential_env } => Some(credential(credential_env)?),
                },
            ),
            BackendConfig::OpenRouter { credential_env, .. } => (
                "https://openrouter.ai/api/v1".into(),
                Some(credential(credential_env)?),
            ),
            BackendConfig::Ollama { endpoint, .. } => (endpoint.trim_end_matches('/').into(), None),
        };
        let client = reqwest::Client::builder()
            .user_agent("sao-reasoning/1.0")
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(10))
            .build()
            .map_err(|_| "HTTP client initialization failed")?;
        Ok(Self {
            config,
            client,
            secret,
            base,
        })
    }
    pub fn redact(&self, text: &str) -> String {
        match &self.secret {
            Some(s) => text.replace(s, "[REDACTED]"),
            None => text.into(),
        }
    }
    pub fn safe_value(&self, value: &Value) -> Value {
        match value {
            Value::String(s) => json!(self.redact(s)),
            Value::Array(a) => Value::Array(a.iter().map(|v| self.safe_value(v)).collect()),
            Value::Object(o) => Value::Object(
                o.iter()
                    .map(|(k, v)| {
                        (
                            self.redact(k),
                            if ["authorization", "api_key", "apikey", "access_token"]
                                .contains(&k.to_lowercase().as_str())
                            {
                                json!("[REDACTED]")
                            } else {
                                self.safe_value(v)
                            },
                        )
                    })
                    .collect(),
            ),
            v => v.clone(),
        }
    }
    pub fn payload(&self, messages: Value, schema: Value) -> Value {
        let c = &self.config;
        match &c.backend {
            BackendConfig::OpenaiCompatible {
                model,
                capabilities,
                reasoning_effort,
                stream,
                ..
            } => {
                let mut v = json!({"model":model,"messages":messages,"stream":stream});
                if let Some(effort) = reasoning_effort { v["reasoning_effort"] = json!(effort); }
                let limit = match capabilities.token_limit_field {
                    TokenLimitField::MaxTokens => Some("max_tokens"),
                    TokenLimitField::MaxCompletionTokens => Some("max_completion_tokens"),
                    TokenLimitField::Unsupported => None,
                };
                if let Some(limit) = limit {
                    v[limit] = json!(c.max_output_tokens);
                }
                match c.structured_output {
                    StructuredOutput::JsonSchema => {
                        v["response_format"] = json!({"type":"json_schema","json_schema":{"name":"npc_decision","strict":true,"schema":strict_provider_schema(schema)}})
                    }
                    StructuredOutput::JsonObject => {
                        v["response_format"] = json!({"type":"json_object"})
                    }
                    StructuredOutput::PromptJson => (),
                }
                if let Some(t) = c.temperature {
                    v["temperature"] = json!(t);
                }
                if let Some(seed) = c.seed {
                    v["seed"] = json!(seed);
                }
                v
            }
            BackendConfig::OpenRouter {
                model,
                provider,
                reasoning,
                ..
            } => {
                let schema = strict_provider_schema(schema);
                let mut v = json!({"model":model,"messages":messages,"stream":false,"max_tokens":c.max_output_tokens,"provider":{"only":[provider],"order":[provider],"allow_fallbacks":false,"require_parameters":true},"response_format":{"type":"json_schema","json_schema":{"name":"npc_decision","strict":true,"schema":schema}}});
                if let Some(t) = c.temperature {
                    v["temperature"] = json!(t);
                }
                if let Some(s) = c.seed {
                    v["seed"] = json!(s);
                }
                if let Some(r) = reasoning {
                    v["reasoning"] = match r {
                        ReasoningBudget::Effort { effort } => {
                            json!({"effort":effort,"exclude":true})
                        }
                        ReasoningBudget::Tokens { max_tokens } => {
                            json!({"max_tokens":max_tokens,"exclude":true})
                        }
                    };
                }
                v
            }
            BackendConfig::Ollama {
                model,
                num_ctx,
                keep_alive,
                ..
            } => {
                let mut v = json!({"model":model,"messages":messages,"stream":false,"format":schema,"keep_alive":keep_alive,"options":{"num_predict":c.max_output_tokens,"num_ctx":num_ctx}});
                if let Some(t) = c.temperature {
                    v["options"]["temperature"] = json!(t);
                }
                if let Some(s) = c.seed {
                    v["options"]["seed"] = json!(s);
                }
                v
            }
        }
    }
    pub async fn catalog(&self) -> Result<Value, String> {
        let path = match &self.config.backend {
            BackendConfig::OpenaiCompatible {
                capabilities,
                base_url,
                ..
            } => {
                return Ok(
                    json!({"capability_source":"operator_configuration","remote_capabilities_verified":false,"base_url":base_url,"declared_capabilities":capabilities,"note":"No catalog endpoint or network capability discovery is assumed; request errors never trigger a mode downgrade"}),
                )
            }
            BackendConfig::OpenRouter { model, .. } => format!("/models/{model}/endpoints"),
            BackendConfig::Ollama { .. } => "/api/tags".into(),
        };
        let r = self
            .client
            .get(format!("{}{path}", self.base))
            .timeout(Duration::from_secs(15))
            .send()
            .await
            .map_err(|_| "capability/catalog request failed")?;
        if !r.status().is_success() {
            return Err(format!("capability/catalog HTTP {}", r.status().as_u16()));
        }
        let mut value: Value = r
            .json()
            .await
            .map_err(|_| "invalid capability/catalog JSON")?;
        if let BackendConfig::OpenRouter {
            model,
            reasoning: Some(_),
            ..
        } = &self.config.backend
        {
            let response = self
                .client
                .get(format!("{}/model/{model}", self.base))
                .timeout(Duration::from_secs(15))
                .send()
                .await
                .map_err(|_| "reasoning capability request failed")?;
            if !response.status().is_success() {
                return Err("reasoning capability lookup rejected".into());
            }
            value["model_details"] = response
                .json::<Value>()
                .await
                .map_err(|_| "invalid reasoning capability JSON")?;
        }
        Ok(self.safe_value(&value))
    }
    pub fn check_capabilities(&self, catalog: &Value) -> Result<(), String> {
        self.config.validate()?;
        if let BackendConfig::OpenRouter {
            provider,
            reasoning,
            ..
        } = &self.config.backend
        {
            let mut required = vec!["response_format", "structured_outputs", "max_tokens"];
            if self.config.temperature.is_some() {
                required.push("temperature");
            }
            if self.config.seed.is_some() {
                required.push("seed");
            }
            if reasoning.is_some() {
                required.push("reasoning");
            }
            if let Some(budget) = reasoning {
                let declared = &catalog["model_details"]["data"]["reasoning"];
                match budget {
                    ReasoningBudget::Effort { effort } => {
                        let selected = serde_json::to_value(effort).unwrap();
                        let available = declared
                            .get("supported_efforts")
                            .ok_or("model does not advertise supported reasoning efforts")?;
                        if !available.is_null()
                            && !available.as_array().is_some_and(|a| a.contains(&selected))
                        {
                            return Err("model does not support selected reasoning effort".into());
                        }
                        if matches!(effort, Effort::None) && declared["mandatory"] == true {
                            return Err("model requires reasoning; none is unsupported".into());
                        }
                    }
                    ReasoningBudget::Tokens { .. } => {
                        if declared["supports_max_tokens"] != true {
                            return Err(
                                "model does not advertise a reasoning token-budget capability"
                                    .into(),
                            );
                        }
                    }
                }
            }
            let endpoints = catalog["data"]["endpoints"]
                .as_array()
                .ok_or("missing endpoint capability evidence")?;
            let matching: Vec<_> = endpoints
                .iter()
                .filter(|e| {
                    e["tag"]
                        .as_str()
                        .is_some_and(|t| t == provider || t.starts_with(&format!("{provider}/")))
                })
                .collect();
            if matching.is_empty() {
                return Err("selected provider has no advertised endpoints for this model".into());
            }
            // Conservative: all endpoints selected by this slug must support the contract.
            for e in matching {
                let supported = e["supported_parameters"]
                    .as_array()
                    .ok_or("endpoint has no capability declaration")?;
                for parameter in &required {
                    if !supported.iter().any(|s| s == parameter) {
                        return Err(format!("selected endpoint does not advertise required parameter: {parameter}; choose a compatible explicit endpoint"));
                    }
                }
            }
        }
        Ok(())
    }
    pub async fn complete(
        &self,
        payload: &Value,
        deadline: Instant,
        cancel: &mut watch::Receiver<Option<String>>,
    ) -> Reply {
        let started = Instant::now();
        let path = match self.config.backend {
            BackendConfig::OpenRouter { .. } | BackendConfig::OpenaiCompatible { .. } => {
                "/chat/completions"
            }
            BackendConfig::Ollama { .. } => "/api/chat",
        };
        let streaming = matches!(
            self.config.backend,
            BackendConfig::OpenaiCompatible { stream: true, .. }
        );
        let mut req = self
            .client
            .post(format!("{}{path}", self.base))
            .json(payload);
        if streaming {
            req = req.header("accept", "text/event-stream");
        }
        if let Some(secret) = &self.secret {
            req = req.bearer_auth(secret);
        }
        let sent = tokio::select! {
            biased;
            _ = cancel.changed() => return Reply::failure(&format!("cancelled: {}", cancel.borrow().as_deref().unwrap_or("runner disconnected"))),
            _ = tokio::time::sleep_until(deadline) => return Reply::failure("wall-time deadline exceeded; delivery and cost may be unknown"),
            result = req.send() => result,
        };
        let mut response = match sent {
            Ok(r) => r,
            Err(_) => return Reply::failure("transport failure; delivery and cost may be unknown"),
        };
        let headers_elapsed_ms = started.elapsed().as_millis();
        let mut first_byte_elapsed_ms = None;
        let status = response.status().as_u16();
        let retry_after_ms = response
            .headers()
            .get("retry-after")
            .and_then(|s| s.to_str().ok())
            .and_then(|s| s.parse::<u64>().ok())
            .map(|s| s.saturating_mul(1000));
        // HTTP errors are regular HTTP bodies, even for a requested stream.
        let is_sse = streaming && response.status().is_success();
        let mut parser = sse::Parser::new(status);
        let mut bytes = Vec::new();
        let mut wire_bytes = 0usize;
        let mut terminal = None;
        let mut truncated = false;
        loop {
            let next = tokio::select! {
                biased;
                _ = cancel.changed() => Err(format!("cancelled: {}; partial response retained", cancel.borrow().as_deref().unwrap_or("runner disconnected"))),
                _ = tokio::time::sleep_until(deadline) => Err("wall-time deadline exceeded; partial response retained; usage/cost may be unknown".into()),
                result = response.chunk() => result.map_err(|_| "response body transport failure; partial evidence retained".to_string()),
            };
            match next {
                Ok(Some(chunk)) => {
                    first_byte_elapsed_ms.get_or_insert_with(|| started.elapsed().as_millis());
                    // Retain a bounded raw prefix independently of parsing the stream.
                    // SSE envelope overhead must not consume the generated-content budget.
                    let wire_remaining = (4 * 1024 * 1024usize).saturating_sub(wire_bytes);
                    let available = if is_sse {
                        &chunk[..chunk.len().min(wire_remaining)]
                    } else {
                        &chunk[..]
                    };
                    wire_bytes += available.len();
                    let remaining = 131072usize.saturating_sub(bytes.len());
                    bytes.extend_from_slice(&available[..available.len().min(remaining)]);
                    if available.len() > remaining {
                        truncated = true;
                    }
                    if is_sse {
                        parser.feed(available, self);
                        if chunk.len() > wire_remaining {
                            terminal = Some(
                                "provider SSE exceeds 4 MiB total wire limit; captured prefix only"
                                    .into(),
                            );
                            break;
                        }
                    } else if truncated {
                        terminal =
                            Some("provider body exceeds 128 KiB; captured prefix only".into());
                        break;
                    }
                    if is_sse && (parser.done || parser.failed()) {
                        break;
                    }
                }
                Ok(None) => break,
                Err(error) => {
                    terminal = Some(error);
                    break;
                }
            }
        }
        let body = String::from_utf8_lossy(&bytes);
        let mut safe_body = self.redact(&body);
        let mut reply = if is_sse {
            // Never retain a credential split across content-delta frames or typed secret fields.
            let sensitive = parser.sensitive
                || self.redact(&parser.reply.raw_output) != parser.reply.raw_output;
            if sensitive {
                safe_body = "[REDACTED: provider stream contained credential material]".into();
            }
            let stream = json!({"headers_elapsed_ms":headers_elapsed_ms,"first_byte_elapsed_ms":first_byte_elapsed_ms,"data_events":parser.data_events,"comment_lines":parser.comment_lines,"done_received":parser.done,"captured_bytes":bytes.len(),"wire_bytes":wire_bytes,"capture_truncated":truncated,"wire_limit_bytes":4*1024*1024});
            let mut reply = parser.finish();
            reply.stream = stream;
            reply.raw_output = self.redact(&reply.raw_output);
            reply
        } else {
            if let Ok(parsed) = serde_json::from_str::<Value>(&safe_body) {
                let safe = self.safe_value(&parsed);
                if safe != parsed {
                    safe_body = safe.to_string();
                }
            }
            self.parse(status, &safe_body)
        };
        reply.response_body = safe_body;
        reply.body_redacted = body != reply.response_body;
        // The exact redacted byte prefix is also retained as hex if invalid UTF-8 prevents
        // an exact text representation. Credential matches are removed before encoding.
        if std::str::from_utf8(&bytes).is_err() {
            let mut safe_bytes = bytes;
            if let Some(secret) = &self.secret {
                while let Some(pos) = safe_bytes
                    .windows(secret.len())
                    .position(|w| w == secret.as_bytes())
                {
                    safe_bytes.splice(pos..pos + secret.len(), b"[REDACTED]".iter().copied());
                    reply.body_redacted = true;
                }
            }
            if !reply
                .response_body
                .starts_with("[REDACTED: provider stream")
            {
                reply.response_bytes_hex =
                    Some(safe_bytes.iter().map(|b| format!("{b:02x}")).collect());
            }
            if !is_sse || !truncated {
                terminal = Some(
                    "invalid UTF-8 in provider body; byte prefix retained subject to redaction"
                        .into(),
                );
            }
        }
        reply.retry_after_ms = retry_after_ms;
        reply.body_truncated = truncated;
        if let Some(error) = terminal {
            reply.error = Some(error);
            reply.retryable = false;
        }
        // Once a successful streaming HTTP response starts, no retry can be safe.
        if is_sse {
            reply.retryable = false;
        }
        reply
    }
    pub fn parse(&self, status: u16, body: &str) -> Reply {
        let mut r = Reply {
            status: Some(status),
            response_body: body.into(),
            ..Reply::failure("malformed provider JSON")
        };
        let v: Value = match serde_json::from_str(body) {
            Ok(v) => v,
            Err(_) => {
                if !(200..300).contains(&status) {
                    r.error = Some(format!(
                        "provider HTTP {status} failure with non-JSON body; see recorded response"
                    ));
                }
                return r;
            }
        };
        r.served_model = v["model"].as_str().map(str::to_string);
        r.served_provider = v["provider"].as_str().map(str::to_string);
        r.usage = v.get("usage").cloned().unwrap_or(Value::Null);
        if !(200..300).contains(&status) || v.get("error").is_some_and(|e| !e.is_null()) {
            r.error = Some(format!(
                "provider rejected request (HTTP {status}); see recorded response"
            ));
            // Retry only definite transient HTTP rejection. No retry on ambiguous delivery.
            r.retryable = matches!(status, 429 | 503);
            return r;
        }
        match self.config.backend {
            BackendConfig::OpenRouter { .. } | BackendConfig::OpenaiCompatible { .. } => {
                let choice = &v["choices"][0];
                r.raw_output = choice["message"]["content"].as_str().unwrap_or("").into();
                r.finish_reason = choice["finish_reason"].as_str().map(str::to_string);
                if choice["message"]
                    .get("refusal")
                    .is_some_and(|v| !v.is_null() && v.as_str() != Some(""))
                {
                    r.error = Some("model refusal".into());
                    return r;
                }
                if r.finish_reason.as_deref() != Some("stop") {
                    r.error = Some("incomplete or unsupported finish reason".into());
                    return r;
                }
            }
            BackendConfig::Ollama { .. } => {
                r.raw_output = v["message"]["content"].as_str().unwrap_or("").into();
                r.finish_reason = v["done_reason"].as_str().map(str::to_string);
                r.usage = json!({"prompt_tokens":v.get("prompt_eval_count"),"completion_tokens":v.get("eval_count"),"cached_prompt_tokens":v.get("prompt_eval_cached_count"),"total_duration_ns":v.get("total_duration")});
                if v["done"] != true || r.finish_reason.as_deref() != Some("stop") {
                    r.error = Some("incomplete or unsupported finish reason".into());
                    return r;
                }
            }
        }
        r.error = if r.raw_output.trim().is_empty() {
            Some("empty model output".into())
        } else {
            None
        };
        r
    }
    #[cfg(test)]
    pub fn mock(config: Config, base: String, secret: Option<String>) -> Self {
        Self {
            config,
            base,
            secret,
            client: reqwest::Client::builder()
                .redirect(reqwest::redirect::Policy::none())
                .build()
                .unwrap(),
        }
    }
}

// Rust integer format annotations are not JSON Schema constraints
// and are outside strict provider format vocabularies. Preserve
// the actual integer types/bounds; authority checks Rust ranges.
fn strict_provider_schema(mut schema: Value) -> Value {
    match &mut schema {
        Value::Object(o) => {
            if o.get("format")
                .and_then(Value::as_str)
                .is_some_and(|f| matches!(f, "int32" | "uint32" | "uint64"))
            {
                o.remove("format");
            }
            for v in o.values_mut() {
                *v = strict_provider_schema(v.take());
            }
        }
        Value::Array(a) => {
            for v in a {
                *v = strict_provider_schema(v.take());
            }
        }
        _ => (),
    }
    schema
}
