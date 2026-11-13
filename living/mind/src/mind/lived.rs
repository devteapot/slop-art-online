//! What a human-played character lives becomes its memory (on by default; `LIVING_PLAYER_MEMORY=0`
//! turns it off; design in docs/PLAYER_MEMORY.md).
//!
//! A player's character receives the same experiences as everyone (the authority's
//! `experience` rows, controlled by the player's identity while the player controls it). This
//! service subscribes to those rows, copies each into a per-character buffer as it arrives (the
//! authority deletes a dead character's rows, and its window keeps only the last 400) and, on a
//! slow cadence, integrates them into the character's Neo4j mind the way consolidation does
//! for an AI character, off the real-time path:
//!
//! - **when:** a buffer of `LIVING_PLAYER_MEMORY_BUFFER` meaningful experiences (default 40) or
//!   `LIVING_PLAYER_MEMORY_CAP` in all (default 200, below the authority's window); one game
//!   day after the first experience waiting (`LIVING_PLAYER_MEMORY_EVERY_S` overrides); the end
//!   of a session, which is the authority's presence signal: the world's minds took the
//!   character over because its person left (`presence.ai`); and at once when it dies;
//! - **with what:** `LIVING_PLAYER_MEMORY_MODEL` (a profile; default the models file's
//!   default), with one system prompt shared by every player (`prompts::internalize_system`)
//!   so a provider caches it;
//! - **how:** `LIVING_PLAYER_MEMORY_MODE=direct` (one call per character) or `batch` (every
//!   character due at once goes into one provider batch job, `llm::Llm::batch`);
//! - **what is written:** the patch, with `lived_under = ["human"]` on every concept, memory
//!   and belief it writes, a `thought` of kind `internalize`, the relations, judgments, places
//!   and beliefs projected from the graph, and the identity (narrative, values, traits, mood)
//!   inferred from the person's conduct when it shows something new (`mind_update`, which the
//!   authority accepts from the mind service for a played character). How far a character is
//!   internalized is kept on its `self` node (`lived_upto`); the experience rows stay in place.
//!
//! When the minds take a character over, its first deliberation waits until what its person
//! lived is internalized (at most `LIVING_TAKEOVER_WAIT_S`, default 120 s), so it thinks with
//! its own past. What it then lives under the minds is consolidated as for any AI character,
//! with `lived_under = ["ai"]`.
//!
//! The model never sees the player's input, the reasons for their choices or anything the
//! character did not perceive: only its experience rows, where they happened (its own
//! position, and the settlement around it) and what its own mind already holds.

use super::{reference, Minds};
use crate::llm::{self, BatchItem, Lane, Msg};
use crate::{memory, prompts};
use anyhow::Result;
use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::Table;
use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;
use std::time::{Duration, Instant};

/// Whether player memory is on (the default; `LIVING_PLAYER_MEMORY=0`, `off` or `false`
/// turns it off). The takeover of an offline player's character depends on it for its past.
pub fn enabled() -> bool {
    !matches!(std::env::var("LIVING_PLAYER_MEMORY").as_deref(), Ok("0") | Ok("off") | Ok("false"))
}

fn env<T: std::str::FromStr>(k: &str) -> Option<T> {
    std::env::var(k).ok().and_then(|v| v.trim().parse().ok())
}

/// Experiences of one character kept in the service at most (a long outage drops the oldest).
const KEPT: usize = 2_000;

#[derive(Clone, Debug)]
pub struct Config {
    pub on: bool,
    pub buffer: usize,
    pub cap: usize,
    pub every: Option<Duration>,
    /// Longest a taken-over character's first deliberation waits for its lived past.
    pub takeover_wait: Duration,
    /// Experiences per integration at most (a larger backlog takes several).
    pub take: usize,
    pub profile: Option<String>,
    pub batch: bool,
    pub poll: Duration,
    pub give_up: Duration,
}

