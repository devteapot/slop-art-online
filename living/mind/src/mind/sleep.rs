//! Sleep-like reorganization of a mind (purpose `reorganize`), at night.
//!
//! A mind that has integrated enough since it last slept tidies itself once a night: weak,
//! unreinforced beliefs fade, then the model merges duplicates, generalizes repeated
//! specifics, relabels and retracts (`prompts::reorganize_system`). The design and its
//! evidence are in docs/MIND_HARNESS.md (item 2) and docs/MODEL_COST.md (Part 2).
//!
//! `LIVING_REORGANIZE` chooses when:
//!
//! - `night-batch` (the default): during the world's night (`LIVING_NIGHT`, default `20-6`,
//!   game hours from the `world` clock the service already subscribes to; the mind cannot see
//!   the body's sleep), everyone due goes out together as one provider batch job per route
//!   (`llm::Llm::batch`, half price, an uploaded file above about 2.4 MB). Later arrivals in the
//!   same night go in another job, at most one per `LIVING_REORGANIZE_BATCH_GAP_S` (60 s).
//!   People in a job are marked consolidating, so no integration interleaves; a job not done
//!   within `LIVING_REORGANIZE_GIVE_UP_S` (a game day) is cancelled and its people go direct
//!   the next night.
//! - `night`: the same rule, one direct call each.
//! - `timer`: as before 2026-11-09: whenever a rested mind has nothing salient to integrate.
//!   Consolidation preempts it, so in a busy town it is rare (28–46 of about 71 people in
//!   4–6 h on aske-coast).
//!
//! Due, at night: at least `LIVING_REORGANIZE_MIN` integrations (2) since the last sleep and
//! `LIVING_REORGANIZE_GAP_S` (1,200 s) since it, at most once a night. Animals only fade (they
//! have no reorganization prompt), on the same rule.

use super::{reference, Minds};
use crate::llm::{self, Attention, BatchItem, Lane, Msg, Reply};
use crate::{memory, prompts};
use anyhow::{anyhow, Result};
use living_bindings::*;
use serde_json::json;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Timer,
    Night,
    NightBatch,
}

#[derive(Clone, Debug)]
pub struct Config {
    pub mode: Mode,
    /// Game hours of the night: from `dusk` to `dawn` (wrapping midnight).
    pub dusk: f32,
    pub dawn: f32,
    pub min_integrations: u32,
    pub min_gap: Duration,
    pub batch_gap: Duration,
    pub poll: Duration,
    pub give_up: Option<Duration>,
}

fn env<T: std::str::FromStr>(k: &str) -> Option<T> {
    std::env::var(k).ok().and_then(|v| v.trim().parse().ok())
}

impl Config {
    pub fn from_env() -> Self {
        let mode = match std::env::var("LIVING_REORGANIZE").as_deref() {
            Ok("timer") => Mode::Timer,
            Ok("night") => Mode::Night,
            _ => Mode::NightBatch,
        };
        let (dusk, dawn) = std::env::var("LIVING_NIGHT")
            .ok()
            .and_then(|v| v.split_once('-').and_then(|(a, b)| Some((a.trim().parse().ok()?, b.trim().parse().ok()?))))
            .unwrap_or((20.0, 6.0));
        Self {
            mode,
            dusk,
            dawn,
            min_integrations: env("LIVING_REORGANIZE_MIN").unwrap_or(2),
            min_gap: Duration::from_secs(env("LIVING_REORGANIZE_GAP_S").unwrap_or(1200)),
            batch_gap: Duration::from_secs(env("LIVING_REORGANIZE_BATCH_GAP_S").unwrap_or(60)),
            poll: Duration::from_secs(env("LIVING_REORGANIZE_POLL_S").unwrap_or(10)),
            give_up: env::<u64>("LIVING_REORGANIZE_GIVE_UP_S").map(Duration::from_secs),
        }
    }
}

