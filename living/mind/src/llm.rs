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
    /// Output cap: a reply is a few thousand tokens at most; a runaway generation is cut off
    /// (and then repaired or retried) instead of running to tens of thousands of tokens.
    /// `null` for endpoints that reject output limits.
    #[serde(default = "max_tokens")]
    pub max_tokens: Option<u32>,
    /// A profile to send calls to when this one is at its rate limit: calls in flight are
    /// kept within a window that grows while calls succeed and shrinks on each HTTP 429, so
    /// this profile runs just below its provider's limit and the rest overflow.
    #[serde(default)]
    pub overflow: Option<String>,
}

fn yes() -> bool {
    true
}

fn max_tokens() -> Option<u32> {
    Some(8000)
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
    /// Profiles by life stage (e.g. children think with a small model).
    #[serde(default)]
    pub stages: HashMap<String, String>,
}

pub struct Llm {
    http: reqwest::Client,
    models: ModelsFile,
    keys: HashMap<String, String>,
    journal: PathBuf,
    budget: Budget,
    windows: std::sync::Mutex<HashMap<String, Window>>,
    gates: std::sync::Mutex<HashMap<String, Gate>>,
}

/// Reachability of a provider (by base URL). When a request cannot reach it (DNS, no route,
/// refused, timed out), calls to it wait instead of failing at once; one probe at a time goes
/// out, with a pause that doubles from 2 s to a minute, until the provider answers again. An
/// outage then costs a paused mind, not hundreds of failed calls a minute.
#[derive(Default)]
struct Gate {
    down_since: Option<Instant>,
    retry_at: Option<Instant>,
    pause: Duration,
    probing: bool,
    held: u64,
}

const GATE_PAUSE_MIN: Duration = Duration::from_secs(2);
const GATE_PAUSE_MAX: Duration = Duration::from_secs(60);

/// Adaptive in-flight limit for a profile with an overflow (additive increase while calls
/// succeed, multiplicative decrease on a rate limit). Separate mind processes sharing one
/// provider key each back off on their own 429s and settle on a fair share of the limit.
struct Window {
    limit: f64,
    in_flight: u32,
    sent: u64,
    overflowed: u64,
    limited: u64,
    logged: Instant,
}

const WINDOW_START: f64 = 8.0;
const WINDOW_MIN: f64 = 1.0;
const WINDOW_MAX: f64 = 128.0;

impl Window {
    fn new() -> Self {
        Self { limit: WINDOW_START, in_flight: 0, sent: 0, overflowed: 0, limited: 0, logged: Instant::now() }
    }
}

/// A global calls-per-minute budget (token bucket, ~15 s of burst). Deliberation may use the
/// whole bucket; deferrable work (consolidation, reorganization, identities) only runs while
/// more than a quarter of it is left, so thinking in the moment keeps priority under load.
struct Budget {
    per_min: f64,
    state: std::sync::Mutex<(f64, std::time::Instant)>,
}

impl Budget {
    fn new(per_min: f64) -> Self {
        Self { per_min, state: std::sync::Mutex::new((per_min / 4.0, std::time::Instant::now())) }
    }