impl Config {
    pub fn from_env() -> Self {
        Self {
            on: enabled(),
            buffer: env("LIVING_PLAYER_MEMORY_BUFFER").unwrap_or(40),
            cap: env("LIVING_PLAYER_MEMORY_CAP").unwrap_or(200),
            every: env::<f64>("LIVING_PLAYER_MEMORY_EVERY_S").map(Duration::from_secs_f64),
            takeover_wait: Duration::from_secs_f64(env("LIVING_TAKEOVER_WAIT_S").unwrap_or(120.0)),
            take: env("LIVING_PLAYER_MEMORY_TAKE").unwrap_or(120),
            profile: std::env::var("LIVING_PLAYER_MEMORY_MODEL").ok().filter(|s| !s.trim().is_empty()),
            batch: std::env::var("LIVING_PLAYER_MEMORY_MODE").as_deref() == Ok("batch"),
            poll: Duration::from_secs_f64(env("LIVING_PLAYER_MEMORY_POLL_S").unwrap_or(15.0)),
            give_up: Duration::from_secs_f64(env("LIVING_PLAYER_MEMORY_BATCH_WAIT_S").unwrap_or(3_600.0)),
        }
    }
}

#[derive(Default)]
struct Player {
    exps: BTreeMap<u64, Experience>,
    /// Internalized up to (from the mind's `self` node; None until read).
    cursor: Option<u64>,
    loading: bool,
    /// When the oldest experience still waiting arrived.
    since: Option<Instant>,
    busy: bool,
    failures: u32,
    retry_after: Option<Instant>,
}

#[derive(Default)]
pub struct Lived {
    players: HashMap<u32, Player>,
}

/// One character's integration, ready to be sent.
pub(super) struct Prepared {
    actor: u32,
    name: String,
    upto: u64,
    batch: Vec<Experience>,
    known: Vec<u64>,
    pub(super) msgs: Vec<Msg>,
    reason: &'static str,
}

/// Why a character's waiting experiences are due for integration, if they are: it died, its
/// person left (`away`: the minds took it over, the authority's presence signal), the buffer
/// is full, or a game day has passed since the oldest arrived (`waited`).
fn reason_due<'a>(cfg: &Config, waiting: impl Iterator<Item = &'a Experience> + Clone, alive: bool, away: bool, waited: Duration, every: Duration) -> Option<&'static str> {
    let all = waiting.clone().count();
    if all == 0 {
        return None;
    }
    let meaningful = waiting.clone().filter(|e| e.salience >= 0.2).count();
    if !alive {
        Some("death")
    } else if away {
        Some("session end")
    } else if meaningful >= cfg.buffer || all >= cfg.cap {
        Some("buffer")
    } else if meaningful > 0 && waited >= every {
        Some("game day")
    } else {
        None
    }
}

impl Minds {
    /// An experience a person lived through their character, as it arrives (or as found at
    /// start): a row controlled by someone other than this service. The character may have
    /// passed to the minds since; what its person lived is still theirs to internalize.
    pub(super) fn lived_add(&self, e: Experience) {
        if !self.lived_cfg.on || self.store.is_none() || !self.allowed(e.observer) || e.controller == self.me {
            return;
        }
        if !self.conn.db.character().id().find(&e.observer).is_some_and(|c| c.kind == "person") {
            return;
        }
        let mut l = self.lived.lock().unwrap();
        let p = l.players.entry(e.observer).or_default();
        if p.cursor.is_some_and(|c| e.id <= c) {
            return;
        }
        p.exps.insert(e.id, e);
        p.since.get_or_insert_with(Instant::now);
        while p.exps.len() > KEPT {
            let first = *p.exps.keys().next().unwrap();
            p.exps.remove(&first);
            log::warn!("lived experience {first} dropped: more than {KEPT} waiting");
        }
    }

