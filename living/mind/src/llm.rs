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
    /// The effort sent per purpose. `null` says the profile deliberately sends none for that
    /// purpose (DeepSeek's thinking off); a purpose the profile is used for and that has no
    /// entry is warned about at start (see [`ModelsFile::effort_gaps`]).
    #[serde(default)]
    pub reasoning_effort: HashMap<String, Option<String>>,
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
    #[serde(default)]
    pub requests_per_minute: Option<f64>,
    #[serde(default)]
    pub tokens_per_minute: Option<u64>,
    #[serde(default)]
    pub prompt_cache_key: bool,
    /// Output caps for particular purposes, over `max_tokens` (for example a 24,000-token
    /// `reorganize` on a profile whose other replies stay under 8,000).
    #[serde(default)]
    pub purpose_max_tokens: HashMap<String, u32>,
}

fn yes() -> bool {
    true
}

fn max_tokens() -> Option<u32> {
    Some(8000)
}

/// The purpose whose settings a newer purpose inherits when a profile does not name it, so a
/// profile written before `reorganize` existed does not send reorganization at the model's
/// default effort (on GLM Flash that is `max`: see docs/MODEL_COST.md).
fn parent_purpose(purpose: &str) -> Option<&'static str> {
    match purpose {
        "reorganize" => Some("consolidate"),
        _ => None,
    }
}

impl Profile {
    /// The reasoning effort sent for a purpose: the profile's own entry, else its parent's.
    pub fn effort(&self, purpose: &str) -> Option<&String> {
        self.effort_entry(purpose).and_then(|e| e.as_ref())
    }

    /// The profile's entry for a purpose (or its parent's): `Some(None)` is an explicit
    /// "send no effort", `None` no entry at all.
    fn effort_entry(&self, purpose: &str) -> Option<&Option<String>> {
        self.reasoning_effort.get(purpose).or_else(|| parent_purpose(purpose).and_then(|p| self.reasoning_effort.get(p)))
    }

    pub fn max_tokens_for(&self, purpose: &str) -> Option<u32> {
        self.purpose_max_tokens.get(purpose).or_else(|| parent_purpose(purpose).and_then(|p| self.purpose_max_tokens.get(p))).copied().or(self.max_tokens)
    }
}

/// Whether a person's mind is being watched: a human player is in their scene or was recently
/// part of what they lived (see mind/lod.rs). Mixes may choose a model by it.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Attention {
    OnStage,
    OffStage,
}

/// One purpose's model in a mix: a profile name, optionally with an effort that replaces the
/// profile's own for this purpose (`"deepseek-flash@low"`), or one per stage of attention.
#[derive(Clone, Debug, Deserialize)]
#[serde(untagged)]
pub enum Choice {
    One(String),
    Staged { on_stage: String, off_stage: String },
}

impl Choice {
    fn pick(&self, at: Attention) -> &str {
        match (self, at) {
            (Self::One(s), _) => s,
            (Self::Staged { on_stage, .. }, Attention::OnStage) => on_stage,
            (Self::Staged { off_stage, .. }, Attention::OffStage) => off_stage,
        }
    }

    fn specs(&self) -> Vec<&str> {
        match self {
            Self::One(s) => vec![s],
            Self::Staged { on_stage, off_stage } => vec![on_stage, off_stage],
        }
    }
}

/// `profile@effort` → (`profile`, `Some(effort)`); a plain name has no override.
pub fn split_spec(spec: &str) -> (&str, Option<&str>) {
    match spec.split_once('@') {
        Some((p, e)) if !e.is_empty() => (p, Some(e)),
        Some((p, _)) => (p, None),
        None => (spec, None),
    }
}

/// The purposes the mind sends (see `Lane::for_purpose`); `*` in a mix covers the rest.
pub const PURPOSES: [&str; 7] = ["think", "deliberate", "talk", "consolidate", "reorganize", "internalize", "judge"];

/// The model purposes a person's route is used for (identity and birth go out as
/// `consolidate`).
pub const PERSON_PURPOSES: [&str; 6] = ["think", "deliberate", "talk", "consolidate", "internalize", "reorganize"];

/// What a call resolved to: the profile it goes to, the effort it sends, and the mix it came
/// from (for the journal).
#[derive(Clone, Debug, PartialEq)]
pub struct Pick {
    pub profile: String,
    pub effort: Option<String>,
    pub mix: Option<String>,
    pub attention: Option<Attention>,
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
    /// Named per-purpose model mixes (`{"talk": "deepseek-flash", "deliberate":
    /// {"on_stage": "deepseek-flash@low", "off_stage": "glm-flash"}, "*": "glm-flash"}`). A mix
    /// name is accepted wherever a profile name is: `default`, `assign`, `rotate`, `stages`,
    /// `groups` and `species`.
    #[serde(default)]
    pub mixes: HashMap<String, HashMap<String, Choice>>,
    /// The route (a profile or a mix) of residents woken into minds on a world whose
    /// residents otherwise live on instinct (docs/TOWN_LIFE.md, "Layer 2"): over their group,
    /// stage, rotation and the default; an assignment by name still wins.
    #[serde(default)]
    pub woken: Option<String>,
}

impl ModelsFile {
    /// Every name the file routes to must be a profile (`profile@effort` included) or a mix,
    /// and a mix must name profiles, not other mixes.
    pub fn check(&self) -> Result<()> {
        let profile_spec = |spec: &str| {
            let (p, e) = split_spec(spec);
            self.profiles.contains_key(p) && e.is_none_or(|e| !e.trim().is_empty())
        };
        for (name, mix) in &self.mixes {
            if self.profiles.contains_key(name) {
                return Err(anyhow!("mix {name} has the name of a profile"));
            }
            if mix.is_empty() {
                return Err(anyhow!("mix {name} is empty"));
            }
            if *name == self.default && !mix.contains_key("*") && !PURPOSES.iter().all(|p| mix.contains_key(*p) || parent_purpose(p).is_some_and(|q| mix.contains_key(q))) {
                return Err(anyhow!("the default mix {name} must cover every purpose (give it a \"*\")"));
            }
            for (purpose, choice) in mix {
                if purpose != "*" && !PURPOSES.contains(&purpose.as_str()) {
                    return Err(anyhow!("mix {name}: unknown purpose {purpose} (one of {}, or *)", PURPOSES.join(", ")));
                }
                for spec in choice.specs() {
                    if !profile_spec(spec) {
                        return Err(anyhow!("mix {name}: {purpose} names {spec}, which is not a profile (mixes name profiles, optionally profile@effort)"));
                    }
                }
            }
        }
        let route = |what: &str, spec: &str| -> Result<()> {
            if profile_spec(spec) || self.mixes.contains_key(spec) {
                Ok(())
            } else {
                Err(anyhow!("{what} names {spec}, which is neither a profile nor a mix"))
            }
        };
        route("default", &self.default)?;
        if let Some(w) = &self.woken {
            route("woken", w)?;
        }
        for (k, v) in self.assign.iter().chain(&self.stages).chain(&self.groups) {
            route(k, v)?;
        }
        for v in &self.rotate {
            route("rotate", v)?;
        }
        for (kind, roles) in &self.species {
            for (role, v) in roles {
                route(&format!("species {kind} {role}"), v)?;
            }
        }
        Ok(())
    }

    /// Every (profile, purpose) this file can send without saying what effort to use: a
    /// route reaches the profile for the purpose, no `@effort` is written there, and the
    /// profile's map has no entry for it (`null` is an entry). GLM Flash without an entry
    /// thinks as at `max` and runs out of tokens (MODEL_COST Part 1: 69% of compiles came back
    /// empty that way). An overflow profile is reached for the routine and interactive
    /// purposes (background ones do not overflow).
    pub fn effort_gaps(&self) -> Vec<String> {
        let mut out = std::collections::BTreeSet::new();
        self.gaps_for("default", &self.default, &PERSON_PURPOSES, &mut out);
        if let Some(w) = &self.woken {
            self.gaps_for("woken", w, &PERSON_PURPOSES, &mut out);
        }
        for (k, v) in self.assign.iter().chain(&self.stages).chain(&self.groups) {
            self.gaps_for(k, v, &PERSON_PURPOSES, &mut out);
        }
        for v in &self.rotate {
            self.gaps_for("rotate", v, &PERSON_PURPOSES, &mut out);
        }
        for (kind, roles) in &self.species {
            for v in roles.values() {
                self.gaps_for(&format!("species {kind}"), v, &["deliberate", "consolidate"], &mut out);
            }
        }
        out.into_iter().collect()
    }