/// The night a game time falls in: the day it began on, while the hour is between dusk and
/// dawn (`None` by day).
pub fn night_of(t: u64, epoch: u64, day_ms: u64, dusk: f32, dawn: f32) -> Option<u64> {
    let h = living_rules::hour_of(t, epoch, day_ms);
    let day = living_rules::day_of(t, epoch, day_ms);
    let wraps = dusk > dawn;
    if wraps {
        if h >= dusk {
            Some(day)
        } else if h < dawn {
            Some(day.saturating_sub(1))
        } else {
            None
        }
    } else {
        (h >= dusk && h < dawn).then_some(day)
    }
}

/// Whether a mind is due to sleep on it tonight.
pub fn due(cfg: &Config, since_sleep: u32, last_sleep: Option<Instant>, slept: Option<u64>, night: u64) -> bool {
    slept != Some(night) && since_sleep >= cfg.min_integrations && last_sleep.is_none_or(|t| t.elapsed() >= cfg.min_gap)
}

/// A reorganization ready to send: the person's route and messages, and what the result is
/// measured against.
pub(super) struct Prep {
    actor: u32,
    name: String,
    route: String,
    at: Attention,
    msgs: Vec<Msg>,
    nodes: i64,
    edges: i64,
    faded: i64,
    now: u64,
}

impl Minds {
    /// The current night, by the world's clock (`None` by day or before the world exists).
    fn night(&self) -> Option<u64> {
        let w = self.conn.db.world().id().find(&0)?;
        night_of(llm::now_ms(), w.epoch_ms, w.day_ms, self.sleep_cfg.dusk, self.sleep_cfg.dawn)
    }

    /// At night, start the sleep of every mind that is due (see the module docs).
    pub(super) fn check_sleep(self: Arc<Self>) {
        if self.sleep_cfg.mode == Mode::Timer {
            return;
        }
        let Some(night) = self.night() else { return };
        let batch = self.sleep_cfg.mode == Mode::NightBatch;
        if batch && self.sleep_batch_at.lock().unwrap().is_some_and(|t| t.elapsed() < self.sleep_cfg.batch_gap) {
            return;
        }
        let mut people = Vec::new();
        let mut direct = Vec::new();
        let mut eligible = 0;
        let mine = self.mine();
        {
            let mut a = self.actors.lock().unwrap();
            for c in &mine {
                let m = a.entry(c.id).or_default();
                if !due(&self.sleep_cfg, m.since_sleep, m.last_sleep, m.slept_night, night) {
                    continue;
                }
                eligible += 1;
                if m.consolidating || m.retry_after.is_some_and(|t| Instant::now() < t) {
                    continue;
                }
                m.consolidating = true;
                m.slept_night = Some(night);
                if c.kind == "person" && batch && !std::mem::take(&mut m.direct_next) {
                    people.push(c.id);
                } else {
                    direct.push(c.id);
                }
            }
        }
        if people.is_empty() && direct.is_empty() {
            return;
        }
        log::info!("night {night}: {} of {} minds go to sleep ({} in a batch, {} direct; {eligible} due)", people.len() + direct.len(), mine.len(), people.len(), direct.len());
        for actor in direct {
            let this = self.clone();
            tokio::spawn(async move {
                let r = this.reorganize(actor).await;
                this.slept(actor, r, false);
            });
        }
        if !people.is_empty() {
            *self.sleep_batch_at.lock().unwrap() = Some(Instant::now());
            let this = self.clone();
            tokio::spawn(async move { this.reorganize_batch(night, people).await });
        }
    }

    /// The end of a sleep (or of a consolidation's reorganization under the timer).
    pub(super) fn slept(&self, actor: u32, r: Result<()>, batch: bool) {
        let mut a = self.actors.lock().unwrap();
        let m = a.entry(actor).or_default();
        m.consolidating = false;
        match r {
            Ok(()) => {
                log::info!("sleep: {} slept ({}, night {:?}, after {} integrations)", self.name(actor), if batch { "batch" } else { "direct" }, self.night(), m.since_sleep);
                m.since_sleep = 0;
                m.last_sleep = Some(Instant::now());
                m.failures = 0;
                m.retry_after = None;
                m.last_consolidated = Some(Instant::now());
            }
            Err(e) => {
                m.failures += 1;
                m.retry_after = Some(Instant::now() + Duration::from_secs(20 * m.failures as u64));
                // A batch that failed goes direct next time.
                m.direct_next = batch;
                log::warn!("sleep for {} failed ({}x): {e:#}", self.name(actor), m.failures);
            }
        }
    }