    /// Start integration for the human-played characters that are due (every 2 s).
    pub(super) fn check_lived(self: Arc<Self>) {
        if !self.lived_cfg.on || self.store.is_none() {
            return;
        }
        let cfg = &self.lived_cfg;
        let day = self.conn.db.world().id().find(&0).map(|w| w.day_ms).unwrap_or(living_rules::DEFAULT_DAY_MS);
        let every = cfg.every.unwrap_or(Duration::from_millis(day));
        let now = Instant::now();
        let mut due = Vec::new();
        let mut load = Vec::new();
        {
            let mut l = self.lived.lock().unwrap();
            for (&id, p) in l.players.iter_mut() {
                if p.cursor.is_none() {
                    if !p.loading {
                        p.loading = true;
                        load.push(id);
                    }
                    continue;
                }
                if p.busy || p.retry_after.is_some_and(|t| now < t) || p.exps.is_empty() {
                    continue;
                }
                let alive = self.conn.db.character().id().find(&id).is_some_and(|c| c.alive);
                let away = self.conn.db.presence().id().find(&id).is_some_and(|p| p.ai);
                let waited = p.since.map_or(Duration::ZERO, |t| now.duration_since(t));
                if let Some(r) = reason_due(cfg, p.exps.values(), alive, away, waited, every) {
                    p.busy = true;
                    due.push((id, r));
                }
            }
        }
        for id in load {
            let this = self.clone();
            tokio::spawn(async move {
                let Some(store) = &this.store else { return };
                let name = this.name(id);
                let r = async {
                    store.ensure_self(id, &name).await?;
                    store.lived_upto(id).await
                }
                .await;
                let mut l = this.lived.lock().unwrap();
                let Some(p) = l.players.get_mut(&id) else { return };
                p.loading = false;
                match r {
                    Ok(upto) => {
                        let upto = upto.unwrap_or(0);
                        p.cursor = Some(upto);
                        p.exps.retain(|k, _| *k > upto);
                        log::info!("{name} (#{id}) is played by a person: lived experience internalized up to {upto}, {} waiting", p.exps.len());
                    }
                    Err(e) => log::warn!("lived cursor for {name}: {e:#}"),
                }
            });
        }
        if due.is_empty() {
            return;
        }
        if cfg.batch {
            let this = self.clone();
            tokio::spawn(async move { this.internalize_batch(due).await });
        } else {
            for (id, reason) in due {
                let this = self.clone();
                tokio::spawn(async move {
                    let r = this.internalize_one(id, reason).await;
                    this.lived_done(id, r);
                });
            }
        }
    }

    /// Whether what a person lived through this character is still waiting to be internalized
    /// (a taken-over character's first thought waits for it).
    pub(super) fn lived_waiting(&self, id: u32) -> bool {
        if !self.lived_cfg.on || self.store.is_none() {
            return false;
        }
        let l = self.lived.lock().unwrap();
        l.players.get(&id).is_some_and(|p| p.busy || p.loading || p.cursor.is_none() || !p.exps.is_empty())
    }

    fn lived_profile(&self) -> String {
        self.lived_cfg.profile.clone().unwrap_or_else(|| self.llm.default_profile())
    }

    fn lived_done(&self, id: u32, r: Result<()>) {
        let alive = self.conn.db.character().id().find(&id).is_some_and(|c| c.alive);
        let mut l = self.lived.lock().unwrap();
        let Some(p) = l.players.get_mut(&id) else { return };
        p.busy = false;
        match r {
            Ok(()) => {
                p.failures = 0;
                p.retry_after = None;
                p.since = (!p.exps.is_empty()).then(Instant::now);
                if !alive && p.exps.is_empty() {
                    l.players.remove(&id);
                }
            }
            Err(e) => {
                p.failures += 1;
                p.retry_after = Some(Instant::now() + Duration::from_secs(30 * p.failures as u64));
                log::warn!("internalizing what {} lived failed ({}x): {e:#}", self.name(id), p.failures);
            }
        }
    }

    /// Where an experience happened, as the character could tell: its position and the
    /// settlement it was in or near.
    fn lived_where(&self, e: &Experience) -> String {
        let mut best: Option<(f32, String, f32)> = None;
        for s in self.conn.db.settlement().iter() {
            let d = ((s.x - e.x).powi(2) + (s.y - e.y).powi(2)).sqrt();
            if d <= s.radius_m * 2.0 && best.as_ref().map_or(true, |b| d < b.0) {
                let name = self.conn.db.community().id().find(&s.community).map(|c| c.name).unwrap_or_else(|| format!("a {}", s.kind.replace('_', " ")));
                best = Some((d, name, s.radius_m));
            }
        }
        let at = format!(" @[{:.0}, {:.0}]", e.x, e.y);
        match best {
            Some((d, name, r)) if d <= r => format!("{at} in {name}"),
            Some((_, name, _)) => format!("{at} outside {name}"),
            None => at,
        }
    }

    async fn lived_prepare(&self, actor: u32, reason: &'static str) -> Result<Option<Prepared>> {
        let Some(store) = &self.store else { return Ok(None) };
        let Some(c) = self.conn.db.character().id().find(&actor) else { return Ok(None) };
        let batch: Vec<Experience> = {
            let l = self.lived.lock().unwrap();
            let Some(p) = l.players.get(&actor) else { return Ok(None) };
            p.exps.values().take(self.lived_cfg.take).cloned().collect()
        };
        let Some(upto) = batch.last().map(|e| e.id) else { return Ok(None) };
        if !batch.iter().any(|e| e.salience >= 0.2) {
            self.lived_advance(actor, upto).await?;
            return Ok(None);
        }
        let _ = store;
        self.integration(&c, batch, upto, reason).await.map(Some)
    }