    /// The gaps of one route for the given purposes (see [`Self::effort_gaps`]).
    pub fn gaps_for(&self, what: &str, route: &str, purposes: &[&str], out: &mut std::collections::BTreeSet<String>) {
        for purpose in purposes {
            let specs: Vec<&str> = match self.mixes.get(route) {
                // A purpose the mix leaves out goes to the default, which is checked on its own.
                Some(mix) => mix.get(*purpose).or_else(|| parent_purpose(purpose).and_then(|p| mix.get(p))).or_else(|| mix.get("*")).map(|c| c.specs()).unwrap_or_default(),
                None => vec![route],
            };
            for spec in specs {
                let (name, written) = split_spec(spec);
                let Some(p) = self.profiles.get(name) else { continue };
                if written.is_none() && p.effort_entry(purpose).is_none() {
                    out.insert(format!("profile {name} has no reasoning_effort for {purpose} (reached by {what} → {route})"));
                }
                let overflows = Lane::for_purpose(purpose) != Lane::Background;
                if let Some(o) = p.overflow.as_deref().filter(|o| overflows && *o != name).and_then(|o| self.profiles.get(o).map(|q| (o, q))) {
                    if o.1.effort_entry(purpose).is_none() {
                        out.insert(format!("profile {} has no reasoning_effort for {purpose} (the overflow of {name}, reached by {what} → {route})", o.0));
                    }
                }
            }
        }
    }