    /// Fade, then build the reorganization request (`None`: the mind is too small to need
    /// one, or the character is an animal; fading was enough).
    pub(super) async fn sleep_prepare(&self, actor: u32) -> Result<Option<Prep>> {
        let Some(store) = &self.store else { return Ok(None) };
        let Some(c) = self.conn.db.character().id().find(&actor) else { return Ok(None) };
        let now = llm::now_ms();
        let faded = store.fade(actor, 0.2, now).await?;
        let (nodes, edges) = store.size(actor).await?;
        if edges < 25 || c.kind != "person" {
            log::info!("{} rested (mind small: {nodes} concepts, {edges} links; {faded} faded)", c.name);
            return Ok(None);
        }
        let fmt = self.fmt_time();
        let concepts = store.concepts(actor, 60).await?;
        let facts = store.around(actor, &[], 120).await?;
        let lines: Vec<String> = facts.iter().map(|f| memory::render_keys(f, &fmt)).collect();
        let msgs = vec![
            Msg { role: "system", content: prompts::reorganize_system() },
            Msg { role: "user", content: prompts::reorganize_user(&c.name, &self.persona_text(actor), &concepts, &lines) },
        ];
        Ok(Some(Prep { actor, name: c.name.clone(), route: self.profile(&c), at: self.attention(actor, None), msgs, nodes, edges, faded, now }))
    }

    /// Apply a reorganization reply to the person's mind.
    pub(super) async fn sleep_finish(&self, prep: Prep, reply: Reply, how: &str) -> Result<()> {
        let Some(store) = &self.store else { return Ok(()) };
        let actor = prep.actor;
        let v = llm::parse_json(&reply.content)?;
        let known: Vec<u64> = self.experiences(actor).iter().map(|e| e.id).collect();
        let (mut patch, notes) = memory::patch_from(&v, &known, &|_| None);
        memory::sugar_into(&json!({"judgments": v["judgments"]}), &mut patch, &[]);
        self.canonical_people(&mut patch);
        let thought_ref = reference(actor, "reorganize");
        store.apply(actor, &patch, &thought_ref, prep.now).await?;
        let (nodes2, edges2) = store.size(actor).await?;
        let (nodes, edges, faded) = (prep.nodes, prep.edges, prep.faded);
        let summary = format!(
            "{} (mind {nodes}→{nodes2} concepts, {edges}→{edges2} links; {} merged, {} retracted, {} generalized, {faded} faded)",
            v["summary"].as_str().unwrap_or("I rested and my thoughts settled."),
            patch.merges.len(),
            patch.retract.len(),
            patch.edges.len()
        );
        log::info!("{} slept on it ({how}): {summary}", prep.name);
        let thought = ThoughtIn {
            kind: "reorganize".into(),
            summary,
            detail: json!({"reply": v, "patch": patch, "notes": notes, "faded": faded, "how": how}).to_string(),
            latency_ms: reply.latency_ms,
            tokens: reply.tokens,
            model: reply.model,
            reference: thought_ref,
        };
        self.project(actor, None, Some(thought)).await
    }

    /// Sleep-like reorganization of one mind, as one direct call.
    pub(super) async fn reorganize(&self, actor: u32) -> Result<()> {
        let Some(prep) = self.sleep_prepare(actor).await? else { return Ok(()) };
        let _slow = self.slow.acquire().await?;
        let reply = self.llm.chat_in_lane(&prep.route, prep.at, "reorganize", &prep.name, &prep.msgs, Lane::Background).await?;
        self.sleep_finish(prep, reply, "direct").await
    }

