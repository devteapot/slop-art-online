//! OpenAI-compatible chat client with per-character model profiles and a JSONL journal
//! of every exchange (exact prompts, raw replies, latency, failures).

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};
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
    /// Optional alternate for legacy configs. Every alternate uses its own pacing.
    #[serde(default)]
    pub overflow: Option<String>,
    #[serde(default = "requests_per_minute")]
    pub requests_per_minute: f64,
    #[serde(default)]
    pub tokens_per_minute: Option<u64>,
    #[serde(default)]
    pub prompt_cache_key: bool,
}

fn requests_per_minute() -> f64 {
    60.0
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
    /// Profiles by group: a town, village or band name (see [`group_of`]), so the
    /// communities of one world can think with different models.
    #[serde(default)]
    pub groups: HashMap<String, String>,
}

/// Generations searched for a group through parents (and a bound on cycles).
pub const GROUP_DEPTH: u32 = 8;

/// The group whose model a person thinks with: their own (the `town` or `band` in their
/// background) or, for someone born in the world, the first found through `parent_a` then
/// `parent_b`, up to `depth` generations back. `of(id)` gives a character's own group and
/// parents (`None` for an unknown character).
pub fn group_of(id: u32, of: &dyn Fn(u32) -> Option<(Option<String>, u32, u32)>, depth: u32) -> Option<String> {
    let (own, a, b) = of(id)?;
    if own.is_some() || depth == 0 {
        return own;
    }
    [a, b].into_iter().filter(|p| *p != 0 && *p != id).find_map(|p| group_of(p, of, depth - 1))
}

pub struct Llm {
    http: reqwest::Client,
    models: ModelsFile,
    keys: HashMap<String, String>,
    journal: PathBuf,
    scheduler: Scheduler,
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
    probing: Option<u64>,
    held: u64,
}

const GATE_PAUSE_MIN: Duration = Duration::from_secs(2);
const GATE_PAUSE_MAX: Duration = Duration::from_secs(60);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Lane {
    Interactive,
    Urgent,
    Routine,
    Background,
}

impl Lane {
    pub fn for_purpose(purpose: &str) -> Self {
        match purpose {
            "talk" => Self::Interactive,
            "combat" | "alarm" | "attack" => Self::Urgent,
            "consolidate" | "reorganize" | "identity" => Self::Background,
            _ => Self::Routine,
        }
    }

    pub fn deliberation(reason: &str, player_act: bool) -> Self {
        if player_act {
            return Self::Interactive;
        }
        let reason = reason.to_lowercase();
        if reason
            .split(|c: char| !c.is_alphanumeric())
            .any(|w| matches!(w, "combat" | "fight" | "fighting" | "alarm" | "attack" | "attacked" | "attacking" | "hit" | "danger" | "wound" | "wounded"))
        {
            Self::Urgent
        } else {
            Self::Routine
        }
    }
}

struct Rate {
    ceiling: f64,
    rpm: f64,
    tpm: Option<u64>,
    next: Instant,
    last_sent: Instant,
    blocked_until: Instant,
    last_increase: Instant,
    tokens: VecDeque<(u64, Instant, u64)>,
}

impl Rate {
    fn new(p: &Profile, now: Instant) -> Self {
        Self {
            ceiling: p.requests_per_minute,
            rpm: p.requests_per_minute,
            tpm: p.tokens_per_minute,
            next: now,
            last_sent: now,
            blocked_until: now,
            last_increase: now,
            tokens: VecDeque::new(),
        }
    }

    fn ready_at(&mut self, cost: u64, now: Instant) -> Instant {
        while self.tokens.front().is_some_and(|(_, at, _)| now.duration_since(*at) >= Duration::from_secs(60)) {
            self.tokens.pop_front();
        }
        let mut at = self.next.max(self.blocked_until);
        if let Some(limit) = self.tpm {
            let mut used: u64 = self.tokens.iter().map(|(_, _, n)| n).sum();
            for (_, sent, n) in &self.tokens {
                if used.saturating_add(cost) <= limit {
                    break;
                }
                used = used.saturating_sub(*n);
                at = at.max(*sent + Duration::from_secs(60));
            }
        }
        at
    }

    fn sent(&mut self, id: u64, cost: u64, now: Instant) {
        self.last_sent = now;
        self.next = now + Duration::from_secs_f64(60.0 / self.rpm);
        self.tokens.push_back((id, now, cost));
    }