    async fn admit(&self, purpose: &str) {
        if self.per_min <= 0.0 {
            return;
        }
        let cap = (self.per_min / 4.0).max(2.0);
        let reserve = if purpose == "deliberate" { 0.0 } else { cap * 0.25 };
        loop {
            {
                let mut s = self.state.lock().unwrap();
                let now = std::time::Instant::now();
                s.0 = (s.0 + now.duration_since(s.1).as_secs_f64() * self.per_min / 60.0).min(cap);
                s.1 = now;
                if s.0 >= 1.0 + reserve {
                    s.0 -= 1.0;
                    return;
                }
            }
            tokio::time::sleep(std::time::Duration::from_millis(250)).await;
        }
    }
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
        let per_min = std::env::var("LIVING_LLM_PER_MIN").ok().and_then(|v| v.parse().ok()).unwrap_or(0.0);
        log::info!("LLM budget: {} (LIVING_LLM_PER_MIN; 0 = unlimited)", if per_min > 0.0 { format!("{per_min} calls/min") } else { "unlimited".into() });
        Ok(Self { http, models, keys, journal, budget: Budget::new(per_min), windows: Default::default(), gates: Default::default() })
    }

    /// Profile for a character: explicit assignment, then rotation, then default.
    /// The most reliable profile, used when another produced an unusable reply.
    pub fn default_profile(&self) -> String {
        self.models.default.clone()
    }

    /// The profile for a life stage, if the configuration names one.
    pub fn stage_profile(&self, stage: &str) -> Option<String> {
        self.models.stages.get(stage).filter(|p| self.keys.contains_key(*p)).cloned()
    }

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
        self.budget.admit(purpose).await;
        // A profile with an overflow runs within its window; beyond it, or on a rate limit,
        // the call goes to the overflow at once instead of waiting.
        if let Some(over) = self.overflow_of(profile) {
            if !self.window_enter(profile) {
                return self.chat_routed(&over, purpose, actor, messages).await;
            }
            let r = self.chat_once(profile, purpose, actor, messages).await;
            let limited = matches!(&r, Err(e) if format!("{e:#}").contains("HTTP 429"));
            self.window_leave(profile, limited);
            return match r {
                Err(_) if limited => self.chat_routed(&over, purpose, actor, messages).await,
                Err(e) => {
                    log::warn!("{actor}: {profile} failed ({e:#}); trying {over}");
                    self.chat_routed(&over, purpose, actor, messages).await
                }
                ok => ok,
            };
        }
        self.chat_routed(profile, purpose, actor, messages).await
    }

    fn overflow_of(&self, profile: &str) -> Option<String> {
        self.models.profiles.get(profile)?.overflow.clone().filter(|o| o != profile && self.keys.contains_key(o))
    }

    /// Take a place in the profile's window, or say it is full (the call overflows).
    fn window_enter(&self, profile: &str) -> bool {
        let mut ws = self.windows.lock().unwrap();
        let w = ws.entry(profile.to_string()).or_insert_with(Window::new);
        if w.logged.elapsed() >= Duration::from_secs(60) {
            log::info!(
                "{profile}: window {:.1} calls in flight; last minute {} sent, {} rate-limited, {} overflowed",
                w.limit, w.sent, w.limited, w.overflowed
            );
            (w.sent, w.limited, w.overflowed, w.logged) = (0, 0, 0, Instant::now());
        }
        if (w.in_flight as f64) < w.limit.floor().max(WINDOW_MIN) {
            w.in_flight += 1;
            w.sent += 1;
            true
        } else {
            w.overflowed += 1;
            false
        }
    }

    fn window_leave(&self, profile: &str, limited: bool) {
        let mut ws = self.windows.lock().unwrap();
        let Some(w) = ws.get_mut(profile) else { return };
        // Grow only while the window is in use; an idle window would drift above the limit.
        let full = w.in_flight as f64 + 1.0 >= w.limit.floor();
        w.in_flight = w.in_flight.saturating_sub(1);
        if limited {
            w.limited += 1;
            w.overflowed += 1;
            w.limit = (w.limit * 0.7).max(WINDOW_MIN);
        } else if full {
            w.limit = (w.limit + 1.0 / w.limit).min(WINDOW_MAX);
        }
    }

    /// One call on a given profile, with rate-limit retries and the default as fallback.
    async fn chat_routed(&self, profile: &str, purpose: &str, actor: &str, messages: &[Msg]) -> Result<Reply> {
        // A rate limit (HTTP 429) passes: wait with growing, jittered pauses and try again on
        // the same model before giving up or falling back.
        let mut first = self.chat_once(profile, purpose, actor, messages).await;
        for attempt in 0..3u32 {
            match &first {
                Err(e) if format!("{e:#}").contains("HTTP 429") => {
                    let jitter = now_ms() % 1000;
                    tokio::time::sleep(Duration::from_millis(1500 * 2u64.pow(attempt) + jitter)).await;
                    first = self.chat_once(profile, purpose, actor, messages).await;
                }
                _ => break,
            }
        }
        match first {
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
        if let Some(m) = p.max_tokens {
            body["max_tokens"] = json!(m);
        }
        if p.json_mode {
            body["response_format"] = json!({"type": "json_object"});
        }
        if let Some(e) = p.reasoning_effort.get(purpose) {
            body["reasoning_effort"] = json!(e);
        }
        let host = p.base_url.clone();
        self.gate_enter(&host).await;
        let started = Instant::now();
        let url = format!("{}/chat/completions", p.base_url.trim_end_matches('/'));
        let mut unreachable = false;
        let result = async {
            let resp = match self.http.post(&url).bearer_auth(key).json(&body).send().await {
                Ok(r) => r,
                Err(e) => {
                    unreachable = e.is_connect() || e.is_timeout() || e.is_request();
                    return Err(anyhow::Error::new(e).context("request"));
                }
            };
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
        self.gate_leave(&host, unreachable);
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

    /// Wait while the provider is unreachable; one caller at a time probes it.
    async fn gate_enter(&self, host: &str) {
        let mut counted = false;
        loop {
            {
                let mut gs = self.gates.lock().unwrap();
                let g = gs.entry(host.to_string()).or_default();
                match g.retry_at {
                    None => return,
                    Some(at) if !g.probing && Instant::now() >= at => {
                        g.probing = true;
                        return;
                    }
                    _ => {
                        if !counted {
                            g.held += 1;
                            counted = true;
                        }
                    }
                }
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }
    }

    fn gate_leave(&self, host: &str, unreachable: bool) {
        let mut gs = self.gates.lock().unwrap();
        let g = gs.entry(host.to_string()).or_default();
        g.probing = false;
        if unreachable {
            g.pause = if g.down_since.is_none() { GATE_PAUSE_MIN } else { (g.pause * 2).min(GATE_PAUSE_MAX) };
            if g.down_since.is_none() {
                g.down_since = Some(Instant::now());
                log::warn!("{host} unreachable: holding model calls, probing every {:?} up to {:?}", GATE_PAUSE_MIN, GATE_PAUSE_MAX);
            }
            g.retry_at = Some(Instant::now() + g.pause);
        } else if let Some(since) = g.down_since.take() {
            log::warn!("{host} reachable again after {:.0} s; {} calls were held meanwhile", since.elapsed().as_secs_f64(), g.held);
            *g = Gate::default();
        }
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
    let v: Value = repair(&s[start..=end]).context("reply JSON")?;
    if !v.is_object() {
        return Err(anyhow!("reply is not a JSON object"));
    }
    Ok(v)
}

/// Parse JSON, repairing the slips small models make: a stray `}`/`]` where a value is
/// expected, and trailing commas. Uses the parser's own error position; bounded retries.
fn repair(text: &str) -> serde_json::Result<Value> {
    let mut t = text.to_string();
    let mut last = serde_json::from_str::<Value>(&t);
    for _ in 0..12 {
        let Err(e) = &last else { break };
        let msg = e.to_string();
        // Byte offset of the error from line/column.
        let (line, col) = (e.line(), e.column());
        let offset = t.split_inclusive('\n').take(line.saturating_sub(1)).map(|l| l.len()).sum::<usize>() + col.saturating_sub(1);
        let bytes = t.as_bytes();
        if offset >= bytes.len() {
            break;
        }
        if msg.contains("expected value") && matches!(bytes[offset], b'}' | b']') {
            // Drop the stray closer and a comma right after it.
            let mut end = offset + 1;
            while end < bytes.len() && (bytes[end] as char).is_whitespace() {
                end += 1;
            }
            if end < bytes.len() && bytes[end] == b',' {
                end += 1;
            }
            t.replace_range(offset..end, "");
        } else if msg.contains("trailing comma") {
            // The comma precedes the reported closer.
            if let Some(i) = t[..offset.min(t.len())].rfind(',') {
                t.replace_range(i..i + 1, "");
            } else {
                break;
            }
        } else {
            break;
        }
        last = serde_json::from_str::<Value>(&t);
    }
    last
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A provider that cannot be reached holds later calls until a probe gets through.
    #[tokio::test]
    async fn unreachable_provider_holds_calls() {
        std::env::set_var("LIVING_TEST_GATE_KEY", "x");
        let models: ModelsFile = serde_json::from_value(json!({
            "default": "dead",
            "profiles": {"dead": {"base_url": "http://127.0.0.1:9/v1", "model": "m", "key_env": "LIVING_TEST_GATE_KEY"}}
        }))
        .unwrap();
        let dir = std::env::temp_dir().join(format!("living-gate-{}", now_ms()));
        let llm = Llm::new(models, dir.clone()).unwrap();
        let msg = [Msg { role: "user", content: "hi".into() }];
        let t = Instant::now();
        assert!(llm.chat("dead", "think", "a", &msg).await.is_err());
        assert!(t.elapsed() < Duration::from_millis(1500), "the first failure is immediate");
        let t = Instant::now();
        assert!(llm.chat("dead", "think", "a", &msg).await.is_err());
        assert!(t.elapsed() >= GATE_PAUSE_MIN, "the next call waits for the probe: {:?}", t.elapsed());
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn repairs_small_model_slips() {
        let v = parse_json("{\n  \"remember\": [],\n  \"nodes\": [\n    },\n    {\"key\": \"self\"}\n  ],\n  \"edges\": [1, 2,],\n}").unwrap();
        assert_eq!(v["nodes"][0]["key"], "self");
        assert_eq!(v["edges"].as_array().unwrap().len(), 2);
    }
}