    /// Everyone due tonight, as one provider batch job per route.
    async fn reorganize_batch(&self, night: u64, people: Vec<u32>) {
        let started = Instant::now();
        let mut by_route: HashMap<(String, Attention), Vec<Prep>> = HashMap::new();
        for actor in people {
            match self.sleep_prepare(actor).await {
                Ok(Some(p)) => by_route.entry((p.route.clone(), p.at)).or_default().push(p),
                r => self.slept(actor, r.map(|_| ()), false),
            }
        }
        let give_up = self.sleep_cfg.give_up.unwrap_or_else(|| {
            let day = self.conn.db.world().id().find(&0).map(|w| w.day_ms).unwrap_or(living_rules::DEFAULT_DAY_MS);
            Duration::from_millis(day)
        });
        for ((route, at), preps) in by_route {
            let n = preps.len();
            let items: Vec<BatchItem> = preps.iter().map(|p| BatchItem { id: format!("sleep-{}-{night}", p.actor), actor: p.name.clone(), messages: p.msgs.iter().map(|m| Msg { role: m.role, content: m.content.clone() }).collect() }).collect();
            let mut preps: HashMap<String, Prep> = preps.into_iter().map(|p| (format!("sleep-{}-{night}", p.actor), p)).collect();
            match self.llm.batch(&route, at, "reorganize", items, self.sleep_cfg.poll, give_up).await {
                Ok(results) => {
                    let mut ok = 0;
                    for (k, r) in results {
                        let Some(p) = preps.remove(&k) else { continue };
                        let actor = p.actor;
                        let r = match r {
                            Ok(reply) => self.sleep_finish(p, reply, "batch").await,
                            Err(e) => Err(e),
                        };
                        ok += usize::from(r.is_ok());
                        self.slept(actor, r, true);
                    }
                    log::info!("night {night}: batch of {n} reorganizations on {route} done in {:.0} s, {ok} applied", started.elapsed().as_secs_f64());
                }
                Err(e) => {
                    log::warn!("night {night}: batch of {n} reorganizations on {route} failed after {:.0} s: {e:#}", started.elapsed().as_secs_f64());
                    for (_, p) in preps {
                        self.slept(p.actor, Err(anyhow!("{e:#}")), true);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg() -> Config {
        Config { mode: Mode::NightBatch, dusk: 20.0, dawn: 6.0, min_integrations: 2, min_gap: Duration::from_secs(1200), batch_gap: Duration::from_secs(60), poll: Duration::from_secs(1), give_up: None }
    }

    #[test]
    fn nights_span_midnight_and_belong_to_the_day_they_began() {
        let day = 720_000;
        // The world starts at 07:00 of day 1.
        let at = |d: u64, h: f64| (((d - 1) as f64 * 24.0 + h - 7.0) / 24.0 * day as f64) as u64;
        assert_eq!(night_of(at(3, 12.0), 0, day, 20.0, 6.0), None, "noon");
        assert_eq!(night_of(at(3, 20.5), 0, day, 20.0, 6.0), Some(3), "after dusk");
        assert_eq!(night_of(at(4, 2.0), 0, day, 20.0, 6.0), Some(3), "after midnight, still the night of day 3");
        assert_eq!(night_of(at(4, 6.5), 0, day, 20.0, 6.0), None, "after dawn");
        assert_eq!(night_of(at(4, 1.0), 0, day, 0.0, 5.0), Some(4), "a night that does not wrap");
    }

    #[test]
    fn due_once_a_night_after_enough_integrations_and_time() {
        let c = cfg();
        assert!(due(&c, 2, None, None, 3));
        assert!(!due(&c, 1, None, None, 3), "one integration is not enough");
        assert!(!due(&c, 5, None, Some(3), 3), "once a night");
        assert!(due(&c, 5, None, Some(2), 3));
        assert!(!due(&c, 5, Some(Instant::now()), None, 3), "twenty minutes since the last");
    }
}