    fn feedback(&mut self, id: u64, limited: bool, headers: &reqwest::header::HeaderMap, usage: Option<u64>, now: Instant) {
        let number = |name| headers.get(name).and_then(|v| v.to_str().ok()).and_then(|s| s.parse::<f64>().ok()).filter(|n| n.is_finite() && *n >= 0.0);
        if let Some(limit) = number("x-ratelimit-limit-req-minute").filter(|n| *n >= 0.01) {
            self.ceiling = self.ceiling.min(limit * 0.9);
            self.rpm = self.rpm.min(self.ceiling);
        }
        if let Some(limit) = number("x-ratelimit-limit-tokens-minute").filter(|n| *n >= 1.0) {
            let limit = (limit * 0.9).max(1.0) as u64;
            self.tpm = Some(self.tpm.map_or(limit, |old| old.min(limit)));
        }
        if let Some(actual) = usage {
            if let Some((_, _, cost)) = self.tokens.iter_mut().find(|(ticket, _, _)| *ticket == id) {
                *cost = actual;
            }
        }
        if limited {
            self.rpm = (self.rpm * 0.5).max(0.01).min(self.ceiling);
            self.last_increase = now;
            let wait = retry_after(headers, std::time::SystemTime::now()).unwrap_or(Duration::from_secs_f64(60.0 / self.rpm));
            self.blocked_until = self.blocked_until.max(now.checked_add(wait).unwrap_or(now + Duration::from_secs(60)));
            self.next = self.next.max(now + Duration::from_secs_f64(60.0 / self.rpm));
        } else if usage.is_some() && now.duration_since(self.last_increase) >= Duration::from_secs(60) {
            self.rpm = (self.rpm + 1.0).min(self.ceiling);
            self.last_increase = now;
        }
        if number("x-ratelimit-remaining-req-minute") == Some(0.0) || number("x-ratelimit-remaining-tokens-minute") == Some(0.0) {
            self.blocked_until = self.blocked_until.max(now + Duration::from_secs(60));
        }
        self.next = self.next.max(self.last_sent + Duration::from_secs_f64(60.0 / self.rpm));
    }
}

fn retry_after(headers: &reqwest::header::HeaderMap, now: std::time::SystemTime) -> Option<Duration> {
    let value = headers.get("retry-after")?.to_str().ok()?;
    if let Ok(seconds) = value.parse::<f64>() {
        return Duration::try_from_secs_f64(seconds).ok();
    }
    let parts: Vec<_> = value.split_whitespace().collect();
    if parts.len() != 6 || parts[5] != "GMT" {
        return None;
    }
    let day: i64 = parts[1].parse().ok()?;
    let month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].iter().position(|m| *m == parts[2])? as i64 + 1;
    let year: i64 = parts[3].parse().ok()?;
    let clock: Vec<u64> = parts[4].split(':').map(str::parse).collect::<std::result::Result<_, _>>().ok()?;
    if !(1970..=9999).contains(&year) || clock.len() != 3 || clock[0] > 23 || clock[1] > 59 || clock[2] > 59 {
        return None;
    }
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let days_in_month = [31, if leap { 29 } else { 28 }, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if day < 1 || day > days_in_month[month as usize - 1] {
        return None;
    }
    // Gregorian civil date to days since Unix epoch, with March as the first month.
    let y = year - i64::from(month <= 2);
    let era = y / 400;
    let yoe = y - era * 400;
    let m = month + if month > 2 { -3 } else { 9 };
    let days = era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + (153 * m + 2) / 5 + day - 1 - 719468;
    let seconds = u64::try_from(days).ok()? * 86400 + clock[0] * 3600 + clock[1] * 60 + clock[2];
    let at = std::time::UNIX_EPOCH.checked_add(Duration::from_secs(seconds))?;
    Some(at.duration_since(now).unwrap_or_default())
}

struct Waiting {
    id: u64,
    profile: String,
    lane: Lane,
    cost: u64,
}

struct Queue {
    rates: HashMap<String, Rate>,
    hosts: HashMap<String, String>,
    gates: HashMap<String, Gate>,
    waiting: VecDeque<Waiting>,
    sequence: u64,
    in_flight: usize,
    lower_in_flight: usize,
    concurrency: usize,
    global_rpm: f64,
    global_next: Instant,
}

impl Queue {
    fn candidate(&mut self, now: Instant) -> Option<u64> {
        if self.in_flight >= self.concurrency || now < self.global_next {
            return None;
        }
        let lane = self.waiting.iter().map(|w| w.lane).min()?;
        let lower_limit = self.concurrency.saturating_sub((self.concurrency / 4).max(1)).max(1);
        if lane != Lane::Interactive && self.lower_in_flight >= lower_limit {
            return None;
        }
        self.waiting
            .iter()
            .filter(|w| w.lane == lane)
            .find(|w| {
                let gate = self.gates.get(&self.hosts[&w.profile]);
                gate.is_none_or(|g| g.retry_at.is_none_or(|at| g.probing.is_none() && now >= at)) && self.rates.get_mut(&w.profile).unwrap().ready_at(w.cost, now) <= now
            })
            .map(|w| w.id)
    }