    /// An integration of `batch` into the character's mind, ready to be sent: its meaningful
    /// lines (salience 0.2 and above) with where they happened, what its mind recalls for them,
    /// and who it is.
    async fn integration(&self, c: &Character, batch: Vec<Experience>, upto: u64, reason: &'static str) -> Result<Prepared> {
        let Some(store) = &self.store else { return Err(anyhow::anyhow!("no memory store")) };
        let actor = c.id;
        let meaningful: Vec<&Experience> = batch.iter().filter(|e| e.salience >= 0.2).collect();
        store.ensure_self(actor, &c.name).await?;
        let fmt = self.fmt_time();
        let recalled = self.recall_for(actor, &self.experience_cues(actor, &meaningful), 32, 6, "consolidate").await;
        let persona = match self.conn.db.persona().id().find(&actor) {
            Some(_) => self.persona_text(actor),
            None => format!("(played by a person: who they are shows only in what they do)\n{}", self.body_line(actor)).trim_end().to_string(),
        };
        let ctx = prompts::Ctx {
            name: &c.name,
            clock: fmt(llm::now_ms()),
            body: String::new(),
            persona,
            relations: self.relations(actor),
            mind: recalled.mind,
            memories: recalled.memories,
            judgments: recalled.judgments,
            places: self.places(actor, None),
            experiences: meaningful.iter().map(|e| format!("{}{}", self.exp_line(e, &fmt, true), self.lived_where(e))).collect(),
            dealings: self.dealings(actor),
            cues: None,
        };
        let msgs = vec![Msg { role: "system", content: prompts::internalize_system() }, Msg { role: "user", content: prompts::consolidate_user(&ctx, "") }];
        let known = meaningful.iter().map(|e| e.id).collect();
        Ok(Prepared { actor, name: c.name.clone(), upto, batch, known, msgs, reason })
    }

    async fn lived_advance(&self, actor: u32, upto: u64) -> Result<()> {
        if let Some(store) = &self.store {
            store.set_lived_upto(actor, upto, llm::now_ms()).await?;
        }
        let mut l = self.lived.lock().unwrap();
        if let Some(p) = l.players.get_mut(&actor) {
            p.cursor = Some(p.cursor.unwrap_or(0).max(upto));
            p.exps.retain(|k, _| *k > upto);
        }
        Ok(())
    }