    /// Whether any mix chooses by stage of attention (then attention is tracked even with the
    /// level of detail off).
    pub fn staged(&self) -> bool {
        self.mixes.values().flat_map(|m| m.values()).any(|c| matches!(c, Choice::Staged { .. }))
    }
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

/// Reachability of a provider (by base URL). When a request cannot connect to it (DNS, no
/// route, refused), calls to it wait instead of failing at once; one probe at a time goes
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

const NON_INTERACTIVE_ADMISSIONS: [Lane; 10] = [Lane::Urgent, Lane::Urgent, Lane::Urgent, Lane::Urgent, Lane::Urgent, Lane::Urgent, Lane::Routine, Lane::Routine, Lane::Routine, Lane::Background];

impl Lane {
    pub fn for_purpose(purpose: &str) -> Self {
        match purpose {
            "talk" => Self::Interactive,
            "combat" | "alarm" | "attack" => Self::Urgent,
            "consolidate" | "reorganize" | "identity" | "internalize" => Self::Background,
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

const RATE_START_RPM: f64 = 600.0;
const RATE_DECREASE: f64 = 0.5;
const RATE_FLOOR_FRACTION: f64 = 0.05;
const RATE_RECOVERY_FRACTION: f64 = 0.05;
const RATE_RECOVERY_INTERVAL: Duration = Duration::from_secs(10);
const RATE_HEADER_HEADROOM: f64 = 0.9;
const RATE_LOG_INTERVAL: Duration = Duration::from_secs(30);

#[derive(Clone, Copy, Debug, PartialEq)]
struct RateLimits {
    ceiling: f64,
    rpm: f64,
    tpm: Option<u64>,
}

struct Rate {
    configured_ceiling: Option<f64>,
    ceiling: f64,
    rpm: f64,
    tpm: Option<u64>,
    next: Instant,
    last_sent: Instant,
    blocked_until: Instant,
    last_increase: Instant,
    last_decrease: Option<Instant>,
    logged_limits: RateLimits,
    last_limit_log: Option<Instant>,
    tokens: VecDeque<(u64, Instant, u64)>,
}

impl Rate {
    fn new(p: &Profile, now: Instant) -> Self {
        let ceiling = p.requests_per_minute.unwrap_or(RATE_START_RPM);
        Self {
            configured_ceiling: p.requests_per_minute,
            ceiling,
            rpm: ceiling,
            tpm: p.tokens_per_minute,
            next: now,
            last_sent: now,
            blocked_until: now,
            last_increase: now,
            last_decrease: None,
            logged_limits: RateLimits { ceiling, rpm: ceiling, tpm: p.tokens_per_minute },
            last_limit_log: None,
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
            let advertised = limit * RATE_HEADER_HEADROOM;
            self.ceiling = self.configured_ceiling.map_or(advertised, |cap| cap.min(advertised));
            self.rpm = self.rpm.min(self.ceiling);
        }
        if let Some(limit) = number("x-ratelimit-limit-tokens-minute").filter(|n| *n >= 1.0) {
            let limit = (limit * RATE_HEADER_HEADROOM).max(1.0) as u64;
            self.tpm = Some(self.tpm.map_or(limit, |old| old.min(limit)));
        }
        if let Some(actual) = usage {
            if let Some((_, _, cost)) = self.tokens.iter_mut().find(|(ticket, _, _)| *ticket == id) {
                *cost = actual;
            }
        }
        if limited {
            // Responses from the same in-flight burst describe one congestion event.
            let sent = self.tokens.iter().find(|(ticket, _, _)| *ticket == id).map(|(_, at, _)| *at);
            if self.last_decrease.is_none_or(|last| sent.is_some_and(|at| at > last)) {
                let floor = (self.ceiling * RATE_FLOOR_FRACTION).max(1.0).min(self.ceiling);
                self.rpm = (self.rpm * RATE_DECREASE).max(floor);
                self.last_decrease = Some(now);
            }
            self.last_increase = now;
            let wait = retry_after(headers, std::time::SystemTime::now()).unwrap_or(Duration::from_secs_f64(60.0 / self.rpm));
            self.blocked_until = self.blocked_until.max(now.checked_add(wait).unwrap_or(now + Duration::from_secs(60)));
            self.next = self.next.max(now + Duration::from_secs_f64(60.0 / self.rpm));
        } else if usage.is_some() && now.duration_since(self.last_increase) >= RATE_RECOVERY_INTERVAL {
            self.rpm = (self.rpm + (self.ceiling * RATE_RECOVERY_FRACTION).max(1.0)).min(self.ceiling);
            self.last_increase = now;
        }
        if number("x-ratelimit-remaining-req-minute") == Some(0.0) || number("x-ratelimit-remaining-tokens-minute") == Some(0.0) {
            self.blocked_until = self.blocked_until.max(now + Duration::from_secs(60));
        }
        self.next = self.next.max(self.last_sent + Duration::from_secs_f64(60.0 / self.rpm));
    }

    fn take_limit_update(&mut self, now: Instant) -> Option<RateLimits> {
        let limits = RateLimits { ceiling: self.ceiling, rpm: self.rpm, tpm: self.tpm };
        if limits == self.logged_limits || self.last_limit_log.is_some_and(|last| now.duration_since(last) < RATE_LOG_INTERVAL) {
            return None;
        }
        self.logged_limits = limits;
        self.last_limit_log = Some(now);
        Some(limits)
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
    next_lane: usize,
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
        let lane = if self.waiting.iter().any(|w| w.lane == Lane::Interactive) {
            Lane::Interactive
        } else {
            (0..NON_INTERACTIVE_ADMISSIONS.len())
                .map(|offset| NON_INTERACTIVE_ADMISSIONS[(self.next_lane + offset) % NON_INTERACTIVE_ADMISSIONS.len()])
                .find(|lane| self.waiting.iter().any(|w| w.lane == *lane))?
        };
        let lower_limit = self.concurrency.saturating_sub((self.concurrency / 4).max(1)).max(1);
        if lane != Lane::Interactive && self.lower_in_flight >= lower_limit {
            return None;
        }
        // Keep a paced lane's turn so cheaper requests cannot consume its token budget forever.
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
        if w.lane != Lane::Interactive {
            let offset = (0..NON_INTERACTIVE_ADMISSIONS.len()).find(|offset| NON_INTERACTIVE_ADMISSIONS[(self.next_lane + offset) % NON_INTERACTIVE_ADMISSIONS.len()] == w.lane).unwrap();
            self.next_lane = (self.next_lane + offset + 1) % NON_INTERACTIVE_ADMISSIONS.len();
        }
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
                next_lane: 0,
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
        let now = Instant::now();
        let mut q = self.queue.lock().unwrap();
        let rate = q.rates.get_mut(profile).unwrap();
        rate.feedback(id, limited, headers, usage, now);
        if let Some(limits) = rate.take_limit_update(now) {
            log::info!(
                "model limits profile={profile} rpm_ceiling={:.2} rpm={:.2} tpm_ceiling={}",
                limits.ceiling, limits.rpm, limits.tpm.map_or_else(|| "none".into(), |limit| limit.to_string())
            );
        }
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
        models.check()?;
        for gap in models.effort_gaps() {
            log::warn!("MODEL CONFIG: {gap}; it goes out at the model's default effort (give it an entry, null for none)");
        }
        for (name, mix) in &models.mixes {
            let missing: Vec<&str> = mix.values().flat_map(|c| c.specs()).map(|s| split_spec(s).0).filter(|p| !keys.contains_key(*p)).collect();
            if !missing.is_empty() {
                log::warn!("model mix `{name}` disabled: profiles without a key: {}", missing.join(", "));
            }
        }
        let usable = |name: &str| match models.mixes.get(name) {
            Some(mix) => mix.values().flat_map(|c| c.specs()).all(|s| keys.contains_key(split_spec(s).0)),
            None => keys.contains_key(split_spec(name).0),
        };
        if !usable(&models.default) {
            return Err(anyhow!("default model profile `{}` has no API key", models.default));
        }
        std::fs::create_dir_all(&journal)?;
        let http = reqwest::Client::builder().timeout(Duration::from_secs(180)).user_agent("sao-living-mind/0.1").build()?;
        let per_min: f64 = std::env::var("LIVING_LLM_PER_MIN").ok().and_then(|v| v.parse().ok()).unwrap_or(0.0);
        for (name, p) in &models.profiles {
            if p.requests_per_minute.is_some_and(|rpm| !rpm.is_finite() || !(0.01..=60000.0).contains(&rpm)) || p.tokens_per_minute == Some(0) {
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

    /// Whether a route (a profile, `profile@effort` or a mix) can be called: every profile it
    /// names has a key.
    pub fn usable(&self, name: &str) -> bool {
        match self.models.mixes.get(name) {
            Some(mix) => mix.values().flat_map(|c| c.specs()).all(|s| self.keys.contains_key(split_spec(s).0)),
            None => self.keys.contains_key(split_spec(name).0),
        }
    }

    /// Whether any mix chooses its model by stage of attention.
    pub fn staged(&self) -> bool {
        self.models.staged()
    }

    /// Warn about a route chosen outside the models file (the player memory's model) that
    /// would send a purpose with no effort entry (see [`ModelsFile::effort_gaps`]).
    pub fn warn_effort_gaps(&self, what: &str, route: &str, purposes: &[&str]) {
        let mut gaps = std::collections::BTreeSet::new();
        self.models.gaps_for(what, route, purposes, &mut gaps);
        for gap in gaps {
            log::warn!("MODEL CONFIG: {gap}; it goes out at the model's default effort (give it an entry, null for none)");
        }
    }

    /// Where a call for `purpose` goes from a route (a profile, `profile@effort` or a mix)
    /// at a stage of attention. A mix without an entry for the purpose (nor its parent, nor
    /// `*`) sends it to the default; a choice whose profile has no key also falls to the
    /// default.
    pub fn pick(&self, route: &str, purpose: &str, at: Attention) -> Pick {
        self.pick_in(route, purpose, at).unwrap_or_else(|| {
            // The default is keyed (checked at start) and a default mix covers every purpose.
            self.pick_in(&self.models.default, purpose, at).expect("the default route covers every purpose")
        })
    }

    fn pick_in(&self, route: &str, purpose: &str, at: Attention) -> Option<Pick> {
        let (spec, mix, attention) = match self.models.mixes.get(route) {
            Some(mix) => {
                let choice = mix.get(purpose).or_else(|| parent_purpose(purpose).and_then(|p| mix.get(p))).or_else(|| mix.get("*"))?;
                (choice.pick(at), Some(route.to_string()), matches!(choice, Choice::Staged { .. }).then_some(at))
            }
            None => (route, None, None),
        };
        let (p, e) = split_spec(spec);
        let profile = self.models.profiles.get(p).filter(|_| self.keys.contains_key(p))?;
        Some(Pick { profile: p.into(), effort: e.map(String::from).or_else(|| profile.effort(purpose).cloned()), mix, attention })
    }

    /// The profile for a life stage, if the configuration names one.
    pub fn stage_profile(&self, stage: &str) -> Option<String> {
        self.models.stages.get(stage).filter(|p| self.usable(p)).cloned()
    }

    /// A person's profile: their group's (unless assigned one by name), over the child
    /// stage's and rotation; without a group, as before: a child's stage profile, else the
    /// assignment, rotation or default. Profiles without a key are passed over.
    pub fn person_profile(&self, id: u32, name: &str, group: Option<&str>, child: bool) -> String {
        let keyed = |p: Option<&String>| p.filter(|p| self.usable(p)).cloned();
        if let Some(g) = keyed(group.and_then(|g| self.models.groups.get(g))) {
            return keyed(self.models.assign.get(name)).unwrap_or(g);
        }
        child.then(|| self.stage_profile("child")).flatten().unwrap_or_else(|| self.profile_for(id, name))
    }

    /// The route of a woken resident (`woken` in the models file), unless assigned one by name
    /// or the route has no key.
    pub fn woken_route(&self, name: &str) -> Option<String> {
        let keyed = |p: Option<&String>| p.filter(|p| self.usable(p)).cloned();
        keyed(self.models.woken.as_ref()).map(|w| keyed(self.models.assign.get(name)).unwrap_or(w))
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
        if self.usable(&pick) {
            pick
        } else {
            self.models.default.clone()
        }
    }

    /// Profile for a species role (`think`, `remember`, `compile`), when configured.
    pub fn species_profile(&self, kind: &str, role: &str) -> Option<String> {
        self.models.species.get(kind).and_then(|m| m.get(role)).filter(|p| self.usable(p)).cloned()
    }

    /// The model a route calls, for logs (`mix name` for a mix).
    pub fn model_name(&self, route: &str) -> String {
        if self.models.mixes.contains_key(route) {
            return format!("mix {route}");
        }
        self.models.profiles.get(split_spec(route).0).map(|p| p.model.clone()).unwrap_or_default()
    }

    /// A call for a purpose on a route (a profile, `profile@effort` or a mix, resolved at the
    /// given stage of attention).
    pub async fn chat(&self, route: &str, at: Attention, purpose: &str, actor: &str, messages: &[Msg]) -> Result<Reply> {
        self.chat_in_lane(route, at, purpose, actor, messages, Lane::for_purpose(purpose)).await
    }

    pub async fn chat_in_lane(&self, route: &str, at: Attention, purpose: &str, actor: &str, messages: &[Msg], lane: Lane) -> Result<Reply> {
        let pick = self.pick(route, purpose, at);
        let mut result = self.chat_once(&pick, purpose, actor, messages, lane).await;
        let limited = matches!(&result, Err(e) if format!("{e:#}").contains("HTTP 429"));
        if lane == Lane::Background {
            // Memory work is not waited on: it fails here and its caller tries again later with
            // a backoff (consolidation's `retry_after`, a sleep's, an integration's next turn)
            // on the model it chose. An overflow model would answer with its own settings for
            // the purpose: DeepSeek with thinking off reorganized acceptably 4 times in 21.
            if result.is_err() && limited {
                result = self.chat_once(&pick, purpose, actor, messages, lane).await;
            }
            return result;
        }
        let default = self.pick(&self.models.default, purpose, at);
        // The overflow profile is called with its own effort for the purpose.
        let alternate = self
            .models
            .profiles
            .get(&pick.profile)
            .and_then(|p| p.overflow.as_ref())
            .filter(|p| **p != pick.profile && self.keys.contains_key(*p))
            .map(|p| Pick { profile: p.clone(), effort: self.models.profiles[p].effort(purpose).cloned(), mix: pick.mix.clone(), attention: pick.attention })
            .or_else(|| (default.profile != pick.profile).then_some(default));
        if result.is_err() {
            if let Some(alternate) = alternate {
                result = self.chat_once(&alternate, purpose, actor, messages, lane).await;
            } else if limited {
                // One recovery attempt goes through the learned pacing and cooldown.
                result = self.chat_once(&pick, purpose, actor, messages, lane).await;
            }
        }
        result
    }

    async fn chat_once(&self, pick: &Pick, purpose: &str, actor: &str, messages: &[Msg], lane: Lane) -> Result<Reply> {
        let profile = pick.profile.as_str();
        let p = self.models.profiles.get(profile).ok_or_else(|| anyhow!("no profile {profile}"))?;
        let key = self.keys.get(profile).ok_or_else(|| anyhow!("profile {profile} has no key"))?;
        let body = request_body(p, profile, purpose, pick.effort.as_deref(), messages);
        let cost = messages.iter().map(|m| (m.content.len() as u64).div_ceil(3) + 8).sum::<u64>() + u64::from(p.max_tokens_for(purpose).unwrap_or(8000));
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
                    // Only a connection that could not be made gates the host. A timeout is one
                    // slow reply (a runaway generation, a loaded model): the host answers other
                    // calls, often for other profiles on the same base URL.
                    unreachable = e.is_connect();
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
            "effort": pick.effort,
            "mix": pick.mix,
            "attention": pick.attention,
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

    /// Journal an exchange made outside this client (a judgment provider) beside the actor's
    /// model exchanges.
    pub async fn journal_entry(&self, actor: &str, entry: &Value) {
        self.journal(actor, entry).await
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

/// The chat-completions body for a profile (the same for a direct call and a batch line).
fn request_body(p: &Profile, profile: &str, purpose: &str, effort: Option<&str>, messages: &[Msg]) -> Value {
    let mut body = json!({
        "model": p.model,
        "messages": messages.iter().map(|m| json!({"role": m.role, "content": m.content})).collect::<Vec<_>>(),
    });
    if let Some(m) = p.max_tokens_for(purpose) {
        body["max_tokens"] = json!(m);
    }
    if p.json_mode {
        body["response_format"] = json!({"type": "json_object"});
    }
    if let Some(e) = effort {
        body["reasoning_effort"] = json!(e);
    }
    if p.prompt_cache_key {
        body["prompt_cache_key"] = json!(format!("sao:{}:{profile}:{purpose}", profile.len()));
    }
    body
}

/// Mistral's front proxy refuses an inline `requests` body above about 2.5 MiB (measured
/// 2026-11-09: 2,609,266 bytes accepted, 2,624,891 refused; docs/MODEL_COST.md Part 2).
/// `LIVING_BATCH_INLINE_LIMIT` lowers it (the fake provider's tests).
pub const BATCH_INLINE_LIMIT: usize = 2_400_000;

fn batch_inline_limit() -> usize {
    std::env::var("LIVING_BATCH_INLINE_LIMIT").ok().and_then(|v| v.parse().ok()).unwrap_or(BATCH_INLINE_LIMIT)
}

/// One request of a batch job: an id that comes back with its answer, the character it is
/// for (its journal file) and the messages.
pub struct BatchItem {
    pub id: String,
    pub actor: String,
    pub messages: Vec<Msg>,
}

impl Llm {
    /// Send requests as one provider batch job (Mistral's batch API: inline `requests`,
    /// `POST /v1/batch/jobs`, polled until done, output read from `GET /v1/files/{id}/content`;
    /// half the price, no latency promise). Each answer is journaled like a direct exchange,
    /// with the job id. Off the real-time path: nothing waits on it but memory.
    /// A batch job's requests go inline up to [`BATCH_INLINE_LIMIT`] bytes, else as an uploaded
    /// JSONL file (`POST /v1/files`, purpose `batch`, then `input_files`).
    pub async fn batch(&self, route: &str, at: Attention, purpose: &str, items: Vec<BatchItem>, poll: Duration, give_up: Duration) -> Result<Vec<(String, Result<Reply>)>> {
        let pick = self.pick(route, purpose, at);
        let profile = pick.profile.as_str();
        let p = self.models.profiles.get(profile).ok_or_else(|| anyhow!("no profile {profile}"))?;
        let key = self.keys.get(profile).ok_or_else(|| anyhow!("profile {profile} has no key"))?;
        let base = p.base_url.trim_end_matches('/');
        let bodies: HashMap<String, (String, Value)> = items.iter().map(|i| (i.id.clone(), (i.actor.clone(), request_body(p, profile, purpose, pick.effort.as_deref(), &i.messages)))).collect();
        let requests: Vec<Value> = items.iter().map(|i| json!({"custom_id": i.id, "body": bodies[&i.id].1})).collect();
        let started = Instant::now();
        let mut spec = json!({"model": p.model, "endpoint": "/v1/chat/completions", "metadata": {"purpose": purpose}});
        let inline = serde_json::to_vec(&requests)?.len();
        let via = if inline > batch_inline_limit() {
            let jsonl: String = requests.iter().map(|r| format!("{r}\n")).collect();
            let boundary = format!("----sao{}", now_ms());
            let mut body = format!("--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nbatch\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{purpose}.jsonl\"\r\nContent-Type: application/jsonl\r\n\r\n").into_bytes();
            body.extend_from_slice(jsonl.as_bytes());
            body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
            let file: Value = self
                .http
                .post(format!("{base}/files"))
                .bearer_auth(key)
                .header("content-type", format!("multipart/form-data; boundary={boundary}"))
                .body(body)
                .send()
                .await
                .context("batch file upload")?
                .error_for_status()
                .context("batch file upload")?
                .json()
                .await?;
            let file = file["id"].as_str().ok_or_else(|| anyhow!("batch file upload: no file id in {file}"))?.to_string();
            spec["input_files"] = json!([file]);
            format!("file {file}, {} bytes", jsonl.len())
        } else {
            spec["requests"] = Value::Array(requests);
            format!("inline, {inline} bytes")
        };
        let job: Value = self.http.post(format!("{base}/batch/jobs")).bearer_auth(key).json(&spec).send().await.context("batch create")?.error_for_status().context("batch create")?.json().await?;
        let id = job["id"].as_str().ok_or_else(|| anyhow!("batch create: no job id in {job}"))?.to_string();
        log::info!("batch job {id}: {} {purpose} requests to {} ({via})", items.len(), p.model);
        let done = loop {
            tokio::time::sleep(poll).await;
            let j: Value = self.http.get(format!("{base}/batch/jobs/{id}")).bearer_auth(key).send().await?.error_for_status()?.json().await?;
            match j["status"].as_str().unwrap_or_default() {
                "SUCCESS" | "FAILED" | "TIMEOUT_EXCEEDED" | "CANCELLED" => break j,
                _ if started.elapsed() > give_up => {
                    let _ = self.http.post(format!("{base}/batch/jobs/{id}/cancel")).bearer_auth(key).send().await;
                    return Err(anyhow!("batch job {id} not done after {:?}; cancelled", give_up));
                }
                _ => {}
            }
        };
        let latency_ms = started.elapsed().as_millis() as u32;
        let mut lines = Vec::new();
        for file in [&done["output_file"], &done["error_file"]] {
            if let Some(f) = file.as_str().filter(|f| !f.is_empty()) {
                let text = self.http.get(format!("{base}/files/{f}/content")).bearer_auth(key).send().await?.error_for_status()?.text().await?;
                lines.extend(text.lines().filter(|l| !l.trim().is_empty()).filter_map(|l| serde_json::from_str::<Value>(l).ok()));
            }
        }
        let mut out = Vec::new();
        for item in &items {
            let line = lines.iter().find(|l| l["custom_id"].as_str() == Some(item.id.as_str()));
            // An answer line carries the chat completion under `response.body` (or `response`).
            let resp = line.map(|l| if l["response"]["body"].is_object() { &l["response"]["body"] } else { &l["response"] });
            let result: Result<(String, u32, Value)> = match resp.filter(|r| r["choices"].is_array()) {
                Some(r) => Ok((content_text(&r["choices"][0]["message"]["content"]), r["usage"]["total_tokens"].as_u64().unwrap_or(0) as u32, r["usage"].clone())),
                None => Err(anyhow!("batch job {id} ({}): no answer for {}: {}", done["status"], item.id, line.map(|l| l.to_string()).unwrap_or_default().chars().take(400).collect::<String>())),
            };
            let (actor, body) = &bodies[&item.id];
            let entry = json!({
                "at_ms": now_ms(),
                "actor": actor,
                "purpose": purpose,
                "profile": profile,
                "model": p.model,
                "effort": pick.effort,
                "mix": pick.mix,
                "attention": pick.attention,
                "mode": "batch",
                "job": id,
                "custom_id": item.id,
                "latency_ms": latency_ms,
                "prompt_tokens": result.as_ref().ok().and_then(|(_, _, u)| u["prompt_tokens"].as_u64()),
                "completion_tokens": result.as_ref().ok().and_then(|(_, _, u)| u["completion_tokens"].as_u64()),
                "cached_tokens": result.as_ref().ok().and_then(|(_, _, u)| u["prompt_tokens_details"]["cached_tokens"].as_u64()),
                "request": body,
                "reply": result.as_ref().map(|(c, _, _)| c.clone()).ok(),
                "tokens": result.as_ref().map(|(_, t, _)| *t).ok(),
                "error": result.as_ref().err().map(|e| format!("{e:#}")),
            });
            self.journal(actor, &entry).await;
            out.push((item.id.clone(), result.map(|(content, tokens, _)| Reply { content, tokens, latency_ms, model: p.model.clone() })));
        }
        log::info!("batch job {id} {} in {:.0} s", done["status"], latency_ms as f64 / 1000.0);
        Ok(out)
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

    fn test_scheduler() -> Scheduler {
        let models: ModelsFile = serde_json::from_value(json!({"default": "p", "profiles": {
            "p": {"base_url": "x", "model": "m", "key_env": "unused", "requests_per_minute": 60}
        }}))
        .unwrap();
        Scheduler::new(&models, 1, 60.0)
    }

    fn enqueue(q: &mut Queue, lane: Lane, cost: u64) -> u64 {
        q.sequence += 1;
        q.waiting.push_back(Waiting { id: q.sequence, profile: "p".into(), lane, cost });
        q.sequence
    }

    fn complete(q: &mut Queue, lane: Lane) {
        q.in_flight -= 1;
        q.lower_in_flight -= usize::from(lane != Lane::Interactive);
    }

    #[test]
    fn background_has_a_bounded_share_under_continuously_refilled_routine_load() {
        for urgent in [false, true] {
            let scheduler = test_scheduler();
            let mut q = scheduler.queue.lock().unwrap();
            let now = q.global_next;
            enqueue(&mut q, Lane::Routine, 10);
            enqueue(&mut q, Lane::Background, 10);
            if urgent {
                enqueue(&mut q, Lane::Urgent, 10);
            }
            let cycle = if urgent { 10 } else { 4 };
            let mut background = 0;
            for step in 0..cycle * 10 {
                let at = now + Duration::from_secs(step);
                let id = q.candidate(at).expect("capacity is available");
                let (lane, _) = q.start(id, at);
                assert_eq!(q.candidate(at), None, "the single slot is saturated");
                complete(&mut q, lane);
                enqueue(&mut q, lane, 10);
                background += usize::from(lane == Lane::Background);
                if (step + 1) % cycle == 0 {
                    assert_eq!(background, 1, "Background needs one admission in every {cycle} while Routine never empties");
                    background = 0;
                }
            }
        }
    }

    #[test]
    fn interactive_preempts_every_weighted_turn_and_urgent_beats_routine() {
        let scheduler = test_scheduler();
        let mut q = scheduler.queue.lock().unwrap();
        let now = q.global_next;
        for lane in [Lane::Background, Lane::Routine, Lane::Urgent] {
            enqueue(&mut q, lane, 10);
        }
        let mut admitted = Vec::new();
        for step in 0..10 {
            let at = now + Duration::from_secs(step * 2);
            let interactive = enqueue(&mut q, Lane::Interactive, 10);
            assert_eq!(q.candidate(at), Some(interactive));
            let (lane, _) = q.start(interactive, at);
            complete(&mut q, lane);
            let at = at + Duration::from_secs(1);
            let id = q.candidate(at).unwrap();
            let (lane, _) = q.start(id, at);
            admitted.push(lane);
            complete(&mut q, lane);
            enqueue(&mut q, lane, 10);
        }
        assert_eq!(admitted[0], Lane::Urgent, "Urgent precedes Routine even when enqueued later");
        assert_eq!(admitted.iter().filter(|lane| **lane == Lane::Urgent).count(), 6);
        assert_eq!(admitted.iter().filter(|lane| **lane == Lane::Routine).count(), 3);
        assert_eq!(admitted.iter().filter(|lane| **lane == Lane::Background).count(), 1);
    }

    #[test]
    fn a_background_turn_waits_for_tokens_instead_of_feeding_cheaper_routine_calls() {
        let scheduler = test_scheduler();
        let mut q = scheduler.queue.lock().unwrap();
        let now = q.global_next;
        q.rates.get_mut("p").unwrap().tpm = Some(100);
        enqueue(&mut q, Lane::Routine, 10);
        let background = enqueue(&mut q, Lane::Background, 80);
        for step in 0..3 {
            let at = now + Duration::from_secs(step);
            let id = q.candidate(at).unwrap();
            let (lane, _) = q.start(id, at);
            assert_eq!(lane, Lane::Routine);
            complete(&mut q, lane);
            enqueue(&mut q, lane, 10);
        }
        assert_eq!(q.candidate(now + Duration::from_secs(3)), None, "save the turn for the larger Background reservation");
        let interactive = enqueue(&mut q, Lane::Interactive, 1);
        assert_eq!(q.candidate(now + Duration::from_secs(3)), Some(interactive));
        let (lane, _) = q.start(interactive, now + Duration::from_secs(3));
        complete(&mut q, lane);
        assert_eq!(q.candidate(now + Duration::from_secs(60)), None);
        assert_eq!(q.candidate(now + Duration::from_secs(61)), Some(background));
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
        assert_eq!(rate.rpm, 19.8);
        headers.clear();
        headers.insert("x-ratelimit-remaining-req-minute", "0".parse().unwrap());
        rate.feedback(1, false, &headers, None, now + Duration::from_secs(120));
        assert!(rate.ready_at(20, now + Duration::from_secs(120)) >= now + Duration::from_secs(180));
    }

    #[test]
    fn learned_limits_log_changes_and_flush_the_latest_suppressed_update() {
        let now = Instant::now();
        let mut rate = Rate::new(&test_profile(), now);
        assert_eq!(rate.take_limit_update(now), None);
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("x-ratelimit-limit-req-minute", "50".parse().unwrap());
        headers.insert("x-ratelimit-limit-tokens-minute", "1000".parse().unwrap());
        rate.feedback(0, false, &headers, None, now);
        assert_eq!(rate.take_limit_update(now), Some(RateLimits { ceiling: 45.0, rpm: 45.0, tpm: Some(900) }));
        rate.feedback(0, false, &headers, None, now + Duration::from_secs(1));
        assert_eq!(rate.take_limit_update(now + Duration::from_secs(1)), None, "unchanged headers do not log");
        headers.insert("x-ratelimit-limit-req-minute", "40".parse().unwrap());
        headers.insert("x-ratelimit-limit-tokens-minute", "500".parse().unwrap());
        rate.feedback(0, false, &headers, None, now + Duration::from_secs(2));
        assert_eq!(rate.take_limit_update(now + Duration::from_secs(2)), None, "changes within thirty seconds coalesce");
        rate.feedback(0, false, &Default::default(), None, now + RATE_LOG_INTERVAL);
        assert_eq!(rate.take_limit_update(now + RATE_LOG_INTERVAL), Some(RateLimits { ceiling: 36.0, rpm: 36.0, tpm: Some(450) }));
        assert_eq!(rate.take_limit_update(now + RATE_LOG_INTERVAL * 2), None);
        headers.insert("x-ratelimit-limit-req-minute", "60".parse().unwrap());
        rate.feedback(0, false, &headers, None, now + RATE_LOG_INTERVAL * 2);
        assert_eq!(rate.take_limit_update(now + RATE_LOG_INTERVAL * 2), Some(RateLimits { ceiling: 54.0, rpm: 36.0, tpm: Some(450) }), "ceiling-only changes also log");
    }

    #[test]
    fn rate_decreases_and_recovery_log_without_provider_headers() {
        let now = Instant::now();
        let mut rate = Rate::new(&test_profile(), now);
        rate.sent(1, 10, now);
        rate.feedback(1, true, &Default::default(), None, now);
        assert_eq!(rate.take_limit_update(now), Some(RateLimits { ceiling: 60.0, rpm: 30.0, tpm: None }));
        rate.feedback(1, true, &Default::default(), None, now + Duration::from_secs(1));
        assert_eq!(rate.take_limit_update(now + Duration::from_secs(1)), None, "duplicate congestion feedback does not log");
        rate.feedback(1, false, &Default::default(), Some(10), now + Duration::from_secs(11));
        assert_eq!(rate.take_limit_update(now + Duration::from_secs(11)), None);
        assert_eq!(rate.take_limit_update(now + RATE_LOG_INTERVAL), Some(RateLimits { ceiling: 60.0, rpm: 33.0, tpm: None }));
    }

    #[test]
    fn a_burst_of_429s_decreases_once_and_new_congestion_respects_the_floor() {
        let now = Instant::now();
        let mut p = test_profile();
        p.requests_per_minute = Some(400.0);
        let mut rate = Rate::new(&p, now);
        for id in 1..=20 {
            rate.sent(id, 10, now + Duration::from_millis(id));
        }
        for id in 1..=20 {
            rate.feedback(id, true, &Default::default(), None, now + Duration::from_secs(1));
            assert_eq!(rate.rpm, 200.0, "one burst must cause one decrease");
        }
        for id in 21..=30 {
            let sent = now + Duration::from_secs(id);
            rate.sent(id, 10, sent);
            rate.feedback(id, true, &Default::default(), None, sent + Duration::from_millis(1));
        }
        assert_eq!(rate.rpm, 20.0, "five percent of the ceiling is the floor");
        rate.feedback(1, true, &Default::default(), None, now + Duration::from_secs(31));
        assert_eq!(rate.rpm, 20.0, "a delayed response cannot decrease again");
    }

    #[test]
    fn a_halved_rate_recovers_in_one_hundred_seconds_without_more_429s() {
        let now = Instant::now();
        let mut p = test_profile();
        p.requests_per_minute = Some(400.0);
        let mut rate = Rate::new(&p, now);
        rate.sent(1, 10, now);
        rate.feedback(1, true, &Default::default(), None, now);
        assert_eq!(rate.rpm, 200.0);
        rate.feedback(1, false, &Default::default(), Some(10), now + Duration::from_secs(9));
        assert_eq!(rate.rpm, 200.0, "recovery waits ten seconds");
        for step in 1..=10 {
            let at = now + RATE_RECOVERY_INTERVAL * step;
            rate.sent(u64::from(step) + 1, 10, at);
            rate.feedback(u64::from(step) + 1, false, &Default::default(), Some(10), at);
            assert_eq!(rate.rpm, 200.0 + 20.0 * f64::from(step));
        }
        rate.feedback(11, false, &Default::default(), Some(10), now + Duration::from_secs(110));
        assert_eq!(rate.rpm, rate.ceiling);
    }

    #[test]
    fn an_unconfigured_profile_starts_at_six_hundred_until_provider_feedback() {
        let now = Instant::now();
        let p: Profile = serde_json::from_value(json!({"base_url": "x", "model": "m", "key_env": "unused"})).unwrap();
        assert_eq!(p.requests_per_minute, None);
        let mut rate = Rate::new(&p, now);
        assert_eq!(rate.rpm, 600.0);
        rate.sent(1, 10, now);
        assert_eq!(rate.ready_at(10, now), now + Duration::from_millis(100));
        rate.feedback(1, false, &Default::default(), Some(10), now + Duration::from_secs(10));
        assert_eq!(rate.rpm, 600.0);
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("x-ratelimit-limit-req-minute", "1000".parse().unwrap());
        rate.feedback(1, false, &headers, None, now + Duration::from_secs(10));
        assert_eq!(rate.ceiling, 900.0, "starting rate is not a static ceiling");
        headers.insert("x-ratelimit-limit-req-minute", "400".parse().unwrap());
        rate.feedback(1, false, &headers, None, now + Duration::from_secs(10));
        assert_eq!(rate.rpm, 360.0);
        let mut no_headers = Rate::new(&p, now);
        no_headers.sent(1, 10, now);
        no_headers.feedback(1, true, &Default::default(), None, now);
        assert_eq!(no_headers.rpm, 300.0);
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
            mixes: Default::default(),
            woken: None,
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
            mixes: Default::default(),
            woken: None,
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
        let reply = llm.chat_in_lane("p", Attention::OnStage, "think", "first", &messages, Lane::Interactive).await.unwrap();
        assert_eq!(reply.tokens, 17);
        llm.chat_in_lane("p", Attention::OnStage, "think", "second", &messages, Lane::Interactive).await.unwrap();
        llm.chat("p", Attention::OnStage, "talk", "second", &messages).await.unwrap();
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
        uncached.chat("p", Attention::OnStage, "consolidate", "uncached", &messages).await.unwrap();
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

    /// A batch whose inline body would pass the provider's limit is uploaded as a file and
    /// referenced by `input_files`; a small one stays inline. Both carry the picked effort.
    #[tokio::test]
    async fn a_large_batch_is_uploaded_as_a_file() {
        struct Fake(std::process::Child);
        impl Drop for Fake {
            fn drop(&mut self) {
                let _ = self.0.kill();
                let _ = self.0.wait();
            }
        }
        let directory = std::env::temp_dir().join(format!("living-batch-{}", now_ms()));
        std::fs::create_dir_all(&directory).unwrap();
        let socket = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = socket.local_addr().unwrap().port();
        drop(socket);
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let log = directory.join("requests.jsonl");
        let fake = Fake(std::process::Command::new("python3").arg(root.join(".agents/skills/verify-llm/scripts/fake_llm.py")).args(["--port", &port.to_string(), "--log"]).arg(&log).stdout(std::process::Stdio::null()).spawn().unwrap());
        let http = reqwest::Client::new();
        for _ in 0..100 {
            if http.get(format!("http://127.0.0.1:{port}/health")).send().await.is_ok() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        std::env::set_var("LIVING_TEST_BATCH_KEY", "dummy-only");
        let models: ModelsFile = serde_json::from_value(json!({"default": "p", "profiles": {"p": {
            "base_url": format!("http://127.0.0.1:{port}/v1"), "model": "m", "key_env": "LIVING_TEST_BATCH_KEY",
            "reasoning_effort": {"consolidate": "high"}, "purpose_max_tokens": {"reorganize": 24000}}},
            "mixes": {"night": {"reorganize": "p@high", "*": "p"}}}))
        .unwrap();
        let llm = Llm::new(models, directory.join("journal")).unwrap();
        let items = |n: usize, size: usize| -> Vec<BatchItem> {
            (0..n).map(|i| BatchItem { id: format!("sleep-{i}"), actor: format!("a{i}"), messages: vec![Msg { role: "system", content: "Tidy the person's mind.".into() }, Msg { role: "user", content: "x".repeat(size) }] }).collect()
        };
        // Below the limit: inline. The default limit is far above these bodies.
        let small = llm.batch("night", Attention::OffStage, "reorganize", items(3, 100), Duration::from_millis(50), Duration::from_secs(20)).await.unwrap();
        assert!(small.iter().all(|(_, r)| r.is_ok()));
        std::env::set_var("LIVING_BATCH_INLINE_LIMIT", "1000");
        let large = llm.batch("night", Attention::OffStage, "reorganize", items(5, 400), Duration::from_millis(50), Duration::from_secs(20)).await.unwrap();
        std::env::remove_var("LIVING_BATCH_INLINE_LIMIT");
        assert_eq!(large.len(), 5);
        assert!(large.iter().all(|(_, r)| r.is_ok()), "every answer comes back from the uploaded file's job");
        let lines: Vec<Value> = std::fs::read_to_string(&log).unwrap().lines().map(|l| serde_json::from_str(l).unwrap()).collect();
        let uploads: Vec<&Value> = lines.iter().filter(|l| l.get("upload").is_some()).collect();
        assert_eq!(uploads.len(), 1, "one upload, for the large batch only");
        assert_eq!(uploads[0]["lines"], 5);
        let answered: Vec<&Value> = lines.iter().filter(|l| l.get("batch_job").is_some_and(|j| !j.is_null())).collect();
        assert_eq!(answered.len(), 8);
        assert!(answered.iter().all(|l| l["body"]["reasoning_effort"] == "high" && l["body"]["max_tokens"] == 24000 && l["purpose"] == "reorganize"));
        let journal: Value = serde_json::from_str(std::fs::read_to_string(directory.join("journal/a4.jsonl")).unwrap().trim()).unwrap();
        assert_eq!((journal["mode"].as_str(), journal["mix"].as_str(), journal["effort"].as_str(), journal["purpose"].as_str()), (Some("batch"), Some("night"), Some("high"), Some("reorganize")));
        drop(fake);
        println!("batch upload evidence: {}", directory.display());
    }

    /// A night of real reorganizations through this client's batch path (paid; ignored):
    /// `LIVING_NIGHT_BATCH_SAMPLES` is a JSONL of `{"id", "actor", "messages"}` (or
    /// model_cost.py samples with `cls: reorganize`), sent on `LIVING_NIGHT_BATCH_ROUTE`
    /// (default the `people` mix of living/configs/models.json) as one job; prints the job's
    /// turnaround, how it went up, usable replies and tokens. docs/MIND_HARNESS.md, item 2.
    #[tokio::test]
    #[ignore]
    async fn night_batch_replay() {
        let samples = std::env::var("LIVING_NIGHT_BATCH_SAMPLES").expect("LIVING_NIGHT_BATCH_SAMPLES");
        let route = std::env::var("LIVING_NIGHT_BATCH_ROUTE").unwrap_or_else(|_| "people".into());
        let models: ModelsFile = serde_json::from_str(&std::fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../configs/models.json")).unwrap()).unwrap();
        let journal = PathBuf::from(std::env::var("LIVING_NIGHT_BATCH_JOURNAL").unwrap_or_else(|_| std::env::temp_dir().join(format!("living-night-{}", now_ms())).display().to_string()));
        let llm = Llm::new(models, journal.clone()).unwrap();
        let items: Vec<BatchItem> = std::fs::read_to_string(&samples)
            .unwrap()
            .lines()
            .filter_map(|l| serde_json::from_str::<Value>(l).ok())
            .filter(|v| v.get("cls").map_or(true, |c| c == "reorganize"))
            .map(|v| BatchItem {
                id: v["id"].as_str().map(String::from).unwrap_or_else(|| v["id"].to_string()),
                actor: v["actor"].as_str().unwrap_or("night").to_string(),
                messages: v["messages"].as_array().unwrap().iter().map(|m| Msg { role: if m["role"] == "system" { "system" } else { "user" }, content: m["content"].as_str().unwrap().to_string() }).collect(),
            })
            .collect();
        let n = items.len();
        let started = Instant::now();
        let out = llm.batch(&route, Attention::OffStage, "reorganize", items, Duration::from_secs(5), Duration::from_secs(3600)).await.unwrap();
        let secs = started.elapsed().as_secs_f64();
        let usable = out.iter().filter(|(_, r)| r.as_ref().is_ok_and(|r| parse_json(&r.content).is_ok())).count();
        let entries: Vec<Value> = std::fs::read_dir(&journal).unwrap().flatten().flat_map(|f| std::fs::read_to_string(f.path()).unwrap().lines().map(|l| serde_json::from_str::<Value>(l).unwrap()).collect::<Vec<_>>()).collect();
        let sum = |k: &str| entries.iter().filter_map(|e| e[k].as_u64()).sum::<u64>();
        println!("{}", json!({"requests": n, "answers": out.len(), "usable": usable, "turnaround_s": secs, "prompt_tokens": sum("prompt_tokens"), "completion_tokens": sum("completion_tokens"), "cached_tokens": sum("cached_tokens"), "journal": journal, "job": entries.first().map(|e| e["job"].clone()), "effort": entries.first().map(|e| e["effort"].clone()), "max_tokens": entries.first().map(|e| e["request"]["max_tokens"].clone())}));
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
        assert!(llm.chat("dead", Attention::OnStage, "think", "a", &msg).await.is_err());
        assert!(t.elapsed() < Duration::from_millis(1500), "the first failure is immediate");
        let t = Instant::now();
        assert!(llm.chat("dead", Attention::OnStage, "think", "a", &msg).await.is_err());
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

    fn mix_models() -> ModelsFile {
        std::env::set_var("LIVING_TEST_MIX_KEY", "x");
        let p = |m: &str, effort: Value| json!({"base_url": "http://127.0.0.1:9/v1", "model": m, "key_env": "LIVING_TEST_MIX_KEY", "reasoning_effort": effort});
        serde_json::from_value(json!({
            "default": "glm",
            "profiles": {
                "glm": p("glm-m", json!({"think": "low", "deliberate": "high", "consolidate": "high"})),
                "ds": p("ds-m", json!({"deliberate": "low"})),
                "nokey": {"base_url": "x", "model": "n", "key_env": "LIVING_TEST_UNSET_KEY"}
            },
            "mixes": {
                "people": {
                    "talk": "ds",
                    "deliberate": {"on_stage": "ds@low", "off_stage": "glm"},
                    "think": "glm",
                    "consolidate": "glm",
                    "reorganize": "glm@max"
                },
                "broken": {"talk": "nokey", "*": "glm"}
            },
            "groups": {"Brandholm": "people"},
            "stages": {"child": "broken"}
        }))
        .unwrap()
    }

    #[test]
    fn mixes_route_each_purpose_and_stage_with_its_effort() {
        let dir = std::env::temp_dir().join(format!("living-mix-{}", now_ms()));
        let llm = Llm::new(mix_models(), dir.clone()).unwrap();
        let pick = |route: &str, purpose: &str, at| {
            let p = llm.pick(route, purpose, at);
            (p.profile, p.effort, p.mix, p.attention)
        };
        let on = Attention::OnStage;
        let off = Attention::OffStage;
        let s = |x: &str| Some(x.to_string());
        assert_eq!(pick("people", "talk", on), ("ds".into(), None, s("people"), None), "DeepSeek's map leaves talk unset (thinking off)");
        assert_eq!(pick("people", "deliberate", on), ("ds".into(), s("low"), s("people"), Some(on)));
        assert_eq!(pick("people", "deliberate", off), ("glm".into(), s("high"), s("people"), Some(off)), "off stage: the profile's own effort");
        assert_eq!(pick("people", "think", off), ("glm".into(), s("low"), s("people"), None));
        assert_eq!(pick("people", "reorganize", on), ("glm".into(), s("max"), s("people"), None), "an effort written in the mix wins");
        assert_eq!(pick("people", "internalize", on), ("glm".into(), None, None, None), "a purpose the mix leaves out goes to the default");
        assert_eq!(pick("glm", "reorganize", on).1, s("high"), "reorganize inherits consolidate's effort on a profile that does not name it");
        assert_eq!(pick("ds@high", "talk", on), ("ds".into(), s("high"), None, None), "profile@effort works as a plain route too");
        assert_eq!(pick("broken", "think", on).0, "glm", "a mix whose member has no key");
        assert_eq!(llm.person_profile(1, "Tam", Some("Brandholm"), false), "people", "a mix is accepted for groups");
        assert_eq!(llm.person_profile(1, "Tam", None, true), "glm", "and a stage naming an unusable mix is passed over");
        assert!(llm.staged());
        assert_eq!(llm.model_name("people"), "mix people");
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn woken_residents_take_their_route_unless_assigned() {
        let dir = std::env::temp_dir().join(format!("living-woken-{}", now_ms()));
        let llm = Llm::new(mix_models(), dir.clone()).unwrap();
        assert_eq!(llm.woken_route("Tam"), None, "no `woken` route: woken residents route like anyone");
        let mut m = mix_models();
        m.woken = Some("people".into());
        m.assign.insert("Mara".into(), "ds".into());
        m.check().unwrap();
        let llm = Llm::new(m, dir.clone()).unwrap();
        assert_eq!(llm.woken_route("Tam"), Some("people".into()));
        assert_eq!(llm.woken_route("Mara"), Some("ds".into()), "an assignment by name still wins");
        let mut m = mix_models();
        m.woken = Some("broken".into());
        let llm = Llm::new(m, dir.clone()).unwrap();
        assert_eq!(llm.woken_route("Tam"), None, "a route with a profile without a key is passed over");
        let mut m = mix_models();
        m.woken = Some("nobody".into());
        assert!(m.check().unwrap_err().to_string().contains("woken names nobody"));
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn a_models_file_naming_what_does_not_exist_is_refused() {
        let mut m = mix_models();
        m.groups.insert("Saltreach".into(), "nobody".into());
        assert!(m.check().unwrap_err().to_string().contains("neither a profile nor a mix"));
        let mut m = mix_models();
        m.mixes.get_mut("people").unwrap().insert("dream".into(), Choice::One("glm".into()));
        assert!(m.check().unwrap_err().to_string().contains("unknown purpose"));
        let mut m = mix_models();
        m.mixes.get_mut("people").unwrap().insert("talk".into(), Choice::One("broken".into()));
        assert!(m.check().unwrap_err().to_string().contains("not a profile"), "mixes do not nest");
        let mut m = mix_models();
        m.default = "people".into();
        assert!(m.check().unwrap_err().to_string().contains("cover every purpose"));
        m.mixes.get_mut("people").unwrap().insert("*".into(), Choice::One("glm".into()));
        assert!(m.check().is_ok());
        assert!(mix_models().check().is_ok());
    }

    #[test]
    fn the_request_body_carries_the_picked_effort_and_the_purpose_cap() {
        let mut p = test_profile();
        p.reasoning_effort.insert("consolidate".into(), Some("high".into()));
        p.max_tokens = Some(8000);
        p.purpose_max_tokens.insert("reorganize".into(), 24000);
        let msgs = [Msg { role: "user", content: "x".into() }];
        let b = request_body(&p, "p", "reorganize", p.effort("reorganize").map(|s| s.as_str()), &msgs);
        assert_eq!((b["reasoning_effort"].as_str(), b["max_tokens"].as_u64()), (Some("high"), Some(24000)));
        let b = request_body(&p, "p", "consolidate", Some("low"), &msgs);
        assert_eq!((b["reasoning_effort"].as_str(), b["max_tokens"].as_u64()), (Some("low"), Some(8000)));
        assert!(request_body(&p, "p", "talk", None, &msgs).get("reasoning_effort").is_none());
    }

    #[test]
    fn the_projects_models_file_is_valid() {
        let text = std::fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../configs/models.json")).unwrap();
        let m: ModelsFile = serde_json::from_str(&text).unwrap();
        m.check().unwrap();
    }

    /// Every purpose the project's routes send has an effort entry (`null` included), and a
    /// purpose a profile is reached for without one is reported, through a mix and through an
    /// overflow (for the purposes that overflow).
    #[test]
    fn purposes_sent_without_an_effort_entry_are_reported() {
        let text = std::fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../configs/models.json")).unwrap();
        let m: ModelsFile = serde_json::from_str(&text).unwrap();
        assert_eq!(m.effort_gaps(), Vec::<String>::new(), "the project's models file");
        let m: ModelsFile = serde_json::from_value(json!({
            "default": "glm",
            "profiles": {
                "glm": {"base_url": "x", "model": "g", "key_env": "K", "overflow": "ds", "reasoning_effort": {"think": "low", "deliberate": "low", "talk": "high", "consolidate": "high", "internalize": "high"}},
                "ds": {"base_url": "x", "model": "d", "key_env": "K", "reasoning_effort": {"think": "low", "talk": null}}
            },
            "mixes": {"m": {"internalize": "ds", "consolidate": "ds@low", "*": "glm"}},
            "groups": {"Brandholm": "m"}
        }))
        .unwrap();
        let gaps = m.effort_gaps();
        let has = |s: &str| gaps.iter().any(|g| g.contains(s));
        assert!(has("profile ds has no reasoning_effort for internalize (reached by Brandholm → m)"), "{gaps:?}");
        assert!(has("profile ds has no reasoning_effort for deliberate (the overflow of glm"), "{gaps:?}");
        assert!(!has("for talk"), "null is an entry: {gaps:?}");
        assert!(!has("ds has no reasoning_effort for consolidate"), "an @effort in the mix is one, and background purposes do not overflow: {gaps:?}");
        assert!(!has("glm has no reasoning_effort for reorganize"), "reorganize inherits consolidate: {gaps:?}");
        // ds's compile as glm's overflow, by the default and by the mix, and its internalize.
        assert_eq!(gaps.len(), 3, "{gaps:?}");
    }

    /// A failed background call (memory) is not sent to the overflow profile, which would
    /// answer with its own settings for the purpose; a routine call still overflows.
    #[tokio::test]
    async fn background_calls_do_not_overflow() {
        std::env::set_var("LIVING_TEST_BACKGROUND_KEY", "x");
        let efforts = json!({"think": "low", "consolidate": "high", "reorganize": "high"});
        let models: ModelsFile = serde_json::from_value(json!({"default": "a", "profiles": {
            "a": {"base_url": "http://127.0.0.1:9/v1", "model": "a", "key_env": "LIVING_TEST_BACKGROUND_KEY", "overflow": "b", "reasoning_effort": efforts},
            "b": {"base_url": "http://localhost:9/v1", "model": "b", "key_env": "LIVING_TEST_BACKGROUND_KEY", "reasoning_effort": efforts}}}))
        .unwrap();
        let dir = std::env::temp_dir().join(format!("living-background-{}", now_ms()));
        let llm = Llm::new(models, dir.clone()).unwrap();
        let msg = [Msg { role: "user", content: "hi".into() }];
        for purpose in ["consolidate", "reorganize"] {
            assert!(llm.chat("a", Attention::OnStage, purpose, purpose, &msg).await.is_err());
        }
        assert!(llm.chat("a", Attention::OnStage, "think", "think", &msg).await.is_err());
        let profiles = |actor: &str| -> Vec<String> {
            std::fs::read_to_string(dir.join(format!("{actor}.jsonl"))).unwrap().lines().map(|l| serde_json::from_str::<Value>(l).unwrap()["profile"].as_str().unwrap().to_string()).collect()
        };
        assert_eq!(profiles("consolidate"), ["a"]);
        assert_eq!(profiles("reorganize"), ["a"]);
        assert_eq!(profiles("think"), ["a", "b"], "a routine call overflows");
        let _ = std::fs::remove_dir_all(dir);
    }

    /// A runaway generation stops near what the purpose needs (measured p99 output on
    /// rules2-r2: think 465, compile 1,008, consolidate 2,388) instead of at 24,000 tokens:
    /// every profile caps every purpose the mind sends, and only `reorganize` goes past 6,000.
    #[test]
    fn every_profile_caps_each_purpose_near_its_need() {
        let text = std::fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../configs/models.json")).unwrap();
        let m: ModelsFile = serde_json::from_str(&text).unwrap();
        for (name, p) in &m.profiles {
            for purpose in ["think", "deliberate", "talk", "consolidate", "internalize", "reorganize", "rethink"] {
                let cap = p.max_tokens_for(purpose).unwrap_or(u32::MAX);
                assert!(p.purpose_max_tokens.contains_key(purpose), "{name} has no cap of its own for {purpose}");
                if purpose == "reorganize" {
                    assert!(cap >= 24000, "{name}: reorganize at GLM high needs 24,000 (MODEL_COST Part 2)");
                } else {
                    assert!(cap <= 6000, "{name}: {purpose} capped at {cap}");
                }
            }
            assert!(p.max_tokens_for("think").unwrap() <= 2000 && p.max_tokens_for("talk").unwrap() <= 1000, "{name}");
        }
    }

    #[test]
    fn repairs_small_model_slips() {
        let v = parse_json("{\n  \"remember\": [],\n  \"nodes\": [\n    },\n    {\"key\": \"self\"}\n  ],\n  \"edges\": [1, 2,],\n}").unwrap();
        assert_eq!(v["nodes"][0]["key"], "self");
        assert_eq!(v["edges"].as_array().unwrap().len(), 2);
    }
}