    fn start(&mut self, id: u64, now: Instant) -> (Lane, Option<String>) {
        let pos = self.waiting.iter().position(|w| w.id == id).unwrap();
        let w = self.waiting.remove(pos).unwrap();
        self.rates.get_mut(&w.profile).unwrap().sent(id, w.cost, now);
        self.in_flight += 1;
        self.lower_in_flight += usize::from(w.lane != Lane::Interactive);
        if self.global_rpm > 0.0 {
            self.global_next = now + Duration::from_secs_f64(60.0 / self.global_rpm);
        }
        let host = self.hosts[&w.profile].clone();
        let probe = self.gates.get_mut(&host).filter(|g| g.retry_at.is_some()).map(|g| {
            g.probing = Some(id);
            host
        });
        (w.lane, probe)
    }
}

struct Scheduler {
    queue: std::sync::Mutex<Queue>,
    changed: tokio::sync::Notify,
}

struct Admission<'a> {
    scheduler: &'a Scheduler,
    id: u64,
    lane: Option<Lane>,
    probe: Option<String>,
}

impl Drop for Admission<'_> {
    fn drop(&mut self) {
        let mut q = self.scheduler.queue.lock().unwrap();
        if let Some(lane) = self.lane {
            q.in_flight -= 1;
            q.lower_in_flight -= usize::from(lane != Lane::Interactive);
        } else {
            q.waiting.retain(|w| w.id != self.id);
        }
        if let Some(host) = &self.probe {
            let g = q.gates.get_mut(host).unwrap();
            if g.probing == Some(self.id) {
                g.probing = None;
            }
        }
        self.scheduler.changed.notify_waiters();
    }
}

impl Scheduler {
    fn new(models: &ModelsFile, concurrency: usize, global_rpm: f64) -> Self {
        let now = Instant::now();
        Self {
            queue: std::sync::Mutex::new(Queue {
                rates: models.profiles.iter().map(|(name, p)| (name.clone(), Rate::new(p, now))).collect(),
                hosts: models.profiles.iter().map(|(name, p)| (name.clone(), p.base_url.clone())).collect(),
                gates: HashMap::new(),
                waiting: VecDeque::new(),
                sequence: 0,
                in_flight: 0,
                lower_in_flight: 0,
                concurrency,
                global_rpm,
                global_next: now,
            }),
            changed: tokio::sync::Notify::new(),
        }
    }