    async fn lived_finish(&self, prep: Prepared, reply: llm::Reply, mode: &str) -> Result<()> {
        let Some(store) = &self.store else { return Ok(()) };
        let v = llm::parse_json(&reply.content)?;
        let now = llm::now_ms();
        let actor = prep.actor;
        let thought_ref = reference(actor, "internalize");
        let batch = &prep.batch;
        let lookup = |id: u64| batch.iter().find(|e| e.id == id).map(|e| (e.at_ms, e.salience as f64, self.anchors(e)));
        let (mut patch, mut notes) = memory::patch_from(&v, &prep.known, &lookup);
        // A player's character keeps no attention cues: its eyes are the player's.
        memory::sugar_into(&memory::without_notice(&v, false), &mut patch, &prep.known);
        notes.extend(self.canonical_people(actor, &mut patch));
        self.keep_refused_merges(actor, &notes);
        notes.extend(self.perceived_people_only(actor, batch, &mut patch));
        let told = |id: u64| batch.iter().find(|e| e.id == id).map(|e| matches!(e.kind.as_str(), "speech" | "whisper" | "read").then_some(e.subject));
        memory::attribute(&mut patch, actor, &told);
        self.name_people(actor, &mut patch);
        patch.lived_under = Some("human".into());
        let renamed = self.people_names(actor, batch, &patch);
        store.apply(actor, &patch, &thought_ref, now).await?;
        store.rename_people(actor, &renamed).await?;
        // Who the person shows themselves to be, read from their conduct (docs/PLAYER_MEMORY.md):
        // only a real change becomes a new version of the identity.
        let identity = match &v["identity"] {
            Value::Object(p) if p.get("narrative").and_then(|n| n.as_str()).is_some_and(|n| !n.is_empty()) && self.persona_changed(actor, p) => Some(p.clone()),
            _ => None,
        };
        if let Some(p) = &identity {
            let version = self.conn.db.persona().id().find(&actor).map(|x| x.version + 1).unwrap_or(1);
            store.set_identity(actor, version, &Value::Object(p.clone()), p.get("why").and_then(|w| w.as_str()).unwrap_or_default(), &thought_ref, now).await?;
        }
        self.lived_advance(actor, prep.upto).await?;
        let summary = v["summary"].as_str().unwrap_or_default().to_string();
        log::info!(
            "{} internalized {} lived experiences ({}, {mode}; +{} edges, -{} retracted, {} memories): {summary}",
            prep.name,
            prep.known.len(),
            prep.reason,
            patch.edges.len(),
            patch.retract.len(),
            patch.remember.len()
        );
        let thought = ThoughtIn {
            kind: "internalize".into(),
            summary,
            detail: json!({"lived_under": "human", "reason": prep.reason, "mode": mode, "experiences": prep.known, "upto": prep.upto, "reply": v, "patch": patch, "notes": notes}).to_string(),
            latency_ms: reply.latency_ms,
            tokens: reply.tokens,
            model: reply.model,
            reference: thought_ref,
        };
        // Goals are intentions nobody perceived: the current ones stay.
        let persona = identity.map(|p| {
            let cur = self.conn.db.persona().id().find(&actor);
            PersonaIn {
                narrative: p.get("narrative").and_then(|x| x.as_str()).unwrap_or_default().into(),
                values: p.get("values").and_then(|x| x.as_array()).map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default(),
                goals: cur.as_ref().map(|c| c.goals.clone()).unwrap_or_default(),
                traits: p.get("traits").map(|t| t.to_string()).unwrap_or_else(|| "{}".into()),
                mood: p.get("mood").and_then(|x| x.as_str()).unwrap_or_default().into(),
                // What a person enjoys is theirs to show; kept as it was.
                pastimes: Vec::new(),
                calling: String::new(),
            }
        });
        // The graph is the memory; the projection is what the body and the observer read. An
        // authority that refuses it (an older module) leaves the memory in place.
        if let Err(e) = self.project(actor, persona, Some(thought)).await {
            log::warn!("projection for {} (played by a person) refused: {e:#}", prep.name);
        }
        Ok(())
    }

    /// People a lived integration may name: those its experiences involve or name, and those
    /// the character already has feelings about. Anything else under `person:<id>` is a model
    /// slip (in the 2026-11-09 run, GLM in batch mode wrote an experience id as the resident's
    /// id, which is a real islander's); its nodes and edges are dropped, with a note.
    fn perceived_people_only(&self, actor: u32, batch: &[Experience], patch: &mut memory::Patch) -> Vec<String> {
        let mut known: std::collections::HashSet<u32> = self.conn.db.relation().iter().filter(|r| r.actor == actor).map(|r| r.other).collect();
        for e in batch {
            known.extend([e.subject, e.object]);
            known.extend(self.named_people(actor, &e.text));
        }
        known.insert(actor);
        let stranger = |k: &str| k.strip_prefix("person:").and_then(|x| x.parse::<u32>().ok()).is_some_and(|id| !known.contains(&id));
        let mut dropped: Vec<String> = patch.nodes.iter().map(|n| n.key.clone()).chain(patch.edges.iter().flat_map(|e| [e.from.clone(), e.to.clone()])).filter(|k| stranger(k)).collect();
        dropped.sort();
        dropped.dedup();
        if dropped.is_empty() {
            return Vec::new();
        }
        patch.nodes.retain(|n| !stranger(&n.key));
        patch.edges.retain(|e| !stranger(&e.from) && !stranger(&e.to));
        patch.retract.retain(|r| !stranger(&r.0) && !stranger(&r.2));
        patch.merges.retain(|m| !stranger(&m.0) && !stranger(&m.1));
        for m in patch.remember.iter_mut() {
            m.involves.retain(|k| !stranger(k));
        }
        log::info!("{}: dropped {} (no one this character perceived)", self.name(actor), dropped.join(", "));
        dropped.into_iter().map(|k| format!("{k} dropped: no one this character perceived")).collect()
    }