    async fn admit(&self, profile: &str, lane: Lane, cost: u64) -> Result<Admission<'_>> {
        let id = {
            let mut q = self.queue.lock().unwrap();
            q.sequence += 1;
            let id = q.sequence;
            let host = q.hosts[profile].clone();
            if let Some(g) = q.gates.get_mut(&host).filter(|g| g.retry_at.is_some()) {
                g.held += 1;
            }
            q.waiting.push_back(Waiting { id, profile: profile.into(), lane, cost });
            id
        };
        let mut admission = Admission { scheduler: self, id, lane: None, probe: None };
        loop {
            let changed = self.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            {
                let mut q = self.queue.lock().unwrap();
                if q.rates[profile].tpm.is_some_and(|limit| cost > limit) {
                    return Err(anyhow!("estimated request tokens {cost} exceed {profile} tokens_per_minute"));
                }
                let now = Instant::now();
                if q.candidate(now) == Some(id) {
                    let (lane, probe) = q.start(id, now);
                    admission.lane = Some(lane);
                    admission.probe = probe;
                    self.changed.notify_waiters();
                    return Ok(admission);
                }
            }
            tokio::select! { _ = changed => {}, _ = tokio::time::sleep(Duration::from_millis(50)) => {} }
        }
    }

    fn feedback(&self, profile: &str, id: u64, limited: bool, headers: &reqwest::header::HeaderMap, usage: Option<u64>) {
        self.queue.lock().unwrap().rates.get_mut(profile).unwrap().feedback(id, limited, headers, usage, Instant::now());
        self.changed.notify_waiters();
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
        let per_min: f64 = std::env::var("LIVING_LLM_PER_MIN").ok().and_then(|v| v.parse().ok()).unwrap_or(0.0);
        for (name, p) in &models.profiles {
            if !p.requests_per_minute.is_finite() || p.requests_per_minute < 0.01 || p.requests_per_minute > 60000.0 || p.tokens_per_minute == Some(0) {
                return Err(anyhow!("profile {name}: requests_per_minute must be between 0.01 and 60000, tokens_per_minute must be positive"));
            }
        }
        if !per_min.is_finite() || per_min < 0.0 || (per_min > 0.0 && per_min < 0.01) || per_min > 60000.0 {
            return Err(anyhow!("LIVING_LLM_PER_MIN must be 0 or between 0.01 and 60000"));
        }
        let concurrency = std::env::var("LIVING_CONCURRENCY").ok().and_then(|v| v.parse().ok()).unwrap_or(64).max(1);
        let scheduler = Scheduler::new(&models, concurrency, per_min);
        Ok(Self { http, models, keys, journal, scheduler })
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

    /// A person's profile: their group's (unless assigned one by name), over the child
    /// stage's and rotation; without a group, as before: a child's stage profile, else the
    /// assignment, rotation or default. Profiles without a key are passed over.
    pub fn person_profile(&self, id: u32, name: &str, group: Option<&str>, child: bool) -> String {
        let keyed = |p: Option<&String>| p.filter(|p| self.keys.contains_key(*p)).cloned();
        if let Some(g) = keyed(group.and_then(|g| self.models.groups.get(g))) {
            return keyed(self.models.assign.get(name)).unwrap_or(g);
        }
        child.then(|| self.stage_profile("child")).flatten().unwrap_or_else(|| self.profile_for(id, name))
    }

    /// Whether any group has a profile (otherwise groups need not be looked up).
    pub fn has_groups(&self) -> bool {
        !self.models.groups.is_empty()
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

    pub async fn chat(&self, profile: &str, purpose: &str, actor: &str, messages: &[Msg]) -> Result<Reply> {
        self.chat_in_lane(profile, purpose, actor, messages, Lane::for_purpose(purpose)).await
    }

    pub async fn chat_in_lane(&self, profile: &str, purpose: &str, actor: &str, messages: &[Msg], lane: Lane) -> Result<Reply> {
        let mut result = self.chat_once(profile, purpose, actor, messages, lane).await;
        let limited = matches!(&result, Err(e) if format!("{e:#}").contains("HTTP 429"));
        let alternate = self
            .models
            .profiles
            .get(profile)
            .and_then(|p| p.overflow.as_ref())
            .filter(|p| p.as_str() != profile && self.keys.contains_key(*p))
            .cloned()
            .or_else(|| (profile != self.models.default).then(|| self.models.default.clone()));
        if result.is_err() {
            if let Some(alternate) = alternate {
                result = self.chat_once(&alternate, purpose, actor, messages, lane).await;
            } else if limited {
                // One recovery attempt goes through the learned pacing and cooldown.
                result = self.chat_once(profile, purpose, actor, messages, lane).await;
            }
        }
        result
    }

    async fn chat_once(&self, profile: &str, purpose: &str, actor: &str, messages: &[Msg], lane: Lane) -> Result<Reply> {
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
        if p.prompt_cache_key {
            body["prompt_cache_key"] = json!(format!("sao:{}:{profile}:{purpose}", profile.len()));
        }
        let cost = messages.iter().map(|m| (m.content.len() as u64).div_ceil(3) + 8).sum::<u64>() + u64::from(p.max_tokens.unwrap_or(8000));
        let host = p.base_url.clone();
        let queued = Instant::now();
        let permit = self.scheduler.admit(profile, lane, cost).await?;
        let queue_wait_ms = queued.elapsed().as_millis() as u64;
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
            let headers = resp.headers().clone();
            self.scheduler.feedback(profile, permit.id, status.as_u16() == 429, &headers, None);
            let text = resp.text().await.context("body")?;
            if !status.is_success() {
                return Err(anyhow!("HTTP {status}: {}", text.chars().take(400).collect::<String>()));
            }
            let v: Value = serde_json::from_str(&text).context("response json")?;
            let content = content_text(&v["choices"][0]["message"]["content"]);
            let tokens = v["usage"]["total_tokens"].as_u64().unwrap_or(0) as u32;
            self.scheduler.feedback(profile, permit.id, false, &reqwest::header::HeaderMap::new(), v["usage"]["total_tokens"].as_u64());
            Ok((content, tokens, v["usage"].clone()))
        }
        .await;
        self.gate_leave(&host, unreachable);
        drop(permit);
        let latency_ms = started.elapsed().as_millis() as u32;
        let entry = json!({
            "at_ms": now_ms(),
            "actor": actor,
            "purpose": purpose,
            "profile": profile,
            "model": p.model,
            "latency_ms": latency_ms,
            "lane": lane,
            "queue_wait_ms": queue_wait_ms,
            "prompt_tokens": result.as_ref().ok().and_then(|(_, _, u)| u["prompt_tokens"].as_u64()),
            "completion_tokens": result.as_ref().ok().and_then(|(_, _, u)| u["completion_tokens"].as_u64()),
            "cached_tokens": result.as_ref().ok().and_then(|(_, _, u)| u["prompt_tokens_details"]["cached_tokens"].as_u64()),
            "request": body,
            "reply": result.as_ref().map(|(c, _, _)| c.clone()).ok(),
            "tokens": result.as_ref().map(|(_, t, _)| *t).ok(),
            "error": result.as_ref().err().map(|e| format!("{e:#}")),
        });
        self.journal(actor, &entry).await;
        let (content, tokens, _) = result?;
        Ok(Reply { content, tokens, latency_ms, model: p.model.clone() })
    }

    fn gate_leave(&self, host: &str, unreachable: bool) {
        let mut queue = self.scheduler.queue.lock().unwrap();
        let waiting = queue.waiting.iter().filter(|w| queue.hosts[&w.profile] == host).count() as u64;
        let g = queue.gates.entry(host.to_string()).or_default();
        g.probing = None;
        if unreachable {
            g.pause = if g.down_since.is_none() { GATE_PAUSE_MIN } else { (g.pause * 2).min(GATE_PAUSE_MAX) };
            if g.down_since.is_none() {
                g.down_since = Some(Instant::now());
                g.held += waiting;
                log::warn!("{host} unreachable: holding model calls, probing every {:?} up to {:?}", GATE_PAUSE_MIN, GATE_PAUSE_MAX);
            }
            g.retry_at = Some(Instant::now() + g.pause);
        } else if let Some(since) = g.down_since.take() {
            log::warn!("{host} reachable again after {:.0} s; {} calls were held meanwhile", since.elapsed().as_secs_f64(), g.held);
            *g = Gate::default();
        }
        self.scheduler.changed.notify_waiters();
    }

    async fn journal(&self, actor: &str, entry: &Value) {
        let path = self.journal.join(format!("{}.jsonl", actor.replace(|c: char| !c.is_alphanumeric(), "_")));
        if let Ok(mut f) = tokio::fs::OpenOptions::new().create(true).append(true).open(&path).await {
            let mut line = entry.to_string();
            line.push('\n');
            let _ = f.write_all(line.as_bytes()).await;
            let _ = f.flush().await;
        }
    }
}