    async fn internalize_one(&self, actor: u32, reason: &'static str) -> Result<()> {
        let Some(prep) = self.lived_prepare(actor, reason).await? else { return Ok(()) };
        let _slow = self.slow.acquire().await?;
        let reply = self.llm.chat_in_lane(&self.lived_profile(), crate::llm::Attention::OnStage, "internalize", &prep.name, &prep.msgs, Lane::Background).await?;
        self.lived_finish(prep, reply, "direct").await
    }

    /// Everyone due at once, as one provider batch job.
    async fn internalize_batch(&self, due: Vec<(u32, &'static str)>) {
        let mut prepared = HashMap::new();
        for (id, reason) in due {
            match self.lived_prepare(id, reason).await {
                Ok(Some(p)) => {
                    prepared.insert(format!("lived-{id}-{}", p.upto), p);
                }
                r => self.lived_done(id, r.map(|_| ())),
            }
        }
        if prepared.is_empty() {
            return;
        }
        let items: Vec<BatchItem> = prepared.iter().map(|(k, p)| BatchItem { id: k.clone(), actor: p.name.clone(), messages: p.msgs.iter().map(|m| Msg { role: m.role, content: m.content.clone() }).collect(), meta: serde_json::Value::Null }).collect();
        let _slow = self.slow.acquire().await;
        match self.llm.batch(&self.lived_profile(), crate::llm::Attention::OnStage, "internalize", items, self.lived_cfg.poll, self.lived_cfg.give_up).await {
            Ok(results) => {
                for (k, r) in results {
                    let Some(p) = prepared.remove(&k) else { continue };
                    let id = p.actor;
                    let r = match r {
                        Ok(reply) => self.lived_finish(p, reply, "batch").await,
                        Err(e) => Err(e),
                    };
                    self.lived_done(id, r);
                }
            }
            Err(e) => {
                for (_, p) in prepared {
                    self.lived_done(p.actor, Err(anyhow::anyhow!("{e:#}")));
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn exp(id: u64, at_ms: u64, salience: f32) -> Experience {
        Experience { id, observer: 1, controller: spacetimedb_sdk::Identity::ZERO, at_ms, kind: "act".into(), subject: 1, object: 0, x: 0.0, y: 0.0, text: String::new(), salience }
    }

    fn cfg() -> Config {
        Config { on: true, buffer: 3, cap: 5, every: None, takeover_wait: Duration::from_secs(120), take: 120, profile: None, batch: false, poll: Duration::from_secs(1), give_up: Duration::from_secs(1) }
    }

    #[test]
    fn cadence_waits_for_a_reason() {
        let day = Duration::from_secs(720);
        let now = 1_000_000;
        let two = [exp(1, now - 1_000, 0.5), exp(2, now - 500, 0.1)];
        // Recent, few, alive, present, within the day: wait.
        assert_eq!(reason_due(&cfg(), two.iter(), true, false, Duration::from_secs(60), day), None);
        // The character died: at once, whatever else holds.
        assert_eq!(reason_due(&cfg(), two.iter(), false, false, Duration::ZERO, day), Some("death"));
        // Its person left and the minds took it over: the session ended.
        assert_eq!(reason_due(&cfg(), two.iter(), true, true, Duration::from_secs(60), day), Some("session end"));
        // Only routine experiences still end with the session (the cursor moves past them).
        assert_eq!(reason_due(&cfg(), [exp(3, now, 0.05)].iter(), true, true, Duration::ZERO, day), Some("session end"));
        // A game day since the oldest arrived.
        assert_eq!(reason_due(&cfg(), two.iter(), true, false, day, day), Some("game day"));
        // Enough meaningful experiences, or enough in all.
        let full: Vec<Experience> = (0..3).map(|i| exp(i, now, 0.4)).collect();
        assert_eq!(reason_due(&cfg(), full.iter(), true, false, Duration::ZERO, day), Some("buffer"));
        let routine: Vec<Experience> = (0..5).map(|i| exp(i, now, 0.05)).collect();
        assert_eq!(reason_due(&cfg(), routine.iter(), true, false, Duration::ZERO, day), Some("buffer"));
        // Only routine experiences never start an integration by time alone.
        assert_eq!(reason_due(&cfg(), routine[..2].iter(), true, false, day, day), None);
        assert_eq!(reason_due(&cfg(), [].iter(), false, true, day, day), None);
    }
}