/// Message content as text: a plain string, or the text parts of a content array
/// (some providers return `[{"type":"thinking",...},{"type":"text","text":...}]`).
fn content_text(c: &Value) -> String {
    match c {
        Value::String(s) => s.clone(),
        Value::Array(parts) => parts.iter().filter(|p| p["type"].as_str() == Some("text")).filter_map(|p| p["text"].as_str()).collect::<Vec<_>>().join(""),
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

    fn test_profile() -> Profile {
        serde_json::from_value(json!({"base_url": "http://127.0.0.1:9/v1", "model": "m", "key_env": "unused", "requests_per_minute": 60})).unwrap()
    }

    #[test]
    fn pacing_uses_an_explicit_clock_and_a_rolling_token_window() {
        let now = Instant::now();
        let mut p = test_profile();
        p.tokens_per_minute = Some(100);
        let mut rate = Rate::new(&p, now);
        assert_eq!(rate.ready_at(80, now), now);
        rate.sent(1, 80, now);
        assert_eq!(rate.ready_at(10, now), now + Duration::from_secs(1));
        assert_eq!(rate.ready_at(30, now + Duration::from_secs(1)), now + Duration::from_secs(60));
        rate.feedback(1, false, &Default::default(), Some(10), now + Duration::from_secs(1));
        assert!(rate.ready_at(90, now + Duration::from_secs(2)) <= now + Duration::from_secs(2));
        assert!(rate.ready_at(100, now + Duration::from_secs(60)) <= now + Duration::from_secs(60));
    }

    #[test]
    fn a_429_reduces_rate_and_obeys_provider_headers() {
        let now = Instant::now();
        let mut rate = Rate::new(&test_profile(), now);
        rate.sent(1, 20, now);
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("retry-after", "120".parse().unwrap());
        headers.insert("x-ratelimit-limit-req-minute", "40".parse().unwrap());
        headers.insert("x-ratelimit-limit-tokens-minute", "1000".parse().unwrap());
        rate.feedback(1, true, &headers, None, now);
        assert_eq!(rate.ceiling, 36.0);
        assert_eq!(rate.rpm, 18.0);
        assert_eq!(rate.tpm, Some(900));
        assert_eq!(rate.ready_at(20, now), now + Duration::from_secs(120));
        rate.feedback(1, false, &Default::default(), Some(10), now + Duration::from_secs(120));
        assert_eq!(rate.rpm, 19.0);
        headers.clear();
        headers.insert("x-ratelimit-remaining-req-minute", "0".parse().unwrap());
        rate.feedback(1, false, &headers, None, now + Duration::from_secs(120));
        assert!(rate.ready_at(20, now + Duration::from_secs(120)) >= now + Duration::from_secs(180));
    }

    #[test]
    fn interactive_precedes_queued_background_at_saturation() {
        let now = Instant::now();
        let models = ModelsFile {
            default: "p".into(),
            profiles: HashMap::from([("p".into(), test_profile())]),
            assign: Default::default(),
            rotate: vec![],
            species: Default::default(),
            stages: Default::default(),
            groups: Default::default(),
        };
        let scheduler = Scheduler::new(&models, 1, 0.0);
        let mut q = scheduler.queue.lock().unwrap();
        q.waiting.push_back(Waiting { id: 1, profile: "p".into(), lane: Lane::Background, cost: 10 });
        q.start(1, now);
        q.waiting.push_back(Waiting { id: 2, profile: "p".into(), lane: Lane::Background, cost: 10 });
        q.waiting.push_back(Waiting { id: 3, profile: "p".into(), lane: Lane::Interactive, cost: 10 });
        assert_eq!(q.candidate(now + Duration::from_secs(1)), None);
        q.in_flight -= 1;
        q.lower_in_flight -= 1;
        assert_eq!(q.candidate(now + Duration::from_secs(1)), Some(3));
        q.start(3, now + Duration::from_secs(1));
        assert_eq!(q.waiting.front().unwrap().id, 2);
    }

    #[test]
    fn lower_lanes_leave_an_interactive_slot_and_global_pacing_is_shared() {
        let now = Instant::now();
        let models = ModelsFile {
            default: "p".into(),
            profiles: HashMap::from([("p".into(), test_profile())]),
            assign: Default::default(),
            rotate: vec![],
            species: Default::default(),
            stages: Default::default(),
            groups: Default::default(),
        };
        let scheduler = Scheduler::new(&models, 2, 30.0);
        let mut q = scheduler.queue.lock().unwrap();
        q.waiting.push_back(Waiting { id: 1, profile: "p".into(), lane: Lane::Background, cost: 10 });
        q.start(1, now);
        q.waiting.push_back(Waiting { id: 2, profile: "p".into(), lane: Lane::Routine, cost: 10 });
        assert_eq!(q.candidate(now + Duration::from_secs(2)), None);
        q.waiting.push_back(Waiting { id: 3, profile: "p".into(), lane: Lane::Interactive, cost: 10 });
        assert_eq!(q.candidate(now + Duration::from_secs(1)), None);
        assert_eq!(q.candidate(now + Duration::from_secs(2)), Some(3));
    }

    #[test]
    fn retry_after_accepts_seconds_and_http_dates() {
        let now = std::time::UNIX_EPOCH + Duration::from_secs(1445412480);
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("retry-after", "Wed, 21 Oct 2015 07:28:05 GMT".parse().unwrap());
        assert_eq!(retry_after(&headers, now), Some(Duration::from_secs(5)));
        headers.insert("retry-after", "0.25".parse().unwrap());
        assert_eq!(retry_after(&headers, now), Some(Duration::from_millis(250)));
        for value in ["bad", "-1", "inf", "NaN", "Wed, 31 Feb 2015 07:28:00 GMT", "Wed, 21 Oct 2015 99:28:00 GMT"] {
            headers.insert("retry-after", value.parse().unwrap());
            assert_eq!(retry_after(&headers, now), None);
        }
    }

    #[test]
    fn lane_mapping_preserves_player_priority_over_combat() {
        assert_eq!(Lane::deliberation("under attack", true), Lane::Interactive);
        assert_eq!(Lane::deliberation("under attack", false), Lane::Urgent);
        assert_eq!(Lane::deliberation("The fight with Tam: your blow missed.", false), Lane::Urgent);
        assert_eq!(Lane::for_purpose("think"), Lane::Routine);
        assert_eq!(Lane::deliberation("white flowers", false), Lane::Routine);
        for purpose in ["consolidate", "reorganize", "identity"] {
            assert_eq!(Lane::for_purpose(purpose), Lane::Background);
        }
        assert_eq!(Lane::for_purpose("talk"), Lane::Interactive);
    }

    #[tokio::test]
    async fn a_cancelled_waiter_uses_no_network_slot_and_leaves_no_ticket() {
        let models: ModelsFile = serde_json::from_value(json!({"default": "p", "profiles": {"p": {"base_url": "x", "model": "m", "key_env": "unused"}}})).unwrap();
        let scheduler = Scheduler::new(&models, 1, 0.0);
        scheduler.queue.lock().unwrap().rates.get_mut("p").unwrap().next = Instant::now() + Duration::from_secs(60);
        let call = scheduler.admit("p", Lane::Background, 10);
        assert!(tokio::time::timeout(Duration::from_millis(10), call).await.is_err());
        let q = scheduler.queue.lock().unwrap();
        assert_eq!(q.in_flight, 0);
        assert!(q.waiting.is_empty());
    }

    #[tokio::test]
    async fn cancellation_releases_an_outage_probe() {
        let models: ModelsFile = serde_json::from_value(json!({"default": "p", "profiles": {"p": {"base_url": "x", "model": "m", "key_env": "unused"}}})).unwrap();
        let scheduler = Scheduler::new(&models, 1, 0.0);
        scheduler.queue.lock().unwrap().gates.insert("x".into(), Gate { retry_at: Some(Instant::now()), ..Default::default() });
        let admission = scheduler.admit("p", Lane::Interactive, 10).await.unwrap();
        assert!(scheduler.queue.lock().unwrap().gates["x"].probing.is_some());
        drop(admission);
        let queue = scheduler.queue.lock().unwrap();
        assert!(queue.gates["x"].probing.is_none());
        assert_eq!(queue.in_flight, 0);
    }

    #[tokio::test]
    async fn fake_transport_records_caching_usage_and_paced_429_recovery() {
        struct Fake(std::process::Child);
        impl Drop for Fake {
            fn drop(&mut self) {
                let _ = self.0.kill();
                let _ = self.0.wait();
            }
        }
        let directory = std::env::temp_dir().join(format!("living-transport-{}", now_ms()));
        std::fs::create_dir_all(&directory).unwrap();
        let socket = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = socket.local_addr().unwrap().port();
        drop(socket);
        let script = directory.join("script.json");
        std::fs::write(&script, json!({"rules": [{"purpose": "consolidate", "usage": {"total_tokens": 17}}, {"purpose": "think", "status": 429, "headers": {"Retry-After": "0.2", "x-ratelimit-limit-req-minute": "6000", "x-ratelimit-limit-tokens-minute": "100000"}}]}).to_string()).unwrap();
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let log = directory.join("requests.jsonl");
        let mut fake = Fake(
            std::process::Command::new("python3")
                .arg(root.join(".agents/skills/verify-llm/scripts/fake_llm.py"))
                .args(["--port", &port.to_string(), "--log"])
                .arg(&log)
                .arg("--script")
                .arg(script)
                .stdout(std::process::Stdio::null())
                .spawn()
                .unwrap(),
        );
        let http = reqwest::Client::new();
        for _ in 0..100 {
            if http.get(format!("http://127.0.0.1:{port}/health")).send().await.is_ok() {
                break;
            }
            assert!(fake.0.try_wait().unwrap().is_none());
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        std::env::set_var("LIVING_TEST_TRANSPORT_KEY", "dummy-only");
        let models: ModelsFile = serde_json::from_value(json!({"default": "p", "profiles": {"p": {
            "base_url": format!("http://127.0.0.1:{port}/v1"), "model": "m", "key_env": "LIVING_TEST_TRANSPORT_KEY",
            "requests_per_minute": 6000, "max_tokens": 256, "prompt_cache_key": true,
            "reasoning_effort": {"think": "think", "talk": "talk", "consolidate": "consolidate"} }}}))
        .unwrap();
        let llm = Llm::new(models, directory.join("journal")).unwrap();
        let messages = [Msg { role: "user", content: "hi".into() }];
        let reply = llm.chat_in_lane("p", "think", "first", &messages, Lane::Interactive).await.unwrap();
        assert_eq!(reply.tokens, 17);
        llm.chat_in_lane("p", "think", "second", &messages, Lane::Interactive).await.unwrap();
        llm.chat("p", "talk", "second", &messages).await.unwrap();
        let entries: Vec<Value> = std::fs::read_to_string(directory.join("journal/first.jsonl")).unwrap().lines().map(|l| serde_json::from_str(l).unwrap()).collect();
        assert_eq!(entries.len(), 2);
        assert!(entries[0]["error"].as_str().unwrap().contains("HTTP 429"));
        assert!(entries[0]["prompt_tokens"].is_null());
        assert_eq!(entries[1]["lane"], "interactive");
        assert_eq!(entries[1]["prompt_tokens"], 12);
        assert_eq!(entries[1]["completion_tokens"], 5);
        assert_eq!(entries[1]["cached_tokens"], 8);
        assert!(entries[1]["queue_wait_ms"].as_u64().unwrap() >= 180);
        let mut uncached = llm.models.clone();
        uncached.profiles.get_mut("p").unwrap().prompt_cache_key = false;
        let uncached = Llm::new(uncached, directory.join("uncached-journal")).unwrap();
        uncached.chat("p", "consolidate", "uncached", &messages).await.unwrap();
        let unknown: Value = serde_json::from_str(std::fs::read_to_string(directory.join("uncached-journal/uncached.jsonl")).unwrap().trim()).unwrap();
        assert!(unknown["prompt_tokens"].is_null() && unknown["completion_tokens"].is_null() && unknown["cached_tokens"].is_null());
        let requests: Vec<Value> = std::fs::read_to_string(log).unwrap().lines().map(|l| serde_json::from_str(l).unwrap()).collect();
        assert_eq!(requests.len(), 5);
        assert!(requests[4]["body"].get("prompt_cache_key").is_none());
        assert!(requests[1]["at_ms"].as_u64().unwrap() - requests[0]["at_ms"].as_u64().unwrap() >= 180);
        assert_eq!(requests[0]["body"]["prompt_cache_key"], requests[2]["body"]["prompt_cache_key"]);
        assert_ne!(requests[2]["body"]["prompt_cache_key"], requests[3]["body"]["prompt_cache_key"]);
        println!("fake transport evidence: {}", directory.display());
    }

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
    fn groups_come_from_ones_own_background_or_ones_parents() {
        // 1, 2: founders of Eastmere and a band; 3: their child; 4: 3's child with an
        // unknown other parent; 5: a founder with no group; 6 and 7: each other's parents.
        let of = |id: u32| match id {
            1 => Some((Some("Eastmere".to_string()), 0, 0)),
            2 => Some((Some("Hollow band".to_string()), 0, 0)),
            3 => Some((None, 1, 2)),
            4 => Some((None, 99, 3)),
            5 => Some((None, 0, 0)),
            6 => Some((None, 7, 0)),
            7 => Some((None, 6, 0)),
            _ => None,
        };
        assert_eq!(group_of(1, &of, GROUP_DEPTH).as_deref(), Some("Eastmere"));
        assert_eq!(group_of(3, &of, GROUP_DEPTH).as_deref(), Some("Eastmere"), "parent_a first");
        assert_eq!(group_of(4, &of, GROUP_DEPTH).as_deref(), Some("Eastmere"), "through a grandparent");
        assert_eq!(group_of(4, &of, 1), None, "bounded depth");
        assert_eq!(group_of(5, &of, GROUP_DEPTH), None);
        assert_eq!(group_of(6, &of, GROUP_DEPTH), None, "a cycle ends");
    }

    #[test]
    fn a_group_profile_overrides_stage_and_rotation_but_not_assignment() {
        std::env::set_var("LIVING_TEST_GROUP_KEY", "x");
        let p = |m: &str| json!({"base_url": "http://127.0.0.1:9/v1", "model": m, "key_env": "LIVING_TEST_GROUP_KEY"});
        let models: ModelsFile = serde_json::from_value(json!({
            "default": "a",
            "profiles": {"a": p("a"), "b": p("b"), "c": p("c"), "kid": p("kid"), "nokey": {"base_url": "x", "model": "n", "key_env": "LIVING_TEST_UNSET_KEY"}},
            "assign": {"Mara": "c"},
            "rotate": ["a", "c"],
            "stages": {"child": "kid"},
            "groups": {"Eastmere": "b", "Stonewatch": "nokey"}
        }))
        .unwrap();
        let dir = std::env::temp_dir().join(format!("living-groups-{}", now_ms()));
        let llm = Llm::new(models, dir.clone()).unwrap();
        assert_eq!(llm.person_profile(1, "Tam", Some("Eastmere"), false), "b");
        assert_eq!(llm.person_profile(1, "Tam", Some("Eastmere"), true), "b", "over the child stage");
        assert_eq!(llm.person_profile(1, "Mara", Some("Eastmere"), false), "c", "an assignment by name wins");
        assert_eq!(llm.person_profile(1, "Tam", Some("Stonewatch"), false), "c", "a profile without a key falls through to rotation");
        assert_eq!(llm.person_profile(2, "Tam", None, true), "kid");
        assert_eq!(llm.person_profile(2, "Mara", None, true), "kid", "without a group, the child stage still comes first");
        assert_eq!(llm.person_profile(2, "Mara", None, false), "c");
        assert_eq!(llm.person_profile(2, "Tam", None, false), "a");
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn repairs_small_model_slips() {
        let v = parse_json("{\n  \"remember\": [],\n  \"nodes\": [\n    },\n    {\"key\": \"self\"}\n  ],\n  \"edges\": [1, 2,],\n}").unwrap();
        assert_eq!(v["nodes"][0]["key"], "self");
        assert_eq!(v["edges"].as_array().unwrap().len(), 2);
    }
}
